import json

from google import genai
from google.genai import types

from app.llm.base import LLMError, LLMResponse, ToolCall, Usage


def _id_real(id_):
    return None if id_ and id_.startswith("gemini_") else id_


def para_gemini(system, messages, tools):
    contents, nomes = [], {}
    anterior_tool = False
    for m in messages:
        if m.role == "tool":
            if m.tool_call_id not in nomes:
                raise LLMError("tool_call_id sem chamada anterior")
            try:
                resultado = json.loads(m.content)
            except (ValueError, TypeError):
                resultado = m.content
            parte = types.Part(
                function_response=types.FunctionResponse(
                    id=_id_real(m.tool_call_id),
                    name=nomes[m.tool_call_id],
                    response={"result": resultado},
                )
            )
            if anterior_tool:
                contents[-1].parts.append(parte)
            else:
                contents.append(types.Content(role="user", parts=[parte]))
        elif m.role == "assistant":
            nomes.update({t.id: t.name for t in m.tool_calls})
            partes = [types.Part(text=m.content)] if m.content else []
            partes += [
                types.Part(
                    function_call=types.FunctionCall(
                        id=_id_real(t.id), name=t.name, args=t.arguments
                    )
                )
                for t in m.tool_calls
            ]
            contents.append(
                m.raw if m.raw is not None else types.Content(role="model", parts=partes)
            )
        else:
            contents.append(types.Content(role="user", parts=[types.Part(text=m.content)]))
        anterior_tool = m.role == "tool"
    declaracoes = [
        types.FunctionDeclaration(
            name=t.name, description=t.description, parameters_json_schema=t.parameters
        )
        for t in tools
    ]
    config = types.GenerateContentConfig(
        system_instruction=system or None,
        tools=[types.Tool(function_declarations=declaracoes)] if declaracoes else None,
    )
    return {"contents": contents, "config": config}


def de_gemini(resposta, model):
    if not resposta.candidates or resposta.candidates[0].content is None:
        raise LLMError("resposta vazia do provedor")
    raw = resposta.candidates[0].content
    partes = raw.parts or []
    texto = "".join(p.text for p in partes if p.text and not p.thought) or None
    calls = []
    for i, p in enumerate(partes):
        if p.function_call:
            fc = p.function_call
            calls.append(ToolCall(fc.id or f"gemini_{i}_{fc.name}", fc.name, dict(fc.args or {})))
    if texto is None and not calls:
        raise LLMError("resposta vazia do provedor")
    u = resposta.usage_metadata
    usage = (
        None
        if u is None
        else Usage(
            u.prompt_token_count or 0,
            (u.candidates_token_count or 0) + (u.thoughts_token_count or 0),
            u.cached_content_token_count or 0,
        )
    )
    return LLMResponse(texto, calls, usage, "gemini", model, raw)


class GeminiClient:
    def __init__(self, model, api_key, cliente=None):
        self.model = model
        self._cliente = cliente if cliente is not None else genai.Client(api_key=api_key)

    def chat(self, system, messages, tools):
        try:
            return de_gemini(
                self._cliente.models.generate_content(
                    model=self.model, **para_gemini(system, messages, tools)
                ),
                self.model,
            )
        except genai.errors.APIError as erro:
            raise LLMError(f"gemini: {erro}") from erro
