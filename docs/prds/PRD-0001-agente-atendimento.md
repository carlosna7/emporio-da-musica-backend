# PRD-0001 — Agente de atendimento

- **Status:** aprovado
- **Data:** 2026-11-02
- **Specs:** SPEC-0001 a SPEC-0007

## Problema
A equipe da Empório da Música (loja de instrumentos em Campo Grande/MS) perde tempo com perguntas repetidas: horários, status de pedido, preço e disponibilidade de produtos.

## Objetivo
Um agente de mensagens de texto, em Python, que responde clientes com dados reais da loja (catálogo, estoque, promoções, pedidos) e com as regras do manual de políticas, no tom da marca, que sabe dizer "não" fora do escopo e que passa para uma pessoa quando precisa.

## Usuário
Cliente final da loja, pela CLI (um site é opcional, depois).

## Requisitos
| ID | Requisito | Origem |
| --- | --- | --- |
| R1 | Persona alinhada ao tom da loja (Emilio: informal, profissional, acolhedor) | Desafio + manual §7.1 |
| R2 | Responder com base nos dados e nas políticas, sem inventar | Desafio + manual §7.1 |
| R3 | Consultar **dados** para preço, estoque, promoção e pedido | Desafio |
| R4 | Consultar **políticas** para horários, pagamento, troca, frete, garantia | Desafio |
| R5 | Tratar fora de escopo: acessórios (redirecionar) e assuntos alheios (recusar) | Desafio + manual §1, §7.1 |
| R6 | Manter contexto dentro da conversa (sem persistir entre sessões) | D09 |
| R7 | Proteger dados de pedidos (verificação do cliente) | Manual §9 (LGPD), D08 |
| R8 | Encaminhar para atendente humano quando necessário | Manual §7.3, D11 |
| R9 | Registrar tokens e custo de cada chamada ao LLM | D14 |

## Fora do escopo
Vender ou fechar pedido, calcular frete por CEP, login de cliente, persistência de histórico, classificação de intenção, dashboard. O site (API + front) era opcional e foi feito depois deste PRD concluído: a API HTTP está na [SPEC-0008](../specs/SPEC-0008-api-http.md) e o front vive no [repositório próprio](https://github.com/carlosna7/emporio-da-musica-frontend).

## Critérios de sucesso
O agente responde certo (e chamando a ferramenta certa) a:
1. "Quais violões disponíveis até R$ 1000?" → `buscar_produtos`
2. "Qual o endereço da loja?" → contatos oficiais do prompt (D13), sem tool e nunca o (67) 3321-4500
3. "Quanto custa o Takamine GD20?" → `buscar_produtos` (com preço PIX)
4. "Me arrependi, posso devolver meu pedido?" → `consultar_pedido` + `consultar_politica`, aplicando o prazo de 7 dias
5. "Vocês vendem cordas?" / "Quem ganhou o jogo ontem?" → resposta de escopo, sem tool
6. "Quero falar com uma pessoa" → tenta entender uma vez; se o cliente insistir, `encaminhar_atendente`

Esses cenários, e outros, viram casos da suíte de avaliação.

## Entregáveis (do desafio)
Repositório público com histórico de commits · README (como rodar, decisões, limitações, uso de IA) · 3 a 5 conversas de exemplo em `examples/`.

## Roadmap de specs
| Spec | Entrega | Depende de |
| --- | --- | --- |
| SPEC-0001 | Ingestão: CSV → SQLite + leitura de `politicas.md` por tópico | — |
| SPEC-0002 | Ferramentas do agente (produtos, pedidos, políticas, encaminhamento) | SPEC-0001 |
| SPEC-0003 | Camada de LLM multi-provedor + `FakeLLM` | — |
| SPEC-0004 | Agente: loop ReAct, persona, memória da conversa, registro de uso | SPEC-0002, SPEC-0003 |
| SPEC-0005 | CLI | SPEC-0004 |
| SPEC-0006 | Suíte de avaliação + relatório (com ablação de memória) | SPEC-0005 |
| SPEC-0007 | Exemplos de conversa + README final | SPEC-0006 |

Decisões: [DECISIONS.md](../DECISIONS.md) · Arquitetura: [ARCHITECTURE.md](../ARCHITECTURE.md) · Modelo de spec: [specs/TEMPLATE.md](../specs/TEMPLATE.md)
