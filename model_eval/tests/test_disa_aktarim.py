"""core/disa_aktarim.py testleri — dis ekip semasina (records[]) donusum.

Sozlesme (2026-07-27): dis ekip her kayitta account_code / account_code_type /
account_description / account_code_reason / amount / debit_credit bekliyor.
Bu testler o sozlesmenin bozulmadigini korur."""

from core.disa_aktarim import (
    DC_DIS_KARSILIGI,
    _hesap_turu,
    faturayi_disa_aktar,
    kayitlari_disa_aktar,
)

# Dis ekibin ornek JSON'undaki dokuz zarf alani (2026-07-27 sozlesmesi).
DIS_ZARF_ALANLARI = {
    "currency",
    "customer",
    "file_path",
    "invoice_id",
    "issue_date",
    "payable_amount",
    "records",
    "success",
    "supplier",
}

DIS_SEMA_ALANLARI = {
    "account_code",
    "account_code_type",
    "account_description",
    "account_code_reason",
    "amount",
    "debit_credit",
}


class TestHesapTuru:
    def test_cari_hesaplar_C_doner(self):
        # CARI_HESAP_KODLARI = {120, 320, 340, 440, 159, 420}
        assert _hesap_turu("320.01.00376") == "C"
        assert _hesap_turu("120.03.00043") == "C"
        assert _hesap_turu("320") == "C"

    def test_diger_hesaplar_G_doner(self):
        assert _hesap_turu("191.01.00020") == "G"
        assert _hesap_turu("770.01.00003") == "G"
        assert _hesap_turu("689") == "G"


class TestDebitCredit:
    def test_ic_sema_dis_semaya_cevrilir(self):
        tahmin = {"entries": [{"account_code": "191.01.00020", "dc": "Borc", "amount": 1.0}]}
        assert kayitlari_disa_aktar(tahmin)[0]["debit_credit"] == "BORÇ"

        tahmin = {"entries": [{"account_code": "320.01.00376", "dc": "Alacak", "amount": 1.0}]}
        assert kayitlari_disa_aktar(tahmin)[0]["debit_credit"] == "ALACAK"

    def test_beklenmedik_deger_oldugu_gibi_gecer(self):
        """Bilinmeyen bir dc degeri sessizce yutulmaz/bozulmaz — oldugu gibi
        gecer ki sorun gorunur kalsin."""
        tahmin = {"entries": [{"account_code": "191", "dc": "Beklenmedik", "amount": 1.0}]}
        assert kayitlari_disa_aktar(tahmin)[0]["debit_credit"] == "Beklenmedik"

    def test_ic_sema_degismedi(self):
        """Ic tarafta Borc/Alacak KALMALI — 184 test ve model_eval_sonuclar
        tablosu buna bagli (bkz. disa_aktarim.py modul docstring'i)."""
        assert set(DC_DIS_KARSILIGI) == {"Borc", "Alacak"}


class TestGerekce:
    def test_fuzzy_eslesmede_benzerlik_orani_yazilir(self):
        tahmin = {
            "entries": [
                {
                    "account_code": "320.01.00376",
                    "dc": "Alacak",
                    "amount": 1700.0,
                    "account_description": "Mehmet Kozcağız",
                    "secim_kaynagi": {"kaynak": "fuzzy", "benzerlik": 0.94, "oran_duzeltildi": False},
                }
            ]
        }
        gerekce = kayitlari_disa_aktar(tahmin)[0]["account_code_reason"]
        assert "Mehmet Kozcağız" in gerekce
        assert "%94" in gerekce

    def test_kdv_oran_duzeltmesi_gerekcede_belirtilir(self):
        tahmin = {
            "entries": [
                {
                    "account_code": "391.02.00010",
                    "dc": "Alacak",
                    "amount": 100.0,
                    "account_description": "%10 Alıştan İade KDV",
                    "secim_kaynagi": {"kaynak": "llm", "benzerlik": None, "oran_duzeltildi": True},
                }
            ]
        }
        gerekce = kayitlari_disa_aktar(tahmin)[0]["account_code_reason"]
        assert "KDV oran" in gerekce
        assert "391.02.00010" in gerekce

    def test_emsal_sayisi_verilirse_gerekcede_gecer(self):
        tahmin = {
            "entries": [
                {
                    "account_code": "191.01.00020",
                    "dc": "Borc",
                    "amount": 283.33,
                    "secim_kaynagi": {"kaynak": "llm", "benzerlik": None, "oran_duzeltildi": False},
                }
            ]
        }
        gerekce = kayitlari_disa_aktar(tahmin, emsal_sayisi=3)[0]["account_code_reason"]
        assert "3 geçmiş" in gerekce

    def test_uc_haneli_kalan_cari_hesapta_uyari_gerekcesi(self):
        tahmin = {
            "entries": [
                {
                    "account_code": "320",
                    "dc": "Alacak",
                    "amount": 50.0,
                    "uyari": "Karşı taraf mizanda bulunamadı — cari kart açılmamış olabilir.",
                }
            ]
        }
        gerekce = kayitlari_disa_aktar(tahmin)[0]["account_code_reason"]
        assert "bulunamadı" in gerekce
        # Uyari zaten gerekcenin icinde anlatildigi icin ikinci kez
        # "UYARI:" olarak eklenmemeli (tekrar olmasin).
        assert gerekce.count("bulunamadı") == 1

    def test_gerekce_asla_bos_kalmaz(self):
        """Iz olmayan (secim_kaynagi yok) bir kayitta bile gerekce dolu olmali —
        dis ekip her kayitta bir gerekce bekliyor."""
        tahmin = {"entries": [{"account_code": "770.01.00003", "dc": "Borc", "amount": 850.0}]}
        assert kayitlari_disa_aktar(tahmin)[0]["account_code_reason"].strip()


class TestSemaUyumu:
    def test_tum_alanlar_her_kayitta_var(self):
        tahmin = {
            "entries": [
                {"account_code": "191.01.00020", "dc": "Borc", "amount": 283.33},
                {"account_code": "320", "dc": "Alacak", "amount": 1700.0, "uyari": "x"},
            ]
        }
        for kayit in kayitlari_disa_aktar(tahmin):
            assert set(kayit) == DIS_SEMA_ALANLARI

    def test_account_description_yoksa_bos_string(self):
        """None degil bos string — dis ekip tip tutarliligi bekliyor."""
        tahmin = {"entries": [{"account_code": "191", "dc": "Borc", "amount": 1.0}]}
        assert kayitlari_disa_aktar(tahmin)[0]["account_description"] == ""

    def test_bos_entries_bos_liste_doner(self):
        assert kayitlari_disa_aktar({"entries": []}) == []
        assert kayitlari_disa_aktar({}) == []

    def test_tutar_ve_kod_aynen_aktarilir(self):
        """Donusum tutari/kodu DEGISTIRMEMELI — sadece alan adlarini cevirir."""
        tahmin = {"entries": [{"account_code": "689.01.00012", "dc": "Borc", "amount": 566.67}]}
        kayit = kayitlari_disa_aktar(tahmin)[0]
        assert kayit["account_code"] == "689.01.00012"
        assert kayit["amount"] == 566.67


def _ornek_invoice(direction="inbox"):
    return {
        "invoice_id": "KOZ2025000002584",
        "direction": direction,
        "header": {
            "invoice_id": "KOZ2025000002584",
            "issue_date": "2025-12-04",
            "currency": "TRY",
            "payable": "1700.00",
            "account_title": "MEHMET KOZCAĞIZ LASTİK AKÜ JANT",
            "account_tax_number": "19367660918",
        },
    }


def _ornek_tahmin():
    return {
        "invoice_id": "KOZ2025000002584",
        "currency": "TRY",
        "error": None,
        "entries": [{"account_code": "320.01.00376", "dc": "Alacak", "amount": 1700.0}],
    }


class TestTamZarf:
    """Dis ekibin ornek JSON'undaki dokuz alanli zarf."""

    def test_dokuz_alan_tam(self):
        z = faturayi_disa_aktar(_ornek_tahmin(), _ornek_invoice(), "0460351893")
        assert set(z) == DIS_ZARF_ALANLARI

    def test_ust_bilgiler_faturadan_gelir(self):
        z = faturayi_disa_aktar(_ornek_tahmin(), _ornek_invoice(), "0460351893")
        assert z["invoice_id"] == "KOZ2025000002584"
        assert z["issue_date"] == "2025-12-04"
        assert z["currency"] == "TRY"
        assert z["payable_amount"] == 1700.0  # string "1700.00" -> float

    def test_inbox_karsi_taraf_TEDARIKCI(self):
        """inbox = bize gelen fatura -> karsi taraf supplier, biz customer."""
        z = faturayi_disa_aktar(_ornek_tahmin(), _ornek_invoice("inbox"), "0460351893")
        assert z["supplier"]["id"] == "19367660918"
        assert "KOZCAĞIZ" in z["supplier"]["name"]
        assert z["customer"]["id"] == "0460351893"

    def test_outbox_karsi_taraf_MUSTERI(self):
        """outbox = biz kestik -> karsi taraf customer, biz supplier."""
        z = faturayi_disa_aktar(_ornek_tahmin(), _ornek_invoice("outbox"), "0460351893")
        assert z["customer"]["id"] == "19367660918"
        assert z["supplier"]["id"] == "0460351893"

    def test_success_hataya_gore(self):
        assert faturayi_disa_aktar(_ornek_tahmin(), _ornek_invoice(), "1")["success"] is True
        hatali = {**_ornek_tahmin(), "error": "LLM erisilemedi"}
        assert faturayi_disa_aktar(hatali, _ornek_invoice(), "1")["success"] is False

    def test_file_path_verilmezse_bos_string(self):
        z = faturayi_disa_aktar(_ornek_tahmin(), _ornek_invoice(), "1")
        assert z["file_path"] == ""
        z2 = faturayi_disa_aktar(_ornek_tahmin(), _ornek_invoice(), "1", file_path="a/b.xml")
        assert z2["file_path"] == "a/b.xml"

    def test_records_zarf_icinde_ayni(self):
        """Zarftaki records, kayitlari_disa_aktar ile BIREBIR ayni olmali."""
        t = _ornek_tahmin()
        assert faturayi_disa_aktar(t, _ornek_invoice(), "1")["records"] == kayitlari_disa_aktar(t)
