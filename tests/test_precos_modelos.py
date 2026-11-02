import pytest

from app.llm.base import Message, ToolCall, ToolSpec, Usage
from app.llm.precos_modelos import PrecoModelo, custo_estimado

C1 = ToolCall("c1", "buscar", {"termo": "violão"})
TOOLS = [ToolSpec("buscar", "Busca", {"type": "object", "properties": {}})]
HIST = [
    Message("user", "oi"),
    Message("assistant", "", [C1]),
    Message("tool", '{"itens": []}', tool_call_id="c1"),
]


def test_precos():
    assert custo_estimado("gpt-5.4-mini", Usage(10000, 1000, 4000)) == pytest.approx(0.0093)
    assert custo_estimado("desconhecido", Usage(1, 1)) is None
    assert PrecoModelo(0.75, 4.5, 0.075).entrada_cache == 0.075


def test_precos_exatos_e_fallback(monkeypatch):
    from app.llm.precos_modelos import PRECOS

    assert PRECOS["gpt-5.4-mini"] == PrecoModelo(0.75, 4.5, 0.075)
    assert custo_estimado("gpt-5.4-mini", Usage(1_000_000, 1_000_000)) == 5.25
    assert custo_estimado("gpt-5.4-mini-2026-03-17", Usage(1, 1)) is None
    assert custo_estimado("gpt-5.4-mini", None) is None
    monkeypatch.setitem(PRECOS, "x", PrecoModelo(1, 2))
    assert custo_estimado("x", Usage(1_000_000, 0, 500_000)) == 1
