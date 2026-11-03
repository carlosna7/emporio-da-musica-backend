import json
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.config import Config
from app.llm.base import LLMClient, LLMError, Message, ToolCall, ToolSpec, Usage
from app.tools import CANAL_WHATSAPP, PASTA_LOGS, Contexto, Ferramenta
from app.uso import registrar_chamada

MENSAGEM_LONGA = (
    "Sua mensagem ficou um pouco longa para mim (limite de {limite} caracteres). "
    "Pode resumir em poucas linhas?"
)
LIMITE_ITERACOES = (
    "Desculpe, não consegui resolver isso por aqui. Quer que eu passe o seu caso "
    f"para um atendente? Se preferir, fale com a equipe no WhatsApp {CANAL_WHATSAPP}."
)
ERRO_PROVEDOR = (
    "Desculpe, estou com uma instabilidade técnica agora. Tente de novo em instantes "
    f"ou fale com a equipe no WhatsApp {CANAL_WHATSAPP}."
)


@dataclass
class Resposta:
    texto: str
    tools_usadas: list[str]
    usage: Usage
    iteracoes: int
    custo_usd: float | None
    status: Literal["ok", "limite_iteracoes", "erro_llm", "mensagem_longa"]
    para_historico: list[Message]


class Agente:
    def __init__(
        self,
        llm: LLMClient,
        tools: dict[str, Ferramenta],
        ctx: Contexto,
        system: str,
        config: Config,
    ):
        self.llm, self.tools, self.ctx, self.system, self.config = llm, tools, ctx, system, config
        self.specs = [ToolSpec(nome, f.descricao, f.parametros) for nome, f in tools.items()]

    def _executar(self, tc: ToolCall, ctx: Contexto) -> dict:
        if tc.name not in self.tools:
            return {
                "erro": f"Ferramenta desconhecida: {tc.name}. Disponíveis: {', '.join(self.tools)}"
            }
        try:
            return self.tools[tc.name].funcao(**tc.arguments, ctx=ctx)
        except TypeError as erro:
            return {"erro": f"Argumentos inválidos para {tc.name}: {erro}"}
        except Exception:
            return {"erro": f"Não foi possível executar {tc.name} agora."}

    def responder(self, historico: list[Message], mensagem: str, conversa_id: str) -> Resposta:
        if len(mensagem) > self.config.max_message_chars:
            return Resposta(
                MENSAGEM_LONGA.format(limite=self.config.max_message_chars),
                [],
                Usage(0, 0),
                0,
                0.0,
                "mensagem_longa",
                [],
            )
        ctx = replace(self.ctx, conversa_id=conversa_id)
        turno = 1 + sum(m.role == "user" for m in historico)
        mensagens = list(historico[-self.config.history_window :]) + [Message("user", mensagem)]
        usadas, usage, custo = [], Usage(0, 0), 0.0

        def finalizar(texto, status, iteracao):
            return Resposta(
                texto,
                usadas,
                usage,
                iteracao,
                round(custo, 6) if custo is not None else None,
                status,
                [Message("user", mensagem), Message("assistant", texto)],
            )

        for iteracao in range(1, self.config.max_tool_iterations + 1):
            inicio = time.perf_counter()
            try:
                resp = self.llm.chat(self.system, mensagens, self.specs)
            except LLMError as erro:
                registrar_chamada(
                    ctx.pasta_logs,
                    conversa_id=conversa_id,
                    turno=turno,
                    iteracao=iteracao,
                    provider=self.config.provider,
                    model=self.config.model,
                    usage=None,
                    latencia_ms=round((time.perf_counter() - inicio) * 1000),
                    tools_chamadas=[],
                    status="erro",
                    erro=str(erro),
                )
                return finalizar(ERRO_PROVEDOR, "erro_llm", iteracao)
            registro = registrar_chamada(
                ctx.pasta_logs,
                conversa_id=conversa_id,
                turno=turno,
                iteracao=iteracao,
                provider=self.config.provider,
                model=self.config.model,
                usage=resp.usage,
                latencia_ms=round((time.perf_counter() - inicio) * 1000),
                tools_chamadas=[tc.name for tc in resp.tool_calls],
                status="ok",
            )
            if resp.usage is not None:
                usage.input_tokens += resp.usage.input_tokens
                usage.output_tokens += resp.usage.output_tokens
                usage.cached_tokens += resp.usage.cached_tokens
            if registro["custo_usd"] is None:
                custo = None
            elif custo is not None:
                custo += registro["custo_usd"]
            if not resp.tool_calls:
                return finalizar(resp.text.strip(), "ok", iteracao)
            if iteracao == self.config.max_tool_iterations:
                break
            mensagens.append(
                Message("assistant", resp.text or "", tool_calls=resp.tool_calls, raw=resp.raw)
            )
            for tc in resp.tool_calls:
                usadas.append(tc.name)
                mensagens.append(
                    Message(
                        "tool",
                        json.dumps(self._executar(tc, ctx), ensure_ascii=False),
                        tool_call_id=tc.id,
                    )
                )
        return finalizar(LIMITE_ITERACOES, "limite_iteracoes", self.config.max_tool_iterations)


def criar_agente(
    config: Config | None = None,
    llm: LLMClient | None = None,
    conexao: sqlite3.Connection | None = None,
    pasta_logs: Path = PASTA_LOGS,
    agora: datetime | None = None,
) -> Agente:
    from app.config import agora_da_loja, carregar_config
    from app.db import conectar
    from app.llm.base import criar_cliente
    from app.politicas import texto_da_secao
    from app.prompts import montar_system_prompt
    from app.tools import TOOLS

    if config is None:
        config = carregar_config()
    if agora is None:
        agora = agora_da_loja(config)
    if llm is None:
        llm = criar_cliente(config.provider, config.model, reasoning_effort=config.reasoning_effort)
    if conexao is None:
        conexao = conectar()
    ctx = Contexto(conexao=conexao, hoje=agora.date(), pasta_logs=pasta_logs)
    system = montar_system_prompt(agora, texto_da_secao(7), texto_da_secao(10))
    return Agente(llm, TOOLS, ctx, system, config)
