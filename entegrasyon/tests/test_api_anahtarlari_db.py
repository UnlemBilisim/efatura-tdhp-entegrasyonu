"""API anahtar deposu ve onayda şirket filtresi — gerçek PostgreSQL ile.

TEST_DATABASE_URL'e bağlanılamazsa atlanır (CI'da çalışır)."""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

import api_anahtarlari  # noqa: E402
import model_eval_koprusu  # noqa: E402
from api_anahtarlari import IstemciKimligi  # noqa: E402

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://efatura:efatura@localhost:5434/model_eval_test"
)


def _postgres_var_mi():
    try:
        import psycopg2

        psycopg2.connect(TEST_DATABASE_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _postgres_var_mi(), reason="TEST_DATABASE_URL'e bağlanılamıyor")

SIRKET_A = "1111111111"
SIRKET_B = "2222222222"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    model_eval_koprusu.model_eval_yolunu_ekle()
    from core import db as core_db

    core_db.reset_pool_for_tests()
    monkeypatch.setattr(api_anahtarlari, "_tablo_hazir", False)
    api_anahtarlari.tabloyu_hazirla()
    with core_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE public.api_anahtarlari")
            cur.execute("TRUNCATE public.model_eval_bekleyen_tahminler")
        conn.commit()
    yield core_db
    core_db.reset_pool_for_tests()


def test_anahtar_olustur_dogrula_iptal(db):
    anahtar = api_anahtarlari.anahtar_olustur("dis-ekip", [SIRKET_A])
    kimlik = api_anahtarlari.anahtari_dogrula(anahtar)
    assert kimlik == IstemciKimligi("dis-ekip", False, frozenset({SIRKET_A}))
    assert kimlik.vkn_izinli_mi(SIRKET_A) and not kimlik.vkn_izinli_mi(SIRKET_B)

    assert api_anahtarlari.anahtari_iptal_et("dis-ekip") is True
    assert api_anahtarlari.anahtari_dogrula(anahtar) is None


def test_anahtarin_duz_metni_saklanmaz(db):
    anahtar = api_anahtarlari.anahtar_olustur("demo", [], tum_sirketler=True)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT anahtar_hash FROM public.api_anahtarlari")
            (saklanan,) = cur.fetchone()
    assert saklanan != anahtar
    assert saklanan == api_anahtarlari.anahtar_ozeti(anahtar)


def test_bilinmeyen_anahtar_reddedilir(db):
    assert api_anahtarlari.anahtari_dogrula("efk_uydurma") is None


def test_kapsamsiz_anahtar_olusturulamaz(db):
    with pytest.raises(ValueError):
        api_anahtarlari.anahtar_olustur("bos", [])


def test_vkn_ekle_kapsami_genisletir_anahtar_degismez(db):
    anahtar = api_anahtarlari.anahtar_olustur("musavir-x", [SIRKET_A])
    assert api_anahtarlari.anahtar_vkn_ekle("musavir-x", SIRKET_B) is True

    kimlik = api_anahtarlari.anahtari_dogrula(anahtar)
    assert kimlik == IstemciKimligi("musavir-x", False, frozenset({SIRKET_A, SIRKET_B}))


def test_vkn_ekle_mukerrer_eklemez(db):
    api_anahtarlari.anahtar_olustur("musavir-y", [SIRKET_A])
    assert api_anahtarlari.anahtar_vkn_ekle("musavir-y", SIRKET_A) is True

    kayit = [a for a in api_anahtarlari.anahtarlari_listele() if a["etiket"] == "musavir-y"][0]
    assert kayit["izinli_vknler"] == [SIRKET_A]


def test_vkn_ekle_aktif_olmayan_anahtara_basarisiz(db):
    assert api_anahtarlari.anahtar_vkn_ekle("yok-boyle-bir-etiket", SIRKET_A) is False

    api_anahtarlari.anahtar_olustur("iptal-edilecek", [SIRKET_A])
    api_anahtarlari.anahtari_iptal_et("iptal-edilecek")
    assert api_anahtarlari.anahtar_vkn_ekle("iptal-edilecek", SIRKET_B) is False


def test_vkn_ekle_gecersiz_vkn_reddedilir(db):
    api_anahtarlari.anahtar_olustur("musavir-z", [SIRKET_A])
    with pytest.raises(ValueError):
        api_anahtarlari.anahtar_vkn_ekle("musavir-z", "kisa")


def _bekleyen_tahmin_ekle(db, tenant_vkn):
    prediction_id = str(uuid.uuid4())
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO model_eval_bekleyen_tahminler
                   (prediction_id, tenant_vkn, invoice_id, invoice_hash, invoice_xml,
                    prediction, approvable, expires_at)
                   VALUES (%s, %s, 'INV-1', 'hash', '<Invoice/>', %s, TRUE, %s)""",
                (prediction_id, tenant_vkn, json.dumps({"entries": []}),
                 datetime.now(timezone.utc) + timedelta(minutes=30)),
            )
        conn.commit()
    return prediction_id


def test_baska_sirketin_tahmini_bulunamadi_sayilir(db, monkeypatch):
    monkeypatch.setattr(model_eval_koprusu, "faturayi_onayla", lambda *a, **k: None)
    prediction_id = _bekleyen_tahmin_ekle(db, SIRKET_A)
    sirket_b_istemcisi = IstemciKimligi("b", False, frozenset({SIRKET_B}))

    with pytest.raises(model_eval_koprusu.BekleyenTahminHatasi) as hata:
        model_eval_koprusu.bekleyen_tahmini_onayla(prediction_id, sirket_b_istemcisi)
    assert hata.value.status_code == 404

    sirket_a_istemcisi = IstemciKimligi("a", False, frozenset({SIRKET_A}))
    assert model_eval_koprusu.bekleyen_tahmini_onayla(prediction_id, sirket_a_istemcisi) == "INV-1"
