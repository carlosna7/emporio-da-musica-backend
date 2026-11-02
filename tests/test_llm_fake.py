import pytest

from app.llm.base import LLMError, Message, ToolCall, ToolSpec, Usage
from app.llm.providers.fake import FakeLLM, resposta_texto, resposta_tool

C1 = ToolCall("c1", "buscar", {"termo": "violão"})
TOOLS = [ToolSpec("buscar", "Busca", {"type": "object", "properties": {}})]
HIST = [
    Message("user", "oi"),
    Message("assistant", "", [C1]),
    Message("tool", '{"itens": []}', tool_call_id="c1"),
]


def test_fake():
    roteiro = [resposta_tool("buscar", termo="violão"), resposta_texto("Achei!")]
    fake = FakeLLM(roteiro)
    mensagens = [Message("user", "oi")]
    assert fake.chat("sys", mensagens, TOOLS).tool_calls[0].arguments == {"termo": "violão"}
    mensagens.append(Message("user", "outra"))
    assert len(fake.chamadas[0]["messages"]) == 1
    assert fake.chat("sys", mensagens, TOOLS).text == "Achei!"
    assert len(roteiro) == 2
    with pytest.raises(LLMError):
        fake.chat("sys", mensagens, TOOLS)


def test_respostas_e_registro_exatos():
    from app.llm.base import LLMResponse

    tool = resposta_tool("buscar_produtos", termo="violão")
    texto = resposta_texto("Achei!")
    assert tool == LLMResponse(
        None,
        [ToolCall("call_buscar_produtos", "buscar_produtos", {"termo": "violão"})],
        Usage(10, 5),
        "fake",
        "fake",
    )
    assert texto == LLMResponse("Achei!", [], Usage(10, 5), "fake", "fake")
    roteiro = [tool, texto]
    fake = FakeLLM(roteiro)
    msgs = [Message("user", "oi")]
    assert fake.chat("sys", msgs, TOOLS) == tool
    assert fake.chamadas[0] == {"system": "sys", "messages": msgs, "tools": TOOLS}
    msgs.append(Message("user", "mais"))
    assert fake.chamadas[0]["messages"] == [Message("user", "oi")]
    assert fake.chat("sys", msgs, TOOLS) == texto and roteiro == [tool, texto]
    with pytest.raises(LLMError):
        fake.chat("sys", msgs, TOOLS)
