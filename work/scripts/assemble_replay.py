"""Assembler for the end-game REPLAY window (group replay_scale, 2026-11-15; static map work\\_replay_static_map.md).

show_replay 0x5ADBF0 builds a STACK-local ReplayWin at a literal 800 x 600 + Win_center over the live map and draws
it natively at every g: at 4K the title "Replay: <year>" (g_popup_title_font, already at g) clipped above its 24-row
band and the Close label overflowed a 20-px bar.  The popup family's scale (g), uniform; every law is in
scaling_laws.py, section END-GAME REPLAY (replay_window / replay_title_box / replay_text_rect / replay_map_rect /
replay_close_rect / replay_map_zoom / replay_clip_free_width).  The map is the engine's own zoom fit on the
s(800) x s(600) window (option A, the user's decision 2026-11-15); where that map would clip a row, the WINDOW grows
(4:3 kept, the user's decision 2026-11-15), never the zoom.

Thunks (pcave2 0x46000..0x47FFF, the region the build owner reserved for this group):
  t_rp_bracket   CALL at 0x5ADC93 (show_replay -> ReplayWin_build; the whole replay, its modal loop included, runs
                 inside this call): g > 16 -> g_rp_btn := ecx + 0x247A0 (the Close FlatButton), call
                 ReplayWin_build, g_rp_btn := 0, bare ret (return-transparent).  g <= 16 -> jmp ReplayWin_build.
  t_rp_maprect   CALL at 0x5AD838 (MapWin_init, rect = the locals {L+3, T+0x1A, R-3, B-0x1A} of the window):
                 inverted to the window edges, then replay_map_rect; jmp MapWin_init.  The MapWin child's
                 GraphicWin_init_2 (0x5AD859) and the Close block read the same locals.
  t_rp_close     CALL at 0x5AD8DD (BaseButton_init; [esp+0x10] y = map B + 3, [esp+0x18] h = 0x14): y += s26 - s23 - 3,
                 h := s23 - s3 -> replay_close_rect (x and w are the map's, already lawful); jmp BaseButton_init.
  t_rp_title     CALL at 0x5AD683 (ReplayWin_draw's d618 title box, rect = the locals {L+4, T+4, R-4, T+0x18} of the
                 client rect): -> replay_title_box; jmp t_nwf_box (the lobby's filled-box painter: K stroke + stripe
                 tail).  The text rect that ReplayWin_draw insets from the same locals uses t_nwf_ins3 (0x5AD691).
  t_rp_btndraw   JMP at 0x404220 (the vtbl+0x14 item-draw stub, dw_scale's site, which jumped to thunk_dw_btndraw):
                 the Close button -- [esp+4] == g_rp_btn (set only while a replay runs at g > 16) AND == ecx + 0x247A0
                 (FlatButton_content_draw calls the stub with ecx = the button's parent, so the button IS this window's
                 Close) -> jmp t_rp_face; anything else -> jmp thunk_dw_btndraw with every register, flag and stack
                 byte as it came.
  t_rp_zoom      CALL at 0x5AD85E (the fitted zoom's store, 6 B + NOP): g > 16 -> store g_rp_z (the fit on the
                 un-grown window, which t_rp_winsize computed) instead of the fit the builder just made on the grown
                 locals; equal for every #WORLDSIZE world, it keeps tiny custom worlds from climbing a unit.
                 g <= 16 -> the plain store.
  t_rp_winsize   CALL at 0x5AD772 (GraphicWin_init_2 of the window, rect = the builder's locals {0,0,800,600}): the
                 rect -> replay_window(g, MapAreaX, MapAreaY, ScreenWidth, ScreenHeight): (s(800), s(600)), the
                 fit z0 of that window -> g_rp_z, and W grown to replay_clip_free_width(u0, X) + 2 s(3)
                 (H := max(H, ceil(3W/4))) where the engine's centring would clip a map row AND the grown window
                 fits the screen AND the fit is above -16 (where the engine draws no map); else s(800) x s(600),
                 the map clipping as vanilla's; jmp GraphicWin_init_2.
  t_rp_face      the Close face (from t_rp_btndraw; the stub's contract: (button, a, b) RET 0xC, eax = 0 = draw the
                 label): every face pixel of the idle pair 238 / 174 and of the hover / pressed pair 224 / 225 ->
                 the BRIGHTER member (238 / 224) on the window grid's stripe_top rows (parent-local row = the
                 button's +0x140 + +0x150 + y), the darker elsewhere (vanilla: bright on the window's even rows);
                 then the four corners keyed (9) s x s, s = btn_corner_notch(g) = ceil(g/16).
  g_rp_btn       4-byte cell, 0 at rest.   g_rp_z   4-byte cell, the un-grown fit (rewritten every build at g > 16).
  t_rp_rows      chain head at 0x46A5AE (map_recentre_fullredraw's site): the replay MapWin's row fix at every g
                 (vanilla's last-row / top-row bug) and its centring at g > 16; else thunk_drawmap_fullguard.
  g_rp_map       4-byte cell, the replay's MapWin while a replay runs (every g), 0 at rest.
Reused unchanged: t_nwf_box (0x5AD650, the d690 outer box) and t_nwf_ins3 (0x5AD691, `mov eax, 3`).

Usage: assemble_replay.py [--splice]   (no flag: print the yaml symbol + content lines)
"""
from __future__ import annotations

import struct
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: F401,E402  (every keystone import is guarded)

PCAVE2 = 0x00A0C000
REGION = (0x46000, 0x48000)
SLOTS = {
    "t_rp_bracket": 0x46000,
    "t_rp_maprect": 0x46040,
    "t_rp_close": 0x460C0,
    "t_rp_title": 0x46120,
    "t_rp_btndraw": 0x46180,
    "t_rp_zoom": 0x461C0,
    "t_rp_winsize": 0x46200,
    "t_rp_face": 0x46380,
    "t_rp_rows": 0x46500,
    "g_rp_btn": 0x46800,
    "g_rp_z": 0x46804,
    "g_rp_map": 0x46808,
}
CELLS = ("g_rp_btn", "g_rp_z", "g_rp_map")
G = 0x00668740                      # g_popup_scale_num
G_STRIPE_PERIOD = 0x0066879C        # g_stripe_period (P = 2T), written with g by thunk_ensure_scale
G_RP_BTN = PCAVE2 + SLOTS["g_rp_btn"]
G_RP_Z = PCAVE2 + SLOTS["g_rp_z"]
G_RP_MAP = PCAVE2 + SLOTS["g_rp_map"]

REPLAYWIN_BUILD = 0x005AD720
GRAPHICWIN_INIT_2 = 0x005D50A0
MAPWIN_INIT = 0x00470920
BASEBUTTON_INIT = 0x00607210
BUFFER_BOX_SPRITE = 0x005E2DD3
T_NWF_BOX = PCAVE2 + 0x40020       # netwin_frame_strokes: Buffer_box_sprite's contract, g-gated
T_NWF_INS3 = PCAVE2 + 0x40040      # netwin_frame_strokes: eax = 3 or scale_px(3, g)
THUNK_DW_BTNDRAW = PCAVE2 + 0x17E40   # dw_scale: the 0x404220 stub's previous target
FULLGUARD = PCAVE2 + 0x5CA8           # map_recentre_fullredraw: thunk_drawmap_fullguard, the 0x46A5AE site's previous target
SITE_POSTCALC = 0x0046A5AE            # MapWin_draw_map, right after MapWin_calculate_dimensions (push / ret detour, 6 B)
MAP_OFF = 0x2320                      # ReplayWin +0x2320 = its MapWin (Console)
CLOSE_BTN_OFF = 0x247A0            # ReplayWin +0x247A0 = the Close FlatButton
MAP_AREA_X, MAP_AREA_Y = 0x00949870, 0x00949874
SCREEN_W, SCREEN_H = 0x009B7B1C, 0x009B7B20   # ScreenWidth / ScreenHeight: the dims Win_center centres the window in
ZOOM_FIELD = 0x200B8               # ReplayWin +0x2320 MapWin +0x1DD98 (map_zoom_idx)
FACE_PAIRS = ((238, 174), (224, 225))   # (bright, dark): idle 0x78D960 (AE / EE), hover / pressed 0x78D9B0 (E1 / E0)
KEY = 9

SITE_BRACKET, SITE_WINSIZE, SITE_MAPRECT, SITE_CLOSE = 0x005ADC93, 0x005AD772, 0x005AD838, 0x005AD8DD
SITE_OUTER, SITE_TITLE, SITE_INS3, SITE_ITEMDRAW = 0x005AD650, 0x005AD683, 0x005AD691, 0x00404220
SITE_ZOOM = 0x005AD85E             # `mov [esi+0x200B8], edi` (89 BE B8 00 02 00): the fitted zoom's store

ABS = {G: "{abs32:g_popup_scale_num}", G_RP_BTN: "{abs32:g_rp_btn}",
       G_RP_Z: "{abs32:g_rp_z}", G_RP_MAP: "{abs32:g_rp_map}", MAP_AREA_X: "{abs32:MapAreaX}", MAP_AREA_Y: "{abs32:MapAreaY}"}
REL = {REPLAYWIN_BUILD: "{rel32:ReplayWin_build}"}


def _s(reg: str, v: int) -> str:
    """reg := scale_px(v, g) = (2 v g + 15) >> 5 (half_down(v g, 16); g >= 1)."""
    return f"""
    imul    {reg}, dword ptr [{G:#x}], {2 * v}
    add     {reg}, 0xf
    sar     {reg}, 5"""


def asm_bracket() -> str:
    """g_rp_map := ecx + 0x2320 (the replay's MapWin) at EVERY g (t_rp_rows' row fix is vanilla's bug, all
    resolutions); g_rp_btn := ecx + 0x247A0 at g > 16; call ReplayWin_build; both cleared; bare ret."""
    return f"""
    lea     eax, [ecx+{MAP_OFF:#x}]
    mov     dword ptr [{G_RP_MAP:#x}], eax
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    lea     eax, [ecx+{CLOSE_BTN_OFF:#x}]
    mov     dword ptr [{G_RP_BTN:#x}], eax
go:
    call    {REPLAYWIN_BUILD:#x}
    mov     dword ptr [{G_RP_BTN:#x}], 0
    mov     dword ptr [{G_RP_MAP:#x}], 0
    ret
"""


def asm_winsize() -> str:
    """rect = [esp+4] = the locals {L, T, R, B}.  W0 = s(R-L), H0 = s(B-T); z0 = the builder's fit on (W0, H0)
    (replay_fit_z: idiv truncation, positive operands) -> g_rp_z; u0 = map_u_of_zoom(z0); need = 4 u0 (X+2) + 2 s(3);
    W = max(W0, need), H = max(H0, (3W + 3) >> 2) when grown; R := L + W, B := T + H.  ecx (the window) and the stack
    kept; eax / edx / esi / edi / ebx saved."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    push    edx
    push    ebx
    push    esi
    push    edi
    push    ecx
    mov     esi, dword ptr [esp+0x1c]
    mov     eax, dword ptr [esi+8]
    sub     eax, dword ptr [esi]
    imul    eax, dword ptr [{G:#x}]
    lea     edi, [eax+eax+0xf]
    sar     edi, 5
    mov     eax, dword ptr [esi+0xc]
    sub     eax, dword ptr [esi+4]
    imul    eax, dword ptr [{G:#x}]
    lea     ebx, [eax+eax+0xf]
    sar     ebx, 5
    lea     eax, [edi+edi]
    cdq
    idiv    dword ptr [{MAP_AREA_X:#x}]
    shl     eax, 4
    cdq
    mov     ecx, 100
    idiv    ecx
    lea     ecx, [eax-0x10]
    lea     eax, [ebx+ebx]
    cdq
    idiv    dword ptr [{MAP_AREA_Y:#x}]
    shl     eax, 4
    cdq
    push    50
    idiv    dword ptr [esp]
    add     esp, 4
    sub     eax, 0x10
    cmp     eax, ecx
    jge     zx
    mov     ecx, eax
zx:
    mov     dword ptr [{G_RP_Z:#x}], ecx
    cmp     ecx, -16
    jle     store
    lea     eax, [ecx+0x10]
    imul    eax, eax, 50
    sar     eax, 4
    inc     eax
    sar     eax, 2
    cmp     eax, 1
    jge     u_ok
    mov     eax, 1
u_ok:
    mov     edx, dword ptr [{MAP_AREA_X:#x}]
    inc     edx
    imul    eax, edx
    shl     eax, 2
{_s("edx", 3)}
    lea     eax, [eax+edx*2]
    cmp     eax, edi
    jle     store
    cmp     eax, dword ptr [{SCREEN_W:#x}]
    jg      store
    lea     edx, [eax+eax*2+3]
    sar     edx, 2
    cmp     edx, ebx
    jge     h_ok
    mov     edx, ebx
h_ok:
    cmp     edx, dword ptr [{SCREEN_H:#x}]
    jg      store
    mov     edi, eax
    mov     ebx, edx
store:
    mov     eax, dword ptr [esi]
    add     eax, edi
    mov     dword ptr [esi+8], eax
    mov     eax, dword ptr [esi+4]
    add     eax, ebx
    mov     dword ptr [esi+0xc], eax
    pop     ecx
    pop     edi
    pop     esi
    pop     ebx
    pop     edx
    pop     eax
go:
    jmp     {GRAPHICWIN_INIT_2:#x}
"""


def asm_maprect() -> str:
    """locals {L+3, T+26, R-3, B-26} of the window -> (L+s3, T+s26, R-s3, B-s26).  ecx (the MapWin) kept."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    push    edx
    push    esi
    mov     esi, dword ptr [esp+0x10]
{_s("edx", 3)}
    sub     edx, 3
    add     dword ptr [esi], edx
    sub     dword ptr [esi+8], edx
{_s("edx", 26)}
    sub     edx, 26
    add     dword ptr [esi+4], edx
    sub     dword ptr [esi+0xc], edx
    pop     esi
    pop     edx
    pop     eax
go:
    jmp     {MAPWIN_INIT:#x}
"""


def asm_close() -> str:
    """BaseButton_init(label, id, x, y, w, h, parent, 0): y = map B + 3 = (H - s26) + 3 -> H - s23; h -> s23 - s3."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    push    edx
{_s("eax", 23)}
{_s("edx", 26)}
    sub     edx, eax
    sub     edx, 3
    add     dword ptr [esp+0x18], edx
{_s("edx", 3)}
    sub     eax, edx
    mov     dword ptr [esp+0x20], eax
    pop     edx
    pop     eax
go:
    jmp     {BASEBUTTON_INIT:#x}
"""


def asm_title() -> str:
    """locals {L+4, T+4, R-4, T+0x18} -> (L+s4, T+s4, R-s4, T+s24); then t_nwf_box (ecx = the dest Buffer, kept)."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    push    edx
    push    esi
    mov     esi, dword ptr [esp+0x10]
{_s("edx", 4)}
    sub     edx, 4
    add     dword ptr [esi], edx
    sub     dword ptr [esi+8], edx
    mov     eax, dword ptr [esi+4]
    sub     eax, 4
    add     dword ptr [esi+4], edx
{_s("edx", 24)}
    add     eax, edx
    mov     dword ptr [esi+0xc], eax
    pop     esi
    pop     edx
    pop     eax
go:
    jmp     {T_NWF_BOX:#x}
"""


def asm_btndraw() -> str:
    """The vtbl+0x14 item-draw stub chain head: this window's Close button -> t_rp_face; else thunk_dw_btndraw with
    every register, flag and stack byte unchanged."""
    return f"""
    pushfd
    cmp     dword ptr [{G_RP_BTN:#x}], 0
    je      pass
    push    eax
    mov     eax, dword ptr [esp+0xc]
    cmp     eax, dword ptr [{G_RP_BTN:#x}]
    jne     no
    sub     eax, {CLOSE_BTN_OFF:#x}
    cmp     eax, ecx
no:
    pop     eax
    jne     pass
    popfd
    jmp     {PCAVE2 + SLOTS["t_rp_face"]:#x}
pass:
    popfd
    jmp     {THUNK_DW_BTNDRAW:#x}
"""


def asm_zoom() -> str:
    """CALL at 0x5AD85E (replaces `mov [esi+0x200B8], edi`, 6 B -> E8 rel32 + NOP).  g <= 16: the store as it was;
    g > 16: the store of g_rp_z.  Every register kept; flags are dead here (the next flag writer `add eax, 3`
    @0x5AD891, no jcc between).  Law replay_map_zoom."""
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     plain
    push    eax
    mov     eax, dword ptr [{G_RP_Z:#x}]
    mov     dword ptr [esi+{ZOOM_FIELD:#x}], eax
    pop     eax
    ret
plain:
    mov     dword ptr [esi+{ZOOM_FIELD:#x}], edi
    ret
"""


def asm_face() -> str:
    """t_rp_face: stack [esp] = the return into FlatButton_content_draw, [esp+4] = the button (+0x444 its Buffer:
    bits +0x498, w +0x47C, h +0x480, negative = top-down; stride (w + 3) & ~3), [esp+8] / [esp+0xC] the stub's other
    args.  RET 0xC with eax = 0 (the default label draw follows).  ebx / esi / edi / ebp kept.
    ASSUMES A TOP-DOWN buffer (row y at bits + y * stride, h taken as |h|): every engine Buffer is created with a
    negative DIB height (canvas_of / the button canvases measured so); a bottom-up buffer would need row h-1-y."""
    (b0, d0), (b2, d2) = FACE_PAIRS
    return f"""
    push    ebp
    push    ebx
    push    esi
    push    edi
    sub     esp, 0x18
    mov     esi, dword ptr [esp+0x2c]
    mov     edi, dword ptr [esi+0x498]
    test    edi, edi
    je      done
    mov     eax, dword ptr [esi+0x47c]
    test    eax, eax
    jle     done
    mov     dword ptr [esp], eax
    mov     edx, dword ptr [esi+0x480]
    test    edx, edx
    jge     hpos
    neg     edx
hpos:
    test    edx, edx
    je      done
    mov     dword ptr [esp+4], edx
    add     eax, 3
    and     eax, 0xfffffffc
    mov     dword ptr [esp+8], eax
    mov     eax, dword ptr [esi+0x140]
    add     eax, dword ptr [esi+0x150]
    mov     dword ptr [esp+0xc], eax
    mov     ecx, dword ptr [{G_STRIPE_PERIOD:#x}]
    shr     ecx, 1
    jne     t_ok
    mov     ecx, 1
t_ok:
    mov     dword ptr [esp+0x10], ecx
    xor     ebp, ebp
row:
    cmp     ebp, dword ptr [esp+4]
    jge     notch
    mov     eax, dword ptr [esp+0xc]
    add     eax, ebp
    cdq
    idiv    dword ptr [esp+0x10]
    test    al, 1
    mov     ebx, {b0 | (b2 << 8)}
    je      top
    mov     ebx, {d0 | (d2 << 8)}
top:
    mov     eax, dword ptr [esp+8]
    imul    eax, ebp
    lea     edx, [edi+eax]
    xor     ecx, ecx
col:
    cmp     ecx, dword ptr [esp]
    jge     next_row
    mov     al, byte ptr [edx+ecx]
    cmp     al, {b0}
    je      p0
    cmp     al, {d0}
    je      p0
    cmp     al, {b2}
    je      p2
    cmp     al, {d2}
    jne     nx
    mov     byte ptr [edx+ecx], bh
    jmp     nx
p2:
    mov     byte ptr [edx+ecx], bh
    jmp     nx
p0:
    mov     byte ptr [edx+ecx], bl
nx:
    inc     ecx
    jmp     col
next_row:
    inc     ebp
    jmp     row
notch:
    mov     ecx, dword ptr [{G:#x}]
    add     ecx, 0xf
    shr     ecx, 4
    cmp     ecx, dword ptr [esp]
    jle     s_w
    mov     ecx, dword ptr [esp]
s_w:
    cmp     ecx, dword ptr [esp+4]
    jle     s_h
    mov     ecx, dword ptr [esp+4]
s_h:
    mov     dword ptr [esp+0x14], ecx
    xor     ebp, ebp
nrow:
    cmp     ebp, dword ptr [esp+0x14]
    jge     done
    mov     eax, dword ptr [esp+8]
    imul    eax, ebp
    lea     edx, [edi+eax]
    mov     eax, dword ptr [esp+4]
    dec     eax
    sub     eax, ebp
    imul    eax, dword ptr [esp+8]
    lea     ebx, [edi+eax]
    xor     ecx, ecx
ncol:
    cmp     ecx, dword ptr [esp+0x14]
    jge     nnext
    mov     byte ptr [edx+ecx], {KEY}
    mov     byte ptr [ebx+ecx], {KEY}
    mov     eax, dword ptr [esp]
    dec     eax
    sub     eax, ecx
    mov     byte ptr [edx+eax], {KEY}
    mov     byte ptr [ebx+eax], {KEY}
    inc     ecx
    jmp     ncol
nnext:
    inc     ebp
    jmp     nrow
done:
    add     esp, 0x18
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    xor     eax, eax
    ret     0xc
"""


def asm_rows() -> str:
    """t_rp_rows: chain head at 0x46A5AE (MapWin_draw_map right after MapWin_calculate_dimensions; entry: esi = the
    MapWin, edi = 0, eax dead -- thunk_drawmap_fullguard's contract).  esi == g_rp_map (the live replay's MapWin) and
    the whole world shown (oddX == X/2, oddY == Y/2):
      ROW FIX (every g; vanilla's bug): calc_dimensions clamps the top row to -2..+4 from the faction's view centre,
      but MapWin_tile_to_pixel only wraps rows in [top, top + oddY + evenY) properly -- at -2 the world's last row
      lands half a world to the left (the "tiles in the air"), at +1..+4 the top rows are never drawn.  top :=
      -(top & 1) (0 or -1, its parity kept so the columns stay), pixel_top += 2u (top' - top): every row already
      placed stays put, the misplaced / missing ones land where they belong.
      CENTRING (g > 16; the user's decision): pixel_left := (cw - 4u(X+1)) / 2 + 4u (the map's span is
      [pixel_left - 4u, pixel_left + 4uX): alternate rows start 4u left), pixel_top := T - 1 + 2u (top' + 1) with
      T = (ch - (2u(Y+1) - 1)) / 2 (the ink from py(0) + 1 to py(Y-1) + 4u - 1): equal margins (+-1).
    Anything else -> thunk_drawmap_fullguard with every register, flag and stack byte unchanged."""
    return f"""
    pushfd
    cmp     esi, dword ptr [{G_RP_MAP:#x}]
    jne     pass
    pushal
    mov     eax, dword ptr [{MAP_AREA_X:#x}]
    sar     eax, 1
    cmp     eax, dword ptr [esi+0x1ddcc]
    jne     done
    mov     eax, dword ptr [{MAP_AREA_Y:#x}]
    sar     eax, 1
    cmp     eax, dword ptr [esi+0x1ddd0]
    jne     done
    mov     ebx, dword ptr [esi+0x1ddc8]
    mov     ecx, dword ptr [esi+0x1dda8]
    mov     edx, ecx
    and     edx, 1
    neg     edx
    mov     dword ptr [esi+0x1dda8], edx
    mov     eax, edx
    sub     eax, ecx
    imul    eax, ebx
    shl     eax, 1
    add     dword ptr [esi+0x1ddb0], eax
    cmp     dword ptr [{G:#x}], 0x10
    jle     done
    mov     eax, dword ptr [esi]
    mov     eax, dword ptr [eax+4]
    add     eax, esi
    mov     ecx, dword ptr [eax+0x4c4]
    mov     edi, dword ptr [eax+0x4c8]
    neg     edi
    mov     eax, dword ptr [{MAP_AREA_X:#x}]
    inc     eax
    imul    eax, ebx
    shl     eax, 2
    sub     ecx, eax
    sar     ecx, 1
    lea     ecx, [ecx+ebx*4]
    mov     dword ptr [esi+0x1ddac], ecx
    mov     eax, dword ptr [{MAP_AREA_Y:#x}]
    inc     eax
    imul    eax, ebx
    shl     eax, 1
    dec     eax
    sub     edi, eax
    sar     edi, 1
    dec     edi
    lea     eax, [edx+1]
    imul    eax, ebx
    shl     eax, 1
    add     edi, eax
    mov     dword ptr [esi+0x1ddb0], edi
done:
    popal
    popfd
    jmp     {FULLGUARD:#x}
pass:
    popfd
    jmp     {FULLGUARD:#x}
"""


SOURCES = {"t_rp_bracket": asm_bracket, "t_rp_maprect": asm_maprect, "t_rp_close": asm_close,
           "t_rp_title": asm_title, "t_rp_btndraw": asm_btndraw, "t_rp_zoom": asm_zoom, "t_rp_winsize": asm_winsize,
           "t_rp_face": asm_face, "t_rp_rows": asm_rows}


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b), "disassembly does not cover"
    return b


def to_template(b: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):   # the patcher takes {rel32:} after E8 only; E9s to fixed VAs stay raw
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
        limit = SLOTS[order[k + 1]] if k + 1 < len(order) else SLOTS["g_rp_btn"]
        assert SLOTS[name] + len(b) <= limit, f"{name} {len(b)}B overflows its slot"
        out[name] = b
    assert REGION[0] <= min(SLOTS.values()) and SLOTS["g_rp_map"] + 4 <= REGION[1]
    return out


def itemdraw_site_bytes() -> bytes:
    """0x404220: E9 rel32 -> t_rp_btndraw (was E9 -> thunk_dw_btndraw)."""
    return b"\xE9" + struct.pack("<i", PCAVE2 + SLOTS["t_rp_btndraw"] - (SITE_ITEMDRAW + 5))


DW_ITEMDRAW_OLD = "E9 1B FC 61 00"     # E9 -> thunk_dw_btndraw (pcave2 + 0x17E40)
assert bytes.fromhex(DW_ITEMDRAW_OLD.replace(" ", "")) == b"\xE9" + struct.pack("<i", THUNK_DW_BTNDRAW - (SITE_ITEMDRAW + 5))

GROUP = "replay_scale"
SYM_NOTES = {
    "t_rp_bracket": "CALL at show_replay 0x5ADC93: g>16 -> g_rp_btn := Close button, call ReplayWin_build, clear, bare ret",
    "t_rp_maprect": "CALL at 0x5AD838 (MapWin_init): the map child rect -> replay_map_rect",
    "t_rp_close": "CALL at 0x5AD8DD (BaseButton_init): the Close bar's y / h -> replay_close_rect",
    "t_rp_title": "CALL at 0x5AD683 (the d618 title box): rect -> replay_title_box, then t_nwf_box",
    "t_rp_btndraw": "JMP at 0x404220 (vtbl+0x14 item-draw stub): this window's Close button -> t_rp_face, else thunk_dw_btndraw unchanged",
    "t_rp_zoom": "CALL at 0x5AD85E (the fitted zoom's store): g>16 stores g_rp_z, the fit on the un-grown window (law replay_map_zoom)",
    "t_rp_winsize": "CALL at 0x5AD772 (GraphicWin_init_2): the window -> replay_window (s(800) x s(600), grown 4:3 where the map would clip a row); g_rp_z := the fit",
    "t_rp_rows": "chain head at 0x46A5AE (after MapWin_calculate_dimensions): the replay MapWin's row fix (every g, vanilla's last-row / top-row bug) + centring (g>16); else thunk_drawmap_fullguard unchanged",
    "t_rp_face": "the Close face: pairs 238/174 and 224/225 bright on the window grid's stripe_top rows, corners keyed s x s (btn_corner_notch); RET 0xC eax 0",
}
CELL_NOTES = {
    "g_rp_btn": "the Close FlatButton (ReplayWin +0x247A0) while a replay runs at g > 16; 0 at rest",
    "g_rp_z": "the map zoom fit on the un-grown window (t_rp_winsize -> t_rp_zoom), rewritten every build at g > 16",
    "g_rp_map": "the replay's MapWin (ReplayWin +0x2320) while a replay runs, at every g; 0 at rest",
}
ENGINE_SYMBOLS = (("ReplayWin_build", REPLAYWIN_BUILD, "fastcall ecx = ReplayWin; builds and runs the replay (modal inside)"),
                  ("MapAreaX", MAP_AREA_X, "int32: the world's width in half-tiles (2 x the #WORLDSIZE width)"),
                  ("MapAreaY", MAP_AREA_Y, "int32: the world's rows"))
NEW_SITES = (   # (id, function, va, original, new, pattern, note)
    ("show_replay.build_bracket", "show_replay", SITE_BRACKET, "E8 88 FA FF FF", "E8 {rel32:t_rp_bracket}",
     "call_target_redirect", "call ReplayWin_build (the whole replay runs inside)"),
    ("ReplayWin_build.window_size", "ReplayWin_build", SITE_WINSIZE, "E8 29 79 02 00", "E8 {rel32:t_rp_winsize}",
     "call_target_redirect", "call GraphicWin_init_2 (the window, rect = locals {0,0,0x320,0x258})"),
    ("ReplayWin_build.map_rect", "ReplayWin_build", SITE_MAPRECT, "E8 E3 30 EC FF", "E8 {rel32:t_rp_maprect}",
     "call_target_redirect", "call MapWin_init (rect = locals {L+3, T+0x1A, R-3, B-0x1A})"),
    ("ReplayWin_build.zoom_store", "ReplayWin_build", SITE_ZOOM, "89 BE B8 00 02 00", "E8 {rel32:t_rp_zoom} 90",
     "instruction_to_thunk_call_plus_nop", "mov [esi+0x200B8], edi (the map zoom the fit chose)"),
    ("ReplayWin_build.close_button", "ReplayWin_build", SITE_CLOSE, "E8 2E 99 05 00", "E8 {rel32:t_rp_close}",
     "call_target_redirect", "call BaseButton_init (Close: y = map B + 3, h = 0x14)"),
    ("ReplayWin_draw.outer_box", "ReplayWin_draw", SITE_OUTER, "E8 7E 57 03 00", "E8 {rel32:t_nwf_box}",
     "call_target_redirect", "call Buffer_box_sprite (d690 outer, the client rect)"),
    ("ReplayWin_draw.title_box", "ReplayWin_draw", SITE_TITLE, "E8 4B 57 03 00", "E8 {rel32:t_rp_title}",
     "call_target_redirect", "call Buffer_box_sprite (d618 title box {L+4, T+4, R-4, T+0x18})"),
    ("ReplayWin_draw.text_inset", "ReplayWin_draw", SITE_INS3, "B8 03 00 00 00", "E8 {rel32:t_nwf_ins3}",
     "literal_to_thunk_call", "MOV EAX, 3 (the title text rect's inset inside the title box)"),
)
M_SYM = (f"  # ==== {GROUP} symbols (2026-11-15, src assemble_replay.py) ====\n", f"  # ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} (assemble_replay.py), 2026-11-15 ====\n", f"      # ==== {GROUP} END ==== cave\n")
M_GRP = (f"  # ==== {GROUP} group ====\n", f"  # ==== {GROUP} END ==== group\n")
M_SITE = (f"  # ==== {GROUP} sites (2026-11-15; src assemble_replay.py) ====\n", f"  # ==== {GROUP} END ==== sites\n")
GROUP_TEXT = f"""  - id: {GROUP}
    description: >
      The end-game REPLAY window (show_replay 0x5ADBF0, a stack-local ReplayWin built at a literal 800 x 600 +
      Win_center over the live map) drew natively at every g, its title and Close label already at g and clipped.
      It now scales as a popup-family window: the window -> replay_window (s(800) x s(600), grown 4:3 just enough
      where the engine's centring would clip a map row -- the user's decision 2026-11-15), the map child ->
      replay_map_rect, the Close bar -> replay_close_rect, the d618 title box -> replay_title_box and its text inset
      -> s(3) (t_nwf_ins3), both boxes painted by the lobby's t_nwf_box (K = stroke_width(g), the 1-row fills
      regenerated on the stripe law), and the Close face (0x78D960 / 0x78D9B0) restriped by t_rp_face: bright on
      the window grid's stripe_top rows as vanilla, corners keyed btn_corner_notch(g).  The map is the engine's own
      zoom fit on the s(800) x s(600) window (the user's option A, 2026-11-15): crisp, off vanilla x g/16 by the fit's
      8-px tile quantization, accepted; t_rp_zoom stores that fit so a grown window never raises the unit.
      The map rows (every g, vanilla's bug): t_rp_rows fixes the replay map's row window after
      MapWin_calculate_dimensions -- the world's last row no longer lands half a world to the left, the top rows are
      no longer dropped -- and above g 16 centres the map in its child (the user's decision 2026-11-15).
      CROSS-GROUP: dw_scale's site FlatButton_itemdraw_stub (0x404220) now jumps to t_rp_btndraw, and
      map_recentre_fullredraw's site MapWin_draw_map.postcalc_guard (0x46A5AE) to t_rp_rows; each passes everything
      that is not this replay's to the previous target (thunk_dw_btndraw / thunk_drawmap_fullguard, bytes untouched)
      with every register, flag and stack byte unchanged.  g <= 16: every scaling site makes the vanilla call.  Laws scaling_laws END-GAME REPLAY; src
      assemble_replay.py; guard tests/test_scaling_replay.py.
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
    j = text.index("\n", i + len(anchor_after) - 1) + 1
    return text[:j] + blk + text[j:]


def splice(path) -> None:
    """Splice this group into patches.yaml byte-safely (text edits only)."""
    import pathlib
    p = pathlib.Path(path)
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    built = build()
    sym = "".join(f"  {n + ':':<31}{{ cave: pcave2, offset: {SLOTS[n]:#x} }}   # {GROUP} ({len(built[n])}B) {SYM_NOTES[n]}\n"
                  for n in sorted(built, key=lambda n: SLOTS[n]))
    for c in CELLS:
        sym += f"  {c + ':':<31}{{ cave: pcave2, offset: {SLOTS[c]:#x}, size: 4 }}   # {GROUP}: {CELL_NOTES[c]}\n"
    for name, va, note in ENGINE_SYMBOLS:
        sym += f"  {name + ':':<31}{{ va: 0x{va:08X} }}                           # {note}\n"
    cave = "".join(f"      - id: {n}\n        offset: {SLOTS[n]:#x}\n        bytes: \"{to_template(built[n], PCAVE2 + SLOTS[n])}\"\n"
                   for n in sorted(built, key=lambda n: SLOTS[n]))
    for c in CELLS:
        cave += f"      - id: {c}\n        offset: {SLOTS[c]:#x}\n        bytes: \"00 00 00 00\"\n"
    sites = "".join(
        f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {fn}\n    virtual_addr: 0x{va:08X}\n"
        f"    length: {len(orig.split())}\n    original_bytes: \"{orig}\"{' ' * max(1, 23 - len(orig))}# {note}\n"
        f"    new_bytes:      \"{new}\"\n    pattern: {pat}\n"
        for sid, fn, va, orig, new, pat, note in NEW_SITES)
    text = _replace_or_insert(text, M_SYM, sym, "  # ==== netwin_frame_strokes END ==== symbols")
    text = _replace_or_insert(text, M_CAVE, cave, "      # ==== netwin_frame_strokes END ==== cave")
    text = _replace_or_insert(text, M_GRP, GROUP_TEXT, "  # ==== netwin_frame_strokes END ==== group")
    text = _replace_or_insert(text, M_SITE, sites, "  # ==== netwin_frame_strokes END ==== sites")
    # dw_scale's item-draw stub site: E9 -> t_rp_btndraw (raw rel32: both ends are fixed VAs)
    i = text.index("  - id: FlatButton_itemdraw_stub\n")
    j = text.index("    new_bytes:", i)
    k = text.index("\n", j)
    new = " ".join(f"{x:02X}" for x in itemdraw_site_bytes())
    line = text[j:k]
    assert any(f'"{v}"' in line for v in (DW_ITEMDRAW_OLD, new, "E9 DB DF 64 00")), line   # DB DF: e6adbb3's slot
    text = text[:j] + f'    new_bytes:      "{new}"   # E9 -> t_rp_btndraw (group {GROUP}), which chains to thunk_dw_btndraw' + text[k:]
    # map_recentre_fullredraw's postcalc site: push t_rp_rows; ret (was push thunk_drawmap_fullguard; ret)
    i = text.index("  - id: MapWin_draw_map.postcalc_guard\n")
    j = text.index("    new_bytes:", i)
    k = text.index("\n", j)
    line = text[j:k]
    assert "{abs32:thunk_drawmap_fullguard}" in line or "{abs32:t_rp_rows}" in line, line
    text = text[:j] + ('    new_bytes:      "68 {abs32:t_rp_rows} C3"   # push t_rp_rows; ret (group replay_scale: the '
                       'replay MapWin\'s row fix + centring, everything else -> thunk_drawmap_fullguard)') + text[k:]
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
    print(f"  0x404220 -> {itemdraw_site_bytes().hex(' ').upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
