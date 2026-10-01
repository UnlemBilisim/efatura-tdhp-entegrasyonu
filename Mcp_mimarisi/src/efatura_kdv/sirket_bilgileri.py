"""Onboarding sırasında kaydedilen şirket profil bilgileri (şu an sadece
NACE kodları) — `public.sirket_bilgileri` tablosu.

Neden gerekli (2026-09-29, kullanıcı kararı — canlıya çıkış hazırlığı):
Önceden dış ekip her `/fatura/isle` isteğinde `satici_nace_kodlari` alanını
doldurmak zorundaydı; unutulursa outbox faturada KDV ön filtresi hiç
çalışmıyordu (bkz. `kalem_nace_esleme.py` — NACE olmadan oran havuzu
hesaplanamaz). Fatura XML'i NACE kodu taşımadığı için (bkz. Mcp_mimarisi/
CLAUDE.md "Kritik gerçekler") bu bilgi zaten ayrı bir kaynaktan gelmek
zorundaydı — artık bu kaynak "her istekte dış ekip" yerine "onboarding
sırasında bir kere biz" oluyor. `/fatura/isle`'daki `satici_nace_kodlari`
alanı opsiyonel kalmaya devam ediyor (dış ekip isterse override edebilir,
bkz. `entegrasyon/app.py::_fatura_isle_ic`), boş gelirse burada kayıtlı
NACE kullanılır.

Bilinçli olarak `public` şemada tutulur (tenant şemasında DEĞİL) — VKN
zaten birincil anahtar, tenant izolasyonuna ihtiyaç yok, tek bir tabloda
tüm şirketleri görmek onboarding/bakım için daha pratik.

Tablo Alembic migration'ı (`56d739edb09d`) ile "belgelenmiştir" ama o
migration `public` şemasına karşı hiç çalıştırılmamıştır — bu projede
Alembic fiilen sadece tenant onboarding'de (`ALEMBIC_TENANT_SCHEMA` ile)
koşulur (bkz. `public`'teki diğer tablolar: `nace_oranlari`,
`api_anahtarlari` vb., hepsi aynı nedenle runtime'da kendiliğinden
oluşuyor). Bu yüzden burada da `api_anahtarlari.py::tabloyu_hazirla()` ile
aynı lazy `CREATE TABLE IF NOT EXISTS` deseni kullanılır (2026-09-30,
onboarding testi sırasında `relation "public.sirket_bilgileri" does not
exist` hatasıyla fark edildi)."""

from __future__ import annotations

import os

import psycopg2

_TABLO_SQL = """
CREATE TABLE IF NOT EXISTS public.sirket_bilgileri (
    vkn                 TEXT PRIMARY KEY,
    nace_kodlari         TEXT[] NOT NULL DEFAULT '{}',
    guncellenme_zamani   TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_tablo_hazir = False


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL env var tanimli degil - orn. "
            "postgresql://user:pass@localhost:5432/efatura_kdv"
        )
    return url


def _tabloyu_hazirla(conn) -> None:
    global _tablo_hazir
    if _tablo_hazir:
        return
    with conn.cursor() as cur:
        cur.execute(_TABLO_SQL)
    conn.commit()
    _tablo_hazir = True


def nace_kodlarini_kaydet(vkn: str, nace_kodlari: list[str], database_url: str | None = None) -> None:
    """Onboarding sırasında (ya da güncellemede) çağrılır. Upsert — aynı VKN
    tekrar kaydedilirse üzerine yazar (çoğalmaz), `guncellenme_zamani` yenilenir."""
    conn = psycopg2.connect(database_url or _database_url())
    try:
        _tabloyu_hazirla(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.sirket_bilgileri (vkn, nace_kodlari, guncellenme_zamani)
                   VALUES (%s, %s, now())
                   ON CONFLICT (vkn) DO UPDATE
                       SET nace_kodlari = EXCLUDED.nace_kodlari, guncellenme_zamani = now()""",
                (vkn, nace_kodlari),
            )
        conn.commit()
    finally:
        conn.close()


def nace_kodlarini_getir(vkn: str, database_url: str | None = None) -> list[str]:
    """Kayıtlı NACE kodlarını döner; şirket hiç kaydedilmemişse boş liste
    (exception FIRLATMAZ) - çağıran taraf bunu 'NACE bilgisi yok, ön filtre
    çalışamayacak' olarak ele alır, kendi başına bir hata durumu değildir."""
    conn = psycopg2.connect(database_url or _database_url())
    try:
        _tabloyu_hazirla(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT nace_kodlari FROM public.sirket_bilgileri WHERE vkn = %s", (vkn,))
            row = cur.fetchone()
    finally:
        conn.close()
    return list(row[0]) if row else []
