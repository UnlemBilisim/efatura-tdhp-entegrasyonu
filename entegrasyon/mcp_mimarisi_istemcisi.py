"""Mcp_mimarisi'nin gerçek FastAPI'sine (POST /fatura/kontrol-et) HTTP
istemcisi.

Bu modül Mcp_mimarisi'nin koduna HİÇ dokunmaz/import etmez — sadece
`Mcp_mimarisi/docs/reference/api-semasi.md`'deki sözleşmeye göre HTTP
isteği atar. Mcp_mimarisi'nin ayrı bir süreç olarak (kendi PostgreSQL'i,
kendi FastAPI/uvicorn'u ile) çalışıyor olması gerekir — bkz.
`Mcp_mimarisi/docs/how-to/api-calistirma.md`.
"""

from __future__ import annotations

import os

import httpx

from log_ortak import mevcut_request_id

MCP_MIMARISI_BASE_URL = os.environ.get("MCP_MIMARISI_BASE_URL", "http://localhost:8000")


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("MCP_INTERNAL_API_TOKEN")
    if not token or len(token) < 32:
        raise McpMimarisiErisilemezHatasi(
            "MCP_INTERNAL_API_TOKEN en az 32 karakter olacak sekilde tanimli degil"
        )
    # X-Request-ID: entegrasyon'un bu istegi islerken kullandigi request-id
    # Mcp_mimarisi'ye de tasinir (RequestIdMiddleware orada bu header'i
    # gorup KENDI uretmek yerine aynen kullanir) - boylece iki servisin
    # loglarinda AYNI request_id ile arama yapip tek bir isteği uctan uca
    # izlemek mumkun olur (2026-09-11, canliya cikis loglama hazirligi).
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": mevcut_request_id(),
    }


class McpMimarisiErisilemezHatasi(Exception):
    """Mcp_mimarisi API'sine ağ/timeout hatasıyla ulaşılamadığında fırlatılır.

    model_eval/entegrasyon.md'nin "kapsam dışı" bölümünde bu durumun
    davranışı tanımsız bırakılmıştı — bu entegrasyon bunu belirsiz
    bırakmak yerine açıkça hata olarak işaretler ve kullanıcıya gösterir
    (sessizce "uygun" veya "insan incelemesi gerekli" varsaymaz)."""


def fatura_kontrol_et(fatura_xml: str, satici_vkn: str, satici_nace_kodlari: list[str]) -> dict:
    """POST /fatura/kontrol-et — tek fatura, kalem bazlı KDV oran kontrolü.

    Dönen sözlük Mcp_mimarisi'nin FaturaKontrolCevabi şemasıyla birebir
    aynıdır (genel_karar, satir_sonuclari, ...)."""
    try:
        resp = httpx.post(
            f"{MCP_MIMARISI_BASE_URL}/fatura/kontrol-et",
            json={
                "fatura_xml": fatura_xml,
                "satici_vkn": satici_vkn,
                "satici_nace_kodlari": satici_nace_kodlari,
            },
            headers=_auth_headers(),
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise McpMimarisiErisilemezHatasi(
            f"Mcp_mimarisi API'sine ({MCP_MIMARISI_BASE_URL}) ulaşılamadı: {exc}"
        ) from exc

    if resp.status_code == 400:
        # Bozuk XML veya VKN uyuşmazlığı — Mcp_mimarisi'nin kendi anlamlı
        # hata mesajı var, olduğu gibi yukarı taşı.
        detail = resp.json().get("detail", resp.text)
        raise ValueError(detail)
    resp.raise_for_status()
    return resp.json()


def saglik_kontrolu() -> dict:
    """GET /saglik — Mcp_mimarisi'nin ayakta olup olmadığını kontrol eder."""
    try:
        resp = httpx.get(f"{MCP_MIMARISI_BASE_URL}/saglik", timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.RequestError as exc:
        raise McpMimarisiErisilemezHatasi(
            f"Mcp_mimarisi API'sine ({MCP_MIMARISI_BASE_URL}) ulaşılamadı: {exc}"
        ) from exc
