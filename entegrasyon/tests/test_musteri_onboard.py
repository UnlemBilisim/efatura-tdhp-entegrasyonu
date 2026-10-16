"""Çok şirketli zip onboarding — güvenli açma, iş durumu, çalışan ve HTTP uçları.

Veritabanı/Ollama GEREKMEZ: çalışanın bağımlılıkları (kurulu_mu / kur / kapsam_ekle)
sahtelerle değiştirilir. Gerçek kurulum ayrıca `scripts/musteri_onboard_toplu.py`'nin
kendi testleriyle ve canlı denemeyle doğrulanır."""

import io
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENTEGRASYON_DIR = Path(__file__).resolve().parents[1]
if str(ENTEGRASYON_DIR) not in sys.path:
    sys.path.insert(0, str(ENTEGRASYON_DIR))

import musteri_onboard_api as mo  # noqa: E402
from api_anahtarlari import IstemciKimligi  # noqa: E402

VKN_A, VKN_B = "1111111111", "2222222222"
XML = b"<Invoice/>"


def _zip(girdiler: dict) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as zf:
        for ad, icerik in girdiler.items():
            zf.writestr(ad, icerik)
    return tampon.getvalue()


def _tam_sirket(vkn, on_ek=""):
    return {f"{on_ek}{vkn}/mizan.xlsx": b"m", f"{on_ek}{vkn}/yevmiye.csv": b"y",
            f"{on_ek}{vkn}/faturalar/a.xml": XML, f"{on_ek}{vkn}/faturalar/b.xml": XML}


def _ac(tmp_path, girdiler):
    z = tmp_path / "x.zip"
    z.write_bytes(_zip(girdiler))
    return mo.zip_guvenli_ac(z, tmp_path / "cikti")


# ---------------- zip_guvenli_ac ----------------

def test_cok_sirketli_zip_acilir_ve_fatura_adlari_siralanir(tmp_path):
    sonuc = _ac(tmp_path, {**_tam_sirket(VKN_A), **_tam_sirket(VKN_B), f"{VKN_A}/nace.txt": b"10.71.01"})
    assert sonuc["vknler"] == [VKN_A, VKN_B]
    assert sorted(p.name for p in (tmp_path / "cikti" / VKN_A / "faturalar").iterdir()) == ["000001.xml", "000002.xml"]
    assert (tmp_path / "cikti" / VKN_A / "nace.txt").read_bytes() == b"10.71.01"


def test_tek_sarmalayici_klasor_tolere_edilir(tmp_path):
    assert _ac(tmp_path, _tam_sirket(VKN_A, on_ek="yukleme/"))["vknler"] == [VKN_A]


def test_macos_cop_ve_izinsiz_dosyalar_atlanir(tmp_path):
    sonuc = _ac(tmp_path, {**_tam_sirket(VKN_A), "__MACOSX/x": b"1", f"{VKN_A}/.DS_Store": b"1",
                           f"{VKN_A}/gizli.exe": b"1", "kok.txt": b"1", "abc/mizan.xlsx": b"1"})
    assert sonuc["vknler"] == [VKN_A] and sonuc["atlanan_dosya"] >= 4 and sonuc["gecersiz_klasorler"] == ["abc"]
    assert not (tmp_path / "cikti" / VKN_A / "gizli.exe").exists()


@pytest.mark.parametrize("kotu_ad", ["../kacis/mizan.xlsx", f"{VKN_A}/../../x", "/etc/passwd", "C:/x/mizan.xlsx", f"{VKN_A}\\mizan.xlsx"])
def test_zip_slip_tum_zip_i_reddeder_ve_disina_yazmaz(tmp_path, kotu_ad):
    with pytest.raises(mo.ZipHatasi):
        _ac(tmp_path, {**_tam_sirket(VKN_A), kotu_ad: b"x"})
    assert not (tmp_path / "kacis").exists() and not (tmp_path.parent / "kacis").exists()


def test_zip_bomb_gercek_bayt_sayisiyla_yakalanir(tmp_path, monkeypatch):
    monkeypatch.setattr(mo, "MAX_TEK_DOSYA_BAYT", 1000)
    with pytest.raises(mo.ZipHatasi):
        _ac(tmp_path, {f"{VKN_A}/faturalar/a.xml": b"A" * 5000})


def test_sikistirma_orani_siniri(tmp_path):
    with pytest.raises(mo.ZipHatasi, match="sıkıştırma"):
        _ac(tmp_path, {f"{VKN_A}/faturalar/a.xml": b"\0" * (6 * 1024 * 1024)})


def test_dosya_sayisi_ve_gecersiz_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(mo, "MAX_DOSYA_SAYISI", 2)
    with pytest.raises(mo.ZipHatasi, match="çok fazla"):
        _ac(tmp_path, _tam_sirket(VKN_A))
    (tmp_path / "bozuk.zip").write_bytes(b"PK\x03\x04bozuk")
    with pytest.raises(mo.ZipHatasi):
        mo.zip_guvenli_ac(tmp_path / "bozuk.zip", tmp_path / "o")


# ---------------- çalışan ----------------

@pytest.fixture
def ortam(tmp_path):
    depo = mo.IsDeposu(tmp_path / "veri")
    olaylar = {"kurulanlar": [], "kapsam": [], "kurulu": set(), "kur_hatasi": set()}

    def kur(vkn, dizin, ilerleme=None):
        assert (dizin / "mizan.xlsx").exists()
        for adim, yuzde in (("sema", 25), ("mizan", 50)):
            ilerleme(adim, yuzde)
        if vkn in olaylar["kur_hatasi"]:
            raise RuntimeError(f"patladi {dizin}")
        for adim, yuzde in (("eslestirme", 75), ("rag", 100)):
            ilerleme(adim, yuzde)
        olaylar["kurulanlar"].append(vkn)
        return {"vkn": vkn}

    c = mo.Calisan(depo, lambda v: v in olaylar["kurulu"], kur,
                   lambda e, v: olaylar["kapsam"].append((e, v)) or True, lambda i: depo.kok / "dosyalar" / i)
    return c, olaylar


def _is_olustur(c, tmp_path, vknler, etiket="musavir"):
    hedef_ic = {}
    for v in vknler:
        hedef_ic.update(_tam_sirket(v))
    veri = c.depo.olustur(etiket, vknler, 0, [])
    mo.zip_guvenli_ac_dosyaya = None
    z = tmp_path / f"{veri['is_id']}.zip"
    z.write_bytes(_zip(hedef_ic))
    mo.zip_guvenli_ac(z, c.is_dizini(veri["is_id"]))
    return veri["is_id"]


def test_yeni_sirket_kurulur_kapsam_eklenir_ham_veri_silinir(ortam, tmp_path):
    c, o = ortam
    is_id = _is_olustur(c, tmp_path, [VKN_A])
    c.isle(is_id)
    j = c.depo.getir(is_id)
    assert j["durum"] == "bitti" and j["sirketler"][VKN_A]["durum"] == "kuruldu"
    assert o["kapsam"] == [("musavir", VKN_A)]
    assert c.depo.kurulum_kaydi(VKN_A)["durum"] == "tamam"
    assert not c.is_dizini(is_id).exists()  # müşteri verisi iş bitince silindi


def test_mevcut_sirket_atlanir_uzerine_yazilmaz(ortam, tmp_path):
    c, o = ortam
    o["kurulu"].add(VKN_A)
    is_id = _is_olustur(c, tmp_path, [VKN_A, VKN_B])
    c.isle(is_id)
    s = c.depo.getir(is_id)["sirketler"]
    assert s[VKN_A]["durum"] == "atlandi" and s[VKN_B]["durum"] == "kuruldu"
    assert o["kurulanlar"] == [VKN_B] and o["kapsam"] == [("musavir", VKN_B)]  # atlanan için kapsam VERİLMEZ


def test_bir_sirket_hata_verirse_digerleri_devam_eder_ve_yol_sizmaz(ortam, tmp_path):
    c, o = ortam
    o["kur_hatasi"].add(VKN_A)
    is_id = _is_olustur(c, tmp_path, [VKN_A, VKN_B])
    c.isle(is_id)
    s = c.depo.getir(is_id)["sirketler"]
    assert s[VKN_A]["durum"] == "hata" and "<zip>" in s[VKN_A]["ayrinti"] and str(c.depo.kok) not in s[VKN_A]["ayrinti"]
    assert s[VKN_B]["durum"] == "kuruldu"
    assert c.depo.kurulum_kaydi(VKN_A)["durum"] == "yarim"


def test_yarim_kalan_kurulum_yalniz_ayni_anahtarla_tekrar_denenir(ortam, tmp_path):
    c, o = ortam
    c.depo.kurulum_kaydet(VKN_A, "yarim", "musavir")
    o["kurulu"].add(VKN_A)  # şema yarım oluşmuş
    c.isle(_is_olustur(c, tmp_path, [VKN_A], etiket="musavir"))
    assert o["kurulanlar"] == [VKN_A]  # aynı anahtar: yeniden denendi

    o["kurulanlar"].clear()
    c.depo.kurulum_kaydet(VKN_B, "yarim", "baska-musavir")
    o["kurulu"].add(VKN_B)
    is_id = _is_olustur(c, tmp_path, [VKN_B], etiket="musavir")
    c.isle(is_id)
    assert o["kurulanlar"] == [] and c.depo.getir(is_id)["sirketler"][VKN_B]["durum"] == "atlandi"


def test_tamamlanmis_kurulum_tekrar_yuklenince_atlanir(ortam, tmp_path):
    c, o = ortam
    c.isle(_is_olustur(c, tmp_path, [VKN_A]))
    o["kurulu"].add(VKN_A)
    o["kurulanlar"].clear()
    is_id = _is_olustur(c, tmp_path, [VKN_A])
    c.isle(is_id)
    assert o["kurulanlar"] == [] and c.depo.getir(is_id)["sirketler"][VKN_A]["durum"] == "atlandi"


def test_yeniden_baslatmada_yarim_isler_hataya_cevrilir(ortam, tmp_path):
    c, _ = ortam
    is_id = _is_olustur(c, tmp_path, [VKN_A])
    assert c.depo.yarim_kalanlari_isaretle() == [is_id]
    j = c.depo.getir(is_id)
    assert j["durum"] == "bitti" and j["sirketler"][VKN_A]["durum"] == "hata"


def test_is_kimligi_yol_gezinmesine_izin_vermez(ortam):
    c, _ = ortam
    assert c.depo.getir("../../etc/passwd") is None


# ---------------- HTTP ----------------

def _istemci(monkeypatch, ortam, kimlik):
    c, _ = ortam
    monkeypatch.setattr(mo, "_calisan", c)
    monkeypatch.setattr(mo.api_anahtarlari if hasattr(mo, "api_anahtarlari") else __import__("api_anahtarlari"), "anahtari_dogrula",
                        lambda a: kimlik if a == "gecerli" else None)
    import app as entegrasyon_app

    return TestClient(entegrasyon_app.app)


YETKILI = IstemciKimligi("musavir", False, frozenset(), True)
YETKISIZ = IstemciKimligi("sade", False, frozenset({VKN_A}), False)
H = {"Authorization": "Bearer gecerli"}


def test_http_anahtarsiz_401_onboard_yetkisiz_403_ve_govde_okunmaz(monkeypatch, ortam):
    c, _ = ortam
    cl = _istemci(monkeypatch, ortam, YETKISIZ)
    assert cl.post(mo.ONBOARD_YOLU, content=b"x").status_code == 401
    r = cl.post(mo.ONBOARD_YOLU, content=_zip(_tam_sirket(VKN_A)), headers=H)
    assert r.status_code == 403
    assert not list((c.depo.kok / "yuklemeler").glob("*"))  # yetkisiz istekte diske hiçbir şey yazılmadı


def test_http_uctan_uca_yukle_isle_sorgula(monkeypatch, ortam):
    c, o = ortam
    cl = _istemci(monkeypatch, ortam, YETKILI)
    r = cl.post(mo.ONBOARD_YOLU, content=_zip({**_tam_sirket(VKN_A), **_tam_sirket(VKN_B)}), headers=H)
    assert r.status_code == 202, r.text
    j = r.json()
    assert j["sirketler"] == [VKN_A, VKN_B] and j["durum"] == "kuyrukta"
    c.isle(c.kuyruk.get_nowait())  # arka plan çalışanını elle sür
    d = cl.get(f"/musteri/isler/{j['is_id']}", headers=H).json()
    assert d["durum"] == "bitti" and {v: s["durum"] for v, s in d["sirketler"].items()} == {VKN_A: "kuruldu", VKN_B: "kuruldu"}
    assert "etiket" not in d and o["kapsam"] == [("musavir", VKN_A), ("musavir", VKN_B)]


def test_http_baska_anahtarin_isi_404(monkeypatch, ortam):
    c, _ = ortam
    cl = _istemci(monkeypatch, ortam, YETKILI)
    j = cl.post(mo.ONBOARD_YOLU, content=_zip(_tam_sirket(VKN_A)), headers=H).json()
    digeri = IstemciKimligi("baska", False, frozenset(), True)
    monkeypatch.setattr(__import__("api_anahtarlari"), "anahtari_dogrula", lambda a: digeri)
    assert cl.get(f"/musteri/isler/{j['is_id']}", headers=H).status_code == 404


@pytest.mark.parametrize("govde,kod", [(b"zip degil", 400), (_zip({"readme.txt": b"x"}), 400), (_zip({"../x/mizan.xlsx": b"x"}), 400)])
def test_http_gecersiz_zip_400_ve_temizlenir(monkeypatch, ortam, govde, kod):
    c, _ = ortam
    cl = _istemci(monkeypatch, ortam, YETKILI)
    assert cl.post(mo.ONBOARD_YOLU, content=govde, headers=H).status_code == kod
    assert not list((c.depo.kok / "yuklemeler").glob("*")) and not list((c.depo.kok / "dosyalar").glob("*"))


def test_http_boyut_siniri_413(monkeypatch, ortam):
    monkeypatch.setattr(mo, "ONBOARD_MAX_ZIP_BYTES", 100)
    cl = _istemci(monkeypatch, ortam, YETKILI)
    assert cl.post(mo.ONBOARD_YOLU, content=_zip(_tam_sirket(VKN_A)), headers=H).status_code == 413


def test_http_cok_bekleyen_is_429(monkeypatch, ortam):
    monkeypatch.setattr(mo, "MAX_BEKLEYEN_IS", 1)
    cl = _istemci(monkeypatch, ortam, YETKILI)
    assert cl.post(mo.ONBOARD_YOLU, content=_zip(_tam_sirket(VKN_A)), headers=H).status_code == 202
    assert cl.post(mo.ONBOARD_YOLU, content=_zip(_tam_sirket(VKN_B)), headers=H).status_code == 429


# ---------------- ilerleme yüzdesi ----------------

def test_yuzde_adim_adim_artar_ve_genel_yuzde_ortalamadir(ortam, tmp_path):
    c, _ = ortam
    veri = c.depo.olustur("musavir", [VKN_A, VKN_B], 0, [])
    assert veri["sirketler"][VKN_A]["yuzde"] == 0 and c.depo.getir(veri["is_id"])["yuzde"] == 0
    c.depo.guncelle(veri["is_id"], vkn=VKN_A, durum="calisiyor", adim="mizan", yuzde=50)
    j = c.depo.getir(veri["is_id"])
    assert j["sirketler"][VKN_A]["adim"] == "mizan" and j["yuzde"] == 25  # (50 + 0) / 2
    c.depo.guncelle(veri["is_id"], vkn=VKN_A, durum="kuruldu", yuzde=100)
    assert c.depo.getir(veri["is_id"])["yuzde"] == 50  # (100 + 0) / 2


def test_bitmis_is_yuzde_100_ve_hata_veren_sirketin_adimi_gorunur(ortam, tmp_path):
    c, o = ortam
    o["kur_hatasi"].add(VKN_A)
    is_id = _is_olustur(c, tmp_path, [VKN_A, VKN_B])
    c.isle(is_id)
    j = c.depo.getir(is_id)
    assert j["durum"] == "bitti" and j["yuzde"] == 100
    assert j["sirketler"][VKN_A]["durum"] == "hata" and j["sirketler"][VKN_A]["adim"] == "mizan"  # nerede kırıldığı belli
    assert j["sirketler"][VKN_A]["yuzde"] == 50 and j["sirketler"][VKN_B]["yuzde"] == 100


def test_atlanan_sirket_yuzde_100(ortam, tmp_path):
    c, o = ortam
    o["kurulu"].add(VKN_A)
    is_id = _is_olustur(c, tmp_path, [VKN_A])
    c.isle(is_id)
    assert c.depo.getir(is_id)["sirketler"][VKN_A]["yuzde"] == 100


def test_http_cevabinda_yuzde_alani_var(monkeypatch, ortam):
    c, _ = ortam
    cl = _istemci(monkeypatch, ortam, YETKILI)
    j = cl.post(mo.ONBOARD_YOLU, content=_zip(_tam_sirket(VKN_A)), headers=H).json()
    d = cl.get(f"/musteri/isler/{j['is_id']}", headers=H).json()
    assert d["yuzde"] == 0 and d["sirketler"][VKN_A]["yuzde"] == 0 and d["sirketler"][VKN_A]["adim"] is None
    c.isle(c.kuyruk.get_nowait())
    assert cl.get(f"/musteri/isler/{j['is_id']}", headers=H).json()["yuzde"] == 100


# ---------------- KAYITLI şirket güncelleme (2026-10-16) ----------------

@pytest.fixture
def ortam_g(tmp_path):
    """Çalışan + sahte `guncelle` (veritabanı/Ollama yok). o["sonuc"] ile güncelleme çıktısı ayarlanır."""
    depo = mo.IsDeposu(tmp_path / "veri")
    o = {"kurulanlar": [], "kapsam": [], "kurulu": {VKN_A}, "guncellenenler": [], "sonuc": {"degisiklik_var": True, "mod": "guncelleme"},
         "hata": None}

    def kur(vkn, dizin, ilerleme=None):
        o["kurulanlar"].append(vkn)
        return {"vkn": vkn}

    def guncelle(vkn, dizin, ilerleme, is_id, istemci):
        assert (dizin / "mizan.xlsx").exists()
        o["guncellenenler"].append((vkn, is_id, istemci))
        for adim, yuzde in (("nace", 25), ("mizan", 50), ("eslestirme", 75), ("rag", 100)):
            ilerleme(adim, yuzde)
        if o["hata"]:
            raise o["hata"](f"patladi {dizin}")
        return dict(o["sonuc"])

    c = mo.Calisan(depo, lambda v: v in o["kurulu"], kur, lambda e, v: o["kapsam"].append((e, v)) or True,
                   lambda i: depo.kok / "dosyalar" / i, guncelle=guncelle)
    return c, o


def _is_g(c, tmp_path, vknler, etiket="musavir", yetkisiz=None):
    veri = c.depo.olustur(etiket, vknler, 0, [], yetkisiz)
    z = tmp_path / f"{veri['is_id']}.zip"
    z.write_bytes(_zip({k: v for vkn in vknler for k, v in _tam_sirket(vkn).items()}))
    mo.zip_guvenli_ac(z, c.is_dizini(veri["is_id"]))
    return veri["is_id"]


def test_kayitli_sirket_yetkiliyse_guncellenir_degisiklik_varsa_guncellendi(ortam_g, tmp_path):
    c, o = ortam_g
    is_id = _is_g(c, tmp_path, [VKN_A])
    c.isle(is_id)
    s = c.depo.getir(is_id)["sirketler"][VKN_A]
    assert s["durum"] == "guncellendi" and s["yuzde"] == 100 and s["adim"] == "rag" and s["ozet"]["mod"] == "guncelleme"
    assert o["guncellenenler"] == [(VKN_A, is_id, "musavir")] and o["kurulanlar"] == []
    assert o["kapsam"] == []  # güncelleme kapsamı değiştirmez


def test_fark_yoksa_degismedi_ve_genel_yuzde_100(ortam_g, tmp_path):
    c, o = ortam_g
    o["sonuc"] = {"degisiklik_var": False, "mod": "guncelleme"}
    is_id = _is_g(c, tmp_path, [VKN_A])
    c.isle(is_id)
    j = c.depo.getir(is_id)
    assert j["sirketler"][VKN_A]["durum"] == "degismedi" and j["durum"] == "bitti" and j["yuzde"] == 100


def test_guncelleme_yetkisi_yoksa_atlanir_ve_veri_degismez(ortam_g, tmp_path):
    c, o = ortam_g
    is_id = _is_g(c, tmp_path, [VKN_A], yetkisiz=[VKN_A])
    c.isle(is_id)
    s = c.depo.getir(is_id)["sirketler"][VKN_A]
    assert s["durum"] == "atlandi" and "yetkisi yok" in s["ayrinti"]
    assert o["guncellenenler"] == [] and o["kurulanlar"] == []  # hiçbir şey çağrılmadı


def test_guncelleme_hatasi_yolu_sizdirmaz_ve_digerleri_devam_eder(ortam_g, tmp_path):
    c, o = ortam_g
    o["kurulu"].add(VKN_B)
    o["hata"] = RuntimeError
    is_id = _is_g(c, tmp_path, [VKN_A, VKN_B])
    c.isle(is_id)
    s = c.depo.getir(is_id)["sirketler"]
    assert all(x["durum"] == "hata" and "<zip>" in x["ayrinti"] and str(c.depo.kok) not in x["ayrinti"] for x in s.values())
    assert len(o["guncellenenler"]) == 2  # birinin hatası diğerini durdurmadı


def test_yeni_ve_kayitli_sirket_ayni_zipte(ortam_g, tmp_path):
    c, o = ortam_g
    is_id = _is_g(c, tmp_path, [VKN_A, VKN_B])  # A kayıtlı (güncellenir), B yeni (kurulur)
    c.isle(is_id)
    s = c.depo.getir(is_id)["sirketler"]
    assert s[VKN_A]["durum"] == "guncellendi" and s[VKN_B]["durum"] == "kuruldu"
    assert o["kurulanlar"] == [VKN_B] and o["kapsam"] == [("musavir", VKN_B)]  # yalnızca YENİ şirket kapsama eklenir


def test_yarim_kurulum_ayni_anahtarla_kurulum_olarak_tekrar_denenir_guncelleme_degil(ortam_g, tmp_path):
    c, o = ortam_g
    c.depo.kurulum_kaydet(VKN_A, "yarim", "musavir")
    c.isle(_is_g(c, tmp_path, [VKN_A]))
    assert o["kurulanlar"] == [VKN_A] and o["guncellenenler"] == []


def test_guncelleme_destegi_olmayan_calisan_eski_gibi_atlar(ortam, tmp_path):
    c, o = ortam  # guncelle=None
    o["kurulu"].add(VKN_A)
    is_id = _is_olustur(c, tmp_path, [VKN_A])
    c.isle(is_id)
    assert c.depo.getir(is_id)["sirketler"][VKN_A]["durum"] == "atlandi"


def test_http_yetkili_anahtar_kayitli_sirketi_gunceller_yetkisiz_olan_atlanir(monkeypatch, ortam_g):
    c, o = ortam_g
    o["kurulu"].add(VKN_B)
    kimlik = IstemciKimligi("musavir", False, frozenset({VKN_A}), True)  # yalnızca A'ya yetkili; B (kayıtlı) kapsam dışı
    cl = _istemci(monkeypatch, ortam_g, kimlik)
    r = cl.post(mo.ONBOARD_YOLU, content=_zip({**_tam_sirket(VKN_A), **_tam_sirket(VKN_B)}), headers=H)
    assert r.status_code == 202, r.text
    c.isle(c.kuyruk.get_nowait())
    d = cl.get(f"/musteri/isler/{r.json()['is_id']}", headers=H).json()
    assert d["sirketler"][VKN_A]["durum"] == "guncellendi" and d["sirketler"][VKN_B]["durum"] == "atlandi"
    assert d["guncelleme_yetkisiz"] == [VKN_B]
    assert [x[0] for x in o["guncellenenler"]] == [VKN_A]  # B'ye dokunulmadı


def test_http_tum_sirketler_anahtari_her_kayitli_sirketi_guncelleyebilir(monkeypatch, ortam_g):
    c, o = ortam_g
    cl = _istemci(monkeypatch, ortam_g, IstemciKimligi("yonetici", True, frozenset(), True))
    r = cl.post(mo.ONBOARD_YOLU, content=_zip(_tam_sirket(VKN_A)), headers=H)
    c.isle(c.kuyruk.get_nowait())
    assert cl.get(f"/musteri/isler/{r.json()['is_id']}", headers=H).json()["sirketler"][VKN_A]["durum"] == "guncellendi"
