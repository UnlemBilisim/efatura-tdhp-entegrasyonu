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
import re
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


def _mizan_ham_oku(excel_yolu):
    """Excel'i satir satir okuyup (kod, ad) ciftlerine cevirir - HESAP KODU/
    HESAP ADI basliklarini tasiyan satiri otomatik bulup (bkz. _baslik_satirini_bul)
    ondan sonraki satirlardan veri okur. Sutun SIRASI ONBOARDING-VERI-FORMATI.md'de
    belirtilmedigi icin isme gore bulunur, pozisyona gore degil.

    Donen: (satirlar, sayac, okunmayan_sayfalar). `sayac` bu asamada ATILAN satirlari sebebiyle sayar
    (sayi_bicimli / gecersiz_kod / tekrar) - onceden bunlar yalnizca loglaniyordu, is kaydina ulasmiyordu.
    Yalnizca ILK sayfa okunur; diger sayfalar `okunmayan_sayfalar`'da ({"ad","satir"}) raporlanir
    (2026-10-19: onceden hic soylenmeden yok sayiliyorlardi)."""
    import openpyxl

    wb = openpyxl.load_workbook(str(excel_yolu), data_only=True)
    ws = wb[wb.sheetnames[0]]
    okunmayan_sayfalar = [{"ad": ad, "satir": wb[ad].max_row} for ad in wb.sheetnames[1:]]
    baslik_satiri, kod_idx, ad_idx = _baslik_satirini_bul(ws)
    gorulen = set()
    satirlar = []
    sayac = {"sayi_bicimli": 0, "gecersiz_kod": 0, "tekrar": 0}
    ornek = {"sayi_bicimli": [], "gecersiz_kod": [], "tekrar": []}
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
            sayac["sayi_bicimli"] += 1
            ornek["sayi_bicimli"].append(f"satır {row_no}: {kod!r}")
            continue
        if not kod:
            continue
        kod_norm = _kod_normalize(kod)
        if not kod_norm:
            _logger.warning("%s satir %d bos/gecersiz kod, atlandi: %r", excel_yolu, row_no, kod)
            sayac["gecersiz_kod"] += 1
            ornek["gecersiz_kod"].append(f"satır {row_no}: {kod!r}")
            continue
        if kod_norm in gorulen:
            _logger.warning("%s satir %d duplike kod, atlandi: %s", excel_yolu, row_no, kod_norm)
            sayac["tekrar"] += 1
            ornek["tekrar"].append(kod_norm)
            continue
        gorulen.add(kod_norm)
        satirlar.append((kod_norm, (ad or "").strip()))
    sayac["_ornek"] = ornek
    return satirlar, sayac, okunmayan_sayfalar


def _mizan_satirlarini_oku(excel_yolu):
    """Geriye uyumlu ince sarmalayici: yalnizca (kod, ad) satirlari (bkz. _mizan_ham_oku)."""
    return _mizan_ham_oku(excel_yolu)[0]


_ANA_KOD_RE = re.compile(r"[0-9]{3}")
_ORNEK_SAYISI = 5


def mizan_oku(excel_yolu):
    """Excel'deki YAPRAK alt hesapları [(hesap_kodu, ana_kod, hesap_adi)] olarak döner + bir okuma raporu: (satirlar, rapor).
    `yukle()` (ilk kurulum, TRUNCATE+INSERT) ve `core/onboarding_guncelleme.py::mizan_guncelle` (güncelleme, yalnızca fark)
    AYNI okuyucuyu/süzgeci kullanır.

    Kabul kuralı (2026-10-19, kullanıcı kararı — gerçek müşteri mizanı `600.01`, `191.01` gibi 2 parçalı hesaplar içeriyordu ve
    önceki "yalnızca tam 3 parçalı kod" süzgeci bunları SESSİZCE atıyordu): ilk parçası 3 haneli ana kod olan, EN AZ 2 parçalı
    ve dosyada kendisinin alt hesabı (aynı önekle başlayan daha uzun kod) OLMAYAN her kod. Yani:
      * `320`            → ana kod satırı: alınmaz (TDHP_GLOSSARY'de zaten var)           [atlanan.ana_kod]
      * `120.01`         → altında `120.01.001` varsa üst grup: alınmaz, yaprak alınır     [atlanan.ust_grup]
      * `600.01`         → altında alt hesap yoksa YAPRAK: alınır (2 parçalı hesap planı)
      * `120.01.001`     → yaprak: alınır;  `120.01.001.0001` (4 parçalı) → yaprak: alınır
    Atılan satırlar sebebiyle sayılır (`rapor["atlanan"]`), ilk birkaç örnek `rapor["atlanan_ornek"]`'te, okunmayan
    ek sayfalar `rapor["okunmayan_sayfalar"]`'da; şüpheli durumlar `rapor["uyari"]` listesinde (kurulum özetine ve panele gider)."""
    ham, sayac, okunmayan_sayfalar = _mizan_ham_oku(excel_yolu)
    ornek = sayac.pop("_ornek")

    # Her kodun segment sınırlı önekleri: bir kodun önekiyse o kod "üst grup"tur (altında yaprak var).
    onekler = set()
    for kod, _ad in ham:
        parcalar = kod.split(".")
        for i in range(1, len(parcalar)):
            onekler.add(".".join(parcalar[:i]))

    atlanan = {"ana_kod": 0, "ust_grup": 0, "sayi_bicimli": sayac["sayi_bicimli"],
               "gecersiz_kod": sayac["gecersiz_kod"], "tekrar": sayac["tekrar"]}
    kabul, derinlik = [], {}
    for kod, ad in ham:
        parcalar = kod.split(".")
        if not _ANA_KOD_RE.fullmatch(parcalar[0]):
            atlanan["gecersiz_kod"] += 1
            ornek["gecersiz_kod"].append(f"kod: {kod!r}")
        elif len(parcalar) == 1:
            atlanan["ana_kod"] += 1
        elif kod in onekler:
            atlanan["ust_grup"] += 1
            ornek.setdefault("ust_grup", []).append(kod)
        else:
            kabul.append((kod, parcalar[0], ad))
            derinlik[str(len(parcalar))] = derinlik.get(str(len(parcalar)), 0) + 1

    uyari = []
    if okunmayan_sayfalar:
        uyari.append(
            f"Mizan dosyasında ilk sayfadan başka {len(okunmayan_sayfalar)} sayfa var "
            f"({', '.join(s['ad'] for s in okunmayan_sayfalar[:5])}); yalnızca İLK sayfa okunur. "
            "Hesap planı birden fazla sayfaya bölünmüşse hepsini tek sayfada birleştirin."
        )
    if atlanan["sayi_bicimli"]:
        uyari.append(f"{atlanan['sayi_bicimli']} satırın HESAP KODU hücresi sayı biçiminde — atlandı (hücreyi 'Metin' biçimine çevirin).")
    if atlanan["gecersiz_kod"]:
        uyari.append(
            f"{atlanan['gecersiz_kod']} satırın kodu geçersiz (ilk parça 3 haneli rakam olmalı) — atlandı: "
            f"{'; '.join(ornek['gecersiz_kod'][:_ORNEK_SAYISI])}"
        )
    if atlanan["tekrar"]:
        uyari.append(f"{atlanan['tekrar']} tekrar eden hesap kodu atlandı (ilk satır geçerli): {'; '.join(ornek['tekrar'][:_ORNEK_SAYISI])}")
    if not kabul:
        uyari.append("Mizanda alınabilecek alt hesap bulunamadı (3 haneli ana kod satırları alt kırılım sayılmaz).")

    rapor = {
        # HESAP KODU hücresi dolu satırların toplamı: ham okumada alınanlar + ham okumada atılanlar
        "okunan_satir": len(ham) + sayac["sayi_bicimli"] + sayac["gecersiz_kod"] + sayac["tekrar"],
        "kabul_edilen": len(kabul),
        "derinlik": derinlik,
        "atlanan": atlanan,
        "atlanan_ornek": {k: v[:_ORNEK_SAYISI] for k, v in ornek.items() if v and k in ("ust_grup", "gecersiz_kod", "tekrar", "sayi_bicimli")},
        "okunmayan_sayfalar": okunmayan_sayfalar,
        "uyari": uyari,
    }
    return kabul, rapor


def mizan_hesap_satirlari(excel_yolu):
    """Geriye uyumlu ince sarmalayıcı: yalnızca kabul edilen [(hesap_kodu, ana_kod, hesap_adi)] (bkz. `mizan_oku`)."""
    return mizan_oku(excel_yolu)[0]


def yukle(vkn: str, excel_yolu: str, database_url: str | None = None) -> int:
    """Geriye uyumlu sarmalayici: yazilan satir sayisini doner (bkz. `yukle_ayrintili`)."""
    return yukle_ayrintili(vkn, excel_yolu, database_url)[0]


def yukle_ayrintili(vkn: str, excel_yolu: str, database_url: str | None = None):
    """Excel'deki YAPRAK alt hesaplari tenant_<vkn>.mizan_alt_kirilim tablosuna
    yazar (TRUNCATE + INSERT) ve (yazilan_satir_sayisi, okuma_raporu) doner. Hangi satirlarin
    alinip hangilerinin atildigi `mizan_oku` docstring'inde (2026-10-19'dan once yalnizca tam
    3 parcali kodlar aliniyordu; 2 parcali `600.01` gibi hesaplar sessizce atiliyordu)."""
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
    satirlar, rapor = mizan_oku(excel_yolu)

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

    atlanan = {k: v for k, v in rapor["atlanan"].items() if v}
    print(f"Tamamlandı: {sema}.mizan_alt_kirilim'e {len(satirlar)} satır yazıldı"
          f" (dosyada {rapor['okunan_satir']} kodlu satır; atlanan: {atlanan or 'yok'}).")
    for u in rapor["uyari"]:
        print(f"  Uyarı: {u}")
    return len(satirlar), rapor


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vkn", required=True, help="Şirketin VKN'si (10 hane, tenant_<vkn> şeması hedeflenir)")
    ap.add_argument("--excel", required=True, help="mizan.xlsx dosyasının yolu")
    args = ap.parse_args()
    yukle(args.vkn, args.excel)


if __name__ == "__main__":
    main()
