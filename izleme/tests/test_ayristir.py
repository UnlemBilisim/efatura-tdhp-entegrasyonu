import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ayristir  # noqa: E402


def istek_satiri(zaman, **k):
    kayit = {"yontem": "POST", "yol": "/musteri/onboard", "durum": 400, "sure_ms": 12, "ip": "10.0.0.5",
             "istemci": "orhan-gazi-basli", "request_id": "ab12", "hata": "Güvensiz dosya yolu: ../x"}
    kayit.update(k)
    return f'{zaman} ' + json.dumps({"zaman": "x", "seviye": "WARNING", "logger": "entegrasyon.istek",
                                      "mesaj": json.dumps(kayit, ensure_ascii=False), "request_id": "ab12"}, ensure_ascii=False)


def test_istek_gunlugu_satiri_hata_mesajiyla_okunur():
    r = ayristir.log_ayristir(istek_satiri("2026-10-16T06:52:04.123456789Z"))
    (i,) = r["istekler"]
    assert i["durum"] == 400 and i["hata"] == "Güvensiz dosya yolu: ../x" and i["istemci"] == "orhan-gazi-basli" and i["kaynak"] == "istek"


def test_saglik_kontrolleri_varsayilan_gizli_istenirse_gosterilir():
    ham = '2026-10-16T06:00:00Z INFO:     127.0.0.1:5000 - "GET /saglik HTTP/1.1" 200 OK\n' \
          '2026-10-16T06:00:01Z INFO:     172.18.0.1:5001 - "POST /fatura/isle HTTP/1.1" 401 Unauthorized'
    assert [i["yol"] for i in ayristir.log_ayristir(ham)["istekler"]] == ["/fatura/isle"]
    assert len(ayristir.log_ayristir(ham, saglik_goster=True)["istekler"]) == 2


def test_erisim_satiri_istek_gunlugu_ayni_olayi_kapsiyorsa_tekrarlanmaz():
    ham = istek_satiri("2026-10-16T06:52:04Z") + "\n" + \
        '2026-10-16T06:52:04Z INFO:     172.18.0.1:5001 - "POST /musteri/onboard HTTP/1.1" 400 Bad Request'
    r = ayristir.log_ayristir(ham)
    assert len(r["istekler"]) == 1 and r["istekler"][0]["kaynak"] == "istek"


def test_istek_gunlugu_olmayan_eski_surumde_erisim_satiri_yedek_olarak_gorunur():
    ham = '2026-10-16T06:52:04Z INFO:     172.18.0.1:5001 - "POST /musteri/onboard HTTP/1.1" 403 Forbidden'
    (i,) = ayristir.log_ayristir(ham)["istekler"]
    assert i["kaynak"] == "erisim" and i["durum"] == 403 and i["hata"] is None


def test_hata_loglari_ve_traceback_birlesir():
    ham = "\n".join([
        '2026-10-16T06:52:04Z ' + json.dumps({"zaman": "x", "seviye": "ERROR", "logger": "entegrasyon.onboard", "mesaj": "onboard basarisiz vkn=1", "request_id": "-"}),
        "2026-10-16T06:52:04Z Traceback (most recent call last):",
        '2026-10-16T06:52:04Z   File "/app/x.py", line 1, in f',
        "2026-10-16T06:52:04Z RuntimeError: patladi",
    ])
    (h,) = ayristir.log_ayristir(ham)["hatalar"]
    assert h["seviye"] == "ERROR" and "onboard basarisiz" in h["mesaj"] and any("RuntimeError" in s for s in h["iz"])


def test_bilgi_seviyesi_json_loglar_hata_akisina_girmez():
    ham = '2026-10-16T06:52:04Z ' + json.dumps({"seviye": "INFO", "logger": "httpx", "mesaj": "x"})
    assert ayristir.log_ayristir(ham)["hatalar"] == []


def test_isleri_ayristir_ardisik_json_ve_siralama():
    a = {"is_id": "a" * 32, "olusturulma": "2026-10-16T06:00:00+00:00", "durum": "bitti", "sirketler": {}}
    b = {"is_id": "b" * 32, "olusturulma": "2026-10-16T07:00:00+00:00", "durum": "calisiyor", "sirketler": {}}
    isler = ayristir.isleri_ayristir(json.dumps(a, indent=2) + "\n" + json.dumps(b))
    assert [j["is_id"][0] for j in isler] == ["b", "a"]
    assert ayristir.isleri_ayristir("bozuk veri") == []


def test_bozuk_satirlar_cokmeye_yol_acmaz():
    assert ayristir.log_ayristir("rastgele metin\n{bozuk json\n2026-10-16T06:00:00Z {bozuk")["istekler"] == []


def test_is_yuzdesi_diskte_yoksa_okunurken_hesaplanir():
    bitti = {"is_id": "a" * 32, "olusturulma": "x", "durum": "bitti", "sirketler": {"1": {"durum": "atlandi", "yuzde": 0}}}
    suruyor = {"is_id": "b" * 32, "olusturulma": "y", "durum": "calisiyor", "sirketler": {
        "1": {"durum": "kuruldu", "yuzde": 100}, "2": {"durum": "calisiyor", "yuzde": 25}}}
    isler = {j["is_id"][0]: j for j in ayristir.isleri_ayristir(json.dumps(bitti) + json.dumps(suruyor))}
    assert isler["a"]["yuzde"] == 100 and isler["b"]["yuzde"] == 62  # (100 + 25) / 2 = 62,5 → Python round() = 62 (sunucudaki hesapla aynı)
