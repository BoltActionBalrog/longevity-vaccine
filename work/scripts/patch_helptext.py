"""Patch the Datalinks text files the mod documents itself in.

helpx.txt   -- the engine's REAL cloaking / submarine detection rules. The stock entries say a cloaked unit is only
               found by entering its square. The engine (spot_all 0x5B6260, decompiled + traced 2026-09-18) also
               reveals a hidden stack to a nearby enemy mover that has Deep Radar, that stands in range of one of its
               own sensor arrays inside its own territory, or when the stack holds more than one unit. Rewrites
               #ABILDESC2 (Cloaking Device), #ABILDESC6 (Deep Pressure Hull) and #ABILDESC1 (Deep Radar).
conceptsx.txt -- the Waypoints concept (#CONCEPT16) gains a paragraph on setting waypoints with the Modern Control
               Set (Ctrl+right click), whose right-click move has no drag to press SPACE during.

Usage:  py patch_helptext.py            apply (idempotent; the first run saves <file>.longevity.bak)
        py patch_helptext.py --restore  put the backups back
        py patch_helptext.py --check    report only
The installer (install.py) calls patch_folder() on every install / update run and restore_folder() on --uninstall;
both cover the game folder AND Thinker's smac_mod copies (see FOLDERS). A file that is not the stock text is left
alone and reported, never a failure.
Byte-safe: reads/writes bytes, keeps CRLF, asserts each stock block before replacing it. Each file carries its own
version marker as a ';' comment line at the very top (both parsers skip ';' lines); an older marker means the file
is rebuilt from its backup and re-patched.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

HELPX_MARK = b"; longevity-helptext v12"
HELPX_OLD_MARKS = [b"; longevity-helptext v%d" % n for n in range(1, 12)]   # earlier revisions: re-patch from the backup
CONCEPTS_MARK = b"; longevity-concepts v2"
CONCEPTS_OLD_MARKS = [b"; longevity-concepts v1"]

HELPX_STOCK = {
    b"#ABILDESC2": [
        b"A {Cloaking Device} allows a unit to avoid detection by enemy units",
        b"unless they actually attempt to enter the same square. Cloaked units",
        b"may also ignore enemy $LINK<Zones of Control=34>--they may move freely between",
        b"squares adjacent to enemy units.",
    ],
    b"#ABILDESC6": [
        b"A {Deep Pressure Hull} allows a sea unit to function as a submarine.",
        b"Submarine units are difficult for enemies to detect.",
    ],
    b"#ABILDESC1": [
        b"{Deep Radar} allows a unit to spot enemies and terrain up to two squares",
        b"away.",
    ],
}

DETECT = [
    b"^",
    b"^A hidden unit is still detected, but only by an enemy unit that moves into",
    b"a square next to it, when:",
    b"^* That enemy unit has $LINK<Deep Radar=80001>. (Deep Radar sees ordinary units",
    b"two squares away, but hidden units only in adjacent squares.)",
    b"^* That enemy unit is standing on a $LINK<sensor array=90009> inside its own territory, or",
    b"within range of one of its bases that has a",
    b"$LINK<Geosynchronous Survey Pod=100041>. It",
    b"then counts as having Deep Radar. Being merely in range of a sensor array is",
    b"not enough.",
    b"^* The hidden unit shares its square with other units. A stack of more than",
    b"one unit is spotted by any enemy unit that moves next to it, even when every",
    b"unit in the stack is cloaked/submerged.",
    b"^Once spotted, a unit stays visible to that faction until it moves again.",
    b"^",
    b"^Units carried inside a cloaked or submarine transport always count as hidden",
    b"with it. With the Longevity preference {Cloaked Transport Hides Its Cargo}",
    b"the transport and its cargo also count as a single unit for the stack rule",
    b"above. Two transports in one square still count as two.",
]

#: Appended to the FIRST paragraph of both entries (no '^' before it: the same paragraph as the stock text), the
#: user's sentence of 2026-10-30. The stock text links a target once per entry (162 of 164 linking entries, measured
#: 2026-10-30): the Cloaking Device paragraph already links Zones of Control one sentence earlier, so its copy is plain;
#: the Deep Pressure Hull paragraph has no earlier link, so its copy carries it.
ZOC_SENTENCE_PLAIN = [
    b"Human-controlled invisible units exert no Zone of Control until they are",
    b"detected.",
]
ZOC_SENTENCE_LINKED = [
    b"Human-controlled invisible units exert no $LINK<Zone of Control=34> until they",
    b"are detected.",
]

HELPX_NEW = {
    b"#ABILDESC2": HELPX_STOCK[b"#ABILDESC2"] + ZOC_SENTENCE_PLAIN + DETECT,
    b"#ABILDESC6": [
        b"A {Deep Pressure Hull} allows a sea unit to function as a submarine.",
        b"Submarine units are hidden from enemies the same way cloaked units are: they",
        b"are found only by an enemy that tries to enter their square.",
    ] + ZOC_SENTENCE_LINKED + DETECT,
    b"#ABILDESC1": HELPX_STOCK[b"#ABILDESC1"] + [
        b"^",
        b"^A unit with Deep Radar also detects $LINK<cloaked=80002> and submarine units, but",
        b"only in the squares adjacent to it.",
    ],
}

CONCEPTS_STOCK = {
    b"#CONCEPT16": [
        b'{Waypoints} can be set when giving a unit "go to" orders. One way to give a unit',
        b'"go to" orders is to click on it to activate it, then',
        b'hold down the {left mouse button and drag} a "movement arrow"',
        b"to where you want the unit to go. You can set waypoints by pressing the {SPACE BAR}",
        b"while the arrow is over a particular square. The unit will move to each of its",
        b"waypoints on its way to its final destination. You can also set waypoints while",
        b"giving a unit Patrol orders, in similar fashion.",
    ],
}

CONCEPTS_NEW = {
    b"#CONCEPT16": CONCEPTS_STOCK[b"#CONCEPT16"] + [
        b"^",
        b"With the {Modern Control Set} (Longevity Mod Preferences), instead place",
        b"waypoints with {CTRL} + {right mouse button}.",
    ],
}

FILES = {
    "helpx.txt": dict(mark=HELPX_MARK, old_marks=HELPX_OLD_MARKS, stock=HELPX_STOCK, new=HELPX_NEW),
    "conceptsx.txt": dict(mark=CONCEPTS_MARK, old_marks=CONCEPTS_OLD_MARKS, stock=CONCEPTS_STOCK, new=CONCEPTS_NEW),
}


def patch_bytes(data: bytes, spec: dict) -> bytes:
    """Return `data` (a PRISTINE file) with every stock block replaced and the marker on top.

    Raises AssertionError when a stock block is not found exactly once (a foreign or already-edited file).
    """
    nl = b"\r\n" if b"\r\n" in data else b"\n"
    out = data
    for tag, stock in spec["stock"].items():
        old = tag + nl + nl.join(stock) + nl
        assert out.count(old) == 1, f"stock block {tag!r} not found exactly once (foreign file?)"
        new = tag + nl + nl.join(spec["new"][tag]) + nl
        out = out.replace(old, new)
    # the marker rides as a comment line at the very top (the parser skips ';' lines)
    return spec["mark"] + nl + out


#: Where the game reads these files from: the game folder, and Thinker's `smac_mod\` copies, which Thinker loads
#: instead of the top-level files when its `smac_only` option is on (thinker.ini; config.cpp ModHelpFile). Both are
#: the same stock text with a different header comment, so the same blocks patch both. A folder that is absent, or
#: lacks a file, is skipped.
FOLDERS = ("", "smac_mod")

#: patch_folder() / restore_folder() statuses, one per file found. FAILED = an OS error on that one file (reported;
#: the other files are still processed).
PATCHED, CURRENT, FOREIGN, RESTORED, UNPATCHED, NO_BACKUP, FAILED = (
    "patched", "current", "foreign", "restored", "unpatched", "no-backup", "failed")


def backup_of(path: pathlib.Path) -> pathlib.Path:
    return path.with_name(path.name + ".longevity.bak")


def patch_file(path: pathlib.Path, spec: dict, check: bool = False) -> str:
    status, text = patch_file_status(path, spec, check)
    return text


def patch_file_status(path: pathlib.Path, spec: dict, check: bool = False) -> tuple:
    """Patch one file in place. Returns (status, human line); never raises for a foreign file.

    An unrecognised file (a stock block missing or duplicated: another mod's text, a translation) is left exactly
    as it is and reported FOREIGN -- the Datalinks text is documentation, never worth refusing an install over.
    """
    bak = backup_of(path)
    data = path.read_bytes()
    if data.startswith(spec["mark"]):
        return CURRENT, f"already patched: {path}"
    note = ""
    if any(data.startswith(m) for m in spec["old_marks"]):
        if not bak.exists():
            return FOREIGN, f"older patch present in {path} but no {bak.name} to rebuild from -- left alone"
        data = bak.read_bytes()
        note = f" (older revision found: rebuilt from {bak.name})"
    try:
        out = patch_bytes(data, spec)
    except AssertionError as e:
        return FOREIGN, f"not the stock text ({e}): {path} -- left alone"
    if check:
        return PATCHED, f"would patch {path} ({len(data)} -> {len(out)} bytes){note}"
    if not bak.exists():
        bak.write_bytes(data)       # `data` is pristine here (an older revision was rebuilt from the backup)
    path.write_bytes(out)
    return PATCHED, f"patched {path} backup: {bak.name}{note}"


def restore_file_status(path: pathlib.Path, spec: dict) -> tuple:
    """Put the backup back when the live file carries our marker (any revision). Returns (status, line)."""
    bak = backup_of(path)
    data = path.read_bytes()
    ours = data.startswith(spec["mark"]) or any(data.startswith(m) for m in spec["old_marks"])
    if not ours:
        return UNPATCHED, f"not patched: {path}"
    if not bak.exists():
        return NO_BACKUP, f"patched but no {bak.name} to restore from: {path} -- left alone"
    path.write_bytes(bak.read_bytes())
    bak.unlink()
    return RESTORED, f"restored {path} from {bak.name}"


def _targets(game_dir: pathlib.Path):
    """Every (relative name, path, spec) present under the game folder, top level first."""
    for folder in FOLDERS:
        base = game_dir / folder if folder else game_dir
        for name, spec in FILES.items():
            path = base / name
            if path.is_file():
                yield (f"{folder}\\{name}" if folder else name), path, spec


def patch_folder(game_dir, check: bool = False, say=print) -> dict:
    """Patch every Datalinks text file the game folder holds (see FOLDERS). Returns {relative name: status}."""
    game_dir = pathlib.Path(game_dir)
    out = {}
    for rel, path, spec in _targets(game_dir):
        try:
            status, text = patch_file_status(path, spec, check)
        except OSError as e:
            status, text = FAILED, f"could not patch {path} ({e}) -- left alone"
        out[rel] = status
        say(text)
    return out


def restore_folder(game_dir, say=print) -> dict:
    """Undo patch_folder(): the backups go back wherever the live file is ours. Returns {relative name: status}."""
    game_dir = pathlib.Path(game_dir)
    out = {}
    for rel, path, spec in _targets(game_dir):
        try:
            status, text = restore_file_status(path, spec)
        except OSError as e:
            status, text = FAILED, f"could not restore {path} ({e})"
        out[rel] = status
        say(text)
    return out


def main() -> int:
    import config
    game = pathlib.Path(config.game_dir())
    if "--restore" in sys.argv:
        res = restore_folder(game)
        return 0 if res and all(s in (RESTORED, UNPATCHED) for s in res.values()) else 1
    res = patch_folder(game, check="--check" in sys.argv)
    if not res:
        print("no Datalinks text files found in", game)
        return 1
    return 0 if all(s in (PATCHED, CURRENT) for s in res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
