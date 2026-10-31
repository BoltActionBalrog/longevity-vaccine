---
name: project-smac-bandmap-overrun-crash
description: DISPROVEN 2026-07-18b — the ESC-quit AV was NOT a bandmap exact-fill overrun; real cause + fix in [[project-smac-stale-scale-float-crash]]. Kept as a don't-retry record
type: project
---

**DISPROVEN — do not act on the theory this file used to contain.** The 2026-07-18 ESC-quit
AVs were attributed here to thunk_bandmap_blit's exact-fill dstW growth reading source index
srcW. That was wrong on every point:

- The stack "frame" 0xA0F14F was a stale dword inside Buffer_draw_2's uninitialized locals,
  not a live return address.
- thunk_bandmap_blit cannot overrun (bm_axis clamps the middle phase; bands are built
  in-range for the GROWN dstN), and its fallback thunk_keyed_stretch_blit is Buffer_copy_3 =
  GDI StretchBlt, which clips. The planned safe_expand_width law + last-col/row replication
  fix is unnecessary — never implement it.

Real root cause (vanilla stale-scale-float reject bug) + the applied fix (76bb1956, group
scale_ratio_uncache) + the stack-walk lessons: [[project-smac-stale-scale-float-crash]].
