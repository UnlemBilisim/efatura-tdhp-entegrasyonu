"""`nace_kdv (1).xlsx`'in `2026_KOD_DEGISIKLIKLERI` sayfasını PostgreSQL'e taşır.

Bir kereye mahsus çalıştırılır (idempotent — tekrar çalıştırılırsa tabloyu
baştan doldurur). Bağlantı `DATABASE_URL` env var'ından okunur.

Şema ve gerekçe: docs/reference/nace-kdv-excel-yapisi.md
("PostgreSQL Şeması" bölümü).

Çalıştırma (proje kökünden):

    DATABASE_URL=postgresql://user:pass@localhost:5432/efatura_kdv \
        python3 scripts/excel_to_postgres.py
"""

from __future__ import annotations

import json
import os
import sys

import openpyxl
import psycopg2

EXCEL_DOSYASI = "nace_kdv (1).xlsx"
GUNCEL_SAYFA = "2026_KOD_DEGISIKLIKLERI"
_KOD_SUTUN_IDX = 2  # YENİ KOD

_KDV_SUTUNLARI = {
    "KDV%0": "kdv_0",
    "KDV %1": "kdv_1",
    "KDV %10": "kdv_10",
    "KDV %20": "kdv_20",
}

SEMA_SQL = """
CREATE TABLE IF NOT EXISTS nace_oranlari (
    nace_kodu     TEXT PRIMARY KEY,
    kdv_0         BOOLEAN NOT NULL DEFAULT FALSE,
    kdv_1         BOOLEAN NOT NULL DEFAULT FALSE,
    kdv_10        BOOLEAN NOT NULL DEFAULT FALSE,
    kdv_20        BOOLEAN NOT NULL DEFAULT FALSE,
    kaynak_satir  JSONB
);
"""


def _excel_satirlarini_oku(excel_path: str):
    """Excel'deki güncel sayfayı okuyup her NACE kodu için sütun-adı→değer eşlemesi üretir."""
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb[GUNCEL_SAYFA]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]

    for row in rows[1:]:
        kod = row[_KOD_SUTUN_IDX]
        if not kod:
            continue
        satir_dict = dict(zip(header, row))
        yield str(kod).strip(), satir_dict


def migrasyonu_calistir(excel_path: str = EXCEL_DOSYASI, database_url: str | None = None):
    """Excel'i okuyup nace_oranlari tablosunu (yeniden) doldurur."""
    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "DATABASE_URL env var tanımlı değil — örn. "
            "postgresql://user:pass@localhost:5432/efatura_kdv"
        )

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(SEMA_SQL)
            cur.execute("TRUNCATE TABLE nace_oranlari")

            satir_sayisi = 0
            for nace_kodu, satir_dict in _excel_satirlarini_oku(excel_path):
                degerler = {sutun_adi: False for sutun_adi in _KDV_SUTUNLARI.values()}
                for excel_sutun, db_sutun in _KDV_SUTUNLARI.items():
                    if satir_dict.get(excel_sutun) is not None:
                        degerler[db_sutun] = True

                # JSONB serileştirme için excel'in datetime/Decimal gibi
                # JSON-uyumsuz tiplerini string'e çeviriyoruz.
                kaynak_satir = {str(k): (v if isinstance(v, (int, float, str, bool)) or v is None else str(v))
                                for k, v in satir_dict.items()}

                cur.execute(
                    """
                    INSERT INTO nace_oranlari (nace_kodu, kdv_0, kdv_1, kdv_10, kdv_20, kaynak_satir)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (nace_kodu) DO UPDATE SET
                        kdv_0 = EXCLUDED.kdv_0,
                        kdv_1 = EXCLUDED.kdv_1,
                        kdv_10 = EXCLUDED.kdv_10,
                        kdv_20 = EXCLUDED.kdv_20,
                        kaynak_satir = EXCLUDED.kaynak_satir
                    """,
                    (
                        nace_kodu,
                        degerler["kdv_0"],
                        degerler["kdv_1"],
                        degerler["kdv_10"],
                        degerler["kdv_20"],
                        json.dumps(kaynak_satir, ensure_ascii=False),
                    ),
                )
                satir_sayisi += 1

        conn.commit()
        print(f"Tamamlandı: {satir_sayisi} NACE kodu nace_oranlari tablosuna yazıldı.")
    finally:
        conn.close()


if __name__ == "__main__":
    excel_path = sys.argv[1] if len(sys.argv) > 1 else EXCEL_DOSYASI
    migrasyonu_calistir(excel_path)
