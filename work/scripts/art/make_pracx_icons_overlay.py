"""Build work/art/pracx_icons_overlay.pcx: PRACX 1.11's icon art, and nothing else.

Input: PRACX's own Icons.pcx (https://github.com/DrazharLn/pracx, resources/Icons.pcx at 06726f8,
the sheet PRACX 1.11's installer writes; CC0 -- see work/art/pracx_icons_overlay-PROVENANCE.txt).
Output: an 800x600 sheet that keeps that file's pixels inside patch_icons.COPY_RECTS (the rectangles
PRACX reads, each with a 1-pixel border) and is plain background everywhere else, so none of the
game's stock art is copied into it.

    py make_pracx_icons_overlay.py [path\\to\\pracx\\resources\\Icons.pcx]

After a rebuild, record the new OVERLAY_SHA256 / EXPECTED_RESULT in patch_icons.py
(test_patch_icons tells you the values).
"""
import collections
import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import patch_icons as pi  # noqa: E402

REPO = HERE.parents[2]
DEFAULT_SRC = REPO / "refs" / "pracx" / "resources" / "Icons.pcx"
OUT = REPO / "work" / "art" / "pracx_icons_overlay.pcx"


def build(src: bytes) -> bytes:
    header, pixels, palette = pi.decode(src)
    bg = collections.Counter(pixels).most_common(1)[0][0]
    blank = bytes((bg,)) * (pi.W * pi.H)
    return pi.encode(header, pi.compose(blank, pixels), palette)


def main() -> int:
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    out = build(src.read_bytes())
    OUT.write_bytes(out)
    print(f"wrote {OUT} ({len(out)} bytes) sha256 {hashlib.sha256(out).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
