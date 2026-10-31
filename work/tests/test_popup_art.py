"""The update prompt's popup picture (`work\\art\\longevity_sm.pcx`) is in the game's popup-art
format and is exactly what its generator produces.

The engine draws it through the same filename-backed path as every `*_sm.pcx` event picture,
so it must match that family: 200x120, 8-bit palettised, the palette shared by `space_sm.pcx`
and `ac_logo_sm.pcx`, index 255 (the key colour) on the four corner pixels only, and NO scanline
dither (a solid picture cannot band under the popup art re-blit).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_WORK = Path(__file__).resolve().parent.parent
_ART = _WORK / "art" / "longevity_sm.pcx"
_GEN = _WORK / "scripts" / "art" / "make_longevity_sm.py"
sys.path.insert(0, str(_WORK / "scripts"))

PIL = pytest.importorskip("PIL.Image")


def _game_dir() -> Path:
    import config
    g = Path(config.game_dir())
    if not (g / "space_sm.pcx").is_file():
        pytest.skip("game dir with space_sm.pcx not available")
    return g


def test_the_art_is_in_the_popup_picture_format():
    im = PIL.open(_ART)
    assert im.size == (200, 120) and im.mode == "P"
    px = im.load()
    corners = {(0, 0), (199, 0), (0, 119), (199, 119)}
    keyed = {(x, y) for y in range(120) for x in range(200) if px[x, y] == 255}
    assert keyed == corners, "index 255 is the key colour: corners only"
    pal = im.getpalette()
    assert tuple(pal[255 * 3:255 * 3 + 3]) == (100, 16, 156), "the family's key colour"


def test_the_art_shares_the_games_popup_palette():
    g = _game_dir()
    ours = PIL.open(_ART).getpalette()
    assert ours == PIL.open(g / "space_sm.pcx").getpalette()
    assert ours == PIL.open(g / "ac_logo_sm.pcx").getpalette()


def _row_alternations(im, xs) -> int:
    """Count rows whose luminance goes up-down-up against both neighbours: a 1-row scanline
    dither alternates on EVERY row; a picture's edges do it once per edge crossing."""
    px = im.convert("RGB").load()
    n = 0
    for x in xs:
        col = [sum(px[x, y]) for y in range(im.size[1])]
        n += sum(1 for y in range(1, im.size[1] - 1)
                 if (col[y] - col[y - 1]) * (col[y + 1] - col[y]) < 0
                 and abs(col[y] - col[y - 1]) > 24)
    return n


def test_the_art_has_no_scanline_dither():
    """The vanilla `*_sm.pcx` carry a 1-row dither the popup re-blit has to repair; ours must
    not need it. The outer margins are plain backdrop and must not alternate at all, and the
    whole picture must alternate far less than the game's own dithered `space_sm.pcx`."""
    im = PIL.open(_ART)
    margins = list(range(0, 24)) + list(range(176, 200))
    assert _row_alternations(im, margins) == 0, "the backdrop alternates row to row: dithered"
    ours = _row_alternations(im, range(0, 200, 4))
    try:
        theirs = _row_alternations(PIL.open(_game_dir() / "space_sm.pcx"), range(0, 200, 4))
    except pytest.skip.Exception:
        theirs = 1500        # measured 2026-09-27 on the GOG install: ~1.5k for the dithered art
    assert ours * 4 < theirs, f"row alternations ours={ours} vs vanilla dithered={theirs}"


def test_the_generator_reproduces_the_committed_bytes(tmp_path):
    g = _game_dir()
    r = subprocess.run([sys.executable, str(_GEN), str(g), str(tmp_path)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "longevity_sm.pcx").read_bytes() == _ART.read_bytes(), \
        "work\\art\\longevity_sm.pcx is stale: re-run make_longevity_sm.py and commit the result"
