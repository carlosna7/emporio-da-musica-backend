import json
import re
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from app.config import Config
from app.llm.base import LLMError, Message
from app.llm.providers.fake import FakeLLM, resposta_texto, resposta_tool
from evals import run
from evals.avaliacao import Caso, Espera

CFG = Config(provider="fake", model="fake")
RAIZ = Path(__file__).resolve().parents[1]


def caso(id="a", turnos=("oi",), agora=datetime(2026, 11, 3, 10, 0), espera=None):
    return Caso(id, "produtos", "desc", agora, turnos, espera or (None,) * len(turnos))


def rodar(casos, roteiros, conexao, tmp_path, **opcoes):
    llms, saida = {}, []

    def llm_para(caso):
        llms[caso.id] = FakeLLM(roteiros[caso.id])
        return llms[caso.id]

    resultados = run.rodar_suite(
        casos, config=opcoes.pop("config", CFG), conexao=conexao, pasta_logs=tmp_path / "logs",
        llm_para=llm_para, escrever=saida.append, **opcoes,
    )
    return resultados, llms, saida


def linhas(arquivo):
    if not arquivo.exists():
        return []
    return [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def caso_memoria():
    return caso(
        "m", turnos=("Quanto custa o Takamine GD20?", "E no PIX?"),
        espera=(Espera(tools=("buscar_produtos",), contem=("2.199", "2.089,05")),
                Espera(contem=("2.089,05",))),
    )


def test_rodar_suite_com_memoria_preserva_historico_e_logs(caso_memoria, conexao, tmp_path):
    primeira_resposta = "Custa R$ 2.199,00; no PIX, R$ 2.089,05."
    roteiros = {"m": [
        resposta_tool("buscar_produtos", termo="takamine gd20"),
        resposta_texto(primeira_resposta),
        resposta_texto("No PIX fica R$ 2.089,05."),
    ]}
    [resultado], llms, saida = rodar([caso_memoria], roteiros, conexao, tmp_path)
    assert resultado.aprovado
    assert resultado.turnos[0].tools_usadas == ["buscar_produtos"]
    assert resultado.turnos[1].tools_usadas == []
    assert llms["m"].chamadas[2]["messages"] == [
        Message("user", "Quanto custa o Takamine GD20?"),
        Message("assistant", primeira_resposta),
        Message("user", "E no PIX?"),
    ]
    assert saida == ["[1/1] m: ok"]
    logs = linhas(tmp_path / "logs" / "llm_calls.jsonl")
    assert {linha["conversa_id"] for linha in logs} == {"eval-m"}
    assert [linha["turno"] for linha in logs] == [1, 1, 2]


def test_rodar_suite_sem_memoria_ignora_historico(caso_memoria, conexao, tmp_path):
    roteiros = {"m": [resposta_texto("a"), resposta_texto("De qual produto?")]}
    [resultado], llms, saida = rodar(
        [caso_memoria], roteiros, conexao, tmp_path, sem_memoria=True,
    )
    assert llms["m"].chamadas[1]["messages"] == [Message("user", "E no PIX?")]
    assert not resultado.aprovado
    assert resultado.turnos[1].falhas == ['falta: "2.089,05"']
    assert saida == ["[1/1] m: FALHOU"]


def test_rodar_suite_usa_agora_do_caso_no_prompt_e_no_handoff(conexao, tmp_path):
    domingo = caso("d", ("quero falar com alguém",), datetime(2026, 11, 8, 15, 0))
    roteiros = {"d": [
        resposta_tool(
            "encaminhar_atendente", motivo="pedido_do_cliente", resumo="quer falar com uma pessoa",
        ),
        resposta_texto("ok"),
    ]}
    _, llms, _ = rodar(
        [domingo], roteiros, conexao, tmp_path,
        config=replace(CFG, agora_fixo=datetime(2025, 1, 1)),
    )
    assert "domingo, 08/11/2026 (2026-11-08), 15:00" in llms["d"].chamadas[0]["system"]
    [handoff] = linhas(tmp_path / "logs" / "handoffs.jsonl")
    assert handoff["protocolo"].startswith("EM-20261108-")
    assert handoff["conversa_id"] == "eval-d"


def test_rodar_caso_mede_latencia_e_custo_de_cada_turno(conexao, tmp_path):
    config = Config(provider="openai", model="gpt-5.4-mini")
    relogio = iter([0.0, 1.5, 10.0, 12.5]).__next__
    resultado = run.rodar_caso(
        caso(turnos=("a", "b")), config=config, conexao=conexao, pasta_logs=tmp_path,
        llm=FakeLLM([resposta_texto("a"), resposta_texto("b")]), relogio=relogio,
    )
    assert [turno.latencia_s for turno in resultado.turnos] == [1.5, 2.5]
    assert [turno.custo_usd for turno in resultado.turnos] == pytest.approx([0.00003, 0.00003])


def test_rodar_suite_continua_depois_de_erro_llm(conexao, tmp_path):
    roteiros = {"a": [], "b": [resposta_texto("oi")]}
    [a, b], _, saida = rodar([caso("a"), caso("b")], roteiros, conexao, tmp_path)
    assert not a.aprovado
    assert a.turnos[0].falhas[0] == "status: erro_llm"
    assert b.turnos[0].texto == "oi"
    assert saida == ["[1/2] a: FALHOU", "[2/2] b: ok"]


def test_rodar_suite_continua_depois_de_excecao(conexao, tmp_path):
    def llm_para(caso):
        if caso.id == "a":
            raise RuntimeError("sem chave")
        return FakeLLM([resposta_texto("oi")])

    a, b = run.rodar_suite(
        [caso("a"), caso("b")], config=CFG, conexao=conexao, pasta_logs=tmp_path,
        llm_para=llm_para, escrever=lambda _: None,
    )
    assert a.erro == "RuntimeError: sem chave"
    assert a.turnos == []
    assert b.aprovado


def test_turno_reprovado_nao_interrompe_caso(conexao, tmp_path):
    dois_turnos = caso(turnos=("a", "b"), espera=(Espera(contem=("x",)), None))
    roteiros = {"a": [resposta_texto("a"), resposta_texto("b")]}
    [resultado], llms, _ = rodar([dois_turnos], roteiros, conexao, tmp_path)
    assert not resultado.aprovado
    assert len(resultado.turnos) == len(llms["a"].chamadas) == 2


def test_aplicar_overrides_preserva_campos_omitidos():
    assert run.aplicar_overrides(CFG) == CFG
    config = run.aplicar_overrides(CFG, provedor="openai", modelo="gpt-5.4-mini", esforco="none")
    assert config == replace(CFG, provider="openai", model="gpt-5.4-mini", reasoning_effort="none")
    assert run.aplicar_overrides(CFG, modelo="outro") == replace(CFG, model="outro")


def test_filtrar_casos_preserva_ordem_do_arquivo_sem_duplicar():
    casos = [caso("a"), caso("b"), caso("c")]
    assert [c.id for c in run.filtrar_casos(casos, ["c", "a", "a"])] == ["a", "c"]
    with pytest.raises(ValueError, match=r"x,\s*y"):
        run.filtrar_casos(casos, ["a", "x", "y"])


@pytest.fixture
def main_fake(monkeypatch, banco, tmp_path):
    chamadas = []

    def criar_cliente(*args, **kwargs):
        chamadas.append((args, kwargs))
        return FakeLLM([resposta_texto("Aqui é da loja de instrumentos.")] * 3)

    monkeypatch.setattr(run, "carregar_config", lambda: CFG)
    monkeypatch.setattr(run, "criar_cliente", criar_cliente)
    monkeypatch.setattr(run, "CAMINHO_BANCO", banco)
    monkeypatch.setattr(run, "PASTA_RESULTADOS", tmp_path / "res")
    monkeypatch.setattr(run, "PASTA_LOGS_EVAL", tmp_path / "logs")
    return chamadas


def test_main_grava_relatorio_parcial_e_mostra_resumo(main_fake, tmp_path, capsys):
    run.main([
        "--casos", "escopo-futebol, memoria-takamine-pix", "--sem-memoria", "--esforco", "low",
    ])
    assert main_fake == [(("fake", "fake"), {"reasoning_effort": "low"})]
    [relatorio] = (tmp_path / "res").iterdir()
    assert re.fullmatch(r"\d{8}-\d{4}-fake-low-sem-memoria-parcial\.md", relatorio.name)
    texto = relatorio.read_text(encoding="utf-8")
    assert "memória desligada" in texto
    assert "| escopo-futebol | escopo |" in texto
    assert "| memoria-takamine-pix | memoria |" in texto
    assert {linha["conversa_id"] for linha in linhas(tmp_path / "logs" / "llm_calls.jsonl")} == {
        "eval-escopo-futebol", "eval-memoria-takamine-pix",
    }
    saida = capsys.readouterr().out
    assert "## Resultado" in saida
    assert "Relatório:" in saida
    assert "[2/2] memoria-takamine-pix:" in saida
    assert "## Casos" not in saida


def test_main_passa_overrides_ao_cliente(main_fake, tmp_path):
    run.main([
        "--casos", "escopo-futebol", "--provedor", "openai", "--modelo", "gpt-5.4-mini",
        "--esforco", "none",
    ])
    assert main_fake == [(("openai", "gpt-5.4-mini"), {"reasoning_effort": "none"})]
    [relatorio] = (tmp_path / "res").iterdir()
    assert relatorio.name.endswith("-gpt-5.4-mini-none-parcial.md")


def test_main_rejeita_caso_desconhecido_antes_do_cliente(main_fake, capsys):
    with pytest.raises(SystemExit) as erro:
        run.main(["--casos", "nao-existe"])
    assert erro.value.code == 2
    assert "nao-existe" in capsys.readouterr().err
    assert main_fake == []


@pytest.mark.parametrize(("funcao", "falha"), [
    ("criar_cliente", LLMError("defina OPENAI_API_KEY no .env")),
    (
        "carregar_config",
        ValueError("LLM_REASONING_EFFORT: valores válidos: none, low, medium, high"),
    ),
    ("carregar_casos", ValueError("casos.json, caso #0: a raiz deve ser uma lista")),
])
def test_main_erro_de_inicio_sem_traceback(main_fake, monkeypatch, tmp_path, capsys, funcao, falha):
    def falhar(*args, **kwargs):
        raise falha

    monkeypatch.setattr(run, funcao, falhar)
    with pytest.raises(SystemExit) as erro:
        run.main([])
    assert erro.value.code == 1
    stderr = capsys.readouterr().err
    assert "Não consegui iniciar a avaliação" in stderr
    assert str(falha) in stderr
    assert "Traceback" not in stderr
    assert not (tmp_path / "res").exists()


def test_main_ajuda_via_python_m():
    processo = subprocess.run(
        [sys.executable, "-m", "evals.run", "--help"], cwd=RAIZ,
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert "--sem-memoria" in processo.stdout


def test_importar_runner_nao_carrega_sdks():
    subprocess.run([
        sys.executable, "-c",
        "import sys, evals.run; assert not any(m in sys.modules for m in "
        "('openai', 'anthropic', 'google.genai'))",
    ], cwd=RAIZ, check=True)
