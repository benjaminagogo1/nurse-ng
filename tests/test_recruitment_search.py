"""Real HTTP SearXNG contract, fallback and persistent discovery integration."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.core.config import Settings, settings
from app.models.recruitment import DiscoveryTask, RecruitmentSource
from app.services import recruitment as registry
from app.services import recruitment_worker as worker
from app.services.recruitment_discovery import execute_discovery
from app.services.recruitment_fetch import FetchedPage, FetchError
from app.services.recruitment_search import general_search, query_searxng, search_available
from tests.test_recruitment_fetch import ScriptedFetcher


@contextmanager
def instance(status=200, data=None, headers=None, raw=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(
                raw if raw is not None else json.dumps(data or {"results": []}).encode()
            )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.fixture(autouse=True)
def no_paid_keys(monkeypatch):
    monkeypatch.setattr(settings, "recruitment_search_key", "")
    monkeypatch.setattr(settings, "recruitment_search_permission_reference", "")
    monkeypatch.setattr(settings, "recruitment_searxng_urls", "")


def test_searxng_http_json_without_key_and_deduplicated_safe_results(monkeypatch):
    results = [
        {
            "url": "https://health.example.gov.ng/internship",
            "title": "Health internship",
            "content": "Do not retain this provider snippet",
        },
        {"url": "https://health.example.gov.ng/internship#apply", "title": "Duplicate"},
        {"url": "http://127.0.0.1/private", "title": "Unsafe"},
        {"url": "https://example.org", "title": None},
    ]
    with instance(data={"results": results}) as (url, calls):
        monkeypatch.setattr(settings, "recruitment_searxng_urls", url)
        result = execute_discovery(
            "search", {"query": "{country} health internship", "country_code": "NG"}
        )
    assert result["ok"] and result["provider"] == "searxng"
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["country_code"] == ""
    assert "Do not retain" not in json.dumps(result)
    query = parse_qs(urlsplit(calls[0]).query)
    assert query["q"] == ["Nigeria health internship"] and query["format"] == ["json"]


def test_failed_instance_falls_back_without_brave(monkeypatch):
    with (
        instance(503) as (first, first_calls),
        instance(data={"results": [{"url": "https://example.gov.ng/jobs", "title": "Jobs"}]}) as (
            second,
            second_calls,
        ),
    ):
        monkeypatch.setattr(settings, "recruitment_searxng_urls", first + "," + second)
        result = execute_discovery("search", {"query": "Nigeria jobs"})
    assert result["ok"] and len(first_calls) == len(second_calls) == 1
    assert result["provider_failures"][0]["outcome"] == "search_unavailable"
    assert first not in result["message"]


def test_malformed_search_links_try_next_instance_instead_of_reporting_empty_success(monkeypatch):
    with (
        instance(data={"results": [
            {"url": "http:///go/v1/provider-redirect", "title": "Nursing vacancies"},
            {"url": "http://127.0.0.1/private", "title": "Unsafe result"},
        ]}) as (first, first_calls),
        instance(data={"results": [
            {"url": "https://health.example.gov.ng/jobs", "title": "Health jobs"},
        ]}) as (second, second_calls),
    ):
        monkeypatch.setattr(settings, "recruitment_searxng_urls", first + "," + second)
        result = execute_discovery("search", {"query": "Nigeria nursing vacancies"})
    assert result["ok"] and len(result["candidates"]) == 1
    assert len(first_calls) == len(second_calls) == 1
    assert result["provider_failures"][0]["outcome"] == "extraction_error"


@pytest.mark.parametrize(
    "status,expected",
    [(403, "configuration_needed"), (429, "rate_limited"), (302, "search_unavailable")],
)
def test_errors_are_bounded_and_redirects_are_not_followed(monkeypatch, status, expected):
    with instance(
        status, headers={"Location": "http://127.0.0.1/private", "Retry-After": "120"}
    ) as (url, calls):
        monkeypatch.setattr(settings, "recruitment_searxng_urls", url)
        with pytest.raises(FetchError) as exc:
            query_searxng(url, "test")
        assert exc.value.code == expected and len(calls) == 1
        if status == 429:
            assert exc.value.retry_after == 120


def test_brave_is_optional_fallback_and_key_stays_server_side(monkeypatch):
    from app.services import recruitment_discovery

    calls = []

    def brave(payload, fetcher, *, key, permission):
        calls.append((key, permission))
        return {
            "ok": True,
            "outcome": "search_checked",
            "candidates": [],
            "message": "Search complete.",
        }

    monkeypatch.setattr(recruitment_discovery, "brave_discovery", brave)
    with instance(503) as (url, _):
        monkeypatch.setattr(settings, "recruitment_searxng_urls", url)
        result = general_search(
            {"query": "Nigeria jobs"},
            None,
            key="test-secret",
            permission="https://example.org/terms",
        )
    assert result["provider"] == "brave" and calls == [("test-secret", "https://example.org/terms")]
    assert "test-secret" not in json.dumps(result)


def test_worker_registers_search_results_and_direct_monitoring_survives_search_outage(
    db_session, monkeypatch
):
    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    site = "https://health.example.gov.ng"
    with instance(
        data={"results": [{"url": site, "title": "Search title, not verified name"}]}
    ) as (url, _):
        monkeypatch.setattr(settings, "recruitment_searxng_urls", url)
        assert registry.ensure_search_schedule(db_session) == 1
        worker.enqueue_due(db_session)
        task = worker.run_next(db_session, executor=execute_discovery)
        assert task.status == "completed"
    source = db_session.scalar(select(RecruitmentSource))
    assert source.verification_status == "pending"
    monkeypatch.setattr(settings, "recruitment_searxng_urls", "")
    assert not search_available()
    fetched = ScriptedFetcher(
        {
            site: FetchedPage(
                site, 200, "text/html", b"<title>State Health Agency</title><p>Nigeria</p>"
            ),
            site + "/robots.txt": FetchedPage("", 404, "", b""),
        }
    )
    worker.enqueue_due(db_session)
    task = worker.run_next(
        db_session, executor=lambda kind, payload: execute_discovery(kind, payload, fetcher=fetched)
    )
    assert task.status == "completed", task.message
    db_session.refresh(source)
    assert source.verification_status == "approved"
    assert source.organization.name == "State Health Agency"
    assert (
        db_session.scalar(select(DiscoveryTask).where(DiscoveryTask.kind == "search")).status
        == "completed"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://key:secret@example.org",
        "https://example.org/?token=x",
        "file:///tmp/private",
        "https://example.org/../admin",
        "https://example.org/#x",
    ],
)
def test_service_configuration_rejects_credentials_and_ambiguous_endpoints(url):
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="development", recruitment_searxng_urls=url)


def test_unconfigured_service_cannot_be_called(monkeypatch):
    with pytest.raises(FetchError, match="not configured"):
        query_searxng("http://127.0.0.1:8080", "test")


def test_content_length_close_is_a_successful_complete_response(monkeypatch):
    body = json.dumps({"results": [{"url": "https://example.org/jobs", "title": "Jobs"}]}).encode()
    with instance(headers={"Content-Length": str(len(body)), "Connection": "close"}, raw=body) as (
        url,
        _,
    ):
        monkeypatch.setattr(settings, "recruitment_searxng_urls", url)
        assert len(query_searxng(url, "jobs")["results"]) == 1


def test_invalid_and_oversized_responses_fail_closed(monkeypatch):
    from app.services.recruitment_fetch import MAX_BYTES

    for body, code in [(b"{", "extraction_error"), (b"x" * (MAX_BYTES + 1), "too_large")]:
        with instance(raw=body) as (url, _):
            monkeypatch.setattr(settings, "recruitment_searxng_urls", url)
            with pytest.raises(FetchError) as exc:
                query_searxng(url, "jobs")
            assert exc.value.code == code


def test_search_cannot_duplicate_or_reopen_a_known_rejected_url(db_session):
    args = dict(
        identity_key="manual:known",
        name="Known Agency",
        category="public_health",
        country_code="NG",
        location="",
        website_url="https://health.example.gov.ng/",
        source_url="https://health.example.gov.ng/jobs",
        discovered_via="manual",
        reference="https://health.example.gov.ng/",
    )
    known, _ = registry.register_candidate(db_session, **args)
    known.verification_status = "rejected"
    db_session.commit()
    found, created = registry.register_candidate(
        db_session,
        **(
            args
            | {"identity_key": "search:new", "discovered_via": "search", "name": "Search title"}
        ),
    )
    assert found.id == known.id and not created and found.verification_status == "rejected"


def test_new_nigerian_search_target_runs_before_old_failed_directory_checks(
    db_session, monkeypatch
):
    from datetime import timedelta

    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    common = dict(
        category="public_health",
        location="",
        source_type="recruitment_page",
        reference="https://example.org/",
    )
    old, _ = registry.register_candidate(
        db_session,
        **common,
        identity_key="old",
        name="Old source",
        country_code="NG",
        website_url="https://old.example.ng",
        source_url="https://old.example.ng",
        discovered_via="ror",
    )
    new, _ = registry.register_candidate(
        db_session,
        **common,
        identity_key="new",
        name="Unverified search title",
        country_code="",
        website_url="https://new.example.ng",
        source_url="https://new.example.ng",
        discovered_via="search",
        evidence={"target_country": "NG"},
    )
    db_session.commit()
    worker.enqueue_due(db_session)
    failed = db_session.scalar(select(DiscoveryTask).where(DiscoveryTask.source_id == old.id))
    failed.attempts = 2
    failed.available_at = registry.now() - timedelta(days=1)
    db_session.commit()
    chosen = worker.claim_next(db_session)
    assert chosen.source_id == new.id
    assert new.organization.country_code == ""


def test_worker_recovers_expired_sqlite_lease_after_restart(db_session, monkeypatch):
    from datetime import timedelta

    from tests.test_recruitment import observation

    monkeypatch.setattr(worker, "NETWORK_COOLDOWN_SECONDS", 0)
    source, _ = registry.register_candidate(
        db_session,
        identity_key="lease:source",
        name="Lease source",
        category="public_health",
        country_code="NG",
        location="",
        website_url="https://source.example.ng/",
        source_url="https://source.example.ng/",
        discovered_via="manual",
        reference="https://source.example.ng/",
    )
    db_session.commit()
    worker.enqueue_due(db_session)
    claimed = worker.claim_next(db_session)
    old_token = claimed.lease_token
    claimed.lease_until = registry.now() - timedelta(seconds=1)
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(DiscoveryTask, claimed.id).lease_until.tzinfo is None
    recovered = worker.claim_next(db_session)
    assert recovered.id == claimed.id and recovered.lease_token != old_token
    assert recovered.status == "running" and recovered.running_key == "network"
    assert (
        worker.apply_result(
            db_session,
            recovered.id,
            old_token,
            {"revision": source.revision},
            observation(source.original_url),
        )
        is False
    )
