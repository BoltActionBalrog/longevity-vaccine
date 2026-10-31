---
name: project-smac-update-checker
description: In-game update checker: DLL prompt + installer flows, verified at 4K + 1600x1200; open = multiplayer manual checks, GOG overlay run, startup timing
type: project
---

**State (2026-09-27): USER-VERIFIED in-game at 4K + 1600x1200 (DLL 75f3c570), COMMITTED +
PUSHED.** Everything below except the multiplayer manual checks (the maintainer's work log) and the GOG-overlay
run passed. Manual test scenarios (base-real, offline, delay) are kept outside the repository.

**Earlier state (2026-09-27):** everything is CODED and unit-tested, NOTHING is in-game verified.
The plan carried the full user-flow accounting F1..F8.
Engine facts from the read-only disassembly: `work\_upd_disasm.md` (C1..C6; symbols recorded in
`terranx.h`, applied to Ghidra). DLL `src\uimod\build\Release\uimod.dll` = **3ec74d25**, deployed with an installer run. First in-game run crashed at the menu on a
330-char label line -> fixed by wrapping ([[feedback-popup-label-line-length]]). (uncommitted
tree; all Phase A-E audits triaged; 3 pre-existing e2e/fetch test failures came from concurrent verdict-text changes, not this work).

**User decisions (2026-09-27, do not relitigate):** check on a worker thread at launch, ZERO
start-time impact; present ONLY at the top level of the main menu (TOPMENU strip is the one modal)
or at the START of the human's turn (never mid-turn / AI moves / over a modal / in sub-screens);
in-game the prompt offers "Save, then quit and update" (engine Save dialog; cancel = abort) and
"Quit and update without saving" (= vanilla Quit's confirmed branch); new optional packs get their
OWN popup each (name + size); replies are exactly "Not now" (nothing written, next launch asks
again) and "Don't ask me again" (user rule 2026-10-31: "a decline of any pack is reset when any new update
releases for a module that is already installed" -- the DLL writes `base:<ver>` / `<id>:<ver>` for an update offer
and `new:<id>:*` for a new pack in `[Longevity] DeclinedUpdates`; the installer's check lists everything again
while one installed module has an undeclined offer, else applies the declines; `manual-<reason>:*` stays for
good); Preferences row =
checkbox "Check for Updates at Startup" + button "Reset Skipped Updates" (renamed 2026-10-31; was "Subscribe to all updates") on the same line
(confirmation popup, clears the declines, turns checking on, says "restart to check now");
offline / broken network must be IDENTICAL to vanilla (a dedicated auditor per phase); every popup
is the game's REALLYQUIT-style art popup with `#sprite longevity_sm.pcx` (200x120 PCX from the
website mark, `work\art\`, generator `work\scripts\art\make_longevity_sm.py`, ships in the base
payload beside the exe; the DLL omits `#sprite` if absent).

**Architecture:** `update_core.h` = header-only pure logic (parser, declines, cmdline, label file,
all strings; harness `work\tests\update_core_selftest.cpp` + `test_update_core.py`, cross-language
golden in `test_install_e2e.py::test_the_dll_parser_reads_every_real_check_answer`). `update.cpp`
= worker (Peek-then-Read pipe, 30 s kill, job object, SEH), `UpdatePoll` (GetMsgProc) state
machine Waiting→Armed→Posted(WM_APP+0x55)→Presenting→Done, gate (`MainMenuIdle`: GameHalted==1,
depth 1, SetupWin vtbl 0x66D8E8, +0x1014 set, 0x58E722 on the stack; `TurnBegan`: token from a
4-site E8 retarget of Console_human_turn 0x514050 + MapWin_g+0x23BE4==1 + no modal + SP), prompt
sequence, hand-off `cmd /D /S /C run-install.bat --update --game-dir <dir> --wait-pid <pid> --only-listed [--modules a,b]` (since 2026-10-31: exactly the packs the popups named; the installer adds nothing but a stale core),
exit (menu: `[W+0xFD0]=-1; Win_release_modal(W)`; game: IRONMAN auto_save + ControlTurnA=1),
save = `save_game(0)` 0x5A9EB0 (0 = saved). X_pops_18 flags 0x40 so ESC = -1 = Not now (ESC
otherwise returns reply 0 = the accept!).

**Audit findings fixed today:** pipe `|` rejected by the value check; refused answers left items
behind; KB/MB rounding; quoted `--lv-manifest`; CRLF harness; decline table cap/overflow refusal;
1023-char write rule both sides; item cap 63 + whitespace parity with receipt.py; `manual:*` →
per-reason `manual-<reason>:*`; picture copy warns instead of failing the deploy; kVerCap 18 (17-char
versions); compiled-in labels, unknown ids SKIPPED (not fatal), duplicates/downgrades/size bounds
refused; leading `#`/`;` neutralised on every popup line.

**Popup format facts MEASURED in-game (2026-09-27, 4K shot):** (1) `^` is a line break ONLY at
the START of a physical line (script.txt rule 7; a lone `^` line = blank line; `^^` = centred); an
inline `^` renders literally. (2) pops flag 0x40 does NOT just make Esc return -1: it turns the
replies into a selection LIST with OK / CANCEL buttons. Plain reply buttons (REALLYQUIT shape) =
flags 0, where Esc returns the highlighted reply = 0, so **reply 0 must be the safe "no"** (vanilla
convention: "Oops, no, wait!" first). Both fixed in update_core.h (ReplySetFor order, PutSan body
'\n' -> "\r\n^"), DLL 5001c5e5 live. (3) `#xs 460` at 4K looks right; picture renders.

**Console gotcha (2026-09-27):** generation 2 used to start with cwd = the staged payload it then
RENAMES into place; with Windows Terminal as the default console the tab was left with a deleted
working directory and could neither restart nor close (X / Enter / Ctrl+D dead, thread alive).
Fixed: `bootstrap.py` spawns gen 2 with cwd = the game folder (the next run's console closed by
itself). Only killing WindowsTerminal.exe removes such a stuck window (it hosts every WT window).

**Multiplayer (static audit 2026-09-27, the maintainer's work log has the detail + 4 short manual checks):** no
in-game prompt in network/hotseat/PBEM by construction (MultiplayerActive / PbemActive flags; lobby =
NetWin modal); hook now 3 control_turn sites only; MainMenuIdle requires both MP flags 0; the check
child inherits only its 3 std handles. DLL 75f3c570 live.

**Pristine exe = developer tool only (user decision 2026-09-27):** the un-PRACX'd terranx.exe with
PRISTINE_GROUPS is kept for the Win11 crash fix and as a clean baseline, never a public target.
InstallUpdateCheck() returns at once without prax.dll ("not a supported update target"); the only
test on that build is a sanity launch (DLL loads, that line, no prompt). Do not propose
pristine-exe user flows.

**Tutorial hints (measured 2026-09-27):** the TutWin (0x8C6E68) is NON-modal, so the modal guards let the
prompt stack over "Your colony pod has crash landed..."; the turn-start gate now also waits on
TutWin +0x9C bit0, and the click that closes it does not count as the player's first action.
Good to know: the engine's own IRON MAN SAVE popup ("the program will now shut down") follows a
confirmed Ironman save.

**Ironman (measured 2026-09-27):** save_game(0) under RULES_IRONMAN still shows the save DIALOG (then
quits by itself once saved). The order is the same everywhere: save dialog FIRST, cancel = abort with
nothing spawned, spawn the updater only after a successful save, and RequestGameExit leaves the
engine alone when ControlTurnA is already set. (Spawning first put the updater console over the
dialog and quit the game after a cancel.)

**More measured popup facts (2026-09-27):** a label with ONE reply line renders as a
one-item list row under the engine's own OK (malformed); message-only notices must have NO reply
lines (vanilla's shape) -- `Notice()` with a single acknowledgement emits none. The turn-start
presentation works in-game (tester switch `--lv-delay=<s>` holds the check back; the launcher
takes `<scenario> delay`); "Save, then update" opened the engine save dialog and a cancel
aborted with the notice, as designed.

**Audit-driven changes after the plan (2026-09-27):** UX text pass (shorter in-game replies,
"what the two no's mean" lines, cancelled-save notice, F6/F7/F8 reworded, URLs without scheme,
`#xs 460`); a "no" to F2 defers pack popups to the next launch, at most one standalone pack popup
per launch; Prefs "Yes" persists CheckForUpdates=1 at once; prefs show/hide lists include the new
row; main-menu gate rejects the HOTSEAT strip (0x58DBAA live above W) and stale stack slots (hit
must be below W); Ironman: save_game(0) is save-AND-quit, so spawn first there; SetErrorMode
around the child spawn (no python3xx.dll error box); installer `--check` never resumes a .part,
discards unverified manifests on any fetch error, 24 s watchdog (`CHECK_WALL_SECONDS`);
uimod.log rotates at 1 MB. Button renamed "Reset Skipped Updates" (user 2026-10-31); kept as the maintainer specified:
the art, the console title (see the maintainer's work log for the auditors' objections).

**Open / next:** (1) user runs both exes with `work\scripts\dev_test_manifest.py <scenario>`'s
recipe (`--lv-manifest=` + `LONGEVITY_TRUST_KEY`) at 4K + one non-4K per plan Part 4; the live
resident updater must be refreshed by an installer run first (it predates `is_declined`);
(2) triage the Phase D/E audits (correctness, UX, offline, regression); (3) UNMEASURED engine
facts to confirm in-game: debugdump values at TOPMENU, ESC→-1 with flags 0x40, the Prefs button
face/placement at g=16/22/25/40, save_game(0) from our popup context; (4) CHANGELOG line only
after user verification; (5) commit.
