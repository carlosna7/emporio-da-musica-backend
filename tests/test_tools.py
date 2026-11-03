from datetime import date

import pytest

from app.tools import Contexto, buscar_produtos, detalhes_produto


@pytest.fixture
def ctx(conexao, tmp_path):
    return Contexto(conexao, date(2026, 11, 2), "teste", tmp_path / "logs")


def ids(resultado):
    return [produto["id"] for produto in resultado["produtos"]]


def test_busca_produtos(ctx):
    r = buscar_produtos(termo="takamine gd20", ctx=ctx)
    assert r == {
        "total": 1,
        "produtos": [
            {
                "id": 95,
                "nome": "Takamine GD20 Dreadnought Natural",
                "categoria": "Violões",
                "preco": 2199.0,
                "preco_promocional": None,
                "desconto_percent": None,
                "preco_pix": 2089.05,
                "estoque": 5,
                "status": "active",
                "disponivel": True,
            }
        ],
    }
    assert ids(buscar_produtos(termo="ACÚSTICA yamaha", ctx=ctx)) == [139, 141]
    assert buscar_produtos(termo="violão", ctx=ctx)["total"] == 0
    r = buscar_produtos(categoria="violoes", preco_max=1000, ctx=ctx)
    assert r["total"] == 12 and ids(r) == [83, 85, 89, 88, 81, 84, 87, 86, 107, 82]
    assert "12" in r["aviso"]
    assert ids(buscar_produtos(em_promocao=True, ctx=ctx)) == [127, 121, 90, 94]
    assert ids(buscar_produtos(categoria="Ukuleles", preco_max=440, ctx=ctx)) == [
        119,
        118,
        116,
        117,
        127,
        120,
        121,
    ]
    assert 121 not in ids(buscar_produtos(categoria="Ukuleles", preco_min=440, ctx=ctx))
    assert buscar_produtos(termo="gf-3d", ctx=ctx)["total"] == 0
    p = buscar_produtos(termo="gf-3d", apenas_disponiveis=False, ctx=ctx)["produtos"][0]
    assert p["preco_pix"] == 759.91 and p["disponivel"] is False
    assert ids(buscar_produtos(termo="7 cordas", ctx=ctx)) == [112, 110, 109, 111]
    assert ids(buscar_produtos(termo="7 cordas", apenas_disponiveis=False, ctx=ctx)) == [
        113,
        112,
        110,
        109,
        111,
    ]
    r = buscar_produtos(ctx=ctx)
    assert r["total"] == 61 and len(r["produtos"]) == 10 and ids(r)[0] == 119


@pytest.mark.parametrize(
    "categoria",
    ["Instrumentos de Sopro (Madeiras)", "Instrumentos de Sopro (Metais)", "Cordas Orquestrais"],
)
def test_categoria_vazia(ctx, categoria):
    assert buscar_produtos(categoria=categoria, ctx=ctx) == {
        "total": 0,
        "produtos": [],
        "aviso": "Nenhum produto encontrado com esses filtros.",
    }


@pytest.mark.parametrize(
    "argumentos",
    [
        {"categoria": "Acessórios"},
        {"preco_max": -1},
        {"preco_max": "mil"},
        {"preco_max": True},
        {"preco_min": 500, "preco_max": 100},
        {"apenas_disponiveis": "sim"},
        {"termo": 123},
    ],
)
def test_busca_invalida(ctx, argumentos):
    assert "erro" in buscar_produtos(**argumentos, ctx=ctx)


def test_detalhes(ctx):
    p = detalhes_produto(95, ctx=ctx)
    assert p["id"] == 95 and p["descricao"].startswith("Violão dreadnought Takamine")
    assert p["specs"] == {
        "top": "Cedro Sólido",
        "back_sides": "Sapele",
        "neck": "Mogno",
        "strings": "steel",
        "scale": "650mm",
        "electronics": "no",
        "color": "Natural",
    }
    assert detalhes_produto(95.0, ctx=ctx)["id"] == 95
    p = detalhes_produto(130, ctx=ctx)
    assert p["status"] == "coming_soon" and p["estoque"] == 2 and p["disponivel"] is False
    assert detalhes_produto(999, ctx=ctx) == {"erro": "Produto 999 não encontrado."}
    for invalido in ["95", True, 95.5]:
        assert "erro" in detalhes_produto(invalido, ctx=ctx)


def test_pedido(ctx):
    from dataclasses import replace

    from app.tools import ERRO_PEDIDO, consultar_pedido

    esperado = {
        "pedido": 1,
        "status": "delivered",
        "data_pedido": "2025-10-15",
        "total": 11499.0,
        "pagamento": "pix",
        "codigo_rastreio": "BRAB1234567BR",
        "previsao_entrega": "2025-10-25",
        "itens": [{"nome": "Martin D-28 Dreadnought Natural", "quantidade": 1}],
        "observacao": None,
        "dias_desde_compra": 383,
        "dias_desde_entrega": 373,
    }
    for contato in [
        "pedro.oliveira@jmail.com",
        " Pedro.Oliveira@JMAIL.COM ",
        "67984321098",
        "67 98432-1098",
        "+55 (67) 98432-1098",
    ]:
        assert consultar_pedido(1, contato, ctx=ctx) == esperado
    for numero, contato in [
        (1, "rafael.pereira@jmail.com"),
        (1, "98432-1098"),
        (999, "pedro.oliveira@jmail.com"),
        (10, "(67) 99456-3456"),
    ]:
        assert consultar_pedido(numero, contato, ctx=ctx) == {"erro": ERRO_PEDIDO}
    r = consultar_pedido(15, "aline.monteiro@jmail.com", ctx=ctx)
    assert r["status"] == "pending" and r["total"] == 8348.0 and r["pagamento"] == "credit_12x"
    assert (
        r["codigo_rastreio"] is None
        and r["previsao_entrega"] is None
        and r["dias_desde_entrega"] is None
    )
    assert r["itens"] == [
        {"nome": "Yamaha C70 Nylon Natural", "quantidade": 1},
        {"nome": "Taylor 214ce Elétrico Aço Natural", "quantidade": 1},
    ]
    assert not {"email", "telefone", "phone", "nome_cliente"} & r.keys()
    assert (
        consultar_pedido(17, "matheus.correia@hayoo.com.br", ctx=ctx)["observacao"]
        == "Pedido cancelado pelo cliente antes do processamento"
    )
    r = consultar_pedido(5, "rafael.pereira@jmail.com", ctx=replace(ctx, hoje=date(2026, 1, 22)))
    assert (r["dias_desde_compra"], r["dias_desde_entrega"]) == (17, 4)
    assert (
        consultar_pedido(8, "anacarol.ferreira@coldmail.com", ctx=ctx)["dias_desde_entrega"] is None
    )
    for contato in ["bruno.martins@jmail.com", "(67) 98543-2109"]:
        assert consultar_pedido(10, contato, ctx=ctx)["itens"] == [
            {"nome": "Music Man Bass 1X Electric Bass", "quantidade": 1}
        ]
    for numero, contato in [("1", "x"), (True, "x"), (1, "   ")]:
        assert consultar_pedido(numero, contato, ctx=ctx)["erro"] != ERRO_PEDIDO


def test_politica_e_encaminhamento(ctx):
    import json
    from dataclasses import replace
    from datetime import datetime

    from app.tools import consultar_politica, encaminhar_atendente

    p = consultar_politica("trocas_devolucoes", ctx=ctx)
    assert p["topico"] == "trocas_devolucoes" and p["texto"].startswith(
        "## 4. Política de Trocas e Devoluções"
    )
    assert "7 (sete) dias corridos" in p["texto"]
    assert (
        "Frete grátis para pedidos acima de R$ 500,00"
        in consultar_politica("frete_entregas", ctx=ctx)["texto"]
    )
    assert "frete_entregas" in consultar_politica("cordas", ctx=ctx)["erro"]
    r = encaminhar_atendente("reclamacao", "Pedido 5 chegou com o tampo trincado.", ctx=ctx)
    assert r == {
        "protocolo": "EM-20261102-0001",
        "prazo_retorno": "24 horas úteis",
        "canal_whatsapp": "(67) 3341-4444",
    }
    arquivo = ctx.pasta_logs / "handoffs.jsonl"
    linha = json.loads(arquivo.read_text(encoding="utf-8").splitlines()[0])
    assert list(linha) == ["protocolo", "ts", "conversa_id", "motivo", "resumo", "contato"]
    assert (
        linha["conversa_id"] == "teste"
        and linha["motivo"] == "reclamacao"
        and linha["contato"] is None
    )
    datetime.fromisoformat(linha["ts"])
    assert (
        encaminhar_atendente("reclamacao", "a", "(67) 99999-0000", ctx=ctx)["protocolo"]
        == "EM-20261102-0002"
    )
    assert (
        json.loads(arquivo.read_text(encoding="utf-8").splitlines()[1])["contato"]
        == "(67) 99999-0000"
    )
    assert (
        encaminhar_atendente("reclamacao", "a", "   ", ctx=replace(ctx, hoje=date(2026, 11, 3)))[
            "protocolo"
        ]
        == "EM-20261103-0001"
    )
    assert json.loads(arquivo.read_text(encoding="utf-8").splitlines()[2])["contato"] is None


@pytest.mark.parametrize(
    "args",
    [
        ("raiva", "a", None),
        ("reclamacao", "", None),
        ("reclamacao", None, None),
        ("reclamacao", "a", 5),
    ],
)
def test_encaminhamento_invalido(ctx, args):
    from app.tools import encaminhar_atendente

    assert "erro" in encaminhar_atendente(*args, ctx=ctx)
    assert not (ctx.pasta_logs / "handoffs.jsonl").exists()


def test_registro(ctx):
    import inspect
    import json
    from pathlib import Path

    from app.politicas import TOPICOS
    from app.tools import CATEGORIAS, MOTIVOS, TOOLS

    assert list(TOOLS) == [
        "buscar_produtos",
        "detalhes_produto",
        "consultar_pedido",
        "consultar_politica",
        "encaminhar_atendente",
    ]
    for ferramenta in TOOLS.values():
        assinatura = inspect.signature(ferramenta.funcao)
        parametros = {k: v for k, v in assinatura.parameters.items() if k != "ctx"}
        assert assinatura.parameters["ctx"].kind == inspect.Parameter.KEYWORD_ONLY
        assert ferramenta.descricao and ferramenta.parametros["type"] == "object"
        assert set(ferramenta.parametros["properties"]) == set(parametros)
        assert set(ferramenta.parametros["required"]) == {
            k for k, v in parametros.items() if v.default is inspect.Parameter.empty
        }
        assert all(
            "type" in p and "description" in p for p in ferramenta.parametros["properties"].values()
        )
    assert TOOLS["buscar_produtos"].parametros["properties"]["categoria"]["enum"] == list(
        CATEGORIAS
    )
    assert TOOLS["consultar_politica"].parametros["properties"]["topico"]["enum"] == list(TOPICOS)
    assert TOOLS["encaminhar_atendente"].parametros["properties"]["motivo"]["enum"] == list(MOTIVOS)
    assert CATEGORIAS == tuple(
        r["name"] for r in ctx.conexao.execute("SELECT name FROM categories ORDER BY category_id")
    )
    texto = Path("app/tools.py").read_text(encoding="utf-8")
    assert "app.llm" not in texto and "3321-4500" not in texto
    for nome, args in [
        ("buscar_produtos", {}),
        ("detalhes_produto", {"product_id": 95}),
        ("consultar_pedido", {"order_id": 1, "email_ou_telefone": "pedro.oliveira@jmail.com"}),
        ("consultar_politica", {"topico": "horarios"}),
        ("encaminhar_atendente", {"motivo": "reclamacao", "resumo": "teste"}),
    ]:
        json.dumps(TOOLS[nome].funcao(**args, ctx=ctx))


def test_outros_casos_de_produtos(ctx):
    p = buscar_produtos(termo="kal-700t", ctx=ctx)["produtos"][0]
    assert (p["preco"], p["preco_promocional"], p["desconto_percent"], p["preco_pix"]) == (
        359.0,
        323.1,
        10,
        None,
    )
    p = buscar_produtos(termo="sn-7c", apenas_disponiveis=False, ctx=ctx)["produtos"][0]
    assert p["status"] == "discontinued" and p["disponivel"] is False
    assert "Violões" in buscar_produtos(categoria="Acessórios", ctx=ctx)["erro"]
    p = detalhes_produto(95, ctx=ctx)
    assert {
        k: p[k] for k in buscar_produtos(termo="takamine gd20", ctx=ctx)["produtos"][0]
    } == buscar_produtos(termo="takamine gd20", ctx=ctx)["produtos"][0]


def test_entradas_invalidas_adicionais(ctx):
    from app.tools import consultar_pedido, consultar_politica, encaminhar_atendente

    assert "erro" in buscar_produtos(em_promocao="sim", ctx=ctx)
    assert "erro" in consultar_politica([], ctx=ctx)
    assert "reclamacao" in encaminhar_atendente("raiva", "x", ctx=ctx)["erro"]
    assert "erro" in consultar_pedido(1, None, ctx=ctx)


def test_verificacoes_explicitas_de_busca(ctx):
    vazio = buscar_produtos(termo="violão", ctx=ctx)
    assert vazio["total"] == 0 and "aviso" in vazio
    acentuada = buscar_produtos(categoria="Violões", preco_max=1000, ctx=ctx)
    sem_acento = buscar_produtos(categoria="violoes", preco_max=1000, ctx=ctx)
    assert acentuada == sem_acento
    assert acentuada["total"] == 12
    assert ids(acentuada) == [83, 85, 89, 88, 81, 84, 87, 86, 107, 82]
    assert 96 not in ids(acentuada) and 113 not in ids(acentuada)
    p = buscar_produtos(termo="gf-3d", apenas_disponiveis=False, ctx=ctx)["produtos"][0]
    assert p["estoque"] == 0 and p["status"] == "active"
    assert p["disponivel"] is False and p["preco_pix"] == 759.91


def test_verificacoes_explicitas_de_pedidos(ctx):
    from dataclasses import replace

    from app.tools import consultar_pedido

    cancelado = consultar_pedido(17, "matheus.correia@hayoo.com.br", ctx=ctx)
    assert cancelado["status"] == "cancelled"
    for contato in ["bruno.martins@jmail.com", "(67) 98543-2109"]:
        assert consultar_pedido(10, contato, ctx=ctx)["pedido"] == 10
    casos = [
        (1, "pedro.oliveira@jmail.com", ctx),
        (15, "aline.monteiro@jmail.com", ctx),
        (17, "matheus.correia@hayoo.com.br", ctx),
        (5, "rafael.pereira@jmail.com", replace(ctx, hoje=date(2026, 1, 22))),
        (8, "anacarol.ferreira@coldmail.com", ctx),
        (10, "bruno.martins@jmail.com", ctx),
    ]
    for numero, contato, contexto in casos:
        resultado = consultar_pedido(numero, contato, ctx=contexto)
        assert "erro" not in resultado
        assert not {"email", "telefone", "phone", "nome_cliente"} & resultado.keys()


def test_verificacoes_explicitas_de_politica_e_registro(ctx):
    import json
    from dataclasses import replace

    from app.tools import TOOLS, consultar_politica, encaminhar_atendente

    erro = consultar_politica("cordas", ctx=ctx)
    assert list(erro) == ["erro"] and "cordas" in erro["erro"] and "frete_entregas" in erro["erro"]
    arquivo = ctx.pasta_logs / "handoffs.jsonl"
    encaminhar_atendente("reclamacao", "Pedido 5 chegou com o tampo trincado.", ctx=ctx)
    assert arquivo.exists()
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1
    assert json.loads(linhas[0])["resumo"] == "Pedido 5 chegou com o tampo trincado."
    encaminhar_atendente("reclamacao", "a", "(67) 99999-0000", ctx=ctx)
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2 and json.loads(linhas[1])["contato"] == "(67) 99999-0000"
    encaminhar_atendente("reclamacao", "a", "   ", ctx=replace(ctx, hoje=date(2026, 11, 3)))
    for ferramenta in TOOLS.values():
        assert (
            not {"ctx", "conexao", "hoje", "conversa_id", "pasta_logs"}
            & ferramenta.parametros["properties"].keys()
        )
