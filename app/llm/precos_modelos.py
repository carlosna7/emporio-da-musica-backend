# Preços Standard consultados em 2026-11-02:
# https://developers.openai.com/api/docs/pricing
# https://platform.claude.com/docs/en/about-claude/pricing
# https://aistudio.google.com/docs/pricing
from dataclasses import dataclass

from app.llm.base import Usage

CONSULTADO_EM = "2026-11-02"


@dataclass(frozen=True)
class PrecoModelo:
    entrada: float
    saida: float
    entrada_cache: float | None = None


PRECOS = {
    "gpt-5.4-mini": PrecoModelo(0.75, 4.5, 0.075),
    "gpt-6-luna": PrecoModelo(0.1, 0.5, 0.01),
    "claude-haiku-5-5": PrecoModelo(0.1, 0.5, 0.01),
    "gemini-3.5-flash-lite": PrecoModelo(0.3, 2.5, 0.03),
}


def custo_estimado(model: str, usage: Usage | None) -> float | None:
    p = PRECOS.get(model)
    if p is None or usage is None:
        return None
    cache = p.entrada_cache if p.entrada_cache is not None else p.entrada
    return round(
        (
            (usage.input_tokens - usage.cached_tokens) * p.entrada
            + usage.cached_tokens * cache
            + usage.output_tokens * p.saida
        )
        / 1_000_000,
        6,
    )
