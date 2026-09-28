"""Mcp_mimarisi testleri için ortak kurulum — DB'siz çalışır."""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from efatura_kdv.nace_kural_kontrolu import NaceOranTablosu  # noqa: E402

SAHTE_NACE_TABLOSU = {
    "532009": [20.0],
    "463304": [1.0, 10.0],
}


@pytest.fixture
def oran_tablosu():
    # Gerçek NaceOranTablosu __init__'te PostgreSQL'e bağlanır; burada
    # bağlantısız bir örnek kurulup tablo elle doldurulur.
    tablo = object.__new__(NaceOranTablosu)
    tablo._tablo = dict(SAHTE_NACE_TABLOSU)
    return tablo
