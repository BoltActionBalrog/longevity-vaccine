"""Unicorn parity for the Hall of Fame bake (assemble_mon.py, the t_hof_* thunks sharing the Monument's block).

Oracle = scaling_laws.hof_* (the Monument's laws with the HOF origin/cells, clamped to HOF_NUM_MAX).  Every thunk is
emulated from its REAL assembled bytes at its REAL cave VA; engine callees and the shared cave helpers
(t_dl_immfix, t_rwk_parity_nn, t_rw_iconblit, t_mon_resample) are recording stubs.  Covers: the build lever
(num/clamp/letterbox/content rect/6 rects/13 icon buttons/CLOSE/3 fonts incl. the scratch Font_init path/row
pitch/the imm walk with g_dl_immg bracketed, native no-op at 1024x768 and in the narrow layout, builder failure
passthrough, fonts inited once per num), the painter imm table (identity at 16, values by the walker oracle, imm8
range up to the clamp, no row inside any HOF site), the three backdrop wrappers, the picture wrapper, the face
chain head (hit: re-centred parity NN at num/16 under the g bracket; miss: chain), the gate and restripe
extensions, the five font detours (flag/register transparent), and the sites' pristine-byte contracts.
"""
from __future__ import annotations

import struct

import pytest

from test_mon_asm_parity import (  # noqa: E402
    AM, BUILD_SWEEP, C, LAYOUT, NARROW_RES, OBJ, PLANES, REC, RES, SE, SL, SP0, STUB, TRAP, VA, _END, _cs, _face, Emu,
    make_buffer, r32, r32s, rand_pal, set_screen, w32,
)

HRES = RES + ((7680, 4320),)
FW = AM.FW
REC2 = REC + 0x800            # this file's recorders (the Monument's live at REC..REC+0x480)
FONT_OBJ = OBJ + 0x20000      # fake Font objects handed out by the find_font stub (0x40 apart)
IMMFIX_REC = REC2 + 0x400


def _hof_arm(e, sw, sh):
    num = SL.hof_scale_num(sw, sh)
    lx, ly = SL.hof_letterbox(sw, sh, num)
    ox, oy = SL.hof_origin(num, lx, ly)
    for k, v in (("g_hof_num", num), ("g_hof_armed", 1 if num > 16 else 0), ("g_hof_lx", lx), ("g_hof_ly", ly), ("g_hof_ox", ox), ("g_hof_oy", oy)):
        w32(e.uc, C[k], v)
    return num, lx, ly


# ---- sites ------------------------------------------------------------------------------------------------------
SITES = [s for s in AM.site_list(dict(VA)) if s["id"].startswith(("hall_of_fame.", "FameWin_draw.")) or s["id"] == "FlatButton_content_draw.faction_dropdown_img"]


def test_sites_match_the_pristine_base_and_end_on_instruction_boundaries():
    assert AM.verify_live(SITES) == []
    for s in SITES:
        b = SE.base_exe_bytes(s["va"], len(s["orig"]) + 16)
        ends = {i.address + i.size for i in _cs.disasm(b, s["va"])}
        assert s["va"] + len(s["orig"]) in ends, s["id"]
    assert len(SITES) == 11
    face = next(s for s in SITES if s["va"] == 0x607F43)
    assert face["orig"] == bytes([0xE8]) + struct.pack("<i", 0x5E4B4A - 0x607F48) and face["group"] == "faction_pickwin_buttons"
    assert face["new"] == "E8 {rel32:t_hof_face}"
    call = next(s for s in SITES if s["va"] == AM.HOF_CALL_SITE)
    assert call["orig"] == bytes([0xE8]) + struct.pack("<i", AM.LOAD_HOFICONS - (AM.HOF_CALL_SITE + 5))


def test_block_fits_the_grown_section():
    assert AM.SECTION_END == 0x30000 and _END <= AM.SECTION_END
    for name in ("t_hof_build", "t_hof_face", "g_hof_immtab", "g_hof_rects"):
        assert LAYOUT[name][0] >= 0x2B000


# ---- the painter imm table ------------------------------------------------------------------------------------------
def test_imm_rows_identity_values_and_layout():
    rows = AM.hof_imm_rows()
    assert len(rows) == len(AM.HOF_PAINTER_IMMS) == 23
    assert len({r[0] for r in rows}) == 23
    for (site, w, a, b, _l), (rs, ra, rb, bits) in zip(AM.HOF_PAINTER_IMMS, rows):
        assert (site, a, b) == (rs, ra, rb) and bits == (1 if w == 4 else 0)
        nat = SE.base_exe_bytes(site, w)
        v = struct.unpack("<i", nat)[0] if w == 4 else struct.unpack("<b", nat)[0]
        assert v == a - b, hex(site)
        for num in (16, 22, 25, 45, SL.HOF_NUM_MAX):
            v = SL.mon_s(a, num) - SL.mon_s(b, num)
            if w == 1:
                assert -128 <= v <= 127, (hex(site), num, v)
    # a row may not touch any HOF site (the walker stores at runtime, after the patcher)
    for site, _a, _b, bits in rows:
        w = 4 if bits & 1 else 1
        for s in SITES:
            assert not (site < s["va"] + len(s["orig"]) and s["va"] < site + w), (hex(site), s["id"])
    tab = AM.hof_immtab()
    assert len(tab) == 23 * 16 + 4 and tab[-4:] == b"\0\0\0\0"
    for k, (site, a, b, bits) in enumerate(rows):
        assert struct.unpack_from("<IiiI", tab, 16 * k) == (site, a, b, bits)
    # the walker's oracle agrees with the law for every row
    import assemble_dl as AD
    for site, a, b, bits in rows:
        for num in (16, 22, 25, 45, 72):
            assert AD.imm_value(a, b, bits, num) == SL.mon_s(a, num) - SL.mon_s(b, num)


# ---- build lever ---------------------------------------------------------------------------------------------------
def _seed_hof(e, sw, sh, wide=1, builder_ret=0, fonts=((3, 40, 30), (-1, 44, 33), (2, 60, 50))):
    """FameWin at its static, the builder's native fields, 13 icon buttons + CLOSE with a redraw vtbl, recorders."""
    uc = e.uc
    set_screen(e, sw, sh, wide)
    uc.mem_write(FW, bytes(0xC000))
    for k, v in enumerate(SL.HOF_CONTENT_NATIVE):
        w32(uc, FW + 0xA24 + 4 * k, v)
    w32(uc, FW + 0xA1C, 108)
    w32(uc, FW + 0xA20, 600)
    w32(uc, FW + 0xA44, 17)
    for i, r in enumerate(SL.HOF_RECTS_NATIVE):
        for k in range(4):
            w32(uc, FW + 0xB42C + 16 * i + 4 * k, r[k])
    w32(uc, STUB + 0x800 + 0xF8, STUB + 0x300)              # button vtbl: +0xF8 = redraw recorder
    btns = [AM.HOF_CAT0 + i * 0xB4C for i in range(6)] + [AM.HOF_FAC0 + i * 0xB4C for i in range(7)] + [AM.HOF_CLOSE]
    nat = list(SL.hof_button_rects(16, 0, 0)) + [SL.hof_close_rect(16, 0, 0)]
    for btn, (x, y, w, h) in zip(btns, nat):
        w32(uc, btn, STUB + 0x800)
        for k, v in enumerate((x, y, x + w, y + h)):
            w32(uc, btn + 0x13C + 4 * k, v)
        for k, v in enumerate((0, 0, w, h)):
            w32(uc, btn + 0x474 + 4 * k, v)
    # fake fonts: find_font hands out FONT_OBJ + n*0x40 (fields pad/cell/cap), Font_init records and leaves the scratch as is
    for n in range(8):
        pad, cell, cap = fonts[n % len(fonts)]
        w32(uc, FONT_OBJ + 0x40 * n, pad)
        w32(uc, FONT_OBJ + 0x40 * n + 0xC, cell)
        w32(uc, FONT_OBJ + 0x40 * n + 0x10, cap)
    for k, tab in enumerate(AM.HOF_FONT_TABLES):
        w32(uc, tab, 0x7000 + k)
    w32(uc, AM.G_DL_IMMG, 0x1234)
    uc.mem_write(REC2, bytes(0x800))
    e.stub(AM.LOAD_HOFICONS, f"mov dword ptr [{REC2:#x}], ecx\nmov eax, {builder_ret}\nret\n")
    e.stub(AM.BUFFER_SET_CLIP, f"mov dword ptr [{REC2 + 0x600:#x}], ecx\nmov eax, [esp+4]\nmov dword ptr [{REC2 + 0x604:#x}], eax\ninc dword ptr [{REC2 + 0x608:#x}]\nmov eax, dword ptr [{REC2 + 0x208:#x}]\nmov dword ptr [{REC2 + 0x60C:#x}], eax\nret 4\n")
    e.stub(AM.GW_RESIZE, f"""
        mov eax, dword ptr [{REC2 + 4:#x}]
        push edx
        mov edx, dword ptr [{C['g_hof_armed']:#x}]
        mov dword ptr [{REC2 + 0x700:#x}+eax*4], edx
        pop edx
        shl eax, 4
        mov dword ptr [{REC2 + 0x10:#x}+eax], ecx
        push edx
        mov edx, dword ptr [esp+8]
        mov dword ptr [{REC2 + 0x14:#x}+eax], edx
        mov edx, dword ptr [esp+0xC]
        mov dword ptr [{REC2 + 0x18:#x}+eax], edx
        mov edx, dword ptr [esp+0x10]
        mov dword ptr [{REC2 + 0x1C:#x}+eax], edx
        pop edx
        inc dword ptr [{REC2 + 4:#x}]
        xor eax, eax
        ret 0xC
    """)
    e.stub(AM.GW_CLEAR, f"mov dword ptr [{REC2 + 0x200:#x}], ecx\nmov eax, [esp+4]\nmov dword ptr [{REC2 + 0x204:#x}], eax\ninc dword ptr [{REC2 + 0x208:#x}]\nret 4\n")
    e.stub(AM.FIND_FONT, f"""
        mov eax, dword ptr [{REC2 + 0x300:#x}]
        push edx
        mov edx, dword ptr [esp+8]
        mov dword ptr [{REC2 + 0x304:#x}+eax*8], edx
        mov edx, dword ptr [esp+0xC]
        mov dword ptr [{REC2 + 0x308:#x}+eax*8], edx
        pop edx
        inc dword ptr [{REC2 + 0x300:#x}]
        shl eax, 6
        add eax, {FONT_OBJ:#x}
        ret
    """)
    e.stub(AM.FONT_INIT, f"""
        mov eax, dword ptr [{REC2 + 0x380:#x}]
        shl eax, 4
        mov dword ptr [{REC2 + 0x390:#x}+eax], ecx
        push edx
        mov edx, dword ptr [esp+8]
        mov dword ptr [{REC2 + 0x394:#x}+eax], edx
        mov edx, dword ptr [esp+0xC]
        mov dword ptr [{REC2 + 0x398:#x}+eax], edx
        mov edx, dword ptr [esp+0x10]
        mov dword ptr [{REC2 + 0x39C:#x}+eax], edx
        pop edx
        inc dword ptr [{REC2 + 0x380:#x}]
        xor eax, eax
        ret 0xC
    """)
    e.stub(AM.T_DL_IMMFIX, f"mov dword ptr [{IMMFIX_REC:#x}], esi\nmov eax, dword ptr [{AM.G_DL_IMMG:#x}]\nmov dword ptr [{IMMFIX_REC + 4:#x}], eax\ninc dword ptr [{IMMFIX_REC + 8:#x}]\nret\n")
    e.stub(STUB + 0x300, f"mov eax, dword ptr [{REC2 + 0x500:#x}]\nmov dword ptr [{REC2 + 0x504:#x}+eax*4], ecx\ninc dword ptr [{REC2 + 0x500:#x}]\nret\n")
    # fonts v2: the CLOSE label = t_fdirect_at(g_font_hof_btn, 14, 1, num); recorder count @+0x580, 16B entries
    e.stub(AM.T_FDIRECT_AT, f"""
        mov eax, dword ptr [{REC2 + 0x580:#x}]
        shl eax, 4
        push edx
        mov edx, dword ptr [esp+8]
        mov dword ptr [{REC2 + 0x584:#x}+eax], edx
        mov edx, dword ptr [esp+0xC]
        mov dword ptr [{REC2 + 0x588:#x}+eax], edx
        mov edx, dword ptr [esp+0x10]
        mov dword ptr [{REC2 + 0x58C:#x}+eax], edx
        mov edx, dword ptr [esp+0x14]
        mov dword ptr [{REC2 + 0x590:#x}+eax], edx
        pop edx
        inc dword ptr [{REC2 + 0x580:#x}]
        mov eax, dword ptr [esp+4]
        ret
    """)
    return btns


def _fdirects(uc):
    n = r32(uc, REC2 + 0x580)
    return [tuple(r32(uc, REC2 + 0x584 + 16 * k + 4 * j) for j in range(4)) for k in range(n)]


def _resizes(uc):
    n = r32(uc, REC2 + 4)
    return [(r32(uc, REC2 + 0x10 + 16 * k), r32(uc, REC2 + 0x14 + 16 * k), r32(uc, REC2 + 0x18 + 16 * k), r32(uc, REC2 + 0x1C + 16 * k)) for k in range(n)]


def _find_fonts(uc):
    n = r32(uc, REC2 + 0x300)
    return [(r32(uc, REC2 + 0x304 + 8 * k), r32(uc, REC2 + 0x308 + 8 * k)) for k in range(n)]


def _font_inits(uc):
    n = r32(uc, REC2 + 0x380)
    return [(r32(uc, REC2 + 0x390 + 16 * k), r32(uc, REC2 + 0x394 + 16 * k), r32(uc, REC2 + 0x398 + 16 * k), r32(uc, REC2 + 0x39C + 16 * k)) for k in range(n)]


@pytest.mark.parametrize("sw,sh", HRES + NARROW_RES)
def test_build_lever_matches_the_laws(sw, sh):
    e = Emu()
    btns = _seed_hof(e, sw, sh)
    uc = e.uc
    uc.mem_write(SP0, struct.pack("<I", TRAP))
    e.run(VA["t_hof_build"], ecx=FW, esi=0x1234, ebx=0x5678, edi=0x9ABC, ebp=0xDEF0)
    assert e.reg("eax") == 0 and e.reg("esi") == 0x1234 and e.reg("ebx") == 0x5678 and e.reg("edi") == 0x9ABC and e.reg("ebp") == 0xDEF0
    assert e.reg("esp") == SP0 + 4
    assert r32(uc, REC2) == FW
    num = SL.hof_scale_num(sw, sh)
    armed = SL.hof_armed(sw, sh, 1)
    assert r32(uc, C["g_hof_num"]) == num
    assert r32(uc, C["g_hof_armed"]) == (1 if armed else 0)
    if not armed:
        assert _resizes(uc) == [] and r32(uc, REC2 + 0x208) == 0 and _find_fonts(uc) == [] and r32(uc, IMMFIX_REC + 8) == 0
        assert tuple(r32(uc, FW + 0xA24 + 4 * k) for k in range(4)) == SL.HOF_CONTENT_NATIVE
        for i, r in enumerate(SL.HOF_RECTS_NATIVE):
            assert tuple(r32(uc, FW + 0xB42C + 16 * i + 4 * k) for k in range(4)) == r
        assert r32(uc, FW + 0xA44) == 17 and r32(uc, AM.G_DL_IMMG) == 0x1234
        return
    lx, ly = SL.hof_letterbox(sw, sh, num)
    ox, oy = SL.hof_origin(num, lx, ly)
    assert (r32s(uc, C["g_hof_lx"]), r32s(uc, C["g_hof_ly"]), r32s(uc, C["g_hof_ox"]), r32s(uc, C["g_hof_oy"])) == (lx, ly, ox, oy)
    assert (r32(uc, C["g_hof_sw"]), r32(uc, C["g_hof_sh"])) == (sw, sh)
    assert r32(uc, C["g_mon_lut_ok"]) == 0
    # window
    rs = _resizes(uc)
    assert rs[0] == (FW, sw, sh, 1)
    assert tuple(r32(uc, FW + 0x13C + 4 * k) for k in range(4)) == (0, 0, sw, sh)
    assert tuple(r32(uc, FW + 0x474 + 4 * k) for k in range(4)) == (0, 0, sw, sh)
    assert (r32(uc, REC2 + 0x200), r32(uc, REC2 + 0x204), r32(uc, REC2 + 0x208)) == (FW, 0, 1)
    # the resize's own repaint runs UNARMED (native, cheap); the clip is the whole window before the clear (v1 ghost)
    assert r32(uc, REC2 + 0x700) == 0 and r32(uc, REC2 + 0x704) == 1
    assert (r32(uc, REC2 + 0x600), r32(uc, REC2 + 0x604), r32(uc, REC2 + 0x608), r32(uc, REC2 + 0x60C)) == (FW + 0x444, FW + 0x474, 1, 0)
    assert tuple(r32s(uc, FW + 0xA24 + 4 * k) for k in range(4)) == SL.hof_content_rect(num, lx, ly)
    # the 6 rects rebuilt from the literals
    for i, want in enumerate(SL.hof_rects(num, lx, ly)):
        got = tuple(r32s(uc, FW + 0xB42C + 16 * i + 4 * k) for k in range(4))
        assert got == want, i
    # 13 icon buttons then CLOSE: resize, move, own rect
    want_btns = list(SL.hof_button_rects(num, lx, ly)) + [SL.hof_close_rect(num, lx, ly)]
    assert len(rs) == 15
    for n, (btn, (x, y, w, h)) in enumerate(zip(btns, want_btns)):
        assert rs[1 + n] == (btn, w, h, 1), n
        assert tuple(r32s(uc, btn + 0x13C + 4 * k) for k in range(4)) == (x, y, x + w, y + h), n
        assert tuple(r32s(uc, btn + 0x474 + 4 * k) for k in range(4)) == (0, 0, w, h), n
    redraws = [r32(uc, REC2 + 0x504 + 4 * k) for k in range(r32(uc, REC2 + 0x500))]
    assert redraws == btns
    # fonts v2: CLOSE label t_fdirect_at(g_font_hof_btn, 14, 1, num) (Arial 14 bold law); painter fonts by
    # size (the pool, or the scratch Font_init'd Arial Narrow BOLD above 40 -- v1 pushed style 0)
    ff = _find_fonts(uc)
    fi = _font_inits(uc)
    assert _fdirects(uc) == [(AM.G_FONT_HOF_BTN, SL.HOF_FONT_LABEL, 1, num)]
    assert r32(uc, AM.HOF_CLOSE + 0x970) == AM.G_FONT_HOF_BTN
    k_ff, k_fi = 0, 0
    for k, sz in enumerate(SL.HOF_FONTS):
        n = SL.hof_font_size(sz, num)
        scratch = C["g_hof_fontscratch"] + 0x28 * k
        if SL.hof_font_scratch(sz, num):
            assert fi[k_fi] == (scratch, AM.AN_STR, n, SL.HOF_FONT_SCRATCH_STYLE), (sz, num)
            assert SL.font_pool_face(sz, 0) == ("Arial Narrow", SL.HOF_FONT_SCRATCH_STYLE)
            assert r32(uc, C[AM.HOF_FONT_CELLS[k]]) == scratch
            k_fi += 1
        else:
            assert ff[k_ff] == (n, 0), (sz, num)
            assert r32(uc, C[AM.HOF_FONT_CELLS[k]]) == FONT_OBJ + 0x40 * k_ff
            k_ff += 1
    assert len(ff) == k_ff and len(fi) == k_fi
    assert r32(uc, C["g_hof_fonts_num"]) == num
    # row pitch from the body font's fields, exactly as load_hoficons reads them
    f14 = r32(uc, C["g_hof_f14"])
    assert r32(uc, FW + 0xA44) == SL.hof_line_height(r32s(uc, f14), r32(uc, f14 + 0xC), r32(uc, f14 + 0x10))
    # the imm walk: once, over our table, with the walker's g == num, restored after
    assert r32(uc, IMMFIX_REC + 8) == 1 and r32(uc, IMMFIX_REC) == VA["g_hof_immtab"] and r32(uc, IMMFIX_REC + 4) == num
    assert r32(uc, AM.G_DL_IMMG) == 0x1234
    # fix 11: the art, the 13 icon buttons and CLOSE lie inside the screen (num's width term)
    assert 0 <= lx and 0 <= ly and lx + SL.mon_s(1024, num) <= sw and ly + SL.mon_s(768, num) <= sh
    for btn in btns:
        l, t, r, b = (r32s(uc, btn + 0x13C + 4 * k) for k in range(4))
        assert 0 <= l and 0 <= t and r <= sw and b <= sh, hex(btn)


def test_build_lever_num_is_scale_uniform_16_and_keeps_the_art_on_screen_over_a_sweep():
    """The REAL t_hof_build (calling the shipped scale_uniform, then the 72 clamp): num / armed / letterbox == the law
    at every screen of the Monument's grid, and every armed layout keeps the art, the 13 icon buttons and CLOSE inside
    the screen."""
    bad = []
    for sw, sh in list(BUILD_SWEEP) + [(7680, 4320), (6144, 4608)]:
        e = Emu()
        btns = _seed_hof(e, sw, sh)
        uc = e.uc
        uc.mem_write(SP0, struct.pack("<I", TRAP))
        e.run(VA["t_hof_build"], ecx=FW)
        num = SL.hof_scale_num(sw, sh)
        armed = SL.hof_armed(sw, sh, 1)
        got = (r32s(uc, C["g_hof_num"]), r32(uc, C["g_hof_armed"]))
        if got != (num, int(armed)):
            bad.append((sw, sh, "num/armed", got, (num, armed)))
            continue
        if not armed:
            continue
        lx, ly = r32s(uc, C["g_hof_lx"]), r32s(uc, C["g_hof_ly"])
        if (lx, ly) != SL.hof_letterbox(sw, sh, num):
            bad.append((sw, sh, "letterbox", (lx, ly)))
        if lx < 0 or ly < 0 or lx + SL.mon_s(1024, num) > sw or ly + SL.mon_s(768, num) > sh:
            bad.append((sw, sh, "art off-screen", (lx, ly, num)))
        for btn in btns:
            l, t, r, b = (r32s(uc, btn + 0x13C + 4 * k) for k in range(4))
            if l < 0 or t < 0 or r > sw or b > sh:
                bad.append((sw, sh, "button off-screen", hex(btn), (l, t, r, b)))
    assert not bad, bad[:8]


def test_build_lever_inits_the_fonts_once_per_num_and_passes_a_failed_builder_through():
    e = Emu()
    btns = _seed_hof(e, 3840, 2160)
    uc = e.uc
    uc.mem_write(SP0, struct.pack("<I", TRAP))
    e.run(VA["t_hof_build"], ecx=FW)
    n_ff, n_fi, n_fd = len(_find_fonts(uc)), len(_font_inits(uc)), len(_fdirects(uc))
    assert n_fi == 2 and n_ff == 1 and n_fd == 1        # 4K: f16/f22 scratch, f14 from the pool, the CLOSE label slot
    e.run(VA["t_hof_build"], ecx=FW)                    # second open at the same num: only the CLOSE label stamp repeats
    assert len(_find_fonts(uc)) == n_ff and len(_font_inits(uc)) == n_fi and len(_fdirects(uc)) == n_fd + 1
    # a failed builder (ret 1): eax passes through untouched, no lever runs
    e = Emu()
    _seed_hof(e, 3840, 2160, builder_ret=1)
    uc = e.uc
    w32(uc, C["g_hof_armed"], 7)
    uc.mem_write(SP0, struct.pack("<I", TRAP))
    e.run(VA["t_hof_build"], ecx=FW, esi=0x11)
    assert e.reg("eax") == 1 and e.reg("esi") == 0x11 and e.reg("esp") == SP0 + 4
    assert _resizes(uc) == [] and r32(uc, C["g_hof_armed"]) == 7 and r32(uc, IMMFIX_REC + 8) == 0


def test_build_lever_is_native_in_the_narrow_layout():
    e = Emu()
    _seed_hof(e, 3840, 2160, wide=0)
    uc = e.uc
    uc.mem_write(SP0, struct.pack("<I", TRAP))
    e.run(VA["t_hof_build"], ecx=FW)
    assert e.reg("eax") == 0 and r32(uc, C["g_hof_armed"]) == 0 and r32(uc, C["g_hof_num"]) == 45
    assert _resizes(uc) == [] and r32(uc, IMMFIX_REC + 8) == 0


# ---- backdrops / picture ---------------------------------------------------------------------------------------------
def _rec_resample(e):
    e.stub(VA["t_mon_resample"], "".join(f"mov eax, dword ptr [esp+{4 + 4 * k}]\nmov dword ptr [{REC + 4 * k:#x}], eax\n" for k in range(11))
           + f"inc dword ptr [{REC + 0x80:#x}]\nret 0x2C\n")


def _rec_parity_nn(e):
    """t_rwk_parity_nn recorder: ecx, the 6 args, the popup g during the call, a copy of the Sprite view."""
    e.stub(AM.T_RWK_PARITY_NN, f"mov dword ptr [{REC2:#x}], ecx\n"
           + "".join(f"mov eax, dword ptr [esp+{4 + 4 * k}]\nmov dword ptr [{REC2 + 4 + 4 * k:#x}], eax\n" for k in range(6))
           + f"mov eax, dword ptr [{AM.G_POPUP:#x}]\nmov dword ptr [{REC2 + 0x20:#x}], eax\n"
           + "".join(f"mov eax, dword ptr [ecx+{4 * k}]\nmov dword ptr [{REC2 + 0x40 + 4 * k:#x}], eax\n" for k in range(10))
           + f"inc dword ptr [{REC2 + 0x24:#x}]\nmov eax, 0x77\nret 0x18\n")


def _rec_pairnn(e):
    """t_hof_pairnn recorder: the 10 args (sdata, spitch, sx, sy, sw, sh, dest, dx, dy, key), count, eax 0x77."""
    e.stub(VA["t_hof_pairnn"], "".join(f"mov eax, dword ptr [esp+{4 + 4 * k}]\nmov dword ptr [{REC2 + 4 + 4 * k:#x}], eax\n" for k in range(10))
           + f"inc dword ptr [{REC2 + 0x30:#x}]\nmov eax, 0x77\nret 0x28\n")


def _pair_source():
    """60x40 synthetic hof-like art: 65/197 row-pair field, a 230 stroke on an odd row and one on an even row, a
    2-row-thick 231 bar, a two-purple (226 even / 224 odd) glyph block, a solid 240 block, scattered key texels."""
    sw, sh = 60, 40
    src = bytearray(sw * sh)
    for y in range(sh):
        for x in range(sw):
            src[y * sw + x] = 65 if y % 2 == 0 else 197
    for x in range(4, 56):
        src[11 * sw + x] = 230                # odd-row stroke
        src[20 * sw + x] = 230                # even-row stroke
        src[26 * sw + x] = 231                # 2-row bar
        src[27 * sw + x] = 231
    for y in range(6, 18):
        for x in range(20, 32):
            src[y * sw + x] = 226 if y % 2 == 0 else 224
    for y in range(30, 36):
        for x in range(40, 50):
            src[y * sw + x] = 240
    for k in range(0, sw * sh, 97):
        src[k] = 9
    return src, sw, sh


@pytest.mark.parametrize("num", (22, 25, 45))
@pytest.mark.parametrize("dx,dy,y0", ((5, 3, 7), (-4, -6, 0), (150, 100, 13)))
def test_pairnn_is_bit_exact_against_the_law(num, dx, dy, y0):
    e = Emu()
    uc = e.uc
    w32(uc, C["g_hof_num"], num)
    pal = bytearray(rand_pal(3))
    for i, rgb in ((65, (0, 0, 0)), (197, (24, 18, 11)), (230, (15, 86, 161)), (231, (28, 69, 136)), (226, (188, 124, 92)), (224, (212, 164, 120)), (240, (100, 100, 100))):
        pal[i * 4:i * 4 + 4] = bytes(rgb) + b"\0"
    src, sw, sh = _pair_source()
    dW, dH = 200, 120
    SDATA, DDATA, DEST = PLANES, PLANES + 0x20000, OBJ + 0x1000
    uc.mem_write(SDATA, bytes(src))
    dst0 = bytes(0xEE for _ in range(dW * dH))
    uc.mem_write(DDATA, dst0)
    make_buffer(e, DEST, DDATA, dW, dH, dW, bytes(pal))
    w32(uc, DEST - 0x304, y0)
    want = bytearray(dst0)
    dw, dh = SL.hof_pair_enlarge(src, sw, 0, 0, sw, sh, bytes(pal), num, want, dW, dW, dH, dx, dy, y0, 9)
    assert want != dst0
    uc.mem_write(SP0, struct.pack("<11I", TRAP, SDATA, sw, 0, 0, sw, sh, DEST, dx & 0xFFFFFFFF, dy & 0xFFFFFFFF, 9))
    e.run(VA["t_hof_pairnn"], esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0x28
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
    got = bytes(uc.mem_read(DDATA, dW * dH))
    assert got == bytes(want)
    # the law's structural claims on the output: both strokes present on every device row they map to; the field at P
    P, hN = SL.mon_stripe(num)
    for srow in (11, 20):
        rows = [j for j in range(dh) if SL.nn_center_index(j, dh, sh) == srow]
        assert rows, srow
        for j in rows:
            yy = dy + j
            if 0 <= yy < dH:
                xx = dx + (5 * dw) // 6                 # source col ~50: on the strokes, outside the glyph block
                if 0 <= xx < dW:
                    assert got[yy * dW + xx] == 230, (srow, j)
    # a field column: every pair texel comes out as the brighter member (197) on the wide phase, 65 otherwise;
    # a texel without a chain on either side (a field row squeezed between two non-field features) stays NN
    xcol = dx + 2 * dw // 3
    if 0 <= xcol < dW:
        i = xcol - dx
        scol = SL.nn_center_index(i, dw, sw)
        for j in range(dh):
            yy = dy + j
            if 0 <= yy < dH:
                srow = SL.nn_center_index(j, dh, sh)
                a, mate = SL.hof_pair_texel(src, sw, scol, srow, 0, sh, 9)
                v = got[yy * dW + xcol]
                if a == 9:
                    assert v == 0xEE, (yy, v)
                elif mate is None:
                    assert v == a, (yy, v, a)
                elif {a, mate} == {65, 197}:
                    assert v == (197 if ((y0 + yy) % P) < hN else 65), (yy, v)
    # a sub-rect source (sx, sy offsets) agrees too
    uc.mem_write(DDATA, dst0)
    want = bytearray(dst0)
    SL.hof_pair_enlarge(src, sw, 7, 5, 30, 20, bytes(pal), num, want, dW, dW, dH, 10, 10, y0, 9)
    uc.mem_write(SP0, struct.pack("<11I", TRAP, SDATA, sw, 7, 5, 30, 20, DEST, 10, 10, 9))
    e.run(VA["t_hof_pairnn"])
    assert bytes(uc.mem_read(DDATA, dW * dH)) == bytes(want)


def test_pairnn_guards_bad_geometry():
    e = Emu()
    uc = e.uc
    w32(uc, C["g_hof_num"], 45)
    DDATA, DEST = PLANES + 0x20000, OBJ + 0x1000
    dst0 = bytes(0xEE for _ in range(100 * 50))
    uc.mem_write(DDATA, dst0)
    make_buffer(e, DEST, DDATA, 100, 50, 100)
    for args in ((0, 60, 0, 0, 60, 40), (PLANES, 0, 0, 0, 60, 40), (PLANES, 60, 0, 0, 0, 40), (PLANES, 60, 0, 0, 60, 0)):
        uc.mem_write(SP0, struct.pack("<11I", TRAP, *args, DEST, 0, 0, 9))
        e.run(VA["t_hof_pairnn"], esi=1)
        assert e.reg("esp") == SP0 + 4 + 0x28 and e.reg("esi") == 1
        assert bytes(uc.mem_read(DDATA, len(dst0))) == dst0


# ---- v7: the hof.pcx field pair (the CLOSE slot's channel rows) ---------------------------------------------------
def _channel_source():
    """60x48 hof.pcx-like art around the CLOSE slot: the 65/197 field on the pcx row parity, two 1-row red strokes
    with a 2-row channel between them and a 2-row channel to a 'button' field below (the slot), a 3-row channel, a
    lone field row squeezed between two strokes, a two-purple pair block next to field rows, scattered key texels."""
    sw, sh = 60, 48
    f0, f1 = SL.HOF_FIELD_PAIR
    src = bytearray((f1 if y % 2 else f0) for y in range(sh) for _x in range(sw))
    for x in range(3, 57):
        for y in (6, 9, 28, 29, 31, 32, 36, 40):    # strokes: 7-8 and 10.. channels, 30 lone, 33-35 3-row
            src[y * sw + x] = 109
    for y in range(14, 22):
        for x in range(24, 36):
            src[y * sw + x] = 226 if y % 2 == 0 else 224
    src[42 * sw + 10] = 233                          # a lone non-field texel inside the field
    for k in range(0, sw * sh, 89):
        src[k] = 9
    return src, sw, sh


def test_field_rule_law_claims():
    src, sw, sh = _channel_source()
    f0, f1 = SL.HOF_FIELD_PAIR
    for x in (5, 40):
        for y in (7, 8, 10, 33, 34, 35):            # every channel row is a member (the chain test alone misses 7/8)
            a, m = SL.hof_pair_texel(src, sw, x, y, 0, sh, 9, SL.HOF_FIELD_PAIR)
            assert m == f0 + f1 - a, (x, y)
        assert SL.hof_pair_texel(src, sw, x, 7, 0, sh, 9)[1] is None
        assert SL.hof_pair_texel(src, sw, x, 30, 0, sh, 9, SL.HOF_FIELD_PAIR)[1] is None   # lone row: NN
        assert SL.hof_pair_texel(src, sw, x, 29, 0, sh, 9, SL.HOF_FIELD_PAIR)[1] is None   # a stroke: NN
    assert SL.hof_pair_texel(src, sw, 10, 42, 0, sh, 9, SL.HOF_FIELD_PAIR)[1] is None
    # where the chain fires the field clause never changes the answer
    for y in range(sh):
        for x in range(sw):
            m0 = SL.hof_pair_texel(src, sw, x, y, 0, sh, 9)[1]
            if m0 is not None:
                assert SL.hof_pair_texel(src, sw, x, y, 0, sh, 9, SL.HOF_FIELD_PAIR)[1] == m0
    assert 9 not in SL.HOF_FIELD_PAIR and SL.HOF_BLACK_INDEX in SL.HOF_FIELD_PAIR


@pytest.mark.parametrize("num", tuple(range(17, 41)) + (45, 72))
def test_pairnn_field_rule_is_bit_exact_against_the_law(num):
    """t_hof_pairnn -> t_hof_pairfld with g_hof_field set = hof_pair_enlarge(field=HOF_FIELD_PAIR); cleared = field None.
    Every num 17..40 (odd and even, T = 1 and 2) + 45 / 72 (T = 2 / 4), every grid phase, a clipped origin and a sub-rect."""
    e = Emu()
    uc = e.uc
    w32(uc, C["g_hof_num"], num)
    pal = bytearray(rand_pal(5))
    for i, rgb in ((65, (0, 0, 0)), (197, (24, 18, 11)), (109, (12, 12, 136)), (226, (188, 124, 92)), (224, (212, 164, 120)), (233, (9, 9, 9))):
        pal[i * 4:i * 4 + 4] = bytes(rgb) + b"\0"
    src, sw, sh = _channel_source()
    dW, dH = 260, 230
    SDATA, DDATA, DEST = PLANES, PLANES + 0x20000, OBJ + 0x1000
    uc.mem_write(SDATA, bytes(src))
    dst0 = bytes(0xEE for _ in range(dW * dH))
    make_buffer(e, DEST, DDATA, dW, dH, dW, bytes(pal))
    P = SL.stripe_period(num)
    cases = [(5, 3, y0, 0, 0, sw, sh) for y0 in range(P)] + [(-4, -7, 1, 0, 0, sw, sh), (2, 2, 0, 3, 5, 40, 33)]
    for flag, field in ((1, SL.HOF_FIELD_PAIR), (0, None)):
        for dx, dy, y0, sx, sy, w, h in cases:
            w32(uc, VA["g_hof_field"], flag)
            w32(uc, DEST - 0x304, y0)
            uc.mem_write(DDATA, dst0)
            want = bytearray(dst0)
            SL.hof_pair_enlarge(src, sw, sx, sy, w, h, bytes(pal), num, want, dW, dW, dH, dx, dy, y0, 9, field)
            uc.mem_write(SP0, struct.pack("<11I", TRAP, SDATA, sw, sx, sy, w, h, DEST, dx & 0xFFFFFFFF, dy & 0xFFFFFFFF, 9))
            e.run(VA["t_hof_pairnn"], esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
            assert e.reg("esp") == SP0 + 4 + 0x28
            assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
            assert bytes(uc.mem_read(DDATA, dW * dH)) == bytes(want), (flag, dx, dy, y0, sx, sy)
    # the rule changed something: the channels came out on the grid with the flag, plain NN without
    w32(uc, VA["g_hof_field"], 1)
    a = bytearray(dst0)
    SL.hof_pair_enlarge(src, sw, 0, 0, sw, sh, bytes(pal), num, a, dW, dW, dH, 0, 0, 0, 9, SL.HOF_FIELD_PAIR)
    b = bytearray(dst0)
    SL.hof_pair_enlarge(src, sw, 0, 0, sw, sh, bytes(pal), num, b, dW, dW, dH, 0, 0, 0, 9)
    assert a != b


def test_pairfld_preserves_the_pairtex_contract_registers():
    """t_hof_pairfld is called with t_hof_pairnn's frame; ecx/edx/edi survive it on every path (chain hit, field hit, miss)."""
    src, sw, sh = _channel_source()
    e = Emu()
    uc = e.uc
    SDATA = PLANES
    uc.mem_write(SDATA, bytes(src))
    FR = SP0 - 0x8000                                # a fake t_hof_pairnn frame
    w32(uc, FR + 0xC, sw)
    w32(uc, FR + 0x14, 0)
    w32(uc, FR + 0x1C, sh)
    w32(uc, FR + 0x2C, 9)
    f0, f1 = SL.HOF_FIELD_PAIR
    for flag in (0, 1):
        w32(uc, VA["g_hof_field"], flag)
        for x, y in ((5, 7), (5, 8), (5, 2), (5, 30), (5, 29), (5, 33), (30, 16), (5, 0), (5, sh - 1)):
            w32(uc, FR - 0x34, y)
            a = src[y * sw + x]
            uc.mem_write(SP0, struct.pack("<I", TRAP))
            e.run(VA["t_hof_pairfld"], esi=SDATA + y * sw + x, ebx=a, ebp=FR, ecx=0x5151, edx=0x6161, edi=0x7171)
            got = e.reg("eax")
            got = -1 if got == 0xFFFFFFFF else got
            m = SL.hof_pair_texel(src, sw, x, y, 0, sh, 9, SL.HOF_FIELD_PAIR if flag else None)[1]
            assert got == (-1 if m is None else m), (flag, x, y)
            assert (e.reg("ecx"), e.reg("edx"), e.reg("edi"), e.reg("ebp"), e.reg("esp")) == (0x5151, 0x6161, 0x7171, FR, SP0 + 4)


@pytest.mark.parametrize("armed", (0, 1))
def test_backdrop_field_bracket_wraps_the_unchanged_backdrop(armed):
    """The hof.pcx site enters t_hof_bd_field: g_hof_field = 1 only for the duration of t_hof_bd_hof, the 7 args / ecx
    reach it unchanged, its eax comes back, RET 0x1C."""
    e = Emu()
    uc = e.uc
    _hof_arm(e, 1920 if armed else 1024, 1080 if armed else 768)
    REC3 = REC2 + 0x600
    e.stub(VA["t_hof_bd_hof"], f"mov dword ptr [{REC3:#x}], ecx\n"
           + f"mov eax, dword ptr [{VA['g_hof_field']:#x}]\nmov dword ptr [{REC3 + 4:#x}], eax\n"
           + "".join(f"mov eax, dword ptr [esp+{4 + 4 * k}]\nmov dword ptr [{REC3 + 8 + 4 * k:#x}], eax\n" for k in range(7))
           + f"inc dword ptr [{REC3 + 0x30:#x}]\nmov eax, 0x5A\nret 0x1C\n")
    uc.mem_write(SP0, struct.pack("<8I", TRAP, 11, 22, 33, 44, 55, 66, 77))
    e.run(VA["t_hof_bd_field"], ecx=0x777, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0x1C and e.reg("eax") == 0x5A
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
    assert r32(uc, REC3 + 0x30) == 1 and r32(uc, REC3) == 0x777 and r32(uc, REC3 + 4) == 1
    assert [r32(uc, REC3 + 8 + 4 * k) for k in range(7)] == [11, 22, 33, 44, 55, 66, 77]
    assert r32(uc, VA["g_hof_field"]) == 0


def test_hof_backdrop_site_enters_the_field_bracket_and_only_it_sets_the_flag():
    site = [s for s in SITES if s["id"] == "FameWin_draw.hof_backdrop"]
    assert len(site) == 1 and site[0]["new"] == "E8 {rel32:t_hof_bd_field}"
    assert "call    t_hof_bd_hof" in AM.asm_hof_bd_field()
    assert "call    t_hof_pairfld" in AM.asm_hof_pairnn() and "t_hof_pairtex" not in AM.asm_hof_pairnn()
    writers = [n for n, fn in AM.THUNKS if "g_hof_field" in fn()] + [n for n, _o, fn in AM.PLACED_THUNKS if "mov     dword ptr [g_hof_field]" in fn()]
    assert writers == ["t_hof_bd_field"]
    for n, o, _fn in AM.PLACED_THUNKS:
        off, b = LAYOUT[n]
        assert off == o and AM.OFF_BD_FIELD <= off and off + len(b) <= AM.OFF_HOF_FIELD
    assert AM.OFF_HOF_FIELD + 4 <= AM.OFF_PLACED_END == 0x1B000 and AM.OFF_BD_FIELD == 0x1AF00


@pytest.mark.parametrize("sw,sh", HRES[:3] + HRES[4:])
def test_frame_backdrop_resamples_to_the_letterbox(sw, sh):
    e = Emu()
    uc = e.uc
    num, lx, ly = _hof_arm(e, sw, sh)
    _rec_resample(e)
    SRC, DEST = OBJ, OBJ + 0x1000
    make_buffer(e, SRC, PLANES, 1024, 768, 1030)
    make_buffer(e, DEST, PLANES + 0x100000, sw, sh, sw)
    uc.mem_write(SP0, struct.pack("<8I", TRAP, DEST, 0, 0, 0, 0, 1024, 768))
    e.run(VA["t_hof_bd_frame"], ecx=SRC, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0x1C and e.reg("eax") == 0
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
    assert r32(uc, REC + 0x80) == 1
    assert [r32s(uc, REC + 4 * k) for k in range(11)] == [PLANES, 1030, 0, 0, 1024, 768, DEST, lx, ly, SL.mon_s(1024, num), SL.mon_s(768, num)]


@pytest.mark.parametrize("bw,bh", ((239, 119), (100, 50), (238, 118)))
def test_world_map_is_the_parity_nn_of_the_native_picture_at_the_device_origin(bw, bh):
    e = Emu()
    uc = e.uc
    num, lx, ly = _hof_arm(e, 3840, 2160)
    _rec_pairnn(e)
    SRC, DEST = OBJ, OBJ + 0x1000
    pitch = bw + 1
    make_buffer(e, SRC, PLANES, bw, bh, pitch)
    make_buffer(e, DEST, PLANES + 0x100000, 3840, 2160, 3840)
    # a runtime map dump with literal key texels: every 7th texel is 9 (inside AND outside the blit rect)
    src = bytearray((9 if (i % 7) == 0 else (i % 5) + 20) for i in range(pitch * (bh + 2)))
    uc.mem_write(PLANES, bytes(src))
    L, T, R, B = SL.hof_rects(num, lx, ly)[1]
    uc.mem_write(SP0, struct.pack("<8I", TRAP, DEST, 0, 0, L, T, R - L, B - T))
    e.run(VA["t_hof_bd_map"], ecx=SRC, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
    assert e.reg("esp") == SP0 + 4 + 0x1C and e.reg("eax") == 0
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
    mw, mh = SL.HOF_MAP_NATIVE
    sw, sh = min(mw, bw), min(mh, bh)
    assert r32(uc, REC2 + 0x30) == 1
    assert [r32s(uc, REC2 + 4 + 4 * k) for k in range(10)] == [PLANES, pitch, 0, 0, sw, sh, DEST, L, T, SL.HOF_BLIT_KEY]
    # the key texels inside the blit rect were remapped to black before the blit, the rest untouched (the law)
    want = bytearray(src)
    n = SL.hof_map_source_fix(want, pitch, 0, 0, sw, sh)
    assert n > 0 and bytes(uc.mem_read(PLANES, len(src))) == bytes(want)
    assert SL.HOF_BLIT_KEY not in bytes(uc.mem_read(PLANES, sh * pitch))[:sw] and 9 in src


@pytest.mark.parametrize("sw,sh", HRES[:3])
def test_hof_backdrop_is_the_parity_nn_over_a_sprite_view_under_the_num_bracket(sw, sh):
    e = Emu()
    uc = e.uc
    num, lx, ly = _hof_arm(e, sw, sh)
    _rec_pairnn(e)
    SRC, DEST = OBJ, OBJ + 0x1000
    make_buffer(e, SRC, PLANES, 800, 600, 804)
    make_buffer(e, DEST, PLANES + 0x100000, sw, sh, sw)
    L, T, _r, _b = SL.hof_content_rect(num, lx, ly)
    for sx, sy in ((0, 0), (3, 2)):
        uc.mem_write(REC2, bytes(0x80))
        uc.mem_write(SP0, struct.pack("<8I", TRAP, DEST, sx, sy, L, T, 800, 600))
        e.run(VA["t_hof_bd_hof"], ecx=SRC, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44)
        assert e.reg("esp") == SP0 + 4 + 0x1C and e.reg("eax") == 0
        assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp")) == (0x11, 0x22, 0x33, 0x44)
        assert r32(uc, REC2 + 0x30) == 1
        assert [r32s(uc, REC2 + 4 + 4 * k) for k in range(10)] == [PLANES, 804, sx, sy, 800, 600, DEST, L, T, SL.HOF_BLIT_KEY]


@pytest.mark.parametrize("sw,sh", HRES[:3])
def test_faction_picture_is_the_parity_nn_with_the_engine_args_at_num(sw, sh):
    e = Emu()
    uc = e.uc
    num, lx, ly = _hof_arm(e, sw, sh)
    _rec_parity_nn(e)
    SPR, DEST = OBJ, OBJ + 0x1000
    uc.mem_write(SPR, bytes(0x40))
    w32(uc, SPR + 4, PLANES)
    w32(uc, SPR + 0xC, 240)
    w32(uc, SPR + 0x10, 233)
    w32(uc, SPR + 0x14, 124)
    make_buffer(e, DEST, PLANES + 0x100000, sw, sh, sw)
    w32(uc, AM.G_POPUP, 40)
    x, y = 1000, 700
    uc.mem_write(SP0, struct.pack("<5I", TRAP, DEST, 9, x, y))
    e.run(VA["t_hof_spr_pic"], ecx=SPR, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44, edx=0x55)
    assert e.reg("esp") == SP0 + 4 + 0x10 and e.reg("eax") == 0x77
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp"), e.reg("edx")) == (0x11, 0x22, 0x33, 0x44, 0x55)
    assert r32(uc, REC2 + 0x24) == 1 and r32(uc, REC2) == SPR
    assert [r32s(uc, REC2 + 4 + 4 * k) for k in range(6)] == [DEST, 9, x, y, num, 16]
    assert r32(uc, REC2 + 0x20) == num and r32(uc, AM.G_POPUP) == 40


@pytest.mark.parametrize("thunk,retn", (("t_hof_bd_frame", 0x1C), ("t_hof_bd_hof", 0x1C), ("t_hof_bd_map", 0x1C), ("t_hof_spr_pic", 0x10)))
def test_wrappers_are_the_native_path_when_unarmed(thunk, retn):
    e = Emu()
    uc = e.uc
    _hof_arm(e, 1024, 768)
    assert r32(uc, C["g_hof_armed"]) == 0
    native = AM.BLIT_CORE if thunk == "t_hof_spr_pic" else AM.COPY4
    e.stub(native, "hlt\n")
    uc.mem_write(SP0, struct.pack("<8I", TRAP, 1, 2, 3, 4, 5, 6, 7))
    e.run(VA[thunk], until=native + 1, ecx=0x777, esi=0x11)
    assert e.reg("esp") == SP0 and e.reg("ecx") == 0x777 and e.reg("esi") == 0x11


# ---- the face chain head ---------------------------------------------------------------------------------------------
def _seed_face(e, sw, sh):
    num, lx, ly = _hof_arm(e, sw, sh)
    _rec_pairnn(e)
    e.stub(AM.T_RW_ICONBLIT, "hlt\n")
    w32(e.uc, AM.G_POPUP, 40)
    SPR = OBJ + 0x3000
    e.uc.mem_write(SPR, bytes(0x40))
    w32(e.uc, SPR + 4, PLANES)
    w32(e.uc, SPR + 0xC, 0)            # pitch 0 -> the width
    w32(e.uc, SPR + 0x10, 79)
    w32(e.uc, SPR + 0x14, 79)
    w32(e.uc, SPR + 0x18, 79)
    w32(e.uc, SPR + 0x1C, 79)
    return num, SPR


@pytest.mark.parametrize("sw,sh", HRES[:3])
@pytest.mark.parametrize("which", (0, 5, 6, 12))
def test_face_hit_recentres_and_draws_the_parity_nn_at_num(sw, sh, which):
    e = Emu()
    uc = e.uc
    num, SPR = _seed_face(e, sw, sh)
    btn = (AM.HOF_CAT0 + which * 0xB4C) if which < 6 else (AM.HOF_FAC0 + (which - 6) * 0xB4C)
    cell = 0x4F if which < 6 else 0x46
    for off in (0x10, 0x14, 0x18, 0x1C):
        w32(uc, SPR + off, cell)
    size = SL.hof_button_size(cell, num)
    canvas = btn + 0x444
    uc.mem_write(btn, bytes(0xB4C))
    w32(uc, canvas + 0x80, size + 6)
    w32(uc, canvas + 0x84, (-(size + 6)) & 0xFFFFFFFF)
    x0, y0 = (size + 6 - size) // 2, (size + 6 - size) // 2
    x_eng, y_eng = (size + 6 - cell) // 2, (size + 6 - cell) // 2       # what the engine pushed (native centring)
    uc.mem_write(SP0, struct.pack("<7I", TRAP, canvas, 9, x_eng, y_eng, 1, 1))
    e.run(VA["t_hof_face"], ecx=SPR, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44, edx=0x55)
    assert e.reg("esp") == SP0 + 4 + 0x18 and e.reg("eax") == 0x77
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp"), e.reg("edx")) == (0x11, 0x22, 0x33, 0x44, 0x55)
    assert r32(uc, REC2 + 0x30) == 1
    assert [r32s(uc, REC2 + 4 + 4 * k) for k in range(10)] == [PLANES, cell, 0, 0, cell, cell, canvas, x0, y0, 9]
    assert (x0, y0) == SL.hof_face_origin(size + 6, -(size + 6), cell, cell, num)
    assert r32(uc, AM.G_POPUP) == 40            # no popup-g bracket any more: the pair law reads g_hof_num


@pytest.mark.parametrize("case", ("unarmed", "scaled_already", "not_a_canvas", "past_the_row", "between_buttons"))
def test_face_misses_chain_to_the_report_head_untouched(case):
    e = Emu()
    uc = e.uc
    num, SPR = _seed_face(e, 3840, 2160)
    dest = AM.HOF_CAT0 + 0x444
    n, d = 1, 1
    if case == "unarmed":
        w32(uc, C["g_hof_armed"], 0)
    elif case == "scaled_already":
        n, d = 40, 16
    elif case == "not_a_canvas":
        dest = OBJ
    elif case == "past_the_row":
        dest = AM.HOF_FAC0 + 7 * 0xB4C + 0x444
    elif case == "between_buttons":
        dest = AM.HOF_CAT0 + 0x444 + 4
    args = struct.pack("<7I", TRAP, dest, 9, 3, 4, n, d)
    uc.mem_write(SP0, args)
    e.run(VA["t_hof_face"], until=AM.T_RW_ICONBLIT + 1, ecx=SPR, esi=0x11, edi=0x22, ebx=0x33, ebp=0x44, edx=0x55)
    assert e.reg("esp") == SP0 and e.reg("ecx") == SPR
    assert (e.reg("esi"), e.reg("edi"), e.reg("ebx"), e.reg("ebp"), e.reg("edx")) == (0x11, 0x22, 0x33, 0x44, 0x55)
    assert bytes(uc.mem_read(SP0, len(args))) == args
    assert r32(uc, REC2 + 0x30) == 0 and r32(uc, AM.G_POPUP) == 40


# ---- gate + restripe extensions --------------------------------------------------------------------------------------
def test_gate_admits_the_hof_close_only_when_the_hof_is_armed():
    e = Emu()
    uc = e.uc
    e.stub(AM.GATE_PRE, "hlt\n")
    for mon, hof, esi, admit in ((0, 1, AM.HOF_CLOSE, True), (0, 0, AM.HOF_CLOSE, False), (1, 0, AM.HOF_CLOSE, False),
                                 (1, 0, AM.BTN_CLOSE, True), (0, 1, AM.BTN_CLOSE, False), (1, 1, AM.BTN_BACK, True), (1, 1, OBJ, False)):
        w32(uc, C["g_mon_armed"], mon)
        w32(uc, C["g_hof_armed"], hof)
        uc.mem_write(SP0, struct.pack("<I", TRAP))
        e.run(VA["t_mon_gate"], until=(TRAP if admit else AM.GATE_PRE + 1), esi=esi, eax=0)
        if admit:
            assert e.reg("eax") == 1 and e.reg("esp") == SP0 + 4
        else:
            assert e.reg("esp") == SP0 and e.reg("esi") == esi


@pytest.mark.parametrize("num", (22, 25, 45))
def test_restripe_handles_the_hof_close_canvas_with_the_hof_num(num):
    e = Emu()
    uc = e.uc
    pal = bytearray(rand_pal(2))
    pal[201 * 4:201 * 4 + 4] = bytes((6, 8, 32, 0))
    pal[109 * 4:109 * 4 + 4] = bytes((12, 12, 136, 0))
    bw, bh = SL.mon_s(0xCE, num), SL.mon_s(0x16, num)
    buf = _face("nn", bw, bh, num, pal)
    want = bytearray(buf)
    assert SL.mon_face_restripe(want, bw, bw, bh, bytes(pal), num) is not None and want != buf
    DDATA, CANVAS = PLANES, AM.HOF_CLOSE + 0x444
    uc.mem_write(DDATA, bytes(buf))
    make_buffer(e, CANVAS, DDATA, bw, bh, bw, bytes(pal))
    w32(uc, C["g_hof_num"], num)
    w32(uc, C["g_hof_armed"], 1)
    w32(uc, C["g_mon_num"], 99)                     # the Monument's cell must not matter
    w32(uc, C["g_mon_armed"], 0)
    e.stub(AM.BUFFER_DRAW2_RESUME, f"mov dword ptr [{REC:#x}], esp\nmov dword ptr [{REC + 4:#x}], ecx\nhlt\n")
    uc.mem_write(SP0 - 0x20, bytes(0x20))
    e.run(VA["t_mon_restripe"], until=AM.BUFFER_DRAW2_RESUME + 12, ecx=CANVAS, eax=1, ebx=2, edx=3, esi=4, edi=5, ebp=6)
    assert r32(uc, REC) == SP0 - 0x18 - 8 and r32(uc, REC + 4) == CANVAS
    assert (e.reg("eax"), e.reg("ebx"), e.reg("edx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (1, 2, 3, 4, 5, 6)
    assert bytes(uc.mem_read(DDATA, len(buf))) == bytes(want)
    # unarmed HOF: untouched
    uc.mem_write(DDATA, bytes(buf))
    w32(uc, C["g_hof_armed"], 0)
    e.run(VA["t_mon_restripe"], until=AM.BUFFER_DRAW2_RESUME + 12, ecx=CANVAS)
    assert bytes(uc.mem_read(DDATA, len(buf))) == bytes(buf)


# ---- font detours ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("va,ln,reg,ti", AM.HOF_FONT_SITES)
@pytest.mark.parametrize("armed", (0, 1))
def test_font_detours_swap_the_painter_fonts_when_armed(va, ln, reg, ti, armed):
    e = Emu()
    uc = e.uc
    tab = AM.HOF_FONT_TABLES[ti]
    cell = AM.HOF_FONT_CELLS[ti]
    w32(uc, tab, 0x8888)
    w32(uc, C[cell], 0x9999)
    w32(uc, C["g_hof_armed"], armed)
    resume = va + ln
    e.stub(resume, f"mov dword ptr [{REC + 4:#x}], eax\nmov dword ptr [{REC + 8:#x}], ecx\npushfd\npop eax\nmov dword ptr [{REC:#x}], eax\nhlt\n")
    regs = {"ecx": 0x11, "edx": 0x22, "esi": 0x33, "ebx": 0x44, "edi": 0x55, "eax": 0x66}
    for flags in (0x202, 0x2C7):                     # a neutral and a busy EFLAGS: both must survive
        uc.reg_write(REG_EFLAGS, flags)
        uc.mem_write(SP0 - 0x20, bytes(0x20))
        e.run(VA[f"t_hof_font_{va:x}"], until=resume + 6, **regs)
        got = {"eax": r32(uc, REC + 4), "ecx": r32(uc, REC + 8)}
        assert got[reg] == (0x9999 if armed else 0x8888)
        for r, v in regs.items():
            if r == reg:
                continue
            assert (got[r] if r in got else e.reg(r)) == v, r
        assert (r32(uc, REC) & 0x8D5) == (flags & 0x8D5)          # CF PF AF ZF SF OF DF intact
        assert e.reg("esp") == SP0                                # pushfd/popfd balanced (the resume stub's own push/pop cancel)
    # the detoured bytes are exactly `mov reg, [table]`
    orig = SE.base_exe_bytes(va, ln)
    ins = list(_cs.disasm(orig, va))
    assert len(ins) == 1 and ins[0].mnemonic == "mov" and ins[0].op_str == f"{reg}, dword ptr [{tab:#x}]"


from unicorn.x86_const import UC_X86_REG_EFLAGS as REG_EFLAGS  # noqa: E402
