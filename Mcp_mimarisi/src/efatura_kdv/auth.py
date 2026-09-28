"""Yalnizca entegrasyon servisinin bildigi dahili MCP token kontrolu."""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .log_ortak import loglamayi_kur

_bearer = HTTPBearer(auto_error=False)
_logger = loglamayi_kur("efatura_kdv.auth", "mcp_mimarisi_api.log")


def _token_parmak_izi(token: str) -> str:
    """Token'in kendisini LOGLAMADAN kim/hangi token'in denendigini ayirt
    etmeye yarayan kisa bir ozet (sha256'nin ilk 8 hex karakteri) - ham
    token asla log'a yazilmaz."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def require_internal_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> None:
    expected = os.environ.get("MCP_INTERNAL_API_TOKEN")
    if not expected or len(expected) < 32:
        _logger.error("AUTH YAPILANDIRMA HATASI — MCP_INTERNAL_API_TOKEN eksik/32 karakterden kisa")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dahili API kimlik dogrulamasi guvenli bicimde yapilandirilmamis.",
        )
    supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    if not supplied or not secrets.compare_digest(supplied, expected):
        _logger.warning(
            "AUTH REDDEDILDI — token_parmak_izi=%s",
            _token_parmak_izi(supplied) if supplied else "(bos)",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Gecerli bir dahili Bearer token gerekli.",
            headers={"WWW-Authenticate": "Bearer"},
        )
