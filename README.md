# Empório da Música — Agente de Atendimento

Construí um agente de atendimento por texto, em Python, para a Empório da Música, loja fictícia de instrumentos em Campo Grande/MS. O Emilio consulta catálogo, estoque, promoções, pedidos e políticas, mantém o contexto da conversa e encaminha para uma pessoa quando precisa. Este é o protótipo do desafio técnico AI Engineer da Artefact.

## Em resumo

- Loop ReAct próprio com cinco ferramentas: dados no SQLite, políticas por tópico e encaminhamento local ([D03](docs/DECISIONS.md#d03--abordagem-do-agente-react-via-function-calling)).
- O padrão `gpt-6-luna` medium aprovou 25/25 casos nas três rodadas da versão final ([D05](docs/DECISIONS.md#d05--modelo-e-provedor-openai-com-o-código-preparado-para-outros)).
- Custo medido de cerca de US$ 0,00015 por turno, estimado pela tabela de preços do projeto ([D05](docs/DECISIONS.md#d05--modelo-e-provedor-openai-com-o-código-preparado-para-outros)).
- Memória medida por ablação: 25/25 com histórico e 20/25 sem; os cinco casos de várias mensagens falharam sem histórico ([relatório](evals/resultados/20261103-1616-gpt-6-luna-medium-sem-memoria.md)).
- Cinco [conversas de exemplo](#conversas-de-exemplo) mostram ferramentas, argumentos, tokens e custo do mesmo agente usado na CLI.

## Como rodar

Requer Python 3.12+ e uma chave de API do provedor escolhido. A interface oficial é um chat no terminal; o mesmo agente também responde por uma [API HTTP](#api-http) para o site. O banco é criado dos dados versionados.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (Linux/macOS: source .venv/bin/activate)
pip install -e ".[dev]"
cp .env.example .env          # Windows (cmd): copy .env.example .env
```

Preencha a chave no `.env`. O ambiente do processo prevalece sobre o arquivo; valor vazio usa o padrão.

| Variável | Padrão | Para que serve |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | `openai`, `anthropic` ou `gemini` |
| `LLM_MODEL` | `gpt-6-luna` | Modelo do provedor |
| `LLM_REASONING_EFFORT` | `medium` | `none`, `low`, `medium`, `high`; usado pelo adaptador OpenAI |
| `OPENAI_API_KEY` | — | Chave OpenAI; nos outros provedores, `ANTHROPIC_API_KEY` ou `GEMINI_API_KEY` |
| `AGENT_TODAY` | Agora em UTC−4 | Data simulada `AAAA-MM-DD` (10h) ou `AAAA-MM-DDTHH:MM` |

```bash
python -m app.cli             # ou: python -m app.cli --debug
```

- Na primeira execução, o banco `data/emporio.db` é criado a partir dos CSVs. Para recriar: `python -m app.ingest`.
- Cada resposta mostra as ferramentas consultadas, por exemplo `[ferramentas: buscar_produtos]`. Com `--debug`, também mostra tokens e custo por resposta.
- `/nova` começa outra conversa; `sair`, `/sair` ou Ctrl+C encerram.
- Para Anthropic ou Gemini, instale o extra antes: `pip install -e ".[anthropic]"` ou `pip install -e ".[gemini]"`.

### API HTTP

A API não guarda estado: o site envia a mensagem com o histórico e recebe a resposta e o trecho a acrescentar ao histórico ([SPEC-0008](docs/specs/SPEC-0008-api-http.md), [D10](docs/DECISIONS.md#d10--interface-cli)).

```bash
python -m uvicorn api.index:app --reload   # documentação interativa em http://localhost:8000/docs
```

```json
POST /chat
{"mensagem": "E em quantas vezes posso parcelar?", "historico": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}], "conversa_id": "site-1"}
→ {"resposta": "...", "ferramentas": ["consultar_politica"], "status": "ok", "conversa_id": "site-1", "historico": [...], "uso": {...}}
```

- `GET /health` confere se está no ar. Com `API_TOKEN` no ambiente, `/chat` exige `Authorization: Bearer <token>`; `CORS_ORIGINS` libera chamadas diretas do navegador.
- Na Vercel, o preset Python encontra `api/index.py` sem `vercel.json`. O banco é criado em `/tmp` na primeira requisição, e logs e protocolos de encaminhamento ficam em `/tmp`, que não persiste.
- Endpoint público gasta a chave: use `API_TOKEN`, limite de gasto no provedor e rate-limit no firewall da hospedagem ([D15](docs/DECISIONS.md#d15--publicação-se-houver-front)).

Testes unitários usam `FakeLLM`, sem rede nem custo:

```bash
pytest
ruff check .
```

A avaliação usa a API real e grava relatórios em [evals/resultados/](evals/resultados/). Uma rodada completa tem 25 casos e 30 turnos; com o padrão, custou US$ 0,0039 a 0,0051 nas três rodadas da versão final.

```bash
python -m evals.run
python -m evals.run --sem-memoria
python -m evals.run --casos produtos-violoes-ate-1000
python -m evals.run --provedor openai --modelo gpt-6-luna --esforco high
```

`--sem-memoria` envia histórico vazio; `--casos` recebe IDs separados por vírgula e produz relatório parcial. `--provedor`, `--modelo` e `--esforco` comparam configurações sem editar o `.env`. Os IDs estão em [evals/casos.json](evals/casos.json).

```bash
python -m evals.exemplos
```

O gerador usa o modelo configurado, com datas simuladas próprias, e sobrescreve os cinco arquivos de [examples/](examples/). Com `gpt-6-luna` medium, a estimativa é de US$ 0,0024 a 0,005 para 16 turnos, em 1 a 2 minutos. Os logs ficam em `evals/logs/exemplos/`, separados da CLI (`logs/`) e da avaliação (`evals/logs/`). Regenero todas as conversas juntas quando o agente mudar; preservo respostas incorretas como evidência e documento as limitações.

## Conversas de exemplo

Gerei estas conversas uma única vez com `python -m evals.exemplos`, usando o padrão `gpt-6-luna` medium, sem editar as respostas. Foram 16 turnos, sem status de erro, com custo estimado total de US$ 0,003776. O autor aprovou os exemplos após a revisão assistida, mantendo as observações documentadas abaixo.

| Conversa | O que mostra | Ferramentas usadas |
| --- | --- | --- |
| [01 — Preço, PIX e parcelamento](examples/01-preco-pix-parcelamento.md) | Preço do Takamine, memória e política de pagamento | `buscar_produtos`, `consultar_politica` |
| [02 — Arrependimento dentro do prazo](examples/02-arrependimento-no-prazo.md) | Verificação do pedido, prazo, frete e reembolso | `consultar_pedido`, `consultar_politica` |
| [03 — Catálogo e indisponíveis](examples/03-catalogo-e-indisponiveis.md) | Faixa de preço, esgotado, descontinuado e pré-lançamento | `buscar_produtos` |
| [04 — Fora do escopo e domingo](examples/04-fora-do-escopo.md) | Acessórios, futebol, retorno da equipe e promoções | `buscar_produtos` |
| [05 — Atendente humano](examples/05-atendente-humano.md) | Uma tentativa de ajuda, encaminhamento e endereço | `encaminhar_atendente` |

Os cabeçalhos distinguem a data simulada do atendimento da data real de geração. Os dados pessoais citados são fictícios e vêm dos CSVs do desafio.

## Arquitetura

```text
Cliente → CLI | API HTTP → Agente.responder(histórico, mensagem)
                 ├─ LLMClient → OpenAI | Anthropic | Gemini | FakeLLM
                 ├─ ferramentas → SQLite (somente leitura) / políticas por tópico
                 └─ logs de chamadas e encaminhamentos
```

| Ferramenta | Quando usa | Fonte |
| --- | --- | --- |
| `buscar_produtos` | Preço, disponibilidade, catálogo e promoções | SQLite |
| `detalhes_produto` | Especificações e descrição de um instrumento | SQLite |
| `consultar_pedido` | Status, rastreio e previsão, com verificação do cliente | SQLite |
| `consultar_politica` | Horários, pagamento, troca, frete, garantia e privacidade | `data/politicas.md` |
| `encaminhar_atendente` | Reclamação, defeito, exclusão de dados ou insistência por pessoa | Registro local e protocolo |

```text
app/              agente, ferramentas, preços, configuração, CLI e adaptadores LLM
data/raw/         dados originais, somente leitura
data/politicas.md manual convertido e revisado
tests/            testes determinísticos com FakeLLM
evals/            avaliação real e gerador de exemplos
evals/resultados/ relatórios versionados
examples/         conversas geradas
docs/             PRD, specs, arquitetura e decisões
```

- O agente não guarda estado: a CLI mantém uma lista e envia as últimas 20 mensagens. O loop tem limite padrão de cinco chamadas ao LLM por turno ([D03](docs/DECISIONS.md#d03--abordagem-do-agente-react-via-function-calling), [D09](docs/DECISIONS.md#d09--memória-da-conversa-sim-persistência-do-histórico-não)).
- Preço, promoção e PIX são calculados no código, em `app/precos.py` ([D07](docs/DECISIONS.md#d07--cálculos-feitos-no-código-não-pelo-llm)).
- Pedido exige número e e-mail ou telefone; erro genérico protege a existência do pedido ([D08](docs/DECISIONS.md#d08--consulta-de-pedido-exige-verificação-lgpd)).
- A interface `LLMClient` permite trocar o provedor; SDKs ficam nos adaptadores ([D05](docs/DECISIONS.md#d05--modelo-e-provedor-openai-com-o-código-preparado-para-outros)).

Os contratos completos estão em [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Decisões técnicas

As justificativas e alternativas descartadas estão no [documento de decisões](docs/DECISIONS.md):

| Decisão | Resumo |
| --- | --- |
| [D01 — Python e ferramental](docs/DECISIONS.md#d01--python-e-ferramental) | Python 3.12 e `pyproject.toml`, instalação com pip ou uv. |
| [D02 — SQLite](docs/DECISIONS.md#d02--banco-de-dados-sqlite) | Dados relacionais pequenos, sem servidor nem dependência adicional. |
| [D03 — ReAct](docs/DECISIONS.md#d03--abordagem-do-agente-react-via-function-calling) | Loop próprio com function calling e cinco ferramentas, sem framework de agente. |
| [D04 — RAG por tópico](docs/DECISIONS.md#d04--políticas-rag-sem-vetores) | Recupero seções inteiras do manual; vetores não se justificam neste volume. |
| [D05 — Modelo e provedor](docs/DECISIONS.md#d05--modelo-e-provedor-openai-com-o-código-preparado-para-outros) | `gpt-6-luna` medium pelo equilíbrio medido entre acerto, custo e latência. |
| [D06 — Persona e prompt](docs/DECISIONS.md#d06--persona-e-estratégia-de-prompt) | Emilio segue o tom e as regras do manual, com data e expediente no prompt. |
| [D07 — Cálculos no código](docs/DECISIONS.md#d07--cálculos-feitos-no-código-não-pelo-llm) | Promoções e PIX já chegam calculados pelas ferramentas. |
| [D08 — Verificação do pedido](docs/DECISIONS.md#d08--consulta-de-pedido-exige-verificação-lgpd) | Número e e-mail ou telefone obrigatórios para consultar dados. |
| [D09 — Memória](docs/DECISIONS.md#d09--memória-da-conversa-sim-persistência-do-histórico-não) | Contexto durante a sessão, sem persistência entre sessões. |
| [D10 — CLI](docs/DECISIONS.md#d10--interface-cli) | Interface suficiente para executar e avaliar o agente; site opcional. |
| [D11 — Atendente](docs/DECISIONS.md#d11--encaminhamento-para-atendente-humano) | Tenta ajudar uma vez e encaminha diante de insistência; registra protocolo local. |
| [D12 — Avaliação](docs/DECISIONS.md#d12--testes-e-avaliação) | TDD com FakeLLM e suíte real de critérios objetivos, sem LLM-juiz. |
| [D13 — Dados](docs/DECISIONS.md#d13--tratamento-dos-dados-e-suposições) | Inconsistências preservadas e suposições explícitas. |
| [D14 — Custo e observabilidade](docs/DECISIONS.md#d14--custo-e-observabilidade) | Tokens, custo estimado, latência e ferramentas por chamada. |
| [D15 — Publicação](docs/DECISIONS.md#d15--publicação-se-houver-front) | Se houver site: chave no backend, limite de gasto no provedor e rate-limit. |
| [D16 — Repositório](docs/DECISIONS.md#d16--repositório) | Histórico separado em spec, teste red, implementação green e ajustes. |
| [D17 — Uso de IA](docs/DECISIONS.md#d17--uso-de-assistentes-de-código) | Modelo por tarefa, specs aprovadas e revisão humana antes dos commits. |
| [D18 — Catálogo filtrado](docs/DECISIONS.md#d18--link-para-catálogo-filtrado-possível-site) | Futuro link com filtros, condicionado à existência do site. |

## Resultados da avaliação

A suíte tem 25 casos em sete categorias: produtos, pedidos, políticas, escopo e segurança, encaminhamento, horário e memória. São 30 turnos, com cinco casos de várias mensagens. A verificação é determinística: ferramentas chamadas e substrings normalizadas de fatos esperados ou proibidos; não há LLM-juiz ([D12](docs/DECISIONS.md#d12--testes-e-avaliação), [contrato](docs/specs/SPEC-0006-avaliacao.md)).

Comparação de 03/11/2026, copiada da [D05](docs/DECISIONS.md#d05--modelo-e-provedor-openai-com-o-código-preparado-para-outros):

| Configuração | Versão do código | Rodadas | Acerto | Custo por rodada | Latência média / máxima por turno |
| --- | --- | ---: | --- | ---: | ---: |
| **`gpt-6-luna` medium** | final | 3 | **25/25 nas 3** | US$ 0,0039 a 0,0051 (média 0,0046) | 3,3 s / 9,1 s |
| `gpt-6-luna` high | final | 3 | 25/25 nas 3 | US$ 0,0051 a 0,0060 (média 0,0055) | 3,8 s / 14,7 s |
| `gpt-6-luna` low | final | 3 | 25/25, 25/25 e 24/25 | US$ 0,0036 a 0,0045 (média 0,0041) | 2,9 s / 7,0 s |
| `gpt-6-luna` medium | antes das correções | 1 | 21/25 | US$ 0,0062 | 4,0 s / 8,1 s |
| `gpt-6-luna` high | antes / com parte das correções | 2 | 22/25 e 23/25 | US$ 0,0067 e 0,0068 | 4,6 s / 10,9 s |
| `gpt-5.4-mini` sem raciocínio | antes das correções | 1 | 16/25 | US$ 0,0387 | 2,7 s / 6,9 s |
| `gemini-3.5-flash-lite` | antes das correções | 1 | 18/25 | US$ 0,0515 (estimado; usei a chave gratuita) | 40,2 s / 107,9 s |

As três rodadas do padrão estão nos relatórios [medium 1](evals/resultados/20261103-1553-gpt-6-luna-medium.md), [medium 2](evals/resultados/20261103-1553-gpt-6-luna-medium-2.md) e [medium 3](evals/resultados/20261103-1554-gpt-6-luna-medium.md). Três das rodadas ([`…-medium-2`](evals/resultados/20261103-1553-gpt-6-luna-medium-2.md), [`…-high-2`](evals/resultados/20261103-1554-gpt-6-luna-high-2.md) e [`…-high-3`](evals/resultados/20261103-1554-gpt-6-luna-high-3.md)) foram reconstruídas da saída do terminal, porque rodadas paralelas no mesmo minuto sobrescreveram o arquivo; o resultado, os tokens e o custo são os que o runner imprimiu.

Na [ablação sem memória](evals/resultados/20261103-1616-gpt-6-luna-medium-sem-memoria.md), o resultado caiu de 25/25 para 20/25. Todos os cinco casos de várias mensagens falharam no segundo turno: 0 de 5 aprovados, contra 5 de 5 com memória. Isso sustenta manter o histórico dentro da sessão ([D09](docs/DECISIONS.md#d09--memória-da-conversa-sim-persistência-do-histórico-não)).

O custo médio do padrão foi US$ 0,0046 por rodada de 30 turnos, cerca de US$ 0,00015 por turno, com aproximadamente 93% dos tokens de entrada em cache. Na projeção base da [D14](docs/DECISIONS.md#d14--custo-e-observabilidade), 5.000 acessos por mês, 3% usando o chat e 150 conversas custariam **US$ 0,14 no cenário realista** e **US$ 4,40 no pessimista**. São hipóteses, não tráfego medido; os demais cenários e fontes estão na D14.

Os resultados variam entre rodadas e cobrem apenas 25 casos. A taxa mede a suíte, não satisfação de clientes. Mini e Gemini rodaram antes das correções; a comparação não isola só o modelo, e a chave gratuita do Gemini limitou a velocidade. Consulte todos os [relatórios versionados](evals/resultados/) para detalhes e falhas.

## Suposições

Adotei estas regras para resolver inconsistências dos dados ([D13](docs/DECISIONS.md#d13--tratamento-dos-dados-e-suposições)):

- Contatos oficiais: (67) 3341-4444 e `contato@emporiodamusica.com.br`; ignoro o outro telefone do manual e o e-mail com acento.
- Parcelamento pela §3.1, mais específica: até 3x com parcela mínima de R$ 50, de 4x a 6x com R$ 80 e de 7x a 12x com R$ 100.
- Como não há data de recebimento, uso `estimated_delivery` como entrega para o prazo de arrependimento.
- `total_brl` é a fonte da verdade do pedido, mesmo quando diverge da soma dos itens; não recalculo.
- Promoções valem por `is_active = 1`, sem inferir vigência pelo calendário.
- Disponível significa `active` com estoque maior que zero. Descontinuados e pré-lançamentos não estão à venda.
- O nome do produto prevalece sobre a descrição divergente; preservo o dado original.

O horário da loja é UTC−4, de Campo Grande/MS. `AGENT_TODAY` permite fixar o agora da CLI; avaliação e exemplos usam as datas dos próprios roteiros ([configuração e prompt](docs/ARCHITECTURE.md)).

## Limitações conhecidas

1. Em consultas de status com previsão vencida, o agente às vezes encaminhou para atendente e gravou o e-mail da verificação como contato. Isso contraria a regra 8 do prompt e a [D11](docs/DECISIONS.md#d11--encaminhamento-para-atendente-humano), que só permite contato oferecido pelo cliente. Nenhum caso da suíte confere esse cenário ([registro na spec](docs/specs/SPEC-0007-exemplos-readme.md#34-readme-final)).
2. Se o modelo incluir o tipo no termo, como “violão giannini gf-3d”, a busca volta vazia e sem `indisponiveis`: todas as palavras precisam aparecer no nome. Pode responder “não temos” para um esgotado que existe ([contrato da busca](docs/ARCHITECTURE.md#6-tools-apptoolspy)).
3. Produtos 135 a 144 têm nomes e descrições divergentes; confio no nome ([D13](docs/DECISIONS.md#d13--tratamento-dos-dados-e-suposições)).
4. Os 25 casos usam substring, com falsos negativos (como “você ainda pode solicitar a devolução”, reprovado no `low`) e verificações fracas, como “não inventar valor de frete”. Aprovação não mede satisfação de clientes ([D05](docs/DECISIONS.md#d05--modelo-e-provedor-openai-com-o-código-preparado-para-outros), [D12](docs/DECISIONS.md#d12--testes-e-avaliação)).
5. Sem persistência entre sessões: fechar a CLI apaga a conversa ([D09](docs/DECISIONS.md#d09--memória-da-conversa-sim-persistência-do-histórico-não)).
6. Na API publicada na Vercel, logs e protocolos de encaminhamento ficam em `/tmp`: somem quando a instância reinicia e podem repetir a numeração entre instâncias ([SPEC-0008](docs/specs/SPEC-0008-api-http.md#8-riscos-e-pontos-em-aberto)).
7. Feriados municipais de Campo Grande ainda não entram no expediente ([arquitetura](docs/ARCHITECTURE.md#8-system-prompt-apppromptspy)).
8. No [exemplo 02](examples/02-arrependimento-no-prazo.md), a resposta diz que o pedido chegou “há 4 dias”, mas não explicita 18/01/2026 como a tabela de revisão pede. No terceiro turno, pede desculpa por uma ambiguidade que não ocorreu. O prazo e as condições de devolução estão corretos; mantive a amostra sem edição ou nova tentativa.

## Uso de IA

Usei Claude Opus para planejamento e discussão das decisões; specs foram preparadas por subagentes Opus a partir do PRD, arquitetura e dados. A implementação usa modelos menores, uma spec por vez, com testes escritos e executados em red antes do código. O fluxo prevê revisão humana das specs e de cada passo antes do commit ([D17](docs/DECISIONS.md#d17--uso-de-assistentes-de-código), [AGENTS.md](AGENTS.md)).

O ciclo de commits separa `docs`, `test` em red e `feat` em green para deixar o progresso de TDD verificável no histórico ([D16](docs/DECISIONS.md#d16--repositório)). Avaliações e exemplos usam a API real do agente do projeto; a assinatura de um assistente foi usada para escrever código ([D12](docs/DECISIONS.md#d12--testes-e-avaliação)). Este README foi redigido com IA; o autor aprovou a entrega após a revisão assistida dos exemplos e da documentação.

## O que ficaria para depois

- Logs e encaminhamentos da API num armazenamento persistente, em vez de `/tmp` ([SPEC-0008](docs/specs/SPEC-0008-api-http.md)).
- Persistência entre sessões se houver login e necessidade real ([D09](docs/DECISIONS.md#d09--memória-da-conversa-sim-persistência-do-histórico-não)).
- LLM-juiz para tom e empatia e `--repeticoes` para medir variância ([SPEC-0006](docs/specs/SPEC-0006-avaliacao.md#8-riscos-e-pontos-em-aberto)).
- Classificação de intenção quando houver tráfego real ([D14](docs/DECISIONS.md#d14--custo-e-observabilidade)).
- RAG vetorial caso o volume de documentos cresça ([D04](docs/DECISIONS.md#d04--políticas-rag-sem-vetores)).
- Links para o catálogo com filtros definidos pelo futuro site ([D18](docs/DECISIONS.md#d18--link-para-catálogo-filtrado-possível-site)).
- Feriados municipais, melhorias na busca e correções dos comportamentos descritos em [Limitações conhecidas](#limitações-conhecidas), em trabalho separado.

## Documentação

- [PRDs](docs/prds/) e [PRD-0001 — Agente de atendimento](docs/prds/PRD-0001-agente-atendimento.md): problema, requisitos e critérios de sucesso.
- [Specs](docs/specs/): contratos e testes de cada entrega; [SPEC-0007](docs/specs/SPEC-0007-exemplos-readme.md) cobre exemplos e README; [SPEC-0008](docs/specs/SPEC-0008-api-http.md), a API HTTP.
- [Decisões técnicas](docs/DECISIONS.md): escolhas, justificativas e alternativas descartadas.
- [Arquitetura](docs/ARCHITECTURE.md): módulos, tipos, configuração e contratos.
- [AGENTS.md](AGENTS.md): regras de escopo, TDD e contribuição para agentes de código.
