"""Mcp_mimarisi HTTP API'si — auth, girdi güvenliği ve uçtan uca karar.

Lifespan (PostgreSQL'den NaceOranTablosu yükleme) çalıştırılmaz: TestClient
`with` bloğu olmadan kullanılır ve `_state` sahte tabloyla doldurulur."""

import pytest
from fastapi.testclient import TestClient

from efatura_kdv import api, security

TOKEN = "internal-test-token-with-at-least-32-chars"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SATICI_VKN = "1111111111"


def _ubl(satici_vkn=SATICI_VKN, oran="20", doctype=False):
    bas = '<?xml version="1.0" encoding="UTF-8"?>'
    if doctype:
        bas += '<!DOCTYPE Invoice [<!ENTITY x "y">]>'
    return f"""{bas}
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>TEST-001</cbc:ID>
  <cbc:UUID>test-uuid</cbc:UUID>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">{satici_vkn}</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">2222222222</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cac:TaxTotal><cac:TaxSubtotal>
      <cbc:Percent>{oran}</cbc:Percent>
      <cac:TaxCategory><cac:TaxScheme><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal></cac:TaxTotal>
    <cac:Item><cbc:Name>Kargo hizmeti</cbc:Name></cac:Item>
  </cac:InvoiceLine>
</Invoice>"""


def _istek(**xml_args):
    return {
        "fatura_xml": _ubl(**xml_args),
        "satici_vkn": SATICI_VKN,
        "satici_nace_kodlari": ["532009"],
    }


@pytest.fixture
def client(monkeypatch, oran_tablosu):
    monkeypatch.setenv("MCP_INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setitem(api._state, "oran_tablosu", oran_tablosu)
    return TestClient(api.app)


def test_saglik_tokensiz_erisilebilir(client):
    response = client.get("/saglik")
    assert response.status_code == 200
    assert response.json()["nace_tablosu_yuklu"] is True


def test_tokensiz_istek_reddedilir(client):
    response = client.post("/fatura/kontrol-et", json=_istek())
    assert response.status_code == 401


def test_yanlis_token_reddedilir(client):
    response = client.post(
        "/fatura/kontrol-et", json=_istek(), headers={"Authorization": "Bearer yanlis"}
    )
    assert response.status_code == 401


def test_token_yapilandirilmamissa_servis_kapali_kalir(client, monkeypatch):
    monkeypatch.delenv("MCP_INTERNAL_API_TOKEN")
    response = client.post("/fatura/kontrol-et", json=_istek(), headers=AUTH)
    assert response.status_code == 503


@pytest.mark.parametrize("yol", ["/fatura/gecmis-kontrol", "/fatura/coklu-kontrol"])
def test_diger_is_uclari_de_token_ister(client, yol):
    response = client.post(yol, json={})
    assert response.status_code == 401


def test_gecerli_fatura_uygun_doner(client):
    response = client.post("/fatura/kontrol-et", json=_istek(), headers=AUTH)
    assert response.status_code == 200
    govde = response.json()
    assert govde["genel_karar"] == "uygun"
    assert govde["satir_sonuclari"][0]["beyan_edilen_oranlar"] == [20.0]


def test_havuz_disi_oran_insan_incelemesine_duser(client):
    response = client.post("/fatura/kontrol-et", json=_istek(oran="1"), headers=AUTH)
    assert response.status_code == 200
    assert response.json()["genel_karar"] == "insan_incelemesi_gerekli"


def test_dtd_iceren_xml_reddedilir(client):
    response = client.post("/fatura/kontrol-et", json=_istek(doctype=True), headers=AUTH)
    assert response.status_code == 400
    assert "DTD" in response.json()["detail"]


def test_satici_vkn_uyusmazligi_400_doner(client):
    response = client.post(
        "/fatura/kontrol-et", json=_istek(satici_vkn="9999999999"), headers=AUTH
    )
    assert response.status_code == 400


def test_istek_boyutu_siniri_uygulanir(client, monkeypatch):
    monkeypatch.setattr(security, "MAX_REQUEST_BYTES", 64)
    response = client.post("/fatura/kontrol-et", json=_istek(), headers=AUTH)
    assert response.status_code == 413


def test_request_id_cevaba_tasinir(client):
    response = client.post(
        "/fatura/kontrol-et", json=_istek(), headers={**AUTH, "X-Request-ID": "abc123"}
    )
    assert response.headers["x-request-id"] == "abc123"
