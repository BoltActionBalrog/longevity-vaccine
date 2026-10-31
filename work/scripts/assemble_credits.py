#!/usr/bin/env python
# Keystone assembler for the View Credits + Interlude scaling thunks
# (group credits_interlude_scaling).
#
# Root cause (both screens): Buffer_load_pcx RESIZES its target Buffer to the
# pcx dims (1024x768 credits2.pcx / 800x600 credits.pcx), so the "fullscreen"
# backdrop collapses to a native-size block in the top-left corner at any
# res > 1024x768. Additionally the credits scroller sub-window (30,200,400x400),
# its font (14), scroll rate (1px/tick), fade bands (8x2px) and the interlude
# text font / 0x19 left clamp / 0x32 INTERLUDE21-22 nudge are native constants.
#
# Thinker prior art (refs\thinker\src\patch.cpp 1363-1367, gui.cpp 1264-1302):
# window_scale_load_pcx at 0x45F3C2 + 0x5D552E (load into temp Buffer, resize
# target to screen, StretchBlt-stretch anamorphically) — we mirror that shape
# with our own primitives, and additionally scale the credits text machinery
# (thinker leaves it native).
#
# All thunks: vanilla-at-1024 x g/16 (g = g_popup_scale_num, ensured via
# thunk_ensure_scale since credits opens straight from the main menu before any
# popup computes it). g<=16 -> pure-math identity or explicit native tail.
#
# Regenerate if any cave offset moves (absolute addrs are baked).

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0xA0C000
MSTRIP_VA = 0x668200                    # menu_strip_thunks cave base

# cave helpers (menu_strip_thunks)
ENSURE_SCALE   = MSTRIP_VA + 0x560      # thunk_ensure_scale: computes g once; clobbers eax/ecx/edx
POPUP_SCALE    = MSTRIP_VA + 0x550      # popup_scale: eax = eax*g/16; clobbers eax+flags only
ENSURE_FRAMEBF = MSTRIP_VA + 0xCE0      # thunk_ensure_frame_buf -> eax = g_frame_buf; clobbers eax/ecx/edx
G_SCALE        = MSTRIP_VA + 0x540      # g_popup_scale_num

# engine
BUFFER_LOAD_PCX   = 0x5D7DE0            # __thiscall(Buffer*; name, pal*, a4, a5) RET 0x10
BUFFER_RESIZE     = 0x5D79C0            # __thiscall(Buffer*; w, h) RET 8
BUFFER_COPY_3     = 0x5D9610            # __thiscall(src; dst, sx,sy,sw,sh, dx,dy,dw,dh) RET 0x24 = GDI StretchBlt
GRAPHICWIN_INIT   = 0x5D4EF0            # __thiscall 9 args RET 0x24
FONT_INIT         = 0x618F40            # __thiscall(Font*; name, size, flags) RET 0xC
FIND_FONT         = 0x5882F0            # __cdecl(size, variant) -> Font*; clobbers eax/ecx/edx
BUFFER_SET_FONT   = 0x5DAC70            # __thiscall(Buffer*; f0, f1, f2, flags) RET 0x10
BUFFER_CHG_COLOR3 = 0x5E2070            # __thiscall(Buffer*; 0, y, w, h, 0, shade) RET 0x18
SCREEN_W          = 0x9B7B1C
SCREEN_H          = 0x9B7B20
FONT_SIZE_TABLE   = 0x68F220            # int[12] {40,36,32,24,22,20,18,16,14,12,10,8}
FONT_TABLE_V0     = 0x93FC58            # variant-0 Font rows, stride 0xA0
G_FONT0           = 0x945770            # config_popups fonts: variant 0
G_FONT1           = 0x9457FC            # variant 1
G_FONT2           = 0x9457F8            # variant 2
WAVE_IS_PLAYING   = 0x4C6B10            # __thiscall(Wave*) -> bool; null-safe on unloaded waves
WAVE_PLAY_2       = 0x4C6920            # __thiscall(Wave*)
G_MENU_MUSIC_WAVE = 0x945780            # top_menu's "fx\opening menu.wav" Wave (0x58E3D9)

LAYOUT = {
    'thunk_pcx_fullscreen':   0x3A00,
    'thunk_credits_subwin':   0x3AA0,
    'thunk_credits_font':     0x3B20,
    'thunk_credits_scroll':   0x3B50,
    'thunk_credits_fade':     0x3B70,
    'thunk_interlude_font':   0x3C40,
    'g_il_f0':                0x3CE0,
    'g_il_f1':                0x3CE4,
    'g_il_f2':                0x3CE8,
    'thunk_interlude_clamp':  0x3CF0,
    'thunk_interlude_nudge':  0x3D20,
    'thunk_credits_music':    0x3D40,
}
V = {k: PCAVE2_VA + off for k, off in LAYOUT.items()}

THUNKS = {}

# --------------------------------------------------------------------------
# thunk_pcx_fullscreen — shared backdrop fix, sites 0x5D552E (GraphicWin_load_pcx
# inner call: credits + demo splash) and 0x45F3C2 (interlude). Same contract as
# Buffer_load_pcx: ecx=dest Buffer, 4 stack args, RET 0x10, eax=result.
# g<=16 -> tail-jmp the original (byte-identical native). g>16 -> load the pcx
# into g_frame_buf (Buffer_load_pcx sizes it), resize dest to ScreenWxScreenH,
# StretchBlt-stretch frame_buf -> dest anamorphically (Buffer_copy_3 is GDI,
# dest-clipped, upscale-only here so NN row-drop can't bite).
# --------------------------------------------------------------------------
THUNKS['thunk_pcx_fullscreen'] = f"""
    push ecx
    call {ENSURE_SCALE}
    pop ecx
    mov eax, [{G_SCALE}]
    cmp eax, 0x10
    jg scaled
    push {BUFFER_LOAD_PCX}
    ret
scaled:
    push ebx
    push esi
    push edi
    mov esi, ecx
    call {ENSURE_FRAMEBF}
    mov edi, eax
    mov eax, [esp+0x1C]          ; a5
    push eax
    mov eax, [esp+0x1C]          ; a4
    push eax
    mov eax, [esp+0x1C]          ; pal*
    push eax
    mov eax, [esp+0x1C]          ; name
    push eax
    mov ecx, edi
    call {BUFFER_LOAD_PCX}
    mov ebx, eax                 ; load result (returned verbatim)
    mov eax, [edi+0x80]          ; loaded width  (0/neg -> load failed, leave dest alone)
    test eax, eax
    jle done
    mov eax, [edi+0x84]          ; loaded height (stored NEGATIVE)
    test eax, eax
    jz done
    mov eax, [{SCREEN_H}]
    push eax
    mov eax, [{SCREEN_W}]
    push eax
    mov ecx, esi
    call {BUFFER_RESIZE}
    mov eax, [{SCREEN_H}]
    push eax                     ; dstH
    mov eax, [{SCREEN_W}]
    push eax                     ; dstW
    push 0                       ; dstY
    push 0                       ; dstX
    mov eax, [edi+0x84]
    neg eax
    push eax                     ; srcH
    mov eax, [edi+0x80]
    push eax                     ; srcW
    push 0                       ; srcY
    push 0                       ; srcX
    push esi                     ; dst
    mov ecx, edi                 ; this = src
    call {BUFFER_COPY_3}
done:
    mov eax, ebx
    pop edi
    pop esi
    pop ebx
    ret 0x10
"""

# --------------------------------------------------------------------------
# thunk_credits_subwin — detour 0x428A8C..0x428ABD (the 9 GraphicWin_init pushes
# incl. the 800/1024 y-branch + the call), resume 0x428ABE. Entry: esi=credits
# obj, eax/edi dead. Vanilla (30, 200 [100 @800], 400, 400) -> x g/16 (pure-math
# identity at g=16). Must leave edi = esi+0x1234 (consumed by the resume code).
# --------------------------------------------------------------------------
THUNKS['thunk_credits_subwin'] = f"""
    call {ENSURE_SCALE}
    push 0
    push 0
    push esi
    push 0x1000020
    push 0
    mov eax, 400
    call {POPUP_SCALE}
    push eax                     ; h
    push eax                     ; w
    mov eax, 200
    cmp dword ptr [{SCREEN_W}], 0x320
    jne yok
    mov eax, 100
yok:
    call {POPUP_SCALE}
    push eax                     ; y
    mov eax, 30
    call {POPUP_SCALE}
    push eax                     ; x
    lea edi, [esi+0x1234]
    mov ecx, edi
    call {GRAPHICWIN_INIT}
    push 0x428ABE
    ret
"""

# --------------------------------------------------------------------------
# thunk_credits_font — detour 0x428AF2..0x428AFB (push 0xE / push ecx / mov
# ecx,edi / call Font_init), resume 0x428AFC. Entry: ecx="Alpha Centauri" ptr,
# edi=Font @credits+0x1C48, "push 1" (flags) already done. 14 -> 14*g/16 (35 @4K).
# Same Font measures AND draws -> measure==draw holds. Scroll-anchored text ->
# no line-box nudge (scaling-text skill).
# --------------------------------------------------------------------------
THUNKS['thunk_credits_font'] = f"""
    push ecx
    call {ENSURE_SCALE}
    pop ecx
    mov eax, 14
    call {POPUP_SCALE}
    push eax                     ; size
    push ecx                     ; face name
    mov ecx, edi
    call {FONT_INIT}
    push 0x428AFC
    ret
"""

# --------------------------------------------------------------------------
# thunk_credits_scroll — CALL-helper replacing the 6-byte `mov edi,[esi+0xA14]`
# @0x428C21 in the credits draw (E8 rel32 + 1 NOP). Scroll offset = ticks*g/16
# so the px/tick rate tracks the scaled line height (time-per-line == vanilla).
# eax dead at the site; ecx/edx preserved.
# --------------------------------------------------------------------------
THUNKS['thunk_credits_scroll'] = f"""
    mov edi, [esi+0xA14]
    mov eax, [{G_SCALE}]
    cmp eax, 0x10
    jle sdone
    imul edi, eax
    sar edi, 4
sdone:
    ret
"""

# --------------------------------------------------------------------------
# thunk_credits_fade — detour 0x428CEE..0x428D49 (the whole 8-band x2px fade
# loop), resume 0x428D4A. Entry: esi=credits obj; ebx/ecx/edx/edi/eax free
# (epilogue pops restore the caller's). Reproduces vanilla exactly at g=16:
#   top band k (0..7):    y = (2k*g)>>4,        h = ((2k+2)*g)>>4 - y
#   bottom band k:        y = H - ((2k+1)*g)>>4, h = ((2k+1)*g)>>4 - ((2k-1)*g)>>4
# (g=16 -> y=2k,h=2 / y=H-1-2k,h=2 = vanilla bit-for-bit, incl. the 1-row
# bottom overhang, which scales proportionally and clips like vanilla's).
# shade = 7-k. W/H read live from the (scaled) sub-window buffer fields.
# --------------------------------------------------------------------------
THUNKS['thunk_credits_fade'] = f"""
    xor ebx, ebx
floop:
    lea eax, [ebx*2]
    call {POPUP_SCALE}
    mov edi, eax                 ; y0
    lea eax, [ebx*2+2]
    call {POPUP_SCALE}
    sub eax, edi                 ; h
    mov ecx, 7
    sub ecx, ebx
    push ecx                     ; shade
    push 0
    push eax                     ; h
    mov eax, [esi+0x16F8]
    push eax                     ; w
    push edi                     ; y
    push 0
    lea ecx, [esi+0x1678]
    call {BUFFER_CHG_COLOR3}
    lea eax, [ebx*2+1]
    call {POPUP_SCALE}
    mov edi, eax                 ; d0
    lea eax, [ebx*2-1]
    call {POPUP_SCALE}           ; d1 (k=0 -> negative, sar handles sign)
    mov edx, edi
    sub edx, eax                 ; h = d0-d1
    mov eax, [esi+0x16FC]
    neg eax                      ; H (stored negative)
    sub eax, edi                 ; y = H-d0
    mov ecx, 7
    sub ecx, ebx
    push ecx                     ; shade
    push 0
    push edx                     ; h
    mov ecx, [esi+0x16F8]
    push ecx                     ; w
    push eax                     ; y
    push 0
    lea ecx, [esi+0x1678]
    call {BUFFER_CHG_COLOR3}
    inc ebx
    cmp ebx, 8
    jl floop
    push 0x428D4A
    ret
"""

# --------------------------------------------------------------------------
# thunk_interlude_font — detour 0x45F382..0x45F39E (the 3 global-font loads +
# 4 pushes + mov ecx,esi + call Buffer_set_font), resume 0x45F39F. Entry:
# esi=window Buffer(+0x444), edi=interlude obj (LIVE), ebx=obj+0xA24 (LIVE).
# The 3 globals are config_popups' find_font picks (variant 0/1/2 rows at one
# size index, row stride 0xA0 from table base 0x93FC58). Scaled swap:
#   idx = ([G_FONT0]-base)/0xA0; native = font_size_table[idx];
#   f_v = find_font(native*g/16, v)  for v=0,1,2   (never mutate the globals —
# shared-field rule). g<=16 -> pass the globals verbatim (byte-identical).
# --------------------------------------------------------------------------
THUNKS['thunk_interlude_font'] = f"""
    call {ENSURE_SCALE}
    mov eax, [{G_SCALE}]
    cmp eax, 0x10
    jg scaled
    push 0
    mov eax, [{G_FONT2}]
    push eax
    mov eax, [{G_FONT1}]
    push eax
    mov eax, [{G_FONT0}]
    push eax
    jmp docall
scaled:
    push ebx
    mov eax, [{G_FONT0}]
    sub eax, {FONT_TABLE_V0}
    xor edx, edx
    mov ecx, 0xA0
    div ecx                      ; eax = size row index
    mov eax, [eax*4+{FONT_SIZE_TABLE}]
    call {POPUP_SCALE}
    mov ebx, eax                 ; scaled size
    push 0
    push ebx
    call {FIND_FONT}
    add esp, 8
    mov [{V['g_il_f0']}], eax
    push 1
    push ebx
    call {FIND_FONT}
    add esp, 8
    mov [{V['g_il_f1']}], eax
    push 2
    push ebx
    call {FIND_FONT}
    add esp, 8
    mov [{V['g_il_f2']}], eax
    pop ebx
    push 0
    mov eax, [{V['g_il_f2']}]
    push eax
    mov eax, [{V['g_il_f1']}]
    push eax
    mov eax, [{V['g_il_f0']}]
    push eax
docall:
    mov ecx, esi
    call {BUFFER_SET_FONT}
    push 0x45F39F
    ret
"""

# --------------------------------------------------------------------------
# thunk_interlude_clamp — detour 0x45F49A..0x45F4A3 (cmp eax,0x19 / jl / mov
# eax,0x19), resume 0x45F4A4. Entry: eax = text rect left. L = min(L, 25*g/16)
# (identity at g=16). ecx dead at resume. g guaranteed computed (font thunk
# ran earlier in this same function).
# --------------------------------------------------------------------------
THUNKS['thunk_interlude_clamp'] = f"""
    mov ecx, eax
    mov eax, 25
    call {POPUP_SCALE}
    cmp ecx, eax
    jl keep
    mov ecx, eax
keep:
    mov eax, ecx
    push 0x45F4A4
    ret
"""

# --------------------------------------------------------------------------
# thunk_interlude_nudge — detour 0x45F4D0..0x45F4E4 (the INTERLUDE21/22
# T+=0x32 / B+=0x32 block), resume 0x45F4E5. Entry: esi = text RECT (obj+0xA14).
# 50 -> 50*g/16 (identity at g=16). eax/ecx/edx dead at resume.
# --------------------------------------------------------------------------
THUNKS['thunk_interlude_nudge'] = f"""
    mov eax, 50
    call {POPUP_SCALE}
    add [esi+4], eax
    add [esi+0xC], eax
    push 0x45F4E5
    ret
"""

# --------------------------------------------------------------------------
# thunk_credits_music — call_target_redirect @0x428B64 (group
# credits_menu_music_dedupe). load_credits_a plays "fx\opening menu.wav" into
# its private Wave 0x703E30 (ecx at the site) WITHOUT stopping the main menu's
# copy already streaming through 0x945780 (top_menu 0x58E3D2) -> two layered
# instances of the menu track. Fix: if the menu wave is already playing, skip
# the credits play (one continuous track menu -> credits); else vanilla play
# (end-of-game / in-game credits paths keep their music). Wave_is_playing is
# null-safe on a never-loaded wave; both fns are thiscall with no stack args,
# and the caller ignores eax.
# --------------------------------------------------------------------------
THUNKS['thunk_credits_music'] = f"""
    push ecx
    mov ecx, {G_MENU_MUSIC_WAVE}
    call {WAVE_IS_PLAYING}
    pop ecx
    test eax, eax
    jnz already
    push {WAVE_PLAY_2}
    ret
already:
    ret
"""

# --------------------------------------------------------------------------

ks = Ks(KS_ARCH_X86, KS_MODE_32)
order = [n for n in LAYOUT if n in THUNKS]
prev_end = None
for name in order:
    off = LAYOUT[name]
    va = V[name]
    stripped = "\n".join(l.split(';')[0] for l in THUNKS[name].splitlines())
    enc, _ = ks.asm(stripped, va)
    b = bytes(enc)
    end = off + len(b)
    nxt = min((o for o in LAYOUT.values() if o > off), default=None)
    fit = 'OK' if nxt is None or end <= nxt else f'*** OVERFLOWS next slot 0x{nxt:X} ***'
    print(f"{name} @ pcave2+0x{off:X} (VA 0x{va:X})  len={len(b)} (0x{len(b):X})  ends 0x{end:X}  {fit}")
    print(" ".join(f"{x:02X}" for x in b))
    print()

# site helper bytes
def rel32(src_va, dst_va, op=b'\xE8'):
    return op + (dst_va - (src_va + 5)).to_bytes(4, 'little', signed=True)

def show_site(label, va, total_len, dst, op=b'\xE8'):
    body = rel32(va, dst, op)
    body += b'\x90' * (total_len - len(body))
    print(f"site {label} @ 0x{va:X} len={total_len}: {' '.join(f'{x:02X}' for x in body)}")

show_site('GraphicWin_load_pcx.pcx_fullscreen', 0x5D552E, 5,  V['thunk_pcx_fullscreen'])
show_site('load_credits_b.pcx_fullscreen',      0x45F3C2, 5,  V['thunk_pcx_fullscreen'])
show_site('load_credits_a.subwin  (JMP)',       0x428A8C, 0x32, V['thunk_credits_subwin'], b'\xE9')
show_site('load_credits_a.font    (JMP)',       0x428AF2, 10, V['thunk_credits_font'], b'\xE9')
show_site('credits_draw.scroll    (CALL)',      0x428C21, 6,  V['thunk_credits_scroll'])
show_site('credits_draw.fade      (JMP)',       0x428CEE, 0x5C, V['thunk_credits_fade'], b'\xE9')
show_site('load_credits_b.font    (JMP)',       0x45F382, 0x1D, V['thunk_interlude_font'], b'\xE9')
show_site('load_credits_b.clamp   (JMP)',       0x45F49A, 10, V['thunk_interlude_clamp'], b'\xE9')
show_site('load_credits_b.nudge   (JMP)',       0x45F4D0, 21, V['thunk_interlude_nudge'], b'\xE9')
show_site('load_credits_a.music   (CALL)',      0x428B64, 5,  V['thunk_credits_music'])
