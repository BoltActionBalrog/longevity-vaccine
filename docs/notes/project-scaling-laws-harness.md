---
name: project-scaling-laws-harness
description: work/scripts/scaling_laws.py = single source of truth for scaling arithmetic; swept by tests/test_scaling_laws.py + guarded by test_scaling_law_guards.py + golden vectors — run BEFORE any frame/layout change
type: project
---

# Scaling-law reference + harness (built 2026-07-09)

**`work\scripts\scaling_laws.py` is the SINGLE SOURCE OF TRUTH** for the scaling arithmetic.
`hook_*.js` and the baked cave thunks are PORTS of it. If a port disagrees, the port has the bug.

- `half_down(a,b)` = round(a/b), exact halves DOWN (4K stroke is 2px; half-up would give 3).
- `stroke_width(g)` = K from the LEVER only (signature guarded — must take `g` and nothing else).
- `cum` / `distribute` = remainder distribution ([[feedback-remainder-distribution]]).
- `row_positions` = repeated stride without accumulated floor.
- `band_widths` = chrome cells 0 (stroke) + 1 (bevel) pinned to K, remainder over inert cells.
- `axis_map` = the 9-slice band-map enlarge (near/far bands mirrored, middle keeps engine NN phase).
- `ring_bottom` = chrome-follows-content (g=16 reduces to vanilla ALGEBRAICALLY).

**`work\scripts\scaling_laws.js` is the ONE JS port** — a Frida prelude publishing `globalThis.SL`,
loaded for every hook by `run-frida.bat` + `run-at-resolution.ps1` (alongside `frida_common.js`).
Hooks must call `SL.*`; a private copy of the math is a test failure
(`test_hooks_do_not_carry_a_private_copy_of_the_math`). `hook_frame9.js` used to carry one.

## Run these before touching the game

    cd work\tests
    py -m pytest test_scaling_laws.py -q        # ~5,280 assertions, <25s, no game launch
    py -m pytest test_scaling_law_guards.py -q  # process tripwires
    py -m pytest test_scaling_js_parity.py -q   # JS prelude vs Python, 24,150 cases (needs node)
    py -m pytest test_bandmap_asm_parity.py -q  # BAKED x86 vs Python under Unicorn (needs keystone+unicorn)

`test_bandmap_asm_parity.py` emulates the REAL assembled bytes of `bm_axis` (from
`scripts\assemble_bandmap.py`) and diffs its output buffer index-for-index against `axis_map`,
across g in [17,40] x n in {3,6,8,44,61} x 9 spans. Use ONE Uc for the module — a fresh instance per
case maps 3MB and ~1000 cases hard-fault the process. pytest's faulthandler prints "Windows fatal
exception: access violation" from Unicorn's softmmu; it is NOISE (exit code 0, tests pass).

- `test_scaling_laws.py` — exhaustive sweep over g in [16,40] x band depths x spans.
  Every assertion names the on-screen defect it prevents.
- `test_scaling_law_guards.py` — guards the PROCESS, not the arithmetic: source-of-truth exists,
  `stroke_width` signature takes only `g`, g=16 is the identity, no screen literals in the
  reference, `hook_frame9.js` still references the fe_pair_remap epilogue + g_fc_exact, golden
  vectors pin the approved 4K look, both skills name the module and the sweep.
- `tests\golden_scaling_vectors.json` — frozen output at REAL draw geometry (from
  frida_frame9.log) at frames the maintainer signed off. Regenerate:
  `py work\scripts\gen_scaling_vectors.py --write` and REVIEW THE DIFF — every changed integer
  is a pixel that moves. The baked asm is verified against these integers, not against the JS.

**Mutation-verified 2026-07-09**: the guards catch all four realistic Python regressions (K from a
span/ratio, un-pinned bevel cell, naive `n*floor(stride)` rows, half-up rounding) AND all three JS
ones (half-up, un-pinned bevel, K from ratio).

**The parity test earned its keep on first run**: JS and Python disagreed by 1px in the middle-phase
clamp whenever `src == 2n` (bounds cross: `lo=n > hi=src-1-n`; Python's `min(max(s,lo),hi)` gave
`hi`, the JS ternary gave `lo`). 157/24,150 cases. Neither was right — there is no middle when the
bands overlap — so BOTH now require `src >= 2n+1` and return null otherwise (engine fallback).
Latent, not active: `n=61` (ornate picker corner) never draws at a 157px span. It would have gone
live the day someone reused the band map for a small ornate frame. No amount of 4K staring finds this.

Skills: **scaling-layout** (new: remainder distribution + chrome-follows-content + the vbase
field-addressing gotcha) and **scaling-frames** (now opens with the three non-obvious laws:
no uniform NN enlarge, K-from-lever + bevel pinned, EPILOGUE law).

## Bake acceptance oracle (before/after) — 2026-07-09

`scripts\hook_strokecensus.js` (OBSERVE-ONLY) + `scripts\check_stroke_census.py`.
The census attaches at `thunk_frame_enlarge` @0xA0F0A0 (onEnter saves ecx=scratch; onLeave reads the
`g_fe_dst/x/y/w/h` the thunk already stashes) and MEASURES each frame's real near/far stroke
thickness from DEST PIXELS. Then the checker judges: `near == far == stroke_width(g)`; exit 1 on any
violation; refuses to pass a log with no g=16 run (native no-op unverified).

- SHIPPED exe -> expect widespread wobble. AFTER bake -> expect 0. That flip IS the acceptance test.
- Run the census WITHOUT hook_frame9.js loaded (it must observe the shipped path).

**Never model the blit's src->dst mapping.** `thunk_keyed_stretch_blit` -> `Buffer_copy_3` @0x5D9610
dispatches through SURFACE VTABLES (`call [ecx+0x68]`, `call [edx+4]`), so the NN index map is NOT
statically derivable from our bytes despite the `= GDI StretchBlt` comment in terranx.h. A python
`floor(j*src/dst)` model agreed with two screenshots — corroboration, not proof. Measure the pixels.

See [[project-smac-frame9-enlarge]] for the frame9 prototype this came out of (still UNBAKED).
