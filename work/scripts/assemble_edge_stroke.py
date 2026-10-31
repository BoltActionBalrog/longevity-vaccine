# Regenerates the 1-px EDGE STROKE / corner-notch thunks of wave-2 W2D (2026-10-25; pcave2 region 0x37000..0x37FFF;
# laws scaling_laws.btn_edge_stroke / edge_stroke_colour / btn_edge_probe / btn_edge_band / box_edge_strokes /
# faction_row_face / filedlg_btn_pair; guards tests\test_scaling_edge_stroke.py + tests\test_edge_stroke_asm_parity.py).
#
# F39 -- the hover (state 1) face of a default 9-slice FlatButton carries a 1-px E0 outline; the 2D zoom's centre NN
# split it unevenly (1 | 2 at g 24, 2 | 3 at g 40) and thunk_fe_pair_remap restriped it E0 / E1.  Two thunks:
#   t_btn_edgeprobe (NEW): thunk_btn_2dscale's `call thunk_btn_bandstripe` (the stretch) is retargeted here.  It runs
#       on the NATIVE composed face (the stretch has not run): zero g_btn_tileH (devfill's "ran this compose" signal)
#       and the edge mask, and -- only when thunk_btn_fillcap captured a 9-slice body this compose -- probe the four
#       edges (edge_stroke_colour at the middle column / art row) into g_btn_edge_mask / g_btn_edge_c0..c3; then
#       `push thunk_btn_bandstripe / ret` with the caller's frame untouched (W3B: `push t_rsb_zoom / ret`, which forwards
#       every non-rail button to thunk_btn_bandstripe -- see PROBE_TAIL).  eax / ecx / edx clobbered (the stretch
#       clobbers them too); ebx / esi / edi / ebp preserved.
#   t_btn_edgeband (NEW): t_ntw_nostripe's tail `push thunk_btn_ringfix / ret` is retargeted here.  CALLs
#       thunk_btn_ringfix (stripes = devfill + litcorner + the pair remap, then the box-face ring), then, when the
#       probe found a stroke AND devfill ran (g_btn_tileH = D > 0; the BaseWin early-out never reaches devfill), draws
#       a K = btn_edge_stroke(g) band of each stroke colour on rows [0, D), every non-key pixel (the s x s notches,
#       s == K, stay key).  Clears the mask.  Inside thunk_btn_2dscale's pushad (esi = button, the rest free).
#
# F40b -- the CHOOSE YOUR FACTIONS name rows (FactionPickWin vtbl+0x2C 0x48A840: Buffer_box_sprite @0x48A892 at the
# DEVICE rect with 1-px strips): 1 x 1 notches and a 1-px hover ring at every g.  Four thunks:
#   t_fac_rowbox (NEW, call-redirect @0x48A892, a Buffer_box_sprite drop-in, RET 8): g > 16 and s <= 4 and the rect
#       inside the canvas, >= 2s each way: save the four s x s corner squares (the background the vanilla notch shows)
#       into g_fr_save, read the set's art once (keyed corners, strokes), CALL Buffer_box_sprite, draw the K band of
#       each stroke (solid), put the saved background back in the keyed corner squares, set g_fr_pending -- all
#       BEFORE draw_item writes the row's text (vanilla's order: the text lands on the stroke; audit condition 2).
#       Gate failed: tail-jump Buffer_box_sprite (the native draw).
#   t_fac_item_pre (NEW): t_lb_item_stripes' `call ListBox_draw_item` is retargeted here: clear g_fr_pending, then
#       tail-jump ListBox_draw_item (an item that never reaches the painter -- index -1, past the count -- leaves no
#       stale pending for the post).
#   t_fac_rowpost (NEW): t_lb_item_stripes' `call t_lbi_restripe_ph` is retargeted here (same contract, RET 0x10):
#       the restripe (which splits a solid E0 band into E0 / E1 and puts the restored corners on the law), then
#       (pending) inside each band the stroke's pair mate back to the stroke colour; the text ink is not touched.
#   t_fac_sqcopy (NEW): stdcall(src, src_pitch, dst, dst_pitch, s) RET 0x14 -- the s x s save / restore copy.
#
# F41 -- thunk_filedlg_rects v2 (RELOCATED from 0x2370, 48 -> 112 B; the call-redirect @0x40771B follows the symbol):
#   v1's x g/16 of the 17-dword array, then the OK / CANCEL pair law filedlg_btn_pair (one width, the odd px to the
#   seam; B = T + fl(22g/16) for both).
#
# Usage: py assemble_edge_stroke.py -> byte templates for patches.yaml (+ round-trip / slot checks).
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
KEY = 9
PASS = 7

SLOTS = {                                   # name: (offset, end)  -- W2D region 0x37000..0x37FFF
    "t_btn_edgeprobe": (0x37000, 0x37140),
    "t_btn_edgeband": (0x37140, 0x37280),
    "t_fac_item_pre": (0x37280, 0x37290),
    "t_fac_sqcopy": (0x37290, 0x372C0),
    "t_fac_rowbox": (0x372C0, 0x37800),
    "thunk_filedlg_rects": (0x37800, 0x37880),
    "t_fac_rowpost": (0x37C40, 0x37F00),     # after thunk_faction_dropimg v3 (0x37900..0x37C36, assemble_dropdither.py)
}
CELLS = {                                   # 4-byte cells (zero-init), W2D region
    "g_btn_edge_mask": 0x37F00, "g_btn_edge_c0": 0x37F04, "g_btn_edge_c1": 0x37F08, "g_btn_edge_c2": 0x37F0C,
    "g_btn_edge_c3": 0x37F10, "g_fr_pending": 0x37F20, "g_fr_buf": 0x37F24,
    "g_fr_rect": 0x37F30,                   # 16 B: L, T, R, B
    "g_fr_save": 0x37F40,                   # 64 B: 4 corners x 4 rows x 4 bytes (s <= 4)
    "g_fr_cmask": 0x37F80, "g_fr_bmask": 0x37F84, "g_fr_bc0": 0x37F88, "g_fr_bc1": 0x37F8C, "g_fr_bc2": 0x37F90,
    "g_fr_bc3": 0x37F94,
}
CELL_LEN = {"g_fr_rect": 16, "g_fr_save": 64}

# sentinel absolutes -> yaml {abs32:} placeholders
SYMS = {n: 0x11110000 + 0x10 * i for i, n in enumerate((
    "g_popup_scale_num", "g_btn_tileH", "g_btn_fill_sprite", "g_btn_nativeW", "g_btn_nativeH",
    "thunk_btn_bandstripe", "Buffer_box_sprite", "FileDlg_build_widgets", "ListBox_draw_item", "t_rsb_zoom",
    *CELLS))}
# sentinel CALL targets -> {rel32:} placeholders
CALLS = {n: 0x22220000 + 0x10 * i for i, n in enumerate((
    "thunk_btn_ringfix", "t_lbi_restripe_ph", "popup_scale", "t_fac_sqcopy", "Buffer_box_sprite"))}


def S(name):
    return f"{SYMS[name]:#x}"


def C(name):
    return f"{CALLS[name]:#x}"


CHK = f"""
chk:
    mov  al, byte ptr [esi]
    cmp  al, {KEY}
    je   chk_no
    cmp  al, byte ptr [esi+ebx]
    je   chk_no
    cmp  al, byte ptr [esi+ebx*2]
    je   chk_no
    clc
    ret
chk_no:
    stc
    ret
"""


# 2026-10-25 W3B (rail scrollbar rework): the probe's tail enters t_rsb_zoom (assemble_rail_sym.py) instead of the
# stretch.  t_rsb_zoom zooms a rail-family bar's two arrows itself (plate on the grip span) and tail-jumps
# thunk_btn_bandstripe -- the stretch -- for every other button, with the caller's frame and registers as they came:
# the chain is 2dscale -> t_btn_edgeprobe (the native face, every button) -> t_rsb_zoom -> thunk_btn_bandstripe.
PROBE_TAIL = "t_rsb_zoom"


def asm_edgeprobe():
    return f"""
    xor  eax, eax
    mov  dword ptr [{S('g_btn_tileH')}], eax
    mov  dword ptr [{S('g_btn_edge_mask')}], eax
    cmp  dword ptr [{S('g_btn_fill_sprite')}], eax
    je   go
    push ebx
    push esi
    push edi
    push ebp
    mov  edi, dword ptr [esi+0x498]
    test edi, edi
    je   back
    mov  ebp, dword ptr [esi+0x8ec]
    test ebp, ebp
    jle  back
    mov  ecx, dword ptr [{S('g_btn_nativeW')}]
    cmp  ecx, 6
    jl   back
    cmp  ecx, ebp
    jg   back
    mov  edx, dword ptr [{S('g_btn_fill_sprite')}]
    mov  edx, dword ptr [edx+0x1c]
    mov  eax, dword ptr [{S('g_btn_nativeH')}]
    cmp  edx, eax
    jle  aok
    mov  edx, eax
aok:
    cmp  edx, 6
    jl   back
    mov  esi, edx
    shr  esi, 1
    imul esi, ebp
    add  esi, edi
    mov  ebx, 1
    call chk
    jc   l1
    mov  byte ptr [{S('g_btn_edge_c2')}], al
    or   byte ptr [{S('g_btn_edge_mask')}], 4
l1:
    lea  esi, [esi+ecx-1]
    neg  ebx
    call chk
    jc   l2
    mov  byte ptr [{S('g_btn_edge_c3')}], al
    or   byte ptr [{S('g_btn_edge_mask')}], 8
l2:
    mov  esi, ecx
    shr  esi, 1
    add  esi, edi
    mov  ebx, ebp
    call chk
    jc   l3
    mov  byte ptr [{S('g_btn_edge_c0')}], al
    or   byte ptr [{S('g_btn_edge_mask')}], 1
l3:
    dec  edx
    imul edx, ebp
    add  esi, edx
    neg  ebx
    call chk
    jc   back
    mov  byte ptr [{S('g_btn_edge_c1')}], al
    or   byte ptr [{S('g_btn_edge_mask')}], 2
back:
    pop  ebp
    pop  edi
    pop  esi
    pop  ebx
go:
    push {S(PROBE_TAIL)}
    ret
{CHK}"""


def asm_edgeband():
    return f"""
    call {C('thunk_btn_ringfix')}
    mov  eax, dword ptr [{S('g_btn_edge_mask')}]
    test eax, eax
    je   done
    and  dword ptr [{S('g_btn_edge_mask')}], 0
    cmp  dword ptr [{S('g_popup_scale_num')}], 0x10
    jle  done
    push ebp
    mov  ebp, esp
    sub  esp, 0x18
    mov  dword ptr [ebp-0x18], eax
    mov  eax, dword ptr [{S('g_popup_scale_num')}]
    add  eax, 0xf
    sar  eax, 4
    mov  dword ptr [ebp-4], eax
    lea  ecx, [eax+eax]
    mov  eax, dword ptr [{S('g_btn_tileH')}]
    cmp  eax, ecx
    jl   out
    mov  dword ptr [ebp-8], eax
    mov  eax, dword ptr [esi+0x4c4]
    cmp  eax, ecx
    jl   out
    mov  dword ptr [ebp-0xc], eax
    mov  eax, dword ptr [esi+0x498]
    test eax, eax
    je   out
    mov  dword ptr [ebp-0x10], eax
    mov  eax, dword ptr [esi+0x8ec]
    cmp  eax, dword ptr [ebp-0xc]
    jl   out
    mov  dword ptr [ebp-0x14], eax
    test byte ptr [ebp-0x18], 1
    je   e1
    push dword ptr [ebp-4]
    push dword ptr [ebp-0xc]
    push 0
    push 0
    mov  al, byte ptr [{S('g_btn_edge_c0')}]
    call fillr
e1:
    test byte ptr [ebp-0x18], 2
    je   e2
    push dword ptr [ebp-4]
    push dword ptr [ebp-0xc]
    mov  eax, dword ptr [ebp-8]
    sub  eax, dword ptr [ebp-4]
    push eax
    push 0
    mov  al, byte ptr [{S('g_btn_edge_c1')}]
    call fillr
e2:
    test byte ptr [ebp-0x18], 4
    je   e3
    push dword ptr [ebp-8]
    push dword ptr [ebp-4]
    push 0
    push 0
    mov  al, byte ptr [{S('g_btn_edge_c2')}]
    call fillr
e3:
    test byte ptr [ebp-0x18], 8
    je   out
    push dword ptr [ebp-8]
    push dword ptr [ebp-4]
    push 0
    mov  eax, dword ptr [ebp-0xc]
    sub  eax, dword ptr [ebp-4]
    push eax
    mov  al, byte ptr [{S('g_btn_edge_c3')}]
    call fillr
out:
    mov  esp, ebp
    pop  ebp
done:
    ret
fillr:
    mov  ebx, dword ptr [esp+0x10]
    mov  edx, dword ptr [esp+8]
fr_row:
    mov  edi, edx
    imul edi, dword ptr [ebp-0x14]
    add  edi, dword ptr [ebp-0x10]
    add  edi, dword ptr [esp+4]
    mov  ecx, dword ptr [esp+0xc]
fr_px:
    cmp  byte ptr [edi], {KEY}
    je   fr_k
    mov  byte ptr [edi], al
fr_k:
    inc  edi
    dec  ecx
    jnz  fr_px
    inc  edx
    dec  ebx
    jnz  fr_row
    ret  0x10
"""


def asm_item_pre():
    return f"""
    and  dword ptr [{S('g_fr_pending')}], 0
    push {S('ListBox_draw_item')}
    ret
"""


def asm_sqcopy():
    return """
    push esi
    push edi
    cld
    mov  esi, dword ptr [esp+0xc]
    mov  edi, dword ptr [esp+0x14]
    mov  edx, dword ptr [esp+0x1c]
sq_row:
    mov  ecx, dword ptr [esp+0x1c]
    push esi
    push edi
    rep movsb
    pop  edi
    pop  esi
    add  esi, dword ptr [esp+0x10]
    add  edi, dword ptr [esp+0x18]
    dec  edx
    jnz  sq_row
    pop  edi
    pop  esi
    ret  0x14
"""


# corner k: (x from L or R-s, y from T or B-s); g_fr_rect = L, T, R, B at +0 / +4 / +8 / +0xC
CORNERS = ((0, 4, False, False), (8, 4, True, False), (0, 0xC, False, True), (8, 0xC, True, True))


def _corner_ptr(k):
    """eax = data + y*stride + x for corner k (ebx = &g_fr_rect, edi = data, ecx = stride, ebp = s)."""
    xo, yo, xs, ys = CORNERS[k]
    return f"""
    mov  eax, dword ptr [ebx+{yo:#x}]
    {"sub  eax, ebp" if ys else ""}
    imul eax, ecx
    add  eax, dword ptr [ebx+{xo:#x}]
    {"sub  eax, ebp" if xs else ""}
    add  eax, edi
"""


# BoxSpriteParams edge strips: (slot offset, row = 0 | h-1 | h/2, col = w/2 | 0 | w-1, mask bit, band)
STRIPS = (
    (0x10, "0", "half_w", 1),        # top
    (0x14, "last", "half_w", 2),     # bottom
    (0x18, "half_h", "0", 4),        # left
    (0x1C, "half_h", "last_w", 8),   # right
)
# corner pieces: (slot offset, row, col): TL (0,0) TR (0,w-1) BL (h-1,0) BR (h-1,w-1)
CORNER_ART = ((0x0, "0", "0"), (0x4, "0", "last_w"), (0x8, "last", "0"), (0xC, "last", "last_w"))


def _art_px(slot, row, col, fail):
    """al = the texel (row, col) of the Sprite at [params+slot] (ebx = params); jump to `fail` when absent."""
    rr = {"0": "", "last": "mov  eax, dword ptr [ecx+0x14]\n    dec  eax\n    imul eax, dword ptr [ecx+0xc]\n    add  edx, eax",
          "half_h": "mov  eax, dword ptr [ecx+0x14]\n    shr  eax, 1\n    imul eax, dword ptr [ecx+0xc]\n    add  edx, eax"}[row]
    cc = {"0": "", "half_w": "mov  eax, dword ptr [ecx+0x10]\n    shr  eax, 1\n    add  edx, eax",
          "last_w": "mov  eax, dword ptr [ecx+0x10]\n    dec  eax\n    add  edx, eax"}[col]
    return f"""
    mov  ecx, dword ptr [ebx+{slot:#x}]
    test ecx, ecx
    je   {fail}
    mov  edx, dword ptr [ecx+4]
    test edx, edx
    je   {fail}
    cmp  dword ptr [ecx+0x10], 0
    jle  {fail}
    cmp  dword ptr [ecx+0x14], 0
    jle  {fail}
    {rr}
    {cc}
    mov  al, byte ptr [edx]
"""


def _art_reads():
    """After the save-under (ebx = params): g_fr_cmask bit k = corner piece k's outer texel is the key; g_fr_bmask bit i
    + g_fr_bc<i> = strip i's edge texel when it is a stroke (not the pass-through 7, not the key 9)."""
    out = [f"""
    mov  ebx, dword ptr [esp+0x18]
    xor  eax, eax
    mov  dword ptr [{S('g_fr_cmask')}], eax
    mov  dword ptr [{S('g_fr_bmask')}], eax
"""]
    for k, (slot, row, col) in enumerate(CORNER_ART):
        out.append(f"""{_art_px(slot, row, col, f"ak{k}")}
    cmp  al, {KEY}
    jne  ak{k}
    or   byte ptr [{S('g_fr_cmask')}], {1 << k}
ak{k}:
""")
    for i, (slot, row, col, bit) in enumerate(STRIPS):
        out.append(f"""{_art_px(slot, row, col, f"as{i}")}
    cmp  al, {PASS}
    je   as{i}
    cmp  al, {KEY}
    je   as{i}
    mov  byte ptr [{S(f'g_fr_bc{i}')}], al
    or   byte ptr [{S('g_fr_bmask')}], {bit}
as{i}:
""")
    return "".join(out)


BAND_RECTS = {1: ("L", "T", "RL", "s"), 2: ("L", "Bs", "RL", "s"), 4: ("L", "T", "s", "BT"), 8: ("Rs", "T", "s", "BT")}
BAND_VAL = {"L": "mov  eax, dword ptr [edi]", "T": "mov  eax, dword ptr [edi+4]",
            "RL": "mov  eax, dword ptr [edi+8]\n    sub  eax, dword ptr [edi]",
            "BT": "mov  eax, dword ptr [edi+0xc]\n    sub  eax, dword ptr [edi+4]",
            "s": "mov  eax, ebp", "Bs": "mov  eax, dword ptr [edi+0xc]\n    sub  eax, ebp",
            "Rs": "mov  eax, dword ptr [edi+8]\n    sub  eax, ebp"}


def _bands(tag, routine, colour):
    """For each stroke edge (g_fr_bmask bit): push the band rect (x, y, w, h) inside g_fr_rect (edi), al = colour(i),
    call `routine`.  ebp = s (== K), edi = &g_fr_rect."""
    out = []
    for i, (_slot, _row, _col, bit) in enumerate(STRIPS):
        x, y, w, h = BAND_RECTS[bit]
        out.append(f"""
    test byte ptr [{S('g_fr_bmask')}], {bit}
    je   {tag}{i}
    {BAND_VAL[h]}
    push eax
    {BAND_VAL[w]}
    push eax
    {BAND_VAL[y]}
    push eax
    {BAND_VAL[x]}
    push eax
    mov  al, byte ptr [{S(f'g_fr_bc{i}')}]
    {colour}
    call {routine}
{tag}{i}:
""")
    return "".join(out)


def asm_rowbox():
    """t_fac_rowbox (v2, 2026-10-25 audit condition 2: vanilla's order -- the strokes under the text).  Gate as v1; then:
    save the keyed-corner background, read the set's art once, CALL Buffer_box_sprite, draw the K bands of each stroke
    (solid), put the background back in the keyed corner squares, RET 8 -- all before draw_item writes the row's text,
    so the text lands on the bands as it lands on vanilla's 1-px stroke.  Gate failed: tail-jump the native draw."""
    saves = "".join(f"""{_corner_ptr(k)}
    push ebp
    push 4
    lea  edx, [esi+{16 * k:#x}]
    push edx
    push ecx
    push eax
    call {C('t_fac_sqcopy')}
    mov  ecx, dword ptr [esp]
""" for k in range(4))
    restores = "".join(f"""
    test byte ptr [{S('g_fr_cmask')}], {1 << k}
    je   rc{k}
{_corner_ptr(k)}
    push ebp
    push ecx
    push eax
    push 4
    mov  edx, {S('g_fr_save')}
    add  edx, {16 * k:#x}
    push edx
    call {C('t_fac_sqcopy')}
    mov  ecx, dword ptr [esi+0x4a8]
rc{k}:
""" for k in range(4))
    return f"""
    cmp  dword ptr [{S('g_popup_scale_num')}], 0x10
    jle  native
    push ebx
    push esi
    push edi
    push ebp
    mov  dword ptr [{S('g_fr_pending')}], 0
    mov  esi, ecx
    mov  ebp, dword ptr [{S('g_popup_scale_num')}]
    add  ebp, 0xf
    sar  ebp, 4
    cmp  ebp, 4
    jg   draw
    mov  edi, dword ptr [esi+0x54]
    test edi, edi
    je   draw
    mov  ecx, dword ptr [esi+0x4a8]
    test ecx, ecx
    jle  draw
    mov  edx, dword ptr [esp+0x14]
    mov  ebx, {S('g_fr_rect')}
    mov  eax, dword ptr [edx]
    test eax, eax
    jl   draw
    mov  dword ptr [ebx], eax
    mov  eax, dword ptr [edx+4]
    test eax, eax
    jl   draw
    mov  dword ptr [ebx+4], eax
    mov  eax, dword ptr [edx+8]
    cmp  eax, dword ptr [esi+0x80]
    jg   draw
    cmp  eax, ecx
    jg   draw
    mov  dword ptr [ebx+8], eax
    sub  eax, dword ptr [ebx]
    sub  eax, ebp
    sub  eax, ebp
    jl   draw
    mov  eax, dword ptr [esi+0x84]
    test eax, eax
    jge  hpos
    neg  eax
hpos:
    cmp  dword ptr [edx+0xc], eax
    jg   draw
    mov  eax, dword ptr [edx+0xc]
    mov  dword ptr [ebx+0xc], eax
    sub  eax, dword ptr [ebx+4]
    sub  eax, ebp
    sub  eax, ebp
    jl   draw
    mov  dword ptr [{S('g_fr_buf')}], esi
    push esi
    push ecx
    mov  esi, {S('g_fr_save')}
{saves}
    pop  ecx
    pop  esi
{_art_reads()}
    mov  dword ptr [{S('g_fr_pending')}], 1
    mov  ecx, esi
    push dword ptr [esp+0x18]
    push dword ptr [esp+0x18]
    call {C('Buffer_box_sprite')}
    mov  esi, dword ptr [{S('g_fr_buf')}]
    mov  edi, dword ptr [esi+0x54]
    mov  ecx, dword ptr [esi+0x4a8]
    mov  ebx, {S('g_fr_rect')}
    push edi
    mov  edi, ebx
{_bands('nb', 'fillb', '')}
    pop  edi
{restores}
    pop  ebp
    pop  edi
    pop  esi
    pop  ebx
    ret  8
draw:
    mov  ecx, esi
    pop  ebp
    pop  edi
    pop  esi
    pop  ebx
native:
    push {S('Buffer_box_sprite')}
    ret
fillb:
    push esi
    push edi
    push ebx
    push ecx
    cld
    mov  ebx, dword ptr [{S('g_fr_buf')}]
    mov  esi, dword ptr [esp+0x20]
    mov  edx, dword ptr [esp+0x18]
fb_row:
    mov  edi, edx
    imul edi, dword ptr [ebx+0x4a8]
    add  edi, dword ptr [ebx+0x54]
    add  edi, dword ptr [esp+0x14]
    mov  ecx, dword ptr [esp+0x1c]
    rep stosb
    inc  edx
    dec  esi
    jnz  fb_row
    pop  ecx
    pop  ebx
    pop  edi
    pop  esi
    ret  0x10
"""


def asm_rowpost():
    """t_fac_rowpost (v2): the restripe (t_lbi_restripe_ph: the whole list canvas onto the stripe law -- the restored
    corner background with it, and the solid bands split into stroke / mate stripes), then (pending) inside each band
    the stroke's pair mate back to the stroke colour (E1 -> E0, EE -> AE, and the reverse); every other index --
    the row's text ink -- is left as the text drew it.  pushad-wrapped."""
    return f"""
    push dword ptr [esp+0x10]
    push dword ptr [esp+0x10]
    push dword ptr [esp+0x10]
    push dword ptr [esp+0x10]
    call {C('t_lbi_restripe_ph')}
    cmp  dword ptr [{S('g_fr_pending')}], 0
    je   r
    and  dword ptr [{S('g_fr_pending')}], 0
    pushad
    mov  esi, dword ptr [{S('g_fr_buf')}]
    cmp  dword ptr [esi+0x54], 0
    je   pa
    mov  ebp, dword ptr [{S('g_popup_scale_num')}]
    add  ebp, 0xf
    sar  ebp, 4
    mov  edi, {S('g_fr_rect')}
{_bands('nf', 'fixb', 'call mate')}
pa:
    popad
r:
    ret  0x10
mate:
    mov  ah, 0xe1
    cmp  al, 0xe0
    je   m_ok
    mov  ah, 0xe0
    cmp  al, 0xe1
    je   m_ok
    mov  ah, 0xee
    cmp  al, 0xae
    je   m_ok
    mov  ah, 0xae
    cmp  al, 0xee
    je   m_ok
    mov  ah, al
m_ok:
    ret
fixb:
    push esi
    push edi
    push ebx
    push ecx
    mov  ebx, dword ptr [{S('g_fr_buf')}]
    mov  esi, dword ptr [esp+0x20]
    mov  edx, dword ptr [esp+0x18]
fx_row:
    mov  edi, edx
    imul edi, dword ptr [ebx+0x4a8]
    add  edi, dword ptr [ebx+0x54]
    add  edi, dword ptr [esp+0x14]
    mov  ecx, dword ptr [esp+0x1c]
fx_px:
    cmp  byte ptr [edi], ah
    jne  fx_k
    mov  byte ptr [edi], al
fx_k:
    inc  edi
    dec  ecx
    jnz  fx_px
    inc  edx
    dec  esi
    jnz  fx_row
    pop  ecx
    pop  ebx
    pop  edi
    pop  esi
    ret  0x10
"""


def asm_filedlg_rects():
    return f"""
    cmp  dword ptr [{S('g_popup_scale_num')}], 0x10
    jle  native
    push ebx
    push esi
    mov  ebx, dword ptr [esp+0x14]
    mov  eax, dword ptr [ebx+0x34]
    sub  eax, dword ptr [ebx+0x2c]
    push eax
    mov  eax, dword ptr [ebx+0x30]
    sub  eax, dword ptr [ebx+0x28]
    push eax
    mov  esi, 1
lp:
    mov  eax, dword ptr [ebx+esi*4]
    call {C('popup_scale')}
    mov  dword ptr [ebx+esi*4], eax
    inc  esi
    cmp  esi, 0x11
    jl   lp
    pop  eax
    call {C('popup_scale')}
    add  eax, dword ptr [ebx+0x28]
    mov  dword ptr [ebx+0x30], eax
    mov  dword ptr [ebx+0x40], eax
    mov  eax, dword ptr [ebx+0x28]
    mov  dword ptr [ebx+0x38], eax
    pop  eax
    call {C('popup_scale')}
    mov  edx, dword ptr [ebx+0x3c]
    sub  edx, dword ptr [ebx+0x24]
    sub  edx, eax
    sar  edx, 1
    mov  eax, dword ptr [ebx+0x24]
    add  eax, edx
    mov  dword ptr [ebx+0x2c], eax
    mov  eax, dword ptr [ebx+0x3c]
    sub  eax, edx
    mov  dword ptr [ebx+0x34], eax
    pop  esi
    pop  ebx
native:
    push {S('FileDlg_build_widgets')}
    ret
"""


SOURCES = {
    "t_btn_edgeprobe": asm_edgeprobe, "t_btn_edgeband": asm_edgeband, "t_fac_item_pre": asm_item_pre,
    "t_fac_sqcopy": asm_sqcopy, "t_fac_rowbox": asm_rowbox, "t_fac_rowpost": asm_rowpost,
    "thunk_filedlg_rects": asm_filedlg_rects,
}


def assemble(src, va):
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    return bytes(enc)


def to_template(blob, va):
    """abs32 sentinels -> {abs32:name}; E8 to a CALL sentinel -> {rel32:name}."""
    rabs = {v: k for k, v in SYMS.items()}
    rcall = {v: k for k, v in CALLS.items()}
    out, i = [], 0
    while i < len(blob):
        if blob[i] == 0xE8 and i + 5 <= len(blob):
            tgt = (va + i + 5 + int.from_bytes(blob[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in rcall:
                out += ["E8", "{rel32:%s}" % rcall[tgt]]
                i += 5
                continue
        if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") in rabs:
            out.append("{abs32:%s}" % rabs[int.from_bytes(blob[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{blob[i]:02X}")
        i += 1
    return " ".join(out)


def resolve(tpl, va, syms, calls):
    """Template -> bytes at va with the given symbol VAs (the patcher's own rules: rel32 only after E8)."""
    out = bytearray()
    for tok in tpl.split():
        if tok.startswith("{abs32:"):
            out += syms[tok[7:-1]].to_bytes(4, "little")
        elif tok.startswith("{rel32:"):
            assert out[-1] == 0xE8
            out += ((calls[tok[7:-1]] - (va + len(out) + 4)) & 0xFFFFFFFF).to_bytes(4, "little")
        else:
            out.append(int(tok, 16))
    return bytes(out)


def build():
    parts = {}
    for name, fn in SOURCES.items():
        off, end = SLOTS[name]
        va = PCAVE2 + off
        blob = assemble(fn(), va)
        assert off + len(blob) <= end, (name, hex(off + len(blob)), hex(end))
        tpl = to_template(blob, va)
        assert resolve(tpl, va, SYMS, CALLS) == blob, name
        parts[name] = (off, len(blob), tpl)
    return parts


def main():
    for name, (off, n, tpl) in build().items():
        print(f"{name}  {n} B @0x{off:X}..0x{off + n:X}")
        print(f'        bytes: "{tpl}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
