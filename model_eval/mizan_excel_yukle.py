#!/usr/bin/env python3
"""Sirkete ozel mizan.xlsx dosyasini PostgreSQL'e (mizan_alt_kirilim tablosu,
tenant_<vkn> semasi) yukler (2026-08-05, Excel'den DB'ye tasima).

Kullanici karari: "her kullanicinin farkli mizan bilgisi olduğu icin buna
gore bir yapi tasarlamamiz lazim" - core/mizan.py::get_alt_kirilimlar() artik
Excel degil bu tabloyu okuyor (bkz. core/mizan.py docstring'i).

Bir kereye mahsus/idempotent calistirilir: hedef semadaki mizan_alt_kirilim
tablosunu TRUNCATE edip Excel'i yeniden yukler - Excel guncellenirse script
tekrar calistirilarak DB senkron tutulur. Ayirici tutarsizligi (tire/bosluk)
core/mizan.py::_kod_normalize ile giderilir, duplike/bos kodlar loglanarak
atlanir (eski Excel-okuma davranisiyla AYNI, sadece hedef Excel'den DB'ye
degisti).

Kullanim (model_eval kokunden):

    DATABASE_URL=postgresql://efatura:sifre@localhost:5434/efatura_kdv \\
        python3 mizan_excel_yukle.py --vkn 0460351893 --excel exceller/mizan.xlsx
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.mizan import _kod_normalize

_logger = logging.getLogger(__name__)


def _sutun_adi_normalize(ad) -> str:
    return str(ad).strip().upper().replace("İ", "I")


def _baslik_satirini_bul(ws):
    """'HESAP KODU' ve 'HESAP ADI' basliklarini tasiyan satiri arar - dis
    ekibin gonderdigi mizan.xlsx'te bu satirin kacinci satir oldugu sabit
    degil (2026-09-30, gercek bug: kod once min_row=7 sabitiydi - bu sadece
    Archive2/mizan.xlsx'in kendi formatina, ustunde 5 bos satir olmasina
    ozguydu; standart formatta - 1. satir baslik - gonderilen bir mizan
    SESSIZCE 0 satir okunuyordu, hic hata vermiyordu. ONBOARDING-VERI-FORMATI.md
    'veri, baslik satirindan sonraki satirdan itibaren okunur' diyor - bu,
    basligin herhangi bir satirda olabilecegini ima ediyor, koddaki sabit
    satir numarasiyla CELISIYORDU). En fazla ilk 20 satira bakilir - normal
    bir mizan dosyasinda basligin bundan daha asagida olmasi beklenmez,
    olursa acik hatayla durulur (sessiz 0 satir yerine)."""
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
        basliklar = {_sutun_adi_normalize(h) for h in row if h}
        if "HESAP KODU" in basliklar and "HESAP ADI" in basliklar:
            kod_idx = next(i for i, h in enumerate(row) if h and _sutun_adi_normalize(h) == "HESAP KODU")
            ad_idx = next(i for i, h in enumerate(row) if h and _sutun_adi_normalize(h) == "HESAP ADI")
            return row_idx, kod_idx, ad_idx
    raise SystemExit(
        "mizan.xlsx'te 'HESAP KODU' ve 'HESAP ADI' başlıklarını taşıyan bir "
        "satır bulunamadı (ilk 20 satır tarandı) - dosya formatını kontrol edin."
    )


def _mizan_satirlarini_oku(excel_yolu):
    """Excel'i satir satir okuyup (kod, ad) ciftlerine cevirir - HESAP KODU/
    HESAP ADI basliklarini tasiyan satiri otomatik bulup (bkz. _baslik_satirini_bul)
    ondan sonraki satirlardan veri okur. Sutun SIRASI ONBOARDING-VERI-FORMATI.md'de
    belirtilmedigi icin isme gore bulunur, pozisyona gore degil."""
    import openpyxl

    wb = openpyxl.load_workbook(str(excel_yolu), data_only=True)
    ws = wb[wb.sheetnames[0]]
    baslik_satiri, kod_idx, ad_idx = _baslik_satirini_bul(ws)
    gorulen = set()
    satirlar = []
    for row_no, row in enumerate(ws.iter_rows(min_row=baslik_satiri + 1, values_only=True), start=baslik_satiri + 1):
        kod = row[kod_idx] if row and len(row) > kod_idx else None
        ad = row[ad_idx] if row and len(row) > ad_idx else None
        if kod is not None and not isinstance(kod, str):
            # Hucre "sayi" bicimindeyse (ornegin 320 metin degil sayi olarak
            # girilmisse) bu satir sessizce kaybolurdu - 2026-09-30, teslim
            # paketi son kontrolunde bulundu (ONBOARDING-VERI-FORMATI.md'ye
            # "hucre metin olmali" uyarisi eklendi, burada da loglaniyor).
            _logger.warning(
                "%s satir %d HESAP KODU hucresi metin degil (%s: %r) - atlandi, "
                "hucreyi Excel'de 'Metin' bicimine cevirin",
                excel_yolu, row_no, type(kod).__name__, kod,
            )
            continue
        if not kod:
            continue
        kod_norm = _kod_normalize(kod)
        if not kod_norm:
            _logger.warning("%s satir %d bos/gecersiz kod, atlandi: %r", excel_yolu, row_no, kod)
            continue
        if kod_norm in gorulen:
            _logger.warning("%s satir %d duplike kod, atlandi: %s", excel_yolu, row_no, kod_norm)
            continue
        gorulen.add(kod_norm)
        satirlar.append((kod_norm, (ad or "").strip()))
    return satirlar


def yukle(vkn: str, excel_yolu: str, database_url: str | None = None) -> int:
    """Excel'deki tum satirlari tenant_<vkn>.mizan_alt_kirilim tablosuna
    yazar (TRUNCATE + INSERT). Sadece 3-seviyeli kodlar (XXX.YY.ZZZZZ) DB'ye
    yazilir - ust seviye ozet satirlari (sadece "191" gibi) atlanir, get_alt_kirilimlar
    onlari zaten kullanmiyordu (bkz. core/mizan.py eski gruplama mantigi)."""
    import psycopg2
    from psycopg2 import sql

    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "DATABASE_URL env var tanimli degil - orn. "
            "postgresql://efatura:sifre@localhost:5434/efatura_kdv"
        )
    if not vkn.isdigit() or len(vkn) != 10:
        raise SystemExit(f"Gecersiz VKN: {vkn!r} - 10 haneli sayisal olmali")

    sema = f"tenant_{vkn}"
    satirlar = [
        (kod, kod.split(".")[0], ad)
        for kod, ad in _mizan_satirlarini_oku(excel_yolu)
        if len(kod.split(".")) == 3 and len(kod.split(".")[0]) == 3
    ]

    from core.db import tenant_kayitli_mi

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            # Şema yoksa search_path sessizce public'e düşer ve mizan başka
            # şirketin tablosuna yazılırdı.
            if not tenant_kayitli_mi(vkn, cur=cur):
                raise SystemExit(
                    f"{sema} şeması yok - önce şirketi onboard edin: "
                    f"python3 Mcp_mimarisi/scripts/tenant_onboarding.py --vkn {vkn}"
                )
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(sema)))
            cur.execute("TRUNCATE TABLE mizan_alt_kirilim")
            for hesap_kodu, ana_kod, hesap_adi in satirlar:
                cur.execute(
                    """
                    INSERT INTO mizan_alt_kirilim (hesap_kodu, ana_kod, hesap_adi)
                    VALUES (%s, %s, %s)
                    """,
                    (hesap_kodu, ana_kod, hesap_adi),
                )
        conn.commit()
    finally:
        conn.close()

    print(f"Tamamlandı: {sema}.mizan_alt_kirilim'e {len(satirlar)} satır yazıldı.")
    return len(satirlar)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vkn", required=True, help="Şirketin VKN'si (10 hane, tenant_<vkn> şeması hedeflenir)")
    ap.add_argument("--excel", required=True, help="mizan.xlsx dosyasının yolu")
    args = ap.parse_args()
    yukle(args.vkn, args.excel)


if __name__ == "__main__":
    main()
