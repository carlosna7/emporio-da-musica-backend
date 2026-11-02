import sqlite3
import unicodedata
from pathlib import Path

CAMINHO_BANCO = Path(__file__).resolve().parents[1] / "data" / "emporio.db"


def normalizar(texto: str) -> str:
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto.lower())
        if not unicodedata.combining(caractere)
    )


def conectar(caminho: Path = CAMINHO_BANCO) -> sqlite3.Connection:
    if not caminho.exists():
        raise FileNotFoundError(f"Banco não encontrado: {caminho}. Execute python -m app.ingest")
    conexao = sqlite3.connect(f"{caminho.resolve().as_uri()}?mode=ro", uri=True)
    conexao.row_factory = sqlite3.Row
    return conexao
