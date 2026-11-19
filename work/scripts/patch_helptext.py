"""Patch the Datalinks text files the mod documents itself in.

helpx.txt   -- the engine's REAL cloaking / submarine detection rules. The stock entries say a cloaked unit is only
               found by entering its square. The engine (spot_all 0x5B6260, decompiled + traced 2026-09-18) also
               reveals a hidden stack to a nearby enemy mover that has Deep Radar, that stands in range of one of its
               own sensor arrays inside its own territory, or when the stack holds more than one unit. Rewrites
               #ABILDESC2 (Cloaking Device), #ABILDESC6 (Deep Pressure Hull) and #ABILDESC1 (Deep Radar).
conceptsx.txt -- the Waypoints concept (#CONCEPT16) gains a paragraph on setting waypoints with the Modern Control
               Set (Ctrl+right click), whose right-click move has no drag to press SPACE during.

Usage:  py patch_helptext.py            apply (idempotent)
        py patch_helptext.py --restore  take our text back out
        py patch_helptext.py --check    report only
The installer (install.py) calls patch_folder() on every install / update run and restore_folder() on --uninstall;
both cover the game folder AND Thinker's smac_mod copies (see FOLDERS). A file that is not the stock text is left
alone and reported, never a failure.
Byte-safe: reads/writes bytes, keeps the file's line ending, asserts each stock block before replacing it. Each file
carries its own version marker as a ';' comment line at the very top (both parsers skip ';' lines).

Undo is the EXACT inverse of the patch, never a saved copy: unpatch_bytes() drops the marker line and puts each stock
block back in place of the block that marker's revision wrote (REVISIONS), then proves it by patching the result again
and getting the live bytes back. So whatever replaced the file since (a Thinker or GOG update re-patched by a later
run), uninstall gives back exactly that file's own text. An older marker is undone the same way before re-patching.
A file carrying our marker that does not invert exactly (a block of ours missing or doubled, our marker below the
first line, a revision whose text is not on record) is left alone and reported -- never overwritten.
No backup is written. The <file>.longevity.bak an earlier version kept is never read: it is deleted once the file is
in a state we can undo (or not ours at all), and kept only beside a file we refused, as the one manual way back.
"""
import os, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

HELPX_MARK = b"; longevity-helptext v12"
HELPX_OLD_MARKS = [b"; longevity-helptext v%d" % n for n in range(1, 12)]   # earlier revisions (see REVISIONS)
CONCEPTS_MARK = b"; longevity-concepts v3"
CONCEPTS_OLD_MARKS = [b"; longevity-concepts v1", b"; longevity-concepts v2"]

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

SUBMARINE_LEAD = [
    b"A {Deep Pressure Hull} allows a sea unit to function as a submarine.",
    b"Submarine units are hidden from enemies the same way cloaked units are: they",
    b"are found only by an enemy that tries to enter their square.",
]

DEEP_RADAR_NEW = HELPX_STOCK[b"#ABILDESC1"] + [
    b"^",
    b"^A unit with Deep Radar also detects $LINK<cloaked=80002> and submarine units, but",
    b"only in the squares adjacent to it.",
]

HELPX_NEW = {
    b"#ABILDESC2": HELPX_STOCK[b"#ABILDESC2"] + ZOC_SENTENCE_PLAIN + DETECT,
    b"#ABILDESC6": SUBMARINE_LEAD + ZOC_SENTENCE_LINKED + DETECT,
    b"#ABILDESC1": DEEP_RADAR_NEW,
}

# ---------------------------------------------------------------- older helpx revisions
#: The detection paragraph each older marker wrote, from git history (patch_helptext.py at c34738c = v6, fa287e6 and
#: 6054951 = v7, f96dec3 = v8; test_patch_helptext's TEXT_OF_MARK holds their hashes). The stock blocks and the block
#: layout never changed: #ABILDESC2 = stock + this, #ABILDESC6 = SUBMARINE_LEAD + this, #ABILDESC1 = DEEP_RADAR_NEW.
#: v1-v5 and v9-v11 were working-copy iterations that were never committed -- and never shipped: the installer's
#: text step began at v12 -- so their text is unknown and a file carrying one is left alone (OLD_REVISION).
_DETECT_V6 = [
    b"^",
    b"^A hidden unit is still detected, but only by an enemy unit that moves into",
    b"a square next to it, when:",
    b"^* That enemy unit has {Deep Radar}. (Deep Radar sees ordinary units two",
    b"squares away, but hidden units only in adjacent squares.)",
    b"^* That enemy unit is standing on a sensor array inside its own territory",
    b"(it then counts as having Deep Radar). Being merely in range of a sensor is",
    b"not enough.",
    b"^* The hidden unit shares its square with other units. A stack of more than",
    b"one unit is spotted by any enemy unit that moves next to it, even when every",
    b"unit in the stack is cloaked/submerged.",
    b"^Once spotted, a unit stays visible to that faction until it moves again.",
    b"^",
    b"^Units carried inside a cloaked or submarine transport always count as hidden",
    b"with it. With the Longevity preference {Cloaked Transport Hides Its Cargo}",
    b"(on by default) the transport and its cargo also count as a single unit for",
    b"the stack rule above; two transports in one square still count as two.",
]
_DETECT_V7 = [
    b"^",
    b"^A hidden unit is still detected, but only by an enemy unit that moves into",
    b"a square next to it, when:",
    b"^* That enemy unit has {Deep Radar}. (Deep Radar sees ordinary units two",
    b"squares away, but hidden units only in adjacent squares.)",
    b"^* That enemy unit is standing on a sensor array inside its own territory, or",
    b"within range of one of its bases that has a {Geosynchronous Survey Pod}. It",
    b"then counts as having Deep Radar. Being merely in range of a sensor array is",
    b"not enough.",
    b"^* The hidden unit shares its square with other units. A stack of more than",
    b"one unit is spotted by any enemy unit that moves next to it, even when every",
    b"unit in the stack is cloaked/submerged.",
    b"^Once spotted, a unit stays visible to that faction until it moves again.",
    b"^",
    b"^Units carried inside a cloaked or submarine transport always count as hidden",
    b"with it. With the Longevity preference {Cloaked Transport Hides Its Cargo}",
    b"(on by default) the transport and its cargo also count as a single unit for",
    b"the stack rule above; two transports in one square still count as two.",
]
_DETECT_V8 = _DETECT_V7[:13] + [
    b"^A hidden unit of yours that a faction has not yet detected exerts no zone of",
    b"control over that faction's units; once detected, it does.",
] + _DETECT_V7[13:]


def _helpx_revision(detect: list) -> dict:
    return {
        b"#ABILDESC2": HELPX_STOCK[b"#ABILDESC2"] + detect,
        b"#ABILDESC6": SUBMARINE_LEAD + detect,
        b"#ABILDESC1": DEEP_RADAR_NEW,
    }


#: {marker: the new blocks that revision wrote}, the current one included -- what unpatch_bytes() takes back out.
HELPX_REVISIONS = {
    b"; longevity-helptext v6": _helpx_revision(_DETECT_V6),
    b"; longevity-helptext v7": _helpx_revision(_DETECT_V7),
    b"; longevity-helptext v8": _helpx_revision(_DETECT_V8),
    HELPX_MARK: HELPX_NEW,
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

def _concepts_revision(tab: bytes) -> dict:
    return {
        b"#CONCEPT16": CONCEPTS_STOCK[b"#CONCEPT16"] + [
            b"^",
            b"With the {Modern Control Set} (" + tab + b"), instead place",
            b"waypoints with {CTRL} + {right mouse button}.",
        ],
    }


#: v3: the Preferences tab is "Longevity Preferences" (user 2026-11-17).
CONCEPTS_NEW = _concepts_revision(b"Longevity Preferences")

#: concepts v1 was a working-copy iteration, never committed or shipped (6054951 introduced the file at v2). v2 (shipped
#: in 1.0.0) named the tab "Longevity Mod Preferences".
CONCEPTS_REVISIONS = {
    b"; longevity-concepts v2": _concepts_revision(b"Longevity Mod Preferences"),
    CONCEPTS_MARK: CONCEPTS_NEW,
}

FILES = {
    "helpx.txt": dict(mark=HELPX_MARK, old_marks=HELPX_OLD_MARKS, stock=HELPX_STOCK, new=HELPX_NEW,
                      revisions=HELPX_REVISIONS),
    "conceptsx.txt": dict(mark=CONCEPTS_MARK, old_marks=CONCEPTS_OLD_MARKS, stock=CONCEPTS_STOCK, new=CONCEPTS_NEW,
                          revisions=CONCEPTS_REVISIONS),
}


def _newline(data: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in data else b"\n"


def _block(tag: bytes, lines: list, nl: bytes) -> bytes:
    return tag + nl + nl.join(lines) + nl


def _apply(data: bytes, stock: dict, new: dict, mark: bytes) -> bytes:
    """The patch, for any revision: each stock block swapped for `new`'s, `mark` on top. AssertionError when a stock
    block is not found exactly once."""
    nl = _newline(data)
    out = data
    for tag, lines in stock.items():
        old = _block(tag, lines, nl)
        if out.count(old) != 1:     # a raise, not an assert: PYTHONOPTIMIZE must not switch the check off
            raise AssertionError(f"stock block {tag!r} not found exactly once (foreign file?)")
        out = out.replace(old, _block(tag, new[tag], nl))
    # the marker rides as a comment line at the very top (the parser skips ';' lines)
    return mark + nl + out


def patch_bytes(data: bytes, spec: dict) -> bytes:
    """Return `data` (a PRISTINE file) with every stock block replaced and the marker on top.

    Raises AssertionError when a stock block is not found exactly once (a foreign or already-edited file).
    """
    return _apply(data, spec["stock"], spec["new"], spec["mark"])


#: What the player reads when a file of ours is left alone (the technical reason follows as Refused.detail).
EDITED_WHY = ("it was changed after Longevity Vaccine added its text, so it is left as it is rather than undo that "
              "change")
OLD_REVISION_WHY = "it holds text from an early Longevity Vaccine test build, which this version cannot take out"
NEWER_REVISION_WHY = "it holds text from a newer Longevity Vaccine version, which this one leaves as it is"
#: A file with a sentence of ours but no marker line: usually ours with the marker deleted by hand, but it can also
#: be someone else's file that took up our wording, so the reason claims neither (audit round 5).
UNMARKED_WHY = ("it contains Longevity Vaccine's wording but not its marker line, so the installer cannot tell "
                "which text is its own and leaves it as it is")


class Refused(Exception):
    """unpatch_bytes() cannot take our text back out exactly. `status` says which case (UNPATCHED / EDITED /
    OLD_REVISION / NEWER_REVISION / UNMARKED), `why` is the player's sentence, `detail` the technical reason."""

    def __init__(self, status: str, why: str, detail: str = ""):
        super().__init__(f"{why} ({detail})" if detail else why)
        self.status, self.why, self.detail = status, why, detail


def _marks(spec: dict) -> list:
    return [spec["mark"]] + list(spec["old_marks"])


def marker_of(data: bytes, spec: dict):
    """The marker (any revision) when the file's FIRST line is one, else None. Whole-line compare (v1 is a prefix of
    v12), ignoring surrounding whitespace: a padded marker line is still ours -- unpatch_bytes refuses it as EDITED
    rather than letting it read as a file we never touched."""
    first = data.split(b"\n", 1)[0].strip()
    return first if first in _marks(spec) else None


def _stray_marker(data: bytes, spec: dict) -> bool:
    """One of our markers on a line below the first: someone added lines above it."""
    marks = set(_marks(spec))
    return any(ln.strip() in marks for ln in data.split(b"\n")[1:])


def _newer_marker(data: bytes, spec: dict):
    """The first line when it is a marker of OUR family that this version does not know (a newer build's), else
    None."""
    first = data.split(b"\n", 1)[0].strip()
    family, current = spec["mark"].rsplit(b" v", 1)
    family += b" v"
    n = first[len(family):]
    if not (first.startswith(family) and n.isdigit() and n.isascii() and not n.startswith(b"0")):
        return None
    # a number, not text (v0 / v012 are not newer), compared without int(): a 5000-digit marker must not raise
    # (Python's int() digit limit)
    return first if (len(n), n) > (len(current), current) else None


#: Shorter lines of ours ("detected.", "^", "away.") are too generic to identify our text on their own.
OUR_LINE_MIN = 40


def _our_lines(spec: dict) -> frozenset:
    """Every line one of our revisions added that is a sentence of ours: at least OUR_LINE_MIN bytes once the
    entry's '^' and surrounding blanks are set aside, and found nowhere in the stock text."""
    stock = b"\n".join(ln for lines in spec["stock"].values() for ln in lines)
    out = set()
    for new in spec["revisions"].values():
        for lines in new.values():
            for ln in lines:
                core = ln.strip(b" \t").lstrip(b"^").strip(b" \t")
                if len(core) >= OUR_LINE_MIN and core not in stock:
                    out.add(core)
    return frozenset(out)


def _carries_our_text(data: bytes, spec: dict) -> bool:
    """A sentence one of our revisions wrote (_our_lines) is anywhere in the file -- a whole line, or part of one
    (a blank or a '^' before or after it, or run onto the end of conceptsx.txt's last line, which has no line break:
    audit 2026-11-16, D8: only whole lines were found). A file whose marker is gone still reads as ours after any
    edit that leaves one of our sentences whole (audit 2026-11-10: a marker-less file of ours was patched a second
    time). Every revision's first added sentence is long and ours alone, so a file that merely continues an entry
    the same way -- Thinker's smac_mod\\helpx.txt follows #ABILDESC1/2/6 with '^' and a '^Desc: ...' line of its
    own -- never matches.

    Known trade-offs (audit round 5), both chosen over a wider or narrower net:
    - A marker-less file of ours escapes only when EVERY sentence of ours in it was reworded (conceptsx has two;
      helpx v12 has 19), or reflowed. conceptsx is then patched again and shows our paragraph twice --
      documentation, never newer text overwritten. helpx cannot be: its #ABILDESC6 text does not keep the stock
      block, so the patch finds no stock block and leaves the file alone (FOREIGN). Matching a single word or
      phrase would catch the conceptsx case but risks refusing a foreign file.
    - A file from elsewhere that quotes one of our sentences verbatim, line-wrapped the same way, is refused
      (UNMARKED) on every run instead of patched; every uninstall then ends INCOMPLETE, with advice that covers
      both readings ("nothing needs doing" if another mod or a translation put the text there)."""
    return any(s in data for s in _our_lines(spec))


def unpatch_bytes(data: bytes, spec: dict) -> bytes:
    """The exact inverse of the patch, for every revision on record: the bytes the file had before we patched it.

    Drops the marker line and puts each stock block back in place of the block that marker's revision wrote, then
    checks the result by patching it again: only a file that comes back byte-identical is returned. Raises Refused:
    UNPATCHED (no marker and none of our text), OLD_REVISION (a marker whose text is not on record), EDITED
    (anything else that is ours -- a block missing or doubled, the marker moved, padded or gone with our text still
    there, ...).
    """
    mark = marker_of(data, spec)
    if _stray_marker(data, spec):
        raise Refused(EDITED, EDITED_WHY, "a Longevity marker below the first line")
    if mark is None:
        newer = _newer_marker(data, spec)
        if newer is not None:
            cut = newer.rsplit(b" v", 1)[0] + b" v"                         # a huge number is not echoed in full
            shown = newer if len(newer) - len(cut) <= 40 else newer[:len(cut) + 40] + b"..."
            raise Refused(NEWER_REVISION, NEWER_REVISION_WHY, f"{shown.decode()} is newer than this version")
        if _carries_our_text(data, spec):
            raise Refused(UNMARKED, UNMARKED_WHY, "a sentence of the Longevity text without its marker line")
        raise Refused(UNPATCHED, "not patched")
    new = spec["revisions"].get(mark)
    if new is None:
        raise Refused(OLD_REVISION, OLD_REVISION_WHY, f"{mark.decode()} is not on record")
    nl = _newline(data)
    head = mark + nl
    if not data.startswith(head):
        raise Refused(EDITED, EDITED_WHY, "the marker line was changed")
    body = data[len(head):]
    spans = []
    for tag, lines in new.items():
        blk = _block(tag, lines, nl)
        n = body.count(blk)
        if n != 1:
            raise Refused(EDITED, EDITED_WHY, f"the {tag.decode()} text appears {n} times")
        i = body.index(blk)
        spans.append((i, i + len(blk), tag))
    spans.sort()
    out, pos = [], 0
    for i, j, tag in spans:
        if i < pos:
            raise Refused(EDITED, EDITED_WHY, "the Longevity entries overlap")
        out += [body[pos:i], _block(tag, spec["stock"][tag], nl)]
        pos = j
    out.append(body[pos:])
    pristine = b"".join(out)
    try:
        again = _apply(pristine, spec["stock"], new, mark)
    except AssertionError:
        again = None
    if again != data:
        raise Refused(EDITED, EDITED_WHY, "the text taken out does not patch back to the same bytes")
    if _carries_our_text(pristine, spec):
        # A sentence of ours outside our blocks (a copied line): taking the blocks out would leave it behind and
        # every later run would read the file as unmarked (audit 2026-11-16).
        raise Refused(EDITED, EDITED_WHY, "a sentence of the Longevity text is outside its entries")
    return pristine


def _refused_line(path: pathlib.Path, r: Refused) -> str:
    detail = f" [{r.detail}]" if r.detail else ""
    return f"{path} left alone: {r.why}.{detail}{_kept_backup_note(path)}"


#: Where the game reads these files from: the game folder, and Thinker's `smac_mod\` copies, which Thinker loads
#: instead of the top-level files when its `smac_only` option is on (thinker.ini; config.cpp ModHelpFile). Both are
#: the same stock text with a different header comment, so the same blocks patch both. A folder that is absent, or
#: lacks a file, is skipped.
FOLDERS = ("", "smac_mod")

#: patch_folder() / restore_folder() statuses, one per file found. FOREIGN = no marker of ours and not the stock text
#: (another mod's, a translation). EDITED = our text, but the file does not invert exactly (changed after we patched
#: it). OLD_REVISION = a marker whose text is not on record (see HELPX_REVISIONS). NEWER_REVISION = a marker of a later
#: build than this one (an older installer run over a newer install). UNMARKED = a sentence of ours but no marker
#: line: ours with the marker deleted, or someone else's file quoting our wording -- the two cannot be told apart, so
#: the advice given for it covers both. All five are left alone. FAILED = an OS error on that one file (reported; the
#: other files are still processed).
PATCHED, CURRENT, FOREIGN, EDITED, OLD_REVISION, NEWER_REVISION, UNMARKED, RESTORED, UNPATCHED, FAILED = (
    "patched", "current", "foreign", "edited", "old-revision", "newer-revision", "unmarked", "restored", "unpatched",
    "failed")

#: The statuses of a file we refused to touch although it carries our text.
REFUSED = (EDITED, OLD_REVISION, NEWER_REVISION, UNMARKED)


def backup_of(path: pathlib.Path) -> pathlib.Path:
    """The whole-file copy versions before 2026-11-10 saved beside each patched file. Never read any more."""
    return path.with_name(path.name + ".longevity.bak")


def _drop_backup(path: pathlib.Path) -> str:
    """Delete an earlier version's backup of `path`; returns the note to append ('' when there was none).

    Best effort: a backup that cannot be deleted (read-only, a folder) is said, never a failure of the text file --
    nothing reads it any more."""
    bak = backup_of(path)
    if not os.path.lexists(bak):    # lexists: a dangling link or junction is still ours to remove
        return ""
    try:
        bak.unlink()
    except OSError as e:
        return f" (could not remove {bak.name}, a copy an earlier version kept: {e.strerror or e}; it is not used)"
    return f" (removed {bak.name}, a copy an earlier version kept)"


def _kept_backup_note(path: pathlib.Path) -> str:
    bak = backup_of(path)
    if not bak.exists():
        return ""
    return (f" The copy an earlier version saved before patching it, {bak.name}, is kept beside it; it may be "
            "older than later game or Thinker updates, so it is never put back automatically.")


def patch_file(path: pathlib.Path, spec: dict, check: bool = False) -> str:
    status, text = patch_file_status(path, spec, check)
    return text


def patch_file_status(path: pathlib.Path, spec: dict, check: bool = False) -> tuple:
    """Patch one file in place. Returns (status, human line); never raises for a foreign file.

    An unrecognised file (a stock block missing or duplicated: another mod's text, a translation) is left exactly
    as it is and reported FOREIGN -- the Datalinks text is documentation, never worth refusing an install over. A
    file of ours that does not invert exactly is left alone too (EDITED / OLD_REVISION). An older revision of ours is
    taken back out exactly (unpatch_bytes) and the current text put in. No backup is written; an earlier version's
    .longevity.bak is deleted (kept only beside a file we refused). Nothing is written that unpatch_bytes could not
    take back out exactly.
    """
    data = path.read_bytes()
    note = ""
    try:
        pristine = unpatch_bytes(data, spec)
    except Refused as r:
        if r.status != UNPATCHED:
            return r.status, _refused_line(path, r)
    else:
        mark = marker_of(data, spec)
        if mark == spec["mark"]:
            return CURRENT, f"already patched: {path}{'' if check else _drop_backup(path)}"
        note = f" (replaced the older revision {mark.decode()})"
        data = pristine
    try:
        out = patch_bytes(data, spec)
        if unpatch_bytes(out, spec) != data:
            raise AssertionError("the patched file would not undo exactly")
    except (AssertionError, Refused) as e:
        # not ours and not stock: no claim on it, so an earlier version's copy beside it is stale
        return FOREIGN, f"{path} left alone: not the stock text ({e}).{'' if check else _drop_backup(path)}"
    if check:
        return PATCHED, f"would patch {path} ({len(data)} -> {len(out)} bytes){note}"
    path.write_bytes(out)
    return PATCHED, f"patched {path}{note}{_drop_backup(path)}"


def restore_plan(path: pathlib.Path, spec: dict) -> list:
    """What restore_file_status would read and change, without changing it: [(path, modes)] (preflight.PROBE_MODES
    joined by "+"). The uninstall probes these before its first change. Mirrors restore_file_status; keep the two
    together: the file is read, and written in place (write_bytes) exactly when unpatch_bytes takes our text out,
    backup or none; an earlier version's .longevity.bak is only deleted best effort (_drop_backup never fails the
    restore), so it is not listed."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError:
        # Unreadable (held open without sharing, access denied): the restore would fail on it too. Listed, so the
        # check's probe refuses the run with the real reason before anything changes -- [] let the run start and
        # stop half way (audit of the merge, 2026-11-16).
        return [(path, "read+overwrite")]
    try:
        unpatch_bytes(data, spec)
    except Refused:
        return []
    return [(path, "read+overwrite")]


def restore_file_status(path: pathlib.Path, spec: dict) -> tuple:
    """Take our text back out of the live file, exactly (unpatch_bytes). Returns (status, line).

    RESTORED: the file is now byte-for-byte what it was before we patched it -- whatever replaced it in between.
    UNPATCHED: no marker of ours and none of our wording (stock, or replaced since the last patch run): untouched.
    EDITED / OLD_REVISION / NEWER_REVISION / UNMARKED (REFUSED): left alone. An earlier version's .longevity.bak is
    deleted, except beside a file left alone.
    """
    data = path.read_bytes()
    try:
        out = unpatch_bytes(data, spec)
    except Refused as r:
        if r.status == UNPATCHED:
            return UNPATCHED, f"not patched: {path}{_drop_backup(path)}"
        return r.status, _refused_line(path, r)
    path.write_bytes(out)
    return RESTORED, f"restored {path}{_drop_backup(path)}"


def spec_for(path: pathlib.Path):
    return FILES.get(pathlib.Path(path).name.lower())


def our_original(path: pathlib.Path, spec: dict = None):
    """The bytes `path` had before we patched it when the live file is exactly a patch of ours (unpatch_bytes: the
    inverse, proved by patching it again), else None. Never raises."""
    spec = spec or spec_for(path)
    if spec is None:
        return None
    try:
        return unpatch_bytes(pathlib.Path(path).read_bytes(), spec)
    except (OSError, Refused):
        return None


def is_our_patch(path: pathlib.Path, spec: dict = None) -> bool:
    """Is the live file exactly a patch of ours, which the uninstall takes back out (our_original)? Never raises."""
    return our_original(path, spec) is not None


def refused_status(path: pathlib.Path, spec: dict = None):
    """The REFUSED status (EDITED / OLD_REVISION / NEWER_REVISION / UNMARKED) when the live file holds text of ours
    that unpatch_bytes will not take out -- the uninstall leaves it and names it in its verdict -- else None (ours
    and invertible, not ours at all, unreadable). Never raises."""
    spec = spec or spec_for(path)
    if spec is None:
        return None
    try:
        unpatch_bytes(pathlib.Path(path).read_bytes(), spec)
    except Refused as r:
        return r.status if r.status in REFUSED else None
    except OSError:
        return None
    return None


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
            status, text = FAILED, f"could not patch {path} ({e.strerror or e}), left alone"
        out[rel] = status
        say(text)
    return out


def restore_folder(game_dir, say=print, quiet=()) -> dict:
    """Undo patch_folder(): our text comes back out wherever the live file is ours. Returns {relative name: status}.
    A file whose status is in `quiet` is not said."""
    game_dir = pathlib.Path(game_dir)
    out = {}
    for rel, path, spec in _targets(game_dir):
        try:
            status, text = restore_file_status(path, spec)
        except OSError as e:
            status, text = FAILED, f"could not restore {path} ({e.strerror or e})"
        out[rel] = status
        if status not in quiet:
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
