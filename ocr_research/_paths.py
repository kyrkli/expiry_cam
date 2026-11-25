"""Shared paths for the research scripts; works in the repo and on the Pi 5.

    repo:   ocr_research/ next to server/
    Pi 5:   ~/expiry_cam/ocr_research/ inside the server folder
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET_DIR = HERE / "dataset"               # labelled photos, never in git
FAILED_DIR = HERE / "unsuccessful_parse"     # copies of photos the OCR got wrong

# Server code (core/, ocr/): ../server in the repo, ../ (~/expiry_cam) on the Pi 5
for candidate in (HERE.parent / "server", HERE.parent):
    if (candidate / "ocr" / "engine.py").exists():
        sys.path.insert(0, str(candidate))
        break

# The benchmark writes into its own database, never into the real product list
os.environ.setdefault("EXPIRYCAM_DB", str(HERE / "bench.db"))
