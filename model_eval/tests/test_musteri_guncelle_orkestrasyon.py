"""`scripts/musteri_onboard_toplu.py::musteriyi_guncelle` — gerçek mock şirket verisiyle uçtan uca (gerçek PostgreSQL; ChromaDB sahte,
Ollama/embedding gerekmez). Kayıtlı şirketin güncellenmesi: ilk gelen veri eklenir, aynısı tekrar gelirse HİÇBİR ŞEY yazılmaz,
değişen parça (mizan adı / yevmiye tutarı / NACE) yalnızca fark olarak uygulanır ve eski değer geçmişte kalır."""

import importlib.util
import shutil
import sys
from pathlib import Path

import openpyxl
import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rag_common  # noqa: E402
from conftest import TEST_DATABASE_URL, requires_postgres  # noqa: E402
from test_onboarding_guncelleme import SahteKoleksiyon  # noqa: E402

KOK = Path(__file__).resolve().parents[2]
MOCK = KOK / "onboarding_test" / "6677889900"
MOCK_VKN, VKN = "6677889900", "9990000002"


def _betik():
    spec = importlib.util.spec_from_file_location("musteri_onboard_toplu_test", KOK / "scripts" / "musteri_onboard_toplu.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def ortam(tmp_path, monkeypatch):
    from core import db as core_db

    musteri = tmp_path / VKN
    shutil.copytree(MOCK, musteri)
    for xml in (musteri / "faturalar").glob("*.xml"):  # mock şirketin VKN'sini test şirketine çevir (gerçek şirketlere dokunma)
        xml.write_text(xml.read_text(encoding="utf-8").replace(MOCK_VKN, VKN), encoding="utf-8")

    kol = SahteKoleksiyon()
    monkeypatch.setattr(rag_common, "get_collection", lambda **k: kol)

    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    cur.execute(f'DROP SCHEMA IF EXISTS "tenant_{VKN}" CASCADE')
    cur.execute(f'CREATE SCHEMA "tenant_{VKN}"')
    cur.execute(f'SET search_path TO "tenant_{VKN}", public')
    cur.execute(core_db._SCHEMA)
    cur.execute("CREATE TABLE IF NOT EXISTS public.sirket_bilgileri (vkn TEXT PRIMARY KEY, nace_kodlari TEXT[] NOT NULL DEFAULT '{}', guncellenme_zamani TIMESTAMPTZ NOT NULL DEFAULT now())")
    cur.execute("DELETE FROM public.sirket_bilgileri WHERE vkn = %s", (VKN,))
    conn.commit()
    yield musteri, kol, conn, cur
    conn.rollback()
    cur.execute(f'DROP SCHEMA IF EXISTS "tenant_{VKN}" CASCADE')
    cur.execute("DELETE FROM public.sirket_bilgileri WHERE vkn = %s", (VKN,))
    conn.commit()
    conn.close()


def _gecmis_sayisi(cur):
    cur.execute(f'SET search_path TO "tenant_{VKN}", public')
    cur.execute("SELECT alan, count(*) FROM onboarding_guncelleme_gecmisi GROUP BY alan")
    return dict(cur.fetchall())


def _guncelle(betik, musteri, ilerleme=None):
    return betik.musteriyi_guncelle(VKN, musteri, TEST_DATABASE_URL, ilerleme=ilerleme, is_id="is-x", istemci="musavir")


@requires_postgres
def test_ilk_veri_eklenir_ayni_veri_tekrar_gelince_fark_yok_degisen_parca_guncellenir(ortam):
    musteri, kol, conn, cur = ortam
    betik = _betik()
    adimlar = []

    o1 = _guncelle(betik, musteri, ilerleme=lambda a, y: adimlar.append((a, y)))
    assert adimlar == [("nace", 25), ("mizan", 50), ("eslestirme", 75), ("rag", 100)]
    assert o1["degisiklik_var"] and o1["mizan"]["eklenen"] == 21 and o1["mizan"]["uygulandi"]
    assert o1["nace"]["degisti"] and o1["rag"]["yeni"] == 2 and o1["rag"]["fatura_eslesme"] == "2/2"
    ilk = _gecmis_sayisi(cur)
    assert ilk == {"nace": 1, "mizan": 21, "rag": 2}

    # --- AYNI veri tekrar: hiçbir şey yazılmaz
    cagri_sayisi = len(kol.upsert_cagrilari)
    o2 = _guncelle(betik, musteri)
    assert o2["degisiklik_var"] is False
    assert o2["mizan"]["uygulandi"] is False and o2["rag"]["yeni"] == 0 and o2["rag"]["degisen"] == 0 and o2["rag"]["ayni"] == 2
    assert not o2["nace"]["degisti"] and len(kol.upsert_cagrilari) == cagri_sayisi
    assert _gecmis_sayisi(cur) == ilk  # yeni geçmiş satırı YOK

    # --- mizan'da bir hesap adı değişir, yevmiyede bir kayıt kodu değişir, NACE'ye bir kod eklenir
    from mizan_excel_yukle import _baslik_satirini_bul

    mz = musteri / "mizan.xlsx"
    wb = openpyxl.load_workbook(mz)
    ws = wb[wb.sheetnames[0]]
    bas, kod_i, ad_i = _baslik_satirini_bul(ws)
    degisen_kod = None
    for satir in ws.iter_rows(min_row=bas + 1):
        k = satir[kod_i].value
        if isinstance(k, str) and len(k.split(".")) == 3:
            degisen_kod, eski_ad = k, satir[ad_i].value
            satir[ad_i].value = eski_ad + " (YENİ ÜNVAN)"
            break
    wb.save(mz)

    yv = musteri / "yevmiye.xlsx"
    wb = openpyxl.load_workbook(yv)
    ws = wb[wb.sheetnames[0]]
    basliklar = [str(c.value).strip().lower() for c in ws[1]]
    kod_i = basliklar.index("hesap_kodu")
    # RAG emsali yalnızca (3 haneli kod, yön, ad) tutar — TUTAR değişikliği emsali değiştirmez; bu yüzden hesap kodunu değiştiriyoruz.
    ws.cell(row=2, column=kod_i + 1).value = "999.01.00001"
    wb.save(yv)

    with open(musteri / "nace.txt", "a", encoding="utf-8") as f:
        f.write("\n47.11.00\n")

    o3 = _guncelle(betik, musteri)
    assert o3["degisiklik_var"]
    assert (o3["mizan"]["eklenen"], o3["mizan"]["degisen"], o3["mizan"]["silinen"]) == (0, 1, 0)
    assert o3["rag"]["degisen"] == 1 and o3["rag"]["yeni"] == 0 and o3["rag"]["ayni"] == 1
    assert o3["nace"]["degisti"] and o3["nace"]["eklenen"] == ["471100"]

    # --- veritabanı: yeni ad uygulandı, ESKİ DEĞER + ZAMAN geçmişte
    cur.execute(f'SET search_path TO "tenant_{VKN}", public')
    cur.execute("SELECT hesap_adi FROM mizan_alt_kirilim WHERE hesap_kodu = %s", (degisen_kod,))
    assert cur.fetchone()[0] == eski_ad + " (YENİ ÜNVAN)"
    cur.execute("SELECT eski_deger, yeni_deger, guncelleme_zamani, is_id, istemci FROM onboarding_guncelleme_gecmisi "
                "WHERE alan = 'mizan' AND islem = 'guncellendi'")
    ((eski, yeni, zaman, is_id, istemci),) = cur.fetchall()
    assert eski == {"hesap_adi": eski_ad} and yeni == {"hesap_adi": eski_ad + " (YENİ ÜNVAN)"}
    assert zaman is not None and is_id == "is-x" and istemci == "musavir"
    cur.execute("SELECT count(*) FROM onboarding_guncelleme_gecmisi WHERE alan = 'rag' AND islem = 'guncellendi'")
    assert cur.fetchone()[0] == 1


@requires_postgres
def test_kismi_guncelleme_yalniz_mizan_gelirse_diger_parcalara_dokunulmaz(ortam):
    musteri, kol, conn, cur = ortam
    betik = _betik()
    _guncelle(betik, musteri)  # önce tam veri
    kismi = musteri.parent / "kismi" / VKN
    kismi.mkdir(parents=True)
    shutil.copy(musteri / "mizan.xlsx", kismi / "mizan.xlsx")
    onceki = len(kol.upsert_cagrilari)
    o = betik.musteriyi_guncelle(VKN, kismi, TEST_DATABASE_URL, is_id="k", istemci="m")
    assert o["degisiklik_var"] is False and "rag" not in o and "nace" not in o
    assert len(kol.upsert_cagrilari) == onceki


@requires_postgres
def test_gecersiz_girdiler_acik_hata_verir(ortam, tmp_path):
    musteri, kol, conn, cur = ortam
    betik = _betik()
    bos = tmp_path / "bos" / VKN
    bos.mkdir(parents=True)
    with pytest.raises(betik.OnboardHatasi, match="güncellenecek dosya yok"):
        betik.musteriyi_guncelle(VKN, bos, TEST_DATABASE_URL)
    yalniz_fatura = tmp_path / "yf" / VKN
    shutil.copytree(musteri / "faturalar", yalniz_fatura / "faturalar")
    with pytest.raises(betik.OnboardHatasi, match="BİRLİKTE"):
        betik.musteriyi_guncelle(VKN, yalniz_fatura, TEST_DATABASE_URL)
