import os
import re
from collections import defaultdict
from statistics import median
from time import perf_counter

from db import init_db, insert_scan, list_recent
from parser import parse_expiry_date
from ocr_engine import run_ocr
import cv2
import subprocess

def demo_store_result(raw_text: str, confidence: float | None = None, image_path: str | None = None) -> None:
    init_db()
    parsed = parse_expiry_date(raw_text)
    row_id = insert_scan(raw_text=raw_text, parsed_expiry_date=parsed, confidence=confidence, image_path=image_path)
    print(f"Stored scan id={row_id}, parsed_expiry_date={parsed}")

    print("Recent rows:")
    for row in list_recent(10):
        print(row)

def capture_frame(save_path="temp_frame.jpg") -> None:
    print("📸 Camera: Focusing and taking a picture...")
    
    command = [ 
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
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    dataset_path = "dataset"
    
    # Dictionaries to collect tag statistics
    tag_total = defaultdict(int)
    tag_success = defaultdict(int)
    
    total_images = 0
    counter_success = 0
    not_successful_parses = set()
    analysis_times = []
    
    # Regex to extract the real expiry date from anywhere in the filename
    # (Matches patterns like 29-02-2028 or 00-01-2027)
    date_pattern = re.compile(r"(\d{2}-\d{2}-\d{4})")

    dataset_images = sorted(os.listdir(dataset_path))

    for test_image in dataset_images:
        # Ignore non-image files (like .DS_Store on Mac)
        if not test_image.lower().endswith(('.png', '.jpg', '.jpeg')):
            continue
            
        total_images += 1
        image_path = os.path.join(dataset_path, test_image)
        image = cv2.imread(image_path)
        
        # 1. Extract the real expiry date
        date_match = date_pattern.search(test_image)
        if not date_match:
            print(f"⚠️ Skipped file {test_image}: Unable to extract date from filename.")
            continue
        real_expiry = date_match.group(1)
        
        # 2. Extract tags (assuming format ID_TAGS_frame_DATE_TIME.jpg)
        # If the format is 078_lowc-inv_frame_..., tags will be at index 1
        parts = test_image.split("_")
        
        tags_str = "norm" # Default tag
        if len(parts) >= 2 and parts[1] != "frame":
            tags_str = parts[1]
            
        # Split the tag string into a list (e.g., "lowc-inv" -> ["lowc", "inv"])
        current_tags = tags_str.split("-")

        print(f"Testing image: {test_image} | Real expiry: {real_expiry} | Tags: {current_tags}")
        
        analysis_start = perf_counter()
        ocr_text = run_ocr(image, filename=test_image, min_conf=0.2)
        analysis_time = perf_counter() - analysis_start
        analysis_times.append(analysis_time)
        print(f"⏱️ Analysis time: {analysis_time:.3f}s")
        print(f"OCR text: {ocr_text}")
        
        parsed_date = parse_expiry_date(ocr_text)
        is_success = (parsed_date == real_expiry)
        
        if is_success:
            print("✅ Parsed date matches the real expiry date!")
            counter_success += 1
        else:
            print(f"❌ Parsed date '{parsed_date}' does NOT match the real expiry date '{real_expiry}'.")
            not_successful_parses.add(test_image)
            
        # Update statistics for each tag found in the filename
        for tag in current_tags:
            tag_total[tag] += 1
            if is_success:
                tag_success[tag] += 1
                
        print("-" * 50)

    # OUTPUT FINAL STATISTICS
    print("\n" + "="*50)
    print("📊 FINAL ANALYTICS (SLICE-BASED EVALUATION)")
    print("="*50)
    
    print(f"Overall accuracy: {counter_success}/{total_images} ({(counter_success/total_images)*100:.2f}%)")
    print("\nAccuracy by category (Tags):")
    print("-" * 40)
    
    # Sort tags alphabetically for a clean output
    for tag in sorted(tag_total.keys()):
        total = tag_total[tag]
        success = tag_success[tag]
        percent = (success / total) * 100 if total > 0 else 0
        print(f"[{tag:^7}] : {success:2d}/{total:2d} ({percent:6.2f}%)")
        
    print("-" * 40)
    print("\nList of unsuccessful parses:")
    for test_image in sorted(not_successful_parses):
        print(f" - {test_image}")

    if analysis_times:
        median_time = median(analysis_times)
        print("\nMedian analysis time:")
        print(f"{median_time:.3f}s across {len(analysis_times)} analyzed images")

if __name__ == "__main__":
    main()