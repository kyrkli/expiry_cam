"""All OLED screens (128x64, 1-bit), drawn with PIL only.

Used by display.py (live screen) and oled_safe.py (last image at power off),
so there is no luma dependency here. Every screen function has the signature
    draw_xxx(d, t, **data)
where d is an ImageDraw and t the seconds since the screen was shown (animations).
"""
import math
from collections import namedtuple

from PIL import Image, ImageDraw, ImageFont

W, H = 128, 64
BAR_H = 13          # status bar height including the separator line
_FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


def _font(name, size):
    try:
        return ImageFont.truetype(_FONT_DIR + name, size)
    except OSError:
        return ImageFont.load_default()


F10 = _font("DejaVuSans.ttf", 10)
B12 = _font("DejaVuSans-Bold.ttf", 12)
B16 = _font("DejaVuSans-Bold.ttf", 16)
B18 = _font("DejaVuSans-Bold.ttf", 18)


# --- text helpers ----------------------------------------------------------------
def fit(d, text, font, width=W):
    """Cut text with an ellipsis so it fits the width."""
    if d.textlength(text, font=font) <= width:
        return text
    while text and d.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def wrap(d, text, font, width=W, max_lines=2):
    """Word wrap into at most max_lines lines, the last one with an ellipsis."""
    lines, cur = [], ""
    for word in text.split():
        test = (cur + " " + word).strip()
        if d.textlength(test, font=font) <= width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return [fit(d, line, font, width) for line in lines]


def center(d, y, text, font, fill=1):
    text = fit(d, text, font)
    d.text(((W - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


def invert(d):
    d.rectangle((0, 0, W - 1, H - 1), fill=1)


# --- icons -----------------------------------------------------------------------
def icon_check(d, x, y, fill=1, s=1):
    d.line((x, y + 4 * s, x + 3 * s, y + 7 * s, x + 8 * s, y), fill=fill, width=2 * s)


def icon_cross(d, x, y, fill=1, s=1):
    d.line((x, y, x + 7 * s, y + 7 * s), fill=fill, width=2 * s)
    d.line((x, y + 7 * s, x + 7 * s, y), fill=fill, width=2 * s)


def icon_wifi(d, x, y, online):
    d.rectangle((x + 6, y + 8, x + 7, y + 9), fill=1)
    d.arc((x + 2, y + 4, x + 11, y + 13), 225, 315, fill=1, width=2)
    d.arc((x - 2, y, x + 15, y + 17), 225, 315, fill=1, width=2)
    if not online:
        d.line((x + 16, y + 1, x + 21, y + 6), fill=1, width=2)
        d.line((x + 16, y + 6, x + 21, y + 1), fill=1, width=2)


def icon_camera(d, x, y, fill=1):
    d.rectangle((x, y + 2, x + 11, y + 9), outline=fill)
    d.rectangle((x + 3, y, x + 6, y + 2), fill=fill)
    d.ellipse((x + 3, y + 3, x + 8, y + 8), outline=fill)


_BARS = (1, 2, 1, 1, 2, 1, 2, 1)


def icon_barcode(d, x, y, fill=1, h=10):
    for w in _BARS:
        d.rectangle((x, y, x + w - 1, y + h - 1), fill=fill)
        x += w + 1


def icon_battery(d, x, y, pct, fill=1):
    d.rectangle((x, y, x + 18, y + 8), outline=fill)
    d.rectangle((x + 19, y + 2, x + 20, y + 6), fill=fill)
    fw = int(15 * max(0, min(100, pct)) / 100)
    if fw:
        d.rectangle((x + 2, y + 2, x + 1 + fw, y + 6), fill=fill)


def icon_power(d, cx, cy, r, fill=1):
    d.arc((cx - r, cy - r, cx + r, cy + r), -60, 240, fill=fill, width=3)
    d.line((cx, cy - r - 2, cx, cy), fill=fill, width=3)


def icon_fridge(d, x, y, fill=1):
    """Tiny version of the bot avatar (26x44)."""
    d.rounded_rectangle((x, y, x + 26, y + 40), radius=5, outline=fill, width=2)
    d.line((x + 1, y + 15, x + 25, y + 15), fill=fill, width=2)
    d.rectangle((x + 8, y + 6, x + 10, y + 9), fill=fill)          # eyes
    d.rectangle((x + 16, y + 6, x + 18, y + 9), fill=fill)
    d.ellipse((x + 6, y + 21, x + 20, y + 35), outline=fill)        # clock
    d.line((x + 13, y + 28, x + 13, y + 24), fill=fill)
    d.line((x + 13, y + 28, x + 9, y + 28), fill=fill)
    d.rectangle((x + 4, y + 41, x + 7, y + 43), fill=fill)          # feet
    d.rectangle((x + 19, y + 41, x + 22, y + 43), fill=fill)


# --- status bar ------------------------------------------------------------------
def draw_status(d, server, battery, pending):
    """server: True/False/None, battery: (pct, low) or None, pending: photo waits."""
    if server is not None:
        icon_wifi(d, 1, 0, server)
    if pending:
        icon_camera(d, 28, 0)
    if battery is not None:
        pct, low = battery
        icon_battery(d, 105, 1, pct)
        label = f"LOW {pct}%" if low else f"{pct}%"
        d.text((101 - d.textlength(label, font=F10), 0), label, font=F10, fill=1)
    d.line((0, 12, W - 1, 12), fill=1)


# --- screens ---------------------------------------------------------------------
def _hints(d, click=True):
    """Bottom line: camera = click, barcode = hold."""
    if click:
        icon_camera(d, 2, 51)
        d.text((17, 50), "click", font=F10, fill=1)
        icon_barcode(d, 70, 51)
        d.text((92, 50), "hold", font=F10, fill=1)
    else:
        icon_barcode(d, 38, 51)
        d.text((60, 50), "hold", font=F10, fill=1)


def draw_splash(d, t):
    icon_fridge(d, 10, 9)
    d.text((48, 18), "Expiry", font=B16, fill=1)
    d.text((48, 34), "cam", font=B16, fill=1)
    dots = "." * (1 + int(t * 3) % 3)
    d.text((48, 52), "starting" + dots, font=F10, fill=1)


def draw_idle(d, t, online=None):
    title = {True: "Ready", False: "Offline", None: "Connecting"}[online]
    center(d, 17, title, B18)
    _hints(d)


def draw_pending(d, t, date="", no_date=False):
    if no_date:                      # the last photo found no date
        center(d, 15, "No date", B16)
        center(d, 34, "retake or scan code", F10)
        _hints(d)
        return
    center(d, 15, f"Photo: {date}", F10)
    center(d, 29, "Scan barcode", B16)
    _hints(d, click=False)


def draw_hold_still(d, t):
    invert(d)
    center(d, 14, "HOLD STILL", B16, fill=0)
    icon_camera(d, 58, 40, fill=0)


def draw_progress(d, t, title="Working", expected=3.0):
    center(d, 20, title, B12)
    frac = min(0.95, t / max(expected, 0.5))     # never looks finished before it is
    d.rectangle((14, 44, 113, 52), outline=1)
    if frac > 0:
        d.rectangle((16, 46, 16 + int(95 * frac), 50), fill=1)


def draw_scanning(d, t):
    center(d, 15, "Scanning", B12)
    widths = [_BARS[i % len(_BARS)] for i in range(16)]   # a wider barcode
    x = (W - (sum(widths) + 2 * (len(widths) - 1))) // 2
    for w in widths:
        d.rectangle((x, 32, x + w - 1, 47), fill=1)
        x += w + 2
    y = 31 + int((math.sin(t * 2 * math.pi * 0.7) + 1) / 2 * 17)   # sweeping laser
    d.line((30, y, 97, y), fill=0, width=3)
    d.line((30, y, 97, y), fill=1, width=1)
    center(d, 52, "release to cancel", F10)


def days_text(days_left):
    if days_left is None:
        return ""
    if days_left > 1:
        return f"{days_left} days left"
    if days_left == 1:
        return "expires tomorrow"
    if days_left == 0:
        return "expires today"
    if days_left == -1:
        return "expired yesterday"
    return f"expired {-days_left} days ago"


def draw_date(d, t, date="", days_left=None):
    center(d, 14, "Best before", F10)
    center(d, 26, date, B18)
    center(d, 50, days_text(days_left), F10)


def draw_expired(d, t, date="", days_left=None):
    invert(d)
    center(d, 6, "EXPIRED", B18, fill=0)
    center(d, 30, date, B12, fill=0)
    center(d, 47, days_text(days_left), F10, fill=0)


def draw_product(d, t, name=None, code="", saved=False, date=None, count=None):
    if saved and (not name or not date):
        # Saved, but without a date or a name: it waits in the bot's "Needs info" group
        center(d, 16, name or "Unknown product", B12)
        text = "Saved · " + (date or "no date")
        x = (W - 14 - d.textlength(text, font=F10)) / 2
        icon_check(d, x, 34)
        d.text((x + 14, 32), text, font=F10, fill=1)
        d.rectangle((0, 48, W - 1, H - 1), fill=1)
        center(d, 50, "Fix in Telegram", F10, fill=0)
        return
    lines = wrap(d, name, B12) if name else ["Unknown product", code]
    for i, line in enumerate(lines):
        center(d, 16 + i * 15, line, B12 if (name or i == 0) else F10)
    if saved and count and count > 1:
        # Same product with the same date was already in the list: white bar, can't miss it
        d.rectangle((0, 48, W - 1, H - 1), fill=1)
        center(d, 50, f"Already in list · now ×{count}", F10, fill=0)
    elif saved:
        text = "Saved" + (f" · {date}" if date else "")
        x = (W - 14 - d.textlength(text, font=F10)) / 2
        icon_check(d, x, 52)
        d.text((x + 14, 50), text, font=F10, fill=1)
    else:
        text = "No photo yet"
        x = (W - 16 - d.textlength(text, font=F10)) / 2
        icon_camera(d, x, 51)
        d.text((x + 16, 50), text, font=F10, fill=1)


def draw_error(d, t, title="Error", hint="Try again", icon="cross"):
    if icon == "camera":
        icon_camera(d, 58, 17)
    elif icon == "barcode":
        icon_barcode(d, 57, 17)
    else:
        icon_cross(d, 60, 17)
    center(d, 31, title, B12)
    center(d, 50, hint, F10)


def draw_low_battery(d, t, pct=0):
    invert(d)
    d.rectangle((44, 6, 80, 24), outline=0, width=2)
    d.rectangle((81, 11, 84, 19), fill=0)
    d.rectangle((48, 10, 48 + max(2, int(28 * pct / 100)), 20), fill=0)
    center(d, 30, "LOW BATTERY", B12, fill=0)
    center(d, 47, f"{pct}% · charge soon", F10, fill=0)


def draw_message(d, t, title="", sub=""):
    font = B16 if d.textlength(title, font=B16) <= W else B12
    center(d, 16, title, font)
    center(d, 40, sub, F10)


def draw_safe_off(d, t):
    icon_power(d, 64, 18, 11)
    center(d, 36, "Safe to", B12)
    center(d, 50, "switch OFF", B12)


# name -> (function, status bar, animated, idle screen = may dim / turn off)
Screen = namedtuple("Screen", "func bar animated idle")
SCREENS = {
    "splash": Screen(draw_splash, False, True, False),
    "idle": Screen(draw_idle, True, False, True),
    "pending": Screen(draw_pending, True, False, True),
    "hold_still": Screen(draw_hold_still, False, False, False),
    "progress": Screen(draw_progress, True, True, False),
    "scanning": Screen(draw_scanning, True, True, False),
    "date": Screen(draw_date, True, False, False),
    "expired": Screen(draw_expired, False, False, False),
    "product": Screen(draw_product, True, False, False),
    "error": Screen(draw_error, True, False, False),
    "low_battery": Screen(draw_low_battery, False, False, False),
    "message": Screen(draw_message, False, False, False),
    "safe_off": Screen(draw_safe_off, False, False, False),
}


def render(screen_name, /, t=0.0, server=None, battery=None, pending=False, **data):
    """Draw one screen into a new 1-bit image."""
    screen = SCREENS[screen_name]
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    if screen.bar:
        draw_status(d, server, battery, pending)
    screen.func(d, t, **data)
    return img
