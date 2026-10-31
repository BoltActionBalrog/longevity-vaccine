"""Every C++ harness build of the suite goes through cpp_harness, under its cross-process lock, and an exe it takes
from a cache is always a complete one.

Under pytest-xdist every worker that draws a test from a module runs that module's fixtures, so a fixture that calls
cl itself races the other workers: two compiles writing one .obj fail with "Cannot open compiler generated file:
...caption.obj: Permission denied" (movie_caption, cold _build: 6 of 6 runs with `-n 5 --dist load`), an mtime check
passes on a half-linked exe, and a support file rewritten while another worker's harness reads it is read empty.
cpp_harness.build (a per-run temp folder) and cpp_harness.build_in_dir (a checked-in `_build` folder) both hold
file_lock while they compile, and both link to a partial name that is renamed onto the exe only on success: a link
killed half-way (a killed worker releases its lock) leaves nothing a later caller takes for a built exe.

The behavioural tests stand in a fake for the batch runner (`cpp_harness._run_bat`), so they need no MSVC and run in
about a second: the child processes are what a killed or racing xdist worker is.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cpp_harness  # noqa: E402

COMPILE = re.compile(r"""\bcl\s+/nologo|vcvars(32|all)\.bat"\s*>nul|\["cl"|\bcl\.exe\b""")
GOOD = b"MZ complete image"


def test_no_test_helper_compiles_outside_cpp_harness():
    offenders = []
    for p in sorted(HERE.rglob("*.py")):
        if p.name in ("cpp_harness.py", pathlib.Path(__file__).name) or "_build" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        offenders += [f"{p.relative_to(HERE)}:{text.count(chr(10), 0, m.start()) + 1}" for m in COMPILE.finditer(text)]
    assert not offenders, f"compile through cpp_harness.build / build_in_dir (they hold the build lock): {offenders}"


def test_in_tree_harness_builds_are_locked():
    for rel in ("movie_caption/test_caption_render.py", "ps_badge/test_ps_badge_render.py"):
        text = (HERE / rel).read_text(encoding="utf-8")
        assert "cpp_harness.build_in_dir(EXE," in text and "subprocess.run(cmd, shell=True" not in text, rel
        assert "/Fe" not in text, f"{rel}: build_in_dir names the output (a partial name, renamed on success)"
    src = (HERE / "cpp_harness.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    body = src[src.index("def build_in_dir("):]
    lock = body.index("with file_lock(out / DIR_LOCK):")
    assert lock < body.index("_link(exe,") and lock < body.index("path.write_bytes(data)"), \
        "the compile and the support-file writes run under the folder's lock"
    assert body.index("exe.unlink(missing_ok=True)") < body.index("_link(exe,"), "a stale exe is gone before the build"


# ---- a fake cl: writes what the batch file names as the output ---------------------------------------------------
def _out_of(bat: pathlib.Path) -> pathlib.Path:
    m = re.search(r'/Fe"([^"]+)"', bat.read_text())
    assert m, bat.read_text()
    return pathlib.Path(m.group(1))


def _child(body: str, *args: str) -> subprocess.CompletedProcess:
    """Run `body` in a fresh interpreter with cpp_harness importable -- an xdist worker of its own."""
    code = "import os, pathlib, re, sys, time\nsys.path.insert(0, sys.argv[1])\nimport cpp_harness\n" + textwrap.dedent(body)
    return subprocess.run([sys.executable, "-c", code, str(HERE), *args], capture_output=True, text=True, timeout=60)


KILLED_MID_LINK = """
def killed_mid_link(bat):
    out = re.search(r'/Fe"([^"]+)"', bat.read_text()).group(1)
    pathlib.Path(out).write_bytes(b"MZ half")          # link.exe has written part of the image ...
    os._exit(9)                                          # ... when the worker is killed: no except, no finally runs
cpp_harness._run_bat = killed_mid_link
"""


@pytest.fixture
def inputs(tmp_path):
    src = tmp_path / "h.cpp"
    src.write_text("int main() { return 0; }\n")
    os.utime(src, (1_000_000_000, 1_000_000_000))      # older than any exe a build writes
    return tmp_path / "_build" / "h.exe", src


@pytest.fixture
def good_cl(monkeypatch):
    """In-process fake: a successful build. -> the list of output paths it wrote, one per build."""
    built = []

    def ok(bat):
        out = _out_of(bat)
        out.write_bytes(GOOD)
        built.append(out)
        return 0, ""
    monkeypatch.setattr(cpp_harness, "_run_bat", ok)
    return built


def test_build_in_dir_killed_mid_link_leaves_no_exe_that_is_reused(inputs, good_cl):
    exe, src = inputs
    r = _child(KILLED_MID_LINK + "cpp_harness.build_in_dir(pathlib.Path(sys.argv[2]), [sys.argv[3]], '/O1 h.cpp')",
               str(exe), str(src))
    assert r.returncode == 9, r.stderr
    assert not exe.exists(), "a link killed half-way left a file at the exe's name (newer than its inputs: 'current')"
    assert cpp_harness.partial_exe(exe).read_bytes() == b"MZ half"        # the kill really landed mid-link
    assert cpp_harness.build_in_dir(exe, [src], "/O1 h.cpp") == exe
    assert len(good_cl) == 1 and exe.read_bytes() == GOOD                # the next caller rebuilt it ...
    assert not cpp_harness.partial_exe(exe).exists()
    assert cpp_harness.build_in_dir(exe, [src], "/O1 h.cpp") == exe and len(good_cl) == 1   # ... and then reuses it


def test_build_killed_mid_link_leaves_no_exe_that_is_reused(inputs, good_cl, monkeypatch):
    _exe, src = inputs
    run = f"linkkill-{uuid.uuid4().hex}"                 # a private run folder (build() keys its cache by run id)
    monkeypatch.setenv("PYTEST_XDIST_TESTRUNUID", run)
    root = pathlib.Path(tempfile.gettempdir()) / f"smacx-cpp-{run}"
    try:
        r = _child(KILLED_MID_LINK + "cpp_harness.build(pathlib.Path(sys.argv[2]), 'linkkill_')", str(src))
        assert r.returncode == 9, r.stderr
        assert not list(root.glob("*/t.exe")), "a link killed half-way left t.exe in the shared run folder"
        exe = cpp_harness.build(src, "linkkill_")
        assert len(good_cl) == 1 and exe.read_bytes() == GOOD and exe.name == "t.exe"
        assert cpp_harness.build(src, "linkkill_") == exe and len(good_cl) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("how", ("raises", "exit_code"))
def test_build_in_dir_failed_link_leaves_neither_name(inputs, monkeypatch, how):
    """The exits this process survives (a timeout raises; cl exits non-zero after writing part of its output)."""
    exe, src = inputs
    exe.parent.mkdir()
    exe.write_bytes(GOOD)
    os.utime(exe, (900_000_000, 900_000_000))            # older than its input: stale, so it is rebuilt

    def failing(bat):
        _out_of(bat).write_bytes(b"MZ half")
        if how == "raises":
            raise RuntimeError("C++ harness build timed out")
        return 2, "LINK : fatal error"
    monkeypatch.setattr(cpp_harness, "_run_bat", failing)
    with pytest.raises(RuntimeError):
        cpp_harness.build_in_dir(exe, [src], "/O1 h.cpp")
    assert not exe.exists() and not cpp_harness.partial_exe(exe).exists()


COLD_RACER = """
def slow_cl(bat):
    with open(sys.argv[4], "a") as f:                    # one line per build that actually ran
        f.write("built\\n")
    time.sleep(0.4)                                      # long enough that every racer arrives mid-build
    pathlib.Path(re.search(r'/Fe"([^"]+)"', bat.read_text()).group(1)).write_bytes(b"MZ complete image")
    return 0, ""
cpp_harness._run_bat = slow_cl
exe, src, support = pathlib.Path(sys.argv[2]), sys.argv[3], pathlib.Path(sys.argv[5])
cpp_harness.build_in_dir(exe, [src], "/O1 h.cpp", files={support: b"movlist"})
print(exe.read_bytes().decode(), support.read_bytes().decode())
"""


def test_build_in_dir_cold_cache_race_builds_once(inputs, tmp_path):
    """Six workers draw the module at once on a cold `_build` (the movie_caption xdist race): one builds, the others
    wait on the folder lock and take the complete exe and support file."""
    exe, src = inputs
    log, support = tmp_path / "builds.log", exe.parent / "movlist_test.txt"
    code = "import os, pathlib, re, sys, time\nsys.path.insert(0, sys.argv[1])\nimport cpp_harness\n" + COLD_RACER
    procs = [subprocess.Popen([sys.executable, "-c", code, str(HERE), str(exe), str(src), str(log), str(support)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(6)]
    outs = [p.communicate(timeout=60) + (p.returncode,) for p in procs]
    assert all(rc == 0 for _o, _e, rc in outs), [e for _o, e, _rc in outs]
    assert all(o.split() == ["MZ", "complete", "image", "movlist"] for o, _e, _rc in outs), outs
    assert log.read_text().splitlines() == ["built"]
