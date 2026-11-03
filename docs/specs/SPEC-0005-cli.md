# SPEC-0005 — CLI: chat no terminal com o Emilio

- **Status:** implementada
- **PRD:** [PRD-0001](../prds/PRD-0001-agente-atendimento.md)
- **Depende de:** SPEC-0004 (`criar_agente`, `Agente.responder`, `Resposta`). Usa `criar_banco` e `conectar` da SPEC-0001 e `LLMError` da SPEC-0003.

## 1. Objetivo
`python -m app.cli` abre um chat no terminal com o Emilio. É a interface oficial ([D10](../DECISIONS.md#d10--interface-cli)): o avaliador clona, cria o `.env` com a chave e conversa. A CLI guarda o histórico numa lista em memória ([D09](../DECISIONS.md#d09--memória-da-conversa-sim-persistência-do-histórico-não)) e mostra, a cada resposta, quais ferramentas o agente consultou.
Atende `PRD-0001/R6` (contexto dentro da conversa) e torna visíveis `R3`/`R4` (dados × políticas) e `R9` (tokens e custo, com `--debug`, [D14](../DECISIONS.md#d14--custo-e-observabilidade)).

## 2. Escopo
- **Dentro:** `app/cli.py` (loop de conversa testável, comandos `sair`/`/sair`/`/nova`, flag `--debug`, criação automática do banco, erros de inicialização sem traceback, UTF-8 no console); seção curta "Como conversar com o Emilio" no `README.md`.
- **Fora:**
  - Mudanças no agente, nas tools, na config, na ingestão e no `FakeLLM`.
  - Cores/ANSI, edição de linha, streaming, salvar a conversa em arquivo, persistência entre sessões (D09).
  - O script de exemplos (SPEC-0007) e a avaliação (SPEC-0006): usam o agente direto, não a CLI.
  - README final (SPEC-0007).
  - Dependências novas: nenhuma (`argparse`, `uuid`, `io`, `sys` da stdlib).

## 3. Contrato

### 3.1 Textos fixos (`app/cli.py`)
```python
BOAS_VINDAS = ("Emilio: Oi! Eu sou o Emilio, atendente virtual da Empório da Música. "
               "Posso ajudar com instrumentos, preços, pedidos e políticas da loja.")
COMANDOS = "Comandos: /nova começa outra conversa; sair ou /sair encerra."
PROMPT_ENTRADA = "Você: "
PREFIXO_RESPOSTA = "Emilio: "
NOVA_CONVERSA = "(nova conversa: o Emilio não lembra mais das mensagens anteriores)"
DESPEDIDA = "Emilio: Até mais! Quando precisar, é só chamar."
CRIANDO_BANCO = "Criando o banco de dados a partir dos CSVs (só na primeira execução)..."
ERRO_INICIO = ("Não consegui iniciar o Emilio: {erro}\n"
               "Confira o arquivo .env (se ainda não existe, copie o .env.example "
               "e preencha a chave do provedor).")
```
Nenhum deles passa pelo LLM. As boas-vindas **não** entram no histórico (o modelo não recebe uma fala que não gerou).

### 3.2 Funções
```python
def gerar_conversa_id() -> str: ...
    # f"cli-{uuid4().hex[:8]}"; o prefixo separa as conversas da CLI das da avaliação/exemplos em logs/llm_calls.jsonl

def formatar_custo(custo: float | None) -> str: ...
    # None → "n/d"; senão f"US$ {custo:.6f}"   (ex.: 0.00003 → "US$ 0.000030")

def linha_ferramentas(tools_usadas: list[str]) -> str: ...
    # [] → "[ferramentas: nenhuma]"; senão "[ferramentas: " + ", ".join(tools_usadas) + "]"
    # na ordem e com repetições, como vieram em Resposta.tools_usadas

def linha_debug(resposta: Resposta, conversa_id: str) -> str: ...
    # f"[debug: {r.status} | {r.iteracoes} chamada(s) ao LLM | tokens: {u.input_tokens} entrada "
    # f"({u.cached_tokens} em cache), {u.output_tokens} saída | custo: {formatar_custo(r.custo_usd)} "
    # f"| conversa: {conversa_id}]"        (r = resposta, u = resposta.usage)

def executar(agente, ler: Callable[[str], str] = input, escrever: Callable[[str], None] = print,
             debug: bool = False, novo_id: Callable[[], str] = gerar_conversa_id) -> int: ...

def abrir_banco(caminho: Path, escrever: Callable[[str], None] = print) -> sqlite3.Connection: ...

def configurar_utf8() -> None: ...

def main(argv: list[str] | None = None) -> None: ...

if __name__ == "__main__":
    main()
```
`agente` é qualquer objeto com `responder(historico, mensagem, conversa_id) -> Resposta` (na prática, um `Agente`). `escrever` recebe **uma** `str` por chamada (pode conter `\n`, ex.: resposta longa do modelo).

### 3.3 `executar`, passo a passo
1. `historico: list[Message] = []`; `conversa_id = novo_id()`; `turnos = 0`; `custo_total: float | None = 0.0`.
2. `escrever(BOAS_VINDAS)`; `escrever(COMANDOS)`; `escrever("")`.
3. Laço, todo dentro de `try` / `except (EOFError, KeyboardInterrupt): escrever("")` (a linha vazia tira a despedida da linha do `Você: `; vale também para Ctrl+C durante a espera da API):
   1. `entrada = ler(PROMPT_ENTRADA).strip()`. Vazia → volta ao início do laço (não chama o agente).
   2. `comando = entrada.lower()`:
      - `"sair"` ou `"/sair"` → sai do laço.
      - `"/nova"` → `historico = []`, `conversa_id = novo_id()`, `escrever(NOVA_CONVERSA)`, `escrever("")`, volta ao laço.
      - outro texto começando com `"/"` → `escrever(COMANDOS)`, `escrever("")`, volta ao laço (comando digitado errado não vai ao LLM).
   3. `resposta = agente.responder(historico, entrada, conversa_id)`; `historico.extend(resposta.para_historico)` (ARCHITECTURE §5; com `mensagem_longa` a lista vem vazia).
   4. `turnos += 1`; `custo_total = None` se `custo_total` ou `resposta.custo_usd` for `None`, senão `custo_total + resposta.custo_usd`.
   5. `escrever(PREFIXO_RESPOSTA + resposta.texto)`; `escrever(linha_ferramentas(resposta.tools_usadas))`; se `debug`, `escrever(linha_debug(resposta, conversa_id))`; `escrever("")`.
   Todos os `status` (`ok`, `limite_iteracoes`, `erro_llm`, `mensagem_longa`) são exibidos do mesmo jeito: o texto já é a mensagem amigável do agente.
4. Depois do laço: `escrever(DESPEDIDA)`; se `debug`, `escrever(f"[debug: {turnos} turno(s) nesta sessão, custo total {formatar_custo(custo_total)}]")`.
5. `return 0`. Outras exceções (bug) não são capturadas.

Exemplo de sessão (sem `--debug`):
```
Emilio: Oi! Eu sou o Emilio, atendente virtual da Empório da Música. Posso ajudar com ...
Comandos: /nova começa outra conversa; sair ou /sair encerra.

Você: Qual o endereço da loja?
Emilio: Fica na Rua 14 de Maio, 3200, no Centro de Campo Grande.
[ferramentas: consultar_politica]

Você: sair
Emilio: Até mais! Quando precisar, é só chamar.
```

### 3.4 Banco, montagem e erros
**`abrir_banco(caminho, escrever)`:** se `caminho` não existe → `escrever(CRIANDO_BANCO)` e `criar_banco(destino=caminho)`. Depois, sempre `return conectar(caminho)` (somente leitura). Passar `caminho` explicitamente a ambas (o padrão de `conectar` é fixado na definição e não enxerga `monkeypatch`).

Por que criar sozinho, e não mandar rodar `python -m app.ingest` e sair com 1: o banco é um artefato derivado (fora do git) e determinístico dos CSVs de `data/raw/`, leva menos de 1 s, e só é criado quando falta (nunca sobrescreve). É um comando a menos para o avaliador, sem esconder nada: a mensagem aparece na tela. `python -m app.ingest` continua sendo o jeito de recriar.

**`configurar_utf8()`:** para cada fluxo em `(sys.stdin, sys.stdout, sys.stderr)`, se `isinstance(fluxo, io.TextIOWrapper)`, `fluxo.reconfigure(encoding="utf-8", errors="replace")`. Chamada só dentro de `main()`, nunca no import. Motivo: no Windows, quando a saída não é o console nativo (Git Bash/mintty, redirecionamento), o Python usa a página de código local e os acentos saem errados; `errors="replace"` evita que um caractere estranho na entrada derrube a sessão.

**`main(argv)`:**
1. `argparse.ArgumentParser(prog="python -m app.cli", description="Converse com o Emilio, o atendente virtual da Empório da Música.")` com uma única flag: `--debug` (`action="store_true"`, `help="mostra status, tokens e custo estimado de cada resposta"`). `args = parser.parse_args(argv)`.
2. `configurar_utf8()`.
3. `try: agente = criar_agente(conexao=abrir_banco(CAMINHO_BANCO))` / `except (LLMError, ValueError) as erro: print(ERRO_INICIO.format(erro=erro), file=sys.stderr); sys.exit(1)`.
   - `LLMError`: provedor inválido, `LLM_MODEL` vazio, chave ausente (`"defina OPENAI_API_KEY no .env"`), extra não instalado (`criar_cliente`, SPEC-0003).
   - `ValueError`: variável inválida no `.env` (`carregar_config`, SPEC-0004 §3.1).
   - `CAMINHO_BANCO` importado de `app.db` no topo de `app/cli.py` e lido como global do módulo na chamada (o teste troca `app.cli.CAMINHO_BANCO`). `criar_agente` também é importado no topo (o teste troca `app.cli.criar_agente`).
4. `sys.exit(executar(agente, ler=input, escrever=print, debug=args.debug))`. Passar `ler=input` **na chamada** (resolvido em tempo de execução, então `monkeypatch` em `builtins.input` funciona no teste).

Imports no topo de `app/cli.py`: `argparse`, `io`, `sqlite3`, `sys`, `uuid.uuid4`, `collections.abc.Callable`, `pathlib.Path`, `app.agent` (`Resposta`, `criar_agente`), `app.db` (`CAMINHO_BANCO`, `conectar`), `app.ingest` (`criar_banco`), `app.llm.base` (`LLMError`, `Message`). Nenhum SDK de provedor é importado (`criar_agente` só importa o adaptador quando é chamado).

## 4. Arquivos
- **Criar:** `app/cli.py`, `tests/test_cli.py`.
- **Alterar:**
  - `README.md`: acrescentar, logo depois da seção "Ambiente", exatamente:
    ````markdown
    ## Como conversar com o Emilio
    ```bash
    cp .env.example .env          # Windows (cmd): copy .env.example .env
    # edite o .env e preencha OPENAI_API_KEY (ou troque LLM_PROVIDER e preencha a chave dele)
    python -m app.cli             # ou: python -m app.cli --debug (tokens e custo de cada resposta)
    ```
    - Na primeira execução, o banco `data/emporio.db` é criado a partir dos CSVs (para recriar: `python -m app.ingest`).
    - Cada resposta mostra as ferramentas que o Emilio consultou, ex.: `[ferramentas: buscar_produtos]`.
    - `/nova` começa outra conversa; `sair`, `/sair` ou Ctrl+C encerram.
    - Anthropic ou Gemini: instale o extra antes (`pip install -e ".[anthropic]"` ou `".[gemini]"`).
    ````
  - Este arquivo (status e critérios ao final).
- **Não alterar:** `app/agent.py`, `app/db.py`, `app/ingest.py`, `app/config.py`, `app/llm/`, `tests/conftest.py`, `.env.example`, `docs/ARCHITECTURE.md` (as mudanças da §8 já foram aplicadas na aprovação).
- **Testes:** `tests/test_cli.py`.

## 5. Testes (escrever ANTES do código)
Comece no *red*. Sem rede: LLM sempre `FakeLLM` (`resposta_texto`, `resposta_tool`; `Usage(10, 5)` em cada resposta). Se o temp do sistema der `PermissionError`, rode `pytest --basetemp=<pasta sua>`.

**Helpers em `tests/test_cli.py`** (usam a fixture `conexao` do `conftest.py`):
```python
CFG = Config(provider="fake", model="fake")
AGORA = datetime(2026, 11, 3, 10, 0)

def montar(roteiro, conexao, tmp_path, config=CFG):
    llm = FakeLLM(roteiro)
    agente = criar_agente(config=config, llm=llm, conexao=conexao, pasta_logs=tmp_path, agora=AGORA)
    return agente, llm

def leitor(entradas):
    """ler() falso: devolve as entradas na ordem; uma exceção na lista é levantada; no fim, EOFError."""
    fila, prompts = list(entradas), []
    def ler(prompt):
        prompts.append(prompt)
        if not fila:
            raise EOFError
        item = fila.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
    return ler, prompts

def rodar(agente, entradas, debug=False, ids=("cli-a", "cli-b", "cli-c")):
    ler, prompts = leitor(entradas)
    saida, fila_ids = [], iter(ids)
    codigo = executar(agente, ler=ler, escrever=saida.append, debug=debug, novo_id=lambda: next(fila_ids))
    return codigo, saida, prompts

def logs(tmp_path):   # lista de dicts de tmp_path / "llm_calls.jsonl"
```

**Loop e histórico**
- [ ] Dois turnos com memória: roteiro `[resposta_tool("consultar_politica", topico="sobre_a_loja"), resposta_texto("Fica na Rua 14 de Maio, 3200."), resposta_texto("Abrimos às 9h.")]`, entradas `["Qual o endereço?", "E que horas abre?"]` → `codigo == 0`; `saida[:3] == [BOAS_VINDAS, COMANDOS, ""]`; a saída contém, nesta ordem, `"Emilio: Fica na Rua 14 de Maio, 3200."`, `"[ferramentas: consultar_politica]"`, `""`, `"Emilio: Abrimos às 9h."`, `"[ferramentas: nenhuma]"`; `saida[-1] == DESPEDIDA`; `llm.chamadas[2]["messages"] == [Message("user", "Qual o endereço?"), Message("assistant", "Fica na Rua 14 de Maio, 3200."), Message("user", "E que horas abre?")]`; nenhuma linha começa com `"[debug"`; todos os `prompts == "Você: "`; os 3 registros de `logs(tmp_path)` têm `conversa_id == "cli-a"` e `turno` `[1, 1, 2]`.
- [ ] Linha vazia e espaços: entradas `["", "   ", "  oi  "]`, roteiro `[resposta_texto("Olá!")]` → `len(llm.chamadas) == 1` e `llm.chamadas[0]["messages"] == [Message("user", "oi")]` (entrada sem os espaços).
- [ ] Ferramentas na ordem, com repetição: `linha_ferramentas(["buscar_produtos", "buscar_produtos", "consultar_politica"]) == "[ferramentas: buscar_produtos, buscar_produtos, consultar_politica]"`; `linha_ferramentas([]) == "[ferramentas: nenhuma]"`.
- [ ] Resposta não-ok é exibida e a conversa segue: (a) `config = Config(provider="fake", model="fake", max_message_chars=10)`, entradas `["x" * 11, "oi"]`, roteiro `[resposta_texto("Olá!")]` → saída contém `"Emilio: " + MENSAGEM_LONGA.format(limite=10)` seguido de `"[ferramentas: nenhuma]"`, e `llm.chamadas[0]["messages"] == [Message("user", "oi")]` (a longa não entrou no histórico); (b) `FakeLLM([])`, entradas `["oi", "de novo"]` → saída contém `"Emilio: " + ERRO_PROVEDOR` duas vezes, `codigo == 0` e `llm.chamadas[1]["messages"] == [Message("user", "oi"), Message("assistant", ERRO_PROVEDOR), Message("user", "de novo")]`.

**Comandos e saída**
- [ ] Sair (parametrizado: `"sair"`, `"/sair"`, `"  SAIR "`): entradas `[<comando>, "oi"]`, `FakeLLM([])` → `codigo == 0`, `llm.chamadas == []`, `len(prompts) == 1` e `saida == [BOAS_VINDAS, COMANDOS, "", DESPEDIDA]` (sem linha vazia extra antes da despedida, ao contrário do EOF).
- [ ] EOF: entradas `[]` → `codigo == 0`, `saida == [BOAS_VINDAS, COMANDOS, "", "", DESPEDIDA]`.
- [ ] Ctrl+C na leitura: entradas `[KeyboardInterrupt()]` → `codigo == 0`, `saida[-2:] == ["", DESPEDIDA]`.
- [ ] Ctrl+C durante a resposta: agente de teste `class Interrompe: def responder(self, historico, mensagem, conversa_id): raise KeyboardInterrupt` com entradas `["oi"]` → `codigo == 0`, `saida[-1] == DESPEDIDA`.
- [ ] `/nova`: roteiro `[resposta_texto("a"), resposta_texto("b")]`, entradas `["um", "/nova", "dois"]` → `NOVA_CONVERSA in saida`; `llm.chamadas[1]["messages"] == [Message("user", "dois")]`; `logs(tmp_path)` com `conversa_id` `["cli-a", "cli-b"]` e `turno` `[1, 1]`.
- [ ] Comando desconhecido: entradas `["/ajuda"]`, `FakeLLM([])` → `llm.chamadas == []` e `COMANDOS` aparece 2 vezes na saída (boas-vindas + resposta ao comando).
- [ ] `gerar_conversa_id()` casa com `re.fullmatch(r"cli-[0-9a-f]{8}", ...)` e duas chamadas dão valores diferentes.

**`--debug`**
- [ ] Com custo: `config = Config(provider="openai", model="gpt-5.4-mini")` (o `FakeLLM` é injetado; o modelo só define o preço), roteiro `[resposta_texto("a"), resposta_texto("b")]`, entradas `["um", "dois"]`, `debug=True` → a saída contém `"[debug: ok | 1 chamada(s) ao LLM | tokens: 10 entrada (0 em cache), 5 saída | custo: US$ 0.000030 | conversa: cli-a]"` (2 vezes) logo depois de cada linha `[ferramentas: ...]`, e `saida[-1] == "[debug: 2 turno(s) nesta sessão, custo total US$ 0.000060]"`.
- [ ] Sem preço: `CFG` (modelo `"fake"`), entradas `["um"]`, `debug=True` → a linha de debug termina em `"custo: n/d | conversa: cli-a]"` e `saida[-1] == "[debug: 1 turno(s) nesta sessão, custo total n/d]"`.
- [ ] `formatar_custo(None) == "n/d"`; `formatar_custo(0.0) == "US$ 0.000000"`; `formatar_custo(0.00003) == "US$ 0.000030"`.

**Banco e montagem (`abrir_banco`, `main`)**
- [ ] Banco ausente: `caminho = tmp_path / "dados" / "emporio.db"`, `saida = []`, `con = abrir_banco(caminho, saida.append)` → `saida == [CRIANDO_BANCO]`, `caminho.exists()`, `con.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0`, e `con.execute("DELETE FROM products")` levanta `sqlite3.OperationalError` (somente leitura). Fechar `con`.
- [ ] Banco existente: com a fixture `banco` do `conftest.py`, `abrir_banco(banco, saida.append)` → `saida == []` e a conexão funciona.
- [ ] `main` sem erro: `monkeypatch.setattr("app.cli.CAMINHO_BANCO", tmp_path / "x.db")`; `abrir_banco` falso (`app.cli.abrir_banco`) que guarda o caminho recebido e devolve `"conexao-falsa"`; `criar_agente` falso (`app.cli.criar_agente`) que guarda os kwargs e devolve `object()`; `monkeypatch.setattr("builtins.input", <função que levanta EOFError>)`. `main(["--debug"])` → `SystemExit` com `code == 0`; caminho recebido `== tmp_path / "x.db"`; kwargs `== {"conexao": "conexao-falsa"}`; `capsys.readouterr().out` contém `BOAS_VINDAS`, `DESPEDIDA` e `"[debug: 0 turno(s) nesta sessão, custo total US$ 0.000000]"`.
- [ ] Erro de montagem (parametrizado: `LLMError("defina OPENAI_API_KEY no .env")`, `ValueError("MAX_TOOL_ITERATIONS deve ser inteiro >= 1")`): `abrir_banco` falso como acima e `criar_agente` falso que levanta o erro → `main([])` levanta `SystemExit` com `code == 1`; `capsys.readouterr().err` contém `"Não consegui iniciar o Emilio"`, a mensagem do erro e `".env.example"`, e não contém `"Traceback"`.
- [ ] Isolamento: `subprocess.run([sys.executable, "-c", "import sys, app.cli; assert not any(m in sys.modules for m in ('openai', 'anthropic', 'google.genai'))"], check=True)` (mesmo padrão de `test_agent.py`).

**Fixtures/mocks:** `conexao` e `banco` do `conftest.py`, `tmp_path` para os logs, `FakeLLM`, `monkeypatch` e `capsys`.

## 6. Plano
Commits seguindo o ciclo da spec (AGENTS.md, D16). Antes de cada commit: `pytest` e `ruff check .` verdes, exceto nos `test(...)`, em que só os testes novos falham.
1. `docs(spec): SPEC-0005 cli` (esta spec, depois de aprovada).
2. Testes de "Loop e histórico", "Comandos e saída" e "`--debug`" *red* → `test(cli): loop de conversa, comandos e debug`. Textos da §3.1, `gerar_conversa_id`, `formatar_custo`, `linha_ferramentas`, `linha_debug` e `executar` → `feat(cli): loop de conversa, comandos e debug`.
3. Testes de "Banco e montagem" *red* → `test(cli): banco automático e erros de inicialização`. `abrir_banco`, `configurar_utf8`, `main`, o bloco `__main__` e a seção do README (§4); marcar os critérios da §7; status **implementada** → `feat(cli): banco automático e erros de inicialização`.

## 7. Critérios de aceite
- [x] [AC-01] `python -m app.cli` abre o chat com as boas-vindas e os comandos, sem chamar o LLM; cada resposta sai como `Emilio: <texto>` seguida de `[ferramentas: ...]` (ou `nenhuma`).
- [x] [AC-02] Memória dentro da sessão: cada turno recebe o histórico anterior via `para_historico`, com o mesmo `conversa_id` (`cli-xxxxxxxx`) em todos os registros de `logs/llm_calls.jsonl`; `/nova` zera o histórico e troca o id.
- [x] [AC-03] Linha vazia e comando desconhecido (`/...`) não chamam o LLM; `sair`, `/sair` (sem diferenciar maiúsculas), Ctrl+D/EOF e Ctrl+C (na leitura ou esperando a API) encerram com a despedida e código 0.
- [x] [AC-04] `--debug` mostra status, chamadas, tokens, custo (`n/d` sem preço) e `conversa_id` por turno, e o total da sessão no fim; sem a flag, nada disso aparece.
- [x] [AC-05] Sem `data/emporio.db`, a CLI avisa e cria o banco a partir dos CSVs antes de conversar; com o banco existente, não recria.
- [x] [AC-06] `LLMError` e `ValueError` na montagem viram `ERRO_INICIO` no stderr, sem traceback, e código de saída 1.
- [x] [AC-07] Acentos corretos no terminal do Windows (UTF-8 configurado só em `main()`); nenhuma dependência nova; importar `app.cli` não carrega SDK de provedor.
- [x] [AC-08] README com a seção "Como conversar com o Emilio" da §4.
- [x] [AC-TESTES] `pytest` verde, sem rede.
- [x] [AC-LINT] `ruff check .` verde.
- **Verificação manual (autor, API real, custa centavos):** com a chave no `.env` e `AGENT_TODAY=2026-11-03`:
  1. Renomear `data/emporio.db` (se existir) e rodar `python -m app.cli` → aparece `CRIANDO_BANCO` e o chat abre.
  2. "Quais violões disponíveis até R$ 1000?" → `[ferramentas: buscar_produtos]`; "Qual o endereço da loja?" → `[ferramentas: consultar_politica]`; "Vocês vendem cordas?" → `[ferramentas: nenhuma]`, redirecionando sem indicar outra loja.
  3. "Quanto custa o Takamine GD20?" e depois "E no PIX?" → o 2º turno cita R$ 2.089,05 (memória); `/nova` e "E no PIX?" de novo → o Emilio pergunta de qual produto.
  4. Acentos certos no PowerShell/Windows Terminal e no Git Bash; Ctrl+C sai com a despedida, sem traceback.
  5. `python -m app.cli --debug` → linhas de debug com `custo: US$ ...`; o `conversa_id` mostrado aparece em `logs/llm_calls.jsonl`.
  6. Esvaziar `OPENAI_API_KEY` no `.env` → `Não consegui iniciar o Emilio: defina OPENAI_API_KEY no .env` e `echo $LASTEXITCODE` (PowerShell) mostra `1`.

## 8. Riscos e pontos em aberto

**Decisões desta spec (confirmar na revisão):**
1. **Linha de ferramentas sempre ligada, sem `--sem-ferramentas`.** É o que a D10 promete e o que o avaliador quer ver (quando o agente consulta dados × políticas); uma flag para escondê-la seria código sem uso. A única flag é `--debug`.
2. **Resumo da sessão só com `--debug`.** Mostrar custo ao "cliente" no modo normal destoa do chat; quem avalia custo usa `--debug` (anunciado no README) ou o `llm_calls.jsonl`.
3. **`/nova` adotado:** permite testar cenários diferentes (ex.: com e sem memória) sem reabrir o terminal. Não recria o agente, então a hora do prompt continua a da abertura (mesma limitação da SPEC-0004 §8-5).
4. **Comando desconhecido não vai ao LLM:** um `/ajuda` ou um `/nova` digitado errado (ex.: `/nvoa`) não gasta chamada; a CLI só repete `COMANDOS`. Efeito colateral aceito: uma mensagem do cliente que comece com `/` também não é enviada.
5. **`sair` sem barra também encerra** (é o que um usuário leigo tenta primeiro). Só a palavra exata, depois de `strip().lower()`.

**Mudanças na ARCHITECTURE (aplicadas na aprovação, 2026-11-02):**
1. **§1 Visão geral:** acrescentar `python -m app.cli [--debug]` ao diagrama/bullet da CLI e a frase "A CLI cria o banco a partir dos CSVs quando `data/emporio.db` não existe (via `criar_banco`); em tempo de execução ele continua somente leitura."
2. **§7 Banco:** "recriado do zero por `python -m app.ingest`; criado automaticamente pela CLI na primeira execução se não existir."
3. **§9 Registro de uso:** registrar que o `conversa_id` da CLI segue o formato `cli-xxxxxxxx` (8 hex), para filtrar as conversas da CLI no `llm_calls.jsonl`.

**Riscos:**
- Ctrl+C no `input()` do Windows às vezes chega como `EOFError`; os dois caminhos dão a mesma saída limpa.
- As boas-vindas fixas não entram no histórico; se o cliente disser "oi", o modelo cumprimenta de novo. Aceitável e mais honesto que injetar uma fala do assistente que o modelo não gerou.
- `abrir_banco` não percebe CSVs alterados depois da criação; o README diz como recriar (`python -m app.ingest`).
- A SPEC-0006 e a SPEC-0007 chamam `criar_agente()` direto; sem o banco, `conectar` aponta `python -m app.ingest`. Se quiserem o mesmo atalho, podem reutilizar `abrir_banco` (decidir nelas).
