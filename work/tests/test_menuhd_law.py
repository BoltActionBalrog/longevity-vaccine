"""uimod menuhd_law.h (C++) vs scaling_laws.menu_hd_layout (the source of truth), exactly; and the law's own promises.

Builds tests/menuhd_selftest.cpp with the VS x86 toolchain (skipped when VS is absent). The law-only tests run anyway.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402
import scaling_laws as SL  # noqa: E402

SCREENS = [(800, 600), (1024, 768), (1280, 1024), (1600, 1200), (1366, 768), (1600, 900), (1920, 1080), (1920, 1200),
           (2560, 1080), (2560, 1440), (3440, 1440), (3840, 1080), (3840, 2160), (5120, 1440), (1440, 1080)]


def test_identity_at_the_stock_size():
    num, den, *rest = SL.menu_hd_layout(1024, 768)
    assert num == den and tuple(rest) == (768, 0, 404, 620)


@pytest.mark.parametrize("w,h", SCREENS)
def test_uniform_and_inside_the_screen(w, h):
    num, den, core_h, y0, strip_w, strip_x = SL.menu_hd_layout(w, h)
    assert num * 1024 <= w * den + den and num * 768 <= h * den + den      # the 4:3 core fits the screen
    assert core_h == 768 * num // den and strip_w == 404 * num // den       # one scale for both axes
    assert 0 <= y0 and y0 + core_h <= h and strip_x + strip_w == w
    if w * 3 >= h * 4:
        assert (core_h, y0) == (h, 0)                                       # wide: full height, no bands


@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "menuhd_selftest.cpp", "menuhd_selftest_", "/Oi /GL")


@pytest.mark.parametrize("w,h", SCREENS + [(1, 1), (7, 5), (12345, 678)])
def test_port_matches_law(exe, w, h):
    out = subprocess.run([str(exe), str(w), str(h)], capture_output=True, text=True, check=True).stdout.split()
    assert tuple(int(v) for v in out) == SL.menu_hd_layout(w, h)
