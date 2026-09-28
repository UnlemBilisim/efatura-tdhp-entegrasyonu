"""HTTP istek boyutu ve temel tarayici guvenlik basliklari."""

import os

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            content_length = 0
        if content_length > MAX_REQUEST_BYTES:
            response = JSONResponse(
                {"detail": "Istek govdesi izin verilen boyutu asiyor."},
                status_code=413,
            )
            await response(scope, receive, send)
            return

        if scope.get("method") in {"POST", "PUT", "PATCH"}:
            messages = []
            total = 0
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body = message.get("body", b"")
                total += len(body)
                if total > MAX_REQUEST_BYTES:
                    response = JSONResponse(
                        {"detail": "Istek govdesi izin verilen boyutu asiyor."},
                        status_code=413,
                    )
                    await response(scope, receive, send)
                    return
                messages.append(message)
                more_body = message.get("more_body", False)
            message_index = 0

            async def replay_receive():
                nonlocal message_index
                if message_index < len(messages):
                    message = messages[message_index]
                    message_index += 1
                    return message
                return {"type": "http.request", "body": b"", "more_body": False}

            receive = replay_receive

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["Referrer-Policy"] = "no-referrer"
                response_headers["X-Frame-Options"] = "DENY"
                response_headers["Content-Security-Policy"] = (
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                    # style-src/font-src'e fonts.googleapis.com/fonts.gstatic.com
                    # eklendi (2026-09-11, demo.html'in IBM Plex yazı tiplerini
                    # kullanabilmesi için) — sadece bu iki güvenilir Google
                    # kaynağına izin verilir, genel bir gevşetme değildir.
                    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                    "font-src 'self' https://fonts.gstatic.com; "
                    "img-src 'self' data:; frame-ancestors 'none'"
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)
