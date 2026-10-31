# Assembles the N2 faction-connector graphic-upscale thunks (v2: thicken + chevron magnify).
# v1 only scaled the primitive COORDS (skeleton lands in scaled positions) but left strokes 1px
# and never touched the arrowhead sprite. v2:
#   thunk_conn_vline/hline  : scale the 3 coords, then draw the line t=round(g/16) px THICK
#                             (t adjacent passes, centered on the scaled centerline).
#   thunk_conn_pixel        : scale x,y, then fill a t x t block (the elbow corners) via t hlines.
#   thunk_conn_chevron      : NEW. wraps the connector's 2 Sprite_blit_scaled_core calls: popup_scale
#                             x,y AND set the engine scale globals (0x696D18/1C = g_popup_scale_num/16)
#                             so the arrowhead sprite EXPANDS 2.5x, then restore the globals. The
#                             chevron is mid-buffer so the engine NN-enlarge's documented 1-row
#                             overrun cannot reach past the dest allocation -> no OOB at non-4K.
# Baked absolute addrs at the fixed pcave2 VAs (regen if a cave offset moves), same pattern as
# assemble_box_devfill.py / assemble_resampler.py.
# Every thunk gates on g_popup_scale_num: g<=16 tail-jumps the engine primitive with the caller's own args
# (fix 10, 2026-10-18; was cmp [ScreenWidth],0x400 -- which drew the scaled path at g=16 on 1280..1366-wide screens).
import keystone, capstone
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
SYM = dict(
    g_popup_scale_num       = 0x00668740,
    popup_scale             = 0x00668750,
    Buffer_vline_2          = 0x005E1BF0,
    Buffer_hline_2          = 0x005E1A80,
    Buffer_put_pixel        = 0x005E2330,
    Sprite_blit_scaled_core = 0x005E4B9A,
    SCALE_NUM_G             = 0x00696D18,
    SCALE_DEN_G             = 0x00696D1C,
    g_fan_top               = 0xA0C000 + 0x1F60,   # native fan-vline top y (set by fan_vline thunk); moved past the bigger Bresenham fan_tick
    g_fan_bot               = 0xA0C000 + 0x1F64,   # native fan-vline bottom y
)
# Repacked 2026-06-26: the Bresenham diag/fan_tick are ~254B each (was ~143/180), so the old 0x80/0xC0
# slots no longer fit. Tight layout below keeps everything below the g_fan_top/g_fan_bot globals (0x1F40).
# Stale thunk_conn_hline_row slot (0x1C00, thunk removed in v2.5) reclaimed. Moving diag/fan_* changes their
# VAs -> site rel32s recompute from the symbol offsets in patches.yaml (must be kept in sync) and each thunk's
# internal call rel32s recompute here; pixel stays at 0x1B00 so fan_tick's baked `push thunk_conn_pixel` holds.
OFFS = dict(thunk_conn_vline=0x1A00, thunk_conn_hline=0x1A80,
            thunk_conn_pixel=0x1B00, thunk_conn_chevron=0x1B80,
            thunk_conn_diag=0x1C00,
            thunk_conn_fan_vline=0x1D00, thunk_conn_fan_row=0x1D90,
            thunk_conn_fan_tick=0x1E20)

S = SYM
# The lo-res gate, `cmp dword ptr [g_popup_scale_num], 0x10`, in its 10-byte imm32 encoding (81 3D disp32 imm32):
# keystone would pick the 7-byte imm8 form (83 3D), shifting every byte after it; the imm32 form keeps each thunk
# the length and layout of its former `cmp [ScreenWidth], 0x400` gate (only the 8 operand bytes change).
G_GATE = (".byte 0x81, 0x3D, " + ", ".join(f"{b:#04x}" for b in S['g_popup_scale_num'].to_bytes(4, 'little'))
          + ", 0x10, 0x00, 0x00, 0x00")

# --- vline: thiscall(ecx=buf, x@+4, y0@+8, y1@+c, color@+10); RET 0x10. Thicken along X. ---
vline = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_vline_2']:#x}
    ret
hi:
    mov  eax, [esp+4]
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    mov  eax, [esp+0xc]
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    push ebp
    mov  ebp, esp
    push esi
    push edi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  edi, eax
    dec  eax
    shr  eax, 1
    sub  [ebp+8], eax
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_vline_2']:#x}
    inc  dword ptr [ebp+8]
    dec  edi
    jnz  lp
    pop  edi
    pop  esi
    pop  ebp
    ret  0x10
"""

# --- hline: thiscall(ecx=buf, x0@+4, x1@+8, y@+c, color@+10); RET 0x10. Thicken along Y. ---
hline = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_hline_2']:#x}
    ret
hi:
    mov  eax, [esp+4]
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    mov  eax, [esp+0xc]
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    push ebp
    mov  ebp, esp
    push esi
    push edi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  edi, eax
    dec  eax
    shr  eax, 1
    sub  [ebp+0x10], eax
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_hline_2']:#x}
    inc  dword ptr [ebp+0x10]
    dec  edi
    jnz  lp
    pop  edi
    pop  esi
    pop  ebp
    ret  0x10
"""

# --- hline_row: like hline, for the 2 INTO-ROW branches. The native branch starts at x0=iVar5+2 while the
#     vertical fan line / riser is at iVar5 (bridged natively by the +1 tick pixel); independent popup_scale
#     of those 1px steps opens a ~2.5px gap at the LEFT (vertical-line) junction. Fix: pre-subtract 2 from x0
#     so it scales to popup_scale(iVar5) = exactly the vertical line's column. Also extend x1 by t to tuck
#     under the arrowhead base on the right (harmless overlap, arrow drawn on top). ---
hline_row = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_hline_2']:#x}
    ret
hi:
    mov  eax, [esp+4]
    sub  eax, 2
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    mov  eax, [esp+0xc]
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    push ebp
    mov  ebp, esp
    push esi
    push edi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  edi, eax
    add  [ebp+0xc], edi
    dec  eax
    shr  eax, 1
    sub  [ebp+0x10], eax
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_hline_2']:#x}
    inc  dword ptr [ebp+0x10]
    dec  edi
    jnz  lp
    pop  edi
    pop  esi
    pop  ebp
    ret  0x10
"""

# --- pixel: thiscall(ecx=buf, x@+4, y@+8, color@+c); RET 0xC. Fill t x t block via t hlines. ---
pixel = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_put_pixel']:#x}
    ret
hi:
    mov  eax, [esp+4]
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    push ebp
    mov  ebp, esp
    sub  esp, 8
    push esi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  [ebp-8], eax
    mov  edx, eax
    dec  edx
    shr  edx, 1
    sub  [ebp+8], edx
    sub  [ebp+0xc], edx
    mov  edx, [ebp+8]
    add  edx, eax
    dec  edx
    mov  [ebp-4], edx
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp-4]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_hline_2']:#x}
    inc  dword ptr [ebp+0xc]
    dec  dword ptr [ebp-8]
    jnz  lp
    pop  esi
    mov  esp, ebp
    pop  ebp
    ret  0xC
"""

# --- chevron: thiscall(ecx=src, dest@+4, key@+8, x@+c, y@+10); RET 0x10. ---
# scale x,y; set scale globals to g_popup_scale_num/16 so the sprite expands 2.5x; restore.
chevron = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Sprite_blit_scaled_core']:#x}
    ret
hi:
    mov  eax, [esp+0xc]
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    mov  eax, [esp+0x10]
    call {S['popup_scale']:#x}
    mov  [esp+0x10], eax
    push ebp
    mov  ebp, esp
    mov  eax, [{S['SCALE_NUM_G']:#x}]
    push eax
    mov  eax, [{S['SCALE_DEN_G']:#x}]
    push eax
    mov  eax, [{S['g_popup_scale_num']:#x}]
    mov  [{S['SCALE_NUM_G']:#x}], eax
    mov  dword ptr [{S['SCALE_DEN_G']:#x}], 0x10
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    call {S['Sprite_blit_scaled_core']:#x}
    pop  eax
    mov  [{S['SCALE_DEN_G']:#x}], eax
    pop  eax
    mov  [{S['SCALE_NUM_G']:#x}], eax
    pop  ebp
    ret  0x10
"""

# --- diag: CHAMFER renderer for the 3 L-corner pixels (single top 0x48993e, single bottom 0x489953, multi
#     trunk corner 0x48981f). Native corner = a 45-deg "\" bevel: a horizontal line ends at (cx-1,cy-1), a corner
#     pixel at (cx,cy), the perpendicular line starts at (cx+1,cy+1). FAITHFUL scaled bevel = a CONNECTED staircase
#     of t x t blocks (t=round(g/16), MATCHING the line thickness) running from the scaled hline-end popup_scale(
#     cx-1,cy-1) to the scaled perpendicular-start popup_scale(cx+1,cy+1).
#     WHY BRESENHAM (not 3 scaled samples): popup_scale FLOORS independently per axis, so at low g the two scaled
#     end-points are e.g. dx=2,dy=3 apart -- sampling only the 3 native positions skips an output pixel (Frida @1920
#     g=22: top corner emitted y=195,196,198 -- 197 gone) so the bevel breaks into disconnected pixels = "corner
#     vanished". And forcing the block size up to ceil(g/16) to bridge the gap (the FAILED 2026-06-26 ceil attempt)
#     makes the corner THICKER than the 1px lines = a deformed lump. The fix is to keep block size = t (= line
#     thickness, no deformation) and plot EVERY output pixel along the diagonal via integer Bresenham (add/sub only,
#     no divide) -> connected at any scale. No-op-equivalent at 4K/1600 (t>=2 -> the same solid chamfer the user
#     confirmed) and correct 1px diagonal at 1920/1280 (t=1). sx=+1 always (x0<x1); sy derived from sign(y1-y0) so
#     the SAME loop serves "\" (diag) and is reused by fan_tick for "/". Locals: -4 buf -8 t -c c=(t-1)/2 -10 x0
#     -14 y0 -18 x1 -1c y1 -20 dx -24 dy(=-|y1-y0|) -28 err -2c sy. ---
diag = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_put_pixel']:#x}
    ret
hi:
    push ebp
    mov  ebp, esp
    sub  esp, 0x2c
    push esi
    push edi
    push ebx
    mov  esi, ecx
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  [ebp-8], eax
    dec  eax
    shr  eax, 1
    mov  [ebp-0xc], eax
    mov  eax, [ebp+8]
    dec  eax
    call {S['popup_scale']:#x}
    mov  [ebp-0x10], eax
    mov  eax, [ebp+0xc]
    dec  eax
    call {S['popup_scale']:#x}
    mov  [ebp-0x14], eax
    mov  eax, [ebp+8]
    inc  eax
    call {S['popup_scale']:#x}
    mov  [ebp-0x18], eax
    mov  eax, [ebp+0xc]
    inc  eax
    call {S['popup_scale']:#x}
    mov  [ebp-0x1c], eax
    mov  eax, [ebp-0x18]
    sub  eax, [ebp-0x10]
    mov  [ebp-0x20], eax
    mov  eax, [ebp-0x1c]
    sub  eax, [ebp-0x14]
    mov  edx, 1
    cmp  eax, 0
    jge  dpos
    mov  edx, -1
dpos:
    mov  [ebp-0x2c], edx
    imul eax, edx
    neg  eax
    mov  [ebp-0x24], eax
    mov  eax, [ebp-0x20]
    add  eax, [ebp-0x24]
    mov  [ebp-0x28], eax
bloop:
    mov  ebx, [ebp-0x14]
    sub  ebx, [ebp-0xc]
    mov  edi, [ebp-8]
rloop:
    mov  eax, [ebp-0x10]
    sub  eax, [ebp-0xc]
    mov  edx, eax
    add  edx, [ebp-8]
    dec  edx
    push dword ptr [ebp+0x10]
    push ebx
    push edx
    push eax
    mov  ecx, esi
    call {S['Buffer_hline_2']:#x}
    inc  ebx
    dec  edi
    jnz  rloop
    mov  eax, [ebp-0x10]
    cmp  eax, [ebp-0x18]
    jne  adv
    mov  eax, [ebp-0x14]
    cmp  eax, [ebp-0x1c]
    je   bdone
adv:
    mov  eax, [ebp-0x28]
    add  eax, eax
    cmp  eax, [ebp-0x24]
    jl   noX
    mov  edx, [ebp-0x28]
    add  edx, [ebp-0x24]
    mov  [ebp-0x28], edx
    inc  dword ptr [ebp-0x10]
noX:
    cmp  eax, [ebp-0x20]
    jg   noY
    mov  edx, [ebp-0x28]
    add  edx, [ebp-0x20]
    mov  [ebp-0x28], edx
    mov  edx, [ebp-0x2c]
    add  [ebp-0x14], edx
noY:
    jmp  bloop
bdone:
    pop  ebx
    pop  edi
    pop  esi
    mov  esp, ebp
    pop  ebp
    ret  0xC
"""

# --- fan_vline: the MULTI-row fan vertical line (site 0x489852), drawn ONCE before the per-row loop. Stores its
#     NATIVE span [y0,y1] in g_fan_top/g_fan_bot so the per-row tick/branch thunks can tell the L-corner rows
#     (0 and 6, whose y falls OUTSIDE this span) from the middle T-junction rows. Then draws plain (scale +
#     thicken, NO extension -- the corner rows are bevelled by the tick). ---
fan_vline = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_vline_2']:#x}
    ret
hi:
    mov  eax, [esp+8]
    mov  [{S['g_fan_top']:#x}], eax
    mov  eax, [esp+0xc]
    mov  [{S['g_fan_bot']:#x}], eax
    mov  eax, [esp+4]
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    mov  eax, [esp+0xc]
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    push ebp
    mov  ebp, esp
    push esi
    push edi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  edi, eax
    dec  eax
    shr  eax, 1
    sub  [ebp+8], eax
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_vline_2']:#x}
    inc  dword ptr [ebp+8]
    dec  edi
    jnz  lp
    pop  edi
    pop  esi
    pop  ebp
    ret  0x10
"""

# --- fan_row: the MULTI-row per-row BRANCH hline (site 0x4898b2). MIDDLE rows (y inside [g_fan_top,g_fan_bot])
#     are T-junctions -> pre-subtract 2 from x0 to reach the continuous fan line. CORNER rows (y outside the
#     span = rows 0/6) are bevelled by the tick staircase, so x0 stays put (plain). x1 extended by t (arrow
#     tuck) in all cases. ---
fan_row = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_hline_2']:#x}
    ret
hi:
    mov  eax, [esp+0xc]
    cmp  eax, [{S['g_fan_top']:#x}]
    jl   nosub
    cmp  eax, [{S['g_fan_bot']:#x}]
    jg   nosub
    sub  dword ptr [esp+4], 2
nosub:
    mov  eax, [esp+4]
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    mov  eax, [esp+0xc]
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    push ebp
    mov  ebp, esp
    push esi
    push edi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  edi, eax
    add  [ebp+0xc], edi
    dec  eax
    shr  eax, 1
    sub  [ebp+0x10], eax
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_hline_2']:#x}
    inc  dword ptr [ebp+0x10]
    dec  edi
    jnz  lp
    pop  edi
    pop  esi
    pop  ebp
    ret  0x10
"""

# --- fan_tick: the MULTI-row per-row TICK pixel (site 0x48989d). MIDDLE rows (cy inside the fan span) -> plain
#     t x t block (tail to thunk_conn_pixel). CORNER rows -> the SAME connected-Bresenham bevel as thunk_conn_diag,
#     direction from the span: row 0 (cy < g_fan_top) -> dir=-1 ("/"), row 6 (cy > g_fan_bot) -> dir=+1 ("\").
#     Endpoints x0=ps(cx-1),y0=ps(cy-dir),x1=ps(cx+1),y1=ps(cy+dir); sy=sign(y1-y0). Same t-thick connected
#     staircase -> no gap + no deformation at t=1 (1920). Locals identical to diag (-2c holds dir then sy). ---
fan_tick = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_put_pixel']:#x}
    ret
hi:
    mov  eax, [esp+8]
    cmp  eax, [{S['g_fan_top']:#x}]
    jl   corner
    cmp  eax, [{S['g_fan_bot']:#x}]
    jg   corner
    push {PCAVE2 + OFFS['thunk_conn_pixel']:#x}
    ret
corner:
    push ebp
    mov  ebp, esp
    sub  esp, 0x2c
    push esi
    push edi
    push ebx
    mov  esi, ecx
    mov  eax, [ebp+0xc]
    mov  edx, 1
    cmp  eax, [{S['g_fan_top']:#x}]
    jge  yd
    mov  edx, -1
yd:
    mov  [ebp-0x2c], edx
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  [ebp-8], eax
    dec  eax
    shr  eax, 1
    mov  [ebp-0xc], eax
    mov  eax, [ebp+8]
    dec  eax
    call {S['popup_scale']:#x}
    mov  [ebp-0x10], eax
    mov  eax, [ebp+0xc]
    sub  eax, [ebp-0x2c]
    call {S['popup_scale']:#x}
    mov  [ebp-0x14], eax
    mov  eax, [ebp+8]
    inc  eax
    call {S['popup_scale']:#x}
    mov  [ebp-0x18], eax
    mov  eax, [ebp+0xc]
    add  eax, [ebp-0x2c]
    call {S['popup_scale']:#x}
    mov  [ebp-0x1c], eax
    mov  eax, [ebp-0x18]
    sub  eax, [ebp-0x10]
    mov  [ebp-0x20], eax
    mov  eax, [ebp-0x1c]
    sub  eax, [ebp-0x14]
    mov  edx, 1
    cmp  eax, 0
    jge  fpos
    mov  edx, -1
fpos:
    mov  [ebp-0x2c], edx
    imul eax, edx
    neg  eax
    mov  [ebp-0x24], eax
    mov  eax, [ebp-0x20]
    add  eax, [ebp-0x24]
    mov  [ebp-0x28], eax
bloop:
    mov  ebx, [ebp-0x14]
    sub  ebx, [ebp-0xc]
    mov  edi, [ebp-8]
rloop:
    mov  eax, [ebp-0x10]
    sub  eax, [ebp-0xc]
    mov  edx, eax
    add  edx, [ebp-8]
    dec  edx
    push dword ptr [ebp+0x10]
    push ebx
    push edx
    push eax
    mov  ecx, esi
    call {S['Buffer_hline_2']:#x}
    inc  ebx
    dec  edi
    jnz  rloop
    mov  eax, [ebp-0x10]
    cmp  eax, [ebp-0x18]
    jne  adv
    mov  eax, [ebp-0x14]
    cmp  eax, [ebp-0x1c]
    je   bdone
adv:
    mov  eax, [ebp-0x28]
    add  eax, eax
    cmp  eax, [ebp-0x24]
    jl   noX
    mov  edx, [ebp-0x28]
    add  edx, [ebp-0x24]
    mov  [ebp-0x28], edx
    inc  dword ptr [ebp-0x10]
noX:
    cmp  eax, [ebp-0x20]
    jg   noY
    mov  edx, [ebp-0x28]
    add  edx, [ebp-0x20]
    mov  [ebp-0x28], edx
    mov  edx, [ebp-0x2c]
    add  [ebp-0x14], edx
noY:
    jmp  bloop
bdone:
    pop  ebx
    pop  edi
    pop  esi
    mov  esp, ebp
    pop  ebp
    ret  0xC
"""

# --- vline_riser: the SINGLE-elbow riser (site 0x48996e). Its top (y0=local_8+2) and bottom (y1=rowY-2) sit
#     2px inside the two corners; the from-play/into-row hlines meet at local_8 / rowY. Pre-extend y0 UP by 2
#     and y1 DOWN by 2 so the riser reaches popup_scale(local_8) and popup_scale(rowY) -> clean square corners
#     with the two hlines (which reach the riser column via their own -2/+2 fixes). Thicken in X as usual. ---
vline_riser = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_vline_2']:#x}
    ret
hi:
    mov  eax, [esp+4]
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    sub  eax, 2
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    mov  eax, [esp+0xc]
    add  eax, 2
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    push ebp
    mov  ebp, esp
    push esi
    push edi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  edi, eax
    dec  eax
    shr  eax, 1
    sub  [ebp+8], eax
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_vline_2']:#x}
    inc  dword ptr [ebp+8]
    dec  edi
    jnz  lp
    pop  edi
    pop  esi
    pop  ebp
    ret  0x10
"""

# --- hline_fromplay: the SINGLE-elbow top hline from the PLAY button (site 0x489922). Its right end x1=iVar5-2
#     sits 2px left of the riser at iVar5; pre-add 2 so it scales to popup_scale(iVar5) = the riser column. ---
hline_fromplay = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_hline_2']:#x}
    ret
hi:
    mov  eax, [esp+4]
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    add  eax, 2
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    mov  eax, [esp+0xc]
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    push ebp
    mov  ebp, esp
    push esi
    push edi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  edi, eax
    dec  eax
    shr  eax, 1
    sub  [ebp+0x10], eax
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_hline_2']:#x}
    inc  dword ptr [ebp+0x10]
    dec  edi
    jnz  lp
    pop  edi
    pop  esi
    pop  ebp
    ret  0x10
"""

# --- hline_stub: the MULTI-row fan top stub (site 0x48983a). Its left end x0=midX+2 sits 2px right of the
#     trunk at midX; pre-subtract 2 so it scales to popup_scale(midX) = the trunk column. x1 (=iVar5) meets
#     the continuous fan vline, so it is NOT extended (extending would poke past the vline). ---
hline_stub = f"""
    {G_GATE}   ; cmp dword ptr [g_popup_scale_num], 0x10 (imm32 form) -- g<=16 -> native
    jg   hi
    push {S['Buffer_hline_2']:#x}
    ret
hi:
    mov  eax, [esp+4]
    sub  eax, 2
    call {S['popup_scale']:#x}
    mov  [esp+4], eax
    mov  eax, [esp+8]
    call {S['popup_scale']:#x}
    mov  [esp+8], eax
    mov  eax, [esp+0xc]
    call {S['popup_scale']:#x}
    mov  [esp+0xc], eax
    push ebp
    mov  ebp, esp
    push esi
    push edi
    mov  eax, [{S['g_popup_scale_num']:#x}]
    add  eax, 0xf
    shr  eax, 4
    mov  edi, eax
    dec  eax
    shr  eax, 1
    sub  [ebp+0x10], eax
    mov  esi, ecx
lp:
    push dword ptr [ebp+0x14]
    push dword ptr [ebp+0x10]
    push dword ptr [ebp+0xc]
    push dword ptr [ebp+8]
    mov  ecx, esi
    call {S['Buffer_hline_2']:#x}
    inc  dword ptr [ebp+0x10]
    dec  edi
    jnz  lp
    pop  edi
    pop  esi
    pop  ebp
    ret  0x10
"""

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

def build(name, src):
    base = PCAVE2 + OFFS[name]
    clean = "\n".join(l.split(";",1)[0].rstrip() for l in src.splitlines() if l.split(";",1)[0].strip())
    enc,_ = ks.asm(clean, base)
    blob = bytes(enc)
    end = OFFS[name] + len(blob)
    nxt = min(v for v in OFFS.values() if v > OFFS[name]) if any(v>OFFS[name] for v in OFFS.values()) else 0x2000
    ok = end <= nxt
    print(f"\n==== {name}: {len(blob)} bytes @ {base:#x} (off {OFFS[name]:#x}) -> ends off {end:#x}; next {nxt:#x}; fits={ok}")
    bad=0
    for ins in md.disasm(blob, base):
        if ins.mnemonic in ("int3","(bad)"): bad+=1
        print(f"   {ins.address:#08x}: {ins.bytes.hex():<18} {ins.mnemonic} {ins.op_str}")
    assert bad==0 and ok, f"{name} bad={bad} fits={ok}"
    print("   BYTES: " + " ".join(f"{b:02X}" for b in blob))
    return blob

srcs = {"thunk_conn_vline":vline,"thunk_conn_hline":hline,"thunk_conn_pixel":pixel,
        "thunk_conn_chevron":chevron,"thunk_conn_diag":diag,
        "thunk_conn_fan_vline":fan_vline,"thunk_conn_fan_row":fan_row,"thunk_conn_fan_tick":fan_tick}
for n in ("thunk_conn_vline","thunk_conn_hline","thunk_conn_pixel","thunk_conn_chevron",
          "thunk_conn_diag","thunk_conn_fan_vline","thunk_conn_fan_row","thunk_conn_fan_tick"):
    build(n, srcs[n])
print("\nall assembled clean")
