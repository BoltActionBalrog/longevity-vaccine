---
name: feedback-frida-dedup-popup-reuse
description: Frida tracing gotcha — SMACX popups reuse the same heap pointer across opens, so dedup on CONTENT not the esi pointer or distinct popups collapse into one log entry
type: feedback
---

When tracing more than one SMACX popup in a single Frida session, do NOT dedup hook output by the popup object pointer (`esi`). Distinct popups (e.g. **Planetfall** and the **Quit** confirm) are allocated, freed, and **reuse the same heap address** across opens — so a per-`esi` `seen` Set silently merges them into ONE logged entry, and the second popup never appears (you'll think the trace "missed" it).

**Why:** cost ~4 wasted trace rounds on ITEM B (2026-06-26): kept getting only one boxW-1555 popup with an art line; it was Planetfall's frame data + Quit's art draw mixed under the same reused ptr. The discriminator field couldn't be found until the dedup was fixed and both popups logged separately.

**How to apply:** key the dedup on per-open *content* instead of the ptr — e.g. the popup's per-open heap allocations (`[esi+0x2188]` text ptr, `[esi+0xa48]` header ptr), or the title string at `[esi+0xa48]` (read an ASCII preview: Planetfall a48="PLANETFALL!", Quit a48="SID MEIER'S..."). A composite like `[0x2188]_[0x218c]_[0xa48]` is robust. Also LOG that key/preview so you can tell which popup each line is.

Corollary: don't assume same-looking popups are the same size — Quit is **boxW=2080** (image-left/text-right), Planetfall is **boxW=1555** (full-width text). See (a private note) (ITEM B) and the established entry-hook rules in [[project-smac-modal-scaling]] / skill `frida-tracing`. Related no-op gotcha: [[feedback-hline-zero-span-noop]].
