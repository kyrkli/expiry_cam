"""HTTP client for the main station (Pi 5 server)."""
import logging
import threading
import time
from pathlib import Path

import requests

import config

log = logging.getLogger("client")

# (connect, read) timeouts in seconds. OCR alone can take up to ~10 s on the Pi 5,
# and the first photo after a server restart also waits for the model to load.
IMAGE_TIMEOUT = (5, 45)
BARCODE_TIMEOUT = (5, 15)
HEALTH_TIMEOUT = (2, 3)
OFFLINE_AFTER_FAILS = 2     # health checks in a row, so one Wi-Fi hiccup does not flicker

# No requests.Session on purpose: a fresh connection per request avoids reusing
# keep-alive sockets that the server already closed. Scans are seconds apart anyway.


class ServerError(Exception):
    """Short message, it is shown on the OLED as is."""


# --- connection status -----------------------------------------------------------
_status_lock = threading.Lock()
_online = None          # None = not checked yet, then True / False
_on_change = None       # callback(online: bool), set by start_monitor()


def is_online():
    return _online


def _report(online: bool) -> None:
    """Remember the server state; call the callback only when it changes."""
    global _online
    with _status_lock:
        if online == _online:
            return
        _online = online
    log.info("server %s", "online" if online else "OFFLINE")
    if _on_change:
        _on_change(online)


def check_health() -> bool:
    try:
        r = requests.get(config.SERVER_URL.rstrip("/") + "/health", timeout=HEALTH_TIMEOUT)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except (requests.RequestException, ValueError):
        return False


def start_monitor(on_change) -> None:
    """Background thread: ping /health, faster while the server is offline."""
    global _on_change
    _on_change = on_change
    interval = getattr(config, "SERVER_CHECK_S", 10)

    def loop():
        fails = 0
        while True:
            if check_health():
                fails = 0
                _report(True)
            else:
                fails += 1
                if fails >= OFFLINE_AFTER_FAILS or _online is None:
                    _report(False)
            if 0 < fails < OFFLINE_AFTER_FAILS:
                time.sleep(2)          # confirm a failure quickly
            elif _online:
                time.sleep(interval)
            else:
                time.sleep(min(interval, 5))   # offline: notice the server coming back soon

    threading.Thread(target=loop, daemon=True, name="server-monitor").start()


# --- requests ----------------------------------------------------------------------
def _post(path: str, timeout, **kwargs) -> dict:
    url = config.SERVER_URL.rstrip("/") + path
    try:
        r = requests.post(url, timeout=timeout, **kwargs)
    except requests.ConnectionError as e:
        log.warning("POST %s: %s", url, e)
        _report(False)
        raise ServerError("No server") from e
    except requests.Timeout as e:
        log.warning("POST %s: timeout", url)
        raise ServerError("Server timeout") from e
    _report(True)       # any HTTP answer means the server is reachable
    if r.status_code != 200:
        log.warning("POST %s: HTTP %d %s", url, r.status_code, r.text[:200])
        raise ServerError(f"Server error {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise ServerError("Bad server reply") from e


def send_image(path: Path) -> dict:
    """Upload a photo of the expiry date.

    Returns {"scan_id", "expiry", "expiry_display", "expires_on", "days_left",
             "expired", "raw_text", "ocr_seconds"}; scan_id is None if no date was found.
    The local file is deleted after a successful upload unless KEEP_LOCAL_PHOTOS is set;
    on any error it stays in captures/.
    """
    path = Path(path)
    with path.open("rb") as f:
        res = _post("/image", IMAGE_TIMEOUT, files={"file": (path.name, f, "image/jpeg")})
    log.info("image %s -> scan %s, expiry %s, text %r",
             path.name, res.get("scan_id"), res.get("expiry"), res.get("raw_text"))
    if not getattr(config, "KEEP_LOCAL_PHOTOS", False):
        path.unlink(missing_ok=True)
    return res


def send_barcode(code: str, scan_id, no_date: bool = False) -> dict:
    """Send a barcode; scan_id links it to the last photo (None = no photo).
    no_date = the last photo found no date: save the product without one.

    Returns {"barcode", "product", "brand", "quantity", "scan_id", "expiry_display",
             "count", "saved"}.
    """
    body = {"barcode": code, "scan_id": scan_id}
    if no_date:
        body["no_date"] = True
    res = _post("/barcode", BARCODE_TIMEOUT, json=body)
    log.info("barcode %s (scan %s) -> %s", code, scan_id, res.get("product"))
    return res
