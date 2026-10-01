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
