"""Şirket API anahtarlarını üretir, listeler ve iptal eder.

entegrasyon/ dizininden, DATABASE_URL tanımlıyken:

    python3 api_anahtari_yonet.py olustur --etiket dis-ekip --vkn 0460351893 --vkn 1111111111
    python3 api_anahtari_yonet.py olustur --etiket yerel-demo --tum-sirketler
    python3 api_anahtari_yonet.py listele
    python3 api_anahtari_yonet.py iptal --etiket dis-ekip
    python3 api_anahtari_yonet.py vkn-ekle --etiket dis-ekip --vkn 2222222222

Her mali müşavire BİR anahtar üretilir (2026-10-01 kararı); müşavirin yeni
bir müşterisi (şirketi) onboard edildiğinde anahtar iptal edilip yeniden
üretilmez — `vkn-ekle` ile mevcut anahtarın kapsamı genişletilir, anahtarın
kendi değeri değişmez, dış ekip elindeki anahtarı güncellemek zorunda kalmaz.

Docker'da: docker compose exec app python3 /app/entegrasyon/api_anahtari_yonet.py ...

Üretilen anahtar YALNIZCA bir kez ekrana yazılır; sistemde sadece özeti
saklanır, kaybedilirse iptal edip yenisi üretilir."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_anahtarlari import (  # noqa: E402
    anahtar_olustur,
    anahtar_vkn_ekle,
    anahtari_iptal_et,
    anahtarlari_listele,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    alt = ap.add_subparsers(dest="komut", required=True)

    olustur = alt.add_parser("olustur", help="Yeni anahtar üret")
    olustur.add_argument("--etiket", required=True, help="Anahtarın kime ait olduğu (audit log'da görünür)")
    kapsam = olustur.add_mutually_exclusive_group(required=True)
    kapsam.add_argument("--vkn", action="append", default=[], help="İzinli şirket VKN'si (tekrarlanabilir)")
    kapsam.add_argument("--tum-sirketler", action="store_true", help="Tüm şirketler adına işlem yapabilir")

    iptal = alt.add_parser("iptal", help="Anahtarı iptal et")
    iptal.add_argument("--etiket", required=True)

    vkn_ekle = alt.add_parser(
        "vkn-ekle", help="Var olan bir anahtarın kapsamına yeni VKN ekle (anahtarın kendisi değişmez)"
    )
    vkn_ekle.add_argument("--etiket", required=True)
    vkn_ekle.add_argument("--vkn", required=True)

    alt.add_parser("listele", help="Anahtarları listele (anahtarın kendisi gösterilmez)")

    args = ap.parse_args()

    if args.komut == "olustur":
        anahtar = anahtar_olustur(args.etiket, args.vkn, tum_sirketler=args.tum_sirketler)
        print(f"Anahtar oluşturuldu ({args.etiket}). Bu değer bir daha gösterilmeyecek:\n\n{anahtar}\n")
    elif args.komut == "iptal":
        if not anahtari_iptal_et(args.etiket):
            raise SystemExit(f"Aktif anahtar bulunamadı: {args.etiket}")
        print(f"İptal edildi: {args.etiket}")
    elif args.komut == "vkn-ekle":
        if not anahtar_vkn_ekle(args.etiket, args.vkn):
            raise SystemExit(f"Aktif anahtar bulunamadı: {args.etiket}")
        print(f"{args.etiket}: {args.vkn} artık yetkili (anahtarın kendisi değişmedi).")
    else:
        for a in anahtarlari_listele():
            kapsam = "TÜM ŞİRKETLER" if a["tum_sirketler"] else ", ".join(a["izinli_vknler"])
            durum = "aktif" if a["aktif"] else "iptal"
            print(f"{a['etiket']:<24} {durum:<6} son kullanım: {a['son_kullanim'] or '-'}  kapsam: {kapsam}")


if __name__ == "__main__":
    main()
