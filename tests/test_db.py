import sqlite3

import pytest


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Violão Elétrico AÇO", "violao eletrico aco"),
        ("Barítono", "baritono"),
        ("Gibson Les Paul Standard '50s", "gibson les paul standard '50s"),
        ("", ""),
    ],
)
def test_normalizar(texto, esperado):
    from app.db import normalizar

    assert normalizar(texto) == esperado


def test_conectar_retorna_linhas_por_nome(conexao):
    assert conexao.row_factory is sqlite3.Row
    row = conexao.execute("SELECT name FROM categories WHERE category_id = 5").fetchone()
    assert row["name"] == "Violões"


def test_conexao_somente_leitura(conexao):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conexao.execute("DELETE FROM products")


def test_banco_inexistente_nao_e_criado(tmp_path):
    from app.db import conectar

    caminho = tmp_path / "nao_existe.db"
    with pytest.raises(FileNotFoundError, match="python -m app.ingest"):
        conectar(caminho)
    assert not caminho.exists()


def test_caminho_com_espaco_e_acento(tmp_path):
    from app.db import conectar
    from app.ingest import criar_banco

    caminho = tmp_path / "com espaço" / "emporio.db"
    criar_banco(destino=caminho)
    conexao = conectar(caminho)
    try:
        assert conexao.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 65
    finally:
        conexao.close()
