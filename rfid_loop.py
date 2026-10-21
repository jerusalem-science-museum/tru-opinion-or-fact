"""
Continuous tag reader for the M5Stack UHF RFID unit (M100 module).

Usage:
    pip install pyserial
    python uhf_poll.py COM4          (Windows)
    python uhf_poll.py /dev/ttyUSB0  (Linux)

Frame format: BB <type> <cmd> <len_hi> <len_lo> <payload...> <checksum> 7E
Checksum = low byte of the sum of every byte from <type> to the end of <payload>.
"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM4"
BAUD = 115200

CMD_GET_INFO = bytes.fromhex("BB 00 03 00 01 00 04 7E")
CMD_SINGLE_POLL = bytes.fromhex("BB 00 22 00 00 22 7E")


def read_frame(ser):
    """Read one full frame from the serial port. Returns bytes or None on timeout."""
    # Sync on the 0xBB header
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
    """Return (rssi, pc, epc_hex) if this frame is a tag notification, else None."""
    if frame[1] != 0x02 or frame[2] != 0x22:
        return None
    payload = frame[5:-2]
    rssi = payload[0]
    pc = payload[1:3].hex()
    epc = payload[3:-2].hex().upper()  # last 2 bytes are the tag CRC
    return rssi, pc, epc


def main():
    print(f"Opening {PORT} at {BAUD} baud...")
    with serial.Serial(PORT, BAUD, timeout=0.3) as ser:
        ser.reset_input_buffer()

        # Sanity check: ask the reader for its hardware version
        ser.write(CMD_GET_INFO)
        frame = read_frame(ser)
        if frame and checksum_ok(frame):
            print("Reader says:", frame[6:-2].decode("ascii", errors="replace"))
        else:
            print("No valid reply to the info command - check port/baud/power.")
            return

        print("Polling for tags. Hold a UHF tag near the antenna. Ctrl+C to stop.\n")
        seen = {}  # epc -> last time printed

        try:
            while True:
                ser.write(CMD_SINGLE_POLL)
                frame = read_frame(ser)

                if frame and checksum_ok(frame):
                    tag = parse_tag(frame)
                    if tag:
                        rssi, pc, epc = tag
                        now = time.time()
                        # Avoid flooding the screen: re-print the same tag every 1s at most
                        if now - seen.get(epc, 0) > 1.0:
                            print(f"EPC: {epc}   RSSI: {rssi}   PC: {pc}")
                        seen[epc] = now
                    # Error frame (type 0x01, cmd 0xFF) just means "no tag in range"

                time.sleep(0.05)
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()