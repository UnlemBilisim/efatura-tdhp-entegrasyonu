"""Kayıtlı şirket güncelleme: fark kuralları (saf) + mizan/NACE/RAG güncellemesi ve değişiklik geçmişi (gerçek PostgreSQL)."""

import json
import sys
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import TEST_DATABASE_URL, requires_postgres  # noqa: E402
from core import onboarding_guncelleme as og  # noqa: E402

VKN = "9990000001"


# ---------------- saf fark kuralları ----------------

def test_nace_normalize_ve_fark_nokta_bosluk_onemsiz():
    assert og.nace_normalize(["10.71.01", " 107101 ", "", "47.11.00"]) == ["107101", "471100"]  # tekrarsız, sıralı, noktasız
    assert og.nace_fark(["10.71.01"], ["107101"])["degisti"] is False
    f = og.nace_fark(["10.71.01"], ["10.71.01", "47.11.00"])
    assert f == {"degisti": True, "eklenen": ["471100"], "cikan": []}
    assert og.nace_fark(["10.71.01"], [])["cikan"] == ["107101"]


def test_mizan_fark_eklenen_degisen_silinen():
    f = og.mizan_fark({"120.01.00001": "A", "120.01.00002": "B", "320.01.00001": "C"},
                      {"120.01.00001": "A", "120.01.00002": "B YENİ", "191.01.00001": "KDV"})
    assert f["eklenen"] == {"191.01.00001": "KDV"} and f["degisen"] == {"120.01.00002": ("B", "B YENİ")}
    assert f["silinen"] == {"320.01.00001": "C"}


def _meta(entries, baslik="ACME", yon="inbox"):
    return {"vkn": "1", "account_title": baslik, "direction": yon, "invoice_type": "SATIS",
            "entries_json": json.dumps(entries, ensure_ascii=False)}


def test_rag_fark_sira_bagimsiz_ve_degisimi_yakalar():
    e1 = [{"account_code": "320", "dc": "Alacak", "amount": 10.0}, {"account_code": "770", "dc": "Borc", "amount": 10.0}]
    mevcut = {"A": _meta(e1), "B": _meta(e1)}
    yeni = [("A", "doc", _meta(list(reversed(e1)))),                    # aynı kayıtlar, farklı sıra → AYNI
            ("B", "doc", _meta([{"account_code": "320", "dc": "Alacak", "amount": 99.0}])),  # içerik değişti
            ("C", "doc", _meta(e1))]                                    # yeni
    f = og.rag_fark(mevcut, yeni)
    assert f["ayni"] == ["A"] and [k[0] for k in f["degisen"]] == ["B"] and [k[0] for k in f["yeni"]] == ["C"]


def test_rag_fark_karsi_taraf_unvani_degisimi_de_degisiklik_sayilir():
    e = [{"account_code": "320", "dc": "Alacak", "amount": 1.0}]
    assert og.rag_fark({"A": _meta(e, baslik="ESKİ")}, [("A", "d", _meta(e, baslik="YENİ"))])["degisen"]


# ---------------- gerçek PostgreSQL ----------------

@pytest.fixture
def tenant_cur():
    """Geçici tenant şeması + gerçek tablolar (core.db._SCHEMA); test sonunda şema silinir. Prod DB'ye dokunulmaz."""
    from core import db as core_db

    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    cur.execute(f'DROP SCHEMA IF EXISTS "tenant_{VKN}" CASCADE')
    cur.execute(f'CREATE SCHEMA "tenant_{VKN}"')
    cur.execute(f'SET search_path TO "tenant_{VKN}", public')
    cur.execute(core_db._SCHEMA)
    conn.commit()
    yield conn, cur
    conn.rollback()
    cur.execute(f'DROP SCHEMA IF EXISTS "tenant_{VKN}" CASCADE')
    conn.commit()
    conn.close()


def _gecmis(cur, alan=None):
    cur.execute("SELECT alan, islem, anahtar, eski_deger, yeni_deger, guncelleme_zamani, is_id, istemci FROM onboarding_guncelleme_gecmisi "
                + ("WHERE alan = %s " if alan else "") + "ORDER BY id", (alan,) if alan else ())
    return cur.fetchall()


def _mizan_satirlari(**kw):
    return [(kod, kod.split(".")[0], ad) for kod, ad in kw.items()]


@requires_postgres
def test_mizan_ilk_yukleme_eklenir_ayni_veri_tekrar_gelirse_hicbir_sey_yazilmaz(tenant_cur):
    conn, cur = tenant_cur
    satirlar = _mizan_satirlari(**{"120.01.00001": "Müşteri A", "120.01.00002": "Müşteri B", "191.01.00001": "İndirilecek KDV"})
    o = og.mizan_guncelle(satirlar, cur, VKN, "is1", "musavir")
    conn.commit()
    assert o["uygulandi"] and o["eklenen"] == 3 and o["degisen"] == 0 and o["silinen"] == 0
    assert len(_gecmis(cur, "mizan")) == 3

    o2 = og.mizan_guncelle(satirlar, cur, VKN, "is2", "musavir")
    conn.commit()
    assert o2 == {"eklenen": 0, "degisen": 0, "silinen": 0, "uygulandi": False, "toplam": 3}
    assert len(_gecmis(cur, "mizan")) == 3  # yeni geçmiş satırı YOK


@requires_postgres
def test_mizan_degisen_eklenen_silinen_uygulanir_eski_deger_ve_zaman_loglanir(tenant_cur):
    conn, cur = tenant_cur
    temel = {f"120.01.{i:05d}": f"Müşteri {i}" for i in range(1, 13)}  # 12 hesap (koruma eşiğinin üstünde)
    og.mizan_guncelle(_mizan_satirlari(**temel), cur, VKN, "ilk", "x")
    conn.commit()
    cur.execute("SELECT updated_at FROM mizan_alt_kirilim WHERE hesap_kodu = '120.01.00002'")
    onceki_zaman = cur.fetchone()[0]

    yeni = dict(temel)
    yeni["120.01.00002"] = "Müşteri 2 (YENİ ÜNVAN)"   # değişen
    yeni["320.01.00001"] = "Satıcı X"                  # eklenen
    del yeni["120.01.00012"]                           # silinen (1/12 → eşik altı)
    o = og.mizan_guncelle(_mizan_satirlari(**yeni), cur, VKN, "guncelleme-is", "musavir")
    conn.commit()
    assert (o["eklenen"], o["degisen"], o["silinen"], o["uygulandi"]) == (1, 1, 1, True)

    cur.execute("SELECT hesap_kodu, hesap_adi, updated_at FROM mizan_alt_kirilim")
    durum = {k: (a, z) for k, a, z in cur.fetchall()}
    assert durum["120.01.00002"][0] == "Müşteri 2 (YENİ ÜNVAN)" and durum["120.01.00002"][1] > onceki_zaman  # updated_at yenilendi
    assert "120.01.00012" not in durum and durum["320.01.00001"][0] == "Satıcı X"

    g = {(a, i, k): (e, y, z, isid, ist) for a, i, k, e, y, z, isid, ist in _gecmis(cur, "mizan") if isid == "guncelleme-is"}
    eski, yeni_d, zaman, isid, ist = g[("mizan", "guncellendi", "120.01.00002")]
    assert eski == {"hesap_adi": "Müşteri 2"} and yeni_d == {"hesap_adi": "Müşteri 2 (YENİ ÜNVAN)"} and zaman is not None and ist == "musavir"
    assert g[("mizan", "silindi", "120.01.00012")][:2] == ({"hesap_adi": "Müşteri 12"}, None)   # eski değer geçmişte KALIR
    assert g[("mizan", "eklendi", "320.01.00001")][:2] == (None, {"hesap_adi": "Satıcı X"})


@requires_postgres
def test_mizan_koruma_bos_dosya_ve_toplu_silme_uygulanmaz(tenant_cur):
    conn, cur = tenant_cur
    temel = {f"120.01.{i:05d}": f"M{i}" for i in range(1, 13)}
    og.mizan_guncelle(_mizan_satirlari(**temel), cur, VKN, "ilk", "x")
    conn.commit()
    with pytest.raises(og.GuncellemeHatasi, match="3 seviyeli hesap"):
        og.mizan_guncelle([], cur, VKN, "bos", "x")
    kucuk = _mizan_satirlari(**{"120.01.00001": "M1", "120.01.00002": "M2"})   # 12 hesabın 10'u siliniyor → eşik üstü
    o = og.mizan_guncelle(kucuk, cur, VKN, "eksik", "x")
    conn.commit()
    assert o["uygulandi"] is False and "UYGULANMADI" in o["uyari"]
    cur.execute("SELECT count(*) FROM mizan_alt_kirilim")
    assert cur.fetchone()[0] == 12  # hiçbir şey silinmedi
    assert not [g for g in _gecmis(cur, "mizan") if g[6] in ("bos", "eksik")]


@requires_postgres
def test_nace_ayni_ise_dokunulmaz_degisirse_eski_deger_loglanir_ve_kaydet_hatasinda_iz_kalmaz(tenant_cur):
    conn, cur = tenant_cur
    og.gecmisi_hazirla(cur)  # fark yoksa modül tabloyu hiç açmaz; test sorgusu için hazır olsun
    kayit = {"nace": ["10.71.01"]}
    kaydedilen = []
    getir = lambda v: kayit["nace"]  # noqa: E731
    kaydet = lambda v, k: (kaydedilen.append(k), kayit.update(nace=k))  # noqa: E731

    assert og.nace_guncelle(VKN, ["107101"], cur, "i1", "m", getir, kaydet) == {"degisti": False}   # nokta farkı fark değil
    assert kaydedilen == [] and _gecmis(cur, "nace") == []

    o = og.nace_guncelle(VKN, ["10.71.01", "47.11.00"], cur, "i2", "m", getir, kaydet)
    conn.commit()
    assert o["degisti"] and o["eklenen"] == ["471100"] and kaydedilen == [["10.71.01", "47.11.00"]]
    ((alan, islem, anahtar, eski, yeni, zaman, isid, ist),) = _gecmis(cur, "nace")
    assert eski == {"nace_kodlari": ["10.71.01"]} and yeni == {"nace_kodlari": ["10.71.01", "47.11.00"]} and zaman is not None

    def patlayan(v, k):
        raise RuntimeError("kaydedilemedi")

    with pytest.raises(RuntimeError):
        og.nace_guncelle(VKN, ["99.99.99"], cur, "i3", "m", getir, patlayan)
    conn.rollback()  # çağıranın yaptığı: geçmiş satırı da geri alınır → yarım iz kalmaz
    cur.execute(f'SET search_path TO "tenant_{VKN}", public')
    assert len(_gecmis(cur, "nace")) == 1


class SahteKoleksiyon:
    def __init__(self, mevcut=None):
        self.kayit = dict(mevcut or {})
        self.upsert_cagrilari = []

    def get(self, ids, include=None):
        bulunan = [i for i in ids if i in self.kayit]
        return {"ids": bulunan, "metadatas": [self.kayit[i] for i in bulunan]}

    def upsert(self, ids, documents, metadatas):
        self.upsert_cagrilari.append(list(ids))
        for i, d, m in zip(ids, documents, metadatas):
            self.kayit[i] = m


@requires_postgres
def test_rag_yalniz_yeni_ve_degisen_yazilir_embedding_icin_ayni_olana_dokunulmaz(tenant_cur):
    conn, cur = tenant_cur
    e = [{"account_code": "320", "dc": "Alacak", "amount": 10.0}]
    e2 = [{"account_code": "320", "dc": "Alacak", "amount": 25.0}]
    kol = SahteKoleksiyon({"A": _meta(e), "B": _meta(e), "ONAYLI-FATURA": _meta(e)})   # sonuncusu dosyada yok (/fatura/onayla ile gelmiş)
    kayitlar = [("A", "d", _meta(e)), ("B", "d", _meta(e2)), ("C", "d", _meta(e))]
    o = og.rag_guncelle(kayitlar, kol, cur, VKN, "is-r", "musavir")
    conn.commit()
    assert o == {"yeni": 1, "degisen": 1, "ayni": 1, "taranan": 3}
    assert [sorted(c) for c in kol.upsert_cagrilari] == [["B", "C"]]   # yalnızca yeni+değişen yazıldı, A'ya dokunulmadı
    assert "ONAYLI-FATURA" in kol.kayit                      # dosyada olmayan emsal ASLA silinmez
    g = {k: (i, eski, yeni) for _a, i, k, eski, yeni, *_ in _gecmis(cur, "rag")}
    assert g["C"][0] == "eklendi" and g["C"][1] is None
    assert g["B"][0] == "guncellendi" and json.loads(g["B"][1]["entries_json"])[0]["amount"] == 10.0 and json.loads(g["B"][2]["entries_json"])[0]["amount"] == 25.0

    o2 = og.rag_guncelle(kayitlar, kol, cur, VKN, "is-r2", "musavir")   # aynı veri tekrar → hiçbir şey
    conn.commit()
    assert o2["yeni"] == 0 and o2["degisen"] == 0 and len(kol.upsert_cagrilari) == 1 and len(_gecmis(cur, "rag")) == 2
