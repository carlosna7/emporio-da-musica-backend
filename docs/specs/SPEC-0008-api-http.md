# SPEC-0008 — API HTTP sem estado para o site

- **Status:** aprovada
- **PRD:** [PRD-0001](../prds/PRD-0001-agente-atendimento.md) (evolução opcional prevista em "Fora do escopo")
- **Depende de:** SPEC-0004 (`criar_agente`, `Agente.responder`, `Resposta`). Usa `criar_banco` e `conectar` da SPEC-0001 e `criar_cliente` da SPEC-0003.

## 1. Objetivo
Expor o Emilio por HTTP para o site da loja, sem guardar estado no servidor: o navegador mantém o histórico e o reenvia a cada pergunta, como a CLI faz com a lista em memória ([D09](../DECISIONS.md#d09--memória-da-conversa-sim-persistência-do-histórico-não), [D10](../DECISIONS.md#d10--interface-cli)). A chave do LLM fica só no backend e a rota de conversa pode exigir um token ([D15](../DECISIONS.md#d15--publicação-se-houver-front)). O mesmo app roda local (`uvicorn`) e como função Python na Vercel.

## 2. Escopo
- **Dentro:** `app/api.py` (fábrica `criar_app`, rotas `GET /health` e `POST /chat`, token opcional, CORS opcional, banco e logs graváveis na Vercel); `api/index.py` (entrada da Vercel); `.vercelignore`; dependências `fastapi` e, no extra `dev`, `httpx` e `uvicorn`; variáveis novas no `.env.example`; seção da API no README.
- **Fora:**
  - Mudanças no agente, nas tools, na config, na ingestão e na CLI.
  - Persistência de conversas no servidor, autenticação de clientes finais, streaming.
  - Rate-limit no código: em função serverless a memória não é compartilhada entre instâncias; o limite fica no firewall da hospedagem e no limite de gasto do provedor (D15).
  - O frontend, que vive em outro repositório.

## 3. Contrato

### 3.1 Fábrica (`app/api.py`)
```python
def criar_app(config: Config | None = None, llm: LLMClient | None = None,
              caminho_banco: Path | None = None, pasta_logs: Path | None = None) -> FastAPI: ...
    # config: carregar_config(); llm: criar_cliente(...) uma vez por processo
    # caminho_banco: preparar_banco(); pasta_logs: PASTA_TEMPORARIA/"logs" se VERCEL, senão PASTA_LOGS

def preparar_banco(caminho: Path = CAMINHO_BANCO) -> Path: ...
    # devolve caminho se existir; senão cria (uma vez) PASTA_TEMPORARIA/"emporio.db" a partir dos CSVs
```
`PASTA_TEMPORARIA = Path(tempfile.gettempdir()) / "emporio-da-musica"`: na Vercel só `/tmp` aceita escrita e o banco gerado não vai para o git. O agente é criado **por requisição**, com conexão própria fechada ao fim: a data e o expediente do system prompt ficam sempre atuais e a conexão SQLite não cruza threads.

### 3.2 Rotas
```text
GET  /health  → 200 {"status": "ok", "modelo": "<LLM_MODEL>"}
POST /chat    → 200 RespostaChat | 401 (token) | 422 (validação)
```

```python
class ItemHistorico(BaseModel):
    role: Literal["user", "assistant"]
    content: str                        # até 4000 caracteres

class PedidoChat(BaseModel):
    mensagem: str                       # mínimo 1 caractere; o limite de tamanho é do agente (MAX_MESSAGE_CHARS)
    historico: list[ItemHistorico] = [] # até 40 itens
    conversa_id: str | None = None      # ^[A-Za-z0-9_-]{1,64}$; ausente → "api-" + 8 hex

class RespostaChat(BaseModel):
    resposta: str
    ferramentas: list[str]              # Resposta.tools_usadas
    status: str                         # Resposta.status
    conversa_id: str
    historico: list[ItemHistorico]      # Resposta.para_historico: o cliente acrescenta ao seu histórico
    uso: UsoChat                        # input_tokens, output_tokens, cached_tokens, custo_usd
```
Falha do provedor não vira erro HTTP: o agente já devolve `status="erro_llm"` com a mensagem amigável, e o site a mostra como qualquer resposta.

### 3.3 Variáveis novas
| Variável | Padrão | Uso |
| --- | --- | --- |
| `API_TOKEN` | vazio | se definido, `POST /chat` exige `Authorization: Bearer <token>` (comparação em tempo constante) |
| `CORS_ORIGINS` | vazio | origens separadas por vírgula; vazio = sem CORS (o site chama pelo próprio servidor) |
| `VERCEL` | definida pela Vercel | banco e logs em `PASTA_TEMPORARIA` |

## 4. Arquivos
- **Criar:** `app/api.py`, `api/index.py`, `.vercelignore`
- **Alterar:** `pyproject.toml`, `.env.example`, `README.md`, `docs/ARCHITECTURE.md`
- **Testes:** `tests/test_api.py`

## 5. Testes (escrever ANTES do código)
Usam `TestClient` do FastAPI, `FakeLLM` e o banco temporário da fixture `banco`.

- [ ] Caso feliz: `GET /health` devolve status e modelo.
- [ ] Caso feliz: `POST /chat` executa uma ferramenta, devolve resposta, ferramentas, status, `conversa_id` informado, histórico do turno e tokens; o log grava o `conversa_id`.
- [ ] Memória: o histórico enviado chega ao LLM antes da mensagem nova; sem `conversa_id`, a API gera um com prefixo `api-`.
- [ ] Entrada inválida → 422 sem chamar o LLM: mensagem vazia, papel `tool` no histórico, `conversa_id` com barras, histórico com 41 itens.
- [ ] Token: com `API_TOKEN`, sem cabeçalho ou com token errado → 401; com o certo → 200.
- [ ] Banco: `preparar_banco` usa o existente e, sem ele, cria a cópia em `PASTA_TEMPORARIA`.
- **Fixtures/mocks:** `banco` do `conftest.py`, `FakeLLM`, `monkeypatch` para `API_TOKEN` e `PASTA_TEMPORARIA`.

## 6. Plano
1. Escrever `tests/test_api.py` e confirmar que falha → commit `test(api): ...`
2. Implementar `app/api.py`, `api/index.py`, `.vercelignore`, dependências, `.env.example` e README → commit `feat(api): ...`

## 7. Critérios de aceite
- [ ] [AC-01] `uvicorn api.index:app` sobe; `GET /health` → 200 e `/docs` mostra as rotas.
- [ ] [AC-02] Uma conversa de vários turnos pelo `/chat`, reenviando o `historico` devolvido, mantém o contexto.
- [ ] [AC-03] Com `API_TOKEN` definido, `/chat` sem o token → 401.
- [ ] [AC-04] Na Vercel, sem `data/emporio.db` no deploy, o banco é criado em `/tmp` e os logs vão para `/tmp`.
- [ ] [AC-TESTES] `pytest` verde
- [ ] [AC-LINT] `ruff check .` verde
- **Verificação manual:** deploy na Vercel → `/health` 200 e conversa de 4 turnos pelo `/chat` com histórico.

## 8. Riscos e pontos em aberto
- Sem `vercel.json`: o preset Python da Vercel encontra `api/index.py` sozinho. Um rewrite para `/api/index` faz o FastAPI receber esse caminho em toda requisição e responder 404.
- Logs e protocolos de encaminhamento em `/tmp` somem quando a instância reinicia, e instâncias diferentes podem repetir a sequência do protocolo. Aceitável no protótipo; um sistema real usaria fila ou banco externo.
- Endpoint público gasta a chave do LLM: usar `API_TOKEN`, limite de gasto no provedor e regra de rate-limit no firewall da Vercel (D15).
