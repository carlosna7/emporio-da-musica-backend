# SPEC-0003 — Camada de LLM multi-provedor + FakeLLM

- **Status:** aprovada
- **PRD:** [PRD-0001](../prds/PRD-0001-agente-atendimento.md)
- **Depende de:** —

## 1. Objetivo
Entregar a interface única `LLMClient` com os tipos neutros, uma fábrica que escolhe o provedor pelo `.env`, os adaptadores OpenAI, Anthropic e Gemini, o `FakeLLM` usado em todos os testes unitários e a tabela de preços por modelo com `custo_estimado`. É a base do loop ReAct via function calling (D03) e da troca de provedor sem reescrever a aplicação (D05).
Atende `PRD-0001/R9` (tokens e custo de cada chamada; o registro em si fica na SPEC-0004) e prepara `R2`/`R3`/`R4` (o agente só consulta dados e políticas por tool calls que passam por esta camada).

## 2. Escopo
- **Dentro:**
  - `app/llm/base.py`: tipos neutros da [ARCHITECTURE §4](../ARCHITECTURE.md#4-camada-de-llm-appllmbasepy), `LLMError`, `Protocol LLMClient` e `criar_cliente`.
  - `app/llm/providers/openai.py`, `anthropic.py`, `gemini.py`: cada um com duas funções **puras** de conversão (ida e volta) e uma classe com a chamada de rede numa linha.
  - `app/llm/providers/fake.py`: `FakeLLM` e dois atalhos para montar respostas.
  - `app/llm/precos_modelos.py`: tabela USD por 1M tokens e `custo_estimado`.
  - Mínimos de versão dos SDKs no `pyproject.toml` (ver §4).
- **Fora:**
  - Loop do agente, janela de histórico, latência e o registro em `logs/llm_calls.jsonl` (SPEC-0004, ARCHITECTURE §5 e §9).
  - Tools e seus `ToolSpec` (SPEC-0002).
  - Leitura do `.env` com `python-dotenv` (`app/config.py`, fora desta spec). A fábrica só lê `os.environ`.
  - Streaming, chamadas assíncronas, prompt caching explícito, retries próprios (fica o retry padrão de cada SDK: 2 tentativas na OpenAI e na Anthropic).
  - Qualquer chamada real à API nos testes (ARCHITECTURE §11).

## 3. Contrato

### 3.1 `app/llm/base.py`
Tipos da ARCHITECTURE §4, **mais um campo opcional `raw`** em `Message` e `LLMResponse` (proposta, ver §8-1):

```python
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

class LLMError(Exception):
    """Falha do provedor, resposta inutilizável, provedor desconhecido, chave ausente ou extra não instalado."""

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict          # JSON Schema de um objeto ({"type": "object", "properties": {...}})

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict           # sempre dict, já decodificado

@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str              # role="tool": resultado da tool serializado em JSON (str)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    raw: Any = field(default=None, repr=False, compare=False)   # opaco, ver abaixo

@dataclass
class Usage:
    input_tokens: int         # TOTAL de entrada, incluindo os tokens lidos do cache
    output_tokens: int        # total de saída, incluindo raciocínio/"thinking"
    cached_tokens: int = 0    # parte de input_tokens servida do cache

@dataclass
class LLMResponse:
    text: str | None          # None só quando há tool_calls
    tool_calls: list[ToolCall]
    usage: Usage | None
    provider: str             # "openai" | "anthropic" | "gemini" | "fake"
    model: str                # o nome CONFIGURADO (LLM_MODEL), não o snapshot devolvido pela API
    raw: Any = field(default=None, repr=False, compare=False)

class LLMClient(Protocol):
    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse: ...

def criar_cliente(provider: str, model: str, api_key: str | None = None) -> LLMClient: ...
```

Regras:
- **`raw`** guarda o conteúdo original da resposta do assistente no formato do provedor. Quem chama nunca lê esse campo, só o devolve: ao anexar a resposta ao histórico, o agente (SPEC-0004) cria `Message(role="assistant", content=resp.text or "", tool_calls=resp.tool_calls, raw=resp.raw)`. Ao converter uma mensagem `assistant` com `raw` preenchido, o adaptador usa `raw` como está, em vez de remontar a mensagem. Motivo: o Gemini 3 exige que a `thought_signature` volte dentro da parte original da chamada de função (sem ela, a API responde 400), e os modelos Claude atuais pedem os blocos `thinking` de volta, sem alteração, durante o uso de tools. `compare=False` mantém a igualdade das mensagens nos testes.
- **Convenção de `Usage`** (vale para os três adaptadores e para `custo_estimado`): `input_tokens` inclui os tokens de cache; `cached_tokens` é um subconjunto deles. O custo cobra `input_tokens - cached_tokens` pelo preço normal e `cached_tokens` pelo preço de cache.
- **Resposta vazia:** se a conversão da resposta não encontrar nem texto nem tool calls, o adaptador levanta `LLMError("resposta vazia do provedor")`. Assim `text is None` implica `tool_calls != []`.
- **Erros de SDK:** `chat()` captura a exceção base do SDK (`openai.OpenAIError`, `anthropic.AnthropicError`, `google.genai.errors.APIError`) e levanta `LLMError(f"{provider}: {erro}") from erro`.
- **Argumentos de tool como string JSON** (OpenAI): `json.loads`; JSON inválido ou que não seja objeto → `LLMError`.

`criar_cliente`:
```python
_VARIAVEIS_CHAVE = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}
```
1. `provider = provider.strip().lower()`. Fora de `_VARIAVEIS_CHAVE` → `LLMError` com a lista dos provedores válidos.
2. `model` vazio → `LLMError("defina LLM_MODEL")`.
3. `api_key = api_key or os.environ.get(VAR, "").strip()`. Se ficar vazia → `LLMError` com o nome da variável (ex.: `"defina OPENAI_API_KEY no .env"`).
4. Importa o adaptador **dentro** da função, com `if/elif` explícito (`from app.llm.providers.openai import OpenAIClient` etc.). Se der `ImportError`, levanta `LLMError(f"instale o extra: pip install -e '.[{provider}]'")`. O extra só se aplica a anthropic e gemini; o openai é dependência do core.
5. Retorna `XClient(model=model, api_key=api_key)`.

`app.llm.base` e `app.llm.providers.fake` **não** importam nenhum SDK (`openai`, `anthropic`, `google.genai`), nem no topo nem indiretamente.

### 3.2 Adaptadores (`app/llm/providers/*.py`)
Os três têm a mesma forma. O SDK é importado no topo do módulo do provedor, e só a fábrica e os testes importam esses módulos.

```python
# openai.py
def para_openai(system: str, messages: list[Message], tools: list[ToolSpec]) -> dict: ...
def de_openai(resposta, model: str) -> LLMResponse: ...
class OpenAIClient:
    def __init__(self, model: str, api_key: str, temperature: float | None = 0.2, cliente=None): ...
    def chat(self, system, messages, tools) -> LLMResponse: ...

# anthropic.py
MAX_TOKENS = 4096
def para_anthropic(system: str, messages: list[Message], tools: list[ToolSpec]) -> dict: ...
def de_anthropic(resposta, model: str) -> LLMResponse: ...
class AnthropicClient:
    def __init__(self, model: str, api_key: str, cliente=None): ...

# gemini.py
def para_gemini(system: str, messages: list[Message], tools: list[ToolSpec]) -> dict: ...
def de_gemini(resposta, model: str) -> LLMResponse: ...
class GeminiClient:
    def __init__(self, model: str, api_key: str, cliente=None): ...
```

- `para_*` devolve os kwargs da chamada do SDK, **sem** `model` e sem parâmetros de amostragem. `de_*` recebe o objeto de resposta do SDK.
- `cliente=None` → o construtor cria o cliente real do SDK (`openai.OpenAI(api_key=api_key, timeout=60.0)`, `anthropic.Anthropic(api_key=api_key, timeout=60.0)`, `genai.Client(api_key=api_key)`). Nos testes, passa-se um objeto falso (`SimpleNamespace`) no lugar do cliente. Nenhum construtor faz chamada de rede.
- `chat()` = `de_x(self._cliente.<método>(model=self.model, **extras, **para_x(...)), self.model)` dentro de `try/except` da exceção base do SDK.

#### OpenAI: Responses API (`client.responses.create`)
**Por que Responses e não Chat Completions:** a Responses tem o mesmo formato dos outros dois (system separado em `instructions`; chamadas e resultados de tool como itens próprios; `usage.input_tokens`/`output_tokens`). Também é nela que a OpenAI oferece function calling em todos os modelos atuais: no Chat Completions, o GPT-6 Astra e o 6.1 Sol não aceitam tools, e o `gpt-6-luna` só aceita com `reasoning_effort="none"`. Os campos abaixo foram conferidos no SDK `openai` 3.42.1 instalado no `.venv`.

| Aspecto | Formato |
| --- | --- |
| System | `instructions=system` |
| Mensagem `user` | `{"role": "user", "content": content}` |
| Mensagem `assistant` | se `content` não for vazio: `{"role": "assistant", "content": content}`; depois, um item por tool call: `{"type": "function_call", "call_id": tc.id, "name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}`. **Não** enviar o campo `id` (`fc_...`) do item: com `store=False`, a API exige o item de raciocínio que o precedeu. `raw` é ignorado (sempre `None` neste adaptador). |
| Mensagem `tool` | `{"type": "function_call_output", "call_id": m.tool_call_id, "output": m.content}` |
| Tools | `{"type": "function", "name", "description", "parameters", "strict": False}`. O `strict=False` é explícito porque os nossos schemas têm parâmetros opcionais. Lista vazia → omitir a chave `tools`. |
| Extras do `chat()` | `store=False` (a OpenAI não guarda a conversa; o histórico é nosso, ver D09) e `temperature=self.temperature`, só quando não for `None` |
| Resposta: texto | concatenar `part.text` de cada item com `item.type == "message"` e `part.type == "output_text"` em `resposta.output`; string vazia → `None` |
| Resposta: tools | itens com `item.type == "function_call"` → `ToolCall(id=item.call_id, name=item.name, arguments=json.loads(item.arguments or "{}"))` |
| Usage | `Usage(input_tokens=u.input_tokens, output_tokens=u.output_tokens, cached_tokens=u.input_tokens_details.cached_tokens or 0)`; `resposta.usage is None` → `usage=None` |
| Outros itens de `output` (ex.: `reasoning`) | ignorados |

#### Anthropic: Messages API (`client.messages.create`)
Campos conferidos no SDK `anthropic` 2.3.0. Esse SDK não tem mais `temperature`, `top_p` e `top_k`, e a versão da API 2026-10-21 rejeita esses campos com 400 em todos os modelos. Por isso **este adaptador não envia temperatura**.

| Aspecto | Formato |
| --- | --- |
| System | `system=system` (omitir se vazio) |
| Mensagem `user` | `{"role": "user", "content": content}` |
| Mensagem `assistant` com `raw` | `{"role": "assistant", "content": raw}` |
| Mensagem `assistant` sem `raw` | sem tool calls: `{"role": "assistant", "content": content}`; com tool calls: `content` é uma lista com `{"type": "text", "text": content}` (só se `content` não for vazio) e depois `{"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}` para cada chamada |
| Mensagens `tool` | **consecutivas viram uma única** mensagem `{"role": "user", "content": [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}, ...]}` |
| Tools | `{"name", "description", "input_schema": parameters}`; lista vazia → omitir `tools` |
| Extras do `chat()` | `max_tokens=MAX_TOKENS` (obrigatório na API; o raciocínio também conta) |
| Resposta: texto | concatenar `b.text` dos blocos com `b.type == "text"` em `resposta.content`; vazio → `None` |
| Resposta: tools | blocos `b.type == "tool_use"` → `ToolCall(id=b.id, name=b.name, arguments=dict(b.input))` |
| `raw` | `[b.model_dump(exclude_none=True) for b in resposta.content]` (inclui os blocos `thinking` com `signature`) |
| Usage | `cache_read = u.cache_read_input_tokens or 0`, `cache_write = u.cache_creation_input_tokens or 0`; `Usage(input_tokens=u.input_tokens + cache_read + cache_write, output_tokens=u.output_tokens, cached_tokens=cache_read)`. Na Anthropic, `input_tokens` **exclui** o cache, por isso a soma. |

#### Gemini: `google-genai` (`client.models.generate_content`)
Campos conferidos no SDK `google-genai` 2.34.0. Este adaptador também **não envia temperatura**: o Google recomenda manter 1.0 no Gemini 3 e avisa que valores menores podem causar *looping* ou piora no raciocínio.

| Aspecto | Formato (`from google.genai import types`) |
| --- | --- |
| Retorno de `para_gemini` | `{"contents": [...], "config": types.GenerateContentConfig(system_instruction=system or None, tools=[types.Tool(function_declarations=[...])] or None)}` |
| Tools | `types.FunctionDeclaration(name=..., description=..., parameters_json_schema=spec.parameters)`; aceita o JSON Schema direto, sem converter para `types.Schema`. Sem tools → `tools=None`. |
| Mensagem `user` | `types.Content(role="user", parts=[types.Part(text=content)])` |
| Mensagem `assistant` com `raw` | `raw` (é o `types.Content` original, com `thought_signature` nas partes) |
| Mensagem `assistant` sem `raw` | `types.Content(role="model", parts=[types.Part(text=content)] se content não for vazio + [types.Part(function_call=types.FunctionCall(id=_id_real(tc.id), name=tc.name, args=tc.arguments))])` |
| Mensagens `tool` | consecutivas viram **um único** `types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(id=_id_real(m.tool_call_id), name=<nome>, response={"result": _json_ou_texto(m.content)}))...])` |
| Nome no `function_response` | o Gemini exige `name`. A conversão monta um dicionário `id → name` a partir dos `tool_calls` das mensagens `assistant` já percorridas. `tool_call_id` sem chamada correspondente → `LLMError`. |
| Ids | `fc.id` pode vir vazio na Gemini API. Nesse caso a volta gera `f"gemini_{i}_{fc.name}"` (`i` = índice da parte). `_id_real(id)` devolve `None` para ids que começam com `gemini_` (gerados por nós) e o próprio id nos demais casos. |
| `_json_ou_texto(s)` | `json.loads(s)`; se falhar, a própria string |
| Resposta: candidato | `resposta.candidates` vazio ou `candidates[0].content is None` → `LLMError` (ex.: prompt bloqueado) |
| Resposta: texto | concatenar `p.text` das partes de `candidates[0].content.parts` com `p.text` e `not p.thought`; vazio → `None` |
| Resposta: tools | partes com `p.function_call` → `ToolCall(id=fc.id or f"gemini_{i}_{fc.name}", name=fc.name, arguments=dict(fc.args or {}))` |
| `raw` | `candidates[0].content` |
| Usage | `um = resposta.usage_metadata`; `None` → `usage=None`; senão `Usage(input_tokens=um.prompt_token_count or 0, output_tokens=(um.candidates_token_count or 0) + (um.thoughts_token_count or 0), cached_tokens=um.cached_content_token_count or 0)`. O Gemini cobra o raciocínio como saída. |

Não é preciso desligar a "automatic function calling" do SDK: ela só age quando se passam funções Python, e aqui passamos declarações.

### 3.3 `app/llm/providers/fake.py`
```python
class FakeLLM:
    def __init__(self, roteiro: list[LLMResponse]): ...
    chamadas: list[dict]   # {"system": str, "messages": list[Message], "tools": list[ToolSpec]}, uma por chat()
    def chat(self, system, messages, tools) -> LLMResponse: ...

def resposta_texto(texto: str) -> LLMResponse: ...
def resposta_tool(name: str, **arguments) -> LLMResponse: ...
```
- `chat()` grava `{"system": system, "messages": list(messages), "tools": list(tools)}`. A **cópia** da lista guarda o histórico como estava naquela chamada, mesmo que o agente mude a lista depois. Em seguida devolve o próximo item do roteiro, na ordem. Com o roteiro esgotado → `LLMError("FakeLLM: roteiro esgotado")`.
- O roteiro é copiado no construtor (`list(roteiro)`), então a lista original do teste não muda.
- `resposta_texto("oi")` → `LLMResponse(text="oi", tool_calls=[], usage=Usage(10, 5), provider="fake", model="fake")`.
- `resposta_tool("buscar_produtos", termo="violão")` → `LLMResponse(text=None, tool_calls=[ToolCall(id="call_buscar_produtos", name="buscar_produtos", arguments={"termo": "violão"})], usage=Usage(10, 5), provider="fake", model="fake")`. Para duas chamadas na mesma resposta, o teste monta o `LLMResponse` à mão.

### 3.4 `app/llm/precos_modelos.py`
```python
CONSULTADO_EM = "2026-11-02"

@dataclass(frozen=True)
class PrecoModelo:
    entrada: float                  # USD por 1M tokens de entrada
    saida: float                    # USD por 1M tokens de saída
    entrada_cache: float | None = None   # USD por 1M tokens lidos do cache; None → cobra como entrada

PRECOS: dict[str, PrecoModelo] = {
    "gpt-5.4-mini":          PrecoModelo(entrada=0.75, saida=4.50, entrada_cache=0.075),
    "gpt-6-luna":            PrecoModelo(entrada=0.10, saida=0.50, entrada_cache=0.01),
    "claude-haiku-5-5":      PrecoModelo(entrada=0.10, saida=0.50, entrada_cache=0.01),   # prompts ≤ 100k tokens
    "gemini-3.5-flash-lite": PrecoModelo(entrada=0.30, saida=2.50, entrada_cache=0.03),
}

def custo_estimado(model: str, usage: Usage | None) -> float | None: ...
```
- Busca pelo nome **exato**. Modelo fora da tabela ou `usage is None` → `None`. Nunca estimar por prefixo nem por "modelo parecido" (ARCHITECTURE §9).
- Fórmula: `((usage.input_tokens - usage.cached_tokens) * p.entrada + usage.cached_tokens * (p.entrada_cache if p.entrada_cache is not None else p.entrada) + usage.output_tokens * p.saida) / 1_000_000`, arredondada com `round(x, 6)`.
- Fontes (consultadas em 2026-11-02, preços *Standard*): OpenAI `developers.openai.com/api/docs/pricing`; Anthropic `platform.claude.com/docs/en/about-claude/pricing`; Google `aistudio.google.com/docs/pricing` (antigo `ai.google.dev/gemini-api/docs/pricing`). Um comentário no topo do módulo registra as três URLs e a data.

## 4. Arquivos
- **Criar:** `app/llm/base.py`, `app/llm/precos_modelos.py`, `app/llm/providers/__init__.py` (vazio, se ainda não existir), `app/llm/providers/openai.py`, `app/llm/providers/anthropic.py`, `app/llm/providers/gemini.py`, `app/llm/providers/fake.py`.
- **Alterar:** `pyproject.toml`, só os mínimos de versão, para os majors em que esta spec foi conferida: `openai>=3.0`, `anthropic>=2.0`, `google-genai>=2.0`. Nenhuma dependência nova.
- **Testes:** `tests/test_llm_base.py`, `tests/test_llm_fake.py`, `tests/test_llm_openai.py`, `tests/test_llm_anthropic.py`, `tests/test_llm_gemini.py`, `tests/test_precos_modelos.py`.

## 5. Testes (escrever ANTES do código)
Comece no *red*. Nenhum teste acessa a rede: as respostas do SDK são montadas com os **tipos reais do SDK** (construtor ou `model_construct`, que não valida campos obrigatórios), e o cliente do SDK é trocado por um `SimpleNamespace` passado em `cliente=`. `tests/test_llm_anthropic.py` começa com `pytest.importorskip("anthropic")` e `tests/test_llm_gemini.py` com `pytest.importorskip("google.genai")`, **antes** de importar o adaptador.

**Dados comuns** (cada arquivo de adaptador define os seus, iguais a estes):
```python
SYS = "Você é o Emilio."
TOOLS = [ToolSpec("buscar_produtos", "Busca produtos",
                  {"type": "object", "properties": {"termo": {"type": "string"}}})]
C1 = ToolCall("c1", "buscar_produtos", {"termo": "violão", "preco_max": 1000})
C2 = ToolCall("c2", "consultar_politica", {"topico": "pagamentos"})
HIST_1 = [Message("user", "Tem violão até 1000?"),
          Message("assistant", "", tool_calls=[C1]),
          Message("tool", '{"itens": []}', tool_call_id="c1")]
HIST_2 = [Message("user", "Violão e formas de pagamento?"),
          Message("assistant", "Vou verificar.", tool_calls=[C1, C2]),
          Message("tool", '{"itens": []}', tool_call_id="c1"),
          Message("tool", '{"topico": "pagamentos", "texto": "PIX"}', tool_call_id="c2")]
```

### `tests/test_llm_base.py`
- [ ] `Message("user", "oi")` tem `tool_calls == []`, `tool_call_id is None` e `raw is None`; duas instâncias não compartilham a mesma lista de `tool_calls`.
- [ ] `Message("assistant", "x", raw=[1]) == Message("assistant", "x")` (o `raw` fica fora da comparação); o mesmo para `LLMResponse`.
- [ ] `Usage(10, 5).cached_tokens == 0`.
- [ ] Isolamento dos SDKs: `subprocess.run([sys.executable, "-c", "import sys, app.llm.base, app.llm.providers.fake; assert not {'openai', 'anthropic', 'google.genai'} & set(sys.modules)"], cwd=<raiz do repo>)` termina com código 0.
- [ ] Fábrica, provedor inválido: `criar_cliente("mistral", "x", api_key="k")` → `LLMError` cuja mensagem contém `"openai"`, `"anthropic"` e `"gemini"`.
- [ ] Fábrica, chave ausente: com `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`, `criar_cliente("openai", "gpt-5.4-mini")` → `LLMError` contendo `"OPENAI_API_KEY"`. Com `monkeypatch.setenv("OPENAI_API_KEY", "  ")` (só espaços), o resultado é o mesmo.
- [ ] Fábrica, modelo vazio: `criar_cliente("openai", "", api_key="k")` → `LLMError`.
- [ ] Fábrica, caso feliz: com `monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")`, `criar_cliente(" OpenAI ", "gpt-5.4-mini")` devolve `OpenAIClient` com `.model == "gpt-5.4-mini"` (o construtor não faz rede).
- [ ] Fábrica, extra não instalado: `monkeypatch.setitem(sys.modules, "anthropic", None)` e `monkeypatch.delitem(sys.modules, "app.llm.providers.anthropic", raising=False)`; `criar_cliente("anthropic", "claude-haiku-5-5", api_key="k")` → `LLMError` contendo `"pip install"`.

### `tests/test_llm_fake.py`
- [ ] Devolve o roteiro na ordem: com `FakeLLM([resposta_tool("buscar_produtos", termo="violão"), resposta_texto("Achei!")])`, a 1ª chamada tem `tool_calls[0].name == "buscar_produtos"` e `arguments == {"termo": "violão"}`, e a 2ª tem `text == "Achei!"`.
- [ ] Roteiro esgotado: a 3ª chamada → `LLMError`.
- [ ] Registra as chamadas: depois de `fake.chat(SYS, msgs, TOOLS)`, `fake.chamadas[0] == {"system": SYS, "messages": msgs, "tools": TOOLS}`.
- [ ] Guarda uma cópia: um `append` em `msgs` depois da chamada não altera `fake.chamadas[0]["messages"]`.
- [ ] Não muda a lista de roteiro recebida no construtor.
- [ ] `resposta_texto` e `resposta_tool` produzem exatamente os objetos da §3.3 (`provider == "fake"`, `usage == Usage(10, 5)`, `id == "call_buscar_produtos"`).

### `tests/test_llm_openai.py`
Montagem da resposta (tipos de `openai.types.responses`):
```python
def resposta(*itens, usage=None):
    return Response.model_construct(output=list(itens), usage=usage, model="gpt-5.4-mini-2026-03-17")
def texto(t):
    return ResponseOutputMessage(id="msg_1", role="assistant", status="completed", type="message",
                                 content=[ResponseOutputText(annotations=[], text=t, type="output_text")])
def chamada(call_id, name, args_json):
    return ResponseFunctionToolCall(call_id=call_id, name=name, arguments=args_json, type="function_call")
USO = ResponseUsage(input_tokens=100, output_tokens=20, total_tokens=120,
                    input_tokens_details=InputTokensDetails(cached_tokens=40, cache_write_tokens=0),
                    output_tokens_details=OutputTokensDetails(reasoning_tokens=0))
```
Ida (`para_openai`):
- [ ] Só usuário, sem tools: `para_openai(SYS, [Message("user", "oi")], [])` → `{"instructions": SYS, "input": [{"role": "user", "content": "oi"}]}` (sem a chave `tools`).
- [ ] Tools: `para_openai(SYS, [...], TOOLS)["tools"] == [{"type": "function", "name": "buscar_produtos", "description": "Busca produtos", "parameters": TOOLS[0].parameters, "strict": False}]`.
- [ ] Histórico com 1 tool call e resultado (`HIST_1`): `input` tem 3 itens: o usuário; `{"type": "function_call", "call_id": "c1", "name": "buscar_produtos", "arguments": ...}` com `json.loads(arguments) == C1.arguments` e **sem** chave `id`; e `{"type": "function_call_output", "call_id": "c1", "output": '{"itens": []}'}`. Não há item de mensagem para o `assistant` de conteúdo vazio.
- [ ] Histórico com 2 tool calls (`HIST_2`): os itens ficam na ordem usuário → `{"role": "assistant", "content": "Vou verificar."}` → `function_call` c1 → `function_call` c2 → `function_call_output` c1 → `function_call_output` c2.
- [ ] `ensure_ascii=False`: o `arguments` de C1 contém o texto literal `"violão"`.

Volta (`de_openai`):
- [ ] Só texto: `de_openai(resposta(texto("Olá!"), usage=USO), "gpt-5.4-mini")` → `text == "Olá!"`, `tool_calls == []`, `provider == "openai"`, `model == "gpt-5.4-mini"` (o configurado, não o snapshot).
- [ ] 1 tool call: `resposta(chamada("call_1", "buscar_produtos", '{"termo": "violão"}'))` → `text is None`, `tool_calls == [ToolCall("call_1", "buscar_produtos", {"termo": "violão"})]`.
- [ ] 2 tool calls + texto: `resposta(texto("Vou ver."), chamada("call_1", ...), chamada("call_2", "consultar_politica", '{"topico": "pagamentos"}'))` → `text == "Vou ver."` e 2 `ToolCall` na ordem.
- [ ] `arguments=""` → `{}`; `arguments="{quebrado"` → `LLMError`.
- [ ] Usage: com `USO` → `Usage(input_tokens=100, output_tokens=20, cached_tokens=40)`; com `usage=None` → `usage is None`.
- [ ] Resposta vazia (`resposta()` sem itens) → `LLMError`.

`chat()` com cliente falso:
- [ ] `capturado = {}`; `falso = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: capturado.update(kw) or resposta(texto("ok"), usage=USO)))`; `OpenAIClient("gpt-5.4-mini", "k", cliente=falso).chat(SYS, [Message("user", "oi")], TOOLS)` devolve `text == "ok"`, e `capturado` tem `model == "gpt-5.4-mini"`, `store is False`, `temperature == 0.2`, `instructions == SYS` e `tools`.
- [ ] Com `temperature=None`, a chave `temperature` não aparece em `capturado`.
- [ ] Se o `create` falso levantar `openai.OpenAIError("caiu")`, `chat()` levanta `LLMError` e a mensagem contém `"openai"`.

### `tests/test_llm_anthropic.py`
Montagem (tipos de `anthropic.types`):
```python
def resposta(*blocos, usage=None):
    return Message.model_construct(id="msg", type="message", role="assistant", model="claude-haiku-5-5",
                                   stop_reason="end_turn", content=list(blocos),
                                   usage=usage or Usage(input_tokens=50, output_tokens=10))
```
Ida (`para_anthropic`):
- [ ] Só usuário: `para_anthropic(SYS, [Message("user", "oi")], [])` → `{"system": SYS, "messages": [{"role": "user", "content": "oi"}]}` (sem `tools`).
- [ ] Tools: `["tools"] == [{"name": "buscar_produtos", "description": "Busca produtos", "input_schema": TOOLS[0].parameters}]`.
- [ ] `HIST_1` → `messages == [{"role": "user", "content": "Tem violão até 1000?"}, {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "buscar_produtos", "input": C1.arguments}]}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": '{"itens": []}'}]}]` (sem bloco de texto vazio).
- [ ] `HIST_2` → a mensagem `assistant` tem `[{"type": "text", "text": "Vou verificar."}, tool_use c1, tool_use c2]`, e os **dois** `tool_result` vêm numa **única** mensagem `user` (total de 3 mensagens).
- [ ] `assistant` com `raw`: `Message("assistant", "", tool_calls=[C1], raw=[{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "tool_use", "id": "c1", "name": "buscar_produtos", "input": C1.arguments}])` é convertida para `{"role": "assistant", "content": <esse raw, idêntico>}`.
- [ ] `assistant` só com texto: `Message("assistant", "Olá")` → `{"role": "assistant", "content": "Olá"}`.

Volta (`de_anthropic`):
- [ ] Só texto: `resposta(TextBlock(type="text", text="Olá!"))` → `text == "Olá!"`, `tool_calls == []`, `provider == "anthropic"`, `model == "claude-haiku-5-5"`.
- [ ] 1 tool call: `resposta(ToolUseBlock(type="tool_use", id="toolu_1", name="buscar_produtos", input={"termo": "violão"}))` → `text is None`, `tool_calls == [ToolCall("toolu_1", "buscar_produtos", {"termo": "violão"})]`.
- [ ] 2 tool calls + texto + thinking: `resposta(ThinkingBlock(type="thinking", thinking="", signature="sig"), TextBlock(type="text", text="Vou ver."), ToolUseBlock(... "toolu_1" ...), ToolUseBlock(... "toolu_2", name="consultar_politica", input={"topico": "pagamentos"}))` → `text == "Vou ver."`, 2 `ToolCall` na ordem, e `raw[0] == {"type": "thinking", "thinking": "", "signature": "sig"}` com `len(raw) == 4`.
- [ ] Usage: `Usage(input_tokens=50, output_tokens=10, cache_read_input_tokens=30, cache_creation_input_tokens=None)` (tipo do SDK) → `Usage(80, 10, 30)` neutro; sem campos de cache → `Usage(50, 10, 0)`.
- [ ] Resposta sem blocos → `LLMError`.

`chat()` com cliente falso (`SimpleNamespace(messages=SimpleNamespace(create=...))`):
- [ ] Os kwargs capturados têm `model`, `max_tokens == MAX_TOKENS`, `system == SYS`, e **não** têm `temperature`.
- [ ] `anthropic.AnthropicError("caiu")` → `LLMError`.

### `tests/test_llm_gemini.py`
Montagem (`from google.genai import types`):
```python
def resposta(*partes, usage=None):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(partes)))],
        usage_metadata=usage)
def fc(name, args, id=None, assinatura=None):
    return types.Part(function_call=types.FunctionCall(id=id, name=name, args=args), thought_signature=assinatura)
```
Ida (`para_gemini`), comparando objetos `types.*` com `==` (o pydantic compara campo a campo):
- [ ] Só usuário, sem tools: `contents == [types.Content(role="user", parts=[types.Part(text="oi")])]`, `config.system_instruction == SYS`, `config.tools is None`, `config.temperature is None`.
- [ ] Tools: `config.tools[0].function_declarations[0]` tem `name == "buscar_produtos"` e `parameters_json_schema == TOOLS[0].parameters`.
- [ ] `HIST_1` → 3 `Content`: user; `model` com `Part(function_call=FunctionCall(id="c1", name="buscar_produtos", args=C1.arguments))`; `user` com `Part(function_response=FunctionResponse(id="c1", name="buscar_produtos", response={"result": {"itens": []}}))`.
- [ ] `HIST_2` → o `Content` `model` tem 3 partes (texto + 2 function_call), e os dois `function_response` (nomes `buscar_produtos` e `consultar_politica`, resolvidos pelo id) vêm num **único** `Content` `user`.
- [ ] Ids gerados: com `ToolCall("gemini_0_buscar_produtos", ...)` e o `tool_call_id` correspondente, `FunctionCall.id is None` e `FunctionResponse.id is None`.
- [ ] `assistant` com `raw`: o `types.Content` passado em `raw` aparece **o mesmo objeto** (`is`) em `contents`, com a `thought_signature` preservada.
- [ ] Resultado que não é JSON (`Message("tool", "texto solto", tool_call_id="c1")`) → `response == {"result": "texto solto"}`.
- [ ] `tool_call_id` sem chamada anterior → `LLMError`.

Volta (`de_gemini`):
- [ ] Só texto: `resposta(types.Part(text="Olá!"))` → `text == "Olá!"`, `tool_calls == []`, `provider == "gemini"`.
- [ ] Parte de pensamento é ignorada: `resposta(types.Part(text="pensando", thought=True), types.Part(text="Olá!"))` → `text == "Olá!"`.
- [ ] 1 tool call sem id: `resposta(fc("buscar_produtos", {"termo": "violão"}, assinatura=b"sig"))` → `tool_calls == [ToolCall("gemini_0_buscar_produtos", "buscar_produtos", {"termo": "violão"})]`, `text is None`, e `raw.parts[0].thought_signature == b"sig"`.
- [ ] 2 tool calls com id: `resposta(fc("buscar_produtos", {...}, id="a"), fc("consultar_politica", {"topico": "pagamentos"}, id="b"))` → ids `"a"` e `"b"`, na ordem.
- [ ] Ida e volta: o `raw` de uma resposta com tool call, colocado numa `Message("assistant", "", tool_calls=..., raw=...)` e reconvertido por `para_gemini`, mantém `thought_signature == b"sig"`.
- [ ] Usage: `types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=10, thoughts_token_count=5, cached_content_token_count=60)` → `Usage(100, 15, 60)`; `usage_metadata=None` → `usage is None`.
- [ ] Sem candidatos (`types.GenerateContentResponse(candidates=[])`) → `LLMError`.

`chat()` com cliente falso (`SimpleNamespace(models=SimpleNamespace(generate_content=...))`):
- [ ] Os kwargs capturados têm `model`, `contents` e `config`.
- [ ] `google.genai.errors.APIError(500, {"error": {"message": "caiu"}})` → `LLMError`.

### `tests/test_precos_modelos.py`
- [ ] Com cache: `custo_estimado("gpt-5.4-mini", Usage(10_000, 1_000, 4_000)) == pytest.approx(0.0093)` (6.000 × 0,75 + 4.000 × 0,075 + 1.000 × 4,50 = 9.300 por 1M).
- [ ] Sem cache: `custo_estimado("gpt-5.4-mini", Usage(1_000_000, 1_000_000)) == pytest.approx(5.25)`.
- [ ] `entrada_cache=None` cobra o cache como entrada: com `monkeypatch.setitem(PRECOS, "x", PrecoModelo(1.0, 2.0))`, `custo_estimado("x", Usage(1_000_000, 0, 500_000)) == pytest.approx(1.0)`.
- [ ] Modelo fora da tabela → `None`, incluindo o snapshot `"gpt-5.4-mini-2026-03-17"` (a busca é exata).
- [ ] `usage=None` → `None`.
- [ ] Os valores confirmados estão na tabela: `PRECOS["gpt-5.4-mini"] == PrecoModelo(0.75, 4.50, 0.075)`.

- **Fixtures/mocks:** `monkeypatch` (variáveis de ambiente, `sys.modules`, `PRECOS`), `SimpleNamespace` como cliente do SDK, tipos reais dos SDKs para as respostas. Não precisa de banco nem de `tmp_path`.

## 6. Plano

**Execução:** houve um único red inicial de coleta, antes da implementação; os testes foram ampliados posteriormente. Os ciclos red separados por fase abaixo não foram executados. Nenhum commit foi criado.
Commits seguindo o ciclo da spec (AGENTS.md, D16). A spec fica "implementada" só no último `feat`.

1. `docs(spec): SPEC-0003 camada de LLM` (esta spec, depois de aprovada).
2. Base + fake: escrever `test_llm_base.py` (menos o caso feliz da fábrica, que depende do adaptador OpenAI) e `test_llm_fake.py`, e confirmar *red* → `test(llm): tipos neutros, fábrica e FakeLLM`. Implementar `base.py` e `fake.py` → `feat(llm): tipos neutros, fábrica e FakeLLM`.
3. OpenAI: `test_llm_openai.py` + caso feliz da fábrica, *red* → `test(llm): adaptador OpenAI (Responses API)`. Implementar `providers/openai.py` → `feat(llm): adaptador OpenAI`.
4. Anthropic: `pip install -e ".[anthropic]"`; `test_llm_anthropic.py` *red* → `test(llm): adaptador Anthropic`. Implementar → `feat(llm): adaptador Anthropic`.
5. Gemini: `pip install -e ".[gemini]"`; `test_llm_gemini.py` *red* → `test(llm): adaptador Gemini`. Implementar → `feat(llm): adaptador Gemini`.
6. Preços: `test_precos_modelos.py` *red* → `test(llm): tabela de preços e custo estimado`. Implementar `precos_modelos.py` e ajustar os mínimos no `pyproject.toml` → `feat(llm): tabela de preços e custo estimado`. Marcar os critérios da §7 e mudar o status para **implementada**.

Antes de cada commit: `pytest` e `ruff check .` verdes, exceto nos commits `test(...)`, em que só os testes novos falham.

## 7. Critérios de aceite
- [ ] [AC-01] Importar `app.llm.base` e `app.llm.providers.fake` não carrega `openai`, `anthropic` nem `google.genai` (teste com `subprocess`).
- [ ] [AC-02] `criar_cliente` levanta `LLMError` com mensagem útil para provedor desconhecido, modelo vazio, chave ausente ou em branco e extra não instalado, e devolve o adaptador certo no caso feliz.
- [ ] [AC-03] `FakeLLM` devolve o roteiro na ordem, guarda uma cópia de cada chamada e falha com `LLMError` quando o roteiro acaba.
- [ ] [AC-04] OpenAI: ida e volta cobrem só texto, 1 e 2 tool calls, histórico com resultado de tool e usage com cache, no formato da Responses API da §3.2, com `store=False` e sem `id` nos itens `function_call`.
- [ ] [AC-05] Anthropic: system no parâmetro `system`, resultados de tool agrupados numa única mensagem `user`, `raw` com os blocos originais (inclusive `thinking`), usage somando o cache à entrada e nenhum envio de `temperature`.
- [ ] [AC-06] Gemini: `function_response` com `name` resolvido pelo id, ids gerados para chamadas sem id, `thought_signature` preservada ida e volta via `raw`, raciocínio contado como saída e nenhum envio de `temperature`.
- [ ] [AC-07] Erros dos SDKs e respostas vazias ou bloqueadas viram `LLMError`, e `text is None` só ocorre com `tool_calls` não vazio.
- [ ] [AC-08] `custo_estimado` segue a fórmula da §3.4, devolve `None` para modelo fora da tabela (busca exata) ou sem usage, e a tabela tem os preços conferidos em 2026-11-02 com as fontes no módulo.
- [ ] [AC-TESTES] `pytest` verde, sem acesso à rede. Com os extras instalados, nenhum teste é pulado.
- [ ] [AC-LINT] `ruff check .` verde.
- **Verificação manual (opcional, autor, custa centavos):** com a chave no `.env`, rodar uma vez por provedor configurado:
  ```python
  from dotenv import load_dotenv; load_dotenv(); import os
  from app.llm.base import Message, ToolSpec, criar_cliente
  llm = criar_cliente(os.environ["LLM_PROVIDER"], os.environ["LLM_MODEL"])
  hora = ToolSpec("hora_atual", "Devolve a hora atual da loja", {"type": "object", "properties": {}})
  msgs = [Message("user", "Que horas são? Use a ferramenta.")]
  r1 = llm.chat("Responda em português.", msgs, [hora]); print(r1)
  msgs += [Message("assistant", r1.text or "", r1.tool_calls, raw=r1.raw), Message("tool", '{"hora": "10:42"}', tool_call_id=r1.tool_calls[0].id)]
  print(llm.chat("Responda em português.", msgs, [hora]))
  ```
  Resultado esperado: `r1` com `tool_calls[0].name == "hora_atual"` e `usage` preenchido; a segunda resposta com texto citando 10:42. Esse teste cobre o que a suíte unitária não alcança: `call_id` na OpenAI, `thought_signature` no Gemini, blocos `thinking` na Anthropic e a temperatura aceita pelo modelo OpenAI.

## 8. Riscos e pontos em aberto
Decisões aprovadas pelo autor antes da implementação: manter as quatro propostas abaixo.

1. **Campo `raw` em `Message` e `LLMResponse` (mudança na ARCHITECTURE §4).** É a proposta mínima para devolver ao provedor o estado opaco do turno: `thought_signature` do Gemini 3 (sem ela, a API devolve 400 no function calling) e blocos `thinking` dos modelos Claude atuais. O campo é opcional, tem padrão `None` e fica fora de `==`, então não quebra quem já usa os tipos. Se aprovado, a ARCHITECTURE §4 ganha `raw: Any = None` nos dois tipos, mais a regra "o agente copia `resp.raw` para a mensagem do assistente" na §5. Se recusado: o Gemini teria de usar o valor documentado `skip_thought_signature_validator`, que o Google diz que piora o modelo, e o Anthropic ficaria sem garantia de funcionar com tools.
2. **Temperatura só na OpenAI.** D05 sugere 0,2–0,3. Na prática: a API da Anthropic passou a rejeitar `temperature` (versão 2026-10-21, e o SDK 2.x nem tem o parâmetro); o Google recomenda manter 1.0 no Gemini 3. A spec usa 0,2 só no adaptador OpenAI e não envia temperatura nos outros dois. Vale ajustar o texto da D05.
3. **Modelo OpenAI padrão.** `gpt-5.4-mini` existe e foi confirmado na página de preços em 2026-11-02 (US$ 0,75 entrada / 0,075 cache / 4,50 saída por 1M). O raciocínio padrão dele é `none`, então aceita `temperature`. Mas ele já não aparece na lista principal de modelos: o barato atual da OpenAI é o **`gpt-6-luna`** (US$ 0,10 / 0,01 / 0,50, function calling suportado, raciocínio padrão `medium`). A estimativa da D05 (US$ 0,004–0,008 por turno) fica otimista com o `gpt-5.4-mini`: um turno com ~3 chamadas de ~3 mil tokens de entrada e ~300 de saída dá cerca de US$ 0,01. Com o `gpt-6-luna` ficaria ~7 vezes mais barato, porém com raciocínio `medium` a temperatura provavelmente é recusada. Recomendo manter `gpt-5.4-mini` agora e comparar com o `gpt-6-luna` na suíte de avaliação (SPEC-0006). Se o autor preferir trocar já, o adaptador precisa de `temperature=None` para esse modelo ou de `reasoning={"effort": "none"}`. As duas tabelas de preço já estão na §3.4.
4. **Preços de Anthropic e Gemini na tabela.** `claude-haiku-5-5` e `gemini-3.5-flash-lite` foram incluídos com preço conferido na página oficial (mesma data), para permitir comparar provedores na avaliação. O Haiku tem preço maior acima de 100 mil tokens de prompt, faixa que este agente não atinge. Se o autor não for testar esses provedores, as duas linhas podem sair.

Riscos (mitigação já na spec):
- **Temperatura e modelo OpenAI:** se `LLM_MODEL` mudar para um modelo de raciocínio com esforço diferente de `none`, a API pode recusar `temperature` com 400. O erro vira `LLMError` com a mensagem do provedor, e a verificação manual pega isso.
- **Responses API sem estado:** com `store=False`, não reenviamos itens de raciocínio. Com o esforço `none` do modelo padrão esses itens não existem; com outros modelos, a qualidade entre iterações pode cair um pouco.
- **Custo do cache na Anthropic:** tokens de *escrita* em cache (`cache_creation_input_tokens`) entram como entrada normal no custo, embora custem 1,25×. Não ligamos prompt caching, então o valor esperado é 0.
- **Nomes de módulo `openai.py` e `anthropic.py`** dentro de `app/llm/providers/` são iguais aos dos pacotes. Com import absoluto (padrão no Python 3), `import openai` dentro deles carrega o SDK, não o próprio módulo. Os nomes vêm da ARCHITECTURE §2 e não mudam.
- **APIs que mudam rápido:** os campos citados foram conferidos nos SDKs instalados (`openai` 3.42.1, `anthropic` 2.3.0, `google-genai` 2.34.0). Os mínimos no `pyproject.toml` garantem esses majors.
