"""_audit_logla() - approvable/red_kodlari alanlari (2026-10-01, kullanici
isteği — "bu tür hatalı şeyleri bizim fark edebilmemiz gerek"). Önceden
audit log sadece `asama` alanını ("başarısız oldu") taşıyordu, HANGİ
deterministik kuralın (PAYABLE_MISMATCH, UNBALANCED vb.) reddettiği
kayıtlı değildi - bu testler yeni alanların doğru doldurulduğunu doğrular."""

import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock


ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

os.environ.setdefault(
    "MCP_INTERNAL_API_TOKEN", "internal-test-token-with-at-least-32-chars"
)

import app as integration_app
from api_anahtarlari import IstemciKimligi


def _istek(**kwargs):
    varsayilan = {"fatura_xml": "<Invoice/>", "satici_vkn": "0460351893"}
    varsayilan.update(kwargs)
    return integration_app.FaturaIsleIstegi(**varsayilan)


def _cevap(asama, approvable=None, validation_errors=None, invoice_id="INV1"):
    tdhp_tahmini = None
    if approvable is not None or validation_errors is not None:
        tdhp_tahmini = integration_app.TdhpTahminiCevabi(
            invoice_id=invoice_id,
            approvable=bool(approvable),
            validation_errors=validation_errors or [],
        )
    return integration_app.FaturaIsleCevabi(asama=asama, yon="outbox", tdhp_tahmini=tdhp_tahmini, mesaj="test")


def _sahte_request():
    req = MagicMock()
    req.client.host = "10.0.0.5"
    return req


def _kimlik():
    return IstemciKimligi(etiket="test-musteri", tum_sirketler=False, izinli_vknler=frozenset({"0460351893"}))


def _audit_satirini_oku(caplog):
    for kayit in caplog.records:
        if kayit.name == "entegrasyon.audit":
            return json.loads(kayit.message)
    raise AssertionError("audit log satiri bulunamadi")


class TestAuditLogRedKodlari:
    def test_payable_mismatch_kodu_audit_loga_yazilir(self, caplog):
        caplog.set_level(logging.INFO, logger="entegrasyon.audit")
        cevap = _cevap(
            "tdhp_dogrulama_basarisiz",
            approvable=False,
            validation_errors=[{"code": "PAYABLE_MISMATCH", "message": "Kayit toplami (100) fatura odenecek tutariyla (200) uyusmuyor."}],
        )
        integration_app._audit_logla(_istek(), cevap, _sahte_request(), _kimlik())
        satir = _audit_satirini_oku(caplog)
        assert satir["approvable"] is False
        assert satir["red_kodlari"] == ["PAYABLE_MISMATCH"]

    def test_mesaj_metni_audit_loga_YAZILMAZ(self, caplog):
        """Hassas detay (tutar vb. icerebilir) audit log'a sizmamali -
        sadece kod yazilir, mesaj metni degil (bkz. modul docstring'i)."""
        caplog.set_level(logging.INFO, logger="entegrasyon.audit")
        cevap = _cevap(
            "tdhp_dogrulama_basarisiz",
            approvable=False,
            validation_errors=[{"code": "PAYABLE_MISMATCH", "message": "Kayit toplami (123456.78) fatura odenecek tutariyla (999.00) uyusmuyor."}],
        )
        integration_app._audit_logla(_istek(), cevap, _sahte_request(), _kimlik())
        satir = _audit_satirini_oku(caplog)
        ham_satir = json.dumps(satir, ensure_ascii=False)
        assert "123456.78" not in ham_satir
        assert "999.00" not in ham_satir

    def test_birden_fazla_red_kodu_siralanir(self, caplog):
        caplog.set_level(logging.INFO, logger="entegrasyon.audit")
        cevap = _cevap(
            "tdhp_dogrulama_basarisiz",
            approvable=False,
            validation_errors=[
                {"code": "UNBALANCED", "message": "..."},
                {"code": "PAYABLE_MISMATCH", "message": "..."},
            ],
        )
        integration_app._audit_logla(_istek(), cevap, _sahte_request(), _kimlik())
        satir = _audit_satirini_oku(caplog)
        assert satir["red_kodlari"] == ["PAYABLE_MISMATCH", "UNBALANCED"]

    def test_basarili_faturada_approvable_true_red_kodlari_bos(self, caplog):
        caplog.set_level(logging.INFO, logger="entegrasyon.audit")
        cevap = _cevap("tdhp_tahmini_tamamlandi", approvable=True, validation_errors=[])
        integration_app._audit_logla(_istek(), cevap, _sahte_request(), _kimlik())
        satir = _audit_satirini_oku(caplog)
        assert satir["approvable"] is True
        assert satir["red_kodlari"] == []

    def test_tdhp_tahmini_hic_yoksa_approvable_none_kirmaz(self, caplog):
        """Ön filtre insan incelemesi bekliyorsa tdhp_tahmini henuz hic
        uretilmemis olabilir - approvable/red_kodlari o durumda guvenli
        varsayilanlara dusmeli, exception firlatmamali."""
        caplog.set_level(logging.INFO, logger="entegrasyon.audit")
        cevap = integration_app.FaturaIsleCevabi(
            asama="on_filtre_insan_incelemesi_bekliyor", yon="outbox", tdhp_tahmini=None, mesaj="test",
        )
        integration_app._audit_logla(_istek(), cevap, _sahte_request(), _kimlik())
        satir = _audit_satirini_oku(caplog)
        assert satir["approvable"] is None
        assert satir["red_kodlari"] == []
