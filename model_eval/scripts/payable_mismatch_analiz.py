#!/usr/bin/env python3
"""PAYABLE_MISMATCH kuralinin GERCEK muhasebeci kayitlari uzerinde ne kadar
reddettigini olcer ve reddi 4 kategoriye ayirir (2026-10-01, TODO.md madde
"PAYABLE_MISMATCH gercek muhasebeci kayitlarinin %9,8'ini reddediyor" icin
kalici olcum script'i - onceki analiz gecici/proje disi script'lerle yapilmis,
tekrarlanabilir degildi).

LLM TAHMINI KULLANMAZ - Archive2/jsons'daki gercek muhasebeci kaydinin
kendisini validate_prediction()'a prediction olarak verip, kuralin kendi
dogru verisini ne siklikta reddettigini olcer (yani kuralin KENDI hata orani,
bir modelin hata orani degil).

Kullanim:
    python3 scripts/payable_mismatch_analiz.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.parsing import normalize_code3, normalize_dc, to_float
from core.validation import validate_prediction

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "Archive2" / "jsons"


def _entries_from_ground_truth(raw):
    entries = []
    for e in raw.get("accounting_entries", []):
        code = normalize_code3(e.get("account_code"))
        dc = normalize_dc(e.get("dc"))
        if not code or not dc:
            continue
        entries.append({"account_code": code, "dc": dc, "amount": to_float(e.get("amount"))})
    return entries


def _invoice_header(raw):
    h = raw.get("header", {})
    return {
        "header": {
            "payable": h.get("payable"),
            "tax_inclusive": h.get("tax_inclusive"),
        },
        "invoice_type": h.get("invoice_type"),
    }


def main():
    dosyalar = sorted(DATA_DIR.glob("*.json"))
    if not dosyalar:
        raise SystemExit(f"{DATA_DIR} icinde .json bulunamadi.")

    toplam = 0
    reddedilen = []
    for yol in dosyalar:
        raw = json.loads(yol.read_text(encoding="utf-8"))
        entries = _entries_from_ground_truth(raw)
        if not entries:
            continue
        toplam += 1
        invoice = _invoice_header(raw)
        # own_vkn PAYABLE_MISMATCH icin kullanilmiyor (sadece EMPTY_ENTRIES/
        # UNRESOLVED_COUNTERPARTY icin mizan lookup gerekir, burada atlaniyor -
        # validate_prediction mizan sorgusu basarisiz olursa dahi PAYABLE_MISMATCH
        # kontrolu entries/header uzerinden bagimsiz calisir).
        try:
            sonuc = validate_prediction({"entries": entries}, invoice, "0460351893")
        except Exception as exc:
            print(f"UYARI: {yol.name} degerlendirilemedi: {exc}", file=sys.stderr)
            continue
        kodlar = {e["code"] for e in sonuc["errors"]}
        if "PAYABLE_MISMATCH" in kodlar:
            borc = sonuc["borc_toplam"]
            payable = to_float(invoice["header"].get("payable"))
            tax_inclusive = to_float(invoice["header"].get("tax_inclusive"))
            fark_payable = (borc - payable) if payable else None
            reddedilen.append({
                "dosya": yol.name,
                "invoice_type": invoice.get("invoice_type"),
                "borc": borc,
                "payable": payable,
                "tax_inclusive": tax_inclusive,
                "fark_payable": fark_payable,
                "fark_oran": (fark_payable / payable * 100) if payable else None,
            })

    print(f"Toplam degerlendirilen: {toplam}")
    print(f"PAYABLE_MISMATCH ile reddedilen: {len(reddedilen)} (%{len(reddedilen)/toplam*100:.1f})")
    print()

    # 4 kategoriye ayirma (2026-10-01, gercek dagilima gore kalibre edildi -
    # ilk denemede esikler cok dardi, gercekte yuvarlama olan kayitlar
    # "aciklanamayan"a dusuyordu, gercek veriyle incelenip duzeltildi):
    # 1) borc payable'in ~2 katiysa -> mukerrer kayit supheli (en guvenilir imza)
    # 2) kucuk mutlak fark (<=1.00 TL) -> yuvarlama/tolerans siddeti
    # 3) ISTISNA (ihracat) + kucuk ORANSAL fark (%0-3 arasi, gercek dagilimda
    #    86 kayittan 85'i bu aralikta kumelenmis - kur farki hipotezini
    #    destekliyor) -> kur farki supheli
    # 4) digerleri -> gercekten aciklanamayan (veri kalitesi sorunu olabilir -
    #    orn. tek bir hesaba ait tutarin yanlislikla iki satira bolunmesi gibi
    #    somut ornekler elle incelenerek bulundu, bkz. sonuc raporundaki notlar)
    mukerrer, kur_farki_supheli, yuvarlama, aciklanamayan = [], [], [], []
    for r in reddedilen:
        fark = r["fark_payable"]
        oran = r["fark_oran"]
        if fark is None:
            aciklanamayan.append(r)
            continue
        if r["payable"] and abs(r["borc"] - 2 * r["payable"]) < 0.02:
            mukerrer.append(r)
        elif abs(fark) <= 1.00:
            yuvarlama.append(r)
        elif r.get("invoice_type") == "ISTISNA" and oran is not None and 0 < abs(oran) <= 3.0:
            kur_farki_supheli.append(r)
        else:
            aciklanamayan.append(r)

    print(f"1) ISTISNA (ihracat), kucuk ORANSAL fark (%0-3 arasi, kur farki supheli): {len(kur_farki_supheli)}")
    print(f"2) Borc, payable'in ~2 kati (mukerrer kayit supheli): {len(mukerrer)}")
    print(f"3) Kucuk mutlak fark (<=1.00 TL, yuvarlama): {len(yuvarlama)}")
    print(f"4) Aciklanamayan fark (yukaridaki 3 kategoriye girmeyen): {len(aciklanamayan)}")
    oran_kucuk = [r for r in aciklanamayan if r["fark_oran"] is not None and abs(r["fark_oran"]) < 10]
    oran_buyuk = [r for r in aciklanamayan if r["fark_oran"] is not None and abs(r["fark_oran"]) >= 10]
    print(f"   4a) Bunlarin orani <10% olanlar (muhtemelen hesap-bazli tahsilat/kur farki): {len(oran_kucuk)}")
    print("   4b) Bunlarin orani >=10% olanlar (muhtemelen tek dosyada BIRDEN FAZLA faturanin")
    print("       kaydi karistigi veri anomalisi - elle incelenen GIB2025000000011 ornegi bunu")
    print("       dogruladi: header.payable tek bir cari hesaba ait, ama borc toplami dosyadaki")
    print(f"       IKI ayri cari hesabin (Elis Ozdas + Fevzi Komur) toplamini yansitiyor): {len(oran_buyuk)}")
    print()

    if aciklanamayan:
        print("Aciklanamayan farklarin ilk 10'u (invoice_type, borc, payable, fark, oran%):")
        for r in sorted(aciklanamayan, key=lambda x: abs(x["fark_payable"] or 0), reverse=True)[:10]:
            print(f"  {r['dosya']}: tip={r['invoice_type']} borc={r['borc']} payable={r['payable']} "
                  f"fark={r['fark_payable']:+.2f} oran={r['fark_oran']:+.2f}%" if r["fark_oran"] is not None
                  else f"  {r['dosya']}: tip={r['invoice_type']} borc={r['borc']} payable={r['payable']} fark={r['fark_payable']}")

    out = Path(__file__).resolve().parent.parent / "results" / "payable_mismatch_analiz.json"
    out.write_text(json.dumps({
        "toplam": toplam,
        "reddedilen_sayisi": len(reddedilen),
        "reddedilen_oran": round(len(reddedilen) / toplam * 100, 2),
        "kur_farki_supheli": len(kur_farki_supheli),
        "mukerrer_supheli": len(mukerrer),
        "yuvarlama": len(yuvarlama),
        "aciklanamayan": len(aciklanamayan),
        "reddedilen_detay": reddedilen,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTam detay: {out}")


if __name__ == "__main__":
    main()
