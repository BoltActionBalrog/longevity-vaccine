---
name: project-smac-pracx-prefs-focus-fix
description: longevity-vaccine issue #6 (PRACX Preferences kills wheel zoom + right-drag on Linux) = Wine leaves no keyboard focus after PRACX's panel closes; fixed by pracxfocus.cpp (uimod.dll 626b10e5), Windows-verified 2026-11-13, Linux unverified
type: project
---

Issue #6 on longevity-vaccine (thomast360, Nobara Linux, 2026-11-12): after opening PRACX -> Preferences, map wheel zoom and right-drag scroll stop until restart. Mechanism, all proven 2026-11-13:
- PRACXWinProc gates its wheel branch and right-drag on `GetFocus() == game hwnd` (refs\pracx\shared\pracx.cpp:1139/1161/1288) and never calls SetFocus.
- The Preferences panel (class `PRACXSettingsWnd`, WS_CHILD of the game window) gives focus to any button clicked in it; closing it destroys that button. Windows then hands focus to the parent; Wine clears it to 0 (Wine master 9f8c4ae: win32u show_window SW_HIDE reverts focus only when the hidden window IS the focus window; wineserver `thread_input_cleanup_window` zeroes focus when the focused button is freed). Wine reactivation (`set_active_window`) does restore focus, so Alt+Tab should recover there.
- Second, every-system PRACX quirk: Esc does nothing once a panel button has focus (the key goes to the button).

Fix: `src\uimod\src\pracxfocus.cpp` + `pracxfocus_core.h` -- thread-local WH_GETMESSAGE hook, PRACX only: game active + focus NULL + no panel + not iconic -> SetFocus(game) before dispatch; Esc key-down on a control inside the panel is readdressed to the panel. Tests: `work\tests\test_pracxfocus.py` (real Win32 windows, Wine close emulated). Repro/verify tool: `work\scripts\focus_probe.py watch|drop|restore` (clears or reads the game thread's focus from outside via AttachThreadInput; run elevated if the game is). User verified in-game on Windows 2026-11-13 (drop -> restored in the same second; Esc closes the panel; OK/Cancel fine). The owner replied on the issue himself 2026-11-14 (Wine focus bug, Alt+Tab workaround, fix next release). Two independent audits 2026-11-14: no crash/regression; they found test gaps (minimised/disabled guards were untestable through SetFocus on Windows -> now asserted on FocusLost; mutants verified caught), wrong comments, and text over-claims (fixed). Alt+Tab recovery holds on winex11/fullscreen, NOT on Wine's native Wayland driver (no foreground change on re-entry).

**Why:** the reporter's environment cannot be reproduced here; the Windows emulation (drop) is the only in-house check.
**How to apply:** a Wine/Proton-only input bug in PRACX -> check focus first with focus_probe.py `watch`. Related: [[project-smac-mouse-scheme-proposals]], (a private note).
