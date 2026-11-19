---
name: feedback-modern-line-matches-vanilla-drag
description: Modern Control Set visuals must equal vanilla's click-drag visuals under the same map settings; a stock setting may change the Modern line only as it changes vanilla's drag
type: feedback
---

Under any stock map setting, the Modern Control Set's move line must look identical to vanilla's click-drag line (owner, 2026-11-14, issue 8). A stock preference may affect the Modern line only where it affects vanilla's drag. Anything beyond vanilla gets its own Modern child setting, never a reinterpretation of a stock one.

**Why:** the first issue-8 fix gated the hover line on "Show go-to path when unit active". That setting never touches vanilla's drag line; it only hides a go-to unit's committed route. The owner had it reverted the same day ([[project-smac-mouse-scheme-proposals]]).

**How to apply:** before tying any Modern behaviour to a stock preference, find every engine test of that preference bit and check whether vanilla's equivalent gesture consults it. Present the vanilla comparison BEFORE building. "The reporter expects the setting to do X" is not a reason.
