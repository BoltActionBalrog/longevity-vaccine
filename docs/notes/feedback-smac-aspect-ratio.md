---
name: feedback-smac-aspect-ratio
description: Project invariant: UI elements must preserve their original 4:3 aspect ratio at every resolution — never distort
type: feedback
---

For the SMAC UI scaling project, **all UI element scaling must preserve the element's original aspect ratio**. Use a uniform scale factor on both axes (never separate W and H factors). Concretely: `scale = min(ScreenWidth / 1024, ScreenHeight / 768)`, applied to both width and height. This produces letterboxing on non-4:3 displays (empty margin on the wider axis), never stretching.

**Why:** User stated explicitly during patch design (2026-05-28): "We always want to maintain the original 4:3 aspect ratio on UI elements. Never distort." Came as a course-correction after I proposed per-axis scaling (`W *= ScreenWidth/1024`, `H *= ScreenHeight/768`) following Thinker's `gui.cpp:1246-1256` convention. Thinker chose distortion-to-fill; this project chooses aspect preservation.

**How to apply:** When designing any UI-scaling patch, derive scaled dimensions from a single shared `scale_uniform` helper. Reject any design that uses separate W and H scale factors, even if it matches Thinker's prior art. The supersedes-Thinker call is intentional. v0.2 may revisit specifically the question of *where* to position letterboxed UI within the screen (centered, top-aligned, etc.) but never the question of whether to letterbox vs distort.

Side effect on the menu strip's strip-to-rect ratio: vanilla `354 / 300 = 1.18` is preserved exactly at every resolution under uniform scaling. This was a deliberate design ratio in the vanilla game; preserving it is automatic with uniform scale, would be lost under per-axis.

Related: [[project-smac-ui-scaling]], [[project-smac-openitem-strip]]
