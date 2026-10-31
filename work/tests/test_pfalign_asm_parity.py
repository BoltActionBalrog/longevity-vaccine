"""Differential: the BAKED pf-align pair must agree with the Python reference.

`scaling_laws.py` is the source of truth; the x86 that ships (from
scripts/assemble_pf_align.py) is emulated here under Unicorn and checked
against body_outer_edge_r/_l and body_inner_edge_r/_l, per g in [16,40],
for the art and no-art branches and all three passthrough gates.

What it verifies:
  * the scratch rect the draw actually receives == the law, edge by edge
  * top/bottom are copied from the LOCAL rect verbatim (never title-derived) -- except the type-1 hug
    arm (v16), whose t/b come from the caller's dialog rect D like its l/r
  * ART popups keep the engine's art-aware LEFT; no-art popups take the
    title-derived left
  * g_d528_left tracks align.l (the body text X follows it via textfollow)
  * g <= 16 / faction singleton / concentric [esi+0xa14] -> the rect arg is
    NOT repointed and the scratch is untouched (native no-op invariant)
  * ecx (dest buffer, thiscall this) and esi (popup) are preserved
  * the tail lands on the right thickener (d5a0_center / box_thick_devfill)

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import (  # noqa: E402
    NATIVE_G,
    body_inner_edge_l,
    body_inner_edge_r,
    body_outer_edge_l,
    body_outer_edge_r,
    itemlist_container_edge_l,
    itemlist_container_edge_r,
    itemlist_ring_hug,
    itemlist_ring_list_r,
    itemlist_ring_takes_hug_arm,
    listbox_ring_takes_hug_arm,
    ornate_picker_takes_container_arm,
    ornate_container_edge_l, ornate_container_edge_r,
    ornate_picker_container_edge_r,
    popup_frame_rewrite_applies,
)

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP,
    UC_X86_REG_ECX,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

import assemble_pf_align as gen  # noqa: E402
import assemble_scale_boxw as BW  # noqa: E402  t_boxw_t1_term v2 + t_t1_list_w (the v17 hug arm calls them)

CODE_UNION = 0x00A17000        # pcave2 + 0xB000 (v4; was +0xA780)
CODE_FRAME = 0x00A17800        # pcave2 + 0xA800
CODE_TEXT = 0x00A17C00         # textfollow v3 (same page)
SENT_PAGE = 0xDEADB000         # all abs32 sentinels live in this one page
G_ADDR = 0xDEADBE00
TITLE_L, TITLE_R = 0xDEADBE04, 0xDEADBE08
UNION = {"l": 0xDEADBE10, "t": 0xDEADBE14, "r": 0xDEADBE18, "b": 0xDEADBE1C}
ALIGN = {"l": 0xDEADBE30, "t": 0xDEADBE34, "r": 0xDEADBE38, "b": 0xDEADBE3C}
D528_LEFT = 0xDEADBE40
D528_KEY = 0xDEADBE50          # g_d528_popup (frame v9 ornate arm -> textfollow v3)
BWS = 0xDEADBE54               # Buffer_write_strings sentinel (textfollow tail)
D528_ENGX = 0xDEADBE58         # g_d528_engx (the engine text X the ornate arm moved)
TAIL_UNION = 0xDEADBE20        # thunk_d5a0_center sentinel
TAIL_FRAME = 0xDEADBE44        # thunk_box_thick_devfill sentinel
SCREEN_W = 0xDEADBE48          # ScreenWidth sentinel (v5-v14 native-fix regime gate; unread since v15)

POPUP = 0x00300000             # scratch popup (fields +0xa14, +0x2144, +0x30bc)
FACTION_POPUP = 0x009403E0     # the singleton the gate excludes
RECT = 0x00400000              # the engine's local rect
STACK = 0x00200000
RETADDR = 0x0040623D

PAGE = 0x1000

# a real 4K title-band stash and a plausible art-popup local rect
T_L, T_R = 65, 1932
LOCAL = {"l": 583, "t": 80, "r": 1740, "b": 152}
BOXW = 679                     # the measured Customize Game Rules native box_w
# the measured NATIVE type-1 local rect (pristine trace: container 7..670)
LOCAL_1024 = {"l": 7, "t": 27, "r": 670, "b": 713}
# v17: the real helpers the hug arm calls (their own g read is the real g_popup_scale_num VA) and the popup's
# Dialog behind [popup+0x21d0] (iv3 = the measured 0xBA0; the vbase object in the same page)
G_REAL = BW.G_SCALE            # 0x668740
IV3 = 0xBA0
IVOBJ = POPUP + 0x2F00
DLG = POPUP + 0x21D0 + IV3     # 0x302D70: +0x20 flags, +0x2c xs, +0x30 fixed_h, +0x40 m, +0x44 gap, +0xcc rows
# the census popup list as calc_reserve leaves it (Customize Game Rules: #xs 440 x1.5, margin 0, 18 rows, the
# rowgap'd gap fl(3g/16) on the else-path); [+0x5c] (and so D.r) is the calc's MEASURED width at draw time
T1_DLG = {"flags": 0, "xs": 660, "fixed_h": 0, "margin": 0, "rows": 18}
# v15: the caller's frame (Popup_on_draw_background ebp) and the engine dialog rect D it holds at
# [ebp-0x44] l / [ebp-0x40] t / [ebp-0x3c] r / [ebp-0x38] b (0x40619D..0x4061AD) -- the 4K Customize Game Rules list
FRAME_EBP = 0x00200800
D_4K = {"l": 25, "t": 95, "r": 1667, "b": 887}


def _blob(asm: str, addr: int) -> bytes:
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    code, _ = ks.asm(asm, addr=addr)
    return bytes(code)


@pytest.fixture(scope="module")
def uc():
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base in (CODE_UNION & ~(PAGE - 1), SENT_PAGE, POPUP, POPUP + 0x2000,
                 POPUP + 0x3000, FACTION_POPUP & ~(PAGE - 1), RECT, STACK, BW.HELPER_VA & ~(PAGE - 1),
                 G_REAL & ~(PAGE - 1)):
        mu.mem_map(base, PAGE)
    mu.mem_write(BW.HELPER_VA, BW.hb)
    mu.mem_write(BW.CORE_VA, BW.cb)
    mu.mem_write(CODE_UNION, _blob(gen.ASM_UNION, CODE_UNION))
    mu.mem_write(CODE_FRAME, _blob(gen.ASM_FRAME, CODE_FRAME))
    mu.mem_write(CODE_TEXT, _blob(gen.ASM_TEXTFOLLOW, CODE_TEXT))
    return mu


def _run(uc, code, tail, g, *, esi=POPUP, a14=0, art=0, dlg=0, sw=3840,
         local=LOCAL, ptype=0, bodyh=0, title=1, margin=0, margin_r=None, title_r=None, d=D_4K, dlgf=None,
         title_l=None):
    def w4(addr, v):
        uc.mem_write(addr, int(v).to_bytes(4, "little", signed=True))

    for i, k in enumerate(("l", "t", "r", "b")):                # the caller's dialog rect D (v15 hug arm)
        w4(FRAME_EBP - 0x44 + 4 * i, d[k])
    uc.reg_write(UC_X86_REG_EBP, FRAME_EBP)

    w4(G_ADDR, g)
    w4(G_REAL, g)
    w4(TITLE_L, T_L if title_l is None else title_l)
    w4(TITLE_R, T_R if title_r is None else title_r)
    w4(SCREEN_W, sw)                                # v5 native-fix regime gate
    for k, addr in list(UNION.items()) + list(ALIGN.items()):
        w4(addr, -0x55555556)                       # poison the scratch
    w4(D528_LEFT, -0x55555556)
    w4(D528_KEY, 0x77777777)                        # stale key: every frame entry must clear it
    if esi == POPUP:
        w4(esi + 0xA14, a14)
        w4(esi + 0x2144, art)
        w4(esi + 0x2350, dlg)                       # dlg_type (type-1 arms)
        w4(esi + 0x30BC, BOXW)                      # box_w (v5 native fix)
        w4(esi + 0x30AC, ptype * 10000)             # popup type (v8 gate)
        w4(esi + 0x30D4, bodyh)                     # body text-box h (v9 arm)
        w4(esi + 0xA48, title)                      # title string ptr (v9 arm)
        w4(esi + 0x30F0, margin)                    # content margin (v9 frame ornate arm)
        w4(esi + 0x30F4, (19 * g) >> 4 if margin_r is None else margin_r)   # right margin (v14 picker arm; canonical by default)
        f = dict(T1_DLG, gap=(3 * g) >> 4)                                     # v17: the type-1 Dialog
        f.update(dlgf or {})
        w4(esi + 0x21D0, IVOBJ)
        w4(IVOBJ + 8, IV3)
        for off, k in ((0x20, "flags"), (0x2C, "xs"), (0x30, "fixed_h"), (0x40, "margin"), (0x44, "gap"),
                       (0xCC, "rows")):
            w4(DLG + off, f[k])
    for i, k in enumerate(("l", "t", "r", "b")):
        w4(RECT + 4 * i, local[k])

    sp = STACK + PAGE - 0x20
    w4(sp, RETADDR)
    w4(sp + 4, RECT)
    w4(sp + 8, 0x0078D5A0)
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.reg_write(UC_X86_REG_ESI, esi)
    uc.reg_write(UC_X86_REG_ECX, 0x00C0FFEE)

    uc.emu_start(code, tail, count=256)             # stops AT the tail target

    assert uc.reg_read(UC_X86_REG_EIP) == tail
    assert uc.reg_read(UC_X86_REG_ECX) == 0x00C0FFEE, "clobbered ecx (dest this)"
    assert uc.reg_read(UC_X86_REG_ESI) == esi, "clobbered esi (popup)"
    assert uc.reg_read(UC_X86_REG_EBP) == FRAME_EBP, "clobbered ebp (the caller's frame)"
    esp = uc.reg_read(UC_X86_REG_ESP)
    rect_arg = int.from_bytes(uc.mem_read(esp + 4, 4), "little")
    def r4(addr):
        return int.from_bytes(uc.mem_read(addr, 4), "little", signed=True)
    return rect_arg, r4


@pytest.mark.parametrize("g", range(17, 41))
def test_union_no_art_matches_the_law(uc, g):
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g)
    assert rect_arg == UNION["l"], "rect arg not repointed to the union scratch"
    assert r4(UNION["l"]) == body_outer_edge_l(T_L, g)
    assert r4(UNION["r"]) == body_outer_edge_r(T_R, g)
    assert r4(UNION["t"]) == LOCAL["t"] and r4(UNION["b"]) == LOCAL["b"]


@pytest.mark.parametrize("g", range(17, 41))
def test_union_art_keeps_local_left_and_aligns_right(uc, g):
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, art=0x03B38F58)
    assert rect_arg == UNION["l"]
    assert r4(UNION["l"]) == LOCAL["l"], "art popup must keep its art-aware left"
    assert r4(UNION["r"]) == body_outer_edge_r(T_R, g)


@pytest.mark.parametrize("g", range(17, 41))
def test_frame_no_art_matches_the_law(uc, g):
    rect_arg, r4 = _run(uc, CODE_FRAME, TAIL_FRAME, g)
    assert rect_arg == ALIGN["l"]
    assert r4(ALIGN["l"]) == body_inner_edge_l(T_L, g)
    assert r4(ALIGN["r"]) == body_inner_edge_r(T_R, g)
    assert r4(ALIGN["t"]) == LOCAL["t"] and r4(ALIGN["b"]) == LOCAL["b"]
    assert r4(D528_LEFT) == r4(ALIGN["l"])


@pytest.mark.parametrize("g", range(17, 41))
def test_frame_art_keeps_local_left_and_aligns_right(uc, g):
    rect_arg, r4 = _run(uc, CODE_FRAME, TAIL_FRAME, g, art=1)
    assert rect_arg == ALIGN["l"]
    assert r4(ALIGN["l"]) == LOCAL["l"]
    assert r4(ALIGN["r"]) == body_inner_edge_r(T_R, g)


@pytest.mark.parametrize("g", range(17, 41))
def test_the_pair_keeps_the_channel_fix(uc, g):
    """The 2026-07-09 channel fix must survive: outer - inner == popup_pad(3)."""
    from scaling_laws import popup_pad
    _, r4u = _run(uc, CODE_UNION, TAIL_UNION, g, art=1)
    outer_r = r4u(UNION["r"])
    _, r4f = _run(uc, CODE_FRAME, TAIL_FRAME, g, art=1)
    assert outer_r - r4f(ALIGN["r"]) == popup_pad(3, g)


@pytest.mark.parametrize("code,tail", [(CODE_UNION, TAIL_UNION), (CODE_FRAME, TAIL_FRAME)])
@pytest.mark.parametrize("gate", ["native_g", "faction", "concentric"])
def test_gates_pass_through_untouched(uc, code, tail, gate):
    kw = {"native_g": dict(g=NATIVE_G),
          "faction": dict(g=40, esi=FACTION_POPUP),
          "concentric": dict(g=40, a14=1)}[gate]
    g = kw.pop("g")
    rect_arg, r4 = _run(uc, code, tail, g, **kw)
    assert rect_arg == RECT, f"{gate}: rect arg was repointed on a passthrough"
    for addr in list(UNION.values()) + list(ALIGN.values()) + [D528_LEFT]:
        assert r4(addr) == -0x55555556, f"{gate}: scratch written on a passthrough"


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("dlg", (4,))
def test_union_container_arm_is_title_inner_derived(uc, g, dlg):
    """The container arm (v6 the #FACTION type-2 listbox; v7 the type-4
    base-name FIELD ring; type 1 left it for the v15 hug arm, the flat /
    slide type 2 for the v18 hug arm -- test_v18_type2_ring_hugs_the_list_window):
    dlg_type 4 + no-art -> the ring is collinear with the title's INNER ring,
    BOTH edges (v5: the v4 -floor(2g/16) faithfully scaled vanilla's -2,
    which is the >1023-regime bug that parks the stroke under the itemlist
    rows; type-2 pristine-1024 measure: ring x=514 == title inner EXACT;
    type-4 pristine-1024 NameBase.png: field left == title inner native 268
    EXACT, right = inner-2 — same accepted symmetric form ships)."""
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=dlg)
    assert rect_arg == UNION["l"]
    assert r4(UNION["l"]) == itemlist_container_edge_l(T_L, g)
    assert r4(UNION["r"]) == itemlist_container_edge_r(T_R, g)
    assert r4(UNION["t"]) == LOCAL["t"] and r4(UNION["b"]) == LOCAL["b"]
    # strictly INSIDE the quit-family outer-flush edges at every g
    assert r4(UNION["l"]) > body_outer_edge_l(T_L, g)
    assert r4(UNION["r"]) < body_outer_edge_r(T_R, g)
    # symmetric: same pad from both title-outer edges
    assert r4(UNION["l"]) - T_L == T_R - r4(UNION["r"])


def _want_hug(d: dict, g: int, f: dict) -> tuple:
    """The v17 law: l/t/b from D, r from the list law (itemlist_ring_list_r), then -+ ps3 (itemlist_ring_hug)."""
    r = itemlist_ring_list_r(d["l"], d["r"], f["xs"], f["margin"], 1, f["gap"], f["flags"], f["fixed_h"], f["rows"], g)
    return itemlist_ring_hug(d["l"], d["t"], r, d["b"], g)


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (0, 5, 2, 6, 12, 10, 1000))
@pytest.mark.parametrize("d", (D_4K, {"l": 82, "t": 95, "r": 1724, "b": 887}, {"l": 13, "t": 52, "r": 916, "b": 484},
                               {"l": 47, "t": 117, "r": 1689, "b": 909}))
def test_v17_type1_ring_hugs_the_list(uc, g, ptype, d):
    """v15 (fix 16, user decision "Hug the list") + v16 (fix 17, all four sides) + v17 (fix 18): a type-1 list
    with no art and no body text takes l/t = D.l/D.t - ps3, b = D.b + ps3 - 1 from the caller's dialog rect and
    r = (D.l + the list window w) + ps3 - 1 (laws itemlist_ring_list_r / itemlist_ring_hug), in EVERY popup
    family -- flat 0, slide 5, ornate 2/6, and raw types outside every band (vanilla's D path never reads
    [+0x30ac]).  D.r is NOT the list here: this draw runs at 0x602B49, before the attach, so D.r = D.l +
    calc_reserve's measured [+0x5c] (the D.r values in these rects are post-attach widths, poison for v17).
    Neither the title stash nor the engine local is read."""
    assert itemlist_ring_takes_hug_arm(1, 0, 0)
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=1, ptype=ptype, d=d)
    assert rect_arg == UNION["l"]
    l, t, r, b = (r4(UNION[k]) for k in ("l", "t", "r", "b"))
    f = dict(T1_DLG, gap=(3 * g) >> 4)
    assert (l, t, r, b) == _want_hug(d, g, f)
    ps3 = (3 * g) >> 4
    list_w = (657 * g) >> 4                                                      # s(vanilla [+0x5c]) = s(xs - 3)
    assert d["l"] - l == d["t"] - t == r + 1 - (d["l"] + list_w) == b + 1 - d["b"] == ps3   # drawn insets
    assert t != LOCAL["t"] and b != LOCAL["b"]                                   # not the v15 engine local
    assert (l, r) != (itemlist_container_edge_l(T_L, g), itemlist_container_edge_r(T_R, g))


@pytest.mark.parametrize("g", (17, 18, 22, 25, 30, 40))
@pytest.mark.parametrize("dr", (25 + 890, 25 + 657, 25 + 2000, -0x1000))
def test_v17_hug_right_edge_ignores_the_pre_attach_d_r(uc, g, dr):
    """The 0x602B49 draw sees D.r = D.l + calc_reserve's measured width (890 at 4K Customize Game Rules, the
    device text): whatever it holds, a multi-row list's ring right edge is D.l + s(vanilla [+0x5c]) + ps3 - 1."""
    d = dict(D_4K, r=dr)
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=1, d=d)
    assert r4(UNION["r"]) == D_4K["l"] + ((657 * g) >> 4) + ((3 * g) >> 4) - 1


@pytest.mark.parametrize("g", (17, 22, 25, 40))
@pytest.mark.parametrize("f", (
    {"rows": 1}, {"rows": 0}, {"rows": 2},                                       # single row: D.r as is
    {"flags": 3, "fixed_h": 300, "gap": 6, "xs": 457},                            # PrefWin-shaped: fixed, w = xs
    {"flags": 2, "xs": 440},                                                      # flags&2 without the height
    {"flags": 1, "fixed_h": 300, "gap": 3},                                       # fixed-height: gap as read
    {"margin": 3},                                                                # + 2m
    {"gap": 5},                                                                   # a foreign gap: as read
))
def test_v17_hug_right_edge_follows_the_list_law(uc, g, f):
    """Every gate of the attach's law (thunk_list_fill_width: > 1 row, fixed width, the native-gap read-back)
    applies to the ring through the shared t_t1_list_w, so the ring right edge == D.l + the list window w."""
    full = dict(T1_DLG, gap=(3 * g) >> 4)
    full.update(f)
    d = dict(D_4K, r=D_4K["l"] + 890)                                            # the pre-attach (calc) D.r
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=1, d=d, dlgf=f)
    want = _want_hug(d, g, full)
    assert tuple(r4(UNION[k]) for k in ("l", "t", "r", "b")) == want, (g, f)
    if full["rows"] <= 1:
        assert r4(UNION["r"]) == d["r"] + ((3 * g) >> 4) - 1                    # the attach keeps [+0x5c]


@pytest.mark.parametrize("g", (17, 22, 25, 40))
def test_v16_hug_reads_d_not_the_local(uc, g):
    """The hug ring follows D on l/t/b and ignores the local rect: two runs that differ only in the local give
    the same ring; two runs that differ only in D.t / D.b move only t / b; moving D.l moves l and r together."""
    d = dict(D_4K)
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=1, d=d)
    base = [r4(UNION[k]) for k in ("l", "t", "r", "b")]
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=1, d=d, local={"l": 1, "t": 2, "r": 3, "b": 4})
    assert [r4(UNION[k]) for k in ("l", "t", "r", "b")] == base
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=1, d=dict(d, t=d["t"] + 40, b=d["b"] + 300))
    assert [r4(UNION[k]) for k in ("l", "t", "r", "b")] == [base[0], base[1] + 40, base[2], base[3] + 300]
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=1, d=dict(d, l=d["l"] + 57))
    assert [r4(UNION[k]) for k in ("l", "t", "r", "b")] == [base[0] + 57, base[1], base[2] + 57, base[3]]


# D rects of the type-2 listbox as the 0x602B49 draw sees them (real-image Unicorn, popup_listbox_emu): Go To at 4K /
# 1600x900 / 1080, the editor unit list (ornate in game; its D shape reused here under a flat family)
D_T2 = ({"l": 82, "t": 95, "r": 1882, "b": 652}, {"l": 37, "t": 42, "r": 847, "b": 291},
        {"l": 45, "t": 52, "r": 1035, "b": 360}, {"l": 47, "t": 117, "r": 1697, "b": 674})


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (0, 5))
@pytest.mark.parametrize("d", D_T2)
def test_v18_type2_ring_hugs_the_list_window(uc, g, ptype, d):
    """v18 (F34, law listbox_ring_takes_hug_arm): a flat / slide type-2 listbox with no art and no body text takes
    the type-1 hug -- l/t = D.l/D.t - ps3, r/b = D.r/D.b + ps3 - 1 (itemlist_ring_hug) -- with D.r AS IS (the type-2
    calc wrote [+0x5c] = the list width before the draw), never the title stash (v7..v17: title inner) nor the
    engine local.  The drawn insets are ps3 on all four sides."""
    assert listbox_ring_takes_hug_arm(2, 0, 0, ptype * 10000)
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=2, ptype=ptype, d=d)
    assert rect_arg == UNION["l"]
    l, t, r, b = (r4(UNION[k]) for k in ("l", "t", "r", "b"))
    assert (l, t, r, b) == itemlist_ring_hug(d["l"], d["t"], d["r"], d["b"], g)
    ps3 = (3 * g) >> 4
    assert d["l"] - l == d["t"] - t == r + 1 - d["r"] == b + 1 - d["b"] == ps3
    assert (l, r) != (itemlist_container_edge_l(T_L, g), itemlist_container_edge_r(T_R, g))


@pytest.mark.parametrize("g", (17, 18, 22, 25, 40))
@pytest.mark.parametrize("f", ({"rows": 0}, {"rows": 1}, {"rows": 12}, {"rows": 40}, {"flags": 3, "xs": 457},
                               {"margin": 3}))
def test_v18_type2_keeps_d_r_whatever_the_dialog_fields(uc, g, f):
    """The type-1 list-law term (t_boxw_t1_term) is skipped for type 2: whatever rows / flags / xs / margin the
    Dialog holds, r == D.r + ps3 - 1 (a D.r the list law would never produce proves it)."""
    d = dict(D_T2[0], r=D_T2[0]["l"] + 1801)
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=2, d=d, dlgf=f)
    assert r4(UNION["r"]) == d["r"] + ((3 * g) >> 4) - 1
    assert r4(UNION["l"]) == d["l"] - ((3 * g) >> 4)


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (2, 6))
def test_v18_ornate_type2_picker_unchanged(uc, g, ptype):
    """The ornate type-2 picker (EDITORWHO / SELECT A FACTION, the stack picker, the editor unit list) keeps fix
    26's arm: l = ornate_container_edge_l, r = ornate_picker_container_edge_r, t/b = the engine local."""
    assert not listbox_ring_takes_hug_arm(2, 0, 0, ptype * 10000)
    assert ornate_picker_takes_container_arm(ptype * 10000, 2, 0, 0, 1)
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=2, ptype=ptype)
    assert r4(UNION["l"]) == ornate_container_edge_l(T_L, g)
    assert r4(UNION["r"]) == ornate_picker_container_edge_r(T_R, (19 * g) >> 4, g)
    assert r4(UNION["t"]) == LOCAL["t"] and r4(UNION["b"]) == LOCAL["b"]


def test_v18_union_yaml_bytes_are_the_assembler_output():
    """The shipped thunk_pf_union_align content == assemble_pf_align's v18 template at its slot (the hug arm's
    call is {rel32:t_boxw_t1_term}), and it ends inside its W2B slot (0x35000..0x35300, before
    thunk_title_hmargin v2)."""
    import re
    yaml_text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r"- id: thunk_pf_union_align\s+offset: 0x35000\s+bytes: \"([^\"]+)\"", yaml_text)
    assert m, "thunk_pf_union_align content entry not found at 0x35000"
    assert re.search(r"thunk_pf_union_align:\s+\{ cave: pcave2, offset: 0x35000 \}", yaml_text)
    assert gen.UNION_VA == 0x00A0C000 + 0x35000
    blob, tmpl = gen.template(gen.ASM_UNION, gen.UNION_VA)
    assert " ".join(m.group(1).split()) == tmpl
    assert "E8 {rel32:t_boxw_t1_term}" in tmpl
    assert gen.UNION_VA + len(blob) <= gen.UNION_SLOT_END


@pytest.mark.parametrize("g", (17, 22, 25, 40))
@pytest.mark.parametrize("case", ["art", "body_text", "dlg2_ornate2", "dlg2_ornate6", "dlg2_art", "dlg2_body",
                                  "dlg4", "dlg8", "dlg16", "none"])
def test_v15_hug_arm_gate(uc, g, case):
    """Only dlg 1 + no art + no body text (v15) and the flat / slide dlg 2 + no art + no body text (v18) hug;
    every other shape keeps its v14 outcome (the D rect is poisoned here: reading it on any other shape would
    show) -- incl. the ORNATE type-2 picker (fix 26's arm) and a type 2 with art or body text."""
    kw = {"art": dict(dlg=1, art=1), "body_text": dict(dlg=1, bodyh=52), "dlg2_ornate2": dict(dlg=2, ptype=2),
          "dlg2_ornate6": dict(dlg=2, ptype=6), "dlg2_art": dict(dlg=2, art=1), "dlg2_body": dict(dlg=2, bodyh=52),
          "dlg4": dict(dlg=4), "dlg8": dict(dlg=8), "dlg16": dict(dlg=16), "none": dict(dlg=-1)}[case]
    assert not itemlist_ring_takes_hug_arm(kw["dlg"], kw.get("bodyh", 0), kw.get("art", 0))
    assert not listbox_ring_takes_hug_arm(kw["dlg"], kw.get("bodyh", 0), kw.get("art", 0),
                                          kw.get("ptype", 0) * 10000)
    poison = {"l": -0x1000, "t": -0x1000, "r": -0x1000, "b": -0x1000}
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, d=poison, **kw)
    _, r4c = _run(uc, CODE_UNION, TAIL_UNION, g, **kw)               # the same shape, a real D
    assert [r4(a) for a in UNION.values()] == [r4c(a) for a in UNION.values()]
    assert all(abs(r4(a)) < 0x800 for a in UNION.values())


@pytest.mark.parametrize("sw", (800, 1024, 1280, 1366, 3840))
@pytest.mark.parametrize("ptype", (0, 5, 6))
@pytest.mark.parametrize("case", ["type1", "type2", "type4", "art", "faction", "concentric", "body_text"])
def test_v15_g16_passes_every_popup_through(uc, sw, ptype, case):
    """g <= 16 is the engine's ring, bit-true, on every screen width (v5-v14 redrew the type-1 right
    stroke at boxw-7 when ScreenWidth > 0x3FF: 750 vs vanilla 693 in game at 1024x768; its rows-under-
    the-stroke premise was thunk_list_fill_width firing at g=16, fix 10)."""
    kw = {"type1": dict(dlg=1), "type2": dict(dlg=2), "type4": dict(dlg=4), "art": dict(dlg=1, art=1),
          "body_text": dict(dlg=1, bodyh=31), "faction": dict(dlg=1, esi=FACTION_POPUP),
          "concentric": dict(dlg=1, a14=1)}[case]
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, NATIVE_G, local=LOCAL_1024, sw=sw, ptype=ptype, **kw)
    assert rect_arg == RECT, f"{case}: rect arg repointed at g=16"
    for addr in UNION.values():
        assert r4(addr) == -0x55555556, f"{case}: scratch written at g=16"


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("dlg", (1, 2, 4))
def test_union_container_types_with_art_fall_to_the_quit_law(uc, g, dlg):
    """Type-1/2/4 WITH art keep today's behavior — the arm is no-art-gated."""
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=dlg, art=1)
    assert r4(UNION["l"]) == LOCAL["l"]
    assert r4(UNION["r"]) == body_outer_edge_r(T_R, g)


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("dlg", (1, 2, 4))
def test_v11_union_with_body_text_nests_the_text_box_on_the_outer_column(uc, g, dlg):
    """Body text + list/field, no art = the engine's UnionRect path: the ring
    sits one stroke pitch OUTSIDE the d528 text box on the title OUTER column
    (pristine BlindResearch.png: ring box+4, text box box+7 == the title
    pair), and its top takes ps3 instead of the list pad. v10 drew it on the
    inner column, over the text box (4K shot 20261003-233707)."""
    from scaling_laws import (popup_pad, union_ring_takes_container_arm,
                              union_ring_top)
    assert not union_ring_takes_container_arm(dlg, 52, 0)
    assert union_ring_takes_container_arm(dlg, 0, 0)
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, dlg=dlg, bodyh=52)
    assert rect_arg == UNION["l"]
    assert r4(UNION["l"]) == body_outer_edge_l(T_L, g)
    assert r4(UNION["r"]) == body_outer_edge_r(T_R, g)
    assert r4(UNION["t"]) == union_ring_top(LOCAL["t"], g)
    assert r4(UNION["b"]) == LOCAL["b"]
    # one stroke pitch outside the d528 text box on both sides
    _, r4f = _run(uc, CODE_FRAME, TAIL_FRAME, g, dlg=dlg, bodyh=52)
    assert r4f(ALIGN["l"]) - body_outer_edge_l(T_L, g) == popup_pad(3, g)
    assert body_outer_edge_r(T_R, g) - r4f(ALIGN["r"]) == popup_pad(3, g)


@pytest.mark.parametrize("dlg", (0, -1, 5, 16))
@pytest.mark.parametrize("bodyh", (0, 52))
def test_v11_other_dialog_types_keep_their_top(uc, dlg, bodyh):
    """The top-pitch rewrite belongs to the UnionRect path of types 1/2/4
    only; quit/plain popups keep local.t whatever their body height."""
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, 40, dlg=dlg, bodyh=bodyh)
    assert r4(UNION["t"]) == LOCAL["t"]


@pytest.mark.parametrize("dlg", (0, -1, 5, 16))
def test_union_other_dialog_types_keep_v3_semantics(uc, dlg):
    """Quit(16)/plain(-1/0) + the v7 gate edge (5) must be byte-for-byte v3
    outcomes (dec/cmp 3/ja: -1/0 wrap unsigned, 5/16 exceed; type 4 moved to
    the container arm in v7, type 3 does not exist in Dialog_set_type)."""
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, 40, dlg=dlg)
    assert r4(UNION["l"]) == body_outer_edge_l(T_L, 40)
    assert r4(UNION["r"]) == body_outer_edge_r(T_R, 40)


def test_the_4k_quit_modal_regression_case(uc):
    """The report itself: g=40, art popup. The union right must land the body's
    drawn stroke exactly on the title's drawn stroke (title rect + delta 3) —
    4px right of where the engine's floor-composed path put it (screenshot
    columns 2752 vs 2756).

    Engine path (pre-fix): ring R = title_R + pad(4) - pad(10) + 2*pad(3),
    drawn FLAT. At g=40 that is T_R + 10 - 25 + 14 = T_R - 1 while the title
    draws at T_R + 3.
    """
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, 40, art=1)
    # 2026-09-18: the title draws FLAT (title_grow_delta == 0) -> flush == the title RECT edge
    assert r4(UNION["r"]) == T_R
    engine_ring_r = T_R + 10 - 25 + 2 * 7
    assert engine_ring_r == T_R - 1
    assert r4(UNION["r"]) - engine_ring_r == 1          # what is left is the engine floor lag

# ---------------------------------------------------------------------------
# v8 popup-type gate (2026-08-01, stack-picker frame report)
# v9 ornate picker container arm (2026-08-01b: the title keeps its engine
# geometry — user rejected the title rewrite — and the picker FRAME takes
# the same title-INNER container relation as types 1/2/4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ptype", (2, 6, 1000))
@pytest.mark.parametrize("g", (17, 22, 25, 40))
def test_v8_frame_ornate_types_pass_through_untouched(uc, ptype, g):
    """The d528 FRAME thunk keeps the v8 gate: ornate types never take its
    flat rewrite (pickers have no body box).  Since v9 an ornate popup whose
    margin is the canonical fl(19g/16) takes the LEFT-only ornate arm (tests
    below); here the margin field is 0, so the identity gate passes it through.
    The engine's d528 comes from the content-margin sum [popup+0x30f0],
    which already scales (trace 47@g40 / 29@g25 ~= 19 native x g/16)."""
    rect_arg, r4 = _run(uc, CODE_FRAME, TAIL_FRAME, g, ptype=ptype)
    assert rect_arg == RECT, f"type {ptype}: rect arg repointed"
    for addr in list(ALIGN.values()) + [D528_LEFT]:
        assert r4(addr) == -0x55555556, f"type {ptype}: scratch written"


# ---------------------------------------------------------------------------
# v9 FRAME ornate arm (2026-10-11): the ornate d528 text box's LEFT edge moves
# from the engine's fl(19g/16) - ps3 (1 px right of the title inner) onto
# stash + ps3, by mutating the engine LOCAL (not a repoint).
# ---------------------------------------------------------------------------
from scaling_laws import (  # noqa: E402
    nested_frame_pad, ornate_text_box_edge_l, ornate_text_box_takes_inner_arm, popup_pad,
    popup_scale_floor,
)


def _ornate_local(g, extra=0):
    m = popup_scale_floor(19, g)
    return m, {"l": m - popup_pad(3, g) + extra, "t": 80, "r": 1700, "b": 152}


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (2, 6))
@pytest.mark.parametrize("extra", (0, 9))
def test_v9_frame_ornate_text_box_left_lands_on_the_title_inner(uc, g, ptype, extra):
    m, local = _ornate_local(g, extra)
    assert ornate_text_box_takes_inner_arm(ptype * 10000, 0, 1, m, g)
    rect_arg, r4 = _run(uc, CODE_FRAME, TAIL_FRAME, g, ptype=ptype, local=local, margin=m, bodyh=50)
    assert rect_arg == RECT, "the ornate arm mutates the local, it must not repoint"
    got = {k: r4(RECT + 4 * i) for i, k in enumerate(("l", "t", "r", "b"))}
    # _run re-seeds TITLE_L with the module T_L, so the law is evaluated on that stash
    assert got["l"] == ornate_text_box_edge_l(local["l"], m, T_L, g)
    assert got["l"] == body_inner_edge_l(T_L, g) + extra       # content_off_x / pad_x addends kept
    assert (got["t"], got["r"], got["b"]) == (local["t"], local["r"], local["b"])
    for addr in ALIGN.values():
        assert r4(addr) == -0x55555556, "ornate arm must not touch the flat scratch"
    assert r4(D528_LEFT) == got["l"], "the moved box left feeds the body text (textfollow v3)"
    assert r4(D528_KEY) == POPUP, "the text key names THIS popup"


@pytest.mark.parametrize("g", range(17, 41))
def test_v9_the_pre_fix_lag_is_one_floor(g):
    """The defect the arm removes: margin fl(19g/16) - 2*ps3 - stash fl(13g/16) = 1 at every g in
    17..40 except 32 (0).  The ring/text consequences run on the REAL patched bytes in
    test_v9_chain_real_bytes_* below."""
    lag = popup_scale_floor(19, g) - 2 * popup_pad(3, g) - popup_scale_floor(13, g)
    assert lag == (0 if g == 32 else 1)


def test_v9_frame_ornate_measured_renames():
    """#RENAME shots: 4K (title stash 1078 abs, inner 1085, box 1086 -> 1085); 1600x1200 (274 / 278,
    box 279 -> 278).  Popup-local stash s(13), margin fl(19g/16)."""
    for g, inner_abs, box_abs in ((40, 1085, 1086), (25, 278, 279)):
        m, local = _ornate_local(g)
        stash = popup_scale_floor(13, g)
        org = inner_abs - (stash + popup_pad(3, g))         # the popup's screen x
        assert org + local["l"] == box_abs                   # the engine box as measured
        assert org + ornate_text_box_edge_l(local["l"], m, stash, g) == inner_abs


@pytest.mark.parametrize("case", ["g16", "art", "no_title", "margin_off", "type1000", "type1", "faction",
                                  "concentric"])
def test_v9_frame_ornate_gates_pass_through_untouched(uc, case):
    g = 16 if case == "g16" else 40
    m, local = _ornate_local(g)
    kw = dict(ptype=6, local=local, margin=m, bodyh=50)
    kw.update({"g16": {}, "art": dict(art=0x1234), "no_title": dict(title=0),
               "margin_off": dict(margin=m + 1), "type1000": dict(ptype=1000), "type1": dict(ptype=1),
               "faction": dict(esi=FACTION_POPUP), "concentric": dict(a14=1)}[case])
    rect_arg, r4 = _run(uc, CODE_FRAME, TAIL_FRAME, g, **kw)
    assert rect_arg == RECT
    assert r4(RECT) == local["l"], f"{case}: local left mutated"
    for addr in list(ALIGN.values()) + [D528_LEFT]:
        assert r4(addr) == -0x55555556, f"{case}: scratch written"
    assert r4(D528_KEY) == 0, f"{case}: stale text key survived a frame entry"


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (2, 6))
@pytest.mark.parametrize("dlg", (1, 2, 4, 8, 16))
def test_v13_ornate_dialog_with_body_text_nests_the_text_box(uc, g, ptype, dlg):
    """Ornate + live dialog + body text box (base-screen #RENAME: type
    60000, dlg 4, body 50 @g40) = the engine's UnionRect path: ring on the
    title OUTER column (the stash), top pitch ps3; bottom stays local."""
    from scaling_laws import ornate_union_takes_outer_arm, union_ring_top
    assert ornate_union_takes_outer_arm(ptype * 10000, dlg, 50, 0, 1)
    assert not ornate_picker_takes_container_arm(ptype * 10000, dlg, 50, 0, 1)
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, ptype=ptype, dlg=dlg, bodyh=50)
    assert rect_arg == UNION["l"]
    assert r4(UNION["l"]) == body_outer_edge_l(T_L, g) == T_L
    assert r4(UNION["r"]) == body_outer_edge_r(T_R, g) == T_R
    assert r4(UNION["t"]) == union_ring_top(LOCAL["t"], g)
    assert r4(UNION["b"]) == LOCAL["b"]


@pytest.mark.parametrize("case", ["hidden", "dlg_none", "body_no_dlg", "art", "body_art", "no_title",
                                  "body_no_title"])
@pytest.mark.parametrize("ptype", (2, 6))
def test_v9_union_non_picker_ornate_shapes_pass_through(uc, case, ptype):
    """Ornate popups OUTSIDE the picker / UnionRect shapes keep the engine's
    arithmetic: hidden sentinel (1000), no live dialog (with or without a
    body box), with art, or without a title (no stash this call — it could
    be stale from a previous popup)."""
    kw = {"hidden": dict(ptype=1000, dlg=8),
          "dlg_none": dict(ptype=ptype, dlg=-1),
          "body_no_dlg": dict(ptype=ptype, dlg=-1, bodyh=120),
          "body_art": dict(ptype=ptype, dlg=8, bodyh=120, art=0x03B38F58),
          "body_no_title": dict(ptype=ptype, dlg=8, bodyh=120, title=0),
          "art": dict(ptype=ptype, dlg=8, art=0x03B38F58),
          "no_title": dict(ptype=ptype, dlg=8, title=0)}[case]
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, 40, **kw)
    assert rect_arg == RECT, f"{case}: rect arg repointed"
    for addr in list(UNION.values()) + [D528_LEFT]:
        assert r4(addr) == -0x55555556, f"{case}: scratch written"


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (2, 6))
def test_v10_ornate_picker_takes_its_own_container_arm(uc, g, ptype):
    """The picker shape (type 6/2, live dialog, no body box, no art, titled)
    takes l/r = title stash -+ (ps3 - delta) — laws ornate_container_edge_l/r
    (v10, 2026-08-01f "not quite flush"): the ornate title strokes render
    GROWN by frame_grow_delta via thunk_box_thick while the container draws
    FLAT, so the flat rect pre-subtracts delta to land on the DRAWN inner
    stroke (v9's borrowed flat-title arm sat delta INSIDE it — measured
    +-3 @g40, symmetric). t/b stay engine."""
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, ptype=ptype, dlg=8)
    assert rect_arg == UNION["l"]
    assert r4(UNION["l"]) == ornate_container_edge_l(T_L, g)
    assert r4(UNION["r"]) == ornate_container_edge_r(T_R, g)
    assert r4(UNION["t"]) == LOCAL["t"] and r4(UNION["b"]) == LOCAL["b"]
    # strictly INSIDE the quit-family outer-flush edges (the v8 defect drew
    # the picker frame ON the title outer column)
    assert r4(UNION["l"]) > body_outer_edge_l(T_L, g)
    assert r4(UNION["r"]) < body_outer_edge_r(T_R, g)
    # symmetric: same pad from both title-outer edges
    assert r4(UNION["l"]) - T_L == T_R - r4(UNION["r"])
    # identity vs the v9 form wherever delta == 0 (all g < 24)
    if g < 24:
        assert r4(UNION["l"]) == itemlist_container_edge_l(T_L, g)
        assert r4(UNION["r"]) == itemlist_container_edge_r(T_R, g)
    # 2026-09-18: flat title -> the ornate arm == the v9 form at every g
    if g == 40:
        assert itemlist_container_edge_l(T_L, g) == r4(UNION["l"])
        assert r4(UNION["r"]) == itemlist_container_edge_r(T_R, g)


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (2, 6))
@pytest.mark.parametrize("mnat", (19, 21, 24, 15))
def test_v14_ornate_picker_right_edge_follows_the_right_margin(uc, g, ptype, mnat):
    """v14 (2026-10-16, SELECT A FACTION): vanilla's list ring R = box_w - margin_r + 3, flush with
    the title inner only for the canonical 19 margin; the arm subtracts the scaled excess
    [+0x30f4] - fl(19g/16) (law ornate_picker_container_edge_r).  Left edge, t/b unchanged."""
    mr = (mnat * g) >> 4
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, ptype=ptype, dlg=8, margin_r=mr)
    assert rect_arg == UNION["l"]
    assert r4(UNION["r"]) == ornate_picker_container_edge_r(T_R, mr, g)
    assert r4(UNION["r"]) == ornate_container_edge_r(T_R, g) - (mr - ((19 * g) >> 4))
    assert r4(UNION["l"]) == ornate_container_edge_l(T_L, g)
    assert r4(UNION["t"]) == LOCAL["t"] and r4(UNION["b"]) == LOCAL["b"]
    if mnat == 19:
        assert r4(UNION["r"]) == ornate_container_edge_r(T_R, g)        # canonical: no change


@pytest.mark.parametrize("g", range(17, 41))
def test_v14_select_a_faction_ring_is_symmetric_after_fix26(uc, g):
    """SELECT A FACTION as it reaches the arm since fix 26 v2 (ornate_popup_margin_r + ORNATE_HALF_OPEN): margins
    19 | 19 at g > 16 (box 19 + 597 + 19), title stash L = s(13), R = box_w - 1 - s(13) (thunk_pf_title_stash v9).
    The ring then hugs the title inner on BOTH sides and mirrors its left edge about the half-open axis:
    R == box_w - 1 - L (stroke columns L.. and ..R), and the v14 excess term is 0.  (Retires the v14 scenario --
    box 19 + 597 + 21, ring within 1 px of ceil(619g/16) - 1 -- which no longer occurs in game at g > 16; the
    margin-excess arithmetic stays covered by test_v14_ornate_picker_right_edge_follows_the_right_margin.)"""
    fl = lambda v: (v * g) >> 4
    boxw = fl(19) + fl(597) + fl(19)
    stash_l, stash_r = fl(13), boxw - 1 - fl(13)
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, ptype=6, dlg=8, margin_r=fl(19), title_l=stash_l, title_r=stash_r)
    assert r4(UNION["l"]) == ornate_container_edge_l(stash_l, g)
    assert r4(UNION["r"]) == ornate_picker_container_edge_r(stash_r, fl(19), g) == ornate_container_edge_r(stash_r, g)
    assert r4(UNION["r"]) == boxw - 1 - r4(UNION["l"]), (r4(UNION["l"]), r4(UNION["r"]), boxw)


def test_v9_picker_dlg8_would_have_hit_the_quit_law_without_the_type_gate(uc):
    """The regression that motivated v8+v9: the picker's dlg_type is 8 (same
    as the quit modal — [+0x2350] cannot distinguish them), so under a flat
    type it falls to the QUIT law; only the popup-type band routes it to the
    container arm."""
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, 40, ptype=0, dlg=8)
    assert r4(UNION["l"]) == body_outer_edge_l(T_L, 40)      # quit law (flat)
    _, r4 = _run(uc, CODE_UNION, TAIL_UNION, 40, ptype=6, dlg=8)
    assert r4(UNION["l"]) == ornate_container_edge_l(T_L, 40)


@pytest.mark.parametrize("g", range(17, 41))
def test_v8_slide_family_keeps_the_rewrite(uc, g):
    """Type 5 (slide family) was in the original census -> same law as type 0."""
    rect_arg, r4 = _run(uc, CODE_UNION, TAIL_UNION, g, ptype=5)
    assert rect_arg == UNION["l"]
    assert r4(UNION["l"]) == body_outer_edge_l(T_L, g)
    assert r4(UNION["r"]) == body_outer_edge_r(T_R, g)
    rect_arg, r4 = _run(uc, CODE_FRAME, TAIL_FRAME, g, ptype=5)
    assert rect_arg == ALIGN["l"]
    assert r4(ALIGN["l"]) == body_inner_edge_l(T_L, g)
    assert r4(ALIGN["r"]) == body_inner_edge_r(T_R, g)


@pytest.mark.parametrize("code,tail", [(CODE_UNION, TAIL_UNION), (CODE_FRAME, TAIL_FRAME)])
@pytest.mark.parametrize("ptype", (0, 1, 2, 3, 4, 5, 6, 7, 1000))
def test_v8_gate_matches_the_law_per_type(uc, code, tail, ptype):
    """The baked comparator == the laws for every type: the FRAME thunk takes
    popup_frame_rewrite_applies alone; the UNION thunk additionally admits
    the ornate picker shape (run here with dlg=8/no-body/no-art/titled)."""
    rect_arg, _ = _run(uc, code, tail, 40, ptype=ptype, dlg=8)
    took = rect_arg != RECT
    expect = popup_frame_rewrite_applies(ptype * 10000)
    if code == CODE_UNION:
        expect = expect or ornate_picker_takes_container_arm(
            ptype * 10000, 8, 0, 0, 1)
    assert took == expect, ptype

# ---------------------------------------------------------------------------
# thunk_pf_title_stash v4 — stash + ornate inset arm (2026-08-01c: the v2
# ornate-flush rewrite stays REVERTED; the arm is a pure uniform inset
# scale of the 6/2 title chain's native 13px l/t/r window insets, law
# ornate_title_inset_delta; bottom stays engine)
# ---------------------------------------------------------------------------

CODE_TITLE = 0x00A17400        # same emu page as the pair above
TAIL_TITLE = 0xDEADBE5C        # t_band_bdraw sentinel (tail push; 2026-10-24 W1A, was thunk_box_thick_flat 0xDEADBE4C)


@pytest.fixture(scope="module")
def uct(uc):
    uc.mem_write(CODE_TITLE, _blob(gen.ASM_TITLE, CODE_TITLE))
    return uc


def _run_title(uct, g, *, esi=POPUP, ptype=6, dlg=8, bodyh=0, local=LOCAL):
    def w4(addr, v):
        uct.mem_write(addr, int(v).to_bytes(4, "little", signed=True))

    w4(G_ADDR, g)
    w4(TITLE_L, -0x55555556)                        # poison the stash
    w4(TITLE_R, -0x55555556)
    if esi == POPUP:
        w4(esi + 0x30AC, ptype * 10000)
        w4(esi + 0x2350, dlg)
        w4(esi + 0x30D4, bodyh)
    for i, k in enumerate(("l", "t", "r", "b")):
        w4(RECT + 4 * i, local[k])

    sp = STACK + PAGE - 0x20
    w4(sp, 0x0040604D)
    w4(sp + 4, RECT)
    w4(sp + 8, 0x0078D5A0)
    uct.reg_write(UC_X86_REG_ESP, sp)
    uct.reg_write(UC_X86_REG_ESI, esi)
    uct.reg_write(UC_X86_REG_ECX, 0x00C0FFEE)
    uct.emu_start(CODE_TITLE, TAIL_TITLE, count=128)
    assert uct.reg_read(UC_X86_REG_EIP) == TAIL_TITLE
    assert uct.reg_read(UC_X86_REG_ECX) == 0x00C0FFEE, "clobbered ecx (dest this)"
    assert uct.reg_read(UC_X86_REG_ESI) == esi, "clobbered esi (popup)"

    def r4(addr):
        return int.from_bytes(uct.mem_read(addr, 4), "little", signed=True)
    rect = tuple(r4(RECT + 4 * i) for i in range(4))
    return rect, r4


from scaling_laws import ornate_title_inset_delta, ornate_title_outer_bottom  # noqa: E402


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (0, 5))
@pytest.mark.parametrize("shape", ["picker", "dlg_none", "has_body"])
def test_title_flat_slide_stash_only_untouched(uct, g, ptype, shape):
    """Flat/slide titles reach the draw untouched (the locked families), and
    the stash records the engine rect."""
    kw = {"picker": dict(), "dlg_none": dict(dlg=-1), "has_body": dict(bodyh=120)}[shape]
    rect, r4 = _run_title(uct, g, ptype=ptype, **kw)
    assert rect == (LOCAL["l"], LOCAL["t"], LOCAL["r"], LOCAL["b"]), \
        f"{ptype}/{shape}: rect must stay untouched"
    assert r4(TITLE_L) == LOCAL["l"] and r4(TITLE_R) == LOCAL["r"], \
        f"{ptype}/{shape}: stash must record the engine rect"


from scaling_laws import ornate_title_engine_top, ornate_title_rect, popup_scale_floor  # noqa: E402


def _orn_local(g):
    """The engine's ornate title rect, popup-local: l = t = 9+ps3+3 (15 @g25, 19 @g40;
    measured), r = W - t, b = whatever the engine wrote (replaced by the arm)."""
    t = ornate_title_engine_top(g)
    return {"l": t, "t": t, "r": 1741 - t, "b": t + 60}


@pytest.mark.parametrize("g", range(17, 41))
@pytest.mark.parametrize("ptype", (2, 6))
@pytest.mark.parametrize("shape", ["picker", "dlg_none", "has_body"])
def test_title_v7_ornate_inset_arm_matches_the_laws(uct, g, ptype, shape):
    """Ornate 6/2 titles (EVERY shape — the inset is a property of the title
    vs the window, not of the picker): the rect lands at s(13) / s(37)
    popup-local whatever the engine top (law ornate_title_rect), and the
    stash records the SHIFTED l/r/b (the v9 frame arm + fieldpads derive
    from it)."""
    kw = {"picker": dict(), "dlg_none": dict(dlg=-1), "has_body": dict(bodyh=120)}[shape]
    local = _orn_local(g)
    rect, r4 = _run_title(uct, g, ptype=ptype, local=local, **kw)
    want = ornate_title_rect(local["l"], local["t"], local["r"], g)
    assert rect == want, f"{ptype}/{shape}: rect must land at s(13)/s(37)"
    assert rect[1] == popup_scale_floor(13, g) and rect[3] == popup_scale_floor(37, g)
    assert rect[0] == popup_scale_floor(13, g) and rect[2] == 1741 - popup_scale_floor(13, g) - 1   # v9: half-open R
    # outer height == s(37)-s(13) (the vanilla 24 scaled, exact floor split)
    assert rect[3] - rect[1] == (37 * g) // 16 - (13 * g) // 16
    assert r4(TITLE_L) == rect[0] and r4(TITLE_R) == rect[2] and r4(0xDEADBE0C) == rect[3], \
        f"{ptype}/{shape}: stash must record the shifted rect (+ the v6 bottom)"


def test_title_v7_the_4k_probe_case(uct):
    """Probe 2026-08-23c @g40 (build 74d0a69c): the engine rect arrived as
    19,19,1722,* and the v5 arm shipped it at 38,38,1703,98 — 6px low/in
    versus the proportionate 32 / 92 (the header reserve [30e8] = s(47) =
    117 sized the rest of the popup for a band ending at 92; the '1px
    field channel' and 'text crowding the frame' were this)."""
    rect, r4 = _run_title(uct, 40, ptype=6, local={"l": 19, "t": 19, "r": 1722, "b": 79})
    assert rect == (32, 32, 1708, 92)                 # v9 (fix 26 v2): R on the half-open axis
    text_slot = (rect[3] - 14) - (rect[1] + 14)
    assert text_slot >= 30, "the scaled title ink (~29-30px) must fit the slot"
    assert 92 <= 107 - 15                      # clear of the measured ring top
    # native identity: the engine rect passes through untouched
    rect, r4 = _run_title(uct, 16, ptype=6, local={"l": 13, "t": 13, "r": 683, "b": 37})
    assert rect == (13, 13, 683, 37)


@pytest.mark.parametrize("case", ["native_g", "faction"])
def test_title_stash_v1_gates_hold(uct, case):
    """g <= 16 / faction: neither rewrite nor stash (bit-true v1 tail)."""
    kw = {"native_g": dict(g=NATIVE_G), "faction": dict(g=40, esi=FACTION_POPUP)}[case]
    g = kw.pop("g")
    rect, r4 = _run_title(uct, g, **kw)
    assert rect == (LOCAL["l"], LOCAL["t"], LOCAL["r"], LOCAL["b"])
    assert r4(TITLE_L) == -0x55555556 and r4(TITLE_R) == -0x55555556


# ---------------------------------------------------------------------------
# thunk_pf_textfollow v3 (2026-10-11): v2 semantics for flat/slide + the ornate
# arm keyed on g_d528_popup (laws popup_textfollow_applies / ornate_textfollow_applies).
# ---------------------------------------------------------------------------
from scaling_laws import ornate_text_x, ornate_textfollow_applies, popup_textfollow_applies  # noqa: E402


def _run_text(uc, g, *, esi=POPUP, ptype=0, art=0, a14=0, key=0, d528_left=777, x=29, engx=29):
    def w4(addr, v):
        uc.mem_write(addr, int(v).to_bytes(4, "little", signed=True))
    w4(G_ADDR, g)
    w4(D528_LEFT, d528_left)
    w4(D528_KEY, key)
    w4(D528_ENGX, engx)
    if esi == POPUP:
        w4(esi + 0xA14, a14)
        w4(esi + 0x2144, art)
        w4(esi + 0x30AC, ptype * 10000)
    sp = STACK + PAGE - 0x40
    for i, v in enumerate((0x604DFA, 0x5555, x, 73, 1026)):
        w4(sp + 4 * i, v)
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.reg_write(UC_X86_REG_ESI, esi)
    uc.reg_write(UC_X86_REG_ECX, 0x00C0FFEE)
    uc.emu_start(CODE_TEXT, BWS, count=128)
    assert uc.reg_read(UC_X86_REG_EIP) == BWS
    assert uc.reg_read(UC_X86_REG_ECX) == 0x00C0FFEE and uc.reg_read(UC_X86_REG_ESI) == esi
    esp = uc.reg_read(UC_X86_REG_ESP)
    st = [int.from_bytes(uc.mem_read(esp + 4 * i, 4), "little", signed=True) for i in range(5)]
    assert st[0] == 0x604DFA and st[1] == 0x5555 and st[3] == 73 and st[4] == 1026, "only X may change"
    return st[2]


@pytest.mark.parametrize("g", (16, 17, 22, 25, 32, 40))
@pytest.mark.parametrize("ptype", (0, 1, 2, 5, 6, 1000))
@pytest.mark.parametrize("art,a14", ((0, 0), (0x1234, 0), (0, 0x733990)))
@pytest.mark.parametrize("keyed", (False, True))
def test_textfollow_v3_matches_both_laws(uc, g, ptype, art, a14, keyed):
    key = POPUP if keyed else 0
    x = _run_text(uc, g, ptype=ptype, art=art, a14=a14, key=key)
    flat = popup_textfollow_applies(ptype * 10000, art, a14, g)
    orn = ornate_textfollow_applies(ptype * 10000, art, a14, key, POPUP, g, 29, 29)
    assert not (flat and orn)
    assert x == (ornate_text_x(777, g) if (flat or orn) else 29)


@pytest.mark.parametrize("g", (22, 40))
def test_textfollow_v3_ornate_key_must_name_this_popup(uc, g):
    assert _run_text(uc, g, ptype=6, key=POPUP + 0x10) == 29        # another popup's key: engine X
    assert _run_text(uc, g, ptype=6, key=0) == 29                   # cleared key: engine X
    assert _run_text(uc, g, ptype=6, key=POPUP) == 777 + popup_pad(3, g)
    assert _run_text(uc, g, esi=FACTION_POPUP, ptype=6, key=FACTION_POPUP) == 29


@pytest.mark.parametrize("g", (17, 22, 25, 40))
@pytest.mark.parametrize("ptype", (2, 6))
def test_textfollow_v3_stale_key_second_popup_same_address(uc, g, ptype):
    """Popup A (ornate, canonical margin) runs frame_align's ornate arm: key = A, g_d528_left = A's moved box,
    g_d528_engx = A's engine text X.  Popup B is a DIFFERENT type 2/6 popup that the allocator put at the SAME
    address and that draws body text WITHOUT passing frame_align (no d528 this draw): it must keep its own
    engine X, never A's g_d528_left + ps3."""
    from scaling_laws import ornate_textfollow_applies
    m, local = _ornate_local(g)
    _, r4 = _run(uc, CODE_FRAME, TAIL_FRAME, g, ptype=ptype, local=local, margin=m, bodyh=50)
    a_left, a_engx = r4(D528_LEFT), r4(D528_ENGX)
    assert r4(D528_KEY) == POPUP and a_engx == local["l"] + popup_pad(3, g)
    # A's own text draw follows its box
    assert _run_text(uc, g, ptype=ptype, key=POPUP, d528_left=a_left, x=a_engx, engx=a_engx) == a_left + popup_pad(3, g)
    # B: same address, its own engine X (another margin / content offset), no frame_align in between
    for b_x in (a_engx + 9, a_engx - 3, 5):
        assert not ornate_textfollow_applies(ptype * 10000, 0, 0, POPUP, POPUP, g, a_engx, b_x)
        assert _run_text(uc, g, ptype=ptype, key=POPUP, d528_left=a_left, x=b_x, engx=a_engx) == b_x
