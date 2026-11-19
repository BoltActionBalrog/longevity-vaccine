"""patch_icons.py: PRACX's icon art added to a stock GOG Icons.pcx (longevity-vaccine issue #7).

The rule under test above all: a sheet that is not exactly a known stock sheet -- PRACX's own (every variant),
a custom sheet, the colour-blind sheet, a damaged file -- is never written, and uninstall puts back only a sheet
that is still exactly ours.

Synthetic sheets stand in for the game's (its art is not in this repository): a "stock" sheet with blank PRACX
rectangles, whose hash is registered in KNOWN_STOCK / EXPECTED_RESULT for the test. When the game folder and the
PRACX reference checkout are present, the real files are checked too.
"""
from __future__ import annotations

import hashlib
import pathlib
import random
import shutil
import stat
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: E402
import patch_icons as pi  # noqa: E402

OVERLAY = ROOT / "art" / "pracx_icons_overlay.pcx"
PRACX_RESOURCES = REPO / "refs" / "pracx" / "resources"
BG = 253


def _in_copy_rects(x: int, y: int) -> bool:
    return any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in pi.COPY_RECTS)


def _header() -> bytes:
    h = bytearray(pi.HEADER_LEN)
    struct.pack_into("<BBBBHHHHHH", h, 0, 10, 5, 1, 8, 0, 0, pi.W - 1, pi.H - 1, 800, 600)
    struct.pack_into("<BHH", h, 65, 1, pi.W, 0)
    return bytes(h)


def _palette(seed: int = 1) -> bytes:
    r = random.Random(seed)
    return b"\x0c" + bytes(r.randrange(256) for _ in range(768))


@pytest.fixture(scope="module")
def overlay_px() -> bytes:
    return pi.load_overlay(OVERLAY)


@pytest.fixture(scope="module")
def stock_px() -> bytes:
    """A sheet like GOG's: art (with runs and literals >= 0xC0) everywhere except PRACX's rectangles."""
    r = random.Random(7)
    px = bytearray(r.choice((BG, BG, BG, r.randrange(256))) for _ in range(pi.W * pi.H))
    for x0, y0, x1, y1 in pi.COPY_RECTS:
        for y in range(y0, y1):
            px[y * pi.W + x0:y * pi.W + x1] = bytes((BG,)) * (x1 - x0)
    return bytes(px)


@pytest.fixture
def stock(monkeypatch, stock_px, overlay_px) -> bytes:
    """The synthetic stock sheet's file bytes, registered as known stock for this test."""
    h = pi.pixel_hash(stock_px)
    monkeypatch.setitem(pi.KNOWN_STOCK, h, "synthetic stock")
    monkeypatch.setitem(pi.EXPECTED_RESULT, h, pi.pixel_hash(pi.compose(stock_px, overlay_px)))
    return pi.encode(_header(), stock_px, _palette())


def _game(tmp_path: pathlib.Path, data: bytes) -> pathlib.Path:
    g = tmp_path / "game"
    g.mkdir()
    (g / pi.SHEET).write_bytes(data)
    return g


def _quiet(*_a) -> None:
    pass


# ---------------------------------------------------------------- the overlay and the rectangles

def test_the_overlay_is_the_recorded_file() -> None:
    assert hashlib.sha256(OVERLAY.read_bytes()).hexdigest() == pi.OVERLAY_SHA256, \
        "the overlay changed: rebuild it with make_pracx_icons_overlay.py and record OVERLAY_SHA256 / EXPECTED_RESULT"


def test_the_overlay_holds_nothing_outside_pracx_rectangles(overlay_px) -> None:
    """Only PRACX's (CC0) art may be in the file we ship: every pixel outside COPY_RECTS is one background index."""
    outside = {overlay_px[y * pi.W + x] for y in range(pi.H) for x in range(pi.W) if not _in_copy_rects(x, y)}
    assert len(outside) == 1, f"the overlay carries art outside PRACX's rectangles: {sorted(outside)[:10]}"
    inside = {overlay_px[yy * pi.W + xx] for x, y, w, h in pi.READ_RECTS
              for yy in range(y, y + h) for xx in range(x, x + w)}
    assert len(inside) > 10, "the overlay's PRACX rectangles are empty"


def test_the_recorded_art_hash_is_the_overlays(overlay_px) -> None:
    assert hashlib.sha256(pi.rect_bytes(overlay_px)).hexdigest() == pi.ART_RECT_SHA256
    assert pi.has_the_art(overlay_px)


@pytest.mark.skipif(not (REPO / "refs" / "pracx" / "shared" / "pracx.cpp").is_file(), reason="no PRACX reference checkout")
def test_read_rects_are_what_pracx_loads() -> None:
    """READ_RECTS is a port of PRACXLoadIcons: rebuild it from the source's own loops, so a wrong rectangle list
    cannot pass by re-recording the hashes."""
    import re
    src = (REPO / "refs" / "pracx" / "shared" / "pracx.cpp").read_text(encoding="utf-8", errors="replace")
    body = src[src.index("int __stdcall PRACXLoadIcons"):]
    body = body[:body.index("return m_pAC->pfncCanvasDestroy4")]
    grey = re.search(r"for \(int y = 0; y < (\d+).*?for \(int x = 0; x < (\d+).*?poLoadingCanvas, 0x109,\s*"
                     r"x \* (\d+), y \* (\d+) \+ (\d+), (\d+), (\d+)", body, re.S)
    ny, nx, sx, sy, oy, w, h = map(int, grey.groups())
    rects = [(x * sx, y * sy + oy, w, h) for y in range(ny) for x in range(nx)]
    found = 0
    for m in re.finditer(r"for \(int x = 0; x < (\d+); x\+\+\)\s*m_pAC->pfncImageFromCanvas\(&m_aimg\w+\[x\], "
                         r"m_pAC->poLoadingCanvas,\s*x \* (\d+) \+ (\d+), (\d+), (\d+), (\d+)", body):
        n, sx, ox, y, w, h = map(int, m.groups())
        rects += [(x * sx + ox, y, w, h) for x in range(n)]
        found += 1
    assert found == 4, f"expected 4 swatch loops in PRACXLoadIcons, found {found}"
    assert sorted(rects) == sorted(pi.READ_RECTS), "READ_RECTS no longer matches PRACXLoadIcons"


def test_copy_rects_are_the_read_rects_with_a_border() -> None:
    assert len(pi.READ_RECTS) == 42
    for (x, y, w, h), (x0, y0, x1, y1) in zip(pi.READ_RECTS, pi.COPY_RECTS):
        assert (x0, y0) == (max(0, x - 1), max(0, y - 1)) and (x1, y1) == (min(pi.W, x + w + 1), min(pi.H, y + h + 1))
        assert 0 <= x0 < x1 <= pi.W and 0 <= y0 < y1 <= pi.H


# ---------------------------------------------------------------- the codec

def test_encode_decode_round_trip(stock, stock_px) -> None:
    h, px, pal = pi.decode(stock)
    assert px == stock_px and h == _header() and pal == _palette()
    assert pi.encode(h, px, pal) == stock
    ov = OVERLAY.read_bytes()
    assert pi.encode(*pi.decode(ov)) == ov


@pytest.mark.parametrize("damage", ["short", "size", "bpp", "no-palette", "trailing", "early-end", "cross-line"])
def test_decode_refuses_what_it_cannot_rewrite_exactly(stock, damage) -> None:
    d = bytearray(stock)
    if damage == "short":
        d = d[:500]
    elif damage == "size":
        struct.pack_into("<H", d, 8, 639)
    elif damage == "bpp":
        d[3] = 4
    elif damage == "no-palette":
        d[-769] = 0
    elif damage == "trailing":
        d[-769:-769] = b"\x01"
    elif damage == "early-end":
        del d[pi.HEADER_LEN + 10:pi.HEADER_LEN + 20]
    elif damage == "cross-line":
        # first scanline as 12 runs of 63 + one of 50 + one run of 63 that would spill into row 2
        body = bytes((0xC0 | 63, 1)) * 12 + bytes((0xC0 | 50, 1)) + bytes((0xC0 | 63, 1))
        d = bytearray(_header()) + body + bytes(stock[pi.HEADER_LEN + len(body):])
    with pytest.raises(pi.SheetError):
        pi.decode(bytes(d))


# ---------------------------------------------------------------- install

def test_a_stock_sheet_gets_the_art_and_nothing_else_changes(tmp_path, stock, stock_px, overlay_px) -> None:
    g = _game(tmp_path, stock)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.ADDED}
    out = (g / pi.SHEET).read_bytes()
    h, px, pal = pi.decode(out)
    assert (h, pal) == (_header(), _palette()), "header or palette changed"
    changed = [i for i in range(pi.W * pi.H) if px[i] != stock_px[i]]
    assert changed, "nothing was added"
    assert all(_in_copy_rects(i % pi.W, i // pi.W) for i in changed), "a pixel outside PRACX's rectangles changed"
    assert pi.has_the_art(px)
    assert pi.backup_of(g / pi.SHEET).read_bytes() == stock
    assert not list(g.glob("*.longevity-tmp"))
    # idempotent
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.CURRENT}
    assert (g / pi.SHEET).read_bytes() == out


def test_check_mode_writes_nothing(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    assert pi.patch_folder(g, OVERLAY, check=True, say=_quiet) == {pi.SHEET: pi.ADDED}
    assert (g / pi.SHEET).read_bytes() == stock and not pi.backup_of(g / pi.SHEET).exists()


def test_a_sheet_that_already_has_the_art_is_not_touched(tmp_path, stock_px, overlay_px) -> None:
    """PRACX's own installer's sheet: the art is there; no write, no backup."""
    data = pi.encode(_header(), pi.compose(stock_px, overlay_px), _palette(3))
    g = _game(tmp_path, data)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.CURRENT}
    assert (g / pi.SHEET).read_bytes() == data and not pi.backup_of(g / pi.SHEET).exists()


def test_a_sheet_with_other_art_in_pracx_rectangles_is_not_touched(tmp_path, stock, stock_px) -> None:
    """Another PRACX variant (dark-grey, scanlines, ...) or a player's own icons: left exactly as they are, even
    when the rest of the sheet is the known stock."""
    px = bytearray(stock_px)
    x0, y0, x1, y1 = pi.COPY_RECTS[5]
    px[(y0 + 3) * pi.W + x0 + 3] = 17
    data = pi.encode(_header(), bytes(px), _palette())
    g = _game(tmp_path, data)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.HAS_ART}
    assert (g / pi.SHEET).read_bytes() == data and not pi.backup_of(g / pi.SHEET).exists()


def test_an_unknown_sheet_with_blank_rectangles_is_not_touched(tmp_path, stock_px) -> None:
    """Blank where PRACX reads, but not a known stock sheet (another edition, the colour-blind sheet): left alone."""
    px = bytearray(stock_px)
    px[0] ^= 1
    data = pi.encode(_header(), bytes(px), _palette())
    g = _game(tmp_path, data)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.FOREIGN}
    assert (g / pi.SHEET).read_bytes() == data and not pi.backup_of(g / pi.SHEET).exists()


def test_an_unreadable_sheet_is_not_touched(tmp_path) -> None:
    data = b"not a pcx" * 200
    g = _game(tmp_path, data)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.FOREIGN}
    assert (g / pi.SHEET).read_bytes() == data and not pi.backup_of(g / pi.SHEET).exists()


def test_a_wrong_overlay_writes_nothing(tmp_path, stock) -> None:
    bad = tmp_path / "overlay.pcx"
    d = bytearray(OVERLAY.read_bytes())
    d[300] ^= 0x01
    bad.write_bytes(bytes(d))
    g = _game(tmp_path, stock)
    # MISSING_ART, not FAILED: the art is not this installer's, so read-only advice would be wrong (2026-11-18).
    assert pi.patch_folder(g, bad, say=_quiet) == {pi.SHEET: pi.MISSING_ART}
    assert pi.patch_folder(g, tmp_path / "missing.pcx", say=_quiet) == {pi.SHEET: pi.MISSING_ART}
    assert (g / pi.SHEET).read_bytes() == stock and not pi.backup_of(g / pi.SHEET).exists()


def test_a_result_that_does_not_check_out_is_not_written(tmp_path, monkeypatch, stock, stock_px) -> None:
    monkeypatch.setitem(pi.EXPECTED_RESULT, pi.pixel_hash(stock_px), "0" * 64)
    g = _game(tmp_path, stock)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.FOREIGN}
    assert (g / pi.SHEET).read_bytes() == stock and not pi.backup_of(g / pi.SHEET).exists()


def test_no_sheet_is_no_result(tmp_path) -> None:
    g = tmp_path / "game"
    g.mkdir()
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {}
    assert pi.restore_folder(g, say=_quiet) == {}


def test_a_read_only_sheet_fails_cleanly(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    sheet = g / pi.SHEET
    sheet.chmod(stat.S_IREAD)
    try:
        assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.FAILED}
        assert sheet.read_bytes() == stock
        assert not pi.tmp_of(sheet).exists(), "a failed write left its temporary file behind"
    finally:
        sheet.chmod(stat.S_IREAD | stat.S_IWRITE)
    # the backup left behind is the original; a later uninstall drops it without touching the sheet
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}
    assert sheet.read_bytes() == stock and not pi.backup_of(sheet).exists()


# ---------------------------------------------------------------- uninstall

def test_uninstall_puts_the_original_back(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    pi.patch_folder(g, OVERLAY, say=_quiet)
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.RESTORED}
    assert (g / pi.SHEET).read_bytes() == stock and not pi.backup_of(g / pi.SHEET).exists()
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}


def test_uninstall_leaves_a_sheet_changed_since(tmp_path, stock_px, stock) -> None:
    """The player put PRACX's (or their own) sheet in after the install: theirs stays, and so does the backup."""
    g = _game(tmp_path, stock)
    pi.patch_folder(g, OVERLAY, say=_quiet)
    theirs = pi.encode(_header(), bytes(stock_px[:-1]) + b"\x05", _palette())
    (g / pi.SHEET).write_bytes(theirs)
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}
    assert (g / pi.SHEET).read_bytes() == theirs and pi.backup_of(g / pi.SHEET).read_bytes() == stock


def test_uninstall_ignores_a_backup_that_is_not_stock(tmp_path, stock_px, stock, overlay_px) -> None:
    ours = pi.encode(_header(), pi.compose(stock_px, overlay_px), _palette())
    g = _game(tmp_path, ours)
    foreign = pi.encode(_header(), bytes(stock_px[:-1]) + b"\x09", _palette())
    pi.backup_of(g / pi.SHEET).write_bytes(foreign)
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}
    assert (g / pi.SHEET).read_bytes() == ours and pi.backup_of(g / pi.SHEET).read_bytes() == foreign


def test_uninstall_after_a_gog_repair_only_drops_the_spare_backup(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    pi.patch_folder(g, OVERLAY, say=_quiet)
    (g / pi.SHEET).write_bytes(stock)          # GOG's "Verify / Repair" put the stock sheet back
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}
    assert (g / pi.SHEET).read_bytes() == stock and not pi.backup_of(g / pi.SHEET).exists()


# ---------------------------------------------------------------- the real files, when present

def _real_game() -> pathlib.Path | None:
    g = config.game_dir(required=False)
    return pathlib.Path(g) if g and (pathlib.Path(g) / pi.SHEET).is_file() else None


def test_every_known_stock_sheet_has_a_recorded_result() -> None:
    assert set(pi.KNOWN_STOCK) == set(pi.EXPECTED_RESULT)
    assert set(pi.PREVIOUS_RESULTS) <= set(pi.KNOWN_STOCK)
    for stock, olds in pi.PREVIOUS_RESULTS.items():
        assert pi.EXPECTED_RESULT[stock] not in olds, "the current result is listed as an earlier one"


@pytest.mark.skipif(_real_game() is None, reason="no game folder")
def test_the_real_gog_sheet(tmp_path, overlay_px) -> None:
    """The live game's Icons.pcx (copied, never written): if it is the known stock sheet, the result is the recorded
    one and matches PRACX's own sheet in every rectangle PRACX reads."""
    src = _real_game() / pi.SHEET
    data = src.read_bytes()
    h, px, pal = pi.decode(data)
    assert pi.encode(h, px, pal) == data, "the codec does not reproduce the game's file"
    if pi.pixel_hash(px) not in pi.KNOWN_STOCK:
        pytest.skip("this game folder's Icons.pcx is not the stock sheet")
    assert pi.area_is_blank(px)
    out = pi.compose(px, overlay_px)
    assert pi.pixel_hash(out) == pi.EXPECTED_RESULT[pi.pixel_hash(px)]
    pracx = PRACX_RESOURCES / "Icons.pcx"
    if pracx.is_file():
        ref = pi.decode(pracx.read_bytes())[1]
        for x, y, w, hh in pi.READ_RECTS:
            for yy in range(y, y + hh):
                assert out[yy * pi.W + x:yy * pi.W + x + w] == ref[yy * pi.W + x:yy * pi.W + x + w]
    g = _game(tmp_path, data)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.ADDED}
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.RESTORED}
    assert (g / pi.SHEET).read_bytes() == data


@pytest.mark.skipif(not PRACX_RESOURCES.is_dir(), reason="no PRACX reference checkout")
@pytest.mark.parametrize("name", sorted(p.name for p in PRACX_RESOURCES.glob("Icons*.pcx")) if PRACX_RESOURCES.is_dir()
                         else ["-"])
def test_every_pracx_sheet_is_left_alone(tmp_path, name) -> None:
    """A valid PRACX install keeps its sheet byte for byte, whichever of PRACX's variants it carries."""
    data = (PRACX_RESOURCES / name).read_bytes()
    g = _game(tmp_path, data)
    assert pi.patch_folder(g, OVERLAY, say=_quiet)[pi.SHEET] in (pi.CURRENT, pi.HAS_ART)
    assert (g / pi.SHEET).read_bytes() == data and not pi.backup_of(g / pi.SHEET).exists()
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}
    assert (g / pi.SHEET).read_bytes() == data


@pytest.mark.skipif(_real_game() is None or not (_real_game() / "Color Blind Palette" / pi.SHEET).is_file(),
                    reason="no GOG colour-blind sheet")
def test_the_colour_blind_sheet_is_left_alone(tmp_path) -> None:
    data = (_real_game() / "Color Blind Palette" / pi.SHEET).read_bytes()
    g = _game(tmp_path, data)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.FOREIGN}
    assert (g / pi.SHEET).read_bytes() == data


def test_a_sheet_held_open_fails_cleanly(tmp_path, stock) -> None:
    """The game running holds the file: the write fails, and nothing is left half-done or behind."""
    g = _game(tmp_path, stock)
    sheet = g / pi.SHEET
    with open(sheet, "rb"):
        res = pi.patch_folder(g, OVERLAY, say=_quiet)
    if res == {pi.SHEET: pi.ADDED}:
        pytest.skip("this filesystem lets an open file be replaced")
    assert res == {pi.SHEET: pi.FAILED} and sheet.read_bytes() == stock and not pi.tmp_of(sheet).exists()


def test_a_failed_backup_write_leaves_nothing_behind(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    bak = pi.backup_of(g / pi.SHEET)
    bak.mkdir()                                  # the backup cannot be written
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.FAILED}
    assert (g / pi.SHEET).read_bytes() == stock, "the sheet changed without a backup"
    assert not pi.tmp_of(bak).exists()


def test_without_the_overlay_a_sheet_that_has_the_art_is_still_current(tmp_path, stock_px, overlay_px) -> None:
    """A resident updater from before the overlay shipped has no art file: it must still tell a finished sheet, and
    a PRACX sheet, apart from a broken installer -- no false "missing" message."""
    missing = tmp_path / "no-overlay.pcx"
    lines = []
    g = _game(tmp_path, pi.encode(_header(), pi.compose(stock_px, overlay_px), _palette()))
    assert pi.patch_folder(g, missing, say=lines.append) == {pi.SHEET: pi.CURRENT}
    other = tmp_path / "other"
    other.mkdir()
    px = bytearray(stock_px)
    px[pi.COPY_RECTS[0][1] * pi.W + pi.COPY_RECTS[0][0] + 5] = 17
    (other / pi.SHEET).write_bytes(pi.encode(_header(), bytes(px), _palette()))
    assert pi.patch_folder(other, missing, say=lines.append) == {pi.SHEET: pi.HAS_ART}
    assert not [t for t in lines if "missing" in t], lines


def _older_release(monkeypatch, stock_px, overlay_px):
    """Pretend an earlier release wrote different art: its result is registered in PREVIOUS_RESULTS."""
    old_overlay = bytearray(overlay_px)
    x0, y0, x1, y1 = pi.COPY_RECTS[0]
    old_overlay[(y0 + 10) * pi.W + x0 + 10] ^= 0x21
    old_px = pi.compose(stock_px, bytes(old_overlay))
    monkeypatch.setitem(pi.PREVIOUS_RESULTS, pi.pixel_hash(stock_px), {pi.pixel_hash(old_px)})
    return pi.encode(_header(), old_px, _palette())


def test_a_sheet_an_older_release_patched_is_rebuilt(tmp_path, monkeypatch, stock, stock_px, overlay_px) -> None:
    old = _older_release(monkeypatch, stock_px, overlay_px)
    g = _game(tmp_path, old)
    pi.backup_of(g / pi.SHEET).write_bytes(stock)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.ADDED}
    assert pi.has_the_art(pi.decode((g / pi.SHEET).read_bytes())[1])
    assert pi.backup_of(g / pi.SHEET).read_bytes() == stock
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.RESTORED}
    assert (g / pi.SHEET).read_bytes() == stock


def test_an_older_release_sheet_without_its_backup_is_left_alone(tmp_path, monkeypatch, stock_px, overlay_px) -> None:
    old = _older_release(monkeypatch, stock_px, overlay_px)
    g = _game(tmp_path, old)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.HAS_ART}
    assert (g / pi.SHEET).read_bytes() == old and not pi.backup_of(g / pi.SHEET).exists()


def test_uninstall_restores_an_older_release_sheet(tmp_path, monkeypatch, stock, stock_px, overlay_px) -> None:
    old = _older_release(monkeypatch, stock_px, overlay_px)
    g = _game(tmp_path, old)
    pi.backup_of(g / pi.SHEET).write_bytes(stock)
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.RESTORED}
    assert (g / pi.SHEET).read_bytes() == stock


def test_uninstall_removes_a_leftover_temporary_file(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    pi.tmp_of(g / pi.SHEET).write_bytes(b"half")
    pi.restore_folder(g, say=_quiet)
    assert not pi.tmp_of(g / pi.SHEET).exists()


def test_uninstall_drops_an_unreadable_backup_beside_the_original(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    pi.backup_of(g / pi.SHEET).write_bytes(b"truncated")
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}
    assert (g / pi.SHEET).read_bytes() == stock and not pi.backup_of(g / pi.SHEET).exists()


def test_uninstall_keeps_an_unreadable_backup_beside_a_sheet_it_did_not_write(tmp_path, stock_px) -> None:
    theirs = pi.encode(_header(), bytes(stock_px[:-1]) + b"\x05", _palette())
    g = _game(tmp_path, theirs)
    pi.backup_of(g / pi.SHEET).write_bytes(b"truncated")
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}
    assert (g / pi.SHEET).read_bytes() == theirs and pi.backup_of(g / pi.SHEET).read_bytes() == b"truncated"



#: Every result this module has written, per stock sheet. When the art changes, EXPECTED_RESULT gets the new value:
#: this test then fails until the old value is moved into PREVIOUS_RESULTS (or a sheet patched by the older release
#: would read as "has its own art", keep its backup forever, and never be restored) and the new one is recorded here.
RESULT_HISTORY = {
    "5150057a128f8dd9605988b01b9bea26081ca7920ea651eac8f8449110155fa5": [
        "6d0372118a9d86197d05114d882be275819d78aaf1cb3985f41a6c580ecc4e23",   # PRACX 1.11 art (2026-11-14)
    ],
}


def test_every_result_ever_written_is_still_recognised() -> None:
    assert set(RESULT_HISTORY) == set(pi.EXPECTED_RESULT)
    for stock, history in RESULT_HISTORY.items():
        assert pi.EXPECTED_RESULT[stock] == history[-1], \
            "EXPECTED_RESULT changed: append the new value to RESULT_HISTORY and move the old one into PREVIOUS_RESULTS"
        assert set(history[:-1]) <= set(pi.PREVIOUS_RESULTS.get(stock, ())), \
            "an earlier release's result is missing from PREVIOUS_RESULTS"


def test_a_restore_whose_backup_cannot_be_deleted_is_still_a_restore(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    pi.patch_folder(g, OVERLAY, say=_quiet)
    bak = pi.backup_of(g / pi.SHEET)
    bak.chmod(stat.S_IREAD)
    try:
        lines = []
        assert pi.restore_folder(g, say=lines.append) == {pi.SHEET: pi.RESTORED}
        assert (g / pi.SHEET).read_bytes() == stock
        assert "deleted by hand" in lines[0], lines
    finally:
        bak.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("how", ["missing", "empty", "zeroed"])
def test_a_lost_sheet_is_rebuilt_from_a_stock_backup(tmp_path, stock, how) -> None:
    """A power cut can leave a renamed file of zeros; a player can delete the file. With our stock backup beside it,
    install rebuilds the sheet and uninstall puts the original back."""
    g = _game(tmp_path, stock)
    pi.patch_folder(g, OVERLAY, say=_quiet)
    sheet = g / pi.SHEET

    def lose():
        if how == "missing":
            sheet.unlink()
        else:
            sheet.write_bytes(b"" if how == "empty" else bytes(48066))
    lose()
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.ADDED}
    assert pi.has_the_art(pi.decode(sheet.read_bytes())[1])
    lose()
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.RESTORED}
    assert sheet.read_bytes() == stock and not pi.backup_of(sheet).exists()


def test_a_lost_sheet_without_a_stock_backup_is_left_alone(tmp_path, stock_px) -> None:
    g = tmp_path / "game"
    g.mkdir()
    (g / pi.SHEET).write_bytes(bytes(100))
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.FOREIGN}
    assert (g / pi.SHEET).read_bytes() == bytes(100)
    theirs = pi.encode(_header(), bytes(stock_px[:-1]) + b"\x05", _palette())
    pi.backup_of(g / pi.SHEET).write_bytes(theirs)
    assert pi.patch_folder(g, OVERLAY, say=_quiet) == {pi.SHEET: pi.FOREIGN}
    assert pi.restore_folder(g, say=_quiet) == {pi.SHEET: pi.UNPATCHED}
    assert (g / pi.SHEET).read_bytes() == bytes(100) and pi.backup_of(g / pi.SHEET).read_bytes() == theirs


def test_uninstall_removes_the_backups_leftover_temporary_file(tmp_path, stock) -> None:
    g = _game(tmp_path, stock)
    pi.tmp_of(pi.backup_of(g / pi.SHEET)).write_bytes(b"half")
    pi.restore_folder(g, say=_quiet)
    assert not pi.tmp_of(pi.backup_of(g / pi.SHEET)).exists()
