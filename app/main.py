from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.web.auth_routes import router as auth_router
from app.web.profile_routes import public_router
from app.web.profile_routes import router as profile_router
from app.web.routes import router

BASE_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age,
        same_site=settings.session_same_site,
        https_only=settings.session_https_only,
    )
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(public_router)
    return app


app = create_app()
