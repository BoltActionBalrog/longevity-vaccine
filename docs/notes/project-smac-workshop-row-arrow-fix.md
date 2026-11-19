---
name: project-smac-workshop-row-arrow-fix
description: Workshop/Datalinks from a base: stray unit-row arrow (VANILLA), wheel zoomed the hidden map (PRACX), workshop unit row never wheel-scrolled (PRACX) -- all fixed in uimod, USER-VERIFIED PRACX + Thinker, pushed 2f6685f
type: project
---

CLOSED 2026-11-14, user-verified on PRACX (all res, arrow) and PRACX + Thinker (wheel); commits eaf0c6b (arrow + workshop wheel) and 2f6685f (generalised wheel + unit row, uimod.dll df380ce9).

**Arrow (vanilla bug):** MainWin unit-row arrow buttons [8] 0x7B5080 / [9] 0x7B5BCC / [10] 0x7B6718 are shown only by BaseWin_draw_garrison and StatusWin_draw_status. The HUD iface's leave hides all 0x2A console buttons; the base iface's leave BaseWin_on_status(0) 0x41DAD0 does not, so [9]/[10] stayed up over the workshop. Fix: `src\uimod\src\rowarrowfix.cpp` wraps BaseWinIface vtbl slot 0x66A3B8 and hides [8..10] on leave. Probe: `work\scripts\hook_dw_arrows.js` (gitignored).

**Wheel from a base (PRACX bug):** PRACX zooms when IsMapShowing() = m_fGlobalTimersEnabled && BaseWin/SocialWin/TutWin hidden. The HUD leave stops the map timers (stop_timers 0x50F440 @0x45CA78) except when the next mode is 0xA/3/2; the base leave never does. Fix in wheel.cpp: while the live iface mode (g_iface_mode_table[idx], pushed BEFORE the leaving on_mode(0)) is 1 workshop / 5 reports / 8 Datalinks AND g_map_blink_timer 0x915688 +4 != 0 (= PRACX's flag exactly) AND focus == game, post up/down pairs.

**Workshop unit row:** DesignWin_on_key 0x439A20 scrolls on VK_LEFT/RIGHT only (buttons 0x17/0x18), no up/down case, so PRACX's up/down never moved it. While Win_get_active_target() == DesignWin_g, notch up = LEFT, down = RIGHT (Thinker's mapping, user's spec).

**Thinker order (measured from source, audited):** thinker.exe injects thinker.dll first; its ModRegisterClassA patches the IAT; prax.dll later wraps it, so the registered class proc is Thinker's ModWinProc and PRACXWinProc is its WinProc. ModWinProc sees every notch first and never zooms unless the key target is the map. uimod therefore stands aside for these screens when GetClassLongPtrA(game, GCLP_WNDPROC) lies in thinker.dll (user: never override Thinker). uimod's ModalUnder still takes base-screen notches before Thinker, but that costs nothing: Thinker's zoomable SUPPORT view is NEUTRALIZED by us (thinkercompat.cpp kUndo, it does not scale), so its wheel zoom only redraws -- don't re-flag it as a conflict. HQ reports ARE reachable from a base; user saw no scrolling issue there (2026-11-14). Backlog (the maintainer's work log): a scaled Thinker-style zoomable support view; rows per notch vs PRACX's live Wheel Scroll.

**Why it matters later:** "who hides a shared console widget" = the leaving iface's on_mode, per [[feedback-restore-at-owners-hide]]. A PRACX "map showing" misjudgement follows the map-timer state, not the window on top. Under Thinker, any wheel/key behaviour must be checked against ModWinProc first ([[feedback-thinker-conflicts-user-decides]]).

**Workspace incident 2026-11-13:** the main checkout's gitignored `src\uimod\third_party\ffmpeg` had been emptied; restored from a worktree. If a DLL build fails on `libavformat/avformat.h`, check that folder first.
