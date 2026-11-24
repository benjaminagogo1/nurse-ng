"""Typed environment configuration and startup validation.

All application settings use the NURSE_NG_ prefix. Production reads process
environment variables, while development may load .env. Settings are cached at
import time: restart web and workers after changing configuration. Validation
rejects unsafe production hosts, origins, cookies and signing keys before serving
traffic. Secret fields must never appear in logs or documentation output.
"""

import os
import re
import secrets
from functools import lru_cache
from ipaddress import ip_address, ip_network
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.public_urls import normalize_origin

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
    """Validated NURSE_NG_ environment contract; secrets are excluded from field repr where
    configured.
    """
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
    database_url: str = Field(default="sqlite:///./nurse_ng.db", repr=False)
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

    avatar_dir: str = "media/avatars"
    avatar_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    # Every externally shared link uses this origin, including background workers.
    # Production has no implicit development address.
    public_base_url: str = ""
    trusted_proxy_ips: str = ""
    android_app_download_url: str = ""
    ios_app_download_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    linkedin_client_id: str = ""
    linkedin_client_secret: str = Field(default="", repr=False)
    account_mail_backend: Literal["disabled", "file", "smtp"] = "disabled"
    account_mail_dir: str = "private-mail"
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl"] = "starttls"
    smtp_username: str = Field(default="", repr=False)
    smtp_password: str = Field(default="", repr=False)
    smtp_from: str = ""

    # Document-review evidence (DECISIONS L47-L48). Files are private: they are
    # written outside the static tree and served only through an authenticated
    # reviewer route. A relative path resolves against the process working
    # directory; never point this inside ``app/static``.
    evidence_dir: str = "evidence"
    evidence_max_bytes: int = 5 * 1024 * 1024
    evidence_scan_command: str = "clamscan"
    evidence_scan_timeout_seconds: int = Field(default=60, ge=1, le=120)
    evidence_retention_days: int = Field(default=90, ge=1, le=365)
    evidence_pending_retention_days: int = Field(default=180, ge=1, le=365)
    backup_dir: str = ".local-backups/automatic"
    backup_retention_days: int = Field(default=7, ge=1, le=30)

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
    community_malware_scan_mode: Literal["disabled", "optional", "required"] = "optional"
    community_malware_scan_command: str = "clamscan"
    community_malware_scan_timeout_seconds: int = 60

    # Private conversation files never share the public community media store.
    message_media_dir: str = "media/messages"
    message_attachment_max_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024
    )
    message_attachment_total_bytes: int = Field(
        default=100 * 1024 * 1024, ge=1024, le=400 * 1024 * 1024
    )
    message_attachment_max_files: int = Field(default=4, ge=1, le=8)
    message_upload_window_bytes: int = Field(default=500 * 1024 * 1024, ge=1024)
    message_storage_quota_bytes: int = Field(default=1024 * 1024 * 1024, ge=1024)

    # Reels processing runs in a separate CLI worker, outside web requests.
    # Empty selects the pinned imageio-ffmpeg binary; operators may use a system binary.
    reels_ffmpeg: str = ""
    reels_process_timeout_seconds: int = Field(default=300, ge=30, le=1200)

    # Live learning uses a managed LiveKit media service. The web application
    # issues restricted, short-lived grants; it never exposes this signing key.
    livekit_url: str = ""
    livekit_api_key: str = Field(default="", repr=False)
    livekit_api_secret: str = Field(default="", repr=False)
    livekit_token_seconds: int = Field(default=300, ge=60, le=600)
    # Recording files belong to an operator-controlled PRIVATE S3-compatible
    # bucket. Learners receive expiring GET signatures after course authorization.
    learning_recording_s3_bucket: str = ""
    learning_recording_s3_region: str = "us-east-1"
    learning_recording_s3_endpoint: str = ""
    learning_recording_s3_access_key: str = Field(default="", repr=False)
    learning_recording_s3_secret_key: str = Field(default="", repr=False)
    learning_recording_s3_force_path_style: bool = True

    # Optional search discovery. ROR directory discovery needs neither setting.
    # The agreement must permit retaining candidate URLs/results for this registry.
    recruitment_search_key: str = Field(default="", repr=False)
    recruitment_search_permission_reference: str = ""
    # Operator-configured services only; these addresses never come from search results.
    recruitment_searxng_urls: str = Field(default="", repr=False)
    recruitment_search_timeout_seconds: int = Field(default=10, ge=2, le=12)
    recruitment_daily_task_limit: int = Field(default=100, ge=1, le=1000)
    recruitment_pending_task_limit: int = Field(default=500, ge=20, le=5000)
    # Readiness requires these worker roles to have a fresh progress report.
    required_workers: str = ""

    @model_validator(mode="after")
    def validate_security_settings(self) -> Self:
        """Normalize host/proxy/worker settings and reject unsafe or incomplete provider config.

        Validation runs before the module exposes cached settings. Development
        convenience defaults do not bypass production HTTPS, secret, database,
        cookie or exact-host requirements. Errors name settings, not secret values.
        """
        roles = [role.strip() for role in self.required_workers.split(",") if role.strip()]
        if set(roles) - {"recruitment", "reels", "notifications"}:
            raise ValueError("Required workers must be recruitment, reels, or notifications.")
        self.required_workers = ",".join(dict.fromkeys(roles))
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
        proxies = [value.strip() for value in self.trusted_proxy_ips.split(",") if value.strip()]
        for value in proxies:
            try:
                if ip_network(value, strict=False).prefixlen == 0:
                    raise ValueError
            except ValueError:
                raise ValueError(
                    "NURSE_NG_TRUSTED_PROXY_IPS must contain exact IPs or bounded CIDR networks; "
                    "wildcards and all-address networks are not allowed."
                ) from None
        self.trusted_proxy_ips = ",".join(dict.fromkeys(proxies))
        from urllib.parse import urlsplit

        livekit_values = (self.livekit_url, self.livekit_api_key, self.livekit_api_secret)
        if any(livekit_values):
            if not all(livekit_values):
                raise ValueError(
                    "Live learning requires LIVEKIT_URL, LIVEKIT_API_KEY "
                    "and LIVEKIT_API_SECRET together."
                )
            media = urlsplit(self.livekit_url)
            if (
                media.scheme not in {"ws", "wss"}
                or not media.hostname
                or media.username
                or media.password
                or media.query
                or media.fragment
                or media.path not in {"", "/"}
                or any(c.isspace() for c in self.livekit_url)
            ):
                raise ValueError(
                    "NURSE_NG_LIVEKIT_URL must be a WebSocket origin without a path or credentials."
                )
            if production and media.scheme != "wss":
                raise ValueError(
                    "Production live learning requires a secure wss:// LiveKit origin."
                )
            normalize_origin(
                f"{'https' if media.scheme == 'wss' else 'http'}://{media.netloc}",
                public=production,
            )
            if len(self.livekit_api_secret) < 32:
                raise ValueError("NURSE_NG_LIVEKIT_API_SECRET must contain at least 32 characters.")
            self.livekit_url = self.livekit_url.rstrip("/")

        recording_values = (
            self.learning_recording_s3_bucket,
            self.learning_recording_s3_access_key,
            self.learning_recording_s3_secret_key,
        )
        if any(recording_values):
            if not all(recording_values) or not all(livekit_values):
                raise ValueError(
                    "Learning recordings require LiveKit "
                    "and complete private S3 bucket credentials."
                )
            if not re.fullmatch(
                r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.learning_recording_s3_bucket
            ):
                raise ValueError(
                    "The learning recording bucket must be a DNS-compatible S3 bucket name."
                )
            if not re.fullmatch(r"[a-z0-9-]{1,40}", self.learning_recording_s3_region):
                raise ValueError("Choose a valid recording S3 region.")
            if self.learning_recording_s3_endpoint:
                self.learning_recording_s3_endpoint = normalize_origin(
                    self.learning_recording_s3_endpoint,
                    public=production,
                )
                if not self.learning_recording_s3_endpoint.startswith("https://"):
                    raise ValueError("Recording storage requires an HTTPS S3 endpoint.")

        endpoints = [
            v.strip().rstrip("/") for v in self.recruitment_searxng_urls.split(",") if v.strip()
        ]
        if len(endpoints) > 3:
            raise ValueError("Configure at most three SearXNG instances.")
        for endpoint in endpoints:
            try:
                parsed = urlsplit(endpoint)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                    or re.search(r"[\s\\\\]", endpoint)
                    or "%" in endpoint
                    or ".." in parsed.path.split("/")
                    or not 1 <= (parsed.port or 80) <= 65535
                ):
                    raise ValueError
            except ValueError:
                raise ValueError(
                    "SearXNG instances must be HTTP(S) base URLs without credentials, "
                    "query or fragment."
                ) from None
        self.recruitment_searxng_urls = ",".join(dict.fromkeys(endpoints))

        if not production and not self.public_base_url:
            self.public_base_url = "http://127.0.0.1:8000"
        self.public_base_url = normalize_origin(self.public_base_url, public=production)
        base = urlsplit(self.public_base_url)
        if production and base.hostname not in hosts:
            raise ValueError("The public site hostname must be included in NURSE_NG_ALLOWED_HOSTS.")
        if production and "database_url" not in self.model_fields_set:
            raise ValueError("Set NURSE_NG_DATABASE_URL explicitly for the production database.")
        try:
            database = make_url(self.database_url)
            if database.drivername in {"postgres", "postgresql"}:
                database = database.set(drivername="postgresql+psycopg")
            if database.get_backend_name() not in {"sqlite", "postgresql"}:
                raise ValueError
            if (
                production
                and database.get_backend_name() == "sqlite"
                and (not database.database or database.database == ":memory:")
            ):
                raise ValueError
            self.database_url = database.render_as_string(hide_password=False)
        except (ArgumentError, ValueError):
            raise ValueError(
                "NURSE_NG_DATABASE_URL must identify PostgreSQL or a persistent SQLite database."
            ) from None
        for value in (self.android_app_download_url, self.ios_app_download_url):
            if not value:
                continue
            download = urlsplit(value)
            if (
                any(char.isspace() for char in value)
                or "\\" in value
                or download.username
                or download.password
                or not (
                    (download.scheme == "https" and download.hostname)
                    or (
                        value.startswith("/")
                        and not value.startswith("//")
                        and not download.scheme
                        and not download.netloc
                    )
                )
            ):
                raise ValueError("Mobile app download links must use HTTPS or a local site path.")
            if download.scheme:
                try:
                    normalize_origin(f"{download.scheme}://{download.netloc}", public=True)
                except ValueError:
                    raise ValueError(
                        "Mobile app download links must use public HTTPS or a local site path."
                    ) from None
        if production and self.account_mail_backend == "file":
            raise ValueError("The file email backend is only available in development.")
        if self.account_mail_backend == "smtp" and (
            not self.smtp_host
            or not self.smtp_from
            or "@" not in self.smtp_from
            or any(c in self.smtp_from for c in "\r\n")
        ):
            raise ValueError("SMTP requires NURSE_NG_SMTP_HOST and a valid NURSE_NG_SMTP_FROM.")
        return self

    @property
    def trusted_hosts(self) -> list[str]:
        # Starlette preserves the brackets around IPv6 literals in Host headers.
        return [f"[{host}]" if ":" in host else host for host in self.allowed_hosts.split(",")]


@lru_cache
def get_settings() -> Settings:
    # Hosting configuration comes from the process environment, never a copied local .env.
    """Load and cache validated settings; production ignores the development .env file."""
    if os.environ.get("NURSE_NG_ENVIRONMENT") == "production":
        return Settings(_env_file=None)
    return Settings()


settings = get_settings()
