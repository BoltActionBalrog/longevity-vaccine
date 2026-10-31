---
name: project-smac-popup-scale-derivation
description: SMACX g_popup_scale_num = clamp(floor(16*min(W/1024, H/768)), 16, 40) -- MIN of both axes, FLOORED (bytes-verified 2026-10-18); per-resolution g table
type: project
---

`g_popup_scale_num` (0x668740, the master UI scale numerator over /16) is set ONCE by `thunk_ensure_scale` (0x668760)
from `scale_uniform` (0x668200):

**g = clamp( floor(16 * min(W/1024, H/768)), 16, 40 )**

`scale_uniform` tests `W*768 > H*1024`: wider than 4:3 -> 16*H/768, else 16*W/1024; unsigned mul/div, so FLOORED.
Verified 2026-10-18 by emulating the baked bytes over 157,201 W x H points,
0 mismatches. The OLD note here ("height-based, rounded") was WRONG -- it gave 1280x1024 = 21, 1600x900 = 19.
g > 16 needs W >= 1088 AND H >= 816. Stripe period P = 2 for g < 22, else 4.
Writers: only thunk_ensure_scale (+ t_hof_spr_pic saves/restores around one call); uimod.dll only reads it.

| Resolution | g | | Resolution | g |
|---|---|---|---|---|
| 1024x768 | 16 | | 1680x1050 | 21 |
| 1280x720/768/800, 1360/1366x768 | 16 | | 1920x1080, 2560x1080 | 22 |
| 1152x864, 1440x900, 1600x900 | 18 | | 1600x1200, 1920x1200 | 25 |
| 1280x960, 1280x1024 | 20 | | 2560x1440, 3440x1440 | 30 |
| 2560x1600, 3840x1600 | 33 | | 2560x2048, 3840x2160 | 40 |

**GOTCHAS:** wider isn't bigger (1920x1080 g=22 < 1600x1200 g=25); 16:9 screens up to 1366 wide stay at g=16 (native)
while W > 1024, so any gate on ScreenWidth > 1024 instead of g > 16 is a lo-res-gate bug there
([[feedback-loores-gate-on-g]]). Pre-existing helpers that model g height-only (tests g_for/_g, hook_setupwin.js
calcG, test_rw_kinds_parity reachable-screen rows) now use `scaling_laws.popup_g(w,h)` / `SL.popupG` (byte-parity
tested against 0x668200 + 0x668760; fix 10, 2026-10-18). ~49 legacy prototype hooks (hook_hudframes*, hook_hudfonts*, ...)
still carry a private height-only g -- convert if one is ever reused.

Stroke thickness convention: most strokes use `t=round(g/16)`; frame/border thickening uses `ceil(g/16)`; they diverge
when frac(g/16) < 0.5. Position scaling uses `popup_scale` (0x668750 = `imul eax,[g]; sar eax,4`, eax-only clobber).
Positional baseline res = 1024x768, see [[project-smac-scaling-baseline-1024]].
