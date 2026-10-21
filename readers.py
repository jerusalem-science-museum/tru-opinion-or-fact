"""
Discover and run the M5Stack UHF RFID (M100) readers.

Port detection
--------------
Readers sit behind CH340 USB-serial chips (VID 0x1A86) or Arduino Leonardo /
other Arduino boards (VID 0x2341 or 0x2A03). `find_reader_ports()` matches
`serial.tools.list_ports.comports()` entries by VID; if nothing matches it
prints every available port with its vid/pid/description as a hint.

Reader ID scheme
----------------
GET_INFO (`BB 00 03 00 01 00 04 7E`) returns the hardware-version string, but
two identical M100 modules return the *same* string (the module has no
per-unit serial in its info replies: param 0x00 = hardware version,
0x01 = software version, 0x02 = manufacturer). So that reply is kept in
`Reader.hw_info` for humans only and is NOT used for uniqueness.

`Reader.id` is chosen, in order of preference:
  1. "sn:<serial>"   - USB serial number, if the adapter reports a real one
                       (genuine Leonardos usually do; CH340 usually doesn't).
                       Windows-synthesised instance ids (containing '&') are
                       not real serials and are skipped.
  2. "loc:<path>"    - USB location (physical port path, e.g. "1-2.3:x.0").
  3. "port:<COMx>"   - device name, last resort.

Options 2 and 3 depend on where the reader is plugged in: MOVING A READER TO
ANOTHER USB SOCKET (or a hub reorder / OS re-enumeration) MAY CHANGE ITS ID,
and the D/U assignment then has to be redone. Option 1 survives that.
If two opened readers still end up with the same id, `open_readers()` appends
"@<port>" to each duplicate and prints a warning.

Queue items: `(reader_id, rssi, epc)`.
"""
import queue
import threading
import time

import serial
import serial.tools.list_ports

from uhf_filter import (BAUD, CMD_GET_INFO, build_cmd, checksum_ok,
                        cmd_set_power, parse_tag, read_frame)

VID_CH340 = 0x1A86
VID_ARDUINO = (0x2341, 0x2A03)
LEONARDO_PIDS = (0x8036, 0x0036)

CMD_GET_SW_VERSION = build_cmd(0x03, b"\x01")
CMD_SINGLE_POLL = build_cmd(0x22)

GET_INFO_ATTEMPTS = 5      # Leonardos may reset when the port opens
GET_INFO_RETRY_WAIT = 0.6  # seconds between attempts (~3 s total)
POLL_INTERVAL = 0.05       # seconds between single polls


class ReaderError(Exception):
    pass


def _fmt_id(v):
    return f"0x{v:04X}" if v is not None else "----"


def find_reader_ports():
    """Return list_ports entries that look like our readers (CH340 / Arduino)."""
    ports = list(serial.tools.list_ports.comports())
    found = [p for p in ports if p.vid == VID_CH340 or p.vid in VID_ARDUINO]
    if not found:
        print("No CH340 / Arduino serial ports found. Available ports:")
        if not ports:
            print("  (none)")
        for p in ports:
            print(f"  {p.device}  vid={_fmt_id(p.vid)} pid={_fmt_id(p.pid)}  {p.description}")
    return found


def reader_id_for(port_info):
    """Stable id from USB info: serial number > USB location > device name."""
    sn = (getattr(port_info, "serial_number", None) or "").strip()
    if sn and "&" not in sn:
        return f"sn:{sn}"
    loc = (getattr(port_info, "location", None) or "").strip()
    if loc:
        return f"loc:{loc}"
    return f"port:{port_info.device}"


def _decode_info(frame):
    # reply payload: <param byte> <ascii string>
    return frame[6:-2].decode("ascii", errors="replace").strip("\x00 ")


def _query(ser, cmd, want_cmd):
    """Send cmd, return first valid reply frame with the given cmd byte, or None."""
    ser.write(cmd)
    deadline = time.time() + 0.6
    while time.time() < deadline:
        frame = read_frame(ser)
        if frame is None:
            return None
        if checksum_ok(frame) and frame[1] == 0x01 and frame[2] == want_cmd:
            return frame
    return None


class Reader(threading.Thread):
    def __init__(self, port_info, out_queue, min_rssi=0, power=None):
        super().__init__(daemon=True)
        self.port = port_info.device
        self.id = reader_id_for(port_info)
        self.out_queue = out_queue
        self.min_rssi = min_rssi
        self._stop_event = threading.Event()
        try:
            self.ser = serial.Serial(self.port, BAUD, timeout=0.3)
        except (serial.SerialException, OSError) as e:
            raise ReaderError(f"{self.port}: cannot open ({e})") from e

        frame = None
        try:
            for attempt in range(GET_INFO_ATTEMPTS):
                self.ser.reset_input_buffer()
                frame = _query(self.ser, CMD_GET_INFO, 0x03)
                if frame:
                    break
                time.sleep(GET_INFO_RETRY_WAIT)
            if not frame:
                raise ReaderError(f"{self.port}: no valid GET_INFO reply (not an M100 reader?)")
            info = _decode_info(frame)
            sw = _query(self.ser, CMD_GET_SW_VERSION, 0x03)
            if sw:
                info += f" / {_decode_info(sw)}"
            self.hw_info = info
            if power is not None:
                self.ser.write(cmd_set_power(power))
                read_frame(self.ser)
        except ReaderError:
            self.ser.close()
            raise
        except (serial.SerialException, OSError) as e:
            self.ser.close()
            raise ReaderError(f"{self.port}: serial error during init ({e})") from e
        self.name = f"Reader-{self.port}"

    def __repr__(self):
        return f"<Reader {self.id} on {self.port}: {self.hw_info}>"

    def run(self):
        ser = self.ser
        try:
            ser.reset_input_buffer()
            while not self._stop_event.is_set():
                # One inventory round: reply is a tag frame per tag seen, or a
                # 0x01/0xFF error frame meaning "no tag in range".
                ser.write(CMD_SINGLE_POLL)
                frame = read_frame(ser)
                while frame is not None:
                    if checksum_ok(frame):
                        tag = parse_tag(frame)
                        if tag:
                            rssi, epc = tag
                            if rssi >= self.min_rssi:
                                self.out_queue.put((self.id, rssi, epc))
                    # several tags in range -> several frames; drain what's already arrived
                    frame = read_frame(ser) if ser.in_waiting else None
                time.sleep(POLL_INTERVAL)
        except (serial.SerialException, OSError) as e:
            print(f"Reader {self.id} ({self.port}) stopped: {e}")
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()


def open_readers(out_queue, min_rssi=0, power=None):
    """Open every detected reader port (threads NOT started). Skips failures."""
    readers = []
    for p in find_reader_ports():
        try:
            r = Reader(p, out_queue, min_rssi=min_rssi, power=power)
        except ReaderError as e:
            print(f"Skipping {e}")
            continue
        print(f"Found reader {r.id} on {r.port}: {r.hw_info}")
        readers.append(r)

    counts = {}
    for r in readers:
        counts[r.id] = counts.get(r.id, 0) + 1
    for r in readers:
        if counts[r.id] > 1:
            new_id = f"{r.id}@{r.port}"
            print(f"WARNING: duplicate reader id {r.id!r}; using {new_id!r} for {r.port}")
            r.id = new_id
    return readers


def wait_for_tag(q, ignore=(), reader_ids=None, timeout=None):
    """Drain stale reads, then block until a fresh tag arrives.

    Skips epcs in `ignore` and (if given) readers not in `reader_ids`.
    Returns (reader_id, epc), or None if `timeout` seconds pass first.
    """
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            break
    deadline = None if timeout is None else time.time() + timeout
    while True:
        remaining = None if deadline is None else deadline - time.time()
        if remaining is not None and remaining <= 0:
            return None
        try:
            reader_id, _rssi, epc = q.get(timeout=remaining)
        except queue.Empty:
            return None
        if epc in ignore:
            continue
        if reader_ids is not None and reader_id not in reader_ids:
            continue
        return reader_id, epc
