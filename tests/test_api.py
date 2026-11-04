import json

import pytest
from fastapi.testclient import TestClient

from app.api import criar_app, preparar_banco
from app.config import Config
from app.llm.providers.fake import FakeLLM, resposta_texto, resposta_tool

CFG = Config(provider="fake", model="fake")


def cliente(roteiro, banco, tmp_path, monkeypatch, token=""):
    monkeypatch.setenv("API_TOKEN", token)
    llm = FakeLLM(roteiro)
    app = criar_app(config=CFG, llm=llm, caminho_banco=banco, pasta_logs=tmp_path / "logs")
    return TestClient(app), llm


def test_health(banco, tmp_path, monkeypatch):
    api, _ = cliente([], banco, tmp_path, monkeypatch)
    resposta = api.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok", "modelo": "fake"}


def test_chat_usa_ferramenta_e_devolve_historico(banco, tmp_path, monkeypatch):
    roteiro = [resposta_tool("buscar_produtos", termo="violão"), resposta_texto("Temos sim!")]
    api, llm = cliente(roteiro, banco, tmp_path, monkeypatch)
    resposta = api.post("/chat", json={"mensagem": "Tem violão?", "conversa_id": "web-1"})
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["resposta"] == "Temos sim!"
    assert corpo["ferramentas"] == ["buscar_produtos"]
    assert corpo["status"] == "ok"
    assert corpo["conversa_id"] == "web-1"
    assert corpo["historico"] == [
        {"role": "user", "content": "Tem violão?"},
        {"role": "assistant", "content": "Temos sim!"},
    ]
    assert corpo["uso"]["input_tokens"] == 20
    assert len(llm.chamadas) == 2
    log = (tmp_path / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log[0])["conversa_id"] == "web-1"


def test_chat_envia_historico_ao_llm(banco, tmp_path, monkeypatch):
    api, llm = cliente([resposta_texto("Custa R$ 100.")], banco, tmp_path, monkeypatch)
    historico = [
        {"role": "user", "content": "Tem o Takamine?"},
        {"role": "assistant", "content": "Temos."},
    ]
    resposta = api.post("/chat", json={"mensagem": "Quanto custa?", "historico": historico})
    assert resposta.status_code == 200
    assert resposta.json()["conversa_id"].startswith("api-")
    enviadas = [(m.role, m.content) for m in llm.chamadas[0]["messages"]]
    assert enviadas == [
        ("user", "Tem o Takamine?"),
        ("assistant", "Temos."),
        ("user", "Quanto custa?"),
    ]


@pytest.mark.parametrize(
    "corpo",
    [
        {"mensagem": ""},
        {"mensagem": "oi", "historico": [{"role": "tool", "content": "x"}]},
        {"mensagem": "oi", "conversa_id": "../../etc"},
        {"mensagem": "oi", "historico": [{"role": "user", "content": "a"}] * 41},
    ],
)
def test_chat_rejeita_pedido_invalido(corpo, banco, tmp_path, monkeypatch):
    api, llm = cliente([], banco, tmp_path, monkeypatch)
    assert api.post("/chat", json=corpo).status_code == 422
    assert llm.chamadas == []


def test_chat_exige_token_quando_configurado(banco, tmp_path, monkeypatch):
    api, _ = cliente([resposta_texto("Oi!")], banco, tmp_path, monkeypatch, token="segredo")
    assert api.post("/chat", json={"mensagem": "oi"}).status_code == 401
    errado = {"Authorization": "Bearer outro"}
    assert api.post("/chat", json={"mensagem": "oi"}, headers=errado).status_code == 401
    certo = {"Authorization": "Bearer segredo"}
    assert api.post("/chat", json={"mensagem": "oi"}, headers=certo).status_code == 200


def test_preparar_banco_cria_copia_temporaria_quando_falta(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.PASTA_TEMPORARIA", tmp_path)
    caminho = preparar_banco(tmp_path / "nao-existe.db")
    assert caminho == tmp_path / "emporio.db"
    assert caminho.exists()


def test_preparar_banco_usa_o_existente(banco):
    assert preparar_banco(banco) == banco
