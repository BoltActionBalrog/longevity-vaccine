"""The Thinker step: plan, back up, swap, journal, recover (design sections 6 and 7).

Rules (user rulings 2026-11-14):
* every file of the pinned release is backed up, then overwritten; missing ones are added;
* files the release does not contain are left alone; the root alphax.txt is always kept;
* thinker.ini is merged and thinker_user.ini commented in place (thinker_ini);
* each run backs up into its OWN timestamped set, LongevityMods\\backups\\thinker-<label>-<stamp>;
  no set is ever deleted automatically, except this run's own set when nothing it holds was
  replaced (a rolled-back F5);
* every write goes through <file>.longevity-tmp + rename; thinker.dll is renamed LAST;
* a path component that is a reparse point (junction, symlink) is refused;
* the journal LongevityMods\\thinker-journal.json exists exactly while a change is unfinished.

The exe and runtime steps of a Longevity route belong to the caller (install.py); this module
records their hashes in the journal so recovery can tell the old exe from the new one.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

import thinker_ini
import thinker_state as st

JOURNAL = Path("LongevityMods") / "thinker-journal.json"
BACKUPS = Path("LongevityMods") / "backups"
TMP = ".longevity-tmp"
DATALINKS = ("smac_mod/helpx.txt", "smac_mod/conceptsx.txt")
BAK = ".longevity.bak"


class ThinkerError(Exception):
    """A Thinker step failure. `kind` is the verdict: F3 (locked), F5 (rolled back), F6 (could not
    put every file back), REFUSED (a reparse point or a bad path)."""

    def __init__(self, kind: str, message: str, path: str = "", files=()):
        super().__init__(message)
        self.kind = kind
        self.path = path
        self.files = list(files)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_reparse(p: Path) -> bool:
    """A junction or symlink -- one rule with safe_fs.is_link (audit-g LOW-9: not every reparse point)."""
    import safe_fs
    return safe_fs.is_link(p)


def refuse_reparse(game_dir: Path, rel: str) -> None:
    """Raise when any component between the game folder and `rel` is a junction or symlink."""
    cur = Path(game_dir)
    for part in Path(rel).parts:
        cur = cur / part
        if _is_reparse(cur):
            raise ThinkerError("REFUSED", f"{Path(rel).as_posix()} goes through a link", rel)


# ---------------------------------------------------------------- the plan

@dataclass
class Action:
    rel: str                       # posix path under the game folder
    kind: str                      # add | replace | keep | rewrite
    data: bytes = None             # the bytes to write (add / replace / rewrite)
    old_sha: str = ""              # the file before (empty when absent)
    new_sha: str = ""


@dataclass
class Plan:
    game_dir: Path
    pin_id: str
    ts: str
    from_label: st.Label
    actions: list = field(default_factory=list)
    ini: object = None              # thinker_ini.MergeResult or None
    user_ini: object = None         # thinker_ini.CommentResult or None
    kept_alphax: bool = False
    #: The Datalinks help texts (DATALINKS) replaced whose live file is exactly a patch of ours -- unpatch_bytes takes
    #: our text back out and patching the result again gives the live bytes (patch_helptext.our_original; audit-l H1,
    #: on master's exact-undo model): only for these is the text without ours the player's original, and the set gets
    #: that. Any other live file is the player's own text, backed up as it is. No .longevity.bak is read or written
    #: (user ruling 2026-11-17: master's model); an earlier version's leftover one is patch_helptext's to drop.
    datalinks_ours: list = field(default_factory=list)

    def changes(self) -> list:
        return [a for a in self.actions if a.kind in ("add", "replace", "rewrite")]


def plan(game_dir: Path, pin_id: str, staged: dict, *, known, old_stock, ts: str,
         from_label: st.Label) -> Plan:
    """What the step will do; reads the folder, writes nothing. `staged` = {rel: Path} of the
    verified release files (thinker_source.extract)."""
    game_dir = Path(game_dir)
    p = Plan(game_dir, pin_id, ts, from_label)
    known_b = {k.encode() if isinstance(k, str) else k for k in known}
    for rel in sorted(staged):
        refuse_reparse(game_dir, rel)
        dest = game_dir.joinpath(*rel.split("/"))
        new = Path(staged[rel]).read_bytes()
        old_sha = sha256(dest) if dest.is_file() else ""
        if rel == "alphax.txt" and dest.exists():
            p.actions.append(Action(rel, "keep", old_sha=old_sha))
            p.kept_alphax = old_sha != hashlib.sha256(new).hexdigest()
            continue
        if rel == "thinker.ini" and dest.is_file():
            p.ini = thinker_ini.merge(dest.read_bytes(), new, known_b, ts, old_stock=old_stock)
            new = p.ini.data
        new_sha = hashlib.sha256(new).hexdigest()
        if old_sha == new_sha:
            p.actions.append(Action(rel, "keep", old_sha=old_sha, new_sha=new_sha))
            continue
        p.actions.append(Action(rel, "replace" if old_sha else "add", new, old_sha, new_sha))
        if rel in DATALINKS and old_sha:
            import patch_helptext
            if patch_helptext.is_our_patch(dest):
                p.datalinks_ours.append(rel)
    user = game_dir / "thinker_user.ini"
    if user.is_file():
        refuse_reparse(game_dir, "thinker_user.ini")
        p.user_ini = thinker_ini.comment_unknown(user.read_bytes(), known_b)
        if p.user_ini.changed:
            p.actions.append(Action("thinker_user.ini", "rewrite", p.user_ini.data, sha256(user),
                                    hashlib.sha256(p.user_ini.data).hexdigest()))
    refuse_reparse(game_dir, BACKUPS.as_posix())
    return p


def _locked(path: Path) -> bool:
    """A share-deny probe: can the file be opened for writing with no sharing? (Windows only.)"""
    if os.name != "nt" or not path.exists():
        return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    import safe_fs
    a = safe_fs.file_attrs(path)
    # GENERIC_WRITE fails on a READ-ONLY file whoever has it open: that is not a lock (audit-l M2). An open with no
    # sharing at all still fails while another program holds the file, read access or not.
    access = 0x80000000 if a is not None and a & 0x1 else 0x40000000 | 0x80000000
    h = k32.CreateFileW(str(path), access, 0, None, 3, 0x80, None)
    if h in (None, wintypes.HANDLE(-1).value):
        return True
    k32.CloseHandle(h)
    return False


def probe_locks(p: Plan, tries: int = 3, wait: float = 3.0):
    """The first file to be replaced that stays locked over `tries` probes (F3), else None."""
    targets = [p.game_dir.joinpath(*a.rel.split("/")) for a in p.changes() if a.old_sha]
    for t in sorted(targets, key=lambda x: x.name != "thinker.dll"):
        for i in range(tries):
            if not _locked(t):
                break
            if i + 1 < tries:
                time.sleep(wait)
        else:
            return t
    return None


# ---------------------------------------------------------------- backups

def backup_label(label: st.Label) -> str:
    return label.version if label.kind == st.VERSION else ("develop" if label.kind == st.DEVELOP else "other")


def new_backup_dir(game_dir: Path, label: st.Label, now: float = None) -> Path:
    """This run's own set: thinker-<label>-<yyyymmdd-hhmmss>, with -2, -3 ... if that name exists.
    Never an existing folder."""
    base = Path(game_dir) / BACKUPS
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now if now is not None else time.time()))
    name = f"thinker-{backup_label(label)}-{stamp}"
    cand, n = base / name, 1
    while cand.exists():
        n += 1
        cand = base / f"{name}-{n}"
    return cand


def rollback_dir(bdir: Path) -> Path:
    """Beside a set, never in it: the copies only an undo needs -- the live Datalinks help texts as Longevity Vaccine
    patched them (audit-k LOW-5). The set itself holds the player's ORIGINAL bytes, so a
    hand restore of it gives byte-for-byte their build. Not named thinker-*: never counted as a backup set."""
    return Path(bdir).with_name("rollback-" + Path(bdir).name)


def drop_rollback(bdir: Path) -> None:
    """The change is finished or undone: the undo-only copies go (never through a link)."""
    import safe_fs
    safe_fs.rmtree(Path(bdir).parents[2], rollback_dir(bdir))


def _copy_for(bdir: Path, rel: str) -> Path:
    """Where an undo reads `rel` back from: the rollback copy when there is one, else the set's."""
    rb = rollback_dir(bdir).joinpath(*rel.split("/"))
    return rb if rb.is_file() else Path(bdir).joinpath(*rel.split("/"))


def older_backups(game_dir: Path, mine: Path = None) -> list:
    base = Path(game_dir) / BACKUPS
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith("thinker-")
                  and (mine is None or p.resolve() != Path(mine).resolve()))


# ---------------------------------------------------------------- the journal

def journal_path(game_dir: Path) -> Path:
    return Path(game_dir) / JOURNAL


def _write_journal(game_dir: Path, doc: dict) -> None:
    jp = journal_path(game_dir)
    jp.parent.mkdir(parents=True, exist_ok=True)
    tmp = jp.with_name(jp.name + TMP)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, jp)


def read_journal(game_dir: Path):
    try:
        return json.loads(journal_path(game_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear_journal(game_dir: Path) -> None:
    import safe_fs
    try:
        safe_fs.unlink(Path(game_dir), journal_path(game_dir))     # never through a junctioned LongevityMods
    except FileNotFoundError:
        pass


def set_step(game_dir: Path, step: int) -> None:
    doc = read_journal(game_dir)
    if doc is not None:
        doc["step"] = step
        _write_journal(game_dir, doc)


# ---------------------------------------------------------------- commit

@dataclass
class Report:
    backup_dir: Path
    replaced: int = 0
    added: int = 0
    kept_or_merged: int = 0
    older_backups: int = 0


def _write_tmp(dest: Path, data: bytes) -> Path:
    tmp = dest.with_name(dest.name + TMP)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.unlink()                                  # a leftover, or a link planted at the tmp name
    except FileNotFoundError:
        pass
    with open(tmp, "xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return tmp


def commit(p: Plan, *, route: str = "thinker", exe: dict = None, now: float = None,
           _replace=os.replace, repair: bool = False, whole: bool = False) -> Report:
    """Steps 1-3 of section 7: journal, backups, tmp files, renames (thinker.dll last).
    On failure everything is put back (ThinkerError F5) or, when that fails too, F6.
    `exe` = {"current": md5, "staged": md5} on a Longevity route, recorded for recovery. `repair`: only missing
    release files are put back (W9); the journal says so, and a recovery of it is no new version (audit-h L2).
    `whole`: an update, downgrade or swap of a Thinker the player had -- the set also gets a copy of every file the
    plan keeps as it is (thinker.exe, the player's alphax.txt, any identical file), so it holds the player's WHOLE
    previous Thinker and can put it back on its own (audit-j MEDIUM-1, user-approved 2026-11-16). Those copies are
    never in the journal: undo and recovery restore only what the change replaced."""
    g = p.game_dir
    bdir = new_backup_dir(g, p.from_label, now)
    acts = sorted(p.changes(), key=lambda a: a.rel == "thinker.dll")
    import safe_fs
    jacts = [{"rel": a.rel, "kind": a.kind, "old": a.old_sha, "new": a.new_sha,
              "attrs": safe_fs.file_attrs(g.joinpath(*a.rel.split("/"))) if a.old_sha else None} for a in acts]
    attrs = {j["rel"]: j["attrs"] for j in jacts}
    doc = {"version": 1, "route": route, "to": p.pin_id, "backup": bdir.name, "step": 1,
           "exe": exe or {}, "actions": jacts, "at": int(time.time())}
    if repair:
        doc["repair"] = True
    done = []                     # rels renamed into place
    created = False
    try:
        _write_journal(g, doc)
        bdir.mkdir(parents=True)
        created = True
        for a in acts:            # back up first, all of them
            src = g.joinpath(*a.rel.split("/"))
            if a.old_sha:
                data = src.read_bytes()
                if a.rel in p.datalinks_ours:
                    # Exactly a patch of ours: the undo copy goes beside the set, and the set gets the player's
                    # ORIGINAL text -- ours taken back out, exactly (audit-k LOW-5, on master's exact-undo model). Any
                    # other text is the player's own: the set keeps it as it is, byte for byte (audit-l H1).
                    import patch_helptext
                    try:
                        original = patch_helptext.unpatch_bytes(data, patch_helptext.spec_for(src))
                    except patch_helptext.Refused:
                        # Changed since the plan, so it no longer inverts: the player's text now, backed up as it is
                        # like any other (audit of 356c8f8, L2: the Refused escaped with the journal at step 1).
                        original = None
                    if original is not None:
                        rb = rollback_dir(bdir).joinpath(*a.rel.split("/"))
                        rb.parent.mkdir(parents=True, exist_ok=True)
                        rb.write_bytes(data)
                        data = original
                b = bdir.joinpath(*a.rel.split("/"))
                b.parent.mkdir(parents=True, exist_ok=True)
                b.write_bytes(data)
                safe_fs.set_file_attrs(b, attrs.get(a.rel))       # a hand restore keeps them (audit-l M2 / L1)
        if whole:
            for a in p.actions:
                if a.kind == "keep" and a.old_sha:
                    b = bdir.joinpath(*a.rel.split("/"))
                    b.parent.mkdir(parents=True, exist_ok=True)
                    b.write_bytes(g.joinpath(*a.rel.split("/")).read_bytes())
                    safe_fs.set_file_attrs(b, safe_fs.file_attrs(g.joinpath(*a.rel.split("/"))))
        tmps = {a.rel: _write_tmp(g.joinpath(*a.rel.split("/")), a.data) for a in acts}
        order = [a.rel for a in acts if a.rel != "thinker.dll"]
        order = order + [a.rel for a in acts if a.rel == "thinker.dll"]
        doc["step"] = 2                               # backups and tmp files complete: renaming
        _write_journal(g, doc)
        for rel in order:
            dest = g.joinpath(*rel.split("/"))
            if attrs.get(rel):
                safe_fs.clear_read_only(dest)             # the player agreed to its replacement (audit-l M2)
            _replace(tmps[rel], dest)
            done.append(rel)
            safe_fs.set_file_attrs(dest, attrs.get(rel))  # the new file keeps the old one's attributes (audit-l L1)
        doc["step"] = 3
        _write_journal(g, doc)
    except OSError as e:
        failed = _rollback(p, bdir, done, acts, attrs)
        _cleanup_tmps(g, acts)
        if failed:
            raise ThinkerError("F6", f"could not put every file back: {e}", files=failed) from e
        if created:
            _remove_own_set(bdir)
        clear_journal(g)
        raise ThinkerError("F5", str(e), path=getattr(e, "filename", "") or "") from e
    r = Report(bdir)
    r.replaced = sum(1 for a in acts if a.kind in ("replace", "rewrite"))
    r.added = sum(1 for a in acts if a.kind == "add")
    r.kept_or_merged = sum(1 for a in p.actions if a.kind == "keep")
    r.older_backups = len(older_backups(g, bdir))
    return r


def finish(game_dir: Path) -> None:
    """Section 7 step 6: the change is complete; the journal goes (before packs), and the undo-only copies with it."""
    doc = validated_journal(Path(game_dir), read_journal(Path(game_dir)))
    if doc is not None:
        drop_rollback(Path(game_dir) / BACKUPS / doc["backup"])
    clear_journal(game_dir)


def _rollback(p: Plan, bdir: Path, done: list, acts: list, attrs: dict = None) -> list:
    """Put back every renamed file from this run's set, with its attributes; returns the rels that could not be."""
    import safe_fs
    attrs = attrs or {}
    failed = []
    old = {a.rel: a.old_sha for a in acts}
    for rel in reversed(done):
        dest = p.game_dir.joinpath(*rel.split("/"))
        try:
            if old.get(rel):
                src = _copy_for(bdir, rel)
                tmp = _write_tmp(dest, src.read_bytes())
                safe_fs.clear_read_only(dest)
                os.replace(tmp, dest)
                safe_fs.set_file_attrs(dest, attrs.get(rel))
            else:
                dest.unlink()                             # it was added
        except OSError:
            failed.append(rel)
    return failed


def _cleanup_tmps(g: Path, acts) -> None:
    for rel in [a.rel for a in acts]:
        t = g.joinpath(*rel.split("/"))
        t = t.with_name(t.name + TMP)
        try:
            t.unlink()
        except OSError:
            pass


def _remove_own_set(bdir: Path) -> None:
    """A rolled-back run's own set holds nothing that was replaced: it goes (it is not an older set)."""
    import safe_fs
    drop_rollback(bdir)
    safe_fs.rmtree(Path(bdir).parents[2], Path(bdir))     # <game>\LongevityMods\backups\<set>; never through a link


# ---------------------------------------------------------------- recovery

FINISHED, UNDONE, LOST = "finished", "undone", "lost"


def _matches(g: Path, acts, side: str, skip=()) -> bool:
    for a in acts:
        if a["rel"] in skip:
            continue
        want = a["new"] if side == "new" else a["old"]
        f = g.joinpath(*a["rel"].split("/"))
        have = sha256(f) if f.is_file() else ""
        if have != want:
            return False
    return True


_BACKUP_RE = __import__("re").compile(r"thinker-[A-Za-z0-9.]{1,24}-\d{8}-\d{6}(-\d{1,4})?")
_SHA_RE = __import__("re").compile(r"[0-9a-f]{64}")
#: The only files a journal may name: the pinned release's own paths (they pass thinker_source.check_path) and
#: thinker_user.ini. (No Datalinks .longevity.bak any more: master's exact-undo model, user ruling 2026-11-17.)
_EXTRA_RELS = {"thinker_user.ini"}

LAST_RECOVERED = None             # the journal's "to" when the last recover() FINISHED a change (for CL)
LAST_BACKUP = None                # the backup set of the change the last recover() FINISHED or UNDID
LAST_ACTIONS = None               # that change's journal actions (the install record of a FINISHED one)
LAST_REPAIR = False               # that change was a repair (W9): no new version, no changelog offer


def _valid_rel(rel) -> bool:
    if not isinstance(rel, str):
        return False
    if rel in _EXTRA_RELS:
        return True
    import thinker_source
    try:
        return thinker_source.check_path(rel) == rel
    except thinker_source.SourceError:
        return False


def validated_journal(game_dir: Path, doc):
    """The journal's actions and backup folder when EVERY path in it is one the step could have written,
    under the game folder and through no link; else None (a corrupt or planted journal: never acted on)."""
    if not isinstance(doc, dict):
        return None
    acts, backup, step = doc.get("actions"), doc.get("backup"), doc.get("step", 0)
    if not isinstance(acts, list) or not isinstance(backup, str) or not _BACKUP_RE.fullmatch(backup):
        return None
    if not isinstance(step, int) or isinstance(step, bool):
        return None
    clean = []
    for a in acts:
        if not isinstance(a, dict) or not _valid_rel(a.get("rel")):
            return None
        old, new = a.get("old"), a.get("new")
        if not (isinstance(old, str) and (old == "" or _SHA_RE.fullmatch(old))):
            return None
        if not (isinstance(new, str) and _SHA_RE.fullmatch(new)):
            return None
        try:
            refuse_reparse(game_dir, a["rel"])
        except ThinkerError:
            return None
        at = a.get("attrs")
        clean.append({"rel": a["rel"], "old": old, "new": new,
                      "attrs": at if isinstance(at, int) and not isinstance(at, bool) and 0 <= at < 0x100 else None})
    try:
        refuse_reparse(game_dir, (BACKUPS / backup).as_posix())
    except ThinkerError:
        return None
    exe = doc.get("exe") if isinstance(doc.get("exe"), dict) else {}
    exe = {k: v for k, v in exe.items() if k in ("current", "staged") and isinstance(v, str)}
    route = doc.get("route") if doc.get("route") in ("thinker", "longevity", "fresh") else "thinker"
    to = doc.get("to") if isinstance(doc.get("to"), str) else ""
    return {"actions": clean, "backup": backup, "step": step, "exe": exe, "route": route, "to": to,
            "repair": doc.get("repair") is True}


def recover(game_dir: Path, live_exe_md5: str = None):
    """Run at every installer entry. Returns None (no journal), FINISHED, UNDONE or LOST (section 7).
    The journal never outlives one call, and a journal that fails validation is never acted on."""
    global LAST_RECOVERED, LAST_BACKUP, LAST_ACTIONS, LAST_REPAIR
    LAST_RECOVERED = LAST_BACKUP = LAST_ACTIONS = None
    LAST_REPAIR = False
    g = Path(game_dir)
    if not journal_path(g).exists():
        return None
    doc = validated_journal(g, read_journal(g))
    if doc is None:
        clear_journal(g)
        return LOST
    acts = doc["actions"]
    bdir = g / BACKUPS / doc["backup"]
    LAST_BACKUP = bdir
    LAST_ACTIONS = acts
    LAST_REPAIR = doc["repair"]
    try:
        # From step 5 the live Datalinks files are re-patched by the installer: they no longer equal the stock
        # text the journal recorded, and that is not a sign of an unfinished swap (round-7 review, D1).
        skip = set(DATALINKS) if doc["step"] >= 5 else set()
        exe = doc.get("exe") or {}
        if doc.get("route") == "longevity" and exe:
            # The exe decides, never the Thinker hashes alone (round-7 review, M1): a crash between the Thinker
            # swap and the exe rename leaves a complete NEW Thinker beside the OLD exe.
            cur, staged = exe.get("current"), exe.get("staged")
            if live_exe_md5 is None or live_exe_md5 not in (cur, staged):
                return LOST
            forward = live_exe_md5 == staged and (cur != staged or doc.get("step", 0) >= 4)
            if forward and _matches(g, acts, "new", skip):
                LAST_RECOVERED = doc["to"]
                return FINISHED
            if not forward and _matches(g, acts, "old"):
                return UNDONE
        elif _matches(g, acts, "new", skip):
            LAST_RECOVERED = doc["to"]
            return FINISHED
        elif _matches(g, acts, "old"):
            return UNDONE
        else:
            forward = doc.get("step", 0) >= 2        # before step 2 nothing was renamed: undo
            if forward:
                r = _roll(g, acts, bdir, True)
                r = r if r != LOST else _roll(g, acts, bdir, False)
                if r == FINISHED:
                    LAST_RECOVERED = doc["to"]
                return r
        r = _roll(g, acts, bdir, forward)
        if r == FINISHED:
            LAST_RECOVERED = doc["to"]
        return r
    except OSError:
        return LOST
    finally:
        for a in acts:                               # leftover tmp files (validated paths only)
            t = g.joinpath(*a["rel"].split("/"))
            try:
                t.with_name(t.name + TMP).unlink()
            except OSError:
                pass
        clear_journal(g)


def undo(game_dir: Path) -> str:
    """Put this run's swap back from its backup set, whatever is in place now (a later step failed with
    the OLD exe still there). Returns UNDONE, or LOST when a file could not be restored."""
    g = Path(game_dir)
    doc = validated_journal(g, read_journal(g))
    if doc is None:
        return LOST
    try:
        r = _roll(g, doc["actions"], g / BACKUPS / doc["backup"], False)
        if r == UNDONE:
            drop_rollback(g / BACKUPS / doc["backup"])
        return r
    finally:
        for a in doc["actions"]:
            t = g.joinpath(*a["rel"].split("/"))
            try:
                t.with_name(t.name + TMP).unlink()
            except OSError:
                pass
        clear_journal(g)


def _roll(g: Path, acts, bdir: Path, forward: bool):
    """Forward: every file not yet in place is renamed in from its leftover tmp file, which must
    verify; backward: every file is restored from this run's set, which must verify. Anything
    that cannot be matched leaves the folder as it is: LOST. Each file keeps the attributes the journal recorded
    (audit-l M2 / L1); read-only never stops the rename."""
    import safe_fs
    if forward:
        for a in acts:
            dest = g.joinpath(*a["rel"].split("/"))
            have = sha256(dest) if dest.is_file() else ""
            if have == a["new"]:
                continue
            tmp = dest.with_name(dest.name + TMP)
            if not tmp.is_file() or sha256(tmp) != a["new"]:
                return LOST
            try:
                safe_fs.clear_read_only(dest)
                os.replace(tmp, dest)
                safe_fs.set_file_attrs(dest, a.get("attrs"))
            except OSError:
                return LOST
        return FINISHED
    ok = True
    for a in acts:
        dest = g.joinpath(*a["rel"].split("/"))
        try:
            if a["old"]:
                if dest.is_file() and sha256(dest) == a["old"]:
                    continue          # never replaced (stopped before its rename -- or its backup): nothing to put back
                src = _copy_for(bdir, a["rel"])
                if not src.is_file() or sha256(src) != a["old"]:
                    ok = False
                    continue
                tmp = _write_tmp(dest, src.read_bytes())
                safe_fs.clear_read_only(dest)
                os.replace(tmp, dest)
                safe_fs.set_file_attrs(dest, a.get("attrs"))
            elif dest.is_file():
                if sha256(dest) == a["new"]:
                    dest.unlink()                         # the file this change added, as it added it
                else:
                    # Not what this change added (a Thinker the player put back by hand after a crash, say:
                    # verification of f076f34 deleted it with no backup): left alone, and not UNDONE.
                    ok = False
        except OSError:
            ok = False
    return UNDONE if ok else LOST
