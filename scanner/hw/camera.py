"""Still capture with rpicam-still."""
import subprocess
import time
from pathlib import Path

import config


def capture() -> Path:
    """Take a photo and return its path. Raises on failure."""
    config.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.CAPTURE_DIR / time.strftime("%Y%m%d_%H%M%S.jpg")
    cmd = [
        "rpicam-still",
        "--nopreview",
        "--timeout", "1000",              # was 2500: time for exposure / white balance
        "--autofocus-on-capture",         # one autofocus cycle right before the shot
        "--autofocus-range", "macro",
        "--autofocus-speed", "fast",
        "--autofocus-window", "0.25,0.25,0.5,0.5",   # focus on the image centre
        "--mode", "2304:1296",            # binned sensor mode, same size as the photo
        "--width", str(config.CAMERA_WIDTH),
        "--height", str(config.CAMERA_HEIGHT),
        "--rotation", "180",              # camera is mounted upside down
        "--sharpness", "1.2",
        "--quality", "93",                # was 100: 2-3x smaller file
        "--denoise", "cdn_off",
        "-o", str(path),
    ]
    subprocess.run(cmd, check=True, timeout=20,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path
