"""Karar izi (core/iz.py + core/single.py'deki kancalar): gelen veri nasıl işlendi, KİM karar verdi, NEDEN, hangi istem/kural (2026-10-19, kullanıcı isteği).
İzin iki temel garantisi: (1) toplanması sonucu DEĞİŞTİRMEZ, (2) hatası işlemi BOZMAZ."""

from unittest.mock import patch

import core.single as single
from core.iz import KararIzi, MAX_METIN
from test_single import OWN_VKN, SAMPLE_XML, _balanced_response

SPEC = {"provider": "ollama", "model": "test-model", "base_url": "http://x", "api_key_env": None, "label": "ollama:test-model"}
MIZAN = {
    "191": [("191.05.00005", "%20 5/10 Tevkifatli KDV")],
    "770": [("770.01.00027", "Diger Cesitli Giderler")],
    "320": [("320.01.00018", "Baska Firma Insaat Nakliyat Ltd Sti"), ("320.01.00019", "Bir Digeri Ticaret A.S.")],
}


def _calistir(monkeypatch, secim_cevabi, iz=None, tekrar=1):
    monkeypatch.setattr(single, "get_alt_kirilimlar", lambda tenant_vkn=None: MIZAN)
    cevaplar = [_balanced_response()] + [(secim_cevabi, 0.2, None)] * tekrar
    with patch.object(single, "call_model", side_effect=cevaplar):
        return single.predict_single_invoice(
            SAMPLE_XML, model=SPEC, own_vkn=OWN_VKN, rag=False, self_correct=False, tevkifat_hint=False, iade_hint=False, alt_kirilim=True, iz=iz,
        )


class TestKararIzi:
    def test_temel_alanlar_ve_gecersiz_karar_veren_sisteme_duser(self):
        iz = KararIzi()
        iz.ekle("t", "Başlık", "llm", sonuc="s", neden="n", a=1)
        iz.ekle("t2", "B2", "bilinmeyen")
        a = iz.to_dict()["adimlar"]
        assert [x["sira"] for x in a] == [1, 2] and a[0]["karar_veren"] == "llm" and a[0]["detay"] == {"a": 1} and a[1]["karar_veren"] == "sistem"

    def test_json_guvenli_ve_uzun_metin_kesilir(self):
        import json

        iz = KararIzi()
        iz.ekle("t", "b", "sistem", nesne=object(), kume={3, 1, 2}, uzun="x" * (MAX_METIN + 500), anahtar_sayi={1: "a"})
        d = iz.to_dict()
        json.dumps(d)  # serileştirilebilir olmalı
        det = d["adimlar"][0]["detay"]
        assert det["kume"] == [1, 2, 3] and det["uzun"].endswith("toplam %d karakter]" % (MAX_METIN + 500)) and det["anahtar_sayi"] == {"1": "a"}

    def test_ekle_hatasi_yutulur(self):
        class Bozuk:
            def __str__(self):
                raise RuntimeError("str patladı")

        iz = KararIzi()
        iz.ekle("t", "b", "sistem", x=Bozuk())  # istisna FIRLATMAMALI
        assert iz.adimlar == []


class TestIzTahminiDegistirmez:
    SECIM = '{"secimler": [{"ana_kod": "191", "alt_kod": "191.05.00005"}, {"ana_kod": "770", "alt_kod": "770.01.00027"}]}'

    def test_iz_toplamak_sonucu_degistirmez(self, monkeypatch):
        izsiz = _calistir(monkeypatch, self.SECIM)
        izli = _calistir(monkeypatch, self.SECIM, iz=KararIzi())
        for alan in ("entries", "balanced", "borc_toplam", "alacak_toplam", "self_corrected", "error"):
            assert izsiz[alan] == izli[alan]

    def test_bozuk_toplayici_islemi_bozmaz(self, monkeypatch):
        class Bozuk:
            def ekle(self, *a, **k):
                raise RuntimeError("iz patladı")

        sonuc = _calistir(monkeypatch, self.SECIM, iz=Bozuk())
        assert {e["account_code"] for e in sonuc["entries"]} == {"191.05.00005", "770.01.00027", "320"}


class TestIzAdimlari:
    SECIM = '{"secimler": [{"ana_kod": "191", "alt_kod": "191.05.00005: %20 5/10 Tevkifatli KDV"}, {"ana_kod": "770", "alt_kod": "770.99.99999"}]}'

    def _adimlar(self, monkeypatch, secim=SECIM, tekrar=2):
        iz = KararIzi()
        _calistir(monkeypatch, secim, iz=iz, tekrar=tekrar)
        return iz.to_dict()["adimlar"]

    def test_akis_sirasi_ve_karar_verenler(self, monkeypatch):
        a = self._adimlar(monkeypatch)
        turler = [x["tur"] for x in a]
        assert turler[:4] == ["fatura_ozeti", "rag", "ipuclari", "ana_llm"] and "alt_kirilim_llm" in turler
        kv = {x["tur"]: x["karar_veren"] for x in a}
        assert kv["fatura_ozeti"] == "sistem" and kv["rag"] == "rag" and kv["ipuclari"] == "kural" and kv["ana_llm"] == "llm" and kv["alt_kirilim_llm"] == "llm"

    def test_ana_llm_istemleri_ve_ham_cevap_kaydedilir(self, monkeypatch):
        ana = next(x for x in self._adimlar(monkeypatch) if x["tur"] == "ana_llm")
        d = ana["detay"]
        assert d["sistem_istemi"] == single.SYSTEM_PROMPT
        assert "ORNEK TEDARIKCI" in d["kullanici_istemi"].upper()  # modele giden istemde faturanın karşı tarafı var
        assert d["ham_cevap"] == _balanced_response()[0] and d["model"] == "test-model"
        assert "191 Borc" in ana["sonuc"] and "320 Alacak" in ana["sonuc"]

    def test_cari_adim_modele_sorulmadigini_ve_aday_nedenlerini_yazar(self, monkeypatch):
        cari = next(x for x in self._adimlar(monkeypatch) if x["tur"] == "alt_kirilim" and x["baslik"].startswith("320"))
        assert cari["karar_veren"] == "kural" and "bulunamadı" in cari["sonuc"]
        assert "Modele sorulmadı" in cari["neden"]
        adaylar = cari["detay"]["adaylar"]
        assert adaylar and all({"kod", "ad", "benzerlik", "kabul", "neden"} <= set(a) for a in adaylar) and all(a["kabul"] is False for a in adaylar)
        assert any(a["neden"].startswith("Ret") for a in adaylar)

    def test_llm_adimi_istemi_denemeleri_ve_degerlendirmeyi_kaydeder(self, monkeypatch):
        llm = next(x for x in self._adimlar(monkeypatch) if x["tur"] == "alt_kirilim_llm")
        d = llm["detay"]
        assert d["sistem_istemi"] == single.ALT_KIRILIM_SYSTEM_PROMPT and "191.05.00005" in d["kullanici_istemi"] and "320.01.00018" not in d["kullanici_istemi"]
        assert set(d["modele_sorulan_kodlar"]) == {"191", "770"}  # cari kod modele sorulmaz
        deneme = d["denemeler"][0]
        assert deneme["ham_cevap"] == self.SECIM
        degerlendirme = {x["ana_kod"]: x for x in deneme["degerlendirme"]}
        assert degerlendirme["191"]["temizlenen"] == "191.05.00005" and degerlendirme["191"]["sonuc"].startswith("KABUL")
        assert degerlendirme["770"]["sonuc"].startswith("REDDEDİLDİ")  # uydurma kod

    def test_alt_kirilim_kodu_adimlari_kim_karar_verdi(self, monkeypatch):
        a = {x["baslik"]: x for x in self._adimlar(monkeypatch) if x["tur"] == "alt_kirilim"}
        assert a["191 alt kırılımı"]["karar_veren"] == "llm" and "191.05.00005" in a["191 alt kırılımı"]["sonuc"]
        assert a["770 alt kırılımı"]["karar_veren"] == "kural" and "çözülemedi" in a["770 alt kırılımı"]["sonuc"]

    def test_rag_kapali_adimi_vardir(self, monkeypatch):
        rag = next(x for x in self._adimlar(monkeypatch) if x["tur"] == "rag")
        assert rag["sonuc"] == "kapalı"

    def test_kdv_oran_duzeltmesi_izde_gorunur(self, monkeypatch):
        """Fatura %10 KDV'li; model %20'yi (391.20) seçiyor → kural aynı türde %10'a (391.10) çeviriyor. İz bunu 'kim, neden' ile yazmalı."""
        xml = SAMPLE_XML.replace("Katma Deger Vergisi", "KDV").replace("<cbc:Percent>20</cbc:Percent>", "<cbc:Percent>10</cbc:Percent>")
        monkeypatch.setattr(single, "get_alt_kirilimlar", lambda tenant_vkn=None: {"391": [("391.10", "%10 Hesaplanan KDV"), ("391.20", "%20 Hesaplanan KDV")]})
        iz = KararIzi()
        entries = '{"entries": [{"account_code": "391", "amount": 100.0, "dc": "Alacak"}, {"account_code": "120", "amount": 100.0, "dc": "Borc"}]}'
        secim = '{"secimler": [{"ana_kod": "391", "alt_kod": "391.20"}]}'
        with patch.object(single, "call_model", side_effect=[(entries, 0.1, None), (secim, 0.1, None)]):
            sonuc = single.predict_single_invoice(xml, model=SPEC, own_vkn=OWN_VKN, rag=False, self_correct=False, alt_kirilim=True, iz=iz)
        assert "391.10" in {e["account_code"] for e in sonuc["entries"]}
        adimlar = iz.to_dict()["adimlar"]
        deg = next(x for x in adimlar if x["tur"] == "alt_kirilim_llm")["detay"]["denemeler"][0]["degerlendirme"][0]
        assert deg["sonuc"].startswith("KABUL") and deg["fatura_kdv_oranlari"] == [10]
        assert deg["kdv_oran_duzeltmesi"].startswith("391.20 → 391.10")
        kdv = next(x for x in adimlar if x["tur"] == "alt_kirilim" and x["baslik"].startswith("391"))
        assert kdv["karar_veren"] == "llm" and "oranı faturadaki orana göre kural tarafından düzeltildi" in kdv["neden"]


class TestCariAdayNedenleri:
    def test_ret_nedeni_ayirt_edici_kelimeyi_soyler(self):
        r = single._cari_esle_ayrintili("FARUK KARAGÖZ", [("120.1", "FARUK KARAMAN"), ("120.2", "HAKAN KARAGÖZ")])
        assert r["durum"] == "eslesmedi" and len(r["adaylar_ayrintili"]) == 2
        neden = {a["kod"]: a["neden"] for a in r["adaylar_ayrintili"]}
        assert "KARAGOZ" in neden["120.1"] and "KARAMAN" in neden["120.1"] and neden["120.1"].startswith("Ret")
        assert "FARUK" in neden["120.2"]

    def test_hukuki_form_celiskisi_nedeni(self):
        r = single._cari_esle_ayrintili("Endüstriyel Elektrik Ltd.Şti.", [("320.1", "ENDÜSTRİYEL ELEKTRİK A.Ş.")])
        assert "hukuki form farklı" in r["adaylar_ayrintili"][0]["neden"]

    def test_kabul_nedeni_hangi_kuralin_saydigini_soyler(self):
        r = single._cari_esle_ayrintili("TAHA KALIP MAKİNA OTOMOTİV YEDEK PARÇA İTHALAT İHRACAT SANAYİ TİCARET LİMİTED ŞİRKETİ", [("320.9", "TAHA KALIP MAKİNA OTOM.LTD.ŞTİ.")])
        assert r["durum"] == "eslesti" and r["adaylar_ayrintili"][0]["kabul"] is True and "kesilmiş" in r["adaylar_ayrintili"][0]["neden"]
        r2 = single._cari_esle_ayrintili("MEHMET ALİ ŞAHİN - ŞAHİN TAKOGRAF", [("120.5", "MEHMET ALİ ŞAHİN")])
        assert "ayıraçtan" in r2["adaylar_ayrintili"][0]["neden"]
