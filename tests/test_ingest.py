import csv
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

PASTA_CSV = Path(__file__).resolve().parents[1] / "data" / "raw"
TABELAS = ("categories", "customers", "products", "orders", "order_items", "promotions")


def copiar_csvs(tmp_path):
    pasta = tmp_path / "raw"
    pasta.mkdir()
    for tabela in TABELAS:
        shutil.copy(PASTA_CSV / f"{tabela}.csv", pasta)
    return pasta


def alterar_csv(caminho, campo_busca, valor_busca, campo, valor):
    with caminho.open(encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        colunas = leitor.fieldnames
        linhas = list(leitor)
    linha = next(linha for linha in linhas if linha[campo_busca] == valor_busca)
    linha[campo] = valor
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas)
        escritor.writeheader()
        escritor.writerows(linhas)


def test_contagens(tmp_path):
    from app.ingest import criar_banco

    caminho = tmp_path / "emporio.db"
    contagens = criar_banco(destino=caminho)
    assert contagens == {
        "categories": 9,
        "customers": 50,
        "products": 65,
        "orders": 20,
        "order_items": 22,
        "promotions": 25,
    }
    with closing(sqlite3.connect(caminho)) as conexao:
        for tabela, quantidade in contagens.items():
            assert conexao.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0] == quantidade


def test_produto_95_completo(conexao):
    produto = conexao.execute("SELECT * FROM products WHERE product_id = 95").fetchone()
    assert produto["name"] == "Takamine GD20 Dreadnought Natural"
    assert produto["nome_normalizado"] == "takamine gd20 dreadnought natural"
    assert produto["category_id"] == 5
    assert produto["price_brl"] == 2199.0
    assert isinstance(produto["price_brl"], float)
    assert produto["stock_quantity"] == 5
    assert isinstance(produto["stock_quantity"], int)
    assert produto["status"] == "active"
    assert produto["created_at"] == "2021-11-03"
    assert json.loads(produto["specs"]) == {
        "top": "Cedro Sólido",
        "back_sides": "Sapele",
        "neck": "Mogno",
        "strings": "steel",
        "scale": "650mm",
        "electronics": "no",
        "color": "Natural",
    }


def test_precos_decimais(conexao):
    assert (
        conexao.execute("SELECT price_brl FROM products WHERE product_id = 81").fetchone()[0]
        == 599.9
    )
    assert conexao.execute("SELECT total_brl FROM orders WHERE order_id = 4").fetchone()[0] == 799.9
    assert (
        conexao.execute("SELECT total_brl FROM orders WHERE order_id = 1").fetchone()[0] == 11499.0
    )


@pytest.mark.parametrize(
    "consulta",
    [
        "SELECT COUNT(*) FROM products WHERE typeof(price_brl) <> 'real' "
        "OR typeof(stock_quantity) <> 'integer'",
        "SELECT COUNT(*) FROM orders WHERE typeof(total_brl) <> 'real'",
        "SELECT COUNT(*) FROM promotions WHERE typeof(is_active) <> 'integer' "
        "OR typeof(discount_percent) <> 'integer'",
    ],
)
def test_tipos_sqlite(conexao, consulta):
    assert conexao.execute(consulta).fetchone()[0] == 0


def test_nomes_normalizados(conexao):
    from app.db import normalizar

    produtos = conexao.execute("SELECT product_id, name, nome_normalizado FROM products").fetchall()
    nomes = {produto["product_id"]: produto["nome_normalizado"] for produto in produtos}
    assert nomes[139] == "bateria acustica yamaha kit 1 studio"
    assert nomes[98] == "yamaha ntx1 eletrico nylon natural"
    assert nomes[128] == "kala ka-b baritono mogno"
    assert len(produtos) == 65
    assert all(p["nome_normalizado"] == normalizar(p["name"]) for p in produtos)


def test_vazio_vira_null(conexao):
    def pedido(numero):
        return conexao.execute(
            "SELECT tracking_code, estimated_delivery, notes FROM orders WHERE order_id = ?",
            (numero,),
        ).fetchone()

    assert tuple(pedido(9)) == (None, None, None)
    assert tuple(pedido(1)) == ("BRAB1234567BR", "2025-10-25", None)
    assert pedido(17)["notes"] == "Pedido cancelado pelo cliente antes do processamento"
    assert (
        conexao.execute("SELECT COUNT(*) FROM orders WHERE tracking_code IS NULL").fetchone()[0]
        == 12
    )
    assert conexao.execute("SELECT COUNT(*) FROM orders WHERE notes IS NOT NULL").fetchone()[0] == 4
    assert (
        conexao.execute(
            "SELECT COUNT(*) FROM orders WHERE tracking_code = '' OR notes = ''"
        ).fetchone()[0]
        == 0
    )


def test_promocoes_ativas(conexao):
    linhas = conexao.execute(
        "SELECT promotion_id, product_id, discount_percent FROM promotions "
        "WHERE is_active = 1 ORDER BY promotion_id"
    ).fetchall()
    assert [tuple(linha) for linha in linhas] == [
        (12, 127, 10),
        (14, 121, 20),
        (19, 90, 18),
        (24, 94, 8),
    ]
    assert {linha[0] for linha in conexao.execute("SELECT DISTINCT is_active FROM promotions")} == {
        0,
        1,
    }


def test_status_produtos(conexao):
    linhas = conexao.execute("SELECT status, COUNT(*) FROM products GROUP BY status")
    assert dict(linhas) == {"active": 62, "discontinued": 2, "coming_soon": 1}
    assert (
        conexao.execute("SELECT status FROM products WHERE product_id = 130").fetchone()[0]
        == "coming_soon"
    )


def test_specs_produtos(conexao):
    produtos = conexao.execute("SELECT product_id, specs FROM products").fetchall()
    assert len(produtos) == 65
    assert all(isinstance(json.loads(produto["specs"]), dict) for produto in produtos)
    specs = next(p["specs"] for p in produtos if p["product_id"] == 131)
    assert json.loads(specs) == {
        "body": "Mahogany",
        "neck": "Mahogany",
        "strings": "6",
        "color": "Heritage Cherry Sunburst",
    }


def test_recria_banco_do_zero(tmp_path):
    from app.ingest import criar_banco

    caminho = tmp_path / "emporio.db"
    with closing(sqlite3.connect(caminho)) as conexao:
        conexao.execute("CREATE TABLE lixo (x)")
    criar_banco(destino=caminho)
    criar_banco(destino=caminho)
    with closing(sqlite3.connect(caminho)) as conexao:
        assert conexao.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 65
        assert (
            conexao.execute("SELECT name FROM sqlite_master WHERE name = 'lixo'").fetchone() is None
        )


@pytest.mark.parametrize("specs", ["{nao é json", "[1, 2]"])
def test_specs_invalidos_removem_banco(tmp_path, specs):
    from app.ingest import criar_banco

    origem = copiar_csvs(tmp_path)
    alterar_csv(origem / "products.csv", "product_id", "95", "specs", specs)
    destino = tmp_path / "emporio.db"
    with pytest.raises(ValueError, match="95"):
        criar_banco(destino=destino, origem=origem)
    assert not destino.exists()


def test_fk_invalida_remove_banco(tmp_path):
    from app.ingest import criar_banco

    origem = copiar_csvs(tmp_path)
    alterar_csv(origem / "order_items.csv", "order_id", "1", "product_id", "999")
    destino = tmp_path / "emporio.db"
    with pytest.raises(sqlite3.IntegrityError):
        criar_banco(destino=destino, origem=origem)
    assert not destino.exists()

