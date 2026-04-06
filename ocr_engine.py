import os
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2
import numpy as np
from paddleocr import PaddleOCR

_OCR = None

def _get_ocr():
    global _OCR
    if _OCR is None:
        _OCR = PaddleOCR(use_angle_cls=True, lang="german")
    return _OCR

def _preprocess(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(blur)

    binary = cv2.adaptiveThreshold(
        enhanced, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        31, 5
    )

    kernel = np.ones((3, 3), np.uint8)
    dilated = cv2.dilate(binary, kernel, iterations=1)
    return dilated

def run_ocr(image: np.ndarray, min_conf: float = 0.35) -> str:
    if image is None:
        return ""

    pre = _preprocess(image)
    ocr = _get_ocr()
    result = ocr.ocr(pre, cls=True)

    if not result or not result[0]:
        return ""

    texts: list[str] = []
    for line in result[0]:
        text = line[1][0]
        conf = float(line[1][1])
        if conf >= min_conf:
            texts.append(text)

    return " ".join(texts).strip()