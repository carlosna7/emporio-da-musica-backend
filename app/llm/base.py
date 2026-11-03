import os
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


class LLMError(Exception):
    """Erro na configuração ou resposta do provedor."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    raw: Any = field(default=None, repr=False, compare=False)


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    usage: Usage | None
    provider: str
    model: str
    raw: Any = field(default=None, repr=False, compare=False)


class LLMClient(Protocol):
    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse: ...


def criar_cliente(
    provider: str, model: str, api_key: str | None = None, reasoning_effort: str | None = None
) -> LLMClient:
    provider = provider.strip().lower()
    variaveis = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    if provider not in variaveis:
        raise LLMError("provedores válidos: openai, anthropic, gemini")
    if not model or not model.strip():
        raise LLMError("defina LLM_MODEL")
    chave = (api_key or os.environ.get(variaveis[provider], "")).strip()
    if not chave:
        raise LLMError(f"defina {variaveis[provider]} no .env")
    try:
        if provider == "openai":
            from app.llm.providers.openai import OpenAIClient as Cliente
        elif provider == "anthropic":
            from app.llm.providers.anthropic import AnthropicClient as Cliente
        else:
            from app.llm.providers.gemini import GeminiClient as Cliente
    except ImportError as erro:
        raise LLMError(f"instale o extra: pip install -e '.[{provider}]'") from erro
    if provider == "openai":
        return Cliente(model=model, api_key=chave, reasoning_effort=reasoning_effort)
    return Cliente(model=model, api_key=chave)
