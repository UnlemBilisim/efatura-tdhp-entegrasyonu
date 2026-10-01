"""LLM muhasebe kayitlarini TDHP, mizan ve fatura toplamlariyla dogrular."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from .constants import TDHP_GLOSSARY
from .mizan import get_alt_kirilimlar
from .parsing import to_float

MONEY_TOLERANCE = Decimal("0.01")
ACCOUNT_CODE_RE = re.compile(r"^\d{3}(?:\.\d{2}\.\d{5})?$")


def _money(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        return number.quantize(MONEY_TOLERANCE)
    except (InvalidOperation, TypeError, ValueError):
        return None


def validate_prediction(prediction: dict, invoice: dict, own_vkn: str) -> dict:
    errors: list[dict[str, str]] = []
    entries = prediction.get("entries") or []
    if not entries:
        errors.append({"code": "EMPTY_ENTRIES", "message": "Muhasebe kaydi bos."})

    mizan = get_alt_kirilimlar(tenant_vkn=own_vkn)
    allowed_full = {code for options in mizan.values() for code, _name in options}
    borc = Decimal("0")
    alacak = Decimal("0")

    for index, entry in enumerate(entries):
        code = str(entry.get("account_code") or "")
        dc = entry.get("dc")
        amount = _money(entry.get("amount"))
        prefix = code[:3]
        if not ACCOUNT_CODE_RE.fullmatch(code):
            errors.append({"code": "INVALID_ACCOUNT_FORMAT", "message": f"Satir {index + 1}: gecersiz hesap kodu {code!r}."})
        elif prefix not in TDHP_GLOSSARY:
            errors.append({"code": "ACCOUNT_NOT_ALLOWED", "message": f"Satir {index + 1}: {prefix} TDHP listesinde yok."})
        elif "." in code and code not in allowed_full:
            errors.append({"code": "SUBACCOUNT_NOT_IN_LEDGER", "message": f"Satir {index + 1}: {code} sirket mizaninda yok."})
        if dc not in {"Borc", "Alacak"}:
            errors.append({"code": "INVALID_DIRECTION", "message": f"Satir {index + 1}: borc/alacak yonu gecersiz."})
        if amount is None or amount <= 0:
            errors.append({"code": "INVALID_AMOUNT", "message": f"Satir {index + 1}: tutar pozitif ve sonlu olmali."})
            continue
        if dc == "Borc":
            borc += amount
        elif dc == "Alacak":
            alacak += amount
        if entry.get("uyari"):
            errors.append({"code": "UNRESOLVED_COUNTERPARTY", "message": f"Satir {index + 1}: {entry['uyari']}"})

    if abs(borc - alacak) > MONEY_TOLERANCE:
        errors.append({"code": "UNBALANCED", "message": "Borc ve alacak toplamlari esit degil."})

    header = invoice.get("header", {})
    payable = _money(to_float(header.get("payable")))
    # Tevkifatlı alışta tam KDV Borç'a yazıldığı için borç toplamı ödenecek
    # tutar değil KDV dahil toplamdır; tevkifatsız faturada ikisi zaten eşit.
    tax_inclusive = _money(to_float(header.get("tax_inclusive")))
    kabul_edilen_toplamlar = [t for t in (payable, tax_inclusive) if t is not None and t > 0]
    if kabul_edilen_toplamlar and all(abs(borc - t) > MONEY_TOLERANCE for t in kabul_edilen_toplamlar):
        errors.append({
            "code": "PAYABLE_MISMATCH",
            "message": f"Kayit toplami ({borc}) fatura odenecek tutariyla ({payable}) uyusmuyor.",
        })

    return {
        "valid": not errors,
        "errors": errors,
        "borc_toplam": float(borc),
        "alacak_toplam": float(alacak),
    }
