from datetime import datetime

import pytest

from app.politicas import texto_da_secao
from app.prompts import montar_system_prompt


def test_prompt():
    p = montar_system_prompt(datetime(2026, 11, 2, 10), texto_da_secao(7), texto_da_secao(10))
    for trecho in (
        "Emilio",
        "Rua 14 de Maio, 3200",
        "(67) 3341-4444",
        "contato@emporiodamusica.com.br",
        "segunda-feira, 02/11/2026 (2026-11-02), 10:00",
        "feriado: Finados",
    ):
        assert trecho in p
    assert "3321-4500" not in p
    assert p.index("## Agora") > p.index("## Manual da loja")


def test_manual_e_pureza():
    agora = datetime(2026, 11, 2, 10)
    p = montar_system_prompt(agora, texto_da_secao(7), texto_da_secao(10))
    for trecho in (
        "Tom de voz",
        "### 7.3 Situações Especiais",
        "consultar a gerência",
        "consultar_politica",
        "consultar_pedido",
        "encaminhar_atendente",
        "não temos no momento",
        "calculado no fechamento do pedido, pelo CEP",
    ):
        assert trecho in p
    for trecho in ("3321", "Última atualização", "\n---", "\n\n\n"):
        assert trecho not in p
    outro = montar_system_prompt(datetime(2026, 11, 3, 10), texto_da_secao(7), texto_da_secao(10))
    assert p.split("## Agora")[0] == outro.split("## Agora")[0]
    assert "A loja está aberta agora, até as 18h." in outro
    simples = montar_system_prompt(agora, "A\nWhatsApp (67) 3321-4500\nB", "C\n---\nrodapé")
    assert "A\nB" in simples and "rodapé" not in simples
    assert simples == montar_system_prompt(agora, "A\nWhatsApp (67) 3321-4500\nB", "C\n---\nrodapé")


@pytest.mark.parametrize(
    ("dia", "nome"),
    [("2026-01-22", "quinta-feira"), ("2026-11-07", "sábado"), ("2026-11-08", "domingo")],
)
def test_dia_semana(dia, nome):
    agora = datetime.fromisoformat(dia + "T15:30")
    p = montar_system_prompt(agora, "", "")
    assert nome in p and "15:30" in p
