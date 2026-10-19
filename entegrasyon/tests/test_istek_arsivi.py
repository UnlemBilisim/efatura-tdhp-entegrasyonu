"""Gelen-istek arşivi — saklama, temizlik, hata dayanıklılığı ve zip/tek-fatura uç noktalarına bağlantısı.

LLM/veritabanı GEREKMEZ (uç nokta testleri sahte iç fonksiyonlarla çalışır)."""

import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

import istek_arsivi as ia  # noqa: E402
import toplu_fatura_api as tf  # noqa: E402
from api_anahtarlari import IstemciKimligi  # noqa: E402

RID = "0123456789ab"
VKN_A = "1111111111"


def _zip_dosyasi(yol: Path, girdiler: dict) -> Path:
    with zipfile.ZipFile(yol, "w") as zf:
        for ad, icerik in girdiler.items():
            zf.writestr(ad, icerik)
    return yol


def _meta(rid=RID):
    return json.loads((ia.kok() / rid / "meta.json").read_text(encoding="utf-8"))


# ---------------- birim ----------------

def test_zip_kaydet_kopyalar_ve_icerik_listesini_meta_ya_yazar(tmp_path):
    z = _zip_dosyasi(tmp_path / "a.zip", {f"{VKN_A}/mizan.xlsx": b"x" * 10, f"{VKN_A}/faturalar/1.xml": b"<a/>"})
    ia.zip_kaydet(RID, z, "musteri_onboard", "orhan", "10.0.0.5", "/musteri/onboard")
    d = ia.kok() / RID
    assert (d / "gelen.zip").read_bytes() == z.read_bytes()
    m = _meta()
    assert m["tip"] == "musteri_onboard" and m["istemci"] == "orhan" and m["ip"] == "10.0.0.5" and m["request_id"] == RID
    assert m["dosyalar"] == {"gelen.zip": z.stat().st_size} and m["zip_dosya_sayisi"] == 2
    assert {i["ad"]: i["bayt"] for i in m["zip_icerik"]} == {f"{VKN_A}/mizan.xlsx": 10, f"{VKN_A}/faturalar/1.xml": 4}


def test_gecersiz_zip_de_saklanir_icerik_listesi_olmadan(tmp_path):
    bozuk = tmp_path / "b.zip"
    bozuk.write_bytes(b"zip degil")
    ia.zip_kaydet(RID, bozuk, "fatura_toplu", "orhan", None, "/fatura/toplu-isle")
    assert (ia.kok() / RID / "gelen.zip").read_bytes() == b"zip degil"
    assert "zip_icerik" not in _meta()


def test_zip_icerik_listesi_sinirlidir(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "ZIP_ICERIK_MAX", 3)
    z = _zip_dosyasi(tmp_path / "c.zip", {f"{i}.xml": b"x" for i in range(10)})
    ia.zip_kaydet(RID, z, "fatura_toplu", "orhan", None, "/x")
    m = _meta()
    assert m["zip_dosya_sayisi"] == 10 and len(m["zip_icerik"]) == 3


@pytest.mark.parametrize("kotu", ["-", "", "../etc", "ABCDEF123456", "0123456789a", "x" * 33, "0123456789ab/../x"])
def test_gecersiz_request_id_arsivlenmez_ve_yol_gezinmesi_olmaz(tmp_path, kotu):
    z = _zip_dosyasi(tmp_path / "a.zip", {"a": b"x"})
    ia.zip_kaydet(kotu, z, "musteri_onboard", "o", None, "/x")
    ia.fatura_kaydet(kotu, "<a/>", {"asama": "x"}, None, "o", None, VKN_A, "a.xml")
    ia.cevap_yaz(kotu, {"a": 1})
    assert not ia.kok().exists() or not list(ia.kok().iterdir())


def test_ayni_request_id_ile_gelen_ikinci_istek_mevcut_kaydi_ezmez(tmp_path):
    """Kimliği istemci X-Request-ID ile verebilir: yetkili bir istemci eski bir isteğin arşivini ezememeli."""
    ilk = _zip_dosyasi(tmp_path / "ilk.zip", {"ilk.xml": b"<ilk/>"})
    ikinci = _zip_dosyasi(tmp_path / "ikinci.zip", {"ikinci.xml": b"<ikinci/>"})
    ia.zip_kaydet(RID, ilk, "musteri_onboard", "orhan", None, "/x")
    ia.zip_kaydet(RID, ikinci, "musteri_onboard", "saldirgan", None, "/x")  # istisna fırlatmaz
    ia.fatura_kaydet(RID, "<ezme/>", {}, None, "saldirgan", None, VKN_A, "a.xml")
    assert (ia.kok() / RID / "gelen.zip").read_bytes() == ilk.read_bytes()
    assert _meta()["istemci"] == "orhan" and not (ia.kok() / RID / "istek.xml").exists()


def test_kapali_arsiv_hicbir_sey_yazmaz(tmp_path, monkeypatch):
    monkeypatch.setenv("GELEN_ARSIV_GUN", "0")
    ia.zip_kaydet(RID, _zip_dosyasi(tmp_path / "a.zip", {"a": b"x"}), "musteri_onboard", "o", None, "/x")
    ia.fatura_kaydet(RID, "<a/>", {}, None, "o", None, VKN_A, "a.xml")
    assert not ia.aktif() and not ia.kok().exists()


def test_fatura_kaydet_xml_cevap_ve_meta_alanlari():
    cevap = {"asama": "tdhp_tahmini_tamamlandi", "tdhp_tahmini": {"invoice_id": "F1", "approvable": False}}
    ia.fatura_kaydet(RID, "<Invoice/>", cevap, None, "orhan", "10.0.0.5", VKN_A, "f.xml")
    d = ia.kok() / RID
    assert (d / "istek.xml").read_text(encoding="utf-8") == "<Invoice/>"
    assert json.loads((d / "cevap.json").read_text(encoding="utf-8")) == cevap
    m = _meta()
    assert (m["tip"], m["durum"], m["vkn"], m["dosya_adi"], m["fatura_no"], m["approvable"], m["sonuc"]) == \
           ("fatura_isle", 200, VKN_A, "f.xml", "F1", False, "tdhp_tahmini_tamamlandi")
    assert set(m["dosyalar"]) == {"istek.xml", "cevap.json"}


def test_fatura_hatasi_cevap_json_yazmaz_ama_durum_ve_nedeni_meta_da_olur():
    ia.fatura_kaydet(RID, "<bozuk", None, {"durum": 400, "detay": "Geçersiz XML"}, "orhan", None, VKN_A, "f.xml")
    m = _meta()
    assert m["durum"] == 400 and m["hata"] == "Geçersiz XML" and set(m["dosyalar"]) == {"istek.xml"}


def test_hata_yaz_meta_ve_cevap_json_ve_dosya_listesi_birlesir(tmp_path):
    ia.zip_kaydet(RID, _zip_dosyasi(tmp_path / "a.zip", {"a": b"x"}), "musteri_onboard", "o", None, "/x")
    ia.hata_yaz(RID, 400, "Zip içinde şirket klasörü yok")
    m = _meta()
    assert m["durum"] == 400 and m["hata"] == "Zip içinde şirket klasörü yok"
    assert set(m["dosyalar"]) == {"gelen.zip", "cevap.json"}  # gelen.zip kaydı kaybolmadı
    assert json.loads((ia.kok() / RID / "cevap.json").read_text(encoding="utf-8")) == {"durum": 400, "detay": "Zip içinde şirket klasörü yok"}


def test_meta_yaz_none_degerleri_mevcut_alani_ezmez(tmp_path):
    ia.zip_kaydet(RID, _zip_dosyasi(tmp_path / "a.zip", {"a": b"x"}), "musteri_onboard", "orhan", "1.2.3.4", "/x")
    ia.meta_yaz(RID, istemci=None, durum=202)
    assert _meta()["istemci"] == "orhan" and _meta()["durum"] == 202


def _eski_yap(rid, gun):
    yol = ia.kok() / rid / "meta.json"
    m = json.loads(yol.read_text(encoding="utf-8"))
    m["zaman"] = (datetime.now(timezone.utc) - timedelta(days=gun)).isoformat(timespec="seconds")
    yol.write_text(json.dumps(m), encoding="utf-8")


def test_temizle_suresi_dolanlari_siler_yenileri_korur(tmp_path):
    for rid in ("a" * 12, "b" * 12):
        ia.zip_kaydet(rid, _zip_dosyasi(tmp_path / f"{rid}.zip", {"a": b"x"}), "musteri_onboard", "o", None, "/x")
    _eski_yap("a" * 12, 8)
    s = ia.temizle()
    assert s == {"silinen_sure": 1, "silinen_boyut": 0}
    assert not (ia.kok() / ("a" * 12)).exists() and (ia.kok() / ("b" * 12)).exists()


def test_temizle_boyut_tavani_asilinca_en_eskiden_siler(tmp_path, monkeypatch):
    for sira, rid in enumerate(("a" * 12, "b" * 12, "c" * 12)):
        z = tmp_path / f"{rid}.zip"
        z.write_bytes(b"PK\x03\x04" + os.urandom(2000))  # ~2 KB (geçersiz zip de olsa saklanır)
        ia.zip_kaydet(rid, z, "musteri_onboard", "o", None, "/x")
        _eski_yap(rid, 3 - sira)  # a en eski, c en yeni
    monkeypatch.setattr(ia, "max_bayt", lambda: 5000)  # ~2 KB'lık üç kayıttan yalnızca en yenisi/ikisi sığar
    s = ia.temizle()
    kalan = sorted(d.name for d in ia.kok().iterdir())
    assert s["silinen_boyut"] >= 1 and "a" * 12 not in kalan and "c" * 12 in kalan


def test_arsiv_hatasi_istegi_bozmaz(tmp_path, monkeypatch):
    dosya = tmp_path / "bu-bir-dosya"
    dosya.write_text("x")
    monkeypatch.setenv("ONBOARD_DATA_DIR", str(dosya))  # dizin oluşturulamaz
    z = _zip_dosyasi(tmp_path / "a.zip", {"a": b"x"})
    ia.zip_kaydet(RID, z, "musteri_onboard", "o", None, "/x")  # istisna fırlatmamalı
    ia.fatura_kaydet(RID, "<a/>", {}, None, "o", None, VKN_A, "a.xml")
    ia.hata_yaz(RID, 400, "x")
    ia.meta_yaz(RID, durum=1)


def test_panel_ile_ayni_sozlesme_izinli_dosyalar_ve_id_deseni():
    """izleme/arsiv.py (panel) ile buradaki beyaz liste aynı kalmalı: ayrışırlarsa panel ya yeni dosyayı göstermez ya da fazlasını açar."""
    sys.path.insert(0, str(ENTEGRASYON_DIR.parent / "izleme"))
    try:
        import arsiv as panel_arsiv
    finally:
        sys.path.pop(0)
    assert panel_arsiv.IZINLI_DOSYALAR == ia.IZINLI_DOSYALAR
    assert panel_arsiv.ID_DESENI.pattern == ia.ID_DESENI.pattern


# ---------------- uç noktalar ----------------

H = {"Authorization": "Bearer gecerli"}


def _zip_bytes(girdiler: dict) -> bytes:
    t = io.BytesIO()
    with zipfile.ZipFile(t, "w") as zf:
        for ad, icerik in girdiler.items():
            zf.writestr(ad, icerik)
    return t.getvalue()


def _tek_arsiv():
    (d,) = [x for x in ia.kok().iterdir() if x.is_dir()]
    return d


def test_toplu_isle_zip_ve_cevabi_arsivler_request_id_is_kaydinda(monkeypatch, tmp_path):
    import api_anahtarlari
    import app as entegrasyon_app

    kimlik = IstemciKimligi("musavir", False, frozenset({VKN_A}), False)
    depo = tf.TopluDeposu(tmp_path / "toplu")
    c = tf.TopluCalisan(depo, lambda *a: {"asama": "tdhp_tahmini_tamamlandi", "tdhp_tahmini": {"approvable": True}})
    monkeypatch.setattr(tf, "_calisan", c)
    monkeypatch.setitem(tf._baglanti, "kayitli_mi", lambda v: True)
    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", lambda a: kimlik if a == "gecerli" else None)
    cl = TestClient(entegrasyon_app.app)

    govde = _zip_bytes({"a.xml": "<a/>", "b.xml": "<b/>"})
    r = cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=govde, headers=H)
    assert r.status_code == 202, r.text
    rid = r.headers["X-Request-ID"]
    d = ia.kok() / rid
    assert (d / "gelen.zip").read_bytes() == govde  # iş bitince silinen zip'in kopyası arşivde
    m = _meta(rid)
    assert m["tip"] == "fatura_toplu" and m["istemci"] == "musavir" and m["durum"] == 202 and m["is_id"] == r.json()["is_id"]
    assert m["zip_dosya_sayisi"] == 2 and json.loads((d / "cevap.json").read_text(encoding="utf-8")) == r.json()
    assert depo.getir(r.json()["is_id"])["request_id"] == rid  # iş kaydından arşive bağlantı


def test_toplu_isle_reddedilen_istek_de_arsivlenir_nedeniyle(monkeypatch, tmp_path):
    import api_anahtarlari
    import app as entegrasyon_app

    kimlik = IstemciKimligi("musavir", False, frozenset({VKN_A}), False)
    monkeypatch.setattr(tf, "_calisan", tf.TopluCalisan(tf.TopluDeposu(tmp_path / "toplu"), lambda *a: {}))
    monkeypatch.setitem(tf._baglanti, "kayitli_mi", lambda v: True)
    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", lambda a: kimlik if a == "gecerli" else None)
    cl = TestClient(entegrasyon_app.app)
    r = cl.post(tf.TOPLU_YOLU, content=_zip_bytes({"2222222222/x.xml": "<a/>"}), headers=H)  # yetkisiz VKN
    assert r.status_code == 403
    rid = r.headers["X-Request-ID"]
    m = _meta(rid)
    assert m["durum"] == 403 and "2222222222" in m["hata"]
    assert (ia.kok() / rid / "gelen.zip").exists() and json.loads((ia.kok() / rid / "cevap.json").read_text(encoding="utf-8"))["durum"] == 403


def test_gecersiz_govde_400_de_arsivlenir(monkeypatch, tmp_path):
    import api_anahtarlari
    import app as entegrasyon_app

    kimlik = IstemciKimligi("musavir", False, frozenset({VKN_A}), False)
    monkeypatch.setattr(tf, "_calisan", tf.TopluCalisan(tf.TopluDeposu(tmp_path / "toplu"), lambda *a: {}))
    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", lambda a: kimlik if a == "gecerli" else None)
    r = TestClient(entegrasyon_app.app).post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=b"zip degil", headers=H)
    assert r.status_code == 400
    rid = r.headers["X-Request-ID"]
    assert (ia.kok() / rid / "gelen.zip").read_bytes() == b"zip degil" and _meta(rid)["durum"] == 400


def test_anahtarsiz_istek_arsivlenmez(monkeypatch, tmp_path):
    """Kimliği doğrulanmamış istek diske hiçbir şey yazdırmamalı (disk doldurma saldırısı)."""
    import app as entegrasyon_app

    r = TestClient(entegrasyon_app.app).post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=b"x" * 5000)
    assert r.status_code == 401
    assert not ia.kok().exists() or not list(ia.kok().iterdir())


# ---------------- tek fatura (/fatura/isle) ----------------

def _fatura_istemci(monkeypatch, ic):
    import api_anahtarlari
    import app as entegrasyon_app

    kimlik = IstemciKimligi("musavir", False, frozenset({VKN_A}), False)
    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", lambda a: kimlik if a == "gecerli" else None)
    monkeypatch.setattr(entegrasyon_app, "_fatura_isle_ic", ic)
    monkeypatch.setattr(entegrasyon_app, "_test_kaydini_logla", lambda *a, **k: None)  # Excel test kaydı yazılmasın
    return TestClient(entegrasyon_app.app, raise_server_exceptions=False)


def test_fatura_isle_xml_ve_cevabi_arsivler(monkeypatch):
    import app as entegrasyon_app

    cevap = entegrasyon_app.FaturaIsleCevabi(asama="tdhp_tahmini_tamamlandi", yon="inbox", mesaj="tamam")
    cl = _fatura_istemci(monkeypatch, lambda istek: cevap)
    r = cl.post("/fatura/isle", json={"fatura_xml": "<Invoice>ÖZEL</Invoice>", "satici_vkn": VKN_A, "dosya_adi": "f1.xml"}, headers=H)
    assert r.status_code == 200, r.text
    d = ia.kok() / r.headers["X-Request-ID"]
    assert (d / "istek.xml").read_text(encoding="utf-8") == "<Invoice>ÖZEL</Invoice>"
    assert json.loads((d / "cevap.json").read_text(encoding="utf-8"))["asama"] == r.json()["asama"] == "tdhp_tahmini_tamamlandi"
    m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert (m["tip"], m["istemci"], m["vkn"], m["dosya_adi"], m["durum"]) == ("fatura_isle", "musavir", VKN_A, "f1.xml", 200)


def test_fatura_isle_http_hatasi_xml_ve_nedeniyle_arsivlenir(monkeypatch):
    from fastapi import HTTPException

    def ic(istek):
        raise HTTPException(status_code=400, detail="Geçersiz XML — belge ayrıştırılamadı")

    r = _fatura_istemci(monkeypatch, ic).post("/fatura/isle", json={"fatura_xml": "<bozuk", "satici_vkn": VKN_A}, headers=H)
    assert r.status_code == 400
    d = ia.kok() / r.headers["X-Request-ID"]
    m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert (d / "istek.xml").read_text(encoding="utf-8") == "<bozuk" and m["durum"] == 400 and "Geçersiz XML" in m["hata"]
    assert not (d / "cevap.json").exists()


def test_fatura_isle_beklenmeyen_hata_500_arsivlenir_ve_yigin_izi_sizmaz(monkeypatch):
    def ic(istek):
        raise RuntimeError("gizli-ic-ayrinti")

    r = _fatura_istemci(monkeypatch, ic).post("/fatura/isle", json={"fatura_xml": "<a/>", "satici_vkn": VKN_A}, headers=H)
    assert r.status_code == 500  # (500'de genel hata yakalayıcı RequestId middleware'inin dışında: yanıtta X-Request-ID yok, tek arşiv dizinine bakılır)
    m = json.loads((_tek_arsiv() / "meta.json").read_text(encoding="utf-8"))
    assert m["durum"] == 500 and "gizli-ic-ayrinti" not in json.dumps(m)


def test_fatura_isle_yetkisiz_vkn_403_arsivlenmez(monkeypatch):
    """403 yetki kontrolünde, arşivlemeden ÖNCE döner: yetkisiz bir VKN adına gelen istek diske yazılmaz."""
    r = _fatura_istemci(monkeypatch, lambda i: None).post("/fatura/isle", json={"fatura_xml": "<a/>", "satici_vkn": "2222222222"}, headers=H)
    assert r.status_code == 403
    assert not ia.kok().exists() or not list(ia.kok().iterdir())


# ---------------- karar izi (iz.json) ----------------

def _gercek_akis_istemcisi(monkeypatch, sahte_tdhp=None, kontrol=None):
    """_fatura_isle_ic GERÇEK çalışır; yalnızca dış bağımlılıklar (Mcp, model_eval, DB) sahtelenir."""
    import api_anahtarlari
    import app as A

    kimlik = IstemciKimligi("musavir", False, frozenset({VKN_A}), False)
    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", lambda a: kimlik if a == "gecerli" else None)
    monkeypatch.setattr(A, "model_eval_hazir_mi", lambda: (True, ""))
    monkeypatch.setattr(A, "sirket_kayitli_mi", lambda v: True)
    monkeypatch.setattr(A, "faturayi_parse_et_ve_yonu_dogrula",
                        lambda xml, vkn: {"direction": "outbox", "header": {"account_title": "ÖRNEK MÜŞTERİ A.Ş.", "account_tax_number": "9990000000"}})
    monkeypatch.setattr(A, "fatura_kontrol_et", kontrol or (lambda *a, **k: {"genel_karar": "uygun", "fatura_no": "F1", "satir_sonuclari": [{"kalem": "x", "karar": "uygun"}]}))
    monkeypatch.setattr(A, "fatura_kur_bilgisi", lambda *a, **k: {"exchange_rate": None})
    monkeypatch.setattr(A, "bekleyen_tahmin_kaydet", lambda *a, **k: "pid-1")
    monkeypatch.setattr(A, "_test_kaydini_logla", lambda *a, **k: None)

    def varsayilan_tdhp(xml, own_vkn, convert_to_try=False, parsed_invoice=None):
        A.iz_adim("ana_llm", "Ana model: 3 haneli hesap kodları", "llm", sonuc="120 Borc 100.00", sistem_istemi="GIZLI-SISTEM-ISTEMI", kullanici_istemi="GIZLI-KULLANICI-ISTEMI")
        return {"invoice_id": "F1", "direction": "outbox", "currency": "TRY", "entries": [], "records": [], "balanced": True, "borc_toplam": 0.0,
                "alacak_toplam": 0.0, "self_corrected": False, "self_correct_reason": None, "error": None, "approvable": True, "validation_errors": []}

    monkeypatch.setattr(A, "tdhp_tahmini_yap", sahte_tdhp or varsayilan_tdhp)
    return TestClient(A.app, raise_server_exceptions=False)


def test_karar_izi_iz_json_olarak_arsivlenir_ve_dis_cevaba_girmez(monkeypatch):
    cl = _gercek_akis_istemcisi(monkeypatch)
    r = cl.post("/fatura/isle", json={"fatura_xml": "<Invoice/>", "satici_vkn": VKN_A, "dosya_adi": "f1.xml"}, headers=H)
    assert r.status_code == 200, r.text
    # ---- dış cevap: istemler (prompt) ve iz asla sızmaz
    assert "GIZLI-SISTEM-ISTEMI" not in r.text and "adimlar" not in r.text and "karar_izi" not in r.text
    # ---- arşiv: iz.json
    d = ia.kok() / r.headers["X-Request-ID"]
    iz = json.loads((d / "iz.json").read_text(encoding="utf-8"))
    turler = [a["tur"] for a in iz["adimlar"]]
    assert turler == ["istek", "sirket", "yon", "on_filtre", "devam", "ana_llm", "sonuc"]
    adim = {a["tur"]: a for a in iz["adimlar"]}
    assert adim["istek"]["detay"]["satici_vkn"] == VKN_A and adim["istek"]["detay"]["dosya_adi"] == "f1.xml"
    assert adim["yon"]["karar_veren"] == "kural" and adim["yon"]["sonuc"].startswith("outbox") and VKN_A in adim["yon"]["neden"]
    assert adim["on_filtre"]["karar_veren"] == "kural" and adim["on_filtre"]["detay"]["on_filtre"]["genel_karar"] == "uygun"
    assert adim["devam"]["sonuc"] == "TDHP tahminine geçildi"
    assert adim["ana_llm"]["detay"]["sistem_istemi"] == "GIZLI-SISTEM-ISTEMI"          # istem arşivde VAR
    assert adim["sonuc"]["detay"]["asama"] == "tdhp_tahmini_tamamlandi"
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert "iz.json" in meta["dosyalar"] and meta["dosyalar"]["iz.json"] == (d / "iz.json").stat().st_size


def test_karar_izi_reddedilen_istekte_nerede_durdugunu_gosterir(monkeypatch):
    cl = _gercek_akis_istemcisi(monkeypatch, kontrol=lambda *a, **k: (_ for _ in ()).throw(ValueError("VKN uyuşmazlığı")))
    r = cl.post("/fatura/isle", json={"fatura_xml": "<Invoice/>", "satici_vkn": VKN_A}, headers=H)
    assert r.status_code == 400
    iz = json.loads((ia.kok() / r.headers["X-Request-ID"] / "iz.json").read_text(encoding="utf-8"))
    assert [a["tur"] for a in iz["adimlar"]][-1] == "hata"
    assert "VKN uyuşmazlığı" in iz["adimlar"][-1]["neden"] and iz["adimlar"][-1]["sonuc"] == "HTTP 400"


def test_karar_izi_arsiv_kapaliyken_toplanmaz(monkeypatch):
    monkeypatch.setenv("GELEN_ARSIV_GUN", "0")
    cl = _gercek_akis_istemcisi(monkeypatch)
    r = cl.post("/fatura/isle", json={"fatura_xml": "<Invoice/>", "satici_vkn": VKN_A}, headers=H)
    assert r.status_code == 200 and not ia.kok().exists()


def test_karar_izi_toplanamazsa_islem_yine_calisir(monkeypatch):
    import app as A

    cl = _gercek_akis_istemcisi(monkeypatch)
    monkeypatch.setattr(A, "yeni_karar_izi", lambda: None)  # model_eval import edilemedi senaryosu: iz kapalı
    r = cl.post("/fatura/isle", json={"fatura_xml": "<Invoice/>", "satici_vkn": VKN_A}, headers=H)
    assert r.status_code == 200
    d = ia.kok() / r.headers["X-Request-ID"]
    assert (d / "istek.xml").exists() and not (d / "iz.json").exists()
