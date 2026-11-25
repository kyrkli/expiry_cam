"""Central configuration for the hand scanner."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = BASE_DIR / "captures"

# --- GPIO (BCM numbering) ----------------------------------------------------
PIN_POWER = 23      # physical pin 16: hold = shutdown, double press = reboot
PIN_TRIGGER = 24    # physical pin 18: click = photo, hold = barcode

# --- Button timing -------------------------------------------------------------
POWER_HOLD_S = 3.0      # hold power button this long to shut down
POWER_DOUBLE_S = 0.6    # max gap between two clicks for reboot
TRIGGER_HOLD_S = 0.4    # trigger held longer than this = barcode mode

# --- OLED ----------------------------------------------------------------------
OLED_ADDR = 0x3C
OLED_DRIVER = "sh1106"  # "sh1106" or "ssd1306", check with tools/oled_test.py
OLED_I2C_PORT = 1       # 1 = main bus; 3 = separate software bus (GPIO5/6), if set up

# --- Battery (ADS1115 A0, divider 100k / 47k) ----------------------------------
ADS_ADDR = 0x48
K_DIV = (100 + 47) / 47
K_CAL = 1.0055               # = multimeter_voltage / shown_voltage
BATTERY_WARN_V = 7.0         # show LOW BAT below this
BATTERY_CUTOFF_V = 6.6       # shut down below this...
BATTERY_CUTOFF_HOLD_S = 30   # ...if it stays low for this long
BATTERY_MIN_VALID_V = 3.0    # lower readings = sensor error, ignored
BATTERY_READ_INTERVAL_S = 5  # how often to read the ADS
BATTERY_WINDOW_S = 30        # median over this time window
BATTERY_ENABLED = True       # read the battery and shut down when empty (keep on!)
BATTERY_SHOW = True          # always show the battery level (False = only when low)

# --- Barcode scanner (GM67 on UART) -------------------------------------------
SCANNER_PORT = "/dev/serial0"
SCANNER_BAUD = 9600
SCANNER_WAKE_BYTE = True   # send 0x00 before START (only if gm67_setup.py needed --wake)

# --- Camera --------------------------------------------------------------------
CAMERA_WIDTH = 2304     # OCR downsizes to 1000 px anyway
CAMERA_HEIGHT = 1296

# --- UI ------------------------------------------------------------------------
RESULT_SHOW_S = 5.0     # how long a result stays on screen

# --- Main station (Pi 5) ------------------------------------------------------
SERVER_URL = "http://my-beautiful-RPi.local:8000"
KEEP_LOCAL_PHOTOS = False   # keep photos in captures/ after a successful upload
SERVER_CHECK_S = 10     # how often to check the server, seconds
