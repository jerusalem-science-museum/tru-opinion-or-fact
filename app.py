"""
Opinion-or-fact exhibit.

Shows bg.jpg full-screen. Putting a registered cube near a reader shows that
cube's imgD (D reader, de'a/opinion) or imgU (U reader, uvda/fact) for 10 s,
then goes back to bg.jpg. With only one reader connected, it can instead
alternate imgU, imgD, imgU, ... on each new read. If the cube has a "sound"
(e.g. mp3), it plays each time the cube triggers.

On the exhibit window:  new<Enter>  registers cubes in the terminal,  Esc quits.

Usage:
    pip install pyserial pillow pygame
    python app.py [--min-rssi 200] [--power 15] [--show-seconds 10]
"""
import argparse
import logging
import os
import queue
import sys
import time
import tkinter as tk
import warnings
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PIL import Image, ImageTk

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
try:
    import pygame.mixer as mixer
    mixer.init()
    mixer_error = None
except Exception as e:  # no pygame / no audio device: run silently
    mixer, mixer_error = None, e

import registration
import store
from readers import open_readers

log = logging.getLogger("app")

LOG_FILE = Path(__file__).resolve().parent / "logs" / "app.log"


def setup_logging():
    """Log to the terminal and to logs/app.log (rotated: 5 x 1 MB kept)."""
    LOG_FILE.parent.mkdir(exist_ok=True)
    to_file = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    to_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s: %(message)s"))
    to_term = logging.StreamHandler()
    to_term.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    logging.basicConfig(level=logging.INFO, handlers=[to_file, to_term])


REARM_SECONDS = 2  # a tag must be away from a reader this long before it triggers again
TOGGLE = "toggle"  # role of a lone reader that alternates U, D, U, ...


class App:
    def __init__(self, root, q, roles, tags, show_seconds):
        self.root = root
        self.q = q
        self.roles = roles            # reader_id -> "D" | "U" | TOGGLE
        self.next_toggle = "U"        # what a TOGGLE reader shows next
        self.tags = tags
        self.index = store.epc_index(tags)
        self.show_ms = int(show_seconds * 1000)
        self.cache = {}
        self.typed = ""
        self.last_seen = {}           # (reader_id, epc) -> time of last read
        self.pending = None           # id of the scheduled return to bg
        self.current = None           # (reader_id, cube) showing now; that cube on that reader is ignored meanwhile

        root.report_callback_exception = lambda *exc: log.error("Error in Tk callback", exc_info=exc)
        root.title("Opinion or Fact")
        root.configure(bg="black")
        self.label = tk.Label(root, bg="black")
        self.label.pack(fill="both", expand=True)
        root.bind("<Key>", self.on_key)
        root.bind("<Escape>", lambda e: root.destroy())

        self.show_window()
        self.show_bg()
        root.after(50, self.poll_tags)

    # --- drawing ---

    def show_window(self):
        self.root.deiconify()
        self.root.attributes("-fullscreen", True)
        self.root.update_idletasks()
        self.root.focus_force()

    def photo(self, path):
        if path not in self.cache:
            w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            img = Image.open(path)
            scale = min(w / img.width, h / img.height)
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
            self.cache[path] = ImageTk.PhotoImage(img)
        return self.cache[path]

    def show(self, path):
        try:
            self.label.configure(image=self.photo(path))
            return True
        except OSError as e:
            log.error("Can't show %s: %s", path, e)
            return False

    def show_bg(self):
        if self.pending:
            self.root.after_cancel(self.pending)
            self.pending = None
        self.current = None
        # no error handling: a bad "bg" in tags.json should crash, not fall back
        self.label.configure(image=self.photo(store.resolve_path(self.tags["bg"])))

    # --- tags ---

    def poll_tags(self):
        try:
            self.handle_reads()
        except Exception:
            log.exception("Error handling tag reads")
        finally:  # always reschedule, or the exhibit stops reacting until restart
            self.root.after(50, self.poll_tags)

    def handle_reads(self):
        now = time.time()
        while True:
            try:
                reader_id, _, epc = self.q.get_nowait()
            except queue.Empty:
                break
            role = self.roles.get(reader_id)
            epc = epc.upper().replace(" ", "")
            key = (reader_id, epc)
            fresh = now - self.last_seen.get(key, 0) > REARM_SECONDS
            self.last_seen[key] = now
            cube = self.index.get(epc)
            # Any face of the cube already showing from this reader (e.g. it was rolled) is
            # ignored until it ends; the same cube on the other reader interrupts.
            showing = self.current and self.current[0] == reader_id and self.current[1] is cube
            if role and cube and fresh and not showing:
                self.trigger(reader_id, cube, role)

    def trigger(self, reader_id, cube, role):
        toggle = role == TOGGLE
        if toggle:
            role = self.next_toggle
        if self.show(store.resolve_path(cube["img" + role])):
            if toggle:
                self.next_toggle = "D" if role == "U" else "U"
            if self.pending:
                self.root.after_cancel(self.pending)
            self.pending = self.root.after(self.show_ms, self.show_bg)
            self.current = (reader_id, cube)
            log.info("Show %s %s (reader %s)", cube.get("name", "?"), role, reader_id)
            if cube.get("sound"):
                self.play(store.resolve_path(cube["sound"]))

    def play(self, path):
        """Play a cube's sound, replacing whatever is playing."""
        if mixer is None:
            return
        try:
            mixer.music.load(str(path))
            mixer.music.play()
        except Exception as e:
            log.error("Can't play %s: %s", path, e)

    # --- keyboard: "new<Enter>" ---

    def on_key(self, event):
        if event.keysym == "Return":
            cmd, self.typed = self.typed.strip().lower(), ""
            if cmd == "new":
                self.register()
        elif event.char and event.char.isprintable():
            self.typed = (self.typed + event.char)[-10:]

    def register(self):
        self.show_bg()
        self.root.withdraw()
        print("\n=== Register cubes (switch to this terminal) ===")
        added = registration.register_cubes(self.root, self.tags, self.q)
        self.index = store.epc_index(self.tags)
        print(f"{added} cube(s) added. Back to the exhibit window.\n")
        while not self.q.empty():   # ignore reads that piled up meanwhile
            self.q.get_nowait()
        self.last_seen.clear()
        self.show_window()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-rssi", type=int, default=200, help="only react to tags with RSSI >= this")
    ap.add_argument("--power", type=float, help="set TX power in dBm (lower = shorter range)")
    ap.add_argument("--show-seconds", type=float, default=2, help="how long to show imgD/imgU")
    args = ap.parse_args()

    setup_logging()
    log.info("=== Starting (log file: %s) ===", LOG_FILE)
    if mixer_error:
        log.warning("Sound disabled (%s)", mixer_error)

    try:
        tags = store.load_tags()
        cfg = store.load_config()
    except store.StoreError as e:
        log.error("%s", e)
        sys.exit(1)

    power = "reader default" if args.power is None else f"{args.power} dBm"
    log.info(f"Settings: min-rssi={args.min_rssi}, power={power}, show-seconds={args.show_seconds}")

    q = queue.Queue()
    readers = open_readers(q, args.min_rssi, args.power)
    for r in readers:
        r.start()

    root = tk.Tk()
    root.withdraw()
    try:
        single = cfg.get("single_reader", "alternate")
        if len(readers) == 1:
            log.info(f"Only one reader connected: single_reader = {single!r} (from config.json)")
        if len(readers) == 1 and single == "alternate":
            roles = {readers[0].id: TOGGLE}
        else:
            roles = registration.assign_reader_roles(readers, cfg, q)
        for r in readers:
            log.info(f"{r.port}: {roles.get(r.id, '?')} reader  ({r.id})")
        log.info(f"{len(tags['cubes'])} cube(s) loaded. Type new<Enter> on the exhibit window to register more.")
        App(root, q, roles, tags, args.show_seconds)
        root.mainloop()
    finally:
        for r in readers:
            r.stop()
        for r in readers:
            r.join(timeout=1)
        log.info("=== Exiting ===")


if __name__ == "__main__":
    main()
