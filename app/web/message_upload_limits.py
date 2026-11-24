"""Bound multipart parsing and request bytes on private message endpoints.

Reject oversized bodies before multipart buffering and constrain field/file
counts at route parsing. This transport limit complements, rather than replaces,
attachment-service validation and account storage quotas.
"""

import json
import re

from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.formparsers import MultiPartException

from app.core.config import settings


class MessageRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def limited(request):
            if request.method == "POST" and request.headers.get("content-type", "").startswith(
                "multipart/form-data"
            ):
                files = (
                    1
                    if request.url.path.endswith("/attachments")
                    else (
                        settings.message_attachment_max_files
                        if re.fullmatch(r"/messages/[0-9a-f-]{36}", request.url.path)
                        else 0
                    )
                )
                await request.form(max_files=files, max_fields=20, max_part_size=16384)
            return await handler(request)

        return limited


class MessageBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].startswith("/messages/")
        ):
            return await self.app(scope, receive, send)
        path = scope["path"]
        maximum = 65536
        if path.endswith("/attachments"):
            maximum += settings.message_attachment_max_bytes
        elif re.fullmatch(r"/messages/[0-9a-f-]{36}", path):
            maximum += settings.message_attachment_total_bytes
        headers = dict(scope["headers"])
        try:
            too_large = int(headers.get(b"content-length", b"0")) > maximum
        except ValueError:
            too_large = True
        if too_large:
            body = json.dumps(
                {"error": "This file request is too large. Choose smaller files."}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        size, exceeded = 0, False

        async def bounded_receive():
            nonlocal size, exceeded
            event = await receive()
            if event["type"] == "http.request":
                size += len(event.get("body", b""))
                if size > maximum:
                    exceeded = True
                    if b"multipart/form-data" in headers.get(b"content-type", b""):
                        # Starlette closes spooled upload files on this exception.
                        raise MultiPartException(
                            "This file request is too large. Choose smaller files."
                        )
                    raise HTTPException(413, "This message request is too large.")
            return event

        async def bounded_send(event):
            if exceeded and event["type"] == "http.response.start":
                event["status"] = 413
            await send(event)

        await self.app(scope, bounded_receive, bounded_send)
