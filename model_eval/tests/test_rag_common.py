"""rag_common.py icin birim testleri.

Calistirmak icin:
    cd model_eval
    python3 -m pytest tests/ -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core as em
import rag_common as rc


# ---------------------------------------------------------------------------
# build_retrieval_text — embedding icin kullanilan metin, sadece kategorik
# bilgi icermeli (tutar/hesap kodu SIZMAMALI)
# ---------------------------------------------------------------------------

SAMPLE_INVOICE = {
    "invoice_id": "INV1",
    "direction": "inbox",
    "header": {
        "account_title": "Turkcell Iletisim Hizmetleri A.S.",
        "account_tax_number": "8770013406",
        "invoice_type": "SATIS",
    },
    "lines": [
        {"product_name": "Tarife ve Paket Ucretleri", "quantity": "1", "total": "207.69 TRY"},
        {"product_name": "", "quantity": "1", "total": "0.00 TRY"},
    ],
    "taxes": [
        {"name": "Katma Deger Vergisi", "code": "0015", "percent": "20", "tax": "41.57 TRY"},
    ],
    "notes": [],
    "gt_pairs": {("191", "Borc"), ("329", "Alacak")},
}


class TestBuildRetrievalText:
    def test_includes_counterparty_and_line_items(self):
        text = rc.build_retrieval_text(SAMPLE_INVOICE)
        assert "Turkcell Iletisim Hizmetleri A.S." in text
        assert "Tarife ve Paket Ucretleri" in text
        assert "Katma Deger Vergisi" in text

    def test_direction_rendered_as_alis_or_satis(self):
        assert "Yon: ALIS" in rc.build_retrieval_text(SAMPLE_INVOICE)
        outbox = dict(SAMPLE_INVOICE, direction="outbox")
        assert "Yon: SATIS" in rc.build_retrieval_text(outbox)

    def test_amounts_and_account_codes_never_leak_into_embedding_text(self):
        """Embedding metni sadece 'ne turden fatura' benzerligini yakalamali -
        tutarlar/hesap kodlari retrieval sinyaline karismamali."""
        text = rc.build_retrieval_text(SAMPLE_INVOICE)
        assert "207.69" not in text
        assert "191" not in text
        assert "329" not in text

    def test_empty_line_names_skipped(self):
        text = rc.build_retrieval_text(SAMPLE_INVOICE)
        assert text.count("Kalem:") == 1  # bos product_name atlanir

    def test_missing_optional_fields_do_not_crash(self):
        minimal = {"invoice_id": "X", "direction": "inbox", "header": {}, "lines": [], "taxes": []}
        text = rc.build_retrieval_text(minimal)
        assert "Yon: ALIS" in text


# ---------------------------------------------------------------------------
# extract_named_gt_entries — ham accounting_entries'i 3 haneli koda gore
# tekillestirme (account_name'i de tasiyarak, evaluate_models.normalize_*
# fonksiyonlariyla ayni mantik)
# ---------------------------------------------------------------------------

class TestExtractNamedGtEntries:
    def test_dedups_by_3_digit_code_and_direction(self):
        raw = {
            "accounting_entries": [
                {"account_code": "191.01.00020", "account_name": "Indirilecek KDV", "dc": "Borç"},
                {"account_code": "191.02.00099", "account_name": "Baska muavin", "dc": "Borç"},
                {"account_code": "329.01.00012", "account_name": "TURKCELL", "dc": "Alacak"},
            ]
        }
        entries = rc.extract_named_gt_entries(raw, em.normalize_code3, em.normalize_dc)
        assert entries == [
            {"code": "191", "dc": "Borc", "name": "Indirilecek KDV"},
            {"code": "329", "dc": "Alacak", "name": "TURKCELL"},
        ]

    def test_first_seen_name_wins_on_dedup(self):
        raw = {
            "accounting_entries": [
                {"account_code": "191.01.00020", "account_name": "Ilk isim", "dc": "Borc"},
                {"account_code": "191.05.00001", "account_name": "Ikinci isim", "dc": "Borc"},
            ]
        }
        entries = rc.extract_named_gt_entries(raw, em.normalize_code3, em.normalize_dc)
        assert entries == [{"code": "191", "dc": "Borc", "name": "Ilk isim"}]

    def test_invalid_entries_skipped(self):
        raw = {"accounting_entries": [{"account_code": "not-a-code", "dc": "Borc"}, {"account_code": "191", "dc": "gecersiz"}]}
        assert rc.extract_named_gt_entries(raw, em.normalize_code3, em.normalize_dc) == []

    def test_missing_key_returns_empty(self):
        assert rc.extract_named_gt_entries({}, em.normalize_code3, em.normalize_dc) == []

    def test_missing_account_name_becomes_empty_string(self):
        raw = {"accounting_entries": [{"account_code": "191", "dc": "Borc"}]}
        entries = rc.extract_named_gt_entries(raw, em.normalize_code3, em.normalize_dc)
        assert entries == [{"code": "191", "dc": "Borc", "name": ""}]


# ---------------------------------------------------------------------------
# invoice_metadata — Chroma metadata semasi (sadece scalar degerler)
# ---------------------------------------------------------------------------

class TestInvoiceMetadata:
    def test_all_values_are_scalars(self):
        meta = rc.invoice_metadata(SAMPLE_INVOICE, [{"code": "191", "dc": "Borc", "name": "x"}])
        for v in meta.values():
            assert isinstance(v, (str, int, float, bool))

    def test_entries_round_trip_through_json(self):
        import json
        named = [{"code": "191", "dc": "Borc", "name": "Indirilecek KDV"}]
        meta = rc.invoice_metadata(SAMPLE_INVOICE, named)
        assert json.loads(meta["entries_json"]) == named

    def test_missing_header_fields_default_to_empty_string(self):
        inv = {"invoice_id": "X", "direction": "inbox", "header": {}}
        meta = rc.invoice_metadata(inv, [])
        assert meta["vkn"] == "" and meta["account_title"] == "" and meta["invoice_type"] == ""


# ---------------------------------------------------------------------------
# format_few_shot_block — LLM promptuna eklenecek Turkce metin
# ---------------------------------------------------------------------------

class TestFormatFewShotBlock:
    def test_empty_list_returns_empty_string(self):
        assert rc.format_few_shot_block([]) == ""

    def test_renders_account_title_and_entries(self):
        similar = [{
            "invoice_id": "OLD1", "distance": 0.1, "account_title": "Turkcell",
            "vkn": "8770013406", "direction": "inbox", "invoice_type": "SATIS",
            "entries": [{"code": "770", "dc": "Borc", "name": "GENEL YONETIM"}],
        }]
        block = rc.format_few_shot_block(similar)
        assert "Turkcell" in block
        assert "770 (GENEL YONETIM) - Borc" in block
        assert "BENZER GECMIS FATURALAR" in block

    def test_entry_without_name_still_renders(self):
        similar = [{
            "invoice_id": "OLD1", "distance": 0.1, "account_title": "X",
            "vkn": "1", "direction": "outbox", "invoice_type": "SATIS",
            "entries": [{"code": "600", "dc": "Alacak", "name": ""}],
        }]
        block = rc.format_few_shot_block(similar)
        assert "600 - Alacak" in block

    def test_no_entries_shows_placeholder(self):
        similar = [{
            "invoice_id": "OLD1", "distance": 0.1, "account_title": "X",
            "vkn": "1", "direction": "inbox", "invoice_type": "SATIS", "entries": [],
        }]
        block = rc.format_few_shot_block(similar)
        assert "(kayit yok)" in block

    def test_multiple_examples_numbered(self):
        similar = [
            {"invoice_id": "A", "distance": 0.3, "account_title": "A", "vkn": "1", "direction": "inbox", "invoice_type": "SATIS", "entries": []},
            {"invoice_id": "B", "distance": 0.4, "account_title": "B", "vkn": "2", "direction": "inbox", "invoice_type": "SATIS", "entries": []},
        ]
        block = rc.format_few_shot_block(similar)
        assert "1. [referans] Karsi taraf: A" in block
        assert "2. [referans] Karsi taraf: B" in block


class TestFormatFewShotBlockTiering:
    """RESULTS.md 6.2: mesafeye gore kademeli dil - guclu eslesme zorlayici,
    zayif eslesme sadece ilham amacli etiketlenir."""

    def test_distance_below_threshold_tagged_strong_match(self):
        similar = [{
            "invoice_id": "A", "distance": rc.STRONG_MATCH_MAX_DISTANCE - 0.01,
            "account_title": "A", "vkn": "1", "direction": "inbox", "invoice_type": "SATIS", "entries": [],
        }]
        block = rc.format_few_shot_block(similar)
        assert "[GUCLU ESLESME] Karsi taraf: A" in block

    def test_distance_at_or_above_threshold_tagged_reference(self):
        similar = [{
            "invoice_id": "A", "distance": rc.STRONG_MATCH_MAX_DISTANCE,
            "account_title": "A", "vkn": "1", "direction": "inbox", "invoice_type": "SATIS", "entries": [],
        }]
        block = rc.format_few_shot_block(similar)
        assert "[referans] Karsi taraf: A" in block

    def test_intro_explains_strong_match_instruction(self):
        similar = [{
            "invoice_id": "A", "distance": 0.01,
            "account_title": "A", "vkn": "1", "direction": "inbox", "invoice_type": "SATIS", "entries": [],
        }]
        block = rc.format_few_shot_block(similar)
        assert "GUCLU ESLESME" in block and "AYNI hesap" in block


# ---------------------------------------------------------------------------
# strongest_precedent / build_precedent_correction_request — self-correct'in
# "RAG emsaline uyulmadi" tetikleyicisi
# ---------------------------------------------------------------------------

class TestStrongestPrecedent:
    def test_returns_none_when_no_candidate_below_threshold(self):
        similar = [{"distance": 0.5}, {"distance": 0.9}]
        assert rc.strongest_precedent(similar) is None

    def test_returns_closest_candidate_below_threshold(self):
        similar = [
            {"distance": 0.1, "account_title": "far-ish"},
            {"distance": 0.02, "account_title": "closest"},
            {"distance": 0.5, "account_title": "too-far"},
        ]
        result = rc.strongest_precedent(similar)
        assert result["account_title"] == "closest"

    def test_empty_list_returns_none(self):
        assert rc.strongest_precedent([]) is None


class TestBuildPrecedentCorrectionRequest:
    STRONG = {
        "account_title": "Turkcell", "distance": 0.02,
        "entries": [{"code": "770", "dc": "Borc", "name": "x"}, {"code": "191", "dc": "Borc", "name": "y"}],
    }

    def test_returns_none_when_prediction_matches_precedent_exactly(self):
        pred_pairs = [("191", "Borc"), ("770", "Borc")]
        assert rc.build_precedent_correction_request(self.STRONG, pred_pairs) is None

    def test_returns_correction_text_when_prediction_differs(self):
        pred_pairs = [("191", "Borc"), ("730", "Borc")]
        text = rc.build_precedent_correction_request(self.STRONG, pred_pairs)
        assert text is not None
        assert "770 (Borc)" in text and "191 (Borc)" in text
        assert "Turkcell" in text

    def test_order_of_pred_pairs_does_not_matter(self):
        pred_pairs = [("730", "Borc"), ("191", "Borc")]
        pred_pairs_reordered = [("191", "Borc"), ("730", "Borc")]
        text1 = rc.build_precedent_correction_request(self.STRONG, pred_pairs)
        text2 = rc.build_precedent_correction_request(self.STRONG, pred_pairs_reordered)
        assert text1 == text2


# ---------------------------------------------------------------------------
# retrieve_similar / _merge_query_result — Chroma sorgu sonucunu birlestirme:
# kendi kendini haric tutma, ayni-VKN oncelikli arama, tekillestirme
# ---------------------------------------------------------------------------

def _chroma_result(ids, distances, metas):
    return {"ids": [ids], "distances": [distances], "metadatas": [metas]}


class TestMergeQueryResult:
    def test_excludes_self_id(self):
        picked = {}
        res = _chroma_result(["SELF", "OTHER"], [0.0, 0.5], [{"account_title": "s"}, {"account_title": "o"}])
        rc._merge_query_result(picked, res, exclude_id="SELF", limit=5)
        assert list(picked.keys()) == ["OTHER"]

    def test_stops_at_limit(self):
        picked = {}
        res = _chroma_result(["A", "B", "C"], [0.1, 0.2, 0.3], [{}, {}, {}])
        rc._merge_query_result(picked, res, exclude_id="X", limit=2)
        assert len(picked) == 2

    def test_does_not_overwrite_already_picked(self):
        picked = {"A": {"invoice_id": "A", "distance": 0.01}}
        res = _chroma_result(["A", "B"], [0.9, 0.2], [{}, {}])
        rc._merge_query_result(picked, res, exclude_id="X", limit=5)
        assert picked["A"]["distance"] == 0.01  # ilk (daha iyi) mesafe korunur

    def test_metadata_entries_json_parsed_back_to_list(self):
        import json
        picked = {}
        entries = [{"code": "191", "dc": "Borc", "name": "x"}]
        res = _chroma_result(["A"], [0.1], [{"entries_json": json.dumps(entries), "account_title": "t", "vkn": "v", "direction": "inbox", "invoice_type": "SATIS"}])
        rc._merge_query_result(picked, res, exclude_id="X", limit=5)
        assert picked["A"]["entries"] == entries

    def test_missing_entries_json_defaults_to_empty_list(self):
        picked = {}
        res = _chroma_result(["A"], [0.1], [{}])
        rc._merge_query_result(picked, res, exclude_id="X", limit=5)
        assert picked["A"]["entries"] == []


class TestRetrieveSimilar:
    def test_prefers_same_vkn_before_global_search(self):
        collection = MagicMock()
        collection.query.side_effect = [
            _chroma_result(["A"], [0.1], [{"account_title": "same-vkn", "vkn": "999", "direction": "inbox", "invoice_type": "SATIS", "entries_json": "[]"}]),
        ]
        result = rc.retrieve_similar(collection, SAMPLE_INVOICE_WITH_VKN(), k=1)
        assert len(result) == 1
        assert result[0]["account_title"] == "same-vkn"
        # sadece bir kez sorgulanmis olmali (ayni-VKN aramasi k'yi doldurdu)
        assert collection.query.call_count == 1
        called_kwargs = collection.query.call_args.kwargs
        assert called_kwargs["where"] == {"vkn": "8770013406"}

    def test_falls_back_to_global_search_when_same_vkn_insufficient(self):
        collection = MagicMock()
        collection.query.side_effect = [
            _chroma_result([], [], []),  # ayni VKN'de sonuc yok
            _chroma_result(["B"], [0.3], [{"account_title": "global", "vkn": "111", "direction": "inbox", "invoice_type": "SATIS", "entries_json": "[]"}]),
        ]
        result = rc.retrieve_similar(collection, SAMPLE_INVOICE_WITH_VKN(), k=1)
        assert len(result) == 1
        assert result[0]["account_title"] == "global"
        assert collection.query.call_count == 2

    def test_results_sorted_by_distance(self):
        collection = MagicMock()
        collection.query.side_effect = [
            _chroma_result(
                ["A", "B"], [0.5, 0.1],
                [
                    {"account_title": "far", "vkn": "1", "direction": "inbox", "invoice_type": "SATIS", "entries_json": "[]"},
                    {"account_title": "near", "vkn": "1", "direction": "inbox", "invoice_type": "SATIS", "entries_json": "[]"},
                ],
            ),
        ]
        result = rc.retrieve_similar(collection, SAMPLE_INVOICE_WITH_VKN(), k=2)
        assert [r["account_title"] for r in result] == ["near", "far"]


def SAMPLE_INVOICE_WITH_VKN():
    inv = dict(SAMPLE_INVOICE)
    inv["header"] = dict(SAMPLE_INVOICE["header"], account_tax_number="8770013406")
    return inv


# ---------------------------------------------------------------------------
# Bos koleksiyon regresyonu (2026-07-30, coklu sirket gecisi): gecmis fatura
# verisi hic olmayan bir sirket icin RAG'in hata FIRLATMADAN "emsal yok"
# davranisina dustugunu acikca dogrular.
# ---------------------------------------------------------------------------

class TestBosKoleksiyonEmsalYok:
    def test_retrieve_similar_bos_koleksiyonda_bos_liste_doner(self):
        collection = MagicMock()
        collection.query.side_effect = [
            _chroma_result([], [], []),
            _chroma_result([], [], []),
        ]
        result = rc.retrieve_similar(collection, SAMPLE_INVOICE_WITH_VKN(), k=3)
        assert result == []

    def test_format_few_shot_block_bos_listede_bos_string(self):
        assert rc.format_few_shot_block([]) == ""

    def test_strongest_precedent_bos_listede_none(self):
        assert rc.strongest_precedent([]) is None


# ---------------------------------------------------------------------------
# koleksiyon_adi_coz / get_collection parametrizasyonu (2026-07-30, coklu
# sirket gecisi) - own_vkn'e gore koleksiyon adi turetme + cache anahtarina
# collection_name'in dahil edilmesi.
# ---------------------------------------------------------------------------

class TestKoleksiyonAdiCoz:
    def test_own_vkn_none_ise_sabit_ada_DUSMEZ(self):
        """2026-07-31 duzeltmesi: own_vkn bos/None geldiginde ARTIK
        Akuzulu'nun (COLLECTION_NAME) koleksiyonuna dusulmez - "hangi sirket
        oldugu bilinmiyor" ile "Akuzulu" karistirilip baska bir sirketin
        faturasi islenirken Akuzulu'nun gecmisinin emsal olarak sizmasi
        (mizan.py::mizan_yolu_coz ile ayni bug'in RAG karsiligi) engellenir."""
        assert rc.koleksiyon_adi_coz(None) != rc.COLLECTION_NAME

    def test_own_vkn_bos_string_ise_sabit_ada_DUSMEZ(self):
        assert rc.koleksiyon_adi_coz("") != rc.COLLECTION_NAME

    def test_own_vkn_default_ise_sabit_ad(self):
        from core.constants import DEFAULT_OWN_VKN
        assert rc.koleksiyon_adi_coz(DEFAULT_OWN_VKN) == rc.COLLECTION_NAME

    def test_baska_vkn_icin_turetilmis_ad(self):
        assert rc.koleksiyon_adi_coz("1111111111") == "tdhp_invoices_1111111111"


class TestGetCollectionCacheKey:
    def test_farkli_collection_name_farkli_cache_girdisi_uretir(self, monkeypatch, tmp_path):
        rc.reset_collection_cache_for_tests()
        olusturulan = []

        class _FakeClient:
            def __init__(self, path):
                pass

            def get_or_create_collection(self, name, embedding_function=None):
                olusturulan.append(name)
                return MagicMock()

        monkeypatch.setattr(rc.chromadb, "PersistentClient", _FakeClient)
        monkeypatch.setattr(rc, "OllamaEmbeddingFunction", MagicMock())

        rc.get_collection(persist_dir=tmp_path, collection_name="tdhp_invoices_1111111111")
        rc.get_collection(persist_dir=tmp_path, collection_name="tdhp_invoices_2222222222")

        assert olusturulan == ["tdhp_invoices_1111111111", "tdhp_invoices_2222222222"]
        rc.reset_collection_cache_for_tests()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
