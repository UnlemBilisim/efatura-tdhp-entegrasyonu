"""TDHP tahminini DIS EKIP semasina (records[]) cevirir.

Neden ayri bir modul (2026-07-27, kullanici karari): `predict_single_invoice`
IC semayi (`entries[]`, dc="Borc"/"Alacak") uretir - 178 test, ChromaDB RAG
kayitlari ve `model_eval_sonuclar` tablosu bu semaya bagli. Dis ekip ise
farkli alan adlari ve BUYUK HARFLI Borc/Alacak istiyor. Ic semayi degistirmek
yerine burada TEK YONLU bir donusum yapilir - ic sema serbest kalir, dis
sozlesme sabitlenir.

Gerekce (`account_code_reason`) DETERMINISTIK uretilir, LLM'e sorulmaz
(kullanici karari, 2026-07-27): kodun nereden geldigini zaten biliyoruz
(`secim_kaynagi` izi - fuzzy isim eslesmesi / LLM secimi / KDV oran
duzeltmesi / 3 hanede kalma). LLM'e "neden bu kodu sectin" diye sormak
post-hoc rasyonalizasyon riski tasir - model kodu bir sebeple secip baska
bir sebep yazabilir. Buradaki gerekce, gercekten olan islemi anlatir.
"""

from __future__ import annotations

from .parsing import to_float
from .single import CARI_HESAP_KODLARI

# Ic sema -> dis sema Borc/Alacak karsiligi. Ic tarafta "Borc"/"Alacak"
# KALIR (testler + model_eval_sonuclar tablosu buna bagli, bkz. modul
# docstring'i); cevrim sadece burada, disa aktarimda yapilir.
DC_DIS_KARSILIGI = {"Borc": "BORÇ", "Alacak": "ALACAK"}


def _hesap_turu(account_code):
    """'C' (cari hesap) mi 'G' (genel/diger) mi?

    Cari hesaplar zaten `CARI_HESAP_KODLARI` (120/320/340/440/159/420) olarak
    tanimli - alt kirilimli kodun (orn. "320.01.00376") ANA kodu bu kumede
    mi diye bakilir. Ayri bir liste TUTULMAZ (kok CLAUDE.md: "var olan
    siniflandirma yapisina ekle, paralel ikinci liste olusturma")."""
    ana_kod = str(account_code).split(".")[0]
    return "C" if ana_kod in CARI_HESAP_KODLARI else "G"


def _gerekce_uret(entry, emsal_sayisi=0, karsi_taraf_vkn=None):
    """Kodun NASIL secildigini anlatan deterministik gerekce cumlesi.

    Kaynak `entry["secim_kaynagi"]` izidir (core/single.py::_entry_dicts_uygula
    tarafindan eklenir). Iz yoksa (alt kirilim adimi hic calismadiysa ya da
    kod 3 hanede kaldiysa) duruma uygun bir aciklama uretilir - alan asla
    bos birakilmaz, cunku dis ekip her kayitta bir gerekce bekliyor."""
    kod = entry.get("account_code", "")
    iz = entry.get("secim_kaynagi") or {}
    kaynak = iz.get("kaynak")

    # 3 haneli kaldiysa (alt kirilim cozulemedi) - en bilgilendirici durum,
    # cunku muhasebecinin elle mudahale etmesi gerekebilir.
    if "." not in str(kod):
        if entry.get("uyari"):
            return (
                f"{kod} için mizanda eşleşen alt kırılım (cari kart) bulunamadı; "
                "ana hesap kodunda bırakıldı — yeni müşteri/tedarikçi olabilir."
            )
        return (
            f"{kod} ana hesap kodu kullanıldı; mizanda bu kod için seçilebilecek "
            "bir alt kırılım bulunamadı."
        )

    if kaynak == "fuzzy":
        benzerlik = iz.get("benzerlik")
        oran_metni = f" (isim benzerliği %{benzerlik * 100:.0f})" if benzerlik else ""
        return (
            f"Karşı taraf unvanı mizandaki '{entry.get('account_description', kod)}' "
            f"kaydıyla eşleşti{oran_metni}; aynı cari hesap kullanıldı."
        )

    if kaynak == "llm":
        if iz.get("oran_duzeltildi"):
            return (
                f"Hesap türü geçmiş emsal faturalara göre seçildi; alt kırılım, "
                f"faturadaki gerçek KDV oranına göre {kod} olarak düzeltildi."
            )
        if emsal_sayisi:
            return (
                f"Aynı tedarikçi/müşteri ile yapılan {emsal_sayisi} geçmiş benzer "
                f"faturada kullanılan hesap kırılımı esas alındı."
            )
        return "Faturadaki kalem açıklaması ve mizandaki alt kırılım adları eşleştirilerek seçildi."

    # Iz yok - alt kirilim adimi calismamis ama kod yine de alt kirilimli
    # (orn. ana model dogrudan alt kirilimli kod uretmis).
    if emsal_sayisi:
        return f"{emsal_sayisi} geçmiş benzer faturadaki kayıtlar esas alınarak seçildi."
    return "Faturadaki kalem bilgisi ile mizandaki hesap planı eşleştirilerek seçildi."


def kayitlari_disa_aktar(tdhp_tahmini, emsal_sayisi=0, karsi_taraf_vkn=None):
    """Ic `entries[]` listesini dis ekibin bekledigi `records[]` semasina cevirir.

    Girdi (ic sema, predict_single_invoice ciktisi):
        {"account_code": "191.01.00020", "dc": "Borc", "amount": 283.33,
         "account_description": "%20 Indirilecek KDV",       # opsiyonel
         "secim_kaynagi": {...}, "uyari": "..."}             # opsiyonel

    Cikti (dis sema):
        {"account_code": "191.01.00020", "account_code_type": "G",
         "account_description": "%20 Indirilecek KDV",
         "account_code_reason": "...", "amount": 283.33,
         "debit_credit": "BORÇ"}

    `uyari` dolu olan kayitlarda uyari metni gerekcenin SONUNA eklenir -
    dis sema ayri bir uyari alani tanimlamiyor, ama bu bilgi kaybolmamali
    (muhasebecinin elle kontrol etmesi gereken durumu isaret ediyor)."""
    kayitlar = []
    for e in tdhp_tahmini.get("entries") or []:
        kod = e.get("account_code")
        gerekce = _gerekce_uret(e, emsal_sayisi=emsal_sayisi, karsi_taraf_vkn=karsi_taraf_vkn)
        uyari = e.get("uyari")
        if uyari and "bulunamadı" not in gerekce:
            gerekce = f"{gerekce} UYARI: {uyari}"

        kayitlar.append(
            {
                "account_code": kod,
                "account_code_type": _hesap_turu(kod),
                "account_description": e.get("account_description") or "",
                "account_code_reason": gerekce,
                "amount": e.get("amount"),
                "debit_credit": DC_DIS_KARSILIGI.get(e.get("dc"), e.get("dc")),
            }
        )
    return kayitlar


def _taraflar(invoice, own_vkn):
    """Fatura yonune gore customer/supplier ikilisini kurar.

    UBL'de karsi taraf TEK bir alanda (header.account_title/account_tax_number)
    tutulur; hangi tarafta oldugu YONE baglidir (bkz. core/parsing.py -
    counterparty_path yone gore secilir):
      - outbox (BIZ kestik)  -> karsi taraf MUSTERI, biz saticiyiz
      - inbox  (bize geldi)  -> karsi taraf TEDARIKCI, biz aliciyiz
    Kendi unvanimizi UBL'den okumuyoruz (parser sadece karsi tarafi tutuyor),
    o yuzden bizim tarafta yalnizca VKN doldurulur, name bos string kalir -
    None yerine bos string, dis sema tip tutarliligi icin (bkz. modul
    docstring'i, account_description ile ayni gerekce)."""
    karsi = {
        "id": (invoice.get("header") or {}).get("account_tax_number") or "",
        "name": (invoice.get("header") or {}).get("account_title") or "",
    }
    biz = {"id": own_vkn or "", "name": ""}
    if invoice.get("direction") == "outbox":
        return karsi, biz  # customer=karsi taraf, supplier=biz
    return biz, karsi  # inbox: customer=biz, supplier=karsi taraf


def faturayi_disa_aktar(tdhp_tahmini, invoice, own_vkn, file_path=None, emsal_sayisi=0):
    """Dis ekibin bekledigi TAM zarfi (records + fatura ust bilgileri) kurar.

    2026-07-27 sozlesmesi - dis ekibin ornek JSON'undaki dokuz alan:
        currency, customer, file_path, invoice_id, issue_date,
        payable_amount, records, success, supplier

    `success`, tahminin hatasiz tamamlanip tamamlanmadigini gosterir
    (tdhp_tahmini["error"] None ise True). `file_path` cagiran katmandan
    gelir - model_eval dosya yolu bilmez (ham XML string alir), bu yuzden
    parametre; verilmezse bos string.

    Ic sema (`entries`) AYNEN korunur; bu fonksiyon onu DEGISTIRMEZ, sadece
    dis gorunumu uretir (bkz. modul docstring'i)."""
    header = invoice.get("header") or {}
    customer, supplier = _taraflar(invoice, own_vkn)
    return {
        "currency": header.get("currency") or tdhp_tahmini.get("currency"),
        "customer": customer,
        "file_path": file_path or "",
        "invoice_id": tdhp_tahmini.get("invoice_id") or header.get("invoice_id"),
        "issue_date": header.get("issue_date"),
        "payable_amount": to_float(header.get("payable")),
        "records": kayitlari_disa_aktar(tdhp_tahmini, emsal_sayisi=emsal_sayisi),
        "success": tdhp_tahmini.get("error") is None,
        "supplier": supplier,
    }
