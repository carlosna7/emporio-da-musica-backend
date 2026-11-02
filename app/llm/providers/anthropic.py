import anthropic

from app.llm.base import LLMError, LLMResponse, ToolCall, Usage

MAX_TOKENS = 4096


def para_anthropic(system, messages, tools):
    saida = []
    for m in messages:
        if m.role == "tool":
            bloco = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            if saida and saida[-1]["role"] == "user" and isinstance(saida[-1]["content"], list):
                saida[-1]["content"].append(bloco)
            else:
                saida.append({"role": "user", "content": [bloco]})
        elif m.role == "assistant":
            conteudo = m.raw
            if conteudo is None:
                if m.tool_calls:
                    conteudo = [{"type": "text", "text": m.content}] if m.content else []
                    conteudo += [
                        {"type": "tool_use", "id": t.id, "name": t.name, "input": t.arguments}
                        for t in m.tool_calls
                    ]
                else:
                    conteudo = m.content
            saida.append({"role": "assistant", "content": conteudo})
        else:
            saida.append({"role": "user", "content": m.content})
    resultado = {"messages": saida}
    if system:
        resultado["system"] = system
    if tools:
        resultado["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
    return resultado


def de_anthropic(resposta, model):
    texto = "".join(b.text for b in resposta.content if b.type == "text") or None
    calls = [
        ToolCall(b.id, b.name, dict(b.input)) for b in resposta.content if b.type == "tool_use"
    ]
    if texto is None and not calls:
        raise LLMError("resposta vazia do provedor")
    u = resposta.usage
    if u is None:
        usage = None
    else:
        leitura = getattr(u, "cache_read_input_tokens", None) or 0
        escrita = getattr(u, "cache_creation_input_tokens", None) or 0
        usage = Usage(u.input_tokens + leitura + escrita, u.output_tokens, leitura)
    return LLMResponse(
        texto,
        calls,
        usage,
        "anthropic",
        model,
        [b.model_dump(exclude_none=True) for b in resposta.content],
    )


class AnthropicClient:
    def __init__(self, model, api_key, cliente=None):
        self.model = model
        self._cliente = (
            cliente if cliente is not None else anthropic.Anthropic(api_key=api_key, timeout=60.0)
        )

    def chat(self, system, messages, tools):
        try:
            return de_anthropic(
                self._cliente.messages.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    **para_anthropic(system, messages, tools),
                ),
                self.model,
            )
        except anthropic.AnthropicError as erro:
            raise LLMError(f"anthropic: {erro}") from erro
