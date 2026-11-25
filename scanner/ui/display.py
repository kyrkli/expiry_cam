"""OLED display: one thread owns the I2C device and does all drawing.

Other threads only change state (show a screen, battery, server, pending photo)
and the display thread redraws. It also runs animations, dims and turns off the
screen when idle (OLED burn-in protection) and reconnects a lost display.
"""
import logging
import threading
import time

from luma.core.interface.serial import i2c
from luma.oled.device import sh1106, ssd1306

import config
from ui import screens

log = logging.getLogger("display")

FRAME_S = 0.2            # animation frame time (a full frame takes ~0.1 s on I2C)
DIM_AFTER_S = 60         # idle screen: dim after this long without a button press
OFF_AFTER_S = 300        # idle screen: turn off after this long
CONTRAST_NORMAL = 0x7F   # luma default
CONTRAST_DIM = 0x05
REINIT_INTERVAL_S = 5    # how often to retry a lost display
DRAW_RETRIES = 3         # a rare I2C glitch must not leave garbage on screen


class Display(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="display")
        self._lock = threading.Lock()
        self._wakeup = threading.Event()        # something changed: redraw soon
        self._drawn = threading.Condition(self._lock)

        self._screen = "splash"
        self._data = {}
        self._since = time.monotonic()          # when the screen was shown (animations)
        self._server = None
        self._batt = None                       # (pct, low) or None = hidden
        self._pending = False
        self._frozen = False                    # shutdown/reboot message, no more changes
        self._dirty = True
        self._seq = 0                           # bumped by every change
        self._drawn_seq = -1
        self._activity = time.monotonic()       # last button press / new screen

        self._dev = None
        self._power = "on"                      # on / dim / off
        self._last_init_try = 0.0
        self.start()

    # --- public API (any thread) -------------------------------------------------
    def show(self, screen, /, wake=True, **data):
        """Switch to a screen from screens.SCREENS with its data.
        wake=False: background change, a dimmed or dark screen stays that way."""
        with self._lock:
            if self._frozen:
                return
            self._screen, self._data = screen, data
            self._since = time.monotonic()
            if wake:
                self._activity = self._since
            self._changed()

    def wake(self):
        """Button pressed: turn the screen back on / undim it."""
        with self._lock:
            self._activity = time.monotonic()
        self._wakeup.set()

    def set_battery(self, pct, low):
        self._set("_batt", (pct, low))

    def hide_battery(self):
        self._set("_batt", None)

    def set_server(self, online):
        self._set("_server", online)

    def set_pending(self, pending):
        self._set("_pending", bool(pending))

    def freeze(self, screen, /, timeout=3.0, **data):
        """Show a final screen, ignore all further changes and wait until it is drawn."""
        with self._lock:
            self._screen, self._data, self._frozen = screen, data, True
            self._since = self._activity = time.monotonic()
            self._changed()
            target = self._seq
            self._drawn.wait_for(lambda: self._drawn_seq >= target, timeout=timeout)

    # --- internals ---------------------------------------------------------------
    def _set(self, attr, value):
        with self._lock:
            if getattr(self, attr) == value:
                return
            setattr(self, attr, value)
            self._changed()

    def _changed(self):
        """Call with the lock held."""
        self._dirty = True
        self._seq += 1
        self._wakeup.set()

    def run(self):
        while True:
            with self._lock:
                animated = screens.SCREENS[self._screen].animated and self._power == "on"
            self._wakeup.wait(FRAME_S if animated else 1.0)
            self._wakeup.clear()
            try:
                self._tick()
            except Exception:
                log.exception("display thread error")
                self._dev = None
                time.sleep(1)

    def _tick(self):
        now = time.monotonic()
        with self._lock:
            screen = screens.SCREENS[self._screen]
            name, data = self._screen, dict(self._data)
            t = now - self._since
            status = dict(server=self._server, battery=self._batt, pending=self._pending)
            dirty, seq, idle_for = self._dirty, self._seq, now - self._activity
            frozen = self._frozen

        if self._dev is None:
            if now - self._last_init_try < REINIT_INTERVAL_S and not frozen:
                return
            if not self._connect():
                return
            dirty = True

        # Burn-in protection: only idle screens dim and turn off
        want = "on"
        if screen.idle and not frozen:
            if idle_for >= OFF_AFTER_S:
                want = "off"
            elif idle_for >= DIM_AFTER_S:
                want = "dim"
        if want != self._power:
            if not self._set_power(want):
                return
            dirty = True

        if self._power == "off":
            self._mark_drawn(seq)            # nothing visible to draw
            return
        if not (dirty or screen.animated):
            return

        img = screens.render(name, t=t, **status, **data)
        for attempt in range(1, DRAW_RETRIES + 1):
            try:
                self._dev.display(img)
                self._mark_drawn(seq)
                return
            except Exception as e:           # OSError, but luma also raises its own errors
                log.warning("OLED draw error (attempt %d): %s", attempt, e)
        self._dev = None                     # reconnect later

    def _mark_drawn(self, seq):
        with self._lock:
            if self._seq == seq:
                self._dirty = False
            self._drawn_seq = max(self._drawn_seq, seq)
            self._drawn.notify_all()

    def _connect(self):
        self._last_init_try = time.monotonic()
        try:
            driver = sh1106 if config.OLED_DRIVER == "sh1106" else ssd1306
            self._dev = driver(i2c(port=config.OLED_I2C_PORT, address=config.OLED_ADDR))
            self._dev.persist = True         # keep the last image when the process stops
            self._dev.contrast(CONTRAST_NORMAL)
            self._power = "on"
            log.info("OLED connected")
            return True
        except Exception as e:
            log.error("OLED init failed: %s", e)
            self._dev = None
            return False

    def _set_power(self, want):
        try:
            if want == "off":
                self._dev.hide()
            else:
                if self._power == "off":
                    self._dev.show()
                self._dev.contrast(CONTRAST_DIM if want == "dim" else CONTRAST_NORMAL)
            log.info("screen %s", want)
            self._power = want
            return True
        except Exception as e:
            log.warning("OLED power change failed: %s", e)
            self._dev = None
            return False
