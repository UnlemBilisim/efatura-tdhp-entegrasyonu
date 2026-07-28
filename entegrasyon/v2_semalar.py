"""v2 API dis semasi — ic semadan TURETILIR, ic sema DEGISMEZ.

Tasarim gerekcesi: docs/explanation/v2-api-tasarim-karari.md

v1 (`/fatura/isle`) ile v2 arasindaki fark yalnizca sunum katmanindadir;
muhasebe kaydini ureten kod (model_eval/core/single.py) AYNIDIR. Bu modul
`predict_single_invoice` ciktisini v2 sozlesmesine cevirir:

  ic sema                     v2 dis sema
  -----------------------     ------------------------------
  dc="Borc"/"Alacak"      ->  side="debit"/"credit"
  account_code_type="C"   ->  account_type="receivable"
  direction="outbox"      ->  direction="outbound"
  uyari dolu / 3 haneli   ->  needs_review=true (acik bayrak)
  entries + records + dis_sema -> YALNIZCA entries (tek kaynak)

Turkce alan adlari ve BORC/ALACAK degerleri v2'de KULLANILMAZ - sozlesme
dili tek tip (Ingilizce) tutulur.
"""

from __future__ import annotations

from typing import Optional

# Ic sema -> v2 karsiliklari. Tek yonlu; v2'den ice donusum YOK.
SIDE_KARSILIGI = {"Borc": "debit", "Alacak": "credit"}
DIRECTION_KARSILIGI = {"outbox": "outbound", "inbox": "inbound"}

# Cari hesap kodlari (120/320/340/440/159/420) "receivable", digerleri
# "general". Kaynak: model_eval/core/single.py::CARI_HESAP_KODLARI - ayri bir
# liste TUTULMAZ (kok CLAUDE.md: paralel siniflandirma olusturma).
ACCOUNT_TYPE_KARSILIGI = {"C": "receivable", "G": "general"}

# KDV on kontrol karari -> v2 verdict.
VAT_VERDICT_KARSILIGI = {
    "uygun": "compliant",
    "insan_incelemesi_gerekli": "review_required",
}


def _kayit_v2(kayit: dict) -> dict:
    """Tek bir muhasebe kaydini v2 semasina cevirir.

    Girdi: core/disa_aktarim.py::kayitlari_disa_aktar ciktisi
    (account_code / account_code_type / account_description /
    account_code_reason / amount / debit_credit).

    `needs_review`: alt kirilim cozulemediginde (kod 3 haneli kaldi, nokta
    yok) TRUE olur. v1'de bu bilgi yalnizca gerekce METNININ icinde gizliydi;
    istemcinin string ayristirmasi gerekiyordu. v2'de acik bir bayrak."""
    kod = kayit.get("account_code") or ""
    return {
        "account_code": kod,
        "account_type": ACCOUNT_TYPE_KARSILIGI.get(kayit.get("account_code_type"), "general"),
        "account_name": kayit.get("account_description") or None,
        "amount": kayit.get("amount"),
        "side": SIDE_KARSILIGI.get(_ic_dc(kayit), None),
        "reason": kayit.get("account_code_reason") or None,
        "needs_review": "." not in str(kod),
    }


def _ic_dc(kayit: dict) -> Optional[str]:
    """disa_aktarim BUYUK HARFLI (BORÇ/ALACAK) uretir; v2 icin ic degere
    (Borc/Alacak) geri esleriz. Iki asamali cevrim gorunuyor ama kasitli:
    v1 sozlesmesi bozulmadan v2 kendi dilini kullaniyor."""
    dis = kayit.get("debit_credit")
    if dis == "BORÇ":
        return "Borc"
    if dis == "ALACAK":
        return "Alacak"
    return dis  # beklenmedik deger sessizce yutulmaz, oldugu gibi gecer


def _vat_check_v2(on_filtre: Optional[dict]) -> Optional[dict]:
    """KDV on kontrol sonucunu v2 semasina cevirir.

    inbox faturalarda on filtre HIC calismaz (baskasinin kestigi faturanin
    mevzuat sorumlulugu bizde degil) - o durumda None doner."""
    if not on_filtre:
        return None
    satirlar = []
    for s in on_filtre.get("satir_sonuclari") or []:
        satirlar.append(
            {
                "line_no": s.get("kalem_sira_no"),
                "line_name": s.get("kalem_adi"),
                "declared_rates": s.get("beyan_edilen_oranlar") or [],
                "allowed_rates": s.get("izin_verilen_oranlar_havuzu") or [],
                "verdict": VAT_VERDICT_KARSILIGI.get(s.get("karar"), s.get("karar")),
                "explanation": s.get("gerekce"),
            }
        )
    return {
        "verdict": VAT_VERDICT_KARSILIGI.get(
            on_filtre.get("genel_karar"), on_filtre.get("genel_karar")
        ),
        "lines": satirlar,
    }


def sonucu_v2ye_cevir(
    tahmin: dict,
    on_filtre: Optional[dict] = None,
    yon: Optional[str] = None,
) -> dict:
    """`predict_single_invoice` + on filtre sonucunu v2 semasina cevirir.

    Girdi `tahmin`, `model_eval_koprusu.tdhp_tahmini_yap` ciktisidir - yani
    icinde `dis_sema` (v1 zarfi) hazir bulunur ve fatura ust bilgileri oradan
    okunur (yeniden ayristirma YAPILMAZ).

    `file_path` v2'de YOK (v1'de her zaman bos donen olu alandi).
    `supplier.name`/`customer.name` bilinmiyorsa None - bos string degil,
    "bilinmiyor" anlami net olsun."""
    zarf = tahmin.get("dis_sema") or {}
    kayitlar = zarf.get("records") or tahmin.get("records") or []

    def _taraf(t: Optional[dict]) -> dict:
        t = t or {}
        return {"vkn": t.get("id") or None, "name": t.get("name") or None}

    entries = [_kayit_v2(k) for k in kayitlar]
    uyarilar = []
    if any(e["needs_review"] for e in entries):
        uyarilar.append(
            "Bazi hesap kodlari alt kirilima cozulemedi (needs_review=true) — "
            "muhasebeci kontrolu gerekiyor."
        )
    if tahmin.get("balanced") is False:
        uyarilar.append("Borc ve alacak toplamlari esit degil — kayit eksik olabilir.")
    if tahmin.get("self_corrected"):
        uyarilar.append(
            f"Kayit model tarafindan bir kez duzeltildi "
            f"(sebep: {tahmin.get('self_correct_reason')})."
        )

    return {
        "invoice": {
            "id": zarf.get("invoice_id") or tahmin.get("invoice_id"),
            "issue_date": zarf.get("issue_date"),
            "currency": zarf.get("currency") or tahmin.get("currency"),
            "payable_amount": zarf.get("payable_amount"),
            "direction": DIRECTION_KARSILIGI.get(yon or tahmin.get("direction")),
            "customer": _taraf(zarf.get("customer")),
            "supplier": _taraf(zarf.get("supplier")),
        },
        "entries": entries,
        "totals": {
            "debit": tahmin.get("borc_toplam"),
            "credit": tahmin.get("alacak_toplam"),
            "balanced": tahmin.get("balanced"),
        },
        "vat_check": _vat_check_v2(on_filtre),
        "warnings": uyarilar,
    }
