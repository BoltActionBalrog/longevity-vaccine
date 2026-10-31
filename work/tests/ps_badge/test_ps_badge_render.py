"""Offline check of the uimod Punishment Sphere badge (src\\uimod\\src\\psbadge.h): compiles the header
into badge_harness.exe (no game) and asserts the C++ rasteriser, size law and tone ramp equal their source
of truth, scaling_laws.ps_badge / ps_badge_raster / ps_badge_ramp, bit for bit at every face width the two
painters produce for g = 16..45.  Also renders the law's badge to work\\_ps_badge_preview\\law_badge_d<N>.png
(1:1 and x8) for visual approval.
"""
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "work" / "scripts"))
sys.path.insert(0, str(HERE.parent))
import cpp_harness  # noqa: E402
from scaling_laws import ps_badge, ps_badge_ramp, ps_badge_raster, ps_staple_ramp, ps_staple_raster  # noqa: E402

HDR = ROOT / "src" / "uimod" / "src" / "psbadge.h"
HARNESS = HERE / "badge_harness.cpp"
EXE = HERE / "_build" / "badge_harness.exe"
PREVIEW = ROOT / "work" / "_ps_badge_preview"

FACE_WIDTHS = sorted({(w * g) >> 4 for w in (38, 30) for g in range(16, 46)})


@pytest.fixture(scope="module")
def harness():
    if not cpp_harness.have_toolchain():
        pytest.skip("MSVC not installed")
    # one build per folder, whichever xdist worker (or concurrent run) gets there first: cpp_harness.build_in_dir
    return cpp_harness.build_in_dir(EXE, (HDR, HARNESS),
                                    f'/std:c++17 /EHsc /O1 /I"{HDR.parent}" /Fo"{EXE.parent}\\\\" "{HARNESS}"')


def test_scaling_ps_badge_cpp_equals_law(harness):
    r = subprocess.run([str(harness)] + [str(w) for w in FACE_WIDTHS], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.split("\n")
    i = 0
    for w in FACE_WIDTHS:
        head = [int(v) for v in lines[i].split()]
        law = ps_badge(w)
        assert head[:3] == [w, law["d"], law["inset"]]
        assert head[3:] == [c for rgb in ps_badge_ramp() for c in rgb]
        d = law["d"]
        want = ["".join("." if t < 0 else str(t) for t in row) for row in ps_badge_raster(d)]
        assert lines[i + 1:i + 1 + d] == want, f"raster differs at face width {w} (d={d})"
        i += 1 + d


def test_scaling_ps_staple_cpp_equals_law(harness):
    """The nerve-staple glyph (2026-10-29): the C++ port equals ps_staple_raster / ps_staple_ramp bit for bit."""
    r = subprocess.run([str(harness)] + [f"s{w}" for w in FACE_WIDTHS], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.split("\n")
    i = 0
    for w in FACE_WIDTHS:
        head = [int(v) for v in lines[i].split()]
        law = ps_badge(w)
        assert head[:3] == [w, law["d"], law["inset"]]
        assert head[3:] == [c for rgb in ps_staple_ramp() for c in rgb]
        d = law["d"]
        want = ["".join("." if t < 0 else str(t) for t in row) for row in ps_staple_raster(d)]
        assert lines[i + 1:i + 1 + d] == want, f"staple raster differs at face width {w} (d={d})"
        i += 1 + d


@pytest.mark.parametrize("d", [15, 21, 23, 37, 12, 16, 18, 30])
def test_scaling_ps_staple_preview_png(d):
    """The staple glyph reads at every size: a black disc with a white X and a white rim, symmetric in both
    axes, the X white at the centre, the space between its arms black."""
    ramp = ps_staple_ramp()
    grid = ps_staple_raster(d)
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    for y, row in enumerate(grid):
        for x, t in enumerate(row):
            if t >= 0:
                img.putpixel((x, y), ramp[t] + (255,))
    PREVIEW.mkdir(exist_ok=True)
    img.save(PREVIEW / f"law_staple_d{d}.png")
    img.resize((d * 8, d * 8), Image.NEAREST).save(PREVIEW / f"law_staple_d{d}_x8.png")
    tones = [t for row in grid for t in row if t >= 0]
    assert 0 in tones and 2 in tones and 4 not in tones
    assert grid == [row[::-1] for row in grid] == grid[::-1], "the badge is symmetric in both axes"
    assert grid[d // 2][d // 2] == 2, "the X's crossing is white"
    assert grid[(d * (100 - 30)) // 200][d // 2] == 0, "between the upper arms is black"
    assert grid[d - 1][d // 2] == 2, "the rim is white"


@pytest.mark.parametrize("d", [15, 21, 23, 37, 12, 16, 18, 30])
def test_scaling_ps_badge_preview_png(d):
    """The law's own raster, written for visual approval (true ramp colours; the game maps each tone to the
    nearest index of the dest buffer's colour table)."""
    ramp = ps_badge_ramp()
    grid = ps_badge_raster(d)
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    for y, row in enumerate(grid):
        for x, t in enumerate(row):
            if t >= 0:
                img.putpixel((x, y), ramp[t] + (255,))
    PREVIEW.mkdir(exist_ok=True)
    img.save(PREVIEW / f"law_badge_d{d}.png")
    img.resize((d * 8, d * 8), Image.NEAREST).save(PREVIEW / f"law_badge_d{d}_x8.png")
    # the design reads at every size: a gold ring and core on a dark disc, symmetric in both axes
    tones = [t for row in grid for t in row if t >= 0]
    assert 4 in tones and 0 in tones
    assert grid == [row[::-1] for row in grid] == grid[::-1]
    assert grid[d // 2][d // 2] == 4
