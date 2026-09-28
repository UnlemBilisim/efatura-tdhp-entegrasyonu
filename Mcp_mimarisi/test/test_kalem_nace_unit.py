"""satir_bazli_kontrol_et() karar mantığı — test_kalem_nace.py'deki manuel
senaryoların DB'siz, sentetik faturalı pytest karşılıkları."""

import pytest

from efatura_kdv.kalem_nace_esleme import (
    SaticiNaceBilgisi,
    SaticiVknUyusmazligiHatasi,
    SatirKararTuru,
    satir_bazli_kontrol_et,
)
from efatura_kdv.ubl_parser import Fatura, FaturaKalemi, Party, VergiKirilimi

SATICI_VKN = "1111111111"


def _kdv(oran, istisna_kodu=None):
    return VergiKirilimi(oran=oran, vergi_tipi_kodu="0015", istisna_kodu=istisna_kodu)


def _fatura(kalem_kirilimlari=None, genel_kirilimlar=None, kalem_sayisi=1):
    kalemler = [
        FaturaKalemi(
            sira_no=str(i + 1),
            kalem_adi=f"Kalem {i + 1}",
            vergi_kirilimlari=list(kalem_kirilimlari or []),
        )
        for i in range(kalem_sayisi)
    ]
    return Fatura(
        fatura_no="TEST-001",
        uuid="test-uuid",
        satici=Party(vkn=SATICI_VKN),
        alici=Party(vkn="2222222222"),
        kalemler=kalemler,
        genel_vergi_kirilimlari=list(genel_kirilimlar or []),
    )


def _kontrol(fatura, nace_kodlari, oran_tablosu):
    satici = SaticiNaceBilgisi(vkn=SATICI_VKN, nace_kodlari=nace_kodlari)
    return satir_bazli_kontrol_et(fatura, satici, oran_tablosu)


def test_tek_nace_oran_havuzda_ise_uygun(oran_tablosu):
    sonuc = _kontrol(_fatura([_kdv(20.0)]), ["532009"], oran_tablosu)
    assert sonuc.genel_karar is SatirKararTuru.UYGUN
    assert "532009" in sonuc.satir_sonuclari[0].gerekce


def test_tek_nace_oran_havuzda_degilse_insan_incelemesi(oran_tablosu):
    sonuc = _kontrol(_fatura([_kdv(20.0)]), ["463304"], oran_tablosu)
    assert sonuc.genel_karar is SatirKararTuru.INSAN_INCELEMESI_GEREKLI


def test_coklu_nace_havuzu_birlestirilir(oran_tablosu):
    sonuc = _kontrol(_fatura([_kdv(10.0)]), ["532009", "463304"], oran_tablosu)
    satir = sonuc.satir_sonuclari[0]
    assert satir.karar is SatirKararTuru.UYGUN
    assert satir.izin_verilen_oranlar_havuzu == [1.0, 10.0, 20.0]
    assert "463304" in satir.gerekce


def test_noktali_nace_kodu_normalize_edilir(oran_tablosu):
    sonuc = _kontrol(_fatura([_kdv(20.0)]), ["53.20.09"], oran_tablosu)
    assert sonuc.genel_karar is SatirKararTuru.UYGUN


def test_bilinmeyen_nace_insan_incelemesi(oran_tablosu):
    sonuc = _kontrol(_fatura([_kdv(20.0)]), ["999999"], oran_tablosu)
    satir = sonuc.satir_sonuclari[0]
    assert satir.karar is SatirKararTuru.INSAN_INCELEMESI_GEREKLI
    assert "bulunamadı" in satir.gerekce


def test_satirda_oran_yoksa_tek_genel_oran_kullanilir(oran_tablosu):
    fatura = _fatura(genel_kirilimlar=[_kdv(20.0)], kalem_sayisi=2)
    sonuc = _kontrol(fatura, ["532009"], oran_tablosu)
    assert sonuc.genel_karar is SatirKararTuru.UYGUN
    assert all(s.beyan_edilen_oranlar == [20.0] for s in sonuc.satir_sonuclari)


def test_satirda_oran_yoksa_karisik_genel_oran_insan_incelemesi(oran_tablosu):
    fatura = _fatura(genel_kirilimlar=[_kdv(20.0), _kdv(10.0)])
    sonuc = _kontrol(fatura, ["532009"], oran_tablosu)
    satir = sonuc.satir_sonuclari[0]
    assert satir.karar is SatirKararTuru.INSAN_INCELEMESI_GEREKLI
    assert satir.beyan_edilen_oranlar == []


def test_kdv_disi_vergi_orani_dikkate_alinmaz(oran_tablosu):
    # Özel İletişim Vergisi (4081) %10'u KDV sanılırsa havuz dışı kalıp
    # yanlışlıkla insan incelemesine düşerdi.
    oiv = VergiKirilimi(oran=10.0, vergi_tipi_kodu="4081")
    sonuc = _kontrol(_fatura([_kdv(20.0), oiv]), ["532009"], oran_tablosu)
    assert sonuc.genel_karar is SatirKararTuru.UYGUN


def test_genel_istisna_kodu_oran_uyusmazligini_cozer(oran_tablosu):
    fatura = _fatura(genel_kirilimlar=[_kdv(0.0, istisna_kodu="301")])
    sonuc = _kontrol(fatura, ["532009"], oran_tablosu)
    satir = sonuc.satir_sonuclari[0]
    assert satir.karar is SatirKararTuru.UYGUN
    assert "301" in satir.gerekce


def test_dolgu_istisna_kodu_sadece_not_ekler(oran_tablosu):
    fatura = _fatura(genel_kirilimlar=[_kdv(0.0, istisna_kodu="351")])
    sonuc = _kontrol(fatura, ["532009"], oran_tablosu)
    satir = sonuc.satir_sonuclari[0]
    assert satir.karar is SatirKararTuru.INSAN_INCELEMESI_GEREKLI
    assert "351" in satir.gerekce


def test_tek_satir_incelemeye_duserse_fatura_geneli_de_duser(oran_tablosu):
    fatura = _fatura(kalem_sayisi=0)
    fatura.kalemler = [
        FaturaKalemi(sira_no="1", kalem_adi="Uygun", vergi_kirilimlari=[_kdv(20.0)]),
        FaturaKalemi(sira_no="2", kalem_adi="Uyumsuz", vergi_kirilimlari=[_kdv(1.0)]),
    ]
    sonuc = _kontrol(fatura, ["532009"], oran_tablosu)
    assert [s.karar for s in sonuc.satir_sonuclari] == [
        SatirKararTuru.UYGUN,
        SatirKararTuru.INSAN_INCELEMESI_GEREKLI,
    ]
    assert sonuc.genel_karar is SatirKararTuru.INSAN_INCELEMESI_GEREKLI


def test_satici_vkn_uyusmazligi_durdurulur(oran_tablosu):
    satici = SaticiNaceBilgisi(vkn="9999999999", nace_kodlari=["532009"])
    with pytest.raises(SaticiVknUyusmazligiHatasi):
        satir_bazli_kontrol_et(_fatura([_kdv(20.0)]), satici, oran_tablosu)
