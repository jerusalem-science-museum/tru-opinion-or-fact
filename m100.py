"""
Serial protocol helpers for the M5Stack UHF RFID unit (M100 module).

Frame format: BB <type> <cmd> <len_hi> <len_lo> <payload...> <checksum> 7E
Checksum = low byte of the sum of every byte from <type> to the end of <payload>.
"""
BAUD = 115200


def build_cmd(cmd, payload=b""):
    body = bytes([0x00, cmd, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload
    return b"\xBB" + body + bytes([sum(body) & 0xFF]) + b"\x7E"


CMD_GET_INFO = build_cmd(0x03, b"\x00")
CMD_SINGLE_POLL = build_cmd(0x22)


def cmd_set_power(dbm):
    centi = int(dbm * 100)  # module expects 0.01 dBm units
    return build_cmd(0xB6, bytes([(centi >> 8) & 0xFF, centi & 0xFF]))


def read_frame(ser):
    """Read one full frame from the serial port. Returns bytes or None on timeout."""
    while True:
        b = ser.read(1)
        if not b:
            return None
        if b[0] == 0xBB:
            break
    head = ser.read(4)  # type, cmd, len_hi, len_lo
    if len(head) < 4:
        return None
    length = (head[2] << 8) | head[3]
    rest = ser.read(length + 2)  # payload + checksum + end marker
    if len(rest) < length + 2:
        return None
    return b + head + rest


def checksum_ok(frame):
    return (sum(frame[1:-2]) & 0xFF) == frame[-2]


def parse_tag(frame):
    """Return (rssi, epc_hex) if this frame is a tag notification, else None.

    An error frame (type 0x01, cmd 0xFF) just means "no tag in range".
    """
    if frame[1] != 0x02 or frame[2] != 0x22:
        return None
    payload = frame[5:-2]
    return payload[0], payload[3:-2].hex().upper()  # rssi, epc (last 2 bytes are tag CRC)
