import re
from datetime import datetime
from typing import Optional

def _normalize_year(y: int) -> int:
    if y == 0:
        return 0
    if y < 100:
        return 2000 + y
    return y

def parse_expiry_date(text: str) -> Optional[str]:
    text = text.lower()
    found_dates = []
    
    def add_date(d: int, m: int, y: int, date_type: str, priority: int = 0):
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
                
                found_dates.append((dt, date_type, d, m, y_norm, priority))
            except ValueError:
                pass 

    # 1. FULL FORMAT WITH SEPARATORS (e.g., 27.07.2026, 27/07/26) - highest priority
    pattern_3 = re.compile(r"(\d{1,2})[./\-]+(\d{1,2})[./\-]+(\d{2,4})")
    for match in pattern_3.finditer(text):
        a, b, c = map(int, match.groups())
        if c >= 100:
            c = (c % 100) + 2000
        add_date(a, b, c, "FULL", priority=3)

    # 1.5 HALF-GLUED DATES (Catches 27.072026 or 2707.2026)
    pattern_missing_sep1 = re.compile(r"(\d{1,2})[./\-]+(\d{1,2})(20[2-3]\d)")
    for match in pattern_missing_sep1.finditer(text):
        add_date(*map(int, match.groups()), "FULL", priority=2)
        
    pattern_missing_sep2 = re.compile(r"(\d{1,2})(\d{1,2})[./\-]+(20[2-3]\d)")
    for match in pattern_missing_sep2.finditer(text):
        add_date(*map(int, match.groups()), "FULL", priority=2)

    # 2. FULLY GLUED 8 DIGITS (e.g., 22032029)
    pattern_glued_8 = re.compile(r"(?<!\d)(\d{2})(\d{2})(20[2-3]\d)(?!\d)")
    for match in pattern_glued_8.finditer(text):
        add_date(*map(int, match.groups()), "FULL", priority=1)
        
    # 2.5 FULLY GLUED 6 DIGITS (e.g., 270726)
    pattern_glued_6 = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")
    for match in pattern_glued_6.finditer(text):
        add_date(*map(int, match.groups()), "FULL", priority=1)

    # 2.6 FULLY GLUED 6 DIGITS MMYYYY (Catches 092025 from image 013/016)
    pattern_glued_mmyyyy = re.compile(r"(?<!\d)(\d{2})(20[2-3]\d)(?!\d)")
    for match in pattern_glued_mmyyyy.finditer(text):
        add_date(1, int(match.group(1)), int(match.group(2)), "MM_YYYY", priority=1)

    # 2.7 FULLY GLUED 7 DIGITS (e.g., "1045027" -> try "10-45-027" -> "10-04-2027")
    # Low priority to avoid overriding correct dates
    pattern_glued_7 = re.compile(r"(?<!\d)(\d{1})(\d{2})(\d{4})(?!\d)")
    for match in pattern_glued_7.finditer(text):
        a, b, c = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if c > 2035:
            c = (c % 100) + 2000
        if 1 <= a <= 31 and 1 <= b <= 12 and 2025 <= c <= 2035:
            add_date(a, b, c, "FULL", priority=0)

    # 3. SPACES FORMAT (e.g., 27 07 2026)
    pattern_3_spaces = re.compile(r"(?<!\d)(\d{1,2})\s+(\d{1,2})\s+(20[2-3]\d|\d{2})(?!\d)")
    for match in pattern_3_spaces.finditer(text):
        add_date(*map(int, match.groups()), "FULL", priority=3)
            
    # 4. MM.YYYY or MM/YYYY
    pattern_mm_yyyy = re.compile(r"(\d{1,2})[./\-\s]+(20[2-3]\d)")
    for match in pattern_mm_yyyy.finditer(text):
        add_date(1, int(match.group(1)), int(match.group(2)), "MM_YYYY", priority=3)

    # 4.5 Single-digit year (e.g., "30/10/2" -> year "2" -> "02" -> 2027)
    pattern_single_year = re.compile(r"(?<!\d)(\d{1,2})[./\-]+(\d{1,2})[./\-]+(\d)(?!\d)")
    for match in pattern_single_year.finditer(text):
        a, b, c = map(int, match.groups())
        if 1 <= c <= 9:
            # Try c+25=27, c+27=29, c+30=32
            for offset in [25, 27, 30]:
                y = c + offset
                if 2025 <= _normalize_year(y) <= 2035:
                    add_date(a, b, y, "FULL", priority=2)
                    break

    # 5. DD.MM or MM.YY (2-digit year, extended range 20-35)
    pattern_2 = re.compile(r"(?<!\d)(\d{1,2})[./\-]+(\d{1,2})(?!\d)")
    for match in pattern_2.finditer(text):
        a, b = map(int, match.groups())
        if 20 <= b <= 35:
            add_date(1, a, b, "MM_YYYY", priority=2)
        if 1 <= a <= 31 and 1 <= b <= 12:
            add_date(a, b, 0, "DD_MM", priority=2)

    # 5.5 Handle "Z" as separator (e.g., "3.10Z" -> "3.10" -> "09/2025")
    pattern_z_sep = re.compile(r"(\d{1,2})[./\-]+(\d{1,2})z")
    for match in pattern_z_sep.finditer(text):
        a, b = map(int, match.groups())
        if 1 <= a <= 12 and 20 <= b <= 35:
            add_date(1, a, b, "MM_YYYY", priority=2)

    # 6. Handle "0.05.2029" -> "30-05-2029" (OCR misread "30" as "0")
    pattern_zero_day = re.compile(r"0[./\-]+(\d{1,2})[./\-]+(20[2-3]\d)")
    for match in pattern_zero_day.finditer(text):
        m, y = int(match.group(1)), int(match.group(2))
        if 1 <= m <= 12:
            add_date(30, m, y, "FULL", priority=0)

    if not found_dates:
        return None
        
    # Sort by: priority (highest first), then date (latest first)
    found_dates.sort(key=lambda x: (-x[5], -x[0].timestamp()))
    best_match = found_dates[0]
    
    _, date_type, d, m, y, _ = best_match
    
    if date_type == "DD_MM":
         return f"{d:02d}-{m:02d}-0000"
    elif date_type == "MM_YYYY":
         return f"00-{m:02d}-{y:04d}"
    else: 
         return f"{d:02d}-{m:02d}-{y:04d}"