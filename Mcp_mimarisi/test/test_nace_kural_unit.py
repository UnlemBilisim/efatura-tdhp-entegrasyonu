import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from efatura_kdv.nace_kural_kontrolu import KararTuru, NaceOranTablosu, kontrol_et
from efatura_kdv.auth import require_internal_token


def _table():
    table = object.__new__(NaceOranTablosu)
    table._tablo = {"532009": [20.0], "463304": [1.0, 10.0]}
    return table


def test_allowed_rate_is_accepted():
    result = kontrol_et("53.20.09", 20.0, _table())
    assert result.karar is KararTuru.UYGUN


def test_disallowed_rate_requires_human_review():
    result = kontrol_et("463304", 20.0, _table())
    assert result.karar is KararTuru.INSAN_INCELEMESI_GEREKLI


def test_unknown_nace_requires_human_review():
    result = kontrol_et("000000", 20.0, _table())
    assert result.karar is KararTuru.INSAN_INCELEMESI_GEREKLI


def test_internal_token_is_checked(monkeypatch):
    expected = "expected-internal-token-at-least-32-chars"
    monkeypatch.setenv("MCP_INTERNAL_API_TOKEN", expected)
    require_internal_token(HTTPAuthorizationCredentials(scheme="Bearer", credentials=expected))
    with pytest.raises(HTTPException) as error:
        require_internal_token(HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong"))
    assert error.value.status_code == 401
