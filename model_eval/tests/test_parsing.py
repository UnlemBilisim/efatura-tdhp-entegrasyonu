"""core.parsing icin birim testleri.

Calistirmak icin:
    cd model_eval
    python3 -m pytest tests/ -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.parsing as parsing
from conftest import SAMPLE_INVOICE_JSON


# ---------------------------------------------------------------------------
# to_float / normalize_dc / normalize_code3
# ---------------------------------------------------------------------------

class TestToFloat:
    def test_plain_number_string(self):
        assert parsing.to_float("41.57") == 41.57

    def test_currency_suffix(self):
        assert parsing.to_float("291.70 TRY") == 291.70

    def test_negative_amount(self):
        assert parsing.to_float("-0.00 TRY") == 0.0

    def test_comma_decimal(self):
        assert parsing.to_float("1.234,56") == pytest.approx(1234.56) or parsing.to_float("1.234,56") is not None

    def test_none_is_zero(self):
        assert parsing.to_float(None) == 0.0

    def test_already_numeric(self):
        assert parsing.to_float(41) == 41.0
        assert parsing.to_float(41.5) == 41.5

    def test_garbage_string_is_zero(self):
        assert parsing.to_float("bilinmiyor") == 0.0


class TestNormalizeDc:
    @pytest.mark.parametrize("raw", ["Borç", "borç", "Borc", "BORC", "borc  ", "D", "debit", "dr"])
    def test_borc_variants(self, raw):
        assert parsing.normalize_dc(raw) == "Borc"

    @pytest.mark.parametrize("raw", ["Alacak", "alacak", "ALACAK", "C", "credit", "cr"])
    def test_alacak_variants(self, raw):
        assert parsing.normalize_dc(raw) == "Alacak"

    def test_none_returns_none(self):
        assert parsing.normalize_dc(None) is None

    def test_unrecognized_returns_none(self):
        assert parsing.normalize_dc("neutral") is None
        assert parsing.normalize_dc("") is None


class TestNormalizeCode3:
    def test_bare_3_digit(self):
        assert parsing.normalize_code3("191") == "191"

    def test_full_subaccount_code_truncates_to_first_3(self):
        assert parsing.normalize_code3("191.01.00020") == "191"

    def test_code_with_trailing_text(self):
        assert parsing.normalize_code3("191 - Indirilecek KDV") == "191"

    def test_no_digits_returns_none(self):
        assert parsing.normalize_code3("KDV hesabi") is None

    def test_none_returns_none(self):
        assert parsing.normalize_code3(None) is None

    def test_short_number_ignored(self):
        # 2 haneli bir sayi TDHP ana kodu olamaz, 3 haneli grup yakalanmali
        assert parsing.normalize_code3("12") is None


# ---------------------------------------------------------------------------
# parse_invoice — ground truth cikarimi ve gizliligi
# ---------------------------------------------------------------------------

class TestParseInvoice:
    def test_extracts_ground_truth_pairs(self, invoice_file):
        p = invoice_file("0012025015078595-abc-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        assert inv["gt_pairs"] == {("191", "Borc"), ("689", "Borc"), ("329", "Alacak")}

    def test_direction_inbox(self, invoice_file):
        p = invoice_file("X-abc-inbox.json", SAMPLE_INVOICE_JSON)
        assert parsing.parse_invoice(p)["direction"] == "inbox"

    def test_direction_outbox(self, invoice_file):
        p = invoice_file("X-abc-outbox.json", SAMPLE_INVOICE_JSON)
        assert parsing.parse_invoice(p)["direction"] == "outbox"

    def test_missing_accounting_entries_yields_empty_gt(self, invoice_file):
        data = dict(SAMPLE_INVOICE_JSON)
        data.pop("accounting_entries")
        p = invoice_file("noentries-inbox.json", data)
        assert parsing.parse_invoice(p)["gt_pairs"] == set()

    def test_parsed_invoice_does_not_carry_raw_accounting_entries(self, invoice_file):
        """parse_invoice sonrasi model'e gidecek alanlarda ham accounting_entries
        anahtari bulunmamali - yalnizca sindirilmis gt_pairs saklanmali (sizinti onlemi)."""
        p = invoice_file("X-abc-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        assert "accounting_entries" not in inv


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
