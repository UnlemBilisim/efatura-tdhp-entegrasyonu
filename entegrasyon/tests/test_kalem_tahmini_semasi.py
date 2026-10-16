"""KalemTahmini (entries[] Pydantic modeli) semasi testleri.

REGRESYON (2026-10-02, canli uctan uca testte bulundu): model_eval/core/
single.py'nin urettigi `onerilen_yeni_kod` alani entries[] icinde vardi ama
web arayuzunde HIC GORUNMUYORDU - kok neden, TdhpTahminiCevabi(**tahmin)
cagrisinin entries listesini KalemTahmini'ye coerce ederken, Pydantic'in
modelde TANIMLI OLMAYAN alanlari SESSIZCE dusurmesiydi (dis_sema ise
Optional[dict] - tipsiz - oldugu icin ayni sorunu yasamiyordu, bu yuzden
curl ile dis_sema.records[] kontrol edilince sorun fark edilmemisti).
Bu testler KalemTahmini'nin model_eval'in urettigi TUM alanlari tasidigini
dogrular - yeni bir alan eklenirse burada da eklenmesi gerektigini hatirlatir."""

import os
import sys
from pathlib import Path

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

os.environ.setdefault(
    "MCP_INTERNAL_API_TOKEN", "internal-test-token-with-at-least-32-chars"
)

import app as integration_app


class TestKalemTahminiOnerilenYeniKod:
    def test_onerilen_yeni_kod_korunur(self):
        """model_eval'dan gelen ham entries sozlugundeki onerilen_yeni_kod
        alani, TdhpTahminiCevabi uzerinden KalemTahmini'ye coerce edildikten
        sonra DUSMEMELI."""
        tahmin = {
            "entries": [
                {
                    "account_code": "320",
                    "dc": "Alacak",
                    "amount": 120.0,
                    "uyari": "Karşı taraf mizanda bulunamadı.",
                    "onerilen_yeni_kod": "320.01.00967",
                }
            ]
        }
        cevap = integration_app.TdhpTahminiCevabi(**tahmin)
        assert cevap.entries[0].onerilen_yeni_kod == "320.01.00967"

    def test_onerilen_yeni_kod_yoksa_none(self):
        tahmin = {
            "entries": [
                {"account_code": "191.01.00020", "dc": "Borc", "amount": 20.0},
            ]
        }
        cevap = integration_app.TdhpTahminiCevabi(**tahmin)
        assert cevap.entries[0].onerilen_yeni_kod is None

    def test_json_cevaba_da_yansir(self):
        """FastAPI'nin gercekte uretecegi JSON serilestirmesinde de alan
        kaybolmamali - model_dump() ile dogrulanir."""
        tahmin = {
            "entries": [
                {
                    "account_code": "730",
                    "dc": "Borc",
                    "amount": 100.0,
                    "onerilen_yeni_kod": "730.01.00041",
                }
            ]
        }
        cevap = integration_app.TdhpTahminiCevabi(**tahmin)
        dump = cevap.model_dump()
        assert dump["entries"][0]["onerilen_yeni_kod"] == "730.01.00041"
