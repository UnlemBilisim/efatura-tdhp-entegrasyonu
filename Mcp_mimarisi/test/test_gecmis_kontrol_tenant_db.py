"""Onboard edilmemiş bir VKN'nin `_tenant_baglantisi` üzerinden sessizce
`public`'e (başka şirketin verisine) düşmemesi — gerçek PostgreSQL ile.

entegrasyon/model_eval tarafı aynı açığı 2026-09-28'de `core.db.
tenant_kayitli_mi` ile kapatmıştı (bkz. model_eval/tests/
test_tenant_izolasyonu.py); bu dosya aynı kontrolün Mcp_mimarisi tarafına
(2026-10-01, TODO.md) da taşındığını doğrular — ikisi de aynı tek kaynağı
(core.db.tenant_kayitli_mi) kullandığı için desen birebir aynı.

TEST_DATABASE_URL'e bağlanılamazsa atlanır (CI'da çalışır, entegrasyon/
model_eval testleriyle aynı desen)."""

import os
import sys
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from efatura_kdv.gecmis_kontrol import GecmisFaturaDeposu, TenantKayitliDegilHatasi  # noqa: E402

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://efatura:efatura@localhost:5434/model_eval_test"
)

KAYITLI_VKN = "1111111111"
KAYITSIZ_VKN = "2222222222"


def _postgres_var_mi():
    try:
        psycopg2.connect(TEST_DATABASE_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _postgres_var_mi(), reason="TEST_DATABASE_URL'e bağlanılamıyor")


@pytest.fixture
def depo():
    from core import db as model_eval_db

    model_eval_db.reset_pool_for_tests()
    depo = GecmisFaturaDeposu(database_url=TEST_DATABASE_URL)
    conn = depo._pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(f"tenant_{KAYITLI_VKN}"))
            )
            cur.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(f"tenant_{KAYITSIZ_VKN}"))
            )
        conn.commit()
    finally:
        depo._pool.putconn(conn)

    yield depo

    depo.kapat()
    model_eval_db.reset_pool_for_tests()


def test_semasi_olan_vkn_baglanabilir(depo):
    with depo._tenant_baglantisi(KAYITLI_VKN) as conn:
        assert conn is not None


def test_kayitsiz_vkn_sessizce_public_e_dusmez(depo):
    with pytest.raises(TenantKayitliDegilHatasi):
        with depo._tenant_baglantisi(KAYITSIZ_VKN):
            pass


def test_default_own_vkn_her_zaman_kayitli(depo):
    from core.constants import DEFAULT_OWN_VKN

    with depo._tenant_baglantisi(DEFAULT_OWN_VKN) as conn:
        assert conn is not None


def test_gecmis_oranlari_getir_kayitsiz_vknde_hata_firlatir(depo):
    """Üst seviye sorgu fonksiyonu da aynı korumadan geçer — regresyon:
    önceden bu çağrı sessizce `public.gecmis_fatura_kalemleri`'ni (varsa)
    okur, boş/yanlış sonuç dönerdi."""
    with pytest.raises(TenantKayitliDegilHatasi):
        depo.gecmis_oranlari_getir(KAYITSIZ_VKN, "herhangi bir kalem")
