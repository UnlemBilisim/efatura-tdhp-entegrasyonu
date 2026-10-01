"""mizan_excel_yukle.py::_mizan_satirlarini_oku - başlık satırının otomatik
bulunması (2026-09-30, gerçek bug'ın düzeltmesi). Önceden başlık satırı
`min_row=7` ile SABİTTİ - bu sadece Archive2/mizan.xlsx'in kendi formatına
(üstünde 5 boş satır) özgüydü. ONBOARDING-VERI-FORMATI.md dış ekibe
başlığın herhangi bir satırda olabileceğini ima ediyor ("veri, başlık
satırından sonraki satırdan itibaren okunur") - standart formatta (1. satır
başlık) bir mizan gönderilirse eski kod SESSİZCE 0 satır okuyordu, hiç
hata vermiyordu."""

import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mizan_excel_yukle import _mizan_satirlarini_oku


def _mizan_yaz(tmp_path, baslik_satiri, veriler, sutun_sirasi=("HESAP KODU", "HESAP ADI")):
    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(baslik_satiri - 1):
        ws.append([])
    ws.append(list(sutun_sirasi))
    for kod, ad in veriler:
        satir = [None, None]
        satir[sutun_sirasi.index("HESAP KODU")] = kod
        satir[sutun_sirasi.index("HESAP ADI")] = ad
        ws.append(satir)
    yol = tmp_path / "mizan.xlsx"
    wb.save(yol)
    return yol


class TestBaslikSatiriOtomatikBulma:
    def test_standart_format_1_satir_baslik(self, tmp_path):
        """Dış ekibin göndermesi beklenen standart format: başlık 1. satır."""
        yol = _mizan_yaz(tmp_path, 1, [("120.01.00001", "Test Müşteri")])
        sonuc = _mizan_satirlarini_oku(yol)
        assert sonuc == [("120.01.00001", "Test Müşteri")]

    def test_gercek_format_6_satir_baslik(self, tmp_path):
        """Archive2/mizan.xlsx'in kendi formatı - üstünde 5 boş satır."""
        yol = _mizan_yaz(tmp_path, 6, [("320.01.00001", "Test Tedarikçi")])
        sonuc = _mizan_satirlarini_oku(yol)
        assert sonuc == [("320.01.00001", "Test Tedarikçi")]

    def test_sutun_sirasi_ters_olsa_da_isme_gore_bulunur(self, tmp_path):
        """ONBOARDING-VERI-FORMATI.md sütun SIRASINI belirtmiyor - isme göre
        bulunmalı, pozisyona göre değil."""
        yol = _mizan_yaz(tmp_path, 1, [("340.01.00001", "Ters Sıra Testi")],
                          sutun_sirasi=("HESAP ADI", "HESAP KODU"))
        sonuc = _mizan_satirlarini_oku(yol)
        assert sonuc == [("340.01.00001", "Ters Sıra Testi")]

    def test_baslik_hic_bulunamazsa_acik_hata(self, tmp_path):
        """Sessizce 0 satır okumak yerine açık SystemExit fırlatmalı."""
        wb = openpyxl.Workbook()
        wb.active.append(["Yanlış Başlık", "Başka Sütun"])
        wb.active.append(["120.01.00001", "Bu satır hiç okunmamalı"])
        yol = tmp_path / "mizan.xlsx"
        wb.save(yol)
        with pytest.raises(SystemExit, match="HESAP KODU"):
            _mizan_satirlarini_oku(yol)

    def test_20_satirdan_sonraki_baslik_bulunamaz(self, tmp_path):
        """Makul bir arama sınırı var - normal bir mizanda başlık bundan
        aşağıda olmamalı, olursa sessizce yanlış okumak yerine açık hata."""
        yol = _mizan_yaz(tmp_path, 25, [("120.01.00001", "Çok Aşağıda")])
        with pytest.raises(SystemExit, match="HESAP KODU"):
            _mizan_satirlarini_oku(yol)


class TestSayisalHesapKoduAtlanir:
    def test_sayisal_kod_atlanir_metin_kod_kalir(self, tmp_path):
        """HESAP KODU hücresi Excel'de sayı biçimindeyse (örn. 320 metin
        değil sayı olarak girilmişse) bu satır sessizce kaybolmamalı -
        atlanır ama diğer, metin biçimindeki satırlar etkilenmez."""
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["HESAP KODU", "HESAP ADI"])
        ws.append(["120.01.00001", "Metin Kod"])
        ws.append([320, "Sayısal Kod"])
        yol = tmp_path / "mizan.xlsx"
        wb.save(yol)

        sonuc = _mizan_satirlarini_oku(yol)
        assert sonuc == [("120.01.00001", "Metin Kod")]

    def test_sayisal_kod_atlanirken_uyari_loglanir(self, tmp_path, caplog):
        """Sessiz veri kaybı olmamalı - hangi satırın neden atlandığı loglanır."""
        import logging

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["HESAP KODU", "HESAP ADI"])
        ws.append([320, "Sayısal Kod"])
        yol = tmp_path / "mizan.xlsx"
        wb.save(yol)

        with caplog.at_level(logging.WARNING):
            _mizan_satirlarini_oku(yol)
        assert any("hucresi metin degil" in r.message for r in caplog.records)

    def test_tamamen_bos_satir_sessizce_atlanir_uyarisiz(self, tmp_path, caplog):
        """Gerçekten boş bir satır (kod hiç girilmemiş) normal bir durum -
        bu, sayısal-tip hatasından ayrı ele alınmalı, uyarı loglamamalı."""
        import logging

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["HESAP KODU", "HESAP ADI"])
        ws.append([None, None])
        ws.append(["120.01.00001", "Geçerli Kod"])
        yol = tmp_path / "mizan.xlsx"
        wb.save(yol)

        with caplog.at_level(logging.WARNING):
            sonuc = _mizan_satirlarini_oku(yol)
        assert sonuc == [("120.01.00001", "Geçerli Kod")]
        assert not any("hucresi metin degil" in r.message for r in caplog.records)
