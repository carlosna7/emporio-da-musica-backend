from types import SimpleNamespace

import pytest

from app.llm.base import LLMError, Message, ToolCall, ToolSpec, Usage

pytest.importorskip("anthropic")

C1 = ToolCall("c1", "buscar", {"termo": "violão"})
TOOLS = [ToolSpec("buscar", "Busca", {"type": "object", "properties": {}})]
HIST = [
    Message("user", "oi"),
    Message("assistant", "", [C1]),
    Message("tool", '{"itens": []}', tool_call_id="c1"),
]


def test_anthropic():
    pytest.importorskip("anthropic")
    from anthropic.types import Message as Resposta
    from anthropic.types import TextBlock, ToolUseBlock
    from anthropic.types import Usage as UsoSDK

    from app.llm.providers.anthropic import de_anthropic, para_anthropic

    kwargs = para_anthropic("sys", HIST + [Message("tool", "{}", tool_call_id="c1")], TOOLS)
    assert len(kwargs["messages"][-1]["content"]) == 2
    resposta = Resposta.model_construct(
        content=[
            TextBlock(type="text", text="ok"),
            ToolUseBlock(type="tool_use", id="c1", name="buscar", input={}),
        ],
        usage=UsoSDK(input_tokens=50, output_tokens=10, cache_read_input_tokens=30),
    )
    convertido = de_anthropic(resposta, "modelo")
    assert convertido.text == "ok" and convertido.usage == Usage(80, 10, 30)
    assert (
        para_anthropic("sys", [Message("assistant", "", raw=convertido.raw)], [])["messages"][0][
            "content"
        ]
        == convertido.raw
    )


def test_anthropic_erro_sdk():
    anthropic = pytest.importorskip("anthropic")
    from app.llm.providers.anthropic import MAX_TOKENS, AnthropicClient

    capturado = {}

    def criar(**kw):
        capturado.update(kw)
        raise anthropic.AnthropicError("caiu")

    with pytest.raises(LLMError, match="anthropic"):
        AnthropicClient(
            "x", "k", cliente=SimpleNamespace(messages=SimpleNamespace(create=criar))
        ).chat("sys", HIST, TOOLS)
    assert capturado["max_tokens"] == MAX_TOKENS and "temperature" not in capturado


def test_conversao_anthropic_completa():
    pytest.importorskip("anthropic")
    from anthropic.types import Message as Resposta
    from anthropic.types import TextBlock, ThinkingBlock, ToolUseBlock
    from anthropic.types import Usage as UsoSDK

    from app.llm.providers.anthropic import de_anthropic, para_anthropic

    def resposta(*blocos, usage=None):
        return Resposta.model_construct(
            content=list(blocos), usage=usage or UsoSDK(input_tokens=50, output_tokens=10)
        )

    assert para_anthropic("sys", [Message("user", "oi")], []) == {
        "system": "sys",
        "messages": [{"role": "user", "content": "oi"}],
    }
    assert para_anthropic("sys", HIST, TOOLS)["tools"] == [
        {"name": "buscar", "description": "Busca", "input_schema": TOOLS[0].parameters}
    ]
    assert para_anthropic("sys", HIST, [])["messages"] == [
        {"role": "user", "content": "oi"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "c1", "name": "buscar", "input": C1.arguments}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "c1", "content": '{"itens": []}'}],
        },
    ]
    assert para_anthropic("sys", [Message("assistant", "Olá")], [])["messages"] == [
        {"role": "assistant", "content": "Olá"}
    ]
    raw = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "tool_use", "id": "c1", "name": "buscar", "input": C1.arguments},
    ]
    assert (
        para_anthropic("sys", [Message("assistant", "", [C1], raw=raw)], [])["messages"][0][
            "content"
        ]
        is raw
    )
    txt = TextBlock(type="text", text="Olá!")
    c1 = ToolUseBlock(type="tool_use", id="a", name="buscar", input={"termo": "violão"})
    c2 = ToolUseBlock(type="tool_use", id="b", name="politica", input={"topico": "pagamentos"})
    r = de_anthropic(resposta(txt), "modelo")
    assert (r.text, r.tool_calls, r.provider, r.model, r.usage) == (
        "Olá!",
        [],
        "anthropic",
        "modelo",
        Usage(50, 10),
    )
    r = de_anthropic(resposta(c1), "modelo")
    assert r.text is None and r.tool_calls == [ToolCall("a", "buscar", {"termo": "violão"})]
    r = de_anthropic(
        resposta(ThinkingBlock(type="thinking", thinking="", signature="sig"), txt, c1, c2),
        "modelo",
    )
    assert r.text == "Olá!" and [c.id for c in r.tool_calls] == ["a", "b"]
    assert len(r.raw) == 4 and r.raw[0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    with pytest.raises(LLMError):
        de_anthropic(resposta(), "modelo")


def test_chat_anthropic_sucesso():
    pytest.importorskip("anthropic")
    from anthropic.types import Message as Resposta
    from anthropic.types import TextBlock
    from anthropic.types import Usage as UsoSDK

    from app.llm.providers.anthropic import MAX_TOKENS, AnthropicClient

    capturado = {}
    resp = Resposta.model_construct(
        content=[TextBlock(type="text", text="ok")], usage=UsoSDK(input_tokens=1, output_tokens=1)
    )
    cliente = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kw: capturado.update(kw) or resp)
    )
    assert AnthropicClient("modelo", "k", cliente=cliente).chat("sys", HIST, TOOLS).text == "ok"
    assert (
        capturado["model"] == "modelo"
        and capturado["max_tokens"] == MAX_TOKENS
        and capturado["system"] == "sys"
        and "temperature" not in capturado
    )


def test_historico_duas_chamadas_anthropic():
    from app.llm.providers.anthropic import para_anthropic

    c2 = ToolCall("c2", "politica", {"topico": "pagamentos"})
    hist = [
        Message("user", "oi"),
        Message("assistant", "Vou verificar.", [C1, c2]),
        Message("tool", "{}", tool_call_id="c1"),
        Message("tool", "{}", tool_call_id="c2"),
    ]
    mensagens = para_anthropic("sys", hist, [])["messages"]
    assert len(mensagens) == 3
    assert mensagens[1]["content"] == [
        {"type": "text", "text": "Vou verificar."},
        {"type": "tool_use", "id": "c1", "name": "buscar", "input": C1.arguments},
        {"type": "tool_use", "id": "c2", "name": "politica", "input": c2.arguments},
    ]
    assert [b["tool_use_id"] for b in mensagens[2]["content"]] == ["c1", "c2"]
