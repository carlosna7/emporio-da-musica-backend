import csv
import json
import sqlite3
from datetime import date
from pathlib import Path

from app.db import CAMINHO_BANCO, normalizar

PASTA_CSV = Path(__file__).resolve().parents[1] / "data" / "raw"
TABELAS = ("categories", "customers", "products", "orders", "order_items", "promotions")

SCHEMA = """
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    nome_normalizado TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    description TEXT,
    price_brl REAL NOT NULL,
    stock_quantity INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'discontinued', 'coming_soon')),
    specs TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL,
    total_brl REAL NOT NULL,
    payment_method TEXT NOT NULL,
    tracking_code TEXT,
    estimated_delivery TEXT,
    notes TEXT
);
CREATE TABLE order_items (
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    PRIMARY KEY (order_id, product_id)
);
CREATE TABLE promotions (
    promotion_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    discount_percent INTEGER NOT NULL,
    description TEXT,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1))
);
"""


def converter_linha(tabela: str, linha: dict[str, str]) -> dict:
    valores = {}
    for coluna, original in linha.items():
        valor = original.strip()
        if not valor:
            valores[coluna] = None
        elif coluna.endswith("_id") or coluna in {
            "stock_quantity", "quantity", "discount_percent", "is_active"
        }:
            valores[coluna] = int(valor)
        elif coluna in {"price_brl", "total_brl"}:
            valores[coluna] = float(valor)
        elif coluna in {"created_at", "order_date", "estimated_delivery"}:
            date.fromisoformat(valor)
            valores[coluna] = valor
        elif tabela == "products" and coluna == "specs":
            try:
                if not isinstance(json.loads(valor), dict):
                    raise ValueError
            except ValueError as erro:
                produto = linha["product_id"].strip()
                raise ValueError(f"specs inválido no produto {produto}") from erro
            valores[coluna] = valor
        else:
            valores[coluna] = valor
    if tabela == "products":
        nome = valores["name"]
        valores["nome_normalizado"] = normalizar(nome) if nome is not None else None
    return valores


def criar_banco(destino: Path = CAMINHO_BANCO, origem: Path = PASTA_CSV) -> dict[str, int]:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.unlink(missing_ok=True)
    conexao = None
    try:
        conexao = sqlite3.connect(destino)
        conexao.execute("PRAGMA foreign_keys = ON")
        conexao.executescript(SCHEMA)
        contagens = {}
        for tabela in TABELAS:
            contagem = 0
            with (origem / f"{tabela}.csv").open(encoding="utf-8", newline="") as arquivo:
                for linha in csv.DictReader(arquivo):
                    valores = converter_linha(tabela, linha)
                    colunas = ", ".join(valores)
                    marcadores = ", ".join("?" for _ in valores)
                    conexao.execute(
                        f"INSERT INTO {tabela} ({colunas}) VALUES ({marcadores})",
                        tuple(valores.values()),
                    )
                    contagem += 1
            contagens[tabela] = contagem
        conexao.commit()
    except Exception:
        if conexao is not None:
            conexao.close()
        destino.unlink(missing_ok=True)
        raise
    conexao.close()
    return contagens


def main() -> None:
    contagens = criar_banco()
    print(CAMINHO_BANCO)
    for tabela, contagem in contagens.items():
        print(f"{tabela}: {contagem}")


if __name__ == "__main__":
    main()
