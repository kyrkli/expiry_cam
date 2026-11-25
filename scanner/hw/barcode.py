"""GM67 barcode reader over UART (host mode, configured with tools/gm67_setup.py)."""
import logging
import threading
import time

import serial

import config
from hw import gm67

log = logging.getLogger("barcode")


class BarcodeReader(threading.Thread):
    """Reads barcodes from the UART and calls on_barcode(code) for each one."""

    def __init__(self, on_barcode):
        super().__init__(daemon=True, name="scanner")
        self._on_barcode = on_barcode
        self._lock = threading.Lock()   # serialize writes from different threads
        try:
            self._ser = serial.Serial(config.SCANNER_PORT, config.SCANNER_BAUD, timeout=0.1)
        except serial.SerialException as e:
            log.error("cannot open %s: %s", config.SCANNER_PORT, e)
            self._ser = None

    def start_scan(self):
        if not self._ser:
            return
        with self._lock:
            self._ser.reset_input_buffer()   # drop leftovers from earlier scans
            if config.SCANNER_WAKE_BYTE:
                self._ser.write(gm67.WAKEUP)
                time.sleep(0.05)
            self._ser.write(gm67.START_DECODE)

    def stop_scan(self):
        if not self._ser:
            return
        with self._lock:
            self._ser.write(gm67.STOP_DECODE)

    def run(self):
        if self._ser is None:
            return
        buf = bytearray()
        while True:
            try:
                chunk = self._ser.read(64)
            except serial.SerialException as e:
                log.error("serial read error: %s", e)
                time.sleep(1)
                continue
            if not chunk:
                continue
            buf.extend(chunk)
            gm67.strip_control_packets(buf)   # ACKs for START/STOP are not barcodes

            # A barcode ends with CR and/or LF (set by gm67_setup.py)
            while True:
                end = next((i for i, b in enumerate(buf) if b in (0x0D, 0x0A)), None)
                if end is None:
                    break
                raw = bytes(buf[:end])
                del buf[:end + 1]
                code = "".join(ch for ch in raw.decode("ascii", "ignore")
                               if ch.isprintable()).strip()
                if code:
                    log.info("barcode: %s", code)
                    self._on_barcode(code)

            if len(buf) > 512:   # garbage without line endings
                buf.clear()
