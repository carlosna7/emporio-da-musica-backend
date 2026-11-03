import json
from types import SimpleNamespace

import pytest

from app.llm.base import LLMError, Message, ToolCall, ToolSpec, Usage
from app.llm.providers.openai import OpenAIClient, de_openai, para_openai

C1 = ToolCall("c1", "buscar", {"termo": "violão"})
TOOLS = [ToolSpec("buscar", "Busca", {"type": "object", "properties": {}})]
HIST = [
    Message("user", "oi"),
    Message("assistant", "", [C1]),
    Message("tool", '{"itens": []}', tool_call_id="c1"),
]


def test_openai():
    from openai.types.responses import (
        Response,
        ResponseFunctionToolCall,
        ResponseOutputMessage,
        ResponseOutputText,
    )

    entrada = para_openai("sys", HIST, TOOLS)
    assert json.loads(entrada["input"][1]["arguments"]) == C1.arguments
    assert "id" not in entrada["input"][1]
    assert entrada["input"][2]["call_id"] == "c1"
    item = ResponseFunctionToolCall(
        call_id="c1", name="buscar", arguments="{}", type="function_call"
    )
    txt = ResponseOutputMessage(
        id="m",
        role="assistant",
        status="completed",
        type="message",
        content=[ResponseOutputText(annotations=[], text="ok", type="output_text")],
    )
    resposta = Response.model_construct(output=[txt, item], usage=None)
    assert de_openai(resposta, "modelo").tool_calls == [ToolCall("c1", "buscar", {})]
    capturado = {}
    cliente = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kw: capturado.update(kw) or resposta)
    )
    assert OpenAIClient("modelo", "k", cliente=cliente).chat("sys", HIST, TOOLS).text == "ok"
    assert capturado["store"] is False and capturado["temperature"] == 0.2
    with pytest.raises(LLMError):
        de_openai(Response.model_construct(output=[], usage=None), "modelo")


def test_openai_argumentos_invalidos_e_temperatura():
    import openai
    from openai.types.responses import Response, ResponseFunctionToolCall

    for argumentos in ("{quebrado", "[]"):
        item = ResponseFunctionToolCall(
            call_id="c", name="x", arguments=argumentos, type="function_call"
        )
        with pytest.raises(LLMError):
            de_openai(Response.model_construct(output=[item], usage=None), "x")
    capturado = {}

    def criar(**kw):
        capturado.update(kw)
        raise openai.OpenAIError("caiu")

    cliente = SimpleNamespace(responses=SimpleNamespace(create=criar))
    with pytest.raises(LLMError, match="openai"):
        OpenAIClient("x", "k", temperature=None, cliente=cliente).chat("sys", HIST, [])
    assert "temperature" not in capturado and "tools" not in capturado


def test_conversao_openai_completa():
    from openai.types.responses import (
        Response,
        ResponseFunctionToolCall,
        ResponseOutputMessage,
        ResponseOutputText,
        ResponseUsage,
    )
    from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails

    def resposta(*itens, usage=None):
        return Response.model_construct(output=list(itens), usage=usage, model="snapshot")

    def texto(t):
        return ResponseOutputMessage(
            id="m",
            role="assistant",
            status="completed",
            type="message",
            content=[ResponseOutputText(annotations=[], text=t, type="output_text")],
        )

    def chamada(id_, name, args):
        return ResponseFunctionToolCall(
            call_id=id_, name=name, arguments=args, type="function_call"
        )

    uso = ResponseUsage(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        input_tokens_details=InputTokensDetails(cached_tokens=40, cache_write_tokens=0),
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
    )
    assert para_openai("sys", [Message("user", "oi")], []) == {
        "instructions": "sys",
        "input": [{"role": "user", "content": "oi"}],
    }
    assert para_openai("sys", HIST, TOOLS)["tools"] == [
        {
            "type": "function",
            "name": "buscar",
            "description": "Busca",
            "parameters": TOOLS[0].parameters,
            "strict": False,
        }
    ]
    r = de_openai(resposta(texto("Olá!"), usage=uso), "gpt-5.4-mini")
    assert (r.text, r.tool_calls, r.provider, r.model, r.usage) == (
        "Olá!",
        [],
        "openai",
        "gpt-5.4-mini",
        Usage(100, 20, 40),
    )
    r = de_openai(resposta(chamada("a", "buscar", '{"termo":"violão"}')), "x")
    assert (
        r.text is None
        and r.tool_calls == [ToolCall("a", "buscar", {"termo": "violão"})]
        and r.usage is None
    )
    r = de_openai(
        resposta(
            texto("Vou ver."),
            chamada("a", "buscar", ""),
            chamada("b", "politica", '{"topico":"pagamentos"}'),
        ),
        "x",
    )
    assert r.text == "Vou ver." and r.tool_calls == [
        ToolCall("a", "buscar", {}),
        ToolCall("b", "politica", {"topico": "pagamentos"}),
    ]
    capturado = {}
    cliente = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kw: capturado.update(kw) or resposta(texto("ok"), usage=uso)
        )
    )
    assert OpenAIClient("gpt-5.4-mini", "k", cliente=cliente).chat("sys", HIST, TOOLS).text == "ok"
    assert (
        capturado["model"] == "gpt-5.4-mini"
        and capturado["store"] is False
        and capturado["temperature"] == 0.2
        and capturado["instructions"] == "sys"
        and capturado["tools"]
    )


def test_historico_duas_chamadas_openai():
    c2 = ToolCall("c2", "politica", {"topico": "pagamentos"})
    hist = [
        Message("user", "oi"),
        Message("assistant", "Vou verificar.", [C1, c2]),
        Message("tool", "{}", tool_call_id="c1"),
        Message("tool", "{}", tool_call_id="c2"),
    ]
    itens = para_openai("sys", hist, TOOLS)["input"]
    assert [item.get("type", item.get("role")) for item in itens] == [
        "user",
        "assistant",
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
    ]
    assert itens[1] == {"role": "assistant", "content": "Vou verificar."}
    assert [item["call_id"] for item in itens[2:]] == ["c1", "c2", "c1", "c2"]
    assert "violão" in itens[2]["arguments"]


@pytest.mark.parametrize("effort", ["medium", "none", None])
def test_raciocinio(effort):
    from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText

    item = ResponseOutputMessage(
        id="m",
        role="assistant",
        status="completed",
        type="message",
        content=[ResponseOutputText(annotations=[], text="ok", type="output_text")],
    )
    resposta = Response.model_construct(output=[item], usage=None)
    capturado = {}
    cliente = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kw: capturado.update(kw) or resposta)
    )
    OpenAIClient("x", "k", cliente=cliente, reasoning_effort=effort).chat("sys", [], [])
    assert capturado.get("reasoning") == ({"effort": effort} if effort is not None else None)
    assert ("temperature" in capturado) == (effort in (None, "none"))
