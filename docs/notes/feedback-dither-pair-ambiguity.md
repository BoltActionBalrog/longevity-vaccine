---
name: feedback-dither-pair-ambiguity
description: a dither-pair INDEX can belong to multiple pairs (0x41 pairs with 0xC4, 0xC6, 0x54) or be a solid fill — key a pair-remap on the pair-MATE's presence in the SOURCE art (content-keyed per blit), never remap a shared index blanket
type: feedback
---

When generalizing a colour-keyed dither remap (scaling-frames §7b), a palette index that looks like
"the black half of the navy pair" can be SHARED: in SMACX, `0x41` partners `0xC4` (navy title/field
dither) but ALSO `0xC6` (the d690 backdrop near-black pair), `0x54` (the ornate game-start fill), and
appears as the SOLID interior pre-fill of `thunk_box_thick` title outers (Frida src histogram: vertical
run 22 = solid, vs run 1 = dither). And a remap that walks the full dest RECT of a HOLLOW frame draw
touches everything COMPOSITED UNDER the frame, not just the frame's own pixels — a blanket shared-index
remap would have navy-striped every popup interior.

**Why:** the pair test is per-pixel, but pair MEMBERSHIP is a property of the art the pixel came from.
Only the unambiguous member (0xC4, 0xE0/0xE1, 0xAE/0xEE) identifies its family on sight.

**How to apply:** remap unambiguous pairs unconditionally; for a pair with a shared member, decide PER
BLIT by scanning the SOURCE small buffer for the unambiguous mate (e.g. enable 0x41/0xC4 iff #C4 >
srcW/2 in the first min(8,srcH) rows — genuine fields are ~50% mate; backdrops/solid fills are ~0).
Stash the src ptr alongside the dest geometry (`g_fe_src`) so the post-blit remap can scan it. This is
the same principle as [[feedback-frida-dedup-popup-reuse]] and the source-keyed listpitch fix: gate on
CONTENT, not on site/window identity. Evidence method: per-pair pixel count + MAX VERTICAL RUN histogram
of every enlarged src (hook_dither_map.js) — run ≤2 everywhere = pure dither, a run ≥3 = solid region
that a remap would corrupt. Shipped as `thunk_fe_pair_remap` (build c592d318). See
[[project-smac-filedlg-dither-synthesis]], skill scaling-frames §7b.


**Addendum 2026-08-29 (chassis picker, 1600×1200):** a detected pair also needs a CANONICAL top member. Ordering by histogram majority or first-seen row is phase-dependent on an NN-enlarged 1:1 dither, so adjacent rects restriped from their own content landed on opposite duty cycles (1/3 vs 2/3 light) — visible as lighter/darker squares at every odd P. Law `pair_top` in scaling_laws.py (force-pair key, else higher peak channel); `stripe_top`'s wide band always carries that member. See [[project-smac-design-workshop]].
