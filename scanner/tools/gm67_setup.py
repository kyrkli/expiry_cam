#!/usr/bin/env python3
"""One-time GM67 configuration over UART.

Stop the app first (it uses the same serial port):
    sudo systemctl stop expiry-cam
Then:
    cd ~/expiry_cam
    sudo venv/bin/python -m tools.gm67_setup --diag     # how the module wakes up (safe)
    sudo venv/bin/python -m tools.gm67_setup --wake     # apply settings
    sudo venv/bin/python -m tools.gm67_setup --test --wake   # START, read one code, STOP
    sudo venv/bin/python -m tools.gm67_setup --lock --wake   # + ignore setup barcodes
    sudo venv/bin/python -m tools.gm67_setup --factory-reset
Wake-up options (use the one --diag found working):
    --wake            send 0x00, wait 50 ms, then the command
    --wake-ms N       same, but wait N ms
    --double          send every command twice (the first one only wakes the module)
"""
import argparse
import os
import subprocess
import sys
import time

import serial

import config
from hw import gm67

RETRIES = 3
PAUSE_BETWEEN_S = 1.0     # give the module time to store each setting

WAKE_MS = None            # None = no wake-up byte
DOUBLE = False            # send each command twice


def hexs(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# --- make sure nobody else reads the port ---------------------------------------
def app_running() -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "expiry-cam"],
                           capture_output=True, text=True)
        return r.stdout.strip() == "active"
    except FileNotFoundError:
        return False


def other_port_users(port: str) -> list[str]:
    """Processes that have the serial device open (visible ones only)."""
    dev = os.path.realpath(port)
    users = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == os.getpid():
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fd_dir):
                if os.path.realpath(os.path.join(fd_dir, fd)) == dev:
                    with open(f"/proc/{pid}/comm") as f:
                        users.append(f"{pid} ({f.read().strip()})")
                    break
        except OSError:
            continue
    return users


# --- sending ---------------------------------------------------------------------
def write_cmd(ser: serial.Serial, pkt: bytes) -> None:
    if WAKE_MS is not None:
        ser.write(gm67.WAKEUP)
        ser.flush()
        time.sleep(WAKE_MS / 1000)
    if DOUBLE:
        ser.write(pkt)
        ser.flush()
        time.sleep(0.1)
        ser.reset_input_buffer()   # ignore a reply to the wake-up copy
    ser.write(pkt)
    ser.flush()                    # wait until all bytes are physically sent


def read_reply(ser: serial.Serial, seconds: float) -> bytes:
    reply = b""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        reply += ser.read(32)
        if bytes([gm67.OP_ACK]) in reply or bytes([gm67.OP_NAK]) in reply:
            break
    return reply


def send(ser: serial.Serial, name: str, pkt: bytes) -> bool:
    """Send one command and wait for ACK/NAK, with retries."""
    reply = b""
    for attempt in range(1, RETRIES + 1):
        ser.reset_input_buffer()
        write_cmd(ser, pkt)
        reply = read_reply(ser, 1.5)
        if bytes([gm67.OP_ACK]) in reply:
            note = f" (attempt {attempt})" if attempt > 1 else ""
            print(f"  OK   {name}{note}")
            time.sleep(PAUSE_BETWEEN_S)
            return True
        if bytes([gm67.OP_NAK]) in reply:
            print(f"  NAK  {name}  (reply: {hexs(reply)})")
            time.sleep(PAUSE_BETWEEN_S)
            return False
        time.sleep(PAUSE_BETWEEN_S)
    print(f"  ???  {name}  (no ACK after {RETRIES} tries, reply: {hexs(reply) or 'nothing'})")
    return False


# --- modes -----------------------------------------------------------------------
def diag(ser: serial.Serial) -> None:
    """Try several wake-up methods with a harmless read-only request."""
    rev = gm67.REQUEST_REVISION
    methods = [
        ("no wake-up", []),
        ("0x00, wait 10 ms", [(gm67.WAKEUP, 0.01)]),
        ("0x00, wait 50 ms", [(gm67.WAKEUP, 0.05)]),
        ("0x00, wait 200 ms", [(gm67.WAKEUP, 0.2)]),
        ("3x 0x00, wait 50 ms", [(b"\x00\x00\x00", 0.05)]),
        ("request sent twice", [(rev, 0.1)]),
    ]
    print("Probing (about 20 s). Every method waits 2 s first so the module can fall asleep.\n")
    for label, pre in methods:
        time.sleep(2.0)
        ser.reset_input_buffer()
        for data, delay in pre:
            ser.write(data)
            ser.flush()
            time.sleep(delay)
        ser.write(rev)
        ser.flush()
        reply = b""
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            reply += ser.read(64)
        text = "".join(chr(b) for b in reply if 32 <= b < 127)
        result = f"{hexs(reply)}  {text!r}" if reply else "nothing"
        print(f"  {label:24} -> {result}")
    print("\nSend this output, it shows which wake-up method works.")


def test_scan(ser: serial.Serial) -> None:
    print("START sent: the white light should turn on. Hold a barcode in front (5 s)...")
    ser.reset_input_buffer()
    write_cmd(ser, gm67.START_DECODE)
    buf = bytearray()
    raw = bytearray()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        chunk = ser.read(64)
        raw += chunk
        buf += chunk
        gm67.strip_control_packets(buf)
        if b"\r" in buf or b"\n" in buf:
            break
    write_cmd(ser, gm67.STOP_DECODE)
    text = buf.decode("ascii", "ignore").strip()
    print(f"Result: {text!r}" if text else "No barcode read.")
    print(f"Raw bytes ({len(raw)}): {hexs(raw[:48])}{' ...' if len(raw) > 48 else ''}")


def main() -> None:
    global WAKE_MS, DOUBLE
    ap = argparse.ArgumentParser(description="Configure the GM67 barcode module")
    ap.add_argument("--diag", action="store_true", help="find a working wake-up method (safe)")
    ap.add_argument("--test", action="store_true", help="START, read one barcode, STOP")
    ap.add_argument("--lock", action="store_true", help="also ignore setup barcodes")
    ap.add_argument("--factory-reset", action="store_true", help="restore factory settings")
    ap.add_argument("--wake", action="store_true", help="0x00 wake-up byte, wait 50 ms")
    ap.add_argument("--wake-ms", type=int, help="0x00 wake-up byte, wait N ms")
    ap.add_argument("--double", action="store_true", help="send every command twice")
    args = ap.parse_args()
    WAKE_MS = None
    if args.wake_ms is not None:
        WAKE_MS = args.wake_ms
    elif args.wake:
        WAKE_MS = 50
    DOUBLE = args.double

    if app_running():
        sys.exit("The app is running and reads the same port.\n"
                 "Stop it first:  sudo systemctl stop expiry-cam")
    users = other_port_users(config.SCANNER_PORT)
    if users:
        sys.exit(f"{config.SCANNER_PORT} is already open by: {', '.join(users)}\n"
                 "Stop that process first.")

    with serial.Serial(config.SCANNER_PORT, config.SCANNER_BAUD,
                       timeout=0.1, exclusive=True) as ser:
        if args.diag:
            diag(ser)
            return
        if args.test:
            test_scan(ser)
            return
        if args.factory_reset:
            send(ser, "Factory reset", gm67.FACTORY_RESET)
            return

        settings = list(gm67.SETTINGS) + ([gm67.LOCK_SETUP_CODES] if args.lock else [])
        wake = "off" if WAKE_MS is None else f"0x00 + {WAKE_MS} ms"
        print(f"Applying settings (wake-up: {wake}, double send: {'on' if DOUBLE else 'off'}):")
        ok = fails_in_row = 0
        for name, pkt in settings:
            if send(ser, name, pkt):
                ok += 1
                fails_in_row = 0
            else:
                fails_in_row += 1
                if fails_in_row >= 2:
                    print("\nThe module stopped responding. Run --diag to find a wake-up")
                    print("method, then run this script again with that option.")
                    break
        print(f"Done: {ok}/{len(settings)} confirmed.")


if __name__ == "__main__":
    main()
