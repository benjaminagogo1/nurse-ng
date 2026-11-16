"""Public opportunity facts only: original prose never leaves the network process."""

import base64
import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from app.services.announcement_extraction import (
    AnnouncementHTML,
    announcement_links,
    explicit_date,
    extract_announcements,
    labelled,
)
from app.services.opportunities import EARLY_CAREER, relevant_opportunity
from app.services.recruitment_fetch import FetchError, in_scope, origin, require_success
from app.services.vacancy_extraction import extract_records, normalize
from app.services.vacancy_quality import (
    canonical_vacancy_record,
    canonical_vacancy_url,
    non_vacancy_reason,
)
from app.services.vacancy_salary import salary_from_text


class ApplicationFacts(HTMLParser):
    """Read factual address properties and a job-bound application form, never submit it."""

    def __init__(self):
        super().__init__()
        self.properties = {}
        self.property = None
        self.form = None
        self.forms = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("itemprop") in {"addressLocality", "addressCountry"}:
            self.property = [tag, attrs["itemprop"], []]
        if tag == "form":
            self.form = {
                "action": attrs.get("action", ""),
                "method": attrs.get("method", "").lower(),
                "job_id": "",
            }
        if (
            tag == "input"
            and self.form is not None
            and attrs.get("name") in {"job_id", "position_id"}
        ):
            self.form["job_id"] = attrs.get("value", "")

    def handle_data(self, data):
        if self.property:
            self.property[2].append(data)

    def handle_endtag(self, tag):
        if self.property and self.property[0] == tag:
            self.properties[self.property[1]] = " ".join("".join(self.property[2]).split())
            self.property = None
        if tag == "form" and self.form is not None:
            self.forms.append(self.form)
            self.form = None


def current_index(page):
    parsed = AnnouncementHTML()
    parsed.feed(page.text)
    return bool(
        re.search(
            r"\b(our job offers|open positions|current vacancies|available vacancies)\b",
            parsed.text,
            re.I,
        )
    )


def index_authorized(source):
    from app.services.recruitment_indexing import staff_index_authorized

    evidence = (source.activation_review or {}).get("evidence", {})
    return bool(
        source.reuse_basis == "factual_index"
        and source.permission_status == "limited"
        and source.collection_adapter == "factual_index"
        and source.allow_collection
        and not source.allow_snapshot_retention
        and not source.allow_republication
        and evidence.get("mode") == "factual_index"
        and evidence.get("scope") == source.reuse_url_prefix
        and evidence.get("requested_url") == source.original_url
        and (
            staff_index_authorized(source)
            or (
                source.approval_mode == "automatic"
                and evidence.get("recruitment_page") == source.observed_url
                and in_scope(source.observed_url, source.reuse_url_prefix)
            )
        )
    )


def prose_deadline(text):
    values = []
    # Bound the phrase so dates elsewhere in an announcement cannot become deadlines.
    pattern = (
        r"(?:deadline|closing date|applications? (?:close|must be (?:received|submitted)))"
        r"[^\n.!?]{0,70}?(\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+"
        r"[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})"
    )
    for value in re.findall(pattern, text, re.I):
        date = explicit_date(value)
        if date:
            values.append(date)
    return values[0] if len(set(values)) == 1 else ""


def factual_records(page, evidence, *, listed_on=""):
    from app.services.recruitment_activation import COUNTRY_TIMEZONES

    parsed = AnnouncementHTML()
    parsed.feed(page.text)
    applications = ApplicationFacts()
    applications.feed(page.text)
    try:
        rows = extract_records(page.body)
    except FetchError:
        rows = []
    # URL aliases still describe one job; differing facts keep the multi-job salary safeguard.
    unique = {}
    for row in rows:
        unique.setdefault(json.dumps(canonical_vacancy_record(row), sort_keys=True), row)
    rows = list(unique.values())
    structured = bool(rows)
    if not rows:
        rows = extract_announcements(page.body, page.url)
    result = []
    for raw in rows:
        data = normalize(raw)
        headings = parsed.main_headings or parsed.headings
        if (
            structured and len(rows) == 1 and not data["announcement_url"]
            and len(headings) == 1 and not non_vacancy_reason(headings[0])
            and data["title"] and data["title"].casefold() in headings[0].casefold()
        ):
            data["announcement_url"] = page.url
        if non_vacancy_reason(data["title"], data["announcement_url"]):
            continue
        if not in_scope(data["announcement_url"], evidence["scope"]):
            continue
        if structured and not relevant_opportunity(data) and not (
            not data["country"] and EARLY_CAREER.search(data["title"])
        ):
            # Publisher sidebars often embed unrelated JobPosting objects. Do not
            # fill the review queue with them. Unknown-country programmes still
            # reach validation; this selection never grants publication eligibility.
            continue
        if not structured:
            # The verified publisher is the organisation offering the announcement.
            if evidence.get("employer_fallback_allowed", True):
                data["employer"] = data["employer"] or evidence["organisation"]
            data["city"] = data["city"] or applications.properties.get("addressLocality", "")
            if not data["country"] and re.search(r"\bNigeria(?:n|ns)?\b", parsed.text, re.I):
                data["country"] = "NG"
            data["closing_date"] = data["closing_date"] or prose_deadline(parsed.text)
        # Ordinary detail pages often state remuneration without JSON-LD salary data.
        # Never apply one page-wide salary to several structured job adverts.
        if not data["salary"] and len(rows) == 1:
            data["salary"] = salary_from_text(parsed.text)
        deadline_text = labelled(
            parsed.text, r"application deadline|closing date|deadline|applications close"
        )
        active_form = bool(
            listed_on
            and any(
                form["method"] == "post"
                and form["job_id"]
                and re.search(r"(?:job|application|eligibility)", form["action"], re.I)
                and in_scope(urljoin(page.url, form["action"]), evidence["scope"])
                for form in applications.forms
            )
        )
        closed = bool(
            re.search(
                r"\b(applications? (?:are |is |now )?closed|no longer accepting applications|"
                r"position (?:is |has been )?filled)\b",
                parsed.text,
                re.I,
            )
        )
        summary = (
            (f"{data['employer']} has published this opportunity"
             if data['employer'] else "This opportunity was published")
            + (
                f" in {'Nigeria' if data['country'] == 'NG' else data['country']}"
                if data["country"]
                else ""
            )
            + ". Read the original announcement for eligibility, responsibilities "
            "and application instructions."
        )
        # Explicit allowlist: do not retain descriptions, qualifications, arbitrary JSON-LD,
        # email addresses or any other original prose in snapshots, records or audit events.
        fact = {
            "@type": "JobPosting",
            "url": data["announcement_url"],
            "title": data["title"][:250],
            "hiringOrganization": {"name": data["employer"][:250]},
            "description": summary,
            "jobLocation": {
                "address": {
                    "addressCountry": data["country"],
                    "addressRegion": data["region"][:250],
                    "addressLocality": data["city"][:250],
                }
            },
            "datePosted": data["publication_date"],
            "validThrough": data["closing_date"],
            "_index": {
                "publisher": evidence["organisation"],
                "source_url": page.url,
                "publication_date_stated": bool(data["publication_date"]),
                "deadline_timezone": COUNTRY_TIMEZONES.get(data["country"], ""),
                "accepting_applications": active_form and not closed,
                "listed_on": listed_on,
                "deadline_unresolved": bool(deadline_text and not data["closing_date"]),
                "closed": closed,
            },
        }
        identifier = raw.get("identifier")
        if isinstance(identifier, dict):
            identifier = identifier.get("value")
        if isinstance(identifier, (str, int)):
            fact["identifier"] = str(identifier)[:500]
        # Keep salary validation effective without republishing copied prose.
        if data["salary"]:
            fact["baseSalary"] = {
                "currency": data["salary"]["currency"],
                "value": {
                    "unitText": data["salary"]["unit"],
                    **{k: v for k, v in data["salary"].items()
                       if k in {"value", "minValue", "maxValue"}},
                },
            }
            if data["salary"].get("basis"):
                fact["_salary_basis"] = data["salary"]["basis"]
        if structured and isinstance(raw.get("employmentType"), str):
            fact["employmentType"] = raw["employmentType"][:40]
        result.append(fact)
    return result


def page_facts(page, evidence, *, listed_on=""):
    require_success(page)
    if "html" not in page.content_type.lower() or not in_scope(page.url, evidence["scope"]):
        raise FetchError(
            "scope_blocked", "Indexing requires HTML within the verified publisher scope."
        )
    body = json.dumps(
        {"url": page.url, "records": factual_records(page, evidence, listed_on=listed_on)},
        sort_keys=True,
    ).encode()
    return {
        "observed_url": page.url,
        "body_base64": base64.b64encode(body).decode(),
        "content_hash": hashlib.sha256(body).hexdigest(),
        "original_content_hash": hashlib.sha256(page.body).hexdigest(),
    }


def collect_index(payload, page, fetcher, evidence):
    from app.services.recruitment_discovery import CAREER_WORDS, PageLinks, _safe_link

    result = page_facts(page, evidence)
    links = announcement_links(
        page.body, page.url, evidence["scope"], include_channels=True,
        page_offset=int(payload.get("page_offset", 0)),
    )
    result.update(detail_pages=[], detail_errors=[], detail_count=len(links), links=[])

    def discover_portals(observed):
        parsed = PageLinks()
        parsed.feed(observed.text)
        known = {link['url'] for link in result['links']}
        for href, label in parsed.links:
            external = _safe_link(observed.url, href)
            if (external and external not in known
                    and not in_scope(external, evidence['scope'])
                    and CAREER_WORDS.search(href.replace('-', ' ') + ' ' + label)
                    and len(result['links']) < 3):
                result['links'].append({'url': external, 'label': label,
                                        'reference': observed.url})
                known.add(external)

    discover_portals(page)
    pending = [
        (url, 1, page.url if current_index(page) else "", False)
        for url in links
    ]
    channel = evidence.get("collection_channel", "")
    if channel:
        if not in_scope(channel, evidence["scope"]):
            raise FetchError("scope_blocked", "The selected channel is outside approved scope.")
        channel = canonical_vacancy_url(channel)
        if channel != canonical_vacancy_url(page.url):
            # A current recruitment channel can be more useful than the publisher's
            # original discovery page. It uses one of the existing four requests.
            pending.insert(0, (channel, 0, "", True))
    seen = {canonical_vacancy_url(page.url)}
    checked = 0
    while pending and checked < 4:
        target, depth, listed_on, selected_channel = pending.pop(0)
        if target in seen:
            continue
        seen.add(target)
        checked += 1
        try:
            child = fetcher.get(
                target, allowed_origin=origin(page.url), allowed_url_prefix=evidence["scope"]
            )
            seen.add(canonical_vacancy_url(child.url))
            result["detail_pages"].append(page_facts(child, evidence, listed_on=listed_on))
            discover_portals(child)
            if depth < 2:
                children = announcement_links(
                    child.body, child.url, evidence["scope"], include_channels=True,
                    page_offset=int(payload.get("page_offset", 0)),
                )
                descendants = [
                    (url, depth + 1, child.url if current_index(child) else "", False)
                    for url in children
                ]
                if selected_channel:
                    pending[0:0] = descendants
                else:
                    pending.extend(descendants)
        except FetchError as exc:
            result["detail_errors"].append({"url": target, "outcome": exc.code})
    return result
