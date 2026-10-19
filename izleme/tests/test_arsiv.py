"""Panelin arşiv tarafı: kimlik/dosya adı beyaz listesi (uzak komuta ulaşan tek kullanıcı girdisi), meta ayrıştırma,
panel sunucusunun uç noktaları (sahte kaynakla — SSH/Docker gerekmez)."""

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arsiv  # noqa: E402
import panel  # noqa: E402

RID = "0123456789ab"
IS_ID = "a" * 32


# ---------------- doğrulama (güvenlik) ----------------

@pytest.mark.parametrize("kotu", [
    "", "-", "../x", "0123456789ab/../../etc", "ABCDEF123456", "0123456789a", "x" * 33, "0123456789ab; rm -rf /",
    "0123456789ab\n", "0123456789ab ", "$(id)", "`id`", None, 123, ["0123456789ab"],
])
def test_gecersiz_kimlik_reddedilir(kotu):
    assert not arsiv.gecerli_id(kotu)
    with pytest.raises(ValueError):
        arsiv.dosya_yolu(kotu, "gelen.zip")


@pytest.mark.parametrize("kotu", ["", "../meta.json", "/etc/passwd", "gelen.zip; id", "gelen.zip\n", "GELEN.ZIP", "sonuclar.jsonl", "meta.json/", None])
def test_gecersiz_dosya_adi_reddedilir(kotu):
    assert not arsiv.gecerli_dosya(kotu)
    with pytest.raises(ValueError):
        arsiv.dosya_yolu(RID, kotu)


def test_gecerli_yol():
    assert arsiv.dosya_yolu(RID, "gelen.zip") == f"/app/data/onboarding/arsiv/{RID}/gelen.zip"
    assert all(arsiv.dosya_yolu(RID, ad).startswith(arsiv.ARSIV_DIZINI + "/") for ad in arsiv.IZINLI_DOSYALAR)


def test_toplu_sonuc_yolu_yalniz_dogrulanmis_toplu_is_icin():
    assert arsiv.toplu_sonuc_yolu({"tip": "fatura_toplu", "is_id": IS_ID}) == f"/app/data/onboarding/toplu/{IS_ID}/sonuclar.jsonl"
    for meta in ({"tip": "musteri_onboard", "is_id": IS_ID}, {"tip": "fatura_toplu", "is_id": "../x"}, {"tip": "fatura_toplu"},
                 {"tip": "fatura_toplu", "is_id": IS_ID + "/.."}, None):
        with pytest.raises(ValueError):
            arsiv.toplu_sonuc_yolu(meta)


def test_indirme_adi_yalniz_guvenli_karakter():
    ad = arsiv.indirme_adi({"tip": 'x";\r\nSet-Cookie: a', "zaman": "2026-10-19T09:52:08+00:00"}, RID, "gelen.zip")
    assert all(c.isalnum() or c in "_.-" for c in ad) and ad.endswith("gelen.zip") and "\n" not in ad and '"' not in ad
    assert arsiv.indirme_adi(None, RID, "istek.xml") == "istek_01234567_istek.xml"


# ---------------- meta ayrıştırma ----------------

def _meta(rid, zaman, **k):
    return json.dumps({"request_id": rid, "zaman": zaman, "tip": "fatura_isle", **k}, indent=1, ensure_ascii=False)


def test_meta_ayristir_cok_satirli_kayitlar_yeniden_eskiye():
    ham = _meta("a" * 12, "2026-10-19T09:00:00+00:00") + "\n" + _meta("b" * 12, "2026-10-19T10:00:00+00:00", durum=400) + "\n"
    assert [k["request_id"] for k in arsiv.meta_ayristir(ham)] == ["b" * 12, "a" * 12]


def test_bozuk_kayit_digerlerini_oldurmez():
    ham = _meta("a" * 12, "2026-10-19T09:00:00+00:00") + "\n{\"request_id\": \"bozuk\n" + _meta("c" * 12, "2026-10-19T11:00:00+00:00") + "\n"
    assert [k["request_id"] for k in arsiv.meta_ayristir(ham)] == ["c" * 12, "a" * 12]


def test_gecersiz_kimlikli_ya_da_nesne_olmayan_kayitlar_atilir():
    ham = _meta("../../etc", "2026-10-19T09:00:00+00:00") + "\n[1,2]\n" + _meta("a" * 12, "2026-10-19T09:00:00+00:00")
    assert [k["request_id"] for k in arsiv.meta_ayristir(ham)] == ["a" * 12]


def test_ozet_yalniz_izinli_dosyalari_ve_bilinen_alanlari_dondurur():
    o = arsiv.ozet({"request_id": RID, "dosyalar": {"gelen.zip": 5, "meta.json": 1, "x/../y": 9}, "gizli_alan": "x", "zip_icerik": [1]})
    assert o["dosyalar"] == {"gelen.zip": 5} and "gizli_alan" not in o and "zip_icerik" not in o


# ---------------- panel sunucusu (sahte kaynak) ----------------

class SahteKaynak(panel.Kaynak):
    def __init__(self, tmp_path):
        super().__init__(True, "sahte", "sahte-container")
        self.tmp, self.cagrilar = tmp_path, []
        self.metalar = {
            RID: {"request_id": RID, "zaman": "2026-10-19T09:52:08+00:00", "tip": "musteri_onboard", "istemci": "orhan", "ip": "10.0.0.5",
                  "durum": 202, "is_id": IS_ID, "dosyalar": {"gelen.zip": 11, "cevap.json": 40}, "zip_icerik": [{"ad": "123/mizan.xlsx", "bayt": 9}],
                  "zip_dosya_sayisi": 1},
            "b" * 12: {"request_id": "b" * 12, "zaman": "2026-10-19T08:00:00+00:00", "tip": "fatura_toplu", "durum": 202, "is_id": "c" * 32,
                       "dosyalar": {"gelen.zip": 5}},
        }
        self.dosyalar = {arsiv.dosya_yolu(RID, "gelen.zip"): b"ZIPICERIK!!",
                         arsiv.dosya_yolu(RID, "cevap.json"): b'{"is_id": "' + IS_ID.encode() + b'"}',
                         arsiv.dosya_yolu("b" * 12, "gelen.zip"): b"12345",
                         f"{arsiv.TOPLU_DIZINI}/{'c' * 32}/sonuclar.jsonl": b'{"sira": 1, "dosya": "a.xml", "sonuc": "hazir"}\n{"sira": 2, "sonuc": "hata", "hata": "x"}\n{yarim'}
        for rid, m in self.metalar.items():
            self.dosyalar[arsiv.dosya_yolu(rid, "meta.json")] = json.dumps(m).encode()
        self.dosyalar[f"{arsiv.ISLER_DIZINI}/{IS_ID}.json"] = json.dumps({"is_id": IS_ID, "durum": "bitti", "olusturulma": "2026-10-19T09:52:08+00:00", "sirketler": {}}).encode()
        self.dosyalar[f"{arsiv.TOPLU_DIZINI}/{'c' * 32}/is.json"] = json.dumps({"is_id": "c" * 32, "durum": "bitti", "toplam": 2, "tamamlanan": 2}).encode()

    def arsiv_metalari(self, adet=500):
        return "\n".join(json.dumps(m, indent=1) for m in self.metalar.values())

    def metin_oku(self, yol, bayt):
        self.cagrilar.append(("oku", yol))
        if yol not in self.dosyalar:
            raise RuntimeError("dosya yok")
        return self.dosyalar[yol][:bayt].decode("utf-8", "replace")

    def dosya_ac(self, yol):
        self.cagrilar.append(("ac", yol))
        icerik = self.dosyalar.get(yol)
        if icerik is None:
            return subprocess.Popen(["sh", "-c", "echo yok >&2; exit 1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p = self.tmp / "ic.bin"
        p.write_bytes(icerik)
        return subprocess.Popen(["cat", str(p)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def istek_loglari(self, baslangic, bitis):
        self.cagrilar.append(("log", baslangic, bitis))
        satir = json.dumps({"zaman": "x", "seviye": "INFO", "logger": "entegrasyon.istek", "request_id": RID,
                            "mesaj": json.dumps({"yontem": "POST", "yol": "/musteri/onboard", "durum": 202, "sure_ms": 5, "request_id": RID})})
        baska = json.dumps({"zaman": "x", "seviye": "INFO", "logger": "entegrasyon.istek", "request_id": "f" * 12,
                            "mesaj": json.dumps({"yontem": "GET", "yol": "/baska", "durum": 200, "request_id": "f" * 12})})
        return f"2026-10-19T09:52:08.1Z {satir}\n2026-10-19T09:52:09.1Z {baska}\n"


@pytest.fixture
def sunucu(tmp_path):
    kaynak = SahteKaynak(tmp_path)
    srv = panel.sunucu_olustur(kaynak, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield kaynak, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _al(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_liste_yeniden_eskiye_ve_dosya_listesiyle(sunucu):
    _, url = sunucu
    kod, _, govde = _al(url + "/api/arsiv")
    j = json.loads(govde)
    assert kod == 200 and j["toplam"] == 2 and [k["request_id"] for k in j["kayitlar"]] == [RID, "b" * 12]
    assert j["kayitlar"][0]["dosyalar"] == {"gelen.zip": 11, "cevap.json": 40}


def test_detay_meta_cevap_is_ve_yalniz_o_istegin_loglari(sunucu):
    kaynak, url = sunucu
    kod, _, govde = _al(f"{url}/api/arsiv/detay?id={RID}")
    j = json.loads(govde)
    assert kod == 200 and j["meta"]["istemci"] == "orhan" and j["onizleme"]["cevap.json"]["metin"].startswith('{"is_id"')
    assert j["is"]["is"]["durum"] == "bitti" and j["is"]["is"]["yuzde"] == 100  # iş dosyasında yüzde yok; panel hesaplar
    assert [i["yol"] for i in j["log"]["istekler"]] == ["/musteri/onboard"]  # başka isteğin satırı süzüldü
    log_cagrisi = next(c for c in kaynak.cagrilar if c[0] == "log")
    assert log_cagrisi[1] < log_cagrisi[2]


def test_detay_toplu_is_sonuclar_yarim_satiri_atar(sunucu):
    _, url = sunucu
    j = json.loads(_al(f"{url}/api/arsiv/detay?id={'b' * 12}")[2])
    assert [r["sira"] for r in j["is"]["sonuclar"]] == [1, 2] and j["is"]["is"]["durum"] == "bitti" and j["is"]["is"]["yuzde"] == 100


@pytest.mark.parametrize("kotu", ["", "../x", "ABC", "0123456789ab;id", "0123456789ab%0a", "%2e%2e%2f"])
def test_detay_gecersiz_kimlik_400_ve_uzak_komut_calismaz(sunucu, kotu):
    kaynak, url = sunucu
    kod, _, _ = _al(f"{url}/api/arsiv/detay?id={kotu}")
    assert kod == 400 and not kaynak.cagrilar


@pytest.mark.parametrize("ad", ["../meta.json", "/etc/passwd", "gelen.zip;id", "baska.txt", "", "GELEN.ZIP"])
def test_indir_gecersiz_dosya_adi_400_ve_uzak_komut_calismaz(sunucu, ad):
    kaynak, url = sunucu
    kod, _, _ = _al(f"{url}/api/arsiv/indir?id={RID}&ad={urllib.request.quote(ad)}")
    assert kod == 400 and not kaynak.cagrilar


def test_indir_gecersiz_kimlik_400(sunucu):
    kaynak, url = sunucu
    assert _al(f"{url}/api/arsiv/indir?id=../../x&ad=gelen.zip")[0] == 400 and not kaynak.cagrilar


def test_indir_dosyayi_eksiksiz_ve_guvenli_basliklarla_verir(sunucu):
    _, url = sunucu
    kod, h, govde = _al(f"{url}/api/arsiv/indir?id={RID}&ad=gelen.zip")
    assert kod == 200 and govde == b"ZIPICERIK!!" and h["Content-Length"] == "11"
    assert h["Content-Disposition"].startswith('attachment; filename="musteri_onboard_') and h["Content-Disposition"].endswith('gelen.zip"')
    assert h["X-Content-Type-Options"] == "nosniff" and h["Content-Type"] == "application/octet-stream" and h["Content-Security-Policy"] == "sandbox"


def test_indir_olmayan_dosya_404(sunucu):
    kaynak, url = sunucu
    kaynak.dosyalar.pop(arsiv.dosya_yolu(RID, "gelen.zip"))
    kod, _, govde = _al(f"{url}/api/arsiv/indir?id={RID}&ad=gelen.zip")
    assert kod == 404 and "bulunamadı" in json.loads(govde)["hata"]


def test_indir_toplu_sonuclari_yalniz_toplu_istek_icin(sunucu):
    _, url = sunucu
    kod, _, govde = _al(f"{url}/api/arsiv/indir?id={'b' * 12}&ad=sonuclar.jsonl")
    assert kod == 200 and govde.startswith(b'{"sira": 1')
    assert _al(f"{url}/api/arsiv/indir?id={RID}&ad=sonuclar.jsonl")[0] == 400  # onboard isteğinin toplu sonucu yok


def test_uzak_komut_yalniz_dogrulanmis_yollarla_kurulur(monkeypatch):
    """Gerçek Kaynak (SSH): komut dizgesi, doğrulanmış sabit yol + hex kimlikten başka bir şey içermez."""
    gorulen = []
    monkeypatch.setattr(subprocess, "run", lambda tam, **k: gorulen.append(tam) or subprocess.CompletedProcess(tam, 0, "{}", ""))
    k = panel.Kaynak(False, "u@h", "kap")
    k.metin_oku(arsiv.dosya_yolu(RID, "cevap.json"), 100)
    assert gorulen[0][-1] == f"docker exec kap head -c 100 /app/data/onboarding/arsiv/{RID}/cevap.json"
    with pytest.raises(ValueError):
        arsiv.dosya_yolu(RID + "; id", "cevap.json")
