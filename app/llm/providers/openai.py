import json

import openai

from app.llm.base import LLMError, LLMResponse, ToolCall, Usage


def para_openai(system, messages, tools):
    itens = []
    for m in messages:
        if m.role == "tool":
            itens.append(
                {"type": "function_call_output", "call_id": m.tool_call_id, "output": m.content}
            )
        else:
            if m.content:
                itens.append({"role": m.role, "content": m.content})
            for tc in m.tool_calls:
                itens.append(
                    {
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    }
                )
    resultado = {"instructions": system, "input": itens}
    if tools:
        resultado["tools"] = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "strict": False,
            }
            for t in tools
        ]
    return resultado


def de_openai(resposta, model):
    textos, calls = [], []
    for item in resposta.output:
        if item.type == "message":
            textos.extend(p.text for p in item.content if p.type == "output_text")
        elif item.type == "function_call":
            try:
                args = json.loads(item.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("argumentos devem ser objeto")
            except (ValueError, TypeError) as erro:
                raise LLMError("argumentos de tool inválidos") from erro
            calls.append(ToolCall(item.call_id, item.name, args))
    texto = "".join(textos) or None
    if texto is None and not calls:
        raise LLMError("resposta vazia do provedor")
    u = resposta.usage
    usage = (
        None
        if u is None
        else Usage(
            u.input_tokens,
            u.output_tokens,
            (u.input_tokens_details.cached_tokens or 0) if u.input_tokens_details else 0,
        )
    )
    return LLMResponse(texto, calls, usage, "openai", model)


class OpenAIClient:
    def __init__(self, model, api_key, temperature=0.2, cliente=None, reasoning_effort=None):
        self.model, self.temperature = model, temperature
        self.reasoning_effort = reasoning_effort
        self._cliente = (
            cliente if cliente is not None else openai.OpenAI(api_key=api_key, timeout=60.0)
        )

    def chat(self, system, messages, tools):
        extras = {"store": False}
        if self.reasoning_effort is not None:
            extras["reasoning"] = {"effort": self.reasoning_effort}
        if self.temperature is not None and self.reasoning_effort in (None, "none"):
            extras["temperature"] = self.temperature
        try:
            return de_openai(
                self._cliente.responses.create(
                    model=self.model, **extras, **para_openai(system, messages, tools)
                ),
                self.model,
            )
        except openai.OpenAIError as erro:
            raise LLMError(f"openai: {erro}") from erro
