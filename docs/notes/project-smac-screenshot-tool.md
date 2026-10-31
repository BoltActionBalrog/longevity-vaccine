---
name: project-smac-screenshot-tool
description: work\run-screenshot.bat: focus-free game screenshot tool (any resolution, works under Frida); PrintScreen can be unreliable, Pause is the dependable trigger
type: project
---

`work\run-screenshot.bat` → `work\scripts\screenshot.py` (bundled tools\python, ctypes + Pillow ImageGrab). Built 2026-07-06 because Windows capture tools were unusable: PrintScreen grabs the whole desktop, Snipping Tool steals focus (fullscreen game reverts display mode + minimizes) and silently no-ops while a Frida probe is attached.

- **One-shot** (default): captures the game window (config exe, fallback any `terranx*`; class `JackalClass`) via screen BitBlt — no focus change, works at any display resolution, indifferent to Frida. Saves PNG to `work\screenshots\` (gitignored) + puts it on the clipboard. **It can be run during a verification session to capture the live game screen** (window must be on-screen, not minimized — screen-grab can't see minimized windows; tool says so explicitly).
- **Resident**: `--hotkey` registers **Pause AND Home** as global hotkeys (Home added 2026-10-26: a laptop over a remote-desktop stream has no Pause key; while resident, Home is swallowed system-wide); `--key ctrl+f9` etc. overrides. `--full` = whole virtual desktop; `--exe NAME` other processes. **`work\run-screenshot-hotkey.bat` = the double-clickable resident launcher — this is the USER's mode** (one-shot is for scripts; double-clicking it would defocus the fullscreen game).
- **The listener must be ELEVATED when the game is** (UIPI blocks hotkey delivery to a lower-IL process while an elevated window has focus): run-frida.bat spawns the game via UAC, which made the hotkey silently dead under any probe until run-screenshot-hotkey.bat got the same self-elevation block (net session check + Start-Process -Verb RunAs). Symptom = hotkey works on plain exe launch, dead under Frida.
- **⚠ VK_SNAPSHOT (PrintScreen) hotkey delivery can be broken — seen for physical presses too (2026-07-06)**: RegisterHotKey succeeds but WM_HOTKEY never arrives (synthesized via keybd_event AND SendInput with extended scancode 0x37, and real key presses) while F9/Pause fire fine — Windows swallows PrtScr below the hotkey layer. **Pause is THE trigger** (SMAC doesn't use it); PrtScr likely still clobbers the clipboard with the legacy both-monitor grab.
- PrintWindow(PW_RENDERFULLCONTENT) fallback exists for surfaces BitBlt can't see (pristine exe's own DirectDraw) — auto-tried when the BitBlt result is uniformly blank; untested live so far.
- If the game runs elevated and hotkeys don't fire in-game, run run-screenshot.bat elevated too.
- 64-bit ctypes lesson baked in: handle-returning APIs (GlobalAlloc/GlobalLock/GetWindowDC…) NEED explicit restype/argtypes or returns truncate to 32-bit (GlobalLock → 0x20 → access violation). See (a private note).
