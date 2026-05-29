import re
from datetime import datetime
from typing import Optional

def _normalize_year(y: int) -> int:
    if y == 0:
        return 0
    return 2000 + y if y < 100 else y

def parse_expiry_date(text: str) -> Optional[str]:
    text = text.lower()
    found_dates = []
    
    def add_date(d: int, m: int, y: int, date_type: str):
        y_norm = _normalize_year(y)
        
        # Protect against garbage years (e.g., from barcodes)
        if y_norm != 0 and not (2025 <= y_norm <= 2035):
            return
            
        if 1 <= m <= 12:
            try:
                if date_type == "DD_MM":
                    dt = datetime(2000, m, d)
                else:
                    dt = datetime(y_norm, m, 1 if date_type == "MM_YYYY" else d)
                
                found_dates.append((dt, date_type, d, m, y_norm))
            except ValueError:
                pass 

    # 1. FULL FORMAT WITH SEPARATORS (e.g., 27.07.2026, 27/07/26)
    pattern_3 = re.compile(r"(\d{1,2})[./\-]+(\d{1,2})[./\-]+(20[2-3]\d|\d{2})")
    for match in pattern_3.finditer(text):
        add_date(*map(int, match.groups()), "FULL")

    # 1.5 HALF-GLUED DATES (Catches 27.072026 or 2707.2026) -> FIXES YOUR 3 ERRORS
    pattern_missing_sep1 = re.compile(r"(\d{1,2})[./\-]+(\d{1,2})(20[2-3]\d)")
    for match in pattern_missing_sep1.finditer(text):
        add_date(*map(int, match.groups()), "FULL")
        
    pattern_missing_sep2 = re.compile(r"(\d{1,2})(\d{1,2})[./\-]+(20[2-3]\d)")
    for match in pattern_missing_sep2.finditer(text):
        add_date(*map(int, match.groups()), "FULL")

    # 2. FULLY GLUED 8 DIGITS (e.g., 22032029)
    pattern_glued_8 = re.compile(r"(?<!\d)(\d{2})(\d{2})(20[2-3]\d)(?!\d)")
    for match in pattern_glued_8.finditer(text):
        add_date(*map(int, match.groups()), "FULL")
        
    # 2.5 FULLY GLUED 6 DIGITS (e.g., 270726)
    pattern_glued_6 = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")
    for match in pattern_glued_6.finditer(text):
        add_date(*map(int, match.groups()), "FULL")

    # 2.6 FULLY GLUED 6 DIGITS MMYYYY (Catches 092025 from image 013/016)
    pattern_glued_mmyyyy = re.compile(r"(?<!\d)(\d{2})(20[2-3]\d)(?!\d)")
    for match in pattern_glued_mmyyyy.finditer(text):
        add_date(1, int(match.group(1)), int(match.group(2)), "MM_YYYY")

    # 3. SPACES FORMAT (e.g., 27 07 2026)
    pattern_3_spaces = re.compile(r"(?<!\d)(\d{1,2})\s+(\d{1,2})\s+(20[2-3]\d|\d{2})(?!\d)")
    for match in pattern_3_spaces.finditer(text):
        add_date(*map(int, match.groups()), "FULL")
            
    # 4. MM.YYYY or MM/YYYY (Updated to catch messy spaces like "05. .2029" from image 082)
    # Changed [./\-]+ to [./\-\s]+
    pattern_mm_yyyy = re.compile(r"(\d{1,2})[./\-\s]+(20[2-3]\d)")
    for match in pattern_mm_yyyy.finditer(text):
        add_date(1, int(match.group(1)), int(match.group(2)), "MM_YYYY")

    # 5. DD.MM or MM.YY
    pattern_2 = re.compile(r"(?<!\d)(\d{1,2})[./\-]+(\d{1,2})(?!\d)")
    for match in pattern_2.finditer(text):
        a, b = map(int, match.groups())
        if 24 <= b <= 35:
            add_date(1, a, b, "MM_YYYY")
        if 1 <= a <= 31 and 1 <= b <= 12:
            add_date(a, b, 0, "DD_MM")

    if not found_dates:
        return None
        
    found_dates.sort(key=lambda x: x[0], reverse=True)
    best_match = found_dates[0]
    
    _, date_type, d, m, y = best_match
    
    if date_type == "DD_MM":
         return f"{d:02d}-{m:02d}-0000"
    elif date_type == "MM_YYYY":
         return f"00-{m:02d}-{y:04d}"
    else: 
         return f"{d:02d}-{m:02d}-{y:04d}"