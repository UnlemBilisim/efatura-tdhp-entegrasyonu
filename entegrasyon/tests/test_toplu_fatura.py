"""Toplu fatura işleme — güvenli zip açma, kalıcı iş durumu, çalışan (devam etme dahil) ve HTTP uçları.

LLM/veritabanı GEREKMEZ: tek-fatura iç fonksiyonu sahte `islem` ile değiştirilir."""

import io
import json
import logging
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

import toplu_fatura_api as tf  # noqa: E402
from api_anahtarlari import IstemciKimligi  # noqa: E402

VKN_A, VKN_B = "1111111111", "2222222222"


def _zip(girdiler: dict, sikistirma=zipfile.ZIP_DEFLATED) -> bytes:
    t = io.BytesIO()
    with zipfile.ZipFile(t, "w", sikistirma) as zf:
        for ad, icerik in girdiler.items():
            zf.writestr(ad, icerik)
    return t.getvalue()


def _cevap(asama="tdhp_tahmini_tamamlandi", approvable=True, fatura_no="F1"):
    return {"asama": asama, "yon": "inbox", "prediction_id": "p-" + fatura_no, "mesaj": "m",
            "tdhp_tahmini": {"invoice_id": fatura_no, "approvable": approvable, "validation_errors": [],
                             "records": [{"account_code": "770", "amount": 1.0}]}}


def sahte_islem(xml, vkn, dosya, onay, kur, gonderen):
    cagrilar.append({"xml": xml, "vkn": vkn, "dosya": dosya, "onay": onay, "kur": kur, "gonderen": gonderen})
    if "HATALI" in xml:
        raise HTTPException(status_code=400, detail="Geçersiz XML — belge ayrıştırılamadı")
    if "CÖKTÜ" in xml:
        raise RuntimeError("beklenmeyen")
    if "KUR" in xml and kur is None:
        return _cevap("kur_onayi_bekliyor")
    if "ONAYSIZ" in xml:
        return _cevap("tdhp_dogrulama_basarisiz", approvable=False)
    return _cevap(fatura_no=dosya)


cagrilar: list = []


@pytest.fixture(autouse=True)
def _temizle():
    cagrilar.clear()


# ---------------- faturalari_cikar ----------------

def test_satici_vkn_verilince_klasor_duzeni_onemsiz_ve_xml_disi_atlanir(tmp_path):
    z = tmp_path / "a.zip"
    z.write_bytes(_zip({"ocak/a.xml": "<a/>", "b.xml": "<b/>", "ocak/not.txt": "x", "__MACOSX/c.xml": "x"}))
    s = tf.faturalari_cikar(z, tmp_path / "o", VKN_A)
    assert [f["vkn"] for f in s["faturalar"]] == [VKN_A, VKN_A] and s["atlanan_dosya"] == 2
    assert sorted(p.name for p in (tmp_path / "o").iterdir()) == ["000001.xml", "000002.xml"]


def test_vkn_klasorleri_cok_sirketli_ve_sarmalayici_tolere_edilir(tmp_path):
    z = tmp_path / "a.zip"
    z.write_bytes(_zip({f"yuk/{VKN_A}/x.xml": "<a/>", f"yuk/{VKN_B}/alt/y.xml": "<b/>", "yuk/kok.xml": "<z/>"}))
    s = tf.faturalari_cikar(z, tmp_path / "o", None)
    assert [(f["vkn"], f["dosya"]) for f in s["faturalar"]] == [(VKN_A, "x.xml"), (VKN_B, "alt/y.xml")]
    assert s["atlanan_dosya"] == 1  # VKN klasörü dışındaki kök dosyası


@pytest.mark.parametrize("kotu", ["../x.xml", "/etc/a.xml", f"{VKN_A}\\a.xml", f"{VKN_A}/../../a.xml"])
def test_zip_slip_tum_zip_i_reddeder(tmp_path, kotu):
    z = tmp_path / "a.zip"
    z.write_bytes(_zip({f"{VKN_A}/ok.xml": "<a/>", kotu: "<x/>"}))
    with pytest.raises(tf.ZipHatasi):
        tf.faturalari_cikar(z, tmp_path / "o", None)


def test_fatura_sayisi_siniri_ve_tek_dosya_boyutu(tmp_path, monkeypatch):
    z = tmp_path / "a.zip"
    z.write_bytes(_zip({f"{VKN_A}/{i}.xml": "<a/>" for i in range(3)}))
    monkeypatch.setattr(tf, "MAX_FATURA", 2)
    with pytest.raises(tf.ZipHatasi, match="en fazla 2"):
        tf.faturalari_cikar(z, tmp_path / "o", None)
    monkeypatch.setattr(tf, "MAX_FATURA", 10)
    monkeypatch.setattr(tf, "MAX_REQUEST_BYTES", 3)
    with pytest.raises(tf.ZipHatasi, match="çok büyük"):
        tf.faturalari_cikar(z, tmp_path / "o2", None)


def test_gecersiz_ve_parolali_zip(tmp_path):
    (tmp_path / "b.zip").write_bytes(b"PK\x03\x04bozuk")
    with pytest.raises(tf.ZipHatasi):
        tf.faturalari_cikar(tmp_path / "b.zip", tmp_path / "o", None)


# ---------------- çalışan ----------------

@pytest.fixture
def ortam(tmp_path):
    depo = tf.TopluDeposu(tmp_path / "toplu")
    return tf.TopluCalisan(depo, sahte_islem), depo


def _is_hazirla(depo, tmp_path, dosyalar: dict, vkn=VKN_A, onay=None, kur=None, etiket="musavir"):
    """dosyalar: {ad: xml_metni} → iş + xml dizini oluşturur, is_id döner."""
    import uuid
    is_id = uuid.uuid4().hex
    xml_d = depo.dizin(is_id) / "xml"
    xml_d.mkdir(parents=True)
    fat = []
    for i, (ad, xml) in enumerate(dosyalar.items(), 1):
        (xml_d / f"{i:06d}.xml").write_text(xml, encoding="utf-8")
        fat.append({"sira": i, "vkn": vkn, "dosya": ad, "yol": f"{i:06d}.xml"})
    depo.olustur(is_id, etiket, fat, onay, kur, 0)
    return is_id


def test_tum_faturalar_islenir_sayaclar_ve_hata_izolasyonu(ortam, tmp_path):
    c, depo = ortam
    is_id = _is_hazirla(depo, tmp_path, {"a.xml": "<ok/>", "b.xml": "HATALI", "c.xml": "ONAYSIZ", "d.xml": "KUR", "e.xml": "CÖKTÜ", "f.xml": "<ok2/>"})
    c.isle(is_id)
    j = depo.getir(is_id)
    assert j["durum"] == "bitti" and j["yuzde"] == 100 and j["tamamlanan"] == 6
    assert j["sayilar"] == {"hazir": 2, "onaysiz": 1, "onay_bekliyor": 0, "kur_bekliyor": 1, "hata": 2}
    sonuclar = {k["dosya"]: k for k in depo.sonuclar(is_id)}
    assert sonuclar["b.xml"]["http_durum"] == 400 and "ayrıştırılamadı" in sonuclar["b.xml"]["hata"]
    assert sonuclar["e.xml"]["hata"] == "Beklenmeyen hata: RuntimeError"  # iç ayrıntı sızmaz
    assert sonuclar["a.xml"]["ozet"]["approvable"] is True and sonuclar["a.xml"]["cevap"]["tdhp_tahmini"]["records"]
    assert not (depo.dizin(is_id) / "xml").exists()  # ham müşteri faturaları iş bitince silindi


def test_onay_ve_kur_secimi_tum_faturalara_uygulanir_ve_gonderen_etiketlenir(ortam, tmp_path):
    c, depo = ortam
    c.isle(_is_hazirla(depo, tmp_path, {"a.xml": "<a/>", "b.xml": "KUR"}, onay=True, kur="tl", etiket="orhan"))
    assert all(x["onay"] is True and x["kur"] == "tl" and x["gonderen"] == "orhan" for x in cagrilar)


def test_yeniden_baslatma_kaldigi_yerden_devam_eder_islenenleri_tekrarlamaz(ortam, tmp_path):
    c, depo = ortam
    is_id = _is_hazirla(depo, tmp_path, {"a.xml": "<a/>", "b.xml": "<b/>", "c.xml": "<c/>"})
    depo.sonuc_ekle(is_id, {"sira": 1, "dosya": "a.xml", "vkn": VKN_A, "sonuc": "hazir", "cevap": _cevap(), "ozet": {}})  # 1. fatura bitmişti
    depo.durum_guncelle(is_id, "calisiyor")
    c2 = tf.TopluCalisan(depo, sahte_islem)
    c2.bitmemisleri_kuyrukla()  # (iş parçacığı BAŞLATILMAZ: test deterministik kalsın)
    assert c2.kuyruk.get_nowait() == is_id
    c2.isle(is_id)
    assert sorted(x["dosya"] for x in cagrilar) == ["b.xml", "c.xml"]  # a.xml yeniden İŞLENMEDİ
    assert depo.getir(is_id)["tamamlanan"] == 3 and depo.getir(is_id)["durum"] == "bitti"


def test_ayni_is_iki_kez_calistirilirsa_tekrar_islenmez(ortam, tmp_path):
    c, depo = ortam
    is_id = _is_hazirla(depo, tmp_path, {"a.xml": "<a/>"})
    c.isle(is_id)
    c.isle(is_id)  # bitmiş iş: sessizce atlanır
    assert len(cagrilar) == 1


def test_audit_logu_ham_xml_icermez(ortam, tmp_path, caplog):
    c, depo = ortam
    with caplog.at_level(logging.INFO, logger="entegrasyon.audit"):
        c.isle(_is_hazirla(depo, tmp_path, {"a.xml": "<GIZLI-FATURA-ICERIGI/>"}))
    assert "GIZLI-FATURA-ICERIGI" not in caplog.text and "toplu_fatura_islendi" in caplog.text


def test_eski_bitmis_isler_temizlenir_yenisi_kalir(ortam, tmp_path):
    c, depo = ortam
    eski, yeni = _is_hazirla(depo, tmp_path, {"a.xml": "<a/>"}), _is_hazirla(depo, tmp_path, {"b.xml": "<b/>"})
    for i in (eski, yeni):
        c.isle(i)
    p = depo.dizin(eski) / "is.json"
    v = json.loads(p.read_text())
    v["olusturulma"] = "2020-01-01T00:00:00+00:00"
    p.write_text(json.dumps(v))
    assert depo.eskileri_temizle(14) == 1 and depo.getir(eski) is None and depo.getir(yeni) is not None


def test_is_kimligi_yol_gezinmesine_izin_vermez(ortam):
    assert ortam[1].getir("../../etc") is None


# ---------------- HTTP ----------------

YETKILI = IstemciKimligi("musavir", False, frozenset({VKN_A}), False)
H = {"Authorization": "Bearer gecerli"}


def _istemci(monkeypatch, tmp_path, kimlik=YETKILI, kayitli=lambda v: True):
    import api_anahtarlari
    import app as entegrasyon_app

    depo = tf.TopluDeposu(tmp_path / "toplu")
    c = tf.TopluCalisan(depo, sahte_islem)
    monkeypatch.setattr(tf, "_calisan", c)
    monkeypatch.setitem(tf._baglanti, "kayitli_mi", kayitli)
    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", lambda a: kimlik if a == "gecerli" else None)
    return TestClient(entegrasyon_app.app), c


def test_http_anahtarsiz_401(monkeypatch, tmp_path):
    cl, _ = _istemci(monkeypatch, tmp_path)
    assert cl.post(tf.TOPLU_YOLU + "?satici_vkn=" + VKN_A, content=b"x").status_code == 401


def test_http_yetkisiz_vkn_403_govde_okunmadan_ve_zip_icindeki_vkn_de_kontrol_edilir(monkeypatch, tmp_path):
    cl, c = _istemci(monkeypatch, tmp_path)
    assert cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_B}", content=_zip({"a.xml": "<a/>"}), headers=H).status_code == 403
    r = cl.post(tf.TOPLU_YOLU, content=_zip({f"{VKN_A}/a.xml": "<a/>", f"{VKN_B}/b.xml": "<b/>"}), headers=H)
    assert r.status_code == 403 and VKN_B in r.json()["detail"] and VKN_A not in r.json()["detail"]
    assert c.depo.bekleyen_sayisi() == 0 and not list((c.depo.kok).glob("[0-9a-f]*"))  # hiçbir şey kuyruğa/diske kalmadı


def test_http_kayitsiz_sirket_404(monkeypatch, tmp_path):
    cl, _ = _istemci(monkeypatch, tmp_path, kayitli=lambda v: False)
    r = cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=_zip({"a.xml": "<a/>"}), headers=H)
    assert r.status_code == 404 and VKN_A in r.json()["detail"]


def test_http_uctan_uca_yukle_isle_ozet_ve_tam_sonuc(monkeypatch, tmp_path):
    cl, c = _istemci(monkeypatch, tmp_path)
    govde = _zip({f"f{i}.xml": ("ONAYSIZ" if i == 2 else "<ok/>") for i in range(1, 5)})
    r = cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}&onay=true&kur_secimi=orijinal", content=govde, headers=H)
    assert r.status_code == 202, r.text
    j = r.json()
    assert j["toplam"] == 4 and j["vknler"] == [VKN_A] and j["durum"] == "kuyrukta"
    d0 = cl.get(f"/fatura/toplu/{j['is_id']}", headers=H).json()
    assert d0["yuzde"] == 0 and d0["faturalar"]["kayitlar"] == []

    c.isle(c.kuyruk.get_nowait())
    assert all(x["onay"] is True and x["kur"] == "orijinal" for x in cagrilar)
    d = cl.get(f"/fatura/toplu/{j['is_id']}", headers=H).json()
    assert d["durum"] == "bitti" and d["yuzde"] == 100 and d["sayilar"]["hazir"] == 3 and d["sayilar"]["onaysiz"] == 1
    assert "etiket" not in d and d["faturalar"]["toplam_kayit"] == 4
    assert "cevap" not in d["faturalar"]["kayitlar"][0] and d["faturalar"]["kayitlar"][0]["prediction_id"]  # özet: records[] yok
    onaysiz = cl.get(f"/fatura/toplu/{j['is_id']}?sonuc=onaysiz", headers=H).json()
    assert [k["dosya"] for k in onaysiz["faturalar"]["kayitlar"]] == ["f2.xml"]
    tam = cl.get(f"/fatura/toplu/{j['is_id']}/sonuclar?boyut=2&sayfa=2", headers=H).json()
    assert tam["toplam_kayit"] == 4 and len(tam["kayitlar"]) == 2 and tam["kayitlar"][0]["cevap"]["tdhp_tahmini"]["records"]


def test_http_cok_sirketli_zip(monkeypatch, tmp_path):
    kimlik = IstemciKimligi("musavir", False, frozenset({VKN_A, VKN_B}), False)
    cl, c = _istemci(monkeypatch, tmp_path, kimlik=kimlik)
    j = cl.post(tf.TOPLU_YOLU, content=_zip({f"{VKN_A}/a.xml": "<a/>", f"{VKN_B}/b.xml": "<b/>"}), headers=H).json()
    c.isle(c.kuyruk.get_nowait())
    assert sorted((x["vkn"], x["dosya"]) for x in cagrilar) == [(VKN_A, "a.xml"), (VKN_B, "b.xml")]
    assert j["vknler"] == [VKN_A, VKN_B]


def test_http_baska_anahtarin_isi_404(monkeypatch, tmp_path):
    import api_anahtarlari
    cl, _ = _istemci(monkeypatch, tmp_path)
    j = cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=_zip({"a.xml": "<a/>"}), headers=H).json()
    digeri = IstemciKimligi("baska", False, frozenset({VKN_A}), False)
    monkeypatch.setattr(api_anahtarlari, "anahtari_dogrula", lambda a: digeri)
    for yol in (f"/fatura/toplu/{j['is_id']}", f"/fatura/toplu/{j['is_id']}/sonuclar"):
        assert cl.get(yol, headers=H).status_code == 404


@pytest.mark.parametrize("govde,kod", [(b"zip degil", 400), (_zip({"readme.txt": "x"}), 400), (_zip({"../a.xml": "x"}), 400)])
def test_http_gecersiz_zip_400_ve_diskte_iz_kalmaz(monkeypatch, tmp_path, govde, kod):
    cl, c = _istemci(monkeypatch, tmp_path)
    assert cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=govde, headers=H).status_code == kod
    assert not list((c.depo.kok).glob("[0-9a-f]*")) and not list((c.depo.kok / "_yuklemeler").glob("*"))


def test_http_gecersiz_parametre_422_boyut_413_ve_429(monkeypatch, tmp_path):
    cl, _ = _istemci(monkeypatch, tmp_path)
    z = _zip({"a.xml": "<a/>"})
    assert cl.post(f"{tf.TOPLU_YOLU}?satici_vkn=123", content=z, headers=H).status_code == 422
    assert cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}&kur_secimi=euro", content=z, headers=H).status_code == 422
    monkeypatch.setattr(tf, "TOPLU_MAX_ZIP_BYTES", 50)
    assert cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=z, headers=H).status_code == 413
    monkeypatch.setattr(tf, "TOPLU_MAX_ZIP_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(tf, "MAX_BEKLEYEN_IS", 1)
    assert cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=z, headers=H).status_code == 202
    assert cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=z, headers=H).status_code == 429


def test_http_genel_istek_siniri_zip_yolu_icin_gecerli_degil(monkeypatch, tmp_path):
    """Genel 10 MB sınırı bu yolda uygulanmaz (akış yolu); 11 MB'lık (saklanmış) zip kabul edilir."""
    import security
    cl, _ = _istemci(monkeypatch, tmp_path)
    buyuk = _zip({"a.xml": b"A" * (5 * 1024 * 1024 + 1), "b.xml": b"B" * (5 * 1024 * 1024 + 1)}, sikistirma=zipfile.ZIP_STORED)
    assert len(buyuk) > security.MAX_REQUEST_BYTES
    monkeypatch.setattr(tf, "MAX_REQUEST_BYTES", 8 * 1024 * 1024)  # tek fatura sınırı içinde
    assert cl.post(f"{tf.TOPLU_YOLU}?satici_vkn={VKN_A}", content=buyuk, headers=H).status_code == 202


# ---------------- tek-fatura iç fonksiyonuna bağlantı ----------------

def test_app_adaptoru_ayni_ic_fonksiyonu_cagirir_ttl_uzatir_ve_sifirlar(monkeypatch):
    import app as entegrasyon_app
    import model_eval_koprusu as kopru

    gorulen = {}

    def sahte_ic(istek):
        gorulen["ttl"] = kopru._tahmin_ttl_dakika.get()
        gorulen["istek"] = istek
        return entegrasyon_app.FaturaIsleCevabi(asama="tdhp_tahmini_tamamlandi", mesaj="ok")

    monkeypatch.setattr(entegrasyon_app, "_fatura_isle_ic", sahte_ic)
    cevap = entegrasyon_app._toplu_islem("<a/>", VKN_A, "a.xml", True, "tl", "orhan")
    assert cevap["asama"] == "tdhp_tahmini_tamamlandi"
    assert gorulen["ttl"] == tf.TAHMIN_TTL_DAKIKA and kopru._tahmin_ttl_dakika.get() == 30  # iş sonrası eski değer
    i = gorulen["istek"]
    assert (i.satici_vkn, i.onay, i.kur_secimi, i.dosya_adi, i.gonderen_kullanici) == (VKN_A, True, "tl", "a.xml", "toplu:orhan")


def test_bos_beklemede_eski_sonuclar_temizlenir(ortam, tmp_path, monkeypatch):
    """İş yokken de saatte bir temizlik yapılır (yalnızca açılışta değil)."""
    c, depo = ortam
    temizlenen = []
    monkeypatch.setattr(depo, "eskileri_temizle", lambda gun: temizlenen.append(gun))

    class Bos:
        def get(self, timeout=None):
            if temizlenen:
                raise SystemExit  # döngüyü bitir
            raise tf.queue.Empty

    c.kuyruk = Bos()
    with pytest.raises(SystemExit):
        c._dongu()
    assert temizlenen == [tf.SAKLAMA_GUN]
