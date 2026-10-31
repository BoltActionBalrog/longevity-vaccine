---
name: feedback-uimod-shared-dll-gate
description: uimod.dll is SHARED by the pristine AND PRACX exes — every DLL feature that touches patcher artifacts (cave VAs, baked thunks, registry slots) must gate on their presence or it crashes the pristine game
type: feedback
---

uimod.dll loads into BOTH targets: the patched `terranx_PRACX.exe` (full cave + thunk
set) AND the pristine `terranx.exe` (group `uimod_bootstrap_native`; only the pristine
group set — NO `.pcave2` section, NO baked thunks, NO vtable repoints).

**The 2026-07-12 incident:** the Longevity prefs-tab module byte-checked its two CODE
patch sites (identical bytes in both exes → checks passed) and then wrote its cave
registry slots at 0xA17120+ in BuildWidgets. On pristine, 0xA17xxx is unmapped → AV at
desktop_init = "crashes when trying to enter the game." It first looked like a
save-format change — the real cause was the SHARED DLL touching a patcher artifact that
only exists on one target.

**Why:** a byte check on the PATCH SITE does not discriminate the exes — vanilla code
bytes are identical in both (PRACX only changes its own sites). Only the patcher's
ARTIFACTS distinguish them.

**How to apply:** every uimod.dll feature that references anything the patcher creates
(cave addresses in `.pcave2`, `menu_strip_thunks` content, baked vtable repoints,
registry slots) must gate on the artifact's PRESENCE at Init/install time and
self-disable with a log line otherwise. The proven gate: parse the exe's section table
for `.pcave2` and require the needed VA range inside it (`Pcave2Present()` in
`src\uimod\src\prefs.cpp`). Features meant to work on BOTH exes (movie player) must not
reference cave VAs at all. Test BOTH exes' uimod.log after any DLL change: the pristine
run must show the feature's "disabled" line, not silence.
