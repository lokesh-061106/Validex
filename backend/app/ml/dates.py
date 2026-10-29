"""Tolerant date parsing for Indian document formats."""

import re
from datetime import date, datetime

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# Regex fragment matching any supported date format (used by extractors)
DATE_PATTERN = (
    r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}(?:st|nd|rd|th)?[\s\-]+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s\-,]+\d{4})"
)


def parse_date(value: str | None) -> date | None:
    """Parse DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, YYYY-MM-DD, '31 December 2026', '31-Dec-2026'."""
    if not value:
        return None
    s = value.strip().lower().replace(",", " ")
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        return _safe(y, mo, d)
    m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
    if m:
        d, mo, y = map(int, m.groups())  # Indian convention: day first
        return _safe(y, mo, d)
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([a-z]+)[\s\-]+(\d{4})", s)
    if m:
        d, mon, y = m.groups()
        mo = MONTHS.get(mon[:3])
        if mo:
            return _safe(int(y), mo, int(d))
    return None


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def to_iso(value: str | None) -> str | None:
    d = parse_date(value)
    return d.isoformat() if d else None


def today() -> date:
    return datetime.now().date()
