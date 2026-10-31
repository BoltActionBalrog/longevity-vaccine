---
name: project-smac-frame9-enlarge
description: frame9 v3 band-map enlarge — prototype VERIFIED all-res 2026-07-09 (runtime only, NOT baked); the reusable scaling laws it produced + bake checklist
type: project
---

# frame9 v3: 9-slice band-map enlarge (hook_frame9.js)

Replaces the four frame renderers' UNIFORM NN enlarge with a per-axis 9-slice map; the engine still
renders the scratch (Buffer_box_sprite, same prefill/size). Fixes the 2-vs-3px opposite-edge stroke
wobble, the corner-bevel weight, the fractional-g dither banding, and the faction list gap.

**STATUS 2026-07-09: CLOSED. Exe = 3843e2a0 = VERIFIED RELEASE LOCK** (user "everything looks good"
in-game 4K/1920/1600/1024; stroke census 294 frames / 0 violations; CHANGELOG'd; patched_md5 re-locked,
full suite 5562 passed). Chain: 75cae700 -> 5e700519 (band map) -> 63b7ada3 (exact fill) -> 469118f6
(hollow Delta zeroed) -> 3843e2a0 (pf_frame_align D2=ps3). pcave2 grown 0x7000->0xB000.

**FOUR fixes, and the last three were each UNMASKED by the one before.** Order matters:
band map -> exact fill exposed the vestigial Delta -> zeroing Delta exposed its COMPENSATION in
thunk_pf_frame_align. Every one of them was an additive constant vanilla never had.
STILL WATCH (audited, NOT changed — user's visual pass found nothing): `thunk_popup_fieldpads`'s
`T = g_band_bottom + 2*(p3+Delta)` and `thunk_popup_artalign`'s `-Delta` term both assume the FIELD
frame grows by Delta. Measure before touching. `thunk_box_thick` KEEPS its Delta (title pair applies it
to BOTH frames -> channel already faithful); compensations referencing the TITLE's grow stay valid.

**VESTIGIAL DELTA (v3, 469118f6).** `D = (g-16)>>3` is our own OUTWARD grow in the renderers, added so a
thickened stroke would not eat the interior under the old NN blit. **D is 0 in vanilla (g=16) — an
additive constant that violates `patched = vanilla x g/16`.** The band map puts a K-wide stroke AT the
rect edge by construction, so D is vestigial. It also broke concentric PAIRS: outer = `hollow` (D),
inner = `hollow_flat` (D=0) => only the outer grew and the channel gained D. Measured @4K: title pair
(box_thick+box_thick, both D) channel 5px = faithful (vanilla 2 x 2.5); text-field pair 8px = 5 + D(3).
The old under-fill masked part of D; exact fill exposed all of it. Fix: `thunk_box_thick_hollow`'s
`83 E8 10 C1 E8 03 8B D8` -> `33 DB 90 90 90 90 90 90` (same 8 bytes, = hollow_flat's prologue).
`thunk_box_thick` KEEPS D (title pair applies it to BOTH frames -> already faithful; tied to the
art-flush signature, [[project-smac-popup-chrome]]). D==0 for g<24 -> only 1600 (D=1) and 4K (D=3) move.
Channels now inset-K = 2/3/3/5 at g=16/22/25/40, each == faithful half_down(2g,16).
**LESSON: an exact-fill fix can UNMASK a second additive-constant bug that under-filling was hiding.**

**EXACT FILL (v2, 63b7ada3) — the first bake's biggest omission.** thunk_frame_enlarge sizes the blit
`dstW = srcW*g/16` where `srcW = span*16/g` is already floored: a DOUBLE FLOOR that under-fills the
rect by up to 2px. At g=16 dst == span, so exact fill IS vanilla. The frame9 prototype had it by
construction ("DW is the rect span exactly"); the first bake replaced only the blit and silently
dropped it. Symptom: Quit modal @1920 outer rect 637x42 drawn 635x39, inner 629x34 drawn 627x33 ->
top channel 3px, bottom 1px, though the rects are perfectly concentric (4/4/4/4). Fix: fe_bandmap
also stashes the span (g_bm_dstw @0xA208 / g_bm_dsth @0xA20C) from the renderer's live frame
([ebp+8]=rect, D = L - X); bandmap_blit consumes it, overrides its own dstW/dstH args in place
(grow-only, cap 4px) and refreshes g_fe_w/h so fe_pair_remap covers the whole rect. Generalises
g_fc_exact to every frame. **LESSON: when porting a prototype, port its INVARIANTS, not just its
code — "exact fill by construction" was a property of the design, not a line of the blit.**

Bake = 2 thunks, no byte-length change at any existing site:
- `thunk_fe_bandmap` @0xA16210 (57B): the 4 renderers' single `E8` to thunk_frame_enlarge is
  retargeted here; their frame is live and each keeps params at [ebp-8], so it stashes params[0]'s
  canvas_w/h (+0x18/+0x1c) into g_band_nx/ny, then push;ret into the UNCHANGED enlarge (epilogue
  preserved byte-for-byte).
- `thunk_bandmap_blit` @0xA16250 (969B): drop-in for thunk_keyed_stretch_blit (same cdecl, RET 0x2C);
  enlarge's NN path calls it. Helpers bm_axis/bm_cum. Consumes g_band_nx/ny; tail-jmps to the shipped
  blit on any unhandled geometry. `thunk_deco_keyed_scaled` (the OTHER keyed_stretch_blit caller)
  deliberately untouched.
Verified baked: enlarge tail = call bilinear / call 0xa16250 / call fe_pair_remap; all 4 renderers
call 0xa16210.

**MEASURED CORRECTION (this is the real defect shape):** Buffer_copy_3 is a CENTRE-ALIGNED NN
stretch -> symmetric at every ratio EXCEPT a half-integer one. g=40 == 2.5 exactly, so the wobble is
**4K-ONLY**: 34/42 frames measured 2px near / 3px far. At g=22 and g=25 all 84 frames were ALREADY
symmetric. An earlier `floor(j*src/dst)` model predicted wobble everywhere and was WRONG (it agreed
with two screenshots — corroboration, not proof). Post-bake acceptance: 4K 34->0, and 1920/1600 must
STAY 0. Some 4K frames shipped 3/3 and now render 2/2 (K=2, half-down) — deliberate, user-approved.

- Replaced entries (all thiscall(dest)(rect,params) RET 8):
  box_thick 0x668E00 (D=(g-16)>>3, prefill 0x41, key -1) | hollow 0xA0C000 (D, 09, 9)
  hollow_flat 0xA0C140 (0, 09, 9) | intK 0xA12C00 (0, 09, 9)
- Band map: `cum(v)=halfDown(v*DW, srcN)`; B=cum(n) from DW/srcN; near band = fwd map, far band =
  mirrored `(srcN-1)-fwd[DW-1-j]` (both anchored to their OWN outer edge => opposite strokes
  quantize identically); middle = the engine's own NN phase `floor(j*srcN/DW)`, clamped.
  n (band depth) = corner sprite CANVAS dims per axis (6x6 simple; 61x44 ornate picker; non-square OK).
  DW = rect span exactly => exact fill structural => g_fc_exact unnecessary.
- Emit via clip-aware Buffer_hline_2/put_pixel RLE, key-skipped. NEVER raw +0x54 writes.

## The five laws (all verified by python sweep over g in [16,40] BEFORE running in-game)

1. **CHROME-CELL LAW.** Native band cells 0 (stroke) and 1 (45-deg bevel diagonal) BOTH scale to K.
   The remainder B-2K spreads over cells 2..n-1 (interior fill — visually inert). Plain cum() gave
   widths 2,1,2,1.. at g=25 (bevel half the stroke -> "corner too small") and 1,2,.. at g=22
   ("too large"). Same complaint, both signs.
2. **K FROM THE LEVER, NOT THE ELEMENT.** stroke K = halfDown(g,16), never each frame's own
   DW/srcN. They differ only at exact-half ratios — but there halfDown tips 2->3 AND becomes
   span-dependent (spans divisible by 5 stay 2) => per-element stroke inconsistency, the exact
   disease this workstream cures. B stays on DW/srcN so bands meet the middle phase seamlessly.
3. **EPILOGUE LAW.** Anything replacing a renderer upstream of thunk_frame_enlarge MUST replicate
   its tail: stash g_fe_dst/x/y (0xA0EFA0/A4/A8), g_fe_w/h (0xA0EFAC/B0, h POSITIVE), g_fe_src
   (0xA0EFC4) = the scratch, then CALL thunk_fe_pair_remap @0xA10000 (no args); and consume
   g_fc_exact @0xA0E554 (write 0). fe_pair_remap is what keeps 1px dither interiors clean at
   fractional g (P=(g+4)>>3 stripe law). Raw NN of a period-2 dither BEATS (runs 2/1 drifting to
   1/2) — invisible at 4K (2.5 => regular 2/3), banded at g=22/25. Skipping it = HUD/title banding.
4. **REMAINDER-DISTRIBUTION LAW (the general one).** `n * floor(scale*v)` != `floor(n*scale*v)`.
   Any repeated stride at scale accumulates the per-cell floor. Faction list: pitch floors
   19*1.5625=29.69 -> 29, losing 4.8px over 7 rows, so the last row stopped ~5px short of the ring
   ("too much gap below Peacekeepers"). Cure = position cell i at `cum(i)=halfDown(i*total,n)` and
   take differences — the SAME primitive as the band widths.
5. **CHROME FOLLOWS CONTENT.** Derive a chrome rect from the quantities the CONTENT uses, never by
   independently scaling the chrome rect. Ring bottom = rowsTop + 7*pitch (not su*(B+3)). This makes
   the g=16 identity ALGEBRAIC (vanilla: 134 + 7*19 = 267 = nativeB+3) — a *proof* of the native
   no-op, not a test of it. This is the defensible, narrow form of the "anchors/margins" idea.

## Faction picker field addressing (reusable)

- FactionPickWin GLOBAL object @0x822718 (`mov ecx,0x822718` @0x58a755 before the exec call);
  its embedded Buffer is at +0x444 (= 0x822b5c, the dest ptr seen in frame draws).
- NATIVE list rect L/T/R/B @ +0x86ac/b0/b4/b8 = 336/134/762/264 (NOT scaled in place — no writeback).
- List-ring LOCAL rect built @0x489741 = (L-3, T-3, R+21, B+3); framecover then scales the whole rect.
- **Row pitch is NOT at W+0x8704.** Virtual inheritance: `mov eax,[ebx]` (ebx=W+0x86bc = Dialog VPTR);
  `mov ecx,[eax+8]` (VIRTUAL-BASE ADJUSTOR); `mov [ecx+esi+0x8704]`. So
  `pitchAddr = W + [[W+0x86bc]+8] + 0x8704`, and rowgap = same base + 0x8700. Reading +0x8704 raw
  yields a pointer. Generalize: `vbase_field(W, 0x86bc, off) = W + [[W+0x86bc]+8] + off`.

## OPEN

- **BAKE** (nothing is in the exe): express the axis map in asm inside thunk_frame_enlarge or a new
  cave (pcave2 occupied past 0x687D — MEASURE, see [[feedback-cave-ledger-lengths]]); retire the
  g_fc_exact setters + thunk_dfstep1_dispatch faction gate; patches.yaml + terranx.h + CHANGELOG +
  test_apply_md5; re-verify 4K + 1920 + 1600 + 1024 (byte-identical at g=16).
- **Row pitch still floors.** The ring now follows the rows, so the gap is gone, but the 7 rows sit
  ~5px tight at 1600. Real fix = law 4 in FactionPickWin_build.pitch/droppos (group
  faction_pickwin_content). Deliberate, separate change.
- Corner band B is 1px smaller than the shipped NN at non-4K (halfDown vs ceil). Accepted as correct
  after the chrome-cell fix; revisit only if a user complains.

See [[feedback-dither-no-resample-on-upscale]], [[feedback-frida-attach-branch-target]] (this
workstream added the Interceptor.replace recurrence), [[feedback-proportionate-scaling]].
