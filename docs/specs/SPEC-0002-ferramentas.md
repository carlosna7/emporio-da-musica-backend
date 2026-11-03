# SPEC-0002 — Ferramentas do agente e regras de preço

- **Status:** aprovada
- **PRD:** [PRD-0001](../prds/PRD-0001-agente-atendimento.md)
- **Depende de:** SPEC-0001 (banco, `normalizar`, `conectar`, `politicas.py`). **Não** depende da SPEC-0003.

## 1. Objetivo
Entregar as 5 tools da [ARCHITECTURE §6](../ARCHITECTURE.md#6-tools-apptoolspy) como funções Python comuns, cada uma com a definição que o modelo vai ler (nome, descrição, JSON Schema), e as regras de preço em `app/precos.py` ([D07](../DECISIONS.md#d07--cálculos-feitos-no-código-não-pelo-llm)). A conversão para `ToolSpec` e o despacho das chamadas ficam na SPEC-0004.
Atende `PRD-0001/R2` (dados calculados no código, sem inventar), `R3` (produtos, promoções, pedidos), `R4` (políticas), `R7` (verificação do pedido, [D08](../DECISIONS.md#d08--consulta-de-pedido-exige-verificação-lgpd)) e `R8` (encaminhamento, [D11](../DECISIONS.md#d11--encaminhamento-para-atendente-humano)).

## 2. Escopo
- **Dentro:**
  - `app/precos.py`: função pura `calcular_precos`.
  - `app/tools.py`: `Contexto`, `CATEGORIAS`, `ERRO_PEDIDO`, as 5 funções e o registro `TOOLS` (nome → função, descrição, parâmetros).
  - As consultas SQL ficam em `app/tools.py` (único consumidor; `db.py` continua só com conexão e `normalizar`, como diz a ARCHITECTURE §2).
- **Fora:**
  - **Frete não é tool:** não há peso, dimensões nem tabela de transportadora; o agente usa `consultar_politica("frete_entregas")` (PRD: "calcular frete por CEP" está fora).
  - `ToolSpec`, despacho das chamadas, captura de exceções inesperadas, `AGENT_TODAY`/`.env` e system prompt: SPEC-0003/SPEC-0004. **`app/tools.py` não importa `app.llm`.**
  - Tradução de códigos (`delivered`, `credit_6x`): vão crus; o modelo traduz (ver §8).
  - Dependências novas: nenhuma (só stdlib).

## 3. Contrato

### 3.1 `app/precos.py`
```python
DESCONTO_PIX = 5   # %, manual §3

def calcular_precos(preco: float, descontos_ativos: list[int]) -> dict:
    """Devolve {"preco_promocional": float | None, "desconto_percent": int | None, "preco_pix": float | None}.
    - descontos_ativos: discount_percent das promoções com is_active = 1 do produto (pode ser vazia).
    - Com promoção: vale o MAIOR desconto; preco_promocional = preco com esse desconto; preco_pix = None
      (PIX não acumula com promoção, manual §6.2).
    - Sem promoção: preco_promocional = None, desconto_percent = None, preco_pix = preco com DESCONTO_PIX.
    Função pura: sem banco, sem validação (os valores vêm do banco tipado da SPEC-0001)."""
```
**Arredondamento (obrigatório):** `float((Decimal(str(preco)) * (100 - pct) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))`. Não usar `round()` de float: vários preços terminam em `,90` e o PIX cai em meio centavo (599,90 × 0,95 = 569,905); `round()` daria 569,9 e o correto é **569,91**.

### 3.2 `app/tools.py` — contexto e constantes
```python
PASTA_LOGS: Path   # <raiz do repo>/logs  (Path(__file__).resolve().parents[1] / "logs")

@dataclass
class Contexto:
    conexao: sqlite3.Connection   # vinda de app.db.conectar()
    hoje: date                    # o despachante passa AGENT_TODAY ou a data real
    conversa_id: str = ""
    pasta_logs: Path = PASTA_LOGS

CATEGORIAS: tuple[str, ...] = (
    "Guitarras", "Baixos", "Baterias e Percussão", "Teclados e Pianos", "Violões",
    "Instrumentos de Sopro (Madeiras)", "Instrumentos de Sopro (Metais)", "Cordas Orquestrais", "Ukuleles",
)   # = categories.name em ordem de category_id (teste garante); vira o enum de `categoria`

ERRO_PEDIDO = ("Não encontrei um pedido com esses dados. "
               "Confira o número do pedido e o e-mail ou telefone usados na compra.")
PRAZO_RETORNO = "24 horas úteis"
CANAL_WHATSAPP = "(67) 3341-4444"   # D13: nunca o (67) 3321-4500 do manual
```
**Contexto injetado:** toda tool recebe `ctx: Contexto` como parâmetro **keyword-only obrigatório** (`def f(..., *, ctx: Contexto)`). Motivo: o despachante da SPEC-0004 chama todas do mesmo jeito (`TOOLS[nome].funcao(**argumentos, ctx=ctx)`), sem saber o que cada uma usa, e o teste monta um único objeto; como o JSON Schema é escrito à mão, `ctx` nunca aparece nele.

### 3.3 Regras comuns
- Toda tool devolve um `dict` serializável em JSON (`json.dumps` funciona).
- Entrada inválida → `{"erro": "<mensagem em português>"}`, **sem** lançar exceção. Exceções inesperadas (banco fechado, bug) não são tratadas aqui: o despachante da SPEC-0004 as converte em `{"erro": ...}` (ARCHITECTURE §5).
- **Inteiro** (`product_id`, `order_id`): aceita `int` (não `bool`) e `float` com valor inteiro (`95.0` → `95`; o Gemini às vezes manda números como float). Qualquer outra coisa → erro.
- **Número** (`preco_min`, `preco_max`): `int` ou `float`, não `bool`, `>= 0`. **Booleano**: só `bool`. **Texto**: só `str`; `termo` vazio ou só espaços = não informado.
- **Disponível** = `status == "active"` e `estoque > 0` (ARCHITECTURE §6).
- **Preço final** de um produto = `preco_promocional` se houver promoção, senão `preco`.

### 3.4 Formato de produto
```python
# usado por buscar_produtos (cada item de "produtos") e detalhes_produto
{"id": int, "nome": str, "categoria": str, "preco": float,
 "preco_promocional": float | None, "desconto_percent": int | None, "preco_pix": float | None,
 "estoque": int, "status": "active" | "discontinued" | "coming_soon", "disponivel": bool}
# detalhes_produto acrescenta: "descricao": str | None, "specs": dict (json.loads de products.specs)
```
`preco_promocional`, `desconto_percent` e `preco_pix` vêm **sempre** de `calcular_precos(preco, descontos)`, com `descontos` = `discount_percent` das linhas de `promotions` com `is_active = 1` daquele produto.

### 3.5 As funções
```python
def buscar_produtos(termo: str | None = None, categoria: str | None = None,
                    preco_min: float | None = None, preco_max: float | None = None,
                    apenas_disponiveis: bool = True, em_promocao: bool = False,
                    *, ctx: Contexto) -> dict:
    """{"total": int, "produtos": [produto, ...], "aviso"?: str}"""
```
1. Validar os tipos (§3.3). `categoria`: comparar `normalizar(categoria.strip())` com `normalizar(nome)` de cada item de `CATEGORIAS` (aceita "violoes"); sem correspondência → `{"erro": "Categoria inválida: <valor>. Válidas: <CATEGORIAS separadas por vírgula>"}`. `preco_min > preco_max` → erro.
2. Ler **todos** os produtos com o nome da categoria (`products JOIN categories`) e montar cada um no formato da §3.4. O catálogo tem 65 itens: filtrar em Python é mais simples que montar SQL dinâmico e deixa o filtro de preço usar o preço final.
3. Filtros (todos combinados com E): categoria; `termo` → `normalizar(termo).split()`, **toda** palavra precisa ser substring de `nome_normalizado` (o nome, nunca a descrição); `apenas_disponiveis` → `disponivel`; `em_promocao` → `desconto_percent is not None`; `preco_min <= preço final <= preco_max`.
4. Ordenar por (preço final, id) crescente. `total` = quantidade filtrada; `produtos` = os 10 primeiros.
5. `aviso` só quando: `total == 0` → `"Nenhum produto encontrado com esses filtros."`; `total > 10` → `f"Mostrando os 10 mais baratos de {total}. Refine com termo ou faixa de preço para ver os demais."`. Categoria válida sem produtos (6, 7 e 8) cai no primeiro caso, sem erro.

**Por que o filtro de preço usa o preço final (promocional quando houver), e não o de tabela nem o PIX:** quem pergunta "até R$ 1000" quer saber o que vai pagar; o promocional vale para qualquer forma de pagamento, enquanto o PIX depende de o cliente escolher PIX. Ex.: o ukulele 121 (R$ 549,00, 20% off → R$ 439,20) aparece em "até R$ 440".

```python
def detalhes_produto(product_id: int, *, ctx: Contexto) -> dict:
    """produto (§3.4) + descricao + specs; inexistente → {"erro": "Produto <id> não encontrado."}"""

def consultar_pedido(order_id: int, email_ou_telefone: str, *, ctx: Contexto) -> dict:
    """{"pedido": int, "status": str, "data_pedido": str, "total": float, "pagamento": str,
        "codigo_rastreio": str | None, "previsao_entrega": str | None,
        "itens": [{"nome": str, "quantidade": int}], "observacao": str | None,
        "dias_desde_compra": int, "dias_desde_entrega": int | None}  ou  {"erro": ...}"""
```
1. `order_id` inválido → `{"erro": "O número do pedido deve ser um número inteiro."}`. `email_ou_telefone` não-`str` ou vazio após `strip()` → `{"erro": "Informe o e-mail ou o telefone usado na compra."}`. (Essas duas mensagens não dizem nada sobre o pedido existir.)
2. Buscar o pedido com o e-mail e o telefone **do cliente daquele pedido** (`orders JOIN customers`). Nunca procurar cliente só pelo e-mail ([D13](../DECISIONS.md#d13--tratamento-dos-dados-e-suposições): `bruno.martins@jmail.com` está nos clientes 11 e 43).
3. Conferência: se a entrada tem `@` → e-mail: `entrada.strip().lower() == email.lower()`. Senão → telefone: só os dígitos (`re.sub(r"\D", "", ...)`); se a entrada tiver 12 ou 13 dígitos e começar com `55`, tirar o `55` (DDI); comparar por igualdade com os dígitos de `customers.phone`.
4. Pedido inexistente **ou** dado que não confere → `{"erro": ERRO_PEDIDO}` (exatamente o mesmo dict).
5. `itens`: `order_items JOIN products`, ordenados por `product_id`. O retorno **não** inclui nome, e-mail nem telefone do cliente (mínimo necessário, LGPD).
6. `dias_desde_compra = (ctx.hoje - date.fromisoformat(order_date)).days`. `dias_desde_entrega = (ctx.hoje - date.fromisoformat(estimated_delivery)).days` **só** se `status == "delivered"` e `estimated_delivery` não é nulo; senão `None` (D13: a previsão é a data de recebimento). Sem limitar a zero.

**Por que os dois campos de dias:** contar dias entre datas é a conta que um LLM mais erra, e D07 manda fazer contas no código. O manual usa duas referências: arrependimento e troca por preferência contam do **recebimento** (§4.1, §4.3) e troca por defeito conta da **compra** (§4.2). A tool entrega os dois números e o prazo (7 ou 30 dias) continua vindo de `consultar_politica`, sem regra de política duplicada no código.

```python
def consultar_politica(topico: str, *, ctx: Contexto) -> dict:
    """{"topico": topico, "texto": app.politicas.texto_do_topico(topico)};
    tópico fora de TOPICOS → {"erro": str(ValueError)} (a mensagem já lista os válidos). ctx não é usado."""

def encaminhar_atendente(motivo: str, resumo: str, contato: str | None = None,
                         *, ctx: Contexto) -> dict:
    """{"protocolo": "EM-AAAAMMDD-XXXX", "prazo_retorno": PRAZO_RETORNO, "canal_whatsapp": CANAL_WHATSAPP}"""
```
1. `motivo` fora de `MOTIVOS = ("reclamacao", "defeito_avaria", "dados_pessoais", "nao_resolvido", "pedido_do_cliente")` → erro listando os válidos. `resumo` não-`str` ou vazio → erro. `contato` não-`str` (e não `None`) → erro; vazio após `strip()` → `None`. Em qualquer erro, nada é gravado.
2. Arquivo: `ctx.pasta_logs / "handoffs.jsonl"`; criar a pasta com `mkdir(parents=True, exist_ok=True)`.
3. Protocolo: `prefixo = f"EM-{ctx.hoje:%Y%m%d}-"`; `XXXX` = (quantidade de linhas do arquivo cujo `protocolo` começa com `prefixo`) + 1, com 4 dígitos (`0001`). Sequencial por dia, determinístico e testável sem mock; a data vem de `ctx.hoje` para bater com o "hoje" do agente.
4. Acrescentar uma linha: `json.dumps({"protocolo", "ts", "conversa_id", "motivo", "resumo", "contato"}, ensure_ascii=False)` + `"\n"`, nessa ordem de chaves, `encoding="utf-8"`. `ts = datetime.now().isoformat(timespec="seconds")` (hora real do registro); `resumo` e `contato` com `strip()`.

### 3.6 Registro `TOOLS`
```python
@dataclass(frozen=True)
class Ferramenta:
    funcao: Callable[..., dict]
    descricao: str      # texto que o modelo lê para decidir quando chamar
    parametros: dict    # JSON Schema: {"type": "object", "properties": {...}, "required": [...]}

TOOLS: dict[str, Ferramenta]   # chaves: os 5 nomes, na ordem abaixo
```
Schemas usam só `type`, `description`, `enum`, `properties` e `required` (subconjunto aceito pelos 3 provedores; sem `additionalProperties`, sem `null`). Opcional = fora de `required`. Os textos abaixo são **exatos**.

**`buscar_produtos`**
- descricao: `"Busca instrumentos no catálogo e devolve preço, preço promocional, preço no PIX, estoque e disponibilidade já calculados. Use para qualquer pergunta sobre preço, disponibilidade, promoção ou opções de produto. Para o TIPO de instrumento (violão, guitarra, baixo, ukulele, bateria, teclado) use 'categoria': muitos nomes não dizem o tipo. Use 'termo' para marca ou modelo. Ordena do menor preço, devolve no máximo 10 e 'total' diz quantos existem. 'total' 0 significa que a loja não tem no momento: não sugira produtos que não vieram desta busca."`
- `required: []`; properties:
  - `termo` string: `"Marca e/ou modelo, ex.: 'yamaha', 'takamine gd20'. Todas as palavras precisam estar no nome do produto."`
  - `categoria` string, `enum: list(CATEGORIAS)`: `"Tipo de instrumento."`
  - `preco_min` number: `"Preço mínimo em reais (compara com o preço promocional, quando houver)."`
  - `preco_max` number: `"Preço máximo em reais (compara com o preço promocional, quando houver)."`
  - `apenas_disponiveis` boolean: `"Padrão true: só produtos à venda e com estoque. Use false para consultar um produto esgotado, descontinuado ou em pré-lançamento."`
  - `em_promocao` boolean: `"Se true, só produtos com promoção ativa."`

**`detalhes_produto`**
- descricao: `"Devolve a descrição e as especificações técnicas (madeiras, cordas, captação etc.) de um produto, com preço e disponibilidade. Use quando o cliente quiser detalhes de um produto já encontrado por buscar_produtos."`
- `required: ["product_id"]`; `product_id` integer: `"O id do produto, como veio em buscar_produtos."`

**`consultar_pedido`**
- descricao: `"Consulta status, rastreio, previsão de entrega e itens de um pedido. Exige o número do pedido E o e-mail ou telefone de quem comprou: peça os dois antes de chamar. Também devolve dias_desde_compra e dias_desde_entrega já calculados, para conferir prazos de troca e devolução com consultar_politica('trocas_devolucoes')."`
- `required: ["order_id", "email_ou_telefone"]`; `order_id` integer: `"Número do pedido."`; `email_ou_telefone` string: `"E-mail ou telefone do cliente, como ele informou."`

**`consultar_politica`**
- descricao: `"Devolve o texto oficial do manual da loja sobre um tópico. Use para endereço e contatos, horários, formas de pagamento e parcelamento, trocas e devoluções, frete e prazos de entrega, regras de promoção, garantia e privacidade. Responda só com o que estiver no texto."`
- `required: ["topico"]`; `topico` string, `enum: list(TOPICOS)`: `"sobre_a_loja: quem somos, endereço, contatos; horarios; pagamentos: formas e parcelamento; trocas_devolucoes: arrependimento, defeito, preferência; frete_entregas: valores, prazos, rastreio (não calcula frete por CEP); promocoes: regras gerais (preço de produto vem de buscar_produtos); garantia; privacidade: dados pessoais e LGPD."`

**`encaminhar_atendente`**
- descricao: `"Registra o caso para a equipe humana e devolve um protocolo. Use para reclamação, defeito ou avaria, pedido de exclusão de dados pessoais, problema que as outras ferramentas não resolvem, ou quando o cliente pedir uma pessoa pela segunda vez. Depois, informe ao cliente o protocolo, o prazo de retorno e o WhatsApp devolvidos."`
- `required: ["motivo", "resumo"]`; properties:
  - `motivo` string, `enum: list(MOTIVOS)`: `"Motivo principal do encaminhamento."`
  - `resumo` string: `"O que aconteceu, em 1 a 3 frases, com o número do pedido se houver. Sem e-mail, telefone ou outros dados pessoais."`
  - `contato` string: `"Telefone ou e-mail para retorno, só se o próprio cliente ofereceu."`

## 4. Arquivos
- **Criar:** `app/precos.py`, `app/tools.py`, `tests/test_precos.py`, `tests/test_tools.py`
- **Alterar:** este arquivo (status e critérios ao final). `logs/` já está no `.gitignore`.
- **Não alterar:** `app/db.py`, `app/ingest.py`, `app/politicas.py`, `tests/conftest.py`, `docs/ARCHITECTURE.md` (mudanças propostas na §8).

## 5. Testes (escrever ANTES do código)
Comece no *red* (`ModuleNotFoundError` conta). Números conferidos nos CSVs em 2026-11-02. Importar `app.precos`/`app.tools` no topo dos arquivos de teste é permitido (a coleta falha só naquele arquivo).

**Fixtures:** as de `tests/conftest.py` (`banco`, `conexao`). Em `test_tools.py`, uma fixture local:
`ctx(conexao, tmp_path) -> Contexto(conexao=conexao, hoje=date(2026, 11, 2), conversa_id="teste", pasta_logs=tmp_path / "logs")`.
Toda chamada de tool nos testes passa `ctx=ctx` (omitido abaixo quando óbvio). Para outra data: `dataclasses.replace(ctx, hoje=...)`. Helper local `ids(r) = [p["id"] for p in r["produtos"]]`.

### `tests/test_precos.py` (sem banco)
- [ ] Sem promoção (Takamine GD20): `calcular_precos(2199.0, [])` → `{"preco_promocional": None, "desconto_percent": None, "preco_pix": 2089.05}`.
- [ ] Promoções ativas reais (parametrizado, `preco_pix is None` em todos):

  | Produto | `preco` | descontos | `preco_promocional` | `desconto_percent` |
  | --- | --- | --- | --- | --- |
  | 127 Kalani KAL-700T | 359.0 | `[10]` | 323.1 | 10 |
  | 121 Ohana CK-20 | 549.0 | `[20]` | 439.2 | 20 |
  | 90 Crafter HT-100 | 2399.0 | `[18]` | 1967.18 | 18 |
  | 94 Taylor 110e | 5999.0 | `[8]` | 5519.08 | 8 |
- [ ] Maior desconto vence, sem acumular: `calcular_precos(1000.0, [10, 25, 15])` → `preco_promocional == 750.0`, `desconto_percent == 25`, `preco_pix is None`.
- [ ] Meio centavo arredonda para cima (parametrizado, sem promoção): `599.9` → `preco_pix == 569.91`; `799.9` → `759.91`; `429.9` → `408.41`.
- [ ] Tipos: `preco_promocional` e `preco_pix` são `float` quando não `None`; `desconto_percent` é `int`.

### `tests/test_tools.py`
**Produtos (`buscar_produtos`, `detalhes_produto`)**
- [ ] Takamine GD20: `buscar_produtos(termo="takamine gd20", ctx=ctx)` → `total == 1` e o produto é exatamente `{"id": 95, "nome": "Takamine GD20 Dreadnought Natural", "categoria": "Violões", "preco": 2199.0, "preco_promocional": None, "desconto_percent": None, "preco_pix": 2089.05, "estoque": 5, "status": "active", "disponivel": True}` (a promoção 4 do produto 95 está inativa e não conta). Sem a chave `aviso`.
- [ ] Acento e maiúsculas: `termo="ACÚSTICA yamaha"` → `ids == [139, 141]`.
- [ ] `termo` só olha o nome: `termo="violão"` → `total == 0` e `"aviso"` presente (nenhum nome traz "violão"; por isso a descrição manda usar `categoria`).
- [ ] Violões até R$ 1000 (PRD, critério 1): `categoria="Violões", preco_max=1000` → `total == 12`, `ids == [83, 85, 89, 88, 81, 84, 87, 86, 107, 82]` e `"12" in aviso`. O mesmo com `categoria="violoes"` → `total == 12`. Os 96 (estoque 0) e 113 (`discontinued`) não aparecem.
- [ ] Promoção (produto 127): `termo="kal-700t"` → `preco == 359.0`, `preco_promocional == 323.1`, `desconto_percent == 10`, `preco_pix is None`.
- [ ] `em_promocao=True` → `total == 4`, `ids == [127, 121, 90, 94]`.
- [ ] Filtro pelo preço final: `categoria="Ukuleles", preco_max=440` → `ids == [119, 118, 116, 117, 127, 120, 121]` (121 entra pelo promocional 439,20); `categoria="Ukuleles", preco_min=440` → `121 not in ids`.
- [ ] Estoque zero (produto 96): `termo="gf-3d"` → `total == 0`; com `apenas_disponiveis=False` → `estoque == 0`, `status == "active"`, `disponivel is False`, `preco_pix == 759.91`.
- [ ] Descontinuado (113): `termo="sn-7c", apenas_disponiveis=False` → `status == "discontinued"`, `disponivel is False`. E `termo="7 cordas"` → `ids == [112, 110, 109, 111]`; com `apenas_disponiveis=False` → `ids == [113, 112, 110, 109, 111]`.
- [ ] Sem filtros: `buscar_produtos(ctx=ctx)` → `total == 61`, `len(produtos) == 10`, `ids[0] == 119`.
- [ ] Categorias vazias (parametrizado: `"Instrumentos de Sopro (Madeiras)"`, `"Instrumentos de Sopro (Metais)"`, `"Cordas Orquestrais"`) → `{"total": 0, "produtos": [], "aviso": "Nenhum produto encontrado com esses filtros."}`, sem `"erro"`.
- [ ] Entrada inválida (parametrizado; cada um devolve dict com `"erro"`): `categoria="Acessórios"` (e a mensagem contém `"Violões"`); `preco_max=-1`; `preco_max="mil"`; `preco_max=True`; `preco_min=500, preco_max=100`; `apenas_disponiveis="sim"`; `termo=123`.
- [ ] `detalhes_produto(95)` → campos da busca iguais aos do teste do Takamine, mais `descricao.startswith("Violão dreadnought Takamine")` e `specs == {"top": "Cedro Sólido", "back_sides": "Sapele", "neck": "Mogno", "strings": "steel", "scale": "650mm", "electronics": "no", "color": "Natural"}`.
- [ ] `detalhes_produto(130)` → `status == "coming_soon"`, `estoque == 2`, `disponivel is False`. `detalhes_produto(95.0)` → `id == 95`.
- [ ] `detalhes_produto` inválido (parametrizado): `999` → `{"erro": "Produto 999 não encontrado."}`; `"95"`, `True`, `95.5` → `"erro"` presente.

**Pedido (`consultar_pedido`)**
- [ ] Pedido 1 por e-mail (`"pedro.oliveira@jmail.com"`) → exatamente `{"pedido": 1, "status": "delivered", "data_pedido": "2025-10-15", "total": 11499.0, "pagamento": "pix", "codigo_rastreio": "BRAB1234567BR", "previsao_entrega": "2025-10-25", "itens": [{"nome": "Martin D-28 Dreadnought Natural", "quantidade": 1}], "observacao": None, "dias_desde_compra": 383, "dias_desde_entrega": 373}`.
- [ ] Mesmo resultado (parametrizado) com `" Pedro.Oliveira@JMAIL.COM "`, `"67984321098"`, `"67 98432-1098"` e `"+55 (67) 98432-1098"`.
- [ ] Dois itens, ainda não entregue: pedido 15 com `"aline.monteiro@jmail.com"` → `status == "pending"`, `total == 8348.0`, `pagamento == "credit_12x"`, `codigo_rastreio is None`, `previsao_entrega is None`, `itens == [{"nome": "Yamaha C70 Nylon Natural", "quantidade": 1}, {"nome": "Taylor 214ce Elétrico Aço Natural", "quantidade": 1}]`, `dias_desde_entrega is None`.
- [ ] Observação: pedido 17 com `"matheus.correia@hayoo.com.br"` → `status == "cancelled"`, `observacao == "Pedido cancelado pelo cliente antes do processamento"`.
- [ ] Arrependimento dentro do prazo: `ctx` com `hoje=date(2026, 1, 22)`, pedido 5 com `"rafael.pereira@jmail.com"` → `dias_desde_entrega == 4`, `dias_desde_compra == 17`. Pedido 8 (`shipped`) com `"anacarol.ferreira@coldmail.com"` → `dias_desde_entrega is None`.
- [ ] E-mail repetido (D13): pedido 10 com `"bruno.martins@jmail.com"` → `pedido == 10`, `itens == [{"nome": "Music Man Bass 1X Electric Bass", "quantidade": 1}]`; com `"(67) 98543-2109"` (cliente 11) → ok; com `"(67) 99456-3456"` (cliente 43, que não tem pedidos) → `{"erro": ERRO_PEDIDO}`.
- [ ] Mesma mensagem (parametrizado): `(1, "rafael.pereira@jmail.com")` (cliente de outro pedido), `(1, "98432-1098")` (telefone incompleto), `(999, "pedro.oliveira@jmail.com")` (pedido inexistente) → todos `== {"erro": ERRO_PEDIDO}`.
- [ ] Nenhum resultado de sucesso tem as chaves `email`, `telefone`, `phone` ou `nome_cliente`.
- [ ] Entrada inválida: `order_id="1"`, `order_id=True` e `email_ou_telefone="   "` → `"erro"` presente e diferente de `ERRO_PEDIDO`.

**Política e encaminhamento**
- [ ] `consultar_politica("trocas_devolucoes", ctx=ctx)` → `topico == "trocas_devolucoes"`, `texto.startswith("## 4. Política de Trocas e Devoluções")`, `"7 (sete) dias corridos" in texto`.
- [ ] `consultar_politica("frete_entregas", ctx=ctx)["texto"]` contém `"Frete grátis para pedidos acima de R$ 500,00"`.
- [ ] `consultar_politica("cordas", ctx=ctx)` → só a chave `"erro"`, que contém `"cordas"` e `"frete_entregas"`.
- [ ] Encaminhamento: `encaminhar_atendente("reclamacao", "Pedido 5 chegou com o tampo trincado.", ctx=ctx)` → `== {"protocolo": "EM-20261102-0001", "prazo_retorno": "24 horas úteis", "canal_whatsapp": "(67) 3341-4444"}`; `tmp_path / "logs" / "handoffs.jsonl"` existe (a pasta foi criada) com uma linha; `json.loads` dela tem as chaves `["protocolo", "ts", "conversa_id", "motivo", "resumo", "contato"]` nessa ordem, `conversa_id == "teste"`, `motivo == "reclamacao"`, `contato is None`, e `datetime.fromisoformat(ts)` não falha.
- [ ] Sequência: segunda chamada no mesmo `ctx` com `contato="(67) 99999-0000"` → `protocolo == "EM-20261102-0002"`, arquivo com 2 linhas, a segunda com `contato == "(67) 99999-0000"`. Com `hoje=date(2026, 11, 3)` → `"EM-20261103-0001"`. `contato="   "` → gravado como `None`.
- [ ] Encaminhamento inválido (parametrizado): `motivo="raiva"` (a mensagem contém `"reclamacao"`), `resumo=""`, `resumo=None`, `contato=5` → `"erro"` presente e o arquivo **não existe** depois.
- [ ] D13: o texto de `app/tools.py` não contém `"3321-4500"`.

**Registro `TOOLS`**
- [ ] `list(TOOLS) == ["buscar_produtos", "detalhes_produto", "consultar_pedido", "consultar_politica", "encaminhar_atendente"]` (frete não é tool).
- [ ] Para cada ferramenta: `descricao` não vazia; `parametros["type"] == "object"`; as chaves de `parametros["properties"]` são exatamente os parâmetros da função sem `ctx` (via `inspect.signature`), e `parametros["required"]` são exatamente os que não têm padrão; toda property tem `type` e `description`; nenhuma property se chama `ctx`, `conexao`, `hoje`, `conversa_id` ou `pasta_logs`.
- [ ] Enums: `categoria` == `list(CATEGORIAS)`; `topico` == `list(TOPICOS)`; `motivo` == `list(MOTIVOS)`. E `CATEGORIAS == tuple(r["name"] for r in conexao.execute("SELECT name FROM categories ORDER BY category_id"))`.
- [ ] `ctx` é keyword-only em todas: `inspect.signature(f).parameters["ctx"].kind == KEYWORD_ONLY`.
- [ ] Independência: o texto de `app/tools.py` não contém `"app.llm"`.
- [ ] Serializável: `json.dumps` funciona no retorno de uma chamada feliz de cada tool.

## 6. Plano
Cada par `test` → `feat` roda `pytest` (com `--basetemp` se o temp do sistema der `PermissionError`) e `ruff check .`.
1. `tests/test_precos.py`; confirmar o red → `test(precos): promoção, PIX e arredondamento`.
2. `app/precos.py` até verde → `feat(precos): regras de preço promocional e PIX`.
3. Testes de produtos em `tests/test_tools.py` (fixture `ctx`); red → `test(tools): busca e detalhes de produto`.
4. `app/tools.py`: `PASTA_LOGS`, `Contexto`, `CATEGORIAS`, validadores, montagem do produto, `buscar_produtos`, `detalhes_produto` → `feat(tools): busca e detalhes de produto`.
5. Testes de pedido; red → `test(tools): consulta de pedido com verificação`.
6. `ERRO_PEDIDO` e `consultar_pedido` → `feat(tools): consulta de pedido com verificação`.
7. Testes de política e encaminhamento; red → `test(tools): política e encaminhamento`.
8. `consultar_politica`, `MOTIVOS`, constantes e `encaminhar_atendente` → `feat(tools): política e encaminhamento`.
9. Testes do registro; red → `test(tools): registro das ferramentas`.
10. `Ferramenta` e `TOOLS` com os textos da §3.6; verificação manual; marcar critérios; status **implementada** → `feat(tools): registro das ferramentas`.

## 7. Critérios de aceite
- [ ] [AC-01] `calcular_precos` aplica só o maior desconto ativo, não dá PIX sobre promoção, dá 5% de PIX sem promoção e arredonda meio centavo para cima.
- [ ] [AC-02] `buscar_produtos` filtra por termo (palavras no nome normalizado), categoria (normalizada, com enum), disponibilidade, promoção e faixa de preço final; ordena por preço; devolve no máximo 10 com `total` e `aviso`; categoria vazia dá `total` 0 sem erro.
- [ ] [AC-03] `detalhes_produto` devolve os mesmos campos de preço da busca, mais `descricao` e `specs` como dict.
- [ ] [AC-04] `consultar_pedido` só responde com número do pedido + e-mail ou telefone do cliente daquele pedido; inexistente e não conferido devolvem o mesmo `ERRO_PEDIDO`; não expõe dados do cliente; traz `dias_desde_compra` e `dias_desde_entrega` calculados com `ctx.hoje`.
- [ ] [AC-05] `consultar_politica` devolve a seção do tópico; tópico inválido vira `{"erro"}`.
- [ ] [AC-06] `encaminhar_atendente` grava uma linha JSON em `<pasta_logs>/handoffs.jsonl`, gera `EM-AAAAMMDD-XXXX` sequencial por dia e devolve prazo e WhatsApp (67) 3341-4444.
- [ ] [AC-07] Nenhuma tool lança exceção por entrada inválida; `ctx` não aparece em nenhum JSON Schema; `TOOLS` tem as 5 tools com descrição e schema coerentes com a assinatura; `app/tools.py` não importa `app.llm`; sem dependências novas.
- [ ] [AC-TESTES] `pytest` verde
- [ ] [AC-LINT] `ruff check .` verde
- **Verificação manual** (depois de `python -m app.ingest`), com o prefixo
  `from datetime import date; from app.db import conectar; from app.tools import *; c = Contexto(conectar(), date(2026, 11, 2), "manual")`:
  - `print(buscar_produtos(termo="takamine gd20", ctx=c))` → `total: 1`, `preco_pix: 2089.05`.
  - `print(buscar_produtos(categoria="Violões", preco_max=1000, ctx=c)["aviso"])` → `Mostrando os 10 mais baratos de 12. ...`.
  - `print(consultar_pedido(1, "(67) 98432-1098", ctx=c)["status"])` → `delivered`; `print(consultar_pedido(1, "x@y.com", ctx=c))` → o `ERRO_PEDIDO`.
  - `print(encaminhar_atendente("pedido_do_cliente", "Teste manual", ctx=c))` → protocolo `EM-20261102-000N`; apagar a linha de teste de `logs/handoffs.jsonl` depois.

## 8. Riscos e pontos em aberto
**Decisões aprovadas pelo autor e incorporadas à ARCHITECTURE:**
1. **`buscar_produtos` devolve `{"total", "produtos", "aviso"?}`, não uma lista.** Motivo: o critério 1 do PRD ("violões até R$ 1000") tem 12 resultados e o limite é 10; com uma lista pura o agente diria que são só aqueles. O `aviso` também deixa explícito o "não temos no momento" das categorias 6, 7 e 8. Assim, todas as tools devolvem `dict`.
2. **`consultar_pedido` ganha `dias_desde_compra` e `dias_desde_entrega`** (justificativa na §3.5).
3. **Tools recebem `ctx: Contexto` keyword-only** e `app/tools.py` expõe `TOOLS: dict[str, Ferramenta]` em vez de `ToolSpec` (ARCHITECTURE §2 diz "funções das tools + ToolSpec de cada uma"). A SPEC-0004 monta `ToolSpec(nome, f.descricao, f.parametros)` e chama `f.funcao(**args, ctx=ctx)`, capturando `TypeError` (argumento faltando ou a mais) junto com as demais exceções. Isso muda o `Agente.__init__` da ARCHITECTURE §5 (`tools: dict[str, Callable], specs: list[ToolSpec]`), que pode passar a receber `TOOLS` e o `Contexto`.
4. **`categoria` vira `enum`** com os 9 nomes de `categories` (inclusive os 3 vazios), e o filtro de preço usa o **preço final** (promocional quando houver). Ambos não estão escritos na ARCHITECTURE.

**Riscos e suposições:**
- `termo` busca só no nome, e nenhum nome contém "violão": se o modelo ignorar a descrição e mandar `termo="violão"`, recebe `total` 0. Mitigação: a descrição da tool e um caso de avaliação (SPEC-0006) para "violões até R$ 1000". Alternativa, se os evals falharem: também comparar o termo com o nome da categoria.
- Códigos crus (`delivered`, `credit_12x`): o modelo traduz. Se os evals mostrarem erro de tradução, um dicionário em `tools.py` resolve.
- Pedidos são de 2025–2026; com a data real, só os `delivered` têm `dias_desde_entrega`, e todos já passaram de 7 dias. Para exemplos de arrependimento dentro do prazo, a SPEC-0006/0007 precisa fixar `AGENT_TODAY` (ex.: `2026-01-22` com o pedido 5).
- Protocolo sequencial lendo o arquivo não é seguro com dois processos gravando ao mesmo tempo. Aceitável para a CLI (um processo).
