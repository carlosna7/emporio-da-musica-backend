import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_secoes_obrigatorias():
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    titulos = [
        "## Em resumo", "## Como rodar", "## Conversas de exemplo", "## Arquitetura",
        "## Decisões técnicas", "## Resultados da avaliação", "## Suposições",
        "## Limitações conhecidas", "## Uso de IA", "## O que ficaria para depois",
        "## Documentação",
    ]
    assert all(t in texto.splitlines() for t in titulos)
    assert [texto.index(t) for t in titulos] == sorted(texto.index(t) for t in titulos)
    assert "Em construção" not in texto


def test_links_relativos_existem():
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    for alvo in re.findall(r"\]\(([^)\s]+)\)", texto):
        if not alvo.startswith(("http://", "https://", "mailto:", "#")):
            assert (RAIZ / alvo.split("#")[0]).exists(), alvo


def test_todos_exemplos_linkados():
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    exemplos = list((RAIZ / "examples").glob("*.md"))
    assert 3 <= len(exemplos) <= 5
    alvos = re.findall(r"\]\(([^)\s]+)\)", texto)
    assert all(f"examples/{p.name}" in alvos for p in exemplos)
