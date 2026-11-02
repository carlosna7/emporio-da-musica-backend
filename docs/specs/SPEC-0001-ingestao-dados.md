# SPEC-0001 — Ingestão de dados e leitura das políticas

- **Status:** aprovada
- **PRD:** [PRD-0001](../prds/PRD-0001-agente-atendimento.md)
- **Depende de:** —

## 1. Objetivo
Transformar os CSVs de `data/raw/` num banco SQLite tipado e somente leitura (`data/emporio.db`) e expor as seções do manual (`data/politicas.md`) por tópico. É a base de dados das tools (SPEC-0002) e do system prompt (SPEC-0004).
Atende `PRD-0001/R2`, `R3` e `R4` (a fonte que as tools vão consultar).

## 2. Escopo
- **Dentro:**
  - `app/ingest.py`: CSV → SQLite, recriando o banco do zero a cada execução; `python -m app.ingest`.
  - `app/db.py`: abrir conexão somente leitura; `normalizar()` (a mesma função serve para `nome_normalizado` aqui e para o termo de busca na SPEC-0002).
  - `app/politicas.py`: separar as seções `## N. Título` de `data/politicas.md` e mapear os tópicos da ARCHITECTURE §6.
  - Os tratamentos de [D13](../DECISIONS.md#d13--tratamento-dos-dados-e-suposições) que são de ingestão: tipos, vazio → `NULL`, `specs` validado.
- **Fora:**
  - Conversão do PDF: `data/politicas.md` já existe (transcrição manual, D17). Nada de `pypdf`.
  - Regras de preço, promoção vigente, PIX e disponibilidade; consultas de produto/pedido; as tools (SPEC-0002).
  - Os demais itens da D13 (telefone, e-mail, parcelamento, `total_brl`, nomes 135–144, `coming_soon`): são regra de negócio ou de prompt. A ingestão **não altera nenhum valor** dos CSVs, só converte tipos.
  - Qualquer coisa de LLM (SPEC-0003) e o system prompt (SPEC-0004).
  - `app/config.py`: não é necessário; os caminhos são constantes de módulo com parâmetro opcional nas funções.

## 3. Contrato

### `app/db.py`
```python
CAMINHO_BANCO: Path   # <raiz do repo>/data/emporio.db  (Path(__file__).resolve().parents[1] / "data" / "emporio.db")

def normalizar(texto: str) -> str:
    """Minúsculas e sem acento: unicodedata.normalize("NFKD", texto.lower()) sem os caracteres combinantes.
    Não remove pontuação nem espaços. Ex.: "Bateria Acústica" -> "bateria acustica"; "Aço" -> "aco"."""

def conectar(caminho: Path = CAMINHO_BANCO) -> sqlite3.Connection:
    """Abre o banco em modo somente leitura, com row_factory = sqlite3.Row.
    URI: f"{caminho.resolve().as_uri()}?mode=ro" com uri=True (funciona com espaços e acentos no caminho).
    Se o arquivo não existe: FileNotFoundError com mensagem contendo "python -m app.ingest"
    (verificar antes de conectar; nunca criar o arquivo)."""
```

### `app/ingest.py`
```python
PASTA_CSV: Path       # <raiz do repo>/data/raw
TABELAS: tuple[str, ...] = ("categories", "customers", "products", "orders", "order_items", "promotions")
                      # ordem de carga (respeita as FKs); cada tabela vem de PASTA_CSV / f"{tabela}.csv"

def criar_banco(destino: Path = CAMINHO_BANCO, origem: Path = PASTA_CSV) -> dict[str, int]:
    """Apaga `destino` se existir, cria o schema abaixo e carrega os CSVs. Devolve {tabela: linhas inseridas}.
    Em qualquer erro: fecha a conexão, apaga `destino` e relança a exceção (nunca deixa banco pela metade)."""

def main() -> None:   # `python -m app.ingest`: criar_banco() e imprime o caminho e a contagem por tabela
```

Regras da carga:
- CSV lido com `csv.DictReader`, `encoding="utf-8"`, `newline=""`. Conexão de escrita com `PRAGMA foreign_keys = ON`.
- Todo valor passa por `.strip()`; **string vazia → `NULL`** (em qualquer coluna). Coluna `NOT NULL` vazia falha no SQLite (erro alto, sem pular linha).
- Conversões por coluna (o resto fica `TEXT` como veio):

| Conversão | Colunas |
| --- | --- |
| `int()` | todas as `*_id`, `stock_quantity`, `quantity`, `discount_percent`, `is_active` |
| `float()` | `price_brl`, `total_brl` |
| data ISO validada com `date.fromisoformat()`, gravada como o texto original | `created_at`, `order_date`, `estimated_delivery` |
| `json.loads()`; tem que ser `dict`, senão `ValueError` com o `product_id`; grava o texto original | `products.specs` |
| calculada: `normalizar(name)` | `products.nome_normalizado` |

- `is_active` vira `0`/`1` (o CHECK do schema garante).
- Mensagem do `ValueError` de `specs`: deve conter o `product_id` (ex.: `"specs inválido no produto 95"`).

Schema (criado exatamente assim):
```sql
CREATE TABLE categories (
    category_id   INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT
);
CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    phone         TEXT NOT NULL,
    email         TEXT NOT NULL,          -- sem UNIQUE: bruno.martins@jmail.com está nos clientes 11 e 43
    city          TEXT
);
CREATE TABLE products (
    product_id       INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    nome_normalizado TEXT NOT NULL,
    category_id      INTEGER NOT NULL REFERENCES categories(category_id),
    description      TEXT,
    price_brl        REAL NOT NULL,
    stock_quantity   INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('active', 'discontinued', 'coming_soon')),
    specs            TEXT NOT NULL,       -- objeto JSON validado
    created_at       TEXT NOT NULL        -- AAAA-MM-DD
);
CREATE TABLE orders (
    order_id           INTEGER PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date         TEXT NOT NULL,
    status             TEXT NOT NULL,     -- pending | confirmed | shipped | delivered | cancelled
    total_brl          REAL NOT NULL,
    payment_method     TEXT NOT NULL,
    tracking_code      TEXT,
    estimated_delivery TEXT,
    notes              TEXT
);
CREATE TABLE order_items (
    order_id    INTEGER NOT NULL REFERENCES orders(order_id),
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    quantity    INTEGER NOT NULL,
    PRIMARY KEY (order_id, product_id)
);
CREATE TABLE promotions (
    promotion_id     INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products(product_id),
    discount_percent INTEGER NOT NULL,
    description      TEXT,
    is_active        INTEGER NOT NULL CHECK (is_active IN (0, 1))
);
```

### `app/politicas.py`
```python
CAMINHO_POLITICAS: Path   # <raiz do repo>/data/politicas.md
TOPICOS: dict[str, int] = {
    "sobre_a_loja": 1, "horarios": 2, "pagamentos": 3, "trocas_devolucoes": 4,
    "frete_entregas": 5, "promocoes": 6, "garantia": 8, "privacidade": 9,
}   # ARCHITECTURE §6; a SPEC-0002 usa as chaves no Literal de consultar_politica

def carregar_secoes(caminho: Path = CAMINHO_POLITICAS) -> dict[int, str]:
    """{número: texto} de cada seção `## N. Título`."""

def texto_do_topico(topico: str, caminho: Path = CAMINHO_POLITICAS) -> str:
    """Texto da seção do tópico. Tópico fora de TOPICOS -> ValueError cuja mensagem
    cita o tópico recebido e lista os válidos."""

def texto_da_secao(numero: int, caminho: Path = CAMINHO_POLITICAS) -> str:
    """Qualquer seção pelo número (a SPEC-0004 usa 7 e 10). Número inexistente -> ValueError."""
```

Regras do recorte:
- Uma seção começa na linha que casa `^## (\d+)\. ` e termina **antes** da próxima linha que começa com `## ` ou no fim do arquivo. `### ` não encerra seção.
- O texto inclui a própria linha de título e todas as subseções `###`; aplicar `.strip()` no resultado.
- Tudo antes do `## 1.` (comentário HTML, capa) é ignorado. O arquivo é lido a cada chamada (é pequeno; sem cache).

## 4. Arquivos
- **Criar:** `app/db.py`, `app/ingest.py`, `app/politicas.py`, `tests/conftest.py`, `tests/test_db.py`, `tests/test_ingest.py`, `tests/test_politicas.py`
- **Alterar:** este arquivo (status e critérios ao final). `.gitignore` já cobre `*.db`; não mexer.
- **Testes:** os três `tests/test_*.py` acima.

## 5. Testes (escrever ANTES do código)
Comece no *red* (falhar por `ModuleNotFoundError` conta como red). Números conferidos nos CSVs em 2026-11-02.

**Fixtures (`tests/conftest.py`)** — fazer o `import` de `app` **dentro** das fixtures, para que `tests/test_ambiente.py` continue passando no red:
- `banco(tmp_path) -> Path`: `criar_banco(destino=tmp_path / "emporio.db")` com a `origem` padrão (`data/raw` real); devolve o caminho.
- `conexao(banco)`: `conectar(banco)`, `yield`, `close()` (no Windows, fechar é obrigatório para limpar o `tmp_path`).

**Helper local em `test_ingest.py`** — `copiar_csvs(tmp_path) -> Path`: copia os 6 CSVs de `data/raw` para `tmp_path / "raw"` (`shutil.copy`). Para editar uma linha: ler com `csv.DictReader`, alterar o campo, regravar com `csv.DictWriter` (mesmos `fieldnames`, `encoding="utf-8"`, `newline=""`). **Nunca** escrever em `data/raw`.

### `tests/test_db.py`
- [ ] `normalizar`: `"Violão Elétrico AÇO"` → `"violao eletrico aco"`; `"Barítono"` → `"baritono"`; `"Gibson Les Paul Standard '50s"` → `"gibson les paul standard '50s"`; `""` → `""`.
- [ ] `conectar(banco)` lê com `sqlite3.Row`: `SELECT name FROM categories WHERE category_id = 5` → `row["name"] == "Violões"`.
- [ ] Somente leitura: `conexao.execute("DELETE FROM products")` levanta `sqlite3.OperationalError` (`match="readonly"`).
- [ ] Banco inexistente: `conectar(tmp_path / "nao_existe.db")` levanta `FileNotFoundError` com `"python -m app.ingest"` na mensagem, e o arquivo **continua não existindo** depois.
- [ ] Caminho com espaço e acento: `criar_banco(destino=tmp_path / "com espaço" / "emporio.db")` (a pasta não existe antes: `criar_banco` cria com `mkdir(parents=True, exist_ok=True)`); `conectar` nesse caminho e `SELECT COUNT(*) FROM products` → `65`.

### `tests/test_ingest.py`
- [ ] **Contagens:** o retorno de `criar_banco` é `{"categories": 9, "customers": 50, "products": 65, "orders": 20, "order_items": 22, "promotions": 25}` e `SELECT COUNT(*)` de cada tabela bate com ele.
- [ ] **Produto 95 completo:** `SELECT * FROM products WHERE product_id = 95` →
  `name == "Takamine GD20 Dreadnought Natural"`, `nome_normalizado == "takamine gd20 dreadnought natural"`, `category_id == 5`, `price_brl == 2199.0` e `isinstance(price_brl, float)`, `stock_quantity == 5` e `isinstance(..., int)`, `status == "active"`, `created_at == "2021-11-03"`,
  `json.loads(specs) == {"top": "Cedro Sólido", "back_sides": "Sapele", "neck": "Mogno", "strings": "steel", "scale": "650mm", "electronics": "no", "color": "Natural"}`.
- [ ] **Preço decimal:** produto 81 → `price_brl == 599.9`; pedido 4 → `total_brl == 799.9`; pedido 1 → `total_brl == 11499.0`.
- [ ] **Tipos no SQLite** (cada consulta devolve `0`):
  `SELECT COUNT(*) FROM products WHERE typeof(price_brl) <> 'real' OR typeof(stock_quantity) <> 'integer'`;
  `SELECT COUNT(*) FROM orders WHERE typeof(total_brl) <> 'real'`;
  `SELECT COUNT(*) FROM promotions WHERE typeof(is_active) <> 'integer' OR typeof(discount_percent) <> 'integer'`.
- [ ] **Nome normalizado:** produto 139 → `"bateria acustica yamaha kit 1 studio"`; produto 98 → `"yamaha ntx1 eletrico nylon natural"`; produto 128 → `"kala ka-b baritono mogno"`. E, para todos os 65 produtos, `nome_normalizado == normalizar(name)`.
- [ ] **Vazio → NULL:** pedido 9 → `tracking_code is None`, `estimated_delivery is None`, `notes is None`; pedido 1 → `tracking_code == "BRAB1234567BR"`, `estimated_delivery == "2025-10-25"`, `notes is None`; pedido 17 → `notes == "Pedido cancelado pelo cliente antes do processamento"`. Contagens: `tracking_code IS NULL` → `12`; `notes IS NOT NULL` → `4`; `WHERE tracking_code = '' OR notes = ''` → `0`.
- [ ] **Promoções ativas:** `SELECT promotion_id, product_id, discount_percent FROM promotions WHERE is_active = 1 ORDER BY promotion_id` → `[(12, 127, 10), (14, 121, 20), (19, 90, 18), (24, 94, 8)]`; `SELECT DISTINCT is_active` → `{0, 1}`.
- [ ] **Status dos produtos:** `SELECT status, COUNT(*) ... GROUP BY status` → `{"active": 62, "discontinued": 2, "coming_soon": 1}` (o `coming_soon` é o 130).
- [ ] **Specs:** os 65 `specs` fazem `json.loads` para `dict`; produto 131 → `{"body": "Mahogany", "neck": "Mahogany", "strings": "6", "color": "Heritage Cherry Sunburst"}`.
- [ ] **Recria do zero:** rodar `criar_banco` duas vezes no mesmo `destino` → `products` continua com `65`. E: criar antes um arquivo SQLite em `destino` com `CREATE TABLE lixo (x)`; depois de `criar_banco`, `SELECT name FROM sqlite_master WHERE name = 'lixo'` não devolve nada.
- [ ] **Specs inválido** (parametrizado com `"{nao é json"` e `"[1, 2]"`): `copiar_csvs`, trocar o `specs` do produto 95, `criar_banco(destino, origem=pasta)` levanta `ValueError` com `"95"` na mensagem, e `destino` **não existe** depois.
- [ ] **FK ativa:** `copiar_csvs`, trocar o `product_id` da primeira linha de `order_items.csv` (pedido 1) de `93` para `999` → `criar_banco` levanta `sqlite3.IntegrityError`, e `destino` não existe depois.

### `tests/test_politicas.py`
Todos usam o `data/politicas.md` real (caminho padrão).
- [ ] `carregar_secoes()` tem as chaves `1` a `10`, exatamente.
- [ ] **Todos os tópicos** (parametrizado) — `texto_do_topico(t).startswith(titulo)`:

  | Tópico | Título esperado |
  | --- | --- |
  | `sobre_a_loja` | `## 1. Sobre a Empório da Música` |
  | `horarios` | `## 2. Horário de Funcionamento` |
  | `pagamentos` | `## 3. Formas de Pagamento` |
  | `trocas_devolucoes` | `## 4. Política de Trocas e Devoluções` |
  | `frete_entregas` | `## 5. Política de Frete e Entregas` |
  | `promocoes` | `## 6. Promoções e Descontos` |
  | `garantia` | `## 8. Garantia` |
  | `privacidade` | `## 9. Privacidade e Proteção de Dados` |
- [ ] **Conteúdo com subseções:** `texto_do_topico("trocas_devolucoes")` contém `"7 (sete) dias corridos após o recebimento"` e `"### 4.4 Itens Não Elegíveis para Troca"`, e **não** contém `"## 5."`.
- [ ] **Tabela preservada:** `texto_do_topico("horarios")` contém `"| Sábado | 09:00 às 13:00 |"`.
- [ ] **Capa fora:** `texto_do_topico("sobre_a_loja")` contém `"### 1.2 Dados da Empresa"` e `"Rua 14 de Maio, 3200"`, e **não** contém `"MANUAL DE POLÍTICAS"` nem `"<!--"`.
- [ ] **Tópico inválido:** `texto_do_topico("cordas")` levanta `ValueError`; a mensagem contém `"cordas"` e `"frete_entregas"` (lista os válidos).
- [ ] **Seções do prompt:** `texto_da_secao(7)` começa com `"## 7. Atendimento via WhatsApp"` e contém `"### 7.3 Situações Especiais"`; `texto_da_secao(10)` começa com `"## 10. Disposições Finais"` e contém `"consultar a gerência"`.
- [ ] **Seção inexistente:** `texto_da_secao(11)` levanta `ValueError`.
- [ ] `TOPICOS` tem exatamente as 8 chaves da tabela acima, e nenhum valor é `7` ou `10`.

## 6. Plano
1. `tests/conftest.py`, `tests/test_db.py`, `tests/test_ingest.py`; rodar `pytest` e ver os novos falhando (`test_ambiente.py` segue verde) → commit `test(ingest): ingestão CSV → SQLite e conexão somente leitura`.
2. `app/db.py` (`CAMINHO_BANCO`, `normalizar`, `conectar`).
3. `app/ingest.py` (schema, conversões, `criar_banco`, `main`) até `pytest` e `ruff check .` verdes → commit `feat(ingest): banco SQLite a partir dos CSVs`.
4. `tests/test_politicas.py`; confirmar o red → commit `test(politicas): seções e tópicos do manual`.
5. `app/politicas.py` até verde; rodar a verificação manual; marcar os critérios e mudar o status para **implementada** → commit `feat(politicas): leitura das seções do manual por tópico`.

## 7. Critérios de aceite
- [ ] [AC-01] `python -m app.ingest` cria `data/emporio.db` do zero com as 6 tabelas e o schema da §3; rodar de novo dá o mesmo resultado.
- [ ] [AC-02] Tipos corretos no banco: preços `REAL`, estoque e ids `INTEGER`, `is_active` 0/1, vazio → `NULL`, `specs` é objeto JSON válido, `nome_normalizado` sem acento (testes da §5).
- [ ] [AC-03] Dado inválido (specs não-objeto, FK quebrada) interrompe a ingestão com erro que identifica o problema e não deixa banco parcial.
- [ ] [AC-04] `conectar()` abre o banco somente leitura (escrita falha) e, sem banco, orienta a rodar `python -m app.ingest`.
- [ ] [AC-05] `texto_do_topico` devolve a seção completa (com `###`) de cada um dos 8 tópicos; tópico inválido gera `ValueError` que lista os válidos; `texto_da_secao(7)` e `texto_da_secao(10)` funcionam.
- [ ] [AC-06] Nenhuma dependência nova (só stdlib); `data/raw/` intocado; `data/emporio.db` ignorado pelo git (`*.db`).
- [ ] [AC-TESTES] `pytest` verde
- [ ] [AC-LINT] `ruff check .` verde
- **Verificação manual:**
  - `python -m app.ingest` → imprime o caminho de `data/emporio.db` e `categories: 9`, `customers: 50`, `products: 65`, `orders: 20`, `order_items: 22`, `promotions: 25`.
  - `python -c "from app.db import conectar; print(tuple(conectar().execute('SELECT name, price_brl FROM products WHERE product_id = 95').fetchone()))"` → `('Takamine GD20 Dreadnought Natural', 2199.0)`.
  - `python -c "from app.politicas import texto_do_topico; print(texto_do_topico('horarios'))"` → a seção 2 com a tabela de horários.
  - `git check-ignore data/emporio.db` → `data/emporio.db`.

## 8. Riscos e pontos em aberto
**Decisões do autor (resolvidas):**
1. **Contatos oficiais:** e-mail `contato@emporiodamusica.com.br` (sem acento) e telefone/WhatsApp **(67) 3341-4444**. O e-mail da §1.2 do `politicas.md` já foi corrigido para o sem acento, então o tópico `sobre_a_loja` sai certo e esta spec não muda. O número (67) 3321-4500 da §7 deve ser **desconsiderado**: a SPEC-0004 põe os contatos oficiais no system prompt com a instrução de usar só eles, e a SPEC-0002 usa 3341-4444 em `canal_whatsapp`. Ver D13 e ARCHITECTURE §8.
2. **E-mail repetido** (`bruno.martins@jmail.com` nos clientes 11, Bruno Carvalho Martins, e 43, Bruno Martins, ambos de Três Lagoas, com telefones diferentes): o dado **não é corrigido** e `customers.email` fica **sem `UNIQUE`**. Corrigir exigiria saber qual cadastro está certo, ou seja, inventar dado. Para o agente não muda nada: a verificação de pedido (D08) compara o e-mail com o cliente **daquele pedido** (o pedido 10 é do cliente 11; o 43 não tem pedidos) e nunca busca cliente só pelo e-mail. Em produção o e-mail seria `UNIQUE`, e a equipe resolveria o caso na origem (ver D13).

**Achado nos dados, sem ação nesta spec:**
- Catálogo menor que o manual: 65 produtos (ids 81–145) e as categorias 6, 7 e 8 (sopro madeiras, sopro metais, cordas orquestrais) **sem nenhum produto**, embora o manual §1 cite esses instrumentos e "mais de 300". As SPECs 0002/0004 precisam responder "não temos no momento" em vez de inventar.

**Suposições:** a ingestão falha alto em qualquer dado fora do esperado (sem pular linhas), porque os CSVs são fixos e pequenos; `specs` é gravado como o texto original do CSV, depois de validado.

**Ajustes sugeridos em outros documentos (não editados aqui):**
- PRD-0001, roadmap: a linha da SPEC-0001 diz "CSV + PDF → SQLite + `politicas.md`"; a conversão do PDF já foi feita à mão (D17). Sugestão: "CSV → SQLite + leitura de `politicas.md`".
- ARCHITECTURE §2 descreve `db.py` como "conexão e consultas"; aqui ele tem só conexão e `normalizar`. Onde ficam as consultas (em `db.py` ou em `tools.py`) é decisão da SPEC-0002.
- ARCHITECTURE §7: vale registrar o caminho `data/emporio.db`, que `python -m app.ingest` o recria e que a leitura usa `mode=ro`.
