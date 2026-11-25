import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

# Labels in front of a date. The words are matched in the text between the previous
# number and the date, so "Herg. 12.03.2025 MHD 12.03.2027" labels each date correctly.
_EXPIRY_LABEL = re.compile(
    r"mhd|mindestens|haltbar|verbrauch|verwend|verw\b|ablauf|\bbis\b|best\s*before|best\s*by"
    r"|\bbbe\b|\bexp|use\s*by"
    r"|b?bf\W*$|\bbb\W*$"                  # BBF: / BF: / BB: right in front of the date
)
# Production dates and lot numbers: never the expiry date if there is another date
_NOT_EXPIRY_LABEL = re.compile(
    r"herg|herst|produziert|produktionsdatum|prod\b|prod\.|abgef[uü]llt|abgepackt|verpackt"
    r"|packed|pack\s*date|\bmfg|\bmfd|manufactur"
    r"|\blot|charge|batch"                   # lot numbers often look like a glued date
)
# A lone "L" right in front of a number is a lot number ("L 270728"), but not "0,5l 12.03.2027"
_LOT_L = re.compile(r"(?<!\w)l\W*$")
_LABEL_WINDOW = 30        # characters in front of a date that are searched for a label


@dataclass
class _Candidate:
    dt: datetime
    date_type: str        # FULL, MM_YYYY or DD_MM
    d: int
    m: int
    y: int
    priority: int         # 3 = full with separators ... 0 = guessed
    start: int            # position in the text
    end: int
    expiry_label: bool = False
    production_label: bool = False


def _normalize_year(y: int) -> int:
    if y == 0:
        return 0
    if y < 100:
        return 2000 + y
    return y


def _is_past(c: _Candidate, today: date) -> bool:
    """True if the candidate is already over on 'today' (a date without a year never is)."""
    if c.date_type == "DD_MM":
        return False
    if c.date_type == "MM_YYYY":
        return date(c.y, c.m, monthrange(c.y, c.m)[1]) < today
    return date(c.y, c.m, c.d) < today


def _overlaps(a: _Candidate, b: _Candidate) -> bool:
    return a.start < b.end and b.start < a.end


def _drop_past(candidates: List[_Candidate], today: date) -> List[_Candidate]:
    """Remove dates that are already over (usually the production date), together with
    their parts ("11.2026" inside "20.11.2026"), but only if a proper date with a year
    remains. A glued number alone never replaces a real date: it may be a lot number."""
    past = [c for c in candidates if c.date_type != "DD_MM" and _is_past(c, today)]
    rest = [c for c in candidates if c not in past
            and not any(p.date_type == "FULL" and _overlaps(p, c) for p in past)]
    if any(c.priority >= 2 and c.date_type != "DD_MM" for c in rest):
        return rest
    return candidates


def _label_candidates(text: str, found: List[_Candidate]) -> None:
    """Mark dates that follow an expiry label (MHD, haltbar bis, BBF, ...) or a production
    or lot label (Herg., hergestellt, LOT, Charge, ...)."""
    for c in found:
        window = text[max(0, c.start - _LABEL_WINDOW):c.start]
        before = re.split(r"\d", window)[-1]          # only the text after the previous number
        if _EXPIRY_LABEL.search(before):
            c.expiry_label = True                     # an expiry label wins over a production word
        elif _NOT_EXPIRY_LABEL.search(before) or _LOT_L.search(window):
            c.production_label = True
    # Parts of a date (e.g. "03.2025" inside "12.03.2025") share the label of that date
    for c in found:
        for other in found:
            if other is c or not _overlaps(c, other):
                continue
            c.expiry_label = c.expiry_label or other.expiry_label
            c.production_label = (c.production_label or other.production_label) and not c.expiry_label


def parse_expiry_date(text: str, today: Optional[date] = None) -> Optional[str]:
    """Find the expiry date in OCR text.

    Returns "DD-MM-YYYY", "00-MM-YYYY" (month and year only) or "DD-MM-0000" (no year).
    With several dates: a date after an expiry label wins, dates after a production or lot
    label are skipped, and if 'today' is given dates that are already over are dropped
    when a real alternative exists (the production date is always the earlier one).
    """
    text = text.lower()
    found_dates: List[_Candidate] = []

    def add_date(d: int, m: int, y: int, date_type: str, priority: int, match) -> None:
        """priority: higher = more reliable format (3=full with sep, 2=half-glued, 1=glued, 0=guessed)"""
        y_norm = _normalize_year(y)

        if y_norm != 0 and not (2025 <= y_norm <= 2035):
            return

        if 1 <= m <= 12:
            try:
                if date_type == "DD_MM":
                    dt = datetime(2000, m, d)
                else:
                    dt = datetime(y_norm, m, 1 if date_type == "MM_YYYY" else d)
                found_dates.append(_Candidate(dt, date_type, d, m, y_norm, priority,
                                              match.start(), match.end()))
            except ValueError:
                pass

    # 1. FULL FORMAT WITH SEPARATORS (e.g., 27.07.2026, 27/07/26) - highest priority
    pattern_3 = re.compile(r"(\d{1,2})[./\-]+(\d{1,2})[./\-]+(\d{2,4})")
    for match in pattern_3.finditer(text):
        a, b, c = map(int, match.groups())
        if c >= 100:
            c = (c % 100) + 2000
        add_date(a, b, c, "FULL", 3, match)

    # 1.5 HALF-GLUED DATES (Catches 27.072026 or 2707.2026)
    pattern_missing_sep1 = re.compile(r"(\d{1,2})[./\-]+(\d{1,2})(20[2-3]\d)")
    for match in pattern_missing_sep1.finditer(text):
        add_date(*map(int, match.groups()), "FULL", 2, match)

    pattern_missing_sep2 = re.compile(r"(\d{1,2})(\d{1,2})[./\-]+(20[2-3]\d)")
    for match in pattern_missing_sep2.finditer(text):
        add_date(*map(int, match.groups()), "FULL", 2, match)

    # 1.6 HALF-GLUED WITH 2-DIGIT YEAR (Catches 29/0327 or 2903/27)
    pattern_missing_sep3 = re.compile(r"(?<!\d)(\d{1,2})[./\-]+(\d{2})(\d{2})(?!\d)")
    for match in pattern_missing_sep3.finditer(text):
        add_date(*map(int, match.groups()), "FULL", 2, match)

    pattern_missing_sep4 = re.compile(r"(?<!\d)(\d{2})(\d{2})[./\-]+(\d{2})(?!\d)")
    for match in pattern_missing_sep4.finditer(text):
        add_date(*map(int, match.groups()), "FULL", 2, match)

    # 2. FULLY GLUED 8 DIGITS (e.g., 22032029)
    pattern_glued_8 = re.compile(r"(?<!\d)(\d{2})(\d{2})(20[2-3]\d)(?!\d)")
    for match in pattern_glued_8.finditer(text):
        add_date(*map(int, match.groups()), "FULL", 1, match)

    # 2.5 FULLY GLUED 6 DIGITS (e.g., 270726)
    pattern_glued_6 = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")
    for match in pattern_glued_6.finditer(text):
        add_date(*map(int, match.groups()), "FULL", 1, match)

    # 2.6 FULLY GLUED 6 DIGITS MMYYYY (Catches 092025 from image 013/016)
    pattern_glued_mmyyyy = re.compile(r"(?<!\d)(\d{2})(20[2-3]\d)(?!\d)")
    for match in pattern_glued_mmyyyy.finditer(text):
        add_date(1, int(match.group(1)), int(match.group(2)), "MM_YYYY", 1, match)

    # 2.7 FULLY GLUED 7 DIGITS (e.g., "1045027" -> try "10-45-027" -> "10-04-2027")
    # Low priority to avoid overriding correct dates
    pattern_glued_7 = re.compile(r"(?<!\d)(\d{1})(\d{2})(\d{4})(?!\d)")
    for match in pattern_glued_7.finditer(text):
        a, b, c = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if c > 2035:
            c = (c % 100) + 2000
        if 1 <= a <= 31 and 1 <= b <= 12 and 2025 <= c <= 2035:
            add_date(a, b, c, "FULL", 0, match)

    # 3. SPACES FORMAT (e.g., 27 07 2026)
    pattern_3_spaces = re.compile(r"(?<!\d)(\d{1,2})\s+(\d{1,2})\s+(20[2-3]\d|\d{2})(?!\d)")
    for match in pattern_3_spaces.finditer(text):
        add_date(*map(int, match.groups()), "FULL", 3, match)

    # 4. MM.YYYY or MM/YYYY
    pattern_mm_yyyy = re.compile(r"(\d{1,2})[./\-\s]+(20[2-3]\d)")
    for match in pattern_mm_yyyy.finditer(text):
        add_date(1, int(match.group(1)), int(match.group(2)), "MM_YYYY", 3, match)

    # 4.5 Single-digit year (e.g., "30/10/2" -> year "2" -> "02" -> 2027)
    pattern_single_year = re.compile(r"(?<!\d)(\d{1,2})[./\-]+(\d{1,2})[./\-]+(\d)(?!\d)")
    for match in pattern_single_year.finditer(text):
        a, b, c = map(int, match.groups())
        if 1 <= c <= 9:
            # Try c+25=27, c+27=29, c+30=32
            for offset in [25, 27, 30]:
                y = c + offset
                if 2025 <= _normalize_year(y) <= 2035:
                    add_date(a, b, y, "FULL", 2, match)
                    break

    # 5. DD.MM or MM.YY (2-digit year, extended range 20-35)
    pattern_2 = re.compile(r"(?<!\d)(\d{1,2})[./\-]+(\d{1,2})(?!\d)")
    for match in pattern_2.finditer(text):
        a, b = map(int, match.groups())
        if 20 <= b <= 35:
            add_date(1, a, b, "MM_YYYY", 2, match)
        if 1 <= a <= 31 and 1 <= b <= 12:
            add_date(a, b, 0, "DD_MM", 2, match)

    # 5.5 Handle "Z" as separator (e.g., "3.10Z" -> "3.10" -> "09/2025")
    pattern_z_sep = re.compile(r"(\d{1,2})[./\-]+(\d{1,2})z")
    for match in pattern_z_sep.finditer(text):
        a, b = map(int, match.groups())
        if 1 <= a <= 12 and 20 <= b <= 35:
            add_date(1, a, b, "MM_YYYY", 2, match)

    # 6. Handle "0.05.2029" -> "30-05-2029" (OCR misread "30" as "0")
    pattern_zero_day = re.compile(r"0[./\-]+(\d{1,2})[./\-]+(20[2-3]\d)")
    for match in pattern_zero_day.finditer(text):
        m, y = int(match.group(1)), int(match.group(2))
        if 1 <= m <= 12:
            add_date(30, m, y, "FULL", 0, match)

    if not found_dates:
        return None

    # Several dates: expiry label first, never a production date or lot number if there is
    # another one,
    # then (with 'today') a date with separators that is not over yet
    _label_candidates(text, found_dates)
    candidates = [c for c in found_dates if c.expiry_label] or \
                 [c for c in found_dates if not c.production_label] or found_dates
    if today is not None:
        candidates = _drop_past(candidates, today)

    # Sort by: priority (highest first), then date (latest first)
    candidates.sort(key=lambda c: (-c.priority, -c.dt.timestamp()))
    best = candidates[0]

    if best.date_type == "DD_MM":
        return f"{best.d:02d}-{best.m:02d}-0000"
    elif best.date_type == "MM_YYYY":
        return f"00-{best.m:02d}-{best.y:04d}"
    else:
        return f"{best.d:02d}-{best.m:02d}-{best.y:04d}"
