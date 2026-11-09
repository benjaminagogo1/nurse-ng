"""Event validation and portable calendar downloads."""

from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models.events import CommunityEvent

LAGOS = ZoneInfo("Africa/Lagos")


def local_time(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(LAGOS)


def upcoming(db, limit=25, offset=0):
    return list(
        db.scalars(
            select(CommunityEvent)
            .where(
                CommunityEvent.status == "scheduled",
                CommunityEvent.ends_at > datetime.now(UTC),
            )
            .order_by(CommunityEvent.starts_at, CommunityEvent.id)
            .offset(offset)
            .limit(limit)
        )
    )


def validated(values):
    result = {}
    for field, label, maximum in (
        ("title", "title", 160),
        ("description", "description", 5000),
        ("location", "location or online joining instructions", 240),
    ):
        value = values.get(field, "").strip()
        if not value or len(value) > maximum:
            raise ValueError(f"Enter the event {label} (up to {maximum} characters).")
        result[field] = value
    try:
        for field in ("starts_at", "ends_at"):
            value = datetime.fromisoformat(values.get(field, ""))
            if value.tzinfo is None:
                value = value.replace(tzinfo=LAGOS)
            result[field] = value.astimezone(UTC)
    except ValueError:
        raise ValueError("Enter valid start and end dates. Times are in Nigeria (WAT).") from None
    if result["ends_at"] <= result["starts_at"]:
        raise ValueError("The event must end after it starts.")
    if result["ends_at"] <= datetime.now(UTC):
        raise ValueError("Choose an event end time in the future.")
    url = values.get("registration_url", "").strip()
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme == "https" and parsed.hostname and not parsed.username
    except ValueError:
        valid = False
    if url and (not valid or len(url) > 2048 or any(ord(c) < 33 for c in url)):
        raise ValueError("Use a complete HTTPS registration link, or leave it blank.")
    result["registration_url"] = url
    return result


def calendar(event):
    def escape(value):
        return (
            value.replace("\\", "\\\\")
            .replace("\r", "")
            .replace("\n", "\\n")
            .replace(
                ";",
                "\\;",
            )
            .replace(",", "\\,")
        )

    def utc(value):
        return local_time(value).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Nurse.ng//Community events//EN",
        "BEGIN:VEVENT",
        f"UID:{event.id}@nurse.ng",
        f"DTSTAMP:{utc(event.updated_at)}",
        f"DTSTART:{utc(event.starts_at)}",
        f"DTEND:{utc(event.ends_at)}",
        "SUMMARY:" + escape(event.title),
        "DESCRIPTION:" + escape(event.description),
        "LOCATION:" + escape(event.location),
        "STATUS:" + ("CANCELLED" if event.status == "cancelled" else "CONFIRMED"),
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    # RFC 5545 folds at 75 octets without splitting a UTF-8 character.
    folded = []
    for line in lines:
        part = ""
        for char in line:
            if len((part + char).encode()) > 75:
                folded.append(part)
                part = " "
            part += char
        folded.append(part)
    return "\r\n".join(folded) + "\r\n"
