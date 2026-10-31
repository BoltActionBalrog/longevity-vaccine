"""Unicorn parity for the ntw_scale thunks (assemble_ntw.py) against scaling_laws.ntw_*.

  * the PRISTINE builder prefix 0x483F90..0x4842E7 (pure rect arithmetic) is emulated and must equal
    ntw_layout(16)  -> the law's g=16 identity is vanilla's own bytes, not a transcription;
  * t_ntw_rects at every g in 16..40 must equal ntw_layout(g) over all 17 rect fields;
  * every call-site wrapper is run to its tail target and its stack args / rect copy compared.
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("unicorn")
pytest.importorskip("keystone")
pefile = pytest.importorskip("pefile")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDX,  # noqa: E402
                               UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

if not pathlib.Path(config.terranx_bak()).exists():
    pytest.skip("pristine .bak not present", allow_module_level=True)
import assemble_ntw as A  # noqa: E402
import wheel_stc_stub  # noqa: E402

GS = list(range(16, 41))
THIS = 0x3000000
STACK, SP0 = 0x2500000, 0x2508000
TRAP = 0x2600000
BUFOBJ, BUFDATA, BW, BH, BPITCH = 0x2700000, 0x2800000, 1400, 1500, 1400
VTBL = 0x2710000


def mk(g: int) -> Uc:
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(A.PCAVE2, 0x38000)                                # the whole pcave2 (t_btn_edgeband is at 0x37140)
    uc.mem_map(0x400000, 0x26A000)                               # .text .. g_popup_scale_num page (stop targets must be fetchable)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(TRAP, 0x1000)
    uc.mem_map(THIS, 0x4000)
    uc.mem_map(BUFOBJ, 0x20000)
    uc.mem_map(BUFDATA, 0x210000)
    uc.mem_write(A.G, struct.pack("<I", g))
    uc.mem_write(TRAP, b"\xf4" * 16)
    for name, (off, b) in A.OUT.items():
        uc.mem_write(A.PCAVE2 + off, b)
    return uc


def run(uc: Uc, start: int, stops, regs=None, stack=(), count=400000):
    """run from start with [esp] = TRAP + stack args until eip hits one of stops (or TRAP)."""
    sp = SP0
    uc.mem_write(sp, struct.pack(f"<{1 + len(stack)}I", TRAP, *[v & 0xFFFFFFFF for v in stack]))
    uc.reg_write(UC_X86_REG_ESP, sp)
    for r, v in (regs or {}).items():
        uc.reg_write(r, v & 0xFFFFFFFF)
    stops = set(stops) | {TRAP}
    hit = {}

    def hook(u, addr, size, _):
        if addr in stops:
            hit["at"] = addr
            u.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(start, 0, count=count)
    finally:
        uc.hook_del(h)
    return hit.get("at")


def rd(uc: Uc, va: int, n: int = 1):
    v = struct.unpack(f"<{n}i", bytes(uc.mem_read(va, 4 * n)))
    return v if n > 1 else v[0]


def fields(uc: Uc):
    return {name: rd(uc, THIS + off, 4) for name, off in SL.NTW_RECT_FIELDS}


# ---- vanilla identity ------------------------------------------------------------------------------
def test_scaling_pristine_builder_prefix_is_the_g16_law():
    uc = mk(16)
    uc.mem_write(0x483F90, A.orig(0x483F90, 0x4842E7 - 0x483F90))
    at = run(uc, 0x483F90, {0x4842E7}, regs={UC_X86_REG_ECX: THIS}, stack=(0x58, 0))
    assert at == 0x4842E7
    assert fields(uc) == SL.ntw_layout(16)
    assert rd(uc, THIS + 0xB24, 2) == (0x58, 0)


def test_scaling_g16_layout_is_the_decompiled_vanilla():
    lay = SL.ntw_layout(16)
    assert lay["win"] == (0, 0, 550, 600) and lay["content"] == (12, 12, 538, 558)
    assert lay["ok"] == (15, 565, 535, 585) and lay["quote_text"][2] == lay["btn1"][0] - 4
    assert lay["btn1"] == (473, 518, 501, 552) and lay["btn2"] == (504, 518, 532, 552)


# ---- the cascade -------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_scaling_rects_match_the_law(g):
    uc = mk(g)
    uc.mem_write(THIS, b"\xCC" * 0x4000)
    regs = {UC_X86_REG_ESI: THIS, UC_X86_REG_EBP: 0x11223344, UC_X86_REG_ECX: 0x55667788}
    assert run(uc, A.VA["t_ntw_rects"], (), regs=regs) == TRAP
    assert fields(uc) == SL.ntw_layout(g)
    assert uc.reg_read(UC_X86_REG_EBP) == 0x11223344 and uc.reg_read(UC_X86_REG_ECX) == 0x55667788
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4
    # nothing outside the 17 rects is written
    blob = bytes(uc.mem_read(THIS, 0x4000))
    assert set(blob[:0xA14]) == {0xCC} and set(blob[0xB24:]) == {0xCC}


@pytest.mark.parametrize("g", GS)
def test_scaling_layout_properties(g):
    lay = SL.ntw_layout(g)
    s = lambda v: SL.scale_px(v, g)   # noqa: E731
    p = s(3)
    assert lay["win"] == (0, 0, s(550), s(600))
    order = ["header", "icon", "cap_tl", "list_tl", "cap_bl", "list_bl", "quote"]
    for a, b in zip(order, order[1:]):
        assert lay[b][1] - lay[a][3] == p                        # ONE frame pitch between every stacked panel
    for l, r in (("cap_tl", "cap_tr"), ("list_tl", "list_tr"), ("cap_bl", "cap_br"), ("list_bl", "list_br")):
        assert lay[r][0] - lay[l][2] == p and lay[l][1::2] == lay[r][1::2]
        assert abs((lay[l][2] - lay[l][0]) - (lay[r][2] - lay[r][0])) <= 1
    for name, hh in (("header", 0x17), ("icon", 0xD9), ("cap_tl", 0x14), ("list_tl", 0x4C), ("list_br", 0x4C)):
        assert lay[name][3] - lay[name][1] == s(hh)              # every panel is vanilla x g/16
    q = lay["quote"]
    assert abs((q[3] - q[1]) - 90 * g / 16) <= 8                 # the remainder cell stays proportionate
    assert lay["content"][3] - q[3] == p and lay["win"][3] - lay["ok"][3] == s(12) + p
    for b in ("btn1", "btn2"):
        w, h = lay[b][2] - lay[b][0], lay[b][3] - lay[b][1]
        assert (SL.btn_native_dim(w, g), SL.btn_native_dim(h, g)) == SL.NTW_ICONBTN   # fixed art survives the 2D zoom's ceil inverse
        assert q[0] < lay[b][0] and lay[b][2] < q[2] and q[1] < lay[b][1] and lay[b][3] < q[3]
    assert SL.btn_native_dim(lay["ok"][3] - lay["ok"][1], g) == SL.NTW_OK_H


# ---- call-site wrappers --------------------------------------------------------------------------------
@pytest.mark.parametrize("g", GS)
def test_scaling_build_arms_only_above_native(g):
    uc = mk(g)
    at = run(uc, A.VA["t_ntw_build"], {A.GW_INIT2}, regs={UC_X86_REG_ESI: THIS, UC_X86_REG_ECX: THIS}, stack=(THIS + 0xA14,))
    assert at == A.GW_INIT2 and uc.reg_read(UC_X86_REG_ESP) == SP0 and rd(uc, SP0 + 4) == THIS + 0xA14
    assert rd(uc, A.ARMED) == rd(uc, A.G_NETWIN) == (1 if g > 16 else 0)
    if g > 16:
        assert fields(uc) == SL.ntw_layout(g)
    else:
        assert fields(uc)["win"] == (0, 0, 0, 0)                 # untouched: vanilla's own values stand


@pytest.mark.parametrize("g", GS)
def test_scaling_caption_size_and_textscroll_insets(g):
    uc = mk(g)
    uc.mem_write(THIS + 0x16C, struct.pack("<i", SL.NTW_CAPTION_SIZE))
    assert run(uc, A.VA["t_ntw_capsz"], {A.WIN_CENTER}, regs={UC_X86_REG_ECX: THIS}) == A.WIN_CENTER
    assert rd(uc, THIS + 0x16C) == SL.ntw_caption_size(g)
    for n in (SL.NTW_LIST_TS_INSET, SL.NTW_QUOTE_TS_INSET):
        uc = mk(g)
        args = (100 + n, 200 + n, 300 - 2 * n, 120 - 2 * n, THIS, 0, -1)
        assert run(uc, A.VA[f"t_ntw_ts{n}"], {A.TS_ATTACH}, stack=args) == A.TS_ATTACH
        d = SL.ntw_ts_inset_delta(n, g)
        got = rd(uc, SP0 + 4, 7)
        assert got[:4] == (100 + n + d, 200 + n + d, 300 - 2 * (n + d), 120 - 2 * (n + d)) and got[4:] == (THIS, 0, -1)
        assert (got[0], got[1]) == (100 + SL.scale_px(n, g), 200 + SL.scale_px(n, g))


@pytest.mark.parametrize("g", GS)
def test_scaling_frame_wrappers(g):
    rect = (37, 101, 1338, 643)
    for name, tgt, fix in (("t_ntw_bm", A.HOLLOWFLAT, (0, 0, -1, -1)), ("t_ntw_bmdf", A.DEVFILL, (0, 0, -1, -1))):
        uc = mk(g)
        uc.mem_write(THIS, struct.pack("<4i", *rect))
        at = run(uc, A.VA[name], {tgt, A.BOX_SPRITE}, regs={UC_X86_REG_ECX: 0xC0FFEE}, stack=(THIS, 0x78D528))
        assert uc.reg_read(UC_X86_REG_ECX) == 0xC0FFEE and uc.reg_read(UC_X86_REG_ESP) == SP0
        assert rd(uc, THIS, 4) == rect                           # the engine's rect is never modified
        if g <= 16:
            assert at == A.BOX_SPRITE and rd(uc, SP0 + 4) == THIS
        else:
            assert at == tgt and rd(uc, SP0 + 4) == A.RECT and rd(uc, SP0 + 8) == 0x78D528
            assert rd(uc, A.RECT, 4) == SL.bandmap_rect_from_halfopen(*rect, g) == tuple(a + b for a, b in zip(rect, fix))
    # OK ring: painter hands OK -/+ native 3
    lay = SL.ntw_layout(g)
    ok = lay["ok"]
    uc = mk(g)
    uc.mem_write(THIS, struct.pack("<4i", ok[0] - 3, ok[1] - 3, ok[2] + 3, ok[3] + 3))
    at = run(uc, A.VA["t_ntw_ring"], {A.HOLLOWFLAT, A.BOX_SPRITE}, regs={UC_X86_REG_ECX: 0xC0FFEE}, stack=(THIS, 0x78D5A0))
    assert uc.reg_read(UC_X86_REG_ECX) == 0xC0FFEE and uc.reg_read(UC_X86_REG_ESP) == SP0
    if g <= 16:
        assert at == A.BOX_SPRITE and rd(uc, SP0 + 4) == THIS
    else:
        p = SL.scale_px(SL.NTW_PAD, g)
        ring = (ok[0] - p, ok[1] - p, ok[2] + p, ok[3] + p)
        assert at == A.HOLLOWFLAT and rd(uc, A.RECT, 4) == SL.bandmap_rect_from_halfopen(*ring, g)
        assert ring[0] == lay["content"][0] and ring[2] == lay["content"][2]      # ring flush with the content frame's columns
        assert ring[3] == lay["win"][3] - SL.scale_px(SL.NTW_OUTER, g)
        assert ring[1] - lay["content"][3] == SL.scale_px(SL.NTW_OK_GAP, g)


@pytest.mark.parametrize("g", GS)
def test_scaling_text_wrappers(g):
    rect = (37, 650, 684, 700)
    d = SL.ntw_pad_delta(g)
    for name, want in (("t_ntw_title", (rect[0] + d, rect[1] + d, rect[2] - d, rect[3] + d)),):
        uc = mk(g)
        uc.mem_write(THIS, struct.pack("<4i", *rect))
        at = run(uc, A.VA[name], {A.CENT7}, regs={UC_X86_REG_ECX: 0xC0FFEE}, stack=(0x9B86A0, THIS, 22))
        assert at == A.CENT7 and uc.reg_read(UC_X86_REG_ECX) == 0xC0FFEE and uc.reg_read(UC_X86_REG_ESP) == SP0
        assert rd(uc, SP0 + 4) == 0x9B86A0 and rd(uc, SP0 + 12) == 22 and rd(uc, THIS, 4) == rect
        if g <= 16:
            assert rd(uc, SP0 + 8) == THIS
        else:
            assert rd(uc, SP0 + 8) == A.RECT and rd(uc, A.RECT, 4) == want
    assert SL.NTW_CAPTION_NUDGE == 0 and "t_ntw_cap" not in A.VA          # measured: captions take no nudge
    assert not [s for s in A.SITES if s[4] == A.CENT7 and s[5] != "t_ntw_title"]


@pytest.mark.parametrize("g", GS)
def test_scaling_icon(g):
    lay = SL.ntw_layout(g)
    l, t, r, b = lay["icon"]
    line_h = 46 * g // 16
    top_native, col = t + 3 + line_h, 0x5C
    h_native = (b - 3) - top_native
    uc = mk(g)
    uc.mem_write(A.MONO_FN, b"\xC2\x1C\x00")
    uc.mem_write(BUFOBJ + 0x54, struct.pack("<I", BUFDATA))
    uc.mem_write(BUFOBJ + 0x80, struct.pack("<2i", BW, -BH))
    uc.mem_write(BUFOBJ + 0x4A8, struct.pack("<i", BPITCH))
    uc.mem_write(BUFDATA, b"\x0F" * (BPITCH * BH))               # worst case: EVERYTHING is idx 0x0F
    frame = SP0 + 0x400
    uc.mem_write(frame - 0x18, struct.pack("<6i", l, top_native, r, 0, r - l, h_native))   # -0x18 L, -0x14 top, -0x10 R, -8 w, -4 h
    seen = {}

    def hook(u, addr, size, _):
        if addr == A.MONO_FN:
            sp = u.reg_read(UC_X86_REG_ESP)
            seen["args"] = struct.unpack("<8i", bytes(u.mem_read(sp, 32)))[1:]
            seen["ecx"] = u.reg_read(UC_X86_REG_ECX)

    uc.hook_add(UC_HOOK_CODE, hook)
    x0 = (r - l - 160) // 2 + l
    y0 = (h_native - 160) // 2 + top_native
    at = run(uc, A.VA["t_ntw_icon"], (), regs={UC_X86_REG_ECX: 0x759E28, UC_X86_REG_EBP: frame, UC_X86_REG_EAX: 0},
             stack=(BUFOBJ, 9, x0, y0, col, SL.NTW_ICON_BOX, SL.NTW_ICON_DEN), count=30_000_000)
    assert at == TRAP and uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0x1C and seen["ecx"] == 0x759E28
    x, y, num = SL.ntw_icon(g, l, r, top_native, h_native)
    if g <= 16:
        assert seen["args"] == (BUFOBJ, 9, x0, y0, col, 160, 215) and (x, y, num) == (x0, y0, 160)
        assert bytes(uc.mem_read(BUFDATA, BPITCH * BH)).count(col) == 0
        return
    assert seen["args"] == (BUFOBJ, 9, x, y, col, num, SL.NTW_ICON_DEN) and num == 10 * g
    p = SL.scale_px(SL.NTW_PAD, g)
    assert l < x and x + num <= r and top_native + (p - 3) <= y and y + num <= b - p      # the box sits inside the icon area
    assert num * 4 > SL.NTW_ICON_DEN * 0 and num < 4 * SL.NTW_ICON_DEN                     # never the >4x rejected blit
    rows = bytes(uc.mem_read(BUFDATA, BPITCH * BH))
    y_lo, y_hi = top_native + (p - 3), b - p
    for yy in (0, t, y_lo - 1, y_lo, y, y_hi - 1, y_hi, BH - 1):
        row = rows[yy * BPITCH: yy * BPITCH + BW]
        inside = y_lo <= yy < y_hi
        assert set(row[l:r]) == ({col} if inside else {0x0F}), yy
        assert set(row[:l]) == {0x0F} and set(row[r:]) == {0x0F}                          # never outside the panel columns


@pytest.mark.parametrize("g", (16, 17, 25, 40))
def test_scaling_title_font_and_gate_and_modal(g):
    uc = mk(g)
    at = run(uc, A.VA["t_ntw_tfont"], {A.T_FFN_AT, A.FIND_FONT}, stack=(40, 0))
    if g <= 16:
        assert at == A.FIND_FONT and rd(uc, SP0 + 4, 2) == (40, 0)
    else:
        sp = uc.reg_read(UC_X86_REG_ESP)
        assert at == A.T_FFN_AT and struct.unpack("<4I", bytes(uc.mem_read(sp + 4, 16))) == (A.TFONT, 40, 0, g)
        assert SL.font_face_law_font(40, 0, g)[1] == 40 * g // 16
    # gate: the three statics admit only while armed, everything else chains
    for armed in (0, 1):
        for esi, mine in ((A.BTN_OK, True), (A.BTN_1, True), (A.BTN_2, True), (A.BTN_OK + 4, False), (0x7F9F58 + 0xA58, False)):
            uc = mk(g)
            uc.mem_write(A.ARMED, struct.pack("<I", armed))
            at = run(uc, A.VA["t_ntw_gate"], {A.T_MON_GATE}, regs={UC_X86_REG_ESI: esi, UC_X86_REG_EAX: 0})
            if armed and mine:
                assert at == TRAP and uc.reg_read(UC_X86_REG_EAX) == 1
            else:
                assert at == A.T_MON_GATE and uc.reg_read(UC_X86_REG_ESP) == SP0
    # modal: armed while the engine's modal runs, clear after, args + result intact, RET 0xC
    uc = mk(g)
    modal = VTBL + 0x800
    uc.mem_write(VTBL + 0xE4, struct.pack("<I", modal))
    uc.mem_write(modal, bytes.fromhex("B8 78 56 34 12 C2 0C 00".replace(" ", "")))       # mov eax,0x12345678 ; ret 0xC
    seen = {}

    def hook(u, addr, size, _):
        if addr == modal:
            sp = u.reg_read(UC_X86_REG_ESP)
            seen["args"] = struct.unpack("<3i", bytes(u.mem_read(sp + 4, 12)))
            seen["flags"] = (rd(u, A.ARMED), rd(u, A.G_NETWIN))
            seen["ecx"] = u.reg_read(UC_X86_REG_ECX)

    uc.hook_add(UC_HOOK_CODE, hook)
    at = run(uc, A.VA["t_ntw_modal"], (), regs={UC_X86_REG_ECX: THIS, UC_X86_REG_EDX: VTBL}, stack=(1, 0, 0))
    assert at == TRAP and uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0xC
    assert seen["args"] == (1, 0, 0) and seen["ecx"] == THIS and uc.reg_read(UC_X86_REG_EAX) == 0x12345678
    assert seen["flags"] == ((1, 1) if g > 16 else (0, 0))
    assert (rd(uc, A.ARMED), rd(uc, A.G_NETWIN)) == (0, 0)


# ---- bake integrity ------------------------------------------------------------------------------------
def test_scaling_block_fits_and_sites_are_pristine_calls():
    end = max(o + len(b) for o, b in A.OUT.values())
    assert A.CODE_OFF <= min(o for o, _ in A.OUT.values()) and end <= A.LIMIT_OFF
    assert max(A.CELL.values()) + 0x30 <= A.PCAVE2 + A.CODE_OFF
    assert len({s[2] for s in A.SITES}) == len(A.SITES) == 30
    for sid, _fn, va, ln, callee, tgt, _note in A.SITES:
        assert tgt in A.VA or tgt in A.REUSED, sid


def test_scaling_yaml_carries_these_exact_bytes():
    import apply_patches as ap
    y = ROOT / "patches" / "patches.yaml"
    if "ntw_scale" not in y.read_text(encoding="utf-8"):
        pytest.skip("ntw_scale not spliced yet")
    sites, groups, caves, symbols = ap.load_patches(y)
    symtab = dict(ap.build_symbol_table(symbols, caves))
    shipped = {e["id"]: " ".join(str(e["bytes"]).split()) for c in caves for e in (c.get("contents") or [])}
    for name, (off, b) in A.OUT.items():
        assert symtab[name] == A.PCAVE2 + off, name
        assert ap.ByteTemplate(A.templ(name)).resolve(A.PCAVE2 + off, symtab) == b, name
        # the SHIPPED bytes, not the template against itself: a hand edit of the yaml that this source of truth does
        # not carry (or a --splice that would undo one) fails here (2026-10-25 W2D audit: t_ntw_nostripe's tail)
        assert shipped[name] == A.templ(name), name
    for name, va in A.REUSED.items():
        assert symtab[name] == va, name                          # a moved shared thunk would silently retarget ours
    for name, va in A.CELL.items():
        assert symtab[name] == va, name


# ---- --splice: byte-exact on current master, idempotent, chain-aware ------------------------------------------------
@pytest.fixture(scope="module")
def shipped_yaml() -> bytes:
    return (ROOT / "patches" / "patches.yaml").read_bytes()


def _eol(data: bytes, eol: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\n", eol)


@pytest.mark.parametrize("eol", (b"\r\n", b"\n"), ids=("crlf", "lf"))
def test_splice_of_the_shipped_yaml_is_a_byte_exact_noop(shipped_yaml, eol):
    """`--splice` on current master: the four blocks are exactly what this script emits (hand edits of the yaml are
    ported back here), and every retargeted call site is already ntw's -- directly, or behind a later group's chain
    head (diplowin's t_dw_gate in front of t_ntw_gate; t_dw_wheel_* -> t_bw_wheel_* -> t_ntw_wheel_*)."""
    data = _eol(shipped_yaml, eol)
    assert A.splice(data) == data


def test_splice_round_trips_emptied_blocks(shipped_yaml):
    """Every block emptied (stale or hand-damaged content between the markers) -> the splice restores the shipped
    yaml byte for byte, and a second splice changes nothing."""
    nl = b"\r\n" if b"\r\n" in shipped_yaml[:4096] else b"\n"
    data = shipped_yaml
    for a, z in (A.M_SYM, A.M_CAVE, A.M_GRP, A.M_SITE):
        a, z = a.strip("\n").encode(), z.strip("\n").encode()
        s = data.index(a) + len(a)
        data = data[:s] + nl + data[data.index(z, s):]
    assert b"- id: t_ntw_rects" not in data and b"- id: ntw_exec.gwinit" not in data
    out = A.splice(data)
    assert out == shipped_yaml
    assert A.splice(out) == out


def _site_callee(text: str, template: str, new: str) -> re.Match:
    pat = re.compile(re.escape(template).replace(re.escape("{T}"), r"(\w+)"))
    edges = A.tail_edges(text)
    hits = [m for m in pat.finditer(text) if A.chains_to(edges, m.group(1), new)]
    assert len(hits) == 1, (template, [m.group(1) for m in hits])
    return hits[0]


@pytest.mark.parametrize("rt", A.RETARGETS, ids=[r[3] for r in A.RETARGETS])
def test_splice_retargets_a_site_still_on_its_old_callee(shipped_yaml, rt):
    """The site as it was before ntw_scale (calling `old`) is retargeted to ntw's head, once; the rest is untouched."""
    template, old, new, _what = rt
    text = shipped_yaml.decode("utf-8")
    m = _site_callee(text, template, new)
    pre = (text[:m.start(1)] + old + text[m.end(1):]).encode("utf-8")
    want = (text[:m.start(1)] + new + text[m.end(1):]).encode("utf-8")
    assert A.splice(pre) == want
    assert A.splice(want) == want


def test_splice_fails_closed_when_the_chain_no_longer_reaches_ntw(shipped_yaml):
    """A later head that tail-jumps past t_ntw_gate (ntw dropped from the chain) is not ours to repair."""
    data = shipped_yaml.replace(b"68 {abs32:t_ntw_gate} C3", b"68 {abs32:t_mon_gate} C3")
    assert data != shipped_yaml
    with pytest.raises(AssertionError, match="thunk_btn_shrink gate call: 0 sites"):
        A.splice(data)


def test_splice_fails_closed_on_a_second_site():
    """A template that matches two candidate sites is ambiguous: no guess."""
    text = ('      - id: t_x_gate\n        offset: 0x10\n        bytes: "B8 01 00 00 00 C3 68 {abs32:t_ntw_gate} C3"\n'
            '    new_bytes: "E8 {rel32:t_x_gate} 85 C0 74 53"\n'
            '    new_bytes: "E8 {rel32:t_mon_gate} 85 C0 74 53"\n').encode()
    with pytest.raises(AssertionError, match="2 sites"):
        A.retarget(text, *A.RETARGETS[0])
    one = text.replace(b'    new_bytes: "E8 {rel32:t_mon_gate} 85 C0 74 53"\n', b"")
    assert A.retarget(one, *A.RETARGETS[0]) == one                       # behind a later head: already ntw's


# ---- icon-button stripes bypass + wheel -------------------------------------------------------------
@pytest.mark.parametrize("armed", (0, 1))
def test_scaling_icon_buttons_skip_the_stripes_pass(armed):
    for esi, mine in ((A.BTN_1, True), (A.BTN_2, True), (A.BTN_OK, False), (0x7F9F58 + 0xA58, False)):
        uc = mk(40)
        uc.mem_write(A.ARMED, struct.pack("<I", armed))
        at = run(uc, A.VA["t_ntw_nostripe"], {A.EDGEBAND, A.RINGFIX}, regs={UC_X86_REG_ESI: esi})
        if armed and mine:
            assert at == TRAP and uc.reg_read(UC_X86_REG_ESP) == SP0 + 4      # plain ret: no stripes / devfill / ring
        else:
            # everyone else: t_btn_edgeband (2026-10-25 W2D F39; it CALLs thunk_btn_ringfix first), stack intact
            assert at == A.EDGEBAND and uc.reg_read(UC_X86_REG_ESP) == SP0


def test_scaling_nostripe_tail_is_the_shipped_edgeband():
    """The pass-through target in the SHIPPED yaml is t_btn_edgeband, whose first instruction calls ringfix."""
    import apply_patches as ap
    _s, _g, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    shipped = {e["id"]: " ".join(str(e["bytes"]).split()) for c in caves for e in (c.get("contents") or [])}
    assert "68 {abs32:t_btn_edgeband} C3" in shipped["t_ntw_nostripe"]
    assert shipped["t_btn_edgeband"].startswith("E8 {rel32:thunk_btn_ringfix} ")
    assert dict(ap.build_symbol_table(symbols, caves))["t_btn_edgeband"] == A.EDGEBAND


def _wheel(g, modal_top, basepop, key, lparam, cursor, engaged, target=0x1234, hidden=()):
    """engaged = set of TextScroll VAs whose bar scrolls.  -> (stop addr, eax, chevron calls [(bar, dir)], presents)"""
    uc = mk(g)
    uc.mem_map(0x800000, 0x200000)                               # NetTechWin_g + MODAL_TOP / BASEPOP / G_HWND pages
    uc.mem_write(A.MODAL_TOP, struct.pack("<I", modal_top))
    uc.mem_write(A.BASEPOP, struct.pack("<I", basepop))
    uc.mem_write(A.G_HWND, struct.pack("<I", 0xBEEF))
    lay = SL.ntw_layout(g)
    for name, off in SL.NTW_RECT_FIELDS:
        uc.mem_write(A.NTW + off, struct.pack("<4i", *lay[name]))
    org = (700, 300)
    uc.mem_write(A.NTW + 0x13C, struct.pack("<2i", *org))
    present = VTBL + 0x900
    uc.mem_write(VTBL + 0xFC, struct.pack("<I", present))
    uc.mem_write(present, b"\xC3")
    for ts in [A.TS_QUOTE] + [A.TS_LIST0 + i * A.TS_STRIDE for i in range(4)]:
        uc.mem_write(ts, struct.pack("<I", VTBL))
        uc.mem_write(ts + 0x9C, b"\x01")
        bar = ts + 0xA20
        uc.mem_write(bar + 0xC4, struct.pack("<I", 1))
        uc.mem_write(bar + 0xA20, struct.pack("<2i", 0, 5 if (ts in engaged or ts in hidden) else 0))
        uc.mem_write(bar + 0x9C, b"\x01" if ts in engaged else b"\x00")     # the bar Win's own shown bit (= TS+0xABC)
    stub = 0x2601000 - 0x100
    iat_gcp, iat_s2c = stub, stub + 0x20
    uc.mem_write(A.IAT_GETCURSORPOS, struct.pack("<I", iat_gcp))
    uc.mem_write(A.IAT_SCREENTOCLIENT, struct.pack("<I", iat_s2c))
    # GetCursorPos(p): p->x = cx ; p->y = cy ; ret 4      ScreenToClient(hwnd, p): ret 8 (identity)
    cx, cy = org[0] + cursor[0], org[1] + cursor[1]
    uc.mem_write(iat_gcp, bytes.fromhex("8B442404C700") + struct.pack("<i", cx) + bytes.fromhex("C74004") + struct.pack("<i", cy) + bytes.fromhex("C20400"))
    uc.mem_write(iat_s2c, bytes.fromhex("C20800"))
    wheel_stc_stub.install(uc)        # the head calls t_wheel_stc (cell 0 = no uimod.dll -> the IAT stub above)
    uc.mem_write(A.GET_TARGET, bytes.fromhex("B8") + struct.pack("<I", target) + b"\xC3")
    uc.mem_write(A.CHEVRON, bytes.fromhex("C20400"))
    calls, presents = [], []

    def hook(u, addr, size, _):
        if addr == A.CHEVRON:
            sp = u.reg_read(UC_X86_REG_ESP)
            calls.append((u.reg_read(UC_X86_REG_ECX), struct.unpack("<I", bytes(u.mem_read(sp + 4, 4)))[0]))
        elif addr == present:
            presents.append(u.reg_read(UC_X86_REG_ECX))

    uc.hook_add(UC_HOOK_CODE, hook)
    frame = [0] * 0x1B
    frame[0x68 // 4 - 1], frame[0x6C // 4 - 1] = key, lparam
    out = {}
    for which, chain in (("down", A.RW_WHEEL_DOWN), ("up", A.RW_WHEEL_UP)):
        calls.clear(); presents.clear()
        at = run(uc, A.VA[f"t_ntw_wheel_{which}"], {chain}, stack=tuple(frame), regs={UC_X86_REG_EAX: 0x77})
        esp_ok = uc.reg_read(UC_X86_REG_ESP) == (SP0 if at == chain else SP0 + 4)
        out[which] = (at, uc.reg_read(UC_X86_REG_EAX), list(calls), list(presents), esp_ok)
    return out, lay


def test_scaling_wheel_routes_to_the_scroll_box_under_the_cursor():
    q, l0, l3 = A.TS_QUOTE, A.TS_LIST0, A.TS_LIST0 + 3 * A.TS_STRIDE
    for g in (16, 25, 40):
        lay = SL.ntw_layout(g)
        mid = lambda r: ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)   # noqa: E731
        # not our modal / a basepop on top / a real arrow key -> untouched
        out, _ = _wheel(g, 0x703EA0, 0, 0x28, 0, mid(lay["quote"]), {q})
        assert out["down"][0] == A.RW_WHEEL_DOWN and out["up"][0] == A.RW_WHEEL_UP and out["down"][4] and out["up"][4]
        out, _ = _wheel(g, A.NTW, 0x999, 0x28, 0, mid(lay["quote"]), {q})
        assert out["down"][0] == A.RW_WHEEL_DOWN and out["down"][2] == []
        out, _ = _wheel(g, A.NTW, 0, 0x28, 0x1500001, mid(lay["quote"]), {q})
        assert out["down"][:3] == (TRAP, 0x1234, []) and out["up"][:2] == (TRAP, 0x1234)
        out, _ = _wheel(g, A.NTW, 0, 0x41, 0, mid(lay["quote"]), {q})
        assert out["down"][:3] == (TRAP, 0x1234, [])
        # quote engaged: the notch scrolls it wherever the cursor is; KEYUP twin swallowed
        for cur in (mid(lay["quote"]), mid(lay["icon"]), mid(lay["list_tl"])):
            out, _ = _wheel(g, A.NTW, 0, 0x28, 0, cur, {q})
            assert out["down"][:4] == (TRAP, 0, [(q + 0xA20, 2)], [q]) and out["down"][4]
            assert out["up"][:3] == (TRAP, 0, [])
        out, _ = _wheel(g, A.NTW, 0, 0x26, 0, mid(lay["quote"]), {q})
        assert out["down"][2] == [(q + 0xA20, 1)]
        # a scrolling list under the cursor wins over the quote; elsewhere the quote wins
        out, _ = _wheel(g, A.NTW, 0, 0x28, 0, mid(lay["list_br"]), {q, l3, l0})
        assert out["down"][2] == [(l3 + 0xA20, 2)] and out["down"][3] == [l3]
        out, _ = _wheel(g, A.NTW, 0, 0x28, 0, mid(lay["list_tr"]), {q, l3})
        assert out["down"][2] == [(q + 0xA20, 2)]
        out, _ = _wheel(g, A.NTW, 0, 0x28, 0, mid(lay["header"]), {l3})
        assert out["down"][2] == [(l3 + 0xA20, 2)]
        # a bar that is NOT SHOWN never scrolls, even though its range is live (user report 2026-09-19: the quote box
        # scrolled with no scrollbar on screen); a shown bar elsewhere still gets the notch
        out, _ = _wheel(g, A.NTW, 0, 0x28, 0, mid(lay["quote"]), set(), hidden={q})
        assert out["down"][:4] == (TRAP, 0, [], [])
        out, _ = _wheel(g, A.NTW, 0, 0x28, 0, mid(lay["list_tl"]), {l3}, hidden={q, l0})
        assert out["down"][2] == [(l3 + 0xA20, 2)]
        # nothing scrolls: still swallowed (never a selection move / map zoom)
        out, _ = _wheel(g, A.NTW, 0, 0x28, 0, mid(lay["quote"]), set())
        assert out["down"][:4] == (TRAP, 0, [], []) and out["down"][4]


@pytest.mark.parametrize("mode,origin,space,hits", wheel_stc_stub.MODES)
def test_wheel_pracx_cursor_modes_list_corner(mode, origin, space, hits):
    """t_ntw_wheel_down through PRACX's hooked GetCursorPos + t_wheel_stc: the bottom-right list's top-left
    corner wins over the quote in every display setup; the no-DLL control misses it by the window origin.
    (_wheel's cursor is NetTechWin-local; the window origin it adds is the backbuffer one.)"""
    g = 25
    q, l3 = A.TS_QUOTE, A.TS_LIST0 + 3 * A.TS_STRIDE
    r = SL.ntw_layout(g)["list_br"]
    cur = wheel_stc_stub.pracx_cursor((r[0], r[1]), origin, space)
    with wheel_stc_stub.mode(mode, *origin):
        out, _ = _wheel(g, A.NTW, 0, 0x28, 0, cur, {q, l3})
    assert out["down"][2] == [((l3 if hits else q) + 0xA20, 2)]
