---
name: feedback-global-lever-all-writers
description: A scaled engine GLOBAL (font ptr, margin, default) must be scaled at EVERY engine writer — popups_normal/popups_tutorial/config_popups re-install natives mid-session
type: feedback
---

When a lever is "repoint an engine global" (g_menu_font, g_bubble_font, popup default fonts/margins),
byte-scan the exe for EVERY writer of that address before calling it baked — not just the one site
the prototype hooked.

**Why:** 2026-09-18 (exe d76dbaa4): HUD dropdown submenus went native-tiny after any tutorial popup.
g_menu_font 0x9B7B68 was scaled only in thunk_menu_layout (MENU widget layout, runs rarely), but
popups_normal 0x588460 re-installs the native [g_popup_menu_font_src] at 0x5886C1, and
TutWin_tut_win ENDS in popups_normal (also called @0x48C349, 0x58428B, config_popups). The symptom
was seen "a couple of times" during prototyping and dismissed as prototype flakiness — an
intermittent native-size revert is a STATE-RESET writer, never noise.

**How to apply:** `pefile` byte-scan for the global's abs32 (see the scan in this fix) and classify
every `A3`/`89 0D`/`89 15`/`C7 05` hit; make all writers ask for the SAME value (one law — here
scaling_laws.menu_font_request; parity test asserts both thunks carry the same request bytes).
popups_normal/popups_tutorial are the usual culprits: they rewrite ~20 popup-style globals
(0x696E0C..0x696E1C margins, fonts) on every tutorial popup. Related: [[feedback-draw-state-multiplicity]],
[[feedback-scaling-inline-rebuild-paths]], [[project-smac-tutwin-tooltip]], [[project-smac-hud-scaling]].
