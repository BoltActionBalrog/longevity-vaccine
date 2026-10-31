---
name: feedback-smac-all-resolutions
description: Project rule — every UI fix must look correct and not crash at ANY resolution, not just 4K; a resolution-gated stopgap is never "done"
type: feedback
---

Every UI scaling fix must look correct AND not crash at **any** resolution — not just the dev machine's 4K. A fix that only works at 4K (e.g. gated to `g=40`) is a STOPGAP, never "done."

**Why:** The dev/test machine is 4K, so it's easy to ship something that's secretly 4K-only and call it stable. It happened with the popup frame-thickening: the render-small-then-NN-enlarge blit overran the dest buffer at non-2.5× scales and crashed Customize Game Rules at 1920×1080 / 1600×1200; the "stable" build just gated thickening to 4K. The maintainer rejected it: "we want visual parity at all resolutions." No written rule had been violated — resolution-independence was only an *implicit* norm — which is exactly how it slipped through. It is now a written project invariant.

**How to apply:**
- Derive every lever from the runtime screen scale (`scale_uniform` / `g_popup_scale_num`), with a low-res `g≤16 → native no-op` gate, so it holds at arbitrary resolutions.
- Prefer techniques that don't depend on integer/2.5× scale factors (e.g. a multi-pass overdraw over a fragile enlarge-blit). Watch for off-by-one/rounding OOB at non-integer scales.
- Before marking a change confirmed, verify at 4K AND at least one non-4K res (`work\run-1920x1080.bat` / `work\run-1600x1200.bat` set the ini through run-at-resolution.ps1 and restore the original resolution on exit).
- A resolution-gated stopgap is allowed ONLY as an explicitly-flagged temporary state in the maintainer's work log — never reported as done, never CHANGELOG'd as done.

Distinct from [[feedback-smac-aspect-ratio]] (that governs *how* to scale — uniform, no distortion; this governs *that a fix must work across resolutions at all*). Live example: (a private note) #1.
