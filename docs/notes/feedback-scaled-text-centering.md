---
name: feedback-scaled-text-centering
description: Why enlarged (popup_scale) vertically-centred UI text sits too low in SMACX, and the standard upward-nudge fix — apply when scaling any centred dialog/button/title text
type: feedback
---

When a font is enlarged via popup_scale (~2.5x @4K), **vertically-centred** text sits visibly **too low**. The text is geometrically centred — the artifact is that the engine's centred writers centre on the font **line-box** (ascent+descent) while the visible glyph **ink** (caps, no descenders) rides high in it. The offset scales with font size: ~1px native (invisible), ~3px at 2.5x (visible).

**Why:** confirmed in-game on the popup title bar (build ee0a6d70, "the change is good"). It does NOT apply universally — see the FlatButton counter-example below.

**How to apply:**
- The bias exists only when the writer centres on the **line-box**. Writers/callers that measure the **tight glyph height** themselves are already ink-centred and need NO nudge. Identify the centring source first, and ALWAYS test before committing.
- Needs it: line-box-centred scaled text (title bar via Buffer_write_cent_l_7).
- Does NOT need it: FlatButton labels — FlatButton_content_draw measures its own text height and centres on it (already ink-centred); nudging made them sit too HIGH (build 19f1f860, reverted in 1f4cfa3e; site FlatButton_content_draw.btntext_nudge left status=skip).
- IMMUNE (anchored, not centred): list rows (FUN_0060f030), wrapped body — never touch.
- `call_target_redirect` the centred-text draw (or its preceding Buffer_set_font) to a cave thunk that subtracts `N=(g-16)/8` from the vertical coord, then tail-jmps the real fn (`push <fn>; ret`, stack intact). `N`≈3px @4K, 0 at g<=16 (lo-res no-op).
- Adjust whatever the writer consumes: a RECT top+bottom (re-centred by the writer) or a pre-computed centred-Y arg on the stack. Tune via the shift (`sar ,3`=/8 ~3px -> `sar ,2`=/4 ~7px).
- **Never** bake the offset into the font itself — it would shift every anchored field that is currently correct. Correct granularity = one per-call-site thunk; there are very few.

Examples: thunk_title_textnudge @0x4060aa (Buffer_set_font before Buffer_write_cent_l_7); thunk_btntext_nudge @0x608441 (Buffer_wrap_cent_4, Y arg at [esp+0x10]). Full write-up: project skill `docs/skills/scaling-text.md`. See (a private note), [[project-smac-modal-scaling]].
