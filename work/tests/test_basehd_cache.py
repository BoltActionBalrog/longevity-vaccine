"""basehd.cpp's own bookkeeping, run: the remembered failure per (sprite, size), the blank cell, the budget trim, the
stale entry after a new game, Adopt, the pack table, and that the row switched off (or off from the ini) holds and
reads nothing.

tests/basehd_cache_selftest.cpp compiles basehd.cpp itself (BASEHD_SELFTEST: a fake exe image and fake engine
functions, real packs on disk read by the real hdpack reader, a 60,000-byte budget) and runs one scenario per process.
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

SCENARIOS = ["off_holds_nothing", "failure_memory", "blank_cell", "budget_trim", "stale_entry", "adopt_skips_empty",
             "table_reuse", "junk_first"]


@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "basehd_cache_selftest.cpp", "basehd_cache_", "/Oi /GL")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_basehd_bookkeeping(exe, tmp_path, scenario):
    r = subprocess.run([str(exe), str(tmp_path), scenario], capture_output=True, text=True, timeout=120)
    lines = r.stdout.splitlines()
    fails = [ln for ln in lines if ln.startswith("FAIL")]
    assert not fails, "\n".join(fails)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(ln.startswith("ok ") for ln in lines), r.stdout + r.stderr
