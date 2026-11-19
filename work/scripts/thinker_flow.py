"""The Thinker update, wired into the installer: consent, the manifest's Thinker data, the installer's
own Thinker question (Q1), the startup-box repair (--fix-thinker: Q-L then Q-T, the hand-over), the
changelog offer (CL), the --check line, and the box's "Don't ask me again" key.

Design: work/briefs/thinker-updater-design.md (draft 9); every player-facing text follows its
section 4. The modules below it do the work: thinker_state (detection, names), thinker_source (the
verified download), thinker_update (plan, backups, journal, swap, recovery), thinker_ini (the
settings files).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import installer_exit as ix
import thinker_data as td
import thinker_source as src
import thinker_state as st
import thinker_update as tu

CONSENT_SECTION = "Longevity"
CONSENT_KEY = "ThinkerUpdate"
CONSENT_ENV = "LONGEVITY_THINKER_CONSENT"      # set by generation 1 for its worker only
CONSENT_TTL = 30 * 60
CONSENT_ENV_TTL = 6 * 3600                     # generation 1 already checked the 30 minutes
DONT_ASK_SECTION = "UIMod"
DONT_ASK_KEY = "ThinkerMismatchDontAsk"
PLAYER_NO_PROMPT_ENV = "LONGEVITY_PLAYER_NO_PROMPT"
SCRUB_ENV = ("LONGEVITY_NO_WAIT", "LONGEVITY_WORKER", "LONGEVITY_PAYLOAD_ROOT", "LONGEVITY_GUARD_MARKER",
             "LONGEVITY_INSTALL_LOCK", PLAYER_NO_PROMPT_ENV, CONSENT_ENV)
ISSUED_FILE = Path("LongevityMods") / "manifest-issued.txt"
RECORD_FILE = Path("LongevityMods") / "thinker-update.json"
CHANGELOG_GLOB = "thinker-changelog-*.txt"
import manifest as _mf
DOWNLOAD_PAGE = _mf.DOWNLOAD_URL
CHANGELOG_URL = src.CHANGELOG_URL
PIN_ID_RE = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3})|(dev-20\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01]))")
LV_RE = re.compile(r"\d{1,4}\.\d{1,4}\.\d{1,4}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
CMD_UNSAFE = set('%&^"!<>|\r\n')


def _inst():
    import install
    return install


def _ver():
    import version
    return version


def scrubbed_env(extra: dict = None) -> dict:
    """The environment for anything that outlives this run (the hand-over console, a relaunched game):
    none of the installer's own run-scoped variables (section 8; round-6 finding B10)."""
    env = {k: v for k, v in os.environ.items() if k not in SCRUB_ENV}
    env.update(extra or {})
    return env


# ---------------------------------------------------------------- consent ([Longevity] ThinkerUpdate)

@dataclass
class Consent:
    kind: str            # "pin" | "keep"
    target: str          # pin id, or the Longevity version for keep
    at: int
    pid: int
    source: str          # "game" | "fix"


def format_consent(kind: str, target: str, source: str, pid: int = None, now: int = None) -> str:
    head = target if kind == "pin" else f"keep:{target}"
    return f"{head}|{int(now if now is not None else time.time())}|{pid if pid is not None else os.getpid()}|{source}"


def parse_consent(raw: str):
    if not raw or len(raw) > 120:
        return None
    parts = raw.strip().split("|")
    if len(parts) not in (3, 4):
        return None
    head, at, pid = parts[0], parts[1], parts[2]
    source = parts[3] if len(parts) == 4 else "game"
    if source not in ("game", "fix") or not at.isdigit() or not pid.isdigit():
        return None
    if head.startswith("keep:"):
        lv = head[5:]
        if not LV_RE.fullmatch(lv):
            return None
        return Consent("keep", lv, int(at), int(pid), source)
    if not PIN_ID_RE.fullmatch(head):
        return None
    return Consent("pin", head, int(at), int(pid), source)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == 259                    # STILL_ACTIVE
        return False
    finally:
        k32.CloseHandle(h)


def consent_fresh(c: Consent, now: float = None, ttl: int = CONSENT_TTL, alive=_pid_alive) -> bool:
    """The time and writer checks (section 8): not in the future, within the TTL, writer gone."""
    now = time.time() if now is None else now
    return c.at <= now + 5 and now - c.at <= ttl and not alive(c.pid)


def consent_matches(c: Consent, pin_id: str, version: str) -> bool:
    return (c.kind == "pin" and c.target == pin_id) or (c.kind == "keep" and c.target == version)


def write_consent(game_dir: Path, value: str) -> bool:
    return bool(_inst().write_ini_str(game_dir, CONSENT_SECTION, CONSENT_KEY, value))


def read_ini_str_absent(game_dir: Path, section: str, key: str):
    """The key's value, or None when it is not in Alpha Centauri.ini (as delete_ini_key tells them apart)."""
    v = _inst().read_ini_str(game_dir, section, key, "\x01absent\x01")
    return None if v == "\x01absent\x01" else v


def delete_ini_key(game_dir: Path, section: str, key: str) -> bool:
    inst = _inst()
    k = inst._kernel32()
    if k is None:
        return False
    if inst.read_ini_str(game_dir, section, key, "\x01absent\x01") == "\x01absent\x01":
        return True                   # not there: deleting it would still rewrite the file (a trailing newline)
    try:
        return bool(k.WritePrivateProfileStringW(section, key, None, inst._ini_path_str(game_dir)))
    except (OSError, ValueError, AttributeError):
        return False


def read_consent_key(game_dir: Path) -> str:
    return _inst().read_ini_str(game_dir, CONSENT_SECTION, CONSENT_KEY, "")


def take_for_generation_one(game_dir: Path):
    """Generation 1, after wait_for_game (the writer has gone): read, check time and writer, delete.
    Returns the raw value to hand to the worker in its environment only, or None."""
    raw = read_consent_key(game_dir)
    if raw:
        delete_ini_key(game_dir, CONSENT_SECTION, CONSENT_KEY)
    c = parse_consent(raw)
    if c is None or not consent_fresh(c):
        return None
    return f"{raw}|{int(time.time())}"                  # + when generation 1 checked it


def take_for_worker(game_dir: Path, pin_id: str, version: str):
    """The worker's consent: from generation 1's hand-off, or (a generation 1 older than this release
    handed nothing over) from the ini itself. Always deletes the key. Returns a Consent or None."""
    handed = os.environ.pop(CONSENT_ENV, "")
    raw = read_consent_key(game_dir)
    if raw:
        delete_ini_key(game_dir, CONSENT_SECTION, CONSENT_KEY)
    c = None
    if handed:
        body, _, checked = handed.rpartition("|")
        c = parse_consent(body)
        if c is None or not checked.isdigit() or time.time() - int(checked) > CONSENT_ENV_TTL:
            c = None
    elif raw:
        c = parse_consent(raw)
        if c is not None and not consent_fresh(c):
            c = None
    if c is None or not consent_matches(c, pin_id, version):
        return None
    return c


def clear_dont_ask(game_dir: Path) -> None:
    """Decision K: every install of Longevity Vaccine (fresh, same-version reinstall, --repair, an
    update that changes the core) clears the box's "Don't ask me again". Never read."""
    delete_ini_key(game_dir, DONT_ASK_SECTION, DONT_ASK_KEY)


# ---------------------------------------------------------------- the manifest's Thinker data

@dataclass
class ThinkerInfo:
    release_pins: dict = field(default_factory=dict)   # Longevity version -> pin id
    pins: dict = field(default_factory=dict)           # pin id -> (src.Pin, {"dll","stamp","image_size"})
    fatal: dict = field(default_factory=dict)          # Longevity version -> frozenset(dll sha256)
    issued: int = 0


def thinker_info(doc) -> ThinkerInfo:
    """The manifest's `thinker` object, grammar-checked; anything malformed is dropped (an entry, or
    the whole object), never trusted. `issued` is top-level."""
    info = ThinkerInfo()
    if not isinstance(doc, dict):
        return info
    iss = doc.get("issued")
    info.issued = iss if isinstance(iss, int) and not isinstance(iss, bool) and iss >= 0 else 0
    t = doc.get("thinker")
    if not isinstance(t, dict):
        return info
    rp = t.get("release_pins")
    if isinstance(rp, dict):
        info.release_pins = {k: v for k, v in rp.items()
                             if isinstance(k, str) and LV_RE.fullmatch(k) and isinstance(v, str) and PIN_ID_RE.fullmatch(v)}
    pins = t.get("pins")
    if isinstance(pins, dict):
        for pid, e in pins.items():
            if not (isinstance(pid, str) and PIN_ID_RE.fullmatch(pid) and isinstance(e, dict)):
                continue
            dl = e.get("download") if isinstance(e.get("download"), dict) else {}
            dll, sha, size = e.get("dll"), dl.get("sha256"), dl.get("size")
            if not (isinstance(dll, str) and SHA_RE.fullmatch(dll) and isinstance(sha, str) and SHA_RE.fullmatch(sha)
                    and isinstance(size, int) and not isinstance(size, bool) and 0 < size < (64 << 20)):
                continue
            strs = {k: (v if isinstance(v, str) else "") for k, v in (("tag", e.get("release_tag")),
                    ("asset", dl.get("asset")), ("dropbox", dl.get("dropbox")), ("rlkey", dl.get("rlkey")))}
            pin = src.Pin(pid, tag=strs["tag"], asset=strs["asset"], dropbox=strs["dropbox"], rlkey=strs["rlkey"],
                          zip_size=size, zip_sha256=sha)
            try:
                src.download_url(pin)
                src.page_url(pin)
            except src.SourceError:
                continue
            if pin.tag and src.TAG_RE.fullmatch(pin.tag) and st.parse_version(pin.tag[1:]).kind == st.VERSION:
                if st.compare(st.parse_version(pin.tag[1:]), st.parse_version(pid)) != 0:
                    continue                                 # the tag must name the entry's own version
            stamp, isize = e.get("stamp"), e.get("image_size")
            meta = {"dll": dll,
                    "stamp": stamp if isinstance(stamp, int) and not isinstance(stamp, bool) else None,
                    "image_size": isize if isinstance(isize, int) and not isinstance(isize, bool) else None}
            info.pins[pid] = (pin, meta)
    fat = t.get("fatal")
    if isinstance(fat, dict):
        for lv, shas in fat.items():
            if isinstance(lv, str) and LV_RE.fullmatch(lv) and isinstance(shas, list):
                info.fatal[lv] = frozenset(s for s in shas if isinstance(s, str) and SHA_RE.fullmatch(s))
    return info


def fatal_for(lv: str, info: ThinkerInfo, own_version: str) -> frozenset:
    """The FATAL list for Longevity `lv`: the compiled list counts only for this installer's OWN
    version (section 3, A-only guard; round-6 finding B7)."""
    got = set(info.fatal.get(lv, ()))
    if lv == own_version:
        got |= set(td.FATAL)
    return frozenset(got)


def compiled_pin() -> src.Pin:
    return src.compiled_pin(td)


def compiled_meta() -> dict:
    return {"dll": td.PIN_DLL_SHA256, "stamp": td.PIN_DLL_STAMP, "image_size": td.PIN_DLL_IMAGE_SIZE}


def issued_floor(game_dir: Path) -> int:
    """The highest `issued` seen; never above now + 1 day (a hostile file, or a build clock running ahead,
    must not switch the Thinker data off for good)."""
    p = Path(game_dir) / ISSUED_FILE
    try:
        v = int(p.read_text(encoding="ascii").strip()[:20] or 0)
    except (OSError, ValueError):
        return 0
    if v > int(time.time()) + 86400:
        import safe_fs
        try:
            safe_fs.unlink(Path(game_dir), p)         # from the future: discarded; never through a link
        except OSError:
            pass
        return 0
    return max(0, v)


def issued_check(game_dir: Path, info: ThinkerInfo, persist: bool) -> bool:
    """False when the manifest is OLDER than one already seen (a replay or a stale cache edge): its
    Thinker data is not used. Raises the floor when `persist` (never for a local or test manifest)."""
    floor = issued_floor(game_dir)
    if info.issued < floor:
        return False
    if persist and floor < info.issued <= int(time.time()) + 86400:
        try:
            p = Path(game_dir) / ISSUED_FILE
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(str(info.issued), encoding="ascii")
            os.replace(tmp, p)
        except OSError:
            pass
    return True


# ---------------------------------------------------------------- wording (section 4.0)

def page_of(pin: src.Pin) -> str:
    return src.page_url(pin)


def page_intro(pin: src.Pin) -> str:
    return "its download page" if pin.is_dev else "its release page"


# Colours of the Thinker question block (user 2026-11-14): the title blue; in the notes only the version
# numbers carry colour, the installed one red and the supported one green ("Thinker Mod" itself plain, and a
# build without a number red as a whole); the author blue; the recommendation yellow. The prompt line keeps
# "Thinker Mod" blue with the numbers red / green beside it; a build without a number stays red as a whole
# there too. ix.painted leaves the text plain on a console without colour.
TITLE_KIND = "keys"
_NUMBERED = re.compile(r"((?:[Yy]our )?Thinker Mod )(\S+)")


def _red(t: str) -> str:
    return ix.painted(t, "bad")


def _green(t: str) -> str:
    return ix.painted(t, "good")


def _blue(t: str) -> str:
    return ix.painted(t, "keys")


def _tm(ts: str) -> str:
    """The supported build on a prompt line: blue "Thinker Mod", green "5.5" (user 2026-11-14)."""
    return f"{_blue('Thinker Mod')} {_green(ts)}"


def _have(label: st.Label, ts: str, capital: bool = False) -> str:
    """{YOURS} on a prompt line: "your " + blue "Thinker Mod" + red "5.4"; a build its number does not name
    ("your development build of Thinker Mod") red as a whole after "your "."""
    y = st.yours(label, ts, capital=capital)
    m = _NUMBERED.fullmatch(y)
    if m:
        return f"{y[:5]}{_blue('Thinker Mod')} {_red(m.group(2))}"
    return y[:5] + _red(y[5:])


def _build(text: str, colour) -> str:
    """A build named in the notes: "Thinker Mod 5.4" / "your Thinker Mod 5.4" colours the number only;
    a build the number does not name ("a development build of Thinker Mod", "a different build of
    Thinker Mod 5.5") is coloured as a whole, after a leading "your "."""
    m = _NUMBERED.fullmatch(text)
    if m:
        return m.group(1) + colour(m.group(2))
    if text[:5].lower() == "your ":
        return text[:5] + colour(text[5:])
    return colour(text)


def _ran(run: str) -> str:
    """{RUN} in the notes, the installed build red."""
    return _build(run, _red)


def _yours(label: st.Label, ts: str, capital: bool = False) -> str:
    """{YOURS} in the notes, the installed build red."""
    return _build(st.yours(label, ts, capital=capital), _red)


def _sup(ts: str) -> str:
    """The supported build in the notes: "Thinker Mod " + green "5.5"."""
    return f"Thinker Mod {_green(ts)}"


def _numbered(label: st.Label, ts_raw: str) -> bool:
    """Does the build's own name end in its version number ("Thinker Mod 5.4")? Then "... files" reads; a
    development, different or unrecognised build is named by a phrase that does not take it (user 2026-11-15:
    "your development build of thinkermod will be backed up to a new folder in ...")."""
    return st.run_name(label, ts_raw).startswith("Thinker Mod ")


def backup_sentence(from_label: st.Label, ts_raw: str) -> str:
    files = " files" if _numbered(from_label, ts_raw) else ""
    return f"{_yours(from_label, ts_raw, capital=True)}{files} will be backed up to a new folder in LongevityMods\\backups."


def downgrade_sentence(ver_have: str, ts: str, lv: str) -> str:
    """The user's approved sentence, verbatim (2026-11-14)."""
    return (f"This is a downgrade! It replaces your newer Thinker Mod {_red(ver_have)} with the older {_sup(ts)}, "
            f"the version Longevity Vaccine {lv} supports.")


def neutral_sentence(run: str, ts: str, lv: str) -> str:
    """The user's approved sentence, verbatim (2026-11-14)."""
    return f"It replaces {_ran(run)} with {_sup(ts)}, the version Longevity Vaccine {lv} supports."


def settings_sentence(direction: str, ts: str) -> str:
    """Where the player's Thinker settings go. Never "new version" for a downgrade (user rule)."""
    into = "the new version of Thinker" if direction == st.UP else _sup(ts)
    return f"Your Thinker settings will be carried over into {into}. You do not need to change them."


def recommend_line(ts: str) -> str:
    """The yellow line of every Thinker question (Q1, Q-T; each direction). User wording 2026-11-15: "...while
    playing with Thinker + Longevity Vaccine."."""
    return ix.painted(f"We STRONGLY recommend installing Thinker Mod {ts} while playing with Thinker + Longevity "
                      "Vaccine.", "warn")


def project_line(url: str = src.THINKER_REPO_URL) -> str:
    """The closing line of a Thinker screen. `url`: the repository for players who have Thinker; the new-install
    screen passes THINKER_DETAILS_URL (user 2026-11-16)."""
    return (f"Thinker Mod is a project by {_blue(src.THINKER_AUTHOR)} and is not affiliated with Longevity "
            f"Vaccine. Learn more here: {_blue(url)}")     # the URL alone in the run: a console still finds the link


def thinker_block(first: str, can: list, direction: str, ts: str, if_no: str = None) -> list:
    """The notes of a Thinker question (journey R's Q-T and Q1), user rulings 2026-11-14: a blank line between
    the paragraphs; no download, rules or multiplayer sentence. `if_no` None: the block ends at the project line,
    with no blank line after it (Q1 when Longevity Vaccine can run alone, user 2026-11-15)."""
    notes = [first, "", *can, "", settings_sentence(direction, ts), "", recommend_line(ts), "", project_line()]
    return notes + ["", if_no] if if_no else notes


# ---------------------------------------------------------------- the Thinker step

@dataclass
class Prepared:
    """A Thinker step that passed its preflight: downloaded, verified, planned, nothing written."""
    game_dir: Path
    pin: src.Pin
    meta: dict
    dll: object                   # thinker_state.Dll or None
    plan: tu.Plan
    ts: str
    direction: str
    report: tu.Report = None
    committed: bool = False
    new: bool = False             # the folder had no Thinker Mod: a first install, nothing replaced (user 2026-11-15)
    repair: int = 0               # W9: only the missing release files are put back (as_repair); how many
    before: dict = None           # commit: the record and changelog copies as they were, for undo


def thinker_staging(game_dir: Path) -> Path:
    """Where the Thinker download and its unpacked files go. Not created here: the download creates it, so a run
    that fails before downloading leaves no empty folder behind (execution audit 2026-11-15)."""
    return Path(game_dir) / "LongevityMods" / "staging" / "thinker"


def _clear_staging(game_dir: Path) -> None:
    """After a finished change the zip and its unpacked files (~4 MB) are not needed again (execution audit
    2026-11-15): they go, and so does LongevityMods\\staging when nothing else is in it."""
    import safe_fs
    d = thinker_staging(game_dir)
    safe_fs.rmtree(Path(game_dir), d)         # never through a junctioned LongevityMods / staging (safe_fs)
    safe_fs.rmdir(Path(game_dir), d.parent)   # only when empty, never a link


def _old_stock_for(label: st.Label):
    """Decision MD: the stock values of the player's own tagged release, or None (carry every value)."""
    if label.kind != st.VERSION:
        return None
    for tag in (f"v{label.version}", f"v{'.'.join(str(x) for x in label.parts)}"):
        if tag in td.STOCK_VALUES:
            return td.STOCK_VALUES[tag]
    return None


RETRY = {"R": "start the game and choose 'Update now'",
         "A": "accept the update in the game when it is offered, or run the updater again",
         "B": "run the installer again"}


def _site() -> str:
    from urllib.parse import urlparse
    u = urlparse(DOWNLOAD_PAGE)
    return f"{u.scheme}://{u.netloc}"


def in_use(path, nothing: str, retry: str, as_were: str = "") -> ix.InstallerError:
    """The approved refusal for a Thinker file another program holds: "<file> is in use by another program, so
    <nothing>." and its remedy. Nothing was changed."""
    return ix.InstallerError(
        f"{Path(path).name} is in use by another program, so {nothing}." + as_were,
        code=ix.EXIT_ABORTED, changed=False,
        remedy="close any program that may have the game folder open (a file manager, an editor, another "
               f"copy of the game), wait a minute for any antivirus scan, then {retry}.")


def _classify(game_dir: Path, pin_sha: str, *, fresh: bool, route: str):
    """st.classify, or -- thinker.dll held with no sharing -- the in-use refusal, before anything is changed (audit-m
    #7: an INSTALLER ERROR crash)."""
    try:
        return st.classify(game_dir, pin_sha)
    except st.DllUnreadable as e:
        raise in_use(e.path, "nothing was installed" if fresh else "nothing was changed",
                     RETRY.get(route, RETRY["B"])) from e


def _state_sentence(lv_have: str, label: st.Label, ts: str, fresh: bool, ours: bool = False) -> str:
    """`ours`: the folder has the pinned build itself -- "your Thinker Mod 5.5", never "your different build of Thinker
    Mod 5.5" (audit-h L3: a failed repair download said so of our own build; fix_thinker's own rule)."""
    if fresh or not lv_have:
        return ""
    return f" Longevity Vaccine {lv_have} and {st.yours(label, None if ours else ts)} are as they were."


def prepare(game_dir: Path, pin: src.Pin, meta: dict, lv: str, *, route: str = "B",
            lv_have: str = "", fresh: bool = False, repair: list = None) -> Prepared:
    """Download, verify, extract and plan the pinned build (section 7 preflight). Raises
    ix.InstallerError F1 / F2 / F3 / a refusal; nothing in the game folder changes -- its download included: a
    preflight that fails or is stopped leaves no staging\\thinker behind, on every route (verification re-run of
    5f88a5c: --fix-thinker and --update kept it after a bad download). `route` picks the retry remedy (R, A or B);
    `lv_have` is the installed Longevity Vaccine for the "as they were" sentence. `repair`: the missing release
    files to put back, and nothing else (W9, as_repair)."""
    try:
        return _prepare(game_dir, pin, meta, lv, route=route, lv_have=lv_have, fresh=fresh, repair=repair)
    except BaseException:
        _clear_staging(Path(game_dir))
        raise


def _prepare(game_dir: Path, pin: src.Pin, meta: dict, lv: str, *, route: str, lv_have: str,
             fresh: bool, repair: list = None) -> Prepared:
    game_dir = Path(game_dir)
    state, dll = _classify(game_dir, meta["dll"], fresh=fresh, route=route)
    label = dll.label if dll else st.Label()
    ts = st.ts_display(pin.pin_id)
    retry = RETRY.get(route, RETRY["B"])
    nothing = "nothing was installed" if fresh else "nothing was changed"
    as_were = _state_sentence(lv_have, label, ts, fresh, ours=state == st.PIN)
    f2 = ix.InstallerError(
        f"The Thinker Mod download did not match the Thinker Mod {ts} release this update was built for, so {nothing}."
        + as_were, code=ix.EXIT_ABORTED, changed=False,
        remedy=f"{retry} later. If it keeps happening, the download link may have changed: get Thinker Mod {ts} "
               f"yourself from {page_intro(pin)} ({page_of(pin)}), and please let us know at {_site()}.")
    run = st.run_name(label, ts)
    direction = st.direction(label, ts, pin.is_dev)
    stg = thinker_staging(game_dir)
    import fetch
    ix.say("\n--- Thinker Mod ---")
    # User-approved wording 2026-11-16 (audit-j's unmarked lines).
    plan_line = f"{run} -> {ts}" if dll is not None else f"Installing Thinker Mod {ts}"
    if direction == st.DOWN:
        plan_line += " (a downgrade)"          # no note naming where the player said yes (user 2026-11-14)
    if not repair:
        ix.say(f"  {plan_line}")                # a repair has no "5.5 -> 5.5": its summary line says what it did
    try:
        url = src.download_url(pin)     # the URL the fetch requests (user 2026-11-14: shown as it is, uncoloured)
        ix.say(f"  Downloading Thinker Mod {ts} from {url}")
        z = src.fetch_zip(pin, stg, url=url, root=game_dir)
    except OSError as e:
        raise ix.InstallerError(f"Thinker Mod {ts} could not be saved to the game folder ({e.strerror or e}), so {nothing}."
                                + as_were, code=ix.EXIT_ABORTED, changed=False,
                                remedy=f"free some disk space, then {retry}.") from e
    except fetch.LinkError as e:
        # A link on the way into the game folder (audit-g LOW-1: this read "could not be downloaded ... check your
        # connection"): the approved line alone (user-approved 2026-11-15), uncut, no connection remedy.
        raise ix.InstallerError(str(e), code=ix.EXIT_ABORTED, changed=False) from e
    except fetch.MismatchError as e:
        # The whole file arrived and is not the release (execution audit 2026-11-15: this read "could not be
        # downloaded ... check your connection" after three retries of the same bad file).
        f2.detail = f"  {fetch.clean(str(e), 200)}"
        raise f2 from e
    except fetch.FetchError as e:
        raise ix.InstallerError(
            f"Thinker Mod {ts} could not be downloaded from {url}, so {nothing}." + as_were,     # the request URL
            code=ix.EXIT_ABORTED, changed=False, detail=f"  {fetch.clean(str(e), 200)}",
            remedy=f"check your connection, then {retry}.") from e
    except src.SourceError as e:
        f2.detail = f"  {e}"
        raise f2 from e
    if not pin.files:
        if pin.pin_id != td.PIN_VERSION:
            raise ix.InstallerError("This installer does not know the files of Thinker Mod " + ts + ", so nothing was changed.",
                                    code=ix.EXIT_ABORTED, changed=False)
        pin = src.Pin(**{**pin.__dict__, "files": compiled_pin().files})
    out = stg / f"files-{pin.pin_id}"
    try:
        staged = src.extract(pin, z, out)
    except OSError as e:
        raise ix.InstallerError(f"Thinker Mod {ts} could not be unpacked ({e.strerror or e}), so {nothing}." + as_were,
                                code=ix.EXIT_ABORTED, changed=False,
                                remedy=f"free some disk space, then {retry}.") from e
    except src.SourceError as e:
        f2.detail = f"  {e}"
        raise f2 from e
    ix.say(f"  Thinker Mod {ts}: downloaded and verified ({len(staged)} files)")
    try:
        p = tu.plan(game_dir, pin.pin_id, staged, known=td.KNOWN_KEYS, old_stock=_old_stock_for(label),
                    ts=ts, from_label=label)
    except (AssertionError, ValueError, OSError) as e:
        raise ix.InstallerError(
            f"Thinker Mod's settings could not be prepared ({type(e).__name__}), so {nothing}." + as_were,
            code=ix.EXIT_ABORTED, changed=False,
            remedy=f"{retry}; if it keeps happening, please report it at {_site()}.") from e
    except tu.ThinkerError as e:
        raise ix.InstallerError(
            f"Thinker Mod could not be changed ({e}), so {nothing}." + as_were,
            code=ix.EXIT_ABORTED, changed=False,
            remedy=f"replace that link in the game folder with an ordinary folder, then {retry}.") from e
    locked = tu.probe_locks(p)
    if locked is not None:
        raise in_use(locked, nothing, retry, as_were)
    prep = Prepared(game_dir, pin, meta, dll, p, ts, direction, new=dll is None)
    prep.retry, prep.as_were, prep.nothing = retry, as_were, nothing
    if repair:
        as_repair(prep, repair)
    return prep


def as_repair(prep: Prepared, missing: list) -> None:
    """W9: the plan puts back the missing release files and nothing else -- no file the player changed is replaced,
    thinker.ini / thinker_user.ini are not merged, no Datalinks text is replaced ("Files you changed are not
    touched", user-approved 2026-11-16). The files already identical stay "keep" (the install record lists them)."""
    want = set(missing)
    p = prep.plan
    p.actions = [a for a in p.actions if (a.kind == "add" and a.rel in want) or a.kind == "keep"]
    p.ini, p.user_ini, p.datalinks_ours, p.kept_alphax = None, None, [], False
    prep.repair = sum(1 for a in p.actions if a.kind == "add")


def commit(prep: Prepared, *, route: str, exe: dict = None) -> tu.Report:
    """Section 7 steps 1-3. Raises ix.InstallerError F5 / F6. A Ctrl-C at any point in it puts back what was
    swapped and says so before the run stops (verification of 9f2cb08, 2026-11-15: a Ctrl-C after the swap left
    Thinker Mod 5.5 with Longevity Vaccine not installed, and the verdict said only "You interrupted")."""
    prep.before = _side_files(prep.game_dir)          # what undo puts back besides Thinker's own files
    try:
        # The player's whole previous Thinker goes into the set (audit-j MEDIUM-1, user-approved 2026-11-16): never a
        # first install's (nothing of the player's) or a repair's (it replaces nothing).
        prep.report = tu.commit(prep.plan, route=route, exe=exe, repair=bool(prep.repair),
                                whole=not prep.new and not prep.repair)
    except KeyboardInterrupt:
        _undo_interrupted_swap(prep)
        raise
    except tu.ThinkerError as e:
        if e.kind == "F6":
            raise ix.InstallerError(
                "The update stopped part-way and could not put every file back. The game may not start "
                "correctly until this is fixed.", changed=True, title="INSTALLATION DID NOT COMPLETE",
                detail="\n".join(f"{f}: your copy from before is in LongevityMods\\backups" for f in e.files),
                remedy="close every program that may be using the game folder, then start the game and choose "
                       "'Update now': it finishes or undoes the change. If the game does not start, run the "
                       f"Longevity Vaccine installer again; you can download it from {DOWNLOAD_PAGE}. If that "
                       "fails too, copy the files listed above back into the game folder.") from e
        if _disk_full(e.__cause__):
            # A full disk (OSError 28 / WinError 112) is not a lock (audit-k LOW-6). User-approved wording 2026-11-16;
            # the remedy is the download's existing one. "so nothing was installed." in setup, "so nothing was
            # changed." everywhere else: both user-approved 2026-11-16.
            raise ix.InstallerError(
                f"Thinker Mod could not be changed (the disk is full), so "
                f"{getattr(prep, 'nothing', 'nothing was changed')}." + getattr(prep, "as_were", ""),
                code=ix.EXIT_ABORTED, changed=False,
                remedy=f"free some disk space, then {getattr(prep, 'retry', RETRY['B'])}.") from e
        name = Path(e.path).name if e.path else "a file"
        raise ix.InstallerError(
            f"Thinker Mod could not be changed ({name} could not be replaced), so "
            f"{getattr(prep, 'nothing', 'nothing was changed')}." + getattr(prep, "as_were", ""),
            code=ix.EXIT_ABORTED, changed=False,
            remedy="close any program that may have the game folder open, wait a minute for any antivirus "
                   f"scan, then {getattr(prep, 'retry', RETRY['B'])}.") from e
    prep.committed = True
    global LAST_COMMITTED
    LAST_COMMITTED = prep                             # install._saying_thinker_state reports it on a Ctrl-C
    try:
        if not prep.repair:                           # a repair is not a new version: no changelog offer
            _write_record(prep)
            _write_changelog_copy(prep)
    except KeyboardInterrupt:
        undo(prep)                                    # F6 if a file could not be put back, else the folder as it was
        prep.put_back = True                          # a caller whose console was captured says it again
        ix.say("  Thinker Mod was put back as it was.")
        raise
    return prep.report


def _disk_full(e) -> bool:
    """ENOSPC, or Windows' ERROR_DISK_FULL / ERROR_HANDLE_DISK_FULL."""
    import errno
    return isinstance(e, OSError) and (e.errno == errno.ENOSPC or getattr(e, "winerror", None) in (39, 112))


def _drop_set(bdir: Path) -> None:
    """Remove one of this installer's Thinker backup sets, and LongevityMods\\backups when that leaves it empty
    (verification of 9f2cb08: an empty backups folder stayed behind every first install)."""
    import safe_fs
    root = Path(bdir).parents[2]                      # <game>\LongevityMods\backups\<set>
    safe_fs.rmtree(root, Path(bdir))                  # never through a junction (safe_fs)
    tu.drop_rollback(Path(bdir))                      # and its undo-only copies beside it (audit-k LOW-5)
    safe_fs.rmdir(root, Path(bdir).parent)            # only when empty, never a link


def _undo_interrupted_swap(prep: Prepared) -> None:
    """Ctrl-C inside tu.commit (its journal written, the swap anywhere from not begun to done): roll it back from
    the journal, remove this run's set, and say so; F6 when a file cannot be put back."""
    import shutil
    g = prep.game_dir
    doc = tu.read_journal(g)
    if doc is None:
        return                                        # stopped before the journal: nothing was changed
    bdir = g / tu.BACKUPS / str(doc.get("backup", ""))
    r = tu.undo(g)
    if r != tu.UNDONE:
        raise ix.InstallerError(
            "The update stopped part-way and could not put every file back. The game may not start correctly until "
            "this is fixed.", changed=True, title="INSTALLATION DID NOT COMPLETE",
            remedy="close every program that may be using the game folder, then run the Longevity Vaccine installer "
                   f"again; you can download it from {DOWNLOAD_PAGE}. If that fails too, copy your Thinker Mod files back "
                   "from the newest folder in LongevityMods\\backups.")
    if doc.get("backup"):
        _drop_set(bdir)
    prep.put_back = True                              # a caller whose console was captured says it again
    ix.say("  Thinker Mod was put back as it was.")


#: The Thinker change this process committed last (install._saying_thinker_state).
LAST_COMMITTED = None


def _side_files(game_dir: Path) -> dict:
    """The record and the changelog copies as they are now: {path: bytes} (a missing record maps to None)."""
    out = {}
    rec = Path(game_dir) / RECORD_FILE
    try:
        out[rec] = rec.read_bytes()
    except OSError:
        out[rec] = None
    for p in (Path(game_dir) / "LongevityMods").glob(CHANGELOG_GLOB):
        try:
            out[p] = p.read_bytes()
        except OSError:
            pass
    return out


def _undo_side_files(prep: Prepared) -> None:
    """After a successful undo nothing of this run's change is left (code review 2026-11-15): its backup set
    goes (every file in it is back in place; an empty one is a first install's), and the record and the
    changelog copies are put back as commit found them -- so older_backups, uninstall_lines and CL never see a
    change that did not happen."""
    bdir = getattr(prep.report, "backup_dir", None)
    if bdir is not None:
        _drop_set(bdir)
    before = getattr(prep, "before", None)
    if before is None:
        return
    import safe_fs
    g = Path(prep.game_dir)
    for p in (g / "LongevityMods").glob(CHANGELOG_GLOB):
        if p not in before:
            try:
                safe_fs.unlink(g, p)
            except OSError:
                pass
    for p, data in before.items():
        try:
            if data is None:
                safe_fs.unlink(g, p)
            elif not safe_fs.link_on_path(g, p.parent):
                p.write_bytes(data)
        except OSError:
            pass


def undo(prep: Prepared) -> str:
    """Put the Thinker files back after a later step failed with the OLD exe in place. Raises the F6 verdict
    when a file could not be restored (never claims "back as it was" when it is not)."""
    if not prep.committed:
        return tu.UNDONE
    r = tu.undo(prep.game_dir)
    if r != tu.UNDONE:
        raise ix.InstallerError(
            "The update stopped part-way and could not put every file back. The game may not start correctly until "
            "this is fixed.", changed=True, title="INSTALLATION DID NOT COMPLETE",
            remedy="close every program that may be using the game folder, then run the Longevity Vaccine installer "
                   f"again; you can download it from {DOWNLOAD_PAGE}. If that fails too, copy your Thinker Mod files back "
                   "from the newest folder in LongevityMods\\backups.")
    prep.committed = False
    _undo_side_files(prep)                  # only after every file is back: an F6 keeps its set (the remedy names it)
    return r


def finish(prep: Prepared) -> None:
    """The change is complete. The empty set of a first install goes BEFORE the journal does (verification of
    9f2cb08: a Ctrl-C between the two left that set for good -- with the journal still there, the next run's
    recovery tidies it), then the journal, then the download."""
    bdir = getattr(prep.report, "backup_dir", None)
    if (prep.new or prep.repair) and bdir is not None:
        try:
            if bdir.is_dir() and not any(bdir.iterdir()):
                _drop_set(bdir)               # a first install replaced nothing: no empty "thinker-other-..." set
        except OSError:
            pass
    plan = getattr(prep, "plan", None)
    if plan is not None and hasattr(plan, "actions"):
        # EVERY release file now in place -- the ones the change wrote and the ones already identical (its "keep"
        # actions): a later change or removal acts on the whole release (audit-f M1: a record of the changed files
        # alone left thinker.exe and the unchanged files behind when Thinker was removed). Written BEFORE the
        # journal goes (audit-g LOW-2: a Ctrl-C between the two lost it for good; with the journal still there, the
        # next run's recovery writes it again).
        files = _record_files((a.rel, a.kind, a.new_sha) for a in plan.actions)
        if prep.repair:
            files = _repaired_record(prep.game_dir, prep.pin.pin_id, files)
        write_install_record(prep.game_dir, prep.pin.pin_id, files)
    tu.finish(prep.game_dir)
    _clear_staging(prep.game_dir)


def _repaired_record(game_dir: Path, pin_id: str, put_back: dict) -> dict:
    """A repair's install record (audit-h M1): every entry of the record it repaired -- the Datalinks-patched help
    texts, the files the player changed, thinker.ini -- plus the files it put back. A repair never had the plan's other
    actions (as_repair), so the record must not be rebuilt from them."""
    rec = read_install_record(game_dir)
    if rec is None or rec["pin"] != pin_id:
        return put_back
    return {**rec["files"], **put_back}


def _files(n: int) -> str:
    return f"{n} file" + ("" if n == 1 else "s")


def _settings_lines(prep: Prepared) -> list:
    """What happened to the player's thinker.ini / thinker_user.ini (merged, keys commented): every summary."""
    p, out = prep.plan, []
    if getattr(p, "ini", None) is not None:
        import thinker_ini
        if p.ini.unparsed:
            out.append("  thinker.ini could not be read (too large, or not text), so Thinker Mod's own settings file was "
                       "installed; your old file is in the backup above.")
        else:
            out.append(f"  thinker.ini: Thinker Mod {prep.ts}'s settings file was installed with your values carried over.")
            if p.ini.commented:
                out.append(f"  Settings Thinker Mod {prep.ts} does not use were kept at the end of thinker.ini as comments: "
                           + thinker_ini.console_names(p.ini.commented) + ".")
    if getattr(p, "user_ini", None) is not None and p.user_ini.changed:
        import thinker_ini
        out.append(f"  thinker_user.ini: settings Thinker Mod {prep.ts} does not use were commented out: "
                   + thinker_ini.console_names(p.user_ini.commented) + ".")
    return out


def summary_lines(prep: Prepared) -> list:
    """C1's commit lines (section 4)."""
    if getattr(prep, "repair", 0):
        # User-approved wording 2026-11-16 ("<N> missing files put back"; one file in the singular).
        n = prep.repair
        return [f"  Thinker Mod {prep.ts}: {n} missing file{'' if n == 1 else 's'} put back"]
    r, p = prep.report, prep.plan
    label = prep.dll.label if prep.dll else st.Label()
    out = []
    if prep.new:
        # A first install replaces nothing of Thinker's own, but a folder can still hold an old thinker.ini /
        # thinker_user.ini (code review 2026-11-15): those are merged and backed up, and the lines below say so.
        # User-approved wording 2026-11-16 (audit-j's unmarked lines).
        out.append(f"  Thinker Mod {prep.ts}: installed ({_files(r.added)} added"
                   + (f", {r.replaced} replaced" if r.replaced else "") + ")")
        if p.kept_alphax:
            out.append("  Kept as it is: alphax.txt (your rules file in the game folder; Thinker Mod's copy is optional)")
        if r.replaced:
            out.append(f"  The files it replaced are saved in LongevityMods\\backups\\{r.backup_dir.name}")
        return out + _settings_lines(prep)
    what = {st.UP: f"updated to {prep.ts}", st.DOWN: f"downgraded from {label.version} to {prep.ts}",
            st.OTHER: f"replaced your build with {prep.ts}"}[prep.direction]
    out.append(f"  Thinker Mod: {what} ({_files(r.replaced)} replaced, {r.added} added, {r.kept_or_merged} kept)")
    if p.kept_alphax:
        out.append("  Kept as it is: alphax.txt (your rules file in the game folder; Thinker Mod's copy is optional)")
    # User-approved wording 2026-11-16 (audit-j's unmarked lines).
    saved = " files are saved" if _numbered(label, prep.ts) else " is saved"          # as backup_sentence
    out.append(f"  {st.yours(label, prep.ts, capital=True)}{saved} in LongevityMods\\backups\\{r.backup_dir.name}")
    if r.older_backups:
        n = r.older_backups
        out.append(f"  You also have {n} older Thinker Mod backup{'s' if n != 1 else ''} in LongevityMods\\backups. "
                   "Nothing deletes them; you can delete any you do not need.")
    out += _settings_lines(prep)
    if any(a.rel == "german/alphax.txt" and a.kind in ("add", "replace") for a in p.actions) and p.kept_alphax:
        out.append("  german\\alphax.txt was updated. If you play with the German rules file copied into the game "
                   "folder, copy it there again.")
    return out


#: The thinker.ini choice (user 2026-11-16, verbatim): the note line (approved with its full stop), and the options,
#: "Skip" first (the marker on it).
INI_NOTE = "Check Thinker.ini to adjust options, such as difficulty."
INI_OPTIONS = ["Skip", "Open Thinker.ini"]


#: The thinker.ini choice this run's committed change owes: True to ask it, False for the note line alone, None for
#: nothing owed. Set by report_change, asked by offer_owed_ini (the closing lines).
_INI_OWED = None
#: The record key a WORKER carries the owed choice in to its parent (the bootstrap), which prints the closing lines.
INI_KEY = "ini_owed"


def report_change(game_dir: Path, prep: Prepared, args) -> None:
    """A committed Thinker change's summary (summary_lines), under its own section heading, like every other part of
    the log (user 2026-11-16: the summary printed under "--- PRACX icons ---"). It owes the thinker.ini choice after
    every install, upgrade, downgrade and same-version build swap; never after a repair, which changes no setting (both
    confirmed by the user, 2026-11-16). The choice is asked in the closing lines, directly before the Thinker changelog
    choice (user 2026-11-16: "Move the thinker.ini prompt to be right before the changelog prompt in all cases. We
    shouldn't have the shortcut prompt bisecting them.")."""
    ix.say("\n--- Thinker Mod ---")
    for line in summary_lines(prep):
        ix.say(line)
    if not getattr(prep, "repair", 0):
        _owe_ini(Path(game_dir), _asks(args))


def _owe_ini(game_dir: Path, asks: bool) -> None:
    """In-process, the closing lines ask it. A worker's closing lines are its parent's (the bootstrap): the record
    carries it there, with this worker's answer to "can it be asked" (the player's --no-prompt reaches only the worker).
    A record that cannot carry it: asked here, as before, so it is never lost."""
    global _INI_OWED
    if not ix.is_worker():
        _INI_OWED = asks
        return
    p = game_dir / RECORD_FILE
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(rec, dict):
            raise ValueError("not a record")
        rec[INI_KEY] = "ask" if asks else "note"
        p.write_text(json.dumps(rec), encoding="utf-8")
    except (OSError, ValueError):
        _offer_ini(game_dir, asks)


def offer_closing(game_dir: Path, process_start: float) -> None:
    """The Thinker choices of the closing lines: the thinker.ini choice, then the changelog choice (or its fallback
    line), with nothing between them."""
    offer_owed_ini(game_dir, process_start)
    offer_changelog(game_dir, process_start)


def offer_owed_ini(game_dir: Path, process_start: float) -> None:
    """The thinker.ini choice this run owes, once: this process's own, else one its worker carried in the record
    (only one written during this run, like the changelog's). Never raises."""
    global _INI_OWED
    asks, _INI_OWED = _INI_OWED, None
    if asks is None and game_dir:
        p = Path(game_dir) / RECORD_FILE
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = None
        if (isinstance(rec, dict) and rec.get(INI_KEY) in ("ask", "note") and isinstance(rec.get("at"), int)
                and rec["at"] >= int(process_start) - 1):
            asks = rec.pop(INI_KEY) == "ask"
            try:
                p.write_text(json.dumps(rec), encoding="utf-8")
            except OSError:
                pass
    if asks is not None:
        _offer_ini(Path(game_dir), asks and ix.can_ask())


def offer_ini(game_dir: Path, args) -> None:
    """The thinker.ini choice, asked now (_offer_ini) as this run's arguments allow."""
    _offer_ini(game_dir, _asks(args))


def _offer_ini(game_dir: Path, asks: bool) -> None:
    """The thinker.ini choice (user 2026-11-16): an arrow choice with no title, like the changelog's. No console or
    --no-prompt: the note line alone. Ctrl-C / EOF is "Skip" (the change is already committed)."""
    if not asks:
        ix.blank()
        ix.say(INI_NOTE)
        ix.blank()
        return
    try:
        pick = _inst()._arrow_menu(None, [[o] for o in INI_OPTIONS], notes=[INI_NOTE])
    except (EOFError, KeyboardInterrupt):
        pick = 0
    if pick == 1:
        _open_ini(Path(game_dir))
    ix.blank()


def _open_ini(game_dir: Path) -> None:
    """"Open Thinker.ini": the game folder's thinker.ini in Notepad, as the changelog is opened; on failure, where it
    is. User-approved wording (2026-11-16), both lines."""
    path = game_dir / "thinker.ini"
    notepad = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
    try:
        if not notepad.is_file() or not path.is_file():
            raise OSError("no notepad or no thinker.ini")
        subprocess.Popen([str(notepad), str(path)], close_fds=True, env=scrubbed_env())
        ix.say(f"Opening Thinker.ini in Notepad. If it does not appear, it is in your game folder: {path}")
    except OSError:
        ix.say(f"Thinker.ini could not be opened. It is in your game folder: {path}")


def game_sees_mismatch(dll, meta: dict) -> bool:
    """The game's own header test against the pin the folder will be compared with."""
    if dll is None:
        return False
    return not st.header_matches(dll, meta.get("stamp"), meta.get("image_size"))


# ---------------------------------------------------------------- record, changelog copy, CL

def _write_record(prep: Prepared) -> None:
    label = prep.dll.label if prep.dll else st.Label()
    doc = {"from": st.run_name(label) if prep.dll is not None else "no Thinker Mod", "to": prep.pin.pin_id,
           "at": int(time.time()), "changelog_offered": False}
    p = prep.game_dir / RECORD_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc), encoding="utf-8")
    except OSError:
        pass


def _write_changelog_copy(prep: Prepared) -> None:
    cl = prep.game_dir / "Changelog.md"
    staged = {a.rel: a for a in prep.plan.actions}
    data = None
    if "Changelog.md" in staged and cl.is_file():
        try:
            data = cl.read_bytes()
        except OSError:
            data = None
    import safe_fs
    mods = prep.game_dir / "LongevityMods"
    for old in mods.glob(CHANGELOG_GLOB):
        try:
            safe_fs.unlink(Path(prep.game_dir), old)
        except OSError:
            pass
    if data is None:
        return
    text = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
    try:
        (mods / changelog_copy_name(prep.pin.pin_id)).write_bytes(text)
    except OSError:
        pass


def changelog_copy_name(pin_id: str) -> str:
    """The changelog copy of ONE build: "thinker-changelog-5.5.txt", or for a development build
    "thinker-changelog-rel_-Nov-1-2026.txt". CL offers this name and no other (user 2026-11-16: a build that shipped no
    Changelog.md -- a development build may not -- is never offered an older build's copy)."""
    ts = st.ts_display(pin_id)
    return f"thinker-changelog-{ts.replace(' ', '-').replace('.', '_') if pin_id.startswith('dev-') else ts}.txt"


def offer_changelog(game_dir: Path, process_start: float) -> None:
    """CL (section 4): once, after a run that committed a Thinker change."""
    if not game_dir:
        return
    game_dir = Path(game_dir)
    p = game_dir / RECORD_FILE
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(rec, dict) or rec.get("changelog_offered") or not isinstance(rec.get("at"), int):
        return
    if rec["at"] < int(process_start) - 1:
        return
    try:
        state, dll = st.classify(game_dir, td.PIN_DLL_SHA256 if rec.get("to") == td.PIN_VERSION else "0" * 64)
    except st.DllUnreadable:
        return                                            # held by another program: no offer this time (audit-m #7)
    if dll is None:
        return
    rec["changelog_offered"] = True
    try:
        p.write_text(json.dumps(rec), encoding="utf-8")
    except OSError:
        pass
    to = str(rec.get("to", ""))
    ts = st.ts_display(to)
    # Only this build's own copy: written when the build shipped a Changelog.md (_write_changelog_copy). Any other
    # copy is an older build's (its deletion failed), never this one's (user 2026-11-16).
    copy = game_dir / "LongevityMods" / changelog_copy_name(to) if PIN_ID_RE.fullmatch(to) else None
    if copy is None or not copy.is_file():
        ix.say(f"What's new in Thinker Mod: {CHANGELOG_URL}")
        return
    rel = f"LongevityMods\\{copy.name}"
    if not ix.can_ask():
        ix.say(f"What's new in Thinker Mod {ts}: {rel} in your game folder, or online: {CHANGELOG_URL}")
        return
    try:
        # User-approved 2026-11-15: an arrow choice WITHOUT a title (the earlier ruling: a title "adds nothing").
        pick = _inst()._arrow_menu(None, [[f"Open the Thinker Mod {ts} changelog"], ["Don't open it"]])
    except (EOFError, KeyboardInterrupt):
        pick = 1                                        # after the commit, a stop here is a no
    if pick == 0:
        _open_changelog(copy, ts, rel)
    ix.blank()                                          # the play note below is its own paragraph


def _open_changelog(copy: Path, ts: str, rel: str) -> None:
    notepad = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
    try:
        if not notepad.is_file():
            raise OSError("no notepad")
        subprocess.Popen([str(notepad), str(copy)], close_fds=True, env=scrubbed_env())
        ix.say(f"Opening the Thinker Mod {ts} changelog in Notepad. If it does not appear, "     # user 2026-11-15
               f"it is in your game folder at {rel}, and online: {CHANGELOG_URL}")
    except OSError:
        ix.say(f"The Thinker Mod {ts} changelog could not be opened. You can read the latest version of it online: "
               f"{CHANGELOG_URL}")


# ---------------------------------------------------------------- recovery at every entry

def recover_at_entry(game_dir: Path, live_exe_md5: str = None) -> str:
    r = tu.recover(game_dir, live_exe_md5=live_exe_md5)
    if r == tu.FINISHED:
        ix.say("An earlier Thinker Mod change was interrupted. It has now been finished.")
        if tu.LAST_RECOVERED and not tu.LAST_REPAIR:  # CL follows a finished recovery too -- never a repair's
            # (audit-h L2: a recovered repair offered the changelog and wrote "from": "")
            p = Path(game_dir) / RECORD_FILE
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"from": "", "to": tu.LAST_RECOVERED, "at": int(time.time()),
                                         "changelog_offered": False}), encoding="utf-8")
            except OSError:
                pass
    elif r == tu.UNDONE:
        ix.say("An earlier Thinker Mod change was interrupted. It has been undone.")
    elif r == tu.LOST:
        ix.say("An earlier Thinker Mod change was interrupted and could not be finished or undone.")
    if r in (tu.FINISHED, tu.UNDONE):
        _tidy_after_recovery(game_dir, r)
    return r


def _tidy_after_recovery(game_dir: Path, r: str) -> None:
    """What a finished or undone change leaves that nothing needs (verification 2026-11-15: after an interruption
    and a re-run the uninstaller listed an empty thinker-other-* set as real copies): the change's backup set when
    it holds no file (a first install's) or when the change was undone (every file in it is back in place), and the
    download in staging. A LOST change keeps everything: its set is the way back."""
    bdir = tu.LAST_BACKUP
    if bdir is not None:
        tu.drop_rollback(bdir)                        # finished or undone: the undo-only copies go (audit-k LOW-5)
    if bdir is not None and bdir.is_dir():
        if r == tu.UNDONE or not any(p.is_file() for p in bdir.rglob("*")):
            _drop_set(bdir)
    _clear_staging(game_dir)
    if r == tu.FINISHED and tu.LAST_RECOVERED and tu.LAST_ACTIONS:
        # The validated journal keeps rel / old / new only: every action in it is a change. The release files it did
        # not change are the ones already identical to the pin's (audit-f M1): recorded too.
        changed = _record_files((a.get("rel"), a.get("kind") or "replace", a.get("new")) for a in tu.LAST_ACTIONS)
        if tu.LAST_REPAIR:
            files = _repaired_record(game_dir, tu.LAST_RECOVERED, changed)     # as a completed repair (audit-h L2)
        else:
            files = _release_files_in_place(game_dir, tu.LAST_RECOVERED)
            files.update(changed)
        write_install_record(game_dir, tu.LAST_RECOVERED, files)


# ---------------------------------------------------------------- Q1: the installer's own question (journey B)

def _player_no_prompt(args) -> bool:
    """The PLAYER said --no-prompt: this run's own flag (not a worker's, whose --no-prompt is the bootstrap's), or
    the bootstrap's marker for it."""
    return ix.player_no_prompt() or (bool(getattr(args, "no_prompt", False)) and not ix.is_worker())


def _asks(args) -> bool:
    """Can Q1 be put? A console, and no --no-prompt from the PLAYER (on an update the bootstrap's own
    --no-prompt is ignored; the player's arrives as an environment marker; round-5 finding B13)."""
    if not ix.can_ask():
        return False
    if ix.is_worker():
        return not os.environ.get(PLAYER_NO_PROMPT_ENV)
    return not getattr(args, "no_prompt", False)


def choose(title: str, notes, options: list, stop_note=None, title_kind: str = TITLE_KIND) -> int:
    """An arrow-key choice in the Thinker question's ruled block (user 2026-11-15): the title blue, the options
    as rows -- the recommended one first, the marker on it -- and Enter takes the row under the marker (its
    index). The selected row is green as a whole; the others keep their own colours. Keys typed before the block
    was drawn are dropped. Ctrl-C / EOF ABORT the run with nothing changed (R-STOP; section 3E)."""
    try:
        return _inst()._arrow_menu(title, [[o] for o in options], notes=list(notes), title_kind=title_kind)
    except (EOFError, KeyboardInterrupt):
        raise ix.stopped_error(stop_note)


#: The new-install screen's first option and its other one (user 2026-11-15).
ONLY_INSTALL = "Only install Longevity Vaccine"
ONLY_UPDATE = "Only update Longevity Vaccine"


def new_install_notes(ts: str) -> list:
    """B, the Thinker screen of a setup run in a folder without Thinker Mod (user 2026-11-15, verbatim)."""
    return [
        "Thinker Mod is a separate mod for Alpha Centauri that is compatible with Longevity Vaccine. It rewrites the "
        "computer players' AI, adds new game rules & options, changes map generation, and much more.",
        "",
        f"Thinker Mod is only recommended for players who want a {ix.painted('more challenging', 'warn')} experience "
        "than vanilla Alpha Centauri.",
        "",
        f"This installer can download Thinker Mod {_green(ts)} and set it up for you.",
        "",
        project_line(src.THINKER_DETAILS_URL),       # a player without Thinker: what it is (user 2026-11-16)
    ]


def offer_thinker_install(game_dir: Path, args, lv: str, defer: bool = False) -> "UpdateThinker":
    """B (user 2026-11-15): a setup run (never --update) in a folder with no thinker.dll offers Thinker Mod.
    "Only install Longevity Vaccine" (the marker starts there) changes nothing about Thinker and is not
    remembered; "Also install" downloads, verifies and plans the pinned build like any Thinker step.
    --with-thinker chooses "Also install"; --keep-thinker, --no-prompt and an unattended run "Only install"."""
    pin, meta = compiled_pin(), compiled_meta()
    state, _dll = _classify(game_dir, meta["dll"], fresh=True, route="B")
    if state != st.NONE:
        return UpdateThinker()
    if getattr(args, "with_thinker", False):
        accepted = "flag"
    elif getattr(args, "keep_thinker", False) or not _asks(args):
        return UpdateThinker()
    else:
        ts = st.ts_display(pin.pin_id)
        options = [ONLY_INSTALL, f"Also install {_blue('Thinker Mod')} {_green(ts)}"]
        if choose("Thinker Mod", new_install_notes(ts), options) != 1:
            return UpdateThinker()
        accepted = "above"
    if defer:          # setup asks every question first; the download comes after them (download_step)
        return UpdateThinker(todo=(pin, meta, lv, dict(route="B", fresh=True)), accepted=accepted)
    return UpdateThinker(prep=prepare(game_dir, pin, meta, lv, route="B", fresh=True), accepted=accepted)


def q1_texts(dll, lv: str, pin: src.Pin, meta: dict, fresh: bool, fatal: bool):
    label = dll.label if dll else st.Label()
    ts = st.ts_display(pin.pin_id)
    run = st.run_name(label, ts)
    d = st.direction(label, ts, pin.is_dev)
    title = "Thinker Mod downgrade" if d == st.DOWN else "Thinker Mod"
    first = f"This game folder has {_ran(run)}. Longevity Vaccine {lv} needs {_sup(ts)}."
    backup = backup_sentence(label, ts)
    # The options in place of [Y/n] (user 2026-11-15): the recommended change first, the marker on it.
    if d == st.UP:
        can = [f"This installer can update Thinker Mod for you. {backup}"]
        change = f"Also update {_blue('Thinker Mod')} to {_green(ts)}"
    elif d == st.DOWN:
        can = [downgrade_sentence(label.version, ts, lv), f"This installer can do this downgrade for you. {backup}"]
        change = f"Also downgrade {_blue('Thinker Mod')} from {_red(label.version)} to {_green(ts)}"
    else:
        can = [f"This installer can change Thinker Mod for you. {neutral_sentence(run, ts, lv)} {backup}"]
        change = f"Also replace {_have(label, ts)} with {_tm(ts)}"
    only = ONLY_INSTALL if fresh else ONLY_UPDATE
    if fatal:
        # User-approved wording 2026-11-16 (audit-j's unmarked lines).
        other = "Cancel the installation" if fresh else "Cancel the update"
        if_no = (f"Longevity Vaccine {lv} does not start with {_yours(label, ts)}, so if you cancel, "
                 + ("nothing is installed." if fresh else "neither mod is changed."))
    else:
        # No "If you choose 'Only install / update Longevity Vaccine', ..." sentence (user 2026-11-15: "Drop" it).
        other, if_no = only, None
    return title, thinker_block(first, can, d, ts, if_no), [change, other]


def keep_line(dll, lv: str, pin: src.Pin, meta: dict) -> str:
    """KEEP (section 4), printed by the run that installs Longevity alone."""
    label = dll.label if dll else st.Label()
    ts = st.ts_display(pin.pin_id)
    s = f"{st.yours(label, ts, capital=True)} stays as it is. Longevity Vaccine {lv} works with Thinker Mod {ts}"
    return s + (", so the game will tell you about the mismatch when it starts." if game_sees_mismatch(dll, meta) else ".")


@dataclass
class UpdateThinker:
    """What do_update / _install do about Thinker this run."""
    prep: Prepared = None         # the Thinker step to commit, or None
    todo: tuple = None            # decided but not yet downloaded (defer=True): (pin, meta, lv, prepare's keywords)
    keep: str = ""                # the KEEP line to add to the verdict ("" = none)
    accepted: str = ""            # "game" | "fix" | "above" | "flag": C1's plan-line note


def update_preflight(game_dir: Path, args, doc, *, fresh: bool, lv: str, persist_issued: bool,
                     defer: bool = False) -> UpdateThinker:
    """Journey A / B: the installed Thinker against THIS release's compiled pin. Decides from the consent,
    --with-thinker, or Q1; prepares the step. Raises R1-update / R1-fresh / R2 / R-KEEP-REFUSED / F1-F3."""
    pin, meta = compiled_pin(), compiled_meta()
    state, dll = _classify(game_dir, meta["dll"], fresh=fresh, route="B" if fresh else "A")
    del PENDING_FORGET[:]
    if state == st.PIN:
        return _repair_step(game_dir, args, pin, meta, lv, fresh=fresh, defer=defer)
    if state != st.OFF_PIN:
        return UpdateThinker()
    info = thinker_info(doc) if doc is not None else ThinkerInfo()
    if doc is not None and not issued_check(game_dir, info, persist_issued):
        info = ThinkerInfo()
    fatal = dll.sha256 in fatal_for(lv, info, _ver().VERSION)
    ts = st.ts_display(pin.pin_id)
    run = st.run_name(dll.label, ts)
    c = take_for_worker(game_dir, pin.pin_id, lv) if not fresh else None
    choice, accepted = None, ""
    if c is not None:
        choice, accepted = ("yes" if c.kind == "pin" else "keep"), c.source
    elif getattr(args, "with_thinker", False):
        choice, accepted = "yes", "flag"
    elif getattr(args, "keep_thinker", False):
        choice, accepted = "keep", "flag"
    elif _asks(args):
        title, notes, options = q1_texts(dll, lv, pin, meta, fresh, fatal)
        note = None if fresh else "Only the updater itself was refreshed; your game files are exactly as they were."
        choice = "yes" if choose(title, notes, options, stop_note=note) == 0 else "no"
        accepted = "above"
    elif ix.player_no_prompt() or (getattr(args, "no_prompt", False) and not ix.is_worker()):
        # The player said not to ask (execution audit 2026-11-15: in a console this said "cannot ask questions ...
        # run it again in a console window"). User-approved wording (2026-11-15).
        raise ix.InstallerError(
            f"Longevity Vaccine {lv} needs Thinker Mod {ts}, this game folder has {run}, and --no-prompt says not to "
            f"ask, so nothing was {'installed' if fresh else 'updated'}.",
            code=ix.EXIT_ABORTED, changed=False,
            disk_note=False if fresh else None,      # "nothing was installed" says it once (verification re-run)
            remedy="run it again with --with-thinker to change Thinker Mod too"
                   + ("." if fatal else ", or with --keep-thinker to leave it as it is."))
    else:
        raise ix.InstallerError(
            f"Longevity Vaccine {lv} needs Thinker Mod {ts}, this game folder has {run}, and this run cannot ask "
            f"questions, so nothing was {'installed' if fresh else 'updated'}.",
            code=ix.EXIT_ABORTED, changed=False, disk_note=False if fresh else None,
            remedy="run it again in a console window and answer the question.")
    if choice in ("no", "keep"):
        if fatal:
            if choice == "keep":
                raise ix.InstallerError(
                    f"Longevity Vaccine {lv} does not start with {st.yours(dll.label, ts)}, so it was not installed on its "
                    "own. Nothing was changed.", code=ix.EXIT_ABORTED, changed=False, disk_note=False,
                    # User-approved wording 2026-11-16 (audit-j's unmarked lines).
                    remedy=("run the installer again and let it change Thinker Mod too." if fresh else
                            "accept the update in the game when it is offered, and let it change Thinker Mod too."))
            raise ix.InstallerError(
                f"You chose not to change Thinker Mod, and Longevity Vaccine {lv} does not start with "
                f"{st.yours(dll.label, ts)}, so Longevity Vaccine was not {'installed' if fresh else 'updated either'}."
                + (" Nothing was changed." if fresh else " Your game works as before."),
                code=ix.EXIT_DECLINED, changed=False,
                title="INSTALLATION CANCELLED" if fresh else "UPDATE CANCELLED",
                # fresh: the message ends "Nothing was changed." -- no second line saying it again (execution audit)
                disk_note=False if fresh else "Only the updater itself was refreshed; your game files are exactly as they were.",
                # User-approved wording 2026-11-16 (audit-j's unmarked lines).
                remedy=(("run the installer again and let it change Thinker Mod too, or get Thinker Mod " + ts + " yourself first, from "
                         f"{page_intro(pin)} ({page_of(pin)}), then run the installer again.") if fresh else
                        ("to update later, accept the update in the game when it is offered, or run the updater again and "
                         f"let it change Thinker Mod too. You can also get Thinker Mod {ts} yourself first, from {page_intro(pin)}: {page_of(pin)}")))
        return UpdateThinker(keep=keep_line(dll, lv, pin, meta))
    route = "B" if fresh else ("R" if accepted == "fix" else "A")
    lv_have = getattr(args, "_lv_have", "") or ""
    kw = dict(route=route, lv_have=lv_have, fresh=fresh)
    if defer:          # setup asks every question first; the download comes after them (download_step)
        return UpdateThinker(todo=(pin, meta, lv, kw), accepted=accepted)
    return UpdateThinker(prep=prepare(game_dir, pin, meta, lv, **kw), accepted=accepted)


def missing_release_files(game_dir: Path) -> list:
    """W9: the release files this installer put in place (its install record) that are no longer there, while the
    live thinker.dll is still the recorded one -- sorted. [] without a valid record, with another thinker.dll, or
    when nothing is missing. A path through a link is not counted (nothing is ever written through one)."""
    game_dir = Path(game_dir)
    rec = read_install_record(game_dir)
    if rec is None:
        return []
    files = rec["files"]
    dll_rel = next((r for r in files if r.lower() == "thinker.dll"), None)
    if dll_rel is None or _live_sha(game_dir / "thinker.dll") != files[dll_rel]:
        return []
    out = []
    for rel in files:
        try:
            tu.refuse_reparse(game_dir, rel)
        except tu.ThinkerError:
            continue
        if not game_dir.joinpath(*rel.split("/")).is_file():
            out.append(rel)
    return sorted(out)


def clear_remove_mark(game_dir: Path) -> None:
    """The record stays, without the mark of an unfinished "Also uninstall" (audit-k LOW-7)."""
    rec = read_install_record(game_dir)
    if rec is not None and rec.get("remove"):
        write_install_record(game_dir, rec["pin"], rec["files"])


#: "Only update Longevity Vaccine" at the repair question: the missing files to forget once the run succeeds
#: (settle_install_record), never before (audit-l L3: a Ctrl-C at a later question said NOTHING WAS CHANGED over it).
PENDING_FORGET: list = []


def _forget_missing(game_dir: Path, missing: list) -> None:
    """"Only update Longevity Vaccine": the record stops listing the missing files, so the question is not put again
    on every run."""
    rec = read_install_record(game_dir)
    if rec is None:
        return
    files = {r: s for r, s in rec["files"].items() if r not in set(missing)}
    write_install_record(game_dir, rec["pin"], files, remove=bool(rec.get("remove")))


def _repair_step(game_dir: Path, args, pin, meta, lv: str, *, fresh: bool, defer: bool) -> "UpdateThinker":
    """W9 (user-approved 2026-11-16): Thinker Mod on the pin, put in place by this installer, with release files
    missing. --with-thinker repairs, --keep-thinker leaves it (no line), a console asks; without one (or with the
    player's --no-prompt) one line says so and the run goes on."""
    missing = missing_release_files(game_dir)
    if not missing:
        return UpdateThinker()
    ts, n = st.ts_display(pin.pin_id), len(missing)
    if getattr(args, "with_thinker", False):
        accepted = "flag"
    elif getattr(args, "keep_thinker", False):
        return UpdateThinker()
    elif _asks(args):
        # User-approved wording 2026-11-16.
        notes = [f"Thinker Mod {_green(ts)} in this game folder is missing {n} of its files.", "",
                 f"This installer can download Thinker Mod {_green(ts)} and put the missing files back. Files you "
                 "changed are not touched."]
        options = [f"Also repair and update {_tm(ts)}", ONLY_UPDATE]
        note = None if fresh else "Only the updater itself was refreshed; your game files are exactly as they were."
        if choose("Thinker Mod", notes, options, stop_note=note) != 0:
            PENDING_FORGET[:] = missing                   # forgotten when the run succeeds (audit-l L3)
            return UpdateThinker()
        accepted = "above"
    else:
        # User-approved wording 2026-11-16.
        ix.say(f"  Thinker Mod {ts} is missing {n} of its files. Run the installer again in a console window to put "
               "them back.")
        return UpdateThinker()
    kw = dict(route="B" if fresh else "A", lv_have=getattr(args, "_lv_have", "") or "", fresh=fresh, repair=missing)
    if defer:
        return UpdateThinker(todo=(pin, meta, lv, kw), accepted=accepted)
    return UpdateThinker(prep=prepare(game_dir, pin, meta, lv, **kw), accepted=accepted)


def download_step(game_dir: Path, step: "UpdateThinker") -> "UpdateThinker":
    """A step decided with defer=True: download, verify and plan it now (prepare). Anything else unchanged."""
    if step.todo is None:
        return step
    pin, meta, lv, kw = step.todo
    return UpdateThinker(prep=prepare(game_dir, pin, meta, lv, **kw), keep=step.keep, accepted=step.accepted)


# ---------------------------------------------------------------- --check: the thinker= line

def check_line(game_dir: Path, doc, latest: str) -> str:
    """`thinker=<have>|<offered>|<bytes>|<lo>` (section 8), or "" when the folder is NONE or already on
    the latest pin, or the manifest lacks the latest pin's data."""
    info = thinker_info(doc)
    pid = info.release_pins.get(latest)
    if not pid or pid not in info.pins:
        return ""
    pin, meta = info.pins[pid]
    state, dll = st.classify(game_dir, meta["dll"])
    if state != st.OFF_PIN:
        return ""
    lab = dll.label
    off = st.parse_version(st.ts_display(pid)) if not pin.is_dev else st.Label()
    # The DLL's ParseVersion takes exactly 3 parts of 0..65535 without leading zeros, and refuses the WHOLE
    # answer otherwise: anything outside that grammar is sent as "?" (the DLL then words it from its own label).
    if lab.kind == st.VERSION and off.kind == st.VERSION and st.compare(lab, off) != 0 \
            and len(lab.parts) <= 3 and all(0 <= p <= 65535 for p in lab.parts):
        have = ".".join(str(lab.parts[k]) if k < len(lab.parts) else "0" for k in range(3))
    else:
        have = "?"
    lo = 0 if dll.sha256 in info.fatal.get(latest, frozenset()) else 1
    return f"thinker={have}|{pid}|{pin.zip_size}|{lo}"


# ---------------------------------------------------------------- --fix-thinker (journey R)

@dataclass
class Handover:
    cmd: str
    cwd: str


_HANDOVER: Handover = None


def pending_handover() -> Handover:
    return _HANDOVER


def handover_spawn(h: Handover) -> bool:
    """Start the update console (after the installer lock was released). True when it started."""
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        subprocess.Popen(h.cmd, cwd=h.cwd, close_fds=True, creationflags=flags, env=scrubbed_env())
        return True
    except OSError:
        return False


def _cmd_safe(s: str) -> bool:
    return not any(ch in CMD_UNSAFE for ch in s)


def fix_thinker(game_dir: Path, args) -> int:
    """Journey R (section 3R). Every outcome that changed nothing offers `Start the game ... [y/N]`."""
    global _RECOVERED, LAST_COMMITTED
    _RECOVERED = None
    LAST_COMMITTED = None
    try:
        return _fix_thinker(game_dir, args)
    except ix.InstallerError as e:
        if e.changed is False:
            _clear_staging(Path(game_dir))            # a keep / cancel leaves no download or empty folder behind
        if e.changed is False and not e.offer_play:
            e.offer_play, e.offer_play_default = True, False
        if _RECOVERED in (tu.FINISHED, tu.UNDONE) and e.changed is False:
            # Something DID change at the start (design section 4, R0's recovery lines): say so.
            word = "finished" if _RECOVERED == tu.FINISHED else "undone"
            e.message = (f"The interrupted Thinker Mod change was {word}. "
                         + e.message.replace("so nothing was changed", "so nothing else was changed"))
            e.changed = True
            e.disk_note = False
        raise
    except KeyboardInterrupt:
        # A Ctrl-C (inside the commit too, which puts the swap back): the download is not needed again
        # (verification of f076f34: staging\thinker stayed after one).
        _clear_staging(Path(game_dir))
        prep = LAST_COMMITTED
        if prep is not None and prep.committed:
            # Past the commit (X_cj, a Ctrl-C in finish): the change is in place, the next run finishes it.
            # User-approved wording (2026-11-15).
            ix.say(f"  Thinker Mod {prep.ts} is in place. Run the installer again to finish the change.")
        raise


_RECOVERED = None


def _fix_thinker(game_dir: Path, args) -> int:
    """Journey R (section 3R). Returns an exit code; sets install._VERDICT / _LAUNCH_EXE / _NOTE_ARGS."""
    global _HANDOVER
    inst = _inst()
    ver = _ver()
    import manifest as mfmod
    import receipt as rc
    game_dir = Path(game_dir)
    ix.say("Longevity Vaccine: making Longevity Vaccine and Thinker Mod work together")
    if getattr(args, "wait_pid", None):
        import bootstrap as bsmod
        ix.say("Waiting for Alpha Centauri to close...")
        if not bsmod._wait_for_pid(int(args.wait_pid), timeout=inst.GAME_EXIT_WAIT):
            raise ix.InstallerError("Alpha Centauri is still running, so nothing was changed.",
                                    code=ix.EXIT_ABORTED, changed=False,
                                    remedy="close the game, then start it again and choose 'Update now'.")
    ix.say("Checking which versions work together...")
    _relaunch_setup(game_dir)
    global _RECOVERED
    recovered = inst._recover_thinker(game_dir, rc.read(game_dir)) or None
    _RECOVERED = recovered
    if recovered == tu.LOST:
        raise ix.InstallerError(
            "The update stopped part-way and could not put every file back. The game may not start correctly "
            "until this is fixed.", changed=True, title="INSTALLATION DID NOT COMPLETE",
            remedy=f"run the Longevity Vaccine installer again; you can download it from {DOWNLOAD_PAGE}.")
    if not inst.lv_in_place(game_dir):
        # A part-finished uninstall (audit-k LOW-1: a repair, the Datalinks patch and "now work together" in a folder
        # with no uimod.dll and the original exe back). Nothing is changed, and no game is offered. User-approved
        # wording 2026-11-16.
        inst._LAUNCH_EXE = None
        raise ix.InstallerError(
            "Longevity Vaccine is not installed in this game folder, so nothing was changed.",
            code=ix.EXIT_ABORTED, changed=False, title="NOTHING WAS CHANGED", disk_note=False,
            remedy=f"run the Longevity Vaccine installer to install it; you can download it from {DOWNLOAD_PAGE}.")
    state_rc = rc.read(game_dir)
    installed = rc.module_version(state_rc, "base")
    resident = ver.VERSION
    pin_cur, meta_cur = compiled_pin(), compiled_meta()
    doc, info, reach, kill, stale = None, ThinkerInfo(), True, None, False
    try:
        raw, sig = inst.fetch_manifest(game_dir, getattr(args, "manifest", None), getattr(args, "offline", False))
        doc = mfmod.load_verified(raw, sig, allow_env=inst._local_manifest(getattr(args, "manifest", None)))
        info = thinker_info(doc)
        if not issued_check(game_dir, info, persist=not inst._local_manifest(getattr(args, "manifest", None))):
            reach, doc, info, stale = False, None, ThinkerInfo(), True
    except Exception as e:  # noqa: BLE001 - offline / untrusted: Thinker-only from compiled data
        ix.say(f"  ({str(getattr(e, 'message', e))[:120]})")      # the reason, never a Python class name
        reach = False
    if installed != resident and installed != ver.UNKNOWN:
        pid_inst = info.release_pins.get(installed)
        same_pin = pid_inst == pin_cur.pin_id
    else:
        same_pin = True
    latest = None
    if doc is not None:
        d = mfmod.decide(doc, installed, state_rc.get("target_id"))
        if d.action == mfmod.MANUAL:
            raise ix.InstallerError(d.message, code=ix.EXIT_ABORTED, changed=False,
                                    remedy=f"download the current version from {d.url}")
        if d.action == mfmod.UPDATE and d.version and ver.is_newer(d.version, installed):
            latest = d.version
    state, dll = _classify(game_dir, meta_cur["dll"], fresh=False, route="R")
    label = dll.label if dll else st.Label()
    ts_cur = st.ts_display(pin_cur.pin_id)
    ix.say("")
    ix.say(f"  Longevity Vaccine {installed} is installed. It works with Thinker Mod {ts_cur}.")
    # Compared with the pin only when it is not the pin: the pinned build itself is "Thinker Mod 5.5", never "a
    # different build of" it (execution audit 2026-11-15).
    ix.say(f"  This game folder has "
           f"{st.run_name(label, ts_cur if state == st.OFF_PIN else None) if dll else 'no Thinker Mod'}.")
    if not reach:
        ix.say("The update server sent older information than this installer has already seen, so it cannot offer a "
               "newer Longevity Vaccine now." if stale else
               "The installer could not reach the update server, so it cannot offer a newer Longevity Vaccine now.")
    # ---- Q-L
    q_l = None
    if latest and not ix.can_ask():
        # No question can be put (--no-prompt, or no console at all: verification of f076f34 drew this menu
        # unattended and under `< NUL`):
        # --no-prompt: the newer Longevity Vaccine is not offered here (the updater's own run offers it), as when the
        # server could not be reached; only the Thinker Mod for this release is matched (verification of 9f2cb08).
        latest = None
    lat_pid = info.release_pins.get(latest) if latest else None
    lat_pin_meta = info.pins.get(lat_pid) if lat_pid else None
    if latest:
        ts_lat = st.ts_display(lat_pid) if lat_pid else "?"
        on_lat = bool(lat_pin_meta and dll and dll.sha256 == lat_pin_meta[1]["dll"])
        will_qt_yes = state != st.NONE and not on_lat
        will_qt_no = state == st.OFF_PIN and same_pin
        notes = [f"Longevity Vaccine {latest} is available. You have {installed}. Longevity Vaccine {latest} works with "
                 + (f"your Thinker Mod {ts_lat}." if on_lat else f"Thinker Mod {ts_lat}.")]
        if state != st.NONE and (will_qt_yes or will_qt_no):
            # User-approved wording 2026-11-17 (during Part 5 of the walkthrough), verbatim; it replaced "After this, the
            # installer offers the Thinker Mod version that goes with your choice."
            notes.append("This installer will offer to update Thinker for you.")
        keep_lv = f"Keep Longevity Vaccine {installed}"         # user 2026-11-15: a choice, not [Y/n]
        # No "If you choose '<Keep Longevity Vaccine ...>', ..." sentence in any variant (user-approved 2026-11-17: dropped).
        # User-approved wording 2026-11-16 (audit-j's unmarked lines).
        q_l = choose("Longevity Vaccine update", notes, [f"Update Longevity Vaccine to {latest}", keep_lv],
                     title_kind=None) == 0
    # ---- the target and Q-T
    if q_l:
        if not lat_pin_meta:
            raise ix.InstallerError(
                "The update information does not say which Thinker Mod the new release needs, so nothing was changed.",
                code=ix.EXIT_ABORTED, changed=False, remedy="try again later.")
        t_lv, t_pin, t_meta = latest, lat_pin_meta[0], lat_pin_meta[1]
    else:
        if not same_pin:
            if q_l is False:
                return _r1_fix(game_dir, dll, meta_cur, kept=f"Longevity Vaccine {installed}",
                               extra="A Longevity Vaccine update was downloaded but not installed, so Thinker Mod can "
                                     "only be changed together with that update.")
            raise ix.InstallerError(
                "A Longevity Vaccine update was downloaded but not installed, and it cannot be offered now, so nothing "
                "was changed.", code=ix.EXIT_ABORTED, changed=False,
                remedy="run the updater again; nothing already downloaded is fetched twice.")
        t_lv, t_pin, t_meta = installed, pin_cur, meta_cur
    t_state, _ = _classify(game_dir, t_meta["dll"], fresh=False, route="R")
    ts_t = st.ts_display(t_pin.pin_id)
    q_t = None
    fatal = bool(q_l and dll and dll.sha256 in fatal_for(t_lv, info, ver.VERSION))
    if t_state == st.OFF_PIN:
        d = st.direction(label, ts_t, t_pin.is_dev)
        run = st.run_name(label, ts_t)
        first = f"Longevity Vaccine {t_lv} works with {_sup(ts_t)}. This game folder has {_ran(run)}."
        backup = backup_sentence(label, ts_t)
        # The options in place of [Y/n] (user 2026-11-15): the change first, the marker on it; colours follow the
        # prompt-line rule.
        if d == st.UP:
            can = [f"This installer can update Thinker Mod from {_red(label.version)} to {_green(ts_t)}. {backup}"]
            title = "Thinker Mod"
            options = [f"Update {_blue('Thinker Mod')} to {_green(ts_t)}", f"Keep {_blue('Thinker Mod')} {_red(label.version)}"]
        elif d == st.DOWN:
            can = [downgrade_sentence(label.version, ts_t, t_lv), f"This installer can do this downgrade for you. {backup}"]
            title = "Thinker Mod downgrade"
            options = [f"Downgrade {_blue('Thinker Mod')} from {_red(label.version)} to {_green(ts_t)}",
                       f"Keep {_blue('Thinker Mod')} {_red(label.version)}"]
        else:
            can = [f"This installer can change Thinker Mod for you. {neutral_sentence(run, ts_t, t_lv)} {backup}"]
            title = "Thinker Mod"
            options = [f"Replace {_have(label, ts_t)} with {_tm(ts_t)}", f"Keep {_have(label, ts_t)}"]
        # Only the fatal form keeps a closing sentence: the "If you choose 'Keep ...'" ones are gone (user
        # 2026-11-15: "Yes, drop those two"), so the block ends at the project line.
        # User-approved wording 2026-11-16 (audit-j's unmarked lines).
        if_no = (f"Longevity Vaccine {t_lv} does not start with {_yours(label, ts_t)}, so if you keep it, "
                 "neither mod is changed.") if fatal else None
        if getattr(args, "with_thinker", False) or getattr(args, "keep_thinker", False):
            q_t = bool(getattr(args, "with_thinker", False))      # the flags answer it, as in setup and the updater
        elif _player_no_prompt(args):
            # --fix-thinker --no-prompt asked anyway (verification of 9f2cb08: then updated Thinker on a default
            # Enter). The setup run's approved --no-prompt refusal.
            raise ix.InstallerError(
                f"Longevity Vaccine {t_lv} needs Thinker Mod {ts_t}, this game folder has {run}, and --no-prompt says "
                "not to ask, so nothing was updated.", code=ix.EXIT_ABORTED, changed=False,
                remedy="run it again with --with-thinker to change Thinker Mod too"
                       + ("." if fatal else ", or with --keep-thinker to leave it as it is."))
        elif not ix.can_ask():
            # No console (unattended, `< NUL`): the menu was drawn and read as a stop (verification of f076f34). The
            # approved cannot-ask refusal, as in setup and the updater.
            raise ix.InstallerError(
                f"Longevity Vaccine {t_lv} needs Thinker Mod {ts_t}, this game folder has {run}, and this run cannot ask "
                "questions, so nothing was updated.", code=ix.EXIT_ABORTED, changed=False,
                remedy="run it again in a console window and answer the question.")
        else:
            q_t = choose(title, thinker_block(first, can, d, ts_t, if_no), options) == 0
    # ---- outcomes
    if q_l:
        if q_t is False and fatal:
            return _r1_fix(game_dir, dll, t_meta, kept=keep_name(label, ts_t, st.direction(label, ts_t, t_pin.is_dev)))
        consent = format_consent("pin", t_pin.pin_id, "fix") if (q_t or t_state != st.OFF_PIN) else \
            format_consent("keep", t_lv, "fix")
        return _hand_over(game_dir, args, consent)
    if state == st.PIN and t_state == st.PIN and missing_release_files(game_dir):
        # The pinned build with release files missing (audit-j MEDIUM-2: a part-finished "Also uninstall" was "already
        # work together"): the repair, as setup and the update offer it.
        return _fix_repair(game_dir, args, pin_cur, meta_cur, installed, missing_release_files(game_dir))
    if q_t:
        prep = prepare(game_dir, t_pin, t_meta, t_lv, route="R",
                       lv_have=installed)
        commit(prep, route="thinker")
        tu.set_step(game_dir, 5)
        try:
            inst.patch_datalinks_text(game_dir)
        except Exception:  # noqa: BLE001 - the help text is not worth failing a committed swap
            pass
        finish(prep)
        report_change(game_dir, prep, args)           # the summary; the thinker.ini choice closes the run
        lab_from = prep.dll.label if prep.dll else st.Label()
        what = {st.UP: f"Thinker Mod updated from {lab_from.version} to {ts_t}.",
                st.DOWN: f"Thinker Mod downgraded from {lab_from.version} to {ts_t}.",
                st.OTHER: f"Thinker Mod {ts_t} installed in place of {st.yours(lab_from, ts_t)}."}[prep.direction]
        inst._VERDICT = ("UPDATE COMPLETE", f"{what} Longevity Vaccine {t_lv} and Thinker Mod {ts_t} now work together.")
        return ix.EXIT_OK
    if q_t is False:
        return _r1_fix(game_dir, dll, t_meta, kept=keep_name(label, ts_t, st.direction(label, ts_t, t_pin.is_dev)))
    if state == st.NONE:
        raise _no_change("This game folder has no Thinker Mod now, so there is nothing to match. Nothing was changed.")
    if recovered in (tu.FINISHED, tu.UNDONE):
        inst._VERDICT = ("UPDATE COMPLETE", f"The interrupted Thinker Mod change was "
                         f"{'finished' if recovered == tu.FINISHED else 'undone'}. Longevity Vaccine {installed} and "
                         f"Thinker Mod {ts_cur} now work together.")
        return ix.EXIT_OK
    if q_l is False:
        raise _no_change(f"You kept Longevity Vaccine {installed}. It works with your Thinker Mod {ts_cur}, so nothing else "
                         "was needed.")
    if state == st.PIN and t_state == st.PIN:
        # The pinned build: nothing to match, whether or not the server answered (execution audit 2026-11-15: offline
        # it ended "could not reach the update server" instead). The line above already said a newer Longevity
        # Vaccine could not be looked for.
        # User-approved wording 2026-11-16 (audit-j's unmarked lines).
        raise _no_change(f"Longevity Vaccine {installed} and Thinker Mod {ts_cur} already work together. Nothing was "
                         "changed.", title="ALREADY UP TO DATE")
    if not reach and stale:
        raise _no_change("The update server sent older information than this installer has already seen, so nothing "
                         "was changed.", remedy="try again in a few minutes.")
    if not reach:
        raise _no_change("The installer could not reach the update server, so nothing was changed.",
                         remedy="check your connection. The next time the game starts, choose 'Update now' in its message. "
                                f"You can also get Thinker Mod {ts_cur} yourself from {page_intro(pin_cur)}: {page_of(pin_cur)}")
    # User-approved wording 2026-11-16 (audit-j's unmarked lines).
    raise _no_change(f"Longevity Vaccine {installed} and Thinker Mod {ts_cur} already work together. Nothing was changed.",
                     title="ALREADY UP TO DATE")


def _fix_repair(game_dir: Path, args, pin, meta, lv: str, missing: list) -> int:
    """--fix-thinker over the pinned build with release files missing (W9's repair, journey R). --with-thinker repairs,
    --keep-thinker keeps; a console asks with W9's approved notes; --no-prompt and no console refuse, changing nothing.
    User-approved wording 2026-11-16: the options, the verdicts and the refusals, as proposed."""
    ts, n = st.ts_display(pin.pin_id), len(missing)
    if getattr(args, "with_thinker", False) or getattr(args, "keep_thinker", False):
        yes = bool(getattr(args, "with_thinker", False))
    elif _player_no_prompt(args):
        raise ix.InstallerError(
            f"Thinker Mod {ts} is missing {n} of its files, and --no-prompt says not to ask, so nothing was changed.",
            code=ix.EXIT_ABORTED, changed=False, disk_note=False, remedy="run it again with --with-thinker to put them back.",
            offer_play=True, offer_play_default=False)
    elif not ix.can_ask():
        raise ix.InstallerError(
            f"Thinker Mod {ts} is missing {n} of its files, and this run cannot ask questions, so nothing was changed.",
            code=ix.EXIT_ABORTED, changed=False, disk_note=False,
            remedy="run it again in a console window and answer the question.", offer_play=True, offer_play_default=False)
    else:
        notes = [f"Thinker Mod {_green(ts)} in this game folder is missing {n} of its files.", "",      # W9, approved
                 f"This installer can download Thinker Mod {_green(ts)} and put the missing files back. Files you "
                 "changed are not touched."]
        yes = choose("Thinker Mod", notes, [f"Repair {_tm(ts)}", f"Keep {_tm(ts)} as it is"]) == 0
    if not yes:
        # "Keep" (or --keep-thinker) is the player's latest answer about this Thinker: an earlier "Also uninstall" that did
        # not finish no longer stands, so the next uninstall asks again (audit-k LOW-7: it removed Thinker unasked).
        clear_remove_mark(game_dir)
        raise ix.InstallerError(
            f"You chose to keep Thinker Mod {ts} as it is, so nothing was changed. It is missing {n} of its files.",
            code=ix.EXIT_DECLINED, changed=False, title="UPDATE CANCELLED", disk_note=False,
            offer_play=True, offer_play_default=False)
    prep = prepare(game_dir, pin, meta, lv, route="R", lv_have=lv, repair=missing)
    commit(prep, route="thinker")
    tu.set_step(game_dir, 5)
    try:
        _inst().patch_datalinks_text(game_dir)
    except Exception:  # noqa: BLE001 - the help text is not worth failing a committed repair
        pass
    finish(prep)
    report_change(game_dir, prep, args)               # the summary line; no thinker.ini choice after a repair
    _inst()._VERDICT = ("UPDATE COMPLETE", f"Thinker Mod {ts} was repaired. Longevity Vaccine {lv} and Thinker Mod {ts} "
                        "now work together.")
    return ix.EXIT_OK


def _no_change(msg: str, title: str = "NOTHING WAS CHANGED", remedy: str = None) -> ix.InstallerError:
    return ix.InstallerError(msg, code=ix.EXIT_ABORTED, changed=False, title=title, disk_note=False, remedy=remedy,
                             offer_play=True, offer_play_default=False)


def keep_name(label: st.Label, ts: str, direction: str) -> str:
    """The build a 'Keep ...' option names, plain: "Thinker Mod 5.4", or "your development build of Thinker Mod"."""
    if direction in (st.UP, st.DOWN):
        return f"Thinker Mod {label.version}"
    return st.yours(label, ts)


def _r1_fix(game_dir: Path, dll, meta: dict, kept: str, extra: str = "") -> int:
    """R1-fix, UPDATE CANCELLED: `kept` names what the player chose to keep -- a Thinker Mod at Q-T, or Longevity
    Vaccine at Q-L (user 2026-11-15) -- and `extra` why that left nothing to do."""
    sees = game_sees_mismatch(dll, meta)
    msg = f"You chose to keep {kept}, so nothing was changed."
    if extra:
        msg += " " + extra
    if sees:
        msg += " The game will tell you about the mismatch again the next time it starts."
    raise ix.InstallerError(msg, code=ix.EXIT_DECLINED, changed=False, title="UPDATE CANCELLED", disk_note=False,
                            offer_play=True, offer_play_default=False)


def _relaunch_setup(game_dir: Path) -> None:
    inst = _inst()
    import receipt as rc
    tid = rc.read(game_dir).get("target_id")
    try:
        inst._LAUNCH_EXE = inst.mod_exe(game_dir, tid) if tid else None
    except Exception:  # noqa: BLE001
        inst._LAUNCH_EXE = None
    inst._NOTE_ARGS = (game_dir, tid)


def _hand_over(game_dir: Path, args, consent: str) -> int:
    """Section 3R step 3: check the command line, write the consent; the spawn happens after the lock is
    released (run_guarded's hand-over close)."""
    global _HANDOVER
    import bootstrap as bsmod
    bat = bsmod.updater_dir(game_dir) / "scripts" / "run-install.bat"
    gd = str(game_dir)
    if gd.endswith("\\"):
        gd += "."                                     # "D:\\" would end in an escaped quote for the C runtime
    cmd_args = ["--update", "--only-listed", "--game-dir", gd, "--wait-pid", str(os.getpid()),
                "--from-fix-thinker"]
    if getattr(args, "manifest", None):
        cmd_args += ["--manifest", str(args.manifest)]
    texts = [str(bat)] + cmd_args
    if not bat.is_file() or not all(_cmd_safe(t) for t in texts) or any("--no-wait" in t for t in texts):
        shown = " ".join(f'"{t}"' if " " in t else t for t in texts)
        raise _no_change("The update could not be started in a new window, so nothing was changed. To start it yourself, "
                         f"run: {shown}")
    if not write_consent(game_dir, consent):
        raise _no_change("The update could not be started in a new window, so nothing was changed.")
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    inner = " ".join(f'"{t}"' if (" " in t or t == str(bat)) else t for t in texts)
    # ONE string, exactly as update.cpp builds it: a list would go through list2cmdline, which escapes the
    # inner quotes with backslashes that cmd.exe does not understand (round-7 code review, B2).
    _HANDOVER = Handover(f'"{system}" /D /S /C "{inner}"', str(game_dir))
    inst = _inst()
    inst._NOTE_ARGS = None
    inst._VERDICT = ("UPDATE HANDED OVER", "The update continues in a new window. This window closes in a few seconds.")
    return ix.EXIT_OK


def handover_failed(game_dir: Path) -> None:
    delete_ini_key(game_dir, CONSENT_SECTION, CONSENT_KEY)


# ---------------------------------------------------------------- the release pipeline's manifest section

PINS_FILE = Path(__file__).resolve().with_name("thinker_pins.json")


def manifest_section(version: str) -> dict:
    """The manifest's `thinker` object for release `version` (section 9): every recorded release's pin,
    this release's pin entry, and its FATAL list. Built from compiled data only; nothing is hosted."""
    try:
        recorded = json.loads(PINS_FILE.read_text(encoding="utf-8")).get("release_pins") or {}
    except (OSError, ValueError):
        recorded = {}
    pins = {k: v for k, v in recorded.items() if isinstance(k, str) and LV_RE.fullmatch(k)
            and isinstance(v, str) and PIN_ID_RE.fullmatch(v)}
    pins[version] = td.PIN_VERSION
    download = {"sha256": td.PIN_ZIP_SHA256, "size": td.PIN_ZIP_SIZE}
    entry = {"dll": td.PIN_DLL_SHA256, "stamp": td.PIN_DLL_STAMP, "image_size": td.PIN_DLL_IMAGE_SIZE}
    if td.PIN_DROPBOX:
        download.update({"dropbox": td.PIN_DROPBOX, "rlkey": td.PIN_RLKEY})
        entry["dev"] = True
    else:
        download["asset"] = td.PIN_ASSET
        entry["release_tag"] = td.PIN_TAG
    entry["download"] = download
    return {"release_pins": dict(sorted(pins.items())),
            "pins": {td.PIN_VERSION: entry},
            "fatal": {version: sorted(td.FATAL)}}


# ---------------------------------------------------------------- uninstall U1

# ---------------------------------------------------------------- the install record and uninstalling Thinker Mod

#: What this installer put in place when it installed or updated Thinker Mod (user design 2026-11-15): the pin and
#: each file with its SHA-256. In the game folder itself, beside the receipt -- not in LongevityMods\ (the player is
#: told that folder is safe to delete after uninstalling), and not in the receipt (whose presence means "Longevity
#: Vaccine is installed", which a kept first Thinker install is not). A normal update never touches it.
INSTALL_RECORD = "longevity-thinker-install.json"

#: Never ours to remove, even when a change wrote them: the game's own rules file -- alphax.txt in the game folder
#: itself, any case -- and the player's own settings, thinker_user.ini in any folder and any case. Thinker's own copies
#: of the rules (smac_mod\alphax.txt, german\alphax.txt) follow the release's rule like any other file: removed while
#: the release's bytes, kept and named when changed (audit-j L2a). The pin's hash gate still decides what is "ours".
_NOT_REMOVED_ROOT = "alphax.txt"
_NOT_REMOVED_ANYWHERE = "thinker_user.ini"

#: Removed even when its live hash is not the recorded one: Thinker's own settings file, which the player edits (the
#: user's ruling). Every other release file is removed only while byte-identical to what was put in place.
_REMOVED_EDITED = "thinker.ini"

#: The release files the last remove_thinker LEFT because the player changed them (rel, forward slashes).
LAST_KEPT: list = []

#: Was the thinker.ini the last remove_thinker kept (LAST_KEPT) changed since this installer wrote it? [bool] or [].
LAST_KEPT_INI_EDITED: list = []

#: The Datalinks help texts (smac_mod) the last remove_thinker left because they hold text of Longevity Vaccine's that
#: it will not take out (patch_helptext's REFUSED: changed after it was patched, an unrecorded or newer revision, our
#: wording without its marker): the uninstall's verdict names them with master's Datalinks sentences, never a second
#: time under "Left in place:" (audit-l H1; user ruling 2026-11-17).
LAST_HELP_EDITED: list = []

#: How many of the last remove_thinker's failures were a link on the way (a re-run cannot fix those).
LAST_LINKED = 0


def _never_removed(rel: str) -> bool:
    return (rel.lower() == _NOT_REMOVED_ROOT or rel.rsplit("/", 1)[-1].lower() == _NOT_REMOVED_ANYWHERE
            or rel.endswith(tu.BAK))


def _pin_files(pin_id: str) -> dict:
    """{lower-case rel: (rel, sha256)} of the release the record names -- only the pin compiled into this installer:
    a record naming any other release describes files this installer cannot check, and is never acted on."""
    pin = compiled_pin()
    if pin_id != pin.pin_id:
        return {}
    return {rel.lower(): (rel, sha) for rel, sha in pin.files}


def _release_files_in_place(game_dir: Path, pin_id: str) -> dict:
    """{rel: sha256} of the pin's own files now in place byte-identical to the release (never one _never_removed names)."""
    out = {}
    for rel, sha in _pin_files(pin_id).values():
        p = Path(game_dir).joinpath(*rel.split("/"))
        if _never_removed(rel) or not p.is_file():
            continue
        try:
            if tu.sha256(p) == sha:
                out[rel] = sha
        except OSError:
            pass
    return out

ONLY_UNINSTALL = "Only uninstall Longevity Vaccine"


def _record_files(actions) -> dict:
    """{rel: sha256} of the release files a change put in place: (rel, kind, new_sha) triples."""
    out = {}
    for rel, kind, new in actions:
        if kind in ("add", "replace", "rewrite", "keep") and isinstance(rel, str) and not _never_removed(rel) \
                and isinstance(new, str) and len(new) == 64:
            out[rel] = new
    return out


def write_install_record(game_dir: Path, pin_id: str, files: dict, remove: bool = False) -> None:
    doc = {"schema": 1, "pin": pin_id, "files": dict(sorted(files.items()))}
    if remove:
        doc["remove"] = True
    p = Path(game_dir) / INSTALL_RECORD
    tmp = p.with_name(p.name + tu.TMP)
    try:
        tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        if p.is_file() and not os.access(p, os.W_OK):
            import stat
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)   # our own record, made read-only by someone (as the marker)
        os.replace(tmp, p)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)                  # never left in the game folder
        except OSError:
            pass


def clear_install_record(game_dir: Path) -> None:
    """Our record goes, read-only or not (unlink_entitled, as our other files: user ruling 2026-11-17, D3(b)); the
    uninstall's up-front check lists it. Never raises."""
    import safe_fs
    p = Path(game_dir) / INSTALL_RECORD
    try:
        if p.is_file() and not safe_fs.link_on_path(Path(game_dir), p):
            safe_fs.unlink_entitled(p)
    except OSError:
        pass


def read_install_record(game_dir: Path):
    """The record, or None: missing, unreadable, or naming a file the change could not have written -- a path that
    is not one of a Thinker release's own (thinker_source.check_path), or that leaves the game folder -- or one that
    is not a file of the pinned release the record names (this installer's compiled pin; compared ignoring case), or
    the game's rules / the player's settings in any folder (audit-f H1: an edited or planted record listed
    ALPHAX.TXT, prac.dll, x.SAV ...). An invalid record is never acted on (its files are never removed)."""
    try:
        doc = json.loads((Path(game_dir) / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("pin"), str) or not isinstance(doc.get("files"), dict):
        return None
    root = Path(game_dir).resolve()
    pin = _pin_files(doc["pin"])
    files = {}
    for rel, sha in doc["files"].items():
        if not tu._valid_rel(rel) or _never_removed(rel) or not isinstance(sha, str) or len(sha) != 64:
            return None
        entry = pin.get(rel.lower())
        if entry is None or entry[0] in files:
            return None
        # The hash is the release's own (audit-g HIGH-1: a record carrying the LIVE files' hashes named the player's
        # own Thinker 5.4 "ours", and "Also" removed it). thinker.ini alone is merged, so its hash is not the pin's.
        if sha != entry[1] and entry[0].lower() != _REMOVED_EDITED:
            return None
        try:
            (Path(game_dir) / rel).resolve().relative_to(root)     # ValueError: outside the folder (3.8: no is_relative_to)
        except (OSError, ValueError):
            return None
        files[entry[0]] = sha                         # the pin's own spelling (audit-g LOW-5: one case everywhere)
    doc["files"] = files
    return doc


def _pin_dll(pin_id: str):
    """The pinned release's thinker.dll hash, or None."""
    entry = _pin_files(pin_id).get("thinker.dll")
    return entry[1] if entry else None


def _rel_of(files: dict, name: str):
    return next((r for r in files if r.lower() == name), None)


def _removal_ready(game_dir: Path, rec: dict) -> bool:
    """May this record's Thinker Mod be removed at all (audit-h L5)? The record lists thinker.dll and the live one is
    the pinned release's; and thinker.exe is either not in the folder, or listed and the release's own -- so removing
    thinker.dll never leaves a launcher behind without it, and a record that does not name the launcher in place (a
    planted {thinker.dll, thinker.ini}, H26) is never acted on. A marked record with no thinker.dll in the folder (H2A)
    is not acted on either: every removal takes thinker.dll last, so nothing of ours is left to finish."""
    files = rec["files"]
    dll_rel, exe_rel = _rel_of(files, "thinker.dll"), _rel_of(files, "thinker.exe")
    want = _pin_dll(rec["pin"])
    if dll_rel is None or not want or _live_sha(game_dir / "thinker.dll") != want:
        return False
    exe = game_dir / "thinker.exe"
    if not exe.exists():
        return True
    return exe_rel is not None and _live_sha(exe) == files[exe_rel]


def _ini_removable(game_dir: Path, rec: dict) -> bool:
    """thinker.ini -- the one file removed even when the player edited it (the user's ruling) -- goes only with a whole
    release of ours (audit-h L5): the record lists thinker.ini (this installer wrote it), thinker.dll and thinker.exe,
    and the live thinker.dll AND thinker.exe are both the release's when the removal starts. Otherwise it stays."""
    files = rec["files"]
    rels = [_rel_of(files, n) for n in (_REMOVED_EDITED, "thinker.dll", "thinker.exe")]
    if None in rels:
        return False
    return all(_live_sha(game_dir.joinpath(*r.split("/"))) == files[r] for r in rels[1:])


def _ini_remainder(game_dir: Path, rec: dict) -> bool:
    """A marked record that is all that is left of an "Also uninstall" whose LAST removal, thinker.ini's, failed (audit-i
    MEDIUM-1: thinker.ini goes after thinker.exe and thinker.dll): the record keeps our thinker.dll entry, thinker.dll and
    thinker.exe are gone, and thinker.ini is the only recorded file still in place. Only then is thinker.ini finished
    without its dll (a planted marked record over files still in place, H2A, is not this)."""
    if not rec.get("remove"):
        return False
    files = rec["files"]
    ini_rel = _rel_of(files, _REMOVED_EDITED)
    if _rel_of(files, "thinker.dll") is None or ini_rel is None:
        return False
    if (game_dir / "thinker.dll").exists() or (game_dir / "thinker.exe").exists():
        return False
    for r in files:
        live = _live_sha(game_dir.joinpath(*r.split("/")))
        if r != ini_rel and live == files[r]:
            return False                                  # a release file of ours still in place (H2A)
    return game_dir.joinpath(*ini_rel.split("/")).is_file()


def ask_uninstall_thinker(game_dir: Path) -> bool:
    """At --uninstall, before anything is removed: also remove the Thinker Mod this installer put in place? Asked
    only when its record is valid AND the live thinker.dll is still the one it installed (a build the player swapped
    in since is theirs: nothing asked, Thinker stays), on a console without --no-prompt (ix.can_ask, NUL-safe).
    A record whose removal an earlier run started (and could not finish) is finished without asking."""
    game_dir = Path(game_dir)
    rec = read_install_record(game_dir)
    if rec is None:
        return False
    want = _pin_dll(rec["pin"])                       # the PIN's dll, never the record's own word (audit-g HIGH-1)
    live = _live_sha(game_dir / "thinker.dll")
    if rec.get("remove"):
        if live is not None and live != want:
            # The mark, but the live thinker.dll is the player's own build: theirs, not ours to finish removing; the
            # uninstall says Thinker stays (audit-g LOW-4), and the run past its up-front check drops the record.
            # Never here: nothing may change before that check, which can still refuse the whole run (audit of
            # 356c8f8, H1).
            return False
        # audit-h L5 (H2A): never with no thinker.dll of ours in place -- except the remainder of our own removal
        return _removal_ready(game_dir, rec) or _ini_remainder(game_dir, rec)
    if not want or live != want or not _removal_ready(game_dir, rec):
        return False
    if not ix.can_ask():
        return False
    ts = st.ts_display(rec["pin"])
    # The user's approved text (2026-11-15); "installed" also after an update of an older Thinker.
    notes = [f"Longevity Vaccine installed Thinker Mod {_green(ts)} in this folder.",
             "Thinker Mod works without Longevity Vaccine."]
    options = [ONLY_UNINSTALL, f"Also uninstall {_blue('Thinker Mod')} {_green(ts)}"]
    return choose("Thinker Mod", notes, options) == 1


def _live_sha(p: Path):
    try:
        return tu.sha256(p) if p.is_file() else None
    except OSError:
        return None


def remove_thinker(game_dir: Path) -> tuple:
    """Remove the files the record lists, each only while byte-identical to what was put in place (thinker.ini even
    when edited: it is Thinker's settings file); a file the player changed is LEFT (the user's ruling, 2026-11-15:
    "Leave edited files"; named in LAST_KEPT), and so is its folder. thinker.exe, thinker.dll and thinker.ini go last,
    in that order, each only when every removal before it succeeded (audit-f M3, audit-i MEDIUM-1: a failure must
    leave Thinker startable); after a failure the record keeps every recorded file still in place. A subfolder goes only
    when that leaves it empty; never the older version back (its backups stay in LongevityMods\\backups).

    A live thinker.dll that is not the recorded one is the player's own Thinker: nothing is removed and the record
    goes (audit-f H2: a hand-installed 5.4 was deleted by a later unattended run). The record is marked first, so a
    run stopped part-way finishes next time -- by these same rules -- and it goes once every unedited file is gone;
    a file left only because a link is on its way keeps its entry but not the mark (a link never goes away by
    itself: the next run asks again rather than finish unasked for ever). Nothing is removed unless the record is
    _removal_ready, and thinker.ini only with a whole release of ours (_ini_removable; audit-h L5). Returns
    (removed, failed)."""
    global LAST_LINKED
    game_dir = Path(game_dir)
    del LAST_KEPT[:]
    del LAST_KEPT_INI_EDITED[:]
    del LAST_HELP_EDITED[:]
    LAST_LINKED = 0
    rec = read_install_record(game_dir)
    if rec is None:
        return 0, 0
    files = rec["files"]
    dll_rel = next((r for r in files if r.lower() == "thinker.dll"), None)
    live = _live_sha(game_dir / "thinker.dll")
    if live is not None and (dll_rel is None or live != files[dll_rel]):
        clear_install_record(game_dir)
        return 0, 0
    remainder = _ini_remainder(game_dir, rec)
    if not (_removal_ready(game_dir, rec) or remainder):
        clear_install_record(game_dir)                    # audit-h L5: never acted on (as ask_uninstall_thinker) --
        return 0, 0                                       # and nothing of ours left to finish (RW8: all gone)
    # decided before anything goes (it goes last). A marked record is a removal of ours being finished: thinker.ini goes
    # with it when the record holds it and our thinker.dll entry (audit-j MEDIUM-2, K04: thinker.exe already gone).
    ini_too = remainder or _ini_removable(game_dir, rec) or bool(
        rec.get("remove") and _rel_of(files, _REMOVED_EDITED) and dll_rel)
    write_install_record(game_dir, rec["pin"], files, remove=True)
    import safe_fs
    removed, failed = 0, 0
    dirs = set()

    def one(rel) -> None:
        global LAST_LINKED
        nonlocal removed, failed
        p = game_dir.joinpath(*rel.split("/"))
        shown = rel.replace("/", "\\")
        try:
            tu.refuse_reparse(game_dir, rel)
            if not p.is_file():
                return                                    # already gone
            sha = tu.sha256(p)        # unreadable (in use): OSError below -- a failure, never "already gone" (audit-l M1)
            if rel.lower() == _REMOVED_EDITED and not ini_too:
                # Not with a whole release of ours: the settings stay -- and are named under "Left in place:", never
                # left unlisted (audit-k LOW-2, M11).
                LAST_KEPT.append(rel)
                LAST_KEPT_INI_EDITED[:] = [sha != files[rel]]
                return
            if sha != files[rel] and rel in tu.DATALINKS:
                # Classified on patch_helptext's exact undo (user ruling 2026-11-17: master's model): the inverse taken,
                # and proved by patching it back to the live bytes.
                import patch_helptext
                if patch_helptext.is_our_patch(p):
                    # Still OUR patched help text: the uninstall's restore of it failed (said above). Unfinished work,
                    # never "a file you changed" (audit-l M1): the full marked record stays, and the re-run finishes.
                    failed += 1
                    return
                if patch_helptext.refused_status(p):
                    LAST_HELP_EDITED.append(rel)          # text of ours left as it is: the verdict names it
                    return
            if sha != files[rel] and rel.lower() != _REMOVED_EDITED:
                LAST_KEPT.append(rel)                     # the player changed it: theirs now
                return
            safe_fs.unlink_entitled(p)                    # a read-only copy too (audit-j MEDIUM-3)
            removed += 1
        except tu.ThinkerError:
            failed += 1
            LAST_LINKED += 1
            ix.say(f"  WARNING: {shown} goes through a link, so it was left alone.")    # user-approved wording 2026-11-15
            return
        except OSError as e:
            failed += 1
            ix.say(f"  WARNING: could not remove {shown}: {e}")    # user-approved: the existing mod-file warning, reused
            return
        parent = p.parent
        while parent != game_dir and game_dir in parent.parents:
            dirs.add(parent)
            parent = parent.parent

    # What Thinker needs to start goes last -- thinker.exe (the launcher), thinker.dll, then thinker.ini, which its
    # DllMain refuses to start without -- each only when everything before it went: a failure anywhere leaves Thinker
    # startable, and the re-run finishes (audit-g LOW-6: a locked file left thinker.dll without its launcher; audit-i
    # MEDIUM-1: thinker.ini went with the other files, and a later failure left exe and dll that could not start).
    # thinker.ini after thinker.exe, not before it: a locked thinker.exe (L07 / L08) then leaves the whole set.
    exe_rel = next((r for r in files if r.lower() == "thinker.exe"), None)
    ini_rel = next((r for r in files if r.lower() == _REMOVED_EDITED), None)
    group = [r for r in (exe_rel, dll_rel, ini_rel) if r is not None]
    for rel in sorted(r for r in files if r not in group):
        one(rel)
    for last in group:
        if not failed:
            one(last)
    for d in sorted(dirs, key=lambda x: len(x.parts), reverse=True):
        safe_fs.rmdir(game_dir, d)                        # only when empty (a kept file keeps it), never a link
    # After ANY failure the FULL record written above stays, with its mark -- exactly what a Ctrl-C leaves (audit-j
    # MEDIUM-2: a record cut down to the files left made the removed ones invisible). So the next uninstall finishes
    # the removal, and a setup or update run offers to put the missing files back (missing_release_files) and then
    # clears the mark (settle_install_record).
    if not failed:
        clear_install_record(game_dir)
    # Said only when nothing recorded is left in place but the files the player changed (named below the list): never
    # while thinker.ini or another file of the release stays (audit-j MEDIUM-2, K04).
    if not failed and removed and all(_live_sha(game_dir.joinpath(*r.split("/"))) is None
                                      or (r in LAST_KEPT and r.lower() != _REMOVED_EDITED) or r in LAST_HELP_EDITED
                                      for r in files):
        ix.say(f"  removed Thinker Mod {st.ts_display(rec['pin'])}")          # user-approved wording 2026-11-15
    return removed, failed


def removal_plan(game_dir: Path) -> tuple:
    """What remove_thinker would read and change, without changing anything: ([(path, modes)], [the links -- junctions
    or symlinks -- on the way to a file it would remove, each once]) -- preflight.PROBE_MODES joined by "+", "entitled" where it deletes (unlink_entitled: read-only or not).
    Mirrors remove_thinker branch by branch; keep the two together. Runs BEFORE the uninstall's Datalinks restore, so
    a smac_mod help text that is exactly a patch of ours counts as the stock text the restore will put back (it is
    then removed like any unchanged file). Never raises."""
    game_dir = Path(game_dir)
    out, links = [], []
    try:
        rec = read_install_record(game_dir)
        if rec is None:
            return out, links
        files = rec["files"]
        dll_rel = next((r for r in files if r.lower() == "thinker.dll"), None)
        out.append((game_dir / "thinker.exe", "read"))
        live = _live_sha(game_dir / "thinker.dll")
        if live is not None and (dll_rel is None or live != files[dll_rel]):
            return out, links
        remainder = _ini_remainder(game_dir, rec)
        if not (_removal_ready(game_dir, rec) or remainder):
            return out, links
        ini_too = remainder or _ini_removable(game_dir, rec) or bool(
            rec.get("remove") and _rel_of(files, _REMOVED_EDITED) and dll_rel)
        import hashlib
        import patch_helptext
        for rel in sorted(files):
            p = game_dir.joinpath(*rel.split("/"))
            try:
                tu.refuse_reparse(game_dir, rel)
            except tu.ThinkerError:
                # the link itself, once however many files lie behind it (user-approved 2026-11-17, L3)
                import safe_fs
                link = safe_fs.first_link(game_dir, p) or p
                lrel = link.relative_to(game_dir).as_posix()
                if lrel not in links:
                    links.append(lrel)
                continue
            if not p.is_file():
                continue
            out.append((p, "read"))
            if rel.lower() == _REMOVED_EDITED and not ini_too:
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue                                  # listed for reading: the check refuses it
            if rel in tu.DATALINKS:
                original = patch_helptext.our_original(p)
                if original is not None:
                    data = original                       # what the restore leaves there
            if hashlib.sha256(data).hexdigest() != files[rel] and rel.lower() != _REMOVED_EDITED:
                continue                                  # the player's now: left
            out.append((p, "delete+entitled"))
    except Exception:  # noqa: BLE001 - a plan never stops the uninstall; the run says what it meets
        pass
    return out, links


def settle_install_record(game_dir: Path) -> None:
    """After a successful install or update run (audit-f H2): an earlier "Also uninstall" that did not finish is
    over -- this run put Longevity Vaccine back. The mark goes; the record keeps the files still in place as they were
    put there and the ones the removal took (missing_release_files offers those back, audit-j MEDIUM-2), drops the ones
    the player changed since, and goes altogether unless our thinker.dll is in place (Thinker is not ours to remove)."""
    game_dir = Path(game_dir)
    if PENDING_FORGET:
        _forget_missing(game_dir, list(PENDING_FORGET))   # "Only update", now that the run succeeded (audit-l L3)
        del PENDING_FORGET[:]
    rec = read_install_record(game_dir)
    if rec is None or not rec.get("remove"):
        return
    if _ini_remainder(game_dir, rec):
        return        # Thinker is gone but our locked thinker.ini: the next uninstall finishes it (audit-k LOW-2, M08)
    keep = {}
    for rel, sha in rec["files"].items():
        live = _live_sha(game_dir.joinpath(*rel.split("/")))
        if live is None:
            keep[rel] = sha       # removed part-way: kept, so missing_release_files offers it back (audit-j MEDIUM-2)
        else:
            # In place: as written, or changed by the player -- an edited file stays too, so a later "Also uninstall"
            # names it under "Left in place:" (audit-l L2: it was dropped, then left unlisted).
            keep[rel] = live if rel.lower() == _REMOVED_EDITED else sha
    if _live_sha(game_dir / "thinker.dll") is not None and any(r.lower() == "thinker.dll" for r in keep):
        write_install_record(game_dir, rec["pin"], keep)
    else:
        clear_install_record(game_dir)


def kept_lines() -> list:
    """The uninstall's "Left in place" lines for the release files remove_thinker left because the player changed
    them. User-approved wording 2026-11-15 (the list's own column format)."""
    out = []
    for rel in LAST_KEPT:
        if rel.lower() == _REMOVED_EDITED and LAST_KEPT_INI_EDITED == [False]:
            # Our own thinker.ini, as written, kept because Thinker Mod was not removed whole (audit-k LOW-2).
            # User-approved wording 2026-11-16 (the list's column format).
            out.append(f"{rel.replace('/', chr(92)):<20} - Thinker Mod's settings file")
        else:
            out.append(f"{rel.replace('/', chr(92)):<20} - a Thinker Mod file you changed, so it was kept")
    return out


def _readable_dll(game_dir: Path):
    """The folder's thinker.dll, or None -- absent, or held by another program (audit-m #7: then nothing about it can
    be said, and the uninstall says nothing rather than crash)."""
    try:
        return st.read_dll(Path(game_dir) / "thinker.dll")
    except st.DllUnreadable:
        return None


def dll_unreadable(game_dir: Path) -> bool:
    """thinker.dll is there and cannot be read (held by another program)."""
    try:
        st.read_dll(Path(game_dir) / "thinker.dll")
        return False
    except st.DllUnreadable:
        return True


def record_waits_for_dll(game_dir: Path) -> bool:
    """Is the install record to be kept for a later uninstall because thinker.dll cannot be read now (audit-m #7)? Only
    a record that is acted on at all (read_install_record): an invalid one is inert and goes regardless (audit of
    356c8f8, L5)."""
    return read_install_record(game_dir) is not None and dll_unreadable(game_dir)


def uninstall_lines(game_dir: Path, also: bool = False) -> list:
    """`also`: the player chose "Also uninstall Thinker Mod" -- never followed by "stays installed" (audit-f M3: a
    locked thinker.dll said so under UNINSTALL INCOMPLETE)."""
    sets = tu.older_backups(game_dir)
    if not sets:
        if also:
            return []
        # No backup set (a first install by this installer replaces nothing): the stays line alone (execution audit
        # 2026-11-15: uninstalling a folder where the installer had added Thinker never said Thinker stays).
        dll = _readable_dll(game_dir)
        if dll is None:
            return []
        run = st.run_name(dll.label)
        return [f"{run[0].upper() + run[1:]} stays installed and works without Longevity Vaccine."]
    stamp = lambda p: re.search(r"(\d{8}-\d{6})(-\d+)?$", p.name).group(0) if re.search(r"\d{8}-\d{6}(-\d+)?$", p.name) else ""
    sets = sorted(sets, key=stamp)
    newest = sets[-1]
    if len(sets) == 1:
        head = f"LongevityMods\\backups\\{newest.name} - copies of your Thinker Mod files from before Longevity Vaccine changed Thinker Mod."
    else:
        head = (f"LongevityMods\\backups\\thinker-* - copies of your Thinker Mod files from before each time Longevity "
                f"Vaccine changed Thinker Mod ({len(sets)} sets; the newest is LongevityMods\\backups\\{newest.name}).")
    dll = _readable_dll(game_dir)
    if dll is not None and not also:
        head += f" {st.run_name(dll.label)[0].upper() + st.run_name(dll.label)[1:]} stays installed and works without Longevity Vaccine."
    return [head]
