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
import logging
import queue
import threading
import time

import serial
import serial.tools.list_ports

from m100 import (BAUD, CMD_GET_INFO, CMD_SINGLE_POLL, build_cmd,
                  checksum_ok, cmd_set_power, parse_tag, read_frame)

VID_CH340 = 0x1A86
VID_ARDUINO = (0x2341, 0x2A03)
LEONARDO_PIDS = (0x8036, 0x0036)

CMD_GET_SW_VERSION = build_cmd(0x03, b"\x01")

GET_INFO_ATTEMPTS = 5      # Leonardos may reset when the port opens
GET_INFO_RETRY_WAIT = 0.6  # seconds between attempts (~3 s total)
POLL_INTERVAL = 0.05       # seconds between single polls
SILENT_SECONDS = 5         # no valid reply this long -> reopen the port
RECONNECT_WAIT = 2         # seconds between reconnect attempts
RECONNECT_LOG_EVERY = 600  # while still failing, log a reminder this often
STATS_EVERY = 3600         # log poll/read counters this often

log = logging.getLogger(__name__)


class ReaderError(Exception):
    pass


def _fmt_id(v):
    return f"0x{v:04X}" if v is not None else "----"


def find_reader_ports():
    """Return list_ports entries that look like our readers (CH340 / Arduino)."""
    ports = list(serial.tools.list_ports.comports())
    found = [p for p in ports if p.vid == VID_CH340 or p.vid in VID_ARDUINO]
    if not found:
        log.warning("No CH340 / Arduino serial ports found. Available ports:")
        if not ports:
            log.warning("  (none)")
        for p in ports:
            log.warning(f"  {p.device}  vid={_fmt_id(p.vid)} pid={_fmt_id(p.pid)}  {p.description}")
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


class ReaderSilent(Exception):
    pass


class Reader(threading.Thread):
    """Polls one M100 forever. If it goes silent or the port errors, reopens it.

    A healthy M100 answers every poll (a tag frame, or the 0x01/0xFF "no tag"
    frame). If no valid frame arrives for SILENT_SECONDS, the USB link is
    assumed stuck (e.g. ch341 "urb stopped: -32", where the port stays open
    but delivers nothing) and the port is closed and reopened. The port is
    looked up again by reader id, since a re-enumerated adapter may come back
    under a different device name.
    """

    def __init__(self, port_info, out_queue, min_rssi=0, power=None):
        super().__init__(daemon=True)
        self.port = port_info.device
        self.base_id = reader_id_for(port_info)  # id without any "@port" suffix
        self.id = self.base_id
        self.out_queue = out_queue
        self.min_rssi = min_rssi
        self.power = power
        self.ser = None
        self._stop_event = threading.Event()
        self._open(self.port)
        self.name = f"Reader-{self.port}"
        self.polls = self.answered = self.reads = self.reconnects = 0

    def __repr__(self):
        return f"<Reader {self.id} on {self.port}: {self.hw_info}>"

    def _open(self, port):
        """Open `port`, check it answers GET_INFO, set power. Raises ReaderError."""
        try:
            ser = serial.Serial(port, BAUD, timeout=0.3, write_timeout=1)
        except (serial.SerialException, OSError) as e:
            raise ReaderError(f"{port}: cannot open ({e})") from e

        frame = None
        try:
            for attempt in range(GET_INFO_ATTEMPTS):
                ser.reset_input_buffer()
                frame = _query(ser, CMD_GET_INFO, 0x03)
                if frame:
                    break
                time.sleep(GET_INFO_RETRY_WAIT)
            if not frame:
                raise ReaderError(f"{port}: no valid GET_INFO reply (not an M100 reader?)")
            info = _decode_info(frame)
            sw = _query(ser, CMD_GET_SW_VERSION, 0x03)
            if sw:
                info += f" / {_decode_info(sw)}"
            if self.power is not None:
                ser.write(cmd_set_power(self.power))
                read_frame(ser)
            ser.reset_input_buffer()
        except ReaderError:
            ser.close()
            raise
        except (serial.SerialException, OSError) as e:
            ser.close()
            raise ReaderError(f"{port}: serial error during init ({e})") from e
        self.ser = ser
        self.port = port
        self.hw_info = info

    def _close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def _find_port(self):
        """Device name currently carrying this reader's id, or None."""
        ports = [p.device for p in serial.tools.list_ports.comports()
                 if reader_id_for(p) == self.base_id]
        if self.port in ports:
            return self.port
        # with duplicate ids another reader may own the other match; only take an unambiguous one
        return ports[0] if len(ports) == 1 else None

    def _poll_once(self, last_reply):
        """One inventory round. Returns the time of the last valid reply."""
        ser = self.ser
        ser.write(CMD_SINGLE_POLL)
        self.polls += 1
        frame = read_frame(ser)
        got_reply = False
        while frame is not None:
            if checksum_ok(frame):
                got_reply = True
                tag = parse_tag(frame)
                if tag:
                    rssi, epc = tag
                    if rssi >= self.min_rssi:
                        self.reads += 1
                        self.out_queue.put((self.id, rssi, epc))
            # several tags in range -> several frames; drain what's already arrived
            frame = read_frame(ser) if ser.in_waiting else None
        now = time.time()
        if got_reply:
            self.answered += 1
            return now
        if now - last_reply > SILENT_SECONDS:
            raise ReaderSilent(f"no reply for {now - last_reply:.0f} s")
        return last_reply

    def _reconnect(self):
        """Close and reopen until it works or stop() is called. Returns True if reconnected."""
        self._close()
        down_since = last_log = time.time()
        attempts = 0
        while not self._stop_event.wait(RECONNECT_WAIT):
            attempts += 1
            old_port = self.port
            port = self._find_port()
            if port is None:
                err = "port not found (unplugged?)"
            else:
                try:
                    self._open(port)
                except ReaderError as e:
                    err = str(e)
                else:
                    self.reconnects += 1
                    moved = f" (was {old_port})" if port != old_port else ""
                    log.info("Reader %s reconnected on %s%s after %.0f s, %d attempt(s)",
                             self.id, port, moved, time.time() - down_since, attempts)
                    return True
            if attempts == 1 or time.time() - last_log >= RECONNECT_LOG_EVERY:
                log.warning("Reader %s: reconnect attempt %d failed: %s (retrying every %g s)",
                            self.id, attempts, err, RECONNECT_WAIT)
                last_log = time.time()
        return False

    def _log_stats(self):
        log.info("Reader %s on %s: %d polls, %d answered, %d tag reads, %d reconnects so far",
                 self.id, self.port, self.polls, self.answered, self.reads, self.reconnects)
        self.polls = self.answered = self.reads = 0

    def run(self):
        last_reply = last_stats = time.time()
        try:
            while not self._stop_event.is_set():
                try:
                    last_reply = self._poll_once(last_reply)
                except ReaderSilent as e:
                    log.warning("Reader %s (%s) went silent: %s; reconnecting", self.id, self.port, e)
                except (serial.SerialException, OSError) as e:
                    log.warning("Reader %s (%s) serial error: %s; reconnecting", self.id, self.port, e)
                except Exception:
                    log.exception("Reader %s (%s) unexpected error; reconnecting", self.id, self.port)
                else:
                    if time.time() - last_stats >= STATS_EVERY:
                        self._log_stats()
                        last_stats = time.time()
                    self._stop_event.wait(POLL_INTERVAL)
                    continue
                if not self._reconnect():
                    break
                last_reply = time.time()
        finally:
            self._close()
            log.info("Reader %s stopped", self.id)

    def stop(self):
        self._stop_event.set()


def open_readers(out_queue, min_rssi=0, power=None):
    """Open every detected reader port (threads NOT started). Skips failures."""
    readers = []
    for p in find_reader_ports():
        try:
            r = Reader(p, out_queue, min_rssi=min_rssi, power=power)
        except ReaderError as e:
            log.warning(f"Skipping {e}")
            continue
        log.info(f"Found reader {r.id} on {r.port}: {r.hw_info}")
        readers.append(r)

    counts = {}
    for r in readers:
        counts[r.id] = counts.get(r.id, 0) + 1
    for r in readers:
        if counts[r.id] > 1:
            new_id = f"{r.id}@{r.port}"
            log.warning(f"Duplicate reader id {r.id!r}; using {new_id!r} for {r.port}")
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
