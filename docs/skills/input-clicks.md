---
name: input-clicks
description: Use when SMACX clicks are eaten, deferred, land on the wrong window, or UI stops responding to the mouse — maps the engine's click-dispatch chain and the diagnosis playbook.
---

# SMACX mouse/click dispatch — map + diagnosis playbook

Decoded 2026-07-05 during the planet-button deferred-click hunt (hook_hudframes34–39).
All symbols are in `work\symbols\terranx.h` and the Ghidra project.

## The dispatch chain (message-driven, NOT polled)

```
user32 msg → [PRACX ModWinProc subclass: rewrites ALL mouse coords via ClientToBackbuffer,
              forwards left clicks]                        refs\pracx\shared\pracx.cpp:1266
  → WinProc 0x5F0650 (game WndProc, stdcall ret 0x10)
      WM_LBUTTONDOWN/UP block (0x5f0a14 / 0x5f0a6b)
      → Win_OnLButtonDown 0x5F2330 (both edges; arg2 = isUp)
          → Win_get_mouse_window 0x5F6F10 (screen→window resolve; NULL ⇒ click DROPPED silently)
          → [only if g_9B7AA4≠0 or win.f98&0x4000000] vtbl+0x12C Win_on_nc_hittest 0x5F5AD0;
            codes 2 / 0xA..0x11 ⇒ STASH in g_mouse_stash_* 0x9B7AA8..B4 and return (no dispatch);
            stash is drained by WM_MOUSEMOVE → Win_do_tracking 0x5F7580
          → vtbl+0x144 Win_on_l_button_down 0x5F63C0 (records g_click_x/y/flag 0x9B7ACC/AD0/AD4
            FIRST; press block gated on f98&0x200200; window's own Spot list @this+0x8F4;
            BLOCKS in a press loop until release)
              → Win_left_down_event 0x5EE750 — entry vetoes ret silently:
                test [win+0x98],0x200000 / test [win+0x9C],8
                  → FlatButton virtuals (shared vtbl 0x669754): +0x50 press 0x6075C0,
                    +0x4C release 0x607A20, +0x54 post-release, +0x44 move, +0x48 leave
      WM_MOUSEMOVE block (0x5f0950): if g_mouse_stash_win 0x9B7AAC set → Win_do_tracking;
      else enter/leave via vtbl+0x40/+0x48 on g_last_mouse_win 0x9B7A7C change
```

## Diagnostic fingerprints (read these before theorizing)

- **press→release spacing** is the single most informative number. Physical click ≈ 80–150ms
  (Win_on_l_button_down blocks in its press loop for the hold). **< 2ms apart = BOTH edges were
  stale in the queue when processed** — the delay is UPSTREAM of the chain (message starvation),
  not a per-window property.
- **Gap in mousewin-change logs while the user is physically moving** = no WM_MOUSEMOVE processed
  at all ⇒ the message pump is starved (someone is spinning without pumping), not a resolve bug.
- **Chain entry hooks that fire only at "replay" time** (same-ms cluster after a boundary event)
  ⇒ don't hunt per-window flags; hunt what blocks the pump.
- Identical `[win+0x98]`/`[win+0x9C]` across healthy and broken windows kills any veto-flag theory
  in one run — log them at 0x5F63C0/0x5EE750 entry for a known-good button AND the broken one.

## Suspect ordering (cheapest decisive test first)

1. **Third-party subclass/spin — check when the pristine exe is immune.** Read the hook source in
   `refs\pracx\` / `refs\thinker\` BEFORE more probes. Known: **PRACXCheckScroll** (pracx.cpp:991,
   PRACX's own "TODO Fix #3") runs from the main loop (thunk call at exe 0x522C25, installed at
   prax load) and spins without pumping while the cursor sits in the edge-scroll zone
   (iScrollArea = ScrollArea_ini×w/1024 from each edge). One-run test: `ScrollArea=0` in
   `[PRACX]` of `Alpha Centauri.ini`. FIXED for the bottom edge by `work\patches\patches_prax.yaml`
   (NOPs the centered-1024 console-band disjuncts; prax.dll 89a0037b→7fd2e711). Left/right/top
   zones still spin (vanilla-PRACX-faithful; console bottom corners are inside them).
2. **Wrong-window dispatch**: hook Win_get_mouse_window keyed on returnAddress==0x5f2343 and log
   the resolved window — a gated per-button hook is blind to a dispatch that went elsewhere.
3. **Silent vetoes**: 0x5EE750 entry flags above; 0x5F63C0 skips its press block on f98&0x200200.
4. **Stash path**: only live when g_9B7AA4≠0 or f98&0x4000000 — verify with an nc-hittest hook
   before assuming.

## Rules learned

- The engine has NO independent mouse poller — if clicks lag, messages lag. Perceived
  "polling" was WndProc-driven all along; a Peek/GetMessage IAT hook that sees zero
  WM_LBUTTON while clicks work is miswired, not proof of polling.
- Win_on_l_button_down records the click globals BEFORE any veto, so a recorded-but-undelivered
  click can be replayed later by boundary enter/leave processing — "fires when I move off the
  button" is a REPLAY signature, with press+release <2ms apart.
- A silent click-drop exists: Win_get_mouse_window returning NULL inside Win_OnLButtonDown skips
  dispatch entirely with no stash and no record.
