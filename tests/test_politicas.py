import pytest


def test_carregar_secoes():
    from app.politicas import carregar_secoes

    assert set(carregar_secoes()) == set(range(1, 11))


@pytest.mark.parametrize(
    ("topico", "titulo"),
    [
        ("sobre_a_loja", "## 1. Sobre a Empório da Música"),
        ("horarios", "## 2. Horário de Funcionamento"),
        ("pagamentos", "## 3. Formas de Pagamento"),
        ("trocas_devolucoes", "## 4. Política de Trocas e Devoluções"),
        ("frete_entregas", "## 5. Política de Frete e Entregas"),
        ("promocoes", "## 6. Promoções e Descontos"),
        ("garantia", "## 8. Garantia"),
        ("privacidade", "## 9. Privacidade e Proteção de Dados"),
    ],
)
def test_titulo_de_cada_topico(topico, titulo):
    from app.politicas import texto_do_topico

    assert texto_do_topico(topico).startswith(titulo)


def test_conteudo_com_subsecoes():
    from app.politicas import texto_do_topico

    texto = texto_do_topico("trocas_devolucoes")
    assert "7 (sete) dias corridos após o recebimento" in texto
    assert "### 4.4 Itens Não Elegíveis para Troca" in texto
    assert "## 5." not in texto


def test_tabela_de_horarios_preservada():
    from app.politicas import texto_do_topico

    assert "| Sábado | 09:00 às 13:00 |" in texto_do_topico("horarios")


def test_capa_fora_da_secao_sobre_a_loja():
    from app.politicas import texto_do_topico

    texto = texto_do_topico("sobre_a_loja")
    assert "### 1.2 Dados da Empresa" in texto
    assert "Rua 14 de Maio, 3200" in texto
    assert "MANUAL DE POLÍTICAS" not in texto
    assert "<!--" not in texto


def test_topico_invalido_lista_validos():
    from app.politicas import texto_do_topico

    with pytest.raises(ValueError) as erro:
        texto_do_topico("cordas")
    assert "cordas" in str(erro.value)
    assert "frete_entregas" in str(erro.value)


@pytest.mark.parametrize(
    ("numero", "titulo", "conteudo"),
    [
        (7, "## 7. Atendimento via WhatsApp", "### 7.3 Situações Especiais"),
        (10, "## 10. Disposições Finais", "consultar a gerência"),
    ],
)
def test_secoes_do_prompt(numero, titulo, conteudo):
    from app.politicas import texto_da_secao

    texto = texto_da_secao(numero)
    assert texto.startswith(titulo)
    assert conteudo in texto


def test_secao_inexistente():
    from app.politicas import texto_da_secao

    with pytest.raises(ValueError):
        texto_da_secao(11)


def test_topicos_excluem_secoes_do_prompt():
    from app.politicas import TOPICOS

    assert set(TOPICOS) == {
        "sobre_a_loja",
        "horarios",
        "pagamentos",
        "trocas_devolucoes",
        "frete_entregas",
        "promocoes",
        "garantia",
        "privacidade",
    }
    assert 7 not in TOPICOS.values()
    assert 10 not in TOPICOS.values()
