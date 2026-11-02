import sys
from pathlib import Path

DATA_RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def test_python_312_ou_superior():
    assert sys.version_info >= (3, 12)


def test_pacote_app_importavel():
    import app  # noqa: F401


def test_dependencias_instaladas():
    import dotenv  # noqa: F401
    import openai  # noqa: F401


def test_dados_brutos_presentes():
    esperados = {
        "categories.csv",
        "customers.csv",
        "orders.csv",
        "order_items.csv",
        "products.csv",
        "promotions.csv",
        "politicas_da_loja.pdf",
    }
    assert esperados <= {p.name for p in DATA_RAW.iterdir()}
