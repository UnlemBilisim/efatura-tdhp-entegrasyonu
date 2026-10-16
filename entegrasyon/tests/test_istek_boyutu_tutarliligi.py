"""FaturaIsleIstegi.fatura_xml'in max_length'i ile SecurityMiddleware'in
MAX_REQUEST_BYTES siniri arasindaki tutarlilik testleri.

REGRESYON (2026-10-02, canli uctan uca testte bulundu): 2026-09-28'de
`fatura_xml` alani `max_length=5_000_000` (karakter) olarak SABIT kodlandi -
o an MAX_REQUEST_BYTES de 10 MB oldugu icin tutarliydi. 2026-10-01'de
MAX_REQUEST_BYTES 30 MB'a cikarilirken (`docker-compose.yml`) bu Pydantic
alani GUNCELLENMEDI - gercek davranis: istek govdesi 30 MB'a kadar kabul
edilirken, 5 MB'i asan bir fatura_xml 413 (govde cok buyuk) yerine 422
(alan cok uzun) ile reddediliyordu - belgelenen 30 MB sinirinin cogu zaman
hic calismadigi anlamina geliyordu. Artik max_length dogrudan security.py'nin
MAX_REQUEST_BYTES'indan turetiliyor - tek kaynak, ikisi birlikte degisir."""

import os
import sys
from pathlib import Path

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

os.environ.setdefault(
    "MCP_INTERNAL_API_TOKEN", "internal-test-token-with-at-least-32-chars"
)

import pytest
from pydantic import ValidationError

import app as integration_app
import security


class TestFaturaXmlMaxLengthTutarliligi:
    def test_max_length_security_ile_ayni(self):
        """Iki sinir birbirinden BAGIMSIZ sayilar olmamali - tek kaynaktan
        gelmeli, aksi halde biri guncellenip digeri unutulabilir (tam da
        bu testin kapattigi regresyon)."""
        field = integration_app.FaturaIsleIstegi.model_fields["fatura_xml"]
        max_length = field.metadata[-1].max_length if field.metadata else None
        assert max_length == security.MAX_REQUEST_BYTES

    def test_security_sinirinin_hemen_altinda_kabul_edilir(self):
        xml = "<Invoice>" + ("A" * 100) + "</Invoice>"
        istek = integration_app.FaturaIsleIstegi(fatura_xml=xml, satici_vkn="0460351893")
        assert istek.fatura_xml == xml

    def test_security_sinirinin_ustunde_reddedilir(self):
        """fatura_xml, MAX_REQUEST_BYTES'i asan bir uzunlukta olursa Pydantic
        alan dogrulamasinda (422) reddedilmeli - once SecurityMiddleware'in
        govde-boyutu kontrolune (413) takilmis olsa bile, iki sinir TUTARLI
        olmali."""
        asiri_uzun = "A" * (security.MAX_REQUEST_BYTES + 1)
        with pytest.raises(ValidationError):
            integration_app.FaturaIsleIstegi(fatura_xml=asiri_uzun, satici_vkn="0460351893")
