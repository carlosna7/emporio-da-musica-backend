import json
import re
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from app.config import Config
from app.horario import situacao_loja
from app.llm.base import LLMError, Message, ToolCall, Usage
from app.llm.providers.fake import FakeLLM, resposta_texto, resposta_tool
from evals import exemplos

CFG = Config(provider="fake", model="fake")
CFG_LUNA = Config(provider="openai", model="gpt-6-luna", reasoning_effort="medium")
AGORA = datetime(2026, 11, 3, 10, 0)
RAIZ = Path(__file__).resolve().parents[1]


def roteiro(nome="01-teste", mensagens=("Quanto custa o Takamine GD20?", "E no PIX?"), agora=AGORA):
    return exemplos.Roteiro(nome, "Preço e PIX", "Mostra preço e memória.", agora, tuple(mensagens))


def linhas(arquivo):
    return ([json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]
            if arquivo.exists() else [])


def test_roteiros_validos_e_horarios():
    roteiros = exemplos.ROTEIROS
    assert 3 <= len(roteiros) <= 5
    assert len({r.nome for r in roteiros}) == len(roteiros)
    assert [r.nome[:2] for r in roteiros] == [f"{i:02}" for i in range(1, len(roteiros) + 1)]
    for r in roteiros:
        assert re.fullmatch(r"\d{2}-[a-z0-9-]+", r.nome)
        assert r.titulo.strip() and r.descricao.strip()
        assert len(r.mensagens) >= 2
        assert all(m.strip() and "\n" not in m and len(m) <= Config().max_message_chars
                   for m in r.mensagens)
    assert any(situacao_loja(r.agora).startswith("A loja está aberta") for r in roteiros)
    assert any(situacao_loja(r.agora).startswith("A loja está fechada") for r in roteiros)


def test_formatar_chamada():
    chamada = ToolCall("c1", "buscar_produtos", {
        "categoria": "Violões", "preco_max": 1000, "em_promocao": True,
    })
    assert exemplos.formatar_chamada(chamada) == (
        'buscar_produtos(categoria="Violões", preco_max=1000, em_promocao=true)'
    )
    assert exemplos.formatar_chamada(ToolCall("c2", "detalhes_produto", {})) == "detalhes_produto()"


def test_citar():
    assert exemplos.citar("Custa R$ 2.199,00.\n\nNo PIX:\n- R$ 2.089,05\n") == (
        "> Custa R$ 2.199,00.\n>\n> No PIX:\n> - R$ 2.089,05"
    )
    assert exemplos.citar("") == ">"


@pytest.fixture
def turnos():
    return [
        exemplos.TurnoExemplo(
            "Quanto custa o Takamine GD20?", "Custa R$ 2.199,00.\n\nNo PIX, R$ 2.089,05.",
            [ToolCall("c1", "buscar_produtos", {"termo": "takamine gd20"})],
            "ok", Usage(1000, 100, 800), 0.0001,
        ),
        exemplos.TurnoExemplo("E no PIX?", "R$ 2.089,05.", [], "ok", Usage(1200, 50, 1000),
                             0.00005),
    ]


def test_montar_markdown_exato(turnos):
    texto = exemplos.montar_markdown(
        roteiro(), turnos, config=CFG_LUNA, quando=datetime(2026, 11, 3, 18, 5),
    )
    assert texto == '''# Preço e PIX

Mostra preço e memória.

- **Data simulada:** terça-feira, 03/11/2026, 10:00 (horário de Campo Grande/MS). A loja está aberta agora, até as 18h.
- **Modelo:** openai · gpt-6-luna · esforço medium
- **Uso:** 2 turnos · 2200 tokens de entrada (1800 em cache) · 150 de saída · custo estimado US$ 0.000150
- **Gerado em:** 03/11/2026 18:05 por `python -m evals.exemplos` (conversa `exemplo-01-teste`), sem edição manual

## Conversa

**Cliente:** Quanto custa o Takamine GD20?

**Emilio:**

> Custa R$ 2.199,00.
>
> No PIX, R$ 2.089,05.

Ferramentas: `buscar_produtos(termo="takamine gd20")`

**Cliente:** E no PIX?

**Emilio:**

> R$ 2.089,05.

Ferramentas: nenhuma
'''  # noqa: E501


def test_montar_markdown_variacoes(turnos):
    turnos[0].chamadas = [
        ToolCall("a", "consultar_pedido", {"order_id": 5, "email_ou_telefone": "a@b.com"}),
        ToolCall("b", "consultar_politica", {"topico": "trocas_devolucoes"}),
    ]
    turnos[1].status = "erro_llm"
    turnos[1].custo_usd = None
    texto = exemplos.montar_markdown(
        roteiro(agora=datetime(2026, 11, 8, 15)), turnos,
        config=Config(reasoning_effort=None), quando=AGORA,
    )
    assert ('Ferramentas: `consultar_pedido(order_id=5, email_ou_telefone="a@b.com")`, '
            '`consultar_politica(topico="trocas_devolucoes")`') in texto
    assert "Ferramentas: nenhuma · status: `erro_llm`" in texto
    assert "custo estimado n/d" in texto
    assert "esforço none" in texto
    assert ("domingo, 08/11/2026, 15:00 (horário de Campo Grande/MS). "
            "A loja está fechada agora. A equipe volta amanhã, "
            "segunda-feira (09/11), às 9h.") in texto


def test_gerar_conversa_memoria_chamadas_e_logs(conexao, tmp_path):
    llm = FakeLLM([
        resposta_tool("buscar_produtos", termo="takamine gd20"),
        resposta_texto("Custa R$ 2.199,00."), resposta_texto("No PIX, R$ 2.089,05."),
    ])
    turnos = exemplos.gerar_conversa(
        roteiro(), config=CFG, conexao=conexao, pasta_logs=tmp_path / "logs", llm=llm,
    )
    assert len(turnos) == 2
    assert turnos[0].chamadas == [
        ToolCall("call_buscar_produtos", "buscar_produtos", {"termo": "takamine gd20"}),
    ]
    assert turnos[1].chamadas == []
    assert turnos[0].usage == Usage(20, 10)
    assert turnos[0].custo_usd is None
    assert turnos[1].texto == "No PIX, R$ 2.089,05."
    assert llm.chamadas[2]["messages"] == [
        Message("user", "Quanto custa o Takamine GD20?"),
        Message("assistant", "Custa R$ 2.199,00."), Message("user", "E no PIX?"),
    ]
    logs = linhas(tmp_path / "logs" / "llm_calls.jsonl")
    assert len(logs) == 3
    assert {linha["conversa_id"] for linha in logs} == {"exemplo-01-teste"}
    assert [linha["turno"] for linha in logs] == [1, 1, 2]


def test_gerar_conversa_agora_no_prompt_e_tools(conexao, tmp_path):
    llm = FakeLLM([
        resposta_tool("encaminhar_atendente", motivo="pedido_do_cliente",
                      resumo="quer falar com uma pessoa"),
        resposta_texto("Protocolo gerado."), resposta_texto("De nada!"),
    ])
    exemplos.gerar_conversa(
        roteiro(mensagens=("quero falar com alguém", "ok"), agora=datetime(2026, 11, 8, 15)),
        config=replace(CFG, agora_fixo=datetime(2025, 1, 1)), conexao=conexao,
        pasta_logs=tmp_path / "logs", llm=llm,
    )
    assert "domingo, 08/11/2026 (2026-11-08), 15:00" in llm.chamadas[0]["system"]
    [handoff] = linhas(tmp_path / "logs" / "handoffs.jsonl")
    assert handoff["protocolo"].startswith("EM-20261108-")
    assert handoff["conversa_id"] == "exemplo-01-teste"


def test_gerar_conversa_continua_apos_erro_llm(conexao, tmp_path):
    turnos = exemplos.gerar_conversa(
        roteiro(), config=CFG, conexao=conexao, pasta_logs=tmp_path, llm=FakeLLM([]),
    )
    assert len(turnos) == 2
    assert all(t.status == "erro_llm" for t in turnos)


def gerar(roteiros, respostas, conexao, tmp_path, config=CFG):
    saida = []
    caminhos = exemplos.gerar_exemplos(
        roteiros, config=config, conexao=conexao, pasta_logs=tmp_path / "logs",
        pasta_saida=tmp_path / "ex", llm=FakeLLM(respostas), quando=AGORA, escrever=saida.append,
    )
    return caminhos, saida


def test_gerar_exemplos_grava_e_sobrescreve(conexao, tmp_path):
    pasta = tmp_path / "ex"
    pasta.mkdir()
    (pasta / "01-a.md").write_text("velho", encoding="utf-8")
    caminhos, saida = gerar(
        [roteiro("01-a", ("oi", "tchau")), roteiro("02-b", ("oi", "tchau"))],
        [resposta_texto("Olá!")] * 4, conexao, tmp_path,
    )
    assert caminhos == [pasta / "01-a.md", pasta / "02-b.md"]
    assert all(p.read_text(encoding="utf-8").startswith("# Preço e PIX\n") for p in caminhos)
    assert "velho" not in caminhos[0].read_text(encoding="utf-8")
    assert saida == [
        "[1/2] 01-a: 2 turnos · custo estimado n/d",
        "[2/2] 02-b: 2 turnos · custo estimado n/d",
        "Total: 4 turnos · custo estimado n/d",
    ]


def test_gerar_exemplos_avisa_status(conexao, tmp_path):
    [caminho], saida = gerar([roteiro()], [resposta_texto("Olá!")], conexao, tmp_path)
    assert "status: `erro_llm`" in caminho.read_text(encoding="utf-8")
    assert saida[0].endswith(" · ATENÇÃO: turno(s) 2 sem status ok")


def test_gerar_exemplos_soma_custo_conhecido(conexao, tmp_path):
    [caminho], saida = gerar(
        [roteiro()], [resposta_texto("a"), resposta_texto("b")], conexao, tmp_path,
        config=Config(provider="openai", model="gpt-5.4-mini"),
    )
    assert saida[0] == "[1/1] 01-teste: 2 turnos · custo estimado US$ 0.000060"
    assert "custo estimado US$ 0.000060" in caminho.read_text(encoding="utf-8")


def test_main_sem_rede(monkeypatch, banco, tmp_path, capsys):
    argumentos = []

    def cliente(*args, **kwargs):
        argumentos.append((args, kwargs))
        return FakeLLM([resposta_texto("Aqui é o Emilio.")] * sum(
            len(r.mensagens) for r in exemplos.ROTEIROS
        ))

    monkeypatch.setattr(exemplos, "carregar_config", lambda: CFG)
    monkeypatch.setattr(exemplos, "criar_cliente", cliente)
    monkeypatch.setattr(exemplos, "CAMINHO_BANCO", banco)
    monkeypatch.setattr(exemplos, "PASTA_EXEMPLOS", tmp_path / "ex")
    monkeypatch.setattr(exemplos, "PASTA_LOGS_EXEMPLOS", tmp_path / "logs")
    exemplos.main([])
    assert argumentos == [(("fake", "fake"), {"reasoning_effort": "medium"})]
    assert {p.name for p in (tmp_path / "ex").iterdir()} == {
        f"{r.nome}.md" for r in exemplos.ROTEIROS
    }
    logs = linhas(tmp_path / "logs" / "llm_calls.jsonl")
    assert {linha["conversa_id"] for linha in logs} == {
        f"exemplo-{r.nome}" for r in exemplos.ROTEIROS
    }
    stdout = capsys.readouterr().out
    assert "Total: " in stdout and f"[{len(exemplos.ROTEIROS)}/{len(exemplos.ROTEIROS)}]" in stdout


@pytest.mark.parametrize(("alvo", "erro"), [
    ("criar_cliente", LLMError("defina OPENAI_API_KEY no .env")),
    ("carregar_config", ValueError(
        "LLM_REASONING_EFFORT: valores válidos: none, low, medium, high",
    )),
])
def test_main_erro_inicializacao(alvo, erro, monkeypatch, tmp_path, capsys):
    def falhar(*args, **kwargs):
        raise erro

    monkeypatch.setattr(exemplos, "carregar_config", lambda: CFG)
    monkeypatch.setattr(exemplos, alvo, falhar)
    monkeypatch.setattr(exemplos, "PASTA_EXEMPLOS", tmp_path / "ex")
    with pytest.raises(SystemExit) as exc:
        exemplos.main([])
    assert exc.value.code == 1
    stderr = capsys.readouterr().err
    assert "Não consegui gerar os exemplos" in stderr and str(erro) in stderr
    assert "Traceback" not in stderr
    assert not (tmp_path / "ex").exists() or not list((tmp_path / "ex").iterdir())


def test_help():
    resultado = subprocess.run(
        [sys.executable, "-m", "evals.exemplos", "--help"], cwd=RAIZ,
        capture_output=True, text=True, encoding="utf-8",
    )
    assert resultado.returncode == 0
    assert "examples/" in resultado.stdout


def test_importacao_nao_carrega_sdk():
    subprocess.run([
        sys.executable, "-c", "import sys, evals.exemplos; assert not any(m in sys.modules "
        "for m in ('openai', 'anthropic', 'google.genai'))",
    ], cwd=RAIZ, check=True)
