# Decisões Técnicas

> Por que construí o agente do jeito que construí. Em cada decisão: o que escolhi, por quê e o que descartei.
> Os detalhes de implementação (contratos, esquemas, convenções) estão em [ARCHITECTURE.md](ARCHITECTURE.md).
> Este arquivo é a base das seções "Decisões técnicas", "Suposições" e "Limitações" do README.

---

## D01 — Python e ferramental
- **Decisão:** Python 3.12, com o código em a raiz do repositório e um `pyproject.toml`. Recomendo `uv`, mas `pip install -e .` também funciona.
- **Por quê:** a única restrição do desafio é Python. O `pyproject` é o padrão atual e funciona com os dois gerenciadores, então quem for avaliar não precisa instalar nada fora do comum.

## D02 — Banco de dados: SQLite
- **Decisão:** SQLite (`sqlite3`, da biblioteca padrão).
- **Por quê:**
  - Os dados são **relacionais**: pedido → cliente, item → pedido/produto, promoção → produto, produto → categoria. SQL resolve com `JOIN` simples.
  - O volume é minúsculo (~250 linhas, 6 tabelas). Sem infraestrutura e sem dependência, roda com um comando.
  - Para publicar, o banco é recriado a partir dos CSVs. Basta importar os arquivos.
- **Descartei:**
  - **MongoDB:** os dados não têm formato de documento. Exigiria um servidor (ou Atlas) e `$lookup` para o que é um `JOIN`. Só o campo `specs` é semiestruturado, e o SQLite guarda isso como JSON.
  - **Postgres:** só faria sentido se o deploy precisasse de escrita concorrente de verdade, o que não é o caso de um protótipo.

## D03 — Abordagem do agente: ReAct via function calling
- **Decisão:** um loop ReAct próprio usando o *function calling* nativo do modelo. O modelo raciocina, escolhe uma ferramenta, recebe o resultado e repete até ter a resposta. Exemplo: "me arrependi, posso devolver o pedido 5?" vira `consultar_pedido` → `consultar_politica("trocas_devolucoes")` → resposta. O loop tem um **limite de iterações** (5): se o agente não chegar a uma resposta, ele para e oferece um atendente, em vez de girar gastando tokens.
- **Ferramentas:**

  | Tool | Quando o agente usa | Fonte |
  | --- | --- | --- |
  | `buscar_produtos` | preço, disponibilidade, catálogo, promoções | SQLite |
  | `detalhes_produto` | especificações técnicas e descrição | SQLite |
  | `consultar_pedido` | status, rastreio, previsão de entrega | SQLite |
  | `consultar_politica` | horários, endereço, pagamento, troca, frete, garantia, privacidade | `politicas.md` |
  | `encaminhar_atendente` | casos que precisam de uma pessoa (D11) | registro local |

- **Por quê:** o desafio pede que o agente saiba *quando* consultar dados e *quando* consultar políticas. Com function calling essa decisão fica explícita e rastreável: cada chamada aparece no log e nos exemplos. Não usei LangChain nem LangGraph: menos dependências e menos abstração deixam a lógica mais simples.
- **Descartei:**
  - **Agente text-to-SQL:** fica muito colado ao banco e depende do SQL que o modelo gerar, mesmo com consultas-padrão. Ele poderia errar a consulta ou ler dados de outros clientes.
  - **ReAct em texto** (`Thought / Action / Observation` escrito no prompt): os modelos atuais já raciocinam internamente. Fazer parse de texto é frágil, o "pensamento" pode vazar para o cliente e gasta mais tokens. O function calling entrega o mesmo ciclo de forma estruturada.

## D04 — Políticas: RAG sem vetores
- **Decisão:** converti o PDF para `data/politicas.md` (versionado e revisado à mão), dividido pelas seções do manual. A ferramenta `consultar_politica(topico)` recupera a seção do tópico pedido, e o modelo responde com base nela. **Continua sendo RAG** (recuperar o trecho certo e gerar a resposta a partir dele), só que a recuperação é por tópico, não por similaridade vetorial.
- **Por quê:** o manual tem ~8 páginas (~2,5 mil tokens) e 10 seções com tema claro. Embeddings, chunking e vector store resolveriam um problema que não existe aqui. Recuperar a seção inteira dá o contexto completo, sem risco de cortar uma regra no meio.
- **Quando eu usaria RAG vetorial:** quando o volume de informação crescesse a ponto de não caber, ou de ficar caro, no contexto. Por exemplo, manuais técnicos de 300 instrumentos ou milhares de tickets antigos. Também quando o conteúdo não tivesse tópicos fixos e o cliente perguntasse com palavras muito diferentes das do documento, ou quando o time atualizasse documentos com frequência. Com bastante informação, a busca semântica agrega valor que compensa a complexidade.
- **Descartei:** RAG com embeddings (over-engineering para esse volume). Injetar o manual inteiro no system prompt é o **plano B**: é mais simples, mas esconde a decisão de "consultar a política".

## D05 — Modelo e provedor: OpenAI, com o código preparado para outros
- **Decisão:** uso a OpenAI, mas o agente não depende dela. Criei uma interface única (`LLMClient`) e um adaptador pequeno para cada provedor: **OpenAI, Anthropic e Gemini**. Provedor e modelo são escolhidos no `.env` (`LLM_PROVIDER`, `LLM_MODEL`). As ferramentas, o loop e os testes não sabem qual provedor está rodando.
- **Por quê:** é uma medida de segurança. Se um provedor ficar fora do ar, mudar o preço ou mudar a política, troco com uma linha no `.env`, sem reescrever a aplicação. Isso também permite comparar modelos na mesma suíte de avaliação (D12). Para um protótipo, o `.env` é suficiente; um painel de configuração não se justifica.
- **Descartei:** LiteLLM e bibliotecas parecidas. Resolveriam a troca de provedor, mas com uma dependência grande para algo que cabe em três adaptadores curtos, e a separação ficaria escondida em vez de visível no código.
- **Custos:** a estimativa inicial, com um modelo *mini* da OpenAI, é de US$ 0,004 a 0,008 por turno, então US$ 5 cobrem de 600 a 1.200 turnos. Os números reais saem do registro de uso (D14) depois que o agente estiver pronto, e vão para o README.

## D06 — Persona e estratégia de prompt
- **Decisão:** system prompt curto, montado a partir do manual (§7.1 tom de voz, §7.2 fluxo, §7.3 situações especiais), com:
  - persona: **Emilio**, atendente da Empório da Música, informal mas profissional, "um amigo que entende de música";
  - regra dura: **nunca** informar preço, estoque, prazo ou status sem chamar uma ferramenta;
  - escopo: só instrumentos. Acessórios são redirecionados com educação; assuntos fora da loja são recusados com gentileza;
  - **data de hoje no prompt**, necessária para os prazos de troca e devolução;
  - fora do expediente: informar o horário de retorno.
- **Por quê:** as regras do próprio manual viram as regras do agente, então dá para justificar o comportamento linha a linha.

## D07 — Cálculos feitos no código, não pelo LLM
- **Decisão:** a ferramenta de produto já devolve `preco`, `preco_promocional`, `desconto_percent` e `preco_pix` calculados. Regras: promoções não são cumulativas, o desconto do PIX (5%) não vale sobre preço promocional e, se houver mais de uma promoção ativa, vale a maior.
- **Por quê:** o manual diz que informar um preço errado pode configurar propaganda enganosa. Fazendo as contas no código, essa margem de erro deixa de existir.

## D08 — Consulta de pedido exige verificação (LGPD)
- **Decisão:** `consultar_pedido` exige o número do pedido **e** o e-mail ou telefone do cliente. Se não conferir, a resposta é genérica ("não encontrei um pedido com esses dados") e não revela se o pedido existe.
- **Por quê:** o manual (§9) cita a LGPD. Sem essa verificação, qualquer pessoa conseguiria listar pedidos de terceiros pelo chat.

## D09 — Memória da conversa sim, persistência do histórico não
- **Decisão:** o agente lembra da conversa **enquanto ela acontece** (as últimas 20 mensagens vão junto a cada pergunta), mas **não salvo o histórico** em banco entre sessões.
- **Por quê:**
  - O enunciado deixa a persistência opcional ("implemente se fizer sentido").
  - Memória dentro da conversa é indispensável: sem ela, "e quanto fica no PIX?" ou "e o de 7 cordas?" não têm sentido.
  - Persistir entre dias, para este caso, é uma camada extra de engenharia com pouco retorno. Atendimento de loja é curto, e o cliente que volta outro dia normalmente traz um assunto novo. Sem login, eu nem saberia com segurança que é a mesma pessoa.
  - Guardar menos dado pessoal é melhor (LGPD).
- **Como vou medir se a memória vale a pena:** a suíte de avaliação roda os casos de várias mensagens **com e sem memória** e compara acerto e tokens. O registro de uso também mostra quantas conversas têm mais de um turno.
- **Descartei:** tabela de histórico no banco com `session_id` e expiração. Fica como evolução, caso exista login e um site em produção.

## D10 — Interface: CLI
- **Decisão:** a interface oficial é uma **CLI** (`python -m app.cli`): um chat no terminal que mostra quais ferramentas o agente chamou. O histórico fica numa lista em memória enquanto o terminal está aberto.
- **Por quê:** o desafio pede o agente, não um site ("o foco é o agente funcionando corretamente"). Com a CLI, quem for avaliar clona, coloca a chave e conversa, sem subir servidor nem front. O script que gera as conversas de exemplo usa o mesmo agente.
- **Depois, se sobrar tempo (opcional):** uma API FastAPI sem estado e o front Next.js, aproveitando o layout que já existe. O navegador guardaria a conversa no `localStorage` e enviaria as últimas mensagens a cada pergunta, então nada fica salvo no servidor. A chave do LLM fica sempre no backend e o Next chama a API pelo servidor.

## D11 — Encaminhamento para atendente humano
- **Decisão:** a ferramenta `encaminhar_atendente` existe, mas o Emilio **tenta entender e resolver primeiro**:
  - dúvida que as ferramentas resolvem → responde;
  - **reclamação, defeito/avaria ou pedido de exclusão de dados** → ouve com empatia, junta o essencial (o que aconteceu e o número do pedido) e encaminha. O manual (§7.3) manda registrar e encaminhar reclamações, com retorno em 24 horas úteis;
  - cliente pede atendente → o Emilio tenta entender o problema uma vez; **se o cliente insistir, encaminha sem resistir**.
- **Por quê:** resolver no próprio chat tira carga da equipe, que é o objetivo do projeto. Mas um bot que se recusa a passar para uma pessoa é uma das experiências que mais irritam. A regra "uma tentativa, depois encaminha" equilibra as duas coisas.
- **No protótipo:** não existe um sistema real de fila. A ferramenta grava o caso num arquivo local e devolve um protocolo, o prazo de retorno e o WhatsApp da loja. O contato do cliente só é registrado se ele quiser passar.

## D12 — Testes e avaliação
- **Decisão:**
  - TDD: em toda spec, os testes vêm antes do código.
  - Os testes unitários usam um **LLM falso** (respostas roteirizadas), então custam zero e sempre dão o mesmo resultado.
  - Uma **suíte de avaliação** com 15 a 20 casos (produtos, pedidos, políticas, segurança, fora do escopo, conversas de várias mensagens) roda contra o modelo real e gera um relatório com aprovados por categoria, tokens, custo e latência. Cada caso tem critérios objetivos: qual ferramenta deveria ser chamada e quais fatos precisam (ou não podem) aparecer na resposta.
  - As conversas de `examples/` são geradas pelo agente real.
- **Por quê:** em agente com LLM, "parece funcionar" não basta. A suíte transforma qualidade em número e pega regressões quando eu mudo o prompt ou o modelo. A taxa de aprovação mede a suíte, não a satisfação de clientes reais.
- **Sobre usar assinatura (ChatGPT/Claude):** a assinatura serve para escrever o código, não para rodar o agente. Os exemplos e a avaliação precisam ser conversas reais com o agente do projeto, então usam a API, e custam centavos.

## D13 — Tratamento dos dados e suposições
A ingestão normaliza os tipos (preço → número, estoque → inteiro, `specs` → JSON validado, datas ISO) e cria um nome normalizado (minúsculas, sem acento) para a busca. Inconsistências que encontrei e como tratei cada uma:

| Achado | Tratamento |
| --- | --- |
| Telefone: (67) 3341-4444 (capa e dados da empresa) × (67) 3321-4500 (§7, WhatsApp) | Uso o **3341-4444**, que aparece como "Telefone / WhatsApp" na tabela oficial, e registro a divergência |
| E-mail com acento (`empóriodamusica`) na §1.2 | Uso `contato@emporiodamusica.com.br` (capa, domínio válido) |
| Cartão: a tabela diz "parcela mínima R$ 100" × §3.1 com faixas (até 3x / 4–6x R$ 80 / 7–12x R$ 100) | Sigo a §3.1, que é mais específica. Interpreto "até 3x, exceto abaixo de R$ 50" como parcela mínima de R$ 50 |
| Pedidos não têm data de recebimento | Uso `estimated_delivery` como data de recebimento para o prazo de arrependimento |
| `total_brl` difere da soma dos itens em alguns pedidos | `total_brl` é a fonte da verdade (pode incluir frete ou desconto); o agente não recalcula |
| Produtos 135–144: o nome não bate com a descrição (ex.: "Music Man Bass 1X" descrito como Fender Jazz Bass) | Mantenho os dados e confio no `name`. Fica como limitação conhecida |
| Produto `coming_soon` aparece num pedido entregue | Ignoro (é histórico). Para venda, `coming_soon` = indisponível |
| Status `discontinued` e `coming_soon` | "Disponível" = `active` com estoque > 0. O agente explica os outros status (§7.3) |
| Promoções: o `is_active` é a fonte da verdade, não o calendário | Só aplico promoções com `is_active = 1` |

## D14 — Custo e observabilidade
- **Decisão:** cada chamada ao LLM gera uma linha de log com provedor, modelo, tokens (direto do `usage` da API), latência, ferramentas chamadas e custo estimado (tabela de preços configurável). Limites simples protegem o orçamento: iterações do loop, tamanho da mensagem e janela de histórico.
- **Por quê:** é pouco código e me dá números reais de custo por conversa para o README, além de mostrar como o agente se comportaria operando de verdade.
- **Descartei (por enquanto):**
  - **Classificação de intenção:** sendo realista, ela só gera valor com volume real de clientes (para decidir o que automatizar primeiro). Aqui ela classificaria só conversas de teste. Os casos de avaliação já têm categoria, e as ferramentas registradas no log permitem derivar a intenção depois, sem custo extra.
  - **Dashboard e simulador de demanda:** exigiriam tráfego que não existe. Números simulados poderiam parecer resultado. No README, projeto o custo mensal a partir do custo médio medido.

## D15 — Publicação (se houver front)
- A chave do LLM fica só no backend (`.env`, nunca versionado).
- **Limite de gasto mensal** configurado no painel do provedor. Essa é a proteção real contra abuso.
- Limites no backend (tamanho de mensagem, iterações) e rate-limit por IP no proxy do Next.

## D16 — Repositório
- Os dados necessários (CSVs + `políticas_da_loja.pdf`) são copiados para `data/raw/` com nomes simples (sem espaços nem acentos). O material original do desafio fica fora do repositório, porque contém o PDF do enunciado da empresa.
- Um commit por passo relevante de cada spec. O desafio pede histórico real de commits.

## D17 — Uso de assistentes de código
- **Planejamento e documentos** (PRD, decisões, specs): Claude Opus, como par de discussão. Eu levo as dúvidas e as ideias (inclusive sugestões de outro assistente, o ChatGPT), avalio as opções e decido. Este arquivo registra essas decisões.
- **Dois documentos, dois públicos:** este `DECISIONS.md` explica meu raciocínio para quem avalia. O [`ARCHITECTURE.md`](ARCHITECTURE.md) é o contexto técnico para os agentes de código: contratos, esquemas e convenções, sem justificativas. Separar os dois evita que os agentes recebam texto que não precisam e que o meu raciocínio se perca no meio de detalhes de implementação.
- **Implementação:** agentes e subagentes (Claude Haiku/Sonnet ou GPT via Codex), uma spec por vez, com TDD. As regras estão em [`AGENTS.md`](../AGENTS.md).
- **Revisão humana:** reviso cada spec antes de implementar e cada passo antes do commit.
