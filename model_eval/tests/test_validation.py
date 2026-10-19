import pytest

from core.validation import validate_prediction


def _invoice(payable="100.00", tax_inclusive=None):
    return {"header": {"payable": payable, "tax_inclusive": tax_inclusive or payable}}


def test_inbox_tevkifat_full_kdv_record_is_valid(monkeypatch):
    """Gerçek fatura HE22026000014163: KDV dahil 54.355,20, tevkifat 4.529,60,
    ödenecek 49.825,60. Alışta tam KDV Borç'a yazıldığı için borç toplamı
    ödenecek tutar değil KDV dahil toplamdır (model_eval/CLAUDE.md, tevkifat
    kuralı)."""
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {})
    result = validate_prediction(
        {
            "entries": [
                {"account_code": "770", "dc": "Borc", "amount": 45296.00},
                {"account_code": "191", "dc": "Borc", "amount": 9059.20},
                {"account_code": "360", "dc": "Alacak", "amount": 4529.60},
                {"account_code": "320", "dc": "Alacak", "amount": 49825.60},
            ]
        },
        _invoice(payable="49825.60", tax_inclusive="54355.20"),
        "1234567890",
    )
    assert result["valid"] is True, result["errors"]


def test_outbox_tevkifat_net_record_is_valid(monkeypatch):
    """Muhasebeci onaylı örnek (Nuret Akalı/Demaş): satışta tevkif edilen
    kısım hiç yazılmaz, borç toplamı ödenecek (net) tutardır."""
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {})
    result = validate_prediction(
        {
            "entries": [
                {"account_code": "120", "dc": "Borc", "amount": 34510.00},
                {"account_code": "600", "dc": "Alacak", "amount": 29750.00},
                {"account_code": "391", "dc": "Alacak", "amount": 4760.00},
            ]
        },
        _invoice(payable="34510.00", tax_inclusive="35700.00"),
        "1234567890",
    )
    assert result["valid"] is True, result["errors"]


def test_record_matching_neither_payable_nor_tax_inclusive_is_rejected(monkeypatch):
    """Ödenecek tutarı hatalı yazılmış fatura (24.800, doğrusu 23.200):
    24.000'lik kayıt iki toplamdan birine de uymadığı için yakalanmalı."""
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {})
    result = validate_prediction(
        {
            "entries": [
                {"account_code": "770", "dc": "Borc", "amount": 20000},
                {"account_code": "191", "dc": "Borc", "amount": 4000},
                {"account_code": "360", "dc": "Alacak", "amount": 800},
                {"account_code": "320", "dc": "Alacak", "amount": 23200},
            ]
        },
        _invoice(payable="24800.00", tax_inclusive="24800.00"),
        "1234567890",
    )
    assert "PAYABLE_MISMATCH" in {error["code"] for error in result["errors"]}


def test_valid_prediction(monkeypatch):
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {})
    result = validate_prediction(
        {
            "entries": [
                {"account_code": "120", "dc": "Borc", "amount": 100},
                {"account_code": "600", "dc": "Alacak", "amount": 100},
            ]
        },
        _invoice(),
        "1234567890",
    )
    assert result["valid"] is True


def test_balanced_but_wrong_total_is_rejected(monkeypatch):
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {})
    result = validate_prediction(
        {
            "entries": [
                {"account_code": "120", "dc": "Borc", "amount": 999},
                {"account_code": "600", "dc": "Alacak", "amount": 999},
            ]
        },
        _invoice(),
        "1234567890",
    )
    assert result["valid"] is False
    assert "PAYABLE_MISMATCH" in {error["code"] for error in result["errors"]}


def test_unknown_account_and_non_finite_amount_are_rejected(monkeypatch):
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {})
    result = validate_prediction(
        {"entries": [{"account_code": "999", "dc": "Borc", "amount": float("nan")}]},
        _invoice(),
        "1234567890",
    )
    codes = {error["code"] for error in result["errors"]}
    assert {"ACCOUNT_NOT_ALLOWED", "INVALID_AMOUNT"} <= codes


def test_unquantizable_huge_amount_is_rejected_without_crashing(monkeypatch):
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {})
    result = validate_prediction(
        {"entries": [{"account_code": "120", "dc": "Borc", "amount": "1e999999"}]},
        _invoice(),
        "1234567890",
    )
    assert "INVALID_AMOUNT" in {error["code"] for error in result["errors"]}


def _dengeli(kod):
    return {"entries": [{"account_code": kod, "dc": "Borc", "amount": 100.0}, {"account_code": "320", "dc": "Alacak", "amount": 100.0}]}


@pytest.mark.parametrize("kod", ["150.01.001", "150.01.03", "600.01", "120.01.00001", "191.01.001.0002"])
def test_farkli_derinlik_ve_dolgudaki_mizan_kodlari_gecerli(monkeypatch, kod):
    """2026-10-19: biçim regex'i yalnızca `XXX.YY.ZZZZZ` kabul ediyordu (Akyüzlü'ye sabit) — başka bir şirketin geçerli
    `150.01.001` / `600.01` kodları INVALID_ACCOUNT_FORMAT ile reddedilip fatura onaylanamaz oluyordu."""
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {kod[:3]: [(kod, "Test")]})
    sonuc = validate_prediction(_dengeli(kod), _invoice("100.00"), "1234567890")
    assert sonuc["valid"] is True, sonuc["errors"]


def test_mizanda_olmayan_alt_hesap_hala_reddedilir(monkeypatch):
    """Biçim gevşedi ama GERÇEK koruma (şirket mizanında üyelik) aynı: uydurma alt hesap SUBACCOUNT_NOT_IN_LEDGER alır."""
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {"600": [("600.01", "A")]})
    sonuc = validate_prediction(_dengeli("600.99"), _invoice("100.00"), "1234567890")
    assert sonuc["valid"] is False and [e["code"] for e in sonuc["errors"]] == ["SUBACCOUNT_NOT_IN_LEDGER"]


@pytest.mark.parametrize("kotu", ["12", "6000", "600.", "600..01", "600.01.", "abc", "600.0 1", "600.01\n", "6001.01"])
def test_bozuk_hesap_kodu_bicimi_reddedilir(monkeypatch, kotu):
    monkeypatch.setattr("core.validation.get_alt_kirilimlar", lambda tenant_vkn: {})
    sonuc = validate_prediction(_dengeli(kotu), _invoice("100.00"), "1234567890")
    assert "INVALID_ACCOUNT_FORMAT" in [e["code"] for e in sonuc["errors"]]
