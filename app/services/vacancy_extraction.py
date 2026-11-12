"""Conservative schema.org JobPosting extraction. No model calls or inferred credentials."""

import base64
import hashlib
import json
import re
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.opportunities import programme_type, relevant_opportunity
from app.services.recruitment_fetch import FetchError, in_scope, origin, require_success

MAX_RECORDS = 50
TYPE_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "contract",
    "INTERN": "internship",
}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        elif tag in {"p", "br", "div", "li"} and not self.skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.skip = max(0, self.skip - 1)
        elif tag in {"p", "div", "li"} and not self.skip:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value) -> str:
    if not isinstance(value, str):
        return ""
    parser = PlainText()
    parser.feed(value)
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


class StructuredBlocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.blocks = []
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = (dict(attrs).get("type") or "").split(";")[
                0
            ].lower() == "application/ld+json"
            self.buffer = []

    def handle_data(self, data):
        if self.active:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.blocks.append("".join(self.buffer))
            self.active = False


def extract_records(body: bytes) -> list[dict]:
    parser = StructuredBlocks()
    parser.feed(body.decode("utf-8", errors="replace"))
    records, visited = [], 0
    for block in parser.blocks:
        try:
            nodes = [json.loads(block)]
        except (ValueError, RecursionError):
            raise FetchError(
                "extraction_error", "Invalid structured data; publication was held."
            ) from None
        while nodes:
            node = nodes.pop()
            visited += 1
            if visited > 10000:
                raise FetchError(
                    "extraction_error", "Structured data exceeds the processing limit."
                )
            if isinstance(node, list):
                nodes.extend(reversed(node))
            elif isinstance(node, dict):
                types = node.get("@type", [])
                types = [types] if isinstance(types, str) else types
                if isinstance(types, list) and any(
                    t
                    in {
                        "JobPosting",
                        "https://schema.org/JobPosting",
                        "http://schema.org/JobPosting",
                    }
                    for t in types
                    if isinstance(t, str)
                ):
                    records.append(node)
                    if len(records) > MAX_RECORDS:
                        raise FetchError(
                            "extraction_error", "More than 50 vacancies need a paginated adapter."
                        )
                else:
                    nodes.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return records


def parse_date(value: str, timezone: str, *, closing=False) -> datetime | None:
    if not value:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = datetime.fromisoformat(value).date()
            if closing:
                day += timedelta(days=1)
            return datetime.combine(day, time.min, ZoneInfo(timezone)).astimezone(UTC)
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(UTC)
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return None


def _text(value) -> str:
    if isinstance(value, list):
        return "\n".join(filter(None, (_text(item) for item in value)))
    return plain(value)


def normalize(raw: dict) -> dict:
    employer = raw.get("hiringOrganization")
    location = raw.get("jobLocation")
    locations = location if isinstance(location, list) else [location]
    addresses = [item.get("address", {}) for item in locations if isinstance(item, dict)]
    addresses = [item for item in addresses if isinstance(item, dict)]
    address = addresses[0] if len(addresses) == 1 else {}
    country = address.get("addressCountry", "")
    if isinstance(country, dict):
        country = country.get("identifier", country.get("name", ""))
    if isinstance(country, str):
        country = {"nigeria": "NG", "united kingdom": "GB", "united states": "US",
                   "united states of america": "US", "canada": "CA", "ghana": "GH",
                   "kenya": "KE", "south africa": "ZA", "australia": "AU"}.get(
                       country.strip().casefold(), country.strip()
                   )
    employment = raw.get("employmentType", "")
    if isinstance(employment, list):
        employment = employment[0] if len(employment) == 1 else ""
    result = {
        "title": plain(raw.get("title")),
        "employer": plain(employer.get("name")) if isinstance(employer, dict) else plain(employer),
        "description": plain(raw.get("description")),
        "country": country.upper()
        if isinstance(country, str) and re.fullmatch("[A-Za-z]{2}", country)
        else "",
        "region": plain(address.get("addressRegion")),
        "city": plain(address.get("addressLocality")),
        "announcement_url": raw.get("url", "") if isinstance(raw.get("url"), str) else "",
        "closing_date": raw.get("validThrough", "")
        if isinstance(raw.get("validThrough"), str)
        else "",
        "publication_date": raw.get("datePosted", "")
        if isinstance(raw.get("datePosted"), str)
        else "",
        "opening_date": "",
        "job_type": programme_type(plain(raw.get("title")))
        or (TYPE_MAP.get(employment.upper(), "") if isinstance(employment, str) else ""),
        "employment_type_text": _text(raw.get("employmentType")),
        "work_mode": "remote" if raw.get("jobLocationType") == "TELECOMMUTE" else "",
        "responsibilities": _text(raw.get("responsibilities")),
        "qualifications": _text(raw.get("qualifications")),
        "experience": _text(raw.get("experienceRequirements")),
        # JobPosting has no dedicated professional-registration field. Preserve
        # any such source text in qualifications/description, without inferring it.
        "registration_requirements": "",
        "skills": _text(raw.get("skills")),
        "benefits": _text(raw.get("jobBenefits")),
        "salary": {},
        "application_method": "external",
        "application_url": "",
        "direct_apply_reported": raw.get("directApply")
        if isinstance(raw.get("directApply"), bool)
        else None,
    }
    # A JobPosting URL is an announcement, not proof of a dedicated application endpoint.
    salary = raw.get("baseSalary")
    if isinstance(salary, dict) and isinstance(salary.get("value"), (dict, str, int, float)):
        value = salary["value"] if isinstance(salary["value"], dict) else {"value": salary["value"]}
        currency = salary.get("currency", "")
        unit = value.get("unitText", "")
        currency = currency.strip().upper() if isinstance(currency, str) else currency
        unit = unit.strip().upper() if isinstance(unit, str) else unit
        if (
            isinstance(currency, str)
            and re.fullmatch("[A-Z]{3}", currency)
            and isinstance(unit, str)
            and unit in {"", "HOUR", "DAY", "WEEK", "MONTH", "YEAR"}
        ):
            try:
                numbers = {
                    key: str(Decimal(str(value[key])))
                    for key in ("value", "minValue", "maxValue")
                    if value.get(key) is not None
                }
                if numbers and all(
                    Decimal(n).is_finite() and 0 <= Decimal(n) <= 10**12 for n in numbers.values()
                ):
                    result["salary"] = {"currency": currency, "unit": unit, **numbers}
                    if raw.get("_salary_basis") in {"gross", "net"}:
                        result["salary"]["basis"] = raw["_salary_basis"]
            except InvalidOperation:
                pass
    return result


def validation_issues(
    data: dict, source, *, employer_confirmed=False, nursing_confirmed=False
) -> list[str]:
    from app.services.vacancy_quality import non_vacancy_reason

    issues = []
    excluded = non_vacancy_reason(data.get("title", ""), data.get("announcement_url", ""))
    if excluded:
        issues.append(excluded)
    for field, limit in [("title", 250), ("employer", 250), ("description", 30000)]:
        if not data.get(field) or len(data[field]) > limit:
            issues.append(f"{field}: required, at most {limit} characters")
    if not nursing_confirmed and not relevant_opportunity(data):
        issues.append(
            "nursing: health or Nigerian early-career opportunity relevance requires review"
        )

    def words(value):
        return " ".join(re.findall(r"\w+", value.casefold()))

    indexing = source.collection_adapter == "factual_index"
    if (
        not indexing
        and not employer_confirmed
        and words(data.get("employer", "")) != words(source.organization.name)
    ):
        issues.append("employer: name differs from the approved organisation")
    if not re.fullmatch(r"[A-Z]{2}", data.get("country", "")):
        issues.append("country: an explicit two-letter vacancy country is required")
    if not in_scope(data.get("announcement_url", ""), source.vacancy_url_prefix):
        issues.append("announcement_url: outside the approved vacancy URL scope")
    salary = data.get("salary", {})
    if (
        "minValue" in salary
        and "maxValue" in salary
        and Decimal(salary["minValue"]) > Decimal(salary["maxValue"])
    ):
        issues.append("salary: minimum salary cannot exceed maximum salary")
    timezone = data.get("_index", {}).get("deadline_timezone", source.deadline_timezone)
    closing = parse_date(data.get("closing_date", ""), timezone, closing=True)
    posted = parse_date(data.get("publication_date", ""), timezone)
    opening = parse_date(data.get("opening_date", ""), timezone)
    index = data.get("_index", {}) if indexing else {}
    if closing is None and not (
        index.get("accepting_applications")
        and not data.get("closing_date")
        and not index.get("deadline_unresolved")
    ):
        issues.append("closing_date: missing or ambiguous deadline")
    if index.get("closed"):
        issues.append("closed: the original announcement no longer accepts applications")
    if (posted is None and (not indexing or data.get("publication_date"))) or (
        posted and posted > datetime.now(UTC) + timedelta(minutes=5)
    ):
        issues.append("publication_date: missing, ambiguous or in the future")
    if closing and posted and closing <= posted:
        issues.append("closing_date: deadline is not after publication")
    if data.get("opening_date") and (not opening or (closing and opening >= closing)):
        issues.append("opening_date: invalid application opening date")
    return issues


def collect_page(payload: dict, fetcher) -> dict:
    prefix = payload.get("reuse_url_prefix", "")
    if not prefix or not in_scope(payload["url"], prefix):
        raise FetchError("scope_blocked", "The page has no matching approved reuse scope.")
    if payload.get("collection_adapter") == "factual_index":
        from app.services.factual_opportunities import collect_index
        from app.services.recruitment_indexing import matching_scope, scope_aliases

        evidence = payload.get("index_evidence", {})
        if evidence.get("mode") != "factual_index" or evidence.get("scope") != prefix:
            raise FetchError(
                "scope_blocked", "Factual collection needs its approved source settings."
            )
        page = fetcher.get(payload["url"], allowed_url_prefixes=scope_aliases(prefix))
        resolved_scope = matching_scope(page.url, prefix)
        if not resolved_scope:
            raise FetchError(
                "scope_blocked", "The returned page is outside the approved publisher."
            )
        collected = collect_index(payload, page, fetcher, {**evidence, "scope": resolved_scope})
        return {
            "ok": True,
            "outcome": "vacancies_collected",
            "canonical_hint": "",
            "message": "Collected factual vacancies and original announcement links.",
            **collected,
        }
    page = fetcher.get(
        payload["url"], allowed_origin=origin(payload["url"]), allowed_url_prefix=prefix
    )
    if not in_scope(page.url, prefix):
        raise FetchError("scope_blocked", "The returned page is outside the approved reuse scope.")
    require_success(page)
    if not any(t in page.content_type.lower() for t in ("text/html", "application/xhtml+xml")):
        raise FetchError("unsupported_content", "The structured vacancy adapter requires HTML.")
    # Retain the fetched page before parsing, including extraction failures.
    result = {
        "ok": True,
        "outcome": "vacancies_collected",
        "observed_url": page.url,
        "canonical_hint": "",
        "content_hash": hashlib.sha256(page.body).hexdigest(),
        "body_base64": base64.b64encode(page.body).decode(),
        "message": "Fetched the original vacancy page; extraction and validation follow.",
    }

    if payload.get("collection_adapter") == "announcements":
        from app.services.announcement_extraction import announcement_links

        links = announcement_links(page.body, page.url, prefix)
        offset = int(payload.get("page_offset", 0)) % max(1, len(links))
        chosen = (links[offset:] + links[:offset])[:4]
        result["detail_pages"] = []
        for target in chosen:
            child = collect_page({"url": target, "reuse_url_prefix": prefix}, fetcher)
            result["detail_pages"].append(child)
        result["detail_count"] = len(links)
    return result
