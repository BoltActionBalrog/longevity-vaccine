"""Preflight: acquire and verify EVERY input before a single game byte is modified.

THE ORDERING REQUIREMENT (user, 2026-09-21): "make sure that everything needed for the
installation is available (such as the network collection manifest, etc.) before actually
modifying on-disk bytes, such as restoring the backup."

So the run splits cleanly in two:

    PREFLIGHT  -- fetch, verify, dry-run, check space/locks/permissions. May populate
                  <game>\\LongevityMods\\staging. Touches NO game file, no exe, no .bak, no ini.
    COMMIT     -- transact.py, which patches a temp copy and atomically swaps it in.

Every check returns a reason instead of raising, so a failure reports ALL of what is wrong rather
than only the first thing -- a user who has to re-run four times to discover four problems will
give up. `Preflight.ok` is the gate; `Preflight.blockers` is what to tell them.

A check that cannot be performed is NOT a pass. `unknown` counts as a blocker unless it is
explicitly advisory, because "we could not tell" and "it is fine" are different answers.
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap   # noqa: E402
import fetch                 # noqa: E402
import manifest as mf        # noqa: E402
import version as ver        # noqa: E402

#: Advisory checks report but do not block.
ADVISORY = "advisory"


class Check:
    __slots__ = ("name", "ok", "detail", "advisory")

    def __init__(self, name: str, ok: bool, detail: str = "", advisory: bool = False):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.advisory = advisory

    def __repr__(self):  # pragma: no cover
        return f"<{self.name}: {'ok' if self.ok else 'FAIL'} {self.detail}>"


class Preflight:
    def __init__(self):
        self.checks: list[Check] = []
        self.staged: dict = {}      # module -> verified archive in staging (a tuple of parts for a split pack)
        self.doc: dict = None                  # the verified manifest
        self.decision = None
        self.wanted: list[str] = []            # modules to fetch: explicit, else the stale ones
        self.patch_log: str = ""               # the patcher's own narration (dry run)

    def add(self, name, ok, detail="", advisory=False) -> bool:
        self.checks.append(Check(name, ok, detail, advisory))
        return ok

    @property
    def blockers(self) -> list:
        return [c for c in self.checks if not c.ok and not c.advisory]

    @property
    def warnings(self) -> list:
        return [c for c in self.checks if not c.ok and c.advisory]

    @property
    def ok(self) -> bool:
        return not self.blockers

    def report(self, say=print) -> None:
        for c in self.checks:
            mark = "ok  " if c.ok else ("warn" if c.advisory else "FAIL")
            say(f"  [{mark}] {c.name}{(': ' + c.detail) if c.detail else ''}")


# ---------------------------------------------------------------- individual checks

def check_game_dir(pf: Preflight, game_dir: Path) -> bool:
    """Returns False when nothing further should be attempted in this directory."""
    game_dir = Path(game_dir)
    if not pf.add("game directory", game_dir.is_dir(), str(game_dir)):
        return False
    # Writability, proven by writing -- an ACL check is not the same question, and discovering a
    # permissions problem mid-write is exactly what this phase exists to prevent.
    #
    # The probe name is unique per run: a fixed name truncated and deleted any pre-existing file
    # of that name, and an exclusive-create refuses to touch someone else's file at all.
    probe = game_dir / f".longevity-probe-{os.getpid()}-{os.urandom(4).hex()}"
    try:
        with probe.open("xb") as f:      # "x" = fail if it exists; never clobber
            f.write(b"x")
    except OSError as e:
        pf.add("game directory is writable", False,
               f"{e}. Run the installer as administrator, or move the game out of "
               f"Program Files")
        return False
    pf.add("game directory is writable", True)
    try:
        probe.unlink()
    except OSError:
        # Cleanup failure is not the same question as writability, and reporting it as "not
        # writable" sent the user to a remedy that could not help.
        pf.add("write probe cleaned up", False,
               f"a stray {probe.name} was left in the game directory; it is safe to delete",
               advisory=True)
    return True


def check_target_and_backup(pf: Preflight, target: Path, table: dict,
                            receipt_target_id: str = None):
    """The exe must be present and its .bak must be a base we recognise AND still support."""
    target = Path(target)
    if not pf.add("target executable", target.is_file(), str(target)):
        return None
    beside = ap.folder_files(target.parent)   # thinker.dll beside the exe = the PRACX + Thinker overlay

    bak = target.with_suffix(target.suffix + ".bak")
    if not bak.is_file():
        # No backup yet = a first install from a clean base. The clean base is then the exe itself.
        try:
            md5 = hashlib.md5(target.read_bytes()).hexdigest()
        except OSError as e:
            pf.add("read the target executable", False, str(e))
            return None
        try:
            spec = ap.resolve_target(md5, table, launch_only=True, present_files=beside,
                                     exe_name=target.name)
        except ap.UnsupportedBase as e:
            pf.add("supported configuration", False, str(e))
            return None
        pf.add("clean base (no .bak yet)", True, f"{spec.id} ({spec.label})")
        return spec

    try:
        bak_md5 = hashlib.md5(bak.read_bytes()).hexdigest()
        live_md5 = hashlib.md5(target.read_bytes()).hexdigest()
    except OSError as e:
        pf.add("read the target and its backup", False, str(e))
        return None
    try:
        spec = ap.resolve_target(bak_md5, table, launch_only=True, present_files=beside,
                                 exe_name=target.name)
    except ap.UnsupportedBase as e:
        pf.add("backup is a supported clean base", False, str(e))
        return None
    pf.add("backup is a supported clean base", True, f"{spec.id} ({spec.label})")

    # THE LIVE EXE MUST BE ACCOUNTED FOR TOO. Hashing only the .bak meant a foreign live binary --
    # a newer PRACX, a Thinker build, anything the player swapped in -- passed preflight and was
    # then overwritten by a build patched from the .bak, destroying it with no backup of ITS
    # bytes. The live file must be either the clean base (not yet patched) or a build we produced:
    # this configuration's, or a sibling configuration's on the same base (PRACX and PRACX +
    # Thinker share one base -- a Thinker build in a folder Thinker was removed from is still ours,
    # not "a binary we did not make"; audit 2026-10-28).
    # ... and a build of ours means ANY release's, not only this one's: patched_md5 changes with
    # every release, so the build an earlier release left on the player's disk is in the target's
    # known_patched history (TargetSpec.builds). Without it every in-game update from one release
    # to the next was refused here as "a binary we did not make".
    known = ({spec.base_md5} | spec.builds) - {None}
    siblings = ap.builds_on_base(table, spec.base_md5, exclude=spec.id)
    if live_md5 in known:
        pf.add("live executable is ours or the clean base", True,
               "clean" if live_md5 == spec.base_md5 else
               "already patched" if live_md5 == spec.patched_md5 else "patched by an earlier release")
    elif live_md5 in siblings:
        pf.add("live executable is ours or the clean base", True,
               "patched for another configuration of the same base")
    else:
        pf.add("live executable is ours or the clean base", False,
               f"{target.name} is {live_md5}, which is neither the clean base ({spec.base_md5}) "
               f"nor a build this installer produced ({spec.patched_md5}). Refusing to replace a "
               f"binary we did not make: back it up and restore the original first.")

    # Crossing targets silently is how you patch a base you never verified: someone who installs
    # Thinker after our mod has a different base underneath the same file name.
    if receipt_target_id and receipt_target_id != spec.id:
        pf.add("target has not changed since install", False,
               f"installed as {receipt_target_id!r}, now looks like {spec.id!r}. Run the installer "
               f"again (a normal install, not --update): it re-patches from the backup for the "
               f"configuration this folder now holds")
    elif receipt_target_id:
        pf.add("target has not changed since install", True, spec.id)
    return spec


def check_not_locked(pf: Preflight, game_dir: Path, game_pid: int = None,
                     target: Path = None, extra: list = None) -> None:
    """Everything we are about to replace is held open while the game runs; discover that now."""
    if game_pid:
        alive = _pid_alive(game_pid)
        pf.add("spawning game has exited", not alive,
               f"pid {game_pid} is still running: close Alpha Centauri" if alive else "")

    # THE TARGET FIRST: it is the file the commit replaces, and it was not checked at all -- so a
    # locked exe surfaced only at commit, after the whole download and staging phase.
    names = []
    if target:
        names.append(Path(target).name)
    names += [p.name for p in sorted(Path(game_dir).glob("*.dll"))
              if p.name.lower().startswith(("uimod", "av", "sw", "prax"))]
    names += list(extra or [])

    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        p = Path(game_dir) / name
        if not p.exists():
            continue
        try:
            with p.open("r+b"):
                pass
            pf.add(f"{name} is not in use", True)
        except OSError as e:
            pf.add(f"{name} is not in use", False,
                   f"{e}. Close the game (or whatever is holding it) and re-run")


#: How a step will use a file, for probe(). Each mode checks what that step's OWN call needs, as measured against
#: every kind of holder (test_uninstall_plan's matrix test holds each mode to its call, holder by holder):
#:   read      -- open(path, "rb") (an md5, read_bytes): Python's open shares read and write, NEVER delete, so a
#:                program holding the file with delete access makes it fail though a share-all open passes
#:   source    -- copied FROM by shutil.copy2 (CopyFile2 on Python 3.12, which shares everything; Python's open on
#:                the 3.8 runtime); not read-only, hidden or system: copy2 passes those bits on to the copy (a
#:                read-only exe a later step must move or delete; a hidden terranx.exe)
#:   overwrite -- written in place (copy2 / write_bytes ONTO it): a write open sharing read and write; not hidden or
#:                system (a file opened to be replaced whole refuses both); not mapped by another program (truncating
#:                a mapped file fails)
#:   rename    -- moved to a FREE name: delete access, sharing everything (a read-only file, a running exe allow it)
#:   delete    -- deleted (os.remove): as rename, and not read-only, and not a running program or a loaded DLL
#:   replace   -- another file moved ONTO its name (os.replace): NOTHING may have it open or mapped -- not even a
#:                program that shares everything, or one that only reads its attributes -- and not read-only
#:   profile   -- a key removed by the Win32 profile API (Alpha Centauri.ini): its own open (read and write, sharing
#:                everything); not read-only; not mapped by another program
#: Audits 2026-11-16: one share-all open per file passed a file Python then could not read (D1) and a name another
#: file could not be moved onto (D2), and refused a file that is only deleted while another program read it sharing
#: delete (D5). A hidden file could not be written (D4).
PROBE_MODES = ("read", "source", "overwrite", "rename", "delete", "replace", "profile")
#: A flag beside the modes, not a call of its own: the run deletes this file with safe_fs.unlink_entitled, which
#: clears the read-only bit first (a file the run has already decided is ours to delete: user ruling 2026-11-17,
#: D3(b); audit-j MEDIUM-3). Read-only then refuses no "delete"; everything else still refuses.
ENTITLED = "entitled"

_SHARE_R, _SHARE_W, _SHARE_D = 0x1, 0x2, 0x4
_SHARE_ALL = _SHARE_R | _SHARE_W | _SHARE_D
_GENERIC_READ, _GENERIC_WRITE, _DELETE, _READ_ATTRIBUTES = 0x80000000, 0x40000000, 0x00010000, 0x80
_IN_USE = "The process cannot access the file because it is being used by another process."


def probe(path: Path, modes) -> str:
    """'' when `path` can be used right now as every mode in `modes` needs; else the reason it cannot. Only opens
    and queries it, and closes it at once -- nothing is read, written or moved. A file that is not there blocks
    nothing: whatever was going to use it has nothing to do."""
    unknown = set(modes) - set(PROBE_MODES) - {ENTITLED}
    if unknown:                                 # never skipped quietly: an unknown mode would pass unchecked
        raise ValueError(f"unknown probe mode(s): {', '.join(sorted(unknown))}")
    if not os.path.lexists(path):
        return ""
    entitled = ENTITLED in modes
    for mode in PROBE_MODES:                    # a fixed order: the same file always gives the same reason
        if mode in modes:
            reason = _probe_mode(Path(path), mode, entitled)
            if reason:
                return reason
    return ""


def change_blocker(path: Path, rename_only: bool = False) -> str:
    """probe() for a file the caller will delete, or only move to a free name (`rename_only`)."""
    return probe(path, {"rename"} if rename_only else {"delete"})


def _attributes(path: Path) -> int:
    try:
        return getattr(os.stat(path), "st_file_attributes", 0)
    except (OSError, TypeError, ValueError, OverflowError):
        return 0


def _probe_mode(path: Path, mode: str, entitled: bool = False) -> str:
    try:
        import ctypes  # noqa: F401
        k32 = _kernel32()
    except (ImportError, OSError, AttributeError):
        k32 = None
    if k32 is None:                             # off Windows (never the installer's case): plain opens
        try:
            with open(path, "rb" if mode in ("read", "source") else "r+b"):
                return ""
        except FileNotFoundError:
            return ""
        except OSError as e:
            return e.strerror or str(e)
    if mode in ("source", "overwrite", "delete", "replace", "profile") and read_only_reason(path) \
            and not (entitled and mode == "delete"):
        return read_only_reason(path)
    # Reads and writes also meet byte-range locks, which no open sees (audit 2026-11-16, F1: a locked set-up record
    # passed, then read as "absent"): a read needs no other program's exclusive lock on any byte, a write no lock.
    if mode == "read":
        return _open_reason(k32, path, _GENERIC_READ, _SHARE_R | _SHARE_W, lock="shared")
    import _winapi
    copyfile2 = hasattr(_winapi, "CopyFile2")   # mirrors shutil.copy2's own branch (3.12: CopyFile2; 3.8: open())
    # hidden / system: a write onto the file refuses them; and CopyFile2 carries them onto the copy (3.8's copy2
    # copies the read-only bit alone, so a hidden source is fine there)
    if (mode == "overwrite" or (mode == "source" and copyfile2)) and _attributes(path) & 0x6:
        return "the file is hidden or a system file"
    if mode == "source":
        share = _SHARE_ALL if copyfile2 else _SHARE_R | _SHARE_W
        return _open_reason(k32, path, _GENERIC_READ, share, lock="shared")
    if mode == "rename":
        return _open_reason(k32, path, _DELETE, _SHARE_ALL)
    if mode == "overwrite":
        return (_open_reason(k32, path, _GENERIC_WRITE, _SHARE_R | _SHARE_W, lock="exclusive")
                or _mapped_reason(k32, path))
    if mode == "profile":
        return (_open_reason(k32, path, _GENERIC_READ | _GENERIC_WRITE, _SHARE_ALL, lock="exclusive")
                or _mapped_reason(k32, path))
    if mode == "delete":
        return _open_reason(k32, path, _DELETE, _SHARE_ALL) or _image_reason(k32, path, entitled)
    if mode == "replace":
        return _held_reason(k32, path)
    raise ValueError(f"unknown probe mode {mode!r}")


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                             wintypes.LPVOID]
    return k32


def _open(k32, path: Path, access: int, share: int):
    """(handle or None, Win32 error)."""
    import ctypes
    from ctypes import wintypes
    h = k32.CreateFileW(str(path), access, share, None, 3, 0, None)        # OPEN_EXISTING
    if h is None or h == wintypes.HANDLE(-1).value:
        return None, ctypes.get_last_error()
    return h, 0


def _open_reason(k32, path: Path, access: int, share: int, lock: str = None) -> str:
    """'' when `path` opens with this access and sharing -- and, with `lock` ("shared" / "exclusive"), when that lock
    on every byte is free (taken and let go at once). A brief open or lock by another program (a virus scanner,
    Explorer reading an icon) is looked at twice more before the file is called in use (ERROR_SHARING_VIOLATION /
    ERROR_LOCK_VIOLATION pass in a moment; audit 2026-11-15); a running game or a lasting handle stays refused."""
    import ctypes
    for attempt in range(3):
        h, err = _open(k32, path, access, share)
        if h is not None:
            try:
                err = _lock_error(k32, h, lock) if lock else 0
            finally:
                k32.CloseHandle(h)
            if not err:
                return ""
        if err in (2, 3):                       # ERROR_FILE_NOT_FOUND / PATH_NOT_FOUND: gone since the listing
            return ""
        if err not in (32, 33) or attempt == 2:
            return ctypes.FormatError(err).strip() or f"error {err}"
        import time
        time.sleep(0.25)
    return ""


def _lock_error(k32, h, kind: str) -> int:
    """0 when a `kind` lock on the whole file (every offset) can be taken through `h` right now; it is let go at
    once. Else the Win32 error (ERROR_LOCK_VIOLATION: another handle holds a conflicting lock on some byte)."""
    import ctypes
    from ctypes import wintypes

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [("internal", ctypes.c_void_p), ("internal_high", ctypes.c_void_p), ("offset", wintypes.DWORD),
                    ("offset_high", wintypes.DWORD), ("event", wintypes.HANDLE)]
    k32.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(OVERLAPPED)]
    k32.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(OVERLAPPED)]
    ov = OVERLAPPED()
    flags = 0x1 | (0x2 if kind == "exclusive" else 0)       # LOCKFILE_FAIL_IMMEDIATELY [| EXCLUSIVE_LOCK]
    if not k32.LockFileEx(h, flags, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(ov)):
        return ctypes.get_last_error() or 33
    k32.UnlockFileEx(h, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(ov))
    return 0


def _users(k32, path: Path):
    """The ids of the processes that have `path` open or mapped (a handle of any access, a loaded DLL, a running exe,
    a mapped view), not counting the query's own handle; None when Windows cannot say (then the caller falls back)."""
    import ctypes
    from ctypes import wintypes
    h, err = _open(k32, path, _READ_ATTRIBUTES, _SHARE_ALL)
    if h is None:
        return [] if err in (2, 3) else None

    class IOSB(ctypes.Structure):
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_void_p)]
    try:
        ntdll = ctypes.WinDLL("ntdll")
        size = 4096
        while size <= 1 << 20:
            buf = ctypes.create_string_buffer(size)
            st = ntdll.NtQueryInformationFile(wintypes.HANDLE(h), ctypes.byref(IOSB()), buf, size, 47) & 0xFFFFFFFF
            if st == 0x80000005 or st == 0xC0000004:            # BUFFER_OVERFLOW / INFO_LENGTH_MISMATCH
                size *= 4
                continue
            if st != 0:                         # FileProcessIdsUsingFileInformation not supported here
                return None
            word = ctypes.sizeof(ctypes.c_size_t)
            n = ctypes.c_ulong.from_buffer(buf, 0).value
            return [ctypes.c_size_t.from_buffer(buf, word * (1 + i)).value for i in range(n)]
        return None
    except (OSError, AttributeError, ValueError):
        return None
    finally:
        k32.CloseHandle(h)


def _held_reason(k32, path: Path) -> str:
    """For a name another file is moved onto: '' only when nothing at all has `path` open or mapped (looked at
    twice more, as _open_reason does). Where Windows cannot list them, an open allowing no sharing stands in for it
    (it misses a holder of the attributes alone)."""
    for attempt in range(3):
        users = _users(k32, path)
        if users is None:
            return _open_reason(k32, path, _GENERIC_READ | _GENERIC_WRITE | _DELETE, 0)
        if not users:
            return ""
        if attempt < 2:
            import time
            time.sleep(0.25)
    return _IN_USE


def _mapped_reason(k32, path: Path) -> str:
    """For a file truncated in place, once a write open passed: a program with a view of it mapped makes the
    truncation fail, whether or not it also holds a handle (audit 2026-11-16, F2: a handle beside the view hid it).
    Each process that uses the file is looked through for such a view (_maps_it); one that cannot be looked at may
    have one: refused (the safe side), and said so. Where Windows cannot list the file's users at all, every process
    this one can look through is (audit 2026-11-16: that case passed unchecked). Looked at twice more, as
    _open_reason does."""
    found = ""
    for attempt in range(3):
        users = _users(k32, path)
        if users is None:
            found = _maps_it(k32, path, _all_processes(k32), every=True)
        else:
            found = _maps_it(k32, path, users) if users else ""
        if not found:
            return ""
        if attempt < 2:
            import time
            time.sleep(0.25)
    if found == "unknown":
        # audit 2026-11-16, F2b: a plain holder the installer cannot look into (another user's or a protected
        # process; a 64-bit one from the 32-bit runtime) is not said to map the file
        return ("another program has the file open, and the installer cannot check whether it has the file mapped "
                "into its memory (which would make the change fail)")
    return "another program has the file mapped into its memory"


def _all_processes(k32) -> list:
    """Every process id on the machine (for when Windows cannot say which use a file)."""
    import ctypes
    from ctypes import wintypes
    enum = getattr(k32, "K32EnumProcesses", None) or ctypes.WinDLL("psapi").EnumProcesses
    enum.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    n = 1024
    while n <= 1 << 20:
        ids, got = (wintypes.DWORD * n)(), wintypes.DWORD(0)
        if not enum(ids, ctypes.sizeof(ids), ctypes.byref(got)):
            return []
        if got.value < ctypes.sizeof(ids):
            return list(ids[:got.value // ctypes.sizeof(wintypes.DWORD)])
        n *= 4
    return []


def _identity(k32, path: str):
    """(NT device, file identity) of `path`: the device is the leading "\\Device\\<name>" of its NT path, and the
    identity is the same for every hard link of one file -- FileIdInfo's 128-bit id where the volume has one (ReFS
    ids do not fit the older 64-bit index), else the volume serial and 64-bit index. None when it cannot be opened."""
    import ctypes
    from ctypes import wintypes

    class INFO(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD)] + [(f"t{i}", wintypes.DWORD) for i in range(6)] + [
            ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD), ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    class FILE_ID_INFO(ctypes.Structure):
        _fields_ = [("volume", ctypes.c_ulonglong), ("id", ctypes.c_ubyte * 16)]
    h, err = _open(k32, path, _READ_ATTRIBUTES, _SHARE_ALL)
    if h is None:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        k32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        n = k32.GetFinalPathNameByHandleW(h, buf, len(buf), 0x2)           # VOLUME_NAME_NT
        if not n or n >= len(buf):
            return None
        parts = buf.value.split("\\")
        device = "\\".join(parts[:3]).lower()                               # "\device\harddiskvolume3"
        fid = FILE_ID_INFO()
        query = getattr(k32, "GetFileInformationByHandleEx", None)
        if query is not None:
            query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            if query(h, 18, ctypes.byref(fid), ctypes.sizeof(fid)):          # FileIdInfo (Windows 8 and later)
                return device, ("id", fid.volume, bytes(fid.id))
        k32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(INFO)]
        info = INFO()
        if not k32.GetFileInformationByHandle(h, ctypes.byref(info)):
            return None
        return device, ("index", info.volume, info.index_high, info.index_low)
    finally:
        k32.CloseHandle(h)


def _maps_it(k32, path: Path, users: list, every: bool = False) -> str:
    """"mapped" when one of the processes `users` has a view of `path` mapped (MEM_MAPPED: a running exe or a loaded
    DLL is MEM_IMAGE, which the write open already refused); "unknown" when one cannot be looked through (another
    user's or a protected process; a 64-bit one seen from this 32-bit runtime), or has a view on the file's volume
    whose name no longer opens (the link it was mapped through was deleted since); else ''.

    A view is matched by the file's identity, not its name: Windows names a view by the hard link it was mapped
    through (audit 2026-11-16, F2a). Only views on the file's own device are looked at (hard links never cross
    volumes): a snapshot copy with the same ids, or a network name that could stall, is never opened. With `every`
    (users are every process on the machine, not known users of the file), a process or name that cannot be looked
    at is passed over rather than counted -- almost every machine has some."""
    import ctypes
    from ctypes import wintypes
    me = _identity(k32, str(path))
    if me is None:
        return "unknown"
    device, target = me
    buf = ctypes.create_unicode_buffer(32768)
    ids = {}

    def view_of(nt_name: str):
        """True: our file; False: another file; None: on our volume, but the name does not open."""
        if not nt_name.lower().startswith(device + "\\"):
            return False
        if nt_name not in ids:
            got = _identity(k32, "\\\\?\\GLOBALROOT" + nt_name)
            ids[nt_name] = None if got is None else got[1] == target
        return ids[nt_name]

    class MBI(ctypes.Structure):
        _fields_ = [("base", ctypes.c_void_p), ("allocation_base", ctypes.c_void_p), ("allocation_protect",
                    wintypes.DWORD), ("size", ctypes.c_size_t), ("state", wintypes.DWORD),
                    ("protect", wintypes.DWORD), ("type", wintypes.DWORD)]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
    k32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    mapped_name = getattr(k32, "K32GetMappedFileNameW", None) or ctypes.WinDLL("psapi").GetMappedFileNameW
    mapped_name.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    me_wow = wintypes.BOOL(0)
    k32.IsWow64Process(k32.GetCurrentProcess(), ctypes.byref(me_wow))
    limit = 1 << (8 * ctypes.sizeof(ctypes.c_void_p))
    unknown = False
    for pid in users:
        ph = k32.OpenProcess(0x0400 | 0x0010, False, pid)     # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if not ph:
            unknown = unknown or not every
            continue
        try:
            if me_wow.value:
                it_wow = wintypes.BOOL(0)
                if not k32.IsWow64Process(ph, ctypes.byref(it_wow)) or not it_wow.value:
                    unknown = unknown or not every
                    continue
            addr, mbi = 0, MBI()
            while addr < limit and k32.VirtualQueryEx(ph, addr, ctypes.byref(mbi), ctypes.sizeof(mbi)):
                base = mbi.base or 0
                if mbi.type == 0x40000 and base == (mbi.allocation_base or 0):     # MEM_MAPPED, a view's start
                    n = mapped_name(ph, base, buf, len(buf))
                    if n:
                        ours = view_of(buf.value)
                        if ours:
                            return "mapped"
                        if ours is None and not every:
                            unknown = True
                if not mbi.size:
                    break
                addr = base + mbi.size
        finally:
            k32.CloseHandle(ph)
    return "unknown" if unknown else ""


def _image_reason(k32, path: Path, entitled: bool = False) -> str:
    """For a file deleted, once delete access passed: a running exe or a loaded DLL cannot be deleted. Their image
    refuses a write open -- as does a program reading the file without sharing write, which does not stop the
    delete. Only a program file can be running, so a file that does not start "MZ" is not refused for it; a program
    file whose write open fails is (the safe side). A read-only file the run deletes anyway (`entitled`) refuses the
    write open for its bit alone: then only a program file some process uses is refused (Windows' list of the file's
    users counts a loaded DLL and a running exe; where it cannot say, the safe side)."""
    import ctypes
    from ctypes import wintypes
    if not _open_reason(k32, path, _GENERIC_WRITE, _SHARE_ALL):
        return ""
    if entitled and read_only_reason(path) and _users(k32, path) == []:
        return ""
    h, err = _open(k32, path, _GENERIC_READ, _SHARE_ALL)
    if h is None:
        return _IN_USE                          # cannot tell what it is: refused
    try:
        buf, got = ctypes.create_string_buffer(2), wintypes.DWORD(0)
        ok = k32.ReadFile(h, buf, 2, ctypes.byref(got), None)
        return _IN_USE if not ok or buf.raw[:got.value] == b"MZ" else ""
    finally:
        k32.CloseHandle(h)


def read_only_reason(path: Path) -> str:
    """'' unless `path` carries the read-only attribute. Never raises."""
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError, OverflowError):
        return ""
    ro = getattr(st, "st_file_attributes", 0) & 0x1 if os.name == "nt" else not (st.st_mode & 0o200)
    return "the file is read-only" if ro else ""


def _pid_alive(pid: int) -> bool:
    """True if the process is running. Fails SAFE: if we cannot tell, we say it is still alive.

    The old version returned False whenever the query failed -- including ERROR_ACCESS_DENIED,
    which a live elevated process produces. "We could not look" became "the game has exited",
    which is the dangerous direction: the installer would proceed to replace files the game still
    holds open.
    """
    try:
        import ctypes
        from ctypes import wintypes
        # use_last_error=True is REQUIRED for ctypes.get_last_error() to return anything. Reading
        # it off the default `ctypes.windll` handle always gave 0, so "no such process" (87) was
        # never recognised and EVERY dead PID was reported as still running -- which made the
        # bootstrap's wait-for-parent spin the full timeout and then refuse to run.
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            err = ctypes.get_last_error()
            # 87 = ERROR_INVALID_PARAMETER: no such process. Anything else (notably 5,
            # ERROR_ACCESS_DENIED) means we were refused, which tells us nothing about whether
            # it is running -- so we assume it is.
            return err != 87
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True                            # could not tell -> assume alive
            return code.value == 259                   # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        return True                                    # could not tell -> assume alive


def check_space(pf: Preflight, game_dir: Path, need: int) -> None:
    free = fetch.free_space(Path(game_dir))
    pf.add("free disk space", free >= need,
           f"{fetch.human_size(free)} free, {fetch.human_size(need)} needed")


def check_manifest(pf: Preflight, raw: bytes, sig: str, installed_version: str,
                   target_id: str, public_key_hex: str = None,
                   allow_env: bool = False, installed_modules: dict = None,
                   labels: dict = None) -> None:
    try:
        doc = mf.load_verified(raw, sig, public_key_hex, allow_env=allow_env)
    except mf.ManifestError as e:
        pf.add("manifest signature", False, str(e))
        return
    pf.add("manifest signature", True)
    pf.doc = doc

    d = mf.decide(doc, installed_version, target_id, installed_modules=installed_modules)
    pf.decision = d
    labels = labels or {}
    if d.action == mf.MANUAL:
        # ONLY the compiled-in message and URL. `d.detail` is manifest-derived and is a developer
        # diagnostic -- interpolating it here put attacker-choosable prose inside our own "see the
        # official link" sentence.
        pf.add("update is available automatically", False, f"{d.message} (see {d.url})")
    elif d.action == mf.NOTHING:
        # Not a [warn]: being current is the healthy state, and a warning on every idle run
        # read as something the player might have to act on.
        pf.add("Longevity Vaccine is up to date", True,
               f"v{installed_version}" if ver.is_valid(installed_version)
               else (d.detail or "already current"))
    else:
        # Say WHAT is offered. "update offered: 0.1.0" on a pack-only update named the base
        # version the player already had.
        parts = []
        base_offered = not ver.is_valid(installed_version) \
            or ver.is_newer(d.version, installed_version)
        if base_offered:
            parts.append(f"Longevity Vaccine v{d.version}")
        mods = doc.get("modules") if isinstance(doc.get("modules"), dict) else {}
        for m in d.modules:
            info = mods.get(m)
            offered = info.get("version") if isinstance(info, dict) else None
            offered = ver.normalise(offered) if isinstance(offered, str) and ver.is_valid(offered) \
                else "?"
            have = (installed_modules or {}).get(m)
            have = ver.normalise(have) if isinstance(have, str) and ver.is_valid(have) else "?"
            parts.append(f"{labels.get(m, m)} v{have} -> v{offered}")
        pf.add("update offered", True, ", ".join(parts) or d.version)
        min_from = doc.get("min_upgradable_from")
        # Only meaningful when the BASE is offered; on a pack-only update it was noise.
        if base_offered and isinstance(min_from, str) and ver.is_valid(min_from):
            if ver.is_valid(installed_version):
                pf.add("this version can be updated directly",
                       ver.at_least(installed_version, min_from),
                       f"v{installed_version} (oldest supported v{min_from})")
            else:
                # Skipping this silently meant an unknown installed version passed the gate with
                # no trace. Say so instead: it is a repair, not a verified upgrade path.
                pf.add("upgrade path supported", False,
                       f"the installed version is unknown, so the {min_from} minimum cannot be "
                       f"checked, so this is treated as a repair", advisory=True)


#: Modules that are required whatever the manifest says about them. The core patch and the
#: installer itself ship together as `base`, so there is no "optional" reading of it.
ALWAYS_REQUIRED = ("base",)


def staging_name(url, module: str) -> str:
    """The file name a module archive is staged under. Derived from the URL so a resumed
    download is found again -- but taken APART, never trusted whole. `Path(url).name` let a
    signed manifest name `C:evil.zip` (drive-relative: escapes staging), `x.zip:ads` (an alternate
    data stream) or `..`. Same whitelist as bootstrap._download_new_payload."""
    import urllib.parse
    try:
        raw = Path(urllib.parse.urlparse(str(url)).path).name if isinstance(url, str) else ""
    except (ValueError, TypeError):
        raw = ""
    safe = "".join(c for c in raw if (c.isascii() and c.isalnum()) or c in "._-").lstrip(".")
    stem = safe.split(".")[0].upper()
    if not safe or stem in _RESERVED or safe.lower() in ("manifest.json", "manifest.json.sig"):
        safe = f"{module}.zip"      # a device name (CON.zip opens the console) or our own files
    # Each module in its own folder: two modules whose URLs end in the same name (or a pack named
    # like the base) can no longer overwrite each other's download.
    return f"{module}/{safe}"


#: Windows device names, reserved at every path level with or without an extension.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} \
    | {f"LPT{i}" for i in range(1, 10)}


def check_archives(pf: Preflight, doc: dict, staging: Path, wanted: list,
                   allow_file: bool = False, explicit: set = (), labels: dict = None) -> None:
    """Download and verify every wanted module into staging. sha256 from the SIGNED manifest.

    A module the manifest marks OPTIONAL is advisory: a broken extras pack must not block the
    core patch. Only a required module is a blocker -- plus a module the player asked for by
    name (`explicit`) that the manifest does not offer at all: "UPDATE COMPLETE" with no pack
    was the answer to `--modules portraits-hd` before that pack existed.
    """
    modules = doc.get("modules")
    modules = modules if isinstance(modules, dict) else {}
    labels = labels or {}
    for name in wanted:
        info = modules.get(name)
        # `base` is required by DEFINITION, not by the manifest saying so. Deriving optionality
        # purely from the entry made a manifest that omits `base` -- the case where we have no
        # idea what to install -- pass the preflight as an advisory note.
        opt = name not in ALWAYS_REQUIRED \
            and not (isinstance(info, dict) and info.get("required"))
        label = labels.get(name, name)
        if not isinstance(info, dict):
            if name in explicit and name not in ALWAYS_REQUIRED:
                pf.add(f"{label}: not released yet", False, "nothing was downloaded")
            else:
                pf.add(f"module {name} declared", False, "not in the manifest", advisory=opt)
            continue
        offered = info.get("version")
        shown = f"{label} v{ver.normalise(offered)}" \
            if isinstance(offered, str) and ver.is_valid(offered) else label
        st = Path(staging)
        game_root = st.parent.parent if st.parent.name.lower() == "longevitymods" else None
        try:
            parts = mf.module_parts(info)
        except mf.PartsError as e:
            pf.add(f"module {name} declared", False, f"manifest entry is malformed ({fetch.clean(e)})",
                   advisory=opt)
            continue
        if parts is not None:
            # A SPLIT pack (manifest.module_parts): byte slices of one archive, each verified against its own signed
            # sha256, then read in place as that archive (fetch.ConcatReader) -- never joined on disk.
            # Named by the part's own signed digest and its index, never by a name taken from the URL: Windows reads
            # `a.001` and `a.001.` as one file, and one part's `<name>.part` could be another's final name. The digest
            # is what makes a leftover safe: a download stopped part-way under one release is never resumed against
            # ANOTHER release's part (that spliced a new tail onto an old prefix, then threw up to a whole part away
            # when the hash failed). module_parts has already checked each sha256 is 64 hex digits.
            dests = [Path(staging) / name / f"{name}.{p['sha256'][:16]}.{i:03d}" for i, p in enumerate(parts, 1)]
            _sweep_stale_parts(Path(staging) / name, name, dests, game_root or Path(staging))
            try:
                fetch.download_parts(parts, dests, label=label, allow_file=allow_file, root=game_root)
            except fetch.FetchError as e:
                pf.add(f"{shown} download", False, str(e), advisory=opt)
                continue
            pf.add(f"{shown} downloaded and verified", True, fetch.human_size(info["size"]))
            staged = tuple(dests)
        else:
            url, digest, size = info.get("url"), info.get("sha256"), info.get("size")
            if not isinstance(url, str) or not isinstance(digest, str) or not url or not digest:
                pf.add(f"module {name} declared", False, "manifest entry lacks a url or sha256",
                       advisory=opt)
                continue
            dest = Path(staging) / staging_name(url, name)
            try:
                fetch.download(url, dest, sha256=digest, size=size,
                               mirror=info.get("mirror"), allow_file=allow_file, label=label, root=game_root)
            except fetch.FetchError as e:
                pf.add(f"{shown} download", False, str(e), advisory=opt)
                continue
            pf.add(f"{shown} downloaded and verified", True, fetch.human_size(dest.stat().st_size))
            staged = dest
        try:
            with open_staged(staged) as src:
                if not zipfile.is_zipfile(src):
                    pf.add(f"{shown} is a readable archive", False, "not a zip", advisory=opt)
                    continue
                with zipfile.ZipFile(src) as z:
                    bad = z.testzip()
            if bad:
                pf.add(f"{shown} is a readable archive", False,
                       f"corrupt entry {fetch.clean(bad, 60)}", advisory=opt)
                continue
        except (zipfile.BadZipFile, OSError, EOFError) as e:
            pf.add(f"{shown} is a readable archive", False, fetch.clean(e), advisory=opt)
            continue
        pf.add(f"{shown} is a readable archive", True)
        pf.staged[name] = staged


def _sweep_stale_parts(folder: Path, name: str, keep: list, root: Path) -> None:
    """Delete the split-pack parts in `folder` that this release does not name: another release's (another digest),
    an earlier client's index-only names (`<module>.NNN`), and their `.part` downloads. They are never resumed into
    this release's parts, and at up to a part's size each they would otherwise hold the disk the free-space check
    counted on until a later success cleared staging. Only names of exactly these shapes are touched, never through
    a link (safe_fs), and a file that cannot be removed is left: it is never read."""
    import re
    import safe_fs
    if not folder.is_dir() or safe_fs.link_on_path(Path(root), folder):
        return
    shape = re.compile(rf"{re.escape(name)}(\.[0-9a-f]{{16}})?\.\d{{3}}(\.part)?", re.IGNORECASE)
    wanted = {d.name.lower() for d in keep} | {d.name.lower() + ".part" for d in keep}
    for f in folder.iterdir():
        try:
            if shape.fullmatch(f.name) and f.name.lower() not in wanted and f.is_file() and not f.is_symlink():
                f.unlink()
        except OSError:
            pass


def open_staged(staged):
    """A staged module archive opened for reading: one file, or a split pack's parts read as the one archive they
    were cut from (a tuple of paths in order; check_archives). The caller closes it (`with`)."""
    if isinstance(staged, (tuple, list)):
        return fetch.ConcatReader(list(staged))
    return open(staged, "rb")


def check_patch_plan(pf: Preflight, target: Path, patches: Path, spec) -> None:
    """Dry-run the real patcher. Its default IS dry-run, so this costs nothing but time and it
    verifies every site's original_bytes and every cave's padding against the actual binary."""
    if spec is None:
        pf.add("patch plan verifies", False, "no base resolved")
        return
    bak = Path(target).with_suffix(Path(target).suffix + ".bak")
    src = bak if bak.is_file() else Path(target)
    # The patcher narrates every site and cave (~3,700 lines). That is a log, not something to
    # scroll past on an idle check -- and "Target: terranx_PRACX.exe.bak" in it read as the
    # game running from its backup. Captured; shown only if the plan is refused.
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = ap.apply_patches(src, Path(patches), do_apply=False, spec=spec)
    except Exception as e:  # noqa: BLE001 - a patcher crash is a blocker, not a traceback
        pf.add("patch plan verifies", False, f"{type(e).__name__}: {e}")
        pf.patch_log = buf.getvalue()
        return
    pf.patch_log = buf.getvalue()
    if rc != 0:
        print(pf.patch_log)
    pf.add("patch plan verifies", rc == 0,
           "" if rc == 0 else f"the patcher refused the plan (code {rc}); see the output above")


def run(*, game_dir: Path, target: Path, patches: Path, table: dict,
        manifest_raw: bytes = None, manifest_sig: str = None,
        installed_version: str = ver.UNKNOWN, receipt_target_id: str = None,
        wanted_modules: list = None, game_pid: int = None,
        public_key_hex: str = None, allow_file: bool = False,
        min_free_bytes: int = 1 << 30, require_manifest: bool = False,
        installed_modules: dict = None, labels: dict = None,
        only_listed: bool = False) -> Preflight:
    """Run every check. Returns a Preflight; NOTHING in the game directory is modified.

    This function does not raise. A check that blows up is itself a blocker -- returning a
    Preflight with a reason is the contract, and letting an exception escape would send a
    read-only game directory or a malformed manifest field to the crash handler instead.

    Which modules get fetched (`pf.wanted`): `wanted_modules` is the EXPLICIT list (`--modules`)
    and is fetched as given; when it is None the set is the decision's stale modules, computed
    from `installed_modules` (name -> receipt version). "Every installed module" is deliberately
    not an option any more -- it re-downloaded a current 1.3 GB pack on every base release.
    `only_listed` (the game's --only-listed): `wanted_modules` is the WHOLE set -- the packs the
    game's popups named and the player accepted -- and no other stale module is added.
    """
    pf = Preflight()
    pf.spec = None
    try:
        writable = check_game_dir(pf, game_dir)
        spec = check_target_and_backup(pf, target, table, receipt_target_id)
        pf.spec = spec
        check_not_locked(pf, game_dir, game_pid, target=target)

        if manifest_raw is None:
            # A caller that wanted an update but could not fetch the manifest must NOT get a
            # clean preflight -- "everything it needs" includes the manifest.
            if require_manifest:
                pf.add("update manifest available", False,
                       "no manifest was supplied, so nothing about this update can be verified")
            check_space(pf, game_dir, min_free_bytes)
        else:
            # allow_env rides on allow_file: both mean "this manifest came from a local
            # file", which is the only situation where a test key may override the
            # compiled-in one.
            check_manifest(pf, manifest_raw, manifest_sig or "", installed_version,
                           spec.id if spec else None, public_key_hex,
                           allow_env=allow_file, installed_modules=installed_modules,
                           labels=labels)
            if pf.doc:
                # Explicit names PLUS the stale installed ones -- not instead of them. With
                # "instead", `--modules portraits-hd` announced a stale movies-hd as "already
                # current" and left it behind.
                pf.wanted = [str(n) for n in (wanted_modules or [])]
                if pf.decision is not None and not only_listed:
                    pf.wanted += [n for n in pf.decision.modules if n not in pf.wanted]
                elif pf.decision is not None:
                    mods_ = pf.doc.get("modules") if isinstance(pf.doc.get("modules"), dict) else {}
                    for n in pf.decision.modules:
                        if n in pf.wanted:
                            continue
                        info = mods_.get(n)
                        v = info.get("version") if isinstance(info, dict) else None
                        v = ver.normalise(v) if isinstance(v, str) and ver.is_valid(v) else "?"
                        have = (installed_modules or {}).get(n)
                        have = ver.normalise(have) if isinstance(have, str) and ver.is_valid(have) \
                            else "?"
                        # A pass: the game's list is the player's answer. Said, so a pack that
                        # stays behind is never a mystery -- and how to take it anyway.
                        pf.add(f"{(labels or {}).get(n, n)} v{v}: not part of this update", True,
                               f"stays at v{have} (not in the list the game passed); "
                               f"run-install.bat --update --modules {n} installs it")
                need = pf.doc.get("min_free_bytes")
                need = need if mf.size_ok(need) else min_free_bytes
                # Add up what we are actually about to download; a fixed constant cannot notice
                # that the wanted module set does not fit.
                mods = pf.doc.get("modules")
                mods = mods if isinstance(mods, dict) else {}
                for name in pf.wanted:
                    info = mods.get(name)
                    sz = info.get("size") if isinstance(info, dict) else None
                    if mf.size_ok(sz) and sz > 0:
                        need += sz * 2        # the archive plus what it expands to
                check_space(pf, game_dir, need)
                if pf.wanted:
                    if not writable:
                        pf.add("modules can be staged", False,
                               "the game directory is not writable, so nothing can be downloaded")
                    elif pf.blockers:
                        # DO NOT DOWNLOAD once something has already failed. The game being open,
                        # a foreign live exe or a changed target id are all decided by this
                        # point, and pulling 1.3 GB into the player's game folder before telling
                        # them nothing could be done is pure waste -- of their bandwidth, their
                        # disk, and their patience.
                        pf.add("modules can be staged", False,
                               "skipped: an earlier check already blocks this update",
                               advisory=True)
                    else:
                        check_archives(pf, pf.doc, fetch.staging_dir(game_dir), pf.wanted,
                                       allow_file=allow_file,
                                       explicit=set(wanted_modules or []), labels=labels)

        check_patch_plan(pf, target, patches, spec)
    except Exception as e:  # noqa: BLE001 - a crashed check is a blocker, not a traceback
        pf.add("preflight completed", False, f"{type(e).__name__}: {e}")
    return pf
