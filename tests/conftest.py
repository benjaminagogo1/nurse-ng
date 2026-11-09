# ruff: noqa: E402
"""Configure an isolated local test environment before importing the application."""

import os
import secrets

os.environ.update({
    "NURSE_NG_ENVIRONMENT": "development",
    "NURSE_NG_DEBUG": "false",
    "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
    "NURSE_NG_ALLOWED_HOSTS": "localhost,127.0.0.1,::1",
    "NURSE_NG_SESSION_HTTPS_ONLY": "false",
    "NURSE_NG_SESSION_SAME_SITE": "lax",
    "NURSE_NG_RECRUITMENT_SEARXNG_URLS": "",
    "NURSE_NG_RECRUITMENT_SEARCH_KEY": "",
    "NURSE_NG_RECRUITMENT_SEARCH_PERMISSION_REFERENCE": "",
})

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  registers every model on the metadata
from app.core.ratelimit import reset_all_limiters
from app.db.base import Base
from app.db.session import enable_sqlite_foreign_keys, get_db
from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Every TestClient request shares one synthetic client address.

    Without a reset, a case that exhausts an allowance would leak into the next
    case (DECISIONS L43).
    """
    reset_all_limiters()
    yield
    reset_all_limiters()


@pytest.fixture
def engine():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    enable_sqlite_foreign_keys(test_engine)
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def db_session(engine):
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, base_url="http://localhost") as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
