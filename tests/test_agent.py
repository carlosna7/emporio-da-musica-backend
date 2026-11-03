import json
from datetime import date

from app.agent import ERRO_PROVEDOR, LIMITE_ITERACOES, MENSAGEM_LONGA, Agente
from app.config import Config
from app.llm.base import Message, Usage
from app.llm.providers.fake import FakeLLM, resposta_texto, resposta_tool
from app.tools import TOOLS, Contexto


def test_loop(conexao, tmp_path):
    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    llm = FakeLLM([resposta_tool("buscar_produtos", termo="takamine gd20"), resposta_texto("ok")])
    agente = Agente(llm, TOOLS, ctx, "SYS", Config(provider="fake", model="fake"))
    resposta = agente.responder([], "oi", "c1")
    assert resposta.texto == "ok" and resposta.usage == Usage(20, 10)
    assert resposta.tools_usadas == ["buscar_produtos"] and resposta.iteracoes == 2
    assert resposta.para_historico == [Message("user", "oi"), Message("assistant", "ok")]
    assert json.loads(llm.chamadas[1]["messages"][2].content)["produtos"][0]["preco_pix"] == 2089.05
    assert len((tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_limites_e_erros(conexao, tmp_path):
    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    a = Agente(FakeLLM([]), TOOLS, ctx, "SYS", Config(max_message_chars=2))
    assert a.responder([], "abc", "c").texto == MENSAGEM_LONGA.format(limite=2)
    assert a.responder([], "oi", "c").texto == ERRO_PROVEDOR
    a = Agente(
        FakeLLM([resposta_tool("consultar_politica", topico="horarios")]),
        TOOLS,
        ctx,
        "SYS",
        Config(max_tool_iterations=1),
    )
    assert a.responder([], "oi", "c").texto == LIMITE_ITERACOES


def test_montagem(conexao, tmp_path):
    from datetime import datetime

    from app.agent import criar_agente

    a = criar_agente(
        config=Config(provider="fake", model="fake"),
        llm=FakeLLM([]),
        conexao=conexao,
        pasta_logs=tmp_path,
        agora=datetime(2026, 11, 8, 15),
    )
    assert a.ctx.hoje == date(2026, 11, 8)
    assert "domingo" in a.system and "3321" not in a.system
    assert a.tools is TOOLS and a.ctx.pasta_logs == tmp_path


def test_historico_tool_e_custo(conexao, tmp_path):
    from app.llm.base import LLMResponse, ToolCall

    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    calls = [
        ToolCall("c1", "buscar_produtos", {"termo": "takamine gd20"}),
        ToolCall("c2", "consultar_politica", {"topico": "pagamentos"}),
    ]
    llm = FakeLLM(
        [
            LLMResponse(None, calls, Usage(10, 5), "fake", "fake", raw={"opaco": 1}),
            resposta_texto("ok"),
        ]
    )
    a = Agente(llm, TOOLS, ctx, "SYS", Config(provider="openai", model="gpt-5.4-mini"))
    historico = [Message("user" if i % 2 == 0 else "assistant", str(i)) for i in range(30)]
    r = a.responder(historico, "nova", "c1")
    mensagens = llm.chamadas[1]["messages"]
    assert llm.chamadas[0]["messages"] == historico[-20:] + [Message("user", "nova")]
    assert len(historico) == 30 and mensagens[21].raw == {"opaco": 1}
    assert [m.tool_call_id for m in mensagens[22:]] == ["c1", "c2"]
    assert json.loads(mensagens[23].content)["topico"] == "pagamentos"
    assert r.tools_usadas == ["buscar_produtos", "consultar_politica"]
    assert r.custo_usd == 0.00006
    linhas = [
        json.loads(linha)
        for linha in (tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [x["turno"] for x in linhas] == [16, 16]
    assert [x["custo_usd"] for x in linhas] == [0.00003, 0.00003]
    assert [x["tools_chamadas"] for x in linhas] == [["buscar_produtos", "consultar_politica"], []]


def test_despacho_de_erros(conexao, tmp_path):
    from app.tools import Ferramenta

    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    for chamada, trecho in [
        (resposta_tool("desconhecida"), "desconhecida"),
        (resposta_tool("detalhes_produto", id=95), "Argumentos inválidos"),
        (resposta_tool("consultar_pedido", order_id=1), "Argumentos inválidos"),
        (resposta_tool("consultar_politica", topico="horarios", ctx="x"), "Argumentos inválidos"),
    ]:
        llm = FakeLLM([chamada, resposta_texto("ok")])
        r = Agente(llm, TOOLS, ctx, "SYS", Config()).responder([], "oi", "c")
        assert (
            r.status == "ok"
            and trecho in json.loads(llm.chamadas[1]["messages"][-1].content)["erro"]
        )

    def falhar(*, ctx):
        raise RuntimeError("segredo interno")

    ferramenta = Ferramenta(falhar, "x", {"type": "object", "properties": {}, "required": []})
    llm = FakeLLM([resposta_tool("falhar"), resposta_texto("ok")])
    Agente(llm, {"falhar": ferramenta}, ctx, "SYS", Config()).responder([], "oi", "c")
    assert "segredo interno" not in llm.chamadas[1]["messages"][-1].content


def test_memoria_contexto_e_falha_intermediaria(conexao, tmp_path):
    from app.tools import Ferramenta

    capturados = []
    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    ferramentas = {
        "espiao": Ferramenta(
            lambda *, ctx: capturados.append(ctx) or {"ok": True},
            "x",
            {"type": "object", "properties": {}, "required": []},
        )
    }
    llm = FakeLLM([resposta_tool("espiao"), resposta_texto("a"), resposta_texto("b")])
    a = Agente(llm, ferramentas, ctx, "SYS", Config())
    a.responder([], "um", "c-42")
    a.responder([], "dois", "c-42")
    assert llm.chamadas[2]["messages"] == [Message("user", "dois")]
    assert capturados[0].conversa_id == "c-42" and capturados[0].hoje == ctx.hoje
    assert a.ctx.conversa_id == ""
    falho = Agente(
        FakeLLM([resposta_tool("consultar_politica", topico="horarios")]),
        TOOLS,
        ctx,
        "SYS",
        Config(),
    )
    r = falho.responder([], "oi", "falha")
    assert r.status == "erro_llm" and r.iteracoes == 2 and r.tools_usadas == ["consultar_politica"]
    linhas = [
        json.loads(linha)
        for linha in (tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [x["status"] for x in linhas[-2:]] == ["ok", "erro"]
    assert linhas[-1]["input_tokens"] is None and "roteiro esgotado" in linhas[-1]["erro"]


def test_limite_exato_e_falha_inicial(conexao, tmp_path):
    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    llm = FakeLLM([resposta_texto("ok")])
    a = Agente(llm, TOOLS, ctx, "SYS", Config(max_message_chars=10))
    r = a.responder([], "x" * 11, "c")
    assert r.status == "mensagem_longa" and r.iteracoes == 0 and r.para_historico == []
    assert not llm.chamadas and not (tmp_path / "llm_calls.jsonl").exists()
    assert a.responder([], "x" * 10, "c").status == "ok"
    pasta = tmp_path / "erro"
    a = Agente(
        FakeLLM([]), TOOLS, Contexto(conexao, date(2026, 11, 2), pasta_logs=pasta), "SYS", Config()
    )
    r = a.responder([], "oi", "c")
    assert r.status == "erro_llm" and r.iteracoes == 1 and r.usage == Usage(0, 0)
    assert r.custo_usd == 0.0 and r.para_historico == [
        Message("user", "oi"),
        Message("assistant", ERRO_PROVEDOR),
    ]
    log = json.loads((pasta / "llm_calls.jsonl").read_text(encoding="utf-8"))
    assert (
        log["status"] == "erro"
        and log["input_tokens"] is None
        and log["custo_usd"] is None
        and "roteiro esgotado" in log["erro"]
    )


def test_limite_de_duas_chamadas(conexao, tmp_path):
    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    llm = FakeLLM(
        [
            resposta_tool("consultar_politica", topico="horarios"),
            resposta_tool("consultar_politica", topico="horarios"),
            resposta_texto("nunca"),
        ]
    )
    r = Agente(llm, TOOLS, ctx, "SYS", Config(max_tool_iterations=2)).responder([], "oi", "c")
    assert r.texto == LIMITE_ITERACOES and r.status == "limite_iteracoes" and r.iteracoes == 2
    assert len(llm.chamadas) == 2 and r.tools_usadas == ["consultar_politica"]
    assert len((tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert r.para_historico[1] == Message("assistant", LIMITE_ITERACOES)


def test_erro_proprio_da_tool(conexao, tmp_path):
    from app.tools import ERRO_PEDIDO

    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    llm = FakeLLM(
        [
            resposta_tool("consultar_pedido", order_id=1, email_ou_telefone="x@y.com"),
            resposta_texto("ok"),
        ]
    )
    r = Agente(llm, TOOLS, ctx, "SYS", Config()).responder([], "oi", "c")
    assert r.status == "ok" and json.loads(llm.chamadas[1]["messages"][-1].content) == {
        "erro": ERRO_PEDIDO
    }


def test_montagem_data_e_isolamento(conexao, tmp_path):
    import subprocess
    import sys
    from datetime import datetime

    from app.agent import criar_agente

    a = criar_agente(
        config=Config(provider="fake", model="fake", agora_fixo=datetime(2026, 1, 22, 10)),
        llm=FakeLLM(
            [
                resposta_tool("consultar_politica", topico="sobre_a_loja"),
                resposta_texto("Rua 14 de Maio, 3200"),
            ]
        ),
        conexao=conexao,
        pasta_logs=tmp_path,
    )
    assert (
        a.ctx.hoje == date(2026, 1, 22)
        and "quinta-feira, 22/01/2026 (2026-01-22), 10:00" in a.system
    )
    assert a.responder([], "Qual o endereço?", "c").status == "ok"
    assert "Rua 14 de Maio" in a.llm.chamadas[1]["messages"][-1].content
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, app.agent; assert not any(m in sys.modules "
            "for m in ('openai', 'anthropic', 'google.genai'))",
        ],
        check=True,
    )


def test_texto_e_contrato_de_chamada(conexao, tmp_path):
    from app.llm.base import ToolSpec

    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    llm = FakeLLM([resposta_texto("Olá! Sou o Emilio.")])
    r = Agente(llm, TOOLS, ctx, "SYS", Config(provider="fake", model="fake")).responder(
        [], "oi", "c1"
    )
    assert r.texto == "Olá! Sou o Emilio." and r.tools_usadas == [] and r.iteracoes == 1
    assert r.usage == Usage(10, 5) and r.status == "ok" and r.custo_usd is None
    assert r.para_historico == [Message("user", "oi"), Message("assistant", r.texto)]
    assert llm.chamadas[0] == {
        "system": "SYS",
        "messages": [Message("user", "oi")],
        "tools": [ToolSpec(n, f.descricao, f.parametros) for n, f in TOOLS.items()],
    }


def test_registro_de_turno_e_resposta_tool(conexao, tmp_path):
    from app.llm.base import LLMResponse, ToolCall

    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    call = ToolCall("call_1", "buscar_produtos", {"termo": "takamine gd20"})
    llm = FakeLLM(
        [
            LLMResponse(None, [call], Usage(10, 5), "fake", "fake", raw={"opaco": 1}),
            resposta_texto("Custa R$ 2.199,00."),
        ]
    )
    r = Agente(llm, TOOLS, ctx, "SYS", Config(provider="fake", model="fake")).responder(
        [], "oi", "c1"
    )
    msgs = llm.chamadas[1]["messages"]
    assert msgs[0] == Message("user", "oi") and msgs[1] == Message("assistant", "", [call])
    assert (
        msgs[1].raw == {"opaco": 1} and msgs[2].tool_call_id == "call_1" and msgs[2].role == "tool"
    )
    assert (
        '"Violões"' in msgs[2].content
        and json.loads(msgs[2].content)["produtos"][0]["preco_pix"] == 2089.05
    )
    assert r.para_historico == [Message("user", "oi"), Message("assistant", "Custa R$ 2.199,00.")]
    linhas = [
        json.loads(linha)
        for linha in (tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for i, linha in enumerate(linhas, 1):
        assert linha["conversa_id"] == "c1" and linha["turno"] == 1 and linha["iteracao"] == i
        assert (
            linha["provider"] == "fake"
            and linha["status"] == "ok"
            and isinstance(linha["latencia_ms"], int)
            and linha["latencia_ms"] >= 0
        )
    assert [x["tools_chamadas"] for x in linhas] == [["buscar_produtos"], []]


def test_nao_executa_injecao_de_ctx_e_informa_disponiveis(conexao, tmp_path):
    ctx = Contexto(conexao, date(2026, 11, 2), pasta_logs=tmp_path)
    chamadas = [
        resposta_tool("calcular_frete", cep="79000000"),
        resposta_tool("detalhes_produto", id=95),
        resposta_tool("consultar_pedido", order_id=1),
        resposta_tool("consultar_politica", topico="horarios", ctx="x"),
    ]
    for chamada in chamadas:
        llm = FakeLLM([chamada, resposta_texto("ok")])
        r = Agente(llm, TOOLS, ctx, "SYS", Config()).responder([], "oi", "c")
        erro = json.loads(llm.chamadas[1]["messages"][-1].content)
        nome = chamada.tool_calls[0].name
        assert r.status == "ok" and r.tools_usadas == [nome] and set(erro) == {"erro"}
        assert nome in erro["erro"]
        assert ("buscar_produtos" if nome == "calcular_frete" else "Argumentos inválidos") in erro[
            "erro"
        ]
