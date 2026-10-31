---
name: feedback-graphicwin-clear-honours-clip
description: GraphicWin_clear fills only the canvas's CURRENT clip, and a painter may leave a partial clip behind; GraphicWin_resize(...,1) repaints synchronously — arm levers AFTER the resize and reset the clip before a "letterbox" clear
type: feedback
---

**Rule:** a build wrapper that does `GraphicWin_resize(win, SW, SH, 1)` + `GraphicWin_clear(0)` to make a letterbox must (1) arm its scaling levers only AFTER the resize call (the resize repaints at once through vtbl+0x30 with whatever the fields hold), and (2) `Buffer_set_clip(canvas, &win+0x474)` before the clear, because `GraphicWin_clear` fills only the canvas's current clip rect and a painter's early-out path can leave the clip at a sub-rect.

**Why:** Hall of Fame bake v1 (2026-09-14): the resize's repaint ran armed with the content rect still native, so hof.pcx went scaled to (119,80); FameWin_draw's no-scores path leaves the clip at the native content rect (119,80,919,680), so the clear wiped only that and a strip of scaled content survived in the left letterbox from y=680 down. Frida trace (hook_hof_ghost.js) showed no engine blit at the ghost — it was the wrapper's own order of operations. The Monument's painter happens to restore its clip, which is why the same shape never bit there.

**How to apply:** any full-screen letterbox wrapper (Monument, HOF, the future HOF-like screens): resize → arm → rect pokes → set_clip(whole) → clear → content rect/tables. When a ghost is a pixel-exact copy of scaled content displaced by (scaled origin − native origin), suspect a repaint that ran with mixed-space fields, not an engine blit.
Related: [[project-smac-hall-of-fame]], [[project-smac-monument-screen]].
