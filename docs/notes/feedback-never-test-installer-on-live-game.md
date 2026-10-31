---
name: feedback-never-test-installer-on-live-game
description: Never smoke-test install.py against the real game directory — always pass a scratch --game-dir
type: feedback
---

**When testing `work\scripts\install.py` or `run-install.bat`, ALWAYS pass a throwaway
`--game-dir` (e.g. `Z:\nope`, or a temp copy). Never let it resolve the real install.**

Why: with no `--game-dir`, `config.game_dir()` autodetects the live
`D:\GOG Galaxy\Games\Sid Meier's Alpha Centauri Planetary Pack`, and the installer then
*writes*: it deploys `uimod.dll` + the 5 ffmpeg DLLs, writes `[UIMod] UpscaledVideos`, and — with
`--no-wait`, because `ask_ai`'s `input()` hits EOF and defaults to YES — re-copies the 1.3 GB HD
pack. This happened on 2026-09-21 during a smoke test. Nothing was
damaged (every file was byte-identical to its repo source, the exe and `.bak` were untouched
because the exe was already patched), but it was an unintended write to a verified install.

**It happened AGAIN on 2026-09-27, through the RESIDENT updater:** an e2e test drove a throwaway
install's `LongevityMods\updater\scripts\run-install.bat --update --wait-pid <pid> --manifest <m>`
(the exact command the game's hand-off runs) with no `--game-dir`; `bootstrap.run` fell through to
`config.game_dir()` autodetection and generation 2 self-updated the REAL GOG install to a 9.9.9
test build (receipt + resident updater; exe/DLL unchanged). Root-cause fix: `config.resident_game_dir()` -- a copy living at
`<game>\LongevityMods\updater\scripts` resolves to ITS OWN game dir before any other source
(`test_a_resident_updater_resolves_its_own_game_dir`), and the DLL's hand-off now passes
`--game-dir` explicitly. Rule stands: any installer/updater invocation in a test gets an explicit
throwaway `--game-dir`, and a command that is "exactly what the game runs" is not exempt.

**The one deliberate exception:** the FIRST-INSTALL test is run on a live install, by the
maintainer, because a copy cannot exercise autodetection, the real launcher shortcut or the
game starting where it lives.

Related: (a private note).
