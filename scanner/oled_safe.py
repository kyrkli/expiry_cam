#!/usr/bin/env python3
"""Last image on the OLED right before the power goes off: "Safe to switch OFF".

Called by the systemd shutdown hook /usr/lib/systemd/system-shutdown/oled-safe
with the action as the first argument (poweroff, halt, reboot, kexec).
On reboot nothing is drawn, the app's "Rebooting" screen stays.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config            # noqa: E402
from ui import screens   # noqa: E402


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "poweroff"
    if action in ("reboot", "kexec"):
        return
    from luma.core.interface.serial import i2c
    from luma.oled.device import sh1106, ssd1306

    driver = sh1106 if config.OLED_DRIVER == "sh1106" else ssd1306
    dev = driver(i2c(port=config.OLED_I2C_PORT, address=config.OLED_ADDR))
    dev.persist = True                  # keep the image after this script ends
    dev.display(screens.render("safe_off"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:              # never block the shutdown
        print(f"oled_safe: {e}", file=sys.stderr)
