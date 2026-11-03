"""Validação dos casos e avaliação determinística das respostas."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.cli import formatar_custo
from app.config import Config
from app.db import normalizar
from app.llm.base import Usage
from app.tools import TOOLS

CATEGORIAS = ("produtos", "pedidos", "politicas", "escopo", "encaminhamento", "horario", "memoria")
CHAVES_ESPERA = ("tools", "tools_proibidas", "contem", "contem_algum", "nao_contem")
ARQUIVO_CASOS = Path(__file__).resolve().parent / "casos.json"
CHAVES_CASO = {"id", "categoria", "descricao", "agora", "turnos", "espera"}


@dataclass(frozen=True)
class Espera:
    tools: tuple[str, ...] = ()
    tools_proibidas: tuple[str, ...] = ()
    contem: tuple[str, ...] = ()
    contem_algum: tuple[tuple[str, ...], ...] = ()
    nao_contem: tuple[str, ...] = ()


@dataclass(frozen=True)
class Caso:
    id: str
    categoria: str
    descricao: str
    agora: datetime
    turnos: tuple[str, ...]
    espera: tuple[Espera | None, ...]


def _texto_valido(valor: object) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def _lista_textos(valor: object, campo: str) -> tuple[str, ...]:
    if not isinstance(valor, list) or not valor or not all(map(_texto_valido, valor)):
        raise ValueError(f"{campo} deve ser uma lista não vazia de textos não vazios")
    return tuple(valor)


def _ler_espera(dados: object) -> Espera | None:
    if dados is None:
        return None
    if not isinstance(dados, dict) or not dados or dados.keys() - set(CHAVES_ESPERA):
        raise ValueError("expectativa deve ter pelo menos uma chave válida")

    campos = {}
    for chave, valor in dados.items():
        if chave == "contem_algum":
            if not isinstance(valor, list) or not valor:
                raise ValueError("contem_algum deve ser uma lista não vazia de grupos")
            campos[chave] = tuple(_lista_textos(grupo, chave) for grupo in valor)
        else:
            campos[chave] = _lista_textos(valor, chave)

    espera = Espera(**campos)
    exigidas = set(espera.tools)
    proibidas = set(espera.tools_proibidas)
    desconhecidas = (exigidas | proibidas) - TOOLS.keys()
    if desconhecidas:
        raise ValueError(f"tools desconhecidas: {', '.join(sorted(desconhecidas))}")
    if exigidas & proibidas:
        raise ValueError("tools e tools_proibidas não podem ter nomes em comum")
    return espera


def _ler_caso(dados: object, id_caso: str | None, ids: set[str]) -> Caso:
    if not isinstance(dados, dict) or dados.keys() != CHAVES_CASO:
        raise ValueError("chaves do caso incorretas")
    if id_caso is None:
        raise ValueError("id inválido")
    if id_caso in ids:
        raise ValueError("id repetido")
    if dados["categoria"] not in CATEGORIAS:
        raise ValueError("categoria inválida")
    if not _texto_valido(dados["descricao"]):
        raise ValueError("descricao deve ser um texto não vazio")

    data = dados["agora"]
    if not isinstance(data, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", data):
        raise ValueError("agora deve seguir AAAA-MM-DDTHH:MM")
    agora = datetime.fromisoformat(data)
    turnos = _lista_textos(dados["turnos"], "turnos")
    expectativas = dados["espera"]
    if not isinstance(expectativas, list) or len(expectativas) != len(turnos):
        raise ValueError("espera deve ter um item por turno")
    if expectativas[-1] is None:
        raise ValueError("a última expectativa não pode ser null")
    return Caso(
        id_caso, dados["categoria"], dados["descricao"], agora, turnos,
        tuple(_ler_espera(item) for item in expectativas),
    )


def carregar_casos(caminho: Path = ARQUIVO_CASOS) -> list[Caso]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise ValueError(f"casos.json, caso #0: {erro}") from erro
    if not isinstance(dados, list):
        raise ValueError("casos.json, caso #0: a raiz deve ser uma lista")

    casos = []
    ids: set[str] = set()
    for indice, item in enumerate(dados, start=1):
        id_caso = item.get("id") if isinstance(item, dict) else None
        if not isinstance(id_caso, str) or not re.fullmatch(r"[a-z0-9-]+", id_caso):
            id_caso = None
        try:
            caso = _ler_caso(item, id_caso, ids)
        except ValueError as erro:
            ident = id_caso or f"#{indice}"
            raise ValueError(f"casos.json, caso {ident}: {erro}") from erro
        casos.append(caso)
        ids.add(caso.id)
    return casos


def normalizar_texto(texto: str) -> str:
    texto = " ".join(normalizar(texto).split())
    texto = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", texto)
    return re.sub(r"(?<=\d) %", "%", texto)


def verificar(espera: Espera | None, texto: str, tools_usadas: list[str], status: str) -> list[str]:
    falhas = [] if status == "ok" else [f"status: {status}"]
    if espera is None:
        return falhas

    falhas.extend(f"tool não chamada: {nome}" for nome in espera.tools if nome not in tools_usadas)
    falhas.extend(
        f"tool proibida chamada: {nome}" for nome in espera.tools_proibidas if nome in tools_usadas
    )
    texto_normalizado = normalizar_texto(texto)
    falhas.extend(
        f'falta: "{s}"' for s in espera.contem if normalizar_texto(s) not in texto_normalizado
    )
    for grupo in espera.contem_algum:
        if not any(normalizar_texto(s) in texto_normalizado for s in grupo):
            falhas.append("nenhuma de: " + " | ".join(f'"{s}"' for s in grupo))
    falhas.extend(
        f'não devia conter: "{s}"'
        for s in espera.nao_contem if normalizar_texto(s) in texto_normalizado
    )
    return falhas


@dataclass
class Turno:
    mensagem: str
    texto: str
    tools_usadas: list[str]
    status: str
    usage: Usage
    custo_usd: float | None
    latencia_s: float
    falhas: list[str]


@dataclass
class ResultadoCaso:
    caso: Caso
    turnos: list[Turno]
    erro: str | None = None

    @property
    def aprovado(self) -> bool:
        return (
            self.erro is None
            and len(self.turnos) == len(self.caso.turnos)
            and not any(turno.falhas for turno in self.turnos)
        )


@dataclass
class Resumo:
    por_categoria: dict[str, tuple[int, int]]
    aprovados: int
    total: int
    multi_aprovados: int
    multi_total: int
    turnos: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    custo_usd: float | None
    latencia_media_s: float | None
    latencia_max_s: float | None


def resumir(resultados: list[ResultadoCaso]) -> Resumo:
    categorias: dict[str, list[bool]] = {}
    multi = []
    for resultado in resultados:
        aprovado = resultado.aprovado
        categorias.setdefault(resultado.caso.categoria, []).append(aprovado)
        if len(resultado.caso.turnos) > 1:
            multi.append(aprovado)

    por_categoria = {
        categoria: (sum(categorias[categoria]), len(categorias[categoria]))
        for categoria in CATEGORIAS if categoria in categorias
    }
    turnos = [turno for resultado in resultados for turno in resultado.turnos]
    custos = [turno.custo_usd for turno in turnos if turno.custo_usd is not None]
    latencias = [turno.latencia_s for turno in turnos]
    return Resumo(
        por_categoria=por_categoria,
        aprovados=sum(aprovados for aprovados, _ in por_categoria.values()),
        total=len(resultados),
        multi_aprovados=sum(multi),
        multi_total=len(multi),
        turnos=len(turnos),
        input_tokens=sum(turno.usage.input_tokens for turno in turnos),
        output_tokens=sum(turno.usage.output_tokens for turno in turnos),
        cached_tokens=sum(turno.usage.cached_tokens for turno in turnos),
        custo_usd=round(sum(custos, 0.0), 6) if len(custos) == len(turnos) else None,
        latencia_media_s=sum(latencias) / len(latencias) if latencias else None,
        latencia_max_s=max(latencias, default=None),
    )


def nome_relatorio(
    config: Config, sem_memoria: bool, quando: datetime, parcial: bool = False,
) -> str:
    modelo = re.sub(r"[^A-Za-z0-9._-]+", "-", config.model)
    esforco = config.reasoning_effort or "none"
    memoria = "-sem-memoria" if sem_memoria else ""
    subconjunto = "-parcial" if parcial else ""
    return f"{quando:%Y%m%d-%H%M}-{modelo}-{esforco}{memoria}{subconjunto}.md"


def _formatar_latencia(latencia: float | None) -> str:
    return "n/d" if latencia is None else f"{latencia:.1f} s"


def _linhas_falhas(resultado: ResultadoCaso) -> list[str]:
    caso = resultado.caso
    linhas = [f"### {caso.id} ({caso.categoria})", caso.descricao, ""]
    if resultado.erro is not None:
        linhas.append(f"- Erro: {resultado.erro}")
    for n, turno in enumerate(resultado.turnos, start=1):
        if not turno.falhas:
            continue
        resposta = " ".join(turno.texto.split())
        if len(resposta) > 300:
            resposta = resposta[:300] + "…"
        linhas.append(f"- Turno {n}: {turno.mensagem}")
        linhas.extend(f"  - {motivo}" for motivo in turno.falhas)
        linhas.append(f"  - Ferramentas: {', '.join(turno.tools_usadas) or 'nenhuma'}")
        linhas.append(f"  - Resposta: {resposta}")
    return linhas


def montar_relatorio(
    resultados: list[ResultadoCaso], *, config: Config, sem_memoria: bool,
    quando: datetime, parcial: bool = False,
) -> str:
    resumo = resumir(resultados)
    esforco = config.reasoning_effort or "none"
    memoria = "desligada" if sem_memoria else "ligada"
    subconjunto = " · subconjunto (--casos)" if parcial else ""
    turnos_previstos = sum(len(resultado.caso.turnos) for resultado in resultados)
    linhas = [
        f"# Avaliação do Emilio: {quando:%d/%m/%Y %H:%M}",
        "",
        f"- **Configuração:** {config.provider} · {config.model} · esforço {esforco}"
        f" · memória {memoria}",
        f"- **Limites:** {config.max_tool_iterations} chamadas ao LLM por turno"
        f" · janela de {config.history_window} mensagens",
        f"- **Casos:** {resumo.total} ({resumo.multi_total} com mais de um turno),"
        f" {turnos_previstos} turnos{subconjunto}",
        "",
        "## Resultado",
        "",
        "| Categoria | Aprovados | Total |",
        "| --- | ---: | ---: |",
    ]
    linhas.extend(
        f"| {categoria} | {aprovados} | {total} |"
        for categoria, (aprovados, total) in resumo.por_categoria.items()
    )
    linhas.extend([
        f"| **Total** | **{resumo.aprovados}** | **{resumo.total}** |",
        "",
        f"Casos com mais de um turno: {resumo.multi_aprovados} de {resumo.multi_total} aprovados.",
        "",
        "## Uso",
        "",
        "| Métrica | Valor |",
        "| --- | ---: |",
        f"| Turnos executados | {resumo.turnos} |",
        f"| Tokens de entrada | {resumo.input_tokens} ({resumo.cached_tokens} em cache) |",
        f"| Tokens de saída | {resumo.output_tokens} |",
        f"| Custo estimado | {formatar_custo(resumo.custo_usd)} |",
        f"| Latência média por turno | {_formatar_latencia(resumo.latencia_media_s)} |",
        f"| Latência máxima por turno | {_formatar_latencia(resumo.latencia_max_s)} |",
        "",
        "## Casos",
        "",
        "| Caso | Categoria | Resultado | Ferramentas | Latência (s) |",
        "| --- | --- | --- | --- | ---: |",
    ])
    reprovados = []
    for resultado in resultados:
        caso = resultado.caso
        status = "ok" if resultado.aprovado else "FALHOU"
        if resultado.erro is not None:
            status = "ERRO"
        if status != "ok":
            reprovados.append(resultado)
        ferramentas = " / ".join(", ".join(t.tools_usadas) or "nenhuma" for t in resultado.turnos)
        latencias = " / ".join(f"{t.latencia_s:.1f}" for t in resultado.turnos)
        linhas.append(
            f"| {caso.id} | {caso.categoria} | {status} | {ferramentas or '—'} |"
            f" {latencias or '—'} |"
        )

    linhas.extend(["", "## Falhas", ""])
    if not reprovados:
        linhas.append("Nenhuma falha.")
    for indice, resultado in enumerate(reprovados):
        if indice:
            linhas.append("")
        linhas.extend(_linhas_falhas(resultado))
    return "\n".join(linhas) + "\n"
