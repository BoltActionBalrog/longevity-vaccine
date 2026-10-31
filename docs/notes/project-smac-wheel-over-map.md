---
name: project-smac-wheel-over-map
description: Mouse wheel over a list popup while the world map shows — CLOSED user-verified 2026-09-19, uimod.dll c11b5d58 (wheel.cpp WH_GETMESSAGE hook); PRACX ate the wheel for map zoom
type: project
---

CLOSED 2026-09-19 (user: "It's perfect"), uimod.dll **c11b5d58**, committed + pushed. No exe change.

**Symptom:** scenario editor SELECT TYPE OF UNIT TO CREATE (shot 20260919): wheel over the list zoomed
the map underneath instead of scrolling.

**Cause:** the whole wheel chain (group wheel_scroll + t_dl/t_rw heads at WinProc 0x5F07B0/0x5F07F0) depends on
PRACX's WndProc posting VK_UP/VK_DOWN pairs with lParam 0. PRACX does that ONLY when the map is not the active
view; with the map up it zooms (Thinker's gui.cpp WM_MOUSEWHEEL branch is the readable equivalent: GW_World ->
Console_zoom, else PostMessage arrows x ListScrollDelta). A popup over the map still counts as "map showing".

**Fix (`src\uimod\src\wheel.cpp`, InstallWheelCapture from Init):** thread-local
`SetWindowsHookEx(WH_GETMESSAGE, ..., GetCurrentThreadId())` — Init runs on the game's main thread (CRT startup
table), so the hook sees WM_MOUSEWHEEL before ANY WndProc, with no dependence on how/when PRACX subclasses.
On PM_REMOVE only: win = g_current_basepop 0x9B8D7C else g_modal_top 0x9B7AE0; vtable in the wheel_scroll class
table (+ all 4 Popup-family vtables); cursor (ScreenToClient of the msg lParam) inside Win+0x13C RECT -> message
becomes WM_NULL and the arrow pairs (lParam 0) are posted; else untouched, so map zoom still works off the popup.
Pairs per notch = [PRACX] ListScrollLines from Alpha Centauri.ini, default 3 (`<DEFAULT>` parses as 0 -> 3);
user found the speed right. Patches no code, reads only .data globals -> safe on the pristine exe
([[feedback-uimod-shared-dll-gate]]); there the arrows are plain selection moves.

**How to apply:** a new scrollable modal class that should take the wheel over the map needs its vtable in BOTH
tables — asm_wheel in assemble_dw.py (chevron conversion) and kScrollable in wheel.cpp (capture). Non-modal lists
(report-screen consoles) are handled by the t_rw/t_dl heads and are never over the map.

Related: [[project-smac-design-workshop]] (wheel_scroll origin), [[project-smac-picker-scrollbar]],
[[project-smac-uimod-dll]].

**2026-09-21g addendum — base screen joined the chain (USER-VERIFIED all res, COMMITTED+PUSHED 94815eb (final exe bd2bae0b), v3 gate = base screen shown, not modal):** `t_bw_wheel_down/up` (assemble_basewin.py) are now the WinProc chain HEAD (-> t_ntw -> t_rw -> t_dl -> dw). Gate: `[g_modal_top] == BaseWin_g 0x6A7628` (the base screen's exec calls vtbl+0xE4 Win_set_modal @0x404182) and no basepop. The list under the cursor: BASE FACILITIES = cursor - BaseWin origin (+0x13C) inside rcFacilities +0x40BAC with its NATIVE edges scaled (v*g)>>4 (clamped g>=16) -> bar +0x41454; else FORCES SUPPORTED = cursor - MainWin origin inside the strip panel +0x40B7C (already device, MainWin-local) -> bar +0x435A0 (its parent is MainWin, whose vtbl+0xC0 repaints the strip). Engaged = bar open ([+0xC4]) && range max > min. No parent present call (ScrollBar_on_chevron's notify repaints like an arrow click). wheel.cpp: BaseWin vtbl 0x66A40C in kScrollable with NO rect test (the base view is full-screen; the map underneath is never interactable). LESSON (caught by the parity test): a chain head that uses eax for cursor math must save the Win_get_active_target result and return it on every non-eaten path — v1 returned scratch and would have dropped every non-list key while a base screen was open.

**2026-09-22 CORRECTION (v3, exe f401ecdc + DLL 590385bc): the base screen is NOT modal.** The probe `hook_bw_wheel_probe.js` (frida_bwwheel_20260922) measured `g_modal_top == 0` and `g_current_basepop == 0` with a base open (the vtbl+0xE4 call @0x404182 is not BaseWin's open path); PRACX itself posted the arrow pairs (map "not showing"), the head reached with the cursor inside the facilities panel and the bar engaged — only the `modal top == BaseWin` gate failed. v3 gate (exe head + wheel.cpp ModalUnder fallback): `[g_modal_top] == 0 && [g_current_basepop] == 0 && (BaseWin_g+0x9C & 1)` (Win_is_visible's flag; measured 5 = bits 0+2 while open). LESSON: "modal top" identifies popups/pickers/report screens, never the base screen — probe the globals before gating on them.
**2026-09-22 notch size (DLL 328ef576):** PRACX's ListScrollLines (ini `<DEFAULT>` = 3 pairs per notch) is fine for long lists but the FORCES SUPPORTED bar has at most THREE positions (draw_supported clamps its range to 0..rows-1, rows <= 3; one position = one unit ROW), so one notch jumped it end to end ("always a minimum of two", user). wheel.cpp `LinesFor(win, client)`: on the base screen with the cursor inside the strip panel +0x40B7C (MainWin-local) a notch posts ONE pair; everything else keeps g_lines. The exe heads are unchanged (without the DLL, PRACX posts 3 pairs there -- accepted gap).
**2026-09-22b CORRECTION (DLL d4ee9d3f): PRACX's ListScrollLines default is 1, not 3** (refs/pracx/shared/pracxsettings.h `DEFAULT_LIST_SCROLL_DELTA 1`; `<DEFAULT>` in the ini leaves it). The 2026-09-19 note "default 3 (`<DEFAULT>` parses as 0 -> 3)" described wheel.cpp's OWN wrong fallback: DLL-captured notches (popups, pickers, base screen) scrolled three rows while PRACX-posted ones (Datalinks, report screens) scrolled one. g_lines now defaults to 1; an explicit ini number still overrides. User decision 2026-09-22: one element per notch everywhere. LinesFor's one-pair rule for FORCES SUPPORTED is kept (harmless; matters only if a player sets ListScrollLines > 1).
