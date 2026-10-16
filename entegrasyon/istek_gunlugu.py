"""Her HTTP isteği için TEK satır yapılandırılmış log (`entegrasyon.istek` logger'ı).

Neden: uvicorn erişim logu yalnızca "POST /musteri/onboard 400" der — NEDEN 400 olduğunu (yanıttaki `detail`)
hiçbir yerde kaydetmez. Bu middleware yöntem, yol, durum, süre, istemci IP'si, doğrulanmış anahtar etiketi,
request_id ve (durum >= 400 ise) hata mesajını tek JSON satırında yazar; izleme paneli (izleme/) bunu okur.

Güvenlik: İstek gövdesi, sorgu parametreleri ve `Authorization` başlığı ASLA loglanmaz. 422 doğrulama
hatalarında yanıt `input` alanını (fatura XML'i olabilir) taşır; yalnızca `loc` + `msg` yazılır. Hata
mesajı 300 karakterle sınırlıdır. Sağlık/arayüz yolları loglanmaz (gürültü)."""

from __future__ import annotations

import json
import logging
import time

from log_ortak import mevcut_request_id

_logger = logging.getLogger("entegrasyon.istek")

ATLANAN_YOLLAR = ("/durum", "/saglik", "/static/", "/favicon.ico", "/openapi.json", "/docs")
ATLANAN_TAM_YOLLAR = ("/",)
MAX_HATA_UZUNLUGU = 300
MAX_YAKALANAN_GOVDE = 8192


def hata_ayrintisi(govde: bytes) -> str | None:
    """Hata yanıtının gövdesinden okunabilir bir mesaj çıkarır; güvenli (girdi yansıtmaz) ve kısa."""
    try:
        veri = json.loads(govde.decode("utf-8", "replace"))
    except ValueError:
        return None
    detay = veri.get("detail") if isinstance(veri, dict) else None
    if detay is None:
        return None
    if isinstance(detay, str):
        metin = detay
    elif isinstance(detay, list):  # FastAPI 422: [{"loc": [...], "msg": "...", "input": ...}]
        parcalar = []
        for e in detay:
            if isinstance(e, dict):
                loc = ".".join(str(p) for p in e.get("loc", []) if p != "body")
                parcalar.append(f"{loc}: {e.get('msg', '')}".strip(": "))
        metin = "; ".join(parcalar) or "doğrulama hatası"
    else:
        metin = "hata"
    return metin[:MAX_HATA_UZUNLUGU]


class IstekGunluguMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        yol = scope.get("path", "")
        if yol in ATLANAN_TAM_YOLLAR or yol.startswith(ATLANAN_YOLLAR):
            await self.app(scope, receive, send)
            return

        baslangic = time.monotonic()
        durum = {"kod": 500, "govde": b""}

        async def send_izleyen(message):
            if message["type"] == "http.response.start":
                durum["kod"] = message["status"]
            elif message["type"] == "http.response.body" and durum["kod"] >= 400:
                if len(durum["govde"]) < MAX_YAKALANAN_GOVDE:
                    durum["govde"] += message.get("body", b"")
            await send(message)

        try:
            await self.app(scope, receive, send_izleyen)
        finally:
            kod = durum["kod"]
            istemci = (scope.get("client") or ("-", 0))[0]
            kayit = {
                "yontem": scope.get("method"),
                "yol": yol,
                "durum": kod,
                "sure_ms": round((time.monotonic() - baslangic) * 1000),
                "ip": istemci,
                "istemci": (scope.get("state") or {}).get("istemci"),  # auth.py doğrulanmış anahtar etiketini yazar
                "request_id": mevcut_request_id(),
            }
            if kod >= 400:
                kayit["hata"] = hata_ayrintisi(durum["govde"])
            seviye = logging.ERROR if kod >= 500 else logging.WARNING if kod >= 400 else logging.INFO
            _logger.log(seviye, json.dumps(kayit, ensure_ascii=False))
