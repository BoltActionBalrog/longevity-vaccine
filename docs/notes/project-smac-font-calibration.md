---
name: project-smac-font-calibration
description: SMAC popup font cell-height calibration (Arial Narrow size->cell); the A3 true-2.5x font fix
type: project
---

The popup body font is **Arial Narrow**; its GDI line-pitch (Font field +0xC "cell")
is what scales, NOT the nominal size. Measured on this DC (Frida active probe
`work\scripts\hook_font_probe.js`, calling Font_init 0x618F40 directly):

| nominal | 16 | 18 | 20 | 22 | 24 | 32 | 36 | 40 | 41 | **42** | 43 | 44 | 45 | 46 |
| cell    | 20 | 22 | 24 | 26 | 29 | 37 | 43 | 47 | 48 | **50** | 52 | 52 | 54 | 56 |

Native popup body = size16 -> cell20. The engine's `find_font` table CAPS at nominal 40
(cell **47** = 2.35x) -> that ~6% shortfall is the A3 bug (faithful 4K body = 20x2.5 = **cell 50**).
**Arial Narrow nominal 42 = cell 50** exactly (measured, not extrapolated). find_font can't
reach it (table maxed at 40), so the fix builds DEDICATED fonts via Font_init.

FIX (decided global per [[project-smac-scaling-baseline-1024]]): at popup-font setup
(thunk that hooks popups_normal 0x588460, currently `thunk_popup_setup_fonts`), replace the
three `find_font(g,0/1/2)` -> g_pf0/1/2 with a **calibration loop** that is faithful at ANY
resolution (no eyeballed magic number): target cell = `20*g/16`; Font_init "Arial Narrow" at
nominal starting = g, `inc` nominal until `[Font+0xC] >= target` (cap ~64); store the scratch
Font* into g_pf0/1/2 (variants 0/1/2 use flags 1/1/3; variant0==variant1 both flag1 so g_pf1
can reuse g_pf0's font). At g=40 -> size42/cell50; at g<=16 -> size16/cell20 (native, low-res
gate honoured). **Build ONCE** (guard on g_pf0!=0): popups_normal can run per-popup and
Font_init calls CreateFontIndirectA -> rebuilding each time would leak GDI HFONTs. Resolution
is fixed per session so one build is correct.
CONFIRMED IN-GAME 2026-06-13 (build 3217a242, unified trace): g_pf0=scratch0_font, cell=50, line
pitch=50 @4K (true 2.5x). Works as designed. The faction quote stayed 3 lines (NOT 4) -- that is a
GDI glyph-WIDTH nonlinearity (cell scales 2.5x but glyph advance only ~2.27x), NOT a size shortfall;
user ACCEPTED 3 lines as geometrically faithful, A3 closed (see [[project-smac-scaling-baseline-1024]]).
Font fix KEPT for proportionality (47px=2.35x was a 6% invariant violation).
FINALIZED 2026-06-13: patched_md5 lock 26b3eb64 -> 3217a242, regression suite GREEN (76 passed), CHANGELOG
line added. Blast radius: g_pf0/1/2 feed ALL popup fonts (title, body, list, button) -> RESIDUAL (low-risk,
non-blocking, calibration is resolution-derived + lo-res gated by construction): a broad non-4K sweep of popup
TITLE (taller text in fixed-height bar?) + BUTTON labels (clip?) + Customize Game Rules at 1920x1080 / 1600x1200
and an L2 numeric-golden refresh (line pitch 47->50) were NOT done exhaustively; spot-check opportunistically.
NOTE: a separate PRE-EXISTING bug surfaced during finalize review -- Planetfall (& likely other body-text popups)
body text crowds both L/R frame strokes (NOT the font; see (a private note) item (PF)). See
[[project-smac-modal-scaling]], (a private note), [[feedback-proportionate-scaling]].
Font field offsets now in terranx.h (+0xC cell, +0x10 glyph, +0x18 ascent, +0x1C descent).
