# Opinion or Fact (דעה או עובדה)

A science-museum exhibit about telling opinions from facts.

Visitors pick up a **cube** and place it on one of two RFID readers:

- the **D reader** (*de'a*, דעה, opinion) shows the cube's **opinion** picture;
- the **U reader** (*uvda*, עובדה, fact) shows the cube's **fact** picture.

The picture fills the screen for a few seconds (and the cube's sound plays, if it has one), then the screen goes back to the **background** picture. Each cube has a tag on all six faces, so it works whichever way up it's placed.

A Raspberry Pi runs the app, with two M5Stack UHF RFID readers on USB and a screen. On power-up the Pi logs in and starts the exhibit full-screen by itself.

The words used here (cube, tag, D/U reader, trigger, …) are defined in [GLOSSARY.md](GLOSSARY.md).

---

## Day-to-day use

| On the exhibit window | Does |
|---|---|
| type `new` then Enter | register new cubes (see below) |
| Esc | quit the app |

To restart after quitting, reboot the Pi, or open a terminal in the project folder and run `./run.sh`.

All configuration lives in two files in the project folder:

- `tags.json`: the cubes, their tags and pictures, plus the background picture.
- `config.json`: which reader is D and which is U, plus the [sensitivity settings](#tuning-sensitivity).

Pictures and sounds live in the `data/` folder.

---

## Adding a new cube

### 1. Prepare the media

Copy the two pictures (opinion + fact) and, optionally, an mp3 into the `data/` folder. Any image size works; it is scaled to fit the screen. Skip this step if the new cube reuses pictures that are already registered (e.g. it replaces a lost cube).

### 2. Register it

1. Click the exhibit window and type `new` then Enter. The window hides, showing the terminal behind it.
2. **Cube name**: type a name, or press Enter to accept the suggested one. Names must be unique (e.g. `tomato 2` for a second tomato cube).
3. **"Hold the first tag of this cube near a reader"**: put the cube, any face down, on either reader.
4. **Pictures:**
   - If pictures are already registered, a numbered list of image pairs appears. Type a number to reuse one (its sound comes along), or press Enter to choose new files.
   - Otherwise, three file dialogs open in turn: the **D (opinion)** image, the **U (fact)** image, then the sound (**Cancel** = no sound). Cancelling an image dialog cancels this cube.
5. **"How many more tags for this cube? [5]"**: press Enter for the usual 5 (6 faces in total). Then turn the cube to each remaining face, lift it off and put it back so a **new** face is on the reader each time. Faces that were already read are ignored, so just keep turning until it asks for the next one.
6. **"Register another cube? [y/N]"**: `y` to repeat, Enter to finish. The cubes are saved and the exhibit window comes back.

Ctrl+C in the terminal stops registration. Cubes already finished are kept; the one in progress is discarded.

> The reader only sees tags that are close enough (see [sensitivity](#tuning-sensitivity)), so during registration put the cube right on the reader.

### Replacing a lost cube

Register the replacement as a new cube and reuse the lost cube's image pair at step 4. The old cube's entry can stay in `tags.json`; its tags just won't be seen any more. Remove it if you like (next section).

If a tag that already belongs to another cube is read during registration, it moves to the new cube (the terminal says so). A cube left with no tags is removed.

### Removing or editing a cube

Quit the app (Esc), then edit `tags.json` in a text editor:

```json
{
  "bg": "bg.png",
  "cubes": [
    {
      "name": "tomat",
      "imgD": "tomatD.png",
      "imgU": "tomatU.png",
      "sound": "tomat.mp3",
      "epcs": ["E280689400005036C1626D0D", "..."]
    }
  ]
}
```

- Delete a whole `{ ... }` cube block to remove a cube (mind the commas between blocks).
- `imgD`, `imgU`, `sound` and `bg` are file names inside `data/`. Change them to swap pictures. `sound` is optional.
- `bg` is the background picture shown between cubes.

If the file has a typo, the app refuses to start and names the file in its error. It never overwrites a broken file, so fix it and start again.

---

## Tuning sensitivity

Sensitivity decides **how close a cube must be** to trigger. Too sensitive, and a cube lying near the readers (or held over the *other* reader) triggers by mistake. Not sensitive enough, and visitors have to press the cube down before anything happens.

There are two settings, both in `config.json`:

```json
{
  "readers": { "...": "D", "...": "U" },
  "single_reader": "alternate",
  "min_rssi": 200,
  "power": null,
  "show_seconds": 2
}
```

| Setting | What it does | Values |
|---|---|---|
| `min_rssi` | Signal strength a tag must reach to count. **Raise it** so cubes must be closer; lower it to accept cubes further away. This is the main knob. | 0–255, higher = stronger signal = closer. Current: 200 |
| `power` | Reader transmit power in dBm. **Lower it** to shrink the reader's whole range; useful when the two readers see each other's cubes. | a number (e.g. `20`), or `null` to leave the reader's own setting |
| `show_seconds` | How long a picture stays up before the background returns. | seconds, e.g. `2` |

All three are **required**: if one is missing or invalid, the app stops at startup and says which. Any of them can also be given when starting the app (`--min-rssi`, `--power`, `--show-seconds`), and a value given there overrides `config.json`. The startup log shows each value and where it came from:

```
Settings: min_rssi=200 (config.json), power=reader default (config.json), show_seconds=2 (config.json)
```

### How to find good values

1. Quit the exhibit (Esc). In a terminal in the project folder, start it with read logging:

   ```
   ./run.sh --log-reads
   ```

   Every tag the readers see is now logged (at most once a second per tag) with its signal strength, and whether it counted:

   ```
   Read loc:1-2 E280689400005036C1626D0D rssi=214 kept (min_rssi 200)
   Read loc:1-2 E280689400005036C1626D0D rssi=187 DROPPED (min_rssi 200)
   ```

2. **Should trigger:** place a cube on each reader the way a visitor would (try a few faces) and note the `rssi` values. Call the lowest one *A*.
3. **Should not trigger:** hold a cube where it must *not* count: lying next to the reader, on the table between the readers, over the other reader. Note the highest `rssi`, *B*.
4. Set `min_rssi` between them, e.g. halfway between *B* and *A*, in `config.json`.
5. If *B* is not clearly below *A* (the "wrong" places read as strong as the right ones), lower `power` (try steps of 2–3 dBm) and repeat from step 1, so the reader stops reaching that far. Then fine-tune `min_rssi` again.
6. Quit, and restart normally (reboot, or `./run.sh` without `--log-reads`).

During normal running, each trigger also logs its strength, e.g. `Show tomat D (reader loc:1-2, rssi 214)`, so you can check later how much margin real visitors leave.

Notes:
- Metal, phones and the table material change the readings, so tune **in the exhibit's final place**.
- A cube left on a reader triggers once. It has to be away for about 2 seconds before it triggers again.

---

## Readers and roles

The two readers are identical, so the app has to be told which is D and which is U. On the first start (or when a reader it doesn't recognise is connected), the terminal asks: **"Which reader is D (opinion)?"** Press Enter and hold a cube on the D reader, or type its number from the list. The answer is saved in `config.json` under `readers`.

A reader is recognised by the **USB socket it is plugged into**. Moving a reader to another socket (or a different hub) may make the app ask again. Keep the readers in the same sockets.

### Only one reader connected

`single_reader` in `config.json` decides what a lone reader does:

- `"alternate"`: **toggle mode**: each new placement alternates fact, opinion, fact, … No question is asked.
- `"assign"`: the reader gets a D or U role as usual (asked once, then saved), and the other role simply doesn't work until the second reader is back.

---

## Logs and troubleshooting

Everything the app reports goes to the terminal and to `logs/app.log` (old logs are kept as `app.log.1` … `app.log.5`).

| Symptom | Check |
|---|---|
| App stops at startup with "Settings: … is not set" / "not valid" | Fix `min_rssi` / `power` / `show_seconds` in `config.json`. |
| App stops with "… is corrupt" | A typo in `tags.json` or `config.json`. Fix the file it names. |
| "No CH340 / Arduino serial ports found" | Readers not plugged in or not powered. The log lists the ports it did find. |
| Reader "went silent … reconnecting" | Normal recovery from a USB glitch. It reconnects by itself. If it repeats often, try another cable. |
| A cube does nothing | Is it registered (`tags.json`)? Run with `--log-reads`: if its reads say `DROPPED`, lower `min_rssi`; if nothing is logged, the tag isn't being seen at all. |
| A picture doesn't appear | Log says "Can't show …": the file named in `tags.json` is missing from `data/`. |
| No sound | Log says "Sound disabled" (no audio device) or "Can't play …" (missing file). |

---

## Installing on a fresh Raspberry Pi

```
git clone <repo-url>
cd tru-opinion-or-fact
./setup.sh
sudo reboot
```

`setup.sh` installs Python and the app's dependencies (in `.venv`), installs AnyDesk for remote access (it asks for an unattended-access password and prints the AnyDesk ID: **write it down**), switches to X11, turns off screen blanking, and sets the Pi to log in and start `run.sh` on boot. Copy `tags.json`, `config.json` and the `data/` folder from a working exhibit, or register cubes from scratch.

---

## For developers

Plain Python scripts (`app.py`, `readers.py`, `registration.py`, `store.py`, `m100.py`), with no build or tests. The reader protocol, file formats and how to test without hardware are described in [CLAUDE.md](CLAUDE.md). Run it on a desktop with:

```
pip install -r requirements.txt
python app.py --log-reads
```
