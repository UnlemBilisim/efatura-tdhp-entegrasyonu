"""core.single icin birim testleri (predict_single_invoice).

Calistirmak icin:
    cd model_eval
    python3 -m pytest tests/test_single.py -v
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.single as single

OWN_VKN = "0460351893"

SAMPLE_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>TEST2026000000001</cbc:ID>
  <cbc:IssueDate>2026-01-15</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID>9990011223</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>ORNEK TEDARIKCI A.S.</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID>{OWN_VKN}</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>AKYUZLU DOVME</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cac:TaxSubtotal>
      <cbc:TaxAmount>100.00</cbc:TaxAmount>
      <cbc:Percent>20</cbc:Percent>
      <cac:TaxCategory>
        <cac:TaxScheme><cbc:Name>Katma Deger Vergisi</cbc:Name><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:AllowanceTotalAmount>0.00</cbc:AllowanceTotalAmount>
    <cbc:TaxExclusiveAmount>500.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>600.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>600.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:InvoicedQuantity unitCode="C62">1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>500.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Ornek Hizmet</cbc:Name></cac:Item>
  </cac:InvoiceLine>
</Invoice>
"""


def _balanced_response():
    return (
        '{"entries": [{"account_code": "191", "amount": 100.00, "dc": "Borc"}, '
        '{"account_code": "770", "amount": 500.00, "dc": "Borc"}, '
        '{"account_code": "320", "amount": 600.00, "dc": "Alacak"}]}',
        0.5,
        None,
    )


class TestPredictSingleInvoiceHappyPath:
    def test_end_to_end_with_mock_provider_no_rag(self):
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}

        with patch.object(single, "call_model", return_value=_balanced_response()) as mock_call:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        mock_call.assert_called_once()
        assert result["invoice_id"] == "TEST2026000000001"
        assert result["direction"] == "inbox"
        assert result["error"] is None
        assert result["balanced"] is True
        assert result["borc_toplam"] == 600.00
        assert result["alacak_toplam"] == 600.00

    def test_amount_field_is_present_and_correct_per_entry(self):
        """score_entries() amount'u atiyordu (sadece (code3, dc) ciftini
        tutuyordu) - bu regresyonun aynen predict_single_invoice'a
        sizmadigini dogrular: her entry kendi amount'unu tasimali."""
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}

        with patch.object(single, "call_model", return_value=_balanced_response()):
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        by_code = {(e["account_code"], e["dc"]): e["amount"] for e in result["entries"]}
        assert by_code[("191", "Borc")] == 100.00
        assert by_code[("770", "Borc")] == 500.00
        assert by_code[("320", "Alacak")] == 600.00

    def test_model_string_is_parsed_via_parse_model_spec(self):
        """model parametresi hazir bir spec dict yerine ham bir string de
        olabilir ('ollama:xxx' gibi, core.cli --models ile ayni sozdizimi)."""
        with patch.object(single, "call_model", return_value=_balanced_response()) as mock_call:
            single.predict_single_invoice(
                SAMPLE_XML, model="ollama:test-model", own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        called_spec = mock_call.call_args[0][0]
        assert called_spec["provider"] == "ollama"
        assert called_spec["model"] == "test-model"

    def test_model_string_without_ollama_host_falls_back_to_default(self):
        """Regresyon: ollama_host verilmeden (varsayilan None) bir model
        string'i kullanildiginda base_url None KALMAMALI - onceden
        parse_model_spec(model, None) cagrilip base_url=None uretiyordu,
        bu da call_ollama_messages'ta host.rstrip("/") ile AttributeError'a
        yol aciyordu (entegrasyon/ ile uctan uca testte bulundu, PROJECT.md
        SS4.1). ollama_host=None -> DEFAULT_OLLAMA_HOST'a dusmeli."""
        with patch.object(single, "call_model", return_value=_balanced_response()) as mock_call:
            single.predict_single_invoice(
                SAMPLE_XML, model="ollama:test-model", own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        called_spec = mock_call.call_args[0][0]
        assert called_spec["base_url"] is not None
        assert called_spec["base_url"] == single.DEFAULT_OLLAMA_HOST

    def test_no_db_write_happens(self):
        """predict_single_invoice DB'ye (core.reporting/core.db) HICBIR SEY
        yazmamali - append_result/get_conn hic cagrilmamali."""
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}

        with patch.object(single, "call_model", return_value=_balanced_response()), \
             patch("core.reporting.append_result") as mock_append, \
             patch("core.db.get_conn") as mock_get_conn:
            single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        mock_append.assert_not_called()
        mock_get_conn.assert_not_called()


class TestPredictSingleInvoiceErrorHandling:
    def test_provider_error_returns_error_field_not_exception(self):
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}

        with patch.object(single, "call_model", return_value=(None, None, "429 Too Many Requests")):
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        assert result["error"] == "429 Too Many Requests"
        assert result["entries"] == []
        assert result["balanced"] is False

    def test_unparseable_model_output_returns_parse_error(self):
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}

        with patch.object(single, "call_model", return_value=("bunlar JSON degil ne yazik", 0.5, None)):
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        assert result["error"] == "json_parse_error"
        assert result["entries"] == []


class TestPredictSingleInvoiceSelfCorrect:
    def test_unbalanced_response_triggers_balance_correction(self):
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}

        unbalanced = '{"entries": [{"account_code": "770", "amount": 500.00, "dc": "Borc"}]}'
        corrected = _balanced_response()[0]

        with patch.object(single, "call_model", return_value=(unbalanced, 0.5, None)), \
             patch.object(single, "self_correct_ollama", return_value=(corrected, 0.3, None)) as mock_correct:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=True, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        mock_correct.assert_called_once()
        assert result["self_corrected"] is True
        assert result["self_correct_reason"] == "balance"
        assert result["balanced"] is True

    def test_balanced_response_does_not_trigger_correction(self):
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}

        with patch.object(single, "call_model", return_value=_balanced_response()), \
             patch.object(single, "self_correct_ollama") as mock_correct:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=True, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        mock_correct.assert_not_called()
        assert result["self_corrected"] is False
        assert result["self_correct_reason"] is None

    def test_self_correct_skipped_for_non_ollama_provider(self):
        """self_correct_ollama sadece Ollama icin calisir (core/runner.py'daki
        ayni kisitlama) - baska bir provider'da dengesiz cevap duzeltilmeye
        CALISILMAZ, oldugu gibi doner."""
        spec = {"provider": "openai", "model": "gpt-4.1", "base_url": None, "api_key_env": None, "label": "openai:gpt-4.1"}
        unbalanced = '{"entries": [{"account_code": "770", "amount": 500.00, "dc": "Borc"}]}'

        with patch.object(single, "call_model", return_value=(unbalanced, 0.5, None)), \
             patch.object(single, "self_correct_ollama") as mock_correct:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=True, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        mock_correct.assert_not_called()
        assert result["self_corrected"] is False
        assert result["balanced"] is False


class TestPredictSingleInvoiceRag:
    def _fake_rag_common(self, strong_precedent):
        return SimpleNamespace(
            DEFAULT_PERSIST_DIR="x", DEFAULT_EMBED_MODEL="y",
            get_collection=lambda **kw: object(),
            retrieve_similar=lambda collection, invoice, k: [strong_precedent] if strong_precedent else [],
            format_few_shot_block=lambda similar: "BLOK" if similar else "",
            strongest_precedent=lambda similar: strong_precedent,
            build_precedent_correction_request=lambda strong, pred_pairs: (
                None if set(pred_pairs) == {(e["code"], e["dc"]) for e in strong["entries"]}
                else "LUTFEN DUZELT"
            ),
        )

    def test_precedent_mismatch_triggers_correction_when_balanced(self, monkeypatch):
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        strong = {
            "invoice_id": "OLD1", "distance": 0.01, "account_title": "Ornek",
            "vkn": "9990011223", "direction": "inbox", "invoice_type": "SATIS",
            "entries": [{"code": "191", "dc": "Borc", "name": "x"}, {"code": "730", "dc": "Borc", "name": "y"}, {"code": "320", "dc": "Alacak", "name": "z"}],
        }
        monkeypatch.setitem(sys.modules, "rag_common", self._fake_rag_common(strong))

        # 770 yerine emsaldeki 730 kullansaydi eslesirdi - burada FARKLI (dengeli ama emsalden sapan)
        first_response = _balanced_response()[0]
        corrected_response = (
            '{"entries": [{"account_code": "191", "amount": 100.00, "dc": "Borc"}, '
            '{"account_code": "730", "amount": 500.00, "dc": "Borc"}, '
            '{"account_code": "320", "amount": 600.00, "dc": "Alacak"}]}'
        )

        with patch.object(single, "call_model", return_value=(first_response, 0.5, None)), \
             patch.object(single, "self_correct_ollama", return_value=(corrected_response, 0.3, None)) as mock_correct:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=True, self_correct=True, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        mock_correct.assert_called_once()
        assert result["self_correct_reason"] == "precedent_mismatch"
        assert any(e["account_code"] == "730" for e in result["entries"])

    def test_rag_disabled_never_imports_rag_common_path(self):
        """rag=False iken rag_common hic import edilmemeli/kullanilmamali -
        self_correct=True olsa bile precedent_mismatch mantigina hic girilmez."""
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}

        with patch.object(single, "call_model", return_value=_balanced_response()), \
             patch.object(single, "self_correct_ollama") as mock_correct:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=True, tevkifat_hint=False, iade_hint=False, alt_kirilim=False,
            )

        mock_correct.assert_not_called()
        assert result["error"] is None


class TestPredictSingleInvoiceAltKirilim:
    """core/mizan.py::get_alt_kirilimlar() ile ikinci LLM cagrisinin
    entries'teki 3 haneli kodlari alt kirilima cevirdigini dogrular
    (2026-07-24 eklendi, kullanici karari: "model butun alt kirilimlari
    bilebilmeli")."""

    def _fake_alt_kirilimlar(self):
        # NOT (2026-07-27): 320'nin adi BILEREK SAMPLE_XML'deki karsi tarafla
        # ("ORNEK TEDARIKCI A.S.") eslesMEYEN bir isim ("Baska Firma Ltd.") -
        # bu testler LLM/fallback yolunu test ediyor; yeni deterministik fuzzy
        # esleme (core/single.py::_cari_fuzzy_esles, %85 esik) devreye girip
        # 320'yi LLM'e sormadan otomatik cozmesin diye. Fuzzy'nin KENDISININ
        # dogru esleme yaptigi ayri bir test asagida (test_cari_fuzzy_*).
        return {
            "191": [("191.05.00005", "%20 5/10 Tevkifatli KDV")],
            "770": [("770.01.00027", "Diger Cesitli Giderler")],
            "320": [("320.01.00018", "Baska Firma Insaat Nakliyat Ltd Sti")],
        }

    def test_alt_kirilim_replaces_3_digit_codes(self, monkeypatch):
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        monkeypatch.setattr(single, "get_alt_kirilimlar", lambda mizan_path=None: self._fake_alt_kirilimlar())

        secim_response = (
            '{"secimler": ['
            '{"ana_kod": "191", "alt_kod": "191.05.00005"}, '
            '{"ana_kod": "770", "alt_kod": "770.01.00027"}, '
            '{"ana_kod": "320", "alt_kod": "320.01.00018"}]}'
        )
        responses = [_balanced_response(), (secim_response, 0.2, None)]

        with patch.object(single, "call_model", side_effect=responses) as mock_call:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False,
                alt_kirilim=True,
            )

        assert mock_call.call_count == 2
        by_dc = {e["dc"]: e["account_code"] for e in result["entries"]}
        assert by_dc["Borc"] in ("191.05.00005", "770.01.00027")
        codes = {e["account_code"] for e in result["entries"]}
        assert codes == {"191.05.00005", "770.01.00027", "320.01.00018"}

    def test_alt_kirilim_skips_code_not_in_llm_choice(self, monkeypatch):
        """LLM bir kod icin secim yapmazsa (ya da uygun secenek bulamadigini
        belirtirse) o kod 3 haneli halinde KALIR, uydurulmaz."""
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        monkeypatch.setattr(single, "get_alt_kirilimlar", lambda mizan_path=None: self._fake_alt_kirilimlar())

        # Sadece 191 icin secim var, 770 ve 320 icin yok.
        secim_response = '{"secimler": [{"ana_kod": "191", "alt_kod": "191.05.00005"}]}'
        responses = [_balanced_response(), (secim_response, 0.2, None)]

        with patch.object(single, "call_model", side_effect=responses):
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False,
                alt_kirilim=True,
            )

        codes = {e["account_code"] for e in result["entries"]}
        assert codes == {"191.05.00005", "770", "320"}

    def test_alt_kirilim_llm_hallucination_is_rejected(self, monkeypatch):
        """LLM, mizan'da OLMAYAN bir alt kod uydurursa bu secim YOK SAYILIR -
        3 haneli kodda kalinir."""
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        monkeypatch.setattr(single, "get_alt_kirilimlar", lambda mizan_path=None: self._fake_alt_kirilimlar())

        secim_response = '{"secimler": [{"ana_kod": "191", "alt_kod": "191.99.99999"}]}'
        # 1 kez otomatik yeniden deneme oldugu icin (bkz. _alt_kirilim_uygula)
        # ayni gecersiz cevap IKI KEZ verilir - retry de kurtaramaz, 3 haneli kalir.
        responses = [_balanced_response(), (secim_response, 0.2, None), (secim_response, 0.2, None)]

        with patch.object(single, "call_model", side_effect=responses):
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False,
                alt_kirilim=True,
            )

        codes = {e["account_code"] for e in result["entries"]}
        assert "191.99.99999" not in codes
        assert "191" in codes

    def test_alt_kirilim_call_failure_falls_back_silently(self, monkeypatch):
        """Alt kirilim cagrisi hata verirse (ikinci call_model basarisiz)
        ana tahmin ETKILENMEZ - entries 3 haneli halinde doner, result["error"]
        None kalir (bu adimin basarisizligi ana tahmini basarisiz SAYMAZ)."""
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        monkeypatch.setattr(single, "get_alt_kirilimlar", lambda mizan_path=None: self._fake_alt_kirilimlar())

        # 1 kez otomatik yeniden deneme oldugu icin (bkz. _alt_kirilim_uygula)
        # HER IKI denemede de hata donmesi gerekir ki kalici basarisizlik test edilsin.
        responses = [
            _balanced_response(),
            (None, None, "500 Internal Server Error"),
            (None, None, "500 Internal Server Error"),
        ]

        with patch.object(single, "call_model", side_effect=responses):
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False,
                alt_kirilim=True,
            )

        assert result["error"] is None
        codes = {e["account_code"] for e in result["entries"]}
        assert codes == {"191", "770", "320"}

    def test_alt_kirilim_retries_once_and_recovers(self, monkeypatch):
        """Ilk alt kirilim denemesi basarisiz olursa (hata/gecersiz cevap),
        OTOMATIK olarak 1 kez daha denenir - ikinci deneme basarili olursa
        sonuc dogru alt kirilimla doner (2026-07-24, kullanici karari:
        50 gercek fatura testinde gecici hatalarin sessizce 3 haneliye
        dusmesi gozlemlendi, LLM'in kendisi tutarliydi)."""
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        monkeypatch.setattr(single, "get_alt_kirilimlar", lambda mizan_path=None: self._fake_alt_kirilimlar())

        secim_response = '{"secimler": [{"ana_kod": "191", "alt_kod": "191.05.00005"}]}'
        responses = [
            _balanced_response(),
            (None, None, "geçici ağ hatası"),  # ilk alt kirilim denemesi basarisiz
            (secim_response, 0.2, None),  # otomatik ikinci deneme basarili
        ]

        with patch.object(single, "call_model", side_effect=responses) as mock_call:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False,
                alt_kirilim=True,
            )

        assert mock_call.call_count == 3
        codes = {e["account_code"] for e in result["entries"]}
        assert "191.05.00005" in codes

    def test_alt_kirilim_disabled_skips_second_call(self, monkeypatch):
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        monkeypatch.setattr(single, "get_alt_kirilimlar", lambda mizan_path=None: self._fake_alt_kirilimlar())

        with patch.object(single, "call_model", return_value=_balanced_response()) as mock_call:
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False,
                alt_kirilim=False,
            )

        mock_call.assert_called_once()
        codes = {e["account_code"] for e in result["entries"]}
        assert codes == {"191", "770", "320"}

    def test_cari_hesap_cozulemezse_uyari_eklenir(self, monkeypatch):
        """320 (cari/tedarikci) alt kirilima cozulemezse (mizanda karsi taraf
        yok), o entry'ye 'yeni karsi taraf' uyarisi eklenir - 770 (gider) ayni
        sekilde cozulemese bile UYARI ALMAZ (2026-07-24 kullanici karari,
        CARI_HESAP_KODLARI)."""
        spec = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
        monkeypatch.setattr(single, "get_alt_kirilimlar", lambda mizan_path=None: self._fake_alt_kirilimlar())

        # LLM sadece 191'i cozer, 320 (cari) ve 770 (gider) cozulmez
        secim_response = '{"secimler": [{"ana_kod": "191", "alt_kod": "191.05.00005"}]}'
        responses = [_balanced_response(), (secim_response, 0.2, None)]

        with patch.object(single, "call_model", side_effect=responses):
            result = single.predict_single_invoice(
                SAMPLE_XML, model=spec, own_vkn=OWN_VKN,
                rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False,
                alt_kirilim=True,
            )

        by_code = {e["account_code"]: e for e in result["entries"]}
        # 320 cari hesap, 3 haneli kaldi -> uyari OLMALI
        assert by_code["320"].get("uyari") is not None
        assert "mizanda bulunamadı" in by_code["320"]["uyari"]
        # 770 gider hesabi, 3 haneli kaldi ama cari DEGIL -> uyari OLMAMALI
        assert by_code["770"].get("uyari") is None
        # 191 cozuldu -> uyari yok
        assert by_code["191.05.00005"].get("uyari") is None


class TestCariFuzzyEsleme:
    """Cari hesap alt kirilimini karsi taraf unvanina gore ISIM BENZERLIGIYLE
    esleme (2026-07-27, %85 esik, LLM'den ONCE deterministik - bkz.
    core/single.py::_cari_fuzzy_esles, memory alt-kirilim-fuzzy-esleme)."""

    ALT_320 = [
        ("320.01.00001", "Acos Makina Sanayi Ve Ticaret Limited Şirketi"),
        ("320.01.00002", "Aşan Çelik Yapı Makine İnş.Turizm San.Ve Tic.Ltd.Şti"),
        ("320.01.00003", "Migros Ticaret Anonim Şirketi"),
    ]

    def test_birebir_eslesme_secilir(self):
        kod, oran = single._cari_fuzzy_esles(
            "Acos Makina Sanayi Ve Ticaret Limited Şirketi", self.ALT_320
        )
        assert kod == "320.01.00001"
        assert oran >= single.CARI_FUZZY_ESIK

    def test_yazim_farki_kisaltma_yine_eslesir(self):
        """Mizanda kisaltmali ('İnş.Turizm San.Ve Tic.Ltd.Şti'), faturada acik
        yazim -> normalizasyon kisaltmalari actigi icin yine %85 ustu eslesir.
        Bu, bu ozelligin cozmek icin eklendigi ANA senaryodur."""
        kod, oran = single._cari_fuzzy_esles(
            "Aşan Çelik Yapı Makine İnşaat Turizm Sanayi Ve Ticaret Limited Şirketi",
            self.ALT_320,
        )
        assert kod == "320.01.00002"
        assert oran >= single.CARI_FUZZY_ESIK

    def test_mizanda_olmayan_esik_altinda_kalir(self):
        """Karsi taraf mizanda gercekten yoksa (ornek: Gumruk Bakanligi) hicbir
        alt kod esige ulasmaz -> None doner, kod 3 haneli kalir (uydurma yok)."""
        kod, oran = single._cari_fuzzy_esles("Gümrük ve Ticaret Bakanlığı", self.ALT_320)
        assert kod is None
        assert oran < single.CARI_FUZZY_ESIK

    def test_bos_unvan_guvenli(self):
        assert single._cari_fuzzy_esles(None, self.ALT_320) == (None, 0.0)
        assert single._cari_fuzzy_esles("Acos", []) == (None, 0.0)


class TestKdvOraniDuzelt:
    """KDV alt kirilim ORAN duzeltmesi (2026-07-27, kullanici karari: LLM turu
    secer, kod yalnizca orani faturaya gore duzeltir - bkz. core/single.py::
    _kdv_oranini_duzelt). Degismez Kural 1: oran LLM'den degil faturadan gelir."""

    ALT_391 = [
        ("391.01.00010", "%10 Hesaplanan KDV"),
        ("391.01.00020", "%20 Hesaplanan KDV"),
        ("391.02.00010", "%10 Alıştan İade KDV"),
        ("391.02.00020", "%20 Alıştan İade KDV"),
        ("391.04.00020", "%20 İhraç Kayıtlı KDV"),
    ]
    ALT_730 = [("730.01.00031", "Genel Üretim Koruyucu Ekipman Gideri")]

    def test_yanlis_oran_ayni_tur_icinde_duzeltilir(self):
        """ANA BUG: LLM 391.02.00020 (%20) sectiyse ama fatura %10 ise, ayni tur
        (391.02) icinde %10'a = 391.02.00010'a cevrilir - tur (Alistan Iade) korunur."""
        assert single._kdv_oranini_duzelt("391.02.00020", self.ALT_391, {10}) == "391.02.00010"

    def test_dogru_oran_degismez(self):
        assert single._kdv_oranini_duzelt("391.02.00010", self.ALT_391, {10}) == "391.02.00010"

    def test_tur_korunur_baska_grup_secilmez(self):
        """%20 Hesaplanan (391.01) -> fatura %10 -> 391.01.00010; Alistan Iade
        grubuna (391.02) ATLAMAZ, tur LLM'in secimi olarak kalir."""
        assert single._kdv_oranini_duzelt("391.01.00020", self.ALT_391, {10}) == "391.01.00010"

    def test_grupta_o_oran_yoksa_dokunmaz(self):
        # İhraç grubunda (391.04) sadece %20 var; fatura %5 -> uygun yok -> aynen kalir.
        assert single._kdv_oranini_duzelt("391.04.00020", self.ALT_391, {5}) == "391.04.00020"

    def test_kdv_disi_kod_degismez(self):
        assert single._kdv_oranini_duzelt("730.01.00031", self.ALT_730, {10}) == "730.01.00031"

    def test_fatura_orani_bilinmiyorsa_dokunmaz(self):
        assert single._kdv_oranini_duzelt("391.02.00020", self.ALT_391, set()) == "391.02.00020"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
