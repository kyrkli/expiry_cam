#!/usr/bin/env python3
"""Expiry cam main station (Pi 5): receives photos and barcodes from the hand scanner.

Endpoints:
    GET  /health            -> {"status": "ok", "ocr_ready": bool}
    POST /image             multipart field "file" (JPEG)
                            -> {"scan_id", "expiry", "expiry_display", "expires_on", "days_left",
                                "expired", "raw_text", "ocr_seconds"}
                            No date found: scan_id = null, nothing is stored in the database
                            (the photo goes to uploads/failed/ for OCR tuning).
    POST /barcode           JSON {"barcode": "...", "scan_id": int | null}
                            -> {"barcode", "product", "brand", "quantity", "scan_id", "expiry_display"}
    GET  /scans?limit=50    -> recent scans

Run:
    python -m uvicorn server:app --host 0.0.0.0 --port 8000
"""
import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from core import dates, db, products
from ocr.parser import parse_expiry_date

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = db.UPLOAD_DIR
FAILED_DIR = UPLOAD_DIR / "failed"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s: %(message)s")
log = logging.getLogger("server")

# PaddleOCR is not thread-safe and keeps per-thread MKL-DNN caches, so it lives in
# exactly one long-lived thread: model load, warm-up and every OCR run happen there.
# This also serializes requests (one photo at a time).
_ocr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")
_ocr_ready = False


async def _in_ocr_thread(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(_ocr_executor, fn, *args)


# --- OCR -----------------------------------------------------------------------------
def _warm_up() -> None:
    """Load the OCR models at startup (runs in the OCR thread), the first load is slow."""
    global _ocr_ready
    try:
        from ocr.engine import _get_ocr
        t0 = time.monotonic()
        ocr = _get_ocr()
        ocr.ocr(np.full((64, 256, 3), 255, np.uint8), cls=True)   # first inference
        _ocr_ready = True
        log.info("OCR ready after %.1f s", time.monotonic() - t0)
    except Exception:
        log.exception("OCR warm-up failed (it will be retried on the first photo)")


def _process_image(data: bytes) -> dict:
    """Decode, save, OCR, parse and store one photo. Runs in the OCR thread."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not a valid image")

    now = datetime.now()
    name = f"{now:%H%M%S}_{uuid.uuid4().hex[:6]}.jpg"

    from ocr.engine import run_ocr
    global _ocr_ready
    t0 = time.monotonic()
    text = run_ocr(img, filename=name)
    seconds = round(time.monotonic() - t0, 2)
    _ocr_ready = True

    parsed = parse_expiry_date(text) if text else None
    expires_on = dates.resolve(parsed, date.today())
    result = {"scan_id": None, "expiry": None, "expiry_display": None, "expires_on": None,
              "days_left": None, "expired": False, "raw_text": text, "ocr_seconds": seconds}

    if expires_on is None:
        # No usable date: keep only the photo (handy for OCR tuning), no database row
        FAILED_DIR.mkdir(parents=True, exist_ok=True)
        (FAILED_DIR / f"{now:%Y-%m-%d}_{name}").write_bytes(data)
        log.info("no date: %r (%.1f s)", text, seconds)
        return result

    day_dir = UPLOAD_DIR / f"{now:%Y-%m-%d}"
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / name
    path.write_bytes(data)
    scan_id = db.insert_scan(raw_text=text, parsed_expiry_date=parsed, confidence=None,
                             image_path=str(path), source="scanner", ocr_seconds=seconds,
                             expires_on=expires_on.isoformat())
    log.info("scan %d: %r -> %s = %s (%.1f s)", scan_id, text, parsed, expires_on, seconds)
    days_left = (expires_on - date.today()).days
    result.update(scan_id=scan_id, expiry=parsed, expiry_display=dates.display(parsed),
                  expires_on=expires_on.isoformat(), days_left=days_left,
                  expired=days_left < 0)
    return result


# --- barcode -------------------------------------------------------------------------
def _process_barcode(code: str, scan_id: Optional[int]) -> dict:
    norm = products.normalize(code)
    if not norm:
        raise ValueError("barcode has no digits")

    scan = None
    if scan_id is not None:
        scan = db.get_scan(scan_id)
        if scan is None:
            raise LookupError(f"scan {scan_id} not found")

    product = products.lookup(code)
    name = product["name"] if product else None
    brand = product["brand"] if product else None
    if scan:
        db.attach_barcode(scan_id, norm, name, brand)
        log.info("scan %d <- barcode %s (%s)", scan_id, norm, name)

    return {
        "barcode": norm,
        "product": name,
        "brand": brand,
        "quantity": product["quantity"] if product else None,
        "scan_id": scan_id,
        "expiry_display": dates.display(scan["parsed_expiry_date"]) if scan else None,
    }


# --- HTTP handlers -------------------------------------------------------------------
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "ocr_ready": _ocr_ready})


async def upload_image(request: Request) -> JSONResponse:
    try:
        form = await request.form()
    except Exception as e:
        return JSONResponse({"error": f"bad form: {e}"}, status_code=400)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"error": "field 'file' missing"}, status_code=400)
    data = await upload.read()
    if not data:
        return JSONResponse({"error": "empty file"}, status_code=400)
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "file too large"}, status_code=413)
    try:
        result = await _in_ocr_thread(_process_image, data)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        log.exception("image processing failed")
        return JSONResponse({"error": f"processing failed: {e}"}, status_code=500)
    return JSONResponse(result)


async def post_barcode(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        code = str(body["barcode"])
        scan_id = body.get("scan_id")
        scan_id = int(scan_id) if scan_id is not None else None
    except Exception:
        return JSONResponse({"error": "expected JSON {barcode, scan_id}"}, status_code=400)
    try:
        result = await run_in_threadpool(_process_barcode, code, scan_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except LookupError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    return JSONResponse(result)


async def get_scans(request: Request) -> JSONResponse:
    try:
        limit = max(1, min(500, int(request.query_params.get("limit", 50))))
    except ValueError:
        limit = 50
    return JSONResponse(await run_in_threadpool(db.list_scans, limit))


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _ocr_executor.submit(_warm_up)          # do not wait, the server answers meanwhile
    log.info("server started, database: %s", db.DB_PATH)
    yield
    _ocr_executor.shutdown(wait=False, cancel_futures=True)


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/image", upload_image, methods=["POST"]),
        Route("/barcode", post_barcode, methods=["POST"]),
        Route("/scans", get_scans, methods=["GET"]),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
