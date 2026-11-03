import json
import re
from datetime import datetime

import pytest

from app.agent import ERRO_PROVEDOR, MENSAGEM_LONGA, criar_agente
from app.cli import (
    BOAS_VINDAS,
    COMANDOS,
    DESPEDIDA,
    NOVA_CONVERSA,
    executar,
    formatar_custo,
    gerar_conversa_id,
    linha_ferramentas,
)
from app.config import Config
from app.llm.base import Message
from app.llm.providers.fake import FakeLLM, resposta_texto, resposta_tool

CFG = Config(provider="fake", model="fake")
AGORA = datetime(2026, 11, 3, 10, 0)


def montar(roteiro, conexao, tmp_path, config=CFG):
    llm = FakeLLM(roteiro)
    return criar_agente(
        config=config, llm=llm, conexao=conexao, pasta_logs=tmp_path, agora=AGORA
    ), llm


def leitor(entradas):
    fila, prompts = list(entradas), []

    def ler(prompt):
        prompts.append(prompt)
        if not fila:
            raise EOFError
        item = fila.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return ler, prompts


def rodar(agente, entradas, debug=False, ids=("cli-a", "cli-b", "cli-c")):
    ler, prompts = leitor(entradas)
    saida, fila_ids = [], iter(ids)
    codigo = executar(
        agente, ler=ler, escrever=saida.append, debug=debug, novo_id=lambda: next(fila_ids)
    )
    return codigo, saida, prompts


def logs(tmp_path):
    return [
        json.loads(x)
        for x in (tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_dois_turnos_com_memoria(conexao, tmp_path):
    agente, llm = montar(
        [
            resposta_tool("consultar_politica", topico="sobre_a_loja"),
            resposta_texto("Fica na Rua 14 de Maio, 3200."),
            resposta_texto("Abrimos às 9h."),
        ],
        conexao,
        tmp_path,
    )
    codigo, saida, prompts = rodar(agente, ["Qual o endereço?", "E que horas abre?"])
    assert codigo == 0 and saida[:3] == [BOAS_VINDAS, COMANDOS, ""]
    assert saida[3:8] == [
        "Emilio: Fica na Rua 14 de Maio, 3200.",
        "[ferramentas: consultar_politica]",
        "",
        "Emilio: Abrimos às 9h.",
        "[ferramentas: nenhuma]",
    ]
    assert saida[-1] == DESPEDIDA and not any(x.startswith("[debug") for x in saida)
    assert all(p == "Você: " for p in prompts)
    assert llm.chamadas[2]["messages"] == [
        Message("user", "Qual o endereço?"),
        Message("assistant", "Fica na Rua 14 de Maio, 3200."),
        Message("user", "E que horas abre?"),
    ]
    assert [x["conversa_id"] for x in logs(tmp_path)] == ["cli-a"] * 3
    assert [x["turno"] for x in logs(tmp_path)] == [1, 1, 2]


def test_vazias_e_espacos(conexao, tmp_path):
    agente, llm = montar([resposta_texto("Olá!")], conexao, tmp_path)
    rodar(agente, ["", "   ", "  oi  "])
    assert len(llm.chamadas) == 1 and llm.chamadas[0]["messages"] == [Message("user", "oi")]


def test_ferramentas():
    assert linha_ferramentas([]) == "[ferramentas: nenhuma]"
    assert (
        linha_ferramentas(["buscar_produtos", "buscar_produtos", "consultar_politica"])
        == "[ferramentas: buscar_produtos, buscar_produtos, consultar_politica]"
    )


def test_respostas_nao_ok(conexao, tmp_path):
    agente, llm = montar(
        [resposta_texto("Olá!")],
        conexao,
        tmp_path,
        Config(provider="fake", model="fake", max_message_chars=10),
    )
    _, saida, _ = rodar(agente, ["x" * 11, "oi"])
    i = saida.index("Emilio: " + MENSAGEM_LONGA.format(limite=10))
    assert saida[i + 1] == "[ferramentas: nenhuma]"
    assert llm.chamadas[0]["messages"] == [Message("user", "oi")]
    agente, llm = montar([], conexao, tmp_path)
    codigo, saida, _ = rodar(agente, ["oi", "de novo"])
    assert codigo == 0 and saida.count("Emilio: " + ERRO_PROVEDOR) == 2
    assert llm.chamadas[1]["messages"] == [
        Message("user", "oi"),
        Message("assistant", ERRO_PROVEDOR),
        Message("user", "de novo"),
    ]


@pytest.mark.parametrize("comando", ["sair", "/sair", "  SAIR "])
def test_sair(comando, conexao, tmp_path):
    agente, llm = montar([], conexao, tmp_path)
    codigo, saida, prompts = rodar(agente, [comando, "oi"])
    assert codigo == 0 and llm.chamadas == [] and len(prompts) == 1
    assert saida == [BOAS_VINDAS, COMANDOS, "", DESPEDIDA]


@pytest.mark.parametrize("entradas", [[], [KeyboardInterrupt()]])
def test_interrupcao_leitura(entradas, conexao, tmp_path):
    agente, _ = montar([], conexao, tmp_path)
    codigo, saida, _ = rodar(agente, entradas)
    assert codigo == 0 and saida == [BOAS_VINDAS, COMANDOS, "", "", DESPEDIDA]


def test_interrupcao_resposta():
    class Interrompe:
        def responder(self, historico, mensagem, conversa_id):
            raise KeyboardInterrupt

    codigo, saida, _ = rodar(Interrompe(), ["oi"])
    assert codigo == 0 and saida[-2:] == ["", DESPEDIDA]


def test_nova_conversa(conexao, tmp_path):
    agente, llm = montar([resposta_texto("a"), resposta_texto("b")], conexao, tmp_path)
    _, saida, _ = rodar(agente, ["um", "/nova", "dois"])
    assert NOVA_CONVERSA in saida and llm.chamadas[1]["messages"] == [Message("user", "dois")]
    assert [x["conversa_id"] for x in logs(tmp_path)] == ["cli-a", "cli-b"]
    assert [x["turno"] for x in logs(tmp_path)] == [1, 1]


def test_comando_desconhecido(conexao, tmp_path):
    agente, llm = montar([], conexao, tmp_path)
    _, saida, _ = rodar(agente, ["/ajuda"])
    assert llm.chamadas == [] and saida.count(COMANDOS) == 2


def test_id():
    a, b = gerar_conversa_id(), gerar_conversa_id()
    assert re.fullmatch(r"cli-[0-9a-f]{8}", a) and a != b


def test_debug_com_custo(conexao, tmp_path):
    agente, _ = montar(
        [resposta_texto("a"), resposta_texto("b")],
        conexao,
        tmp_path,
        Config(provider="openai", model="gpt-5.4-mini"),
    )
    _, saida, _ = rodar(agente, ["um", "dois"], debug=True)
    linha = (
        "[debug: ok | 1 chamada(s) ao LLM | tokens: 10 entrada (0 em cache), 5 saída "
        "| custo: US$ 0.000030 | conversa: cli-a]"
    )
    assert saida.count(linha) == 2
    assert all(saida[i - 1] == "[ferramentas: nenhuma]" for i, x in enumerate(saida) if x == linha)
    assert saida[-1] == "[debug: 2 turno(s) nesta sessão, custo total US$ 0.000060]"


def test_debug_sem_preco(conexao, tmp_path):
    agente, _ = montar([resposta_texto("a")], conexao, tmp_path)
    _, saida, _ = rodar(agente, ["um"], debug=True)
    assert any(x.endswith("custo: n/d | conversa: cli-a]") for x in saida)
    assert saida[-1] == "[debug: 1 turno(s) nesta sessão, custo total n/d]"


def test_formatar_custo():
    assert formatar_custo(None) == "n/d"
    assert formatar_custo(0.0) == "US$ 0.000000"
    assert formatar_custo(0.00003) == "US$ 0.000030"


def test_abrir_banco_ausente(tmp_path):
    import sqlite3

    from app.cli import CRIANDO_BANCO, abrir_banco

    caminho = tmp_path / "dados" / "emporio.db"
    saida = []
    con = abrir_banco(caminho, saida.append)
    try:
        assert saida == [CRIANDO_BANCO] and caminho.exists()
        assert con.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DELETE FROM products")
    finally:
        con.close()


def test_abrir_banco_existente(banco):
    from app.cli import abrir_banco

    saida = []
    con = abrir_banco(banco, saida.append)
    try:
        assert saida == [] and con.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0
    finally:
        con.close()


def test_main(monkeypatch, tmp_path, capsys):
    from app.cli import main

    caminho = tmp_path / "x.db"
    recebido = {}
    monkeypatch.setattr("app.cli.CAMINHO_BANCO", caminho)
    monkeypatch.setattr(
        "app.cli.abrir_banco", lambda c: recebido.update(caminho=c) or "conexao-falsa"
    )
    monkeypatch.setattr("app.cli.criar_agente", lambda **kw: recebido.update(kwargs=kw) or object())
    monkeypatch.setattr("builtins.input", leitor([])[0])
    with pytest.raises(SystemExit) as exc:
        main(["--debug"])
    assert exc.value.code == 0
    assert recebido == {"caminho": caminho, "kwargs": {"conexao": "conexao-falsa"}}
    out = capsys.readouterr().out
    assert BOAS_VINDAS in out and DESPEDIDA in out
    assert "[debug: 0 turno(s) nesta sessão, custo total US$ 0.000000]" in out


@pytest.mark.parametrize(
    "erro",
    [
        pytest.param("llm", id="llm"),
        pytest.param("valor", id="valor"),
    ],
)
def test_main_erro(erro, monkeypatch, capsys):
    from app.cli import main
    from app.llm.base import LLMError

    exc = (
        LLMError("defina OPENAI_API_KEY no .env")
        if erro == "llm"
        else ValueError("MAX_TOOL_ITERATIONS deve ser inteiro >= 1")
    )
    monkeypatch.setattr("app.cli.abrir_banco", lambda c: "conexao-falsa")

    def falhar(**kwargs):
        raise exc

    monkeypatch.setattr("app.cli.criar_agente", falhar)
    with pytest.raises(SystemExit) as saida:
        main([])
    assert saida.value.code == 1
    err = capsys.readouterr().err
    assert "Não consegui iniciar o Emilio" in err and str(exc) in err and ".env.example" in err
    assert "Traceback" not in err


def test_isolamento():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, app.cli; assert not any(m in sys.modules "
            "for m in ('openai', 'anthropic', 'google.genai'))",
        ],
        check=True,
    )
