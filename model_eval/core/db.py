"""PostgreSQL baglanti havuzu ve sonuc tablosu semasi.

Mcp_mimarisi ile ayni Postgres sunucusunu (ayni DATABASE_URL) paylasir ama
tablo isim alani cakismasin diye tum tablolar `model_eval_` on ekini tasir -
bkz. ENTEGRASYON.md. Havuz process omru boyunca tek seferlik olusturulur
(module-level singleton) - CLI'nin `--model-parallelism`/`--concurrency` ile
ayni process icinde acilan cok sayida thread bu havuzu paylasir.
"""

import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.pool

_pool = None
_pool_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_eval_sonuclar (
    id             BIGSERIAL PRIMARY KEY,
    file_label     TEXT NOT NULL,
    invoice_id     TEXT NOT NULL,
    record         JSONB NOT NULL,
    is_error       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_eval_sonuclar_label_invoice
    ON model_eval_sonuclar (file_label, invoice_id);
"""


def _database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL env var tanimli degil - orn. "
            "postgresql://user:pass@localhost:5432/efatura"
        )
    return url


def get_pool():
    """Process omru boyunca tek `ThreadedConnectionPool`. Cagrildigi ilk anda
    semayi da (CREATE TABLE IF NOT EXISTS) dogrular/olusturur."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2, maxconn=10, dsn=_database_url()
            )
            conn = pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(_SCHEMA)
                conn.commit()
            finally:
                pool.putconn(conn)
            _pool = pool
    return _pool


@contextmanager
def get_conn():
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def reset_pool_for_tests():
    """Sadece testlerde: her test kendi DATABASE_URL'iyle (orn. ayri bir
    test semasi/DB) calisabilsin diye singleton'i sifirlar."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
        _pool = None
