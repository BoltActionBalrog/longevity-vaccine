"""scaling_laws.portrait_applies: the smooth leader-portrait enlarge takes portraits only, never a SHAPED sprite.

The Spartans' council logo (spartans.pcx, a 62x72 / 62x71 hexagon -- the one portrait-shaped faction logo) passed the
shape gate and came out on an opaque near-black square (2026-10-11).  The gate's opaque-ring rule refuses it; every
real leader portrait and native-life face must still qualify (angels.pcx's portraits carry stray key texels inside)."""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

KEY = 255
FACTIONS = ["gaians", "hive", "univ", "morgan", "spartans", "believe", "peace",
            "cyborg", "pirates", "drone", "angels", "fungboy", "caretake", "usurper"]
#: load_faction_art's leader slots (x, y, w, h) incl. the 1-px frame, identical on every sheet
SLOTS = {"smallcouncil": (88, 457, 96, 115), "bigcouncil": (185, 457, 118, 144),
         "diplomacy": (304, 457, 131, 157), "datalink": (531, 1, 164, 198)}
#: the two council logo cells (normal / hover) inside the cyan grid; the sprite is the cell's non-key bounding box
LOGO_CELLS = [(1, 457, 87, 529), (1, 530, 87, 602)]
NATIVE_FACES = ["BTfungtow", "BTsealrk", "BTsporlnch", "Btchi", "Btisl", "Btwrm"]


def _sheet(name):
    from PIL import Image
    d = config.game_dir(required=False)
    p = d / f"{name}.pcx" if d else None
    if not p or not p.exists():
        pytest.skip("game art not available")
    return Image.open(p)


def trimmed(im, box, key=KEY):
    """The Sprite a cell cuts to: the bounding box of its non-key texels (bytes, w, h)."""
    cell = im.crop(box)
    w, h = cell.size
    b = cell.tobytes()
    xs = [x for y in range(h) for x in range(w) if b[y * w + x] != key]
    ys = [y for y in range(h) for x in range(w) if b[y * w + x] != key]
    sub = cell.crop((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
    return sub.tobytes(), sub.size[0], sub.size[1]


def framed(sw, sh, interior=10, ring=25, corner=KEY):
    src = bytearray(sw * sh)
    for y in range(sh):
        for x in range(sw):
            edge = y in (0, sh - 1) or x in (0, sw - 1)
            src[y * sw + x] = (corner if y in (0, sh - 1) and x in (0, sw - 1) else ring) if edge else interior
    return src


@pytest.mark.parametrize("g", [17, 22, 25, 40])
def test_opaque_ring_qualifies(g):
    assert SL.portrait_applies(bytes(framed(40, 60)), 40, 40, 60, KEY, g)
    assert SL.portrait_applies(bytes(framed(40, 60, corner=30)), 40, 40, 60, KEY, g)   # unkeyed corners too


@pytest.mark.parametrize("pos", ["top", "bottom", "left", "right"])
def test_key_on_the_ring_refuses(pos):
    sw, sh = 40, 60
    src = framed(sw, sh)
    x, y = {"top": (5, 0), "bottom": (sw - 2, sh - 1), "left": (0, 1), "right": (sw - 1, sh - 2)}[pos]
    src[y * sw + x] = KEY
    assert not SL.portrait_applies(bytes(src), sw, sw, sh, KEY, 40)
    assert SL.portrait_enlarge(bytes(src), sw, sw, sh, KEY, bytes(1024), 40) is None


def test_key_inside_still_qualifies():
    sw, sh = 40, 60
    src = framed(sw, sh)
    for x, y in ((1, 1), (20, 30), (sw - 2, sh - 2)):
        src[y * sw + x] = KEY
    assert SL.portrait_applies(bytes(src), sw, sw, sh, KEY, 40)


def test_pitch_is_honoured():
    sw, sh, pitch = 40, 60, 44
    src = bytearray([KEY]) * (pitch * sh)                                   # key in the pitch padding only
    f = framed(sw, sh)
    for y in range(sh):
        src[y * pitch:y * pitch + sw] = f[y * sw:(y + 1) * sw]
    assert SL.portrait_applies(bytes(src), pitch, sw, sh, KEY, 40)


@pytest.mark.parametrize("fac", FACTIONS)
@pytest.mark.parametrize("slot", list(SLOTS))
def test_every_leader_portrait_qualifies(fac, slot):
    im = _sheet(fac)
    x, y, w, h = SLOTS[slot]
    src = im.crop((x, y, x + w, y + h)).tobytes()
    assert SL.portrait_applies(src, w, w, h, KEY, 40)


@pytest.mark.parametrize("face", NATIVE_FACES)
def test_every_native_face_qualifies(face):
    im = _sheet(face)
    w, h = im.size
    assert SL.portrait_applies(im.tobytes(), w, w, h, KEY, 40)


@pytest.mark.parametrize("fac", FACTIONS)
@pytest.mark.parametrize("cell", [0, 1], ids=["normal", "hover"])
def test_no_council_logo_qualifies(fac, cell):
    src, w, h = trimmed(_sheet(fac), LOGO_CELLS[cell])
    for g in (17, 22, 25, 40):
        assert not SL.portrait_applies(src, w, w, h, KEY, g), (fac, w, h)


@pytest.mark.parametrize("cell", [0, 1], ids=["normal", "hover"])
def test_spartan_logo_is_portrait_shaped_but_refused_by_the_ring(cell):
    """The regression: the shape gate alone takes it (h > w >= PORTRAIT_MIN_W); only the ring refuses it."""
    src, w, h = trimmed(_sheet("spartans"), LOGO_CELLS[cell])
    assert w == 62 and h in (71, 72) and h > w >= SL.PORTRAIT_MIN_W
    assert not SL.portrait_ring_opaque(src, w, w, h, KEY)
