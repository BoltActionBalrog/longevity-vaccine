---
name: project-smac-win11-24h2-fix
description: Windows 11 24H2 GOG Alien Crossfire freeze fix — SPINLOCK port of Thinker's CRT file-lock fix (group win11_24h2_filelock_fix), confirmed working on PRACX. 2026-07-04 ported to the PRISTINE exe too (group added to PRISTINE_GROUPS; pristine build 01bb80b0 = VERIFIED RELEASE LOCK, user in-game confirm, CHANGELOG'd, committed). CS-zero-init alternative FAILED and is disabled.
type: project
---

## >>> UPDATE 2026-07-04 — PORTED TO THE PRISTINE EXE (same flow as the cinematics loader) — CLOSED <<<
`win11_24h2_filelock_fix` added to `PRISTINE_GROUPS` in apply_patches.py (installer inherits — it reads
`ap.PRISTINE_GROUPS`). The 20 CRT sites and the 0x668200 `menu_strip_thunks` cave region are byte-identical
across the PRACX (2d0b1438) and pristine (cc659f) bases, so the group verified [ok] on cc659f unchanged.
Flow: restore game-dir pristine terranx.exe from .bak (cc659f) → `run-apply-patches --pristine --apply` →
new live pristine MD5 **01bb80b0** (== scratch rehearsal byte-exact); pytest 201 green. **VERIFIED
RELEASE LOCK 2026-07-04: user in-game confirm "It works great" on the pristine exe; CHANGELOG'd
(pristine-scope line) + committed.** LESSON: the pristine
build's MD5 DRIFTS whenever any pcave2/menu_strip_thunks content changes (whole-cave writes), even for
PRACX-only thunks — the live pristine was found at e8a6872f vs the recorded 529bee3d for exactly this
reason; always re-derive from .bak, never trust the recorded pristine MD5 across cave edits.

## >>> UPDATE 2026-05-31 — the SPINLOCK STANDS. Two false alarms cleared up: <<<
1. **The spinlock did NOT break audio.** earlier game audio seemed dead with the fix on; it
   was actually a **Windows per-app volume/mute setting** (the game was muted in the Windows mixer). The
   spinlock never touched audio. (Lesson: rule out OS mixer state before suspecting a patch.)
2. **The CS zero-init theory was TRIED and FAILED.** Hypothesis (from a half-remembered video + RE): the CRT
   mallocs the per-FILE `CRITICAL_SECTION` un-zeroed (`_getstream` 0x649778 `malloc(0x38)`, CS at `_FILEX+0x20`;
   `_iob` lazy-lock `FUN_00647d04` `malloc(0x18)`) so the **DebugInfo (CS+0) is garbage**, and 24H2 chokes on it.
   Built group `win11_24h2_cs_zeroinit` (`thunk_zero_init_cs` @ cave 0x900) to zero the CS before
   `InitializeCriticalSection` at the 2 ICS sites (`_getstream` 0x6497FC, `_iob` 0x647D41) WITHOUT touching the
   file functions. **Tested build 63df81b0 (spinlock OFF, zero-init ON) → freeze RETURNED.** So zeroing the CS
   at init is NOT sufficient: the 24H2 fault is in **using** the CRT per-FILE critical section, not just its
   init — which is exactly why the spinlock (which bypasses the CRT CS entirely) is the fix. The
   `win11_24h2_cs_zeroinit` group is left in patches.yaml **disabled** (status:skip) as a tried-and-failed
   record; its dead thunk bytes at cave 0x900 are inert. CRITICAL_SECTION x86 layout (for reference): +0
   DebugInfo, +4 LockCount, +8 RecursionCount, +0xc OwningThread, +0x10 LockSemaphore, +0x14 SpinCount (0x18).

**Current state:** spinlock `win11_24h2_filelock_fix` RE-ENABLED; build **344fa2f9** (= prior spinlock build +
inert dead bytes). PENDING: user to re-confirm the freeze is gone with the spinlock restored (the cs_zeroinit
test had the spinlock off, which is why it froze).

---
(the spinlock fix — the working approach:)

**The bug (external, NOT caused by our patches):** GOG *Alien Crossfire* (SMACX `terranx.exe`) crashes on **Windows 11 24H2** (build 26100). Symptoms: starting a single-player game → at colony-pod landing the engine drops into a stuck "HOTSEAT/EMAIL MULTIPLAYER — Set Password" prompt + garbage mission-year + units not placing, then freeze. Base SMAC works; only SMACX. Confirmed external by A/B test: it reproduces on the **clean PRACX `.bak`** (no patches of ours). Community workarounds (roll back to 23H2, Yitzi/Kyrub patches, Steam) are intractable for a redistributable patcher. See [[reference-smac-modding]].

**Root cause:** the statically-linked 1999 MSVC CRT's **per-FILE locking** (`_lock_file` @ `0x647C37`, `_unlock_file` @ `0x647C89`, called at entry/exit of the 10 stdio wrappers `_fwrite`/`_fread`/`_fclose`/`_fseek`/`_fprintf`/`_ftell`/`_fgets`/`_fgetc`/`_fputc`/`_rewind`) **faults on 24H2** when a savegame is written (the hot-seat turn-start writes a save). Thinker fixed this in **v5.0 (2025-05-02)**: changelog "Fix original game crash issues on Windows 11 update 24H2 that happened when the savegame was being written." Thinker's `patch.cpp` replaces the file locking with a single global `std::mutex` across **20 call sites** (10 lock + 10 unlock).

**Our port (works without Thinker's DLL/C++ runtime):** a self-contained **global spinlock** on one cave dword — `LOCK CMPXCHG` is a single instruction, no imports, no init (dword starts 0). Group `win11_24h2_filelock_fix` in `patches.yaml`:
- Cave thunks (in `menu_strip_thunks` @ base 0x668200): `filelock_lock` @ +0x290 (`push eax;push ecx;.spin: xor eax,eax;mov ecx,1;lock cmpxchg [filelock_var],ecx;jnz .spin;pop ecx;pop eax;ret`), `filelock_unlock` @ +0x2B0 (`mov dword [filelock_var],0;ret`), `filelock_var` @ +0x2C0 (dword=0). Both thunks are `__cdecl`, ignore the FILE* arg (global lock), preserve all registers (EAX/ECX push/pop; cmpxchg leaves EDX etc. untouched), non-recursive (matches Thinker's mutex; CRT funcs lock-at-entry/unlock-at-exit, no nesting).
- 20 sites redirect each `CALL _lock_file/_unlock_file` → `filelock_lock/unlock` (symbols `crt_lock_file`/`crt_unlock_file` capture the original targets for verification). Site VAs (lock): fclose 0x6455AE, fwrite 0x646046, fread 0x64617F, fgetc 0x64685C, fputc 0x64688D, fgets 0x647283, rewind 0x6472D6, fseek 0x647337, fprintf 0x64781D, ftell 0x647927. (unlock): 0x6455BC, 0x646061, 0x64619A, 0x64687B, 0x6468B6, 0x6472BF, 0x647325, 0x64734F, 0x647843, 0x647935.

**Status:** applied and **confirmed working in-game 2026-05-29** — single-player plays past turn 1, no hot-seat prompt. Current full-patch MD5 `27cb07f01e9272639d90afa7cc409c22` (menu scaling + window-height + this fix). The CRT region (0x645xxx–0x647xxx) is untouched by PRACX, so the addresses match the PRACX-GOG binary.

**GOG's 13-Nov-2024 update does NOT fix this (empirically confirmed 2026-05-29).** That update's "Win 10/11 compatibility" is purely *external* shimming — DDrawCompat (`ddraw.dll`, a DirectDraw graphics shim, incl. `CpuAffinity=1`) + a `HighDpiAware` compat layer. It touches ZERO executable bytes: GOG's bundled `terranx_PRACX.exe` is byte-identical to our pre-fix `2d0b14` baseline. User **ran `terranx_PRACX.exe` (with DDrawCompat active) and the hotseat freeze STILL reproduces** — so CpuAffinity=1 does not mask it and GOG's claim was about rendering/launch, not this CRT regression. Our spinlock fix remains strictly necessary and is the only thing that cures it. See [[project-smac-gog-update-report]].

**Coexistence:** the group is marked `skippable` — if another mod (Thinker, a static patcher) already modified these CRT sites, the patcher calmly skips this group and keeps the menu scaling. See [[project-smac-patcher-v02]] for the skippable mechanism.

Related: [[project-smac-ui-scaling]], [[project-smac-patcher-v02]], [[project-smac-menu-strip-scaling]], [[reference-smac-modding]]
