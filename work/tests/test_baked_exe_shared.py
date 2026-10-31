"""The patched exe is built once per pytest run (conftest's `baked_exe`, baked_exe.py), never by a test module's own
fixture or helper.

1. Static guard: `"--apply"` (the patcher's commit flag) may appear in a test module only inside a `test_*` function --
   a test whose subject IS the apply (test_apply_md5, test_targets).  A fixture or helper that runs it rebuilds the exe
   once per chunk per worker under the cost-aware scheduler; take `baked_exe` instead.
2. The sharing logic of baked_exe.build, with the apply stubbed: one build per run and key, a failure recorded for
   every waiter, a build without its success marker redone, nothing shared across runs.
"""
from __future__ import annotations

import ast
import os
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import baked_exe as B

HERE = Path(__file__).resolve().parent
FLAG = "-" * 2 + "apply"           # spelled out so this module does not trip its own guard


def _apply_outside_tests(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    allowed = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            allowed.update(id(n) for n in ast.walk(node))
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value == FLAG and id(n) not in allowed]


def test_no_module_builds_its_own_baked_exe():
    bad = {p.name: lines for p in sorted(HERE.glob("test_*.py")) if (lines := _apply_outside_tests(p))}
    assert not bad, ("these modules run `apply_patches --apply` outside a test function (a fixture or helper "
                     f"rebuilding the exe per chunk); use conftest's session fixture `baked_exe`: {bad}")


def test_the_guard_sees_a_fixture_build(tmp_path):
    p = tmp_path / "test_x.py"
    p.write_text('import pytest\n@pytest.fixture(scope="module")\ndef baked(tmp_path_factory):\n'
                 '    run(["--target", "x", "--apply"])\n\ndef test_a(baked):\n    run(["--apply"])\n',
                 encoding="utf-8")
    assert _apply_outside_tests(p) == [4]


# ---- 2. sharing ------------------------------------------------------------------------------------------------------
@pytest.fixture
def rig(tmp_path, monkeypatch):
    """baked_exe.build under a fake xdist run: its own temp root, the apply stubbed (records each call)."""
    r = SimpleNamespace(bak=tmp_path / "x.bak", calls=[], tmp=tmp_path / "tmp", fail=False)
    r.bak.write_bytes(b"pristine")
    r.tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(r.tmp))
    monkeypatch.setenv("PYTEST_XDIST_TESTRUNUID", "run1")

    def fake_apply(src, out):
        r.calls.append(out)
        if r.fail:
            raise B.BuildError("patch set does not apply: boom")
        dst = out / B.EXE_NAME
        dst.write_bytes(src.read_bytes() + b"+patched")
        os.chmod(dst, stat.S_IREAD)
        return dst

    monkeypatch.setattr(B, "_apply", fake_apply)
    yield r
    for d in r.tmp.glob("smacx-baked-*"):
        B._rmtree(d)


def _serial_dir():
    raise AssertionError("not a serial run")


def test_one_build_per_run_and_key(rig):
    a = B.build(rig.bak, _serial_dir)
    b = B.build(rig.bak, _serial_dir)
    assert a == b and a.read_bytes() == b"pristine+patched" and len(rig.calls) == 1
    assert a.parent.parent == rig.tmp / "smacx-baked-run1"


def test_the_shared_exe_is_read_only(rig):
    exe = B.build(rig.bak, _serial_dir)
    with pytest.raises(PermissionError):
        exe.open("r+b")


def test_a_failed_build_is_raised_to_every_waiter_without_rebuilding(rig):
    rig.fail = True
    with pytest.raises(B.BuildError, match="boom"):
        B.build(rig.bak, _serial_dir)
    rig.fail = False
    with pytest.raises(B.BuildError, match="boom"):
        B.build(rig.bak, _serial_dir)
    assert len(rig.calls) == 1


def test_a_build_without_its_marker_is_redone(rig):
    exe = B.build(rig.bak, _serial_dir)
    (exe.parent.parent / f"{B.input_key(rig.bak)}.ok").unlink()
    assert B.build(rig.bak, _serial_dir) == exe and len(rig.calls) == 2


def test_a_new_run_or_input_builds_again(rig, monkeypatch):
    a = B.build(rig.bak, _serial_dir)
    monkeypatch.setenv("PYTEST_XDIST_TESTRUNUID", "run2")
    b = B.build(rig.bak, _serial_dir)
    rig.bak.write_bytes(b"other")
    c = B.build(rig.bak, _serial_dir)
    assert len({a, b, c}) == 3 and len(rig.calls) == 3 and c.read_bytes() == b"other+patched"


def test_the_key_covers_every_input(rig, tmp_path, monkeypatch):
    files = []
    for i in range(3):
        f = tmp_path / f"in{i}"
        f.write_bytes(b"a")
        files.append(f)
    monkeypatch.setattr(B, "inputs", lambda: tuple(files))
    k0 = B.input_key(rig.bak)
    for f in files:
        f.write_bytes(b"b")
        assert B.input_key(rig.bak) != k0, f
        f.write_bytes(b"a")
    assert B.input_key(rig.bak) == k0


def test_serial_builds_in_the_given_dir(rig, tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_XDIST_TESTRUNUID")
    out = tmp_path / "serial"
    out.mkdir()
    assert B.build(rig.bak, lambda: out) == out / B.EXE_NAME
