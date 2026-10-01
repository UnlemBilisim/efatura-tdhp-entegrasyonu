#!/usr/bin/env python3
"""Yeni bir musteriyi (sirket) tek komutla sisteme ekler: PostgreSQL semasi +
mizan + gecmis fatura/yevmiye verisinden RAG emsal havuzu.

2 gunluk canliya cikis hazirligi (2026-09-29) icin: ayni anda 5-10 musteri
gelecek, her biri icin su klasor yapisi beklenir:

    <onboarding-kok>/<vkn>/
        mizan.xlsx              (zorunlu)
        faturalar/*.xml         (zorunlu - son 6 ayin fatura XML'leri)
        yevmiye.xlsx VEYA .csv  (zorunlu - bkz. scripts/yevmiye_fatura_esle.py
                                  basindaki sutun aciklamasi)

Sirayla yapar (herhangi bir adim basarisiz olursa DURUR, sonraki adimlara
GECMEZ - yari tamamlanmis bir onboarding'in fark edilmeden kalmasini onlemek
icin):
    1. tenant_<vkn> semasi + migration'lar (Mcp_mimarisi/scripts/tenant_onboarding.py)
    2. Mizan yukleme (model_eval/mizan_excel_yukle.py)
    3. Fatura XML'lerini yevmiye kaydiyla eslestirip ground-truth JSON uret
       (model_eval/scripts/yevmiye_fatura_esle.py)
    4. Uretilen JSON'lari bu musterinin RAG koleksiyonuna indeksle
       (model_eval/build_vector_db.py --own-vkn <vkn>)

Kullanim (proje kokunden, DATABASE_URL tanimliyken):

    DATABASE_URL=postgresql://efatura:sifre@localhost:5434/efatura_kdv \\
        python3 scripts/musteri_onboard_toplu.py --onboarding-kok onboarding/

Bu, onboarding/ altindaki HER alt klasoru (klasor adi = VKN) sirayla isler.
Tek bir musteri icin: --vkn 1234567890 --onboarding-kok onboarding/ ile
sadece o alt klasoru isler.

Idempotent'tir: her alt adim kendi script'inin idempotent davranisina
sahiptir (sema CREATE IF NOT EXISTS, mizan TRUNCATE+INSERT, RAG upsert) -
ayni musteriyi tekrar calistirmak veri bozmaz, gunceller."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "Mcp_mimarisi" / "scripts"))
sys.path.insert(0, str(ROOT_DIR / "model_eval"))
sys.path.insert(0, str(ROOT_DIR / "model_eval" / "scripts"))


class OnboardHatasi(Exception):
    """Bir alt adim basarisiz oldugunda firlatilir - hangi adimda/hangi
    musteride durduğu net olsun diye ayri bir tip (generic Exception degil)."""


def _nace_kodlarini_oku(musteri_dizini: Path) -> list[str]:
    """nace.txt opsiyoneldir (her satirda bir NACE kodu, bos satirlar/#
    yorumlari atlanir). Yoksa bos liste doner - onboard_et() bu durumda
    zaten kendi uyarisini basar, burada AYRICA hata verilmez."""
    nace_dosyasi = musteri_dizini / "nace.txt"
    if not nace_dosyasi.exists():
        return []
    satirlar = nace_dosyasi.read_text(encoding="utf-8").splitlines()
    return [s.strip() for s in satirlar if s.strip() and not s.strip().startswith("#")]


def _musteri_dosyalarini_dogrula(musteri_dizini: Path) -> tuple[Path, Path, Path]:
    mizan = musteri_dizini / "mizan.xlsx"
    faturalar = musteri_dizini / "faturalar"
    yevmiye_xlsx = musteri_dizini / "yevmiye.xlsx"
    yevmiye_csv = musteri_dizini / "yevmiye.csv"
    yevmiye = yevmiye_xlsx if yevmiye_xlsx.exists() else yevmiye_csv

    eksikler = []
    if not mizan.exists():
        eksikler.append(f"mizan.xlsx ({mizan})")
    if not faturalar.is_dir() or not list(faturalar.glob("*.xml")):
        eksikler.append(f"faturalar/*.xml ({faturalar})")
    if not yevmiye.exists():
        eksikler.append(f"yevmiye.xlsx veya yevmiye.csv ({musteri_dizini})")
    if eksikler:
        raise OnboardHatasi(f"{musteri_dizini.name}: eksik dosya(lar): {'; '.join(eksikler)}")
    return mizan, faturalar, yevmiye


def _musteriyi_onboard_et(vkn: str, musteri_dizini: Path, database_url: str) -> dict:
    mizan_yolu, faturalar_dizini, yevmiye_yolu = _musteri_dosyalarini_dogrula(musteri_dizini)
    nace_kodlari = _nace_kodlarini_oku(musteri_dizini)

    print(f"\n{'=' * 60}\n{vkn} icin onboarding basliyor ({musteri_dizini})\n{'=' * 60}")

    print(f"\n--- [1/4] {vkn}: sema + migration + NACE ---")
    from tenant_onboarding import onboard_et  # noqa: E402

    onboard_et(vkn, database_url, nace_kodlari=nace_kodlari)

    print(f"\n--- [2/4] {vkn}: mizan yukleniyor ---")
    from mizan_excel_yukle import yukle as mizan_yukle  # noqa: E402

    mizan_satir_sayisi = mizan_yukle(vkn, str(mizan_yolu), database_url=database_url)

    print(f"\n--- [3/4] {vkn}: fatura XML'leri yevmiye ile eslestiriliyor ---")
    from yevmiye_fatura_esle import esle_ve_uret  # noqa: E402

    cikti_dizini = musteri_dizini / ".jsons_uretilen"
    ozet = esle_ve_uret(vkn, faturalar_dizini, yevmiye_yolu, cikti_dizini)

    print(f"\n--- [4/4] {vkn}: RAG koleksiyonu olusturuluyor ---")
    if ozet["eslesen"] == 0:
        print(
            "  Uyari: hicbir fatura yevmiye ile eslesmedi, RAG adimi ATLANDI "
            "(build_vector_db.py bos veri setiyle calismaz)."
        )
    else:
        from build_vector_db import index_directory  # noqa: E402

        index_directory(own_vkn=vkn, data_dir=cikti_dizini)

    if ozet["yon_belirsiz_atlanan"]:
        print(
            f"\n!!! DIKKAT {vkn}: {len(ozet['yon_belirsiz_atlanan'])} faturada VKN "
            f"({vkn}) ne alici ne satici tarafinda bulunamadi - YANLIS VKN girilmis "
            f"OLABILIR. Bu faturalar RAG'a yazilmadi: {ozet['yon_belirsiz_atlanan'][:5]}"
        )

    return {
        "vkn": vkn, "mizan_satir_sayisi": mizan_satir_sayisi,
        "fatura_eslesme": f"{ozet['eslesen']}/{ozet['toplam_xml']}",
        "esiy_yevmiyede_var_xml_de_yok": len(ozet["yevmiyede_var_xml_de_yok"]),
        "esiy_xml_de_var_yevmiyede_yok": len(ozet["xml_de_var_yevmiyede_yok"]),
        "yon_belirsiz": len(ozet["yon_belirsiz_atlanan"]),
        "nace_kodlari": nace_kodlari,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onboarding-kok", required=True, type=Path, help="Alt klasorleri VKN olan kok dizin")
    ap.add_argument("--vkn", default=None, help="Sadece bu VKN'yi isle (verilmezse kok altindaki HEPSI islenir)")
    args = ap.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL env var tanimli degil.")

    if not args.onboarding_kok.is_dir():
        raise SystemExit(f"Onboarding kok dizini bulunamadi: {args.onboarding_kok}")

    if args.vkn:
        musteri_dizinleri = [args.onboarding_kok / args.vkn]
    else:
        musteri_dizinleri = sorted(p for p in args.onboarding_kok.iterdir() if p.is_dir())

    if not musteri_dizinleri:
        raise SystemExit(f"{args.onboarding_kok} altinda islenecek musteri klasoru yok.")

    basarili, basarisiz = [], []
    for musteri_dizini in musteri_dizinleri:
        vkn = musteri_dizini.name
        try:
            sonuc = _musteriyi_onboard_et(vkn, musteri_dizini, database_url)
            basarili.append(sonuc)
        except OnboardHatasi as exc:
            print(f"\n!!! {vkn} ATLANDI (dosya eksik): {exc}", file=sys.stderr)
            basarisiz.append((vkn, str(exc)))
        except Exception as exc:  # noqa: BLE001
            print(f"\n!!! {vkn} BASARISIZ: {exc}", file=sys.stderr)
            basarisiz.append((vkn, str(exc)))

    print(f"\n{'=' * 60}\nOZET\n{'=' * 60}")
    print(f"Basarili: {len(basarili)}/{len(musteri_dizinleri)}")
    for s in basarili:
        print(
            f"  {s['vkn']}: mizan {s['mizan_satir_sayisi']} satir, "
            f"fatura eslesme {s['fatura_eslesme']}, "
            f"esiy(yevmiyede var xml yok)={s['esiy_yevmiyede_var_xml_de_yok']}, "
            f"esiy(xml var yevmiyede yok)={s['esiy_xml_de_var_yevmiyede_yok']}, "
            f"yon_belirsiz={s['yon_belirsiz']}, "
            f"nace={s['nace_kodlari'] or '(YOK - on filtre calismaz!)'}"
        )
    if basarisiz:
        print(f"\nBasarisiz/atlandi: {len(basarisiz)}")
        for vkn, hata in basarisiz:
            print(f"  {vkn}: {hata}")
        sys.exit(1)


if __name__ == "__main__":
    main()
