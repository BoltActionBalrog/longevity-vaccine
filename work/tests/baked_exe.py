"""The patched exe the emulator suites run: the pristine .bak with the live patches.yaml applied, built ONCE per pytest
run (conftest's `baked_exe` fixture).  Same build as `apply_patches.py --target <copy of the .bak> --apply`, the same
argv and environment every module used to run in its own module fixture."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import apply_patches as ap
import config
from cpp_harness import file_lock

EXE_NAME = "terranx_test.exe"
APPLY_TIMEOUT_S = 600
LOCK_TIMEOUT_S = APPLY_TIMEOUT_S + 120     # the holder's apply is killed at APPLY_TIMEOUT_S; never wait longer
STALE_RUN_DIR_S = 86400                    # shared run dirs older than this are swept on the next build


class BuildError(RuntimeError):
    pass


def inputs() -> tuple:
    """Every file the build reads that can change its bytes: the patch set, the patcher and its config module.  (The
    .bak is added by `input_key`.)"""
    return Path(ap.DEFAULT_PATCHES), Path(ap.__file__), Path(config.__file__)


def input_key(bak: Path) -> str:
    h = hashlib.sha256(sys.executable.encode())
    for p in (*inputs(), Path(bak)):
        p = p.resolve()
        h.update(str(p).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:24]


def _apply(bak: Path, out: Path) -> Path:
    dst = out / EXE_NAME
    shutil.copy2(bak, dst)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([sys.executable, str(Path(ap.__file__).resolve()), "--target", str(dst), "--apply"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                           timeout=APPLY_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        raise BuildError(f"apply_patches.py --apply timed out after {APPLY_TIMEOUT_S}s") from e
    if r.returncode != 0:
        raise BuildError("patch set does not apply to the .bak -- this test must not go green without the real "
                         "bytes: " + r.stdout[-1500:] + r.stderr[-1500:])
    os.chmod(dst, stat.S_IREAD)            # read-only to every test: a write raises instead of corrupting the share
    return dst


def _rmtree(path: Path) -> None:
    def writable_retry(fn, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        fn(p)
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=writable_retry)
        else:
            shutil.rmtree(path, onerror=writable_retry)
    except OSError:
        pass


def _sweep_stale_run_dirs(tmp: Path, keep: Path) -> None:
    now = time.time()
    for d in tmp.glob("smacx-baked-*"):
        try:
            if d != keep and now - d.stat().st_mtime > STALE_RUN_DIR_S:
                _rmtree(d)
        except OSError:
            pass


def build(bak: Path, serial_dir) -> Path:
    """The baked exe's path (read-only).  `serial_dir()` gives the directory to build in when not under xdist.

    Under pytest-xdist the workers of ONE run share one build per input key (`cpp_harness.build`'s scheme): otherwise
    every chunk the scheduler cuts from a module repays the ~1.2 s apply in each worker that draws one.  Keyed by
    xdist's per-run id, never reused across runs.  Built under a file lock; success is recorded by a marker written
    after the exe is complete, so a waiter never takes a half-built (or unpatched) copy, and a failed build is recorded
    so every later waiter raises the same output instead of rebuilding.
    """
    run = os.environ.get("PYTEST_XDIST_TESTRUNUID")
    if not run:
        return _apply(bak, Path(serial_dir()))
    tmp = Path(tempfile.gettempdir())
    root = tmp / f"smacx-baked-{run}"
    root.mkdir(exist_ok=True)
    _sweep_stale_run_dirs(tmp, root)
    key = input_key(bak)
    final, ok, failed = root / key, root / f"{key}.ok", root / f"{key}.err"
    with file_lock(root / f"{key}.lock", LOCK_TIMEOUT_S):
        if ok.exists():
            return final / EXE_NAME
        if failed.exists():
            raise BuildError(failed.read_text(encoding="utf-8", errors="replace"))
        _rmtree(final)                     # a leftover without the marker (an interrupted build)
        final.mkdir()
        try:
            exe = _apply(bak, final)
        except BuildError as e:
            failed.write_text(str(e), encoding="utf-8")
            raise
        ok.touch()
        return exe
