#!/usr/bin/env python
"""diplowin_scale bake (2026-09-26): the MULTIPLAYER NEGOTIATION WINDOW (Thinker's DiploWin 0x73ACD8; builder
DiploWin_build 0x443F10 via diplo 0x444D90, draw 0x4436C0, faction sides 0x442A10 / 0x442DC0, offers 0x443170).

PORT OF: scaling_laws.py :: dw_window_rect / dw_frame_lr / dw_layout / dw_chat_rects / dw_caption_size /
dw_ts_inset_delta / dw_text_inset / dw_console_frame / dw_ring / dw_art_rect / dw_status_rect / dw_offer_list
(the SOURCE OF TRUTH).  Parity: tests\\test_diplowin_asm_parity.py; law sweep: tests\\test_scaling_diplowin.py.

Vanilla builds a 832 x (0x254 - strip) window whose child rects all derive from (w, h) and are STORED in the
object before GraphicWin_init @0x444617; with the strip device-scaled by the HUD bake the window collapsed to a
64-px sliver at 4K.  ONE lever rewrites every live rect field from the law at device density; the painters'
native insets follow through call-site wrappers:

  t_dw_rects    CALL helper (esi = this): the dw_layout law over +0xEDC..+0x109C + the chat / edit boxes,
                and the window rect into g_dw_win.
  t_dw_build    0x444617 `call GraphicWin_init`: g>16 -> t_dw_rects, x/y/w/h args from g_dw_win.
  t_dw_capsz    0x44462A `call GraphicWin_clear`: caption size [+0x16C] = dp(0x1A).
  t_dw_ts3      0x444676 TextScroll_attach: the chat box inset native 3 -> dp(3).
  t_dw_enter    0x444DA0 `call DiploWin_build` (inside diplo; build + modal + close all run inside it):
                refcount g_dw_armed around the call (the button gate's arm).
  t_dw_gate     head of thunk_btn_shrink's gate chain (in front of t_ntw_gate): DiploWin's 11 FlatButtons
                (+0x10AC + n*0xB4C, n = 2..12) -> admitted to the 2D zoom while armed.
  t_dw_bm / t_dw_bmdf   DiploWin-canvas frames: R-1/B-1 rect copy (law bandmap_rect_from_halfopen) ->
                thunk_box_thick_hollow_flat (d5a0) / thunk_box_thick_devfill (d618, d528, the d690 backdrop).
  t_dw_ring     the two painter rings (a union -/+ native 3) -> -/+ dp(3), R-1/B-1, hollow_flat.
  t_dw_mw4      the two MainWin console frames (seed D90 / D80 inset native 4) -> dp(4), then the engine
                entry (thunk_hud_boxframe thickens MainWin-canvas frames itself).
  t_dw_in3      every write_cent_l_7 text rect: the native-3 inset -> dp(3).
  t_dw_artL/R   the faction art Sprite_draw_2 (1:1): placed per dw_art_rect, drawn g:16 through
                thunk_art_draw (edge-pinned parity re-blit: the art is scanline-dithered) with
                thunk_portrait_avg's dest gate poked to this canvas around the call -- the Datalinks
                t_dl_portrait recipe, same sprite; the caller's art-rect locals are rewritten so the status
                box below derives from the drawn art.
  t_dw_status   Buffer_map_colors_2 on the status box: native 4 / 0x18 insets -> dp().
  t_dw_offers   the offer-list Buffer_set_text_color: list x / top / width per dw_offer_list (the Spot_add
                hit rows copy the same locals, so clicks follow).
REUSED: t_ffn at the 10 find_font(14, v) sites (face law); thunk_popup_railshow / railhide at the two slide
calls (the window is now enlarged, so the animation rails need the arm like the base screen / Council).
CHAT (v3/v4): t_dw_chatfont (the log + edit line font), t_dw_ts3's g_netwin_active bracket + thunk_pref_sbzoom v9 +
t_dw_gate arrows + thunk_btn_stripes v12 (the chat-history scrollbar), t_dw_wheel_down/up (wheel scrolls the chat).
g<=16: every thunk tail-jumps / passes through to the native callee untouched.

Usage: py assemble_diplowin.py            (assemble + checks)
       py assemble_diplowin.py --splice   (also splice into ..\\patches\\patches.yaml, byte-safe, idempotent)
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
BASE_OFF = 0x2D6D0                     # cave_map: 0x2D6C4..0x2E000 FREE (g_dp_bio_under ends 0x2D6C4)
LIMIT_OFF = 0x2E000                    # g_ffn_keys
FIXED = {"t_dw_rects": (0x197B0, 0x1A000)}   # cave_map: 0x197AA..0x1A000 FREE (thunk_wheel_up ends 0x197AA; g_dw_vpdone next)
G = 0x668740                           # g_popup_scale_num

# ---- engine / cave anchors ---------------------------------------------------------
DW = 0x0073ACD8                        # DiploWin
CANVAS = DW + 0x444
BTN_LO, BTN_HI = DW + 0x10AC + 2 * 0xB4C, DW + 0x10AC + 12 * 0xB4C
SW_VA, SH_VA, STRIP_VA, DC0_VA = 0x009B7B1C, 0x009B7B20, 0x007AF59C, 0x007AF5E0
BUILD = 0x00443F10
GW_INIT = 0x005D4EF0
GW_CLEAR = 0x005D5250
TS_ATTACH = 0x006292D0
BOX_SPRITE = 0x005E2DD3
CENT7 = 0x005DD130
FIND_FONT = 0x005882F0
SPRITE_DRAW2 = 0x005E4B4A
MAP_COLORS = 0x005DA4D0
SET_TEXT_COLOR = 0x005DACB0
SLIDE_SHOW, SLIDE_HIDE = 0x0045D440, 0x0045D970
ART_W_TAB = 0x0078EEE4                 # g_faction_art sprite width (+0x18 of 0x78EECC), stride 0x65C per faction
HOLLOWFLAT = PCAVE2 + 0x140
DEVFILL = PCAVE2 + 0x42A0
T_FFN = PCAVE2 + 0x2E570
T_NTW_GATE = PCAVE2 + 0x2EF40
ART_DRAW = PCAVE2 + 0x29EB0
PAVG_GATE_IMM = PCAVE2 + 0xA05         # imm32 of thunk_portrait_avg's dest gate (`cmp eax, 0x940824`)
RAILSHOW, RAILHIDE = PCAVE2 + 0x3550, PCAVE2 + 0x44D0
TS_CLEAR = 0x00629780                  # TextScroll_clear (ecx = chat log): the first call after both chat attaches
FONT_INIT = 0x00618F40                 # Font_init(name, size, style) thiscall RET 0xC
HUD_FONT_NAME = 0x00691B2C             # g_hud_font_name: the face WinMain gives the default font 0x7D3948 (Arial Narrow)
CHAT_FONT_SLOTS = (DW + 0xA388 + 0x970, DW + 0xDA7C + 0x970)   # chat TextScroll / EditLine embedded-buffer font
ONMODE = 0x00443C70                    # DiploWinIface_on_mode
IFACE_VTBL0 = 0x0066B5E0               # DiploWin iface vtbl slot 0 (= on_mode)
T_CR_MARK = PCAVE2 + 0x17080
G_CR_BUF, G_CR_L, G_CR_R, G_CR_B = PCAVE2 + 0x12790, PCAVE2 + 0x12794, PCAVE2 + 0x12798, PCAVE2 + 0x1279C
IAT_VIRTUALALLOC = 0x00669134
SEED_D80, SEED_D90, SEED_DB0 = 0x007AF5A0, 0x007AF5B0, 0x007AF5D0
MW_CANVAS_DATA, MW_CANVAS_PITCH = 0x007AECB8, 0x007AF10C   # MainWin canvas Buffer +0x54 pixels / +0x4A8 pitch
CHAT_TS = DW + 0xA388                  # the chat-history TextScroll (parent MainWin)
CHAT_SB = CHAT_TS + 0xA20              # its ScrollBar (0x745A80; sbzoom v9 whitelists it)
CHAT_ARROWS = (CHAT_SB + 0xAAC, CHAT_SB + 0x15F8)   # its two arrow FlatButtons (btn_stripes v12 restripes them)
G_NETWIN = PCAVE2 + 0x4800             # g_netwin_active: thunk_sb_xinset / thunk_sb_width scale g_scrollbar_w iff set
BASEPOP, MODAL_TOP = 0x009B8D7C, 0x009B7AE0
GET_TARGET = 0x005F6A50                # Win_get_active_target (the wheel sites' original callee)
CHEVRON = 0x00606B20                   # ScrollBar_on_chevron thiscall RET 4 (1 up / 2 down)
T_BW_WHEEL_DOWN, T_BW_WHEEL_UP = PCAVE2 + 0x110A0, PCAVE2 + 0x4190   # the current WinProc wheel chain heads
REUSED = {"thunk_box_thick_hollow_flat": HOLLOWFLAT, "thunk_box_thick_devfill": DEVFILL, "t_ffn": T_FFN,
          "t_ntw_gate": T_NTW_GATE, "thunk_art_draw": ART_DRAW,
          "thunk_popup_railshow": RAILSHOW, "thunk_popup_railhide": RAILHIDE,
          "t_cr_mark": T_CR_MARK, "g_cr_buf": G_CR_BUF, "g_cr_L": G_CR_L, "g_cr_R": G_CR_R, "g_cr_B": G_CR_B,
          "g_netwin_active": G_NETWIN, "t_bw_wheel_down": T_BW_WHEEL_DOWN, "t_bw_wheel_up": T_BW_WHEEL_UP}

# ---- cells (zero-init section padding) ----------------------------------------------
K_SRC = [("W", SL.DW_W), ("HB", SL.DW_HBASE), ("CW", SL.DW_CENTER_W), ("IN", SL.DW_IN), ("PAD", SL.DW_PAD),
         ("GA", SL.DW_GAP), ("GB", SL.DW_GAP_MID), ("BH", SL.DW_BAR_H), ("HT", SL.DW_HDR_T),
         ("NT", SL.DW_NAME_T), ("PT", SL.DW_PANEL_T), ("AH", SL.DW_ART[1]), ("R3", SL.DW_ROW3_B),
         ("R2", SL.DW_ROW2_B), ("R1", SL.DW_ROW1_B), ("THB", SL.DW_THDR_B), ("CI", SL.DW_CHAT_IN),
         ("CB", SL.DW_CHAT_B), ("ET", SL.DW_EDIT_T), ("EB", SL.DW_EDIT_B)]
S_NAMES = ["K", "FL", "FR", "IL", "IR", "H", "HW", "L3", "THIRD", "CELLS", "B", "T"]
CELLS = [("g_dw_k", 4 * len(K_SRC)), ("g_dw_s", 4 * len(S_NAMES)), ("g_dw_win", 16), ("g_dw_rect", 16),
         ("g_dw_armed", 4), ("g_dw_chatfont", 0x40), ("g_dw_chatfont_g", 4)]
CELL = {}
_o = BASE_OFF
for _n, _sz in CELLS:
    CELL[_n] = PCAVE2 + _o
    _o = (_o + _sz + 3) & ~3
CODE_OFF = (_o + 15) & ~15
K = {n: CELL["g_dw_k"] + 4 * i for i, (n, _) in enumerate(K_SRC)}
S = {n: CELL["g_dw_s"] + 4 * i for i, n in enumerate(S_NAMES)}
WIN, RECT, ARMED = CELL["g_dw_win"], CELL["g_dw_rect"], CELL["g_dw_armed"]
CHATFONT, CHATFONT_G = CELL["g_dw_chatfont"], CELL["g_dw_chatfont_g"]


def k(n: str) -> str:
    return f"dword ptr [{K[n]:#x}]"


def s(n: str) -> str:
    return f"dword ptr [{S[n]:#x}]"


def DP(reg: str) -> str:
    """reg = dp(reg, g) = (reg*g) >> 4 (g > 16 on every path that uses it)."""
    return f"imul {reg}, dword ptr [{G:#x}]\n    sar {reg}, 4"


def put(off: int, l: str, t: str, r: str, b: str) -> str:
    """store 4 register / imm operands to the rect field at esi+off"""
    return "\n".join(f"    mov dword ptr [esi+{off + 4 * i:#x}], {v}" for i, v in enumerate((l, t, r, b)))


def asm_rects() -> str:
    a = ["    pushad"]
    for n, v in K_SRC:
        a += [f"    mov eax, {v}", "    " + DP("eax"), f"    mov {k(n)}, eax"]
    a += [
        # K = stroke_width(g) = half_down(g, 16) = (2g + 15) >> 5
        f"    mov eax, dword ptr [{G:#x}]", "    lea eax, [eax*2+15]", "    sar eax, 5", f"    mov {s('K')}, eax",
        # FL = (15g >> 4) + (8g >> 4)  (the two left rail strips)
        f"    mov eax, {SL.DW_RAIL_L[0]}", "    " + DP("eax"), f"    mov edx, {SL.DW_RAIL_L[1]}", "    " + DP("edx"),
        "    add eax, edx", f"    mov {s('FL')}, eax",
        # window: h = dp(0x254) - strip ; w = dp(0x340) ; x = idiv(SW - dp(0x320), 2) ; y = SH - strip - h
        f"    mov eax, {k('HB')}", f"    sub eax, dword ptr [{STRIP_VA:#x}]", f"    mov {s('H')}, eax",
        f"    mov dword ptr [{WIN + 12:#x}], eax",
        f"    mov eax, {k('W')}", f"    mov dword ptr [{WIN + 8:#x}], eax",
        f"    mov eax, dword ptr [{SW_VA:#x}]", f"    sub eax, {k('CW')}", "    cdq", "    sub eax, edx", "    sar eax, 1",
        f"    mov dword ptr [{WIN:#x}], eax",
        f"    mov eax, dword ptr [{SH_VA:#x}]", f"    sub eax, dword ptr [{STRIP_VA:#x}]", f"    sub eax, {s('H')}",
        f"    mov dword ptr [{WIN + 4:#x}], eax",
        # FR = ((w << 4) / g - 0x37) * g >> 4  (railscale's double-floor right anchor)
        f"    mov eax, {k('W')}", "    shl eax, 4", "    xor edx, edx", f"    div dword ptr [{G:#x}]",
        f"    sub eax, {SL.DW_RAIL_R}", "    " + DP("eax"), f"    mov {s('FR')}, eax",
        # frame
        f"    mov eax, {s('FL')}", f"    mov ecx, {s('FR')}", f"    mov edx, {s('H')}", put(0xEDC, "eax", "0", "ecx", "edx"),
        # IL / IR
        f"    add eax, {k('IN')}", f"    mov {s('IL')}, eax", f"    sub ecx, {k('IN')}", f"    mov {s('IR')}, ecx",
        # header 0xF4C: (IL, HT, IR, HT+BH)
        f"    mov edx, {k('HT')}", f"    mov ebx, edx", f"    add ebx, {k('BH')}", put(0xF4C, "eax", "edx", "ecx", "ebx"),
        # HW = (IR - IL + GA) >> 1
        "    mov edx, ecx", "    sub edx, eax", f"    add edx, {k('GA')}", "    sar edx, 1", f"    mov {s('HW')}, edx",
        # names: T = NT, B = NT + BH; left (IL, IL+HW-GA), right (IL+HW, IR)
        f"    mov ebx, {k('NT')}", "    mov edi, ebx", f"    add edi, {k('BH')}",
        "    lea ebp, [eax+edx]", "    mov edx, ebp", f"    sub edx, {k('GA')}",       # ebp = IL+HW, edx = IL+HW-GA
        put(0xF7C, "eax", "ebx", "edx", "edi"), put(0xF8C, "ebp", "ebx", "ecx", "edi"),
        # panels: T = PT, B = PT + 2K + AH
        f"    mov ebx, {k('PT')}", "    mov edi, ebx", f"    add edi, {s('K')}", f"    add edi, {s('K')}", f"    add edi, {k('AH')}",
        put(0xF5C, "eax", "ebx", "edx", "edi"), put(0xF6C, "ebp", "ebx", "ecx", "edi"),
        # row 3: t7 = (FR - FL) / 7 ; L3 = FL + t7 ; THIRD = ((FR - t7) - L3 + GA) / 3
        f"    mov eax, {s('FR')}", f"    sub eax, {s('FL')}", "    xor edx, edx", "    mov ecx, 7", "    div ecx",
        "    mov ebx, eax", f"    add eax, {s('FL')}", f"    mov {s('L3')}, eax",               # ebx = t7, eax = L3
        f"    mov edx, {s('FR')}", "    sub edx, ebx", "    sub edx, eax", f"    add edx, {k('GA')}",
        "    mov eax, edx", "    xor edx, edx", "    mov ecx, 3", "    div ecx", f"    mov {s('THIRD')}, eax",
        # B3 = H - R3 ; T3 = B3 - BH
        f"    mov edi, {s('H')}", f"    sub edi, {k('R3')}", "    mov ebx, edi", f"    sub ebx, {k('BH')}",
    ]
    for i, off in enumerate((0xFFC, 0x100C, 0x101C)):
        a += [f"    mov eax, {s('THIRD')}", f"    imul eax, eax, {i}", f"    add eax, {s('L3')}",
              "    mov ecx, eax", f"    add ecx, {s('THIRD')}", f"    sub ecx, {k('GA')}", put(off, "eax", "ebx", "ecx", "edi")]
    # rows 2 / 1: CELLS = (IR - IL) - (2GA + GB); col i = IL + cum(i) + before[i] .. IL + cum(i+1) + before[i]
    a += [f"    mov eax, {s('IR')}", f"    sub eax, {s('IL')}", f"    sub eax, {k('GA')}", f"    sub eax, {k('GA')}",
          f"    sub eax, {k('GB')}", f"    mov {s('CELLS')}, eax"]

    def cum_to(reg: str, i: int) -> list:
        """reg = IL + cum(i, CELLS, 4) = IL + (2*i*CELLS + 3) >> 3"""
        return [f"    mov {reg}, {s('CELLS')}", f"    imul {reg}, {reg}, {2 * i}", f"    add {reg}, 3", f"    sar {reg}, 3",
                f"    add {reg}, {s('IL')}"]

    before = ([], [k("GA")], [k("GA"), k("GB")], [k("GA"), k("GB"), k("GA")])
    rows = ((0x104C, 0x105C, 0x108C, 0x109C), (0x102C, 0x103C, 0x106C, 0x107C))
    for i in range(4):
        a += cum_to("eax", i) + cum_to("ecx", i + 1)
        for b in before[i]:
            a += [f"    add eax, {b}", f"    add ecx, {b}"]
        for (off2, off1) in ((rows[0][i], rows[1][i]),):
            for off, rk in ((off2, "R2"), (off1, "R1")):
                a += [f"    mov edi, {s('H')}", f"    sub edi, {k(rk)}", "    mov ebx, edi", f"    sub ebx, {k('BH')}",
                      put(off, "eax", "ebx", "ecx", "edi")]
    a += [
        # headers: B = H - THB, T = B - BH ; TRADE (col0.L, col1.R), DIPLOMACY (col2.L, col3.R)
        f"    mov edi, {s('H')}", f"    sub edi, {k('THB')}", "    mov ebx, edi", f"    sub ebx, {k('BH')}",
        "    mov eax, dword ptr [esi+0x104C]", "    mov ecx, dword ptr [esi+0x1064]", put(0xF9C, "eax", "ebx", "ecx", "edi"),
        "    mov eax, dword ptr [esi+0x108C]", "    mov ecx, dword ptr [esi+0x10A4]", put(0xFBC, "eax", "ebx", "ecx", "edi"),
        # rings: (hdr.L - P, hdr.T - P, colR + P, row2.B + P)
        f"    mov edx, {k('PAD')}", "    sub ebx, edx", "    mov edi, dword ptr [esi+0x1058]", "    add edi, edx",
        "    mov eax, dword ptr [esi+0xF9C]", "    sub eax, edx", "    mov ecx, dword ptr [esi+0x1064]", "    add ecx, edx",
        put(0xFAC, "eax", "ebx", "ecx", "edi"),
        "    mov eax, dword ptr [esi+0xFBC]", "    sub eax, edx", "    mov ecx, dword ptr [esi+0x10A4]", "    add ecx, edx",
        put(0xFCC, "eax", "ebx", "ecx", "edi"),
        # chat / edit boxes from the DEVICE seed DC0: chat (L+CI, T+CI, R-CI, B-CB), edit (L+CI, B-ET, R-CI, B-EB)
        f"    mov eax, dword ptr [{DC0_VA:#x}]", f"    add eax, {k('CI')}",
        f"    mov ecx, dword ptr [{DC0_VA + 8:#x}]", f"    sub ecx, {k('CI')}",
        f"    mov ebx, dword ptr [{DC0_VA + 4:#x}]", f"    add ebx, {k('CI')}",
        f"    mov edi, dword ptr [{DC0_VA + 12:#x}]", "    mov edx, edi", f"    sub edx, {k('CB')}",
        put(0xF3C, "eax", "ebx", "ecx", "edx"),
        "    mov ebx, edi", f"    sub ebx, {k('ET')}", f"    sub edi, {k('EB')}", put(0xF2C, "eax", "ebx", "ecx", "edi"),
        "    popad", "    ret",
    ]
    return "\n".join(a)


def _rect_copy(d_l: str = "", d_t: str = "", d_r: str = "", d_b: str = "", arg: str = "esp+4") -> str:
    """copy the RECT at [arg] into g_dw_rect applying per-edge asm fix-ups on edx, repoint [arg]."""
    out = [f"    mov eax, dword ptr [{arg}]"]
    for i, fix in enumerate((d_l, d_t, d_r, d_b)):
        out += [f"    mov edx, dword ptr [eax+{4 * i}]"] + ([f"    {fix}"] if fix else []) + [f"    mov dword ptr [{RECT + 4 * i:#x}], edx"]
    out.append(f"    mov dword ptr [{arg}], {RECT:#x}")
    return "\n".join(out)


def delta(reg: str, native: int) -> str:
    """reg = dp(native) - native"""
    return f"mov {reg}, {native}\n    {DP(reg)}\n    sub {reg}, {native}"


def asm_art(right: bool, lbl: str) -> str:
    # E8 at the Sprite_draw_2 site (0x442BF8 left / 0x442FA8 right). ecx = Sprite*; [esp+4] dest, +8 key, +0xC x,
    # +0x10 y, +0x14 num(1), +0x18 den(1); RET 0x18.  Caller ebp frame: [ebp-0x14..-8] = the art rect (L,T,R,B).
    panel = 0xF6C if right else 0xF5C
    place = (f"    mov eax, dword ptr [{DW + panel + 8:#x}]\n    sub eax, ebx\n    sub eax, esi" if right
             else f"    mov eax, dword ptr [{DW + panel:#x}]\n    add eax, ebx")
    return f"""
    cmp dword ptr [{G:#x}], 16
    jle {lbl}_native
    push ebx
    push esi
    push edi
    mov esi, dword ptr [ecx+0x18]
    {DP("esi")}
    mov edi, dword ptr [ecx+0x1C]
    {DP("edi")}
    mov ebx, dword ptr [{G:#x}]
    lea ebx, [ebx*2+15]
    sar ebx, 5
{place}
    mov edx, dword ptr [{DW + panel + 4:#x}]
    add edx, ebx
    mov dword ptr [ebp-0x14], eax
    mov dword ptr [ebp-0x10], edx
    lea ebx, [eax+esi]
    mov dword ptr [ebp-0xC], ebx
    lea ebx, [edx+edi]
    mov dword ptr [ebp-8], ebx
    mov dword ptr [esp+0x18], eax
    mov dword ptr [esp+0x1C], edx
    pop edi
    pop esi
    pop ebx
    push dword ptr [{PAVG_GATE_IMM:#x}]
    mov dword ptr [{PAVG_GATE_IMM:#x}], {CANVAS:#x}
    push 16
    push dword ptr [{G:#x}]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    call {ART_DRAW:#x}
    pop dword ptr [{PAVG_GATE_IMM:#x}]
    ret 0x18
{lbl}_native:
    jmp {SPRITE_DRAW2:#x}
"""


THUNKS = [
    ("t_dw_rects", asm_rects()),
    ("t_dw_build", f"""
    cmp dword ptr [{G:#x}], 16
    jle nb_native
    call t_dw_rects
    mov eax, dword ptr [{WIN:#x}]
    mov dword ptr [esp+4], eax
    mov eax, dword ptr [{WIN + 4:#x}]
    mov dword ptr [esp+8], eax
    mov eax, dword ptr [{WIN + 8:#x}]
    mov dword ptr [esp+0xC], eax
    mov eax, dword ptr [{WIN + 12:#x}]
    mov dword ptr [esp+0x10], eax
nb_native:
    jmp {GW_INIT:#x}
"""),
    ("t_dw_capsz", f"""
    cmp dword ptr [{G:#x}], 16
    jle nc_native
    mov eax, {SL.DW_CAPTION}
    {DP("eax")}
    mov dword ptr [ecx+0x16C], eax
nc_native:
    jmp {GW_CLEAR:#x}
"""),
    # v2 (2026-09-27): also the chat-history SCROLLBAR.  TextScroll_attach creates the whole bar (x = w -
    # g_scrollbar_w @0x62944D, width @0x6058AE, arrows / track / thumb zone from that width) and draws only the
    # bar's own arrows inside; both g_scrollbar_w reads scale iff g_netwin_active, so a SHORT refcount bracket
    # around this one call scales the bar without admitting any other FlatButton (holding the flag for the
    # window's life would: thunk_btn_gate's netwin branch).  Clamped dec: thunk_sb_restripe writes it absolute.
    ("t_dw_ts3", f"""
    cmp dword ptr [{G:#x}], 16
    jle nt_native
    {delta("eax", SL.DW_TS_IN)}
    add dword ptr [esp+4], eax
    add dword ptr [esp+8], eax
    add eax, eax
    sub dword ptr [esp+0xC], eax
    sub dword ptr [esp+0x10], eax
    inc dword ptr [{G_NETWIN:#x}]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    call {TS_ATTACH:#x}
    cmp dword ptr [{G_NETWIN:#x}], 0
    jle nt_out
    dec dword ptr [{G_NETWIN:#x}]
nt_out:
    ret 0x1C
nt_native:
    jmp {TS_ATTACH:#x}
"""),
    ("t_dw_enter", f"""
    cmp dword ptr [{G:#x}], 16
    jle ne_native
    inc dword ptr [{ARMED:#x}]
    push dword ptr [esp+8]
    push dword ptr [esp+8]
    call {BUILD:#x}
    dec dword ptr [{ARMED:#x}]
    ret 8
ne_native:
    jmp {BUILD:#x}
"""),
    ("t_dw_gate", f"""
    cmp dword ptr [{ARMED:#x}], 0
    je ng_pass
    cmp esi, {CHAT_ARROWS[0]:#x}
    je ng_hit
    cmp esi, {CHAT_ARROWS[1]:#x}
    je ng_hit
    cmp esi, {BTN_LO:#x}
    jb ng_pass
    cmp esi, {BTN_HI:#x}
    ja ng_pass
ng_hit:
    mov eax, 1
    ret
ng_pass:
    push {T_NTW_GATE:#x}
    ret
"""),
    ("t_dw_bm", f"""
    cmp dword ptr [{G:#x}], 16
    jle nbm_native
{_rect_copy(d_r="dec edx", d_b="dec edx")}
    push {HOLLOWFLAT:#x}
    ret
nbm_native:
    jmp {BOX_SPRITE:#x}
"""),
    ("t_dw_bmdf", f"""
    cmp dword ptr [{G:#x}], 16
    jle nbd_native
{_rect_copy(d_r="dec edx", d_b="dec edx")}
    push {DEVFILL:#x}
    ret
nbd_native:
    jmp {BOX_SPRITE:#x}
"""),
    ("t_dw_ring", f"""
    cmp dword ptr [{G:#x}], 16
    jle nr_native
    push ecx
    {delta("ecx", SL.DW_PAD)}
{_rect_copy(d_l="sub edx, ecx", d_t="sub edx, ecx", d_r="lea edx, [edx+ecx-1]", d_b="lea edx, [edx+ecx-1]", arg="esp+8")}
    pop ecx
    push {HOLLOWFLAT:#x}
    ret
nr_native:
    jmp {BOX_SPRITE:#x}
"""),
    ("t_dw_mw4", f"""
    cmp dword ptr [{G:#x}], 16
    jle nw_native
    push ecx
    {delta("ecx", SL.DW_CONSOLE_IN)}
{_rect_copy(d_l="add edx, ecx", d_t="add edx, ecx", d_r="sub edx, ecx", d_b="sub edx, ecx", arg="esp+8")}
    pop ecx
nw_native:
    jmp {BOX_SPRITE:#x}
"""),
    ("t_dw_in3", f"""
    cmp dword ptr [{G:#x}], 16
    jle ni_native
    push ecx
    {delta("ecx", SL.DW_PAD)}
{_rect_copy(d_l="add edx, ecx", d_t="add edx, ecx", d_r="sub edx, ecx", d_b="sub edx, ecx", arg="esp+0xC")}
    pop ecx
ni_native:
    jmp {CENT7:#x}
"""),
    # E8 at 0x44485F `call TextScroll_clear` (after both chat attaches): the chat log + edit line draw with the
    # engine DEFAULT font 0x7D3948 (WinMain: Arial Narrow 12 regular, face [g_hud_font_name]) -- a global, so
    # it is not scaled; the two widgets' embedded-buffer font (+0x970, the slot the NetWin chat fix stamps) get a
    # private Font of the same face at fl(12g/16), initialised once per g (no HFONT per open).
    ("t_dw_chatfont", f"""
    cmp dword ptr [{G:#x}], 16
    jle ncf_native
    push ecx
    mov eax, dword ptr [{G:#x}]
    cmp eax, dword ptr [{CHATFONT_G:#x}]
    je ncf_stamp
    mov dword ptr [{CHATFONT_G:#x}], eax
    mov eax, 12
    {DP("eax")}
    push 0
    push eax
    push dword ptr [{HUD_FONT_NAME:#x}]
    mov ecx, {CHATFONT:#x}
    call {FONT_INIT:#x}
ncf_stamp:
    mov dword ptr [{CHAT_FONT_SLOTS[0]:#x}], {CHATFONT:#x}
    mov dword ptr [{CHAT_FONT_SLOTS[1]:#x}], {CHATFONT:#x}
    pop ecx
ncf_native:
    jmp {TS_CLEAR:#x}
"""),
    # DiploWin iface vtbl slot 0 (on_mode): the console save-under snapshot on ENTER -- line-for-line port of the
    # live t_cr_snap_dl / t_cmb_snap (shares the g_cr_* cells + buffer; t_cr_mark records the return mode; the
    # slide_hide exit t_cr_tile_exit restores).  Only the tail differs: jmp DiploWinIface_on_mode.  slide_show
    # (win, 2) re-tiles the console big-centre; without this the close left the big-centre fill under the readouts.
    ("t_dw_snap", f"""
    cmp dword ptr [{G:#x}], 0x10
    jle sn_tail
    cmp dword ptr [esp+4], 0
    je sn_tail
    pushad
    mov eax, dword ptr [{SEED_D80 + 8:#x}]
    dec eax
    mov dword ptr [{G_CR_L:#x}], eax
    mov edx, dword ptr [{SEED_D90:#x}]
    mov dword ptr [{G_CR_R:#x}], edx
    mov ecx, dword ptr [{SEED_DB0 + 4:#x}]
    add ecx, 2
    mov dword ptr [{G_CR_B:#x}], ecx
    mov ebx, dword ptr [{G_CR_BUF:#x}]
    test ebx, ebx
    jne sn_have
    mov eax, edx
    sub eax, dword ptr [{G_CR_L:#x}]
    imul eax, ecx
    push 4
    push 0x3000
    push eax
    push 0
    call dword ptr [{IAT_VIRTUALALLOC:#x}]
    test eax, eax
    je sn_bail
    mov dword ptr [{G_CR_BUF:#x}], eax
    mov ebx, eax
sn_have:
    mov esi, dword ptr [{MW_CANVAS_DATA:#x}]
    test esi, esi
    je sn_bail
    add esi, dword ptr [{G_CR_L:#x}]
    mov edi, ebx
    mov edx, dword ptr [{G_CR_R:#x}]
    sub edx, dword ptr [{G_CR_L:#x}]
    mov ebp, dword ptr [{G_CR_B:#x}]
sn_row:
    push esi
    push edi
    mov ecx, edx
    rep movsb
    pop edi
    pop esi
    add esi, dword ptr [{MW_CANVAS_PITCH:#x}]
    add edi, edx
    dec ebp
    jne sn_row
    call {T_CR_MARK:#x}
    .byte 0x0f, 0x1f, 0x40, 0x00
sn_bail:
    popad
sn_tail:
    jmp {ONMODE:#x}
"""),
    # Heads of the WinProc wheel_scroll chain (E8 replacing `call Win_get_active_target`; [esp+0x68] = wParam,
    # [esp+0x6C] = lParam at entry; chained in front of t_bw_wheel_*).  While the negotiation window is the modal
    # top (no BasePop over it), a synthetic wheel arrow (lParam 0; uimod wheel.cpp posts it) chevron-scrolls the
    # chat log if ENGAGED -- the NTW v3 test: TextScroll shown AND its BAR shown (the range stays live on a hidden
    # bar) AND parented AND range max > min -- and is swallowed either way.  Ungated on g, like the NTW heads.
    # Unlike the NTW heads the synthetic arrows do NOT require Win_get_active_target != 0: that is DiploWin's
    # active child +0xA8, which DiploWin_build never sets (both chat widgets belong to MainWin), so a 0 would have
    # left the wheel silently dead.  Real keys (lParam != 0) and other keys still return the callee's eax.
    ("t_dw_wheel_down", f"""
    cmp dword ptr [{BASEPOP:#x}], 0
    jne wd_chain
    cmp dword ptr [{MODAL_TOP:#x}], {DW:#x}
    jne wd_chain
    call {GET_TARGET:#x}
    cmp dword ptr [esp+0x6C], 0
    jne wd_xout
    mov edx, dword ptr [esp+0x68]
    cmp edx, 0x26
    je wd_go
    cmp edx, 0x28
    jne wd_xout
wd_go:
    push esi
    push edi
    mov ecx, 1
    cmp edx, 0x26
    je wd_dir
    mov ecx, 2
wd_dir:
    mov esi, {CHAT_TS:#x}
    test byte ptr [esi+0x9C], 1
    jz wd_eat
    lea edi, [esi+0xA20]
    test byte ptr [edi+0x9C], 1
    jz wd_eat
    cmp dword ptr [edi+0xC4], 0
    je wd_eat
    mov eax, dword ptr [edi+0xA24]
    cmp eax, dword ptr [edi+0xA20]
    jle wd_eat
    push ecx
    mov ecx, edi
    call {CHEVRON:#x}
    mov edx, dword ptr [esi]
    mov ecx, esi
    call dword ptr [edx+0xFC]
wd_eat:
    xor eax, eax
    pop edi
    pop esi
    ret
wd_xout:
    ret
wd_chain:
    push {T_BW_WHEEL_DOWN:#x}
    ret
"""),
    ("t_dw_wheel_up", f"""
    cmp dword ptr [{BASEPOP:#x}], 0
    jne wu_chain
    cmp dword ptr [{MODAL_TOP:#x}], {DW:#x}
    jne wu_chain
    call {GET_TARGET:#x}
    cmp dword ptr [esp+0x6C], 0
    jne wu_xout
    mov edx, dword ptr [esp+0x68]
    cmp edx, 0x26
    je wu_eat
    cmp edx, 0x28
    jne wu_xout
wu_eat:
    xor eax, eax
wu_xout:
    ret
wu_chain:
    push {T_BW_WHEEL_UP:#x}
    ret
"""),
    ("t_dw_artL", asm_art(False, "nal")),
    ("t_dw_artR", asm_art(True, "nar")),
    # E8 at Buffer_map_colors_2 (0x442D44 / 0x4430F5): ecx = canvas, [esp+4] = the caller's art-rect local
    # (in place: the status text inset right after reuses it).
    ("t_dw_status", f"""
    cmp dword ptr [{G:#x}], 16
    jle nsx_native
    push ecx
    mov eax, dword ptr [esp+8]
    {delta("ecx", SL.DW_STATUS_IN)}
    add dword ptr [eax], ecx
    sub dword ptr [eax+8], ecx
    sub dword ptr [eax+0xC], ecx
    {delta("ecx", SL.DW_STATUS_H)}
    sub dword ptr [eax+4], ecx
    pop ecx
nsx_native:
    jmp {MAP_COLORS:#x}
"""),
    # E8 at the offer-list Buffer_set_text_color (0x44329D): esi = side (0 left / 1 right), edi = this,
    # ebx = list top (native), [ebp-0x28] = x, [ebp-4] = width, [ebp-0xC] = row pitch.  Rewrites all four:
    # x / top / width per dw_offer_list, pitch per dw_offer_pitch -- vanilla's own find_font(14,0) line metric
    # (read exactly as @0x443184..97, through the UNPATCHED find_font entry) x g/16, never the scaled font's metric.
    ("t_dw_offers", f"""
    cmp dword ptr [{G:#x}], 16
    jle nof_native
    push ecx
    push 0
    push 14
    call {FIND_FONT:#x}
    add esp, 8
    mov ecx, dword ptr [eax]
    test ecx, ecx
    jl nof_m1
    mov edx, dword ptr [eax+0x10]
    add edx, ecx
    jmp nof_m2
nof_m1:
    mov edx, dword ptr [eax+0xC]
nof_m2:
    {DP("edx")}
    mov dword ptr [ebp-0xC], edx
    mov eax, dword ptr [edi+0xAB4]
    test esi, esi
    je nof_f
    mov eax, dword ptr [edi+0xAB8]
nof_f:
    imul eax, eax, 0x65C
    mov eax, dword ptr [eax+{ART_W_TAB:#x}]
    {DP("eax")}
    mov ecx, dword ptr [{G:#x}]
    lea ecx, [ecx*2+15]
    sar ecx, 5
    add eax, ecx
    mov ecx, {SL.DW_PAD}
    {DP("ecx")}
    test esi, esi
    jne nof_right
    mov edx, dword ptr [edi+0xF5C]
    add edx, eax
    add edx, ecx
    mov dword ptr [ebp-0x28], edx
    mov eax, dword ptr [edi+0xF64]
    sub eax, ecx
    sub eax, edx
    mov dword ptr [ebp-4], eax
    mov ebx, dword ptr [edi+0xF60]
    add ebx, ecx
    jmp nof_done
nof_right:
    mov edx, dword ptr [edi+0xF6C]
    add edx, ecx
    mov dword ptr [ebp-0x28], edx
    mov ebx, dword ptr [edi+0xF74]
    sub ebx, eax
    sub ebx, ecx
    sub ebx, edx
    mov dword ptr [ebp-4], ebx
    mov ebx, dword ptr [edi+0xF70]
    add ebx, ecx
nof_done:
    pop ecx
nof_native:
    jmp {SET_TEXT_COLOR:#x}
"""),
]

ks = Ks(KS_ARCH_X86, KS_MODE_32)


def assemble_all() -> dict[str, tuple[int, bytes]]:
    names = {n: PCAVE2 + CODE_OFF for n, _ in THUNKS}
    out: dict[str, tuple[int, bytes]] = {}
    for _pass in range(4):
        off, new = CODE_OFF, {}
        for name, asm in THUNKS:
            src = asm
            for n2, va in sorted(names.items(), key=lambda kv: -len(kv[0])):
                src = re.sub(rf"\b{n2}\b", f"{va:#x}", src)
            at = FIXED[name][0] if name in FIXED else off
            enc, _ = ks.asm(src, PCAVE2 + at)
            b = bytes(enc)
            out[name] = (at, b)
            new[name] = PCAVE2 + at
            if name in FIXED:
                assert at + len(b) <= FIXED[name][1], (name, hex(at + len(b)))
            else:
                off = (off + len(b) + 15) & ~15
        if new == names:
            break
        names = new
    else:
        raise RuntimeError("layout did not converge")
    assert off <= LIMIT_OFF, hex(off)
    return out


OUT = assemble_all()
VA = {n: PCAVE2 + o for n, (o, _) in OUT.items()}

pe = pefile.PE(str(config.terranx_bak()), fast_load=True)
IMG = pe.OPTIONAL_HEADER.ImageBase


def orig(va: int, n: int) -> bytes:
    for sec in pe.sections:
        a = IMG + sec.VirtualAddress
        if a <= va < a + sec.SizeOfRawData:
            return sec.get_data()[va - a: va - a + n]
    raise KeyError(hex(va))


# (id, function, va, native callee, target, note)
BLD, DRW, SIDE_L, SIDE_R, OFF_P, ONM = ("DiploWin_build", "DiploWin_draw", "DiploWin_draw_left", "DiploWin_draw_right",
                                        "DiploWin_draw_offers", "DiploWinIface_on_mode")
SITES = [
    ("DiploWin_build.gwinit", BLD, 0x444617, GW_INIT, "t_dw_build", "GraphicWin_init: every layout rect re-derived at device density first (law dw_layout)"),
    ("DiploWin_build.caption", BLD, 0x44462A, GW_CLEAR, "t_dw_capsz", "GraphicWin_clear: caption size [+0x16C] = dp(0x1A)"),
    ("DiploWin_build.backdrop_d690", BLD, 0x44463B, BOX_SPRITE, "t_dw_bmdf", "d690 backdrop over the frame rect -> devfill (device tile + dither tail)"),
    ("DiploWin_build.ts_chat", BLD, 0x444676, TS_ATTACH, "t_dw_ts3", "TextScroll_attach (chat log): native inset 3 -> dp(3)"),
    ("DiploWin_build.font_button", BLD, 0x4447DD, FIND_FONT, "t_ffn", "find_font(14,1) button labels -> the face law"),
    ("DiploWin_build.chat_font", BLD, 0x44485F, TS_CLEAR, "t_dw_chatfont", "TextScroll_clear after both chat attaches: chat log + edit line font -> the default face at fl(12g/16)"),
    ("diplo.build_bracket", "diplo", 0x444DA0, BUILD, "t_dw_enter", "call DiploWin_build: g_dw_armed refcount around build + modal + close"),
    ("DiploWin_draw.console_d90", DRW, 0x443714, BOX_SPRITE, "t_dw_mw4", "MainWin console frame (seed D90) inset native 4 -> dp(4)"),
    ("DiploWin_draw.console_d80", DRW, 0x443756, BOX_SPRITE, "t_dw_mw4", "MainWin console frame (seed D80) inset native 4 -> dp(4)"),
    ("DiploWin_draw.ring_panels", DRW, 0x4437BC, BOX_SPRITE, "t_dw_ring", "d5a0 ring round header + both faction panels: union -/+ dp(3)"),
    ("DiploWin_draw.ring_row3", DRW, 0x44381E, BOX_SPRITE, "t_dw_ring", "d5a0 ring round the ACCEPT / DECLINE / END row: union -/+ dp(3)"),
    ("DiploWin_draw.trade_hdr_d618", DRW, 0x44384B, BOX_SPRITE, "t_dw_bmdf", "TRADE header box"),
    ("DiploWin_draw.font_titles", DRW, 0x44387F, FIND_FONT, "t_ffn", "find_font(14,1) TRADE / DIPLOMACY / status caption"),
    ("DiploWin_draw.trade_text", DRW, 0x4438D6, CENT7, "t_dw_in3", "TRADE caption: inset dp(3)"),
    ("DiploWin_draw.trade_ring_d5a0", DRW, 0x443903, BOX_SPRITE, "t_dw_bm", "TRADE ring"),
    ("DiploWin_draw.diplo_hdr_d618", DRW, 0x443930, BOX_SPRITE, "t_dw_bmdf", "DIPLOMACY header box"),
    ("DiploWin_draw.diplo_text", DRW, 0x44398F, CENT7, "t_dw_in3", "DIPLOMACY caption: inset dp(3)"),
    ("DiploWin_draw.diplo_ring_d5a0", DRW, 0x4439BC, BOX_SPRITE, "t_dw_bm", "DIPLOMACY ring"),
    ("DiploWin_draw.status_hdr_d618", DRW, 0x4439E3, BOX_SPRITE, "t_dw_bmdf", "Communications Link header box"),
    ("DiploWin_draw.status_text", DRW, 0x443BCF, CENT7, "t_dw_in3", "Communications Link caption: inset dp(3)"),
    ("DiploWin_draw_left.font_name", SIDE_L, 0x442A36, FIND_FONT, "t_ffn", "find_font(14,1) faction name"),
    ("DiploWin_draw_left.name_d618", SIDE_L, 0x442B16, BOX_SPRITE, "t_dw_bmdf", "faction name box"),
    ("DiploWin_draw_left.name_text", SIDE_L, 0x442B69, CENT7, "t_dw_in3", "faction name: inset dp(3)"),
    ("DiploWin_draw_left.panel_d528", SIDE_L, 0x442B96, BOX_SPRITE, "t_dw_bmdf", "faction panel box"),
    ("DiploWin_draw_left.art", SIDE_L, 0x442BF8, SPRITE_DRAW2, "t_dw_artL", "faction art: dw_art_rect, g:16 through thunk_art_draw"),
    ("DiploWin_draw_left.font_status", SIDE_L, 0x442C2A, FIND_FONT, "t_ffn", "find_font(14,1) status word"),
    ("DiploWin_draw_left.status_map", SIDE_L, 0x442D44, MAP_COLORS, "t_dw_status", "status box colour map: dw_status_rect"),
    ("DiploWin_draw_left.status_text", SIDE_L, 0x442D8C, CENT7, "t_dw_in3", "status word: inset dp(3)"),
    ("DiploWin_draw_right.font_name", SIDE_R, 0x442DE6, FIND_FONT, "t_ffn", "find_font(14,1) faction name"),
    ("DiploWin_draw_right.name_d618", SIDE_R, 0x442EC6, BOX_SPRITE, "t_dw_bmdf", "faction name box"),
    ("DiploWin_draw_right.name_text", SIDE_R, 0x442F19, CENT7, "t_dw_in3", "faction name: inset dp(3)"),
    ("DiploWin_draw_right.panel_d528", SIDE_R, 0x442F46, BOX_SPRITE, "t_dw_bmdf", "faction panel box"),
    ("DiploWin_draw_right.art", SIDE_R, 0x442FA8, SPRITE_DRAW2, "t_dw_artR", "faction art: dw_art_rect, g:16 through thunk_art_draw"),
    ("DiploWin_draw_right.font_status", SIDE_R, 0x442FDA, FIND_FONT, "t_ffn", "find_font(14,1) status word"),
    ("DiploWin_draw_right.status_map", SIDE_R, 0x4430F5, MAP_COLORS, "t_dw_status", "status box colour map: dw_status_rect"),
    ("DiploWin_draw_right.status_text", SIDE_R, 0x44313D, CENT7, "t_dw_in3", "status word: inset dp(3)"),
    ("DiploWin_draw_offers.font_metrics", OFF_P, 0x44317F, FIND_FONT, "t_ffn", "find_font(14,0) -> the scaled row pitch"),
    ("DiploWin_draw_offers.font_2", OFF_P, 0x4431AE, FIND_FONT, "t_ffn", "find_font(14,2) offer markup font"),
    ("DiploWin_draw_offers.font_1", OFF_P, 0x4431BB, FIND_FONT, "t_ffn", "find_font(14,1) offer markup font"),
    ("DiploWin_draw_offers.font_0", OFF_P, 0x4431C8, FIND_FONT, "t_ffn", "find_font(14,0) offer markup font"),
    ("DiploWin_draw_offers.list_rect", OFF_P, 0x44329D, SET_TEXT_COLOR, "t_dw_offers", "offer list x / top / width: dw_offer_list"),
    ("DiploWinIface_on_mode.railarm_show", ONM, 0x443CBC, SLIDE_SHOW, "thunk_popup_railshow", "slide_show(win,2): the enlarged window's animation rails need the rail gate"),
    ("DiploWinIface_on_mode.railarm_hide", ONM, 0x443D47, SLIDE_HIDE, "thunk_popup_railhide", "slide_hide(win,2): same"),
]

for sid, fn, va, callee, tgt, note in SITES:
    o = orig(va, 5)
    assert o == b"\xE8" + struct.pack("<i", callee - (va + 5)), (sid, o.hex())

# (id, function, va, original pointer, target, note): 4-byte vtable slot repoints
VTABLE_SITES = [
    ("DiploWin_iface_vtbl.on_mode_saveunder", "DiploWinIface_vtbl", IFACE_VTBL0, ONMODE, "t_dw_snap",
     "console save-under snapshot on enter (t_cr_tile_exit restores at the slide_hide exit)"),
]
for sid, fn, va, ptr, tgt, note in VTABLE_SITES:
    assert orig(va, 4) == struct.pack("<I", ptr), (sid, orig(va, 4).hex())

GROUP = "diplowin_scale"
SRC = "src assemble_diplowin.py"
M_SYM = (f"  # ==== {GROUP} symbols (2026-09-26, {SRC}) ====\n", f"# ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} cave ({SRC}; laws scaling_laws.dw_*; parity tests\\test_diplowin_asm_parity.py) ====\n", f"# ==== {GROUP} END ==== cave\n")
M_GRP = (f"  # ==== {GROUP} group ====\n", f"# ==== {GROUP} END ==== groups\n")
M_SITE = (f"  # ==== {GROUP} sites (2026-09-26; {SRC}) ====\n", f"# ==== {GROUP} END ==== sites\n")


def hexs(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def templ(name: str) -> str:
    """cave bytes with inter-cave calls as {rel32:} and push-ret tail jumps as {abs32:} placeholders (engine targets stay literal)."""
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    from capstone.x86 import X86_OP_IMM
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    off, b = OUT[name]
    syms = {v: n for n, v in {**REUSED, **VA}.items()}
    out = []
    for ins in md.disasm(b, PCAVE2 + off):
        raw = hexs(ins.bytes)
        if ins.mnemonic == "call" and ins.size == 5 and ins.operands[0].type == X86_OP_IMM:
            tgt = ins.operands[0].imm & 0xFFFFFFFF
            if tgt in syms:
                raw = f"E8 {{rel32:{syms[tgt]}}}"
        elif ins.mnemonic == "push" and ins.size == 5 and ins.bytes[0] == 0x68:
            tgt = ins.operands[0].imm & 0xFFFFFFFF
            if tgt in syms:
                raw = f"68 {{abs32:{syms[tgt]}}}"
        else:
            for sym_name, sym_va in REUSED.items():           # shared cells (g_cr_*) by name, not by VA
                le = hexs(struct.pack("<I", sym_va))
                if le in raw:
                    raw = raw.replace(le, f"{{abs32:{sym_name}}}")
        out.append(raw)
    return " ".join(out)


def blocks() -> tuple[str, str, str, str]:
    sym = M_SYM[0]
    for n, sz in CELLS:
        sym += f"  {n}:{' ' * max(1, 29 - len(n))}{{ cave: pcave2, offset: {CELL[n] - PCAVE2:#07x}, size: {sz} }}\n"
    for n, (o, b) in OUT.items():
        sym += f"  {n}:{' ' * max(1, 29 - len(n))}{{ cave: pcave2, offset: {o:#07x} }}   # {GROUP} ({len(b)}B)\n"
    sym += M_SYM[1]
    cave = M_CAVE[0]
    for n, (o, _b) in OUT.items():
        cave += f"      - id: {n}\n        offset: {o:#07x}\n        bytes: \"{templ(n)}\"\n"
    cave += M_CAVE[1]
    grp = M_GRP[0] + f"""  - id: {GROUP}
    description: >
      MULTIPLAYER NEGOTIATION WINDOW (DiploWin 0x73ACD8; builder 0x443F10 via diplo 0x444D90, draw 0x4436C0,
      faction sides 0x442A10 / 0x442DC0, offers 0x443170) scales to the popup scale.  Vanilla sized it
      832 x (0x254 - strip) with the strip device-scaled by the HUD bake, so it collapsed (64 px tall at
      4K).  One lever at GraphicWin_init rewrites every stored layout rect from the law (scaling_laws.
      dw_layout: vanilla's cascade at dp() density, cumulative edges, one pinned bar height dp(20),
      panels pinned to the art, frame abutting the scaled rails, chat boxes mixed-space off the device
      seed DC0); painter insets, rings, the MainWin console frames, the status box and the offer lists
      follow through call-site wrappers; frames via the band-map thunks (R-1/B-1), the d690 backdrop via
      devfill; the faction art (scanline-dithered) through thunk_art_draw (the Datalinks recipe); fonts
      via t_ffn; the 11 FlatButtons admitted to the 2D zoom by t_dw_gate (head of the shrink gate chain)
      while g_dw_armed; the slide calls take the rail arm.  Every thunk is a native pass-through at
      g<=16.  Chat log + edit line: a private same-face font at fl(12g/16) (t_dw_chatfont), the history
      scrollbar via a g_netwin_active bracket around TextScroll_attach (t_dw_ts3) + thunk_pref_sbzoom v9 +
      t_dw_gate arrows + thunk_btn_stripes v12; the wheel scrolls it (t_dw_wheel_* chain heads + uimod
      wheel.cpp); console save-under via t_dw_snap on the iface vtbl.  In-game check via the debug
      path (uimod_debug.flag + Scroll Lock -> Ctrl+COMMLINK).  Parity: tests\\test_diplowin_asm_parity.py.
    code_caves:
      - pcave2
    members:
""" + "".join(f"      - {x[0]}\n" for x in SITES + VTABLE_SITES) + M_GRP[1]
    site = M_SITE[0]
    for sid, fn, va, _callee, tgt, note in SITES:
        site += (f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {fn}\n"
                 f"    virtual_addr: 0x{va:08X}\n    length: 5\n"
                 f"    original_bytes: \"{hexs(orig(va, 5))}\"\n"
                 f"    new_bytes:      \"E8 {{rel32:{tgt}}}\"\n"
                 f"    pattern: call_target_redirect\n    # {note}\n")
    for sid, fn, va, _ptr, tgt, note in VTABLE_SITES:
        site += (f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {fn}\n"
                 f"    virtual_addr: 0x{va:08X}\n    length: 4\n"
                 f"    original_bytes: \"{hexs(orig(va, 4))}\"\n"
                 f"    new_bytes:      \"{{abs32:{tgt}}}\"\n"
                 f"    pattern: vtable_repoint\n    # {note}\n")
    site += M_SITE[1]
    return sym, cave, grp, site


RETARGETS = [   # (old, new, what): yaml text swaps, each must match exactly once (idempotent)
    ("E8 {rel32:t_ntw_gate} 85 C0 74 53", "E8 {rel32:t_dw_gate} 85 C0 74 53", "thunk_btn_shrink gate call"),
    ('"E8 {rel32:t_bw_wheel_down}"', '"E8 {rel32:t_dw_wheel_down}"', "wheel keydown site (new chain head)"),
    ('"E8 {rel32:t_bw_wheel_up}"', '"E8 {rel32:t_dw_wheel_up}"', "wheel keyup site (new chain head)"),
]


def main() -> int:
    for n, (o, b) in OUT.items():
        print(f"OK  {n:14s} @0x{o:05X} len={len(b):4d}")
    last = max(o + len(b) for n, (o, b) in OUT.items() if n not in FIXED)
    print(f"cells 0x{BASE_OFF:05X}..0x{CODE_OFF:05X}; code ends 0x{last:05X} (limit 0x{LIMIT_OFF:05X}); sites: {len(SITES)}")
    if "--splice" not in sys.argv:
        return 0
    sym, cave, grp, site = blocks()
    y = pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
    data = y.read_bytes()
    nl = b"\r\n" if b"\r\n" in data[:4096] else b"\n"

    def put_block(data, block, markers, anchor):
        blk = block.replace("\n", nl.decode()).encode("utf-8")
        a, z = markers[0].strip("\n").encode(), markers[1].strip("\n").encode()
        if a in data:
            st = data.index(a)
            st = data.rfind(nl, 0, st) + len(nl)
            e = data.index(z, st) + len(z)
            if data[e:e + len(nl)] == nl:
                e += len(nl)
            assert 0 < st < e
            return data[:st] + blk + data[e:]
        anc = anchor.encode()
        assert data.count(anc) == 1, anchor
        p = data.index(anc) + len(anc)
        p = data.index(nl, p) + len(nl)
        return data[:p] + blk + data[p:]

    data = put_block(data, sym, M_SYM, "# ==== ntw_scale END ==== symbols")
    data = put_block(data, cave, M_CAVE, "# ==== ntw_scale END ==== cave")
    data = put_block(data, grp, M_GRP, "# ==== ntw_scale END ==== groups")
    data = put_block(data, site, M_SITE, "# ==== ntw_scale END ==== sites")
    for old_s, new_s, what in RETARGETS:
        old, new = old_s.encode(), new_s.encode()
        if new not in data:
            assert data.count(old) == 1, f"{what}: not found exactly once"
            data = data.replace(old, new)
    y.write_bytes(data)
    print("spliced into", y)
    return 0


if __name__ == "__main__":
    sys.exit(main())
