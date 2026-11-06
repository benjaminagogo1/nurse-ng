import re
import secrets
from functools import lru_cache
from ipaddress import ip_address
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEVELOPMENT_KEYS = frozenset({"insecure-dev-key-change-me", "change-me-in-development"})
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def _validate_host(host: str) -> None:
    """Accept exact DNS names and IP addresses, without URLs, ports, or wildcards."""
    try:
        ip_address(host)
        return
    except ValueError:
        pass
    if len(host) > 253 or not all(_HOST_LABEL.fullmatch(label) for label in host.split(".")):
        raise ValueError(
            "NURSE_NG_ALLOWED_HOSTS must contain exact hostnames or IP addresses, "
            "without schemes, ports, paths, or wildcards."
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NURSE_NG_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["development", "production"] = "production"
    app_name: str = "Nurse.ng"
    debug: bool = False
    # Never ship a shared signing key. Development can generate an ephemeral one.
    secret_key: str = Field(default="", repr=False)
    database_url: str = "sqlite:///./nurse_ng.db"
    allowed_hosts: str = ""

    session_cookie_name: str = "nurse_ng_session"
    session_max_age: int = 60 * 60 * 24 * 14  # 14 days
    session_https_only: bool = True
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
    community_post_limit: int = 10
    community_post_window_seconds: int = 3600
    community_reply_limit: int = 60
    community_reply_window_seconds: int = 3600
    community_report_limit: int = 20
    community_report_window_seconds: int = 3600
    community_upload_window_bytes: int = 500 * 1024 * 1024
    community_upload_window_seconds: int = 24 * 60 * 60
    community_storage_quota_bytes: int = 5 * 1024 * 1024 * 1024
    community_upload_chunk_bytes: int = 1024 * 1024
    community_malware_scan_mode: Literal["disabled", "optional", "required"] = (
        "optional"
    )
    community_malware_scan_command: str = "clamscan"
    community_malware_scan_timeout_seconds: int = 60

    @model_validator(mode="after")
    def validate_security_settings(self) -> Self:
        production = self.environment == "production"
        if not self.secret_key and not production:
            self.secret_key = secrets.token_urlsafe(32)
        if (
            len(self.secret_key) < 32
            or self.secret_key.strip().casefold() in _DEVELOPMENT_KEYS
            or self.secret_key != self.secret_key.strip()
        ):
            raise ValueError(
                "Set NURSE_NG_SECRET_KEY to a randomly generated value of at least "
                "32 characters; development placeholders are not allowed."
            )
        if production and self.debug:
            raise ValueError("NURSE_NG_DEBUG must be false in production.")
        if production and not self.session_https_only:
            raise ValueError("NURSE_NG_SESSION_HTTPS_ONLY must be true in production.")
        if self.session_same_site == "none" and not self.session_https_only:
            raise ValueError("SameSite=None requires NURSE_NG_SESSION_HTTPS_ONLY=true.")

        if not self.allowed_hosts.strip():
            if production:
                raise ValueError("Set NURSE_NG_ALLOWED_HOSTS explicitly in production.")
            self.allowed_hosts = "localhost,127.0.0.1,::1"
        hosts = [host.strip().lower() for host in self.allowed_hosts.split(",")]
        for host in hosts:
            _validate_host(host)
        self.allowed_hosts = ",".join(dict.fromkeys(hosts))
        return self

    @property
    def trusted_hosts(self) -> list[str]:
        # Starlette preserves the brackets around IPv6 literals in Host headers.
        return [f"[{host}]" if ":" in host else host for host in self.allowed_hosts.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
