---
name: project-smac-uimod-dll
description: The C++ addon-DLL half of the hybrid architecture — where it lives, how to build it, current step
type: project
---

Hybrid binary-patch + DLL architecture (see [[project-smac-uimod-architecture]], brief at
`work\DLL_PORT_BRIEF.md`): the DLL half is a C++ project at **`src\uimod\`** (named subproject under
the repo's top-level `src\`, leaving room for a later `src\bootstrap\` exe-hook + `src\shared\`).

**Status (2026-06-23): Step 1 DONE — thinnest bootstrap builds + verified x86.** Output `uimod.dll`,
a do-nothing `DllMain` that announces itself via `OutputDebugString`. No injection/hooking yet.

- **Build system = native Visual Studio project** (`uimod.sln` + `uimod.vcxproj`), so the source can be
  edited/built/debugged in the VS2022 IDE directly (user's preference, 2026-06-24). CMake was REMOVED to
  avoid two drifting build systems. `build.bat [Debug|Release]` runs MSBuild on the SAME `uimod.vcxproj`
  the IDE uses (MSBuild at `…\MSBuild\Current\Bin\MSBuild.exe`; nothing on system PATH). Output
  `src\uimod\build\<Config>\uimod.dll` (`build\` + `.vs\` + `*.vcxproj.user` git-ignored).
- **x86 is mandatory** — terranx.exe is 32-bit; verified built DLL PE machine = `0x014C`. The project
  defines ONLY the Win32 platform (no x64), so the IDE can't build the wrong bitness. Toolset v143,
  Release links the static CRT (`/MT`) so the DLL has no VC++ redist dependency in the game dir.

**Entry point (2026-06-23):** `extern "C" void __stdcall Init(HMODULE)` in `src\uimod\src\init.cpp`,
exported as **ordinal 1** + name "Init" via `src\uimod\uimod.def`. `__stdcall` is load-bearing — the
loader does `push hMod; call Init; …; ret`, so Init must pop its own arg. `DllMain` stays minimal;
`Init` is the real entry the bootstrap loader calls after PRACX.

**Bootstrap design (owner decision 2026-06-23): ONE dll supports BOTH PRACX exe (now) + native ACX
(future).** Two separate "is PRACX present?" checks:
- **Load TRIGGER = patch-time, per target** (placement differs, can't be one runtime check): PRACX exe
  → CHAIN off PRACX's stub (replace `ret`@0x668189 with `jmp` to our pcave2 loader thunk = last-writer);
  native exe → install our OWN loader stub as a startup-table entry the way PRACX does (FUTURE, additive).
  See [[project-smac-pracx-load-mechanism]].
- **PRACX COOPERATION = runtime in the DLL**: `Init()` does `GetModuleHandleA("prax.dll")` → cooperative
  vs standalone mode.

**Bootstrap DONE 2026-06-24 (live MD5 ccc1bed5).** patches.yaml group `uimod_bootstrap`:
pcave2 `thunk_uimod_loader` @0x19C0 (41B mirror of PRACX's stub for "uimod") + site replacing PRACX stub's
terminal `ret`@0x668189 with `push thunk_uimod_loader; ret` (detour_inplace). Used push/ret not `E9 jmp`
(patcher's rel32 resolver requires a preceding E8). Fixed `apply_patches.py` VaResolver to bound sections by
max(VirtualSize,SizeOfRawData) so a SITE resolves in the _SELFMOD file-only zone (past VirtualSize 0x415d)
where PRACX's stub lives. uimod.dll deployed to game dir beside prax.dll (manual; NOT auto-deployed yet).
Verification: DLL-LOAD confirmed via uimod.log (Init + "PRACX detected -> cooperative mode"); owner
separately confirmed the game reaches the main menu + is playable. (Initial "in-game verified" was an
overclaim from reading uimod.log alone via an unattended launch = load, not playability — see
(a private note).) Layer-1 tests green (103; 117 sites). Res-independent (no multi-res
sweep). No CHANGELOG (do-nothing DLL, not player-visible).

**NEXT:** (a) confirm Init can READ PRACX runtime state / HOOK one game function; (b) port one existing
simple fix into the DLL to evaluate ergonomics; (c) FUTURE native-ACX loader (own startup-table entry,
additive). Binary-patch corpus + MD5 harness stay (hybrid, not rewrite).
