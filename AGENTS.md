# Regras para agentes de código

Projeto: agente de atendimento da Empório da Música (desafio técnico Artefact).
O avaliador mede **raciocínio, clareza e iniciativa**. Simplicidade vence sofisticação.

## Antes de codar
1. Leia [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (contratos e convenções), a spec que vai implementar em `docs/specs/` e o PRD dela em `docs/prds/`.
   [docs/DECISIONS.md](docs/DECISIONS.md) explica o porquê das escolhas; consulte se precisar de contexto, mas não é o seu guia de implementação.
2. Implemente **uma spec por vez**, só o que está nela. Se algo estiver ambíguo ou contradisser o ARCHITECTURE, pare e pergunte; não invente escopo.

## Como codar
- **TDD obrigatório:** escreva os testes da spec (seção 5) primeiro, rode e confirme que falham (*red*). Só então implemente até ficarem verdes.
- Python 3.12, código em `app/`, testes em `tests/`.
- Testes unitários **nunca** acessam a rede: LLM sempre via `FakeLLM`. Chamadas reais só em `evals/`.
- Não adicione dependências fora das listadas no ARCHITECTURE (§2) ou na spec.
- Sem framework de agente (LangChain etc.). SDK de provedor só dentro de `app/llm/providers/`.
- Cálculos de preço e desconto no código (`app/precos.py`), nunca no prompt.
- Funções pequenas, nomes claros e em português no domínio (`buscar_produtos`, `consultar_pedido`). Comentários só onde o *porquê* não é óbvio.

## Antes de entregar cada passo
```bash
pytest
ruff check .
```
Tudo verde → marque os critérios de aceite da spec → um commit pequeno com mensagem descritiva (ex.: `feat(ingest): carrega produtos no SQLite`).

## Não mexa
- O frontend, que vive em outro repositório (`../emporio-da-musica-frontend/`). Só o futuro PRD-0002, opcional, toca nele.
- `../Desafio Técnico AI Engineer 2026/` (material original, fora de qualquer repositório).
- `data/raw/` (cópia fiel dos dados originais; só leitura).
- `docs/DECISIONS.md` (escrito pelo autor).
- `.env` e chaves de API.
