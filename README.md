# Empório da Música — Agente de Atendimento

Protótipo de um agente de atendimento por texto, em Python, para a Empório da Música, loja fictícia de instrumentos musicais em Campo Grande/MS. Desafio técnico AI Engineer (Artefact).

> 🚧 Em construção. As instruções completas, as decisões técnicas e as limitações entram aqui ao final do projeto.

## Documentação
- [PRDs](docs/prds/): problema, requisitos e roadmap ([PRD-0001 — Agente de atendimento](docs/prds/PRD-0001-agente-atendimento.md))
- [Decisões técnicas](docs/DECISIONS.md): o que escolhi, por quê e o que descartei
- [Arquitetura](docs/ARCHITECTURE.md): contratos e convenções (contexto para os agentes de código)
- [Specs](docs/specs/)

## Ambiente
Requer Python 3.12+.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -e ".[dev]"
cp .env.example .env          # preencha a chave do provedor
pytest
```

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
