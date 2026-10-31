---
name: scaling-frames
description: Use when scaling, thickening, or fixing the box/margins/strokes of a 9-slice popup frame or modal background in the SMACX patcher, including banding/dither artifacts in a modal's tiled fill.
---

# Scaling 9-slice frames & modal boxes in the SMACX UI

Popup frames are `Buffer_box_sprite(dest, RECT*, BoxSpriteParams*)` (0x5e2dd3) 9-slice draws:
corners blit 1:1, edges tile at **native** cross-thickness, optional interior fill. So at hi-res
everything else is ~2.5× but the **stroke lines stay hairline**. Three separable problems, three
levers — don't conflate them.

## ⚠ READ FIRST — three laws that are non-obvious and get silently regressed

The arithmetic below lives in `work\scripts\scaling_laws.py` and is swept by
`work\tests\test_scaling_laws.py` (5,200+ assertions, no game launch, <25s).
**That module is the source of truth**; the Frida hooks and cave thunks are ports of it.
Changing frame arithmetic without running that sweep is how the 2-vs-3px stroke wobble,
the corner-bevel weight, and the fractional-`g` banding each came back. See
[[project-smac-frame9-enlarge]] and skill **scaling-layout**.

1. **Never uniformly NN-enlarge an already-rendered frame.** One ratio cannot serve both
   the corner band (must scale faithfully) and the 1px stroke (must land on exactly `K`);
   NN dumps the remainder on whichever *opposite* edge the phase hits → 2px one side, 3px
   the other. Use the per-axis 9-slice band map (`scaling_laws.axis_map`): near band and
   far band carry identical widths, each anchored to its **own outer edge**; the middle
   keeps the engine's own NN phase `floor(j*src/dst)`. `dst` = the rect span exactly, so
   the fill is exact **by construction** and `g_fc_exact` becomes unnecessary.

2. **Stroke `K = half_down(g,16)` comes from the LEVER, not the frame's own dst/src ratio,
   and cells 0 AND 1 of the corner band both get `K`.** Cell 1 is the 45° bevel diagonal —
   it is chrome, exactly like the stroke. Pinning only cell 0 gives the bevel half the
   stroke's weight at g=25 ("corners too small at 1600") and double at g=22 ("too large at
   1920"): one bug, opposite signs. The remainder spreads over the inert interior cells.

3. **EPILOGUE LAW — anything replacing a renderer upstream of `thunk_frame_enlarge` must
   replicate its tail.** That tail is what keeps 1px dither interiors clean:
   stash `g_fe_dst/x/y` (0xA0EFA0/A4/A8), `g_fe_w/h` (0xA0EFAC/B0, **h POSITIVE**),
   `g_fe_src` (0xA0EFC4, the scratch buffer) → `CALL thunk_fe_pair_remap` (0xA10000, no
   args) → consume `g_fc_exact` (0xA0E554, write 0). Skip it and every 1px dither field
   beats under NN (runs 2/1 drifting to 1/2) — invisible at 4K where the ratio is a clean
   2.5, **banded at g=22/25**. That was the "HUD and Planetfall title box are banded"
   report. The band depth `n` = the corner sprite's **canvas** dims per axis (6×6 simple,
   61×44 for the picker's ornate frame; non-square is normal).

## 0. Identify the ACTUAL draw first (Frida frame-map)

Before patching anything, trace the frame draws: run an observer that logs every
`Buffer_box_sprite` (sprite name by params-VA, rect, return addr, **dest-buffer size**) plus
`GraphicWin_fill`/`fill_3` (rect, color), open the dialog, quit, read the log.
`hook_fieldrect.js` is the current example of that observer (attach at the renderer ENTRIES,
never at the baked detour site 0x5E2DD3; `work\scripts\PROBES.md` lists the others):
`work\run-frida-at-res.bat hook_fieldrect.js <W> <H>`. This stops guessing:
- A draw site can be **dead** for your popup. e.g. d528 (option-block frame @0x406154) is gated on
  `[+0x30d4]!=0` which is **0 for list popups** → it never fires; the visible "frame around the
  options" is actually the OUTER-UNION d5a0 @0x406238. Patching the dead site = no visible change.
- `destbuf == rect` tells you a sprite fills its buffer (not inset) → a "too small" symptom is NOT a
  rect-sizing problem (see §3).
- Returns in `0x429xxx` / unrelated funcs are other screens behind the modal — ignore.

## 1. Thicken a stroke — render-small-then-NN-blit thunk

`call_target_redirect` the `Buffer_box_sprite` call to a cave thunk (`thunk_box_thick` /
`thunk_box_thick_hollow` / `_hollow_flat`) that: gates on hi-res (`cmp [g_popup_scale_num],0x10; jle native`),
renders the frame **small** (`(R-L)*16/g`) into a scratch `Buffer g_frame_buf`, then **enlarges it back
keyed ×(g/16)** via `thunk_frame_enlarge`. Strokes thicken 2.5×.
**Use a FLAT variant (`_flat` / `_hollow_flat`, Δ=0): the drawn frame must BE its rect.** The original
`thunk_box_thick` grows `Δ=(g-16)/8` outward — an additive constant vanilla does not have; it put every popup
title Δ too close to the border and forced a Δ compensation into ~10 downstream laws (removed 2026-09-18, law
`title_grow_delta == 0`). It survives only for the diplomacy talk title, whose rects pre-inset by +D.
Same thiscall/RET-8 contract as `Buffer_box_sprite`, so it's a drop-in for the call. Lo-res g=16 → native
draw (exact no-op). Reusable for any 9-slice frame.

**If the frame has a TILED/textured interior fill (dither, gradient), §1 bands it** — the StretchBlt
row-doubles the native-tiled fill. Don't stop at §1 there; split the render per §4.

**Do the enlarge via the bounds-safe path, NOT raw `Buffer_draw_2`.** Enlarging with
`Buffer_draw_2`'s `num>den` mode writes one row past the dest at fractional ratios (fine at 4K's 40/16,
**crashes** at 1080p's 22/16 etc.). Route it through `thunk_frame_enlarge` (StretchBlt-based), which is a
drop-in with the same `__thiscall`/RET 0x18 contract as `Buffer_draw_2`. Full rationale + the general
sprite-scaling primitive: see [[scaling-sprites]].

**`thunk_frame_enlarge` floor-quantizes its output** (`dstH = floor(smallH·g/16)` on top of
`smallH = floor(H·16/g)`), so the magnified frame is a hair SHORTER than the rect and the bottom/right
strokes render slightly inset. Harmless on a single-stroke frame; on a **double/concentric** frame it
makes the inter-stroke channel asymmetric — that's §5 (exact-fill).

### THE BLIT-KEY RULE (this is the sharp edge)

`Buffer_draw_2`'s 3rd arg is the transparency **key**:
- **opaque-fill** frame (interior pre-filled with a real index, e.g. `0x41` title band) → blit key
  **-1** (`6A FF`, copy-all). Interior copies opaque. Correct for `thunk_box_thick` (title).
- **hollow** frame (interior pre-filled with transparent key `9`, so content shows through) → blit key
  **9** (`6A 09`). Only strokes copy; the key-9 interior is **keyed out**.

**Get this wrong and you punch a transparent hole.** A hollow frame blitted copy-all (-1) writes its
key-9 interior onto the dest → see-through strips between the frame and the content (the part rows
don't cover). The symptom looks like a too-small background; it's actually the frame draw punching
through. One-byte fix: `6A FF` → `6A 09`. See [[project_smac_frame_strip_key]].

## 2. Grow the box / scale margins — the REUSABLE box lever

`BasePop_calculate_dimensions` (0x603800) **derives** the box from margin fields, so scaling the
margins grows the box AND insets the content as a unit (no element moves relative to each other):
- `box_w (+0x30bc) += [+0x21b4](right) + [+0x21b0](left)`; content origin X includes `[+0x30f0]=[+0x21b0]`.
- `box_h (+0x30c0) += [+0x21bc](bottom) + [+0x21b8](header)`.

Lever: `thunk_scale_box_margin` (pcave2 +0xE0) redirects the `BasePop_calc` **call** in
`Popup_calculate_dimensions` @0x404e93 (`ecx=esi=this`), scales `[+0x21b0]/[+0x21b4]/[+0x21bc]` by
popup_scale (`imul [g]; sar 4`), tail-jmps `BasePop_calc`. Group `popup_box_margin_scale` (skippable),
applies to **all** popups. Leave `[+0x21b8]` (header/top) alone — `thunk_scale_header` already owns it
(double-scale otherwise). Field map in `terranx.h`.

## 3. "The background is too small" — fix the DRAW, don't move elements

The user's instinct is right: don't rearrange/shrink content to hide a gap. Find what paints the field
and why it falls short. The dark modal field is the **d690 "filled" backdrop** (the only black-painter;
every `GraphicWin_fill` in the popup uses the transparent key 9). If frame-map shows d690's `rect ==
destbuf`, it already fills its buffer — the gap is NOT d690's size, it's the §1 blit-key punch. Fix the
key, not the geometry.

## 4. A dithered/textured interior FILL bands when thickened — split the render

A box-sprite whose interior fill is a **tiled texture** (e.g. the 24×24 dither tile behind the faction
leader-quote) **bands** at non-4K once you thicken it via §1. The §1 thunk tiles the fill at **native**
size then StretchBlt-enlarges the whole scratch → the dither's scanlines get NN-**row-doubled** at a
fractional ratio = irregular banding. It looks fine at 4K (≈integer 2.5×, phase-aligned) and broken
everywhere else — the classic resolution-dependent NN tell. StretchBlt (§1) can't cure it: a native-tiled
texture *must* be tiled at **device** resolution to stay clean.

**Fix — `thunk_box_thick_devfill` (split render, drop-in for the `Buffer_box_sprite` call):**
- **STEP1:** call the proven §1 thick render (`thunk_box_thick_hollow_flat`) — keep it for the **bevel**.
  You CANNOT render the border without its fill: the 9-slice edges tile `params[8]` (the fill) as a
  **mask alongside the bevel sprite**, so a border-only render exposes the raw highlight and paints the
  frame **white** (the documented "attempt #1 white-strip bug"). STEP1 gives a correct bevel + a banded
  center.
- **STEP2:** overwrite only the inset center with a clean device-res fill —
  `Buffer_box_sprite(dest, INSET_rect, scratch)` where `scratch` = a copy of `params` with the 8 border
  slices zeroed (all 9 slices are null-checked, so border-zeroing is safe). This tiles `params[8]` at
  **device** resolution across the center → clean dither, bevel untouched.

**Inset by the STROKE width, not the edge width.** The bevel is ~1–2px green stroke + ~7px fill-MASK +
clean center. Inset `N = ceil(g/16) = (g+15)>>4` (the green-stroke width only) so STEP2's clean fill also
covers the **fill-mask** band. Insetting by the full edge-sprite width (`6·g/16`) leaves that fill-mask
banded = a "banded ring inside the inner stroke."

### THE ASYMMETRIC-INSET RULE (the sharp edge here)

StretchBlt rounds the **right/bottom** strokes 1px *toward* the box edge, so a symmetric `R-N`/`B-N` clean
fill **clips their outer pixel** — right/bottom strokes come out 1px while top/left stay 2px. Inset
**top/left by N, right/bottom by N+1** (`lea edx,[ebx+1]` then `sub eax,edx` for R/B). The 1px you stop
short of reverts to STEP1's render — which is the green **stroke** there, not banded fill — so it restores
the eaten pixel without re-banding. **Verify by pixel-measuring the innermost stroke width on all four
mid-edges**; a top/left-vs-right/bottom asymmetry (2px vs 1px) is the signature, and the only reliable
read — Frida can't hook the popup redraw path (draw-buffer abort), so measure from a screenshot.

Reusable for **any** dithered/textured box-sprite modal background. Gate g≤16 → native no-op.
See [[project_smac_faction_dither_layer]]; the underlying NN edge-drop theory is [[scaling-sprites]] §"thin-line disappearance".

**§4 (devfill) re-tiles the ORIGINAL texture at device res — right when the texture is aperiodic or its
native cell reads the same at any density. For a 1px PERIODIC scanline dither that must *read like
pristine* at every g, use §7 (synthesize scaled stripes) instead** — device-res re-tiling of a 1px dither
keeps it 1px at 4K where pristine-look requires the pattern itself to scale.

## 5. Double-frame channel asymmetry — exact-fill the enlarge

The §1 render-small→enlarge path sizes its output by a **double floor** (`dstH = floor(smallH·g/16)`,
`smallH = floor(H·16/g)`), so the magnified frame is SHORTER than the rect by `H − dstH`, anchored at
the top-left → the **bottom/right strokes render inset** from the rect edge (top/left stay flush). The
shortfall is **box-height-dependent** (a function of `H mod g`).

- On a **single-stroke** frame this is a sub-perceptible ~1px bottom/right inset (nothing to compare it
  against) → leave it; §1 is fine.
- On a **double / concentric** frame (two strokes with a visible channel — e.g. the faction title's
  outer d5a0 + inner d618) the two boxes have **different heights**, so they inset by **different**
  amounts → the stroke-to-stroke **channel goes unequal top-vs-bottom**, and because it's a floor the
  direction **flips with resolution** (faction title measured: 1600×1200 bottom gap ~4px vs top ~2px;
  1920×1080 bottom ~1px vs top ~3px). Making the *rects* concentric is necessary but **NOT sufficient** —
  the render still drifts downstream of the rect.

**Fix — exact-fill the enlarge.** `thunk_frame_enlarge` (pcave2 +0x30A0, relocated from +0x2560 when the
§7b remap tail outgrew the slot) reads a flag `g_fc_exact`; when
set it OVERRIDES `dstW/dstH` with the EXACT scaled rect `W×H` (`R−L`, `B−T`, read from
`g_faction_scratch_rect` which still holds the box rect at enlarge time), then clears the flag. GDI
`StretchBlt` stretches to any size, so the frame fills the rect exactly → **all four strokes flush →
equal channel both ends at any g**, bevel preserved (no thickness change, just placement). The flag is
set by `thunk_factionwin_framecover` for its two title strokes — d5a0 (direct → `_hollow_flat`) and d618
(filled → `devfill` STEP1 → `_hollow_flat`) — and left 0 otherwise (the final list-d5a0 draw clears it,
so it never leaks to other popups).

### WHEN to route a frame through exact-fill
- **YES:** a concentric **double** frame whose inter-stroke channel must read even (title-style boxes).
- **NO (default):** single-stroke frames — keep the plain §1 enlarge; the inset is invisible and
  exact-fill would churn verified popups for no visible gain.
- **Don't blanket-enable it.** It is flag-gated precisely so unflagged callers run **byte-identical**
  (verified: the `je` skips the override). Universalizing is a real refactor, not a default flip — the
  Δ-grow thunks (`thunk_box_thick` / `_hollow`) target the GROWN footprint `(W+2Δ)×(H+2Δ)` at
  `(L−Δ,T−Δ)`, not `W×H`, and read no per-call rect, so each caller would have to pass its own exact
  dims; and you'd then owe a full re-verify of every popup at 4K+1600+1920+1024. Only do it as a
  deliberate polish pass, or when a specific frame shows a *visible* asymmetry.

**The floor-inset is RESOLUTION-INVERSE — don't compensate it with a `popup_scale` push.** The shortfall
`H − floor(floor(H·16/g)·g/16)` is **large at low g (~10px at 1600×1200) and ~0 at 4K** (4K's headroom hides
it). So a scaled-constant push (`[edi+k] += popup_scale(N)`) scales the WRONG way — it adds most where the
defect is least. On the file-dialog inner frame this crushed the 4K inner/outer right channel (the push shoved
the inner stroke into the outer). The right fix is **exact-fill**, which removes the inset at its source and is
correct at every g by construction. (An *intentional extra gap* — e.g. the inner-bottom button clearance — is a
legitimate `popup_scale(N)` push and survives because it isn't floor-compensation and has window margin to
absorb it; just don't conflate the two.) See [[feedback-floor-inset-resolution-inverse]].

**Measure the RENDER, not the rects.** A Frida trace of the box rects can read perfectly symmetric while
the strokes are not (this floor-loss lives in the enlarge, downstream of the rect — the trap that made
two earlier "fixes" address the wrong layer). Confirm by pixel-measuring the actual frame in a
screenshot, and **palette-resolve each pixel to RGB**: the strokes are green (e.g. `0x1f`=(49,78,44),
`0x22`=(35,59,34)) over a **near-black** backdrop (`0xc6`≈(12,12,16)), so a raw luminance threshold
mislabels them — classify by green-dominance. Also separate the concepts: **stroke THICKNESS** vs the
**CHANNEL gap** between strokes are different measurements; the faction defect was the channel, not the
thickness. The bright topmost line above the title (`0x1a`≈(73,108,61)) is the **window border** (d690),
not part of the title frame — don't count it as a stroke.

## Dead ends (do not retry)

- Scaling `rect.left` in `thunk_content_frame` to widen the outer margin → overlaps the **fixed-X row
  checkboxes** and corrupts downstream layout (the rect is reused). The left margin has no room; use §2.
- Pulling the frame's top/bottom in (`[eax+4]+=N`,`[eax+0xc]-=N`) to hide strips → cosmetic hack that
  moves the frame off the rows; the strips were the blit-key bug (§1), not a sizing issue. Reverted.
- Compensating the §5 floor-inset (right/bottom stroke pulled in) with a `popup_scale(N)` outward push →
  it scales backwards (the inset is big at low g, ~0 at 4K) and crushed the 4K inner/outer channel. Use
  exact-fill instead. (file-dialog inner frame, v9→v10.) See [[feedback-floor-inset-resolution-inverse]].

## Sites in this repo (Customize Game Rules, all confirmed)

- Title frames (opaque): `thunk_box_thick_flat` (key -1, Δ=0) @ 0x406048/0x406078 via `thunk_pf_title_stash` /
  `thunk_inner_margin`, group `popup_title_scaling`.
- Options/outer-union frame (hollow): `thunk_content_frame` @0x406238 → tail-jmp `thunk_box_thick_hollow`
  (key 9), group `popup_list_fill_width`.
- Box margins: `thunk_scale_box_margin` @0x404e93, group `popup_box_margin_scale`.
- Dithered modal bg (§4): `thunk_box_thick_devfill` (pcave2 +0xE00) wired on d690 @0x405f77 (group
  `popup_outer_backdrop_scale`) + d528 (via `thunk_channel_adjust` tail); faction quote box, build 70bd8286.
  Keystone src `work\scripts\assemble_box_devfill.py`.

## 7. Periodic scanline dither — SYNTHESIZE at device density (never resample, never flatten)

A 1px-period scanline dither (the dark navy/black field behind the file-picker list, title strip, and
margins; pair = idx **65 black / 196 navy**, selected-row blue 224/225) **cannot survive any resampling**:
NN beats it into irregular 1,2,1,2 runs at fractional g, and bilinear only softens the beat
([[feedback-dither-no-resample-on-upscale]]). Flattening to a solid loses the texture (user-rejected
v1–v5). The only faithful fix is to **GENERATE the pattern at the output density**: uniform stripes,
period **P = 2T, T = stripe_rows(g)** device rows per stripe, both members the same thickness:
**T = 1 below g = 22** (screens under 1080 px high — 2 rows read too coarse there, user 2026-10-04 on
1600x900), **else art_scan_rows(g) = max(2, g // 16)**, the pictures' scanline rule (ONE stripe thickness
on every surface; it replaced the proportional `P = (g+4)>>3`, whose 2/1 and 3/2 duties beat against the
2-row pictures). `thunk_ensure_scale` stores P in the cell `g_stripe_period` next to g and the popup-g
thunks read it; the Monument / Hall of Fame thunks compute T from their own num (T = 3 from num 48).
Top member first, **hN = (P+1)>>1 = T**. Call `scaling_laws.stripe_period` / `stripe_top`; never
re-derive. A Unicorn harness that writes g gets the cell written for it (tests\conftest.py). Never put a
`;` comment in keystone asm text (it hangs). Since it's generated, runs are uniform at every g — no beat
by construction. Two mechanisms, chosen by WHERE the dither comes from:

- **(a) The dither is a TILED SPRITE fill (`Buffer_tile` of a 24×24 tile): swap the tile.**
  `Buffer_tile` (0x5DA860)'s "sprite" arg is just a **Buffer** (it reads only W +0x80 / H +0x84 and blits
  via `Buffer_copy_4`), so build a 0x800×P scratch striped tile once per g (`thunk_ensure_stripes`:
  `crt_malloc(0x588)+Buffer_ctor+Buffer_resize+Buffer_set_clip+2×Buffer_fill_3` — set the clip explicitly,
  a fresh Buffer's stale clip silently empties `fill_3`) and swap the sprite arg at the call site, keeping
  the vanilla `srcOff==dest` args (= ABSOLUTE grid anchoring). File-picker rows + the two `Buffer_copy_4`
  backdrop captures (replaced with a `Buffer_tile` of the same tile) are this case.
- **(b) The dither is BAKED INTO the 9-slice frame ART: colour-keyed REMAP after the enlarge.**
  Frame art can carry dither rows *inside the sprite* (the file-dialog d618 title band is ALL dither;
  every stroke has a dithered ring at the art-piece thickness) — there is no fill param to redirect and
  no tile call to swap, and §4's devfill can't help (the dither isn't `params[8]`). Fix: after the §1
  enlarge blits, walk the dest rect and rewrite **only pixels equal to a dither pair** to the
  stripe colour for their output row (`y mod P < hN → top colour else bottom`). Everything else —
  strokes, bevel, text, art — is a different index and passes through untouched, so no masking/geometry
  is needed and overlapping art is safe. Implementation: `thunk_frame_enlarge` stashes the blit's dest
  buffer+rect (+ the SRC ptr, `g_fe_src`) into globals pre-blit (both exact-fill paths converge there),
  then calls `thunk_fe_pair_remap` (raw pixel walk via Buffer **data +0x54 / stride +0x4a8**; clamp to
  buf W/|H|, H stored negative). **Skip the bilinear path**: its blend re-quantises the pair to other
  indices (197/198) and ornate metallic art has legitimate dark pixels the remap would eat.

  **THE PAIR-AMBIGUITY RULE (the sharp edge — see [[feedback-dither-pair-ambiguity]]):** an index can
  belong to MULTIPLE pairs or be a legit solid. `0x41` partners `0xC4` (navy fields) but also `0xC6`
  (d690 backdrop pair), `0x54` (ornate game-start fill), and is the solid `thunk_box_thick` title-outer
  pre-fill. And a hollow frame's dest-rect walk touches everything composited UNDER the frame. So:
  remap unambiguous pairs (`0xE0/0xE1` blue rows, `0xAE/0xEE` teal rows) unconditionally; for the navy
  family decide **per blit by scanning the src** for the unambiguous mate (`#C4 > srcW/2` over the first
  min(8,srcH) rows → genuine field; backdrops/solids ≈ 0 → leave `0x41` alone). Evidence tool:
  `work\scripts\hook_dither_map.js` logs a per-pair count + max-vertical-run histogram of every enlarged
  src (run ≤2 = pure dither; run ≥3 = a solid a remap would corrupt).

  **THE STATE/RECOLOR RULE (the OTHER sharp edge — [[feedback-draw-state-multiplicity]]): never
  hardcode a pair for an element that has variants.** The "same" element renders DIFFERENT pairs per
  interaction state or animation frame: the HUD MENU/COMMLINK band is a 3-sprite state ARRAY (idle
  0x7d059c 92/C8, hover 0x7d05c8 E6/E7, pressed 0x7d05f4 63/66 — stride +0x2C), and turn.flc's flash
  frames recolor the identical layout with a different pair every frame. A hardcoded pair fixes the
  one state you censused and leaves the rest banding (the pressed-state regression on build 71abb57e).
  Default to **PER-DRAW pair detection**: sample two vertically-adjacent pixels of the NATIVE source
  just before/after the stretch (pick a column inside the field, away from border cols/rows and any
  overlaid glyphs), skip on equal / key / border indices, top-stripe colour = the even-native-row
  member. Then every state, recolor, and future palette variant is covered by construction
  (`restripe_core` + the two detection wrappers in `assemble_band_restripe.py` are the reusable
  implementation; identity-gate the call site, not the pair). Census every state before trusting ANY
  pair table: hover, press-and-hold, animating — see the state-census rule in [[frida-tracing]].

### 7c. When the strip ALSO map-bleeds — full-rect RE-SYNTHESIS (covers the engine's dropped row)

The §7b remap recolours dither but still relies on the ENGINE's scaled blit to *place* the pixels — and
that blit has a second defect. At fractional num/den the engine expander (`Sprite_fill_scaling_table`
Bresenham @0x5EB20F + `Sprite_get_clipped_y_table_expand` @0x5EABBF, shared by `Sprite_blit_scaled_core`/
`Sprite_draw_2` + 6 other wrappers) covers one dest row **short** of the true scaled height. The dropped
row keeps the buffer's **key-9** fill, so on a keyed window the MAP bleeds through as a **1px
background-coloured streak per blit** (red over red map, invisible over dark). Invisible at 4K: exact
2.5× (18→45) AND the gap row lands on the dark stripe phase — never conclude "no gap" from one 4K
background. See [[feedback-sprite-expand-drops-last-row]].

When a strip shows a 1px background-coloured streak per blit at non-4K, don't remap — **synthesize the
whole dest rect yourself**, post-blit:
- Walk the full scaled dest rect. For each dest `(x,y)`, NN-map back to the native source cell via an
  integer row/col **DDA** (`srcRow = y·den/num`) — this covers ALL rows **including the one the engine
  dropped**.
- Structural (non-dither) source pixel → NN-place; key pixel → skip; a detected dither-pair member →
  overwrite with the **P-law stripe colour** for the dest-buffer row (phase = dest `y`, so every strip
  shares ONE seamless pattern and is bit-identical to exact NN at 4K = no-op there).
- Detect the pair **per-draw** from the native sprite (strict-alternation probe at two adjacent mid
  rows) — never a hardcoded index (§7b state rule).
- **Uniform row pitch:** a native `y = base + k·rowH + r` must map to `sc(base) + k·sc(rowH) + sc(r)`,
  NOT per-value `round(y·g/16)` — per-value rounding drifts the seam 1px per row AND restarts the NN
  phase = the seam banding the user reported at g=22/25.
- `Sprite_draw_2` is **THISCALL** (ECX=sprite, `[esp+8]`=key): read the sprite from **ECX**, not the
  stack, or the h-gate + pair detect run on garbage (the zero-diff MENU bug).

`hm_synth_core` (pcave2, group `commlink_menu_scale`, src `scripts\assemble_hudmenu_scale.py`) is the
reusable implementation; prototype `synthStrip()` in `hook_hudmenu_scale.js`. Build fad779d8,
user-verified 4K/1920/1600. Full mechanism: [[project-smac-commlink-panel]] + [[project-smac-hud-scaling]].

Anchor every stripe producer to **the same grid: `y mod P` from the OWNING BUFFER's origin** — the tile
swap keeps the engine's absolute anchoring, the backdrop tile starts at dest 0 phase 0, and the remap
computes row colour from the dest-buffer y. Layers drawn into the **same buffer** (frame rings, backdrop,
rows) then align exactly, with no seams at draw boundaries. Phase across *different* buffers (window vs
list child) may differ by the composite offset — invisible across a frame stroke, don't chase it.
**Pictures sit on the same grid** (option B stage 2, 2026-10-06): every picture enlarge — the exe art body
(`art_reblit_row(j, sh, num, den, y0)`, field from `[ebp-0x18] + j`), uimod `Enlarge` / `FieldEnlarge` /
`EnlargeRgb` (Draw's `y0`, cache key carries `y0 mod 2T`), the council flag LUT (`flag_restripe_bright` =
`stripe_top(Y + r)`) — takes its field from the DEST row via `art_scan_phase(y0 + jt)`, never from the
picture's own first interior row (that was the 1-row step along the BIOSCAN silhouette / colour bar).

### Diagnosis — which case is it?
- Run-length the field in a screenshot column: period tracking g ⇒ a stretch is producing it (find the
  stretch); period 1px at any g ⇒ native tiling (case a, only *reads wrong* vs a scaled reference).
- **Flipped-duty rings hugging the strokes** (e.g. field N2/K1 but K2/N1 for ~an art-piece-width beside a
  frame) = the art-baked case (b) — the ring is the frame sprite's own dither, drawn by the enlarge.
- The colour pair is exact palette indices — scan with exact-match, not luminance.
- Duty note: P is even, so the field is pristine's 50% duty at every g; the coloured member opens the grid.

File-picker build 7d9ba26c (v6 + P3e), user-confirmed at all resolutions. Full history + colour tables:
[[project-smac-filedlg-dither-synthesis]].

## Sites — Load/Save file picker (P3c–P3e, final build 7d9ba26c; all user-confirmed, CLOSED)

- One dispatcher `thunk_filedlg_frame` (pcave2 +0x2720, 435B; keystone src `work\scripts\assemble_filedlg_frame.py`
  — regenerate via inline `python -c`, a file-run backgrounds + loses output) redirects all 5 file-dialog
  `Buffer_box_sprite` calls, dispatching on the params VA: OUTER (6846b0/78D690) → `hollow_flat` + exact-fill +
  **bilinear** (`g_fd_bilinear` → `thunk_bilinear_blit`, ornate edges tear under NN); INNER (78D528) → `hollow_flat`
  + exact-fill (§5; flush right/bottom — was the v9 popup_scale-push dead end) + bottom button-gap push; TITLE
  (78D618) → concentric-to-inner (`g_fd_inner`) + exact-fill + `hollow_flat`.
- Row pitch (NOT a frame): `thunk_filedlg_listpitch` (pcave2 +0x26C0) entry-detour on `ListBox_draw_item`; scale
  the SHARED `Dialog[+0x68]/[+0x44]/[+0x34]` only while native (`cmp lh,0x10; jg skip`), else per-row re-scale
  compounds. See [[feedback-shared-field-per-row-doublescale]].
- Dither stripes (§7a): `thunk_ensure_stripes` (pcave2 +0x2DA0) + `thunk_filedlg_rowbg_v6` (+0x2F00, row-tile
  swap @0x407327) + `thunk_copy4_stripes` (+0x2F50, backdrop captures @0x60BBBA/0x60C421). Gated
  `g_filedlg_active` then g≤16→native.
- Frame-baked dither remap (§7b): `thunk_fe_pair_remap` (pcave2 +0x3860, 377B v2; keystone src
  `work\scripts\assemble_fe_pair_remap.py`) called UNGATED from `thunk_frame_enlarge`'s (+0x30A0) NN tail
  for EVERY menu (build c592d318 — the original +0x2FD0 thunk was navy-only + `g_filedlg_active`-gated,
  which left all non-filedlg popups banding, refs\MangledSmacx.png). 3 pairs per the ambiguity rule
  above. Cave-content only — no new sites.

## Sites — faction picker ("Choose Your Factions", all confirmed)

- One dispatcher `thunk_factionwin_framecover` (pcave2 +0x2400) call-redirects all 4 redraw box draws
  (d690 backdrop / d5a0 title / d618 inner-title / d5a0 list): scales+centers the rect, derives the inner
  title d618 **concentric** to the cached outer d5a0 rect (`g_fc_title_rect`, inset `popup_scale(3)` all
  sides — fixes the rect-level asymmetry), dispatches by the FILL field `[params+0x20]` (filled→devfill,
  hollow→`_hollow_flat`), and sets `g_fc_exact` for the two title strokes (§5 exact-fill — fixes the
  render-level channel asymmetry). Build a190c45b.
- Exact-fill enlarge (§5): `g_fc_exact` flag (pcave2 +0x2554) + the modified `thunk_frame_enlarge`
  (now at +0x30A0). Title channel even top/bottom/left/right at 1600×1200 + 1920×1080.

## 8. Aligning a NEIGHBOR (art, another frame) to a drawn stroke — the rect→drawn transform

A frame's **drawn** stroke is NOT at its rect edge once §1 thickening is in play. Two terms sit between
the rect a thunk stores and the pixel the player sees, and both scale with g:
- any downstream inset the engine (or our inset thunks) applies before the draw (e.g. the popup field
  frame draws `p3 = floor(3g/16)` outside its stored rect), and
- **the §1 thunks' outward grow `Δ = (g−16)>>3`** — the stroke lands `Δ` OUTSIDE the rect on every edge
  (0 @g22, 1 @g25, 3 @g40).

Rules learned the hard way (Quit art/text-box flush, builds f7d13698→95b68156):
- **Calibrate `stash→drawn` empirically, and INCLUDE a 4K point.** A residual profile of ~3px @4K /
  ~1px @1600 / 0 @1920+native is Δ's signature; three calibration points that all sit where Δ≈0 will
  produce a law that's exact everywhere except 4K (exactly the bug class users report as "rounding").
- **Facing strokes lose `2·Δ` of margin**: a band's BOTTOM stroke grows down `Δ` while the frame-below's
  TOP stroke grows up `Δ`. A vanilla margin of 3 → `p3` between the RECTS reads `p3 − 2Δ` between the
  DRAWN strokes (~1px @4K). Fix at the rect level: anchor the lower rect to the upper rect's stored
  coordinate **plus `2·(p3+Δ)`** so the drawn margin = `p3` exactly (Quit: `fieldT = bandB + 2·(p3+Δ)`,
  native identity 29+2·(3+0)=35 = pristine).
- **Anchor to the other artifact's STORED coordinate, never a parallel formula** — two cascades that
  agree at g=16 floor apart at fractional g. Stash the source rect where it's final (one detour), read
  it in the consumer.
- **Ordering**: `Popup_on_draw_background` draws the chrome BEFORE the popup art blits — so the art can
  read frame stashes, but a frame cannot read the art's final position. Don't design the dependency
  backwards.
- **Stash hygiene** (popups REUSE heap ptrs): key the stash to the owner (`g_band_popup=esi`),
  consume-on-use in the reader, and disarm at `Popup_hide` (folded into `thunk_popup_railhide`); an
  excluded owner (the faction quote popup — its portrait layout is separately tuned) simply never arms
  the key, and the reader passes through native.

- **A popup may have NO TITLE** (`[popup+0xa48]==0`): `Popup_on_draw_background` jumps over the whole title block
  (`je` @0x405f84), so every per-draw title stash (`g_title_left/right/bottom`, the band key) is simply NOT WRITTEN and a
  reader gets the PREVIOUS popup's values. Any lever that reads a title stash must have an untitled answer.
  `thunk_untitled_stash` (site 0x405F7C) supplies it by running the titled path's own inset thunks on the window rect —
  call the other cascade, don't re-derive it. The untitled header reserve is 18 (titled 38) and scales the same way.
- **The nest pad at 0x406211 serves three source-rect paths with two different meanings**: around a LIST it is the
  stroke→rows channel (`scale_px(2)`); around a drawn d528 text box (body-only path) it is the stroke PITCH
  (`popup_pad(3)`). `nested_frame_pad(g, body_only)`. Verify a pad change on all three paths.
- **When two elements that should be flush are not, measure EACH against vanilla at three resolutions before choosing
  which one moves.** Quit's art sat Δ above its ring after the ring stopped growing; history said "the ring is low",
  the numbers (band→ring 9/4/3 vs vanilla 7.5/4.7/4.1) said move the ART. `flat_art_anchor`.
- **Not every art popup is flush**: the faction quote portrait sits 1 NATIVE px below its ring in vanilla. Measure the
  relation per popup on a ≥1.5× pristine capture; never assume Quit's.

Sites: group `popup_art_align` — `thunk_band_stash` (@0x40603D detour, band L+B), `thunk_popup_fieldpads`
v3 (band-anchored field top), `thunk_popup_artalign` ([popup+0x3168] wrapper: art x = bandL+5+g/16,
y = fieldT−p3−Δ+6), build 95b68156, user-confirmed 4K/1600/1920.

## 6. FlatButton bar fill + corner notch (faction buttons — confirmed, build cb53e04f)

The faction picker's buttons (INFO/CHANGE NAME/OK/CANCEL, PLAY SELECTED/RANDOM) are **FlatButtons**, not
9-slice popup frames — a separate but analogous device-fill path. `thunk_btn_2dscale` NN-zooms the whole
button buffer, then calls **`thunk_btn_devfill`** (pcave2 +0x1660) to re-tile the captured bar dither at
**device** resolution (same anti-banding idea as §4) and punch the 4 corner notches via
`thunk_corner_punch` (+0x1740).

**STATES + the stripe law (build 1417a5c2, all user-confirmed):** the body sprite is picked by state
index `ebp` at the fill (0=normal dither `0x77a90c` ae/ee; 1=hover `0x77a990` = ae/ee **+ solid 0xE0
edge rows**; 2=pressed `0x77aa14` = pure 0xE0/0xE1 dither). devfill only re-tiles state 0 — hover/
pressed kept the raw NN zoom and **banded**. Fix: `thunk_btn_stripes` (pcave2 +0x2FD0, between 2dscale
and devfill) runs `thunk_fe_pair_remap` (§7b) over the whole button buffer for EVERY state
(`g_fe_src=0` → navy family off). **Pick the remap law by the SCREEN's dither language**: popup/filedlg
buttons use the natural period-P law (their rows are P-striped); faction buttons set the one-shot
`g_rm_povr=2` override (self-clearing) = **1px parity law**, keeping that screen's 1px device-density
language for all states (accepted collateral: hover's solid E0 edges dither to E0/E1 on odd rows).
`g_rm_povr` contract: only set when g>16 is guaranteed — the remap's g≤16 early-ret doesn't consume it.

- **Corner notch shape = solid `s×s` SQUARE** (`s=ceil(g/16)`), pure H/V edges. The user **chose the
  square over a 45° staircase** (a staircase reads as a diagonal nick at 1920/s2). The source chamfer is a
  single 1px transparent corner pixel; don't relitigate the shape into a bevel. `thunk_corner_punch` is
  the 17B square fill (`ebp=s, ecx=stride, edi=corner topleft`).
- **Re-tile FULL-BLEED over the whole buffer** (`destX=0, destY=0, destW=origW, destH=origH`), and place
  the bottom corners at `origH−s`. A capture-based height (`fill_h·g/16`) rounds **~2px short** of the true
  scaled button height → the engine's native fill **over-draws** the bottom rows (a thin strip) and the
  bottom notch sits 2px high. Full-bleed cures it (these buttons are full-bleed: dither spans the buffer
  top-to-bottom, no in-buffer frame).
- **`origH` MUST be `NEG([g_btn_origH])`.** That global (and `[esi+0x4c8]`) store the buffer `h` field
  **negative** (top-down DIB); using it un-negated as `destH` / `(origH−s)·stride` crashed at 4K. See
  [[scaling-sprites]] "sharp edges" + [[feedback-negative-height-saved-copy]].
- **Measure from a screenshot pixel-grid** (Frida can't hook this redraw): the top corner read correct
  while the bottom showed the 2px over-draw. Full writeup: [[project-smac-faction-button-corners]].
