"""What Thinker Mod a game folder has, and how to name it to the player.

Detection asks two questions only (user rulings, 2026-11-13): is a thinker.dll present, and is it
the pinned build (its sha256 equals the pin's). Any other build is OFF-PIN and is offered the
replacement; its own label (MOD_VERSION) is read for WORDING only.

The label grammar is the DLL's (src/uimod/src/thinkercheck_core.h, ParseLabel), and the names are
the shared {RUN} / {YOURS} grammar (design section 4.0; fixture tests/thinker_labels.json):
  "Thinker Mod v<d>(.<d>)*" with nothing alphanumeric straight after  -> a plain version
  "Thinker Mod develop build"                                          -> a development build
  anything else                                                        -> unrecognised
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

NONE, PIN, OFF_PIN = "none", "pin", "off-pin"
VERSION, DEVELOP, UNRECOGNISED = "version", "develop", "unrecognised"
UP, DOWN, OTHER = "up", "down", "other"

_MAX_PARTS = 4
_KVER = b"Thinker Mod v"
_KDEV = b"Thinker Mod develop build"


@dataclass(frozen=True)
class Label:
    kind: str = UNRECOGNISED
    version: str = ""                          # "5.6" for a plain version
    parts: tuple = field(default_factory=tuple)


def _dotted(s: bytes):
    """(parts, consumed) for "<d>(.<d>)*" at the start of s, or None (ParseDotted)."""
    i, parts = 0, []
    while True:
        if len(parts) == _MAX_PARTS:
            return None
        d = 0
        v = 0
        while i < len(s) and 0x30 <= s[i] <= 0x39:
            d += 1
            if d > 5:
                return None
            v = v * 10 + s[i] - 0x30
            i += 1
        if d == 0:
            return None
        parts.append(v)
        if i + 1 < len(s) and s[i:i + 1] == b"." and 0x30 <= s[i + 1] <= 0x39:
            i += 1
            continue
        break
    if i >= 24:
        return None
    return tuple(parts), i


def parse_label(s) -> Label:
    """ParseLabel, for a string without its terminator (bytes or str)."""
    if isinstance(s, str):
        s = s.encode("latin-1", "replace")
    if s == _KDEV:
        return Label(DEVELOP)
    if len(s) > len(_KVER) and s.startswith(_KVER):
        rest = s[len(_KVER):]
        got = _dotted(rest)
        if got:
            parts, used = got
            nxt = rest[used:used + 1]
            if not (nxt.isalnum() and nxt.isascii()):
                return Label(VERSION, rest[:used].decode("ascii"), parts)
    return Label(UNRECOGNISED)


def parse_version(s: str) -> Label:
    """A dotted version string ("5.5", "1.0.0") as a Label (ParseVersionString)."""
    b = (s or "").encode("ascii", "replace")
    got = _dotted(b)
    if got and got[1] == len(b) and b:
        return Label(VERSION, s, got[0])
    return Label(UNRECOGNISED)


def compare(a: Label, b: Label) -> int:
    """-1 / 0 / +1 for two plain versions; missing parts count as 0 ("5.5" == "5.5.0")."""
    for k in range(_MAX_PARTS):
        x = a.parts[k] if k < len(a.parts) else 0
        y = b.parts[k] if k < len(b.parts) else 0
        if x != y:
            return -1 if x < y else 1
    return 0


def same_number(label: Label, ts: str) -> bool:
    t = parse_version(ts)
    return label.kind == VERSION and t.kind == VERSION and compare(label, t) == 0


def run_name(label: Label, against: str = None) -> str:
    """{RUN}: the folder's build in running text, compared with `against` (the pin), if given."""
    if label.kind == DEVELOP:
        return "a development build of Thinker Mod"
    if label.kind != VERSION:
        return "an unrecognised build of Thinker Mod"
    if against and same_number(label, against):
        return f"a different build of Thinker Mod {label.version}"
    return f"Thinker Mod {label.version}"


def yours(label: Label, against: str = None, capital: bool = False) -> str:
    """{YOURS}: the same build in a possessive slot."""
    r = run_name(label, against)
    if r.startswith("a "):
        r = r[2:]
    elif r.startswith("an "):
        r = r[3:]
    s = "your " + r
    return s[0].upper() + s[1:] if capital else s


def direction(label: Label, pin: str, pin_is_dev: bool = False) -> str:
    """UP / DOWN / OTHER from the label against the target pin (section 4.0)."""
    if pin_is_dev or label.kind != VERSION:
        return OTHER
    t = parse_version(pin)
    if t.kind != VERSION:
        return OTHER
    c = compare(label, t)
    return UP if c < 0 else DOWN if c > 0 else OTHER


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def ts_display(pin_id: str) -> str:
    """{TS}: "5.6" for a release pin ("5.6.0" -> "5.6", as Thinker writes it), "rel. Nov 9 2025" for a
    development-build pin "dev-20251109" (user ruling 2026-11-14)."""
    m = re.fullmatch(r"dev-(\d{4})(\d{2})(\d{2})", pin_id or "")
    if m:
        try:
            d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return pin_id                       # an impossible date: shown as recorded, never a crash
        return f"rel. {_MONTHS[d.month - 1]} {d.day} {d.year}"
    parts = (pin_id or "").split(".")
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


# ---------------------------------------------------------------- the folder's thinker.dll

@dataclass(frozen=True)
class Dll:
    sha256: str
    stamp: int                     # PE TimeDateStamp, or None when unreadable
    image_size: int                # PE SizeOfImage, or None
    label: Label


def _pe_header(data: bytes):
    if data[:2] != b"MZ":
        return None, None
    pe = int.from_bytes(data[0x3C:0x40], "little")
    if data[pe:pe + 4] != b"PE\0\0" or len(data) < pe + 0x54:
        return None, None
    return (int.from_bytes(data[pe + 8:pe + 12], "little"),
            int.from_bytes(data[pe + 0x50:pe + 0x54], "little"))


def dll_label(data: bytes) -> Label:
    """The dll's own label: every NUL-terminated "Thinker Mod v..." / "Thinker Mod develop build"
    string in the file must agree (5.5 holds four identical copies); disagreement is unrecognised."""
    found = set()
    for m in re.finditer(rb"Thinker Mod [^\x00]{0,40}\x00", data):
        lab = parse_label(m.group()[:-1])
        if lab.kind != UNRECOGNISED:
            found.add(lab)
    return found.pop() if len(found) == 1 else Label(UNRECOGNISED)


class DllUnreadable(OSError):
    """thinker.dll is there but cannot be read: another program holds it with no sharing (audit-m #7). `path` names it;
    callers say "<file> is in use by another program" (thinker_flow.in_use), never crash."""

    def __init__(self, path: Path):
        super().__init__(f"{Path(path).name} cannot be read")
        self.path = Path(path)


def read_dll(path: Path):
    """Dll for `path`, or None when there is no file. Raises DllUnreadable when it is there and cannot be read."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = p.read_bytes()
    except OSError as e:
        raise DllUnreadable(p) from e
    stamp, size = _pe_header(data)
    return Dll(hashlib.sha256(data).hexdigest(), stamp, size, dll_label(data))


def classify(game_dir: Path, pin_sha256: str):
    """(state, Dll or None): NONE, PIN or OFF_PIN for the folder's thinker.dll against the pin."""
    dll = read_dll(Path(game_dir) / "thinker.dll")
    if dll is None:
        return NONE, None
    return (PIN if dll.sha256 == pin_sha256.lower() else OFF_PIN), dll


def header_matches(dll: Dll, stamp: int, image_size: int) -> bool:
    """The GAME's own test (PE stamp + size): what the startup box will see. Used for every line
    that promises what the game will do at start (the promise rule, section 4.0)."""
    return dll is not None and dll.stamp == stamp and dll.image_size == image_size
