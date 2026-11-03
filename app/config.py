import os
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ARQUIVO_ENV = Path(__file__).resolve().parents[1] / ".env"
FUSO_LOJA = timezone(timedelta(hours=-4))
HORA_FIXA = time(10, 0)


@dataclass(frozen=True)
class Config:
    provider: str = "openai"
    model: str = "gpt-6-luna"
    reasoning_effort: str | None = "medium"
    agora_fixo: datetime | None = None
    max_tool_iterations: int = 5
    history_window: int = 20
    max_message_chars: int = 1000


def carregar_config(arquivo_env: Path | None = ARQUIVO_ENV) -> Config:
    if arquivo_env is not None:
        load_dotenv(arquivo_env, override=False)

    def valor(nome, padrao):
        return os.environ.get(nome, "").strip() or padrao

    effort = valor("LLM_REASONING_EFFORT", "medium").lower()
    if effort not in ("none", "low", "medium", "high"):
        raise ValueError("LLM_REASONING_EFFORT: valores válidos: none, low, medium, high")
    data = valor("AGENT_TODAY", "")
    agora = None
    if data:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?", data):
                raise ValueError
            agora = datetime.fromisoformat(data)
            if len(data) == 10:
                agora = datetime.combine(agora.date(), HORA_FIXA)
        except ValueError as erro:
            raise ValueError("AGENT_TODAY deve seguir AAAA-MM-DD ou AAAA-MM-DDTHH:MM") from erro

    def inteiro(nome, padrao):
        try:
            n = int(valor(nome, str(padrao)))
            if n < 1:
                raise ValueError
            return n
        except ValueError as erro:
            raise ValueError(f"{nome} deve ser inteiro >= 1") from erro

    return Config(
        valor("LLM_PROVIDER", "openai").lower(),
        valor("LLM_MODEL", "gpt-6-luna"),
        effort,
        agora,
        inteiro("MAX_TOOL_ITERATIONS", 5),
        inteiro("HISTORY_WINDOW", 20),
        inteiro("MAX_MESSAGE_CHARS", 1000),
    )


def agora_da_loja(config: Config) -> datetime:
    return (
        config.agora_fixo
        if config.agora_fixo is not None
        else datetime.now(FUSO_LOJA).replace(tzinfo=None)
    )
