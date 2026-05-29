import os
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2
import numpy as np
from paddleocr import PaddleOCR
from parser import parse_expiry_date

_OCR = None

def _get_ocr():
    global _OCR
    if _OCR is None:
        _OCR = PaddleOCR(use_angle_cls=True, lang="german", show_log=False)
    return _OCR


def get_text_rois(image: np.ndarray) -> list[np.ndarray]:
    scale = 1000.0 / image.shape[1]
    dim = (1000, int(image.shape[0] * scale))
    resized = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    
    kernel_grad = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel_grad)

    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    
    kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (20, 20))
    connected = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel_close)

    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rois = []
    for c in contours:
        rect = cv2.minAreaRect(c)
        (center_x, center_y), (width, height), angle = rect
        true_area = width * height

        # 💡 ИЗМЕНЕНИЕ 1: Сняли верхний лимит (40000). 
        # Теперь алгоритм будет вырезать даже огромные блоки (штрихкод + изогнутый текст).
        # Увеличение этого большого куска в 2 раза поможет нейросети прочитать мелкий изогнутый шрифт.
        if true_area > 1200:
            x, y, w, h = cv2.boundingRect(c)
            
            pad_x, pad_y = 30, 30
            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(resized.shape[1], x + w + pad_x)
            y2 = min(resized.shape[0], y + h + pad_y)

            crop = resized[y1:y2, x1:x2]
            rois.append(crop)

    if not rois:
        rois.append(resized)
    else:
        rois.append(resized)

    return rois


def _generate_preprocessing_variants(crop: np.ndarray) -> list[tuple[str, np.ndarray]]:
    variants = []
    
    enlarged = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    variants.append(("v0_color", enlarged))
    
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    variants.append(("v1_base", gray))

    clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(gray)
    variants.append(("v2_clahe", enhanced))

    gaussian = cv2.GaussianBlur(enhanced, (5, 5), 0)
    sharpened = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
    _, thresh = cv2.threshold(sharpened, 150, 255, cv2.THRESH_TRUNC)
    variants.append(("v3_sharp", thresh))
    
    # 💡 ИЗМЕНЕНИЕ 2: Магия Inpainting для металлических бликов
    # Находим экстремально белые пиксели (блик)
    _, mask = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
    # Закрашиваем блик соседними пикселями (реставрация)
    inpainted = cv2.inpaint(gray, mask, 3, cv2.INPAINT_TELEA)
    # Применяем жесткий адаптивный порог, чтобы вытянуть буквы
    adaptive = cv2.adaptiveThreshold(
        inpainted, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
        31, 7
    )
    variants.append(("v4_inpaint", cv2.bitwise_not(adaptive)))

    return variants


def run_ocr(image: np.ndarray, filename: str = "default", min_conf: float = 0.35) -> str:
    if image is None:
        return ""

    rois = get_text_rois(image)
    ocr = _get_ocr()
    
    debug_dir = "debug_output"
    os.makedirs(debug_dir, exist_ok=True)
    safe_name = filename.replace(".jpg", "")

    best_full_text = ""
    found_valid = False 

    for roi_idx, crop in enumerate(rois):
        if found_valid:
            break 
            
        variants = _generate_preprocessing_variants(crop)
        
        for filter_name, preprocessed_img in variants:
            debug_filename = f"{debug_dir}/{safe_name}_roi_{roi_idx}_{filter_name}.jpg"
            cv2.imwrite(debug_filename, preprocessed_img)

            result = ocr.ocr(preprocessed_img, cls=True)

            if not result or not result[0]:
                continue

            current_texts = []
            for line in result[0]:
                text = line[1][0]
                conf = float(line[1][1])
                if conf >= min_conf:
                    current_texts.append(text)

            combined_text = " ".join(current_texts).strip()
            
            from parser import parse_expiry_date
            if parse_expiry_date(combined_text) is not None:
                best_full_text += " " + combined_text
                found_valid = True 
                break 
            
            best_full_text += " " + combined_text

    return best_full_text.strip()