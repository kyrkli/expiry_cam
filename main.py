import os

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

from ocr_engine import run_ocr
import cv2
import subprocess

def capture_frame(save_path="temp_frame.jpg") -> None:
    print("📸 Camera: Focusing and taking a picture...")
    
    # Form the command for libcamera
    # --autofocus-mode default forces the lens to focus before capturing
    # --nopreview disables the screen output
    # --timeout 1000 gives the camera 1 second to adjust white balance and focus
    command = [ # TODO Some options can be added here
        "rpicam-still",
        "--autofocus-mode", "auto",
        "--autofocus-range", "macro",
        "--nopreview",
        "--timeout", "2500",
        "--width", "4608",
        "--height", "2592",
        "--sharpness", "1.2",
        "--quality", "100",
        "--denoise", "cdn_off",
        "-o", save_path
    ]
    
    try:
        # Execute the command silently
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Read the saved image via OpenCV
        image = cv2.imread(save_path)
        if image is not None:
            print("✅ Frame successfully captured and loaded into memory!")
            return image
        else:
            print("❌ Error: OpenCV could not read the file.")
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Camera error: {e}")
        return None


def main() -> None:
    
    #image = capture_frame(save_path="temp_frame.jpg")
    
    #test dataset

    dataset_path = "dataset"
    total_images = len(os.listdir(dataset_path))
    counter_success = 0
    not_successful_parses = set()

    for test_image in os.listdir(dataset_path):
        image = cv2.imread(f"{dataset_path}/{test_image}")
        
        # Assuming filename format "frame_00-01-2027_18h15m39s.jpg"
        real_expiry = test_image.split("_")[2].split(".")[0]  # Extract the expiry date

        print(f"Testing image: {test_image}, real expiry: {real_expiry}")
        ocr_text = run_ocr(image, filename=test_image)
        print(f"OCR text: {ocr_text}")
        
        parsed_date = parse_expiry_date(ocr_text)
        if parsed_date == real_expiry:
            print("✅ Parsed date matches the real expiry date!")
            counter_success += 1
        else:
            print(f"❌ Parsed date '{parsed_date}' does NOT match the real expiry date '{real_expiry}'.")
            not_successful_parses.add(test_image)  # Add the filename to the set of unsuccessful parses
        print("-" * 50)

    not_successful_parses = sorted(not_successful_parses)
    for test_image in not_successful_parses:
        print(f"Unsuccessful parse: {test_image}")

    print(f"Final accuracy: {counter_success}/{total_images} ({(counter_success/total_images)*100:.2f}%)")

    # insert_scan(...)

if __name__ == "__main__":
    main()