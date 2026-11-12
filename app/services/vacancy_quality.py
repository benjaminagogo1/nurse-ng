"""Conservative exclusions for pages that do not describe individual opportunities."""

import re
from urllib.parse import unquote, urlsplit, urlunsplit

from app.services.recruitment_fetch import public_url

ROLE_OR_PROGRAMME = re.compile(
    r"\b(?:nurses?|midwi(?:fe|ves)|doctors?|physicians?|pharmacists?|dentists?|"
    r"scientists?|technicians?|technologists?|radiographers?|officers?|assistants?|"
    r"workers?|attendants?|caregivers?|aides?|therapists?|educators?|instructors?|trainers?|"
    r"consultants?|specialists?|managers?|directors?|coordinators?|analysts?|"
    r"supervisors?|practitioners?|researchers?|lecturers?|residen(?:t|ts|cy)|"
    r"interns?(?:hip)?s?|fellows?(?:hip)?s?|trainees?(?:hip)?s?|apprentice\w*|"
    r"volunteers?|recruitment|vacanc(?:y|ies)|graduate[ -]+(?:programmes?|programs?|schemes?))\b",
    re.I,
)


def announcement_intent(title: str, text: str = "", url: str = "") -> bool:
    """Health words and a generic Apply link alone do not establish a job advert."""
    if ROLE_OR_PROGRAMME.search(title) or re.search(
        r"^(?:job title|position|role|vacancy|requisition(?: id)?)\s*[:–-]\s*\S",
        text, re.I | re.M,
    ):
        return True
    try:
        return bool(re.search(r"/(?:jobs?|positions?|vacanc(?:y|ies))/[^/]+", urlsplit(url).path))
    except ValueError:
        return False


def canonical_vacancy_url(value: str) -> str:
    """Ignore known advertising tags, retaining every parameter that may identify a job."""
    try:
        parts = urlsplit(public_url(value))
    except ValueError:
        # Invalid records still reach validation; identity normalization grants no fetch rights.
        return value
    query = []
    for part in parts.query.split("&"):
        name = unquote(part.split("=", 1)[0]).casefold()
        if name.startswith("utm_") or name in {"gclid", "fbclid", "msclkid"}:
            continue
        if part:
            query.append(part)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query), ""))


def non_vacancy_reason(title: str, url: str = "") -> str:
    """Do not confuse admissions, service pages or search categories with job adverts.

    This intentionally does not invent an employer, deadline, or vacancy status.
    Uncertain individual opportunities still go through the normal validation checks.
    """
    title = " ".join((title or "").split())
    try:
        parts = urlsplit(url)
        if (parts.hostname or "").removeprefix("www.") == "myjobmag.com" and re.search(
            r"^/jobs-(?:at|by-[^/]+|in)/", parts.path,
        ):
            return "category: this is a publisher's employer or jobs category page"
    except ValueError:
        pass
    if re.search(
        r"\b(?:school|college|university)\b.*\b(?:admission|entrance|forms?\b.*sale)",
        title, re.I,
    ) or re.search(r"\b(?:admission|entrance)\s+(?:forms?|exams?|examinations?)\b", title, re.I):
        return "admissions: an admission or school application notice is not a job vacancy"
    if re.fullmatch(r"(?:medical\s+)?library\s+services?", title, re.I):
        return "service: this title describes a library service, not a vacancy"
    if (re.search(r"\bshort[ -]course\b", title, re.I) and not ROLE_OR_PROGRAMME.search(title)) or (
        re.fullmatch(r"medical education", title, re.I)
        or re.match(r"^(?:the )?graduate school\b", title, re.I)
    ):
        return "education: this is a course or school page, not a job vacancy"
    if re.fullmatch(r"(?:non[ -])?clinical professionals", title, re.I) or re.match(
        r"^nursing at\s+", title, re.I,
    ):
        return "category: this is a recruitment channel, not an individual vacancy"
    if re.search(r"\b(?:jobs|vacancies)\s+(?:in|by)\s+[^.!?]{1,80}$", title, re.I):
        return "category: this is a jobs category or search page"
    if re.fullmatch(
        r"(?:(?:all|current|available|latest|graduate|nursing|healthcare|medical)\s+)*"
        r"(?:jobs|vacancies|opportunities|careers)", title, re.I,
    ):
        return "category: this is a recruitment channel, not an individual vacancy"
    return ""
