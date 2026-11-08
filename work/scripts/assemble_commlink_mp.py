"""Assembler for the COMMLINK panel's multiplayer click spots (group commlink_mp_spots, 2026-11-07).

The COMMLINK panel (MultiWin 0x7FD648; commlink_redraw 0x479330) draws in device space through commlink_menu_scale
(x = hm_sc(x), y = hm_rowY(y): scaling_laws.commlink_sc / commlink_row_y), and its faction rows' Spot_add rects
follow (thunk_comm_rowrect).  Three multiplayer-only Spot_add sites and one clip still used NATIVE rects:

  0x478C0C  commlink_draw_mp_header 0x478BE0: the time widget's spot (idx 0, type 2: a click opens the time controls
            dialog Console_time_controls 0x515900).  Rect = the header strip {0, y, W, y + [+0x112C]} -- x / width already
            device (W = +0x4C4), y native.  Its text is centred in the same rect by Buffer_write_cent_l_7, whose
            thunk_comm_cent7 maps T / B through hm_rowY in place AFTER this registration.
  0x47946F  commlink_redraw: Buffer_set_clip(the strip under the widget) before its text -- native, so at g > 16 the
            text (placed by thunk_comm_cent7 at the mapped rect) fell outside the clip and was never drawn.
  0x47947E  commlink_redraw: the strip's spot (idx 3, type 2) through commlink_spot_rect 0x47A6F0 (thiscall ecx =
            spot list; idx, type, RECT*; RET 0xC); the same RECT then feeds commlink_write_cent 0x47A720's cent_l_7
            text, which maps it again -> the thunk maps a COPY, never the caller's rect (the clip thunk too).
  0x4786DE  commlink_draw_faction_row: each faction's mute LED (idx = faction, type 0), x = L + 7 / w = h = the row
            height, all native (thunk_comm_rowrect scales the row rect only after it, at 0x4786F7); the LED sprite
            itself is drawn by Sprite_draw_2 through thunk_hudmenu_sd2 at (hm_sc(x), hm_rowY(y)).

At 4K the time widget is drawn at y 450..520 while its spot stayed at 180..208, under the faction rows (Spot_check: the
last added wins, and the rows are added after it): the widget could not be clicked; a click on a mute LED hit another
row's LED (at g 22 / 25 the next faction's: the wrong player muted) or nothing.  Law scaling_laws.commlink_spot: the
spot covers what is drawn -- top through commlink_row_y, bottom through commlink_bottom (commlink_row_y, except the
panel's own bottom, which the box scaled linearly: sc(b) == the canvas height -> the canvas height), x / right through
commlink_sc where the site's x is native (the LED only).  g <= 16: every site makes its vanilla call, vanilla args.

Bottom pin (user decision 2026-11-07): the panel box is sc(222) tall (thunk_comm_gwinit) while its rows run on
hm_rowY, which ends up to 5 rows short of the box (g 19) or 6 past it (g 20 / 28 / 36); in the collapsed multiplayer
layout ([0x93F660] != 0, MultiWin +0xA24 = 0) the content -- title strip at 7 rows + 2 footers, time widget, the strip
under it, ending exactly at the native height 7 row_h + 2 footer_h + title_h + header_h + 0xE -- is one block above
transparent rows, and the strip was cut off / its text centred off.  hm_rowY's first 6 bytes are `push t_clmp_rowy;
ret`: t_clmp_rowy = commlink_panel_y = hm_rowY + (the canvas height - hm_rowY(native height)) in that layout, plain
hm_rowY otherwise -- every COMMLINK caller (strip blits, the header / strip text, these spots) inherits it.

Thunks (pcave2 0x40A00..0x40DD4, the MP region 0x40000..0x40FFF; pcave2 grown 0x40000 -> 0x41000):
  t_clmp_hdr    0x478C0C's call-target (thiscall ecx = spot list; idx, type, x, y, w, h; = Spot_add's): g > 16 -> y
                through commlink_row_y, h = commlink_bottom(y + h) - y'; then Spot_add.  ecx / ebx / esi / edi / ebp kept.
  t_clmp_led    0x4786DE's call-target, same contract: also x, w through commlink_sc.
  t_clmp_strip  0x47947E's call-target (idx, type, RECT*): g > 16 -> the RECT copied to g_clmp_rect, T through
                commlink_row_y, B through commlink_bottom, [esp+0xC] repointed; then 0x47A6F0.  Every register kept.
  t_clmp_clip   0x47946F's call-target (thiscall ecx = Buffer; RECT*; = Buffer_set_clip's, RET 4): the same mapped copy
                in g_clmp_clip; then Buffer_set_clip.  Every register kept.
  t_clmp_bot    helper: eax = commlink_bottom(eax) (the panel height = |Buffer h| of 0x7FDA8C, +0x84); clobbers edx.
  t_clmp_rowy   hm_rowY's entry: eax = commlink_panel_y(eax) (the displaced 6 bytes, re-entering hm_rowY +6 / +0x54;
                the native height from MultiWin +0x1158 / +0x11B4 / +0x1100 / +0x112C, the canvas from +0x444+0x84);
                clobbers edx, as hm_rowY.
  g_clmp_rect / g_clmp_clip   16-byte RECT cells.

Guard: tests/test_commlink_mp_spots.py (the laws vs the baked hm_sc / hm_rowY; the real image's panel in multiplayer,
collapsed and expanded: every type-0 / type-2 spot covers its drawn rows, the panel's bottom row included, clicks
return the right spot, the strip text's clip covers its rect; identity at 16).

Usage: assemble_commlink_mp.py [--splice]
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: F401,E402

PCAVE2 = 0x00A0C000
SLOTS = {"t_clmp_hdr": 0x40A00, "t_clmp_led": 0x40A60, "t_clmp_strip": 0x40AC0, "t_clmp_clip": 0x40B20,
         "t_clmp_bot": 0x40B80, "g_clmp_rect": 0x40BE0, "g_clmp_clip": 0x40BF0, "t_clmp_rowy": 0x40D60,
         "t_clmp_synth": 0x40C70, "t_clmp_synh": 0x40CB0, "g_clmp_son": 0x40D40, "t_clmp_trow": 0x40C00}
CELLS = ("g_clmp_rect", "g_clmp_clip")
FLAGS = ("g_clmp_son",)            # 4-byte cells
REGION_END = 0x40E00              # the MP region 0x40000..0x40FFF: 0x40A00..0x40DFF (netwin_frame_strokes 0x40000..0x409FF)
G = 0x00668740
HM_SC = PCAVE2 + 0x5D60            # hm_sc: eax = (eax g + 8) >> 4 (eax only)
HM_ROWY = PCAVE2 + 0x5D70          # hm_rowY: eax = the uniform-row-pitch map (clobbers edx; ebx / ecx preserved)
SPOT_ADD = 0x005FA960              # Spot_add(thiscall spot list; idx, type, x, y, w, h) RET 0x18
SPOT_RECT = 0x0047A6F0             # commlink_spot_rect (idx, type, RECT*) RET 0xC
SET_CLIP = 0x005D8000              # Buffer_set_clip(thiscall Buffer; RECT*) RET 4
MW = 0x007FD648                    # MultiWin, the COMMLINK panel
PANEL_H = MW + 0x444 + 0x84        # the panel Buffer's h (negative: top-down)
MP_ACTIVE = 0x0093F660             # MultiplayerActive
H_CELL = PCAVE2 + 0x41A60          # g_clmp_h (assemble_commlink_hdr.py): the core's H for the header post-pass
T_POST = PCAVE2 + 0x41000          # t_clmp_post (assemble_commlink_hdr.py): t_clmp_synth's tail
T_PRE = PCAVE2 + 0x41AC0           # t_clmp_pre (assemble_commlink_hdr.py): the railed-strip column mode
TITLE_SPR = 0x007FE72C             # MultiWin +0x10E4: the panel's 138 x 6 title strip (scaling_laws.COMMLINK_TITLE_SPRITE)
HM_ROWY_BODY = HM_ROWY + 6         # hm_rowY after its (displaced) `cmp eax, 6 / jl small / push ebx`: push ecx ... pop ebx; ret
HM_ROWY_SMALL = HM_ROWY + 0x54     # hm_rowY's y < 6 path: eax = hm_sc(eax); ret
HM_SYNTH = PCAVE2 + 0x65D0         # hm_synth_core(dst, dx, dy, num, den, spr) RET 0x18
SON = PCAVE2 + 0x40D40             # g_clmp_son: 1 only around thunk_hudmenu_sbc's call of hm_synth_core (t_clmp_synth)
RECT = PCAVE2 + SLOTS["g_clmp_rect"]
CLIP = PCAVE2 + SLOTS["g_clmp_clip"]
BOT = PCAVE2 + SLOTS["t_clmp_bot"]
SITES = (   # (id, function, va, original, target, note)
    ("commlink_draw_mp_header.time_spot", "commlink_draw_mp_header", 0x00478C0C, "E8 4F 1D 18 00", "t_clmp_hdr",
     "call Spot_add (the time widget, type 2)"),
    ("commlink_redraw.mp_strip_clip", "commlink_redraw", 0x0047946F, "E8 8C EB 15 00", "t_clmp_clip",
     "call Buffer_set_clip (the strip under the time widget, before its text)"),
    ("commlink_redraw.mp_strip_spot", "commlink_redraw", 0x0047947E, "E8 6D 12 00 00", "t_clmp_strip",
     "call 0x47A6F0 (the strip under the time widget, type 2)"),
    ("commlink_draw_faction_row.mute_led_spot", "commlink_draw_faction_row", 0x004786DE, "E8 7D 22 18 00", "t_clmp_led",
     "call Spot_add (a faction row's mute LED, type 0)"),
)
ABS = {G: "{abs32:g_popup_scale_num}", RECT: "{abs32:g_clmp_rect}", CLIP: "{abs32:g_clmp_clip}",
       SON: "{abs32:g_clmp_son}", H_CELL: "{abs32:g_clmp_h}", T_POST: "{abs32:t_clmp_post}"}
REL = {HM_SC: "{rel32:hm_sc}", HM_ROWY: "{rel32:hm_rowY}", BOT: "{rel32:t_clmp_bot}", HM_SYNTH: "{rel32:hm_synth_core}",
       T_PRE: "{rel32:t_clmp_pre}"}


def asm_rowy() -> str:
    """hm_rowY's new entry (its first 6 bytes are `push t_clmp_rowy; ret`): eax = commlink_panel_y(eax) -- the
    displaced hm_rowY, plus commlink_pin_shift in the collapsed multiplayer layout -- only while the canvas IS the
    multiplayer box (|h| == hm_sc(native h); a box built for single player, or the 0-tall canvas of the build's own
    repaints, is not pinned: audit 2026-11-07).  Clobbers edx (as hm_rowY); every other register kept.
    The re-entry points hm_rowY +6 / +0x54 are literals (HM_ROWY_BODY / HM_ROWY_SMALL; guarded by
    test_commlink_mp_spots.test_rowy_reentry_literals)."""
    return f"""
    call    raw
    cmp     dword ptr [{MP_ACTIVE:#x}], 0
    je      out
    cmp     dword ptr [{MW + 0xA24:#x}], 0
    jne     out
    push    ecx
    mov     ecx, eax
    mov     eax, dword ptr [{MW + 0x1158:#x}]
    imul    eax, eax, 7
    mov     edx, dword ptr [{MW + 0x11B4:#x}]
    lea     eax, [eax + edx*2]
    add     eax, dword ptr [{MW + 0x1100:#x}]
    add     eax, dword ptr [{MW + 0x112C:#x}]
    add     eax, 0xe
    push    eax
    call    {HM_SC:#x}
    mov     edx, dword ptr [{PANEL_H:#x}]
    test    edx, edx
    jns     pos
    neg     edx
pos:
    cmp     eax, edx
    pop     eax
    jne     nopin
    push    edx
    call    raw
    pop     edx
    sub     edx, eax
    lea     eax, [ecx + edx]
    pop     ecx
    ret
nopin:
    mov     eax, ecx
    pop     ecx
out:
    ret
raw:
    cmp     eax, 6
    jl      small
    push    ebx
    push    {HM_ROWY_BODY:#x}
    ret
small:
    push    {HM_ROWY_SMALL:#x}
    ret
"""


def asm_synth() -> str:
    """thunk_hudmenu_sbc's post-blit call (was `call hm_synth_core`): the same 6 args, RET 0x18, under g_clmp_son;
    g_clmp_h := -1 before the core (t_clmp_synh sets it when the core gets that far), then the tail t_clmp_post
    (son := 0, the header strip's post-pass, RET 0x18)."""
    return f"""
    mov     dword ptr [{SON:#x}], 1
    mov     dword ptr [{H_CELL:#x}], -1
    call    {T_PRE:#x}
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    call    {HM_SYNTH:#x}
    push    {T_POST:#x}
    ret
"""


def asm_synh() -> str:
    """hm_synth_core's dest-height block (20 bytes -> `call t_clmp_synh` + 15 nops; runs in its frame: [ebp-0x14] sh,
    [ebp+0x14] num, ecx den, [ebp+0xC] dx, [ebp+0x10] dy; writes [ebp-0x30] H): H = (sh num + den/2) / den as before
    -- and under g_clmp_son, in multiplayer, for a strip at dx 0: H = max(H, hm_rowY(y + sh) - dy), y the native row
    with hm_rowY(y) == dy (scaling_laws.commlink_strip_rows).  ecx / ebx / esi / edi kept."""
    return f"""
    mov     eax, dword ptr [ebp-0x14]
    imul    eax, dword ptr [ebp+0x14]
    mov     edx, ecx
    sar     edx, 1
    add     eax, edx
    xor     edx, edx
    div     ecx
    mov     dword ptr [ebp-0x30], eax
    cmp     dword ptr [{SON:#x}], 0
    je      out
    cmp     dword ptr [{MP_ACTIVE:#x}], 0
    je      out
    cmp     dword ptr [ebp+0xc], 0
    jne     out
    push    ebx
    push    ecx
    push    esi
    xor     ebx, ebx
inv:
    mov     eax, ebx
    call    {HM_ROWY:#x}
    cmp     eax, dword ptr [ebp+0x10]
    je      found
    jg      done
    inc     ebx
    cmp     ebx, 0x200
    jl      inv
    jmp     done
found:
    mov     esi, eax
    mov     eax, ebx
    add     eax, dword ptr [ebp-0x14]
    call    {HM_ROWY:#x}
    sub     eax, esi
    cmp     eax, dword ptr [ebp-0x30]
    jle     done
    mov     dword ptr [ebp-0x30], eax
done:
    pop     esi
    pop     ecx
    pop     ebx
out:
    mov     eax, dword ptr [ebp-0x30]
    mov     dword ptr [{H_CELL:#x}], eax
    ret
"""


def asm_trow() -> str:
    """hm_synth_core's source-row block (12 bytes at sy_row -> `call t_clmp_trow` + 7 nops; runs in its frame:
    [ebp-0x64] the DDA row, [ebp-0x14] sh, [ebp-0x30] H, [ebp-0x74] the dest row y, [ebp+0x10] dy, [ebp+0x1C] the
    sprite, [ebp-0x5C] P, [ebp-0x60] P >> 1): eax = the DDA row clamped to sh - 1 as before -- and under g_clmp_son,
    for the title strip (sprite TITLE_SPR, sh 6), scaling_laws.commlink_title_src_row: j = y - dy; K = half_down(g,
    16) = (2 g + 15) >> 5; when H > 4 K: j < 4 K -> j / K, else row 4 on y mod P < P >> 1, row 5 elsewhere.  Every
    register but eax kept (the core reloads ebx / ecx / edx / esi / edi after it)."""
    return f"""
    mov     eax, dword ptr [ebp-0x64]
    cmp     eax, dword ptr [ebp-0x14]
    jl      r_ok
    mov     eax, dword ptr [ebp-0x14]
    dec     eax
r_ok:
    cmp     dword ptr [{SON:#x}], 0
    je      out
    cmp     dword ptr [ebp+0x1c], {TITLE_SPR:#x}
    jne     out
    cmp     dword ptr [ebp-0x14], 6
    jne     out
    push    ecx
    push    edx
    mov     ecx, dword ptr [{G:#x}]
    lea     ecx, [ecx*2+0xf]
    sar     ecx, 5
    lea     edx, [ecx*4]
    cmp     edx, dword ptr [ebp-0x30]
    jge     keep
    mov     eax, dword ptr [ebp-0x74]
    sub     eax, dword ptr [ebp+0x10]
    cmp     eax, edx
    jge     fill
    xor     edx, edx
    div     ecx
    jmp     keep
fill:
    mov     eax, dword ptr [ebp-0x74]
    xor     edx, edx
    div     dword ptr [ebp-0x5c]
    mov     eax, 4
    cmp     edx, dword ptr [ebp-0x60]
    jl      keep
    inc     eax
keep:
    pop     edx
    pop     ecx
out:
    ret
"""


def asm_bot() -> str:
    return f"""
    push    ecx
    mov     ecx, eax
    call    {HM_SC:#x}
    mov     edx, dword ptr [{PANEL_H:#x}]
    test    edx, edx
    jns     pos
    neg     edx
pos:
    cmp     eax, edx
    je      out
    mov     eax, ecx
    call    {HM_ROWY:#x}
out:
    pop     ecx
    ret
"""


def _y_h(y: str, h: str) -> str:
    """[y], [h] (stack operands, esi free) -> commlink_row_y(y), commlink_bottom(y + h) - commlink_row_y(y)"""
    return f"""
    mov     eax, dword ptr [{y}]
    mov     esi, eax
    add     esi, dword ptr [{h}]
    call    {HM_ROWY:#x}
    mov     dword ptr [{y}], eax
    xchg    eax, esi
    call    {BOT:#x}
    sub     eax, esi
    mov     dword ptr [{h}], eax"""


def _x_w(x: str, w: str) -> str:
    return f"""
    mov     eax, dword ptr [{x}]
    mov     esi, eax
    add     esi, dword ptr [{w}]
    call    {HM_SC:#x}
    mov     dword ptr [{x}], eax
    xchg    eax, esi
    call    {HM_SC:#x}
    sub     eax, esi
    mov     dword ptr [{w}], eax"""


def asm_spot(native_x: bool) -> str:
    # entry: [esp] ret, +4 idx, +8 type, +0xC x, +0x10 y, +0x14 w, +0x18 h; after the two pushes everything is +8
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    esi
    push    edx
{_y_h("esp+0x18", "esp+0x20")}
{_x_w("esp+0x14", "esp+0x1c") if native_x else ""}
    pop     edx
    pop     esi
go:
    push    {SPOT_ADD:#x}
    ret
"""


def _rect_map(cell: int, arg: str, tail: int) -> str:
    """[arg] RECT* -> cell (L, R as they are; T through commlink_row_y, B through commlink_bottom), [arg] := cell"""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    push    edx
    push    esi
    push    edi
    mov     esi, dword ptr [{arg}]
    mov     edi, {cell:#x}
    mov     eax, dword ptr [esi]
    mov     dword ptr [edi], eax
    mov     eax, dword ptr [esi+8]
    mov     dword ptr [edi+8], eax
    mov     eax, dword ptr [esi+4]
    call    {HM_ROWY:#x}
    mov     dword ptr [edi+4], eax
    mov     eax, dword ptr [esi+0xc]
    call    {BOT:#x}
    mov     dword ptr [edi+0xc], eax
    mov     dword ptr [{arg}], edi
    pop     edi
    pop     esi
    pop     edx
    pop     eax
go:
    push    {tail:#x}
    ret
"""


def asm_strip() -> str:
    # after the 4 pushes: [esp+0x10] ret, +0x14 idx, +0x18 type, +0x1C RECT*
    return _rect_map(RECT, "esp+0x1c", SPOT_RECT)


def asm_clip() -> str:
    # after the 4 pushes: [esp+0x10] ret, +0x14 RECT*
    return _rect_map(CLIP, "esp+0x14", SET_CLIP)


SOURCES = {"t_clmp_hdr": lambda: asm_spot(False), "t_clmp_led": lambda: asm_spot(True), "t_clmp_strip": asm_strip,
           "t_clmp_clip": asm_clip, "t_clmp_bot": asm_bot, "t_clmp_rowy": asm_rowy, "t_clmp_synth": asm_synth,
           "t_clmp_synh": asm_synh, "t_clmp_trow": asm_trow}


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b), "disassembly does not cover"
    return b


def to_template(b: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):
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
        nxt = [SLOTS[n] for n in list(SOURCES) + list(CELLS) + list(FLAGS) if SLOTS[n] > SLOTS[name]]
        limit = min(nxt) if nxt else REGION_END
        assert SLOTS[name] + len(b) <= limit, f"{name} {len(b)}B overflows its slot"
        out[name] = b
    assert SLOTS[CELLS[-1]] + 16 <= REGION_END and SLOTS[order[-1]] + len(out[order[-1]]) <= REGION_END
    assert all(SLOTS[f] + 4 <= REGION_END for f in FLAGS)
    return out


GROUP = "commlink_mp_spots"
NOTES = {
    "t_clmp_hdr": "call-target at 0x478C0C (the time widget's Spot_add, type 2): y -> hm_rowY, bottom -> t_clmp_bot",
    "t_clmp_led": "call-target at 0x4786DE (a faction row's mute-LED Spot_add, type 0): x,w -> hm_sc; y -> hm_rowY, bottom -> t_clmp_bot",
    "t_clmp_strip": "call-target at 0x47947E (commlink_spot_rect, type 2): a COPY of the rect, T -> hm_rowY, B -> t_clmp_bot",
    "t_clmp_clip": "call-target at 0x47946F (Buffer_set_clip before the strip text): the same mapped COPY",
    "t_clmp_bot": "helper: eax = commlink_bottom(eax): the panel's own bottom -> the canvas height, else hm_rowY (clobbers edx)",
    "t_clmp_rowy": "hm_rowY's entry (push/ret from its first 6 bytes): commlink_panel_y -- the collapsed MP layout pinned to the box bottom (clobbers edx)",
    "t_clmp_synth": "thunk_hudmenu_sbc's post-blit call (was hm_synth_core): the same args under g_clmp_son, g_clmp_h := -1, t_clmp_pre, tail t_clmp_post",
    "t_clmp_synh": "CALL helper = hm_synth_core's dest-height block: + the MP strip row-law span, grow only (commlink_strip_rows); H -> g_clmp_h",
    "t_clmp_trow": "CALL helper = hm_synth_core's source-row block: the COMMLINK title strip's even lines (commlink_title_src_row) under g_clmp_son",
}
M_SYM = (f"  # ==== {GROUP} symbols (2026-11-07, src assemble_commlink_mp.py) ====\n", f"  # ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} (assemble_commlink_mp.py), 2026-11-07 ====\n", f"      # ==== {GROUP} END ==== cave\n")
M_GRP = (f"  # ==== {GROUP} group ====\n", f"  # ==== {GROUP} END ==== group\n")
M_SITE = (f"  # ==== {GROUP} sites (2026-11-07; src assemble_commlink_mp.py) ====\n", f"  # ==== {GROUP} END ==== sites\n")
GROUP_TEXT = f"""  - id: {GROUP}
    description: >
      The COMMLINK panel's multiplayer-only click spots were registered at native coordinates while the panel draws in
      device space (commlink_menu_scale): the time widget (commlink_draw_mp_header, type 2 -- a click opens the time
      controls), the strip under it (type 2) and each faction row's mute LED (type 0); and the strip's text clip was
      native, so its text was clipped away at g > 16.  At 4K the widget is drawn at y 450..520 with its spot at
      180..208 under the faction rows, so it could not be clicked, and a mute-LED click hit another row's LED (the
      wrong player muted at g 22 / 25) or nothing.  Each spot and the clip now cover what is drawn (law
      scaling_laws.commlink_spot: top through commlink_row_y = hm_rowY, bottom through commlink_bottom -- the panel's
      own bottom to the canvas height --, x and right through commlink_sc = hm_sc where the site's x is native).
      g <= 16: the vanilla calls.  And the collapsed multiplayer layout (MultiWin +0xA24 = 0: title strip, time
      widget and the strip under it bottom-aligned in the box) is pinned to the box bottom (user decision
      2026-11-07): the box is sc(222) tall while its rows run on hm_rowY, which ended up to 5 rows short of it or 6
      past it (the strip cut off, its text off-centre); hm_rowY's entry (push t_clmp_rowy; ret) adds
      scaling_laws.commlink_pin_shift there, so every collapsed draw, text rect and spot moves as one block and the
      strip ends on the box bottom.  Single player and the expanded layout: hm_rowY unchanged.
      And in multiplayer the strips off the 18-row grid (the title, 6 rows, and the time widget, 28) were synthesized
      sc(h) tall from their row-law tops, 1 row short of the next strip at most g (a see-through hairline between
      title / widget / strip, both layouts): thunk_hudmenu_sbc's synth call goes through t_clmp_synth, and
      hm_synth_core's height block (call t_clmp_synh) grows a full-width strip to its row-law span
      (scaling_laws.commlink_strip_rows, at most 1 row; single player, the MENU strips and the LEDs unchanged).
      And the panel's 6-row title strip (MultiWin +0x10E4: a 3-row metal plate, a dark line, a 2-row black fill) came
      out of the core's NN as uneven lines -- 3,2,3,2 rows at 4K (user 2026-11-07, "the title strips come out uneven at
      2.5x"): hm_synth_core's source-row block (call t_clmp_trow) gives each of its four 1-row lines K =
      stroke_width(g) rows and the fill the remainder, regenerated on the stripe grid (scaling_laws.
      commlink_title_src_row / commlink_title_synth; every other strip and the MENU strips unchanged).
      And the 28-row multiplayer header strip (MultiWin +0x1110, the time widget's: a rounded box, two scanline pairs
      sharing c5) banded in three colours (the core's one-pair probe recoloured the outside rows, its NN beat the rest)
      and its 1-px border / corner / rail lines came out 2 / 3 px: t_clmp_synth's tail t_clmp_post redraws it by
      scaling_laws.commlink_header_synth (both axes on commlink_zone_map: lines K, fields proportional, the box
      interior the remainder; every texel through its scanicon pair, the even row on top) -- t_clhd_draw /
      t_clhd_zone / t_clhd_lut, pcave2 0x41000.. (src assemble_commlink_hdr.py).
      Src assemble_commlink_mp.py; guards tests/test_commlink_mp_spots.py, test_hm_synth_core_parity.py,
      test_commlink_hdr_asm_parity.py.
    code_caves:
      - pcave2
    members: []
"""


def _replace_or_insert(text: str, markers, body: str, anchor_after: str) -> str:
    blk = markers[0] + body + markers[1]
    if markers[0] in text:
        a = text.index(markers[0])
        b = text.index(markers[1], a) + len(markers[1])
        return text[:a] + blk + text[b:]
    assert text.count(anchor_after) == 1, ("splice anchor must be unique", anchor_after[:60])
    i = text.index(anchor_after)
    j = text.index("\n", i + len(anchor_after) - 1) + 1
    return text[:j] + blk + text[j:]


def splice(path) -> None:
    """Text-only splice into patches.yaml (CRLF kept), idempotent; anchored after the netwin_frame_strokes blocks."""
    import pathlib
    p = pathlib.Path(path)
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    built = build()
    sym = "".join(f"  {n + ':':<31}{{ cave: pcave2, offset: {SLOTS[n]:#x} }}   # {GROUP} ({len(built[n])}B) {NOTES[n]}\n"
                  for n in sorted(built, key=lambda n: SLOTS[n]))
    sym += "".join(f"  {c + ':':<31}{{ cave: pcave2, offset: {SLOTS[c]:#x}, size: 16 }}   # {GROUP}: a mapped RECT copy\n"
                   for c in CELLS)
    sym += "".join(f"  {c + ':':<31}{{ cave: pcave2, offset: {SLOTS[c]:#x}, size: 4 }}   # {GROUP}: 1 only around t_clmp_synth's call of hm_synth_core\n"
                   for c in FLAGS)
    cave = "".join(f"      - id: {n}\n        offset: {SLOTS[n]:#x}\n        bytes: \"{to_template(built[n], PCAVE2 + SLOTS[n])}\"\n"
                   for n in sorted(built, key=lambda n: SLOTS[n]))
    cave += "".join(f"      - id: {c}\n        offset: {SLOTS[c]:#x}\n        bytes: \"{' '.join(['00'] * 16)}\"\n" for c in CELLS)
    cave += "".join(f"      - id: {c}\n        offset: {SLOTS[c]:#x}\n        bytes: \"00 00 00 00\"\n" for c in FLAGS)
    sites ="".join(
        f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {fn}\n    virtual_addr: 0x{va:08X}\n"
        f"    length: 5\n    original_bytes: \"{orig}\"         # {note}\n"
        f"    new_bytes:      \"E8 {{rel32:{tgt}}}\"\n    pattern: call_target_redirect\n"
        for sid, fn, va, orig, tgt, note in SITES)
    text = _replace_or_insert(text, M_SYM, sym, "  # ==== netwin_frame_strokes END ==== symbols")
    text = _replace_or_insert(text, M_CAVE, cave, "      # ==== netwin_frame_strokes END ==== cave")
    text = _replace_or_insert(text, M_GRP, GROUP_TEXT, "  # ==== netwin_frame_strokes END ==== group")
    text = _replace_or_insert(text, M_SITE, sites, "  # ==== netwin_frame_strokes END ==== sites")
    p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def main() -> int:
    if "--splice" in sys.argv:
        import pathlib
        splice(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
        print("spliced")
        return 0
    for name, b in build().items():
        print(f"  {name}: {SLOTS[name]:#x} {len(b)}B\n    {to_template(b, PCAVE2 + SLOTS[name])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
