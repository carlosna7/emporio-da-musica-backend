"""API HTTP sem estado sobre o agente: o cliente guarda o histórico e o reenvia a cada pergunta."""

import os
import secrets
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent import criar_agente
from app.config import Config, carregar_config
from app.db import CAMINHO_BANCO, conectar
from app.ingest import criar_banco
from app.llm.base import LLMClient, Message, criar_cliente
from app.tools import PASTA_LOGS

# Na Vercel só /tmp aceita escrita, e o banco gerado não vai para o git.
PASTA_TEMPORARIA = Path(tempfile.gettempdir()) / "emporio-da-musica"
MAX_ITENS_HISTORICO = 40
MAX_CHARS_ITEM_HISTORICO = 4000


class ItemHistorico(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_CHARS_ITEM_HISTORICO)


class PedidoChat(BaseModel):
    mensagem: str = Field(min_length=1)
    historico: list[ItemHistorico] = Field(default_factory=list, max_length=MAX_ITENS_HISTORICO)
    conversa_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class UsoChat(BaseModel):
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    custo_usd: float | None


class RespostaChat(BaseModel):
    resposta: str
    ferramentas: list[str]
    status: str
    conversa_id: str
    historico: list[ItemHistorico]
    uso: UsoChat


def na_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


def preparar_banco(caminho: Path = CAMINHO_BANCO) -> Path:
    if caminho.exists():
        return caminho
    destino = PASTA_TEMPORARIA / "emporio.db"
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        criar_banco(destino=destino)
    return destino


def criar_app(
    config: Config | None = None,
    llm: LLMClient | None = None,
    caminho_banco: Path | None = None,
    pasta_logs: Path | None = None,
) -> FastAPI:
    config = config or carregar_config()
    if llm is None:
        llm = criar_cliente(config.provider, config.model, reasoning_effort=config.reasoning_effort)
    banco = caminho_banco or preparar_banco()
    if pasta_logs is None:
        pasta_logs = PASTA_TEMPORARIA / "logs" if na_vercel() else PASTA_LOGS
    token = os.environ.get("API_TOKEN", "").strip()

    def verificar_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if token and not secrets.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="Token inválido ou ausente.")

    app = FastAPI(title="Empório da Música — Emilio", version="0.1.0")
    origens = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if origens:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origens,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "modelo": config.model}

    @app.post("/chat", dependencies=[Depends(verificar_token)])
    def chat(pedido: PedidoChat) -> RespostaChat:
        conversa_id = pedido.conversa_id or f"api-{uuid4().hex[:8]}"
        historico = [Message(item.role, item.content) for item in pedido.historico]
        conexao = conectar(banco)
        try:
            # Agente criado por requisição: a data e o expediente do prompt ficam sempre atuais.
            agente = criar_agente(config=config, llm=llm, conexao=conexao, pasta_logs=pasta_logs)
            resposta = agente.responder(historico, pedido.mensagem, conversa_id)
        finally:
            conexao.close()
        return RespostaChat(
            resposta=resposta.texto,
            ferramentas=resposta.tools_usadas,
            status=resposta.status,
            conversa_id=conversa_id,
            historico=[
                ItemHistorico(role=m.role, content=m.content) for m in resposta.para_historico
            ],
            uso=UsoChat(
                input_tokens=resposta.usage.input_tokens,
                output_tokens=resposta.usage.output_tokens,
                cached_tokens=resposta.usage.cached_tokens,
                custo_usd=resposta.custo_usd,
            ),
        )

    return app
