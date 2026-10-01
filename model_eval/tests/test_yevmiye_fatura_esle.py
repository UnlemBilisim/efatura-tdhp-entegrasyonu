"""scripts/yevmiye_fatura_esle.py::esle_ve_uret() - onboarding'in kalbi olan
fatura XML + yevmiye eşleştirme akışı (2026-10-01, TODO.md "Detaylı test
yazılacak" maddesi için - önceden bu akış sadece elle, geçici script'lerle
doğrulanmıştı, kalıcı pytest testi yoktu).

4 ana senaryo: mutlu yol, yanlış own_vkn (direction_uncertain), eksik sütun,
eşleşmeyen fatura no - TODO.md'de bu dört senaryo açıkça isteniyordu."""

import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from yevmiye_fatura_esle import esle_ve_uret

OWN_VKN = "6677889900"
KARSI_VKN = "1234509876"

_XML_SABLON = """<?xml version="1.0" encoding="utf-8"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>{fatura_no}</cbc:ID>
  <cbc:UUID>{uuid}</cbc:UUID>
  <cbc:IssueDate>2026-09-15</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="VKN">{satici_vkn}</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>Satici Test A.S.</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="VKN">{alici_vkn}</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>Alici Test A.S.</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="TRY">100.00</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="TRY">1000.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="TRY">100.00</cbc:TaxAmount>
      <cbc:Percent>10.00</cbc:Percent>
      <cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="TRY">1000.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="TRY">1000.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="TRY">1100.00</cbc:TaxInclusiveAmount>
    <cbc:AllowanceTotalAmount currencyID="TRY">0.00</cbc:AllowanceTotalAmount>
    <cbc:PayableAmount currencyID="TRY">1100.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">1.000000</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="TRY">1000.00</cbc:LineExtensionAmount>
    <cac:TaxTotal>
      <cbc:TaxAmount currencyID="TRY">100.00</cbc:TaxAmount>
      <cac:TaxSubtotal>
        <cbc:TaxableAmount currencyID="TRY">1000.00</cbc:TaxableAmount>
        <cbc:TaxAmount currencyID="TRY">100.00</cbc:TaxAmount>
        <cbc:Percent>10.00</cbc:Percent>
        <cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>
      </cac:TaxSubtotal>
    </cac:TaxTotal>
    <cac:Item><cbc:Name>Test Urun</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="TRY">1000.000000</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>"""


def _xml_yaz(dizin, fatura_no, satici_vkn=OWN_VKN, alici_vkn=KARSI_VKN):
    icerik = _XML_SABLON.format(fatura_no=fatura_no, uuid=f"uuid-{fatura_no}", satici_vkn=satici_vkn, alici_vkn=alici_vkn)
    (dizin / f"{fatura_no}.xml").write_text(icerik, encoding="utf-8")


def _yevmiye_yaz(dizin, satirlar, dosya_adi="yevmiye.xlsx", basliklar=("fatura_no", "hesap_kodu", "hesap_adi", "borc_alacak", "tutar")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(basliklar))
    for satir in satirlar:
        ws.append(list(satir))
    yol = dizin / dosya_adi
    wb.save(yol)
    return yol


class TestMutluYol:
    def test_eslesen_fatura_json_uretir(self, tmp_path):
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000001")

        yevmiye = _yevmiye_yaz(tmp_path, [
            ("TST2026000000001", "600.01.00001", "Satislar", "Alacak", "1000.00"),
            ("TST2026000000001", "391.01.00010", "%10 Hesaplanan KDV", "Alacak", "100.00"),
            ("TST2026000000001", "120.01.00001", "Alici Test A.S.", "Borc", "1100.00"),
        ])

        cikti = tmp_path / "jsons"
        ozet = esle_ve_uret(OWN_VKN, faturalar, yevmiye, cikti)

        assert ozet["eslesen"] == 1
        assert ozet["toplam_xml"] == 1
        assert ozet["xml_de_var_yevmiyede_yok"] == []
        assert ozet["yevmiyede_var_xml_de_yok"] == []
        assert ozet["yon_belirsiz_atlanan"] == []

        uretilen = cikti / "TST2026000000001.json"
        assert uretilen.exists()

    def test_uretilen_json_icerigi_dogru(self, tmp_path):
        """Archive2/jsons formatına uygunluk - build_vector_db.py'nin
        beklediği alan adları (header, accounting_entries) birebir olmalı."""
        import json

        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000002")
        yevmiye = _yevmiye_yaz(tmp_path, [
            ("TST2026000000002", "600.01.00001", "Satislar", "Alacak", "1000.00"),
            ("TST2026000000002", "120.01.00001", "Alici Test A.S.", "Borc", "1100.00"),
        ])
        cikti = tmp_path / "jsons"
        esle_ve_uret(OWN_VKN, faturalar, yevmiye, cikti)

        veri = json.loads((cikti / "TST2026000000002.json").read_text(encoding="utf-8"))
        assert veri["header"]["invoice_id"] == "TST2026000000002"
        assert veri["header"]["payable"] == "1100.00 TRY"
        assert len(veri["accounting_entries"]) == 2
        kodlar = {e["account_code"] for e in veri["accounting_entries"]}
        assert kodlar == {"600.01.00001", "120.01.00001"}
        assert all(e["dc"] in ("Borç", "Alacak") for e in veri["accounting_entries"])

    def test_coklu_fatura_hepsi_eslesir(self, tmp_path):
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        for i in range(1, 4):
            _xml_yaz(faturalar, f"TST202600000000{i}")
        yevmiye = _yevmiye_yaz(tmp_path, [
            (f"TST202600000000{i}", "600.01.00001", "Satislar", "Alacak", "1000.00")
            for i in range(1, 4)
        ] + [
            (f"TST202600000000{i}", "120.01.00001", "Alici", "Borc", "1100.00")
            for i in range(1, 4)
        ])
        ozet = esle_ve_uret(OWN_VKN, faturalar, yevmiye, tmp_path / "jsons")
        assert ozet["eslesen"] == 3


class TestYanlisVkn:
    def test_own_vkn_hicbir_tarafta_yoksa_yon_belirsiz_atlanir(self, tmp_path):
        """own_vkn ne alici ne satici tarafindaysa (yanlis VKN girilmis
        olabilir) bu fatura RAG'a YAZILMAMALI - emsal havuzu kirlenmesin."""
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        # satici/alici ikisi de BASKA VKN'ler - own_vkn (6677889900) hicbirinde yok
        _xml_yaz(faturalar, "TST2026000000009", satici_vkn="1111111111", alici_vkn="2222222222")

        yevmiye = _yevmiye_yaz(tmp_path, [
            ("TST2026000000009", "600.01.00001", "Satislar", "Alacak", "1000.00"),
        ])
        cikti = tmp_path / "jsons"
        ozet = esle_ve_uret(OWN_VKN, faturalar, yevmiye, cikti)

        assert ozet["eslesen"] == 0
        assert ozet["yon_belirsiz_atlanan"] == ["TST2026000000009"]
        assert not (cikti / "TST2026000000009.json").exists()

    def test_dogru_vkn_etkilenmez(self, tmp_path):
        """Yanlis VKN'li bir fatura, DOGRU VKN'li digerlerinin eslesmesini
        engellememeli - sadece kendisi atlanir."""
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000010", satici_vkn=OWN_VKN)
        _xml_yaz(faturalar, "TST2026000000011", satici_vkn="9999999999", alici_vkn="8888888888")

        yevmiye = _yevmiye_yaz(tmp_path, [
            ("TST2026000000010", "600.01.00001", "Satislar", "Alacak", "1000.00"),
            ("TST2026000000011", "600.01.00001", "Satislar", "Alacak", "1000.00"),
        ])
        ozet = esle_ve_uret(OWN_VKN, faturalar, yevmiye, tmp_path / "jsons")

        assert ozet["eslesen"] == 1
        assert ozet["yon_belirsiz_atlanan"] == ["TST2026000000011"]


class TestEksikSutun:
    def test_zorunlu_sutun_eksikse_acik_hatayla_durur(self, tmp_path):
        """Sessizce yanlis sutun kullanmak yerine (ornegin tutar sutunu
        hesap_adi sanilmak) acikca durmali."""
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000020")

        # 'tutar' sutunu HIC yok
        yevmiye = _yevmiye_yaz(
            tmp_path,
            [("TST2026000000020", "600.01.00001", "Satislar", "Alacak")],
            basliklar=("fatura_no", "hesap_kodu", "hesap_adi", "borc_alacak"),
        )
        with pytest.raises(SystemExit, match="tutar"):
            esle_ve_uret(OWN_VKN, faturalar, yevmiye, tmp_path / "jsons")

    def test_birden_fazla_sutun_eksikse_hepsi_raporlanir(self, tmp_path):
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000021")

        yevmiye = _yevmiye_yaz(
            tmp_path,
            [("TST2026000000021", "600.01.00001")],
            basliklar=("fatura_no", "hesap_kodu"),
        )
        with pytest.raises(SystemExit) as exc:
            esle_ve_uret(OWN_VKN, faturalar, yevmiye, tmp_path / "jsons")
        assert "hesap_adi" in str(exc.value)
        assert "borc_alacak" in str(exc.value)
        assert "tutar" in str(exc.value)

    def test_serbest_bicimli_baslik_varyantlari_kabul_edilir(self, tmp_path):
        """Dis ekip farkli bir yazimla gonderebilir (ornegin 'Fatura No',
        'Hesap Kodu') - bunlar da taninmali, sadece tam esit string degil."""
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000022")

        yevmiye = _yevmiye_yaz(
            tmp_path,
            [("TST2026000000022", "600.01.00001", "Satislar", "Alacak", "1000.00")],
            basliklar=("Fatura No", "Hesap Kodu", "Hesap Adi", "Borc/Alacak", "Tutar"),
        )
        ozet = esle_ve_uret(OWN_VKN, faturalar, yevmiye, tmp_path / "jsons")
        assert ozet["eslesen"] == 1


class TestEslesmeyenFaturaNo:
    def test_xml_var_yevmiyede_yoksa_raporlanir_atlanir(self, tmp_path):
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000030")

        # Yevmiyede FARKLI bir fatura no var
        yevmiye = _yevmiye_yaz(tmp_path, [
            ("TST2026000000099", "600.01.00001", "Satislar", "Alacak", "1000.00"),
        ])
        cikti = tmp_path / "jsons"
        ozet = esle_ve_uret(OWN_VKN, faturalar, yevmiye, cikti)

        assert ozet["eslesen"] == 0
        assert ozet["xml_de_var_yevmiyede_yok"] == ["TST2026000000030"]
        assert ozet["yevmiyede_var_xml_de_yok"] == ["TST2026000000099"]
        assert not (cikti / "TST2026000000030.json").exists()

    def test_kismi_eslesme_sadece_eslesenler_yazilir(self, tmp_path):
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000040")
        _xml_yaz(faturalar, "TST2026000000041")

        yevmiye = _yevmiye_yaz(tmp_path, [
            ("TST2026000000040", "600.01.00001", "Satislar", "Alacak", "1000.00"),
            # 041 icin yevmiye kaydi YOK
        ])
        cikti = tmp_path / "jsons"
        ozet = esle_ve_uret(OWN_VKN, faturalar, yevmiye, cikti)

        assert ozet["eslesen"] == 1
        assert ozet["xml_de_var_yevmiyede_yok"] == ["TST2026000000041"]
        assert (cikti / "TST2026000000040.json").exists()
        assert not (cikti / "TST2026000000041.json").exists()

    def test_eslesmeyen_satirlar_veri_uydurmadan_atlanir(self, tmp_path):
        """Fatura no bos veya gecersizse satir sessizce atlanir (uyari
        stderr'e yazilir) - veri uydurulmaz, o satir hic kullanilmaz."""
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000050")

        yevmiye = _yevmiye_yaz(tmp_path, [
            ("TST2026000000050", "600.01.00001", "Satislar", "Alacak", "1000.00"),
            ("", "999.01.00001", "Bos fatura no", "Borc", "500.00"),
        ])
        ozet = esle_ve_uret(OWN_VKN, faturalar, yevmiye, tmp_path / "jsons")
        assert ozet["eslesen"] == 1
        assert ozet["toplam_yevmiye_fatura"] == 1


class TestBosGirdiler:
    def test_fatura_dizini_bossa_acik_hata(self, tmp_path):
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        yevmiye = _yevmiye_yaz(tmp_path, [
            ("TST2026000000060", "600.01.00001", "Satislar", "Alacak", "1000.00"),
        ])
        with pytest.raises(SystemExit, match="xml"):
            esle_ve_uret(OWN_VKN, faturalar, yevmiye, tmp_path / "jsons")

    def test_yevmiye_dosyasi_bossa_acik_hata(self, tmp_path):
        faturalar = tmp_path / "faturalar"
        faturalar.mkdir()
        _xml_yaz(faturalar, "TST2026000000061")

        wb = openpyxl.Workbook()
        yol = tmp_path / "bos_yevmiye.xlsx"
        wb.save(yol)
        with pytest.raises(SystemExit, match="bos"):
            esle_ve_uret(OWN_VKN, faturalar, yol, tmp_path / "jsons")
