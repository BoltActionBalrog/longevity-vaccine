---
name: feedback-font-law-snapped-size
description: t_ffn/font_face_law scale the REQUESTED size; vanilla renders find_font's SNAPPED size (26->24, 11->12) -- scale the snapped size
type: feedback
---

`find_font(S, v)` snaps S to the pool table (40,36,32,24,22,20,18,16,14,12,10,8; ties go to the larger), so a
painter that asks for 26 draws Arial Narrow 24 bold and one that asks for 11 draws Arial 12. The project's
`font_face_law` / `t_ffn(S, v)` scale S itself, giving fl(26*g/16) / fl(11*g/16): too big for 26, too small for 11
(4K: title AN 73 instead of 67, list Arial 30 instead of 33). Glyph-proven 2026-11-15 on the Holobook pristine
(`work\_hb_static_map.md` d2: every ink pixel matched with AN24b / AN18 b+i / Arial 12).

**Why:** "vanilla x g/16" means what vanilla RENDERS, and the pool snap happens before rendering.

**How to apply:** for any request size not in the pool, scale `find_font_snap(S)` (same face/style as vanilla),
not S. The report family's (11,0) and (26,0) slots in `assemble_rw.FONTS` use t_ffn(S) -- unaudited against
this; check before reusing them. Emulate GDI only with the game's `arialn.ttf` registered alone
([[feedback-game-font-synthetic-bold]]); line pitch is still sublinear ([[feedback-font-metric-sublinearity]]).
