import pytest

from app.precos import calcular_precos


def test_sem_promocao():
    assert calcular_precos(2199.0, []) == {
        "preco_promocional": None,
        "desconto_percent": None,
        "preco_pix": 2089.05,
    }


@pytest.mark.parametrize(
    "preco,descontos,esperado",
    [
        (359.0, [10], 323.1),
        (549.0, [20], 439.2),
        (2399.0, [18], 1967.18),
        (5999.0, [8], 5519.08),
        (1000.0, [10, 25, 15], 750.0),
    ],
)
def test_promocao(preco, descontos, esperado):
    r = calcular_precos(preco, descontos)
    assert r == {
        "preco_promocional": esperado,
        "desconto_percent": max(descontos),
        "preco_pix": None,
    }
    assert isinstance(r["preco_promocional"], float) and isinstance(r["desconto_percent"], int)


@pytest.mark.parametrize("preco,esperado", [(599.9, 569.91), (799.9, 759.91), (429.9, 408.41)])
def test_arredondamento(preco, esperado):
    r = calcular_precos(preco, [])
    assert r["preco_pix"] == esperado and isinstance(r["preco_pix"], float)
