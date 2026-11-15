"""terrainhd.cpp's own bookkeeping, run: the row off from the ini (nothing cut) and live (the exact stock textures and
UVs back, nothing held), a new game at a level, a new screen size, PRACX's Alt+T overlays drawn from level copies,
a cut that fails part way (stock for the session, retried only by switching the row), a pack damaged before or
after install, and a scratch resize that fails without the fatal exit.

tests/terrainhd_cache_selftest.cpp compiles terrainhd.cpp itself (TERRAINHD_SELFTEST: a fake exe image and fake
engine functions, a real 8192 x 6144 pack on disk read by the real hdpack reader) and runs one scenario per process.
Skipped when Visual Studio is absent.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402

SCENARIOS = ["off_holds_nothing", "new_game", "overlays", "cut_fails", "bad_pack", "pack_damaged_later",
             "scratch_resize_fails"]


@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "terrainhd_cache_selftest.cpp", "terrainhd_cache_", "/Oi /GL")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_terrainhd_bookkeeping(exe, tmp_path, scenario):
    r = subprocess.run([str(exe), str(tmp_path), scenario], capture_output=True, text=True, timeout=300)
    lines = r.stdout.splitlines()
    fails = [ln for ln in lines if ln.startswith("FAIL")]
    assert not fails, "\n".join(fails)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(ln.startswith("ok ") for ln in lines), r.stdout + r.stderr
