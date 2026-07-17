import os
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2
import numpy as np
from paddleocr import PaddleOCR
from parser import parse_expiry_date
from typing import Optional
import time
import re

_OCR = None

# ---------------------------------------------------------------------------
RESIZE_WIDTH = 1000
MIN_CONF = 0.10
MAX_TIME = 9.5


def _get_ocr():
    global _OCR
    if _OCR is None:
        _OCR = PaddleOCR(
            use_angle_cls=True,
            lang="german",
            show_log=False,
            use_mkldnn=True,
            det_db_thresh=0.3,
            det_db_box_thresh=0.4,
            det_db_unclip_ratio=1.8,
            use_dilation=False,
        )
    return _OCR


def crop_rotated_rect(img: np.ndarray, rect: tuple, padding: int = 20) -> np.ndarray:
    box = cv2.boxPoints(rect)
    box = np.intp(box)
    rect_ordered = np.zeros((4, 2), dtype="float32")
    s = box.sum(axis=1)
    rect_ordered[0] = box[np.argmin(s)]
    rect_ordered[2] = box[np.argmax(s)]
    diff = np.diff(box, axis=1)
    rect_ordered[1] = box[np.argmin(diff)]
    rect_ordered[3] = box[np.argmax(diff)]
    src_pts = rect_ordered.astype("float32")
    tl, tr, br, bl = src_pts

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = max(int(widthA), int(widthB))
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = max(int(heightA), int(heightB))

    if maxWidth == 0 or maxHeight == 0:
        return None

    dst_pts = np.array([
        [0, 0], [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1], [0, maxHeight - 1]
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(img, M, (maxWidth, maxHeight))
    if maxHeight > maxWidth:
        warped = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)
    return cv2.copyMakeBorder(warped, padding, padding, padding, padding,
                               cv2.BORDER_CONSTANT, value=[255, 255, 255])


def get_text_rois(image: np.ndarray) -> list[np.ndarray]:
    h, w = image.shape[:2]
    scale = RESIZE_WIDTH / w
    dim = (RESIZE_WIDTH, int(h * scale))
    resized = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (20, 20))
    connected = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, close_kernel)
    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rois = []
    for c in contours:
        rect = cv2.minAreaRect(c)
        (cx, cy), (cw, ch), angle = rect
        if cw * ch <= 1000:
            continue
        if cw > ch:
            safe_w = cw + 60
            safe_h = ch + 10
        else:
            safe_w = cw + 10
            safe_h = ch + 60
        expanded = ((cx, cy), (safe_w, safe_h), angle)
        crop = crop_rotated_rect(resized, expanded, padding=20)
        if crop is not None:
            rois.append(crop)

    if not rois:
        rois.append(resized)
    else:
        rois.append(resized)
    return rois


def _ocr_one(ocr, img: np.ndarray) -> tuple[str, float]:
    if img.size == 0:
        return "", 0.0
    result = ocr.ocr(img, cls=True)
    if not result or not result[0]:
        return "", 0.0

    lines = []
    confs = []
    for line in result[0]:
        text = line[1][0]
        conf = float(line[1][1])
        if conf >= MIN_CONF:
            lines.append(text)
            confs.append(conf)
    if not lines:
        return "", 0.0

    combined = " ".join(lines).strip()
    avg_conf = float(np.mean(confs)) if confs else 0.0
    return combined, avg_conf


def _preprocess_adaptive(gray: np.ndarray) -> np.ndarray:
    """Apply adaptive thresholding to handle low-contrast and varying lighting."""
    filtered = cv2.bilateralFilter(gray, 9, 75, 75)
    adaptive = cv2.adaptiveThreshold(filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY, 31, 2)
    return adaptive


def _preprocess_dotmatrix(gray: np.ndarray) -> np.ndarray:
    """Connect dot-matrix printed characters into solid strokes."""
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel, iterations=1)
    return closed


def _preprocess_glare(gray: np.ndarray) -> np.ndarray:
    """Normalize uneven illumination / glare via background division."""
    bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=25)
    norm = cv2.divide(gray, bg, scale=255)
    return norm


def _preprocess_lowcontrast(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=8.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    lo, hi = np.percentile(enhanced, [2, 98])
    if hi > lo:
        enhanced = np.clip((enhanced - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
    return enhanced


def _estimate_skew_angle(gray: np.ndarray) -> float:
    """Estimate dominant text skew angle in degrees."""
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                            minLineLength=gray.shape[1] // 4, maxLineGap=20)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if -45 < angle < 45:
            angles.append(angle)
    if not angles:
        return 0.0
    return float(np.median(angles))


def _rotate_image(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderValue=255)


def run_ocr(image: np.ndarray, filename: str = "default", min_conf: float = MIN_CONF) -> str:
    if image is None:
        return ""

    deadline = time.time() + MAX_TIME
    ocr = _get_ocr()
    rois = get_text_rois(image)

    roi_crops = rois[:-1] if len(rois) > 1 else []
    full_img = rois[-1]

    best_text = ""
    best_conf = 0.0
    best_parsed = False

    def update_best(text: str, conf: float):
        nonlocal best_text, best_conf, best_parsed
        # Try original text
        parsed = parse_expiry_date(text) is not None
        if parsed and not best_parsed:
            best_text = text
            best_conf = conf
            best_parsed = True
            return
        # Try digit-filtered text
        digit_only = ' '.join(re.sub(r'[^0-9./\-:\s]', ' ', text).split())
        if digit_only and digit_only != text:
            parsed = parse_expiry_date(digit_only) is not None
            if parsed and not best_parsed:
                best_text = digit_only
                best_conf = conf
                best_parsed = True
                return
        if not best_parsed and conf > best_conf:
            best_text = text
            best_conf = conf

    def remaining():
        return deadline - time.time()

    # === Phase 1: Cropped ROIs — only 2 top ROIs, save time for full image ===
    roi_crops.sort(key=lambda x: x.shape[0] * x.shape[1], reverse=True)
    roi_crops = roi_crops[:2]

    for crop in roi_crops:
        if remaining() <= 0.5:
            break

        enlarged = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)

        text, conf = _ocr_one(ocr, gray)
        if text:
            update_best(text, conf)
            if best_parsed and conf >= 0.25:
                return best_text

        if best_parsed:
            return best_text

    # === Phase 2: Full image — try at 800px for better detection ===
    h, w = full_img.shape[:2]
    if w > 800:
        scale = 800 / w
        full_small = cv2.resize(full_img, (800, int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        full_small = full_img
    full_gray = cv2.cvtColor(full_small, cv2.COLOR_BGR2GRAY)

    # Try base full image
    if remaining() > 0.5:
        text, conf = _ocr_one(ocr, full_gray)
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    # Try CLAHE on full image
    if remaining() > 0.5 and not best_parsed:
        clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(4, 4))
        text, conf = _ocr_one(ocr, clahe.apply(full_gray))
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    # Try adaptive thresholding
    if remaining() > 0.5 and not best_parsed:
        adaptive = _preprocess_adaptive(full_gray)
        text, conf = _ocr_one(ocr, adaptive)
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    # Try glare removal
    if remaining() > 0.5 and not best_parsed:
        glare_free = _preprocess_glare(full_gray)
        text, conf = _ocr_one(ocr, glare_free)
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    # Try low contrast enhancement
    if remaining() > 0.5 and not best_parsed:
        enhanced = _preprocess_lowcontrast(full_gray)
        text, conf = _ocr_one(ocr, enhanced)
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    # Try dot matrix processing
    if remaining() > 0.5 and not best_parsed:
        dot_processed = _preprocess_dotmatrix(full_gray)
        text, conf = _ocr_one(ocr, dot_processed)
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    # Try skew correction
    if remaining() > 0.5 and not best_parsed:
        skew_angle = _estimate_skew_angle(full_gray)
        if abs(skew_angle) > 0.5:
            deskewed = _rotate_image(full_gray, -skew_angle)
            text, conf = _ocr_one(ocr, deskewed)
            if text:
                update_best(text, conf)
                if best_parsed:
                    return best_text

    # Try rotations
    if remaining() > 0.5 and not best_parsed:
        rot180 = cv2.rotate(full_gray, cv2.ROTATE_180)
        text, conf = _ocr_one(ocr, rot180)
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    if remaining() > 0.5 and not best_parsed:
        rot90 = cv2.rotate(full_gray, cv2.ROTATE_90_CLOCKWISE)
        text, conf = _ocr_one(ocr, rot90)
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    if remaining() > 0.5 and not best_parsed:
        rot90ccw = cv2.rotate(full_gray, cv2.ROTATE_90_COUNTERCLOCKWISE)
        text, conf = _ocr_one(ocr, rot90ccw)
        if text:
            update_best(text, conf)

    # === Phase 3: Fallback — try adaptive thresholding on rotated versions ===
    if not best_parsed and remaining() > 0.5:
        adaptive = _preprocess_adaptive(full_gray)
        rot180 = cv2.rotate(adaptive, cv2.ROTATE_180)
        text, conf = _ocr_one(ocr, rot180)
        if text:
            update_best(text, conf)
            if best_parsed:
                return best_text

    if not best_parsed and remaining() > 0.5:
        adaptive = _preprocess_adaptive(full_gray)
        rot90 = cv2.rotate(adaptive, cv2.ROTATE_90_CLOCKWISE)
        text, conf = _ocr_one(ocr, rot90)
        if text:
            update_best(text, conf)

    if not best_parsed and remaining() > 0.5:
        adaptive = _preprocess_adaptive(full_gray)
        rot90ccw = cv2.rotate(adaptive, cv2.ROTATE_90_COUNTERCLOCKWISE)
        text, conf = _ocr_one(ocr, rot90ccw)
        if text:
            update_best(text, conf)

    return best_text