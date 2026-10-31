---
name: project-smac-snapped-border
description: 9-slice frame corners are CHAMFERED -- a flat-strip redraw (snapped border) makes them SQUARE; bevel-preserving thicken must go through the sprite render (GROW) or scale corner sprites. d690 outermost frame loses its bevel at scale (item D5).
type: project
---

The faction-quote frame strokes rendered ~1px thicker on the BOTTOM at g=40 (symmetric at g=25). The
discriminator trace (hook_faction_nn_roundtrip.js @g=40+g=25) proved root cause = **H2, the GDI StretchBlt
phase**, NOT H1 (the rect-math double-floor in thunk_box_thick_hollow/thunk_frame_enlarge): the small src
stroke is symmetric 1px, but the x2.5 StretchBlt upscale of a 1px line outputs 2px/3px. The H1 round-trip
loss was a constant 1px at BOTH resolutions, so it is NOT the cause (asymmetry is g=40-only).

KEY TRUTH (verified in code via a phase sweep + game-dev literature): nearest-neighbour scaling is fully
DETERMINISTIC, but you CANNOT NN-scale a 1px line by a non-integer factor (x2.5) to equal-thickness edges —
no sampling phase yields 2/2; it's 2/3 or 3/2. So "round-to-nearest in the enlarge" and any phase tweak are
dead ends. The correct deterministic, resolution-independent fix is to draw the border at a SNAPPED INTEGER
thickness drawn directly (the 9-slice "scale border as integer, stretch only the centre" approach), NEVER to
NN-magnify the 1px line.

ATTEMPTED then REVERTED for the OUTER d5a0 (A4-A, 2026-06-14): thunk_d5a0_snapped (pcave2 0x980) drew the frame
as 4 plain Buffer_fill_3 strips (snapped thickness T=(g+7)>>4). It DID make the stroke symmetric -- BUT a plain
rectangle has SQUARE corners, so it DESTROYED the box-sprite's CHAMFERED (beveled) corner. The maintainer flagged the
lost bevel as a serious regression. thunk_d5a0_snapped + g_strip_rect were DELETED and thunk_content_frame's tail
repointed back to thunk_d5a0_center (sprite-based GROW path -> magnifies the whole frame incl. corners -> chamfer
preserved). Back to confirmed MD5 8d03ddf7. The 1px bottom-stroke asymmetry stays DEFERRED (lesser evil).

HARD LESSON: a flat-strip / non-sprite frame redraw CANNOT reproduce a chamfered 9-slice corner. Any
bevel-preserving stroke thicken MUST go through the sprite render (GROW = render small + StretchBlt magnify, which
scales corners too) OR explicitly scale the corner sprites. Do NOT re-attempt the snapped-strip approach on any
frame that has a chamfer (d5a0, d528, d690 all do).

INVERSE PROBLEM (item D5, (a private note)) -- **SOLVED + CONFIRMED 2026-06-14, MD5 897fdc84, @4K + non-4K**:
the OUTERMOST modal frame d690 (popup window backdrop, generic-branch draw at Popup_on_draw_background 0x405f77) kept
native 1:1 corner sprites while the popup auto-sizes big (40px fonts) -> ~6px chamfer on a ~1705px frame read SQUARE.
FIX = group `popup_outer_backdrop_scale`: redirect 0x405f77 -> the EXISTING thunk_box_thick_hollow_flat **without
nulling the fill**. It renders d690 small (key-9 prefill, fill KEPT -> opaque interior) then keyed x(g/16) StretchBlt
magnify IN PLACE (Delta=0, same footprint) -> 1px border + 1px chamfer scale to ~(g/16)px. Covers generic popups +
faction quote box; faction MAIN modal (FUN_00429300 @0x429a5b) + 0x48968b dialog left native (deferred).

ATTEMPT #1 REVERTED 2026-06-14 drew WHITE HATCH STRIPS, and the post-mortem here BLAMED "textured edges banding under
StretchBlt" -- **that was WRONG**. hook_d690_sprites.js -> frida_d690_sprites.log proved d690 is PURE FLAT COLOR: 6x6
corners, border line = palette idx 26 (1px), interior = fill_param 7, 1px transparent-key(9) corner chamfer, and EVERY
edge `uniform-along-tile` (ZERO texture). The real cause of the strips: attempt #1 NULLED the fill (+0x20) -> the
magnified interior became transparent (key 9) and uninitialized scratch/background showed through as hatch. KEEPING the
fill eliminates it. CORRECTED LESSON: the thin-frame GROW/magnify path (thunk_box_thick_hollow_flat -> thunk_frame_
enlarge) IS fine for the big d690 backdrop too -- the only requirement is to keep its fill so the interior stays opaque.
RULE still holds: bevel-preserving thicken goes through the sprite render (here the whole flat backdrop magnifies, so
corners scale too), NEVER a flat-strip redraw. See skill scaling-frames.
