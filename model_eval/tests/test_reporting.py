"""core.reporting icin birim testleri (PostgreSQL uzerinden).

Calistirmak icin (once Docker'daki test DB'sinin ayakta oldugundan emin ol):
    cd model_eval
    python3 -m pytest tests/ -v

PostgreSQL'e (TEST_DATABASE_URL) baglanilamiyorsa bu testler otomatik
atlanir (bkz. conftest.py).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.reporting as reporting
from tests.conftest import requires_postgres

pytestmark = requires_postgres


# ---------------------------------------------------------------------------
# result_label / sanitize_file_label — etiketleme
# ---------------------------------------------------------------------------

class TestResultLabel:
    def test_distinct_models_get_distinct_labels(self):
        l1 = reporting.result_label("openai:gpt-4.1", with_glossary=False)
        l2 = reporting.result_label("anthropic:claude-sonnet-5", with_glossary=False)
        assert l1 != l2

    def test_glossary_suffix_distinguishes_experiment_arm(self):
        base = reporting.result_label("qwen2.5:14b", with_glossary=False)
        with_g = reporting.result_label("qwen2.5:14b", with_glossary=True)
        assert base != with_g
        assert with_g == base + "+glossary"


class TestSanitizeFileLabel:
    def test_sanitizes_special_characters(self):
        label = "openai-compat:https://api.groq.com/openai/v1|llama-3.3-70b-versatile|GROQ_API_KEY"
        safe = reporting.sanitize_file_label(label)
        assert "/" not in safe and ":" not in safe and "|" not in safe


# ---------------------------------------------------------------------------
# append_result / load_done_ids / delete_results — kayit ve resume mantigi
# ---------------------------------------------------------------------------

class TestLoadDoneIds:
    def test_missing_label_returns_empty_set(self, db_conn):
        assert reporting.load_done_ids("nope-model") == set()

    def test_reads_invoice_ids_from_successfully_scored_results(self, db_conn):
        reporting.append_result("model-a", {"invoice_id": "A1", "tp_pairs": 1})
        reporting.append_result("model-a", {"invoice_id": "A2", "error": "timeout"})
        # A2 hata almis - done sayilmamali, bir sonraki kosuda tekrar denenmeli
        assert reporting.load_done_ids("model-a") == {"A1"}

    def test_error_records_never_marked_done_regardless_of_error_type(self, db_conn):
        reporting.append_result("model-a", {"invoice_id": "A1", "error": "429 Too Many Requests"})
        reporting.append_result("model-a", {"invoice_id": "A2", "error": "403 Forbidden"})
        reporting.append_result("model-a", {"invoice_id": "A3", "error": "json_parse_error"})
        reporting.append_result("model-a", {"invoice_id": "A4", "tp_pairs": 0, "fp_pairs": 0, "fn_pairs": 0})
        assert reporting.load_done_ids("model-a") == {"A4"}

    def test_retry_after_error_supersedes_earlier_error_record(self, db_conn):
        """Ayni invoice_id icin once hata, sonra basarili kayit eklenirse
        (retry sonucu), invoice tamamlanmis sayilmali."""
        reporting.append_result("model-a", {"invoice_id": "A1", "error": "429 Too Many Requests"})
        reporting.append_result("model-a", {"invoice_id": "A1", "tp_pairs": 1, "fp_pairs": 0, "fn_pairs": 0})
        assert reporting.load_done_ids("model-a") == {"A1"}

    def test_labels_are_isolated_from_each_other(self, db_conn):
        reporting.append_result("model-a", {"invoice_id": "A1", "tp_pairs": 1})
        reporting.append_result("model-b", {"invoice_id": "A1", "error": "timeout"})
        assert reporting.load_done_ids("model-a") == {"A1"}
        assert reporting.load_done_ids("model-b") == set()


class TestDeleteResults:
    def test_overwrite_clears_only_target_label(self, db_conn):
        reporting.append_result("model-a", {"invoice_id": "A1", "tp_pairs": 1})
        reporting.append_result("model-b", {"invoice_id": "A1", "tp_pairs": 1})
        reporting.delete_results("model-a")
        assert reporting.load_done_ids("model-a") == set()
        assert reporting.load_done_ids("model-b") == {"A1"}


# ---------------------------------------------------------------------------
# summarize_model — agregasyon aritmetigi
# ---------------------------------------------------------------------------

class TestSummarizeModel:
    def test_perfect_model_scores_1_0(self, db_conn):
        reporting.append_result("test-model", {
            "invoice_id": "A1", "tp_pairs": 2, "fp_pairs": 0, "fn_pairs": 0,
            "tp_codes": 2, "fp_codes": 0, "fn_codes": 0,
            "exact_pair_match": True, "exact_code_match": True, "balanced": True,
            "fn_code_list": [], "fp_code_list": [], "latency_s": 1.0,
        })
        s = reporting.summarize_model("test-model", "test-model")
        assert s["pair_f1"] == 1.0
        assert s["code_f1"] == 1.0
        assert s["exact_pair_match_rate"] == 1.0
        assert s["n_hard_errors"] == 0

    def test_mixed_results_micro_averages_correctly(self, db_conn):
        # invoice 1: 2 dogru, 1 yanlis (fp), 0 kacirilan
        reporting.append_result("test-model", {
            "invoice_id": "A1", "tp_pairs": 2, "fp_pairs": 1, "fn_pairs": 0,
            "tp_codes": 2, "fp_codes": 1, "fn_codes": 0,
            "exact_pair_match": False, "exact_code_match": False, "balanced": False,
            "fn_code_list": [], "fp_code_list": ["600"], "latency_s": 2.0,
        })
        # invoice 2: 1 dogru, 0 yanlis, 1 kacirilan
        reporting.append_result("test-model", {
            "invoice_id": "A2", "tp_pairs": 1, "fp_pairs": 0, "fn_pairs": 1,
            "tp_codes": 1, "fp_codes": 0, "fn_codes": 1,
            "exact_pair_match": False, "exact_code_match": False, "balanced": True,
            "fn_code_list": ["689"], "fp_code_list": [], "latency_s": 3.0,
        })
        s = reporting.summarize_model("test-model", "test-model")
        # micro precision = tp/(tp+fp) = 3/4, recall = tp/(tp+fn) = 3/4
        assert s["pair_precision"] == pytest.approx(0.75)
        assert s["pair_recall"] == pytest.approx(0.75)
        assert s["avg_latency_s"] == pytest.approx(2.5)
        assert s["most_hallucinated_codes"] == [("600", 1)]
        assert s["most_missed_codes"] == [("689", 1)]

    def test_hard_errors_excluded_from_scoring(self, db_conn):
        reporting.append_result("test-model", {"invoice_id": "A1", "error": "json_parse_error"})
        reporting.append_result("test-model", {
            "invoice_id": "A2", "tp_pairs": 1, "fp_pairs": 0, "fn_pairs": 0,
            "tp_codes": 1, "fp_codes": 0, "fn_codes": 0,
            "exact_pair_match": True, "exact_code_match": True, "balanced": True,
            "fn_code_list": [], "fp_code_list": [], "latency_s": 1.0,
        })
        s = reporting.summarize_model("test-model", "test-model")
        assert s["n_total"] == 2
        assert s["n_scored"] == 1
        assert s["n_hard_errors"] == 1
        assert s["pair_f1"] == 1.0  # sadece skorlanabilen kayit metrige giriyor

    def test_empty_label_does_not_crash_and_returns_zeros(self, db_conn):
        s = reporting.summarize_model("test-model", "test-model")
        assert s["n_total"] == 0
        assert s["pair_f1"] == 0.0
        assert s["avg_latency_s"] == 0.0

    def test_missing_label_treated_as_empty(self, db_conn):
        s = reporting.summarize_model("ghost-model", "ghost-model")
        assert s["n_total"] == 0
        assert s["model"] == "ghost-model"

    def test_dedups_by_invoice_id_keeping_latest_record(self, db_conn):
        """429/403 hatasi alip retry sonrasi basarili olan bir fatura icin
        ayni invoice_id ile iki satir birikir (eski hata + yeni basari). Ozet,
        eski hata satirini bir hard-error gibi sayip sonucu bozmamali - sadece
        son (en guncel, id DESC) kaydi hesaba katmali."""
        reporting.append_result("test-model", {"invoice_id": "A1", "error": "429 Too Many Requests"})
        reporting.append_result("test-model", {
            "invoice_id": "A1", "tp_pairs": 2, "fp_pairs": 0, "fn_pairs": 0,
            "tp_codes": 2, "fp_codes": 0, "fn_codes": 0,
            "exact_pair_match": True, "exact_code_match": True, "balanced": True,
            "fn_code_list": [], "fp_code_list": [], "latency_s": 1.5,
        })
        reporting.append_result("test-model", {
            "invoice_id": "A2", "tp_pairs": 1, "fp_pairs": 0, "fn_pairs": 0,
            "tp_codes": 1, "fp_codes": 0, "fn_codes": 0,
            "exact_pair_match": True, "exact_code_match": True, "balanced": True,
            "fn_code_list": [], "fp_code_list": [], "latency_s": 2.0,
        })
        s = reporting.summarize_model("test-model", "test-model")
        assert s["n_total"] == 2       # A1 tekil sayilir, eski hata satiri dusurulur
        assert s["n_scored"] == 2
        assert s["n_hard_errors"] == 0
        assert s["pair_f1"] == 1.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
