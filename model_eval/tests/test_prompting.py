"""core.prompting icin birim testleri.

Calistirmak icin:
    cd model_eval
    python3 -m pytest tests/ -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.parsing as parsing
import core.prompting as prompting
from conftest import SAMPLE_INVOICE_JSON


class TestBuildAltKirilimUserPromptParaBirimi:
    """2026-07-31 duzeltmesi: EUR faturada 601.01.00001 ("Yurt Disi TL
    Satislari") yanlislikla secildi cunku alt kirilim LLM cagrisi para
    birimini hic gormuyordu - artik FATURA BAGLAMI'nda gosteriliyor."""

    def _sahte_invoice(self, currency):
        return {
            "header": {
                "currency": currency,
                "account_title": "Test Musteri",
                "account_tax_number": "1234567890",
                "invoice_type": "SATIS",
            }
        }

    def test_para_birimi_prompta_yaziliyor(self):
        inv = self._sahte_invoice("EUR")
        prompt = prompting.build_alt_kirilim_user_prompt(
            inv, [{"account_code": "601", "dc": "Alacak"}],
            {"601": [("601.01.00001", "Yurt Disi TL Satislari"), ("601.01.00002", "Yurt Disi Euro Satislari")]},
        )
        assert "Para Birimi: EUR" in prompt

    def test_currency_eksikse_soru_isareti_yazilir(self):
        inv = {"header": {}}
        prompt = prompting.build_alt_kirilim_user_prompt(inv, [], {})
        assert "Para Birimi: ?" in prompt

    def test_sistem_prompt_doviz_uyum_kurali_iceriyor(self):
        assert "PARA BIRIMI" in prompting.ALT_KIRILIM_SYSTEM_PROMPT
        assert "Euro" in prompting.ALT_KIRILIM_SYSTEM_PROMPT


class TestBuildUserPromptNoLeak:
    def test_ground_truth_account_codes_not_in_prompt(self, invoice_file):
        p = invoice_file("X-abc-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        prompt = prompting.build_user_prompt(inv, "Test Sektoru")
        for code, _ in inv["gt_pairs"]:
            # 3 haneli kod tesadufen baska bir yerde (tutar vs) gecebilir diye
            # daha spesifik olan tam muavin kodunu ariyoruz: sizmamali.
            assert "191.01.00020" not in prompt
            assert "689.01.00009" not in prompt
            assert "329.01.00012" not in prompt
        assert "Muhasebe Kayitlari" not in prompt
        assert "accounting_entries" not in prompt

    def test_inbox_direction_text(self, invoice_file):
        p = invoice_file("X-abc-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        prompt = prompting.build_user_prompt(inv, "Test Sektoru")
        assert "ALIS faturasidir" in prompt

    def test_outbox_direction_text(self, invoice_file):
        p = invoice_file("X-abc-outbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        prompt = prompting.build_user_prompt(inv, "Test Sektoru")
        assert "SATIS faturasidir" in prompt

    def test_exemption_reason_included_when_present(self, invoice_file):
        data = json.loads(json.dumps(SAMPLE_INVOICE_JSON))
        data["taxes"][0]["exemption"] = {"code": "301", "reason": "11/1-a Mal Ihracati"}
        p = invoice_file("X-abc-outbox.json", data)
        inv = parsing.parse_invoice(p)
        prompt = prompting.build_user_prompt(inv, "Test Sektoru")
        assert "301" in prompt and "Mal Ihracati" in prompt

    def test_empty_lines_placeholder(self, invoice_file):
        data = json.loads(json.dumps(SAMPLE_INVOICE_JSON))
        data["lines"] = []
        p = invoice_file("X-abc-inbox.json", data)
        inv = parsing.parse_invoice(p)
        prompt = prompting.build_user_prompt(inv, "Test Sektoru")
        assert "satir kalemi bilgisi yok" in prompt


# ---------------------------------------------------------------------------
# build_direction_text / compute_iade_hint — IADE faturalarda ters kayit
# mantigi (bkz. RESULTS.md SS6.3): normal alis/satis cerceevesi YANLIS,
# outbox+IADE = alistan iade, inbox+IADE = satistan iade.
# ---------------------------------------------------------------------------

def _iade_invoice(direction, tax_exclusive=100.0, tax_total=20.0, payable=120.0):
    return {
        "direction": direction,
        "header": {
            "invoice_type": "IADE",
            "tax_exclusive": f"{tax_exclusive:.2f} TRY",
            "tax_inclusive": f"{payable:.2f} TRY",
            "payable": f"{payable:.2f} TRY",
        },
        "taxes": [{"name": "KDV", "code": "0015", "percent": "20", "tax": f"{tax_total:.2f} TRY"}],
    }


class TestBuildDirectionText:
    def test_normal_inbox_unaffected(self):
        inv = {"direction": "inbox", "header": {"invoice_type": "SATIS"}}
        assert prompting.build_direction_text(inv) == "Bu fatura sirketimizin ALDIGI bir ALIS faturasidir (biz aliciyiz)."

    def test_normal_outbox_unaffected(self):
        inv = {"direction": "outbox", "header": {"invoice_type": "SATIS"}}
        assert prompting.build_direction_text(inv) == "Bu fatura sirketimizin KESTIGI bir SATIS faturasidir (biz saticiyiz)."

    def test_iade_outbox_framed_as_purchase_return_not_sale(self):
        """outbox + IADE = ALISTAN iade (tedarikciye iade) - 'biz saticiyiz'
        DEMEMELI, bu tam tersini soyleyen yanlis bir cerceve olurdu."""
        inv = {"direction": "outbox", "header": {"invoice_type": "IADE"}}
        text = prompting.build_direction_text(inv)
        assert "ALISIN IADESIDIR" in text
        assert "saticiyiz" not in text

    def test_iade_inbox_framed_as_sale_return_not_purchase(self):
        inv = {"direction": "inbox", "header": {"invoice_type": "IADE"}}
        text = prompting.build_direction_text(inv)
        assert "SATISIN IADESIDIR" in text
        assert "aliciyiz" not in text

    def test_invoice_type_case_insensitive(self):
        inv = {"direction": "outbox", "header": {"invoice_type": "iade"}}
        assert "ALISIN IADESIDIR" in prompting.build_direction_text(inv)


class TestComputeIadeHint:
    def test_outbox_uses_391_alacak_and_320_borc(self):
        inv = _iade_invoice("outbox", tax_exclusive=100.0, tax_total=20.0, payable=120.0)
        hint = prompting.compute_iade_hint(inv)
        assert "ALISTAN IADE" in hint
        assert "391" in hint and "ALACAK" in hint
        assert "120.00" in hint  # karsi tarafa BORC
        assert "20.00" in hint  # KDV ALACAK
        assert "100.00" in hint  # mal/hizmet ALACAK

    def test_inbox_uses_191_borc_and_karsi_taraf_alacak(self):
        inv = _iade_invoice("inbox", tax_exclusive=100.0, tax_total=20.0, payable=120.0)
        hint = prompting.compute_iade_hint(inv)
        assert "SATISTAN IADE" in hint
        assert "191" in hint and "BORC" in hint
        assert "120.00" in hint  # karsi tarafa ALACAK

    def test_returns_none_when_no_tax(self):
        inv = _iade_invoice("outbox", tax_exclusive=100.0, tax_total=0.0, payable=100.0)
        assert prompting.compute_iade_hint(inv) is None

    def test_returns_none_when_no_payable(self):
        inv = _iade_invoice("outbox", tax_exclusive=0.0, tax_total=0.0, payable=0.0)
        assert prompting.compute_iade_hint(inv) is None

    def test_does_not_mutate_account_code_choice(self):
        """Hint, hangi mal/hizmet hesabinin (150/730/770 vb.) kullanilacagina
        karar VERMEZ - bu hala modelin/RAG'in siniflandirma karari."""
        inv = _iade_invoice("outbox")
        hint = prompting.compute_iade_hint(inv)
        assert "SEN belirle" in hint

    def test_returns_none_for_non_iade_invoice_type(self):
        """KRITIK: bu hint SADECE IADE faturalari icindir. invoice_type kontrolu
        olmadan, normal bir SATIS/ALIS faturasinda da tetiklenir ve yon/KDV-kodunu
        YANLIS (ters) hesaplardi - cunku payable>0/tax>0 her faturada dogrudur."""
        inv = _iade_invoice("outbox")
        inv["header"]["invoice_type"] = "SATIS"
        assert prompting.compute_iade_hint(inv) is None

    def test_invoice_type_check_is_case_insensitive(self):
        inv = _iade_invoice("outbox")
        inv["header"]["invoice_type"] = "iade"
        assert prompting.compute_iade_hint(inv) is not None


class TestBuildUserPromptIadeHint:
    def test_iade_hint_block_appears_only_when_flag_and_type_match(self, invoice_file):
        data = json.loads(json.dumps(SAMPLE_INVOICE_JSON))
        data["header"]["invoice_type"] = "IADE"
        p = invoice_file("X-abc-outbox.json", data)
        inv = parsing.parse_invoice(p)

        with_hint = prompting.build_user_prompt(inv, "Test Sektoru", iade_hint=True)
        without_hint = prompting.build_user_prompt(inv, "Test Sektoru", iade_hint=False)
        assert "IADE FATURASI HESAPLAMASI" in with_hint
        assert "IADE FATURASI HESAPLAMASI" not in without_hint

    def test_no_iade_block_for_non_iade_invoice_even_if_flag_set(self, invoice_file):
        """SAMPLE_INVOICE_JSON'un invoice_type'i SATIS - --iade-hint verilse
        bile bu faturada IADE blogu OLUSMAMALI (yanlis ters-yon hesaplamasi
        dayatmamali)."""
        p = invoice_file("X-abc-outbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        prompt = prompting.build_user_prompt(inv, "Test Sektoru", iade_hint=True)
        assert "IADE FATURASI HESAPLAMASI" not in prompt


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
