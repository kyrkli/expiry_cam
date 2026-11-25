#!/usr/bin/env python3
"""Hand scanner main program.

Trigger (GPIO24): click = photo of the expiry date, hold = scan barcode.
Power   (GPIO23): hold 3 s = shutdown, double click = reboot.
"""
import logging
import queue
import subprocess
import threading
import time

from gpiozero import Button

import config
from hw import camera
from hw.barcode import BarcodeReader
from hw.battery import BatteryMonitor
from net import client
from ui.display import Display

log = logging.getLogger("app")

CAPTURE_KEEP_DAYS = 14      # photos left in captures/ after a failed upload are deleted then
PENDING_TIMEOUT_S = 180     # a photo (also one without a date) waits this long for its barcode
SPLASH_MIN_S = 1.5          # start screen: at least this long...
SPLASH_MAX_S = 5.0          # ...and at most this long while the server is checked
NO_BARCODE_SHOW_S = 2.5
LOW_BATTERY_SHOW_S = 4.0

# Events sent from callbacks / threads to the main loop
EV_CLICK = "click"
EV_HOLD_START = "hold_start"
EV_HOLD_END = "hold_end"
EV_BARCODE = "barcode"
EV_JOB_DONE = "job_done"
EV_SERVER = "server"            # server went online / offline
EV_LOW_BATTERY = "low_battery"  # battery just went below the warning level

# States
SPLASH = "splash"      # start screen
IDLE = "idle"
BUSY = "busy"          # background job running (photo, upload)
SCANNING = "scanning"  # trigger held, waiting for a barcode
RESULT = "result"      # showing a result for a few seconds

# What a finished job does with the photo that waits for its barcode
KEEP, CLEAR = "keep", "clear"


class App:
    def __init__(self):
        self.events = queue.Queue()
        self.display = Display()     # starts with the splash screen
        self.state = SPLASH
        self.started = time.monotonic()
        self.result_until = 0.0
        self.pending = None          # photo waiting for its barcode: {scan_id, date, since}
                                     # (no_date=True: the photo found no date)
        self.got_barcode = False
        self._photo_expected_s = 3.0  # upload + OCR time, learned, for the progress bar
        self._low_warned = False
        self._power_action = False   # shutdown/reboot already started

        self.battery = BatteryMonitor(
            on_update=self._on_battery_update,
            on_empty=lambda: self.shutdown("Battery empty", "Shutting down"),
        )
        self.barcode = BarcodeReader(on_barcode=lambda code: self.events.put((EV_BARCODE, code)))
        self._setup_buttons()

    # ------------------------------------------------------------------ buttons
    def _setup_buttons(self):
        # Trigger: callbacks only post events, the main loop does the work
        self.trigger = Button(config.PIN_TRIGGER, pull_up=True, bounce_time=0.03,
                              hold_time=config.TRIGGER_HOLD_S)
        self._trigger_held = False
        self.trigger.when_pressed = self._on_trigger_pressed
        self.trigger.when_held = self._on_trigger_held
        self.trigger.when_released = self._on_trigger_released

        # Power: handled directly in the callbacks, so it works in any state
        self.power = Button(config.PIN_POWER, pull_up=True, bounce_time=0.05,
                            hold_time=config.POWER_HOLD_S)
        self._power_held = False
        self._last_power_click = 0.0
        self.power.when_pressed = self._on_power_pressed
        self.power.when_held = self._on_power_held
        self.power.when_released = self._on_power_released

    def _on_trigger_pressed(self):
        self._trigger_held = False
        self.display.wake()

    def _on_trigger_held(self):
        self._trigger_held = True
        self.events.put((EV_HOLD_START, None))

    def _on_trigger_released(self):
        self.events.put((EV_HOLD_END if self._trigger_held else EV_CLICK, None))

    def _on_power_pressed(self):
        self._power_held = False
        self.display.wake()

    def _on_power_held(self):
        self._power_held = True
        self.shutdown()

    def _on_power_released(self):
        if self._power_held:          # long press already handled
            return
        now = time.monotonic()
        if now - self._last_power_click <= config.POWER_DOUBLE_S:
            self.reboot()
        else:
            self._last_power_click = now

    # ------------------------------------------------------------------ battery
    def _on_battery_update(self, voltage, pct, low):
        # Always show a low-battery warning, the normal indicator only if enabled
        if config.BATTERY_SHOW or low:
            self.display.set_battery(pct, low)
        else:
            self.display.hide_battery()
        if low and not self._low_warned:          # full-screen warning once
            self._low_warned = True
            self.events.put((EV_LOW_BATTERY, pct))
        elif not low:
            self._low_warned = False

    # ------------------------------------------------------------ power actions
    def shutdown(self, title="Shutting down", sub="Please wait"):
        if self._power_action:
            return
        self._power_action = True
        log.info("shutdown requested")
        try:
            self.display.freeze("message", title=title, sub=sub)
        except Exception:
            log.exception("display failed, shutting down anyway")
        finally:
            subprocess.run(["systemctl", "poweroff"])

    def reboot(self):
        if self._power_action:
            return
        self._power_action = True
        log.info("reboot requested")
        try:
            self.display.freeze("message", title="Rebooting", sub="Please wait")
        except Exception:
            log.exception("display failed, rebooting anyway")
        finally:
            subprocess.run(["systemctl", "reboot"])

    # ---------------------------------------------------------------- main loop
    def run(self):
        if config.BATTERY_ENABLED:
            self.battery.start()
        self.barcode.start()
        client.start_monitor(on_change=lambda online: self.events.put((EV_SERVER, online)))
        log.info("scanner app started")

        while True:
            try:
                ev, data = self.events.get(timeout=0.2)
                self.handle(ev, data)
            except queue.Empty:
                pass
            self._timers()

    def _timers(self):
        now = time.monotonic()
        if self.state == SPLASH:
            waited = now - self.started
            if (waited >= SPLASH_MIN_S and client.is_online() is not None) \
                    or waited >= SPLASH_MAX_S:
                self.show_idle()
        elif self.state == RESULT and now > self.result_until:
            self.show_idle()

        if self.pending and now - self.pending["since"] > PENDING_TIMEOUT_S:
            log.info("photo (scan %s) got no barcode in time", self.pending["scan_id"])
            self.set_pending(None)
            if self.state == IDLE:
                self.show_idle(wake=False)

    def handle(self, ev, data):
        ready = self.state in (SPLASH, IDLE, RESULT)

        if ev == EV_JOB_DONE:
            screen, screen_data, pending = data
            if pending == CLEAR:
                self.set_pending(None)
            elif isinstance(pending, dict):
                self.set_pending(pending)
            self.show_result(screen, **screen_data)

        elif ev == EV_SERVER:
            self.display.set_server(data)
            if self.state == IDLE:
                self.show_idle(wake=False)    # "Ready" / "Offline"

        elif ev == EV_LOW_BATTERY:
            if self.state in (IDLE, RESULT):
                self.show_result("low_battery", seconds=LOW_BATTERY_SHOW_S, pct=data)

        elif ev == EV_CLICK and ready:
            self.set_pending(None)    # a new photo replaces the waiting one
            self.run_job(self.job_photo)

        elif ev == EV_HOLD_START and ready:
            self.state = SCANNING
            self.got_barcode = False
            self.display.show("scanning")
            self.barcode.start_scan()

        elif ev == EV_BARCODE and self.state == SCANNING:
            self.got_barcode = True
            self.barcode.stop_scan()
            self.run_job(self.job_barcode, data, self.pending)

        elif ev == EV_HOLD_END and self.state == SCANNING:
            self.barcode.stop_scan()
            if not self.got_barcode:
                self.show_result("error", seconds=NO_BARCODE_SHOW_S, title="No barcode",
                                 hint="Hold until it beeps", icon="barcode")

        else:
            log.debug("ignored %s in state %s", ev, self.state)

    # ---------------------------------------------------------------- screens
    def set_pending(self, pending):
        self.pending = pending
        self.display.set_pending(pending is not None)

    def show_idle(self, wake=True):
        """wake=False for background changes: do not undim a sleeping screen."""
        self.state = IDLE
        if self.pending:
            self.display.show("pending", wake=wake, date=self.pending["date"],
                              no_date=self.pending.get("no_date", False))
        else:
            self.display.show("idle", wake=wake, online=client.is_online())

    def show_result(self, screen, seconds=None, **data):
        self.state = RESULT
        self.result_until = time.monotonic() + (seconds or config.RESULT_SHOW_S)
        self.display.show(screen, **data)

    # ------------------------------------------------------------ background jobs
    def run_job(self, func, *args):
        """Run a slow task in a thread. It returns (screen, data, pending action),
        which comes back to the main loop as EV_JOB_DONE."""
        self.state = BUSY

        def worker():
            try:
                result = func(*args)
            except Exception as e:
                log.exception("job %s failed", func.__name__)
                result = (*error_screen(e), KEEP)
            self.events.put((EV_JOB_DONE, result))

        threading.Thread(target=worker, daemon=True).start()

    def job_photo(self):
        self.display.show("hold_still")
        path = camera.capture()
        t0 = time.monotonic()
        self.display.show("progress", title="Reading date", expected=self._photo_expected_s)
        res = client.send_image(path)
        self._photo_expected_s = 0.7 * self._photo_expected_s + 0.3 * (time.monotonic() - t0)
        if res.get("scan_id") is None:       # the server stores nothing without a date
            # Retake, or scan the barcode: then the product is saved without a date
            pending = dict(scan_id=None, date=None, no_date=True, since=time.monotonic())
            return ("error", dict(title="Date not found", hint="Retake or scan code",
                                  icon="camera"), pending)
        date = res.get("expiry_display") or "?"
        pending = dict(scan_id=res["scan_id"], date=date, since=time.monotonic())
        screen = "expired" if res.get("expired") else "date"
        return (screen, dict(date=date, days_left=res.get("days_left")), pending)

    def job_barcode(self, code, pending):
        self.display.show("progress", title="Looking up", expected=1.5)
        scan_id = pending["scan_id"] if pending else None
        no_date = bool(pending and pending.get("no_date"))
        res = client.send_barcode(code, scan_id, no_date=no_date)
        date = res.get("expiry_display") or (pending or {}).get("date")
        return ("product", dict(name=res.get("product"), code=res.get("barcode") or code,
                                saved=res.get("saved", scan_id is not None), date=date,
                                count=res.get("count")), CLEAR)


def error_screen(e):
    """Exception -> ("error", screen data) with a short title and a hint."""
    if isinstance(e, client.ServerError):
        hint = "Check the Pi 5" if str(e) == "No server" else "Try again"
        return "error", dict(title=str(e), hint=hint)
    if isinstance(e, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
        return "error", dict(title="Camera error", hint="Try again", icon="camera")
    return "error", dict(title="Error", hint=str(e)[:40] or type(e).__name__)


def clean_captures():
    """Photos stay in captures/ only when the upload failed; delete them after
    CAPTURE_KEEP_DAYS (unless KEEP_LOCAL_PHOTOS asks to keep every photo)."""
    if getattr(config, "KEEP_LOCAL_PHOTOS", False) or not config.CAPTURE_DIR.is_dir():
        return
    limit = time.time() - CAPTURE_KEEP_DAYS * 86400
    deleted = 0
    for photo in config.CAPTURE_DIR.glob("*.jpg"):
        try:
            if photo.stat().st_mtime < limit:
                photo.unlink()
                deleted += 1
        except OSError as e:
            log.warning("could not delete %s: %s", photo, e)
    if deleted:
        log.info("deleted %d old photos from captures/", deleted)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    clean_captures()
    App().run()


if __name__ == "__main__":
    main()
