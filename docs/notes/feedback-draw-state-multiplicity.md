---
name: feedback-draw-state-multiplicity
description: THE recurring SMACX failure class — a UI element is never ONE draw; enumerate ALL states/variants/paths (state sprite arrays, hover/pressed, animation loops, inline rebuilds, per-frame recolors, sibling creation paths) BEFORE fixing, or the fix covers only the variant you happened to observe
type: feedback
---

**The class (named 2026-07-06, after it recurred on nearly every menu touched):** a fix built from observing ONE rendering of an element silently misses the
element's OTHER renderings. The game re-draws the "same" element through different sprites, sites,
paths, or colorings depending on interaction state, animation phase, or rebuild trigger — and each
variant fails the same way the observed one did.

**Why:** the engine branches per state/phase at the DATA level (sprite arrays, per-frame palettes)
and the CODE level (duplicate sites, inline rebuild blocks), so a hook/gate/pair keyed on the one
observed variant is structurally blind to the rest. Every burn looked "done" at first verify.

**The five known mechanisms (each burned us at least once):**
1. **State sprite ARRAYS** — one FlatButton = 3 band sprites (idle 0x7d059c 92/C8, hover 0x7d05c8
   E6/E7, pressed 0x7d05f4 63/66); v1 hardcoded idle's pair → pressed stayed banded (e638e7b8 fix).
   State sprites sit at ARRAY STRIDE from each other (here +0x2C) — found one, probe its neighbors.
2. **Animation/slide loops draw through their OWN sites** (different dest buffer + coord space than
   the settled sites) and the CLOSE animation has its own set again — [[feedback-animation-loop-draw-sites]].
3. **Inline REBUILD paths** in command/event handlers re-create the element natively, bypassing
   build-site hooks; sibling CREATION paths read the same field at other offsets —
   [[feedback-scaling-inline-rebuild-paths]].
4. **Per-frame RECOLORS** — turn.flc flash frames repaint the identical layout with a DIFFERENT
   dither pair each frame; any hardcoded pair covers exactly one frame.
5. **The hide/hidden TWIN** of a draw function (census sprite xrefs including the hide twin).

**How to apply — the STATE CENSUS rule (now also in skills frida-tracing + scaling-frames):**
- Before designing a fix, enumerate the element's variants and capture EACH in the census run:
  hover it, PRESS-AND-HOLD it, release off-element, let it animate, open/close it, select/refresh
  it, let it flash. One run, all states.
- Build probes so variants can't hide: dedup on CONTENT (a sampled row/signature), never on
  dims/site alone — same-size different-art states alias under a dims key (the v2 census fix that
  exposed the pressed sprite). Sibling of [[feedback-frida-dedup-popup-reuse]].
- Statically: census EVERY xref to the sprite/primitive (settled + animation + hide) and byte-scan
  the whole handler for every read of the field being scaled.
- Prefer PER-DRAW DERIVATION over per-variant constants: detect the dither pair from the source
  rows at draw time (restripe wrappers), derive sizes from the live scale — then unobserved
  variants are covered by construction instead of by enumeration.
- Verify protocol must exercise the states too (a private note): "verified"
  means seen idle + hover + pressed + animating, not a screenshot of the settled look.
