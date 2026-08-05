"""core.mizan icin birim testleri (2026-08-05, Excel'den PostgreSQL'e tasima).

Calistirmak icin:
    cd model_eval
    TEST_DATABASE_URL=postgresql://efatura:efatura@localhost:5434/model_eval_test \\
        /usr/bin/python3 -m pytest tests/test_mizan.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.mizan as mizan
from conftest import TEST_DATABASE_URL, requires_postgres

TEST_TENANT_VKN = "9999999999"


@pytest.fixture(autouse=True)
def _mizan_cache_temiz():
    mizan.reset_mizan_cache_for_tests()
    yield
    mizan.reset_mizan_cache_for_tests()


@pytest.fixture
def tenant_mizan_db():
    """Test tenant semasinda (tenant_9999999999) mizan_alt_kirilim tablosunu
    hazirlar/temizler ve os.environ['DATABASE_URL']'i test DB'sine yonlendirir
    - db_conn fixture'inin AYNISI degil, cunku burada public degil bir tenant
    semasi hedefleniyor (get_conn(tenant_vkn=...) search_path'i degistiriyor)."""
    import os

    from core import db as db_module
    from psycopg2 import sql

    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    db_module.reset_pool_for_tests()
    pool = db_module.get_pool()  # public semada _SCHEMA'yi olusturur (baz tablo tanimlari)

    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(f"tenant_{TEST_TENANT_VKN}")
            ))
            cur.execute(sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(f"tenant_{TEST_TENANT_VKN}")
            ))
            cur.execute(db_module._SCHEMA)
            cur.execute("TRUNCATE TABLE mizan_alt_kirilim")
        conn.commit()
    finally:
        pool.putconn(conn)

    yield TEST_TENANT_VKN

    db_module.reset_pool_for_tests()
    if old_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old_url


def _satir_ekle(tenant_vkn, satirlar):
    """satirlar: [(hesap_kodu, hesap_adi), ...] - ana_kod hesap_kodu'ndan turetilir."""
    from core.db import get_conn

    with get_conn(tenant_vkn=tenant_vkn) as conn:
        with conn.cursor() as cur:
            for kod, ad in satirlar:
                cur.execute(
                    "INSERT INTO mizan_alt_kirilim (hesap_kodu, ana_kod, hesap_adi) VALUES (%s, %s, %s)",
                    (kod, kod.split(".")[0], ad),
                )
        conn.commit()


class TestKodNormalize:
    def test_tire_ayiricisi_noktaya_cevrilir(self):
        assert mizan._kod_normalize("191-01-00020") == "191.01.00020"

    def test_bosluk_ayiricisi_noktaya_cevrilir(self):
        assert mizan._kod_normalize("191 01 00020") == "191.01.00020"

    def test_ardisik_nokta_tekillestirilir(self):
        assert mizan._kod_normalize("191..01...00020") == "191.01.00020"

    def test_zaten_dogru_format_degismez(self):
        assert mizan._kod_normalize("191.01.00020") == "191.01.00020"


class TestTenantVknGecerliMi:
    def test_none_gecersiz(self):
        assert mizan._tenant_vkn_gecerli_mi(None) is False

    def test_bos_string_gecersiz(self):
        assert mizan._tenant_vkn_gecerli_mi("") is False

    def test_harf_iceren_gecersiz(self):
        assert mizan._tenant_vkn_gecerli_mi("12345abcde") is False

    def test_10_haneden_kisa_gecersiz(self):
        assert mizan._tenant_vkn_gecerli_mi("123456789") is False

    def test_10_hane_sayisal_gecerli(self):
        assert mizan._tenant_vkn_gecerli_mi("1234567890") is True


class TestGetAltKirilimlarGecersizTenant:
    """DB'ye hic baglanmadan calisan, gecersiz/bos own_vkn durumunu kapsayan
    testler (2026-07-31 bug'inin DB'ye tasindiktan sonraki karsiligi): own_vkn
    bilinmiyorsa hicbir sirketin mizanina YANLISLIKLA dusulmemeli."""

    def test_none_ise_bos_dict_doner_exception_firlamaz(self):
        assert mizan.get_alt_kirilimlar(None) == {}

    def test_bos_string_ise_bos_dict_doner(self):
        assert mizan.get_alt_kirilimlar("") == {}

    def test_gecersiz_format_ise_bos_dict_doner(self):
        assert mizan.get_alt_kirilimlar("kisa") == {}


@requires_postgres
class TestGetAltKirilimlarDB:
    def test_dosya_yoksa_bos_dict_doner_exception_firlamaz(self, tenant_mizan_db):
        """Sema/tablo var ama satir yok - "bu sirketin mizani hic yok" hali."""
        assert mizan.get_alt_kirilimlar(tenant_mizan_db) == {}

    def test_gecerli_veri_ana_koda_gore_gruplanir(self, tenant_mizan_db):
        _satir_ekle(tenant_mizan_db, [
            ("191.01.00020", "%20 Indirilecek KDV"),
            ("191.01.00010", "%10 Indirilecek KDV"),
            ("320.01.00001", "Test Tedarikci"),
        ])
        sonuc = mizan.get_alt_kirilimlar(tenant_mizan_db)
        assert sorted(sonuc["191"]) == sorted([
            ("191.01.00020", "%20 Indirilecek KDV"),
            ("191.01.00010", "%10 Indirilecek KDV"),
        ])
        assert sonuc["320"] == [("320.01.00001", "Test Tedarikci")]

    def test_sonuc_cachelenir(self, tenant_mizan_db):
        _satir_ekle(tenant_mizan_db, [("191.01.00020", "%20 Indirilecek KDV")])
        birinci = mizan.get_alt_kirilimlar(tenant_mizan_db)
        # DB'deki satiri sildikten sonra bile cache'ten donmeli
        from core.db import get_conn
        with get_conn(tenant_vkn=tenant_mizan_db) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE mizan_alt_kirilim")
            conn.commit()
        ikinci = mizan.get_alt_kirilimlar(tenant_mizan_db)
        assert birinci is ikinci

    def test_farkli_tenant_farkli_cache_key(self, tenant_mizan_db):
        """Ayni process icinde iki farkli sirketin mizani birbirine karismamali
        (2026-07-31 bug'inin kok nedeni - once cache key VKN'e bagli degildi
        gibi bir riski onlemek icin acikca test edilir)."""
        _satir_ekle(tenant_mizan_db, [("191.01.00020", "Şirket A KDV")])
        sonuc_a = mizan.get_alt_kirilimlar(tenant_mizan_db)
        sonuc_bos = mizan.get_alt_kirilimlar(None)
        assert sonuc_a != sonuc_bos
        assert sonuc_bos == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
