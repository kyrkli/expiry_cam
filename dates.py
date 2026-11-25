"""Helpers for the parser's date strings.

parse_expiry_date() returns one of:
    "27-07-2026"  full date
    "00-07-2026"  month and year only  -> counts as the last day of that month
    "27-07-0000"  day and month only   -> the next such day from the scan date on
"""
import calendar
from datetime import date
from typing import Optional


def _split(parsed: str):
    d, m, y = (int(x) for x in parsed.split("-"))
    return d, m, y


def _end_of_month(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def resolve(parsed: Optional[str], ref: date) -> Optional[date]:
    """Turn a parser string into a real date. ref = day of the scan.
    Returns None if the string is not a valid date."""
    if not parsed:
        return None
    try:
        d, m, y = _split(parsed)
        if not 1 <= m <= 12:
            return None
        if y:                                       # year known
            return _end_of_month(y, m) if d == 0 else date(y, m, d)
        # No year: the first matching date that is not in the past
        for year in range(ref.year, ref.year + 5):  # 5 years covers 29 February
            try:
                candidate = _end_of_month(year, m) if d == 0 else date(year, m, d)
            except ValueError:
                continue
            if candidate >= ref:
                return candidate
        return None
    except ValueError:
        return None


def display(parsed: Optional[str]) -> Optional[str]:
    """'27-07-2026' -> '27.07.2026', '00-07-2026' -> '07/2026', '27-07-0000' -> '27.07.'"""
    if not parsed:
        return None
    try:
        d, m, y = parsed.split("-")
    except ValueError:
        return parsed
    if d == "00":
        return f"{m}/{y}" if y != "0000" else f"{m}/????"
    if y == "0000":
        return f"{d}.{m}."
    return f"{d}.{m}.{y}"