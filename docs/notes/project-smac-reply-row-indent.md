---
name: project-smac-reply-row-indent
description: Type-16 reply rows (diplomacy replies, Quit menu): button-edge -> text channel stayed native 3px; scaled in-register at the painter read 0x60DB8B by uimod rowindent.cpp (DLL 7e4d3dac) -- BUILT 2026-09-19, awaiting in-game verify
type: project
---

Type-16 dialog rows are painted by `Dialog_type16_draw_item` 0x60D750; text rect.left = row.x + Dialog[+0x34]
(text indent, native 3, written at 0x404D3F in Popup_calculate_dimensions; 0x1B for type 1). Measured 2026-09-19:
pristine TechTrade/CommlinkTrade 11-12 px at 2.8125x (= 4 native incl. glyph bearing) vs ours 4-5 px at 2.5x
(should be 10). Row height / font / vertical centring were already proportional.

Fix = uimod `rowindent.cpp`: 6-byte detour at 0x60DB8B (`mov edx,[ecx+esi+0x34]; add edi,edx`), edx = edx*g>>4 when
g>16, never stored. Law `scaling_laws.t16_row_text_indent` + tests. Cave-free (g read from 0x668740, zero on the
unpatched exe -> native).

**Why at the read:** the stored field is the F term of `t16_row_measure_width` (native-space max(xs, W+F)-F) --
scaling the writer would narrow xs-won boxes. See [[feedback-shared-field-one-owner]].

Left alone: the second read 0x60DCF7 (right column rect of '|' two-column rows, council popup verified).
The painter supports MULTI-LINE rows (Buffer_wrap_2, per-item line count) -- the diplomacy replies did not wrap,
cause not investigated (user chose shorter text, see [[project-smac-ai-cloak-visibility]]).

Status: BUILT, deployed 7e4d3dac, uncommitted; needs user check at 4K + one non-4K, and a look at other type-16
popups (Quit menu etc.).

2026-09-19 measured on user shots (first build, floor): 4K gap 4-5 -> 8-9 px (law 7 + glyph bearing) OK; 1920x1080 (x2 stretched capture) ~4-5 real px OK; 1600x1200 (x1.8 stretched) only ~3 real px -- floor(3*25/16)=4 loses 0.7 px. Switched the law to scale_px/half_down ((2vg+15)>>5): 3,4,5,7 at g=16/22/25/40 (4K + 1080 unchanged, 1600 +1). DLL 7e4d3dac. Stretched captures are bilinear-blurred: +-1 device px measurement error.

2026-09-19 build 7e4d3dac measured on user shots at 1024x768 / 1600x1200 / 1920x1080 / 4K (quote-row gap, device px
on the 4K display; pristine = 11-12): 1024 9-11 (no-op, = pristine within capture blur), 1600 8-10 (was 6-8),
1080 10, 4K 9 @2.5x. Rows, centring, fit all good. USER-SEEN at all four; not yet explicitly confirmed/committed.

FINDING (same shots): type-16 rows DO wrap to two lines natively -- at 1024x768 the 88-char "likewise ... (Including
undetected cloaked troops)" reply wraps and the button doubles in height (Dialog_item word-wrap + the painter's
per-item line count). At g>16 the same text fits on one line (font-metric sublinearity), and the earlier 97-char text
CLIPPED at 4K instead of wrapping: the wrap budget at g>16 is wider than the drawn row. Latent scaling defect for any
reply between ~92 and the budget; not fixed (no vanilla string known to hit it).

2026-09-20 WRAP FIX, second attempt (MEASURED this time) -- exe 6986cfe7 (diff vs 7d407602 = site rel32 + 42B thunk),
DLL c2fe6c0b (diagnostics removed; still carries the TEMP long GETOUT suffix). AWAITING user verify.
- FIRST ATTEMPT WAS WRONG (exe 1b96bd37, reverted): I modelled the cause as thunk_item_wrap_budget double-scaling in
  Dialog_item 0x60C920 and patched it without measuring. uimod wrapdbg log showed type-16 replies NEVER reach 0x60C920:
  Dialogs_item 0x612A70 byte table -> types 1/4/8/16 go to 0x609990 (lines := 1, no wrap); only type 2 goes to 0x60C920.
  terranx.h's "Dialog_item 0x60C920" note is the TYPE-2 adder. Lesson: measure, don't model.
- REAL CAUSE: Dialog_type16_calc 0x60D380 sets each row's line count = W / budget + 1 at 0x60D5FA (idiv ebp), budget =
  [+0x2C]/cols - 2*[+0x40] - [+0x34] (only when flags&2 and [+0x2C]!=0). W comes from the measure site 0x60D5CE, which OUR
  thunk_t16_measure_native makes NATIVE-font at g>16 (right for ordinary popups: [+0x2C] = native #xs). ANCHORED popups
  (pops_18's second BasePop [0x9BC074], +0xA14 = DiploTalkWin 0x733990) have [+0x2C] = DEVICE parent width (log: 1750 @g40,
  700 @g16) -> native W / device budget = 0 -> always 1 line -> clip.
- FIX: thunk_t16_measure_sel @pcave2 0x16DA0 heads the site: [0x9BC074] non-null && [+0xA14]!=0 && esi inside that object
  -> real Buffer_text_width (device font); else -> thunk_t16_measure_native. In the fixed-width branch W feeds only the
  line count. Law scaling_laws.t16_row_line_count. Not covered: anchored BasePops OTHER than [0x9BC074] (programmatic
  diplomacy menus via Popup_start_3/BasePop_item) keep the old behaviour.
- pops_18 uses two BasePop objects: [0x9BC078] (ordinary, flags 7, #xs native) and [0x9BC074] (anchored, flags 3).

2026-09-20 third pass (MEASURED at the idiv 0x60D5FA via a temp DLL stub): with exe 6986cfe7 the anchored measure IS
device (W 1496 for the 97-char reply) but budget 1498 -> lines 1, yet the text clips: the painter's text width is
[+0x64] - indent = budget - gap[+0x44] - (indent_dev - indent) ~ 1488. The engine's budget is `gap` px too wide in
VANILLA (3 px slip) and our scaled indent adds 4 more @g40. The "barely overflowing" test text landed exactly in that
10 px window. Fix = uimod rowindent.cpp second site: 5-byte detour at 0x60D5FA, divisor := budget - gap - (scale_px(indent)
- indent) for the anchored popup at g>16 (law t16_row_text_budget; ebp restored for the loop). BOTH fixes are needed:
measure_sel (device W) + the drawn-width divisor. DLL 2e255f9d (still the TEMP long suffix). AWAITING user verify.

2026-09-20 CLOSED: user-verified at 4K/1600/1920/1024 with the long test suffix (2-line button everywhere), short suffix restored (DLL 14ae5dae), committed + pushed.
