"""Action feedback, with ordinary forms and optional JSON enhancement."""

from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse


def message(title: str, body: str, *, tone: str = "success", fields: dict | None = None,
            compact: bool = False):
    notice = {"title": title, "body": body, "tone": tone, "fields": fields or {}}
    if compact:
        notice["compact"] = True
    return notice


def enhanced(request: Request) -> bool:
    return request.headers.get("x-account-feedback") == "1"


def pending_feedback(request: Request):
    saved = request.session.get("account_feedback")
    if request.method == "GET" and saved and saved.get("path") == request.url.path:
        return saved
    return None


def redirect_feedback(request: Request, path: str, notice: dict, *, code: str = ""):
    # Store only display text, never passwords, addresses, or verification tokens.
    request.session["account_feedback"] = {
        "path": urlsplit(path).path, "notice": notice, "code": code,
    }
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    if enhanced(request):
        return JSONResponse({"redirect": path}, headers=headers)
    return RedirectResponse(path, status_code=303, headers=headers)


def render_error(request: Request, template: str, context: dict, notice: dict, *, status_code=400):
    if enhanced(request):
        return JSONResponse({"feedback": notice}, status_code=status_code,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    from app.web.templating import render

    return render(request, template, {**context, "feedback": notice}, status_code=status_code,
                  headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
