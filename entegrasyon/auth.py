"""Entegrasyon API'si için şirkete bağlı API anahtarı doğrulaması."""

from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import api_anahtarlari
from api_anahtarlari import IstemciKimligi
from log_ortak import loglamayi_kur

_bearer = HTTPBearer(auto_error=False)
_logger = loglamayi_kur("entegrasyon.auth", "entegrasyon.log")


def _token_parmak_izi(token: str) -> str:
    """Token'in kendisini LOGLAMADAN kim/hangi token'in denendigini ayirt
    etmeye yarayan kisa bir ozet (sha256'nin ilk 8 hex karakteri) - ham
    token asla log'a yazilmaz (log dosyasi sizarsa token da sizmasin diye)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def require_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> IstemciKimligi:
    supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    if not supplied:
        _logger.warning("AUTH REDDEDILDI — anahtar yok")
        raise _yetkisiz()
    try:
        kimlik = api_anahtarlari.anahtari_dogrula(supplied)
    except Exception:  # noqa: BLE001
        _logger.error("AUTH DOGRULANAMADI — anahtar deposuna erisilemiyor", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kimlik doğrulama şu an yapılamıyor.",
        )
    if kimlik is None:
        _logger.warning("AUTH REDDEDILDI — token_parmak_izi=%s", _token_parmak_izi(supplied))
        raise _yetkisiz()
    return kimlik


def vkn_yetkisini_dogrula(kimlik: IstemciKimligi, vkn: str) -> None:
    if not kimlik.vkn_izinli_mi(vkn):
        _logger.warning("YETKI REDDEDILDI — istemci=%s vkn=%s", kimlik.etiket, vkn)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Bu anahtarın VKN {vkn} adına işlem yetkisi yok.",
        )


def _yetkisiz() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Geçerli bir API anahtarı gerekli.",
        headers={"WWW-Authenticate": "Bearer"},
    )
