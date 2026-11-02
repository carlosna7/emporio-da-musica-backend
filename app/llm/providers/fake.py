from app.llm.base import LLMError, LLMResponse, ToolCall, Usage


class FakeLLM:
    def __init__(self, roteiro):
        self._roteiro = list(roteiro)
        self.chamadas = []

    def chat(self, system, messages, tools):
        self.chamadas.append({"system": system, "messages": list(messages), "tools": list(tools)})
        if not self._roteiro:
            raise LLMError("FakeLLM: roteiro esgotado")
        return self._roteiro.pop(0)


def resposta_texto(texto):
    return LLMResponse(texto, [], Usage(10, 5), "fake", "fake")


def resposta_tool(name, **arguments):
    return LLMResponse(
        None, [ToolCall(f"call_{name}", name, arguments)], Usage(10, 5), "fake", "fake"
    )
