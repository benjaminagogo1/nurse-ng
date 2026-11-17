"""Configured public addresses shared by the web app and background workers."""

import re
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_NUMERIC_HOST = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*")
_LOCAL_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal", ".lan", ".home.arpa")


def normalize_origin(value: str, *, public: bool = False) -> str:
    """Validate an origin without DNS requests or trusting a request Host header."""
    try:
        if not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
            raise ValueError
        if "\\" in value or "%" in value:
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        try:
            address = ip_address(host)
        except ValueError:
            address = None
            if len(host) > 253 or not all(_LABEL.fullmatch(label) for label in host.split(".")):
                raise ValueError from None
        if public:
            if parsed.scheme != "https":
                raise ValueError
            if address:
                mapped = getattr(address, "ipv4_mapped", None) or address
                if not mapped.is_global or mapped.is_multicast:
                    raise ValueError
            elif (
                "." not in host
                or host.endswith(_LOCAL_SUFFIXES)
                or _NUMERIC_HOST.fullmatch(host)
            ):
                raise ValueError
        authority = f"[{host}]" if ":" in host else host
        if port is not None and (parsed.scheme, port) not in {("https", 443), ("http", 80)}:
            authority += f":{port}"
        return urlunsplit((parsed.scheme, authority, "", "", ""))
    except (ValueError, UnicodeError):
        description = "a public HTTPS origin" if public else "an HTTP(S) origin"
        raise ValueError(f"NURSE_NG_PUBLIC_BASE_URL must be {description}.") from None


def public_site_ready() -> bool:
    from app.core.config import settings

    try:
        normalize_origin(settings.public_base_url, public=True)
    except ValueError:
        return False
    return True


def public_url(path: str) -> str:
    """Build an application link from the configured origin, including in workers."""
    from app.core.config import settings

    parsed = urlsplit(path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or "\\" in path
        or any(ord(char) <= 32 or ord(char) == 127 for char in path)
        or ".." in parsed.path.split("/")
    ):
        raise ValueError("Public application links require a local absolute path.")
    return normalize_origin(settings.public_base_url) + path
