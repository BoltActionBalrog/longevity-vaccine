---
name: feedback-wrap-width-desync-line-step
description: A constant wrap-width delta causes a VARIABLE height error (word-wrap is a step function) — measure and draw must wrap at the SAME width
type: feedback
---

When text is word-wrapped, the MEASURE pass (which sizes the box) and the DRAW pass must wrap at the
**identical pixel width**. If a scaling thunk narrows one side only, word-wrap turns that *constant*
width delta into a *whole-line* height step: a quote with a line ending inside the delta renders one
MORE line than the box was measured for, and that line overflows the frame. Every other quote is
unaffected. So the symptom is a **variable** vertical overflow that appears on one element at one
resolution — from a **constant** horizontal delta.

**Why:** width → line-count is a step function, not linear.

**How to apply:**
- Never falsify a width-desync hypothesis with "a constant N-px delta can't cause a variable N-px gap."
  That reasoning is wrong and cost a full session on the SMACX faction quote box (`Yang overflows at 4K
  only`). Check line COUNTS (`drawBottom = y_in + N*lineheight`), not pixel deltas.
- Fix the side that is NOT faithful to `vanilla × g/16`. In SMACX the DRAW's inset (`3 × g/16`) was
  correct; widening it to match the measure shoved text into the right border. The MEASURE was wrong, so
  mirror the draw's narrowing onto the measure. See [[feedback-proportionate-scaling]].
- A thunk's Y/X/width deltas ARE the layout law. Derive dependent constants from the thunk's own bytes,
  never fit them to 2 sampled resolutions — a 2-point fit through g=40/25 silently breaks at g=22
  (1920×1080). Check the fit is exactly 0 at g=16 (native no-op) as a sanity gate.
  See [[feedback-loores-gate-on-g]] and [[project-smac-popup-scale-derivation]].
- Ground truth: hook the wrap primitive and the draw, and require `measW == drawW` per draw. Shared
  globals (e.g. `g_popup_body_bottom` 0x9B8CE8) are clobbered by other windows — never read them as a
  per-element bottom. See [[feedback-frida-trace-rect-and-sprite-capture]].

SMACX specifics: `Buffer_wrap_height_flying` (0x5DDDA0) arg2 `[esp+8]` = wrap budget →
`g_wrap_width_budget` 0x9B3A98. `BasePop_calculate_dimensions` builds it as
`[+0x30bc] − 2*[+0x30e0] − [+0x21c8] − [+0x30d8]`. Details in [[project-smac-faction-quote-box]].
