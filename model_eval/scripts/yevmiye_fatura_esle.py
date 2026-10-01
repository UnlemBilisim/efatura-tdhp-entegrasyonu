#!/usr/bin/env python3
"""Yeni musteri onboarding'i icin: fatura XML'lerini yevmiye kaydiyla (gercek
muhasebe kaydiyla) fatura numarasina gore eslestirip build_vector_db.py'nin
okuyacagi Archive2/jsons formatinda ground-truth JSON dosyalari uretir.

Neden gerekli: build_vector_db.py SADECE ayni JSON icinde hem fatura hem
accounting_entries olan dosyalari indeksleyebilir (RAG bir fatura+kayit CIFTI
uzerinden ogreniyor). Dis ekipten/muhasebeciden gelen veri iki AYRI kaynakta
geliyor - fatura XML'leri ve yevmiye dokumu (xlsx/csv) - bu script ikisini
fatura numarasina gore birlestirip tek JSON'a cevirir.

Yevmiye dosyasi beklenen sutunlar (xlsx/csv, baslik satiri ZORUNLU):
    fatura_no, hesap_kodu, hesap_adi, borc_alacak, tutar
(sutun adlari kucuk/buyuk harf ve alt cizgi/bosluk farkina duyarli degildir,
bkz. _SUTUN_ESLEMELERI - "Fatura No", "Hesap Kodu" gibi varyantlar da kabul
edilir.)

Kullanim (model_eval kokunden):

    python3 scripts/yevmiye_fatura_esle.py \\
        --own-vkn 1122334455 \\
        --fatura-dizini onboarding/1122334455/faturalar \\
        --yevmiye-dosyasi onboarding/1122334455/yevmiye.xlsx \\
        --cikti-dizini onboarding/1122334455/jsons_uretilen

Ciktidaki JSON'lar daha sonra build_vector_db.py'ye --data-dir olarak verilir
(bkz. scripts/musteri_onboard_toplu.py, bu script'i otomatik cagirir)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.parsing import normalize_code3, normalize_dc, parse_invoice_xml  # noqa: E402

_SUTUN_ESLEMELERI = {
    "fatura_no": {"fatura_no", "faturano", "fatura no", "belge_no", "belgeno", "belge no", "invoice_id", "invoice no"},
    "hesap_kodu": {"hesap_kodu", "hesapkodu", "hesap kodu", "account_code"},
    "hesap_adi": {"hesap_adi", "hesapadi", "hesap adi", "account_name"},
    "borc_alacak": {"borc_alacak", "borcalacak", "borc/alacak", "borc alacak", "dc", "yon"},
    "tutar": {"tutar", "amount", "miktar"},
}


def _sutun_adi_normalize(ad: str) -> str:
    return str(ad).strip().lower().replace("İ", "i").replace("ı", "i")


def _sutun_indekslerini_bul(baslik_satiri: list) -> dict[str, int]:
    """Serbest bicimli baslik satirindan zorunlu 5 sutunun indeksini cikarir.
    Eksik bir sutun varsa acik bir hatayla durur - sessizce yanlis sutunu
    kullanmaz (ornegin 'tutar' sutunu bulunamayip 'hesap_adi' sanilmaz)."""
    normalize_edilmis = {_sutun_adi_normalize(h): i for i, h in enumerate(baslik_satiri) if h}
    sonuc = {}
    eksikler = []
    for alan, varyantlar in _SUTUN_ESLEMELERI.items():
        bulundu = next((normalize_edilmis[v] for v in varyantlar if v in normalize_edilmis), None)
        if bulundu is None:
            eksikler.append(alan)
        else:
            sonuc[alan] = bulundu
    if eksikler:
        raise SystemExit(
            f"Yevmiye dosyasinda zorunlu sutun(lar) bulunamadi: {', '.join(eksikler)}. "
            f"Baslik satirinda bulunanlar: {baslik_satiri}"
        )
    return sonuc


def _yevmiye_satirlarini_oku(yevmiye_yolu: Path) -> dict[str, list[dict]]:
    """Yevmiye dosyasini okuyup fatura_no -> [{"account_code","account_name","amount","dc"}, ...]
    sozlugune cevirir. xlsx ve csv ikisini de destekler (uzantiya gore secilir)."""
    if yevmiye_yolu.suffix.lower() == ".csv":
        import csv

        with open(yevmiye_yolu, newline="", encoding="utf-8-sig") as f:
            satirlar = list(csv.reader(f))
    else:
        import openpyxl

        wb = openpyxl.load_workbook(str(yevmiye_yolu), data_only=True)
        satirlar = [list(row) for row in wb.worksheets[0].iter_rows(values_only=True)]

    if not satirlar:
        raise SystemExit(f"Yevmiye dosyasi bos: {yevmiye_yolu}")

    idx = _sutun_indekslerini_bul(satirlar[0])
    gruplu = defaultdict(list)
    atlanan = 0
    for satir_no, satir in enumerate(satirlar[1:], start=2):
        if not satir or all(h in (None, "") for h in satir):
            continue
        fatura_no = str(satir[idx["fatura_no"]] or "").strip()
        kod = normalize_code3(satir[idx["hesap_kodu"]])
        dc = normalize_dc(satir[idx["borc_alacak"]])
        tutar_ham = satir[idx["tutar"]]
        if not fatura_no or not kod or not dc or tutar_ham in (None, ""):
            print(f"  Uyari: satir {satir_no} eksik/gecersiz alan icin atlandi: {satir}", file=sys.stderr)
            atlanan += 1
            continue
        gruplu[fatura_no].append({
            "account_code": str(satir[idx["hesap_kodu"]]).strip(),
            "account_name": str(satir[idx["hesap_adi"]] or "").strip(),
            "amount": str(tutar_ham),
            "dc": "Borç" if dc == "Borc" else "Alacak",
        })
    print(f"Yevmiye dosyasindan {len(gruplu)} farkli fatura no icin kayit okundu ({atlanan} satir atlandi).")
    return gruplu


def _fatura_baslik_json(invoice: dict) -> dict:
    """parse_invoice_xml() ciktisindan Archive2/jsons formatindaki "header"
    blogunu uretir - alan adlari/format AYNEN uyusmali (bkz. Archive2/jsons
    ornekleri), aksi halde build_vector_db.py bu dosyayi ground-truth'suz
    sanip atlar ya da yanlis okur."""
    h = invoice["header"]
    para = h.get("currency") or "TRY"

    def _parali(deger):
        return f"{deger} {para}" if deger not in (None, "") else None

    return {
        "account_title": h.get("account_title") or "",
        "account_tax_number": h.get("account_tax_number") or "",
        "invoice_id": invoice["invoice_id"],
        "issue_date": h.get("issue_date"),
        "currency": para,
        "invoice_type": h.get("invoice_type") or "",
        "allowance_total": _parali(h.get("allowance_total")) or f"0.00 {para}",
        "tax_exclusive": _parali(h.get("tax_exclusive")),
        "tax_inclusive": _parali(h.get("tax_inclusive")),
        "payable": _parali(h.get("payable")),
    }


def esle_ve_uret(own_vkn: str, fatura_dizini: Path, yevmiye_dosyasi: Path, cikti_dizini: Path) -> dict:
    """Ana fonksiyon - test'ler dogrudan bunu cagirir. XML'leri okur, yevmiye
    ile fatura numarasina gore eslestirir, eslesen her fatura icin Archive2/
    jsons formatinda bir JSON dosyasi yazar. Eslesmeyenleri SESSIZCE atlamaz -
    ozet raporda acikca sayar (kullanici veri kaybini fark edebilsin diye)."""
    cikti_dizini.mkdir(parents=True, exist_ok=True)
    yevmiye_by_fatura = _yevmiye_satirlarini_oku(yevmiye_dosyasi)

    xml_dosyalari = sorted(fatura_dizini.glob("*.xml"))
    if not xml_dosyalari:
        raise SystemExit(f"{fatura_dizini} icinde .xml fatura bulunamadi.")

    eslesen = 0
    xml_de_var_yevmiyede_yok = []
    yon_belirsiz_atlanan = []
    yazilan_dosyalar = []
    xml_fatura_no_listesi = set()
    for xml_yolu in xml_dosyalari:
        invoice = parse_invoice_xml(xml_yolu, own_vkn=own_vkn)
        fatura_no = invoice["invoice_id"]
        xml_fatura_no_listesi.add(fatura_no)

        # own_vkn faturanin ne alicisinda ne saticisinda bulunamadiysa
        # (parse_invoice_xml'in direction_uncertain=True isaretledigi durum)
        # bu faturayi RAG'a YAZMAYIZ - yanlis yon (inbox/outbox) etiketiyle
        # emsal havuzunu kirletmek, "yanlis VKN girilmis" hatasini sessizce
        # gizler (2026-09-29, toplu onboard testinde gozlemlendi).
        if invoice.get("direction_uncertain"):
            yon_belirsiz_atlanan.append(fatura_no)
            continue

        entries = yevmiye_by_fatura.get(fatura_no)
        if not entries:
            xml_de_var_yevmiyede_yok.append(fatura_no)
            continue

        cikti = {
            "header": _fatura_baslik_json(invoice),
            "taxes": [
                {"name": t.get("name") or "", "code": t.get("code") or "", "percent": str(t.get("percent") or "0"),
                 "tax": f"{t.get('tax')} {invoice['header'].get('currency') or 'TRY'}" if t.get("tax") is not None else None,
                 "exemption": {}}
                for t in invoice.get("taxes", [])
            ],
            "accounting_entries": entries,
            "lines": [
                {"product_name": ln.get("product_name") or "", "quantity": ln.get("quantity") or "",
                 "total": f"{ln.get('total')} {invoice['header'].get('currency') or 'TRY'}" if ln.get("total") is not None else None}
                for ln in invoice.get("lines", [])
            ],
            "notes": invoice.get("notes", []),
        }
        hedef = cikti_dizini / f"{fatura_no}.json"
        hedef.write_text(json.dumps(cikti, ensure_ascii=False, indent=2), encoding="utf-8")
        yazilan_dosyalar.append(hedef)
        eslesen += 1

    yevmiyede_var_xml_de_yok = sorted(set(yevmiye_by_fatura) - xml_fatura_no_listesi)

    ozet = {
        "toplam_xml": len(xml_dosyalari),
        "toplam_yevmiye_fatura": len(yevmiye_by_fatura),
        "eslesen": eslesen,
        "xml_de_var_yevmiyede_yok": xml_de_var_yevmiyede_yok,
        "yevmiyede_var_xml_de_yok": yevmiyede_var_xml_de_yok,
        "yon_belirsiz_atlanan": yon_belirsiz_atlanan,
        "cikti_dizini": str(cikti_dizini),
    }
    return ozet


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--own-vkn", required=True, help="Yon tespiti (inbox/outbox) icin sirketin kendi VKN'si")
    ap.add_argument("--fatura-dizini", required=True, type=Path, help="Fatura XML'lerinin bulundugu klasor")
    ap.add_argument("--yevmiye-dosyasi", required=True, type=Path, help="Yevmiye dokumu (.xlsx veya .csv)")
    ap.add_argument("--cikti-dizini", required=True, type=Path, help="Uretilen JSON'larin yazilacagi klasor")
    args = ap.parse_args()

    ozet = esle_ve_uret(args.own_vkn, args.fatura_dizini, args.yevmiye_dosyasi, args.cikti_dizini)

    print(f"\nTamamlandi: {ozet['eslesen']}/{ozet['toplam_xml']} fatura yevmiye kaydiyla eslesti.")
    print(f"Cikti: {ozet['cikti_dizini']}")
    if ozet["yon_belirsiz_atlanan"]:
        print(
            f"\n!!! ONEMLI: {len(ozet['yon_belirsiz_atlanan'])} faturada own_vkn "
            f"({args.own_vkn}) ne alici ne satici tarafinda bulunamadi - bu YANLIS "
            f"VKN girildigine isaret edebilir. Bu faturalar RAG'a YAZILMADI: "
            f"{ozet['yon_belirsiz_atlanan'][:10]}"
            + (" ..." if len(ozet["yon_belirsiz_atlanan"]) > 10 else "")
        )
    if ozet["xml_de_var_yevmiyede_yok"]:
        print(
            f"\nUyari: {len(ozet['xml_de_var_yevmiyede_yok'])} fatura XML'i var ama yevmiye kaydi "
            f"bulunamadi (RAG'a EKLENMEYECEK): {ozet['xml_de_var_yevmiyede_yok'][:10]}"
            + (" ..." if len(ozet["xml_de_var_yevmiyede_yok"]) > 10 else "")
        )
    if ozet["yevmiyede_var_xml_de_yok"]:
        print(
            f"\nUyari: {len(ozet['yevmiyede_var_xml_de_yok'])} fatura numarasi yevmiyede var ama "
            f"XML'i bulunamadi (bu fatura no'lar atlandi): {ozet['yevmiyede_var_xml_de_yok'][:10]}"
            + (" ..." if len(ozet["yevmiyede_var_xml_de_yok"]) > 10 else "")
        )


if __name__ == "__main__":
    main()
