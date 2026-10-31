"""Unicorn parity for the diplowin_scale thunks (assemble_diplowin.py) against scaling_laws.dw_*.

  * t_dw_rects at every g in 17..40 over several screens / strips / seeds == dw_window_rect + dw_layout (all live
    fields), nothing else in the object written, callee-saved registers intact;
  * every call-site wrapper is run to its tail target (engine callees are stop addresses; thunk_art_draw is a
    RET 0x18 stub) and its stack args / rect copy / caller-frame locals compared with the law;
  * g=16: every wrapper reaches its native callee with the stack and registers untouched;
  * the yaml carries exactly these bytes (a site / thunk desync fails here).
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("unicorn")
pytest.importorskip("keystone")
pytest.importorskip("pefile")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
                               UC_X86_REG_ESI, UC_X86_REG_ESP)

import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

if not pathlib.Path(config.terranx_bak()).exists():
    pytest.skip("pristine .bak not present", allow_module_level=True)
import assemble_diplowin as A  # noqa: E402

GS = list(range(17, 41))
STACK, SP0 = 0x02500000, 0x02508000
FRAME = 0x02504000                        # a caller ebp frame
TRAP = 0x02600000
NATIVE_DC0 = (262, 66, 763, 234)
SAVED = {UC_X86_REG_EBX: 0xB0B0B0B0, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
         UC_X86_REG_EBP: FRAME}


def mk(g: int) -> Uc:
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(0x400000, 0xA0C000 - 0x400000)      # image range (zero: every global the thunks read is written below)
    uc.mem_map(A.PCAVE2, 0x30000)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(TRAP, 0x1000)
    uc.mem_write(TRAP, b"\xf4" * 16)
    uc.mem_write(A.G, struct.pack("<I", g))
    for name, (off, b) in A.OUT.items():
        uc.mem_write(A.PCAVE2 + off, b)
    uc.mem_write(A.ART_DRAW, b"\xC2\x18\x00")      # thunk_art_draw stub: ret 0x18
    uc.mem_write(A.PAVG_GATE_IMM, struct.pack("<I", 0x940824))
    return uc


def run(uc: Uc, start: int, stops, regs=None, stack=(), count=400000, hook=None):
    sp = SP0
    uc.mem_write(sp, struct.pack(f"<{1 + len(stack)}I", TRAP, *[v & 0xFFFFFFFF for v in stack]))
    uc.reg_write(UC_X86_REG_ESP, sp)
    for r, v in {**SAVED, **(regs or {})}.items():
        uc.reg_write(r, v & 0xFFFFFFFF)
    stops = set(stops) | {TRAP}
    hit = {}

    def h(u, addr, size, _):
        if hook:
            hook(u, addr)
        if addr in stops:
            hit["at"] = addr
            u.emu_stop()

    hh = uc.hook_add(UC_HOOK_CODE, h)
    try:
        uc.emu_start(start, 0, count=count)
    finally:
        uc.hook_del(hh)
    return hit.get("at")


def rd(uc: Uc, va: int, n: int = 1):
    v = struct.unpack(f"<{n}i", bytes(uc.mem_read(va, 4 * n)))
    return v if n > 1 else v[0]


def wr(uc: Uc, va: int, *vals):
    uc.mem_write(va, struct.pack(f"<{len(vals)}i", *vals))


def esp(uc: Uc) -> int:
    return uc.reg_read(UC_X86_REG_ESP)


# ---- the lever ---------------------------------------------------------------------------------------------------
WORLDS = [(3840, 2160), (1920, 1080), (1600, 1200), (2560, 1440), (1280, 1024), (1024, 768)]


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("sw,sh", WORLDS)
def test_scaling_rects_match_the_law(g, sw, sh):
    uc = mk(g)
    strip = (SL.NATIVE_G and (213 * g) >> 4)
    dc0 = tuple(SL.dp(v, g) for v in NATIVE_DC0)
    wr(uc, A.SW_VA, sw)
    wr(uc, A.SH_VA, sh)
    wr(uc, A.STRIP_VA, strip)
    wr(uc, A.DC0_VA, *dc0)
    uc.mem_write(A.DW, b"\xCC" * 0x1200)
    assert run(uc, A.VA["t_dw_rects"], (), regs={UC_X86_REG_ESI: A.DW, UC_X86_REG_ECX: 0x55667788}) == TRAP
    x, y, w, h = SL.dw_window_rect(sw, sh, strip, g)
    assert rd(uc, A.WIN, 4) == (x, y, w, h)
    lay = SL.dw_layout(w, h, dc0, g)
    got = {off: rd(uc, A.DW + off, 4) for off in lay}
    assert got == lay
    blob = bytes(uc.mem_read(A.DW, 0x1200))
    written = set()
    for off in lay:
        written.update(range(off, off + 16))
    assert all(blob[i] == 0xCC for i in range(0x1200) if i not in written)
    assert uc.reg_read(UC_X86_REG_ESI) == A.DW and uc.reg_read(UC_X86_REG_ECX) == 0x55667788
    assert uc.reg_read(UC_X86_REG_EBP) == FRAME and uc.reg_read(UC_X86_REG_EBX) == SAVED[UC_X86_REG_EBX]
    assert uc.reg_read(UC_X86_REG_EDI) == SAVED[UC_X86_REG_EDI] and esp(uc) == SP0 + 4


@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_scaling_build_rewrites_the_window_args(g):
    uc = mk(g)
    sw, sh, strip = 3840, 2160, (213 * g) >> 4 if g > 16 else 213
    wr(uc, A.SW_VA, sw)
    wr(uc, A.SH_VA, sh)
    wr(uc, A.STRIP_VA, strip)
    wr(uc, A.DC0_VA, *[SL.dp(v, g) for v in NATIVE_DC0])
    args = (1520, 1564, 0x340, 0x254 - strip, 0, 0x5000000, 0x9156B0, 0, 0)
    assert run(uc, A.VA["t_dw_build"], {A.GW_INIT}, regs={UC_X86_REG_ECX: A.DW, UC_X86_REG_ESI: A.DW}, stack=args) == A.GW_INIT
    got = rd(uc, esp(uc) + 4, 9)
    want = SL.dw_window_rect(sw, sh, strip, g) if g > 16 else args[:4]
    assert got[:4] == tuple(want) and got[4:] == args[4:]
    assert esp(uc) == SP0 and rd(uc, esp(uc)) == TRAP
    assert uc.reg_read(UC_X86_REG_ECX) == A.DW and uc.reg_read(UC_X86_REG_ESI) == A.DW
    assert uc.reg_read(UC_X86_REG_EBX) == SAVED[UC_X86_REG_EBX] and uc.reg_read(UC_X86_REG_EDI) == SAVED[UC_X86_REG_EDI]


# ---- builder wrappers --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_scaling_capsz(g):
    uc = mk(g)
    wr(uc, A.DW + 0x16C, 0x1A)
    assert run(uc, A.VA["t_dw_capsz"], {A.GW_CLEAR}, regs={UC_X86_REG_ECX: A.DW}, stack=(9,)) == A.GW_CLEAR
    assert rd(uc, A.DW + 0x16C) == SL.dw_caption_size(g)
    assert esp(uc) == SP0 and uc.reg_read(UC_X86_REG_ECX) == A.DW


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
@pytest.mark.parametrize("netwin0", [0, 1])
def test_scaling_ts3(g, netwin0):
    """g<=16: tail to TextScroll_attach, args untouched.  g>16: the dp(3) inset, then TextScroll_attach CALLED with
    g_netwin_active raised by one (the two g_scrollbar_w reads inside scale the bar), restored after; ret 0x1C."""
    uc = mk(g)
    args = (500, 200, 900, 300, 0x7AE820, 0, -1)
    wr(uc, A.G_NETWIN, netwin0)
    d = SL.dw_ts_inset_delta(g)
    want = (500 + d, 200 + d, 900 - 2 * d, 300 - 2 * d, 0x7AE820, 0, -1)
    if g <= 16:
        assert run(uc, A.VA["t_dw_ts3"], {A.TS_ATTACH}, regs={UC_X86_REG_ECX: 0x1234}, stack=args) == A.TS_ATTACH
        assert rd(uc, SP0 + 4, 7) == args and uc.reg_read(UC_X86_REG_ECX) == 0x1234 and rd(uc, A.G_NETWIN) == netwin0
        return
    uc.mem_write(A.TS_ATTACH, b"\xC2\x1C\x00")                       # TextScroll_attach stub: ret 0x1C
    seen = {}

    def hook(u, addr):
        if addr == A.TS_ATTACH:
            seen["netwin"] = rd(u, A.G_NETWIN)
            seen["args"] = rd(u, esp(u) + 4, 7)
            seen["ecx"] = u.reg_read(UC_X86_REG_ECX)

    assert run(uc, A.VA["t_dw_ts3"], (), regs={UC_X86_REG_ECX: 0x1234}, stack=args, hook=hook) == TRAP
    assert seen == {"netwin": netwin0 + 1, "args": want, "ecx": 0x1234}
    assert rd(uc, A.G_NETWIN) == netwin0                              # the bracket closes
    assert esp(uc) == SP0 + 4 + 0x1C                                  # ret 0x1C: the site's 7 args consumed


def test_scaling_ts3_bracket_clamps_at_zero():
    """thunk_sb_restripe writes g_netwin_active absolute; a 0 seen after the call must not go negative."""
    uc = mk(25)
    uc.mem_write(A.TS_ATTACH, b"\xC7\x05" + struct.pack("<I", A.G_NETWIN) + b"\x00\x00\x00\x00\xC2\x1C\x00")
    wr(uc, A.G_NETWIN, 0)
    assert run(uc, A.VA["t_dw_ts3"], (), regs={UC_X86_REG_ECX: 0x1234},
               stack=(500, 200, 900, 300, 0x7AE820, 0, -1)) == TRAP
    assert rd(uc, A.G_NETWIN) == 0 and esp(uc) == SP0 + 4 + 0x1C


@pytest.mark.parametrize("g", [16, 25])
def test_scaling_enter_brackets_the_builder(g):
    uc = mk(g)
    seen = {}

    def hook(u, addr):
        if addr == A.BUILD:
            seen["armed"] = rd(u, A.ARMED)
            seen["args"] = rd(u, esp(u) + 4, 2)
            seen["ecx"] = u.reg_read(UC_X86_REG_ECX)
            # emulate DiploWin_build's RET 8 (thiscall)
            ret = struct.unpack("<I", bytes(u.mem_read(esp(u), 4)))[0]
            u.reg_write(UC_X86_REG_ESP, esp(u) + 12)
            u.reg_write(UC_X86_REG_EIP, ret)

    assert run(uc, A.VA["t_dw_enter"], (), regs={UC_X86_REG_ECX: A.DW}, stack=(3, 5), hook=hook) == TRAP
    assert seen["args"] == (3, 5) and seen["ecx"] == A.DW
    assert seen["armed"] == (1 if g > 16 else 0)
    assert rd(uc, A.ARMED) == 0
    assert esp(uc) == SP0 + 4 + 8                          # ret 8: the caller's two args consumed


@pytest.mark.parametrize("armed", [0, 1])
@pytest.mark.parametrize("n", [1, 2, 7, 12, 13])
def test_scaling_gate(armed, n):
    uc = mk(25)
    wr(uc, A.ARMED, armed)
    btn = A.DW + 0x10AC + n * 0xB4C
    at = run(uc, A.VA["t_dw_gate"], {A.T_NTW_GATE}, regs={UC_X86_REG_ESI: btn, UC_X86_REG_EAX: 0})
    if armed and 2 <= n <= 12:
        assert at == TRAP and uc.reg_read(UC_X86_REG_EAX) == 1
    else:
        assert at == A.T_NTW_GATE and esp(uc) == SP0
    assert uc.reg_read(UC_X86_REG_ESI) == btn


@pytest.mark.parametrize("armed", [0, 1])
@pytest.mark.parametrize("obj", ["up", "dn", "bar", "up+4"])
def test_scaling_gate_admits_the_chat_bar_arrows(armed, obj):
    uc = mk(25)
    wr(uc, A.ARMED, armed)
    esi = {"up": A.CHAT_ARROWS[0], "dn": A.CHAT_ARROWS[1], "bar": A.CHAT_SB, "up+4": A.CHAT_ARROWS[0] + 4}[obj]
    at = run(uc, A.VA["t_dw_gate"], {A.T_NTW_GATE}, regs={UC_X86_REG_ESI: esi, UC_X86_REG_EAX: 0})
    if armed and obj in ("up", "dn"):
        assert at == TRAP and uc.reg_read(UC_X86_REG_EAX) == 1
    else:
        assert at == A.T_NTW_GATE and esp(uc) == SP0


# ---- the wheel heads ---------------------------------------------------------------------------------------------
def wheel_world(g, modal, basepop, ts_shown, sb_shown, rng, target=0x12345678):
    uc = mk(g)
    uc.mem_write(A.GET_TARGET, b"\xB8" + struct.pack("<I", target) + b"\xC3")   # Win_get_active_target stub
    uc.mem_write(A.CHEVRON, b"\xC2\x04\x00")                         # ScrollBar_on_chevron stub: ret 4
    wr(uc, A.MODAL_TOP, modal)
    wr(uc, A.BASEPOP, basepop)
    uc.mem_write(A.CHAT_TS + 0x9C, bytes([1 if ts_shown else 0]))
    uc.mem_write(A.CHAT_SB + 0x9C, bytes([1 if sb_shown else 0]))
    wr(uc, A.CHAT_SB + 0xC4, A.CHAT_TS)
    wr(uc, A.CHAT_SB + 0xA20, 0, rng)                                 # range min / max
    VT = 0x02503E00
    wr(uc, A.CHAT_TS, VT)
    uc.mem_write(VT + 0xFC, struct.pack("<I", 0x02503F00))
    uc.mem_write(0x02503F00, b"\xC3")                                 # TextScroll present: ret
    return uc


@pytest.mark.parametrize("target", [0x12345678, 0])
@pytest.mark.parametrize("key", [0x26, 0x28])
@pytest.mark.parametrize("engaged", [True, False])
def test_scaling_wheel_down_scrolls_the_chat(key, engaged, target):
    """target 0: Win_get_active_target returns DiploWin's active child +0xA8, which DiploWin_build never sets --
    the synthetic wheel arrows must still scroll (the NTW heads' `jz xout` would have left the wheel dead)."""
    uc = wheel_world(25, A.DW, 0, True, engaged, 7, target=target)
    calls = []

    def hook(u, addr):
        if addr == A.CHEVRON:
            calls.append((u.reg_read(UC_X86_REG_ECX), rd(u, esp(u) + 4)))

    stack = [0] * 0x19 + [key, 0]                                     # [esp+0x68] = wParam, [esp+0x6C] = lParam
    at = run(uc, A.VA["t_dw_wheel_down"], (), stack=stack, hook=hook)
    assert at == TRAP and uc.reg_read(UC_X86_REG_EAX) == 0            # swallowed either way
    assert calls == ([(A.CHAT_SB, 1 if key == 0x26 else 2)] if engaged else [])
    for r in (UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBX, UC_X86_REG_EBP):
        assert uc.reg_read(r) == SAVED[r]
    assert esp(uc) == SP0 + 4


@pytest.mark.parametrize("modal,basepop", [(0x876478, 0), (A.DW, 0x9403E0), (0, 0)])
def test_scaling_wheel_chains_when_not_ours(modal, basepop):
    for name, nxt in (("t_dw_wheel_down", A.T_BW_WHEEL_DOWN), ("t_dw_wheel_up", A.T_BW_WHEEL_UP)):
        uc = wheel_world(25, modal, basepop, True, True, 7)
        stack = [0] * 0x19 + [0x28, 0]
        assert run(uc, A.VA[name], {nxt}, stack=stack) == nxt and esp(uc) == SP0


def test_scaling_wheel_real_keys_pass_through():
    """lParam != 0 (a real key press) or another key: the original callee's target is returned untouched."""
    for name in ("t_dw_wheel_down", "t_dw_wheel_up"):
        for key, lp in ((0x28, 5), (0x41, 0)):
            uc = wheel_world(25, A.DW, 0, True, True, 7)
            assert run(uc, A.VA[name], (), stack=[0] * 0x19 + [key, lp]) == TRAP
            assert uc.reg_read(UC_X86_REG_EAX) == 0x12345678 and esp(uc) == SP0 + 4


# ---- frame / text wrappers --------------------------------------------------------------------------------------
RECT_VA = 0x02503000


def frame_case(name, g, rect, stops, argpos=1, extra=()):
    uc = mk(g)
    wr(uc, RECT_VA, *rect)
    stack = [RECT_VA] if argpos == 1 else [0x6839FC, RECT_VA, 5]
    stack += list(extra)
    at = run(uc, A.VA[name], stops, regs={UC_X86_REG_ECX: 0x73B11C}, stack=stack)
    assert uc.reg_read(UC_X86_REG_ECX) == 0x73B11C
    assert rd(uc, RECT_VA, 4) == tuple(rect)                  # the engine's rect is never mutated
    ptr = rd(uc, SP0 + 4 * argpos) & 0xFFFFFFFF
    return uc, at, rd(uc, ptr, 4)


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_scaling_bm_bmdf(g):
    r = (100, 50, 900, 300)
    for name, tgt in (("t_dw_bm", A.HOLLOWFLAT), ("t_dw_bmdf", A.DEVFILL)):
        uc, at, got = frame_case(name, g, r, {tgt, A.BOX_SPRITE}, extra=(0x78D5A0,))
        if g > 16:
            assert at == tgt and got == SL.bandmap_rect_from_halfopen(*r, g)
        else:
            assert at == A.BOX_SPRITE and got == r


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_scaling_ring(g):
    union = (60, 120, 960, 800)
    r = (union[0] - 3, union[1] - 3, union[2] + 3, union[3] + 3)       # what the painter hands over
    uc, at, got = frame_case("t_dw_ring", g, r, {A.HOLLOWFLAT, A.BOX_SPRITE}, extra=(0x78D5A0,))
    if g > 16:
        l, t, rr, b = SL.dw_ring(union, g)
        assert at == A.HOLLOWFLAT and got == (l, t, rr - 1, b - 1)
    else:
        assert at == A.BOX_SPRITE and got == r


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_scaling_mw4(g):
    seed = (1950, 140, 2550, 630)
    r = (seed[0] + 4, seed[1] + 4, seed[2] - 4, seed[3] - 4)
    uc, at, got = frame_case("t_dw_mw4", g, r, {A.BOX_SPRITE}, extra=(0x78D5A0,))
    assert at == A.BOX_SPRITE
    assert got == (SL.dw_console_frame(seed, g) if g > 16 else r)


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_scaling_in3(g):
    box = (100, 50, 900, 100)
    r = (box[0] + 3, box[1] + 3, box[2] - 3, box[3] - 3)
    uc, at, got = frame_case("t_dw_in3", g, r, {A.CENT7}, argpos=2)
    assert at == A.CENT7
    assert got == (SL.dw_text_inset(box, g) if g > 16 else r)
    assert rd(uc, SP0 + 4) == 0x6839FC and rd(uc, SP0 + 12) == 5


# ---- art / status / offers --------------------------------------------------------------------------------------
ART_W, ART_H = 164, 198
SPRITE = 0x02503800


def art_world(g):
    uc = mk(g)
    w, h = SL.dp(832, g), SL.dp(596, g) - ((213 * g) >> 4 if g > 16 else 213)
    lay = SL.dw_layout(w, h, tuple(SL.dp(v, g) for v in NATIVE_DC0), g) if g > 16 else \
        SL.dw_layout(832, 383, NATIVE_DC0, 16)
    for off in (0xF5C, 0xF6C):
        wr(uc, A.DW + off, *lay[off])
    wr(uc, SPRITE + 0x18, ART_W, ART_H)
    return uc, lay


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
@pytest.mark.parametrize("right", [False, True])
def test_scaling_art(g, right):
    uc, lay = art_world(g)
    panel = lay[0xF6C if right else 0xF5C]
    # native caller state: the art rect locals + pushed x/y
    nx = panel[2] - 1 - ART_W if right else panel[0] + 1
    ny = panel[1] + 1
    wr(uc, FRAME - 0x14, nx, ny, nx + ART_W, ny + ART_H)
    seen = {}

    def hook(u, addr):
        if addr == A.ART_DRAW:
            seen["args"] = rd(u, esp(u) + 4, 6)
            seen["gate"] = rd(u, A.PAVG_GATE_IMM)
            seen["ecx"] = u.reg_read(UC_X86_REG_ECX)

    name = "t_dw_artR" if right else "t_dw_artL"
    at = run(uc, A.VA[name], {A.SPRITE_DRAW2}, regs={UC_X86_REG_ECX: SPRITE},
             stack=(A.CANVAS, 9, nx, ny, 1, 1), hook=hook)
    if g <= 16:
        assert at == A.SPRITE_DRAW2 and rd(uc, SP0 + 4, 6) == (A.CANVAS, 9, nx, ny, 1, 1)
        return
    art = SL.dw_art_rect(panel, right, ART_W, ART_H, g)
    assert at == TRAP and esp(uc) == SP0 + 4 + 0x18            # ret 0x18
    assert seen["args"] == (A.CANVAS, 9, art[0], art[1], g, 16)
    assert seen["gate"] == A.CANVAS and seen["ecx"] == SPRITE
    assert rd(uc, A.PAVG_GATE_IMM) == 0x940824                  # restored
    assert rd(uc, FRAME - 0x14, 4) == art                        # the status box derives from the drawn art
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI):
        assert uc.reg_read(r) == SAVED[r]
    assert uc.reg_read(UC_X86_REG_EBP) == FRAME


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
def test_scaling_status(g):
    art = (78, 135, 488, 630)
    native = (art[0] + 4, art[3] - 0x18, art[2] - 4, art[3] - 4)
    uc = mk(g)
    wr(uc, FRAME - 0x14, *native)
    at = run(uc, A.VA["t_dw_status"], {A.MAP_COLORS}, regs={UC_X86_REG_ECX: A.CANVAS}, stack=(FRAME - 0x14, 0x6F107C))
    assert at == A.MAP_COLORS and uc.reg_read(UC_X86_REG_ECX) == A.CANVAS
    assert rd(uc, FRAME - 0x14, 4) == (SL.dw_status_rect(art, g) if g > 16 else native)
    assert rd(uc, SP0 + 4, 2) == (FRAME - 0x14, 0x6F107C)


FONT = 0x02503C00


@pytest.mark.parametrize("g", [16, 17, 22, 25, 40])
@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("metric", [(3, 14, 0), (-1, 0, 17)])     # ([f], [f+0x10], [f+0xC]): both metric branches
def test_scaling_offers(g, side, metric):
    uc, lay = art_world(g)
    uc.mem_write(A.FIND_FONT, b"\xB8" + struct.pack("<I", FONT) + b"\xC3")   # mov eax, FONT ; ret (cdecl)
    f0, f10, fc = metric
    wr(uc, FONT, f0)
    wr(uc, FONT + 0xC, fc)
    wr(uc, FONT + 0x10, f10)
    native_metric = f10 + f0 if f0 >= 0 else fc
    wr(uc, FRAME - 0xC, 12345)                               # the painter's pitch local (scaled-font metric)
    wr(uc, A.DW + 0xAB4, 3)
    wr(uc, A.DW + 0xAB8, 5)
    wr(uc, A.ART_W_TAB + 3 * 0x65C, ART_W)
    wr(uc, A.ART_W_TAB + 5 * 0x65C, ART_W)
    panel = lay[0xF6C if side else 0xF5C]
    nx = panel[0] + 3 if side else panel[0] + ART_W + 1 + 3
    nr = panel[2] - 1 - ART_W - 3 if side else panel[2] - 3
    wr(uc, FRAME - 0x28, nx)
    wr(uc, FRAME - 4, nr - nx)
    regs = {UC_X86_REG_ESI: side, UC_X86_REG_EDI: A.DW, UC_X86_REG_EBX: panel[1] + 3, UC_X86_REG_ECX: A.CANVAS}
    at = run(uc, A.VA["t_dw_offers"], {A.SET_TEXT_COLOR}, regs=regs, stack=(0x41, -1, 1, 1))
    assert at == A.SET_TEXT_COLOR and uc.reg_read(UC_X86_REG_ECX) == A.CANVAS
    x, t, w = SL.dw_offer_list(panel, bool(side), ART_W, g) if g > 16 else (nx, panel[1] + 3, nr - nx)
    assert (rd(uc, FRAME - 0x28), uc.reg_read(UC_X86_REG_EBX), rd(uc, FRAME - 4)) == (x, t, w)
    assert rd(uc, FRAME - 0xC) == (SL.dw_offer_pitch(native_metric, g) if g > 16 else 12345)
    assert uc.reg_read(UC_X86_REG_ESI) == side and uc.reg_read(UC_X86_REG_EDI) == A.DW
    if g == 16:
        assert (nx, panel[1] + 3, nr - nx) == SL.dw_offer_list(panel, bool(side), ART_W, 16)


# ---- the yaml carries these bytes -------------------------------------------------------------------------------
def test_scaling_yaml_carries_these_exact_bytes():
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    st = dict(ap.build_symbol_table(symbols, caves))
    ents = {e["id"]: e for c in caves for e in (c.get("contents") or [])}
    for name, (off, b) in A.OUT.items():
        assert st[name] == A.PCAVE2 + off, name
        assert ap.ByteTemplate(ents[name]["bytes"]).resolve(st[name], st) == b, name
    for name, va in A.REUSED.items():
        assert st[name] == va, name
    by_id = {s["id"]: s for s in sites}
    for sid, _fn, va, _callee, tgt, _note in A.SITES:
        s = by_id[sid]
        v = s["virtual_addr"]
        assert (v if isinstance(v, int) else int(v, 16)) == va and s["group"] == A.GROUP
        assert ap.ByteTemplate(s["new_bytes"]).resolve(va, st) == b"\xE8" + struct.pack("<i", st[tgt] - (va + 5))


# ---- chat font / console save-under ----------------------------------------------------------------------------
@pytest.mark.parametrize("g", [16, 22, 25, 40])
def test_scaling_chatfont(g):
    uc = mk(g)
    wr(uc, A.HUD_FONT_NAME, 0x00691B40)                                 # the face-name pointer the engine reads
    uc.mem_write(A.FONT_INIT, b"\xC2\x0C\x00")                          # Font_init stub: ret 0xC
    for slot in A.CHAT_FONT_SLOTS:
        wr(uc, slot, 0x7D3948)
    calls = []

    def hook(u, addr):
        if addr == A.FONT_INIT:
            calls.append((u.reg_read(UC_X86_REG_ECX), rd(u, esp(u) + 4, 3)))

    for _ in range(2):                                                    # a second open at the same g: no re-init
        at = run(uc, A.VA["t_dw_chatfont"], {A.TS_CLEAR}, regs={UC_X86_REG_ECX: A.DW + 0xA388}, hook=hook)
        assert at == A.TS_CLEAR and uc.reg_read(UC_X86_REG_ECX) == A.DW + 0xA388 and esp(uc) == SP0
    if g <= 16:
        assert calls == [] and all(rd(uc, s) == 0x7D3948 for s in A.CHAT_FONT_SLOTS)
        return
    assert calls == [(A.CHATFONT, (0x00691B40, SL.dp(12, g), 0))]
    assert all(rd(uc, s) == A.CHATFONT for s in A.CHAT_FONT_SLOTS)


def test_scaling_snap_is_the_live_console_saveunder_clone():
    """t_dw_snap must stay an exact clone of the live t_cr_snap_dl (the other save-under snapshots' family) --
    same instructions and encodings, only its own branch targets and the tail (DiploWinIface_on_mode) differ.
    If the family is revised, this fails until the clone is re-ported."""
    import apply_patches as ap
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    st = dict(ap.build_symbol_table(symbols, caves))
    ents = {e["id"]: e for c in caves for e in (c.get("contents") or [])}
    live = ap.ByteTemplate(ents["t_cr_snap_dl"]["bytes"]).resolve(st["t_cr_snap_dl"], st)
    off, mine = A.OUT["t_dw_snap"]
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    L, M = list(md.disasm(live, st["t_cr_snap_dl"])), list(md.disasm(mine, A.PCAVE2 + off))
    assert len(L) == len(M) and len(live) == len(mine)
    branches = {"jle", "je", "jne", "jmp"}
    for a, b in zip(L, M):
        if a.mnemonic in branches:
            assert (a.mnemonic, a.size) == (b.mnemonic, b.size)
            ta, tb = int(a.op_str, 16), int(b.op_str, 16)
            if a.mnemonic == "jmp":
                assert tb == A.ONMODE
            else:
                assert ta - st["t_cr_snap_dl"] == tb - (A.PCAVE2 + off)
        elif a.mnemonic == "call" and a.bytes[0] == 0xE8:             # rel32: same absolute target (t_cr_mark)
            assert (b.mnemonic, b.op_str, b.size) == (a.mnemonic, a.op_str, a.size)
        else:
            assert (a.mnemonic, a.op_str, a.bytes) == (b.mnemonic, b.op_str, b.bytes)


def test_scaling_yaml_carries_the_vtable_repoint():
    import apply_patches as ap
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    st = dict(ap.build_symbol_table(symbols, caves))
    by_id = {s["id"]: s for s in sites}
    for sid, _fn, va, ptr, tgt, _note in A.VTABLE_SITES:
        s = by_id[sid]
        v = s["virtual_addr"]
        assert (v if isinstance(v, int) else int(v, 16)) == va and s["group"] == A.GROUP
        assert s["pattern"] == "vtable_repoint"
        assert ap.ByteTemplate(s["new_bytes"]).resolve(va, st) == struct.pack("<I", st[tgt])
