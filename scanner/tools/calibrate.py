#!/usr/bin/env python3
"""Battery calibration: compares the ADS1115 reading with a multimeter.

Keep the app running (same load as in real use) and run:
    cd ~/expiry_cam
    venv/bin/python -m tools.calibrate
Hold the multimeter probes on BUCK IN+ / IN- while it measures.
"""
import time
from statistics import median

import smbus

import config


def read_uncalibrated(bus: smbus.SMBus) -> float:
    """Pack voltage from A0 vs GND (±4.096 V range), without K_CAL."""
    bus.write_i2c_block_data(config.ADS_ADDR, 0x01, [0xC3, 0x83])
    time.sleep(0.01)
    hi, lo = bus.read_i2c_block_data(config.ADS_ADDR, 0x00, 2)
    raw = (hi << 8) | lo
    if raw > 32767:
        raw -= 65536
    return raw * 4.096 / 32768 * config.K_DIV


def main() -> None:
    bus = smbus.SMBus(1)
    print("Measuring for 10 s. Keep the multimeter on BUCK IN+ / IN- and")
    print("remember the value it shows.\n")
    samples = []
    for _ in range(10):
        samples.append(read_uncalibrated(bus))
        print(f"  ADS: {samples[-1]:.3f} V")
        time.sleep(1)

    v_ads = median(samples)
    answer = input(f"\nADS median: {v_ads:.3f} V. Multimeter value (V): ")
    v_meter = float(answer.replace(",", "."))
    k_cal = v_meter / v_ads

    print(f"\nPut this into config.py:\n    K_CAL = {k_cal:.4f}")
    if not 0.97 <= k_cal <= 1.03:
        print("\nWarning: unusually large correction. Check R1/R2 values with the")
        print("multimeter and the divider wiring before using this number.")


if __name__ == "__main__":
    main()
