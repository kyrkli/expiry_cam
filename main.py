from db import init_db, insert_scan, list_recent
from parser import parse_expiry_date

def demo_store_result(raw_text: str, confidence: float | None = None, image_path: str | None = None) -> None:
    init_db()
    parsed = parse_expiry_date(raw_text)
    row_id = insert_scan(raw_text=raw_text, parsed_expiry_date=parsed, confidence=confidence, image_path=image_path)
    print(f"Stored scan id={row_id}, parsed_expiry_date={parsed}")

    print("Recent rows:")
    for row in list_recent(10):
        print(row)


from camera import ScannerCamera
from ocr_engine import run_ocr

def main() -> None:
    cam = ScannerCamera(save_path="temp_frame.jpg")
    image = cam.capture_frame()

    if image is None:
        print("Capture failed.")
        return

    print(f"Captured image shape: {image.shape}")
    
    ocr_text = run_ocr(image)
    print(f"OCR text: {ocr_text}")
    
    # parsed_date = parse_expiry_date(ocr_text)
    # insert_scan(...)

if __name__ == "__main__":
    main()