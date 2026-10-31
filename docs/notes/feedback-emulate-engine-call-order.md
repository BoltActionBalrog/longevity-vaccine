---
name: feedback-emulate-engine-call-order
description: An emulation harness must run the engine's draws in the engine's own call order -- a value read "at draw time" depends on WHEN the draw happens relative to later writers
type: feedback
---

When a thunk reads engine state at draw time, the harness must replay the engine's real call sequence, including
draws that fire in the middle of a builder, and must check the value the draw actually sees, not the final state.

**Why:** 2026-10-22: fixes 16/17 hugged the type-1 checkbox popup ring to the dialog rect D
(D.r = D.l + Dialog[+0x5c]). The harness ran calc -> calc -> attach (0x602B50..) -> background, so the draw saw the
post-attach [+0x5c] (the list width) and every test said "D is the bar". In the real game BasePop_exec_3 redraws the
popup at 0x602B49 (BasePop_on_redraw -> Popup_on_draw_background) BEFORE Dialog_set_type attaches the list at 0x602BFE,
so the ring read calc_reserve's measured text width and ended halfway across the rows at 4K -- the maintainer caught it in
game after deploy. Three independent reviewers passed it because they reused the same order. The harness had even
measured the two differing values (d5c_calc vs list_w) without asking which one the draw sees.

**How to apply:** before trusting an end-to-end harness, list every call in the real builder between the first writer
and the last reader of the field (xref the builder's CALLs, incl. vtable redraws), and run the draw at EACH point it
fires; assert the drawn value at every such point equals the law. A reviewer must independently re-derive the call
order from the bytes, never inherit the fixer's harness order. Related: the project rules "measure the engine; do not model
it", [[feedback-engine-nn-column-map]], (a private note).
