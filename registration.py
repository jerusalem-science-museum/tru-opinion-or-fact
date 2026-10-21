"""
Terminal-driven setup flows for the exhibit.

assign_reader_roles(readers, cfg, q) -> {reader_id: "D" | "U"}
    Startup: map each connected reader to its role, asking only when needed.
register_cubes(root, data, q) -> number of cubes added
    Triggered by typing new<Enter> on the exhibit window.

Both use plain input()/print(); tags are detected with readers.wait_for_tag().
"""
import sys
from tkinter import filedialog

from readers import wait_for_tag
from store import (DATA_DIR, add_cube, epc_index, image_pairs, next_cube_name,
                   resolve_path, save_config, save_tags)

ROLES = ("D", "U")
ROLE_NAMES = {"D": "D (דעה, opinion)", "U": "U (עובדה, fact)"}
try:    # e.g. stdout redirected on Windows (cp1252) can't print Hebrew
    "".join(ROLE_NAMES.values()).encode(sys.stdout.encoding or "ascii")
except (UnicodeEncodeError, LookupError, AttributeError):
    ROLE_NAMES = {"D": "D (de'a, opinion)", "U": "U (uvda, fact)"}
DEFAULT_EXTRA_TAGS = 5      # a cube has 6 faces: first tag + 5 more
MAX_EXTRA_TAGS = 50
IMAGE_TYPES = [("Images", "*.jpg *.jpeg *.png *.gif *.bmp"), ("All files", "*.*")]
SOUND_TYPES = [("Audio", "*.mp3 *.wav *.ogg"), ("All files", "*.*")]


def _wait_tag(q, **kw):
    """wait_for_tag in short slices so Ctrl+C works on Windows too."""
    while True:
        hit = wait_for_tag(q, timeout=0.5, **kw)
        if hit:
            return hit


def _norm(epc):
    return "".join(str(epc).split()).upper()


def _yes(prompt, default=False):
    ans = input(prompt).strip().lower()
    return default if not ans else ans in ("y", "yes")


# ---------------------------------------------------------------- reader roles

def _ask_role(prompt):
    while True:
        ans = input(prompt).strip().upper()
        if ans in ROLES:
            return ans
        print("  Please type D or U.")


def _pick_reader(q, readers, what):
    """Return the reader the operator means: typed number, or Enter + tag."""
    by_id = {r.id: r for r in readers}
    numbers = ", ".join(str(i) for i in range(1, len(readers) + 1))
    while True:
        ans = input(f"{what}: type its number ({numbers}), "
                    f"or press Enter and hold a tag near it: ").strip()
        if not ans:
            print("  Waiting for a tag...")
            reader_id, _epc = _wait_tag(q, reader_ids=set(by_id))
            r = by_id[reader_id]
            print(f"  -> {r.port}  ({r.id})")
            return r
        if ans.isdigit() and 1 <= int(ans) <= len(readers):
            return readers[int(ans) - 1]
        print("  Not a valid number.")


def _list_readers(readers):
    for i, r in enumerate(readers, 1):
        print(f"  {i}) {r.port}  id={r.id}  {r.hw_info}")


def _run_role_setup(q, readers):
    if len(readers) == 1:
        print("WARNING: only one reader connected - only one role will work.")
        return {readers[0].id: _ask_role("Is this reader D (opinion) or U (fact)? [D/U]: ")}

    if len(readers) == 2:
        d = _pick_reader(q, readers, f"Which reader is {ROLE_NAMES['D']}")
        return {r.id: ("D" if r is d else "U") for r in readers}

    # More than two: assign each one; both roles must end up used.
    while True:
        roles = {}
        while len(roles) < len(readers):
            left = [r for r in readers if r.id not in roles]
            print("Not assigned yet:")
            _list_readers(left)
            r = left[0] if len(left) == 1 else _pick_reader(q, left, "Pick a reader")
            roles[r.id] = _ask_role(f"Role for {r.port}? [D/U]: ")
        if set(roles.values()) == set(ROLES):
            return roles
        print("Both D and U need at least one reader - let's start again.")


def assign_reader_roles(readers, cfg, q):
    """Return {reader_id: "D"|"U"} for the connected readers.

    Uses cfg["readers"] when it already covers them; otherwise asks in the
    terminal and saves via save_config (entries of unplugged readers are kept).
    """
    saved = cfg.setdefault("readers", {})
    if not readers:
        print("WARNING: no readers connected.")
        return {}

    roles = {r.id: saved.get(r.id) for r in readers}
    known = all(v in ROLES for v in roles.values())
    if known and (len(readers) == 1 or set(roles.values()) == set(ROLES)):
        if len(readers) == 1:
            print(f"WARNING: only one reader connected ({ROLE_NAMES[roles[readers[0].id]]}) "
                  f"- the other role won't work.")
        return roles

    print("\n=== Reader setup ===")
    print("Connected readers:")
    _list_readers(readers)
    roles = _run_role_setup(q, readers)

    saved.update(roles)
    save_config(cfg)
    for r in readers:
        print(f"  {r.port}: {ROLE_NAMES[roles[r.id]]}")
    print("Reader roles saved.\n")
    return roles


# ---------------------------------------------------------------- cubes

def _ask_name(data):
    taken = {c.get("name") for c in data.get("cubes", [])}
    default = next_cube_name(data)
    while True:
        name = input(f"Cube name [{default}]: ").strip() or default
        if name not in taken:
            return name
        print(f"  '{name}' is already used - pick another name.")


def _note_owner(data, epc):
    cube = epc_index(data).get(_norm(epc))
    if cube is not None:
        print(f"  (this tag belongs to '{cube.get('name')}' - it will be moved to the new cube)")


def _sound_for_pair(data, d, u):
    """Sound of the first cube using this image pair, if any."""
    for c in data.get("cubes", []):
        if (c.get("imgD"), c.get("imgU")) == (d, u) and c.get("sound"):
            return c["sound"]
    return None


def _choose_media(root, data):
    """Return (img_d, img_u, sound_or_None), or None if the operator cancelled."""
    pairs = image_pairs(data)
    if pairs:
        print("Existing image pairs (reuse one for a replacement cube):")
        for i, (d, u) in enumerate(pairs, 1):
            sound = _sound_for_pair(data, d, u)
            print(f"  {i}) D: {d}   U: {u}" + (f"   sound: {sound}" if sound else ""))
        while True:
            ans = input("Type a number to reuse it, or press Enter to choose files: ").strip()
            if not ans:
                break
            if ans.isdigit() and 1 <= int(ans) <= len(pairs):
                d, u = pairs[int(ans) - 1]
                sound = _sound_for_pair(data, d, u)
                return (str(resolve_path(d)), str(resolve_path(u)),
                        str(resolve_path(sound)) if sound else None)
            print("  Not a valid number.")

    paths = []
    for role in ROLES:
        print(f"Choose the {ROLE_NAMES[role]} image in the file dialog...")
        path = filedialog.askopenfilename(
            parent=root, title=f"Choose the {ROLE_NAMES[role]} image",
            initialdir=str(DATA_DIR), filetypes=IMAGE_TYPES)
        if not path:
            return None
        print(f"  {role}: {path}")
        paths.append(path)

    print("Choose a sound (mp3) for this cube, or Cancel for none...")
    sound = filedialog.askopenfilename(
        parent=root, title="Choose the cube's sound (Cancel = no sound)",
        initialdir=str(DATA_DIR), filetypes=SOUND_TYPES)
    print(f"  sound: {sound or '(none)'}")
    return paths[0], paths[1], sound or None


def _ask_extra_count():
    while True:
        ans = input(f"How many more tags for this cube? [{DEFAULT_EXTRA_TAGS}] (0 = none): ").strip()
        if not ans:
            return DEFAULT_EXTRA_TAGS
        if ans.isdigit() and int(ans) <= MAX_EXTRA_TAGS:
            return int(ans)
        print(f"  Please type a number from 0 to {MAX_EXTRA_TAGS}.")


def _register_one(root, data, q):
    """Run the flow for one cube. Returns the new cube, or None if cancelled."""
    name = _ask_name(data)

    print("Hold the first tag of this cube near a reader...")
    _reader, epc = _wait_tag(q)
    epcs = [_norm(epc)]
    print(f"  tag 1: {epcs[0]}")
    _note_owner(data, epcs[0])

    media = _choose_media(root, data)
    if media is None:
        print("Cancelled - this cube was not added.")
        return None
    img_d, img_u, sound = media

    extra = _ask_extra_count()
    total = 1 + extra
    for n in range(2, total + 1):
        print(f"Move the previous tag away, then hold tag {n}/{total} near a reader...")
        _reader, epc = _wait_tag(q, ignore=set(epcs))
        epc = _norm(epc)
        if epc in epcs:     # same tag, just formatted differently
            continue
        epcs.append(epc)
        print(f"  tag {n}/{total}: {epc}")
        _note_owner(data, epc)

    cube = add_cube(data, name, img_d, img_u, epcs, sound)
    print(f"Cube '{name}' added with {len(epcs)} tag(s).")
    return cube


def register_cubes(root, data, q):
    """Register cubes in the terminal; saves tags once at the end.

    Ctrl+C keeps (and saves) the finished cubes and drops the one in progress.
    Returns the number of cubes added.
    """
    print("\n=== Register new cube ===  (Ctrl+C to stop)")
    added = 0
    try:
        while True:
            if _register_one(root, data, q) is not None:
                added += 1
            if not _yes("Register another cube? [y/N]: "):
                break
            print()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped - the unfinished cube was discarded.")
    if added:
        save_tags(data)
        print(f"Saved {added} new cube(s).")
    else:
        print("Nothing new to save.")
    return added
