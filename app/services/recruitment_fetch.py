"""Bounded, credential-free public-page discovery with DNS-pinned connections.

The worker runs this transport in a disposable process with a hard deadline.
HTTPS verification stays enabled. No proxies, cookies, or browser profiles are used.
"""

import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from app.services.recruitment_tls import source_ssl_context

USER_AGENT = "NurseNgSourceDiscovery/1.0"
MAX_BYTES = 2 * 1024 * 1024


def _is_public(address) -> bool:
    return bool(
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not getattr(address, "ipv4_mapped", None)
        and not getattr(address, "sixtofour", None)
        and not getattr(address, "teredo", None)
    )


class FetchError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False, retry_after: int = 900):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


def public_url(value: str) -> str:
    """Validate without performing DNS or rewriting the caller's original address."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise FetchError("unsafe_url", "Enter a complete public HTTP or HTTPS URL.")
    if re.search(r"[\x00-\x20\x7f\\]", value) or re.search(
        r"%(?:0[0-9a-f]|1[0-9a-f]|7f)", value, re.I
    ):
        raise FetchError("unsafe_url", "URLs cannot contain whitespace or control characters.")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port
        sensitive = {
            "token",
            "access_token",
            "api_key",
            "apikey",
            "password",
            "secret",
            "signature",
            "authorization",
            "x-amz-signature",
        }
        if any(key.lower() in sensitive for key, _ in parse_qsl(parsed.query)):
            raise ValueError
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 80 if parsed.scheme == "http" else 443}
            or "%" in host
            or host.endswith(".")
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host):
                raise ValueError from None
            if any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x)
                for x in host.split(".")
            ):
                raise ValueError from None
        else:
            if not _is_public(address):
                raise ValueError
    except (ValueError, UnicodeError):
        raise FetchError(
            "unsafe_url", "Only public HTTP/HTTPS URLs on standard ports are allowed."
        ) from None
    return value


def origin(value: str) -> str:
    parsed = urlsplit(public_url(value))
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    return f"{parsed.scheme}://{'[' + host + ']' if ':' in host else host}"


def url_key(value: str) -> str:
    parsed = urlsplit(public_url(value))
    normalized = origin(value) + (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
    return hashlib.sha256(normalized.encode()).hexdigest()


def public_addresses(host: str, port: int) -> list[str]:
    try:
        addresses = list(
            dict.fromkeys(
                row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            )
        )
    except OSError:
        raise FetchError(
            "dns_error", "DNS lookup failed; the organisation remains unverified.", retryable=True
        ) from None
    if not addresses or any(not _is_public(ipaddress.ip_address(value)) for value in addresses):
        raise FetchError("unsafe_url", "The address resolves to a non-public network.")
    return addresses


@dataclass
class FetchedPage:
    url: str
    status: int
    content_type: str
    body: bytes
    retry_after: str = ""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class PublicFetcher:
    def __init__(self, *, budget_seconds: int = 40, max_requests: int = 8):
        self.deadline = time.monotonic() + budget_seconds
        self.max_requests = max_requests
        self.requests = 0
        self.last_request: dict[str, float] = {}
        self.rules: dict[str, RobotFileParser] = {}

    def _remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("timeout", "The page check exceeded its time budget.", retryable=True)
        return min(remaining, 10)

    def _wait(self, site: str, delay: float) -> None:
        wait = max(0, self.last_request.get(site, 0) + delay - time.monotonic())
        if wait >= self.deadline - time.monotonic():
            raise FetchError(
                "rate_limited",
                "The site's crawl delay exceeds this check's budget.",
                retryable=True,
            )
        if wait:
            time.sleep(wait)

    def _request(self, url: str, headers: dict[str, str] | None = None) -> FetchedPage:
        parsed = urlsplit(public_url(url))
        site = origin(url)
        self._wait(site, 2)
        self.requests += 1
        if self.requests > self.max_requests:
            raise FetchError("request_limit", "The page check reached its request limit.")
        host = parsed.hostname.encode("idna").decode("ascii")
        port = 443 if parsed.scheme == "https" else 80
        address = public_addresses(host, port)[0]
        connection = http.client.HTTPConnection(host, port, timeout=self._remaining())
        try:
            # Connect to the validated numeric address, never resolve the hostname a second time.
            connection.sock = socket.create_connection((address, port), timeout=self._remaining())
            if parsed.scheme == "https":
                connection.sock = source_ssl_context(host).wrap_socket(
                    connection.sock,
                    server_hostname=host,
                )
            transport_socket = connection.sock
            target = urlunsplit(
                (
                    "",
                    "",
                    quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                    quote(parsed.query, safe="%=&?/:@!$'()*+,;~-._"),
                    "",
                )
            )
            self.last_request[site] = time.monotonic()
            connection.request(
                "GET",
                target,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Encoding": "identity",
                    "Accept": "text/html,application/json,application/xml,text/plain;q=0.9",
                    **(headers or {}),
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                return FetchedPage(response.getheader("Location", ""), response.status, "", b"")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise FetchError("unsupported_content", "Compressed responses are not supported.")
            length = response.getheader("Content-Length", "")
            if length.isdigit() and int(length) > MAX_BYTES:
                raise FetchError("too_large", "The response exceeds the page-size limit.")
            body = bytearray()
            while True:
                transport_socket.settimeout(self._remaining())
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise FetchError("too_large", "The response exceeds the page-size limit.")
            return FetchedPage(
                url,
                response.status,
                response.getheader("Content-Type", ""),
                bytes(body),
                response.getheader("Retry-After", ""),
            )
        except ssl.SSLError:
            raise FetchError(
                "tls_error", "HTTPS certificate validation failed.", retryable=True
            ) from None
        except (TimeoutError, socket.timeout):
            raise FetchError(
                "timeout", "The website did not respond in time.", retryable=True
            ) from None
        except (OSError, http.client.HTTPException):
            raise FetchError("connection_error", "The connection failed.", retryable=True) from None
        finally:
            connection.close()

    def _robots(self, url: str) -> None:
        site = origin(url)
        if site not in self.rules:
            page = self.get(site + "/robots.txt", robots=False)
            parser = RobotFileParser(site + "/robots.txt")
            if page.status in {404, 410}:
                parser.parse(["User-agent: *", "Disallow:"])
            elif page.status in {401, 403}:
                parser.parse(["User-agent: *", "Disallow: /"])
            elif page.status == 200:
                parser.parse(page.text.splitlines())
            elif page.status == 429:
                require_success(page)
            else:
                raise FetchError(
                    "robots_unavailable", "Robots policy could not be checked.", retryable=True
                )
            self.rules[site] = parser
        rules = self.rules[site]
        if not rules.can_fetch(USER_AGENT, url):
            raise FetchError("policy_blocked", "The site's robots policy disallows this check.")
        rate = rules.request_rate(USER_AGENT)
        delay = max(
            2,
            rules.crawl_delay(USER_AGENT) or 0,
            rate.seconds / max(1, rate.requests) if rate else 0,
        )
        self._wait(site, delay)

    def get(
        self,
        url: str,
        *,
        robots: bool = True,
        allowed_origin: str | None = None,
        allowed_url_prefix: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchedPage:
        current = public_url(url)
        for _ in range(4):
            if allowed_url_prefix and not in_scope(current, allowed_url_prefix):
                raise FetchError(
                    "scope_blocked", "The endpoint is outside the approved reuse scope."
                )
            if allowed_origin and origin(current) != allowed_origin:
                raise FetchError(
                    "redirect_blocked", "The endpoint redirected outside its allowed origin."
                )
            if robots:
                self._robots(current)
            page = self._request(current, headers)
            if page.status not in {301, 302, 303, 307, 308}:
                return page
            target = public_url(urljoin(current, page.url))
            if urlsplit(current).scheme == "https" and urlsplit(target).scheme != "https":
                raise FetchError(
                    "redirect_blocked", "An HTTPS page redirected to an insecure address."
                )
            if headers and origin(target) != origin(current):
                raise FetchError(
                    "redirect_blocked", "Credential-bearing requests cannot change origin."
                )
            current = target
        raise FetchError("redirect_limit", "The website redirected too many times.")


def in_scope(url: str, prefix: str) -> bool:
    try:
        if origin(url) != origin(prefix):
            return False
        target, scope = urlsplit(public_url(url)), urlsplit(public_url(prefix))
        for key, value in parse_qsl(target.query):
            if key.lower() in {
                "url",
                "next",
                "redirect",
                "redirect_url",
                "redirect_uri",
                "return",
                "return_url",
                "continue",
            }:
                if origin(urljoin(url, value)) != origin(prefix):
                    return False
        if scope.query or scope.fragment:
            return False
        path = target.path or "/"
        for _ in range(3):
            path = unquote(path)
        if "\\" in path or any(part in {".", ".."} for part in path.split("/")):
            return False
        root = unquote(scope.path).rstrip("/")
        return path == root or path.startswith(root + "/")
    except (FetchError, ValueError):
        return False


def require_success(page: FetchedPage) -> None:
    if page.status == 200:
        return
    if page.status == 429:
        delay = 900
        try:
            if page.retry_after.isdigit():
                delay = max(delay, int(page.retry_after))
            elif page.retry_after:
                value = parsedate_to_datetime(page.retry_after)
                delay = max(delay, int((value - datetime.now(UTC)).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            pass
        # Pause conservatively; unusually large limits require operator attention.
        delay = min(delay, 365 * 86400)
        raise FetchError(
            "rate_limited",
            "The website asked for fewer requests.",
            retryable=True,
            retry_after=delay,
        )
    if page.status in {401, 403}:
        raise FetchError(
            "access_blocked", "The website restricted access; its identity is unchanged."
        )
    raise FetchError(
        "http_error", f"The website returned HTTP {page.status}.", retryable=page.status >= 500
    )
