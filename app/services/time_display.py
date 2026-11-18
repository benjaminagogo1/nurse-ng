"""Shared, readable timestamps without changing their recorded clock or date."""

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
