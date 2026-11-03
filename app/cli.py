"""Interface de conversa no terminal."""

import argparse
import io
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from app.agent import Resposta, criar_agente
from app.db import CAMINHO_BANCO, conectar
from app.ingest import criar_banco
from app.llm.base import LLMError, Message

BOAS_VINDAS = (
    "Emilio: Oi! Eu sou o Emilio, atendente virtual da Empório da Música. "
    "Posso ajudar com instrumentos, preços, pedidos e políticas da loja."
)
COMANDOS = "Comandos: /nova começa outra conversa; sair ou /sair encerra."
PROMPT_ENTRADA = "Você: "
PREFIXO_RESPOSTA = "Emilio: "
NOVA_CONVERSA = "(nova conversa: o Emilio não lembra mais das mensagens anteriores)"
DESPEDIDA = "Emilio: Até mais! Quando precisar, é só chamar."
CRIANDO_BANCO = "Criando o banco de dados a partir dos CSVs (só na primeira execução)..."
ERRO_INICIO = (
    "Não consegui iniciar o Emilio: {erro}\n"
    "Confira o arquivo .env (se ainda não existe, copie o .env.example "
    "e preencha a chave do provedor)."
)


def gerar_conversa_id() -> str:
    return f"cli-{uuid4().hex[:8]}"


def formatar_custo(custo: float | None) -> str:
    return "n/d" if custo is None else f"US$ {custo:.6f}"


def linha_ferramentas(tools_usadas: list[str]) -> str:
    return f"[ferramentas: {', '.join(tools_usadas) if tools_usadas else 'nenhuma'}]"


def linha_debug(resposta: Resposta, conversa_id: str) -> str:
    u = resposta.usage
    return (
        f"[debug: {resposta.status} | {resposta.iteracoes} chamada(s) ao LLM | "
        f"tokens: {u.input_tokens} entrada ({u.cached_tokens} em cache), {u.output_tokens} saída "
        f"| custo: {formatar_custo(resposta.custo_usd)} | conversa: {conversa_id}]"
    )


def executar(
    agente,
    ler: Callable[[str], str] = input,
    escrever: Callable[[str], None] = print,
    debug: bool = False,
    novo_id: Callable[[], str] = gerar_conversa_id,
) -> int:
    historico: list[Message] = []
    conversa_id = novo_id()
    turnos = 0
    custo_total: float | None = 0.0
    escrever(BOAS_VINDAS)
    escrever(COMANDOS)
    escrever("")
    try:
        while True:
            entrada = ler(PROMPT_ENTRADA).strip()
            if not entrada:
                continue
            comando = entrada.lower()
            if comando in ("sair", "/sair"):
                break
            if comando == "/nova":
                historico = []
                conversa_id = novo_id()
                escrever(NOVA_CONVERSA)
                escrever("")
                continue
            if comando.startswith("/"):
                escrever(COMANDOS)
                escrever("")
                continue
            resposta = agente.responder(historico, entrada, conversa_id)
            historico.extend(resposta.para_historico)
            turnos += 1
            if custo_total is None or resposta.custo_usd is None:
                custo_total = None
            else:
                custo_total += resposta.custo_usd
            escrever(PREFIXO_RESPOSTA + resposta.texto)
            escrever(linha_ferramentas(resposta.tools_usadas))
            if debug:
                escrever(linha_debug(resposta, conversa_id))
            escrever("")
    except (EOFError, KeyboardInterrupt):
        escrever("")
    escrever(DESPEDIDA)
    if debug:
        escrever(
            f"[debug: {turnos} turno(s) nesta sessão, custo total {formatar_custo(custo_total)}]"
        )
    return 0


def abrir_banco(caminho: Path, escrever: Callable[[str], None] = print) -> sqlite3.Connection:
    if not caminho.exists():
        escrever(CRIANDO_BANCO)
        criar_banco(destino=caminho)
    return conectar(caminho)


def configurar_utf8() -> None:
    for fluxo in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(fluxo, io.TextIOWrapper):
            fluxo.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Converse com o Emilio, o atendente virtual da Empório da Música.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="mostra status, tokens e custo estimado de cada resposta",
    )
    args = parser.parse_args(argv)
    configurar_utf8()
    try:
        agente = criar_agente(conexao=abrir_banco(CAMINHO_BANCO))
    except (LLMError, ValueError) as erro:
        print(ERRO_INICIO.format(erro=erro), file=sys.stderr)
        sys.exit(1)
    sys.exit(executar(agente, ler=input, escrever=print, debug=args.debug))


if __name__ == "__main__":
    main()
