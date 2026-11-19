# uimod.dll — SMACX UI Mod addon DLL

The DLL half of the hybrid binary-patch + DLL architecture. Decision rule
(binary patch for small, MD5-lockable UI-math fixes;
this DLL for features needing code volume, last-writer-over-PRACX cooperation, or C++).

## How it loads

`uimod.dll` is loaded by chaining off PRACX's own loader stub (group `uimod_bootstrap` in
`work\patches\patches.yaml`). The chain is two-phase: the exported `PreInit(HMODULE prax)`
(ordinal 2) runs with prax.dll loaded but before PRACX's own init, to head off what that init
does irreversibly (its boot display-mode switch; the process DPI awareness); then PRACX
initialises; then the exported `Init(HMODULE)` (ordinal 1, `src\init.cpp`) runs as the
last-writer, detects PRACX via `GetModuleHandle("prax.dll")`, installs each module below and
logs to `uimod.log` beside the DLL. An exe baked before the two-phase chain calls only `Init`. Every module byte-checks the code it hooks
and disables itself with a log line when the bytes differ (another mod, another build).

## Modules

| Source | What it does |
|--------|--------------|
| `movie.cpp`, `caption.cpp` | In-process cinematic player (libav): plays the original `.wve` movies and the HD `.mp4` pack inside the game window, with a port of the game's post-movie caption. |
| `portrait.cpp`, `portrait_law.h` | Smooth leader portraits at enlarged UI scales: scanlines removed, Lanczos enlarge, scanlines regenerated at device density. |
| `vidmode.cpp`, `gpuscale.cpp` | Persisted Fullscreen / Borderless / Windowed display mode, with a GPU present for the stretched modes. |
| `vidsafety.h`, `vidwatch.cpp` | Display-topology safety for those modes: a monitor change (not a USB or work-area notice that leaves the monitors as they were, not PRACX's own mode switch) releases the pointer clip, topmost and the backdrop; they come back 3 s after the display settles, on the game's own monitor only (the game is never moved to another monitor by itself). A watchdog thread receives the display broadcasts (so the release happens even while the game thread is busy) and owns the escape hotkey (`[UIMod] EscapeHotkey`, default Ctrl+Alt+Shift+End). It only measures and logs the game thread's stalls and releases nothing on one: a long AI turn keeps the game thread busy for seconds while it draws. The way out of a game thread that truly hangs: the escape hotkey frees the pointer and hides the backdrop at once, but the window stays on top until the game thread runs again (leaving the topmost band is queued to it), so Ctrl+Alt+Del then Task Manager ends it. Window ghosting is off for the process, so Windows never swaps a busy game for a "not responding" copy. |
| `prefs.cpp` | The "Longevity Preferences" page in the game's Preferences window. |
| `update.cpp`, `update_core.h` | Update checker: runs the resident installer's `--check` as a hidden child and shows the in-game prompt. The update checker does no networking in-process and trusts nothing from the network. |
| `wheel.cpp` | Mouse wheel over lists and scrollbars, routed by what is under the cursor. |
| `rowindent.cpp` | Reply-row text indent scales with the UI. |
| `techwin.cpp` | Tech breakthrough window opens its text boxes at the top (original-game bug). |
| `pssphere.cpp`, `psbadge.h` | Punishment Sphere: shows the drones the sphere suppresses (display only). |
| `aivis.cpp` | AI perception filter: the AI no longer sees cloaked units it should not, and notices a cloaked or submerged unit that attacks it (original-game bugs). Also the Long Range Fire repairs: firing at an empty square no longer starts an artillery duel the firing unit cannot win, enemy artillery in range returns fire in a fair Artillery Duel with a message, and a hasty duel at reduced strength asks first (original-game bugs). |
| `blinkfix.cpp` | The selected unit's blink redraws its neighbouring tiles too, so a sprite wider than its tile (big ships) no longer leaves a solid sliver on the off tick (original-game bug). |
| `hudsync.cpp` | A resumed turn with a pending unit (a loaded game) enters move mode instead of the base game's half-selected view mode; the HUD unit panel's stored tile is synced to the unit the game waits on when it becomes current (original-game desync). |
| `viewdragfix.cpp` | In view mode (V) a drag no longer arms a move line that the release would not honour (original-game bug: it only selected the unit). |
| `hudmovesfix.cpp` | The HUD's "Moves" readout repaints when the engine gives up a go-to that has no route (original-game bug: it showed the pre-move count until the unit was re-selected). |
| `musicfix.cpp` | In-game music stops when a game ends (original-game bug). |
| `riotfix.cpp` | Drone-riot defection fix (original-game bug). |
| `leaderfree.cpp`, `leaderfree_core.h` | An AI probe team that frees a captured faction leader frees that leader, instead of resetting a living faction (often the player) to a colony pod (original-game bug), and the faction that held the leader is told so in its own words instead of "you liberated" them (original-game bug). Under Thinker Mod, which fixes the rescue in its own probe code, only the message is applied, pinned to Thinker 5.5. |
| `modernctl.cpp`, `praxdrag.cpp` | Modern Control Set (right-click to move, hover move-to line, Ctrl+right waypoints, Shift+right menu), the map drag-scroll button under PRACX, the camera options, and the Shift/Ctrl auto-repeat click fix (original-game bug). |
| `dragdelay.cpp` | The drag-move hold delay setting. |
| `mapscroll.cpp` | Smooth map scrolling under PRACX: each drag / edge-scroll step shifts the map canvas in place and re-renders only the exposed strips (the engine's filtered `MapWin_gen_map` through PRACX's wrapper, with our own strip rects), instead of PRACX's full redraw per step; the scroll's end settles with one full draw. |
| `debugdump.cpp` | Developer diagnostic: with `uimod_debug.flag` beside the exe, Pause dumps popup geometry to the log. Read-only. |
| `cursorscale.cpp` | The engine's map cursors (go-to, patrol, airdrop, artillery and the rest) at vanilla x g/16. |
| `lanjoin.cpp`, `lanjoin_core.h` | TCP/IP multiplayer between two PCs on one home network behind a router without NAT loopback (Windows' DirectPlay NAT-helper bug): completes the NAT helper's address query from the router's UPnP mappings. The DLL's only networking; Winsock is delay-loaded and never touched in single player. `[UIMod] DirectPlayLanFix=0` turns it off. |
| `mptimefix.cpp` | The multiplayer "No Time Control" readout no longer flashes black on a redraw (original-game bug). |
| `interludekey.cpp` | The keystroke that closes a story interlude no longer leaks to the map (original-game bug). |
| `portrait_files.cpp`, `prewarm.cpp` | Replaceable leader portraits from the `portraits/` folder and the HD pack: fail-closed decode of untrusted image files, cache, and a background pre-bake so a faction's first portrait does not stall. |
| `winlines.cpp`, `lineoverlay.h` | Lines the engine draws straight onto the game window, kept right while the frame is stretched into a client of another size. |
| `thinkercompat.cpp`, `thinker_sites.h` | The "apply after Thinker" pass for the PRACX + Thinker target: re-applies our patches over the sites thinker.dll rewrites (table generated by `work/scripts/gen_thinker_sites.py`). |
| `thinkeraivis.cpp` | The AI perception filter's and the Long Range Fire repairs' Thinker half (Thinker replaces the engine's unit planner). |
| `thinkertext.cpp` | Thinker's own base-screen text lines placed at our scale. |
| `thinkerversion.cpp` | The Thinker Mod startup check: when the game runs a Thinker Mod build other than the one this release is pinned to, one dialog offers [Update now] (starts the installer to install the matching Thinker and ends the game), [Not now] or [Don't ask me again]. Until then the parts of the DLL that touch thinker.dll stay off (reduced mode). |
| `rowarrowfix.cpp` | The base screen's unit-row scroll arrows are hidden when another screen takes the console, so the Design Workshop opened from a base no longer shows a stray, dead arrow (original-game bug). |
| `pracxfocus.cpp`, `pracxfocus_core.h` | PRACX's Preferences panel no longer leaves the map without its mouse wheel and drag scrolling under Wine (PRACX bug), and Esc closes the panel after one of its buttons was clicked. |

## Build

Open **`uimod.sln`** in Visual Studio 2022 and Build (F7), or build from the command line:

```
build.bat            # Release (default)
build.bat Debug      # Debug
```

`build.bat` runs MSBuild on the *same* `uimod.vcxproj` the IDE uses, so CLI and IDE builds
are identical. Nothing needs to be on the system PATH (MSBuild is sourced from the VS install).

- **Win32 (x86) only by design** — `terranx.exe` is a 32-bit process, so the DLL must be x86.
  The project deliberately defines no x64 platform, so the IDE can't build the wrong bitness.
- Release links the **static CRT** (`/MT`), so the DLL has no VC++ redistributable dependency
  when dropped into the game folder.

Output: `build\Release\uimod.dll` (or `build\Debug\uimod.dll`). Deploy it into the game
directory beside `prax.dll`; PRACX's chained loader then `LoadLibrary`s it at startup.

## Layout

```
src\uimod\
  uimod.sln              Visual Studio solution (open this)
  uimod.vcxproj[.filters] the project (Win32-only, DynamicLibrary, links uimod.def)
  build.bat              CLI build via MSBuild on uimod.vcxproj (identical to the IDE build)
  uimod.def              export table: Init @1 (+ strips the __stdcall _Init@4 decoration)
  uimod.rc               VERSIONINFO resource; takes its numbers from src\version.h
  src\dllmain.cpp        minimal DllMain
  src\init.cpp           Init(HMODULE) — the entry the PRACX-chained loader calls
  src\*.cpp / *.h        one module per feature (table above)
  src\version.h          THE product version (RC-safe #defines); mirrors work\scripts\version.py
  third_party\ffmpeg\    the slim LGPL ffmpeg: DLLs, headers, import libs (tracked; built by tools\build_ffmpeg_slim.sh)
  build\                 MSBuild output + .vs\ IDE cache (git-ignored)
```
