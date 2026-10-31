"""Reference implementation of the SMACX UI scaling laws.

This module is the SINGLE SOURCE OF TRUTH for the arithmetic. The Frida
prototypes (`hook_*.js`) and the baked cave thunks are *ports* of what is
here; when they disagree, this file is right and the port has a bug.

Nothing in here touches the game, the exe, or any file — it is pure integer
math so it can be swept exhaustively in `work/tests/test_scaling_laws.py`
before a single frame is drawn. That sweep has already caught two real bugs
that in-game eyeballing missed (a stroke width tipping 2->3 at 4K and going
span-dependent; a corner bevel getting half the stroke's weight at g=25).

--------------------------------------------------------------------------
THE LAWS
--------------------------------------------------------------------------
1. PROPORTIONATE       every scaled value = vanilla * (g/16). Measure the
                       vanilla value first; never eyeball a magnitude.
2. REMAINDER           n*floor(s*v) != floor(n*s*v). Position cell i at
   DISTRIBUTION        cum(i) = half_down(i*total, n) and take differences.
                       The per-cell floor otherwise accumulates to the far
                       end of the run.
3. CHROME CELLS        cells that are chrome (stroke, bevel) take the
   PINNED TO K         canonical stroke width K; the remainder spreads over
                       the inert cells (interior fill / padding) only.
4. K FROM THE LEVER    K = half_down(g, 16), never an element's own
                       src->dst ratio. Ratios differ from g/16 at exact-half
                       boundaries and are span-dependent, which makes two
                       frames on one screen disagree.
5. CHROME FOLLOWS      derive a chrome rect from the quantities the CONTENT
   CONTENT             uses; never independently scale the chrome rect. Then
                       the g=16 identity is ALGEBRAIC (a proof of the native
                       no-op), not something you test and hope.

Every public function here satisfies: at g == 16 it is the identity.
That is asserted by the test sweep and must never be weakened.
"""
from __future__ import annotations

import functools
import math
from typing import List, Optional, Tuple

# The scale lever `g_popup_scale_num` @0x668740: clamp(floor(16*min(W/1024, H/768)), 16, 40) -- popup_g(W, H).
# g == 16 is native (1024x768, and every 16:9 screen up to 1366 wide). g=18 @1600x900, 20 @1280x1024,
# 22 @1920x1080, 25 @1600x1200, 40 @3840x2160.
G_MIN, G_MAX = 16, 40
NATIVE_G = 16


def half_down(a: int, b: int) -> int:
    """round(a/b) with exact halves going DOWN. Integer math, b > 0.

    Half-DOWN (not half-up) because the user-approved 4K look has a 2px
    stroke: g/16 = 2.5 exactly, and half-up would render 3px.
    """
    if b <= 0:
        raise ValueError("half_down: b must be positive")
    return (2 * a + b - 1) // (2 * b)


def scale_px(v: int, g: int) -> int:
    """LAW 1 — the proportionate rule itself: `patched = vanilla * (g/16)`.

    `v` MUST be a measured vanilla (pristine-exe) magnitude, never an
    already-patched one, and never an eyeballed "comfortable" size.
    """
    return half_down(v * g, NATIVE_G)


def stroke_width(g: int) -> int:
    """LAW 4 — the canonical stroke width K, derived from the lever alone.

    Every frame on a screen shares this K, so strokes cannot disagree between
    elements. Do NOT recompute this from a particular frame's dst/src ratio.
    """
    return half_down(g, NATIVE_G)


def option_row_gap(vanilla_pitch: int, drawn_row_h: int, g: int) -> int:
    """LAWS 1+5 — the inter-row gap of a scaled option list (the QUIT type-16
    row gap; engine sites: calc 0x60d731, draw 0x60d8f3).

    The engine lays rows out on a UNIFORM stride `pitch = drawn_row_h + gap`
    and reserves `content_h = pitch * count`. The scaled quantity that must obey
    LAW 1 is therefore the PITCH, not the gap: the pitch is what positions row i.

    So pin the pitch to `scale_px(vanilla_pitch, g)` and let the gap absorb the
    rounding (LAW 5, chrome follows content — the gap is chrome between rows).

    Do NOT instead scale the gap directly as `scale_px(vanilla_gap, g)`. It is
    the obvious move and it is wrong: `drawn_row_h` and the gap each round
    independently, so their sum leaves the faithful pitch. Measured against the
    real engine (pristine pitch 22 = text_height 19 + gap 3, drawn bar 20):

        scale_px(20,g) + scale_px(2,g) != scale_px(22,g)   at g = 18, 26, 34

    i.e. rows land 1px off at three resolutions — invisible at 4K, wrong at
    1152x864. Same disease as [[feedback-remainder-distribution]].

    At g=16 this is the identity by construction: the calc measures the row with
    Buffer_text_height (19), so gap = 22 - 19 = 3, the vanilla field value. That
    is a PROOF of the native no-op, not a coincidence to be tested and hoped for.

    `drawn_row_h` is the row height the DRAW loop actually uses (post
    thunk_quit_rowpitch that is Buffer_text_line_height). Clamped at 0: a font
    whose line height exceeds the scaled pitch must not produce a negative gap.
    """
    return max(0, scale_px(vanilla_pitch, g) - drawn_row_h)


def cum(i: int, total: int, n: int) -> int:
    """LAW 2 — cumulative position of cell boundary `i` in a run of `n` cells
    spanning `total` pixels. Exact at both ends: cum(0)=0, cum(n)=total."""
    return half_down(i * total, n)


def distribute(total: int, n: int) -> List[int]:
    """LAW 2 — split `total` pixels over `n` cells, spreading the remainder.

    sum(distribute(t, n)) == t exactly; no cell differs from t/n by more
    than 1; the sequence is monotone in the sense that partial sums track
    the ideal line. This is the primitive for ANY repeated stride at scale:
    list rows, button bars, tab strips, tick marks, 9-slice band cells.

    Contrast the bug it replaces: `[total // n] * n` discards n * frac(t/n)
    pixels, all of which pile up at the far end of the run.
    """
    if n <= 0:
        raise ValueError("distribute: n must be positive")
    return [cum(i + 1, total, n) - cum(i, total, n) for i in range(n)]


def row_positions(top: int, native_pitch: int, count: int, scale_num: int,
                  scale_den: int = NATIVE_G) -> List[int]:
    """LAW 2 applied to a repeated stride (the faction-list row bug).

    The engine does `top + i * floor(scale*pitch)`, so it loses
    `count * frac(scale*pitch)` px by the last row (4.8px for the 7 faction
    rows at 1600x1200). This lands row i at its faithful rounded position
    instead, and the run ends exactly at `top + round(count*scale*pitch)`.
    """
    total = half_down(count * native_pitch * scale_num, scale_den)
    return [top + cum(i, total, count) for i in range(count)]


def band_widths(n: int, band_px: int, k: int) -> List[int]:
    """LAWS 2+3 — per-cell widths of a scaled 9-slice corner band.

    `n`       native band depth (the corner sprite's canvas dim, per axis)
    `band_px` the band's total scaled depth, B
    `k`       the canonical stroke width from `stroke_width(g)`

    Native cell 0 is the frame's stroke and cell 1 is its 45-degree bevel
    diagonal: both are CHROME and must render at exactly k. Cells 2..n-1 are
    interior fill (transparent or flat) and absorb the remainder.

    Pinning only cell 0 leaves the bevel at half the stroke's weight at
    g=25 ("corners too small") and double at g=22 ("too large") — the same
    complaint with opposite signs.

    Falls back to a plain distribution when the band is too shallow to hold
    two chrome cells (degenerate frames, and g=16 where k=1 anyway).
    """
    if n <= 0 or band_px <= 0:
        raise ValueError("band_widths: n and band_px must be positive")
    if n <= 2 or band_px < 2 * k:
        return distribute(band_px, n)
    rem = band_px - 2 * k
    return [k, k] + distribute(rem, n - 2)


def axis_map(src_n: int, dst_n: int, n: int, g: int) -> Optional[List[int]]:
    """LAWS 2+3+4 — dest index -> src index for one axis of a 9-slice enlarge.

    Replaces the uniform nearest-neighbour enlarge of an ALREADY-RENDERED
    frame, which cannot serve both the band (must scale faithfully) and the
    1px stroke (must land on exactly K) when the span is not a clean
    multiple: NN dumps the whole remainder onto whichever opposite edge the
    phase happens to hit, giving the 2-vs-3px stroke wobble.

    Near band and far band carry the same widths, each anchored to its OWN
    outer edge, so opposite strokes quantize identically. The middle keeps
    the ENGINE's own NN phase `floor(j*src_n/dst_n)`, clamped inside the
    bands — resampling it with a different phase re-picks which source rows
    duplicate, which is banding (see feedback-dither-no-resample-on-upscale).

    Returns None when the geometry cannot support two bands AND a middle
    (`src_n >= 2n + 1`); callers must fall back to the engine's own renderer
    rather than draw something wrong. At `src_n == 2n` the clamp bounds cross
    (`lo = n > hi = src_n-1-n`) and there is no honest middle sample — a
    JS/Python differential sweep found the two ports silently disagreeing by
    one pixel there. Reject the geometry instead of picking a winner.

    B (the band's scaled depth) derives from the frame's own dst/src ratio so
    the band meets the middle phase seamlessly. K derives from the lever.
    """
    if n <= 0 or src_n < 2 * n + 1:
        return None
    b = cum(n, dst_n, src_n)
    if b <= 0 or dst_n < 2 * b:
        return None

    widths = band_widths(n, b, stroke_width(g))
    fwd: List[int] = []
    for y, w in enumerate(widths):
        fwd.extend([y] * w)
    del fwd[b:]                       # defensive; sum(widths) == b already

    lo, hi = n, src_n - 1 - n         # lo <= hi, guaranteed by the guard above
    out: List[int] = []
    for j in range(dst_n):
        if j < b:
            out.append(fwd[j])                       # near band
        elif j >= dst_n - b:
            out.append((src_n - 1) - fwd[dst_n - 1 - j])   # far band, mirrored
        else:
            s = (j * src_n) // dst_n                 # engine's own NN phase
            out.append(min(max(s, lo), hi))
    return out


def line_axis_map(src_n: int, dst_n: int, lines: List[int], g: int) -> Optional[List[int]]:
    """LAWS 2+3 for a FULL-AXIS enlarge of a pre-rendered art plane (deswin.pcx).

    A backdrop that already carries its 1px frame strokes cannot be enlarged by
    nearest-neighbour: centre-aligned NN gives a 1px native line 2 OR 3 device
    px at x2.5 depending on phase (and a 1558/623 = 2.5008 map drifts the
    verticals to 3px past x=450), 1 OR 2 px at x1.5625 / x1.375 — so the two
    strokes of a 3px-apart separator pair come out 1px + 2px (Design Workshop
    audit 2026-08-28, `work/_dw_dither_audit.md` #12).

    `lines` = the native row (or column) indices that carry an axis-aligned
    stroke, MEASURED from the source plane (a run of non-dither, non-key
    pixels >= 60 long), never hardcoded. Every such index renders at exactly
    K = stroke_width(g) device px; the remaining device span is spread over
    the field indices with `distribute` (LAW 2) so no field cell is off the
    ideal by more than 1 and the total is exact. Returns the dest->src map.

    At g=16: K=1, dst == src, every cell 1 -> the identity (native no-op is
    algebraic). Returns None when the field cannot get >= 1px per native
    cell (only possible at dst < src); callers fall back to plain NN.
    """
    if src_n <= 0 or dst_n < src_n:
        return None
    k = stroke_width(g)
    line_set = set(i for i in lines if 0 <= i < src_n)
    n_l = len(line_set)
    n_f = src_n - n_l
    rem = dst_n - n_l * k
    if n_f == 0:
        if rem != 0:
            return None
        field: List[int] = []
    else:
        if rem < n_f:
            return None
        field = distribute(rem, n_f)
    out: List[int] = []
    fi = 0
    for i in range(src_n):
        if i in line_set:
            w = k
        else:
            w = field[fi]
            fi += 1
        out.extend([i] * w)
    return out


def ring_bottom(ring_top: int, inset: int, rows: int, pitch: int,
                scale: float) -> int:
    """LAW 5 — a chrome rect's far edge, derived from the CONTENT it wraps.

    The faction picker's list ring is built natively as
    `(L-inset, T-inset, R+21, B+inset)` with inset=3, and natively
    `T + rows*pitch == B + inset` — the ring's bottom IS where the rows end,
    flush by construction. Scaling the ring rect independently breaks that
    identity (the rows' pitch floors, the ring's does not), leaving a growing
    void below the last row.

    Rebuilding it from the rows' own numbers makes g=16 reduce to vanilla
    exactly: ring_top=131, inset=3, 7*19=133  ->  267 == nativeB + 3.

    `scale` is whatever the caller applied to the chrome rect (scale_uniform
    for the picker, NOT necessarily g/16 — they differ at 1920x1080).
    """
    rows_top = ring_top + round(scale * inset)
    return rows_top + rows * pitch


def popup_pad(v: int, g: int) -> int:
    """LAW 1, popup-chrome variant: the baked chrome thunks scale a native pad
    `v` with a FLOOR — `(v*g) >> 4` — not `half_down`. This is the shipped
    popup-chrome convention (thunk_popup_fieldR/fieldpads/nestpads/titleinsets,
    thunk_inner_margin all use `sar 4`); it differs from `scale_px` when v*g/16
    lands past an exact half (e.g. v=3, g=19: floor 3, half_down 4). Keep the
    two distinct: strokes round half-down, pads floor.
    """
    return (v * g) // NATIVE_G


def frame_grow_delta(g: int) -> int:
    """The TITLE thickener's outward grow. thunk_box_thick renders a frame's
    9-slice small and blits it back GROWN by delta on every side, so the drawn
    stroke of a title frame sits `delta` OUTSIDE its rect. The body thickeners
    (thunk_box_thick_hollow since the 2026-07-09 channel fix, hollow_flat,
    devfill STEP1) draw FLAT — their stroke sits AT the rect edge.

    delta is 0 at g=16 (identity) and 0 for all g < 24, which is why a
    title/body misalignment from ignoring it is invisible at 1920x1080 and
    below and only shows at 1600x1200 (1px) and 4K (3px).
    """
    return max(0, (g - NATIVE_G) >> 3)


def title_grow_delta(g: int) -> int:
    """The POPUP title pair's outward grow: 0 since 2026-09-18.

    Until then the popup title drew through thunk_box_thick and its strokes sat
    frame_grow_delta OUTSIDE the rect on all four sides: 4K Quit measured the
    title strokes at frame+7 on L/T/R where vanilla x g/16 is +10 = popup_pad(4),
    the box 67 rows tall vs 61, and the whole body was aligned to the grown
    stroke (ring -> border gap 5 / 3 px @g40 / g25 vs 7.5 / 4.7).  The pair now
    draws through thunk_box_thick_flat (Delta = 0), so the drawn title IS its
    rect, like every body frame since 2026-07-09.

    Every popup-chain law below that used to carry frame_grow_delta as a
    compensation for that grow calls THIS instead; the asm ports keep their
    `(g-16) sar 3` instruction with the shift count 31 (== 0 for g > 16: same
    length, no relocation).  frame_grow_delta itself stays: thunk_box_thick still
    serves the diplomacy talk title, whose rects pre-inset by +D
    (diplo_speech_rects)."""
    return 0


def body_outer_edge_r(title_right: int, g: int) -> int:
    """LAW 5 — BODY-OUTER (d5a0 union, draw site 0x406238) rect.right, derived
    from the title-outer rect the popup already computed (g_title_right).

    Vanilla has the body-outer frame FLUSH with the title-outer frame (both
    rings end at backdrop-4; pristine quit-modal trace: title [27,4,696,28],
    body [233,32,696,61]). At scale the title draws through thunk_box_thick
    (stroke lands at rect + frame_grow_delta) while the body draws FLAT, so
    flushness of the DRAWN edges requires the body rect to pre-add the delta
    the title's draw will add:

        body_rect.right = title_rect.right + frame_grow_delta(g)

    Deriving from g_title_right (not recomputing pads) also kills the floor-
    composition lag of the engine path (-popup_pad(10)+popup_pad(3)+popup_pad(3)
    != -popup_pad(4) at g=25 and g=40). g=16: delta=0 -> identity, the vanilla
    696==696 relation, algebraically.
    """
    return title_right + title_grow_delta(g)


def body_inner_edge_r(title_right: int, g: int) -> int:
    """LAW 5 — BODY-INNER (d528, draw site 0x406154) rect.right: one channel
    popup_pad(3) inside the body-outer, mirroring the title pair whose drawn
    channel is also popup_pad(3) (thunk_inner_margin nests the d618 by ps3 and
    both title frames grow by the same delta). g=16: title_right - 3, the
    vanilla 693 == 696 - 3 relation.
    """
    return body_outer_edge_r(title_right, g) - popup_pad(3, g)


def body_outer_edge_l(title_left: int, g: int) -> int:
    """Mirror of body_outer_edge_r for the left edge. Only applied when the
    popup has NO art sprite ([popup+0x2144] == 0): an art popup's body frame
    starts right of the image, so its left edge keeps the engine's art-aware
    value and only the right edge is title-derived.
    """
    return title_left - title_grow_delta(g)


def body_inner_edge_l(title_left: int, g: int) -> int:
    """Mirror of body_inner_edge_r (no-art popups only, as above)."""
    return body_outer_edge_l(title_left, g) + popup_pad(3, g)


# --------------------------------------------------------------------------
# TutWin directional tooltips (crash-land "LANDFALL" et al.)
# --------------------------------------------------------------------------
# TutWin draws NO title band, so the pf-align chain's stash (g_title_left/
# right, normally refreshed by thunk_pf_title_stash at every titled popup's
# title draw) is STALE for it, and thunk_scale_header's titled-only gate
# ([popup+0xa48] != 0) never scales its content top. Measured vanilla
# (1024x768 run, 2026-07-10): window 490x211, ring d5a0 {13,21,477,170},
# field d528 {16,24,474,167}, content top [popup+0x30e8] = 27.

TUTWIN_RING_INSET = 13      # vanilla d5a0 inset from the window edge, both sides
TUTWIN_CONTENT_TOP = 27     # vanilla [popup+0x30e8] (text Y; field T = top-ps3+delta-ish offsets below it)
BTN_BAR_NATIVE_H = 20       # the FlatButton bar art's native row count


def tutwin_stash_left(g: int) -> int:
    """LAW 5 — the SYNTHETIC title stash fed to the pf-align chain for TutWin.

    Chosen so the chain's own laws land the drawn ring at the vanilla inset:
    `body_outer_edge_l(tutwin_stash_left(g), g) == scale_px(13, g)` for every
    g (asserted algebraically by the sweep). The field then sits popup_pad(3)
    inside the ring and the body text popup_pad(3) inside the field via the
    UNCHANGED baked chain (frame_align / union_align / textfollow) — this
    function feeds the chain; it never replaces it. g=16: 13 + 0 = 13, and
    the chain reproduces the vanilla {13,16} pair exactly.
    """
    return scale_px(TUTWIN_RING_INSET, g) + title_grow_delta(g)


def tutwin_stash_right(window_w: int, g: int) -> int:
    """Mirror of tutwin_stash_left for the right edge (window_w = TutWin's scaled
    window width == its canvas width; uimod debugdump 2026-09-19: 1599 @g40, 998 @g25).
    NOTE: since pf-align v8 (2026-08-01) TutWin -- ornate type 2, untitled, with a body
    box -- takes the ENGINE arithmetic, so this stash no longer places its ring; the
    ring follows the text field (law ornate_field_right_sub). g=16: W - 13."""
    return window_w - scale_px(TUTWIN_RING_INSET, g) - title_grow_delta(g)


def tutwin_content_top(g: int) -> int:
    """LAW 1 — TutWin's content top [popup+0x30e8], vanilla 27. Everything
    above the body follows it at DRAW time (text Y == 30e8; field T and ring
    T are fixed pf-chain offsets below it), and boxH was computed WITH it, so
    the baked fixup adds (tutwin_content_top(g) - 27) to boxH as well — the
    box grows to accommodate the drop (LAW 5). g=16: 27 (identity).
    TutWin is the singleton instance of ornate_untitled_content_top.
    """
    return ornate_untitled_content_top(TUTWIN_CONTENT_TOP, popup_type=2, titled=False,
                                       anchored=False, is_tutwin=True,
                                       faction_quote=False, g=g)


ORNATE_POPUP_TYPES = (2, 6)  # Popup_calc's own ornate test: `cmp edi,6 / je / cmp edi,2` @0x404dd9
ORNATE_UNTITLED_HEADER = 0x12 + 9   # 0x404d4c untitled 0x12, + ecx=9 ornate @0x404e17 = 27


def ornate_untitled_content_top(native_30e8: int, *, popup_type: int, titled: bool,
                                anchored: bool, is_tutwin: bool, faction_quote: bool,
                                g: int) -> int:
    """LAW — thunk_tutwin_ctop v2: the content top [popup+0x30e8] of an
    UNTITLED ORNATE popup.  Vanilla Popup_calculate_dimensions sets the
    header reserve [+0x21b8] = 0x12 (untitled) and adds 9 for the ornate
    family (engine type edi == 6 or 2, after PopupDialogState's 0/5 -> 6
    conversion inside sub-interfaces), so EVERY untitled ornate popup has
    content top 27 — the TutWin singleton (tutwin_content_top) and the heap
    popups alike (tutor.txt #COMMERCE over the diplomacy talk screen, type 6).
    thunk_scale_header scales titled + untitled flat/slide tops only, so this
    one stayed native while L/R/B were scaled: ring drawn over the window band.
    Scaled: scale_px(27, g); boxH grows by the same delta (LAW 5).
    Excluded (returned unchanged): titled (popup_header_reserve owns it),
    anchored ([+0xa14] != 0: BasePop_calc's other branch), the faction-quote
    singleton (thunk_d528_inset owns its top), non-ornate types, and any value
    that is not the native 27 (the bake's double-scale guard).  TutWin is
    admitted by identity regardless of the type/anchor fields.
    Identity at g <= 16."""
    if g <= NATIVE_G or native_30e8 != ORNATE_UNTITLED_HEADER:
        return native_30e8
    if not is_tutwin and (popup_type not in ORNATE_POPUP_TYPES or titled or anchored
                          or faction_quote):
        return native_30e8
    return scale_px(ORNATE_UNTITLED_HEADER, g)


TUTWIN_POP_POINTER_INSET = 5   # TutWin_tour6 0x4BAB5B / 0x4BAD49: `add edx,5`


def tutwin_pop_pointer_x(pop_left: int, mainwin_x: int, g: int) -> int:
    """The drone tour's (DRONETOUR1 / DRONETOUR5) pointer-line TARGET x.

    Vanilla TutWin_tour6 converts the citizens-row rect CENTRE to screen
    space through GraphicWin_local_to_screen(MainWin) but then passes
    `rect.left + 5` -- the raw MainWin-LOCAL left edge -- as the target x
    (only y takes the converted value). That is a VANILLA bug masked at
    1024x768, where the console strip starts at screen x = 0: at any wider
    resolution the strip is bottom-CENTRED, so the target lands
    MainWin.x pixels left of the row (2.5x scaled: 640 px at 4K, the line
    ended at the console's left rail in shot 20260917-225639).

    `pop_left` is the rect's LEFT as stored at runtime -- DEVICE space
    (basewin_strip_seed_rects writes the scaled rects) -- so it is added
    as-is; only the native +5 inset scales (floor idiom of the strip seed
    law); and the MainWin screen origin is added the way local_to_screen
    would. g<=16: vanilla's own `left + 5`, no origin term (byte-for-byte
    the displaced instruction; the strip origin is 0 there anyway)."""
    if g <= NATIVE_G:
        return pop_left + TUTWIN_POP_POINTER_INSET
    return mainwin_x + pop_left + popup_scale_floor(TUTWIN_POP_POINTER_INSET, g)


# ---------------------------------------------------------------------------
# Popup screen-edge anchoring (BasePop_exec_3 placement 0x60296F..0x602B43).
# ---------------------------------------------------------------------------
POPUP_LOC_CENTRE = 0x1000        # [popup+0x30F8]/[+0x30FC] sentinel: centre on that axis
POPUP_LOC_KEEP = 0x2000          # BasePop_set_loc / script #x #y: leave the request alone
POPUP_EDGE_ANCHOR_MIN = -0x1000  # exclusive lower bound of an edge-anchor request
FACTION_PICKER_ORIGIN = 5        # FactionPickWin_build: GraphicWin_init(5, 5, 790, 300)
FACTION_QUOTE_X = 5              # thumb_routine: BasePop_set_loc(5, 0x136) -- the picker's left


def popup_edge_anchor_offset(req: int, g: int) -> int:
    """The x/y placement REQUEST a popup is laid out with, device space.

    BasePop_exec_3 reads the request ([popup+0x30F8] x / [+0x30FC] y) and
    places the window:  0x1000 = centred; a NEGATIVE request anchors the far
    edge, `pos = span - box + req` (right / bottom; a child popup measures
    against its parent window the same way); anything else is a literal
    position. The negatives are NATIVE edge gaps -- Script.txt `#x -5 #y -5`
    (every pre-game setup popup: CUSTOMNAMES "Customize Your Faction",
    RULES, DIFFICULTY, FACTION, ...; Thinker's modmenu.txt too), `-20` (the
    BATTLE* combat prompts), Console_go_to's set_loc(-10, -10), the second
    NetMsg's x = -5 -- and vanilla adds them raw, so at 4K the Customize
    popup sat 5 device px off the corner (Pause dump [2130,1561,3835,2155]).

    Law: a request in (-0x1000, 0) is a gap of m = -req native px and scales
    as -floor(m*g/16) -- the magnitude floors, so the far-edge gap equals the
    near-edge popup_scale_floor gap (the faction picker's 5 -> 12 at g=40;
    8 at g=25/22). Everything else passes through: the centre sentinel,
    positive literals (TutWin passes DEVICE screen positions through set_loc,
    so a positive request is NOT reliably native -- the native ones scale at
    their sources, popup_positive_loc), and <= -0x1000. g<=16:
    identity (vanilla)."""
    if g <= NATIVE_G or not (POPUP_EDGE_ANCHOR_MIN < req < 0):
        return req
    return -popup_scale_floor(-req, g)


def popup_edge_anchor_shift(req: int, g: int) -> int:
    """What thunk_popup_edge_anchor adds to the engine's placed coordinate.

    Every negative branch of the engine placement is `<terms> + req`, so the
    scaled placement is the vanilla one plus (law - req) -- one correction
    at the branches' join (0x602B49) covers the screen-anchored, the
    flag-2 and the child-popup arms alike. <= 0: the popup moves AWAY from
    the edge it hugs."""
    return popup_edge_anchor_offset(req, g) - req


def popup_place_axis(req: int, span: int, box: int, g: int) -> int:
    """The placed top-left on one axis for a screen-anchored popup (the
    engine's main arm: span = ScreenWidth/Height, box = window extent)."""
    if req == POPUP_LOC_CENTRE:
        return (span - box) >> 1
    if req < 0:
        return span - box + popup_edge_anchor_offset(req, g)
    return req


def faction_picker_origin(g: int) -> int:
    """CHOOSE YOUR FACTIONS window top-left (x == y), device space: the native
    (5, 5) gap from the screen's top-left corner scales like the window it
    places (popup_scale_floor, the picker's own w/h idiom) -- 12 at g=40, the
    same gap the edge-anchored setup popups keep from the bottom-right."""
    return popup_scale_floor(FACTION_PICKER_ORIGIN, g)


def faction_quote_x(g: int) -> int:
    """The faction quote box's x (thumb_routine set_loc x): the picker's own
    left edge, so the two stay flush at every g (y is thunk_factionwin_quoteloc's
    popup_scale(0x136))."""
    return popup_scale_floor(FACTION_QUOTE_X, g)


def popup_positive_loc(req: int, g: int) -> int:
    """A POSITIVE native placement literal (top-left gap from the near
    screen / parent edge), device space.

    Two sources hand BasePop a positive x/y that is NATIVE by construction:
    the script parse in BasePop_start (`#x` / `#y` -> atoi -> [popup+0x30F8]
    @0x601E91 / [+0x30FC] @0x601EDF; census Script.txt == xscript.txt:
    FACTIONX 5,5, NEWBASE / FIRSTBASE 10,40, CHATASK 5,40, BATTLEPAUSE 20,20)
    and NetMsg_pop's BasePop_set_loc(+0x537C, +0x5380) @0x47A94F (the ctor
    constants: NetMsg_g (0x1000, 8), 0x7FFF80 (-5, 40)). Vanilla uses them
    raw, so at 4K FACTIONX's list sat 5 device px off the corner while its
    quote box (faction_quote_x) sat 12.  Only the script parse applies this
    law (t_scrloc_x / t_scrloc_y).  NetMsg_g's y = 8 stays unscaled on
    purpose (user decision 2026-10-22, fix 18 backs out fix 6's t_netmsg_loc):
    no visible case has been verified -- "Bases cannot be built adjacent"
    takes the ticker path 0x47ABBA and never reaches 0x47A94F; only the rare
    a4 = 1/2 notices (UPKEEP, VOTING, multiplayer AWAIT) do.

    Law: 0 < req < 0x1000 is a gap and scales popup_scale_floor(req, g)
    (12 at g=40 for 5; the same idiom as the faction picker's origin).
    Everything else passes through: the centre sentinel 0x1000 and anything
    above, 0, and every negative (the far-edge requests -- the join thunk
    owns those, popup_edge_anchor_offset; scaling them here too would
    double-scale). Not applied at BasePop_set_loc itself: TutWin passes
    device positions and thumb_routine pre-scaled ones through it. g<=16:
    identity (vanilla)."""
    if g <= NATIVE_G or not (0 < req < POPUP_LOC_CENTRE):
        return req
    return popup_scale_floor(req, g)


TUTWIN_EDGE_GAP_X = 5   # TutWin_tut_win 0x4BE34E / 0x4BE35A / 0x4BE37D / 0x4BE380: the box's side gap
TUTWIN_EDGE_GAP_Y = 8   # TutWin_tut_win 0x4BE319 `sub eax,8`: the bottom-placed box's gap


def tutwin_window_h(box_h: int, btn_h: int, g: int) -> int:
    """Height of the window BasePop_exec_3 creates for the TutWin box.

    TutWin_tut_win places from the box [+0x30C0] after a MEASURE-ONLY pass
    (BasePop_exec_3(1, 0) returns at 0x6027AF, before the window's
    GraphicWin_init at 0x60287C), so no window exists yet and the canvas
    [+0x4C8] still holds the PREVIOUS show's height (or 0 on the first).
    The second pass creates the window box_h + D tall, D the button-row
    growth thunk_grow_box adds at 0x602861 (popup_button_row_growth, read
    from the same [+0x30D0] the measure pass leaves -- the TutWin is its own
    window, [+0xA3C] == self, and [+0xA14] == 0, so the growth always fires).
    g<=16: D = 0, the box itself."""
    return box_h + popup_button_row_growth(btn_h, g)


def tutwin_place(sw: int, sh: int, box_w: int, box_h: int, btn_h: int, ty: int,
                 left: bool, bottom: bool, g: int) -> Tuple[int, int, int, int]:
    """TutWin box top-left + pointer-line attach point, device space:
    returns (x, y, attach_x, attach_y) -- the locals set_loc receives
    ([ebp+0x10] / [ebp+0x14]) and [+0x538C] / [+0x5390].

    Vanilla (0x4BE2A7..0x4BE38B) picks a side and an end from the target:
    `left` -> x = 5, attach_x = 5 + box_w/2; else x = SW - box_w - 5,
    attach_x = SW - box_w/2 - 5. `bottom` -> y = SH - box_h - 8, attach on
    the box's top edge; else y = target_y/8 (C truncation, proportional --
    unchanged), attach on the box's bottom edge y + box_h.

    Law: the 5 / 8 are native gaps and scale popup_scale_floor (12 / 20 at
    g=40), and every height term is the WINDOW height (tutwin_window_h),
    not the box: the growth made the window D taller than the box vanilla
    places from, which pushed the bottom rail off-screen at 4K (D=30 > 8).
    The branches are vanilla's and do not depend on g. g<=16: vanilla
    byte for byte."""
    if g <= NATIVE_G:
        gx, gy = TUTWIN_EDGE_GAP_X, TUTWIN_EDGE_GAP_Y
    else:
        gx = popup_scale_floor(TUTWIN_EDGE_GAP_X, g)
        gy = popup_scale_floor(TUTWIN_EDGE_GAP_Y, g)
    win_h = tutwin_window_h(box_h, btn_h, g)
    half = box_w // 2 if box_w >= 0 else -((-box_w) // 2)
    if left:
        x, ax = gx, gx + half
    else:
        x, ax = sw - box_w - gx, sw - half - gx
    if bottom:
        y = sh - win_h - gy
        ay = y
    else:
        y = ty // 8 if ty >= 0 else -((-ty) // 8)
        ay = y + win_h
    return x, y, ax, ay


MENU_FONT_NATIVE = 16   # g_popup_menu_font_src: find_font(16,0)
MENU_FONT_MAX = 40      # the pool's largest face


def menu_font_request(g: int) -> Optional[Tuple[int, int]]:
    """The (size, variant) asked of find_font for g_menu_font -- the ONE font
    the universal Menu control (every HUD dropdown submenu, right-click menu)
    sizes AND draws from. None = keep the engine's own native pointer.

    g_menu_font has TWO engine writers besides config_popups: the MENU
    widget's layout (thunk_menu_layout) and popups_normal 0x5886C1, which
    re-installs the native [g_popup_menu_font_src] at the END OF EVERY
    TUTORIAL POPUP (TutWin_tut_win -> popups_tutorial ... popups_normal) and
    from 0x48C349 / 0x58428B. Scaling only the layout writer left every
    submenu native-tiny after any tour/hint until the next layout
    (shot 20260918-000615). BOTH writers must ask for the same font:

        size = 16 * g/16 = g, capped at the pool max 40; variant 1
        g <= 16 -> None (the displaced native store, byte-identical)"""
    if g <= NATIVE_G:
        return None
    return (min(MENU_FONT_NATIVE * g // NATIVE_G, MENU_FONT_MAX), 1)


def tutwin_base_pointer_pt(native_center: int, g: int) -> int:
    """A tutorial pointer target that lives INSIDE the base screen (every
    TutWin site that converts through GraphicWin_local_to_screen(BaseWin_g):
    TutWin_do_base, TutWin_base_rect, the 3 DRONETOUR6/TOUR1PSYCHBUTTON
    steps of TutWin_tour6 and the 14 TOUR1* steps of TutWin_tour1).

    Those rects (BaseWin+0x40D0C psych row, +0x40DDC, +0x40E3C, the tab
    seeds ...) are NATIVE BaseWin-local -- the base screen's interior scales
    at the primitive boundary (basewin_pt), so the rect fields never change.
    Vanilla passes the native centre straight to local_to_screen; at 4K that
    is the point 2.5x too close to the window's top-left (the psych step's
    line ended in the map view, shot 20260917-234627). The target is the
    same consumer-boundary law the drawing itself uses, applied to the
    centre BEFORE the origin add:

        x_dev = basewin_pt(cx_native, g) = floor(cx * g/16)

    (the strip-side rects converted through MainWin are DEVICE space
    already and are not touched -- the thunk gates on ecx == BaseWin_g).
    g<=16 identity."""
    return basewin_pt(native_center, g)


def btn_native_dim(scaled: int, g: int) -> int:
    """The INVERSE of the window-dim FLOOR scale for the popup-button 2D-zoom
    shrink (v2 2026-07-21e: CEIL, was round).

    thunk_btn_shrink recovers the native render size from the button's scaled
    canvas dim. Every window family that reaches the shrink scales its dims
    by the FLOOR idiom — popup_scale_floor for the popup/pref/TutWin levers,
    thunk_basewin_gwinit's `imul; sar 4` for the BaseWin children — and the
    exact inverse of `dev = fl(n*g/16)` is

        ceil(dev*16/g)  =  (dev*16 + g - 1) // g

    (dev*16/g lands in (n-1, n] because the floor loses at most 15/g < 1).

    v1 shipped `(scaled*16 + g/2) / g` (round) and was applied to H ONLY
    ("W untouched — round==floor for all seen"). Round agrees with ceil on
    every previously-verified dim (r = n*g mod 16 <= g/2 for all of them —
    the 20/22-native art heights at g=22/25/40), but UNDER-recovers whenever
    r/g > 1/2: fl(20*23/16)=28 -> 19 at g=23, fl(238*25/16)=371 -> 237 at
    g=25 — a floor-forward can shed up to 15/16 of a pixel, more than the
    half-pixel round can give back. Ceil is the exact inverse at every g,
    the all-resolutions rule.

    v2's visible target was the BaseWin GOVERNOR chevrons (fixed-art 20x20
    state-sprite buttons, 2026-07-21e 1600x1200 report): with NO W law at
    all, shrink's raw floor descaled their W 31 -> 19, the KSB declared a
    19-wide source and the art's 20th column — the bright right border —
    was never sampled ("chevron overlapped by the button on its right").
    9-slice buttons self-heal (they re-render at the believed width);
    fixed-art sprites cannot, so the law now covers BOTH axes.

    The original shipped floor was strictly worse on H too (clipped the
    20-row bar art to 19 at g=25/22 — the 2026-07-10 hover-highlight
    defect).

    Matches the baked asm `(scaled*16 + g - 1) / g` (thunk_tutbtn_post v3,
    both axes; thunk_btn_shrink's own floor is overwritten there before any
    consumer reads it).
    """
    return (scaled * NATIVE_G + g - 1) // g


def btn_bar_tile_height(orig_h_abs: int, native_h: int, art_h: int) -> int:
    """thunk_btn_devfill's device-res dither re-tile HEIGHT (and the y-anchor
    of the bottom corner-notch punches).

    The FlatButton frame art is 20 rows for every piece and every state,
    drawn 1:1 and TOP-anchored (no bottom pieces, no fill in the default
    set), so vanilla paints at most art_h native rows; a window taller than
    the art keeps a transparent (key-9) gap below the bar — vanilla-1024's
    picker text buttons are 22 native tall and genuinely show a 2px gap.
    The 2D zoom preserves that gap (GraphicWin_fill pre-keys the canvas),
    but devfill's FULL-BLEED re-tile (correct on the 20-native popup action
    buttons it was gridded against) over-tiled the gap on 22-native buttons:
    a 5-px phantom bar at 4K that made the base state taller than the
    faithful hover state (shot ...174559).

    The cap is the zoom's OWN mapping of the art bottom, NOT a parallel
    scale_px rounding, so the dither boundary lands exactly on the zoomed
    art's last row at every g.  The zoom is GDI StretchBlt (COLORONCOLOR,
    via thunk_keyed_stretch_blit), MEASURED as centre-sampled NN
    (nn_center_index: device row j reads native row ((2j+1)*native)//(2*orig));
    real GDI differs from that model only on an n -> n+1 stretch whose other
    axis is also nearly 1:1 (audit-w1B, host GDI), which no 22-native button
    zoom hits (host-GDI sweep g 16..40).  So the art covers the device rows j with (2j+1)*native < 2*art*orig:
    (2*art*orig + native - 1) // (2*native) of them (v2, 2026-10-24 wave-1
    F33).  v1's floor(art*orig/native) is one row short whenever that
    quotient's fraction is >= 1/2 (22-native at g 25: 30 vs the zoomed art's
    31 rows): the NN'd art bottom row stayed under the re-tile and the
    bottom corner notch was s x (s+1).  Full-bleed is the identity whenever
    art_h >= native_h, which is every previously-verified button class
    (popup/prefwin/TutWin 20-native).
    """
    if native_h <= 0:
        return orig_h_abs
    return min(orig_h_abs, (2 * art_h * orig_h_abs + native_h - 1) // (2 * native_h))


def btn_corner_notch(g: int) -> int:
    """LAW (2026-10-24 wave-1 F33) -- the side of the square corner notch of a 2D-zoomed FlatButton BAR face, in
    EVERY draw state (idle, hover, pressed / lit: FlatButton_content_draw's state law 0..2): s = ceil(g/16).

    Vanilla's bar art carries a 1-px key notch at each corner in every state (the default 9-slice set's TL / TR caps
    and the box-sprite sets' corner pieces, measured 1 x 1 at 1024).  The square-notch convention (the faction
    buttons, project_smac_faction_button_corners: an s x s key square, pure H/V edges) scales it to s x s.  The NN
    zoom alone leaves round(dev/native) <= s px per axis -- at 4K 2 on the top / left and 3 on the bottom / right
    (2x2 / 3x2 / 2x3 / 3x3), at 1920x1080 1 x 1 -- so every state is re-punched to s x s at the true corners (the
    bottom pair on the zoomed art bottom btn_bar_tile_height, the full canvas for box-sprite faces):
      * 9-slice bars, state 0: thunk_btn_devfill re-tiles the dither then punches all four (as before);
      * 9-slice bars, states 1 / 2 (fillcap v3 captures every state): t_btn_litcorner punches each corner whose
        zoomed corner pixel is key (the art's notch; a notch-less corner is left alone);
      * box-sprite faces (HUD TOOLBAR, Datalinks buttons): thunk_btn_ringfix punches K x K (K = btn_ring_k = s) iff
        the TL corner art is keyed, in every state (v2: no longer only when a hover ring edge drew).
    State-sprite faces (pixel-art buttons) are not bars and keep the NN image of their art.  g <= 16: no zoom, the
    vanilla 1-px notch."""
    return (g + 15) >> 4 if g > NATIVE_G else 1


# ==== 1-px art EDGE STROKES on bar faces (2026-10-25 wave-2 F39 / F40) ================================================
# Census (vanilla, measured at g = 16 on the real image): the 1-px light outline (0xE0) of the HOVER / LIT state is
# the only edge stroke a non-BaseWin bar face carries --
#   * the default 9-slice FlatButton set (TL 0x77A964 / T 0x77A990 / TR 0x77A9BC): state 1 only, all four sides;
#     states 0 / 2 are dither to the edge (no stroke);
#   * the faction-picker name rows (FactionPickWin vtbl+0x2C 0x48A840, Buffer_box_sprite with the BoxSpriteParams
#     sets 0x78D960 / 0x78D988 / 0x78D9B0): state 1 only (strips +0x10..+0x1C, row / col 0 = E0);
#   * the faction-picker drop arrows (16 x 16 state sprites, thunk_faction_dropimg): state 1 only (E0 ring, E0 glyph);
#   * the two BaseWin 9-slice sets (0x77A754.. / 0x77A5C8.., BaseWin_init 0x41FFE5..0x4206C5) stroke every state, but
#     the BaseWin range takes thunk_btn_stripes' early-out (bandstripe v4's user-approved NN + restripe), out of scope.
EDGE_STROKE_KEY = 9


def btn_edge_stroke(g: int) -> int:
    """LAW (2026-10-25 wave-2 F39) -- the device width K of a bar face's 1-px art EDGE STROKE, on all four sides, in
    every state that carries one: K = btn_corner_notch(g) = btn_ring_k(g) = ceil(g/16) (1 at g <= 16).

    Chosen as the notch law was: the stroke and the notch are the same vanilla feature size (1 px each, the notch at
    the stroke's corner), so the only width that keeps vanilla's corner shape -- an s x s key notch wrapped by the
    stroke, the stroke's inner edge flush with the notch's -- is K = s; the box-sprite hover ring (btn_ring_k, user-
    accepted 2026-10-18 with the notches) is already K = ceil(g/16).  The zoom alone cannot give it: the stroke's
    centre-NN image is round(dev/native) px per edge and splits unevenly (the lobby LAUNCH hover face, host GDI:
    1 | 1 at g 16..23, 1 | 2 at g 24, 2 | 2 at g 25..39, 2 | 3 at g 40; user shots 4K 20261025-000608 / 000611).
    K >= every NN run of a 1-px column (test_law_nn_notch_never_exceeds_s), so a K band covers the whole NN image:
    each edge is redrawn as a K-wide band of the stroke's colour, the same width on all four sides at every g.  The
    band is SOLID (vanilla's stroke is one index; thunk_fe_pair_remap would otherwise restripe 0xE0 into E0 / E1,
    the recorded dither-pair collateral) -- so it is drawn after the pair remap."""
    return btn_corner_notch(g)


def edge_stroke_colour(n0: int, n1: int, n2: int, key: int = EDGE_STROKE_KEY) -> Optional[int]:
    """The edge probe: an edge carries a 1-px stroke iff its outermost art pixel n0 is not the key and differs from
    BOTH of the next two pixels inward (n1, n2) -- a period-2 scanline dither has n0 == n2, a solid fill n0 == n1.
    Returns the stroke colour, else None.  Read on the NATIVE art (exact indices: no zoom, no remap)."""
    return n0 if (n0 != key and n0 != n1 and n0 != n2) else None


def btn_edge_probe(rows, art_h: int) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    """t_btn_edgeprobe: the four edge strokes (top, bottom, left, right) of a NATIVE composed 9-slice face (rows =
    the face as the 2D zoom's source sees it, before thunk_btn_2dscale's stretch; art_h = the captured T piece's
    canvas h).  The art is top-anchored: A = min(art_h, H) rows carry it.  Top / bottom at the middle column
    xm = W >> 1 (rows 0, 1, 2 / A-1, A-2, A-3); left / right on the middle art row ym = A >> 1 (cols 0, 1, 2 /
    W-1, W-2, W-3).  The label is drawn after the zoom, so the probe reads bare art.  W < 6 or A < 6: no strokes."""
    h, w = len(rows), len(rows[0])
    a = min(art_h, h)
    if w < 6 or a < 6:
        return None, None, None, None
    xm, ym = w >> 1, a >> 1
    return (edge_stroke_colour(rows[0][xm], rows[1][xm], rows[2][xm]),
            edge_stroke_colour(rows[a - 1][xm], rows[a - 2][xm], rows[a - 3][xm]),
            edge_stroke_colour(rows[ym][0], rows[ym][1], rows[ym][2]),
            edge_stroke_colour(rows[ym][w - 1], rows[ym][w - 2], rows[ym][w - 3]))


def edge_band_rects(w: int, d: int, k: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """The four K bands (x, y, w, h) of a face w wide whose art ends at row d (top, bottom, left, right): the top /
    bottom bands span the full width, the side bands the full art height [0, d).  Corners are left to the notch."""
    return ((0, 0, w, k), (0, d - k, w, k), (0, 0, k, d), (w - k, 0, k, d))


def btn_edge_band(canvas, d: int, g: int, colours, key: int = EDGE_STROKE_KEY):
    """t_btn_edgeband's reference: after thunk_btn_ringfix (stripes = devfill + litcorner + the pair remap) each edge
    with a stroke colour gets a K = btn_edge_stroke(g) band on rows [0, d) (d = btn_bar_tile_height, the zoomed art
    bottom), every NON-KEY pixel written (the s x s corner notches, s == K, stay key).  Skipped unless d >= 2K and
    w >= 2K.  canvas: list of row lists (modified copy returned)."""
    out = [list(r) for r in canvas]
    w = len(out[0]) if out else 0
    k = btn_edge_stroke(g)
    if g <= NATIVE_G or d < 2 * k or w < 2 * k:
        return out
    for col, (x0, y0, bw, bh) in zip(colours, edge_band_rects(w, d, k)):
        if col is None:
            continue
        for y in range(y0, y0 + bh):
            for x in range(x0, x0 + bw):
                if out[y][x] != key:
                    out[y][x] = col
    return out


def nn_mirror_index(j: int, dst: int, src: int) -> int:
    """Mirror-symmetric centre-sampled NN (thunk_faction_dropimg v3): the first half of the dest axis takes
    nn_center_index, the second half its mirror image (src - 1 - nn_center_index(dst - 1 - j)).  Every src index then
    gets a palindromic run count, so a symmetric source (the drop arrow's centred glyph) stays symmetric at every
    ratio -- the plain centre map ties at an exact half (16 -> 24: index 1 one column left of its mirror) and the
    floor map (v2) shifted the glyph a column left (1600x1200: margins 4 | 3, 1920x1080: 3 | 2)."""
    if dst <= 0 or src <= 0:
        return 0
    m = dst - 1 - j
    if j <= m:
        return nn_center_index(j, dst, src)
    return src - 1 - nn_center_index(m, dst, src)


BASEWIN_BTN_LO, BASEWIN_BTN_HI = 0x6B4DE8, 0x6C4670   # BaseWin_g + 0xD7C0: its 22 FlatButtons (stride 0xB4C), end excl.


def btn_zoom_mirrored(btn: int) -> bool:
    """t_sbt_zoom samples a BaseWin FlatButton face mirror-symmetrically (btn_zoom_index)."""
    return BASEWIN_BTN_LO <= btn < BASEWIN_BTN_HI


def btn_zoom_index(j: int, dst: int, src: int, mirror: bool) -> int:
    """LAW (2026-10-25 W7H, F39 class on the base screen) -- t_sbt_zoom's per-axis NN map for an owned FlatButton face:
    a BaseWin face (btn_zoom_mirrored) takes nn_mirror_index, every other owned face nn_center_index.

    Vanilla's BaseWin 9-slice sets carry a 1-px edge stroke in EVERY state (the tab row, GOVERNOR, RESOURCE / SUPPORT
    / PSYCH, RENAME / OK, the facilities button: E7 / 61 outlines, the default set's E0 hover ring) and a 1x1 corner
    notch.  The centre map ties at an exact half, so its image of a 1-px edge was uneven -- 1 | 2 at g 24 and 2 | 3 at
    g 40 left | right AND top | bottom in every state (measured on the real image, W7H), the notches 1x1 | 2x2 and
    2x2 | 3x3; SUPPORT's 193-wide hover ring T 2 / B 3 at 4K.  The mirror map gives every source index a palindromic
    run count, so both strokes of a pair and all four notches are equal at every g; it differs from the centre map
    only on the second half of an axis at a tie, so every other g / face is unchanged.  (The F39 K band is not used
    here: it covers the NN image with K = ceil(g/16), 1 -> 2 px at g 17..23, 2 -> 3 px at g 33..39.)  Monotone with
    index <= j on an enlarge (the in-place pass stays safe)."""
    return nn_mirror_index(j, dst, src) if mirror else nn_center_index(j, dst, src)


FACTION_ROW_BOX_SETS = (0x78D960, 0x78D988, 0x78D9B0)   # the name-row painter's BoxSpriteParams, state 0 / 1 / 2
FACTION_ROW_PAINTER = 0x48A840     # FactionPickWin vtbl+0x2C: (win, item, state, rect*) -> Buffer_box_sprite @0x48A892
BOX_PASS_THROUGH = 7               # a BoxSpriteParams strip texel that leaves the dest pixel (no stroke)
FACTION_ROW_SAVE_MAX = 4           # t_fac_rowbox's save-under holds 4 x (4 x 4) bytes: s <= 4 (g <= 64; g is clamped to 40)


def box_edge_strokes(strips) -> Tuple[Optional[int], ...]:
    """The four edge strokes (top, bottom, left, right) of a BoxSpriteParams set, read as thunk_btn_ringfix reads
    them: top strip row 0 / bottom strip row h-1 at the middle column, left strip column 0 / right strip column w-1
    at the middle row; the pass-through 7 or the key 9 = no stroke.  strips: (top, bottom, left, right) row lists."""
    t, b, l, r = strips
    cols = (t[0][len(t[0]) >> 1], b[-1][len(b[0]) >> 1], l[len(l) >> 1][0], r[len(r) >> 1][-1])
    return tuple(None if c in (BOX_PASS_THROUGH, EDGE_STROKE_KEY) else c for c in cols)


STROKE_MATE = {0xE0: 0xE1, 0xE1: 0xE0, 0xAE: 0xEE, 0xEE: 0xAE}   # the pair members a restripe swaps a stroke with


def faction_row_face(before, painted, rect, g: int, corners_keyed, strokes, ink=None, restripe=lambda c: c):
    """LAW (2026-10-25 wave-2 F40b; v2 after the audit: vanilla's draw order) -- a CHOOSE YOUR FACTIONS name row
    (FACTION_ROW_PAINTER: Buffer_box_sprite of the state's set straight onto the list canvas at the DEVICE rect; the
    strips are 1 px, so a row at g > 16 kept vanilla's 1 x 1 corner notches and, hovered, a 1-px E0 ring at every g
    -- 1600x1200 665 x 25 rows, user shot 20261025-000825).  Every bar face gets s x s notches (btn_corner_notch) and
    K-wide strokes (btn_edge_stroke), in vanilla's order -- the strokes first, the row's text on top:
      1. the box paint (`painted`);
      2. each edge with a stroke (box_edge_strokes of the state's set) -> a K band of its colour inside the rect;
      3. each corner whose corner piece is keyed (the vanilla notch: the box draw leaves that pixel) -> the s x s
         square of the canvas as it was BEFORE the paint (the background the vanilla notch shows: a save-under);
      4. the item's text (`ink`: {(y, x): index}), drawn by ListBox_draw_item over all of it;
      5. the list restripe (t_lb_item_stripes' t_lbi_restripe_ph) over the canvas -- the restored corners with it;
      6. inside each band, the stroke's pair mate (STROKE_MATE) back to the stroke: the restripe splits a solid E0
         band into E0 / E1; every other index -- the text ink -- stays as the text drew it (a text pixel in the
         stroke's own mate colour inside a band would come back as the stroke; the row text does not use E1).
    before / painted: the list canvas (row lists) before the painter and right after its box draw; restripe: canvas
    -> canvas; rect = (L, T, R, B) half-open.  Not applied (the paint, the ink, the restripe) unless g > 16,
    s <= FACTION_ROW_SAVE_MAX, the rect inside the canvas and >= 2s each way."""
    s = btn_corner_notch(g)
    L, T, R, B = rect
    H, W = len(painted), (len(painted[0]) if painted else 0)
    out = [list(r) for r in painted]
    applied = not (g <= NATIVE_G or s > FACTION_ROW_SAVE_MAX or L < 0 or T < 0 or R > W or B > H
                   or R - L < 2 * s or B - T < 2 * s)
    bands = [(col, (L + x0, T + y0, bw, bh)) for col, (x0, y0, bw, bh) in
             zip(strokes, edge_band_rects(R - L, B - T, s)) if col is not None] if applied else []
    if applied:
        for col, (x0, y0, bw, bh) in bands:
            for y in range(y0, y0 + bh):
                out[y][x0:x0 + bw] = [col] * bw
        for keyed, (y0, x0) in zip(corners_keyed, ((T, L), (T, R - s), (B - s, L), (B - s, R - s))):
            if keyed:
                for y in range(y0, y0 + s):
                    out[y][x0:x0 + s] = before[y][x0:x0 + s]
    for (y, x), v in (ink or {}).items():
        out[y][x] = v
    out = [list(r) for r in restripe(out)]
    for col, (x0, y0, bw, bh) in bands:
        m = STROKE_MATE.get(col)
        for y in range(y0, y0 + bh):
            for x in range(x0, x0 + bw):
                if m is not None and out[y][x] == m:
                    out[y][x] = col
    return out


# ==== THIN RINGS of the 0x78D960 BoxSpriteParams family (2026-10-25 wave-7 W7R, user: "Scale the thin rings") ========
# 0x78D960 is not a draw primitive: it is three 9-slice BoxSpriteParams sets, state 0 / 1 / 2 at 0x78D960 + state * 0x28
# (FACTION_ROW_BOX_SETS), loaded by load_interface 0x455610 and drawn by Buffer_box_sprite 0x5E2DD3.  Measured on the
# real art (box_edge_strokes): ONLY state 1 (0x78D988) carries a stroke -- a 1-px E0 ring on all four sides; states 0 / 2
# are pass-through 7 to the edge (no stroke), over their fill (0: AE / EE, 1: AE / EE, 2: E1 / E0).  Every set keys its
# four corner texels (the 1 x 1 notch).  So a ref to the family draws a THIN RING only where state 1 can reach the draw.
# The census: every .text imm32 / disp32 into [0x78D960, 0x78D9D8) of the pristine image, keyed by the VA of its 4 bytes
# (an instruction start is ambiguous to a byte scan), with the instruction in the note.  A FlatButton dressing's
# 0x78D988 / 0x78D9B0 companions (within THIN_RING_COMPANION_SPAN bytes of its 0x78D960) are classified by that entry.
#   menu_box     -- the universal Menu's row / background callbacks (states 0 / 2): no ring; the fill and the 1 x 1
#                   notch / 1-px row inset scale by menu_row_clip / menu_box_rect (below);
#   no_stroke    -- only states 0 / 2 reach the draw: no ring (intentionally the native art);
#   fill_tile    -- a set's +0x20 fill Buffer used as a Buffer_tile source: not a ring;
#   option_row   -- popup option rows (0x405BF6 -> t_rowbox_solid -> t_rowbox_trim -> t_rowbox_ph -> band map): the
#                   ListBox hover (state 1) ring at K = stroke_width(g), then solid (ring_solid);
#   btn_ring     -- a FlatButton face (+0xAC8 / +0xACC / +0xAD0 = sets 0 / 1 / 2) in the 2D zoom: thunk_btn_ringfix's
#                   K = btn_ring_k(g) ring (already scaled; user-accepted 2026-10-18);
#   row_face     -- the faction picker name rows: t_fac_rowbox's K = btn_edge_stroke(g) bands (already scaled);
#   unreachable  -- the DiploWin list item back (DW_ITEM_BACK, the iface vtbl slot +0x48): its native 1-px ring stays,
#                   because no shipped flow draws it -- the slot is dispatched only by MainWin's vtbl+0x2C forwarder
#                   0x45C8F0 for the CURRENT mode, a list calls vtbl+0x2C on its PARENT window, the only lists
#                   parented to MainWin_g are the six HQ report console ListBoxes (report modes), and the DiploWin
#                   builder / painters attach no list (static + Unicorn: test_scaling_thin_rings.py).  Not patched
#                   (W7R v2: unreachable cave code is audit surface only).
THIN_RING_FAMILY_REFS = {
    0x403B4F: ("@0x403B4C lea: g_menu_hilite_draw (universal Menu rows: hot 2 / else 0, site 0x403B55)", "menu_box"),
    0x403B77: ("@0x403B76 push: g_menu_border_draw (universal Menu background, state 0, site 0x403B88)", "menu_box"),
    0x405BEE: ("@0x405BEB lea: Popup_on_dialog_item_back_draw (popup option rows, site 0x405BF6)", "option_row"),
    0x407308: ("@0x407306 mov: FileDlg_draw_row (state-2 fill tile)", "fill_tile"),
    0x4153D4: ("@0x4153D3 mov: BaseWin_draw_queue (state-2 fill tile)", "fill_tile"),
    0x4153F9: ("@0x4153F8 mov: BaseWin_draw_queue (state-0 fill tile)", "fill_tile"),
    0x429C95: ("@0x429C8F mov: DatalinkWin_build (wing FlatButtons, 0 / 1 / 2)", "btn_ring"),
    0x42A18E: ("@0x42A18C mov: DatalinkWin_list_row_bg (state-1 fill tile)", "fill_tile"),
    0x42A1CA: ("@0x42A1C8 mov: DatalinkWin_list_row_bg (state-0 fill tile)", "fill_tile"),
    0x43CFFC: ("@0x43CFF6 mov: DesignWin_build (FlatButton 0 / 2 / 2)", "no_stroke"),
    0x440CAE: ("@0x440CA8 mov: DiploTalkWin_init (DATALINKS FlatButton +0x2158, 0 / 1 / 2)", "btn_ring"),
    0x443EE7: ("@0x443EE4 lea: DiploWinIface_item_back (iface vtbl +0x48, state 1 / 2, site 0x443EEF)", "unreachable"),
    0x444820: ("@0x44481A mov: DiploWin_build (FlatButtons +0x10AC + n * 0xB4C, 0 / 1 / 2)", "btn_ring"),
    0x45AAB6: ("@0x45AAB0 mov: MainWin_build (HUD TOOLBAR FlatButton +0x2498, 0 / 1 / 2)", "btn_ring"),
    0x4845BB: ("@0x4845B5 mov: NetTechWin_exec (FlatButton +0xB2C, 0 / 1 / 2)", "btn_ring"),
    0x48A88A: ("@0x48A887 lea: FactionPickWin_row_painter (name rows, site 0x48A892)", "row_face"),
    0x499800: ("@0x4997FA mov: ReportWin_tech_page (tech FlatButton, 0 / 1 / 2)", "btn_ring"),
    0x499942: ("@0x49993C mov: ReportWin_tech_page (tech FlatButton, 0 / 1 / 2)", "btn_ring"),
    0x499A81: ("@0x499A7B mov: ReportWin_tech_page (tech FlatButton, 0 / 1 / 2)", "btn_ring"),
    0x499BF3: ("@0x499BED mov: ReportWin_tech_page (tech FlatButton, 0 / 1 / 2)", "btn_ring"),
    0x499DCA: ("@0x499DC4 mov: ReportWin_tech_page (tech FlatButton, 0 / 1 / 2)", "btn_ring"),
    0x499F50: ("@0x499F4A mov: ReportWin_tech_page (tech FlatButton, 0 / 1 / 2)", "btn_ring"),
    0x5AD8FC: ("@0x5AD8F6 mov: end-game Replay window 0x5AD720 (FlatButton 0 / 2 / 2)", "no_stroke"),
}
THIN_RING_COMPANION_SPAN = 0x20  # a dressing's 0x78D988 / 0x78D9B0 imm32 lies within this of its 0x78D960 imm32
THIN_RING_SET_STATE1 = 0x78D988   # the only set of the family with a stroke (E0, all four sides)
DW_ITEM_BACK = 0x443E50           # DiploWin iface vtbl 0x66B5E0 +0x48: (win, a2, state, rect*) RET 0x10, ecx unused
DW_ITEM_RING_SITE = 0x443EEF      # its Buffer_box_sprite(&local rect, 0x78D960 + state * 0x28), state 1 / 2
OPTION_ROW_SITE = 0x405BF6        # Popup_on_dialog_item_back_draw's Buffer_box_sprite (-> t_rowbox_solid)
MENU_ROW_SITE = 0x403B55          # g_menu_hilite_draw's Buffer_box_sprite(self+0x474, set 0 / 2) under the row clip
MENU_BORDER_SITE = 0x403B88       # g_menu_border_draw's Buffer_box_sprite(self+0x474, set 0)


def ring_band_rects(l: int, t: int, r: int, b: int, k: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """The four K bands of a ring on the HALF-OPEN rect [l, r) x [t, b), as half-open (x0, y0, x1, y1) -- top, bottom,
    left, right -- each WITHOUT the k x k corner squares (the band map leaves those keyed: the scaled 1 x 1 notch)."""
    return ((l + k, t, r - k, t + k), (l + k, b - k, r - k, b), (l, t + k, l + k, b - k), (r - k, t + k, r, b - k))


def ring_solid(painted, rect, g: int, strokes, clip=None):
    """LAW (2026-10-25 wave-7 W7R) -- a band-mapped 0x78D960-family ring made solid again (t_ring_solid).

    The popup option rows (OPTION_ROW_SITE) draw the ListBox HOVER row (ListBox_draw_item 0x60BB58: state 1 when the
    item is the list's hover index [+0xF0]) with the state-1 set: vanilla a 1-px SOLID E0 ring on the half-open row
    rect.  The band map (t_rowbox_trim -> t_rowbox_ph -> thunk_rowbox_guard -> thunk_box_thick_hollow_flat) already
    draws it K = stroke_width(g) wide on bandmap_rect_from_halfopen of the rect, with K x K keyed corners, but its pair
    remap restripes the stroke into E0 / E1 (the dither-pair collateral).  Vanilla's stroke is one index, so inside each
    K band (ring_band_rects, corners excluded) of the half-open rect (the band-map rect + 1 on R / B), intersected with
    the clip and the canvas, the stroke's pair mate goes back to the stroke (STROKE_MATE, as faction_row_face step 6).
    The interior and everything outside the bands are untouched; the list draws the row text after the back, over it,
    as in vanilla.  painted: the canvas (row lists) as the band map left it -- the engine's own render; strokes =
    box_edge_strokes of the state's set (states 0 / 2: none -> nothing changes); clip = the Buffer's clip (L, T, R, B)
    half-open, default the canvas.  Applied only when g > 16 and the rect is >= 2K each way.  g <= 16: verbatim."""
    out = [list(row) for row in painted]
    if g <= NATIVE_G:
        return out
    k = stroke_width(g)
    l, t, r, b = rect
    if r - l < 2 * k or b - t < 2 * k:
        return out
    hh, ww = len(out), (len(out[0]) if out else 0)
    cl, ct, cr, cb = clip if clip is not None else (0, 0, ww, hh)
    cl, ct, cr, cb = max(cl, 0), max(ct, 0), min(cr, ww), min(cb, hh)
    for col, (x0, y0, x1, y1) in zip(strokes, ring_band_rects(l, t, r, b, k)):
        m = STROKE_MATE.get(col) if col is not None else None
        if m is None:
            continue
        for y in range(max(y0, ct), min(y1, cb)):
            for x in range(max(x0, cl), min(x1, cr)):
                if out[y][x] == m:
                    out[y][x] = col
    return out


def menu_row_clip(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-25 wave-7 W7R v2) -- the universal Menu's row clip (g_menu_hilite_draw 0x403AF0: vanilla
    (1, row top, W - 1, row bottom), W = the menu width [+0x47C]; the row's set -- 2 hot, 0 else -- is drawn over the
    whole menu rect under it).  The 1-px inset of every row from the menu's left / right edges is the same vanilla
    feature size as the background's 1 x 1 corner notch, so it scales with it: inset K = stroke_width(g) (the band map's
    notch, menu_box_rect) on both sides -- the vanilla relation inset == notch kept, mirrored.  Identity at g <= 16."""
    if g <= NATIVE_G:
        return (l, t, r, b)
    k = stroke_width(g)
    return (l + k - 1, t, r - (k - 1), b)


def menu_box_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-25 wave-7 W7R v2) -- the universal Menu background (g_menu_border_draw 0x403B70: the state-0 set over
    the menu's half-open rect [+0x474]) at g > 16 takes the popup option rows' path: the band map of
    bandmap_rect_from_halfopen(rect) (thunk_rowbox_guard -> thunk_box_thick_hollow_flat), so the AE / EE fill is on the
    stripe law (stripe_rows(g) rows per stripe, phase = the menu buffer's row; natively it stayed the 1-row tile at
    every g) and the 1 x 1 keyed corner notch is K x K, K = stroke_width(g).  The rows (menu_row_clip) keep their native
    draw under the scaled clip and are restriped in it: a normal row (state 0, AE / EE) by t_rw_restripe on the same
    buffer grid as the background (top member = the fill tile's row 0, AE, the band map's own top), the HOT row (state 2,
    E0 / E1) anchored to its own top (menu_hot_row_colour).  Identity at g <= 16."""
    if g <= NATIVE_G:
        return (l, t, r, b)
    return bandmap_rect_from_halfopen(l, t, r, b, g)


MENU_HOT_SET = 0x78D9B0            # the state-2 set g_menu_hilite_draw draws on the hot row
MENU_HOT_TOP, MENU_HOT_MATE = 0xE0, 0xE1


def menu_hot_row_colour(y: int, row_top: int, g: int) -> int:
    """LAW (2026-10-25 wave-7 W7R v3, audit-w7R) -- the universal Menu's HOT row fill (the state-2 E0 / E1 pair) at g > 16:
    device row y of a hot row whose clip top is row_top takes MENU_HOT_TOP (E0) on the first T rows of each period and
    MENU_HOT_MATE (E1) on the next T, T = stripe_rows(g), counted from the ROW's top: ((y - row_top) // T) % 2 == 0 -> E0.

    Vanilla (1024x768, measured): every hot row starts with E0 on its top edge and all hot rows look identical.  A grid
    anchored on the menu buffer's row (v2: t_rw_restripe, E1 top) made the hot rows differ from one another wherever the
    row pitch is not a multiple of the period -- 1920x1080 alternated E1 / E0 tops row to row and cut 1-row stripes at a
    row's top and bottom.  Anchoring on the row's own top restores vanilla's look at every g.  It gives up the alignment
    of the hot row's stripes with the background's AE / EE grid; the two meet only in the K-px inset columns beside the
    row (menu_row_clip), accepted for vanilla's look (audit-w7R).  Every E0 / E1 pixel in the row's clip is rewritten (the
    row holds the pair alone when the fill is restriped: its text is drawn after).  Identity at g <= 16 (not applied)."""
    t = stripe_rows(g)
    return MENU_HOT_TOP if ((y - row_top) // t) % 2 == 0 else MENU_HOT_MATE


FILEDLG_BTN_RECTS = {            # FileDlg_layout's 17-dword array [9..16]: OK / CANCEL, window-local, vanilla
    "menu": ((19, 358, 165, 380), (168, 358, 315, 380)),     # Path A (main-menu LOAD), window w 0x14E
    "ingame": ((33, 348, 179, 370), (182, 348, 329, 370)),   # Path B (in-game LOAD / SAVE), between the rails
}


def filedlg_btn_pair(ok, cancel, g: int):
    """LAW (2026-10-25 wave-2 F41) -- the Load / Save OK | CANCEL windows (thunk_filedlg_rects v2, on the 17-dword
    array at the FileDlg_build_widgets call @0x40771B).  Vanilla: 146 | 147 x 22 with EQUAL outer margins (Path A
    19 | 19 in the 334 window; Path B 10 | 10 inside the 23 / 55 rails) and a 3-px seam -- a mirrored pair whose odd
    total (293) gave CANCEL the extra pixel.  The floor of each edge (v1) made it 228 | 230 at 1600x1200 (2 px
    apart) and the height fl(370g/16) - fl(348g/16) = 35 at g 25, whose CEIL inverse recovers 23 native rows for the
    22-row window: the 20-row art came out 30 rows (faction picker, same art, same g: 31).  The law (the lobby pair's,
    netwin_btn_pair; the user's symmetry rule):
      L = fl(ok.l g/16), R = fl(cancel.r g/16)   -- the outer edges, unchanged;
      S = fl((cancel.l - ok.r) g/16)               -- the seam;
      w = (R - L - S) >> 1 for BOTH (the odd px to the seam, never to one button);
      T = fl(ok.t g/16), H = fl((ok.b - ok.t) g/16) for both (B = T + H: the window is the floor image of the
      vanilla 22, so the CEIL inverse recovers 22 and the face is btn_bar_tile_height(H, 22, 20) = vanilla x g/16).
    g <= 16: vanilla, verbatim (146 | 147)."""
    if g <= NATIVE_G:
        return tuple(ok), tuple(cancel)
    L, R = popup_scale_floor(ok[0], g), popup_scale_floor(cancel[2], g)
    T, H = popup_scale_floor(ok[1], g), popup_scale_floor(ok[3] - ok[1], g)
    w = (R - L - popup_scale_floor(cancel[0] - ok[2], g)) >> 1
    return (L, T, L + w, T + H), (R - w, T, R, T + H)


# The one MEASURED native [+0x44] inter-row margin. 3 is the popup Dialog
# struct-copy default (q16 evidence: "a struct-copy default with NO immediate
# initializer in .text, reading a constant 3 at EVERY g").  The PrefWin page
# dialogs do NOT share it: Dialog_init_2 seeds the Dialog default 6 (0x69709c;
# frida_quit_rows.log textelem gap_44=6 at 1024 AND 4K), and their calc takes
# the FIXED-HEIGHT path (flags&1 && [+0x30]) that never reaches the thunk_rowgap
# site 0x60f018 -- the 2026-07-11 "wrote 3 vs left-native drew identical rows"
# proof was vacuous for them (the thunk never ran there).
# Do NOT add values that were merely inferred: an earlier "PrefWin native = 1"
# inference came from misattributing the +2px row pitch that actually belonged
# to the ungated popup_list_rowheight redirect (font leading, not margin).
DIALOG_ROW_MARGIN_NATIVES = (3,)


def dialog_row_margin(field_value: int, g: int) -> int:
    """LAW 1 on the generic Dialog inter-row margin [+0x44] (thunk_rowgap v2).

    FUN_0060ed10's pitch reserve is `pitch = [+0x68] line-height + [+0x44]
    margin`, shared by EVERY multi-row Dialog list (popup option/checkbox
    lists, PrefWin pages, ...). The margin never scaled natively, so the thunk
    SETs the field at the calc. v1's defect this law repairs: it gated on
    ScreenWidth > 0x3FF — at 1024x768 (W=0x400, g=16) it FIRED
    ([[feedback-loores-gate-on-g]]); the gate is now g > 16, so g<=16 returns
    the field untouched (the native no-op is the gate itself, with no width
    literal to slip).

    The scaled value is floor(native * g / 16) — floor (the asm's `sar 4`),
    NOT half_down: v1 shipped floor and that look is user-verified at
    g=22/25/40; for native 3 the two roundings differ at g=25 (4 vs 5), so
    half_down would silently move approved screens. For g>16 this law is
    bit-identical to v1.

    VALUE MAP, not blind scaling: the calc runs twice per build and the field
    is persistent, so the transform must be idempotent. Only the measured
    native (3) is scaled; everything else — including the law's own outputs
    4..7 on a second pass — passes through (3 itself is the fixed point for
    g<22, where floor(3g/16)==3). f(f(v)) == f(v) for every g.

    Pitch-pinning (option_row_gap's stronger form) is NOT available here: the
    site is one shared code path and the native pitch differs per dialog
    family, so it cannot be a thunk constant; the margin's own native value,
    read from the field, is the only per-dialog quantity the thunk has.
    """
    if g <= NATIVE_G:
        return field_value
    if field_value in DIALOG_ROW_MARGIN_NATIVES:
        return (field_value * g) >> 4
    return field_value


def dialog_row_margin_native(field_value: int, g: int, rowgap_path: bool) -> int:
    """The NATIVE [+0x44] behind a field thunk_rowgap may already have scaled (its inverse).

    thunk_rowgap runs only on the type-1 calc's else-path (0x60f018: flags&1 == 0
    or [+0x30] == 0) and maps the native 3 to floor(3g/16); everything else is
    untouched.  So on that path a field equal to floor(3g/16) IS a native 3, and
    off it (the fixed-height Dialog_init_2 / Dialog_init_3 lists: PrefWin
    pages, the editor CheckList) the field is native as read.  Exact for every
    native the type-1 consumers carry (3 on the else-path; 6 off it) --
    test_scaling_list_fill_width.py pins the round trip.
    """
    if g <= NATIVE_G or not rowgap_path:
        return field_value
    for native in DIALOG_ROW_MARGIN_NATIVES:
        if field_value == (native * g) >> 4:
            return native
    return field_value


# ==== Type-1 popup checkbox-list rows on ONE uniform pitch (W8T F46, 2026-10-27) ====
# Vanilla (pristine bytes + a pristine render of GOVOPTIONS / RULES at 1024x768): Popup_calculate_dimensions writes the
# popup Dialog's row preset [+0x48] = 0x13 (0x404CE8, every popup type but 5) and gap [+0x44] = 3 (0x404D04); the calc
# FUN_0060ed10 sets [+0x68] = max([+0x48], Buffer_text_height) = max(19, 12) = 19 and, on its else-path (0x60F018),
# [+0x60] = ([+0x68] + [+0x44]) * rows; CheckList_draw_item puts row r's bar at listY + extra + r*22 + (3 >> 1), 19
# rows tall (max(rowH, lineH * extra_lines), 0 extra lines); the click handler (0x60F735) takes row = y / 22.
# The deployed lever (popup_list_rowheight) feeds the calc the device LINE height (50 @g40, native 20) for its
# Buffer_text_height, so the bar became s(20) where vanilla's is the preset 19, and the stride s(20) + fl(3g/16)
# accumulated: 4K 57 for 55, the list 1083 for 1045.
# User decision (2026-10-27): EQUAL gaps -- one uniform pitch (the repo's uniform-pitch law, as pref_tab_pitch /
# option_row_gap: the PITCH obeys LAW 1, P = half_down(22 g, 16)), the bars ~s(19) (stripe-symmetric pick), the first
# top s(1); the list is rows x P, i.e. it drifts from rows x 22 g/16 by rows x (P - 22 g/16) (accepted: -9.5 px at
# 1280x1024).  User decision (2026-10-27, option B of the W8T audit): each label is LIFTED so its main ink ends on
# the bar's last row (vanilla: the 'p' descender ends on row 19 of the 19-row bar; the scaled label font's ink is
# 6-14 % taller than 14 g/16, so the bottom-aligned label's top margin is 1.25-4.25 px short -- accepted), and the
# checkbox is top-aligned on the bar (vanilla top 0).
TYPE1_ROW_GAP_NATIVE = DIALOG_ROW_MARGIN_NATIVES[0]     # 3: the one native gap these rows serve
TYPE1_ROW_TOP_NATIVE = TYPE1_ROW_GAP_NATIVE >> 1        # 1: the draw's gap >> 1 above each bar
TYPE1_POPUP_ROW_PRESET = 0x13                            # 19: the popup Dialog's [+0x48] (0x404CE8)


def type1_row_h(preset: int, g: int) -> int:
    """LAW 1 -- the type-1 popup row's bar height (vanilla's preset 19, which beats its 12-px glyph): of s(preset) - 1,
    s(preset), s(preset) + 1, the ones within 1 px of preset x g/16 whose gap P - h is within 1 px of 3 g/16 and
    which are a multiple of the stripe thickness T = stripe_rows(g) (then the restriped bar face's top and bottom
    edge runs are equal at every stripe phase: the bars and the uniform pitch put each row on a different phase), the
    nearest to preset x g/16 (the smaller on a tie); none -> s(preset).  4K: 48 (47.5 is a tie; 47 is odd)."""
    base = scale_px(preset, g)
    if g <= NATIVE_G:
        return base
    pitch = type1_row_pitch(preset, g)
    t = stripe_rows(g)
    cands = [h for h in (base - 1, base, base + 1)
             if abs(16 * h - preset * g) <= 16 and abs(16 * (pitch - h) - TYPE1_ROW_GAP_NATIVE * g) <= 16 and h % t == 0]
    return min(cands, key=lambda h: (abs(16 * h - preset * g), h)) if cands else base


def type1_label_lift(font_off: int, font_cap_h: int, ink_descent: int, bar_h: int) -> int:
    """LAW (option B) -- how far the row label is lifted so its main ink ends on the bar's last row: the label's rect
    top is rowTop + font[+0x1C] (tmDescent; CheckList_draw_item 0x60F46B) and its baseline font[+0x10] (cap_h =
    tmAscent - tmInternalLeading) below that (the writer), so the ink ends at font[+0x1C] + font[+0x10] +
    ink_descent; ink_descent = the label font's 'p' black box below its origin (GetGlyphOutlineA GGO_METRICS:
    gmBlackBoxY - gmptGlyphOrigin.y -- the deepest of the labels' descenders, = g j q y ( ), measured: vanilla 3,
    4K 8; tmDescent is 4 / 10 and no font field tracks the ink: off by -2..+2 over g 17..40).  Never lowered (0
    when it already fits)."""
    return max(0, font_off + font_cap_h + ink_descent - bar_h)


def type1_checkbox_y_arg(row_top: int, g: int) -> int:
    """LAW (option B) -- the y FUN_00405b20 hands t_ck_list for a marked row: t_ck_list adds (16 - g) >> 1
    (checkbox_list_y), so handing row_top - ((16 - g) >> 1) draws the checkbox top on the bar's top row (vanilla:
    top 0, bottom 1 = bar 19 - sprite 18).  The engine's centring ((H - 18) >> 1) + ((16 - g) >> 1) mixed native
    and device units and sat the box flush with the bar bottom at g 24 / 32 / 34 / 36 / 40."""
    return row_top - ((NATIVE_G - g) >> 1)


def type1_row_pitch(preset: int, g: int) -> int:
    """The ONE device pitch: half_down((preset + 3) g, 16) (vanilla 22).  Every gap is P - s(preset), equal."""
    return half_down((preset + TYPE1_ROW_GAP_NATIVE) * g, NATIVE_G)


def type1_row_cell(r: int, preset: int, g: int) -> int:
    """Row r's click cell boundary in the list window: r * P.  cell(rows) is the list height (vanilla rows x 22)."""
    return r * type1_row_pitch(preset, g)


def type1_row_top(r: int, preset: int, g: int) -> int:
    """Row r's bar top in the list window (before the draw's multi-line `extra`): s(1) + r * P (vanilla 1 + 22 r).
    Inside its cell for every g >= 16: s(1) + s(preset) <= P (their ideal sum is 2 g/16 short of it)."""
    return scale_px(TYPE1_ROW_TOP_NATIVE, g) + r * type1_row_pitch(preset, g)


def type1_row_at(y: int, preset: int, g: int) -> int:
    """The click handler's row for list-window y: y // P (x86 idiv truncates; y >= 0) -- the exact inverse of the
    cells, as vanilla's y / 22."""
    return _trunc_div(y, type1_row_pitch(preset, g))


def type1_row_cum_calc(g: int, rows: int, preset: int, gap_field: int, text_h_dev: int) -> bool:
    """The calc gate (t1c_calc, after thunk_rowgap at the else-path 0x60F018): g > 16, a multi-row list, a positive
    native preset, the popup gap (the field thunk_rowgap leaves: fl(3g/16) for the native 3), and vanilla's max()
    still picking the preset (the device glyph height <= s(preset); vanilla 12 <= 19).  True -> [+0x68] =
    type1_row_h, [+0x60] = type1_row_cell(rows); False -> the engine's ([+0x68] + [+0x44]) * rows, as deployed."""
    return (g > NATIVE_G and rows > 1 and 0 < preset < 0x100
            and gap_field == (TYPE1_ROW_GAP_NATIVE * g) >> 4 and text_h_dev <= type1_row_h(preset, g))


def type1_row_cum_marked(g: int, rows: int, preset: int, gap_field: int, row_h_field: int, list_h_field: int) -> int:
    """The draw / click gate (t1c_pn): the device pitch P when the dialog carries the calc's identity ([+0x68] ==
    s(preset), [+0x60] == rows x P, the popup gap), else 0 (the engine's stride: PrefWin pages and the editor
    CheckLists carry preset -1, the type-16 / type-8 lists never reach these sites)."""
    if not (g > NATIVE_G and rows > 1 and 0 < preset < 0x100 and gap_field == (TYPE1_ROW_GAP_NATIVE * g) >> 4):
        return 0
    if row_h_field != type1_row_h(preset, g) or list_h_field != type1_row_cell(rows, preset, g):
        return 0
    return type1_row_pitch(preset, g)


def type1_row_layout(rows: int, preset: int, g: int) -> List[Tuple[int, int]]:
    """Every bar's half-open rows [top, top + h) in the list window (single-line rows), the list height being
    type1_row_cell(rows).  g = 16: [22 r + 1, 22 r + 20), vanilla's own arithmetic."""
    h = type1_row_h(preset, g) if g > NATIVE_G else preset
    return [(type1_row_top(r, preset, g), type1_row_top(r, preset, g) + h) for r in range(rows)]


# ==== Type-1 checkbox-list bar faces striped from each bar's OWN top (W9B, 2026-10-27) ====
# The bars are drawn by the popup painter FUN_00405b20 (Popup_on_dialog_item_back_draw) at 0x405BF6 with the set
# 0x78D960 + state * 0x28: state 2 when the row's checkbox is ON (CheckList_draw_item's flag = [+0xEC] bit), else 1
# for the list's cursor row ([+0xF0] == idx), else 0.  Vanilla, measured (pristine render of GOVOPTIONS at 1024x768,
# confirmed on the user's shot 20261024-130147): every bar opens and closes with EE (states 0 / 1; state 1 adds the
# solid 1-px E0 ring over that face) or E0 (state 2), alternating 1-row stripes -- every row an identical copy (the
# 22-px pitch is even, so the bar's grid and the list buffer's grid agree).  Deployed (W8T v3): the band map's pair
# remap stripes the bars on the POPUP's grid (t_rowbox_ph / option_row_stripe_phase), and the uniform pitch P is not a
# multiple of the period 2T at most g, so the rows alternate 2 (or 4) looks and the dark edge rows merge with the gap.
TYPE1_BAR_OPEN = {0x78D960: 0xEE, 0x78D988: 0xEE, 0x78D9B0: 0xE0}   # the face index on each bar's top row (vanilla)
TYPE1_BAR_HOVER_SET = 0x78D988       # state 1: the face under the solid E0 ring (the only set with a stroke)


def type1_bar_pair(set_va: int) -> Tuple[int, int]:
    """(opening, mate) of a type-1 bar's face pair: (E0, E1) for the checked set 0x78D9B0, else (EE, AE)."""
    o = TYPE1_BAR_OPEN.get(set_va, 0xEE)
    return o, STROKE_MATE[o]


def type1_bar_colour(y: int, bar_top: int, set_va: int, g: int) -> int:
    """LAW (W9B, user decision 2026-10-27: "make every row identical") -- the face index of device row y of a marked
    type-1 bar (type1_row_cum_marked != 0) whose top row is bar_top, at g > 16: vanilla's opening member
    (type1_bar_pair) on the first T = stripe_rows(g) rows counted from the BAR's own top, the mate on the next T, and
    so on: ((y - bar_top) // T) % 2 == 0 -> opening.  The universal Menu's hot row is the precedent
    (menu_hot_row_colour).  Every bar of every state is then an identical copy, as in vanilla.  Given up (accepted by
    the user): the bars' stripes are out of step with the list background's in the gaps.  Where h / T is even
    (type1_row_h) the bar closes on the mate, where vanilla closes on the opening member (19 rows, odd); where
    h % T != 0 the last stripe is cut short -- both follow from W8T's bar height, which this law does not move.

    v2 (audit-w9B item 3) -- the HOVER row (TYPE1_BAR_HOVER_SET: the solid ring K = stroke_width(g) over the face):
    vanilla's 1-px ring covers exactly the opening stripe, so the interior starts on the mate, flush against the ring.
    Where K < T (g 22..24: K 1, T 2) a top anchor left a 1-row sliver of the opening member under the ring, so the
    hover row's phase origin is bar_top + K - T: the T-row opening stripe ends exactly under the ring and the interior
    opens with a full T-row mate stripe.  Identical to the plain anchor wherever K == T (g 17..21, 25..40).  The
    interior's bottom end stays on the regular grid (a mirrored bottom anchor would also close it on the mate, but only
    by a centre stripe of 2T / T +- 1 rows: one stripe thickness is the dither law, audit-w9B item 4 declined)."""
    o, m = type1_bar_pair(set_va)
    t = stripe_rows(g)
    origin = bar_top + (stroke_width(g) - t if set_va == TYPE1_BAR_HOVER_SET else 0)
    return o if ((y - origin) // t) % 2 == 0 else m


TYPE1_POPUP_KIND = 1                 # the popup's list kind [popup + 0x2350] (FUN_00405b20's checkbox branch 0x405B92)


def type1_bar_gate(g: int, popup_kind: int, marked_pitch: int) -> bool:
    """The gate of the bar restripe (t1c_bar at 0x405BF6): g > 16, a type-1 (checkbox) popup list, and its Dialog
    carrying the W8T calc's identity (type1_row_cum_marked != 0).  ListBox popups (type 2), PrefWin pages and the
    editor CheckLists (preset -1, unmarked) and every g <= 16 keep the deployed draw byte for byte."""
    return g > NATIVE_G and popup_kind == TYPE1_POPUP_KIND and marked_pitch != 0


def type1_bar_restripe(canvas, rect, set_va: int, g: int, clip=None):
    """The port's whole effect (t1c_bar, after the deployed draw t_rowbox_solid): inside the bar's drawn extent rect
    (l, t, r, b) half-open -- the band-map rect + 1 on R / B, as t_ring_solid takes it -- cut to the Buffer's clip
    (half-open, default the canvas) and the canvas, every pixel equal to either member of the set's pair becomes
    type1_bar_colour(y, t).  Nothing else changes: the keyed corner notch (the captured background), the state-1 ring
    (solid E0, not a member of the AE / EE pair), and the label / checkbox (the checkbox is drawn left of the rect, the
    label after it).  Applied by the caller only for a marked list at g > 16; returns a new canvas."""
    out = [list(row) for row in canvas]
    hh, ww = len(out), (len(out[0]) if out else 0)
    l, t, r, b = rect
    cl, ct, cr, cb = clip if clip is not None else (0, 0, ww, hh)
    o, m = type1_bar_pair(set_va)
    for y in range(max(t, ct, 0), min(b, cb, hh)):
        c = type1_bar_colour(y, t, set_va, g)
        for x in range(max(l, cl, 0), min(r, cr, ww)):
            if out[y][x] in (o, m):
                out[y][x] = c
    return out


def _trunc_div(a: int, b: int) -> int:
    """x86 `idiv` (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def type1_list_widths(xs: int, margin: int, cols: int, gap: int, fixed: bool,
                      text_w: int = 0, indent: int = 0) -> Tuple[int, int, int]:
    """VANILLA's type-1 list width block (OptionList_calc_reserve 0x60ED10, 0x60EEFD..0x60EFD3), every input native.

    -> (w, d5c, d64): the GraphicWin_init width arg (= [+0x5c], read at 0x60e891), [+0x5c] and [+0x64] (the
    row-highlight bar width).  `fixed` = flags&2 && xs (Dialog_init_2 / Dialog_init_3 set flags|=3):
        [+0x5c] = xs,  [+0x64] = (xs - 2m)/cols - gap
    else (popup lists): [+0x64]' = gap + indent + max text width; [+0x5c]' = max(xs + 2m, [+0x64]'*cols + 2m);
        [+0x64] = ([+0x5c]' - 2m)/cols - gap,  [+0x5c] = [+0x5c]' - gap.
    Measured (Frida): Customize Game Rules xs 660 gap 3 -> 657/657/657; PrefWin page xs 457 gap 6 -> 457/457/451.
    """
    m2 = 2 * margin
    if fixed and xs:
        return xs, xs, _trunc_div(xs - m2, cols) - gap
    d64 = gap + indent + text_w
    d5c = max(xs + m2, d64 * cols + m2)
    d64 = _trunc_div(d5c - m2, cols) - gap
    return d5c - gap, d5c - gap, d64


def type1_list_xs_dominant(xs: int, margin: int, cols: int, gap: int, text_w: int, indent: int) -> bool:
    """True when vanilla's [+0x5c] comes from xs, not from the text (the else-path `jg` @0x60EF9E keeps xs + 2m).
    thunk_list_fill_width re-forms vanilla from xs alone, so every list it serves must satisfy this at native."""
    return xs + 2 * margin > (gap + indent + text_w) * cols + 2 * margin


DIPLO_EDIT_VTBL = 0x0066E964    # DiploEditWin vtable: the editor diplomacy modal, whose CheckList rect is pre-scaled


def type1_list_fill_width(xs: int, margin: int, cols: int, gap_field: int, flags: int, fixed_h: int,
                          rows: int, g: int, owned: bool = False) -> Optional[Tuple[int, int, int]]:
    """LAW 1 on the type-1 checkbox-list window (thunk_list_fill_width v3, FUN_0060e800 0x60e8a1).

    -> (w, d5c, d64) the thunk writes, or None (untouched: GraphicWin_init gets vanilla's args).

    patched = floor(vanilla * g/16) of EACH of w, [+0x5c], [+0x64] -- scale vanilla's RESULT, never re-derive it
    from scaled parts (Customize Game Rules 4K: fl(657*2.5) = 1642, where s(660) - s(3) = 1643 and v1/v2's
    s(660) = 1650; PrefWin page bar fl(451*2.5) = 1127, v1/v2 1142).  `vanilla` = type1_list_widths on the
    NATIVE inputs, xs-dominant (the thunk cannot see the native text width at g > 16: the calc measured the
    scaled font -- type1_list_xs_dominant must hold for every list served); the gap is
    dialog_row_margin_native of the field (thunk_rowgap has run on the else-path by the time this does).

    `owned`: a container its owner already scaled (DiploEditWin, the editor immtab law): xs is device px, so
    w = [+0x5c] = xs and [+0x64] = (xs - s(2m))/cols - s(gap), s = floor(v*g/16) -- vanilla's insets, scaled.

    g <= 16 or a single row (rows <= 1: a label / Planetfall's wrapped body) -> None.
    """
    if g <= NATIVE_G or rows <= 1:
        return None
    is_fixed = bool(flags & 2) and xs != 0
    if owned:
        bar = _trunc_div(xs - ((2 * margin * g) >> 4), cols) - ((gap_field * g) >> 4)
        return xs, xs, bar
    rowgap_path = not (flags & 1) or fixed_h == 0
    gap = dialog_row_margin_native(gap_field, g, rowgap_path)
    w, d5c, d64 = type1_list_widths(xs, margin, cols, gap, is_fixed)
    return (w * g) >> 4, (d5c * g) >> 4, (d64 * g) >> 4


def t16_row_line_count(text_w_native: int, text_w_device: int, budget: int,
                        g: int, anchored: bool) -> int:
    """LAW — the type-16 calc's per-row line count (0x60D5FA: lines = W / budget + 1,
    budget = [+0x2C]/cols - 2*[+0x40] - [+0x34]); W and the budget must be in ONE space.

    Ordinary popups keep [+0x2C] native (#xs), so W is the NATIVE-font measure
    (thunk_t16_measure_native; t16_row_measure_width). An ANCHORED popup (BasePop
    +0xA14: the diplomacy talk window) has [+0x2C] = the parent's DEVICE width
    (measured 1750 @g40 / 700 @g16), so W must be the DEVICE-font measure
    (thunk_t16_measure_sel tail-jumps the real Buffer_text_width). The defect
    form, native W over a device budget, is always 1 line: a long reply clipped
    where vanilla wraps it to a two-line button. Device W, not native W x g/16:
    the device font is narrower than proportional (font-metric sublinearity), so
    the scaled estimate would wrap rows that fit.
    """
    if g <= NATIVE_G:
        return text_w_native // budget + 1
    w = text_w_device if anchored else text_w_native
    return w // budget + 1


def t16_row_text_budget(budget: int, indent_native: int, gap: int, g: int,
                        anchored: bool) -> int:
    """LAW — the divisor of t16_row_line_count must be the width the text is DRAWN in
    (uimod rowindent.cpp, site 0x60D5FA).

    The engine divides by budget = [+0x2C]/cols - 2*[+0x40] - [+0x34], but the
    painter's text rect is [+0x64] - indent with [+0x64] = budget + [+0x34] - gap:
    the budget is `gap` px too wide in vanilla (3 px), and t16_row_text_indent
    widens the slip to gap + (indent_dev - indent_native). A reply whose width
    lands in that window counts one line and clips at the button's right edge
    (measured 2026-09-20 @g40: W 1496, budget 1498, drawn ~1488).

    Anchored popups only, g > 16: there W and the budget are both device. Ordinary
    popups divide native by native (verified) and are left alone, as is g <= 16.
    """
    if g <= NATIVE_G or not anchored or budget <= 0 or budget >= 100000:
        return budget
    drawn = budget - gap - (t16_row_text_indent(indent_native, g) - indent_native)
    return drawn if drawn > 0 else budget


T16_ROW_TEXT_INDENT_NATIVE = 3


def t16_row_text_indent(field_value: int, g: int) -> int:
    """LAW — the type-16 reply-row text indent (Dialog [+0x34], native 3), scaled
    IN-REGISTER at the painter's read 0x60DB8B (FUN_0060d750: rect.left += [+0x34])
    — uimod rowindent.cpp.

    Pristine TechTrade/CommlinkTrade vs our 4K diplomacy rows (2026-09-19): the
    row height, font and vertical centring all scale, the button-edge -> text
    channel stayed a literal 3 px (+1 glyph bearing): 4 px where vanilla x 2.5
    is 10.

    Scaled at the READ, never at the writer 0x404D3F: the stored field is also
    the F term of t16_row_measure_width (d5c = max(xs, W+F) - F, native space,
    then one xg/16) — a device value there narrows every xs-won box by
    (F_dev - 3) native px. The stored field stays native; one consumer scales.
    scale_px (half_down), not the popup family's floor: this is new work, and on
    a 3 px native the floor loses most of a pixel at g=25 (4 vs 4.69; measured
    visibly tight at 1600x1200). asm: (2*v*g + 15) >> 5.
    """
    if g <= NATIVE_G:
        return field_value
    return scale_px(field_value, g)


def popup_scale_floor(v: int, g: int) -> int:
    """The popup-family FLOOR idiom: floor(v * g/16), the asm's `imul; sar 4`.

    This is deliberately NOT scale_px (half_down): the entire baked popup/pref
    lever family shipped floor and was user-verified at g=22/25/40; the two
    roundings differ at exact .5 boundaries (e.g. 350*25/16 = 546.875 floors
    to 546 where half_down says 547), so switching would move approved
    screens. New chrome-stroke work uses scale_px/stroke_width; consumers of
    THIS function are ports of the floor-based prototypes.
    """
    return (v * g) >> 4


def prefwin_window_pos(screen_w: int, screen_h: int, g: int) -> Tuple[int, int]:
    """The PrefWin window-position law (thunk_pref_gwinit self-arm +
    thunk_pref_show rect re-assert; prototype hook_prefwin_scale.js v19,
    user-verified at all four resolutions).

    Vanilla's OWN ctor computes x = ScreenW/2 - 350, y = ScreenH - 618 (the
    constants are resolution-independent, the screen terms are not), so the
    scaled law keeps the screen terms and scales only the constants:

        x = ScreenW/2 - floor(350*g/16),  y = ScreenH - floor(618*g/16)

    At g=16 this collapses to vanilla's own expression — the native no-op is
    algebraic. Verified against the live prototype log: (1045,615) @4K,
    (254,235) @1600x1200.
    """
    return (screen_w // 2 - popup_scale_floor(350, g),
            screen_h - popup_scale_floor(618, g))


PREFWIN_NATIVE_WH = (778, 390)      # PrefWin_build's GraphicWin_init w / h (the ctor's literals)
PREFWIN_BACKDROP_SITE = 0x48FB19    # PrefWin_show's d690 backdrop (23, 0, W - 55, H): rail to rail
#: the nine PrefWin Buffer_box_sprite chrome sites (thunk_pref_boxframe; the backdrop through t_pref_bd) -- every rect
#: NATIVE, half-open: PrefWin_show 0x48FB19 backdrop d690, 0x48FB29 inner d690, 0x48FB39 left panel d7f8, 0x48FBB7
#: right panel d7f8, 0x48FC01 audio slider frame d690; PrefWin_repaint_right 0x49184D, PrefWin_repaint_gamma 0x4918B1,
#: PrefWin_refresh 0x491C42 / 0x491C8C.  uimod.dll's Longevity page calls thunk_pref_boxframe too (the same contract).
PREF_FRAME_SITES = (0x48FB19, 0x48FB29, 0x48FB39, 0x48FBB7, 0x48FC01, 0x49184D, 0x4918B1, 0x491C42, 0x491C8C)

#: The PrefWin frames' NATIVE half-open rects, measured on the pristine image (prefwin_halfopen_emu at 1024x768; the
#: sites rebuild them from PrefWin_build's statics every call).  'dll' is uimod.dll's Longevity-page slider frame
#: (prefs.cpp: FrameX, FrameY - BotShift + 44, + FrameW, + 48; BotShift is 0 at every g > 16).
PREF_FRAME_NATIVE = {
    "backdrop": (23, 0, 723, 390),
    "inner": (27, 4, 719, 386),
    "lpanel": (30, 7, 250, 383),
    "rpanel": (253, 7, 716, 383),
    "sframe": (256, 287, 713, 379),
    "dll": (256, 331, 713, 379),
}
#: The frames' CONTENT, native child-window x / y / w / h (thunk_pref_gwinit scales each arg by floor, so a child's
#: device right edge is fl(x g/16) + fl(w g/16)): the left panel's button column (first row y 10, last row 360 + 20),
#: the right panel's page list (x 256, w 457, top y 10; thunk_pref_attach / thunk_list_fill_width) and the More
#: button under it (PrefWin_btn_more, 256, 360, 214, 20), the slider rows' label column (x 259, y 290 + 22 i, h 20: the
#: audio page's Off toggles, the Longevity page's labels; the sliders at x 382, w 328).
PREF_BTN_X, PREF_BTN_W = 33, 214
PREF_CONTENT_TOP, PREF_CONTENT_LAST_Y, PREF_ROW_H = 10, 360, 20
PREF_LIST_X, PREF_LIST_W = 256, 457
PREF_LABEL_LAST_Y = 356             # the audio page's 4th label row (290 + 3 * 22); the Longevity frame's 2nd


def prefwin_window_wh(g: int) -> Tuple[int, int]:
    """LAW (2026-10-25 wave-6 W6A, F42) -- the PrefWin window's device w / h (thunk_pref_gwinit's self arm).

    w = CEIL(778g/16), h = fl(390g/16).  PrefWin slides in on the slide rails, whose right strips re-anchor through
    railscale's double floor fl((fl(W*16/g) - 55) * g/16) (rail_right_strip_x).  A floored W loses a native px in
    that descale whenever 778g/16 is fractional (g=22: fl(1069*16/22) = 777), so the right rails landed 1..4 px LEFT
    of the backdrop's own right edge fl(723g/16) and covered its right border entirely (1920x1080 / 1600x1200 /
    2560x1440: no right border; 4K: 1 px against the left's 2).  The ceiling is the width whose descale is exactly 778
    at every g (the se_window_w precedent), so the rails land ON fl(723g/16).  g <= 16: vanilla's own 778 x 390."""
    w, h = PREFWIN_NATIVE_WH
    if g <= NATIVE_G:
        return w, h
    return (w * g + 15) >> 4, popup_scale_floor(h, g)


def pref_backdrop_draw_rect(rect: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """t_pref_bd's law: the backdrop site's NATIVE rect -> T, R, B fl(v g/16) from that rect, L on the left slide rails'
    composed extent rail_left_extent (fl(23g/16) is one px right of it at odd g), then R-1 / B-1 (inclusive band map).
    g <= 16: the rect unchanged."""
    if g <= NATIVE_G:
        return tuple(rect)
    _l, t, r, b = (popup_scale_floor(v, g) for v in rect)
    return bandmap_rect_from_halfopen(rail_left_extent(g), t, r, b, g)


def _pref_slider_frame_bottom(t: int, g: int) -> int:
    """A slider frame's half-open device bottom (prefwin_layout): its top fl(t g/16) mirrored about the label column --
    bottom channel = fl((t + 3)g/16) - fl(t g/16) - K below the last label row's fl(356g/16) + fl(20g/16)."""
    k = stroke_width(g)
    f = lambda v: popup_scale_floor(v, g)                                     # noqa: E731
    return f(PREF_LABEL_LAST_Y) + f(PREF_ROW_H) + (f(t + 3) - f(t) - k) + k


@functools.lru_cache(maxsize=None)
def pref_chain_split(g: int) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]:
    """The PrefWin frame chain's channels at g > 16 (prefwin_layout), both axes chosen together.
    -> ((a_h, b_h, c_lp, c_rp), (a_t, b_v, c_v, a_b)).

    Each side of each axis is a chain of three channels between the backdrop border's inner edge and the content --
    backdrop -> inner (vanilla 3), inner -> panel (2), panel -> content (2) -- with a fixed budget (prefwin_layout).
    Mirrored by construction: horizontally a_h and b_h serve both sides and each panel's content channel takes its
    side's remainder (c_lp = S_L - a_h - b_h, c_rp = S_R - a_h - b_h: two different frames, each mirrored about its
    own content); vertically b_v and c_v serve top and bottom of both panels and the backdrop -> inner channel takes
    the remainder (a_t = S_T - b_v - c_v, a_b = S_B - b_v - c_v).  So the floors' slack lands in one place per axis.

    SCORED: every distinct spacing the split sets, each against vanilla x g/16 as |16 v - w g| -- the eight channels,
    the PANEL GAP (list_l - btn_r - 2K - c_lp - c_rp, vanilla 3) and the two slider frames' BOTTOM GAPS to the right
    panel (vanilla 3; v2 left these three unscored and they absorbed the error, audit-w6A v2: 4K's gap 9 vs 7.5).
    The split minimises, in order: the number of spacings MORE THAN 1 px off; the number of vanilla relations it
    breaks -- the cross-axis channel pairs left unequal (a_h | a_t, b_h | b_v, c_lp | c_v, c_rp | c_v: each frame's
    four sides are equal in vanilla); the worst error; the sum of squared errors; then the wider outer channels
    (deterministic).  Broken relations rank AHEAD of the worst error: the user's rule, symmetry beats 1-px exactness
    (W6A v4, the user's 2560x1440 decision: (5,4,3,4)/(5,4,3,6), one cross pair broken and the panel gap 1.375 px off,
    over v3's (5,3,4,5)/(5,4,3,6), worst 1.25 px but three cross pairs broken).
    Every candidate keeps each spacing >= 0."""
    k = stroke_width(g)
    f = lambda v: popup_scale_floor(v, g)                                     # noqa: E731
    bd, inner, lp = PREF_FRAME_NATIVE["backdrop"], PREF_FRAME_NATIVE["inner"], PREF_FRAME_NATIVE["lpanel"]
    rp, sf = PREF_FRAME_NATIVE["rpanel"], PREF_FRAME_NATIVE["sframe"]
    w_a, w_b, w_c = inner[0] - (bd[0] + 1), lp[0] - (inner[0] + 1), PREF_BTN_X - (lp[0] + 1)    # 3, 2, 2
    w_gap, w_sfb = rp[0] - lp[2], (rp[3] - 1) - sf[3]                                          # 3, 3
    btn_r, list_l = f(PREF_BTN_X) + f(PREF_BTN_W), f(PREF_LIST_X)
    list_r, bot = list_l + f(PREF_LIST_W), f(PREF_CONTENT_LAST_Y) + f(PREF_ROW_H)
    s_l = f(PREF_BTN_X) - (rail_left_extent(g) + k) - 2 * k
    s_r = (f(bd[2]) - k) - list_r - 2 * k
    s_t = f(PREF_CONTENT_TOP) - k - 2 * k
    s_b = (f(bd[3]) - k) - bot - 2 * k
    gap0 = list_l - btn_r - 2 * k
    sfb = [_pref_slider_frame_bottom(PREF_FRAME_NATIVE[n][1], g) for n in ("sframe", "dll")]
    err = lambda v, w: abs(16 * v - w * g)                                    # noqa: E731
    hs, vs = [], []
    for a in range(s_l + 1):
        for b in range(s_l + 1):
            cl, cr = s_l - a - b, s_r - a - b
            gap = gap0 - cl - cr
            if min(cl, cr, gap) >= 0:
                hs.append(((a, b, cl, cr), [err(a, w_a), err(b, w_b), err(cl, w_c), err(cr, w_c), err(gap, w_gap)]))
    for b in range(s_t + 1):
        for c in range(s_t + 1):
            at, ab = s_t - b - c, s_b - b - c
            gaps = [bot + c - x for x in sfb]
            if min(at, ab, *gaps) >= 0:
                vs.append(((at, b, c, ab), [err(at, w_a), err(ab, w_a), err(b, w_b), err(c, w_c)]
                           + [err(x, w_sfb) for x in gaps]))
    best = None
    for h, eh in hs:
        for v, ev in vs:
            e = eh + ev
            cross = (h[0] != v[0]) + (h[1] != v[1]) + (h[2] != v[2]) + (h[3] != v[2])
            key = (sum(x > NATIVE_G for x in e), cross, max(e), sum(x * x for x in e),
                   tuple(-x for x in h), tuple(-x for x in v))
            if best is None or key < best[0]:
                best = (key, h, v)
    return best[1], best[2]


def prefwin_layout(g: int) -> dict:
    """LAW (2026-10-25 wave-6 W6A v3, the user's mirror rule) -- every PrefWin frame placed by MIRRORING about its
    content, so each vanilla-mirrored channel pair stays equal.

    Fixed: the content (child windows, floor-scaled per arg -- PREF_* above) and the backdrop on its rails (L =
    rail_left_extent, R = fl(723g/16) - 1, T = 0, B = fl(390g/16) - 1, inclusive; pref_frame_draw_rect).  Between
    the backdrop's border (stroke K) and the content run two frames (inner, then a panel), so each side of each axis
    is a CHAIN of three channels -- backdrop -> inner (vanilla 3), inner -> panel (2), panel -> content (2) -- with a
    fixed budget S = (content edge - backdrop inner edge) - 2K:

        S_L = fl(33g/16) - rail_left_extent - 3K        S_R = fl(723g/16) - 3K - (fl(256g/16) + fl(457g/16))
        S_T = fl(10g/16) - 3K                           S_B = fl(390g/16) - 3K - (fl(360g/16) + fl(20g/16))

    pref_chain_split chooses the channels: two of each axis's three are mirrored (the same value on both sides) and
    the sides' difference (0..2 px, the floors' irreducible slack) goes to ONE place per axis:
      horizontal: the panel -> content channel of the panel on that side (left panel -> buttons vs right panel ->
        list: two different frames, no mirrored pair broken; each panel stays mirrored about its own content);
        the panel gap between them is what is left of the content gap;
      vertical: the backdrop -> inner channel at the BOTTOM (the two panels share T / B and so do their contents,
        so no non-mirrored spacing exists on this axis -- the slack lands on the outermost pair, next to the
        window's floored height).
    The values are the ones that leave the fewest spacings (channels, panel gap, slider-frame bottom gaps) more than
    1 px off vanilla x g/16, then the fewest broken cross-axis relations, then the smallest worst error
    (pref_chain_split).
    The slider frames (the audio page's, uimod.dll's Longevity frame) keep their top fl(t g/16) and span the page
    list's columns [fl(256g/16), fl(256g/16) + fl(457g/16)) -- the right panel is mirrored about that span, so panel
    -> frame L == R -- and their BOTTOM mirrors the top about the label column: bottom channel = fl((t + 3)g/16) -
    fl(t g/16) - K, below the last label row's fl(356g/16) + fl(20g/16).

    Returns the INCLUSIVE device rects the band-map renderers draw (key = PREF_FRAME_NATIVE's) and the channels.
    g <= 16: the native half-open rects (the primitive's own render; vanilla's channels 3 / 2 / 2 by construction)."""
    if g <= NATIVE_G:
        out = {k: v for k, v in PREF_FRAME_NATIVE.items()}
        out.update(K=1, a_h=3, b_h=2, c_lp=2, c_rp=2, a_t=3, a_b=3, b_v=2, c_v=2)
        return out
    f = lambda v: popup_scale_floor(v, g)                                     # noqa: E731
    k = stroke_width(g)
    bd = PREF_FRAME_NATIVE["backdrop"]
    bd_in = (rail_left_extent(g) + k, k, f(bd[2]) - k, f(bd[3]) - k)          # the backdrop border's inner edges
    btn_l, btn_r = f(PREF_BTN_X), f(PREF_BTN_X) + f(PREF_BTN_W)
    list_l = f(PREF_LIST_X)
    list_r = list_l + f(PREF_LIST_W)
    top, bot = f(PREF_CONTENT_TOP), f(PREF_CONTENT_LAST_Y) + f(PREF_ROW_H)
    (a_h, b_h, c_lp, c_rp), (a_t, b_v, c_v, a_b) = pref_chain_split(g)
    sf_b = {n: _pref_slider_frame_bottom(PREF_FRAME_NATIVE[n][1], g) for n in ("sframe", "dll")}
    # half-open [L, R) x [T, B), then inclusive for the band map
    in_ho = (bd_in[0] + a_h, bd_in[1] + a_t, bd_in[2] - a_h, bd_in[3] - a_b)
    pt, pb = in_ho[1] + k + b_v, in_ho[3] - k - b_v
    lp_ho = (in_ho[0] + k + b_h, pt, btn_r + c_lp + k, pb)
    rp_ho = (list_l - c_rp - k, pt, in_ho[2] - k - b_h, pb)
    out = {"inner": in_ho, "lpanel": lp_ho, "rpanel": rp_ho}
    for name in ("sframe", "dll"):
        out[name] = (list_l, f(PREF_FRAME_NATIVE[name][1]), list_r, sf_b[name])
    out = {n: bandmap_rect_from_halfopen(*r, g) for n, r in out.items()}
    out["backdrop"] = pref_backdrop_draw_rect(bd, g)
    out.update(K=k, a_h=a_h, b_h=b_h, c_lp=c_lp, c_rp=c_rp, a_t=a_t, a_b=a_b, b_v=b_v, c_v=c_v)
    return out


def pref_frame_draw_rect(site: int, rect: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-25 wave-6 W6A v2, F42) -- the device rect a PrefWin chrome site (PREF_FRAME_SITES, and uimod.dll's
    page frame) hands its band-map renderer, from the site's NATIVE half-open rect.

    A frame of PREF_FRAME_NATIVE (identified by its native rect: the sites and the DLL rebuild it from the statics per
    call) -> its prefwin_layout rect, mirrored about its content; the backdrop site 0x48FB19 (t_pref_bd) ->
    pref_backdrop_draw_rect of the rect it is handed (rail to rail).  Any other
    rect (and g > G_MAX, which the clamped lever never produces: t_pref_frame's table holds g 17..G_MAX) -> every
    edge fl(v g/16), then bandmap_rect_from_halfopen's R-1 / B-1 (the band map draws INCLUSIVE; the
    scaled half-open rect alone drew one device px past the native extent).  g <= 16: the native primitive's own
    half-open render of the native rect, unchanged."""
    if g <= NATIVE_G:
        return tuple(rect)
    rect = tuple(rect)
    if site == PREFWIN_BACKDROP_SITE:
        return pref_backdrop_draw_rect(rect, g)
    for name, native in PREF_FRAME_NATIVE.items():
        if name != "backdrop" and rect == native and g <= G_MAX:
            return prefwin_layout(g)[name]
    return bandmap_rect_from_halfopen(*(popup_scale_floor(v, g) for v in rect), g)


def pref_mode_cell_x(frame_x: int, frame_w: int, i: int, n: int = 3) -> int:
    """NATIVE x of cell `i` in the Longevity page's one-line display-mode row
    (Fullscreen / Borderless / Windowed; uimod prefs.cpp ModeCellX).

    The cells split the page's slider-frame span (g_prefwin_frame_x/_w,
    NATIVE units) by LAW 2 -- cum(), never i * (frame_w // n) -- and each
    cell is its own child window whose native x the baked GraphicWin_init
    gate scales ONCE (floor(x*g/16)). Device positions therefore descend from
    cumulative native positions: no per-cell pitch is ever scaled and
    multiplied, so the last cell cannot drift at g=22/25, and at g=16 the
    device x IS the native x.
    """
    return frame_x + cum(i, frame_w, n)


#: The left panel's CATEGORY column (PrefWin_build 0x48D9CC..0x48DD10 + uimod.dll's Longevity tab): FlatButton child
#: windows at native (PREF_BTN_X, PREF_CONTENT_TOP + PREF_TAB_PITCH * i, PREF_BTN_W, PREF_ROW_H), i = 0..5 the six stock
#: tabs, i = 6 the DLL's "Longevity Mod Preferences" (y0 + 0x84).  Vanilla's gaps are all 2 (pitch 22, face 20).
#: Gamma Correction is NOT a row of the column: the same x / w / h at y0 + 0x9A (row 7, no DLL) or y0 + 0xB0 (row 8,
#: the DLL's imm patch @0x48DD03); it keeps the plain floor, like Restore Defaults / OK / Cancel.
PREF_TAB_PITCH, PREF_TAB_ROWS = 22, 7


def pref_tab_pitch(g: int) -> int:
    """LAW (2026-10-27 wave-8 W8P, the user's decision) -- the category column's ONE device pitch.

    The rows are child windows floor-scaled per arg, so their tops fl((10 + 22 i) g/16) step by 27 / 28 px at g 20,
    30 / 31 at g 22: the gaps alternate (4,3,3,3,4,3 at 1920x1080) where vanilla's are all equal.  User decision: one
    uniform pitch, the first top and the face height unchanged, the slack into the space above Gamma Correction.

    The pitch is the repo's uniform-pitch law (option_row_gap; nutgrid_layout's P = min(half_down(p g, 16), avail //
    rows)): the PITCH obeys LAW 1, P = half_down(22 g, 16), and the gap is what the floored face leaves of it,
    P - fl(20 g/16).  The avail clamp never binds here (the column ends at most 2 px below its floor position and the
    gap above Gamma is 24 native; tests/test_scaling_prefwin_tabs.py proves it for every g), so it is not carried.
    g <= 16: vanilla's 22."""
    if g <= NATIVE_G:
        return PREF_TAB_PITCH
    return half_down(PREF_TAB_PITCH * g, NATIVE_G)


def pref_tab_row(x: int, y: int, w: int, h: int, x0: int = PREF_BTN_X, y0: int = PREF_CONTENT_TOP,
                 w0: int = PREF_BTN_W, h0: int = PREF_ROW_H) -> Optional[int]:
    """The category-column row a PrefWin child's NATIVE GraphicWin_init args (x, y, w, h) describe, else None: x / w / h
    the column's (the engine statics 0x85788C / 0x857894 / 0x686B88), y = y0 + 22 i with 0 <= i < PREF_TAB_ROWS (y0 =
    0x857890).  Gamma (row 7 / 8), Restore Defaults / OK / Cancel (y 314 / 337 / 360) and every page widget miss."""
    if (x, w, h) != (x0, w0, h0):
        return None
    d = y - y0
    if d < 0 or d % PREF_TAB_PITCH or d // PREF_TAB_PITCH >= PREF_TAB_ROWS:
        return None
    return d // PREF_TAB_PITCH


def pref_child_y(x: int, y: int, w: int, h: int, g: int, y0: int = PREF_CONTENT_TOP, **statics) -> int:
    """LAW (W8P) -- the device y thunk_pref_gwinit's child arm hands GraphicWin_init for a PrefWin child (parent ==
    PrefWin, NATIVE args): a category row i (pref_tab_row) -> fl(y0 g/16) + i * pref_tab_pitch(g) (row 0 keeps its
    floor top, so the frame chain prefwin_layout -- which reads only fl(10g/16) -- is untouched); any other child ->
    fl(y g/16) as before.  g <= 16: y unchanged.  x / w / h keep their floors (fl(v g/16)): the face height is the
    same fl(20g/16) on every row."""
    if g <= NATIVE_G:
        return y
    i = pref_tab_row(x, y, w, h, y0=y0, **statics)
    if i is None:
        return popup_scale_floor(y, g)
    return popup_scale_floor(y0, g) + i * pref_tab_pitch(g)


def map_label_font_size(native: int, g: int, pct: int) -> int:
    """The map-label font size law (thunk_map_font; group map_label_fonts) —
    the on-map base-name/"(production)"/landmark label fonts with the
    user-facing "Longevity Mod Preferences" font-scale slider applied.

    The engine (MapWin_calculate_dimensions 0x462980) computes a zoom-derived
    NATIVE size, capped at 12; the slider percent pct in [0, 100] interpolates
    the SCALE FACTOR between pristine (16/16) and the full popup scale (g/16):

        f    = 16 + (g - 16) * pct // 100      (16ths; integer floor)
        size = native * f >> 4

    Endpoints are exact by construction:
      * pct = 100 -> f = g      -> native*g>>4  == popup_scale_floor(native, g)
                                  (bit-identical to the pre-slider bake)
      * pct = 0   -> f = 16     -> native (pristine), at EVERY g
      * g <= 16   -> native unconditionally (lo-res gate on g, never ScreenW)

    The interpolation lives in the FACTOR, not the output, so a coarse native
    size (1..12) cannot alias distinct pct values into a non-monotonic size.
    """
    if g <= 16:
        return native
    f = 16 + (g - 16) * pct // 100
    return (native * f) >> 4


def itemlist_box_width(xs_stored: int, measured_dev: int, trim: int, g: int) -> int:
    """LAW 1 on the mixed-space popup box width — the thunk_scale_boxw
    v4/v5 arm (v4: type-1 checkbox #itemlist, the Customize Game Rules
    over-widening fix; v5: also type-2 #listbox, the scenario #FACTION fix).

    BasePop's native law (decompile 0x603800 lines 102-136): box = tw + trim,
    tw = [+iv3+0x222c] ?: [+iv3+0x21fc]. Two facts make the type-1 case special:

    * [+0x21fc] (the stored #xs) was ALREADY multiplied ×3/2 by the ENGINE for
      any screen wider than 1023 (BasePop_start @0x601bf0 — byte-identical in
      un-PRACX'd vanilla; popup scripts are 800×600-baseline). xs is therefore
      the correct 1024-vanilla magnitude, still native-space.
    * [+0x222c] = max(xs, measured item width), where the items are measured
      with the dialog's CURRENT font — under our font scaling that term is
      already DEVICE-space. [+0x222c] is a MIXED-space max.

    v3 scaled tw wholesale ×g/16, double-scaling the text term: Customize Game
    Rules @4K = (890+22)*40>>4 = 2280 vs faithful 1705 (frida_boxw2.log
    2026-07-12; 1705 == drawn rows 1589 + insets 86+30, exact flush).

    The lawful form compares in ONE space:

        box = max(scale(xs), measured_dev) + scale(trim)

    == scale(max(xs, native_text) + trim) up to the floor, i.e. vanilla ×g/16.
    At g == 16 the identity is ALGEBRAIC: fonts are native there, so
    measured_dev == max(xs, native_text) == the engine's own tw. Floor idiom
    (popup_scale_floor), matching the baked v3 family this extends.

    xs_stored is itemlist_box_term_native's term (v7: vanilla's type-1 [+0x5c], not raw xs).

    Types 1, 2 AND 8 take this arm (all with d5c != 0 and no art; type 8 = the OptionList
    multi-column popup, e.g. the unit-stack picker, added v6 2026-10-11: its d5c = max(native xs, device
    column content) and v3 made a 16-unit stack 4077 px wide at 4K). Type 2 was
    assumed safe (d5c == 0 for #SELECTSERVICE, whose items attach AFTER
    BasePop_calc) — FALSIFIED 2026-07-12 by the scenario #FACTION popup: its
    items exist BEFORE the calc, so ListBox_calculate_dimensions has already
    run and thunk_lbcalc_minw has already made d5c DEVICE-space by
    construction (w5c = max(scale(xs), item_dev) = 1312 = 525*40>>4 @4K,
    frida_faction_scenario_crash.log:311); the v3 arm re-scaled it to 3280
    vs faithful 1312 (box near-full-screen, position clamped to x=0).
    Type -1 leaves [+0x222c] == 0 (v3's native-input law is correct there)
    and type 16 is governed by its own q16/fieldpads family (user-locked —
    do not touch) PLUS the t16_row_measure_width corollary below: type 16
    takes the v3 wholesale-×g/16 arm, whose native-input contract is enforced
    at the MEASURE (0x60D5CE measures with the native font at every g), not
    in the thunk.
    """
    if g <= NATIVE_G:
        return (measured_dev if measured_dev else xs_stored) + trim
    return max(popup_scale_floor(xs_stored, g), measured_dev) + popup_scale_floor(trim, g)


def itemlist_box_term_native(dlg_type: int, xs: int, margin: int, gap_field: int, flags: int, fixed_h: int,
                             g: int) -> int:
    """The NATIVE term the mixed-space arm of thunk_scale_boxw (v7) scales: itemlist_box_width's xs_stored.

    Type 1 (the checkbox list): VANILLA's [+0x5c], re-formed from the native inputs exactly as
    thunk_list_fill_width re-forms the list window (type1_list_fill_width) -- xs-dominant:
        fixed (flags & 2 and xs)   xs
        else                       xs + 2m - gap,   gap = dialog_row_margin_native(field)
    Vanilla builds the box from the SAME [+0x5c] as the list window (BasePop_calculate_dimensions
    0x603BE0..0x603C19: box = [+0x5c] + trim), so the box content and the list are one width at every g.
    v4..v6 scaled xs itself: the box content was s(660) around a list of s(657) (fix 14) -- the row bars
    stopped s(660) - s(657) short of the box on the right only (8 px at 4K).

    Types 2 and 8 (ListBox / OptionList) keep xs: their [+0x5c] is not the type-1 formula.
    """
    if dlg_type != 1 or (flags & 2 and xs):
        return xs
    rowgap_path = not (flags & 1) or fixed_h == 0
    return xs + 2 * margin - dialog_row_margin_native(gap_field, g, rowgap_path)


def t16_row_measure_width(xs_clamped: int, w_measured_native: int, f_margin: int,
                          g: int) -> int:
    """LAW — the type-16 dialog row-width term (Dialog_type16_calc_dimensions
    0x60D380) and why its string measure MUST be native at every g
    (thunk_t16_measure_native at call site 0x60D5CE, a standalone site (no group)).

    The engine (0x60D5CE loop + 0x60D618..0x60D6EC, cols=1, icon=0, P=0):

        d5c = max(xs_clamped, W + F) - F        # W = max Buffer_text_width
        box_row = d5c * g >> 4                  # thunk_scale_boxw v3 arm

    where xs_clamped is NATIVE (the wrapper's art-arm min(tw+art_w, 658) —
    the pinned minw_baseline_clamp) and W is measured with the dialog font.
    Under our font scaling the dialog font is DEVICE at g>16, so W entered
    the max in device space: whenever the measured rows beat the native term
    (rows ≳ xs_clamped native px — the council "Select a motion" two-column
    '|' rows), the max returned a device value and the v3 arm scaled it AGAIN.

    Council propose popup, runtime-pinned (frida_council_width.log +
    frida_council_confirm.log): d5c native = 658-3 = 655 → lawful box_row
    655@g16 / fl(655*25/16)=1023@g25 / fl(655*40/16)=1637@g40. The defect
    form measured W=812 device at g40 → d5c=812 → 2030 (+margins 82+167 =
    box 2279 vs lawful 1886). At g25 the native branch still won the max
    (W25 < 655), so the defect was INVISIBLE at 1600×1200 — never validate
    this class below the g where the measured branch flips.

    The fix measures W with the NATIVE font (global [0x9403D8], the
    find_font(16,0) the popups_normal rewire left untouched) and lets the v3
    arm apply the single ×g/16. Descale-then-rescale of the device measure is
    UNSOUND: the inflated value must never enter the engine max at all.
    At g <= 16 the helper tail-jumps the real Buffer_text_width (byte-path
    identity).
    """
    if g <= NATIVE_G:
        # native font == dialog font: the engine's own arithmetic, one space
        return max(xs_clamped, w_measured_native + f_margin) - f_margin
    d5c = max(xs_clamped, w_measured_native + f_margin) - f_margin
    return popup_scale_floor(d5c, g)


def type4_dialog_width(min_w: int, item_w: int, g: int, fixed: bool = False) -> int:
    """LAW - width of the type-4 (text-entry) dialog window, the w argument
    Dialog_type4_attach 0x611B84 hands GraphicWin_init (thunk_t4_winw).

    Vanilla (Dialog_type4_calc_dimensions 0x6123D1): item_w [+0x5c] =
    max(min_w [+0x2c], content) with min_w the popup's native #xs and content
    = label + edit text measured with the dialog font. Under our font scaling
    content is DEVICE while min_w stays native (a shared source: box width,
    wrap budget), so the window - and with it the EditLine's black field,
    whose right edge is column width + [+0x34] - kept its native pixel width
    at every g (label + field ~666 px @g16/25/40, field 612 / 582 / 546;
    shots 20261004-011211 / -013435 / -013401). One space:

        w = max(floor(min_w * g/16), item_w)

    Pristine NameBase.png: field right = dialog left + xs. g<=16 -> item_w.
    `fixed` (flags [+0x20] & 2, anchored popups: [+0x2c] is the host's own
    device width) passes through."""
    if g <= NATIVE_G or fixed:
        return item_w
    return max(popup_scale_floor(min_w, g), item_w)


def type4_column_width(min_w: int, col_w: int, columns: int, g: int,
                       fixed: bool = False) -> int:
    """Column width of the same dialog (thunk_t4_colw, reads at 0x611C95 /
    0x611CF5): col_w [+0x64] = item_w / columns, so the scaled form is
    max(col_w, floor(min_w * g/16) / columns) == type4_dialog_width / columns
    (truncating division, as the engine's idiv)."""
    if g <= NATIVE_G or fixed:
        return col_w
    return max(col_w, int(popup_scale_floor(min_w, g) / columns))


def itemlist_container_edge_l(title_outer_l: int, g: int) -> int:
    """LAW 5 — the CONTAINER ring's left edge, derived from the title stash
    (thunk_pf_union_align container arm: type-1 checkbox #itemlist since v4,
    PLUS type-2 #listbox since v6 — the scenario #FACTION pristine-1024
    measure shows the same relation, ring x=514 == title inner EXACT; the
    quit-law fallthrough drew it title-OUTER-flush = the too-wide channel —
    PLUS type-4 text-entry since v7: the base-name FIELD ring, pristine-1024
    NameBase.png measure left == title inner native 268 EXACT / right =
    inner-2, the same relation and the same shipped symmetric form; the
    fallthrough drew it on the title OUTER column, the 2026-07-16 report.
    Types 1/2/4 all share the title-INNER container relation; only the
    quit/type-16 family is outer-flush).

    Vanilla, measured from the ENGINE (pristine-4K frida_namewidth2.log
    2026-07-12, Customize Game Rules, boxw=679): title outer d5a0 = 4..675,
    title inner d618 = 7..672 (channel = pad(3)), container ring = 7..670.
    The container's LEFT is FLUSH with the title's INNER stroke; its RIGHT is
    inner − 2. This is a DIFFERENT vanilla outcome than the Quit family
    (body ring flush with the title's OUTER stroke, pristine R=696==696):
    one engine formula, different inputs per dialog type — so the pf-align
    override must carry a per-family arm, not one global relation.

    Derivation from the SAME quantities the title pair uses (the baked title
    chrome keeps channel == pad(3), the 2026-07-09 fix):

        container.l = title_outer_l + pad(3)     == the drawn d618 inner edge

    so flushness at every g is ALGEBRAIC, immune to independent floor-lag.
    Identity at g=16: 4 + 3 = 7 == the measured vanilla rect.
    """
    return title_outer_l + popup_pad(3, g)


def itemlist_container_edge_r(title_outer_r: int, g: int) -> int:
    """LAW 5 — the type-1 container ring's right edge (see the _l docstring).

        container.r = title_outer_r − pad(3)     == the drawn d618 inner edge

    Symmetric with _l: BOTH container edges are collinear with the title's
    inner ring at every g (the user's spec, taken literally).

    v4 shipped `− pad(3) − floor(2g/16)`, scaling vanilla's −2 offset (native
    rect 670 at boxw 679). v5 dropped it as a "vanilla bug" (rows under the
    stroke at 1024, shot 20260712-120835) -- RETRACTED by fix 16 (2026-10-18):
    that collision was OUR list-width override firing at g=16 (the committed
    thunk_list_fill_width / its Frida prototype, ScreenWidth>0x3FF gate: row
    window 660 = s(xs) instead of vanilla's 657, bars [10, 670) under the
    stroke column 669).  Pristine is 2 px clear: the bytes keep the rows two
    columns off the stroke in every layout (bars [10, 667), ring [7, 670);
    see itemlist_ring_hug).

    Since fix 16 this arm serves the type-2 listbox and the type-4 field
    ring only; the TYPE-1 checkbox ring hugs its list (itemlist_ring_hug).
    Since F34 (v18) the flat / slide type-2 listbox hugs too
    (listbox_ring_takes_hug_arm): the type-4 field ring only.
    """
    return title_outer_r - popup_pad(3, g)


def itemlist_ring_takes_hug_arm(dlg_type: int, body_h: int, art: int) -> bool:
    """LAW 5b gate (thunk_pf_union_align v15) - a TYPE-1 checkbox list with no
    body text box and no art: the engine's ring is the dialog rect D -+ 3
    (0x406205 path: D.l = the list x, D.r = D.l + [+0x5c]), whatever the popup
    family (flat 0, slide 5, ornate 2/6 -- the D path at 0x406183..0x4061AD
    does not read [+0x30ac]).  Body text -> the UnionRect path (v11, title
    OUTER column); art -> the quit family; both unchanged.

    D.r at draw time is calc_reserve's width, not the list's: the ring is
    first drawn at BasePop_exec_3 0x602B49 (BasePop_on_redraw ->
    Popup_on_draw_background), BEFORE Dialog_set_type attaches the list at
    0x602BFE, where thunk_list_fill_width writes [+0x5c] = the list width.  At
    g = 16 the two agree (vanilla); at g > 16 the calc's [+0x5c] is the
    measured device text, so the hug takes its right edge from the list law
    (itemlist_ring_list_r), never from D.r."""
    return dlg_type == 1 and not art and body_h == 0


def listbox_ring_takes_hug_arm(dlg_type: int, body_h: int, art: int, raw_30ac: int) -> bool:
    """LAW 5d gate (F34, thunk_pf_union_align v18) - a TYPE-2 #listbox popup of the FLAT (0) or SLIDE (5) family
    with no body text box and no art hugs its list on all four sides, like the type-1 ring (itemlist_ring_hug).

    Vanilla (pristine .bak, Go To / SELECT DESTINATION, 1024x768, real-image Unicorn): the ring is the engine's
    dialog rect D -+ 3 (the 0x406205 path, the same as type 1): list window [33, 753) x [38, 263), ring strokes
    cols 30 / 755 and rows 35 / 265 -- 3 / 3 / 3 / 3 to the list, channel 2 | 2.  It is NOT the title's inner
    column: vanilla's list sits 9 | 11 inside the frame strokes (23 / 764), so its ring R is 2 px inside the title
    inner (757).  v7..v17 drew the type-2 ring on the title inner (itemlist_container_edge_l/r), so at g > 16 the
    ring was centred on the frame while the rows kept vanilla's left bias: 4K ring -> list 6 | 9 (T 3, B 4),
    1080 4 | 5 (user shots 20261024-233521 / -233621).

    D at the draw IS the list window, unlike type 1: the type-2 calc (BasePop_calc's ListBox calc, pass 1) writes
    Dialog[+0x5c] = the list width before the first draw (BasePop_exec_3 0x602B49), and the attach (0x602BFE)
    builds the window from that same [+0x5c] -- measured equal at every g in 16..40 (Go To, EDITORUNIT).  So the
    hug takes D's four edges as they are (no itemlist_ring_list_r term).

    The ORNATE family (2 / 6: EDITORWHO / SELECT A FACTION, the stack picker, the editor unit list) keeps fix 26's
    picker arm (ornate_picker_container_edge_r: flush with the title inner on both sides, ring -> rows equal --
    user-verified); body text -> the UnionRect path (v11); art -> the quit family."""
    return dlg_type == 2 and not art and body_h == 0 and popup_frame_rewrite_applies(raw_30ac)


def itemlist_ring_list_r(d_l: int, d_r: int, xs: int, margin: int, cols: int, gap_field: int, flags: int,
                         fixed_h: int, rows: int, g: int) -> int:
    """LAW 5c (thunk_pf_union_align v17, fix 18) - the RIGHT edge (half-open) of the list window the type-1 ring
    hugs, as the draw at BasePop_exec_3 0x602B49 must compute it.

    That draw precedes the attach (0x602BFE), so the engine's D.r = D.l + Dialog[+0x5c] is still
    OptionList_calc_reserve's measured width -- at g > 16 the device-font text (4K Customize Game Rules: 890 where
    the list is 1642, ring R 3052 vs the list's 3798, user shot 20261022-204738).  The list window the attach
    then builds is type1_list_fill_width's w (> 1 row) or the calc's own [+0x5c] (a single row, g <= 16), so:

        r = D.l + type1_list_fill_width(...).w      g > 16 and rows > 1
        r = D.r                                      otherwise (the attach leaves [+0x5c] as measured)

    The SAME law and the SAME gates as the attach; the bytes share its arithmetic (t_t1_list_w, called by
    thunk_list_fill_width v4 and, through t_boxw_t1_term v2, by the ring).  The attach's DiploEditWin owned arm
    (owned=True) cannot reach a popup's ring: its parent is the editor's own stack window (vtbl 0x66E964,
    vtbl+0x180 = 0x4E3300, not Popup_on_draw_background), and a popup's list parent is its [+0xa3c] (itself, or
    BasePop_start's parent arg; no DiploEditWin code passes one).  Domain: type1_list_fill_width's
    (xs-dominant lists, type1_list_xs_dominant; every census popup list)."""
    w = type1_list_fill_width(xs, margin, cols, gap_field, flags, fixed_h, rows, g)
    return d_r if w is None else d_l + w[0]


def itemlist_ring_hug(list_l: int, list_t: int, list_r: int, list_b: int,
                      g: int) -> Tuple[int, int, int, int]:
    """LAW 5b - the TYPE-1 checkbox ring HUGS its list on ALL FOUR sides (user
    decision 2026-10-18 "Hug the list": fix 16 left/right, fix 17 top/bottom):
    Customize Game Rules (#RULES, main menu and scenario editor),
    Announcements (#BASEWARNINGS), Governor Settings (#GOVOPTIONS),
    #SCENRULES, #SCENVICTORY, #ASSEMBLEGROUP, #AIEDITOR/2, #EDITVEH, and
    Thinker's #OPTIONS (modmenu.txt; X_pop_9("modmenu", "OPTIONS", ...,
    PopDialogCheckbox|PopDialogBtnCancel)).  The census is NOT fully provable
    from the bytes: X_pop callers that pass the dialog flags in a register
    (not an immediate) cannot be enumerated statically.  The arm is gated on
    the popup's SHAPE (itemlist_ring_takes_hug_arm), not on a tag list, so an
    unlisted type-1 list hugs too.

    Vanilla (pristine .bak, every layout at g = 16, Unicorn chain
    test_scaling_type1_box_fill): the ring is the engine's dialog rect D -+ 3
    on every side (0x406205 path: D = [ebp-0x44] l = the list x, [ebp-0x40]
    t = the y cursor, [ebp-0x3c] r = l + [+0x5c], [ebp-0x38] b = t + the
    dialog height; built at 0x40619D..0x4061AD) -- bars [10, 667), ring
    [7, 670) at boxw 679: 3 / 3 / 3 / 3 (stroke col 7 / 669, channel 2 / 2).

    D.r is NOT the list's right edge at draw time.  The ring is first drawn at
    BasePop_exec_3 0x602B49 (BasePop_on_redraw -> Popup_on_draw_background),
    BEFORE Dialog_set_type attaches the list at 0x602BFE: D.r = D.l +
    calc_reserve's [+0x5c].  At g = 16 that equals the list window (vanilla);
    at g > 16 it is the measured device text, and thunk_list_fill_width only
    writes the list width into [+0x5c] at the attach.  So the arguments here
    are the LIST WINDOW (l, r: list x / x + w, r from itemlist_ring_list_r)
    and D's t / b -- never D.r (fixes 16/17 hugged D.r: 4K Customize Game
    Rules R 3052 where the rows end at 3798; fix 18).  So

        l = list_l - popup_pad(3, g)   t = D.t - popup_pad(3, g)
        r = list_r + popup_pad(3, g)   b = D.b + popup_pad(3, g)
                                       then bandmap_rect_from_halfopen

    Rounding that keeps T == B == L == R: ONE floored pad fl(3g/16) applied
    to D's OWN four edges (never two independently-scaled positions, never
    the title stash, whose L/R margins are vanilla's unequal 10/12 or 33/67,
    never nestpads' scale_px(2) local), and the far edges taken in by one
    because at g > 16 the ring draws through the band map (thunk_d5a0_center
    -> thunk_box_thick_hollow) with an INCLUSIVE footprint [l, r] x [t, b]
    (4K shot 20261017-114319: ring rect 17..1688 -> stroke cols 17-18 and
    1687-1688; the title pair the same), while the bars stay half-open (the
    row frame is clamped to the list window).  Drawn: strokes [l, l+K) /
    [r-K+1, r] / [t, t+K) / [b-K+1, b]; the drawn insets are (D.l - l) ==
    (r + 1 - D.r) == (D.t - t) == (b + 1 - D.b) == fl(3g/16) and the visible
    channels to D fl(3g/16) - K, equal.  g <= 16: the engine's own D -+ 3
    drawn half-open (identity: the vanilla ring).  Fix 16 kept t/b = the
    engine local, D -+ nestpads' scale_px(2) (nested_frame_pad): D-relative
    T = s(2), B = s(2) + 1 (the inclusive footprint) -- 5/6 at 4K, 2/3 at
    1600x900 (T under vanilla's native 3)."""
    p = 3 if g <= NATIVE_G else popup_pad(3, g)
    return bandmap_rect_from_halfopen(list_l - p, list_t - p, list_r + p, list_b + p, g)


def union_ring_takes_container_arm(dlg_type: int, body_h: int, art: int) -> bool:
    """LAW 5 gate (thunk_pf_union_align v11) - WHICH column the ring drawn at
    Popup_on_draw_background 0x406238 sits on, read from the engine
    (0x4060E7..0x406238), not from the dialog type alone.

    F = the body text field (d528): l = content_l - 3 == the title INNER
    column; D = the dialog rect, l = content_l. The ring is rect -+ 3 of:

        body_h == 0 (no text box)          D      -> l = content_l - 3 = INNER
        body_h != 0, dialog, no art        F u D  (0x4061B2 copies F's l/r
                                           into D, then UnionRect)
                                                  -> l = F.l - 3     = OUTER
        body_h != 0, no dialog or art      F      -> OUTER (quit family)

    So the title-inner CONTAINER relation holds only for a list/field popup
    with NO body text ([+0x30d4] == 0: Customize Game Rules, scenario
    #FACTION, #FIRSTBASE - the three popups it was measured on). With body
    text the ring nests the d528 text box, one pitch outside it, on the
    title OUTER column. v4-v10 keyed on dlg_type in {1,2,4} alone and drew
    that ring ON the text box (pristine BlindResearch.png #TECHRANDOM:
    ring box+4 / text box box+7 == the title pair; ours @4K both at +17,
    user shot 20261003-233707).

    Fix 16 (v15): of the shapes this admits, dlg_type 1 then takes the hug
    arm (itemlist_ring_takes_hug_arm / itemlist_ring_hug); F34 (v18): a flat /
    slide dlg_type 2 hugs too (listbox_ring_takes_hug_arm); 4 keeps the
    title-inner container edges.  The g<=16 native-fix arm v5-v14 carried
    (r = boxw - 7) is gone: g<=16 is the engine's own ring."""
    return dlg_type in (1, 2, 4) and not art and body_h == 0


def union_ring_top(local_t: int, g: int) -> int:
    """LAW - top of the UnionRect-path ring (body text box + dialog, no art).

    thunk_popup_nestpads gives that path the LIST pad nested_frame_pad(g) =
    scale_px(2) on all four edges, so the engine local is F.t - scale_px(2).
    The top (like the left and right) nests the d528 text-box STROKE, both
    drawn flat at their rect edge, so its pad is the stroke PITCH
    popup_pad(3) - the body-only convention; only the bottom nests the list.
    Measured before the fix @g40: pitch 5 on top (961 -> 966) against 7 on
    the title pair. Identity at g=16 (3 - 3)."""
    return local_t - (popup_pad(3, g) - nested_frame_pad(g))


# itemlist_container_native_fix_r (the v5-v14 g<=16 "boxw - 7" arm) was RETIRED by fix 16 (2026-10-18): the
# rows-under-the-stroke collision it repaired was our own thunk_list_fill_width firing at g=16 through a
# ScreenWidth>0x3FF gate (fix 10 re-gated it on g); pristine bytes are 3 / 3 in every layout, and the arm put the
# in-game ring R at boxw - 7 = 750 where vanilla draws 693 (console shown, 1024x768).  g<=16 is the engine's ring.


POPUP_BTN_ROW_H = 20   # [popup+0x30d0] at the clamp: 0x14 (vtbl+0x174 -> 0x40503F), or 0 with no button row


def ingame_popup_min_boxh(box_h: int, g: int, btn_h: int = POPUP_BTN_ROW_H,
                          own_window: bool = True) -> Tuple[int, int]:
    """LAW 1 on the in-game popup MINIMUM box height (the tail of
    Popup_calculate_dimensions @0x404EBD; thunk_popup_min_boxh).

    Vanilla: every in-game popup of the slide-rail "console monitor" family
    (mode 0/5, console strip visible, [+0xa14]==0) is clamped
    `if (box_h < 300) { footer_reserve[+0x30ec] += 300 - box_h;
    box_h[+0x30c0] = 300; }` right after BasePop_calculate_dimensions.
    Popup_show then bottom-anchors the window on the console strip
    (y = ScreenH - g_console_strip_height - h), so the clamp is what gives a
    short popup its tall mostly-empty body BELOW the content (pristine
    NameBase @1024: content ~= 136, box 300, top = 768-213-300 = 255) and,
    equally, its high on-screen placement.

    At g>16 the scaled content of a small popup exceeds the NATIVE 300, so
    the vanilla clamp went dead: the box hugged its content and, being
    bottom-anchored, sat far below vanilla's placement with no body reserve
    (2026-07-16 namebase report @4K: top 1279, box ~349; faithful top 878,
    window 750). The minimum scales like the rest of the popup family:

        M    = floor(300 * g/16)          (popup_scale_floor, the floor idiom)
        v1:  box' = max(box_h, M);  footer += box' - box_h   (superseded)

    g<=16 -> M=300, vanilla's own constant: the native no-op is algebraic
    (300*16>>4 == 300). Fires for ANY in-game popup whose scaled window is
    under M — exactly the popups vanilla clamps at native scale. Returns
    (box_h', footer_delta); the footer term keeps the button row directly
    under the content, as vanilla does.

    v2 (2026-10-03): M is the height of the WINDOW, and the window is not
    box_h. BasePop_exec_3 creates it box_h + D tall, D = the button-row
    growth thunk_grow_box adds at 0x602861 (popup_button_row_growth, read
    from the same [+0x30d0] this clamp sees). v1 clamped box_h to M, so every
    clamped popup came out M + D tall and, bottom-anchored, sat D too high
    with D extra body under OK (measured: Confirm Research Priorities and
    Chief Librarian @4K top 848 vs faithful 878 = 2160-532-750; Chief
    Librarian @1920x1080 top 369 vs 376). The clamp therefore targets

        box' = max(box_h, M - D)      ->  window = max(box_h + D, M)

    (ingame_popup_window_h). D = 0 at g<=16, so the native identity stands.

    v3: D is subtracted only for a popup that creates its OWN window
    ([+0xa3c] == popup). BasePop_start given a parent window stores it in
    [+0xa3c]; exec_3 0x60281E then skips the window creation and with it the
    0x602861 growth, so an embedded popup keeps the plain box' = max(box, M).
    """
    m = popup_scale_floor(300, g) if g > NATIVE_G else 300
    if own_window:
        m -= popup_button_row_growth(btn_h, g)
    if box_h < m:
        return m, m - box_h
    return box_h, 0


def popup_button_row_growth(btn_h: int, g: int) -> int:
    """What thunk_grow_box adds to the popup window height at BasePop_exec_3
    0x602861: floor(btn_h*g/16) - btn_h, btn_h = [popup+0x30d0] (20 native)."""
    if g <= NATIVE_G:
        return 0
    return popup_scale_floor(btn_h, g) - btn_h


def ingame_popup_window_h(box_h: int, g: int, btn_h: int = POPUP_BTN_ROW_H) -> int:
    """Created height of a clamp-family in-game popup that owns its window:
    the clamped box plus the button-row growth == max(box_h + D,
    floor(300*g/16))."""
    box, _ = ingame_popup_min_boxh(box_h, g, btn_h, True)
    return box + popup_button_row_growth(btn_h, g)


def popup_button_row_bounds(total: int, n: int) -> List[int]:
    """LAW (fix 19) — the cell boundaries b(0..n) of a popup button row whose n buttons share `total` px (the row
    minus its n-1 gaps): b(k) = cum(k) for 2k <= n, total - cum(n-k) above.  The remainder distribution of
    [[feedback-remainder-distribution]] mirrored about the centre: b(0) = 0, b(n) = total, every cell within 1 px of
    total/n, and the widths are a palindrome whenever one exists (every odd n; an even n with an even remainder) --
    symmetry over 1-px exactness.  Odd n: identical to distribute()."""
    if n <= 0:
        raise ValueError("popup_button_row_bounds: n must be positive")
    return [cum(k, total, n) if 2 * k <= n else total - cum(n - k, total, n) for k in range(n + 1)]


def popup_button_row_slot(x: int, w: int, n: int, rem: int, gap: int, margin_r: int, g: int) -> Tuple[int, int]:
    """LAW (fix 19) — BaseButton_init's (x, w) for a button of BasePop_exec_3's bottom row.

    Vanilla (BasePop_calculate_dimensions 0x603FD5..0x604012): w = (box_w - 2*pad_x - (n-1)*gap) / n, the
    remainder `rem` dropped; exec_3 anchors the row on the RIGHT (x = -margin_r = [+0x30F4] for the last slot, each
    slot to its left (w + gap) further; a negative x is the button's right edge relative to the parent's right), so
    all of `rem` lands on the left: the row starts rem px inside the span the calc gave it (4K Rules +1, 1080p +2,
    1600x900 +1 against the list above it) and ends flush.

    g > 16: the row keeps its span [xl - T - (n-1)*gap, xl), T = n*w + rem, and its gaps; slot i (j = n-1-i from the
    right) is the cell [b(i), b(i+1)) of popup_button_row_bounds(T, n): x' = xl - T + b(i+1) - j*gap,
    w' = b(i+1) - b(i).  rem = 0 is the identity by construction.  g <= 16, a left-anchored row (x >= 0) or an x off
    the vanilla slot grid: vanilla's (x, w)."""
    xl = -margin_r
    stride = w + gap
    if g <= NATIVE_G or not 0 <= rem < n or x >= 0 or stride <= 0 or xl - x < 0 or (xl - x) % stride:
        return x, w
    j = (xl - x) // stride
    if j >= n:
        return x, w
    i = n - 1 - j
    total = n * w + rem
    b = popup_button_row_bounds(total, n)
    return xl - total + b[i + 1] - j * gap, b[i + 1] - b[i]


# ---------------------------------------------------------------------------
# BaseWin (base screen) true re-layout — option A, user-picked 2026-07-18 after
# the option-B composite look-prototype. Design: work\_tmp_basewin_relayout_design.md;
# ground truth: work\frida_basewin2.log + _tmp_disasm_basewin_init.txt.
# ---------------------------------------------------------------------------

BASEWIN_NATIVE_W = 758   # BaseWin_init 0041F4EE PUSH 0x2F6
BASEWIN_NATIVE_H = 490   # rcMapView.h 89 + 0x191 (0041EE8D ADD EAX,0x191)
BASEWIN_CENTER_C = 726   # 0041F4B6 LEA EAX,[EDX-0x2D6]; 726 = 758-32 -> the +16 nudge


def basewin_window_rect(screen_w: int, screen_h: int, strip_h: int,
                        g: int) -> Tuple[int, int, int, int]:
    """The BaseWin window law (GraphicWin_init entry-gate arm, ecx==BaseWin_g).

    Vanilla (BaseWin_init @0x41E8D0, !=800 branch): x = (SW - 726)/2 (the 726
    = 758-32 encodes the same +16 nudge as Popup_show), w = 758, h = 490
    (rcMapView.h 89 + 0x191), and the window bottom rests on the console
    strip: y = (SH - strip_h) - h. strip_h is the RUNTIME (already g-scaled)
    g_console_strip_height — a mixed-space input by design; only the vanilla
    constants scale (the PrefWin native-expression pattern):

        w = floor(758*g/16), h = floor(490*g/16)
        x = (SW - floor(726*g/16)) // 2
        y = (SH - strip_h) - h

    g<=16 no-op is algebraic (758*16>>4 == 758 etc.). Pinned against traces:
    g=16 1024x768 strip 213 -> (149, 65, 758, 490)   [= pristine r1 149,65,907,555]
    g=40 4K strip 532       -> (1012, 403, 1895, 1225) [= proto rewrite values]
    The ==800 vanilla seed branch is g=16-only -> no-op by the same gate.
    """
    gg = g if g > NATIVE_G else NATIVE_G
    w = popup_scale_floor(BASEWIN_NATIVE_W, gg)
    h = popup_scale_floor(BASEWIN_NATIVE_H, gg)
    x = (screen_w - popup_scale_floor(BASEWIN_CENTER_C, gg)) // 2
    y = (screen_h - strip_h) - h
    return x, y, w, h


FILEDLG_INGAME_W = 0x18A     # FileDlg_layout in-game (map visible) window w = 0x14e + 0x3c
FILEDLG_INGAME_H = 0x191     # ... h = 0x177 + 0x1a
FILEDLG_MENU_W = 0x14E       # main-menu path
FILEDLG_MENU_H = 0x189


def filedlg_native_origin(screen_w: int, screen_h: int, strip_h: int,
                          in_game: bool) -> Tuple[int, int, int, int]:
    """Vanilla FileDlg_layout window args (0x407453..0x4074ef), strip_h =
    g_console_strip_height as the engine reads it on BOTH paths (213 at g <= 16,
    fl(213g/16) after hud_seedscale -- set before top_menu, so the main menu
    reads it too): in-game x = (SW-0x13c)/2 - 0x17, y = SH - strip - 0x191;
    main menu x = (SW-0x13c)/2, y = SH - strip - 0x192 (1024x768: (354, 153))."""
    x = int((screen_w - 0x13C) / 2)          # cdq; sub; sar = truncate toward 0
    if in_game:
        return x - 0x17, screen_h - strip_h - 0x191, FILEDLG_INGAME_W, FILEDLG_INGAME_H
    return x, screen_h - strip_h - 0x192, FILEDLG_MENU_W, FILEDLG_MENU_H


def filedlg_window_origin(screen_w: int, screen_h: int, strip_h: int,
                          x: int, y: int, w: int, h: int,
                          g: int) -> Tuple[int, int, int, int]:
    """The file-picker window law (thunk_filedlg_graphicwin v3, call-redirect
    @0x4074f1), given vanilla's own args (x, y, w, h) at this resolution.

    Vanilla anchors the window on the console top T = SH - strip_h and on
    c = SW>>1 on BOTH paths (filedlg_native_origin): in game its BOTTOM rests
    on T (T - y == h) and its visible part (the window minus the 32px right
    scrollbar gap) is centred on c; at the main menu it sits 9 above T with
    its centre 9 right of c.  Both offsets scale:

        w' = s(w), h' = s(h)
        x' = c - s(c - x)
        y' = T - s(T - y)        (in game == T - h': the bottom stays on the console top)

    strip_h is the engine's g_console_strip_height on both paths: its one
    writer, MainWin_build's literal 0xD5 (0x459726), runs from system_init
    before top_menu, and thunk_hud_seedscale makes it fl(213g/16) in the same
    build, so the MAIN MENU sees it too (1366x768 shot 20261022-210249: the
    window at y = 768 - 213 - 0x192 = 153).
    v1 screen-centred the window: below 4K the scaled window then reached
    past the scaled console top and the HUD hid the OK/CANCEL row.  v2 kept
    the main menu screen-centred on the belief that the strip was 0 there:
    4K (1502, 589) where vanilla x g/16 is (1525, 623).  v3 (fix 19) anchors
    both paths.
    Gate is g > 16 (the lo-res gate): g <= 16 returns vanilla's own args at
    ANY screen width.  Until fix 10 the gate was SW > 1024 (v1's), and the
    then-screen-centred main-menu arm moved every 1280..1366-wide g=16 screen
    off vanilla's bottom anchor (1280x768: (473, 187) vs vanilla (482, 153)).
    """
    if g <= NATIVE_G:
        return x, y, w, h
    s = lambda v: popup_scale_floor(v, g)   # noqa: E731  asm: imul; sar 4
    c = screen_w >> 1
    top = screen_h - strip_h
    return c - s(c - x), top - s(top - y), s(w), s(h)


BASEWIN_FRAME_INSET_L = 23   # 0041F51A ADD EAX,0x17 — left frame inset (= the slide_show margin-clear width)
BASEWIN_FRAME_INSET_R = 55   # 0041F529 SUB ECX,0x37 — right frame inset (= the rail anchor offset 0x20+15+8)
BASEWIN_FRAME_OVER_B = 3     # 0041F532 ADD EDX,3    — bottom edge pushed off-canvas (vanilla look)


def basewin_console_frame_rect(g: int) -> Tuple[int, int, int, int]:
    """BaseWin OUTER console-frame rect law, v2 (BaseWin_init box_sprite
    @0x41F53E, sprite set 0x78d690 — thunk_bw_boxsprite_console).

    Vanilla builds this ONE rect from the canvas BOUNDS [0,0,W,H] plus native
    insets: [0+23, 0, W-55, H+3]. The bounds are DEVICE space (slice-1 scales
    the canvas), the insets are NATIVE — a mixed-space input. Blind rect
    x g/16 (the generic thunk_bw_boxsprite consumer law, correct for the
    native-space locals every other redirected site passes) double-scales the
    right edge (1840 -> 4600, clipped at the canvas edge) so the frame's
    198-scanline interior floods the margin strip vanilla leaves key-9
    TRANSPARENT — the 4K black bar right of the console rails
    (frida_basewin9/10, 2026-07-21).

    Because W = fl(758g/16) and H = fl(490g/16) by the slice-1 window law,
    the vanilla mixed-space expression resolves to CONSTANTS [23,0,703,493]
    — so the law is simply the interior consumer-boundary law basewin_pt on
    each edge:

        (pt(23), 0, pt(703), pt(493))

    v1 anchored right = W - fl(55g/16), which lands 1 ABOVE pt(703) whenever
    fl(758g)+... floor-lag composes (1758 vs 1757 at g=40) — and the rails
    re-anchor and draw AFTER the frame, so they overlaid the frame's right
    stroke (the 2026-07-21 "frame stroke cut off by the rail art" report).

    v2 pinned right = pt(703), claiming that equals the rail anchor "by the
    IDENTICAL formula". It does NOT: the rails re-anchor through
    rail_right_anchor's DOUBLE FLOOR — native' = fl(W_dev*16/g) - 55, then
    the engine's Sprite_draw_2 floors again, device = fl(native'*g/16).
    Whenever 758*g/16 is fractional the descale loses a native pixel
    (fl(1184*16/25) = 757, not 758), so at g=25 the rails land at 1096 while
    pt(703) = 1098 — the rails ate the whole K-wide stroke (the 2026-07-21
    1600x1200 "frame stroke cut off on the right" report). g=22 misses by 1
    the same way. Only exact multiples (g=40) coincide, which is why 4K
    looked flush.

    v3: right = the rails' OWN double-floor anchor,

        fl((fl(W_dev*16/g) - 55) * g/16),   W_dev = fl(758*g/16)

    — the filedlg railscale precedent (match the neighbor's own floor
    cascade, never a parallel formula; see thunk_popup_d690insets which
    replicates the identical double floor for the popup backdrops). Bit-
    identical at g=40 (1757), flush at EVERY g by construction. Identity at
    g<=16 (the vanilla [23, 0, 703, 493]); bottom pt(493) stays past the
    canvas H = pt(490) (off-canvas bottom edge, the vanilla look).

    v4 (2026-10-25 W5A, the base-screen mirror law): the rect is the RAILS'
    OWN span, drawn inclusive by the devfill / hollow_flat band renderers:

        (Lx, 0, A - 1, pt(493)),  Lx = basewin_rail_left_extent(g), A = basewin_rail_anchor(g)

    v3 handed the inclusive renderer the rails' anchor A itself, so the right
    stroke's outer column sat ON the right rail's first column and the rails
    (drawn after, by slide_show) ate it: the visible right border was K - 1
    (none at g 17..24 = 1080, 1 px of 2 at 4K) where vanilla draws [23, 703)
    half-open (stroke col 702, rails from 703) -- MEASURED on the pristine
    image (the box_sprite footprint is 23..702).  And v3's left pt(23) sits 1
    px right of the left rails' composed extent fl(15g/16) + fl(8g/16) at odd
    g 17 / 19 / 21 / 23 / 33 / 35 / 37 / 39: a key-9 (see-through) column
    between the left rail and the console stroke.  v4 spans exactly the gap
    the rails leave, so both strokes are K wide and abut a rail, and the
    frame is mirror-symmetric about the rail axis by construction (first +
    last column = A + Lx - 1 = basewin_rail_axis_sum - 1).  W5A v2: A is the
    BaseWin's own rail anchor A* = pt(726) - Lx (basewin_rail_anchor), so 4K
    is (57, 0, 1757, 1232) with the rail at 1758.  At g = 17
    railscale's own arm B did not arm (canvas 520 rows < the 529-row art:
    native rails at W - 55) -- v3 left a 4 px see-through gap 746..749 there
    (measured); t_bw_railscale arms the BaseWin at every g > 16.
    """
    if g <= NATIVE_G:
        return (BASEWIN_FRAME_INSET_L, 0,
                BASEWIN_NATIVE_W - BASEWIN_FRAME_INSET_R,
                BASEWIN_NATIVE_H + BASEWIN_FRAME_OVER_B)
    return (basewin_rail_left_extent(g), 0, basewin_rail_anchor(g) - 1,
            basewin_pt(BASEWIN_NATIVE_H + BASEWIN_FRAME_OVER_B, g))


def basewin_rail_left_extent(g: int) -> int:
    """Device columns the base screen's two LEFT rail strips cover: outer fl(15g/16) then inner fl(8g/16) at
    x = fl(15g/16) (railscale's left arm, unchanged).  t_bw_railscale arms for the BaseWin canvas at EVERY g > 16
    (railscale's own arm B skipped g = 17, where the 520-row canvas is shorter than the 529-row art: native rails,
    measured).  g<=16: the native 15 + 8 = 23."""
    return rail_left_extent(g) if g > NATIVE_G else sum(SE_RAIL_LEFT_STRIPS)


def basewin_rail_anchor(g: int) -> int:
    """Window-local device x of the base screen's RIGHT inner rail strip (W5A v2, design (c)): the mirror of the left
    rails' end through the CONTENT axis pt(726),

        A* = pt(726) - Lx,   Lx = basewin_rail_left_extent(g)

    so the right rails [A*, pt(726)) mirror the left rails [0, Lx) exactly and S = pt(726).  v1 (and every other
    slide window) keeps railscale's double floor fl((fl(W*16/g) - 55) * g/16) over the canvas width W =
    fl(758g/16): it loses a native px whenever 758g/16 is fractional, so those rails lagged the content by 1..4 px
    and v1's mirror pulled the right column / GOVERNOR up to 3.9 px off vanilla x g/16 (audit-w5A).  Only the
    BaseWin canvas takes A* (t_bw_railscale on the 4 settled slide_show sites, t_bw_railanchor inside
    thunk_filedlg_railslide's animation frames; the production picker draws no rails over the base screen and keeps
    railscale's anchor when it slides alone -- audit-w5A v2); the move is +0..+4 px (-2 at g = 17, where the rails were native)
    and the right rails still end 32 g/16 px inside the canvas.  g<=16: vanilla 703."""
    if g <= NATIVE_G:
        return BASEWIN_NATIVE_W - BASEWIN_FRAME_INSET_R
    return basewin_pt(BASEWIN_TAB_SUM, g) - basewin_rail_left_extent(g)


def basewin_rail_strip_x(buf_w: int, x_arg: int, g: int) -> int:
    """Window-local device x of a BaseWin slide-rail strip (settled: t_bw_railscale; animation: L + this, through
    thunk_filedlg_railslide + t_bw_railanchor).  slide_show's args are 0 / 15 / buf_w - 55 / buf_w - 47 (buf_w = the
    canvas width, device at g > 16): a LEFT strip (2x < buf_w) at fl(x*g/16), as railscale; a RIGHT strip at
    A* + fl((x - (buf_w - 0x37))*g/16) -- the inner one at A*, the outer one directly against it (railscale v3's
    abutment).  g<=16: the arg itself (Sprite_draw_2 1/1)."""
    if g <= NATIVE_G:
        return x_arg
    if 2 * x_arg < buf_w:
        return (x_arg * g) >> 4
    return basewin_rail_anchor(g) + (((x_arg - (buf_w - RAIL_INNER_RIGHT_OFF)) * g) >> 4)


def basewin_rail_axis_sum(g: int) -> int:
    """THE base-screen mirror axis, as an edge sum S (mirror of an exclusive edge x = S - x; of an inclusive column
    c = S - 1 - c): the rails' own span, left rails [0, Lx) + right rails from A,  S = A + Lx.  Since W5A v2 the
    right rails sit on A* = pt(726) - Lx, so S = pt(726): the content axis, the one basewin_pt already places the
    left half on.  Vanilla's centre is mirror-symmetric about x = 363 (S = 726): rails 0..22 | 703..725, console
    23..702, left column 27..162 | right column 563..698, the tab row.  Every right-side edge that must mirror a
    left-side one -- the console's right stroke, the right column's rims, the tab frame and the right half of the
    tab row -- is placed through this sum.  g<=16: 726."""
    if g <= NATIVE_G:
        return BASEWIN_TAB_SUM
    return basewin_rail_anchor(g) + basewin_rail_left_extent(g)


BASEWIN_RIM_LO = 690   # native RIGHT edges in [690, 699] are the right column's rims: 699 (the right panel, the
BASEWIN_RIM_HI = 699   # intake / energy rows, the tab frame), 697 / 696 (their inner boxes, CONQUER, text rects),
                       # 693 (the facilities header text, the list scrollbar, the facilities button).  Measured on the
                       # pristine image (every centre primitive call, BaseWin_init + the 9 centre painters): no other
                       # right edge lies in 560..702, no left edge >= 600.


def basewin_is_rim(r: int) -> bool:
    return BASEWIN_RIM_LO <= r <= BASEWIN_RIM_HI


def basewin_rim_x(r: int, g: int) -> int:
    """A native EXCLUSIVE right edge r -> device (text rects, child windows, the scrollbar rect).

    A rim edge mirrors its left twin's edge through the rail axis: x = S - pt(726 - r).  Any other edge is the plain
    interior law pt(r).  So the right column's channel to the console stroke is the left column's channel (and every
    concentric channel inside it pairs with its left twin) at every g -- the 2026-10-25 1600x1200 console->panel
    5 | 2 and 1080 5 | 3.  With S = pt(726) (W5A v2) the rim is within 1 px of pt(r).  g<=16: r (the native no-op)."""
    if g <= NATIVE_G:
        return r
    if not basewin_is_rim(r):
        return basewin_pt(r, g)
    return basewin_rail_axis_sum(g) - basewin_pt(BASEWIN_TAB_SUM - r, g)


def basewin_rim_box_r(r: int, g: int) -> int:
    """The LAST COLUMN a centre box with native (half-open) right edge r is drawn to: basewin_rim_x(r) - 1 -- a rim
    edge's last column is the exact column mirror of the twin's first column, S - 1 - pt(726 - r), any other edge's is
    pt(r) - 1 (W5A v4, F42: every centre box is drawn half-open; v3 drew a non-rim edge inclusive on pt(r), +1 px).
    g<=16: r (the native rect, which the engine draws half-open itself)."""
    if g <= NATIVE_G:
        return r
    return basewin_rim_x(r, g) - 1


def basewin_child_x(x: int, w: int, g: int) -> int:
    """thunk_basewin_gwinit's generic child x.  A rim child in the right column (x >= 563, x + w a rim: the
    facilities BaseButton 569 + 124) takes the axis mirror S - pt(726 - x) on its left edge too, like every other
    right-column left edge (W5A v3: with a plain pt(569) left and a mirrored right its width ran +1.5 px over
    124 g/16 at 2560x1440; mirrored, within 0.75 at every g).  Every other child: pt(x).  g<=16: x."""
    if g <= NATIVE_G:
        return x
    if basewin_is_rim(x + w) and x >= BASEWIN_RCOL_L:
        return basewin_rail_axis_sum(g) - basewin_pt(BASEWIN_TAB_SUM - x, g)
    return basewin_pt(x, g)


def basewin_child_w(x: int, w: int, g: int) -> int:
    """thunk_basewin_gwinit's generic child width.  A child whose native right edge x + w is a rim (the facilities
    BaseButton 569 + 124 = 693) ends on basewin_rim_x, inside the mirrored list box: w = rim_x(x + w) -
    basewin_child_x; every other child keeps fl(w*g/16).  (The tab-row children have their own arm; CONQUER's
    right edge S - pt(30) is rim_x(696) too; the RENAME / OK row its own, basewin_child_rect v7.)  g<=16: w."""
    if g <= NATIVE_G:
        return w
    if basewin_is_rim(x + w):
        return basewin_rim_x(x + w, g) - basewin_child_x(x, w, g)
    return popup_scale_floor(w, g)


BASEWIN_RCOL_L = 563   # the right column's left edge (vanilla 563 = the mirror of the left column's 163)


def basewin_mirror_x(v: int, g: int) -> int:
    """The mirror of a native EXCLUSIVE edge v through the base screen's axis: S - pt(726 - v).  A half-open [l, r)
    maps to [S - pt(726 - l'), ...) with every column c of the twin at S - 1 - c, so the twin's first / last columns
    swap exactly.  Within 1 px of pt(v) when S = pt(726) (W5A v2).  g<=16: v."""
    if g <= NATIVE_G:
        return v
    return basewin_rail_axis_sum(g) - basewin_pt(BASEWIN_TAB_SUM - v, g)


def basewin_left_x(l: int, g: int) -> int:
    """A native LEFT edge l -> device (W5A v4): a right-column left edge (l >= 563) is the exclusive axis mirror
    S - pt(726 - l) -- the first column of its half-open box, the mirror of the left twin's last column pt(726 - l) - 1;
    any other edge the plain interior law pt(l).  basewin_mirror_rect's L, and the left edge the text rects
    (thunk_bw_rect_core, basewin_text_rect) and the facilities wheel hit test (t_bw_wheel_down) take, so the centred
    text and the hit area follow the drawn box.  g<=16: l."""
    if g <= NATIVE_G:
        return l
    return basewin_mirror_x(l, g) if l >= BASEWIN_RCOL_L else basewin_pt(l, g)


def basewin_text_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """The device rect thunk_bw_rect_core hands a BaseWin text primitive for a native text rect (W5A v4): left edge
    basewin_left_x, right edge basewin_rim_x, T / B plain pt -- in the right column the text box is the drawn box's
    half-open extent, so a centred title (BASE FACILITIES) is the mirror of its left twin's.  g<=16: the rect."""
    if g <= NATIVE_G:
        return (l, t, r, b)
    return (basewin_left_x(l, g), basewin_pt(t, g), basewin_rim_x(r, g), basewin_pt(b, g))


def basewin_mirror_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """W5A v2 / v4: the HALF-OPEN device rect [L, R) x [T, B) of a native centre box / clip / fill [l, r) x [t, b).
    Every edge that has a mirror twin about the base screen's axis 363 is placed by the mirror of the twin
    (basewin_mirror_x), every other edge by plain basewin_pt:
      * a left edge in the right column (l >= 563: the right panel 563, its inner boxes 566) -- the left column's
        right edges' mirror;
      * a right edge whose rect is in the right column (l >= 563), is self-mirrored (l + r == 726: the middle panel
        166..560, the support-view fill 167..559) or is a rim (690..699: the right panel, the intake / energy rows,
        their inner boxes) -- the left edges' mirror.
    T / B are plain pt.  So every twin pair of edges sums to S: the twin columns are equal in width and every channel
    between them pairs up, at every g.  Rects with no twin (the bottom chassis box 128..622 is mirrored about 375, not
    363; the expense pips; anything left of the axis) are plain pt.
    The clips (thunk_bw_clip) and the support-view fill (thunk_bw_fill2) take this rect as is -- the engine's
    primitives are half-open.  A BOX takes basewin_box_draw_rect (the inclusive band renderers' R - 1 / B - 1).
    v4 (F42): v2 / v3 handed the box renderers this rect inclusive (pt(r) / pt(b) drawn: every box +1 px right and
    down; the right column mirrored that overreach onto its LEFT edge, S - 1 - pt(726 - l)).  Half-open, a right-column
    left edge is the plain exclusive mirror for a box and a clip alike (the clip still starts on the box's first
    column).  g<=16: the rect itself."""
    if g <= NATIVE_G:
        return (l, t, r, b)
    L = basewin_left_x(l, g)
    mirr = l >= BASEWIN_RCOL_L or l + r == BASEWIN_TAB_SUM or basewin_is_rim(r)
    R = basewin_mirror_x(r, g) if mirr else basewin_pt(r, g)
    return (L, basewin_pt(t, g), R, basewin_pt(b, g))


def basewin_box_draw_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-25 W5A v4, F42) -- the INCLUSIVE rect a centre box_sprite site (thunk_bw_boxsprite) draws: the
    half-open basewin_mirror_rect trimmed by the shared F42 helpers (t_bm_ho_hf / t_bm_ho_df:
    bandmap_rect_from_halfopen, R - 1 and B - 1 in place around the band renderer), so the footprint [L, R-1] x
    [T, B-1] is exactly vanilla's half-open extent at device scale -- on BOTH columns, and the mirror pairs stay
    exact (a left box's last column pt(r) - 1 and its right twin's first column S - pt(r) sum to S - 1).
    g<=16: the native rect (the native primitive draws it half-open)."""
    return bandmap_rect_from_halfopen(*basewin_mirror_rect(l, t, r, b, g), g)


#: the BaseWin interior fills (thunk_bw_fill2) that are a native 1-px inset of a centre box, -> that box: draw_farm's
#: GraphicWin_fill_2 @0x40F17F fills (167, 34, 559, 256) right AFTER its box (166, 33, 560, 257) @0x40F156
BASEWIN_FILL_INSET_BOX = {(167, 34, 559, 256): (166, 33, 560, 257)}


def basewin_fill_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-25 W5A v5) -- the device rect thunk_bw_fill2 hands GraphicWin_fill_2 for a native BaseWin fill.

    A fill that vanilla builds as the native 1-px inset of the box it follows (BASEWIN_FILL_INSET_BOX: the middle /
    farm panel's interior, drawn AFTER the box) is that box's DRAWN interior: the half-open box
    [L, R) x [T, B) = basewin_mirror_rect(box) inset by the stroke width K on every side,
    [L + K, R - K) x [T + K, B - K) -- vanilla's inset 1 IS its stroke width.  v4 scaled the inset rect on its own
    (basewin_mirror_rect of 167..559 / 34..256): with the box now half-open, the fill overpainted the inner column / row
    of the K = 2 right / bottom strokes (audit-w5A v4: stroke widths L / R / T / B 1 / 1 / 2 / 1 at g 25 / 27, bottom 1
    at g 26, 28..31; the fill also left a 1-px backdrop gap where pt(167) - pt(166) = 2 or pt(34) - pt(33) = 3 > K).
    Every other fill (the SUPPORT view's full-panel black fill @0x408EF2, rcRspPanel itself) is the half-open
    basewin_mirror_rect.  g<=16: the rect (the native primitive, inset 1 = K)."""
    if g <= NATIVE_G:
        return (l, t, r, b)
    box = BASEWIN_FILL_INSET_BOX.get((l, t, r, b))
    if box is None:
        return basewin_mirror_rect(l, t, r, b, g)
    L, T, R, B = basewin_mirror_rect(*box, g)
    k = stroke_width(g)
    return (L + k, T + k, R - k, B - k)


BASEWIN_TWIN_ROWS = (7, 234)   # native y of the BaseWin child rows mirrored about 363: the tab row (EXPLORE ..
                               # CONQUER) and the RESOURCE / SUPPORT / PSYCH row (169 / 299 / 429, w 128).  The
                               # RENAME / OK row (y 449) is centred on 375 -- not a twin row.


BASEWIN_OKROW_Y = 449          # the RENAME (131, w 238) / OK (381, w 238) row: mirrored about x = 375 inside its row
BASEWIN_OKROW_SUM = 750        # frame, the BaseWin_init box (128, 446, 622, 472) @0x41F5B7 (128 + 622 = 131 + 619 =
BASEWIN_OKROW_BOX_L = 128      # 369 + 381 = 750); the box itself is drawn on plain pt (t_bw_mirrect: no twin about
BASEWIN_OKROW_BOX_R = 622      # 363), so the row mirrors through the box's OWN device edge sum
BASEWIN_CHEV_GAP = 2           # vanilla's chevron channels: DISCOVER 256 | 258 chevron 1 278 | 280 GOVERNOR


def basewin_okrow_axis_sum(g: int) -> int:
    """The RENAME / OK row's device mirror axis as an edge sum: the drawn row frame's own half-open edges,
    S2 = pt(128) + pt(622) (the box is placed on plain pt).  So box -> RENAME and OK -> box are equal channels and
    RENAME | OK is self-mirrored at every g (v6: unequal at 45 of g 17..64).  g<=16: 750."""
    if g <= NATIVE_G:
        return BASEWIN_OKROW_SUM
    return basewin_pt(BASEWIN_OKROW_BOX_L, g) + basewin_pt(BASEWIN_OKROW_BOX_R, g)


BASEWIN_TAB_CHANNEL = 2        # vanilla's visible channel between a tab-frame stroke (rows 4 / 29) and the buttons
BASEWIN_TAB_ROW_DIMS = ("T", "B", "H", "t", "tb", "c")   # frame top / bottom / height, button top / bottom, channel


def basewin_tab_row_v6(g: int) -> Tuple[int, int, int]:
    """The deployed (v6, thunk_bw_boxsprite_tabframe v4) tab row, vertically: (frame top T, frame bottom B
    half-open, button top t) -- T = pt(4), t = pt(7), the frame's bottom stroke row mirrored about the buttons
    [t, t + fl(20g/16)): B = 2t + fl(20g/16) - T.  The reference basewin_tab_row_v is never worse than."""
    if g <= NATIVE_G:
        return (BASEWIN_TABFRAME_T, 30, BASEWIN_TAB_Y)
    t, tp = basewin_pt(BASEWIN_TAB_Y, g), basewin_pt(BASEWIN_TABFRAME_T, g)
    return (tp, 2 * t + popup_scale_floor(BASEWIN_TAB_BTN_H, g) - tp, t)


def basewin_tab_row_errors(T: int, B: int, t: int, g: int) -> dict:
    """Device - vanilla x g/16 of the tab row's vertical dimensions: the frame's top T, bottom B (half-open) and
    height, the buttons' top t and bottom t + fl(20g/16), and the visible channel c = t - T - K (= the bottom one,
    the row is mirrored) against vanilla's 2 px."""
    h, k = popup_scale_floor(BASEWIN_TAB_BTN_H, g), stroke_width(g)
    return {"T": T - 4 * g / 16, "B": B - 30 * g / 16, "H": (B - T) - 26 * g / 16, "t": t - 7 * g / 16,
            "tb": t + h - 27 * g / 16, "c": (t - T - k) - BASEWIN_TAB_CHANNEL * g / 16}


@functools.lru_cache(maxsize=None)
def basewin_tab_row_v(g: int) -> Tuple[int, int, int]:
    """LAW (2026-10-25 W7H v2, the audit-w7H law) -- the tab row, vertically: (frame top T, frame bottom B half-open,
    button top t).  Every tab-row child keeps h = fl(20g/16) (the 20-row bar art and the chevrons' 20 x 20 coverage
    art fill exactly that; a taller window recovers a 21- / 22-row native face through thunk_btn_shrink's CEIL
    inverse and leaves transparent key rows under the art -- measured).  The row stays vertically mirrored like
    vanilla's (strokes at 4 and 29 around buttons 7..27: channels 2 | 2): ONE visible channel c above and below the
    buttons, T = t - K - c, B = t + h + c + K.

    t (floor or ceil of 7g/16) and c are chosen JOINTLY per g, over the six dimensions basewin_tab_row_errors scores,
    lexicographically: (1) no dimension > 1 px off vanilla x g/16 that the deployed row (basewin_tab_row_v6) had
    within 1 px; (2) the fewest dimensions > 1 px; (3) the fewest dimensions worse than deployed; (4) the smallest
    worst error.  v6 mirrored the frame about pt(7) + fl(20g/16), whose bottom lags up to 1.56 px: the frame bottom
    ran -1.12 .. -1.88 at g 18 / 20 / 22 / 25 / 27 / 29 / 31 / 34 / 36 / 38, the buttons' bottom -1.06 .. -1.56.  This
    law: every dimension within 1 px at every g 17..40 except the channel at g 23 / 39 (+1.12, = deployed), none
    worse than deployed beyond 1 px; within 1 px the channel at g 18 / 34 (-0.25 -> +0.75) and the button top at
    g 19 / 35 (-0.31 -> +0.69, the price of its bottom -1.06 -> -0.06) are the only dimensions further from
    vanilla x g/16 than deployed; the frame top leaves pt(4) by 1 px where that is closer (or no worse) on every
    dimension.  4K unchanged (T 10, t 17, B 74).  Port: thunk_basewin_gwinit v7 / thunk_bw_boxsprite_tabframe v5
    read g_bw_tabrow_tbl (t, T per g 17..G_MAX, emitted from this law).  g<=16: vanilla; g > G_MAX (unreachable,
    g_popup_scale_num is clamped): v6."""
    if g <= NATIVE_G or g > G_MAX:
        return basewin_tab_row_v6(g)
    h, k = popup_scale_floor(BASEWIN_TAB_BTN_H, g), stroke_width(g)
    dep = basewin_tab_row_errors(*basewin_tab_row_v6(g), g)
    best = None
    for t in sorted({(BASEWIN_TAB_Y * g) >> 4, -((-BASEWIN_TAB_Y * g) >> 4)}):
        for c in range(0, (3 * g >> 4) + 3):
            T, B = t - k - c, t + h + c + k
            e = basewin_tab_row_errors(T, B, t, g)
            key = (sum(abs(e[d]) > 1 >= abs(dep[d]) for d in BASEWIN_TAB_ROW_DIMS),
                   sum(abs(e[d]) > 1 for d in BASEWIN_TAB_ROW_DIMS),
                   sum(abs(e[d]) > abs(dep[d]) + 1e-9 for d in BASEWIN_TAB_ROW_DIMS),
                   max(abs(v) for v in e.values()), t, c)
            if best is None or key < best[0]:
                best = (key, (T, B, t))
    return best[1]


def basewin_tab_btn_y(g: int) -> int:
    """The tab-row children's device top (y == 7): basewin_tab_row_v's t.  g<=16: 7."""
    return basewin_tab_row_v(g)[2]


def basewin_tabframe_top(g: int) -> int:
    """The tab-frame box's (site 0x41F56A) TOP edge, the first row of its top stroke: basewin_tab_row_v's T
    (v6: pt(4)).  g<=16: 4."""
    return basewin_tab_row_v(g)[0]


def basewin_chev_x(native_x: int, g: int) -> int:
    """W7H (2026-10-25) -- a LEFT-half chevron's device x (the 20 x 20 state-sprite children, w == h == 20 on the tab
    row: chevron 1 at 258).  The chevron is D x D, D = fl(20g/16) -- its coverage art's own size: the edge law's
    pt(278) - pt(258) is D + 1 at g 19 / 22 / 23 / 27 / 30 / 31 / 35 / 38 / 39, where thunk_btn_shrink's CEIL inverse
    then recovers a 21-px native face and the art leaves a transparent key column.  Its CENTRE is vanilla's
    (x + 10) scaled onto the base screen's axis S = basewin_tab_axis_sum (= pt(726), through which chevron 2 mirrors
    it): x = (fl(2 (x + 10) S / 726) - D + 1) >> 1.  v6's pt(258) left chevron 1's right edge up to 1.62 px short
    (g 19 / 22 / 23 / 27 / 30 / 31 / 35 / 38 / 39) and chevron 2's left edge on the mirror; anchored on S, all four
    chevron edges are within 1 px at every g 17..64, and the DISCOVER | chevron | GOVERNOR channels (vanilla 2 | 2)
    are never further apart than v6's (unequal at 24 of g 17..64, v6 36).  g<=16: x."""
    if g <= NATIVE_G:
        return native_x
    d = popup_scale_floor(BASEWIN_CHEV_W, g)
    c2 = (2 * (native_x + BASEWIN_CHEV_W // 2) * basewin_tab_axis_sum(g)) // BASEWIN_TAB_SUM
    return (c2 - d + 1) >> 1


def basewin_child_rect(x: int, y: int, w: int, h: int, g: int) -> Tuple[int, int, int, int]:
    """thunk_basewin_gwinit v8's child arm (x, y, w, h device) for a BaseWin child built at native (x, y, w, h).

    v6: on a twin row (BASEWIN_TWIN_ROWS) a right-half child (x > 363) mirrors its twin, x = S - pt(726 - x - w) -
    fl(wg/16) (basewin_tab_mirror_x), and the self-mirrored child (2x + w == 726: GOVERNOR, SUPPORT) is centred,
    w = S - 2 pt(x); elsewhere a rim child (x + w in 690..699) ends on basewin_rim_x (basewin_child_w); everything
    else x g/16.
    v7 (W7H 2026-10-25), three arms on top:
      * the tab row (y == 7): y = basewin_tab_btn_y ((7g + 7) >> 4), h = fl(20g/16) -- the tab frame mirrors its
        bottom about these buttons (basewin_tabframe_bottom);
      * the chevrons (y == 7, w == 20): chevron 1 D x D at basewin_chev_x, chevron 2 its mirror S - x1 - D;
      * the RENAME / OK row (y == 449, mirrored about 375 inside its frame (128, 446, 622, 472)): RENAME on the edge
        law [pt(131), pt(369)), OK the mirror [S2 - pt(369), S2 - pt(131)) through the frame's own edge sum
        S2 = basewin_okrow_axis_sum (v6: fl(238g/16) from pt(x), the right edges -1.06 .. -1.69): both 238 g/16
        within 1 px, box -> RENAME == OK -> box at every g; y / h unchanged (pt(449), fl(20g/16)).
    v8 (W8B 2026-10-27, the user's F48 / F49 / F50): the button rows' GAPS --
      * the tab row's left half EXPLORE / DISCOVER / chevron 1 on basewin_tab_row_h (equal gaps between the buttons,
        any remainder in the frame -> EXPLORE channel), the right half (BUILD / CONQUER / chevron 2) their mirrors
        through S, x = S - x_twin - w_twin;
      * RESOURCE / SUPPORT on basewin_rsp_row_h (panel -> RESOURCE == RESOURCE -> SUPPORT), PSYCH RESOURCE's mirror,
        SUPPORT centred (w = S - 2x);
      * RENAME / OK: y = basewin_okrow_v's t (the row frame moves with it: basewin_okrow_box_rect -- one channel
        above and below the buttons).
    v9 (W8R 2026-10-27, audit-w8B F52): RESOURCE / SUPPORT / PSYCH (the three w-128 children of row 234 the v8 arm
    places) y = basewin_rsp_row_v (the channel below the buttons the row's side channel; h unchanged).
    GOVERNOR and every other child as v7.  g > G_MAX (unreachable): v7.
    The hit rect is the window, so it follows the drawn button.  g<=16: the args."""
    if g <= NATIVE_G:
        return (x, y, w, h)
    py, ph = basewin_pt(y, g), popup_scale_floor(h, g)
    S = basewin_rail_axis_sum(g)
    if y in BASEWIN_TWIN_ROWS:
        twin = x if x <= BASEWIN_TAB_AXIS else BASEWIN_TAB_SUM - x - w
        left = basewin_row_left_child(twin, y, w, g)
        if y == BASEWIN_TAB_Y:
            py = basewin_tab_btn_y(g)
        if left is not None:
            lx, lw = left
            if y == BASEWIN_RSP_Y:
                py = basewin_rsp_row_v(g)
            if x <= BASEWIN_TAB_AXIS:
                return (lx, py, lw, ph)
            return (S - lx - lw, py, lw, ph)
        if y == BASEWIN_TAB_Y and w == BASEWIN_CHEV_W:
            d = popup_scale_floor(BASEWIN_CHEV_W, g)
            if x > BASEWIN_TAB_AXIS:
                return (S - basewin_chev_x(twin, g) - d, py, d, ph)
            return (basewin_chev_x(x, g), py, d, ph)
        if x > BASEWIN_TAB_AXIS:
            return (basewin_tab_mirror_x(x, w, g), py, popup_scale_floor(w, g), ph)
        if 2 * x + w == BASEWIN_TAB_SUM:
            if (y, x) == (BASEWIN_RSP_Y, BASEWIN_RSP_SUPPORT_X):
                sx = basewin_rsp_row_h(g)[2]
                py = basewin_rsp_row_v(g)
            else:
                sx = basewin_pt(x, g)
            return (sx, py, S - 2 * sx, ph)
        return (basewin_pt(x, g), py, popup_scale_floor(w, g), ph)
    if y == BASEWIN_OKROW_Y:
        py = basewin_okrow_v(g)[2]
        if 2 * x > BASEWIN_OKROW_SUM:
            tl, tr = BASEWIN_OKROW_SUM - x - w, BASEWIN_OKROW_SUM - x
            return (basewin_okrow_axis_sum(g) - basewin_pt(tr, g), py, basewin_pt(tr, g) - basewin_pt(tl, g), ph)
        return (basewin_pt(x, g), py, basewin_pt(x + w, g) - basewin_pt(x, g), ph)
    return (basewin_child_x(x, w, g), py, basewin_child_w(x, w, g), ph)


BASEWIN_ROW_GAP = 2            # vanilla's channel between neighbours on the base screen's button rows: tab frame 27 |
                               # 30 EXPLORE 142 | 144 DISCOVER 256 | 258 chevron 278 | 280 GOVERNOR (mirrored on the
                               # right); panel 166 | 169 RESOURCE 297 | 299 SUPPORT 427 | 429 PSYCH 557 | 559 panel
BASEWIN_TAB_E_X, BASEWIN_TAB_D_X, BASEWIN_TAB_BTN_W = 30, 144, 112   # EXPLORE / DISCOVER (w 112, BUILD / CONQUER
                                                                     # their mirrors)
BASEWIN_RSP_Y = 234
BASEWIN_RSP_R_X, BASEWIN_RSP_SUPPORT_X, BASEWIN_RSP_W = 169, 299, 128  # RESOURCE / SUPPORT (PSYCH 429 = the mirror)
BASEWIN_RSP_PANEL_L = 166      # the middle panel (166, 33, 560, 257) the row sits in: its left stroke column
BASEWIN_OKROW_BOX_T, BASEWIN_OKROW_BOX_B = 446, 472   # the RENAME / OK row frame's top / half-open bottom
BASEWIN_OKROW_DIMS = ("T", "B", "H", "t", "tb", "c", "cb", "above", "aboveL", "below")
BASEWIN_OKROW_ABOVE_B = 441    # the energy-allocation panel (166, 352, 699, 441) above the RENAME / OK frame: its bottom
BASEWIN_OKROW_ABOVEL_B = 443   # the left column's bottom box (27, 387, 163, 443), above-left of the frame: its bottom


def basewin_row_left_child(twin: int, y: int, w: int, g: int) -> Optional[Tuple[int, int]]:
    """(device x, device w) of a LEFT-half twin-row child the v8 row laws place (native left x `twin` on row y), else
    None: the tab row's EXPLORE (30) / DISCOVER (144) and chevron 1 (258, w 20) -- basewin_tab_row_h; the
    RESOURCE / SUPPORT / PSYCH row's RESOURCE (169) -- basewin_rsp_row_h.  thunk_basewin_gwinit v8 reads the same
    values from g_bw_rows_tbl (t_bw_rowfix)."""
    if g <= NATIVE_G:
        return None
    if y == BASEWIN_TAB_Y:
        xe, wb, xd, xc = basewin_tab_row_h(g)
        if w == BASEWIN_CHEV_W:
            return (xc, popup_scale_floor(BASEWIN_CHEV_W, g)) if twin == BASEWIN_CHEV1_X else None
        if w == BASEWIN_TAB_BTN_W and twin in (BASEWIN_TAB_E_X, BASEWIN_TAB_D_X):
            return (xe if twin == BASEWIN_TAB_E_X else xd, wb)
        return None
    if y == BASEWIN_RSP_Y and twin == BASEWIN_RSP_R_X and w == BASEWIN_RSP_W:
        xr, wr, _xs = basewin_rsp_row_h(g)
        return (xr, wr)
    return None


def basewin_tab_row_h_v7(g: int) -> Tuple[int, int, int, int]:
    """The deployed (v7) tab row's left half, horizontally: (EXPLORE x, button w, DISCOVER x, chevron 1 x) =
    (pt(30), fl(112g/16), pt(144), basewin_chev_x(258)).  The reference basewin_tab_row_h is never worse than."""
    return (basewin_pt(BASEWIN_TAB_E_X, g), popup_scale_floor(BASEWIN_TAB_BTN_W, g), basewin_pt(BASEWIN_TAB_D_X, g),
            basewin_chev_x(BASEWIN_CHEV1_X, g))


def basewin_tab_row_h_errors(xe: int, wb: int, xd: int, xc: int, g: int) -> Tuple[Tuple[int, ...], dict]:
    """The tab row's left half: (the four visible gaps frame -> EXPLORE -> DISCOVER -> chevron 1 -> GOVERNOR,
    {dimension: device - vanilla x g/16}) -- every button edge, the button width, each gap against vanilla's 2.  The
    frame's left stroke [pt(27), + K) and GOVERNOR's left edge pt(280) are fixed (the frame is flush with the column
    panels below it, GOVERNOR centred on the axis); the chevron is D x D, D = fl(20g/16)."""
    k, d = stroke_width(g), popup_scale_floor(BASEWIN_CHEV_W, g)
    f0, gl = basewin_pt(BASEWIN_TABFRAME_L, g), basewin_pt(BASEWIN_GOV_L, g)
    gaps = (xe - f0 - k, xd - xe - wb, xc - xd - wb, gl - xc - d)
    pos = {"xE": (xe, 30), "rE": (xe + wb, 142), "xD": (xd, 144), "rD": (xd + wb, 256), "xC": (xc, 258),
           "rC": (xc + d, 278), "w": (wb, 112)}
    S = basewin_rail_axis_sum(g)
    for n in ("xE", "rE", "xD", "rD", "xC", "rC"):     # the right half: each edge's mirror S - v (native 726 - n)
        v, nat = pos[n]
        pos["m" + n] = (S - v, BASEWIN_TAB_SUM - nat)
    e = {n: v - nat * g / 16 for n, (v, nat) in pos.items()}
    for i, a in enumerate(gaps):
        e[f"a{i}"] = a - BASEWIN_ROW_GAP * g / 16
    return gaps, e


@functools.lru_cache(maxsize=None)
def basewin_tab_row_h(g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-27 W8B, the user's F49) -- the tab row's left half, horizontally: (EXPLORE x, button w,
    DISCOVER x, chevron 1 x); BUILD / CONQUER / chevron 2 are their mirrors through S (basewin_child_rect v8),
    GOVERNOR keeps pt(280) .. S - pt(280), the frame pt(27).  Vanilla's gaps are all 2 (frame 27 | 30 EXPLORE 142 |
    144 DISCOVER 256 | 258 chevron 278 | 280 GOVERNOR); v7 placed each edge on its own floor, so the gaps came out
    unequal at 19 of g 17..40 (1600x1200 2, 4, 3, 3 -- frame -> EXPLORE 1.12 px short; 1280x1024 3, 3, 2, 3).
    Each tuple here is the LEFT half (frame | E | D | chevron | GOVERNOR); the right half is its mirror.

    Between the fixed frame stroke and GOVERNOR the half holds EXPLORE, DISCOVER (one width wb, = each other like
    vanilla's) and the D-wide chevron: four gaps, mirrored onto the right half through S -- so every right-half edge is
    S - v, and its error is -frac(726g/16) - the left one's (basewin_tab_row_h_errors scores both halves).  wb is
    fl(112g/16) or one more / less, chosen jointly with the gaps, lexicographically over those dimensions: (1) none
    > 1 px off vanilla x g/16 that v7 had within 1 px; (2) the fewest > 1 px; (3) the smallest spread of the four
    gaps; (4) a remainder that cannot be split evenly sits in ONE mirrored gap pair, at the row ends (frame ->
    EXPLORE = CONQUER -> frame) or flanking GOVERNOR (chevron -> GOVERNOR = GOVERNOR -> chevron), the other three
    gaps equal (the user's "slack placed symmetrically / at the row ends"); (5) the fewest changed values against v7
    (v7 itself is a candidate: a row v7 already equalised is kept); (6) the smallest worst error; (7) the smallest
    sum.  Result: all four gaps equal at 10 of g 17..40 (18, 22, 25, 26, 28, 30..32, 34, 38; 1600x1200 3, 3, 3, 3,
    1600x900 3, 3, 3, 3 with the buttons 1 px narrower); the remainder at the row ends at 17 / 23 / 24 / 33 / 39 / 40
    (4K 6, 5, 5, 5 = v7) or flanking GOVERNOR at 20 / 36 (1280x1024 3, 3, 3, 2); at 19 / 21 / 27 / 29 / 35 / 37 no
    such layout is within 1 px and v7 stays.  Every dimension within 1 px except the frame channel at g 23 / 39
    (+1.12, = v7).  4K unchanged.  Port: t_bw_rowfix reads g_bw_rows_tbl (emitted from this law).  g<=16 / g > G_MAX
    (unreachable): v7."""
    v7 = basewin_tab_row_h_v7(g)
    if g <= NATIVE_G or g > G_MAX:
        return v7
    k, d = stroke_width(g), popup_scale_floor(BASEWIN_CHEV_W, g)
    f0, gl = basewin_pt(BASEWIN_TABFRAME_L, g), basewin_pt(BASEWIN_GOV_L, g)
    w0 = popup_scale_floor(BASEWIN_TAB_BTN_W, g)
    _g7, e7 = basewin_tab_row_h_errors(*v7, g)
    cands = [v7]
    for wb in (w0 - 1, w0, w0 + 1):
        slack = gl - f0 - k - 2 * wb - d
        for a0 in range(1, slack - 2):
            for a1 in range(1, slack - a0 - 1):
                for a2 in range(1, slack - a0 - a1):
                    xe = f0 + k + a0
                    cands.append((xe, wb, xe + wb + a1, xe + 2 * wb + a1 + a2))
    best = None
    for c in cands:
        gaps, e = basewin_tab_row_h_errors(*c, g)
        placed = gaps[1] == gaps[2] == gaps[3] or gaps[0] == gaps[1] == gaps[2]    # the odd pair at the ends / centre
        key = (sum(abs(e[n]) > 1 >= abs(e7[n]) for n in e), sum(abs(e[n]) > 1 for n in e),
               max(gaps) - min(gaps), not placed, sum(a != b for a, b in zip(c, v7)),
               round(max(abs(v) for v in e.values()), 9), round(sum(abs(v) for v in e.values()), 9), c)
        if best is None or key < best[0]:
            best = (key, c)
    return best[1]


def basewin_rsp_row_h_v7(g: int) -> Tuple[int, int, int]:
    """The deployed (v7) RESOURCE / SUPPORT / PSYCH row, horizontally: (RESOURCE x, RESOURCE w, SUPPORT x) =
    (pt(169), fl(128g/16), pt(299)); SUPPORT w = S - 2x, PSYCH the mirror of RESOURCE."""
    return (basewin_pt(BASEWIN_RSP_R_X, g), popup_scale_floor(BASEWIN_RSP_W, g),
            basewin_pt(BASEWIN_RSP_SUPPORT_X, g))


def basewin_rsp_row_h_errors(xr: int, wr: int, xs: int, g: int) -> Tuple[Tuple[int, int], int, dict]:
    """The RESOURCE / SUPPORT / PSYCH row: ((panel -> RESOURCE, RESOURCE -> SUPPORT) -- the row is mirrored, so its
    gaps are (a, b, b, a) --, SUPPORT's width S - 2 xs, {dimension: device - vanilla x g/16}).  The panel's left
    stroke [pt(166), + K) is fixed (basewin_box_draw_rect of the middle panel; its right stroke is the mirror)."""
    k, S = stroke_width(g), basewin_rail_axis_sum(g)
    pl = basewin_pt(BASEWIN_RSP_PANEL_L, g)
    ws = S - 2 * xs
    gaps = (xr - pl - k, xs - xr - wr)
    pos = {"xR": (xr, 169), "rR": (xr + wr, 297), "xS": (xs, 299), "rS": (S - xs, 427), "wR": (wr, 128),
           "wS": (ws, 128), "xP": (S - xr - wr, 429), "rP": (S - xr, 557)}
    e = {n: v - nat * g / 16 for n, (v, nat) in pos.items()}
    for i, a in enumerate(gaps):
        e[f"a{i}"] = a - BASEWIN_ROW_GAP * g / 16
    return gaps, ws, e


@functools.lru_cache(maxsize=None)
def basewin_rsp_row_h(g: int) -> Tuple[int, int, int]:
    """LAW (2026-10-27 W8B, the user's F50) -- the RESOURCE / SUPPORT / PSYCH row, horizontally: (RESOURCE x,
    RESOURCE w, SUPPORT x); SUPPORT w = S - 2x (centred), PSYCH = RESOURCE's mirror through S.  Vanilla's gaps are
    all 2 (panel 166 | 169 .. 297 | 299 .. 427 | 429 .. 557 | 559 panel); v7 (pt(169), fl(128g/16), pt(299)) left
    panel -> RESOURCE != RESOURCE -> SUPPORT at 9 of g 17..40 (1280x1024 3, 2, 2, 3).

    The row is mirrored, so its gaps are (a, b, b, a).  RESOURCE's width is fl(128g/16) or one more / less, its x
    and both gaps chosen jointly, lexicographically over basewin_rsp_row_h_errors' dimensions: (1) none > 1 px off
    vanilla x g/16 that v7 had within 1 px; (2) the fewest > 1 px; (3) |a - b|; (4) the fewest changed values
    against v7 (v7 is a candidate: a row v7 already equalised is kept); (5) RESOURCE w != SUPPORT w (vanilla: all
    128); (6) the smallest worst error; (7) the smallest sum.  Result: a == b at every g 17..40 but 18 / 34 (no equal
    layout within 1 px: v7's 3, 2, 2, 3 / 5, 4, 4, 5 kept, the remainder at the row ends).  Where v7's gaps were
    unequal and its widths equal (g 19 / 28 / 35) the equal gaps cost RESOURCE / PSYCH 1 px wider than SUPPORT
    (153 | 152 | 153 at g 19); g 20 / 29 / 36 trade v7's SUPPORT +1 for -1 (1280x1024 160 | 159 | 160); g 30 gets
    both relations (2560x1440 241 x 3, gaps 3).  Every dimension within 1 px.  4K unchanged.  Port: t_bw_rowfix
    reads g_bw_rows_tbl.  g<=16 / g > G_MAX (unreachable): v7."""
    v7 = basewin_rsp_row_h_v7(g)
    if g <= NATIVE_G or g > G_MAX:
        return v7
    k = stroke_width(g)
    pl = basewin_pt(BASEWIN_RSP_PANEL_L, g)
    w0 = popup_scale_floor(BASEWIN_RSP_W, g)
    _g7, _w7, e7 = basewin_rsp_row_h_errors(*v7, g)
    cands = [v7]
    for wr in (w0 - 1, w0, w0 + 1):
        for a in range(1, (4 * g >> 4) + 3):
            for b in range(1, (4 * g >> 4) + 3):
                cands.append((pl + k + a, wr, pl + k + a + wr + b))
    best = None
    for c in cands:
        gaps, ws, e = basewin_rsp_row_h_errors(*c, g)
        key = (sum(abs(e[n]) > 1 >= abs(e7[n]) for n in e), sum(abs(e[n]) > 1 for n in e),
               abs(gaps[0] - gaps[1]), sum(a != b for a, b in zip(c, v7)), int(ws != c[1]),
               round(max(abs(v) for v in e.values()), 9), round(sum(abs(v) for v in e.values()), 9), c)
        if best is None or key < best[0]:
            best = (key, c)
    return best[1]


BASEWIN_RSP_ROW_V_DIMS = ("t", "tb", "cb")


def basewin_rsp_row_v_v8(g: int) -> int:
    """The deployed (v8) RESOURCE / SUPPORT / PSYCH row's button top: pt(234) (h = fl(20g/16))."""
    return basewin_pt(BASEWIN_RSP_Y, g)


def basewin_rsp_panel_stroke_b(g: int) -> int:
    """The first device row of the middle panel's (166, 33, 560, 257) BOTTOM stroke, as drawn: the half-open box
    bottom pt(257) less the stroke width K (basewin_box_draw_rect's inclusive bottom pt(257) - 1, K rows up).
    Vanilla: row 256.  g<=16: 256."""
    return basewin_pt(BASEWIN_RSP_PANEL_NATIVE[3], g) - stroke_width(g)


def basewin_rsp_side_channel(g: int) -> int:
    """The RESOURCE / SUPPORT / PSYCH row's SIDE channel: panel left stroke -> RESOURCE (= PSYCH -> right stroke, the
    row is mirrored), basewin_rsp_row_h's first gap.  Vanilla 2 (stroke column 166, RESOURCE at 169)."""
    return basewin_rsp_row_h_errors(*basewin_rsp_row_h(g), g)[0][0]


def basewin_rsp_row_v_errors(t: int, g: int) -> dict:
    """Device - vanilla x g/16 of the RESOURCE / SUPPORT / PSYCH row's vertical dimensions for button top t: the top
    t (vanilla 234), the bottom t + fl(20g/16) (vanilla 254, half-open), and the visible channel below the buttons
    to the panel's bottom stroke cb = basewin_rsp_panel_stroke_b - t - h (vanilla 2: rows 254 / 255).  The row has no
    channel ABOVE it: the buttons overlay the panel content's (the farm / support map's) bottom edge."""
    h = popup_scale_floor(BASEWIN_TAB_BTN_H, g)
    return {"t": t - BASEWIN_RSP_Y * g / 16, "tb": t + h - (BASEWIN_RSP_Y + BASEWIN_TAB_BTN_H) * g / 16,
            "cb": (basewin_rsp_panel_stroke_b(g) - t - h) - BASEWIN_ROW_GAP * g / 16}


@functools.lru_cache(maxsize=None)
def basewin_rsp_row_v(g: int) -> int:
    """LAW (2026-10-27 W8R, audit-w8B F52) -- the RESOURCE / SUPPORT / PSYCH row, vertically: the three buttons' ONE
    device top t (h = fl(20g/16) unchanged: the 20-row bar art fills exactly that window -- the CEIL inverse
    recovers 20 -- so face == window == hit rect).  Vanilla sits the row inside the middle panel with ONE channel on
    three sides: panel stroke 166 | 169 RESOURCE (left), PSYCH 557 | 559 (right), buttons' bottom 254 | 256 stroke
    (below) -- all 2.  v8 placed t on pt(234) and the bottom on pt(234) + fl(20g/16): two floors, the bottom up to
    1.62 px short (g 19 / 27 / 35 -1.62, 22 / 30 / 38 -1.25, 23 / 31 / 39 -1.12) and the channel below one wider
    than the side channel there.

    t is chosen per g from floor / ceil of 234g/16 and the equal-channel top (basewin_rsp_panel_stroke_b - h -
    basewin_rsp_side_channel), lexicographically over basewin_rsp_row_v_errors: (0) never break a side == bottom
    channel equality v8 had (the user's rule: an equal pair stays equal); (1) none > 1 px off vanilla x g/16 that
    v8 had within 1 px; (2) the fewest > 1 px; (3) bottom channel == side channel; (4) v8 itself when it is a
    candidate (no change); (5) the smallest worst error.  Result: every dimension within 1 px at every g 17..40
    except g 31 (the bottom -1.12, = v8: its channels 4 | 4 are equal and the only within-1-px top, ceil, makes the
    bottom one 3 -- the user's call).  The channels become equal at g 17 / 22 / 23 / 27 / 30 / 33 / 38 / 39
    (1920x1080 3 | 3, was 3 | 4); they stay unequal at g 19 / 35 (side 2 / 4, bottom 3 / 5 -- v8 4 / 6; equal costs
    the top +1.12) and g 29 (side 4, bottom 3 = v8; equal costs the bottom -1.38).  1600x1200, 1280x1024, 1600x900,
    4K unchanged.  The row's mirror pairs are horizontal (basewin_rsp_row_h), untouched: one t for all three.
    Port: t_bw_rowfix reads g_bw_rspv_tbl (one word per g, emitted from this law).  g<=16 / g > G_MAX
    (unreachable): v8."""
    v8 = basewin_rsp_row_v_v8(g)
    if g <= NATIVE_G or g > G_MAX:
        return v8
    h, a = popup_scale_floor(BASEWIN_TAB_BTN_H, g), basewin_rsp_side_channel(g)
    sb = basewin_rsp_panel_stroke_b(g)
    e8 = basewin_rsp_row_v_errors(v8, g)
    eq8 = sb - v8 - h == a
    best = None
    for t in sorted({(BASEWIN_RSP_Y * g) >> 4, -((-BASEWIN_RSP_Y * g) >> 4), sb - h - a}):
        e = basewin_rsp_row_v_errors(t, g)
        eq = sb - t - h == a
        key = (eq8 and not eq, sum(abs(e[d]) > 1 >= abs(e8[d]) for d in BASEWIN_RSP_ROW_V_DIMS),
               sum(abs(e[d]) > 1 for d in BASEWIN_RSP_ROW_V_DIMS), not eq, t != v8,
               round(max(abs(v) for v in e.values()), 9), t)
        if best is None or key < best[0]:
            best = (key, t)
    return best[1]


def basewin_okrow_v_v7(g: int) -> Tuple[int, int, int]:
    """The deployed (v7) RENAME / OK row, vertically: (frame top T, frame bottom B half-open, button top t) =
    (pt(446), pt(472), pt(449)) -- channels above / below the buttons unequal at 14 of g 17..40 (1920x1080 3 | 4,
    4K 5 | 6; vanilla 2 | 2), the buttons' bottom up to 1.69 px short at 7 of them."""
    return (basewin_pt(BASEWIN_OKROW_BOX_T, g), basewin_pt(BASEWIN_OKROW_BOX_B, g), basewin_pt(BASEWIN_OKROW_Y, g))


def basewin_okrow_v_errors(T: int, B: int, t: int, g: int) -> dict:
    """Device - vanilla x g/16 of the RENAME / OK row's vertical dimensions: the frame's top T, bottom B (half-open)
    and height, the buttons' top t and bottom t + fl(20g/16), and the visible channels above (c = t - T - K) and
    below (cb = B - K - t - h) against vanilla's 2 | 2 (strokes at rows 446 / 471 around buttons 449..468), and
    (v2, audit-w8B C1) the frame's three NEIGHBOUR gaps: from the energy-allocation panel above (166, 352, 699, 441):
    T - pt(441) against vanilla's 5; from the left column's bottom box (27, 387, 163, 443), above-left: T - pt(443)
    against 3; to the base window's bottom: pt(490) - B against 18 (the BaseWin canvas is fl(490g/16) rows)."""
    h, k = popup_scale_floor(BASEWIN_TAB_BTN_H, g), stroke_width(g)
    return {"T": T - BASEWIN_OKROW_BOX_T * g / 16, "B": B - BASEWIN_OKROW_BOX_B * g / 16,
            "H": (B - T) - (BASEWIN_OKROW_BOX_B - BASEWIN_OKROW_BOX_T) * g / 16, "t": t - BASEWIN_OKROW_Y * g / 16,
            "tb": t + h - (BASEWIN_OKROW_Y + BASEWIN_TAB_BTN_H) * g / 16,
            "c": (t - T - k) - BASEWIN_TAB_CHANNEL * g / 16, "cb": (B - k - t - h) - BASEWIN_TAB_CHANNEL * g / 16,
            "above": (T - basewin_pt(BASEWIN_OKROW_ABOVE_B, g)) - (BASEWIN_OKROW_BOX_T - BASEWIN_OKROW_ABOVE_B) * g / 16,
            "aboveL": (T - basewin_pt(BASEWIN_OKROW_ABOVEL_B, g))
            - (BASEWIN_OKROW_BOX_T - BASEWIN_OKROW_ABOVEL_B) * g / 16,
            "below": (basewin_pt(BASEWIN_NATIVE_H, g) - B) - (BASEWIN_NATIVE_H - BASEWIN_OKROW_BOX_B) * g / 16}


@functools.lru_cache(maxsize=None)
def basewin_okrow_v(g: int) -> Tuple[int, int, int]:
    """LAW (2026-10-27 W8B, the user's F48) -- the RENAME / OK row, vertically: (frame top T, frame bottom B
    half-open, button top t).  The row is the tab row's twin in vanilla (a 1-px frame, buttons h 20, channel 2 above
    and below), so it takes the tab row's law with the tab row's OWN channel: c = basewin_tab_row_v's t - T - K
    (the two framed rows keep vanilla's equal channel at every g), T = t - K - c, B = t + h + c + K, h = fl(20g/16)
    (the bar art's own height, as on the tab row).  t is floor or ceil of 449g/16, chosen lexicographically over
    basewin_okrow_v_errors (the row's own dimensions AND, v2, the frame's three neighbour gaps): (1) none > 1 px off
    vanilla x g/16 that v7 had within 1 px; (2) the fewest > 1 px; (3) the fewest worse than v7; (4) v7 itself when
    it is a candidate (its channels already equal: no change); (5) the smallest worst error.  Result: every
    dimension within 1 px at every g 17..40 except the channels at g 23 / 39 (+1.12, = the tab row's; v7 had the
    bottom one there already -- every equal-channel layout has a dimension > 1 px there) and g 26, where every
    equal-channel layout has one dimension at 1.12: the law keeps v7's button bottom -1.12 (frame 724..766) -- the
    other choice, the frame 1 px lower (725..767), puts the gap to the left column's box at +1.12 (the user's call).
    A free channel (chosen per row, not the tab row's) gives the same layout at every g.  4K: the frame bottom
    1180 -> 1179; 1600x1200 unchanged (v1 moved it 1 px down: the gap to the window bottom -1.12, audit-w8B C1).
    Port: thunk_bw_boxsprite_okrow (the frame, site 0x41F5B7) and t_bw_rowfix (the buttons' y) read g_bw_rows_tbl.
    g<=16 / g > G_MAX (unreachable): v7."""
    v7 = basewin_okrow_v_v7(g)
    if g <= NATIVE_G or g > G_MAX:
        return v7
    h, k = popup_scale_floor(BASEWIN_TAB_BTN_H, g), stroke_width(g)
    tt, tT = basewin_tab_row_v(g)[2], basewin_tab_row_v(g)[0]
    c = tt - tT - k
    e7 = basewin_okrow_v_errors(*v7, g)
    best = None
    for t in sorted({(BASEWIN_OKROW_Y * g) >> 4, -((-BASEWIN_OKROW_Y * g) >> 4)}):
        T, B = t - k - c, t + h + c + k
        e = basewin_okrow_v_errors(T, B, t, g)
        key = (sum(abs(e[d]) > 1 >= abs(e7[d]) for d in BASEWIN_OKROW_DIMS),
               sum(abs(e[d]) > 1 for d in BASEWIN_OKROW_DIMS),
               sum(abs(e[d]) > abs(e7[d]) + 1e-9 for d in BASEWIN_OKROW_DIMS),
               (T, B, t) != v7, round(max(abs(v) for v in e.values()), 9), t)
        if best is None or key < best[0]:
            best = (key, (T, B, t))
    return best[1]


def basewin_okrow_box_rect(g: int) -> Tuple[int, int, int, int]:
    """The RENAME / OK row frame (BaseWin_init's box (128, 446, 622, 472), site 0x41F5B7), HALF-OPEN device rect:
    L / R on plain pt (basewin_mirror_rect: 128 + 622 is no twin pair), T / B from basewin_okrow_v.  Drawn by
    thunk_bw_boxsprite_okrow through the shared trim helpers (bandmap_rect_from_halfopen: R - 1 / B - 1).
    g<=16: the native rect."""
    if g <= NATIVE_G:
        return (BASEWIN_OKROW_BOX_L, BASEWIN_OKROW_BOX_T, BASEWIN_OKROW_BOX_R, BASEWIN_OKROW_BOX_B)
    T, B, _t = basewin_okrow_v(g)
    return (basewin_pt(BASEWIN_OKROW_BOX_L, g), T, basewin_pt(BASEWIN_OKROW_BOX_R, g), B)


def basewin_okrow_box_draw_rect(g: int) -> Tuple[int, int, int, int]:
    """The RENAME / OK row frame's INCLUSIVE band-renderer footprint: basewin_okrow_box_rect trimmed R - 1 / B - 1."""
    return bandmap_rect_from_halfopen(*basewin_okrow_box_rect(g), g)


def basewin_rows_table(g: int) -> Tuple[int, ...]:
    """g_bw_rows_tbl's row for g (17..G_MAX), ten little-endian words: the tab row's (EXPLORE x, button w,
    DISCOVER x, chevron 1 x) (basewin_tab_row_h), the RESOURCE / SUPPORT / PSYCH row's (RESOURCE x, RESOURCE w,
    SUPPORT x) (basewin_rsp_row_h), the RENAME / OK row's button top t and frame top T / bottom B (basewin_okrow_v)."""
    T, B, t = basewin_okrow_v(g)
    return basewin_tab_row_h(g) + basewin_rsp_row_h(g) + (t, T, B)


BASEWIN_CHEV1_X = 258   # BaseWin_init seed rects (l,t,r,b; w = r-l pushed):
BASEWIN_GOV_L = 280     #   EXPLORE 30..142, DISCOVER 144..256, chevron1 258..278,
BASEWIN_GOV_R = 446     #   GOVERNOR 280..446, chevron2 448..468, BUILD 470..582,
BASEWIN_CHEV2_X = 448   #   CONQUER 584..696; tab-frame box [27,4,699,30]
BASEWIN_CHEV_Y = 7      #   (+0x40d6c family literals; chevron w/h = the 20x20
BASEWIN_CHEV_W = 20     #   state-sprite's own dims via +0xc9e4)
BASEWIN_GOV_W = 166
BASEWIN_TAB_Y = 7        # every tab-row child window has y == 7
BASEWIN_TAB_AXIS = 363   # the native mirror axis (frame 27+699 = buttons 30+696 = 726)
BASEWIN_TAB_SUM = 726    # native edge-sum: mirror(x) = 726 - x
BASEWIN_TABFRAME_L = 27


def basewin_tab_axis_sum(g: int) -> int:
    """The tab row's device mirror axis, as an EDGE SUM (mirror(x) = S - x).

    Vanilla's whole tab row is mirror-symmetric about x=363 (frame 27..699,
    GOVERNOR 280..446 self-mirrored, satellite pairs chevron/BUILD/CONQUER
    flanking it). S is GOVERNOR's RENDERED device edge-sum:

        S = 2*pt(280) + fl(166*g/16)

    — the left edge through the child law twice plus the independently-
    floored width, exactly the window thunk_basewin_gwinit produces. Using
    the rendered edges (not pt(446), which can lag the rendered right edge
    by 1 when the two floor phases compose) keeps GOVERNOR itself the
    anchor: everything mirrored through S is symmetric to the BUTTON the
    pairs visually flank. g<=16: the native 726.

    v2 (2026-10-25 W5A, the base-screen mirror law): S is THE base-screen
    axis, basewin_rail_axis_sum(g) = pt(726) (the right rails sit on the
    left rails' mirror since W5A v2), and GOVERNOR is centred on it
    (basewin_gov_w: its rendered sum 2*pt(280) + fl(166g/16) is pt(726) or
    pt(726) - 1, so the width moves by 0 / +1).  With ONE axis every channel
    of the console / tab frame / button row pairs exactly; the one
    element that absorbs the parity is GOVERNOR's width (+0 / +1 px).  4K:
    the deployed row bit-identical.  The left half (EXPLORE, DISCOVER,
    chevron 1, the frame's left edge) is untouched."""
    return basewin_rail_axis_sum(g)


def basewin_gov_w(g: int) -> int:
    """GOVERNOR's device width (thunk_basewin_gwinit, the self-mirrored tab child: y == 7, 2x + w == 726): the span
    that centres it on the axis S = pt(726) with its left edge on pt(280), S - 2*pt(280) -- fl(166g/16) or one more
    (within 2 px of 166 g/16; 4K 415, unchanged).  g<=16: 166."""
    if g <= NATIVE_G:
        return BASEWIN_GOV_W
    return basewin_tab_axis_sum(g) - 2 * basewin_pt(BASEWIN_GOV_L, g)


def basewin_tab_mirror_x(native_x: int, native_w: int, g: int) -> int:
    """Device x for a RIGHT-half tab-row child (native x > 363: chevron2 448,
    BUILD 470, CONQUER 584) — the whole-row mirror law (2026-07-21g report:
    "the channel between Build and the Chevron is different than Discover
    and the Chevron ... All of those channels should be symmetric").

    Each right-half button is the mirror twin of a left-half one (twin_l =
    726 - x - w). Its device position mirrors the twin's RENDERED interval
    through the axis sum:

        x_dev = S - pt(726 - x - w) - fl(w*g/16)

    so every gap pair (frame|E vs C|frame, E|D vs B|C, D|chev vs chev|B,
    chev|GOV vs GOV|chev) is EQUAL at every g by construction — the gap
    tuple is palindromic (sweep-tested). Independent per-edge flooring
    quantized mirror twins on different phases (g=25: 3px left of the
    chevron pair vs 4px right; this superseded the 07-21f chevron-only law
    basewin_chev2_x, which equals this law's chevron case at every g where
    pt(446) == the rendered GOVERNOR right edge). Left-half children and
    GOVERNOR keep plain basewin_pt — the left side is the reference.
    Identity at g<=16 (S - (726-x-w) - w == x algebraically).  Since W5A
    (2026-10-25) S is the RAIL axis (basewin_tab_axis_sum v2), so the right
    half sits within 1 px of plain pt -- 4K bit-identical (chevron2
    1120, BUILD 1175, CONQUER 1460) -- with GOVERNOR sized to the same axis
    (basewin_gov_w); every gap pair stays equal."""
    if g <= NATIVE_G:
        return native_x
    twin_l = BASEWIN_TAB_SUM - native_x - native_w
    return (basewin_tab_axis_sum(g) - basewin_pt(twin_l, g)
            - popup_scale_floor(native_w, g))


def basewin_tabframe_right(g: int) -> int:
    """The tab-frame box's (site 0x41F56A) RIGHT edge: the exact pixel
    mirror of its left stroke COLUMN through the row axis,

        r_dev = S - pt(27) - 1

    MEASURED CONVENTION (2026-07-22, live 1920 + pristine capture): the
    frame primitive renders each stroke AT the arg coordinate, inclusive
    (left arg pt(27)=37 rendered at rel col 37; right arg rendered at its
    own col; same vertically). The mirror of an inclusive column c about a
    span with edge-sum S is S - 1 - c (first+last = S-1), so mirroring the
    1px left stroke needs the extra -1 — S - pt(27) (the 07-21g law) put
    the right channel 1 wider than the left at EVERY g (3/4 at g=22,
    masked at 4K as 6/7). Vanilla renders symmetric 2/2: its native args
    here are [27,4,698,29] — the [27,4,699,30] seed rect is exclusive-
    space, minus-one'd upstream. l/t stay plain pt; the bottom takes
    basewin_tabframe_bottom (the vertical twin). Identity at g<=16
    (726 - 27 - 1 = 698 == the measured native arg)."""
    if g <= NATIVE_G:
        return BASEWIN_TAB_SUM - BASEWIN_TABFRAME_L - 1
    return basewin_tab_axis_sum(g) - basewin_pt(BASEWIN_TABFRAME_L, g) - 1


BASEWIN_TABFRAME_T = 4
BASEWIN_TAB_BTN_H = 20   # every tab-row window: y=7, h=20 (chevrons = sprite dims)


def basewin_tabframe_bottom(g: int) -> int:
    """The tab-frame box's BOTTOM edge — the VERTICAL mirror-gap law
    (2026-07-21h 1920x1080 report: "the channel above the buttons and below
    the buttons does not match. The channel below should be smaller").

    Vanilla renders vertically symmetric: 1px strokes 25 native rows apart
    (rows 4 and 29 — MEASURED in the pristine capture 2026-07-22; its
    native args here are t=4, b=29, the seed rect's 30 being exclusive-
    space, minus-one'd upstream). The primitive renders each stroke AT the
    arg row, inclusive (measured live at g=22: t arg 5 -> rendered rel row
    5, b arg 40 -> rel row 40). The mirror of the inclusive top-stroke ROW
    t about the buttons' inclusive interval [btnT .. btnB-1] (whose
    first+last = btnT+btnB-1) is

        b_dev = btnT + btnB - 1 - t = 2*pt(7) + fl(20*g/16) - pt(4) - 1

    making the VISIBLE bottom channel (b - btnB) equal the visible top
    channel (btnT - t - 1) at every g by algebra. The 07-21h law omitted
    the -1 (it mirrored edge COORDINATES, not the stroke row), leaving the
    bottom channel 1 wider than the top at EVERY g — 3/4 at g=22 (the
    2026-07-22 "still slightly asymmetric" 1920 report), 3/4 at g=25, 6/7
    at 4K (below eye threshold). Identity at g<=16 (14 + 20 - 4 - 1 = 29
    == the measured native arg); |delta| from plain pt(30) <= 2."""
    if g <= NATIVE_G:
        return 29
    # v4 (W7H 2026-10-25): the last row of the bottom stroke of basewin_tab_row_v -- still the stroke-row mirror
    # of the top stroke about the buttons, but t and the channel are chosen jointly (v3: pt(7) + fl(20g/16) lagged by
    # up to 1.56, so the frame bottom ran -1.12..-1.88 px off 30g/16 at g 18/20/22/25/27/29/31/34/36/38).
    return basewin_tab_row_v(g)[1] - 1


def basewin_pt(v: int, g: int) -> int:
    """The BaseWin INTERIOR consumer-boundary law: every coordinate a
    BaseWin draw fn hands a drawing primitive whose dest is the BaseWin
    canvas (0x6A7A6C) scales floor(v*g/16) AT THE PRIMITIVE ENTRY; the draw
    fns' own math stays entirely native-space (no mixed-space class).

    RECTs scale each EDGE independently through this law (cum-position
    form): two cells that shared an edge natively stay flush scaled, and a
    cell's width comes out fl(r*g/16)-fl(l*g/16), NOT fl(w*g/16) — the
    remainder-distribution rule, applied by construction.

    v may be negative (clip sentinels); >>4 is an arithmetic shift, i.e.
    floor toward -inf, matching the JS Math.floor port exactly.
    """
    return v if g <= NATIVE_G else (v * g) >> 4


FACSB_W_NATIVE = 12   # BaseWin_draw_facilities: attach rect = [r - 0xC, t, r, b] (@0x41000D)


def basewin_facsb_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """BASE FACILITIES overflow-scrollbar attach rect (BaseWin_draw_facilities
    @0x41002C -> ScrollBar_attach_rect; thunk_bw_facsb_attach).

    Vanilla hands ScrollBar_attach_rect [r-12, t, r, b] built from the
    panel's NATIVE inner rect (the +0x40BAC field rect inset by 3; b is the
    facilities BaseButton's top +0x40E80 while that button is visible).  The
    bar is a child of BaseWin_g, so thunk_basewin_gwinit's generic child arm
    scaled its OUTER window x g/16 -- but ScrollBar_init_inner sizes the two
    arrow FlatButtons (w-2 square) and the track (h-2w) from the rect it is
    HANDED, so a native rect there leaves 10x10 native arrows and a native
    grip inside a device-wide rail (the 2026-09-20/21 report).  The fix hands
    init_inner the DEVICE rect and exempts the bar from the child arm, so
    every derived field is device space -- the exact shape the FORCES
    SUPPORTED bar already has (its rect is device at its site because its
    parent is the console MainWin, not BaseWin).

    Law: the right edge sits on the panel's inner right edge through the
    interior consumer-boundary law basewin_pt (the same value the row text
    and its Spot rects use); the width is the bar's OWN native width scaled,
    fl(12g/16) (a butting element scales to its own inset -- the supported
    bar's [listR-3-s(12), top, listR-3, bot]); top/bottom through basewin_pt.
    Identity at g<=16.  `l` is unused, as in vanilla; kept so the signature
    mirrors the caller's RECT.

    v2 (2026-10-25 W5A): the right edge is basewin_rim_x(r) -- the real r is
    the list's inner rim 693, which the base-screen mirror law places
    through the rail axis (it moves with the mirrored list box, 0..-4 px).
    A non-rim r keeps pt(r).
    """
    if g <= NATIVE_G:
        return (r - FACSB_W_NATIVE, t, r, b)
    x1 = basewin_rim_x(r, g)
    return (x1 - ((FACSB_W_NATIVE * g) >> 4), basewin_pt(t, g), x1, basewin_pt(b, g))


def basewin_font_size(native: int, g: int) -> int:
    """BaseWin interior text render-swap law (wmfr_l gate): layout runs with
    the NATIVE font (measures, centering, wrap budgets — all native-space);
    only at render does the gate substitute find_font(size*g/16). Floor
    idiom; identity at g<=16."""
    return native if g <= NATIVE_G else popup_scale_floor(native, g)


def basewin_sprite_ratio(num: int, den: int, g: int) -> Tuple[int, int]:
    """BaseWin interior sprite law (Sprite_draw_2/mono_2 gates): compose the
    call's own num/den with g/16 EXACTLY as a fraction — (num*g, den*16) —
    never pre-floor either factor (n*g and den*16 stay well inside int32 for
    engine ratios). Identity at g<=16.

    RESOURCE-view yield orbs (slice 8, farm_orb thunks): PRACX rewrites the
    rel32 of draw_farm's four sprite-blit CALL SITES at startup (pracx.cpp
    m_astHooks 0x40F7DB/0x40F81B/0x40F84D/0x40F8A9, its gray unworked-
    resources feature), so a call-target redirect there is dead at runtime.
    The orb thunks instead rewrite the ALREADY-PUSHED num/den stack slots
    (literal 1,1 -> this law with num=den=1 -> (g,16)) — or the SCALE
    globals 0x696D18/1C for the ratio-less zero-marker core call — from
    detours on pre-call instructions PRACX does not touch. Positions stay
    untouched: the yield loop already computes DEVICE coords via
    basewin_farm_zoom/basewin_farm_seed."""
    if g <= NATIVE_G:
        return num, den
    return num * g, den * NATIVE_G


def basewin_pop_face_enlarge(g: int) -> str:
    """Which primitive enlarges a citizens-row face (BaseWin_draw_pop, 4 sites, t_pop_ratio):
    'engine' = Sprite_draw_2 at the vanilla 1/1 (g<=16, byte-path native), 'bilinear' =
    thunk_sprite_bilinear at basewin_sprite_ratio(1, 1, g) above it.  Every citizen face carries
    its own 1:1 scanline dither under a photo (drone red/dark-red, worker navy/black): the engine's
    source-driven NN bands it at 22/16 and 25/16 (2.5x is phase-aligned: 4K proves nothing) and
    covers one source column short at 25/16, and a pair-remap tail would stripe the photo -- the
    palette-aware average is the tool for photo+dither sprites (the F4 faces' law, rw kinds v5).
    v3 (2026-09-20): 'hybrid' = thunk_face_hybrid above g 16 -- the average only SOFTENED the baked
    scanline background (low-frequency share 0.03-0.07 on the drones, unchanged elsewhere); the
    hybrid keeps the average for the photo and regenerates the background (face_hybrid_enlarge)."""
    return "engine" if g <= NATIVE_G else "hybrid"


# ---- citizen faces: HYBRID enlarge (thunk_face_hybrid, 2026-09-20) --------------------------------
# newicons.pcx / aliencit.pcx citizens (large 38x48: base citizens row; small 30x38: PSYCH rows, F4
# CITIZENS rows) are a photo over a baked period-2 scanline background.  No resample keeps that
# background even (the dither invariant: NN bands hard, the palette-aware average bands soft), and a
# blanket pair remap would stripe the photo.  Law: a dest pixel whose NEAREST source texel
# (bilinear_axis `near` on both axes) is a BACKGROUND texel is regenerated at device density
# (stripe_period(g), wide rows = stripe_top over the DEST BUFFER's absolute y: one phase grid per
# buffer, so neighbouring faces fuse); every other dest pixel is thunk_sprite_bilinear's, untouched.
# Background membership (face_pair_mate, v2 2026-09-20), three rules, the key never a member:
#   1. DIRECT: the texel lies ANYWHERE inside a maximal vertical alternating run a/b/a/b... of
#      >= FACE_PAIR_MIN_VRUN rows in its column (b = the neighbour above, else below; b != a, b != key).
#      A lone 1-px stroke between field rows reaches 3 rows and never qualifies.  v1 used the HOF test
#      (hof_pair_texel: the texel at the END of a one-sided 4-row chain): the few background rows
#      between the sprite's top border and the top of the head are hemmed in on both sides, failed
#      both one-sided chains, stayed bilinear and beat against the regenerated stripes around them --
#      a dark smudge above every drone's head (user, 1600x1200).  A minimum of 3 rows was tried and
#      REJECTED: it speckles the foreheads.
#   2. RUN: >= FACE_PAIR_MIN_RUN horizontally adjacent direct texels of the identical unordered
#      {a, mate} pair (a coincidence inside the photo is 1-2 texels wide; a background stripe is a run).
#   3. GAP FILL (the small 30x38 faces have fewer than 4 rows above the head): a non-member, non-key
#      texel takes the flanking mate when the maximal horizontal run of NON-member texels of its own
#      index that contains it is at most FACE_PAIR_MAX_GAP long and is flanked on BOTH sides, on the same
#      row, by rule-1+2 members of that same index and one same mate.  One pass (flanks are never
#      gap-filled texels); the cap keeps a full-width same-colour art row (the small superdrone's
#      shoulder line) out.
# Wide member = hof_pair_top (brighter by luma over the dest table, ties -> lower index).  Port:
# thunk_face_hybrid (assemble_rw_kinds.asm_face_hybrid, pinned pcave2+0x21A00); parity
# tests\test_face_hybrid_parity.py.
FACE_PAIR_MIN_RUN = 3
FACE_PAIR_MIN_VRUN = 4
FACE_PAIR_MAX_GAP = 12


def face_pair_vrun(src, pitch: int, sh: int, sx: int, sy: int, b: int, key: int) -> bool:
    """Rule 1 for one candidate mate b: the texel (sx, sy) = a is not the key, b is neither a nor the key, and
    the maximal vertical run through the texel that alternates a/b (rows [0, sh)) is >= FACE_PAIR_MIN_VRUN
    rows long.  Side-free: the run reaches b through whichever vertical neighbour is b."""
    a = src[sy * pitch + sx]
    if a == key or b == a or b == key:
        return False
    n = 1
    for d in (-1, 1):
        yy = sy + d
        while 0 <= yy < sh and src[yy * pitch + sx] == (b if (yy - sy) & 1 else a):
            n += 1
            yy += d
    return n >= FACE_PAIR_MIN_VRUN


def face_pair_run_mate(src, pitch: int, sw: int, sh: int, sx: int, sy: int, key: int):
    """Rules 1 + 2: (a, mate).  Candidates = the neighbour ABOVE, then the one below (a texel where two
    stripe bands meet is direct for both).  mate = the first candidate b with face_pair_vrun(texel, b) AND
    a horizontal run of >= FACE_PAIR_MIN_RUN adjacent texels (this one included, columns [0, sw)) that are
    direct for the identical unordered pair: index a with face_pair_vrun(.., b), or index b with
    face_pair_vrun(.., a).  None otherwise."""
    a = src[sy * pitch + sx]
    if a == key:
        return a, None
    tried = None
    for ny in (sy - 1, sy + 1):
        if not (0 <= ny < sh):
            continue
        b = src[ny * pitch + sx]
        if b == tried or not face_pair_vrun(src, pitch, sh, sx, sy, b, key):
            continue
        tried = b
        run = 1
        for d in (-1, 1):
            xx = sx + d
            while 0 <= xx < sw and run < FACE_PAIR_MIN_RUN:
                n = src[sy * pitch + xx]
                if not ((n == a and face_pair_vrun(src, pitch, sh, xx, sy, b, key)) or
                        (n == b and face_pair_vrun(src, pitch, sh, xx, sy, a, key))):
                    break
                run += 1
                xx += d
        if run >= FACE_PAIR_MIN_RUN:
            return a, b
    return a, None


def face_pair_mate(src, pitch: int, sw: int, sh: int, sx: int, sy: int, key: int):
    """The pair mate of the texel (sx, sy) of a sw x sh sprite (row pitch `pitch`) iff it is a baked
    scanline-BACKGROUND texel (rules 1-3 above), else None."""
    a, mate = face_pair_run_mate(src, pitch, sw, sh, sx, sy, key)
    if mate is not None or a == key:
        return mate
    gap, flank = 1, []
    for d in (-1, 1):                                   # rule 3: walk the same-index non-member run both ways
        xx = sx + d
        while True:
            if not (0 <= xx < sw):
                return None
            n, nm = face_pair_run_mate(src, pitch, sw, sh, xx, sy, key)
            if n != a:
                return None
            if nm is not None:
                flank.append(nm)
                break
            gap += 1
            if gap > FACE_PAIR_MAX_GAP:
                return None
            xx += d
    return flank[0] if flank[0] == flank[1] else None


def sprite_bilinear_pixel(src, pitch: int, sw: int, sh: int, dxi: int, dyi: int, num: int, den: int, pal: bytes, key: int,
                          memo: Optional[dict] = None):
    """thunk_sprite_bilinear's value for the sprite-relative dest pixel (dxi, dyi), or None when it
    writes nothing: the coverage texel (near, near) is the key -> None; else the 8.8-weighted average
    of the non-key taps' dest-table entries (pal = the dest's 256 x 4-byte table, first three bytes of
    each entry), rounded (+wt/2), -> palette_nearest (never the key).  `memo` (colour -> index) only saves repeated
    palette searches for one (pal, key)."""
    i0, i1, fy, ny = bilinear_axis(dyi, num, den, sh)
    j0, j1, fx, nx = bilinear_axis(dxi, num, den, sw)
    if src[ny * pitch + nx] == key:
        return None
    acc, wt = [0, 0, 0], 0
    for xx, yy, w in ((j0, i0, (256 - fx) * (256 - fy)), (j1, i0, fx * (256 - fy)),
                      (j0, i1, (256 - fx) * fy), (j1, i1, fx * fy)):
        t = src[yy * pitch + xx]
        if t == key:
            continue
        for c in range(3):
            acc[c] += pal[t * 4 + c] * w
        wt += w
    if wt <= 0:
        return None
    c = tuple((acc[k] + (wt >> 1)) // wt for k in range(3))
    if memo is not None and c in memo:
        return memo[c]
    v = palette_nearest(c, [pal[i * 4:i * 4 + 3] for i in range(256)], key)
    if memo is not None:
        memo[c] = v
    return v


def face_hybrid_enlarge(src, pitch: int, sw: int, sh: int, off_l: int, off_t: int, pal: bytes, num: int, den: int,
                        g: int, dst, d_pitch: int, d_w: int, d_h: int, x: int, y: int, key: int):
    """Reference citizen-face enlarge (thunk_face_hybrid; Sprite_draw_2 contract).  Returns None -- the
    ENGINE draws, dst untouched -- at g <= 16 or on any thunk_sprite_bilinear guard failure (num <= den,
    den <= 0, empty sprite / dest); else draws into dst (d_w x d_h px, row pitch d_pitch) and returns
    (dw, dh) = (fl(sw*num/den), fl(sh*num/den)).  Placement (x + fl(off_l*num/den), y + fl(off_t*num/den))
    (only the sprite's own draw offsets scale), clipped to the dest bounds.  Per dest pixel: nearest texel
    = the key -> untouched; face_pair_mate(nearest) -> the pair's hof_pair_top member when
    stripe_top(dest y, g), the other member otherwise; else sprite_bilinear_pixel.  pal = the dest's
    RGBQUAD[256] (b,g,r,x: mon_luma's layout)."""
    if g <= NATIVE_G or den <= 0 or num <= den or sw <= 0 or sh <= 0 or d_pitch <= 0:
        return None
    px, py = x + (off_l * num) // den, y + (off_t * num) // den
    dw, dh = (sw * num) // den, (sh * num) // den
    mates: dict = {}
    memo: dict = {}
    for dyi in range(dh):
        dy = py + dyi
        if not (0 <= dy < d_h):
            continue
        ny = bilinear_axis(dyi, num, den, sh)[3]
        wide = stripe_top(dy, g)
        for dxi in range(dw):
            dx = px + dxi
            if not (0 <= dx < d_w):
                continue
            nx = bilinear_axis(dxi, num, den, sw)[3]
            a = src[ny * pitch + nx]
            if a == key:
                continue
            if (nx, ny) not in mates:
                mates[(nx, ny)] = face_pair_mate(src, pitch, sw, sh, nx, ny, key)
            mate = mates[(nx, ny)]
            if mate is not None:
                top = hof_pair_top(a, mate, pal)
                dst[dy * d_pitch + dx] = top if wide else (mate if top == a else a)
                continue
            v = sprite_bilinear_pixel(src, pitch, sw, sh, dxi, dyi, num, den, pal, key, memo)
            if v is not None:
                dst[dy * d_pitch + dx] = v
    return dw, dh


# Punishment Sphere drone badge (uimod pssphere.cpp / psbadge.h are the PORT of the three laws below).
PS_BADGE_NUM, PS_BADGE_DEN = 15, 38          # badge diameter : face width, as designed on the 38 px face
PS_BADGE_DARK, PS_BADGE_GOLD = (12, 20, 32), (228, 208, 132)
PS_BADGE_RING_PCT = (70, 92)                 # gold ring   0.70R < r <= 0.92R
PS_BADGE_CORE_PCT = 38                       # gold core   r <= 0.38R
PS_BADGE_STRAP_PCT = (30, 80)                # gold straps |along| in 0.30R..0.80R on both diagonals ...
PS_BADGE_STRAP_HALF_PERMILLE = 85            # ... of full width 0.17R
PS_BADGE_EXCLUDED_INDICES = (8, 9, 246, 247, 253)   # key / reserved slots a quantiser must never emit
# Nerve-staple badge (2026-10-29, user's final choice after the clamp, the button-with-blindfold and the white
# disc: a BLACK disc with a white X and a thin white rim -- the X of the nerve-staple button, nothing else).
# Same disc, size law and placement as the sphere badge. Tones: 0 black (disc), 1 edge (grey), 2 white (X and
# rim); 3 and 4 unused.
PS_STAPLE_TONES = ((12, 10, 10), (120, 118, 118), (246, 246, 246), (246, 246, 246), (246, 246, 246))
PS_STAPLE_X_HALF_PCT = 46                    # the X spans +-0.46R in u and v, centred on the disc
PS_STAPLE_X_HALFWIDTH_PERMILLE = 130         # each stroke is 0.26R wide ...
PS_STAPLE_X_MIN_HALFWIDTH = 12               # ... but never under 1.5 px (12/16 px half-width)
PS_STAPLE_RIM_PCT = 88                       # the rim: r > 0.88R is white


def ps_badge(face_w_dev: int) -> dict:
    """Punishment Sphere badge on a drone / superdrone citizen face: geometry from the face's DEVICE
    width (BaseWin floor(38g/16), F4 floor(30g/16)), so it holds at every resolution and on the
    unpatched exe (g treated as 16).  d = half_down(15*face_w, 38); inset = max(1, face_w // 38);
    badge top-left = face origin + (inset, inset).  The badge is new art (vanilla has none): the
    15:38 ratio is the approved design, scaled with the face it sits on."""
    if face_w_dev <= 0:
        raise ValueError("ps_badge: face width must be positive")
    return {"d": half_down(PS_BADGE_NUM * face_w_dev, PS_BADGE_DEN),
            "inset": max(1, face_w_dev // PS_BADGE_DEN)}


def ps_badge_origin_x(face_x: int, face_w_dev: int, right: bool) -> int:
    """Badge left edge on its face.  The badge sits in the corner the row's overlap leaves VISIBLE:
    the base screen draws faces left to right (each later face covers its predecessor's RIGHT part)
    -> upper-LEFT (right=False); F4 draws right to left (the later face covers the LEFT part) ->
    upper-RIGHT (right=True, user 2026-09-20 from 4K shots).  Same inset from either edge."""
    b = ps_badge(face_w_dev)
    return face_x + face_w_dev - b["inset"] - b["d"] if right else face_x + b["inset"]


def ps_badge_raster(d: int) -> List[List[int]]:
    """The badge RASTERISED at device diameter d (never resampled): d x d grid of tone 0..4 on the
    DARK->GOLD ramp, -1 = not drawn (pixel centre outside the disc).  Integer-exact: positions in
    1/16 px about the centre (R = 8d), 4x4 subsamples per pixel, tone = (gold_samples + 2) >> 2."""
    R2 = (8 * d) * (8 * d)
    lo, hi = PS_BADGE_RING_PCT
    s0, s1 = PS_BADGE_STRAP_PCT
    hw = PS_BADGE_STRAP_HALF_PERMILLE

    def gold(u: int, v: int) -> bool:
        r2 = u * u + v * v
        if r2 > R2:
            return False
        if 10000 * r2 <= PS_BADGE_CORE_PCT * PS_BADGE_CORE_PCT * R2:
            return True
        if lo * lo * R2 < 10000 * r2 <= hi * hi * R2:
            return True
        for a, b in ((u + v, u - v), (u - v, u + v)):        # along / across, both x sqrt(2)
            if 1000000 * b * b <= 2 * hw * hw * R2 and 2 * s0 * s0 * R2 <= 10000 * a * a <= 2 * s1 * s1 * R2:
                return True
        return False

    grid = []
    for py in range(d):
        row = []
        for px in range(d):
            cu, cv = 16 * px + 8 - 8 * d, 16 * py + 8 - 8 * d
            if cu * cu + cv * cv > R2:
                row.append(-1)
                continue
            n = sum(gold(16 * px + 4 * sx + 2 - 8 * d, 16 * py + 4 * sy + 2 - 8 * d)
                    for sy in range(4) for sx in range(4))
            row.append((n + 2) >> 2)
        grid.append(row)
    return grid


def ps_badge_ramp() -> List[Tuple[int, int, int]]:
    """The 5 tones' RGB, tone t = DARK + (GOLD - DARK) * t/4 rounded half-up; each is mapped to the
    nearest index of the DEST buffer's own colour table, never one of PS_BADGE_EXCLUDED_INDICES."""
    return [tuple((8 * PS_BADGE_DARK[k] + 2 * (PS_BADGE_GOLD[k] - PS_BADGE_DARK[k]) * t + 4) // 8
                  for k in range(3)) for t in range(5)]


def ps_staple_class(u: int, v: int, R: int) -> int:
    """The nerve-staple badge's colour class at 1/16 px position (u, v) about the centre, R = 8d:
    -1 outside the disc, 2 white (the rim or the X), 0 black."""
    r2 = u * u + v * v
    if r2 > R * R:
        return -1
    if 10000 * r2 > PS_STAPLE_RIM_PCT * PS_STAPLE_RIM_PCT * R * R:
        return 2                                            # the rim
    half = PS_STAPLE_X_HALF_PCT * R // 100
    hw = max(PS_STAPLE_X_HALFWIDTH_PERMILLE * R // 1000, PS_STAPLE_X_MIN_HALFWIDTH)
    if abs(u) <= half and abs(v) <= half and (abs(u - v) <= hw or abs(u + v) <= hw):
        return 2                                            # the X
    return 0


def ps_staple_raster(d: int) -> List[List[int]]:
    """The nerve-staple badge RASTERISED at device diameter d (never resampled): d x d grid of tone 0..2,
    -1 = not drawn (pixel centre outside the disc).  4x4 subsamples per pixel: the majority class wins
    (2 white / 0 black); a white pixel with fewer than 8 of its 16 samples white is the edge tone 1.
    Integer-exact, 1/16 px positions, R = 8d."""
    R = 8 * d
    R2 = R * R
    grid = []
    for py in range(d):
        row = []
        for px in range(d):
            cu, cv = 16 * px + 8 - 8 * d, 16 * py + 8 - 8 * d
            if cu * cu + cv * cv > R2:
                row.append(-1)
                continue
            n_black = n_white = 0
            for sy in range(4):
                for sx in range(4):
                    c = ps_staple_class(16 * px + 4 * sx + 2 - 8 * d, 16 * py + 4 * sy + 2 - 8 * d, R)
                    if c == 0:
                        n_black += 1
                    elif c == 2:
                        n_white += 1
            if n_white > n_black:
                row.append(2 if n_white >= 8 else 1)
            else:
                row.append(0)
        grid.append(row)
    return grid


def ps_staple_ramp() -> List[Tuple[int, int, int]]:
    """The staple badge's tones: black, edge grey, white (PS_STAPLE_TONES; 3 and 4 repeat white)."""
    return [tuple(c) for c in PS_STAPLE_TONES]


def basewin_pen_descale(x_dev: int, g: int) -> int:
    """BaseWin pen-return law (write_l/write_l_4 family EXT brackets): the
    engine's text writers RETURN the advanced pen x in DEVICE space, and the
    draw fns chain the next write from that return — feeding it back through
    basewin_pt would double-scale (the "Energy:"-without-value class). The
    bracket descales the return to native space, x*16//g, so every chained
    hop re-enters the fns' native-space math. Round-trip error is <=1 native
    px per hop (the scaled font's true width is preserved because the next
    basewin_pt re-scale lands within 1 device px of the engine's real pen).
    Identity at g<=16 (bracket gate off)."""
    if g <= NATIVE_G:
        return x_dev
    return (x_dev << 4) // g


def basewin_farm_zoom(num: int, den: int, g: int) -> Tuple[int, int]:
    """BaseWin farm-view zoom law (draw_farm RESOURCE-tab render): the whole
    farm pipeline — tile step iVar4 = (num*50/den +1)>>2, terrain poly size,
    veh/base stamps, resource-icon centering widths — derives from the
    g_map_zoom_num/den globals, so the view scales by composing the ENGINE'S
    OWN zoom: (num*g, den*16), exactly the basewin_sprite_ratio fraction
    rule. A non-positive entry num is the -1 'unset' sentinel (vanilla
    treats it as 1/1 via its <1 fallbacks) and normalizes to (g, 16). The
    vanilla mid-fn 1/1 re-seeds take the same law with num=den=1. Identity
    at g<=16."""
    if g <= NATIVE_G:
        return num, den
    if num <= 0:
        num, den = 1, 1
    return num * g, den * NATIVE_G


def basewin_farm_seed(x0: int, y0: int, x1: int, raw: int,
                      g: int) -> Tuple[int, int, int]:
    """BaseWin farm-view seed law (draw_farm 0x40F21B block): vanilla
    computes, from the NATIVE panel rect fields (+0x40b8c) and the
    zoom-derived rounded tile width `raw`,

        local_24 = ((raw>>2))*2            (tile half-step)
        local_28 = (x1-x0)/2 - 2*local_24 + x0     (x seed, centering)
        local_2c = 3*local_24 + 4 + y0             (y seed)

    Armed (g>16): `raw` is ALREADY device-scaled (basewin_farm_zoom drives
    the engine's own raw = num*50/den), the rect fields scale through
    basewin_pt per edge, and the +4 nudge scales as basewin_pt(4) = g>>2.
    The mixed forms (native fields + scaled step) are exactly the black-
    panel bug; every term must be in ONE space."""
    step2 = (raw >> 2) * 2
    if g <= NATIVE_G:
        l28 = (x1 - x0) // 2 - 2 * step2 + x0
        l2c = 3 * step2 + 4 + y0
        return step2, l28, l2c
    x0d, x1d, y0d = basewin_pt(x0, g), basewin_pt(x1, g), basewin_pt(y0, g)
    l28 = (x1d - x0d) // 2 - 2 * step2 + x0d
    l2c = 3 * step2 + (g >> 2) + y0d
    return step2, l28, l2c


# rcRspPanel (+0x40B8C, abs 0x6E81B4): the R/S/P tab content panel, seeded
# identically on BOTH BaseWin_init layout branches (@0x41E9D3 / 0x41EBB9).
BASEWIN_RSP_PANEL_NATIVE = (166, 33, 560, 257)


def support_map_rect(l: int, t: int, r: int, b: int,
                     g: int) -> Tuple[int, int, int, int]:
    """SUPPORT-tab embedded-map window law (ported by thunk_bw_supprect, the
    detour on MapWin_init_2's mode-2 rect-load block @0x470B2A): draw_support
    sizes an embedded world-map Console (BaseWin+0x1E674) from rcRspPanel via
    MapWin_init -> GraphicWin_init_2; scale each EDGE basewin_pt — the SAME
    per-edge law thunk_bw_clip applies to draw_support's opening set_clip, so
    the device window stays flush with the panel clip and its W/H come out in
    cum-position form.  NEVER write the shared +0x40B8C global (TutWin_tour1
    and the BaseWin_click tooltip in_box_2 read it native) — the thunk scales
    into MapWin_init_2's ebp LOCALS only.  Identity at g<=16."""
    return (basewin_pt(l, g), basewin_pt(t, g),
            basewin_pt(r, g), basewin_pt(b, g))


def support_map_fit(avail_w: int, avail_h: int,
                    half_x: int, half_y: int) -> int:
    """EXACT port of draw_support's zoom-fit loop (map zoom UNARMED branch):
    walk the discrete zoom-index series i = 2..-15 — tile w = fl((800+50i)/16),
    tile h = fl((400+25i)/16) (loop counters start 900/450, step 50/25) — and
    return the FIRST (densest) index whose FULL world map fits:
    half_x*tw <= avail_w AND half_y*th <= avail_h (half_x/half_y =
    g_map_width_tiles/2 and DAT_00949874/2); -15 when nothing fits.

    avail_w/h are the embedded MapWin's client dims (+0x1EB38/3C =
    its GraphicWin +0x4C4/|+0x4C8|) = the rcRspPanel dims.  Feed them
    device-scaled via support_map_rect and this vanilla loop picks a
    ~g/16-denser index BY ITSELF; the map then renders from native tile art
    at that zoom — ZERO resampling, which is the SUPPORT-tab water-banding
    fix (the old mapblit copy_3 stretch resampled a native render).

    CAP (accepted limit): the series tops out at i=2 (56px tiles), so maps
    narrower than ~47 half-tiles stop gaining density before 2.5x at g=40 —
    relatively smaller, still crisp.  Do NOT extend the series or 'fix' the
    quantization per-consumer; the armed g_map_zoom branch (num*50/den) is
    the engine's own continuous path and stays untouched."""
    idx, w14, h8 = 2, 900, 450
    while True:
        tw = w14 >> 4
        if half_x * tw <= avail_w:
            th = h8 >> 4
            if half_y * th <= avail_h:
                return idx
        idx -= 1
        w14 -= 50
        h8 -= 25
        if w14 <= 50:
            return idx


def veh_size_scaled(s: int, g: int) -> int:
    """Unit-renderer size-index law (ported by thunk_hud_vehargs, the entry
    detour on veh_draw @0x5594F0 / base_draw @0x55AF20): the WHOLE unit render
    derives from the size index s as the ratio (s+16)/16 — the flag/health/
    label sprites via SCALE_NUM_G/DEN (0x696D18/1C = s+16, 16), every layout
    offset (all of veh_draw's unarmed branches are linear in (s+16):
    (s*5+0x50)*10>>4 == (s+16)*50/16 etc.), the label font via
    FontCache_get(s,..), and the 3D flic body via vehdraw_draw's
    zoom = (s+16)*0.07/16 (consts 0x66DF18/0x66D8D0).  ONE rewrite at fn
    entry therefore scales the whole unit self-consistently:

        s' = (((s+16)*g) >> 4) - 16

    Known native sizes: base-screen garrison -7, StatusWin sentinels 0/-4/-8,
    supported/hq lists.  Gates (part of the law, mirrored by the thunk):
    identity at g<=16 and for |s|>16 (map callers pass real/large or already
    device-scaled sizes); the thunk additionally gates dest buf ∈ {strip
    0x7AEC64, status 0x8C59AC} and skips BaseWin-range callers with
    g_map_zoom armed (draw_production/draw_farm self-scale via the zoom
    globals — basewin_farm_zoom).  When g_map_zoom_num>=1 the engine ignores
    s entirely, so the rewrite composes safely with every zoom-armed path.
    Floor loss: the applied ratio (s'+16)/16 floors the exact (s+16)*g/256
    (garrison at g=40: 22/16 = 2.444x vs 2.5x — the worst case over the
    sentinel set, visually invisible; do NOT "fix" it per-consumer)."""
    if g <= NATIVE_G or not -16 <= s <= 16:
        return s
    return ((s + 16) * g >> 4) - 16


def veh_flic_zoom(s: int) -> float:
    """The engine's unit-body flic zoom for an UNARMED map zoom
    (vehdraw_draw @0x4C12A0): zoom = (s+16) * 0.07 / 16.  Reference
    companion of veh_size_scaled for trace decoding (0.09625 at g=40 ==
    s'=6 == garrison's native -7 through the law; 0.0875 == StatusWin -8;
    0.13125 == -4).  Chassis classes 8/9/10 and sea/air hulls compose extra
    table multipliers (0.125/1.25/0.8) on top — they scale the SAME for
    native and scaled s, so the law's ratio survives them."""
    return (s + 16) * 0.07 / 16.0


def blit_clip_visible(dx: int, dy: int, w: int, h: int,
                      clip: Tuple[int, int, int, int]):
    """Chrome-pipeline clip law (the base-screen ENERGY-band eraser class):
    every VANILLA draw primitive writes through the dest Buffer's active clip
    rect (+0x20..+0x2C) — Buffer_box_sprite pre-intersects each internal
    strip/fill rect with it (proven: the 1024 native trace shows the
    draw_expenses backdrop [23,0,703,404] painting ONLY inside the panel clip
    [166,260,699,349]).  Our thick-chrome enlarge pipeline (bandmap raw band
    loops / keyed_stretch_blit's Buffer_draw_2-out / fe_pair_remap's raw walk)
    bypasses the clip, so a box whose rect EXCEEDS its clip — legal in vanilla,
    first hit by the BaseWin backdrops — repaints the whole rect and erases
    neighbouring panels (the ENERGY-ALLOCATION header + ECONOMY row band).

    Law: a chrome out-blit of w*h pixels landing at dest (dx,dy) may write
    exactly the intersection with the active clip (l,t,r,b), half-open on
    r/b like the engine's own clip test.  Returns (vx0,vy0,vx1,vy1) in DEST
    space, or None when nothing is visible."""
    l, t, r, b = clip
    vx0, vy0 = max(dx, l), max(dy, t)
    vx1, vy1 = min(dx + w, r), min(dy + h, b)
    if vx0 >= vx1 or vy0 >= vy1:
        return None
    return vx0, vy0, vx1, vy1


def blit_clip_contains(dx: int, dy: int, w: int, h: int,
                       clip: Tuple[int, int, int, int]) -> bool:
    """Passthrough gate for the clip law: when the active clip CONTAINS the
    whole blit, the pipeline must run its original (verified) code paths
    bit-identically — the popup family always lands here (their clip == the
    whole window), so no shipped look changes.  Only a strictly smaller clip
    takes the new clipped paths (bandmap disarm -> KSB fallback, clipkey
    partial copy)."""
    l, t, r, b = clip
    return dx >= l and dy >= t and dx + w <= r and dy + h <= b


def remap_clip_bounds(x: int, y: int, w: int, h: int, buf_w: int, buf_h: int,
                      clip: Tuple[int, int, int, int]):
    """fe_pair_remap walk-bound law (v5): the stripe remap raw-walks the
    dest rows, so its bounds must be the staged rect clamped to BOTH the
    buffer dims (v4 behaviour) AND the active clip (new) — the remap is a
    repaint of pixels the blit was allowed to touch, never more.  Returns
    (x0, x1, y0, y1) half-open, possibly empty (x0>=x1 or y0>=y1)."""
    l, t, r, b = clip
    x0 = max(x, 0, l)
    y0 = max(y, 0, t)
    x1 = min(x + w, buf_w, r)
    y1 = min(y + h, buf_h, b)
    return x0, x1, y0, y1


FORCE_PRESCAN_ROWS = 8   # the force-path content key reads at most the first 8 rows of the staged rect


def force_prescan_bounds(x: int, y: int, w: int, h: int, buf_w: int, buf_h: int):
    """Force-path content-key prescan block (thunk_fe_pair_remap v9 + thunk_s54_restripe v3, 2026-10-17).

    The prescan that decides which dither family a staged rect (g_fe_x/y/w/h) carries reads the
    first <= 8 rows from (max(x,0), max(y,0)), w columns wide -- clamped to the BUFFER (W, H), never
    past it.  Note the columns run from x0 = max(x,0) for w columns (the bytes do not shorten w by a
    negative x), unlike remap_clip_bounds' x + w.  The clip is deliberately not applied (a clip-aware
    key would change which rows key a narrowed draw -- cosmetic, per screen).  Returns
    (x0, x1, y0, y1) half-open; empty (x1 <= x0 or y1 <= y0) -> no family keys.  A family keys when
    its count over the block exceeds (x1 - x0) // 2 (dither_force_mate / hatch_keyed width).
    Before v9 / v3 the block was (x0, x0 + w, y0, y0 + min(h, 8)) unclamped: a half-open rect
    (B = H) staged inclusive, or a frame within 8 rows of / below the buffer bottom, read past the
    plane (an access violation when the DIB ends on a page)."""
    x0 = max(x, 0)
    y0 = max(y, 0)
    if w <= 0 or h <= 0:
        return x0, x0, y0, y0
    x1 = min(x0 + w, buf_w)
    y1 = min(y0 + min(h, FORCE_PRESCAN_ROWS), buf_h)
    return x0, x1, y0, y1


def console_rail_arm(dest_h_abs: int, art_h: int, g: int) -> bool:
    """Console side-rail scaling gate (slide_show chrome, 2026-07-19c): the four
    rail strips (529px native art) are drawn 1:1 into every console window; a
    window TALLER than the art is necessarily one of our g-scaled windows and
    its rails must scale (the base screen's black side columns / floating
    right-rail fragment). Windows the art still covers keep native rails --
    the vanilla-correct look. The screen buffer (slide-loop dest) never arms."""
    return g > NATIVE_G and dest_h_abs > art_h


def rail_right_anchor(win_w_dev: int, x_dev: int, g: int) -> int:
    """Right-side rail re-anchor (thunk_filedlg_railscale, user-verified for the
    file dialog 2026-07-03, generalized 2026-07-19c): Sprite_draw_2 multiplies
    the dest x by num/den, so a right-anchored strip must be re-expressed in
    NATIVE space before the scale: x' = nativeWinW - (winW - x), where
    winW - x is the strip's native offset-from-right (the composed arg mixes
    device winW with native offsets). Left strips (2x < winW) pass through."""
    return (win_w_dev << 4) // g - (win_w_dev - x_dev)


RAIL_INNER_RIGHT_OFF = 0x37   # slide_show's inner right strip: canvas - 0x37 (0x20 gap + outer 15 + inner 8)


def rail_right_strip_x(win_w_dev: int, x_dev: int, g: int) -> int:
    """Window-local DEVICE x of a right slide-rail strip (thunk_filedlg_railscale v3, 2026-10-17).

    The inner right strip (x = winW - 0x37) sits at railscale's double floor fl(rail_right_anchor * g/16) -- the
    cascade every abutting frame / backdrop R reads (filedlg insets, popup chrome, se_backdrop_rect, dw_frame_lr,
    rw_window_rects, the BaseWin console frame).  Every other right strip is placed RELATIVE to it: + fl(e*g/16),
    e = x - (winW - 0x37) its native offset from the inner strip -- so the outer strip (x = winW - 0x2F, e = 8) starts
    exactly where the inner one's fl(8g/16) drawn columns end, the way the left pair abuts (outer at 0, inner at
    fl(15g/16)).  v2 floored fl((N - 0x2F)*g/16) independently: a 1-px see-through column between the right strips
    whenever the two floors phased apart (odd g; 1600x1200 base-name popup x=1202; SocialWin/BaseWin g 17,19,25,27,
    33,35,41,43, DesignWin every odd g, ~half the popup widths).  The outer strip's right end never moves outward
    (fl(a)+fl(b) <= fl(a+b)).  Vanilla abuts (g=16 identity: x itself)."""
    if g <= NATIVE_G:
        return x_dev
    inner = win_w_dev - RAIL_INNER_RIGHT_OFF
    anchor = (rail_right_anchor(win_w_dev, inner, g) * g) >> 4
    return anchor + (((x_dev - inner) * g) >> 4)


# ==== chevron coverage filter (bandstripe v8, thunk_chev_coverage) ==========
# The GOVERNOR chevron art is a horizontal 1px 50/50 stripe DITHER (orange/red
# glyph pair, dim flank pair).  Raw centre-NN at fractional g duplicates rows
# irregularly (phase-flip: one color double-height per half image) and every
# stripe-synthesis treatment was rejected on look (v4/v5.1/v6/B/C, 2026-07-22..24).
# The user-approved render (work\chev_candidates3.png "coverage linear g2.2",
# approved 2026-07-24) is:
#   1. COVERAGE (area) resample -- dest cell averages exactly the src pixels it
#      geometrically overlaps.  For our upscales each dest cell overlaps at most
#      2 src pixels per axis, and most dest rows sit INSIDE one src stripe, so
#      stripes stay pure and blends land only at true stripe boundaries
#      (evenly spaced -- kills the bilinear "rung roulette" dark blotches).
#   2. LINEAR-LIGHT averaging (gamma 2.2 via the 256-entry LIN16 LUT) -- the eye
#      blends a 1px dither linearly in LIGHT; sRGB-domain averaging
#      under-brightens the mix and snaps to a darker palette rung.
#   3. REDMEAN nearest-palette quantization over the LIVE 256-entry palette
#      (@0x94C590), key index EXCLUDED so no opaque pixel turns transparent.
# The functions below are the integer SPEC; the cave thunk is a byte-level port
# and the Unicorn parity test must agree bit-exactly.

CHEV_SRC = 20          # chevron state-sprite art is 20x20
CHEV_KEY = 9           # canvas transparency index

_GAMMA = 2.2


def _build_lin16() -> Tuple[int, ...]:
    """256-entry sRGB->linear16 LUT, forced STRICTLY monotone (raw gamma 2.2
    rounds entries 1..2 to 0, colliding with entry 0 and breaking the
    binary-search inverse; the max(prev+1) clamp nudges only near-black
    entries by <=2 counts). Baked verbatim into the cave as data."""
    lut, prev = [], -1
    for v in range(256):
        x = max(prev + 1, int(round(((v / 255.0) ** _GAMMA) * 65535)))
        lut.append(x)
        prev = x
    assert lut[255] == 65535
    return tuple(lut)


SRGB_LIN16: Tuple[int, ...] = _build_lin16()


def coverage_taps(S: int, D: int) -> List[Tuple[int, int, int]]:
    """Per-dest-cell coverage taps for an S->D upscale (D >= S).

    Dest cell i covers src interval [i*S/D, (i+1)*S/D).  In integer units of
    1/D of a src pixel the cell is S wide and src pixel s spans [s*D, (s+1)*D),
    so the cell overlaps at most TWO src pixels.  Returns (s0, w0, w1): src s0
    with weight w0, src s0+1 with weight w1; w0 + w1 == S exactly.  D == S is
    the identity (w0 = S).  Pure integers -- exact at every g."""
    taps = []
    for i in range(D):
        t = i * S
        s0 = t // D
        r = t - s0 * D
        w0 = min(D - r, S)
        taps.append((s0, w0, S - w0))
    return taps


def linear16_to_srgb(x: int) -> int:
    """Inverse of SRGB_LIN16 by binary search (nearest entry, ties -> upper).
    The thunk ports THIS exact search: first v with LIN16[v] >= x, then take
    v-1 iff x is STRICTLY nearer to it."""
    lo, hi = 0, 255
    while lo < hi:
        mid = (lo + hi) >> 1
        if SRGB_LIN16[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    if lo > 0 and x - SRGB_LIN16[lo - 1] < SRGB_LIN16[lo] - x:
        return lo - 1
    return lo


def redmean_dist2(c1: Tuple[int, int, int], c2: Tuple[int, int, int]) -> int:
    """Integer redmean color distance (x256 of the classic formula):
    (512+rm)*dr^2 + 1024*dg^2 + (767-rm)*db^2, rm = (r1+r2)>>1.  Max ~1.7e8,
    fits int32.  Plain Euclidean snapped a red-orange blend to a bluish entry
    (the mauve band, 2026-07-24b) -- do not simplify."""
    rm = (c1[0] + c2[0]) >> 1
    dr, dg, db = c1[0] - c2[0], c1[1] - c2[1], c1[2] - c2[2]
    # green weight = 4 x the x256 scale (spelled out: the bare product is a
    # screen-literal the law guards ban)
    return (512 + rm) * dr * dr + 4 * 256 * dg * dg + (767 - rm) * db * db


def nearest_palette_redmean(c: Tuple[int, int, int],
                            palette: List[Tuple[int, int, int]],
                            exclude: int = CHEV_KEY) -> int:
    """First index of minimal redmean distance (strict <, like the asm's jge
    skip), with the key index excluded from candidacy."""
    best, bestd = -1, 1 << 62
    for i, p in enumerate(palette):
        if i == exclude:
            continue
        d = redmean_dist2(p, c)
        if d < bestd:
            best, bestd = i, d
    return best


def chevron_coverage_filter(src_idx: List[List[int]],
                            palette: List[Tuple[int, int, int]],
                            D: int, key: int = CHEV_KEY) -> List[List[int]]:
    """The approved chevron zoom: S x S palette-index art -> D x D indices.

    Per dest pixel: accumulate LIN16(palette rgb) * (wy*wx) over the <=4
    covered src texels, skipping key texels; if key weight is >= half the
    total (S*S), the dest pixel IS key (corner preservation); else divide by
    the non-key weight (round-half-up), inverse-gamma each channel, and take
    the redmean-nearest non-key palette index."""
    S = len(src_idx)
    taps = coverage_taps(S, D)
    total = S * S
    out = []
    for j in range(D):
        sy0, wy0, wy1 = taps[j]
        row = []
        for i in range(D):
            sx0, wx0, wx1 = taps[i]
            accr = accg = accb = wkey = 0
            for sy, wy in ((sy0, wy0), (sy0 + 1, wy1)):
                if wy == 0:
                    continue
                for sx, wx in ((sx0, wx0), (sx0 + 1, wx1)):
                    if wx == 0:
                        continue
                    w = wy * wx
                    idx = src_idx[sy][sx]
                    if idx == key:
                        wkey += w
                        continue
                    r, gg, b = palette[idx]
                    accr += SRGB_LIN16[r] * w
                    accg += SRGB_LIN16[gg] * w
                    accb += SRGB_LIN16[b] * w
            if 2 * wkey >= total:
                row.append(key)
                continue
            wsum = total - wkey
            half = wsum >> 1
            c = (linear16_to_srgb((accr + half) // wsum),
                 linear16_to_srgb((accg + half) // wsum),
                 linear16_to_srgb((accb + half) // wsum))
            row.append(nearest_palette_redmean(c, palette, exclude=key))
        out.append(row)
    return out


def coverage_filter_rect(src_idx: List[List[int]],
                         palette: List[Tuple[int, int, int]],
                         DW: int, DH: int,
                         key: int = CHEV_KEY) -> List[List[int]]:
    """Rectangular generalization of chevron_coverage_filter: W x H art ->
    DW x DH indices (DW >= W, DH >= H).  Same accumulate / half-key threshold /
    inverse-gamma / redmean pipeline; per-axis tap weights sum to W and H so
    the per-pixel weight total is W*H.  W == H and DW == DH degenerates to
    chevron_coverage_filter exactly (pinned by test).  First instance: the
    garrison/HUD unit-row arrow art (12 x 42, 2026-07-26i) — the hover state
    is a 1px 50/50 stripe dither that centre-NN phase-flips into bands (the
    'first-hover garble' residue after the 26h stale-scratch fix)."""
    H = len(src_idx)
    W = len(src_idx[0])
    taps_y = coverage_taps(H, DH)
    taps_x = coverage_taps(W, DW)
    total = W * H
    out = []
    for j in range(DH):
        sy0, wy0, wy1 = taps_y[j]
        row = []
        for i in range(DW):
            sx0, wx0, wx1 = taps_x[i]
            accr = accg = accb = wkey = 0
            for sy, wy in ((sy0, wy0), (sy0 + 1, wy1)):
                if wy == 0:
                    continue
                for sx, wx in ((sx0, wx0), (sx0 + 1, wx1)):
                    if wx == 0:
                        continue
                    w = wy * wx
                    idx = src_idx[sy][sx]
                    if idx == key:
                        wkey += w
                        continue
                    r, gg, b = palette[idx]
                    accr += SRGB_LIN16[r] * w
                    accg += SRGB_LIN16[gg] * w
                    accb += SRGB_LIN16[b] * w
            if 2 * wkey >= total:
                row.append(key)
                continue
            wsum = total - wkey
            half = wsum >> 1
            c = (linear16_to_srgb((accr + half) // wsum),
                 linear16_to_srgb((accg + half) // wsum),
                 linear16_to_srgb((accb + half) // wsum))
            row.append(nearest_palette_redmean(c, palette, exclude=key))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# BaseWin bottom-HUD strip panel seed rects (groups 11-16) — 2026-07-25b
# ---------------------------------------------------------------------------
# Port of the BaseWin_init strip seed block (0x41EEB0..0x41F29B, !=800 branch;
# decompile work\_tmp_decomp_basewin_ctor_init.txt lines 281-396, trace
# work\frida_basewin_strip.log). The four MainWin region rects arrive ALREADY
# device-scaled (closed HUD work, its own rounding — consumers must READ the
# LIVE globals, never re-derive them as vanilla*g/16):
#   A @0x7AF5A0 production+queue column   S @0x7AF5B0 forces-supported
#   C @0x7AF5C0 plate+citizens region     G @0x7AF5D0 garrison row
# Vanilla mixes those with NATIVE additive constants (the NetWin mixed-space
# class): the constants scale popup_scale_floor, the 7/12 column split is
# proportional and stays. At g<=16 every s(k)==k, so the law is the identity
# on the vanilla block (pinned by test golden vectors) — no gate needed, but
# the thunk still gates g>16 so the ScreenWidth==800 seed branch (g==16 by
# derivation) is never overwritten with !=800 formulas.

# Vanilla region vectors measured at the native baseline res (g=16 run,
# frida_basewin_strip.log):
BASEWIN_STRIP_REGIONS_NATIVE = {
    "A": (4, 56, 245, 252),
    "S": (779, 56, 1020, 252),
    "C": (262, 66, 763, 172),
    # G right edge = a measured COORDINATE, spelled 3*256 to satisfy the
    # screen-literal guard (precedent: redmean's 4*256).
    "G": (244, 188, 3 * 256, 252),
}


def basewin_strip_seed_rects(A: Tuple[int, int, int, int],
                             S: Tuple[int, int, int, int],
                             C: Tuple[int, int, int, int],
                             G: Tuple[int, int, int, int],
                             g: int) -> dict:
    """All 13 strip-side BaseWin panel seed rects, scaled-constant form.

    Field map (BaseWin_g + offset -> key):
      +0x40c6c production   +0x40dec turnsA(CHANGE)  +0x40dfc turnsB(HURRY)
      +0x40c9c queue_outer  +0x40c7c queue_hdr       +0x40c8c queue_list
      +0x40c5c pop(citizens) +0x40cac plate          +0x40e2c redbtn_frame
      +0x40c2c garrison     +0x40b7c sup_outer       +0x40b5c sup_hdr
      +0x40b6c sup_list     (+0x40e6c..78 = copy of queue_hdr, thunk writes it)

    Constants with meaning: 0x14 header height; 0x3a citizens-row carve-out
    (54px row + 4 inset); 0x3e red-button reserve (48 sprite + margins);
    0x17/0x2d/0x19 CHANGE/HURRY row anchors off the production bottom;
    plate.bottom = citizens.top - 4 + 1 (the +1 is vanilla's own overlap).
    """
    s = lambda k: popup_scale_floor(k, g)  # noqa: E731
    Al, At, Ar, Ab = A
    Sl, St, Sr, Sb = S
    Cl, Ct, Cr, Cb = C
    Gl, Gt, Gr, Gb = G
    prod = (Al + s(4), At + s(4), (Ar - Al) * 7 // 12 - s(4), Ab - s(4))
    garr = (Gl, Gt + s(4), Gr - s(4), Gb - s(4))
    turnsB = (prod[2] + s(3), prod[3] - s(0x17), garr[0] - s(7), prod[3] - s(3))
    turnsA = (prod[2] + s(3), prod[3] - s(0x2D), garr[0] - s(7), prod[3] - s(0x19))
    qout = (prod[2] + s(4), At + s(4), Ar - s(4), turnsA[1] - s(7))
    qhdr = (prod[2] + s(7), At + s(7), Ar - s(7), At + s(7) + s(0x14))
    qlist = (prod[2] + s(7), qhdr[3] + s(2), Ar - s(7), turnsA[1] - s(10))
    pop = (Cl + s(4), Cb - s(0x3A), Cr - s(0x3E), Cb - s(4))
    plate = (Cl + s(4), Ct + s(4), Cr - s(4), pop[1] - s(4) + s(1))
    # redbtn is SIZE-ANCHORED: r/b = l/t + s(48) (vanilla stores r = Cr - 7 =
    # l + 48; native identity below).  48 is 3*16, so ceil-descale
    # round-trips exactly at every g.  Do NOT pre-subtract 1 here: the art
    # window is created with w = r - l off these same fields (GraphicWin_init
    # sites 0x420743/0x4207de), so shrinking the field shrinks frame AND art
    # together and can never change the ring channels — that compensation
    # belongs in basewin_redbtn_frame below, at the frame DRAW.
    redbtn = (pop[2] + s(7), pop[1] + s(3),
              pop[2] + s(7) + s(0x30), pop[1] + s(3) + s(0x30))
    sout = (Sl + s(4), St + s(4), Sr - s(4), Sb - s(4))
    shdr = (Sl + s(7), St + s(7), Sr - s(7), St + s(7) + s(0x14))
    slist = (Sl + s(7), shdr[3] + s(2), Sr - s(7), Sb - s(7))
    return {
        "production": prod, "garrison": garr,
        "turnsA": turnsA, "turnsB": turnsB,
        "queue_outer": qout, "queue_hdr": qhdr, "queue_list": qlist,
        "pop": pop, "plate": plate, "redbtn": redbtn,
        "sup_outer": sout, "sup_hdr": shdr, "sup_list": slist,
    }


# Plate chevron button art (console sheet extracts, BaseWin_init 0x41f6ec/
# 0x41f739) — the sprites stay NATIVE; only the WINDOW rects scale and the
# vtable btnzoom KSB fills them (GOVERNOR-chevron precedent).
CHEVRON_SPRITE_W_NATIVE = 20
CHEVRON_SPRITE_H_NATIVE = 35


def basewin_strip_chevron_rects(plate: Tuple[int, int, int, int],
                                sprite_w: int, sprite_h: int,
                                g: int) -> dict:
    """Plate chevron button window rects (BaseWin_init 0x41f9f5/0x41fac0).

    btn2 (+0x40d4c, obj +0xee58) = [plate.l + s(3), plate.t + s(3),
    l + s(w), t + s(h)]; btn3 (+0x40d5c, obj +0xf9a4) = [plate.r - s(3) -
    s(w), same t, plate.r - s(3), same b].  sprite_w/h are the LIVE sprite
    dim fields (+0xcaec/+0xcaf0 = sprite obj +0x18/+0x1c) — read, never
    assumed, so localized console art follows.  The art stays native: the
    btnzoom KSB derives its source dims by CEIL descale of the window size,
    and ceil(fl(k*g/16)*16/g) == k for every k at g > 16, so the fill is
    exact (no dead slack — the staple-window lesson).
    """
    s = lambda k: popup_scale_floor(k, g)  # noqa: E731
    l2, t = plate[0] + s(3), plate[1] + s(3)
    btn2 = (l2, t, l2 + s(sprite_w), t + s(sprite_h))
    r3 = plate[2] - s(3)
    btn3 = (r3 - s(sprite_w), t, r3, t + s(sprite_h))
    return {"btn2": btn2, "btn3": btn3}


def basewin_title_box(plate: Tuple[int, int, int, int],
                      chev_w: int, chev_h: int, g: int) -> Tuple[int, int, int, int]:
    """Base-name title box (BaseWin_draw_info 0x415bf5..0x415c33, color
    0x78d528).

    Horizontal: plate.l/r -/+ s(6 + chev_w) (vanilla's -6-w pad, single
    floor over the sum — t_info_pad).  Vertical: top = plate.t + s(3)
    (flush with the chevron windows); bottom NATIVE = plate.b - 3
    (vanilla's form; its box primitive strokes at coordinate-1, landing on
    the chevron art's last row 107 — flush).  Bottom SCALED = top +
    s(chev_h) - 1: our thickened outline strokes [y1-t+1, y1], and the
    chevron KSB fill is immovably s(35) tall, so anchoring y1 to the art's
    last device row keeps the title stroke overlaying the chevron art's
    bottom border band at every g.  Vanilla's plate.b - s(3) diverges from
    it under independent floors (plate outer 41 rows: s(41)-s(3) !=
    s(3)+s(35) in general) — that divergence was the visible 3px "chevron
    sits high" defect.  The slack lands as extra dark padding above the
    plate's bottom stroke (invisible) instead.
    """
    s = lambda k: popup_scale_floor(k, g)  # noqa: E731
    pad = s(6 + chev_w)
    top = plate[1] + s(3)
    if g <= 16:
        return (plate[0] + pad, top, plate[2] - pad, plate[3] - s(3))
    return (plate[0] + pad, top, plate[2] - pad, top + s(chev_h) - 1)


def basewin_redbtn_frame(redbtn: Tuple[int, int, int, int],
                         g: int) -> Tuple[int, int, int, int]:
    """Staple-button ring frame rect (BaseWin_draw_info 0x415b35..0x415b5e,
    9-slice def 0x78d5a0 via Buffer_box_sprite).

    Vanilla inflates the redbtn field rect by 3 and its 9-slice places the
    right/bottom stroke at coordinate-1; the KSB art window is w = r - l off
    the SAME fields, i.e. art spans [l, r-1] (exclusive right).  Those two
    conventions cancel natively: channels 3-1 = 2 on all four sides.  Our
    thickened band ends AT the coordinate ([x1-t+1, x1]), so on the scaled
    path the frame rect's r/b must pull in by 1 to reproduce vanilla's
    stroke placement — otherwise the right/bottom channels run s(3)-t+1 vs
    s(3)-t on the left/top, a constant 1px asymmetry no field value can fix
    (field changes move frame and art together).  Port: t_info_btnframe.
    """
    s3 = popup_scale_floor(3, g)
    one = 1 if g > 16 else 0
    l, t, r, b = redbtn
    return (l - s3, t - s3, r + s3 - one, b + s3 - one)


def box2_ring_rects(l: int, t: int, r: int, b: int,
                    g: int) -> List[Tuple[int, int, int, int]]:
    """Buffer_box_2 1px-outline thicken law (the bar-grid cell highlights:
    production current-turn box @0x40ED80, nutrients intake box @0x4116A5).

    Buffer_box_2 is an OUTLINE, not a fill (feedback-buffer-box2-is-
    outline): 4 one-px strokes on the rect edges.  The vanilla 1px outline
    thickens INWARD to the canonical K = stroke_width(g) nested rings,
    ring i = (l+i, t+i, r-i, b-i) for i = 0..K-1.

    INWARD because the box marks a bar-grid CELL the engine has already
    filled: the outer ring stays on the vanilla cell edge, the extra
    weight eats the cell's own interior, and flush neighbors are never
    touched.  NOT ceil(g/16): thunk_hud_cellring (the HUD box-6 cell
    highlight) predates LAW 4 and uses ceil; new chrome-stroke work
    shares stroke_width so strokes cannot disagree across a screen
    (K: g=22 -> 1, g=25 -> 2, g=40 -> 2).

    Ring 0 is emitted unconditionally (identity: K(16)=1 -> exactly the
    vanilla call, whatever the rect).  An inner ring is dropped when it
    would degenerate (span < 1 on either axis) — the hline/vline
    zero-span no-op class must not be fed inverted rects.
    """
    out = [(l, t, r, b)]
    for i in range(1, stroke_width(g)):
        if r - i <= l + i or b - i <= t + i:
            break
        out.append((l + i, t + i, r - i, b - i))
    return out


def base_popbox_pads(g: int) -> Tuple[int, int, int, int]:
    """base_draw pop-number box pads, FARM VIEW ONLY (gate: dest buffer ==
    BaseWin canvas 0x6A7A6C; the main map keeps native pads at every
    engine zoom — vanilla design, do not touch).

    The box is font-derived: right = x + Font_width(text) + 5, bottom =
    y + font_height + 4, glyph pen = (left+2, top+1) (base_draw
    0x55B3CF/0x55B605/0x55B675).  The FONT already scales in the farm
    view — FontCache_get takes its zoom branch off the armed g_map_zoom,
    which draw_farm composes x g/16 — so only the native additive pads
    lag proportion (measured @4K: box 26x34 vs faithful ~30x39; with
    scaled pads 33x40, matching the pristine mockup's 33x39).

    Returns (pad_w, pad_h, text_dx, text_dy) = basewin_pt of (5, 4, 2, 1);
    identity (5, 4, 2, 1) at g <= 16.
    """
    return (basewin_pt(5, g), basewin_pt(4, g),
            basewin_pt(2, g), basewin_pt(1, g))


def descale_point(dev: int, g: int) -> int:
    """Exact left-inverse of popup_scale_floor for POINT hit-testing.

    n = (16*dev + 15) // g is the unique n with fl(n*g/16) <= dev <
    fl((n+1)*g/16) for every g >= 16 (each native cell maps to >= 1 device
    px, so the inverse is well-defined).  Used by the BaseWin map/facilities
    hit path (Spot rects and the pixel->tile fn 0x409100 are native-space;
    the mouse arrives in device space).  NOT for sizes — sizes descale by
    CEIL (feedback_floor_descale_roundtrip); this is the cell-index inverse.
    """
    return (16 * dev + 15) // g


# Native constants inside the 7 strip DRAW fns (device-space layout: every
# rect/anchor the fns compute is device once the seed rects are scaled, so
# each native additive/size constant scales by the floor idiom — the NetWin
# mixed-space law applied at the draw layer).  Keys name the semantic site,
# values are the vanilla immediates (byte-verified in the disasm).
BASEWIN_STRIP_CONTENT_NATIVE = {
    "inset3": 3,        # box_sprite interior insets, all fns
    "ghost5": 5,        # production/flash: queue ghost-box expansion (edge
                        # shared with production's right frame at native)
    "pad2": 2,          # production/flash: bar-area text margins
    "union3": 3,        # production/flash: CHANGE/HURRY union frame expansion
    "blank6": 6,        # production/flash: 6x6 blank corner sprite for it
    "pic_anchor": 0x28,  # production/flash: unit-picture centre y off box top
    "name_anchor": 0x41,  # production/flash: unit-name text y off box top
    "icon_half": 0x14,  # production: project/facility mono icon half-size
    "icon_size": 0x28,  # production: mono icon size arg (FUN_005e3e00)
    "bar_min_h": 2,     # production: min px per cost row (grid density)
    "bar_tile_thresh": 8,  # production: tile-vs-flat cell height threshold
    "bar_nudge": 1,     # production: cell border 1px nudges
    "pop_sprite_h": 0x30,  # pop: citizen sprite height (centering term)
    "garr_cell": 0x38,  # garrison: unit cell width (2 sites: cell + stats w)
    "garr_gap": 5,      # garrison: inter-cell gap (divisor + advance + squeeze)
    "garr_stats_y": 6,  # garrison: stats text y nudge
    "garr_edge": 1,     # garrison: squeeze-branch region-edge inset
    "sup_cell": 0x3e,   # supported: unit cell width (native 100 pre-scaled 10/16)
    "sup_row": 0x2e,    # supported: row height (native 75 pre-scaled)
    "sup_icon": 0xd,    # supported: ability-icon x pitch (2 locals)
    "sup_fit_pad": 0xc,  # supported: column-fit width pad
    "sup_scroll": 0xf,  # supported: scrollbar inset
    "info_pad": 6,      # info: plate inner-frame pad beside the chevron
    "q_list_x": 5,      # queue: slot-list x inset
    "q_list_y": 2,      # queue: slot-list y inset (non-800 branch)
}

# Local Font_init sizes per fn (the strip fns lay out in device space, so the
# local fonts scale AT their init sites — unlike the center fns where locals
# must stay native and only set_font swaps; see basewin_font_size docstring).
BASEWIN_STRIP_FONTS_NATIVE = {
    "production": (12, 12), "flash": (12, 12), "queue": (12, 10),
    "pop": (9,), "garrison": (12,), "supported": (10,),
    "shared_hdr": (14,),   # BaseWin+0x40E8C 14-bold via set_font swap
    "info_cap": 32,        # find_font shrink-loop start (table caps at 40 ->
                           # cave Font, not find_font, above native)
}


def basewin_strip_content(g: int) -> dict:
    """Scaled values for every native constant inside the strip draw fns.

    Law: value' = popup_scale_floor(value, g), identity at g<=16 (each cave
    thunk gates on g and re-runs the vanilla arithmetic byte-faithfully at
    native).  The supported-panel sprite ratio (SCALE_NUM_G/DEN_G) composes
    vanilla's own 10/16 prescale with g/16 as an exact fraction (10g, 256) —
    the basewin_sprite_ratio no-pre-floor rule; at g<=16 the thunk leaves
    vanilla's literal (10, 16) untouched (value-equal, byte-exact behavior:
    the blit core's scale-cache compares raw pair values).
    """
    out = {k: basewin_pt(v, g) for k, v in
           BASEWIN_STRIP_CONTENT_NATIVE.items()}
    out["sup_scale_pair"] = (10, 16) if g <= NATIVE_G else (10 * g, 256)
    out["pop_ratio"] = (1, 1) if g <= NATIVE_G else (g, 16)
    out["fonts"] = {k: (tuple(basewin_font_size(s, g) for s in v)
                        if isinstance(v, tuple) else basewin_font_size(v, g))
                    for k, v in BASEWIN_STRIP_FONTS_NATIVE.items()}
    return out


def basewin_strip_pop_citizen_y(row_top: int, cell_h: int, g: int) -> int:
    """Citizen-sprite vertical centering in draw_pop: vanilla centres the
    48px portrait in the (device) square cell as top + (cellH - 48)/2; the
    scaled form centres the *scaled* sprite: top + (cellH - fl(48*g/16))/2.
    cell_h is already device (derives from the scaled seed rect); the C `/2`
    is a CDQ/SUB/SAR round-toward-zero divide and cellH >= sprite height in
    every reachable layout, so plain //2 matches the asm."""
    return row_top + (cell_h - basewin_pt(0x30, g)) // 2


QUEUE_ROW_PITCH_NATIVE = 13    # font-10 line height, MEASURED from the
                               # vanilla 1024 capture 20260725-145003
                               # (queue rows at y=600,613,...,691)
GARRISON_STATS_H_NATIVE = 18   # font-12 line height, MEASURED same capture
                               # (stats top 236 == area bottom 248 - 18 + 6)


def basewin_strip_queue_row_y(i: int, g: int) -> int:
    """Cumulative y offset of queue slot row i (0-based) below the first row.

    Vanilla derives the row advance from the row FONT's line height (13 for
    the >=1024-family font 10).  Left alone, the scaled engine reads the
    SCALED font's line height, which is SUBLINEAR in size (18 at g=25, 27 at
    g=40 -- faithful is 20.3 / 32.5): the rows compress and the list reads
    cramped (2026-07-25e user report).  The faithful form scales the
    CUMULATIVE native offset with ONE floor -- cum(i) = fl(13*i*g/16) --
    never i times a per-row floor (feedback-remainder-distribution: the
    faction row gap / corner bevel class).
    """
    return popup_scale_floor(QUEUE_ROW_PITCH_NATIVE * i, g)


def basewin_strip_queue_row_advance(i: int, g: int) -> int:
    """Row advance/height handed back to draw_queue for the engine's 1-based
    row counter i (EDI): cum(i) - cum(i-1).  The cut thunk computes exactly
    this at g>16; at g<=16 it re-runs the vanilla metric read, so native
    identity holds by CONSTRUCTION (robust to localized fonts), not by the
    13 constant."""
    return (basewin_strip_queue_row_y(i, g)
            - basewin_strip_queue_row_y(i - 1, g))


def basewin_strip_garrison_stats_y(bottom_dev: int, g: int) -> int:
    """Top of the garrison stats-digit line in draw_garrison.

    Vanilla: y = area_bottom - font_line_height + 6 with the font-12 line
    height 18.  The scaled font's metric is sublinear (22 at g=25 vs faithful
    28), which drops the text 2-3px and pushes the digit bottoms across the
    panel clip (the flat-cut 0/2 the user reported).  Faithful:
    y = bottom_dev - fl(18*g/16) + fl(6*g/16).  The thunk keeps vanilla's
    metric path at g<=16 (identity by construction)."""
    return (bottom_dev - popup_scale_floor(GARRISON_STATS_H_NATIVE, g)
            + popup_scale_floor(6, g))


HUD_TICKER_LINE_H = 15        # the strip font's native line height (Arial 12 bold): pristine native-res trace cell0C=15, wrap_h=15
HUD_TICKER_ROWS = 4           # TextScroll_attach h = 4 * line height (0x4595C0)
HUD_TICKER_LIFT_NATIVE = 4    # VANILLA-BUG FIX: the strip font's descent (3) + 1 px clearance -- see hud_ticker_bottom_native


def hud_ticker_bottom_native(d38_dev: int, g: int) -> int:
    """The ticker window's y, native px relative to the map window's bottom (negative = above): vanilla
    y = [MainWin+0xD38] - 4*15 (pristine native-res trace: D38 42 -> -18), LIFTED by HUD_TICKER_LIFT_NATIVE.
    D38 is device-space under the HUD seed table, so it is brought back with the ceil descale (the floor-descale
    round trip: 105 @g40 / 65 @g25 / 57 @g22 -> 42).
    The lift (user decision 2026-10-15) is a VANILLA-BUG fix and so the one exception to the g <= 16 native no-op:
    vanilla's bottom text row sits with ZERO descender clearance over the console strip -- pristine 1024 shot
    terranx_pristine_1024x768_20261011-235347, the "y" of "atrocity." has its baseline at row 530 and the strip art
    from row 531 covers its descender (one pixel leaks at 532).  The descent is 3 native rows, so the whole ticker
    (window + rows, both read this y) rises 3 + 1 = 4 native px at EVERY g: measured baselines -> after the lift,
    1024 530 -> 526 (descender 527..529, art 531); 1600 829 -> 823 (art 834); 1080 753 -> 748; 4K 1567 -> 1557
    (post art 1568).  Nothing sits above the ticker but the map, which it already overlays."""
    d38n = d38_dev if g <= NATIVE_G else -((-d38_dev * NATIVE_G) // g)
    return d38n - HUD_TICKER_ROWS * HUD_TICKER_LINE_H - HUD_TICKER_LIFT_NATIVE


def hud_ticker_native_y(engine_y: int) -> int:
    """g <= 16: the ticker's TextScroll_attach y = the engine's own y (D38 - 4 * the native font's line height, kept
    from the engine so a localized strip font still sizes its window) lifted by HUD_TICKER_LIFT_NATIVE; h untouched.
    With the stock font (L = 15) this is hud_ticker_bottom_native(D38, g)."""
    return engine_y - HUD_TICKER_LIFT_NATIVE


def hud_ticker_window(d38_dev: int, g: int, engine_h: int = 0) -> Tuple[int, int]:
    """(y, h) for the ticker's TextScroll_attach (site 0x459626): bottom y' = fl(Yn*g/16), top = fl((Yn-60)*g/16),
    h = y' - top -- one floor per edge of the vanilla window, so its 4 rows land at vanilla x g/16.  The engine
    used the SCALED font's line height (36 at 4K vs vanilla 15 x 2.5 = 37.5), five times: the text sat ~8 px low
    and its glyph bodies slid under the console's raised posts (user 4K shots 224634 / 225915, 2026-10-11).
    h is never below engine_h (the engine's own 4 * L_scaled): where the scaled font's line height rounds UP past
    15g/16, 4 lines must still fit or TextScroll's update routine (0x629490) enables its scrollbar; the window then
    grows upward only -- the rows are anchored at its bottom (hud_ticker_row_top).  g<=16: vanilla's window lifted
    by HUD_TICKER_LIFT_NATIVE (hud_ticker_native_y), h = 4 * 15."""
    yn = hud_ticker_bottom_native(d38_dev, g)
    if g <= NATIVE_G:
        return yn, HUD_TICKER_ROWS * HUD_TICKER_LINE_H
    bot = popup_scale_floor(yn, g)
    top = popup_scale_floor(yn - HUD_TICKER_ROWS * HUD_TICKER_LINE_H, g)
    return bot, max(bot - top, engine_h)


def hud_ticker_row_top(k: int, d38_dev: int, g: int, h: int = 0) -> int:
    """Canvas y of the top of the k-th text row counted from the ticker's bottom (k = 0 -> the canvas height h,
    k = 1 -> the bottom line's top): fl((Yn - 15k)*g/16) - fl((Yn - 60)*g/16), the cumulative native offset under
    ONE floor (feedback-remainder-distribution).  TextScroll_draw lays entries bottom-up (ebx = h; ebx -=
    Buffer_wrap_height per entry); t_ticker_wraph returns the step that lands each entry on these tops."""
    yn = hud_ticker_bottom_native(d38_dev, g)
    if g <= NATIVE_G:
        return (HUD_TICKER_ROWS - k) * HUD_TICKER_LINE_H
    h = h or hud_ticker_window(d38_dev, g)[1]
    return popup_scale_floor(yn - HUD_TICKER_LINE_H * k, g) - popup_scale_floor(yn, g) + h


def is_native_noop_g(g: int) -> bool:
    return g <= NATIVE_G


def hud_unit_arrow_rects(anchor: Tuple[int, int, int, int], x9: int,
                         sprite_w: int, sprite_h: int, g: int) -> dict:
    """MainWin unit-row scroll-arrow button window rects (MainWin_build
    0x45a816..0x45a8d5; buttons[8..10] = 0x7B5080/0x7B5BCC/0x7B6718, seeds
    +0xAAC/+0xABC/+0xACC).

    anchor = the +0xCEC..+0xCF8 seed quad (cec, cf0, cf4, cf8) and x9 =
    +0xDB0 — ALL already device-scaled by thunk_hud_seedscale (the block
    runs after the 0x459E8A detour).  Vanilla composes them with NATIVE
    sprite dims (+0x22E40/44 = arrow sprite +0x18/+0x1c, 12x42) and native
    +/-4 pads — the mixed-space class (plate-chevron twin,
    basewin_strip_chevron_rects).  Faithful: size = s(w) x s(h), pads s(4),
    positions untouched (already device).  The art stays native; the
    btnzoom KSB fills by CEIL descale (exact for every k at g > 16).  The
    vertical centering keeps vanilla's idiom (truncating /2: cdq;sub;sar);
    the garrison/StatusWin unit-row spans read btn9.r/btn10.l back, so the
    row region follows the wider arrows proportionally.
    g = 16: bit-identical to vanilla (s and the pads are identities).
    """
    cec, cf0, cf4, cf8 = anchor
    s = lambda k: popup_scale_floor(k, g)  # noqa: E731
    sw, sh, p4 = s(sprite_w), s(sprite_h), s(4)
    span = (cf8 - sh) - cf0
    ycen = cf0 + (span // 2 if span >= 0 else -((-span) // 2))
    x8 = cec + p4
    x10 = cf4 - sw - p4
    return {
        "btn8": (x8, ycen, x8 + sw, ycen + sh),
        "btn9": (x9, ycen, x9 + sw, ycen + sh),
        "btn10": (x10, ycen, x10 + sw, ycen + sh),
    }


HUD_CELL_FRAME_INSET_NATIVE = 3   # box-6 nested 9-slice inset, one frame one side
                                  # (StatusWin_draw_status 0x4B80D4 esi=3, applied
                                  # twice per side; scaled by thunk_hud_n13)


HUD_ROW_LABEL_LINEH_NATIVE = 13   # strip font-12 line height, MEASURED live
                                  # (frida_hudcell.log 2026-08-02: [LBL] arg10=13
                                  # native, 27 at g=40 — the scaled font metric
                                  # is SUBLINEAR, 27 vs faithful 32.5)


def hud_row_label_y(cell_b: int, s3: int, line_h_live: int, g: int) -> int:
    """HUD unit-row "0-1-1" label y (StatusWin_draw_status 0x4B86DD..0x4B86EC,
    port thunk_hud_n16 v2).

    Vanilla: y = cellB + [StatusWin+0x154c] − line_h + 1, live-traced native
    as 242 + 3 − 13 + 1 = 233 = cellB − 9 (all three exes, 2026-08-02).
    [+0x154c] arrives already device-scaled (3 → 7 at g=40); line_h is the
    LIVE scaled strip-font metric and is sublinear (27 at g=40 vs faithful
    32.5), so the raw formula lands the label ~6px low of proportion — the
    font-metric-sublinearity class: substitute fl(13·g/16) for the metric at
    g>16, keep the live metric read at g<=16 (identity by construction,
    robust to localized fonts).  4K: 606+7−32+1 = 582 = cellT+88 vs exact
    proportional 87.5.  The RETIRED v1 law (cellB − fl(19g/16), gated on the
    4K metric value 27) put the label 25px above faithful at 4K and was
    inert at every other g — the 2026-08-01 "numbers written too high"
    report."""
    line_h = line_h_live if g <= NATIVE_G else popup_scale_floor(
        HUD_ROW_LABEL_LINEH_NATIVE, g)
    return cell_b + s3 - line_h + 1


def hud_cell_h_inset(g: int) -> int:
    """StatusWin box-6 (HUD unit-row) cell-height inset (site 0x4B816F).

    Vanilla: cell_h = strip_h - 12, where 12 IS the four 3px frame insets
    (two nested 9-slice frames, top 3+3 + bottom 3+3) — the cell exactly
    fills the content area and the selection ring (cell outset 2, drawn
    inward-thickened by thunk_hud_cellring) closes 4px above the strip
    bottom.  thunk_hud_n13 scales each inset to fl(3g/16), but the -12
    stayed native, so at g=40 the cell bottom overshot the strip bottom by
    2 and the ring's bottom edge drew past the HUD bound (user report
    2026-08-01, HudUnitStack.png vs 20260801-150111 shot: rails run to the
    clip with no bottom edge).

    Faithful: 4*fl(3g/16) — composed from the SAME per-inset floor n13
    applies (one shared floor cascade, feedback-floor-descale-roundtrip;
    NOT fl(12g/16): at g=40 that is 30 vs the true 28 and the cell falls
    2px short of flush).  Identity 12 at g=16.  Port: thunk_hud_cellh.
    """
    return 4 * popup_scale_floor(HUD_CELL_FRAME_INSET_NATIVE, g)


def hud_cell_ring_outset(g: int) -> int:
    """StatusWin box-6 selected-cell ring outset from the cell rect (port
    thunk_hud_cellring v2, site 0x4B8764 upstream rect).

    Vanilla draws the ring at cell outset 2 — which is frame inset 3 minus
    its 1px stroke: the ring BUTTS the inner 9-slice frame's content-side
    stroke edge with zero channel (HudUnitStack.png pristine: stroke px then
    ring px, flush).  The inset scales to i = fl(3g/16) (thunk_hud_n13) and
    the frame stroke — native band px0 — band-maps to half_down(i, 3) device
    px, so flush is

        outset = i - half_down(i, 3)

    2 at g=16 (the vanilla constant, identity), 3 at g=22/25, 5 at g=40.
    The unscaled native 2 left a dark channel between ring and frame stroke
    (2-3px at 4K, 2026-08-02 screenshot vs pristine; mirrored edges' band
    remainder can shift their stroke 1px content-ward, giving at most 1px of
    ring-over-stroke overlap, never a residual gap).  The ring still
    thickens INWARD by K=(g+15)>>4 from the outset rect, and outset >= K
    keeps its inner edge clear of the cell content at every g.

    SECOND PORT — thunk_hud_cellclip (sites 0x4B82F1 / 0x4B84AF): the cell
    painter clips each cell to cell+/-2 via Buffer_set_clip before drawing,
    i.e. vanilla's clip outset == ring outset == 2 and the ring draws exactly
    ON the clip boundary.  The clip must widen by the SAME outset(g) or the
    scaled ring is fully clipped and no box draws at all (2026-08-02b defect:
    ring moved, clip didn't)."""
    i = popup_scale_floor(HUD_CELL_FRAME_INSET_NATIVE, g)
    return i - half_down(i, 3)


def hud_cell_ring_rect(frame_x: int, frame_y: int, frame_y1: int,
                       cell_l: int, cell_r: int, g: int) -> tuple:
    """StatusWin box-6 selection-ring rect AND cell clip rect — one law, two
    ports (thunk_hud_cellring v5, thunk_hud_cellclip v4).  Domain g > 16;
    at g <= 16 both thunks pass the vanilla cell±2 rect through untouched
    (see the domain note at the end).

    ENGINE FACTS (measured from the bytes, 2026-08-02g — do not re-model):

    * Buffer_box_2 (0x5E3203) draws the 1px frame of the HALF-OPEN box
      [L,R)×[T,B): top hline at row T, LEFT vline at col L, but bottom
      hline at row B-1 and right vline at col R-1 (Unicorn on the pristine
      exe; hline/vline are inclusive-endpoint, box_2 decs B and R first).
      The clip (Buffer_set_clip = verbatim IntersectRect) culls half-open
      the same way: y == clip.B and x == clip.R are culled, y == B-1 and
      x == R-1 draw.  So a ring drawn AT the clip rect survives entirely —
      vanilla's own invariant (clip == ring == cell±2).
    * The HUD frames are NOT box_2 outlines: thunk_hud_boxframe 9-slice
      band-maps them with an INCLUSIVE footprint (fe_bandmap dst = far-edge
      +1), and band_widths pins the chrome cell to stroke_width(g), so the
      stored frame rect (x, y, X1, Y1) — each field fl(nat*g/16), inclusive
      far edges — renders strokes at
          top  [Y  .. Y+kS-1]   left [X .. X+kS-1]
          bottom [Y1-kS+1 .. Y1],   kS = stroke_width(g)
      (validated against axis_map for every g in 17..40 and every corner
      depth n in 4..12 — scratchpad validate_ring_law_v4.py).
    * hd = half_down(i,3) is NOT the frame stroke width: it coincides with
      kS at g=22/40 but diverges at g=25/26 (hd=1, kS=2) — the v3.1 hd-based
      law overlapped the left/top strokes there, and its B = Y1-hd painted
      row Y1-hd-1, a 1px background channel above the stroke at almost
      every g (4K shot 153025: ring rows 2125-27, channel 2128, stroke
      2129-30).  Flush laws must use stroke_width(g), never hd.

    The frame's device position is fl((nat_strip+3)*g/16) — NOT devStrip +
    fl(3g/16): n*floor != floor*n, so at 4K the inner frame's left edge
    lands at 355 while devStrip+i = 354.  No uniform cell-relative outset
    can be flush against that on every edge; the VERTICAL edges anchor to
    the FRAME'S OWN stored rect (0xA11720, populated by the pre-loop inner
    frame draw at 0x4B8106) — the strip is ONE row of cells, so every cell
    shares the frame's top/bottom.  The LEFT edge is per-cell: only cell 0
    butts the frame's left stroke (the 08-02g v4 defect anchored L to the
    frame for EVERY cell, so selecting any later unit drew the ring from
    the strip's left stroke to that cell — "overly wide box, left edge
    always anchored", user 1920x1080 shot 170930):

        L = cell_l - d, SNAPPED to frame_x + kS when within 2px (cell 0)
        T = frame_y + kS         (first row under the top stroke)
        R = cell_r + d           (right: no frame — symmetric outset,
                                  law hud_cell_ring_outset; drawn at R-1)
        B = frame_y1 + 1 - kS    (drawn bottom = B-1 = Y1-kS, the last row
                                  above the stroke [Y1-kS+1 .. Y1])

    with kS = stroke_width(g), i = fl(3g/16), hd = half_down(i,3),
    d = i - hd.  The snap threshold 2 is PROVEN safe: cell 0's
    cell-derived left is devStrip + i + hd + seed - d = devStrip + 2hd +
    seed - ... vs frame fl((nat+3)g/16) + kS; floor superadditivity bounds
    fl((nat+3)g/16) - (devStrip + i) to [0,1], hd - kS to [-1,0] and seed
    to [0,2], so |cell-derived - frame-flush| <= 2 at EVERY g and drift,
    while interior cells differ by a full pitch (>= 80 device px at
    g >= 17) — the snap can never capture them.  The
    SAME rect is stored as the cell clip (thunk_hud_cellclip v4): clip ==
    ring restores the vanilla invariant, makes every ring pixel drawable
    by construction (half-open on both sides), and replaces the v2b
    cell-anchored clip whose bottom fell 1px short of the ring at
    g in {29,30,31,36} under the n*floor drift.  Content draws (clipped
    before the ring in the same cell pass) can never touch a stroke px.

    Golden 4K (g=40, window-local): frame (355,487,1902,612), cell 0 at
    cellL 361 / cellR 513 -> (357,489,518,611): DRAWN ring cols 357..517,
    rows 489..610, flush under the measured stroke rows (611,612 = screen
    2129,2130).  Interior cell k: L = cellL_k - 5 (symmetric with R).

    DOMAIN: g > 16 only.  The bandmap's inclusive footprint is one row
    taller than the native frame's half-open [Y..Y1) render, so at g=16
    this law gives B = Y1 = cell+3 where vanilla passes cell+2 — the
    thunks' g<=16 gate (caller rect passed through) IS the native no-op;
    the law function must not be evaluated there."""
    ks = stroke_width(g)
    i = popup_scale_floor(HUD_CELL_FRAME_INSET_NATIVE, g)
    hd = half_down(i, 3)
    d = i - hd
    l_frame = frame_x + ks
    l_cell = cell_l - d
    l = l_cell if l_cell - l_frame > 2 else l_frame
    return (l, frame_y + ks, cell_r + d, frame_y1 + 1 - ks)


HUD_CELL_GAP_NATIVE = 5      # vanilla inter-cell gap in the box-6 unit row
HUD_ROW_SEED_NATIVE = 1      # vanilla first-cell x inset from the strip content edge


def hud_cell_pitch_gap(g: int) -> int:
    """StatusWin box-6 inter-cell gap: vanilla pitch = slot width + 5.

    thunk_hud_n14 already scales the +5 inside the max-slot-count divisor and
    thunk_hud_n15 derives slotw_dev = span/count - fl(5g/16), so the engine's
    intended device pitch is exactly slotw_dev + fl(5g/16) (cells tile the
    span).  The LOOP-TAIL ADVANCE and the Spot_add click-region widths carry
    their own native +5s, and leaving them unscaled squeezes the row left:
    2026-08-02 4K shot measured pitch 157 = slotw_dev 152 + native 5, vs the
    pristine-equivalent 165 — the selection ring (outset 5 at g=40) then
    filled the ENTIRE 5px inter-cell gap, crowding the neighbor's flag
    (pristine leaves ~3 native px of clearance).  Identity at g=16.

    Ports: thunk_hud_n17 (part-A pitch 0x4B8404), n18 (part-A next-cell
    anchor 0x4B840A), n19 (loop-tail pitch 0x4B87C6), n20/n21 (Spot_add
    widths 0x4B8380 / 0x4B87A3)."""
    return popup_scale_floor(HUD_CELL_GAP_NATIVE, g)


def hud_row_seed_inset(g: int) -> int:
    """StatusWin box-6 first-cell x seed: vanilla cellL = strip content + 1.

    The +1 is a native additive constant and must scale (fl(g/16)); left
    unscaled, the whole row sits 1 device px too far LEFT of the law's flush
    model at g>=32 — at 4K that put the ring's left edge exactly ON the inner
    frame stroke's content-side pixel (1px ring-over-stroke overlap where
    top/bottom measured flush; cellL at content+2 restores flush).  Identity
    at g=16..31 (fl(g/16)=1 = vanilla).

    Port: thunk_hud_n22 (site 0x4B827C, the `inc ecx` seed)."""
    return popup_scale_floor(HUD_ROW_SEED_NATIVE, g)


# ==== HUD strip seed table: the right console panel on the mirror grid (F32) =
# thunk_hud_seedscale (MainWin_build's console2_A call-redirect @0x459E8A) scales the 97 seed / derived rect dwords
# of the HUD strip (MainWin +0xA2C..+0xDFC, g_hud_seedtable) once, at build; every console screen reads them live.
HUD_STRIP_NATIVE_W = 4 * 256        # the strip window's vanilla width (spelled for the screen-literal guard)

#: The right console panel's x seeds: the panel rect +0xD90 (779, 56, 1020, 252) -- vanilla's exact mirror of the
#: left panel +0xD80 (4, 56, 245, 252): 4 + 1020 = 245 + 779 = 1024 -- and every x MainWin_build derives from it
#: before the detour (0x459D18..0x459E15): TURN band +0xA7C (l + 4, l + 4 + 0xE9), minimap +0xCFC (l + 1, r - 1),
#: DETAIL / WORLD map buttons +0xA9C / +0xA8C (r - 6 - 0x36 .. r - 6, and the pair pitch), mission-year box +0xD0C
#: (l + 6, WORLD.l - 3).  Byte offsets into MainWin; the l and r dword of each rect.
HUD_SEED_MIRROR_FIELDS = (0xA7C, 0xA84, 0xA8C, 0xA94, 0xA9C, 0xAA4, 0xCFC, 0xD04, 0xD0C, 0xD14, 0xD90, 0xD98)


def hud_strip_w(g: int) -> int:
    """The HUD strip window's device width, as thunk_hud_seedscale recomputes it (+0xA1C..+0xA24): fl(1024g/16)."""
    return popup_scale_floor(HUD_STRIP_NATIVE_W, g)


def hud_seed_x(native_x: int, g: int, mirror: bool) -> int:
    """LAW (F32) -- one HUD strip x seed on the device grid.

    Left / centre seeds: fl(x*g/16) (the floor image, unchanged).  Right console panel seeds (mirror=True,
    HUD_SEED_MIRROR_FIELDS): W' - fl((1024 - x)*g/16), W' = hud_strip_w(g) -- the device MIRROR of the left-panel x
    they mirror natively.  The left panel's right edge fl(245g/16) mirrors to W' - fl(245g/16), but the floor of
    779g/16 is one less at every g that is not a multiple of 16 (1024g/16 is an integer, 245g/16 is not), so the right
    panel and its whole inner chain sat 1 px left of the mirror (4K: da50 2587 / d5a0 2594 / d528 2601 vs 2588 / 2595 /
    2602; the F6 ORBITAL ATTACK VIEW target buttons 560 vs 561), and at g with 1020g/16 fractional the outer edge too
    (1920x1080 / 1600x1200: both edges, stroke sums 1918 / 1598 = W - 2).  With W' = 64g exact the mirror form is
    the CEIL image, (x*g + 15) >> 4 -- the thunk's form (hud_seed_ceil_equals_mirror pins the identity).  Every
    right-panel seed takes it, so the panel's internal offsets keep the phase the floor gave them (the minimap's
    l + 1 / r - 1 gaps stay equal) and every derived chain moves with its anchor.
    g <= 16: vanilla."""
    if g <= NATIVE_G:
        return native_x
    if mirror:
        return hud_strip_w(g) - popup_scale_floor(HUD_STRIP_NATIVE_W - native_x, g)
    return popup_scale_floor(native_x, g)


def hud_seed_scaled(field: int, native: int, g: int, x_fields=HUD_SEED_MIRROR_FIELDS) -> int:
    """thunk_hud_seedscale's value for one table dword at MainWin + field: hud_seed_x on the mirror grid for the
    right-panel x fields, the plain floor for every other (left / centre x, every y, the strip height +0xD7C)."""
    if g <= NATIVE_G:
        return native
    return hud_seed_x(native, g, field in x_fields)


def hud_backdrop_col_map(dst_w: int, src_w: int) -> List[int]:
    """LAW (F32 v2) -- the console backdrop's column map, dest col -> console2_A.pcx col: the MIRROR-symmetric NN
    (scanicon_axis_map: map[n - 1 - d] == src - 1 - map[d]).

    MainWin_build stretches the 1024-wide pcx to the strip with Buffer_copy_3 @0x459F65 = GDI StretchBlt, MEASURED
    centre-aligned NN with ties to the UPPER column (nn_center_index; audit-w2C gditie.py on the user's shots).  Ties
    (d + 1/2) * src / dst integer recur every 16 / gcd(g, 16) source columns, and a tie sends one more dest column to
    the upper texel -- so on the right half the panel strokes (art column 779) get one column more than their left
    mirrors (244): 4K 1947..1949 vs 610..611, the right da50 / HUD stroke runs one px wider.  The mirror map differs
    from GDI's exactly at the right-half ties (hud_backdrop_tie_cols), where it takes the LOWER texel -- the texel GDI
    gives the column before (an enlarge).  Port: t_hb_mirror (pcave2 0x360A0), wrapping t_hud_backdrop: the engine
    stretch + the stripe-law restripe as before, then every right-half tie column := its left neighbour, rows cut to
    the dest clip.  The restripe is per texel and per absolute dest row, so the copied column carries texel d - 1's
    stripes on the same rows: the dither stays on the stripe law.  g <= 16: no copy (dst == src: no ties)."""
    return scanicon_axis_map(dst_w, src_w)


def hud_backdrop_tie_cols(dst_w: int, src_w: int) -> List[int]:
    """The dest columns t_hb_mirror rewrites: right of the centre (2d + 1 > dst) and an exact centre-NN tie
    ((2d + 1) * src divisible by 2 * dst)."""
    if dst_w <= src_w:
        return []
    return [d for d in range((dst_w + 1) >> 1, dst_w) if ((2 * d + 1) * src_w) % (2 * dst_w) == 0]


HUD_MAP_BTN_WORLD = (904, 214, 958, 246)    # MainWin +0xA8C: the WORLD map button window (FlatButton 0x7B39E8, id 0x3EE)
HUD_MAP_BTN_DETAIL = (960, 214, 1014, 246)  # MainWin +0xA9C: the DETAIL map button window (0x7B4534, id 0x3EF)
HUD_MAP_BTN_FIELDS = (0xA8C, 0xA9C)


def hud_map_btn_pair(g: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """LAW (F32) -- the x spans ((l, r), (l, r)) of the HUD's WORLD / DETAIL map-mode buttons, vanilla 904..958 and
    960..1014: two 54-px windows and a 2-px seam, which BaseButton_init gets as (x, r - x) @0x45AD20 / @0x45AD99.

    The pair's OUTER edges are right-panel seeds on the mirror grid (hud_seed_x: WORLD.l, DETAIL.r); one width
    w = (R - L - s(2)) >> 1 for both, the odd px in the seam (the netwin_btn_pair / t_rw_btnw rule): WORLD = (L, L + w),
    DETAIL = (R - w, R); the seam is s(2) or s(2) + 1 and w within 1 px of 54g/16.  Each edge floored or mirrored alone
    gives the two windows widths one px apart at 6 of the 24 g in 17..40 (floor: 21/23/29/31/37/39; the mirror grid
    alone: 17/19/25/27/33/35, 1600x1200 among them); F32 v1's w = fl(54g/16) left the seam at s(2) + 2 at 14 g.  Only WORLD.r (+0xA94) and
    DETAIL.l (+0xA9C) differ from the seeds; their other readers take the pair's union (box 9 0x45BEEE, the diplomacy
    strip's 0x4402FE / t_dp_box_hqunion: min l / max r) or overwrite the read (DiploTalkWin_init 0x4407B3).
    Port: t_hud_btnpair, between thunk_hud_seedscale and t_hud_mi_square.  g <= 16: vanilla."""
    if g <= NATIVE_G:
        return (HUD_MAP_BTN_WORLD[0], HUD_MAP_BTN_WORLD[2]), (HUD_MAP_BTN_DETAIL[0], HUD_MAP_BTN_DETAIL[2])
    lo, hi = hud_seed_x(HUD_MAP_BTN_WORLD[0], g, True), hud_seed_x(HUD_MAP_BTN_DETAIL[2], g, True)
    w = (hi - lo - popup_scale_floor(HUD_MAP_BTN_DETAIL[0] - HUD_MAP_BTN_WORLD[2], g)) >> 1
    return (lo, lo + w), (hi - w, hi)


# ==== HUD box-sprite frame rects (thunk_hud_boxframe NAT table) ==============
# Native (L,T,R,B) per Buffer_box_sprite call site (keyed on the caller's
# return address).  The engine's own device rects DRIFT from fl(nat*g/16)
# (n*floor != floor*n through the seed table), so the thunk substitutes
# fl(nat*g/16) per edge for every listed site.
HUD_BOXFRAME_NAT = {
    0x4b6a0e: (140, 60, 241, 189), 0x4b6a46: (143, 63, 238, 186),
    0x4b4d73: (8, 60, 136, 248),   0x4b4dab: (11, 63, 133, 245),
    0x4b80ce: (139, 192, 764, 248), 0x4b8106: (142, 195, 761, 245),
    0x45bf66: (785, 214, 901, 246),   # (0x45bf3e, box 9 outer: t_box9_outer since F32 v2, hud_box9_outer_rect)
    0x45bd88: (266, 70, 759, 168), 0x45be28: (266, 70, 759, 168),
    0x45bd99: (269, 73, 495, 165), 0x45bdaa: (498, 73, 724, 165),
    0x45910d: (269, 73, 495, 165), 0x4564a7: (269, 73, 495, 165),
}
HUD_BOX5_RIGHT_PANEL_SITE = 0x45bdaa
# Column split between the two box-5 readout panels: midpoint of the panel
# lefts (269, 498).  Every table rect's left is >= 100 native px from it.
HUD_BOX5_SPLIT_NATIVE = 383


def hud_boxframe_rect(site: int, engine_rect: tuple, g: int) -> tuple:
    """Device rect thunk_hud_boxframe draws for a HUD Buffer_box_sprite call.

    ENGINE FACT (frida_infowin_clear_20260918T213604/213713.log, 4K + 1600):
    the InfoWin typewriter ALTERNATES between the two box-5 panels
    (InfoWin_reset 0x458FF0: cur = (cur-1)&1) and clears the panel it is
    about to retype with Buffer_box_sprite(d7f8) on rect[cur+1] — d7f8 is a
    FILLED set (interface.pcx fill cell = the 2-row scanline pair), so the
    box draw IS the engine's panel clear.  Both shared painters (ret
    0x45910D reset, 0x4564A7 layout) therefore reach the thunk with EITHER
    panel's rect.  A site-keyed table alone mapped both to the LEFT panel:
    the right panel was never cleared (typewriter cursor ran over the old
    text; stale readout text showed through the scenario-editor palette
    gaps) and the left was wiped while still displayed.

    LAW: a listed site draws fl(nat*g/16) per edge, where nat is the site's
    table rect — EXCEPT when the engine's rect lies right of the box-5
    column split while the table rect lies left of it: the site is a shared
    panel painter asked for the RIGHT panel, so nat = the right panel's
    rect.  The split test is in one space (left*16 > split*g) and is
    resolution-safe: drift is a few px, the margin >= 100 native px.
    Unlisted sites and g <= 16 pass the engine rect through.

    F32 (2026-10-25): the box-9 sites (HUD_BOXFRAME_MIRROR_SITES) sit in the
    right console panel, whose seeds thunk_hud_seedscale now puts on the
    strip's mirror grid (hud_seed_x); their x edges follow it, so the frame
    stays on the seeds its content is laid out from (d0c, a9c), and the right
    edge is drawn EXCLUSIVE (r - 1): thunk_box_thick_hollow_flat paints its
    rect inclusively, vanilla Buffer_box_sprite's r is one past the stroke
    (vanilla box 9: stroke columns 785 and 900 for d0c 785..901), so the
    inclusive draw put the right stroke one column too far right and the
    box's right channel one px short of its left at every g.  The box-9
    OUTER frame (0x45BF3E) is no longer a table site: t_box9_outer sets its
    engine rect (hud_box9_outer_rect)."""
    if g <= 16:
        return tuple(engine_rect)
    nat = HUD_BOXFRAME_NAT.get(site)
    if nat is None:
        return tuple(engine_rect)
    if (engine_rect[0] * 16 > HUD_BOX5_SPLIT_NATIVE * g
            and nat[0] <= HUD_BOX5_SPLIT_NATIVE):
        nat = HUD_BOXFRAME_NAT[HUD_BOX5_RIGHT_PANEL_SITE]
    if site in HUD_BOXFRAME_MIRROR_SITES:
        return (hud_seed_x(nat[0], g, True), popup_scale_floor(nat[1], g),
                hud_seed_x(nat[2], g, True) - 1, popup_scale_floor(nat[3], g))
    return tuple(popup_scale_floor(v, g) for v in nat)


#: F32: the box-9 inner frame (the mission-year box d0c @0x45BF61): right-panel content, drawn on the mirror grid with
#: an exclusive right edge.  thunk_hud_boxframe reads a NEGATIVE table x as "mirror this edge" and a negative RIGHT
#: edge as "mirror, then r - 1" (hud_boxframe_table_row).
HUD_BOXFRAME_MIRROR_SITES = frozenset({0x45bf66})

#: The box-9 OUTER frame (UnionRect(d0c, a9c) -+ 3, Buffer_box_sprite @0x45BF39, rect = the painter's local): vanilla
#: (782, 211, 1017, 249), nested 3 px inside the right console panel +0xD90 (779, 56, 1020, 252) on both sides.
HUD_BOX9_OUTER_NATIVE = (782, 211, 1017, 249)
HUD_BOX9_OUTER_INSET = 3


def hud_box9_outer_rect(panel_l: int, panel_r: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (F32 v2, the match-opposite-edge-margin rule) -- the rect t_box9_outer hands Buffer_box_sprite for the box-9
    outer frame, drawn by the INCLUSIVE thick renderer (thunk_hud_boxframe passes an unlisted site's rect through):
    (P.l + s(3), fl(211g/16), P.r - s(3) - 1, fl(249g/16)), P = the right console panel's device seeds (+0xD90 l / r,
    on the mirror grid), s(3) = fl(3g/16).  Its channels to the panel's tiled interior (l + 1 .. r - 2) are then
    s(3) - 1 on BOTH sides at every g; each edge on its own grid (ceil(782g/16) / ceil(1017g/16) - 1, F32 v1 + R - 1)
    left them one px apart at g 19 / 20 / 29 / 35 / 36 (and the v1 inclusive right edge at 22 of 24 g).  The box stays
    within 2 px of vanilla x g/16 (the panel's own ceil grid on the right).  g <= 16: the engine's rect, untouched."""
    s3 = popup_scale_floor(HUD_BOX9_OUTER_INSET, g)
    return (panel_l + s3, popup_scale_floor(HUD_BOX9_OUTER_NATIVE[1], g),
            panel_r - s3 - 1, popup_scale_floor(HUD_BOX9_OUTER_NATIVE[3], g))


def hud_boxframe_table_row(site: int) -> Tuple[int, int, int, int, int]:
    """g_hud_nat_table's row for `site` (thunk_hud_boxframe's encoding of HUD_BOXFRAME_NAT): (site, l, t, r, b), with
    the x edges of a HUD_BOXFRAME_MIRROR_SITES row stored NEGATED.  The thunk's per-edge `imul; sar 4` then floors
    -x*g/16 = -ceil(x*g/16), and its `jns; neg` turns that into ceil(x*g/16) = hud_seed_x(x, g, True) (then `dec` on
    the right edge, the loop's ecx == 2: the exclusive edge); a positive edge is the plain floor.  The box-5 split test
    reads the row's l UNSIGNED (`ja`), so a negated l never takes the shared-painter substitution (the box-9 site is
    not a shared painter)."""
    l, t, r, b = HUD_BOXFRAME_NAT[site]
    if site in HUD_BOXFRAME_MIRROR_SITES:
        l, r = -l, -r
    return site, l, t, r, b


# ==== Combat console (BattleWin) ============================================
# Ground truth: work\_cmb_probe\combat_geom_20260918T222427.log (PRISTINE exe,
# 1024x768) + the three patched runs of the same battle; static map
# work\_cmb_static_map.md.  BattleWin_battle_report 0x421B50 paints the whole
# console into the strip buffer from rects BattleWin_init 0x4219E0 derives out
# of the (already seed-scaled) MainWin seeds D80 / DC0.
BATTLE_RECT_INSET_NATIVE = 4    # seed -> box inset (all four sides)
BATTLE_RECT_GAP_NATIVE = 3      # gap between the two boxes of a pair / text inset / label gap
BATTLE_SLOT_NATIVE = 75         # unit slot: veh x-centring, unit-name y = top + slot, "destroyed" y = slot/4
BATTLE_STATS_Y_NATIVE = 5       # first stats line y = top + 5
BATTLE_PORTRAIT_NATIVE = (96, 115)
BATTLE_FONT_STATS_NATIVE = 12   # 3 x Font_init(hud face, 12, style 0/2/1)  -> font_direct_law
BATTLE_FONT_FACTION_NATIVE = (14, 1)   # find_font(14,1)                   -> font_face_law (t_ffn)
BATTLE_FONT_UNIT_NATIVE = (16, 1)      # find_font(16,1)                   -> font_face_law (t_ffn)


def battlewin_rects(d80: Tuple[int, int, int, int], dc0: Tuple[int, int, int, int],
                    g: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """(unitL +0x30, unitR +0x40, portraitL +0x50, portraitR +0x60) from the
    DEVICE seeds.  Vanilla BattleWin_init applies its insets 4 / gap 3 as native
    additive constants on top of seeds that are already x g/16; the law scales
    them (fl(v*g/16)) and keeps the engine's own split formula.  g=16 is the
    pristine trace byte for byte: D80 4,56,245,252 / DC0 262,66,763,234 ->
    266,70,511,230 / 514,70,759,230 / 8,60,123,248 / 126,60,241,248.
    Port: thunk t_cmb_init (wraps the sole BattleWin_init call @0x58F1DB)."""
    s4 = popup_scale_floor(BATTLE_RECT_INSET_NATIVE, g)
    s3 = popup_scale_floor(BATTLE_RECT_GAP_NATIVE, g)
    a, t, b = dc0[0] + s4, dc0[1] + s4, dc0[3] - s4
    m = ((dc0[2] - a) - 1) // 2 - s3 + a
    d = (m - a) + s3
    unit_l, unit_r = (a, t, m, b), (a + d, t, m + d, b)
    a2, t2, b2 = d80[0] + s4, d80[1] + s4, d80[3] - s4
    m2 = ((d80[2] - a2) - 1) // 2 - s3 + a2
    rects = (unit_l, unit_r, (a2, t2, m2, b2), (m2 + s3, t2, d80[2] - s4, b2))
    if g <= 16:
        return rects
    # FAR-EDGE CONVERSION (measured 2026-09-18, dumps 232346/232440/232515): vanilla's
    # Buffer_box_sprite is HALF-OPEN (stroke drawn at R-1 / B-1) but at g > 16 these rects are
    # rendered by thunk_hud_boxframe's band map, whose footprint is INCLUSIVE (stroke lands ON
    # R / B).  Unconverted, the pair gap drew 3/3/6 px at g=22/25/40 against the faithful
    # fl(3g/16) = 4/4/7 and the right/bottom seed channels came out 1 px short.  Emitting
    # R-1 / B-1 puts the drawn far stroke where vanilla x g/16 puts it: gap == fl(3g/16) exactly.
    return tuple((l, tt, r - 1, bb - 1) for l, tt, r, bb in rects)


def battle_portrait_layout(box: Tuple[int, int, int, int], g: int,
                           native_wh: Tuple[int, int] = BATTLE_PORTRAIT_NATIVE) -> Tuple[int, int, int, int, int]:
    """(x, y, w', h', label_top) of a faction portrait in its box.  The engine
    centres on the sprite width and reuses the side margin as the top margin
    (y = T + (x - L)); the label rect starts h + 3 under y.  The law feeds the
    SAME formulas the scaled dims w' = fl(w*g/16), h' = fl(h*g/16) and the
    scaled gap.  g=16: box 8,60,123,248 -> x 17, y 69, label top 187 (pristine
    wrap_cent_6 rect top).  Ports: t_cmb_wL/wR (width read), t_cmb_hL/hR
    (height read + gap), the two Sprite_draw_2 sites -> thunk_cw_portrait
    (g/16 + parity re-blit: the portraits' 1-row scanline dither must be regenerated, never resampled)."""
    w = popup_scale_floor(native_wh[0], g)
    h = popup_scale_floor(native_wh[1], g)
    x = box[0] + int(((box[2] - box[0]) - w) / 2)       # cdq; sub; sar = trunc toward zero
    y = (box[1] - box[0]) + x
    return x, y, w, h, y + h + popup_scale_floor(BATTLE_RECT_GAP_NATIVE, g)


def battle_slot(g: int) -> int:
    """Unit slot width (vanilla 75 when ScreenWidth != 800).  Port: t_cmb_slot."""
    return popup_scale_floor(BATTLE_SLOT_NATIVE, g)


def battle_unit_name_y(box_top: int, g: int) -> int:
    """Unit-name wrap y = (box.T + inset 3) + slot.  Pristine: 70+3+75 = 148."""
    return box_top + popup_scale_floor(BATTLE_RECT_GAP_NATIVE, g) + battle_slot(g)


def battle_stats_y(box_top: int, g: int) -> int:
    """First stats line y = (box.T + inset 3) + 5.  Pristine: 70+3+5 = 78.  Port: t_cmb_stat5."""
    return box_top + popup_scale_floor(BATTLE_RECT_GAP_NATIVE, g) + popup_scale_floor(BATTLE_STATS_Y_NATIVE, g)


# ==== HUD event log (MessageWin 0x7F67F8, the MESSAGES view of the centre console) ====
# MessageWin_init 0x471D50 builds a ListBox over the seed-scaled MainWin+0xD1C rect: row stride (B-T)/5 and
# text indent (B-T)/4 are rect-derived (already scale); the font is a direct
# Font_init(hud face, 12, 0) and the row icon (interface.pcx 615,530 16x15, a pure row-pair
# scanline dither) is drawn 1:1 at row.L+4, centred on the row height.
MSGLOG_FONT_NATIVE = 12          # Font_init(hud face, 12, 0) @0x471DA7 -> font_direct_law
MSGLOG_ICON_NATIVE = (16, 15)
MSGLOG_ICON_INSET_NATIVE = 4


def msglog_icon_layout(row_x: int, row_y: int, row_h: int, g: int,
                       native_wh: Tuple[int, int] = MSGLOG_ICON_NATIVE) -> Tuple[int, int, int, int]:
    """(x, y, w', h') of the event-log row icon.  The engine's own formulas
    (MessageWin_draw_icon 0x471870: x = row.L + 4, y = row.T + (row_h - h)/2, trunc toward zero)
    fed the scaled dims and inset.  Ports: t_msg_h (height read), t_msg_icon (inset + draw ->
    own blit, law msglog_icon_pixels)."""
    w = popup_scale_floor(native_wh[0], g)
    h = popup_scale_floor(native_wh[1], g)
    return (row_x + popup_scale_floor(MSGLOG_ICON_INSET_NATIVE, g),
            row_y + int((row_h - h) / 2), w, h)


def msglog_icon_pixels(src: List[List[int]], g: int, key: int) -> List[List[Optional[int]]]:
    """Device pixels of the event-log row icon (None = keyed, dest untouched).

    The art is a pure row-pair scanline dither (even rows light, odd rows dark) over a 2-class
    shape whose arrowhead diagonal steps one column PER ROW.  Pair-granular parity rows
    (thunk_cw_portrait) take a pair's light and dark rows from different source rows, so the
    diagonal combs (measured on the 2026-09-18 20:03 shots).  Law: SHAPE = centre-aligned NN of
    the source on both axes, SHADE = dest-row parity (row 0 light) through the pair LUT the art
    itself defines: bg light src[0][1] / dark src[1][0], arrow light src[2][8] / dark src[1][8].
    Dest dims fl(w g/16) x fl(h g/16).  Port: t_msg_icon."""
    sh, sw = len(src), len(src[0])
    dw, dh = popup_scale_floor(sw, g), popup_scale_floor(sh, g)
    bg_l, bg_d, ar_l, ar_d = src[0][1], src[1][0], src[2][8], src[1][8]
    to_light, to_dark = {bg_d: bg_l, ar_d: ar_l}, {bg_l: bg_d, ar_l: ar_d}
    out: List[List[Optional[int]]] = []
    for j in range(dh):
        sy = min(((2 * j + 1) * 16) // (2 * g), sh - 1)
        lut = to_dark if (j // stripe_rows(g)) & 1 else to_light
        row: List[Optional[int]] = []
        for i in range(dw):
            c = src[sy][min(((2 * i + 1) * 16) // (2 * g), sw - 1)]
            row.append(None if c == key else lut.get(c, c))
        out.append(row)
    return out


# ==== Scanline-dithered ICON enlarge: the checkbox X sprites (fix 28, 2026-10-24) ====================
# The three 18x18 checkbox sprites (interface.pcx (227,1) / (227,20) / (227,39), +10 at load; key 9) are pixel art
# under a 1-row scanline overlay: every native row pair is a dither pair, per art class (background, X stroke,
# a few frame texels), and the dim art reuses one index as the odd-row BACKGROUND and the even-row STROKE.  They
# were enlarged by the engine's plain NN (Sprite_draw_2 at g/16; the lobby's Sprite_blit_scaled_core under the
# scale globals), so the dither came out as 1,2,1,1,2 runs at g = 22 / 25 and 2,3 at 40 -- the CLAUDE.md dither
# invariant.  Sites: the type-1 popup lists (0x405BD4: Customize Game Rules, Governor, Announcements ...), the
# CheckList rows (0x60F41C / 0x60F457: Preferences, the scenario editor's treaty list) and the lobby's CUSTOM GAME
# OPTIONS (0x47FAD4 / 0x47FD2B).  The msglog icon law, generalised to ANY row-pair scanline icon:
#   SHAPE = a MIRROR-SYMMETRIC nearest-neighbour map on both axes over dw = fl(w num/den), dh = fl(h num/den)
#           (scanicon_axis_map: the centre-aligned NN's own widths for the outer texel pairs, copied onto their
#           mirror texels; the remainder goes to the middle pair / middle texel -- the user rule "symmetry beats
#           1-px exactness": plain centre NN gives the first / last column 1 / 2 px at g = 24 and 2 / 3 at 40),
#           placed at (x + fl(offx num/den), y + fl(offy num/den)) -- the engine's own dims and origin (measured:
#           it writes exactly that rect).  Every native row / column survives.
#   SHADE = per texel, through the pair LUT the art itself defines, keyed by (index, native row parity):
#           a dither texel shows the member of its pair whose native parity the DEST row wants.  The dest row wants
#           the TOP parity qt where stripe_top(dest_y + phase, g) (the one stripe law: T = stripe_rows(g) device
#           rows per member, the chrome's grid), the other parity elsewhere.  qt = the native parity of the BRIGHTER
#           member (r + g + b of the dest buffer's own colour table, ties -> the lower index) of the DOMINANT pair
#           (most texels); every other pair keeps the art's own phase relative to it (per-pair "brighter on top"
#           would invert a pair the artist drew phase-inverted).
#   LUT   = for each key k = (index, parity) present: the strict plurality of its vertical neighbours' indices
#           (key texels neither vote nor are voted for; a tie, including all-zero, is no plurality).  k pairs with
#           mate m iff m != index, m won with >= 2 votes, (m, parity ^ 1)'s own plurality is index, and BOTH keys
#           cover >= SCANICON_MIN_MEMBER texels (a scanline field spans two row pairs in two columns at least; the
#           checked art's 2-3-texel corner bevel 0xC0 / 0xE2 is art, not dither).  Anything else (anti-aliased
#           edges, the bevel) keeps its mapped index.  The port refuses every sprite but CHECKBOX_SPRITES (the
#           plain engine draw then), so no other art -- e.g. CheckList's default 32x32 sprites -- ever reaches it.
#   phase = the rows the dest canvas's stripe grid is advanced by: 0 for the lobby (NetWin canvas, every lobby
#           layer phases from its own row 0); for the list rows the dest is the list's own child canvas, whose
#           background is the parent's grid shifted by the child's parent-local top -- list_stripe_phase of
#           Win +0x140 + +0x150 (= option_row_stripe_phase, the bars t_rowbox_ph stages; measured in the emulated
#           GOVOPTIONS / RULES lists and the PrefWin CheckList, whose captured background shows exactly that phase).
#   g <= 16: never reached (every site keeps its vanilla call).  Ports: t_ck_draw (core, Sprite_draw_2 contract),
#   t_ck_list (the three list sites), t_ck_core (the two lobby core sites).
CHECKBOX_SPRITES = (0x7794D8, 0x779504, 0x779530)
SCANICON_MIN_MEMBER = 4


def scanicon_axis_map(n: int, src: int) -> List[int]:
    """The mirror-symmetric NN map of one axis: dest index -> source index, n >= src (an enlarge).  K = the outer
    texel pairs (src // 2 - 1 for an even src, src // 2 for an odd one); B = the dest indices the centre NN gives
    texels 0 .. K-1 (nn_center_index), and the mirror indices n-B .. n-1 take texels src-K .. src-1 mirrored
    (src - 1 - nn(n - 1 - d)).  The middle n - 2B indices go to the middle texel (odd src) or the middle pair
    (even src; the left one takes the odd leftover).  Symmetric: map[n-1-d] == src-1-map[d] wherever the middle
    pair's split allows (all of it when n - 2B is even)."""
    k_out = src // 2 - 1 if src % 2 == 0 else src // 2
    b = 0
    while b < n and nn_center_index(b, n, src) < k_out:
        b += 1
    mid = n - 2 * b
    out = []
    for d in range(n):
        if d < b:
            out.append(nn_center_index(d, n, src))
        elif d >= n - b:
            out.append(src - 1 - nn_center_index(n - 1 - d, n, src))
        elif src % 2:
            out.append(k_out)
        else:
            out.append(k_out if d - b < (mid + 1) // 2 else k_out + 1)
    return out


def scanicon_pair_lut(rows: List[List[int]], key: int) -> Tuple[dict, dict]:
    """(lut, n): lut[(index, parity)] = mate for every texel class that is a scanline-dither member (law above);
    n[(index, parity)] = its texel count.  Key texels are ignored."""
    h, w = len(rows), len(rows[0])
    n: dict = {}
    for r in range(h):
        for c in range(w):
            v = rows[r][c]
            if v != key:
                n[(v, r & 1)] = n.get((v, r & 1), 0) + 1
    plural: dict = {}
    for k in sorted(n):
        v, p = k
        cnt = [0] * 256
        for r in range(p, h, 2):
            for c in range(w):
                if rows[r][c] != v:
                    continue
                for rr in (r - 1, r + 1):
                    if 0 <= rr < h and rows[rr][c] != key:
                        cnt[rows[rr][c]] += 1
        best, tie = 0, False
        for u in range(1, 256):
            if cnt[u] > cnt[best]:
                best, tie = u, False
            elif cnt[u] == cnt[best]:
                tie = True
        plural[k] = (None if tie else best, cnt[best])
    lut = {}
    for k, (m, votes) in plural.items():
        v, p = k
        if (m is not None and m != v and votes >= 2 and plural.get((m, p ^ 1), (None, 0))[0] == v
                and n[k] >= SCANICON_MIN_MEMBER and n[(m, p ^ 1)] >= SCANICON_MIN_MEMBER):
            lut[k] = m
    return lut, n


def scanicon_top_parity(lut: dict, n: dict, rgb) -> int:
    """qt: the native row parity whose member the stripe-TOP dest rows show -- the brighter member (sum of
    rgb(index), ties -> the lower index) of the dominant pair (max texels; ties -> the lower (index, parity) key).
    0 when the art has no pair (then nothing is shaded anyway)."""
    if not lut:
        return 0
    best, weight = None, -1
    for k in sorted(lut):
        v, p = k
        wgt = n[k] + n[(lut[k], p ^ 1)]
        if wgt > weight:
            best, weight = k, wgt
    v, p = best
    m = lut[best]
    bv, bm = sum(rgb(v)), sum(rgb(m))
    return p if (bv > bm or (bv == bm and v < m)) else p ^ 1


def scanicon_pixels(rows: List[List[int]], key: int, num: int, den: int, g: int, y0: int, phase: int,
                    rgb) -> List[List[Optional[int]]]:
    """Device pixels (None = keyed, dest untouched) of a scanline icon enlarged num/den whose row 0 lands on dest
    row y0, on a canvas whose stripe grid is advanced by `phase` rows (law above)."""
    sh, sw = len(rows), len(rows[0])
    dw, dh = (sw * num) // den, (sh * num) // den
    lut, n = scanicon_pair_lut(rows, key)
    qt = scanicon_top_parity(lut, n, rgb)
    ymap, xmap = scanicon_axis_map(dh, sh), scanicon_axis_map(dw, sw)
    out: List[List[Optional[int]]] = []
    for j in range(dh):
        sy = ymap[j]
        par = sy & 1
        want = qt if stripe_top(y0 + j + phase, g) else qt ^ 1
        row: List[Optional[int]] = []
        for i in range(dw):
            v = rows[sy][xmap[i]]
            if v == key:
                row.append(None)
                continue
            m = lut.get((v, par))
            row.append(m if (m is not None and par != want) else v)
        out.append(row)
    return out


def scanicon_draw(dest: bytearray, stride: int, clip: Tuple[int, int, int, int], rows: List[List[int]], key: int,
                  x: int, y: int, num: int, den: int, g: int, phase: int, rgb, offs: Tuple[int, int] = (0, 0)) -> None:
    """The core's whole draw into a byte canvas: scanicon_pixels placed at (x + fl(offx num/den), y + fl(offy
    num/den)), written only inside the half-open clip (l, t, r, b) (the dest Buffer's clip +0x20..+0x2C,
    intersected with the buffer: the engine honours it the same way, measured)."""
    px, py = x + (offs[0] * num) // den, y + (offs[1] * num) // den
    pix = scanicon_pixels(rows, key, num, den, g, py, phase, rgb)
    l, t, r, b = clip
    for j, row in enumerate(pix):
        dy = py + j
        if not t <= dy < b:
            continue
        for i, v in enumerate(row):
            dx = px + i
            if v is not None and l <= dx < r:
                dest[dy * stride + dx] = v


# ---- the lobby's panel fills (fix 28 v2, audit F37) ----
# NetWin's ~20 Buffer_box_sprite panels (window backdrop d690 = C6/41, panels d528 / title bands d618 = C4/41, the
# roster toggle cells dca8 = 0x27/0x22) fill their interior by Buffer_tile_phase of a 24x24 tile whose rows are a 1-row
# dither a,b,a,b -- tiled 1:1, so at g >= 22 the panels showed 1-row stripes beside 2-row checkbox / button faces.
# Law: after the engine box, every pixel of the box's FILL rect (exactly the rect the engine tiled; the edge sprites
# and whatever their keyed pixels show are left alone) holding a or b shows the brighter member (r + g + b of the
# dest colour table, ties -> the lower index; C4 / C6 over 41 as every chrome field) where stripe_top(dest row, g),
# the other member elsewhere -- phase 0, the NetWin canvas grid t_ck_core's boxes and the button faces sit on.  The
# pair is read per draw from the tile itself (no index table); a tile that is not a clean row dither is left alone.
# g <= 16: the vanilla call.  Port: t_nw_box.


def box_fill_rect(rect: Tuple[int, int, int, int], lw: int, th: int, rw: int, bh: int) -> Tuple[int, int, int, int]:
    """Buffer_box_sprite's fill rect (0x5E312F..0x5E317B): the half-open rect inset by the left / right edge
    sprites' width (+0x18) and the top / bottom edge sprites' height (+0x1C); a missing edge sprite insets 0."""
    l, t, r, b = rect
    return l + lw, t + th, r - rw, b - bh


def tile_scan_pair(tile_rows: List[List[int]]) -> Optional[Tuple[int, int]]:
    """(a, b) when the tile's first four rows are uniform and alternate a, b, a, b (a != b), else None."""
    if len(tile_rows) < 4 or not tile_rows[0]:
        return None
    a, b = tile_rows[0][0], tile_rows[1][0]
    if a == b:
        return None
    for r in range(4):
        if any(v != (a if r % 2 == 0 else b) for v in tile_rows[r]):
            return None
    return a, b


def panel_fill_pixel(idx: int, y: int, g: int, a: int, b: int, rgb) -> int:
    """A fill pixel on dest row y after t_nw_box: a / b -> the brighter member on stripe_top rows, the other below;
    anything else (text drawn later never reaches here) untouched."""
    if idx not in (a, b):
        return idx
    sa, sb = sum(rgb(a)), sum(rgb(b))
    top, mate = (a, b) if (sa > sb or (sa == sb and a < b)) else (b, a)
    return top if stripe_top(y, g) else mate


def checkbox_list_phase(rect1_top: int, rect2_top: int, g: int) -> int:
    """t_ck_list's phase for a list-row checkbox: the dest list canvas's parent-local top (Win +0x140 + +0x150)
    reduced to [0, P) -- option_row_stripe_phase, the grid the row bars (t_rowbox_ph) and the captured
    background already sit on."""
    return option_row_stripe_phase(rect1_top, rect2_top, g)


def checkbox_list_y(y: int, g: int) -> int:
    """The list sites' vertical placement, kept from thunk_checkbox_scale (fix 28 changes the pixels, not the
    placement): y += (16 - g) >> 1 (arithmetic shift)."""
    return y + ((NATIVE_G - g) >> 1)


# ==== type-8 OptionList (unit-stack picker / story-choice rows) =============
# The type-8 Dialog element (Dialog+0xb14) carries a sprite display ratio
# num/den at elem+0x1c/+0x20 (native 1/1).  OptionList_calculate_dimensions
# measures max sprite W/H through it, and OptionList_draw_item draws through
# the SAME pair (Sprite_draw_2 args, SCALE_NUM_G/DEN_G for the custom unit
# draw fn, the centering math, and the selection Buffer_box).  The row pitch
# is [+0x68] = fl(gap*g/16) + max(line_height, spriteH*num/den) — at 4K the
# unscaled sprite side turned the vanilla icon-dominated pitch (3+37=40)
# into a text-dominated 57 (7+50) with native-size icons.


def optionlist8_sprite_ratio(num: int, den: int, g: int) -> Tuple[int, int]:
    """Type-8 OptionList sprite ratio: the SAME fraction law as
    basewin_sprite_ratio — (num*g, den*16), never pre-floored — applied at
    the three elem num/den read sites (calc 0x610AE1; draw_item main pair
    0x610DF1; draw_item selection-box re-read 0x610FC7).  Composes with any
    native ratio; identity at g <= 16.  Every downstream consumer (measure
    maxima [+0x54]/[+0x58], Sprite_draw_2, SCALE_NUM/DEN_G, centering,
    selection box width) inherits through registers or fields, so measure
    and draw stay consistent by construction (LAW 5)."""
    return basewin_sprite_ratio(num, den, g)


def optionlist8_row_pitch(gap: int, line_h: int, spr_h: int,
                          num: int, den: int, g: int) -> int:
    """Type-8 row pitch [+0x68] with the sprite side scaled: the ENGINE's own
    formula fed scaled inputs (gap via the live thunk_q8_pitchgap floor
    idiom, sprite H via optionlist8_sprite_ratio).  line_h is whatever the
    measure font reports at runtime (already scaled at g > 16 — the measure
    and draw fonts are the same Dialog[+0x70] triple).  At g = 16 this is
    algebraically vanilla: gap + max(line_h, spr_h*num//den)."""
    n2, d2 = optionlist8_sprite_ratio(num, den, g)
    return popup_scale_floor(gap, g) + max(line_h, (spr_h * n2) // d2)


OPTIONLIST8_LABEL_PAD = 4      # draw_item's native icon-to-label gap (lea ecx,[edx+ebx+4] @0x610D98)


def optionlist8_label_pad(g: int) -> int:
    """The type-8 icon-to-label gap at g: fl(4*g/16) = g>>2 above native, the native 4 at g <= 16.
    ONE owner for both its consumers (optionlist8_text_x, optionlist8_row_width)."""
    return OPTIONLIST8_LABEL_PAD if g <= NATIVE_G else g >> 2


def optionlist8_text_x(row_x: int, max_spr_w_scaled: int, g: int) -> int:
    """Type-8 row label X (draw_item local_10): row x + the measured sprite
    column [+0x54] (already scaled by the ratio law) + the native 4px
    icon-to-label gap scaled fl(4*g/16) = g>>2 (site 0x610D98).  Identity at
    g <= 16 (g>>2 == 4)."""
    return row_x + max_spr_w_scaled + optionlist8_label_pad(g)


def optionlist8_row_width(max_text_w: int, margin: int, max_spr_w_scaled: int, g: int) -> int:
    """Type-8 row width [+0x64] (OptionList_calculate_dimensions 0x610B6D..0x610B84): the engine's
    maxText [+0x5c] + 2*[+0x40] + the sprite column [+0x54], grown by EXACTLY the label-x shift
    optionlist8_text_x adds over the native 4 (optionlist8_label_pad(g) - 4).  draw_item clips the
    label to [row_x + sprW + pad, row_x + [+0x64]), so a native row width under a scaled pad cut the
    longest label by pad - 4 px (6 @g40, 3 @g25).  The dialog width [+0x5c] (calc tail 0x610C25),
    the row window and the box inherit it through the engine's own arithmetic.  Identity at g <= 19
    (g>>2 == 4)."""
    return max_text_w + 2 * margin + max_spr_w_scaled + optionlist8_label_pad(g) - OPTIONLIST8_LABEL_PAD


def optionlist8_list_width(col_w: int, gap: int, cols: int, xs: int, g: int) -> int:
    """Type-8 OptionList row-window width [D+0x5c] (OptionList_calculate_dimensions tail 0x610C25..0x610C41):
    max(xs, (col_w + G)*cols - G) with G = the SAME scaled gap the draw stride uses (optionlist8_row_origin_gap,
    site 0x610C84).  The engine read the native gap here while drawing with the scaled one, so a multi-column
    list drew (cols-1)*(G-gap) px past its window and the last column's labels were clipped (unit-stack picker,
    4K shot 225617, 2026-10-11).  g <= 16: G = gap, vanilla."""
    gg = optionlist8_row_origin_gap(gap, g)
    return max(xs, (col_w + gg) * cols - gg)


def optionlist8_row_origin_gap(gap: int, g: int) -> int:
    """Type-8 draw-side gap read (site 0x610C84): the same scaled gap the
    calc used, re-derived from the never-written native field — the draw
    loop's row-y offset is then the engine's own (gap_scaled >> 1) and the
    multi-column stride is rowW + gap_scaled, consistent with the calc's
    reserve (LAW 5; identity at g <= 16)."""
    return popup_scale_floor(gap, g)


# ==== ornate popup interior (type-6/2 backdrop &0x6846b0) ===================
# Buffer_box_sprite paints a def's interior by tiling params[8] (the fill
# sprite) over the rect inset by the def's OWN edge-sprite dims: left inset
# = params[6].w, top = params[4].h, right -= params[7].w, bottom -=
# params[5].h, each only when that edge slice is non-null (decompiled
# 0x5e2dd3, final Buffer_tile block).  The ornate def's fill is a 1px-pair
# scanline stripe: band-map-enlarging the SMALL render NN-duplicates those
# rows (uneven at fractional g -> the 1600x1200 color banding; 2/3-blocks at
# 4K).  Fix (the popup-interior-stripes recipe): devfill lays the interior
# at DEVICE density first, and the hollow-clone ERASES the fill region of
# the small render back to key 9 so the keyed band-map blit skips it — the
# erase boundary is the same native fill region the engine painted, so it
# meets the border bands pixel-for-pixel by construction (no parallel band
# formula).  Edge Buffer_tile_mask passes lie OUTSIDE the fill region, so
# the metal edge look (fill-masked) is untouched.


def boxdef_fill_region(l: int, t: int, r: int, b: int,
                       lw: int, th: int, rw: int, bh: int
                       ) -> Tuple[int, int, int, int]:
    """The engine's own fill-inset law (Buffer_box_sprite final tile block):
    rect inset per-edge by that edge sprite's cross dim, 0 for a null slice.
    Pass lw/th/rw/bh = 0 for null slices; returns (l', t', r', b')."""
    return l + lw, t + th, r - rw, b - bh


def hollow_interior_erase(small_w: int, small_h: int,
                          lw: int, th: int, rw: int, bh: int):
    """Erase rect for the hollow-clone (thunk_hollow_keyint): the fill region
    of the SMALL render (whose rect is {0,0,small_w,small_h}), or None when
    degenerate (r' <= l' or b' <= t' — tiny rects at deep insets must skip
    the erase, never fill a negative span).  Only reachable at g > 16 (the
    clone tail-jmps native Buffer_box_sprite at g <= 16), and only engaged
    for fill-bearing defs (params[8] == 0 skips) — so flat/hollow defs and
    the native look are bit-identical no-ops."""
    l2, t2, r2, b2 = boxdef_fill_region(0, 0, small_w, small_h, lw, th, rw, bh)
    if r2 <= l2 or b2 <= t2:
        return None
    return l2, t2, r2, b2


# The ornate def (&0x6846B0) needs a DEEPER erase than the generic fill-region
# law: its nine cells are 61x44 slices of interface.pcx (3x3 grid at 296,711;
# init @0x453d66), where each edge/corner cell is a narrow METAL band plus
# transparent-key filler, and Buffer_box_sprite's per-cell Buffer_tile_mask
# pass paints the fill's stripes into those keyed holes.  Erasing only the
# engine fill region (inset 61/44) leaves the edge margins' mask-pass stripes
# riding the band-map NN -> the user-visible "banding on the sides"
# (1600x1200, 2026-08-01).  The metal cores measure EXACTLY (art-measured,
# crisp 1.00/0.00 column/row profiles; corner inner quadrants pure key):
ORNATE_METAL_INSETS = (8, 8, 9, 6)   # left, top, right, bottom — native px


def ornate_interior_erase(small_w: int, small_h: int):
    """Erase rect for the ORNATE def in thunk_hollow_keyint: inset by the
    metal-core widths, not the fill-region insets — everything inboard of the
    metal is either transparent key (erase is a no-op) or mask-pass stripes
    (the thing that bands).  Vanilla shows the same masked-fill stripes
    there, and the devfill underlay reproduces them at device density, so
    content is preserved.  None when degenerate (skip the erase)."""
    lw, th, rw, bh = ORNATE_METAL_INSETS
    return hollow_interior_erase(small_w, small_h, lw, th, rw, bh)


# ---------------------------------------------------------------------------
# pf-align popup-type gate (v8, 2026-08-01)
# ---------------------------------------------------------------------------
# The pf_union_align/pf_frame_align pair rewrites the popup body-frame rects
# against the TITLE stash (quit law / container arms).  Those laws were
# censused on the FLAT (popup type 0) and SLIDE (type 5) families only; the
# ORNATE families (type 6 in-game popups like the unit-stack picker, type 2)
# lay their frame from the content-margin sum [popup+0x30f0], which ALREADY
# scales (trace 2026-07-31: 47@g40 / 29@g25 ~= 19 native x g/16) — the
# quit-law override parked the picker frame on the title OUTER column
# (l = titleL - delta = 7 dev @4K).  The raw field [popup+0x30ac] stores
# popup_type * 10000 (Popup_on_draw_background divides by 10000; 1000 is the
# hidden-popup sentinel).

def popup_frame_rewrite_applies(raw_30ac: int) -> bool:
    """True iff the pf-align pair may rewrite this popup's frame rects.
    Keyed on the RAW +0x30ac value exactly as the thunks compare it
    (unsigned band test, no division): type 0 (flat) and type 5 (slide)
    take the rewrite; every other type (2/6 ornate, 1000 hidden, future
    values) passes through to the engine's own already-scaled arithmetic."""
    return 0 <= raw_30ac < 10000 or 50000 <= raw_30ac < 60000


# ---------------------------------------------------------------------------
# ornate (type-6/2) picker frame -> container arm + type-8 ring bottom
# (2026-08-01; v9 supersedes the 08-01b title rewrite — user rejected the
# shrunken title box: the TITLE keeps its engine geometry, the FRAME moves)
# ---------------------------------------------------------------------------
# The ornate in-game popup family (unit-stack picker et al.) draws its
# content frame through the SAME final d5a0 site (0x406238 -> pf_union
# chain) and its title inner d618 through the SAME site as the flat popups,
# and banding v2 already scales both the title's +3 inner step and the
# ring's +-3 expansion (live-byte diff 2026-08-01: sites 0x406078/0x406211
# are cave calls).  So "frame collinear with the title INNER stroke" for the
# picker is the SAME user-verified relation as the type-1/2/4 container arm:
# itemlist_container_edge_l/r(title_stash, g) = stash +- popup_pad(3, g).
# Screenshot check (builds 39ad8f56): required left shift = +7 @g40 / +4
# @g25 == popup_pad(3, g) exactly.

def ornate_title_outer_bottom(t_engine: int, g: int) -> int:
    """Ornate title-box OUTER bottom (2026-08-01d follow-up, user report
    "inner frame stroke is partially overlapping the title font"): vanilla's
    title outer box spans win+13 .. win+37 (height 24); the engine's b at
    g>16 is win+9+s(0x1c) (its 0x1c is banding-scaled but the +9 stays
    native), which after the inset arm raised t to win+s(13) left only a
    19px text slot for the 29px scaled title ink @g40 (measured: ink rows
    797-825 covering the inner top stroke at 797-798).  Room below is
    confirmed: the content-frame ring top sits at win+107 @g40 while
    faithful b = win+s(37) = 92 (gap 15 ~= the faithful rows-relative gap).
    v5 wrote b' = t_engine + s(37) - 13 assuming t_engine == 13; at g>16 the
    engine top is 9 + ps3 + 3 (ornate_title_engine_top), so that landed 2px
    low @g25 / 6px low @g40.  v7 (2026-08-23c): b' = s(37) popup-local,
    whatever the engine top — the same value for t_engine == 13 (the JS
    port / prior goldens) and the faithful one otherwise.  Purely visual
    (the header/list layout was computed from fields earlier; b feeds only
    the title draws and the text centering)."""
    if g <= NATIVE_G:
        return t_engine + 24
    return popup_scale_floor(37, g)


def nested_frame_pad(g: int, body_only: bool = False) -> int:
    """LAW - the popup's NESTED frame inset (thunk_popup_nestpads @0x406211; the
    listbox / field container drawn from the list rect +-pad).  Vanilla: rect =
    list +-3 with a 1px stroke drawn AT the rect edge -> the visible channel
    between stroke and rows is 3-1 = 2.  At g>16 the thick chain (content_frame
    -> pf_union_align -> box_thick) draws the K-wide stroke OUTSIDE the rect
    (measured Select Special Ability: rect L 22 -> stroke [21] @g22, rect 25 ->
    [23,24] @g25), so with pad = floor(3g/16) the channel became 4/4 + the
    child-x compensation = the user's "channel not quite correct".  The lawful
    inset under that convention is the scaled CHANNEL itself: scale_px(2, g)
    (3 @g22/g25, 5 @g40).  Native identity: 3.
    CORRECTION (verify16): the OUTSIDE premise is stale.  Today the stroke is
    drawn INSIDE the rect, inclusive [l..r] x [t..b] (thunk_box_thick_hollow
    `xor ebx, ebx` = no outward grow; thunk_fe_bandmap dst W = r - l + 1), so
    this pad is the stroke's outer edge and the drawn channel is pad - K.
    The type-1 checkbox ring no longer uses this pad on any side: the
    pf_union hug arm reads D (itemlist_ring_hug, fix 16 l/r, fix 17 t/b).

    v3 (2026-09-18, untitled version popup 4K shot 20260918-003046): the
    above is the LIST-container convention and v2 applied it to all three
    source-rect paths of 0x406211.  On the BODY-ONLY path (a drawn d528 text
    box and no list union: [+0x30d4] != 0 and ([+0x2350] == -1 or art)) the
    ring nests around ANOTHER STROKE, both drawn FLAT at their rect edge, so
    the pad is the stroke PITCH: vanilla 3 = 1px stroke + 2px channel ->
    popup_pad(3, g), the same pitch the pf-align pair already gives the right
    edge (body_outer_edge_r - body_inner_edge_r).  Measured before the fix:
    pitch 5 on L/T/B vs 7 on R @g40.  `body_only=False` is unchanged v2."""
    if g <= NATIVE_G:
        return 3
    return popup_pad(3, g) if body_only else scale_px(2, g)


def popup_header_reserve(native_21b8: int, titled: bool, raw_30ac: int,
                         faction_quote: bool, g: int) -> int:
    """LAW - thunk_scale_header v2: the header reserve [+0x30e8] copied from
    [+0x21b8] in BasePop_calc (0x6039b3, the [0xa14]==0 branch).  v1 scaled
    TITLED popups only (38 -> popup_pad(38)); an UNTITLED popup's 18 stayed
    native at every g, so its whole top group (field T = 18-3, ring top 12,
    art top 12, text) sat 12 DEVICE px under the window edge instead of
    12*g/16 (version popup @g40: ring top +6 vs faithful +30).  v2: untitled
    FLAT/SLIDE popups scale too.  Excluded: the faction-quote singleton
    (thunk_d528_inset carries its own popup_pad(12)-12 top compensation) and
    the ORNATE family (its untitled 27 is ornate_untitled_content_top's).  [+0x30e8]
    feeds box_h, so the box grows by the same amount.  Identity at g=16."""
    if g <= NATIVE_G:
        return native_21b8
    if titled:
        return popup_pad(native_21b8, g)
    if faction_quote or not popup_frame_rewrite_applies(raw_30ac):
        return native_21b8
    return popup_pad(native_21b8, g)


def untitled_virtual_title_bottom(content_top: int, g: int) -> int:
    """LAW - thunk_untitled_stash.  An untitled FLAT/SLIDE popup skips the
    engine's whole title block (je @0x405f84), so thunk_pf_title_stash never
    runs and the pf-align pair / artalign read the PREVIOUS popup's
    g_title_left/right (version popup: text-box right edge 178px short).  The
    stash thunk runs the SAME inset thunks the titled path runs on the same
    window rect (one cascade) to store the VIRTUAL band L/R, and arms the
    band key so artalign's x law applies.  The armed key also selects
    fieldpads' band-anchored T = B + 2*(ps3 + delta); an untitled popup has
    no band, its T is the engine's content_top - ps3, so the virtual bottom
    is chosen to make that arm land there exactly:
        B = content_top - ps3 - 2*(ps3 + delta)
    content_top = [+0x30e8] + [+0x30e0] (popup-local)."""
    ps3 = popup_pad(3, g)
    return content_top - ps3 - 2 * (ps3 + title_grow_delta(g))


def flat_art_anchor(field_top: int, g: int) -> int:
    """LAW - thunk_popup_nestpads v3's anchor pre-add for every KEYED flat/slide
    body-only popup (titled or untitled): g_field_anchor = T + frame_grow_delta.
    artalign's flat math (popup_art_y) subtracts a delta calibrated 2026-07-03
    against a ring that grew OUTWARD; the 2026-07-09 channel fix made the ring
    draw FLAT at T - popup_pad(3), leaving the art delta ABOVE it (measured
    Quit: 928 vs 931 @g40, 437 vs 438 @g25, flush @g22; pristine: same row).
    The pre-add cancels it -> art top ON the ring top at every g.  The RING
    stays (band->ring gap 9/4/3 vs vanilla 7.5/4.7/4.1 is closer than the
    6/3/3 a ring move would give).  Ornate+art popups are excluded: fieldpads
    already pre-adds for them (g_fp_ornart)."""
    return field_top + title_grow_delta(g)


def ornate_dialog_child_x(x_engine: int, g: int, pad_x: int = 3) -> int:
    """Ornate (type-6/2) dialog child-area x correction (2026-08-01d, user
    report "the unit selection box has its left edge overlapping the left
    frame stroke of the unit box").  Vanilla: child x = win+19 (margin sum),
    content frame = child-3 = win+16, selection ring x = child x -> ring sits
    3 native px inside the frame.  TWO-POINT pixel measurement (4K 131629 +
    1600 222653): the engine's child x arrives at win + s(16) + 3 at both g
    (43 @g40, ~28 @g25) — the chain scales 16 of the 19 and keeps one +3
    native, so the ring hugged the (faithfully-placed s(16)) frame with a
    1-2px gap instead of s(3)=7.  Correction at the child-x selection site
    (0x602b88, after the [0x21cc]-override/global merge): x += ps3 - 3,
    turning s(16)+3 into s(16)+ps3 == fl(19g/16) at every g in [16,40]
    (floor split is exact: fl(16g/16) = g).  Identity at g <= 16 (gate) and
    wherever ps3 == 3 (g <= 21).  The ring WIDTH is faithful and untouched
    (pristine: 50 native x 2.5 = 125 measured — the 'too wide' suspicion
    was the gap deficit).
    2026-08-14 CORRECTION (trace, not pixels): the engine's child x global
    0x9b8cec is written at 0x604292 as [30b4]+[30f0]+[30e0]+[30d8] = 47
    @g40 = fl(19g/16) already — for the stack picker AND the EDITORWHO
    picker (same inputs).  So the "s(16)+3" premise was a misinference; the
    +ps3-3 is an EFFECT-verified compensation for the ornate family (stack
    picker user-verified with it; EDITORWHO's gutters become symmetric 51/51
    vs vanilla 47.5/52.5, <=1.5 native/side, accepted).  Do not re-derive
    the frame relation from this docstring — measure."""
    # 2026-08-29 REFINEMENT (Select Special Ability, engine-measured @1024/1920/1600): the one native
    # +3 the chain keeps is the popup's pad term [+0x30e0] = (3*[+0x21c0])/2 (3 for the stack picker /
    # EDITORWHO with [+0x21c0]=2; 0 for the ability listbox).  With pad 0 the engine child x is already
    # fl(19g/16) and the +ps3-3 pushed the rows 1 px right.  So the compensation is
    # popup_pad(pad_x) - pad_x: identical for pad 3, zero for pad-free popups (thunk_orn_childx v2
    # gates on [+0x30e0] != 0).
    if g <= NATIVE_G or pad_x == 0:
        return x_engine
    return x_engine + popup_pad(pad_x, g) - pad_x


# fix 26 v2 (2026-10-24): every ornate (type 2/6) chrome element sits on vanilla's HALF-OPEN axis x <-> W - 1 - x at
# g > 16.  Vanilla 1024: title band strokes at cols 13 and W-14, union box likewise -- the same axis as the child
# windows (rows, OK / CANCEL bar), so line -> bar is 12 | 12.  The scaled chrome is drawn INCLUSIVE (band-map), so a
# rect whose R mirrors L (R = W - L) lands on x <-> W - x, one px right of the child windows: line -> bar n | n+1,
# ring -> rows 6 | 7 @g40.  The ornate arms therefore pull their R in by ORNATE_HALF_OPEN (the title stash, the
# unkeyed field R, the content-frame ring); the frame's right band mirrors on the same axis (ornate_popup_*).
ORNATE_HALF_OPEN = 1


def ornate_title_rect(l: int, t: int, r: int, g: int) -> tuple[int, int, int, int]:
    """thunk_pf_title_stash v7 (2026-08-23c) — the ornate (type 6/2) title
    rect AS DRAWN, popup-local: l/t/r moved so the top-left lands at s(13)
    exactly, b = s(37).  The v4-v6 arm added ornate_title_inset_delta(g) =
    s(13)-13 to the ENGINE rect assuming its top was the native 13 — but at
    g>16 the engine chain is 9 + ps3 + 3 (15 @g25, 19 @g40; the +3 step is
    banding-scaled), so the band landed at 22/38 instead of 20/32 and its
    bottom at 59/98 instead of 57/92 (4K probe 2026-08-23c: rect 38,38,
    1703,98 vs the header reserve 117 = s(47) — the 1px field channel and
    the "text crowding the frame" were this 6px, NOT the field or the text;
    the engine's 30e8 / T / text chain is proportionate already).  Native
    identity: t = 13 -> delta 0, b = 37.
    v9 (fix 26 v2): r - ORNATE_HALF_OPEN at g > 16 -- the inclusive-drawn band's R stroke lands on col
    W - 1 - s(13), vanilla's half-open mirror of the left stroke (the stash, and every ring / text box / field
    derived from it, follows)."""
    if g <= NATIVE_G:
        return (l, t, r, t + 24)
    d = popup_scale_floor(13, g) - t
    return (l + d, t + d, r - d - ORNATE_HALF_OPEN, popup_scale_floor(37, g))


def ornate_title_engine_top(g: int) -> int:
    """The engine's ornate title rect top before the stash arm (for tests and
    the docs — the thunk reads the rect itself): the native +9 / +3 / +1
    chain with banding v2's scaled steps = 9 + ps3 + ceil(g/16).  Measured:
    13 native, 15 @g25 (run 24), 19 @g40 (probe 2026-08-23c)."""
    return 13 if g <= NATIVE_G else 9 + popup_pad(3, g) + ((g + 15) >> 4)


def ornate_title_inset_delta(g: int) -> int:
    """Ornate (type-6/2) title-box inset correction (2026-08-01c, user report
    "channels between the title frame's upper and side edges and the edge of
    the modal are wrong").  Vanilla insets the title box 13 native px from
    the window edge on LEFT, TOP and RIGHT (engine chain +9+3+1 sides /
    +9+4 top; pristine StackPicker.png measure: sides 12.1, top ~14 native,
    frame at 16); at g>16 those constants stay native while everything else
    scales, parking the title strokes against the border art (patched-4K
    measure: win+12/13 on all three edges).  The faithful inset is
    popup_scale_floor(13, g); this delta shifts the engine's computed rect
    l/t/r by the difference.  The BOTTOM stays with the engine's value:
    banding v2 already scales its 0x1c component (measured b = win+9+s(28)
    @g40) and the list block sits directly beneath it — pushing b to s(37)
    would cross the content-frame ring top (measured collision at g40).
    Identity at g<=16.  The v9 picker frame (title stash + ps3) then lands
    at win + s(13) + s(3) ~= the faithful s(16) frame channel.
    NB (2026-08-23c): this is the delta for a NATIVE-13 top only; the engine
    top at g>16 is ornate_title_engine_top(g) — the shipped thunk (v7) uses
    ornate_title_rect, which lands at s(13) regardless."""
    return popup_scale_floor(13, g) - 13


def ornate_picker_takes_container_arm(raw_30ac: int, dlg_type: int,
                                      body_h: int, art_sprite: int,
                                      title_ptr: int) -> bool:
    """True iff an ornate popup's content frame takes the title-INNER
    container rewrite (l/r = itemlist_container_edge_l/r of the title
    stash).  Keyed on the RAW +0x30ac value as the thunk compares it:
    type 2 or 6 (ornate), a live dialog (dlg != -1), no body text-box
    (body_h == 0 — the d528 path is engine-laid and untouched), no art
    sprite, and a present title string (the stash is only meaningful when
    THIS popup drew a title this call).  Everything else passes through."""
    ornate = 20000 <= raw_30ac < 30000 or 60000 <= raw_30ac < 70000
    return (ornate and dlg_type != -1 and body_h == 0
            and art_sprite == 0 and title_ptr != 0)


def ornate_union_takes_outer_arm(raw_30ac: int, dlg_type: int,
                                 body_h: int, art_sprite: int,
                                 title_ptr: int) -> bool:
    """True iff an ornate popup's ring takes the UnionRect rewrite
    (thunk_pf_union_align v13): type 2 or 6, a live dialog, a body text box
    (body_h != 0), no art, a title drawn this call.  That is the engine's
    UnionRect(text box, dialog) path (see union_ring_takes_container_arm):
    the ring nests the d528 text box on the title OUTER column, so

        ring.l = title stash l, ring.r = title stash r   (body_outer_edge_l/r)
        ring.t = union_ring_top(local.t)                 (pitch ps3)

    Measured: base-screen #RENAME (type 60000, dlg 4) vanilla @1024 ring
    175 / 848 == title outer, text box 178 / 845 == title inner; ours @g40
    before the fix ring 35 / 1715 local vs the stash 32 / 1717, pitch 5.
    The same shape with body_h == 0 is ornate_picker_takes_container_arm;
    ornate body-only, art and untitled popups keep the engine arithmetic."""
    ornate = 20000 <= raw_30ac < 30000 or 60000 <= raw_30ac < 70000
    return (ornate and dlg_type != -1 and body_h != 0
            and art_sprite == 0 and title_ptr != 0)


def ornate_container_edge_l(title_stash_l: int, g: int) -> int:
    """Ornate (type-6/2) container-frame LEFT edge (2026-08-01f, user report
    "the frame stroke on the unit box is not quite flush with the inner
    stroke of the title box").  The ornate title chain renders BOTH its
    strokes through thunk_box_thick, whose 9-slice blit draws the stroke
    frame_grow_delta(g) OUTSIDE its rect (measured 4K shot 140121: outer
    1155 / inner 1162 = ps3 apart — both grown, the delta cancels in their
    gap), while the container frame draws FLAT at its rect.  v9's borrowed
    type-1/2/4 arm (stash +- ps3, whose titles draw flat) therefore landed
    the frame delta INSIDE the drawn title inner (measured 1165/2673 vs
    inner 1162/2676 = +-3 = +-frame_grow_delta(40), symmetric).  Flushness
    of the DRAWN edges needs the same compensation the quit family already
    carries (body_outer_edge_r = title_right + delta):

        ornate container.l = stash_l + popup_pad(3, g) - frame_grow_delta(g)

    Identity vs the v9 form wherever delta == 0 (all g < 24, incl. native)."""
    return itemlist_container_edge_l(title_stash_l, g) - title_grow_delta(g)


def ornate_container_edge_r(title_stash_r: int, g: int) -> int:
    """Ornate container-frame RIGHT edge — mirror of _l (see its docstring):
    stash_r - popup_pad(3, g) + frame_grow_delta(g)."""
    return itemlist_container_edge_r(title_stash_r, g) + title_grow_delta(g)


def ornate_picker_container_edge_r(title_stash_r: int, margin_r_dev: int, g: int) -> int:
    """Ornate PICKER container ring RIGHT edge (thunk_pf_union_align v14, 2026-10-16; the scenario editor's
    SELECT A FACTION, its 810-wide list popup and the unit stack picker).  Vanilla's ring for a list-only popup is the engine's list
    rect +- 3 (0x406205 path: L = list_l - 3, R = list_l + listW + 3 = box_w - [+0x30f4] + 3 when the list
    spans the margins).  Against the title (inner R = box_w - 16) that is flush only when the right margin
    is the canonical 19 = 13 + 3 + 3; SELECT A FACTION's is 21 (frida_selectfaction 1024 log: ring 16 / 619,
    title inner 16 / 621, rows 19..616 -> channel 2 both sides), so vanilla parks the right stroke 2 px
    INSIDE the title inner.  ornate_container_edge_r assumed flush for every picker: +6 device px @g40
    (measured ring 1552 vs vanilla x 2.5 = 1546.5, rows->stroke 12 vs 5).

        R = ornate_container_edge_r(stash_r, g) - (margin_r_dev - popup_scale_floor(19, g))

    Title-anchored like the left edge (user 2026-08-01: the title keeps its engine geometry, the frame
    moves; flush where vanilla is flush), minus the scaled margin excess.  Popup_calc sets [+0x21b4] = 21 for
    EVERY ornate 6/2 popup (0x404E19 -> BasePop_calc 0x6039E9 -> [+0x30f4], scaled fl(21g/16)), so every
    popup this arm admits moves left by fl(21g/16) - fl(19g/16) -- the unit stack picker too (pristine
    StackPicker.png: its ring R also sits ~2 native px inside the title inner); within +-1 device px of ceil(619 g/16) - 1 at every g in
    17..40 (the engine list form fl(19g/16) + fl(listW g/16) + ps3 misses by 2 at g = 19/21/25/31/35/37).
    fix 26 (ornate_popup_margin_r): at g > 16 Popup_calc now writes 19, so in game the excess term is 0 and the ring
    is flush with the title inner on both sides; the law stays general in margin_r_dev."""
    return ornate_container_edge_r(title_stash_r, g) - (margin_r_dev - popup_scale_floor(ORNATE_MARGIN_L_NATIVE, g))


# Ornate (type 6/2) BODY text box d528, LEFT edge (thunk_pf_frame_align v9,
# 2026-10-11).  Vanilla chains the ornate content margin from the title:
# [popup+0x30f0] = 19 = title inset 13 + pitch 3 + pitch 3, so the engine's
# text box L = margin - 3 (+ the content_off_x / pad_x addends) lands ON the
# title INNER stroke (pristine 1024 #RENAME: text box 178 == title inner 178).
# At scale the three terms floor separately: margin fl(19g/16) vs title stash
# fl(13g/16) + 2*ps3 -> the box sits 1 px RIGHT of the title inner at every
# g in 17..40 except 32 (measured #RENAME: 4K box 1086 vs inner 1085, pitch
# to the ring 8 left / 7 right; 1600x1200 279 vs 278).  The fix replaces the
# margin term by its title-anchored value, keeping every other addend.
ORNATE_MARGIN_L_NATIVE = 19        # ornate content margin = 13 + 3 + 3


def ornate_text_box_takes_inner_arm(raw_30ac: int, art_sprite: int, title_ptr: int,
                                    margin_l_dev: int, g: int) -> bool:
    """True iff the ornate d528 text box takes the title-anchored LEFT edge:
    g > 16, popup type 2 or 6 (raw +0x30ac band), no art sprite (an art
    popup's box starts right of the image), a title drawn this call (the
    stash is only fresh then), and the vanilla identity the relation rests
    on — the device margin [+0x30f0] IS the canonical fl(19g/16).  A popup
    with any other margin keeps the engine arithmetic."""
    ornate = 20000 <= raw_30ac < 30000 or 60000 <= raw_30ac < 70000
    return (g > NATIVE_G and ornate and art_sprite == 0 and title_ptr != 0
            and margin_l_dev == popup_scale_floor(ORNATE_MARGIN_L_NATIVE, g))


def ornate_text_box_edge_l(local_l: int, margin_l_dev: int, title_stash_l: int, g: int) -> int:
    """The ornate text box's LEFT edge: the engine local with its margin term
    swapped for title stash + 2*ps3, i.e. body_inner_edge_l(stash) plus any
    content_off_x / pad_x the engine added.  The body-only ring (nestpads,
    pad ps3 around this same local) then lands on the title OUTER column,
    the vanilla relation, instead of 1 px inside it."""
    return local_l - margin_l_dev + title_stash_l + 2 * popup_pad(3, g)


def ornate_textfollow_applies(raw_30ac: int, art_sprite: int, ext_win: int,
                              key_popup: int, popup: int, g: int,
                              key_engine_x: int = 0, engine_x: int = 0) -> bool:
    """thunk_pf_textfollow v3 ornate arm: the body text X follows the text
    box iff frame_align v9's ornate arm moved THIS popup's box (key_popup ==
    popup; the key is cleared at every frame_align entry and set only by that
    arm) FOR THIS engine text X (key_engine_x == engine_x: the arm records the
    engine X its box belongs to, so a later popup reusing the heap address
    that draws body text without a d528 pass keeps its own engine X), plus
    textfollow's own gates (g > 16, no art, not anchored, type 2/6).
    X = ornate_text_x(g_d528_left, g)."""
    ornate = 20000 <= raw_30ac < 30000 or 60000 <= raw_30ac < 70000
    return (g > NATIVE_G and art_sprite == 0 and ext_win == 0 and ornate
            and key_popup != 0 and key_popup == popup and key_engine_x == engine_x)


def ornate_text_x(text_box_l: int, g: int) -> int:
    """Body text X inside the moved ornate text box: one ps3 pitch, the same
    as every flat popup (textfollow v2) and vanilla's native 3.  The engine
    X was text_box_l(engine) + ps3, so the text moves by exactly the box's
    shift and the draw WIDTH is untouched: every line break is unchanged."""
    return text_box_l + popup_pad(3, g)


def optionlist8_ring_bottom(y_plus_1: int, pitch: int, g: int) -> int:
    """Type-8 selection-ring bottom (draw_item Buffer_box, site 0x610FC2):
    vanilla writes y+1 + pitch - 3, where the 3 is the NATIVE row gap
    (pitch = gap + max(line_h, spr_h_scaled)).  With the gap scaled
    (popup_scale_floor) but the -3 constant native, the ring runs
    gapS - 3 rows past its cell and the NEXT item's back-erase
    (Buffer_copy_4, exactly pitch tall) wipes the bottom stroke — the
    user-visible "selection box cut off at the bottom" (verticals end at
    the cell boundary: measured cy+99 @g40, cy+61 @g25).  Subtracting the
    same floor idiom the pitch used keeps the ring inside its cell at
    every g (off = gapS>>1 <= gapS-2 for gapS >= 3) and is the identity
    at g = 16."""
    return y_plus_1 + pitch - popup_scale_floor(3, g)


# ==== base production picker (ProdPicker = BaseWin+0xA1C, obj 0x6A8044) =====
#
# MEASURED 2026-08-03 by hook_prodpicker.js v2/v3 at FOUR resolutions
# (3840x2160 g=40, 1600x1200 g=25, 1920x1080 g=22, 1024x768 g=16 = vanilla).
# Every constant below is a pristine magnitude read off the g=16 run, so the
# laws are proportionate to VANILLA and not to the already-patched state.
#
#   BaseWin canvas   = fl(758*g/16) x fl(490*g/16)   [the closed base-screen arc]
#   picker canvas    = fl(BaseWin*g/16)              <-- THE DOUBLE-SCALE BUG
#   colw             = (BaseWin_w - 81)/5            [true width -> grid is right]
#   pitch            = 108 at every g                <-- NEVER SCALED
#   cell interior    = resolution-invariant (cell h 105, fac icon 46, zoom 72)
#
PRODPICKER_PITCH_NATIVE = 108     # ProdPicker_ctor 0x492689 -> +0xA838 seed
PRODPICKER_GRID_MARGIN = 0x51     # build_items 0x493977 `sub ecx,0x51` (23+55+3)
PRODPICKER_CELL_L = 0x1B          # draw_cell rect, 0x4927EF..0x492853
PRODPICKER_CELL_R = 0x18
PRODPICKER_CELL_T = 4
PRODPICKER_CELL_B = 1
PRODPICKER_BTN_W = 100            # ProdPicker_exec 0x4949B3 -> +0xB70
PRODPICKER_BTN_H = 0x14           # push at 0x494B6E (per-button)
PRODPICKER_BTN_GAP = 3            # step = btn_w + gap = 103 (0x67)
PRODPICKER_BTN_PAD = 0x20         # centring pad, layout 0x494AD4..0x494B21
PRODPICKER_BTN_ROW_GAP_Y = 8      # button row y = pitch*vis_rows + 8
PRODPICKER_FONT_CELLNAME = 12     # Font_init 0x4939DB, FIXED (never scaled)
PRODPICKER_FONT_BUTTON = 14       # Font_init 0x493A61, FIXED (never scaled)
PRODPICKER_FONT_STATS = 10        # 0x493A4B max(10, colw/15); at native colw=135
                                  # the max floor always wins, so vanilla == 10


def prodpicker_window_size(basewin_w: int, basewin_h_abs: int,
                           g: int) -> Tuple[int, int]:
    """ProdPicker window size (GraphicWin_init @0x494915, base-screen variant).

    The picker passes (0, 0, BaseWin+0x4C4, -(BaseWin+0x4C8)) — i.e. it reads
    the parent's canvas dims, which the base-screen arc has ALREADY scaled to
    device space.  Its parent argument is BaseWin_g, so thunk_basewin_gwinit's
    child arm (meant for children whose coords are NATIVE) multiplies them by
    g/16 a SECOND time.  Measured: 1895x1225 -> 4737x3062 @g=40,
    1184x765 -> 1850x1195 @g=25, 1042x673 -> 1432x925 @g=22, identity @g=16.

    The law is therefore an EXEMPTION, not arithmetic: this child is already
    device-space, so its rect passes through untouched at every g.  Expressing
    it as a function keeps the port honest — thunk_basewin_gwinit must return
    exactly these values for ecx == 0x6A8044.
    """
    return basewin_w, basewin_h_abs


def prodpicker_double_scaled_window(basewin_w: int, basewin_h_abs: int,
                                    g: int) -> Tuple[int, int]:
    """The BUG the exemption removes — kept so the sweep can assert the two
    forms agree ONLY at the native no-op (a regression tripwire: if a future
    edit re-arms the child arm for the picker, the g>16 divergence fails)."""
    return basewin_pt(basewin_w, g), basewin_pt(basewin_h_abs, g)


def prodpicker_col_w(win_w: int, g: int) -> int:
    """Grid column width.  Vanilla is (win_w - 81)/5 where win_w is the
    picker's (device) width and 81 is a NATIVE additive constant living inside
    a device-space width — the mixed-space class ([[project-smac-netwin-lobby]]:
    native additive constants must scale x g/16).  Unscaled, the grid's side
    margins stay 27/61px at 4K instead of the faithful 67/147.
    Identity at g=16: (win_w - 81)/5."""
    return (win_w - basewin_pt(PRODPICKER_GRID_MARGIN, g)) // 5


def prodpicker_row_pitch(g: int) -> int:
    """Row pitch — THE lever.  Vanilla 108 is a ctor seed that never scales,
    which is the whole "squashed rows + huge empty body" defect: 4 rows of 108
    fill 432 of a 1225-tall device window.

    Pin the PITCH (uniform stride), do NOT distribute rows via cum().  Every
    consumer — cell rects, the scroll blit in scroll_to, the button row's y,
    the facility icon (pitch*3/7) and the unit zoom (pitch*2/3) — reads this
    ONE field, so a uniform stride keeps them mutually consistent; a per-row
    cum() would desync the scroll blit from the rows it shifts.  Same reasoning
    as option_row_gap.  Identity at g=16 by construction.
    """
    return basewin_pt(PRODPICKER_PITCH_NATIVE, g)


def prodpicker_cell_rect(col: int, row: int, colw: int, pitch: int,
                         g: int) -> Tuple[int, int, int, int]:
    """One grid cell's rect (draw_cell, fed to Buffer_set_clip @0x49285F).

    Vanilla: (col*colw + 0x1B, row*pitch + 4, (col+1)*colw + 0x18,
              row*pitch + pitch + 1).  colw and pitch arrive already scaled;
    only the four native additive insets need the floor idiom.  Verified
    against the g=16 log line `[cell 0] clip=(27,4,159,109)` and the 4K line
    `(27,4,386,109)` — this function reproduces the engine exactly.
    """
    return (col * colw + basewin_pt(PRODPICKER_CELL_L, g),
            row * pitch + basewin_pt(PRODPICKER_CELL_T, g),
            (col + 1) * colw + basewin_pt(PRODPICKER_CELL_R, g),
            row * pitch + pitch + basewin_pt(PRODPICKER_CELL_B, g))


def prodpicker_button_rects(win_w: int, count: int, pitch: int, vis_rows: int,
                            g: int) -> List[Tuple[int, int, int, int]]:
    """The button row (ProdPicker_exec 0x494AD4..0x494B21 + the BaseButton_init
    sites).  Vanilla lays the row out RIGHT-to-LEFT:

        step      = btn_w + 3
        x_leftmost = (W - step*count - 0x20) / 2
        x[i]      = x_leftmost + (count-1-i)*step        # button 0 = rightmost
        y         = pitch*vis_rows + 8,  w = 100, h = 20

    The math is CORRECT and needs no law of our own — it was simply fed the
    double-scaled W (measured shift 1421/333/195/0 px at g=40/25/22/16, i.e.
    (W_inflated - W_true)/2).  With the exemption above and the native
    constants scaled, the row re-centres under the grid at every g (checked in
    the sweep against prodpicker_cell_rect's span, <= 3px).
    Identity at g=16: (758 - 618 - 32)/2 = 54, step 103, y = 440, 100x20.
    """
    if count <= 0:
        raise ValueError("prodpicker_button_rects: count must be positive")
    bw = basewin_pt(PRODPICKER_BTN_W, g)
    bh = basewin_pt(PRODPICKER_BTN_H, g)
    step = bw + basewin_pt(PRODPICKER_BTN_GAP, g)
    pad = basewin_pt(PRODPICKER_BTN_PAD, g)
    y = pitch * vis_rows + basewin_pt(PRODPICKER_BTN_ROW_GAP_Y, g)
    x_left = (win_w - step * count - pad) // 2
    out = []
    for i in range(count):
        x = x_left + (count - 1 - i) * step
        out.append((x, y, x + bw, y + bh))
    return out


def prodpicker_font_size(native: int, g: int) -> int:
    """Picker font sizes.  cellName (12) and button (14) are FIXED literals —
    measured byte-identical Font structs at all four resolutions.  stats is
    max(10, colw/15), which tracks colw but lands ~1px short of proportionate
    (24/14/12 measured vs 25/15/13 faithful); since the picker's native colw is
    always 135 the max() floor always wins natively, so vanilla stats == 10 and
    the same floor idiom applies to all three.  Identity at g<=16."""
    return basewin_font_size(native, g)


PRODPICKER_FRAME_L = 0x17         # vanilla's frame left inset (0x494993)
PRODPICKER_FRAME_RSUB = 0x4E      # vanilla's right: R = W - 0x4E + 0x17
PRODPICKER_CELL_GUTTER = 4        # frame->grid gutter; 27-4 == 23 == FRAME_L
PRODPICKER_BTNFRAME_INSET = 3     # button-row frame outset (0x494F54 `mov eax,3`)


def prodpicker_frame_rect(colw: int, win_h: int, g: int) -> Tuple[int, int, int, int]:
    """The picker's outer 9-slice frame (Buffer_box_sprite @0x4949A0).

    Vanilla builds it from the WINDOW: (0x17, 0, W - 0x4E + 0x17, H), i.e.
    L = 23, R = W - 55, where 23/78 are NATIVE additive constants inside an
    already-DEVICE W.  Left unscaled the right gutter grows without bound —
    at g=25 the grid ended at 1079 while the frame ran to 1129 ("a large black
    area to the right" with the art hugging the left edge).

    But scaling those two constants in place is NOT enough: the grid's right
    edge is 5*colw + inset and colw FLOORS, so `5*colw` sheds up to 4px that
    a window-derived frame does not (LAW 2).  Swept, that leaves the two
    gutters up to 4px apart — visibly lopsided at g=28/30/37/39.

    So derive the frame from the CONTENT it wraps (LAW 5): both edges are the
    grid's own edges plus the scaled gutter.  The gutters are then EQUAL by
    construction at every g, and at g=16 the expression collapses to vanilla's
    own numbers — 27-4 = 23 and 5*135+24+4 = 703 = W-55 — so the native no-op
    is ALGEBRAIC, not a coincidence the sweep has to catch.

    v2 (pass 4, measured 2026-08-04 shots): the BaseWin backdrop art has a
    bright bevel LINE in the very column the frame stroke covers at g=16
    (native x=23), and the art's column lands at fl(23*g/16) — measured
    exposed at device x=31 (g=22) and x=35 (g=25), covered at g=16/40 where
    the cascades happen to agree.  v1's L = bp(27)-bp(4) sits 1px RIGHT of
    that at g=22/25, exposing 1px of bright bevel ("the frame stroke on the
    left reads as too bright").  So L must share the ART's cascade: L = bp(23)
    exactly (match-opposite-edge, [[feedback-floor-descale-roundtrip]]).  The
    stroke itself is drawn K=stroke_width(g) wide INWARD from the rect edge by
    thunk_box_thick_hollow_flat (pass 4 reroutes the picker's three
    Buffer_box_sprite calls), so covering the art line needs only the EDGE to
    coincide.  R mirrors the resulting left gutter (bp(27)-bp(23)-K between
    stroke and grid) on the right of the grid's own edge; K cancels:
    R = 5*colw + bp(24) + bp(27) - bp(23).  Gutters stay equal by
    construction, and g=16 is still algebraic: L = 23, R = 675+24+27-23 = 703.

    BACKLOG (2026-10-25 W7H, user decision): over the base screen (the exec parents the picker to BaseWin_g iff
    Win_is_visible(BaseWin_g); it draws no rails then) this frame does not coincide with the console frame
    [Lx, A* - 1] (basewin_console_frame_rect): base pixels show between its filled frame and the rails (g 17: 1
    column left / 3 right; g 19 a stroke-gap-stroke seam) and it runs up to 5 px over the right rail (g 28 / 30).
    Putting it on [Lx, A* - 1] alone is a trade: the grid is up to ~4 px wider than 675 g/16 (colw floors from a
    758 g/16 window), so the frame -> grid gutters (vanilla 3 | 3) come out up to 4 | 1 (g 26), 5 | 1 (g 28 / 30).
    The trade-free fix is the grid on the base-screen mirror law too (cell rect, hit test, scroll blit).
    """
    left = basewin_pt(PRODPICKER_FRAME_L, g)
    return (left, 0,
            5 * colw + basewin_pt(PRODPICKER_CELL_R, g)
            + basewin_pt(PRODPICKER_CELL_L, g) - left, win_h)


def prodpicker_button_frame(win_w: int, count: int, pitch: int, vis_rows: int,
                            g: int) -> Tuple[int, int, int, int]:
    """The frame drawn around the button row (Buffer_box_sprite @0x494F7C).

    Vanilla outsets the row's bounding box by 3 on every edge, reading four
    locals the button-layout block wrote.  Those locals still hold the NATIVE
    positions after prodpicker_button_rects moves the buttons — the thunk
    rewrites the pushed BaseButton_init args, not the caller's own registers —
    so the frame stayed at the unscaled place AND kept a native 3px stroke
    inset ("the frame stroke of the button box at the bottom is unscaled and
    mis-positioned").  Deriving it from the SAME quantities the buttons use is
    LAW 5 (chrome follows content): it cannot drift from them at any g.
    Identity at g=16 by construction.
    """
    rects = prodpicker_button_rects(win_w, count, pitch, vis_rows, g)
    d = basewin_pt(PRODPICKER_BTNFRAME_INSET, g)
    return (rects[-1][0] - d, rects[0][1] - d, rects[0][2] + d, rects[0][3] + d)


# Union frames: a button row / component union outset by a native 3 (scaled by its own lever) and drawn with
# Buffer_box_sprite, HALF-OPEN.  At g > 16 each goes to a band-map renderer (inclusive footprint) and so needs
# bandmap_rect_from_halfopen's R-1 / B-1: site -> the renderer the trimming helper tail-calls.
HALFOPEN_UNION_FRAME_SITES = {0x494F7C: "thunk_pp_boxsprite",            # ProdPicker_exec button-row frame (F38)
                              0x437B89: "thunk_box_thick_hollow_flat"}   # DesignWin_repaint union frame (D4)


def union_frame_draw_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-25 wave-2 W2A, F38) -- the rect HALFOPEN_UNION_FRAME_SITES hand their band-map renderer.

    The production picker's button-box frame (prodpicker_button_frame: the row outset by bp(3) on every edge) and the
    Design Workshop's union frame (UnionRect outset s(3), immfix 0x437B65) are half-open rects, which the native
    primitive draws with the right / bottom stroke on R-1 / B-1 (vanilla channel 2 on all four sides).  thunk_pp_boxsprite
    and thunk_box_thick_hollow_flat band-map them INCLUSIVE, so the far strokes landed on R / B: the channels came out
    2 | 3 both ways at 1600x900 (buttons x 570..1026, strokes 567 / 1030; y 603..624, strokes 600 / 628).  The draw gets
    bandmap_rect_from_halfopen's (L, T, R-1, B-1) at g > 16 -- every channel is then d - K on all four sides
    (union_frame_channels), equal at every g.  g <= 16: the native half-open render, unchanged.
    Port: t_bm_ho_pp / t_bm_ho_hf (assemble_halfopen_frames.py)."""
    return bandmap_rect_from_halfopen(l, t, r, b, g)


def union_frame_channels(inner: Tuple[int, int, int, int], d: int, g: int) -> dict:
    """The DRAWN channels between a union frame and its content [l, r) x [t, b) outset by d: the frame rect is
    (l-d, t-d, r+d, b+d) drawn through union_frame_draw_rect with K-wide strokes (K = 1 at g <= 16, native).
    Every side is d - K: vanilla 3 - 1 = 2; 1600x900 (g 18, d 3, K 1) 2; 4K (d 7, K 2) 5."""
    l, t, r, b = inner
    K = stroke_width(g) if g > NATIVE_G else 1
    fl_, ft, fr, fb = l - d, t - d, r + d, b + d
    if g > NATIVE_G:
        fl_, ft, fr, fb = union_frame_draw_rect(fl_, ft, fr, fb, g)
    else:
        fr, fb = fr - 1, fb - 1                             # native half-open: last col / row drawn
    return {"L": l - (fl_ + K), "T": t - (ft + K), "R": (fr - K + 1) - r, "B": (fb - K + 1) - b}


# ---- pass 5 (2026-08-05): cell text y + hit-grid alignment -------------------
# Trace-measured (hook_prodpicker.js v3, 4K g=40 + 1024 g=16, both runs in
# work\frida_prodpicker.log):
#   title write y   = cell_T + 1(inset) + 5(native pad)      10 native / 16 @4K
#   bottom line y1  = (cell_B - 1) - h,  h = measure() = n_lines * m,
#                     m = stats metric (f0>=0 ? f4+f0 : lh) = 10 native / 23 @4K
#   line above  y2  = y1 - m + (m - f4)//2   (write_cent_l_7 centring a one-line
#                     band (y1-m .. y1); 89 native / 226 @4K — matches EXACTLY,
#                     so y2 needs no lever of its own once y1 is right)
# The native pad/anchor are CONSTANTS of the vanilla fonts (thunk_pp_font pins
# the native sizes), so the device targets substitute fl(native * g/16) per
# [[feedback-font-metric-sublinearity]] instead of trusting scaled-font metrics.

PRODPICKER_TITLE_PAD = 5        # draw_cell 0x492AC5/0x492AD0 `add r,5` (native)
PRODPICKER_STATS_ANCHOR = 11    # native bottom-line anchor: y1 = cell_B - 11
PRODPICKER_STATS_LINE = 10      # native stats line metric m = f4+f0 = 7+3

def prodpicker_title_pad(g: int) -> int:
    """The pad ADDED to the (already +1-inset) cell top for the title rect.

    Vanilla adds 5 after the native +1 interior inset — total offset 6 from the
    cell top.  The +1 inset stays native at every g (a register `inc`), so the
    pad substitutes bp(6)-1 to make the TOTAL offset exactly bp(6):
    g=16 -> 5 (identity, algebraic); g=40 -> 14 (total 15 = fl(6*40/16)).
    """
    if g <= 16:
        return PRODPICKER_TITLE_PAD
    return basewin_pt(PRODPICKER_TITLE_PAD + 1, g) - 1


def prodpicker_stats_h(h_meas: int, m_dev: int, g: int) -> int:
    """Substitute for the measured bottom-block height h (0x5DC360 @0x492B6D).

    The site computes y1 = (cell_B - 1) - h.  Vanilla h = n_lines * m with
    m = 10 native, so the native anchor is bp-scalable as n * (bp(11) - 1):
    per line, exactly bp(11) below the cell bottom (the -1 cancels the native
    interior inset).  The scaled font's own m (23 @4K, sublinear vs the
    proportional 25) is only used to RECOVER n: h' = h * (bp(11)-1) / m_dev.
    Exact for h = n*m; identity at g<=16 or on any degenerate input.
    """
    if g <= 16 or m_dev <= 0 or h_meas <= 0:
        return h_meas
    return h_meas * (basewin_pt(PRODPICKER_STATS_ANCHOR, g) - 1) // m_dev


def _idiv(a: int, b: int) -> int:
    """x86 idiv: truncate toward zero (Python // floors negatives)."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def prodpicker_hit_cell(x: int, y: int, colw: int, pitch: int,
                        g: int) -> Tuple[int, int]:
    """Mouse -> (col, row), select handler 0x4941C0 (vtbl+0x4C, LOCAL coords).

    Vanilla maps col = x/colw, row = y/pitch with NO inset subtraction, while
    the drawn cell k starts at k*colw + bp(0x1B) / k*pitch + bp(4) — so the
    right bp(0x1B) / bottom bp(4) band of every drawn cell selects the
    NEIGHBOR (user-confirmed by edge-clicks in the v3 trace: x=365 in drawn
    col 0 selected col 1 @4K; user-confirmed at 1024 too, pass 5b).  The hit
    grid aligns to the drawn cells at EVERY g by subtracting the same insets
    draw_cell uses (bp is identity at g=16, so the native subtraction is the
    native 0x1B/4); each cell owns [its left/top edge .. next cell's edge).
    DELIBERATE fix of vanilla's own skew — the one sanctioned exception to
    the g<=16 native no-op invariant, user-requested 2026-08-05.
    """
    x -= basewin_pt(PRODPICKER_CELL_L, g)
    y -= basewin_pt(PRODPICKER_CELL_T, g)
    return _idiv(x, colw), _idiv(y, pitch)


# ---- one-row scroll blit (ProdPicker_scroll_to 0x493CB0) ----------------------
# Vanilla moves the rows that stay visible with ONE self-blit, Buffer_copy_4
# 0x5DFF00 @0x493D69 (scroll up: content moves DOWN) / @0x493E23 (scroll down),
# then draws only the exposed row:
#     x = 0x15 (src and dst), w = cols*colw + 0x17 + 2 - 0x15 -> right edge
#     cols*colw + 0x19 = the last cell's right inset 0x18, +1;
#     y: 4 <-> pitch+4, h = (vis_rows-1)*pitch.
# The right edge is a NATIVE additive constant inside a device-space grid; the
# cells' own right inset scales to bp(0x18) (prodpicker_cell_rect), so above
# g=16 a bp(0x19)-0x19 px strip of the last column never moved (34 px @4K).
PRODPICKER_SCROLL_X = 0x15        # blit left edge (src == dst), 0x493D31/0x493DE5
PRODPICKER_SCROLL_R = 0x19        # right edge inset: cols*colw + 0x17 + 2
PRODPICKER_SCROLL_Y = 4           # top of the moved block (== CELL_T natively)


def prodpicker_scroll_redraws(pitch: int, g: int) -> bool:
    """True when a one-row scroll must redraw every visible cell instead of
    blitting (thunk_pp_scrollblit's fallback, ProdPicker_draw_visible).

    The stripe phase is ABSOLUTE in the picker canvas (stripe_top(y): the
    devfill restripe keys on the dest row), so content moved by `pitch` rows
    keeps a phase that is off by pitch mod P against freshly drawn rows.  Only a
    pitch that is a multiple of P moves stripes onto their own grid: fl(108g/16)
    is 270 @g=40 (P=4 -> off by 2, the gutters between rows would show a doubled
    band) and odd at g=18/20/21/23/....  Those g redraw — vanilla's own path for
    multi-row jumps — and are exact by construction.  Never at g<=16."""
    return g > NATIVE_G and pitch % stripe_period(g) != 0


def prodpicker_scroll_blit(cols: int, colw: int, pitch: int, vis_rows: int,
                           g: int, up: bool) -> Tuple[int, int, int, int, int, int]:
    """The (sx, sy, dx, dy, w, h) Buffer_copy_4 receives for a one-row scroll.

    g<=16: vanilla verbatim.  Above: the right edge follows the cells it moves,
    R = cols*colw + bp(0x19) (vanilla's 0x19 additive, scaled like every other
    picker inset; >= the last cell's bp(0x18) right edge).

    The WIDTH is then rounded up to a multiple of 4 by moving the LEFT edge
    left (x = R - w, at most 3 px, into the canvas's key-9 margin outside the
    frame).  Measured by emulating 0x5DFF00's bytes: both self-blit paths here
    (sx == dx, dy != sy) copy with DF=1, and when w & 3 = r != 0 the dword run
    covers [x+2r, x+w+r) and the byte tail [x+r-3, x+2r-4] — the copy writes up
    to 3 columns past BOTH ends and skips columns x+r..x+2r-1.  Vanilla's own
    w = 679 (r = 3) drags the frame's right stroke column 702 along.  With
    w & 3 == 0 the copy is exact, so the right edge lands where the law puts it.

    The vertical block stays vanilla's (rows 4 .. 4+(vis_rows-1)*pitch, shifted
    by exactly pitch): it covers every moved cell's [T, B) because
    bp(4) >= 4 and bp(1) < 4, and its bottom vis_rows*pitch + 4 stays above the
    button-row frame (pitch*vis_rows + bp(8) - bp(3)).
    """
    h = (vis_rows - 1) * pitch
    y0, y1 = PRODPICKER_SCROLL_Y, pitch + PRODPICKER_SCROLL_Y
    sy, dy = (y0, y1) if up else (y1, y0)
    if g <= NATIVE_G:
        x = PRODPICKER_SCROLL_X
        w = cols * colw + PRODPICKER_SCROLL_R - PRODPICKER_SCROLL_X
        return x, sy, x, dy, w, h
    right = cols * colw + basewin_pt(PRODPICKER_SCROLL_R, g)
    w = (right - PRODPICKER_SCROLL_X + 3) & ~3
    x = right - w
    return x, sy, x, dy, w, h


def buffer_copy4_selfblit_columns(x: int, w: int) -> set:
    """Model (from emulating 0x5DFF00's bytes, not from reading it) of the dest
    columns Buffer_copy_4's sx == dx, dy != sy self-blit actually writes.  Every
    written column receives its own source column (no horizontal displacement);
    the defect is the SET: exact iff w % 4 == 0."""
    r = w & 3
    if r == 0:
        return set(range(x, x + w))
    return set(range(x + 2 * r, x + w + r)) | set(range(x + r - 3, x + 2 * r - 3))


# ==== devfill force-path field pairs + stripe law (fe_pair_remap v6, pass 5c) ====
# The devfill STEP3 restripe is CONTENT-KEYED (feedback-dither-pair-ambiguity):
# it scans <=8 rows of the dest rect the fill mask was just tiled into and
# enables exactly the pair whose COLORED member dominates (> width/2 pixels of
# a row-width) — solid fills and art never trip it.  v5 knew navy 0xC4/0x41 +
# backdrop 0xC6/0x41; the ProdPicker draws in the BASE-SCREEN palette and adds
# selected-cell 0xBF/0x53 and grid-gutter 0xC5/0x41 (ground truth
# frida_pp_field.log 2026-08-06: fill tiles 24x24 c4/41 unsel, 24x24 bf/53
# sel, 10x10 41/c5 grid; post-draw canvas: unsel striped 41,c4,c4 @g25, sel
# and gutters left 1px — exactly the two pairs the v5 table lacked).
# Colored member on top, matching every shipped stripe field.

DITHER_FORCE_PAIRS = {0xC4: 0x41, 0xC6: 0x41, 0xC5: 0x41, 0xBF: 0x53}


# The first g of a screen 1080 px high (16 * 1080 // 768).  A gate on g, never on a screen dimension.
STRIPE_2ROW_MIN_G = 22


def stripe_rows(g: int) -> int:
    """Device rows T per chrome stripe, bright and dark alike = the pictures'
    art_scan_rows(g) (option B: ONE stripe thickness on every surface;
    thickness alone leaves "vanilla x g/16"): 1 below STRIPE_2ROW_MIN_G
    (screens under 1080 px high: user 2026-10-04 on the 1600x900 shots,
    "2-pixel scanlines are too much" there), else max(2, g // 16)."""
    return art_scan_rows(g)


def stripe_period(g: int, override: int = 0) -> int:
    """Stripe period P in device px (skill scaling-frames §7): P = 2 * T,
    T = stripe_rows(g).  2 for g <= 21 (1-row stripes; g <= 16 never
    restripes), 4 for g = 22..47 -- every popup g from 1080 px up, since
    thunk_ensure_scale clamps g to 40; only the Monument / Hall of Fame nums
    (unclamped / 72) reach 6.  The popup-g asm ports read it from the cell
    g_stripe_period, which thunk_ensure_scale writes with g; the num ports
    (Monument / Hall of Fame / t_rwk_parity_nn) compute stripe_rows inline.
    `override` is the one-shot g_rm_povr: no thunk sets it since 2026-10-04
    (the faction buttons' 1-px parity law passed 2)."""
    if override:
        return override
    return 2 * stripe_rows(g)


def stripe_top(y: int, g: int, override: int = 0) -> bool:
    """Row y (dest-buffer space — ONE phase grid per buffer, so every layer
    fuses seamlessly) carries the TOP (colored) member iff y mod P < hN,
    hN = (P+1)>>1.  P is even, so hN = T and this is ((y // T) & 1) == 0:
    the top member opens the grid, both members T rows."""
    p = stripe_period(g, override)
    return (y % p) < ((p + 1) >> 1)


def list_stripe_phase(child_top: int, g: int, override: int = 0) -> int:
    """Rows a child canvas's stripe grid is advanced by so its stripes sit on its PARENT canvas's grid:
    the child's parent-local top modulo the period.  The top is rRect1.top + rRect2.top (Win +0x140 +
    +0x150: Win_init 0x5EBD80 keeps the position in rRect2 for a client-area window, in rRect1 otherwise;
    Win_flip_rect_2 0x5ECFE0 adds both), never +0x140 alone (0 for a client-area window).  Child row r
    then carries the TOP member iff stripe_top(child_top + r): (r + phase) mod P < hN.  Asm ports pass the
    raw sum and let their own `div P` / Buffer_tile's `idiv tileH` reduce it (right for P = 6 too; `and 3`
    is right only while P is 2 or 4).  Users: thunk_filedlg_rowbg_v6 / thunk_copy4_stripes (Load/Save,
    via srcOffY), t_dl_tile_ph + g_dl_rs_phi (Datalinks topic list, via the restripe row index)."""
    return child_top % stripe_period(g, override)


def btn_face_stripe_phase(rect1_top: int, rect2_top: int, g: int, override: int = 0) -> int:
    """The row phase thunk_btn_stripes v13 gives a FlatButton face (its own canvas, Win+0x444) so the face's
    pair stripes sit on its PARENT canvas's grid -- the panel the button is flipped onto: list_stripe_phase of
    the parent-local top rRect1.top + rRect2.top (Win +0x140 + +0x150).  A negative top (a button scrolled or
    placed above its parent) takes the true floor modulus, still the parent grid.  Before v13 every face phased from its own row 0, so a button whose
    top sat on an odd parent row was a whole stripe off the panel around it (1600x1200 Social Engineering,
    1920x1080 council / Operations Director rows).  Only the plain fe path takes it: the ed / sb-arrow paths
    keep phase 0.  Social Engineering's own face restripe (thunk_se_rowdraw, after fe) takes it too:
    the vtable entry thunk_se_rowdraw_ph stages the reduced phase in g_se_yph and every stripe row goes
    through thunk_se_stripe_px_ph (2026-10-11; without it the SE faces stayed one row off at 1600x1200,
    shot 200540).  The asm stages a non-negative sum raw in g_rm_yph (fe_pair_remap v8 reduces (row + sum) by
    P) and reduces a negative one itself (cdq / idiv P, + P) so the unsigned `div` never sees a wrapped row."""
    return list_stripe_phase(rect1_top + rect2_top, g, override)


def flatbutton_draw_state(forced: int, hover: int, pressed_a: int, pressed_b: int) -> int:
    """The draw state FlatButton_content_draw 0x607E50 picks (0x607EC8..0x607EFC, ebp: the index of every per-state
    sprite table): forced_state +0xAB8 when 0..2; else 2 when either pressed flag (+0xA9C, +0xA18) is set; else 1 when
    hover_flag +0xA74 is set; else 0.  State 2 is the PRESSED face (a selected tab, a held button), 1 the hover face."""
    if 0 <= forced < 3:
        return forced
    if pressed_b or pressed_a:
        return 2
    return int(bool(hover))


#: The FlatButton faces that stripe on their OWN top (W9A, the user's decision 2026-10-27), everything else keeps the
#: parent grid (btn_face_stripe_phase): every child FlatButton of PrefWin (parent +0xC4 == PrefWin_g 0x8578D8: the seven
#: category tabs incl. uimod.dll's, Gamma, Restore Defaults / OK / Cancel / More, the audio page's Off toggles, the
#: DLL's labels and its Subscribe button -- not the sliders' arrow buttons, whose parent is their ScrollBar) and the
#: Social Engineering screen's right column (SocialWin+0x6020 + i*0xB4C for i = 17..26: the ten society-model rows at
#: 0x8B829C + j*0xB4C, ids 0x11..0x1A).
OWN_FACE_PARENT = 0x8578D8
SE_OWN_FACE_LO, SE_OWN_FACE_N, FLATBUTTON_SIZE = 0x8B829C, 10, 0xB4C
SE_OWN_FACE_HI = SE_OWN_FACE_LO + SE_OWN_FACE_N * FLATBUTTON_SIZE


def own_top_face(btn: int, parent: int) -> bool:
    """Whether FlatButton `btn` (its address) with parent `parent` stripes on its own top (OWN_FACE_PARENT above)."""
    return parent == OWN_FACE_PARENT or SE_OWN_FACE_LO <= btn < SE_OWN_FACE_HI


def own_face_stripe_phase(h: int, g: int, pressed: bool = False) -> int:
    """LAW (2026-10-27 wave-9 W9A, the user's decision "ownc") -- the row phase of a FlatButton face that stripes on
    its OWN top, like vanilla (whose face art is drawn in each button's own buffer): face row r carries the pair's TOP
    member (AE of AE/EE, E0 of E0/E1 -- what fe_pair_remap / thunk_se_rowdraw put on stripe_top rows) iff
    (r + phase) mod P < T, T = stripe_rows(g), P = 2T.

    Vanilla's 20-row faces open with their row-0 colour and close on the other member: normal AE ... EE, pressed
    E1 ... E0 (the pressed art opens DARK, with the pair's mate), hover E0 (solid edge) / EE ... AE / E0.  At g > 16 the
    face is h = fl(20g/16) rows (any h), so the law picks, among the phases whose row 0 is the top member and whose last
    row h-1 is the mate, the one whose shorter end run (min(first run, last run)) is longest, then the longer first run;
    when no phase closes on the mate (h odd at T = 1) phase 0 (open on the top member).  pressed (draw state 2,
    flatbutton_draw_state) shifts it by T: the mate opens, the top member closes.  Every face of one height then looks
    the same whatever its screen row -- the seven PrefWin tabs identical in every state.  The trade the user accepted:
    a face's stripes may run out of step with the panel's faint dark side strip beside it (the parent grid).
    g <= 16: 0 (vanilla's art untouched).  h <= 0 (no face): phase 0, still shifted when pressed."""
    if g <= NATIVE_G:
        return 0
    t = stripe_rows(g)
    p = 2 * t
    best, best_key = 0, None
    for ph in range(p if h > 0 else 0):
        rows = [((r + ph) % p) < t for r in range(h)]
        if not rows[0] or rows[-1]:
            continue
        a = next((i for i, v in enumerate(rows) if not v), h)
        b = next((i for i, v in enumerate(reversed(rows)) if v), h)
        key = (min(a, b), a)
        if best_key is None or key > best_key:
            best, best_key = ph, key
    return (best + t) % p if pressed else best


def btn_face_phase(btn: int, parent: int, rect1_top: int, rect2_top: int, h: int, g: int, state: int) -> int:
    """The row phase a FlatButton face takes (thunk_btn_stripes v14's plain fe path and the SE face restripe entry
    thunk_se_rowdraw_ph v2, through t_face_own): own_face_stripe_phase for an own_top_face, else the parent grid
    (btn_face_stripe_phase, reduced to [0, P))."""
    if own_top_face(btn, parent):
        return own_face_stripe_phase(h, g, state == 2)
    return btn_face_stripe_phase(rect1_top, rect2_top, g)


def prodpicker_sel_outline_rects(l: int, t: int, r: int, b: int, g: int) -> List[Tuple[int, int, int, int]]:
    """The production picker's SELECTED-cell outline (Buffer_box_2 0xFF at 0x492F74 on the cell rect vanilla
    has already inset by 1 px, 0x49289A..0x4928B7).  Vanilla: a 1-px ring just inside the 1-px frame stroke.
    Scaled: the frame stroke is K = stroke_width(g) thick, so the ring band moves to [K, 2K) inside the cell --
    the vanilla inset rect pushed in by K-1, then box2_ring_rects' K nested rings.  Drawn at vanilla's 1-px
    inset with K=2 the ring's corner pixel fell in the frame's K x K keyed corner notch, which no unselected
    redraw repaints: a stray white pixel per selected-then-deselected cell, copied down the column by the
    one-row scroll (1600x1200 / 4K; 1920x1080 K=1 is unchanged).  K<=1: the vanilla call, verbatim.
    The cell frame (thunk_pp_boxsprite -> hollow_flat / devfill, band-map footprint INCLUSIVE of R0/B0) puts
    its right / bottom stroke on R0-K+1..R0 / B0-K+1..B0 while the left / top stroke is L0..L0+K-1: the
    inset rect (r = R0-1, b = B0-1) is pushed in by K-1 on the left / top but K-2 on the right / bottom so the
    rings butt every stroke (audit 2026-10-11; K-1 on all four sides left a 1-px seam at R0-K+1 / B0-K+1,
    and with the clip cutting column R0 the visible stroke is R0-K+1..R0-1 -- still flush)."""
    k = stroke_width(g)
    if k <= 1:
        return [(l, t, r, b)]
    return box2_ring_rects(l + k - 1, t + k - 1, r - (k - 2), b - (k - 2), g)


def option_row_stripe_phase(rect1_top: int, rect2_top: int, g: int, override: int = 0) -> int:
    """The row phase the popup option-row bars take (t_rowbox_ph, the 0x405BF6 row-frame call): the rows
    draw into the Dialog's own child GraphicWin, so their stripes sit on the POPUP's grid only when advanced
    by that child's parent-local top -- the same law as a FlatButton face (btn_face_stripe_phase).  Without
    it the bars were one row (g=22, child top 225) or half a period (g=40, top 410) off the popup frame
    (Protocol Director, 2026-10-11)."""
    return btn_face_stripe_phase(rect1_top, rect2_top, g, override)


def faction_list_stripe_phase(rect1_top: int, rect2_top: int, g: int, override: int = 0) -> int:
    """The row phase the CHOOSE YOUR FACTIONS name list takes (t_lbi_restripe_ph, staged around
    t_lb_item_stripes' t_tf_restripe call): the ListBox draws into its own child canvas, whose in-list gaps are
    the Buffer_copy_4 capture of FactionPickWin's canvas (the parent grid) and whose rows t_tf_restripe
    regenerates -- from the CHILD's row 0 before this, so the rows sat one stripe off the gaps and the
    FlatButtons wherever the list's parent-local top is odd.  Measured (picker canvas row 0 = its top frame
    line; list canvas row 0 = item 0's first row): 4K top 335 -> 3 (rows one off, shot 20261011-200837),
    1600x1200 209 -> 1 (one off, 20261006-222044), 1920x1080 184 -> 0 (already on the grid, 20261006-222202).
    Same law as a FlatButton face (btn_face_stripe_phase)."""
    return btn_face_stripe_phase(rect1_top, rect2_top, g, override)


def dw_button_face_stripe_phase(rect1_top: int, rect2_top: int, g: int, override: int = 0) -> int:
    """The row phase the Design Workshop's 25 FlatButton faces take (t_dw_face_ph stages it in g_se_yph; the
    DW-owned copy of the SE face restripe, thunk_dw_btnface, then stripes every row through
    thunk_se_stripe_px_ph): each face's PARENT-local top (Win +0x140 + +0x150) mod P, the same law as
    btn_stripes v13.  The parent differs by button (DesignWin_build, _dw_dec_all.txt 242 / 401-411):
      DesignWin-parented: ids 0..8 (RETIRE, APPLY, PROTO, RETIRE ALL, DONE, RENAME, OBSOLETE, UPGRADE, CANCEL)
        -> DesignWin-local top;
      MainWin_g-parented: ids 9..0x16 (the 14 VEHICLE PRESETS) and 0x17 / 0x18 (the slot-strip arrows)
        -> MainWin-local top (MainWin's canvas = the console strip, top = SH - fl(257 g / 16)).
    Before this every face phased from its own row 0.  Measured (shots, first face row = its canvas top mod P):
      1920x1080 20261006-201336, DesignWin frame line y 255: APPLY 444 -> 0 (on the grid), DONE row 479 -> 3
        (one stripe off);
      MainWin top 727 / 799 / 1518 at 1920x1080 / 1600x1200 / 4K (first console-art row; = SH - fl(257g/16)):
        the 1080 GARRISON preset 847 - 727 = 120 -> 0 (on the console grid today, unchanged);
      slot-strip arrows (= the HUD unit-row arrow rects, hud_unit_arrow_rects from vanilla box6 T 192 / B 248):
        4K 497 -> 1; at 1080 the top is 273 or 274 (the +-4 pad's space is not pinned; art centre 1028.2) -> 1 or 2,
        unresolved -- and the DW arrow (10-06) is pixel-identical to the HUD arrow (10-12) at 1080, so whether
        btnface's pair detection restripes the arrow art at all is unmeasured."""
    return btn_face_stripe_phase(rect1_top, rect2_top, g, override)


def btn_zoom_stripe_phase(rect1_top: int, rect2_top: int, g: int, band_match: bool, override: int = 0) -> int:
    """The row phase t_sbt_zoom (the owned-FlatButton enlarge that regenerates the face dither) adds to its dest row
    (t_sbt_ph stages it): the button's PARENT-local top mod P -- btn_face_stripe_phase -- for the esi-owned classes
    (the 25 Design Workshop buttons, MainWin's unit-row arrows buttons[8..10], SocialWin's 35); 0 for the
    band-match classes (MENU / COMMLINK / the BaseWin range), unchanged.  Before (2026-10-04..10-15) every owned
    face phased from its own row 0.  Measured: the DW slot-strip arrows (ids 0x17/0x18, MainWin-parented) and the
    HUD unit-row arrows share rects, art and this path (pixel-identical in 20261014-230811 / -230642 at 4K,
    -231218 / -231100 at 1600); the zoom's top member is the art's 0x(53,61,115) row (its canvas rows {0,1} under
    phase 0).  MainWin-local arrow tops from hud_unit_arrow_rects (anchors fl(192 g/16), fl(248 g/16)): 497 / 311 /
    274 at g 40 / 25 / 22 -- exactly the canvas tops the shots imply (top-member rows {3,0} / {2,3} / {1,2} vs
    MainWin top 1518 / 799 / 727) -- so the phase is 1 / 3 / 2: the 4K and 1600 arrows were a stripe off the
    console and the 1080 ones half a period off (members swapped; the run boundaries happened to agree)."""
    return 0 if band_match else btn_face_stripe_phase(rect1_top, rect2_top, g, override)


def pair_top(a: int, b: int, rgb) -> int:
    """Canonical TOP member of a detected dither pair (the member stripe_top
    puts on the WIDE band, hN of P rows).  Content-keyed detection (most
    frequent index first) is NOT canonical: an NN-enlarged 1:1 dither's
    majority member depends on phase, so adjacent rects restriped from their
    own histogram came out 2:1 vs 1:2 (2026-08-29 1600x1200 chassis picker:
    row-3 tiles + canvas 1/3 light, row-4 tiles + cell 9 2/3 light).  Law:
    a DITHER_FORCE_PAIRS key wins; else the member with the higher PEAK
    channel (navy 191 (14,34,67) over grey-green 83 (27,33,31); tile blue
    197 (11,18,24) over black 65) -- ties by channel sum, then lower index
    (pair_top_by_colour).  `rgb(i)` -> (r,g,b)."""
    for top, mate in DITHER_FORCE_PAIRS.items():
        if {a, b} == {top, mate}:
            return top
    return pair_top_by_colour(a, b, rgb)


def stripe_color(top_idx: int, y: int, g: int, override: int = 0) -> int:
    """The index a pair-member pixel on dest row y is rewritten to."""
    return top_idx if stripe_top(y, g, override) else DITHER_FORCE_PAIRS[top_idx]


def dither_force_mate(counts: dict, width: int):
    """Force-path pair selection: the colored member whose count over the
    scanned rows exceeds width/2, or None.  Several families can key (the
    count spans every scanned row, so more than one member can pass);
    0x41 (the shared bottom member of C4/C6/C5) goes to the first in the
    order navy -> backdrop -> C5 (the DITHER_FORCE_PAIRS order)."""
    for top in DITHER_FORCE_PAIRS:
        if counts.get(top, 0) > width // 2:
            return top
    return None


# ---- scrollbar-face pair — ONE-SHOT family, never content-keyed ------------
# (2026-08-08 sb banding fix.)  The console ScrollBar's arrow faces and thumb
# grip dither a FIFTH pair, 0xF0/0xB9 (palette 240=(53,61,115) top / 185=
# (17,50,79) bottom; sampled from the 20260808 1600x1200/4K shots, matched
# EXACTLY in frida_palette.log).  0xF0 ALSO occurs as SOLID console art —
# frida_pp_rail.log's bake row dump carries a 21px 0xF0 run in the rail strip
# — so this pair must NEVER join DITHER_FORCE_PAIRS: a content prescan would
# false-positive on art.  It is enabled only by the explicit self-clearing
# one-shot g_rm_f0ovr (same set-only-under-g>16 contract as g_rm_povr), set
# by the two owners of the surfaces: thunk_sb_restripe (whole sb canvas =
# trough + thumb, tail of every armed ScrollBar_draw via thunk_pref_sbzoom)
# and thunk_btn_stripes v3 (the two picker arrow FlatButton statics).

DITHER_ONESHOT_PAIRS = {0xF0: 0xB9}


def stripe_color_sb(y: int, g: int, override: int = 0) -> int:
    """The index a 0xF0/0xB9 pixel on dest row y is rewritten to (one-shot
    family; same P/hN/phase grid as every other stripe producer)."""
    return 0xF0 if stripe_top(y, g, override) else 0xB9


def pair_remap_pixel(idx: int, y: int, g: int, *, navy: bool = False,
                     bd: bool = False, c5: bool = False, bf: bool = False,
                     f0: bool = False, override: int = 0) -> int:
    """thunk_fe_pair_remap v7 per-pixel law: what dest index `idx` on dest
    row y becomes.  Unconditional pairs E0/E1 (blue) + AE/EE (teal); keyed
    families navy C4/41, backdrop C6/41, gutter C5/41, sel BF/53 (flags from
    the force/src prescans); one-shot family F0/B9 (`f0` = the consumed
    g_rm_f0ovr).  0x41 arbitration order: navy -> backdrop -> C5.  Every
    other index (strokes/bevel/art/text/key) passes through untouched."""
    top = stripe_top(y, g, override)
    if idx in (0xE0, 0xE1):
        return 0xE0 if top else 0xE1
    if idx in (0xAE, 0xEE):
        return 0xAE if top else 0xEE
    if idx in (0xF0, 0xB9):
        return (0xF0 if top else 0xB9) if f0 else idx
    if idx == 0xC4:
        return (0xC4 if top else 0x41) if navy else idx
    if idx == 0xC6:
        return (0xC6 if top else 0x41) if bd else idx
    if idx == 0xC5:
        return (0xC5 if top else 0x41) if c5 else idx
    if idx in (0xBF, 0x53):
        return (0xBF if top else 0x53) if bf else idx
    if idx == 0x41:
        if navy:
            return 0xC4 if top else 0x41
        if bd:
            return 0xC6 if top else 0x41
        if c5:
            return 0xC5 if top else 0x41
    return idx


# ---- scenario-editor icon-face pairs (thunk_ed_remap; proto v5 FIX 2e) -----
# (2026-08-12, user-verified 4K + 1600x1200.)  The 31 editor FlatButtons
# (palette 25 + red-brush 6, statics [EDITOR_BTN_LO, EDITOR_BTN_HI), pitch
# 0xB4C, measured gate census) route through the shrink/NN-zoom pipeline, so
# their striped console-art STATE faces band — and their pairs are not in
# fe_pair_remap's family set (the pre-v4 sb-arrow story repeating).  Pairs
# MEASURED from the verified [stripe] log at g=40 (P=5) AND g=25 (P=3):
#   f0/b9  palette state faces (the sb pair again),
#   a2/ef  palette hover faces (teal 162 / purple 239),
#   e0/e2  palette selected faces — 0xE0's mate HERE is E2, NOT the baked E1
#          ([[feedback-dither-pair-ambiguity]]); E1 strays (written by the
#          unconditional e0/e1 family) fold into the family,
#   c9/6d  red-brush normal faces (near-black 201 top / mid-red 109),
#   68/6d  red-brush hover/pressed (mid-red top / bright 104) — 0x6D sits in
#          BOTH red pairs, so the two are ARBITRATED per blit by credits.
# Canonical tops are FIXED (f0, a2, e0, c9, 6d): the proto's chain-start vote
# flipped once at g=25 (a2/ef voted top=ef) — a bake must never vote.
#
# DETECTION is the proto's run-chain law, not a membership count: per column,
# run-length encode; runs longer than P+1 BREAK chains (this is what excludes
# solid art — a boundary between two solid regions is two LONG runs and never
# credits); alternating two-value chains of >= EDITOR_FACE_CHAIN_MIN runs
# credit their run count to the pair.  A family enables when its credits over
# the full-width scan reach editor_face_threshold(w) = 2*w (the proto required
# 24 credits over 12 sampled columns = 2/column; the verified log's weakest
# real face credited ~3.5/column, margin ~1.75x).
#
# PASS ORDER (btn_stripes v5): thunk_ed_remap runs BEFORE thunk_fe_pair_remap
# on the same rect.  Both share the one phase grid, so the composition is
# stable: pair_remap_pixel(editor_face_remap_pixel(v)) ==
# editor_face_remap_pixel(v) for every enabled-family member (tested).

EDITOR_BTN_LO, EDITOR_BTN_HI = 0x7B7264, 0x7CD098

# top -> bottom, canonical top first (dict order = credit/arbitration order)
EDITOR_FACE_PAIRS = {
    0xF0: 0xB9,
    0xA2: 0xEF,
    0xE0: 0xE2,
    0xC9: 0x6D,
    0x6D: 0x68,
}
EDITOR_FACE_CHAIN_MIN = 6      # runs per credited chain (proto detectFacePair)
# FORCE (2026-10-06): the 31 editor palette/brush FlatButtons restripe with
# the bar at 0.  Census of interface.pcx (25 cells x 3 states 43x18 at
# (350+44*(k%8), 245+57*(k//8)+19*s), 6 brush x 3 at (465+25*i, 438+25*s)
# 24x24): every pair pixel of all 93 faces sits on the row-parity mask (0
# violations), so a phase restripe of every pair pixel regenerates the mask;
# the glyph-cut faces (cells 1, 11, 22) credit 40..169 against 2*w = 92..214
# at every g and the hatch (cell 21) credits 0 -- no chain threshold separates
# them (test_stripes_edpal_asm_parity, both shots pixel-exact).  Every other
# caller (locator, ATTACK!, chevrons) keeps the detector.


def editor_face_forced(btn: int) -> bool:
    """thunk_ed_remap's force gate: the button (saved esi) is an editor static."""
    return EDITOR_BTN_LO <= btn < EDITOR_BTN_HI


def editor_face_maxrun(g: int) -> int:
    """Longest run that can still belong to a banded stripe chain: P+1
    (an NN-zoomed 1px pair never produces a longer member run)."""
    return stripe_period(g) + 1


def editor_face_threshold(w: int, forced: bool = False) -> int:
    """Credits needed to enable a family: 2 per column of the full scan, 0
    for a forced (editor) button."""
    return 0 if forced else 2 * w


def editor_face_chain_credits(columns, g: int) -> dict:
    """Model of thunk_ed_remap's detector.  `columns` = iterable of pixel
    columns (each an iterable of palette indices, top to bottom).  Returns
    {(lo, hi): credited_runs} for every two-value alternating chain of
    >= EDITOR_FACE_CHAIN_MIN runs whose runs are all <= P+1."""
    maxrun = editor_face_maxrun(g)
    credits: dict = {}

    def flush(c0, c1, chain):
        if chain >= EDITOR_FACE_CHAIN_MIN and c0 >= 0 and c1 >= 0:
            key = (min(c0, c1), max(c0, c1))
            credits[key] = credits.get(key, 0) + chain

    for col in columns:
        runs = []
        prev, length = -1, 0
        for v in col:
            if v == prev:
                length += 1
            else:
                if prev >= 0:
                    runs.append((prev, length))
                prev, length = v, 1
        if prev >= 0:
            runs.append((prev, length))
        c0 = c1 = -1
        chain = 0
        for val, length in runs:
            if length > maxrun:
                flush(c0, c1, chain)
                c0 = c1 = -1
                chain = 0
                continue
            if chain == 0:
                c0, chain = val, 1
            elif chain == 1:
                if val != c0:
                    c1, chain = val, 2
                else:
                    flush(c0, c1, chain)
                    c0, chain = val, 1
            elif val == (c0 if chain % 2 == 0 else c1):
                chain += 1
            else:
                flush(c0, c1, chain)
                c0, c1, chain = val, -1, 1
        flush(c0, c1, chain)
    return credits


def editor_face_enable(credits: dict, w: int, forced: bool = False) -> dict:
    """Family enables from chain credits.  Red arbitration: 0x6D belongs to
    whichever red pair carries more credits (c9 wins ties — the normal face);
    at most one red family enables per blit."""
    thr = editor_face_threshold(w, forced)

    def c(top, bot):
        return credits.get((min(top, bot), max(top, bot)), 0)

    c_c9, c_68 = c(0xC9, 0x6D), c(0x6D, 0x68)
    c9 = c_c9 >= thr and c_c9 >= c_68
    return {
        "f0": c(0xF0, 0xB9) >= thr,
        "a2": c(0xA2, 0xEF) >= thr,
        "e2": c(0xE0, 0xE2) >= thr,
        "c9": c9,
        "m68": (not c9) and c_68 >= thr,
    }


def editor_face_remap_pixel(idx: int, y: int, g: int, *, f0: bool = False,
                            a2: bool = False, e2: bool = False,
                            c9: bool = False, m68: bool = False) -> int:
    """thunk_ed_remap per-pixel law (editor buttons only, g > 16 only):
    what dest index `idx` on dest row y becomes given the enabled families.
    The e0/e2 family owns {E0, E1, E2} (E1 strays fold in); 0x6D follows the
    arbitrated red family.  Everything else passes through untouched."""
    top = stripe_top(y, g)
    if idx in (0xF0, 0xB9) and f0:
        return 0xF0 if top else 0xB9
    if idx in (0xA2, 0xEF) and a2:
        return 0xA2 if top else 0xEF
    if idx in (0xE0, 0xE1, 0xE2) and e2:
        return 0xE0 if top else 0xE2
    if idx == 0xC9 and c9:
        return 0xC9 if top else 0x6D
    if idx == 0x68 and m68:
        return 0x6D if top else 0x68
    if idx == 0x6D:
        if c9:
            return 0xC9 if top else 0x6D
        if m68:
            return 0x6D if top else 0x68
    return idx


# ==== console rail strip + its embedded ScrollBar (rail_slide_in 0x45DEA0) ====
# The visible geometry of the ProdPicker's scrollbar does NOT come from the
# picker's own ScrollBar_init_inner call (that rect is created hidden and never
# shown) -- it comes ENTIRELY from the generic console-rail slide helper
# rail_slide_in(win, &sb) @0x45DEA0, which every popup/report screen shares.
# The helper synthesizes a 47px strip (32px ornate rail column + 15px wall)
# from the console_x art into a scratch Buffer, bakes it into the window canvas
# at (clientW-47, yTop-y1), then RE-GEOMETRIES the scrollbar to sit inside it.
#
# Vanilla is MIXED-SPACE and that mix is the whole defect: the strip buffer is
# as tall as the DEVICE window while every art constant (26/34/25 tile heights,
# the 47/43/24/21 insets) stays native -- so at 4K you get a full-height column
# of native-size tiles with a native-width bar parked at a native inset (the
# 4K/native height ratio measured 1173/425 = 2.80, not 2.50).
#
# The fix descales to native, applies vanilla's own quantization there, and
# rescales: synthesize the strip at NATIVE height, then keyed-ENLARGE it x g/16
# at the bake (Buffer_draw_2 already takes num/den), and scale the four tail
# constants through the same cascade.  Every output is then vanilla x (g/16) by
# construction and the g<=16 path is bit-identical to vanilla.
# Ground truth: frida_pp_scrollbar.log 2026-08-06 (4K g=40 + 1024 g=16).

# ---- rail channel dither (thunk_rail_bake v2, 2026-08-15) --------------------
# The console_x rail column art (console_x.pcx rows 279..400: top cap / mid /
# bottom cap / filler) is a 1px ROW dither 0x41/0xC5 on EVERY row, with the teal
# AE guide lines and the cap bevels overlaid.  NN-enlarging the native strip
# x g/16 bands it at fractional g (1920x1080 shot 20260815-010148, g=22).  The
# bake regenerates it at device density: mark every 0x41/0xC5 of the NATIVE
# strip as RAIL_CHANNEL_MARK before the blit (no geometry model of the blit is
# needed -- the mark survives NN and nothing else in the canvas is that index),
# then rewrite every mark in the dest rect by rail_channel_pixel.  Same phase
# grid (dest-buffer row) and the same C5-top/41-bottom duty as fe's C5/41
# gutter family (pair_remap_pixel), so the strip and the bar's trough agree.
RAIL_CHANNEL_MARK = 0xFD    # palette 253 = pure magenta (the pcx key colour; never art)
RAIL_CHANNEL_TOP = 0xC5
RAIL_CHANNEL_BOT = 0x41


def rail_channel_mark(idx: int) -> int:
    """Pass 1 (native strip): the two dither members become the mark; every
    other index (AE lines, bevels, F0/B9 cap art, key 9, wall) passes through."""
    return RAIL_CHANNEL_MARK if idx in (RAIL_CHANNEL_TOP, RAIL_CHANNEL_BOT) else idx


def rail_channel_pixel(idx: int, y: int, g: int) -> int:
    """Pass 2 (device canvas, dest row y): a marked pixel becomes C5 on
    stripe-top rows and 0x41 below; anything else is untouched."""
    if idx != RAIL_CHANNEL_MARK:
        return idx
    return RAIL_CHANNEL_TOP if stripe_top(y, g) else RAIL_CHANNEL_BOT


# ---- scrollbar arrow face background (thunk_sbarrow_bg, 2026-08-15) ----------
# The arrow FlatButton's face background is its OWN 1px row dither 0xC2/0xC5
# (palette 194/197; measured in the 1920x1080 + 1600x1200 shots), not the bar's
# 41/C5 trough, and no fe/ed family owns it -> banded after the button zoom.
SBARROW_BG_TOP, SBARROW_BG_BOT = 0xC2, 0xC5


def sbarrow_bg_pixel(idx: int, y: int, g: int) -> int:
    """thunk_sbarrow_bg per-pixel law over the arrow's canvas (row y of the
    button buffer): a C2/C5 member becomes C2 on stripe-top rows / C5 below;
    everything else (chevron F0/B9 or A2/EF, bevels, key) passes through."""
    if idx not in (SBARROW_BG_TOP, SBARROW_BG_BOT):
        return idx
    return SBARROW_BG_TOP if stripe_top(y, g) else SBARROW_BG_BOT


RAIL_STRIP_W    = 47      # bufA width = wall(15) + rail column(32); [ebp-0x1c] @0x45E005
RAIL_WALL_W     = 15      # r_outer sprite 0x7D0048, drawn at strip x=32
RAIL_ART_Y      = 3       # top cap y inside the strip buffer (0x45E2B8 `push 3`)
RAIL_TOPCAP_H   = 26      # console_x top cap 32x26   (0x7CFF14)
RAIL_MIDTILE_H  = 34      # console_x mid tile 32x34  (0x7CFF40)
RAIL_BOTCAP_H   = 25      # console_x bottom cap 32x25(0x7CFF6C)
RAIL_QUANT_PAD  = 0x2C    # the `lea eax,[edx+esi+0x2c]` slack in the tile count
RAIL_TOP_INSET  = 13      # yTop = min(y1+13, max(A,y1)); the picker's native inset
RAIL_INSET_A    = 238     # threshold A (94 when ScreenWidth==800); 0x45DF45..0x45DF63
RAIL_SB_W       = 0x18    # sb resize w   (0x45E4D1)
RAIL_SB_Y       = 0x15    # sb move y     (0x45E4DE)
RAIL_SB_XSUB    = 0x2B    # sb x = clientW - 0x2B (0x45E4E0)
RAIL_SB_HSUB    = 10      # sb h = railH - 10     (0x45E4C9 `add esi,-0xa`)


def rail_top_inset(y1: int, g: int, screen_w: int = 0) -> int:
    """Strip origin relative to the window top (window-local y of the bake).

    Vanilla: yTop = min(y1+13, max(A,y1)), A = 94 @800px wide else 238 -- a
    DEVICE-space threshold on a NATIVE constant, so the same window loses its
    13px inset once it happens to sit low enough on a big screen (4K measured
    inset 0, 1024/1920 measured 13).  Gated (g>16) we pin the native inset to
    the vanilla 13 and scale it, so the rail sits the same way at every g."""
    if g <= 16:
        a = 94 if screen_w == 800 else RAIL_INSET_A
        return min(y1 + RAIL_TOP_INSET, max(a, y1)) - y1
    return basewin_pt(RAIL_TOP_INSET, g)


def rail_strip_src_h(win_h: int, inset: int, g: int) -> int:
    """Height of the strip buffer as it is SYNTHESIZED (Buffer_init @0x45E22C).

    Vanilla passes the device span y2-yTop.  Gated we pass its NATIVE
    equivalent ceil(span*16/g) -- the floor-descale round-trip law
    [[feedback-floor-descale-roundtrip]] -- so the tile quantization below runs
    on native art in native units, exactly as it does at 1024."""
    span = win_h - inset
    if g <= 16:
        return span
    return -(-span * 16 // g)


def rail_quantized_h(src_h: int) -> int:
    """Vanilla rail height: whole 34px mid tiles between the two caps.

    esi = 26 + 25 + 34*N with N = floor((src_h - 44 - 26 - 25)/34); the engine
    spells it as a trunc-toward-zero idiv of (95 - src_h) by 34, so short
    buffers give N<0 and a collapsing rail -- reproduced exactly here."""
    slack = RAIL_QUANT_PAD + RAIL_TOPCAP_H + RAIL_BOTCAP_H - src_h
    return RAIL_TOPCAP_H + RAIL_BOTCAP_H - RAIL_MIDTILE_H * _idiv(slack, RAIL_MIDTILE_H)


def rail_strip_x(win_w: int, g: int) -> int:
    """Window-local DEVICE x of the rail scrollbar strip (rail_slide_in's bake, 2026-10-17 fix sbstrip).

    Vanilla bakes the 47-px strip (32-px rail column + the 15-px r_outer wall) at clientW - 47 = exactly where
    slide_show's OUTER right strip sits (canvas - 0x2F): the rail column opens where the closed wall stood, and the
    slide-out leaves the wall back on that column.  At g > 16 the slide rails go through railscale's double floor
    (rail_right_strip_x), which sits 0..4 px LEFT of a plain clientW - fl(47g/16); the bake v1/v2, the bar and the
    slide-out used the plain form, so 1-4 px of the outer strip's art stayed visible between the inner strip and the
    rail column (report g=25: 2, file dialog g=21/23: 3, 4K: 1).  Law: the strip starts AT the outer right strip, rail_right_strip_x(winW,
    winW - 47, g); its wall then ends 0..4 px inside the canvas (the outer strip's own right-gap phase) and the
    slide-out's end-state wall lands exactly on the outer strip (fl(47g/16) - 2g == fl(15g/16)).  g <= 16: winW - 47
    (the formula is the identity at g = 16 as well)."""
    if g <= NATIVE_G:
        return win_w - RAIL_STRIP_W
    return rail_right_strip_x(win_w, win_w - RAIL_STRIP_W, g)


RAIL_COL_W = RAIL_STRIP_W - RAIL_WALL_W   # 32: the rail column's native width (strip columns 0..31)
RAIL_CYAN_L, RAIL_CYAN_R = 3, 28           # the column art's 1-px guide lines (console_x mid tile cols 3 / 28)


def rail_nn_col(k: int, g: int) -> int:
    """Device offset of native strip column k inside the g/16-enlarged rail strip (2026-10-17 fix rail2).

    The bake enlarges the strip with the ENGINE's Buffer_draw_2, whose NN places source column k at the sum of the
    first k entries of its run table (g_sprite_scale_runs, Sprite_fill_scaling_table 0x5EB20F -> engine_scale_runs),
    NOT at fl(k*g/16): the table's odd-base start shifts it, so column 32 (the wall's first) lands at 2g + 1 for
    g = 25..31 and 48 (2g + 2 from 57).  Measured on the real engine (Unicorn, g = 16..96, any dest x: column k at
    x + rail_nn_col(k, g); drawn width fl(47g/16), height fl(h*g/16), rows on the same table).  g <= 16: k."""
    if g <= NATIVE_G:
        return k
    return sum(engine_scale_runs(g, 16, k))


def rail_wall_off(win_w: int, g: int) -> int:
    """Offset of the strip's WALL from the strip x (rail_strip_x) once baked (2026-10-17 fix rail2).

    The bake draws the rail column (strip columns 0..31) through the engine, rail_nn_col(32, g) wide, and the wall as
    r_outer through thunk_sprite_scale_nn -- the same scaler, sprite, width fl(15g/16) and column samples as
    slide_show's outer right rail -- right after it.  The slide-out rolls the capture back by this same offset, so the
    rolled-up wall lands exactly where the closed outer rail stood.  Clamped so the wall never passes the canvas
    (win_w - rail_strip_x - fl(15g/16) >= rail_nn_col(32) for g <= 47; at g = 48 / 57..63 / 80.. one width phase
    would put the wall's last column outside -- the wall then covers the column's last device px instead, and the
    end state stays exact).  g <= 16: 32 (vanilla: the -32 roll-up)."""
    if g <= NATIVE_G:
        return RAIL_COL_W
    room = win_w - rail_strip_x(win_w, g) - ((RAIL_WALL_W * g) >> 4)
    return min(rail_nn_col(RAIL_COL_W, g), room)


def rail_layout(win_w: int, win_h: int, g: int,
                y1: int = 0, screen_w: int = 0) -> dict:
    """Full gated geometry of the rail strip + its scrollbar, window-local.

    Returns the exact arguments the five patched sites produce:
      strip_src_h  -> Buffer_init h        (site C, 0x45E22C)
      bake_x/y, blit_num/den -> Buffer_draw_2 (site D, 0x45E4BB)
      sb_x/y/w/h   -> resize + Win_move    (site E, 0x45E4C6)
    plus rail_h (the engine's esi) and the drawn top/bottom of the rail column,
    which the tests use to prove the bar keeps its vanilla 5px/4px margins
    inside the art at every g.

    v2 (2026-10-17, fix sbstrip): the strip starts at rail_strip_x (the outer right slide rail's own x) instead of
    winW - fl(47g/16), and the bar keeps its offset INSIDE the strip, bp(47) - bp(0x2B) -- the whole assembly moves
    together, so the bar's margins in the rail column, its arrows/thumb and its hit rect (the bar window itself) are
    unchanged relative to the art.  Identity at g <= 16 (winW - 47 / winW - 0x2B).

    v3 (2026-10-17, fix rail2): every column edge is where the ENGINE's NN put the art (rail_nn_col), not k*g/16.  The
    bar sits exactly between the column's two cyan guide lines (native cols 3 / 28; vanilla 3+1 | 24 | 1+3):
    sb_x = x0 + rail_nn_col(4), sb_w = rail_nn_col(28) - rail_nn_col(4) -- it touches both lines at every g (v2's
    bp(47) - bp(0x2B) / bp(24) covered the left line or left a 1-px gap before the right one at 13 of g = 17..40).
    The rail column ends at x0 + rail_nn_col(32) (art_right; v2 assumed 2g), the wall starts at x0 + rail_wall_off and
    is fl(15g/16) wide (wall_x / strip_right)."""
    inset = rail_top_inset(y1, g, screen_w)
    src_h = rail_strip_src_h(win_h, inset, g)
    rail_h = rail_quantized_h(src_h)
    num, den = (g, 16) if g > 16 else (1, 1)
    x0 = rail_strip_x(win_w, g)
    # v4 (2026-10-25, W3B): the column is ONE symmetric map (rail_col_map) -- the bar is [b, Wc - b), the lines K wide
    # on its two sides, the column's art ends at the wall (x0 + Wc).  v3 placed the bar on the engine's NN table.
    b, wc = rail_bar_inset(win_w, g), rail_col_w(win_w, g)
    (l0, l1), (r0, r1) = rail_line_spans(win_w, g)
    c4, c28 = b, wc - b
    wall_x = x0 + rail_wall_off(win_w, g)
    return {
        "inset": inset,
        "strip_src_h": src_h,
        "rail_h": rail_h,
        "bake_x": x0,
        "bake_y": inset,
        "blit_num": num,
        "blit_den": den,
        "sb_x": x0 + c4,
        "sb_y": basewin_pt(RAIL_SB_Y, g),
        "sb_w": c28 - c4,
        "sb_h": (rail_h - RAIL_SB_HSUB) * num // den,
        # drawn extent of the rail column inside the window (dest space)
        "art_top": inset + RAIL_ART_Y * num // den,
        "art_bottom": inset + (rail_h + RAIL_ART_Y) * num // den,
        "art_left": x0,
        "art_right": x0 + (wc if g > NATIVE_G else RAIL_COL_W),
        # the cyan guide lines' device spans [l, r)
        "cyan_l": (x0 + l0, x0 + l1),
        "cyan_r": (x0 + r0, x0 + r1),
        # the wall (r_outer through scale_nn) and the strip's drawn right end (the wall's last column + 1); <= win_w
        "wall_x": wall_x,
        "strip_right": wall_x + RAIL_WALL_W * num // den,
    }


def rail_out_tail(g: int, animate: bool, win_w: Optional[int] = None) -> Tuple[int, int]:
    """rail_slide_out 0x45E540 end state for the gated rail family (2026-09-26r).

    Vanilla captures the strip column [R - 47, R) of the window canvas
    (0x45E68C: R - [0x7D0060] - 0x20 = R - 15 - 32), rolls it up (when the
    animation pref [0x9A6494]&0x80000 is on and it is not MP: 8 frames x 4 px,
    or 4 x 8 in MP -- net -32), clears the column to key 9 and re-blits the
    capture at L + shift (0x45EB01): shift -32 leaves the 15-px WALL at
    [L, L+15) and nothing else; with the roll-up skipped the shift is 0 and
    the whole (now bar-less) rail channel stays.  The gated g>16 strip is
    bp(47) wide with its wall at column fl(32g/16) (rail_layout art_right),
    so the lawful end state is capture width bp(47) and shift -fl(32g/16)
    (= -2g) when vanilla would have animated, 0 otherwise.  railout_hstep
    zeroes the roll-up FRAMES (a native 64-px capture slid over the enlarged
    strip tore) -- v1..v3 left the shift at 0 too, so a window that stays
    open (the in-game LOAD/SAVE picker after entering a folder that fits)
    kept the whole rail + the bar's arrow ghost where vanilla shows the wall.
    Returns (capture width, final x shift).

    v2 (2026-10-17, fix sbstrip): with win_w given, the capture starts where the strip was baked, rail_strip_x
    (the outer right rail's x), and runs to the window's right edge: width win_w - rail_strip_x = bp(47) + the
    0..4 px right-gap phase (key-9 / untouched canvas, re-blitted keyed: no-op).  The shifted wall then lands
    exactly on the outer right strip.  Without win_w: the v1 width bp(47) (strip width alone).

    v3 (2026-10-17, fix rail2): the shift is the wall's own offset in the baked strip, -rail_wall_off(win_w, g) --
    the engine put strip column 32 at rail_nn_col(32) = 2g + 1 for g = 25..31 / 48, so v2's -2g left a 1-px seam
    between the inner and outer right rails after the bar slid away (1600x1200, 1920x1200, 2560x1440).  Without
    win_w: -rail_nn_col(32, g) (the unclamped offset)."""
    if g <= NATIVE_G:
        return RAIL_STRIP_W, (-32 if animate else 0)
    if win_w is None:
        return basewin_pt(RAIL_STRIP_W, g), (-rail_nn_col(RAIL_COL_W, g) if animate else 0)
    return win_w - rail_strip_x(win_w, g), (-rail_wall_off(win_w, g) if animate else 0)


def scrollbar_arrow_square(b: int, bordered: bool) -> int:
    """Side of BOTH of a Scroll's arrow buttons, given b = +0xA60 = min(w,h).

    ScrollBar_init_inner 0x6054D0 creates the pair square and equal: b-2 at
    (1,1)/(H-b+1) when the bar has a border colour (+0xA1C != -1), else b at
    (0,0)/(H-b).  ScrollBar_on_resize 0x606860 then re-derives b = min(w,h) and
    resizes ONLY the down button (+0x15F8) -- +0xAAC is never touched, at
    either of its two arms (0x6068DB unbordered / 0x606935 bordered).

    That asymmetry is a latent VANILLA bug: b only moves if the bar's SHORT
    axis changes, and vanilla only ever grows a scrollbar along its long axis.
    Scaling the ProdPicker's bar is the first thing in the game that widens
    one (24 -> bp(24)), which strands the up button's window at its creation
    size.  FlatButton_content_draw then centres the zoomed chevron against the
    stale W (`x = (W - sprW)/2`) and clips it to the stale 24x24 buffer, so the
    correctly-placed chevron gets a smaller, offset ghost on top of it -- and
    the up arrow's HIT rect stays 24x24 in the corner, which is why it reads as
    having no hitbox.  The fix keeps the pair in sync; it is a no-op wherever
    the two are already equal, so every other scrollbar in the game is
    untouched at every resolution.  Ground truth: 4K capture 20260808-124143
    (ghost clipped to exactly 24x24 at the widget's client origin).
    """
    return b - 2 if bordered else b


# ==== RAIL SCROLLBAR: one symmetric column (W3B, 2026-10-25; user-approved "rail scrollbar rework" 2026-10-24) =======
# Vanilla's rail column (native strip cols 0..31) is mirror-symmetric where it shows: outer 3 | cyan line 1 | bar 24 |
# line 1 | outer 3 (lines at cols 3 and 28 = 31 - 3), and the bar's two arrow plates and its thumb grip are one 18-px
# span centred in the bar, 3 | 18 | 3 (the plate at button-local 3 of a 24-px square arrow, the grip at (24 - 18) / 2).
# Scaled, four mechanisms each rounded on their own (shots 20261022-204321 / 205616 / 205821, reproduced exactly by the
# real image, scratchpad w3B):
#   * the column went through the ENGINE's NN run table (rail_nn_col): unequal lines (4K 3 | 2, 1080 2 | 1) and outer
#     offsets (1600x1200 5 | 4);
#   * the bar sat on that table's col 4 / col 28 (rail_layout v3);
#   * the arrow plate is GDI StretchBlt's centre-NN of the native button (fl(bw*16/g) -> bw): 1080 25 px, 1600x1200 29;
#   * the grip is drawn fl(18g/16) wide at vanilla's (bw - 18) / 2 minus 18(g - 16)/32: 1080 24 px one left of the
#     plate's centre.
# LAW (fix 20 item D, d_plan.py): ONE column map per strip, axis_map_chrome(32, Wc, 4, g, 3, 3) -- the guide line is
# the band's chrome cell (K wide), the three outer cells share the rest, both bands laid from their OWN outer edge (so
# the map mirrors), the middle is the engine-style NN; Wc = the VISIBLE column, rail_wall_off (the wall covers the
# rest).  The bar is the channel between the lines, [b, Wc - b) with b = cum(4, Wc, 32).  The plates and the grip share
# ONE span: w = fl(18g/16), one less when (bar - w) is odd (symmetry over 1-px exactness, user rule), centred.  Rows
# are untouched: the column blit keeps the engine's own row map (rail_blit_rows, measured on the real Buffer_draw_2).
# Every piece is g > 16 only; g <= 16 runs vanilla's bytes.
RAIL_BAND_CELLS = 4            # native cells per chrome band: outer 0..2 + the guide line 3 (and 28..31 mirrored)
RAIL_LINE_CELL = 3             # the line's cell in each band, counted from that band's outer edge
RAIL_GRIP_W = 18               # native arrow plate / thumb grip width (the 0x9B8DE8 arrow faces, the +0xA74 grip)
# The RAIL FAMILY = every ScrollBar whose window runs the rail recipe (rail_slide_in -> thunk_rail_bake / thunk_rail_sbfit
# lay its column and fit its bar by rail_layout_zones), so its arrow plates and thumb grip must sit on the SAME span
# (rail_grip_span(bar, 18, g), centred) -- t_rsb_israil's admission list, (parent identity, bar offset):
#   the ProdPicker static 0x6A8044 + 0x7120, the ReportWin static 0x876478 + 0xC10C, a FileDlg (vtbl 0x669EC8) + 0x3DD8,
#   a Popup ([vtbl+4] == Popup_show 0x404920) + 0x3230, and the Design Workshop PartPicker (vtbl 0x66B2B8) + 0xA14.
# The PartPicker runs the recipe through thunk_dw_pk_enter (the rail gate's ProdPicker comparand := the live picker) but
# was missing from the admission list until W9C F53 (2026-10-27): its column and bar were on the law while its plates
# went through StretchBlt's centre-NN (4K 45 px at 7 | 8) and its grip through t_sbt_grip (45 px at 8 | 7, user shot
# 20261027-133259), where rail_grip_span gives 44 at 8 | 8.  Every member must also be RAIL-FITTED (its client width ==
# the law's bar for its parent's canvas), as v3 requires.
RAIL_FAMILY_VTBL_BARS = ((0x669EC8, 0x3DD8), (0x66B2B8, 0xA14))   # (parent vtable, bar offset) members keyed on the vtable


def rail_col_w(win_w: int, g: int) -> int:
    """Wc: device width of the rail column the strip shows = the wall's offset in the baked strip (the wall covers the
    engine column's last px where rail_wall_off clamps).  g <= 16: 32."""
    return rail_wall_off(win_w, g)


RAIL_PLATE_COL = 7             # native strip col where the arrow plate / grip span starts (cols 7..24 = 4 + (24 - 18) / 2)


def mirror_nn_src(k: int, src_n: int, dst_n: int) -> int:
    """Mirror-exact centre-sampled NN: dest k of dst_n -> source of src_n.  The left half (and an odd centre) is the
    centre sample ((2k+1) src) / (2 dst); the right half is its mirror, src - 1 - left(dst - 1 - k), so dest k and
    dst - 1 - k always show mirror sources (plain centre sampling breaks that on an exact tie: w = 27, src 18 sends
    k = 1 -> 1 but k = 25 -> 17, a 1-px bevel asymmetry)."""
    m = dst_n - 1 - k
    if k <= m:
        return ((2 * k + 1) * src_n) // (2 * dst_n)
    return src_n - 1 - ((2 * m + 1) * src_n) // (2 * dst_n)


def rail_col_map(win_w: int, g: int) -> List[int]:
    """Dest column j (0 <= j < Wc, from the strip x) -> the native strip column it shows.  g <= 16: the identity over
    the 32 columns (vanilla's 1:1 blit).

    Mirror-exact, zone by zone (native 3 outer | 1 line | 3 channel | 18 plate | 3 channel | 1 line | 3 outer), on the
    layout rail_layout_zones picks (b, the grip span w, its offset off):
      * the chrome bands: the line K wide (cell 3), cells 0..2 share b - K (distribute) -- axis_map_chrome's band
        layout, at the band depth b of the min-max law instead of cum(4, Wc, 32);
      * the channel cells 4..6 share off (distribute);
      * the plate cells 7..24 land on the grip span by mirror_nn_src -- the top / bottom caps' art under the arrow
        plates (the plate-shaped ornament at native cols 7..24) lies exactly under the plates, so the arrows' key
        margins show no sliver of it (the plan's engine-NN middle put it 1 px right of the 4K plate);
      * the right half mirrors the left: m[Wc - 1 - j] = 31 - m[j]."""
    if g <= NATIVE_G:
        return list(range(RAIL_COL_W))
    wc = rail_col_w(win_w, g)
    b, w, off = rail_layout_zones(wc, g)
    k = stroke_width(g)
    out: List[int] = []
    for cell, width in enumerate(distribute(b - k, RAIL_LINE_CELL) + [k]):
        out.extend([cell] * width)
    chan = RAIL_PLATE_COL - RAIL_BAND_CELLS                     # 3 channel cells
    for j in range(off):
        out.append(RAIL_BAND_CELLS + next(i for i in range(chan) if j < cum(i + 1, off, chan)))
    for k in range(w):
        out.append(RAIL_PLATE_COL + mirror_nn_src(k, RAIL_GRIP_W, w))
    left = len(out)
    out.extend(RAIL_COL_W - 1 - out[b + off - 1 - i] for i in range(wc - left))
    # every column but an odd span's centre shows the mirror of its mirror column's source (the centre has none)
    assert len(out) == wc and all(out[wc - 1 - j] == RAIL_COL_W - 1 - out[j] for j in range(wc) if 2 * j != wc - 1)
    return out


RAIL_ZONE_VANILLA = (("outer", 3), ("bar", 24), ("plate", 18), ("channel", 3))   # native px of each laid zone


def rail_layout_zone_devs(wc: int, b: int, g: int) -> Optional[Tuple[int, ...]]:
    """16 x |device - vanilla x g/16| of every zone the band depth b decides, for a column Wc wide: outer b - K, the bar
    Wc - 2b, the plate / grip w = rail_grip_span(bar, 18, g) and its channel off.  None when the plate does not fit.
    (The line, K = stroke_width(g), does not depend on b.)"""
    k = stroke_width(g)
    bw = wc - 2 * b
    off, w = rail_grip_span(bw, RAIL_GRIP_W, g)
    if b < k or off < 0:
        return None
    vals = dict(outer=b - k, bar=bw, plate=w, channel=off)
    return tuple(abs(16 * vals[n] - v * g) for n, v in RAIL_ZONE_VANILLA)


def rail_layout_zones(wc: int, g: int) -> Tuple[int, int, int]:
    """(b, w, off) for a rail column Wc wide (audit W3B MEDIUM 2, 2026-10-25).  The layout is symmetric by
    construction (two K-wide lines, the bar [b, Wc - b), the grip span centred in it), so the one free choice is the
    band depth b.  LAW: b minimises the WORST per-zone deviation from vanilla x g/16 (rail_layout_zone_devs: outer,
    bar, plate, channel), b in [K, Wc / 2] with the plate fitting; ties go to the smaller SUM of deviations, then to
    the b nearest the proportional band 4 Wc / 32, then to the smaller b.  cum(4, Wc, 32) alone gave 1600x1200
    (Wc 51 = 2g + 1) bar 39 / outer 4 / channel 6 / plate 27 (three zones > 1 px off); the law gives bar 37 / outer 5 /
    channel 4 / plate 29, every zone within 0.88 px.  Every g 17..52: worst zone <= 1 px."""
    best = None
    for b in range(stroke_width(g), wc // 2 + 1):
        d = rail_layout_zone_devs(wc, b, g)
        if d is None:
            continue
        key = (max(d), sum(d), abs(32 * b - 4 * wc), b)
        if best is None or key < best[0]:
            best = (key, b)
    assert best is not None
    b = best[1]
    off, w = rail_grip_span(wc - 2 * b, RAIL_GRIP_W, g)
    return b, w, off


def rail_bar_inset(win_w: int, g: int) -> int:
    """b: the band depth = the bar's offset from the strip x; the bar is [b, Wc - b) (rail_layout_zones).  g <= 16: 4
    (vanilla col 4)."""
    if g <= NATIVE_G:
        return RAIL_CYAN_L + 1
    return rail_layout_zones(rail_col_w(win_w, g), g)[0]


def rail_line_spans(win_w: int, g: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """The two cyan guide lines, strip-local half-open [l, r): [b - K, b) and [Wc - b, Wc - b + K).  g <= 16: the
    native cols 3 and 28."""
    if g <= NATIVE_G:
        return (RAIL_CYAN_L, RAIL_CYAN_L + 1), (RAIL_CYAN_R, RAIL_CYAN_R + 1)
    b, wc, k = rail_bar_inset(win_w, g), rail_col_w(win_w, g), stroke_width(g)
    return (b - k, b), (wc - b, wc - b + k)


def rail_grip_span(inner_w: int, spr_w: int, g: int) -> Tuple[int, int]:
    """(offset, w) of the arrow plate / thumb grip inside a span inner_w wide (the bar, the arrow square, the thumb
    rect), centred -- both channels equal, so w must have inner_w's parity.  w = the inner_w-parity value NEAREST
    spr_w*g/16 (audit W3B MEDIUM 1: the v1 "fl, one less on the wrong parity" fell up to 1.875 px short where a
    same-parity value 0.125 px away existed, g 17 18 -> 20 for 19.125): fl(spr_w g/16) when its parity fits, else
    fl + 1 when spr_w g/16 has a fraction, else (an exact tie between fl - 1 and fl + 1) the SMALLER, fl - 1 (the
    tie rule: never wider than vanilla when it cannot be exact; 4K's 45 -> 44 in a 60 bar).  g <= 16: vanilla's
    `(inner_w - spr_w) / 2` (cdq; sub; sar = truncation) at spr_w."""
    if g <= NATIVE_G:
        return int((inner_w - spr_w) / 2), spr_w
    w = (spr_w * g) >> 4
    if (inner_w - w) & 1:
        w += 1 if (spr_w * g) & 15 else -1
    return (inner_w - w) >> 1, w


def rail_blit_rows(src_h: int, g: int, y0: int, canvas_h: int) -> List[int]:
    """The native strip row each dest row y0 + d shows, d = 0.. -- the ENGINE's own row map (Buffer_draw_2 at g/16,
    measured on the real image under Unicorn: dest rows fl(src_h*g/16), source row s over the run engine_scale_runs
    [s], clipped at the canvas bottom).  The column blit (t_rsb_blit) keeps it, so only columns move."""
    full = (src_h * g) >> 4
    out: List[int] = []
    for s, run in enumerate(engine_scale_runs(g, NATIVE_G, src_h)):
        for _ in range(run):
            if len(out) < full and y0 + len(out) < canvas_h:
                out.append(s)
    return out


def stretch_nn_src(i: int, src_n: int, dst_n: int) -> int:
    """GDI StretchBlt (COLORONCOLOR) dest column i -> source column: centre-aligned NN, measured (CLAUDE.md 'measure
    the engine'; image_emu's api_StretchBlt)."""
    return min(((2 * i + 1) * src_n) // (2 * dst_n), src_n - 1)


def rail_arrow_col_map(aw: int, wn: int, f0: int, f1: int, g: int) -> List[Optional[int]]:
    """A rail bar's arrow button, zoomed: dest column j (0 <= j < aw) -> the NATIVE column it shows (None = key 9).
    The native render (btn_shrink: wn = fl(aw*16/g) wide) draws the plate in columns [f0, f1) and nothing else; it
    lands on rail_grip_span(aw, f1 - f0, g) by mirror_nn_src (dest k and w - 1 - k show mirror columns); the margins
    are key.  Rows are StretchBlt's centre-NN (the KSB zoom's)."""
    off, w = rail_grip_span(aw, f1 - f0, g)
    out: List[Optional[int]] = []
    for j in range(aw):
        k = j - off
        out.append(f0 + mirror_nn_src(k, f1 - f0, w) if 0 <= k < w else None)
    return out


# ==== ARMED NON-RAIL SCROLLBARS: one span for plates and grip, on both axes (W10S F56, 2026-10-27; user-approved) ======
# Vanilla (pristine survey at 1024x768, scratchpad w9C\f53survey): every ScrollBar's arrow plates and thumb grip share
# ONE span centred in the bar -- the 20-px bars (the four Prefs Audio / Visual sliders, horizontal; the MP lobby chat and
# the popup heap list bars, vertical) an 18-px plate / grip at 1 | 1, the 12-px bars (base FACILITIES / SUPPORTED) a
# 10-px glyph / grip at 1 | 1 -- and the grip sits 1 | 1 in its square thumb rect on the long axis too.  Armed (the art
# zoomed at g > 16: thunk_pref_sbzoom's bracket, the lobby / Datalinks holders), the bars outside the rail family
# rounded on their own: the grip through thunk_sb_thumb's recentre x - fl(sw (g - 16) / 32) (22 at 1 | 2 at g 20, 45 at
# 3 | 2 at 4K), the plates through the keyed stretch of the whole native button (27 at 2 | 2 at g 25 where the grip is
# 28 at 1 | 2) -- a 1-px asymmetric channel and plate != grip at g 19..27 and 35..40 (F56, a regression from vanilla).
# LAW: an armed non-rail bar takes the rail family's span (rail_grip_span) on BOTH axes, so it holds for the horizontal
# sliders as for the vertical bars:
#   * the grip: (ox, w) = rail_grip_span(R - L, sw, g), (oy, h) = rail_grip_span(B - T, sh, g) in the thumb rect
#     (L, T, R, B) that ScrollBar_thumb_rect lays (the b x b square the press hit-tests), drawn by t_rsb_gripdraw;
#   * each arrow: its native plate square [c0, c0 + F) -- F the larger extent of the native render's non-key bbox, c0
#     its start on that axis: the plate is a square sprite centred on both axes of the square native render -- lands on
#     rail_grip_span(aw, F, g) on both axes, so plate span == grip span (the plate sprite and the grip sprite are
#     equally wide in every bar class), centred, key margins.  CENTRING ONLY (USER DECISION 2026-10-27): the face
#     pixels are a plain nearest-neighbour of the native plate at its new size, like the deployed art scaling (the
#     keyed stretch blit's GDI centre-NN, stretch_nn_src, of the whole native button) but with the MIRROR-EXACT
#     tie-break (mirror_nn_src, v5): the two differ only on tie pixels, and the centre tie-break broke the up / down
#     arrows' mirror at g 19 / 30 / 35 (20-px triangles) and 23 / 39 (12-px glyphs) where deployed kept it (audit
#     w10S v4; the user's rule: symmetry over 1-px exactness).  The scanline-art regeneration of v2 / v3 is deferred to
#     the stripe backlog.
# The gate (sb_nonrail_gate): g > 16, the object is a ScrollBar (its vtable's +0x34 is ScrollBar_on_resize: the exe's
# vtable and uimod.dll's private copies alike), and it is not a rail-family identity (t_rsb_israil's list, fitted or not:
# the rail family keeps its own paths).  The grip is reached only when thunk_sb_thumb arms it, an arrow only when
# thunk_btn_2dscale zooms it.  g <= 16: neither runs (vanilla's bytes).  Ports: assemble_nonrail_sb.py (t_nrs_*).
SB_ON_RESIZE = 0x606860            # ScrollBar_on_resize = [ScrollBar vtbl + 0x34]: the "is a ScrollBar" test
SB_ON_RESIZE_SLOT = 0x34
SB_ARROW_KEY = 9                   # the arrow buffers' key (the native render's margins)
SB_ARROW_MAX = 128                 # the zoom tables bound the arrow side (native and dest; every armed bar: <= 50 px)


def sb_nonrail_gate(g: int, is_scrollbar: bool, rail_identity: bool) -> bool:
    """The armed non-rail bar gate (above): g > 16, a ScrollBar, not a rail-family identity."""
    return g > NATIVE_G and is_scrollbar and not rail_identity


def sb_nonrail_grip_rect(thumb: Tuple[int, int, int, int], sw: int, sh: int, g: int) -> Tuple[int, int, int, int]:
    """(x, y, w, h) of an armed non-rail bar's grip in its thumb rect (L, T, R, B): rail_grip_span on each axis."""
    l, t, r, b = thumb
    ox, w = rail_grip_span(r - l, sw, g)
    oy, h = rail_grip_span(b - t, sh, g)
    return l + ox, t + oy, w, h


def sb_arrow_plate(native, wn: int, hn: int) -> Optional[Tuple[int, int]]:
    """(c0, F): the native plate square of an arrow's native render (rows of a wn x hn plane, key 9 margins) -- F the
    larger extent of the non-key bbox (columns win a tie), c0 its start on that axis.  None when nothing is drawn."""
    cols = [x for x in range(wn) if any(native[y][x] != SB_ARROW_KEY for y in range(hn))]
    rows = [y for y in range(hn) if any(native[y][x] != SB_ARROW_KEY for x in range(wn))]
    if not cols:
        return None
    fx, fy = cols[-1] + 1 - cols[0], rows[-1] + 1 - rows[0]
    return (cols[0], fx) if fx >= fy else (rows[0], fy)


def sb_nonrail_arrow(native, wn: int, hn: int, aw: int, ah: int, g: int) -> Optional[List[List[int]]]:
    """An armed non-rail bar's arrow, zoomed in place from its native render (wn x hn) to aw x ah (v5, centring only):
    the plate square (sb_arrow_plate) on rail_grip_span(aw, F, g) on both axes, its pixels a plain NN of the native
    plate, F -> w on each axis, with the mirror-exact tie-break (mirror_nn_src), key margins.  None = not re-laid (the zoom keeps its old
    path): g <= 16, a non-square native or dest, a side over SB_ARROW_MAX, nothing drawn, or a native row read BELOW the
    row it lands on (the in-place zoom writes the rows bottom-up)."""
    if g <= NATIVE_G or wn != hn or aw != ah or aw > SB_ARROW_MAX or wn > SB_ARROW_MAX:
        return None
    pl = sb_arrow_plate(native, wn, hn)
    if pl is None:
        return None
    c0, f = pl
    off, w = rail_grip_span(aw, f, g)
    if w <= 0 or off < 0:
        return None
    tab: List[Optional[int]] = [c0 + mirror_nn_src(k - off, f, w) if 0 <= k - off < w else None for k in range(aw)]
    if any(r is not None and r > y for y, r in enumerate(tab)):
        return None
    return [[SB_ARROW_KEY if tab[y] is None or tab[x] is None else native[tab[y]][tab[x]] for x in range(aw)]
            for y in range(ah)]


# ============================================================================
# SCENARIO EDITOR arc (2026-08-11) — two subsystems, one law each.
# Ground truth: hook_editorpanel_pin.js + hook_scenedit_census.js at g=40 AND
# g=25 (work\frida_editorpanel_pin.log, frida_scenedit_census.log); builder
# disassembly of DiploEditWin_exec 0x4DB080 and the MainWin_build tail
# 0x45AF62-0x45B4A0, immediates verified against the pristine .bak.
# ============================================================================

# Native anchors, all MEASURED (never eyeballed):
#  - rcConsoleCenter (MainWin+0xDA0) descales to the SAME native rect at g=40
#    and g=25 (655,165,1907,430)/2.5 == (409,103,1192,268)/1.5625 == below.
#  - seed formulas were confirmed INTEGER-EXACT against the live (bugged)
#    engine at both scales: x0 = rcCC.left+7; palette y0 = (top+7) +
#    ((bottom-7) - 5*18 - (top+7) - 4)//2; red y0 = (top+7) +
#    ((bottom-7)-(top+7) - (3*24+2))//2.  Evaluated at g=16 they give the
#    vanilla seeds below, so the g=16 identity is the engine's own arithmetic.
EDITOR_RCC_NATIVE = (262, 66, 763, 172)   # rcConsoleCenter at g=16, wide layouts
EDITOR_PAL_CELL_W, EDITOR_PAL_CELL_H = 43, 18   # interface.pcx (350,245) cells
EDITOR_PAL_PITCH_X, EDITOR_PAL_PITCH_Y = 44, 19  # cell + 1px gap
EDITOR_PAL_COLS, EDITOR_PAL_ROWS = 5, 5          # column-major, 25 buttons
EDITOR_PAL_X0, EDITOR_PAL_Y0 = 269, 72           # vanilla seed[0] top-left
EDITOR_RED_CELL = 24                             # red brush buttons (465,438)
EDITOR_RED_PITCH = 25
EDITOR_RED_X0, EDITOR_RED_Y0 = 497, 82           # vanilla brushSeed[0]
EDITOR_UNION_PAD = 3                             # engraved frame union +-3
EDITOR_INFO_PAD = 4                              # painter_editor_info insets
EDITOR_INFO_LINE_STEP = 13                       # native Buffer_text_line_height
EDITOR_INFO_RIGHT_PAD = 3                        # +0xD74 = I.l - 3 (`sub eax, 3` @0x45B497)
EDITOR_RED_CHAIN = 9                             # red x0 = paletteSeed[24].R + 9 (`add edi, 9` @0x45B073)


def editor_red_chain_delta(g: int) -> int:
    """LAW (2026-10-25 W3A, the red-brush flanks) -- how far the red-brush group (its 6 cells, their union frame and
    so the info rect's left edge) moves from the absolute scale_px(497) placement.

    Vanilla MainWin_build (pristine-verified) does NOT place the red brush absolutely: x0 = paletteSeed[24].R + 9
    (`mov edi, [esi+0xC64]; add edi, 9` @0x45B06D) -- the 9 is the palette frame's pad 3, the channel 3 and the red
    frame's pad 3 (both unions inflate the cells by 3).  editor_panel_seeds scaled every red x absolutely, so the
    channel between the two frames absorbed the palette's pinned-width shortfall and both roundings: palette | red
    vs red | info 8 | 6 at 4K (3 | 2 at 1600x900, 5 | 3 at g = 24; 3 | 3 at 1080 and 4 | 4 at 1600x1200 by
    accident).  The law chains it as vanilla does with the 9 decomposed into the three pads it is made of:
    x0 = pal[24].R + 3 * s(3), so the palette | red channel is the red | info one (both s(3) - 1 under the K-wide
    inclusive footprint, editor_info_channel) at every g: editor_red_flank_channels.  The cells keep their pinned size and pitch; the group moves by this delta
    (-2..+1 over g 16..64); every other element (palette, unions' pads, info right edge, the M / I / TOOLBAR column) is
    untouched.  0 at g <= 16 (and 16 * 488 / 16 + 9 == 497: the chain IS vanilla's arithmetic)."""
    if g <= NATIVE_G:
        return 0
    pal_r = scale_px(EDITOR_PAL_X0 + (EDITOR_PAL_COLS - 1) * EDITOR_PAL_PITCH_X, g) + scale_px(EDITOR_PAL_CELL_W, g)
    return pal_r + 3 * scale_px(EDITOR_UNION_PAD, g) - scale_px(EDITOR_RED_X0, g)


def editor_panel_seeds(g: int) -> dict:
    """LAW — map-editor console middle panel (palette + red buttons + frames).

    The vanilla bug class is [[feedback-remainder-distribution]] applied to a
    2-D grid: MainWin_build composes the ALREADY-SCALED rcConsoleCenter anchor
    with NATIVE cell dims and pads.  The law rebuilds every seed as
    vanilla x (g/16): each cell POSITION is scale_px of its vanilla ABSOLUTE
    position (LAW 1 per position — never top + i*floor(pitch), and not
    anchored-relative either: scale_px(anchor) + cum() compounds two
    roundings to 1.25px at g=25, which this module's own sweep caught),
    cell sizes PINNED equal via scale_px (cells are content; the 1px
    inter-cell gaps absorb the remainder), and the two engraved-frame unions
    + the info-rect left edge derived from the cells (LAW B — chrome follows
    content, so at g=16 the unions collapse to the engine's own +-3
    arithmetic algebraically).

    Returns column-major rect lists matching the engine arrays MainWin+0xADC
    (25) and +0xC6C (6), plus pal_union (+0xD4C), red_union (+0xD5C), and the
    info rect's left/top/bottom (+0xD6C; its RIGHT edge is editor_info_right:
    the live M/T/I seed [+0xA3C].left - scale_px(3), the mirror of info_left's
    pad, computed by MainWin_build itself @0x45B491 — native `- 3` there until
    fix 24's t_ed_info_right).  All rects (l, t, r, b).

    The red cells' x are scale_px of their vanilla absolute positions PLUS editor_red_chain_delta(g) (2026-10-25 W3A):
    the group is chained off the palette as vanilla chains it (x0 = pal[24].R + 3 * s(3)), so the red-brush frame's
    two flank channels are equal at every g (editor_red_flank_channels).  Ports: thunk_ed_seeds (absolute) then
    t_ed_redchain (its tail: shifts the 6 red seeds, the red-union stash and the info-left stash by the delta).
    """
    cw, ch = scale_px(EDITOR_PAL_CELL_W, g), scale_px(EDITOR_PAL_CELL_H, g)
    colx = [scale_px(EDITOR_PAL_X0 + i * EDITOR_PAL_PITCH_X, g)
            for i in range(EDITOR_PAL_COLS)]
    rowy = [scale_px(EDITOR_PAL_Y0 + i * EDITOR_PAL_PITCH_Y, g)
            for i in range(EDITOR_PAL_ROWS)]
    pal = [(x, y, x + cw, y + ch) for x in colx for y in rowy]
    rs = scale_px(EDITOR_RED_CELL, g)
    dx = editor_red_chain_delta(g)     # the red group chained off the palette (vanilla's x0 = pal.R + 9)
    rcolx = [scale_px(EDITOR_RED_X0 + i * EDITOR_RED_PITCH, g) + dx for i in range(2)]
    rrowy = [scale_px(EDITOR_RED_Y0 + i * EDITOR_RED_PITCH, g) for i in range(3)]
    red = [(x, y, x + rs, y + rs) for x in rcolx for y in rrowy]
    p3 = scale_px(EDITOR_UNION_PAD, g)
    pal_union = (pal[0][0] - p3, pal[0][1] - p3,
                 pal[-1][2] + p3, pal[-1][3] + p3)
    red_union = (red[0][0] - p3, red[0][1] - p3,
                 red[-1][2] + p3, red[-1][3] + p3)
    return {
        "pal": pal, "red": red,
        "pal_union": pal_union, "red_union": red_union,
        "info_left": red_union[2] + p3,
        "info_top": red_union[1], "info_bottom": red_union[3],
        "info_pad": scale_px(EDITOR_INFO_PAD, g),
        # painter_editor_info advances y by Buffer_text_line_height (native 13,
        # trace-proven) — [[feedback-font-metric-sublinearity]]: the scaled
        # font's OWN metric is sublinear (29 at g=40 vs lawful 32), which
        # orphans the bottom margin at 4K while g=25 lands snug by accident.
        # Substitute fl(13*g/16); at g=16 this IS the live metric (identity).
        "info_step": scale_px(EDITOR_INFO_LINE_STEP, g),
        "cell": (cw, ch), "red_cell": rs,
    }


def editor_info_right(col_l: int, g: int) -> int:
    """LAW (fix 24) — the scenario-editor info rect's RIGHT edge, MainWin +0xD74, from the live left edge col_l of
    the HUD M / I / TOOLBAR column (I.l, +0xA3C = hud_mi_column(g)[0]).

    Vanilla (MainWin_build 0x45B480..0x45B4A0, pristine-verified) builds the info rect between its two neighbours
    with one pad of 3 on each side: left = red_union.r + 3 (@0x45B486), right = I.l - 3 (`sub eax, 3` @0x45B497).
    editor_panel_seeds scales the LEFT pad (info_left = red_union.r + s(3), re-asserted by thunk_ed_painter); the
    RIGHT one stayed native, so at every g > 16 the box sat 2 px from the column but s(3) - 1 px from the red-brush
    frame (4K: 2 vs 6).  Law: right = col_l - s(3) with the same s(3) = scale_px(3, g) as the left pad, so the
    box's two flanking channels are equal at every g (the symmetry rule; editor_info_channel).  g <= 16: col_l - 3.
    Port: t_ed_info_right (call-redirected from 0x45B497, after the image's own `mov eax, [esi+0xA3C]`)."""
    if g <= NATIVE_G:
        return col_l - EDITOR_INFO_RIGHT_PAD
    return col_l - scale_px(EDITOR_INFO_RIGHT_PAD, g)


def editor_info_channel(g: int) -> int:
    """The visible channel (device px) on EACH side of the scenario-editor info box under editor_info_right and
    editor_panel_seeds: red-brush union's right stroke -> info left stroke, and info right stroke -> the M / I /
    TOOLBAR column.  Vanilla g = 16 (real image): red stroke 548, info strokes 552 / 730, column 734 -> 3 | 3 (the
    native box is half-open: right stroke on r - 1).  At g > 16 painter_editor_info's frame and the unions go through
    thunk_pp_boxsprite, whose K-wide footprint INCLUDES R0 (strokes R0-K+1..R0; prodpicker_sel_outline_rects), so a
    pad p leaves p - 1 on both sides: s(3) - 1 (4K 6 | 6; before fix 24 the right side was 3 - 1 = 2 at every g)."""
    if g <= NATIVE_G:
        return EDITOR_INFO_RIGHT_PAD
    return scale_px(EDITOR_INFO_RIGHT_PAD, g) - 1


def editor_red_flank_channels(g: int) -> Tuple[int, int]:
    """The red-brush frame's two flank channels (device px, on its mid row): palette union's right stroke -> red union's
    left stroke, and red union's right stroke -> the info box's left stroke, under editor_panel_seeds (frames drawn
    half-open at g = 16, with thunk_pp_boxsprite's inclusive K-wide footprint above).  Vanilla 3 | 3 (real image:
    strokes 490 / 494 / 548 / 552).  Law: both editor_info_channel(g) = s(3) - 1 at every g > 16 -- the mirrored pair
    (and so equal to the info box's own channel to the M / I / TOOLBAR column).  Before the chain (absolute red x):
    4K 8 | 6, 1600x900 3 | 2, 1920x1080 3 | 3, 1600x1200 4 | 4 -- the user's shots, reproduced on the real image."""
    s = editor_panel_seeds(g)
    inc = 1 if g > NATIVE_G else 0
    return (s["red_union"][0] - s["pal_union"][2] - inc, s["info_left"] - s["red_union"][2] - inc)


# DiploEditWin_exec 0x4DB080 vanilla immediates (all byte-verified in the
# pristine .bak; live trace at g=40 and g=25 shows them UNSCALED today):
DIPLO_W, DIPLO_H = 758, 398          # pushes @0x4DB0B0/B5 + dupes @0xa14/0xa18
DIPLO_PANEL_TOP, DIPLO_PANEL_BOT = 31, 370   # 0x1F / 0x172
DIPLO_BAND_H = 20                    # 0x14: title band AND button heights
DIPLO_FONT_DLG, DIPLO_FONT_TITLE = 14, 16
DIPLO_CHK_NATIVE_PITCH = 22          # measured: 6 rows in 339px @g=40 -> ~55dev
DIPLO_CHK_ROWS = 13


def diplo_editor_layout(g: int) -> dict:
    """LAW — the scenario-editor diplomacy modal (DiploEditWin_exec 0x4DB080).

    A PORT of the builder's own arithmetic with every native immediate
    replaced by scale_px(vanilla, g).  The derived quantities keep the
    engine's exact operator semantics so the g=16 identity is algebraic:
      - W//3 (imul 0x55555556) and W//2 (cdq/sub/sar) are trunc-toward-zero,
        == floor for positive W;
      - button width = (span + pad2)//4 with span = W - 2*pad4; the trailing
        button lands within 3px of the right inset (the /4 remainder), always
        PULLING IN, never overrunning (LAW B corollary).
    At g=16 every output equals the vanilla trace values (window 758x398,
    list (4,31,248,370), chk (383,31,754,370), buttons x=[4,192,380,568]
    w=186 y=374..394) — verified in test_scaling_scenedit.py.
    """
    W, H = scale_px(DIPLO_W, g), scale_px(DIPLO_H, g)
    i2, i3, i4 = scale_px(2, g), scale_px(3, g), scale_px(4, g)
    top, bot = scale_px(DIPLO_PANEL_TOP, g), scale_px(DIPLO_PANEL_BOT, g)
    band_h = scale_px(DIPLO_BAND_H, g)
    title_band = (i4, i4, W - i4, i4 + band_h)
    list_rect = (i4, top, W // 3 - i4, bot)
    list_content = (list_rect[0] + i3, list_rect[1] + i3,
                    list_rect[2] - i3, list_rect[3] - i3)
    half = W // 2
    chk_rect = (half + i4, top, 2 * half - i4, bot)
    left, right = i4, W - i4
    span = right - left
    bt = (span + i2) // 4
    btn_w = bt - i2
    btn_y1 = H - i4
    btn_y0 = btn_y1 - band_h
    return {
        "W": W, "H": H,
        "title_band": title_band, "title_inset": i3,
        "list_rect": list_rect, "list_content": list_content,
        "chk_rect": chk_rect,
        "btn_xs": [left + k * bt for k in range(4)],
        "btn_w": btn_w, "btn_y0": btn_y0, "btn_y1": btn_y1,
        "font_dlg": scale_px(DIPLO_FONT_DLG, g),
        "font_title": scale_px(DIPLO_FONT_TITLE, g),
        "pad2": i2, "pad3": i3, "pad4": i4, "band_h": band_h,
    }


# ==== type-16 rows/OK width — q16 (v4 EDITORWHO picker fix 2026-08-14; v6 = the law, below) ====
# (v1..v5 history first; the CURRENT law is the v6 paragraph.)
# The engine's own vanilla relation (both trace-proven at g=16, live exe,
# frida_scenedit_popupdiag.log): the type-16 rows child window IS the popup's
# content area — x = Lmargin, w = box_w - Lmargin - Rmargin (picker: x=19,
# w=597=637-19-21; quit: x=33, w=655=755-33-67).  At g>16 the attach still
# passes the NATIVE-space measured w ([D+0x5c]) while box_w is device, so
# thunk_q16_fill_width widens it: W' = max(w*g/16, arm2), ONLY-WIDEN.
#
# arm2 selection (v4):
#   - stash miss (menu popups / no field drawn):    arm2 = box_w - 2x
#   - stash hit  (this popup's field drew; fieldpads):
#       pds == 6 (PopupDialogState list family):    arm2 = box_w - 2x   [v4]
#       else:                                       arm2 = field_L + field_R - 2x
# The mirror (field) arm preserves a designed symmetric rows-inside-field
# inset (WIMPOUT class).  The pds=6 list family has NO such inset — its rows
# ARE the content area (x == Lmargin, insets 3/5 native, asymmetric), so the
# mirror degenerates to full-flush and overruns the right inner frame + rail
# (picker @4K: mirror 1502 vs lawful 1492; box arm 1489, right edge box-x =
# 1540 == vanilla*2.5 exactly).  Art popups already neuter the mirror via the
# fieldpads v5 L=R=0 stash (arm2 goes negative, wM wins) — quit unchanged.
# The stash is CONSUMED (boxw cleared) on every call that reaches the arm
# selection, matched or not — v3 semantics, kept.
#
# v5 (2026-09-28): the widening is COUNT-INDEPENDENT.  Vanilla's row width has
# no count term (Dialog_type16_calc_dimensions 0x60D380: [D+0x64] = [D+0x44] +
# [D+0x34] + max text width, [D+0x5c] = max([D+0x2c], [D+0x64]*cols) + 2*[D+0x40]
# - [D+0x44]), so a ONE-row list spans the content area exactly like a two-row
# one.  v1..v4 skipped count <= 1 (a prototype guard, never a law): the council
# propose picker with a single motion available drew its row 653 px wide beside
# a 1636-px OK/CANCEL pair at 4K (work\screenshots\_Problems\Council.png).
# count == 0 never reaches the attach site (the calc returns 7 and
# Dialog_type16_attach bails @0x60D22B); the law keeps it native for totality.
#
# v6 (2026-09-29): CHROME FOLLOWS CONTENT -- the row window ends where the popup's
# content ends, W = box_w - right_margin - x, and nothing else.  The OK / CANCEL
# bar is anchored the same way (BasePop_exec_3 0x602C51: x = -[popup+0x30F4], its
# right edge = box_w - [+0x30F4]), so rows and bar share their right edge by
# construction, which is the vanilla relation in every pristine option popup
# (Council / CouncilSingle / Quit rows 183..837 = the OK..CANCEL pair; WhoToVote
# 182..838; SELECT A FACTION 212..808).  At g = 16 the expression IS vanilla's
# own arithmetic (quit 755 - 67 - 33 = 655, picker 637 - 21 - 19 = 597).
# What it replaces, and why each term was wrong (pixels, 2026-09-29 census):
#   * wM = w*g/16: `w` is not native.  The calc runs twice; the first pass sees
#     the native gap [D+0x44] = 3 (Popup_calculate_dimensions resets it
#     @0x404D04) and yields 655, thunk_q16_rowgap then stores the DEVICE gap
#     (3 / 3 / 3 / 4 / 5 at g = 16 / 22 / 25 / 30 / 40) and the attach's pass
#     computes budget - gap = 654 @g30, 653 @g40 -> rows 1632 beside a 1637
#     OK..CANCEL pair at 4K (5 px short; flush at g22/g25 by luck).  Only when
#     the #xs budget wins the calc's max; with the measured row winning the gap
#     cancels, so no correction of `w` at the attach can be right for both.
#   * the field mirror (field_L + field_R - 2x): text popups overshot the OK bar
#     by 4 px @g25 and 6 px @g40 (Operations Director prompt); vanilla's inset
#     inside the field box is 5 left / 7 right, not symmetric.
#   * the box arm (box_w - 2x): right margin != left margin (in-game 33 / 67
#     native), so it ran past the content edge wherever it won.
# The fieldpads stash cells (g_field_L / _R / _boxw) and g_boxw_num are no longer
# read here.  Anchored popups never reach the thunk (t16_row_window_anchored).
# NOT covered: a list of more than [D+0x50] = 12 rows (two columns) -- the thunk
# still writes the whole width into the per-column [D+0x64], as v1..v5 did.

def q16_fill_width(g: int, w: int, x: int, box_w: int, mrg_r: int, count: int) -> int:
    """thunk_q16_fill_width v6: the width the type-16 row window (and
    [D+0x5c]/[D+0x64]) takes.  `w` = the attach's measured width, `x` = the row
    window's x in the popup, `box_w` = [popup+0x30BC], `mrg_r` = the popup's
    device right margin [popup+0x30F4].  Returns `w` unchanged at g<=16 /
    count<1 / when the content span is not wider than `w` (only-widen)."""
    if g <= 16 or count < 1:
        return w
    W = box_w - mrg_r - x
    return W if W > w else w


# ==== type-16 row window: which popups take the widening at all (2026-09-26) ====
# The engine's ANCHORED popup branch (BasePop +0xA14 = external window != 0; BasePop_calc
# 0x60391A, BasePop_exec_3 0x602677) seeds the Dialog's row budget [+0x2C] from the external
# window's DEVICE width (1750 @g40 for the diplomacy speech box, DiploTalkWin 0x733990), so its
# type-16 rows already span the box at attach time and thunk_q16_fill_width (then w*g/16;
# since v6 the popup-box span, which an anchored popup does not have) must not touch them.
# The diplo_talk_scale bake therefore skips the fill thunk for anchored
# popups -- but its two type-16 wrappers (t_dp_q16gate @0x60D299, t_dp_q16fixed @0x60D717)
# keyed the skip on "talk screen open" ([DiploTalkWin+0xA94] != -1) instead of the popup's
# own field.  An ORDINARY popup raised mid-talk (the #ASKSEEDESIGN "Operations Director"
# prompt from tech_achieved 0x5BB000 after a tech trade: X_pop flags 0, so BasePop_start
# 0x601C71 zeroes +0xA14) then drew its option rows at the native d5c width (655 device px
# @4K against a 1642-px OK bar, work\screenshots\_Problems\NewDesignsOverDiplo.png).
# LAW: the skip keys on the popup's +0xA14 exactly as the engine's ext branch does.  In this
# exe the field is only ever 0 or 0x733990 (writers: 0x600E05/0x6014BE copy
# g_popup_def_ext_win, whose sole writer 0x6050F0 is called only by DiploTalkWin_open;
# BasePop_set_external_window 0x605010 is unreferenced).

def t16_row_window_anchored(ext_win: int) -> bool:
    """LAW -- a type-16 popup's row window is already device-wide (skip
    thunk_q16_fill_width, leave the fixed-height gap arm alone) iff the popup is
    anchored to an external window: BasePop [+0xA14] != 0.  The talk-screen state
    is NOT a proxy for this (an ordinary popup can be raised mid-talk)."""
    return ext_win != 0


# ==== list-family popup hatch 0x54/0x41 (thunk_s54_restripe, 2026-08-14) ====
# The pds=6 list-family popup interior (EDITORWHO picker et al.) tiles a
# SIXTH dither pair, 0x54/0x41 (palette 84=(13,18,15) top / 65=black bottom;
# RLE dumps frida_scenedit_popupdiag.log 4K+native: whole interior 1px rows).
# devfill STEP2 tiles it 1:1 at device res -> 2.5x too fine @4K (same class
# as the C6/C4 interiors fixed 2026-07-04; this pair was deliberately outside
# DITHER_FORCE_PAIRS because 0x41 also partners C4/C6/C5 and solid fills).
# Fix: a dedicated pass (thunk_s54_restripe, wraps devfill's fe_pair_remap
# call) that is MATE-KEYED both ways (feedback-dither-pair-ambiguity): over
# <=8 scanned rows BOTH members must exceed width/2 (a 1px row-alternating
# hatch gives ~4w each; a solid 0x54 or solid 0x41 surface never fires).
# When keyed, BOTH members rewrite to the row colour (the rect is the freshly
# tiled mask, pure pair by construction; later draws overlay).  Same P/hN
# phase grid as every stripe producer.

def s54_hatch_keyed(count54: int, count41: int, width: int) -> bool:
    """Mate-keyed enable: both members dominate the scanned rows."""
    return count54 > width // 2 and count41 > width // 2


def s54_row_color(y: int, g: int) -> int:
    """Row colour of the restriped 0x54/0x41 hatch (colored member on top,
    matching every shipped stripe field)."""
    return 0x54 if stripe_top(y, g) else 0x41


# ==== report list-row / title-band hatch 0xC2/0x41 (thunk_s54_restripe v2, 2026-09-12) ====
# The HQ report pages' BASE STATUS entry boxes, list rows and the title band (and the
# Design Workshop's hovered slot, param set d550) tile a SEVENTH pair 0xC2/0x41 (palette
# 194=(13,28,48) top / 65=black bottom; the user's 4K/1600/1920 shots 2026-09-12 read it 1:1
# at every res -- sweep items F/G).  Same class as 0x54/0x41: devfill STEP2 tiles the mask 1:1
# at device density and fe_pair_remap's content-keyed families leave it alone.  0xC2 is
# AMBIGUOUS (it is ALSO the top member of the scrollbar-arrow face dither 0xC2/0xC5, restriped
# by thunk_btn_stripes' own pass -- scaling_laws.SBARROW_BG_TOP) so it stays OUT of
# DITHER_FORCE_PAIRS and takes the mate-keyed pass: over <=8 scanned rows BOTH members must
# exceed width/2 (a C2/C5 face has no 0x41 and never fires; a solid 0xC2 surface never
# fires).  When keyed, both members rewrite to the row colour on the shared P/hN phase grid --
# the fill is regenerated at device density like every other popup interior, and the rows'
# bottom edges end on the same partial band as every neighbouring stripe field (item G).

HATCH_MATE_PAIRS = {0x54: 0x41, 0xC2: 0x41}      # top (colored) member -> mate; pass order


def hatch_keyed(count_top: int, count_mate: int, width: int) -> bool:
    """Mate-keyed enable of one hatch pair: both members dominate the scanned rows."""
    return count_top > width // 2 and count_mate > width // 2


def hatch_pair_for(counts: dict, width: int):
    """The hatch pair the pass restripes for a scanned rect: the first HATCH_MATE_PAIRS top
    whose family is mate-keyed (0x54 before 0xC2), or None.  A freshly tiled mask is pure
    pair by construction, so at most one top member can dominate."""
    for top, mate in HATCH_MATE_PAIRS.items():
        if hatch_keyed(counts.get(top, 0), counts.get(mate, 0), width):
            return top
    return None


def hatch_row_color(top: int, y: int, g: int) -> int:
    """Row colour of a restriped hatch pair (colored member on the top band)."""
    return top if stripe_top(y, g) else HATCH_MATE_PAIRS[top]


# ==== DIPLOMACY talk screen (diplo_talk_scale, assemble_diplo.py; proto hook_diplo_proto.js) ====
# Anchored speech box + the console-strip content under it.  MIXED-SPACE class: MainWin seeds and
# the anchor (DiploTalkWin 700x450 -> fl(700g/16) x fl(450g/16)) are device-space; every native
# +-1/2/3/4/6/7/0x14/0x1B/0x37... constant scales fl(k*g/16); frame strokes K = stroke_width(g),
# h1 = diplo_far_edge_trim(g) (1 at every g > 16: half-open far edge -> inclusive band-map footprint),
# title thickener grows outward by frame_grow_delta(g).
# Cumulative anchors where vanilla chains constants (remainder law): hdr B = D80.T + fl(24g/16),
# body T = D80.T + fl(26g/16), centre = DC0 inset fl(7g/16), centre.B = DC0.B - fl(30g/16).

def dp(v: int, g: int) -> int:
    """floor(v*g/16), identity at g<=16 (the whole diplo bake's sc())."""
    return v if g <= 16 else (v * g) >> 4


def diplo_strip_rect_table(seeds: dict, flcW: int, g: int) -> dict:
    """DiploTalkWin rect table (offsets 0x20C4..0x2144) from the MainWin seed rects
    D80/D90/DB0/DC0/A8C/A9C (device) and the faction.flc width (native).  Returns
    {offset: (L,T,R,B)}.  Vanilla: g=16 reproduces DiploTalkWin_init 0x4407B3..0x440A2A."""
    D80, D90, DB0, DC0, A8C, A9C = (seeds[k] for k in ("D80", "D90", "DB0", "DC0", "A8C", "A9C"))
    s3, s4, s6, s7, s20 = dp(3, g), dp(4, g), dp(6, g), dp(7, g), dp(20, g)
    hq2144 = (D90[2] - A9C[2] + D90[0], A8C[1], A8C[0] - s3, A8C[3])
    hq2114 = (D90[0] + s4, D90[1] + s4, D90[2] - s4, hq2144[1] - s6)
    r2104 = (DB0[0] + s4, DB0[1] + s4, DB0[2] - s4, DB0[3] - s4)
    c = (DC0[0] + s7, DC0[1] + s7, DC0[2] - s7, DC0[3] - s7)
    hh = int((c[2] - c[0] + s3) / 2)
    dl = (c[0], c[3] - s20, c[0] + hh - s3, c[3])
    pr = (c[0] + hh, c[3] - s20, c[0] + hh - s3 + hh, c[3])
    c20F4 = (c[0], c[1], c[2], DC0[3] - dp(30, g))
    nwL = D80[2] - s4 - dp(flcW + 2, g)
    nw = (nwL, D80[1] + s4, D80[2] - s4, D80[3] - s4)
    bh = (D80[0] + s4, D80[1] + s4, nwL - s3, D80[1] + dp(24, g))
    bb = (D80[0] + s4, D80[1] + dp(26, g), nwL - s3, D80[3] - s4)
    return {0x20C4: bh, 0x20D4: bb, 0x20E4: nw, 0x20F4: c20F4, 0x2104: r2104, 0x2114: hq2114,
            0x2124: dl, 0x2134: pr, 0x2144: hq2144}


def diplo_far_edge_trim(g: int) -> int:
    """LAW — h1, the far-edge trim of the anchored DIPLOMACY speech box: 1 at every g > 16, else 0.

    It computes only that constant.  diplo_speech_rects subtracts it, and six thunks of assemble_diplo.py
    port it as a literal `mov reg, 1` (h1_into; each is gated g > 16; test_diplo_asm_parity H1_THUNKS),
    at exactly these edges:
      * t_dp_fill (GraphicWin_fill_2 @0x405D0B): fill R.  The caller copies the same rect into the
        backdrop d690 box (@0x405D39 -> thunk_box_thick_devfill), so the backdrop R carries it too.
        The fill/backdrop B (clipB + sc(5)) is NOT trimmed.
      * t_dp_title_outer (d5a0 @0x405D91) and t_dp_title_inner (d618 @0x405DC6), both -> thunk_box_thick:
        R AND B.
      * t_dp_title_text (write_cent_l_7 @0x405E31): the TITLE TEXT rect is trimmed as well, R AND B
        (it is outer' inset 2*sc(3), and outer' carries -h1), so the centred title moves with the frame.
      * t_dp_textblock (d528 @0x405E95 -> thunk_box_thick_devfill): R only (d528.B is not trimmed);
        the final union (t_dp_knest @0x405EA6) gets it from the d528 locals the caller re-reads.
      * t_dp_wrapwidth (the 0x603E42 / 0x603F3D repoints): the measure width (from d528.R).
    Left and top edges are never trimmed.  The type-16 option rows are NOT trimmed by this law:
    t_dp_itemrect trims them by its own literal `dec` (law t16_item_draw_rect).

    Vanilla's Buffer_box_sprite draws the HALF-OPEN box [L,R)x[T,B) (far strokes at R-1/B-1); the
    band map paints the INCLUSIVE footprint (far strokes END at R/B), so the scaled half-open edge
    comes in by exactly ONE device px at every g > 16 = bandmap_rect_from_halfopen; 0 at g <= 16
    (the native primitive draws).

    Supersedes h1 = K-1 (K = stroke_width, the 2026-08 proto model "the flat thickener draws R/B at
    [E-1, E-1+K-1]"): K-1 is 1 only for g = 25..40 (G_MAX), 0 at g = 17..24, so at 1920x1080
    (g = 22) the backdrop, title and speech box all drew one px too far right and the title one
    row too tall (verifier, live c9f3a45b shot 20261017-115317).  At g = 25..40 the value is
    unchanged."""
    return 1 if g > NATIVE_G else 0


def diplo_speech_rects(clip: tuple, f: dict, g: int) -> dict:
    """Anchored speech-box rects on the DiploTalkWin canvas (clip = TW +0x474 L,T,R,B; f = popup
    fields 30F0/30D8/21C8/30E0/30E8/30D4).  fill/backdrop, title outer/inner/text, text-block d528,
    final union (d528 -+ sc3), art x/y (before the art fn's own -5/-6), measure width.
    h1 = diplo_far_edge_trim (1 at g > 16); the art x keeps K (the drawn left stroke's width)."""
    L, T, R, B = clip
    K = stroke_width(g); h1 = diplo_far_edge_trim(g); D = frame_grow_delta(g)
    s3 = dp(3, g)
    fill = (L + dp(0x17, g), T, R - dp(0x37, g) - h1, B + dp(5, g))
    outer = (L + dp(0x1B, g) + D, T + dp(4, g) + D, R - dp(0x3B, g) - D - h1, T + dp(0x1C, g) - D - h1)
    inner = (outer[0] + s3, outer[1] + s3, outer[2] - s3, outer[3] - s3)
    text = (inner[0] + s3, inner[1] + s3, inner[2] - s3, inner[3] - s3)
    d528 = (f[0x30F0] + f[0x30D8] + f[0x21C8] + f[0x30E0] - s3,
            f[0x30E8] + f[0x30E0] - dp(6, g) + s3,
            R - dp(0x3B, g) - h1 - s3,
            f[0x30D4] + f[0x30E8] + f[0x30E0] + s3 - 3)
    final = (d528[0] - s3, d528[1] - s3, d528[2] + s3, d528[3] + s3)
    art = (L + dp(0x1B, g) + K + 5, f[0x30E8] - dp(6, g) + 6)
    measure = d528[2] - f[0x30F0] - f[0x30D8] - dp(5, g)
    return {"fill": fill, "outer": outer, "inner": inner, "text": text, "d528": d528, "final": final,
            "art": art, "measure": measure}


def diplo_q16_fixed_gap(rowH: int, g: int) -> int:
    """Type-16 fixed-height (anchored) arm: gap' = max(0, half_down(22g,16) - rowH) (Site-B law)."""
    if g <= 16 or rowH <= 0:
        return None
    return max(0, half_down(22 * g, NATIVE_G) - rowH)


# ---- status-panel "DIPLOMATIC STATUS: <treaty>" line fit (2026-10-11; port t_dp_status_fit in assemble_diplo.py) ----
# DiploTalkWin_draw_status_panels wraps the line with Buffer_wrap_3 @0x43FE07 in the DiploTalkWin +0xA44 font
# (Font_init(g_hud_font_name = "Arial", 12, 0); scaled to fl(12g/16) by t_fontinit).  Vanilla (g = 16):
# panel0 (269..511), x = L+3+2+65+3 = 342, w = (R-3)-3-x = 163; "DIPLOMATIC STATUS: NONE" measures 161 px =
# 2 px of slack, so GDI's per-size advance rounding wraps NONE onto a second line at g = 24/36/40/44 (4K: 411 px
# in a 410 px budget).  TRUCE (168) / TREATY (171) / VENDETTA (188) wrap in vanilla itself.  Law = the
# se_label_fit idiom keyed on vanilla's line count: when the string fits ONE line in vanilla's font + budget,
# step the font down from fl(12g/16) until it fits one line in the device budget (min 8); when vanilla wraps
# it, leave the scaled font alone (the wrap IS vanilla's layout).  The measure is the painter's own break
# finder (Buffer_find_line_break_l: 0 = no break), so "fits" == width <= budget.  g <= 16 -> native.
DIPLO_STATUS_FONT_NATIVE = 12
DIPLO_STATUS_FONT_MIN = 8
DIPLO_STATUS_DC0_NATIVE_LR = (262, 763)    # MainWin DC0 seed L/R at g = 16 (device = fl(v*g/16))
DIPLO_STATUS_LOGO_W = 65                   # faction logo sprite width (interface.pcx cell 65x50)
DIPLO_STATUS_NATIVE_W = 163                # vanilla's wrap width at g = 16 (= diplo_status_wrap(16)[1])


def diplo_status_panel0(g: int, dc0_lr: Tuple[int, int] = None) -> Tuple[int, int]:
    """(L, R) of status panel 0 (the other faction's): the 20F4 rect (DC0 inset s7) split (W+s3)>>1 - s3
    (t_dp_box_panel).  dc0_lr = the DEVICE DC0 seed L/R (default fl(native*g/16))."""
    if dc0_lr is None:
        dc0_lr = (dp(DIPLO_STATUS_DC0_NATIVE_LR[0], g), dp(DIPLO_STATUS_DC0_NATIVE_LR[1], g))
    s3, s7 = dp(3, g), dp(7, g)
    L, R = dc0_lr[0] + s7, dc0_lr[1] - s7
    return L, L + ((R - L + s3) >> 1) - s3


def diplo_status_wrap(g: int, dc0_lr: Tuple[int, int] = None, logo_w: int = DIPLO_STATUS_LOGO_W) -> Tuple[int, int]:
    """(x, w) handed to Buffer_wrap_3 for the panel-0 status lines (t_dp_txt_wrap3 / t_dp_status_fit):
    x = p.L + 2*s3 + s2 + dp(logo_w); w = p.R - 2*s3 - x."""
    pL, pR = diplo_status_panel0(g, dc0_lr)
    s2, s3 = dp(2, g), dp(3, g)
    x = pL + 2 * s3 + s2 + dp(logo_w, g)
    return x, pR - 2 * s3 - x


def diplo_status_font_size(g: int, width, budget: int) -> int:
    """Font size the status line is drawn with at g.  width(size) = the line's width in the +0xA44 face at
    that size (the painter's break-finder measure); budget = the device wrap width (t_dp_txt_wrap3).
    vanilla wraps (width(12) > DIPLO_STATUS_NATIVE_W) -> fl(12g/16) unchanged; else step down from fl(12g/16)
    until width(size) <= budget or size == DIPLO_STATUS_FONT_MIN.  g <= 16 -> the native 12."""
    if g <= NATIVE_G:
        return DIPLO_STATUS_FONT_NATIVE
    size = dp(DIPLO_STATUS_FONT_NATIVE, g)
    if width(DIPLO_STATUS_FONT_NATIVE) > DIPLO_STATUS_NATIVE_W:
        return size
    while size > DIPLO_STATUS_FONT_MIN and width(size) > budget:
        size -= 1
    return size


def diplo_status_next_y(y_wrap: int, lh_status: int, lh_drawn: int) -> int:
    """The y handed on to the INFILTRATION / Energy / Might lines (the painter keeps wrap_3's return in ebx
    @0x43FE0C).  wrap_3 advances y by its font's line height per line ([f] >= 0 ? [f+0x10]+[f] : [f+0xC]);
    when the fit font drew the (one) line, swap its advance for one +0xA44 line: y_wrap - lh_drawn + lh_status,
    so the block below sits exactly where vanilla's one-line layout x g/16 puts it, whatever the status word.
    lh_drawn == lh_status (no fit) -> y_wrap unchanged."""
    return y_wrap - lh_drawn + lh_status


def diplo_q16_row_width(budget: int, margin: int, cols: int, g: int):
    """Type-16 ANCHORED row width [D+0x64] (t_dp_q16anch, 2026-10-11).  The
    engine's fixed-width branch (Dialog_type16_calc 0x60D690) writes
    (budget - 2*margin)/cols - [D+0x44]: vanilla's row gap is the native 3, so
    the rows end 3 px short of the OK bar (pristine Diplomacy\\Opening.png:
    rows 211..808, OK 211..811).  At scale [D+0x44] is the VERTICAL gap
    diplo_q16_fixed_gap (5 @g40, sublinear font height), so the horizontal
    trim shrank to 5 where vanilla x g/16 is 7.5.  The trim is the native 3
    scaled with the popup-pitch floor popup_pad(3, g) — the same 3-px pitch
    every other popup chrome relation uses, a single constant (no run, so no
    remainder distribution).  None at g <= 16 (native no-op).

    "Rows end ps3 short of the OK bar" holds for cols == 1 only: with N
    columns each column is (B - 2m)/N wide and the trim applies per column
    (the per-column floor and the 2m margin move the last column's end).
    Wrap: the draw wraps a row at [D+0x64] - [D+0x34] while the calc sizes
    the row's height from B/cols - 2m - [D+0x34]; the gap between the two
    is exactly this trim (cols == 1), the one band of text widths that
    wraps to an extra line the row was not sized for -- vanilla's own 3 px
    band, scaled (test_diplo_q16_reply_wrap_spill_band_is_vanilla_scaled)."""
    if g <= NATIVE_G:
        return None
    n = budget - 2 * margin
    q = abs(n) // abs(cols)                      # idiv truncates toward zero
    return (q if (n >= 0) == (cols > 0) else -q) - popup_pad(3, g)


def t16_item_draw_rect(l: int, t: int, r: int, b: int, g: int, anchored: bool = False,
                       dialog_type: int = 16) -> Tuple[int, int, int, int]:
    """LAW — the rect a TYPE-16 option row's frame is drawn from (t_dp_itemrect v2, the
    wrapper at all four Popup_on_dialog_item_back_draw vtable slots).

    The row frame (0x405BF6) reaches the band map through thunk_rowbox_guard ->
    thunk_box_thick_hollow_flat, which paints the INCLUSIVE footprint, so the
    rect the draw loop builds (half-open: L = margin + col*(w+gap), R = L + [D+0x64],
    B = T + rowH) must come in by ONE on the far edges = bandmap_rect_from_halfopen.
    Then the drawn row is exactly [D+0x64] x rowH, the OK/CANCEL FlatButtons'
    height, and the visible inter-row gap is option_row_gap's.

    Supersedes the 2026-08 "lever R" (trim K-1, K = stroke_width): K-1 equals 1
    only for g >= 25, so at g = 17..24 the diplomacy reply rows drew one px too
    wide and too tall (1920x1080: 822 x 28 for an 821 x 27 rect); and the plain
    type-16 rows (Quit, Planetary Council propose) had no trim at all (51/32/28
    vs OK 50/31/27 at 4K/1600/1080).  On the plain rows R-1 moves no pixel when
    the row window is exactly [D+0x64] wide (thunk_q16_fill_width writes both):
    hollow_flat already clamps R to W-1.

    Anchored (diplomacy) rows trim the caller's rect itself; plain rows hand the
    native fn a trimmed COPY (the caller's text centring is not moved).  Other
    dialog types and g <= 16: unchanged.  (The native fn 0x405B20 draws only the
    checkbox sprite and the row frame; the row's content is the caller's draw.)

    Scope: the option ROWS only.  The speech-box TITLE is not this law's: its two
    frames (d5a0/d618) AND its title TEXT rect (write_cent_l_7 @0x405E31,
    t_dp_title_text) are trimmed R and B by diplo_far_edge_trim, so the title
    text IS trimmed -- by that law, not by this one."""
    if g <= NATIVE_G or not (anchored or dialog_type == 16):
        return (l, t, r, b)
    return bandmap_rect_from_halfopen(l, t, r, b, g)


# ==== PLANETARY COUNCIL session screen (council_scale; proto hook_council_proto.js) ====
# CouncilWin 0x6FEC80: exec FUN_00427230 (seed table + fonts + GraphicWin_init),
# repaint FUN_00426aa0, column painter FUN_00425db0, proposal painter FUN_00426470.
# Ground truth: frida_council_trace.log 2026-08-21 @1024/g16 (vanilla-value trace on
# the live exe — g<=16 is the native no-op) + exec/painter disassembly immediates.
# MIXED-SPACE class: the console proposal rect 0x7AF5C0 and g_console_strip_height
# arrive DEVICE-scaled (HUD bakes); every seed rect and +-1/2/3/4/10/0x14/0x17/
# 0x37 painter constant is native.
# BUTTON FACES (no arithmetic law here): the 6 CouncilWin FlatButtons render
# their 9-slice with the ctor-DEFAULT pieces (T/TL/TR only, 67x20 native) —
# a native 20px bar in the scaled 50px rect.  The fix is NOT a rect law: the
# baked popup_button_2dzoom pipeline (thunk_btn_shrink native-render ->
# thunk_btn_2dscale KSB zoom + device restripe) is armed for these 6 buttons
# by a gate HIT on ESI in [CWIN+0xD94, +6*0xB4C) (proto v7 lever G; bake =
# gate_pre v2).  council_button_row above stays the geometry authority.  All ports use dp() (floor), matching the
# imm-rewrite lever shapes.  The +1/-1 box_sprite frame insets in the column
# painter are INC/DEC instructions (not patchable immediates): the proto keeps
# them native and these laws model that faithfully via the `frame_inset`
# parameter (1 in the proto; sc(1) once the bake thunks the painter).

# Vanilla window (exec 0x4279c4..0x427a1d): 812x min(395, SH-strip), centered
# on (SW-780)/2, bottom resting on the console strip.
COUNCIL_W, COUNCIL_H_CAP, COUNCIL_CENTER_W = 0x32C, 0x18B, 0x30C
# Seed table vanilla values (trace lines banner/params/cols, byte-identical to
# the exec immediates).  Columns: 7 slots; outer set = governor-seated layout
# (chevron tops, tall center slot 3), inner set = no-governor layout (flat).
COUNCIL_BANNER = (245, 355, 538, 378)                 # [0xBA4] ELECTED banner
COUNCIL_PARAMS = (30, 750, 27)                        # [0xBC4],[0xBCC],[0xBD0]
COUNCIL_OUTER_L = (30, 130, 230, 330, 452, 552, 652)  # [0xBF4+0x20c]
COUNCIL_OUTER_T = (53, 45, 37, 29, 37, 45, 53)
COUNCIL_INNER_L = (32, 135, 238, 341, 444, 547, 650)  # [0xC04+0x20c]
COUNCIL_INNER_T = 29
COUNCIL_COL_W, COUNCIL_COL_H = 98, 282                # all slots except...
COUNCIL_CENTER_COL_W, COUNCIL_CENTER_COL_H = 120, 323 # ...outer center (slot 3)
# Painter constants (all native immediates, addresses in the proto):
COUNCIL_CHIP_H = 0x17      # chip bottom band height (top = B-1-sc(0x17))
COUNCIL_LIFT = 0x14        # votes-label lift above the chip; also hdr band h
COUNCIL_PAD3, COUNCIL_PAD4, COUNCIL_PAD2 = 3, 4, 2
COUNCIL_LOGO_GAP = 10      # name baseline -> faction logo y gap
COUNCIL_BACKDROP_L, COUNCIL_BACKDROP_RSUB = 0x17, 0x37  # repaint backdrop rect
COUNCIL_FONTS = (20, 14, 14, 12, 12, 14)  # b7c, adc, ab4, b04, b2c, b54
COUNCIL_NAME_PAD = 5       # [font b04 +0] line pad written after Font_init


def council_window_rect(screen_w: int, screen_h: int, strip_h: int,
                        g: int) -> Tuple[int, int, int, int]:
    """LAW — CouncilWin geometry (x, y, w, h).  w/h/centering vanilla x g/16
    (strip_h arrives device-scaled); the height cap binds exactly like
    vanilla's (short screens shrink the window, content clips bottom —
    vanilla-faithful).  g=16: (SW-780)/2, SH-strip-395, 812, 395."""
    w = dp(COUNCIL_W, g)
    h = min(dp(COUNCIL_H_CAP, g), screen_h - strip_h)
    x = (screen_w - dp(COUNCIL_CENTER_W, g)) // 2
    y = (screen_h - strip_h) - h
    return (x, y, w, h)


def council_seed_rects(g: int) -> dict:
    """LAW — the CouncilWin seed-rect table, device space.

    Each column rect scales as position fl(L,T) + PINNED size (fl(w), fl(h))
    (LAW 3 shape: the 7 columns must share one width; the 2-5px inter-column
    gaps absorb the remainder — max drift 1px, columns never butt).  Banner
    and params are plain per-field dp().  g=16 reproduces the trace table
    verbatim."""
    w, h = dp(COUNCIL_COL_W, g), dp(COUNCIL_COL_H, g)
    cw, ch = dp(COUNCIL_CENTER_COL_W, g), dp(COUNCIL_CENTER_COL_H, g)
    outer = []
    for c in range(7):
        ll, tt = dp(COUNCIL_OUTER_L[c], g), dp(COUNCIL_OUTER_T[c], g)
        if c == 3:
            outer.append((ll, tt, ll + cw, tt + ch))
        else:
            outer.append((ll, tt, ll + w, tt + h))
    inner = [(dp(l, g), dp(COUNCIL_INNER_T, g),
              dp(l, g) + w, dp(COUNCIL_INNER_T, g) + h)
             for l in COUNCIL_INNER_L]
    return {
        "banner": tuple(dp(v, g) for v in COUNCIL_BANNER),
        "params": tuple(dp(v, g) for v in COUNCIL_PARAMS),
        "outer": outer, "inner": inner,
    }


def council_button_row(con_rect: Tuple[int, int, int, int], g: int) -> dict:
    """LAW — the console button row, a PORT of exec 0x427661..0x427776.

    `con_rect` = the DEVICE console proposal rect [0x7AF5C0..].  Box = con
    inset sc(4); text-area bottom [0xBC0] = btnT - sc(3); the full-width
    button [0xD04] (VOTE) spans (box.L+sc3, btnT, box.R-sc3, box.B-sc3) with
    btnT = box.B - sc(0x17).  g=16 == trace btn rects.

    The three thirds (the YES / NO / ABSTAIN FlatButtons [0xCD4], [0xCE4], [0xCF4], parented to MainWin, x = L,
    w = R - L at BaseButton_init 0x427A89 / 0x427B7B / 0x427BEA): vanilla's exec (pristine-verified) is
        third = trunc((R - L + 3) / 3)          # `add eax, 3` @0x4276EF, the 0x55555556 imul
        r0    = L + third - 3                   # `lea edx, [edx+ecx-3]` @0x427704 (disp8 @0x427707)
        step  = r0 - L + 3                      # `add eax, 3` @0x427726 / @0x427751
    i.e. three cells of w = third - 3 with 3-px seams, the remainder rem = (R - L + 3) mod 3 dropped at the right
    end (vanilla 1024: R - third[2].R = 1).  "thirds_engine" is that block with every native 3 -> sc(3) -- what the
    image computes once all four 3s are in the council imm table (F43, 2026-10-25: the disp8 @0x427707 was missing,
    so the cells were third - 3 wide with sc(3) seams and the row ran 3 * (sc(3) - 3) px past the VOTE's right edge:
    4K third[2] = (2136, 2541) against R = 2530, 6 px over the d5a0 ring stroke).
    g > 16 "thirds" (t_cw_rowsym, the E8 @0x427784 wrapper ahead of thunk_cw_seeds): the same three cells and seams
    with the dropped remainder distributed by popup_button_row_bounds (the fix-19 button-row law, mirrored about the
    centre) -- outer edges ON the VOTE's edges (third[0].L = L, third[2].R = R), seams sc(3), widths a palindrome
    (rem 1: w, w+1, w; rem 2: w+1, w, w+1).  The symmetry rule over the remainder's 1 px; rem = 0 is the identity.
    g <= 16: vanilla's thirds exactly (thirds == thirds_engine)."""
    s3, s4 = dp(COUNCIL_PAD3, g), dp(COUNCIL_PAD4, g)
    s17 = dp(COUNCIL_CHIP_H, g)
    box = (con_rect[0] + s4, con_rect[1] + s4,
           con_rect[2] - s4, con_rect[3] - s4)
    b3 = box[3] - s3
    top = b3 - (s17 - s3)          # == box.B - s17
    text_bottom = top - s3         # [0xBC0]
    L, R = box[0] + s3, box[2] - s3
    full = (L, top, R, b3)
    span = R - L + s3
    third = _idiv(span, 3)         # idiv trunc, matching the 0x55555556 imul
    r0 = third - s3 + L
    step = (r0 - L) + s3
    engine = [(L, top, r0, b3),
              (L + step, top, r0 + step, b3),
              (L + 2 * step, top, r0 + 2 * step, b3)]
    btns = engine
    if g > NATIVE_G:
        b = popup_button_row_bounds(R - L - 2 * s3, 3)
        btns = [(L + b[i] + i * s3, top, L + b[i + 1] + i * s3, b3) for i in range(3)]
    return {"box": box, "full": full, "thirds": btns, "thirds_engine": engine,
            "text_bottom": text_bottom, "btn_top": top}


def council_thirds_fixup(full_r: int, thirds: List[Tuple[int, int, int, int]], g: int) -> List[Tuple[int, int, int, int]]:
    """The arithmetic t_cw_rowsym applies to the image's thirds_engine (council_button_row): rem = VOTE.R -
    third[2].R; when g > 16 and 0 <= rem <= 2 (unsigned compare), with d1 = rem >> 1 and e = rem - d1:
    third[0].R += d1, third[1].L += d1, third[1].R += e, third[2].L += e, third[2].R += rem.  Anything else (g <= 16,
    a remainder outside the law -- e.g. the imm table not yet applied) leaves the rects untouched.  == "thirds" of
    council_button_row for every lawful row (pinned by the tests)."""
    t = [list(r) for r in thirds]
    rem = full_r - t[2][2]
    if g <= NATIVE_G or not 0 <= rem <= 2:
        return [tuple(r) for r in t]
    d1 = rem >> 1
    e = rem - d1
    t[0][2] += d1
    t[1][0] += d1
    t[1][2] += e
    t[2][0] += e
    t[2][2] += rem
    return [tuple(r) for r in t]


# The three Buffer_box_sprite draws onto the console canvas 0x7AEC64 that frame the proposal / VOTE row (all three
# HALF-OPEN engine rects): CouncilWin_repaint's d5a0 box = the console proposal rect inset 4 (the VOTE row's ring),
# CouncilWin_draw_proposal's d618 header band [T, T+0x14) and its d528 body box [T+0x16, text_bottom).
COUNCIL_CONSOLE_FRAME_SITES = {0x426B14: 0x78D5A0, 0x4264DD: 0x78D618, 0x4265AB: 0x78D528}


def council_console_frame_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-25 wave-2 W2A, F31) -- the rect the band-map renderer gets for COUNCIL_CONSOLE_FRAME_SITES.

    Those draws reach thunk_box_thick_hollow_flat through the Buffer_box_sprite prologue hook (thunk_hud_boxframe's
    pass-through for the console canvas), which hands it the half-open rect UNTRIMMED: the band map's inclusive
    footprint put the right / bottom strokes on col R / row B, one px outside the native extent -- the VOTE row's ring
    came out 5 | 6 at 4K (3 | 4 at 1920x1080 and 2560x1440) and 3 | 4 top / bottom at 1080.  The rect is
    bandmap_rect_from_halfopen's (L, T, R-1, B-1) at g > 16 (t_rw_rowframe, the report screens' identical d5a0 / d528
    treatment); g <= 16 the native primitive's half-open render, unchanged.
    The drawn channels around the VOTE row are then vanilla x g/16: council_vote_channels."""
    return bandmap_rect_from_halfopen(l, t, r, b, g)


def council_vote_channels(con_rect: Tuple[int, int, int, int], g: int) -> dict:
    """The DRAWN channels (device px) around the full-width VOTE button under council_button_row and
    council_console_frame_rect: L / R / B to the d5a0 box (inset 4 from the console proposal rect, strokes K wide on
    its outer cols / rows), T to the d528 body box's bottom stroke (that box's half-open B is text_bottom = btnT - s3).

    Vanilla (g = 16, K = 1, half-open): L = R = B = 2, T = 3 -- the body box's bottom stroke sits on row
    text_bottom - 1, one row higher than the d5a0's bottom stroke relative to the button (vanilla's own 3 | 2, not a
    mirrored pair).  Scaled: L = R = B = s(3) - K, T = s(3), i.e. vanilla x g/16 for every one (4K 5 / 5 / 5 and 7 for
    2 x 2.5 and 3 x 2.5; 1920x1080 3 / 3 / 3 and 4 for 2.75 and 4.125), and L == R at every g."""
    row = council_button_row(con_rect, g)
    K = stroke_width(g) if g > NATIVE_G else 1
    box = row["box"]
    bl, bt, br, bb = council_console_frame_rect(*box, g) if g > NATIVE_G else (box[0], box[1], box[2] - 1, box[3] - 1)
    L, T, R, B = row["full"]
    body_bottom_last = row["text_bottom"] - 1          # half-open body box: bottom stroke ends on text_bottom - 1
    return {"L": L - (bl + K), "R": (br - K + 1) - R, "B": (bb - K + 1) - B, "T": T - (body_bottom_last + 1)}


COUNCIL_CHIP_PAD = 4      # vanilla: the chip sits 4 px inside its column on L / R / B (the frame inset 1 + the pad 3)


def council_frame_inset(g: int) -> int:
    """LAW (2026-10-25 wave-6 W6B; t_cw_inset @0x425EEE) -- the column painter's frame inset fi: the rect it draws the
    portrait, the name lines, the logo, the chip and the votes label in is the column rect inset fi on every side.
    Vanilla's INC / DEC is 1 = the d528 frame's stroke, so the portrait (96 wide in the 98-wide column) abuts both
    strokes; scaled, the inset is the stroke the band map draws, stroke_width(g) (v1 kept the native 1: at K = 2 the
    portrait covered the left stroke's inner column and left 2 px of black before the right one at 4K).  g <= 16: 1."""
    return stroke_width(g) if g > NATIVE_G else 1


def council_column_vanilla_w(col_w: int, g: int) -> int:
    """The vanilla width of a scaled council column: 120 for the governor's centre column (outer set slot 3), 98 for
    every other (both sets) -- told apart by the device width alone (16w > 109g), as t_cw_chipfix does."""
    return COUNCIL_CENTER_COL_W if 16 * col_w > 109 * g else COUNCIL_COL_W


def council_chip_pad(col_w: int, g: int) -> int:
    """LAW v3 (2026-10-25 wave-6 W6B v2, user: chip widths within 1 px) -- the chip's inset from its column on L / R /
    B (one value, so the three stay equal).  Vanilla: 4 in every column, the chip vw - 8 wide (90 / 112).  The device
    columns are not all vw x g/16 wide (the floor; W5B's parity +1 for the centre columns), so a fixed dp(4) left the
    chip up to 2.1 px off its own vanilla x g/16 width (governor g 19/22/27/30/34/39 +2.0; the wider inner centre column
    +1.25..+2.12).  The pad is solved from the column: p = round((col_w - (vw - 8) g/16) / 2) =
    half_down(16 col_w - (vw - 8) g, 32) -- the chip width within 1 px of exact (2p steps by 2) and, as the column is
    within ~1 px of vw g/16, p within 0.75 px of 4g/16 (swept g 17..64, every column kind).  Mirrored columns are
    one width, so mirrored chips share p.  g = 16: 4 (= vanilla)."""
    vw = council_column_vanilla_w(col_w, g)
    return half_down(16 * col_w - (vw - 2 * COUNCIL_CHIP_PAD) * g, 32)


def council_chip_fix_delta(col_w: int, g: int) -> int:
    """t_cw_chipfix's correction (E8 @0x426135, after the painter's chip block): the painter builds the chip from the
    inset rect with its scaled pad, (L'+s3, B'-s17, R'-s3, B'-s3), L' = L + fi; the law wants it council_chip_pad
    inside the column, so L / R / T / B move by d = pad - dp(3) - fi."""
    return council_chip_pad(col_w, g) - dp(COUNCIL_PAD3, g) - council_frame_inset(g)


def council_chip_rects(inner: Tuple[int, int, int, int], g: int) -> dict:
    """LAW v3 (2026-10-25 wave-6 W6B v2) -- the vote chip + votes-label rects from a DEVICE column rect.

    Vanilla (the column painter 0x426113..0x426135): chip = (L+1+3, B-1-0x17, R-1-3, B-1-3) -- 4 px inside the column
    on L / R / B, 20 tall -- inner col0 (32,29,130,311) -> (36,287,126,307), votes label = the chip lifted by its
    own height 0x14 -> (36,267,126,287).  Scaled: the inset p = council_chip_pad(column width) on L / R / B (W6B v1:
    dp(4) everywhere; deployed before: fi + dp(3) with the native fi = 1, 8 against 10 at 4K); the height
    h = dp(0x17) - dp(3) (LAW B -- the label lift is the chip band itself, so the label bottom stays flush on the
    chip top at every g): chip = (L + p, B - p - h, R - p, B - p), votes = chip - h.  g <= 16: vanilla."""
    s3 = dp(COUNCIL_PAD3, g)
    s17 = dp(COUNCIL_CHIP_H, g)
    s14 = s17 - s3
    L, T, R, B = inner
    p = council_chip_pad(R - L, g) if g > NATIVE_G else COUNCIL_CHIP_PAD
    chip = (L + p, B - p - s14, R - p, B - p)
    votes = (chip[0], chip[1] - s14, chip[2], chip[3] - s14)
    return {"chip": chip, "votes": votes}


COUNCIL_PORTRAIT_W = 96    # the small council portrait canvas (the 98-wide column's interior)
COUNCIL_PORTRAIT_BIG_W = 118  # the governor's portrait (the 120-wide centre column's interior)


def council_portrait_slack(col_w: int, sprite_w: int, g: int) -> int:
    """Device px of the column interior (col_w - 2 fi) the portrait (dp(sprite_w) wide, Sprite_draw_2 at g/16) does
    not fill -- vanilla 0 (the portrait abuts both strokes) in both kinds; scaled -1 .. +2 (the governor column:
    W5B's parity +1 and the floors)."""
    return col_w - 2 * council_frame_inset(g) - dp(sprite_w, g)


def council_portrait_xy(inner: Tuple[int, int, int, int], g: int, sprite_w: Optional[int] = None) -> Tuple[int, int]:
    """LAW v2 (W6B v2, user: "centre it") -- the portrait's draw origin (Sprite_draw_2 @0x425F3C via t_cw_portx):
    (L + fi + half, T + fi), half = the interior slack split equally, an odd px on the RIGHT (trunc toward zero:
    +1 -> 0 | +1, -1 -> 0 | -1, +2 -> +1 | +1).  Everything else in the column centres on the interior already (the
    name lines on (L'+R')/2, the logo by council_logo_x) and the hit Spot is the column rect, so they all agree with
    the centred portrait.  Vertically the portrait abuts the top stroke (T + fi) and the name line follows its bottom
    (council_text_y) -- there is no bounded vertical slack.  sprite_w None: the column kind's vanilla canvas."""
    fi = council_frame_inset(g)
    L, T, R, B = inner
    if sprite_w is None:
        sprite_w = (COUNCIL_PORTRAIT_BIG_W if council_column_vanilla_w(R - L, g) == COUNCIL_CENTER_COL_W
                    else COUNCIL_PORTRAIT_W)
    half = 0
    if g > NATIVE_G:
        sl = council_portrait_slack(R - L, sprite_w, g)
        half = sl // 2 if sl >= 0 else -((-sl) // 2)
    return L + fi + half, T + fi


def council_portrait_gaps(col_w: int, sprite_w: int, g: int) -> Tuple[int, int]:
    """(left, right) device px between the strokes' inner edges and the portrait under council_portrait_xy (vanilla
    0 | 0): equal when the slack is even, the odd px on the right."""
    sl = council_portrait_slack(col_w, sprite_w, g)
    half = 0 if g <= NATIVE_G else (sl // 2 if sl >= 0 else -((-sl) // 2))
    return half, sl - half


def council_backdrop_rect_v1(win_w: int, win_h_abs: int, g: int) -> Tuple[int, int, int, int]:
    """SUPERSEDED (2026-10-25 wave-5 W5B; kept as the reference the before-build draws): thunk_cw_backdrop37's rect,
    (dp(0x17), 0, W - dp(0x37), H + 1) drawn INCLUSIVE.  W - dp(0x37) is 1 (4K) .. 3 px right of the rails' own
    cascade (council_rail_mirror_sum) and the band map drew col R as well: the right border sat under the inner right
    rail at every g > 16 (4K 3840x2160 shot 20261024-233251: R = 1893, rail at 1892), and dp(0x17) is 1 px right of
    the left rails' extent at g = 17, 19, 21, 23, 33, 35, 37, 39 (a see-through column)."""
    return (dp(COUNCIL_BACKDROP_L, g), 0,
            win_w - dp(COUNCIL_BACKDROP_RSUB, g), win_h_abs + 1)


def council_rail_mirror_sum(win_w: int, g: int) -> int:
    """LAW (2026-10-25 wave-5 W5B) -- S1, the half-open mirror sum of the CouncilWin's slide rails: a rect [a, b) and
    its mirror [S1 - b, S1 - a) sit symmetrically between them.  The council SLIDES (its iface show 0x426FA0 calls
    slide_show through thunk_popup_railshow), so its side rails are the generic 15 / 8 x 529 strips through railscale:
    left [0, rail_left_extent), right inner strip at rail_right_strip_x(W, W - 0x37) (the double floor every abutting
    frame reads), the outer one abutting it -- the right pair the exact mirror of the left (inner 8, outer 15 device
    floors), ending at S1 - 1.  S1 = inner right strip x + left extent.  Vanilla: W - 0x37 + 23 = 780 (the 812-wide
    canvas centred on 780).  The rails' span is 0..4 px short of 780g/16 (the double floor; 4K 1949 vs 1950, g = 35
    1702 vs 1706): the council layout mirrors about the rails as they are drawn, never about 780g/16."""
    if g <= NATIVE_G:
        return win_w - RAIL_INNER_RIGHT_OFF + sum(SE_RAIL_LEFT_STRIPS)
    return rail_right_strip_x(win_w, win_w - RAIL_INNER_RIGHT_OFF, g) + rail_left_extent(g)


def council_backdrop_rect(win_w: int, win_h_abs: int, g: int) -> Tuple[int, int, int, int]:
    """LAW v2 (2026-10-25 wave-5 W5B; t_cw_backdrop @0x426B4E) -- the repaint's d690 backdrop rect, drawn HALF-OPEN.

    Vanilla (0x426b2a..0x426b4e) (0x17, 0, W - 0x37, H + 1) is exactly the rails' inner edges: the left rails cover
    [0, 0x17), the inner right strip starts at W - 0x37.  At g > 16 both edges follow the rails' own cascades (the
    se_backdrop_rect precedent): L = rail_left_extent, R = the inner right strip x = council_rail_mirror_sum - L, so
    the left and right borders are both K wide and mirror each other (4K: 57..58 | 1890..1891 between rails ending at
    56 / starting at 1892).  B = H + 1 is vanilla's own overdraw: the 1-px bottom stroke falls one row below the
    canvas (measured at 1024: the last canvas row 394 holds the backdrop's side strokes and the ring's bottom chamfer
    row, no horizontal stroke), as does the ring's, which inherits B.  v3 (2026-10-25 wave-7 W7B, t_cw_bd2): B = H + K,
    the K-row scaled stroke below the canvas, and the frame CLIPPED there, not clamped (council_frame_clip; v2 left
    H + 1 and the band map's clamp squeezed the frame into the canvas: both bottom strokes on its last rows, 4K screen
    rows 1626..1627 in the console's centre notch).  The rect stays in the repaint's frame and the d5a0 ring
    (0x426B7B) is it inset dp(4) on L / T / R (council_ring_rect).  g <= 16: vanilla."""
    if g <= NATIVE_G:
        return (COUNCIL_BACKDROP_L, 0, win_w - COUNCIL_BACKDROP_RSUB, win_h_abs + 1)
    left = rail_left_extent(g)
    return (left, 0, council_rail_mirror_sum(win_w, g) - left, win_h_abs + stroke_width(g))


def council_frame_clip(rect: Tuple[int, int, int, int], canvas_h: int) -> Tuple[int, int, int, int]:
    """LAW (W7B; t_cw_clipdraw) -- what a council frame draw covers: the frame is rendered for its WHOLE half-open rect
    and the canvas keeps rows [T, min(B, H)) of it -- the native Buffer_box_sprite's clip, vanilla's behaviour.  The
    band-map renderers instead clamp the rect to the canvas (B <= H - 1 inclusive: thunk_clamp_frame_rect) and redraw
    the whole frame inside, so a frame that runs below the canvas shows its bottom stroke on the last rows; the
    council's backdrop / ring go through a canvas-wide scratch instead (only when B > H)."""
    l, t, r, b = rect
    return (l, t, r, min(b, canvas_h))


def council_ring_rect(win_w: int, win_h_abs: int, g: int) -> Tuple[int, int, int, int]:
    """The repaint's second d5a0 draw (0x426B5C..0x426B7B): the backdrop rect inset dp(4) on L / T / R (the 4 is in
    g_cw_immtab), B unchanged; drawn HALF-OPEN (t_bm_ho_hf at g > 16).  Self-mirrored about the rails because the
    backdrop is."""
    l, t, r, b = council_backdrop_rect(win_w, win_h_abs, g)
    s4 = dp(COUNCIL_PAD4, g)
    return (l + s4, t + s4, r - s4, b)


def council_centre_width(s1: int, w: int) -> int:
    """A self-mirrored council column (the centre slot 3, both sets) of law width w: the nearest width to vanilla x g/16
    whose parity lets it sit exactly centred, w + ((s1 - w) & 1) (w = dp() is the floor, so w + 1 is never farther from
    the exact width than w - 1).  The symmetry rule over the 1 px."""
    return w + ((s1 - w) & 1)


#: vanilla's ring -> column 0 channel and the three gaps up to the centre column, per set: ring L 0x17 + 4 = 27,
#: stroke 1, so the run starts at 28 (inner: 32 - 28 = 4, 135 - 130 = 238 - 233 = 341 - 336 = 5; outer: 2 each).
#: These are the WEIGHTS of the scaled run (council_mirror_cols): derived from the seed constants, never retyped.
COUNCIL_RUN_START = COUNCIL_BACKDROP_L + COUNCIL_PAD4 + 1


def council_channel_weights(left: Tuple[int, ...]) -> Tuple[int, int, int, int]:
    """(ring -> col0, col0 | col1, col1 | col2, col2 | col3) of one vanilla set (COUNCIL_INNER_L / COUNCIL_OUTER_L, the
    side columns COUNCIL_COL_W wide): inner (4, 5, 5, 5), outer (2, 2, 2, 2)."""
    return (left[0] - COUNCIL_RUN_START,) + tuple(left[i + 1] - (left[i] + COUNCIL_COL_W) for i in range(3))


def council_mirror_cols(cols: List[Tuple[int, int, int, int]], s1: int, centre_w: int, start: int,
                        weights: Tuple[int, ...]) -> List[Tuple[int, int, int, int]]:
    """t_cw_mirror's arithmetic (2026-10-25 wave-5 W5B, v2 after audit-w5B) on one seven-column set.

    The centre column 3 keeps its T / B, width council_centre_width(S1, centre_w), L3 = (S1 - width) / 2 (exactly
    centred between the rails).  The left half is ONE run from `start` (the ring's inner edge: ring L + its stroke K)
    to L3: four channels (ring -> col0 and the three gaps) and three side columns of their seed width w.  The channel
    budget B = L3 - start - 3w is split by the WEIGHTED remainder law -- the vanilla channels as weights, cum() over the
    cumulative weight -- so col c's L = start + cum(w_0 + .. + w_c, B, sum(w)) + c * w.  Columns 6 - c are the mirrors,
    (S1 - R_c, T, S1 - L_c, B) -- vanilla's own relation (30 + 749 = 32 + 747 = 779 = S1 - 1 for every pair).
    v1 left columns 0..2 on their dp() seeds and dropped the rails' 0..4 px shortfall (railscale's double floor) into
    the two centre gaps alone: governor set 1080 [3, 4, 2, 2, 4, 3] where vanilla x g/16 is 2.75 each, 4K [5, 5, 4, ..]
    with ring -> col 6 against 5.  Now every channel is within 1.38 px (governor) / 1.31 px (inner) of vanilla x g/16
    for g 17..64 (4K governor set exact: 5 everywhere), at the cost of moving columns 0..2 by at most 2 px.
    g = 16: the identity (B = 8 / 19 = the weights' sum)."""
    out = [tuple(c) for c in cols]
    l3, t3, r3, b3 = cols[3]
    w3 = council_centre_width(s1, centre_w)
    l3 = (s1 - w3) >> 1
    out[3] = (l3, t3, l3 + w3, b3)
    w = cols[0][2] - cols[0][0]
    budget = l3 - start - 3 * w
    total = sum(weights)
    acc = 0
    for c in range(3):
        acc += weights[c]
        left = start + cum(acc, budget, total) + c * w
        _l, t, _r, b = cols[c]
        out[c] = (left, t, left + w, b)
        _l6, t6, _r6, b6 = cols[6 - c]
        out[6 - c] = (s1 - left - w, t6, s1 - left, b6)
    return out


def council_column_rects(g: int) -> dict:
    """LAW (2026-10-25 wave-5 W5B) -- the column rects the painters READ: thunk_cw_seeds' council_seed_rects, then
    t_cw_mirror (the seeds thunk's tail, before Font_init) re-lays both sets about the rails (council_mirror_cols) at
    g > 16 with S1 = council_rail_mirror_sum(dp(812), g) -- the canvas GraphicWin_init creates right after (imm
    0x427A14 = dp(0x32C)) -- and the run start = the ring's inner edge (rail extent + dp(4) + stroke_width).  Banner and params are untouched (the banner is not centred in
    vanilla: 245 + 537 = 782).  g <= 16: the seeds verbatim (vanilla is mirrored already, S1 = 780)."""
    s = council_seed_rects(g)
    if g <= NATIVE_G:
        return s
    s1 = council_rail_mirror_sum(dp(COUNCIL_W, g), g)
    start = council_backdrop_rect(dp(COUNCIL_W, g), 0, g)[0] + dp(COUNCIL_PAD4, g) + stroke_width(g)
    out = dict(s)
    out["outer"] = council_mirror_cols(s["outer"], s1, dp(COUNCIL_CENTER_COL_W, g), start,
                                       council_channel_weights(COUNCIL_OUTER_L))
    out["inner"] = council_mirror_cols(s["inner"], s1, dp(COUNCIL_COL_W, g), start,
                                       council_channel_weights(COUNCIL_INNER_L))
    out["s1"] = s1
    out["start"] = start
    return out


def council_drawn(rect: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """The INCLUSIVE footprint a council frame draw covers (the backdrop, the d5a0 ring, the column frames, the chips):
    half-open [L, R) x [T, B) at every g -- vanilla's native render; at g > 16 the band map gets (L, T, R - 1, B - 1)
    (bandmap_rect_from_halfopen, via t_cw_hodf / t_bm_ho_hf / t_cw_chiphalf)."""
    l, t, r, b = rect
    return (l, t, r - 1, b - 1)


def council_layout_channels(g: int, inner: bool = True) -> dict:
    """The council's mirrored channels (device px), left value vs right value, from the laws above: the backdrop
    border widths, border -> ring, ring -> outer column, the six inter-column gaps (paired outside-in), and the
    column -> chip channels.  Every pair equal at every g (pinned by the tests)."""
    W = dp(COUNCIL_W, g)
    K = stroke_width(g) if g > NATIVE_G else 1
    bd = council_drawn(council_backdrop_rect(W, 0, g), g)
    rg = council_drawn(council_ring_rect(W, 0, g), g)
    cols = [council_drawn(c, g) for c in council_column_rects(g)["inner" if inner else "outer"]]
    gaps = [cols[i + 1][0] - cols[i][2] - 1 for i in range(6)]
    chips = [council_drawn(council_chip_rects(c, g)["chip"], g) for c in council_column_rects(g)["inner" if inner else "outer"]]
    return {
        "border": (K, K),
        "border_ring": (rg[0] - (bd[0] + K), (bd[2] - K + 1) - rg[2] - 1),
        "ring_col": (cols[0][0] - (rg[0] + K), (rg[2] - K + 1) - cols[6][2] - 1),
        "gaps": [(gaps[i], gaps[5 - i]) for i in range(3)],
        "col_chip": [((ch[0] - (c[0] + K)), (c[2] - K + 1) - ch[2] - 1) for c, ch in zip(cols, chips)],
        "chip_mirror": [(chips[i][0] - cols[i][0], cols[6 - i][2] - chips[6 - i][2]) for i in range(3)],
    }


def council_text_y(t_dev: int, portrait_canvas_h: int, g: int,
                   frame_inset: Optional[int] = None) -> int:
    """LAW — leader name line-1 y: the painter's T+fi + [spr+0x1c] + 4 with
    the sprite canvas height (native field) and the 4 scaled: y = T_dev + fi
    + dp(canvas_h) + sc(4).  The proto applies the (dp(ph)-ph) delta at the
    Buffer_write_cent_l_8 call sites since [spr+0x1c] is a runtime read.
    fi defaults to council_frame_inset(g) (W6B: the line follows the portrait)."""
    fi = council_frame_inset(g) if frame_inset is None else frame_inset
    return t_dev + fi + dp(portrait_canvas_h, g) + dp(COUNCIL_PAD4, g)


def council_logo_x(l_dev: int, r_dev: int, canvas_w: int, g: int,
                   frame_inset: Optional[int] = None) -> int:
    """LAW — faction logo centering with the DEVICE content width:
    x = (L+fi) + ((R-fi) - (L+fi) - dp(canvas_w))//2 (trunc, span>=0): the slack split, an odd px on the right (the
    portrait's rule, council_portrait_xy).  Vanilla centers with the NATIVE canvas width — at g>16 that lands the
    logo ~half the growth too far right.  fi defaults to council_frame_inset(g).  Enforced since 2026-10-25 W7B by
    t_cw_logox: thunk_cw_logo's two-step recentre ((span - cw) >> 1 then + (cw - dp(cw)) >> 1, two floors) was up to
    2 px off it -- the real 86-wide canvas 12 | 14 at 4K, 7 | 9 at g = 24 (vanilla 5 | 5)."""
    fi = council_frame_inset(g) if frame_inset is None else frame_inset
    lo, hi = l_dev + fi, r_dev - fi
    return lo + (hi - lo - dp(canvas_w, g)) // 2


def council_sd2_pre(target_dev: int, off_native: int, g: int) -> int:
    """RETIRED FOR THE COUNCIL PATH — do NOT port to the council bake.

    Premise DISPROVEN by the 2026-08-22 v5 run (screenshot 005016): the
    council portrait/logo Sprite_draw_2 path draws AT the x/y args
    UNMODIFIED — num/den only zooms the sprite CONTENT.  Pre-descaling the
    args by x*16/g bunched every portrait at 0.4x positions (col0 at window
    x~32 = descaled 80).  The council fix (proto v6+) passes device x/y
    straight through and sets only num=g/den=16.

    Kept solely as a record of the floor/ceil-bracket descale arithmetic in
    case some OTHER sd2 call site genuinely re-scales its args (none is
    currently known to; measure the engine before believing one does):
    to land content at `target_dev` under an engine that places it at
    fl((x+off)*g/16), pick between floor and ceil descale whichever renders
    closer (blind CEIL overshoots up to 2px at fractional g — the sweep
    caught it).  Ties pull IN (floor, LAW B corollary).
    g=16 identity: x = target - off."""
    if g <= 16:
        return target_dev - off_native
    flo = target_dev * 16 // g
    cei = -(-target_dev * 16 // g)
    dflo = (flo * g) >> 4
    dcei = (cei * g) >> 4
    pick = flo if abs(dflo - target_dev) <= abs(dcei - target_dev) else cei
    return pick - off_native


def council_castvote_art(x_seed_dev: int, y_seed_dev: int, g: int) -> Tuple[int, int]:
    """LAW — Cast-a-Vote (#GOVVOTE) popup art position (proto v9 lever V,
    stub over the per-instance [popup+0x3168] fn-ptr): IDENTITY PASS-THROUGH.

    BasePop_on_redraw hands the art draw the popup's margin-sum seeds
    (x = [30e0]+[30f0]+[21c8], y = [30e8]+[30e0], window-relative for
    self-parent popups).  Those seeds are ALREADY DEVICE-SCALED by the
    baked popup chrome patches (run-8 [gv] ARMED dump @g40: [30e8]=117 =
    dp(38)+dp(9) via the baked header_reserve_resume store; [30f0]=47) —
    the v8 dp(seed-5)+5 form DOUBLE-SCALED (art measured at winT+277 =
    exactly the double-scale prediction; the [[feedback-shared-field-per-
    row-doublescale]] class: a baked store-site patch had scaled the field
    first — grep patches.yaml for a store patch on any seed field BEFORE
    assuming it is native).

    The engine's own seeds reproduce every vanilla relation (art flush-left
    with the rows, tucked under the title band, clear of the rows — the
    pristine layout); the ONLY defect was the t_dp_artalign ->
    thunk_popup_artalign QUOTE-BOX override (g_field_anchor y law).  So the
    whole fix is BYPASS: gated popup -> thunk_sprite_draw with the args
    untouched.  Art SIZE needs nothing either: the flag sprite is built at
    the 1024-baseline (~200x120) and the baked popup_art_scaling ratio
    [3104]/[3108] = g/16 zooms it lawfully (pristine 4K draws it x45/16
    UNCLAMPED = 556x329, confirming the native).

    v2 Y-COMPENSATION (2026-08-23, gv_arthead armed branch only):
    thunk_sprite_draw applies vanilla's NATIVE draw offset x-5,y-6 (bytes
    83 E9 05 83 EA 06, byte-parity with sprite_draw_func 0x404860) to the
    DEVICE seeds, so art_top = y_dev - 6 instead of y_dev - dp(6): the flag
    lands dp(6)-6 px LOW (9 dev @g40, 3 @g25, 0 at g<=16).  Pixel-measured
    on build aaeb05d5 vs refs\\pristine\\Council\\BadCastVote.png (a 1024
    capture PRACX-stretched x2.8125): band-gap 12.4 -> 16.0 native and
    row-gap 8.2 -> 4.8 native, BOTH restored exactly by +9 dev.  Invisible
    through proto v28 because band+field sat ~6 dev low with it; title_stash
    v7 (v5 bake) fixed the band and exposed the art.  Y' = y - (dp(6)-6).
    v3 X-COMPENSATION (2026-10-14): the same native offset hits x — the
    engine's `sub ecx,5` on the DEVICE x seed leaves the flag (5g>>4)-5 dev
    px RIGHT of vanilla (7 @g40, 2 @g25, 1 @g22, 0 at g<=16).  Attributed by
    two relations at two scales (exe 4a5abdc8, user shots 232732 @4K and
    233126 @1600 vs BadCastVote.png, measured against the popup's inner
    frame line): frame->flag 8.8 / 7.0 native vs vanilla 6.0 (= +7 / +2
    dev), and row_left - flag_left 1.20 / 1.92 native vs vanilla 3.91;
    frame->row 11.2 / 10.9 vs 11.4 (the rows are right).  The v2 note's
    "+3.7 dev @g40, does not fit" reading was on a pre-v5 build and not
    frame-relative.  X' = x - ((5g>>4)-5), applied by t_gv_artx from the
    same armed branch.  g<=16 identity."""
    if g <= 16:
        return (x_seed_dev, y_seed_dev)
    return (x_seed_dev - ((5 * g >> 4) - 5), y_seed_dev - ((6 * g >> 4) - 6))


# NOTE — COUNCIL PHASE 2 frames/dither (no NEW arithmetic law — pure routing
# onto the existing box_thick family; stroke K = half_down/band_widths laws
# above apply unchanged).  The 9 CouncilWin-dest Buffer_box_sprite E8 sites
# (col painter 0x425EE9/0x4261AA/0x4261D6/0x426203/0x426230/0x42625C/0x426286,
# repaint 0x426B7B/0x426BD2) redirect to the family thunks: d5a0 (hollow band)
# -> thunk_box_thick_hollow_flat, filled sets d528 + chips da28/d9d8/da00 ->
# thunk_box_thick_devfill (STEP1 thick render builds the LAZY chip fill
# sprites before STEP2 reads them; routing is STATIC per site because
# [params+0x20] is null pre-first-draw).  The d690 backdrop @0x426B4E rides
# the lever-B stub whose tail is now devfill.  The 3 CONSOLE-dest sites
# (0x4264DD/0x4265AB/0x426B14, ecx=0x7AEC64) belong to the baked hud_frames
# machinery — never redirect them.  Rects at all 9 sites are ALREADY DEVICE
# (phase-1 seeds + imms) — the adapter must NOT rescale (the PrefWin
# boxframe adapter scales because ITS sites rebuild native rects; council
# does not).  Chip dither = orange f5-family pair: if absent from the fe
# table, STEP2's 1:1 device tile still satisfies the no-banding invariant;
# judge the stripe language at g=22/25, never 4K.  Proto v10 lever F.
#
# CHIP LAW (v11+v12, runs 10-11): the chip sets' bevel is 2-3 NATIVE px
# (pristine Vote.png pixel-measured: dark-yellow AA col + 2 yellow cols;
# fill = natively 1px HORIZONTAL yellow/orange stripes), NOT the 1-native-px
# border devfill's K/K+1 inset assumes — so devfill's STEP2 tile started
# INSIDE the scaled bevel and overwrote its inner columns (run-10, visible
# only L/R; top/bottom stripes run parallel to the bevel).  AND the chip
# border PIECES are FAT — thin bevel + interior PADDING that vanilla
# Buffer_tile_masks the fill over (Buffer_box_sprite decompile: every
# border piece draw is followed by Buffer_tile_mask(fill, piecePos, ...,
# params[9]) when params[8]!=0) — a fill-nulled frame render exposes the
# raw padding as a flat grey ring (run-11 "massive white outlines").
# Fix = THREE passes, no bevel-width formula (the bevel's inner edge lands
# under centre-aligned NN — measure-don't-model):
#   1. fill  = Buffer_box_sprite(dest, K/K+1-inset rect, borders-nulled
#      params copy) — STEP2's own 1:1 device-density mechanism;
#   2. frame = hollow_flat(dest, ORIGINAL rect, fill-nulled params copy) —
#      thick bevel + (raw padding) over the tile edge;
#   3. mask  = Buffer_tile_mask 0x5DA6C0 (fill, rectL,rectT, rectL,rectT,
#      w,h, params[9]) over the WHOLE rect — replaces padding-colored
#      pixels with the 1:1 device fill; bevel + center stripes are not the
#      mask color and survive.  Tile phase is DEST-anchored (box_sprite
#      passes pos==phase at every call) so all passes align seamlessly.
# Chips keep the 1px device-stripe language (their native art IS 1px
# stripes; no fe-table conversion).

# NOTE — Cast-a-Vote FLAG SCANLINE RESTRIPE (dither invariant port, v13):
# the UN-flag field is 1px scanline dither BUILT by council code at the
# 1024 baseline; the popup art zoom (sd2 num/16, NN) resamples it — banding
# at fractional g (run-12 @g25: irregular 1/2-row runs), invisible at 4K
# (2.5x phase-aligns).  The prior modal-class image fix, thunk_portrait_avg
# (palette-aware bilinear at the 0x5E4B4A entry), gates on dest==0x940824 —
# the faction-quote buffer ONLY — so this popup missed it; and bilinear is
# the wrong treatment for scanlines regardless: VANILLA at any res BUILDS
# the flag at device size (the builder IS the dither regenerator), so the
# faithful look is crisp 1px rows.  Fix (stubArt v17): after the draw,
# rewrite EVERY pixel of the drawn rect ((x-5,y-6), ceil(src*g/16)) through
# a row-parity pair-mate LUT (256B toBright / toDark, identity for non-pair
# indices) alternating per DEVICE row; g<=16 identity.
# PAIR SOURCE (v17) — DEST INDEX SPACE, both halves MEASURED:
#   * the canvas manager remaps every PCX palette index +10 mod 256 on load
#     (the 10 reserved Windows system-palette slots).  Proven two ways: the
#     hof_*.pcx files (in-game screen dumps) carry the runtime palette with
#     council_sm's colors shifted +10 exactly (dist 0 nearest-match), and
#     the [sd1] live dest-rect histogram matches those shifted indices
#     byte-for-byte.
#   * council_sm.pcx pair census (odd row = bright, even = dark, globally
#     phase-coherent): field 250->230 x7575 (98%), logo 245->33 x763 (100%),
#     laurel 64->36 x358 (100%)  ==>  dest pairs 0x04/0xF0, 0xFF/0x2B,
#     0x4A/0x2E.  pcx 180 (dest 0xBE) EXCLUDED: mate splits 50/50 between
#     0xF0/0x51 (dither-pair-ambiguity rule) — identity, small logo-edge
#     shading residue accepted.
#   * phase: rect row 0 = the art's doubled top-border row ([sd1] rows 0/1
#     = 0x23), first content row = rect row 2 = bright; even rect rows use
#     toBright.  Rect cols 0-1 overhang non-art row stripes 0x41/0x54 —
#     LUT-identity, untouched.
# The source bits are NOT readable from the sprite on this path: popup art
# is the FILENAME-BACKED Sprite variant — the 0x5E4B9A blit core gates on
# [sprite+0] (ppszFileName) and resolves pixels via the canvas manager
# @0x9B6080 (call 0x5D7DE0); pcBits @+0x04 stays NULL forever.  History:
# v13 read [sprite+0] = filename bytes (restriped nothing); v14 deref'd
# pcBits==NULL on the first, not-yet-loaded draw call and AV'd; v15 keyed
# the PCX's OWN palette slots 0xFA/0xE6 — correct colors, wrong index
# space, matched nothing (the designed harmless no-op).  LESSON: a
# fixed-content-index key must be measured in the DEST buffer's index
# space, never from the source art's own palette.
# Bake shape: same LUT loop as a cave thunk in the [0x3168] gv chain; the
# 512B LUT block lives in cave BSS (256-aligned so xor ebx,0x100 toggles).
# PROTOCOL DIRECTOR port (v18): the proposal popup draws the same flag via
# [0x3168] -> t_dp_artalign -> thunk_popup_artalign, whose SINGLE exit is
# the tail `push thunk_sprite_draw; ret` @0xA0F7F0 (both armed and
# passthrough branches converge there; t_dp_artalign's every path funnels
# into artalign).  Port = retarget that abs32 to a 32B gate stub
# (window==g_pd_popup && g>16 -> the SHARED stubArt armed tail; else
# thunk_sprite_draw untouched).  x/y at that seam are artalign's FINAL
# values, so the restripe rect is the drawn rect by construction — the
# positioning path is never touched.  g_pd_popup armed per-draw by the
# 0x405C80 title attach ("protocol director"); faction quote box and every
# other titled popup pass through unmodified.
# v21 SUPERSESSION (RUN 18/19/20 proved every popup-side gate wrong): the
# PROTOCOL DIRECTOR modal is NOT popup-family — it never passes 0x405C80
# and never calls thunk_sprite_draw; it draws the flag via sd2 0x5E4B4A ->
# Buffer_draw_2 from ret-chain 0x602b50 <- 0x662e0d <- 0x477f19 (measured
# by Thread.backtrace at the blit).  The WORKING fix (v21, user-verified)
# sits at the blit chokepoint itself: Buffer_draw_2 0x5D84C0 (thiscall src;
# dest,key,X,Y,num,den — dest rect = (X,Y) unscaled origin, ceil(src*num/
# den) size) with content gate bufIsFlag (src rows 1/2 col 2 hold the flag
# pair raw 250/230 or +10-remapped 4/240), then the v17 LUT restripe of
# exactly that rect.  SYMBOL CORRECTION to the v13 prose above: 0x5D7DE0 =
# Buffer_load_pcx (thiscall on the 0x9B6080 CANVAS Buffer; resizes it),
# 0x5D84C0 = Buffer_draw_2 — "the canvas manager resolves pixels" =
# load-by-name into the canvas Buffer, then a plain keyed scale blit.

# NOTE — COUNCIL PORTRAIT/LOGO PARITY-REBLIT (dither invariant, v22): the
# per-faction portraits and symbols on the vote tally are scanline-dithered
# art enlarged by OUR stubPortrait/stubLogo levers (sd2 num=g/den=16 @
# 0x425F3C/0x426105) — introduced with no regeneration tail, so they band
# at fractional g (defect by definition; portraits comb-band too, just
# harder to see on photo content).  Per-faction palettes make a fixed
# pair-mate LUT impossible.  LAW (palette-free regeneration): re-blit the
# dest rect from the SOURCE with
#   col map  sx = floor((2i+1)*den / (2*num))        (centre-aligned NN —
#            the measured engine map, never floor(i*den/num))
#   row map  p  = floor((2j+1)*den / (4*num))        (centre-NN at PAIR
#            granularity), r = 2p + (j&1)            (dest parity picks
#            bright/dark within the pair)
# Properties (simulated g=17/22/25/40): strict 1px alternation at device
# density, pair-monotone (no comb jitter), full pair coverage, <=1 native-
# pair positional error.  src==key pixels are skipped (background
# survives); g<=16 native no-op (gate num>den).  The naive parity fix —
# nudge the centre-NN row r to the nearest parity-matching neighbour — is
# the "obvious simplification" bug: it alternates correctly but steps the
# image row BACKWARD at run boundaries (pair-monotone FALSE).  Scanline
# pairs are two shadings of the same image row, so the pair-granular swap
# costs nothing on dithered art and <=1px on solid art.  WHERE (v23): the
# pcBits sd2 path blits inside Sprite_blit_scaled_core 0x5E4B9A's OWN pixel
# loop — there is NO downstream Buffer_draw_2/copy_3 call to intercept
# (v22's marker gate was consumed by an unrelated button-face StretchBlt:
# a marker that outlives its blit is a hazard, not a gate).  Proto: attach
# at the stubPortrait/stubLogo ENTRIES (onLeave = after sd2 returns), src =
# Sprite pcBits +0x4 / pitch +0xC / blit_w +0x10 / blit_h +0x14, dest rect
# = (x+dp(off_x +0x20), y+dp(off_y +0x24), ceil(blit*g/16)) — MEASURED by a
# dest-diff bbox on every draw.  Bake shape: CALL-wrapper stub (CALL sd2,
# then the re-blit loop, RET) in the stubArt pattern.

# NOTE — Cast-a-Vote EMPTY-TEXT FRAME HIDE (no arithmetic law): art popups
# with a list dialog skip the UnionRect in Popup_on_draw_background
# ([+0x2144]!=0 gate @0x4061d0), so BOTH the d528 frame (E8 @0x406154) and
# the final d5a0 frame (E8 @0x406238) box the EMPTY body-text rect — a
# vanilla quirk visible in refs\pristine\Council\BadCastVote.png.  Fix
# (user-directed divergence from vanilla, THIS popup only, all
# resolutions): skip both draws when the drawing popup is the armed
# #GOVVOTE instance (esi==g_gv_popup -> RET 8; Buffer_box_sprite is
# callee-clean).  Proto v8 lever V; bake = gate stubs ahead of
# thunk_d528_inset / thunk_content_frame keyed the same way.


# ==== council TALK popups (ornate type-6 art/text popups over CouncilWin;
#      refs\pristine\Council\WhoToVote.png + DiploBribe.png; run-24 probe
#      2026-08-22, proto v25) ====
# Both council talk popups ("for whom do you wish me to vote?" = the
# player's own faction, NO portrait; the Gaian bribe = 131x157 portrait
# 0x6846D8[f]) are ORNATE ([+0x30ac] = 60000) titled, self-parent
# ([+0xa14]==0) popups.  Two baked popup-family thunks mishandle ornate:
#
# (A) thunk_pf_textfollow (body-text X = g_d528_left + ps3) carries NO
#     popup-type gate, but g_d528_left is only refreshed by
#     thunk_pf_frame_align, which v8-gates on popup_frame_rewrite_applies
#     (FLAT/SLIDE only).  An ornate art-less popup therefore draws its body
#     text at the LAST flat popup's d528 left (run 24: X=372 = the PROTOCOL
#     DIRECTOR popup's 51+321, with the ornate popup's own 30D8=0 / 30F0=29)
#     — text ~225 native px right of its box, overrunning the right stroke.
#     LAW: textfollow applies iff frame_align applies (one gate, one
#     stash).  Ornate passes through to the engine's X = 30E0+30F0+21C8+
#     30D8, which already scales (30F0 = 47@g40 / 29@g25 / 26@g22).
#
# (B) thunk_popup_artalign x = g_band_left + 5 + (g>>4), where g_band_left
#     is stashed by thunk_band_stash @0x40603D BEFORE the title draw
#     @0x406048 — and thunk_pf_title_stash's ornate arm shifts that rect's
#     l/t/r by ornate_title_inset_delta(g) AFTER the stash.  So for ornate
#     popups the art anchored to a band stroke that then moved right by
#     the delta (run 24 @g25: bandL 15, art drawn 16, stroke measured 22-23
#     = 15 + 7).  LAW: add the same delta to the ornate art x.  y is
#     unchanged (pristine: portrait top flush with the field outer top —
#     the existing anchor law reproduces it exactly: fieldT 62 -> 57).
#
# (B-y, OPEN — measure at g=16 before writing): the ornate band's bottom
#     piece draws ~3 device px below B+delta at g25, so fieldpads' band-
#     anchored T (= B + 2*(ps3+delta)) leaves a ZERO channel under the
#     band (pristine 4K: ~4 native).  Needs the native overhang from a
#     1024 run (band rect B from the title-stash probe vs the drawn stroke
#     row) — do not fit it from the g25 shot alone.

def ornate_popup_type(raw_30ac: int) -> bool:
    """Raw [+0x30ac] band test for the ornate in-game family (types 2/6),
    exactly as thunk_pf_title_stash / union_align compare it."""
    return 20000 <= raw_30ac < 30000 or 60000 <= raw_30ac < 70000


def popup_textfollow_applies(raw_30ac: int, art_sprite: int, ext_win: int,
                             g: int) -> bool:
    """LAW A — thunk_pf_textfollow rewrites body-text X iff the stash it
    reads (g_d528_left) was refreshed for THIS popup: titled self-parent
    (ext_win == 0), no art, g > 16, AND popup_frame_rewrite_applies —
    the ornate family passes through (engine X, already scaled)."""
    return (g > NATIVE_G and art_sprite == 0 and ext_win == 0
            and popup_frame_rewrite_applies(raw_30ac))


def popup_art_x(band_left_stash: int, raw_30ac: int, g: int) -> int:
    """LAW B-x — thunk_popup_artalign x SEED (drawn = x - 5): the art frame
    flush with the title band's DRAWN outer stroke.  Flat/slide: band_left
    + 5 + (g >> 4) (the baked v5 law, user-approved Quit 4K/1600/1920).
    Ornate: the band rect moves by ornate_title_inset_delta(g) between the
    stash and its draw (so the anchor is the POST-shift g_title_left), and
    the ornate band draws through thunk_box_thick with its stroke grown
    frame_grow_delta OUTSIDE the rect — so the flush relation is
    drawn x = title_left - delta + ceil(g/16) (the stroke's width), i.e.
    + ceil(g/16) - (g>>4) - delta on top of the flat law.  @g25 that term
    is 0 (2-1-1: the user-approved run-26 look); @g40 it is -2 (3-2-3):
    build a715c815 measured the portrait 3px right of the band stroke
    (1092 vs 1087-1088) where pristine has it adjacent (1px).  Identity at
    g <= 16.  Baked as: fieldpads' ornate+art arm adds the term to
    g_title_left before artalign reads it (artalign v6 itself unchanged)."""
    if g <= NATIVE_G:
        return band_left_stash + 5
    x = band_left_stash + 5 + (g >> 4)
    if ornate_popup_type(raw_30ac):
        x += ornate_title_inset_delta(g) + popup_art_ornate_x_adjust(g)
    return x


def popup_art_ornate_x_adjust(g: int) -> int:
    """ceil(g/16) - (g>>4) - frame_grow_delta(g): the ornate family's art x
    correction (see popup_art_x).  0 @g<=16 and @g25; -2 @g40; -1 @g22."""
    if g <= NATIVE_G:
        return 0
    return ((g + 15) >> 4) - (g >> 4) - title_grow_delta(g)


def popup_art_y(field_anchor: int, raw_30ac: int, g: int) -> int:
    """thunk_popup_artalign y SEED (drawn = y - 6): art top flush with the
    text-field frame's drawn OUTER top.  Flat/slide: anchor - ps3 -
    frame_grow_delta (the baked v5 law, 4-point fit on the Quit popup).
    ORNATE: the field d528 draws FLAT through thunk_d528_inset ->
    hollow_flat at anchor - ps3 (no grow), so the art must not subtract
    delta: measured a715c815 @g40 portrait top 808 vs field top 811 (3 =
    delta), @g25 432 vs 433 (1 = delta); pristine DiploBribe has them on
    the same row (777).  Baked as: fieldpads' ornate+art arm stores
    g_field_anchor = T + delta (artalign's subtraction cancels)."""
    if g <= NATIVE_G:
        return field_anchor + 6
    y = field_anchor - popup_pad(3, g) - title_grow_delta(g) + 6
    if ornate_popup_type(raw_30ac):
        y += title_grow_delta(g)
    return y


def popup_field_top(t_src: int, title_bottom: int, raw_30ac: int,
                    key_armed: bool, g: int) -> int:
    """LAW B-y — thunk_popup_fieldpads' text-field T (the d528 rect top; the
    d5a0 union draws ps3 above it).  FLAT/SLIDE popups whose band was
    stashed THIS draw take the band-anchored arm T = B + 2*(ps3 + delta)
    (baked v3, user-approved: band-bottom / field-top channel = ps3
    exactly; B = the title rect bottom = g_title_bottom == band_stash's).
    The ORNATE family keeps the ENGINE arm T = t_src - ps3: its whole
    vertical chain is already proportionate — header reserve [30e8] = s(47),
    T = s(47) - ps3, union top T - ps3, text Y = [30e8], rows/box sized
    from it (4K probe 2026-08-23c: 117 / 110 / 103 / 117; native 47 / 44 /
    41 / 47, band bottom 37 -> channel 3 rows -> 7.5px @g40 == measured 8).
    What was wrong at 4K was the BAND (6px low, ornate_title_rect); the v7
    band-anchored-for-all arm and the v3 text-Y shift (both reverted) moved
    the frame and text inside a box that had not grown, crowding the rows
    into the OK bar.  Unkeyed (untitled / faction): t_src - ps3.  Identity
    at g <= 16."""
    if g <= NATIVE_G:
        return t_src - 3
    # 2026-09-18 (title_grow_delta == 0): the keyed flat/slide arm T = B + 2*(ps3 + delta) was a
    # compensation for the GROWN title bottom.  Vanilla (pristine QuitWithComMenu.png, native rows from
    # the frame top): title strokes 4 / 27, ring top 32, field top 35 -- i.e. the ENGINE arm x g/16
    # (t_src = s(38) -> T = s(38) - ps3 ~ s(35); title bottom -> ring channel 4 native rows).  The
    # keyed arm measured 9 / 4 / 3 px there vs 10 / 6.25 / 5.5; every family now takes the engine arm.
    return t_src - popup_pad(3, g)


def popup_field_right_src_ornate(band_pre_r: int, g: int) -> int:
    """LAW C (run 26, user: "the dialog box's right stroke should be flush
    with the title box's right stroke; the two [list-row] buttons extend too
    far right") -- the ORNATE text-field R SOURCE = ecx at thunk_popup_
    fieldpads entry (field R = ecx + ps3; union R = field R + ps3; the list
    rows end at field R - scaled 4).

    Engine (Popup_on_draw_background else-arm, decompile): flat field R =
    winR - 10 (+3 later); the ornate branch then runs `sub ecx,9` @0x40612c
    -> winR - 19 -> field d528 R = winR - 16 == the band's INNER d618 R
    (band outer winR-13, inner -3) and union d5a0 = winR - 13 == band OUTER.
    Pristine WhoToVote/DiploBribe 4K: field stroke ON the band inner stroke,
    union ON the band outer, list rows end ON the OK bar -- both sides.
    thunk_popup_fieldR scales the -10, the -9 stays native: run 26 @g25
    field R 1067 vs band inner 1061 (+6), union 1071 vs outer 1065, rows 7px
    past the OK bar (1317 vs 1310).  Scaling the 9 alone is a floor cascade
    (exact @g25, 1-2px off @g22/g40); the faithful law anchors to the DRAWN
    band -- the same relation ornate_container_edge_r carries: the band draws
    at R' = pre_r - ornate_title_inset_delta (thunk_box_thick, stroke Delta
    OUTSIDE), its inner at R' - ps3 (+Delta drawn); the field draws FLAT, so
    field R = R' - ps3 + Delta  ->  ecx = R' - 2*ps3 + Delta.
    Native identity: pre_r = winR-13 -> winR-19 exactly.  The LEFT edge
    keeps the engine's [+0x30f0]-derived L (native 19 = 13 + 6 scales as one
    term and carries the art column [+0x30d8]; @g25 it lands on the inner
    stroke already)."""
    if g <= NATIVE_G:
        return band_pre_r - 6
    r_drawn = band_pre_r - ornate_title_inset_delta(g)
    return r_drawn - 2 * popup_pad(3, g) + title_grow_delta(g)


# ==========================================================================
# SOCIAL ENGINEERING screen (SocialWin 0x8A6270) — the se_scale bake laws.
# Prototype hook_se_scale_proto.js v23, USER-VERIFIED 4K/1600/1920 2026-08-25
# (pixel-measured).  Ported by scripts\assemble_se.py (thunk_se_transform et
# al.); parity in tests\test_se_asm_parity.py; sweep in tests\test_scaling_se.py.
#
# MODAL (window-local, native constants seeded by SocialWin_build every open):
#   every rect EDGE scales scale_px (half-down) — the modal is a pure vanilla
#   x g/16 table; FlatButton rect DIMS are re-pinned to the FLOOR idiom
#   (popup_scale_floor) because thunk_btn_shrink descales with ceil(dev*16/g),
#   the exact inverse of floor only (a half-down dim descales to n+1 = a phantom
#   transparent row: the "missing bottom ring" @1600).  The 10 SOCIETY rows sit
#   on a UNIFORM pitch scale_px(22) (LAW option_row_gap shape), and the SOCIETY
#   panel bottom / SPARTANS box follow the row stack with EQUAL free channels.
# FRAME CONVENTION (measured g22 K=1 / g25 K=2): the box_thick thunks draw the
#   top stroke on rows T..T+K-1 and the bottom stroke on rows B-K+1..B — row B
#   INCLUSIVE (the drawn frame is H+1 tall).  Vanilla (g<=16, native path) is
#   half-open (B-1).  Channel arithmetic against a thunk-drawn frame counts it.
# ==========================================================================
SE_MODAL_W, SE_MODAL_H = 0x341, 0x162
SE_SOCIETY_OUTER = (0x271, 4, 0x306, 0xFA)
SE_SOCIETY_ROW_L, SE_SOCIETY_ROW_R, SE_SOCIETY_ROW_Y0 = 0x274, 0x303, 0x1D
SE_SOCIETY_ROW_W, SE_SOCIETY_ROW_H, SE_SOCIETY_PITCH = 143, 20, 22
SE_BAND_RECTS = ((0x1A, 0x04, 0x26E, 0x4A), (0x1A, 0x4D, 0x26E, 0x93),
                 (0x1A, 0x96, 0x26E, 0xDC), (0x1A, 0xDF, 0x26E, 0x125))
SE_OPTION_X, SE_OPTION_Y = (0x1D, 0xB1, 0x145, 0x1D9), (0x1D, 0x66, 0xAF, 0xF8)
SE_OPTION_W, SE_OPTION_H = 146, 20
SE_FACTION_BOX = (0x271, 0xFD, 0x306, 0x12D)
SE_BTN_OK, SE_BTN_RESET, SE_BTN_CANCEL = (0x1E4, 0x13A, 0x286, 0x14E), (0x13F, 0x13A, 0x1E1, 0x14E), (0x9A, 0x13A, 0x13C, 0x14E)
SE_BTN_W, SE_BTN_H = 162, 20
SE_BAND_TITLE_H = 23          # panel/band title band bottom = T + s(23) (painter: +3 inset, +0x14 band)
SE_PANEL_CHANNEL = 3          # vanilla free rows between the panel stroke and the SPARTANS stroke
SE_FRAME_BOTTOM_INCL = 1      # thunk-drawn bottom stroke ends ON row B (measured)
SE_FONT_SIZES = (14, 14, 14, 14, 12, 11, 11, 14, 14)   # SocialWin fonts F0..F8 (Font_init push imm8)
SE_FONT_PAD = 3               # F5/F6 line-pad dword written after init
SE_LOCK_ART_W, SE_LOCK_ART_H = 24, 14
SE_TILE_W, SE_TILE_H = 14, 14
SE_BUTTON_PAIRS = ((174, 238), (224, 225))   # (top, bottom) FlatButton face dither families: normal / selected
SE_KEY = 9


def se_rect_edges(rect: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """LAW 1 on a modal-local rect: every edge scale_px (half-down)."""
    return tuple(scale_px(v, g) for v in rect)  # type: ignore[return-value]


def se_button_rect(rect: Tuple[int, int, int, int], w: int, h: int, g: int) -> Tuple[int, int, int, int]:
    """A FlatButton rect: L/T = scaled edges, R/B = L/T + FLOOR dims (the shrink's
    exact inverse: ceil(fl(h*g/16)*16/g) == h for every g in 16..40)."""
    ll, tt = scale_px(rect[0], g), scale_px(rect[1], g)
    return (ll, tt, ll + popup_scale_floor(w, g), tt + popup_scale_floor(h, g))


def se_button_run_lefts(span_l: int, span_r: int, w: int, gap: int, n: int, g: int) -> List[int]:
    """Left edges of a horizontal run of n FlatButtons, native width w and channel gap, centred in the
    native span [span_l, span_r] (vanilla: the option row in its band frame 0x1A..0x26E = margins 3/3;
    CANCEL..OK in exactly their own span 0x9A..0x286).  Every channel is ONE width G = scale_px(gap),
    every button keeps the floor width W = fl(w*g/16) (the shrink's exact inverse, se_button_rect), and
    the run is centred in [s(span_l), s(span_r)]: the leftover floor-halved onto the left, so the two
    outer margins differ by at most 1.  Scaling each left edge alone (se_button_rect) let the channels
    differ by a pixel (g=22: 3,4,3; g=25: 4,3,3 -- user 2026-10-11, 1920x1080 shot 215846: "uneven
    channels between the social engineering buttons"); vanilla's are all equal.  g=16: vanilla."""
    if g <= NATIVE_G:
        a, ww, gg = span_l, w, gap
        d = ((span_r - span_l) - (n * w + (n - 1) * gap)) // 2
    else:
        ww, gg = popup_scale_floor(w, g), scale_px(gap, g)
        a, b = scale_px(span_l, g), scale_px(span_r, g)
        d = ((b - a) - (n * ww + (n - 1) * gg)) // 2
    return [a + d + i * (ww + gg) for i in range(n)]


def se_society_rows(g: int) -> List[Tuple[int, int, int, int]]:
    """The 10 SOCIETY row rects: uniform pitch scale_px(22) from t0 = s(0x1D),
    h = fl(20), L = s(0x274), R = L + fl(143)."""
    ll = scale_px(SE_SOCIETY_ROW_L, g)
    t0, pitch, h = scale_px(SE_SOCIETY_ROW_Y0, g), scale_px(SE_SOCIETY_PITCH, g), popup_scale_floor(SE_SOCIETY_ROW_H, g)
    w = popup_scale_floor(SE_SOCIETY_ROW_W, g)
    return [(ll, t0 + i * pitch, ll + w, t0 + i * pitch + h) for i in range(10)]


def se_society_panel(g: int) -> Tuple[int, int, int, int]:
    """SOCIETY panel outer rect.  g<=16: vanilla.  g>16: L/T/R scaled edges; the
    bottom is placed so the free channel below the last row EQUALS the free
    channel between the title band's bottom stroke and the first row:
      bandB   = T + s(23)                 (the painter's own patched arithmetic)
      topFree = t0 - bandB - INCL
      B       = lastB + topFree + (K - 1) (bottom stroke rows B-K+1..B)"""
    if g <= NATIVE_G:
        return SE_SOCIETY_OUTER
    ll, tt, rr, _ = se_rect_edges(SE_SOCIETY_OUTER, g)
    rows = se_society_rows(g)
    band_b = tt + scale_px(SE_BAND_TITLE_H, g)
    top_free = rows[0][1] - band_b - SE_FRAME_BOTTOM_INCL
    bb = rows[-1][3] + top_free + (stroke_width(g) - 1)
    return (ll, tt, rr, bb)


def se_faction_box(g: int) -> Tuple[int, int, int, int]:
    """SPARTANS box: g<=16 vanilla; g>16 top = panel B + INCL + s(3) (vanilla's 3
    free rows), height = the scaled-edge height (s(0x12D) - s(0xFD))."""
    if g <= NATIVE_G:
        return SE_FACTION_BOX
    ll, tt, rr, bb = se_rect_edges(SE_FACTION_BOX, g)
    top = se_society_panel(g)[3] + SE_FRAME_BOTTOM_INCL + scale_px(SE_PANEL_CHANNEL, g)
    return (ll, top, rr, top + (bb - tt))


SE_BACKDROP = (0x17, 0, 0x30A, 0x162)   # SocialWin_build Buffer_box_sprite d690 rect (window-local)
SE_RAIL_LEFT_STRIPS = (15, 8)             # slide_show left rail art: outer 15 + inner 8 = the backdrop L inset 0x17
SE_RAIL_RIGHT_OFF = 55                    # right rails start at W - 55 (rails 23 + 32 margin) = W - 0x37 = 0x30A


def rail_left_extent(g: int) -> int:
    """Device columns the two LEFT slide-rail strips cover (thunk_filedlg_railscale
    draws each strip through its own floor: outer fl(15g/16) then inner fl(8g/16)
    at x' = fl(15g/16)).  A backdrop that must ABUT the rails starts here -- never
    fl(23g/16) or s(23), which exceed the composed extent by 1 at some g
    (filedlg insets v2 / popup_chrome_insets precedent)."""
    if g <= NATIVE_G:
        return sum(SE_RAIL_LEFT_STRIPS)
    return sum(popup_scale_floor(v, g) for v in SE_RAIL_LEFT_STRIPS)


def se_window_w(g: int) -> int:
    """The SocialWin GraphicWin_init width imm (0x341 @0x4B32D7): CEIL(833*g/16), not
    half-down.  railscale re-anchors the right rails through fl(W_dev*16/g) - 55,
    and half_down(833*g,16) descales to 832 at most g (1145 @g22 -> 832.7), which
    drags the rails -- and the backdrop R that must abut them -- up to 3px inside
    the seed at 4K.  The ceil width is the unique W_dev whose floor-descale is
    exactly 833 for every g >= 16 ([[feedback-floor-descale-roundtrip]]), so the
    right rails start at fl(778*g/16) = the FLOOR idiom the modal's buttons use."""
    if g <= NATIVE_G:
        return SE_MODAL_W
    return (SE_MODAL_W * g + NATIVE_G - 1) // NATIVE_G


def se_backdrop_rect(g: int) -> Tuple[int, int, int, int]:
    """The builder's d690 backdrop rect after the imm table.  Vanilla relationship:
    L = rail width, R = rail start (W - 55) -- the SocialWin SLIDES (slide_show
    via SocialWin_show_hide 0x4B2120), so its side rails are the generic 15/8x529
    strips.  With the rail gate armed (se_scale v2) they scale through railscale,
    and both edges follow the rails' OWN cascades: L = rail_left_extent, R =
    fl(rail_right_anchor(W, W-55) * g/16) with W = se_window_w (== fl(778*g/16))."""
    if g <= NATIVE_G:
        return SE_BACKDROP
    w = se_window_w(g)
    right = popup_scale_floor(rail_right_anchor(w, w - SE_RAIL_RIGHT_OFF, g), g)
    return (rail_left_extent(g), 0, right, scale_px(SE_MODAL_H, g))


def se_modal_rects(g: int) -> dict:
    """The whole modal rect table after thunk_se_transform (g<=16: vanilla verbatim).
    Keys: society_outer, society_rows[10], bands[4], options[16] (band-major:
    index = band*4 + col), faction, ok, reset, cancel, backdrop (rail-abutting)."""
    if g <= NATIVE_G:
        rows = [(SE_SOCIETY_ROW_L, SE_SOCIETY_ROW_Y0 + i * SE_SOCIETY_PITCH,
                 SE_SOCIETY_ROW_R, SE_SOCIETY_ROW_Y0 + i * SE_SOCIETY_PITCH + SE_SOCIETY_ROW_H) for i in range(10)]
        opts = [(x, y, x + SE_OPTION_W, y + SE_OPTION_H) for y in SE_OPTION_Y for x in SE_OPTION_X]
        return {"society_outer": SE_SOCIETY_OUTER, "society_rows": rows, "bands": list(SE_BAND_RECTS),
                "options": opts, "faction": SE_FACTION_BOX, "ok": SE_BTN_OK, "reset": SE_BTN_RESET,
                "cancel": SE_BTN_CANCEL, "backdrop": SE_BACKDROP}
    def at(left: int, rect: Tuple[int, int, int, int], w: int, h: int) -> Tuple[int, int, int, int]:
        tt = scale_px(rect[1], g)
        return (left, tt, left + popup_scale_floor(w, g), tt + popup_scale_floor(h, g))
    olefts = se_button_run_lefts(SE_BAND_RECTS[0][0], SE_BAND_RECTS[0][2], SE_OPTION_W,
                                 SE_OPTION_X[1] - SE_OPTION_X[0] - SE_OPTION_W, 4, g)
    opts = [at(lx, (x, y, x + SE_OPTION_W, y + SE_OPTION_H), SE_OPTION_W, SE_OPTION_H)
            for y in SE_OPTION_Y for x, lx in zip(SE_OPTION_X, olefts)]
    blefts = se_button_run_lefts(SE_BTN_CANCEL[0], SE_BTN_OK[2], SE_BTN_W, SE_BTN_RESET[0] - SE_BTN_CANCEL[2], 3, g)
    return {
        "society_outer": se_society_panel(g),
        "society_rows": se_society_rows(g),
        "bands": [se_rect_edges(r, g) for r in SE_BAND_RECTS],
        "options": opts,
        "faction": se_faction_box(g),
        "ok": at(blefts[2], SE_BTN_OK, SE_BTN_W, SE_BTN_H),
        "reset": at(blefts[1], SE_BTN_RESET, SE_BTN_W, SE_BTN_H),
        "cancel": at(blefts[0], SE_BTN_CANCEL, SE_BTN_W, SE_BTN_H),
        "backdrop": se_backdrop_rect(g),
    }


# F42 (2026-10-25 wave-4 W4C, v2): the SocialWin modal's frames on their HALF-OPEN rects, and the layout that keeps every
# vanilla-mirrored / vanilla-aligned pair of the modal mirrored once they are.
#
# The twelve Buffer_box_sprite frame sites below are HALF-OPEN engine rects (vanilla: right stroke on col R-1, bottom
# on row B-1).  The band-map renderers draw a rect INCLUSIVE (bandmap_rect_from_halfopen), so every frame landed one
# device px right of and below its native extent, and the OK row's union frame went to the native primitive (a 1-px
# ring at every g).  Each site now goes through a trimming helper (assemble_halfopen_frames.SE_SITE_HELPER: R-1 and
# B-1 at g > 16, then the renderer the site called before; the union frame -> the K-wide hollow_flat).  Trimming alone
# unmasked the layout the inclusive footprint had been hiding (audit-w4C): the option rows / cells and the SOCIETY rows
# were placed by independently rounded edges, so T / B and L / R channels that vanilla mirrors came out unequal, and
# the band title bands lost the bottom row they share with the SOCIETY title band.  se_halfopen_layout re-derives the
# tables from the drawn half-open frames.
SE_HALFOPEN_FRAME_SITES = {
    0x4B3315: ("SocialWin_build.backdrop_d690", "thunk_box_thick_devfill"),
    0x4AF226: ("SocialWin_draw_society_panel.d5a0", "thunk_box_thick_hollow_flat"),
    0x4AF26F: ("SocialWin_draw_society_panel.d618", "thunk_box_thick_devfill"),
    0x4AF35F: ("SocialWin_draw_band.d5a0", "thunk_box_thick_hollow_flat"),
    0x4AF3A8: ("SocialWin_draw_band.d618_title", "thunk_box_thick_devfill"),
    0x4AF47E: ("SocialWin_draw_band.d618_lock_a", "thunk_box_thick_devfill"),
    0x4AF4A7: ("SocialWin_draw_band.d618_lock_b", "thunk_box_thick_devfill"),
    0x4AF4E9: ("SocialWin_draw_band.d618_lock_c", "thunk_box_thick_devfill"),
    0x4AF904: ("SocialWin_draw_faction_box.d5a0", "thunk_box_thick_hollow_flat"),
    0x4AF94A: ("SocialWin_draw_faction_box.d618", "thunk_box_thick_devfill"),
    0x4AFA13: ("SocialWin_draw_faction_box.d618_b", "thunk_box_thick_devfill"),
    0x4B1A8F: ("SocialWin_repaint.union_frame", "thunk_box_thick_hollow_flat"),   # was the native Buffer_box_sprite
}
SE_UNION_FRAME_SITE = 0x4B1A8F
SE_SPARTANS_GAP = 2            # vanilla rows between the SPARTANS box's two bands (f1 [256, 276), f2 [278, 298))


def se_frame_draw_rect(site: int, l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (2026-10-25 wave-4 W4C, F42) -- the rect SE_HALFOPEN_FRAME_SITES hand their band-map renderer: R-1 and B-1 at
    g > 16 (bandmap_rect_from_halfopen), so the inclusive footprint is exactly vanilla's half-open extent at device
    scale.  The backdrop's B is the canvas height: thunk_box_thick_devfill clamps a rect's B to the last canvas row IN
    PLACE before it draws, so a trimmed and an untrimmed backdrop B draw the same bottom rows (measured; the caller's
    local is left clamped either way).  g <= 16: the native half-open render, unchanged."""
    if site not in SE_HALFOPEN_FRAME_SITES:
        raise KeyError(hex(site))
    return bandmap_rect_from_halfopen(l, t, r, b, g)


def se_frame_footprint(rect: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """The DRAWN columns / rows (inclusive) of an SE_HALFOPEN_FRAME_SITES frame: [L, R-1] x [T, B-1] at every g."""
    return (rect[0], rect[1], rect[2] - 1, rect[3] - 1)


def _se_err16(x16: int, v: int, g: int) -> int:
    """|x - v*g/16| * 16 for x16 = 16*x (integer arithmetic, the asm port's own)."""
    return abs(x16 - v * g)


# W5C (2026-10-25 wave-5, F42 v3): ONE grammar for every SE frame's interior, vanilla's own additive construction
# (inset 3 = stroke 1 + channel 2, title band 20, rows / cells 20 on a 22 pitch, so every title -> row, row -> cell,
# cell -> stroke and row -> row channel is the same 2 and every inset the same 3).  W4C v2 scaled the parts per
# rounding: the title band s(23) - s(3) tall but its cells fl(20), the cells s(22) below the row, the title insets
# s(3) -- three roundings of related natives -- so the band's title-top inset vs cell-bottom inset and the option row's
# centring in its band could not both hold (audit-w4C v2 residuals (a) 32 band x g cases, (b) 5).  Now:
#   h  = fl(20)  the ONE rounding of every 20: the option / SOCIETY rows and the cells (FlatButtons: the shrink's exact
#                inverse, se_button_rect) AND every title band (band, SOCIETY, SPARTANS f1) and SPARTANS f2;
#   c  = the ONE channel (vanilla 2): title -> row, row -> cell seam, cell -> stroke, row -> row;
#   ti = c + K   the ONE inset (vanilla 3 = K + 2): the band / SOCIETY title band's T, L and R, the SPARTANS bands' L / R,
#                and so every frame's bottom inset (cells / last row -> frame B);
#   o  = h + c   the row -> cell offset AND the SOCIETY row pitch (vanilla 22 = 20 + 2);
#   Hb = ti + h + c + h + c + h + c + K = 3h + 4c + 2K  (vanilla 70).
# Then, by construction at every g: title -> row == cell -> stroke == c; title top inset == cell-row bottom inset == ti
# (relation a); the option row centred in its band (relation b: ti + h + c == c + h + c + K); the SOCIETY title top inset
# == its last-row bottom inset and its row 4 centred (vanilla 113 | 113); the cells on the SOCIETY rows' line.
# The painter immediates that carry ti / h / o (SE_LAYOUT_IMMS) are t_se_layout's alone (removed from thunk_se_immfix's
# table), so each has one owner.
SE_T0, SE_INSET, SE_CHANNEL, SE_ROW_H, SE_ROW_OFF = 4, 3, 2, 20, 22
SE_BAND_H, SE_BAND_PITCH, SE_BAND3_UNION = 70, 73, 18         # band height / pitch, band 3 -> OK-union free rows
SE_SOC_H = SE_SOCIETY_OUTER[3] - SE_SOCIETY_OUTER[1]           # 246, the SOCIETY panel's height
SE_SPARTANS_H = SE_FACTION_BOX[3] - SE_FACTION_BOX[1]          # 48, the SPARTANS box's height
SE_SOC_SPARTANS, SE_SPARTANS_UNION, SE_SPARTANS_BAND3 = 3, 10, 8   # SOCIETY -> SPARTANS / SPARTANS -> union rows;
#                                                                  SPARTANS B - band 3 B (the audit L-D distance)
#: the painter immediates t_se_layout owns: imm VA -> (bytes, role, native).  role ti (title-band top inset) / tlr (the
#: title bands' and SPARTANS bands' L / R inset: W5C's ti, also under the hybrid) / h / o / fi, -h = the f2 band's
#: `add eax, -imm` from the SPARTANS inner B.  0x4AF379 / 0x4AF240 (the band / SOCIETY inner rect B, never read before a
#: rewrite) stay thunk_se_immfix's s(3).
SE_LAYOUT_IMMS = {
    0x4AF36F: (1, "tlr", 3),    # SocialWin_draw_band: title R  (sub eax, imm8 @0x4AF36D)
    0x4AF378: (1, "tlr", 3),    #   title L  (add ecx, imm8 @0x4AF376)
    0x4AF381: (1, "ti", 3),    #   title T  (add eax, imm8 @0x4AF37F)
    0x4AF39C: (1, "h", 20),    #   title height (add eax, imm8 @0x4AF39A; was s(23) - s(3))
    0x4AF48A: (4, "o", 22),    #   lock_b = lock_a + o (mov eax, imm32 @0x4AF489)
    0x4AF4CC: (1, "o", 22),    #   lock_c T = option T + o (add eax, imm8 @0x4AF4CA)
    0x4AF4DF: (1, "o", 22),    #   lock_c B = option B + o (add ecx, imm8 @0x4AF4DD)
    0x4AF236: (1, "tlr", 3),    # SocialWin_draw_society_panel: title R (sub eax, imm8 @0x4AF234)
    0x4AF23F: (1, "tlr", 3),    #   title L (add ecx, imm8 @0x4AF23D)
    0x4AF248: (1, "ti", 3),    #   title T (add eax, imm8 @0x4AF246)
    0x4AF263: (1, "h", 20),    #   title height (add eax, imm8 @0x4AF261; was s(23) - s(3))
    0x4AF917: (1, "tlr", 3),    # SocialWin_draw_faction_box: bands R (sub edx, imm8 @0x4AF915)
    0x4AF91A: (1, "fi", 3),    #   f1 T (add eax, imm8 @0x4AF918)
    0x4AF91D: (1, "tlr", 3),    #   bands L (add ecx, imm8 @0x4AF91B)
    0x4AF929: (1, "fi", 3),    #   f2 B (sub edi, imm8 @0x4AF927)
    0x4AF938: (1, "h", 20),    #   f1 height (add eax, imm8 @0x4AF936; was s(23) - s(3))
    0x4AFA09: (1, "-h", -20),  #   f2 T = inner B - h (add eax, imm8 @0x4AFA07; was -s(20))
}


def _se_tie(parts: Tuple[Tuple[int, int], ...]) -> int:
    """The deterministic tie-break of the SE searches: the L1 distance from the scaled values first, then the deltas
    lexicographically (each (delta, bits) field holds delta + its offset).  The asm builds the same integer."""
    l1, low, shift = sum(abs(d) for d, _b in parts), 0, 0
    for d, b in reversed(parts):
        low |= (d + (1 << (b - 1))) << shift
        shift += b
    return (l1 << shift) | low


def se_halfopen_choices(g: int) -> Tuple[int, ...]:
    """LAW (W4C v2, W5C v3) -- the free integers of se_halfopen_layout, each a small delta from its scaled value:
    -> (bR - s(622), pL - s(625), pR - s(774), T0 - s(4), c - s(2), P - s(73), gs - s(3), fi - s(3), gf - s(2)).
    g <= 16: zeros (the native tables).  Every error is in x16 integer units; every key is (worst, sum, tie).
      A. T0 (band 0 / SOCIETY top), c (the one channel; ti = c + K, o = h + c, Hb = 3h + 4c + 2K), P (band pitch):
         T0 in s(4)+{-1..1}, c in s(2)+{-1..1}, P in s(73)+{-2..2}; errors vs vanilla x g/16 of T0 (4), ti (3), c (2),
         o (22), Hb (70), the band gap P - Hb (3), band 3 -> the OK union (18; union T = OK T - s(3)) and the SOCIETY
         panel's height 2ti + 2h + c + 9o (246: o is its row pitch too, so its 9-pitch drift is c's to spread).
         The three band relations hold by construction, so this only spreads the rounding: brute force over every
         integer layout that keeps them (tests/test_scaling_se_halfopen.py) finds no smaller worst error.
      B. bR (the four bands' R): the 4-button option run (fl(146) each, s(2) seams) centred in [L+K, R-K) -- even
         leftover -- with its channel closest to c (the run under its title band, inset ti = K + c, as vanilla's
         29..618 = title 29..618), then the smaller |d|, then the smaller R; R in s(622)+{-1..1};
      C. pL, pR (the SOCIETY panel and the SPARTANS box): the 143-px rows centred in [pL+K, pR-K) (even leftover);
         pL in bR + s(3) + {-1..1}, pR in s(774)+{-2..2}: the worst of |band R -> panel L gap - 3g/16|,
         2 |rows channel - c| and |panel -> backdrop stroke - 3g/16|, then the sum, then |dl| + |dr|, pL, pR.  A rows
         channel off c breaks two vanilla alignments (the rows under the SOCIETY title band and under the SPARTANS
         bands, both inset ti = K + c), so a 1-px miss costs 2 (user rule: symmetry over 1-px exactness): the panel
         takes up to 1.25 px of gap error to keep them aligned, never the 2.5 px exact alignment costs at g 24 / 40;
      D. gs (SOCIETY -> SPARTANS rows), fi (the SPARTANS bands' T / B inset), gf (between its bands): gs in s(3)+{-2..2},
         fi in s(3)+{-1..1}, gf in s(2)+{-1..1}; errors of gs (3), fi (3), gf (2), SPARTANS -> union (10), SPARTANS B -
         band 3 B (8) and the SPARTANS box's height 2fi + 2h + gf (48) -- the right column absorbs what the SOCIETY
         panel's 9-pitch drift leaves (o is the cells' offset too).
    Port: t_se_layout (assemble_halfopen_frames.py), the same searches in the same order and integer units."""
    if g <= NATIVE_G:
        return (0,) * 9
    k = stroke_width(g)
    h, w146, w143 = popup_scale_floor(SE_ROW_H, g), popup_scale_floor(146, g), popup_scale_floor(143, g)
    s2, s3, s4, s73 = scale_px(2, g), scale_px(3, g), scale_px(SE_T0, g), scale_px(SE_BAND_PITCH, g)
    union_t = scale_px(SE_BTN_OK[1], g) - s3
    best = None
    for dt in (-1, 0, 1):
        t0 = s4 + dt
        for dc in (-1, 0, 1):
            c = s2 + dc
            ti, o, hb = c + k, h + c, 3 * h + 4 * c + 2 * k
            for dp in (-2, -1, 0, 1, 2):
                p = s73 + dp
                e = (_se_err16(16 * t0, SE_T0, g), _se_err16(16 * ti, SE_INSET, g), _se_err16(16 * c, SE_CHANNEL, g),
                     _se_err16(16 * o, SE_ROW_OFF, g), _se_err16(16 * hb, SE_BAND_H, g),
                     _se_err16(16 * (p - hb), SE_BAND_PITCH - SE_BAND_H, g),
                     _se_err16(16 * (union_t - (t0 + 3 * p + hb)), SE_BAND3_UNION, g),
                     _se_err16(16 * (2 * ti + 2 * h + c + 9 * o), SE_SOC_H, g))
                key = (max(e), sum(e), _se_tie(((dt, 2), (dc, 2), (dp, 3))))
                if best is None or key < best[0]:
                    best = (key, dt, dc, dp)
    _k, d_t0, d_c, d_p = best
    t0, c, p = s4 + d_t0, s2 + d_c, s73 + d_p
    ti, o, hb = c + k, h + c, 3 * h + 4 * c + 2 * k
    b_l, run = scale_px(0x1A, g), 4 * w146 + 3 * s2
    best = None
    for d in (-1, 0, 1):
        r = scale_px(0x26E, g) + d
        lo = (r - k) - (b_l + k) - run
        if lo % 2:
            continue
        key = (abs(lo // 2 - c), abs(d), r)
        if best is None or key < best[0]:
            best = (key, r)
    b_r = best[1]
    rail_r = se_backdrop_rect(g)[2]
    best = None
    for dl in (-1, 0, 1):
        p_l = b_r + s3 + dl
        for dr in (-2, -1, 0, 1, 2):
            p_r = scale_px(SE_SOCIETY_OUTER[2], g) + dr
            lo = (p_r - k) - (p_l + k) - w143
            if lo % 2:
                continue
            e = (_se_err16(16 * (p_l - b_r), 3, g), 32 * abs(lo // 2 - c),
                 _se_err16(16 * ((rail_r - k) - p_r), 3, g))
            key = (max(e), sum(e), abs(dl) + abs(dr), p_l, p_r)
            if best is None or key < best[0]:
                best = (key, p_l, p_r)
    p_l, p_r = best[1], best[2]
    b3_b = t0 + 3 * p + hb
    soc_b = t0 + ti + h + c + 9 * o + h + ti
    best = None
    for dg in (-2, -1, 0, 1, 2):
        gs = s3 + dg
        for dfi in (-1, 0, 1):
            fi = s3 + dfi
            for dgf in (-1, 0, 1):
                gf = s2 + dgf
                f_b = soc_b + gs + 2 * fi + 2 * h + gf
                e = (_se_err16(16 * gs, SE_SOC_SPARTANS, g), _se_err16(16 * fi, SE_INSET, g),
                     _se_err16(16 * gf, SE_SPARTANS_GAP, g), _se_err16(16 * (union_t - f_b), SE_SPARTANS_UNION, g),
                     _se_err16(16 * (f_b - b3_b), SE_SPARTANS_BAND3, g),
                     _se_err16(16 * (2 * fi + 2 * h + gf), SE_SPARTANS_H, g))
                key = (max(e), sum(e), _se_tie(((dg, 3), (dfi, 2), (dgf, 2))))
                if best is None or key < best[0]:
                    best = (key, dg, dfi, dgf)
    _k, d_gs, d_fi, d_gf = best
    return (b_r - scale_px(0x26E, g), p_l - scale_px(SE_SOCIETY_OUTER[0], g), p_r - scale_px(SE_SOCIETY_OUTER[2], g),
            d_t0, d_c, d_p, d_gs, d_fi, d_gf)


def _se_band_err16(g: int, t0: int, ti: int, c1: int, c2: int, c3: int, os_: int, p: int):
    """The twelve band-column terms of the hybrid metric in x16 units (vanilla x g/16 targets): T0 (4), the title inset
    ti (3), the title band h (20), the channels c1 title -> row / c2 row -> cell / c3 cell -> stroke (2 each), the cell
    offset h + c2 (22), the SOCIETY row pitch os (22), the band height Hb (70), the band gap P - Hb (3), band 3 -> the OK
    union (18) and the SOCIETY height ti + h + c1 + 9 os + h + c3 + K (246).  -> (max, sum, Hb, SOCIETY B, band 3 B)."""
    k, h = stroke_width(g), popup_scale_floor(SE_ROW_H, g)
    union_t = scale_px(SE_BTN_OK[1], g) - scale_px(3, g)
    hb = ti + h + c1 + h + c2 + h + c3 + k
    soc_h = ti + h + c1 + 9 * os_ + h + c3 + k
    b3b = t0 + 3 * p + hb
    e = [_se_err16(16 * x, v, g) for x, v in (
        (t0, SE_T0), (ti, SE_INSET), (h, SE_ROW_H), (c1, SE_CHANNEL), (c2, SE_CHANNEL), (c3, SE_CHANNEL),
        (h + c2, SE_ROW_OFF), (os_, SE_ROW_OFF), (hb, SE_BAND_H), (p - hb, SE_BAND_PITCH - SE_BAND_H),
        (union_t - b3b, SE_BAND3_UNION), (soc_h, SE_SOC_H))]
    return max(e), sum(e), hb, t0 + soc_h, b3b


def _se_right_err16(g: int, soc_b: int, b3b: int, gs: int, fi: int, gf: int):
    """The six right-column terms (x16): SOCIETY -> SPARTANS gs (3), the SPARTANS insets fi (3), its band gap gf (2), its
    height 2fi + 2h + gf (48), SPARTANS -> the OK union (10), SPARTANS B - band 3 B (8).  -> (max, sum)."""
    h = popup_scale_floor(SE_ROW_H, g)
    union_t = scale_px(SE_BTN_OK[1], g) - scale_px(3, g)
    fac_h = 2 * fi + 2 * h + gf
    f_b = soc_b + gs + fac_h
    e = [_se_err16(16 * x, v, g) for x, v in (
        (gs, SE_SOC_SPARTANS), (fi, SE_INSET), (gf, SE_SPARTANS_GAP), (fac_h, SE_SPARTANS_H),
        (union_t - f_b, SE_SPARTANS_UNION), (f_b - b3b, SE_SPARTANS_BAND3))]
    return max(e), sum(e)


def _se_right_best(g: int, soc_b: int, b3b: int):
    """The right column for a band column: gs in s(3)-2..s(3)+3, fi in s(3)+-1, gf in s(2)+-1; min (max, sum, gs, fi,
    gf).  -> (max, sum, gs, fi, gf)."""
    s2, s3 = scale_px(2, g), scale_px(3, g)
    best = None
    for gs in range(s3 - 2, s3 + 4):
        for fi in range(s3 - 1, s3 + 2):
            for gf in range(s2 - 1, s2 + 2):
                mx, sm = _se_right_err16(g, soc_b, b3b, gs, fi, gf)
                if best is None or (mx, sm, gs, fi, gf) < best:
                    best = (mx, sm, gs, fi, gf)
    return best


#: the hybrid's worst-error limit (x16 units = 2.5 px): above it the relation-exact layout gives way (user, 2026-10-25,
#: the se_options comparison: "Hybrid")
SE_HYBRID_LIMIT16 = 40
SE_HYBRID_KINDS = ("adj", "a", "b", "os")


def se_halfopen_hybrid(g: int):
    """LAW (2026-10-25 wave-6 W6H, the user's choice "Hybrid") -- where the relation-exact W5C layout's worst error vs
    vanilla x g/16 (the 18 terms of _se_band_err16 + _se_right_err16 on W5C's integers) exceeds 2.5 px, break exactly ONE
    vertical relation by exactly 1 px, the title band staying one rounding (h = fl(20)):
      adj  title -> row channel c1 != cell -> stroke channel c3   (c1 = c3 +- 1, c2 = c1, ti = c3 + K);
      a    title-top inset ti != cell-row bottom inset c3 + K      (ti = c + K +- 1, c2 = c +- 1);
      b    option row off-centre by 1                             (c2 = c +- 1, ti = c + K);
      os   SOCIETY row pitch != the cell offset h + c2 (row 1 off the cells' line by 1; os = h + c +- 1).
    Every other relation stays exact (c1 == c3 == c except where named; o = h + c2; SOCIETY bottom inset c3 + K).
    Ranges: T0 s(4)+-1, ti s(3)-1..+2, c1 / c2 / c3 s(2)-1..+2, os s(22)+-1, P s(73)-3..+3; the right column per
    candidate by _se_right_best.  Key: min (worst, sum, T0, ti, c1, c2, c3, os, P) over the 18 terms.
    -> None (W5C kept) or dict(T0, ti, c1, c2, c3, os, P, gs, fi, gf, kind, sign, worst16).
    This reproduces the se_options\\layouts.py prototype the user approved (its product search filtered to one relation
    broken by 1: the first minimum in product order is the lexicographic minimum of the same parameter tuple)."""
    if g <= NATIVE_G:
        return None
    k, h = stroke_width(g), popup_scale_floor(SE_ROW_H, g)
    q = se_halfopen_parts_w5c(g)
    bmx, bsm, _hb, soc_b, b3b = _se_band_err16(g, q["T0"], q["ti"], q["c"], q["c"], q["c"], q["o"], q["P"])
    rmx, _rsm = _se_right_err16(g, soc_b, b3b, q["gs"], q["fi"], q["gf"])
    if max(bmx, rmx) <= SE_HYBRID_LIMIT16:
        return None
    s2, s3, s4, s22, s73 = (scale_px(v, g) for v in (2, 3, SE_T0, SE_ROW_OFF, SE_BAND_PITCH))
    best = None
    for dt in (-1, 0, 1):
        t0 = s4 + dt
        for c in range(s2 - 1, s2 + 3):
            for kind in SE_HYBRID_KINDS:
                for sign in (-1, 1):
                    c1, c2, c3, ti, os_ = c, c + sign, c, c + k, h + c + sign
                    if kind == "adj":
                        c1 = c + sign
                    elif kind == "a":
                        ti = c + k + sign
                    elif kind == "os":
                        c2 = c
                    if not (s3 - 1 <= ti <= s3 + 2 and all(s2 - 1 <= x <= s2 + 2 for x in (c1, c2, c3))
                            and s22 - 1 <= os_ <= s22 + 1):
                        continue
                    for p in range(s73 - 3, s73 + 4):
                        bmx, bsm, _hb, soc_b, b3b = _se_band_err16(g, t0, ti, c1, c2, c3, os_, p)
                        if best is not None and (bmx > best[0][0] or (bmx == best[0][0] and bsm > best[0][1])):
                            continue          # the right column only adds to both: cannot beat the best
                        rmx, rsm, gs, fi, gf = _se_right_best(g, soc_b, b3b)
                        key = (max(bmx, rmx), bsm + rsm, t0, ti, c1, c2, c3, os_, p)
                        if best is None or key < best[0]:
                            best = (key, dict(T0=t0, ti=ti, c1=c1, c2=c2, c3=c3, os=os_, P=p, gs=gs, fi=fi, gf=gf,
                                              kind=kind, sign=sign, worst16=key[0]))
    return best[1]


def se_halfopen_worst16(g: int) -> int:
    """The worst of the 18 terms (x16) for the layout the build draws at g (hybrid or W5C)."""
    q = se_halfopen_parts(g)
    if g <= NATIVE_G:
        return 0
    bmx, _s, _hb, soc_b, b3b = _se_band_err16(g, q["T0"], q["ti"], q["c1"], q["c2"], q["c3"], q["os"], q["P"])
    return max(bmx, _se_right_err16(g, soc_b, b3b, q["gs"], q["fi"], q["gf"])[0])


def se_halfopen_parts_w5c(g: int) -> dict:
    """The W5C (relation-exact) construction's integers at g (g <= 16: vanilla's): T0, K, h, c, ti, o, Hb, P, bL, bR,
    pL, pR, gs, fi, gf."""
    if g <= NATIVE_G:
        return dict(T0=4, K=1, h=20, c=2, ti=3, o=22, Hb=70, P=73, bL=0x1A, bR=0x26E, pL=SE_SOCIETY_OUTER[0],
                    pR=SE_SOCIETY_OUTER[2], gs=3, fi=3, gf=2)
    d_br, d_pl, d_pr, d_t0, d_c, d_p, d_gs, d_fi, d_gf = se_halfopen_choices(g)
    k, h = stroke_width(g), popup_scale_floor(SE_ROW_H, g)
    c = scale_px(SE_CHANNEL, g) + d_c
    return dict(T0=scale_px(SE_T0, g) + d_t0, K=k, h=h, c=c, ti=c + k, o=h + c, Hb=3 * h + 4 * c + 2 * k,
                P=scale_px(SE_BAND_PITCH, g) + d_p, bL=scale_px(0x1A, g), bR=scale_px(0x26E, g) + d_br,
                pL=scale_px(SE_SOCIETY_OUTER[0], g) + d_pl, pR=scale_px(SE_SOCIETY_OUTER[2], g) + d_pr,
                gs=scale_px(SE_SOC_SPARTANS, g) + d_gs, fi=scale_px(SE_INSET, g) + d_fi,
                gf=scale_px(SE_SPARTANS_GAP, g) + d_gf)


def se_halfopen_parts(g: int) -> dict:
    """The integers the build draws at g: W5C's (se_halfopen_parts_w5c) with c1 = c2 = c3 = c, os = o, tlr = ti -- or,
    where se_halfopen_hybrid fires, its T0 / ti / c1 / c2 / c3 / os / P / gs / fi / gf (o = h + c2, Hb = ti + h + c1 + h
    + c2 + h + c3 + K).  Horizontal geometry (bL, bR, pL, pR, c = the option-run / row channel target) and the title
    bands' L / R inset tlr stay W5C's in both (the approved prototype).  kind = the broken relation or None."""
    q = dict(se_halfopen_parts_w5c(g))
    q.update(c1=q["c"], c2=q["c"], c3=q["c"], os=q["o"], tlr=q["ti"], kind=None)
    hy = se_halfopen_hybrid(g)
    if hy is not None:
        k, h = q["K"], q["h"]
        q.update({n: hy[n] for n in ("T0", "ti", "c1", "c2", "c3", "os", "P", "gs", "fi", "gf", "kind")})
        q.update(o=h + hy["c2"], Hb=hy["ti"] + h + hy["c1"] + h + hy["c2"] + h + hy["c3"] + k)
    return q


def se_halfopen_imms(g: int) -> dict:
    """LAW (W5C, W6H) -- the value t_se_layout stores at each SE_LAYOUT_IMMS immediate (g <= 16: the native bytes)."""
    q = se_halfopen_parts(g)
    val = {"ti": q["ti"], "tlr": q["tlr"], "h": q["h"], "o": q["o"], "fi": q["fi"], "-h": -q["h"]}
    return {va: val[role] for va, (_w, role, _n) in SE_LAYOUT_IMMS.items()}


def se_halfopen_layout(g: int) -> dict:
    """LAW (W4C v2, W5C v3, W6H) -- the SocialWin tables t_se_layout writes after the transform (thunk_se_btnrun's
    tail, before SocialWin_model_reset and before any FlatButton is built from them), the frames drawn half-open, from
    se_halfopen_parts (T0, K, h, ti, c1, c2, c3, os, o = h + c2, Hb, P, bL, bR, pL, pR, gs, fi, gf):
      bands[i]     = (bL, T0 + i*P, bR, T0 + i*P + Hb);
      options      = 4 per band, fl(146) wide, s(2) seams, centred in [bL+K, bR-K); y = T + ti + h + c1, h tall -- the
                     title band [T+ti, T+ti+h) c1 above, the cells (+o) below, c3 + K above the band's B;
      society_outer= (pL, T0, pR, B): rows (fl(143) x h, pitch os) centred in [pL+K, pR-K) from T0 + ti + h + c1 (the
                     option rows' line), B = last row B + c3 + K;
      faction      = (pL, F, pR, F + fi + h + gf + h + fi), F = B + gs -- the SPARTANS box from its parts.
    W5C: c1 = c2 = c3, os = o (every relation exact); the hybrid breaks one (se_halfopen_hybrid).
    The painter immediates (se_halfopen_imms) draw the title bands / cells / SPARTANS bands on the same integers.
    The backdrop and the OK row are the transform's (se_modal_rects).  g <= 16: se_modal_rects(16) verbatim."""
    m = dict(se_modal_rects(g))
    if g <= NATIVE_G:
        return m
    q = se_halfopen_parts(g)
    k, h, ti, c1, c3, os_, hb, p, t0 = (q[n] for n in ("K", "h", "ti", "c1", "c3", "os", "Hb", "P", "T0"))
    w146, w143, s2 = popup_scale_floor(146, g), popup_scale_floor(143, g), scale_px(2, g)
    b_l, b_r = q["bL"], q["bR"]
    x0 = b_l + k + ((b_r - k) - (b_l + k) - (4 * w146 + 3 * s2)) // 2
    bands, opts = [], []
    for i in range(4):
        t = t0 + i * p
        bands.append((b_l, t, b_r, t + hb))
        y = t + ti + h + c1
        opts += [(x0 + j * (w146 + s2), y, x0 + j * (w146 + s2) + w146, y + h) for j in range(4)]
    p_l, p_r = q["pL"], q["pR"]
    rl = p_l + k + ((p_r - k) - (p_l + k) - w143) // 2
    r0 = t0 + ti + h + c1
    rows = [(rl, r0 + i * os_, rl + w143, r0 + i * os_ + h) for i in range(10)]
    p_b = rows[-1][3] + c3 + k
    f_t = p_b + q["gs"]
    m.update(bands=bands, options=opts, society_outer=(p_l, t0, p_r, p_b), society_rows=rows,
             faction=(p_l, f_t, p_r, f_t + 2 * q["fi"] + 2 * h + q["gf"]))
    return m


def se_console_rects(regions: List[int], g: int) -> dict:
    """The console-overlay tables from the 16 MainWin region dwords 0x7AF5A0..DC
    (already HUD-scaled: r0 = left console, r1 = right, r2 = centre, rs = slider
    strip).  Native additive constants scale scale_px (NetWin additive-constant
    law); g<=16 reproduces SocialWin_build verbatim.  LABS absorbs the column
    remainder (builder law); arrow table order 0,1=ECON 2,3=LABS 4,5=PSYCH;
    lock table order ECON, PSYCH, LABS; lock_phase_y = the shared lock top."""
    def s(v: int) -> int:
        return scale_px(v, g)
    r0, r1, r2, rs = regions[0:4], regions[4:8], regions[8:12], regions[12:16]
    fx = (r1[0] + s(4), r1[1] + s(4), r1[2] - s(4), r1[3] - s(4))
    center = (r2[0] + s(4), r2[1] + s(4), r2[2] - s(4), r2[3] - s(4))
    L, T, R, B = r0[0] + s(7), rs[1] + s(7), rs[2] - s(7), rs[3] - s(7)
    col_w = (R - L - s(4)) // 3 - s(3)
    econ = (L, T, L + col_w, B)
    psych = (L + col_w + s(3), T, L + 2 * col_w + s(3), B)
    labs = (psych[2] + s(3), T, R, B)
    hover = (r0[0] + s(4), r0[1] + s(4), r0[2] - s(4), T - s(6))
    arrows = []
    for i, q in enumerate((econ, econ, labs, labs, psych, psych)):
        arrows.append((q[0] + s(3), q[1] + s(3), q[0] + s(0x17), q[1] + s(0x17)) if i % 2 == 0
                      else (q[2] - s(0x17), q[1] + s(3), q[2] - s(3), q[1] + s(0x17)))
    locks = [(q[0] + s(3), q[3] - s(0x11), q[0] + s(0x1B), q[3] - s(3)) for q in (econ, psych, labs)]
    return {"fx_box": fx, "center_box": center, "slider_econ": econ, "slider_psych": psych,
            "slider_labs": labs, "hover_box": hover, "arrows": arrows, "locks": locks,
            "lock_phase_y": econ[3] - s(0x11)}


def se_imm(a: int, b: int, g: int) -> int:
    """A painter/builder immediate that is a composed vanilla constant: s(a) - s(b)
    (b covers total-on-base sites and pure negatives a=0).  Identity at g=16."""
    return scale_px(a, g) - scale_px(b, g)


def se_font_size(native: int, g: int) -> int:
    """Font_init size imm8 for the 9 SocialWin fonts: fl(native*g/16) (v2 2026-09-17).
    v1 used s() = half-down, which rounds 14*25/16 = 21.875 UP to 22 at 1600x1200 while the
    model buttons' widths (s(a)-s(b) of a 154-native interior) grow x1.5625: the label font
    grew x1.571 > the button, and the longest label ("THOUGHT CONTROL", 228 px in Arial bold 22
    vs a 241 px interior minus 2 x s(5) pads) was ellipsised.  Floor keeps every font at or
    below the geometry's growth (the rw_font_nominal / mon_font_size / basewin_font_size rule);
    identity at g<=16."""
    return popup_scale_floor(native, g)


def se_sprite_canvas(cw: int, ch: int, g: int) -> Tuple[int, int]:
    """sd2-fed sprites (band digits, effect icons): data/pitch/blit stay NATIVE
    (the (g,16) sd2 ratio enlarges), only canvas w/h scale — canvas dims are the
    layout aliases (icon_gap / row_h / ...) and the y-anchor subtracts canvas h."""
    return (scale_px(cw, g), scale_px(ch, g))


def se_lock_plane_dims(g: int) -> Tuple[int, int]:
    """The raw-blitted lock sprites: plane = s(24) x s(14), pitch = s(24)."""
    return (scale_px(SE_LOCK_ART_W, g), scale_px(SE_LOCK_ART_H, g))


def se_tile_height(g: int) -> int:
    """Slider bar tiles: W x 2P stripes (Buffer_tile's absolute anchoring keeps
    the dest-row phase; 2P is a multiple of P so tile row y mod 2P == stripe_top(y))."""
    return 2 * stripe_period(g)


def se_centre_map(dst: int, src: int) -> List[int]:
    """Centre-aligned NN column/row map (the engine's own stretch phase)."""
    return [min(src - 1, ((2 * j + 1) * src) // (2 * dst)) for j in range(dst)]


# ---------------------------------------------------------------------------
# SELECT RESEARCH GOAL — tech_pick 0x5BEB70 / TechWin (2026-08-27)
#
# The window is a stack-local GraphicWin built by TechWin_exec 0x486510.  Vanilla
# SCREEN-FITS it (cw = SW/cols - 20 ...) and keeps every interior constant native,
# so at 4K the frame fills the screen while fonts/icons/insets stay 1x (the shot
# the user reported).  Law decision (user, 2026-08-27, "option a"): keep vanilla's
# screen-fit law and evaluate it AT DEVICE DENSITY = the same arithmetic with each
# native constant scaled (SW/cols - s(20) ...).  This equals "run vanilla on the
# virtual (SW*16/g, SH*16/g) screen, then x g/16" to within the rounding of the
# constants, and — unlike a fixed 949x720 x g/16 window — never produces a
# smaller picker than vanilla draws at the same resolution.
#
# Gutter rule: the +1 gutters in W = (cw+1)*cols + 1, the cell pitch cw+1 and
# the hit-test x/(cw+1) are 1-byte `inc` instructions and share the SAME value,
# so they stay native 1 (a scaled gutter would desync draw vs hit-test).  The
# proportionate pitch is carried by cw itself: pitch_dev = cw_dev + 1.
# ---------------------------------------------------------------------------
TECH_COLS_TABLE = (0, 1, 2, 3, 4, 5, 3, 4, 4, 5, 5, 6, 4, 5, 5, 5, 4, 5, 6, 5,
                   5, 7, 6, 6, 6, 5, 7, 7, 7, 8, 8, 8, 8, 7, 7, 7, 8, 8, 8, 8)
TECH_COLS_OVER = 10             # n >= 40 (the exec's edi = 10, shared with pad)
TECH_PAD = 10                   # [+0xA1C]: cursor pad, icon gap, bottom margin pad/2
TECH_CAPTION_H = 0x1D           # [+0x16C]; hit-test y -= 0x1D; cell T clamp
TECH_GRID_TOP = 0x1E            # first cell row; H = (ch+1)*rows + 0x1E
TECH_CELL_INSET = 3             # cell frame R/B -= 3, L/T clamp 3, canvas edge - 3
TECH_CW_MARGIN = 0x14           # cw = SW/cols - 20 (n<=8) | (SW-20)/cols (n>8)
TECH_CH_MARGIN_LE8 = 0x28       # overflow: ch = SH/rows - 40 (n<=8)
TECH_CH_MARGIN_GT8 = 0x45       # overflow: ch = (SH-69)/rows (n>8)
TECH_CAPTION_STRIP = (3, 0x17)  # strip rect {3,3,W-3,3+0x17}; text rect inset 3 more
TECH_STRIP_BOTTOM = 3 + 0x17    # strip bottom edge scaled as ONE cascade: s(26) (v2)
TECH_CELL_GAP = 1 + 3           # native gutter (inc) + inset: the proportionate gap/right-bottom channel (v2)
TECH_ICON_ART = 0xD7            # tech icon art 215x215 (techs\tech0NN.pcx)
TECH_ICON_THRESH = (0x8C, 0xB4) # cw <= 0x8C -> s=-14; cw < 0xB4 -> -12; else -10
TECH_ICON_CLASSES = (-14, -12, -10)
TECH_FONT_BODY_LE8, TECH_FONT_BIG_LE8, TECH_FONT_NAME_LE8 = 14, 18, 20
TECH_FONT_BODY_GT8, TECH_FONT_BIG_GT8, TECH_FONT_NAME_GT8 = 10, 12, 12
TECH_FONT_CAPTION = 18
# painter insets (native): name x+2/w-6 (n<=8), name x+2/w-4 (n>8), overflow w-2,
# category x+1/w-2, quote x+4/w-8, unlock x+1/w-2 (the +1s are `inc` = stay native)
TECH_INSETS = {"name_x": 2, "name_w": 6, "name9_w": 4, "overflow_w": 2,
               "cat_w": 2, "quote_x": 4, "quote_w": 8, "unlock_w": 2}


def tech_cols(n: int) -> int:
    """cols = table[n] (0x487A01..0x487C58), 10 for n >= 40."""
    if n < 0:
        raise ValueError("tech_cols: n must be >= 0")
    return TECH_COLS_TABLE[n] if n < len(TECH_COLS_TABLE) else TECH_COLS_OVER


def tech_layout(screen_w: int, screen_h: int, n: int, g: int) -> dict:
    """TechWin_exec layout law at device density (option a).  Identity at g=16 =
    vanilla's screen-fit law verbatim (trace-verified at 1024/1600/4K).

      cols = table[n]; rows = ceil(n/cols)
      cw   = n<=8 ? SW/cols - s(20) : (SW - s(20))/cols ;  cw = min(cw, SW/3)
      ch   = cw*3/2 ;  ch = max(ch, SH/2)
      if ch*rows + s(0x1D) > SH:  ch = n<=8 ? SH/rows - s(40) : (SH - s(69))/rows
      W = (cw+1)*cols + 1 ;  H = (ch+1)*rows + s(0x1E) ;  Win_center -> x,y
    """
    if n <= 0:
        raise ValueError("tech_layout: n must be >= 1 (n == 0 returns -1 before layout)")
    cols = tech_cols(n)
    rows = n // cols + (1 if n % cols else 0)
    s = lambda v: scale_px(v, g)  # noqa: E731
    if n <= 8:
        cw = screen_w // cols - s(TECH_CW_MARGIN)
    else:
        cw = (screen_w - s(TECH_CW_MARGIN)) // cols
    cw = min(cw, screen_w // 3)
    ch = (cw * 3) // 2
    ch = max(ch, screen_h // 2)
    if ch * rows + s(TECH_CAPTION_H) > screen_h:
        if n <= 8:
            ch = screen_h // rows - s(TECH_CH_MARGIN_LE8)
        else:
            ch = (screen_h - s(TECH_CH_MARGIN_GT8)) // rows
    w = (cw + 1) * cols + 1
    h = (ch + 1) * rows + s(TECH_GRID_TOP)
    return {"cols": cols, "rows": rows, "cw": cw, "ch": ch, "W": w, "H": h,
            "x": (screen_w - w) // 2, "y": (screen_h - h) // 2,
            "pad": s(TECH_PAD), "caption": s(TECH_CAPTION_H), "grid_top": s(TECH_GRID_TOP)}


def tech_cell_rect(idx: int, lay: dict, g: int) -> Tuple[int, int, int, int]:
    """TechWin_draw_cell 0x4863F0 frame rect (the Buffer_box_sprite d528/d578 rect):
      L = col*(cw+1)+1 ; R = L+cw-c_rb ; T = row*(ch+1)+s(0x1E) ; B = T+ch-c_rb
      L = max(L, s(3)) ; R = min(R, W-s(3)) ; T = max(T, s(0x1D)) ; B = min(B, H-s(3))
    with c_rb = tech_cell_inset_rb(g) (v2: the R/B inset absorbs the native +1 gutter so
    gap = L' - R = s(4) and the right/bottom channel W - R = s(4); the L-clamp stays
    s(3) so the left channel = s(3) - K).  (W/H = the window canvas = lay["W"]/lay["H"])."""
    s = lambda v: scale_px(v, g)  # noqa: E731
    cols, cw, ch = lay["cols"], lay["cw"], lay["ch"]
    col, row = idx % cols, idx // cols
    c_rb = tech_cell_inset_rb(g)
    l = col * (cw + 1) + 1
    r = l + cw - c_rb
    t = row * (ch + 1) + s(TECH_GRID_TOP)
    b = t + ch - c_rb
    l = max(l, s(TECH_CELL_INSET))
    r = min(r, lay["W"] - s(TECH_CELL_INSET))
    t = max(t, s(TECH_CAPTION_H))
    b = min(b, lay["H"] - s(TECH_CELL_INSET))
    return (l, t, r, b)


def tech_hit_index(x: int, y: int, lay: dict, g: int) -> int:
    """TechWin on_mouse_move 0x485FC0 hit-test (window-local device coords):
    y -= s(0x1D); in range iff 0<=x<cols*(cw+1) and 0<=y<rows*(ch+1);
    idx = (y/(ch+1))*cols + x/(cw+1).  -1 = miss."""
    y -= scale_px(TECH_CAPTION_H, g)
    cols, rows, cw, ch = lay["cols"], lay["rows"], lay["cw"], lay["ch"]
    if x < 0 or y < 0 or x >= cols * (cw + 1) or y >= rows * (ch + 1):
        return -1
    return (y // (ch + 1)) * cols + x // (cw + 1)


def tech_icon_class(cw_dev: int, g: int) -> int:
    """Icon size class s (0x4850DD..0x4850F9) from the DEVICE cw with the two
    thresholds scaled: cw >= s(0xB4) -> -10 ; cw <= s(0x8C) -> -14 ; else -12."""
    lo, hi = (scale_px(v, g) for v in TECH_ICON_THRESH)
    if cw_dev >= hi:
        return -10
    return -14 if cw_dev <= lo else -12


def tech_icon_ratio(s_class: int, g: int) -> Tuple[int, int]:
    """SCALE_NUM_G/DEN_G for the Sprite_draw_mono_2 icon blit: vanilla (16+s)/16;
    at g>16 ((16+s)*g)/256 = vanilla x g/16 exactly (always < 1, so the engine's
    4x blit cap is never approached).  g<=16 returns vanilla's own pair."""
    if s_class not in TECH_ICON_CLASSES:
        raise ValueError("tech_icon_ratio: s must be one of %r" % (TECH_ICON_CLASSES,))
    if g <= NATIVE_G:
        return (16 + s_class, 16)
    return ((16 + s_class) * g, 256)


def tech_icon_w(s_class: int, g: int) -> int:
    """iconW = floor(215 * num / den) (the painter's `sar 4` -> `sar 8` at g>16)."""
    num, den = tech_icon_ratio(s_class, g)
    return (TECH_ICON_ART * num) // den


def tech_icon_imms(g: int) -> dict:
    """The painter immediates that realise tech_icon_ratio in place (identity g<=16):
      den   : mov [SCALE_DEN_G], imm32 @0x485140      16 -> 256
      s10   : mov ebx, imm32 @0x4850E4                -10 -> 6g-16   (16+s = 6g)
      mask  : and ebx, imm8 @0x4850F6                   2 -> 2g      (bl=0 path -> 4g-16)
      add   : add ebx, imm8 @0x4850F9                 -14 -> 2g-16   (bl=1 path -> 2g-16)
      shift : sar eax, imm8 @0x485183 / 0x485213        4 -> 8       (iconW = 215*num/256)"""
    if g <= NATIVE_G:
        return {"den": 16, "s10": -10, "mask": 2, "add": -14, "shift": 4}
    return {"den": 256, "s10": 6 * g - 16, "mask": 2 * g, "add": 2 * g - 16, "shift": 8}


DW_FIT_MARGIN = 8       # device px kept clear of the Caviar target edge (footprint n<=8 overdraw)
DW_FIT_SLACK = 4        # trial-space px added to the extent: centring drift + 2x2 trial footprint
DW_FIT_MIN_FIT = 1.02   # below this gain the FIT mode is not worth a second render


def dw_fit_plan(bb: Tuple[int, int, int, int], tn: int, g: int, ssaa: bool = True, fit: bool = True) -> dict:
    """LAW — Design Workshop unit-render FIT/SSAA plan from a native-zoom TRIAL render.

    The trial renders the unit at its native Caviar zoom z into the tn x tn target;
    bb is the trial's dirty bbox in target space.  The real render then runs at
    zoom z*k and is composited back at W screen px per tn target px, so the unit
    lands on screen at exactly vanilla x (g/16) ("need") whatever k is; k > need is
    pure supersampling (k = 2*need => 2x2 SSAA).

    THE CONSTRAINT IS RADIAL, NOT THE EXTENT: Caviar scales the model about the
    TARGET CENTRE c = tn/2, and the trial bbox is not centred there (the flag&4
    centring accumulator and the part offsets drift with rotation).  v14's law used
    kf = (tn-16)/(E*1.06) with E = max(w,h): the Rover Formers' crane at 4K had
    E = 158 (fits x5 = 790 px) but its far edge sat 104 px from the centre, and
    x5 that crosses the target edge (real bbox to x=1025 / y=0, user 4K shot
    20260829-020648).  A part that crosses the ctx clip is plotted by the CLIPPED
    twin 0x664000 — vanilla 2x2 footprint — so the crane went see-through at some
    rotations exactly like the v13 colony-pod tank.  So: R = max distance of the
    bbox from c (+ DW_FIT_SLACK in trial space), and the scaled radius must stay
    inside c - DW_FIT_MARGIN.

    Modes: 'ssaa' when the safe k reaches at least need (k = min(2*need, kf) — the
    SSAA factor eases from 2 down to 1 rather than popping to a non-SSAA fit);
    'fit'/'fit1:1' when only a sub-need gain fits (FIT enabled); else 'nn' (k=1,
    W = tn*g/16 = the engine's own NN enlarge of a native-zoom render; v14s had
    16g, the 256^2-target value, wrong for option E's tn=1024).

    OVERLAY draws (Caviar_overlay 0x6171A0: the Probability Sheath shell, drawn
    through a 256x256 translucency table by the wrapper's OWN blit after
    Caviar_draw returns with flag|8) must call this with ssaa=False: the SSAA
    composite cannot apply the table, so the wrapper's blit is rescaled instead
    (num=W, den=tn) and a 1:1 device-density render ('fit1:1', W == tn) is the
    resample-free case.  W is rounded to an integer and k re-derived
    from it so the composite ratio is exact (tn/W per device px)."""
    c = tn / 2
    need = g / 16
    r = max(1.0, bb[2] - c, c - bb[0], bb[3] - c, c - bb[1]) + DW_FIT_SLACK
    kf = (c - DW_FIT_MARGIN) / r
    if ssaa and kf >= need:
        k, mode = min(2 * need, kf), "ssaa"
    elif fit and kf > DW_FIT_MIN_FIT:
        k = min(need, kf)
        mode = "fit1:1" if k >= need - 1e-9 else "fit"
    else:
        return {"k": 1.0, "W": tn * g // 16, "mode": "nn", "R": r, "kf": kf}
    w = int(math.floor(tn * need / k + 0.5))
    k = tn * need / w
    return {"k": k, "W": w, "mode": mode, "R": r, "kf": kf}


def dw_button_rows(win_l: int, win_r: int, g: int) -> dict:
    """LAW — Design Workshop modal button rows, x geometry (DesignWin builder 0x43C8C9..0x43CA34).

    Vanilla: x0 = L+0x1B; cell = (R-0x20-0x1B - x0 + 3) / 5 (trunc); the LOWER row
    (DONE RENAME OBSOLETE UPGRADE CANCEL) is x_i = x0 + i*cell, width cell-3, so the
    channel is 3 and the pitch is cell.  The UPPER row is built from the lower one:
    APPLY = DONE's rect, PROTO = APPLY + ((R_last - x_last) + 3), RETIRE = CANCEL's rect,
    RETIRE ALL = RETIRE + ((x_last - R_last) - 3) — and (R_last - x_last) + 3 == cell, so
    every button of both rows sits on the SAME 5-column grid (PROTO over RENAME,
    RETIRE ALL over UPGRADE).

    Scaled: every immediate is scale_px'd (the proto's S levers).  The two post-loop
    +-3 (0x43C9B2 / 0x43CA27) were left native until v14t, so the upper pitch was
    cell - s(3) + 3: at g=25 PROTO sat 2 px left of RENAME and the upper channels read
    5 px against the lower row's 7 (user 1600 shot 20260829-022448).  The visible
    channel is the rect channel + 2*s(1) (FlatButton face inset), identical per row."""
    s3, x0 = scale_px(3, g), win_l + scale_px(0x1B, g)
    span = (win_r - scale_px(0x20, g) - scale_px(0x1B, g)) - x0 + s3
    cell = int(span / 5)                       # engine: imul 0x66666667 + sar 1 = truncating /5
    lower = [(x0 + i * cell, x0 + i * cell + cell - s3) for i in range(5)]
    x_last, r_last = lower[4]
    pitch_up = (r_last - x_last) + s3          # post-loop cursors: == cell once both +-3 scale
    apply, retire = lower[0], lower[4]
    proto = (apply[0] + pitch_up, apply[1] + pitch_up)
    retire_all = (retire[0] - pitch_up, retire[1] - pitch_up)
    return {"cell": cell, "channel": s3, "lower": lower, "upper": [apply, proto, retire_all, retire]}


# ==== Type-2 (#listbox) popup ListBox layout SOURCES (fix 29) ====
# Popup_calculate_dimensions 0x404B10 is the one writer of the popup list's layout sources on the list's Dialog part
# D = popup + 0x21D0 + [[popup + 0x21D0] + 8]: stride [D+0x48] = 0x13 (@0x404CE8), gap [D+0x44] = 3 (@0x404D04),
# text indent [D+0x34] = 3 (@0x404D3F; 27 @0x404D29 is the type-1 checkbox dialog, which never reaches the ListBox
# calc).  The popup state 5 (PopupDialogState @0x404CC0) skips the stride/indent stores and leaves the Dialog ctor's
# stride -1 (row height from the font).  ListBox_calculate_dimensions 0x60A1E0 then runs on the SAME fields at
# least twice per show (BasePop_calc's dims dispatch @0x603B42, ListBox_attach @0x60A6C1 from Dialog_set_type), and
# again on every re-attach (Dialog redraw dispatch @0x61303B, ListBox_update_changes @0x60C9F4).
POPUP_LB_STRIDE_NATIVE = 0x13
POPUP_LB_GAP_NATIVE = 3
POPUP_LB_INDENT_NATIVE = 3
POPUP_LB_TYPE = 2                 # popup [+0x2350]: the dims dispatch 0x6132A0 reaches the ListBox calc for exactly 2


def popup_listbox_sources(stride: int, gap: int, indent: int, g: int, *, popup_type: int = POPUP_LB_TYPE,
                          popup_active: bool = True) -> Tuple[int, int, int]:
    """LAW — the type-2 popup ListBox's layout sources as every calc pass must see them: scaled ONCE, at the writer,
    to fl(native * g/16) (the popup FLOOR idiom, popup_scale_floor), keyed on the writer's own native literal.

    (stride, gap, indent) are the fields as Popup_calculate_dimensions leaves them at its BasePop_calc call 0x404E93.
    The scale applies iff g > 16 (lo-res native no-op), the popup is a type-2 list, it runs inside an exec_3 modal
    (g_popup_active) and the stride is the writer's native 0x13 -- which it is exactly when the writer stored it this
    pass (fl(19 g/16) >= 20 for every g > 16, so a re-run of the calc on the same popup can never re-scale; state 5
    keeps the ctor's -1 and stays native, as before).  Every later calc pass then reads these values unchanged.

    Why not at the calc entry (thunk_lbcalc_scale's popup arm, retired by fix 29): a calc-entry scale needs an
    "already scaled" key, and its 0 < stride <= 0x16 key cannot tell native 19 from fl(19 g/16) = 20/21/22 at
    g = 17/18/19, so the second pass (ListBox_attach) scaled again: the list window took 12 rows at fl(21*18/16) = 23
    (273 px at 1600x900) while the box reserve [popup+0x30C4] and the button row were laid out from pass 1's 21
    (249 px): the 12th row was drawn under the buttons.  At g >= 20 the key closed after one pass, which is why only
    g 17..19 broke.  Port: thunk_lbsrc_scale (CALL-redirect @0x404E93, tail -> thunk_scale_box_margin)."""
    if (g <= NATIVE_G or not popup_active or popup_type != POPUP_LB_TYPE
            or stride != POPUP_LB_STRIDE_NATIVE):
        return stride, gap, indent
    return popup_scale_floor(stride, g), popup_scale_floor(gap, g), popup_scale_floor(indent, g)


FILEDLG_LB_STRIDE_NATIVE = 0x16   # FileDlg_layout's one store @0x40777A (Dialog_init_3 leaves -1 before it)


def listbox_calc_entry_sources(stride: int, gap: int, indent: int, g: int, *,
                               filedlg_active: bool = False) -> Tuple[int, int, int]:
    """LAW — what thunk_lbcalc_scale (entry of ListBox_calculate_dimensions 0x60A1E0) does to the sources since
    fix 29: only the LOAD/SAVE picker arm is left.  Under g_filedlg_active at g > 16 a stride in (0, 0x16] is the
    FileDlg's native 0x16 (fl(22 g/16) >= 23 for every g > 16, so the key closes after one pass at ANY g) and the
    three sources scale once; every other list -- the popup's own (popup_listbox_sources owns it at the writer) and
    any other window's list recalculated while a popup is up -- passes through untouched."""
    if g <= NATIVE_G or not filedlg_active or not 0 < stride <= FILEDLG_LB_STRIDE_NATIVE:
        return stride, gap, indent
    return popup_scale_floor(stride, g), popup_scale_floor(gap, g), popup_scale_floor(indent, g)


def popup_listbox_rows_h(rows: int, stride: int, gap: int) -> int:
    """The list area height ListBox_calculate_dimensions derives for `rows` visible rows from the sources it reads
    (rowH = stride - gap; area = rows * stride - gap, the engine's [+0x60]).  BasePop_calc's box reserve
    [popup+0x30C4] comes from pass 1 and the list window (GraphicWin_init at ListBox_attach) from pass 2: they agree
    iff both passes read the same sources (the fix-29 invariant)."""
    return rows * stride - gap


def listbox_bar_reserve(sbw: int, g: int, popup_active: bool = True, rw_inlist: bool = False,
                        filedlg_active: bool = False) -> int:
    """LAW — the type-2 ListBox popup's scrollbar RESERVE (ListBox_calculate_dimensions
    0x60A1E0): when the rows overflow the visible count, the dialog width w5c gets
    `+= g_scrollbar_w` (0x60A63D; multi-column twin [+0x60] += @0x60A614; the
    flags&2 per-column bar subtract @0x60A659 divides the same global).  Every
    other term of the chain is scaled (w5c = max(scale(xs), items) via
    thunk_lbcalc_minw, the popup margins, the row stride) but this add stayed
    NATIVE: Select Special Ability @1920 measured w5c = 825 + 20 = 845 where
    vanilla is 600 + 20 = 620 -> box 899 vs lawful 907 (660*22/16), the frame R
    and the rail zone squeezed by 20*(g/16-1) (hardware watchpoint 2026-08-29:
    writers 0x60A432 = 825 then 0x60A640 = 845).  Scaled like the popup chrome
    pads: floor(v*g/16), gated on g_popup_active && g>16 exactly like
    thunk_lbcalc_minw (the value must NEVER be baked as 20 — g_scrollbar_w is a
    SHARED runtime global: read it live).  v2 (2026-09-26): while an HQ-report console list is
    being attached (g_rw_inlist == 1, between t_rw_scrollsmall and t_rw_scrollnormal) the WRITER
    already holds s(12) -- one owner per shared field -- so the readers pass it through even under
    the popup gate (a PROFILE opened from the diplomacy talk runs inside that popup's exec loop).
    v3 (2026-09-26q): the gate is g_popup_active OR g_filedlg_active (thunk_list_gate) -- the
    LOAD/SAVE picker's list builds the same heap V bar at the main menu (list flags 0x80020, no
    rail style 0x40) and every reserve read stayed native there (20-px bar at 4K, probe
    frida_filedlg_heapbar_20260927T0542xx); in game the same reads (row width, canvas) follow."""
    if rw_inlist or g <= NATIVE_G or not (popup_active or filedlg_active):
        return sbw
    return popup_pad(sbw, g)


def listbox_dialog_width(list_w_dev: int, sbw: int, g: int, popup_active: bool = True) -> int:
    """w5c after the reserve: the (already device-space) list width + the bar
    reserve.  Vanilla identity: list + 20."""
    return list_w_dev + listbox_bar_reserve(sbw, g, popup_active)


FACTION_QUOTE_POPUP = 0x9403E0     # the static faction-quote popup (thunk_d528_inset places its box its own way)


def popup_body_box_bottom(b: int, dialog: int, art: int, popup: int, g: int) -> int:
    """LAW (W9C F54, 2026-10-27) -- the bottom B the in-game popup's BODY-TEXT box is drawn with.

    Popup_on_draw_background builds the body-text rect [ebp-0x34..-0x28] = (L, T, R, B) HALF-OPEN (B = text top +
    [+0x30D4]), draws the inner d528 frame on it (site 0x406154) and, when the outer d5a0 union is the text rect alone
    -- no dialog element ([+0x2350] == -1) or an art popup ([+0x2144] != 0, the vanilla UnionRect skip @0x4061D0) --
    the union on (L - 3, T - 3, R + 3, B + 3) (0x4061FA..0x40621D, site 0x406238).  Vanilla's 9-slice draws a
    half-open rect's bottom stroke on row B - 1; the band-map thunks both frames go through draw row B (the F42 class,
    bandmap_rect_from_halfopen).  R already arrives inclusive (the pf_align / content_frame thunks anchor it to the
    title); B did not, so both bottom strokes sat one row low: the Planetary Governor popup (user shot
    20261027-133512, reproduced by f54\\gov_emu on the bb211440 bake) union -> OK 7 at 1920x1080 vs 6 x 22/16 = 8.25,
    1.88 short at g 21 / 29; the inner / outer stroke gap stayed equal (both moved).
    LAW: in that case the rect's B is decremented ONCE, before the d528 draw, and the union inherits it -- the inclusive
    footprint is then the native half-open extent (union -> OK = fl(6 g / 16) at every g, the stroke gaps unchanged).
    REACH (audit W9C): the Governor, every plain text + OK popup (flat and ornate), the TutWin windows (LANDFALL), the
    untitled ornate MPRECEIVEFILE, and every ART popup WITH or without a dialog (UPHEAVAL, NERVESTAPLE, CALLSCOUNCIL:
    vanilla's UnionRect skip makes their union the text rect alone, so their bottom strokes were one row low too).
    Not touched: a popup WITHOUT art that has body text and a dialog (#RENAME, COUNCILVOTE: the union is
    UnionRect(text, dialog), its bottom placed by the dialog family's thunks -- B - 1 there over-shoots the button
    channel by 1.75 - 2 px), a popup without body text (the d528 site does not run), the faction-quote popup (its own
    placement in thunk_d528_inset), and g <= 16 (vanilla)."""
    if g <= NATIVE_G or popup == FACTION_QUOTE_POPUP:
        return b
    if dialog == -1 or art != 0:
        return b - 1
    return b


def bandmap_rect_from_halfopen(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW — feeding a HALF-OPEN engine rect to the band-map frame thunk.

    ENGINE FACTS (measured): the native Buffer_box_sprite 9-slice renders the
    HALF-OPEN box [L,R)x[T,B) (right stroke at col R-1, bottom at row B-1), and
    every sibling primitive that shares the rect agrees — Buffer_tile_2 fills
    W = R-L columns, Buffer_set_clip culls col R / row B.  thunk_box_thick_hollow_flat
    (and _devfill/_intK) band-map with an INCLUSIVE footprint instead: the far
    edges R and B are drawn (the fe_bandmap dst is far-edge+1; see hud_cell_ring).
    Passing the scaled half-open rect straight through therefore renders the frame
    one device px too wide AND too tall (Design Workshop picker cells: 264x228 for
    a 263x227 law rect at 4K), and anything that later repaints the rect with the
    half-open convention (the empty-cell tile after a scroll) leaves that last
    column/row of stroke behind — the "phantom frame strokes" of the weapon picker
    scrolled to its bottom (user 4K shot 20260829-015255 vs pristine WeaponBottom.png).
    The tech screen met the same spill (tech_cell_inset_rb, "devfill with R-1/B-1").

    So a band-map thunk gets a COPY of the rect with the far edges decremented:
    the inclusive footprint [L..R-1]x[T..B-1] is then exactly the native half-open
    extent at device scale.  Identity at g<=16: the thunks pass the caller's rect
    to the native primitive there, whose half-open render already matches."""
    if g <= NATIVE_G:
        return (l, t, r, b)
    return (l, t, r - 1, b - 1)


def popup_backdrop_draw_right(rect_r: int, win_r: int, g: int) -> int:
    """LAW — the R the in-game popup's d690 backdrop DRAW gets (thunk_backdrop_railtrim).

    thunk_popup_d690insets lands the backdrop R on the right rail's first column
    (railscale's own double floor).  Vanilla draws that rect HALF-OPEN, so the
    border sits at R-1 and abuts the rail; thunk_box_thick_devfill band-maps it
    INCLUSIVE (bandmap_rect_from_halfopen), so the stroke's outer column lands ON
    col R and the rail, painted later, covers it: visible border K-1 = 1/1/0 px
    @g40/25/22 vs the left border's K (measured 2026-09-18, Quit + version + name-base).
    Only the DRAW copy moves: the rect itself still feeds the title band and the
    text-field R.  rect_r == win_r = the rect was not rail-inset (menu popups, the
    ornate types) -> nothing covers col R there (measured: full K on the faction
    quote box), unchanged.  B is under the bottom chrome in vanilla too -> kept."""
    if g <= NATIVE_G or rect_r == win_r:
        return rect_r
    return bandmap_rect_from_halfopen(0, 0, rect_r, 0, g)[2]


POPUP_TITLE_BAND_INSET = 4      # vanilla: band L 0x1A+1 = backdrop L 0x17 + 4; band R -0x3A-1 = backdrop R -0x37 - 4


def popup_title_band_lr(win_r: int, g: int) -> Tuple[int, int]:
    """LAW — the in-game rail popup's title band (L, R) as the band draw receives it (Popup_on_draw_background's band
    rect at 0x406048 after thunk_popup_titleinsets, the engine's `inc edx` @0x406027 and thunk_title_height's dec), for
    the window-local rect [0, win_r): R is the value thunk_box_thick_flat band-maps INCLUSIVE and the band thunk
    stashes as g_title_right (L as g_title_left).

    Vanilla (g <= 16, half-open draws): L = 0x17 + 4, R = (win_r - 0x37) - 4: the band sits 4 inside the backdrop
    on both sides, so its drawn strokes are 3 px clear of the backdrop's on both (L 0x1B vs 0x17, R col 0x3C vs 0x38
    from the right).  g > 16: L = rail_left_extent + fl(4g/16) (the backdrop's L), and R mirrors it against the
    backdrop's DRAWN right edge -- popup_title_band_right -- so both channels are fl(4g/16) - K."""
    if g <= NATIVE_G:
        return 0x17 + POPUP_TITLE_BAND_INSET, win_r - 0x37 - POPUP_TITLE_BAND_INSET
    anchor = ((((win_r << 4) // g) - 55) * g) >> 4          # thunk_popup_d690insets' R: railscale's double floor
    return rail_left_extent(g) + (POPUP_TITLE_BAND_INSET * g >> 4), popup_title_band_right(anchor, win_r, g)


def popup_title_band_right(anchor: int, win_r: int, g: int) -> int:
    """LAW (fix 19) — the title band's final R = the backdrop's DRAWN right edge (popup_backdrop_draw_right: the
    railtrim moves only the backdrop's draw copy to anchor - 1) minus fl(4g/16), the mirror of L = backdrop L +
    fl(4g/16).  v1 measured R from the untrimmed anchor, so the band's right channel was 1 px narrower than its left
    at every g > 16 (SELECT DESTINATION 8/7 @4K, 4/3 @1080p, 3/2 @1600x900).  Every g_title_right consumer (the union
    / container / body rings, their mirrored arms) moves with it, so each mirrors its g_title_left twin."""
    if g <= NATIVE_G:
        return anchor - POPUP_TITLE_BAND_INSET
    return popup_backdrop_draw_right(anchor, win_r, g) - (POPUP_TITLE_BAND_INSET * g >> 4)


def tech_cell_inset_rb(g: int) -> int:
    """v2 R/B cell inset = s(1+3) - 1.  Vanilla's cell gap and right/bottom channel are
    gutter(1, a 1-byte `inc` shared with the hit-test -> stays native) + inset(3) = 4;
    the proportionate gap is s(4), so the scaled inset carries what the gutter cannot.
    Identity 3 at g=16; 4 @g22, 5 @g25, 9 @g40.  (proto v1 measured s(3)=7 + 1 = 8 -> 7
    fill @4K vs the 10 vanilla x 2.5 asks for)."""
    return scale_px(TECH_CELL_GAP, g) - 1


def tech_strip_h_imm(g: int) -> int:
    """v2 immediate for `add eax,0x17` @0x487DBD: the strip bottom is s(3)+imm and must
    land on ONE cascade s(26) (floor-descale round-trip rule) -> imm = s(26) - s(3)
    (23 @g16, 32 @g22, 36 @g25, 58 @g40; s(3)+s(0x17) gave 64 @g40 = 1 px short)."""
    return scale_px(TECH_STRIP_BOTTOM, g) - scale_px(TECH_CAPTION_STRIP[0], g)


def tech_font_cell(native_cell: int, g: int) -> int:
    """v2 font law: fonts are calibrated by CELL (Font+0xC line pitch), target =
    fl(native_cell * g/16) (font-metric sublinearity law), Font_init'd at the smallest
    nominal whose cell >= target.  find_font (0x5882F0) cannot be used at g>16: it snaps
    to font_size_table {40,36,32,24,22,20,18,16,14,12,10,8} (name 20*2.5=50 -> 40,
    title 45 -> 40 at 4K: x2.0 measured in proto v1).  g<=16 -> the native cell."""
    return (native_cell * g) // 16


def tech_channels(g: int) -> dict:
    """The drawn fill widths (px between strokes) the v2 laws produce, for the
    proportionality test: vanilla left 2 / top 4 / gap 4 / right,bottom 3."""
    s = lambda v: scale_px(v, g)  # noqa: E731
    k = stroke_width(g)
    return {"left": s(TECH_CELL_INSET) - k,
            "top": s(TECH_GRID_TOP) - s(TECH_STRIP_BOTTOM),
            "gap": tech_cell_inset_rb(g) + 1,
            "right": tech_cell_inset_rb(g) + 1 - k,
            "bottom": tech_cell_inset_rb(g) + 1 - k}


def tech_font_size(native: int, g: int) -> int:
    """Nominal-size scaling s(native) (proto v1; superseded for the calibrated fonts by
    tech_font_cell -- kept for the search start of the calibration loop)."""
    return scale_px(native, g)


def tech_imm(v: int, g: int) -> int:
    """A single native constant in the tech cluster (insets, margins, caption): s(v)."""
    return scale_px(v, g)


def tech_caption_rects(lay: dict, g: int) -> dict:
    """Exec chrome after GraphicWin_init: caption strip d618 {s3,s3,W-s3,s(26)} (v2: the
    bottom is one cascade s(26) = s3 + tech_strip_h_imm) and the title text rect inset
    s(3) more: {2*s3, 2*s3, W-2*s3, s(26)-s3}."""
    s3 = scale_px(TECH_CAPTION_STRIP[0], g)
    w = lay["W"]
    strip = (s3, s3, w - s3, s3 + tech_strip_h_imm(g))
    text = (strip[0] + s3, strip[1] + s3, strip[2] - s3, strip[3] - s3)
    return {"strip": strip, "text": text, "backdrop": (0, 0, w, lay["H"])}


# --- btn ring overdraw (DL BACK/EXIT/category hover ring; 2026-09-01) -----------------------
def btn_ring_k(g: int) -> int:
    """Device thickness of the 2d-zoomed FlatButton hover ring's regenerated strokes.

    The box-sprite face art carries a 1px stroke; the NN zoom duplicates it to
    floor/ceil(g/16) unevenly per edge, and the E0/E1 pair remap then restripes the
    solid stroke (dither-pair ambiguity).  thunk_btn_ringfix overdraws the ring at
    device density AFTER the remap: K = ceil(g/16) on ALL four edges (>= every NN
    run, so no residual old-ring pixels survive), stroke colour read per edge from
    the BoxSpriteParams strip ART (colour 7/9 = no stroke on that edge), corner
    notches punched K x K with key 9 iff the corner art is keyed (the vanilla 1px
    chamfer, scaled -- the square-notch convention of the faction buttons).
    Identity at g<=16 (K=1 == the native ring; the thunk gates g>16 anyway).
    """
    return (g + 15) >> 4


# --- Datalinks tech page inputs: scaled exactly ONCE (2026-09-19) ---------------------------
RW_TEXTB_INSET = 0x35    # vanilla init_report_screen: textB (RW+0x5980) = win_h (RW+0x5990, the frame rect bottom) - 0x35;
                         # never read win_h from RW+0xA20: ReportWin_tech_reset overwrites it with textB - clipT every paint


def dl_tech_inputs(text_b: int, line_h: int, win_h: int, g: int) -> tuple[int, int]:
    """(textB, lineH) ReportWin_tech_page must see on the Datalinks path = vanilla x g/16, ONCE.

    The side-button column centres in [lineH + top + s(15), textB - s(30)], so both inputs
    must be device values.  They have TWO possible states on entry: NATIVE (vanilla
    init_report_screen: text_b == win_h - 0x35) or already DEVICE (the rw_scale_shared init
    lever rewrote them: text_b == fl(win_h) - s(0x35), and for g > 16 s(0x35) != 0x35, so the
    vanilla identity cannot hold).  The wrapper scales only the NATIVE state; a magnitude
    guard (the old `<= 800` / `<= 64`) is resolution-dependent and double-scales every
    device value under it (1600x1200: side buttons ~225px low; 4K: lineH only, ~26px).
    Identity at g <= 16.
    """
    if g <= 16 or text_b + RW_TEXTB_INSET != win_h:
        return text_b, line_h
    return scale_px(text_b, g), scale_px(line_h, g)


# --- ReportWin_tech_page: the leads-to row slots around y_mid (2026-10-25 F44) -----------------------------------
RW_TECH_ROW_GAP = 0x10   # vanilla: neighbouring rows sit btn_h + 16 apart in BOTH layouts -- the odd pair
                         # (non-DL 0x49957F / 0x499582, Datalinks 0x4995CC / 0x4995CF) and the even pitch 0x49960D /
                         # 0x49967C.  One gap, one owner: s(16) at every one of the six imms.


def rw_tech_row_slots(y_mid: int, btn_h: int, g: int) -> tuple[tuple[int, int, int], tuple[int, int, int, int]]:
    """ReportWin_tech_page's row slots = vanilla with the gap scaled ONCE: p = btn_h + s(16).

    odd  (RW+0x595C, RW+0x5958, RW+0x5960) = (y_mid - p, y_mid, y_mid + p)       -- a column of 1 / 3 rows
    even (RW+0x5964 .. RW+0x5970)          = y_mid + (i - 1) * p - trunc(p / 2), i = 0..3   -- 2 / 4 rows
    (trunc = the engine's cdq / sub / sar; p > 0 so it is a floor.)  btn_h is the device button height (the F2
    card's s(0x28)).  Both layouts take the SAME p, so the gap between any two neighbouring rows is s(16), above
    y_mid exactly as below it.  The non-DL odd pair is a separate pair of immediates from the Datalinks one (the
    page branches on iface mode 8): F2 drew its 3-row column with the native 16 while its 2- / 4-row columns took
    s(16) -- 24 px short at 4K, 6 px at 1080.  Identity at g <= 16 (s(16) == 16).
    """
    gap = scale_px(RW_TECH_ROW_GAP, g)
    p = btn_h + gap
    half = p // 2 if p >= 0 else -((-p) // 2)
    odd = (y_mid - btn_h - gap, y_mid, y_mid + btn_h + gap)
    even = tuple((i - 1) * p - half + y_mid for i in range(4))
    return odd, even


# --- ReportWin_tech_page F2 card: the research header's insets, text gaps and bracket outset (2026-10-25 F45) -----
# Vanilla immediates of the F2-only branch (iface mode != 8; the Datalinks page never runs them).  Each is a device
# offset added to an already-device coordinate, so each scales ONCE: s(v).
RW_TECH_HDR_INSET = 3        # band -> text box, both sides: L 0x498DBF (blind) / 0x498C85, R 0x498CB0
RW_TECH_LINE_X = 3           # text box L -> line text x: line 1 0x498D4F, line 2 0x499171
RW_TECH_BLIND_TEXT_X = 5     # blind-research box L -> its text x: 0x498DC5
RW_TECH_NAME_GAP = 0xF       # research name end -> the next text piece on line 1: 0x498FDD
RW_TECH_RATE_GAP = 4         # 'Breakthroughs every ...' end -> 'Next breakthrough ...': 0x49948A
RW_TECH_BRACKET_OUTSET = 7   # research bracket: clip rect outset before the box draw, inset after (round trip):
                             # 0x4992C7 / 0x499334 (bracket 1), 0x49938B / 0x4993FB (bracket 2)
RW_TECH_CARD_IMMS = {        # imm VA -> vanilla value (the rows of assemble_rw.RW_IMMS, HD kind, b = 0)
    0x498DBF: RW_TECH_HDR_INSET, 0x498DC5: RW_TECH_BLIND_TEXT_X, 0x499171: RW_TECH_LINE_X,
    0x498FDD: RW_TECH_NAME_GAP, 0x49948A: RW_TECH_RATE_GAP,
    0x4992C7: RW_TECH_BRACKET_OUTSET, 0x499334: RW_TECH_BRACKET_OUTSET,
    0x49938B: RW_TECH_BRACKET_OUTSET, 0x4993FB: RW_TECH_BRACKET_OUTSET,
}


def rw_tech_card_imms(g: int) -> dict[int, int]:
    """The F45 immediates' device values at g: s(vanilla) each.  Identity at g <= 16."""
    return {va: scale_px(v, g) for va, v in RW_TECH_CARD_IMMS.items()}


def rw_tech_blind_header(band_l: int, band_r: int, g: int) -> tuple[int, int, int]:
    """Blind-research header (GameRules 0x200, not omniscient): (box L, box R, text x).

    The text box sits s(3) inside the band on BOTH sides (vanilla 3 / 3 -- the right inset was already s(3), the
    left a native 3: 3 vs 7 at 4K) and its text starts s(5) inside the box.  Identity at g <= 16.
    """
    box_l = band_l + scale_px(RW_TECH_HDR_INSET, g)
    return box_l, band_r - scale_px(RW_TECH_HDR_INSET, g), box_l + scale_px(RW_TECH_BLIND_TEXT_X, g)


def rw_tech_line_x(box_l: int, g: int) -> int:
    """Header line 1 and line 2 share one x: text box L + s(3) (line 2 was box L + 3, 4 px left of line 1 at 4K)."""
    return box_l + scale_px(RW_TECH_LINE_X, g)


def rw_tech_text_gap(end_x: int, vanilla_gap: int, g: int) -> int:
    """x of the next text piece after a piece ending at end_x: end_x + s(gap) (0xF after the name, 4 after the rate)."""
    return end_x + scale_px(vanilla_gap, g)


def rw_tech_bracket_rect(clip: tuple[int, int, int, int], g: int) -> tuple[int, int, int, int]:
    """The research bracket's box rect: the clip rect (the progress increment) outset by s(7) on all four sides.
    The page insets it by the same s(7) after the draw, so the rect round-trips exactly.  Identity at g <= 16."""
    d = scale_px(RW_TECH_BRACKET_OUTSET, g)
    l, t, r, b = clip
    return l - d, t - d, r + d, b + d


RW_TECH_RING = 1             # research increment ring: bracket 2's clip = bracket 1's clip inset 1 on every side
                             # (inc / dec 0x499366 L, 0x499367 R, 0x499368 T, 0x499378 B; measured: a 1-px ring of
                             # the progress art around the bar-coloured interior, pristine 1024x768)


def rw_tech_ring_clip(clip: tuple[int, int, int, int], g: int) -> tuple[int, int, int, int]:
    """The research bracket's second clip: the increment (bracket 1's clip) inset by the ring width on all four
    sides.  The ring is a 1-px vanilla stroke, so it is K = stroke_width(g) device px (LAW 4: the K every frame on
    the screen shares; 2 at 4K, 1 at 1080), the same on L / T / R / B.  g <= 16: the native 1 (no-op gate).
    An increment narrower than 2K leaves an empty clip -- bracket 2 draws nothing, as vanilla does below 2 px.
    The ring's pixels are progress art, so they keep the device stripe grid (the dither law): every ring pixel is the
    colour the progress segment has on the same row -- vanilla's relation, held by restriping the increment right after
    bracket 1 (t_rw_br1), while every column still has its stripe mate."""
    k = stroke_width(g) if g > NATIVE_G else RW_TECH_RING
    l, t, r, b = clip
    return l + k, t + k, r - k, b - k


# --- parity-preserving NN enlarge for scanline-striped sprite art (2026-09-09) --------------
# The console's icon family (7 kind-tab icons, 7 faction-tab logos incl. the crest, the base
# locator buttons) is period-2 scanline art: every odd/even native row pair is a dither pair
# (Report.pcx: purple/navy F0/B9 + tile-blue/black C5/41 in state 0, teal/purple in hover ...).
# Resampling that art bands (NN hard, bilinear soft; the dither invariant) -- so the enlarge
# REGENERATES the stripes: each device row takes the stripe phase from the shared device grid
# (stripe_top) and samples a native row of the matching parity; columns are the crisp
# output-driven edge-clamped NN of thunk_sprite_scale_nn.  Pair-agnostic: no palette census,
# so a new state/pair can never band.  Identity at g=16 (plain NN, which IS the engine's 1:1).
PARITY_MIN_DELTA = 4     # channel units (0..255): below this the two parities are "the same"


def nn_center_index(d: int, dst: int, src: int) -> int:
    """Output-driven, centre-sampled, EDGE-CLAMPED NN inverse map (thunk_sprite_scale_nn's law):
    dest index d in [0, dst) -> src index ((2d+1)*src) // (2*dst), clamped to [0, src-1], so the
    last dest col/row always reads the last src col/row (the engine's source-driven DDA drops it
    at a fractional ratio: thin-line disappearance)."""
    if dst <= 0 or src <= 0:
        return 0
    return min(max(((2 * d + 1) * src) // (2 * dst), 0), src - 1)


# ==== MAP CURSORS (load_cursors 0x454FC0: 12 sprites cut from CURSOR.PCX at 0x93AA70, stride 0x2C) ==================
# The engine's software cursor (Win_update_cursor 0x5F1820 + PaintMain's blit 0x5EFF0E) draws these at native size
# at every resolution: a 29x27 patrol cursor on a 4K screen (user 2026-10-14).  Law: the whole 32x32 cell is
# enlarged by output-driven, centre-sampled NN (nn_center_index) to cursor_canvas_px(g) = scale_px(32, g); the art is
# shaded pixel art (no ordered dither / scanlines, measured on CURSOR.PCX), so NN is the right enlargement.  The
# sprite's trimmed content rect and the hotspot follow the same map: a native pixel c covers the dest run
# cursor_nn_run(c); the content rect is the union of its columns' / rows' runs, the hotspot the run's centre.
# g <= 16: the native cell, untouched.
CURSOR_CELL = 32


def cursor_canvas_px(g: int) -> int:
    """The enlarged cursor cell side: vanilla 32 x g/16 (scale_px); 32 at g <= 16."""
    return CURSOR_CELL if g <= NATIVE_G else scale_px(CURSOR_CELL, g)


def cursor_nn_run(c: int, g: int, n: int = CURSOR_CELL) -> Tuple[int, int]:
    """The dest indices [a, b] (inclusive) whose nn_center_index source is native index c in a cell of n, at the
    canvas size cursor_canvas_px(g) (scaled with the cell: n * S / 32).  Non-empty for every c (the canvas is never
    smaller than the cell)."""
    s = n if g <= NATIVE_G else scale_px(n, g)
    hits = [d for d in range(s) if nn_center_index(d, s, n) == c]
    return hits[0], hits[-1]


def cursor_hotspot(h: int, g: int) -> int:
    """The scaled hotspot coordinate: the centre (rounded down) of the dest run of the native hot pixel h, so the
    hot point stays on that pixel's middle at every scale.  g <= 16: h."""
    if g <= NATIVE_G:
        return h
    a, b = cursor_nn_run(h, g)
    return (a + b) // 2


def cursor_content_rect(left: int, top: int, w: int, h: int, g: int) -> Tuple[int, int, int, int]:
    """The trimmed content rect (Sprite +0x20 / +0x24 / +0x10 / +0x14) of the enlarged cell: from the first dest
    index of the first native column / row to the last dest index of the last one.  g <= 16 or an empty rect:
    unchanged."""
    if g <= NATIVE_G or w <= 0 or h <= 0:
        return left, top, w, h
    l0, _ = cursor_nn_run(left, g)
    _, r1 = cursor_nn_run(left + w - 1, g)
    t0, _ = cursor_nn_run(top, g)
    _, b1 = cursor_nn_run(top + h - 1, g)
    return l0, t0, r1 - l0 + 1, b1 - t0 + 1


def stripe_parity_vote(peak_even: float, peak_odd: float, sum_even: float, sum_odd: float) -> int:
    """Which native row parity carries the TOP (wide-band, coloured) stripe member of a sprite:
    1 = odd rows, 0 = even rows, -1 = not striped (plain NN).  Inputs = means over the OPAQUE
    texels of each parity of the palette peak channel (pair_top's first key) and of the channel
    sum (its second key): a striped sprite has one parity systematically brighter; a photo /
    line-art sprite has both parities alike -> -1.  Ties within PARITY_MIN_DELTA fall through
    to the sum means, then to -1."""
    d = peak_odd - peak_even
    if abs(d) < PARITY_MIN_DELTA:
        d = sum_odd - sum_even
        if abs(d) < PARITY_MIN_DELTA:
            return -1
    return 1 if d > 0 else 0


def stripe_parity_vote_sums(pe: int, ne: int, po: int, no: int, se: int, so: int) -> int:
    """The thunk's integer form: peak/channel-sum TOTALS and opaque-texel COUNTS per parity, floor
    means (unsigned div), then stripe_parity_vote.  An empty parity -> -1 (unstriped)."""
    if ne <= 0 or no <= 0:
        return -1
    return stripe_parity_vote(pe // ne, po // no, se // ne, so // no)


def parity_nn_row(dy: int, dst_h: int, src_h: int, y_abs: int, g: int, top_parity: int) -> int:
    """Native row that dest row dy of a parity-preserving NN enlarge samples.

    g <= 16, an unstriped sprite (top_parity < 0) or a sprite under 2 rows -> nn_center_index
    (plain output-driven NN; identity to the engine at g=16).  Otherwise the dest row's stripe
    phase on the shared device grid (stripe_top(y_abs, g); y_abs = the row in the buffer the
    stripes must fuse with) selects the native parity -- top rows sample rows of parity
    top_parity, bottom rows the other -- and the row is the nominal centre sample when it has
    that parity, else the NEARER of its two neighbours (the one in range at the sprite edge).
    |row - nominal| <= 1 always: the shape moves by at most one native row while the stripe
    pattern comes out at the device period P (the fill law), never as a resampled 2-row period."""
    n = nn_center_index(dy, dst_h, src_h)
    if g <= NATIVE_G or top_parity < 0 or src_h < 2:
        return n
    want = top_parity if stripe_top(y_abs, g) else 1 - top_parity
    if n % 2 == want:
        return n
    lo, hi = n - 1, n + 1
    if lo < 0:
        return hi
    if hi >= src_h:
        return lo
    exact2 = (2 * dy + 1) * src_h                     # 2*dst_h x the exact source centre
    dlo = abs((2 * lo + 1) * dst_h - exact2)
    dhi = abs((2 * hi + 1) * dst_h - exact2)
    return lo if dlo <= dhi else hi


def parity_nn_row_map(dst_h: int, src_h: int, y0: int, g: int, top_parity: int) -> List[int]:
    """[parity_nn_row(dy, ...) for every dest row], y_abs = y0 + dy."""
    return [parity_nn_row(dy, dst_h, src_h, y0 + dy, g, top_parity) for dy in range(dst_h)]


# --- console icon family v2 (t_rwk_parity_nn v2, 2026-09-12): the columns blend ----------------
# Report.pcx's 7 kind-tab icons (29x35 x 3 states) and the faction tabs' small report logos are
# row-parity art THROUGH AND THROUGH: odd rows use one palette family (E6/BB light frame+glyph),
# even rows the other (B0/37); there is no non-pair pixel to smooth.  The parity row law above
# keeps every stripe exact; the v1 columns were centre-sampled NN (nn_center_index), so at
# 22/16 and 25/16 a 2-px glyph stem came out 3 or 4 device px by phase (uneven verticals).
# v2 = the A5 bilinear's tap law on the x axis only, INSIDE the parity-selected native row:
# a dest pixel reads its two horizontal taps from that one row (never a row of the other
# parity), keeps the index VERBATIM when no blend is needed (equal taps or a key tap -- the
# stripe pair members survive for the later restripe passes) and blends only a true glyph
# edge, palette-nearest over the dest's synced palette, never the key (bilinear law).

def bilinear_axis(d: int, num: int, den: int, src: int) -> Tuple[int, int, int, int]:
    """Top-left-aligned 8.8 tap law of thunk_sprite_bilinear on one axis: dest index d ->
    (i0, i1, f, near) with i0 = floor(d*den/num) (clamped into the source), i1 = min(i0+1,
    src-1), f = ((d*den mod num) << 8) // num the weight of i1, and near = the coverage texel
    (i1 iff that fraction is >= 1/2, else i0)."""
    if num <= 0 or den <= 0 or src <= 0:
        return (0, 0, 0, 0)
    i0, rem = divmod(d * den, num)
    i0 = min(max(i0, 0), src - 1)
    i1 = min(i0 + 1, src - 1)
    f = (rem << 8) // num
    near = i1 if 2 * rem >= num else i0
    return i0, i1, f, near


def palette_nearest(c, table, key: int) -> int:
    """Lowest palette index whose (c0,c1,c2) entry is at minimal squared distance from c;
    the transparency key never wins (the bilinear's never-emit-the-key rule)."""
    best, bd = 0, 1 << 62
    for i in range(256):
        if i == key:
            continue
        e = table[i]
        d = (e[0] - c[0]) ** 2 + (e[1] - c[1]) ** 2 + (e[2] - c[2]) ** 2
        if d < bd:
            bd, best = d, i
    return best


def parity_hblend_pixel(t0: int, t1: int, f: int, tn: int, table, key: int):
    """The v2 x-law of the parity enlarge for one dest pixel: t0/t1 = the two horizontal taps
    (weight f/256 on t1) and tn = the coverage texel, all read from the parity-selected native
    row.  None = transparent (the coverage texel is the key).  Equal taps or a key tap emit the
    surviving index verbatim; otherwise the 8.8 blend of the two palette entries, rounded, then
    palette_nearest."""
    if tn == key:
        return None
    if t0 == t1:
        return t0
    if t0 == key:
        return t1
    if t1 == key:
        return t0
    a, b = table[t0], table[t1]
    c = [(a[i] * (256 - f) + b[i] * f + 128) >> 8 for i in range(3)]
    return palette_nearest(c, table, key)


# --- HQ report BASE STATUS rows: chrome follows content (2026-09-10) ----------------------------
# Vanilla (refs/pristine/HQData/Base_Citizens.png): entry box 40 rows = 1px stroke + 38-row citizen
# face + 1px stroke, pitch 42 (cell 40 + 2).  ReportWin_draw_bases keeps ONE cell quantity
# (0x28 -> row height AND the leader-icon cell width) and places the face at
# y = rowBottom - pitch/2 - 18.  Scaling the cell by s(40) and the face by floor(38g/16)
# independently leaves the face 0..2 rows short of the strokes (user 2026-09-09: "citizen
# graphics don't line up with the top and bottom frame stroke"); the faithful law sizes the
# CHROME from the CONTENT it wraps (frame9 law 5): cell = 2K + face, and the y immediate keeps
# the face flush under the top stroke.  Identity at g=16: 2 + 38 = 40, 40 - 21 - 1 = 18.
BASES_ROW_FACE_H, BASES_ROW_GAP, BASES_FACE_Y_IMM = 38, 2, 18


def bases_face_h(g: int) -> int:
    """Device height of a citizen face: the engine blit's floor(38*g/16) (Sprite_blit_scaled_core
    under the g/16 SCALE bracket)."""
    return (BASES_ROW_FACE_H * g) // NATIVE_G


def bases_row_cell(g: int) -> int:
    """Entry-box height (and leader-icon cell width) = K stroke + face + K stroke."""
    return 2 * stroke_width(g) + bases_face_h(g)


def bases_row_pitch(g: int) -> int:
    """Row pitch = cell + s(2) (the painter's `pitch = cell + 2`, gap scaled by its own row)."""
    return bases_row_cell(g) + scale_px(BASES_ROW_GAP, g)


# ---- HQ report BASE LOCATOR ring (ReportIf_blink_step, 2026-09-12) --------------------------------
# Clicking a base row (ReportWin_on_lclick 0x496E10) arms a 150 ms timer whose step stamps one of four
# 12x12 ring sprites (dot0..3.pcx, ReportIf+0x20254) onto the minimap window's canvas (WorldWin+0x444)
# through Sprite_blit_scaled_core at blink_x = px-7, blink_y = py-5 (px,py = the base tile's pixel in the
# already g/16-scaled minimap).  The stamp ran at the globals' 1:1 ratio, so the ring stayed 12 px on a
# 2.5x minimap.  Law: the stamp scales by g/16 (SCALE_NUM_G/DEN_G bracket = the citizen faces' G bracket)
# and its two native centring offsets scale with it.  The engine rejects ratios above g_sprite_scale_max
# (4.0): g caps at 40 -> 2.5, never reached.
BLINK_OFF_X, BLINK_OFF_Y = 7, 5
# "Big F4 indicators" (Longevity Mod Preferences checkbox -> g_big_f4, 2026-09-12d): a DELIBERATE divergence
# the user chose -- the ring at 2x the lawful size (3x until 2026-09-12f), at every g (native included).
# Above g=32 that ratio exceeds the engine core's 4.0 reject, so the big path stamps through
# thunk_sprite_scale_nn (our full-coverage NN, same Sprite_draw_2 contract, no cap) and leaves the SCALE
# globals alone.
BLINK_BIG_MUL = 2


# v2 centring (2026-09-12h, user's 4K shots 234142 vs pristine 234322): the ring's centre lives at (5.5, 5.5)
# of the 12x12 sprite, so vanilla's ring centre sits at (px-1.5, py+0.5) from the tile pixel (blink = px-7,
# py-5; measured (-0.5, +0.5) native in the pristine capture).  Scaling the (7,5) anchor instead kept the
# sprite's top-left law and dragged the centre by (1-r) native per axis -- 1.3 native low at 2x (measured
# (-0.6, +1.8)).  The stamp is now placed so that its centre (6r into a 12r sprite) lands on vanilla's
# centre scaled by g/16: x' = px - hd(3g,32) - 6r, y' = py + hd(g,32) - 6r, with px = x+7, py = y+5.
# v3 (2026-09-13, user's 1600 shot 001539: ring centre (-1.0, -0.3) native from the box centre, "slightly
# left"): vanilla's own ring sits half a native LEFT of the box centre; the user wants it centred, so the x
# term becomes hd(g,32) (~0.5 native) instead of hd(3g,32) (~1.5) -- a deliberate half-pixel divergence.
BLINK_RING_CENTRE = 6            # the ring's centre inside the 12-px sprite (5.5 + the half-pixel)
# v13 (2026-09-13g, Frida-traced hook_chkrow_observer v2/v3 at 4K + 1600): the ring is centred on the BASE BOX
# itself.  The locator box is drawn by base_draw on the embedded CONSOLE's canvas (WorldWin+[[WorldWin+0x152C]+4]
# +0x1970) at console (px+3, py, px+9, py+6) half-open, (px,py) = MapWin_tile_to_pixel(console, tx, ty); that
# render (WorldWin +0xA14 x +0xA18, 320x152 on an 80x80 map) is copied to WorldWin+0xA1C and then EITHER centred
# 1:1 at (+0x239C4, +0x239C8) OR (thunk_worldwin_fill: g>16 with buf*g/16 overflowing the window, or the engine's
# own buf > window) StretchBlt'd (GDI, centre-aligned NN: dest j <- src floor((j+0.5)*buf/win)) to the window
# (+0x4C4 x -(+0x4C8)).  The engine's blink point instead comes from WorldWin_tile_to_pixel = (win_w*tx/80,
# win_h*ty/80) - (7,5): a DIFFERENT mapping (uniform per tile; the console's is 4 px/tile over 320 with a 2-tile
# left cut, 2 px/row over 152 with a 3-row top cut), so the ring drifted 2 console px right of the box at every g
# and up to +-8 device px in y on other rows.  The stamp now ignores the blink point at g>16: t_rwk_blinktile
# stashes the clicked base's tile (ReportWin_on_lclick 0x4974B2, the WorldWin_tile_to_pixel call), t_rwk_blink
# asks MapWin_tile_to_pixel for (px,py), and centres the 12r ring on the box centre (px+6, py+3) mapped exactly as
# the composition maps it (live fields; identity at g<=16 = the engine's own 1:1 stamp).
BLINK_BOX = (3, 0, 6, 6)         # base_draw's locator box inside its tile pixel: (dx, dy, w, h), console space (traced)


def minimap_stretched(g: int, win_w: int, win_h: int, buf_w: int, buf_h: int) -> bool:
    """thunk_worldwin_fill's decision (+ the engine's own): the map render is StretchBlt'd to the window."""
    return (win_w < (buf_w * g) >> 4 or win_h < (buf_h * g) >> 4 or win_w < buf_w or win_h < buf_h)


def blink_frame_span(off: int, w: int, num: int, den: int = NATIVE_G) -> int:
    """2*P + W of a ring frame drawn by thunk_sprite_scale_nn: P = floor(off*num/den) (the frame's draw offset
    inside its 12-px canvas, scaled), W = floor(w*num/den) (the frame's content width, scaled).  The drawn
    content's centre is X' + P + W/2 = X' + span/2."""
    return 2 * ((off * num) // den) + (w * num) // den


def blink_place(x: int, y: int, px: int, py: int, g: int, big: bool, win_w: int, win_h: int, buf_w: int, buf_h: int,
                off_x: int = 0, off_y: int = 0, spr_off_x: int = 0, spr_off_y: int = 0, spr_w: int = 12, spr_h: int = 12):
    """(x', y', num, den) of the BASE LOCATOR ring stamp (v14).  x,y = the engine's blink point (used only at
    g<=16 lawful, where the engine's own 1:1 stamp is left alone); px,py = the base pass's tile pixel for the
    clicked tile = MapWin_tile_to_pixel minus the console's row height [+0x1DDC0] in y (MapWin_gen_bases_only
    0x469B40 subtracts it before MapWin_draw_base_tile); win/buf = WorldWin +0x4C4/-0x4C8 and +0xA14/+0xA18;
    off = +0x239C4/+0x239C8 (the 1:1 centring offsets); spr_* = the frame sprite's own iLeftOffset/iTopOffset
    (+0x20/+0x24) and blit w/h (+0x10/+0x14).
    v14: every g>16 (and big) stamp goes through thunk_sprite_scale_nn at num/den = mg/16, and the frame's DRAWN
    content centre (X' + floor(off*num/16) + floor(w*num/16)/2, the scaler's own floors) is put on the box centre
    (px+6, py+3) mapped as the composition maps it: stretched -> * win/buf, else + off; half_down.  v13 centred the
    12r canvas instead, so the floored frames sat up to 0.75 dev px off at 1600 / 0.5 at 1920.
    Positive results only: the thunk's idiv truncates where Python floors (a ring off the top/left edge)."""
    if not big and g <= NATIVE_G:
        return (x, y, NATIVE_G, NATIVE_G)
    m = BLINK_BIG_MUL if big else 1
    num = m * g
    dx, dy, w, h = BLINK_BOX
    cx2, cy2 = 2 * px + 2 * dx + w, 2 * py + 2 * dy + h            # 2 x the box centre (px+6, py+3)
    tx, ty = blink_frame_span(spr_off_x, spr_w, num), blink_frame_span(spr_off_y, spr_h, num)
    if minimap_stretched(g, win_w, win_h, buf_w, buf_h):
        X = half_down(cx2 * win_w - tx * buf_w, 2 * buf_w)
        Y = half_down(cy2 * win_h - ty * buf_h, 2 * buf_h)
    else:
        X = half_down(2 * off_x + cx2 - tx, 2)
        Y = half_down(2 * off_y + cy2 - ty, 2)
    return (X, Y, num, NATIVE_G)


def bases_face_y_imm(g: int) -> int:
    """The immediate v in `y = rowBottom - pitch/2 - v` that puts the face top at rowTop + K:
    v = cell - pitch//2 - K  (identity 18 at g=16)."""
    return bases_row_cell(g) - (bases_row_pitch(g) >> 1) - stroke_width(g)


def rw_font_nominal(native: int, g: int) -> int:
    """Nominal size handed to find_font for the 15 report-window fonts: fl(native*g/16), NOT
    half_down.  find_font snaps the nominal to font_size_table {40,36,32,24,22,20,18,16,14,12,10,8}
    and resolves an exact tie to the LARGER size (19 -> 20).  A half-down nominal lands on such a
    tie for the 12-px list font at g=25 (18.75 -> 19 -> 20 = x1.67 while the rows scale x1.56):
    the BEST BASES panel's 'ENERGY RESERVES:' label ran into its right-aligned value at
    1600x1200 (user sweep 2026-09-11).  Flooring keeps the nominal <= the proportionate size, so
    the snap can only round up by the table's own granularity, never through a tie.  Identity at
    g=16; 16.5 -> 16 at g=22 and exact at g=40 either way (only g=25's size-12 fonts move: 20 -> 18).
    Text must fit the row it is laid out in: see feedback-font-metric-sublinearity."""
    return (native * g) // NATIVE_G


# ==========================================================================
# PLANETARY MONUMENT (F9; MonumentWin 0x7F9F58) -- full-height 4:3 letterbox
# ==========================================================================
# User decision 2026-09-13: the Monument (and the Hall of Fame) occupy the WHOLE
# display: the 1024x768 art scaled UNIFORMLY to the full screen height, centred,
# black letterbox at the sides.  Scale source = the UNCLAMPED popup g,
# num = min(floor(16*ScreenH/768), floor(16*ScreenW/1024)) over den 16 (45 @4K, 25 @1600x1200,
# 22 @1080p, 20 @1280x1024) -- the popup clamp (g<=40) would leave 120-px bars at 4K; the width
# term keeps the art inside a screen narrower than 4:3 (fix 11).  den is ALWAYS 16: the
# engine's sprite scaler and every baked blit thunk assume n/16.
# Prototype: hook_monument_proto.js v7d, measured-correct at 4K/1600/1080p
# (letterbox exact, alignment vs the pristine 2.8125x shots (0,0)).
# Every value here = vanilla x num/16 through half_down; identity at num == 16.

MON_NATIVE_W, MON_NATIVE_H = 0x400, 0x300         # the wide layout's art (the screen at native scale)
MON_ORG_X, MON_ORG_Y = 112, 84                     # content origin in the wide layout ((W-800)/2, (H-600)/2)
MON_CONTENT_NATIVE = (112, 84, 912, 684)          # MonumentWin +0xA24 in the wide build
MON_BTN_NATIVE = (824, 747, 200, 21)              # CLOSE / BACK FlatButton (x, y, w, h), window-local
MON_FONT_PLAQUE = 12                              # [0x8A40BC] = find_font(12, 0) in vanilla
MON_FONT_LABEL = 14                               # button label font 0x6E84B4 = 14 bold
MON_TABLE_COUNTS = ((0x3134, 17), (0x334C, 6), (0x366C, 7))   # rect tables A (pic far/text/pic near + 14 icons), B banners, C glyphs + emblem


def mon_scale_num(screen_w: int, screen_h: int) -> int:
    """The Monument's scale numerator over den 16:

        num = min(floor(16*ScreenH/768), floor(16*ScreenW/1024)) = scale_uniform(16, W, H), UNCLAMPED

    -- the popup g before its 16..40 clamp (popup_g; the 40 cap would not reach the full height at 4K),
    and the splash's splash_scale_num law.  4:3 and wider: the height term (the full-height letterbox).
    Narrower than 4:3 (1280x1024, 1152x960, portrait): the width term, so the s(1024) x s(768) art is
    never wider than the screen -- the height-only num of the first bake put the art 32 px past each
    side at 1280x1024 (BACK off-screen) and up to 740 px on a portrait screen (fix 11, 2026-10-18).
    Port: t_mon_build / t_hof_build call the shared scale_uniform (@0x668200) with eax = 16."""
    return scale_uniform(NATIVE_G, screen_w, screen_h)


def mon_armed(screen_w: int, screen_h: int, wide: int) -> bool:
    """The levers are live only in the engine's 1024x768 layout (wide flag 0x8A4168 != 0)
    and above native scale (num > 16).  At 1024x768 num == 16 -> every thunk is a no-op."""
    return bool(wide) and mon_scale_num(screen_w, screen_h) > NATIVE_G


def mon_art_rect(screen_w: int, screen_h: int, num: int) -> Tuple[int, int, int, int]:
    """(L, T, R, B) of the letterboxed s(1024) x s(768) art on the screen (half-open)."""
    lx, ly = mon_letterbox(screen_w, screen_h, num)
    return (lx, ly, lx + mon_s(MON_NATIVE_W, num), ly + mon_s(MON_NATIVE_H, num))


def mon_s(v: int, num: int) -> int:
    """half_down(v*num, 16): the one rounding every Monument geometry value takes."""
    return half_down(v * num, NATIVE_G)


def mon_letterbox(screen_w: int, screen_h: int, num: int) -> Tuple[int, int]:
    """(LX, LY): the scaled 1024x768 art centred on the screen (>> 1 floors, as the proto)."""
    return ((screen_w - mon_s(MON_NATIVE_W, num)) >> 1, (screen_h - mon_s(MON_NATIVE_H, num)) >> 1)


def mon_rect(r: Tuple[int, int, int, int], num: int, lx: int, ly: int) -> Tuple[int, int, int, int]:
    """A window-space rect authored as content-relative + (112,84): scaled dev = letterbox +
    s(112|84) + s(native - 112|84) -- each literal scaled independently (v1 forgot the s(112)/s(84)
    term and sat 315/236 px off at 4K)."""
    ox, oy = lx + mon_s(MON_ORG_X, num), ly + mon_s(MON_ORG_Y, num)
    return (ox + mon_s(r[0] - MON_ORG_X, num), oy + mon_s(r[1] - MON_ORG_Y, num),
            ox + mon_s(r[2] - MON_ORG_X, num), oy + mon_s(r[3] - MON_ORG_Y, num))


def mon_content_rect(num: int, lx: int, ly: int) -> Tuple[int, int, int, int]:
    """MonumentWin +0xA24: (LX + s(112), LY + s(84), LX + s(912), LY + s(684))."""
    l, t, r, b = MON_CONTENT_NATIVE
    return (lx + mon_s(l, num), ly + mon_s(t, num), lx + mon_s(r, num), ly + mon_s(b, num))


def mon_button_rect(num: int, lx: int, ly: int) -> Tuple[int, int, int, int]:
    """(x, y, w, h) of CLOSE / BACK: (LX + s(824), LY + s(747), s(200), s(21)) -- the window is
    resized to s(200) x s(21) and moved (parent-local +0x13C), its own rect +0x474 = (0,0,w,h)."""
    x, y, w, h = MON_BTN_NATIVE
    return (lx + mon_s(x, num), ly + mon_s(y, num), mon_s(w, num), mon_s(h, num))


def mon_font_size(native: int, num: int) -> int:
    """Nominal handed to find_font: floor(native*num/16) (plaque 12 -> 33 @4K, labels 14 -> 39)."""
    return (native * num) // NATIVE_G


def mon_stripe(num: int) -> Tuple[int, int]:
    """(P, hN) of every regenerated scanline on this screen (skill scaling-frames s7): the one stripe law
    P = 2T, hN = T, T = stripe_rows(num), from the Monument's own num (unclamped: T = 1 under 1080 px high, 45 @4K
    -> T = 2; T = 3 from num 48 = 2304 px high; the Hall of Fame's num clamps at 72)."""
    p = stripe_period(num)
    return p, (p + 1) >> 1


# ---- resampler (Lanczos-3 + Floyd-Steinberg error diffusion into the dest palette) -----------------
# User decision 2026-09-13 (options C/D): photographic art is enlarged SMOOTHLY, then error-diffused
# into the 8-bit canvas palette AT DEVICE DENSITY (a bilinear/NN palette match snaps back to the same
# ~11 sky entries = the banding).  The kernel phase is quantised to MON_PHASES per tap window; the
# weights are integers summing to 256 (remainder into the largest tap), the horizontal pass keeps
# 12-bit signed intermediates (Lanczos lobes ring negative) and the vertical pass diffuses the error
# in 1/16 units (7/16 right, 3/16 - 5/16 - 1/16 below).  Palette LUT = 15-bit RGB -> nearest palette
# index by squared distance over the expanded 8-bit channels, NEVER index 9 (the transparency key).
MON_TAPS = 6
MON_PHASES = 64
MON_KEY = 9
MON_MAX_DW = 8192


def _lanczos3(x: float) -> float:
    ax = abs(x)
    if ax >= 3.0:
        return 0.0
    if ax < 1e-9:
        return 1.0
    px = math.pi * x
    return 3.0 * math.sin(px) * math.sin(px / 3.0) / (px * px)


def mon_phase_weights(phases: int = MON_PHASES) -> List[Tuple[int, ...]]:
    """phases x MON_TAPS integer weights (sum 256): phase q stands for the fractional offset
    f = (q + 0.5)/phases of the sample centre c inside its source cell; tap t sits at floor(c) - 2 + t."""
    out = []
    for q in range(phases):
        f = (q + 0.5) / phases
        w = [_lanczos3(f + 2 - t) for t in range(MON_TAPS)]
        sm = sum(w)
        iw = [int(math.floor(256.0 * v / sm + 0.5)) for v in w]
        imax = max(range(MON_TAPS), key=lambda t: (abs(iw[t]), -t))
        iw[imax] += 256 - sum(iw)
        out.append(tuple(iw))
    return out


def mon_axis_taps(n_src: int, n_dst: int, phases: int = MON_PHASES) -> List[Tuple[Tuple[int, ...], int]]:
    """Per output index i: (clamped source indices of the 6 taps, phase q).  c = (i+0.5)*n_src/n_dst - 0.5,
    c64 = floor(c*phases) computed as ((2i+1)*(phases/2)*n_src + (phases/2)*n_dst) // n_dst - phases
    (a non-negative integer division: the asm's one udiv per column/row)."""
    half = phases >> 1
    out = []
    for i in range(n_dst):
        c64 = ((2 * i + 1) * half * n_src + half * n_dst) // n_dst - phases
        ci = c64 >> 6 if phases == 64 else c64 // phases
        q = c64 & (phases - 1)
        base = ci - 2
        idx = tuple(min(n_src - 1, max(0, base + t)) for t in range(MON_TAPS))
        out.append((idx, q))
    return out


def mon_nearest_lut(pal: bytes, lo: int = 0, hi: int = 256) -> List[int]:
    """32768-entry 15-bit RGB -> nearest palette index (RGBQUAD table b,g,r,x; strict < argmin over
    k in [lo, hi), first k wins ties, key 9 skipped).  The default [0, 256) is the Monument / Hall of
    Fame search.  A caller whose source occupies only a sub-range of the table passes that range so
    ringing never resolves to entries the source does not own (the splash: SPLASH_PAL_LO/HI)."""
    lut = []
    for i in range(1 << 15):
        r5, g5, b5 = (i >> 10) & 31, (i >> 5) & 31, i & 31
        r, g, b = (r5 << 3) | (r5 >> 2), (g5 << 3) | (g5 >> 2), (b5 << 3) | (b5 >> 2)
        best, bd = lo, 1 << 30
        for k in range(lo, hi):
            if k == MON_KEY:
                continue
            db, dg, dr = pal[k * 4] - b, pal[k * 4 + 1] - g, pal[k * 4 + 2] - r
            d = dr * dr + dg * dg + db * db
            if d < bd:
                bd, best = d, k
        lut.append(best)
    return lut


def mon_resample(src, s_pitch: int, sx: int, sy: int, sw: int, sh: int, pal: bytes,
                 dst, d_pitch: int, d_w: int, d_h: int, dx: int, dy: int, dw: int, dh: int,
                 lut: List[int], dither: bool = True) -> None:
    """Reference of the baked resampler (mon_resample in assemble_mon.py).  src/dst are bytearrays of
    8-bit indices with the given pitches; both index the SAME table `pal` (the dest canvas's synced
    DIB table -- the engine remaps every asset into the game palette on load; a Buffer_init'd
    scratch's own table is an identity ramp and must never be used).  Writes only inside the dest."""
    if sw <= 0 or sh <= 0 or dw <= 0 or dh <= 0 or dw > MON_MAX_DW:
        return
    W = mon_phase_weights()
    cols = mon_axis_taps(sw, dw)
    rows = mon_axis_taps(sh, dh)
    hcache: dict = {}

    def hrow(r: int) -> List[int]:
        o = hcache.get(r)
        if o is None:
            base = (sy + r) * s_pitch + sx
            o = []
            for idx, q in cols:
                wq = W[q]
                ab = ag = ar = 0
                for t in range(MON_TAPS):
                    p = src[base + idx[t]] * 4
                    ab += pal[p] * wq[t]
                    ag += pal[p + 1] * wq[t]
                    ar += pal[p + 2] * wq[t]
                o += [ab >> 4, ag >> 4, ar >> 4]
            hcache[r] = o
        return o

    ew = dw + 2
    e0 = [0] * (ew * 3)
    e1 = [0] * (ew * 3)
    x0, y0 = max(dx, 0), max(dy, 0)
    x1, y1 = min(dx + dw, d_w), min(dy + dh, d_h)
    for j in range(dh):
        y = dy + j
        ridx, rq = rows[j]
        wq = W[rq]
        taps = [hrow(ridx[t]) for t in range(MON_TAPS)]
        for i in range(ew * 3):
            e1[i] = 0
        for i in range(dw):
            x = dx + i
            v = [0, 0, 0]
            for c in range(3):
                acc = 0
                for t in range(MON_TAPS):
                    acc += taps[t][i * 3 + c] * wq[t]
                a = acc >> 12
                if dither:
                    a += e0[(i + 1) * 3 + c] >> 4
                v[c] = 0 if a < 0 else 255 if a > 255 else a
            b, g, r = v
            idx = lut[((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)]
            if y0 <= y < y1 and x0 <= x < x1:
                dst[y * d_pitch + x] = idx
            if dither:
                for c in range(3):
                    d = v[c] - pal[idx * 4 + c]
                    e0[(i + 2) * 3 + c] += d * 7
                    e1[i * 3 + c] += d * 3
                    e1[(i + 1) * 3 + c] += d * 5
                    e1[(i + 2) * 3 + c] += d
        e0, e1 = e1, e0


# ---- the blue plaque panel: regenerated scanlines --------------------------------------------------
# The near-view text panel (monzoom1/2.pcx rows ~127..174) is a 1-px light/dark scanline dither on a
# perspective trapezoid.  Resampling it bands (dither invariant) -> after the backdrop enlarge the
# panel rows are REGENERATED at device density: light rows (the panel's dominant index) hN of every P
# device rows, the dark rows NN from the matching native dark row, per light row's own column extent.
# The stripe (P, hN = mon_stripe) and the GEOMETRY are separate maps since 2026-10-04: device row y belongs to
# native row pair k = ((y - Y0) * 8) // num (a pair is 2 native rows = num/8 device rows) for the trapezoid's
# column extent and the dark row's source, whatever the stripe thickness.
# Detection is PALETTE-INDEPENDENT and per draw (the engine remaps the pcx on load: the art's index
# 230 is 240 at runtime): a light row = a source row where ONE index covers >= MON_PANEL_MIN px; the
# panel = the longest run of such rows spaced exactly 2 apart sharing that index, whose in-between rows
# carry < MON_PANEL_GAP px of it (a solid keyed block has every row uniform and must not match).
MON_PANEL_MIN = 300
MON_PANEL_GAP = 100
MON_PANEL_MIN_ROWS = 4


def mon_panel_rows(src, s_pitch: int, sw: int, sh: int):
    """(light_idx, ny0, count) of the detected panel or None: rows ny0, ny0+2, ... (count of them),
    light index light_idx.  Ties in a row's histogram resolve to the LOWEST index (first strict max)."""
    dom = []
    for y in range(sh):
        row = src[y * s_pitch:y * s_pitch + sw]
        cnt = [0] * 256
        for v in row:
            cnt[v] += 1
        bi = 0
        for i in range(1, 256):
            if cnt[i] > cnt[bi]:
                bi = i
        dom.append(bi if cnt[bi] >= MON_PANEL_MIN else -1)

    def between_ok(j: int, idx: int) -> bool:
        row = src[(j + 1) * s_pitch:(j + 1) * s_pitch + sw]
        return sum(1 for v in row if v == idx) < MON_PANEL_GAP

    best = (0, -1, -1)
    for i in range(sh):
        if dom[i] < 0:
            continue
        n, j = 1, i
        while j + 2 < sh and dom[j + 2] == dom[i] and between_ok(j, dom[i]):
            n += 1
            j += 2
        if n > best[0]:
            best = (n, i, dom[i])
    if best[0] < MON_PANEL_MIN_ROWS:
        return None
    return best[2], best[1], best[0]


def mon_row_extent(src, s_pitch: int, sw: int, y: int, idx: int) -> Tuple[int, int]:
    """(lo, hi) first/last column of idx on source row y."""
    row = src[y * s_pitch:y * s_pitch + sw]
    lo, hi = sw, -1
    for x in range(sw):
        if row[x] == idx:
            if x < lo:
                lo = x
            hi = x
    return lo, hi


def mon_panel_synth(src, s_pitch: int, sw: int, sh: int, dst, d_pitch: int, d_w: int, d_h: int,
                    dx: int, dy: int, num: int) -> Optional[Tuple[int, int, int, int]]:
    """Regenerate the panel scanlines into dst (the enlarged backdrop placed at dx,dy): returns
    (Y0, Y1, P, hN) or None when no panel was found."""
    found = mon_panel_rows(src, s_pitch, sw, sh)
    if found is None:
        return None
    light, ny0, n = found
    ny1 = ny0 + 2 * n
    P, hN = mon_stripe(num)
    Y0, Y1 = dy + mon_s(ny0, num), dy + mon_s(ny1, num)
    for y in range(Y0, Y1):
        if y < 0 or y >= d_h:
            continue
        k = min(n - 1, ((y - Y0) * 8) // num)
        ph = (y - Y0) % P
        ly = ny0 + 2 * k
        lo, hi = mon_row_extent(src, s_pitch, sw, ly, light)
        X0, X1 = dx + mon_s(lo, num), dx + mon_s(hi + 1, num)
        w = X1 - X0
        if w <= 0:
            continue
        xs, xe = max(0, X0), min(d_w, X1)
        if ph < hN:
            for x in range(xs, xe):
                dst[y * d_pitch + x] = light
        else:
            nd = min(ny1 - 1, ly + 1)
            span = hi + 1 - lo
            for x in range(xs, xe):
                i = x - X0
                dst[y * d_pitch + x] = src[nd * s_pitch + min(sw - 1, lo + (i * span) // w)]
    return Y0, Y1, P, hN


# ---- CLOSE / BACK faces: restripe at composite time -------------------------------------------------
# The bevel face is a 1-px red/black scanline dither; the 2dzoom chain's NN enlarge beats it into
# 2/3-px runs.  At Buffer_draw_2 entry with src == a Monument button canvas (EVERY face path by
# construction: sprite states, the tiled bevel fill of the idle face, focus rings) the pair is detected
# PER DRAW from the canvas's middle column (>= 6 runs alternating between exactly two indices, every run
# <= P+1 rows) and every pixel of the pair is rewritten to the P-law stripe.  Phase law: a FIXED member on
# top (mon_face_top) -- reading the phase off the canvas flashed at 1600x1200 because the engine re-tiles
# the idle fill between composites with a shifting phase.  num <= 16 -> untouched; num 17..21 restripes at
# P = 2 (1-row stripes: the NN enlarge leaves a beat of doubled rows there -- user's 1600x900 Hall of Fame
# CLOSE, 2026-10-04).
MON_FACE_MIN_RUNS = 6


def mon_face_pair(column: List[int], P: int) -> Optional[Tuple[int, int]]:
    """(a, b) of the best alternating chain in a canvas column (a = the chain's first member) or None."""
    if not column:
        return None
    runs = []
    cur, ln = column[0], 1
    for v in column[1:]:
        if v == cur:
            ln += 1
        else:
            runs.append((cur, ln))
            cur, ln = v, 1
    runs.append((cur, ln))
    best, best_len = None, 0
    for i in range(len(runs)):
        j, pa, pb = i, runs[i][0], -1
        while j < len(runs) and runs[j][1] <= P + 1:
            v = runs[j][0]
            if v != pa:
                if pb < 0:
                    pb = v
                elif v != pb:
                    break
            j += 1
        if pb >= 0 and j - i >= MON_FACE_MIN_RUNS and j - i > best_len:
            best, best_len = (pa, pb), j - i
    return best


def mon_luma(pal: bytes, i: int) -> int:
    """RGBQUAD (b,g,r) luma x1000: b*114 + g*587 + r*299."""
    return pal[i * 4] * 114 + pal[i * 4 + 1] * 587 + pal[i * 4 + 2] * 299


def mon_face_top(a: int, b: int, pal: bytes) -> int:
    """The BRIGHTER member goes on the stripe-top rows (the grid's first T rows); ties -> a.  Both members
    are T rows since 2026-10-04 (even P); the choice only fixes the phase, as on the popups (coloured member
    first) and the HOF pair law (hof_pair_top)."""
    return a if mon_luma(pal, a) >= mon_luma(pal, b) else b


def mon_face_restripe(buf, pitch: int, w: int, h: int, pal: bytes, num: int) -> Optional[Tuple[int, int, int]]:
    """Restripe a button canvas in place; returns (a, b, top) or None (no pair / P <= 2)."""
    P, hN = mon_stripe(num)
    if num <= NATIVE_G or w <= 0 or h <= 0:
        return None
    x = w >> 1
    pair = mon_face_pair([buf[y * pitch + x] for y in range(h)], P)
    if pair is None:
        return None
    a, b = pair
    top = mon_face_top(a, b, pal)
    bot = b if top == a else a
    for y in range(h):
        c = top if (y % P) < hN else bot
        base = y * pitch
        for i in range(w):
            v = buf[base + i]
            if v == a or v == b:
                buf[base + i] = c
    return a, b, top


# ==========================================================================
# HALL OF FAME (F10; FameWin 0x74DAF8) -- full-height 4:3 letterbox
# ==========================================================================
# User decision 2026-09-13: the Hall of Fame gets the Monument's look: the
# engine's 1024x768 layout scaled UNIFORMLY to the screen height, centred,
# black letterbox at the sides.  Same scale source as the Monument
# (mon_scale_num: min(floor(16*ScreenH/768), floor(16*ScreenW/1024)) over den 16) with ONE extra clamp:
# the painter positions its crest / band / titles / rows from imm8 literals
# (rewritten in place by the DL walker, 1-byte stores), the largest being
# 0x1C (the TOP 5 title x inset); half_down(0x1C*num) stays a signed byte
# only up to num 72 (ScreenH 3456) -- above that the art is letterboxed on
# all four sides instead of overflowing a byte.  Armed only in the wide
# layout (0x8A4168) with num > 16; everything else is the native path.
# Every geometry value = vanilla x num/16 through half_down (mon_s); the
# button CELLS use floor (fl) because the face scaler's output is floor.
# Bake: assemble_mon.py (shares the Monument's cave block: resampler, face
# restripe, gate); parity tests/test_hof_asm_parity.py; laws tests/test_scaling_hof.py.

HOF_NUM_MAX = 72
HOF_ORG_X, HOF_ORG_Y = 0x77, 0x50                      # content origin in the wide layout (load_hoficons +0xA14/+0xA18)
HOF_CONTENT_NATIVE = (0x77, 0x50, 0x77 + 800, 0x50 + 600)   # FameWin +0xA24..+0xA30
HOF_RECT_LITERALS = (                                   # load_hoficons' 24 imm32 (content-relative), table +0xB42C
    (0x1E, 0x10E, 0x123, 0x147),    # 0 TOP 5 SCORES panel
    (0x12F, 0x10D, 0x21D, 0x183),   # 1 WORLD MAP picture (238x118)
    (0x228, 0x10D, 0x2FA, 0x21F),   # 2 SCORE ANALYSIS panel
    (0x15, 0x7B, 0x303, 0xED),      # 3 faction button row (7 x 0x46 cells)
    (0x4C, 0x27, 0x2D4, 0x77),      # 4 category button row (6 x 0x4F cells)
    (0x128, 0x187, 0x224, 0x248),   # 5 faction picture (233x124)
)
HOF_RECTS_NATIVE = tuple((l + HOF_ORG_X, t + HOF_ORG_Y, r + HOF_ORG_X, b + HOF_ORG_Y) for l, t, r, b in HOF_RECT_LITERALS)
HOF_MAP_NATIVE = (HOF_RECT_LITERALS[1][2] - HOF_RECT_LITERALS[1][0], HOF_RECT_LITERALS[1][3] - HOF_RECT_LITERALS[1][1])   # 238x118
HOF_CAT_N, HOF_CAT_CELL, HOF_CAT_RECT = 6, 0x4F, 4          # 6 category BaseButtons, 79-px cells, over rect 4
HOF_FAC_N, HOF_FAC_CELL, HOF_FAC_RECT = 7, 0x46, 3          # 7 faction BaseButtons, 70-px cells, over rect 3
HOF_CLOSE_NATIVE = (0x22A, 0x22C, 0xCE, 0x16)               # CLOSE FlatButton (x, y, w, h), CONTENT-relative
HOF_FONTS = (14, 16, 22)                                    # painter fonts: [0x8A40C8] f14 body, [0x8A40D4] f16 panel titles, [0x8A40EC] f22 band
HOF_FONT_TABLE_MAX = 40                                     # find_font's largest pool size; above it a Font_init'd scratch Font
HOF_FONT_SCRATCH_STYLE = 1                                  # the pool's style for a >12 native at variant 0 = Arial Narrow BOLD (font_pool_face; v1 pushed 0 = bold drop)
HOF_FONT_LABEL = 14                                         # CLOSE label font 0x6E84B4 = 14 bold


def hof_scale_num(screen_w: int, screen_h: int) -> int:
    """The Hall of Fame's scale numerator over den 16: the Monument's law (min of both axes,
    mon_scale_num) clamped to HOF_NUM_MAX (the imm8 painter literals)."""
    return min(mon_scale_num(screen_w, screen_h), HOF_NUM_MAX)


def hof_armed(screen_w: int, screen_h: int, wide: int) -> bool:
    return bool(wide) and hof_scale_num(screen_w, screen_h) > NATIVE_G


def hof_letterbox(screen_w: int, screen_h: int, num: int) -> Tuple[int, int]:
    """(LX, LY): the scaled 1024x768 art centred on the screen (>> 1 floors, as the Monument)."""
    return mon_letterbox(screen_w, screen_h, num)


def hof_origin(num: int, lx: int, ly: int) -> Tuple[int, int]:
    """(OX, OY) = letterbox + s(119|80): the device content origin every content-relative literal adds to."""
    return lx + mon_s(HOF_ORG_X, num), ly + mon_s(HOF_ORG_Y, num)


def hof_rect(r: Tuple[int, int, int, int], num: int, lx: int, ly: int) -> Tuple[int, int, int, int]:
    """A window-space rect authored as content-relative + (119,80): dev = origin + s(native - 119|80),
    each literal scaled independently (the Monument's mon_rect with the HOF origin)."""
    ox, oy = hof_origin(num, lx, ly)
    return (ox + mon_s(r[0] - HOF_ORG_X, num), oy + mon_s(r[1] - HOF_ORG_Y, num),
            ox + mon_s(r[2] - HOF_ORG_X, num), oy + mon_s(r[3] - HOF_ORG_Y, num))


def hof_rects(num: int, lx: int, ly: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """FameWin +0xB42C: the 6 rects re-derived from the literals (the builder's table is REBUILT from
    constants, not rescaled from its in-memory values)."""
    return tuple(hof_rect(r, num, lx, ly) for r in HOF_RECTS_NATIVE)


def hof_content_rect(num: int, lx: int, ly: int) -> Tuple[int, int, int, int]:
    """FameWin +0xA24: (LX + s(119), LY + s(80), LX + s(919), LY + s(680))."""
    l, t, r, b = HOF_CONTENT_NATIVE
    return (lx + mon_s(l, num), ly + mon_s(t, num), lx + mon_s(r, num), ly + mon_s(b, num))


def hof_close_rect(num: int, lx: int, ly: int) -> Tuple[int, int, int, int]:
    """(x, y, w, h) of CLOSE: (OX + s(0x22A), OY + s(0x22C), s(0xCE), s(0x16)) -- the builder adds its
    literals to the CONTENT origin (+0xA24/+0xA28), unlike the Monument's window-local buttons."""
    ox, oy = hof_origin(num, lx, ly)
    x, y, w, h = HOF_CLOSE_NATIVE
    return (ox + mon_s(x, num), oy + mon_s(y, num), mon_s(w, num), mon_s(h, num))


def hof_button_size(cell: int, num: int) -> int:
    """Side of an icon button's square window: floor(cell*num/16) = the parity-NN face scaler's output
    (dstW = srcW*num/den, floor), so the 79x79 / 70x70 face fills its canvas exactly."""
    return (cell * num) // NATIVE_G


def hof_button_offsets(n: int, rect_nat: Tuple[int, int, int, int], cell: int) -> Tuple[int, int, int]:
    """(pitch, x0, y0) of the builder's NATIVE icon layout over its native row rect: pitch = (R-L)/n, the
    face at (pitch - cell)/2 into its pitch and ((B-T) - cell)/2 into the row (integer division: the odd
    spare row goes to the BOTTOM -- the category faces sit at rows 119..197 with the art's separator line
    on row 198)."""
    L, T, R, B = rect_nat
    pitch = (R - L) // n
    return pitch, (pitch - cell) // 2, ((B - T) - cell) // 2


def hof_button_rect(i: int, n: int, rect_nat: Tuple[int, int, int, int], cell: int, num: int, lx: int, ly: int) -> Tuple[int, int, int, int]:
    """(x, y, w, h) of icon button i of n: the row rect's device origin + s(native offsets), size at
    hof_button_size.  The centring is done NATIVELY and scaled (v5): centring the scaled face in the scaled
    row split the 2-3 spare device rows top/bottom and dropped the button's bottom row onto the art's
    separator line at 1600x1200 (the line vanished under every category button); scaling the native
    offsets keeps the spare rows below the face exactly like vanilla.  Identity to load_hoficons at num == 16."""
    pitch, x0, y0 = hof_button_offsets(n, rect_nat, cell)
    L, T, _r, _b = hof_rect(rect_nat, num, lx, ly)
    size = hof_button_size(cell, num)
    return (L + mon_s(x0 + i * pitch, num), T + mon_s(y0, num), size, size)


def hof_button_rects(num: int, lx: int, ly: int) -> Tuple[Tuple[int, int, int, int], ...]:
    """The 13 icon buttons: 6 category (rect 4, 0x4F) then 7 faction (rect 3, 0x46)."""
    cat = [hof_button_rect(i, HOF_CAT_N, HOF_RECTS_NATIVE[HOF_CAT_RECT], HOF_CAT_CELL, num, lx, ly) for i in range(HOF_CAT_N)]
    fac = [hof_button_rect(i, HOF_FAC_N, HOF_RECTS_NATIVE[HOF_FAC_RECT], HOF_FAC_CELL, num, lx, ly) for i in range(HOF_FAC_N)]
    return tuple(cat + fac)


def hof_font_size(native: int, num: int) -> int:
    """Nominal size handed to find_font / Font_init: floor(native*num/16) (the Monument's law)."""
    return mon_font_size(native, num)


def hof_font_scratch(native: int, num: int) -> bool:
    """True when the nominal exceeds find_font's 40-px pool -> a Font_init'd scratch Font (f22 -> 61 @4K)."""
    return hof_font_size(native, num) > HOF_FONT_TABLE_MAX


def hof_line_height(pad: int, cell: int, cap: int) -> int:
    """FameWin +0xA44 (the score/TOP 5 row pitch) from the body Font's fields exactly as load_hoficons
    reads them: pad (+0) < 0 -> cell (+0xC), else cap_height (+0x10) + pad."""
    return cell if pad < 0 else cap + pad


def hof_face_origin(canvas_w: int, canvas_h: int, sprite_w: int, sprite_h: int, num: int) -> Tuple[int, int]:
    """Where the state sprite's scaled face lands in an icon button canvas: FlatButton_content_draw centres
    the NATIVE sprite ((W - w)/2, (H - h)/2, H negative in +0x4C8); the scaled draw is centred on the scaled
    face instead ((W - fl(w))/2, (H - fl(h))/2, sar) = t_rw_iconblit's recentre law.  0,0 when the face is
    the cell (79 in 79)."""
    fw, fh = (sprite_w * num) // NATIVE_G, (sprite_h * num) // NATIVE_G
    return (canvas_w - fw) >> 1, ((-canvas_h) - fh) >> 1


# The parity enlarge's horizontal blend snaps to palette_nearest EXCLUDING only the blit's key: a
# keyless blit (key 0x100, HOF v1..v3) let index 9 (RGB 9,0,0 = the transparency key) win for the
# orange-into-black blends along the box frames -> holes showing the game map behind the window on
# the black stripe rows (user 4K shots 2026-09-14).  Every HOF parity blit therefore passes key 9:
# hof.pcx carries no pcx index 255 (runtime 9), so no real texel goes transparent; the world-map
# dump is a runtime canvas capture that MAY hold literal 9s, so its private scratch is remapped
# 9 -> HOF_BLACK_INDEX (hof.pcx's dark stripe member 55 + 10, rendered (0,0,0)) before the blit.
HOF_BLIT_KEY = MON_KEY
HOF_BLACK_INDEX = 65


def hof_map_source_fix(src: bytearray, pitch: int, sx: int, sy: int, sw: int, sh: int) -> int:
    """Remap every literal key texel of the world-map dump's blit rect to black; returns the count."""
    n = 0
    for y in range(sy, sy + sh):
        base = y * pitch
        for x in range(sx, sx + sw):
            if src[base + x] == HOF_BLIT_KEY:
                src[base + x] = HOF_BLACK_INDEX
                n += 1
    return n


# ---- HOF v6: NN enlarge + pair-only restripe (the parity NN dropped single-row chrome) -------------------
# The parity-preserving NN picks, for every device row, the native row of the parity the device stripe phase
# demands (|shift| <= 1).  Right for period-2 dither, wrong for hof.pcx / hoficons: their 1-px frame strokes,
# corner chamfers and separator lines are single rows of EITHER parity, and at 22/16 (P=3: one parity gets
# 1 device row in 3) or 25/16 a row of the minority parity is skipped entirely (user 1080p 2026-09-14: the
# world-map box's bottom stroke gone, corners malformed).  v6 enlarges with the edge-safe, centre-sampled NN
# (every native row/column lands on >= 1 device row/column) and regenerates ONLY the dither pairs: a texel
# whose two vertical neighbours are both the same other index is one member of a row pair (a/b/a), and the
# device pixel takes the pair's WIDE member on the wide stripe phase (stripe_top over the device grid, hN of
# P rows) and the other member on the rest -- identical to the parity NN for period-2 fields, identity for
# every other texel.  The wide member is the BRIGHTER one (luma over the dest table): the popups' navy-wide
# duty, and at P=3 it keeps a two-purple glyph light and a red/dark bevel red instead of two-thirds dark
# (the user's 1080p "black specks" / "top red rows missing").
HOF_PAIR_MIN_LUMA_DELTA = 0
# v7 (2026-10-11): hof.pcx's own scanline field -- pcx 55 (0,0,0) / 187 (11,18,24) + the 10-entry palette offset.
# The chain test cannot see a field run squeezed between two strokes (the CLOSE slot's 'channels': 2 native rows
# between the outer and inner red frame, and between the inner frame and the button), so those rows fell to plain
# NN and came out as 1-row / 3-row runs on a 2-row grid.  For the hof.pcx backdrop a texel of THIS pair whose
# vertical neighbour is its mate is a pair member too: the field reads as one continuous T-row scanline on the
# dest grid passing behind every stroke (as the pcx draws it: the 55/187 row parity runs straight across them).
HOF_FIELD_PAIR = (65, 197)


def hof_pair_top(a: int, b: int, pal: bytes) -> int:
    """The WIDE (stripe-top) member of a row pair: the brighter by luma; ties -> the lower index."""
    la, lb = mon_luma(pal, a), mon_luma(pal, b)
    if la == lb:
        return min(a, b)
    return a if la > lb else b


def hof_pair_texel(src, pitch: int, sx: int, sy: int, sh_top: int, sh_bot: int, key: int, field=None):
    """(a, mate) for the texel at (sx, sy) of a source whose valid rows are [sh_top, sh_bot): mate = the
    neighbour b on a side where the column reads a/b/a/b from the texel outward (three rows beyond it, either
    side).  A lone 1-px stroke between two field rows never qualifies (two rows out it meets the field's other
    member, not itself); a field row next to a stroke qualifies through its other side.  A key texel is never
    a pair member and a chain through the key is not a chain.  `field` = the source's own field pair (A, B)
    (HOF_FIELD_PAIR for hof.pcx, None elsewhere): when no chain qualifies, a texel of that pair whose vertical
    neighbour (up first, inside the valid rows) is its mate is a member -- a 2-row channel between strokes."""
    a = src[sy * pitch + sx]
    if a == key:
        return a, None
    for d in (-1, 1):                                   # v2: a ONE-SIDED chain b/a/b beyond the texel qualifies
        y3 = sy + 3 * d                                 # (a field row next to a stroke has unequal neighbours yet
        if not (sh_top <= y3 < sh_bot):                 # continues the pair on its other side); a lone stroke
            continue                                    # between two field rows never sees its own index 2 rows away
        n1 = src[(sy + d) * pitch + sx]
        if n1 == a or n1 == key:
            continue
        if src[(sy + 2 * d) * pitch + sx] == a and src[y3 * pitch + sx] == n1:
            return a, n1
    if field is not None and a in field:
        m = field[0] + field[1] - a
        for d in (-1, 1):
            if sh_top <= sy + d < sh_bot and src[(sy + d) * pitch + sx] == m:
                return a, m
    return a, None


def hof_pair_enlarge(src, pitch: int, sx: int, sy: int, sw: int, sh: int, pal: bytes, num: int,
                     dst, d_pitch: int, d_w: int, d_h: int, dx: int, dy: int, y_abs0: int, key: int,
                     field=None) -> Tuple[int, int]:
    """Enlarge the source rect to (dx, dy) at num/16 into dst (clipped to d_w x d_h); returns (dw, dh).
    Rows/cols: nn_center_index (edge-clamped).  Pair texels restriped by the device phase of the absolute row
    y_abs0 + dy_dest (y_abs0 = the dest window's y in its parent, the shared phase grid).  Key texels skipped.
    `field`: hof_pair_texel's field pair (HOF_FIELD_PAIR for the hof.pcx backdrop only)."""
    dw, dh = (sw * num) // NATIVE_G, (sh * num) // NATIVE_G
    P, hN = mon_stripe(num)
    for j in range(dh):
        yy = dy + j
        if yy < 0 or yy >= d_h:
            continue
        srow = sy + nn_center_index(j, dh, sh)
        wide = ((y_abs0 + yy) % P) < hN
        for i in range(dw):
            xx = dx + i
            if xx < 0 or xx >= d_w:
                continue
            scol = sx + nn_center_index(i, dw, sw)
            a, mate = hof_pair_texel(src, pitch, scol, srow, sy, sy + sh, key, field)
            if a == key:
                continue
            if mate is not None:
                top = hof_pair_top(a, mate, pal)
                a = top if wide else (mate if top == a else a)
            dst[yy * d_pitch + xx] = a
    return dw, dh


# ==========================================================================
# FONT FACE / WEIGHT LAW (2026-09-17; brief work\FONT_FACE_WEIGHT_AUDIT.md)
# The engine's find_font pool (config_popups 0x588BB0..0x588BFD) keys the FACE and the
# WEIGHT on the NATIVE size: every pool font above 12 px is "Arial Narrow" and bold for
# variants 0 and 1 alike (variant 2 = bold-italic); 12 px and below is plain "Arial" with
# the weight = the variant.  Scaling a <=12 native by asking the pool for the SCALED size
# silently crosses that boundary (Arial regular -> Arial Narrow bold at every g >= 18).
# The law: derive name and style from the NATIVE size and variant, then size = fl(S*num/16)
# (identity at num <= 16).  Ports: work\scripts\assemble_fontlaw.py (t_ffn / t_ffn_num /
# t_ffn_at / t_fdirect_at); parity tests\test_fontlaw_asm_parity.py.
# ==========================================================================
FONT_POOL_SIZES = (40, 36, 32, 24, 22, 20, 18, 16, 14, 12, 10, 8)   # font_size_table @0x68F220
FONT_VARIANT_FLAGS = (0, 1, 2, 4)                                   # font_variant_flags @0x68F250
FONT_POOL_SMALL_MAX = 12         # pool face boundary: size > 12 -> "Arial Narrow" + bold
FONT_POOL_MAX = 40               # the largest pool size; above it a Font_init'd cave Font
FONT_NAME_ARIAL, FONT_NAME_NARROW = "Arial", "Arial Narrow"
# The (native, variant) pool keys that reach a cave slot at some g > 16: every <=12 key the
# patch set scales, plus the >12 keys whose fl(S*40/16) exceeds the 40-px pool at 4K.
FONT_LAW_SLOT_KEYS = ((10, 0), (11, 0), (12, 0), (12, 1), (12, 2),
                      (14, 0), (14, 1), (14, 2), (16, 0), (16, 1), (16, 2),
                      (18, 2), (22, 0), (26, 0), (32, 0))
FONT_LAW_SLOT_STRIDE = 0x30      # Font object 0x28 + num @+0x28 + key (S | style<<8 | narrow<<16) @+0x2C


def find_font_snap(size: int) -> int:
    """find_font's own size resolution (0x588304..0x588324): the pool size with the smallest
    |table - size|; an exact tie resolves to the FIRST table entry = the LARGER size."""
    best, best_d = FONT_POOL_SIZES[0], None
    for t in FONT_POOL_SIZES:
        d = abs(t - size)
        if best_d is None or d < best_d:
            best, best_d = t, d
    return best


def font_pool_face(native: int, variant: int) -> Tuple[str, int]:
    """(name, style) the pool gives a NATIVE (size, variant): the config_popups law."""
    narrow = native > FONT_POOL_SMALL_MAX
    return (FONT_NAME_NARROW if narrow else FONT_NAME_ARIAL,
            (1 if narrow else 0) | FONT_VARIANT_FLAGS[variant])


def font_scaled_size(native: int, num: int) -> int:
    """Nominal size at num/16: fl(native*num/16) (rw_font_nominal / mon_font_size), native at num<=16."""
    return native if num <= NATIVE_G else (native * num) // NATIVE_G


def font_face_law(native: int, variant: int, num: int) -> Tuple:
    """The face-preserving replacement for find_font(fl(S*num/16), v):
      num <= 16                     -> ('pool', S, v)           (the vanilla lookup, native no-op)
      S > 12 and fl(S*num/16) <= 40 -> ('pool', n, v)           (the pool already gives Narrow+bold)
      else                          -> ('init', name, n, style) (Font_init on a cave slot keyed (S,v))
    where (name, style) = font_pool_face(S, v) and n = fl(S*num/16)."""
    if num <= NATIVE_G:
        return ("pool", native, variant)
    n = font_scaled_size(native, num)
    if native > FONT_POOL_SMALL_MAX and n <= FONT_POOL_MAX:
        return ("pool", n, variant)
    name, style = font_pool_face(native, variant)
    return ("init", name, n, style)


def font_face_law_font(native: int, variant: int, num: int) -> Tuple[str, int, int]:
    """(name, size, style) the player actually sees under font_face_law (pool sizes snapped)."""
    r = font_face_law(native, variant, num)
    if r[0] == "pool":
        name, style = font_pool_face(find_font_snap(r[1]), r[2])
        return (name, find_font_snap(r[1]), style)
    return (r[1], r[2], r[3])


def font_direct_law(native: int, style: int, num: int) -> Tuple[str, int, int]:
    """A font vanilla Font_init's DIRECTLY (not through the pool, e.g. the button label font
    0x6E84B4 = Font_init("Arial", 14, 1)): keep its own name and style, scale only the size."""
    return (FONT_NAME_ARIAL, font_scaled_size(native, num), style)


def font_law_slot_key(native: int, style: int, narrow: bool) -> int:
    """The idempotence key a cave slot stores at +0x2C: S | style<<8 | narrow<<16."""
    return native | (style << 8) | ((1 if narrow else 0) << 16)


def font_law_slot_index(native: int, variant: int) -> Optional[int]:
    """Which shared slot a pool (S, v) key uses; None -> no slot (the port falls back to the pool)."""
    try:
        return FONT_LAW_SLOT_KEYS.index((native, variant))
    except ValueError:
        return None


# ---- the engine's button-label fonts (probe hook_btnfont_probe.js, 1024x768, 2026-09-17) ----------
# The static default label Font 0x7D3948 is Font_init'd "Times New Roman" 12 regular by its ctor and then
# RE-inited "Arial" 12 regular during startup, before config_popups' pool; GetObject on a live COUNCIL
# button's +0x970 (= 0x7D3948) reads Arial -12 weight 0.  The PrefWin buttons' +0x970 is the shared
# 0x6E84B4 = Font_init("Arial", 14, 1); the HUD M/I buttons' +0x970 is 0x7CFE8C = Arial 14 bold.
BUTTON_DEFAULT_FONT = (12, 0)      # (native size, pool variant) of the default FlatButton label font -> t_ffn(12, 0)
BUTTON_SHARED_A14B = (14, 1)       # the Font_init("Arial", 14, 1) family (0x6E84B4, 0x7CFE8C) -> t_fdirect_a14b()


def button_default_font_law(g: int) -> Tuple[str, int, int]:
    """What the COUNCIL/MP-time, scenario-diplo and TutWin TOUR/Close labels draw with at g: the pool face
    law for the native (12, 0) = Arial fl(12g/16) regular (Arial 12 regular at g <= 16)."""
    return font_face_law_font(*BUTTON_DEFAULT_FONT, g)


def button_a14b_font_law(g: int) -> Tuple[str, int, int]:
    """What the PrefWin / BaseWin / HUD M-I / HQ-console labels draw with at g: Arial fl(14g/16) bold."""
    return font_direct_law(BUTTON_SHARED_A14B[0], BUTTON_SHARED_A14B[1], g)


# ---- SocialWin button-label fit (2026-09-17; port t_se_labelfit in assemble_fontlaw.py) -------------
SE_LABEL_FONT_NATIVE = 14      # SocialWin fonts[1] = Font_init("Arial", 14, 1): the model/faction/row-button label font
SE_LABEL_FONT_MIN = 8
SE_LABEL_SLACK = 6             # FlatButton_content_draw ellipsises when Font_width(label) > (R - L) - 6


def se_label_fit(g: int, labels_fit) -> int:
    """The label Font's size after SocialWin_build at g: start at fl(14*g/16) (the se_font_size law)
    and step down by 1 until labels_fit(size) is true or the size reaches SE_LABEL_FONT_MIN.
    labels_fit(size) = every button drawn with that Font has Font_width(label) <= (button w - 6).
    Vanilla sits at ZERO slack ("THOUGHT CONTROL" 140 px vs 146 - 6 at 1024x768) so GDI's per-size
    advance rounding can push a proportionate size over by a pixel (19 -> 195 > 194 at 1920x1080);
    the engine's own base-name loop is the faithful answer.  g <= 16 -> the native 14 untouched."""
    if g <= NATIVE_G:
        return SE_LABEL_FONT_NATIVE
    size = se_font_size(SE_LABEL_FONT_NATIVE, g)
    while size > SE_LABEL_FONT_MIN and not labels_fit(size):
        size -= 1
    return size


# ==== TECH BREAKTHROUGH window (Thinker "NetTechWin" 0x811E40; builder 0x483F90, painter 0x483950) =========
# "OUR RESEARCHERS HAVE MADE A BREAKTHROUGH": a fixed 550x600 GraphicWin whose builder derives 17 rects from
# the window rect by additive immediates (decompile work\_ntw_dec_core.txt; pristine ref
# refs\pristine\TechBreakthrough.png).  The law is vanilla's own cascade at DEVICE density: every additive
# constant c becomes s(c) = scale_px(c, g), the window is s(550) x s(600), and the quote box absorbs the
# rounding remainder exactly where vanilla's cascade leaves its slack (top-down panels meet the bottom-up
# button zone there) -- chrome follows content, so g = 16 is vanilla's arithmetic verbatim.  Compound
# immediates are split into their measured parts (0x0F = outer 12 + pad 3, 0x2A = 12 + 3 + 20 + 3 + 4,
# 0x22/0x28/0x41/0x25 = pads + the 28x34 icon buttons) so the 3 px frame pitch is ONE value everywhere.
# Button dims use the FLOOR idiom: thunk_tutbtn_post recovers the native face by CEIL (btn_native_dim), the
# exact inverse of the floor forward only -- a half-down dim can ceil one px over and clip fixed art.
NTW_WIN = (550, 600)
NTW_OUTER = 12            # ornate frame band: window edge -> content frame
NTW_PAD = 3               # frame pitch: every nested frame / neighbour gap
NTW_HEADER_H = 0x17
NTW_ICON_H = 0xD9
NTW_CAPTION_H = 0x14
NTW_LIST_H = 0x4C
NTW_OK_H = 20
NTW_OK_GAP = 4            # content frame bottom -> OK ring top
NTW_ICONBTN = (28, 34)
NTW_QUOTE_TEXT_GAP = 4    # quote text right edge -> first icon button
NTW_CAPTION_SIZE = 0x1A   # Win+0x16C
NTW_LIST_TS_INSET = 4     # TextScroll_attach inset inside a list panel
NTW_QUOTE_TS_INSET = 3
NTW_ICON_BOX = 160        # Sprite_draw_mono_scaled num (den 215): the icon is centred as a 160 box
NTW_ICON_DEN = 215
NTW_RECT_FIELDS = (("win", 0xA14), ("content", 0xA24), ("header", 0xA34), ("icon", 0xA44),
                   ("list_tl", 0xA54), ("list_tr", 0xA64), ("list_bl", 0xA74), ("list_br", 0xA84),
                   ("cap_tl", 0xA94), ("cap_tr", 0xAA4), ("cap_bl", 0xAB4), ("cap_br", 0xAC4),
                   ("quote", 0xAD4), ("quote_text", 0xAE4), ("ok", 0xAF4), ("btn1", 0xB04), ("btn2", 0xB14))


def ntw_layout(g: int) -> Dict[str, Tuple[int, int, int, int]]:
    """The 17 rects of the breakthrough window at g (field order NTW_RECT_FIELDS).  g <= 16 -> vanilla."""
    g = max(g, NATIVE_G)
    s = lambda v: scale_px(v, g)                 # noqa: E731
    f = lambda v: popup_scale_floor(v, g)        # noqa: E731
    w, h = s(NTW_WIN[0]), s(NTW_WIN[1])
    o, p = s(NTW_OUTER), s(NTW_PAD)
    il, ir = o + p, w - o - p                    # inner column L / R
    ok_b = h - o - p
    ok_t = ok_b - f(NTW_OK_H)
    content_b = ok_t - p - s(NTW_OK_GAP)
    r: Dict[str, Tuple[int, int, int, int]] = {"win": (0, 0, w, h), "content": (o, o, w - o, content_b),
                                               "ok": (il, ok_t, ir, ok_b)}
    t = o + p
    r["header"] = (il, t, ir, t + s(NTW_HEADER_H))
    t = r["header"][3] + p
    r["icon"] = (il, t, ir, t + s(NTW_ICON_H))
    mid = ((ir - il) + p) // 2 - p + il
    t = r["icon"][3] + p
    for cap, lst in (("cap_t", "list_t"), ("cap_b", "list_b")):
        b = t + s(NTW_CAPTION_H)
        r[cap + "l"], r[cap + "r"] = (il, t, mid, b), (mid + p, t, ir, b)
        t = b + p
        b = t + s(NTW_LIST_H)
        r[lst + "l"], r[lst + "r"] = (il, t, mid, b), (mid + p, t, ir, b)
        t = b + p
    r["quote"] = (il, t, ir, content_b - p)
    bw, bh = f(NTW_ICONBTN[0]), f(NTW_ICONBTN[1])
    b2_r, b_b = (w - o) - 2 * p, content_b - 2 * p
    r["btn2"] = (b2_r - bw, b_b - bh, b2_r, b_b)
    b1_r = r["btn2"][0] - p
    r["btn1"] = (b1_r - bw, b_b - bh, b1_r, b_b)
    r["quote_text"] = (il, t, r["btn1"][0] - s(NTW_QUOTE_TEXT_GAP), content_b - p)
    return r


def ntw_caption_size(g: int) -> int:
    return scale_px(NTW_CAPTION_SIZE, max(g, NATIVE_G))


def ntw_ts_inset_delta(native_inset: int, g: int) -> int:
    """What the TextScroll_attach wrappers add to the engine's native-inset args: x/y += d, w/h -= 2d."""
    return scale_px(native_inset, max(g, NATIVE_G)) - native_inset


def ntw_pad_delta(g: int) -> int:
    """d = s(3) - 3: the painter's three native-3 insets (OK ring, title text, icon area)."""
    return scale_px(NTW_PAD, max(g, NATIVE_G)) - NTW_PAD


def ntw_icon(g: int, l: int, r: int, top_native: int, h_native: int) -> Tuple[int, int, int]:
    """(x, y, num) for the breakthrough icon.  The painter hands the wrapper its own locals: the icon
    panel's raw L/R, top_native = T + 3 + lineH and h_native = (B - 3) - top_native, both with the NATIVE
    3; the title sits d lower and the bottom inset is d deeper, so the area is (top + d, h - 2d).  num =
    160*g/16 = 10g exactly; the box is centred with the engine's own `cdq; sub; sar 1` (trunc toward 0)."""
    g = max(g, NATIVE_G)
    d = ntw_pad_delta(g)
    box = NTW_ICON_BOX * g // NATIVE_G
    half = lambda v: int(v / 2)                  # noqa: E731  (cdq; sub eax,edx; sar eax,1)
    return l + half((r - l) - box), top_native + d + half((h_native - 2 * d) - box), box


# Caption text (header + the 4 panel captions, Buffer_write_cent_l_7 in 23 / 20 px slots, find_font(16,1)): NO nudge.
# MEASURED on the first bake (2026-09-19 shots 1543xx): vanilla ink gaps top/bottom 5/4 (header 6/6); un-nudged scaled
# 11/10 @g40 (faithful 12.5/10), 7/7 @g25 (7.8/6.2), 6/5 @g22 (6.9/5.5).  A (g-16)>>3 upward nudge (the popup-title
# habit) measured 8/13 @g40 = 3-4 px HIGH: these slots hold the writer's own line box, the bias is already vanilla's.
NTW_CAPTION_NUDGE = 0


# ==== ORNATE frame band map (def &0x6846B0, corner canvas 61x44) — 2026-09-19 =====================================
# band_widths pins cells 0 and 1 of a corner band to K because on every PLAIN def those are the stroke and its
# bevel.  On the ornate def they are TRANSPARENT MARGIN: the art is  margin(3-4 px key) | metal(4-5) | green line(1)
# | key interior, so (a) the margin collapsed to 2K + remainder (7/6/3 px @g40/25/22 for a 3-px margin: 7.5/4.7/4.1
# proportionate) and (b) the one real stroke, the inner green line, fell in the remainder zone and took whatever
# rounding landed there — and because the far band MIRRORS the near widths while the art is not symmetric (the line
# is cell 7 from the left but cell 8 from the right), opposite sides rounded differently: 2/3 px L/R @g40, 1/2 @g25
# and @g22 (measured on the tech-breakthrough shots 20260919-1543xx; vanilla 1/1).
# LAW: pin the cell that IS the stroke, per side; everything else (margin, metal, key interior) is inert and shares
# the remainder.  Cell indices are read off the ENGINE's own native render (1024x768 shot, 26-39 of 40 samples per
# side agree), not the pcx grid: near x 7, far x 8 (from the right edge), near y 7, far y 5 (from the bottom).
ORNATE_BAND = (61, 44)                     # TL corner sprite canvas = the band depth per axis; identifies the def
ORNATE_STROKE_CELL = {"x": (7, 8), "y": (7, 5)}     # axis -> (near cell, far cell counted from the far edge)


def chrome_band_widths(n: int, band_px: int, k: int, c: int) -> List[int]:
    """Per-cell widths of a corner band whose ONE chrome cell is `c`: widths[c] == k, the other n-1 cells share
    band_px - k by the remainder-distribution law.  Same degenerate fallback as band_widths."""
    if n <= 0 or band_px <= 0:
        raise ValueError("chrome_band_widths: n and band_px must be positive")
    if not 0 <= c < n:
        raise ValueError("chrome_band_widths: chrome cell outside the band")
    if n <= 2 or band_px < 2 * k:
        return distribute(band_px, n)
    rest = distribute(band_px - k, n - 1)
    return rest[:c] + [k] + rest[c:]


def axis_map_chrome(src_n: int, dst_n: int, n: int, g: int, c_near: int, c_far: int,
                    skip: int = 0) -> Optional[List[int]]:
    """axis_map with per-side chrome cells: the near band uses chrome_band_widths(.., c_near), the far band its OWN
    widths chrome_band_widths(.., c_far) laid from the far edge (not a mirror of the near band).  Middle and the
    None conditions are axis_map's verbatim.

    skip (0 or 1, fix 26): the far band's outermost `skip` source cells are never sampled.  Its table is built with
    chrome cell c_far - skip and every entry + skip (dest col dst_n-1-jj shows far[jj]).  skip == 0 is the form
    above.  The map stays monotone non-decreasing: the far band's innermost column samples src_n-1-(n-1+skip) <=
    the middle's clamp src_n-1-n."""
    if not 0 <= skip <= 1 or not 0 <= c_far - skip < n:
        raise ValueError("axis_map_chrome: skip must be 0/1 and c_far - skip a cell of the band")
    if n <= 0 or src_n < 2 * n + 1:
        return None
    b = cum(n, dst_n, src_n)
    if b <= 0 or dst_n < 2 * b:
        return None
    k = stroke_width(g)

    def fwd(c: int) -> List[int]:
        f: List[int] = []
        for y, w in enumerate(chrome_band_widths(n, b, k, c)):
            f.extend([y] * w)
        return f[:b]

    near = fwd(c_near)
    far = [v + skip for v in fwd(c_far - skip)]
    lo, hi = n, src_n - 1 - n
    out: List[int] = []
    for j in range(dst_n):
        if j < b:
            out.append(near[j])
        elif j >= dst_n - b:
            out.append((src_n - 1) - far[dst_n - 1 - j])
        else:
            out.append(min(max((j * src_n) // dst_n, lo), hi))
    return out


# ==== ORNATE POPUP frame: the right band mirrors the left on the half-open axis (fix 26 v4, 2026-10-24) ==============
# The ornate art is asymmetric: on every row the right side carries ONE MORE source column outside its green line than
# the left (green = column 7 from the left, 8 from the right).  Where that extra column sits depends on the row:
#   * the straight edge (rows 43..206): it is transparent KEY (outer key runs 3 | 4);
#   * the top-right corner (rows 0..43): the right ornament is one column wider than the left's;
#   * the bottom-right clamp (rows 207..247): the green line is DOUBLED (columns 7 and 8 from the right).
# axis_map_chrome lays each band from its own art, so the right green line sat one native column further in than the
# left's mirror: line -> title band 12 | 9 @g40, 7 | 4 @g25, 6 | 4 @g22.
# LAW (Popup_on_draw_background's backdrop only, armed by t_orn_bd_arm; NetTechWin keeps skip 0; keyed blits only --
# an opaque blit (key -1) is all MIRROR): from the green line inward every row is axis_map_chrome skip 1 (the far
# band = the near band's cell layout one source column outward), so the right green line is the mirror of the left
# about the frame's half-open axis x <-> W - 1 - x on EVERY row (one straight line).  The outer segment drops the
# extra column per row CLASS (ornate_popup_row_class), and the classes are BLOCKS of the art, so no vertically
# continuous art column ever crosses from one outer map to another:
#   * MIRROR (the straight edge): the extra key column is not sampled -- transparent margins and metal mirror the left;
#   * DUP (the bottom-right clamp: every row from the first doubled-line row of the lower half down): the old
#     (vanilla x g/16) outer cells 0..6, the line in the near layout's stroke cell, and the DUPLICATE line column is the
#     one dropped -- no art column is lost at any g and the clamp's margins stay vanilla x g/16;
#   * CORNER (the top-right ornament: every row that fails the mirror pattern, plus a pattern row whose outer art
#     continues one of them vertically -- the ornament's foot, row 43): the old outer cells 0..6 too (margins and
#     ornament vanilla x g/16, every g), the green line in the near layout's stroke cell, and the ornament's innermost
#     column (7 from the right: the bevel next to the line, mostly flat) is the one dropped ("O4", user decision
#     2026-10-24 after audit26b: closest to vanilla x g/16, no compression; supersedes v3's squeeze).
# A CORNER row is a DUP row's map with the shift stopping at D (left of the line) instead of E (through the line).
#   * PLAIN (audit26c N1, any block): a row with NO extra column at all -- both line columns key and the two key runs
#     equal (the bottom edge's last row 249: 61 | 61) -- shows the near layout UNSHIFTED across the whole far band
#     (jj < b: src_n-1-near[jj]), the exact mirror of its left: the skip-1 maps would sample one column further in and
#     cut the right key run one cell short (150 | 153 @4K; vanilla 152.5 | 152.5, c67c3cd1 153 | 153).
ORNATE_POPUP_FAR_SKIP = 1
ORNATE_POPUP_OUTER_CELLS = 8           # the right band's source columns outside (and excluding) its green line


def ornate_popup_axis_map_x(src_n: int, dst_n: int, g: int) -> Optional[List[int]]:
    """The ornate POPUP frame's x column map on a MIRROR row (dest col -> src col): axis_map_chrome with the far chrome
    cell c_far - 1 == c_near (the near layout) and skip 1: dest col W-1-jj shows src_n-2-near[jj]."""
    c_near, c_far = ORNATE_STROKE_CELL["x"]
    return axis_map_chrome(src_n, dst_n, ORNATE_BAND[0], g, c_near, c_far, ORNATE_POPUP_FAR_SKIP)


def ornate_popup_outer_width(src_n: int, dst_n: int, g: int) -> int:
    """D = the device width of the near band's cells 0..c_near-1 (left of the green line) = where the right band's
    green line starts, counted from the right edge."""
    m = axis_map_chrome(src_n, dst_n, ORNATE_BAND[0], g, *ORNATE_STROKE_CELL["x"])
    c_near = ORNATE_STROKE_CELL["x"][0]
    return sum(1 for j in range(cum(ORNATE_BAND[0], dst_n, src_n)) if m[j] < c_near)


def ornate_popup_line_end(src_n: int, dst_n: int, g: int) -> int:
    """E = D + the near layout's stroke-cell width: the device width of the near band's cells 0..c_near (through the
    green line) -- the DUP rows' outer segment."""
    m = axis_map_chrome(src_n, dst_n, ORNATE_BAND[0], g, *ORNATE_STROKE_CELL["x"])
    c_near = ORNATE_STROKE_CELL["x"][0]
    return sum(1 for j in range(cum(ORNATE_BAND[0], dst_n, src_n)) if m[j] <= c_near)


def ornate_popup_row_mirrors(row: List[int], key: int) -> bool:
    """The MIRROR pattern: the row's last column is the key, and its 8 columns before that repeat the structure of
    its first 8 (the left outer segment + its line column, c_near = 7) -- every column key where the left one is key
    and carrying the left line column's colour (row[c_near]) exactly where the left one does.  So the right side IS
    the left one plus one transparent outer column: the straight edge, not the corner ornament (one column wider),
    not the bottom-right clamp (art in the outer column, a doubled line)."""
    c_near = ORNATE_STROKE_CELL["x"][0]
    if row[-1] != key:
        return False
    line = row[c_near]
    return all((row[c] == key) == (row[-2 - c] == key) and (row[c] == line) == (row[-2 - c] == line)
               for c in range(c_near + 1))


def ornate_popup_row_doubled(row: List[int], key: int) -> bool:
    """The bottom-right clamp's doubled line: the right's columns c_near and c_near + 1 (from the right) both carry the
    left line column's colour, and it is not the key."""
    c_near = ORNATE_STROKE_CELL["x"][0]
    line = row[c_near]
    return line != key and row[-1 - c_near] == line and row[-2 - c_near] == line


def ornate_popup_dup_start(art: List[List[int]], key: int) -> int:
    """First source row of the DUP block: the first row of the art's lower half (y >= H // 2) with a doubled line;
    len(art) when there is none."""
    h = len(art)
    return next((y for y in range(h // 2, h) if ornate_popup_row_doubled(art[y], key)), h)


def ornate_popup_rows_continue(a: List[int], b: List[int], key: int) -> bool:
    """Two vertically adjacent source rows share art in the right's outer segment: some column c < 8 from the right
    is the same non-key colour in both."""
    return any(a[-1 - c] == b[-1 - c] != key for c in range(ORNATE_POPUP_OUTER_CELLS))


def ornate_popup_row_plain(row: List[int], key: int) -> bool:
    """A PLAIN row: both line columns (c_near from the left, c_near + 1 from the right) are the key and the two outer
    key runs are equal -- the right carries no extra column to drop."""
    c_near = ORNATE_STROKE_CELL["x"][0]
    if row[c_near] != key or row[-2 - c_near] != key:
        return False
    run = lambda r: next((i for i, v in enumerate(r) if v != key), len(r))  # noqa: E731
    return run(row) == run(row[::-1])


def ornate_popup_row_class(art: List[List[int]], y: int, key: int) -> str:
    """'mirror' | 'corner' | 'dup' | 'plain' for source row y (see the LAW above).  key == -1 (an opaque blit):
    'mirror'."""
    if key == -1:
        return "mirror"
    if ornate_popup_row_plain(art[y], key):
        return "plain"
    yd = ornate_popup_dup_start(art, key)
    if y >= yd:
        return "dup"
    row = art[y]
    if not ornate_popup_row_mirrors(row, key):
        return "corner"
    for n in (y - 1, y + 1):
        if 0 <= n < yd and not ornate_popup_row_mirrors(art[n], key) and ornate_popup_rows_continue(row, art[n], key):
            return "corner"
    return "mirror"


def ornate_popup_row_map(art: List[List[int]], y: int, dst_n: int, g: int, key: int) -> Optional[List[int]]:
    """The x map the ornate POPUP frame uses for source row y of `art`: ornate_popup_axis_map_x, with its outer
    segment shifted one source column outward per ornate_popup_row_class -- DUP: jj < E shows src_n-1-near[jj] (the
    old outer cells and the line, the duplicate line column dropped); CORNER: jj < D (the old outer cells 0..6; the
    line stays the mirror's, column 7 from the right is dropped); PLAIN: jj < b (the whole far band: the near layout
    unshifted, nothing dropped); MIRROR: unchanged."""
    src_n = len(art[y])
    m = ornate_popup_axis_map_x(src_n, dst_n, g)
    if m is None:
        return None
    cls = ornate_popup_row_class(art, y, key)
    out = list(m)
    if cls != "mirror":
        n = {"dup": ornate_popup_line_end, "corner": ornate_popup_outer_width}.get(
            cls, lambda s_, d_, g_: cum(ORNATE_BAND[0], d_, s_))(src_n, dst_n, g)
        for jj in range(n):
            out[dst_n - 1 - jj] += 1
    return out


# ==== ORNATE POPUP content margin, right (fix 26, 2026-10-24, user-approved design "P") ============================
# Popup_calc @0x404E19 sets the ornate (type 2/6) margins L/R = 19/21 native.  19 = title inset 13 + 3 + 3 (the
# content edge lands on the title inner stroke); the right's 21 parks every container (picker ring, list rows, OK
# bar) 2 native px inside the title inner on the right only.  With the frame mirrored (F2) that is the last
# asymmetric term: line -> ring 19/24 @g40.  LAW: at g > 16 the right margin is the left's 19, so every container
# is flush with the title inner on both sides; the box is s(2) narrower and re-centred.  g <= 16 keeps vanilla's 21.
ORNATE_MARGIN_R_NATIVE = 21


def popup_content_frame_right(rect_r: int, box_w: int, rect_l: int, ornate: bool, g: int) -> int:
    """thunk_content_frame (the d5a0 OUTER-UNION ring @0x406238) + t_orn_cfpost: at g > 16 the ring is widened to
    R = box_w - L (only-widen) -- symmetric about the inclusive axis.  fix 26 v2: an ORNATE popup's ring that the
    widen landed exactly there is pulled in by ORNATE_HALF_OPEN onto the half-open axis (box_w - 1 - L) -- the
    untitled ornate body ring (TutWin, MPRECEIVEFILE); titled ornate rings are re-derived from the title stash by
    thunk_pf_union_align anyway.  Flat / slide popups and g <= 16 are unchanged."""
    if g <= NATIVE_G:
        return rect_r
    r = max(rect_r, box_w - rect_l)
    if ornate and r == box_w - rect_l:
        r -= ORNATE_HALF_OPEN
    return r


def ornate_popup_margin_r(g: int) -> int:
    """[popup+0x21b4] (native units; the box-margin lever then floor-scales it into [+0x30f4]) for an ornate 2/6
    popup at g: 21 at g <= 16 (vanilla), the left margin's 19 above."""
    return ORNATE_MARGIN_R_NATIVE if g <= NATIVE_G else ORNATE_MARGIN_L_NATIVE


def ornate_outer_key(src: List[List[int]], fx: List[int], fy: List[int], bx: int, by: int, key: int) -> List[Tuple[int, int]]:
    """Dest pixels (x, y) the ornate blit RE-KEYS after its keyed copy: walking inward from each outer edge of the
    dest, along every row (at most bx px from the left and from the right) and every column (at most by px from the
    top and from the bottom), while the mapped source pixel is the key.  That is the art's transparent margin and
    its corner cut-outs — the only key pixels connected to the outside — and nothing else (the first non-key pixel
    ends the walk, so holes inside the metal and the key interior keep whatever lies under them).  Vanilla shows the
    map there; the two-pass ornate backdrop (device-density underlay first, metal keyed over it) left the underlay
    visible as a dark rim outside the metal (4 px @g40/g25, 1-3 @g22).
    fx may also be one x map PER DEST ROW (fix 26 v2, ornate_popup_row_map): every probe of row y reads row y's map."""
    rows = fx if fx and isinstance(fx[0], list) else None
    w, h = len(rows[0] if rows else fx), len(fy)

    def fxr(y: int) -> List[int]:
        return rows[y] if rows else fx

    out = set()
    for y in range(h):
        row, m = src[fy[y]], fxr(y)
        for rng in (range(0, min(bx, w)), range(w - 1, max(w - 1 - bx, -1), -1)):
            for x in rng:
                if row[m[x]] != key:
                    break
                out.add((x, y))
    for x in range(w):
        for rng in (range(0, min(by, h)), range(h - 1, max(h - 1 - by, -1), -1)):
            for y in rng:
                if src[fy[y]][fxr(y)[x]] != key:
                    break
                out.add((x, y))
    return sorted(out)


# ==== ornate popups: text-field right inset (2026-09-19) ===========================================================
ORNATE_FIELD_LEFT_MARGIN = 19     # [popup+0x30f0] native (scaled by the box-margin lever with the FLOOR idiom)
ORNATE_FIELD_RIGHT_BASE = 10      # `lea ecx,[edx-0xa]` @0x406116 (thunk_popup_fieldR: floor-scaled)
ORNATE_FIELD_RIGHT_SUB = 9        # `sub ecx,9` @0x40612C, ornate types 2/6 only -- was left NATIVE


def ornate_field_right_sub(g: int) -> int:
    """What the ornate `sub ecx,9` must subtract at g so an UNKEYED ornate popup's text field is inset equally on
    both sides, as in vanilla (19 - 3 == 10 + 9 - 3 == 16).  Left inset = fl(19g/16) - ps3; right inset =
    fl(10g/16) + X - ps3  ->  X = fl(19g/16) - fl(10g/16): the neighbour's OWN cascade (floor-descale round-trip
    rule), not a bare fl(9g/16) (1 px short at g=22).  9 at g <= 16; 13 / 14 / 22 @g22 / 25 / 40.
    Measured defect with the native 9 (tutorial tour window, live geometry via uimod debugdump): field insets L/R
    40/26 @g40 and 25/20 @g25, the ring riding the ornate border's inner line on the right.  Keyed (titled) ornate
    popups are outside this law: thunk_popup_fieldpads' ornate arm replaces the field R from g_title_right.
    fix 26 v2 (2026-10-24, ORNATE_HALF_OPEN): + 1 at g > 16.  The field R is drawn INCLUSIVE (band-map), so equal
    inset VALUES put it on the axis x <-> W - x; one more puts the drawn box on vanilla's half-open axis
    x <-> W - 1 - x, the axis the frame line, the title band and the child windows (rows, OK bar) use."""
    if g <= NATIVE_G:
        return ORNATE_FIELD_RIGHT_SUB
    return (popup_scale_floor(ORNATE_FIELD_LEFT_MARGIN, g) - popup_scale_floor(ORNATE_FIELD_RIGHT_BASE, g)
            + ORNATE_HALF_OPEN)


# ==== popup art on the shared popup canvas: edge-pinned parity re-blit (2026-09-20) ================================
# Every picture a BasePop draws into the shared popup canvas (0x940824: the 200x120 *_sm.pcx event pictures, the
# version logo, the 131x157 faction-picker portrait) is a 1-px frame (index 25, chamfer = key) around a 1-row
# scanline-dithered interior.  Any resample (engine NN, thunk_portrait_avg's bilinear) keeps the source period, so
# the interior bands at g=22/25 (measured row-luminance runs 2,1,2,1,2,2 / 1,1,2,1,2 on 1600 and 1920 shots).  The
# council re-blit (thunk_parity_reblit) cured the interior but was pair-granular to the last row: with an even
# source height the bottom frame row landed one device row early and a picture row was drawn beneath it.  Law: rows
# the centre map sends to the first / last source row stay there (the frame keeps its NN share); every other device
# row shows the nearest source row of its scanline field, the field changing every art_scan_rows(num, den) device
# rows (v2 2026-10-04: the popup pictures' 2-row scanlines for every re-blitted picture; v1 alternated per row),
# counted on the DEST BUFFER's stripe grid (v3 2026-10-06, option B stage 2: field ((y0 + j) // T) & 1 for device
# row j at dest row y0 + j -- the picture's stripes continue the chrome's; before, from the first interior row).  Both centre maps are
# the edge-clamped nn_center_index over the DEVICE extent (the council re-blit's den/num map never reaches the last
# source row at small ratios: g=17, sh=10 stops at row 8).
# UNFRAMED art (v4 2026-10-17): the 1-px frame is a property of the popup pictures, not of every sprite the body
# re-blits.  Art with no frame -- the diplomacy BIOSCAN colour bar (interface.pcx 9x147, g_diplo_colour_bar_sprite) and
# the council portrait slots (g_faction_sprites + 0x478 / 0x4A4) -- has scanlines in rows 0 and sh-1 too, and pinning
# them showed source row 0 / sh-1 regardless of the stripe grid (a 2-row band then a 1-row stripe at the bar's top at
# 4K; a dark row on a navy grid row at its top at 1920x1080 and at its bottom at 1600x1200).  framed=False: no pinned
# rows (jt, jb = 0, dh), every device row shows the nearest source row of its own field over ALL sh rows (row 0 =
# interior row -1, the same parity convention: field 0 shows the odd rows).  The thunk decides framed-ness by IDENTITY
# (the sprite's pixel pointer equals the colour bar's or a council slot's), never by content -- content tests misread
# real assets.  framed=True is the v3 law exactly.
# Port: thunk_art_reblit (assemble_artreblit.py); parity tests\test_artreblit_asm_parity.py, tests\test_artreblit_unframed_asm.py.
def art_reblit_col(i: int, sw: int, num: int, den: int = NATIVE_G) -> int:
    """Device column i -> source column: nn_center_index over dw = fl(sw*num/den)."""
    return nn_center_index(i, (sw * num) // den, sw)


def art_frame_rows(sh: int, num: int, den: int = NATIVE_G, framed: bool = True) -> Tuple[int, int]:
    """(jt, jb): the device rows [jt, jb) the centre map sends INSIDE the 1-px frame (source rows 1..sh-2); rows
    above / below are pinned to the frame row.  Closed form of scanning nn_center_index over dh = fl(sh*num/den):
    jt = #rows whose centre maps to row 0, jb = #rows whose centre maps below sh-1.  Unframed art: (0, dh), no
    pinned row."""
    dh = (sh * num) // den
    if sh < 2 or dh <= 0:
        return 0, 0
    if not framed:
        return 0, dh
    jt = min(max((2 * dh + sh - 1) // (2 * sh), 0), dh)
    jb = min(max(((2 * dh * (sh - 1) - 1) // sh + 1) // 2, 0), dh)
    return jt, jb


def art_scan_near(y: int, h0: int, h1: int, num: int, den: int = NATIVE_G, phase: int = 0, top: int = 1) -> int:
    """Interior device row y (of h1) -> the SOURCE row it shows: the row of its own field (art_scan_field of the
    DEST-BUFFER row y + phase; phase = the dest row of interior device row 0, see art_scan_phase) NEAREST the
    row's centre, field rows clamped to the art.  top = the source row of interior row 0: 1 under a 1-px frame
    (interior row r = source row r + 1, h0 = sh - 2), 0 for unframed art (h0 = sh).  Field k shows source rows of
    parity k ^ 1 either way, i.e. interior parity q = k ^ (1 - top), n_field = (h0 - q + 1) // 2 rows.  Integer form
    of art_field_enlarge's `near`: m = floor(((2y+1)*h0 + (1-2q)*h1) / (4*h1)) -- floor, not truncation (the
    numerator goes negative at the top)."""
    k = art_scan_field(y + phase, num, den)
    q = k ^ (1 - top)
    n_field = (h0 - q + 1) // 2
    m = ((2 * y + 1) * h0 + (1 - 2 * q) * h1) // (4 * h1)
    m = min(max(m, 0), n_field - 1)
    return 2 * m + q + top


def art_reblit_row(j: int, sh: int, num: int, den: int = NATIVE_G, y0: int = 0, framed: bool = True) -> int:
    """Device row j -> source row.  Frame rows (outside art_frame_rows) are pinned to the centre map; interior rows
    show their field's nearest source row (art_scan_near): scanlines art_scan_rows(num, den) device rows thick,
    the chrome's thickness, on the DEST BUFFER's stripe grid (y0 = the dest row of device row 0: device row j
    shows field ((y0 + j) // T) & 1, the member stripe_top gives the chrome at that row -- option B stage 2,
    2026-10-06: a picture's stripes continue the panel's, no 1-row step along the join).  Art under 4 rows, or
    with no interior device row, is plain centre NN.  framed=False (unframed art, v4 2026-10-17): no frame row is
    pinned; every device row is a field row over all sh source rows."""
    c = nn_center_index(j, (sh * num) // den, sh)
    jt, jb = art_frame_rows(sh, num, den, framed)
    if sh < 4 or not jt <= j < jb:
        return max(c, 0)
    if not framed:
        return art_scan_near(j - jt, sh, jb - jt, num, den, y0 + jt, 0)
    return art_scan_near(j - jt, sh - 2, jb - jt, num, den, y0 + jt)


def art_reblit(dest: bytes, d_w: int, d_h: int, d_pitch: int, src, sw: int, sh: int, s_pitch: int, key: int,
               x: int, y: int, offx: int, offy: int, num: int, den: int = NATIVE_G, framed: bool = True) -> bytes:
    """Full port of thunk_art_reblit: redraw the engine-placed art rect from the source through the two maps;
    key texels skipped; clipped right/bottom; identity (no write) at num <= den or a negative origin.
    The sprite offsets scale with C / x86 TRUNCATION toward zero (_idiv), like both ports (the asm's cdq; idiv
    and uimod portrait.cpp's int `/`): a negative offset would land one device px off under Python's floor."""
    out = bytearray(dest)
    x0, y0 = x + _idiv(offx * num, den), y + _idiv(offy * num, den)
    dw, dh = (sw * num) // den, (sh * num) // den
    if num <= den or x0 < 0 or y0 < 0:
        return bytes(out)
    iw = min(dw, d_w - x0)
    if iw <= 0:
        return bytes(out)
    for j in range(dh):
        dy = y0 + j
        if dy >= d_h:
            break
        r = art_reblit_row(j, sh, num, den, y0, framed)
        for i in range(iw):
            v = src[r * s_pitch + art_reblit_col(i, sw, num, den)]
            if v != key:
                out[dy * d_pitch + x0 + i] = v
    return bytes(out)


def quote_art_origin(x: int, y: int, g: int) -> Tuple[int, int]:
    """Where thunk_portrait_drop places art drawn into the shared popup canvas: x = fl(5g/16), y + fl(12(g-16)/16)
    at g > 16, the engine's (x, y) otherwise.  thunk_art_wrap re-derives it for the re-blit (portrait_drop adjusts
    its OWN arg copy, the caller's frame keeps the engine values)."""
    if g <= NATIVE_G:
        return x, y
    return (5 * g) >> 4, y + ((12 * (g - NATIVE_G)) >> 4)


# ==== base screen: NUTRIENTS storage grid with sub-8-px rows (2026-09-21) ==========================================
# BaseWin_draw_nutrients (0x411240) sizes its grid from the box: rows = [ebp-0x2c], native row pitch p = [ebp-0x28] =
# fl(avail / rows) over the area [ebp-0x50] .. [ebp-0x48], grid top = area_top + (avail - p*rows)/2.  Below p = 8 each
# cell is a SOLID GraphicWin_fill_2 rect (T, T+p-1) -- a 1-px gap under every row.  Scaling each edge on its own
# (floor) gives cell heights 1,1,1,1,2,2,2,2 at 25/16 for p = 2: alternating light and dark 12-px blocks (user's g=25
# shot 2026-09-20, measured).  No edge rounding cures a 3.125-px period built from 1-px features, so the grid is
# regenerated at ONE device pitch (the dither doctrine applied to geometry) and re-centred in the box:
#   P  = min(half_down(p*g, 16), fl(avail_dev / rows))   never taller than the box (chrome follows content: pull IN)
#   gap = stroke_width(g), but the filled part never drops under half the pitch (brighter member wide)
# Identity at g <= 16 (P = p, cell = p-1).  Port: thunk_bw_nutrect (assemble_nutgrid.py); tests\test_nutgrid_asm_parity.py.
NUTGRID_MAX_PITCH = 8           # `cmp edi, 8` twice in the cell loop (BaseWin_draw_nutrients+0x3C0 / +0x3EE): below it the cells are fills, from it up tiles
NUTGRID_MIN_PITCH = 2           # p = 1 draws nothing in vanilla (H = 0)


def nutgrid_applies(pitch: int, g: int) -> bool:
    return g > NATIVE_G and NUTGRID_MIN_PITCH <= pitch < NUTGRID_MAX_PITCH


def nutgrid_layout(area_top: int, area_bot: int, rows: int, pitch: int, g: int) -> Tuple[int, int, int]:
    """(y0, P, cell): device y of row 0, device row pitch, device filled height.  Native args."""
    if not nutgrid_applies(pitch, g) or rows <= 0:
        return area_top + ((area_bot - area_top) - pitch * rows) // 2, pitch, pitch - 1
    top, bot = (area_top * g) >> 4, (area_bot * g) >> 4
    avail = bot - top
    P = max(min(half_down(pitch * g, NATIVE_G), avail // rows), 1)
    cell = max(P - stroke_width(g), (P + 1) >> 1)
    if cell >= P:
        cell = max(P - 1, 1)
    return top + (avail - rows * P) // 2, P, cell


def nutgrid_row_rect(area_top: int, area_bot: int, rows: int, pitch: int, row: int, g: int) -> Tuple[int, int]:
    """(T, B) of row `row` in device space (half-open fill, as GraphicWin_fill_2 draws it)."""
    y0, P, cell = nutgrid_layout(area_top, area_bot, rows, pitch, g)
    return y0 + row * P, y0 + row * P + cell


# ==== leader portraits: smooth composite enlarge (2026-09-21; uimod portrait.cpp is the PORT) ======================
# The 8-bit leader portraits (1-px frame, photo scanlined through the WHOLE image) read blocky under any NN enlarge
# and no palette-index resample can smooth them.  User-chosen look ("option C", previews work\_portrait_preview\
# options): take the scanlines OUT, enlarge the photo with a Lanczos-3 filter, sharpen lightly, put the scanlines
# back at DEVICE density, and fit to the live palette with error diffusion (a plain nearest-colour fit posterises
# and drifts the dark greys to green).  The frame rows/cols stay the edge-pinned NN of art_reblit.
#   applies: num > den, PORTRAIT-shaped art (sh > sw), a real key (<= 0xFF: the opaque flic path is excluded),
#            and an OPAQUE RING: no key texel on the outer row / column ring except its 4 corners.  The enlarge keys
#            the ring corners only and writes everything inside opaque, so a SHAPED sprite (key reaching in from
#            the edge) would lose its transparency.  Every leader / native-life portrait has the opaque ring
#            (measured on all 14 faction sheets x 4 slots + the 6 BT*.pcx faces; a bake only writes indices
#            PORTRAIT_PAL_LO..HI).  The ring, not the interior: angels.pcx's big council / diplomacy / datalink
#            portraits carry stray key texels INSIDE (an artist's dropouts) and must still qualify.  The ring
#            refuses Santiago's council logo (spartans.pcx 62x72 / 62x71 hexagon, the one portrait-shaped logo:
#            it came out on an opaque near-black square; 2026-10-11) -- it keeps the parity re-blit.
#   palette: pal = the dest Buffer's RGBQUAD table (b,g,r,x); candidates = PORTRAIT_PAL_LO..PORTRAIT_PAL_HI only
#            (the key, the reserved system slots and the cycling tail never appear)
# Every step after the (double) Lanczos weights is integer arithmetic so the C++ port matches bit for bit.
PORTRAIT_PAL_LO, PORTRAIT_PAL_HI = 10, 245
PORTRAIT_LANCZOS_A = 3
PORTRAIT_WEIGHT_Q = 14                  # filter taps in Q14
PORTRAIT_SHARPEN_Q8 = 154               # unsharp amount 0.60
PORTRAIT_SHARPEN_THRESHOLD = 2
PORTRAIT_DITHER_Q8 = 218                # error-diffusion strength 0.85
PORTRAIT_DIST_WEIGHTS = (2, 4, 3)       # r, g, b weights of the squared-difference palette search
PORTRAIT_MIN_W = 32                     # leader art is >= 96 wide; the diplomacy colour bar (9x147, a scanline gradient) and
                                        # any icon-class sprite are NOT portraits and keep the parity re-blit (2026-09-21)


def portrait_ring_opaque(src, s_pitch: int, sw: int, sh: int, key: int) -> bool:
    """No key texel on the art's outer ring (rows 0 / sh-1, columns 0 / sw-1) except the 4 corners."""
    for y in (0, sh - 1):
        if key in src[y * s_pitch + 1: y * s_pitch + sw - 1]:
            return False
    for y in range(1, sh - 1):
        if src[y * s_pitch] == key or src[y * s_pitch + sw - 1] == key:
            return False
    return True


def portrait_applies(src, s_pitch: int, sw: int, sh: int, key: int, num: int, den: int = NATIVE_G) -> bool:
    return (num > den > 0 and sh > sw >= PORTRAIT_MIN_W and 0 <= key <= 0xFF
            and portrait_ring_opaque(src, s_pitch, sw, sh, key))


def _portrait_taps(n_in: int, n_out: int):
    """Per output sample: (first input index, Q14 taps).  Lanczos-3, centres (o+0.5)*n_in/n_out, taps clipped to
    the image and renormalised; the Q14 rounding remainder goes to the largest tap so every set sums to 1.0."""
    import math
    scale = n_in / n_out
    fs = max(scale, 1.0)
    support = PORTRAIT_LANCZOS_A * fs
    out = []
    for o in range(n_out):
        c = (o + 0.5) * scale
        lo = max(int(math.floor(c - support)), 0)
        hi = min(int(math.ceil(c + support)), n_in)
        ws = []
        for i in range(lo, hi):
            x = (i + 0.5 - c) / fs
            if x == 0.0:
                w = 1.0
            elif abs(x) >= PORTRAIT_LANCZOS_A:
                w = 0.0
            else:
                px = math.pi * x
                w = PORTRAIT_LANCZOS_A * math.sin(px) * math.sin(px / PORTRAIT_LANCZOS_A) / (px * px)
            ws.append(w)
        tot = 0.0
        for w in ws:                                   # plain left-to-right sum, as the C++ port (not sum():
            tot += w                                   # Python 3.12 compensates, which could flip a tie)
        q = [int(math.floor(w / tot * (1 << PORTRAIT_WEIGHT_Q) + 0.5)) for w in ws]
        q[max(range(len(q)), key=lambda k: q[k])] += (1 << PORTRAIT_WEIGHT_Q) - sum(q)
        out.append((lo, q))
    return out


def _portrait_clamp8(v: int) -> int:
    return 0 if v < 0 else 255 if v > 255 else v


def portrait_enlarge(src, s_pitch: int, sw: int, sh: int, key: int, pal: bytes, num: int, den: int = NATIVE_G,
                     y0: int = 0):
    """Reference composite enlarge.  Returns (dw, dh, rows) with rows[j][i] = palette index or None (key / leave
    the dest alone), or None when the law does not apply.  Device row j / column i are relative to the art; y0 =
    the dest-buffer row device row 0 lands on (art_scan_phase: the scanlines sit on the buffer's stripe grid)."""
    if not portrait_applies(src, s_pitch, sw, sh, key, num, den):
        return None
    dw, dh = (sw * num) // den, (sh * num) // den
    crow = [nn_center_index(j, dh, sh) for j in range(dh)]
    ccol = [nn_center_index(i, dw, sw) for i in range(dw)]
    jt = next(j for j in range(dh) if crow[j] > 0)
    jb = next(j for j in range(dh - 1, -1, -1) if crow[j] < sh - 1) + 1
    il = next(i for i in range(dw) if ccol[i] > 0)
    ir = next(i for i in range(dw - 1, -1, -1) if ccol[i] < sw - 1) + 1
    W0, H0, W1, H1 = sw - 2, sh - 2, ir - il, jb - jt

    def rgb_of(idx):                                   # RGBQUAD b,g,r -> (r, g, b)
        return pal[idx * 4 + 2], pal[idx * 4 + 1], pal[idx * 4]

    photo = [[rgb_of(src[(y + 1) * s_pitch + x + 1]) for x in range(W0)] for y in range(H0)]
    # 1. which field is bright (luma 77/150/29), and the dark:bright ratio in Q8
    lum = [sum(77 * p[0] + 150 * p[1] + 29 * p[2] for p in row) for row in photo]
    ev, od = sum(lum[0::2]), sum(lum[1::2])
    n_ev, n_od = len(lum[0::2]), len(lum[1::2])
    bright = 0 if ev * n_od >= od * n_ev else 1          # compare the MEANS without dividing
    b_sum, b_n, d_sum, d_n = (ev, n_ev, od, n_od) if bright == 0 else (od, n_od, ev, n_ev)
    ratio_q8 = min((d_sum * b_n * 256) // max(b_sum * d_n, 1), 256)
    # 2. de-scanline: the overlay only DARKENS alternate rows -- the dark rows carry real picture detail (pupils,
    #    nostrils, mouth corners are often ONE row tall), so they are gained back up by 256/ratio, never rebuilt
    #    from their neighbours (v1 did that and smeared every one-row black accent in a bright row over three rows:
    #    black blotches on Santiago's face in the combat console, user 2026-09-21)
    if ratio_q8 > 0:
        for y in range(H0):
            if (y & 1) != bright:
                photo[y] = [tuple(_portrait_clamp8((v * 256 + (ratio_q8 >> 1)) // ratio_q8) for v in p) for p in photo[y]]
    # 3. Lanczos-3, horizontal then vertical, Q14, rounded and clamped after each pass
    half = 1 << (PORTRAIT_WEIGHT_Q - 1)
    tx, ty = _portrait_taps(W0, W1), _portrait_taps(H0, H1)
    hor = [[tuple(_portrait_clamp8((sum(q[k] * row[lo + k][c] for k in range(len(q))) + half) >> PORTRAIT_WEIGHT_Q)
                  for c in range(3)) for lo, q in tx] for row in photo]
    big = [[tuple(_portrait_clamp8((sum(q[k] * hor[lo + k][x][c] for k in range(len(q))) + half) >> PORTRAIT_WEIGHT_Q)
                  for c in range(3)) for x in range(W1)] for lo, q in ty]

    # 4. light unsharp: 3x3 binomial blur (1 2 1, edge-clamped), amount Q8, threshold on the difference
    def blur(img, h, w):
        t = [[tuple((img[y][max(x - 1, 0)][c] + 2 * img[y][x][c] + img[y][min(x + 1, w - 1)][c] + 2) >> 2
                    for c in range(3)) for x in range(w)] for y in range(h)]
        return [[tuple((t[max(y - 1, 0)][x][c] + 2 * t[y][x][c] + t[min(y + 1, h - 1)][x][c] + 2) >> 2
                       for c in range(3)) for x in range(w)] for y in range(h)]

    bl = blur(big, H1, W1)
    shp = [[tuple(_portrait_clamp8(big[y][x][c] + (((big[y][x][c] - bl[y][x][c]) * PORTRAIT_SHARPEN_Q8) >> 8))
                  if abs(big[y][x][c] - bl[y][x][c]) >= PORTRAIT_SHARPEN_THRESHOLD else big[y][x][c]
                  for c in range(3)) for x in range(W1)] for y in range(H1)]
    # 5. scanlines as THICK as the chrome's: art_scan_rows(num, den) device rows per scanline, bright and dark
    #    alike, on the DEST BUFFER's stripe grid (art_scan_phase): interior row y is grid row y + phase, and shows
    #    the bright field iff its grid stripe index parity equals the source's bright parity
    t = art_scan_rows(num, den)
    phase = art_scan_phase(y0 + jt, num, den)
    for y in range(H1):
        if (((y + phase) // t) & 1) != bright:
            shp[y] = [tuple((v * ratio_q8) >> 8 for v in p) for p in shp[y]]
    # 6. serpentine Floyd-Steinberg into the candidate indices
    cands = [(i,) + rgb_of(i) for i in range(PORTRAIT_PAL_LO, PORTRAIT_PAL_HI + 1)]
    wr, wg, wb = PORTRAIT_DIST_WEIGHTS
    acc = [[list(p) for p in row] for row in shp]
    fit = [[0] * W1 for _ in range(H1)]
    for y in range(H1):
        xs = range(W1) if (y & 1) == 0 else range(W1 - 1, -1, -1)
        dx = 1 if (y & 1) == 0 else -1
        for x in xs:
            r, g_, b = (_portrait_clamp8(v) for v in acc[y][x])
            best, bd, pick = 0, None, (0, 0, 0)
            for ci, cr, cg, cb in cands:
                d = wr * (cr - r) * (cr - r) + wg * (cg - g_) * (cg - g_) + wb * (cb - b) * (cb - b)
                if bd is None or d < bd:
                    best, bd, pick = ci, d, (cr, cg, cb)
            fit[y][x] = best
            err = [((v - p) * PORTRAIT_DITHER_Q8) >> 8 for v, p in zip((r, g_, b), pick)]
            for ox, oy, k in ((dx, 0, 7), (-dx, 1, 3), (0, 1, 5), (dx, 1, 1)):
                xx, yy = x + ox, y + oy
                if 0 <= xx < W1 and yy < H1:
                    for c in range(3):
                        acc[yy][xx][c] += (err[c] * k) >> 4
    # 7. assemble: frame rows/cols = edge-pinned NN of the source (key -> None), interior = the fit
    rows = []
    for j in range(dh):
        line = []
        for i in range(dw):
            if jt <= j < jb and il <= i < ir:
                line.append(fit[j - jt][i - il])
            else:
                v = src[crow[j] * s_pitch + ccol[i]]
                line.append(None if v == key else v)
        rows.append(line)
    return dw, dh, rows


# ==== replacement portraits from an RGB image (2026-09-30) =========================================================
# A player image (<game>\portraits\<name>.png|.jpg, or the portraits-hd pack in portraits\hd\) replaces a leader
# slot (council small/big, diplomacy, datalink) or a native-life file (BT*.pcx).  The picture is resampled from the
# RGB source itself at every size -- never from a dithered bake (dither is never resampled) -- and dithered into the
# LIVE game palette: Phase-0 measured every portrait dest's table == g_main_palette at g=16 and g=40, and the sheets'
# own tables differ from it in 30 entries, so a sheet palette is the wrong target.
#   pre-reduce: integer box average by k = ceil(long side / PORTRAIT_SRC_MAX_LONG), once after decode; g-independent,
#               so the framing below is identical at every scale
#   frame:      a uniform COVER crop to the slot's NATIVE interior aspect (never per-axis stretch).  Too wide: centred.
#               Too tall: PORTRAIT_FRAME_TOP_NUM/DEN of the excess above (faces sit high: the HD pack's tall outlier
#               registers 46 px down a 152 px excess, 0.30 -> 1/3).  One rect per (image, slot), reused at every g.
#   resample:   the portrait_enlarge Lanczos-3 taps (Q14) straight from the crop to the target interior
#   scanlines:  optional ([UIMod] PortraitScanlines, default on).  (bright, ratio_q8) are measured from the VANILLA art
#               the image replaces (portrait_scanline_params, portrait_enlarge's step 1) BEFORE anything overwrites
#               it.  Scanlines are 1 row thick at native size and art_scan_rows(num, den) device rows above it --
#               the popup pictures' thickness (user 2026-10-03), same as portrait_enlarge step 5; interior row u
#               (0 = first row inside the frame) is dark iff ((u // rows) & 1) != bright.  Two modes: OVERLAY darkens the dark rows only (vanilla's model: mean falls by
#               (1-r)/2); MEAN keeps the picture's mean (bright rows x 2/(1+r), dark rows x 2r/(1+r), clamped).
#   dither:     portrait_enlarge's serpentine Floyd-Steinberg into indices PORTRAIT_PAL_LO..HI, no unsharp (a
#               downscale is already sharp; sharpening it rings)
#   framing:    the diplomacy / datalink slots and the native-life pictures carry a 1-px FRAME (PCX index 25 =
#               engine index 35 after Buffer_load_pcx's +10, rgb (30,53,30));
#               the two COUNCIL slots (96x115, 118x144) do NOT -- their edge rows/cols are picture (measured on the
#               sheets 2026-10-03; treating them as framed left a ring of the vanilla painting around a replacement,
#               user 4K council shot).  framed=False replaces the whole sprite: target sw x sh (device dw x dh),
#               crop to the sw:sh aspect; its top row is interior row -1 (device: the dest grid, art_scan_phase)
#   native art: an image EXACTLY the slot's size (w x h == sw x sh with the frame, or the (sw-2) x (sh-2) interior)
#               is a player's edit of the game art: already scanlined and dithered.  It is never resampled (dither
#               is never resampled): nearest-colour into the interior, no added scanlines, and above native the
#               caller enlarges the bake with portrait_enlarge exactly like vanilla art.
#   palette:    every `pal` here is RGBQUAD (b, g, r, x) as a dest Buffer's +0xA4 table.  g_main_palette is
#               PALETTEENTRY (r, g, b, flags): convert with portrait_rgbquad_from_paletteentry first.
# Integer arithmetic after the Lanczos weights, so the C++ port matches bit for bit.
PORTRAIT_SRC_MAX_LONG = 1536
PORTRAIT_FRAME_TOP_NUM, PORTRAIT_FRAME_TOP_DEN = 1, 3
PORTRAIT_SCAN_OFF, PORTRAIT_SCAN_OVERLAY, PORTRAIT_SCAN_MEAN = 0, 1, 2


def portrait_shr_round(v: int, n: int) -> int:
    """v / 2**n rounded to nearest, halves away from zero -- SYMMETRIC for negative v.  The replacement path's error
    diffusion uses it for both the damping (x Q8 >> 8) and the 7/3/5/1-of-16 split: a plain `>>` floors toward -inf,
    so negative errors lose more than positive ones gain and the picture drifts ~2/255 dark (measured on every
    replacement at 4K / 1920 / 1600, audit F1 2026-10-03; user chose this fix, option B, keeping the 85% damping).
    The vanilla smoother (portrait_enlarge) keeps the floor: its look is user-approved."""
    h = 1 << (n - 1)
    return (v + h) >> n if v >= 0 else -((-v + h) >> n)


# ==== popup event pictures: field-separated smooth enlarge (2026-10-03; uimod portrait_law.h FieldEnlarge = PORT) ===
# The *_sm.pcx event pictures (1-px frame, scanlined) read blocky under the parity re-blit (art_reblit: every source
# row PAIR becomes one block, fl(2.5 x 5) px at g=40).  portrait_enlarge is NOT usable on them: it models the
# scanlines as ONE dark:bright ratio per picture, and these pictures break that model (drone_sm: flat background
# rows are two unrelated palette colours, local ratio 0.30 vs 0.41 for the picture) -> the flat field came back as
# five dithered colours = a resampled dither (user 2026-10-03).
# Law: NO scanline model.  The two scanline FIELDS (interior rows of one parity) are enlarged independently with
# Lanczos-3, each sampled at its own true row centres, and laid back as EVEN scanlines art_scan_rows(num, den)
# device rows thick: interior device row y shows field ((y + phase) // T) & 1, phase = art_scan_phase(y0 + jt) --
# the DEST BUFFER's stripe grid (2026-10-06; before, the first stripe was the picture's first interior row's).  T = max(2, num // den): bright and dark always the same thickness (an uneven duty
# brightens the picture 9-16% and is a banding class), never thicker than vanilla x scale beyond the 2-row floor.
# User-approved on pixel-exact sheets at g = 22 / 25 / 40 (2026-10-03): the 1-row parity scanline of art_reblit
# is too fine to see at 4K (the pristine art shows clear red scanlines behind drone_sm's face), 3 rows at g = 40
# reads coarser than the art.  Palette fit:
#   - a device texel whose smooth colour EQUALS the colour of the NEAREST source texel of its own field keeps that
#     texel's INDEX and absorbs any carried error (a flat scanline field comes out as its two source indices);
#   - every other texel is error-diffused, the error staying inside its own FIELD (right neighbour, then the
#     next device row of the same field; serpentine per field) so one field never tints the other.  Candidates =
#     PORTRAIT_PAL_LO..HI plus every other index the picture's interior itself uses (the Windows static colours:
#     council_sm is a third navy index 4 -- without them every fitted navy texel moved 55 levels).  Error terms
#     round to nearest (floor shifts darkened every picture ~2 levels).
# Anti-ringing: after each Lanczos pass a sample is clamped, per channel, into the range of the two source samples
# that bracket it on that axis, so a flat field stays flat right up to a hard edge (no overshoot halo) and the
# exact-texel rule holds there.  No sharpening.
# Frame ring (rows / cols the centre map pins to the first / last source row / col): top / bottom rows = the pinned
# source row; the side columns of an interior row = the nearest source row of that row's field (an unframed
# picture's edge column carries the same scanlines as its interior).
#   applies: num > den, both dims >= ART_FIELD_MIN, no key texel inside the frame (a keyed hole cannot be filtered)
ART_FIELD_MIN = 32


def art_scan_rows(num: int, den: int = NATIVE_G) -> int:
    """Device rows per scanline (bright and dark alike) of an enlarged picture: 1 below the ratio 22/16 (screens
    under 1080 px high: user 2026-10-04, 2 rows read too coarse at 1600x900), else max(2, num // den).  The same
    rule as the chrome (stripe_rows)."""
    if num * NATIVE_G < STRIPE_2ROW_MIN_G * den:
        return 1
    return max(2, num // den)


def flag_restripe_bright(y: int, g: int) -> bool:
    """thunk_flag_restripe (the council UN flag, council_sm.pcx: a 98%-pair field the picture enlarges cannot
    carry): DEST-BUFFER row y takes the BRIGHT LUT half iff ((y // T) & 1) == 0, T = stripe_rows(g) -- the one
    stripe thickness, on the buffer's stripe grid like every picture (= stripe_top: bright where the chrome's
    coloured member is).  y = the draw's Y + the row index, never the row index alone (2026-10-06)."""
    return stripe_top(y, g)


def art_scan_field(y: int, num: int, den: int = NATIVE_G) -> int:
    """Interior parity (field) shown by interior device row y."""
    return (y // art_scan_rows(num, den)) & 1


def art_scan_next(y: int, num: int, den: int = NATIVE_G) -> int:
    """The next interior device row below y that shows the same field."""
    t = art_scan_rows(num, den)
    return y + 1 if (y + 1) % t else y + t + 1


def art_scan_ordinal(y: int, num: int, den: int = NATIVE_G) -> int:
    """How many rows of its own field lie above interior device row y (the serpentine counter)."""
    t = art_scan_rows(num, den)
    return (y // (2 * t)) * t + y % t


def art_scan_phase(y0: int, num: int, den: int = NATIVE_G) -> int:
    """The stripe-grid phase of a picture whose row 0 lands on dest-buffer row y0: y0 mod 2T, never negative (a
    replaced portrait may be clipped above the buffer).  Every picture enlarge counts its fields from the DEST
    BUFFER's row 0 (option B stage 2, 2026-10-06), so interior device row y shows field art_scan_field(y + phase)
    with phase = art_scan_phase(y0 + jt) -- the same grid stripe_top gives the chrome drawn into that buffer.
    The dest row is in hand at every draw (thunk_art_reblit_body [ebp-0x18] + the row index; uimod Draw's y0)."""
    return y0 % (2 * art_scan_rows(num, den))


def art_field_applies(src, s_pitch: int, sw: int, sh: int, key: int, num: int, den: int = NATIVE_G) -> bool:
    if not (num > den > 0 and sw >= ART_FIELD_MIN and sh >= ART_FIELD_MIN):
        return False
    if 0 <= key <= 0xFF:
        for y in range(1, sh - 1):
            if key in src[y * s_pitch + 1: y * s_pitch + sw - 1]:
                return False
    return True


def _art_field_taps(n_field: int, k: int, centres):
    """Per device row of field k: (first field row, Q14 taps).  `centres` = the rows' centres in INTERIOR source
    rows (row r spans [r, r+1)); field row m is interior row 2m + k, centre 2m + k + 0.5.  Lanczos-3 in field-row
    units, taps clipped to the field and renormalised, rounding remainder to the largest tap (every set sums to 1)."""
    import math
    out = []
    for c in centres:
        cf = (c - k - 0.5) / 2.0                       # field coordinate: field row m has its centre at m
        lo = max(int(math.floor(cf - PORTRAIT_LANCZOS_A)), 0)
        hi = min(int(math.ceil(cf + PORTRAIT_LANCZOS_A)) + 1, n_field)
        ws = []
        for i in range(lo, hi):
            x = i - cf
            if x == 0.0:
                w = 1.0
            elif abs(x) >= PORTRAIT_LANCZOS_A:
                w = 0.0
            else:
                px = math.pi * x
                w = PORTRAIT_LANCZOS_A * math.sin(px) * math.sin(px / PORTRAIT_LANCZOS_A) / (px * px)
            ws.append(w)
        tot = 0.0
        for w in ws:
            tot += w
        q = [int(math.floor(w / tot * (1 << PORTRAIT_WEIGHT_Q) + 0.5)) for w in ws]
        q[max(range(len(q)), key=lambda t: q[t])] += (1 << PORTRAIT_WEIGHT_Q) - sum(q)
        m0 = int(math.floor(cf))                       # the two field rows that bracket the centre (edge-clamped)
        mn = int(math.floor(cf + 0.5))                 # and the nearest one
        out.append((lo, q, min(max(m0, 0), n_field - 1), min(max(m0 + 1, 0), n_field - 1),
                    min(max(mn, 0), n_field - 1)))
    return out


def _art_field_hull(v, a, b):
    """v clamped per channel into [min(a, b), max(a, b)]."""
    return tuple(min(max(x, min(p, q)), max(p, q)) for x, p, q in zip(v, a, b))


def art_field_enlarge(src, s_pitch: int, sw: int, sh: int, key: int, pal: bytes, num: int, den: int = NATIVE_G,
                      y0: int = 0):
    """Reference field-separated enlarge.  Returns (dw, dh, rows) with rows[j][i] = palette index or None (key:
    leave the dest alone), or None when the law does not apply.  pal = RGBQUAD[256] (b,g,r,x).  y0 = the
    dest-buffer row device row 0 lands on (art_scan_phase): the fields sit on the buffer's stripe grid."""
    if not art_field_applies(src, s_pitch, sw, sh, key, num, den):
        return None
    dw, dh = (sw * num) // den, (sh * num) // den
    crow = [nn_center_index(j, dh, sh) for j in range(dh)]
    ccol = [nn_center_index(i, dw, sw) for i in range(dw)]
    jt = next(j for j in range(dh) if crow[j] > 0)
    jb = next(j for j in range(dh - 1, -1, -1) if crow[j] < sh - 1) + 1
    il = next(i for i in range(dw) if ccol[i] > 0)
    ir = next(i for i in range(dw - 1, -1, -1) if ccol[i] < sw - 1) + 1
    W0, H0, W1, H1 = sw - 2, sh - 2, ir - il, jb - jt
    phase = art_scan_phase(y0 + jt, num, den)          # interior row y is dest row y0 + jt + y

    def rgb_of(idx):
        return pal[idx * 4 + 2], pal[idx * 4 + 1], pal[idx * 4]

    photo = [[rgb_of(src[(y + 1) * s_pitch + x + 1]) for x in range(W0)] for y in range(H0)]
    half = 1 << (PORTRAIT_WEIGHT_Q - 1)
    import math
    tx = _portrait_taps(W0, W1)
    scale = W0 / W1
    bx = []                                            # per device column: the two bracketing source columns
    for o in range(W1):
        i0 = int(math.floor((o + 0.5) * scale - 0.5))
        bx.append((min(max(i0, 0), W0 - 1), min(max(i0 + 1, 0), W0 - 1)))
    hor = [[_art_field_hull(tuple(_portrait_clamp8((sum(q[t] * row[lo + t][c] for t in range(len(q))) + half)
                                                   >> PORTRAIT_WEIGHT_Q) for c in range(3)), row[i0], row[i1])
            for (lo, q), (i0, i1) in zip(tx, bx)] for row in photo]
    # vertical, per field: interior device row y shows field art_scan_field(y); near[y] = the nearest SOURCE row
    # of that field (interior row r is source row r + 1)
    big = [None] * H1
    near = [0] * H1
    for k in (0, 1):
        ys = [y for y in range(H1) if art_scan_field(y + phase, num, den) == k]
        n_field = (H0 - k + 1) // 2
        taps = _art_field_taps(n_field, k, [(y + 0.5) * H0 / H1 for y in ys])
        for y, (lo, q, m0, m1, mn) in zip(ys, taps):
            near[y] = art_scan_near(y, H0, H1, num, den, phase)   # one definition, shared with art_reblit_row (== 2*mn+k+1)
            big[y] = [_art_field_hull(tuple(_portrait_clamp8((sum(q[t] * hor[2 * (lo + t) + k][x][c]
                                                                  for t in range(len(q))) + half) >> PORTRAIT_WEIGHT_Q)
                                            for c in range(3)), hor[2 * m0 + k][x], hor[2 * m1 + k][x])
                      for x in range(W1)]
    used = set()
    for y in range(1, sh - 1):
        used.update(src[y * s_pitch + 1: y * s_pitch + sw - 1])
    extra = sorted(i for i in used if not PORTRAIT_PAL_LO <= i <= PORTRAIT_PAL_HI and i != key)
    cands = [(i,) + rgb_of(i) for i in list(range(PORTRAIT_PAL_LO, PORTRAIT_PAL_HI + 1)) + extra]
    wr, wg, wb = PORTRAIT_DIST_WEIGHTS
    err = [[[0, 0, 0] for _ in range(W1)] for _ in range(H1)]
    fit = [[0] * W1 for _ in range(H1)]
    for y in range(H1):
        dx = 1 if (art_scan_ordinal(y + phase, num, den) & 1) == 0 else -1    # serpentine per FIELD, on the grid
        oy_ = art_scan_next(y + phase, num, den) - (y + phase)
        r_src = near[y]
        for x in (range(W1) if dx == 1 else range(W1 - 1, -1, -1)):
            t = src[r_src * s_pitch + art_reblit_col(il + x, sw, num, den)]
            if rgb_of(t) == big[y][x]:                 # the field's own nearest texel: keep its index, drop the error
                fit[y][x] = t
                continue
            r, g_, b = (_portrait_clamp8(v + e) for v, e in zip(big[y][x], err[y][x]))
            best, bd, pick = 0, None, (0, 0, 0)
            for ci, cr, cg, cb in cands:
                d = wr * (cr - r) * (cr - r) + wg * (cg - g_) * (cg - g_) + wb * (cb - b) * (cb - b)
                if bd is None or d < bd:
                    best, bd, pick = ci, d, (cr, cg, cb)
            fit[y][x] = best
            e3 = [((v - p) * PORTRAIT_DITHER_Q8 + 128) >> 8 for v, p in zip((r, g_, b), pick)]
            for ox, oy, kk in ((dx, 0, 7), (-dx, oy_, 3), (0, oy_, 5), (dx, oy_, 1)):
                xx, yy = x + ox, y + oy
                if 0 <= xx < W1 and yy < H1:
                    for c in range(3):
                        err[yy][xx][c] += (e3[c] * kk + 8) >> 4
    rows = []
    for j in range(dh):
        line = []
        r_ring = near[j - jt] if jt <= j < jb else crow[j]
        for i in range(dw):
            if jt <= j < jb and il <= i < ir:
                line.append(fit[j - jt][i - il])
            else:
                v = src[r_ring * s_pitch + ccol[i]]
                line.append(None if v == key else v)
        rows.append(line)
    return dw, dh, rows


def portrait_rgbquad_from_paletteentry(pe: bytes) -> bytes:
    out = bytearray(256 * 4)
    for i in range(256):
        out[i * 4], out[i * 4 + 1], out[i * 4 + 2] = pe[i * 4 + 2], pe[i * 4 + 1], pe[i * 4]
    return bytes(out)


def portrait_is_native_art(w: int, h: int, sw: int, sh: int, framed: bool = True) -> bool:
    return (w, h) == (sw, sh) or (framed and (w, h) == (sw - 2, sh - 2))


def portrait_bake_native(rgb: bytes, w: int, h: int, sw: int, sh: int, pal: bytes,
                         framed: bool = True) -> Optional[List[List[int]]]:
    """Nearest-colour (no dither, no scanlines) of a native-art replacement: the interior of framed art (frame
    stripped from a full-size image), the whole sprite of unframed art."""
    if not portrait_is_native_art(w, h, sw, sh, framed) or sw < 3 or sh < 3 or len(rgb) < w * h * 3:
        return None
    o = 1 if framed and (w, h) == (sw, sh) else 0
    m = 2 if framed else 0                            # rows/cols the frame takes
    wr, wg, wb = PORTRAIT_DIST_WEIGHTS
    cands = [(i, pal[i * 4 + 2], pal[i * 4 + 1], pal[i * 4]) for i in range(PORTRAIT_PAL_LO, PORTRAIT_PAL_HI + 1)]
    out = []
    for y in range(sh - m):
        row = []
        for x in range(sw - m):
            p = ((y + o) * w + x + o) * 3
            r, g_, b = rgb[p], rgb[p + 1], rgb[p + 2]
            row.append(min(cands, key=lambda c: (wr * (c[1] - r) ** 2 + wg * (c[2] - g_) ** 2 + wb * (c[3] - b) ** 2,
                                                  c[0]))[0])
        out.append(row)
    return out


def portrait_scanline_params(src, s_pitch: int, sw: int, sh: int, pal: bytes) -> Tuple[int, int]:
    """(bright, ratio_q8) of framed, scanlined art: portrait_enlarge step 1, over the interior."""
    W0, H0 = sw - 2, sh - 2
    lum = []
    for y in range(H0):
        s = 0
        for x in range(W0):
            i = src[(y + 1) * s_pitch + x + 1]
            s += 77 * pal[i * 4 + 2] + 150 * pal[i * 4 + 1] + 29 * pal[i * 4]
        lum.append(s)
    ev, od = sum(lum[0::2]), sum(lum[1::2])
    n_ev, n_od = len(lum[0::2]), len(lum[1::2])
    bright = 0 if ev * n_od >= od * n_ev else 1
    b_sum, b_n, d_sum, d_n = (ev, n_ev, od, n_od) if bright == 0 else (od, n_od, ev, n_ev)
    return bright, min((d_sum * b_n * 256) // max(b_sum * d_n, 1), 256)


def portrait_prereduce_factor(w: int, h: int) -> int:
    return max(1, -(-max(w, h) // PORTRAIT_SRC_MAX_LONG))


def portrait_prereduce(rgb: bytes, w: int, h: int):
    """Box-average k x k blocks (k = portrait_prereduce_factor), rounding half up; trailing partial blocks dropped.
    rgb: w*h*3 bytes, r,g,b.  Returns (bytes, w // k, h // k)."""
    import numpy as np
    k = portrait_prereduce_factor(w, h)
    if k == 1:
        return bytes(rgb), w, h
    a = np.frombuffer(bytes(rgb), dtype=np.uint8).reshape(h, w, 3).astype(np.int64)
    nw, nh = w // k, h // k
    s = a[:nh * k, :nw * k].reshape(nh, k, nw, k, 3).sum(axis=(1, 3))
    n = k * k
    return ((s + n // 2) // n).astype(np.uint8).tobytes(), nw, nh


def portrait_frame_rect(w: int, h: int, tw: int, th: int) -> Tuple[int, int, int, int]:
    """Cover crop (x, y, cw, ch) of a w x h image to the tw:th aspect.  Degenerate input (any side < 1): the whole
    image (w, h clamped to >= 0) -- portrait_from_rgb then declines it."""
    if w < 1 or h < 1 or tw < 1 or th < 1:
        return 0, 0, max(w, 0), max(h, 0)
    if w * th > h * tw:                                  # too wide: full height, centred
        cw = max(1, (h * tw) // th)
        return (w - cw) // 2, 0, cw, h
    ch = max(1, (w * th) // tw)                          # too tall (or exact): full width, top-biased
    return 0, ((h - ch) * PORTRAIT_FRAME_TOP_NUM) // PORTRAIT_FRAME_TOP_DEN, w, ch


def _portrait_weight_matrix(n_in: int, n_out: int):
    import numpy as np
    m = np.zeros((n_out, n_in), dtype=np.int64)
    for o, (lo, q) in enumerate(_portrait_taps(n_in, n_out)):
        m[o, lo:lo + len(q)] = q
    return m


def portrait_scan_rows(big, th: int, scan: int, bright: int, ratio_q8: int, y0: int, rows: int = 1) -> None:
    """Apply the scanline mode in place to an int64 (th, tw, 3) array.  Scanlines are `rows` rows thick (1 at native
    size; art_scan_rows(num, den) on an enlarge, the chrome's thickness).  y0 = the stripe-grid row of output row 0
    (a native bake: the interior row, 0 = the first row inside the frame, -1 = an unframed sprite's top row; an
    enlarge: the dest buffer's phase, art_scan_phase).  Grid row u is dark iff ((u // rows) & 1) != bright -- the
    vanilla art's own field when rows == 1."""
    import numpy as np
    if scan == PORTRAIT_SCAN_OFF or ratio_q8 >= 256:
        return
    d = 256 + ratio_q8
    for y in range(th):
        dark = (((y0 + y) // rows) & 1) != bright
        if scan == PORTRAIT_SCAN_OVERLAY:
            if dark:
                big[y] = (big[y] * ratio_q8) >> 8
        elif dark:
            big[y] = (big[y] * 2 * ratio_q8 + d // 2) // d
        else:
            big[y] = np.minimum((big[y] * 512 + d // 2) // d, 255)


def portrait_from_rgb(rgb: bytes, w: int, h: int, crop: Tuple[int, int, int, int], tw: int, th: int, pal: bytes,
                      scan: int, bright: int, ratio_q8: int, y0: int, rows: int = 1) -> Optional[List[List[int]]]:
    """tw x th palette indices for a (pre-reduced) RGB image's crop.  y0 / rows = portrait_scan_rows' phase / thickness
    (y0 = the stripe-grid row of output row 0: the interior row for a native bake, the dest-buffer phase for an
    enlarge).  None on degenerate input (empty image / target, crop outside the image)."""
    import numpy as np
    cx, cy, cw, ch = crop
    if (w < 1 or h < 1 or tw < 1 or th < 1 or cw < 1 or ch < 1 or cx < 0 or cy < 0 or cx + cw > w or cy + ch > h
            or len(rgb) < w * h * 3):
        return None
    a = np.frombuffer(bytes(rgb)[:w * h * 3], dtype=np.uint8).reshape(h, w, 3)[cy:cy + ch, cx:cx + cw].astype(np.int64)
    half = 1 << (PORTRAIT_WEIGHT_Q - 1)
    mx, my = _portrait_weight_matrix(cw, tw), _portrait_weight_matrix(ch, th)
    hor = np.empty((ch, tw, 3), dtype=np.int64)
    for c in range(3):
        hor[:, :, c] = np.clip((a[:, :, c] @ mx.T + half) >> PORTRAIT_WEIGHT_Q, 0, 255)
    big = np.empty((th, tw, 3), dtype=np.int64)
    for c in range(3):
        big[:, :, c] = np.clip((my @ hor[:, :, c] + half) >> PORTRAIT_WEIGHT_Q, 0, 255)
    portrait_scan_rows(big, th, scan, bright, ratio_q8, y0, rows)
    cand = np.arange(PORTRAIT_PAL_LO, PORTRAIT_PAL_HI + 1)
    pr = np.array([pal[i * 4 + 2] for i in cand], dtype=np.int64)
    pg = np.array([pal[i * 4 + 1] for i in cand], dtype=np.int64)
    pb = np.array([pal[i * 4] for i in cand], dtype=np.int64)
    wr, wg, wb = PORTRAIT_DIST_WEIGHTS
    acc = big.tolist()
    fit = [[0] * tw for _ in range(th)]
    for y in range(th):
        dx = 1 if (y & 1) == 0 else -1
        for x in (range(tw) if dx == 1 else range(tw - 1, -1, -1)):
            r, g_, b = (_portrait_clamp8(v) for v in acc[y][x])
            k = int(np.argmin(wr * (pr - r) ** 2 + wg * (pg - g_) ** 2 + wb * (pb - b) ** 2))   # first minimum
            fit[y][x] = int(cand[k])
            err = (portrait_shr_round((r - int(pr[k])) * PORTRAIT_DITHER_Q8, 8),
                   portrait_shr_round((g_ - int(pg[k])) * PORTRAIT_DITHER_Q8, 8),
                   portrait_shr_round((b - int(pb[k])) * PORTRAIT_DITHER_Q8, 8))
            for ox, oy, kk in ((dx, 0, 7), (-dx, 1, 3), (0, 1, 5), (dx, 1, 1)):
                xx, yy = x + ox, y + oy
                if 0 <= xx < tw and yy < th:
                    for c in range(3):
                        acc[yy][xx][c] += portrait_shr_round(err[c] * kk, 4)
    return fit


def portrait_bake(sw: int, sh: int, pal: bytes, rgb: bytes, w: int, h: int, scan: int, bright: int,
                  ratio_q8: int, framed: bool = True) -> Optional[List[List[int]]]:
    """Native-size replacement: framed art -> the (sw-2) x (sh-2) interior, frame untouched; unframed art (the
    council slots) -> the whole sw x sh sprite.  (bright, ratio_q8) = portrait_scanline_params of the VANILLA art,
    captured before the first bake (a re-bake must not re-measure).  A native-art image (portrait_is_native_art)
    takes portrait_bake_native instead.  None if degenerate."""
    if sw < 3 or sh < 3:
        return None
    if portrait_is_native_art(w, h, sw, sh, framed):
        return portrait_bake_native(rgb, w, h, sw, sh, pal, framed)
    if w < 1 or h < 1:
        return None
    m = 2 if framed else 0
    crop = portrait_frame_rect(w, h, sw - m, sh - m)
    return portrait_from_rgb(rgb, w, h, crop, sw - m, sh - m, pal, scan, bright, ratio_q8, 0 if framed else -1)


def portrait_enlarge_rgb(src, s_pitch: int, sw: int, sh: int, key: int, pal: bytes, num: int, den: int,
                         rgb: bytes, w: int, h: int, scan: int, bright: int, ratio_q8: int, framed: bool = True,
                         y0: int = 0):
    """portrait_enlarge with the interior drawn from a replacement RGB image.  src = the art's own pixels (the frame
    comes from them; after a native bake its interior is ignored).  (bright, ratio_q8) come from the VANILLA art,
    captured before the bake -- measuring the bake would be circular.  Same geometry and return as portrait_enlarge;
    applies at num > den for any framed art (no shape gate: the caller identified the slot).  None for a native-art
    image (the caller enlarges its bake with portrait_enlarge) and on degenerate input.  y0 = the dest-buffer row
    device row 0 lands on: the scanlines sit on the buffer's stripe grid (art_scan_phase)."""
    if not (num > den > 0 and sw >= 3 and sh >= 3) or portrait_is_native_art(w, h, sw, sh, framed) or w < 1 or h < 1:
        return None
    dw, dh = (sw * num) // den, (sh * num) // den
    t = art_scan_rows(num, den)
    crow = [nn_center_index(j, dh, sh) for j in range(dh)]
    jt = next(j for j in range(dh) if crow[j] > 0)       # the first device row of the art's interior source rows
    if not framed:                                    # the whole device rect is picture: no frame to keep
        fit = portrait_from_rgb(rgb, w, h, portrait_frame_rect(w, h, sw, sh), dw, dh, pal, scan, bright, ratio_q8,
                                art_scan_phase(y0, num, den), t)
        if fit is None:
            return None
        return dw, dh, [list(r) for r in fit]
    ccol = [nn_center_index(i, dw, sw) for i in range(dw)]
    jb = next(j for j in range(dh - 1, -1, -1) if crow[j] < sh - 1) + 1
    il = next(i for i in range(dw) if ccol[i] > 0)
    ir = next(i for i in range(dw - 1, -1, -1) if ccol[i] < sw - 1) + 1
    W1, H1 = ir - il, jb - jt
    if W1 <= 0 or H1 <= 0:
        return None
    crop = portrait_frame_rect(w, h, sw - 2, sh - 2)       # the NATIVE interior aspect: same framing at every g
    fit = portrait_from_rgb(rgb, w, h, crop, W1, H1, pal, scan, bright, ratio_q8, art_scan_phase(y0 + jt, num, den), t)
    if fit is None:
        return None
    rows = []
    for j in range(dh):
        line = []
        for i in range(dw):
            if jt <= j < jb and il <= i < ir:
                line.append(fit[j - jt][i - il])
            else:
                v = src[crow[j] * s_pitch + ccol[i]]
                line.append(None if v == key else v)
        rows.append(line)
    return dw, dh, rows


# ==== base screen: NUTRIENTS / MINERALS / ENERGY intake bars (pips) (2026-09-21) ===================================
# BaseWin_draw_expenses (0x412AA0) draws each bar as PIPS: native pitch p (register esi at every pip draw), pip width
# max(1, p-1), x advancing by p from the bar start x0 = [ebp-0x20] (the text end Buffer_write_l_4 returned); the bar
# is PIPBAR_SPAN = 0xC2 native px (`0xC2 / p + 1` pips at most).  Twelve Buffer_tile_2 sites + six GraphicWin_fill_2
# sites, three bars.  Scaling each pip edge on its own gives widths 2,1,2,1,2,2 at 25/16 for p = 2 (user's big-base
# shots 2026-09-21, measured) -- vanilla is even by construction.  Same cure as nutgrid_layout, horizontally: ONE
# device pitch per bar, capped so the longest bar cannot overrun its native span; pip k sits at pt(x0) + k*P.
# A pip that is not on the bar's native grid (x < x0, (x-x0) % p != 0, k beyond the bar) keeps the plain edge law.
PIPBAR_SPAN = 0xC2
PIPBAR_MIN_PITCH = 2


def pipbar_applies(x0: int, pitch: int, x: int, g: int) -> bool:
    if g <= NATIVE_G or pitch < PIPBAR_MIN_PITCH or x < x0 or (x - x0) % pitch:
        return False
    return (x - x0) // pitch <= PIPBAR_SPAN // pitch + 1


def pipbar_snap(g: int) -> int:
    """How far (device px) two bars' starts may differ and still be ONE column.  x0 is the text end the engine
    measured: '013 - 000' and '008 - 004' differ by a device pixel in the scaled font and the native round-trip
    (ceil down, floor up) doubles it -- the MINERALS bar sat 2 px right of the other two (user 2026-09-21).
    Vanilla's three bars share one start; so do ours: a bar within the snap of the last bar start reuses it."""
    return (g >> 4) + 2


def pipbar_top(prev_top: int, x0: int, g: int) -> int:
    top = (x0 * g) >> 4
    return prev_top if abs(prev_top - top) <= pipbar_snap(g) else top


def pipbar_pip(x0: int, pitch: int, x: int, width: int, g: int, prev_top: Optional[int] = None) -> Tuple[int, int]:
    """(x', W') of the pip drawn natively at x with width `width`.  Native args; device result."""
    if not pipbar_applies(x0, pitch, x, g):
        left = (x * g) >> 4
        return left, (((x + width) * g) >> 4) - left
    n = PIPBAR_SPAN // pitch + 1
    top = (x0 * g) >> 4
    span = (((x0 + n * pitch) * g) >> 4) - top
    P = max(min(half_down(pitch * g, NATIVE_G), span // n), 1)
    cell = max(P - stroke_width(g), (P + 1) >> 1)
    if cell >= P:
        cell = max(P - 1, 1)
    if prev_top is not None:
        top = pipbar_top(prev_top, x0, g)
    return top + ((x - x0) // pitch) * P, cell


# ==== map: unit move / goto path line + its "Move to" label (2026-09-24) ==========================================
# MapWin_on_mouse_move 0x46F000 (drag a unit) and draw_my_dest 0x4B4BF0 (a unit's Go-To order) draw on the Console's
# buffered overlay GraphicWin (+0x444, Buffer 0x93755C): every hop of the path is ONE Buffer_line_2 call (1px
# Bresenham, thiscall (x1,y1,x2,y2,color) RET 0x14; x-major when |dx| >= |dy|, delegates to vline/hline when
# x1==x2 / y1==y2, draws NOTHING for a zero-length line) from MapWin_direct_dest_line @0x4673DC, and the label is
# Buffer_write_l_3 with find_font(12,1) + Buffer_set_text_color(0x9F, shadow 0x41, dx 1, dy 1).  The overlay is
# cleared whole (GraphicWin_fill(9)) and presented whole, so nothing else bounds the drawing.
#
# LINE LAW: K = stroke_width(g) parallel copies of the vanilla line, offset along its MINOR axis (y for an x-major
# line, x for a y-major one) by move_line_offsets(g) = lo..lo+K-1, lo = -((K-1)>>1): the offset-0 copy IS the
# vanilla line (vanilla pixels are a subset), an even K puts its extra pixel on the + side (down / right, the side
# the label's text shadow already falls on).  Minor-axis offsets give every major-axis step exactly K pixels.
# JOINTS: consecutive hops share an endpoint and can leave by different axes (a vertical hop offset in x meets a
# horizontal hop offset in y): the outer corner of the joint's K x K cross-section is then covered by neither
# (a notch, K >= 2).  So each hop also plugs both endpoints with the K x K square offsets x offsets (K rows of
# Buffer_hline_2, span K-1 >= 1 -- never the zero-span no-op).  At a polyline's two free ends the plug is a
# square cap reaching K-1 px past the vanilla endpoint on the + side.  K <= 1 (every g <= 24) and zero-length
# lines are the ONE native call, unchanged.
# LABEL: font = font_face_law(12, 1, g) (t_ffn: Arial 12 bold -> Arial bold fl(12g/16), native at g <= 16); the
# text-shadow offset (dx, dy) = move_label_shadow(dx, dy, g) = scale_px each (1 -> stroke_width(g)).
# PORT: work/scripts/assemble_move_line.py (t_ml_line, t_ml_textcolor); parity tests/test_move_line_asm_parity.py.
MOVE_LABEL_FONT = (12, 1)             # find_font(12, 1) @0x46F595
MOVE_LABEL_SHADOW = (1, 1)            # Buffer_set_text_color(.., 0x9F, 0x41, 1, 1) @0x46F586


def move_line_offsets(g: int) -> List[int]:
    """The K minor-axis offsets of the thickened path line: lo..lo+K-1 with lo = -((K-1)>>1); [0] at K == 1."""
    k = stroke_width(g)
    lo = -((k - 1) >> 1)
    return [lo + i for i in range(k)]


def move_line_calls(x1: int, y1: int, x2: int, y2: int, g: int) -> List[Tuple]:
    """The draw calls that replace ONE vanilla Buffer_line_2(x1, y1, x2, y2, color), in the port's order:
      ('line', x1', y1', x2', y2')   Buffer_line_2 copies, offset by move_line_offsets(g) along the minor axis;
      ('hline', x0, x1, y)          Buffer_hline_2 rows of the K x K endpoint plugs, (x1,y1) first then (x2,y2).
    g <= 16, K <= 1, or a zero-length line -> [('line', x1, y1, x2, y2)] = the vanilla call."""
    k = stroke_width(g)
    if g <= NATIVE_G or k <= 1 or (x1 == x2 and y1 == y2):
        return [("line", x1, y1, x2, y2)]
    offs = move_line_offsets(g)
    x_major = abs(x2 - x1) >= abs(y2 - y1)
    calls: List[Tuple] = []
    for o in offs:
        ox, oy = (0, o) if x_major else (o, 0)
        calls.append(("line", x1 + ox, y1 + oy, x2 + ox, y2 + oy))
    lo = offs[0]
    for px, py in ((x1, y1), (x2, y2)):
        for r in offs:
            calls.append(("hline", px + lo, px + lo + k - 1, py + r))
    return calls


PLANWIN_NATIVE_W, PLANWIN_NATIVE_H = 239, 119   # vanilla's Go To panel at g=16 (PlanWin rect copy 0x939F08 = 780,88,1019,207)


def planwin_native_dims(dev_w: int, dev_h: int, g: int) -> Tuple[int, int]:
    """The Go To / battle-plan map panel (PlanWin 0x834D70) renders at VANILLA's panel size and is enlarged into its
    device-size window (user decision 2026-10-15, option (b)).  The engine draws map tiles at fixed native sizes per
    zoom, so a device-size panel showed the whole planet small inside black margins at a far fit (zoom -14 = 320 x 160
    in 597 x 297 at 4K, shot 20261015-002643) or pushed the destination off the panel at a floored zoom (v1, 1600
    shot 20261014-231100): no engine zoom frames a trip the way vanilla does at this panel size.  So every PlanWin
    draw (fit_two / fit_one / render / overlay_draw) sees its canvas as vanilla's 239 x 119 (the Buffer's own
    w / h / clip / bounds -- calc_dims 0x462980 sizes the tile window from +0x4C4 / +0x4C8), and the native image is
    enlarged x g/16 into the device canvas before the present.  g <= 16: the device dims (no-op); never larger than
    the device canvas."""
    if g <= NATIVE_G:
        return dev_w, dev_h
    return min(PLANWIN_NATIVE_W, dev_w), min(PLANWIN_NATIVE_H, dev_h)


def planwin_enlarge(native: List[List[int]], dev_w: int, dev_h: int) -> List[List[int]]:
    """The enlargement of the native PlanWin image into the device canvas: centre-sampled, edge-clamped NN on the
    8-bit palette indices (nn_center_index both axes).  NN, not a smooth filter: the canvas is palette-indexed (an
    average of two indices is a third, unrelated colour), and the map art is tile pixel art, not an ordered
    2-colour dither (the stripe rule does not apply).  Done in place in the device canvas (the native image sits
    in its top-left corner): source index <= dest index on both axes for an enlargement, so walking rows and
    columns from the last to the first never reads a pixel already written."""
    nh, nw = len(native), len(native[0])
    return [[native[nn_center_index(j, dev_h, nh)][nn_center_index(i, dev_w, nw)] for i in range(dev_w)]
            for j in range(dev_h)]


def planwin_line_calls(x1: int, y1: int, x2: int, y2: int, dash_on: int, dash_off: int, phase: int,
                       g: int) -> List[Tuple[int, int, int, int, int, int, int]]:
    """The Buffer_line (0x5E09D0, dashed) calls that replace ONE vanilla route-line draw on the Go To / battle-plan
    map panel (PlanWin 0x834D70: PlanWin_overlay_draw 0x48B370) -- since 2026-10-15 the panel renders natively and is
    enlarged (planwin_native_dims), so its line stays the engine's; this law now serves the MAIN map's dashed order
    lines (MapWin_direct_dest_line 0x46741E via t_map_dash).  Same thickening law as the
    map path line (move_line_calls): K = stroke_width(g) copies offset along the MINOR axis by move_line_offsets;
    every copy shares the scaled dash pattern (on / off / phase each scale_px, vanilla x g/16), so the dashes stay
    in register across the copies.  No endpoint plugs: a dashed line's ends may fall in a gap.  The dashes scale
    at EVERY g > 16, independent of K (audit 2026-10-12: gating them on K > 1 left 4/4 dashes at g 17..24, 4 -> 6
    between g 24 and 25); K = 1 -> one copy with the scaled pattern.  g <= 16: [the vanilla call]."""
    if g <= NATIVE_G:
        return [(x1, y1, x2, y2, dash_on, dash_off, phase)]
    on, off, ph = scale_px(dash_on, g), scale_px(dash_off, g), scale_px(phase, g)
    x_major = abs(x2 - x1) >= abs(y2 - y1)
    out = []
    for o in move_line_offsets(g):
        ox, oy = (0, o) if x_major else (o, 0)
        out.append((x1 + ox, y1 + oy, x2 + ox, y2 + oy, on, off, ph))
    return out


MAP_DEST_SLOT_SHIFT = {1: (1, 1), 2: (0, -1)}   # vanilla 1-px slot separations of the non-overlay arm (dx, dy)


def map_dest_slot_shift(mode: int, g: int) -> Tuple[int, int]:
    """The endpoint shift of a main-map dashed order line by slot: MapWin_direct_dest_line 0x4672C0's non-overlay
    arm (overlay == 0) moves slot 1 by (+1, +1) and slot 2 by (0, -1) (pristine 0x46734A..0x46737C), so a base's
    up-to-three destination lines (MapWin_draw_base_dest, slot = mode) lie side by side.  Those lines are K =
    stroke_width(g) px thick (planwin_line_calls), so each 1-px separation is vanilla x g/16 = scale_px(1, g) = K:
    with the vanilla 1-px shift the slot-0 line is covered on a shared leg (audit 2026-10-14).  Other modes: no
    shift.  g <= 16: the vanilla shift."""
    dx, dy = MAP_DEST_SLOT_SHIFT.get(mode, (0, 0))
    if g <= NATIVE_G:
        return dx, dy
    return dx * scale_px(1, g), dy * scale_px(1, g)


def move_label_shadow(dx: int, dy: int, g: int) -> Tuple[int, int]:
    """The label's text-shadow offset (Buffer +0x55C / +0x56C): vanilla x g/16, native at g <= 16."""
    if g <= NATIVE_G:
        return dx, dy
    return scale_px(dx, g), scale_px(dy, g)


# ==== MP NEGOTIATION WINDOW (DiploWin 0x73ACD8; builder DiploWin_build 0x443F10, draw 0x4436C0) ===================
# The multiplayer negotiation window (Thinker "DiploWin"; opened by diplo 0x444D90).  Vanilla builds a
# 832 x (0x254 - strip) GraphicWin over the console (x=(SW-800)/2, y=SH-strip-h) and derives every child rect from
# (w, h) by additive immediates, storing them in the object BEFORE GraphicWin_init @0x444617 and the widget
# attaches (pristine disassembly 0x443F82..0x4445DB).  Our HUD seed scale makes the strip device-sized, so vanilla's
# h = 596 - strip collapses (383/304/264/64 at g=16/22/25/40): the window must scale as a whole.
#
# The law is vanilla's cascade at device density with the diplo-family FLOOR dp(): positions are CUMULATIVE from
# the edge they hang off (top chain from 0, bottom chain from h -- layout Law A), every 20-px bar keeps ONE pinned
# height dp(20) (the button zoom recovers the native face by CEIL), and the faction panels are pinned to the art
# they frame (Law B: vanilla's panel B = ring.T - 7 lands flush on the 198-px art + 1-px strokes only because
# h = 383; a per-constant floor would open a 4-10 px gap).  The panel -> ring gap absorbs the remainder.
# Mixed space: the strip and the MainWin seed DC0 (0x7AF5E0) arrive DEVICE-scaled; only vanilla's constants scale.
# The frame's left edge = the scaled left rails' extent ((15g>>4)+(8g>>4), thunk_popup_d690insets' cascade) and its
# right edge = the right rails' double-floor anchor, so frame and rails abut at every g (the BaseWin v3 lesson).
DW_W, DW_HBASE, DW_CENTER_W = 0x340, 0x254, 0x320
DW_RAIL_L = (15, 8)             # left rail strips (outer, inner): frame L = their scaled extent
DW_RAIL_R = 0x37                # right rails start at W - 0x37 (0x20 gap + 8 + 15): frame R abuts them
DW_IN = 7                       # frame -> content column (and header top)
DW_PAD = 3                      # ring / text inset
DW_GAP = 2                      # column gap
DW_GAP_MID = 8                  # the TRADE | DIPLOMACY centre split
DW_BAR_H = 0x14                 # every 20-px bar: buttons, headers, name boxes, title
DW_HDR_T, DW_NAME_T, DW_PANEL_T = 7, 30, 53     # top chain (from frame.T = 0)
DW_ROW3_B, DW_ROW2_B, DW_ROW1_B = 0x1A, 0x38, 0x4E   # bottom chain: row bottoms, up from h (26/56/78)
DW_THDR_B = 0x64                # TRADE / DIPLOMACY header bottom, up from h (100)
DW_ART = (164, 198)             # faction art (g_faction_art[f] + 0x84)
DW_CAPTION = 0x1A               # Win+0x16C caption size
DW_CHAT_IN, DW_CHAT_B = 4, 0x1B # chat box inside DC0: L/T/R inset, bottom inset
DW_EDIT_T, DW_EDIT_B = 0x18, 4  # edit box, up from DC0.B
DW_TS_IN = 3                    # TextScroll_attach inset inside the chat box
DW_BUTTONS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)   # ids with a widget (0/1 are command-only)


def dw_window_rect(screen_w: int, screen_h: int, strip_h: int, g: int) -> Tuple[int, int, int, int]:
    """LAW -- DiploWin (x, y, w, h).  strip_h arrives device-scaled (never re-scaled); vanilla has no height cap.
    g=16: ((SW-800)/2, SH-596, 832, 596-strip)."""
    w = dp(DW_W, g)
    h = dp(DW_HBASE, g) - strip_h
    x = _idiv(screen_w - dp(DW_CENTER_W, g), 2)
    y = (screen_h - strip_h) - h
    return (x, y, w, h)


def dw_frame_lr(w: int, g: int) -> Tuple[int, int]:
    """Frame (+0xEDC) L / R: abut the scaled side rails (left: the two strips' floor cascade; right: the
    railscale double-floor anchor).  g=16: (0x17, w - 0x37)."""
    if g <= NATIVE_G:
        return sum(DW_RAIL_L), w - DW_RAIL_R
    assert DW_RAIL_L == SE_RAIL_LEFT_STRIPS          # the same two left strips every slide window draws
    left = rail_left_extent(g)
    right = popup_scale_floor(rail_right_anchor(w, w - DW_RAIL_R, g), g)
    return left, right


def dw_layout(w: int, h: int, dc0: Tuple[int, int, int, int], g: int) -> dict:
    """LAW -- every live DiploWin layout rect, {field offset: (L, T, R, B)}, window-local except the chat /
    edit boxes (0xF3C / 0xF2C: MainWin-canvas coords from the DEVICE seed DC0).  g=16 reproduces
    DiploWin_build 0x443F82..0x4445DB verbatim (tests pin it against the pristine image)."""
    d = lambda v: dp(v, g)                       # noqa: E731
    fl, fr = dw_frame_lr(w, g)
    il, ir = fl + d(DW_IN), fr - d(DW_IN)
    ga, gb, bh, p3 = d(DW_GAP), d(DW_GAP_MID), d(DW_BAR_H), d(DW_PAD)
    r = {0xEDC: (fl, 0, fr, h)}
    ht = d(DW_HDR_T)
    r[0xF4C] = (il, ht, ir, ht + bh)
    hw = _idiv(ir - il + ga, 2)                  # vanilla ((R-L)+2)/2 - 2 halves
    nt = d(DW_NAME_T)
    r[0xF7C] = (il, nt, il + hw - ga, nt + bh)
    r[0xF8C] = (il + hw, nt, ir, nt + bh)        # right half ends at the inner column (vanilla: exact at g=16)
    pt = d(DW_PANEL_T)
    pb = pt + 2 * stroke_width(g) + d(DW_ART[1])  # pinned to the art + one stroke each side
    r[0xF5C] = (il, pt, il + hw - ga, pb)
    r[0xF6C] = (il + hw, pt, ir, pb)
    # row 3: the w/7 column, three cells (vanilla (span+2)/3 - 2)
    t7 = _idiv(fr - fl, 7)
    l3 = fl + t7
    third = _idiv((fr - t7) - l3 + ga, 3)
    b3 = h - d(DW_ROW3_B)
    for i, off in enumerate((0xFFC, 0x100C, 0x101C)):
        r[off] = (l3 + i * third, b3 - bh, l3 + (i + 1) * third - ga, b3)
    # rows 2 / 1: four columns, gaps 2 | 8 | 2.  Vanilla's (span-4)/4 divides exactly at g=16 (4 x 182 + 12 =
    # 740); at device density the cells take cumulative boundaries (LAW 2) so the last column still ends at the
    # inner column, flush with the panels / name boxes above it and the DIPLOMACY header.
    cells = (ir - il) - (2 * ga + gb)
    before = (0, ga, ga + gb, 2 * ga + gb)
    cols = [(il + cum(i, cells, 4) + before[i], il + cum(i + 1, cells, 4) + before[i]) for i in range(4)]
    b2, b1 = h - d(DW_ROW2_B), h - d(DW_ROW1_B)
    for (l, rr), o2, o1 in zip(cols, (0x104C, 0x105C, 0x108C, 0x109C), (0x102C, 0x103C, 0x106C, 0x107C)):
        r[o2] = (l, b2 - bh, rr, b2)
        r[o1] = (l, b1 - bh, rr, b1)
    tb = h - d(DW_THDR_B)
    r[0xF9C] = (cols[0][0], tb - bh, cols[1][1], tb)
    r[0xFBC] = (cols[2][0], tb - bh, cols[3][1], tb)
    for ring, hdr, row2a, row2b in ((0xFAC, 0xF9C, 0x104C, 0x105C), (0xFCC, 0xFBC, 0x108C, 0x109C)):
        r[ring] = (r[hdr][0] - p3, r[hdr][1] - p3, r[row2b][2] + p3, r[row2a][3] + p3)
    r.update(dw_chat_rects(dc0, g))
    return r


def dw_chat_rects(dc0: Tuple[int, int, int, int], g: int) -> dict:
    """LAW -- the chat log (+0xF3C) and edit line (+0xF2C) boxes inside the console centre seed DC0 (DEVICE space
    already: only vanilla's insets scale).  g=16: (L+4, T+4, R-4, B-0x1B) / (L+4, B-0x18, R-4, B-4)."""
    d = lambda v: dp(v, g)                       # noqa: E731
    L, T, R, B = dc0
    chat = (L + d(DW_CHAT_IN), T + d(DW_CHAT_IN), R - d(DW_CHAT_IN), B - d(DW_CHAT_B))
    edit = (chat[0], B - d(DW_EDIT_T), chat[2], B - d(DW_EDIT_B))
    return {0xF3C: chat, 0xF2C: edit}


def dw_caption_size(g: int) -> int:
    return dp(DW_CAPTION, g)


def dw_ts_inset_delta(g: int) -> int:
    """What the TextScroll_attach wrapper adds to vanilla's native-inset args: x/y += d, w/h -= 2d."""
    return dp(DW_TS_IN, g) - DW_TS_IN


# ---- DiploWin painters (0x4436C0 draw, 0x442A10 / 0x442DC0 faction sides, 0x443170 offer lists) ---------------
# Every painter-local constant is an inset off a (now device) layout rect; each scales once, dp().
DW_CONSOLE_IN = 4               # MainWin console frames 0x443714 / 0x443756: seed D90 / D80 inset 4
DW_STATUS_IN, DW_STATUS_H = 4, 0x18   # status box: art (L+4, B-0x18, R-4, B-4), colour-mapped, inset 3 text


def dw_text_inset(rect: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """The write_cent_l_7 text rect: the box inset dp(3) on every side (vanilla 3)."""
    p = dp(DW_PAD, g)
    return (rect[0] + p, rect[1] + p, rect[2] - p, rect[3] - p)


def dw_console_frame(seed: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """The two MainWin console-panel frames the window paints (seed rects are device already)."""
    d = dp(DW_CONSOLE_IN, g)
    return (seed[0] + d, seed[1] + d, seed[2] - d, seed[3] - d)


def dw_ring(union: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """The painter's rings: a union of layout rects grown dp(3) (vanilla 3)."""
    p = dp(DW_PAD, g)
    return (union[0] - p, union[1] - p, union[2] + p, union[3] + p)


def dw_art_rect(panel: Tuple[int, int, int, int], right: bool, art_w: int, art_h: int,
                g: int) -> Tuple[int, int, int, int]:
    """The faction art inside its d528 panel, one stroke K in from the panel edge (vanilla: 1 px, the 1-px
    stroke), left panel left-aligned / right panel right-aligned; drawn at fl(w*g/16) x fl(h*g/16)."""
    k = stroke_width(g) if g > NATIVE_G else 1
    w, h = dp(art_w, g), dp(art_h, g)
    x = panel[2] - k - w if right else panel[0] + k
    y = panel[1] + k
    return (x, y, x + w, y + h)


def dw_status_rect(art: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """The negotiation-status box over the bottom of the art (colour-mapped, then its text inset dp(3))."""
    d = lambda v: dp(v, g)                       # noqa: E731
    return (art[0] + d(DW_STATUS_IN), art[3] - d(DW_STATUS_H), art[2] - d(DW_STATUS_IN), art[3] - d(DW_STATUS_IN))


def dw_offer_pitch(native_metric: int, g: int) -> int:
    """The offer-list row pitch: fl(native line metric x g/16) of vanilla's find_font(14,0) (@0x443184..97:
    [f] < 0 ? [f+0xC] : [f+0x10] + [f]).  NEVER the scaled font's own metric: the pool snaps sizes and line height
    is sublinear in size (feedback_font_metric_sublinearity), and the row loop has no clip -- a scaled-metric pitch
    was +9% at g=22 / +12.5% at g=32, overflowing the art-pinned panel by a row where vanilla fit 12 offers."""
    return dp(native_metric, g)


def dw_offer_list(panel: Tuple[int, int, int, int], right: bool, art_w: int, g: int) -> Tuple[int, int, int]:
    """The offer list beside the art: (x, top, width).  Left panel: art.R + dp(3) .. panel.R - dp(3); right panel:
    panel.L + dp(3) .. art.L - dp(3); top panel.T + dp(3).  Row pitch = the scaled find_font(14,0) line height."""
    p = dp(DW_PAD, g)
    art = dw_art_rect(panel, right, art_w, 0, g)
    x, r = (panel[0] + p, art[0] - p) if right else (art[2] + p, panel[2] - p)
    return (x, panel[1] + p, r - x)


def intel_block_top(flow_y: int, portrait_y: int, portrait_h: int, g: int) -> int:
    """HQ report intel PROFILE page (ReportWin kind 0): the top of the POLITICS / treaty block.  The engine flows it as
    y = rows_end + lineH + s(0x14) with 8..11 dossier rows above (AGENDA / ENERGY RESERVES / RESEARCHING are conditional)
    and vanilla lets it overlap the 131x157 leader portrait by 2 (9 rows) / 17 (8 rows) native px.  Enlarged, the
    portrait is fl(h*g/16) tall (the resampler's idiv law) while the line height is sublinear (36 at g=40, not 37.5), so
    the flow alone deepens that overlap to 18 / 54 device px at 4K.  Law: never above the portrait's drawn bottom plus the
    body inset s(4).  g<=16 -> the engine's flow, untouched (the portrait is native there)."""
    if g <= 16:
        return flow_y
    return max(flow_y, portrait_y + (portrait_h * g) // 16 + scale_px(4, g))


def rw_line_h(engine_metric: int, g: int) -> int:
    """HQ report screens: the shared line height [ReportWin+0xE268] / [ReportIf+0x1C] that every report row pitch,
    header band (lineH+9), console title box (lineH+6) and console list row (lineH+3) consume.  The engine derives it
    from the report font's metric, which is SUBLINEAR once the font is enlarged (36 at g=40 where vanilla's 15 x 2.5 =
    37.5; 24 at g=25 vs 23.4), so at g>16 the lever substitutes scale_px(15, g) -- 15 being the native f12 metric
    measured on the pristine 1024 frame.  g<=16: the engine's own metric read, untouched."""
    if g <= 16:
        return engine_metric
    return scale_px(15, g)


RW_CONSOLE_TITLE_INSET = 0x4C     # pristine `and eax,0x4C` at every console painter's centre-title setup
RW_CONSOLE_LB_INSET = 3           # pristine `+3` (L/T rows) / `mov eax,-3` (R/B) around every console ListBox


def rw_console_title_inset(mask: int, g: int) -> int:
    """HQ report consoles (labs / energy / ops / projects / sat / units / score / intel): the centre title box's left
    shift past the faction logo, x += mask & 0x4C with mask = 0 / -1 (wide layout).  Law: mask & scale_px(0x4C, g)
    (imm8 overflows at g=40: 190).  g=16 -> the native 0x4C exactly; the clamp g>=16 makes it a no-op below."""
    return (mask & scale_px(RW_CONSOLE_TITLE_INSET, g)) & 0xFFFFFFFF


def rw_console_listbox_rb(g: int) -> int:
    """HQ report consoles: the ListBox rect's R/B inset (`mov eax,-3`, added to R and B) -- the mirror of the
    +scale_px(3, g) L/T rows, so the four strokes around the list stay symmetric: -scale_px(3, g)."""
    return -scale_px(RW_CONSOLE_LB_INSET, g)


# ---- HQ report console tab pairs (F2 TECHNOLOGY|BASES, F4 GOVERNOR|BEST BASES), 2026-10-17 ------------------------
# Vanilla (ReportIf_activate 0x4A4554.. / 0x4A472C.., console painters 0x4A701C.. / 0x4A90A8..): the tab box is the d5a0
# {L+6, T+6, L+6 + (W-0xC), T+6+0x1A} on the console panel region (ReportIf +0x20 = L,T,R,B), drawn HALF-OPEN; the two
# buttons sit at {L+9, T+9}, w = W-0x12, h = 0x14, left w = w/2-1, right at L+9+w/2+1.  Pristine (Tech.png, 2.8125x):
# box stroke 1 at the rect's outer row/col, then a 2-px channel to the buttons on all four sides, a 2-px seam,
# left 110 / right 111 at the 1024 panel (W = 241).  9 = 6 (box inset) + 1 (stroke) + 2 (channel).
RW_TAB_BOX_INSET = 6
RW_TAB_BOX_H = 0x1A
RW_TAB_CHANNEL = 2


# ---- HQ report console chrome chain (2026-10-17, console-wide) -----------------------------------------------------
# Vanilla (ReportIf_console_chrome 0x4A3D20 + every console painter's `x/y +6, w/h -0xC` cursor), measured on every
# pristine HQData page at 2.8125x: on all four sides of both side panels the strokes run da50 (the region's own edge,
# 1 px) -- 2-px channel -- d5a0 (region +3, 1 px) -- 2-px channel -- d528 / the page's content box (region +6, 1 px).
# The centre + kind-icon strip: d5a0 at +4, d528 at +7 (channel 2 again).  Scaled independently (s(3) for the d5a0,
# s(6) for the content box) the second channel is s6 - s3 - K: 6 at 4K, 2 at 1600x1200, 3 at 1920x1080 against
# s(2) = 5 / 3 / 3.  Law: chrome pinned to the inner stroke -- the content box sits one STEP U = K + s(2) (stroke +
# channel) inside the d5a0 it nests in, wherever that d5a0 is.
RW_CONSOLE_PANEL_INSET = 3        # the side panels' d5a0 inset (ReportIf_console_chrome `mov edx,3`, scaled s(3))
RW_CONSOLE_CENTRE_INSET = 4       # the centre / strip d5a0 inset (`mov edx,4`, scaled s(4))


def rw_console_step(g: int) -> int:
    """LAW — one nesting step of the console chrome: the next box's outer edge sits K + s(2) inside the enclosing
    box's outer edge (its K-wide stroke, then the s(2) channel).  g <= 16: 3 (1 + 2)."""
    if g <= NATIVE_G:
        return 1 + RW_TAB_CHANNEL
    return stroke_width(g) + scale_px(RW_TAB_CHANNEL, g)


def rw_console_box_inset(g: int) -> int:
    """LAW — a side panel's content box (every console painter's `x/y +6, w/h -0xC` cursor, the d528 title/list/body
    boxes built on it, the F2 / F4 tab boxes) inset from the panel region: the panel d5a0 at s(3), plus one step.
    C = s(3) + K + s(2); the far edges mirror it (w = W - 2C).  g <= 16: 6.  NOT s(6): s(6) != s(3) + K + s(2) at
    g = 18..20 / 23..25 / 29..30 / 34..36 / 39..41 / ... (4K: 15 vs 14, 1600x1200: 9 vs 10)."""
    if g <= NATIVE_G:
        return 2 * RW_CONSOLE_PANEL_INSET
    return scale_px(RW_CONSOLE_PANEL_INSET, g) + rw_console_step(g)


def rw_console_centre_inset(g: int) -> int:
    """LAW — the centre / kind-icon-strip d528 inset from its region: its d5a0 at s(4), plus one step.  g <= 16: 7."""
    if g <= NATIVE_G:
        return RW_CONSOLE_CENTRE_INSET + 3
    return scale_px(RW_CONSOLE_CENTRE_INSET, g) + rw_console_step(g)


RW_STRIP_FRAME_SHIFT = 7          # pristine `add eax,-7` @0x4A3D7A: the kind-icon strip's da50 starts 7 px left of its region
RW_STRIP_SAVE_CAP = 0xC00         # t_rwk_stripframe's stack save area (bytes): the hidden band s(7) x strip h is 17 x 160 at g=40


def rw_strip_frame(region: Tuple[int, int, int, int], g: int) -> dict:
    """LAW — the HQ report kind-icon strip's outer da50 frame (ReportIf_console_chrome 0x4A3D6D..0x4A3D9B).

    Vanilla sets the clip to the strip region (L, T, R, B) and draws the da50 at (L-7, T, R, B), so the frame's left
    stroke and corners fall outside the clip and only its top / bottom / right strokes show, half-open (1 px on the
    region's outer rows / last column).  Scaled: the SAME frame as every other console frame -- the half-open box
    (L - s(7), T, R, B) band-mapped with strokes K on its outer rows / cols (t_rwk_boxforce: top [T, T+K), bottom
    [B-K, B), right [R-K, R)) -- then clipped to the region: the hidden band [L - s(7), L) x [T, B) keeps the pixels it
    had before the draw.  The band map writes the dest plane directly and ignores the clip, so thunk_frame_enlarge
    sends any frame that leaves its clip to the GDI NN stretch instead (3-row strokes at 4K, and the exact-fill size
    of the R-1/B-1 rect: bottom / right stroke one px inside, channel to the d5a0 one px short at every g) --
    t_rwk_stripframe draws with the clip's left edge widened to the frame and restores the band from a save.
    Returns the frame, the hidden band, the three visible stroke spans (half-open) and the channels to the strip's
    d5a0 at s(4) (rw_console_centre_inset's box): s(4) - K on top, bottom and right alike (g <= 16: 3 / 3 / 3)."""
    L, T, R, B = region
    if g <= NATIVE_G:
        k, shift, d5 = 1, RW_STRIP_FRAME_SHIFT, RW_CONSOLE_CENTRE_INSET
    else:
        k, shift, d5 = stroke_width(g), scale_px(RW_STRIP_FRAME_SHIFT, g), scale_px(RW_CONSOLE_CENTRE_INSET, g)
    return {"frame": (L - shift, T, R, B), "hidden": (L - shift, T, L, B),
            "top": (T, T + k), "bottom": (B - k, B), "right": (R - k, R),
            "channel_top": d5 - k, "channel_bottom": d5 - k, "channel_right": d5 - k}


def rw_strip_anchor(strip: Tuple[int, int, int, int], panel_l: Tuple[int, int, int, int], g: int) -> Tuple[int, int, int, int]:
    """LAW — the kind-icon strip's region AS THE CONSOLE CHROME DRAWS IT (ReportIf_console_chrome 0x4A3D65..0x4A3F51:
    clip, da50 frame, d5a0, d528): its left edge has ONE owner, the left panel's right da50 stroke.

    Vanilla's MainWin seeds put the strip region on the panel's last column (strip L 244 = panel R 245 - 1), so the
    strip draw (clip L, frame interior) paints over the panel's right stroke in the strip rows -- the stroke stops at
    the strip's top stroke -- and the panel's d5a0 (R - 3) and the strip's d5a0 (L + 4 - 3 = panel R) sit 3 px apart,
    the strip's own T / B / R channel (4 - 1).  Scaled by thunk_hud_seedscale the two seeds floor independently,
    fl(244g/16) vs fl(245g/16), while the panel's stroke is K wide: at g = 25 / 28 (41, 44) the strip starts one px
    right of the stroke's first column (that column survives at L-1 through the strip rows) and at g = 23 / 39 one px
    left of it; the d5a0 -> d5a0 gap is L + s(4) - Rp = channel +-1 there (1600x1200: 5 vs 4).  Law: the strip
    region's L = panel R - K, so the panel stroke [Rp-K, Rp) is the strip's first K columns (overwritten, as vanilla's
    one column is) and the gap is s(4) - K = rw_strip_frame's T / B / R channel at every g.  T / R / B are the region's
    own (the strip's right side is its own frame: rw_strip_frame).  The kind tabs follow the same L (rw_kind_tab_x).
    g <= 16: the region itself (vanilla, byte for byte)."""
    if g <= NATIVE_G:
        return tuple(strip)
    _L, T, R, B = strip
    return (panel_l[2] - stroke_width(g), T, R, B)


RW_KIND_TAB_X0 = 17              # t_rw_init_leave: kind tab i at strip L + 17 + 42 i (vanilla, ReportIf+0xA298 + 4 i)
RW_KIND_TAB_PITCH = 42


def rw_kind_tab_x(i: int, strip: Tuple[int, int, int, int], panel_l: Tuple[int, int, int, int], g: int) -> int:
    """LAW — the x of HQ-report kind tab i (ReportIf+0xA298 + 4i): the strip's DRAWN left edge (rw_strip_anchor) +
    s(17 + 42i).  Vanilla anchors the tabs on the strip region's L, which IS the drawn edge at g = 16; at g = 23 / 25 /
    28 / 39 the drawn edge is the region's L -+ 1 (rw_strip_anchor), and a tab row still on the region's L sat 1 px
    off vanilla's tab -> d528 margin 13 x g/16 (2026-10-18 fix 12 / N3, measured on the baked chrome: g23 17 -> 18,
    g25 22 -> 21, g28 24 -> 23, g39 30 -> 31 against 18.7 / 20.3 / 22.8 / 31.7; every other g identical).
    The pitch is untouched (every tab moves together).  g <= 16: L + 17 + 42i."""
    off = RW_KIND_TAB_X0 + RW_KIND_TAB_PITCH * i
    if g <= NATIVE_G:
        return strip[0] + off
    return rw_strip_anchor(strip, panel_l, g)[0] + scale_px(off, g)


def rw_console_box_w(span: int, g: int) -> int:
    """LAW — a console content box's width / height: span - 2C (rw_console_box_inset), the far edge mirroring the
    near one.  g <= 16: span - 0xC."""
    return span - 2 * rw_console_box_inset(g)


RW_CONSOLE_TITLE_PAD = 6          # console title box h = lineH + 6 (the `add edx,6` at every title box, scaled s(6))
RW_CONSOLE_TITLE_GAP = 2          # body box top = title box bottom + 2 (the `add eax,2`, scaled s(2))
RW_CONSOLE_LIST_TOP = 0x20        # pristine `add reg,0x20`: the F6 faction / satellite target + F7 unit command buttons' y


def rw_console_list_top(g: int) -> int:
    """LAW — the first FlatButton of a console button list (F6 SELECT FACTION / SATELLITE TARGET, F7 AUTOMATE UNITS;
    ReportIf_activate `add reg,0x20` at 0x4A5756 / 0x4AB296 / 0x4A5506) below the panel region top: one step U below
    the body box's top edge, so the top channel (body stroke -> button face) is s(2) like the side channels (P = C + U).
    Vanilla: body top = T + 6 + (lineH 15 + 6) + 2 = T + 0x1D, buttons at T + 0x20 = body top + 1 + 2 (pristine
    SatelliteAttackButton.png / Units.png at 2.8125x: stroke, then a 2-native channel above AND beside the first
    button).  g > 16: C + rw_line_h(15) + s(6) + s(2) + U -- the painter's own body top (the title box h is the scaled
    lineH + s(6)) plus one step.  s(0x20) put the top channel off s(2) at 17 of g = 17..40 (4K: 7 against the side
    channels' 5; 1920x1080 / 1600x1200 happen to agree at 3).  g <= 16: 0x20."""
    if g <= NATIVE_G:
        return RW_CONSOLE_LIST_TOP
    return (rw_console_box_inset(g) + rw_line_h(15, g) + scale_px(RW_CONSOLE_TITLE_PAD, g)
            + scale_px(RW_CONSOLE_TITLE_GAP, g) + rw_console_step(g))


# The walker rows that carry the chain (t_rw_immsum): each value is a signed integer combination of scale_px terms,
# value = sum(coef * scale_px(v, g)).  Keys name the law; the term lists are the law's own definition at g > 16.
RW_SUM_TERMS = {
    "U": ((1, 1), (1, RW_TAB_CHANNEL)),                                          # rw_console_step
    "C": ((1, RW_CONSOLE_PANEL_INSET), (1, 1), (1, RW_TAB_CHANNEL)),             # rw_console_box_inset
    "P": ((1, RW_CONSOLE_PANEL_INSET), (2, 1), (2, RW_TAB_CHANNEL)),             # rw_tab_inset = C + U
    "Q": ((1, RW_CONSOLE_CENTRE_INSET), (1, 1), (1, RW_TAB_CHANNEL)),            # rw_console_centre_inset
    "L28C": ((1, 0x28), (1, RW_CONSOLE_PANEL_INSET), (1, 1), (1, RW_TAB_CHANNEL)),  # s(0x28) + C (F4 list bottom)
    # rw_console_list_top = C + s(15) + s(6) + s(2) + U (5 terms: the walker chains two table rows)
    "Y": ((1, RW_CONSOLE_PANEL_INSET), (2, 1), (3, RW_TAB_CHANNEL), (1, 15), (1, RW_CONSOLE_TITLE_PAD)),
}


def rw_sum_law(key: str, g: int) -> int:
    """The law each RW_SUM_TERMS key stands for (computed from the law functions, not from the terms)."""
    return {"U": rw_console_step, "C": rw_console_box_inset, "P": rw_tab_inset, "Q": rw_console_centre_inset,
            "L28C": lambda gg: scale_px(0x28, gg) + rw_console_box_inset(gg), "Y": rw_console_list_top}[key](g)


def rw_sum_value(terms, g: int) -> int:
    """What the t_rw_immsum walker stores for a row: sum(coef * scale_px(v, g))."""
    return sum(c * scale_px(v, g) for c, v in terms)


def rw_console_inset_w(span: int, inset: int, g: int) -> int:
    """LAW — a console box's span inset by `inset` on BOTH sides: span - 2*s(inset) (g <= 16: span - 2*inset, vanilla's
    own `sub reg, 2*inset` constant).  Never span - s(2*inset): s(0xC) != 2*s(6) at g = 17/18/20/23/25/26/... (1600x1200:
    19 vs 18), which pushed every console box's far edge one px off the panel's mirror (the box sat s(6) from the
    panel's left but s(0xC)-s(6) from its right).  Ports: the F6 satellite / F4 mode tab rows (2*s(3)), the
    ReportWin_draw_energy text / list rects (2*s(6), t_rw_immsum rows).  The console CONTENT boxes use
    rw_console_box_w (span - 2C) since the 2026-10-17 console chain."""
    if g <= NATIVE_G:
        return span - 2 * inset
    return span - 2 * scale_px(inset, g)


def rw_tab_inset(g: int) -> int:
    """LAW — the tab buttons' (and every button / list cursor nested in a content box: the F4 governor list, the F6
    satellite target and F7 unit command buttons) inset from the console panel region: P = C + K + s(2) (the content
    box inset rw_console_box_inset + the box stroke + the channel), chrome pinned so the drawn channel is exactly s(2)
    on every side.  s(9) is NOT this at most g (the scaled sum of the parts is not the scaled whole).  g <= 16: 9.
    v2 (2026-10-17 console chain): C replaces v1's s(6)."""
    if g <= NATIVE_G:
        return RW_TAB_BOX_INSET + 1 + RW_TAB_CHANNEL
    return rw_console_box_inset(g) + rw_console_step(g)


def rw_tab_pair(region: Tuple[int, int, int, int], g: int):
    """LAW — (box, left, right) rects of a console tab pair on the panel region (L, T, R, B), all HALF-OPEN.

    box   = [L+C, R-C) x [T+C, T+C+s(0x1A))  (C = rw_console_box_inset; the far edge mirrors the near one)
    P     = rw_tab_inset(g) = C + K + s2;  buttons span [L+P, R-P) x [T+P, boxB-K-s2)
    left  = (W - s2) >> 1 wide; seam s2; right = the remainder (W - s2 - left: the inert cell takes the parity)
    so with the box drawn half-open (strokes K at its outer rows/cols) every channel (button face -> box stroke) is
    s(2) and the seam is s(2).  g <= 16: vanilla's own arithmetic (C truncating division), byte for byte."""
    L, T, R, B = region
    if g <= NATIVE_G:
        W = R - L
        box = (L + 6, T + 6, L + 6 + (W - 0xC), T + 6 + RW_TAB_BOX_H)
        x, y, w = L + 9, T + 9, W - 0x12
        h2 = int(w / 2)                                   # cdq / sub eax,edx / sar eax,1
        left = (x, y, x + h2 - 1, y + 0x14)
        right = (x + h2 + 1, y, x + h2 + 1 + h2, y + 0x14)
        return box, left, right
    C, s2, K = rw_console_box_inset(g), scale_px(RW_TAB_CHANNEL, g), stroke_width(g)
    box = (L + C, T + C, R - C, T + C + scale_px(RW_TAB_BOX_H, g))
    P = rw_tab_inset(g)
    bl, br, bt, bb = L + P, R - P, T + P, box[3] - K - s2
    wl = (br - bl - s2) >> 1
    return box, (bl, bt, bl + wl, bb), (bl + wl + s2, bt, br, bb)


def rw_tab_channels(region: Tuple[int, int, int, int], g: int) -> dict:
    """The DRAWN channels of rw_tab_pair: the box is half-open with strokes K (1 at g <= 16) on its outer rows/cols,
    so its inner face is [boxL+K, boxR-K) x [boxT+K, boxB-K).  Returns L/R/T/B channels, the seam, and the two widths."""
    box, a, b = rw_tab_pair(region, g)
    K = stroke_width(g) if g > NATIVE_G else 1
    return {"L": a[0] - (box[0] + K), "R": (box[2] - K) - b[2], "T": a[1] - (box[1] + K), "B": (box[3] - K) - a[3],
            "Bb": (box[3] - K) - b[3], "seam": b[0] - a[2], "wl": a[2] - a[0], "wr": b[2] - b[0]}


RW_BTN_ROW = 0x87E070           # ReportIf_activate's console button row (L, T, R, B): L @0x4A43C9, R @0x4A43DE (t_rw_btnr)
RW_BTN_SEAM = 2                 # vanilla DATALINKS -> CLOSE seam: DATALINKS [L, mid - 1), CLOSE [mid + 1, ...)


def rw_btn_pair(row_l: int, row_r: int, g: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """LAW (2026-10-25 wave-2 W2A, F30) -- the HQ report console's DATALINKS / CLOSE pair: (x0, x1) half-open spans.

    The row [row_l, row_r) is t_rw_btnl / t_rw_btnr's (centred on the clip: row_l + row_r = clipL + clipR) and the row
    frame (ReportWin_show 0x496CD0, t_rw_rowframe, half-open) wraps it at s(3), so the two OUTER edges must sit on the
    row's edges for the two channels to the ring to be equal.  Vanilla (ReportIf_activate 0x4A43E4..0x4A44E9) splits at
    mid = (clipL + clipR) >> 1: DATALINKS [row_l, mid - 1), CLOSE [mid + 1, 2*mid - row_l).  When the row is odd wide
    (row_l + row_r odd) CLOSE ends one px short of row_r -- at native the row is always even (26 + 670), but at g > 16
    it is odd at many g (4K: [1301, 2538) = 1237 px), and bake v4's s(2) split put that px between CLOSE and the ring:
    4K channels 5 | 6, widths 616 | 615.
    Law: ONE width w = (row_r - row_l - s(2)) >> 1 for both, DATALINKS = (row_l, row_l + w), CLOSE = (row_r - w,
    row_r); the odd px goes to the seam (s(2) or one more), never to one button or one channel (the user's symmetry
    rule; the netwin_btn_pair precedent).  g <= 16: vanilla's own split, byte for byte.
    Port: t_rw_btnw (CALLed from t_rw_gap1 / t_rw_gap2)."""
    if g <= NATIVE_G:
        mid = (row_l + row_r) >> 1
        return (row_l, mid - 1), (mid + 1, 2 * mid - row_l)
    w = (row_r - row_l - scale_px(RW_BTN_SEAM, g)) >> 1
    return (row_l, row_l + w), (row_r - w, row_r)


RW_TAB_BTN_NATIVE_H = 0x14      # ReportIf_activate `add ecx,0x14` @0x4A45CA/0x4A4675/0x4A47A1/0x4A484F: tab button h
RW_TAB_BTN_OBJECTS = (0x891944, 0x892490, 0x893070, 0x893BBC)   # ReportIf 0x885F38 + 0xBA0C/0xC558/0xD138/0xDC84


def rw_tab_btn_zoom_src_h(g: int) -> int:
    """LAW — the 2D-zoom SOURCE height of the four HQ console tab buttons (TECHNOLOGY | BASES, GOVERNOR | BEST BASES):
    their vanilla native window height 0x14, which is also the default FlatButton art's BTN_BAR_NATIVE_H (20) rows.

    Every popup-class FlatButton renders at a NATIVE size thunk_tutbtn_post recovers from its device window,
    btn_native_dim = ceil(h*16/g), the exact inverse of the floor forward fl(n*g/16).  The tab buttons are not sized
    by that forward: their face is rw_tab_pair's channel law (box s(0x1A) minus K and s(2) on each side), which is
    taller than fl(20*g/16) at most g (51 vs 50 at g=40), so the inverse over-recovers 21 (22 at g=19).  The default
    art (top-left / top-right caps + fill, no bottom pieces) is 20 rows drawn top-anchored, so native row 20 stays key
    and the centre NN zoom maps the bottom device rows to it: the face stops 1-2 rows short (4K B channel 7 vs T 5,
    1080p 4 vs 3).  Every native row of the 20-row source is art, so the zoom fills the law face exactly and the
    channels are s(2) top and bottom.  g <= 16 has no 2D zoom: the vanilla button draws at this height natively."""
    return RW_TAB_BTN_NATIVE_H


COUNCIL_BTN_RANGE = (0x6FFA14, 0x703DDC)   # CouncilWin 0x6FEC80 + 0xD94: FlatButton[6] stride 0xB4C (the zoom gate's range)
COUNCIL_BTN_NATIVE_H = 0x14     # CouncilWin_exec button row: T = (B-3) + -0x14 @0x4276C2, h = B-3 - T


def council_btn_h(g: int) -> int:
    """The CouncilWin buttons' device height: the immfix entry 0x4276C2+2 rewrites the row's `add eax,-0x14` to
    -(fl(0x17*g/16) - fl(3*g/16)) (assemble_council IMMTAB, kind 2 = negate), so h = fl(23g/16) - fl(3g/16).
    That is fl(20g/16) or one more (38 vs 37 at 2560x1440): never the floor image of 20 alone.  Where it is one more
    (g 19/21/23/26/30/31/35/37/39) the unpinned CEIL-inverse zoom leaves the face 2 rows short at g 26/30/31/35/37/39
    and 1 row short at g 19/21/23 (flatbutton_zoom_face_rows(h, 21))."""
    if g <= NATIVE_G:
        return COUNCIL_BTN_NATIVE_H
    return (0x17 * g >> 4) - (3 * g >> 4)


NETWIN_BTN_OBJECTS = (0x80F674, 0x8101C0)   # NetWin 0x80A6F8 + 0x4F7C LAUNCH GAME / + 0x5AC8 CANCEL (the lobby's FlatButtons)
NETWIN_BTN_RECTS = {0x80F674: (317, 212, 553, 232), 0x8101C0: (556, 212, 792, 232)}   # NetWin +0xC34 / +0xC44, vanilla
NETWIN_BTN_SEAM = 3             # 556 - 553


def netwin_btn_pair(g: int) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]:
    """LAW (2026-10-24 wave-1 fix 27) -- the MULTIPLAYER SETUP lobby's LAUNCH GAME / CANCEL windows (NetWin rect table
    +0xC34 / +0xC44, read by NetWin_setup_lobby's two BaseButton_init calls @0x482AF8 / @0x482BA2): a mirrored pair.
    Outer edges and rows on the floor images the rect-table scale (thunk_nw_rectscale) gives every dword --
    L = fl(317g/16) (the left column's content edge), R = fl(792g/16), T = fl(212g/16), B = fl(232g/16) -- and ONE
    width w = (R - L - fl(3g/16)) >> 1 for both: LAUNCH = (L, T, L + w, B), CANCEL = (R - w, T, R, B).  The odd px
    of R - L - fl(3g/16) goes to the seam (fl(3g/16) or one more), never to one button (the user's symmetry rule).
    The bare floor of each edge made the widths fl(553g/16) - fl(317g/16) vs fl(792g/16) - fl(556g/16), 1 px apart
    at g 21/26/27/30/37 (2560x1440: 442 | 443).  g <= 16: vanilla (the law is the identity there too).
    Port: t_nw_btnpair, CALLed from thunk_nw_rectscale's tail."""
    (l0, t0, r0, b0), (l1, _t1, r1, _b1) = NETWIN_BTN_RECTS[0x80F674], NETWIN_BTN_RECTS[0x8101C0]
    if g <= NATIVE_G:
        return (l0, t0, r0, b0), (l1, t0, r1, b0)
    L, R = popup_scale_floor(l0, g), popup_scale_floor(r1, g)
    T, B = popup_scale_floor(t0, g), popup_scale_floor(b0, g)
    w = (R - L - popup_scale_floor(NETWIN_BTN_SEAM, g)) >> 1
    return (L, T, L + w, B), (R - w, T, R, B)


def netwin_btn_h(g: int) -> int:
    """The lobby LAUNCH / CANCEL device height: fl(232g/16) - fl(212g/16), fl(20g/16) or one more (28 at 1920x1080,
    where fl(20g/16) = 27): the CEIL inverse over-recovers 21 there, so the pair is pinned (flatbutton_nath_pinned)."""
    a, _b = netwin_btn_pair(g)
    return a[3] - a[1]


HUD_MI_BTN_OBJECTS = (0x7AF620, 0x7B016C)   # MainWin FlatButtons[0] M (id 0x3E8) / [1] I (id 0x3E9), the zoom gate's compares
HUD_MI_BTN_RECTS = {0x7AF620: (734, 75, 754, 95), 0x7B016C: (734, 143, 754, 163)}   # vanilla (g = 16) windows, 20x20


HUD_MI_SEED_FIELDS = {0x7AF620: 0xA2C, 0x7B016C: 0xA3C}   # MainWin +0xA2C rcBtn0Seed (M) / +0xA3C rcBtn1Seed (I)
HUD_TOOLBAR_OBJ = 0x7B0CB8      # MainWin FlatButtons[2] TOOLBAR (id 0x3EA): the scenario editor's, in the M / I column
HUD_TOOLBAR_RECT = (734, 100, 754, 138)   # vanilla (g = 16) window: M / I's left and right edges, between them
HUD_TOOLBAR_SEED_FIELD = 0xA4C  # MainWin +0xA4C (l, t, r, b), derived from M.b / I.t before thunk_hud_seedscale


def hud_mi_column(g: int) -> Tuple[int, int]:
    """LAW (fix 23b) -- the x span (l, r) of the HUD M / I / TOOLBAR column: one left and one right edge for all three
    windows.  RIGHT-anchored: r = fl(754g/16), the floor image of the vanilla right edge every pre-fix-23 window had,
    l = r - s(20).  g <= 16: vanilla (734, 754).

    fl(754g/16) - fl(734g/16) is s(20) or one more (g 17/18/19/25/26/27/33/34/35); a square column must drop the extra
    px on one side.  Right-anchoring keeps it out of the right inset to the console frame (the M "corner" pair: top
    inset == right inset; the I corner: right == bottom), so every corner pair that held before fix 23 still holds;
    the px goes to the 10-native-px channel left of the column (to the box-5 info panel), which grows by 1 there.  That
    channel then sits FARTHER from 10g/16 at g 18/19/26/27/34/35 (worst 1.125 px, g 19/27/35) and closer only at
    g 17/25/33: the cost accepted under the symmetry rule, which keeps the corner pairs.  Left-anchoring (fix 23's
    l = fl(734g/16), r = l + s(20)) put it into the right inset and lost the M corner at g 18/25/34 (census: the real
    MainWin_build + centre painter + FlatButton draw, fix 23b)."""
    if g <= NATIVE_G:
        return HUD_TOOLBAR_RECT[0], HUD_TOOLBAR_RECT[2]
    r = popup_scale_floor(HUD_TOOLBAR_RECT[2], g)
    return r - popup_scale_floor(BTN_BAR_NATIVE_H, g), r


def hud_mi_btn_rect(obj: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (fix 23 / 23b) -- the HUD M / I windows (MainWin +0xA2C / +0xA3C, which MainWin_build hands BaseButton_init
    @0x45AA20 / @0x45A995 as x, y, r - x, b - y): a SQUARE of side s(20) = fl(20g/16) in the column hud_mi_column,
    anchored vertically at the edge that faces the TOOLBAR -- M at its bottom fl(95g/16), I at its top fl(143g/16):
    M = (l, fl(95g/16) - s(20), r, fl(95g/16)),  I = (l, fl(143g/16), r, fl(143g/16) + s(20)).

    thunk_hud_seedscale floors each of the 97 table dwords alone, so a window built from two floored edges is
    fl(b*g/16) - fl(t*g/16) = fl(20g/16) or one more, per axis and per button (1920x1080: M 27x27, I 27x28;
    2560x1440: M 37x38, I 37x37).  The FlatButton 2D zoom recovers its native size by the CEIL inverse
    btn_native_dim; on a one-more side that is 21 (22) and the 20-row / 20-col default art leaves the far key
    row / col, so the face fell 1-2 px short and M != I.  At s(20) the CEIL inverse is exactly 20 at every g
    (20 - 16/g < fl(20g/16)*16/g <= 20), so both faces fill their windows, M == I, and both are square, with no pin
    (flatbutton_nath_pinned stays the tabs + Council only).

    Anchoring (fix 23b census over g 16..40 on the real image): with the TOOLBAR-facing edges on the floor grid the
    TOOLBAR gaps are the floor image of vanilla's 5 / 5 (equal at 12 g, 8 before fix 23) and the extra px of
    fl(95g/16) - fl(75g/16) goes to M's top inset, which equalises the M corner at 8 g (4 before, 1 under fix 23's
    top-left anchoring); the I corner keeps every g it held before (10 vs 9).  No pair that held before fix 23 breaks.
    Moved edges: M.t down by 0 / 1 (g 23/26/27/29/30/31/39), M.l / I.l right by 0 / 1 (hud_mi_column), M.b / I.r /
    M.r unchanged, I.b up by 0 / 1.  Readers: BaseButton_init's arg loads; the TutWin tour centres @0x4BD69D / 0x4BD718
    ((l + r) / 2, (t + b) / 2: the window's own centre); MainWin_build @0x45B491 reads I.l for the scenario-editor
    info rect's right edge (+0xD74 = I.l - s(3), editor_info_right since fix 24), which therefore follows the column.
    TOOLBAR (+0xA4C) shares the column: hud_toolbar_rect.
    Port: t_hud_mi_square, the tail of thunk_hud_seedscale.  g <= 16: vanilla (734, 75, 754, 95) / (734, 143, 754, 163)."""
    l, t, r, b = HUD_MI_BTN_RECTS[obj]
    if g <= NATIVE_G:
        return l, t, r, b
    side = popup_scale_floor(BTN_BAR_NATIVE_H, g)
    x0, x1 = hud_mi_column(g)
    if obj == HUD_MI_BTN_OBJECTS[0]:
        y1 = popup_scale_floor(b, g)
        return x0, y1 - side, x1, y1
    y0 = popup_scale_floor(t, g)
    return x0, y0, x1, y0 + side


def hud_toolbar_rect(g: int) -> Tuple[int, int, int, int]:
    """LAW (fix 23b) -- the scenario editor's TOOLBAR window (MainWin +0xA4C, FlatButton 0x7B0CB8, vanilla
    (734, 100, 754, 138); shown with M / I in the editor's omniscient view): the M / I column's x span
    (hud_mi_column) and the floor image of its vanilla rows, (l, fl(100g/16), r, fl(138g/16)).  Fix 23 left it at
    fl(754g/16) on the right while M / I ended at l + s(20): it stuck out 1 px at g 17/18/19/25/26/27/33/34/35.
    Rows unchanged: centring it on s(38) between M and I would equalise its gaps at 18 g but un-centre its caption
    vertically at g 18/23/26/31/34/39, where it is centred now.  Port: t_hud_mi_square.  g <= 16: vanilla."""
    if g <= NATIVE_G:
        return HUD_TOOLBAR_RECT
    x0, x1 = hud_mi_column(g)
    return x0, popup_scale_floor(HUD_TOOLBAR_RECT[1], g), x1, popup_scale_floor(HUD_TOOLBAR_RECT[3], g)


def hud_mi_btn_h(obj: int, g: int) -> int:
    """The HUD M / I buttons' device height (= width): hud_mi_btn_rect's side, s(20) at g > 16, 0x14 at g <= 16."""
    _l, t, _r, b = hud_mi_btn_rect(obj, g)
    return b - t


def flatbutton_nath_pinned(obj: int) -> bool:
    """The FlatButtons whose 2D-zoom source height is pinned to vanilla's 0x14 (t_btn_nath_pin): default 20-row art,
    vanilla h 0x14, and a device height from a composite law (rw_tab_pair's channels; council_btn_h; the lobby pair's
    two floored edges, netwin_btn_h -- fix 27) that the CEIL inverse over-recovers to 21 / 22.  An object list, not a class: the default art is also worn by vanilla-0x16
    buttons (the faction picker's text buttons, the Load/Save OK / CANCEL) whose floor-law height recovers 22
    EXACTLY -- their 2-row key band is vanilla's -- and nothing on the object records the vanilla height.  The HUD
    M / I pair (HUD_MI_BTN_OBJECTS) is deliberately NOT in the list (fix 22b, the user's symmetry rule): its windows
    are s(20) squares (hud_mi_btn_rect, fix 23), where the CEIL inverse is already 20."""
    return (obj in RW_TAB_BTN_OBJECTS or obj in NETWIN_BTN_OBJECTS
            or COUNCIL_BTN_RANGE[0] <= obj < COUNCIL_BTN_RANGE[1])


def flatbutton_zoom_src_h(obj: int, dev_h: int, g: int) -> int:
    """LAW -- the native height a 2D-zoomed FlatButton renders at (thunk_tutbtn_post -> t_btn_nath_pin):
    BTN_BAR_NATIVE_H for the pinned objects, else the CEIL inverse btn_native_dim.  For every pinned object the
    inverse is >= 20 at every g (tabs 20..22, council / lobby 20..21), so the pin == min(inverse, the art's 20 rows)."""
    if g > NATIVE_G and flatbutton_nath_pinned(obj):
        return BTN_BAR_NATIVE_H
    return btn_native_dim(dev_h, g)


def flatbutton_zoom_face_rows(dev_h: int, native_h: int, art_h: int = BTN_BAR_NATIVE_H) -> int:
    """The device rows a default-art FlatButton's 2D zoom paints with art: the centre-sampled NN row map
    (nn_center_index, the engine stretch) sends device row j to native row ((2j+1)*native_h)//(2*dev_h); rows whose
    source is at or past the art bottom (art_h, top-anchored) are key and stay transparent.  dev_h when
    native_h <= art_h."""
    return sum(1 for j in range(dev_h) if nn_center_index(j, dev_h, native_h) < art_h)


def rw_sat_tabs(clip_l: int, clip_r: int, g: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """LAW — F6 SATELLITE SUMMARY | ORBITAL ATTACK VIEW x spans (half-open) on the ReportWin clip (ReportIf_activate
    0x4A4C13..0x4A4D7F).  Vanilla: x = clipL+3, w = clipW-6, left [x, x+w/2-1), right [x+w/2+1, x+w): both 3 inside
    the clip, seam 2, the halves equal or the right one 1 wider.  g > 16: x = clipL + s3, w = rw_console_inset_w(clipW, 3)
    (the right inset mirrors the left: s(6) != 2*s(3) at 4K / 1600), left (w - s2) >> 1, seam s2, right the rest."""
    if g <= NATIVE_G:
        x, w = clip_l + 3, clip_r - clip_l - 6
        h2 = int(w / 2)
        return (x, x + h2 - 1), (x + h2 + 1, x + w)
    s3, s2 = scale_px(3, g), scale_px(RW_TAB_CHANNEL, g)
    x, w = clip_l + s3, rw_console_inset_w(clip_r - clip_l, 3, g)
    wl = (w - s2) >> 1
    return (x, x + wl), (x + wl + s2, x + w)


RW_PROJECTS_ROW_PITCH = 56       # kind 5 SECRET PROJECTS painter: row y = top + 56*k + 2 (the `x56` lea; cell 0x36 + gap 2)
RW_PROJECTS_ROW_INSET = 2         # ... the `+2` of that lea (row 0's offset below the list top)
RW_UNITS_ROW_PITCH = 0x2B         # kind 7 UNITS painter: both row-rect edges advance by 0x2B per visible row


def rw_list_row_offset(k: int, native_pitch: int, g: int) -> int:
    """HQ report canvas lists (F5 projects, F7 units): visible row k's offset below row 0 = cum(k) =
    scale_px(k * native_pitch, g) -- ONE rounding of the whole run, never k times a per-row rounding
    ([[feedback-remainder-distribution]]).  The painters advance a scaled pitch per row (projects
    s(0x36)+s(2) = 87 at g=25 where 56 x 25/16 = 87.5; units s(0x2B) = 67 vs 67.19), so rows lose a pixel
    every couple of rows.  Not row_positions(): that law spreads a KNOWN count's total, but these lists
    scroll and the painter knows only the row's own index -- a row's place must not depend on how many
    rows follow it.  |cum(k) - k*pitch*g/16| <= 1/2 for every k.  g=16 -> k*pitch exactly."""
    return scale_px(k * native_pitch, g)


def rw_list_row_advance(k: int, native_pitch: int, g: int) -> int:
    """The step from visible row k-1 to row k (k >= 1): cum(k) - cum(k-1), i.e. floor or ceil of the real
    scaled pitch.  The units painter keeps both row-rect edges as running sums, so it adds this per row (the
    rect height s(0x2B) - s(2) stays fixed; the gap between rows absorbs the rounding, LAW 5)."""
    return rw_list_row_offset(k, native_pitch, g) - rw_list_row_offset(k - 1, native_pitch, g)


BASES_ROW_PITCH_NATIVE = 42       # kind 4 BASE STATUS painter: pitch [ebp-0x1C] = cell 0x28 + 2 (0x49D687)


def bases_row_advance(k: int, g: int) -> int:
    """F4 BASE STATUS: the step from visible row k-1 to row k (k >= 1) = cum(k) - cum(k-1) at the native pitch 42, so
    row k sits s(42k) below row 0.  The painter added its device pitch bases_row_pitch(g) = cell + s(2) per row, which
    is not s(42) (g=18: 46 vs 47.25, 11 px short by the 10th row; g=25: 66 vs 65.6; g=40: 104 vs 105).  The entry box
    stays bases_row_cell(g) (chrome wraps the face); the gap between boxes absorbs the rounding (LAW 5).  The visible
    row count (h - s(6)) / bases_row_pitch(g) is untouched: it equals vanilla's 10 at every g in 17..40 and the 10th
    box ends >= 27 px above the clip bottom (test_rw_rowcum_asm).  g <= 16: the engine's own pitch."""
    if g <= NATIVE_G:
        return bases_row_pitch(g)
    return rw_list_row_advance(k, BASES_ROW_PITCH_NATIVE, g)


RW_ENERGY_ROW_STRIDE_NATIVE = 15 + 3   # kind 3 energy ListBox: row stride [Dialog+0x48] = lineH + 3 (0x49CC7D..0x49CC8F)


def rw_energy_row_stride(engine_stride: int, g: int) -> int:
    """F3 ENERGY ListBox row stride: vanilla lineH + 3 = 18.  At g > 16 the engine added the two separately scaled terms
    rw_line_h(g) + s(3) (g=40: 37 + 7 = 44 where 18 x 2.5 = 45, a row short every row); law: ONE rounding of the sum,
    scale_px(18, g).  The engine ListBox lays rows at i x stride (shared ListBox_draw_item / set_hover walk path), so
    this is per-row rounding: |error| <= 1/2 px per row, exact wherever 18g/16 is whole (g=40).  Never fewer rows than
    vanilla: rw_energy_visible_rows with this stride >= vanilla's 24 at every g in 17..40 (24, or 25 at g=18/20; the
    engine stride showed 23 at g=19 and 25 at g=18/20/24/29/40), so no fallback to the engine stride is needed.  g <= 16: the engine's own
    lineH + 3."""
    if g <= NATIVE_G:
        return engine_stride
    return scale_px(RW_ENERGY_ROW_STRIDE_NATIVE, g)


RW_LB_DEFAULT_GAP = 6    # Dialog reset 0x608F50: [Dialog+0x44] = [0x69709C] = 6 (no other writer; unscaled at every g)


def rw_energy_list_h(win_h_dev: int, g: int) -> int:
    """F3 ENERGY ListBox box height [Dialog+0x30] as Dialog_init_3 (0x49CC58) receives it from ReportWin_draw_energy:
    T = clipT + 2(lineH + 9) + 2 + 3, B = clipB - 3 - 3 (the painter's literals, walker-scaled at g > 16; lineH =
    rw_line_h).  Native (H 553, clip {.., 3, .., 500}): 494 - 56 = 438."""
    _frame, clip = rw_window_rects(650, win_h_dev, g)
    s = (lambda v: v) if g <= NATIVE_G else (lambda v: scale_px(v, g))
    line_h = 15 if g <= NATIVE_G else rw_line_h(15, g)
    top = clip[1] + 2 * (line_h + s(9)) + s(2) + s(3)
    return clip[3] - 2 * s(3) - top


def rw_energy_visible_rows(stride: int, win_h_dev: int, g: int) -> int:
    """ListBox_calculate_dimensions 0x60A4DB: visible = (h - [+0x3C] - [+0x38] + gap) / rowH with the insets 0 (Dialog
    reset) and gap RW_LB_DEFAULT_GAP; rowH = the painter's stride [Dialog+0x48].  The scrollbar's page is visible - 1
    (ListBox_update_changes), so page and thumb follow this count."""
    return (rw_energy_list_h(win_h_dev, g) + RW_LB_DEFAULT_GAP) // stride


def rw_projects_row_y(top: int, k: int, g: int) -> int:
    """F5 SECRET PROJECTS: top of visible row k (both columns) = top + s(2) + cum(k) at pitch 56.  The cell
    height stays scale_px(0x36, g) (the drawn element); the gap absorbs the rounding."""
    return top + scale_px(RW_PROJECTS_ROW_INSET, g) + rw_list_row_offset(k, RW_PROJECTS_ROW_PITCH, g)


# Native list geometry above the first row (vanilla painters, clip top T = 3, f12 lineH = 15 = RW_LINE_H at g > 16):
RW_LIST_TOP_NATIVE = 3 + 15 + 9                  # T + lineH + 9: the title band both painters put above the list
RW_UNITS_COUNT_INSET = RW_LIST_TOP_NATIVE + 2     # units:    rows = (textB - (top + 2)) / 0x2B
RW_PROJECTS_COUNT_INSET = RW_LIST_TOP_NATIVE + 5  # projects: rows = (textB - top - 5) / 0x36 (vanilla divides by the
RW_PROJECTS_COUNT_DIV = 0x36                      #           cell 54, not the pitch 56 -- kept: vanilla's own relation)


def rw_report_textb_native(win_h_dev: int, g: int) -> int:
    """The vanilla textB the device window was scaled from: win_h (RW+0x5990, the frame rect bottom) is fl(H*g/16)
    after the init lever, so H = ceil(win_h*16/g) exactly (the floor-descale round trip, g >= 16) and textB = H - 0x35.
    RW+0xA20 is NOT win_h at paint time: ReportWin_tech_reset (0x496BB0; the store at 0x496C60) rewrites it to textB - clipT on every page
    paint, which made F5 / F7 count one row short (2026-10-17)."""
    return (16 * win_h_dev + g - 1) // g - RW_TEXTB_INSET


def _rw_visible_rows(h_dev: int, win_h_dev: int, g: int, inset: int, div: int) -> int:
    if g <= NATIVE_G:
        return h_dev // div                      # vanilla's own division on its own h (any layout, incl. 800x600)
    return (rw_report_textb_native(win_h_dev, g) - inset) // div


def rw_units_visible_rows(h_dev: int, win_h_dev: int, g: int) -> int:
    """F7 UNITS: the visible-row count = VANILLA's count, floor(h_nat / 0x2B).  At g > 16 the device h is built from
    separately rounded edges (fl(win_h) - s(0x35) - s(3) - s(15) - s(9) - s(2)), so neither h / s(0x2B) nor
    16h / (0x2B g) can tell an h_nat that is an exact multiple of 0x2B from one a pixel short -- either could show a
    row more or less than vanilla x g/16.  The count is therefore taken in NATIVE space, from the exactly recovered
    textB (rw_report_textb_native); the rows then sit at cum(k) and the last one ends inside the list at every g
    (tested 16..40 on the real layout).  g <= 16: vanilla's division of the engine's h."""
    return _rw_visible_rows(h_dev, win_h_dev, g, RW_UNITS_COUNT_INSET, RW_UNITS_ROW_PITCH)


def rw_projects_visible_rows(h_dev: int, win_h_dev: int, g: int) -> int:
    """F5 SECRET PROJECTS: the visible-row count = vanilla's, floor((textB - top - 5) / 0x36) in native space (same
    reasoning as rw_units_visible_rows; vanilla's own divisor 0x36 kept).  g <= 16: the engine's h / 0x36."""
    return _rw_visible_rows(h_dev, win_h_dev, g, RW_PROJECTS_COUNT_INSET, RW_PROJECTS_COUNT_DIV)


RW_FRAME_L = 0x17        # init_report_screen: d690 window frame rect {0x17, 0, 0x17 + W, H} (RW+0x5984)
RW_CLIP_INSET = 3        # content clip (RW+0x5974) = the frame rect inset 3 on L/T/R: {0x1A, 3, W + 0x14, H - 0x35}
RW_WIN_EXTRA = 0x4E      # GraphicWin_init width = W + 0x4E (0x17 left rails + 0x37 right rails/margin): canvas 728 at g=16


def rw_canvas_w(win_w: int, g: int) -> int:
    """ReportWin canvas width (t_rw_init_leave's GraphicWin_resize width, g_rw_rect+8); vanilla W + 0x4E.

    v2 (2026-10-17): ceil(N*g/16) with N = ceil(W*16/g) + 0x4E -- the device W's exact native descale plus vanilla's
    extra, i.e. the native canvas (728 for the 650 window), re-scaled by CEIL: the unique device width whose railscale
    descale fl(cw*16/g) is N itself ([[feedback-floor-descale-roundtrip]], the se_window_w precedent).  The inner right
    rail and the frame R (rw_window_rects) then land on fl((N - 0x37)*g/16) = vanilla x g/16; v1's W + s(0x4E)
    descaled to N - 1 at most g (R and the right rails 1 px left at g=22/25, 2 at g=33..39).  The canvas grows by 0..1
    px; every canvas-relative consumer (the list bar, the saved right-border column, the slide rails) reads it live."""
    if g <= NATIVE_G:
        return win_w + RW_WIN_EXTRA
    n = (win_w * 16 + g - 1) // g + RW_WIN_EXTRA
    return (n * g + NATIVE_G - 1) // NATIVE_G


def rw_window_rects(win_w: int, win_h: int, g: int) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """HQ report window (ReportWin, init lever t_rw_init_leave): (frame, clip) for the device window W x H.

    Vanilla draws the d690 window frame on {0x17, 0, 0x17+W, H} and the page content clip (the F2 header band's d5a0
    frame, the kind-3/4 page frames, every page's [A14]/[A1C]) on {0x1A, 3, W+0x14, H-0x35}: the clip is the frame
    inset by 3 on L, T and R -- a 2-px channel between the two strokes on all three sides.  Scaling each literal on
    its own (s(0x1A) / s(3) / W+s(0x14)) puts the left inset at s(26)-s(23), the top at s(3) and the right at
    s(23)-s(20): three floor phases that disagree by 1 px at 17/18/19/20/22/24/29/31/33/34/35/36/38/40 (1920x1080:
    channel 3 left / 4 right).  Law: ONE cascade off the frame -- clip = frame inset s(3) on every side, so the
    channel is s(3)-K on L, T and R at every g.  The bottom inset 0x35 is not a channel (the DATALINKS/CLOSE row lives
    there) and keeps its own s(0x35).  Identity at g=16: {23,0,23+W,H} / {26,3,W+20,H-53}.

    v5 (2026-10-17): the frame's L / R ABUT the slide rails, through the rails' OWN cascades (the rule SocialWin
    se_backdrop_rect and DiploWin dw_frame_lr already follow).  Vanilla's frame edges ARE the rail edges: L = 0x17 =
    outer 15 + inner 8 strip, R = 0x17 + W = canvas - 0x37 = where slide_show draws the inner right strip.  At g > 16
    the rails go through thunk_filedlg_railscale: the left strips end at rail_left_extent(g) (fl(15g/16) + fl(8g/16)),
    the inner right strip starts at fl((fl(cw*16/g) - 0x37)*g/16) (cw = rw_canvas_w).  v4's s(0x17) / s(0x17) + W
    sat 1 px RIGHT of the left rails (a see-through column, 1920x1080 x512 / 1600x1200 x291) and its R-1 stroke
    column under the inner right rail at most g (1-3 px; the rail drawn at the slide settle hid the whole K-wide
    stroke whenever a report was opened from the map).  The clip, every page and the window placement follow the frame
    (rw_window_x).

    v6 (2026-10-17, rw_canvas_w v2): with the exact canvas the descale is the native 728, so R = fl(673*g/16) =
    vanilla x g/16 at every g (v5: 1 px left at 22/25, 2 at 33..39).  The frame width R - L is W..W+2 (L is the left
    strips' two floors, <= fl(23g/16)), within 1.5 px of the exact 650g/16 at every g 17..48; 4K unchanged."""
    if g <= NATIVE_G:
        f, i, b = RW_FRAME_L, RW_CLIP_INSET, 0x35
        left, right = f, f + win_w
    else:
        i, b = scale_px(RW_CLIP_INSET, g), scale_px(0x35, g)
        cw = rw_canvas_w(win_w, g)
        left = rail_left_extent(g)
        right = popup_scale_floor(rail_right_anchor(cw, cw - SE_RAIL_RIGHT_OFF, g), g)
    frame = (left, 0, right, win_h)
    return frame, (left + i, i, right - i, win_h - b)


def rw_window_x(screen_w: int, win_w: int, g: int) -> tuple[int, int]:
    """(frame screen x = RW+0xA14 at init, window x = RW+0x13C): the FRAME is centred on the screen, as vanilla's
    (ScreenWidth - W)/2 centres its 0x17..0x17+W frame; the window starts the frame's L to the left of it.  v5 centres
    the frame's own width R - L (rw_window_rects) and offsets by its own L; g <= 16: ((SW-W)/2, (SW-W)/2 - 0x17)."""
    (left, _t, right, _b), _clip = rw_window_rects(win_w, 0, g)
    a14 = (screen_w - (right - left)) >> 1
    return a14, a14 - left


LB_TEXT_PAD_NATIVE = 2   # ListBox ctor/close: [elem+0x2C] = [0x6970E4] = 2; ListBox_draw_item insets the text by pad+1 per side


def rw_list_text_pad(g: int) -> int:
    """HQ report lists (the six console ListBoxes inside the g_rw_inlist bracket + the energy page's ReportWin+0x5A0C
    list): the value ListBox_close stores in the per-list text pad [elem+0x2C].  ListBox_draw_item insets every
    column's text rect by pad + 1 on each side (0x60BD49.. / 0x60BEFB..: L += [D+0x34] + pad + 1, R -= pad + 1), so the
    native inset is 3 px and the right-aligned column's right edge sits 2-3 native px left of the bar trough.  The pad
    is a static default the levers never touched: at g=25 the text met the trough with a 1-px gap (F3 BASE
    EXPENDITURES, 2026-10-11) and the left text sat 5 px from the list stroke where vanilla x g/16 is 8.  Law: the
    TOTAL inset scales, pad + 1 = scale_px(3, g), so the stored pad is scale_px(3, g) - 1.  Identity at g=16: 2."""
    if g <= NATIVE_G:
        return LB_TEXT_PAD_NATIVE
    return scale_px(LB_TEXT_PAD_NATIVE + 1, g) - 1


def slide_rail_outer_row(screen_h_dev: int, g: int, screen_is_800: bool = False) -> int:
    """Slide-window chrome (slide_show 0x45D440): the SCREEN row where the 15x529 outer rail strips start.  Vanilla:
    0x5E + (ScreenWidth != 800 ? 0x90 : 0) = 238 (94 at 800x600) = 768 - 530, so the strip's foot lands on the last
    screen row; for the report window (top 3) the wide pillar starts 235 rows below the window top.  Device law:
    ScreenHeight_dev - fl(530*g/16), identity at 768/g=16.  g<=16 -> the native constant."""
    if g <= NATIVE_G:
        return 0x5E + (0 if screen_is_800 else 0x90)
    return screen_h_dev - (530 * g) // 16


def slide_rail_outer_a(win_top_dev: int, screen_h_dev: int, g: int, screen_is_800: bool = False) -> int:
    """The value t_slide_rail_a / _a2 store in slide_show's [ebp-0x24] / slide_hide's [ebp-0x38]: the outer strips'
    start ROW in device screen space (slide_rail_outer_row).  The open/close animation frames draw at
    max(slide_y, A) in screen coordinates through thunk_railslide (v2: device y as pushed, the outer top no
    higher than the settled one -- slide_rail_anim_y), so the cell must be the device row itself; only the two settled draws (window-local, through the
    railscale x g/16 floor) need a descaled value, and they get it at their own sites (slide_rail_settled_v).
    win_top_dev is unused (kept for the callers; v2 folded the descale into the cell and broke the animation)."""
    return slide_rail_outer_row(screen_h_dev, g, screen_is_800)


def slide_rail_settled_v(slide_y_dev: int, a: int, win_top_dev: int, g: int) -> int:
    """The settled outer-strip draw's y argument: vanilla v = max(slide_y, A) - T (window-local); at g>16 the
    railscale (v3; the v1shim before it) multiplies it by g/16 (floor), so the site hands back ceil(v*16/g) and the floor lands on
    R_dev - T within g/16 - 1 px ([[feedback-floor-descale-roundtrip]]).  v >= 0 on this path (settled slide_y == T)."""
    v = max(slide_y_dev, a) - win_top_dev
    if g <= NATIVE_G:
        return v
    n = 16 * v + g - 1
    return abs(n) // g * (1 if n >= 0 else -1)


def slide_rail_outer_y(slide_y_dev: int, a: int, win_top_dev: int, g: int) -> int:
    """The settled outer strip's window-relative device y: the site's slide_rail_settled_v through railscale's floor
    (fl(v'*g/16) at g>16, v' at g<=16)."""
    v = slide_rail_settled_v(slide_y_dev, a, win_top_dev, g)
    return v if g <= NATIVE_G else (v * g) // 16


SLIDE_RAIL_STRIPS = ("outer_left", "inner_left", "inner_right", "outer_right")   # slide_show / slide_hide draw order
SLIDE_RAIL_W = (15, 8, 8, 15)            # the strips' art widths (sprite canvas w: 0x7CFFDC / 0x7D0008 / 0x7D0034 / 0x7D0060)
SLIDE_RAIL_GAP = 0x20                    # the 32-px margin right of the right pair (canvas - 55 / canvas - 47)


def slide_rail_local_x_args(buf_w: int) -> Tuple[int, int, int, int]:
    """slide_show / slide_hide's window-local x for the four strips, from the window canvas width buf_w (device at
    g>16 -- the composed arg mixes it with the native art widths): 0, 15, buf_w - 55, buf_w - 47.  The animation
    frames push these plus the window's screen left L; the settled draws push them as they are."""
    ol, il, ir, orr = SLIDE_RAIL_W
    return 0, ol, buf_w - orr - ir - SLIDE_RAIL_GAP, buf_w - orr - SLIDE_RAIL_GAP


def slide_rail_settled_x(buf_w: int, x_arg: int, g: int) -> int:
    """The settled strip's window-local device x (thunk_filedlg_railscale v3): a left strip (2x < buf_w) at
    fl(x*g/16) (its native offset 0 / 15), a right strip at rail_right_strip_x (the inner one at railscale's double
    floor, the outer one directly against it).  g<=16: the arg itself (engine Sprite_draw_2 1/1)."""
    if g <= NATIVE_G:
        return x_arg
    if 2 * x_arg < buf_w:
        return (x_arg * g) // 16
    return rail_right_strip_x(buf_w, x_arg, g)


def slide_rail_anim_x(left: int, x_arg: int, buf_w: int, g: int) -> int:
    """thunk_filedlg_railslide v2: the open/close animation frame's strip SCREEN x.  The frames push x = L + the local
    arg (L = the window's screen left [ebp-0x1c]); the strip lands where the settled draw puts it: L +
    slide_rail_settled_x(buf_w, x - L, g), then thunk_sprite_scale_nn v2 (origin not rescaled).  v1 ceil-descaled the
    SCREEN x (Ln = ceil(L*16/g)) and let the shim floor it back: fl((Ln + d)*g/16) != L + fl(d*g/16) unless L*16/g
    sits on the right phase, so mid-slide the strips sat 1 px off the settled ones at most L (a see-through column
    between the left strips and the inner strip over the frame's first stroke at 1920x1080 / 1600x1200; the right
    pair 1 px apart).  The x does not depend on the slide row, so every frame is the settled column set."""
    if g <= NATIVE_G:
        return x_arg
    return left + slide_rail_settled_x(buf_w, x_arg - left, g)


def slide_rail_anim_y(y_arg: int, a: int, win_top: int, outer: bool, g: int) -> int:
    """thunk_filedlg_railslide v2: the animation frame's strip SCREEN top.  The inner strips push the slide row y (the
    moving window top) and stay there; the outer strips push max(slide_y, A) (A = the device start row,
    slide_rail_outer_a) and start no higher than the settled outer top T + slide_rail_outer_y(T, A, T) -- the
    settled sites ceil-descale A - T and railscale floors it back, so the settled top is A rounded DOWN the screen by
    up to ceil(g/16) - 1 rows.  max(y, that) == the settled top on the settled frame (slide_y == T) and follows the
    window top once it is lower.  A <= T: the settled v is 0 and y (>= T) stands.  g<=16: y."""
    if g <= NATIVE_G or not outer or a <= win_top:
        return y_arg
    return max(y_arg, win_top + slide_rail_outer_y(win_top, a, win_top, g))


def slide_rail_anim_rows(y_dev: int, bottom: int, blit_h: int, g: int) -> int:
    """Rows the animation frame's strip covers: the bottom clamp (vanilla relies on the screen buffer's clip rect = the
    window rect; thunk_sprite_scale_nn clips only to the buffer) lowers the dest buffer's height to B for the draw, so
    the strip covers min(fl(H*g/16), B - y) rows -- exactly where vanilla's clip and the settled draw end it.  v3
    (2026-10-17); v2 shrank the sprite's blit h to fl((B - y)*16/g) native rows, and fl(that*g/16) fell 1-3 rows short
    of B on every strip that reached it (the last show frame vs the settled strip).  0 = no draw.  g<=16 (the native
    Sprite_draw_2 under the engine clip rect): min(H, B - y)."""
    vis = bottom - y_dev
    if vis <= 0:
        return 0
    full = blit_h if g <= NATIVE_G else (blit_h * g) // 16
    return min(full, vis)


def slide_frames(top: int, bottom: int, steps: int, show: bool) -> list:
    """The slide rows the animation loop draws at: slide_show (0x45D58E..) step = ceil((B - T)/steps), rows B - step,
    B - 2*step, ... clamped to T (the last frame at T, then the settled draws); slide_hide (0x45DB7E..) step =
    trunc((B - T)/steps), rows T + step, T + 2*step, ... (the window starts settled, so the first frame has already
    moved)."""
    if show:
        step = -(-(bottom - top) // steps)
        return [max(bottom - k * step, top) for k in range(1, steps + 1)]
    step = (bottom - top) // steps
    return [top + k * step for k in range(1, steps + 1)]


# ==========================================================================
# STARTUP SPLASH (logo.pcx; Win_init_class 0x5F01F0 / GraphicsMgr_set_mode 0x635510)
# ==========================================================================
# Vanilla: Buffer_fill_2(g_screen_buffer, 0), Buffer_load_pcx(local, "logo.pcx", active Palette, 10, 236)
# (pixel values +10, the 236-entry palette into entries 10..245), then a 1:1 Buffer_copy_4 centred with
# (screen - src)/2.  Authored for the 1024x768 screen (an 800x600 picture inside a black border), so the
# law is the full-screen menus' one (Monument / Hall of Fame, mon_scale_num): num = min(floor(16*ScreenH/768),
# floor(16*ScreenW/1024)) over den 16, UNCLAMPED -- the width term so the 1024x768 frame it was composed in
# always fits a narrow screen (4:3 and wider: the height term alone).  Size = vanilla x num/16 through
# half_down on each axis from ONE num (4:3 kept), centred with >> 1 like the letterboxed menus; num <= 16
# -> the engine's own 1:1 blit, untouched.  The picture is photographic (81 colours, no scanline / row
# dither: period-2 row/column texel repeats ~1 %), so it takes the Monument resampler (mon_resample:
# Lanczos-3 + Floyd-Steinberg at device density into the dest table) -- user decision 2026-10-11
# "smooth".  Both src and dest index the active Palette: the dest's DIB table is synced to it first
# (Buffer_sync_to_palette, exactly what Win_flip_rect does before the BitBlt), and the LUT is rebuilt
# for that table on every splash (the Monument's cached LUT belongs to another palette).
# The LUT searches ONLY the entries logo.pcx was loaded into, [SPLASH_PAL_LO, SPLASH_PAL_HI) = 10..245
# (Buffer_load_pcx(.., 10, 236) @0x5F042B / @0x6356AD): entries 0..9 / 246..255 are the Windows system
# colours, and Lanczos ringing on near-black / dark-red texels otherwise resolves to (128,0,0), (0,128,128),
# (192,192,192), ... -- stray speckle the picture never contained.
SPLASH_BASE_W, SPLASH_BASE_H = MON_NATIVE_W, MON_NATIVE_H
SPLASH_PAL_LO, SPLASH_PAL_COUNT = 10, 236
SPLASH_PAL_HI = SPLASH_PAL_LO + SPLASH_PAL_COUNT


def splash_scale_num(screen_w: int, screen_h: int) -> int:
    """Scale numerator over 16: min(floor(16*H/768), floor(16*W/1024)); 0 for a degenerate screen."""
    if screen_w <= 0 or screen_h <= 0:
        return 0
    return min((NATIVE_G * screen_h) // SPLASH_BASE_H, (NATIVE_G * screen_w) // SPLASH_BASE_W)


def splash_armed(screen_w: int, screen_h: int) -> bool:
    """The enlarge runs only above native scale; at num <= 16 the vanilla 1:1 blit is left alone."""
    return splash_scale_num(screen_w, screen_h) > NATIVE_G


def _trunc_half(v: int) -> int:
    """The engine's `cdq; sub eax,edx; sar eax,1` = v / 2 truncated toward zero."""
    return -((-v) // 2) if v < 0 else v // 2


def splash_rect(screen_w: int, screen_h: int, src_w: int, src_h: int) -> Tuple[int, int, int, int]:
    """(x, y, w, h) the splash picture is drawn at on g_screen_buffer.  Armed: w = s(src_w), h = s(src_h)
    (s = half_down(v*num, 16), one num for both axes), x = (W - w) >> 1, y = (H - h) >> 1.  Not armed: the
    vanilla blit, ((W - src_w)/2, (H - src_h)/2) truncated, 1:1."""
    num = splash_scale_num(screen_w, screen_h)
    if num <= NATIVE_G:
        return (_trunc_half(screen_w - src_w), _trunc_half(screen_h - src_h), src_w, src_h)
    w, h = mon_s(src_w, num), mon_s(src_h, num)
    return ((screen_w - w) >> 1, (screen_h - h) >> 1, w, h)


def splash_compose(src, s_pitch: int, src_w: int, src_h: int, pal: bytes, screen_w: int, screen_h: int,
                   lut: Optional[List[int]] = None) -> bytearray:
    """Reference of the whole splash frame: the black (index 0) screen with the picture blitted 1:1
    (not armed) or resampled into splash_rect (armed).  pal = the active palette as the dest's synced
    RGBQUAD table (b, g, r, x) x 256."""
    dst = bytearray(screen_w * screen_h)
    x, y, w, h = splash_rect(screen_w, screen_h, src_w, src_h)
    if not splash_armed(screen_w, screen_h):
        for r in range(max(0, -y), min(src_h, screen_h - y)):
            c0, c1 = max(0, -x), min(src_w, screen_w - x)
            if c0 < c1:
                dst[(y + r) * screen_w + x + c0:(y + r) * screen_w + x + c1] = bytes(src[r * s_pitch + c0:r * s_pitch + c1])
        return dst
    if lut is None:
        lut = mon_nearest_lut(pal, SPLASH_PAL_LO, SPLASH_PAL_HI)
    mon_resample(src, s_pitch, 0, 0, src_w, src_h, pal, dst, screen_w, screen_w, screen_h, x, y, w, h, lut)
    return dst


# --- map-effect blits above the engine's 4.0 enlarge cap (2026-10-11) ----------------------
# Every scaled sprite core stores f = (float)(num/den) and REJECTS the blit when f > 4.0 (qword
# g_sprite_scale_max 0x66FDC8; `fcomp; fnstsw; test ah,0x41; jne accept`): nothing is drawn.  The
# cap exists because the enlarge path's ROW REPLAY (0x5E97BE) only knows run lengths 1, 2, 3 and
# "else 4": each source row is written to at most 4 dest rows, so a ratio above 4 would compress
# the rows.  Two map effects scale with the map zoom, which PRACX lets run far past vanilla's
# range: the Planet Buster cloud (boom 0x504AA0: buster.flc via Buffer_draw_table at num/den =
# (zoom+16)*k14/(k10*16)) and the ordinary combat explosions (same fn: Sprite_draw_table at
# SCALE_NUM_G/DEN_G = (zoom+16)/16).  Above the cap the patch draws exactly what an UNCAPPED engine
# would -- the engine's dest rect (effect_blit_rect), its clip, its Bresenham run table
# (engine_scale_runs, Sprite_fill_scaling_table 0x5EB20F) walked like its clipped-table builders
# (engine_run_blocks, 0x5EAB0F / 0x5EABBF), and its per-SOURCE-texel blend (one table lookup
# against the dest pixel at the block's top-left, copied over the whole block) -- with a row
# replay of any length.  At or below the cap it is the native call, so crossing 4.0 is seamless
# (the replica equals the native core pixel for pixel at <= 4.0: test_effect_cap_asm_parity.py).
# No g: the cap is a ratio, so the gate is the ratio itself.
ENGINE_SCALE_MAX = 4.0


def f32(v: float) -> float:
    """Round a double to IEEE single (the engine's `fstp dword` of num/den)."""
    import struct
    return struct.unpack("<f", struct.pack("<f", v))[0]


def engine_scale_f(num: int, den: int) -> float:
    """The engine's ratio float: fild num; fidiv den; fstp dword (0x9B6624)."""
    return f32(num / den)


def engine_scale_rejects(num: int, den: int) -> bool:
    """True when the engine's scaled sprite core draws NOTHING: num != den (1:1 skips the check) and
    the float32 ratio compares greater than 4.0 (`test ah,0x41` accepts below AND equal)."""
    return num != den and engine_scale_f(num, den) > ENGINE_SCALE_MAX


def _ftol(v: float) -> int:
    """MSVC _ftol 0x6458C8: truncate toward zero."""
    return int(v)


def effect_blit_rect(x: int, y: int, off_x: int, off_y: int, w: int, h: int,
                     num: int, den: int) -> Tuple[int, int, int, int]:
    """(L0, T0, W', H'): the dest rect the engine's scaled path computes (0x5E92D7) for a sprite of blit
    size w x h at draw offsets (off_x, off_y), drawn at (x, y), ratio num/den, in its own arithmetic:
    H' = ftol(h*f), W' = ftol(w*f), T0 = ftol(y + off_y*f), L0 = ftol(x + off_x*f), f =
    engine_scale_f.  The over-cap path keeps exactly this rect (anchor and size of an uncapped
    engine)."""
    f = engine_scale_f(num, den)
    return (_ftol(x + off_x * f), _ftol(y + off_y * f), _ftol(w * f), _ftol(h * f))


def effect_blit_clip(rect: Tuple[int, int, int, int],
                     clip: Tuple[int, int, int, int]) -> Optional[Tuple[int, int, int, int]]:
    """(Lc, Tc, cw, ch) = rect (L0, T0, W', H') intersected with the dest clip (l, t, r, b; right/bottom
    exclusive -- the engine's IntersectRect against dest+0x20); None when empty."""
    l0, t0, w, h = rect
    lc, tc = max(l0, clip[0]), max(t0, clip[1])
    cw, ch = min(l0 + w, clip[2]) - lc, min(t0 + h, clip[3]) - tc
    if cw <= 0 or ch <= 0:
        return None
    return (lc, tc, cw, ch)


def engine_scale_runs(num: int, den: int, n: int) -> List[int]:
    """Port of Sprite_fill_scaling_table (0x5EB20F): the first n dest-run lengths, one per SOURCE pixel,
    for ratio num/den (hi = max, lo = min).  lo > 1: base = hi div lo, err = hi mod lo - 2lo, then per
    entry err += 2(hi mod lo), run = base + 1 and err -= 2lo when err > 0, else base.  An odd base starts
    err higher by hi.  lo == 1: every run is hi.  The engine stores 800 entries; this generates n."""
    hi, lo = max(num, den), min(num, den)
    if lo > 1:
        base, rem = divmod(hi, lo)
        inc, dec = 2 * rem, 2 * lo
        err = rem - dec
    else:
        base, inc, dec, err = hi, 0, 0, 0
    if base & 1:
        err += hi
    if lo == 1:
        return [base] * n
    runs = []
    for _ in range(n):
        err += inc
        if err > 0:
            runs.append(base + 1)
            err -= dec
        else:
            runs.append(base)
    return runs


def engine_run_blocks(runs: List[int], off: int, span: int) -> List[Tuple[int, int]]:
    """Port of the clipped-table builders (0x5EAB0F x / 0x5EABBF y): the (source index, dest length) blocks
    covering a clipped span that starts `off` dest pixels into the unclipped rect.  Whole runs are skipped
    while off > 0; a run straddling the clip edge gives a partial first block; the last block is cut to the
    span.  Source indices are NOT bounded by the sprite (neither are the engine's)."""
    i = 0
    while off > 0:
        off -= runs[i]
        i += 1
    blocks: List[Tuple[int, int]] = []
    if off < 0:
        blocks.append((i - 1, -off))
        span -= -off
    j = i
    while span > 0:
        blocks.append((j, runs[j]))
        span -= runs[j]
        j += 1
    if span < 0:
        k, ln = blocks[-1]
        blocks[-1] = (k, ln + span)
    return blocks


def effect_blit_engine(dest: bytearray, dpitch: int, src, pitch: int, key: int, table: bytes,
                       rect: Tuple[int, int, int, int], clip: Tuple[int, int, int, int], num: int, den: int) -> None:
    """The enlarge path of Sprite_draw_table with an unbounded row replay, in place on dest (dpitch per row):
    rows and columns from engine_run_blocks over engine_scale_runs(num, den); per (row block, column block)
    the source texel s = src[row*pitch + col]; s == key (low byte) leaves the block; otherwise ONE lookup
    table[s << 8 | dest at the block's top-left] fills the whole block.  rect = effect_blit_rect, clip = the
    dest clip (l, t, r, b exclusive)."""
    crop = effect_blit_clip(rect, clip)
    if crop is None:
        return
    lc, tc, cw, ch = crop
    l0, t0 = rect[0], rect[1]
    n = max(lc - l0 + cw, tc - t0 + ch) + 2
    runs = engine_scale_runs(num, den, n)
    cols = engine_run_blocks(runs, lc - l0, cw)
    y = tc
    for r, rl in engine_run_blocks(runs, tc - t0, ch):
        x = lc
        for c, cl in cols:
            s = src[r * pitch + c]
            if s != (key & 0xFF):
                v = table[(s << 8) | dest[y * dpitch + x]]
                for yy in range(y, y + rl):
                    dest[yy * dpitch + x:yy * dpitch + x + cl] = bytes([v]) * cl
            x += cl
        y += rl


def buster_scale(zoom_idx: int, reactor: int) -> Tuple[int, int]:
    """boom's Planet Buster blit ratio (num, den) = ((zoom+16)*k14, k10*16); reactor 1..4 = Fission 3/2,
    Fusion 4/2, Quantum 5/2, Singularity 5/2 (boom's stack tables [ebp-0x88] / [ebp-0x98] indexed by
    g_pb_reactor 0x90F7D4)."""
    k14 = {1: 3, 2: 4, 3: 5, 4: 5}[reactor]
    return ((zoom_idx + 16) * k14, 2 * 16)


# --- map sprites above the engine's 4.0 enlarge cap: every capped core, uncapped (2026-10-11) -------------------
# PRACX zooms the main map to zoom_idx 72 at 4K; unit flags, base icons and the terrain overlay sprites are drawn at
# map_sprite_scale = (zoom+16)/16 through the capped cores, so from zoom 49 (ratio > 4.0) they vanish.  The fix sits
# on the 8 cores' shared reject path and draws what an uncapped engine would, for ANY core: the same rect / clip /
# runs as effect_blit_engine (engine_scale_runs walked by engine_run_blocks, source indices unbounded like the
# engine's), and the per-SOURCE-texel value computed by the core itself -- one 1:1 composite of the block's texel
# onto the block's top-left dest pixel -- then copied over the block (engine_enlarge_blit, `value` = the core's
# per-pixel rule).  At or below the cap the native core runs; the parity suite checks the replica equals the REAL
# cores pixel for pixel at <= 4.0 on noisy backgrounds, so crossing the cap is seamless.


def engine_enlarge_blit(dest: bytearray, dpitch: int, src, pitch: int, key: int, value,
                        rect: Tuple[int, int, int, int], clip: Tuple[int, int, int, int], num: int, den: int) -> None:
    """effect_blit_engine for any core: per (row block, column block) the source texel s; s == key (low byte)
    leaves the block; otherwise v = value(s, dest at the block's top-left) fills the whole block (keyed core:
    value = s; mono: the colour; table cores: table[s << 8 | d])."""
    crop = effect_blit_clip(rect, clip)
    if crop is None:
        return
    lc, tc, cw, ch = crop
    l0, t0 = rect[0], rect[1]
    runs = engine_scale_runs(num, den, max(lc - l0 + cw, tc - t0 + ch) + 2)
    cols = engine_run_blocks(runs, lc - l0, cw)
    y = tc
    for r, rl in engine_run_blocks(runs, tc - t0, ch):
        x = lc
        for c, cl in cols:
            s = src[r * pitch + c]
            if s != (key & 0xFF):
                v = value(s, dest[y * dpitch + x])
                for yy in range(y, y + rl):
                    dest[yy * dpitch + x:yy * dpitch + x + cl] = bytes([v]) * cl
            x += cl
        y += rl


def map_sprite_scale(zoom_idx: int, zoom_num: int = 0, zoom_den: int = 0) -> Tuple[int, int]:
    """SCALE_NUM_G/DEN_G for map sprites (veh_draw 0x55971F, base_draw 0x55B15C, MapWin_gen_terrain_poly
    0x464D38): (g_map_zoom_num, g_map_zoom_den) when g_map_zoom_num > 0, else (zoom_idx + 16, 16)."""
    return (zoom_num, zoom_den) if zoom_num > 0 else (zoom_idx + 16, 16)


def pracx_max_zoom(screen_w: int, screen_h: int) -> int:
    """PRACX ZoomInit (refs/pracx/shared/pracx.cpp): the deepest zoom = the first even z whose tile
    (i*8 x i*4, i = (50*(z+16)/16 + 1)/4) leaves <= 6 tiles across or <= 3 down the map area (H - 213)."""
    z = 0
    while True:
        z += 2
        i = (50 * (z + 16) // 16 + 1) // 4
        if not (screen_w // max(i * 8, 1) > 6 and (screen_h - 213) // max(i * 4, 1) > 3):
            return z


# ==== stripe regeneration: the leftover thunks' laws (fix 7, 2026-10-17) =============================================
# Laws the shipped bytes ALREADY carry, moved here from their assemblers / tests (no byte changed by the move):
#   stretchblt_centre_nn          Buffer_copy_3 = GDI StretchBlt, as MEASURED (the engine stretch t_hud_backdrop wraps)
#   column_dither_marks           the ONE vertical A,B,A,B column rule: t_hb_col, t_spr_stripes (+ its neighbour
#                                 condition), t_sbt_zoom (btn_dither_marks)
#   pair_top_by_colour            pair_top's colour order (t_hb_col ports it without the DITHER_FORCE_PAIRS table)
#   vertical_dither_regen         t_hud_backdrop + t_hb_* (dest-driven statement)
#   devfill_inset / devfill_stage_rect    thunk_box_thick_devfill v2: STEP2 inset, STEP3 staging (applied 2026-10-06)
#   popup_scale_num               thunk_ensure_scale's g (scale_uniform / popup_g: scale_uniform + thunk_ensure_scale, W x H -> g)
#   stripe_tile_rows              thunk_ensure_stripes' two scratch tiles
#   drop_arrow_render             thunk_faction_dropimg (the faction row drop-arrow)
#   strip_synth_dims / strip_synth_pair / strip_synth    hm_synth_core (MENU / COMMLINK strips)
#   se_tile_rows                  thunk_se_tiles' slider bar tiles
# Parity: tests/test_stripes_leftovers_asm_parity.py, test_ensure_scale_parity.py, test_ensure_stripes_parity.py,
# test_faction_dropimg_parity.py, test_hm_synth_core_parity.py, test_se_asm_parity.py; law tests:
# test_scaling_stripe_regen_laws.py.

DITHER_WINDOW_ROWS = 4          # a column texel is dither when it lies in a vertical window A,B,A,B of 4 rows
HB_MAX_SRC_H = 0x200            # t_hud_backdrop's stack planes: one byte per native row (refuses a taller source)
STRIPE_TILE_W = 0x800           # thunk_ensure_stripes: Buffer_resize(0x800, P) for both scratch tiles
STRIPE_TILE_PAIRS = ((0xC4, 0x41), (0xE0, 0xE1))   # g_stripe_navy, g_stripe_sel: (top, mate)
DROP_ARROW_PAIR = (0xAE, 0xEE)  # thunk_faction_dropimg: the drop arrow's scanline members (top, mate)
STRIP_SYNTH_SRC_W = (3, 2048)   # hm_synth_core refuses a sprite outside these blit widths ...
STRIP_SYNTH_SRC_H = (2, 256)    # ... and heights (inclusive)


def stretchblt_centre_nn(dest: bytearray, stride: int, src_rows, *, sx: int, sy: int, sw: int, sh: int,
                         dx: int, dy: int, dw: int, dh: int) -> None:
    """Buffer_copy_3 = GDI StretchBlt, SRCCOPY, 8-bit: MEASURED centre-aligned NN on both axes
    (nn_center_index).  On the console strip of the 4K / 1080 shots 97.1 % / 99.2 % of the top 40 rows equal
    this model and 66 % / 51 % the floor model; the rest is overdrawn chrome.  No clip: the engine clips to the
    dest bitmap only.  src_rows = the whole source plane (rows), the rect is (sx, sy, sw, sh)."""
    for y in range(dh):
        row = src_rows[sy + nn_center_index(y, dh, sh)]
        o = (dy + y) * stride + dx
        for x in range(dw):
            dest[o + x] = row[sx + nn_center_index(x, dw, sw)]


def column_dither_marks(rows, key: int, *, rect=None) -> dict:
    """{(r, c): mate} for every texel of the source RECT (sx, sy, sw, sh) (default: all of `rows`; r, c are
    rect-relative) that lies in a vertical window of DITHER_WINDOW_ROWS rows A,B,A,B of its column (A != B,
    neither the key).  Windows are tested top to bottom; a window starting at row r owns rows r..r+3 from r on, so
    the LAST window that starts at or above a row owns it, and the mate is that window's other member.
    No neighbour condition: t_hb_col uses it as is (the console separators are single columns); t_spr_stripes
    adds one on top (assemble_stripes_spr.spr_marks); t_sbt_zoom's chain (btn_dither_marks) is this rule."""
    if rect is None:
        sx, sy, sw, sh = 0, 0, len(rows[0]), len(rows)
    else:
        sx, sy, sw, sh = rect
    q = DITHER_WINDOW_ROWS
    out = {}
    for c in range(sw):
        rem, pair = 0, (0, 0)
        for r in range(sh):
            if r + q - 1 < sh:
                p0, p1, p2, p3 = (rows[sy + r + k][sx + c] for k in range(q))
                if p0 != p1 and p0 != key and p1 != key and p0 == p2 and p1 == p3:
                    pair, rem = (p0, p1), q
            if rem:
                rem -= 1
                out[(r, c)] = pair[0] ^ pair[1] ^ rows[sy + r][sx + c]
    return out


def pair_top_by_colour(a: int, b: int, rgb) -> int:
    """pair_top's colour order, without the DITHER_FORCE_PAIRS table: the member with the higher PEAK channel, ties
    by channel sum, then the lower index; `rgb(i)` -> (r, g, b).  t_hb_col compares the packed key
    peak << 20 | sum << 8 | (255 - i) (sum <= 765 < 4096, so the fields never overlap); A wins ties, which only
    a == b can produce.  Under the game palette it picks the table's member on every DITHER_FORCE_PAIRS pair
    (pinned in test_scaling_stripe_regen_laws.py)."""
    ra, rb = rgb(a), rgb(b)
    ka, kb = (max(ra), sum(ra), -a), (max(rb), sum(rb), -b)
    return a if ka >= kb else b


def vertical_dither_regen(dest: bytearray, stride: int, src_rows, key: int, g: int, rgb, *, sx: int, sy: int,
                          sw: int, sh: int, dx: int, dy: int, dw: int, dh: int, clip, regen: bool = True) -> None:
    """t_hud_backdrop (+ t_hb_col / t_hb_paint / t_hb_setup), DEST-DRIVEN: every pixel of the dest rect takes the
    engine stretch (stretchblt_centre_nn); at g > 16, on an enlarge of both axes of a source DITHER_WINDOW_ROWS ..
    HB_MAX_SRC_H rows tall, a pixel inside the dest clip (half-open l, t, r, b, buffer space) whose centre-NN
    texel is column-marked (column_dither_marks over the src rect) takes the pair's top (pair_top_by_colour on the
    dest buffer's colour table) where stripe_top(dest-buffer row, g), else the mate.  `regen=False` = the engine
    stretch alone.  The thunk's other refusals (copy failed, null planes, period < 2, negative offsets, either
    rect outside its buffer, empty clip) leave the engine draw and are not part of this law."""
    cm = [nn_center_index(x, dw, sw) for x in range(dw)]
    rm = [nn_center_index(y, dh, sh) for y in range(dh)]
    live = (regen and g > NATIVE_G and dw > sw and dh > sh and DITHER_WINDOW_ROWS <= sh <= HB_MAX_SRC_H)
    marks = column_dither_marks(src_rows, key, rect=(sx, sy, sw, sh)) if live else {}
    xs, xe = max(0, clip[0] - dx), min(dw, clip[2] - dx)
    ys, ye = max(0, clip[1] - dy), min(dh, clip[3] - dy)
    tops = {}
    for y in range(dh):
        r = rm[y]
        row = src_rows[sy + r]
        o = (dy + y) * stride + dx
        regen_row = live and ys <= y < ye
        on_top = stripe_top(dy + y, g)
        for x in range(dw):
            c = cm[x]
            v = row[sx + c]
            if regen_row and xs <= x < xe:
                mate = marks.get((r, c))
                if mate is not None:
                    top = tops.get((v, mate))
                    if top is None:
                        top = tops[(v, mate)] = pair_top_by_colour(v, mate, rgb)
                    v = top if on_top else (v ^ mate ^ top)
            dest[o + x] = v


def devfill_inset(g: int) -> int:
    """thunk_box_thick_devfill v2's STEP2 inset N = (g+15)>>4 (right / bottom: N+1) -- NOT the stroke width
    (the same arithmetic as btn_ring_k, a different meaning)."""
    return (g + 15) >> 4


def devfill_stage_rect(rect) -> Tuple[int, int, int, int]:
    """(x, y, w, h) thunk_box_thick_devfill's STEP3 stages into g_fe_x / g_fe_y / g_fe_w / g_fe_h for the
    INCLUSIVE frame rect (L, T, R, B): the whole frame, (L, T, R-L+1, B-T+1) (applied 2026-10-06; before, the
    devfill_inset scratch rect, which left STEP1's banded fill as a ring).  g <= 16: devfill draws natively and
    stages nothing."""
    l, t, r, b = rect
    return l, t, r - l + 1, b - t + 1


def popup_scale_num(raw: int) -> int:
    """g_popup_scale_num as thunk_ensure_scale stores it: raw = scale_uniform(16) (min of both axes, floored --
    see scale_uniform / popup_g), clamped to G_MIN..G_MAX.  The same thunk stores g_stripe_period = stripe_period(g) next to it with the closed form
    (g < 22 ? 2 : 4), which is the law only for g <= 47: the clamp at G_MAX is what keeps them equal
    (test_ensure_scale_parity.py guards the pairing).  Written once (a non-zero g is cached)."""
    return min(G_MAX, max(G_MIN, raw))


# scale_uniform's operands, written as the asm's own immediates (mov ecx,0x300 / mov edx,0x400 / mov ecx,0x400): the
# native screen of the g = 16 baseline.  Their one use is DERIVING g from the screen (scale_uniform / popup_g) --
# never a gate (test_scaling_law_guards bans decimal screen literals in law code).
SCALE_UNIFORM_BASE_W, SCALE_UNIFORM_BASE_H = 0x400, 0x300


def scale_uniform(dim: int, screen_w: int, screen_h: int) -> int:
    """scale_uniform (menu_strip_thunks +0x00 @0x668200): dim x min(W/1024, H/768), FLOORED.  The asm compares
    the cross products unsigned (`W*768 > H*1024` -> the H axis, else the W axis; a tie takes the W axis), then
    `mul` / `div` unsigned: wider than 4:3 -> dim*H // 768, else dim*W // 1024.  32-bit products as the bytes
    compute them (`mul` keeps edx:eax, so dim*H is exact; the comparison products wrap at 2^32)."""
    m = 0xFFFFFFFF
    if (screen_w * SCALE_UNIFORM_BASE_H) & m > (screen_h * SCALE_UNIFORM_BASE_W) & m:
        return ((dim & m) * (screen_h & m)) // SCALE_UNIFORM_BASE_H
    return ((dim & m) * (screen_w & m)) // SCALE_UNIFORM_BASE_W


def popup_g(screen_w: int, screen_h: int) -> int:
    """THE g a W x H screen runs at: g_popup_scale_num as thunk_ensure_scale (0x668760) stores it on that screen,
    popup_scale_num(scale_uniform(16, W, H)) =

        g = clamp(floor(16 * min(W/1024, H/768)), 16, 40)

    -- the MIN of both axes, FLOORED (bytes-verified: test_scaling_popup_g_parity.py emulates the real
    scale_uniform + thunk_ensure_scale bytes).  NOT height-only and NOT rounded: 1280x1024 runs at 20 (not 21),
    1600x900 at 18 (not 19), and every 16:9 screen up to 1366 wide at 16 (native) while W > 1024 -- which is why a
    lo-res gate keys on g, never on ScreenWidth.  Any table of "the g each resolution runs at" comes from here."""
    return popup_scale_num(scale_uniform(16, screen_w, screen_h))


# ---- SetupWin menu strip: the main menu and every SetupWin strip submenu (SetupWin_do_menu_rightside 0x4ADB70,
# SetupWin_draw_item 0x4AE4D0). Vanilla magnitudes, read off the pristine bytes:
MENU_STRIP_W, MENU_STRIP_H = 354, 75      # openitem.flc frame: [SetupWin+0x1198] / -[SetupWin+0x119C]
MENU_STRIP_SEP_H = 20                     # titled menu: the colour-9 separator under the title strip (0x4ADF50 / 0x4AE199)
MENU_STRIP_FONT = 18                      # Font_init(&font, name, 0x12, 1) @0x4ADC8E
MENU_STRIP_HIT_L = 15                     # Spot rect left   (0x4ADFAC mov [ebp-0x1c], 0xF)
MENU_STRIP_HIT_R = 300                    # Spot rect right  (0x4ADFA5 mov eax, 0x12C)
MENU_STRIP_TEXT_L = 27                    # draw_item text rect: hit L + 4 + 8 (0x4AE587 / 0x4AE590)
MENU_STRIP_TEXT_R = 304                   #                      hit R - 4 + 8 (0x4AE58A / 0x4AE593)
MENU_STRIP_TEXT_T = 33                    # text band: strip top + 0x1F + 2        (0x4AE502 / 0x4AE57E)
MENU_STRIP_TEXT_B = 55                    #            strip top + 0x1F + 0x1A - 2 (0x4AE50E / 0x4AE58D)
MENU_STRIP_CLIP_T = 31                    # draw_item clip band: strip top + 0x1F  (0x4AE502)
MENU_STRIP_CLIP_B = 57                    #                      strip top + 0x39  (0x4AE50E)
MENU_STRIP_TITLE_INSET = 4                # titled menu: title rect = hit rect inset 4 each side (0x4ADFE0 mov ebx, 4)


def menu_strip_px(v: int, g: int) -> int:
    """The SetupWin menu-strip law (thunk strip_px, menu_strip_thunks): every strip magnitude is
    v if g <= 16 else floor(v * g/16) -- vanilla x g/16 on the ONE lever, the same rule as basewin_pt, so
    g <= 16 (1024x768, 800x600, every 16:9 screen up to 1366 wide) is vanilla's native strip.

    It replaced scale_uniform (unclamped min(W/1024, H/768)): that drew 800x600 at 0.78x, 1366x1024 at 1.33x
    where g = 20, and 4K at 2.81x past the g = 40 cap every other screen stops at."""
    return basewin_pt(v, g)


def menu_strip_layout(screen_w: int, screen_h: int, items: int, titled: bool, g: int) -> dict:
    """Every coordinate SetupWin hands an engine primitive for an `items`-item strip menu, on the law
    menu_strip_px (s below). Each element is vanilla's magnitude through s, rects in EDGE form (each edge its own
    s(v): text L = s(27), not s(15) + s(12)), strips at the uniform pitch s(75) (every strip is the same
    stretched art):

      font      s(18)
      window    w = s(354), h = n*s(75) + (s(20) if titled); bottom-right: (screen_w - w, screen_h - h)
                (n = items + 1 for a titled menu: the title is strip 0)
      strips    the open/close animation strips, (x, y, w, h) = (0, y_i, s(354), s(75)) with the separator
                (0, s(75), s(354), s(20)) after the title strip and every later strip pushed down by s(20)
      spots     item i's hit rect (x, y, w, h) = (s(15), T_i, s(300) - s(15), s(75)), T_i = T0 + i*s(75),
                T0 = s(75) + s(20) titled else 0 -- exactly the rows of the strip draw_item paints for it
      title     titled menu: the title text rect (L, T, R, B) = (s(15) + s(4), s(33), s(300) - s(4), s(55))
      item      per item, draw_item's three primitives: the clip band (s(15), T + s(31), s(300), T + s(57)),
                the strip blit (0, T, s(354), s(75)), the text rect (s(27), T + s(33), s(304), T + s(55))
    """
    def s(v):
        return menu_strip_px(v, g)
    n = items + (1 if titled else 0)
    w, pitch, sep = s(MENU_STRIP_W), s(MENU_STRIP_H), s(MENU_STRIP_SEP_H)
    h = n * pitch + (sep if titled else 0)
    strips, separator, y = [], None, 0
    for i in range(n):
        strips.append((0, y, w, pitch))
        y += pitch
        if i == 0 and titled:
            separator = (0, y, w, sep)
            y += sep
    t0 = pitch + sep if titled else 0
    hit_l, hit_r = s(MENU_STRIP_HIT_L), s(MENU_STRIP_HIT_R)
    spots = [(hit_l, t0 + i * pitch, hit_r - hit_l, pitch) for i in range(items)]
    inset = s(MENU_STRIP_TITLE_INSET)
    title = (hit_l + inset, s(MENU_STRIP_TEXT_T), hit_r - inset, s(MENU_STRIP_TEXT_B)) if titled else None
    item = []
    for _x, top, _w, _h in spots:
        item.append({"clip": (hit_l, top + s(MENU_STRIP_CLIP_T), hit_r, top + s(MENU_STRIP_CLIP_B)),
                     "blit": (0, top, w, pitch),
                     "text": (s(MENU_STRIP_TEXT_L), top + s(MENU_STRIP_TEXT_T), s(MENU_STRIP_TEXT_R),
                              top + s(MENU_STRIP_TEXT_B))})
    return {"font": s(MENU_STRIP_FONT), "window": (screen_w - w, screen_h - h, w, h), "strips": strips,
            "separator": separator, "spots": spots, "title": title, "item": item}


# ---- The opening backdrop and the planet-customisation decoration (SetupWin_draw_item's deco block 0x4AE679..
# 0x4AE740: the Ocean Coverage / Clouds / Native Life planet, the Erosive Forces moons).  The backdrop is drawn by
# change_opening (0x589A30): its Buffer_copy_3 @0x589AE8 STRETCHES the art over the whole screen, per axis
# (art w x h -> ScreenWidth x ScreenHeight).  Which art is the CALLER's choice, on ScreenWidth alone (0x58E422 /
# 0x58E4D0 / 0x58E59D / 0x58E615 `cmp eax, edi(0x320)`): ScreenWidth == 800 -> (x)openingb.pcx (800x600), else
# (x)openinga.pcx (1024x768).  The decoration loader (custom_planet 0x58C454 / 0x58C4AA / 0x58C5E0 / 0x58C6BC) keys
# on the same test: the 800 art gets its own placement (planet at (449, -168), moon{n}_800.pcx at (0, 0)), every
# other width the 1024 placement (planet right-aligned at (W - 404, 0), MOON{n}.PCX at (0, 0)).
OPENING_ART_B_W, OPENING_ART_B_H = 0x320, 0x258     # (x)openingb.pcx: the engine's own asset choice, never a lever
OPENING_ART_A_W, OPENING_ART_A_H = SCALE_UNIFORM_BASE_W, SCALE_UNIFORM_BASE_H   # (x)openinga.pcx


def opening_art(screen_w: int) -> Tuple[int, int]:
    """(w, h) of the art change_opening stretches over a ScreenWidth-wide screen: the 800x600 art iff ScreenWidth
    is its width, else the 1024x768 art -- the engine's own test (0x58E422), not a scaling gate."""
    if screen_w == OPENING_ART_B_W:
        return OPENING_ART_B_W, OPENING_ART_B_H
    return OPENING_ART_A_W, OPENING_ART_A_H


def opening_backdrop_native(screen_w: int, screen_h: int) -> bool:
    """The backdrop is drawn 1:1 (its art IS the screen size: 800x600, 1024x768).  Then the decoration is vanilla's
    own draw, callee for callee; on any other screen the backdrop is stretched and the decoration with it."""
    return (screen_w, screen_h) == opening_art(screen_w)


def opening_map_x(v: int, screen_w: int) -> int:
    """The backdrop's x map (scale_x, menu_strip_thunks +0x370): v * ScreenWidth / art_w, `imul` / `idiv`
    (truncates toward zero).  The identity on the 800 art (800 / 800) and at ScreenWidth 1024."""
    return _trunc_div(v * screen_w, opening_art(screen_w)[0])


def opening_map_y(v: int, screen_w: int, screen_h: int) -> int:
    """The backdrop's y map (scale_y, +0x390): v * ScreenHeight / art_h, signed (the 800 planet sits at y = -168)."""
    return _trunc_div(v * screen_h, opening_art(screen_w)[1])


def opening_deco(x: int, y: int, src_w: int, src_h: int, keyed: bool, screen_w: int, screen_h: int) -> dict:
    """One decoration draw on a W x H screen, from the slot the loader wrote ((x, y) = [SetupWin+0xA28/0xA34 +4i])
    and the art's (src_w, src_h).  THE LAW: the decoration follows the backdrop's own mapping.

      backdrop drawn 1:1 (opening_backdrop_native): vanilla -- "copy4" (opaque: Buffer_copy_4 1:1 at (x, y)) or
          "draw2" (keyed: Buffer_draw_2 at (x, y), 1/1), refreshed at (x, y, src_w, src_h);
      backdrop stretched: the same per-axis stretch, dw = map_x(src_w), dh = map_y(src_h):
          opaque "copy3" at (x + src_w - dw, map_y(y), dw, dh) -- the loader right-aligns the planet in SCREEN
          space (x = W - src_w), so its right edge is held (= W - dw, the art's own 620 * W/1024 slot); the 800
          art's (449, -168) has map_x = identity and map_y(-168) = -168 * H/600;
          keyed "ksb" (thunk_keyed_stretch_blit, key 9) at (x, y, dw, dh) -- the moons sit at the art origin
          (0, 0), which every map keeps;
      refresh (thunk_deco_soft_update, path-agnostic -- it runs after either draw): rw = max(dw, src_w),
          (max(0, x + src_w - rw), map_y(y), rw, dh).  It covers BOTH draws: enlarging, rw = dw and the opaque
          span exactly (keyed x = 0 clamps to [0, dw)); shrinking (a screen narrower than its art, W < 1024 and
          != 800), rw = src_w covers [x, x + src_w), which holds the keyed [x, x + dw) AND the opaque
          [x + src_w - dw, x + src_w).  On the native screens it IS vanilla's refresh."""
    if opening_backdrop_native(screen_w, screen_h):
        return {"native": True, "draw": ("draw2" if keyed else "copy4", x, y, src_w, src_h),
                "refresh": (x, y, src_w, src_h)}
    dw, dh = opening_map_x(src_w, screen_w), opening_map_y(src_h, screen_w, screen_h)
    if keyed:
        draw = ("ksb", x, y, dw, dh)
    else:
        draw = ("copy3", x + src_w - dw, opening_map_y(y, screen_w, screen_h), dw, dh)
    rw = max(dw, src_w)
    return {"native": False, "draw": draw,
            "refresh": (max(0, x + src_w - rw), opening_map_y(y, screen_w, screen_h), rw, dh)}


def stripe_tile_rows(top: int, mate: int, g: int, override: int = 0) -> List[int]:
    """thunk_ensure_stripes' scratch tile, one index per row: P = stripe_period(g) rows (Buffer_resize(0x800, P)),
    top on rows [0, hN), mate on [hN, P), hN = (P+1)>>1 (= stripe_rows(g): P is even), so Buffer_tile's absolute
    anchoring puts row y on stripe_top(y, g).  Two tiles: STRIPE_TILE_PAIRS (navy, sel)."""
    p = stripe_period(g, override)
    hn = (p + 1) >> 1
    return [top] * hn + [mate] * (p - hn)


def drop_arrow_render(src_rows, out_w: int, out_h: int, g: int) -> List[List[int]]:
    """thunk_faction_dropimg v3's render (the faction row's drop arrow: a 16 x 16 state sprite -- state 0 an AE / EE
    1-row scanline background, a 41 glyph and key-9 corners; state 1 the same with an E0 1-px ring and an E0 glyph;
    state 2 an E1 / E0 scanline background and a 41 glyph).  The WHOLE dest buffer out_w x out_h from (0, 0):
      1. MIRROR-SYMMETRIC centre NN (nn_mirror_index on both axes; v2 was floor NN, which shifted the glyph a
         column left / up -- 1600x1200 margins 4 | 3);
      2. pair regeneration on the dest-row stripe grid (stripe_top(r, g)): AE / EE -> AE on top rows, else EE (AE on
         top as in pair_remap_pixel); E1 -> E0 on top rows, else E1, and E0 likewise ONLY when the source holds an
         E1 texel (content-keyed: state 1 uses E0 as a SOLID ring + glyph colour, state 2 as a dither member;
         [[feedback-dither-pair-ambiguity]]) -- v2 copied E0 / E1 through the NN, so the pressed face banded;
      3. each source edge with a 1-px stroke (edge_stroke_colour at the middle row / column) redrawn as a
         K = btn_edge_stroke(g) band of its colour on all of that side (needs out_w, out_h >= 2K);
      4. each corner whose source corner texel is the key punched to an s x s key square, s = btn_corner_notch(g)
         (v2 kept the NN image of the 1-px notch: 1600x1200 TL 2x2, TR 1x2, BL 2x1, BR 1x1).
    No keying while writing: the buffer is the arrow's own."""
    sh, sw = len(src_rows), len(src_rows[0])
    has_e1 = any(v == 0xE1 for r in src_rows for v in r)
    out = []
    for r in range(out_h):
        src = src_rows[nn_mirror_index(r, out_h, sh)]
        on_top = stripe_top(r, g)
        line = []
        for c in range(out_w):
            v = src[nn_mirror_index(c, out_w, sw)]
            if v in DROP_ARROW_PAIR:
                v = DROP_ARROW_PAIR[0] if on_top else DROP_ARROW_PAIR[1]
            elif v == 0xE1 or (v == 0xE0 and has_e1):
                v = 0xE0 if on_top else 0xE1
            line.append(v)
        out.append(line)
    k = btn_edge_stroke(g)
    if sw >= 3 and sh >= 3 and out_w >= 2 * k and out_h >= 2 * k:
        xm, ym = sw >> 1, sh >> 1
        cols = (edge_stroke_colour(src_rows[0][xm], src_rows[1][xm], src_rows[2][xm]),
                edge_stroke_colour(src_rows[sh - 1][xm], src_rows[sh - 2][xm], src_rows[sh - 3][xm]),
                edge_stroke_colour(src_rows[ym][0], src_rows[ym][1], src_rows[ym][2]),
                edge_stroke_colour(src_rows[ym][sw - 1], src_rows[ym][sw - 2], src_rows[ym][sw - 3]))
        for col, (x0, y0, bw, bh) in zip(cols, edge_band_rects(out_w, out_h, k)):
            if col is not None:
                for y in range(y0, y0 + bh):
                    for x in range(x0, x0 + bw):
                        out[y][x] = col
        s = btn_corner_notch(g)
        for (sy, sx), (y0, x0) in (((0, 0), (0, 0)), ((0, sw - 1), (0, out_w - s)), ((sh - 1, 0), (out_h - s, 0)),
                                   ((sh - 1, sw - 1), (out_h - s, out_w - s))):
            if src_rows[sy][sx] == EDGE_STROKE_KEY:
                for y in range(y0, y0 + s):
                    for x in range(x0, x0 + s):
                        out[y][x] = EDGE_STROKE_KEY
    return out


def strip_synth_dims(w: int, h: int, num: int, den: int) -> Tuple[int, int]:
    """hm_synth_core's dest rect size: (w*num + den/2) // den on each axis -- HALF-UP at an exact half (not LAW 1's
    half_down: the strip can be 1 px larger than scale_px there; user-verified at 4K / 1080 / 1600 as is)."""
    return (w * num + (den >> 1)) // den, (h * num + (den >> 1)) // den


def strip_synth_pair(src_rows, key: int):
    """hm_synth_core's per-draw pair probe: at the middle column xm = sw >> 1, rows r = sh >> 1 then r - 1 (each
    needs 1 <= r and r + 2 < sh): a = src[r][xm], b = src[r+1][xm], a != b, neither the key, src[r-1][xm] == b and
    src[r+2][xm] == a.  -> (light, dark) with light = the member on the EVEN native row (a if r is even, else b),
    or None."""
    sh, sw = len(src_rows), len(src_rows[0])
    xm = sw >> 1
    r = sh >> 1
    for _ in range(2):
        if r >= 1 and r + 2 < sh:
            a, b = src_rows[r][xm], src_rows[r + 1][xm]
            if a != b and a != key and b != key and src_rows[r - 1][xm] == b and src_rows[r + 2][xm] == a:
                return (a, b) if r % 2 == 0 else (b, a)
        r -= 1
    return None


def strip_synth(dest: bytearray, stride: int, buf_w: int, buf_h: int, src_rows, key: int, dx: int, dy: int,
                num: int, den: int, g: int) -> None:
    """hm_synth_core(dst, dx, dy, num, den, spr), run after the engine's strip blit: re-synthesises the whole dest
    rect strip_synth_dims at (dx, dy), cut to the buffer [0, buf_w) x [0, buf_h): dest (x, y) reads texel
    (min((y-dy)*den // num, sh-1), min((x-dx)*den // num, sw-1)) (floor NN, edge-clamped: it covers the last row
    the engine's expander drops); a member of strip_synth_pair becomes light on stripe_top(y, g) rows, else dark;
    a key texel leaves the pixel.  g <= 16, a source outside STRIP_SYNTH_SRC_W x STRIP_SYNTH_SRC_H, den <= 0 or an
    empty cut: nothing.  Domain num > den: the asm steps its row / column DDA at most once per pixel, which is the
    floor map only there (both callers pass (g, 16) or (sc(18), 18) with g > 16)."""
    if g <= NATIVE_G:
        return
    sh, sw = len(src_rows), len(src_rows[0])
    if not (STRIP_SYNTH_SRC_W[0] <= sw <= STRIP_SYNTH_SRC_W[1] and STRIP_SYNTH_SRC_H[0] <= sh <= STRIP_SYNTH_SRC_H[1]):
        return
    if den <= 0:
        return
    if num <= den:
        raise ValueError(f"strip_synth: num {num} <= den {den} is outside the asm's single-step DDA domain")
    dw, dh = strip_synth_dims(sw, sh, num, den)
    xs, ys = max(dx, 0), max(dy, 0)
    xe, ye = min(dx + dw, buf_w), min(dy + dh, buf_h)
    if xe <= xs or ye <= ys:
        return
    pair = strip_synth_pair(src_rows, key)
    cols = [min(((x - dx) * den) // num, sw - 1) for x in range(xs, xe)]
    for y in range(ys, ye):
        src = src_rows[min(((y - dy) * den) // num, sh - 1)]
        tex = (pair[0] if stripe_top(y, g) else pair[1]) if pair else None
        o = y * stride
        for x, c in zip(range(xs, xe), cols):
            v = src[c]
            if pair and v in pair:
                v = tex
            if v != key:
                dest[o + x] = v


# ==== The in-game MENU dropdown's strips: one mirrored column map (W9C F55, 2026-10-27) ====
# load_menu 0x402F40 cuts menu2.pcx into a title strip (139 x 6) and three row strips (139 x 18: normal / 2nd / hot);
# MEASURED on the pristine image (scratchpad w9C\f55, canvas index = file index + 10): every row strip is, by column,
#   fill 0..3 | the 0x0E2243 side line 4 (index 191) | fill 5..132 | line 133 | fill 134..137 | a brown edge column 138
# (index 233, opaque) -- the two lines 1 px wide, 4 px of fill outside each (the right one measured to the brown edge);
# the title strip carries the left line's pixel on its last row only (art).  The widget window is W = (139 g + 8) >> 4
# wide (thunk_menu_layout's hm_sc(139)).  Deployed (hm_synth_core's floor NN at (sc(18), 18) for the rows, (g, 16) for
# the title): the rows came out (139 sc18 + 9) // 18 wide -- 1-2 px short of W at g 17 / 18 / 25 (a key-9 sliver, the
# map shows through) or past it at g 20 / 22 / 30 (the brown column clipped) -- and the lines 1 | 2 px wide at 1080
# (user shot 20261027-133512: x 262 | 441-442, insets 6 | 4), 3 | 2 at 4K, the title's line pixel 1 px off the rows'.
# LAW: every MENU strip (title and rows) is laid on ONE column map W wide, zone by zone, mirrored about [0, W - b):
#   the lines K = stroke_width(g) wide; the brown edge b = K at [W - b, W); the fill i on both sides; the interior
#   M = W - b - 2 i - 2 K; i minimises the WORST deviation from vanilla x g/16 of the fill (4) and the interior (128),
#   ties to the smaller sum, then the fill nearer 4 g / 16, then the smaller i (rail_layout_zones' rule); inside each
#   zone the native columns land by mirror_nn_src; the right half is the mirror (137 - left), so both lines and both
#   fills are equal by construction.  Rows keep their vertical map (sc(18) / 18 rows, the title g / 16).  g <= 16: the
#   identity over 139 columns (vanilla's 1:1 blit; the thunks are not entered).
HUDMENU_STRIP_W = 139                 # the menu2.pcx strip width (title and rows)
HUDMENU_STRIP_FILL = 4                # native fill outside each side line
HUDMENU_STRIP_LINE_L = 4              # native left line column (the right one is 133 = 137 - 4)
HUDMENU_STRIP_INTERIOR = 128          # native fill between the lines (cols 5..132)
HUDMENU_STRIP_EDGE = 138              # the brown right-edge column


def menu_strip_dest_w(g: int) -> int:
    """W: the MENU window / every strip's dest width, hm_sc(139) = (139 g + 8) >> 4.  g <= 16: 139."""
    return HUDMENU_STRIP_W if g <= NATIVE_G else (HUDMENU_STRIP_W * g + 8) >> 4


def menu_strip_zones(g: int) -> Tuple[int, int, int, int, int]:
    """(W, i, K, M, b): the MENU strip column layout (see the block comment).  g <= 16: (139, 4, 1, 128, 1)."""
    if g <= NATIVE_G:
        return HUDMENU_STRIP_W, HUDMENU_STRIP_FILL, 1, HUDMENU_STRIP_INTERIOR, 1
    w = menu_strip_dest_w(g)
    k = stroke_width(g)
    b = k
    best = None
    i = 0
    while True:
        i += 1
        m = w - b - 2 * i - 2 * k
        if m <= 0:
            break
        d_fill, d_int = abs(16 * i - HUDMENU_STRIP_FILL * g), abs(16 * m - HUDMENU_STRIP_INTERIOR * g)
        key = (max(d_fill, d_int), d_fill + d_int, d_fill, i)
        if best is None or key < best[0]:
            best = (key, i, m)
    assert best is not None
    return w, best[1], k, best[2], b


def menu_strip_col_map(g: int) -> List[int]:
    """Dest column j (0 <= j < W) -> the native strip column it shows (the same map for the title and every row).
    g <= 16: the identity."""
    if g <= NATIVE_G:
        return list(range(HUDMENU_STRIP_W))
    w, i, k, m, b = menu_strip_zones(g)
    left = ([mirror_nn_src(x, HUDMENU_STRIP_FILL, i) for x in range(i)] + [HUDMENU_STRIP_LINE_L] * k
            + [HUDMENU_STRIP_LINE_L + 1 + mirror_nn_src(x, HUDMENU_STRIP_INTERIOR, m) for x in range(m)])
    r = w - b
    out = [left[j] if j <= r - 1 - j else HUDMENU_STRIP_EDGE - 1 - left[r - 1 - j] for j in range(r)]
    return out + [HUDMENU_STRIP_EDGE] * b


def menu_strip_synth(dest: bytearray, stride: int, buf_w: int, buf_h: int, src_rows, key: int, dx: int, dy: int,
                     num: int, den: int, g: int) -> None:
    """t_mc_synth: strip_synth for a MENU strip (a 139-wide sprite into the MENU buffer 0x938520) with the dest width
    menu_strip_dest_w and the columns menu_strip_col_map in place of the floor NN; rows, the stripe remap of the pair
    and the key skip exactly strip_synth's."""
    if g <= NATIVE_G:
        return
    sh, sw = len(src_rows), len(src_rows[0])
    if sw != HUDMENU_STRIP_W or den <= 0:
        return
    w = menu_strip_dest_w(g)
    dh = strip_synth_dims(sw, sh, num, den)[1]
    xs, ys = max(dx, 0), max(dy, 0)
    xe, ye = min(dx + w, buf_w), min(dy + dh, buf_h)
    if xe <= xs or ye <= ys:
        return
    pair = strip_synth_pair(src_rows, key)
    cmap = menu_strip_col_map(g)
    cols = [cmap[x - dx] for x in range(xs, xe)]
    for y in range(ys, ye):
        src = src_rows[min(((y - dy) * den) // num, sh - 1)]
        tex = (pair[0] if stripe_top(y, g) else pair[1]) if pair else None
        o = y * stride
        for x, c in zip(range(xs, xe), cols):
            v = src[c]
            if pair and v in pair:
                v = tex
            if v != key:
                dest[o + x] = v


def se_tile_rows(pair, g: int, w: int = SE_TILE_W) -> List[bytes]:
    """thunk_se_tiles' slider bar tile for a (top, mate) face pair: w x se_tile_height(g) (= 2P) rows, row y the top
    on stripe_top(y, g), else the mate (Buffer_tile's absolute anchoring keeps the dest-row phase)."""
    a, b = pair
    return [bytes([a if stripe_top(y, g) else b]) * w for y in range(se_tile_height(g))]


# ==== Type-1 popups: the dialog -> button-row span, the title band, the option-row frame (W1A, 2026-10-24) ====
# Every vanilla value below was read off the pristine bytes / a pristine render (1024x768 GOVOPTIONS, flat and
# ornate, and Go To; work/tests/test_scaling_type1_popup_gaps.py renders them on the real image).

POPUP_PAD_Y_SRC = 4                  # [+0x21C4]: Popup_calculate_dimensions' vertical pad source (vanilla [+0x30E4] = 6)
POPUP_FLAG_PAD_UNSCALED = 1 << 10    # [+0x30A8] bit 10: BasePop_calculate_dimensions' raw-pad branch 0x603979
DIPLO_TALK_ANCHOR = 0x733990         # [+0xA14] of a DiploTalkWin-anchored popup (t_dp_itemrect's anchored arm)
OPTION_ROW_TRIMMED_TYPE = 16         # the dialog type t_dp_itemrect hands a trimmed rect (t16_item_draw_rect)
POPUP_TITLE_BAND_TOP = 4             # the title band's half-open rows in the window: [frame_t + 4, frame_t + 28)
POPUP_TITLE_BAND_BOTTOM = 28         # (0x40601F..0x406033: +3 +1 and +3 +0x1A -1; pristine rows 4..27 painted)


def popup_pad_y(src: int, g: int) -> int:
    """[+0x30E4] on BasePop_calculate_dimensions' scaled-pad branch (0x60394F..0x603971: W > 1023, [+0x30A8] & 0x400
    clear, no anchor window): vanilla 3 * src / 2 (6), x g/16 applied after it (the `call 0xA0C250` @0x603969).  The
    same dword is the button row's horizontal gap (0x602CA4 / 0x602FA5 / 0x603FEB / 0x604037, t_btnrow_init), so it
    stays as it is; only the box-height use of the PAIR changes (popup_box_h_btn_pad)."""
    return popup_scale_floor((3 * src) >> 1, g)


def popup_dialog_btn_span(src: int, g: int) -> int:
    """LAW (fix 25a) -- the vertical span a popup reserves between its dialog element (a type-1 checkbox list, a type-2
    list, a field) and its button row when NO body text sits above the dialog ([+0x30D4] == 0).

    Vanilla, BasePop_calculate_dimensions 0x6041E6..0x60422A: box_h = header + 2 pad_x + max(body, art) + dialog
    + [+0x30E4] (dialog != 0, @0x60420A) + [+0x30E4] (btn_h != 0, @0x60421C) + btn_h + footer; BasePop_exec_3 puts
    the dialog at the content top (0x602B50: + [+0x30E4] only when [+0x30D4] != 0; Popup_on_draw_background 0x40613B
    makes the same test) and the row at the BOTTOM (0x602C1B: btn_y = box_h - footer - pad_x - btn_h).  So with no
    body text BOTH pads lie between the dialog and the row: ONE vanilla span 2 * 6 = 12 (pristine 1024x768
    GOVOPTIONS: ring bottom row 458, row top 471 -> 12 clear rows).  Scaled pad by pad it was 2 * fl(6g/16), up to
    1.75 px short of 12 x g/16 (g = 21 / 29 / 37: 14 / 20 / 26 vs 15.75 / 21.75 / 27.75).  One magnitude is scaled
    once: fl(2 v g/16), v = 3 * src / 2.  With body text the two pads are separate gaps (body -> dialog, dialog ->
    row) and each keeps popup_pad_y."""
    return popup_scale_floor(2 * ((3 * src) >> 1), g)


def popup_box_h_btn_pad(pad_y: int, src: int, body_h: int, dialog_h: int, flags: int, g: int) -> int:
    """LAW (fix 25a) -- what the SECOND pad add (0x60421C, the btn_h != 0 branch) contributes to box_h; t_btn_vgap is
    its port (ecx in place of `mov ecx, [esi+0x30E4]`).  g > 16, no body text, a dialog (so the first add @0x60420A
    ran) and the scaled-pad branch: popup_dialog_btn_span - pad_y, so the pair sums to the span.  Otherwise pad_y
    (vanilla, and every split / single-pad layout; the raw-pad branch [+0x30A8] & 0x400 keeps the engine's raw pad).
    The site is on the no-anchor path only ([+0xA14] == 0: 0x60418E sends the anchored box to 0x604268).  The row is
    bottom-anchored on box_h, so the remainder (0 or 1 px) lands between the dialog and the buttons; nothing above the
    dialog, the margin under the row and [+0x30E4] itself move."""
    if g <= NATIVE_G or body_h != 0 or dialog_h == 0 or flags & POPUP_FLAG_PAD_UNSCALED:
        return pad_y
    return popup_dialog_btn_span(src, g) - pad_y


def popup_title_band_rows(frame_t: int, g: int) -> Tuple[int, int]:
    """LAW (fix 25b) -- the half-open rows [t, b) of a FLAT / SLIDE popup's title band (the outer d5a0 box; the inner
    d618 box sits fl(3g/16) inside it on every side): t = frame_t + fl(4g/16), b = frame_t + fl(28g/16), each edge one
    floor of its vanilla position (thunk_title_height v2).  v1 built b = t + fl(24g/16) -- two floors -- and lost a row
    at every g = 3 mod 4 (19, 23, 27, 31, 35, 39: b 32 vs 28 x 19/16 = 33.25), which the band map's inclusive bottom
    row hid until title_band_draw_rect took it away.  The ornate (2/6) band is ornate_title_rect's (b = fl(37g/16):
    thunk_pf_title_stash's ornate arm overwrites this rect).  Identity at g = 16: [frame_t + 4, frame_t + 28)."""
    return frame_t + popup_scale_floor(POPUP_TITLE_BAND_TOP, g), frame_t + popup_scale_floor(POPUP_TITLE_BAND_BOTTOM, g)



def title_band_draw_rect(l: int, t: int, r: int, b: int, g: int) -> Tuple[int, int, int, int]:
    """LAW (fix 25b) -- the rect the title band's two box draws hand thunk_box_thick_flat: the outer d5a0 @0x406048
    (thunk_pf_title_stash's tail) and the inner d618 @0x406078 (thunk_inner_margin's tail), both through t_band_bdraw,
    which passes a stack COPY (the engine's rect stays half-open for the inner inset and the title text).

    The engine's band rect is HALF-OPEN (vanilla Buffer_box_sprite paints rows t..b-1: pristine flat rows 4..27, ornate
    13..36); at g > 16 the band map paints rows t..b INCLUSIVE, so both boxes' bottom strokes sat one row low in every
    family (4K flat outer bottom rows 69-70 where vanilla x 2.5 is 67.5..70 -> 68-69; ornate 91-92 for 90-91) and the
    band -> ring clearance was up to 1.44 px under vanilla x g/16 (g = 17 / 23 / 33 / 39 ornate, 28 flat).  The far
    edge b comes in by one (bandmap_rect_from_halfopen's b) on both boxes, so the outer -> inner channel stays
    fl(3g/16) - K at the top and the bottom.  r is not this law's: the in-game rail path's R is already the drawn
    column (popup_title_band_right), the ornate band's is ornate_title_rect's ORNATE_HALF_OPEN; the main-menu path's is
    title_band_hmargin_lr's (F36: thunk_title_hmargin v2).  Identity at g <= 16."""
    if g <= NATIVE_G:
        return (l, t, r, b)
    return (l, t, r, b - 1)


def title_band_hmargin_lr(frame_l: int, frame_r: int, family: int, g: int) -> Tuple[int, int]:
    """LAW (F36, thunk_title_hmargin v2) -- the title band's (L, R) as the band draw (0x406048) receives it on the
    "+3" path of Popup_on_draw_background (0x40600A: the console hidden -- every main-menu popup -- or a non-rail
    family), from the frame rect [frame_l, frame_r) the band block starts from ([ebp-0x14] / [ebp-0xc]; `family` =
    [ebp-4], [+0x30ac] / 10000).

    Vanilla (half-open draws): L = frame_l + 3 + 1, R = frame_r - 3 - 1 (0x406015 / 0x406027 / 0x406031): the band's
    strokes are 3 px clear of the frame's on both sides (pristine Customize Game Rules 1024x768: 3 | 3).  v1 scaled
    the inset to fl(4g/16) on both sides, but at g > 16 the flat band map paints [L, R] INCLUSIVE, so the right
    stroke landed one column outside its mirror: frame -> band 8 | 7 at 4K, 4 | 3 at 1080 / 1600x1200, 3 | 2 at
    1600x900.  v2 takes R in by one (bandmap_rect_from_halfopen's r), the same fold the in-game rail path makes
    (popup_title_band_right) -- both channels fl(4g/16) - K.  Every g_title_right consumer reached from this path
    (the d528 text box, the quit-family / UnionRect ring, the type-4 field ring, the untitled stash) moves with
    it, so each keeps mirroring its g_title_left twin.

    The ORNATE families (2 / 6, which also take this path in game) pass: their band is ornate_title_rect's
    (thunk_pf_title_stash's ornate arm already pulls R in by ORNATE_HALF_OPEN).  Identity at g <= 16."""
    ins = popup_scale_floor(POPUP_TITLE_BAND_INSET, g)
    r = frame_r - ins
    if g > NATIVE_G and family not in (2, 6):
        r -= 1
    return frame_l + ins, r


def option_row_frame_site_rect(l: int, t: int, r: int, b: int, g: int, dialog_type: int,
                               anchored: bool = False) -> Tuple[int, int, int, int]:
    """LAW (F35) -- the rect the per-option row frame draw at 0x405BF6 (FUN_00405b20 -> t_rowbox_trim -> t_rowbox_ph
    -> thunk_rowbox_guard -> thunk_box_thick_hollow_flat) hands the band map, from the native fn's own LOCAL copy of
    the row rect ([ebp-0x14]; nothing reads it after the draw).

    Vanilla paints the bar half-open: pristine 1024x768 GOVOPTIONS (type 1) rows [39, 58) of the 22-row cell [38, 60):
    1 background row above, 2 below (distribute(3, 2) = [1, 2]), 3 between bars; Go To (type 2) [19, 35) of [19, 38).
    The band map paints the inclusive footprint, so every bar was one row taller than its rect: the visible gap between
    rows 1 short of fl(3g/16) (4K 6 vs 7) and the type-1 ring-to-bar split reversed against vanilla's smaller-first
    (1080 5/4, 1600x1200 4/3, 4K 8/8).  bandmap_rect_from_halfopen on the far edges restores vanilla's footprint
    (4K 8/9, 1080 5/5, 1600x1200 4/4; gap fl(3g/16)).  R - 1 moves no pixel where the bar reaches the list window's
    right edge (types 1 and 2 hand R = the window width, which thunk_rowbox_guard / hollow_flat clamp to W - 1); it
    keeps the footprint lawful where a bar stops short of it.

    Rows t_dp_itemrect already trimmed (t16_item_draw_rect: dialog type 16, every DiploTalkWin-anchored row) pass
    through, so composed with it every row's frame is bandmap_rect_from_halfopen of the engine's rect exactly once.
    The trim is at the frame draw, not at the fn's input: the type-1 checkbox centres in the UNTRIMMED rect (0x405BB0:
    y = t + (b - t - h) / 2), vanilla's relation to the half-open bar.  Identity at g <= 16."""
    if g <= NATIVE_G or anchored or dialog_type == OPTION_ROW_TRIMMED_TYPE:
        return (l, t, r, b)
    return bandmap_rect_from_halfopen(l, t, r, b, g)

POPUP_HEADER_TITLED = 0x26            # [+0x21B8] header reserve of a titled popup (Popup_calculate_dimensions)
POPUP_HEADER_ORNATE_EXTRA = 9         # + this for the ornate types 2 / 6 (@0x404E17)


def popup_title_ring_clear(g: int, ornate: bool = False) -> int:
    """LAW (measured, fix 25b) -- the clear rows between a titled type-1 popup's title band and its list ring (no body
    text, no art): ring top - band end.  It is a COMPOSITION of three lawful positions, each one floor of its own
    vanilla position, and nothing else moves it:
      * the list top = the content top fl(38g/16) flat / fl(47g/16) ornate ([+0x30E8] header reserve, pad_x 0 for a
        type-1 list; real-image renders: exact at every g in 16..40);
      * the ring top = list top - fl(3g/16) (itemlist_ring_hug: T == B == L == R == fl(3g/16), the user's "hug the
        list" decision);
      * the band end = popup_title_band_rows' b fl(28g/16) flat / ornate_title_rect's fl(37g/16).
    Vanilla 38 - 3 - 28 = 7 (ornate 47 - 3 - 37).  The span lands in [fl(7g/16), fl(7g/16) + 2]: + 2 only at g = 25
    (both families: 12 vs 10.94) and g = 31 ornate (15 vs 13.56), where fl(3g/16) loses more than the header's floor.
    Bounding it to fl(7g/16) + 1 there needs the ring top on fl(35g/16) / fl(44g/16) -- a top inset of fl(3g/16) + 1
    against fl(3g/16) on the other three sides (breaks the hug) -- or the content top off its own lawful floor (every
    titled popup's header reserve); neither is taken.  Identity at g = 16: 7."""
    header = POPUP_HEADER_TITLED + (POPUP_HEADER_ORNATE_EXTRA if ornate else 0)
    band_end = ornate_title_rect(0, 0, 0, g)[3] if ornate and g > NATIVE_G else (
        popup_title_band_rows(0, g)[1] if not ornate else 37)
    return popup_scale_floor(header, g) - popup_pad(3, g) - band_end

