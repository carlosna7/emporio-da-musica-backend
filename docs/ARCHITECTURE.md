# Arquitetura — contexto técnico para agentes de código

> Este arquivo diz **como** o sistema é montado: contratos, esquemas e convenções.
> O **porquê** de cada escolha está em [DECISIONS.md](DECISIONS.md), escrito pelo autor para os avaliadores.
> Se uma spec contradisser este arquivo, pare e pergunte.

## 1. Visão geral

```
usuário ─▶ CLI (app/cli.py) ─▶ Agente.responder(historico, mensagem)
                                   │  loop ReAct (máx. MAX_TOOL_ITERATIONS)
                                   ├─▶ LLMClient.chat(...)  ── adaptador: openai | anthropic | gemini | fake
                                   └─▶ tools ──▶ SQLite (somente leitura) / data/politicas.md
                                   └─▶ logs/llm_calls.jsonl, logs/handoffs.jsonl
```

- O **Agente não guarda estado**: recebe o histórico e devolve a resposta. Quem guarda o histórico é a interface (a CLI, numa lista em memória).
- O banco é **somente leitura** em tempo de execução. Só a ingestão escreve nele.
- Nenhum módulo fora de `app/llm/providers/` importa SDK de provedor.

## 2. Layout

```
emporio-da-musica-backend/   # raiz do repositório
  AGENTS.md  CLAUDE.md  README.md
  docs/                     # DECISIONS, ARCHITECTURE, prds/, specs/
  pyproject.toml            # deps: openai, python-dotenv; extras [anthropic], [gemini]; dev: pytest, ruff
  .env.example
  data/raw/                 # CSVs + políticas_da_loja.pdf (cópias)
  data/politicas.md         # manual convertido e revisado
  app/
    config.py               # lê .env
    ingest.py               # CSV → SQLite (python -m app.ingest)
    db.py                   # conexão somente leitura + normalizar()
    precos.py               # regras de preço (promo, PIX)
    politicas.py            # carrega politicas.md e mapeia tópicos
    tools.py                # funções das tools + ToolSpec de cada uma
    prompts.py              # system prompt (persona Emilio)
    agent.py                # loop ReAct
    uso.py                  # registro de chamadas e custo estimado
    cli.py
    llm/
      base.py               # tipos neutros + Protocol LLMClient
      precos_modelos.py     # tabela USD por 1M tokens, por modelo
      providers/openai.py  anthropic.py  gemini.py  fake.py
  evals/casos.json  evals/run.py  evals/relatorio.md
  scripts/gerar_exemplos.py
  logs/                     # fora do git
  tests/
  examples/                 # conversas de exemplo (entregável do desafio)
```

## 3. Configuração (`.env`)

| Variável | Padrão | Uso |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | `openai` \| `anthropic` \| `gemini` |
| `LLM_MODEL` | `gpt-5.4-mini` | nome do modelo do provedor |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | — | só a do provedor ativo é obrigatória |
| `AGENT_TODAY` | data real | fixa "hoje" (testes, avaliação, exemplos) |
| `MAX_TOOL_ITERATIONS` | `5` | limite do loop ReAct |
| `HISTORY_WINDOW` | `20` | mensagens de histórico enviadas ao modelo |
| `MAX_MESSAGE_CHARS` | `1000` | mensagens maiores são recusadas |

## 4. Camada de LLM (`app/llm/base.py`)

Tipos neutros, sem nada específico de provedor:

```python
@dataclass
class ToolSpec:      name: str; description: str; parameters: dict   # JSON Schema
@dataclass
class ToolCall:      id: str; name: str; arguments: dict
@dataclass
class Message:       role: Literal["user", "assistant", "tool"]; content: str
                     tool_calls: list[ToolCall] = field(default_factory=list)
                     tool_call_id: str | None = None; raw: Any = None
@dataclass
class Usage:         input_tokens: int; output_tokens: int; cached_tokens: int = 0
@dataclass
class LLMResponse:   text: str | None; tool_calls: list[ToolCall]; usage: Usage | None
                     provider: str; model: str; raw: Any = None

class LLMClient(Protocol):
    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse: ...

def criar_cliente(provider: str, model: str) -> LLMClient: ...   # fábrica lida do .env
```

- `raw` é opaco e preserva o conteúdo original do provedor quando necessário; fica fora da comparação das mensagens.
- Cada adaptador converte `Message`/`ToolSpec` para o formato do SDK e converte a resposta de volta. Importa o SDK **dentro** do módulo (extras opcionais).
- `FakeLLM(roteiro: list[LLMResponse])` devolve respostas pré-definidas e registra as chamadas recebidas. É usado em todos os testes unitários.

## 5. Agente (`app/agent.py`)

```python
@dataclass
class Resposta:  texto: str; tools_usadas: list[str]; usage: Usage; iteracoes: int

class Agente:
    def __init__(self, llm: LLMClient, tools: dict[str, Callable], specs: list[ToolSpec], system: str): ...
    def responder(self, historico: list[Message], mensagem: str, conversa_id: str) -> Resposta: ...
```

Loop: envia `system + histórico[-HISTORY_WINDOW:] + mensagem` → se houver `tool_calls`, executa cada uma, anexa a resposta do assistente com `raw=resp.raw`, anexa os resultados como `role="tool"` e repete → se vier texto, retorna. Se passar de `MAX_TOOL_ITERATIONS`, devolve uma mensagem de fallback oferecendo atendente. Erro dentro de uma tool vira resultado `{"erro": "..."}` para o modelo, e o loop não quebra. Cada chamada ao LLM é registrada (§9).

## 6. Tools (`app/tools.py`)

Todas devolvem `dict`/`list` serializável em JSON. Argumentos inválidos → `{"erro": "..."}`.

| Tool | Assinatura | Retorno (resumo) |
| --- | --- | --- |
| `buscar_produtos` | `(termo: str = None, categoria: str = None, preco_min: float = None, preco_max: float = None, apenas_disponiveis: bool = True, em_promocao: bool = False)` | até 10 × `{id, nome, categoria, preco, preco_promocional, desconto_percent, preco_pix, estoque, status, disponivel}` |
| `detalhes_produto` | `(product_id: int)` | campos acima + `descricao`, `specs` (dict) |
| `consultar_pedido` | `(order_id: int, email_ou_telefone: str)` | `{pedido, status, data_pedido, total, pagamento, codigo_rastreio, previsao_entrega, itens: [{nome, quantidade}], observacao}` ou `{erro}` genérico |
| `consultar_politica` | `(topico: Literal[...])` | `{topico, texto}` |
| `encaminhar_atendente` | `(motivo: Literal["reclamacao", "defeito_avaria", "dados_pessoais", "nao_resolvido", "pedido_do_cliente"], resumo: str, contato: str = None)` | `{protocolo, prazo_retorno: "24 horas úteis", canal_whatsapp}` |

Regras:
- **Busca:** `termo` é normalizado (minúsculas, sem acento) e dividido em palavras; todas precisam aparecer em `nome_normalizado`. `categoria` aceita o nome da tabela `categories`.
- **Disponível** = `status == "active"` e `estoque > 0`.
- **Preço** (`app/precos.py`): só promoções com `is_active = 1`; se houver mais de uma, vale a de maior desconto; `preco_pix = preco × 0,95` **apenas** quando não há promoção (senão `null`). Arredondar para 2 casas.
- **Pedido:** e-mail comparado sem diferenciar maiúsculas; telefone comparado só pelos dígitos. Pedido inexistente e dado que não confere devolvem **a mesma** mensagem de erro.
- **Encaminhamento:** grava uma linha em `logs/handoffs.jsonl` com `{protocolo, ts, conversa_id, motivo, resumo, contato}`. `contato` só quando o cliente oferecer. Protocolo: `EM-AAAAMMDD-XXXX`.

### Tópicos de política
`politicas.md` tem uma seção `##` por tópico; `app/politicas.py` faz o mapeamento:

| Tópico | Seção do manual |
| --- | --- |
| `sobre_a_loja` | §1 (sobre, missão, endereço, contatos) |
| `horarios` | §2 |
| `pagamentos` | §3 |
| `trocas_devolucoes` | §4 |
| `frete_entregas` | §5 |
| `promocoes` | §6 |
| `garantia` | §8 |
| `privacidade` | §9 |

§7 (diretrizes de atendimento) e §10 vão para o **system prompt**, não para a tool.

## 7. Banco (SQLite, gerado por `ingest.py`)

Tabelas espelham os CSVs: `categories`, `products`, `customers`, `orders`, `order_items`, `promotions`.
Arquivo: `data/emporio.db` (fora do git), recriado do zero por `python -m app.ingest`. Em tempo de execução é aberto com `mode=ro`. Schema completo: [SPEC-0001 §3](specs/SPEC-0001-ingestao-dados.md#3-contrato).
Extras da ingestão: `products.nome_normalizado`; `products.specs` como texto JSON validado; preços `REAL`; estoque `INTEGER`; datas ISO `TEXT`; vazio → `NULL`.
Inconsistências conhecidas e o tratamento de cada uma: [DECISIONS.md — Tratamento dos dados](DECISIONS.md#d13--tratamento-dos-dados-e-suposições).

## 8. System prompt (`app/prompts.py`)
Montado a partir do manual §7 e §10. Contém: persona **Emilio** (informal, profissional, "amigo que entende de música"); data de hoje; horário de funcionamento (para avisar fora do expediente); **contatos oficiais da D13** (endereço, telefone/WhatsApp (67) 3341-4444, `contato@emporiodamusica.com.br`) com a instrução de usá-los mesmo que o manual traga outro número ou e-mail; regras:
1. Nunca informar preço, estoque, prazo ou status sem tool.
2. Políticas → `consultar_politica`; dados → tools de produto/pedido.
3. Só instrumentos: acessórios são redirecionados com educação; assuntos fora da loja são recusados com gentileza.
4. Promoção: mostrar preço original, preço promocional e % de desconto.
5. Encaminhamento (ver DECISIONS): tentar entender e resolver primeiro; reclamação, defeito/avaria e pedido de exclusão de dados → encaminhar; se o cliente pedir atendente **pela segunda vez**, encaminhar sem insistir.
6. Pedir número do pedido + e-mail ou telefone antes de consultar pedido.

## 9. Registro de uso (`app/uso.py`)
Uma linha por chamada ao LLM em `logs/llm_calls.jsonl`:
`{ts, conversa_id, turno, provider, model, input_tokens, output_tokens, cached_tokens, latencia_ms, tools_chamadas, custo_usd, status}`.
`custo_usd` vem de `precos_modelos.py`; modelo fora da tabela → `null` (nunca inventar preço). Tokens sempre do `usage` da API.

## 10. Avaliação (`evals/`)
`casos.json`: lista de `{id, categoria, turnos: [str], espera: {tools: [str], contem: [str], nao_contem: [str]}}`.
`python -m evals.run [--sem-memoria]` roda os casos com o LLM real e `AGENT_TODAY` fixo, e grava `evals/relatorio.md` com: aprovados/reprovados por categoria, tokens, custo e latência média. `--sem-memoria` passa histórico vazio a cada turno (ablação: mede quanto a memória da conversa contribui nos casos multi-turno).

## 11. Testes
- `pytest` em `tests/`, um arquivo por módulo (`test_ingest.py`, `test_tools.py`…).
- Banco de teste: ingestão real dos CSVs num `tmp_path` (são pequenos), via fixture em `conftest.py`.
- LLM: sempre `FakeLLM`. Adaptadores testados convertendo objetos de resposta falsos do SDK (sem rede).
- Testes com rede: só em `evals/`, nunca no `pytest`.
