"""core.scoring icin birim testleri.

Calistirmak icin:
    cd model_eval
    python3 -m pytest tests/ -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.scoring as scoring


# ---------------------------------------------------------------------------
# extract_json_block / parse_model_output — modelin gurultulu ciktisini ayristirma
# ---------------------------------------------------------------------------

class TestExtractJsonBlock:
    def test_clean_json(self):
        assert scoring.extract_json_block('{"a": 1}') == {"a": 1}

    def test_markdown_fenced_json(self):
        text = "```json\n{\"a\": 1}\n```"
        assert scoring.extract_json_block(text) == {"a": 1}

    def test_json_with_surrounding_prose(self):
        text = 'Iste cevabim:\n{"entries": [{"a": 1}]}\nUmarim yardimci olur.'
        assert scoring.extract_json_block(text) == {"entries": [{"a": 1}]}

    def test_bare_list(self):
        text = '[{"a": 1}, {"a": 2}]'
        assert scoring.extract_json_block(text) == [{"a": 1}, {"a": 2}]

    def test_unparseable_returns_none(self):
        assert scoring.extract_json_block("bunun disinda hicbir sey yok") is None

    def test_empty_string_returns_none(self):
        assert scoring.extract_json_block("") is None


class TestParseModelOutput:
    def test_entries_key_dict(self):
        raw = '{"entries": [{"account_code": "191", "dc": "Borc", "amount": 1}]}'
        entries, err = scoring.parse_model_output(raw)
        assert err is None
        assert len(entries) == 1

    def test_bare_list_accepted(self):
        raw = '[{"account_code": "191", "dc": "Borc", "amount": 1}]'
        entries, err = scoring.parse_model_output(raw)
        assert err is None
        assert len(entries) == 1

    def test_dict_without_entries_but_with_some_list_value(self):
        raw = '{"kayitlar": [{"account_code": "191", "dc": "Borc", "amount": 1}]}'
        entries, err = scoring.parse_model_output(raw)
        assert err is None
        assert len(entries) == 1

    def test_unparseable_json_reports_error(self):
        entries, err = scoring.parse_model_output("gecersiz metin")
        assert entries is None
        assert err == "json_parse_error"

    def test_json_object_with_no_list_reports_error(self):
        raw = '{"account_code": "191"}'
        entries, err = scoring.parse_model_output(raw)
        assert entries is None
        assert err == "no_entries_field"


# ---------------------------------------------------------------------------
# score_entries — degerlendirme mantigi (bu scriptin kalbi)
# ---------------------------------------------------------------------------

class TestScoreEntries:
    GT = {("191", "Borc"), ("329", "Alacak"), ("689", "Borc"), ("770", "Borc")}

    def test_perfect_match(self):
        entries = [
            {"account_code": "191", "amount": 41.57, "dc": "Borc"},
            {"account_code": "329", "amount": 291.70, "dc": "Alacak"},
            {"account_code": "689", "amount": 20.78, "dc": "Borc"},
            {"account_code": "770", "amount": 229.35, "dc": "Borc"},
        ]
        m = scoring.score_entries(self.GT, entries)
        assert m["exact_pair_match"] is True
        assert m["exact_code_match"] is True
        assert m["tp_pairs"] == 4 and m["fp_pairs"] == 0 and m["fn_pairs"] == 0
        assert m["balanced"] is True  # borc toplami == alacak toplami

    def test_full_subaccount_codes_normalize_before_matching(self):
        """Model kurallara uymayip sirkete ozel alt hesap numarasi ('191.01.00020')
        dondurse bile, sadece ilk 3 hane karsilastirmaya girmeli."""
        entries = [
            {"account_code": "191.01.00020", "amount": 41.57, "dc": "Borç"},
            {"account_code": "329.01.00012", "amount": 291.70, "dc": "Alacak"},
            {"account_code": "689.01.00009", "amount": 20.78, "dc": "borç"},
            {"account_code": "770", "amount": 229.35, "dc": "Debit"},
        ]
        m = scoring.score_entries(self.GT, entries)
        assert m["exact_pair_match"] is True

    def test_wrong_direction_counts_as_pair_miss_but_code_hit(self):
        entries = [{"account_code": "191", "amount": 41.57, "dc": "Alacak"}]  # ters yon
        m = scoring.score_entries(self.GT, entries)
        assert m["tp_pairs"] == 0          # yon (dc) yanlis, pair eslesmiyor
        assert m["tp_codes"] == 1          # ama hesap kodu dogru secilmis
        assert m["exact_pair_match"] is False

    def test_hallucinated_and_missed_codes_tracked(self):
        entries = [
            {"account_code": "191", "amount": 41.57, "dc": "Borc"},
            {"account_code": "600", "amount": 10, "dc": "Borc"},  # halusinasyon
        ]
        m = scoring.score_entries(self.GT, entries)
        assert m["fp_code_list"] == ["600"]
        assert set(m["fn_code_list"]) == {"329", "689", "770"}

    def test_invalid_entries_are_skipped_not_crashed(self):
        entries = [
            "bu bir dict degil",
            {"account_code": "191", "amount": 41.57, "dc": "gecersiz_yon"},
            {"account_code": "cift degil", "amount": 1, "dc": "Borc"},
        ]
        m = scoring.score_entries(self.GT, entries)
        assert m["n_skipped_entries"] == 3
        assert m["pred_pairs"] == []

    def test_empty_entries_not_marked_balanced(self):
        m = scoring.score_entries(self.GT, [])
        assert m["balanced"] is False  # bos kayit "dengeli" sayilmamali

    def test_unbalanced_double_entry_detected(self):
        entries = [
            {"account_code": "191", "amount": 41.57, "dc": "Borc"},
            {"account_code": "329", "amount": 999.00, "dc": "Alacak"},  # kasitli dengesiz
        ]
        m = scoring.score_entries(self.GT, entries)
        assert m["balanced"] is False

    def test_duplicate_same_pair_does_not_double_count(self):
        entries = [
            {"account_code": "191", "amount": 20, "dc": "Borc"},
            {"account_code": "191", "amount": 21.57, "dc": "Borc"},  # ayni (code, dc) ikinci kez
        ]
        m = scoring.score_entries(self.GT, entries)
        assert m["tp_pairs"] == 1  # set oldugu icin tekil sayilmali


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
