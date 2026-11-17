"""Navigation stays on the browser's origin, including behind an HTTPS proxy."""

from fastapi import Request


def page_url(request: Request, **parameters) -> str:
    target = request.url.include_query_params(**parameters)
    return target.path + ("?" + target.query if target.query else "")
