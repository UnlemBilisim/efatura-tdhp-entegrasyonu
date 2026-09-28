import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

EXTERNAL_TOKEN = "external-test-token-with-at-least-32-chars"
os.environ.setdefault("EFATURA_API_TOKEN", EXTERNAL_TOKEN)
os.environ.setdefault(
    "MCP_INTERNAL_API_TOKEN", "internal-test-token-with-at-least-32-chars"
)

import app as integration_app
import security


client = TestClient(integration_app.app)
AUTH = {"Authorization": f"Bearer {EXTERNAL_TOKEN}"}


@pytest.mark.skip(
    reason=(
        "2026-09-11 kullanıcı kararı: auth geçici olarak kaldırıldı "
        "(entegrasyon/app.py fatura_isle() notuna bkz.) — auth tekrar "
        "eklenince bu test skip'siz geçmeli."
    )
)
def test_business_endpoint_requires_token():
    response = client.get("/kayitli-sirketler")
    assert response.status_code == 401


@pytest.mark.skip(
    reason=(
        "2026-09-11 kullanıcı kararı: auth geçici olarak kaldırıldı "
        "(entegrasyon/app.py fatura_isle() notuna bkz.) — auth tekrar "
        "eklenince bu test skip'siz geçmeli."
    )
)
def test_wrong_token_is_rejected():
    response = client.get("/kayitli-sirketler", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


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


def test_server_side_prediction_id_is_returned(monkeypatch):
    monkeypatch.setattr(
        integration_app,
        "faturayi_parse_et_ve_yonu_dogrula",
        lambda _xml, _vkn: {"direction": "inbox", "header": {}},
    )
    monkeypatch.setattr(integration_app, "model_eval_hazir_mi", lambda: (True, "hazir"))
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
    monkeypatch.setattr(integration_app, "bekleyen_tahmini_onayla", lambda value: "INV-1")
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
