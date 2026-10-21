"""
UHF reader (M100) with an RSSI threshold: only tags whose signal is at or above
--min-rssi get "registered". Everything else is ignored.

Usage:
    python uhf_filter.py COM5 --calibrate          # show RSSI of every tag to find a good threshold
    python uhf_filter.py COM5 --min-rssi 200       # register only tags at/above 200
    python uhf_filter.py COM5 --min-rssi 200 --power 15   # also lower TX power to 15 dBm

Frame format: BB <type> <cmd> <len_hi> <len_lo> <payload...> <checksum> 7E
Checksum = low byte of the sum of every byte from <type> to the end of <payload>.
"""
import argparse
import time
import serial

BAUD = 115200


def build_cmd(cmd, payload=b""):
    body = bytes([0x00, cmd, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload
    return b"\xBB" + body + bytes([sum(body) & 0xFF]) + b"\x7E"


CMD_GET_INFO = build_cmd(0x03, b"\x00")
CMD_MULTI_POLL = build_cmd(0x27, bytes([0x22, 0x27, 0x10]))  # 0x2710 = 10000 polls
CMD_STOP_POLL = build_cmd(0x28)


def cmd_set_power(dbm):
    centi = int(dbm * 100)  # module expects 0.01 dBm units
    return build_cmd(0xB6, bytes([(centi >> 8) & 0xFF, centi & 0xFF]))


def read_frame(ser):
    while True:
        b = ser.read(1)
        if not b:
            return None
        if b[0] == 0xBB:
            break
    head = ser.read(4)
    if len(head) < 4:
        return None
    length = (head[2] << 8) | head[3]
    rest = ser.read(length + 2)
    if len(rest) < length + 2:
        return None
    return b + head + rest


def checksum_ok(frame):
    return (sum(frame[1:-2]) & 0xFF) == frame[-2]


def parse_tag(frame):
    if frame[1] != 0x02 or frame[2] != 0x22:
        return None
    payload = frame[5:-2]
    return payload[0], payload[3:-2].hex().upper()  # rssi, epc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("--min-rssi", type=int, default=0, help="register only tags with RSSI >= this")
    ap.add_argument("--calibrate", action="store_true", help="print every read with its RSSI, no filtering")
    ap.add_argument("--power", type=float, help="set TX power in dBm (lower = shorter range)")
    args = ap.parse_args()

    with serial.Serial(args.port, BAUD, timeout=0.3) as ser:
        ser.reset_input_buffer()

        ser.write(CMD_GET_INFO)
        frame = read_frame(ser)
        if not (frame and checksum_ok(frame)):
            print("No valid reply from reader - check port/baud/power.")
            return
        print("Reader:", frame[6:-2].decode("ascii", errors="replace"))

        if args.power is not None:
            ser.write(cmd_set_power(args.power))
            read_frame(ser)
            print(f"Requested TX power: {args.power} dBm")

        registered = {}  # epc -> best rssi seen
        ser.reset_input_buffer()
        ser.write(CMD_MULTI_POLL)
        last_rx = time.time()
        print("Reading... Ctrl+C to stop.\n")

        try:
            while True:
                frame = read_frame(ser)
                if frame is None:
                    # Reader went quiet (poll count finished?) - restart continuous polling
                    if time.time() - last_rx > 2:
                        ser.write(CMD_MULTI_POLL)
                        last_rx = time.time()
                    continue
                if not checksum_ok(frame):
                    continue
                last_rx = time.time()

                tag = parse_tag(frame)
                if not tag:
                    continue
                rssi, epc = tag

                if args.calibrate:
                    print(f"EPC {epc}  RSSI {rssi}")
                    continue

                if rssi >= args.min_rssi:
                    if epc not in registered:
                        print(f"REGISTERED  EPC {epc}  RSSI {rssi}")
                    registered[epc] = max(rssi, registered.get(epc, 0))
        except KeyboardInterrupt:
            ser.write(CMD_STOP_POLL)
            print(f"\nStopped. {len(registered)} tag(s) registered:")
            for epc, best in registered.items():
                print(f"  {epc}  (best RSSI {best})")


if __name__ == "__main__":
    main()
