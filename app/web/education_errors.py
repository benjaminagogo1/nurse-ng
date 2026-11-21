"""Convert safe domain/provider failures into the app's HTTP feedback formats."""

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.services.education_live import EducationLiveError
from app.web.errors import http_error


async def education_error(request, error):
    """Expose safe explanations while preserving provider outages as failures.

    Classroom fetches request JSON and must not receive an HTML error document.
    Ordinary page requests keep the existing accessible application error page.
    The domain/provider classes intentionally exclude credential-bearing errors.
    """
    code = 503 if isinstance(error, EducationLiveError) else error.status_code
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            {"detail": str(error)}, status_code=code, headers={"Cache-Control": "no-store"}
        )
    return await http_error(request, HTTPException(code, str(error)))
