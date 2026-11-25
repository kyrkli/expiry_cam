"""Battery monitor thread: ADS1115 A0 -> pack voltage -> state of charge."""
import logging
import threading
import time
from collections import deque
from statistics import median

import smbus

import config

log = logging.getLogger("battery")

# Pack voltage (2S Li-ion, light load) -> state of charge, %.
# Rough values; 0 % is our safe cut-off, not the cell's absolute minimum.
# Replace with numbers from your own discharge test.
SOC_TABLE = [
    (8.30, 100), (8.10, 90), (7.95, 80), (7.85, 70), (7.75, 60),
    (7.65, 50), (7.55, 40), (7.45, 30), (7.30, 20), (7.10, 10), (6.60, 0),
]


def soc_percent(v: float) -> int:
    """Linear interpolation in SOC_TABLE."""
    if v >= SOC_TABLE[0][0]:
        return 100
    if v <= SOC_TABLE[-1][0]:
        return 0
    for (v_hi, p_hi), (v_lo, p_lo) in zip(SOC_TABLE, SOC_TABLE[1:]):
        if v_lo <= v <= v_hi:
            return round(p_lo + (v - v_lo) * (p_hi - p_lo) / (v_hi - v_lo))
    return 0


class BatteryMonitor(threading.Thread):
    """Reads the pack voltage every BATTERY_READ_INTERVAL_S and reports a smoothed value.

    on_update(voltage, pct, low) is called after every reading.
    on_empty() is called once when the pack stays below the cut-off.
    """

    def __init__(self, on_update, on_empty):
        super().__init__(daemon=True, name="battery")
        self._bus = smbus.SMBus(1)
        self._on_update = on_update
        self._on_empty = on_empty
        window = round(config.BATTERY_WINDOW_S / config.BATTERY_READ_INTERVAL_S)
        self._samples = deque(maxlen=max(3, window))   # median over BATTERY_WINDOW_S
        self._low_since = None
        self._empty_fired = False
        self.voltage = None                # latest smoothed voltage

    def _read_voltage(self) -> float:
        """Single-shot read of A0 vs GND, ±4.096 V range, 128 SPS."""
        self._bus.write_i2c_block_data(config.ADS_ADDR, 0x01, [0xC3, 0x83])
        time.sleep(0.01)
        hi, lo = self._bus.read_i2c_block_data(config.ADS_ADDR, 0x00, 2)
        raw = (hi << 8) | lo
        if raw > 32767:
            raw -= 65536
        return raw * 4.096 / 32768 * config.K_DIV * config.K_CAL

    def run(self):
        while True:
            try:
                v = self._read_voltage()
                if v >= config.BATTERY_MIN_VALID_V:
                    self._samples.append(v)
            except OSError as e:
                log.warning("ADS read error: %s", e)

            if self._samples:
                v_avg = median(self._samples)
                self.voltage = v_avg
                self._on_update(v_avg, soc_percent(v_avg), v_avg < config.BATTERY_WARN_V)
                self._check_empty(v_avg)

            time.sleep(config.BATTERY_READ_INTERVAL_S)

    def _check_empty(self, v_avg: float):
        # Act only on a full window of valid readings
        if v_avg < config.BATTERY_CUTOFF_V and len(self._samples) == self._samples.maxlen:
            if self._low_since is None:
                self._low_since = time.monotonic()
                log.warning("battery below cut-off: %.2f V", v_avg)
            elif (not self._empty_fired
                  and time.monotonic() - self._low_since >= config.BATTERY_CUTOFF_HOLD_S):
                self._empty_fired = True
                self._on_empty()
        else:
            self._low_since = None
