"""v2 dis sema donusumu testleri.

v2 sozlesmesi (teslim/API-ENTEGRASYON-KILAVUZU-v2.md) kod tarafinda korunmali;
bu testler alan adlari/deger kumeleri degistiginde kirilir.

Not: v2 modulleri `entegrasyon/` altinda oldugu icin sys.path'e o dizin
eklenir — `model_eval` testleri normalde kendi paketini test eder, bu dosya
bilincli bir istisnadir (dis sozlesme model_eval'in urettigi veriden
turetildigi icin donusumun burada test edilmesi anlamli)."""

import sys
from pathlib import Path

import pytest

_ENTEGRASYON = Path(__file__).resolve().parent.parent.parent / "entegrasyon"
if str(_ENTEGRASYON) not in sys.path:
    sys.path.insert(0, str(_ENTEGRASYON))

v2 = pytest.importorskip(
    "v2_semalar", reason="entegrasyon/v2_semalar.py bulunamadi (ayri bilesen)"
)


def _ornek_tahmin(**degisiklikler):
    """model_eval_koprusu.tdhp_tahmini_yap ciktisinin sadelestirilmis hali."""
    t = {
        "invoice_id": "AKA2025000000001",
        "direction": "outbox",
        "currency": "TRY",
        "balanced": True,
        "borc_toplam": 58319.20,
        "alacak_toplam": 58319.20,
        "self_corrected": False,
        "self_correct_reason": None,
        "error": None,
        "dis_sema": {
            "invoice_id": "AKA2025000000001",
            "issue_date": "2025-01-07",
            "currency": "TRY",
            "payable_amount": 58319.20,
            "customer": {"id": "8441199152", "name": "TİMSAN VİNÇ LTD."},
            "supplier": {"id": "0460351893", "name": ""},
            "success": True,
            "records": [
                {
                    "account_code": "120.01.00295",
                    "account_code_type": "C",
                    "account_description": "TİMSAN VINÇ",
                    "account_code_reason": "Isim benzerligi %100.",
                    "amount": 58319.20,
                    "debit_credit": "BORÇ",
                },
                {
                    "account_code": "600.01.00005",
                    "account_code_type": "G",
                    "account_description": "%20 Yurtici Satis",
                    "account_code_reason": "Kalem aciklamasi eslestirildi.",
                    "amount": 58319.20,
                    "debit_credit": "ALACAK",
                },
            ],
        },
    }
    t.update(degisiklikler)
    return t


V2_UST_ALANLAR = {"invoice", "entries", "totals", "vat_check", "warnings"}
V2_ENTRY_ALANLAR = {
    "account_code", "account_type", "account_name",
    "amount", "side", "reason", "needs_review",
}


class TestSemaYapisi:
    def test_ust_alanlar_tam(self):
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        assert set(s) == V2_UST_ALANLAR

    def test_entry_alanlari_tam(self):
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        for e in s["entries"]:
            assert set(e) == V2_ENTRY_ALANLAR

    def test_v1_alanlari_v2de_YOK(self):
        """records/dis_sema/file_path v2'de bulunmamali — tek veri kaynagi."""
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        assert "records" not in s
        assert "dis_sema" not in s
        assert "file_path" not in s["invoice"]


class TestDegerCevrimi:
    def test_borc_alacak_side_olur(self):
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        assert s["entries"][0]["side"] == "debit"
        assert s["entries"][1]["side"] == "credit"

    def test_turkce_deger_v2de_kalmaz(self):
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        assert all(e["side"] in ("debit", "credit") for e in s["entries"])

    def test_hesap_turu_cevrimi(self):
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        assert s["entries"][0]["account_type"] == "receivable"  # C
        assert s["entries"][1]["account_type"] == "general"  # G

    def test_yon_cevrimi(self):
        assert v2.sonucu_v2ye_cevir(_ornek_tahmin(), yon="outbox")["invoice"]["direction"] == "outbound"
        assert v2.sonucu_v2ye_cevir(_ornek_tahmin(), yon="inbox")["invoice"]["direction"] == "inbound"

    def test_bos_isim_None_olur(self):
        """Bos string yerine None — 'bilinmiyor' anlami net olsun."""
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        assert s["invoice"]["supplier"]["name"] is None
        assert s["invoice"]["customer"]["name"] == "TİMSAN VİNÇ LTD."


class TestNeedsReview:
    def test_alt_kirilimli_kod_review_gerektirmez(self):
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        assert all(e["needs_review"] is False for e in s["entries"])

    def test_uc_haneli_kod_review_gerektirir(self):
        t = _ornek_tahmin()
        t["dis_sema"]["records"][0]["account_code"] = "320"
        s = v2.sonucu_v2ye_cevir(t)
        assert s["entries"][0]["needs_review"] is True

    def test_review_gerekirse_uyari_eklenir(self):
        t = _ornek_tahmin()
        t["dis_sema"]["records"][0]["account_code"] = "320"
        s = v2.sonucu_v2ye_cevir(t)
        assert any("needs_review" in u for u in s["warnings"])


class TestUyarilar:
    def test_dengesiz_kayit_uyari_uretir(self):
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin(balanced=False))
        assert any("esit degil" in u for u in s["warnings"])

    def test_self_correct_uyari_uretir(self):
        s = v2.sonucu_v2ye_cevir(
            _ornek_tahmin(self_corrected=True, self_correct_reason="balance")
        )
        assert any("duzeltildi" in u for u in s["warnings"])

    def test_sorunsuz_kayitta_uyari_yok(self):
        assert v2.sonucu_v2ye_cevir(_ornek_tahmin())["warnings"] == []


class TestVatCheck:
    def test_on_filtre_yoksa_None(self):
        """inbound faturada KDV kontrolu hic calismaz."""
        assert v2.sonucu_v2ye_cevir(_ornek_tahmin())["vat_check"] is None

    def test_karar_ingilizceye_cevrilir(self):
        on_filtre = {
            "genel_karar": "insan_incelemesi_gerekli",
            "satir_sonuclari": [
                {
                    "kalem_sira_no": "1",
                    "kalem_adi": "KANCA",
                    "beyan_edilen_oranlar": [20.0],
                    "izin_verilen_oranlar_havuzu": [],
                    "karar": "insan_incelemesi_gerekli",
                    "gerekce": "NACE bulunamadi.",
                }
            ],
        }
        vc = v2.sonucu_v2ye_cevir(_ornek_tahmin(), on_filtre)["vat_check"]
        assert vc["verdict"] == "review_required"
        assert vc["lines"][0]["verdict"] == "review_required"
        assert vc["lines"][0]["line_name"] == "KANCA"

    def test_uygun_karar_compliant_olur(self):
        on_filtre = {"genel_karar": "uygun", "satir_sonuclari": []}
        assert v2.sonucu_v2ye_cevir(_ornek_tahmin(), on_filtre)["vat_check"]["verdict"] == "compliant"


class TestTotals:
    def test_toplamlar_aynen_aktarilir(self):
        s = v2.sonucu_v2ye_cevir(_ornek_tahmin())
        assert s["totals"] == {"debit": 58319.20, "credit": 58319.20, "balanced": True}
