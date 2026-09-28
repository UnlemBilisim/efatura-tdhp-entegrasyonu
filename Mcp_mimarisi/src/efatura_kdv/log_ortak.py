"""Profesyonel/production loglama altyapisi — JSON structured log +
request-id korelasyonu + rotasyonlu dosya handler.

Neden gerekli (2026-09-11, canliya cikis hazirligi): onceki loglama
`logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")`
sadece serbest metin uretiyordu — tarih yoktu (sadece saat), istekler
arasi korelasyon (ayni HTTP isteginin farkli log satirlarini birbirine
baglama) imkansizdi, ve dosyaya yazilan loglar rotasyonsuz sinirsiz
buyuyordu. (2026-09-28: sistem artik sadece Docker ile calistiriliyor,
bkz. asagidaki LOG_DIR notu — rotasyon container'da Docker'in kendi log
suruculugune, docker/docker-compose.yml'deki `logging:` ayarina emanet.)

Bu modul iki bagimsiz sistemde (entegrasyon/, Mcp_mimarisi/) ayni sekilde
kopyalanir cunku iki proje birbirine kod olarak baglanmaz (bkz. CLAUDE.md
"iki proje kod olarak birlestirilmez" kurali) — mantik birebir ayni
kalmali, degisiklik ikisine de uygulanmali.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import sys
import time
import uuid
from pathlib import Path

# İstek başına benzersiz kimlik — tüm log satırlarında görünür, aynı HTTP
# isteğine ait farklı log satırlarını (örn. "[1/5] İSTEK ALINDI" ile
# "TAMAMLANDI") birbirine bağlamak için. contextvars kullanılıyor çünkü
# thread-local'dan farklı olarak async/await sınırlarını da doğru geçer
# (uvicorn/starlette event-loop tabanlı çalışıyor).
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def yeni_request_id() -> str:
    """Kısa, okunabilir bir request-id üretir (tam UUID yerine ilk 12 hex
    karakter — log satırında yer kaplamadan pratikte çakışma riski yok)."""
    return uuid.uuid4().hex[:12]


def request_id_belirle(deger: str) -> None:
    _request_id_var.set(deger)


def mevcut_request_id() -> str:
    return _request_id_var.get()


class _RequestIdFilter(logging.Filter):
    """Her log kaydına o anki request-id'yi ekler (yoksa "-")."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = mevcut_request_id()
        return True


class _JsonFormatter(logging.Formatter):
    """Structured (tek satır JSON) log formatı — log toplama/arama
    araçlarına (ELK, Loki, CloudWatch vb.) doğrudan verilebilir. Stack
    trace `exc_info` verildiğinde `exception` alanında ayrı tutulur,
    serbest metne gömülmez (arama/filtreleme kolaylığı)."""

    def format(self, record: logging.LogRecord) -> str:
        kayit = {
            "zaman": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "seviye": record.levelname,
            "logger": record.name,
            "mesaj": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            kayit["exception"] = self.formatException(record.exc_info)
        return json.dumps(kayit, ensure_ascii=False)


class _OkunabilirFormatter(logging.Formatter):
    """Terminalde/geliştirmede okunması kolay format — request-id dahil.
    LOG_FORMAT=text ile seçilir (varsayılan: json)."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def loglamayi_kur(logger_adi: str, log_dosyasi_adi: str) -> logging.Logger:
    """Root logger'ı bir kez yapılandırır (stdout + rotasyonlu dosya) ve
    verilen isimde bir logger döner. Aynı süreç içinde birden fazla
    çağrılırsa handler'lar TEKRAR eklenmez (idempotent) — modül birden
    fazla yerden import edilebildiği için önemli.

    LOG_DIR env var'ı verilirse dosya handler'ı da eklenir (varsayılan: hiç
    eklenmez — bkz. aşağıdaki not). LOG_FORMAT ile "json" (varsayılan,
    production) veya "text" (geliştirme, terminalde okunabilir) seçilir.
    LOG_LEVEL ile seviye değiştirilebilir (varsayılan INFO).
    """
    root = logging.getLogger()
    zaten_kurulu = any(
        isinstance(h, logging.Handler) and getattr(h, "_efatura_log_handler", False)
        for h in root.handlers
    )
    if not zaten_kurulu:
        seviye = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
        root.setLevel(seviye)

        format_secimi = os.environ.get("LOG_FORMAT", "json").lower()
        formatter: logging.Formatter = (
            _OkunabilirFormatter() if format_secimi == "text" else _JsonFormatter()
        )
        istek_filtresi = _RequestIdFilter()

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        stdout_handler.addFilter(istek_filtresi)
        stdout_handler._efatura_log_handler = True  # type: ignore[attr-defined]
        root.addHandler(stdout_handler)

        # Dosyaya da yaz (rotasyonlu) — LOG_DIR verilmemişse dosya handler'ı
        # hiç eklenmez. Sistem artık sadece Docker ile çalıştırıldığından
        # (2026-09-28, baslat.sh kaldırıldı) LOG_DIR hiçbir yerde set
        # edilmiyor — sadece stdout'a yazılır, supervisord onu container
        # log akışına verir (bkz. docker/supervisord.conf), rotasyon
        # sorumluluğu Docker'ın kendi log sürücüsündedir (bkz.
        # docker/docker-compose.yml'deki `logging:` ayarı).
        log_dir = os.environ.get("LOG_DIR")
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            dosya_yolu = Path(log_dir) / log_dosyasi_adi
            # 10 MB x 5 dosya = en fazla ~50MB — sınırsız büyümeyi önler
            # (önceki durumda .calistirma/*.log rotasyonsuzdu).
            dosya_handler = logging.handlers.RotatingFileHandler(
                dosya_yolu, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            dosya_handler.setFormatter(formatter)
            dosya_handler.addFilter(istek_filtresi)
            dosya_handler._efatura_log_handler = True  # type: ignore[attr-defined]
            root.addHandler(dosya_handler)

    return logging.getLogger(logger_adi)


class RequestIdMiddleware:
    """ASGI middleware — her HTTP isteğine bir request-id atar (istemci
    `X-Request-ID` header'ı gönderdiyse onu kullanır, yoksa yeni üretir),
    contextvars'a yazar (tüm log satırları bunu otomatik taşır) ve cevaba
    `X-Request-ID` header'ı olarak geri ekler (istemci kendi isteğini
    sunucu loglarında arayabilsin diye)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        gelen_id = headers.get(b"x-request-id")
        request_id = gelen_id.decode("latin-1") if gelen_id else yeni_request_id()
        request_id_belirle(request_id)

        baslangic = time.monotonic()

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                from starlette.datastructures import MutableHeaders

                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            # İstek bitiminde context'i sıfırla — aynı worker/thread'in
            # sıradaki (ilgisiz) isteğine eski request-id sızmasın.
            request_id_belirle("-")
            _ = time.monotonic() - baslangic  # erişim endpoint'lerinde ayrıca ölçülüyor
