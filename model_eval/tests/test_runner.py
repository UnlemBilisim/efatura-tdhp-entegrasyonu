"""core.runner icin birim testleri (PostgreSQL uzerinden).

Calistirmak icin:
    cd model_eval
    python3 -m pytest tests/ -v
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.parsing as parsing
import core.reporting as reporting
import core.runner as runner
from core.constants import SYSTEM_PROMPT
from conftest import SAMPLE_INVOICE_JSON, requires_postgres

pytestmark = requires_postgres


def _latest_records_for(file_label):
    """Test dogrulamasi icin: her invoice_id'nin EN SON kaydini doner (eski
    jsonl'de dedup edilmis okuma assertion'larinin karsiligi)."""
    return reporting._latest_records(file_label)


def _all_raw_records_for(file_label):
    """Test dogrulamasi icin: bir file_label altindaki TUM ham satirlari
    (dedup edilmeden, id sirasiyla) doner - eski jsonl dosyasindaki "kac
    satir birikti" assertion'larinin karsiligi."""
    from core import db
    file_label = reporting.sanitize_file_label(file_label)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT record FROM model_eval_sonuclar WHERE file_label = %s ORDER BY id",
                (file_label,),
            )
            return [row[0] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# run_model — resumability: daha once islenmis fatura tekrar API'ye gitmemeli
# ---------------------------------------------------------------------------

class TestRunModelResumability:
    def test_already_done_invoices_are_skipped(self, db_conn, tmp_path, invoice_file):
        p = invoice_file("A1-x-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        inv["invoice_id"] = "A1"

        reporting.append_result("ollama:test-model", {"invoice_id": "A1", "tp_pairs": 1})

        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        args = SimpleNamespace(output_dir=str(tmp_path), overwrite=False, concurrency=2, temperature=0.0, timeout=30)

        with patch.object(runner, "call_model") as mock_call:
            runner.run_model(spec, [inv], args, "Test Sektoru")

        mock_call.assert_not_called()  # zaten sonucu var, tekrar API'ye gidilmemeli

    def test_overwrite_flag_reruns_everything(self, db_conn, tmp_path, invoice_file):
        p = invoice_file("A1-x-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        inv["invoice_id"] = "A1"

        reporting.append_result("ollama:test-model", {"invoice_id": "A1", "tp_pairs": 1})

        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        args = SimpleNamespace(output_dir=str(tmp_path), overwrite=True, concurrency=2, temperature=0.0, timeout=30)

        with patch.object(runner, "call_model", return_value=('{"entries": []}', 0.5, None)) as mock_call:
            runner.run_model(spec, [inv], args, "Test Sektoru")

        mock_call.assert_called_once()

    def test_previously_errored_invoice_is_retried_not_skipped(self, db_conn, tmp_path, invoice_file):
        """429/403 gibi bir hatayla biten fatura, done sayilmamali - bir sonraki
        calistirmada otomatik olarak tekrar API'ye gitmeli."""
        p = invoice_file("A1-x-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        inv["invoice_id"] = "A1"

        reporting.append_result("ollama:test-model", {"invoice_id": "A1", "error": "429 Too Many Requests"})

        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        args = SimpleNamespace(output_dir=str(tmp_path), overwrite=False, concurrency=2, temperature=0.0, timeout=30)

        with patch.object(runner, "call_model", return_value=('{"entries": []}', 0.5, None)) as mock_call:
            runner.run_model(spec, [inv], args, "Test Sektoru")

        mock_call.assert_called_once()  # hatali oldugu icin tekrar denenmis olmali

        records = _all_raw_records_for("ollama:test-model")
        assert len(records) == 2  # eski hata satiri + yeni basarili deneme, ikisi de tabloda kalir

    def test_records_include_sent_prompts_for_success_and_error(self, db_conn, tmp_path, invoice_file):
        """Kullanicinin kaydinda gonderilen prompt'u gorebilmesi icin her
        kayitta (basarili ya da hatali) sent_system_prompt / sent_user_prompt
        alani olmali."""
        p = invoice_file("A1-x-inbox.json", SAMPLE_INVOICE_JSON)
        inv_ok = parsing.parse_invoice(p)
        inv_ok["invoice_id"] = "OK1"
        p2 = invoice_file("A2-x-inbox.json", SAMPLE_INVOICE_JSON)
        inv_err = parsing.parse_invoice(p2)
        inv_err["invoice_id"] = "ERR1"

        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        args = SimpleNamespace(output_dir=str(tmp_path), overwrite=False, concurrency=2, temperature=0.0, timeout=30)

        with patch.object(runner, "call_model", side_effect=[
            ('{"entries": []}', 0.5, None),
            (None, None, "429 Too Many Requests"),
        ]) as mock_call:
            runner.run_model(spec, [inv_ok, inv_err], args, "Test Sektoru")

        records = _latest_records_for("ollama:test-model")
        assert len(records) == 2
        for rec in records:
            assert "sent_system_prompt" in rec and rec["sent_system_prompt"] == SYSTEM_PROMPT
            assert "sent_user_prompt" in rec and "FATURA BILGILERI" in rec["sent_user_prompt"]


# ---------------------------------------------------------------------------
# run_model + --rag + --self-correct — RESULTS.md 6.2: model, RAG'in gosterdigi
# GUCLU bir emsalden farkli (ama dengeli) bir kod urettiginde de duzeltme
# turu tetiklenmeli (sadece dengesizlikte degil).
# ---------------------------------------------------------------------------

class TestRunModelRagPrecedentSelfCorrect:
    def _fake_rag_common(self, strong_precedent):
        return SimpleNamespace(
            get_collection=lambda **kw: object(),
            retrieve_similar=lambda collection, invoice, k: [strong_precedent],
            format_few_shot_block=lambda similar: "BLOK",
            strongest_precedent=lambda similar: strong_precedent,
            build_precedent_correction_request=lambda strong, pred_pairs: (
                None if set(pred_pairs) == {(e["code"], e["dc"]) for e in strong["entries"]}
                else "LUTFEN DUZELT"
            ),
        )

    def _base_args(self, output_dir):
        return SimpleNamespace(
            output_dir=str(output_dir), overwrite=True, concurrency=1, temperature=0.0, timeout=30,
            rag=True, rag_k=3, rag_persist_dir="x", rag_embed_model="y", rag_ollama_host=None,
            self_correct=True,
        )

    def test_precedent_mismatch_triggers_correction_when_balanced(self, db_conn, tmp_path, invoice_file, monkeypatch):
        p = invoice_file("A1-x-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        inv["invoice_id"] = "A1"

        strong = {
            "invoice_id": "OLD1", "distance": 0.01, "account_title": "Turkcell",
            "vkn": "1", "direction": "inbox", "invoice_type": "SATIS",
            "entries": [{"code": "770", "dc": "Borc", "name": "x"}, {"code": "320", "dc": "Alacak", "name": "y"}],
        }
        monkeypatch.setitem(sys.modules, "rag_common", self._fake_rag_common(strong))

        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        args = self._base_args(tmp_path)

        # ilk cevap DENGELI (100==100) ama emsaldeki 770 yerine 730 kullaniyor
        first_response = json.dumps({"entries": [
            {"account_code": "730", "amount": 100, "dc": "Borc"},
            {"account_code": "320", "amount": 100, "dc": "Alacak"},
        ]})
        corrected_response = json.dumps({"entries": [
            {"account_code": "770", "amount": 100, "dc": "Borc"},
            {"account_code": "320", "amount": 100, "dc": "Alacak"},
        ]})

        with patch.object(runner, "call_model", return_value=(first_response, 0.5, None)), \
             patch.object(runner, "self_correct_ollama", return_value=(corrected_response, 0.3, None)) as mock_correct:
            runner.run_model(spec, [inv], args, "Test Sektoru")

        mock_correct.assert_called_once()
        records = _latest_records_for("ollama:test-model+selfcorrect+rag")
        assert len(records) == 1
        rec = records[0]
        assert rec["self_corrected"] is True
        assert rec["self_correct_reason"] == "precedent_mismatch"
        assert ["770", "Borc"] in rec["pred_pairs"]

    def test_balance_issue_takes_priority_over_precedent_check(self, db_conn, tmp_path, invoice_file, monkeypatch):
        """Ayni anda hem dengesizlik hem emsal-uyumsuzlugu varsa, once dengesizlik
        duzeltilmeye calisilir (RAG'in verecegi kod onerisi anlamsizdir cunku
        cevap zaten matematiksel olarak gecersiz)."""
        p = invoice_file("A1-x-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        inv["invoice_id"] = "A1"

        strong = {
            "invoice_id": "OLD1", "distance": 0.01, "account_title": "Turkcell",
            "vkn": "1", "direction": "inbox", "invoice_type": "SATIS",
            "entries": [{"code": "770", "dc": "Borc", "name": "x"}],
        }
        monkeypatch.setitem(sys.modules, "rag_common", self._fake_rag_common(strong))

        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        args = self._base_args(tmp_path)

        # DENGESIZ (100 != 0) ve emsalden de farkli
        first_response = json.dumps({"entries": [{"account_code": "730", "amount": 100, "dc": "Borc"}]})
        corrected_response = json.dumps({"entries": [{"account_code": "730", "amount": 100, "dc": "Borc"}]})

        with patch.object(runner, "call_model", return_value=(first_response, 0.5, None)), \
             patch.object(runner, "self_correct_ollama", return_value=(corrected_response, 0.3, None)) as mock_correct:
            runner.run_model(spec, [inv], args, "Test Sektoru")

        mock_correct.assert_called_once()
        records = _latest_records_for("ollama:test-model+selfcorrect+rag")
        assert len(records) == 1
        assert records[0]["self_correct_reason"] == "balance"

    def test_no_correction_when_prediction_already_matches_precedent(self, db_conn, tmp_path, invoice_file, monkeypatch):
        p = invoice_file("A1-x-inbox.json", SAMPLE_INVOICE_JSON)
        inv = parsing.parse_invoice(p)
        inv["invoice_id"] = "A1"

        strong = {
            "invoice_id": "OLD1", "distance": 0.01, "account_title": "Turkcell",
            "vkn": "1", "direction": "inbox", "invoice_type": "SATIS",
            "entries": [{"code": "770", "dc": "Borc", "name": "x"}, {"code": "320", "dc": "Alacak", "name": "y"}],
        }
        monkeypatch.setitem(sys.modules, "rag_common", self._fake_rag_common(strong))

        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        args = self._base_args(tmp_path)

        # ilk cevap zaten emsalle ayni ve dengeli - duzeltme turu GEREKSIZ
        response = json.dumps({"entries": [
            {"account_code": "770", "amount": 100, "dc": "Borc"},
            {"account_code": "320", "amount": 100, "dc": "Alacak"},
        ]})

        with patch.object(runner, "call_model", return_value=(response, 0.5, None)), \
             patch.object(runner, "self_correct_ollama") as mock_correct:
            runner.run_model(spec, [inv], args, "Test Sektoru")

        mock_correct.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
