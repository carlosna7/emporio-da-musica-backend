from datetime import datetime

import pytest

from app.config import FUSO_LOJA, Config, agora_da_loja, carregar_config


@pytest.fixture(autouse=True)
def limpar(monkeypatch):
    for nome in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_REASONING_EFFORT",
        "AGENT_TODAY",
        "MAX_TOOL_ITERATIONS",
        "HISTORY_WINDOW",
        "MAX_MESSAGE_CHARS",
    ):
        monkeypatch.setenv(nome, "")
        monkeypatch.delenv(nome)


def test_padrao_e_ambiente(monkeypatch):
    assert carregar_config(None) == Config()
    assert Config() == Config("openai", "gpt-6-luna", "medium", None, 5, 20, 1000)
    for nome, valor in {
        "LLM_PROVIDER": " Anthropic ",
        "LLM_MODEL": "claude",
        "LLM_REASONING_EFFORT": " LOW ",
        "AGENT_TODAY": "2026-01-22",
        "MAX_TOOL_ITERATIONS": "3",
        "HISTORY_WINDOW": "10",
        "MAX_MESSAGE_CHARS": "500",
    }.items():
        monkeypatch.setenv(nome, valor)
    assert carregar_config(None) == Config(
        "anthropic", "claude", "low", datetime(2026, 1, 22, 10), 3, 10, 500
    )


@pytest.mark.parametrize(
    "nome,valor",
    [
        ("LLM_REASONING_EFFORT", "máximo"),
        ("AGENT_TODAY", "22/01/2026"),
        ("AGENT_TODAY", "2026-13-01"),
        ("AGENT_TODAY", "20260122"),
        ("AGENT_TODAY", "2026-11-03T25:00"),
        ("AGENT_TODAY", "2026-11-03 19:30"),
        ("MAX_TOOL_ITERATIONS", "0"),
        ("MAX_TOOL_ITERATIONS", "-1"),
        ("MAX_TOOL_ITERATIONS", "abc"),
        ("MAX_TOOL_ITERATIONS", "2.5"),
        ("HISTORY_WINDOW", "0"),
        ("MAX_MESSAGE_CHARS", "0"),
    ],
)
def test_invalidos(monkeypatch, nome, valor):
    monkeypatch.setenv(nome, valor)
    with pytest.raises(ValueError, match=nome):
        carregar_config(None)


def test_arquivo_e_hora(monkeypatch, tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text("MAX_MESSAGE_CHARS=321", encoding="utf-8")
    assert carregar_config(arquivo).max_message_chars == 321
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "999")
    assert carregar_config(arquivo).max_message_chars == 999
    monkeypatch.setenv("AGENT_TODAY", "2026-11-03T19:30")
    assert agora_da_loja(carregar_config(None)) == datetime(2026, 11, 3, 19, 30)
    antes = datetime.now(FUSO_LOJA).replace(tzinfo=None)
    atual = agora_da_loja(Config())
    assert antes <= atual <= datetime.now(FUSO_LOJA).replace(tzinfo=None)
    assert atual.tzinfo is None


def test_valores_vazios_none_e_arquivo_inexistente(monkeypatch, tmp_path):
    for nome in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_REASONING_EFFORT",
        "AGENT_TODAY",
        "MAX_TOOL_ITERATIONS",
        "HISTORY_WINDOW",
        "MAX_MESSAGE_CHARS",
    ):
        monkeypatch.setenv(nome, "   ")
    assert carregar_config(None) == Config()
    assert carregar_config(tmp_path / "ausente") == Config()
    monkeypatch.setenv("LLM_REASONING_EFFORT", "none")
    assert carregar_config(None).reasoning_effort == "none"


def test_mensagens_de_validacao(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "máximo")
    with pytest.raises(ValueError, match="LLM_REASONING_EFFORT.*medium"):
        carregar_config(None)
    monkeypatch.delenv("LLM_REASONING_EFFORT")
    monkeypatch.setenv("AGENT_TODAY", "invalida")
    with pytest.raises(ValueError, match="AGENT_TODAY.*AAAA-MM-DD"):
        carregar_config(None)
