---
name: project-smac-basewin-uniform-pitch
description: Base screen tiny repeated cells (NUTRIENTS storage rows, NUTRIENTS/MINERALS/ENERGY intake-bar pips): one device pitch per grid instead of per-edge floor; CLOSED exe b67475a1 user-verified all resolutions 2026-09-21, committed
type: project
---

**Symptom (user 2026-09-20/21, big bases at non-4K):** alternating light/dark blocks in the NUTRIENTS storage box; uneven pips in the three intake bars. First mis-logged as dither banding; it is LAW A ([[feedback-remainder-distribution]]): the features are 1 native px (cell p-1 + 1-px gap, p = 2), and thunk_bw_fill2 / thunk_bw_tile2 floor each edge, so sizes run 1,1,1,1,2,2,2,2 at 25/16. Vanilla is even by construction (integer pitch). 4K is clean (2.5 = exact halves) — judge at g=22/25.

**User decision:** option A = UNIFORM beats proportionate for these grids: one integer device pitch `P = min(half_down(p*g,16), fl(avail_dev / count))`, filled part `max(P - stroke_width(g), (P+1)>>1)` (< P), grid re-centred (nutrients) / anchored at pt(x0) (bars). At g=22 a pitch-2 grid becomes 1+1 px and ~27 % shorter than vanilla x g/16; accepted.

**Where:** laws `scaling_laws.nutgrid_layout` / `pipbar_pip`; assemblers `assemble_nutgrid.py` (pcave2 0x1CBA0..) / `assemble_pipbar.py` (0x1CD30..); Unicorn parity `tests/test_nutgrid_asm_parity.py` / `test_pipbar_asm_parity.py`. Site-keyed thunks read the painter's ebp frame: BaseWin_draw_nutrients (0x411240) pitch [ebp-0x28], rows [ebp-0x2c], row index [ebp-0x44], area [ebp-0x50]/[ebp-0x48] (sites 0x411611 / 0x41163F fills + ring 0x4116A5; pitch >= 8 is the Buffer_tile_2 path and already lawful 1-px parity); BaseWin_draw_expenses (0x412AA0) pip pitch = esi at all 18 pip sites, bar start x0 = [ebp-0x20] (Buffer_write_l_4's return, native), bar = 0xC2 px (`0xC2/p + 1` pips); a pip off the bar's native grid falls back to the plain edge law.

**Shared bar start (b67475a1):** the bar's x0 is a MEASURED text end; '013 - 000' vs '008 - 004' differ by a device px in the scaled font and the native round-trip (ceil down, floor up) doubles it -> MINERALS sat 2 px right. `g_bw_pip_top` + law `pipbar_top`: a bar within `pipbar_snap(g) = (g>>4)+2` device px of the last bar's start reuses it. The jitter predated the pip work.

**How to apply:** any other repeated sub-3-px cell grid on a scaled screen has the same disease — look for blocks of period ~12 px at 1600. The scaling_laws guard test rejects the literals 1600/1920 anywhere in the module, comments and addresses included. Borderless captures are the game stretched x1.8/x2 by the GPU scaler: recover game pixels by centre sampling (validated: a parity portrait recovers as all-1 runs) — exact-colour detectors need Fullscreen shots.
