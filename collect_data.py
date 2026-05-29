import os
import cv2
from datetime import datetime
import cv2
import subprocess

# Configuration
DATASET_DIR = "./dataset"

def capture_frame(save_path="temp_frame.jpg") -> None:
    print("📸 Camera: Focusing and taking a picture...")
    
    # Form the command for libcamera
    # --autofocus-mode default forces the lens to focus before capturing
    # --nopreview disables the screen output
    # --timeout 5000 gives the camera 5 seconds to adjust white balance and focus
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



def main():
    # Create dataset directory if it doesn't exist
    os.makedirs(DATASET_DIR, exist_ok=True)
    
    print("=======================================")
    print("📸 Data Collection Mode Started")
    print("=======================================")
    
    while True:
        try:
            input("\nPress ENTER to capture a photo (or Ctrl+C to exit)...")
        except KeyboardInterrupt:
            print("\nExiting data collection mode.")
            break
        
        img = capture_frame(save_path="latest.jpg")
        if img is None:
            continue
        
        actual_exp_date = "22-03-2029"
        timestamp = datetime.now().strftime("%Hh%Mm%Ss")
        filename = f"frame_{actual_exp_date}_{timestamp}.jpg"
        filepath = os.path.join(DATASET_DIR, filename)
        
        cv2.imwrite(filepath, img)
        print(f"✅ Saved correctly: {filepath}")

if __name__ == "__main__":
    main()