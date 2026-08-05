"""Aküzülü'nün (VKN 0460351893) public şemadaki verisini tenant_0460351893'e
taşır (2026-07-30, çoklu şirket geçişi, TEK SEFERLİK göç scripti).

Bu, geri alınması güç bir production veri işlemidir. Kullanıcı kararı
(2026-07-30): veri KOPYALANIR (public silinmez), doğrulama yapılır, silme
AYRI bir adım/onayla yapılır — bu script SİLME içermez, sadece kopyalar.

nace_oranlari BU GÖÇE DAHİL DEĞİL — o paylaşılan mevzuat referans tablosu,
public'te kalır (bkz. Mcp_mimarisi CLAUDE.md, migration 9846b14dc658).

Adımlar:
1. tenant_0460351893 şemasını oluştur + migration'ları çalıştır (boş tablolar)
   — bkz. scripts/tenant_onboarding.py (bu script onu çağırır).
2. public.gecmis_fatura_kalemleri, public.islenmis_faturalar,
   public.model_eval_sonuclar'ı ilgili tenant tablolarına INSERT ile kopyala.
3. Satır sayılarını karşılaştırarak doğrula.
4. Özet rapor yazdır — public tabloları SİLMEZ, bu ayrı bir karar/adımdır.

Çalıştırma (Mcp_mimarisi kökünden, --dry-run ile önce deneyin):

    DATABASE_URL=postgresql://user:pass@localhost:5432/efatura_kdv \\
        python3 scripts/akyuzlu_public_to_tenant_gocu.py --dry-run

    DATABASE_URL=... python3 scripts/akyuzlu_public_to_tenant_gocu.py --calistir
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from tenant_onboarding import onboard_et  # noqa: E402

AKUZULU_VKN = "0460351893"
TENANT_SEMASI = f"tenant_{AKUZULU_VKN}"

# model_eval_sonuclar model_eval'in tablosu, satici_vkn kolonu yok - o yuzden
# TUM public.model_eval_sonuclar tenant'a kopyalanir (bu DB'de zaten sadece
# Akuzulu'nun kayitlari var - coklu sirket gecisinden ONCE tek sirket
# calisiyordu). Diger iki tablo satici_vkn'e gore FILTRELENEREK kopyalanir
# (ileride ayni public semada baska VKN'nin kalinti verisi olursa karismasin).
TASINACAK_TABLOLAR = [
    ("gecmis_fatura_kalemleri", "satici_vkn"),
    ("islenmis_faturalar", None),  # fatura_no PK, VKN kolonu yok - tumu tasinir
    ("model_eval_sonuclar", None),  # VKN kolonu yok - tumu tasinir
]


def _satir_sayisi(conn, sema, tablo):
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(sql.Identifier(sema), sql.Identifier(tablo)))
        return cur.fetchone()[0]


def _public_kolonlari(conn, tablo):
    """public.<tablo>'nun sütun adlarını sırayla döner - `INSERT ... SELECT *`
    sütun İSMİNE değil POZİSYONA göre eşleşir; tenant şemasındaki tablo
    Alembic migration'ında farklı bir sütun sırasıyla tanımlandığı için
    (public'te istisna_kodu en sonda, tenant'ta fatura_no'dan önce) `SELECT *`
    kullanmak fatura_tarihi/istisna_kodu değerlerini birbirine karıştırıyordu
    (DatatypeMismatch ile yakalandı, canlıda veri karışmadan durduruldu).
    Bu yüzden sütun listesi HER İKİ tarafta da açıkça belirtiliyor."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (tablo,),
        )
        return [row[0] for row in cur.fetchall()]


def _kopyala(conn, tablo, vkn_kolonu, dry_run):
    kaynak_sayi = _satir_sayisi(conn, "public", tablo)
    if vkn_kolonu:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM public.{} WHERE {} = %s").format(
                    sql.Identifier(tablo), sql.Identifier(vkn_kolonu)
                ),
                (AKUZULU_VKN,),
            )
            tasinacak_sayi = cur.fetchone()[0]
    else:
        tasinacak_sayi = kaynak_sayi

    print(f"  public.{tablo}: {kaynak_sayi} satır (taşınacak: {tasinacak_sayi})")
    if dry_run:
        return tasinacak_sayi

    kolonlar = _public_kolonlari(conn, tablo)
    kolon_listesi = sql.SQL(", ").join(sql.Identifier(k) for k in kolonlar)

    with conn.cursor() as cur:
        if vkn_kolonu:
            cur.execute(
                sql.SQL("INSERT INTO {}.{} ({kolonlar}) SELECT {kolonlar} FROM public.{} WHERE {} = %s").format(
                    sql.Identifier(TENANT_SEMASI), sql.Identifier(tablo),
                    sql.Identifier(tablo), sql.Identifier(vkn_kolonu),
                    kolonlar=kolon_listesi,
                ),
                (AKUZULU_VKN,),
            )
        else:
            cur.execute(
                sql.SQL("INSERT INTO {}.{} ({kolonlar}) SELECT {kolonlar} FROM public.{}").format(
                    sql.Identifier(TENANT_SEMASI), sql.Identifier(tablo), sql.Identifier(tablo),
                    kolonlar=kolon_listesi,
                )
            )
    return tasinacak_sayi


def calistir(database_url: str, dry_run: bool) -> None:
    print(f"=== Aküzülü göçü ({'DRY-RUN' if dry_run else 'GERÇEK ÇALIŞTIRMA'}) ===\n")

    print(f"[1/3] Tenant şeması hazırlanıyor: {TENANT_SEMASI}")
    if dry_run:
        print("  (dry-run: onboard_et() atlandı, sadece kopyalama sayıları gösterilecek)")
    else:
        onboard_et(AKUZULU_VKN, database_url)

    print("\n[2/3] Veri kopyalanıyor:")
    conn = psycopg2.connect(database_url)
    try:
        beklenen = {}
        for tablo, vkn_kolonu in TASINACAK_TABLOLAR:
            beklenen[tablo] = _kopyala(conn, tablo, vkn_kolonu, dry_run)
        if not dry_run:
            conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    if dry_run:
        conn.close()
        print("\n[3/3] Dry-run tamamlandı — hiçbir şey yazılmadı.")
        return

    print("\n[3/3] Doğrulama:")
    tum_dogru = True
    for tablo, _ in TASINACAK_TABLOLAR:
        tenant_sayi = _satir_sayisi(conn, TENANT_SEMASI, tablo)
        beklenen_sayi = beklenen[tablo]
        durum = "OK" if tenant_sayi == beklenen_sayi else "UYUŞMAZLIK"
        if tenant_sayi != beklenen_sayi:
            tum_dogru = False
        print(f"  {TENANT_SEMASI}.{tablo}: {tenant_sayi} satır (beklenen: {beklenen_sayi}) [{durum}]")
    conn.close()

    if tum_dogru:
        print(
            "\nGöç tamamlandı, satır sayıları eşleşiyor. public tabloları SİLİNMEDİ "
            "— bu script silme yapmaz, ayrı bir onay adımı olarak elle yapılmalı."
        )
    else:
        print(
            "\nUYARI: satır sayıları eşleşmiyor — public tabloları SİLMEDEN önce "
            "durumu manuel inceleyin.", file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    grup = ap.add_mutually_exclusive_group(required=True)
    grup.add_argument("--dry-run", action="store_true", help="Hiçbir şey yazmadan sadece satır sayılarını göster")
    grup.add_argument("--calistir", action="store_true", help="Göçü gerçekten çalıştır (veri yazar)")
    args = ap.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL env var tanımlı değil.", file=sys.stderr)
        sys.exit(1)

    calistir(database_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
