# SPEC-NNNN — <nome>

> Copie para `docs/specs/SPEC-NNNN-nome.md`. Leia o PRD de origem e o [ARCHITECTURE](../ARCHITECTURE.md) antes.
> **Linke** decisões e seções (ex.: "ver D07", "ARCHITECTURE §6") em vez de repeti-las.

- **Status:** rascunho | aprovada | implementada
- **PRD:** [PRD-NNNN](../prds/PRD-NNNN-nome.md)
- **Depende de:** SPEC-NNNN

## 1. Objetivo
O que esta spec entrega, em 1 a 3 frases, e quais requisitos do PRD ela atende (ex.: `PRD-0001/R3`).

## 2. Escopo
- **Dentro:**
- **Fora:**

## 3. Contrato
Assinaturas públicas que outras partes do código vão usar: funções, schemas de tools, endpoints, tabelas.
Use blocos de código com tipos Python, por exemplo:

```python
def buscar_produtos(termo: str | None = None, ...) -> list[ProdutoResumo]: ...
```

## 4. Arquivos
- **Criar:** `app/...`
- **Alterar:**
- **Testes:** `tests/test_<modulo>.py`

## 5. Testes (escrever ANTES do código)
Comece no *red*. Unit tests nunca chamam a API real (ver ARCHITECTURE §11).

- [ ] Caso feliz:
- [ ] Borda / entrada inválida:
- [ ] Regra de negócio:
- **Fixtures/mocks:** (banco SQLite temporário em `tmp_path`, `FakeLLM`, etc.)

## 6. Plano
Passos pequenos e ordenados. Os commits seguem o ciclo da spec (ver D16):

1. Escrever os testes da §5 e confirmar que falham → commit `test(<escopo>): ...`
2. Implementar até os testes passarem → commit `feat(<escopo>): ...` (marcar a spec como implementada)
3. …

## 7. Critérios de aceite
IDs fixos; ajuste o texto, mas não o ID.

- [ ] [AC-01] Comportamento observável, com a evidência esperada
- [ ] [AC-TESTES] `pytest` verde
- [ ] [AC-LINT] `ruff check .` verde
- **Verificação manual:** comando → resultado esperado

## 8. Riscos e pontos em aberto
Suposições, riscos e mitigação. Pontos que precisam de decisão humana **antes** de implementar.
