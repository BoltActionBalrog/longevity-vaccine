---
name: feedback-bake-port-fidelity
description: Baking a Frida prototype into cave thunks — the four ways a faithful-looking port diverged (Design Workshop bake v1..v1g, 2026-08-29) and the crash-diagnosis recipe
type: feedback
---

A bake is a PORT of a user-verified prototype; every divergence from the proto is a defect. The Design Workshop bake needed six follow-up builds, each a port-fidelity slip:

1. **Exec-scoped gates must stay exec-scoped.** The proto armed a button HIT range only inside `DesignWin_exec`; the bake made it static → the same buttons draw at game init (`DesignWin_build` runs from the static-window init at 0x58EEB7) → crash on save load. Bracket with a cell set by a ret-swap enter/leave pair.
2. **A reused thunk's TAIL is part of its contract.** `thunk_se_rowdraw` ends with `jmp SocialWin_draw_society_row` (the ORIGINAL slot method), not the default stub — reused for DW buttons it drew SE sprites relative to the wrong parent → `Buffer_load_pcx(-1)`. Read a thunk to its last instruction before reusing it; never stop a parity test at a thunk's ENTRY (run it to the return and compare output).
3. **Never add a gate the proto did not have.** An invented `flag&1` check in the Caviar FIT thunk (the engine's `test cl,1` is the OBJECT flag) silently dropped every icon draw. Every condition in a thunk needs a proto line to cite.
4. **A hook keyed on a DEST BUFFER covers every draw into it.** The proto's hollow_flat hook restriped all picker-canvas draws (cells AND the container); porting only the cells left the gutters banded. Enumerate the dest's draws (callers census), don't port from memory. Likewise a per-draw detected pair becomes a per-params-set pair (d528/d550/d578) in a thunk.

Also: hit tests that descale device coords must use the CEIL inverse of the half-down scale ([[feedback-floor-descale-roundtrip]]) — truncation drops a cell's first device pixel.

**Why:** each slip cost a user run + a fix cycle; all were catchable by reading the reused code to its end and by diffing the thunk's conditions/sites against the proto's.
**How to apply:** before baking, list every proto hook with (host, gate, dest, tail) and map each to a thunk 1:1; the parity test must drive every thunk to its return. When a bake crashes: WER Application event 1000 gives the fault offset → `_disasm_live.py` → `hook_savecrash.js` (ebp chain + raw stack), run via `work\run-frida-at-res.bat`, gives the frames; the strcat-under-`Buffer_load_pcx(-1)` signature = a sprite pointer computed from the wrong object.
