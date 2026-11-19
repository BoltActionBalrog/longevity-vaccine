"""The throwaway desktop / installs folders conftest makes for every pytest process are gone when the run ends,
and the stale sweep removes only empty, old folders whose owner has exited (lv_tempdirs.py)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import lv_tempdirs

HERE = Path(__file__).resolve().parent
PROBE_ENV = "LV_TEMPDIRS_PROBE"


@pytest.mark.skipif(not os.environ.get(PROBE_ENV), reason="only inside test_run_leaves_none_behind's inner run")
def test_probe_uses_the_folders():
    """Inner run: an xdist WORKER's folders exist, are its own, and take files (as an installer leaves them)."""
    assert os.environ.get("PYTEST_XDIST_WORKER"), "the inner run went serial: only the controller's cleanup is seen"
    desktop = Path(os.environ["LONGEVITY_DESKTOP_DIRS"])
    installs = Path(os.environ["LONGEVITY_INSTALLS_FILE"])
    for d in (desktop, installs.parent):
        assert d.is_dir() and d.name.startswith(f"lv-{'desktop' if d == desktop else 'installs'}-{os.getpid()}-")
        assert Path(os.environ[PROBE_ENV]) in d.parents
    (desktop / "Alpha Centauri.lnk").write_bytes(b"x")
    installs.write_text("C:\\somewhere\n", encoding="utf-8")


def test_run_leaves_none_behind(tmp_path):
    """A parallel run (controller + 2 workers, each making its own pair) leaves no lv-* folder in %TEMP%.

    ~3 s: one real inner run (two workers importing conftest) is the only way to see the exit-time cleanup of the
    controller AND the workers; the inner run selects one trivial test and does not log timings."""
    temp = tmp_path / "temp"
    temp.mkdir()
    env = {k: v for k, v in os.environ.items()               # the inner controller is not one of OUR workers
           if not k.startswith("PYTEST_XDIST_") and k != "PYTEST_CURRENT_TEST"}
    env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp), SMACX_TIMINGS="0", **{PROBE_ENV: str(temp)})
    r = subprocess.run([sys.executable, "-m", "pytest", f"{Path(__file__).name}::test_probe_uses_the_folders",
                        "-n", "2", "-p", "no:cacheprovider"],
                       cwd=HERE, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert "1 passed" in r.stdout, r.stdout[-3000:]
    assert [p.name for p in temp.iterdir() if p.name.startswith(lv_tempdirs.PREFIXES)] == []


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_sweep_removes_only_old_orphans(tmp_path):
    now = time.time()
    old = now - lv_tempdirs.STALE_AFTER_S - 60
    dead, live = _dead_pid(), os.getpid()

    def mk(name, mtime, files=()):
        d = tmp_path / name
        d.mkdir()
        for f in files:
            (d / f).write_text("x")
        os.utime(d, (mtime, mtime))
        return d

    gone = [mk(f"lv-desktop-{dead}-abc", old), mk(f"lv-installs-{dead}-def", old),
            mk(f"lv-installs-{dead}-full", old, ["installs.txt"]),             # a killed run's: contents too
            mk("lv-desktop-legacy1", old)]                                     # pre-PID name, empty
    kept = [mk(f"lv-desktop-{dead}-new", now, ["x.lnk"]),                      # too young
            mk("lv-installs-legacy2", old, ["installs.txt"]),                   # pre-PID name, owner unknown, not empty
            mk(f"lv-desktop-{live}-run", old),                                 # owner still running
            mk("lv-other-thing", old), mk("unrelated", old)]                   # not ours
    (tmp_path / "lv-desktop-file").write_text("x")                            # a file, not a folder
    os.utime(tmp_path / "lv-desktop-file", (old, old))

    removed = lv_tempdirs.sweep_stale(tmp_path, now=now)
    assert sorted(removed) == sorted(str(d) for d in gone)
    assert all(not d.exists() for d in gone)
    assert all(d.is_dir() for d in kept)
    assert (tmp_path / "lv-desktop-file").is_file()


def test_pid_alive():
    assert lv_tempdirs._pid_alive(os.getpid())
    assert not lv_tempdirs._pid_alive(_dead_pid())


def test_this_process_owns_its_pair():
    """conftest made this process's folders through lv_tempdirs, so they are on its exit list."""
    desktop = os.environ["LONGEVITY_DESKTOP_DIRS"]
    installs_dir = str(Path(os.environ["LONGEVITY_INSTALLS_FILE"]).parent)
    assert desktop in lv_tempdirs._owned and installs_dir in lv_tempdirs._owned
