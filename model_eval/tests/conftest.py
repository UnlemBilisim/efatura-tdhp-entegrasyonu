"""Test dosyalari arasinda paylasilan fixture'lar ve ornek veri."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# core.reporting/core.db PostgreSQL'e yazar - testler icin prod DB'sinden ayri
# bir test veritabani kullanilir (bkz. GOREV_MIMARI_DUZELTME.md / mimari
# denetim, 2026-07-22). TEST_DATABASE_URL tanimli degilse bu testler skip
# edilir - CI/gelistirici ortaminda PostgreSQL yoksa suit hala calisabilir.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://efatura:efatura@localhost:5434/model_eval_test"
)


def _postgres_available():
    try:
        import psycopg2
        conn = psycopg2.connect(TEST_DATABASE_URL, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_available(), reason="TEST_DATABASE_URL'e baglanilamiyor - PostgreSQL testleri atlandi"
)


@pytest.fixture
def db_conn():
    """Her testten once ilgili tablolari temizler, os.environ['DATABASE_URL']'i
    test DB'sine yonlendirir ve core.db singleton pool'unu sifirlar - boylece
    testler birbirinden ve gercek gelistirme/prod DB'sinden izole calisir."""
    from core import db as db_module

    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    db_module.reset_pool_for_tests()
    pool = db_module.get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE model_eval_sonuclar RESTART IDENTITY")
        conn.commit()
    finally:
        pool.putconn(conn)

    yield

    db_module.reset_pool_for_tests()
    if old_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old_url

SAMPLE_INVOICE_JSON = {
    "header": {
        "account_title": "Turkcell Iletisim Hizmetleri A.S.",
        "account_tax_number": "8770013406",
        "invoice_id": "0012025015078595",
        "issue_date": "2025-01-25",
        "currency": "TRY",
        "invoice_type": "SATIS",
        "allowance_total": "0.00 TRY",
        "tax_exclusive": "207.83 TRY",
        "tax_inclusive": "291.70 TRY",
        "payable": "291.70 TRY",
    },
    "taxes": [
        {"name": "Katma Deger Vergisi", "code": "0015", "percent": "20", "tax": "41.57 TRY", "exemption": {}},
    ],
    "accounting_entries": [
        {"account_code": "191.01.00020", "account_name": "%20 Indirilecek KDV", "amount": "41.57", "dc": "Borç"},
        {"account_code": "689.01.00009", "account_name": "OZEL ILETISIM VERGISI", "amount": "20.78", "dc": "Borç"},
        {"account_code": "329.01.00012", "account_name": "TURKCELL", "amount": "291.70", "dc": "Alacak"},
    ],
    "lines": [
        {"product_name": "Tarife ve Paket Ucretleri", "quantity": "1 T0", "total": "207.69 TRY"},
    ],
    "notes": ["Ornek not"],
}


@pytest.fixture
def invoice_file(tmp_path):
    def _write(filename, data):
        p = tmp_path / filename
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p
    return _write
