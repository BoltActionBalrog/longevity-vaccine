---
name: feedback-font-metric-sublinearity
description: Font line metrics are SUBLINEAR in font size — any layout mixing a metric with scaled constants under-scales; replace the metric with fl(native_metric·g/16), never trust metric(scaled_font)
type: feedback
---

Engine font line heights are NOT proportional to font size (measured, SMACX `0x5dac70` metric block: size 10 → 13, 13 → 17, 15 → 18, 16/18 → 22, 25 → 27 — roughly f+3/f+4). So scaling a FONT does not scale the layouts derived from its metrics: at g=25 the queue font scaled 10→15 but its line height went 13→18 where faithful is 20.3. Two user-visible defects came from this in one day (2026-07-25): queue slot rows cramped at every scaled resolution, and garrison stat digits clipped at the panel bottom (y = bottom − metric + s(6) sat 2-3px low).

**Why:** metrics carry additive leading that doesn't scale with glyph size, and the engine's layouts (row pitch via repeated `y += line_height`, bottom-anchored text via `bottom − line_height + k`) consume the metric directly.

**How to apply:**
- When scaling a layout that reads a font metric, MEASURE the native metric (pristine screenshot or metric trace), then substitute `fl(native_metric·g/16)` on the scaled path; keep the engine's metric read on the g≤16 path so native identity holds by construction (robust to localized fonts).
- For repeated advances (row pitch), use the cumulative form `cum(i)=fl(native·i·g/16)` and hand back `cum(i)−cum(i−1)` per step — [[feedback-remainder-distribution]].
- The metric block layout at the strip fns: `+0 leading` (−1 = use +0xc), `+0x10 base height` (h = +0 >= 0 ? +0x10 + +0 : +0xc).
- Worked examples: `t_qrow_h_ecx/eax` + `t_garr_statsy` v3 in assemble_strip_content.py; laws `basewin_strip_queue_row_y/_advance`, `basewin_strip_garrison_stats_y`.

Related: [[feedback-remainder-distribution]], [[project-smac-base-screen]], [[feedback-wrap-width-desync-line-step]].
