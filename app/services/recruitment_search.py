"""Python search orchestration; search services are separate from public-page fetching."""

import http.client
import json
import socket
import ssl
import time
from urllib.parse import urlencode, urlsplit

from app.core.config import settings
from app.services.recruitment_fetch import MAX_BYTES, FetchError, public_url, url_key


def search_available():
    return bool(
        settings.recruitment_searxng_urls
        or (settings.recruitment_search_key and settings.recruitment_search_permission_reference)
    )


def query_searxng(endpoint, query):
    """Only configured service addresses may use this client, including private deployments.

    Discovered websites still use PublicFetcher with public-IP pinning and robots rules.
    No redirects, cookies, proxy environment, user credentials or arbitrary target URLs.
    """
    configured = settings.recruitment_searxng_urls.split(",")
    if endpoint not in configured or not endpoint:
        raise FetchError("configuration_needed", "The search instance is not configured.")
    parsed = urlsplit(endpoint)
    timeout = settings.recruitment_search_timeout_seconds
    deadline = time.monotonic() + timeout
    connection_type = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    kwargs = {"timeout": timeout}
    if parsed.scheme == "https":
        kwargs["context"] = ssl.create_default_context()
    connection = connection_type(parsed.hostname, parsed.port, **kwargs)
    parameters = urlencode(
        {"q": query, "format": "json", "categories": "general", "language": "en", "safesearch": 1}
    )
    path = parsed.path.rstrip("/") + "/search?" + parameters
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "NurseNgSourceDiscovery/1.0",
            },
        )
        transport_socket = connection.sock
        response = connection.getresponse()
        if response.status == 429:
            retry = response.getheader("Retry-After", "900")
            raise FetchError(
                "rate_limited",
                "Search instance rate limited the request.",
                retryable=True,
                retry_after=min(86400, max(60, int(retry))) if retry.isdigit() else 900,
            )
        if response.status == 403:
            raise FetchError(
                "configuration_needed",
                "Search instance denied JSON access; enable search.formats: [html, json].",
            )
        if response.status != 200:
            raise FetchError(
                "search_unavailable",
                "Search instance returned an unsuccessful response.",
                retryable=True,
            )
        if (
            "json" not in response.getheader("Content-Type", "").lower()
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise FetchError(
                "extraction_error", "Search instance did not return uncompressed JSON."
            )
        body = bytearray()
        while True:
            if response.isclosed():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            transport_socket.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise FetchError("too_large", "Search response exceeded its size limit.")
        data = json.loads(body)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError
        return data
    except (TimeoutError, socket.timeout):
        raise FetchError("timeout", "Search instance timed out.", retryable=True) from None
    except ssl.SSLError:
        raise FetchError(
            "tls_error", "Search instance certificate validation failed.", retryable=True
        ) from None
    except (OSError, http.client.HTTPException):
        raise FetchError(
            "connection_error", "Search instance could not be reached.", retryable=True
        ) from None
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, FetchError):
            raise
        raise FetchError("extraction_error", "Search instance returned invalid JSON.") from None
    finally:
        connection.close()


def candidates_from_results(rows, *, query, provider, permission="", target_country=""):
    """Only minimal discovery facts, never provider snippets or implied source approval."""
    from app.services.recruitment_fetch import origin

    candidates, seen = [], set()
    for row in rows[:100]:
        try:
            target = public_url(row["url"])
            title = row.get("title", "")
            if not isinstance(title, str) or not title.strip():
                continue
            key = url_key(target)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "identity_key": "search:" + key,
                    "name": title[:250],
                    "category": "unconfirmed",
                    "country_code": "",
                    "location": "",
                    "website_url": origin(target),
                    "source_url": target,
                    "discovered_via": "search",
                    "reference": target,
                    "source_type": "search_candidate",
                    "evidence": {
                        "query": query,
                        "target_country": target_country,
                        "provider": provider,
                        "permission_reference": permission,
                        "notice": "Search suggestions are not verified organisation identity.",
                    },
                }
            )
            if len(candidates) >= 20:
                break
        except (FetchError, KeyError, TypeError, ValueError):
            continue
    return candidates


def general_search(payload, fetcher, *, key="", permission=""):
    from app.services.recruitment_discovery import (
        DISCOVERY_CATEGORIES,
        NIGERIAN_REGIONS,
        brave_discovery,
        search_query,
    )

    query = search_query(payload)
    endpoints = [v for v in settings.recruitment_searxng_urls.split(",") if v]
    start = (max(1, payload.get("page", 1)) - 1) % max(1, len(endpoints))
    failures, retry_after = [], 60
    for index in list(range(start, len(endpoints))) + list(range(start)):
        try:
            data = query_searxng(endpoints[index], query)
            if not data["results"] and data.get("unresponsive_engines"):
                raise FetchError(
                    "search_unavailable", "Search engines were unavailable.", retryable=True
                )
            candidates = candidates_from_results(
                data["results"],
                query=query,
                provider="searxng",
                target_country=payload.get("country_code", ""),
            )
            return {
                "ok": True,
                "outcome": "search_checked",
                "candidates": candidates,
                "next_page": payload.get("page", 1)
                % ((len(NIGERIAN_REGIONS) + 1) * len(DISCOVERY_CATEGORIES))
                + 1,
                "provider": "searxng",
                "provider_failures": failures,
                "message": f"SearXNG found {len(candidates)} candidate pages; "
                f"{len(failures)} instance failures; "
                f"{len(data.get('unresponsive_engines', []))} upstream engines unavailable.",
            }
        except FetchError as exc:
            failures.append({"provider": "searxng", "instance": index + 1, "outcome": exc.code})
            retry_after = max(retry_after, exc.retry_after if exc.code == "rate_limited" else 60)
    if key and permission:
        try:
            result = brave_discovery(payload, fetcher, key=key, permission=permission)
            return {
                **result,
                "provider": "brave",
                "provider_failures": failures,
                "message": result["message"]
                + f" Brave fallback; {len(failures)} instance failures.",
            }
        except FetchError as exc:
            failures.append({"provider": "brave", "outcome": exc.code})
            retry_after = max(retry_after, exc.retry_after if exc.code == "rate_limited" else 60)
    if not failures:
        raise FetchError("configuration_needed", "Configure a SearXNG instance; Brave is optional.")
    return {
        "ok": False,
        "outcome": (
            "rate_limited"
            if any(v["outcome"] == "rate_limited" for v in failures)
            else "search_unavailable"
        ),
        "retryable": True,
        "retry_after": retry_after,
        "provider_failures": failures,
        "message": "Search providers unavailable: "
        + ", ".join(f"{v['provider']} {v['outcome']}" for v in failures),
    }
