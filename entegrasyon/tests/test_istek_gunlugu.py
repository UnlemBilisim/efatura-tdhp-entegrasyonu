"""İstek günlüğü: her istek için tek JSON satırı, hata mesajı dahil; gövde/başlık/girdi ASLA loglanmaz."""

import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

from istek_gunlugu import IstekGunluguMiddleware, hata_ayrintisi  # noqa: E402


class Govde(BaseModel):
    sayi: int


def _uygulama():
    app = FastAPI()
    app.add_middleware(IstekGunluguMiddleware)

    @app.get("/tamam")
    def tamam(request: Request):
        request.state.istemci = "musavir-x"
        return {"ok": True}

    @app.get("/hata400")
    def hata400():
        raise HTTPException(status_code=400, detail="Güvensiz dosya yolu: ../x")

    @app.get("/hata500")
    def hata500():
        raise HTTPException(status_code=500, detail="patladi")

    @app.post("/dogrula")
    def dogrula(g: Govde):
        return g

    @app.get("/durum")
    def durum():
        return {"x": 1}

    return app


@pytest.fixture
def istemci():
    return TestClient(_uygulama())


def _kayitlar(caplog):
    return [(r.levelno, json.loads(r.getMessage())) for r in caplog.records if r.name == "entegrasyon.istek"]


def test_basarili_istek_tek_satir_ve_istemci_etiketi(istemci, caplog):
    with caplog.at_level(logging.INFO, logger="entegrasyon.istek"):
        assert istemci.get("/tamam").status_code == 200
    (seviye, k), = _kayitlar(caplog)
    assert seviye == logging.INFO and k["yontem"] == "GET" and k["yol"] == "/tamam" and k["durum"] == 200
    assert k["istemci"] == "musavir-x" and "hata" not in k and isinstance(k["sure_ms"], int)


def test_4xx_hata_mesajiyla_ve_warning_seviyesinde(istemci, caplog):
    with caplog.at_level(logging.INFO, logger="entegrasyon.istek"):
        istemci.get("/hata400")
    (seviye, k), = _kayitlar(caplog)
    assert seviye == logging.WARNING and k["durum"] == 400 and k["hata"] == "Güvensiz dosya yolu: ../x"


def test_5xx_error_seviyesinde(istemci, caplog):
    with caplog.at_level(logging.INFO, logger="entegrasyon.istek"):
        istemci.get("/hata500")
    (seviye, k), = _kayitlar(caplog)
    assert seviye == logging.ERROR and k["durum"] == 500


def test_422_yalniz_alan_ve_mesaj_girdiyi_yansitmaz(istemci, caplog):
    with caplog.at_level(logging.INFO, logger="entegrasyon.istek"):
        istemci.post("/dogrula", json={"sayi": "GIZLI-FATURA-ICERIGI-123"})
    (seviye, k), = _kayitlar(caplog)
    assert k["durum"] == 422 and "sayi" in k["hata"]
    assert "GIZLI-FATURA-ICERIGI-123" not in json.dumps(k) and "GIZLI-FATURA-ICERIGI-123" not in caplog.text


def test_authorization_ve_govde_hic_loglanmaz(istemci, caplog):
    with caplog.at_level(logging.DEBUG):
        istemci.post("/dogrula", json={"sayi": 1}, headers={"Authorization": "Bearer efk_COKGIZLI"})
    assert "efk_COKGIZLI" not in caplog.text


def test_saglik_ve_arayuz_yollari_loglanmaz(istemci, caplog):
    with caplog.at_level(logging.INFO, logger="entegrasyon.istek"):
        istemci.get("/durum")
    assert _kayitlar(caplog) == []


def test_hata_ayrintisi_sinirli_ve_bozuk_govdeye_dayanikli():
    assert hata_ayrintisi(b"bozuk") is None and hata_ayrintisi(b'{"x": 1}') is None
    assert len(hata_ayrintisi(json.dumps({"detail": "a" * 5000}).encode())) == 300
