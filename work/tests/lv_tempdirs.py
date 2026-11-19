"""The throwaway desktop / remembered-installs folders every pytest process points the installer at.

conftest.py makes one of each per process (the controller and every xdist worker) at import. Each name carries
the owning PID (`lv-desktop-<pid>-<random>`) and the owner removes its own at exit, so a run leaves none behind.
A process that was killed cannot clean up; `sweep_stale` removes such leftovers later: a folder older than a few
hours whose named owner is no longer running goes with whatever a test left in it (a killed run's folder is
rarely empty), and an old-style folder with no PID in its name goes only when it is EMPTY. Never one a live run
(or its installer subprocess) may still use, and never anything else in the temp folder.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

PREFIXES = ("lv-desktop-", "lv-installs-")
STALE_AFTER_S = 6 * 3600
_NAME = re.compile(r"^lv-(?:desktop|installs)-(?:(\d+)-)?")

_owned: list[str] = []


def make(kind: str) -> str:
    """A fresh folder `lv-<kind>-<pid>-<random>` in the temp folder, removed when this process exits."""
    path = tempfile.mkdtemp(prefix=f"lv-{kind}-{os.getpid()}-")
    if not _owned:
        atexit.register(cleanup)
    _owned.append(path)
    return path


def cleanup() -> None:
    """Remove the folders this process made (with whatever a test or installer left in them)."""
    while _owned:
        shutil.rmtree(_owned.pop(), ignore_errors=True)


def _pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5              # ACCESS_DENIED: it exists, someone else's
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == 259                         # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def sweep_stale(root: str | os.PathLike | None = None, *, max_age_s: float = STALE_AFTER_S,
                now: float | None = None) -> list[str]:
    """Remove old `lv-desktop-*` / `lv-installs-*` folders whose owner is gone. Returns what it removed.

    Kept: anything newer than `max_age_s`; anything whose name names a running PID (a reused PID only keeps a
    folder longer); and an old-style folder (no PID in its name, so no owner to ask) that is not empty -- os.rmdir
    refuses it, so one a live old-style run writes into between the check and the removal is left alone too.
    A PID-named folder whose owner has exited is removed with its contents (rmtree does not follow junctions).
    """
    root = Path(root if root is not None else tempfile.gettempdir())
    now = time.time() if now is None else now
    removed = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return removed
    for e in entries:
        m = _NAME.match(e.name)
        if not m:
            continue
        try:
            if not e.is_dir(follow_symlinks=False) or now - e.stat(follow_symlinks=False).st_mtime < max_age_s:
                continue
        except OSError:
            continue
        if m.group(1):
            if _pid_alive(int(m.group(1))):
                continue
            shutil.rmtree(e.path, ignore_errors=True)        # its owner is gone: nobody can be using it
            if os.path.lexists(e.path):
                continue
        else:
            try:
                os.rmdir(e.path)                             # no owner to ask: only ever an EMPTY folder
            except OSError:
                continue
        removed.append(e.path)
    return removed
