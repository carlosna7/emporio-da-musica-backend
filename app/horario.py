from datetime import date, datetime, timedelta

DIAS_SEMANA = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
HORARIO = {0: (9, 18), 1: (9, 18), 2: (9, 18), 3: (9, 18), 4: (9, 18), 5: (9, 13)}
FERIADOS_FIXOS = {
    (1, 1): "Confraternização Universal",
    (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalho",
    (9, 7): "Independência do Brasil",
    (10, 11): "Criação do Estado de Mato Grosso do Sul",
    (10, 12): "Nossa Senhora Aparecida",
    (11, 2): "Finados",
    (11, 15): "Proclamação da República",
    (11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    (12, 25): "Natal",
}


def pascoa(ano: int) -> date:
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ajuste = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ajuste) // 451
    mes = (h + ajuste - 7 * m + 114) // 31
    dia = (h + ajuste - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def feriado(dia: date) -> str | None:
    return FERIADOS_FIXOS.get((dia.month, dia.day)) or (
        "Sexta-feira Santa" if dia == pascoa(dia.year) - timedelta(days=2) else None
    )


def situacao_loja(agora: datetime) -> str:
    hoje = agora.date()
    nome = feriado(hoje)
    horario = HORARIO.get(hoje.weekday()) if nome is None else None
    if horario and horario[0] <= agora.hour < horario[1]:
        return f"A loja está aberta agora, até as {horario[1]}h."
    motivo = f" (feriado: {nome})" if nome else ""
    if horario and agora.hour < horario[0]:
        quando, abre = "hoje", horario[0]
    else:
        for dias in range(1, 15):
            proximo = hoje + timedelta(days=dias)
            if proximo.weekday() in HORARIO and not feriado(proximo):
                abre = HORARIO[proximo.weekday()][0]
                quando = f"{DIAS_SEMANA[proximo.weekday()]} ({proximo:%d/%m})"
                if dias == 1:
                    quando = "amanhã, " + quando
                break
        else:
            raise ValueError("Nenhum dia aberto nos próximos 14 dias")
    return f"A loja está fechada agora{motivo}. A equipe volta {quando}, às {abre}h."
