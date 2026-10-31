"""Build a standalone C++ test harness with the VS 2022 x86 toolchain (shared by the pytest files
that check uimod's header-only logic against the Python side)."""
from __future__ import annotations

import contextlib
import errno
import hashlib
import msvcrt
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time

#: The Community edition's path; another edition sets VCVARS32 to its vcvars32.bat (README "Building and testing").
VCVARS = pathlib.Path(os.environ.get("VCVARS32")
                      or r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat")

_INCLUDE = re.compile(rb'^\s*#\s*include\s*"([^"]+)"', re.M)
COMPILE_TIMEOUT_S = 600
LOCK_TIMEOUT_S = COMPILE_TIMEOUT_S + 120   # the holder's compile is killed at COMPILE_TIMEOUT_S; never wait longer
STALE_RUN_DIR_S = 86400        # shared run dirs older than this are swept on the next build


def have_toolchain() -> bool:
    return VCVARS.exists()


def _run_bat(bat: pathlib.Path) -> tuple[int, str]:
    """Run a build script; (exit code, output). Raises on a timeout."""
    # Not subprocess.run(timeout=): on expiry it kills only cmd.exe, and then blocks reading the pipes that cl.exe
    # (a GRANDCHILD) still holds open -- a hung compile would hang this worker, and every worker waiting on the build
    # lock, for good. Kill the whole tree instead.
    p = subprocess.Popen(["cmd", "/c", str(bat)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = p.communicate(timeout=COMPILE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        stdout, stderr = p.communicate()
        raise RuntimeError(f"C++ harness build timed out after {COMPILE_TIMEOUT_S}s:\n{stdout}{stderr}")
    return p.returncode, stdout + stderr


def partial_exe(exe: pathlib.Path) -> pathlib.Path:
    """The name cl links `exe` to; renamed onto `exe` only once the build has succeeded."""
    return exe.with_name(f"{exe.stem}.partial{exe.suffix}")


def _link(exe: pathlib.Path, bat: pathlib.Path, cl_args: str, pre: str = "") -> None:
    """Build `exe` with `cl /nologo <cl_args>` (after the batch lines `pre`); raises with cl's output on failure.

    cl links to `partial_exe(exe)`, which is renamed onto `exe` (same folder, atomic) only when cl exited 0 with its
    output on disk. Both caches here take an existing exe for a built one (build_in_dir: the exe is newer than its
    inputs; build: t.exe is in the run folder), so a link killed half-way -- the worker's process killed, a timeout,
    Ctrl-C -- must never leave a file at that name: at most it leaves the partial name, which nothing reads and the
    next build replaces. The `finally` covers every exit this process survives; the rename covers the ones it does not.
    """
    assert "/Fe" not in cl_args, "the output name is set here (the partial name, renamed onto the exe)"
    part = partial_exe(exe)
    part.unlink(missing_ok=True)
    bat.write_text(f'@echo off\ncall "{VCVARS}" >nul\n{pre}cl /nologo {cl_args} /Fe"{part}"\nexit /b %errorlevel%\n')
    try:
        rc, output = _run_bat(bat)
        if rc != 0 or not part.exists():
            raise RuntimeError(output)
        os.replace(part, exe)
    finally:
        part.unlink(missing_ok=True)


def _compile(src: pathlib.Path, out: pathlib.Path, extra_flags: str) -> pathlib.Path:
    exe = out / "t.exe"
    _link(exe, out / "build.bat",
          f'/O2 /EHsc /W4 {extra_flags} /D_CRT_SECURE_NO_WARNINGS /Fo:"{out / "t.obj"}" "{src.name}"',
          pre=f'cd /d "{src.parent}"\n')
    return exe


def _source_key(src: pathlib.Path, extra_flags: str) -> str:
    """Hash of the flags, `src` and its whole `#include "..."` closure -- every input of ours.

    A quoted include is looked up as cl does without /I (none of these builds pass one): the includer's directory,
    then the directories of the files that included IT. One found nowhere is an error, not a skip -- an input left
    out of the key is a stale exe nobody notices.
    """
    h = hashlib.sha256(extra_flags.encode())
    seen = set()
    todo = [(src.resolve(), ())]                       # (file, directories of its includers, nearest first)
    while todo:
        p, outer = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        data = p.read_bytes()
        h.update(str(p).encode() + b"\0" + data)
        dirs = (p.parent, *outer)
        for m in _INCLUDE.findall(data):
            hit = next((d / m.decode() for d in dirs if (d / m.decode()).is_file()), None)
            if hit is None:
                raise FileNotFoundError(f'{p}: #include "{m.decode()}" not found (searched {", ".join(map(str, dirs))})')
            todo.append((hit.resolve(), dirs))
    return h.hexdigest()[:24]


@contextlib.contextmanager
def file_lock(path: pathlib.Path, timeout_s: float = LOCK_TIMEOUT_S):
    """Exclusive lock on `path` across processes (also baked_exe.build's); waits at most `timeout_s`."""
    deadline = time.monotonic() + timeout_s
    with open(path, "a+b") as f:                       # empty file, position 0: every process locks byte 0
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EDEADLOCK):
                    raise
                if time.monotonic() > deadline:
                    raise TimeoutError(f"no build lock after {timeout_s}s: {path}") from e
                time.sleep(0.1)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def _sweep_stale_run_dirs(tmp: pathlib.Path, keep: pathlib.Path) -> None:
    now = time.time()
    for d in tmp.glob("smacx-cpp-*"):
        try:
            if d != keep and now - d.stat().st_mtime > STALE_RUN_DIR_S:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def build(src: pathlib.Path, prefix: str, extra_flags: str = "") -> pathlib.Path:
    """Compile `src` (one .cpp) to a temp exe and return its path; raises with cl's output.  `extra_flags` lets a
    test match the DLL's own release codegen (e.g. /Oi /GL for float-sensitive ports).

    Under pytest-xdist the workers of ONE run share one build per (sources, flags): otherwise every worker that
    draws a test from the module compiles the same exe (~10 s each, 1,170 s of a 344 s wall). Keyed by xdist's
    per-run id, never reused across runs -- a run-to-run cache would trust that the hash covers the compiler and
    SDK headers, and it does not. (Passing xdist's `--testrunuid` by hand defeats that; do not.)

    The compile writes straight into the shared directory, under the lock: a waiter looks for t.exe only while it
    holds the lock, and t.exe only ever appears complete (`_link`: a worker killed mid-link releases the lock but
    leaves no t.exe), so it never takes a half-linked exe; there is no directory rename for an AV scanner to break.
    A failed compile is recorded, and every later waiter raises the same output instead of recompiling.
    """
    run = os.environ.get("PYTEST_XDIST_TESTRUNUID")
    if not run:
        return _compile(src, pathlib.Path(tempfile.mkdtemp(prefix=prefix)), extra_flags)
    tmp = pathlib.Path(tempfile.gettempdir())
    root = tmp / f"smacx-cpp-{run}"
    root.mkdir(exist_ok=True)
    _sweep_stale_run_dirs(tmp, root)
    key = _source_key(src, extra_flags)
    final, failed = root / key, root / f"{key}.err"
    with file_lock(root / f"{key}.lock"):
        if (final / "t.exe").exists():
            return final / "t.exe"
        if failed.exists():
            raise RuntimeError(failed.read_text(encoding="utf-8", errors="replace"))
        shutil.rmtree(final, ignore_errors=True)        # a leftover without t.exe (an interrupted link, AV)
        final.mkdir()
        try:
            return _compile(src, final, extra_flags)
        except RuntimeError as e:
            failed.write_text(str(e), encoding="utf-8")
            shutil.rmtree(final, ignore_errors=True)
            raise


DIR_LOCK = ".build.lock"


def build_in_dir(exe: pathlib.Path, inputs, cl_args: str, files: dict | None = None) -> pathlib.Path:
    """Build `exe` into its own folder (a harness's checked-in `_build`, kept across runs) with `cl <cl_args>` -- whose
    objects land in that folder too; no /Fe, `_link` names the output -- when it is missing or older than any of
    `inputs`; and write each of `files`
    ({path: bytes}, support files the tests read) whose content differs. All of it under one cross-process lock on the
    folder (`file_lock`): every xdist worker that draws a test from the module runs the module fixture, and two cl's
    writing the same .obj fail with "Cannot open ... .obj: Permission denied", a check of the exe's mtime can pass on a
    half-linked exe, and a support file rewritten while another worker's exe reads it is read empty. Whoever takes the
    lock first builds; the rest find the exe current. A failed or interrupted build leaves no exe behind (`_link`
    links to a partial name, renamed onto `exe` only on success), so the next caller retries -- an exe killed
    half-linked is newer than its inputs and would otherwise pass the mtime check for good.
    """
    out = exe.parent
    out.mkdir(parents=True, exist_ok=True)
    with file_lock(out / DIR_LOCK):
        newest = max(pathlib.Path(p).stat().st_mtime for p in inputs)
        if not exe.exists() or exe.stat().st_mtime < newest:
            exe.unlink(missing_ok=True)
            _link(exe, out / f"{exe.stem}.build.bat", cl_args)
        for path, data in (files or {}).items():
            path = pathlib.Path(path)
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
    return exe
