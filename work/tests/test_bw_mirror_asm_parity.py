"""Differential (Unicorn): the base-screen mirror law's cave code (2026-10-25 W5A v2), resolved from patches.yaml
with the real symbol table, against scaling_laws:

  * t_bw_railsum            eax = basewin_rail_axis_sum(g) = pt(726), edx = basewin_rail_left_extent(g); ecx kept;
  * t_bw_rimx               edx = basewin_rim_x for every native edge 0..800; eax / ecx preserved;
  * t_bw_mirrect            g_bw_rect = basewin_mirror_rect(rect, g) (half-open, W5A v4) for the base screen's rects
                            and probes;
  * t_bw_railscale          the 4 settled slide_show rail sites: the BaseWin canvas's strips at basewin_rail_strip_x
                            with num / den = g / 16 and y = fl(y g/16), tail thunk_sprite_scale_nn (every g > 16,
                            g = 17 included); any other dest, or g <= 16, -> thunk_filedlg_railscale with the stack,
                            ecx and the args untouched;
  * t_bw_railanchor         railslide's anchor: the BaseWin (g_fd_winbuf == its canvas) A*, every other window
                            railscale's double floor fl((fl(W*16/g) - 0x37) * g/16), for a sweep of widths;
  * thunk_bw_boxsprite_console v4 / thunk_bw_boxsprite_tabframe v4 / thunk_bw_boxsprite / thunk_bw_clip /
    thunk_bw_fill2 / thunk_bw_rect_core: the rect each hands its renderer == the law, the dispatch / stack / ecx
    contracts, and the g <= 16 (canvas 758) native exits untouched.  thunk_bw_boxsprite (v4, F42) runs on through the
    shared trim helper (t_bm_ho_hf / t_bm_ho_df, executed here): the band renderer receives basewin_box_draw_rect
    (R - 1 / B - 1), and g_bw_rect is the half-open rect again when the helper returns to the site.
(thunk_basewin_gwinit v6, thunk_bw_facsb_attach and t_bw_wheel_down are pinned in test_facsb_asm_parity.py /
test_bw_wheel_asm_parity.py; thunk_filedlg_railslide's whole frame contract in test_rail*_parity; the real-image proof
is test_scaling_basewin_mirror.py.)  4K (g = 40) is in every sweep here (the e2e module covers g = 33 instead).
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent - asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

BW = 0x6A7628
CANVAS = BW + 0x444
PP_CANVAS = 0x6A8044 + 0x444    # the production picker: NOT armed (no rails over the base screen; alone, railscale's)
BOX_SPRITE, SET_CLIP, FILL_2 = 0x5E2DD3, 0x5D8000, 0x5D5350
RENDER_RET = 0x00410051         # a `ret 8` the renderer stub is resumed at (thiscall, rect + params)
STACK = 0x00200000
SITE_RET, STUB_RET = 0x00410031, 0x00410041
G_RANGE = range(16, 41)


def _load():
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    thunks = {}
    for cave in doc["code_caves"]:
        base = cave["virtual_addr"]
        base = int(base, 16) if isinstance(base, str) else base
        for c in cave.get("contents", []) or []:
            off = c["offset"]
            off = int(off, 16) if isinstance(off, str) else off
            thunks[c["id"]] = (base + off, ap.ByteTemplate(c["bytes"]).resolve(base + off, symtab))
    return symtab, thunks


SYMTAB, THUNKS = _load()
G_VA = SYMTAB["g_popup_scale_num"]
G_BW_RECT = SYMTAB["g_bw_rect"]
G_FD_WINBUF = SYMTAB["g_fd_winbuf"]
HOLLOW, DEVFILL = SYMTAB["thunk_box_thick_hollow_flat"], SYMTAB["thunk_box_thick_devfill"]
RAILSCALE, SCALE_NN = SYMTAB["thunk_filedlg_railscale"], SYMTAB["thunk_sprite_scale_nn"]
HO_HF, HO_DF = SYMTAB["t_bm_ho_hf"], SYMTAB["t_bm_ho_df"]
CODE = ("t_bw_railsum", "t_bw_rimcore", "t_bw_rimx", "t_bw_lmir", "t_bw_mirrect", "t_bw_railscale", "t_bw_railanchor",
        "thunk_bw_boxsprite_console", "thunk_bw_boxsprite_tabframe", "thunk_bw_boxsprite", "thunk_bw_clip",
        "thunk_bw_fill2", "thunk_bw_rect_core", "t_bm_ho_hf", "t_bm_ho_df", "t_bw_fillrect",
        "g_bw_tabrow_tbl")                       # W7H v2: the tab row's (t, T) table, read by the tab-frame adapter


def _uc(g):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(0xA0C000, 0x40000)                 # pcave2 (whole: the W5A code sits at +0x3C000)
    uc.mem_map(0x5D0000, 0x20000)                 # Buffer_set_clip / Buffer_box_sprite / GraphicWin_fill_2 (hlt)
    uc.mem_map(0x410000, 0x1000)                  # site / stub returns
    uc.mem_map(0x660000, 0x10000)                 # g_popup_scale_num
    uc.mem_map(0x6A7000, 0x2000)                  # BaseWin_g's + the production picker's canvas fields
    uc.mem_map(STACK, 0x10000)
    for tid in CODE:
        uc.mem_write(*THUNKS[tid])
    for va in (HOLLOW, DEVFILL, BOX_SPRITE, SET_CLIP, FILL_2, SITE_RET, STUB_RET, RAILSCALE, SCALE_NN):
        uc.mem_write(va, b"\xF4")
    uc.mem_write(G_VA, struct.pack("<i", g))
    w = (SL.BASEWIN_NATIVE_W * g) >> 4 if g > 16 else SL.BASEWIN_NATIVE_W
    h = (SL.BASEWIN_NATIVE_H * g) >> 4 if g > 16 else SL.BASEWIN_NATIVE_H
    uc.mem_write(CANVAS + 0x80, struct.pack("<2i", w, -h))
    return uc


def _go(uc, va, regs, stack, count=600):
    esp = STACK + 0x8000
    uc.mem_write(esp, b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in stack))
    uc.reg_write(UC_X86_REG_ESP, esp)
    for r, v in regs.items():
        uc.reg_write(r, v)
    try:
        uc.emu_start(va, 0, count=count)
    except unicorn.UcError:
        pass
    return uc.reg_read(UC_X86_REG_EIP), esp


def _at(eip, t):
    return eip in (t, t + 1)


def _ret(uc, tid, regs):
    eip, esp = _go(uc, THUNKS[tid][0], regs, [SITE_RET])
    assert _at(eip, SITE_RET) and uc.reg_read(UC_X86_REG_ESP) == esp + 4, (tid, hex(eip))


def _rect(uc):
    return struct.unpack("<4i", uc.mem_read(G_BW_RECT, 16))


# ---------------------------------------------------------------- the helpers
@pytest.mark.parametrize("g", G_RANGE)
def test_railsum_is_the_content_axis(g):
    uc = _uc(g)
    _ret(uc, "t_bw_railsum", {UC_X86_REG_EDX: 0x3333, UC_X86_REG_ECX: 0x2222})
    assert uc.reg_read(UC_X86_REG_EAX) == SL.basewin_rail_axis_sum(g) == ((726 * g) >> 4 if g > 16 else 726)
    assert uc.reg_read(UC_X86_REG_EDX) == SL.basewin_rail_left_extent(g) and uc.reg_read(UC_X86_REG_ECX) == 0x2222


@pytest.mark.parametrize("g", G_RANGE)
def test_lmir_is_the_law(g):
    """t_bw_lmir (v4): a native LEFT edge -> basewin_left_x (>= 563 the exclusive axis mirror, else pt)."""
    uc = _uc(g)
    for l in list(range(0, 800, 37)) + list(range(555, 572)):
        _ret(uc, "t_bw_lmir", {UC_X86_REG_EDX: l, UC_X86_REG_EAX: 0x1111, UC_X86_REG_ECX: 0x2222})
        assert uc.reg_read(UC_X86_REG_EDX) & 0xFFFFFFFF == SL.basewin_left_x(l, g) & 0xFFFFFFFF, (l, g)
        assert uc.reg_read(UC_X86_REG_EAX) == 0x1111 and uc.reg_read(UC_X86_REG_ECX) == 0x2222


@pytest.mark.parametrize("g", G_RANGE)
def test_rimx_is_the_law(g):
    uc = _uc(g)
    for r in list(range(0, 800, 37)) + list(range(686, 704)):
        _ret(uc, "t_bw_rimx", {UC_X86_REG_EDX: r, UC_X86_REG_EAX: 0x1111, UC_X86_REG_ECX: 0x2222})
        assert uc.reg_read(UC_X86_REG_EDX) == SL.basewin_rim_x(r, g), (r, g)
        assert uc.reg_read(UC_X86_REG_EAX) == 0x1111 and uc.reg_read(UC_X86_REG_ECX) == 0x2222


#: every centre box / clip / fill rect the pristine image draws (BaseWin_init + the centre painters, census W5A),
#: plus probes on each side of every arm (563 / 562 left, 690 / 689 / 699 / 700 right, l + r == 726 or not)
RECTS = [(563, 33, 699, 257), (566, 36, 696, 56), (566, 57, 696, 254), (166, 352, 699, 441), (346, 376, 696, 438),
         (169, 355, 696, 375), (166, 260, 699, 349), (298, 263, 697, 325), (169, 326, 696, 346), (166, 33, 560, 257),
         (167, 34, 559, 256), (27, 33, 163, 187), (30, 36, 160, 56), (27, 190, 163, 384), (27, 387, 163, 443),
         (128, 446, 622, 472), (169, 376, 297, 396), (299, 376, 344, 396), (365, 268, 369, 277), (555, 268, 559, 277),
         (562, 10, 699, 20), (563, 10, 650, 20), (100, 10, 690, 20), (100, 10, 689, 20), (100, 10, 700, 20),
         (300, 10, 426, 20), (301, 10, 426, 20), (167, 34, 559, 256), (167, 34, 559, 255), (166, 34, 559, 256),
         (0, 0, 758, 490)]


@pytest.mark.parametrize("g", G_RANGE)
def test_mirrect_is_the_law(g):
    if g <= 16:
        return                  # reached only past the callers' canvas gate
    uc = _uc(g)
    rect_va = STACK + 0x100
    for rect in RECTS:
        uc.mem_write(rect_va, struct.pack("<4i", *rect))
        _ret(uc, "t_bw_mirrect", {UC_X86_REG_EAX: rect_va, UC_X86_REG_EDX: 0x7777, UC_X86_REG_ECX: 0x2222,
                                  UC_X86_REG_EBX: 0x5555})
        assert _rect(uc) == SL.basewin_mirror_rect(*rect, g), (rect, g)
        assert (uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_ECX), uc.reg_read(UC_X86_REG_EBX)) == \
            (rect_va, 0x2222, 0x5555)
        assert struct.unpack("<4i", uc.mem_read(rect_va, 16)) == rect, "the caller's local is never written"


# ---------------------------------------------------------------- the rails
SPRITE = 0x7CFFC4


@pytest.mark.parametrize("g", G_RANGE)
def test_railscale_bw_puts_the_basewin_strips_on_the_mirror(g):
    w = (758 * g) >> 4 if g > 16 else 758
    for x, y, dest in ((x, y, d) for x in (0, 15, w - 55, w - 47) for y in (0, 7, 100) for d in (CANVAS,)):
        if True:
            uc = _uc(g)
            uc.mem_write(dest + 0x80, struct.pack("<i", w))
            eip, esp = _go(uc, THUNKS["t_bw_railscale"][0], {UC_X86_REG_ECX: SPRITE},
                           [SITE_RET, dest, 9, x, y, 1, 1])
            args = struct.unpack("<I2I4i", uc.mem_read(esp, 28))
            assert uc.reg_read(UC_X86_REG_ECX) == SPRITE and uc.reg_read(UC_X86_REG_ESP) == esp
            if g <= 16:
                assert _at(eip, RAILSCALE) and args == (SITE_RET, dest, 9, x, y, 1, 1)
                continue
            assert _at(eip, SCALE_NN), (g, x, hex(eip))
            assert args == (SITE_RET, dest, 9, SL.basewin_rail_strip_x(w, x, g), (y * g) >> 4, g, 16), (g, x, args)
    if g > 16:      # the right rails end ON the axis, inside the canvas
        assert SL.basewin_rail_strip_x(w, w - 47, g) + ((15 * g) >> 4) == SL.basewin_rail_axis_sum(g) <= w


@pytest.mark.parametrize("g", (17, 22, 25, 33, 40))
def test_railscale_bw_passes_every_other_dest_through(g):
    for dest in (0x9B7490, CANVAS + 4, PP_CANVAS, PP_CANVAS + 4, 0x6FEC80 + 0x444):   # the picker passes through
        uc = _uc(g)
        eip, esp = _go(uc, THUNKS["t_bw_railscale"][0], {UC_X86_REG_ECX: SPRITE}, [SITE_RET, dest, 9, 700, 5, 1, 1])
        assert _at(eip, RAILSCALE) and uc.reg_read(UC_X86_REG_ESP) == esp
        assert struct.unpack("<I2I4i", uc.mem_read(esp, 28)) == (SITE_RET, dest, 9, 700, 5, 1, 1)


@pytest.mark.parametrize("g", range(17, 41))
def test_railanchor_basewin_and_the_double_floor(g):
    for winbuf, widths in ((CANVAS, [(758 * g) >> 4]), (PP_CANVAS, [(758 * g) >> 4]),
                           (0x1234560, list(range(400, 2400, 97)))):   # the picker takes the double floor (W5A v3)
        for w in widths:
            uc = _uc(g)
            uc.mem_write(G_FD_WINBUF, struct.pack("<I", winbuf))
            _ret(uc, "t_bw_railanchor", {UC_X86_REG_EDX: w, UC_X86_REG_EBX: g, UC_X86_REG_ECX: 0x2222})
            want = SL.basewin_rail_anchor(g) if winbuf == CANVAS else SL.popup_scale_floor(
                SL.rail_right_anchor(w, w - 0x37, g), g)
            assert uc.reg_read(UC_X86_REG_EAX) == want, (g, w, hex(winbuf))
            assert uc.reg_read(UC_X86_REG_EBX) == g and uc.reg_read(UC_X86_REG_ECX) == 0x2222


# ---------------------------------------------------------------- the box / text / clip / fill adapters
def _box(tid, g, rect, fill, tail=True):
    """tail: the adapter tail-jumps its renderer (esp unchanged at the stop); False: it stops inside a helper's call."""
    uc = _uc(g)
    rect_va, params = STACK + 0x100, STACK + 0x200
    uc.mem_write(rect_va, struct.pack("<4i", *rect))
    uc.mem_write(params + 0x20, struct.pack("<I", 1 if fill else 0))
    eip, esp = _go(uc, THUNKS[tid][0], {UC_X86_REG_ECX: CANVAS}, [SITE_RET, rect_va, params])
    assert (uc.reg_read(UC_X86_REG_ESP) == esp or not tail) and uc.reg_read(UC_X86_REG_ECX) == CANVAS
    argp = struct.unpack("<I", uc.mem_read(esp + 4, 4))[0]
    return uc, eip, argp, rect_va


@pytest.mark.parametrize("g", G_RANGE)
def test_console_v4_is_the_rails_span(g):
    for fill in (True, False):
        uc, eip, argp, rect_va = _box("thunk_bw_boxsprite_console", g, (23, 0, 703, 493), fill)
        if g <= 16:
            assert _at(eip, BOX_SPRITE) and argp == rect_va
            continue
        assert _at(eip, DEVFILL if fill else HOLLOW) and argp == G_BW_RECT
        assert _rect(uc) == SL.basewin_console_frame_rect(g)


@pytest.mark.parametrize("g", G_RANGE)
def test_tabframe_v4_on_the_axis(g):
    uc, eip, argp, rect_va = _box("thunk_bw_boxsprite_tabframe", g, (27, 4, 699, 30), True)
    if g <= 16:
        assert _at(eip, BOX_SPRITE) and argp == rect_va
        return
    assert _at(eip, DEVFILL) and argp == G_BW_RECT
    pt = lambda v: SL.basewin_pt(v, g)  # noqa: E731
    assert _rect(uc) == (pt(27), SL.basewin_tabframe_top(g), SL.basewin_tabframe_right(g), SL.basewin_tabframe_bottom(g))
    assert _rect(uc)[2] == SL.basewin_box_draw_rect(563, 33, 699, 257, g)[2], "flush with the right panel's rim"


@pytest.mark.parametrize("g", G_RANGE)
def test_boxsprite_mirrors(g):
    """v4 (F42): the half-open mirrored rect into g_bw_rect, push + ret to the shared trim helper (t_bm_ho_df for a
    fill-bearing set, t_bm_ho_hf for a hollow one), which CALLs the band renderer with R - 1 / B - 1
    (basewin_box_draw_rect), then restores the rect and returns to the site (RET 8: stack and ecx intact)."""
    for rect in RECTS[:-1]:
        fill = rect[0] % 2 == 0
        uc, eip, argp, rect_va = _box("thunk_bw_boxsprite", g, rect, fill, tail=g <= 16)
        if g <= 16:
            assert _at(eip, BOX_SPRITE) and argp == rect_va
            continue
        # stopped at the renderer stub, CALLed by the helper: [esp] = its return, [esp+4] = rect*, [esp+8] = params
        assert _at(eip, DEVFILL if fill else HOLLOW), (rect, g, hex(eip))
        esp = uc.reg_read(UC_X86_REG_ESP)
        hret, rp, params = struct.unpack("<3I", uc.mem_read(esp, 12))
        helper = HO_DF if fill else HO_HF
        assert helper < hret < helper + 0x40 and rp == G_BW_RECT and params == STACK + 0x200, (rect, g)
        assert _rect(uc) == SL.basewin_box_draw_rect(*rect, g), (rect, g)
        assert uc.reg_read(UC_X86_REG_ECX) == CANVAS
        assert struct.unpack("<4i", uc.mem_read(rect_va, 16)) == rect, "the caller's local is never written"
        # the renderer returns (thiscall RET 8): the helper restores R / B and returns to the site, args popped
        uc.mem_write(RENDER_RET, b"\xC2\x08\x00")
        try:
            uc.emu_start(RENDER_RET, 0, count=200)
        except unicorn.UcError:
            pass
        assert _at(uc.reg_read(UC_X86_REG_EIP), SITE_RET), (rect, g, hex(uc.reg_read(UC_X86_REG_EIP)))
        assert uc.reg_read(UC_X86_REG_ECX) == CANVAS
        assert _rect(uc) == SL.basewin_mirror_rect(*rect, g), "the helper restores the half-open rect"


@pytest.mark.parametrize("g", G_RANGE)
def test_clip_fill_and_text_rects(g):
    pt = lambda v: SL.basewin_pt(v, g)  # noqa: E731
    rect_va = STACK + 0x100
    for rect in RECTS:
        # set_clip adapter: thiscall (rect*) -> tail-jmp Buffer_set_clip; GraphicWin_fill_2 adapter: this = BaseWin
        for tid, ecx, target in (("thunk_bw_clip", CANVAS, SET_CLIP), ("thunk_bw_fill2", BW, FILL_2)):
            uc = _uc(g)
            uc.mem_write(rect_va, struct.pack("<4i", *rect))
            eip, esp = _go(uc, THUNKS[tid][0], {UC_X86_REG_ECX: ecx}, [SITE_RET, rect_va, 7])
            argp = struct.unpack("<I", uc.mem_read(esp + 4, 4))[0]
            assert _at(eip, target) and uc.reg_read(UC_X86_REG_ECX) == ecx and uc.reg_read(UC_X86_REG_ESP) == esp
            if g <= 16:
                assert argp == rect_va
            else:
                want = SL.basewin_fill_rect(*rect, g) if tid == "thunk_bw_fill2" else SL.basewin_mirror_rect(*rect, g)
                assert argp == G_BW_RECT and _rect(uc) == want, (tid, rect, g)
            assert struct.unpack("<4i", uc.mem_read(rect_va, 16)) == rect, "the caller's local is never written"
        # rect_core (text): CALL-entered from a stub ([esp] stub ret, [esp+4] site ret, [esp+8] str, [esp+0xC] rect*)
        uc = _uc(g)
        uc.mem_write(rect_va, struct.pack("<4i", *rect))
        eip, esp = _go(uc, THUNKS["thunk_bw_rect_core"][0], {UC_X86_REG_ECX: CANVAS},
                       [STUB_RET, SITE_RET, 0xABCD, rect_va])
        argp = struct.unpack("<I", uc.mem_read(esp + 0xC, 4))[0]
        assert _at(eip, STUB_RET) and uc.reg_read(UC_X86_REG_ECX) == CANVAS
        if g <= 16:
            assert argp == rect_va
        else:
            assert argp == G_BW_RECT
            assert _rect(uc) == SL.basewin_text_rect(*rect, g), (rect, g)
            if rect[0] >= 563 and SL.basewin_is_rim(rect[2]):     # a right-column text box IS its drawn box
                L, _t, R, _b = SL.basewin_box_draw_rect(*rect, g)
                assert (_rect(uc)[0], _rect(uc)[2]) == (L, R + 1), (rect, g)
