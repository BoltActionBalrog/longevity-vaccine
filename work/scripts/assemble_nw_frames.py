"""Assembler for the MULTIPLAYER SETUP lobby's frame strokes (group netwin_frame_strokes, 2026-11-07).

The lobby (NetWin 0x80A6F8, painter NetWin_draw 0x481AD0 and its section painters) draws every frame with
Buffer_box_sprite at the scaled rect table: the 9-slice corners / edges blit 1:1, so at g > 16 every stroke stayed
1 px while the window around it grew x g/16 (ACTION_ITEMS "NetWin lobby: lock-cell/section frames stay 1 px").
Five frame styles (the params' sprites, dumped from the image): d690 window backdrop (stroke 1A, fill C6/41), d5a0
section outline (stroke 1F, 2-step bevel, no fill), d618 title / header bands and d528 panels (stroke 22, fill
C4/41), dca8 roster toggle cells (stroke 1F, fill 27/22).  Every one but d5a0 is a 1-px stroke whose corner pixel
is keyed (a 1-px chamfer) over a fill mask; d5a0 is a 1-px stroke with a one-pixel diagonal bevel step.

Law (scaling_laws.nw_frame_bands / nw_frame_interior): the frame the band-map thickener draws (the popup family's and the tech
breakthrough window's thunk_box_thick_hollow_flat / thunk_box_thick_devfill, fed the half-open rect as
bandmap_rect_from_halfopen) -- K = stroke_width(g) = half_down(g, 16) on every edge, the chamfer a K x K keyed block,
the bevel step a K x K block -- with the filled boxes' interior inside the K band on the lobby's panel stripe law
(fix 28 v2 / F37, panel_fill_pixel, phase 0 on the NetWin canvas).  The band-map thunks are ~10x the lobby's whole
repaint at 4K (they walk every pixel of every panel, the 2000x1500 backdrop included, three times), so the baked
path paints the same pixels directly: the engine box at its own rect (its fast 1:1 tile fill), the K-wide stroke
band over it, the K x K corner blocks put back as they were before the box, then the stripe tail.  The band-map
thunks stay here as ORACLE: tests/test_scaling_nw_frames.py requires the baked thunks to draw exactly their pixels.
The title band's inset from its outline is the engine's native 3 (0x481B33 `mov eax, 3`) -> scale_px(3, g)
(nw_title_band_inset), like every other nested lobby pair, whose rects come from the already-scaled rect table.
Two neighbours the thicker strokes expose, fixed here: the title outline's bottom (thunk_nw_rectscale stores
T + fl(26g/16) with T = fl(3g/16), up to 1.44 px short of 29 g/16 -> nw_title_rect_bottom), and the roster lock icon,
drawn at the lock cell's L + 1 (vanilla: the column after its 1-px stroke) -> L + K (nw_lock_icon_x; it covered the
inner stroke column at K = 2).

Thunks (pcave2 0x40000..0x407FF: the MP region 0x40000..0x40FFF, pcave2 grown 0x40000 -> 0x41000 for it -- every older
0x1000 block belongs to a wave; this group takes 0x40000..0x409FF, commlink_mp_spots 0x40A00..):
  t_nwf_bm    the four d5a0 section-outline sites' call-target (thiscall ecx = dest Buffer; RECT* half-open, params;
              RET 8): g <= 16 -> push Buffer_box_sprite / ret (the vanilla call, untouched); else eax = 1, on to
              t_nwf_core.
  t_nwf_box   the 17 filled sites' call-target (was {rel32:t_nw_box}): g <= 16 -> the vanilla call; else eax = 0,
              on to t_nwf_core.
  t_nwf_title the title outline site 0x481B28 (the rect is NetWin_draw's local copy of +0xA14, which it then insets for
              the title band and centres the title text in): g <= 16 -> the vanilla call; else B := T - fl(3g/16) +
              fl(29g/16), eax = 1, on to t_nwf_core.
  t_nwf_lock  the roster lock icon's Sprite_draw_2 site 0x480599 (was {rel32:thunk_nw_toggle}): g > 16 -> x += K - 1;
              then thunk_nw_toggle (num g / den 16).  Registers preserved.
  t_nwf_core  K = half_down(g, 16).  Guards (else t_nw_box for a filled box -- the shipped fix 28 v2 behaviour -- or
              the plain engine box for an outline): 1 <= K <= 4, the rect at least 6K each way,
              the dest has a pixel plane, the params' TL corner sprite is memory-backed, unoffset, >= 3x3, and its
              top-left 3x3 is the class's shape (chamfer: key, stroke, stroke, fill-not-stroke; bevel: key key key
              on the corner L, stroke on the diagonal) -- the stroke colour is read from it.
              Chamfer (filled): save the four K x K corner blocks of the dest, the engine box, the four stroke bands
              [L+K, R-K) x [T, T+K) / [B-K, B) and [L, L+K) / [R-K, R) x [T+K, B-K), restore the blocks, then
              t_nw_box's stripe tail over [L+K, R-K) x [T+K, B-K).  Bevel (outline): no engine box (it has no fill);
              the runs [L+2K, R-2K) x [T, T+K) / [B-K, B), [L, L+K) / [R-K, R) x [T+2K, B-2K) and the four K x K
              steps at (L+K, T+K), (R-2K, T+K), (L+K, B-2K), (R-2K, B-2K).  Every write is clipped to the dest
              clip (+0x20..+0x2C) and the buffer, as the engine's own box.  RET 8.
  t_nwf_ins3  CALL at 0x481B33 (replaces `mov eax, 3`): eax = 3 at g <= 16, else scale_px(3, g).  Clobbers
              eax / flags only (the site's next instructions overwrite the flags).
  t_nwf_ts    the chat log's TextScroll_attach site 0x482A00: x, y += d, w, h -= 2d, d = scale_px(3, g) - 3 (law
              nw_chat_log_inset: the native 3-px inset left a 1-px gap to the K = 2 stroke).
  g_nwf_rect  16-byte RECT cell (zero at rest; only the ORACLE thunks use it).

Parity / end to end: tests/test_scaling_nw_frames.py (the whole lobby drawn by the real image at every g 16..40:
baked == ORACLE pixel for pixel, the strokes K wide and symmetric, the interior on the stripe law, g = 16 equal to
the pristine exe, the title band at vanilla x g/16).

Usage: assemble_nw_frames.py   -> prints the yaml symbol + content lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: F401,E402  (every keystone import is guarded)

PCAVE2 = 0x00A0C000
REGION = (0x40000, 0x40A00)       # the MP region 0x40000..0x40FFF (pcave2 grown 0x40000 -> 0x41000, 2026-11-07): 0x40000..0x409FF
SLOTS = {
    "t_nwf_bm": 0x40000,
    "t_nwf_box": 0x40020,
    "t_nwf_ins3": 0x40040,
    "t_nwf_title": 0x40060,
    "t_nwf_lock": 0x400A0,
    "t_nwf_core": 0x400E0,
    "t_nwf_ts": 0x40800,
    "g_nwf_rect": 0x409F0,
}
# where the tests drop the oracle bytes: the outline oracle AT t_nwf_core (t_nwf_title tails there), the box after it
ORACLE_SLOTS = {"t_nwf_bm": 0x400E0, "t_nwf_box": 0x40140}
G = 0x00668740                     # g_popup_scale_num
BUFFER_BOX_SPRITE = 0x005E2DD3     # thiscall(ecx = dest Buffer; RECT* half-open, BoxSpriteParams*) RET 8
HOLLOWFLAT = PCAVE2 + 0x140        # thunk_box_thick_hollow_flat (same contract, inclusive footprint)
DEVFILL = PCAVE2 + 0x42A0          # thunk_box_thick_devfill v2 (same contract, inclusive footprint, stripe tail)
T_NW_BOX = PCAVE2 + 0x33700        # t_nw_box (fix 28 v2): the engine box + the panel stripe law -- the guard fallback
NW_TOGGLE = PCAVE2 + 0x4960        # thunk_nw_toggle: the roster lock icon's Sprite_draw_2 at num g / den 16
G_STRIPE_PERIOD = 0x0066879C       # g_stripe_period (P = 2T)
RECT = PCAVE2 + SLOTS["g_nwf_rect"]
CORE = PCAVE2 + SLOTS["t_nwf_core"]
TITLE_INSET_SITE = 0x00481B33      # NetWin_draw: `mov eax, 3` (B8 03 00 00 00), the d618 title band inset
TITLE_INSET_NATIVE = 3
TITLE_OUTLINE_SITE = 0x00481B28    # NetWin_draw: the title outline's Buffer_box_sprite (rect = its local A14 copy)
LOCK_ICON_SITE = 0x00480599        # NetWin_draw_players: the roster lock icon (call thunk_nw_toggle), x = cell L + 1
CHAT_LOG_SITE = 0x00482A00         # NetWin_setup_lobby: TextScroll_attach(chat log) at the panel rect + native 3 / - 6
TEXTSCROLL_ATTACH = 0x006292D0     # TextScroll_attach(thiscall; x, y, w, h, parent, 0, -1)
K_MAX = 4

ABS = {G: "{abs32:g_popup_scale_num}", G_STRIPE_PERIOD: "{abs32:g_stripe_period}", RECT: "{abs32:g_nwf_rect}",
       BUFFER_BOX_SPRITE: "{abs32:Buffer_box_sprite}", HOLLOWFLAT: "{abs32:thunk_box_thick_hollow_flat}",
       CORE: "{abs32:t_nwf_core}", NW_TOGGLE: "{abs32:thunk_nw_toggle}"}
REL = {BUFFER_BOX_SPRITE: "{rel32:Buffer_box_sprite}", DEVFILL: "{rel32:thunk_box_thick_devfill}",
       T_NW_BOX: "{rel32:t_nw_box}"}

# the sites: every `E8 rel32` call to Buffer_box_sprite the lobby painters make (census of NetWin_draw on the image)
OUTLINE_SITES = (            # d5a0, no fill: the four section outlines (plain engine calls today; the title's is
    ("NetWin_draw_options.outline_d5a0", 0x0047F992),       # TITLE_OUTLINE_SITE -> t_nwf_title)
    ("NetWin_draw.outline_d5a0_chat", 0x00481BFC),
    ("NetWin_draw_players.outline_d5a0", 0x004803BA),
    ("NetWin_draw_settings.outline_d5a0", 0x00480993),
)
FILLED_SITES = (             # the 17 netwin_panel_stripes sites ({rel32:t_nw_box} today)
    0x0047F9A5, 0x0047FA3E, 0x0047FA51, 0x0047FEAB, 0x0047FEBE, 0x0047FF2B, 0x004801DB, 0x004803CD, 0x0048049D,
    0x004804B0, 0x004804D6, 0x004809A6, 0x00480A40, 0x00481AFB, 0x00481B5D, 0x00481C0F, 0x00481C22,
)


# ---- frame locals of t_nwf_core / the oracle box (ebp-relative) ----
L_TH, L_TW, L_A, L_B, L_TOP, L_MATE = -0x04, -0x08, -0x0C, -0x10, -0x14, -0x18
L_IL, L_IT, L_IR, L_IB = -0x1C, -0x20, -0x24, -0x28          # the stripe tail's interior rect (clamped there)
L_K, L_S = -0x2C, -0x30                                       # stroke width, stroke colour
L_L, L_T, L_R, L_BB = -0x34, -0x38, -0x3C, -0x40              # the caller's half-open rect
L_CL, L_CT, L_CR, L_CB = -0x44, -0x48, -0x4C, -0x50           # clip ∩ buffer, half-open
L_CLS, L_ROW = -0x54, -0x58
SAVE = -0xA0                                                  # 4 corners x K_MAX^2 bytes
FRAME = 0xA8


def _e(off: int) -> str:
    return f"ebp-{-off:#x}" if off < 0 else f"ebp+{off:#x}"


def _rect_copy() -> str:
    """[esp+4] RECT -> g_nwf_rect with R-1 / B-1 (law bandmap_rect_from_halfopen); repoint [esp+4]."""
    out = ["    mov eax, dword ptr [esp+4]"]
    for i in range(4):
        out.append(f"    mov edx, dword ptr [eax+{4 * i}]")
        if i >= 2:
            out.append("    dec edx")
        out.append(f"    mov dword ptr [{RECT + 4 * i:#x}], edx")
    out.append(f"    mov dword ptr [esp+4], {RECT:#x}")
    return "\n".join(out)


def _stripe_tail() -> str:
    """t_nw_box's own stripe tail (assemble_checkbox_stripes.asm_nw_box), its fill rect replaced by the interior
    inside the K-wide stroke band: [L+K, R-K) x [T+K, B-K) of the caller's rect [ebp+8], K at L_K.  Ends at `done`
    (restores ebx / esi / edi, leave, RET 8)."""
    return f"""
    mov     eax, dword ptr [ebp+0xc]
    test    eax, eax
    je      done
    mov     edi, dword ptr [eax+0x20]
    test    edi, edi
    je      done
    mov     eax, dword ptr [{G_STRIPE_PERIOD:#x}]
    cmp     eax, 2
    jl      done
    shr     eax, 1
    mov     dword ptr [{_e(L_TH)}], eax
    cmp     dword ptr [esi+0x54], 0
    je      done
    mov     ecx, dword ptr [edi+0x80]
    test    ecx, ecx
    jle     done
    mov     dword ptr [{_e(L_TW)}], ecx
    mov     edx, dword ptr [edi+0x84]
    test    edx, edx
    jns     th_pos
    neg     edx
th_pos:
    cmp     edx, 4
    jl      done
    mov     ebx, dword ptr [edi+0x54]
    test    ebx, ebx
    je      done
    mov     edx, dword ptr [edi+0x4a8]
    test    edx, edx
    jle     done
    movzx   eax, byte ptr [ebx]
    mov     dword ptr [{_e(L_A)}], eax
    movzx   eax, byte ptr [ebx+edx]
    mov     dword ptr [{_e(L_B)}], eax
    cmp     eax, dword ptr [{_e(L_A)}]
    je      done
    xor     edi, edi
v_row:
    cmp     edi, 4
    jge     v_ok
    mov     eax, dword ptr [{_e(L_A)}]
    test    edi, 1
    je      v_even
    mov     eax, dword ptr [{_e(L_B)}]
v_even:
    xor     ecx, ecx
v_col:
    cmp     ecx, dword ptr [{_e(L_TW)}]
    jge     v_next
    cmp     al, byte ptr [ebx+ecx]
    jne     done
    inc     ecx
    jmp     v_col
v_next:
    add     ebx, edx
    inc     edi
    jmp     v_row
v_ok:
    mov     ecx, dword ptr [{_e(L_A)}]
    mov     edx, dword ptr [{_e(L_B)}]
    movzx   eax, byte ptr [esi+ecx*4+0xa4]
    movzx   edi, byte ptr [esi+ecx*4+0xa5]
    add     eax, edi
    movzx   edi, byte ptr [esi+ecx*4+0xa6]
    add     eax, edi
    movzx   ebx, byte ptr [esi+edx*4+0xa4]
    movzx   edi, byte ptr [esi+edx*4+0xa5]
    add     ebx, edi
    movzx   edi, byte ptr [esi+edx*4+0xa6]
    add     ebx, edi
    cmp     eax, ebx
    ja      a_top
    jb      b_top
    cmp     ecx, edx
    jb      a_top
b_top:
    xchg    ecx, edx
a_top:
    mov     dword ptr [{_e(L_TOP)}], ecx
    mov     dword ptr [{_e(L_MATE)}], edx
    mov     eax, dword ptr [ebp+8]
    mov     edx, dword ptr [{_e(L_K)}]
    mov     ecx, dword ptr [eax]
    add     ecx, edx
    mov     dword ptr [{_e(L_IL)}], ecx
    mov     ecx, dword ptr [eax+4]
    add     ecx, edx
    mov     dword ptr [{_e(L_IT)}], ecx
    mov     ecx, dword ptr [eax+8]
    sub     ecx, edx
    mov     dword ptr [{_e(L_IR)}], ecx
    mov     ecx, dword ptr [eax+0xc]
    sub     ecx, edx
    mov     dword ptr [{_e(L_IB)}], ecx
    mov     eax, dword ptr [esi+0x20]
    test    eax, eax
    jns     c1
    xor     eax, eax
c1:
    cmp     eax, dword ptr [{_e(L_IL)}]
    jge     c1s
    mov     eax, dword ptr [{_e(L_IL)}]
c1s:
    mov     dword ptr [{_e(L_IL)}], eax
    mov     eax, dword ptr [esi+0x24]
    test    eax, eax
    jns     c2
    xor     eax, eax
c2:
    cmp     eax, dword ptr [{_e(L_IT)}]
    jge     c2s
    mov     eax, dword ptr [{_e(L_IT)}]
c2s:
    mov     dword ptr [{_e(L_IT)}], eax
    mov     eax, dword ptr [esi+0x28]
    cmp     eax, dword ptr [esi+0x80]
    jle     c3
    mov     eax, dword ptr [esi+0x80]
c3:
    cmp     eax, dword ptr [{_e(L_IR)}]
    jle     c3s
    mov     eax, dword ptr [{_e(L_IR)}]
c3s:
    mov     dword ptr [{_e(L_IR)}], eax
    mov     edx, dword ptr [esi+0x84]
    test    edx, edx
    jns     c4h
    neg     edx
c4h:
    mov     eax, dword ptr [esi+0x2c]
    cmp     eax, edx
    jle     c4
    mov     eax, edx
c4:
    cmp     eax, dword ptr [{_e(L_IB)}]
    jle     c4s
    mov     eax, dword ptr [{_e(L_IB)}]
c4s:
    mov     dword ptr [{_e(L_IB)}], eax
    mov     ebx, dword ptr [{_e(L_IT)}]
r_row:
    cmp     ebx, dword ptr [{_e(L_IB)}]
    jge     done
    mov     eax, ebx
    xor     edx, edx
    div     dword ptr [{_e(L_TH)}]
    mov     edx, dword ptr [{_e(L_TOP)}]
    test    al, 1
    je      r_top
    mov     edx, dword ptr [{_e(L_MATE)}]
r_top:
    mov     edi, ebx
    imul    edi, dword ptr [esi+0x4a8]
    add     edi, dword ptr [esi+0x54]
    mov     ecx, dword ptr [{_e(L_IL)}]
r_col:
    cmp     ecx, dword ptr [{_e(L_IR)}]
    jge     r_next
    mov     al, byte ptr [edi+ecx]
    cmp     al, byte ptr [{_e(L_A)}]
    je      r_put
    cmp     al, byte ptr [{_e(L_B)}]
    jne     r_skip
r_put:
    mov     byte ptr [edi+ecx], dl
r_skip:
    inc     ecx
    jmp     r_col
r_next:
    inc     ebx
    jmp     r_row
done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     8"""


# ---- the baked thunks ----

def asm_entry(cls: int) -> str:
    """t_nwf_bm (cls 1, the d5a0 outlines) / t_nwf_box (cls 0, the filled panels): g <= 16 -> the vanilla call
    (push Buffer_box_sprite / ret, ecx and the stack untouched); else eax = cls and on into t_nwf_core."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      hi
    push    {BUFFER_BOX_SPRITE:#x}
    ret
hi:
    mov     eax, {cls}
    push    {CORE:#x}
    ret
"""


def asm_ins3() -> str:
    """eax = scale_px(3, g) = (6g + 15) >> 5 at g > 16, else 3."""
    return f"""
    mov     eax, dword ptr [{G:#x}]
    cmp     eax, 0x10
    jg      hi
    mov     eax, {TITLE_INSET_NATIVE}
    ret
hi:
    imul    eax, eax, {2 * TITLE_INSET_NATIVE}
    add     eax, 0xf
    sar     eax, 5
    ret
"""


def asm_title() -> str:
    """t_nwf_title (the title outline site): g <= 16 -> the vanilla call; else the caller's rect copy's bottom :=
    T - fl(3g/16) + fl(29g/16) (law nw_title_rect_bottom; NetWin_draw insets the title band and centres the title text
    in the same local copy afterwards), eax = 1 (bevel) and on into t_nwf_core.  ecx (the dest) untouched."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      hi
    push    {BUFFER_BOX_SPRITE:#x}
    ret
hi:
    mov     eax, dword ptr [{G:#x}]
    imul    eax, eax, 29
    sar     eax, 4
    mov     edx, dword ptr [{G:#x}]
    lea     edx, [edx+edx*2]
    sar     edx, 4
    sub     eax, edx
    mov     edx, dword ptr [esp+4]
    add     eax, dword ptr [edx+4]
    mov     dword ptr [edx+0xc], eax
    mov     eax, 1
    push    {CORE:#x}
    ret
"""


def asm_lock() -> str:
    """t_nwf_lock (the roster lock icon's Sprite_draw_2 site; thiscall ecx = sprite, [esp+4] dest, +8 key, +0xC x,
    +0x10 y, +0x14 num, +0x18 den): g > 16 -> x += K - 1 (law nw_lock_icon_x: the engine's L + 1 -> L + K); then on
    into thunk_nw_toggle (num g / den 16).  Every register is preserved."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    mov     eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+0xf]
    sar     eax, 5
    dec     eax
    add     dword ptr [esp+0x10], eax
    pop     eax
go:
    push    {NW_TOGGLE:#x}
    ret
"""


def _v(base: int, kmul: int) -> str:
    """eax = [rect local base] + kmul * K"""
    out = [f"    mov     eax, dword ptr [{_e(base)}]"]
    if kmul:
        out.append(f"    mov     ecx, dword ptr [{_e(L_K)}]")
        if abs(kmul) == 2:
            out.append("    add     ecx, ecx")
        out.append(f"    {'add' if kmul > 0 else 'sub'}     eax, ecx")
    return "\n".join(out)


def _band(l, t, r, b) -> str:
    """call nwf_fill for [l, r) x [t, b), each operand a (rect local, K multiple) pair."""
    return "\n".join([
        _v(*b), "    push    eax",
        _v(*r), "    push    eax",
        _v(*t), "    push    eax",
        _v(*l),
        "    pop     ebx", "    pop     ecx", "    pop     edx",
        "    call    nwf_fill",
    ])


def asm_core() -> str:
    """t_nwf_core: thiscall ecx = dest Buffer, eax = class (0 chamfer, filled; 1 bevel, outline); [esp+4] RECT*
    half-open, [esp+8] BoxSpriteParams*; RET 8.  Law nw_frame_pixels."""
    L, T, R, B = L_L, L_T, L_R, L_BB
    bevel = "\n".join(_band(*x) for x in (
        ((L, 2), (T, 0), (R, -2), (T, 1)),          # top run
        ((L, 2), (B, -1), (R, -2), (B, 0)),         # bottom run
        ((L, 0), (T, 2), (L, 1), (B, -2)),          # left run
        ((R, -1), (T, 2), (R, 0), (B, -2)),         # right run
        ((L, 1), (T, 1), (L, 2), (T, 2)),           # TL bevel step
        ((R, -2), (T, 1), (R, -1), (T, 2)),         # TR
        ((L, 1), (B, -2), (L, 2), (B, -1)),         # BL
        ((R, -2), (B, -2), (R, -1), (B, -1)),       # BR
    ))
    chamfer = "\n".join(_band(*x) for x in (
        ((L, 1), (T, 0), (R, -1), (T, 1)),          # top band
        ((L, 1), (B, -1), (R, -1), (B, 0)),         # bottom band
        ((L, 0), (T, 1), (L, 1), (B, -1)),          # left band
        ((R, -1), (T, 1), (R, 0), (B, -1)),         # right band
    ))

    def corners(mode: int) -> str:
        out = []
        blocks = (((L, 0), (T, 0)), ((R, -1), (T, 0)), ((L, 0), (B, -1)), ((R, -1), (B, -1)))
        for k, (x, y) in enumerate(blocks):
            out += [_v(*y), "    mov     ebx, eax", _v(*x),
                    f"    lea     edi, [{_e(SAVE + k * K_MAX * K_MAX)}]",
                    f"    mov     edx, {mode}",
                    "    call    nwf_corner"]
        return "\n".join(out)

    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, {FRAME:#x}
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
    mov     dword ptr [{_e(L_CLS)}], eax
    mov     eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+0xf]
    sar     eax, 5
    mov     dword ptr [{_e(L_K)}], eax
    mov     eax, dword ptr [ebp+8]
    mov     ecx, dword ptr [eax]
    mov     dword ptr [{_e(L)}], ecx
    mov     ecx, dword ptr [eax+4]
    mov     dword ptr [{_e(T)}], ecx
    mov     ecx, dword ptr [eax+8]
    mov     dword ptr [{_e(R)}], ecx
    mov     ecx, dword ptr [eax+0xc]
    mov     dword ptr [{_e(B)}], ecx
    mov     eax, dword ptr [esi+0x20]
    test    eax, eax
    jns     clp1
    xor     eax, eax
clp1:
    mov     dword ptr [{_e(L_CL)}], eax
    mov     eax, dword ptr [esi+0x24]
    test    eax, eax
    jns     clp2
    xor     eax, eax
clp2:
    mov     dword ptr [{_e(L_CT)}], eax
    mov     eax, dword ptr [esi+0x28]
    cmp     eax, dword ptr [esi+0x80]
    jle     clp3
    mov     eax, dword ptr [esi+0x80]
clp3:
    mov     dword ptr [{_e(L_CR)}], eax
    mov     edx, dword ptr [esi+0x84]
    test    edx, edx
    jns     clp4h
    neg     edx
clp4h:
    mov     eax, dword ptr [esi+0x2c]
    cmp     eax, edx
    jle     clp4
    mov     eax, edx
clp4:
    mov     dword ptr [{_e(L_CB)}], eax
    mov     eax, dword ptr [{_e(L_K)}]
    cmp     eax, 1
    jl      fallback
    cmp     eax, {K_MAX}
    jg      fallback
    imul    eax, eax, 6
    mov     ecx, dword ptr [{_e(R)}]
    sub     ecx, dword ptr [{_e(L)}]
    cmp     ecx, eax
    jl      fallback
    mov     ecx, dword ptr [{_e(B)}]
    sub     ecx, dword ptr [{_e(T)}]
    cmp     ecx, eax
    jl      fallback
    cmp     dword ptr [esi+0x54], 0
    je      fallback
    cmp     dword ptr [esi+0x4a8], 0
    jle     fallback
    mov     ebx, dword ptr [ebp+0xc]
    test    ebx, ebx
    je      fallback
    mov     ebx, dword ptr [ebx]
    test    ebx, ebx
    je      fallback
    cmp     dword ptr [ebx+0x10], 3
    jl      fallback
    cmp     dword ptr [ebx+0x14], 3
    jl      fallback
    cmp     dword ptr [ebx+0x20], 0
    jne     fallback
    cmp     dword ptr [ebx+0x24], 0
    jne     fallback
    mov     ecx, dword ptr [ebx+0xc]
    cmp     ecx, 3
    jl      fallback
    mov     edi, dword ptr [ebx+4]
    test    edi, edi
    je      fallback
    mov     al, byte ptr [ebx+8]
    cmp     dword ptr [{_e(L_CLS)}], 0
    jne     g_bevel
    cmp     al, byte ptr [edi]
    jne     fallback
    movzx   edx, byte ptr [edi+1]
    cmp     dl, al
    je      fallback
    cmp     dl, byte ptr [edi+ecx]
    jne     fallback
    cmp     dl, byte ptr [edi+ecx+1]
    je      fallback
    mov     dword ptr [{_e(L_S)}], edx
{corners(0)}
    push    dword ptr [ebp+0xc]
    push    dword ptr [ebp+8]
    mov     ecx, esi
    call    {BUFFER_BOX_SPRITE:#x}
{chamfer}
{corners(1)}
{_stripe_tail()}

g_bevel:
    cmp     al, byte ptr [edi]
    jne     fallback
    cmp     al, byte ptr [edi+1]
    jne     fallback
    cmp     al, byte ptr [edi+ecx]
    jne     fallback
    movzx   edx, byte ptr [edi+2]
    cmp     dl, al
    je      fallback
    cmp     dl, byte ptr [edi+ecx+1]
    jne     fallback
    cmp     dl, byte ptr [edi+ecx*2]
    jne     fallback
    mov     dword ptr [{_e(L_S)}], edx
{bevel}
    jmp     done

fallback:
    push    dword ptr [ebp+0xc]
    push    dword ptr [ebp+8]
    mov     ecx, esi
    cmp     dword ptr [{_e(L_CLS)}], 0
    jne     fb_plain
    call    {T_NW_BOX:#x}
    jmp     done
fb_plain:
    call    {BUFFER_BOX_SPRITE:#x}
    jmp     done

nwf_fill:
    cmp     eax, dword ptr [{_e(L_CL)}]
    jge     f1
    mov     eax, dword ptr [{_e(L_CL)}]
f1:
    cmp     ebx, dword ptr [{_e(L_CT)}]
    jge     f2
    mov     ebx, dword ptr [{_e(L_CT)}]
f2:
    cmp     ecx, dword ptr [{_e(L_CR)}]
    jle     f3
    mov     ecx, dword ptr [{_e(L_CR)}]
f3:
    cmp     edx, dword ptr [{_e(L_CB)}]
    jle     f4
    mov     edx, dword ptr [{_e(L_CB)}]
f4:
    sub     ecx, eax
    jle     f_out
f_row:
    cmp     ebx, edx
    jge     f_out
    push    ecx
    push    eax
    mov     edi, ebx
    imul    edi, dword ptr [esi+0x4a8]
    add     edi, dword ptr [esi+0x54]
    add     edi, eax
    mov     eax, dword ptr [{_e(L_S)}]
    cld
    rep stosb
    pop     eax
    pop     ecx
    inc     ebx
    jmp     f_row
f_out:
    ret

nwf_corner:
    mov     dword ptr [{_e(L_ROW)}], 0
cnr_row:
    mov     ecx, dword ptr [{_e(L_ROW)}]
    cmp     ecx, dword ptr [{_e(L_K)}]
    jge     cnr_out
    push    eax
    push    ebx
    add     ebx, ecx
    xor     ecx, ecx
cnr_col:
    cmp     ecx, dword ptr [{_e(L_K)}]
    jge     cnr_next
    push    eax
    add     eax, ecx
    cmp     eax, dword ptr [{_e(L_CL)}]
    jl      cnr_skip
    cmp     eax, dword ptr [{_e(L_CR)}]
    jge     cnr_skip
    cmp     ebx, dword ptr [{_e(L_CT)}]
    jl      cnr_skip
    cmp     ebx, dword ptr [{_e(L_CB)}]
    jge     cnr_skip
    push    edx
    mov     edx, ebx
    imul    edx, dword ptr [esi+0x4a8]
    add     edx, dword ptr [esi+0x54]
    add     eax, edx
    pop     edx
    test    edx, edx
    jne     cnr_put
    push    edx
    mov     dl, byte ptr [eax]
    mov     byte ptr [edi], dl
    pop     edx
    jmp     cnr_skip
cnr_put:
    push    edx
    mov     dl, byte ptr [edi]
    mov     byte ptr [eax], dl
    pop     edx
cnr_skip:
    pop     eax
    inc     edi
    inc     ecx
    jmp     cnr_col
cnr_next:
    pop     ebx
    pop     eax
    inc     dword ptr [{_e(L_ROW)}]
    jmp     cnr_row
cnr_out:
    ret
"""


# ---- test oracle (never baked) ----

def oracle_bm() -> str:
    """The band-map thickener for an outline: R-1 / B-1 copy into thunk_box_thick_hollow_flat."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      hi
    push    {BUFFER_BOX_SPRITE:#x}
    ret
hi:
{_rect_copy()}
    push    {HOLLOWFLAT:#x}
    ret
"""


def oracle_box() -> str:
    """The band-map thickener for a filled panel: R-1 / B-1 copy into thunk_box_thick_devfill, then the panel
    stripe tail over [L+K, R-K) x [T+K, B-K)."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      hi
    push    {BUFFER_BOX_SPRITE:#x}
    ret
hi:
    push    ebp
    mov     ebp, esp
    sub     esp, {FRAME:#x}
    push    ebx
    push    esi
    push    edi
    mov     esi, ecx
    mov     eax, dword ptr [ebp+8]
    mov     edx, dword ptr [eax]
    mov     dword ptr [{RECT:#x}], edx
    mov     edx, dword ptr [eax+4]
    mov     dword ptr [{RECT + 4:#x}], edx
    mov     edx, dword ptr [eax+8]
    dec     edx
    mov     dword ptr [{RECT + 8:#x}], edx
    mov     edx, dword ptr [eax+0xc]
    dec     edx
    mov     dword ptr [{RECT + 0xC:#x}], edx
    push    dword ptr [ebp+0xc]
    push    {RECT:#x}
    mov     ecx, esi
    call    {DEVFILL:#x}
    mov     eax, dword ptr [{G:#x}]
    lea     eax, [eax*2+0xf]
    sar     eax, 5
    mov     dword ptr [{_e(L_K)}], eax
{_stripe_tail()}
"""


def asm_ts() -> str:
    """t_nwf_ts (the chat log's TextScroll_attach site 0x482A00; thiscall ecx = the TextScroll, [esp+4] x, +8 y, +0xC w,
    +0x10 h): the engine passes the (scaled) chat panel rect inset by a NATIVE 3 -> g > 16: x, y += d, w, h -= 2d,
    d = scale_px(3, g) - 3 (law nw_chat_log_inset; the tech window's t_ntw_ts3 precedent).  Every register kept."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    mov     eax, dword ptr [{G:#x}]
    imul    eax, eax, 6
    add     eax, 0xf
    sar     eax, 5
    sub     eax, 3
    add     dword ptr [esp+8], eax
    add     dword ptr [esp+0xc], eax
    shl     eax, 1
    sub     dword ptr [esp+0x10], eax
    sub     dword ptr [esp+0x14], eax
    pop     eax
go:
    push    {TEXTSCROLL_ATTACH:#x}
    ret
"""


SOURCES = {"t_nwf_bm": lambda: asm_entry(1), "t_nwf_box": lambda: asm_entry(0), "t_nwf_ins3": asm_ins3,
           "t_nwf_title": asm_title, "t_nwf_lock": asm_lock, "t_nwf_core": asm_core, "t_nwf_ts": asm_ts}
ORACLE = {"t_nwf_bm": oracle_bm, "t_nwf_box": oracle_box}


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b), "disassembly does not cover"
    return b


def to_template(b: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):   # the patcher takes {rel32:} after E8 only
            tgt = (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in REL:
                out += [f"{b[i]:02X}", REL[tgt]]
                i += 5
                continue
        if i + 4 <= len(b) and int.from_bytes(b[i:i + 4], "little") in ABS:
            out.append(ABS[int.from_bytes(b[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


def build() -> dict[str, bytes]:
    out = {}
    order = sorted(SOURCES, key=lambda n: SLOTS[n])
    for k, name in enumerate(order):
        b = assemble(SOURCES[name](), PCAVE2 + SLOTS[name])
        limit = SLOTS[order[k + 1]] if k + 1 < len(order) else SLOTS["g_nwf_rect"]
        assert SLOTS[name] + len(b) <= limit, f"{name} {len(b)}B overflows its slot"
        out[name] = b
    assert REGION[0] <= min(SLOTS.values()) and SLOTS["g_nwf_rect"] + 16 <= REGION[1]
    return out


def build_oracle() -> dict[str, bytes]:
    """The oracle thunks at ORACLE_SLOTS (the tests overwrite the baked entries' bytes with these)."""
    out = {name: assemble(fn(), PCAVE2 + ORACLE_SLOTS[name]) for name, fn in ORACLE.items()}
    assert ORACLE_SLOTS["t_nwf_bm"] + len(out["t_nwf_bm"]) <= ORACLE_SLOTS["t_nwf_box"]
    assert ORACLE_SLOTS["t_nwf_box"] + len(out["t_nwf_box"]) <= SLOTS["t_nwf_ts"]   # the oracle lobby run calls t_nwf_ts
    return out


GROUP = "netwin_frame_strokes"
SYM_NOTES = {
    "t_nwf_bm": "call-target at the four d5a0 section-outline sites: g<=16 vanilla, else eax=1 -> t_nwf_core",
    "t_nwf_box": "call-target at the 17 filled lobby panel sites (was t_nw_box): g<=16 vanilla, else eax=0 -> t_nwf_core",
    "t_nwf_ins3": "CALL at 0x481B33 (mov eax,3): eax = 3, or scale_px(3,g) at g>16 (title band inset)",
    "t_nwf_title": "call-target at the title outline 0x481B28: caller's rect copy B := T-fl(3g/16)+fl(29g/16), eax=1 -> t_nwf_core",
    "t_nwf_lock": "call-target at the roster lock icon 0x480599: x += K-1 (L+1 -> L+K), then thunk_nw_toggle",
    "t_nwf_core": "the lobby frame painter (law nw_frame_bands / nw_frame_interior): engine box + K-wide stroke band + K x K corners + panel stripe tail; guard fallback t_nw_box / the engine box",
    "t_nwf_ts": "call-target at the chat log TextScroll_attach 0x482A00: the native 3 inset -> scale_px(3,g) (law nw_chat_log_inset)",
}
NEW_SITES = (   # (id, function, va, original, target, pattern, note)
    ("NetWin_draw.outline_d5a0_title", "NetWin_draw", TITLE_OUTLINE_SITE, "E8 A6 12 16 00", "t_nwf_title",
     "call_target_redirect", "call Buffer_box_sprite (title outline, rect = the local +0xA14 copy)"),
    ("NetWin_draw.title_band_inset", "NetWin_draw", TITLE_INSET_SITE, "B8 03 00 00 00", "t_nwf_ins3",
     "literal_to_thunk_call", "MOV EAX, 3 (the title band's inset from its outline)"),
    ("NetWin_draw_options.outline_d5a0", "NetWin_draw_options", 0x0047F992, "E8 3C 34 16 00", "t_nwf_bm",
     "call_target_redirect", "call Buffer_box_sprite (CUSTOM GAME OPTIONS outline)"),
    ("NetWin_draw.outline_d5a0_chat", "NetWin_draw", 0x00481BFC, "E8 D2 11 16 00", "t_nwf_bm",
     "call_target_redirect", "call Buffer_box_sprite (chat outline)"),
    ("NetWin_draw_players.outline_d5a0", "NetWin_draw_players", 0x004803BA, "E8 14 2A 16 00", "t_nwf_bm",
     "call_target_redirect", "call Buffer_box_sprite (PLAYERS outline)"),
    ("NetWin_draw_settings.outline_d5a0", "NetWin_draw_settings", 0x00480993, "E8 3B 24 16 00", "t_nwf_bm",
     "call_target_redirect", "call Buffer_box_sprite (settings outline)"),
    ("NetWin_setup_lobby.chat_log_attach", "NetWin_setup_lobby", CHAT_LOG_SITE, "E8 CB 68 1A 00", "t_nwf_ts",
     "call_target_redirect", "call TextScroll_attach (chat log, the panel rect inset by a native 3)"),
)
assert {s[2] for s in NEW_SITES} == {va for _, va in OUTLINE_SITES} | {TITLE_OUTLINE_SITE, TITLE_INSET_SITE, CHAT_LOG_SITE}

M_SYM = (f"  # ==== {GROUP} symbols (2026-11-07, src assemble_nw_frames.py) ====\n", f"  # ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} (assemble_nw_frames.py), 2026-11-07 ====\n", f"      # ==== {GROUP} END ==== cave\n")
M_GRP = (f"  # ==== {GROUP} group ====\n", f"  # ==== {GROUP} END ==== group\n")
M_SITE = (f"  # ==== {GROUP} sites (2026-11-07; src assemble_nw_frames.py) ====\n", f"  # ==== {GROUP} END ==== sites\n")
GROUP_TEXT = f"""  - id: {GROUP}
    description: >
      The MULTIPLAYER SETUP lobby's frames are Buffer_box_sprite boxes at the scaled rect table whose 1-px strokes stayed
      1 px at every g.  Every lobby frame now draws on the band-map thickener's law (stroke_width(g) on every edge, the
      keyed 1-px chamfer and the d5a0 bevel step K x K) and every filled panel's interior inside that band is on the
      panel stripe law (panel_fill_pixel, so the 5-px 1-row ring the native edge sprites left inside every panel at
      g >= 22 is gone).  t_nwf_core paints those pixels directly (the engine box at its own rect, the K band, the
      saved corners, the stripe tail): the band-map thunks are ~10x the whole repaint at 4K and stay as the test
      oracle, which the baked pixels equal at every g 17..40.  Also: the title band's inset from its outline scales
      (native 3 -> scale_px(3, g)), the title outline's bottom is the client top + fl(29g/16) (thunk_nw_rectscale's
      double floor left it up to 1.44 px short), and the roster lock icon sits at cell L + K (vanilla L + 1, beside
      the 1-px stroke), and the chat log's text area keeps its scaled gap from the thicker stroke (its native 3-px
      inset -> scale_px(3, g)).  Retargeted call sites kept in their own groups: the 17 netwin_panel_stripes sites ->
      t_nwf_box (t_nw_box stays as t_nwf_core's guard fallback), NetWin_draw_players.toggle -> t_nwf_lock.  g <= 16:
      every site makes the vanilla call.  Laws scaling_laws.nw_frame_bands / nw_frame_interior / nw_title_band_inset /
      nw_title_rect_bottom / nw_lock_icon_x / nw_chat_log_inset; src assemble_nw_frames.py; guard tests/test_scaling_nw_frames.py.
    code_caves:
      - pcave2
    members: []
"""


def _block(markers, body: str) -> str:
    return markers[0] + body + markers[1]


def _replace_or_insert(text: str, markers, body: str, anchor_after: str) -> str:
    """Replace the marker block when present (idempotent), else insert it right after the line `anchor_after`."""
    blk = _block(markers, body)
    if markers[0] in text:
        a = text.index(markers[0])
        b = text.index(markers[1], a) + len(markers[1])
        return text[:a] + blk + text[b:]
    assert text.count(anchor_after) == 1, ("splice anchor must be unique", anchor_after[:60])
    i = text.index(anchor_after)
    j = text.index("\n", i + len(anchor_after) - 1) + 1          # the end of the anchor's LAST line
    return text[:j] + blk + text[j:]


def splice(path) -> None:
    """Splice this group into patches.yaml byte-safely (text edits only: the file is UTF-8 and never round-tripped)."""
    import pathlib
    p = pathlib.Path(path)
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    built = build()
    sym = "".join(f"  {n + ':':<31}{{ cave: pcave2, offset: {SLOTS[n]:#x} }}   # {GROUP} ({len(built[n])}B) {SYM_NOTES[n]}\n"
                  for n in sorted(built, key=lambda n: SLOTS[n]))
    sym += (f"  {'g_nwf_rect:':<31}{{ cave: pcave2, offset: {SLOTS['g_nwf_rect']:#x}, size: 16 }}   # {GROUP}: "
            f"the band-map test oracle's R-1 / B-1 RECT copy (unused by the baked thunks); 0 at rest\n")
    cave = "".join(f"      - id: {n}\n        offset: {SLOTS[n]:#x}\n        bytes: \"{to_template(built[n], PCAVE2 + SLOTS[n])}\"\n"
                   for n in sorted(built, key=lambda n: SLOTS[n]))
    cave += f"      - id: g_nwf_rect\n        offset: {SLOTS['g_nwf_rect']:#x}\n        bytes: \"{' '.join(['00'] * 16)}\"\n"
    sites = "".join(
        f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {fn}\n    virtual_addr: 0x{va:08X}\n"
        f"    length: 5\n    original_bytes: \"{orig}\"{' ' * max(1, 23 - len(orig))}# {note}\n"
        f"    new_bytes:      \"E8 {{rel32:{tgt}}}\"\n    pattern: {pat}\n"
        for sid, fn, va, orig, tgt, pat, note in NEW_SITES)
    text = _replace_or_insert(text, M_SYM, sym, "\n  t_nw_box:")
    i = text.index("      - id: t_nw_box\n        offset: 0x33700\n        bytes: ")      # t_nw_box's content entry
    text = _replace_or_insert(text, M_CAVE, cave, text[i:text.index("\n", text.index("        bytes: ", i))])
    text = _replace_or_insert(text, M_GRP, GROUP_TEXT, "  # ==== netwin_panel_stripes END ==== group")
    i = text.index("  - id: NetWin_draw.panel_d528_chat_log\n")
    anchor = text[i:text.index("    pattern: call_target_redirect\n", i)] + "    pattern: call_target_redirect"
    text = _replace_or_insert(text, M_SITE, sites, anchor)
    # retarget the 17 filled panel sites and the lock icon site (they keep their groups)
    for va in FILLED_SITES:
        key = f"    virtual_addr: 0x{va:08X}\n"
        i = text.index(key)
        j = text.index("    new_bytes:", i)
        k = text.index("\n", j)
        line = text[j:k]
        assert "t_nw_box" in line or "t_nwf_box" in line, (hex(va), line)
        text = text[:j] + line.replace("{rel32:t_nw_box}", "{rel32:t_nwf_box}") + text[k:]
    key = f"    virtual_addr: 0x{LOCK_ICON_SITE:08X}\n"
    i = text.index(key)
    j = text.index("    new_bytes:", i)
    k = text.index("\n", j)
    line = text[j:k]
    assert "thunk_nw_toggle" in line or "t_nwf_lock" in line, line
    text = text[:j] + line.replace("{rel32:thunk_nw_toggle}", "{rel32:t_nwf_lock}") + text[k:]
    p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def main() -> int:
    if "--splice" in sys.argv:
        import pathlib
        splice(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
        print("spliced")
        return 0
    for name, b in build().items():
        off = SLOTS[name]
        print(f"  {name}: {{ cave: pcave2, offset: {off:#x} }}   # {len(b)}B")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{to_template(b, PCAVE2 + off)}\"")
    print(f"      - id: g_nwf_rect\n        offset: {SLOTS['g_nwf_rect']:#x}\n        bytes: \"{' '.join(['00'] * 16)}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
