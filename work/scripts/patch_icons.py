"""Add PRACX's own icon art to a GOG Planetary Pack Icons.pcx that lacks it.

PRACX (prax.dll, PRACXLoadIcons) copies 42 rectangles out of the Icons.pcx the game loads: 24 grey
yield icons (40x40 at x*41, 150+y*41), which it draws on unworked base tiles ("Show Unworked City
Resources"), and 18 swatches (56x56) for its territory / elevation / rainfall / rockiness map views.
PRACX's own installer writes a sheet that holds them. GOG's Planetary Pack installs PRACX 1.11 but keeps
the stock sheet, where those rectangles are empty background: PRACX copies blank sprites and the
overlays draw nothing (longevity-vaccine issue #7).

This module copies exactly those rectangles (each with a 1-pixel border, PRACX's grid lines) from
art/pracx_icons_overlay.pcx into the player's Icons.pcx. Nothing else in the file changes: header,
palette and every other pixel stay as they were.

It touches ONLY a sheet whose pixels are exactly a known stock sheet that lacks the art (KNOWN_STOCK).
Any other Icons.pcx -- PRACX's own (any of its variants), a custom sheet, the colour-blind sheet, an
unreadable file -- is left exactly as it is and reported, never a failure. The first change saves
Icons.pcx.longevity.bak; restore_folder() puts it back only while the live file is still exactly our
result.

Usage:  py patch_icons.py            apply (idempotent)
        py patch_icons.py --restore  put the backup back
        py patch_icons.py --check    report only
The installer (install.py) calls patch_folder() on every install / update run and restore_folder()
on --uninstall.
"""
import hashlib
import os
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

SHEET = "Icons.pcx"
W, H = 800, 600
HEADER_LEN = 128
PALETTE_LEN = 769            # 0x0C marker + 256 RGB triples

#: The rectangles PRACXLoadIcons copies (x, y, w, h): pracx.cpp, PRACX 1.11.
READ_RECTS = (
    tuple((x * 41, 150 + y * 41, 40, 40) for y in range(3) for x in range(8))    # grey yield icons
    + tuple((x * 57 + 1, 429, 56, 56) for x in range(8))                         # faction colours
    + tuple((x * 57 + 1, 372, 56, 56) for x in range(3))                         # rainfall
    + tuple((x * 57 + 229, 486, 56, 56) for x in range(4))                       # elevation
    + tuple((x * 57 + 229, 543, 56, 56) for x in range(3))                       # rockiness
)

#: What is copied: each read rectangle plus a 1-pixel border, clipped to the sheet (x0, y0, x1, y1).
COPY_RECTS = tuple((max(0, x - 1), max(0, y - 1), min(W, x + w + 1), min(H, y + h + 1))
                   for x, y, w, h in READ_RECTS)

#: sha256 of the decoded 800x600 pixel indices of a stock sheet this module may change -> what it is.
#: Only these are ever written to. Every one is empty background over all of COPY_RECTS.
KNOWN_STOCK = {
    "5150057a128f8dd9605988b01b9bea26081ca7920ea651eac8f8449110155fa5": "GOG Planetary Pack Icons.pcx (file md5 c57db4c2)",
}

#: sha256 of the decoded pixels of KNOWN_STOCK's sheet after the copy. The write is refused unless the
#: result matches, so a wrong overlay or a codec fault can never reach the player's file.
EXPECTED_RESULT = {
    "5150057a128f8dd9605988b01b9bea26081ca7920ea651eac8f8449110155fa5":
        "6d0372118a9d86197d05114d882be275819d78aaf1cb3985f41a6c580ecc4e23",
}

#: Results an EARLIER release wrote from the same stock sheet (stock hash -> set of result hashes). When the art
#: changes, move the old EXPECTED_RESULT value here: a sheet an older release patched is then still recognised as
#: ours -- rebuilt from its backup on install, put back on uninstall -- instead of looking like a player's own art.
PREVIOUS_RESULTS: dict = {}

#: sha256 of the overlay file this module was written against (work/art/pracx_icons_overlay.pcx).
OVERLAY_SHA256 = "e97fb75e84280f5c2eaf91b9db891e4214a14acb20ced67fc224a497a00b5dad"

#: sha256 of PRACX's art over COPY_RECTS (rect_bytes of the overlay): a sheet whose rectangles hash to this already
#: has the art, which is told without the overlay file (a resident updater from before it shipped has none).
ART_RECT_SHA256 = "726156c5305a1e9c2f355a47ec53a58d598e65d1a1f37310b2bb3d7e97236e80"

ADDED, CURRENT, FOREIGN, HAS_ART, RESTORED, UNPATCHED, NO_BACKUP, FAILED = (
    "added", "current", "foreign", "has-art", "restored", "unpatched", "no-backup", "failed")
#: The art is not in this installer (or is not the expected file): nothing was tried on the sheet, and running the
#: same installer again cannot help -- unlike FAILED, a write that did not go through.
MISSING_ART = "missing-art"


class SheetError(ValueError):
    """Not an Icons.pcx this module can read (wrong size/format, damaged RLE)."""


def decode(data: bytes) -> tuple:
    """(header, pixels, palette) of an 800x600 8-bit single-plane RLE PCX; SheetError otherwise.

    Strict: the RLE stream must end exactly where the palette starts and no run may cross a scanline,
    so a file this cannot re-encode byte-for-byte is refused rather than rewritten."""
    if len(data) < HEADER_LEN + PALETTE_LEN:
        raise SheetError("too short")
    man, ver, enc, bpp, x0, y0, x1, y1 = struct.unpack_from("<BBBBHHHH", data, 0)
    planes, bpl = struct.unpack_from("<BH", data, 65)
    if (man, enc, bpp, planes) != (10, 1, 8, 1) or (x0, y0, x1, y1) != (0, 0, W - 1, H - 1) or bpl != W:
        raise SheetError(f"not an 800x600 8-bit PCX (version {ver}, {x1 - x0 + 1}x{y1 - y0 + 1}, "
                         f"{bpp} bpp, {planes} plane(s), {bpl} bytes/line)")
    end = len(data) - PALETTE_LEN
    if data[end] != 0x0C:
        raise SheetError("no 256-colour palette")
    out = bytearray()
    i = HEADER_LEN
    for _row in range(H):
        line_end = len(out) + W
        while len(out) < line_end:
            if i >= end:
                raise SheetError("pixel data ends early")
            b = data[i]
            i += 1
            if b >= 0xC0:
                if i >= end:
                    raise SheetError("pixel data ends early")
                n = b & 0x3F
                if len(out) + n > line_end:
                    raise SheetError("a run crosses a scanline")
                out += bytes((data[i],)) * n
                i += 1
            else:
                out.append(b)
    if i != end:
        raise SheetError("extra bytes after the pixel data")
    return data[:HEADER_LEN], bytes(out), data[end:]


def encode(header: bytes, pixels: bytes, palette: bytes) -> bytes:
    """The standard PCX RLE (runs of up to 63 within a scanline; a literal >= 0xC0 as a run of 1).
    decode(encode(...)) is the identity, and encode(*decode(f)) == f for the game's own sheets."""
    assert len(header) == HEADER_LEN and len(palette) == PALETTE_LEN and len(pixels) == W * H
    out = bytearray(header)
    for y in range(H):
        line = pixels[y * W:(y + 1) * W]
        j = 0
        while j < W:
            v = line[j]
            n = 1
            while j + n < W and n < 63 and line[j + n] == v:
                n += 1
            if n > 1 or v >= 0xC0:
                out += bytes((0xC0 | n, v))
            else:
                out.append(v)
            j += n
    return bytes(out) + palette


def pixel_hash(pixels: bytes) -> str:
    return hashlib.sha256(pixels).hexdigest()


def compose(pixels: bytes, overlay: bytes) -> bytes:
    """`pixels` with every COPY_RECTS rectangle taken from `overlay` (both decoded 800x600)."""
    out = bytearray(pixels)
    for x0, y0, x1, y1 in COPY_RECTS:
        for y in range(y0, y1):
            out[y * W + x0:y * W + x1] = overlay[y * W + x0:y * W + x1]
    return bytes(out)


def rect_bytes(pixels: bytes) -> bytes:
    """The pixels inside COPY_RECTS, row by row, rectangle by rectangle."""
    return b"".join(pixels[y * W + x0:y * W + x1] for x0, y0, x1, y1 in COPY_RECTS for y in range(y0, y1))


def has_the_art(pixels: bytes) -> bool:
    """Every copied rectangle already holds PRACX's art (PRACX's own sheet, or one this module wrote)."""
    return hashlib.sha256(rect_bytes(pixels)).hexdigest() == ART_RECT_SHA256


def area_is_blank(pixels: bytes) -> bool:
    """Every copied rectangle is one colour, the sheet's background at the first rectangle's corner."""
    bg = pixels[COPY_RECTS[0][1] * W + COPY_RECTS[0][0]]
    return all(b == bg for b in rect_bytes(pixels))


def _results_of(stock: str) -> set:
    """Every result hash this module (this release or an earlier one) writes from `stock`."""
    return {EXPECTED_RESULT[stock]} | set(PREVIOUS_RESULTS.get(stock, ()))


def _older_result_stock(h: str):
    """The stock sheet an EARLIER release's result `h` was made from, or None."""
    return next((stock for stock, olds in PREVIOUS_RESULTS.items() if h in olds), None)


def backup_of(path: pathlib.Path) -> pathlib.Path:
    return path.with_name(path.name + ".longevity.bak")


def tmp_of(path: pathlib.Path) -> pathlib.Path:
    return path.with_name(path.name + ".longevity-tmp")


def load_overlay(path: pathlib.Path) -> bytes:
    """The overlay's decoded pixels; SheetError when the file is not the one this module expects."""
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != OVERLAY_SHA256:
        raise SheetError(f"{path.name} is not the expected file")
    return decode(data)[1]


def _write_atomic(path: pathlib.Path, data: bytes) -> None:
    """Write next to `path`, then swap it in: `path` is never left half-written, and a failed write (a locked or
    read-only file, a full disk) leaves no temporary file behind."""
    tmp = tmp_of(path)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())           # on disk before the swap: a power cut cannot leave a renamed empty file
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _stock_backup(bak: pathlib.Path, header: bytes, palette: bytes, stock: str):
    """The backup's bytes when it is exactly `stock` with the live file's header and palette, else None."""
    if not bak.is_file():
        return None
    data = bak.read_bytes()
    try:
        h, px, pal = decode(data)
    except SheetError:
        return None
    return data if (h, pal) == (header, palette) and pixel_hash(px) == stock else None


def _wiped(path: pathlib.Path) -> bool:
    """Missing, empty, or nothing but zero bytes: what a lost write leaves, never a sheet anyone made."""
    if not path.is_file():
        return True
    data = path.read_bytes()
    return data.count(0) == len(data)


def _any_stock_backup(bak: pathlib.Path):
    """The backup's bytes when it decodes to a known stock sheet, else None."""
    if not bak.is_file():
        return None
    data = bak.read_bytes()
    try:
        return data if pixel_hash(decode(data)[1]) in KNOWN_STOCK else None
    except SheetError:
        return None


def _clear_temps(path: pathlib.Path) -> None:
    """An interrupted write's leftovers, beside the sheet or beside its backup (the names are ours)."""
    for t in (tmp_of(path), tmp_of(backup_of(path))):
        if t.is_file():
            t.unlink()


def patch_file_status(path: pathlib.Path, load, check: bool = False) -> tuple:
    """Add the art to one sheet. `load()` returns the overlay's pixels (called only when a write is due).
    Returns (status, line); never raises for a file it does not recognise."""
    bak = backup_of(path)
    note = ""
    if _wiped(path):
        # Only a sheet this module backed up is rebuilt: the backup must be a verified stock sheet.
        data = _any_stock_backup(bak)
        if data is None:
            return FOREIGN, f"{path.name} is missing or empty and there is no backup to rebuild it from: left alone"
        note = f" (it was missing or empty: rebuilt from {bak.name})"
    else:
        data = path.read_bytes()
    try:
        header, pixels, palette = decode(data)
    except SheetError as e:
        return FOREIGN, f"{path.name} is not a sheet the installer recognises ({e}): left alone"
    if has_the_art(pixels):
        return CURRENT, f"{path.name} already has PRACX's icon art"
    h = pixel_hash(pixels)
    if h in KNOWN_STOCK:
        stock, base = h, data
    elif _older_result_stock(h):
        stock = _older_result_stock(h)
        base = _stock_backup(bak, header, palette, stock)
        if base is None:
            return HAS_ART, f"{path.name} has an earlier version of the icon art and no backup to rebuild from: left alone"
        note += f" (an earlier version was rebuilt from {bak.name})"
    elif not area_is_blank(pixels):
        return HAS_ART, f"{path.name} has its own art where PRACX's icons go: left alone"
    else:
        return FOREIGN, (f"{path.name} is not the stock GOG sheet, so PRACX's grey unworked-tile yields cannot be "
                         "added to it, so it is left alone")
    try:
        overlay = load()
    except (OSError, SheetError) as e:
        return MISSING_ART, (f"PRACX's icon art is missing or damaged in this installer ({e}), so {path.name} is "
                             "left alone")
    base_px = decode(base)[1]
    out_pixels = compose(base_px, overlay)
    out = encode(header, out_pixels, palette)
    if pixel_hash(out_pixels) != EXPECTED_RESULT[stock] or decode(out) != (header, out_pixels, palette):
        return FOREIGN, f"{path.name}: the result did not check out, so it is left alone"
    if check:
        return ADDED, f"would add PRACX's icon art to {path.name}{note}"
    if not bak.is_file() or bak.read_bytes() != base:
        _write_atomic(bak, base)           # a verified stock sheet: the original
    _write_atomic(path, out)
    return ADDED, f"added PRACX's icon art to {path.name} (backup: {bak.name}){note}"


def restore_plan(path: pathlib.Path) -> list:
    """What restore_file_status would read and change, without changing it: [(path, modes)] (preflight.PROBE_MODES
    joined by "+"). The uninstall probes these before its first change. Mirrors restore_file_status branch by
    branch; keep the two together. A backup _drop_backup deletes is not listed: failing that delete does not fail
    the restore. A write is _write_atomic's: the temporary file is written afresh and moved ONTO the sheet's name
    ("replace": nothing may hold the sheet then, not even a program sharing everything -- audit 2026-11-16, D2)."""
    bak = backup_of(path)
    if not path.is_file() and not bak.is_file():
        return []                               # restore_folder does not call the restore at all
    temps = [t for t in (tmp_of(path), tmp_of(bak)) if t.is_file()]
    out = [(t, "delete") for t in temps]        # _clear_temps
    # the sheet's own temporary name is written afresh when a write is due: where deletes are not POSIX (FAT, older
    # Windows) a program still holding the deleted temporary file keeps that name taken
    write = [(path, "replace")] + ([(tmp_of(path), "replace")] if tmp_of(path) in temps else [])
    try:
        if not bak.exists():
            return out
        reads = [(p, "read") for p in (path, bak) if p.is_file()]
        if _wiped(path):
            return out + reads + (write if _any_stock_backup(bak) is not None else [])
        try:
            live_h, live_px, live_pal = decode(path.read_bytes())
        except SheetError:
            return out + reads
        try:
            bak_h, bak_px, bak_pal = decode(bak.read_bytes())
            bak_stock = pixel_hash(bak_px) if pixel_hash(bak_px) in KNOWN_STOCK else None
        except SheetError:
            bak_h = bak_pal = bak_stock = None
        if pixel_hash(live_px) in KNOWN_STOCK and (bak_stock or bak_h is None):
            return out + reads + [(bak, "delete")]      # deleted, unguarded
        if bak_stock is None:
            return out + reads
        if (live_h, live_pal) != (bak_h, bak_pal) or pixel_hash(live_px) not in _results_of(bak_stock):
            return out + reads
        return out + reads + write
    except OSError:
        # Unreadable (held open without sharing, access denied): the restore would fail on it too. Listed, so the
        # uninstall's probe refuses with the real reason before anything changes (audit of the merge, 2026-11-16).
        return out + [(p, "read") for p in (path, bak) if p.exists()]


def restore_file_status(path: pathlib.Path) -> tuple:
    """Put the backup back while the live sheet is still exactly what this module wrote from it."""
    _clear_temps(path)
    bak = backup_of(path)
    if not bak.exists():
        return UNPATCHED, f"{path.name}: no backup of ours, so there is nothing to restore"
    if _wiped(path):
        orig = _any_stock_backup(bak)
        if orig is None:
            return UNPATCHED, f"{path.name} is missing or empty and {bak.name} is not the stock sheet: left alone"
        _write_atomic(path, orig)
        return _drop_backup(bak, f"put {path.name} back from {bak.name} (it was missing or empty)")
    try:
        live_h, live_px, live_pal = decode(path.read_bytes())
    except SheetError as e:
        return UNPATCHED, f"{path.name} is not a sheet the installer wrote ({e}): left alone (backup kept)"
    orig = bak.read_bytes()
    try:
        bak_h, bak_px, bak_pal = decode(orig)
        bak_stock = pixel_hash(bak_px) if pixel_hash(bak_px) in KNOWN_STOCK else None
    except SheetError:
        bak_h = bak_pal = bak_stock = None
    if pixel_hash(live_px) in KNOWN_STOCK and (bak_stock or bak_h is None):
        bak.unlink()                       # the original is already in place (a GOG repair); the backup is spare
        return UNPATCHED, f"{path.name} is already the original"
    if bak_stock is None:
        return UNPATCHED, f"{bak.name} is not the stock sheet: left alone"
    if (live_h, live_pal) != (bak_h, bak_pal) or pixel_hash(live_px) not in _results_of(bak_stock):
        return UNPATCHED, f"{path.name} was changed after Longevity Vaccine's install: left alone (backup kept)"
    _write_atomic(path, orig)
    return _drop_backup(bak, f"restored {path.name} from {bak.name}")


def _drop_backup(bak: pathlib.Path, done: str) -> tuple:
    """After the original is back: the backup is spare. Failing to delete it does not undo the restore."""
    try:
        bak.unlink()
    except OSError as e:
        return RESTORED, f"{done}; {bak.name} could not be deleted ({e}) and can be deleted by hand"
    return RESTORED, done


def patch_folder(game_dir, overlay_path, check: bool = False, say=print) -> dict:
    """Add the art to <game_dir>/Icons.pcx. Returns {name: status}; {} when the folder has neither Icons.pcx nor
    a backup of it."""
    path = pathlib.Path(game_dir) / SHEET
    if not path.is_file() and not backup_of(path).is_file():
        return {}
    try:
        status, text = patch_file_status(path, lambda: load_overlay(pathlib.Path(overlay_path)), check)
    except OSError as e:
        status, text = FAILED, f"could not update {SHEET} ({e}): left alone"
    say(text)
    return {SHEET: status}


def restore_folder(game_dir, say=print) -> dict:
    """Undo patch_folder(). Returns {name: status}; {} when the folder has neither Icons.pcx nor a backup of it."""
    path = pathlib.Path(game_dir) / SHEET
    if not path.is_file() and not backup_of(path).is_file():
        return {}
    try:
        status, text = restore_file_status(path)
    except OSError as e:
        status, text = FAILED, f"could not restore {SHEET} ({e})"
    say(text)
    return {SHEET: status}


def main() -> int:
    import config
    game = pathlib.Path(config.game_dir())
    if "--restore" in sys.argv:
        res = restore_folder(game)
        return 0 if res and all(s in (RESTORED, UNPATCHED) for s in res.values()) else 1
    overlay = pathlib.Path(__file__).resolve().parents[1] / "art" / "pracx_icons_overlay.pcx"
    res = patch_folder(game, overlay, check="--check" in sys.argv)
    if not res:
        print("no", SHEET, "in", game)
        return 1
    return 0 if all(s in (ADDED, CURRENT) for s in res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
