import pytest

from app.llm.base import LLMError, Message, ToolCall, ToolSpec, Usage, criar_cliente
from app.llm.providers.openai import OpenAIClient

C1 = ToolCall("c1", "buscar", {"termo": "violão"})
TOOLS = [ToolSpec("buscar", "Busca", {"type": "object", "properties": {}})]
HIST = [
    Message("user", "oi"),
    Message("assistant", "", [C1]),
    Message("tool", '{"itens": []}', tool_call_id="c1"),
]


def test_fabrica(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for provider, model in [("invalido", "x"), ("openai", ""), ("openai", "x")]:
        with pytest.raises(LLMError):
            criar_cliente(provider, model)
    assert criar_cliente(" OpenAI ", "gpt-5.4-mini", "k").model == "gpt-5.4-mini"


def test_imports_sem_sdk():
    import subprocess
    import sys

    codigo = "import sys; import app.llm.base, app.llm.providers.fake; "
    codigo += "assert not any(x in sys.modules for x in ('openai', 'anthropic', 'google.genai'))"
    subprocess.run([sys.executable, "-c", codigo], check=True)


def test_fabrica_extra_ausente(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.delitem(sys.modules, "app.llm.providers.anthropic", raising=False)
    with pytest.raises(LLMError, match="pip install"):
        criar_cliente("anthropic", "modelo", "k")


def test_fabrica_chave_em_branco(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "  ")
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        criar_cliente("openai", "modelo")
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        criar_cliente("openai", "modelo", "  ")


def test_tipos_neutros():
    from app.llm.base import LLMResponse

    a, b = Message("user", "oi"), Message("user", "oi")
    assert a.tool_calls == [] and a.tool_call_id is None and a.raw is None
    a.tool_calls.append(C1)
    assert b.tool_calls == []
    assert Message("assistant", "x", raw=[1]) == Message("assistant", "x")
    assert LLMResponse("x", [], None, "fake", "fake", raw=[1]) == LLMResponse(
        "x", [], None, "fake", "fake"
    )
    assert Usage(10, 5).cached_tokens == 0


def test_fabrica_detalhes(monkeypatch):
    with pytest.raises(LLMError) as erro:
        criar_cliente("mistral", "x", "k")
    assert all(p in str(erro.value) for p in ("openai", "anthropic", "gemini"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    cliente = criar_cliente(" OpenAI ", "gpt-5.4-mini")
    assert isinstance(cliente, OpenAIClient) and cliente.model == "gpt-5.4-mini"


def test_fabrica_raciocinio(monkeypatch):
    from app.llm.base import criar_cliente

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert (
        criar_cliente("openai", "gpt-6-luna", reasoning_effort="medium").reasoning_effort
        == "medium"
    )


def test_anthropic_ignora_raciocinio():
    pytest.importorskip("anthropic")
    from app.llm.base import criar_cliente

    assert criar_cliente("anthropic", "claude-haiku-5-5", api_key="k", reasoning_effort="medium")
