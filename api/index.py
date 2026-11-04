"""Ponto de entrada da Vercel: expõe o app FastAPI do pacote app."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import criar_app  # noqa: E402

app = criar_app()
