from types import SimpleNamespace

import pytest

from app.llm.base import LLMError, Message, ToolCall, ToolSpec, Usage
from app.llm.providers.openai import para_openai

pytest.importorskip("google.genai")

C1 = ToolCall("c1", "buscar", {"termo": "violão"})
TOOLS = [ToolSpec("buscar", "Busca", {"type": "object", "properties": {}})]
HIST = [
    Message("user", "oi"),
    Message("assistant", "", [C1]),
    Message("tool", '{"itens": []}', tool_call_id="c1"),
]


def test_gemini():
    pytest.importorskip("google.genai")
    from google.genai import types

    from app.llm.providers.gemini import de_gemini, para_gemini

    resultado = para_gemini("sys", HIST, TOOLS)
    assert resultado["contents"][2].parts[0].function_response.name == "buscar"
    original = types.Content(
        role="model",
        parts=[
            types.Part(
                function_call=types.FunctionCall(name="buscar", args={}), thought_signature=b"sig"
            )
        ],
    )
    resp = types.GenerateContentResponse(candidates=[types.Candidate(content=original)])
    convertido = de_gemini(resp, "modelo")
    assert convertido.tool_calls[0].id == "gemini_0_buscar"
    assert (
        para_gemini(
            "sys", [Message("assistant", "", convertido.tool_calls, raw=convertido.raw)], []
        )["contents"][0]
        is convertido.raw
    )
    with pytest.raises(LLMError):
        para_gemini("sys", [Message("tool", "{}", tool_call_id="ausente")], [])


def test_gemini_erro_sdk_e_usage():
    pytest.importorskip("google.genai")
    from google.genai import errors, types

    from app.llm.providers.gemini import GeminiClient, de_gemini, para_gemini

    capturado = {}

    def criar(**kw):
        capturado.update(kw)
        raise errors.APIError(500, {"error": {"message": "caiu"}})

    with pytest.raises(LLMError, match="gemini"):
        GeminiClient(
            "x", "k", cliente=SimpleNamespace(models=SimpleNamespace(generate_content=criar))
        ).chat("sys", HIST, TOOLS)
    assert capturado["config"].temperature is None
    partes = [types.Part(text="pensando", thought=True), types.Part(text="ok")]
    uso = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=100,
        candidates_token_count=10,
        thoughts_token_count=5,
        cached_content_token_count=60,
    )
    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=partes))], usage_metadata=uso
    )
    convertido = de_gemini(resp, "x")
    assert convertido.text == "ok" and convertido.usage == Usage(100, 15, 60)
    assert para_gemini("sys", HIST[:2] + [Message("tool", "texto", tool_call_id="c1")], [])[
        "contents"
    ][2].parts[0].function_response.response == {"result": "texto"}
    with pytest.raises(LLMError):
        de_gemini(types.GenerateContentResponse(candidates=[]), "x")


def test_gemini_ids_gerados_e_resultado():
    pytest.importorskip("google.genai")
    from app.llm.providers.gemini import para_gemini

    call = ToolCall("gemini_0_buscar", "buscar", {})
    hist = [Message("assistant", "", [call]), Message("tool", "{}", tool_call_id=call.id)]
    partes = para_gemini("", hist, [])["contents"]
    assert partes[0].parts[0].function_call.id is None
    assert partes[1].parts[0].function_response.id is None


def test_historico_duas_chamadas_e_raw():
    pytest.importorskip("anthropic")
    pytest.importorskip("google.genai")
    from app.llm.providers.anthropic import para_anthropic
    from app.llm.providers.gemini import para_gemini

    c2 = ToolCall("c2", "politica", {"topico": "pagamentos"})
    hist = [
        Message("user", "oi"),
        Message("assistant", "Vou verificar.", [C1, c2]),
        Message("tool", "{}", tool_call_id="c1"),
        Message("tool", "{}", tool_call_id="c2"),
    ]
    aberto = para_openai("sys", hist, TOOLS)["input"]
    assert [x.get("type", x.get("role")) for x in aberto] == [
        "user",
        "assistant",
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
    ]
    assert "violão" in aberto[2]["arguments"]
    ant = para_anthropic("sys", hist, TOOLS)["messages"]
    assert len(ant) == 3 and len(ant[1]["content"]) == 3 and len(ant[2]["content"]) == 2
    gem = para_gemini("sys", hist, TOOLS)["contents"]
    assert len(gem) == 3 and len(gem[1].parts) == 3 and len(gem[2].parts) == 2
    assert [p.function_response.name for p in gem[2].parts] == ["buscar", "politica"]


def test_conversao_gemini_completa():
    pytest.importorskip("google.genai")
    from google.genai import types

    from app.llm.providers.gemini import de_gemini, para_gemini

    def resposta(*partes, usage=None):
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=list(partes)))],
            usage_metadata=usage,
        )

    def fc(name, args, id_=None, assinatura=None):
        return types.Part(
            function_call=types.FunctionCall(id=id_, name=name, args=args),
            thought_signature=assinatura,
        )

    simples = para_gemini("sys", [Message("user", "oi")], [])
    assert simples["contents"] == [types.Content(role="user", parts=[types.Part(text="oi")])]
    assert (
        simples["config"].system_instruction == "sys"
        and simples["config"].tools is None
        and simples["config"].temperature is None
    )
    saida = para_gemini("sys", HIST, TOOLS)
    declaracao = saida["config"].tools[0].function_declarations[0]
    assert declaracao.name == "buscar" and declaracao.parameters_json_schema == TOOLS[0].parameters
    assert saida["contents"][1] == types.Content(
        role="model",
        parts=[
            types.Part(function_call=types.FunctionCall(id="c1", name="buscar", args=C1.arguments))
        ],
    )
    assert saida["contents"][2] == types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id="c1", name="buscar", response={"result": {"itens": []}}
                )
            )
        ],
    )
    r = de_gemini(resposta(types.Part(text="Olá!")), "modelo")
    assert (r.text, r.tool_calls, r.provider, r.usage) == ("Olá!", [], "gemini", None)
    r = de_gemini(resposta(fc("buscar", {"termo": "violão"}, assinatura=b"sig")), "modelo")
    assert r.text is None and r.tool_calls == [
        ToolCall("gemini_0_buscar", "buscar", {"termo": "violão"})
    ]
    reconvertido = para_gemini("sys", [Message("assistant", "", r.tool_calls, raw=r.raw)], [])[
        "contents"
    ][0]
    assert reconvertido is r.raw and reconvertido.parts[0].thought_signature == b"sig"
    r = de_gemini(
        resposta(fc("buscar", {}, "a"), fc("politica", {"topico": "pagamentos"}, "b")), "modelo"
    )
    assert [c.id for c in r.tool_calls] == ["a", "b"]


def test_chat_gemini_sucesso():
    pytest.importorskip("google.genai")
    from google.genai import types

    from app.llm.providers.gemini import GeminiClient

    capturado = {}
    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[types.Part(text="ok")]))]
    )
    cliente = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: capturado.update(kw) or resp)
    )
    assert GeminiClient("modelo", "k", cliente=cliente).chat("sys", HIST, TOOLS).text == "ok"
    assert capturado["model"] == "modelo" and "contents" in capturado and "config" in capturado
