from core.validation import validate_prediction


def _invoice(payable="100.00"):
    return {"header": {"payable": payable}}


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
