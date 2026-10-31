"""Assemble the base-production-picker (ProdPicker) relayout thunks.

Group `prodpicker_relayout`.  Every thunk here is a PORT of scaling_laws.py's
prodpicker_* laws (swept in tests/test_scaling_laws.py); if a thunk disagrees
with the module, the thunk has the bug.

Measurement that produced the laws: work\\frida_prodpicker.log, hook_prodpicker.js
v2/v3 at 3840x2160 (g=40), 1600x1200 (g=25), 1920x1080 (g=22) and 1024x768
(g=16 = vanilla).  Three defects, one thunk each (plus the gwinit exemption
which lives in assemble_basewin.py):

  thunk_pp_layout  -- ProdPicker_build_items 0x4939A4 (replaces the 12-byte
                      pitch-copy pair `mov edx,[esi+0xA838]; mov [esi+0xA820],edx`).
                      pitch  = fl(108*g/16)          [law prodpicker_row_pitch]
                      colw   = (win_w - fl(0x51*g/16)) / 5  [prodpicker_col_w]
                      Vanilla's 108 is a ctor seed that NEVER scaled — 4 rows of
                      108 filled 432 of a 1225-tall device window (the squashed
                      rows + huge empty body).  Everything else in the cell
                      follows: rect height, facility icon (pitch*3/7), unit zoom
                      (pitch*2/3), and the button row's y.
                      The 0x51 grid margin is a NATIVE additive constant living
                      inside a DEVICE width (the mixed-space class) — unscaled
                      the grid's side margins stay 27/61px at 4K vs 67/147.
                      Register contract at the site: ecx = win_w-0x51, edi = the
                      engine's colw, esi = picker, eax = win_w-0x51 (the engine
                      divides eax by edi at 0x4939B7 to recompute the column
                      count, so eax must track the same margin edi was built
                      from).  edx/ecx are dead across the site (edx is reloaded
                      by cdq at 0x4939B6, ecx at 0x4939B0).

  thunk_pp_font    -- Font_init call-target redirect, sites 0x4939DB (cellName,
                      pushes 12) and 0x493A61 (button, pushes 14).  Both sizes
                      are FIXED literals — measured byte-identical Font structs
                      at all four resolutions.  Scales the already-pushed size
                      arg, then tail-jmps Font_init.  [prodpicker_font_size]

  thunk_pp_font10  -- Font_init redirect for the stats font, site 0x493A4B.
                      Vanilla computes max(10, colw/15); colw is now SCALED, so
                      passing it through thunk_pp_font would double-scale (338/15
                      = 22 -> 55 @4K).  Natively colw is always 135, so the max()
                      floor always wins and vanilla == 10: force fl(10*g/16).
                      (The `big` font at 0x493A13 is deliberately NOT redirected
                      — its max(24,...) is likewise colw-driven, but the static
                      census found NO reader for +0xAC4 anywhere in the picker.)

  thunk_pp_btn     -- BaseButton_init call-target redirect, all NINE sites
                      (0x494B80/BF4/C59/CBF/D25/DBD/E23/E89/EF4).  Implements
                      prodpicker_button_rects outright: rewrites the pushed
                      x,y,w,h.  Vanilla's centring math is CORRECT (it was only
                      fed the double-scaled width), but its constants — btn 100x20,
                      gap 3, pad 0x20, row gap-y 8 — are native, so the row is
                      recomputed here from the law instead of patching the
                      literals at 9+ sites.
                      Button POSITION is the INIT ORDER, not the slot index
                      (measured: slot0 is the RIGHTMOST, slot3 second, slot1
                      fourth).  Rather than track it statefully (a counter goes
                      stale across opens, and would break on a variant that does
                      not init HELP first), the thunk INVERTS the caller's own
                      arithmetic: the caller passes x = xl_nat + k*103, where
                      xl_nat = (W - 103*count - 0x20)/2 and 103 = [+0xB70]+3
                      (both left untouched), so k = (x_caller - xl_nat)/103
                      recovers the position with NO state at all.
                      Tail-jmps BaseButton_init 0x607210, whose own baked entry
                      detour is untouched.

Cave: the free pcave2 TAIL (0xFDB0..0x10000, 596 B measured by the patch-surface
census).  Nothing here is entered from a `push imm32; ret` chain.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000

# --- sentinel placeholders (resolved by the yaml {abs32:} tokens) -----------
G = 0xDEADBE00                # g_popup_scale_num        -> 0x668740
PERIOD = 0xDEADBE04           # g_stripe_period          -> 0x66879C
SENT = {G: "{abs32:g_popup_scale_num}", PERIOD: "{abs32:g_stripe_period}"}

FONT_INIT = 0x618F40          # Font_init(name, size, style), thiscall ecx=font
BTN_INIT = 0x607210           # BaseButton_init (its own entry detour is ours)
PICKER = 0x6A8044             # ProdPicker = BaseWin_g + 0xA1C

COPY4 = 0x5DFF00              # Buffer_copy_4, thiscall RET 0x1C
DRAW_VISIBLE = 0x493C70       # ProdPicker_draw_visible, fastcall plain RET

# picker field offsets (terranx.h)
F_CANVAS = 0x444              # GraphicWin canvas (struct Buffer)
F_WINW = 0x4C4                # GraphicWin canvas w
F_COLS = 0xA810
F_COLW = 0xA81C
F_VISROWS = 0xA814
F_PITCH = 0xA820
F_BTNCOUNT = 0xB6C

# vanilla magnitudes — measured at g=16, never eyeballed
PITCH_NATIVE = 108
GRID_MARGIN = 0x51
BTN_W, BTN_H, BTN_GAP, BTN_PAD, BTN_GAPY = 100, 0x14, 3, 0x20, 8
STATS_NATIVE = 10
SCROLL_X, SCROLL_R = 0x15, 0x19   # scroll_to blit left edge / right inset

# --- cave layout (free tail) ------------------------------------------------
LAYOUT_OFF = 0xFDB0
FONT_OFF = 0xFE00
FONT10_OFF = 0xFE30
BTN_OFF = 0xFE60
CAVE_END = 0x10000
# pass-3 thunks (2026-08-03b) go in the freed interior slot at 0x37F6..0x3A00
# (vacated fieldpads-v3 / fe_pair_remap-v3). The pcave2 TAIL has only 233B left
# after thunk_pp_btn and three thunks do not fit there. NB: verify occupancy
# against patches.yaml, not against this file — see [[feedback-cave-ledger-lengths]].
FRAME_OFF = 0x3800
CELLRECT_OFF = 0x3840
BTNFRAME_OFF = 0x38A0
# pass-4 adapter (2026-08-04): free tail of the same freed slot (btnframe ends
# 0x391B; next occupant 0x3A00 — ledger + live-exe verified)
BOXSPRITE_OFF = 0x3930
# pass-5 (2026-08-05): boxsprite ends 0x3953; 0x3958..0x3A00 re-verified free
# (live bytes all zero, next occupant starts exactly 0x3A00).  measure goes to
# the pcave2 TAIL (pp_btn ends 0xFF17; 0xFF18..0x10000 verified all zero).
HITY_OFF = 0x3960
HITX_OFF = 0x3980
TITLEPAD_OFF = 0x39B0
MEASURE_OFF = 0xFF20
# 2026-10-10 one-row scroll blit: pcave2 0x302FA..0x30FFF is ledger-declared free
# (the Caviar grow); slot chosen with `cave_map.py --fit` / `--at`.
SCROLLBLIT_OFF = 0x30E00
SCROLLBLIT_END = 0x30E80

MEASURE_FN = 0x5DC360         # wrapped-text height measure (ret 8, clean entry)
# picker static stats-font fields (picker 0x6A8044 + 0xAEC block)
STATS_F0 = 0x6A8B30
STATS_LH = 0x6A8B3C
STATS_F4 = 0x6A8B40

# pass-4 dispatch targets (fixed cave VAs, precedent thunk_pref_boxframe)
HOLLOW_FLAT = 0xA0C140        # thunk_box_thick_hollow_flat (K-wide, hollow)
DEVFILL = 0xA102A0            # thunk_box_thick_devfill (K-wide + device fill)
BOX_SPRITE = 0x5E2DD3         # native Buffer_box_sprite

FRAME_L = 0x17
FRAME_RSUB = 0x4E
CELL_BASE = 0x17          # shared base of both x insets (L = base+4, R = base+4-3)
CELL_GAP = 4              # frame->grid gutter
CELL_SEP = 3              # inter-cell separation
BTNFRAME_INSET = 3


def asm_layout():
    """pitch + colw.  g<=16 reproduces vanilla's two displaced instructions."""
    return f"""
        mov  edx, dword ptr [{G}]
        cmp  edx, 0x10
        jle  native
        add  ecx, {GRID_MARGIN}
        imul eax, edx, {GRID_MARGIN}
        sar  eax, 4
        sub  ecx, eax
        mov  eax, ecx
        push ecx
        cdq
        mov  ecx, 5
        idiv ecx
        mov  edi, eax
        pop  eax
        mov  edx, dword ptr [{G}]
        imul edx, edx, {PITCH_NATIVE}
        sar  edx, 4
        mov  dword ptr [esi + {F_PITCH}], edx
        ret
    native:
        mov  edx, dword ptr [esi + 0xA838]
        mov  dword ptr [esi + {F_PITCH}], edx
        ret
    """


def asm_font():
    """Scale the already-pushed Font_init size arg.  After `push eax` the size
    sits at [esp+0xC] (ret at +4, name at +8)."""
    return f"""
        push eax
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  done
        imul eax, dword ptr [esp + 0xC]
        sar  eax, 4
        mov  dword ptr [esp + 0xC], eax
    done:
        pop  eax
        jmp  {FONT_INIT}
    """


def asm_font10():
    """Force the stats size to fl(10*g/16) (vanilla == 10 at every native colw)."""
    return f"""
        push eax
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  done
        imul eax, eax, {STATS_NATIVE}
        sar  eax, 4
        mov  dword ptr [esp + 0xC], eax
    done:
        pop  eax
        jmp  {FONT_INIT}
    """


def asm_btn():
    """Port of scaling_laws.prodpicker_button_rects.

    Stack at entry (the E8 has pushed ret):
        [esp]=ret [+4]=label [+8]=id [+0xC]=x [+0x10]=y [+0x14]=w [+0x18]=h
        [+0x1C]=parent [+0x20]=a9
    """
    return f"""
        cmp  dword ptr [esp + 0x1C], {PICKER}
        jne  pass
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  pass
        push ebx
        push ecx
        push edx
        push esi
        push edi
        mov  esi, dword ptr [{G}]
        mov  eax, dword ptr [{PICKER + F_WINW}]
        mov  edx, dword ptr [{PICKER + F_BTNCOUNT}]
        imul edx, edx, {BTN_W + BTN_GAP}
        sub  eax, edx
        sub  eax, {BTN_PAD}
        cdq
        sub  eax, edx
        sar  eax, 1
        mov  ecx, dword ptr [esp + 0x20]
        sub  ecx, eax
        mov  eax, ecx
        cdq
        mov  ecx, {BTN_W + BTN_GAP}
        idiv ecx
        mov  edi, eax
        imul ebx, esi, {BTN_W}
        sar  ebx, 4
        imul ecx, esi, {BTN_GAP}
        sar  ecx, 4
        add  ecx, ebx
        mov  eax, dword ptr [{PICKER + F_WINW}]
        mov  edx, dword ptr [{PICKER + F_BTNCOUNT}]
        imul edx, ecx
        sub  eax, edx
        push ecx
        imul ecx, esi, {BTN_PAD}
        sar  ecx, 4
        sub  eax, ecx
        pop  ecx
        cdq
        sub  eax, edx
        sar  eax, 1
        imul edi, ecx
        add  eax, edi
        mov  dword ptr [esp + 0x20], eax
        mov  eax, dword ptr [{PICKER + F_PITCH}]
        imul eax, dword ptr [{PICKER + F_VISROWS}]
        imul edx, esi, {BTN_GAPY}
        sar  edx, 4
        add  eax, edx
        mov  dword ptr [esp + 0x24], eax
        mov  dword ptr [esp + 0x28], ebx
        imul eax, esi, {BTN_H}
        sar  eax, 4
        mov  dword ptr [esp + 0x2C], eax
        pop  edi
        pop  esi
        pop  edx
        pop  ecx
        pop  ebx
    pass:
        jmp  {BTN_INIT}
    """


def asm_frame():
    """Outer 9-slice frame — site 0x494993 (7B `mov [ebp-0x3C],0x17`).
    On entry eax holds vanilla's W-0x4E+0x17 and ebx is the picker; we overwrite
    the stored L and eax (the R, stored by the next instruction).
    v2 (pass 4): L = bp(0x17) EXACTLY — the BaseWin console frame's left stroke
    lives at that cascade (bright bevel exposed 1px at g=22/25 when L was
    bp(27)-bp(4)); vanilla draws the two frames coincident at x=23 and this
    keeps them coincident at every g.  R mirrors the left stroke-to-grid
    gutter; the K-wide stroke (drawn inward by thunk_pp_boxsprite's dispatch)
    cancels out of the rect: R = 5*colw + bp(0x18) + bp(0x1B) - bp(0x17).
    g=16: L=23, R=675+24+27-23=703 — algebraic identity.
    Law prodpicker_frame_rect (v2)."""
    return f"""
        push edx
        mov  edx, dword ptr [{G}]
        cmp  edx, 0x10
        jle  native
        imul eax, edx, {FRAME_L}
        sar  eax, 4
        mov  dword ptr [ebp - 0x3C], eax
        push ecx
        mov  ecx, eax
        imul eax, edx, {CELL_BASE + CELL_GAP}
        sar  eax, 4
        sub  eax, ecx
        imul ecx, edx, {CELL_BASE + CELL_GAP - CELL_SEP}
        sar  ecx, 4
        add  eax, ecx
        mov  edx, dword ptr [ebx + 0xA81C]
        lea  edx, [edx + edx*4]
        add  eax, edx
        pop  ecx
        pop  edx
        ret
    native:
        mov  dword ptr [ebp - 0x3C], {FRAME_L}
        pop  edx
        ret
    """


def asm_boxsprite():
    """Pass-4 Buffer_box_sprite dispatch for the picker's three 9-slice draws
    (grid frame 0x4949A0, cell outline 0x492889, button-box frame 0x494F7C —
    call-target redirects, rects ALREADY device-scaled by the pass-3 thunks).
    Clone of thunk_pref_boxframe's dispatch minus its rect scaling:
    [params+0x20] != 0 -> thunk_box_thick_devfill, else hollow_flat (K-wide
    band-map strokes).  g<=16 -> plain native draw (identity)."""
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  native
        mov  eax, dword ptr [esp + 8]
        cmp  dword ptr [eax + 0x20], 0
        jne  devfill
        jmp  {HOLLOW_FLAT}
    devfill:
        jmp  {DEVFILL}
    native:
        jmp  {BOX_SPRITE}
    """


def asm_cellrect():
    """Cell-rect insets — site 0x492829, 21 bytes replaced (the three `add r,4`,
    the `sub edi,3`, the two stores and the `sub ecx,3`).
    On entry: eax = col*colw+0x17, edx = rowY, ecx = rowY+pitch,
              edi = (col+1)*colw+0x17, ebp = frame.
    On exit the engine expects edx = T, edi = R, ecx = B, eax = L-4 (it adds the
    4 back at 0x49284D), plus [ebp-0xC] = T and [ebp-8] = R already stored.
    Law prodpicker_cell_rect."""
    return f"""
        push ebx
        mov  ebx, dword ptr [{G}]
        cmp  ebx, 0x10
        jle  native
        push esi
        imul esi, ebx, {CELL_BASE + CELL_GAP - CELL_SEP}
        sar  esi, 4
        sub  edi, {CELL_BASE}
        add  edi, esi
        imul esi, ebx, {CELL_GAP}
        sar  esi, 4
        add  edx, esi
        imul esi, ebx, {CELL_GAP - CELL_SEP}
        sar  esi, 4
        add  ecx, esi
        imul esi, ebx, {CELL_BASE + CELL_GAP}
        sar  esi, 4
        sub  eax, {CELL_BASE + CELL_GAP}
        add  eax, esi
        pop  esi
        jmp  store
    native:
        add  edi, {CELL_GAP - CELL_SEP}
        add  edx, {CELL_GAP}
        add  ecx, {CELL_GAP - CELL_SEP}
    store:
        mov  dword ptr [ebp - 0xC], edx
        mov  dword ptr [ebp - 8], edi
        pop  ebx
        ret
    """


def asm_btnframe():
    """Button-row frame — site 0x494F54, replaces `mov eax,3` (5B).
    The caller has just loaded edx/ecx/edi/esi = L/R/T/B from locals the NATIVE
    layout block wrote, then insets them by eax on each edge and stores them
    back.  We recompute the rect from the same quantities the buttons use and
    set eax = 0 so the following four adds/subs are no-ops.
    ebx (the picker) must survive — the frame call reads [ebx+0x444].
    Law prodpicker_button_frame."""
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  native
        imul ecx, eax, {BTN_GAP}
        sar  ecx, 4
        push ecx
        imul edx, eax, {BTN_W}
        sar  edx, 4
        lea  edi, [edx + ecx]
        mov  esi, dword ptr [ebx + {F_WINW}]
        mov  ecx, dword ptr [ebx + {F_BTNCOUNT}]
        imul ecx, edi
        sub  esi, ecx
        imul ecx, eax, {BTN_PAD}
        sar  ecx, 4
        sub  esi, ecx
        mov  ecx, esi
        sar  ecx, 31
        sub  esi, ecx
        sar  esi, 1
        mov  ecx, dword ptr [ebx + {F_BTNCOUNT}]
        dec  ecx
        imul ecx, edi
        add  ecx, esi
        add  ecx, edx
        mov  edi, dword ptr [ebx + {F_PITCH}]
        imul edi, dword ptr [ebx + {F_VISROWS}]
        imul edx, eax, {BTN_GAPY}
        sar  edx, 4
        add  edi, edx
        imul edx, eax, {BTN_H}
        sar  edx, 4
        add  edx, edi
        pop  eax
        sub  esi, eax
        add  ecx, eax
        sub  edi, eax
        add  edx, eax
        xchg edx, esi
        xor  eax, eax
        ret
    native:
        mov  eax, {BTNFRAME_INSET}
        ret
    """


def asm_hity():
    """Hit-grid y — cut thunk @0x4941CA (7B: cdq + idiv [esi+0xA820]).
    select_from_xy 0x4941C0 maps row = y/pitch with NO inset, so the bottom
    bp(4) band of every drawn cell selects the next row.  y -= bp(4) at EVERY
    g (law prodpicker_hit_cell; bp identity at g=16 -> native 4 — deliberate
    fix of vanilla's own skew, user-requested pass 5b).  Entry: eax = y
    (loaded at 0x4941C3), esi = picker; ecx DEAD here, edx dies to cdq."""
    return f"""
        mov  ecx, dword ptr [{G}]
        imul ecx, ecx, {CELL_GAP}
        sar  ecx, 4
        sub  eax, ecx
        cdq
        idiv dword ptr [esi + {F_PITCH}]
        ret
    """


def asm_hitx():
    """Hit-grid x — cut thunk @0x4941D9 (17B: mov eax,[ebp+8] / cdq /
    imul edi,[esi+0xA810] / idiv [esi+0xA81C]).  x -= bp(0x1B) at EVERY g
    (bp identity at g=16 -> native 0x1B — deliberate vanilla fix, pass 5b).
    ecx is LIVE across the cut (old selection, compared at 0x4941F4) — only
    eax/edx are scratch; edi carries row -> row*count exactly as vanilla."""
    return f"""
        mov  eax, dword ptr [ebp + 8]
        mov  edx, dword ptr [{G}]
        imul edx, edx, {CELL_BASE + CELL_GAP}
        sar  edx, 4
        sub  eax, edx
        imul edi, dword ptr [esi + 0xA810]
        cdq
        idiv dword ptr [esi + 0xA81C]
        ret
    """


def asm_titlepad():
    """Cell title pad — cut thunk @0x492AC2 (20B).  Vanilla: rect.y = T+5,
    clip bottom = T+3m+5 (T already carries the native +1 interior inset,
    which stays 1 at every g).  Substitute pad' = bp(6)-1 so the TOTAL offset
    from the cell top is exactly bp(6) (law prodpicker_title_pad; native
    identity bp(6)-1 == 5 algebraic).  Entry: edx = T, eax = m (title-font
    metric); writes [ebp-0x30]/[ebp-0x28]; ecx scratch (vanilla clobbers it);
    ebx LIVE (item idx) — preserved."""
    return f"""
        push ebx
        mov  ebx, dword ptr [{G}]
        cmp  ebx, 0x10
        jle  native
        imul ebx, ebx, {CELL_GAP + 2}
        sar  ebx, 4
        dec  ebx
        jmp  apply
    native:
        mov  ebx, 5
    apply:
        mov  ecx, dword ptr [ebp - 0xC]
        add  edx, ebx
        mov  dword ptr [ebp - 0x30], edx
        lea  ecx, [ecx + eax*2]
        add  eax, ecx
        add  eax, ebx
        mov  dword ptr [ebp - 0x28], eax
        pop  ebx
        ret
    """


def asm_measure():
    """Bottom-block height — call-target redirect @0x492B6D (call 0x5DC360).
    The site computes y1 = (cell_B - 1) - h; vanilla h = n_lines * m with the
    scaled stats font's m sublinear (23 @4K vs proportional 25) -> the block
    sat ~3px low and the "1-1-2" line nearly touched the cell bottom.
    Substitute h' = h * (bp(11)-1) / m — per line exactly bp(11) below the
    cell bottom (law prodpicker_stats_h; native identity h*10/10).  m read
    live from the picker's stats font (f0>=0 ? f4+f0 : lh) only to recover
    the line count.  0x5DC360 is ret 8 (callee-clean) with a CLEAN entry, so
    the wrapper re-pushes both args and mirrors the ret 8."""
    return f"""
        push dword ptr [esp + 8]
        push dword ptr [esp + 8]
        call {MEASURE_FN}
        mov  ecx, dword ptr [{G}]
        cmp  ecx, 0x10
        jle  done
        mov  ecx, dword ptr [{STATS_F0}]
        test ecx, ecx
        jl   use_lh
        add  ecx, dword ptr [{STATS_F4}]
        jmp  got_m
    use_lh:
        mov  ecx, dword ptr [{STATS_LH}]
    got_m:
        test ecx, ecx
        jle  done
        test eax, eax
        jle  done
        push ebx
        mov  ebx, ecx
        mov  ecx, dword ptr [{G}]
        imul ecx, ecx, 11
        sar  ecx, 4
        dec  ecx
        imul eax, ecx
        cdq
        idiv ebx
        pop  ebx
    done:
        ret  8
    """


def asm_scrollblit():
    """One-row scroll blit — call-target redirect of BOTH Buffer_copy_4 calls in
    ProdPicker_scroll_to (0x493D69 scroll up, 0x493E23 scroll down).
    Law prodpicker_scroll_blit / prodpicker_scroll_redraws.

    Entry (E8 pushed ret): ecx = picker canvas (picker+0x444; caller `mov ecx,edi`
    with edi = esi+0x444), [esp+4] src, +8 sx, +0xC sy, +0x10 dx, +0x14 dy,
    +0x18 w, +0x1C h.  Buffer_copy_4 is thiscall RET 0x1C; eax/ecx/edx are dead
    after it at both sites (0x493D6E / 0x493E28 reload edi and use only
    esi/edi/ebx), so they are scratch here; ebx/esi/edi/ebp are untouched.
      g<=16                -> tail-jmp Buffer_copy_4 verbatim (vanilla).
      pitch % P != 0       -> drop the blit: consume ret+7 args, push ret back,
                              tail-jmp ProdPicker_draw_visible (fastcall, plain
                              RET) -- every visible cell redrawn on its own
                              stripe grid; the caller still draws the exposed row
                              and soft-updates, exactly as after vanilla's blit.
      else                 -> R = cols*colw + bp(0x19); w = (R - 0x15 + 3) & ~3;
                              sx = dx = R - w; tail-jmp Buffer_copy_4.
    P = g_stripe_period (written with g by thunk_ensure_scale; >= 2)."""
    return f"""
        mov  eax, dword ptr [{G}]
        cmp  eax, 0x10
        jle  native
        mov  eax, dword ptr [ecx + {F_PITCH - F_CANVAS}]
        xor  edx, edx
        div  dword ptr [{PERIOD}]
        test edx, edx
        jnz  redraw
        mov  eax, dword ptr [ecx + {F_COLW - F_CANVAS}]
        imul eax, dword ptr [ecx + {F_COLS - F_CANVAS}]
        mov  edx, dword ptr [{G}]
        imul edx, edx, {SCROLL_R}
        sar  edx, 4
        add  eax, edx
        lea  edx, [eax - {SCROLL_X - 3}]
        and  edx, -4
        mov  dword ptr [esp + 0x18], edx
        sub  eax, edx
        mov  dword ptr [esp + 8], eax
        mov  dword ptr [esp + 0x10], eax
    native:
        jmp  {COPY4}
    redraw:
        pop  eax
        add  esp, 0x1C
        push eax
        sub  ecx, {F_CANVAS}
        jmp  {DRAW_VISIBLE}
    """


def emit(name, off, asm):
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(asm, addr=PCAVE2 + off)
    blob = bytes(code)
    out, i = [], 0
    while i < len(blob):
        for sent, tok in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(tok)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    print(f"{name}  {len(blob)} bytes @ pcave2+{off:#x} (VA {PCAVE2 + off:#x})"
          f" .. end {off + len(blob):#x}")
    print('        bytes: "' + " ".join(out) + '"')
    print()
    return len(blob)


def main():
    n = emit("thunk_pp_layout", LAYOUT_OFF, asm_layout())
    assert LAYOUT_OFF + n <= FONT_OFF, "pp_layout overruns its slot"
    n = emit("thunk_pp_font", FONT_OFF, asm_font())
    assert FONT_OFF + n <= FONT10_OFF, "pp_font overruns its slot"
    n = emit("thunk_pp_font10", FONT10_OFF, asm_font10())
    assert FONT10_OFF + n <= BTN_OFF, "pp_font10 overruns its slot"
    n = emit("thunk_pp_btn", BTN_OFF, asm_btn())
    assert BTN_OFF + n <= CAVE_END, "pp_btn overruns the cave tail"
    n = emit("thunk_pp_frame", FRAME_OFF, asm_frame())
    assert FRAME_OFF + n <= CELLRECT_OFF, "pp_frame overruns its slot"
    n = emit("thunk_pp_cellrect", CELLRECT_OFF, asm_cellrect())
    assert CELLRECT_OFF + n <= BTNFRAME_OFF, "pp_cellrect overruns its slot"
    n = emit("thunk_pp_btnframe", BTNFRAME_OFF, asm_btnframe())
    assert BTNFRAME_OFF + n <= BOXSPRITE_OFF, "pp_btnframe overruns its slot"
    n = emit("thunk_pp_boxsprite", BOXSPRITE_OFF, asm_boxsprite())
    assert BOXSPRITE_OFF + n <= HITY_OFF, "pp_boxsprite overruns its slot"
    n = emit("thunk_pp_hity", HITY_OFF, asm_hity())
    assert HITY_OFF + n <= HITX_OFF, "pp_hity overruns its slot"
    n = emit("thunk_pp_hitx", HITX_OFF, asm_hitx())
    assert HITX_OFF + n <= TITLEPAD_OFF, "pp_hitx overruns its slot"
    n = emit("thunk_pp_titlepad", TITLEPAD_OFF, asm_titlepad())
    assert TITLEPAD_OFF + n <= 0x3A00, "pp_titlepad overruns the freed slot"
    n = emit("thunk_pp_measure", MEASURE_OFF, asm_measure())
    assert MEASURE_OFF + n <= CAVE_END, "pp_measure overruns the cave tail"
    n = emit("thunk_pp_scrollblit", SCROLLBLIT_OFF, asm_scrollblit())
    assert SCROLLBLIT_OFF + n <= SCROLLBLIT_END, "pp_scrollblit overruns its slot"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
