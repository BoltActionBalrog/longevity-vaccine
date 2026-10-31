---
name: feedback-site-keyed-table-shared-painter
description: A return-address-keyed rect/param table is wrong for any call site that serves more than one element (shared painters, alternating panels)
type: feedback
---

Never key a substitute rect/param on the caller's RETURN ADDRESS alone unless the site provably draws ONE element. Census each site's engine rect across STATES first; when a site serves several elements, discriminate on the engine's own argument (e.g. which side of a column split the rect lies on), in ONE coordinate space.

**Why:** thunk_hud_boxframe v1's NAT table mapped the two InfoWin shared painters (ret 0x45910D reset / 0x4564A7 layout) to the LEFT box-5 panel rect. The engine alternates panels (InfoWin_reset 0x458FF0: cur=(cur-1)&1) and its panel CLEAR is that very Buffer_box_sprite(d7f8) draw (d7f8 is a FILLED set), so the right panel was never cleared (typewriter cursor ran over old text, stale text under the scenario-editor palette) and the left was wiped while displayed. Invisible in a still screenshot; found 2026-09-18 with a pre/post panel-histogram probe (hook_infowin_clear.js). Fixed exe 84456078 (user-verified, committed in 7908af05), law scaling_laws.hud_boxframe_rect. Same family as [[feedback-draw-state-multiplicity]].

**How to apply:** when building any site-keyed table (NAT rects, imm tables keyed on ret), log the engine args per site over a full state cycle and assert one-rect-per-site before baking; a box-sprite draw of a FILLED set may be the engine's CLEAR — substituting its rect moves the clear. Strip Buffer pitch is +0x4A8 (not +0x4A4); HUD runtime fill pair = palette 196/65.
