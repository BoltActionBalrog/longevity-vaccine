# WHY — rejected alternatives for the scaling laws

Records of what we **did** are everywhere: `patches.yaml`, `CHANGELOG.md`, git history. Records of
what we **tried and abandoned** exist nowhere, so every few months someone (human or model) proposes a
dead end that looks obviously correct, spends a day on it, and rediscovers the same failure.

This file is that record. **Read it before proposing an alternative to `work\scripts\scaling_laws.py`.**

Each entry: what was proposed, why it looks right, and the specific way it fails. Every one of these
was actually implemented and actually failed — none is hypothetical.

---

## 1. Lattice snap: round every rect to a K-pixel grid

**Proposal.** Strokes wobble because `span % K != 0`. Snap all four rect coordinates to a multiple of
`K = round(g/16)`, then every source pixel maps to exactly `K` dest pixels and both edge strokes are
uniform. Spend the ≤1px error on the element's outer extent, never on a stroke or a channel.
(Implemented as `hook_intksnap.js`.)

**Why it looks right.** It genuinely does make opposite strokes equal, and the maths is clean: with
`span % K == 0` the NN ratio is exact, so there is no remainder to dump on an edge.

**Why it fails.** `K` is 1 or 2 across the whole clamp `g ∈ [16,40]`, so "multiple of K" means "even".
**An even lattice cannot represent an odd margin.** The faction quote's channel is `ps3 = (3g)>>4 = 7`
at 4K — odd. The snap crushed it to 6 or 8, visibly moving the quote frame and changing a margin the
user had already approved. Any scheme that quantises the *rect* destroys odd geometry somewhere.

**What replaced it.** Leave the rect alone; change only the enlarge. The band map (`axis_map`) gives
uniform strokes for *any* span, so nothing needs snapping.

---

## 2. Derive the stroke width K from each frame's own dst/src ratio

**Proposal.** The band's scale is `DW/srcN`, so the stroke should be `round(DW/srcN)`, not
`round(g/16)`. Then the band and the stretched middle share one scale and the corner joins its edges
seamlessly.

**Why it looks right.** It is locally self-consistent, and at 4K the two agree (`2.5` either way), so
it passes the resolution you look at first.

**Why it fails.** `srcN = floor(DW·16/g)` carries its own rounding, so `DW/srcN` differs from `g/16`
at exact-half boundaries — and it is **span-dependent**. At `g=40` the ratio is `2.5014` for most
spans, which `half_down` tips from 2 to **3**, but spans divisible by 5 stay at 2. Result: two frames
on the *same screen* get different stroke widths. That is the exact disease this workstream cured.

**What replaced it.** `K = half_down(g,16)` — from the lever alone, identical for every frame on
screen. Only the band *depth* `B` derives from `DW/srcN`, so the band still meets the middle phase
seamlessly. Guarded by `test_stroke_width_takes_only_g`, which inspects the function's signature.

---

## 3. Re-render the 9-slice from the raw BoxSpriteParams sprites

**Proposal.** Don't scale a rendered frame — scale the *sprite set*, and let a hand-written renderer
blit corners at integer `K` and tile edges at `K × native` thickness. Extent is exact by construction;
no snap, no `g_fc_exact`, no channel error.

**Why it looks right.** It is the textbook 9-slice fix, and `Buffer_box_sprite` really is a 9-slice
(corners `Sprite_draw_2(...,1,1)` native, edges `Buffer_tile_2` at `canvas_h`).

**Why it fails.** It means re-deriving canvas-vs-blit dims, `off_x/off_y`, key handling and tile phase
— and getting every one right. It painted the edge sprite's five `0x07` body-fill rows that the engine
leaves transparent, so body colour leaked inside the stroke: 1px on the near edges, 3px on the far
ones. The user's verdict was decisive: *"We're still drawing incorrect colors. I'm not talking about
geometry."* **The engine already renders this frame correctly at native size. Do not re-derive it.**

**What replaced it.** Let the engine render the native scratch exactly as the shipped thunk does;
replace only the enlarge. Colours can no longer be wrong because none are chosen.

---

## 4. Round half UP

**Proposal.** `half_down` is unusual. Use ordinary rounding.

**Why it looks right.** It is what everyone writes by default.

**Why it fails.** `g/16 = 2.5` exactly at 4K. Half-up renders every 4K frame stroke at **3px**. The
user approved 2px. `half_down(a,b) = (2a + b − 1) / (2b)`, and the golden vectors pin
`stroke_width(40) == 2` with that comment attached.

---

## 5. Model the stretch blit as `floor(j·src/dst)`

**Proposal.** `thunk_keyed_stretch_blit` is nearest-neighbour, so dest pixel `j` samples source pixel
`floor(j·src/dst)`. Derive the "before" stroke widths from that and use them as the bake's oracle.

**Why it looks right.** It is the standard NN mapping, `terranx.h` says the chain is "GDI StretchBlt",
and the model **agreed with two of the user's screenshots** at two different resolutions.

**Why it fails.** `thunk_keyed_stretch_blit → Buffer_copy_3 @0x5D9610` dispatches through *surface
vtables* (`call [ecx+0x68]`, `call [edx+4]`) — the mapping is not statically derivable from our bytes.
The real blit is **centre-aligned** NN, which is symmetric at every ratio **except a half-integer one**.
So the 2px/3px stroke split is **4K-only** (`40/16 = 2.5` exactly), not universal. The model predicted
wobble at every resolution and produced a table that was confidently, thoroughly wrong. Agreement on
two points of a curve says nothing about its shape.

**What replaced it.** `hook_strokecensus.js` — read the destination pixels and measure the real stroke
thickness. Result: 34 of 42 frames violate at `g=40`; **zero** at `g=22` and `g=25`.
**Corollary now in CLAUDE.md: measure the engine, do not model it.**

---

## 6. `p3 = floor(3g/16)` explains the field-box insets

**Proposal.** `thunk_popup_fieldpads` pads L/R/T by `p3` and forgets the bottom; that asymmetry is the
channel bug.

**Why it looks right.** The thunk's own comment says exactly that, and the pristine `d528` rect is
`(edi−3, ebx−3, ecx+3, eax+ebx)` — L/T/R padded, B not.

**Why it fails.** Measured insets are `4/4/4` at `g=22`, `5/5/5` at `g=25`, `10/10/10` at `g=40`.
`p3` would give `4/4/7`. The real cause was elsewhere entirely (see §7).

---

## 7. "The concentric rects are misaligned"

**Proposal.** The outer and inner frame rects are rounded independently, so the channel lands wherever
the roundings fall.

**Why it looks right.** The channel really was asymmetric, and the numbers really did vary per
resolution.

**Why it fails.** `hook_fieldrect.js` showed the rects **concentric** (`4/4/4/4` on all three pairs). The
frames *under-filled* them: `thunk_frame_enlarge` sized the blit `srcW·g/16` where `srcW = span·16/g`
was already floored — a **double floor** losing up to 2px. At `g=16` `dst == span`, so **exact fill is
the vanilla behaviour**; the prototype had it by construction and the first bake dropped it.

**Scope of that evidence (read before citing it).** Those captures are `g=16` and `g=22` only, and
`Delta = (g−16)>>3` is **0 at both**. They disprove independent *rect rounding*, which is what this
proposal claimed. They say **nothing** about the `Delta` grow of §8, which cannot manifest below `g=24`.
A `4/4/4/4` reading at `g=22` is not evidence that `g=40` reads `7/7/7/7`. Measure at `g=25` (Delta=1)
or `g=40` (Delta=3) before concluding anything about a Delta-shaped channel defect.

**Lesson.** When porting a prototype, port its **invariants**, not just its code. "Exact fill by
construction" was a property of the design, not a line of the blit. And a measurement taken where the
suspected term is identically zero refutes nothing — check that your capture's `g` can even *express*
the defect.

---

## 8. Removing a hack is a one-line change

**Proposal.** `D = (g−16)>>3` (the renderers' outward grow) is vestigial once the band map puts a
`K`-wide stroke at the rect edge. Zero it.

**Why it looks right.** It is true. `D` is 0 in vanilla, so it violates `patched = vanilla × g/16`, and
it inflated concentric channels (outer `hollow` had `D`, inner `hollow_flat` did not).

**Why it is incomplete.** **Every compensation written against `D` dies with it.**
`thunk_pf_frame_align`'s `D2 = ps3 − Delta` existed solely to cancel that grow; zeroing `D` made the
left/right channels `Delta` *smaller* than top/bottom at `g ≥ 24`. `thunk_box_thick`
deliberately **keeps** its `D` — its title pair applies it to both frames, so that channel is already
faithful, and compensations referencing the *title's* grow remain valid.

### ⚠ `thunk_popup_fieldpads` and `thunk_popup_artalign` — DO NOT "FIX" THESE

Two compensations still reference `Delta` and *look* stale:

  * `thunk_popup_fieldpads`: `T = g_band_bottom + 2*(p3 + Delta)`
  * `thunk_popup_artalign`:  `y = anchor − floor(3g/16) − Delta + 6`

**They are deliberately untouched, and the obvious fix is not supported by evidence.** What is
established, by measurement, not by model:

  * `thunk_box_thick`'s outward grow is **exactly `Delta`** — the title frame's drawn bottom sits at
    `rectB + Delta` (`+1` @ g=25, `+3` @ g=40; `−1` at native, where a 1px stroke ends at `rectB−1`).
    So `box_thick` genuinely grows *into* the margin that `fieldpads` widens. The two may cancel.
  * The concentric channels are **correct**: `d528`/`d5a0` insets read `7/7/7/7` at 4K and `4/4/4/4`
    at 1600×1200, i.e. exactly `ps3(g)` on all four sides, with no `Delta` term.
  * A pixel probe of the drawn band→ring margin (`hook_fielddrawn.js`, since deleted) produced
    `4 / 4 / 9` at g=16/25/40 against a faithful `4 / 6 / 10` — *too tight*, the **opposite sign** to
    the predicted "Delta too large", and matching neither `Delta` nor `2·Delta`. That measurement was
    itself unsound (it compared different popups, and its "body top" caught the field's interior fill
    rather than its stroke), so it proves nothing either way. It does prove the naive story is wrong.

**Rect coords are not stroke coords.** The rect gap `fieldTop − bandBottom` really does equal
`2*(p3 + Delta)` exactly at g=22/25/40 — and that fact alone tells you nothing, because `box_thick`
draws past its own rect and the body frame does not. Anyone who "fixes" `fieldpads` from the rect
arithmetic will move a margin that may already be right.

Before touching either: measure the **drawn** margin on the *same* popup across g, on the pristine exe
first. The user's all-res visual pass found nothing wrong here. This is low-priority polish, and the
cost of getting it wrong is a visible regression in every popup.

**Lesson.** Before removing an additive constant, grep for its asm signature (`83 E8 10 C1 E8 03`)
**and** its name in comments; fix or re-verify each compensation in the same change. Decide
per-subject, never globally.

**Postscript (2026-07-10).** The lesson was incomplete when written: `D2` was found and re-derived,
but **two more compensations against `D` were missed** — `thunk_pf_union_align` and
`thunk_pf_frame_align`, whose `right = g_title_right` only landed flush because the hollow re-added
`D` at draw time. Zeroing the hollow's `D` slid every body pair `Delta` inside its title pair; the
user caught it as the quit modal's body frame 4px left of the title frame at 4K (art popups added a
1px floor-lag on top, §10). The compensations you miss are the ones that don't *mention* the constant:
these two never named `Delta` — they silently assumed both draw paths grew alike. See §10 for the law
that replaced rect-equality alignment. The `fieldpads`/`artalign` warning above still stands unchanged.

---

## 9. Scale the option-row GAP proportionately

**Proposal.** The QUIT modal's two buttons are too close at 4K. The gap between them is 2px in vanilla, so
scale it: `gap' = half_down(2g, 16)` → `2 / 3 / 3 / 5` at g = 16 / 22 / 25 / 40. Textbook LAW 1.

**Why it looks right.** It is LAW 1, applied to exactly the quantity the user is complaining about. It
reproduces the engine's own numbers at **every resolution we ship against** — 4K, 1600×1200, 1920×1080 — and
at native. Four for four. The gap even comes out 5 at 4K, which is the correct answer.

**Why it fails.** The engine positions row *i* on a **uniform stride** `pitch = rowH + gap`, and `rowH` is
itself a scaled quantity (`Buffer_text_line_height`). Scaling `rowH` and `gap` independently means each
rounds independently, and their sum is not the rounded sum:

```
half_down(20g,16) + half_down(2g,16)  !=  half_down(22g,16)      at g = 18, 26, 34
```

Rows land 1px off the faithful pitch at those three levers — invisible at every resolution anyone tests, and
wrong at 1152×864. This is `n·floor(s·v) != floor(n·s·v)` (see [[feedback-remainder-distribution]]) wearing a
different hat: the same disease as the faction-row pitch, found *before* it shipped only because the sweep
runs over all 25 lever values instead of the 4 we look at.

**What replaced it.** LAW 5, chrome follows content. The pitch is what positions the row, so pin the *pitch*
and let the gap absorb the rounding:

```
pitch' = half_down(22g, 16)          # 22 = vanilla pitch, MEASURED on the pristine exe
gap'   = max(0, pitch' - rowH)
```

At g=16 the calc still measures rows with `Buffer_text_height` (19), so `gap' = 22 - 19 = 3` — the vanilla
field value, **algebraically**. The native no-op is a proof, not a test that happens to pass.

**Second trap in the same defect.** The gap must be written to the FIELD `[D+0x44]`, not just to the calc's
register: the draw loop at `0x60d8f3` re-reads the field to rebuild its own pitch. Fixing only the calc
(Site B, `0x60d731`) grows `content_h` — a taller box — while the bars do not move.

---

## 10. Align two frames by giving their rects the same coordinate

**Proposal.** The body-outer frame must sit flush with the title-outer frame (vanilla law: both rings
end at `backdrop − 4`). The popup already computed the title rect, so stash it and reuse it:
`union.right = g_title_right`. Same coordinate, same 9-slice thickener family — flush by construction.
(Shipped as `thunk_pf_union_align`/`thunk_pf_frame_align` v2.x.)

**Why it looks right.** It follows the "read the other artifact's stored coordinate, never a parallel
formula" lesson (the right instinct — parallel formulas floor differently at fractional `g`, §9's
disease). And it genuinely *was* flush when written.

**Why it fails.** **Rect equality is drawn-edge equality only while both draws share the same
rect→stroke transform** — and the transform is a property of the thickener *variant*, not of the
family. `thunk_box_thick` (title) lands its stroke `Delta=(g−16)>>3` OUTSIDE its rect; when §8's
cleanup made `thunk_box_thick_hollow` (body) draw FLAT, identical rects started producing edges 3px
apart at 4K — and no test failed, because the invariant lived in a comment ("same outward grow as
title-outer"), not in a law. The failure is also invisible below `g=24` (`Delta=0`), so 1920×1080
verification passes it clean. Separately, gating the aligns OFF for art popups (a LEFT-edge concern —
don't span the image) silently discarded the RIGHT-edge alignment those popups still needed: an
all-or-nothing skip of a per-edge law.

**What replaced it.** `scaling_laws.py :: body_outer_edge_r/_l, body_inner_edge_r/_l` — the
flat-drawn rect **pre-adds the counterpart's grow**: `union.r = title.r + Delta`,
`d528.r = title.r − (ps3 − Delta)`; art popups keep their art-aware left and align only the right.
Swept per-g by `test_scaling_laws.py` (drawn-flushness + channel invariants, the 0/0/2/4px defect
signature pinned) and the shipped bytes emulated against the laws by `test_pfalign_asm_parity.py`.
**Rule: an alignment between a grown-drawn frame and a flat-drawn frame is a LAW about drawn edges;
state it in `scaling_laws.py` where the sweep can watch it, because the g<24 window hides it from
every eyeball pass.** If the `box_thick` family's grow ever changes again, the pf aligns are the
compensations to re-derive (pointer comment on the hollow's DELTA REMOVED block in `patches.yaml`).

---

## How to add to this file

When an approach is abandoned, add an entry *before* you delete the code. State it in the form
"proposal / why it looks right / why it fails", and name the concrete evidence (a log, a measurement, a
user quote). An entry with no failure mechanism is not useful — it will just be re-argued.
