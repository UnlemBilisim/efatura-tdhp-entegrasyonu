"""`ubls/` klasöründeki geçmiş OUTBOX faturalarını PostgreSQL'e taşır.

Sadece bizim kestiğimiz (outbox) faturalar kaydedilir — inbox faturalar
bizim doğruluğumuzu yansıtmaz, çapraz kontrol amacıyla kullanılmaz (bkz.
PROJECT.md §3.9, docs/reference/gecmis-fatura-semasi.md).

Bir kereye mahsus çalıştırılır (idempotent — tekrar çalıştırılırsa tabloyu
baştan doldurur). Bağlantı `DATABASE_URL` env var'ından okunur.

Çalıştırma (proje kökünden):

    DATABASE_URL=postgresql://user:pass@localhost:5432/efatura_kdv \
        python3 scripts/gecmis_faturalari_yukle.py
"""

from __future__ import annotations

import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from efatura_kdv.ubl_parser import parse_ubl_invoice
from efatura_kdv.kalem_nace_esleme import kalem_istisna_kodlari
from efatura_kdv.gecmis_kontrol import normalize_kalem_adi

UBLS_KLASORU = "ubls"

SEMA_SQL = """
CREATE TABLE IF NOT EXISTS gecmis_fatura_kalemleri (
    id                    SERIAL PRIMARY KEY,
    satici_vkn            TEXT NOT NULL,
    kalem_adi_normalize   TEXT NOT NULL,
    kalem_adi_orijinal    TEXT NOT NULL,
    oran                  NUMERIC NOT NULL,
    istisna_kodu          TEXT,
    fatura_no             TEXT NOT NULL,
    fatura_tarihi         DATE,
    kaynak_dosya          TEXT NOT NULL
);

ALTER TABLE gecmis_fatura_kalemleri ADD COLUMN IF NOT EXISTS istisna_kodu TEXT;

CREATE INDEX IF NOT EXISTS idx_gecmis_eslesme
    ON gecmis_fatura_kalemleri (satici_vkn, kalem_adi_normalize);
"""

# normalize_kalem_adi artık efatura_kdv.gecmis_kontrol'den import ediliyor
# (2026-08-05, kod-tekrarı temizliği) - önceden burada birebir aynı mantık
# ikinci kez tanımlıydı, biri değişip diğeri unutulursa normalize edilmiş
# anahtarlar sessizce eşleşmeme riski taşıyordu.


def _outbox_kalemlerini_topla(ubls_klasoru: str):
    """ubls/ klasöründeki outbox dosyalarını okuyup her kalem-oran çifti için satır üretir.

    İstisna düzeltmesi (2026-07-22): bazı kalemlerde KDV kırılımı var
    (`vergi_tipi_kodu == "0015"`, yani kalem.kdv_kirilimlari doludur) ama
    `oran` alanı None'dır — bu, istisna kapsamındaki (ör. ihracat) satırlarda
    satıcının oran yazmadığı gerçek bir durumdur (bkz. PROJECT.md §3.9,
    örnek: AKK2025000000003, istisna kodu 301). Önceki sürüm bu kalemleri
    `kalem.kdv_oranlari` boş döndüğü için SESSİZCE atlıyordu — istisna
    bilgisi hiç geçmiş tabloya girmiyordu. Artık: oran None ama istisna kodu
    varsa, oran %0 olarak kaydedilir (istisna zaten %0 anlamına gelir) ve
    istisna_kodu sütunu doldurulur."""
    dosyalar = sorted(f for f in os.listdir(ubls_klasoru) if "outbox" in f and f.endswith(".xml"))

    for dosya in dosyalar:
        yol = os.path.join(ubls_klasoru, dosya)
        fatura = parse_ubl_invoice(yol)

        for kalem in fatura.kalemler:
            if not kalem.kalem_adi:
                continue

            if kalem.kdv_oranlari:
                for oran in kalem.kdv_oranlari:
                    yield {
                        "satici_vkn": fatura.satici.vkn,
                        "kalem_adi_normalize": normalize_kalem_adi(kalem.kalem_adi),
                        "kalem_adi_orijinal": kalem.kalem_adi,
                        "oran": oran,
                        "istisna_kodu": None,
                        "fatura_no": fatura.fatura_no,
                        "fatura_tarihi": fatura.duzenleme_tarihi,
                        "kaynak_dosya": dosya,
                    }
                continue

            # oran yok — istisna kodu var mı diye bak (kalemde veya fatura
            # genelinde, bkz. kalem_istisna_kodlari()).
            istisna_kodlari = kalem_istisna_kodlari(kalem, fatura)
            for istisna_kodu, _aciklama in istisna_kodlari:
                yield {
                    "satici_vkn": fatura.satici.vkn,
                    "kalem_adi_normalize": normalize_kalem_adi(kalem.kalem_adi),
                    "kalem_adi_orijinal": kalem.kalem_adi,
                    "oran": 0.0,
                    "istisna_kodu": istisna_kodu,
                    "fatura_no": fatura.fatura_no,
                    "fatura_tarihi": fatura.duzenleme_tarihi,
                    "kaynak_dosya": dosya,
                }


def migrasyonu_calistir(ubls_klasoru: str = UBLS_KLASORU, database_url: str | None = None):
    """outbox faturalarını okuyup gecmis_fatura_kalemleri tablosunu (yeniden) doldurur."""
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
            cur.execute("TRUNCATE TABLE gecmis_fatura_kalemleri RESTART IDENTITY")

            satir_sayisi = 0
            fatura_sayisi = set()
            for satir in _outbox_kalemlerini_topla(ubls_klasoru):
                cur.execute(
                    """
                    INSERT INTO gecmis_fatura_kalemleri
                        (satici_vkn, kalem_adi_normalize, kalem_adi_orijinal,
                         oran, istisna_kodu, fatura_no, fatura_tarihi, kaynak_dosya)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        satir["satici_vkn"],
                        satir["kalem_adi_normalize"],
                        satir["kalem_adi_orijinal"],
                        satir["oran"],
                        satir["istisna_kodu"],
                        satir["fatura_no"],
                        satir["fatura_tarihi"],
                        satir["kaynak_dosya"],
                    ),
                )
                satir_sayisi += 1
                fatura_sayisi.add(satir["kaynak_dosya"])

        conn.commit()
        print(
            f"Tamamlandı: {len(fatura_sayisi)} outbox faturasından "
            f"{satir_sayisi} kalem-oran satırı yazıldı."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    ubls_klasoru = sys.argv[1] if len(sys.argv) > 1 else UBLS_KLASORU
    migrasyonu_calistir(ubls_klasoru)
