from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NURSE_NG_",
        extra="ignore",
    )

    app_name: str = "Nurse.ng"
    debug: bool = False
    # Signs the session cookie. Production must set NURSE_NG_SECRET_KEY.
    secret_key: str = "insecure-dev-key-change-me"
    database_url: str = "sqlite:///./nurse_ng.db"
    allowed_hosts: str = "localhost,127.0.0.1"

    session_cookie_name: str = "nurse_ng_session"
    session_max_age: int = 60 * 60 * 24 * 14  # 14 days
    session_https_only: bool = False
    session_same_site: Literal["lax", "strict", "none"] = "lax"

    # Authentication abuse controls (DECISIONS L37-L44).
    # Per-IP counters live in process memory; account lockout is persisted on
    # the user row. Both are configurable so operations can tune without a code
    # change, and so tests can keep the defaults honest.
    login_ip_limit: int = 10
    login_ip_window_seconds: int = 300
    register_ip_limit: int = 5
    register_ip_window_seconds: int = 3600
    login_lockout_threshold: int = 5
    login_lockout_seconds: int = 900

    # Document-review evidence (DECISIONS L47-L48). Files are private: they are
    # written outside the static tree and served only through an authenticated
    # reviewer route. A relative path resolves against the process working
    # directory; never point this inside ``app/static``.
    evidence_dir: str = "evidence"
    evidence_max_bytes: int = 5 * 1024 * 1024

    # Public community media is kept separate from private review evidence.
    # These are conservative pilot defaults and remain configurable while the
    # production storage/processing provider is undecided.
    community_media_dir: str = "media/community"
    community_image_max_bytes: int = 10 * 1024 * 1024
    community_video_max_bytes: int = 100 * 1024 * 1024
    community_video_max_seconds: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
