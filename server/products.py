"""Product lookup by barcode: local cache first, then Open Food Facts."""
import logging
import os
from typing import Optional

import requests

import db

log = logging.getLogger("products")

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_FIELDS = "product_name,product_name_de,product_name_en,brands,quantity,image_front_small_url"
# Open Food Facts asks for a custom User-Agent: 'app_name/app_version (URL or contact)'.
# Put your own contact in the EXPIRYCAM_USER_AGENT environment variable if you like.
USER_AGENT = os.environ.get("EXPIRYCAM_USER_AGENT", "ExpiryCam/0.1 (hobby project)")
TIMEOUT_S = 6
RETRY_NOT_FOUND_DAYS = 7   # ask Open Food Facts again about unknown codes after a week


def normalize(code: str) -> str:
    """Digits only; 12-digit UPC-A becomes 13-digit EAN-13 (leading 0)."""
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) == 12:
        return "0" + digits
    return digits


def _fetch(code: str) -> Optional[dict]:
    """One Open Food Facts request. Returns the product dict, None if unknown.
    Raises requests.RequestException on network problems."""
    r = requests.get(
        OFF_URL.format(code=code),
        params={"fields": OFF_FIELDS},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_S,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    if data.get("status") != 1 or not data.get("product"):
        return None
    return data["product"]


def lookup(code: str) -> Optional[dict]:
    """Return {"barcode", "name", "brand", "quantity", "image_url"} or None if unknown."""
    norm = normalize(code)
    if not norm:
        return None

    cached = db.get_product(norm)
    if cached and (cached["found"] or cached["age_days"] < RETRY_NOT_FOUND_DAYS):
        return _as_result(cached) if cached["found"] else None

    # UPC-A codes are stored both ways in Open Food Facts, try both spellings
    raw = "".join(ch for ch in code if ch.isdigit())
    candidates = [norm] + ([raw] if raw != norm else [])
    try:
        product = None
        for candidate in candidates:
            product = _fetch(candidate)
            if product:
                break
    except requests.RequestException as e:
        log.warning("Open Food Facts not reachable: %s", e)
        return _as_result(cached) if cached and cached["found"] else None

    if not product:
        db.save_product(norm, found=False)
        log.info("product %s not found", norm)
        return None

    name = (product.get("product_name") or product.get("product_name_de")
            or product.get("product_name_en") or None)
    brand = (product.get("brands") or "").split(",")[0].strip() or None
    db.save_product(norm, found=True, name=name, brand=brand,
                    quantity=product.get("quantity") or None,
                    image_url=product.get("image_front_small_url") or None)
    log.info("product %s: %s / %s", norm, name, brand)
    return _as_result(db.get_product(norm))


def _as_result(row: dict) -> dict:
    return {k: row.get(k) for k in ("barcode", "name", "brand", "quantity", "image_url")}