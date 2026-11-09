from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.web.account_routes import router as account_router
from app.web.activity_routes import router as activity_router
from app.web.auth_routes import router as auth_router
from app.web.community_routes import router as community_router
from app.web.errors import http_error, server_error, validation_error
from app.web.event_routes import router as event_router
from app.web.jobs_routes import router as jobs_router
from app.web.messages_routes import router as messages_router
from app.web.moderation_routes import router as moderation_router
from app.web.notification_routes import router as notification_router
from app.web.offline_routes import router as offline_router
from app.web.onboarding_routes import router as onboarding_router
from app.web.opportunity_routes import router as opportunity_router
from app.web.pages_routes import router as pages_router
from app.web.profile_routes import public_router
from app.web.profile_routes import router as profile_router
from app.web.recruitment_routes import router as recruitment_router
from app.web.reel_routes import router as reel_router
from app.web.review_routes import router as review_router
from app.web.routes import router
from app.web.social_routes import router as social_router
from app.web.tour_routes import router as tour_router
from app.web.vacancy_routes import router as vacancy_router

BASE_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, server_error)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age,
        same_site=settings.session_same_site,
        https_only=settings.session_https_only,
    )
    # Added last so invalid hosts are rejected before session handling or routes.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts,
        www_redirect=False,
    )
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(social_router)
    app.include_router(event_router)
    app.include_router(offline_router)
    app.include_router(onboarding_router)
    app.include_router(tour_router)
    app.include_router(account_router)
    app.include_router(activity_router)
    app.include_router(profile_router)
    app.include_router(review_router)
    app.include_router(recruitment_router)
    app.include_router(vacancy_router)
    app.include_router(community_router)
    app.include_router(reel_router)
    app.include_router(moderation_router)
    app.include_router(opportunity_router)
    app.include_router(jobs_router)
    app.include_router(messages_router)
    app.include_router(notification_router)
    app.include_router(pages_router)
    app.include_router(public_router)
    return app


app = create_app()
