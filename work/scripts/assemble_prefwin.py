"""Assemble the PrefWin scaling thunk set (group prefwin_scale) -- the bake of
hook_prefwin_scale.js v19, user-verified in-game at 4K/1600x1200/1920x1080/1024x768.

v2 (2026-07-12, Longevity prefs tab): adds a DLL WIDGET REGISTRY -- four dword slots
at FIXED cave VAs that uimod.dll fills at PrefWin-build time so its OWN PrefWin
widgets (the "Longevity Mod Preferences" tab button + label button + font-scale
slider) ride the SAME zoom/init machinery as the 19 engine statics:

  g_dll_pref_lo/hi    -- btnzoom arms for ecx in [lo,hi] (the DLL's widget block)
                         in ADDITION to the engine range [0x858338,0x872140].
                         lo==0 (no DLL) -> extra check never matches.
  g_dll_pref_slider   -- sbzoom + gwinit slkid arm for this instance too.
  g_map_font_pct      -- 0..100 map-label font scale (see thunk_map_font below);
                         default 100 == full g/16 (bake-only behavior unchanged).

thunk_map_font (NEW, group map_label_fonts): the 3 MapWin_calculate_dimensions
Font_init sites redirect here (was thunk_hud_font). size' = native*(16 +
(g-16)*pct/100)/16 -- pct=100 reproduces thunk_hud_font bit-exactly
(native*g>>4), pct=0 is native (pristine), g<=16 native no-op regardless.
LAW: scaling_laws.map_label_font_size (this asm is a port; parity test
tests/test_mapfont_asm_parity.py).

thunk_pref_show + g_pref_wins RELOCATED 0xADC0/0xAE90 -> 0xB180/0xB250 (the grown
btnzoom/sbzoom/gwinit push the packed block past the 0xAF00 boundary where
thunk_scale_boxw lives; old slots freed/zeros).

PORT OF the prototype's transforms, byte-faithful to its arithmetic
(S(v) = floor(v*g/16); laws scaling_laws.popup_scale_floor / prefwin_window_pos):

  thunk_pref_gwinit   -- GraphicWin_init 0x5D4EF0 ENTRY detour (displaces the 6-byte
                         `mov eax,fs:[0]`). Three laws: (A) ecx==PrefWin -> window law
                         x=SW/2-S(350) y=SH-S(618), w=CEIL(778g/16) h=S(390)
                         (scaling_laws.prefwin_window_wh, W6A 2026-10-25: the ceiling
                         is the width the slide rails' double-floor descale maps back
                         to exactly 778, so the right rails land on the backdrop's
                         edge fl(723g/16)); (B) parent==PrefWin ->
                         child x,y,w,h *= g/16 EXCEPT ret in [0x60E800,0x60F000) (the
                         page-attach inner init arrives via thunk_list_fill_width's
                         tail-jmp and owns its own w law); W8P 2026-10-27: y through
                         t_pref_tabrow (the category column on ONE pitch, law
                         scaling_laws.pref_child_y); (C) parent in {4 slider
                         statics} OR parent==[g_dll_pref_slider] (nonzero) -> arrow/
                         thumb mini-windows, each arg scaled only if native-plausible
                         (x,y in [0,340]; w,h in (0,40] -- the ctor derives the
                         right-arrow x from the ALREADY-SCALED parent w).
  thunk_pref_ffscale  -- the 7 PrefWin_build find_font call sites: size *= g/16.
  thunk_pref_dlg2     -- the 7 per-page Dialog_init_2 call sites: x,y,h *= g/16, w
                         NATIVE (the baked thunk_list_fill_width owns w; scaling here
                         double-scaled to 2855 in the v11 log).
  thunk_pref_attach   -- FUN_0060e800 ENTRY detour (displaces `push ebx; mov ebx,[esp+8]`),
                         gated on win==PrefWin: page attach x,y *= g/16.
  thunk_pref_boxframe -- v3 (W6A v2, 2026-10-25): jmp t_pref_frame.  The entry the 8
                         non-backdrop Buffer_box_sprite chrome sites (4 show + 4
                         repaint) call, and uimod.dll for its own page chrome (same
                         contract as Buffer_box_sprite); it keeps its address 0xA16D00.
  t_pref_frame        -- (W6A v2, pcave2 0x3E080; laws scaling_laws.prefwin_layout /
                         pref_frame_draw_rect): a NATIVE rect found in g_pref_frame_keys
                         (inner frame, the two panels, the audio slider frame, the
                         DLL's Longevity frame) -> its g_pref_frame_tbl row, the frame
                         mirrored about its content (INCLUSIVE device rect: the band map
                         draws its rect inclusive, so the half-open native extent is
                         [L, R-1] x [T, B-1]); any other rect -> fl(v*g/16) per edge,
                         then R-1 / B-1.  Then dispatch like thunk_factionwin_framecover:
                         [params+0x20]!=0 -> thunk_box_thick_devfill, else
                         thunk_box_thick_hollow_flat (band-map K=half_down(g,16) strokes);
                         g<=16 -> plain native entry 0x5E2DD3 untouched.
  t_pref_bd           -- (W6A, pcave2 0x3E000): the backdrop site 0x48FB19 -- fl(v*g/16)
                         per edge, R-1 / B-1, L on the left slide rails' extent
                         fl(15g/16) + fl(8g/16) (scaling_laws.rail_left_extent).
  thunk_pref_btnzoom  -- FlatButton content-draw vtable slot [0x669784] repoint: for
                         ecx in the PrefWin widget cluster [0x858338,0x872140] OR in
                         [[g_dll_pref_lo],[g_dll_pref_hi]] (lo nonzero) set
                         g_popup_active around the draw (the proven popup
                         shrink+2D-zoom renders the button native and NN-zooms x g/16).
                         v3 (2026-09-13): REFCOUNT bracket (INC / DEC clamped at 0,
                         the thunk_basewin_btnzoom pattern). The v2 absolute 1/0
                         bracket was the only absolute writer of g_popup_active in
                         the cave; a PrefWin/DLL-range button draw after the quit
                         modal's exec_3 INC zeroed the depth, so the OK hover redraw
                         drew the native 20-px bar at the top of its scaled window.
  thunk_pref_sbzoom   -- ScrollBar_draw vtable slot [0x669D88] repoint: for the 4
                         PrefWin sliders or [g_dll_pref_slider] set g_netwin_active
                         around the draw (activates baked thunk_sb_thumb nub scale +
                         arrow zoom gate).
  thunk_pref_show     -- PrefWin_show 0x48FA00 ENTRY detour (displaces the 6-byte
                         frame prologue): (1) re-assert the window rect to the law
                         position (Popup_show-shape idempotent repair); (2) write the
                         15 buttons' label font slot [btn+0x970] = find_font(S(14),1)
                         (buttons seed the slot from the native def-font at init);
                         (3) drive vtbl+0xF8 refresh of the 15 buttons + 4 sliders
                         (build-time renders predate the font fix and zoom gates).
                         The DLL's widgets do their own font/refresh in its vtable
                         wrappers -- NOT in this table.
  g_pref_wins         -- the 19 static window addresses (15 buttons + 4 sliders).

Every thunk is a g_popup_scale_num<=16 native no-op (the vtable stubs arm gates whose
baked consumers are identity at g=16 -- prototype-proven at 1024x768).

The rail chrome (4 slide sites) redirects to the EXISTING baked wrappers
thunk_popup_railshow/railhide -- plain call_target_redirects, no new code here.

Assembled at FIXED VAs (pcave2 = 0xA0C000): raw bytes, do not relocate; regenerate
from this script, do not hand-edit patches.yaml.
"""
import struct
import sys
from pathlib import Path

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scaling_laws as SL  # noqa: E402  (W6A v2: the PrefWin mirror layout table is emitted from the law)
from scaling_laws import G_MAX, NATIVE_G  # noqa: E402

PCAVE2 = 0xA0C000

# engine / patch-set constants (all verified against the pristine .bak + ledger)
G = 0x668740                # g_popup_scale_num
SW = 0x9B7B1C               # ScreenWidth
SH = 0x9B7B20               # ScreenHeight
PREFWIN = 0x8578D8
FIND_FONT = 0x5882F0        # cdecl(size, variant)
T_FFN = 0xA0C000 + 0x2E570  # t_ffn(S, v) cdecl: find_font drop-in with the face/weight law (assemble_fontlaw.py)
T_FDIRECT_A14B = 0xA0C000 + 0x2E590   # t_fdirect_a14b() cdecl -> the shared Arial fl(14g/16) BOLD slot: the PrefWin
                                      # buttons' vanilla +0x970 is the shared 0x6E84B4 = Font_init("Arial",14,1) (probe
                                      # hook_btnfont_probe.js 2026-09-17); thunk_pref_show v1 asked the pool = Arial Narrow
FONT_INIT = 0x618F40        # thiscall(ecx=Font; name, height, style) RET 0xC
ENSURE_SCALE = 0x668760     # thunk_ensure_scale (EAX-only, idempotent)
DIALOG_INIT2 = 0x609300
GWINIT_RESUME = 0x5D4EF6
ATTACH_RESUME = 0x60E806
SHOW_RESUME = 0x48FA06
BBS = 0x5E2DD3              # Buffer_box_sprite entry (baked hud_boxframe detour lives there)
HOLLOW_FLAT = PCAVE2 + 0x140     # thunk_box_thick_hollow_flat
DEVFILL = PCAVE2 + 0x42A0        # thunk_box_thick_devfill v2
G_POPUP_ACTIVE = PCAVE2 + 0x530
G_NETWIN_ACTIVE = PCAVE2 + 0x4800
CONTENT_DRAW = 0x607E50
SB_DRAW = 0x6066F0

BTNS = [0x858338, 0x858E84, 0x8599D0, 0x85A51C, 0x85B068, 0x85BBB4, 0x85C700,
        0x86C6E0, 0x86DD78, 0x86D22C, 0x86E8C4, 0x86FF5C, 0x8715F4, 0x870AA8,
        0x872140]
SLIDERS = [0x862064, 0x8641B0, 0x8662FC, 0x868448]

BASE_OFF = 0xAAE0           # first free pcave2 offset for the packed thunk block
BLOCK_LIMIT = 0xAF00        # thunk_scale_boxw starts here -- packed block must not cross

# tail block (after thunk_pf_union_align, which ends 0xB11D)
DLL_PREF_LO_OFF = 0xB120    # dword 0: DLL widget block start (0 = unregistered)
DLL_PREF_HI_OFF = 0xB124    # dword 0: DLL widget block end (inclusive)
DLL_PREF_SLIDER_OFF = 0xB128  # dword 0: DLL slider instance
MAP_FONT_PCT_OFF = 0xB12C   # dword 100: map-label font scale percent
MAP_FONT_OFF = 0xB130       # thunk_map_font (ends 0xB168)
BIG_F4_OFF = 0xB170         # dword 1 (default ON since 2026-09-13): "Big F4 indicators" pref (uimod.dll checkbox) -> t_rwk_blink stamps the BASE LOCATOR ring at 2g/16
SHOW_OFF = 0xB180           # thunk_pref_show (relocated from 0xADC0)
TABLE_OFF = 0xB250          # g_pref_wins (relocated from 0xAE90)
CAVE_LIMIT = 0xB800

G_DLL_LO = PCAVE2 + DLL_PREF_LO_OFF
G_DLL_HI = PCAVE2 + DLL_PREF_HI_OFF
G_DLL_SLIDER = PCAVE2 + DLL_PREF_SLIDER_OFF
G_MAP_FONT_PCT = PCAVE2 + MAP_FONT_PCT_OFF

PREF_13C = PREFWIN + 0x13C
PREF_140 = PREFWIN + 0x140
PREF_144 = PREFWIN + 0x144
PREF_148 = PREFWIN + 0x148


def asm_gwinit():
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  out
        cmp  ecx, {PREFWIN}
        je   selfwin
        mov  edx, dword ptr [esp + 0x1C]
        cmp  edx, {PREFWIN}
        je   child
        cmp  edx, {SLIDERS[0]}
        je   slkid
        cmp  edx, {SLIDERS[1]}
        je   slkid
        cmp  edx, {SLIDERS[2]}
        je   slkid
        cmp  edx, {SLIDERS[3]}
        je   slkid
        test edx, edx
        je   out
        cmp  edx, dword ptr [{G_DLL_SLIDER}]
        je   slkid
        jmp  out
    selfwin:
        imul edx, eax, 350
        sar  edx, 4
        mov  eax, dword ptr [{SW}]
        sar  eax, 1
        sub  eax, edx
        mov  dword ptr [esp + 4], eax
        mov  eax, dword ptr [{G}]
        imul edx, eax, 618
        sar  edx, 4
        mov  eax, dword ptr [{SH}]
        sub  eax, edx
        mov  dword ptr [esp + 8], eax
        mov  eax, dword ptr [{G}]
        mov  edx, dword ptr [esp + 0xC]
        imul edx, eax
        add  edx, 15
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
        mov  edx, dword ptr [esp + 0x10]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
        jmp  out
    child:
        mov  edx, dword ptr [esp]
        cmp  edx, 0x60E800
        jb   cscale
        cmp  edx, 0x60F000
        jb   out
    cscale:
        call {PCAVE2 + T_PREF_TABROW_OFF}
        mov  edx, dword ptr [esp + 4]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 4], edx
        mov  edx, dword ptr [esp + 0xC]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
        mov  edx, dword ptr [esp + 0x10]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
        jmp  out
    slkid:
        mov  edx, dword ptr [esp + 4]
        cmp  edx, 340
        ja   sk1
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 4], edx
    sk1:
        mov  edx, dword ptr [esp + 8]
        cmp  edx, 340
        ja   sk2
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 8], edx
    sk2:
        mov  edx, dword ptr [esp + 0xC]
        test edx, edx
        jle  sk3
        cmp  edx, 40
        jg   sk3
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
    sk3:
        mov  edx, dword ptr [esp + 0x10]
        test edx, edx
        jle  out
        cmp  edx, 40
        jg   out
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
    out:
        mov  eax, dword ptr fs:[0]
        jmp  {GWINIT_RESUME}
    """


def asm_ffscale():
    # v2 (2026-09-17, audit finding 3.11): the 7 PrefWin_build find_font sites push their NATIVE
    # (size, variant); t_ffn (assemble_fontlaw.py) is the face-preserving drop-in (Arial regular /
    # italic / bold for the <=12 natives, the pool as before for the 14s; vanilla lookup at g<=16).
    # push abs + ret = the cave tail-jmp law ({{rel32:}} only after E8).
    return f"""
        push {T_FFN}
        ret
    """


def asm_dlg2():
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  go
        mov  edx, dword ptr [esp + 4]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 4], edx
        mov  edx, dword ptr [esp + 8]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 8], edx
        mov  edx, dword ptr [esp + 0x10]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0x10], edx
    go:
        jmp  {DIALOG_INIT2}
    """


def asm_attach():
    return f"""
        cmp  dword ptr [esp + 4], {PREFWIN}
        jne  out
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  out
        mov  edx, dword ptr [esp + 8]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 8], edx
        mov  edx, dword ptr [esp + 0xC]
        imul edx, eax
        sar  edx, 4
        mov  dword ptr [esp + 0xC], edx
    out:
        push ebx
        mov  ebx, dword ptr [esp + 8]
        push esi
        jmp  {ATTACH_RESUME}
    """


def asm_pref_bd():
    """t_pref_bd (2026-10-25 wave-6 W6A, F42; law scaling_laws.pref_frame_draw_rect): PrefWin_show's backdrop site
    0x48FB19 -- thunk_pref_boxframe v2 with the left edge on the left slide rails' composed extent
    fl(15g/16) + fl(8g/16) (rail_left_extent).  Same stack contract (ecx = dest Buffer, rect, params; the rect is
    rewritten in place, as the shared thunk does)."""
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  native
        mov  edx, dword ptr [esp + 4]
        push ecx
        mov  ecx, dword ptr [edx + 4]
        imul ecx, eax
        sar  ecx, 4
        mov  dword ptr [edx + 4], ecx
        mov  ecx, dword ptr [edx + 8]
        imul ecx, eax
        sar  ecx, 4
        dec  ecx
        mov  dword ptr [edx + 8], ecx
        mov  ecx, dword ptr [edx + 0xC]
        imul ecx, eax
        sar  ecx, 4
        dec  ecx
        mov  dword ptr [edx + 0xC], ecx
        imul ecx, eax, 15
        sar  ecx, 4
        mov  dword ptr [edx], ecx
        imul ecx, eax, 8
        sar  ecx, 4
        add  dword ptr [edx], ecx
        pop  ecx
        mov  edx, dword ptr [esp + 8]
        cmp  dword ptr [edx + 0x20], 0
        jne  filled
        jmp  {HOLLOW_FLAT}
    filled:
        jmp  {DEVFILL}
    native:
        jmp  {BBS}
    """


#: W6A (2026-10-25): the thunks this wave changes, at their PINNED offsets (the packed `order` in main() predates
#: later relocations of its neighbours; these are emitted / tested here): gwinit w-ceil in place, boxframe v3 (a
#: trampoline) in place, and in W6A's pcave2 region 0x3E000..0x3EFFF t_pref_bd (the backdrop), t_pref_frame (every other
#: PrefWin frame) and its two data blocks.
T_PREF_FRAME_OFF = 0x3E080
G_PREF_FRAME_KEYS_OFF = 0x3E180      # the native rects t_pref_frame recognises (PREF_FRAME_ORDER, 4 dwords each)
G_PREF_FRAME_TBL_OFF = 0x3E200       # prefwin_layout per g 17..40 x frame: 4 int16 (inclusive device L, T, R, B)
PREF_FRAME_ORDER = ("inner", "lpanel", "rpanel", "sframe", "dll")
T_PREF_TABROW_OFF = 0x3E5C0          # W8P (2026-10-27): the free tail of W6A's region, after g_pref_frame_tbl
W6A_THUNKS = (("thunk_pref_gwinit", 0xAAE0, 0xAC60), ("thunk_pref_boxframe", 0xAD00, 0xAD60),
              ("t_pref_bd", 0x3E000, 0x3E080), ("t_pref_frame", T_PREF_FRAME_OFF, G_PREF_FRAME_KEYS_OFF),
              ("g_pref_frame_keys", G_PREF_FRAME_KEYS_OFF, G_PREF_FRAME_TBL_OFF),
              ("g_pref_frame_tbl", G_PREF_FRAME_TBL_OFF, T_PREF_TABROW_OFF),
              ("t_pref_tabrow", T_PREF_TABROW_OFF, 0x3E640))

# the category column's engine statics (PrefWin_build reads them for every tab row; uimod.dll's Longevity tab too)
TAB_X, TAB_Y0, TAB_W, TAB_H = 0x85788C, 0x857890, 0x857894, 0x686B88


def asm_pref_tabrow():
    """t_pref_tabrow (2026-10-27 wave-8 W8P; law scaling_laws.pref_child_y / pref_tab_pitch): CALLed by
    thunk_pref_gwinit's child arm (parent == PrefWin, g > 16, eax = g) BEFORE it scales x / w / h, with the caller's
    GraphicWin_init args NATIVE at [esp + 8] x, [esp + 0xC] y, [esp + 0x10] w, [esp + 0x14] h.  Writes the device y:
    a category-column row (x / w / h == the statics, y - y0 = 22 i, 0 <= i < 7) -> fl(y0 g/16) + i * half_down(22g, 16)
    (one pitch: the gaps equal); any other child -> fl(y g/16) (the arm's old floor).  eax (g), ecx (the window being
    inited: GraphicWin_init is thiscall), ebx, esi, edi, ebp preserved; edx clobbered (the arm reloads it)."""
    return f"""
        push ecx
        push ebx
        mov  ebx, dword ptr [esp + 0x14]
        mov  ecx, dword ptr [{TAB_X}]
        cmp  ecx, dword ptr [esp + 0x10]
        jne  plain
        mov  ecx, dword ptr [{TAB_W}]
        cmp  ecx, dword ptr [esp + 0x18]
        jne  plain
        mov  ecx, dword ptr [{TAB_H}]
        cmp  ecx, dword ptr [esp + 0x1C]
        jne  plain
        sub  ebx, dword ptr [{TAB_Y0}]
        jl   plain
        cmp  ebx, {SL.PREF_TAB_PITCH * SL.PREF_TAB_ROWS}
        jge  plain
        push eax
        mov  eax, ebx
        xor  edx, edx
        mov  ecx, {SL.PREF_TAB_PITCH}
        div  ecx
        mov  ebx, eax
        pop  eax
        test edx, edx
        jne  plain
        imul ecx, eax, {2 * SL.PREF_TAB_PITCH}
        add  ecx, 15
        sar  ecx, 5
        imul ecx, ebx
        mov  edx, dword ptr [{TAB_Y0}]
        imul edx, eax
        sar  edx, 4
        add  edx, ecx
        jmp  store
    plain:
        mov  edx, dword ptr [esp + 0x14]
        imul edx, eax
        sar  edx, 4
    store:
        mov  dword ptr [esp + 0x14], edx
        pop  ebx
        pop  ecx
        ret
    """


def asm_boxframe():
    """thunk_pref_boxframe v3 (2026-10-25 wave-6 W6A v2): a trampoline to t_pref_frame.  Its entry 0xA16D00 is what the
    eight non-backdrop chrome sites call and what uimod.dll's Longevity page calls directly, so it keeps that address
    and the Buffer_box_sprite stack contract; the work moved to W6A's region (the mirror layout's table does not fit
    the 96-byte slot)."""
    return f"""
        jmp  {PCAVE2 + T_PREF_FRAME_OFF}
    """


def asm_pref_frame():
    """t_pref_frame (2026-10-25 wave-6 W6A v2; law scaling_laws.pref_frame_draw_rect / prefwin_layout): the PrefWin
    frames mirrored about their content.  g <= 16 -> Buffer_box_sprite untouched.  A rect equal to one of
    g_pref_frame_keys (the frames' NATIVE rects; every site and the DLL rebuild theirs from the statics per call) at
    g <= G_MAX -> its row of g_pref_frame_tbl (prefwin_layout(g), inclusive, int16) written over the rect; any other
    rect (or g > G_MAX, unreachable: g_popup_scale_num is clamped) -> every edge fl(v g/16), then R-1 / B-1 (v2's
    generic arm).  Then the [params+0x20] dispatch (filled -> thunk_box_thick_devfill, hollow ->
    thunk_box_thick_hollow_flat).  ecx (dest), ebx, esi, edi, ebp preserved; the rect is rewritten in place (the
    callers' contract since v1)."""
    keys = PCAVE2 + G_PREF_FRAME_KEYS_OFF
    tbl = PCAVE2 + G_PREF_FRAME_TBL_OFF
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  native
        mov  edx, dword ptr [esp + 4]
        push ecx
        push ebx
        push esi
        cmp  eax, {G_MAX}
        jg   generic
        mov  esi, {keys}
        xor  ebx, ebx
    find:
        mov  ecx, dword ptr [esi]
        cmp  ecx, dword ptr [edx]
        jne  next
        mov  ecx, dword ptr [esi + 4]
        cmp  ecx, dword ptr [edx + 4]
        jne  next
        mov  ecx, dword ptr [esi + 8]
        cmp  ecx, dword ptr [edx + 8]
        jne  next
        mov  ecx, dword ptr [esi + 0xC]
        cmp  ecx, dword ptr [edx + 0xC]
        je   found
    next:
        add  esi, 0x10
        inc  ebx
        cmp  ebx, {len(PREF_FRAME_ORDER)}
        jb   find
    generic:
        xor  ebx, ebx
    gscale:
        mov  ecx, dword ptr [edx + ebx * 4]
        imul ecx, eax
        sar  ecx, 4
        mov  dword ptr [edx + ebx * 4], ecx
        inc  ebx
        cmp  ebx, 4
        jb   gscale
        dec  dword ptr [edx + 8]
        dec  dword ptr [edx + 0xC]
        jmp  dispatch
    found:
        lea  ecx, [eax - 0x11]
        imul ecx, ecx, {len(PREF_FRAME_ORDER)}
        add  ecx, ebx
        lea  esi, [ecx * 8 + {tbl}]
        movsx ecx, word ptr [esi]
        mov  dword ptr [edx], ecx
        movsx ecx, word ptr [esi + 2]
        mov  dword ptr [edx + 4], ecx
        movsx ecx, word ptr [esi + 4]
        mov  dword ptr [edx + 8], ecx
        movsx ecx, word ptr [esi + 6]
        mov  dword ptr [edx + 0xC], ecx
    dispatch:
        pop  esi
        pop  ebx
        pop  ecx
        mov  edx, dword ptr [esp + 8]
        cmp  dword ptr [edx + 0x20], 0
        jne  filled
        jmp  {HOLLOW_FLAT}
    filled:
        jmp  {DEVFILL}
    native:
        jmp  {BBS}
    """


def pref_frame_keys() -> bytes:
    """g_pref_frame_keys: the native rects of PREF_FRAME_ORDER (scaling_laws.PREF_FRAME_NATIVE), 4 dwords each."""
    return b"".join(struct.pack("<4i", *SL.PREF_FRAME_NATIVE[n]) for n in PREF_FRAME_ORDER)


def pref_frame_table() -> bytes:
    """g_pref_frame_tbl: for g = 17 .. G_MAX, for each frame of PREF_FRAME_ORDER, scaling_laws.prefwin_layout(g)'s
    inclusive device rect as 4 int16 (emitted from the law, never retyped)."""
    out = b""
    for g in range(NATIVE_G + 1, G_MAX + 1):
        lay = SL.prefwin_layout(g)
        out += b"".join(struct.pack("<4h", *lay[n]) for n in PREF_FRAME_ORDER)
    return out


def emit_w6a() -> dict:
    """{name: (offset, bytes)} -- every branch target an absolute engine / cave VA (the bytes are position-bound)."""
    fns = {"thunk_pref_gwinit": asm_gwinit, "thunk_pref_boxframe": asm_boxframe, "t_pref_bd": asm_pref_bd,
           "t_pref_frame": asm_pref_frame, "t_pref_tabrow": asm_pref_tabrow}
    data = {"g_pref_frame_keys": pref_frame_keys, "g_pref_frame_tbl": pref_frame_table}
    out = {}
    for name, off, end in W6A_THUNKS:
        b = data[name]() if name in data else assemble(fns[name](), PCAVE2 + off)
        assert off + len(b) <= end, (name, len(b))
        out[name] = (off, b)
    return out


def asm_btnzoom():
    return f"""
        cmp  ecx, {BTNS[0]}
        jb   dllchk
        cmp  ecx, {BTNS[-1]}
        jbe  arm
    dllchk:
        mov  eax, dword ptr [{G_DLL_LO}]
        test eax, eax
        je   plain
        cmp  ecx, eax
        jb   plain
        cmp  ecx, dword ptr [{G_DLL_HI}]
        ja   plain
    arm:
        inc  dword ptr [{G_POPUP_ACTIVE}]
        call {CONTENT_DRAW}
        cmp  dword ptr [{G_POPUP_ACTIVE}], 0
        jle  done
        dec  dword ptr [{G_POPUP_ACTIVE}]
    done:
        ret
    plain:
        jmp  {CONTENT_DRAW}
    """


def asm_sbzoom():
    return f"""
        cmp  ecx, {SLIDERS[0]}
        je   go
        cmp  ecx, {SLIDERS[1]}
        je   go
        cmp  ecx, {SLIDERS[2]}
        je   go
        cmp  ecx, {SLIDERS[3]}
        je   go
        cmp  ecx, dword ptr [{G_DLL_SLIDER}]
        je   go
        jmp  {SB_DRAW}
    go:
        mov  dword ptr [{G_NETWIN_ACTIVE}], 1
        call {SB_DRAW}
        mov  dword ptr [{G_NETWIN_ACTIVE}], 0
        ret
    """


def asm_mapfont():
    # thiscall shim in front of Font_init: ecx = Font (preserved), stack at entry
    # [esp]=site ret, [esp+4]=name, [esp+8]=height, [esp+C]=style.
    # size' = native*(16 + (g-16)*pct/100) >> 4; g<=16 -> untouched (native).
    # pct=100 -> native*g>>4 (== thunk_hud_font); pct=0 -> native exact.
    return f"""
        call {ENSURE_SCALE}
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  go
        push ecx
        sub  eax, 16
        imul eax, dword ptr [{G_MAP_FONT_PCT}]
        mov  ecx, 100
        cdq
        idiv ecx
        add  eax, 16
        imul eax, dword ptr [esp + 0xC]
        sar  eax, 4
        mov  dword ptr [esp + 0xC], eax
        pop  ecx
    go:
        push {FONT_INIT}
        ret
    """


def asm_show(win_table_va):
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  done
        push ecx
        push esi
        push edi
        imul edx, eax, 350
        sar  edx, 4
        mov  ecx, dword ptr [{SW}]
        sar  ecx, 1
        sub  ecx, edx
        mov  edx, dword ptr [{PREF_144}]
        sub  edx, dword ptr [{PREF_13C}]
        mov  dword ptr [{PREF_13C}], ecx
        add  ecx, edx
        mov  dword ptr [{PREF_144}], ecx
        imul edx, eax, 618
        sar  edx, 4
        mov  ecx, dword ptr [{SH}]
        sub  ecx, edx
        mov  edx, dword ptr [{PREF_148}]
        sub  edx, dword ptr [{PREF_140}]
        mov  dword ptr [{PREF_140}], ecx
        add  ecx, edx
        mov  dword ptr [{PREF_148}], ecx
        call {T_FDIRECT_A14B}
        test eax, eax
        jz   redraw
        mov  esi, {win_table_va}
        mov  edi, 15
    floop:
        mov  ecx, dword ptr [esi]
        cmp  dword ptr [ecx + 0x970], 0
        je   fnext
        mov  dword ptr [ecx + 0x970], eax
    fnext:
        add  esi, 4
        dec  edi
        jnz  floop
    redraw:
        mov  esi, {win_table_va}
        mov  edi, 19
    rloop:
        mov  ecx, dword ptr [esi]
        mov  eax, dword ptr [ecx]
        call dword ptr [eax + 0xF8]
        add  esi, 4
        dec  edi
        jnz  rloop
        pop  edi
        pop  esi
        pop  ecx
    done:
        push ebp
        mov  ebp, esp
        sub  esp, 0x40
        jmp  {SHOW_RESUME}
    """


def assemble(src: str, va: int) -> bytes:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(src, addr=va)
    return bytes(code)


def main() -> int:
    order = [
        ("thunk_pref_gwinit", asm_gwinit),
        ("thunk_pref_ffscale", asm_ffscale),
        ("thunk_pref_dlg2", asm_dlg2),
        ("thunk_pref_attach", asm_attach),
        ("thunk_pref_boxframe", asm_boxframe),
        ("thunk_pref_btnzoom", asm_btnzoom),
        ("thunk_pref_sbzoom", asm_sbzoom),
    ]
    off = BASE_OFF
    layout = []
    for name, fn in order:
        blob = assemble(fn(), PCAVE2 + off)
        layout.append((name, off, blob))
        off = (off + len(blob) + 0xF) & ~0xF
    assert off <= BLOCK_LIMIT, f"packed block overruns 0x{BLOCK_LIMIT:04X}: end=0x{off:04X}"

    # tail block: registry slots + map-font thunk + relocated show/table
    layout.append(("g_dll_pref_lo", DLL_PREF_LO_OFF, (0).to_bytes(4, "little")))
    layout.append(("g_dll_pref_hi", DLL_PREF_HI_OFF, (0).to_bytes(4, "little")))
    layout.append(("g_dll_pref_slider", DLL_PREF_SLIDER_OFF, (0).to_bytes(4, "little")))
    layout.append(("g_map_font_pct", MAP_FONT_PCT_OFF, (100).to_bytes(4, "little")))
    mapfont = assemble(asm_mapfont(), PCAVE2 + MAP_FONT_OFF)
    assert MAP_FONT_OFF + len(mapfont) <= SHOW_OFF, f"thunk_map_font overruns: {len(mapfont)}B"
    layout.append(("thunk_map_font", MAP_FONT_OFF, mapfont))
    assert MAP_FONT_OFF + len(mapfont) <= BIG_F4_OFF < BIG_F4_OFF + 4 <= SHOW_OFF
    layout.append(("g_big_f4", BIG_F4_OFF, (1).to_bytes(4, "little")))
    show = assemble(asm_show(PCAVE2 + TABLE_OFF), PCAVE2 + SHOW_OFF)
    assert SHOW_OFF + len(show) <= TABLE_OFF, f"thunk_pref_show overruns: {len(show)}B"
    layout.append(("thunk_pref_show", SHOW_OFF, show))
    table = b"".join(v.to_bytes(4, "little") for v in BTNS + SLIDERS)
    layout.append(("g_pref_wins", TABLE_OFF, table))
    end = TABLE_OFF + len(table)
    assert end <= CAVE_LIMIT, f"overruns pcave2: end=0x{end:04X} > 0x{CAVE_LIMIT:04X}"

    for name, o, blob in layout:
        print(f"{name:22s} offset 0x{o:04X}  {len(blob):3d}B  (VA 0x{PCAVE2 + o:06X})")
    print(f"packed block end 0x{off:04X} / 0x{BLOCK_LIMIT:04X}; tail end 0x{end:04X} / 0x{CAVE_LIMIT:04X}\n")
    for name, o, blob in layout:
        hexs = " ".join(f"{b:02X}" for b in blob)
        print(f"      - id: {name}\n        offset: 0x{o:X}")
        if name.startswith("g_"):
            print("        data: true")
        print(f'        bytes: "{hexs}"\n')

    # cross-check the window-position law against scaling_laws
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import prefwin_window_pos, popup_scale_floor, map_label_font_size
    for (sw, sh, g, want) in ((3840, 2160, 40, (1045, 615)), (1600, 1200, 25, (254, 235)),
                              (1920, 1080, 22, (479, 231)), (1024, 768, 16, (162, 150))):
        got = prefwin_window_pos(sw, sh, g)
        assert got == want, (sw, sh, g, got, want)
        asm_x = (sw >> 1) - ((350 * g) >> 4)
        asm_y = sh - ((618 * g) >> 4)
        assert (asm_x, asm_y) == got, (g, asm_x, asm_y, got)
    assert popup_scale_floor(14, 40) == 35 and popup_scale_floor(14, 25) == 21
    # thunk_map_font arithmetic == the law at the pinned corners
    for g in (16, 22, 25, 40):
        for pct in (0, 25, 50, 75, 100):
            for native in (1, 4, 8, 12):
                want = map_label_font_size(native, g, pct)
                got = native if g <= 16 else (native * (16 + (g - 16) * pct // 100)) >> 4
                assert got == want, (native, g, pct, got, want)
    assert map_label_font_size(12, 40, 100) == 30 and map_label_font_size(12, 40, 0) == 12
    print("asm arithmetic == scaling_laws (prefwin_window_pos + map_label_font_size)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
