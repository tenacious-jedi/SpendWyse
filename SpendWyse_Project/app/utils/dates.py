from datetime import date
from typing import Optional


def parse_date(value: str) -> Optional[date]:
    """Parse a YYYY-MM-DD string, returning None on anything unparseable."""
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def parse_month(value: str) -> Optional[tuple[int, int]]:
    """Parse a YYYY-MM string into (year, month), or None if invalid.

    The year is upper-bounded to date's own range (max 9999); otherwise a
    value like 99999 would parse here and then raise ValueError when a date
    is built from it downstream.
    """
    try:
        y, m = value.split("-")
        year, month = int(y), int(m)
    except (ValueError, AttributeError):
        return None
    if not (1 <= month <= 12 and 1900 < year <= 9999):
        return None
    return year, month
