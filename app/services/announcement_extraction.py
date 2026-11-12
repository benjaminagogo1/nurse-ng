"""Evidence-based extraction from ordinary announcement pages within approved scope."""

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from app.services.opportunities import relevant_opportunity
from app.services.recruitment_fetch import in_scope, public_url, url_key
from app.services.vacancy_extraction import normalize
from app.services.vacancy_quality import announcement_intent, non_vacancy_reason


class AnnouncementHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.headings, self.links, self.meta = [], [], [], {}
        self.skip = 0
        self.heading = None
        self.anchor = None
        self.main_depth = 0
        self.main_parts = []
        self.main_headings = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "nav", "footer", "header"}:
            self.skip += 1
        if tag in {"main", "article"}:
            self.main_depth += 1
        if self.skip:
            return
        if tag == "meta":
            key = values.get("property") or values.get("name") or ""
            self.meta.setdefault(key.lower(), values.get("content") or "")
        if tag == "h1":
            self.heading = []
        if tag == "a":
            self.anchor = [values.get("href") or "", []]
        if tag in {"p", "div", "li", "br", "dt", "dd", "h1", "h2", "tr"}:
            self._append("\n")
        if tag == "time" and self.main_depth and values.get("datetime"):
            self.meta.setdefault("article:published_time", values["datetime"])

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "nav", "footer", "header"}:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "h1" and self.heading is not None:
            heading = " ".join("".join(self.heading).split())
            self.headings.append(heading)
            if self.main_depth:
                self.main_headings.append(heading)
            self.heading = None
        if tag == "a" and self.anchor:
            self.links.append((self.anchor[0], " ".join("".join(self.anchor[1]).split())))
            self.anchor = None
        if tag in {"p", "div", "li", "dt", "dd", "h1", "h2", "tr"}:
            self._append("\n")
        if tag in {"main", "article"}:
            self.main_depth = max(0, self.main_depth - 1)

    def _append(self, value):
        self.parts.append(value)
        if self.main_depth:
            self.main_parts.append(value)

    def handle_data(self, data):
        if self.skip:
            return
        self._append(data)
        if self.heading is not None:
            self.heading.append(data)
        if self.anchor:
            self.anchor[1].append(data)

    @property
    def text(self):
        return "\n".join(
            " ".join(line.split())
            for line in "".join(self.main_parts or self.parts).splitlines()
            if line.strip()
        )


def explicit_date(value):
    """Only ISO or a named month with an explicit year; never guess numeric dates."""
    value = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", value.strip(), flags=re.I)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.+)?", value):
        return value
    for pattern in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    return ""


def labelled(text, labels):
    values = re.findall(r"^(?:" + labels + r")[ \t]*[:–-][ \t]*([^\n]+)$", text, flags=re.I | re.M)
    unique = set(value.strip() for value in values)
    return next(iter(unique)) if len(unique) == 1 else ""


def extract_announcements(body: bytes, url: str) -> list[dict]:
    parsed = AnnouncementHTML()
    parsed.feed(body.decode("utf-8", errors="replace"))
    headings = parsed.main_headings or parsed.headings
    if not headings and parsed.meta.get("og:title"):
        headings = [parsed.meta["og:title"]]
    if len(headings) != 1:
        return []
    title, text = headings[0], parsed.text
    if non_vacancy_reason(title, url) or not announcement_intent(title, text, url):
        return []
    if not relevant_opportunity({"title": title, "country": "NG"}):
        return []
    if not re.search(r"\b(apply|applications?|recruit(?:ing|ment)?|vacanc(?:y|ies))\b", text, re.I):
        return []
    location = labelled(
        text, r"location|job location|programme location|program location|duty station"
    )
    country = labelled(text, r"country")
    if country.casefold() in {"ng", "nigeria"}:
        country = "NG"
    elif not country and re.search(r"\bNigeria\b", location, re.I):
        country = "NG"
    elif not re.fullmatch(r"[A-Z]{2}", country):
        country = ""
    # Names and dates remain empty when not present, sending the record to review.
    raw = {
        "@type": "JobPosting",
        "url": url,
        "title": title,
        "description": text,
        "hiringOrganization": {"name": labelled(text, r"employer|organi[sz]ation|institution")},
        "jobLocation": {"address": {"addressCountry": country, "addressLocality": location}},
        "datePosted": explicit_date(
            labelled(text, r"published|publication date|date posted")
            or parsed.meta.get("article:published_time", "")
        ),
        "validThrough": explicit_date(
            labelled(text, r"application deadline|closing date|deadline|applications close")
        ),
        "_adapter": "announcements-v1",
    }
    # Preserve the original evidence for review; normalize performs no new inference.
    normalize(raw)
    return [raw]


def announcement_links(body: bytes, url: str, prefix: str, *, include_channels=False) -> list[str]:
    parsed = AnnouncementHTML()
    parsed.feed(body.decode("utf-8", errors="replace"))
    result, seen = [], {url_key(url)}
    priority = {}
    links = parsed.links
    if include_channels:
        from app.services.recruitment_discovery import CAREER_WORDS, PageLinks

        all_links = PageLinks()
        all_links.feed(body.decode("utf-8", errors="replace"))
        links = all_links.links
    for href, label in links:
        target = urljoin(url, href)
        excluded = non_vacancy_reason(label, target)
        # Category pages may lead to real adverts; admissions and service links do not.
        if excluded and (not include_channels or not excluded.startswith("category:")):
            continue
        individual = relevant_opportunity({"title": label, "country": "NG"}) and (
            announcement_intent(label, url=target)
        )
        if not individual and not (
            include_channels and (
                excluded.startswith("category:")
                or CAREER_WORDS.search(label + " " + href.replace("-", " "))
            )
        ):
            continue
        try:
            target = public_url(target)
        except ValueError:
            continue
        if (
            urlsplit(target)
            .path.lower()
            .endswith((".pdf", ".doc", ".docx", ".zip", ".jpg", ".png"))
        ):
            continue
        if not in_scope(target, prefix) or url_key(target) in seen:
            continue
        seen.add(url_key(target))
        result.append(target)
        priority[target] = (
            2 if excluded else 0 if individual else 1
        )
    return sorted(result, key=priority.get) if include_channels else result
