import json
import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.db import normalizar
from app.politicas import TOPICOS
from app.precos import calcular_precos

PASTA_LOGS = Path(__file__).resolve().parents[1] / "logs"
CATEGORIAS = (
    "Guitarras",
    "Baixos",
    "Baterias e Percussão",
    "Teclados e Pianos",
    "Violões",
    "Instrumentos de Sopro (Madeiras)",
    "Instrumentos de Sopro (Metais)",
    "Cordas Orquestrais",
    "Ukuleles",
)
AVISO_INDISPONIVEIS = (
    "Nenhum produto à venda com esses filtros. Os itens de 'indisponiveis' existem no "
    "catálogo, mas não podem ser comprados agora: diga o motivo de cada um (estoque 0 = "
    "esgotado; discontinued = descontinuado, saiu de linha; coming_soon = pré-lançamento, "
    "ainda não está à venda)."
)


@dataclass
class Contexto:
    conexao: sqlite3.Connection
    hoje: date
    conversa_id: str = ""
    pasta_logs: Path = PASTA_LOGS


def _inteiro(valor):
    return (isinstance(valor, int) and not isinstance(valor, bool)) or (
        isinstance(valor, float) and valor.is_integer()
    )


def _produto(linha, ctx):
    descontos = [
        r[0]
        for r in ctx.conexao.execute(
            "SELECT discount_percent FROM promotions WHERE product_id = ? AND is_active = 1",
            (linha["product_id"],),
        )
    ]
    return {
        "id": linha["product_id"],
        "nome": linha["name"],
        "categoria": linha["categoria"],
        "preco": linha["price_brl"],
        **calcular_precos(linha["price_brl"], descontos),
        "estoque": linha["stock_quantity"],
        "status": linha["status"],
        "disponivel": linha["status"] == "active" and linha["stock_quantity"] > 0,
    }


def _linhas(ctx):
    return ctx.conexao.execute(
        "SELECT p.*, c.name AS categoria FROM products p JOIN categories c USING (category_id)"
    ).fetchall()


def buscar_produtos(
    termo=None,
    categoria=None,
    preco_min=None,
    preco_max=None,
    apenas_disponiveis=True,
    em_promocao=False,
    *,
    ctx: Contexto,
) -> dict:
    if termo is not None and not isinstance(termo, str):
        return {"erro": "Termo deve ser texto."}
    if categoria is not None:
        if not isinstance(categoria, str):
            return {"erro": "Categoria deve ser texto."}
        categoria_original = categoria
        categoria = next(
            (c for c in CATEGORIAS if normalizar(c) == normalizar(categoria.strip())), None
        )
        if categoria is None:
            return {
                "erro": (
                    f"Categoria inválida: {categoria_original}. Válidas: {', '.join(CATEGORIAS)}"
                )
            }
    for valor in (preco_min, preco_max):
        if valor is not None and (
            isinstance(valor, bool)
            or not isinstance(valor, (int, float))
            or not math.isfinite(valor)
            or valor < 0
        ):
            return {"erro": "Preço deve ser um número não negativo."}
    if preco_min is not None and preco_max is not None and preco_min > preco_max:
        return {"erro": "Preço mínimo maior que o máximo."}
    if not isinstance(apenas_disponiveis, bool) or not isinstance(em_promocao, bool):
        return {"erro": "Filtros de disponibilidade e promoção devem ser booleanos."}
    palavras = normalizar(termo or "").split()
    produtos, indisponiveis = [], []
    for linha in _linhas(ctx):
        p = _produto(linha, ctx)
        final = p["preco_promocional"] if p["preco_promocional"] is not None else p["preco"]
        if (categoria is not None and p["categoria"] != categoria) or not all(
            x in linha["nome_normalizado"] for x in palavras
        ):
            continue
        if em_promocao and p["desconto_percent"] is None:
            continue
        if (preco_min is not None and final < preco_min) or (
            preco_max is not None and final > preco_max
        ):
            continue
        if apenas_disponiveis and not p["disponivel"]:
            indisponiveis.append(p)
        else:
            produtos.append(p)

    def ordem(p):
        return (
            p["preco_promocional"] if p["preco_promocional"] is not None else p["preco"],
            p["id"],
        )

    produtos.sort(key=ordem)
    total = len(produtos)
    resultado = {"total": total, "produtos": produtos[:10]}
    # Sem isso o modelo lê "nada encontrado" e diz "não temos", sem buscar de novo
    # com apenas_disponiveis=false (SPEC-0002 §3.5, passo 6).
    if total == 0 and indisponiveis:
        resultado["aviso"] = AVISO_INDISPONIVEIS
        resultado["indisponiveis"] = sorted(indisponiveis, key=ordem)[:10]
    elif total == 0:
        resultado["aviso"] = "Nenhum produto encontrado com esses filtros."
    elif total > 10:
        resultado["aviso"] = (
            f"Mostrando os 10 mais baratos de {total}. "
            "Refine com termo ou faixa de preço para ver os demais."
        )
    return resultado


def detalhes_produto(product_id, *, ctx: Contexto) -> dict:
    if not _inteiro(product_id):
        return {"erro": "O id do produto deve ser um número inteiro."}
    product_id = int(product_id)
    linha = next((p for p in _linhas(ctx) if p["product_id"] == product_id), None)
    if linha is None:
        return {"erro": f"Produto {product_id} não encontrado."}
    return {
        **_produto(linha, ctx),
        "descricao": linha["description"],
        "specs": json.loads(linha["specs"]),
    }


ERRO_PEDIDO = (
    "Não encontrei um pedido com esses dados. "
    "Confira o número do pedido e o e-mail ou telefone usados na compra."
)


def consultar_pedido(order_id, email_ou_telefone, *, ctx: Contexto) -> dict:
    import re

    if not _inteiro(order_id):
        return {"erro": "O número do pedido deve ser um número inteiro."}
    if not isinstance(email_ou_telefone, str) or not email_ou_telefone.strip():
        return {"erro": "Informe o e-mail ou o telefone usado na compra."}
    pedido = ctx.conexao.execute(
        "SELECT o.*, c.email, c.phone FROM orders o JOIN customers c USING (customer_id) "
        "WHERE o.order_id = ?",
        (int(order_id),),
    ).fetchone()
    entrada = email_ou_telefone.strip()
    if pedido is None:
        return {"erro": ERRO_PEDIDO}
    if "@" in entrada:
        confere = entrada.lower() == pedido["email"].lower()
    else:
        digitos = re.sub(r"\D", "", entrada)
        if len(digitos) in (12, 13) and digitos.startswith("55"):
            digitos = digitos[2:]
        confere = digitos == re.sub(r"\D", "", pedido["phone"])
    if not confere:
        return {"erro": ERRO_PEDIDO}
    itens = [
        {"nome": r["name"], "quantidade": r["quantity"]}
        for r in ctx.conexao.execute(
            "SELECT p.name, i.quantity FROM order_items i JOIN products p USING (product_id) "
            "WHERE i.order_id = ? ORDER BY i.product_id",
            (int(order_id),),
        )
    ]
    entrega = pedido["estimated_delivery"]
    return {
        "pedido": pedido["order_id"],
        "status": pedido["status"],
        "data_pedido": pedido["order_date"],
        "total": pedido["total_brl"],
        "pagamento": pedido["payment_method"],
        "codigo_rastreio": pedido["tracking_code"],
        "previsao_entrega": entrega,
        "itens": itens,
        "observacao": pedido["notes"],
        "dias_desde_compra": (ctx.hoje - date.fromisoformat(pedido["order_date"])).days,
        "dias_desde_entrega": (ctx.hoje - date.fromisoformat(entrega)).days
        if pedido["status"] == "delivered" and entrega
        else None,
    }


MOTIVOS = ("reclamacao", "defeito_avaria", "dados_pessoais", "nao_resolvido", "pedido_do_cliente")
PRAZO_RETORNO = "24 horas úteis"
CANAL_WHATSAPP = "(67) 3341-4444"


def consultar_politica(topico, *, ctx: Contexto) -> dict:
    from app.politicas import texto_do_topico

    if not isinstance(topico, str):
        return {"erro": "Tópico deve ser texto."}
    try:
        return {"topico": topico, "texto": texto_do_topico(topico)}
    except ValueError as exc:
        return {"erro": str(exc)}


def encaminhar_atendente(motivo, resumo, contato=None, *, ctx: Contexto) -> dict:
    from datetime import datetime

    if not isinstance(motivo, str) or motivo not in MOTIVOS:
        return {"erro": f"Motivo inválido: {motivo}. Válidos: {', '.join(MOTIVOS)}"}
    if not isinstance(resumo, str) or not resumo.strip():
        return {"erro": "Informe um resumo do caso."}
    if contato is not None and not isinstance(contato, str):
        return {"erro": "Contato deve ser texto."}
    contato = (contato.strip() or None) if contato is not None else None
    ctx.pasta_logs.mkdir(parents=True, exist_ok=True)
    caminho = ctx.pasta_logs / "handoffs.jsonl"
    prefixo = f"EM-{ctx.hoje:%Y%m%d}-"
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
    numero = sum(json.loads(linha)["protocolo"].startswith(prefixo) for linha in linhas) + 1
    protocolo = f"{prefixo}{numero:04d}"
    registro = {
        "protocolo": protocolo,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "conversa_id": ctx.conversa_id,
        "motivo": motivo,
        "resumo": resumo.strip(),
        "contato": contato,
    }
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return {
        "protocolo": protocolo,
        "prazo_retorno": PRAZO_RETORNO,
        "canal_whatsapp": CANAL_WHATSAPP,
    }


@dataclass(frozen=True)
class Ferramenta:
    funcao: Callable[..., dict]
    descricao: str
    parametros: dict


TOOLS = {
    "buscar_produtos": Ferramenta(
        funcao=buscar_produtos,
        descricao=(
            "Busca instrumentos no catálogo e devolve preço, preço "
            "promocional, preço no PIX, estoque e disponibilidade já "
            "calculados. Use para qualquer pergunta sobre preço, "
            "disponibilidade, promoção ou opções de produto. Para o TIPO de "
            "instrumento (violão, guitarra, baixo, ukulele, bateria, teclado) "
            "use 'categoria': muitos nomes não dizem o tipo. Use 'termo' para "
            "marca ou modelo. Ordena do menor preço, devolve no máximo 10 e "
            "'total' diz quantos existem. 'total' 0 significa que a loja não "
            "tem no momento: não sugira produtos que não vieram desta busca."
        ),
        parametros={
            "type": "object",
            "properties": {
                "termo": {
                    "type": "string",
                    "description": (
                        "Marca e/ou modelo, ex.: 'yamaha', 'takamine gd20'. Todas as "
                        "palavras precisam estar no nome do produto."
                    ),
                },
                "categoria": {
                    "type": "string",
                    "description": ("Tipo de instrumento."),
                    "enum": list(CATEGORIAS),
                },
                "preco_min": {
                    "type": "number",
                    "description": (
                        "Preço mínimo em reais (compara com o preço promocional, quando houver)."
                    ),
                },
                "preco_max": {
                    "type": "number",
                    "description": (
                        "Preço máximo em reais (compara com o preço promocional, quando houver)."
                    ),
                },
                "apenas_disponiveis": {
                    "type": "boolean",
                    "description": (
                        "Padrão true: só produtos à venda e com estoque. Use false para "
                        "consultar um produto esgotado, descontinuado ou em "
                        "pré-lançamento."
                    ),
                },
                "em_promocao": {
                    "type": "boolean",
                    "description": ("Se true, só produtos com promoção ativa."),
                },
            },
            "required": [],
        },
    ),
    "detalhes_produto": Ferramenta(
        funcao=detalhes_produto,
        descricao=(
            "Devolve a descrição e as especificações técnicas (madeiras, "
            "cordas, captação etc.) de um produto, com preço e "
            "disponibilidade. Use quando o cliente quiser detalhes de um "
            "produto já encontrado por buscar_produtos."
        ),
        parametros={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "description": ("O id do produto, como veio em buscar_produtos."),
                },
            },
            "required": ["product_id"],
        },
    ),
    "consultar_pedido": Ferramenta(
        funcao=consultar_pedido,
        descricao=(
            "Consulta status, rastreio, previsão de entrega e itens de um "
            "pedido. Exige o número do pedido E o e-mail ou telefone de quem "
            "comprou: peça os dois antes de chamar. Também devolve "
            "dias_desde_compra e dias_desde_entrega já calculados, para "
            "conferir prazos de troca e devolução com "
            "consultar_politica('trocas_devolucoes')."
        ),
        parametros={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": ("Número do pedido."),
                },
                "email_ou_telefone": {
                    "type": "string",
                    "description": ("E-mail ou telefone do cliente, como ele informou."),
                },
            },
            "required": ["order_id", "email_ou_telefone"],
        },
    ),
    "consultar_politica": Ferramenta(
        funcao=consultar_politica,
        descricao=(
            "Devolve o texto oficial do manual da loja sobre um tópico. Use "
            "para horários, formas de pagamento e "
            "parcelamento, trocas e devoluções, frete e prazos de entrega, "
            "regras de promoção, garantia e privacidade. Responda só com o que "
            "estiver no texto."
        ),
        parametros={
            "type": "object",
            "properties": {
                "topico": {
                    "type": "string",
                    "description": (
                        "sobre_a_loja: quem somos, endereço, contatos; horarios; "
                        "pagamentos: formas e parcelamento; trocas_devolucoes: "
                        "arrependimento, defeito, preferência; frete_entregas: valores, "
                        "prazos, rastreio (não calcula frete por CEP); promocoes: regras "
                        "gerais (preço de produto vem de buscar_produtos); garantia; "
                        "privacidade: dados pessoais e LGPD."
                    ),
                    "enum": list(TOPICOS),
                },
            },
            "required": ["topico"],
        },
    ),
    "encaminhar_atendente": Ferramenta(
        funcao=encaminhar_atendente,
        descricao=(
            "Registra o caso para a equipe humana e devolve um protocolo. Use "
            "para reclamação, defeito ou avaria, pedido de exclusão de dados "
            "pessoais, problema que as outras ferramentas não resolvem, ou "
            "quando o cliente pedir uma pessoa pela segunda vez. Depois, "
            "informe ao cliente o protocolo, o prazo de retorno e o WhatsApp "
            "devolvidos."
        ),
        parametros={
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": ("Motivo principal do encaminhamento."),
                    "enum": list(MOTIVOS),
                },
                "resumo": {
                    "type": "string",
                    "description": (
                        "O que aconteceu, em 1 a 3 frases, com o número do pedido se "
                        "houver. Sem e-mail, telefone ou outros dados pessoais."
                    ),
                },
                "contato": {
                    "type": "string",
                    "description": (
                        "Telefone ou e-mail para retorno, só se o próprio cliente ofereceu."
                    ),
                },
            },
            "required": ["motivo", "resumo"],
        },
    ),
}
