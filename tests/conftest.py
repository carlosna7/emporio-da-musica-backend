import pytest


@pytest.fixture
def banco(tmp_path):
    from app.ingest import criar_banco

    caminho = tmp_path / "emporio.db"
    criar_banco(destino=caminho)
    return caminho


@pytest.fixture
def conexao(banco):
    from app.db import conectar

    conexao = conectar(banco)
    yield conexao
    conexao.close()
