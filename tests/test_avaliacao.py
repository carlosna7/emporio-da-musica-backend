import json
from datetime import datetime

import pytest

from app.config import Config
from app.horario import HORARIO, feriado
from app.llm.base import Usage
from evals.avaliacao import (
    CATEGORIAS,
    Caso,
    Espera,
    ResultadoCaso,
    Turno,
    carregar_casos,
    montar_relatorio,
    nome_relatorio,
    normalizar_texto,
    resumir,
    verificar,
)

CFG = Config()
QUANDO = datetime(2026, 11, 3, 14, 30)


def escrever_casos(tmp_path, casos):
    caminho = tmp_path / "casos.json"
    caminho.write_text(json.dumps(casos), encoding="utf-8")
    return caminho


def caso_valido(**muda):
    base = {
        "id": "c1",
        "categoria": "produtos",
        "descricao": "d",
        "agora": "2026-11-03T10:00",
        "turnos": ["oi"],
        "espera": [{"tools": ["buscar_produtos"]}],
    }
    return {**base, **muda}


def test_casos_reais_cobrem_prd_e_horarios():
    casos = carregar_casos()
    por_id = {caso.id: caso for caso in casos}
    assert len(casos) == len(por_id) == 25
    assert {caso.categoria for caso in casos} == set(CATEGORIAS)
    assert sum(len(caso.turnos) > 1 for caso in casos) == 5
    assert sum(len(caso.turnos) for caso in casos) == 30
    dias = {caso.agora.weekday() for caso in casos}
    assert {5, 6} <= dias
    assert any(feriado(caso.agora.date()) for caso in casos)
    dias_uteis = [
        caso.agora for caso in casos
        if caso.agora.weekday() < 5 and not feriado(caso.agora.date())
    ]
    assert {
        HORARIO[agora.weekday()][0] <= agora.hour < HORARIO[agora.weekday()][1]
        for agora in dias_uteis
    } == {True, False}
    assert {
        "produtos-violoes-ate-1000",
        "politicas-endereco-contatos",
        "memoria-takamine-pix",
        "politicas-arrependimento-no-prazo",
        "politicas-arrependimento-fora-do-prazo",
        "escopo-acessorios-cordas",
        "escopo-futebol",
        "encaminhamento-atendente-insiste",
    } <= por_id.keys()
    assert "3321" in por_id["politicas-endereco-contatos"].espera[0].nao_contem
    for caso in casos:
        for espera in caso.espera:
            if espera and "encaminhar_atendente" in espera.tools:
                assert f"EM-{caso.agora:%Y%m%d}-" in espera.contem


def test_carregar_casos_converte_listas_em_tuplas(tmp_path):
    caminho = escrever_casos(tmp_path, [caso_valido()])
    [caso] = carregar_casos(caminho)
    assert caso.agora == datetime(2026, 11, 3, 10, 0)
    assert caso.turnos == ("oi",)
    assert caso.espera == (Espera(tools=("buscar_produtos",)),)

    caminho = escrever_casos(tmp_path, [caso_valido(
        turnos=["oi", "tchau"], espera=[None, {"contem_algum": [["a", "b"]]}],
    )])
    [caso] = carregar_casos(caminho)
    assert caso.espera == (None, Espera(contem_algum=(("a", "b"),)))


@pytest.mark.parametrize(("dados", "ident"), [
    ({}, "#0"),
    ([caso_valido(), caso_valido()], "c1"),
    ([caso_valido(id="C1")], "#1"),
    ([caso_valido(id="#1")], "#1"),
    ([{"categoria": "produtos"}], "#1"),
    ([caso_valido(categoria="vendas")], "c1"),
    ([caso_valido(descricao=" ")], "c1"),
    ([caso_valido(agora="2026-11-03")], "c1"),
    ([caso_valido(agora="2026-13-03T10:00")], "c1"),
    ([caso_valido(turnos=[])], "c1"),
    ([caso_valido(turnos=["  "])], "c1"),
    ([caso_valido(espera=[])], "c1"),
    ([caso_valido(espera=[None])], "c1"),
    ([caso_valido(espera=[{}])], "c1"),
    ([caso_valido(contém=[])], "c1"),
    ([caso_valido(espera=[{"contém": ["x"]}])], "c1"),
    ([caso_valido(espera=[{"tools": ["calcular_frete"]}])], "c1"),
    ([caso_valido(espera=[{
        "tools": ["buscar_produtos"], "tools_proibidas": ["buscar_produtos"],
    }])], "c1"),
    ([caso_valido(espera=[{"contem_algum": [[]]}])], "c1"),
    ([caso_valido(espera=[{"contem": [""]}])], "c1"),
])
def test_carregar_casos_rejeita_dados_invalidos(tmp_path, dados, ident):
    with pytest.raises(ValueError, match=rf"casos\.json, caso {ident}:"):
        carregar_casos(escrever_casos(tmp_path, dados))


@pytest.mark.parametrize(("entrada", "saida"), [
    ("R$ 2.089,05", "r$ 2089,05"),
    ("R$\u00a02.089,05", "r$ 2089,05"),
    ("1.234.567,89", "1234567,89"),
    ("Pré-Lançamento", "pre-lancamento"),
    ("18 %", "18%"),
    ("(67) 3341-4444", "(67) 3341-4444"),
    ("versão 2.1", "versao 2.1"),
    ("22.01.2026", "22.01.2026"),
    ("Às 9h\n\nAté   amanhã", "as 9h ate amanha"),
    ("EM-20261103-0001", "em-20261103-0001"),
])
def test_normalizar_texto(entrada, saida):
    assert normalizar_texto(entrada) == saida


@pytest.mark.parametrize("texto", ["No PIX: R$ 2.089,05.", "R$2089,05", "2089,05 no PIX"])
def test_verificar_aceita_formatos_de_preco_em_reais(texto):
    assert verificar(Espera(contem=("2.089,05",)), texto, [], "ok") == []


@pytest.mark.parametrize("texto", ["R$ 2.089,50", "2,089.05"])
def test_verificar_rejeita_outro_preco_ou_formato_americano(texto):
    assert verificar(Espera(contem=("2.089,05",)), texto, [], "ok") == ['falta: "2.089,05"']


def test_verificar_normaliza_acentos_dos_dois_lados():
    espera = Espera(contem=("pré-lançamento",))
    assert verificar(espera, "PRE-LANCAMENTO em breve", [], "ok") == []


def test_verificar_tools_exigidas_e_proibidas():
    exigida = Espera(tools=("buscar_produtos",))
    assert verificar(exigida, "", ["detalhes_produto", "buscar_produtos"], "ok") == []
    assert verificar(exigida, "", [], "ok") == ["tool não chamada: buscar_produtos"]
    proibida = Espera(tools_proibidas=("consultar_pedido",))
    assert verificar(proibida, "", ["consultar_pedido"], "ok") == [
        "tool proibida chamada: consultar_pedido",
    ]


def test_verificar_exige_uma_alternativa_de_cada_grupo():
    espera = Espera(contem_algum=(("7 dias", "sete dias"), ("passou",)))
    assert verificar(espera, "Já passou o prazo de sete dias.", [], "ok") == []
    assert verificar(espera, "O prazo é de 30 dias.", [], "ok") == [
        'nenhuma de: "7 dias" | "sete dias"', 'nenhuma de: "passou"',
    ]


def test_verificar_rejeita_texto_proibido():
    espera = Espera(nao_contem=("3321",))
    assert verificar(espera, "WhatsApp (67) 3321-4500", [], "ok") == ['não devia conter: "3321"']


def test_verificar_turno_sem_expectativa_ainda_exige_status_ok():
    assert verificar(None, "", [], "ok") == []
    assert verificar(None, "", [], "erro_llm") == ["status: erro_llm"]


def test_verificar_ordena_motivos_de_falha():
    espera = Espera(
        tools=("a",), tools_proibidas=("b",), contem=("x",),
        contem_algum=(("y",),), nao_contem=("z",),
    )
    assert verificar(espera, "z", ["b"], "limite_iteracoes") == [
        "status: limite_iteracoes",
        "tool não chamada: a",
        "tool proibida chamada: b",
        'falta: "x"',
        'nenhuma de: "y"',
        'não devia conter: "z"',
    ]


def caso(id, categoria="produtos", n_turnos=1):
    return Caso(id, categoria, "desc", QUANDO, ("msg",) * n_turnos, (Espera(),) * n_turnos)


def turno(falhas=(), custo=0.001, latencia=2.0, texto="ok"):
    return Turno(
        "msg", texto, ["buscar_produtos"], "ok", Usage(1000, 100, 500),
        custo, latencia, list(falhas),
    )


@pytest.fixture
def resultados():
    return [
        ResultadoCaso(caso("a"), [turno()]),
        ResultadoCaso(caso("b", n_turnos=2), [
            turno(latencia=1.0, custo=0.002),
            turno(falhas=['falta: "x"'], latencia=4.0, custo=0.002),
        ]),
        ResultadoCaso(caso("c", categoria="escopo"), [], erro="RuntimeError: boom"),
    ]


def test_resumir_conta_aprovacoes_tokens_custo_e_latencia(resultados):
    resumo = resumir(resultados)
    assert resumo.por_categoria == {"produtos": (1, 2), "escopo": (0, 1)}
    assert list(resumo.por_categoria) == ["produtos", "escopo"]
    assert (resumo.aprovados, resumo.total) == (1, 3)
    assert (resumo.multi_aprovados, resumo.multi_total) == (0, 1)
    assert resumo.turnos == 3
    assert (resumo.input_tokens, resumo.output_tokens, resumo.cached_tokens) == (3000, 300, 1500)
    assert resumo.custo_usd == pytest.approx(0.005)
    assert resumo.latencia_media_s == pytest.approx(7 / 3)
    assert resumo.latencia_max_s == 4.0
    assert [resultado.aprovado for resultado in resultados] == [True, False, False]
    assert not ResultadoCaso(caso("incompleto", n_turnos=2), [turno()]).aprovado


def test_resumir_custo_desconhecido_e_caso_sem_turnos(resultados):
    assert resumir([ResultadoCaso(caso("a"), [turno(custo=None)])]).custo_usd is None
    resumo = resumir([resultados[2]])
    assert resumo.turnos == 0
    assert resumo.custo_usd == 0.0
    assert resumo.latencia_media_s is resumo.latencia_max_s is None


def test_montar_relatorio_mostra_uso_casos_e_so_turnos_reprovados(resultados):
    texto = montar_relatorio(resultados, config=CFG, sem_memoria=False, quando=QUANDO)
    assert texto.startswith("# Avaliação do Emilio: 03/11/2026 14:30\n")
    assert texto.endswith("\n")
    for trecho in (
        "openai · gpt-6-luna · esforço medium · memória ligada",
        "5 chamadas ao LLM por turno · janela de 20 mensagens",
        "3 (1 com mais de um turno), 4 turnos",
        "| produtos | 1 | 2 |",
        "| escopo | 0 | 1 |",
        "| **Total** | **1** | **3** |",
        "Casos com mais de um turno: 0 de 1 aprovados.",
        "| Tokens de entrada | 3000 (1500 em cache) |",
        "| Custo estimado | US$ 0.005000 |",
        "| Latência média por turno | 2.3 s |",
        "| Latência máxima por turno | 4.0 s |",
        "| a | produtos | ok | buscar_produtos | 2.0 |",
        "| b | produtos | FALHOU | buscar_produtos / buscar_produtos | 1.0 / 4.0 |",
        "| c | escopo | ERRO | — | — |",
        "### b (produtos)",
        "- Turno 2: msg",
        '  - falta: "x"',
        "  - Ferramentas: buscar_produtos",
        "### c (escopo)",
        "- Erro: RuntimeError: boom",
    ):
        assert trecho in texto
    assert "### a (" not in texto
    assert "- Turno 1:" not in texto


def test_montar_relatorio_parcial_sem_memoria_e_sem_falhas():
    resultado = ResultadoCaso(caso("a"), [turno(custo=None)])
    texto = montar_relatorio([resultado], config=CFG, sem_memoria=True, quando=QUANDO, parcial=True)
    assert "memória desligada" in texto
    assert "· subconjunto (--casos)" in texto
    assert "## Falhas\n\nNenhuma falha.\n" in texto
    assert "| Custo estimado | n/d |" in texto


def test_montar_relatorio_sem_turnos_tem_latencias_indisponiveis(resultados):
    texto = montar_relatorio([resultados[2]], config=CFG, sem_memoria=False, quando=QUANDO)
    assert "| Latência média por turno | n/d |" in texto
    assert "| Latência máxima por turno | n/d |" in texto


@pytest.mark.parametrize(("resposta", "trecho"), [
    ("a" * 400, "a" * 300 + "…"),
    ("linha 1\n\nlinha 2", "linha 1 linha 2"),
])
def test_montar_relatorio_resume_resposta(resposta, trecho):
    resultado = ResultadoCaso(caso("a"), [turno(falhas=["falhou"], texto=resposta)])
    texto = montar_relatorio([resultado], config=CFG, sem_memoria=False, quando=QUANDO)
    assert f"  - Resposta: {trecho}\n" in texto
    assert "a" * 301 not in texto


def test_nome_relatorio_tem_configuracao_e_sufixos():
    assert nome_relatorio(CFG, False, QUANDO) == "20261103-1430-gpt-6-luna-medium.md"
    assert nome_relatorio(CFG, True, QUANDO) == "20261103-1430-gpt-6-luna-medium-sem-memoria.md"
    assert nome_relatorio(CFG, True, QUANDO, parcial=True).endswith("-sem-memoria-parcial.md")
    config = Config(model="models/gemini 3", reasoning_effort=None)
    assert nome_relatorio(config, False, QUANDO) == "20261103-1430-models-gemini-3-none.md"
