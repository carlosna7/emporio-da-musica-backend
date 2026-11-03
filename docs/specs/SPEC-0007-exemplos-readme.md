# SPEC-0007 — Conversas de exemplo e README final

- **Status:** implementada
- **PRD:** [PRD-0001](../prds/PRD-0001-agente-atendimento.md)
- **Depende de:** SPEC-0006 (os números da avaliação que o README cita). Reutiliza `criar_agente` e `Resposta` (SPEC-0004), `criar_cliente`, `LLMError`, `ToolCall` e `Usage` (SPEC-0003), `abrir_banco`, `configurar_utf8` e `formatar_custo` (SPEC-0005), `situacao_loja` e `DIAS_SEMANA` (`app/horario.py`).

## 1. Objetivo
Fechar os entregáveis do desafio que ainda faltam (PRD-0001, "Entregáveis"):
1. **3 a 5 conversas de exemplo em `examples/`**, geradas pelo agente real por um script pequeno e reproduzível (`python -m evals.exemplos`), como prometem a [D10](../DECISIONS.md#d10--interface-cli) ("o script que gera as conversas de exemplo usa o mesmo agente") e a [D12](../DECISIONS.md#d12--testes-e-avaliação) ("as conversas de `examples/` são geradas pelo agente real"). Cada arquivo mostra a mensagem do cliente, a resposta do Emilio e as ferramentas chamadas em cada turno, com data simulada, modelo, tokens e custo.
2. **README final**: como rodar, visão da arquitetura, decisões, resultados da avaliação, suposições, limitações, uso de IA e próximos passos, com o conteúdo vindo do DECISIONS, do ARCHITECTURE e dos relatórios (sem números novos nem inventados).

Os exemplos tornam visíveis os critérios de sucesso 1 a 6 do PRD e os requisitos `R1`–`R8` em conversas mais naturais que os casos da suíte; o cabeçalho de cada um mostra `R9` (tokens e custo).

**Por que gerar de novo, e não aproveitar a avaliação:** os relatórios de `evals/resultados/` não guardam o texto das conversas (só a resposta truncada dos turnos reprovados) e `evals/logs/llm_calls.jsonl` só tem tokens, tools e custo. Não há de onde tirar as conversas sem rodar o agente.

## 2. Escopo
- **Dentro:**
  - `evals/exemplos.py`: os 5 roteiros (§3.2), o gerador (§3.3) e o `main`.
  - `examples/01-…md` a `examples/05-…md`: gerados pelo script com o modelo padrão (`gpt-6-luna`, `medium`), **sem edição manual**, revisados pelo autor e versionados.
  - `README.md` reescrito conforme §3.4.
  - Testes: `tests/test_exemplos.py` (parte determinística, com `FakeLLM`) e `tests/test_readme.py` (seções e links).
- **Fora:**
  - Mudanças em `app/` (agente, prompt, tools, CLI). As limitações encontradas vão para o README; correções, se o autor quiser, vão numa spec ou num `fix:` separado.
  - Mudanças em `evals/run.py`, `evals/avaliacao.py` e `evals/casos.json`.
  - `docs/DECISIONS.md` (escrito pelo autor; o README só resume e linka).
  - Verificar as respostas dos exemplos automaticamente (isso é o papel da suíte; aqui o autor lê, §8-4).
  - Flags no script (`--conversas`, `--modelo`, `--esforco`), índice gerado em `examples/README.md`, tradução do README.
  - O frontend e o PRD-0002 (opcional).
  - Dependências novas: nenhuma (`argparse`, `json`, `contextlib`, `dataclasses`, da stdlib).

## 3. Contrato

### 3.1 Onde fica o script e como roda
`evals/exemplos.py`, rodado com `python -m evals.exemplos` a partir da raiz (mesmo mecanismo do `python -m evals.run`, SPEC-0006 §3.5; não precisa mudar o `pyproject.toml`).

Por que em `evals/` e não em `scripts/gerar_exemplos.py` (o que o ARCHITECTURE §2 prevê hoje): o AGENTS.md diz que chamadas reais ao LLM **só** ficam em `evals/`. Além disso, `scripts/` não é pacote e o script precisaria de ajuste no `sys.path` para importar o que já existe em `evals/`. A mudança no ARCHITECTURE está na §8.

### 3.2 Roteiros (`evals/exemplos.py`)
```python
@dataclass(frozen=True)
class Roteiro:
    nome: str                    # "NN-slug": nome do arquivo (examples/<nome>.md) e conversa_id "exemplo-<nome>"
    titulo: str                  # vira o "# " do Markdown
    descricao: str               # uma frase: o que a conversa mostra (critérios do PRD)
    agora: datetime              # "agora" da loja nesta conversa (sem fuso, horário de MS)
    mensagens: tuple[str, ...]   # mensagens do cliente, em ordem

ROTEIROS: tuple[Roteiro, ...] = (...)   # os 5 abaixo, nesta ordem
```
Os roteiros ficam em Python, e não num JSON como os casos: são 5, não têm expectativas e não precisam de validação de formato além dos testes da §5.

Conteúdo **exato** de `ROTEIROS`:

| `nome` | `titulo` | `agora` | Mensagens |
| --- | --- | --- | --- |
| `01-preco-pix-parcelamento` | Preço, PIX e parcelamento | `2026-11-03 10:00` (terça, aberta) | 1. `Oi! Quanto custa o Takamine GD20?` 2. `E no PIX, quanto fica?` 3. `E se eu parcelar no cartão, dá pra fazer em 12x?` |
| `02-arrependimento-no-prazo` | Arrependimento dentro do prazo | `2026-01-22 10:00` (quinta, aberta) | 1. `Oi, comprei um violão com vocês e me arrependi. Ainda dá pra devolver?` 2. `É o pedido 5, e-mail rafael.pereira@jmail.com` 3. `E o frete da devolução fica por minha conta? Como recebo o dinheiro de volta?` |
| `03-catalogo-e-indisponiveis` | Catálogo e produtos indisponíveis | `2026-11-03 15:00` (terça, aberta) | 1. `Quais violões vocês têm disponíveis até R$ 1000?` 2. `E o Giannini GF-3D, vocês têm?` 3. `E o Shelby SN-7C de 7 cordas?` 4. `Por último: o ukulele Kala KA-ABP-CTG barítono já está à venda?` |
| `04-fora-do-escopo` | Fora do escopo e domingo | `2026-11-08 15:00` (domingo, fechada) | 1. `Oi! Vocês vendem cordas de violão?` 2. `Ah, beleza. E quem ganhou o jogo do Flamengo ontem?` 3. `Haha, justo. Então quais ukuleles estão em promoção?` |
| `05-atendente-humano` | Pedido de atendente humano | `2026-11-04 10:00` (quarta, aberta) | 1. `Quero falar com uma pessoa.` 2. `Prefiro falar com um atendente humano mesmo, por favor.` 3. `Valeu! E qual o endereço da loja, caso eu queira passar aí?` |

`descricao` de cada um (exata):
1. `Preço com a busca no catálogo, o PIX calculado pela ferramenta, a memória da conversa ("e no PIX?") e a política de parcelamento.`
2. `O Emilio pede o número do pedido e o e-mail antes de consultar, confere a entrega e aplica o prazo de 7 dias do direito de arrependimento.`
3. `Busca com faixa de preço e os três casos de produto que existe mas não pode ser comprado: esgotado, descontinuado e pré-lançamento.`
4. `Acessório redirecionado para instrumentos, assunto alheio recusado com gentileza e a volta ao catálogo, num domingo com a loja fechada.`
5. `O Emilio tenta entender o problema uma vez, encaminha quando o cliente insiste e responde o endereço pelos contatos oficiais.`

Rastreio do PRD e o que o autor confere ao ler cada arquivo (fatos tirados do banco com as próprias tools e do manual; os mesmos da SPEC-0006 §3.2):

| Conversa | PRD | O que precisa aparecer | O que não pode aparecer |
| --- | --- | --- | --- |
| 01 | 3, R3, R4, R6 | T1: `buscar_produtos`; R$ 2.199,00 e PIX R$ 2.089,05. T2: R$ 2.089,05 sem perguntar de qual produto. T3: `consultar_politica` (`pagamentos`); até 12x sem juros, parcela mínima de R$ 100 de 7x a 12x | valor de parcela calculado pelo modelo (D07; registrar, §8-9) |
| 02 | 4, R2, R7 | T1: sem `consultar_pedido`; pede número e e-mail ou telefone. T2: `consultar_pedido`; entregue em 18/01/2026, há 4 dias, dentro dos 7 dias. T3: frete de devolução por conta da loja; reembolso na mesma forma de pagamento (PIX) em até 10 dias úteis | "fora do prazo"; `delivered` sem tradução |
| 03 | 1, R2, R3 | T1: `buscar_produtos` com faixa até 1000; o mais barato é o Tagima Memphis AC-39, R$ 429,90. T2: GF-3D esgotado. T3: SN-7C descontinuado. T4: Kala KA-ABP-CTG em pré-lançamento | Takamine, Taylor ou Martin no T1; `coming_soon`; "não temos" para um produto que veio em `indisponiveis` |
| 04 | 5, R5, horário | T1: não vende acessórios, oferece instrumentos, sem `buscar_produtos`. T2: recusa sem tool. T3: `buscar_produtos`; Kalani KAL-700T R$ 359,00 por R$ 323,10 (10%) e Ohana CK-20 R$ 549,00 por R$ 439,20 (20%). Em algum turno: a equipe volta amanhã, segunda (09/11), às 9h | outra loja indicada; PIX sobre preço promocional |
| 05 | 6, 2, R8 | T1: sem `encaminhar_atendente`; pergunta como ajudar. T2: `encaminhar_atendente` (`pedido_do_cliente`); protocolo `EM-20261104-…`; retorno em 24 horas úteis. T3: Rua 14 de Maio, 3200, sem tool | (67) 3321-4500; contato inventado no encaminhamento |

Os roteiros evitam de propósito escrever o tipo junto do modelo ("o violão Giannini GF-3D") quando citam um produto pelo nome, porque o modelo tende a copiar a frase para o termo de busca e a busca volta vazia, sem `indisponiveis` (limitação 2 da §3.4). O objetivo dos exemplos é mostrar o atendimento; a limitação fica documentada no README, não escondida (§8-4).

### 3.3 Gerador (`evals/exemplos.py`)
```python
PASTA_EXEMPLOS = Path(__file__).resolve().parents[1] / "examples"            # versionada
PASTA_LOGS_EXEMPLOS = Path(__file__).resolve().parent / "logs" / "exemplos"   # fora do git (padrão logs/)
ERRO_INICIO = "Não consegui gerar os exemplos: {erro}"

@dataclass
class TurnoExemplo:
    mensagem: str
    texto: str
    chamadas: list[ToolCall]     # tool calls pedidas pelo modelo neste turno, na ordem
    status: str                  # Resposta.status
    usage: Usage                 # Resposta.usage (soma das chamadas do turno)
    custo_usd: float | None      # Resposta.custo_usd

class GravadorLLM:
    """Embrulha um LLMClient e guarda as tool calls de cada resposta (nome e argumentos)."""
    def __init__(self, llm: LLMClient): ...       # self.llm = llm; self.chamadas: list[ToolCall] = []
    def chat(self, system, messages, tools) -> LLMResponse: ...
        # resp = self.llm.chat(system, messages, tools); self.chamadas.extend(resp.tool_calls); return resp
        # LLMError passa direto (o agente a captura)

def gerar_conversa(roteiro: Roteiro, *, config: Config, conexao: sqlite3.Connection,
                   pasta_logs: Path, llm: LLMClient) -> list[TurnoExemplo]: ...
def formatar_chamada(chamada: ToolCall) -> str: ...
def citar(texto: str) -> str: ...
def montar_markdown(roteiro: Roteiro, turnos: list[TurnoExemplo], *, config: Config,
                    quando: datetime) -> str: ...
def gerar_exemplos(roteiros: Sequence[Roteiro], *, config: Config, conexao: sqlite3.Connection,
                   pasta_logs: Path, pasta_saida: Path, llm: LLMClient, quando: datetime,
                   escrever: Callable[[str], None] = print) -> list[Path]: ...
def main(argv: list[str] | None = None) -> None: ...

if __name__ == "__main__":
    main()
```

**Por que um laço próprio, e não `rodar_caso` da avaliação:** `rodar_caso` fixa o `conversa_id` em `eval-<id>`, exige um `Caso` com expectativas, roda `verificar` e não guarda os argumentos das tools. Adaptá-lo mexeria na SPEC-0006 já implementada; o laço daqui tem 8 linhas. Também não reaproveito `Turno` (ele tem `falhas` e `latencia_s`, que aqui não servem, e não tem os argumentos).

**Por que o `GravadorLLM`:** `Resposta.tools_usadas` só tem os nomes. Com os argumentos, o leitor vê **como** o agente consultou (`consultar_pedido(order_id=5, email_ou_telefone="…")`, `consultar_politica(topico="trocas_devolucoes")`), que é o que o desafio quer avaliar (dados × políticas). O embrulho fica em `evals/` e não muda nada em `app/`. Os resultados das tools (JSON) ficam de fora para não poluir a conversa (§8-5).

**`gerar_conversa`:**
1. `gravador = GravadorLLM(llm)`; `agente = criar_agente(config=config, llm=gravador, conexao=conexao, pasta_logs=pasta_logs, agora=roteiro.agora)`. Um agente por conversa, como na avaliação: o prompt e o `ctx.hoje` dependem do `agora` (o `AGENT_TODAY` do `.env` não vale aqui).
2. `historico = []`; `conversa_id = f"exemplo-{roteiro.nome}"`. Para cada `mensagem`: `antes = len(gravador.chamadas)`; `r = agente.responder(historico, mensagem, conversa_id)`; `historico.extend(r.para_historico)`; acrescenta `TurnoExemplo(mensagem, r.texto, gravador.chamadas[antes:], r.status, r.usage, r.custo_usd)`.
3. Devolve os turnos. Status diferente de `ok` não interrompe a conversa (aparece no Markdown e no terminal). Exceções que não sejam `LLMError` (bug) não são capturadas.

Nota: se um turno atingir `MAX_TOOL_ITERATIONS`, as tool calls da última resposta aparecem em `chamadas` mas não foram executadas (o agente para antes). O status `limite_iteracoes` marca esse turno.

**`formatar_chamada`:** `f"{nome}({args})"`, com `args = ", ".join(f"{chave}={json.dumps(valor, ensure_ascii=False)}" for chave, valor in arguments.items())`, na ordem em que o modelo mandou. Ex.: `buscar_produtos(categoria="Violões", preco_max=1000, em_promocao=true)`; sem argumentos, `detalhes_produto()`.

**`citar`:** transforma o texto do Emilio em citação Markdown, preservando listas e negrito: `"\n".join(f"> {linha}" if linha.strip() else ">" for linha in texto.strip().splitlines())`; texto vazio → `">"`.

**`montar_markdown`:** o texto exato abaixo. `{…}` são campos, linhas entre parênteses são regras e não entram no arquivo, e o arquivo termina com `\n`.
````text
# {roteiro.titulo}

{roteiro.descricao}

- **Data simulada:** {DIAS_SEMANA[agora.weekday()]}, {agora:%d/%m/%Y}, {agora:%H:%M} (horário de Campo Grande/MS). {situacao_loja(agora)}
- **Modelo:** {config.provider} · {config.model} · esforço {config.reasoning_effort or "none"}
- **Uso:** {n} turnos · {input} tokens de entrada ({cached} em cache) · {output} de saída · custo estimado {formatar_custo(custo)}
- **Gerado em:** {quando:%d/%m/%Y %H:%M} por `python -m evals.exemplos` (conversa `exemplo-{roteiro.nome}`), sem edição manual

## Conversa

(para cada turno, separados por uma linha em branco:)
**Cliente:** {t.mensagem}

**Emilio:**

{citar(t.texto)}

Ferramentas: {chamadas}{" · status: `" + t.status + "`" se t.status != "ok"}
````
- `chamadas` = `", ".join(f"`{formatar_chamada(c)}`" for c in t.chamadas)`, ou `nenhuma`.
- `input`, `cached`, `output` = somas dos `usage` dos turnos. `custo` = soma de `custo_usd`, `None` se algum for `None`, arredondada em 6 casas. `formatar_custo` vem de `app.cli`.

**`gerar_exemplos`:** cria `pasta_saida` se preciso. Para cada roteiro (`i` a partir de 1, `n = len(roteiros)`): `turnos = gerar_conversa(...)`; grava `montar_markdown(...)` em `pasta_saida / f"{roteiro.nome}.md"` (`encoding="utf-8"`, **sobrescreve**: os arquivos são versionados e o `git diff` mostra o que mudou); `escrever(f"[{i}/{n}] {roteiro.nome}: {len(turnos)} turnos · custo estimado {formatar_custo(custo)}")`, acrescentando `f" · ATENÇÃO: turno(s) {lista} sem status ok"` quando houver (`lista` = números dos turnos, separados por vírgula). No fim: `escrever(f"Total: {turnos} turnos · custo estimado {formatar_custo(total)}")` e devolve os caminhos na ordem.

**`main(argv)`:**
1. `argparse.ArgumentParser(prog="python -m evals.exemplos", description="Gera as conversas de exemplo em examples/ com o agente e o LLM configurados no .env.")`, sem opções (só `--help`). `args = parser.parse_args(argv)`.
2. `configurar_utf8()`.
3. `try: config = carregar_config(); llm = criar_cliente(config.provider, config.model, reasoning_effort=config.reasoning_effort); conexao = abrir_banco(CAMINHO_BANCO)` / `except (LLMError, ValueError) as erro: print(ERRO_INICIO.format(erro=erro), file=sys.stderr); sys.exit(1)`.
4. `with closing(conexao): gerar_exemplos(ROTEIROS, config=config, conexao=conexao, pasta_logs=PASTA_LOGS_EXEMPLOS, pasta_saida=PASTA_EXEMPLOS, llm=llm, quando=datetime.now())`.
5. Termina com código 0, mesmo com turno sem status `ok` (o aviso já saiu no terminal; quem decide é o autor, §8-4).

`carregar_config`, `criar_cliente`, `CAMINHO_BANCO`, `abrir_banco`, `ROTEIROS`, `PASTA_EXEMPLOS` e `PASTA_LOGS_EXEMPLOS` são lidos como globais do módulo na hora da chamada (os testes trocam com `monkeypatch`). Nenhum SDK de provedor é importado (`criar_cliente` importa o adaptador só quando é chamado).

**Logs:** chamadas em `evals/logs/exemplos/llm_calls.jsonl` com `conversa_id = "exemplo-<nome>"` e encaminhamentos em `evals/logs/exemplos/handoffs.jsonl`. Nada se mistura com `logs/` (CLI) nem com `evals/logs/` (avaliação). A pasta própria também deixa o protocolo da conversa 05 limpo: a numeração é por dia e por arquivo (SPEC-0002), então o primeiro encaminhamento gerado para 04/11/2026 é `EM-20261104-0001` (e `-0002`, `-0003`… se o autor regenerar).

**Custo e tempo esperados:** 16 turnos. Com o custo medido de ~US$ 0,00015 por turno (`gpt-6-luna` medium, D05), cerca de **US$ 0,0024** por geração; com o histórico mais longo das conversas de 3 e 4 turnos, até ~US$ 0,005. Tempo: 3,3 s por turno em média (máximo de 9,1 s na avaliação), de 1 a 2 minutos no total.

### 3.4 README final
Português, primeira pessoa e o mesmo tom do DECISIONS (§8-6). O README **resume e linka**: cada decisão aparece em uma ou duas linhas com link para a âncora no DECISIONS, e os números são copiados das fontes abaixo, sem arredondar de outro jeito nem calcular números novos. Seções, nesta ordem (os títulos `##` são exatos, porque o teste da §5 confere):

| Seção | O que entra | Fonte |
| --- | --- | --- |
| Título + abertura | O que é o projeto (2 a 3 frases), sem o aviso "Em construção" | PRD-0001 (Problema, Objetivo) |
| `## Em resumo` | 4 a 6 bullets: agente ReAct com 5 ferramentas (dados × políticas); 25/25 nas 3 rodadas do modelo padrão; ~US$ 0,00015 por turno; memória medida por ablação; link para os exemplos | D03, D05, D09 |
| `## Como rodar` | Requisitos e instalação; `.env` (tabela curta: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_REASONING_EFFORT`, `OPENAI_API_KEY`, `AGENT_TODAY`); conversar (`python -m app.cli [--debug]`, o texto atual da seção "Como conversar com o Emilio"); testes (`pytest`, `ruff check .`); avaliação (`python -m evals.run` e as flags, custo por rodada); gerar exemplos (`python -m evals.exemplos`, custo e tempo da §3.3) | README atual, ARCHITECTURE §3, SPEC-0005, SPEC-0006, esta spec |
| `## Conversas de exemplo` | Tabela com link para cada arquivo de `examples/`, o que ele mostra e as ferramentas usadas; frase dizendo que foram geradas pelo script, com o modelo padrão e sem edição | §3.2 e os arquivos gerados |
| `## Arquitetura` | Diagrama do ARCHITECTURE §1 (simplificado), tabela das ferramentas (D03), layout de pastas resumido e 4 bullets: agente sem estado, cálculos no código (D07), verificação do pedido (D08), provedor trocável (D05). Link para o ARCHITECTURE | ARCHITECTURE §1, §2, §6; D03, D05, D07, D08 |
| `## Decisões técnicas` | Uma linha por decisão (D01 a D18), com link para a âncora | DECISIONS |
| `## Resultados da avaliação` | O que a suíte mede (25 casos, 7 categorias, verificação determinística, sem juiz); tabela da comparação de modelos; ablação da memória (25/25 com memória × 20/25 sem, os 5 casos de várias mensagens falhando no 2º turno, 0 de 5); custo por turno e por rodada; projeção mensal (linha base da D14 e link para os cenários); ressalvas (variância, 25 casos, a taxa mede a suíte); link para `evals/resultados/` | D05, D09, D12, D14, relatórios |
| `## Suposições` | As da D13 que mudam o comportamento (telefone e e-mail oficiais, parcelamento pela §3.1, entrega = previsão, `total_brl` como verdade, promoções por `is_active`, "disponível" = ativo com estoque, nome vale mais que a descrição), fuso UTC−4 e o "agora" configurável | D13, ARCHITECTURE §3 e §8 |
| `## Limitações conhecidas` | A lista abaixo | Esta spec, D09, D13, SPEC-0006 §8 |
| `## Uso de IA` | Resumo da D17 (planejamento com Claude Opus, specs por subagente, implementação com modelos menores e TDD, revisão humana), o histórico de commits que deixa o TDD visível (D16), exemplos e avaliação pela API (D12), e que o próprio README foi redigido com IA e revisado pelo autor | D12, D16, D17, AGENTS.md |
| `## O que ficaria para depois` | Site com API e front (PRD-0002, D10, D15); persistência entre sessões com login (D09); LLM-juiz para tom e `--repeticoes` (SPEC-0006 §8); classificação de intenção com tráfego real (D14); RAG vetorial se o volume crescer (D04); link para o catálogo filtrado (D18); feriados municipais (ARCHITECTURE §8); correções das limitações abaixo | Fontes citadas |
| `## Documentação` | Links para PRDs, specs, DECISIONS, ARCHITECTURE e AGENTS.md (a seção atual, ampliada) | README atual |

**Tabela da comparação de modelos** (copiada da D05, só as colunas Configuração, Versão do código, Rodadas, Acerto, Custo por rodada e Latência), com a frase: "três das rodadas (`…-medium-2`, `…-high-2` e `…-high-3`) foram reconstruídas da saída do terminal, porque rodadas paralelas no mesmo minuto sobrescreveram o arquivo; o resultado, os tokens e o custo são os que o runner imprimiu" (§8-7).

**Limitações conhecidas** (todas entram, com a fonte quando houver):
1. Em consultas de status com a previsão de entrega já vencida, o agente às vezes encaminhou o caso para um atendente em vez de só informar o status, e gravou o e-mail usado na verificação como contato do cliente. Isso contraria a regra 8 do prompt e a D11 (contato só quando o cliente oferece); nenhum caso da suíte confere esse cenário.
2. Se o modelo puser o tipo do produto no termo de busca ("violão giannini gf-3d"), a busca volta vazia e sem `indisponiveis`, porque todas as palavras precisam estar no nome. O agente pode dizer "não temos" para um produto que existe esgotado.
3. Produtos 135 a 144 têm nome e descrição divergentes; o agente confia no nome (D13).
4. A suíte tem 25 casos e verifica por substring: há falsos negativos (ex.: "você ainda pode solicitar a devolução", reprovado no `low`, D05) e verificações fracas (ex.: "não inventar valor de frete"). A taxa de aprovação mede a suíte, não a satisfação de clientes (D12).
5. Sem persistência entre sessões: fechar a CLI apaga a conversa (D09).
6. Site e API fora do escopo; o PRD-0002 é opcional (D10).
7. Feriados municipais de Campo Grande não estão no cálculo do expediente (ARCHITECTURE §8).
8. As que a revisão dos exemplos encontrar (§8-4), com o link para o arquivo.

## 4. Arquivos
- **Criar:** `evals/exemplos.py`, `tests/test_exemplos.py`, `tests/test_readme.py`. `examples/01-…md` a `05-…md` são **gerados** pelo script (passo 4 da §6), nunca escritos à mão.
- **Alterar:** `README.md` (reescrito, §3.4); este arquivo (status e critérios no final); `docs/ARCHITECTURE.md` (na aprovação, §8); remover `scripts/.gitkeep` (a pasta deixa de existir, §8-1).
- **Não alterar:** `app/` inteiro, `evals/run.py`, `evals/avaliacao.py`, `evals/casos.json`, `docs/DECISIONS.md`, `tests/conftest.py`, `pyproject.toml`, `.gitignore` (o padrão `logs/` já ignora `evals/logs/exemplos/`), `.env.example`.

## 5. Testes (escrever ANTES do código)
Comece no *red*. Nenhum teste acessa a rede: LLM sempre `FakeLLM` (`resposta_texto`, `resposta_tool`; cada resposta tem `Usage(10, 5)`). Os exemplos em si usam o LLM real e **não** são testados pelo `pytest`: o que se testa é a parte determinística (roteiros, formatação, gravação, laço com memória e montagem). Se o temp do sistema der `PermissionError`, rode `pytest --basetemp=<pasta sua, fora do repositório>`.

### `tests/test_exemplos.py`
**Helpers** (usam as fixtures `conexao` e `banco` do `conftest.py`):
```python
CFG = Config(provider="fake", model="fake")
CFG_LUNA = Config(provider="openai", model="gpt-6-luna", reasoning_effort="medium")
AGORA = datetime(2026, 11, 3, 10, 0)

def roteiro(nome="01-teste", mensagens=("Quanto custa o Takamine GD20?", "E no PIX?"), agora=AGORA) -> Roteiro:
    return Roteiro(nome, "Preço e PIX", "Mostra preço e memória.", agora, tuple(mensagens))

def linhas(arquivo) -> list[dict]:   # json.loads de cada linha ([] se não existe)
```

**Roteiros (`ROTEIROS` real)**
- [x] `3 <= len(ROTEIROS) <= 5`; os nomes são únicos, casam com `r"\d{2}-[a-z0-9-]+"` e são numerados em sequência a partir de `01` (`[r.nome[:2] for r in ROTEIROS] == ["01", "02", …]`).
- [x] Todo roteiro tem `titulo` e `descricao` não vazios e pelo menos 2 mensagens (todos mostram memória); toda mensagem é não vazia depois de `strip()`, não tem `"\n"` e tem no máximo `Config().max_message_chars` caracteres (nenhuma é recusada sem chamar o LLM).
- [x] Horário coberto: pelo menos um roteiro com `situacao_loja(r.agora)` começando em `"A loja está fechada"` e um com `"A loja está aberta"`.

**Formatação**
- [x] `formatar_chamada(ToolCall("c1", "buscar_produtos", {"categoria": "Violões", "preco_max": 1000, "em_promocao": True})) == 'buscar_produtos(categoria="Violões", preco_max=1000, em_promocao=true)'`; `formatar_chamada(ToolCall("c2", "detalhes_produto", {})) == "detalhes_produto()"`.
- [x] `citar("Custa R$ 2.199,00.\n\nNo PIX:\n- R$ 2.089,05\n") == "> Custa R$ 2.199,00.\n>\n> No PIX:\n> - R$ 2.089,05"`; `citar("") == ">"`.
- [x] `montar_markdown` exato: com `roteiro()`, `CFG_LUNA`, `quando=datetime(2026, 11, 3, 18, 5)` e os turnos `TurnoExemplo("Quanto custa o Takamine GD20?", "Custa R$ 2.199,00.\n\nNo PIX, R$ 2.089,05.", [ToolCall("c1", "buscar_produtos", {"termo": "takamine gd20"})], "ok", Usage(1000, 100, 800), 0.0001)` e `TurnoExemplo("E no PIX?", "R$ 2.089,05.", [], "ok", Usage(1200, 50, 1000), 0.00005)`, o resultado é **igual** a:
  ````text
  # Preço e PIX

  Mostra preço e memória.

  - **Data simulada:** terça-feira, 03/11/2026, 10:00 (horário de Campo Grande/MS). A loja está aberta agora, até as 18h.
  - **Modelo:** openai · gpt-6-luna · esforço medium
  - **Uso:** 2 turnos · 2200 tokens de entrada (1800 em cache) · 150 de saída · custo estimado US$ 0.000150
  - **Gerado em:** 03/11/2026 18:05 por `python -m evals.exemplos` (conversa `exemplo-01-teste`), sem edição manual

  ## Conversa

  **Cliente:** Quanto custa o Takamine GD20?

  **Emilio:**

  > Custa R$ 2.199,00.
  >
  > No PIX, R$ 2.089,05.

  Ferramentas: `buscar_produtos(termo="takamine gd20")`

  **Cliente:** E no PIX?

  **Emilio:**

  > R$ 2.089,05.

  Ferramentas: nenhuma
  ````
  (com `\n` no final).
- [x] Variações: duas chamadas no mesmo turno → `` "Ferramentas: `consultar_pedido(order_id=5, email_ou_telefone=\"a@b.com\")`, `consultar_politica(topico=\"trocas_devolucoes\")`" ``; turno com status `"erro_llm"` e sem chamadas → `"Ferramentas: nenhuma · status: `erro_llm`"`; um turno com `custo_usd=None` → `"custo estimado n/d"`; `Config(reasoning_effort=None)` → `"esforço none"`; `agora=datetime(2026, 11, 8, 15, 0)` → `"domingo, 08/11/2026, 15:00 (horário de Campo Grande/MS). A loja está fechada agora. A equipe volta amanhã, segunda-feira (09/11), às 9h."`.

**`gerar_conversa` (sem rede)**
- [x] Memória e chamadas: roteiro padrão, `llm = FakeLLM([resposta_tool("buscar_produtos", termo="takamine gd20"), resposta_texto("Custa R$ 2.199,00."), resposta_texto("No PIX, R$ 2.089,05.")])`, `pasta_logs=tmp_path / "logs"` → 2 turnos; `turnos[0].chamadas == [ToolCall("call_buscar_produtos", "buscar_produtos", {"termo": "takamine gd20"})]`; `turnos[1].chamadas == []`; `turnos[0].usage == Usage(20, 10)` (duas chamadas no turno); `turnos[0].custo_usd is None` (modelo `fake` sem preço); `turnos[1].texto == "No PIX, R$ 2.089,05."`; `llm.chamadas[2]["messages"] == [Message("user", "Quanto custa o Takamine GD20?"), Message("assistant", "Custa R$ 2.199,00."), Message("user", "E no PIX?")]`.
- [x] `agora` do roteiro chega ao prompt e às tools: `roteiro(mensagens=("quero falar com alguém", "ok"), agora=datetime(2026, 11, 8, 15, 0))`, roteiro do LLM `[resposta_tool("encaminhar_atendente", motivo="pedido_do_cliente", resumo="quer falar com uma pessoa"), resposta_texto("Protocolo gerado."), resposta_texto("De nada!")]` → `"domingo, 08/11/2026 (2026-11-08), 15:00" in llm.chamadas[0]["system"]`; `linhas(tmp_path / "logs" / "handoffs.jsonl")` tem 1 linha com `protocolo` começando em `"EM-20261108-"` e `conversa_id == "exemplo-01-teste"`.
- [x] Logs na pasta indicada: no cenário do teste "Memória e chamadas", `linhas(tmp_path / "logs" / "llm_calls.jsonl")` tem 3 linhas, todas com `conversa_id == "exemplo-01-teste"`, e `turno` `[1, 1, 2]`.
- [x] Erro do provedor não interrompe: `FakeLLM([])` → 2 turnos, os dois com `status == "erro_llm"`.

**`gerar_exemplos`**
- [x] Grava e sobrescreve: `pasta = tmp_path / "ex"`, com `pasta / "01-a.md"` já contendo `"velho"`; roteiros `[roteiro("01-a", ("oi", "tchau")), roteiro("02-b", ("oi", "tchau"))]`, `FakeLLM([resposta_texto("Olá!")] * 4)`, `saida = []`, `escrever=saida.append` → devolve `[pasta / "01-a.md", pasta / "02-b.md"]`; os dois começam com `"# Preço e PIX\n"`; `"velho"` não está mais em `01-a.md`; `saida == ["[1/2] 01-a: 2 turnos · custo estimado n/d", "[2/2] 02-b: 2 turnos · custo estimado n/d", "Total: 4 turnos · custo estimado n/d"]`.
- [x] Aviso de status: um roteiro de 2 mensagens com `FakeLLM([resposta_texto("Olá!")])` (o 2º turno vira `erro_llm`) → o arquivo é gravado, contém `"status: `erro_llm`"`, e `saida[0]` termina em `" · ATENÇÃO: turno(s) 2 sem status ok"`.
- [x] Custo somado com preço conhecido: `config=Config(provider="openai", model="gpt-5.4-mini")`, um roteiro de 2 mensagens e `FakeLLM([resposta_texto("a"), resposta_texto("b")])` → `saida[0] == "[1/1] 01-teste: 2 turnos · custo estimado US$ 0.000060"` e o arquivo contém `"custo estimado US$ 0.000060"`.

**`main`**
- [x] Ponta a ponta (sem rede): `monkeypatch` de `evals.exemplos.carregar_config` (→ `CFG`), `evals.exemplos.criar_cliente` (guarda os argumentos e devolve `FakeLLM([resposta_texto("Aqui é o Emilio.")] * total)`, com `total = sum(len(r.mensagens) for r in ROTEIROS)`), `evals.exemplos.CAMINHO_BANCO` (→ `banco`), `evals.exemplos.PASTA_EXEMPLOS` (→ `tmp_path / "ex"`) e `evals.exemplos.PASTA_LOGS_EXEMPLOS` (→ `tmp_path / "logs"`). `main([])` → `criar_cliente` recebeu `("fake", "fake")`; os arquivos de `tmp_path / "ex"` são exatamente `{f"{r.nome}.md" for r in ROTEIROS}`; os `conversa_id` de `tmp_path / "logs" / "llm_calls.jsonl"` são exatamente `{f"exemplo-{r.nome}" for r in ROTEIROS}`; `capsys.readouterr().out` contém `"Total: "` e `f"[{len(ROTEIROS)}/{len(ROTEIROS)}]"`.
- [x] Erro de inicialização (parametrizado: `criar_cliente` levanta `LLMError("defina OPENAI_API_KEY no .env")`; `carregar_config` levanta `ValueError("LLM_REASONING_EFFORT: valores válidos: none, low, medium, high")`) → `SystemExit` com `code == 1`; o stderr contém `"Não consegui gerar os exemplos"` e a mensagem, e não contém `"Traceback"`; `tmp_path / "ex"` não existe ou está vazia.
- [x] `subprocess.run([sys.executable, "-m", "evals.exemplos", "--help"], cwd=<raiz do repo>, capture_output=True, text=True, encoding="utf-8")` → `returncode == 0` e `"examples/"` no stdout.
- [x] Isolamento: `subprocess.run([sys.executable, "-c", "import sys, evals.exemplos; assert not any(m in sys.modules for m in ('openai', 'anthropic', 'google.genai'))"], cwd=<raiz do repo>, check=True)`.

### `tests/test_readme.py`
Por que testar um README: o teste não confere texto, só a estrutura que o desafio cobra e os links. Link quebrado (um relatório renomeado, um exemplo regenerado com outro nome) é o erro mais provável num README que aponta para dezenas de arquivos, e é barato de pegar. Três testes, sem rede:
- [x] Seções obrigatórias: cada um destes títulos aparece como linha inteira no `README.md`: `## Em resumo`, `## Como rodar`, `## Conversas de exemplo`, `## Arquitetura`, `## Decisões técnicas`, `## Resultados da avaliação`, `## Suposições`, `## Limitações conhecidas`, `## Uso de IA`, `## O que ficaria para depois`, `## Documentação`. E `"Em construção"` não aparece.
- [x] Links relativos existem: para cada alvo de `re.findall(r"\]\(([^)\s]+)\)", texto)` que não começa com `http://`, `https://`, `mailto:` nem `#`, o caminho sem a âncora (`alvo.split("#")[0]`) existe a partir da raiz do repositório.
- [x] Todos os exemplos estão no README: os arquivos `examples/*.md` são de 3 a 5 e cada um aparece como alvo de link (`examples/<nome>.md`).

**Fixtures/mocks:** `conexao` e `banco` do `conftest.py`, `tmp_path`, `FakeLLM`, `monkeypatch`, `capsys`. `<raiz do repo>` = `Path(__file__).resolve().parents[1]`.

## 6. Plano
Commits seguindo o ciclo da spec (AGENTS.md, D16; escopo `evals` para o script). Antes de cada commit: `pytest` e `ruff check .` verdes, exceto nos `test(...)`, em que só os testes novos falham.
1. `docs(spec): SPEC-0007 exemplos e README` (esta spec, depois de aprovada, com as mudanças da §8 no ARCHITECTURE e sem `scripts/.gitkeep`).
2. `tests/test_exemplos.py` *red* → `test(evals): roteiros, formatação e geração das conversas de exemplo`.
3. `evals/exemplos.py` até ficar verde → `feat(evals): gerador das conversas de exemplo`.
4. **Autor, API real (~US$ 0,003):** `python -m evals.exemplos`; ler cada arquivo contra a tabela da §3.2 e aplicar a regra da §8-4 → `docs(examples): conversas de exemplo geradas com gpt-6-luna medium`.
5. `tests/test_readme.py` *red* (o README atual não tem as seções) → `test(readme): seções obrigatórias e links`.
6. README final (§3.4) até ficar verde; marcar os critérios da §7; status **implementada** → `docs(readme): README final com como rodar, decisões, resultados, limitações e uso de IA`.

## 7. Critérios de aceite
- [x] [AC-01] `python -m evals.exemplos` gera os 5 arquivos da §3.2 em `examples/`, um agente por conversa com o `agora` do roteiro, `conversa_id` `exemplo-<nome>` e logs e encaminhamentos em `evals/logs/exemplos/` (nada novo em `logs/` nem em `evals/logs/llm_calls.jsonl`).
- [x] [AC-02] Cada arquivo segue o formato da §3.3: título, descrição, data simulada com a situação da loja, modelo e esforço, tokens e custo estimado (`n/d` sem preço), data de geração e, por turno, a mensagem do cliente, a resposta do Emilio citada e as ferramentas com os argumentos (ou `nenhuma`), com o status marcado quando não for `ok`.
- [x] [AC-03] A memória funciona como na CLI: cada turno recebe o histórico anterior (`para_historico`).
- [x] [AC-04] Erro de configuração sai com código 1 e `ERRO_INICIO`, sem traceback; turno sem status `ok` gera aviso no terminal; importar `evals.exemplos` não carrega SDK de provedor; nenhuma dependência nova; nenhum teste usa a rede.
- [x] [AC-05] `examples/` versionada com as 5 conversas geradas pelo modelo padrão, sem edição manual, revisadas pelo autor contra a tabela da §3.2; juntas, cobrem os critérios de sucesso 1 a 6 do PRD.
- [x] [AC-06] README com as seções da §3.4, na ordem; números iguais aos da D05, D09 e D14 e dos relatórios; decisões resumidas com link para o DECISIONS; nenhum link relativo quebrado; todos os exemplos linkados.
- [x] [AC-07] "Limitações conhecidas" com os itens 1 a 7 da §3.4 e o que a revisão dos exemplos encontrar.
- [x] [AC-08] ARCHITECTURE atualizado (§8) e `scripts/` removida.
- [x] [AC-TESTES] `pytest` verde, sem rede.
- [x] [AC-LINT] `ruff check .` verde.
- **Evidências da implementação (03/11/2026):** testes escritos antes do gerador (red por módulo ausente) e antes do README (red por seções e exemplos ausentes). A geração real foi executada uma única vez com `openai`, `gpt-6-luna`, esforço `medium`, sem edição do `.env` ou das respostas: 5 arquivos, 16 turnos com status `ok`, 29 chamadas ao LLM, custo estimado total US$ 0,003776; logs isolados e ignorados pelo Git. Na revisão assistida, o exemplo 02 informa “há 4 dias”, sem explicitar 18/01/2026, e pede desculpa por ambiguidade inexistente; observações preservadas e documentadas no README. O autor aprovou a entrega após a revisão assistida e solicitou o commit de finalização, encerrando o AC-05. A visualização do Markdown e a reprodução em clone limpo não foram executadas nesta sessão.
- **Verificação manual (autor, API real, ~US$ 0,003):** com a chave no `.env` e o modelo padrão:
  1. `python -m evals.exemplos` → 5 linhas `[i/5] …` sem `ATENÇÃO` e `Total: 16 turnos · custo estimado US$ 0.00…`.
  2. Ler os 5 arquivos contra a tabela da §3.2 (ferramentas e fatos de cada turno).
  3. `evals/logs/exemplos/llm_calls.jsonl` com `conversa_id` `exemplo-…`; o custo somado bate com o dos cabeçalhos; `git status` mostra só `examples/` (os logs ficam ignorados).
  4. Abrir o README no GitHub (ou num visualizador de Markdown): tabelas renderizadas, links e âncoras do DECISIONS funcionando, citações dos exemplos legíveis.
  5. Seguir o "Como rodar" num clone limpo: `pip install -e ".[dev]"`, `.env`, `python -m app.cli`, `pytest`.

## 8. Riscos e pontos em aberto

**Decisões do autor (resolvidas na aprovação, 2026-11-03):** as 10 aprovadas como recomendado abaixo. As mudanças no ARCHITECTURE do fim desta seção foram aplicadas e `scripts/` foi removida.
1. **Onde fica o script.** *Recomendação:* `evals/exemplos.py` (`python -m evals.exemplos`), porque o AGENTS.md só permite chamadas reais em `evals/` e o script reaproveita o mesmo jeito de rodar da avaliação; remover `scripts/.gitkeep`. *Alternativa:* `scripts/gerar_exemplos.py`, como diz o ARCHITECTURE §2 hoje, abrindo uma exceção no AGENTS.md e ajustando o `sys.path`.
2. **Reaproveitar o runner da avaliação.** *Recomendação:* laço próprio de 8 linhas e um `TurnoExemplo` (§3.3), sem tocar na SPEC-0006: `rodar_caso` fixa o `conversa_id` `eval-`, exige expectativas e não guarda argumentos. *Alternativa:* generalizar `rodar_caso` com um prefixo de `conversa_id` e `espera` opcional, e montar os exemplos a partir de `ResultadoCaso` (menos código novo, mas mexe numa spec implementada e mistura dois propósitos).
3. **Conversas fixas no repositório ou regeneradas.** *Recomendação:* fixas e versionadas (são o entregável), geradas uma vez com o modelo padrão e só regeneradas, **todas juntas**, quando o prompt ou as tools mudarem, num commit `docs(examples)` que diga o motivo. *Alternativa:* regenerar a cada mudança relevante do código, aceitando que os textos mudem a cada vez.
4. **O que fazer se um exemplo mostrar uma resposta errada.** *Recomendação:* não escolher a dedo. Gerar uma vez; se uma resposta estiver errada, manter o arquivo e registrar o erro em "Limitações conhecidas" com link para ele (é evidência honesta, coerente com a D12: "nunca afrouxo uma verificação para esconder um erro real"). Se o erro for grave e o autor corrigir o agente num `fix:` separado, regenerar as 5. *Alternativa:* regenerar até sair uma versão boa e dizer no README quantas tentativas foram (mais bonito, menos honesto).
5. **Mostrar os argumentos das ferramentas.** *Recomendação:* sim, via `GravadorLLM` (§3.3); é o que mostra *como* o agente consulta dados e políticas. *Alternativa:* só os nomes, como a CLI (`[ferramentas: buscar_produtos]`), sem o embrulho. Uma terceira opção, mostrar também um resumo do resultado de cada tool (ex.: `total` e ids de `indisponiveis`), ficou de fora por poluir a conversa.
6. **Idioma e tom do README.** *Recomendação:* português, em primeira pessoa e no tom do DECISIONS (o desafio, os dados e o agente são em português). *Alternativa:* inglês, por ser repositório público, ou um resumo curto em inglês no topo.
7. **Relatórios `-2`/`-3` reconstruídos como evidência.** *Recomendação:* mantê-los e citá-los, com a nota da §3.4: o cabeçalho de cada um já diz que foi reconstruído, e resultado, tokens e custo vêm da saída do runner. *Alternativa:* rodar de novo as três rodadas (~US$ 0,015, agora sem risco de sobrescrever) e trocar os números na D05 e no README; os reconstruídos ficariam só como histórico.
8. **Logs em pasta própria.** *Recomendação:* `evals/logs/exemplos/` (protocolo limpo na conversa 05 e custo da geração separado do da avaliação). *Alternativa:* `evals/logs/`, distinguindo pelo prefixo `exemplo-` (o protocolo da conversa 05 sairia com o número seguinte aos encaminhamentos da avaliação naquele dia).
9. **Valor da parcela calculado pelo modelo.** No T3 da conversa 01, o Emilio pode escrever "12x de R$ 183,25", uma conta que nenhuma tool faz (D07 e regra 3 do prompt). *Recomendação:* se acontecer, tratar pela regra do item 4 (limitação no README); calcular parcelas em `app/precos.py` seria escopo novo. *Alternativa:* trocar a mensagem por uma pergunta que não convide à conta ("Quais as formas de pagamento?"), perdendo um pouco de naturalidade.
10. **Teste do README.** *Recomendação:* os 3 testes da §5 (seções, links, exemplos linkados), sem conferir texto. *Alternativa:* nenhum teste, só a verificação manual.

**Riscos (mitigação):**
- **Respostas variam a cada geração:** o LLM não é determinístico; os exemplos são uma amostra, não a prova (a prova é a suíte, D12). O cabeçalho registra modelo, esforço e data de geração.
- **Datas simuladas × data real:** os pedidos são de 2026 e a conversa 02 se passa em 22/01/2026; o cabeçalho "Data simulada" deixa isso explícito para o leitor.
- **Dados pessoais nos exemplos:** só os dados fictícios dos CSVs (ex.: `rafael.pereira@jmail.com`), os mesmos que já estão em `data/raw/`.
- **README desatualizado depois:** os números vêm do DECISIONS; se a D05 mudar, o README muda junto. O teste de links pega arquivo renomeado, mas não âncora quebrada (verificação manual 4).
- **Busca vazia por causa do termo (limitação 2):** os roteiros dos indisponíveis evitam o tipo junto do modelo, mas o modelo pode acrescentá-lo por conta própria; aí vale o item 4.

**Mudanças no ARCHITECTURE (aplicar na aprovação):**
1. **§2 Layout:** trocar a linha `scripts/gerar_exemplos.py` por, dentro de `evals/`:
   ```
     exemplos.py           # python -m evals.exemplos: gera examples/ com o agente real (SPEC-0007)
     logs/exemplos/        # llm_calls.jsonl e handoffs.jsonl da geração dos exemplos (fora do git)
   ```
2. **§10 Avaliação:** acrescentar no fim: "`python -m evals.exemplos` roda os 5 roteiros de `evals/exemplos.py` com o agente real (um agente por conversa, com o `agora` do roteiro, `conversa_id` `exemplo-<nome>`, logs em `evals/logs/exemplos/`) e grava `examples/<nome>.md` com as mensagens, as respostas, as ferramentas chamadas com os argumentos, tokens e custo. Contrato: [SPEC-0007](specs/SPEC-0007-exemplos-readme.md)."
3. **§11 Testes:** acrescentar "O gerador de exemplos é testado com `FakeLLM` em `tests/test_exemplos.py`; `tests/test_readme.py` confere as seções obrigatórias e os links do README."
