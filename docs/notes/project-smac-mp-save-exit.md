---
name: project-smac-mp-save-exit
description: Multiplayer/hotseat SAVE quits the game — NOT a crash, NOT our patch: it's a clean intentional ExitProcess after a successful save (base-game MP save-and-exit). Repros on pristine.
type: project
---

# "Multiplayer save crash" = base-game save-and-exit (NOT a crash, NOT our patcher)

**2026-07-04.** User reported the game "crashing" when saving a hotseat/multiplayer
session (to reload for debugging). Investigated with Frida crash-catcher
`work\scripts\hook_savecrash.js` (AV handler + teardown hooks on ExitProcess/
TerminateProcess/RtlExitUserProcess/MessageBox/CRT-exit + `save_game`/`FileDlg_save_modal`
brackets + WriteFile size logging). Result (`work\frida_savecrash.log`):

- `save_game` (0x5A9EB0) ENTER → file picker (`FileDlg_save_modal` 0x613D50) → **6 WriteFile
  calls (~250 KB) write the full save** → `save_game` returns **eax=1 (SUCCESS)**.
- THEN, at saveDepth=0 (save already finished), the game calls **ExitProcess** via the CRT
  `doexit` → `call dword [0x66918c]` (ExitProcess IAT) at **VA 0x644ec4**. Clean exit(),
  NOT an access violation, NOT the draw-buffer fatal branch, NO MessageBox.
- Save file on disk is complete + header-valid (`54 45 52 52 41 4E 00 1A` = "TERRAN") and
  **reloadable** — the debugging goal is met by just loading it.

**It is the underlying game (repros on pristine cc659f too — user-confirmed).** None of our
thunks are in the path (our caves are pcave2 @0xA0C000; the exit is stock CRT + base-game
logic). This is SMAC's intended **multiplayer save-and-exit** (the "Do you really want to
WIMP OUT of this multiplayer game?" context / PBEM-hotseat turn hand-off: the save IS the
pass mechanism, so the game exits after writing). Assessed high-confidence "by design" from:
clean exit after SUCCESS + MP-only + the wimp-out quit context. Did NOT trace the exact
`if(multiplayer) exit()` gate (14 `save_game` callers 0x5149f9…0x5284aa; the exit is
downstream in the MP quit/turn loop, not immediately after the save call) — not worth it.

**Workaround for iterative UI-scaling debugging:** save/reload in SINGLE-PLAYER (SP save does
NOT exit), or accept the exit and reload the valid MP `.SAV`. Autosaves (`saves\auto\*.SAV`)
are also written without exiting.

Tooling left in place: `hook_savecrash.js` (reusable crash/teardown catcher — Frida 17 needs
`resolveExport()` not the removed `Module.findExportByName`; re-enumerate modules at fault
time for late-loaded DLLs). The 4 launcher "SMACX Frida Trace" shortcuts were repointed to it
(repoint back to the real trace hook before UI-scaling Frida work). Also made
`hook_wimpout.js` (probe for the two OPEN WIMP-OUT modal UI defects — see below).

## RESOLVED 2026-07-04 (both defects closed by the a4ceb34b lock — see [[project-smac-popup-interior-stripes]]; kept as historical record)
`refs\MangledSmacx.png` vs `refs\pristine\Multiplayer\Quit.png` (the in-game MP quit popup):
1. Option-row bars overflow the modal on the RIGHT + are wider than the OK bar. Suspect
   `thunk_q16_fill_width` v2 `max(w·M(g)>>4, box_w−2x)`: WIMP OUT is the first type-16 popup
   whose box width is driven by the long PROMPT text, not the rows, so the rows take the
   `box_w−2x` arm (with the recorded q8 asymmetric-margin overrun) while OK stays at `w·M`.
   The v5 lock note flagged this case "verify". Vanilla law: rows == OK width, symmetric.
2. Body interior reads pure black @4K. It's device-density 1px dither (the ⅔-downscaled 4K
   shot averages the navy/black pair to (6,6,8)). Cause (static-confirmed): titled + no-art +
   non-faction popups (WIMP OUT / Planetfall / DPLAYERROR class) route the body-inner d528
   frame through `thunk_pf_frame_align` (gate g>16 & esi≠0x9403e0 & [+0xa14]==0 & [+0x2144]==0,
   both branches tail `push 0xA0CE00;ret` = `thunk_box_thick_devfill` STEP2 = fill dither at
   DEVICE res). SP Quit looks right because its art sprite skips the class. Should scale the
   scanline like the title band (~2.5px @4K), not device-1px. Strip ABOVE the title band is a
   separate pure-(0,0,0) anomaly. Probe `hook_wimpout.js` ready (never run — pivoted to crash).

Related: [[project-smac-popup-chrome]], [[project-smac-quit-type8-optionlist]],
(a private note).
