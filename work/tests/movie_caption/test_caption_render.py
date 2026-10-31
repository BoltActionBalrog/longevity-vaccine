"""Offline check of the uimod post-movie caption (src\\uimod\\src\\caption.cpp): renders the
SUPERCOLLIDER caption at several screen sizes with caption_harness.exe (no game) and asserts every
measured ink position equals the MEASURED VANILLA position x k (k = movie scale), all axes sharing
the one factor.  Vanilla numbers: work\\_mov_caption_data_and_pixels.md (native 640x480 px).
"""
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import cpp_harness  # noqa: E402

SRC = ROOT / "src" / "uimod" / "src" / "caption.cpp"
HARNESS = HERE / "caption_harness.cpp"
EXE = HERE / "_build" / "caption_harness.exe"

MOVLIST = """#SUPERCOLLIDER
Arial, 0, 10,
56, 55, 1, 1,
Arial, 1, 14,
56, 55, 1, 1,
Arial, 1, 14,
56, 55, 1, 1,
160, 150, 320, 180,
10, 4000,

^^[The Supercollider]
^
^
^^$LINK<Research output=45> at this base is doubled.


#NEXT
"""

# measured vanilla, native px (ink rows/cols are inclusive; *_end = one past the last ink px)
# Anchors only: line TOPS (baseline-derived) and line CENTRES. Ink EDGES of a centred line are not
# k-linear -- hinted Arial at 10/14 px is proportionally wider (and its descender longer) than the
# same face at k x the size -- so the law centres each scaled line on vanilla's centre x k.
VANILLA = dict(title_top=228, title_cx=320.5, body_top=267, body_cx=319.5)
NATIVE_W, NATIVE_H = 400, 192
SCREENS = [(3840, 2160), (1920, 1080), (1600, 1200), (1024, 768), (640, 480)]


@pytest.fixture(scope="module")
def harness():
    if not cpp_harness.have_toolchain():
        pytest.skip("MSVC not installed")
    # every xdist worker that draws a test runs this fixture: one build and one movlist write per folder, under its lock
    ml = EXE.parent / "movlist_test.txt"
    cpp_harness.build_in_dir(EXE, (SRC, HARNESS, SRC.parent / "caption.h"),
                             f'/std:c++17 /EHsc /O1 /Fo"{EXE.parent}\\\\" "{HARNESS}" "{SRC}" gdi32.lib user32.lib',
                             files={ml: MOVLIST.replace("\n", "\r\n").encode("ascii")})
    return EXE, ml


def render(harness, w, h, out_dir):
    """`out_dir`: the test's own tmp_path. The bitmap used to go to _build/caption_WxH.bmp, which every run of this
    checkout shares: two suites at once wrote the same file and one of them could not open it (exit 3)."""
    exe, ml = harness
    out = out_dir / f"caption_{w}x{h}.bmp"
    r = subprocess.run([str(exe), str(ml), "supercollider", str(w), str(h), str(NATIVE_W), str(NATIVE_H), str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    info = dict(kv.split("=") for kv in r.stdout.split())
    dst = [int(v) for v in info["dst"].split(",")]
    return Image.open(out).convert("RGB"), dst, float(info["k"]), int(info["presents"])


def ink_bands(img):
    """Foreground ink (bright; the shadow is black on a dark frame) -> list of (top, end, left, right_end) per text band."""
    w, h = img.size
    px = img.load()
    rows = [any(px[x, y][0] > 140 for x in range(w)) for y in range(h)]
    bands, y = [], 0
    while y < h:
        if rows[y]:
            y1 = y
            while y1 < h and rows[y1]:
                y1 += 1
            xs = [x for x in range(w) if any(px[x, yy][0] > 140 for yy in range(y, y1))]
            bands.append((y, y1, xs[0], xs[-1] + 1))
            y = y1
        else:
            y += 1
    return bands


@pytest.mark.parametrize("w,h", SCREENS)
def test_scaling_caption_is_vanilla_times_k(harness, w, h, tmp_path):
    img, dst, k, presents = render(harness, w, h, tmp_path)
    ox = dst[0] - (640 - NATIVE_W) / 2 * k
    oy = dst[1] - (480 - NATIVE_H) / 2 * k
    bands = ink_bands(img)
    assert len(bands) == 2, bands                      # title + one body line, as vanilla
    (tt, te, tl, tr), (bt, be, bl, br) = bands
    tol = 0.75 * k + 1.0                               # glyph rasterisation is not exactly linear in size
    got = dict(title_top=(tt - oy) / k, title_cx=((tl + tr) / 2 - ox) / k,
               body_top=(bt - oy) / k, body_cx=((bl + br) / 2 - ox) / k)
    for name, van in VANILLA.items():
        assert abs(got[name] - van) * k <= tol, f"{name}: got {got[name]:.2f} native, vanilla {van} (k={k:.3f})"
    # every typed character is presented once: 17 title + 40 body
    assert presents == len("The Supercollider") + len("Research output at this base is doubled.")
    # nothing drawn outside the movie frame
    assert dst[1] <= tt and be <= dst[3] and dst[0] <= min(tl, bl) and max(tr, br) <= dst[2]
