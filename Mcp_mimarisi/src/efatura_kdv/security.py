"""MCP API icin toplam HTTP istek boyutu siniri."""

import os

from starlette.responses import JSONResponse

MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))


class RequestSizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
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
                    total += len(message.get("body", b""))
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
        await self.app(scope, receive, send)
