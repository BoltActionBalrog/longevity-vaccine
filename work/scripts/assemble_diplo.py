"""Assemble the DIPLOMACY talk-screen bake (group diplo_talk_scale) with keystone.

Prototype: work\\scripts\\hook_diplo_proto.js (v9d speech box USER-VERIFIED 4K+1600 2026-08-17,
v10 console-strip content laws pixel-verified 4K+1600 2026-08-17/18).  Every law here is
vanilla x g/16 with the g<=16 native no-op; the strip half is the MIXED-SPACE class (MainWin
seeds already device-scaled; the +-1/2/3/4/6/0x14/0x16/0x17 constants, the 10/12/14 fonts and
the 1:1 sprite/flic draws were native).

STRIP HALF (this file, part 1) -- all CALL-TARGET REDIRECTS (E8 site -> adapter -> jmp native):
the native callees (Buffer_box_sprite 0x5E2DD3, write_cent_l_7 0x5DD130, Sprite_draw_2
0x5E4B4A) are baked entry-detour thunks KEYED ON THE RETURN ADDRESS, so the adapter must
tail-jmp with [esp] == the original site return (Frida could not host these: attaching at the
cave heads killed the COMMLINK Council face, attaching at the call insns relocated the E8).
  t_dp_table    BaseButton_init #1 @0x440BD9: rebuild the DiploTalkWin rect table 0x20C4..0x2144
                from the MainWin seeds with sc() insets (law diplo_strip_rects), rewrite the
                DATALINKS x/y/w/h args from the fixed 0x2124 (HQINFO/PROFILE inits read the table
                after this call).  Fonts: the 5 Font_init sites -> the existing t_fontinit.
  t_dp_box_*    box_sprite rect fixes: centre frame DC0 inset s4, HQ-button union +-s3, status
                panel split (W+s3)/2 - s3 (stashes the panel rect -> g_dp_panel), HQ panel B-s4
  t_dp_c7_*     write_cent_l_7 rects: BIOSCAN header (20C4 inset s3), HQ name (2114 +s1, h s20)
  t_dp_sd2_*    Sprite_draw_2: colour bar (R-2w', vcentred), faction logo (L+s3, T+s3+fontH+s3;
                stashes w' -> g_dp_logow), HQ picture (hcentred, T+s1+s20+s1), slide_show bezel
                (num/den only); all num/den = g/16
  t_dp_cent6    wrap_cent_6 name rect {L+s3, T+s3+s2, R-s3, T+s3+fontH}; returns ret+(s3-3) so the
                engine's native +3 lands the first text line at ret'+s3
  t_dp_txt      wrap_3 / write_l_3 status lines: x = panel.L+s3+s2+logow'+s3, w = panel.R-2*s3-x
  t_dp_news_*   news panel: separator y = T+s1+sc(sprH) (get_pixel + hline), text x = L+sc(5),
                y chain sep+s4 / +fontH(A6C) / +fontH(A44)  (all land off-strip, as vanilla clips)
  t_dp_flinit   Flic_init x,y: bioscan literals (26,90) -> sc; news = 20E4.L+s1, 20E4.T+s1+H/4
  t_dp_flicdraw Flic_draw_frame dst-bounce (thunk_band_draw law) for the two diplo flics, one
                persistent native scratch per flic, copy_3 NN stretch x g/16 + scaled dirty rect
  thunk_btn_gate v8: +3 statics (DATALINKS/PROFILE/HQINFO FlatButtons -> shrink/2D-zoom frames)

Output: prints the yaml fragments and writes work\\patches\\_fragment_diplo_*.yaml (each keeps its own EOL; an
unchanged fragment is not rewritten); splice with `py assemble_diplo.py --splice` (idempotent, marker-guarded: the
blocks are replaced in place, patches.yaml keeps its EOL, a no-op run does not write).  `--out-dir` / `--yaml` point
both at copies (tests: test_diplo_assembler_io.py).
"""
from __future__ import annotations

import os
import re
import sys

import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2_VA = 0xA0C000
BASE_OFF = 0x11560           # first free cell after thunk_comm_rowrect (0x11500..0x11551)
SECTION_END = 0x31000        # pcave2's CURRENT length in patches.yaml (this bake grew it 0x12000 -> 0x14000; later
                             # bakes to 0x31000, and t_cr_tile v3 / t_cr_tile_exit sit past 0x14000 since 2026-09-26)
G = 0x668740                 # g_popup_scale_num
TW = 0x733990                # DiploTalkWin
MW = 0x7AE820
MW_CANVAS = 0x7AEC64
BOX_SPRITE = 0x5E2DD3
CENT7 = 0x5DD130
SPRITE_DRAW_2 = 0x5E4B4A
WRAP_CENT_6 = 0x5DDAB0
WRAP_3 = 0x5DD730
WRITE_L_3 = 0x5DCEA0
GET_PIXEL = 0x5E2210
HLINE_2 = 0x5E1A80
FLIC_INIT = 0x629E50
FLIC_DRAW = 0x62A070
BASEBTN_INIT = 0x607210
CRT_MALLOC = 0x64558A
BUF_CTOR = 0x5D7210
BUF_RESIZE = 0x5D79C0
BUF_COPY_3 = 0x5D9610
SEED = {"D80": 0x7AF5A0, "D90": 0x7AF5B0, "DB0": 0x7AF5D0, "DC0": 0x7AF5E0, "A8C": 0x7AF2AC, "A9C": 0x7AF2BC}
FLIC_NEWS = TW + 0xAE8
FLIC_BIO = TW + 0x15CC

# ---- data cells (zero-init section padding, reserved by symbol entries) ----
CELLS = [("g_dp_panel", 16), ("g_dp_logow", 4), ("g_dp_sepy", 4), ("g_dp_newsy", 4),
         ("g_dp_scr_news", 4), ("g_dp_scr_bio", 4)]
CELL_VA = {}
_off = BASE_OFF
for _n, _sz in CELLS:
    CELL_VA[_n] = PCAVE2_VA + _off
    _off += _sz
THUNKS_OFF = (_off + 15) & ~15

_lbl = [0]


def sc(reg: str) -> str:
    """reg = floor(reg*g/16) (caller guarantees g>16). Clobbers flags."""
    return f"imul {reg}, dword ptr [{G:#x}]\nsar {reg}, 4\n"


def sck(reg: str, k: int) -> str:
    return f"mov {reg}, {k}\n" + sc(reg)


def gate_native(target: int) -> str:
    """g<=16 -> tail-jmp the native callee (registers/stack untouched)."""
    _lbl[0] += 1
    return f"cmp dword ptr [{G:#x}], 0x10\njg gn_{_lbl[0]}\njmp {target:#x}\ngn_{_lbl[0]}:\n"


def fontH(freg_out: str, font_va: int) -> str:
    """freg_out = engine line-height idiom of Font at font_va: [f]<0 ? [f+0xC] : [f+0x10]+[f]. Uses edx as scratch."""
    _lbl[0] += 1
    n = _lbl[0]
    return (f"mov edx, dword ptr [{font_va:#x}]\n"
            f"test edx, edx\n"
            f"js fh_neg_{n}\n"
            f"mov {freg_out}, dword ptr [{font_va + 0x10:#x}]\n"
            f"add {freg_out}, edx\n"
            f"jmp fh_done_{n}\n"
            f"fh_neg_{n}:\n"
            f"mov {freg_out}, dword ptr [{font_va + 0xC:#x}]\n"
            f"fh_done_{n}:\n")


THUNK_ASM: dict[str, str] = {}


def T(name: str, asm: str) -> None:
    THUNK_ASM[name] = asm


# ---------------------------------------------------------------------------
# t_dp_table: BaseButton_init #1 (0x440BD9).  [esp]=ret +4 label +8 id +C x +10 y +14 w +18 h.
# Frame: push ebp/mov ebp,esp -> [ebp+8]=label .. [ebp+0x10]=x [ebp+0x14]=y [ebp+0x18]=w [ebp+0x1C]=h
# locals: [ebp-4]=s1 -8=s2 -C=s3 -10=s4 -14=s6 -18=s7 -1C=s20 -20=s24 -24=s26 -28=s30 -2C=flcWd -30=hh -34=nwL
# ---------------------------------------------------------------------------
def _sc_local(k: int, off: int) -> str:
    return f"mov eax, {k}\n{sc('eax')}mov dword ptr [ebp-{off:#x}], eax\n"


def _rect_store(base: int, L: str, Tt: str, R: str, B: str) -> str:
    """store four already-computed register/expr values (each an asm snippet leaving eax) into TW+base"""
    return (f"{L}mov dword ptr [{TW + base:#x}], eax\n"
            f"{Tt}mov dword ptr [{TW + base + 4:#x}], eax\n"
            f"{R}mov dword ptr [{TW + base + 8:#x}], eax\n"
            f"{B}mov dword ptr [{TW + base + 12:#x}], eax\n")


def seed(name: str, i: int) -> str:            # eax = seed field
    return f"mov eax, dword ptr [{SEED[name] + 4 * i:#x}]\n"


def loc(off: int, op: str = "add") -> str:      # eax op= local
    return f"{op} eax, dword ptr [ebp-{off:#x}]\n"


T("t_dp_table", (
    gate_native(BASEBTN_INIT) +
    "push ebp\nmov ebp, esp\nsub esp, 0x40\npushad\n" +
    "".join(_sc_local(k, o) for k, o in ((1, 4), (2, 8), (3, 0xC), (4, 0x10), (6, 0x14), (7, 0x18), (20, 0x1C), (24, 0x20), (26, 0x24), (30, 0x28))) +
    # flcW native = 20E4.R - 20E4.L - 2 ; flcWd = sc(flcW+2)
    f"mov eax, dword ptr [{TW + 0x20EC:#x}]\nsub eax, dword ptr [{TW + 0x20E4:#x}]\n{sc('eax')}mov dword ptr [ebp-0x2C], eax\n" +
    # hq2144 = {D90.R - A9C.R + D90.L, A8C.T, A8C.L - s3, A8C.B}
    _rect_store(0x2144,
                seed("D90", 2) + f"sub eax, dword ptr [{SEED['A9C'] + 8:#x}]\nadd eax, dword ptr [{SEED['D90']:#x}]\n",
                seed("A8C", 1),
                seed("A8C", 0) + loc(0xC, "sub"),
                seed("A8C", 3)) +
    # hq2114 = {D90.L+s4, D90.T+s4, D90.R-s4, 2144.T - s6}
    _rect_store(0x2114,
                seed("D90", 0) + loc(0x10),
                seed("D90", 1) + loc(0x10),
                seed("D90", 2) + loc(0x10, "sub"),
                f"mov eax, dword ptr [{TW + 0x2148:#x}]\n" + loc(0x14, "sub")) +
    # r2104 = DB0 inset s4
    _rect_store(0x2104,
                seed("DB0", 0) + loc(0x10), seed("DB0", 1) + loc(0x10),
                seed("DB0", 2) + loc(0x10, "sub"), seed("DB0", 3) + loc(0x10, "sub")) +
    # c = DC0 inset s7 -> 20F4 (B = DC0.B - s30); hh = (W + s3) >> 1
    _rect_store(0x20F4,
                seed("DC0", 0) + loc(0x18), seed("DC0", 1) + loc(0x18),
                seed("DC0", 2) + loc(0x18, "sub"), seed("DC0", 3) + loc(0x28, "sub")) +
    f"mov eax, dword ptr [{TW + 0x20FC:#x}]\nsub eax, dword ptr [{TW + 0x20F4:#x}]\nadd eax, dword ptr [ebp-0xC]\nsar eax, 1\nmov dword ptr [ebp-0x30], eax\n" +
    # cB (button bottom) = DC0.B - s7 (the centre rect bottom before the -0x17): keep in ebx
    seed("DC0", 3) + loc(0x18, "sub") + "mov ebx, eax\n" +
    # dl2124 = {c.L, cB - s20, c.L + hh - s3, cB}
    _rect_store(0x2124,
                f"mov eax, dword ptr [{TW + 0x20F4:#x}]\n",
                "mov eax, ebx\n" + loc(0x1C, "sub"),
                f"mov eax, dword ptr [{TW + 0x20F4:#x}]\nadd eax, dword ptr [ebp-0x30]\n" + loc(0xC, "sub"),
                "mov eax, ebx\n") +
    # pr2134 = {c.L + hh, cB - s20, c.L + 2hh - s3, cB}
    _rect_store(0x2134,
                f"mov eax, dword ptr [{TW + 0x20F4:#x}]\nadd eax, dword ptr [ebp-0x30]\n",
                "mov eax, ebx\n" + loc(0x1C, "sub"),
                f"mov eax, dword ptr [{TW + 0x20F4:#x}]\nadd eax, dword ptr [ebp-0x30]\nadd eax, dword ptr [ebp-0x30]\n" + loc(0xC, "sub"),
                "mov eax, ebx\n") +
    # nw2 = {D80.R - s4 - flcWd, D80.T + s4, D80.R - s4, D80.B - s4}
    _rect_store(0x20E4,
                seed("D80", 2) + loc(0x10, "sub") + loc(0x2C, "sub") + "mov dword ptr [ebp-0x34], eax\n",
                seed("D80", 1) + loc(0x10),
                seed("D80", 2) + loc(0x10, "sub"),
                seed("D80", 3) + loc(0x10, "sub")) +
    # bh20C4 = {D80.L+s4, D80.T+s4, nwL - s3, D80.T + s24}
    _rect_store(0x20C4,
                seed("D80", 0) + loc(0x10), seed("D80", 1) + loc(0x10),
                "mov eax, dword ptr [ebp-0x34]\n" + loc(0xC, "sub"),
                seed("D80", 1) + loc(0x20)) +
    # bb20D4 = {D80.L+s4, D80.T+s26, nwL - s3, D80.B - s4}
    _rect_store(0x20D4,
                seed("D80", 0) + loc(0x10), seed("D80", 1) + loc(0x24),
                "mov eax, dword ptr [ebp-0x34]\n" + loc(0xC, "sub"),
                seed("D80", 3) + loc(0x10, "sub")) +
    # args from 2124: x, y, w, h
    f"mov eax, dword ptr [{TW + 0x2124:#x}]\nmov dword ptr [ebp+0x10], eax\n"
    f"mov eax, dword ptr [{TW + 0x2128:#x}]\nmov dword ptr [ebp+0x14], eax\n"
    f"mov eax, dword ptr [{TW + 0x212C:#x}]\nsub eax, dword ptr [{TW + 0x2124:#x}]\nmov dword ptr [ebp+0x18], eax\n"
    f"mov eax, dword ptr [{TW + 0x2130:#x}]\nsub eax, dword ptr [{TW + 0x2128:#x}]\nmov dword ptr [ebp+0x1C], eax\n"
    "popad\nmov esp, ebp\npop ebp\n"
    f"jmp {BASEBTN_INIT:#x}\n"))

# ---------------------------------------------------------------------------
# box_sprite adapters: [esp]=ret +4 rect* +8 set ; ecx=dest (preserve) ; jmp 0x5E2DD3
# ---------------------------------------------------------------------------
def _box(name: str, body: str) -> None:
    T(name, gate_native(BOX_SPRITE) + "push ebx\npush esi\nmov esi, dword ptr [esp+0xC]\n" + body + f"pop esi\npop ebx\njmp {BOX_SPRITE:#x}\n")


# centre frame: DC0 inset s4
_box("t_dp_box_centre",
     sck("ebx", 4) +
     f"mov eax, dword ptr [{SEED['DC0']:#x}]\nadd eax, ebx\nmov dword ptr [esi], eax\n"
     f"mov eax, dword ptr [{SEED['DC0'] + 4:#x}]\nadd eax, ebx\nmov dword ptr [esi+4], eax\n"
     f"mov eax, dword ptr [{SEED['DC0'] + 8:#x}]\nsub eax, ebx\nmov dword ptr [esi+8], eax\n"
     f"mov eax, dword ptr [{SEED['DC0'] + 12:#x}]\nsub eax, ebx\nmov dword ptr [esi+12], eax\n")

# HQ-button union: min/max of A8C, A9C, 2144' then -+s3.  (vanilla UnionRect then +-3)
_box("t_dp_box_hqunion",
     sck("ebx", 3) +
     # L = min(A8C.L, A9C.L, 2144.L) - s3
     f"mov eax, dword ptr [{SEED['A8C']:#x}]\nmov edx, dword ptr [{SEED['A9C']:#x}]\ncmp edx, eax\njge u1\nmov eax, edx\nu1:\nmov edx, dword ptr [{TW + 0x2144:#x}]\ncmp edx, eax\njge u2\nmov eax, edx\nu2:\nsub eax, ebx\nmov dword ptr [esi], eax\n"
     f"mov eax, dword ptr [{SEED['A8C'] + 4:#x}]\nmov edx, dword ptr [{SEED['A9C'] + 4:#x}]\ncmp edx, eax\njge u3\nmov eax, edx\nu3:\nmov edx, dword ptr [{TW + 0x2148:#x}]\ncmp edx, eax\njge u4\nmov eax, edx\nu4:\nsub eax, ebx\nmov dword ptr [esi+4], eax\n"
     f"mov eax, dword ptr [{SEED['A8C'] + 8:#x}]\nmov edx, dword ptr [{SEED['A9C'] + 8:#x}]\ncmp edx, eax\njle u5\nmov eax, edx\nu5:\nmov edx, dword ptr [{TW + 0x214C:#x}]\ncmp edx, eax\njle u6\nmov eax, edx\nu6:\nadd eax, ebx\nmov dword ptr [esi+8], eax\n"
     f"mov eax, dword ptr [{SEED['A8C'] + 12:#x}]\nmov edx, dword ptr [{SEED['A9C'] + 12:#x}]\ncmp edx, eax\njle u7\nmov eax, edx\nu7:\nmov edx, dword ptr [{TW + 0x2150:#x}]\ncmp edx, eax\njle u8\nmov eax, edx\nu8:\nadd eax, ebx\nmov dword ptr [esi+12], eax\n")

# status panel i: c=20F4', hh=(W+s3)>>1, i = (rect.L == c.L) ? 0 : 1 ; rect = {c.L+i*hh, c.T, c.L+i*hh+hh-s3, c.B}; stash -> g_dp_panel
_box("t_dp_box_panel",
     sck("ebx", 3) +
     f"mov eax, dword ptr [{TW + 0x20FC:#x}]\nsub eax, dword ptr [{TW + 0x20F4:#x}]\nadd eax, ebx\nsar eax, 1\n"          # eax = hh
     f"mov edx, dword ptr [{TW + 0x20F4:#x}]\ncmp dword ptr [esi], edx\nje p0\nadd edx, eax\np0:\n"                       # edx = L_i
     "mov dword ptr [esi], edx\nadd edx, eax\nsub edx, ebx\nmov dword ptr [esi+8], edx\n"
     f"mov eax, dword ptr [{TW + 0x20F8:#x}]\nmov dword ptr [esi+4], eax\nmov eax, dword ptr [{TW + 0x2100:#x}]\nmov dword ptr [esi+12], eax\n"
     f"mov eax, dword ptr [esi]\nmov dword ptr [{CELL_VA['g_dp_panel']:#x}], eax\n"
     f"mov eax, dword ptr [esi+4]\nmov dword ptr [{CELL_VA['g_dp_panel'] + 4:#x}], eax\n"
     f"mov eax, dword ptr [esi+8]\nmov dword ptr [{CELL_VA['g_dp_panel'] + 8:#x}], eax\n"
     f"mov eax, dword ptr [esi+12]\nmov dword ptr [{CELL_VA['g_dp_panel'] + 12:#x}], eax\n")

# HQ panel: {2114.L, T, R, B - s4}   (vanilla copies 2114 then B-=4)
_box("t_dp_box_hq",
     sck("ebx", 4) +
     f"mov eax, dword ptr [{TW + 0x2120:#x}]\nsub eax, ebx\nmov dword ptr [esi+12], eax\n")

# ---------------------------------------------------------------------------
# write_cent_l_7 adapters: [esp]=ret +4 str +8 rect* +C len ; ecx=dest ; jmp 0x5DD130
# ---------------------------------------------------------------------------
def _c7(name: str, body: str) -> None:
    T(name, gate_native(CENT7) + "push ebx\npush esi\nmov esi, dword ptr [esp+0x10]\n" + body + f"pop esi\npop ebx\njmp {CENT7:#x}\n")


_c7("t_dp_c7_bio",  # 20C4 inset s3
    sck("ebx", 3) +
    f"mov eax, dword ptr [{TW + 0x20C4:#x}]\nadd eax, ebx\nmov dword ptr [esi], eax\n"
    f"mov eax, dword ptr [{TW + 0x20C8:#x}]\nadd eax, ebx\nmov dword ptr [esi+4], eax\n"
    f"mov eax, dword ptr [{TW + 0x20CC:#x}]\nsub eax, ebx\nmov dword ptr [esi+8], eax\n"
    f"mov eax, dword ptr [{TW + 0x20D0:#x}]\nsub eax, ebx\nmov dword ptr [esi+12], eax\n")
_c7("t_dp_c7_hq",   # {2114.L+s1, T+s1, R-s1, T+s1+s20}
    sck("ebx", 1) +
    f"mov eax, dword ptr [{TW + 0x2114:#x}]\nadd eax, ebx\nmov dword ptr [esi], eax\n"
    f"mov eax, dword ptr [{TW + 0x2118:#x}]\nadd eax, ebx\nmov dword ptr [esi+4], eax\n"
    f"mov eax, dword ptr [{TW + 0x211C:#x}]\nsub eax, ebx\nmov dword ptr [esi+8], eax\n"
    f"mov eax, dword ptr [{TW + 0x2118:#x}]\nadd eax, ebx\n" + sck("edx", 20) + "add eax, edx\nmov dword ptr [esi+12], eax\n")

# ---------------------------------------------------------------------------
# Sprite_draw_2 adapters: ecx=sprite (w +0x18, h +0x1C) ; [esp]=ret +4 dest +8 key +C x +10 y +14 num +18 den ; jmp 0x5E4B4A
# ---------------------------------------------------------------------------
ART_DRAW = PCAVE2_VA + 0x29EB0   # thunk_art_draw (assemble_artreblit.py): Sprite_draw_2 drop-in + edge-pinned parity re-blit
SPR_STRIPES = PCAVE2_VA + 0xF9E4  # t_spr_stripes (assemble_stripes_spr.py): Sprite_draw_2 drop-in, per-texel stripe regenerate
PARITY_NN = PCAVE2_VA + 0x213C0  # t_rwk_parity_nn (assemble_rw_kinds.py): Sprite_draw_2 drop-in, parity NN on the stripe law


def _sd2(name: str, body: str, tail: int = SPRITE_DRAW_2) -> None:
    T(name, gate_native(SPRITE_DRAW_2) + "push ebx\npush esi\npush edi\n"                       # args now at [esp+0x10]..
            "mov esi, esp\n" + body +
            f"mov eax, dword ptr [{G:#x}]\nmov dword ptr [esi+0x20], eax\nmov dword ptr [esi+0x24], 16\n"  # num/den = g/16 (after the 3 pushes: x=[esi+0x18] y=[esi+0x1C] num=[esi+0x20] den=[esi+0x24])
            f"pop edi\npop esi\npop ebx\njmp {tail:#x}\n")


# colour bar: x = 20D4.R - 2*w' ; y = 20D4.T + ((H - h') >> 1)   (H = 20D4 height, uninset as vanilla)
# 2026-09-21: tail = thunk_art_draw -- the 9x147 bar is a 1-row scanline dither (bright row / dark dithered row) and
# the engine NN banded it at g=22/25 (user's 1600 + 1920 shots 184025 / 184052: row runs 2,2,1,2,1,2); 4K clean (3/2).
_sd2("t_dp_sd2_bar",
     "mov eax, dword ptr [ecx+0x18]\n" + sc("eax") + f"mov edx, dword ptr [{TW + 0x20DC:#x}]\nsub edx, eax\nsub edx, eax\nmov dword ptr [esi+0x18], edx\n"
     "mov eax, dword ptr [ecx+0x1C]\n" + sc("eax") + f"mov edx, dword ptr [{TW + 0x20E0:#x}]\nsub edx, dword ptr [{TW + 0x20D8:#x}]\nsub edx, eax\nmov eax, edx\ncdq\nsub eax, edx\nsar eax, 1\nadd eax, dword ptr [{TW + 0x20D8:#x}]\nmov dword ptr [esi+0x1C], eax\n",
     tail=ART_DRAW)
# faction logo: x = panel.L + s3 ; y = panel.T + s3 + fontH(A6C) + s3 ; stash w' -> g_dp_logow
_sd2("t_dp_sd2_logo",
     "mov eax, dword ptr [ecx+0x18]\n" + sc("eax") + f"mov dword ptr [{CELL_VA['g_dp_logow']:#x}], eax\n" +
     sck("ebx", 3) +
     f"mov eax, dword ptr [{CELL_VA['g_dp_panel']:#x}]\nadd eax, ebx\nmov dword ptr [esi+0x18], eax\n" +
     "push ecx\n" + fontH("edi", TW + 0xA6C) + "pop ecx\n" +
     f"mov eax, dword ptr [{CELL_VA['g_dp_panel'] + 4:#x}]\nadd eax, ebx\nadd eax, edi\nadd eax, ebx\nmov dword ptr [esi+0x1C], eax\n",
     tail=SPR_STRIPES)
# (2026-10-05: tail=PARITY_NN was tried for the logo and withdrawn with the SE icons -- t_rwk_parity_nn reorders rows and
#  blends columns on art that is not a strict row-pair dither; user: "shadowed and a bit blurry".)
# HQ picture: L0 = 2114.L+s1, R0 = 2114.R-s1 ; x = L0 + ((R0-L0) - w')>>1 ; y = 2114.T + s1 + s20 + s1
_sd2("t_dp_sd2_hqpic",
     sck("ebx", 1) +
     "mov eax, dword ptr [ecx+0x18]\n" + sc("eax") + "mov edi, eax\n"                          # edi = w'
     f"mov edx, dword ptr [{TW + 0x211C:#x}]\nsub edx, ebx\nmov eax, dword ptr [{TW + 0x2114:#x}]\nadd eax, ebx\nsub edx, eax\nsub edx, edi\nmov edi, eax\nmov eax, edx\ncdq\nsub eax, edx\nsar eax, 1\nadd eax, edi\nmov dword ptr [esi+0x18], eax\n"
     f"mov eax, dword ptr [{TW + 0x2118:#x}]\nadd eax, ebx\nadd eax, ebx\n" + sck("edx", 20) + "add eax, edx\nmov dword ptr [esi+0x1C], eax\n",
     tail=ART_DRAW)   # the landscape is scanline-dithered: the engine NN banded it at g=22/25
# slide_show bezel: only num/den (x,y seed-scaled by the engine); guard native 1/1
T("t_dp_sd2_bezel",
  gate_native(SPRITE_DRAW_2) +
  f"cmp dword ptr [esp+0x14], 1\njne bz_n\ncmp dword ptr [esp+0x18], 1\njne bz_n\n"
  f"mov eax, dword ptr [{G:#x}]\nmov dword ptr [esp+0x14], eax\nmov dword ptr [esp+0x18], 16\nbz_n:\njmp {SPRITE_DRAW_2:#x}\n")

# ---------------------------------------------------------------------------
# wrap_cent_6 (str, rect*) thiscall RET 8: rect = {p.L+s3, p.T+s3+s2, p.R-s3, p.T+s3+fontH(A6C)} ; return ret + (s3-3)
# ---------------------------------------------------------------------------
T("t_dp_cent6",
  gate_native(WRAP_CENT_6) +
  "push ebx\npush esi\npush edi\nmov esi, dword ptr [esp+0x14]\n" +          # rect*
  sck("ebx", 3) +
  f"mov eax, dword ptr [{CELL_VA['g_dp_panel']:#x}]\nadd eax, ebx\nmov dword ptr [esi], eax\n"
  f"mov eax, dword ptr [{CELL_VA['g_dp_panel'] + 8:#x}]\nsub eax, ebx\nmov dword ptr [esi+8], eax\n" +
  sck("edx", 2) + f"mov eax, dword ptr [{CELL_VA['g_dp_panel'] + 4:#x}]\nadd eax, ebx\nadd eax, edx\nmov dword ptr [esi+4], eax\n" +
  "push ecx\n" + fontH("edi", TW + 0xA6C) + "pop ecx\n" +
  f"mov eax, dword ptr [{CELL_VA['g_dp_panel'] + 4:#x}]\nadd eax, ebx\nadd eax, edi\nmov dword ptr [esi+12], eax\n"
  # call the native with copies of the args, then adjust the return
  "push esi\npush dword ptr [esp+0x14]\n"                                        # rect, str (str at [esp+0x10] before this push)
  f"call {WRAP_CENT_6:#x}\n"
  "add eax, ebx\nsub eax, 3\n"
  "pop edi\npop esi\npop ebx\nret 8\n")

# ---------------------------------------------------------------------------
# status text: wrap_3 (str,x,y,w) / write_l_3 (str,x,y,len): x = p.L+s3+s2+logow'+s3 ; wrap_3 also w = p.R-2*s3-x
# [esp]=ret +4 str +8 x +C y +10 w|len
# ---------------------------------------------------------------------------
_TXT_X = (sck("eax", 3) + "mov edx, eax\nadd edx, eax\n" + sck("eax", 2) + "add edx, eax\n"          # edx = 2*s3 + s2
          f"add edx, dword ptr [{CELL_VA['g_dp_logow']:#x}]\nadd edx, dword ptr [{CELL_VA['g_dp_panel']:#x}]\nmov dword ptr [esp+8], edx\n")
_TXT_W = (sck("eax", 3) + f"add eax, eax\nmov edx, dword ptr [{CELL_VA['g_dp_panel'] + 8:#x}]\nsub edx, eax\nsub edx, dword ptr [esp+8]\n"
          "mov dword ptr [esp+0x10], edx\n")
T("t_dp_txt_wrap3",
  gate_native(WRAP_3) + _TXT_X + _TXT_W +
  f"jmp {WRAP_3:#x}\n")
T("t_dp_txt_wl3",
  gate_native(WRITE_L_3) + _TXT_X + f"jmp {WRITE_L_3:#x}\n")

# ---------------------------------------------------------------------------
# news panel: get_pixel (x,y): x = 20E4.L, y = 20E4.T + s1 + sc(sprH[20B4]) -> g_dp_sepy ; hline (x0,x1,y,c): L+s1, R-s1, sepy ;
# write_l_3 sites: x = 20E4.L + s5 ; y1 = sepy + s4 ; y2 = y1 + fontH(A6C) ; y3 = y2 + fontH(A44)   (g_dp_newsy chain)
# ---------------------------------------------------------------------------
T("t_dp_news_sep",
  gate_native(GET_PIXEL) +
  f"mov eax, dword ptr [{TW + 0x20E4:#x}]\nmov dword ptr [esp+4], eax\n"
  f"mov edx, dword ptr [{TW + 0x20B4:#x}]\nmov eax, dword ptr [edx+0x1C]\n" + sc("eax") + "mov edx, eax\n" + sck("eax", 1) +
  f"add eax, edx\nadd eax, dword ptr [{TW + 0x20E8:#x}]\nmov dword ptr [esp+8], eax\nmov dword ptr [{CELL_VA['g_dp_sepy']:#x}], eax\n"
  f"jmp {GET_PIXEL:#x}\n")
T("t_dp_news_hline",
  gate_native(HLINE_2) +
  sck("eax", 1) + f"mov edx, dword ptr [{TW + 0x20E4:#x}]\nadd edx, eax\nmov dword ptr [esp+4], edx\n"
  f"mov edx, dword ptr [{TW + 0x20EC:#x}]\nsub edx, eax\nmov dword ptr [esp+8], edx\n"
  f"mov eax, dword ptr [{CELL_VA['g_dp_sepy']:#x}]\nmov dword ptr [esp+0xC], eax\n"
  f"jmp {HLINE_2:#x}\n")
_NEWS_X = sck("eax", 5) + f"add eax, dword ptr [{TW + 0x20E4:#x}]\nmov dword ptr [esp+8], eax\n"
T("t_dp_news_t1",
  gate_native(WRITE_L_3) + _NEWS_X + sck("eax", 4) + f"add eax, dword ptr [{CELL_VA['g_dp_sepy']:#x}]\nmov dword ptr [{CELL_VA['g_dp_newsy']:#x}], eax\nmov dword ptr [esp+0xC], eax\njmp {WRITE_L_3:#x}\n")
T("t_dp_news_t2",
  gate_native(WRITE_L_3) + _NEWS_X + fontH("eax", TW + 0xA6C) + f"add eax, dword ptr [{CELL_VA['g_dp_newsy']:#x}]\nmov dword ptr [{CELL_VA['g_dp_newsy']:#x}], eax\nmov dword ptr [esp+0xC], eax\njmp {WRITE_L_3:#x}\n")
T("t_dp_news_t3",
  gate_native(WRITE_L_3) + _NEWS_X + fontH("eax", TW + 0xA44) + f"add eax, dword ptr [{CELL_VA['g_dp_newsy']:#x}]\nmov dword ptr [{CELL_VA['g_dp_newsy']:#x}], eax\nmov dword ptr [esp+0xC], eax\njmp {WRITE_L_3:#x}\n")

# ---------------------------------------------------------------------------
# Flic_init (this; dst, name, x, y, flag): [esp]=ret +4 dst +8 name +C x +10 y +14 flag
# ---------------------------------------------------------------------------
T("t_dp_flinit_bio",
  gate_native(FLIC_INIT) +
  "mov eax, dword ptr [esp+0xC]\n" + sc("eax") + "mov dword ptr [esp+0xC], eax\n"
  "mov eax, dword ptr [esp+0x10]\n" + sc("eax") + "mov dword ptr [esp+0x10], eax\n"
  f"jmp {FLIC_INIT:#x}\n")
T("t_dp_flinit_news",
  gate_native(FLIC_INIT) +
  sck("eax", 1) + f"mov edx, dword ptr [{TW + 0x20E4:#x}]\nadd edx, eax\nmov dword ptr [esp+0xC], edx\n"
  f"mov edx, dword ptr [{TW + 0x20F0:#x}]\nsub edx, dword ptr [{TW + 0x20E8:#x}]\nsar edx, 2\nadd edx, eax\nadd edx, dword ptr [{TW + 0x20E8:#x}]\nmov dword ptr [esp+0x10], edx\n"
  f"jmp {FLIC_INIT:#x}\n")

# ---------------------------------------------------------------------------
# Flic_draw_frame dst-bounce for the two diplo flics (thunk_band_draw law).  thiscall(flic; x,y) RET 8.
# scratch slot: ecx==FLIC_NEWS -> g_dp_scr_news, ecx==FLIC_BIO -> g_dp_scr_bio, else native.
# ---------------------------------------------------------------------------
T("t_dp_flicdraw", f"""
    cmp dword ptr [{G:#x}], 0x10
    jle native
    mov eax, {CELL_VA['g_dp_scr_news']:#x}
    cmp ecx, {FLIC_NEWS:#x}
    je slot
    mov eax, {CELL_VA['g_dp_scr_bio']:#x}
    cmp ecx, {FLIC_BIO:#x}
    jne native
slot:
    push ebp
    mov ebp, esp
    push ebx
    push esi
    push edi
    mov esi, ecx
    mov ebx, eax
    mov edi, dword ptr [ebx]
    test edi, edi
    jnz have
    push 0x588
    call {CRT_MALLOC:#x}
    add esp, 4
    test eax, eax
    je bail
    mov edi, eax
    mov ecx, edi
    call {BUF_CTOR:#x}
    mov eax, dword ptr [esi+0x59C]
    mov edx, dword ptr [esi+0x5A0]
    push edx
    push eax
    mov ecx, edi
    call {BUF_RESIZE:#x}
    mov dword ptr [ebx], edi
have:
    mov ebx, dword ptr [esi+0x5A8]
    mov dword ptr [esi+0x5A8], edi
    push 0
    push 0
    mov ecx, esi
    call {FLIC_DRAW:#x}
    mov dword ptr [esi+0x5A8], ebx
    mov eax, dword ptr [ebp+8]
    mov dword ptr [esi+0x5AC], eax
    mov eax, dword ptr [ebp+12]
    mov dword ptr [esi+0x5B0], eax
    mov ecx, dword ptr [{G:#x}]
    mov eax, dword ptr [esi+0x59C]
    imul eax, ecx
    sar eax, 4
    mov edx, dword ptr [esi+0x5A0]
    imul edx, ecx
    sar edx, 4
    mov ecx, dword ptr [ebp+8]
    mov dword ptr [esi+0x58C], ecx
    add ecx, eax
    mov dword ptr [esi+0x594], ecx
    mov ecx, dword ptr [ebp+12]
    mov dword ptr [esi+0x590], ecx
    add ecx, edx
    mov dword ptr [esi+0x598], ecx
    push edx
    push eax
    push dword ptr [ebp+12]
    push dword ptr [ebp+8]
    push dword ptr [esi+0x5A0]
    push dword ptr [esi+0x59C]
    push 0
    push 0
    push ebx
    mov ecx, edi
    call {BUF_COPY_3:#x}
    xor eax, eax
    pop edi
    pop esi
    pop ebx
    pop ebp
    ret 8
bail:
    mov ecx, esi
    pop edi
    pop esi
    pop ebx
    pop ebp
native:
    jmp {FLIC_DRAW:#x}
""")


# ===========================================================================================
# POPUP HALF -- the anchored speech box (proto levers A/F/T/X/K/H/E/C/W/M/G/B/Y/Q/R/P).  Anchored
# == [popup+0xA14]==DiploTalkWin (esi=popup in BasePop_calc / exec_3 / on_draw_background).  In
# the two type-16 Dialog sites the popup is reached through the Dialog subobject in esi:
# Dialog_type16_attach this = popup+0x2C44 (site 0x60D299 -> [esi-0x2230]) and Dialog_type16_calc
# this = popup+0x2214 (site 0x60D717 -> [esi-0x1800]); there the test is the engine's own ext
# branch condition [+0xA14] != 0 (law scaling_laws.t16_row_window_anchored).  2026-09-26: these
# two used to key on talkOpen ([DiploTalkWin+0xA94]!=-1), which also caught every ORDINARY popup
# raised mid-talk (#ASKSEEDESIGN after a tech trade: rows drawn native-wide -- 655 px beside a 1642-px
# OK bar at 4K, _Problems/NewDesignsOverDiplo.png).  Both gate fixes kept their slots and sizes
# (t_dp_q16fixed 63 B, t_dp_q16gate 19 B).
# ===========================================================================================
GWIN_FILL_2 = 0x5D5350
THUNK_BOX_THICK = 0x668E00        # menu_strip_thunks(0x668200)+0xC00
THUNK_DEVFILL = 0xA102A0          # pcave2+0x42A0
THUNK_SCALE_BOXW = 0xA16F00       # pcave2+0xAF00
THUNK_GROW_BOX = 0x668A00         # menu_strip+0x800
THUNK_BTN_VCENTER = 0xA0C220      # pcave2+0x220
THUNK_ORN_CHILDX = 0xA1BB90       # pcave2+0xFB90
THUNK_Q16_FILL = 0xA1D000         # pcave2+0x11000
THUNK_FACTION_WRAPWIDTH = 0xA12E00
THUNK_POPUP_ARTALIGN = 0xA0F7A0
GWIN_INIT = 0x5D4EF0
ITEM_BACK_DRAW = 0x405B20
TW_A94 = TW + 0xA94
TW_CLIP = TW + 0x474              # L,T,R,B at +0x474/+0x478/+0x47C/+0x480


def anch_esi(label: str) -> str:   # jne label when esi is NOT the anchored popup
    return f"cmp dword ptr [esi+0xa14], {TW:#x}\njne {label}\n"


def g_gt16(label: str) -> str:     # jle label when g<=16
    return f"cmp dword ptr [{G:#x}], 0x10\njle {label}\n"


# K = stroke_width = half_down(g,16) = (2g+15)>>5 ; h1 = diplo_far_edge_trim = 1 ; D = frame_grow_delta = (g-16)>>3   (scaling_laws ports)
def K_into(reg: str) -> str:               # K = half_down(g,16) = (2g+15)>>5  (scaling_laws.stroke_width)
    return f"mov {reg}, dword ptr [{G:#x}]\nadd {reg}, {reg}\nadd {reg}, 15\nsar {reg}, 5\n"


def h1_into(reg: str) -> str:
    """reg = h1 = scaling_laws.diplo_far_edge_trim(g) = 1 (every caller is gated g > 16: the band map's inclusive
    footprint ends at R/B, vanilla's half-open box at R-1/B-1).  v2 (2026-10-17) of v1's `K_into(reg); dec reg`
    (= K-1, which is 1 only for g = 25..40 and 0 at g = 17..24 -> the 1080 speech box drew 1 px wide / the title 1 row
    tall).  NOP-padded to v1's length so the sequential layout does not move; reg ends equal to v1's at g = 25..40.
    Used by exactly six thunks: t_dp_fill (fill R; the backdrop d690 reuses that rect), t_dp_title_outer /
    t_dp_title_inner (R and B), t_dp_title_text (the title TEXT rect, R and B: it IS trimmed), t_dp_textblock (d528 R
    only) and t_dp_wrapwidth (measure).  NOT by t_dp_itemrect: the type-16 rows' trim is its own `dec`
    (scaling_laws.t16_item_draw_rect)."""
    _ks = Ks(KS_ARCH_X86, KS_MODE_32)
    pad = len(_ks.asm(K_into(reg) + f"dec {reg}\n")[0]) - len(_ks.asm(f"mov {reg}, 1\n")[0])
    assert pad >= 0
    return f"mov {reg}, 1\n" + "nop\n" * pad


def D_into(reg: str) -> str:
    return f"mov {reg}, dword ptr [{G:#x}]\nsub {reg}, 16\nsar {reg}, 3\n"


# --- A: DiploTalkWin_init literals ---
T("t_dp_pushw", f"pop edx\nmov eax, 700\n{g_gt16('pw_n')}{sc('eax')}pw_n:\npush eax\njmp edx\n")                 # push 0x2bc -> push W'
T("t_dp_movh", f"mov ecx, 450\n{g_gt16('mh_n')}{sc('ecx')}mh_n:\nret\n")                                            # mov ecx,0x1c2 -> H'
T("t_dp_movex", f"mov edx, 0x20\n{g_gt16('mx_n')}{sc('edx')}mx_n:\nadd eax, edx\ncdq\nsub eax, edx\nsar eax, 1\nret\n")  # ((SW-W')+sc(0x20))/2
T("t_dp_frameL", f"mov eax, dword ptr [edx]\nmov ecx, 0x17\n{g_gt16('fl_n')}{sc('ecx')}fl_n:\nadd eax, ecx\nret\n")
T("t_dp_frameR", f"push eax\nmov eax, 0x37\n{g_gt16('fr_n')}{sc('eax')}fr_n:\nsub ecx, eax\npop eax\nmov edx, dword ptr [edx+0xc]\nret\n")

# --- H/E: BasePop_calc anchored branch cuts (esi=popup, ebp=0 at c1) ---
T("t_dp_calc_e4", f"mov dword ptr [esi+0x30e0], ebp\nmov edx, dword ptr [esi+0x21c4]\n{g_gt16('e4_n')}{sc('edx')}e4_n:\nmov dword ptr [esi+0x30e4], edx\nret\n")
T("t_dp_calc_hdr", f"mov edx, dword ptr [esi+0x21b8]\n{g_gt16('hd_n')}{sc('edx')}hd_n:\nmov dword ptr [esi+0x30e8], edx\nmov eax, dword ptr [esi+0x21bc]\nmov dword ptr [esi+0x30ec], eax\nret\n")

# --- Y: OK row bottom offset -0x1e -> -sc(30) (anchored-only branch of Popup_on_adjust_button_placement) ---
T("t_dp_oky", f"mov eax, 30\n{g_gt16('ok_n')}{sc('eax')}ok_n:\nneg eax\nmov dword ptr [ecx], eax\nret\n")

# --- Q: type-16 fixed-height arm: gap' = max(0, half_down(22g,16) - rowH) (eax=D, ecx=[D+0x30], esi=popup+0x2214) ; anchored-gated ---
T("t_dp_q16fixed", f"""
    mov dword ptr [eax+0x60], ecx
    cmp dword ptr [esi-0x1800], 0
    je q_done
    {g_gt16('q_done')}push ebx
    mov ebx, dword ptr [eax+0x68]
    test ebx, ebx
    jle q_pop
    mov edx, dword ptr [{G:#x}]
    imul edx, edx, 0x2c
    add edx, 0xf
    sar edx, 5
    sub edx, ebx
    jge q_st
    xor edx, edx
q_st:
    mov dword ptr [eax+0x44], edx
q_pop:
    pop ebx
q_done:
    mov edx, dword ptr [esi]
    mov eax, dword ptr [edx+8]
    lea ecx, [eax+esi]
    ret
""")

# --- K nest: final union rect = d528' -+ sc(3) (diplo branch only; regs as vanilla: ecx/eax/edx/ebx adjusted, ebp frame) ---
T("t_dp_knest", f"""
    push edi
    mov edi, 3
    {g_gt16('kn_n')}{sc('edi')}kn_n:
    sub ecx, edi
    mov dword ptr [ebp-0x24], eax
    mov dword ptr [ebp-0x20], ecx
    sub eax, edi
    add edx, edi
    lea ecx, [ebp-0x24]
    add ebx, edi
    pop edi
    ret
""")

# --- F: fill rect (ecx=TW, [esp+4]=rect*): {clipL+sc(0x17), clipT, clipR-sc(0x37)-h1, clipB+sc(5)} ---
T("t_dp_fill", f"""
    {gate_native(GWIN_FILL_2)}push esi
    mov esi, dword ptr [esp+8]
    mov eax, 0x17
    {sc('eax')}add eax, dword ptr [{TW_CLIP:#x}]
    mov dword ptr [esi], eax
    mov eax, 0x37
    {sc('eax')}mov edx, dword ptr [{TW_CLIP + 8:#x}]
    sub edx, eax
    {h1_into('eax')}sub edx, eax
    mov dword ptr [esi+8], edx
    mov eax, 5
    {sc('eax')}add eax, dword ptr [{TW_CLIP + 12:#x}]
    mov dword ptr [esi+12], eax
    pop esi
    jmp {GWIN_FILL_2:#x}
""")


# --- T: title outer/inner/text.  Outer' = {cL+sc(0x1B)+D, cT+sc(4)+D, cR-sc(0x3B)-D-h1, cT+sc(0x1C)-D-h1}; inner = outer' inset sc(3); text = inner inset sc(3)
def _title_rect(extra_inset_mult: int) -> str:
    """write outer' inset (extra_inset_mult*sc(3)) into the rect at esi. uses eax/edx/ebx/edi (caller saves)."""
    return (D_into('edi') +                                              # edi = D
            h1_into('ebx') +                                             # ebx = h1
            f"mov eax, 0x1B\n{sc('eax')}add eax, dword ptr [{TW_CLIP:#x}]\nadd eax, edi\nmov dword ptr [esi], eax\n"
            f"mov eax, 4\n{sc('eax')}add eax, dword ptr [{TW_CLIP + 4:#x}]\nadd eax, edi\nmov dword ptr [esi+4], eax\n"
            f"mov eax, 0x3B\n{sc('eax')}mov edx, dword ptr [{TW_CLIP + 8:#x}]\nsub edx, eax\nsub edx, edi\nsub edx, ebx\nmov dword ptr [esi+8], edx\n"
            f"mov eax, 0x1C\n{sc('eax')}add eax, dword ptr [{TW_CLIP + 4:#x}]\nsub eax, edi\nsub eax, ebx\nmov dword ptr [esi+12], eax\n" +
            (f"mov eax, 3\n{sc('eax')}imul eax, eax, {extra_inset_mult}\nadd dword ptr [esi], eax\nadd dword ptr [esi+4], eax\nsub dword ptr [esi+8], eax\nsub dword ptr [esi+12], eax\n" if extra_inset_mult else ""))


def _title(name: str, mult: int, target: int) -> None:
    T(name, gate_native(target) + "push ebx\npush esi\npush edi\nmov esi, dword ptr [esp+0x10]\n" + _title_rect(mult) + f"pop edi\npop esi\npop ebx\njmp {target:#x}\n")


_title("t_dp_title_outer", 0, THUNK_BOX_THICK)   # box_sprite(rect*, d5a0) contract -> thunk_box_thick (drop-in)
_title("t_dp_title_inner", 1, THUNK_BOX_THICK)   # d618
# title text: cent7 (str, rect*, len): rect at [esp+8] -> after 3 pushes at [esp+0x14]
T("t_dp_title_text", gate_native(CENT7) + "push ebx\npush esi\npush edi\nmov esi, dword ptr [esp+0x14]\n" + _title_rect(2) + f"pop edi\npop esi\npop ebx\njmp {CENT7:#x}\n")

# --- X: text-block d528 (esi=popup): {30F0+30D8+21C8+30E0-sc3, 30E8+30E0-sc6+sc3, cR-sc(0x3B)-h1-sc3, 30D4+30E8+30E0+sc3-3} -> devfill
T("t_dp_textblock", f"""
    {gate_native(THUNK_DEVFILL)}push ebx
    push edi
    mov edi, dword ptr [esp+0xC]
    mov ebx, 3
    {sc('ebx')}mov eax, dword ptr [esi+0x30f0]
    add eax, dword ptr [esi+0x30d8]
    add eax, dword ptr [esi+0x21c8]
    add eax, dword ptr [esi+0x30e0]
    sub eax, ebx
    mov dword ptr [edi], eax
    mov eax, dword ptr [esi+0x30e8]
    add eax, dword ptr [esi+0x30e0]
    add eax, ebx
    mov edx, 6
    {sc('edx')}sub eax, edx
    mov dword ptr [edi+4], eax
    mov eax, 0x3B
    {sc('eax')}mov edx, dword ptr [{TW_CLIP + 8:#x}]
    sub edx, eax
    sub edx, ebx
    {h1_into('eax')}sub edx, eax
    mov dword ptr [edi+8], edx
    mov eax, dword ptr [esi+0x30d4]
    add eax, dword ptr [esi+0x30e8]
    add eax, dword ptr [esi+0x30e0]
    add eax, ebx
    sub eax, 3
    mov dword ptr [edi+12], eax
    pop edi
    pop ebx
    jmp {THUNK_DEVFILL:#x}
""")

# --- W: box_w native arm for anchored (wrapper in front of thunk_scale_boxw; site 0x603D82 push;ret, resume 0x603D88) ---
T("t_dp_boxw_gate", f"{anch_esi('bw_s')}mov ebx, dword ptr [esi+0x30e0]\npush 0x603D88\nret\nbw_s:\njmp {THUNK_SCALE_BOXW:#x}\n")
# --- G: grow_box native (site 0x602861, resume 0x602867), btn_vcenter native (site 0x602C49, resume 0x602C51), orn_childx native (E8 site 0x602B88)
T("t_dp_growbox_gate", f"{anch_esi('gb_s')}mov ecx, dword ptr [esi+0x30c0]\npush 0x602867\nret\ngb_s:\njmp {THUNK_GROW_BOX:#x}\n")
T("t_dp_vcenter_gate", f"{anch_esi('vc_s')}mov dword ptr [esp+0x14], eax\nlea eax, [esp+0x18]\npush 0x602C51\nret\nvc_s:\njmp {THUNK_BTN_VCENTER:#x}\n")
T("t_dp_childx_gate", f"{anch_esi('cx_s')}cmp dword ptr [esi+0x2350], -1\nret\ncx_s:\njmp {THUNK_ORN_CHILDX:#x}\n")
# --- B: q16 fill width native while the talk screen is open (E8 site 0x60D299 -> GraphicWin_init) ---
# wrapper at 0x60D299 (Dialog_type16_attach's GraphicWin_init call, esi=popup+0x2C44): anchored ([+0xA14]!=0,
# rows already device-wide from the ext window) -> plain GraphicWin_init; else -> thunk_q16_fill_width
# 2026-10-11: the anchored arm jumps to t_dp_q16anch (fixed slot, below) instead of GraphicWin_init -- same 5-byte
# jmp rel32, so the gate stays 19 B and the sequential layout does not move.
T_DP_Q16ANCH = PCAVE2_VA + 0x30850
T("t_dp_q16gate", f"cmp dword ptr [esi-0x2230], 0\nje q16_s\njmp {T_DP_Q16ANCH:#x}\nq16_s:\njmp {THUNK_Q16_FILL:#x}\n")
# --- M: measure width for anchored: [esp+8] = ((clipR - sc(0x3B)) - h1 - sc(3)) - 30F0 - 30D8 - sc(5)  (esi=popup; then thunk_faction_wrapwidth passes through)
T("t_dp_wrapwidth", f"""
    {anch_esi('ww_s')}{g_gt16('ww_s')}push ebx
    mov edx, 0x3B
    {sc('edx')}mov ebx, dword ptr [{TW_CLIP + 8:#x}]
    sub ebx, edx
    {h1_into('eax')}sub ebx, eax
    mov edx, 3
    {sc('edx')}sub ebx, edx
    sub ebx, dword ptr [esi+0x30f0]
    sub ebx, dword ptr [esi+0x30d8]
    mov edx, 5
    {sc('edx')}sub ebx, edx
    mov dword ptr [esp+0xC], ebx
    pop ebx
ww_s:
    jmp {THUNK_FACTION_WRAPWIDTH:#x}
""")
# --- P: art xy for anchored (fn-ptr [popup+0x3168]; args sprite/[esp+4] popup/[esp+8] res/[esp+C] x/[esp+10] y/[esp+14]) -> thunk_popup_artalign
T("t_dp_artalign", f"""
    {g_gt16('aa_s')}mov eax, dword ptr [esp+8]
    cmp dword ptr [eax+0xa14], {TW:#x}
    jne aa_s
    mov edx, 0x1B
    {sc('edx')}add edx, dword ptr [{TW_CLIP:#x}]
    {K_into('ecx')}add edx, ecx
    add edx, 5
    mov dword ptr [esp+0x10], edx
    mov edx, 6
    {sc('edx')}mov ecx, dword ptr [eax+0x30e8]
    sub ecx, edx
    add ecx, 6
    mov dword ptr [esp+0x14], ecx
aa_s:
    jmp {THUNK_POPUP_ARTALIGN:#x}
""")
# --- R: the type-16 option row's frame rect (vtable wrapper of Popup_on_dialog_item_back_draw at all FOUR slots that
# hold it; ecx = popup, [esp+4] buf, [esp+8] a3, [esp+0xC] idx, [esp+0x10] rect*, thiscall RET 0x10).
# Law scaling_laws.t16_item_draw_rect = bandmap_rect_from_halfopen: the row frame reaches the band map
# (0x405BF6 -> t_rowbox_ph -> thunk_rowbox_guard -> thunk_box_thick_hollow_flat), which paints the INCLUSIVE
# footprint [L..R]x[T..B], so the far edges come in by ONE at every g > 16.
# v2 (2026-10-17): v1 trimmed the anchored rect by K-1 (the 2026-08 lever R model "the flat thickener draws R/B at
# [E-1, E-1+K-1]"); K-1 == 1 only for g >= 25, so at g = 17..24 the diplomacy reply rows drew 1 px too wide and too
# tall (1080 shot 20261017-115317: 822 x 28 for an 821 x 27 rect).  The constant 1 reproduces v1's OUTPUT (not its
# bytes) for g = 25..40 (G_MAX) only; v1 trimmed K-1 = 2 at g >= 41, where v2 keeps the lawful 1.
#   anchored ([+0xA14] == DiploTalkWin): trim the CALLER's rect in place (v1's contract: the caller's text and focus
#     rect see the trimmed rect, as at 4K/1600 since 2026-08-20) -> jmp the native fn.
#   plain type 16 ([+0x2350] == 16: Quit, Planetary Council propose, every other non-anchored option list): the
#     native fn gets a trimmed stack COPY; the caller's rect (its text centring and focus rect) is untouched.
#     R-1 moves no pixel where the row window already clips at W-1 (hollow_flat's clamp); B-1 drops the 1-px-taller
#     bar (4K 51 / 1600 32 / 1080 28 vs OK 50 / 31 / 27) and restores option_row_gap's gap.
#   g <= 16 / any other popup or dialog type: jmp the native fn untouched.
T("t_dp_itemrect", f"""
    {g_gt16('ir_n')}mov edx, dword ptr [esp+0x10]
    cmp dword ptr [ecx+0xa14], {TW:#x}
    jne ir_plain
    dec dword ptr [edx+8]
    dec dword ptr [edx+12]
ir_n:
    jmp {ITEM_BACK_DRAW:#x}
ir_plain:
    cmp dword ptr [ecx+0x2350], 0x10
    jne ir_n
    push dword ptr [edx+12]
    push dword ptr [edx+8]
    push dword ptr [edx+4]
    push dword ptr [edx]
    dec dword ptr [esp+8]
    dec dword ptr [esp+12]
    push esp
    push dword ptr [esp+0x20]
    push dword ptr [esp+0x20]
    push dword ptr [esp+0x20]
    call {ITEM_BACK_DRAW:#x}
    add esp, 16
    ret 0x10
""")
# v2 outgrew v1's 52-B sequential slot (0x12750..0x12790, now free/zeros): fixed slot in the hole after g_pw_state
# (cave_map 2026-10-17: 0x45A4..0x4640 FREE; the planwin ledger says "free 0x4568..0x4640" around its 52-B cells).
LOW_HOLES = {"t_dp_itemrect": (0x45B0, 0x4640)}

# ---- popup-half site tables ----
# cuts: (site_id, va, len, thunk)  -> new_bytes = E8 rel32 + NOP pad ; original from the pristine exe
CUTS = [
    ("DiploTalkWin_init.gwinit_w",     0x440AF2, 5,  "t_dp_pushw"),
    ("DiploTalkWin_init.gwinit_h",     0x440AE0, 5,  "t_dp_movh"),
    ("DiploTalkWin_init.move_x",       0x440B32, 8,  "t_dp_movex"),
    ("DiploTalkWin_init.frame_left",   0x440B68, 5,  "t_dp_frameL"),
    ("DiploTalkWin_init.frame_right",  0x440B7D, 6,  "t_dp_frameR"),
    ("BasePop_calculate_dimensions.anch_e4",  0x60392B, 18, "t_dp_calc_e4"),
    ("BasePop_calculate_dimensions.anch_hdr", 0x603999, 24, "t_dp_calc_hdr"),
    ("Popup_on_adjust_button_placement.anch_oky", 0x40507F, 6, "t_dp_oky"),
    ("Dialog_type16_calc.fixed_arm_gap",       0x60D717, 11, "t_dp_q16fixed"),
    ("Popup_on_draw_background.diplo_knest",  0x405EA6, 21, "t_dp_knest"),
]
# new call-target redirects in the diplo branch of Popup_on_draw_background: (site_id, va, thunk, expected native target)
POPUP_REDIRECTS = [
    ("Popup_on_draw_background.diplo_fill",        0x405D0B, "t_dp_fill",         GWIN_FILL_2),
    ("Popup_on_draw_background.diplo_backdrop",    0x405D39, "thunk_box_thick_devfill", BOX_SPRITE),
    ("Popup_on_draw_background.diplo_title_outer", 0x405D91, "t_dp_title_outer",  BOX_SPRITE),
    ("Popup_on_draw_background.diplo_title_inner", 0x405DC6, "t_dp_title_inner",  BOX_SPRITE),
    ("Popup_on_draw_background.diplo_title_text",  0x405E31, "t_dp_title_text",   CENT7),
    ("Popup_on_draw_background.diplo_textblock",   0x405E95, "t_dp_textblock",    BOX_SPRITE),
]
# vtable repoints: (site_id, va, thunk)  original "20 5B 40 00"
VTABLES = [(f"vtbl_item_back_draw_{i}", va, "t_dp_itemrect") for i, va in enumerate((0x6695F4, 0x66A8D4, 0x66CB8C, 0x66DDB0))]
# EXISTING sites whose new_bytes get repointed at a wrapper: va -> (old placeholder, new placeholder)
EXISTING_REPOINTS = {
    0x603D82: ("{abs32:thunk_scale_boxw}",     "{abs32:t_dp_boxw_gate}"),
    0x602861: ("{abs32:thunk_grow_box}",       "{abs32:t_dp_growbox_gate}"),
    0x602C49: ("{abs32:thunk_btn_vcenter}",    "{abs32:t_dp_vcenter_gate}"),
    0x602B88: ("{rel32:thunk_orn_childx}",     "{rel32:t_dp_childx_gate}"),
    0x60D299: ("{rel32:thunk_q16_fill_width}", "{rel32:t_dp_q16gate}"),
    0x603E42: ("{rel32:thunk_faction_wrapwidth}", "{rel32:t_dp_wrapwidth}"),
    0x603F3D: ("{rel32:thunk_faction_wrapwidth}", "{rel32:t_dp_wrapwidth}"),
    0x404BDE: ("{abs32:thunk_popup_artalign}", "{abs32:t_dp_artalign}"),
}
# EXISTING_REPOINTS a later bake took over: va -> the shipped placeholder (a wrapper that still reaches our target)
REPOINT_TAKEN_OVER = {
    0x404BDE: "{abs32:thunk_gv_arthead}",   # council_scale 2026-08-22 Cast-a-Vote gate head; else -> t_dp_artalign
}
# thunk_btn_gate v8 prefix: 3 diplo FlatButton statics -> HIT
BTN_STATICS = (TW + 0x2158, TW + 0x2CA4, TW + 0x37F0)


def btn_gate_prefix() -> bytes:
    asm = "".join(f"cmp esi, {v:#x}\nje hit\n" for v in BTN_STATICS) + "jmp body\nhit:\nmov eax, 1\nret\nbody:\n"
    enc, _ = ks.asm(asm, 0)
    return bytes(enc)


# ---------------------------------------------------------------------------
# CONSOLE SAVE-UNDER (diplo-exit residue fix, proto hook_tile_restore_proto.js
# v6 USER-VERIFIED 4K 2026-08-20).  The diplomacy flow paints the console
# strip's inter-panel centre column directly onto the MainWin canvas; the
# exit restore (MainWin_tile_panels normal mode) re-tiles only its DA0/DB0
# rects (each inset 1), leaving the gap band + bezel footprint holding diplo
# pixels, and the 24x24 tile texture [0x78D6B0] is a flat backdrop that
# cannot reproduce the scaled pcx art.  Fix = popup save-under pattern:
#   t_cr_snap  (iface vtbl 0x66B424 slot 0 -> wraps DiploTalkIface_on_mode):
#              on ENTER at g>16, snapshot canvas x [D80.R..D90.L) x y
#              [0..DB0.T+2) into a VirtualAlloc'd buffer (once; res is fixed
#              per session), arm the restore.
#   t_cr_tile  (call-target redirect at ALL 12 E8 callers of tile_panels):
#              this==MainWin && armed==1 (only ever set at g>16) && big==0 &&
#              iface mode in {0 = HUD, 4 = diplo} -> call native, then copy the
#              saved rows back and GraphicWin_soft_update the rect (ecx reloaded
#              as a literal: the native call clobbers it BEFORE the pushad).  The MODE gate is load-bearing: armed is never
#              cleared and every console-skinning window (base screen 0x41E7AD
#              mode 3, ...) passes this==MainWin, so without it the HUD centre
#              column is stamped under their panels (probe hook_console_stamp.js
#              2026-09-20).  Neither `this` nor the mode ARG discriminates.
#              Panel painters always run AFTER tile_panels in every paint
#              flow, so fresh panel content repaints on top.
# g<=16: both thunks are native passthroughs (vanilla restore is correct).
# ---------------------------------------------------------------------------
TILE_PANELS = 0x45C290
ONMODE = 0x440380
SOFT_UPDATE = 0x5D5720
IAT_VIRTUALALLOC = 0x669134
G_BIG = 0x7D3930
CANVAS_DATA = MW_CANVAS + 0x54
CANVAS_STRIDE = MW_CANVAS + 0x4A8
IFACE_VTBL0 = 0x66B424
IFACE_MODE_TAB = 0x7AE778    # g_iface_mode_table
IFACE_MODE_IDX = 0x7D392C    # g_iface_mode_idx

CR_CELLS_OFF = 0x12790       # after the sequential thunk region (cave_map: free from 0x12784)
CELLS2 = [("g_cr_buf", 4), ("g_cr_L", 4), ("g_cr_R", 4), ("g_cr_B", 4), ("g_cr_armed", 4), ("g_cr_mode", 4)]
CELL2_VA = {}
_o2 = CR_CELLS_OFF
for _n, _sz in CELLS2:
    CELL2_VA[_n] = PCAVE2_VA + _o2
    _o2 += _sz
FIXED_OFF = {"t_cr_snap": 0x127B0, "t_cr_tile": 0x17350,
             "t_cr_mark": 0x17080, "t_cr_tile_exit": 0x170B0}   # cave_map --fit 128: 0x17080-0x17100 FREE (2026-09-23);
# t_cr_tile v3 (2026-09-26) RELOCATED 0x128B0 (144 B slot, now FREE) -> 0x17350 (cave_map --fit 160: 0x17344-0x17400 FREE)
FIXED_OFF.update({n: lo for n, (lo, hi) in LOW_HOLES.items()})   # 2026-10-17: t_dp_itemrect v2, below the sequential region
CRBUF, CRL, CRR, CRB, CRARM, CRMODE = (CELL2_VA[n] for n in ("g_cr_buf", "g_cr_L", "g_cr_R", "g_cr_B", "g_cr_armed", "g_cr_mode"))
T_CR_MARK = PCAVE2_VA + FIXED_OFF["t_cr_mark"]
T_CR_TILE = PCAVE2_VA + FIXED_OFF["t_cr_tile"]
# the 10-byte `mov [g_cr_armed],1` of every snapshot thunk (diplo / DL / combat clones) is this
# same-length call: arm + record the mode the save-under returns to (see t_cr_mark)
# v4 (2026-09-26): the snapshot starts one column LEFT of D80.right (the D80 right frame column: the
# hide-tail 1:1 centre sprite overwrites it and neither the D80 inset fill nor the old snapshot covered
# it, at every g); the extra `dec eax` is paid for by a 4-byte arm NOP so every clone stays 181 B in place.
CR_ARM_ASM = f"call {T_CR_MARK:#x}\n.byte 0x0F, 0x1F, 0x40, 0x00\n"

T("t_cr_snap", f"""
cmp dword ptr [{G:#x}], 0x10
jle cr_pass
cmp dword ptr [esp+4], 0
je cr_pass
pushad
mov eax, dword ptr [{SEED['D80'] + 8:#x}]
dec eax
mov dword ptr [{CRL:#x}], eax
mov edx, dword ptr [{SEED['D90']:#x}]
mov dword ptr [{CRR:#x}], edx
mov ecx, dword ptr [{SEED['DB0'] + 4:#x}]
add ecx, 2
mov dword ptr [{CRB:#x}], ecx
mov ebx, dword ptr [{CRBUF:#x}]
test ebx, ebx
jnz cr_have
mov eax, edx
sub eax, dword ptr [{CRL:#x}]
imul eax, ecx
push 4
push 0x3000
push eax
push 0
call dword ptr [{IAT_VIRTUALALLOC:#x}]
test eax, eax
jz cr_bail
mov dword ptr [{CRBUF:#x}], eax
mov ebx, eax
cr_have:
mov esi, dword ptr [{CANVAS_DATA:#x}]
test esi, esi
jz cr_bail
add esi, dword ptr [{CRL:#x}]
mov edi, ebx
mov edx, dword ptr [{CRR:#x}]
sub edx, dword ptr [{CRL:#x}]
mov ebp, dword ptr [{CRB:#x}]
cr_row:
push esi
push edi
mov ecx, edx
rep movsb
pop edi
pop esi
add esi, dword ptr [{CANVAS_STRIDE:#x}]
add edi, edx
dec ebp
jnz cr_row
{CR_ARM_ASM}cr_bail:
popad
cr_pass:
jmp {ONMODE:#x}
""")

T("t_cr_tile", f"""
cmp ecx, {MW:#x}
jne ct_plain
mov eax, dword ptr [{CRARM:#x}]
dec eax
or eax, dword ptr [{G_BIG:#x}]
jnz ct_plain
mov eax, dword ptr [{IFACE_MODE_IDX:#x}]
mov eax, dword ptr [eax*4 + {IFACE_MODE_TAB:#x}]
test al, 0xFB
jz ct_go
ct_plain:
jmp {TILE_PANELS:#x}
ct_go:
pushad
mov edi, dword ptr [{CANVAS_DATA:#x}]
test edi, edi
jz ct_skip
add edi, dword ptr [{CRL:#x}]
mov esi, dword ptr [{CRBUF:#x}]
mov edx, dword ptr [{CRR:#x}]
sub edx, dword ptr [{CRL:#x}]
mov ebp, dword ptr [{CRB:#x}]
ct_row:
push esi
push edi
mov ecx, edx
rep movsb
pop edi
pop esi
add edi, dword ptr [{CANVAS_STRIDE:#x}]
add esi, edx
dec ebp
jnz ct_row
ct_skip:
popad
push dword ptr [esp+4]
call {TILE_PANELS:#x}
pushad
push dword ptr [{CRB:#x}]
mov eax, dword ptr [{CRR:#x}]
sub eax, dword ptr [{CRL:#x}]
push eax
push 0
push dword ptr [{CRL:#x}]
mov ecx, {MW:#x}
call {SOFT_UPDATE:#x}
popad
ret 4
""")

# ct_go = t_cr_tile's restore path: copy the snapshot back FIRST, then the native tile_panels (its
# flat fill of the D80/DA0/DB0/D90 interiors WINS over the snapshot: v3 2026-09-26 -- v2 copied
# back AFTER the native fill, so a snapshot holding a nested screen's text re-dirtied the 7-px channel
# between the two HUD readout panels, which the readout repaint never covers: the PROFILE report's
# title survived there, user 4K shot 20260926-160047), then soft_update the column, ret 4.
# t_cr_tile_exit enters it with t_cr_tile's own entry stack.  Located in the assembled bytes.
_ct_blob = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(THUNK_ASM["t_cr_tile"], T_CR_TILE)[0])
_ct_sig = bytes.fromhex("608B3D") + CANVAS_DATA.to_bytes(4, "little")   # pushad / mov edi,[canvas data]
assert _ct_blob.count(_ct_sig) == 1, "t_cr_tile: ct_go signature not unique"
CT_GO = T_CR_TILE + _ct_blob.index(_ct_sig)

# RETURN-MODE save-under (2026-09-23, probe hook_dl_help_stamp.js 4K+1600): Datalinks entered from
# the BASE screen (production picker Help) exits via release_iface_mode, which POPS the mode stack
# before the leaving iface's on_mode(0) -> slide_hide(win,2) -> tile_panels @0x45DE3C, so t_cr_tile's
# {0,4} gate sees mode 3 and skips the restore: the DL big-centre tiling stays in the band between
# DA0 and DB0 until the base closes (the base never repaints it).
#   t_cr_mark       (called from every snapshot thunk in place of `mov [g_cr_armed],1`, inside its
#                   pushad): g_cr_mode = g_iface_mode_table[idx-1] = the mode being left, i.e. the
#                   mode the exit returns to (set_iface_mode pushes before on_mode(1)); armed = 1
#                   for a HUD snapshot (mode 0, t_cr_tile's contract, unchanged), 2 otherwise --
#                   t_cr_tile gates on armed == 1, so a BASE-screen snapshot is never pasted under
#                   the HUD after the base closes (user 4K shot 20260923-221742: name plate /
#                   citizens box outlines between the HUD panels).
#   t_cr_tile_exit  (the slide_hide exit site 0x45DE3C only = the leaving console iface's OWN
#                   hide): armed != 0 && ecx == MainWin && big == 0 && g_cr_mode != -1 -> restore
#                   via ct_go, one-shot (g_cr_mode := -1) for an armed==2 snapshot; otherwise
#                   t_cr_tile unchanged.  v2 (2026-09-26): NO mode-stack compare.  A screen opened
#                   FROM the talk (DATALINKS -> set_iface_mode pushes 8, PROFILE pushes 5) runs the
#                   diplo hide with the NEW mode on top, so the old `mode == g_cr_mode` test (and
#                   t_cr_tile's {0,4} gate) skipped the restore; the inner iface then snapshotted the
#                   dirty canvas (hide-tail 1:1 centre sprite band + diplo pixels) and every later
#                   restore pasted it back under the HUD / editor panel (user shot
#                   _Problems/CenterConsole.png, probe-confirmed).  The leaving iface's own hide
#                   always restores its own snapshot, whatever is on the stack, so every nested
#                   snapshot is taken from a clean column.  Restricted to the exit site so the
#                   snapshot is never pasted under a base screen on ordinary redraws (b644faa2).
T("t_cr_mark", f"""
mov eax, dword ptr [{IFACE_MODE_IDX:#x}]
mov eax, dword ptr [eax*4 + {IFACE_MODE_TAB - 4:#x}]
mov dword ptr [{CRMODE:#x}], eax
mov dword ptr [{CRARM:#x}], 1
test eax, eax
jz cm_done
mov dword ptr [{CRARM:#x}], 2
cm_done:
ret
""")

T("t_cr_tile_exit", f"""
cmp ecx, {MW:#x}
jne tx_plain
cmp dword ptr [{G_BIG:#x}], 0
jne tx_plain
cmp dword ptr [{CRMODE:#x}], 0xFFFFFFFF
je tx_plain
mov eax, dword ptr [{CRARM:#x}]
test eax, eax
jz tx_plain
cmp eax, 2
jne tx_go
mov dword ptr [{CRMODE:#x}], 0xFFFFFFFF
tx_go:
jmp {CT_GO:#x}
tx_plain:
jmp {T_CR_TILE:#x}
""")

# ---------------------------------------------------------------------------
# t_dp_status_fit (2026-10-11): the "DIPLOMATIC STATUS: <treaty>" wrap_3 @0x43FE07 (law scaling_laws.
# diplo_status_font_size / diplo_status_next_y).  Vanilla fits "...: NONE" at 2 px of slack (161 px in
# 163); the scaled Arial fl(12g/16) runs past its fl-scaled budget at some g (4K: 411 in 410 -> NONE on
# a 2nd line).  Entry = t_dp_txt_wrap3's: ecx = MainWin canvas, [esp]=ret +4 str +8 x +C y +10 w; the
# painter set DiploTalkWin +0xA44 on the canvas once (0x43FD18) for every status line.  g<=16 -> wrap_3
# verbatim.  g>16: x/w exactly as t_dp_txt_wrap3; then (painter's own measure, sf_meas):
#   vanilla test: native Arial 12 (private slot, Font_init once) vs DIPLO_STATUS_NATIVE_W -> wraps? keep A44
#   else A44 (fl(12g/16)) vs w; overflow -> Font_init the fit slot one size smaller (keyed on g_dp_fitsz,
#   so a repaint at the same size never re-creates the HFONT) until it fits or reaches the minimum.
# draws with wrap_3 (called, not tail-jumped: wrap_3 is not ret-keyed), puts +0xA44 back on the canvas for
# the INFILTRATION / Energy / Might lines, and -- when the fit font drew the line -- returns
# y' + lh(A44) - lh(fit) (wrap_3 advances y by its font's line height, Buffer_wrap_3 0x5DD8B8: [f] >= 0 ?
# [f+0x10]+[f] : [f+0xC]), so the following lines sit where one +0xA44 line puts them.
# ebx/esi/edi/ebp preserved; RET 0x10.
# sf_meas "fits" = Font_find_line_break_l's remaining budget >= 1 with budget w+1 (<=> width <= w).  The
# return value alone is not enough: one unbreakable word that overflows comes back 0 with *budget = 0
# (0x619505), the same as a fit.
# Layout: code in the pcave2 range reserved 2026-10-11 (cave_map --at 0x30B00 / 0x30CFF: FREE, after
# t_splash_blit); cells in the 0x27C22 hole.
#   0x30B00..0x30C00  t_dp_status_fit (entry, x/w, measure loop)
#   0x30C00..0x30D00  t_dp_status_tail (draw + y + restore; the sf_meas / sf_set / sf_lh helpers)
#   0x27C28..0x27C7C  cells: two Font slots (struct Font = 0x28) + the fit slot's size key
FONT_INIT = 0x618F40
SET_FONT = 0x5DAC70          # Buffer_set_font(this; f0, f1, f2, f3) thiscall RET 0x10
FIND_BREAK = 0x5DC410        # Buffer_find_line_break_l(this; str, int* budget, len) thiscall RET 0xC
CRT_STRLEN = 0x6453E0
HUD_FONT_NAME = 0x691B2C     # g_hud_font_name (char*) -- the face DiploTalkWin_init gives +0xA44
STATUS_FONT = TW + 0xA44
STATUS_WRAP_SITE = 0x43FE07
FONT_SIZE = 0x28
FIT_CELLS_OFF = 0x27C28
CELLS3 = [("g_dp_natfont", FONT_SIZE), ("g_dp_fitfont", FONT_SIZE), ("g_dp_fitsz", 4)]
CELL3_VA = {}
_o3 = FIT_CELLS_OFF
for _n, _sz in CELLS3:
    CELL3_VA[_n] = PCAVE2_VA + _o3
    _o3 += _sz
FIT_CELLS_END = _o3
assert 0x27C22 <= FIT_CELLS_OFF and FIT_CELLS_END <= 0x27D00
STATUS_HOLES = {"t_dp_status_fit": (0x30B00, 0x30C00), "t_dp_status_tail": (0x30C00, 0x30D00)}
FIXED_OFF["t_dp_status_fit"] = STATUS_HOLES["t_dp_status_fit"][0]
FIXED_OFF["t_dp_status_tail"] = STATUS_HOLES["t_dp_status_tail"][0]
NATFONT, FITFONT, FITSZ = CELL3_VA["g_dp_natfont"], CELL3_VA["g_dp_fitfont"], CELL3_VA["g_dp_fitsz"]
SF_DRAW = PCAVE2_VA + FIXED_OFF["t_dp_status_tail"]     # tail +0: jmp sf_draw    (2-byte short jmps; asserted below)
SF_NATINIT = SF_DRAW + 2                                # tail +2: jmp sf_natinit
SF_MEAS = SF_DRAW + 4                                   # tail +4: sf_meas

# t_dp_status_fit frame: [esp]=size local, then edi esi ebx ebp, ret; args str +0x18 x +0x1C y +0x20 w +0x24.
# ebx = the Font the line is drawn with (A44 unless the fit shrank it), esi = str, edi = len, ebp = canvas.
T("t_dp_status_fit", gate_native(WRAP_3) + _TXT_X + _TXT_W + f"""
push ebp
push ebx
push esi
push edi
push eax
mov ebp, ecx
mov esi, dword ptr [esp+0x18]
push esi
call {CRT_STRLEN:#x}
pop ecx
mov edi, eax
call {SF_NATINIT:#x}
mov eax, {NATFONT:#x}
mov edx, {SL.DIPLO_STATUS_NATIVE_W}
call {SF_MEAS:#x}
mov ebx, {STATUS_FONT:#x}
test eax, eax
jne {SF_DRAW:#x}
mov eax, dword ptr [{G:#x}]
imul eax, eax, {SL.DIPLO_STATUS_FONT_NATIVE}
sar eax, 4
mov dword ptr [esp], eax
sf_try:
mov eax, ebx
mov edx, dword ptr [esp+0x24]
call {SF_MEAS:#x}
test eax, eax
je {SF_DRAW:#x}
mov eax, dword ptr [esp]
cmp eax, {SL.DIPLO_STATUS_FONT_MIN}
jle {SF_DRAW:#x}
dec eax
mov dword ptr [esp], eax
mov ebx, {FITFONT:#x}
cmp eax, dword ptr [{FITSZ:#x}]
je sf_try
mov dword ptr [{FITSZ:#x}], eax
push 0
push eax
push dword ptr [{HUD_FONT_NAME:#x}]
mov ecx, {FITFONT:#x}
call {FONT_INIT:#x}
jmp sf_try
""")

# t_dp_status_tail: +0 sf_draw (jumped to with t_dp_status_fit's frame), +2 sf_natinit (Font_init the native slot
# once: g_hud_font_name 12 regular = DiploTalkWin_init's +0xA44 call @0x440A6D), +4 sf_meas (eax = Font, edx = w ->
# eax = 0 when the string fits w in that Font, else 1), sf_set (eax = Font -> Buffer_set_font(canvas; eax, 0, 0, 0),
# the painter's own call shape @0x43FD18), sf_lh (eax = Font -> eax = wrap_3's line advance; clobbers edx).
T("t_dp_status_tail", f"""
jmp sf_draw
jmp sf_natinit
sf_meas:
inc edx
push edx
call sf_set
mov eax, esp
push edi
push eax
push esi
mov ecx, ebp
call {FIND_BREAK:#x}
pop edx
xor eax, eax
test edx, edx
setle al
ret
sf_natinit:
cmp dword ptr [{NATFONT + 8:#x}], 0
jne sf_nat
push 0
push {SL.DIPLO_STATUS_FONT_NATIVE}
push dword ptr [{HUD_FONT_NAME:#x}]
mov ecx, {NATFONT:#x}
call {FONT_INIT:#x}
sf_nat:
ret
sf_set:
push 0
push 0
push 0
push eax
mov ecx, ebp
call {SET_FONT:#x}
ret
sf_lh:
mov edx, dword ptr [eax]
test edx, edx
jl sf_lh_c
mov eax, dword ptr [eax+0x10]
add eax, edx
ret
sf_lh_c:
mov eax, dword ptr [eax+0xC]
ret
sf_draw:
mov eax, ebx
call sf_set
push dword ptr [esp+0x24]
push dword ptr [esp+0x24]
push dword ptr [esp+0x24]
push dword ptr [esp+0x24]
mov ecx, ebp
call {WRAP_3:#x}
mov esi, eax
cmp ebx, {STATUS_FONT:#x}
je sf_restore
mov eax, ebx
call sf_lh
sub esi, eax
mov eax, {STATUS_FONT:#x}
call sf_lh
add esi, eax
sf_restore:
mov eax, {STATUS_FONT:#x}
call sf_set
mov eax, esi
pop ecx
pop edi
pop esi
pop ebx
pop ebp
ret 0x10
""")


# --- t_dp_q16anch (2026-10-11, law diplo_q16_row_width): the ANCHORED arm of t_dp_q16gate (E8 @0x60D299 in place
# of `call GraphicWin_init`; esi = Dialog_type16_attach this = popup+0x2C44, D = esi+0x12C, ecx = the GraphicWin this
# -> preserved).  Vanilla's fixed-width branch (calc 0x60D690, taken iff [D+0x20]&2 && [D+0x2C]) trims each row
# column by the row gap [D+0x44] = the native 3: rows end 3 px short of the OK bar (pristine Diplomacy\Opening.png
# 211..808 vs 211..811).  At scale [D+0x44] is the VERTICAL gap (t_dp_q16fixed: 5 @g40), so the rows ended 5 short
# where vanilla x g/16 is 7.5.  Recompute [D+0x64] = (B - 2*[D+0x40]) / [D+0x4C] - ps3 with the engine's own idiv;
# the window width [D+0x5C] (= B, the OK bar span) and the vertical gap are untouched.  g<=16 / other branch ->
# plain GraphicWin_init.  eax/edx are call-clobbered at the site.
T("t_dp_q16anch", f"""
    {g_gt16('qa_go')}test byte ptr [esi+0x14c], 2
    je qa_go
    mov eax, dword ptr [esi+0x158]
    test eax, eax
    je qa_go
    mov edx, dword ptr [esi+0x16c]
    add edx, edx
    sub eax, edx
    cdq
    idiv dword ptr [esi+0x178]
    mov edx, dword ptr [{G:#x}]
    lea edx, [edx+edx*2]
    sar edx, 4
    sub eax, edx
    mov dword ptr [esi+0x190], eax
qa_go:
    jmp {GWIN_INIT:#x}
""")
FIXED_OFF["t_dp_q16anch"] = T_DP_Q16ANCH - PCAVE2_VA     # reserved fix-agent range 0x30700..0x30A00 (cave_map --at: FREE)

# every E8 caller of MainWin_tile_panels in the built exe (byte-scan census
# 2026-08-19; no abs32/table refs exist) -- the thunk gates on this==MainWin
# so the BaseWin-family console painters pass straight through.
TILE_EXIT_SITE = 0x45DE3C    # slide_hide(win,2) tail -> t_cr_tile_exit
TILE_SITES = [0x41E7AD, 0x422CF2, 0x426AD2, 0x431E98, 0x4379D2, 0x4400CB,
              0x4402B1, 0x4436D2, 0x45BC73, 0x45D90E, 0x45DE3C, 0x4B19D2]
VTABLES2 = [("iface_on_mode_saveunder", IFACE_VTBL0, "t_cr_snap", ONMODE)]

# ---- site tables: (site_id, va, thunk) -- original bytes are read from the pristine exe ----
REDIRECTS = [
    ("DiploTalkWin_init.font_a",        0x440A57, "t_fontinit"),
    ("DiploTalkWin_init.font_b",        0x440A6D, "t_fontinit"),
    ("DiploTalkWin_init.font_c",        0x440AA9, "t_fontinit"),
    ("DiploTalkWin_init.font_a800",     0x440A7E, "t_fontinit"),
    ("DiploTalkWin_init.font_b800",     0x440A94, "t_fontinit"),
    ("DiploTalkWin_init.rect_table",    0x440BD9, "t_dp_table"),
    ("DiploTalkWin_draw_strip.frame_centre",   0x4402F3, "t_dp_box_centre"),
    ("DiploTalkWin_draw_strip.frame_hqunion",  0x440352, "t_dp_box_hqunion"),
    ("DiploTalkWin_draw_status_panels.panel",  0x43FB0A, "t_dp_box_panel"),
    ("DiploTalkWin_draw_hq_panel.panel",       0x440108, "t_dp_box_hq"),
    ("DiploTalkWin_draw_bioscan_panel.header_text", 0x43F6D8, "t_dp_c7_bio"),
    ("DiploTalkWin_draw_hq_panel.name_text",   0x440233, "t_dp_c7_hq"),
    ("DiploTalkWin_draw_bioscan_panel.colour_bar", 0x43F778, "t_dp_sd2_bar"),
    ("DiploTalkWin_draw_status_panels.logo",   0x43FBFB, "t_dp_sd2_logo"),
    ("DiploTalkWin_draw_hq_panel.picture",     0x440277, "t_dp_sd2_hqpic"),
    ("slide_show.diplo_bezel",                 0x45D8E9, "t_dp_sd2_bezel"),
    ("DiploTalkWin_draw_status_panels.name",   0x43FCA2, "t_dp_cent6"),
    ("DiploTalkWin_draw_status_panels.status_wrap",  STATUS_WRAP_SITE, "t_dp_status_fit"),   # 2026-10-11 (was t_dp_txt_wrap3)
    ("DiploTalkWin_draw_status_panels.infil_wrap",   0x43FE97, "t_dp_txt_wrap3"),
    ("DiploTalkWin_draw_status_panels.energy",       0x43FF53, "t_dp_txt_wl3"),
    ("DiploTalkWin_draw_status_panels.might_label",  0x43FFC7, "t_dp_txt_wl3"),
    ("DiploTalkWin_draw_news_panel.sep_pixel",  0x43F801, "t_dp_news_sep"),
    ("DiploTalkWin_draw_news_panel.sep_line",   0x43F818, "t_dp_news_hline"),
    ("DiploTalkWin_draw_news_panel.name",       0x43F8D1, "t_dp_news_t1"),
    ("DiploTalkWin_draw_news_panel.reputation", 0x43F9BA, "t_dp_news_t2"),
    ("DiploTalkWin_draw_news_panel.mood",       0x43FA82, "t_dp_news_t3"),
    # NB patches.yaml + _fragment_diplo_sites.yaml point this site at thunk_art_bioinit (assemble_artreblit.py, 2026-09-21),
    # which wraps t_dp_flinit_bio: TAKEN_OVER (below) emits that shipped target.
    ("DiploTalkWin_open.flic_bio",      0x43F45E, "t_dp_flinit_bio"),
    ("DiploTalkWin_open.flic_news",     0x43F4DD, "t_dp_flinit_news"),
    ("DiploTalkWin_open.flic_news_fallback", 0x43F504, "t_dp_flinit_news"),
    # NB patches.yaml + _fragment_diplo_sites.yaml point these three flic sites at thunk_art_flic (assemble_artreblit.py,
    # 2026-09-20), which wraps t_dp_flicdraw with the scanline re-blit: TAKEN_OVER (below) emits that shipped target.
    ("DiploTalkWin_open.news_first_draw",    0x43F596, "t_dp_flicdraw"),
    ("DiploTalkWin_bioscan_tick.draw",       0x43F22C, "t_dp_flicdraw"),
    ("DiploTalkWin_news_tick.draw",          0x43F26F, "t_dp_flicdraw"),
] + [(f"tile_panels_wrap.site_{va:06x}", va, "t_cr_tile_exit" if va == TILE_EXIT_SITE else "t_cr_tile")
      for va in TILE_SITES]
EXPECT_TARGET = {"t_fontinit": 0x618F40, "t_dp_table": BASEBTN_INIT, "t_dp_box_centre": BOX_SPRITE, "t_dp_box_hqunion": BOX_SPRITE,
                 "t_dp_box_panel": BOX_SPRITE, "t_dp_box_hq": BOX_SPRITE, "t_dp_c7_bio": CENT7, "t_dp_c7_hq": CENT7,
                 "t_dp_sd2_bar": SPRITE_DRAW_2, "t_dp_sd2_logo": SPRITE_DRAW_2, "t_dp_sd2_hqpic": SPRITE_DRAW_2, "t_dp_sd2_bezel": SPRITE_DRAW_2,
                 "t_dp_cent6": WRAP_CENT_6, "t_dp_txt_wrap3": WRAP_3, "t_dp_txt_wl3": WRITE_L_3, "t_dp_news_sep": GET_PIXEL,
                 "t_dp_news_hline": HLINE_2, "t_dp_news_t1": WRITE_L_3, "t_dp_news_t2": WRITE_L_3, "t_dp_news_t3": WRITE_L_3,
                 "t_dp_flinit_bio": FLIC_INIT, "t_dp_flinit_news": FLIC_INIT, "t_dp_flicdraw": FLIC_DRAW,
                 "t_cr_tile": TILE_PANELS, "t_cr_tile_exit": TILE_PANELS,
                 "t_dp_status_fit": WRAP_3}

ks = Ks(KS_ARCH_X86, KS_MODE_32)
YAML = os.path.join(os.path.dirname(__file__), "..", "patches", "patches.yaml")
GROUP = "diplo_talk_scale"
MARK_B = f"# ==== {GROUP} BEGIN (src assemble_diplo.py) ===="
MARK_E = f"# ==== {GROUP} END ===="


def assemble(name: str, asm: str, va: int) -> bytes:
    try:
        enc, _ = ks.asm(asm, va)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"[{name}] keystone: {e}\n{asm}")
    return bytes(enc)


def assemble_all():
    layout = {}
    off = THUNKS_OFF
    for name, asm in THUNK_ASM.items():
        if name in FIXED_OFF:
            fo = FIXED_OFF[name]
            blob = assemble(name, asm, PCAVE2_VA + fo)
            layout[name] = (fo, blob)
            continue
        blob = assemble(name, asm, PCAVE2_VA + off)
        layout[name] = (off, blob)
        off = (off + len(blob) + 3) & ~3
    # the sequential region must stay clear of the fixed save-under block
    assert off <= CR_CELLS_OFF, f"sequential thunks overran the save-under cells: {off:#x} > {CR_CELLS_OFF:#x}"
    end = off
    for n, (lo, hi) in LOW_HOLES.items():            # fixed slots BELOW the sequential region: each stays inside its hole
        fo, blob = layout[n]
        assert fo == lo and fo + len(blob) <= hi, f"{n}: {fo:#x}+{len(blob)} overruns its hole {lo:#x}..{hi:#x}"
    fixed = sorted((fo, fo + len(layout[n][1]), n) for n, fo in FIXED_OFF.items() if n not in LOW_HOLES)
    prev_end = CR_CELLS_OFF + sum(sz for _, sz in CELLS2)   # save-under cells end
    for fs, fe, n in fixed:
        assert fs >= prev_end, f"{n} overlaps previous block: {fs:#x} < {prev_end:#x}"
        prev_end = fe
        end = max(end, fe)
    for n, (hs, he) in STATUS_HOLES.items():          # the 2026-10-11 reserved holes, never grown
        fo, blob = layout[n]
        assert fo == hs and fo + len(blob) <= he, f"{n}: {fo:#x}+{len(blob)} overruns its hole {hs:#x}..{he:#x}"
    tail = layout["t_dp_status_tail"][1]
    assert tail[0] == 0xEB and tail[2] == 0xEB, "t_dp_status_tail: +0/+2 must be 2-byte short jmps (SF_NATINIT/SF_MEAS)"
    return layout, end


def to_tokens(blob: bytes) -> str:
    return " ".join(f"{b:02X}" for b in blob)


def orig_bytes(pe, va: int, n: int = 5) -> bytes:
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def site_entry(sid, va, ln, orig, newb, pattern, comment="", nb_comment=""):
    return (f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {sid.split('.')[0]}\n"
            f"    virtual_addr: {va:#010x}\n    length: {ln}\n    original_bytes: \"{orig}\"{('  # ' + comment) if comment else ''}\n"
            f"    new_bytes:      \"{newb}\"{('   # ' + nb_comment) if nb_comment else ''}\n    pattern: {pattern}\n")


# Sites a later bake took over (assemble_artreblit.py, popup_art_reblit): each wrapper calls the thunk REDIRECTS
# names, so REDIRECTS keeps it (the original-target check) and the fragment carries the SHIPPED target + its comment.
TAKEN_OVER = {
    "DiploTalkWin_open.flic_bio": (
        "thunk_art_bioinit",
        "popup_art_reblit 2026-09-21: wraps t_dp_flinit_bio (was {rel32:t_dp_flinit_bio}); fills the flic canvas "
        "with key 9 + captures the device save-under"),
    **{sid: ("thunk_art_flic", "popup_art_reblit 2026-09-20: wraps t_dp_flicdraw (was {rel32:t_dp_flicdraw})")
       for sid in ("DiploTalkWin_open.news_first_draw", "DiploTalkWin_bioscan_tick.draw", "DiploTalkWin_news_tick.draw")},
}


def build_fragments():
    layout, end = assemble_all()
    assert end <= SECTION_END, f"content overruns section: {end:#x} > {SECTION_END:#x}"
    pe = pefile.PE(str(config.terranx_bak()))
    for sid, va, thunk in REDIRECTS:
        ob = orig_bytes(pe, va)
        assert ob[0] == 0xE8, f"{sid}: not a CALL at {va:#x}: {ob.hex()}"
        tgt = (va + 5 + int.from_bytes(ob[1:5], "little", signed=True)) & 0xFFFFFFFF
        assert tgt == EXPECT_TARGET[thunk], f"{sid}: call target {tgt:#x} != expected {EXPECT_TARGET[thunk]:#x}"
    for sid, va, thunk, exp in POPUP_REDIRECTS:
        ob = orig_bytes(pe, va)
        assert ob[0] == 0xE8, f"{sid}: not a CALL at {va:#x}"
        tgt = (va + 5 + int.from_bytes(ob[1:5], "little", signed=True)) & 0xFFFFFFFF
        assert tgt == exp, f"{sid}: call target {tgt:#x} != expected {exp:#x}"
    for sid, va, thunk in VTABLES:
        assert orig_bytes(pe, va, 4) == ITEM_BACK_DRAW.to_bytes(4, "little"), f"{sid}: vtable slot mismatch"
    for sid, va, thunk, exp in VTABLES2:
        assert orig_bytes(pe, va, 4) == exp.to_bytes(4, "little"), f"{sid}: vtable slot != {exp:#x}"

    sym = []
    o = BASE_OFF
    for n, sz in CELLS:
        sym.append(f"  {n}:{' ' * max(1, 30 - len(n) - 3)}{{ cave: pcave2, offset: {o:#x}, size: {sz} }}   # {sz}B diplo cell (src assemble_diplo.py)")
        o += sz
    o = CR_CELLS_OFF
    for n, sz in CELLS2:
        sym.append(f"  {n}:{' ' * max(1, 30 - len(n) - 3)}{{ cave: pcave2, offset: {o:#x}, size: {sz} }}   # {sz}B console save-under cell (src assemble_diplo.py)")
        o += sz
    o = FIT_CELLS_OFF
    for n, sz in CELLS3:
        sym.append(f"  {n}:{' ' * max(1, 30 - len(n) - 3)}{{ cave: pcave2, offset: {o:#x}, size: {sz} }}   # {sz}B status-line fit cell (src assemble_diplo.py)")
        o += sz
    for name in layout:
        off, blob = layout[name]
        sym.append(f"  {name}:{' ' * max(1, 30 - len(name) - 3)}{{ cave: pcave2, offset: {off:#x} }}   # {len(blob)}B {GROUP} (src assemble_diplo.py)")
    ce = []
    for name in layout:
        off, blob = layout[name]
        ce.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{to_tokens(blob)}\"\n")
    sites = []
    for sid, va, thunk in REDIRECTS:
        thunk, nb_comment = TAKEN_OVER.get(sid, (thunk, ""))
        sites.append(site_entry(sid, va, 5, to_tokens(orig_bytes(pe, va)), f"E8 {{rel32:{thunk}}}", "call_target_redirect",
                                nb_comment=nb_comment))
    for sid, va, thunk, exp in POPUP_REDIRECTS:
        sites.append(site_entry(sid, va, 5, to_tokens(orig_bytes(pe, va)), f"E8 {{rel32:{thunk}}}", "call_target_redirect"))
    for sid, va, ln, thunk in CUTS:
        nops = " 90" * (ln - 5)
        sites.append(site_entry(sid, va, ln, to_tokens(orig_bytes(pe, va, ln)), f"E8 {{rel32:{thunk}}}{nops}", "block_cut_thunk"))
    for sid, va, thunk in VTABLES:
        sites.append(site_entry(sid, va, 4, to_tokens(orig_bytes(pe, va, 4)), f"{{abs32:{thunk}}}", "vtable_repoint", "Popup_on_dialog_item_back_draw slot"))
    for sid, va, thunk, exp in VTABLES2:
        sites.append(site_entry(sid, va, 4, to_tokens(orig_bytes(pe, va, 4)), f"{{abs32:{thunk}}}", "vtable_repoint", "DiploTalkIface_on_mode slot (console save-under snapshot)"))
    seq_end = max(o + len(b) for n, (o, b) in layout.items() if n not in FIXED_OFF)
    fixed_txt = ", ".join(f"{n} {layout[n][0]:#x}" for n in sorted(FIXED_OFF, key=lambda n: layout[n][0]))
    members = [sid for sid, *_ in REDIRECTS] + [sid for sid, *_ in POPUP_REDIRECTS] + [sid for sid, *_ in CUTS] + [sid for sid, *_ in VTABLES] + [sid for sid, *_ in VTABLES2]
    group = (f"  - id: {GROUP}\n    description: >\n"
             f"      DIPLOMACY talk screen: the anchored speech box (DiploTalkWin 700x450 window, backdrop/title/text-block\n"
             f"      frames + strokes, header/art column/row gap/OK row/measure width anchored arms) and the console-strip\n"
             f"      content under it (3 fonts, panel rect table, BIOSCAN/status/HQ painters, faction logo/colour bar/HQ\n"
             f"      picture/bezel sprite ratios, the two flics dst-bounced, DATALINKS/PROFILE/HQINFO frame zoom) all scale\n"
             f"      vanilla x g/16; g<=16 native no-op.  Proto hook_diplo_proto.js v9d/v10 user-verified 4K+1600 2026-08-17/18.\n"
             f"      src assemble_diplo.py: sequential thunks pcave2 {THUNKS_OFF:#x}..{seq_end:#x}, cells {BASE_OFF:#x}; fixed blocks\n"
             f"      {fixed_txt};\n"
             f"      cells {CR_CELLS_OFF:#x} (save-under), {FIT_CELLS_OFF:#x} (status fit).  Also repoints 8 existing\n"
             f"      sites at anchored-gate wrappers (see EXISTING_REPOINTS) and prefixes thunk_btn_gate (v8).\n"
             f"      PLUS the console save-under (proto v6 user-verified 4K 2026-08-20): t_cr_snap on the iface vtbl\n"
             f"      snapshots the strip's centre column on diplo enter; t_cr_tile wraps all 12 tile_panels callers and\n"
             f"      blits it back after every armed normal-mode pass (this==MainWin gate), fixing the exit residue.\n"
             f"      PLUS the status-line fit (2026-10-11): t_dp_status_fit at 0x43FE07 steps the +0xA44 font down until\n"
             f"      'DIPLOMATIC STATUS: <treaty>' fits one line wherever vanilla shows one line (law diplo_status_font_size).\n"
             f"    code_caves:\n      - pcave2\n    members:\n" + "".join(f"      - {m}\n" for m in members))
    return layout, end, sym, ce, sites, group


def read_text_eol(path: str):
    """(text with LF newlines, the file's EOL): CRLF when most of its newlines are CRLF, else LF."""
    with open(path, "rb") as fh:
        data = fh.read()
    crlf, lf = data.count(b"\r\n"), data.count(b"\n")
    eol = "\r\n" if crlf and 2 * crlf >= lf else "\n"
    return data.decode("utf-8").replace("\r\n", "\n"), eol


def write_text_eol(path: str, text: str, default_eol: str = "\n") -> bool:
    """Write LF `text` with the EOL the file already has (default_eol for a new file).  A file whose bytes would
    not change is left untouched (no write, mtime kept).  Returns True when the file was written."""
    eol = read_text_eol(path)[1] if os.path.exists(path) else default_eol
    new = text.replace("\r\n", "\n").replace("\n", eol).encode("utf-8")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            if fh.read() == new:
                return False
    with open(path, "wb") as fh:
        fh.write(new)
    return True


def fragment_texts(sym, ce, sites, group) -> dict:
    """The four _fragment_diplo_*.yaml bodies (LF), by file name -- the pure emit of this assembler."""
    return {"_fragment_diplo_symbols.yaml": "\n".join(sym) + "\n", "_fragment_diplo_cave.yaml": "\n".join(ce),
            "_fragment_diplo_sites.yaml": "\n".join(sites), "_fragment_diplo_group.yaml": group}


def write_fragments(pdir: str, texts: dict) -> list:
    """Write the fragments into pdir, each keeping its own EOL; returns the names actually rewritten."""
    return [fn for fn, body in texts.items() if write_text_eol(os.path.join(pdir, fn), body)]


def splice_text(txt: str, sym, ce, sites, group) -> str:
    """patches.yaml text (LF) with this group's four marker-guarded blocks set to the emit.  A block already present is
    replaced IN PLACE (so a second splice is a no-op); a missing one is inserted before the last `# ----` header of
    its section (sites: appended at the end).  Then the EXISTING_REPOINTS, the thunk_btn_gate prefix and the pcave2
    length bump, each a no-op once applied."""
    def block(sect, body):
        return f"{MARK_B} {sect}\n{body.rstrip()}\n{MARK_E} {sect}\n"

    def ids(sect, s):
        return set(re.findall(r"^  ([A-Za-z_]\w*):" if sect == "symbols" else r"^ *- id: (\S+)", s, re.M))

    def put(txt, sect, body, before):
        pat = re.compile(rf"^{re.escape(MARK_B)} {sect}\n.*?\n{re.escape(MARK_E)} {sect}\n", re.S | re.M)
        m = pat.search(txt)
        if m:
            foreign = sorted(ids(sect, m.group(0)) - ids(sect, body))
            if foreign:      # an entry another bake (or a hand edit) put inside OUR block: a re-splice would delete it
                raise SystemExit(f"[splice] {sect} block holds entries this assembler does not emit: {foreign}; "
                                 f"move them out of the {GROUP} markers (or retire them) first")
            return txt[:m.start()] + block(sect, body) + txt[m.end():]
        if before is None:
            return txt.rstrip("\n") + "\n\n" + block(sect, body)
        i = txt.index(before)
        j = txt.rfind("\n# ----", 0, i)
        return txt[:j] + "\n" + block(sect, body) + txt[j:]
    txt = put(txt, "symbols", "\n".join(sym), "\ncode_caves:")
    txt = put(txt, "cave", "\n".join(ce), "\ngroups:")
    txt = put(txt, "groups", group, "\nsites:")
    txt = put(txt, "sites", "\n".join(sites), None)
    for va, (old, new) in EXISTING_REPOINTS.items():
        key = f"virtual_addr: 0x{va:08X}"
        i = txt.find(key)
        if i < 0:
            i = txt.index(f"virtual_addr: {va:#010x}")
        j = txt.index("new_bytes:", i)
        k = txt.index("\n", j)
        line = txt[j:k]
        q0 = line.index('"')
        q1 = line.index('"', q0 + 1) + 1
        val = line[q0:q1]                       # the quoted value only: the trailing comment names old targets too
        if new in val or (va in REPOINT_TAKEN_OVER and REPOINT_TAKEN_OVER[va] in val):
            continue
        assert old in val, f"repoint {va:#x}: expected {old} in {val!r}"
        txt = (txt[:j] + line[:q0] + val.replace(old, new) + line[q1:] + f"   # {GROUP}: anchored-gate wrapper (was {old})"
               + txt[k:])
    i = txt.index("      - id: thunk_btn_gate\n")
    j = txt.index("bytes: \"", i) + len("bytes: \"")
    k = txt.index("\"", j)
    body = txt[j:k]
    pre = to_tokens(btn_gate_prefix())
    if not body.startswith(pre):
        txt = txt[:j] + pre + " " + body + txt[k:]
    txt = re.sub(r"(  - id: pcave2\n(?:.*\n){3}    length: )0x1[23]000", r"\g<1>0x14000", txt, count=1)
    return txt


def splice(sym, ce, sites, group, yaml_path: str = None) -> bool:
    """Splice the emit into patches.yaml (or yaml_path), keeping its EOL; no write when nothing changes."""
    path = yaml_path or YAML
    txt, _eol = read_text_eol(path)
    return write_text_eol(path, splice_text(txt, sym, ce, sites, group))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="assemble the diplo_talk_scale bake")
    ap.add_argument("--splice", action="store_true", help="also splice the emit into patches.yaml (idempotent)")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "patches"),
                    help="where the _fragment_diplo_*.yaml files go (default work\\patches)")
    ap.add_argument("--yaml", default=YAML, help="the patches.yaml --splice edits (default work\\patches\\patches.yaml)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    layout, end, sym, ce, sites, group = build_fragments()
    print(f"cells @ pcave2+{BASE_OFF:#x}: " + ", ".join(f"{n}={CELL_VA[n] - PCAVE2_VA:#x}" for n, _ in CELLS))
    print(f"thunks: pcave2+{THUNKS_OFF:#x} .. +{end:#x}  ({end - THUNKS_OFF} B)")
    for name in layout:
        off, blob = layout[name]
        print(f"  {name:22s} +{off:#x} {len(blob)}B")
    pdir = args.out_dir
    changed = write_fragments(pdir, fragment_texts(sym, ce, sites, group))
    print(f"[sites] {len(sites)} entries; fragments -> {pdir}\\_fragment_diplo_*.yaml "
          f"({', '.join(changed) if changed else 'all unchanged, not rewritten'})")
    if args.splice:
        print(f"[splice] {args.yaml} " + ("updated" if splice(sym, ce, sites, group, args.yaml) else "unchanged (no-op)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
