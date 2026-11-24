"""Directory/search adapters and bounded recruitment-page inspection.

Adapters return observations, never source approval or vacancy publication.

Network work runs through the isolated recruitment worker. Directory/search
observations are candidates; recruitment_activation and vacancies separately
decide whether a source may collect or publish.
"""

import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin
from xml.etree import ElementTree

from app.services.recruitment_fetch import (
    FetchError,
    PublicFetcher,
    origin,
    public_url,
    require_success,
    url_key,
)

CAREER_WORDS = re.compile(
    r"\b(careers?|recruitment|vacanc(?:y|ies)|jobs?|internships?|fellows?(?:hip)?s?|"
    r"traineeships?|graduate[ -]+programmes?|digital[ -]+health|emploi|recrutement|"
    r"carri[eè]res?|vacantes|empleos?|vagas|carreiras?|recrutamento)\b",
    re.I,
)
TERMS_WORDS = re.compile(r"\b(terms|copyright|privacy|conditions|legal)\b", re.I)
NIGERIAN_REGIONS = (
    "Abia",
    "Adamawa",
    "Akwa Ibom",
    "Anambra",
    "Bauchi",
    "Bayelsa",
    "Benue",
    "Borno",
    "Cross River",
    "Delta",
    "Ebonyi",
    "Edo",
    "Ekiti",
    "Enugu",
    "Gombe",
    "Imo",
    "Jigawa",
    "Kaduna",
    "Kano",
    "Katsina",
    "Kebbi",
    "Kogi",
    "Kwara",
    "Lagos",
    "Nasarawa",
    "Niger",
    "Ogun",
    "Ondo",
    "Osun",
    "Oyo",
    "Plateau",
    "Rivers",
    "Sokoto",
    "Taraba",
    "Yobe",
    "Zamfara",
    "Federal Capital Territory Abuja",
)
DISCOVERY_CATEGORIES = (
    "ministry of health",
    "health service commission",
    "teaching hospital",
    "Federal Medical Centre",
    "specialist hospital",
    "private hospital",
    "healthcare organisation",
    "licensed healthcare recruitment agency",
    "government recruitment",
    "youth fellowship programme",
    "digital health programme",
    "public health internship",
    "healthcare graduate trainee programme",
    "federal health recruitment",
    "state primary healthcare recruitment",
    "graduate internship programme",
    "NGO health careers",
    "NGO internship and volunteer programme",
    "midwifery recruitment",
    "allied healthcare careers",
)


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.canonical = ""
        self.title = ""
        self._in_title = False
        self._anchor = ""
        self._label = ""
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attributes = {key: value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            self._anchor, self._label = attributes.get("href", ""), ""
        if tag == "link" and attributes.get("rel", "").lower() == "canonical":
            self.canonical = attributes.get("href", "")
        if (
            len(self.links) < 2000
            and tag == "link"
            and attributes.get("type", "")
            in {
                "application/rss+xml",
                "application/atom+xml",
            }
        ):
            self.links.append((attributes.get("href", ""), attributes.get("title", "")))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self._skip = max(0, self._skip - 1)
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._anchor:
            if len(self.links) < 2000:
                self.links.append((self._anchor, self._label.strip()[:200]))
            self._anchor, self._label = "", ""

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title = (self.title + data)[:300]
        if self._anchor:
            self._label = (self._label + " " + data)[:300]


def _safe_link(base: str, link: str) -> str:
    try:
        return public_url(urljoin(base, link))
    except (FetchError, ValueError):
        return ""


def _json_response(fetcher, url: str, *, headers=None) -> dict:
    page = fetcher.get(url, robots=False, allowed_origin=origin(url), headers=headers)
    require_success(page)
    try:
        data = json.loads(page.text)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, TypeError):
        raise FetchError(
            "extraction_error", "The directory returned an invalid response."
        ) from None


def ror_discovery(payload: dict, fetcher) -> dict:
    filters = ["types:healthcare"]
    if payload.get("country_code"):
        filters.append("locations.geonames_details.country_code:" + payload["country_code"])
    parameters = {"filter": ",".join(filters), "page": payload.get("page", 1)}
    if payload.get("query"):
        parameters["query"] = payload["query"]
    url = "https://api.ror.org/v2/organizations?" + urlencode(parameters)
    data = _json_response(fetcher, url)
    items = data.get("items")
    if not isinstance(items, list):
        raise FetchError("extraction_error", "The directory did not return an organisation list.")
    candidates = []
    skipped = 0
    for row in items[:20]:
        try:
            if "healthcare" not in row.get("types", []):
                raise ValueError
            identity = row["id"]
            if not re.fullmatch(r"https://ror.org/[a-z0-9]{9}", identity):
                raise ValueError
            name = next(x["value"] for x in row["names"] if "ror_display" in x["types"])
            website = next(x["value"] for x in row["links"] if x["type"] == "website")
            public_url(website)
            geo = (row.get("locations") or [{}])[0].get("geonames_details", {})
            code = geo.get("country_code", "")
            if not re.fullmatch(r"[A-Z]{2}", code):
                code = ""
            candidates.append(
                {
                    "identity_key": identity,
                    "name": str(name)[:250],
                    "category": "healthcare",
                    "country_code": code,
                    "location": str(geo.get("name", ""))[:250],
                    "website_url": website,
                    "source_url": website,
                    "discovered_via": "ror",
                    "reference": identity,
                    "source_type": "institution_site",
                    "evidence": {
                        "directory_query": url,
                        "licence": "ROR metadata: CC0",
                        "registry_id": identity,
                    },
                }
            )
        except (KeyError, TypeError, ValueError, StopIteration, AttributeError):
            skipped += 1
    total = data.get("number_of_results", 0)
    if not isinstance(total, int) or total < 0:
        raise FetchError("extraction_error", "The directory returned an invalid result count.")
    next_page = payload.get("page", 1) + 1
    if next_page > 500 or (next_page - 1) * 20 >= total:
        next_page = 1
    return {
        "ok": True,
        "outcome": "directory_checked",
        "candidates": candidates,
        "next_page": next_page,
        "skipped": skipped,
        "reference": url,
        "message": f"Checked {len(items[:20])} directory records; {skipped} could not be used.",
    }


def search_query(payload: dict) -> str:
    index = max(0, payload.get("page", 1) - 1)
    # Visit every category before moving to the next region, with a national
    # round as well. Fellowships must not wait months behind hospital searches.
    regions = ("", *NIGERIAN_REGIONS)
    region = (
        regions[(index // len(DISCOVERY_CATEGORIES) if '{category}' in payload['query']
                 else index) % len(regions)]
        if payload.get("country_code") == "NG"
        else ""
    )
    category_index = index
    category = DISCOVERY_CATEGORIES[category_index % len(DISCOVERY_CATEGORIES)]
    text = payload["query"]
    for token, value in {
        "{region}": region,
        "{category}": category,
        "{country}": "Nigeria"
        if payload.get("country_code") == "NG"
        else payload.get("country_code", ""),
    }.items():
        text = text.replace(token, value)
    return " ".join(text.split())[:400]


def brave_discovery(payload: dict, fetcher, *, key: str, permission: str) -> dict:
    if not key or not permission:
        raise FetchError(
            "configuration_needed",
            "Search is disabled until its key and storage permission are configured.",
        )
    query = search_query(payload)
    url = "https://api.search.brave.com/res/v1/web/search?" + urlencode({"q": query, "count": 20})
    data = _json_response(fetcher, url, headers={"X-Subscription-Token": key})
    results = data.get("web", {}).get("results", [])
    if not isinstance(results, list):
        raise FetchError("extraction_error", "The search provider returned invalid results.")
    from app.services.recruitment_search import candidates_from_results

    candidates = candidates_from_results(
        results,
        query=query,
        provider="brave",
        permission=permission,
        target_country=payload.get("country_code", ""),
    )
    return {
        "ok": True,
        "outcome": "search_checked",
        "candidates": candidates,
        "next_page": payload.get("page", 1)
        % ((len(NIGERIAN_REGIONS) + 1) * len(DISCOVERY_CATEGORIES))
        + 1,
        "message": f"Found {len(candidates)} candidate pages for review.",
    }


def inspect_source(payload: dict, fetcher) -> dict:
    # Discovery records public redirects. Collection remains constrained to approved scope.
    page = fetcher.get(payload["url"])
    require_success(page)
    if not any(t in page.content_type.lower() for t in ("text/html", "application/xhtml+xml")):
        raise FetchError(
            "unsupported_content", "This checker supports HTML recruitment pages only."
        )
    parsed = PageLinks()
    parsed.feed(page.text)
    links, terms, documents, seen = [], [], [], set()
    for href, label in parsed.links:
        target = _safe_link(page.url, href)
        if not target or url_key(target) in seen or url_key(target) == url_key(payload["url"]):
            continue
        seen.add(url_key(target))
        if CAREER_WORDS.search(href.replace("-", " ").replace("_", " ") + " " + label):
            links.append({"url": target, "label": label[:200]})
            if re.search(r"\.(?:pdf|docx?)(?:[?#]|$)", target, re.I):
                documents.append({"url": target, "label": label[:200]})
        elif re.search(r"\.(?:pdf|docx?)(?:[?#]|$)", target, re.I) and re.search(
            r"\b(application|vacancy|recruitment|fellowship|internship)\b", label, re.I
        ):
            documents.append({"url": target, "label": label[:200]})
        elif TERMS_WORDS.search(label):
            terms.append(target)
    sitemap_note = ""
    if not links and payload.get("source_type") == "institution_site":
        try:
            sitemap = fetcher.get(origin(page.url) + "/sitemap.xml")
            if sitemap.status == 200 and "<!DOCTYPE" not in sitemap.text.upper():
                root = ElementTree.fromstring(sitemap.body)
                for element in root.iter():
                    if element.tag.rsplit("}", 1)[-1] == "loc" and element.text:
                        target = _safe_link(page.url, element.text.strip())
                        if target and CAREER_WORDS.search(target.replace("-", " ")):
                            links.append(
                                {"url": target, "label": "Recruitment-related sitemap URL"}
                            )
                        if len(links) >= 3:
                            break
        except (FetchError, ElementTree.ParseError):
            sitemap_note = "No usable recruitment sitemap was available."
    result = {
        "ok": True,
        "outcome": "page_checked",
        "observed_url": page.url,
        "canonical_hint": _safe_link(page.url, parsed.canonical) if parsed.canonical else "",
        "content_hash": hashlib.sha256(page.body).hexdigest(),
        "title": parsed.title.strip(),
        "links": links[:3],
        "terms_links": terms[:3],
        "document_links": documents[:10],
        "sitemap_note": sitemap_note,
        "message": "Page inspected. No vacancy or verification decision was created.",
    }
    from app.services.recruitment_activation import attach_assessment

    return attach_assessment(payload, page, fetcher, result)


def execute_discovery(
    kind: str, payload: dict, *, fetcher=None, search_key: str = "", search_permission: str = ""
) -> dict:
    fetcher = fetcher or PublicFetcher()
    try:
        if kind == "ror":
            return ror_discovery(payload, fetcher)
        if kind == "brave":
            return brave_discovery(payload, fetcher, key=search_key, permission=search_permission)
        if kind == "search":
            from app.services.recruitment_search import general_search

            return general_search(payload, fetcher, key=search_key, permission=search_permission)
        if kind == "inspect":
            if payload.get("collect_vacancies"):
                from app.services.vacancy_extraction import collect_page

                return collect_page(payload, fetcher)
            return inspect_source(payload, fetcher)
        raise FetchError("unsupported_task", "Unsupported discovery task.")
    except FetchError as exc:
        return {
            "ok": False,
            "outcome": exc.code,
            "message": str(exc),
            "retryable": exc.retryable,
            "retry_after": exc.retry_after,
        }
