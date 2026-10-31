---
name: project-smac-riot-defection-fix
description: VANILLA crash in drone_riot's base-defection block (uninitialised REVOLT weights -> idiv 0) + inverted REVOLT roll; uimod riotfix.cpp, DLL e0bde654, USER-VERIFIED 2026-09-20, not committed
type: project
---

**Status 2026-09-20:** built + deployed (DLL **e0bde654**), USER-VERIFIED 2026-09-20 (heavy testing with and without the Free Drones; log + Windows event log clean), CHANGELOG Fixes line added, COMMITTED+PUSHED fc72282. Emulation: work\tests\test_riotfix_parity.py reproduces the vanilla fault on the pristine bytes. Details in the maintainer's work log.

**Bug (base game, both exes):** drone_riot 0x4F4FB0, defection block from 0x4F5553 (every entry jumps to that address). Seven per-faction REVOLT weights at [ebp-0x58..-0x40] are never initialised — the loop's "-1" store is `mov [ebp-0x3c],-1`, one fixed slot past the array. P = ftol(100 * prod(1 - w/100)) is therefore computed from stack garbage; roll r = timeGetTime()%100; weighted pick = (timeGetTime()/100) % sum(weights). No REVOLT faction in the game (stock: only the Free Drones, drone.txt REVOLT 75) -> sum 0 -> 0xC0000094 at 0x4F5633 whenever garbage P >= r; otherwise the base silently goes to the nearest foreign faction (why it looked random to the maintainer). Roll was also inverted (pick ran when r <= P = the NO-poach chance): REVOLT 75 gave ~26%.

**Fix:** site detour sets the 7 slots to -1 (both consumers skip -1; 0 would behave the same) + `jl`->`jg` at 0x4F561D (pick when r >= P). With both, no-REVOLT games can never reach the division. v2 also replaces the raw `call [timeGetTime]` @0x4F55F9 (the block's only randomness: r = t%100, pick = (t/100)%sum, read SIGNED) with RiotRoll() = rand()%100 + 100*rand() via the C runtime rand 0x64601D that drone_riot already uses. In vanilla a negative clock (uptime > 24.8 days) ALWAYS takes the weighted pick (r <= P) = certain crash without a REVOLT faction; An initial reading had this backwards; the emulation corrected it. User explicitly approved the gameplay change ("the game did not play as designed for this quarter century").

**Why:** user crash ending a turn while testing [[project-smac-punishment-sphere]]; unrelated to our patches (drone_riot bytes identical live vs pristine). Thinker removed the event ("issues with the original code"). Reach conditions: 2nd+ riot turn, police roll, not HQ/recent capture, >1 base, facility-destroy loop exhausted, SE police < -2, human non-alien owner.

**How to apply:** an "intermittent end-turn crash" with fault offset 0xF5633 is this. Lesson: a crash that "sometimes works" = look for uninitialised locals feeding a guard, not just the faulting divide.

**Thinker:** riotfix is INERT there — Thinker's upkeep (write_call 0x527039 -> mod_base_upkeep -> mod_base_drones -> mod_drone_riot, in thinker.dll) never calls vanilla drone_riot, and its riot has no defection event at all. thinker.dll exports only ThinkerModule. Decision (accept vs reinstate) is item 4 of the pre-release Thinker sweep in the maintainer's work log.
