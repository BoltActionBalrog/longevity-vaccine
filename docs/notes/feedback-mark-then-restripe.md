---
name: feedback-mark-then-restripe
description: Regenerating a dithered surface after an engine enlarge you don't want to model — mark the pair in the NATIVE source with an unused palette index (0xFD magenta), let the engine blit, then rewrite marks over the dest rect at device density; also lists what fe_pair_remap must NOT be pointed at
type: feedback
---

**Rule.** When an enlarged surface bands (2/1/2/1 runs at g=22/25) and the enlarge is an engine
primitive whose sampling you would otherwise have to model (rail_slide_in's Buffer_draw_2 of the
console_x rail strip, 2026-08-15): do NOT model the blit and do NOT run `fe_pair_remap` blindly.
Pattern that worked (thunk_rail_bake v2, law `rail_channel_pixel`):
1. pass 1 over the NATIVE source: rewrite every pixel of the dither pair (41/C5) to a MARK index
   that never appears in art — 0xFD = palette 253 pure magenta, the pcx key colour;
2. call the engine blit untouched (callee-clean CALL: pop the ret into a global, `jmp [ret]` after);
3. pass 2 over the dest rect (over-cover is safe — only the mark is touched, clipped to canvas):
   mark → pair-top on stripe-top rows / pair-bottom below, same phase grid `P=(g+4)>>3` as fe.

**Why:** "measure the engine, don't model it" — the mark survives whatever NN/centre-aligned
sampling the primitive does, so geometry is never guessed; the survivor set IS the measurement.

**How to apply:**
- Before reaching for `fe_pair_remap` on a NEW surface, census which of its families the surface
  contains as SOLID art: the console rail strip carries vertical AE guide lines and fe's
  unconditional AE/EE family would have dashed them; 0xF0 is solid console art too. Wrong tool.
- Every visible STATE has its own pair: sb arrow normal = F0/B9, hover chevron = A2/EF, arrow
  FACE background = C2/C5 (194/197, distinct from the bar's 41/C5 trough). Census per state
  ([[feedback-draw-state-multiplicity]]); RLE the columns of the shot at g=22, don't eyeball —
  "stone texture, deliberately untouched" was a wrong call hidden by 4K phase alignment.
- Wheel scrolling on rail bars is a PRACX WndProc limitation (posts VK_UP/DOWN unless map shows),
  not a patch defect — don't chase it.
See [[project-smac-picker-scrollbar]] 2026-08-15b, [[feedback-dither-no-resample-on-upscale]].
