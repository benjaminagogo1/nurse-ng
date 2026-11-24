"""Shared, readable timestamps without changing their recorded clock or date.

The saved UTC instant is formatted without mutating its value. The browser
NurseTime formatter follows the same display convention; calendar-date-only
formatting is a separate template filter.
"""

from datetime import datetime

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def display_datetime(value: datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            return value
    period = "AM" if value.hour < 12 else "PM"
    return (
        f"{value.day:02d} {MONTHS[value.month - 1]} {value.year} "
        f"{value.hour % 12 or 12:02d}:{value.minute:02d} {period}"
    )
