import subprocess
import os
import cv2

class ScannerCamera:
    def __init__(self, save_path="temp_frame.jpg"):
        self.save_path = save_path

    def capture_frame(self):
        print("📸 Camera: Focusing and taking a picture...")
        
        # Form the command for libcamera
        # --autofocus-mode default forces the lens to focus before capturing
        # --nopreview disables the screen output
        # --timeout 1000 gives the camera 1 second to adjust white balance and focus
        command = [ # TODO Some options can be added here
            "rpicam-still",
            "--autofocus-mode", "default",
            "--nopreview",
            "--timeout", "5000",
            "-o", self.save_path
        ]
        
        try:
            # Execute the command silently
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Read the saved image via OpenCV
            image = cv2.imread(self.save_path)
            if image is not None:
                print("✅ Frame successfully captured and loaded into memory!")
                return image
            else:
                print("❌ Error: OpenCV could not read the file.")
                return None
                
        except subprocess.CalledProcessError as e:
            print(f"❌ Camera error: {e}")
            return None
