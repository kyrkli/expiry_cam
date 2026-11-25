"""GM67 serial protocol helpers (from the GM67 manual, Appendix 6).

Packet format: <length> <opcode> <source=0x04> <status> [data...] <checksum hi> <checksum lo>
length counts all bytes except the 2 checksum bytes.
checksum = 0x10000 - (sum of all bytes before it), 16-bit, big-endian.
"""


def packet(*body: int) -> bytes:
    """Build a packet from its body bytes and append the checksum."""
    s = sum(body) & 0xFFFF
    c = (0x10000 - s) & 0xFFFF
    return bytes(body) + bytes([c >> 8, c & 0xFF])


def param(*data: int) -> bytes:
    """PARAM_SEND (opcode 0xC6), status 0x08 = store permanently."""
    body = (0xC6, 0x04, 0x08, 0x00) + data
    return packet(len(body) + 1, *body)


# --- Commands -------------------------------------------------------------------
WAKEUP = b"\x00"                                  # harmless; wakes the module if asleep
START_DECODE = packet(0x04, 0xE4, 0x04, 0x00)     # 04 E4 04 00 FF 14
STOP_DECODE = packet(0x04, 0xE5, 0x04, 0x00)      # 04 E5 04 00 FF 13
FACTORY_RESET = param(0xF2, 0xFF, 0x00)           # 08 C6 04 08 00 F2 FF 00 FD 35
REQUEST_REVISION = packet(0x04, 0xA3, 0x04, 0x00) # 04 A3 04 00 FF 55, read-only, safe probe

ACK = packet(0x04, 0xD0, 0x04, 0x00)              # 04 D0 04 00 FF 28
OP_ACK, OP_NAK = 0xD0, 0xD1

# --- Settings for the hand scanner (name, packet) ------------------------------
SETTINGS = [
    # Scan only when the Pi says so (trigger held -> START, released -> STOP)
    ("Read mode: host (serial trigger)", param(0x8A, 0x08)),
    # End every barcode with CR LF, so the Pi knows where it ends (default: none!)
    ("Terminator: CR LF", param(0xF2, 0x05, 0x01)),
    # Allow reading the same product twice in a row (several items, same EAN)
    ("Same code delay: none", param(0xF2, 0xC9, 0x00)),
    # Product barcodes only: 1D on, 2D (QR, DataMatrix, ...) off.
    # QR codes on packaging would otherwise be read instead of the EAN.
    ("1D codes: on", param(0xF2, 0x11, 0x01)),
    ("2D codes: off", param(0xF2, 0x50, 0x00)),
    ("EAN-13: on", param(0x03, 0x01)),
    ("EAN-8: on", param(0x04, 0x01)),
    ("UPC-A: on", param(0x01, 0x01)),
    ("UPC-E: on", param(0x02, 0x01)),
    # Send the full code incl. check digit (needed for product database lookups)
    ("EAN-13: send check digit", param(0xF2, 0x16, 0x01)),
    ("EAN-8: send check digit", param(0xF2, 0x80, 0x01)),
    ("UPC-A: send check digit", param(0x28, 0x01)),
    ("UPC-E: send check digit", param(0x29, 0x01)),
    # UPC codes start with a number-system digit (often 0) that is dropped by default
    ("UPC-A: send leading digit", param(0x22, 0x01)),
    ("UPC-E: send leading digit", param(0x23, 0x01)),
    # Quiet power-up, success beep stays on
    ("Start-up beep: off", param(0xF2, 0x0D, 0x00)),
    ("Success beep: on", param(0x38, 0x01)),
    ("Beep volume: middle", param(0x8C, 0x01)),
    # Max. scan time per START, in 0.1 s units (default 3 s): lets you hold the
    # trigger up to 10 s; also a safety net if STOP never arrives.
    # (The "quick set" variant F2 FA made the E470 hang, this is the plain parameter.)
    ("Scanning duration: 10 s", param(0x88, 0x64)),
]

# Optional, applied last with --lock: ignore setup barcodes from now on
# (reconfiguration then only works over the serial port, e.g. with this script)
LOCK_SETUP_CODES = ("Setup barcodes: ignored", param(0xEC, 0x00))


def strip_control_packets(buf: bytearray) -> None:
    """Remove ACK/NAK packets from a receive buffer in place."""
    i = 0
    while i < len(buf) - 1:
        length, op = buf[i], buf[i + 1]
        if op in (OP_ACK, OP_NAK) and length in (0x04, 0x05):
            end = i + length + 2
            if end > len(buf):
                return          # incomplete packet, wait for more bytes
            del buf[i:end]
            continue
        i += 1
