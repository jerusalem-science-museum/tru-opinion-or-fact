"""Persistence for registered cubes (tags.json) and reader roles (config.json).

tags.json -- one entry per physical cube; all its EPCs share one image pair:
    {"cubes": [{"name": "tomato cube 1", "imgD": "tomatD.jpg",
                "imgU": "tomatU.jpg", "epcs": ["E200...", ...]}]}
  A lost cube is replaced by registering a new entry (it may reuse the same
  image paths).  Media paths are stored relative to the data/ folder
  (DATA_DIR) with forward slashes when they are inside it; anything else is
  stored absolute.

config.json -- {"readers": {"<reader_id>": "D" | "U"}}; other top-level keys
  are kept as-is.

A corrupt (unparsable or wrongly shaped) JSON file raises StoreError naming
the file; it is never silently replaced, so a hand-edit typo can't wipe the
registrations.

Standard library only.  All functions read HERE / TAGS_FILE / CONFIG_FILE at
call time, so tests can monkeypatch them.
"""

import json
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"  # images and sounds; also the default folder for file dialogs
TAGS_FILE = HERE / "tags.json"
CONFIG_FILE = HERE / "config.json"


class StoreError(Exception):
    """A tags/config file exists but can't be used (corrupt JSON or bad shape)."""


# ---------- generic JSON helpers ----------

def _load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise StoreError(f"{path} is corrupt ({e}). Fix or remove it; "
                         f"it was left untouched.") from e
    if not isinstance(data, dict):
        raise StoreError(f"{path} must contain a JSON object, "
                         f"got {type(data).__name__}. It was left untouched.")
    return data


def _save_json(path, data):
    """Atomic write: temp file in the same folder, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------- paths ----------

def to_stored_path(path) -> str:
    """Relative to DATA_DIR (forward slashes) if inside it, else absolute."""
    p = Path(path).expanduser().resolve()
    try:
        return p.relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:      # outside the project, incl. another drive letter
        return str(p)


def resolve_path(stored) -> Path:
    p = Path(stored)
    return p if p.is_absolute() else DATA_DIR / p


# ---------- tags ----------

def _norm_epc(epc) -> str:
    return "".join(str(epc).split()).upper()


def load_tags() -> dict:
    data = _load_json(TAGS_FILE, {"cubes": []})
    cubes = data.setdefault("cubes", [])
    if not isinstance(cubes, list) or not all(
            isinstance(c, dict) and isinstance(c.get("epcs", []), list)
            for c in cubes):
        raise StoreError(f"{TAGS_FILE}: 'cubes' must be a list of objects "
                         f"with an 'epcs' list. It was left untouched.")
    for c in cubes:
        c.setdefault("epcs", [])
    return data


def save_tags(data: dict) -> None:
    _save_json(TAGS_FILE, data)


def epc_index(data: dict) -> dict:
    """epc -> its cube dict (EPCs normalised to upper-case, no spaces)."""
    index = {}
    for cube in data.get("cubes", []):
        for epc in cube.get("epcs", []):
            index[_norm_epc(epc)] = cube
    return index


def add_cube(data, name, img_d, img_u, epcs, sound=None) -> dict:
    """Append a new cube; any of its EPCs are taken away from other cubes.

    `sound` is an optional audio file (e.g. mp3) played whenever the cube triggers.

    Cubes left with no EPCs are dropped.  Returns the new cube dict.
    """
    new_epcs = []
    for e in epcs:
        e = _norm_epc(e)
        if e and e not in new_epcs:
            new_epcs.append(e)
    wanted = set(new_epcs)

    kept = []
    for cube in data.setdefault("cubes", []):
        moved = [e for e in cube.get("epcs", []) if _norm_epc(e) in wanted]
        if moved:
            for e in moved:
                print(f"note: tag {e} moved from '{cube.get('name')}' to '{name}'")
            cube["epcs"] = [e for e in cube["epcs"] if _norm_epc(e) not in wanted]
            if not cube["epcs"]:
                print(f"note: cube '{cube.get('name')}' has no tags left, removed")
                continue
        kept.append(cube)

    cube = {"name": name,
            "imgD": to_stored_path(img_d),
            "imgU": to_stored_path(img_u),
            "epcs": new_epcs}
    if sound:
        cube["sound"] = to_stored_path(sound)
    kept.append(cube)
    data["cubes"] = kept
    return cube


def remove_cube(data, name) -> bool:
    """Remove every cube with this name; True if any was removed."""
    cubes = data.get("cubes", [])
    kept = [c for c in cubes if c.get("name") != name]
    data["cubes"] = kept
    return len(kept) != len(cubes)


def image_pairs(data) -> list:
    """Distinct (imgD, imgU) pairs in first-seen order."""
    seen = []
    for cube in data.get("cubes", []):
        pair = (cube.get("imgD"), cube.get("imgU"))
        if pair not in seen:
            seen.append(pair)
    return seen


def next_cube_name(data, base="cube") -> str:
    used = {c.get("name") for c in data.get("cubes", [])}
    n = 1
    while f"{base} {n}" in used:
        n += 1
    return f"{base} {n}"


# ---------- config ----------

def load_config() -> dict:
    cfg = _load_json(CONFIG_FILE, {"readers": {}})
    readers = cfg.setdefault("readers", {})
    if not isinstance(readers, dict):
        raise StoreError(f"{CONFIG_FILE}: 'readers' must be an object. "
                         f"It was left untouched.")
    return cfg


def save_config(cfg: dict) -> None:
    _save_json(CONFIG_FILE, cfg)
