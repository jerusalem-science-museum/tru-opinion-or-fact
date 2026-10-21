# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A science-museum exhibit ("opinion or fact" — Hebrew *de'a* = opinion, *uvda* = fact) driven by an M5Stack UHF RFID unit (M100 module) over a serial port. Plain Python scripts, no package, no build, no tests. Only dependency is `pyserial`.

```
pip install pyserial
python rfid_loop.py COM4                          # simple single-poll loop, prints each tag (≤1×/s per EPC)
python uhf_filter.py COM5 --calibrate             # print RSSI of every read, to choose a threshold
python uhf_filter.py COM5 --min-rssi 200 [--power 15]   # register only tags with RSSI ≥ threshold; optionally lower TX power (dBm)
```

Testing requires the physical reader plugged in; both scripts first send a GET_INFO command and exit if the reader doesn't answer.

## Reader protocol (shared by both scripts)

- Serial 115200 baud. Frame: `BB <type> <cmd> <len_hi> <len_lo> <payload> <checksum> 7E`; checksum = low byte of sum of bytes from `<type>` through end of payload. `uhf_filter.py`'s `build_cmd()` constructs frames; `rfid_loop.py` uses hardcoded hex.
- Tag notification = type `0x02`, cmd `0x22`. Payload: `rssi(1) | pc(2) | epc(...) | crc(2)`. A type `0x01`/cmd `0xFF` error frame just means "no tag in range".
- Commands used: `0x03` get info, `0x22` single poll, `0x27` multi-poll (count 10000; `uhf_filter.py` re-issues it after 2 s of silence), `0x28` stop multi-poll, `0xB6` set TX power (units of 0.01 dBm).
- `read_frame` / `checksum_ok` / `parse_tag` are duplicated between the two scripts (note `parse_tag` returns different tuples in each). Prefer reusing `uhf_filter.py`'s versions when building new code.

## Exhibit app (spec in README.md)

```
pip install pyserial pillow pygame
python app.py [--min-rssi 200] [--power 15] [--show-seconds 10]
```

Two readers: the **D** reader (de'a, opinion) and the **U** reader (uvda, fact). Each exhibit cube has a tag on all 6 faces; placing it on a reader shows that cube's `imgD` / `imgU` full-screen for 10 s, then back to `bg.jpg`. A tag left on the reader triggers once (it must be away `REARM_SECONDS` to re-trigger). While a cube is showing, reads of any of its tags (any face) from the same reader are ignored until it returns to bg; the same cube on the other reader, or another cube, interrupts. On the window, `new<Enter>` registers cubes in the terminal; Esc quits. If only one reader is connected, startup offers toggle mode (role `TOGGLE`, not saved to config): that reader alternates imgU, imgD, imgU, … on each fresh read.

- `readers.py` — finds ports by USB VID (CH340 0x1A86, Arduino 0x2341/0x2A03), one `Reader` thread per port, all pushing `(reader_id, rssi, epc)` into one shared queue. Reader ids are `sn:<usb serial>` → `loc:<usb location>` → `port:<COMx>`, because both M100s return the same GET_INFO string; moving a reader to another USB socket may change its id and force role re-assignment. Reuses `uhf_filter.py`'s frame helpers.
- `store.py` — `tags.json` = `{"cubes": [{"name","imgD","imgU","epcs":[...], "sound"?}]}` (optional `sound` = mp3 played via `pygame.mixer.music` on every trigger, replacing any sound already playing; app runs silently if pygame/audio is unavailable) (one entry per physical cube; a replacement for a lost cube is a new entry reusing the image pair). `config.json` = `{"readers": {reader_id: "D"|"U"}}`. Atomic writes; corrupt files raise `StoreError` rather than being overwritten. EPCs are normalised upper-case; image paths inside the project are stored relative.
- `registration.py` — terminal flows. `assign_reader_roles` runs at startup only if connected readers lack D/U roles (operator holds a tag on the D reader, or types its number). `register_cubes` asks name → first tag → images (file dialogs D then U, or reuse an existing pair) → N more tags (default 5) → another cube?
- `app.py` — Tk main loop polls the queue with `after()`. Registration runs blocking `input()` on the Tk main thread with the window withdrawn; reads that pile up meanwhile are discarded.

Testing without hardware: build `App(root, queue, roles, tags, secs)` directly and `put` fake `(reader_id, rssi, epc)` tuples on the queue. Run Python with `-B` to avoid `__pycache__`.
