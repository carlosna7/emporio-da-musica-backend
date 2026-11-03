import json
from datetime import datetime
from pathlib import Path

from app.llm.base import Usage
from app.llm.precos_modelos import custo_estimado

ARQUIVO_USO = "llm_calls.jsonl"


def registrar_chamada(
    pasta_logs: Path,
    *,
    conversa_id: str,
    turno: int,
    iteracao: int,
    provider: str,
    model: str,
    usage: Usage | None,
    latencia_ms: int,
    tools_chamadas: list[str],
    status: str,
    erro: str | None = None,
) -> dict:
    registro = dict(
        ts=datetime.now().isoformat(timespec="seconds"),
        conversa_id=conversa_id,
        turno=turno,
        iteracao=iteracao,
        provider=provider,
        model=model,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        cached_tokens=usage.cached_tokens if usage else None,
        latencia_ms=latencia_ms,
        tools_chamadas=tools_chamadas,
        custo_usd=custo_estimado(model, usage),
        status=status,
        erro=erro,
    )
    pasta_logs.mkdir(parents=True, exist_ok=True)
    with (pasta_logs / ARQUIVO_USO).open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro
