---
name: project-smac-popup-wrap
description: Popup body wrap width: how the engine sizes the text budget, and the thunk that scales it
type: project
---

# SMAC popup BODY wrap-width — DEFINITIVE (static RE, 2026-05-31)

**STATUS 2026-06-26: action item CLOSED as stale (no longer reproduces).** The May "box stayed ~622" defect
is gone — Frida (hook_wrapwidth.js, BasePop_calculate_dimensions 0x603800 onLeave, @4K) measured the Planetfall
popup `box_w[0x30bc] = 1555 = 622 × 40/16` exactly, i.e. the box now auto-sizes to the FAITHFUL 2.5× width and
the body fills it (user-confirmed by eye). Fixed incidentally by the later `boxw_scale` work, not the original
`popup_wrap_width`/thunk_wrap_budget patch. CHANGELOG entry added. The RE below is retained for reference.
(Hook gotcha for any re-run: g read from the transient scale globals 0x696D18/1C is WRONG outside the connector
draw — derive g from ScreenH 0x9B7B20; box widths alone prove the resolution. Buffer_wrap_height 0x5dc360 is
also called by tooltips/menus/help, so the body call is a needle — gate to large budgets or the popup ptr.)

Question: how is popup body text split into lines, and where is the wrap-width lever to widen the body column at 4K.

## ANSWER: runtime WORD-WRAP driven by a pixel-width budget (NOT pre-broken). It CAN be widened.

## Call path (body line list build)
- `BasePop_start` (0x601c10) reads the popup script file line-by-line (FUN_005fd570=read line, parse_string), and for each non-button text line calls `Dialogs_item` (0x612a70) — branch at 0x6025ad when `[popup+0x30a8]&4==0`.
- `Dialogs_item` (0x612a70) = jump table on element type `[elem+0x180]`. Text (case 1/4/8/0x10) -> `Dialog_item` (0x60c920) [Ghidra mislabels it `ListBox_item`; the real ListBox path is case 2 -> 0x609990].
- `Dialog_item` (0x60c920) appends ONE node per script line AND pre-wraps it for height via `Buffer_wrap_height`.

## THE WRAP-WIDTH LEVER (single best site)
`Dialog_item` 0x60c920:
```
0x60c938: mov edx,[0x9b8dd4]        ; DAT_009b8dd4 = text margin (runtime, 0xc/0x14 = 12/20px)
0x60c942: mov edi,[ecx+esi+0x2c]    ; edi = TEXT ELEMENT WIDTH  [elem+0x2c]
0x60c946: 2b fa  sub edi,edx        ; edi = element_width - margin = WRAP BUDGET (pixels)
0x60c94a: jle ...
0x60c958: call 0x5dc360             ; Buffer_wrap_height(string, edi)
```
=> body wrap width = `[elem+0x2c] - DAT_009b8dd4`. `[elem+0x2c]` is the text element rect width (auto-size default ~640 -> ~622px wrap observed).

## Wrap engine (proves word-wrap, not delimiter split)
- `Buffer_wrap_height` (0x5dc360) / `Buffer_wrap_2` (0x5dd530, render) / `Buffer_wrap_cent` (0x5dba30) all loop calling `Buffer_find_line_break_l` (0x5dc410) with a max-pixel-width = `*param_3` (the rect/budget width).
- `Buffer_find_line_break_l` (0x5dc410) handles SMAC format codes `{ } [ ] $ =` then delegates width break to `Font_find_line_break_l` (0x619370).
- `Font_find_line_break_l` (0x619370): `iVar5=*param_3` (budget); scans words via `_memchr(...,0x20)`; measures each word with GDI **`GetTextExtentPoint32A(DAT_009bb488, str, len, &size)`** (font=[param_1+8]); subtracts from budget; when `<0` breaks and backs up to last space (`memrchr ' '`). This is the char-width fn (NOT Buffer_text_width_2 — matches prior trace).

## Render side (same width source)
Per-row painters `FUN_0060d750`/`FUN_0060f030` re-wrap each node at draw time via `Buffer_wrap_2(str,&rect)` using the element rect width (derived from same box). Layout `FUN_0060ed10` measures each (already-wrapped) node string via `Buffer_text_width` (0x5dc790, whole-string, no newline logic) -> max = element natural width `[+0x64]` -> dialog content width `[+0x21fc/+0x222c]` -> box outer width `popup[0xc2f]`.

## Box/budget formula in BasePop_calculate_dimensions (0x603800)
- box outer width `popup[0xc2f]` = `[esi+0x30bc]` = content_width + 2*pad (sites 0x603b79 / 0x603bf2 / 0x603c06 / 0x603c19).
- body height wrap budget recomputed at 0x603d82-0x603da8 (C: `iVar1 = (popup[0xc2f] - 2*popup[0xc38] - popup[0x21c8] - popup[0xc36])`) and fed to `Buffer_wrap_height` calls at 0x603e09 / 0x603f03.
- Existing hi-res `(x*3)/2` guards (`if ... 0x3ff < DAT_009b7b1c`) exist in BasePop_init (0x6015b0) and calculate_dimensions, but ONLY on the explicit-size branch (`popup[0xa14]!=0` / `popup[0x285]!=0`). Auto-size body popups skip them — that is why the body scales tall-not-wide today.

## PATCH STRATEGY
Widen `[elem+0x2c]` (the text element width) for the body element, OR scale `edi` at 0x60c946 after `sub edi,edx` (2b fa, 2 bytes). Scaling edi here widens the per-line wrap budget -> more text/line -> wider measured lines -> wider auto-sized box; box outer width + render rect follow automatically. For 2.5x use *40/16. Co-opt the `0x3ff < DAT_009b7b1c` hi-res guard so it only applies at 4K. Caveat: `[elem+0x2c]` default itself may cap the box; confirm the auto-size default of `[elem+0x2c]` (set in Dialog_init_4/6/7 at 0x60931e/0x6094b9/0x60975c/0x609838) is >= desired width, else also widen that default. Render rect must agree with build budget or text clips — verify both `Dialog_item` (build) and `FUN_0060d750` (render) see the widened width.
