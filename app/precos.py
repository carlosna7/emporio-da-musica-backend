from decimal import ROUND_HALF_UP, Decimal

DESCONTO_PIX = 5


def calcular_precos(preco: float, descontos_ativos: list[int]) -> dict:
    desconto = max(descontos_ativos) if descontos_ativos else None
    pct = desconto if desconto is not None else DESCONTO_PIX
    valor = float(
        (Decimal(str(preco)) * (100 - pct) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    return {
        "preco_promocional": valor if desconto is not None else None,
        "desconto_percent": desconto,
        "preco_pix": valor if desconto is None else None,
    }
