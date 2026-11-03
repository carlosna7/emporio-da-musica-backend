from datetime import date, datetime

import pytest

from app.horario import feriado, pascoa, situacao_loja


def test_feriados():
    assert pascoa(2026) == date(2026, 4, 5)
    assert pascoa(2027) == date(2027, 3, 28)
    assert feriado(date(2026, 4, 3)) == "Sexta-feira Santa"
    assert feriado(date(2026, 11, 2)) == "Finados"
    assert feriado(date(2026, 11, 3)) is None


@pytest.mark.parametrize(
    "data,esperado",
    [
        ("2026-11-03T10:00", "A loja está aberta agora, até as 18h."),
        ("2026-11-03T07:30", "A loja está fechada agora. A equipe volta hoje, às 9h."),
        (
            "2026-11-03T18:00",
            "A loja está fechada agora. A equipe volta amanhã, quarta-feira (04/11), às 9h.",
        ),
        (
            "2026-11-07T14:00",
            "A loja está fechada agora. A equipe volta segunda-feira (09/11), às 9h.",
        ),
        (
            "2026-11-02T10:00",
            "A loja está fechada agora (feriado: Finados). A equipe volta "
            "amanhã, terça-feira (03/11), às 9h.",
        ),
    ],
)
def test_situacao(data, esperado):
    assert situacao_loja(datetime.fromisoformat(data)) == esperado


def test_expedientes_adicionais():
    casos = [
        (
            "2026-11-06T19:30",
            "A loja está fechada agora. A equipe volta amanhã, sábado (07/11), às 9h.",
        ),
        ("2026-11-07T12:00", "A loja está aberta agora, até as 13h."),
        (
            "2026-11-08T15:00",
            "A loja está fechada agora. A equipe volta amanhã, segunda-feira (09/11), às 9h.",
        ),
        (
            "2026-11-20T10:00",
            "A loja está fechada agora (feriado: Dia Nacional de Zumbi e da Consciência Negra). "
            "A equipe volta amanhã, sábado (21/11), às 9h.",
        ),
        (
            "2026-11-14T14:00",
            "A loja está fechada agora. A equipe volta segunda-feira (16/11), às 9h.",
        ),
        (
            "2026-04-03T11:00",
            "A loja está fechada agora (feriado: Sexta-feira Santa). "
            "A equipe volta amanhã, sábado (04/04), às 9h.",
        ),
    ]
    for data, esperado in casos:
        assert situacao_loja(datetime.fromisoformat(data)) == esperado
    assert feriado(date(2026, 10, 11)) == "Criação do Estado de Mato Grosso do Sul"
