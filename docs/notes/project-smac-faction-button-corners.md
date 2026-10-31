---
name: project-smac-faction-button-corners
description: Faction-picker bottom-button corner notch + bar-fill — SQUARE notch (not staircase), full-bleed devfill via NEG(origH); DONE build cb53e04f
type: project
---

Faction Select bottom buttons (INFO / CHANGE NAME / OK / CANCEL + PLAY SELECTED/RANDOM) corner shape + bar-fill. **DONE + user-confirmed @4K and non-4K, build cb53e04f, 2026-06-27.** CHANGELOG'd.

**Shape decision (do NOT relitigate):** the corner notch is a solid **s×s SQUARE** (s=ceil(g/16)), pure horizontal/vertical edges — NOT a 45° staircase/diagonal. The owner chose this (2026-06-27) after rejecting a staircase triangle (build 7d6ef4dc) that "read as a diagonal nick" at 1920/s2. Their framing: "pristine is essentially a one-pixel black square." `thunk_corner_punch` (pcave2 0x1740) = the 17B square fill `for(row=s){for(col=s)[edi+col-1]=9; edi+=stride;}`, ebp=s, ecx=stride, edi=corner topleft; called 4× by `thunk_btn_devfill`.

**Bottom over-draw fix:** `thunk_btn_devfill` (pcave2 0x1660) re-tiles the captured bar dither at DEVICE res over the button buffer, then punches the 4 corners. Originally it tiled to `destH = fill_h·g/16`, which rounds ~2px **short** of the true scaled button height, so the engine's native-scaled fill **over-drew** the bottom 2 rows (a thin strip with the native 1px chamfer) and the bottom square notch sat 2px high. Fix = re-tile **FULL-BLEED**: destX=0, destY=0, destW=[g_btn_origW], **destH=NEG([g_btn_origH])**, and place bottom corners at `NEG(origH)−s`. These FlatButtons are full-bleed (the teal dither spans the whole buffer top-to-bottom, no in-buffer frame — confirmed by pixel-gridding MangledSmacx.png @1920). devfill 199B→170B.

**Crash gotcha (cost a 4K crash):** origH MUST be `NEG([g_btn_origH])`. That global AND `[esi+0x4c8]` store the button buffer's h field **NEGATIVE** (top-down DIB). An earlier full-bleed attempt (build 2d2fa7c4) used `[esi+0x4c8]` un-negated → `(origH−s)·stride` went large-negative → wild write → **crash entering the menu at 4K**. Always neg first (exactly what 2dscale does to feed the StretchBlt dstH). See [[feedback-negative-height-saved-copy]].

**Diagnosis method that worked:** Frida can't hook the popup/button redraw path, so I measured the RENDER from the maintainer's screenshot — pixel-gridded the corner (`#`=fill, `.`=cut), classifying by palette green-dominance, which showed the top corner correct but the bottom notch 2px high + a native strip. See skill scaling-frames (button site) + frida-tracing (render-grid). Related: [[project-smac-faction-dither-layer]] (popup devfill split-render), [[reference-faction-picker-component-map]].
