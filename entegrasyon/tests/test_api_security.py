import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

os.environ.setdefault(
    "MCP_INTERNAL_API_TOKEN", "internal-test-token-with-at-least-32-chars"
)

import api_anahtarlari
import app as integration_app
import security
from api_anahtarlari import IstemciKimligi

client = TestClient(integration_app.app)

YETKILI_VKN = "1234567890"
SAHTE_ANAHTARLAR = {
    "tum-sirketler-anahtari": IstemciKimligi("test-tum", True, frozenset()),
    "sinirli-anahtar": IstemciKimligi("test-sinirli", False, frozenset({YETKILI_VKN})),
}
AUTH = {"Authorization": "Bearer tum-sirketler-anahtari"}
SINIRLI_AUTH = {"Authorization": "Bearer sinirli-anahtar"}


@pytest.fixture(autouse=True)
def _sahte_anahtar_deposu(monkeypatch):
    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", SAHTE_ANAHTARLAR.get)


@pytest.mark.parametrize(
    ("metot", "yol"),
    [("get", "/kayitli-sirketler"), ("post", "/fatura/isle"), ("post", "/fatura/onayla")],
)
def test_business_endpoints_require_key(metot, yol):
    response = getattr(client, metot)(yol)
    assert response.status_code == 401


def test_wrong_key_is_rejected():
    response = client.get("/kayitli-sirketler", headers={"Authorization": "Bearer yanlis"})
    assert response.status_code == 401


def test_key_store_unreachable_returns_503(monkeypatch):
    def _erisilemez(_anahtar):
        raise ConnectionError("veritabani kapali")

    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", _erisilemez)
    response = client.get("/kayitli-sirketler", headers=AUTH)
    assert response.status_code == 503


def test_key_cannot_act_for_other_company(monkeypatch):
    def _cagrilmamali(*_args, **_kwargs):
        raise AssertionError("yetkisiz şirket için işlem yapılmamalı")

    monkeypatch.setattr(integration_app, "_fatura_isle_ic", _cagrilmamali)
    response = client.post(
        "/fatura/isle",
        headers=SINIRLI_AUTH,
        json={"fatura_xml": "<Invoice/>", "satici_vkn": "9999999999"},
    )
    assert response.status_code == 403


def test_registered_companies_are_filtered_by_key(monkeypatch):
    import model_eval_koprusu

    monkeypatch.setattr(integration_app, "model_eval_hazir_mi", lambda: (True, "hazir"))
    monkeypatch.setattr(
        model_eval_koprusu, "kayitli_vknleri_getir", lambda: [YETKILI_VKN, "9999999999"]
    )
    assert client.get("/kayitli-sirketler", headers=SINIRLI_AUTH).json() == {
        "vkn_listesi": [YETKILI_VKN]
    }
    assert client.get("/kayitli-sirketler", headers=AUTH).json() == {
        "vkn_listesi": [YETKILI_VKN, "9999999999"]
    }


def test_health_endpoint_remains_public(monkeypatch):
    monkeypatch.setattr(integration_app, "model_eval_hazir_mi", lambda: (True, "hazir"))
    response = client.get("/durum")
    assert response.status_code == 200
    assert response.json()["model_eval_hazir"] is True
    assert response.headers["x-content-type-options"] == "nosniff"


def test_request_body_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(security, "MAX_REQUEST_BYTES", 32)
    response = client.post(
        "/fatura/isle",
        headers=AUTH,
        json={"fatura_xml": "x" * 100, "satici_vkn": "1234567890"},
    )
    assert response.status_code == 413


def test_unregistered_company_is_rejected_before_prediction(monkeypatch):
    monkeypatch.setattr(integration_app, "model_eval_hazir_mi", lambda: (True, "hazir"))
    monkeypatch.setattr(integration_app, "sirket_kayitli_mi", lambda _vkn: False)

    def _cagrilmamali(*_args, **_kwargs):
        raise AssertionError("onboard edilmemiş şirket için tahmin üretilmemeli")

    monkeypatch.setattr(integration_app, "tdhp_tahmini_yap", _cagrilmamali)
    monkeypatch.setattr(integration_app, "fatura_kontrol_et", _cagrilmamali)

    response = client.post(
        "/fatura/isle",
        headers=AUTH,
        json={"fatura_xml": "<Invoice/>", "satici_vkn": "1234567890"},
    )
    assert response.status_code == 404
    assert "1234567890" in response.json()["detail"]


def test_server_side_prediction_id_is_returned(monkeypatch):
    monkeypatch.setattr(
        integration_app,
        "faturayi_parse_et_ve_yonu_dogrula",
        lambda _xml, _vkn: {"direction": "inbox", "header": {}},
    )
    monkeypatch.setattr(integration_app, "model_eval_hazir_mi", lambda: (True, "hazir"))
    monkeypatch.setattr(integration_app, "sirket_kayitli_mi", lambda _vkn: True)
    monkeypatch.setattr(
        integration_app,
        "fatura_kur_bilgisi",
        lambda _xml, own_vkn: {"currency": "TRY", "exchange_rate": None, "exchange_target_currency": None},
    )
    monkeypatch.setattr(
        integration_app,
        "tdhp_tahmini_yap",
        lambda *_args, **_kwargs: {
            "invoice_id": "INV-1", "direction": "inbox", "currency": "TRY",
            "entries": [{"account_code": "320", "dc": "Alacak", "amount": 100.0}],
            "records": [], "balanced": True, "borc_toplam": 100.0,
            "alacak_toplam": 100.0, "approvable": True,
        },
    )
    monkeypatch.setattr(integration_app, "bekleyen_tahmin_kaydet", lambda *_args: "pred-1")
    monkeypatch.setattr(integration_app, "_test_kaydini_logla", lambda *_args: None)

    response = client.post(
        "/fatura/isle",
        headers=AUTH,
        json={"fatura_xml": "<Invoice/>", "satici_vkn": "1234567890"},
    )
    assert response.status_code == 200
    assert response.json()["prediction_id"] == "pred-1"


def test_approval_accepts_only_prediction_id(monkeypatch):
    monkeypatch.setattr(integration_app, "bekleyen_tahmini_onayla", lambda value, kimlik: "INV-1")
    monkeypatch.setattr(integration_app, "_test_kaydini_onaylandi_isaretle", lambda *_args: None)
    response = client.post(
        "/fatura/onayla",
        headers=AUTH,
        json={"prediction_id": "00000000-0000-4000-8000-000000000001"},
    )
    assert response.status_code == 200

    old_contract = client.post(
        "/fatura/onayla",
        headers=AUTH,
        json={"fatura_xml": "<Invoice/>", "satici_vkn": "123", "tdhp_tahmini": {}},
    )
    assert old_contract.status_code == 422
