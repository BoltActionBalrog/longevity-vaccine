---
name: project-smac-music-fix
description: Game music under movies + over the main menu — CLOSED 2026-10-04, uimod.dll 301632d1; how the engine's music and sound-manager suspend work
type: project
---

CLOSED 2026-10-04, uimod.dll 301632d1 (exe unchanged 54a505ec), user-verified in game, committed + pushed.

Two causes, both DLL-only fixes:
- **Music under a movie**: the native movie routine `set_video_mode` 0x4BEA50 suspends the sound manager (0x90D978; 0x4C4FC0 / resume 0x4C4FD0, or pause 0x4C51D0 / unpause 0x4C51C0 when `8BitMovieSound` != 0). PRACX's hook and our `uimod_PlayMovie` replace that routine, so the calls never ran. NOT an updater regression: the gap dates from the first in-process player. Fix = `GameSoundHold` in movie.cpp (same calls, same pref) + `timeBeginPeriod(1)` because suspend stops soundx.dll's timer, which was what kept the timer resolution raised for the frame loop's Sleep.
- **Music over the main menu after leaving a game (BASE-GAME bug, user confirmed on pristine)**: `g_music` 0x74DAA0 is destroyed only at the top of `load_music` 0x4457E0 and by the Music pref toggle. Fix = musicfix.cpp: `call DesignWin_reset` at 0x58EFF5 (first call in `desktop_close`) -> stub that does `(*vtbl+8)(1); g_music = 0`. Hooked inside desktop_close so Thinker's control_game replacement is covered too.

Engine facts worth keeping: soundx.dll plays on its own threads + a 15 ms multimedia timer (music never depends on the game thread); pause/suspend are flag-gated, not refcounted; sounds requested while suspended are queued in a 256-slot ring and drain on resume; the music "tick" is `input_callback` 0x4457C0, called from WinProc on input. Vanilla's movie loop DROPS all window messages; our `Pump()` dispatches them.

Residue is in the maintainer's work log. Test: work\tests\test_musicfix_sites.py. See [[project-smac-movie-player]], (a private note).
