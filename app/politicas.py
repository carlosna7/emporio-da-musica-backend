import re
from pathlib import Path

CAMINHO_POLITICAS = Path(__file__).resolve().parents[1] / "data" / "politicas.md"
TOPICOS = {
    "sobre_a_loja": 1,
    "horarios": 2,
    "pagamentos": 3,
    "trocas_devolucoes": 4,
    "frete_entregas": 5,
    "promocoes": 6,
    "garantia": 8,
    "privacidade": 9,
}


def carregar_secoes(caminho: Path = CAMINHO_POLITICAS) -> dict[int, str]:
    secoes: dict[int, str] = {}
    numero = None
    linhas: list[str] = []
    iniciou = False
    for linha in caminho.read_text(encoding="utf-8").splitlines(keepends=True):
        if linha.startswith("## "):
            if numero is not None:
                secoes[numero] = "".join(linhas).strip()
            titulo = re.match(r"^## (\d+)\. ", linha)
            numero = int(titulo.group(1)) if titulo else None
            if numero == 1:
                iniciou = True
            if not iniciou:
                numero = None
            linhas = []
        if numero is not None:
            linhas.append(linha)
    if numero is not None:
        secoes[numero] = "".join(linhas).strip()
    return secoes


def texto_da_secao(numero: int, caminho: Path = CAMINHO_POLITICAS) -> str:
    secoes = carregar_secoes(caminho)
    if numero not in secoes:
        raise ValueError(f"Seção inexistente: {numero}")
    return secoes[numero]


def texto_do_topico(topico: str, caminho: Path = CAMINHO_POLITICAS) -> str:
    if topico not in TOPICOS:
        raise ValueError(f"Tópico inválido: {topico}. Válidos: {', '.join(TOPICOS)}")
    return texto_da_secao(TOPICOS[topico], caminho)
