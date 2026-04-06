import re
from datetime import datetime
from typing import Optional

_DATE_PATTERNS = [
    re.compile(r"\b(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{2,4})\b"),  # DD.MM.YY / DD-MM-YYYY
    re.compile(r"\b(?P<m>\d{1,2})[./-](?P<y>\d{2,4})\b"),                       # MM.YYYY
]

def _normalize_year(y: int) -> int:
    return 2000 + y if y < 100 else y

def parse_expiry_date(text: str) -> Optional[str]:
    for p in _DATE_PATTERNS:
        m = p.search(text)
        if not m:
            continue

        gd = m.groupdict()
        try:
            if "d" in gd and gd["d"] is not None:
                d = int(gd["d"])
                mth = int(gd["m"])
                y = _normalize_year(int(gd["y"]))
                dt = datetime(y, mth, d)
                return dt.strftime("%Y-%m-%d")
            else:
                mth = int(gd["m"])
                y = _normalize_year(int(gd["y"]))
                dt = datetime(y, mth, 1)
                return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None