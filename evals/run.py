"""Executa os casos de avaliação contra o LLM configurado."""

import argparse
import itertools
import sqlite3
import sys
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app.agent import criar_agente
from app.cli import abrir_banco, configurar_utf8
from app.config import Config, carregar_config
from app.db import CAMINHO_BANCO
from app.llm.base import LLMClient, LLMError, Message, criar_cliente
from evals.avaliacao import (
    ARQUIVO_CASOS,
    Caso,
    ResultadoCaso,
    Turno,
    carregar_casos,
    montar_relatorio,
    nome_relatorio,
    verificar,
)

PASTA_RESULTADOS = Path(__file__).resolve().parent / "resultados"
PASTA_LOGS_EVAL = Path(__file__).resolve().parent / "logs"
ERRO_INICIO = "Não consegui iniciar a avaliação: {erro}"


def rodar_caso(
    caso: Caso, *, config: Config, conexao: sqlite3.Connection, pasta_logs: Path,
    llm: LLMClient, sem_memoria: bool = False,
    relogio: Callable[[], float] = time.perf_counter,
) -> ResultadoCaso:
    agente = criar_agente(
        config=config, llm=llm, conexao=conexao, pasta_logs=pasta_logs, agora=caso.agora,
    )
    historico: list[Message] = []
    turnos = []
    conversa_id = f"eval-{caso.id}"
    for mensagem, espera in zip(caso.turnos, caso.espera, strict=True):
        inicio = relogio()
        resposta = agente.responder([] if sem_memoria else historico, mensagem, conversa_id)
        latencia_s = relogio() - inicio
        if not sem_memoria:
            historico.extend(resposta.para_historico)
        turnos.append(Turno(
            mensagem, resposta.texto, list(resposta.tools_usadas), resposta.status,
            resposta.usage, resposta.custo_usd, latencia_s,
            verificar(espera, resposta.texto, resposta.tools_usadas, resposta.status),
        ))
    return ResultadoCaso(caso, turnos)


def rodar_suite(
    casos: list[Caso], *, config: Config, conexao: sqlite3.Connection, pasta_logs: Path,
    llm_para: Callable[[Caso], LLMClient], sem_memoria: bool = False,
    relogio: Callable[[], float] = time.perf_counter,
    escrever: Callable[[str], None] = print,
) -> list[ResultadoCaso]:
    resultados = []
    total = len(casos)
    for indice, caso in enumerate(casos, start=1):
        try:
            resultado = rodar_caso(
                caso, config=config, conexao=conexao, pasta_logs=pasta_logs,
                llm=llm_para(caso), sem_memoria=sem_memoria, relogio=relogio,
            )
        except Exception as erro:
            resultado = ResultadoCaso(caso, [], erro=f"{type(erro).__name__}: {erro}")
        resultados.append(resultado)
        escrever(f"[{indice}/{total}] {caso.id}: {'ok' if resultado.aprovado else 'FALHOU'}")
    return resultados


def aplicar_overrides(
    config: Config, *, provedor: str | None = None, modelo: str | None = None,
    esforco: str | None = None,
) -> Config:
    opcoes = {"provider": provedor, "model": modelo, "reasoning_effort": esforco}
    return replace(config, **{campo: valor for campo, valor in opcoes.items() if valor is not None})


def filtrar_casos(casos: list[Caso], ids: list[str]) -> list[Caso]:
    selecionados = set(ids)
    desconhecidos = selecionados - {caso.id for caso in casos}
    if desconhecidos:
        raise ValueError(", ".join(sorted(desconhecidos)))
    return [caso for caso in casos if caso.id in selecionados]


def gravar_relatorio(pasta: Path, nome: str, texto: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    base = nome.removesuffix(".md")
    for numero in itertools.count(1):
        caminho = pasta / (nome if numero == 1 else f"{base}-{numero}.md")
        # "x" falha se o arquivo existe: rodadas em paralelo nunca gravam no mesmo nome.
        try:
            with caminho.open("x", encoding="utf-8") as arquivo:
                arquivo.write(texto)
        except FileExistsError:
            continue
        return caminho


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description=(
            "Roda a suíte de avaliação do Emilio contra o LLM real e grava o relatório "
            "em evals/resultados/."
        ),
    )
    parser.add_argument(
        "--sem-memoria", action="store_true",
        help="envia histórico vazio a cada turno (ablação da memória)",
    )
    parser.add_argument("--casos", help="ids separados por vírgula (padrão: todos)")
    parser.add_argument(
        "--provedor", choices=["openai", "anthropic", "gemini"], help="sobrescreve LLM_PROVIDER",
    )
    parser.add_argument("--modelo", help="sobrescreve LLM_MODEL")
    parser.add_argument(
        "--esforco", choices=["none", "low", "medium", "high"],
        help="sobrescreve LLM_REASONING_EFFORT",
    )
    configurar_utf8()
    args = parser.parse_args(argv)

    try:
        casos = carregar_casos(ARQUIVO_CASOS)
    except ValueError as erro:
        print(ERRO_INICIO.format(erro=erro), file=sys.stderr)
        sys.exit(1)

    if args.casos:
        ids = [id_caso for trecho in args.casos.split(",") if (id_caso := trecho.strip())]
        try:
            casos = filtrar_casos(casos, ids)
        except ValueError as erro:
            parser.error(f"casos desconhecidos: {erro}")

    try:
        config = aplicar_overrides(
            carregar_config(), provedor=args.provedor, modelo=args.modelo, esforco=args.esforco,
        )
        llm = criar_cliente(config.provider, config.model, reasoning_effort=config.reasoning_effort)
        conexao = abrir_banco(CAMINHO_BANCO)
    except (LLMError, ValueError) as erro:
        print(ERRO_INICIO.format(erro=erro), file=sys.stderr)
        sys.exit(1)

    inicio = datetime.now()
    with closing(conexao):
        resultados = rodar_suite(
            casos, config=config, conexao=conexao, pasta_logs=PASTA_LOGS_EVAL,
            llm_para=lambda caso: llm, sem_memoria=args.sem_memoria,
        )
    parcial = bool(args.casos)
    texto = montar_relatorio(
        resultados, config=config, sem_memoria=args.sem_memoria, quando=inicio, parcial=parcial,
    )
    caminho = gravar_relatorio(
        PASTA_RESULTADOS, nome_relatorio(config, args.sem_memoria, inicio, parcial), texto,
    )
    print(texto.split("\n## Casos", 1)[0])
    print(f"Relatório: {caminho}")


if __name__ == "__main__":
    main()
