"""What is installed, recorded on the player's disk.

Before this the product had NO install identity: `install.py` wrote no receipt, and "already
patched" was decided by hashing the `.bak`, so a player on an old patch set was indistinguishable
from one on the newest and a normal re-run could never refresh them.

TWO STORES, deliberately (the user's choice):

  * `Alpha Centauri.ini` `[Longevity]` -- the few values the DLL needs at startup. The engine side
    already speaks the Win32 profile API for the `[UIMod]` keys, so reading these costs the DLL
    nothing and needs no JSON parser on the C++ side.
  * `longevity-install.json` beside the exe -- the richer record only the installer needs:
    per-module version, sha256 and file list, which is what makes an incremental install possible
    (skip the unchanged clips instead of recopying 1.3 GB).

Everything here is defensive. A missing, truncated, hand-edited or foreign-encoded receipt must
degrade to "I do not know what is installed" and let the installer proceed, never crash: the
receipt is a convenience, and the authoritative facts are always the bytes on disk.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import version as ver  # noqa: E402

JSON_NAME = "longevity-install.json"
INI_NAME = "Alpha Centauri.ini"
INI_SECTION = "Longevity"

#: [Longevity] ini keys. Flat scalars only -- the DLL reads them with GetPrivateProfileInt/String.
KEY_TARGET = "TargetId"
KEY_LAST_CHECK = "LastUpdateCheck"
#: Per ITEM and version: `base:0.2.0;movies-hd:0.2.0;new:portraits-hd:0.2.0`. A declined item is
#: not offered again until ITS version changes, so declining a pack update never hides the next
#: base release. The game writes it (WritePrivateProfileStringW) on "no"; --check reads it.
KEY_DECLINED = "DeclinedUpdates"
KEY_AUTO_UPDATE = "AutoUpdate"
#: Per-module version keys, e.g. base -> BaseVersion.
MODULE_KEYS = {"base": "BaseVersion", "movies-hd": "MoviesHdVersion",
               "portraits-hd": "PortraitsHdVersion"}


#: Room for any value we store, plus a hand-edited one. Counted in characters (wide API).
_INI_BUF = 1024


def _ini_path(game_dir: Path) -> str:
    # RESOLVE. The Win32 profile API treats a bare or relative name as relative to %WINDIR%, so
    # `--game-dir .` collapsed this to "Alpha Centauri.ini" and every [Longevity] read, write and
    # delete targeted C:\Windows\Alpha Centauri.ini -- silently failing unelevated, and SUCCEEDING
    # elevated, which is exactly what the preflight tells the user to do when a write fails.
    try:
        return str(Path(game_dir).resolve() / INI_NAME)
    except OSError:
        return str(Path(game_dir) / INI_NAME)


def _k32():
    try:
        return ctypes.windll.kernel32
    except (AttributeError, OSError):
        return None


def ini_get(game_dir: Path, key: str, default: str = "") -> str:
    """One [Longevity] value. Never raises.

    WIDE entry points deliberately: the ANSI ones take an mbcs-encoded path, and encoding it with
    `errors="replace"` turns an unencodable character into `?` -- a different, valid path. An
    install under a Cyrillic, CJK or accented folder name would have read and written someone
    else's file, silently and with a success return.
    """
    k = _k32()
    if k is None:
        return default
    try:
        buf = ctypes.create_unicode_buffer(_INI_BUF)
        n = k.GetPrivateProfileStringW(INI_SECTION, key, default, buf, _INI_BUF,
                                       _ini_path(game_dir))
        return buf[:n]
    except (OSError, AttributeError, ValueError):
        return default


def ini_set(game_dir: Path, key: str, value: str) -> bool:
    k = _k32()
    if k is None:
        return False
    # A newline in a value writes EXTRA KEYS into [Longevity]: `ini_set(g, "TargetId",
    # "a\nFoo=bar")` lands a `Foo=bar` line of its own. Nothing reachable supplies one today
    # (ids come from patches.yaml, versions are validated), but an unguarded injection point in
    # the one file the DLL reads at startup is not worth keeping.
    if any(c in str(value) for c in "\r\n\x00"):
        return False
    try:
        return bool(k.WritePrivateProfileStringW(
            INI_SECTION, key, str(value), _ini_path(game_dir)))
    except (OSError, AttributeError, ValueError):
        return False


def read(game_dir: Path) -> dict:
    """The installed state. Always returns a usable dict, never raises."""
    game_dir = Path(game_dir)
    out = {"modules": {}, "target_id": None, "source": "none"}

    p = game_dir / JSON_NAME
    if p.is_file():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                mods = doc.get("modules")
                if isinstance(mods, dict):
                    out["modules"] = {k: v for k, v in mods.items() if isinstance(v, dict)}
                if isinstance(doc.get("target_id"), str):
                    out["target_id"] = doc["target_id"]
                out["source"] = "json"
        except (ValueError, OSError, UnicodeDecodeError):
            # A corrupt receipt is not a reason to refuse to install; fall through to the ini.
            out["source"] = "corrupt-json"

    # The ini is the fallback AND the cross-check: the DLL only ever sees these.
    if not out["target_id"]:
        t = ini_get(game_dir, KEY_TARGET)
        out["target_id"] = t or None
    for name, key in MODULE_KEYS.items():
        v = ini_get(game_dir, key)
        have = out["modules"].get(name)
        json_ok = isinstance(have, dict) and isinstance(have.get("version"), str) \
            and ver.is_valid(have["version"])
        # The ini is consulted when the JSON has no usable version for the module -- not only
        # when it has no entry. And an unreadable ini value still marks the module as PRESENT:
        # its files are on disk, and module_version() reads it as UNKNOWN, which decide() treats
        # as "offer the update". Dropping it made an installed pack "not installed".
        if v and not json_ok:
            out["modules"][name] = {"version": ver.normalise(v) if ver.is_valid(v) else v}
            if out["source"] == "none":
                out["source"] = "ini"
    return out


def module_version(state: dict, name: str) -> str:
    v = (state.get("modules") or {}).get(name, {}).get("version")
    return ver.normalise(v) if isinstance(v, str) and ver.is_valid(v) else ver.UNKNOWN


def installed_modules(state: dict) -> list:
    """Every module the receipt has an entry for -- INCLUDING one whose version is unreadable.

    Filtering those out (the old rule: `module_version != UNKNOWN`) made a pack with a corrupt or
    "0.0.0" version vanish from the installed list: its files were on disk, yet the player was
    told it was "available but not installed" and --check reported it as new. An unreadable
    version now reads as UNKNOWN, which decide() treats as "offer the update" -- the honest
    answer, and the same one the base gets.
    """
    return sorted(n for n, info in (state.get("modules") or {}).items()
                  if isinstance(n, str) and isinstance(info, dict))


def write(game_dir: Path, *, target_id: str = None, modules: dict = None,
          say=print) -> bool:
    """Record the install. Returns False on failure but never raises -- a receipt we could not
    write must not undo a successful install, it just means the next run knows less."""
    game_dir = Path(game_dir)
    # Every caller is ours, but this is the LAST step of a successful install: a bad argument
    # here must degrade to a thinner receipt, never raise. An AttributeError from `.items()` on a
    # non-dict, or a TypeError from json.dumps on an unserialisable value, would have escaped
    # into the crash handler AFTER the exe was already patched -- telling the player their
    # finished install was an installer bug.
    modules = modules if isinstance(modules, dict) else {}
    modules = {str(n): (i if isinstance(i, dict) else {}) for n, i in modules.items()}
    target_id = target_id if isinstance(target_id, str) and target_id else None
    ok = True

    doc = {
        "schema": 1,
        "product": "longevity-vaccine",
        "target_id": target_id,
        "installed_at": int(time.time()),
        "modules": modules,
    }
    try:
        tmp = game_dir / (JSON_NAME + ".tmp")
        try:
            body = json.dumps(doc, indent=2)
        except (TypeError, ValueError):
            doc["modules"] = {n: {"version": i.get("version")} for n, i in modules.items()}
            body = json.dumps(doc, indent=2, default=str)
        tmp.write_text(body + "\n", encoding="utf-8")
        tmp.replace(game_dir / JSON_NAME)
    except (OSError, TypeError, ValueError) as e:
        say(f"  WARNING: could not write {JSON_NAME}: {e}")
        ok = False

    if target_id and not ini_set(game_dir, KEY_TARGET, target_id):
        ok = False
    for name, info in modules.items():
        key = MODULE_KEYS.get(name)
        v = info.get("version")
        if key and isinstance(v, str) and ver.is_valid(v):
            if not ini_set(game_dir, key, ver.normalise(v)):
                ok = False
    if not ok:
        say("  WARNING: the install receipt is incomplete; the next update may re-do more work "
            "than necessary.")
    return ok


def note_check(game_dir: Path, when: int = None) -> None:
    ini_set(game_dir, KEY_LAST_CHECK, str(int(when if when is not None else time.time())))


#: Characters an item name may not contain: the entry separator, the ini's own syntax, and what
#: ini_set refuses anyway. `:` is allowed -- `new:<id>` is an item -- because the version is
#: split off with rpartition, so any number of colons before it are the item.
_DECLINE_FORBIDDEN = ";=\r\n\x00[]"

#: The "any version" decline: `<item>:*` hides that item at every offered version UNTIL THE NEXT
#: UNDECLINED RELEASE FOR SOMETHING INSTALLED -- the game's "Don't ask me again" on a NEW pack's
#: offer (`new:<id>:*`). On an UPDATE offer the game writes `<item>:<offered version>` instead
#: (since 2026-10-31). Either kind is void while the base or an installed pack has an offer the
#: player has not declined: the user's rule, "a decline of any pack is reset when any new update
#: releases for a module that is already installed" (install.check_report applies it). And while
#: the BASE offer stays declined, new packs are not offered either (any update brings a stale core
#: along); a declined stale pack hides only itself.
#: `manual-<reason>:*` on the manual-install notice keeps its own meaning: silenced for THAT
#: reason, for good.
DECLINE_ANY = "*"

#: Longest item the DLL's fixed-buffer reader keeps (update_core.h Declines::E::item[64]).
#: Both sides refuse / drop longer ones so a rewrite by either never erases the other's entry.
_DECLINE_ITEM_MAX = 63

#: The whitespace both sides strip around an entry -- str.strip() with no argument would also
#: eat \x0b, \xa0 or 　, which the DLL's reader does not.
_DECLINE_WS = " \t\r\n"


def manual_decline_item(reason) -> str:
    """The DeclinedUpdates item for the manual-install notice with `reason` (a manifest.REASONS
    key or empty/None). Keyed by reason: a different kill switch later is a different notice."""
    return "manual-" + (reason if isinstance(reason, str) and reason else "unspecified")


def declined(game_dir: Path) -> dict:
    """item -> the version the player declined, or DECLINE_ANY. Malformed entries are dropped,
    never raised."""
    raw = ini_get(game_dir, KEY_DECLINED)
    parts = raw.split(";")
    if len(raw) >= _INI_BUF - 1:
        # The profile API truncated the value. The last entry may be cut mid-version
        # ("base:9.9.99" read as "base:9.9.9" would suppress a real offer): drop it.
        parts = parts[:-1]
    out = {}
    for part in parts:
        item, sep, v = part.strip(_DECLINE_WS).rpartition(":")
        item = item.strip(_DECLINE_WS)
        v = v.strip(_DECLINE_WS)
        if not sep or not item or len(item) > _DECLINE_ITEM_MAX:
            continue
        if v == DECLINE_ANY:
            out[item] = DECLINE_ANY
        elif ver.is_valid(v):
            out[item] = ver.normalise(v)
    return out


def is_declined(declined: dict, item: str, offered: str) -> bool:
    """True when `item` must be omitted from the game's offer at `offered` (a normalised
    version): declined at exactly that version, or at any version (DECLINE_ANY)."""
    v = declined.get(item) if isinstance(declined, dict) else None
    return v == DECLINE_ANY or (v is not None and v == offered)


def decline(game_dir: Path, item: str, version: str) -> bool:
    """Remember "no" for one item at one version (or DECLINE_ANY for every version).
    Items: `base`, a module id, `new:<id>`, or `manual`."""
    item = item.strip(_DECLINE_WS) if isinstance(item, str) else ""
    if not item or len(item) > _DECLINE_ITEM_MAX or any(c in item for c in _DECLINE_FORBIDDEN) \
            or any(not (32 < ord(c) < 127) for c in item):
        return False        # never True for something declined() could not read back
    if isinstance(version, str) and version.strip(_DECLINE_WS) == DECLINE_ANY:
        version = DECLINE_ANY
    elif ver.is_valid(version):
        version = ver.normalise(version)
    else:
        return False
    d = declined(game_dir)
    d[item] = version
    value = ";".join(f"{k}:{v}" for k, v in sorted(d.items()))
    if len(value) >= _INI_BUF - 1:
        return False        # would read back truncated (declined() drops the cut last entry)
    return ini_set(game_dir, KEY_DECLINED, value)


def clear_declines(game_dir: Path) -> bool:
    """Forget every decline (the game's "Reset Skipped Updates")."""
    return ini_set(game_dir, KEY_DECLINED, "")


def clear(game_dir: Path, say=print) -> None:
    """Remove the receipt (uninstall). Leaves the [UIMod] settings alone -- they are the player's
    preferences, not our bookkeeping."""
    game_dir = Path(game_dir)
    try:
        (game_dir / JSON_NAME).unlink(missing_ok=True)
    except OSError as e:
        say(f"  WARNING: could not remove {JSON_NAME}: {e}")
    k = _k32()
    for key in list(MODULE_KEYS.values()) + [KEY_TARGET, KEY_DECLINED, KEY_LAST_CHECK]:
        if k is None:
            break
        try:
            # A NULL value DELETES the key (that is the documented Win32 behaviour, and the only
            # way to remove one).
            k.WritePrivateProfileStringW(INI_SECTION, key, None, _ini_path(game_dir))
        except (OSError, AttributeError, ValueError):
            pass
