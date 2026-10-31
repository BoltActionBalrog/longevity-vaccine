"""Ornate (type 2/6) popups: every chrome channel symmetric at every g > 16 (fix 26 v3: "F2 + P", reworked after
audit26 and audit26b).

Laws (scaling_laws.py, the source of truth):
  * ORNATE_HALF_OPEN -- every ornate chrome element sits on vanilla's HALF-OPEN axis x <-> W - 1 - x, the axis of the
    child windows (list rows, the OK / CANCEL bar): the title band (ornate_title_rect, thunk_pf_title_stash v9), the
    unkeyed field box (ornate_field_right_sub, t_orn_fieldsub v2), the content-frame ring (popup_content_frame_right,
    t_orn_cfpost) -- and the frame line:
  * ornate_popup_row_map -- the popup backdrop's ornate frame (armed only by t_orn_bd_arm around
    Popup_on_draw_background's backdrop call @0x405F77; NetTechWin @0x483998 never arms it) lays its RIGHT x band per
    SOURCE ROW CLASS (ornate_popup_row_class, BLOCKS of the art): the straight edge MIRRORS the left (the extra
    outermost key column is never sampled); the top-right ornament incl. its foot is CORNER (the old vanilla x g/16
    outer cells, the ornament's innermost bevel column 7 dropped: the user's "O4"); the bottom-right clamp from its
    first doubled-line row down is DUP (the old outer cells, the duplicate line column dropped).  The green line
    mirrors on EVERY row and no vertically continuous art column jogs at a class boundary.  thunk_bandmap_orn
    + t_orn_rowcls / t_orn_oc / t_orn_rcls / t_orn_rpat / t_orn_rnb.
  * ornate_popup_margin_r -- P: the ornate right content margin is the left's 19 at g > 16 (t_orn_rmargin @0x404E19).

Before (deployed c67c3cd1, 4K SELECT A FACTION): line -> title band 12 | 9, ring 5 inside the title inner on the
right, line -> ring 19 | 21, line -> OK bar 27 | 30, ring -> rows 6 | 7; tutorial window 13 | 10.  After: all equal,
at every g in 17..40 (both 64g x 48g and ceil(1024g/16) x ceil(768g/16) screens, scratch harness); g <= 16
byte-identical to vanilla; flat popups byte-identical.

Proof layers (all on the REAL bytes of a module-scoped bake of patches.yaml):
  1. wiring: the sites, the redirected tails, the arm, NetTechWin's direct call, the slots;
  2. Unicorn slices: the arm scopes the flag to exactly the thunk_tutwin_backdrop call; Popup_calc's margin block;
  3. END TO END (ornate_popup_emu.py on image_emu.py): the real builders (SELECT A FACTION's EDITORWHO picker,
     #RENAME, the TutWin tutorial window, GOVOPTIONS -- a type-1 list in an ornate popup --, the council vote, the
     untitled MPRECEIVEFILE box, and the flat #NEWBASE / GOVOPTIONS) boot the baked image under Unicorn and draw in
     the engine's own call order (DRAW #1 inside BasePop_exec_3 AND a later full redraw).  Every pair is read off
     the pixels at 4K and at one other g per family, and every ornate blit is captured (source art, args, dest
     before / after) and must equal the per-row law on the REAL art pixel for pixel;
  4. the per-row law itself on the captured REAL arts at EVERY g in 17..40 (no boot: pure law): class blocks,
     vertical continuity across every class boundary, exactly one dropped column per class, the line mirrored, the
     margins.
  Mutants it must kill: F2 without P (picker ring), fix 22's band-only mirror B2 (union ring); the asm-level mutants
  of the classes (no foot link, no DUP block, no CORNER shift) are killed in test_bandmap_ornate_asm_parity.py.

COST: each end-to-end item boots the whole image once (0.2-1 s) and builds one popup at one screen (1-3 s): 9 pair
renders + 2 disarmed 4K + 4 at g = 16 + 4 flat at g = 18 + 1 frame-alone + 2 mutants, each rendered once per worker
and shared by every item that reads it (module cache); the all-g coverage is the law layer (4), not renders.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_body_box as BB  # noqa: E402
import assemble_type1_gaps as W1A  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x668740
SITE_P = 0x404E19
SITE_P_ORIG = bytes.fromhex("C786B421000015000000")
SITE_NTW = 0x483998
SITE_BACKDROP = 0x405F77
HEAP = 0x20000000
G_BAND_NX, G_BAND_NY = 0xA16200, 0xA16204

#: B2 = fix 22's backed-out "band-only mirror" (thunk_pf_title_stash v8 + t_orn_title_rmirror @pcave2 0x1F70),
#: as audit20 rebuilt it: (va, bytes it replaces, bytes).  Applied to the fix-26-disarmed image (t_orn_rowcls, which
#: now lives at 0x1F70, is dead there: the mirror flag is never armed).
B2 = (
    (0xA0CF21, "6f81fee00394007467", "6681fee0039400745e"),
    (0xA0CF4B, "27", "37"),
    (0xA0CF73, "8b4424048b10891500cfa0008b5008891504cfa0008b500c891510eaa1006840a8a300c3" + "00" * 21,
     "e8160000008b442404e8ef0f0000eb05e8060000006840a8a300c38b4424088b10891500cfa0008b5008891504cfa0008b500c891510eaa100c3"),
    (0xA0DF70, None,
     "5357508bb9800000004f8b55e439fa7e0289fa2b55dc7e6b89d789d0c1e00431d2f7354087660083f87b725789c38d47016bc07a8d4418"
     "ff31d201dbf7f38d5400ff39d77c3d8b15408766008d54120fc1ea0529d089c36bc00e83c03b31d2516a7859f7f193c1e00483c03b31d2"
     "f7f15929c301fb8b45dc8d1c438b14242b1a895a08585f5bc3"),
)

#: the user's 4K shots this harness reproduces stroke for stroke on the deployed (fix-26-disarmed) geometry
#: (work/screenshots, gitignored; the cross-check runs when present): case -> shot.
SHOTS = {"EW": "terranx_pracx_3840x2160_20261022-204501.png", "TW": "terranx_pracx_3840x2160_20261022-204405.png"}
SHOT_DIR = ROOT / "screenshots"


# ---------------------------------------------------------------------------------------------------- the images
@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


class Image:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        pe = pefile.PE(data=bytes(data), fast_load=True)
        self.ib = pe.OPTIONAL_HEADER.ImageBase
        self.secs = [(self.ib + s.VirtualAddress, s.PointerToRawData, s.SizeOfRawData) for s in pe.sections]

    def off(self, va: int) -> int:
        for v, raw, size in self.secs:
            if v <= va < v + size:
                return raw + va - v
        raise KeyError(hex(va))

    def rd(self, va: int, n: int) -> bytes:
        o = self.off(va)
        return bytes(self.data[o:o + n])

    def wr(self, va: int, b: bytes):
        o = self.off(va)
        self.data[o:o + len(b)] = b


def off_edits(im: Image, st: dict) -> list:
    """fix 26 fully disarmed = the deployed c67c3cd1 geometry (scratch harness: identical renders, 10 families x 3
    screens): the P site, the railtrim tail, the title stash v9 -> v7, the field sub v2 -> v1, the content-frame tail."""
    e = [(SITE_P, SITE_P_ORIG),
         (st["thunk_backdrop_railtrim"] + 0x18, b"\x68" + struct.pack("<I", st["thunk_tutwin_backdrop"]) + b"\xC3")]
    v9 = bytearray(im.rd(st["thunk_pf_title_stash"], 128))
    assert v9[0x58:0x5C] == bytes.fromhex("40294208")                  # inc eax / sub [edx+8], eax
    v7 = v9[:0x58] + v9[0x59:]
    for o, op in ((0x08, 0x7E), (0x10, 0x74), (0x32, 0x73)):          # the rel8s that jump past the inc
        assert v7[o] == op
        v7[o + 1] = (v7[o + 1] - 1) & 0xFF
    e.append((st["thunk_pf_title_stash"], bytes(v7) + b"\0"))
    fs = im.rd(st["t_orn_fieldsub"], 63)
    i = fs.find(bytes.fromhex("8D4C0108"))
    assert i > 0
    e.append((st["t_orn_fieldsub"] + i, bytes.fromhex("8D4C0109")))
    cf = im.rd(st["thunk_content_frame"], 42)
    j = cf.find(b"\x68" + struct.pack("<I", st["t_orn_cfpost"]))
    assert j > 0
    e.append((st["thunk_content_frame"] + j + 1, struct.pack("<I", st["thunk_pf_union_align"])))
    return e


@pytest.fixture(scope="module")
def images(tmp_path_factory, bak_path, symtab, baked_exe):
    """{name: path}: the bake of patches.yaml (conftest's shared `baked_exe`), pristine (the .bak), and in-memory
    variants of the bake: off (fix 26 disarmed, off_edits), frame (off + the frame mirror re-armed: the frame alone),
    f2only (the P site restored), b2 (off + fix 22's band-only mirror)."""
    d = tmp_path_factory.mktemp("ornate_sym")
    dst = Path(baked_exe)
    baked = Image(dst.read_bytes())
    out = {"baked": str(dst), "pristine": str(bak_path), "_baked_image": baked}

    def variant(name, edits):
        im = Image(bytes(baked.data))
        for va, b in edits:
            im.wr(va, b)
        p = d / f"{name}.exe"
        p.write_bytes(bytes(im.data))
        out[name] = str(p)
        return im

    off = off_edits(baked, symtab)
    tail = symtab["thunk_backdrop_railtrim"] + 0x18
    off_im = variant("off", off)
    variant("frame", [e for e in off if e[0] != tail])
    variant("f2only", [(SITE_P, SITE_P_ORIG)])
    rc = symtab["t_orn_rowcls"]
    # 2026-10-24 W1A fix 25b: the title band draws through t_band_bdraw (law title_band_draw_rect), so B2's title-draw
    # tail `push thunk_box_thick_flat; ret` (68 40A8A300 C3) is retargeted to this tree's title draw on both sides of
    # the transplant -- B2 keeps the draw path the tree has; only its band-only mirror differs
    flat = "68" + struct.pack("<I", symtab["thunk_box_thick_flat"]).hex() + "c3"
    assert flat == "6840a8a300c3"
    draw = "68" + struct.pack("<I", symtab["t_band_bdraw"]).hex() + "c3"
    b2 = [(va, old and old.replace(flat, draw), new.replace(flat, draw)) for va, old, new in B2]
    if not all(old is None or off_im.rd(va, len(bytes.fromhex(old))) == bytes.fromhex(old) for va, old, _n in b2):
        pytest.fail("B2's bytes no longer transplant onto this tree (thunk_pf_title_stash moved): re-derive B2")
    orn = baked.rd(symtab["thunk_bandmap_orn"], 1494)          # B2's thunk lands on t_orn_rowcls' slot: the
    k = next(i for i in range(len(orn) - 5) if orn[i] == 0xE8 and   # blit's call to it becomes `and [ebp-80], 0`
             symtab["thunk_bandmap_orn"] + i + 5 + struct.unpack_from("<i", orn, i + 1)[0] == rc)
    variant("b2", off + [(va, bytes.fromhex(new)) for va, _o, new in b2]
            + [(symtab["thunk_bandmap_orn"] + k, bytes.fromhex("8365B00090"))])
    # shot = off + W1A's fixes off (assemble_type1_gaps.disarm_edits): the geometry the user's 2026-10-22 shots were
    # taken on (c67c3cd1) -- W1A's fix 25b moved the title band's bottom strokes, which the shot cross-check reads
    # W9C F54 (t_gv_bodyb, 2026-10-27) lifts the body box's bottom strokes one row, the tutorial window's included: the
    # shot predates it, so its site goes back to `call thunk_d528_inset`
    assert off_im.rd(BB.SITE, 1) == b"\xe8"
    bodyb_off = [(BB.SITE + 1, struct.pack("<i", symtab["thunk_d528_inset"] - (BB.SITE + 5)))]
    variant("shot", off + W1A.disarm_edits(off_im.rd, symtab) + bodyb_off)
    return out


@pytest.fixture(scope="module")
def emu_mod():
    from conftest import _missing                       # skip, or fail under LONGEVITY_REQUIRE_E2E
    try:
        import ornate_popup_emu as O
    except Exception as x:                              # no game dir / host GDI: the end-to-end layer cannot run
        _missing(Path("ornate_popup_emu"), f"the real-image popup renderer ({x})")
    if not (Path(O.GAME) / "interface.pcx").is_file():
        _missing(Path(O.GAME) / "interface.pcx", "the game's frame art")
    return O


_RENDERS: dict = {}


def _after_sel(im: Image, st: dict) -> int:
    """The return address of thunk_frame_enlarge's one `call thunk_bandmap_sel` (the blit is done there)."""
    fe = st["thunk_frame_enlarge"]
    b = im.rd(fe, 0x100)
    hits = [fe + i + 5 for i in range(len(b) - 5)
            if b[i] == 0xE8 and fe + i + 5 + struct.unpack_from("<i", b, i + 1)[0] == st["thunk_bandmap_sel"]]
    assert len(hits) == 1
    return hits[0]


def render(O, images, symtab, name, case, g=None, wh=None):
    """One boot + build per (image, case, screen), cached for the module.  g = 40 renders at 3840 x 2160 (the user's
    4K), other g at 64g x 48g (g exact).  Every thunk_bandmap_orn call is captured: the source art, the args, the
    stashed exact-fill w/h, the mirror flag, and the dest buffer before / after."""
    w, h = wh or ((3840, 2160) if g == 40 else (64 * g, 48 * g))
    key = (images[name], case, w, h)
    if key not in _RENDERS:
        caps, pend = [], {}

        def snap(e, obj):
            pix, bw, bh, st = e.r32(obj + 0x54), e.s32(obj + 0x80), -e.s32(obj + 0x84), e.s32(obj + 0x4A8)
            return np.frombuffer(bytes(e.uc.mem_read(pix, st * bh)), np.uint8).reshape(bh, st)[:, :bw].copy()

        def on_orn(e):
            esp = e.reg(UC_X86_REG_ESP)
            a = [e.s32(esp + 4 + 4 * i) for i in range(11)]
            pend.update(src=snap(e, a[0] & 0xFFFFFFFF), dst=a[1] & 0xFFFFFFFF, args=a,
                        mirror=e.r32(symtab["g_orn_mirror"]), stash=(e.s32(symtab["g_bm_dstw"]), e.s32(symtab["g_bm_dsth"])))
            pend["before"] = snap(e, pend["dst"])

        def on_after(e):
            if pend:
                c = dict(pend)
                c["after"] = snap(e, c["dst"])
                caps.append(c)
                pend.clear()

        r = O.render(images[name], case, w, h,
                     hooks=[(symtab["thunk_bandmap_orn"], on_orn), (_after_sel(images["_baked_image"], symtab), on_after)])
        r["blits"] = caps
        _RENDERS[key] = r
    r = _RENDERS[key]
    if g is not None:
        assert r["g"] == g
    return r


def blit_by_law(c: dict, g: int):
    """What thunk_bandmap_orn must leave in the dest for one captured call: the keyed copy through the per-row law
    (ornate_popup_row_map when armed, axis_map_chrome otherwise) + the outer-key re-key, over the dest as it was."""
    a, src = c["args"], c["src"]
    srcw, srch, dx, dy, dw, dh, key = a[4:11]
    for i, st in enumerate(c["stash"]):                    # the blit's exact-fill: grow by <= 4 to the stashed span
        cur = (dw, dh)[i]
        if 0 < st and cur <= st <= cur + 4:
            dw, dh = (st, dh) if i == 0 else (dw, st)
    exp = c["before"].astype(int).copy()
    H, W = exp.shape
    fy = SL.axis_map_chrome(srch, dh, SL.ORNATE_BAND[1], g, *SL.ORNATE_STROKE_CELL["y"])
    rows = [r.tolist() for r in src]
    if c["mirror"]:                                       # one map per row CLASS; each SOURCE row picks its class's
        cls = class_list(rows, key)
        per_cls = {k: SL.ornate_popup_row_map(rows, cls.index(k), dw, g, key) for k in set(cls[sy] for sy in fy)}
        fx = [per_cls[cls[fy[y]]] for y in range(dh)]
    else:
        fx = [SL.axis_map_chrome(srcw, dw, SL.ORNATE_BAND[0], g, *SL.ORNATE_STROKE_CELL["x"])] * dh
    x0, x1 = max(0, -dx), min(dw, W - dx)
    for y in range(dh):
        if 0 <= dy + y < H and x0 < x1:
            v = src[fy[y]][np.asarray(fx[y][x0:x1])]
            seg = exp[dy + y, dx + x0:dx + x1]
            exp[dy + y, dx + x0:dx + x1] = np.where(v != key, v, seg)
    if key != -1:
        bx, by = SL.cum(SL.ORNATE_BAND[0], dw, srcw), SL.cum(SL.ORNATE_BAND[1], dh, srch)
        for x, y in SL.ornate_outer_key(rows, fx, fy, bx, by, key):
            if 0 <= dx + x < W and 0 <= dy + y < H:
                exp[dy + y, dx + x] = key
    return exp, (srcw, dw, key, rows)


_CLASSES: dict = {}


def class_list(rows, key) -> list:
    """ornate_popup_row_class for every row of one art (cached per art: the classes do not depend on g)."""
    k = (key, tuple(map(tuple, rows)))
    if k not in _CLASSES:
        _CLASSES[k] = [SL.ornate_popup_row_class(rows, y, key) for y in range(len(rows))]
    return _CLASSES[k]


# ---------------------------------------------------------------------------------------------------- pair checks
def _sym(v) -> bool:
    return v is not None and v[0] == v[1]


def _straight_margins(c) -> tuple:
    """The transparent margins L | R on the canvas' middle row (the straight edge)."""
    r = c[c.shape[0] // 2]
    W = len(r)
    return next(i for i in range(W) if r[i] != 9), next(i for i in range(W) if r[W - 1 - i] != 9)


def chrome_pairs(a, c) -> list:
    """Every family: frame line -> title band / body box, band -> inner, line -> ring / text box, line -> the OK bar,
    the straight-edge transparent margins."""
    bad = [(k, a.get(k)) for k in ("ch_line_band", "ch_band_inner", "ch_line_ring", "ch_line_textbox", "line_btn")
           if a.get(k) is not None and not _sym(a.get(k))]
    m = _straight_margins(c)
    if m[0] != m[1]:
        bad.append(("straight_margins", m))
    return bad


def picker_pairs(a, c) -> list:
    """SELECT A FACTION / stack picker: the list ring flush with the title inner on both sides, ring -> rows equal."""
    bad = chrome_pairs(a, c)
    if a.get("inner_to_ring") != (0, 0):
        bad.append(("inner_to_ring", a.get("inner_to_ring")))
    if a.get("ch_ring_content") is not None and not _sym(a.get("ch_ring_content")):
        bad.append(("ch_ring_content", a.get("ch_ring_content")))
    return bad


def union_pairs(a, c) -> list:
    """#RENAME / the council vote: the union ring flush with the title OUTER, the text box with the title INNER."""
    bad = chrome_pairs(a, c)
    for k in ("outer_to_ring", "inner_to_textbox"):
        if a.get(k) != (0, 0):
            bad.append((k, a.get(k)))
    return bad


def list_pairs(a, c) -> list:
    """GOVOPTIONS (type-1 list in an ornate popup): + the hug ring equally inside the title inner."""
    bad = chrome_pairs(a, c)
    if not _sym(a.get("inner_to_ring")):
        bad.append(("inner_to_ring", a.get("inner_to_ring")))
    return bad


CHECK = {"EW": picker_pairs, "PK": picker_pairs, "RN": union_pairs, "VO": union_pairs, "GO": list_pairs,
         "TW": chrome_pairs, "MR": chrome_pairs}


# ---------------------------------------------------------------------------------------------------- 1. wiring
def test_scaling_fix26_wiring(images, symtab):
    im = images["_baked_image"]
    st = symtab
    rel = lambda va, tgt: b"\xE8" + struct.pack("<i", tgt - (va + 5))  # noqa: E731
    assert im.rd(SITE_P, 10) == rel(SITE_P, st["t_orn_rmargin"]) + b"\x90" * 5
    assert im.rd(SITE_BACKDROP, 5) == rel(SITE_BACKDROP, st["thunk_backdrop_railtrim"])
    assert im.rd(SITE_NTW, 5) == rel(SITE_NTW, st["thunk_tutwin_backdrop"])             # never armed
    assert im.rd(st["thunk_backdrop_railtrim"] + 0x18, 6) == b"\x68" + struct.pack("<I", st["t_orn_bd_arm"]) + b"\xC3"
    a = im.rd(st["t_orn_bd_arm"], 36)
    assert a[:2] == b"\xC7\x05" and struct.unpack_from("<I", a, 2)[0] == st["g_orn_mirror"]
    assert a[18] == 0xE8 and st["t_orn_bd_arm"] + 23 + struct.unpack_from("<i", a, 19)[0] == st["thunk_tutwin_backdrop"]
    assert im.rd(st["g_orn_mirror"], 4) == b"\0\0\0\0"                                  # disarmed at rest
    cf = im.rd(st["thunk_content_frame"], 42)
    assert cf.endswith(b"\x68" + struct.pack("<I", st["t_orn_cfpost"]) + b"\xC3")
    assert im.rd(st["t_orn_cfpost"] + 63, 6) == b"\x68" + struct.pack("<I", st["thunk_pf_union_align"]) + b"\xC3"
    assert im.rd(st["thunk_pf_title_stash"] + 0x58, 4) == bytes.fromhex("40294208")      # v9: r -= delta + 1
    assert bytes.fromhex("8D4C0108") in im.rd(st["t_orn_fieldsub"], 63)                  # v2: X + 1
    orn = im.rd(st["thunk_bandmap_orn"], 1494)
    calls = {st["thunk_bandmap_orn"] + i + 5 + struct.unpack_from("<i", orn, i + 1)[0]
             for i in range(len(orn) - 5) if orn[i] == 0xE8}
    assert {st["t_orn_oc"], st["t_orn_rowcls"]} <= calls
    assert st["thunk_bandmap_orn"] + 1494 <= st["t_orn_fieldsub"]

    def callees(name, n):
        b = im.rd(st[name], n)
        return [st[name] + i + 5 + struct.unpack_from("<i", b, i + 1)[0] for i in range(n - 5) if b[i] == 0xE8]
    assert callees("t_orn_oc", 84) == [st["t_orn_rcls"]]                                 # fix 26 v3: the classes
    assert callees("t_orn_rcls", 130) == [st["t_orn_rplain"], st["t_orn_rpat"], st["t_orn_rnb"], st["t_orn_rnb"]]
    assert callees("t_orn_rnb", 73) == [st["t_orn_rpat"]]
    rc = im.rd(st["t_orn_rowcls"], 77)
    assert rc[:1] == b"\x60" and rc[-2:] == b"\x61\xC3" and b"\xE8" not in rc[20:]     # pushad .. popad; ret, no calls
    assert SL.ornate_popup_margin_r(16) == 21 and all(SL.ornate_popup_margin_r(g) == 19 for g in range(17, 41))


# ---------------------------------------------------------------------------------------------------- 2. slices
class Slice:
    def __init__(self, im: Image):
        pe = pefile.PE(data=bytes(im.data))
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            va = im.ib + s.VirtualAddress
            mu.mem_map(va, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(va, s.get_data())
        mu.mem_map(HEAP, 0x200000)

    def r32(self, va):
        return struct.unpack("<i", self.mu.mem_read(va, 4))[0]

    def w32(self, va, v):
        self.mu.mem_write(va, struct.pack("<i", v))


@pytest.fixture(scope="module")
def slice_(images):
    return Slice(images["_baked_image"])


@pytest.mark.parametrize("g", (17, 25, 40))
def test_scaling_fix26_arm_scopes_the_flag_to_the_backdrop_call(slice_, symtab, g):
    """thunk_backdrop_railtrim -> t_orn_bd_arm: g_orn_mirror is 1 exactly while thunk_tutwin_backdrop runs (it sees
    the caller's ecx and both args), 0 after; the arm returns to the 0x405F77 caller with ret 8 and its eax."""
    s, mu = slice_, slice_.mu
    flag, tut = symtab["g_orn_mirror"], symtab["thunk_tutwin_backdrop"]
    saved = bytes(mu.mem_read(tut, 3))
    mu.mem_write(tut, b"\xC2\x08\x00")                 # stand-in: ret 8 (records what it is called with)
    mu.ctl_remove_cache(tut, tut + 3)
    seen = {}

    def at_tut(uc, addr, size, _):
        if addr == tut:
            esp = uc.reg_read(UC_X86_REG_ESP)
            seen["flag"] = s.r32(flag)
            seen["ecx"] = uc.reg_read(UC_X86_REG_ECX)
            seen["args"] = (s.r32(esp + 4), s.r32(esp + 8))
            uc.reg_write(UC_X86_REG_EAX, 0x1234ABCD)

    hk = mu.hook_add(UC_HOOK_CODE, at_tut)
    try:
        s.w32(G_VA, g)
        rect, win, ret, sp = HEAP + 0x100, HEAP + 0x200, HEAP + 0x1000, HEAP + 0x8000
        mu.mem_write(rect, struct.pack("<4i", 10, 20, 900, 400))
        mu.mem_write(win, struct.pack("<4i", 0, 0, 900, 400))       # rect.R == window R: no rail trim
        mu.mem_write(ret, b"\x90")
        mu.mem_write(sp, struct.pack("<3I", ret, rect, 0x6846B0))
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_EBX, win)
        mu.reg_write(UC_X86_REG_ECX, 0x0BADF00D)
        mu.emu_start(symtab["thunk_backdrop_railtrim"], ret, count=200)
    finally:
        mu.hook_del(hk)
        mu.mem_write(tut, saved)
        mu.ctl_remove_cache(tut, tut + 3)
    assert seen == {"flag": 1, "ecx": 0x0BADF00D, "args": (rect, 0x6846B0)}
    assert s.r32(flag) == 0
    assert mu.reg_read(UC_X86_REG_ESP) == sp + 12 and mu.reg_read(UC_X86_REG_EAX) == 0x1234ABCD


@pytest.mark.parametrize("g", (0, 12) + tuple(range(16, 41)))
def test_scaling_fix26_popup_calc_writes_the_margin_law(slice_, g):
    """Popup_calc's ornate block 0x404E07..0x404E29 on the baked bytes: [+0x21b4] = ornate_popup_margin_r(g),
    [+0x21b0] = 19, [+0x21b8] = header + ecx (vanilla), esi / ecx preserved."""
    s, mu = slice_, slice_.mu
    obj = HEAP + 0x10000
    mu.mem_write(obj, b"\0" * 0x3400)
    s.w32(obj + 0x21B8, 18)
    s.w32(G_VA, g)
    mu.reg_write(UC_X86_REG_ESI, obj)
    mu.reg_write(UC_X86_REG_ECX, 9)
    mu.reg_write(UC_X86_REG_ESP, HEAP + 0x9000)
    mu.emu_start(0x404E07, 0x404E29, count=100)
    assert s.r32(obj + 0x21B4) == SL.ornate_popup_margin_r(g)
    assert s.r32(obj + 0x21B0) == SL.ORNATE_MARGIN_L_NATIVE and s.r32(obj + 0x21B8) == 18 + 9
    assert mu.reg_read(UC_X86_REG_ESI) == obj and mu.reg_read(UC_X86_REG_ECX) == 9
    assert mu.reg_read(UC_X86_REG_ESP) == HEAP + 0x9000


@pytest.mark.parametrize("g", (16, 17, 22, 40))
@pytest.mark.parametrize("ornate", (0, 1))
def test_scaling_fix26_content_frame_ring(slice_, symtab, g, ornate):
    """thunk_content_frame -> t_orn_cfpost on the baked bytes == popup_content_frame_right: the widen to box_w - L,
    then an ornate ring left there one px in (half-open axis); flat popups and g <= 16 untouched."""
    s, mu = slice_, slice_.mu
    ua = symtab["thunk_pf_union_align"]
    pop, rect, ret, sp = HEAP + 0x20000, HEAP + 0x300, HEAP + 0x1000, HEAP + 0x8000
    for rect_r in (500, 900, 951, 952):
        mu.mem_write(pop, b"\0" * 0x3200)
        s.w32(pop + 0x30AC, 60000 if ornate else 0)
        s.w32(pop + 0x30BC, 1000)
        mu.mem_write(rect, struct.pack("<4i", 48, 30, rect_r, 300))
        mu.mem_write(sp, struct.pack("<3I", ret, rect, 0x78D5A0))
        s.w32(G_VA, g)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ESI, pop)
        mu.emu_start(symtab["thunk_content_frame"], ua, count=200)
        assert mu.reg_read(UC_X86_REG_ESP) == sp
        assert s.r32(rect + 8) == SL.popup_content_frame_right(rect_r, 1000, 48, bool(ornate), g), (g, ornate, rect_r)


# ---------------------------------------------------------------------------------------------------- 3. end to end
#: 4K + one other g per family (g = 17: every cell 1 px; the all-g coverage is the law layer below; PK
#: shares EW's arms -- scratch sweep)
PAIRS = [("EW", 40), ("EW", 17), ("RN", 40), ("RN", 22), ("TW", 40), ("TW", 22), ("GO", 22), ("VO", 25), ("MR", 25)]


@pytest.mark.parametrize("case,g", PAIRS)
def test_scaling_ornate_popup_pairs_are_symmetric(emu_mod, images, symtab, case, g):
    """Every chrome pair of the real popup equal on both sides -- incl. line -> OK bar and the picker's ring -> rows
    -- at DRAW #1 and after a full redraw; every ornate blit of the build == the per-row law on the real art."""
    r = render(emu_mod, images, symtab, "baked", case, g)
    for which in ("d1", "later"):
        a = emu_mod.pairs(r[which], r["children"])
        assert a, (case, g, which, "no ornate title found")
        assert CHECK[case](a, r[which]) == [], (case, g, which)
    assert r["blits"] and all(c["mirror"] == 1 for c in r["blits"])
    for c in r["blits"]:
        exp, _ = blit_by_law(c, g)
        assert (exp == c["after"]).all(), (case, g, int((exp != c["after"]).sum()))


def _right_starts(m, srcw) -> dict:
    """source column c (0 = the right's outermost) -> its first dest offset from the right edge, for c < 16."""
    out, W = {}, len(m)
    for jj in range(W):
        c = srcw - 1 - m[W - 1 - jj]
        if 0 <= c < 16 and c not in out:
            out[c] = jj
    return out


def _start(st: dict, row, srcw: int, c: int):
    """Where right source column c starts in one row's map; None when the map DROPS it.  A column dropped as the
    duplicate of its outer neighbour (the DUP rows' line column 8 = column 7) starts where that neighbour does -- the
    same pixels."""
    while c not in st and c > 0 and row[srcw - 1 - c] == row[srcw - c]:
        c -= 1
    return st.get(c)


#: the right source columns (0 = outermost) a row of each class may drop: MIRROR the extra key column, CORNER (O4)
#: the ornament's innermost bevel column 7, DUP the duplicate line column 8
DROPS = {"mirror": 0, "corner": 7, "dup": 8, "plain": None}


@pytest.fixture(scope="module")
def real_arts(emu_mod, images, symtab):
    """The REAL frame arts the 4K builds blit (SELECT A FACTION, #RENAME, the tutorial window): (case, rows, key)."""
    out = []
    for case in ("EW", "RN", "TW"):
        c = render(emu_mod, images, symtab, "baked", case, 40)["blits"][0]
        out.append((case, [r.tolist() for r in c["src"]], c["args"][10]))
    return out


def test_scaling_ornate_frame_rows_on_the_real_art(real_arts):
    """Per native row of each REAL frame art, the law at EVERY g in 17..40 (audit26b F1 / F3, the user's O4):
      * the classes are BLOCKS top to bottom -- CORNER (the top-right ornament and its foot), MIRROR (the straight
        edge), DUP (from the lower half's first doubled-line row), and the one PLAIN last row;
      * VERTICAL CONTINUITY: at every class boundary, every right source column c < 16 that carries the same non-key
        colour in both rows and is drawn in both starts at the same dest offset in both (no horizontal shift of
        continuous art: v2's row-43 seam moved cols 2 / 4 / 7 by 1-3 px); a column one row DROPS is a drop, checked
        below, not a jog;
      * a row whose outer key runs are equal (vanilla symmetric) draws equal key runs (audit26c N1: the PLAIN
        bottom row);
      * each row drops exactly its class's one column (DROPS) and nothing else: MIRROR its outermost (key) column,
        CORNER the ornament's innermost bevel column 7, DUP the line column 8, which repeats column 7 on every row
        except the bottom band below the line -- at every g, g = 17 included;
      * a CORNER / DUP row's outer cells 0..6 are the old (vanilla x g/16, c67c3cd1) map's: margins and ornament exact;
      * the green line mirrors about x <-> W - 1 - x on every row that carries it; a MIRROR row's margin + metal +
        line are mirrored; every map is monotone."""
    for case, rows, key in real_arts:
        srcw, h = len(rows[0]), len(rows)
        cls = class_list(rows, key)
        blocks = [cls[0]] + [c for p, c in zip(cls, cls[1:]) if c != p]
        assert blocks == ["corner", "mirror", "dup", "plain"] and cls.count("plain") == 1, (case, blocks)
        run = lambda r: next((i for i, v in enumerate(r) if v != key), len(r))  # noqa: E731
        yd = cls.index("dup")
        c_near = SL.ORNATE_STROKE_CELL["x"][0]
        frame_line = rows[h // 2][c_near]
        dup_diff = [y for y in range(yd, h) if rows[y][srcw - 9] != rows[y][srcw - 8]]
        last_line = max(y for y in range(yd, h) if rows[y][c_near] == frame_line)
        assert all(y > last_line for y in dup_diff), (case, dup_diff, last_line)   # only below the bottom line
        assert all(rows[y][-1] == key for y in range(h) if cls[y] == "mirror")
        for g in range(17, 41):
            dw = (srcw * g) // 16 + 1
            old = SL.axis_map_chrome(srcw, dw, SL.ORNATE_BAND[0], g, *SL.ORNATE_STROKE_CELL["x"])
            b, k = SL.cum(SL.ORNATE_BAND[0], dw, srcw), SL.stroke_width(g)
            d = SL.ornate_popup_outer_width(srcw, dw, g)
            maps = {c: SL.ornate_popup_row_map(rows, cls.index(c), dw, g, key) for c in DROPS}
            starts = {c: _right_starts(m, srcw) for c, m in maps.items()}
            for c, m in maps.items():
                assert all(m[i] <= m[i + 1] for i in range(dw - 1)), (case, g, c)
                drop = set() if DROPS[c] is None else {srcw - 1 - DROPS[c]}
                assert {old[x] for x in range(dw - b, dw)} - set(m[dw - b:]) == drop, (case, g, c)
                if c in ("corner", "dup"):
                    assert m[dw - d:] == old[dw - d:], (case, g, c)        # the outer cells 0..6: vanilla x g/16
            for y in range(h - 1):                                          # vertical continuity at the boundaries
                c0, c1 = cls[y], cls[y + 1]
                if c0 != c1:
                    for c in range(16):
                        if rows[y][srcw - 1 - c] == rows[y + 1][srcw - 1 - c] != key:
                            p0 = _start(starts[c0], rows[y], srcw, c)
                            p1 = _start(starts[c1], rows[y + 1], srcw, c)
                            assert p0 is None or p1 is None or p0 == p1, (case, g, y, c, p0, p1)
            for y, row in enumerate(rows):
                c = cls[y]
                new = [row[x] for x in maps[c]]
                if run(row) == run(row[::-1]):                              # N1: vanilla symmetric -> L == R
                    assert run(new) == run(new[::-1]), (case, g, y, c, run(new), run(new[::-1]))
                if c == "mirror":
                    sig = [(v == key, v == frame_line) for v in new]
                    assert sig[dw - d - k:][::-1] == sig[:d + k], (case, g, y)  # margin + metal + line mirrored
                line = row[c_near]
                gl = [x for x in range(b) if new[x] == line != key]
                gr = [x for x in range(dw - b, dw) if new[x] == line != key]
                if line == frame_line and gl and gl == list(range(gl[0], gl[0] + k)):
                    assert set(dw - 1 - x for x in gl) <= set(gr), (case, g, y, gl, gr)


#: case -> ((line_band, family pair, its value) baked, the same off = the deployed c67c3cd1 geometry), at 4K
PINS_4K = {"EW": (((12, 12), "inner_to_ring", (0, 0)), ((12, 9), "inner_to_ring", (0, 5))),
           "TW": (((13, 13), "ch_band_inner", (5, 5)), ((13, 10), "ch_band_inner", (5, 5)))}


@pytest.mark.parametrize("case", sorted(PINS_4K))
def test_scaling_ornate_popup_4k_values_and_the_users_shot(emu_mod, images, symtab, case):
    """The pinned 4K numbers (3840 x 2160, g = 40), before (fix 26 disarmed = the deployed geometry) and after:
    SELECT A FACTION line -> band 12 | 9 -> 12 | 12, ring 0 | 5 inside the title inner -> flush, line -> ring
    19 | 21 -> 19 | 19, line -> OK bar 27 | 30 -> 27 | 27, ring -> rows 6 | 7 -> 6 | 6; the tutorial window 13 | 10 ->
    13 | 13.  The window is s(21) - s(19) = 5 px narrower; the left side and the buttons do not move.  When the
    user's shot is present (work/screenshots, gitignored), the disarmed image (fix 26 and W1A off: the shot's
    c67c3cd1 geometry) draws every stroke where the shot has it: all emulated green-line / title / ring stroke pixels
    (indices 31 and 34) carry one colour each."""
    new = render(emu_mod, images, symtab, "baked", case, 40)
    old = render(emu_mod, images, symtab, "off", case, 40)
    a, b = emu_mod.pairs(new["d1"], new["children"]), emu_mod.pairs(old["d1"], old["children"])
    for got, (band, k, v) in ((a, PINS_4K[case][0]), (b, PINS_4K[case][1])):
        assert (got["ch_line_band"], got[k]) == (band, v), (case, got["ch_line_band"], got[k])
    assert b["W"] - a["W"] == SL.popup_scale_floor(21, 40) - SL.popup_scale_floor(19, 40) == 5
    assert emu_mod.buttons(new["children"]) == emu_mod.buttons(old["children"])
    assert a["line"][0] == b["line"][0] and a["outer"][0] == b["outer"][0]       # the left side never moves
    assert a["line_btn"] == (27, 27) and b["line_btn"] == (27, 30)
    if case == "EW":
        assert a["ch_line_ring"] == (19, 19) and b["ch_line_ring"] == (19, 21)
        assert a["ch_ring_content"] == (6, 6) and b["ch_ring_content"] == (6, 7)
    shot = SHOT_DIR / SHOTS[case]
    if not shot.is_file():
        return
    from PIL import Image as PILImage
    shot_r = render(emu_mod, images, symtab, "shot", case, 40)
    c = shot_r["d1"]
    x0, y0 = shot_r["placed"]
    sub = np.array(PILImage.open(shot).convert("RGB"))[y0:y0 + c.shape[0], x0:x0 + c.shape[1]].astype(int)
    for idx in (31, 34):
        px = sub[c == idx]
        ref = np.median(px, axis=0)
        assert len(px) > 1000
        assert (np.abs(px - ref).sum(-1) <= 6).all(), (case, idx, np.unique(px, axis=0)[:4])


@pytest.mark.parametrize("case", ("EW", "RN"))
def test_scaling_ornate_popup_g16_is_pristine(emu_mod, images, symtab, case):
    new = render(emu_mod, images, symtab, "baked", case, wh=(1024, 768))
    van = render(emu_mod, images, symtab, "pristine", case, wh=(1024, 768))
    for k in ("d1", "later"):
        assert new[k].shape == van[k].shape and (new[k] == van[k]).all(), (case, k)
    assert new["children"] == van["children"] and new["placed"] == van["placed"]
    assert not new["blits"]                               # the enlarge never runs at g <= 16


@pytest.mark.parametrize("case,g", (("NB", 18), ("GF", 18)))
def test_scaling_flat_popup_is_untouched(emu_mod, images, symtab, case, g):
    """#NEWBASE / GOVOPTIONS flat: byte-identical with fix 26 disarmed -- no ornate arm reaches a flat popup."""
    new = render(emu_mod, images, symtab, "baked", case, g)
    off = render(emu_mod, images, symtab, "off", case, g)
    assert new["typ"] < 20000
    for k in ("d1", "later"):
        assert (new[k] == off[k]).all()
    assert new["children"] == off["children"]


def test_scaling_fix26_the_frame_alone_changes_only_the_right_band(emu_mod, images, symtab):
    """The frame mirror alone (everything else disarmed) against the disarmed image at 4K: every changed pixel lies
    in the frame's far x band [W - b, W), no child-window pixel changes -- the interior's device-density stripes and
    every other element are untouched (the band map only re-picks NN source columns of the frame art)."""
    f = render(emu_mod, images, symtab, "frame", "EW", 40)
    off = render(emu_mod, images, symtab, "off", "EW", 40)          # shared with the 4K pins
    for k in ("d1", "later"):
        A, B = off[k], f[k]
        ys, xs = np.nonzero(A != B)
        W = A.shape[1]
        b = SL.cum(SL.ORNATE_BAND[0], W, ((W - 1) * 16) // 40)
        assert len(xs) and xs.min() >= W - b, (k, xs.min(), W - b)
        assert not ((A >= 256) | (B >= 256))[ys, xs].any()


def test_scaling_fix26_mutant_f2_without_p_fails_the_picker_pairs(emu_mod, images, symtab):
    r = render(emu_mod, images, symtab, "f2only", "EW", 25)
    a = emu_mod.pairs(r["d1"], r["children"])
    assert _sym(a["ch_line_band"])                    # the frame + title fixes alone fix the band channel ...
    assert picker_pairs(a, r["d1"]) != []             # ... but leave the ring 2 native px inside on the right


def test_scaling_fix26_mutant_b2_band_only_mirror_fails_the_union_ring(emu_mod, images, symtab):
    assert "b2" in images                             # the fixture fails (never skips) when B2 does not transplant
    r = render(emu_mod, images, symtab, "b2", "RN", 25)
    a = emu_mod.pairs(r["d1"], r["children"])
    assert _sym(a["ch_line_band"])
    assert union_pairs(a, r["d1"]) != []
