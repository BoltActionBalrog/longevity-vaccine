---
name: feedback-game-font-synthetic-bold
description: In-game "Arial Narrow bold" is GDI SYNTHETIC bold of arialn.ttf (the game registers only arialn.ttf) -- GDI font emulation must load arialn.ttf ONLY
type: feedback
---

The game registers only `arialn.ttf` (the only font-file string in terranx_PRACX.exe / terranx.exe / the DLLs), and
Arial Narrow is not installed system-wide here. So every in-game "Arial Narrow" weight-700 font (find_font pool,
g_pf0/g_pf*, list rows, popup titles at g > 16) is GDI's synthetic bold of Arial Narrow REGULAR, about 9% wider than
the real `arialnb.ttf` face.

**Why:** 2026-10-18: one investigator measured with no Arial Narrow loaded (Windows fell back to
Arial) and "found" a faction-picker label overflow that did not exist; the fixer then loaded all four AN files and got
widths 9% too narrow. The fix-12 reviewer matched the maintainer's 1024x768 "SELECT A FACTION" title pixel-exactly
(136x11, 524/524 px) only with arialn.ttf alone.

**How to apply:** any ctypes/GDI emulation of game text: `AddFontResourceExA(<game dir>\arialn.ttf, FR_PRIVATE)` and
NOTHING else from the Arial Narrow family; Arial (system font) needs nothing. Treat any width/overflow result measured
otherwise as unverified. Related: [[feedback-font-metric-sublinearity]], [[project-smac-font-face-weight-audit]].
