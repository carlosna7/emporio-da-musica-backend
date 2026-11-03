import json

from app.llm.base import Usage
from app.uso import registrar_chamada


def test_registro(tmp_path):
    args = dict(
        conversa_id="c",
        turno=1,
        iteracao=1,
        provider="fake",
        model="fake",
        usage=Usage(10, 5),
        latencia_ms=3,
        tools_chamadas=["ação"],
        status="ok",
    )
    registro = registrar_chamada(tmp_path, **args)
    assert list(registro) == [
        "ts",
        "conversa_id",
        "turno",
        "iteracao",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "latencia_ms",
        "tools_chamadas",
        "custo_usd",
        "status",
        "erro",
    ]
    assert registro["custo_usd"] is None
    assert json.loads((tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8")) == registro


def test_uso_sem_dados_e_acumulo(tmp_path):
    from datetime import datetime

    import pytest

    pasta = tmp_path / "logs"
    args = dict(
        conversa_id="c1",
        turno=2,
        iteracao=1,
        provider="openai",
        model="gpt-5.4-mini",
        usage=Usage(10000, 1000, 4000),
        latencia_ms=850,
        tools_chamadas=["buscar_produtos"],
        status="ok",
    )
    r = registrar_chamada(pasta, **args)
    assert r["custo_usd"] == pytest.approx(0.0093)
    assert datetime.fromisoformat(r["ts"])
    args.update(usage=None, status="erro", erro="conexão recusada")
    r2 = registrar_chamada(pasta, **args)
    assert all(
        r2[k] is None for k in ("input_tokens", "output_tokens", "cached_tokens", "custo_usd")
    )
    texto = (pasta / "llm_calls.jsonl").read_text(encoding="utf-8")
    assert "conexão recusada" in texto and [json.loads(linha) for linha in texto.splitlines()] == [
        r,
        r2,
    ]
