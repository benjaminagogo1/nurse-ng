"""Outbound source checks must not reach private networks or bypass access policies."""

import socket

import pytest

from app.services import recruitment_fetch as transport
from app.services.recruitment_discovery import execute_discovery
from app.services.recruitment_fetch import FetchedPage, FetchError, PublicFetcher, public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://224.0.0.1",
        "http://[2002:7f00:1::]",
        "http://10.2.3.4",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]",
        "http://[::ffff:8.8.8.8]",
        "http://localhost",
        "file:///etc/passwd",
        "https://user:secret@example.org",
        "https://example.org:8443",
        "https://example.org/%0d%0aHost:x",
        "https://example.org\\@localhost",
        "https://example.org/?access_token=private",
    ],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(FetchError):
        public_url(url)


def test_exact_url_is_preserved_and_dns_rejects_mixed_answers(monkeypatch):
    url = "https://lshsc.ng/recruitment"
    assert public_url(url) == url
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            for address in ["8.8.8.8", "127.0.0.1"]
        ],
    )
    with pytest.raises(FetchError, match="non-public"):
        transport.public_addresses("example.org", 443)


class ScriptedFetcher(PublicFetcher):
    def __init__(self, responses):
        super().__init__()
        self.responses = responses
        self.calls = []

    def _request(self, url, headers=None):
        self.calls.append((url, headers))
        return self.responses[url]


def test_robots_denial_blocks_page_request():
    fetcher = ScriptedFetcher(
        {
            "https://example.org/robots.txt": FetchedPage(
                "https://example.org/robots.txt",
                200,
                "text/plain",
                b"User-agent: *\nDisallow: /jobs",
            )
        }
    )
    with pytest.raises(FetchError, match="disallows"):
        fetcher.get("https://example.org/jobs")
    assert len(fetcher.calls) == 1


@pytest.mark.parametrize(
    "target",
    ["http://127.0.0.1/private", "http://example.org/insecure", "https://evil.example.org"],
)
def test_redirect_does_not_leak_provider_credentials(target):
    fetcher = ScriptedFetcher({"https://api.example.org/search": FetchedPage(target, 302, "", b"")})
    with pytest.raises(FetchError):
        fetcher.get(
            "https://api.example.org/search",
            robots=False,
            headers={"X-Subscription-Token": "private"},
            allowed_origin="https://api.example.org",
        )
    assert len(fetcher.calls) == 1


def test_cross_domain_page_redirect_checks_new_robots():
    fetcher = ScriptedFetcher(
        {
            "https://first.example.org/robots.txt": FetchedPage("", 404, "", b""),
            "https://first.example.org/jobs": FetchedPage(
                "https://second.example.org/jobs", 302, "", b""
            ),
            "https://second.example.org/robots.txt": FetchedPage("", 403, "", b""),
        }
    )
    with pytest.raises(FetchError, match="disallows"):
        fetcher.get("https://first.example.org/jobs")
    assert [url for url, _ in fetcher.calls][-1] == "https://second.example.org/robots.txt"


def test_robots_unavailable_fails_closed_and_rate_limit_preserves_retry_after():
    fetcher = ScriptedFetcher({"https://example.org/robots.txt": FetchedPage("", 503, "", b"")})
    result = execute_discovery("inspect", {"url": "https://example.org/jobs"}, fetcher=fetcher)
    assert result["outcome"] == "robots_unavailable"
    with pytest.raises(FetchError) as error:
        transport.require_success(FetchedPage("", 429, "", b"", "7200"))
    assert error.value.retry_after == 7200


def test_crawl_delay_above_check_budget_is_deferred():
    fetcher = ScriptedFetcher(
        {
            "https://example.org/robots.txt": FetchedPage(
                "", 200, "text/plain", b"User-agent: *\nCrawl-delay: 120\nDisallow:"
            )
        }
    )
    fetcher.last_request["https://example.org"] = transport.time.monotonic()
    with pytest.raises(FetchError, match="crawl delay"):
        fetcher.get("https://example.org/jobs")


def test_parser_ignores_scripts_and_keeps_canonical_as_hint():
    fetcher = ScriptedFetcher(
        {
            "https://lshsc.ng/robots.txt": FetchedPage("", 404, "", b""),
            "https://lshsc.ng/recruitment": FetchedPage(
                "https://lshsc.ng/recruitment",
                200,
                "text/html",
                b"""
            <title>Recruitment guidance</title><script><a href="/fake-jobs">jobs</a></script>
            <link rel="canonical" href="https://different.example.org/">
            <a href="http://127.0.0.1/jobs">Vacancies</a><a href="/careers">Careers</a>
            <a href="/legal">Terms</a>""",
            ),
        }
    )
    result = execute_discovery("inspect", {"url": "https://lshsc.ng/recruitment"}, fetcher=fetcher)
    assert result["ok"]
    assert result["links"] == [{"url": "https://lshsc.ng/careers", "label": "Careers"}]
    assert result["canonical_hint"] == "https://different.example.org/"
    assert "vacancies" not in result


@pytest.mark.parametrize(
    "headers,body,code",
    [
        ({"Content-Encoding": "gzip"}, b"compressed", "unsupported_content"),
        ({"Content-Length": str(transport.MAX_BYTES + 1)}, b"", "too_large"),
        ({}, b"x" * (transport.MAX_BYTES + 1), "too_large"),
    ],
)
def test_transport_pins_validated_ip_and_bounds_response(monkeypatch, headers, body, code):
    addresses = []

    class Socket:
        def settimeout(self, value):
            pass

    class Response:
        status = 200
        offset = 0

        def getheader(self, name, default=""):
            return headers.get(name, default)

        def read1(self, size):
            data = body[self.offset : self.offset + size]
            self.offset += len(data)
            return data

    class Connection:
        sock = None

        def __init__(self, *a, **kw):
            pass

        def request(self, *a, **kw):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(transport, "public_addresses", lambda *a: ["8.8.8.8"])

    def connect(address, **kwargs):
        addresses.append(address)
        return Socket()

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(transport.http.client, "HTTPConnection", Connection)
    with pytest.raises(FetchError) as error:
        PublicFetcher().get("http://example.org", robots=False)
    assert error.value.code == code
    assert addresses == [("8.8.8.8", 80)]
