---
name: feedback-wheel-route-by-cursor
description: Mouse-wheel routing on a screen with several scrollables goes by the CURSOR, never by a fixed priority; one row per notch everywhere
type: feedback
---

When a screen holds more than one scrollable (Datalinks: category list + article text box + console
quote box; base screen: BASE FACILITIES + FORCES SUPPORTED), a wheel head must pick the bar UNDER THE
CURSOR (cursor − owner origin inside the element's device rect, half-open), and only fall back to a
default when nothing under the cursor is engaged. A fixed "first engaged bar" order (the 2026-08-30
Datalinks head) made the second scrollable unreachable whenever both overflowed. Default = one arrow
pair per notch everywhere (PRACX's real ListScrollLines default; the DLL's old "3" fallback was wrong).

**Why:** the maintainer asked for exactly this twice (base screen 2026-09-21, Datalinks 2026-09-22) and
called three rows per notch "too much"; a picker that "captures everywhere" is fine only as the
fallback, not as the first choice.

**How to apply:** new wheel heads copy t_bw_wheel_down / t_dl_wheel_down v2: fix the chevron id
first (the cursor IAT calls clobber edx), GetCursorPos + ScreenToClient(G_HWND), subtract the owning
window's +0x13C origin (MainWin for strip/console elements), test each element rect, engaged = bar
open (+0xC4) && max (+0xA24) > min (+0xA20) && window shown (+0x9C bit0). Gate on what is really on
top: the base screen is NOT modal (g_modal_top stays 0), Datalinks IS. Parity-test the edges at
L−1/L/R−1/R. See [[project-smac-datalinks]], [[project-smac-base-screen]],
[[project-smac-wheel-over-map]].
