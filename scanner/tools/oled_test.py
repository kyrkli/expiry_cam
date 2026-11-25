#!/usr/bin/env python3
"""OLED check: draws a frame and a text. Stop the app first (it owns the display).

    sudo systemctl stop expiry-cam
    cd ~/expiry_cam && venv/bin/python -m tools.oled_test
If the picture looks shifted by 2 pixels, switch OLED_DRIVER in config.py.
"""
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106, ssd1306

import config

driver = sh1106 if config.OLED_DRIVER == "sh1106" else ssd1306
oled = driver(i2c(port=config.OLED_I2C_PORT, address=config.OLED_ADDR))
oled.persist = True  # keep the image after the script exits

with canvas(oled) as draw:
    draw.rectangle(oled.bounding_box, outline="white")
    draw.text((10, 25), f"Hello, scanner! ({config.OLED_DRIVER})", fill="white")
print("Drawn. Restart the app afterwards: sudo systemctl start expiry-cam")
