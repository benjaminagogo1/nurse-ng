"""Readable browser errors without exposing validation inputs or internal exceptions."""

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.web.feedback import enhanced, message
from app.web.templating import render


def browser_error(request, code, body, headers=None, fields=None):
    notice = message("We couldn’t complete this action", body, tone="error", fields=fields)
    headers = {"Cache-Control": "no-store", **(headers or {})}
    if enhanced(request):
        return JSONResponse({"feedback": notice}, status_code=code, headers=headers)
    # An error handler may run before authentication or during a database failure.
    # It cannot establish sign-out, so leave browser drafts and acknowledgements alone.
    return render(
        request, "pages/error.html",
        {"feedback": notice, "draft_session_known": False}, code, headers,
    )


async def http_error(request: Request, exc: HTTPException):
    if 300 <= exc.status_code < 400:
        return await http_exception_handler(request, exc)
    if enhanced(request) or "text/html" in request.headers.get("accept", ""):
        defaults = {
            400: "Please refresh the page and try again. Your session may have expired.",
            401: "Please sign in to continue.",
            403: "Your account does not have access to this action.",
            404: "This item is unavailable or you do not have access to it.",
            429: "Too many attempts. Please wait before trying again.",
        }
        detail = exc.detail if isinstance(exc.detail, str) else ""
        if "CSRF" in detail:
            detail = (
                "Your session may have expired. Keep a copy of your work, "
                "then refresh and try again."
            )
        if detail in {"Not Found", "Forbidden", "Bad Request", "Unauthorized"}:
            detail = ""
        return browser_error(
            request,
            exc.status_code,
            detail or defaults.get(exc.status_code, "Please try again later."),
            exc.headers,
        )
    return await http_exception_handler(request, exc)


async def validation_error(request: Request, exc: RequestValidationError):
    if enhanced(request) or "text/html" in request.headers.get("accept", ""):
        fields = {
            str(error["loc"][-1]): "Check this value and try again."
            for error in exc.errors()
            if error["loc"] and error["loc"][0] == "body"
        }
        return browser_error(
            request, 422, "Please check the submitted values and try again.", fields=fields
        )
    return await request_validation_exception_handler(request, exc)


async def server_error(request: Request, exc: Exception):
    return browser_error(
        request,
        500,
        "The request was interrupted. Check whether the action completed before trying again.",
    )
