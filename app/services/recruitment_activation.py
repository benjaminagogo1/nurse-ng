"""Reproducible automatic source checks; ambiguous evidence stays in staff review.

Assessment consumes recorded observations and explicit policy inputs.
Ambiguous authority or reuse evidence stays reviewable; an automatic assessment
must not overwrite protected staff decisions or silently broaden approved scope.
"""

import base64
import re
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit

from app.services.recruitment_fetch import FetchError, in_scope, origin, require_success, url_key
from app.services.vacancy_extraction import extract_records, normalize, parse_date, plain

POLICY_VERSION = 3
LICENCES = {
    "https://creativecommons.org/publicdomain/zero/1.0/": "CC0 1.0",
    "https://creativecommons.org/licenses/by/4.0/": "CC BY 4.0",
}
# Country alone must never choose among multiple deadline zones. Other countries
# can activate when all source dates include explicit UTC offsets.
COUNTRY_TIMEZONES = {"NG": "Africa/Lagos", "GH": "Africa/Accra", "KE": "Africa/Nairobi"}


def eligible(source) -> bool:
    return (
        source.approval_mode in {"", "automatic"}
        and source.automation_status == "monitoring"
        and source.verification_status not in {"rejected", "revoked"}
    )


def context(source, db=None) -> dict:
    org = source.organization
    facts = {
        "identity": org.identity_key,
        "name": org.name,
        "country": org.country_code,
        "website": org.website_url,
        "source_type": source.source_type,
    }
    if db is not None:
        from sqlalchemy import select

        from app.models.recruitment import SourceEvent

        facts["references"] = list(
            db.scalars(
                select(SourceEvent.reference_url)
                .where(
                    SourceEvent.source_id == source.id,
                    SourceEvent.kind == "discovered",
                )
                .limit(3)
            )
        )
    return facts


def words(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


class PageLicence(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.links = set()

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        attrs = dict(attrs)
        if tag == "link" and self.in_head and "license" in (attrs.get("rel") or "").split():
            self.links.add((attrs.get("href") or "").rstrip("/") + "/")

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def assess_licensed(payload: dict, page, fetcher) -> dict:
    """Run inside the bounded network child. Do not retain page bodies before passing."""
    from app.services.recruitment_discovery import (
        CAREER_WORDS,
        PageLinks,
        _json_response,
        _safe_link,
    )

    facts = payload["automatic_activation"]
    report = {
        "policy_version": POLICY_VERSION,
        "status": "needs_review",
        "reasons": [],
        "evidence": {},
    }
    reasons, evidence = report["reasons"], report["evidence"]

    def blocked(message):
        reasons.append(message)
        return report

    if not re.fullmatch(r"https://ror.org/[a-z0-9]{9}", facts["identity"]):
        return blocked("No supported independent organisation record. Staff evidence is needed.")
    if not facts["country"] or not facts["name"]:
        return blocked("Organisation name and country must be established.")
    if (
        urlsplit(payload["url"]).scheme != "https"
        or urlsplit(facts["website"]).scheme != "https"
        or url_key(page.url) != url_key(payload["url"])
        or origin(page.url) != origin(facts["website"])
        or urlsplit(page.url).query
    ):
        return blocked("Automatic activation needs the exact HTTPS page on the official origin.")

    directory_url = "https://api.ror.org/v2/organizations/" + facts["identity"].rsplit("/", 1)[-1]
    directory = _json_response(fetcher, directory_url)
    names = [row.get("value", "") for row in directory.get("names", []) if isinstance(row, dict)]
    websites = [
        row.get("value", "")
        for row in directory.get("links", [])
        if isinstance(row, dict) and row.get("type") == "website"
    ]
    countries = [
        (row.get("geonames_details") or {}).get("country_code")
        for row in directory.get("locations", [])
        if isinstance(row, dict)
    ]
    if (
        directory.get("id") != facts["identity"]
        or directory.get("status") != "active"
        or not any(isinstance(name, str) and words(name) == words(facts["name"]) for name in names)
        or facts["country"] not in countries
        or facts["website"] not in websites
    ):
        return blocked("The current healthcare directory record does not match this organisation.")
    evidence["directory"] = directory_url
    evidence["organisation"] = facts["name"]
    home = (
        page
        if url_key(page.url) == url_key(facts["website"])
        else fetcher.get(
            facts["website"],
            allowed_origin=origin(page.url),
        )
    )
    require_success(home)
    if "text/html" not in home.content_type.lower() or origin(home.url) != origin(page.url):
        return blocked("The official homepage could not be verified as HTML on the same origin.")
    if words(facts["name"]) not in words(plain(home.text)):
        return blocked("The official homepage does not identify the expected organisation.")
    links = PageLinks()
    links.feed(home.text)
    linked = url_key(home.url) == url_key(page.url) or any(
        target and url_key(target) == url_key(page.url)
        for href, _ in links.links
        if (target := _safe_link(home.url, href))
    )
    if not linked:
        return blocked("The official homepage has no direct link to this recruitment page.")
    page_links = PageLinks()
    page_links.feed(page.text)
    if page_links.canonical:
        canonical = _safe_link(page.url, page_links.canonical)
        if not canonical or url_key(canonical) != url_key(page.url):
            return blocked("The page identifies a different canonical announcement address.")
    if not CAREER_WORDS.search(urlsplit(page.url).path + " " + page_links.title):
        return blocked("The linked page is not clearly identified as a recruitment channel.")
    evidence["official_homepage"] = home.url
    evidence["recruitment_page"] = page.url
    licence = PageLicence()
    licence.feed(page.text)
    if len(licence.links) != 1 or not licence.links.issubset(LICENCES):
        return blocked(
            "No unambiguous supported page-level reuse terms. Staff can record another legal basis."
        )
    evidence["licence_url"] = next(iter(licence.links))
    evidence["licence_name"] = LICENCES[evidence["licence_url"]]
    try:
        records = extract_records(page.body)
        normalized = [normalize(raw) for raw in records]
    except (FetchError, TypeError, ValueError, RecursionError):
        return blocked("Structured vacancy data could not be assessed; staff review is needed.")
    from app.services.opportunities import relevant_opportunity

    matching = [
        data
        for data in normalized
        if relevant_opportunity(data)
        and words(data["employer"]) == words(facts["name"])
        and data["country"] == facts["country"]
    ]
    if not matching:
        return blocked("No relevant structured opportunity matches the organisation and country.")
    timezone = COUNTRY_TIMEZONES.get(facts["country"], "")
    if timezone and any(
        data["country"] != facts["country"]
        and any("T" not in data[key] for key in ("closing_date", "publication_date"))
        for data in normalized
    ):
        return blocked("Vacancies in different countries need an explicit deadline timezone.")
    if not timezone:
        dates = [data[key] for data in normalized for key in ("closing_date", "publication_date")]
        if not all("T" in value and parse_date(value, "UTC") for value in dates):
            return blocked("Date-only or ambiguous deadlines need a staff-confirmed timezone.")
        timezone = "UTC"
    if not any(in_scope(data["announcement_url"], payload["url"]) for data in matching):
        return blocked("Matching announcement URLs are outside this page's collection scope.")
    # Channel identity is established here. Individual vacancy problems, including
    # reversed salaries and missing deadlines, belong to the ingestion review queue.
    evidence["timezone"] = timezone
    report["status"] = "eligible"
    return report


def authority_url(url):
    """Restricted government namespace or a named intergovernmental publisher."""
    host = urlsplit(url).hostname or ""
    return urlsplit(url).scheme == "https" and (
        host.endswith(".gov.ng") or host in {"undp.org", "www.undp.org", "who.int", "www.who.int"}
    )


def same_publisher_origin(first, second):
    """Only the conventional www alias; every connection still verifies its hostname."""
    a, b = urlsplit(first), urlsplit(second)
    return a.scheme == b.scheme == "https" and (a.hostname or "").removeprefix("www.") == (
        b.hostname or ""
    ).removeprefix("www.")


def directory_site_matches(listed, website):
    """A registry's old HTTP link may establish the HTTPS upgrade of the same website."""
    if not isinstance(listed, str):
        return False
    return same_publisher_origin(listed.replace("http://", "https://", 1), website) and urlsplit(
        listed
    ).path.rstrip("/") == urlsplit(website).path.rstrip("/")


def assess_index(payload, page, fetcher):
    """Verify a publisher independently of licences and vacancy data availability."""
    from app.services.announcement_extraction import AnnouncementHTML
    from app.services.recruitment_discovery import PageLinks, _json_response, _safe_link

    facts = payload["automatic_activation"]
    report = {
        "policy_version": POLICY_VERSION,
        "status": "needs_review",
        "reasons": [],
        "evidence": {},
    }

    def blocked(reason):
        report["reasons"].append(reason)
        return report

    if urlsplit(page.url).scheme != "https" or urlsplit(payload["url"]).scheme != "https":
        return blocked("Automatic indexing requires HTTPS with verified publisher identity.")
    # A same-origin redirect can canonicalise a path; a redirect cannot establish a new owner.
    if not same_publisher_origin(page.url, payload["url"]):
        return blocked("A different destination origin needs independent organisation evidence.")
    parsed = PageLinks()
    parsed.feed(page.text)
    if parsed.canonical:
        canonical = _safe_link(page.url, parsed.canonical)
        if not canonical or url_key(canonical) != url_key(page.url):
            return blocked("The page identifies a different canonical announcement address.")
    website = facts.get("website") or origin(page.url) + "/"
    identity = facts.get("identity", "")
    name, country = facts.get("name", ""), facts.get("country", "")
    evidence = report["evidence"]
    home = page if url_key(page.url) == url_key(website) else fetcher.get(website)
    require_success(home)
    if "html" not in home.content_type.lower() or not same_publisher_origin(home.url, website):
        return blocked("The publisher homepage could not be verified on its expected origin.")
    independent = False
    home_verified = False
    if authority_url(home.url) and same_publisher_origin(home.url, page.url):
        independent = True
        evidence["identity_basis"] = (
            "government_domain"
            if (urlsplit(home.url).hostname or "").endswith(".gov.ng")
            else "intergovernmental_domain"
        )
        if evidence["identity_basis"] == "government_domain":
            country = "NG"
    elif re.fullmatch(r"https://ror.org/[a-z0-9]{9}", identity):
        directory_url = "https://api.ror.org/v2/organizations/" + identity.rsplit("/", 1)[-1]
        directory = _json_response(fetcher, directory_url)
        home_verified = (
            directory.get("id") == identity
            and directory.get("status") == "active"
            and any(
                row.get("type") == "website" and directory_site_matches(row.get("value"), website)
                for row in directory.get("links", [])
                if isinstance(row, dict)
            )
            and any(
                words(row.get("value", "")) == words(name)
                for row in directory.get("names", [])
                if isinstance(row, dict)
            )
            and any(
                (row.get("geonames_details") or {}).get("country_code") == country
                for row in directory.get("locations", [])
                if isinstance(row, dict)
            )
        )
        independent = home_verified and same_publisher_origin(home.url, page.url)
        evidence.update(identity_basis="directory", directory=directory_url)
    if not independent:
        for reference in [website, *facts.get("references", [])][:4]:
            directory_reference = home_verified and same_publisher_origin(reference, home.url)
            if (not authority_url(reference) and not directory_reference) or origin(
                reference
            ) == origin(page.url):
                continue
            authority = home if url_key(reference) == url_key(home.url) else fetcher.get(reference)
            require_success(authority)
            if not authority_url(authority.url) and not (
                directory_reference and same_publisher_origin(authority.url, home.url)
            ):
                continue
            links = PageLinks()
            links.feed(authority.text)
            if any(
                target and same_publisher_origin(target, page.url)
                for href, _ in links.links
                if (target := _safe_link(authority.url, href))
            ):
                independent = True
                evidence.update(
                    identity_basis="directory_backlink"
                    if directory_reference
                    else "authoritative_backlink",
                    authority_reference=authority.url,
                )
                break
    if not independent:
        return blocked(
            "No supported independent organisation evidence: an official government domain, "
            "current directory record or authoritative backlink is needed."
        )
    home_info = AnnouncementHTML()
    home_info.feed(home.text)
    if identity.startswith("search:") or not name:
        home_links = PageLinks()
        home_links.feed(home.text)
        name = home_info.meta.get("og:site_name") or home_links.title.strip()
        if not name or words(name) in {"home", "welcome", "homepage"}:
            return blocked("The official publisher name could not be established.")
    elif words(name) not in words(plain(home.text)):
        return blocked("The official homepage does not identify the expected organisation.")
    if not country:
        return blocked("Publisher country could not be established independently.")
    publisher_info = AnnouncementHTML()
    publisher_info.feed(page.text)
    publisher = publisher_info.meta.get("og:site_name", "")
    if (
        evidence.get("identity_basis") in {"directory_backlink", "authoritative_backlink"}
        and publisher
    ):
        name = publisher
    evidence.update(
        organisation=name[:250],
        country=country,
        official_homepage=home.url,
        recruitment_page=page.url,
        scope=origin(page.url) + "/",
        requested_url=payload["url"],
        timezone=COUNTRY_TIMEZONES.get(country, "UTC"),
        mode="factual_index",
    )
    report["status"] = "eligible"
    return report


def assess(payload, page, fetcher):
    # Keep the existing licensed full-content path. Indexing does not claim those rights.
    licence = PageLicence()
    licence.feed(page.text)
    if (
        licence.links
        and licence.links.issubset(LICENCES)
        and payload["automatic_activation"].get("identity", "").startswith("https://ror.org/")
    ):
        return assess_licensed(payload, page, fetcher)
    return assess_index(payload, page, fetcher)


def attach_assessment(payload, page, fetcher, result):
    if "automatic_activation" not in payload:
        return result
    report = assess(payload, page, fetcher)
    result["activation_review"] = report
    if report["status"] == "eligible":
        if report["evidence"].get("mode") == "factual_index":
            from app.services.factual_opportunities import collect_index

            collected = collect_index(payload, page, fetcher, report["evidence"])
            collected["links"] = (collected["links"] + result.get("links", []))[:3]
            result.update(collected)
        else:
            result["body_base64"] = base64.b64encode(page.body).decode()
    return result


def apply_assessment(db, source, result, timestamp, task_id):
    """Caller has already fenced the worker and locked the source revision."""
    from app.services.recruitment import REUSE_RIGHTS, event
    from app.services.vacancies import mark_source_unconfirmed

    report = result.get("activation_review")
    if not report or not eligible(source):
        return False
    if report.get("policy_version") != POLICY_VERSION:
        raise ValueError("Unsupported automatic activation policy")
    report = {**report, "checked_at": timestamp.isoformat()}
    previous = source.activation_review or {}
    source.activation_review = report
    activated = report["status"] == "eligible"
    if activated:
        evidence = report["evidence"]
        indexing = evidence.get("mode") == "factual_index"
        if (not indexing and evidence["licence_url"] not in LICENCES) or evidence[
            "recruitment_page"
        ] != source.observed_url:
            raise ValueError("Automatic evidence does not match the checked page")
        source.verification_status = "approved"
        source.approval_mode = "automatic"
        source.permission_status = "limited" if indexing else "permitted"
        source.reuse_basis = "factual_index" if indexing else "published_licence"
        source.reuse_url_prefix = evidence["scope"] if indexing else source.original_url
        for right in REUSE_RIGHTS:
            setattr(source, right, not indexing or right == "allow_collection")
        source.collection_method = "html"
        source.collection_adapter = "factual_index" if indexing else "jsonld"
        source.vacancy_url_prefix = source.reuse_url_prefix
        source.deadline_timezone = evidence["timezone"]
        source.last_verified_at = timestamp
        source.approval_expires_at = timestamp + timedelta(hours=48)
        source.access_notes = (
            "Factual listings with original links; no full page retention or republication."
            if indexing
            else ("Automatically checked page-level reuse terms: " + evidence["licence_url"])
        )
        if indexing and source.organization.identity_key.startswith("search:"):
            source.organization.name = evidence["organisation"]
            source.organization.country_code = evidence["country"]
    elif source.approval_mode == "automatic":
        source.verification_status = "pending"
        source.permission_status = "unknown"
        source.approval_expires_at = None
        source.collection_adapter = ""
        mark_source_unconfirmed(db, source.id)
    # Keep reason/evidence changes, without repeating an identical decision every day.
    if any(previous.get(key) != report.get(key) for key in ("status", "reasons", "evidence")):
        event(
            db,
            source,
            "automatic_activation" if activated else "automatic_review_needed",
            task_id=task_id,
            reference=source.original_url,
            details=report,
        )
    return activated
