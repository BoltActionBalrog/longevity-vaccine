---
name: feedback-wheel-scrolls-list
description: Mouse wheel over any list scrolls the LIST (never acts like the arrow keys / moves the selection); a notch over a list that fits is eaten
type: feedback
---

The mouse wheel over a list scrolls that list's view, everywhere in the game (F3 energy report and every other
wheel site). It must never behave like the arrow keys, i.e. never move the selection. When the list fits (nothing
to scroll), the notch is eaten rather than passed on as an arrow key (assemble_rw.py `EAT_WHEN_LIST_FITS = True`).

**Why:** user decision 2026-10-11 ("it should scroll the list. It should not work like the arrows").

**How to apply:** any new wheel handler routes to the bar under the cursor ([[feedback-wheel-route-by-cursor]]),
scrolls without touching the selection, and eats a notch over a non-scrollable list. Audit existing wheel sites
against this when touching them.
