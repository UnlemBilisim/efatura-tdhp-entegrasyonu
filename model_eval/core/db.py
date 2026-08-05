"""PostgreSQL baglanti havuzu ve sonuc tablosu semasi.

Mcp_mimarisi ile ayni Postgres sunucusunu (ayni DATABASE_URL) paylasir ama
tablo isim alani cakismasin diye tum tablolar `model_eval_` on ekini tasir -
bkz. entegrasyon.md. Havuz process omru boyunca tek seferlik olusturulur
(module-level singleton) - CLI'nin `--model-parallelism`/`--concurrency` ile
ayni process icinde acilan cok sayida thread bu havuzu paylasir.
"""

import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
from psycopg2 import sql

_pool = None
_pool_lock = threading.Lock()


def _tenant_semasi(tenant_vkn):
    """tenant_vkn'den şema adını türetir (2026-07-30, çoklu şirket geçişi).
    Şema adı SQL identifier'dır, %s ile parametrize EDİLEMEZ — sıkı
    doğrulanır (sadece rakam, VKN 10 hanelidir)."""
    if not tenant_vkn or not tenant_vkn.isdigit():
        raise ValueError(f"Geçersiz VKN formatı, şema adı türetilemez: {tenant_vkn!r}")
    return f"tenant_{tenant_vkn}"

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

CREATE TABLE IF NOT EXISTS mizan_alt_kirilim (
    hesap_kodu     TEXT PRIMARY KEY,
    ana_kod        TEXT NOT NULL,
    hesap_adi      TEXT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mizan_alt_kirilim_ana_kod
    ON mizan_alt_kirilim (ana_kod);
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
def get_conn(tenant_vkn=None):
    """tenant_vkn verilmezse (varsayılan) davranış DEĞİŞMEZ: public şemaya
    bağlanır (mevcut CLI/test akışı). Verilirse (2026-07-30, çoklu şirket
    geçişi) search_path o şirketin tenant şemasına çevrilir - havuz TEK ve
    bağlantılar şirketler arası yeniden kullanıldığı için search_path
    DSN'e gömülemez, her ödünç almada yeniden set edilir."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        sema = _tenant_semasi(tenant_vkn) if tenant_vkn else "public"
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(sema)))
        yield conn
    finally:
        pool.putconn(conn)


def kayitli_tenant_vknleri():
    """Onboard edilmiş şirketlerin VKN listesini döner (2026-07-30, çoklu
    şirket geçişi — entegrasyon arayüzünde VKN input'una öneri göstermek
    için). Kaynak: PostgreSQL'deki `tenant_<vkn>` şemaları — ayrı bir
    "tenant kayıt" tablosu YOK (kullanıcı kararı: şimdilik sadece VKN
    yeterli), şema listesi zaten tek doğru kaynak.

    Henüz göç etmemiş DEFAULT_OWN_VKN (public şemada duran mevcut şirket)
    bu listede YOKTUR — bu fonksiyon sadece tenant_* şemalarını okur, çağıran
    taraf (entegrasyon/app.py) DEFAULT_OWN_VKN'i ayrıca ekler."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'tenant\\_%' ESCAPE '\\' ORDER BY schema_name"
            )
            return [row[0].removeprefix("tenant_") for row in cur.fetchall()]
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
