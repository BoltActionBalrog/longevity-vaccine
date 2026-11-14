"""objecthd.cpp's own bookkeeping, run: the remembered failure per (object, size), the blank cells found when a sheet
is proven, the size cache, the budget trim, the Datalinks size, and that the row switched off (or off from the ini)
holds nothing and is proven again when switched on.

tests/objecthd_cache_selftest.cpp compiles objecthd.cpp itself (OBJECTHD_SELFTEST: a fake exe image and fake engine
functions, real sheets on disk read by the real hdpack reader, a 60,000-byte budget) and runs one scenario per
process. Skipped when Visual Studio is absent.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402

SCENARIOS = ["off_holds_nothing", "on_again_fails_stock", "failure_memory_and_size_cache", "blank_cell", "budget_trim",
             "datalinks_scale"]


@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "objecthd_cache_selftest.cpp", "objecthd_cache_", "/Oi /GL")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_objecthd_bookkeeping(exe, tmp_path, scenario):
    r = subprocess.run([str(exe), str(tmp_path), scenario], capture_output=True, text=True, timeout=120)
    lines = r.stdout.splitlines()
    fails = [ln for ln in lines if ln.startswith("FAIL")]
    assert not fails, "\n".join(fails)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(ln.startswith("ok ") for ln in lines), r.stdout + r.stderr
