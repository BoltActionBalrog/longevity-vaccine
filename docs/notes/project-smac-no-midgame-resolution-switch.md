---
name: project-smac-no-midgame-resolution-switch
description: Resolution never changes mid-game -- PRACX's options need a restart; the maintainer does not support or plan mid-game switching
type: project
---

The game's resolution (and so g / g_popup_scale_num) never changes inside a running session: PRACX's options menu needs a restart to take effect, mid-game resolution switching has never been supported, and the maintainer does not plan to support it (user 2026-10-15).

**Why:** audits kept raising "display-mode change mid-session" hazards (stale scaled caches, cursor re-scale, Go To black save buffer after a switch, prewarm restart on a scale change). Those paths cannot occur in practice.

**How to apply:** treat a mid-session g change as unreachable when weighing findings -- don't block a fix on it or design for it; at most note it. Still never crash if it somehow happens. Verification at another resolution means a separate launch (launcher shortcuts per resolution). Related: [[feedback-smac-all-resolutions]], [[project-smac-video-mode]].
