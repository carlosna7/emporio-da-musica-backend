"""Gera conversas reproduzíveis com o agente real, sem editar as respostas."""

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.agent import criar_agente
from app.cli import abrir_banco, configurar_utf8, formatar_custo
from app.config import Config, carregar_config
from app.db import CAMINHO_BANCO
from app.horario import DIAS_SEMANA, situacao_loja
from app.llm.base import LLMClient, LLMError, LLMResponse, Message, ToolCall, Usage, criar_cliente

PASTA_EXEMPLOS = Path(__file__).resolve().parents[1] / "examples"
PASTA_LOGS_EXEMPLOS = Path(__file__).resolve().parent / "logs" / "exemplos"
ERRO_INICIO = "Não consegui gerar os exemplos: {erro}"


@dataclass(frozen=True)
class Roteiro:
    nome: str
    titulo: str
    descricao: str
    agora: datetime
    mensagens: tuple[str, ...]


ROTEIROS: tuple[Roteiro, ...] = (
    Roteiro(
        "01-preco-pix-parcelamento", "Preço, PIX e parcelamento",
        'Preço com a busca no catálogo, o PIX calculado pela ferramenta, a memória da conversa '
        '("e no PIX?") e a política de parcelamento.',
        datetime(2026, 11, 3, 10),
        (
            "Oi! Quanto custa o Takamine GD20?",
            "E no PIX, quanto fica?",
            "E se eu parcelar no cartão, dá pra fazer em 12x?",
        ),
    ),
    Roteiro(
        "02-arrependimento-no-prazo", "Arrependimento dentro do prazo",
        "O Emilio pede o número do pedido e o e-mail antes de consultar, confere a entrega "
        "e aplica o prazo de 7 dias do direito de arrependimento.",
        datetime(2026, 1, 22, 10),
        (
            "Oi, comprei um violão com vocês e me arrependi. Ainda dá pra devolver?",
            "É o pedido 5, e-mail rafael.pereira@jmail.com",
            "E o frete da devolução fica por minha conta? Como recebo o dinheiro de volta?",
        ),
    ),
    Roteiro(
        "03-catalogo-e-indisponiveis", "Catálogo e produtos indisponíveis",
        "Busca com faixa de preço e os três casos de produto que existe mas não pode ser "
        "comprado: esgotado, descontinuado e pré-lançamento.",
        datetime(2026, 11, 3, 15),
        (
            "Quais violões vocês têm disponíveis até R$ 1000?",
            "E o Giannini GF-3D, vocês têm?",
            "E o Shelby SN-7C de 7 cordas?",
            "Por último: o ukulele Kala KA-ABP-CTG barítono já está à venda?",
        ),
    ),
    Roteiro(
        "04-fora-do-escopo", "Fora do escopo e domingo",
        "Acessório redirecionado para instrumentos, assunto alheio recusado com gentileza "
        "e a volta ao catálogo, num domingo com a loja fechada.",
        datetime(2026, 11, 8, 15),
        (
            "Oi! Vocês vendem cordas de violão?",
            "Ah, beleza. E quem ganhou o jogo do Flamengo ontem?",
            "Haha, justo. Então quais ukuleles estão em promoção?",
        ),
    ),
    Roteiro(
        "05-atendente-humano", "Pedido de atendente humano",
        "O Emilio tenta entender o problema uma vez, encaminha quando o cliente insiste "
        "e responde o endereço pelos contatos oficiais.",
        datetime(2026, 11, 4, 10),
        (
            "Quero falar com uma pessoa.",
            "Prefiro falar com um atendente humano mesmo, por favor.",
            "Valeu! E qual o endereço da loja, caso eu queira passar aí?",
        ),
    ),
)


@dataclass
class TurnoExemplo:
    mensagem: str
    texto: str
    chamadas: list[ToolCall]
    status: str
    usage: Usage
    custo_usd: float | None


class GravadorLLM:
    """Guarda as chamadas pedidas pelo modelo, na ordem, com seus argumentos."""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.chamadas: list[ToolCall] = []

    def chat(self, system, messages, tools) -> LLMResponse:
        resposta = self.llm.chat(system, messages, tools)
        self.chamadas.extend(resposta.tool_calls)
        return resposta


def gerar_conversa(
    roteiro: Roteiro, *, config: Config, conexao: sqlite3.Connection,
    pasta_logs: Path, llm: LLMClient,
) -> list[TurnoExemplo]:
    gravador = GravadorLLM(llm)
    agente = criar_agente(
        config=config, llm=gravador, conexao=conexao, pasta_logs=pasta_logs, agora=roteiro.agora,
    )
    historico: list[Message] = []
    turnos = []
    conversa_id = f"exemplo-{roteiro.nome}"
    for mensagem in roteiro.mensagens:
        antes = len(gravador.chamadas)
        resposta = agente.responder(historico, mensagem, conversa_id)
        historico.extend(resposta.para_historico)
        turnos.append(TurnoExemplo(
            mensagem, resposta.texto, gravador.chamadas[antes:], resposta.status,
            resposta.usage, resposta.custo_usd,
        ))
    return turnos


def formatar_chamada(chamada: ToolCall) -> str:
    argumentos = ", ".join(
        f"{chave}={json.dumps(valor, ensure_ascii=False)}"
        for chave, valor in chamada.arguments.items()
    )
    return f"{chamada.name}({argumentos})"


def citar(texto: str) -> str:
    return "\n".join(
        f"> {linha}" if linha.strip() else ">" for linha in texto.strip().splitlines()
    ) or ">"


def somar_custos(turnos: Sequence[TurnoExemplo]) -> float | None:
    if any(turno.custo_usd is None for turno in turnos):
        return None
    return round(sum(turno.custo_usd for turno in turnos), 6)


def montar_markdown(
    roteiro: Roteiro, turnos: list[TurnoExemplo], *, config: Config, quando: datetime,
) -> str:
    agora = roteiro.agora
    entrada = sum(t.usage.input_tokens for t in turnos)
    cache = sum(t.usage.cached_tokens for t in turnos)
    saida = sum(t.usage.output_tokens for t in turnos)
    partes = [
        f"# {roteiro.titulo}", roteiro.descricao,
        (
            f"- **Data simulada:** {DIAS_SEMANA[agora.weekday()]}, {agora:%d/%m/%Y}, "
            f"{agora:%H:%M} (horário de Campo Grande/MS). {situacao_loja(agora)}\n"
            f"- **Modelo:** {config.provider} · {config.model} · esforço "
            f"{config.reasoning_effort or 'none'}\n"
            f"- **Uso:** {len(turnos)} turnos · {entrada} tokens de entrada ({cache} em cache) · "
            f"{saida} de saída · custo estimado {formatar_custo(somar_custos(turnos))}\n"
            f"- **Gerado em:** {quando:%d/%m/%Y %H:%M} por `python -m evals.exemplos` "
            f"(conversa `exemplo-{roteiro.nome}`), sem edição manual"
        ),
        "## Conversa",
    ]
    for turno in turnos:
        chamadas = ", ".join(f"`{formatar_chamada(c)}`" for c in turno.chamadas) or "nenhuma"
        status = f" · status: `{turno.status}`" if turno.status != "ok" else ""
        partes.extend([
            f"**Cliente:** {turno.mensagem}", "**Emilio:**", citar(turno.texto),
            f"Ferramentas: {chamadas}{status}",
        ])
    return "\n\n".join(partes) + "\n"


def gerar_exemplos(
    roteiros: Sequence[Roteiro], *, config: Config, conexao: sqlite3.Connection,
    pasta_logs: Path, pasta_saida: Path, llm: LLMClient, quando: datetime,
    escrever: Callable[[str], None] = print,
) -> list[Path]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminhos = []
    todos_turnos = []
    for indice, roteiro in enumerate(roteiros, start=1):
        turnos = gerar_conversa(
            roteiro, config=config, conexao=conexao, pasta_logs=pasta_logs, llm=llm,
        )
        caminho = pasta_saida / f"{roteiro.nome}.md"
        caminho.write_text(
            montar_markdown(roteiro, turnos, config=config, quando=quando), encoding="utf-8",
        )
        caminhos.append(caminho)
        todos_turnos.extend(turnos)
        aviso = ""
        falhos = ", ".join(str(i) for i, turno in enumerate(turnos, 1) if turno.status != "ok")
        if falhos:
            aviso = f" · ATENÇÃO: turno(s) {falhos} sem status ok"
        escrever(
            f"[{indice}/{len(roteiros)}] {roteiro.nome}: {len(turnos)} turnos · "
            f"custo estimado {formatar_custo(somar_custos(turnos))}{aviso}"
        )
    escrever(
        f"Total: {len(todos_turnos)} turnos · "
        f"custo estimado {formatar_custo(somar_custos(todos_turnos))}"
    )
    return caminhos


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evals.exemplos",
        description=("Gera as conversas de exemplo em examples/ com o agente e o LLM "
                     "configurados no .env."),
    )
    parser.parse_args(argv)
    configurar_utf8()
    try:
        config = carregar_config()
        llm = criar_cliente(config.provider, config.model, reasoning_effort=config.reasoning_effort)
        conexao = abrir_banco(CAMINHO_BANCO)
    except (LLMError, ValueError) as erro:
        print(ERRO_INICIO.format(erro=erro), file=sys.stderr)
        sys.exit(1)
    with closing(conexao):
        gerar_exemplos(
            ROTEIROS, config=config, conexao=conexao, pasta_logs=PASTA_LOGS_EXEMPLOS,
            pasta_saida=PASTA_EXEMPLOS, llm=llm, quando=datetime.now(),
        )


if __name__ == "__main__":
    main()
