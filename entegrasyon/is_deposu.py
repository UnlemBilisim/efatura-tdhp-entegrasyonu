"""v2 API icin kalici is (job) deposu — PostgreSQL tabanli.

Neden kalici (2026-07-27, v2 tasarim karari): asenkron desende istemci
`job_id` ile sonucu sonradan sorar. Bellekte tutmak servis yeniden
baslatildiginda tum islerin kaybolmasi anlamina gelirdi; toplu gonderimde
(dis ekip batch yapacak) bu kabul edilemez.

Tablo `api_jobs` — `entegrasyon/` bilesenine aittir. Mevcut kurala gore her
bilesen kendi tablolarini kullanir (bkz. System/CLAUDE.md); `api_` oneki bu
ayrimi korur, `model_eval_sonuclar` ve `nace_oranlari`'na dokunulmaz.

Istek govdesi (invoice_xml dahil) `request` kolonunda saklanir - boylece onay
verilirken istemci 500 KB XML'i TEKRAR GONDERMEZ (v1'deki en buyuk
tasarim sorunu).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Optional

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

SEMA_SQL = """
CREATE TABLE IF NOT EXISTS api_jobs (
    job_id       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    request      JSONB NOT NULL,
    result       JSONB,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_api_jobs_status ON api_jobs (status);
CREATE INDEX IF NOT EXISTS idx_api_jobs_created ON api_jobs (created_at DESC);
"""

# Gecerli durum degerleri - v2 sozlesmesinin bir parcasi, degistirmek dis
# semayi kirar (bkz. docs/explanation/v2-api-tasarim-karari.md).
DURUMLAR = frozenset({
    "queued",
    "processing",
    "awaiting_approval",
    "completed",
    "failed",
})

_pool: Optional[ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def _havuz() -> ThreadedConnectionPool:
    """Process-omru baglanti havuzu; ilk cagrida semayi da dogrular.

    `core/db.py` ile ayni desen - DATABASE_URL env'den okunur, yoksa ACIK bir
    hata verilir (gomulu kimlik bilgisi fallback'i YOK)."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError(
                    "DATABASE_URL env var tanimli degil — v2 API is deposu "
                    "PostgreSQL gerektiriyor (orn. "
                    "postgresql://user:pass@localhost:5434/efatura_kdv)"
                )
            havuz = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=url)
            conn = havuz.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(SEMA_SQL)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                havuz.putconn(conn)
            _pool = havuz
    return _pool


def _yaz(sql: str, params: tuple):
    """Tek bir yazma sorgusu — hata durumunda ROLLBACK yapip baglantiyi
    havuza temiz iade eder (bozuk transaction sonraki istegi zehirlemesin;
    bu, gecmis_kontrol.py'de bulunan bir hatanin tekrarlanmamasi icin)."""
    havuz = _havuz()
    conn = havuz.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        havuz.putconn(conn)


def is_olustur(istek: dict) -> str:
    """Yeni bir isi `queued` durumunda kaydeder ve job_id doner."""
    job_id = uuid.uuid4().hex
    _yaz(
        "INSERT INTO api_jobs (job_id, status, request) VALUES (%s, %s, %s)",
        (job_id, "queued", json.dumps(istek, ensure_ascii=False)),
    )
    return job_id


def is_getir(job_id: str) -> Optional[dict]:
    """job_id'ye ait isi doner; yoksa None (cagiran taraf 404 uretir)."""
    havuz = _havuz()
    conn = havuz.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT job_id, status, request, result, error, created_at, updated_at "
                "FROM api_jobs WHERE job_id = %s",
                (job_id,),
            )
            satir = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        havuz.putconn(conn)

    if satir is None:
        return None
    return {
        "job_id": satir[0],
        "status": satir[1],
        "request": satir[2],
        "result": satir[3],
        "error": satir[4],
        "created_at": satir[5],
        "updated_at": satir[6],
    }


def durum_guncelle(
    job_id: str,
    status: str,
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """Isin durumunu (ve varsa sonucunu/hatasini) guncelller.

    Bilinmeyen bir status degeri ValueError firlatir - sessizce yazilmasi
    dis sozlesmeyi bozar (istemci tanimadigi bir durum gorur)."""
    if status not in DURUMLAR:
        raise ValueError(f"gecersiz is durumu: {status!r} (gecerli: {sorted(DURUMLAR)})")
    _yaz(
        "UPDATE api_jobs SET status = %s, result = %s, error = %s, updated_at = now() "
        "WHERE job_id = %s",
        (
            status,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            error,
            job_id,
        ),
    )


def istek_guncelle(job_id: str, istek: dict) -> None:
    """Saklanan istek govdesini guncelller — onay/kur secimi eklenirken
    kullanilir (istemci XML'i tekrar gondermedigi icin mevcut govdeye
    yalnizca yeni alan islenir)."""
    _yaz(
        "UPDATE api_jobs SET request = %s, updated_at = now() WHERE job_id = %s",
        (json.dumps(istek, ensure_ascii=False), job_id),
    )


def havuzu_kapat() -> None:
    """Test/kapanis icin havuzu serbest birakir."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None
