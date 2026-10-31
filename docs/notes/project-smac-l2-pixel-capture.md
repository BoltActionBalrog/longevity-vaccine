---
name: project-smac-l2-pixel-capture
description: why Layer-2 modal PIXEL capture was REMOVED (2026-06-07) — RE findings if ever revisited
type: reference
---

Layer-2 modal regression is **NUMERIC-ONLY**. Pixel/PNG capture was **REMOVED from the tests on 2026-06-07** (briefly tabled, then deleted at user request) as high-effort / low-value: snap_to_png.py deleted; probe_modal.js + compare_snapshots.py + run-capture.bat + REGRESSION.md stripped of all pixel code; numpy/pillow no longer needed by Layer 2. This note retains the RE findings in case it's ever revisited. See [[project-regression-framework]].

## What works (keep)
- **Numeric golden**: solid & reproducible. `customize-game-rules@3840x2160.json` captures box 1705x1152, frame rect, margins 25/30, band 20, header_reserve 95 / footer_reserve 45, content 0x0 (this is a titled/"else" branch modal — dialog substruct null), and **67 buttons with exact id/x/y/w/h/parent**. This already pins button geometry MORE precisely than pixels would.
- **Title-render fix**: removed the title-font hook at `0x4060aa` — its Frida Interceptor trampoline on that `CALL Buffer_set_font` was suppressing the title render. Title now draws (confirmed in the popup-bg PNG).
- **Button-capture fix**: removed the `Popup_start` (0x406380) reset — Popup_start fires ~4x per modal (`psTotal=4`), so resetting there wiped the modal's own buttons (gave buttons=0). Now snapshot-since-last-capture. CAVEAT: buttons accumulate globally, so a detour through a screen that does NOT hit `Popup_on_draw_background` (0x405c80) — e.g. Datalinks, an external window — leaks its ~65 buttons forward into the next capture. **Must navigate DIRECTLY to the target modal for clean buttons.** Parent histogram confirmed clean: rules body = parent 0x7ae820 (57) + 4 scrollbars (2 each) + BACK/EXIT (0x7cdd0c, 2).

## The pixel rabbit hole (why tabled)
No single buffer holds the fully-composited modal (frame+title+CONTENT):
- **popup buffer `pp+0x444`** = background ONLY: frame + title + inner content border. Children do NOT composite here (PNG: title renders, content area empty).
- **`GraphicWin_soft_update` (0x5D5720)** NEVER fires for the popup (the plan's assumed blit path was wrong).
- **`GraphicWin_redraw` (0x5D5A70)** fires only for CHILD elements, each with its own tiny buffer (20x20, 106x14, 233x22, 54x32, 43x18, 24x24…); never for the popup root.
- **`Popup_on_draw_background` (0x405c80)** fires ONLY ONCE per popup, not per frame → "dump on 2nd sighting" fails.
- **`g_backbuffer` (0x945824)** shows the MAIN-MENU splash, not the modal → it's the saved-background buffer the popup stashes to restore on close, not the live display surface.
- Each child blits to the real display surface (under PRACX likely a DirectDraw primary, not yet located). The composited modal image exists only there.

## Resume options (future)
- **A** — locate the PRACX display/primary (DirectDraw) surface and dump the popup's screen rect from it. Need the real screen x,y (NOT `screen_rect`/+0x474 = 0,0 which is buffer-local origin).
- **B** — reconstruct in Python: popup bg (`pp+0x444`, we have it) + blit each child buffer at its (x,y). Needs dumping each child GraphicWin buffer (hook GraphicWin_redraw, dump ecx+0x444 + screen pos); child x/y/w/h already come from BaseButton_init.
- **C (recommended)** — ship the NUMERIC golden as the gate + the popup-background PNG (frame/title/box) as a visual check; skip full-content pixels.

## Gotchas to remember
- **Palette**: `pp+0x444+0xa4` RGBQUAD cache = 0 (GDI palette not populated for these surfaces) → snap_to_png used greyscale fallback. Color PNGs would need the global game palette (location TBD).
- **JSON pixel-dims backfill FAILS silently under Frida** (the File read/rewrite in `dumpPixels`); had to add the `pixel{}` block manually. Fix or set dims at JSON-write time if resuming.
- If revisiting, note the JSON pixel-dims **backfill failed silently under Frida** (File read/rewrite in the old `dumpPixels`) — set dims at JSON-write time instead. (The diagnostic backbuffer/histogram code that briefly lived in probe_modal.js has since been removed.)
