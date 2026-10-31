---
name: project-smac-namebase-popup
description: Namebase/pop_ask in-game popup — CLOSED 52ef21b4 all-res (vanilla min-boxh-300 clamp scaled + type-4 field ring inner-flush); left-rail defect was downstream of the short window; engine facts for the whole in-game popup family
type: project
---

**2026-07-16: CLOSED — VERIFIED RELEASE LOCK 52ef21b4 (user confirmed ALL resolutions;
committed). Namebase popup "too low + short" ROOT-CAUSED and BAKED as group
`popup_ingame_min_boxh`; Name-field ring outer-flush fixed by pf_union_align v7 (container arm
{1,2} → {1,2,4}). Accepted side effect: small in-game popups (quit confirm, Disband) sit
taller/higher — vanilla's own clamp, previously missing at scale.**

Engine facts (all measured — decompile + pristine `refs\pristine\NameBase.png`, a 1024×768
capture pillarboxed in 3840×2160, content scale ×2.8125, content left edge x=480):

1. **The in-game popup MIN-HEIGHT law**: `Popup_calculate_dimensions` (0x404B10) tail @0x404EBD:
   in-game popups (mode `[+0x30ac]/10000` ∈ {0,5}, console `Win_is_visible(0x7ae820)`,
   `[+0xa14]==0`) get `if (box_h < 300) { footer_reserve[+0x30ec] += 300−box_h; box_h = 300 }`.
   `Popup_show` (0x404920) then bottom-anchors: `Win_move((SW−w+0x20)/2, SH − g_console_strip_height
   − h)`. So vanilla's tall mostly-empty body below a short popup's OK row AND its high placement
   are BOTH this clamp (pristine namebase: content ≈136 → box 300 → top = 768−213−300 = 255).
   At g>16 the native 300 went dead (any scaled content exceeds it) → box hugged content and sat
   low (@4K measured: box 349 → top 1279; faithful 750 → 877). FIX: thunk_popup_min_boxh
   (pcave2+0xB2C0, 51B, src `scripts\assemble_popup_minboxh.py`) displaces the whole 44-byte clamp
   block; law `scaling_laws.ingame_popup_min_boxh`: M = floor(300·g/16), box′ = max(box, M),
   footer += box′−box. Vanilla gates stay in front of the site → main-menu popups / TutWin /
   ticker (`[+0xa14]!=0`) exempt exactly as vanilla. Unicorn parity
   `tests\test_minboxh_asm_parity.py`. **Side effect to expect at verify: ANY small in-game popup
   (quit confirm, Disband) may now sit taller/higher than the pre-2026-07-16 locked look — that
   is vanilla's own clamp, previously missing at scale.**

2. **#FIRSTBASE script**: `#x 10 #y 40 #xs 320`, no `#ys` (Script.txt/xscript.txt line ~901).
   The popup is dlg_type 4 (single text-entry): `Dialog_type4_attach` @0x611AF0 (recorded in
   terranx.h) places the dialog window at (body_left, body_bottom) with h = `Dialog[+0x60]` =
   `line_height + gap` per row (`Dialog_type4_calc_dimensions` 0x612150) — the entry row itself
   is SMALL; the tall body is entirely the min-height clamp's footer, NOT a dialog area.

3. **Button row is bottom-anchored WITHIN the box**: exec_3 y = box_h − footer − pad − btn_h
   (0x602600, vtbl+0x178 transform). Because the clamp pours into footer, OK stays directly
   under the content — scaling the min preserves that automatically.

4. **slide_show settled rail geometry** (0x45D440, sites 0x45D82C/51/75/A9, dest = win+0x444):
   left strips at window-local x=0 (15-wide, sprite 0x7CFFC4) and x=15 (8-wide, 0x7CFFF0);
   right strips at x = winW−32−wD−wC (0x7D001C) and winW−32−wD (0x7D0048) — the 32 = the
   in-game popup's right slack (margin asymmetry 33/67). Sites 1&4 clamp their y to screen
   y≥238 (`(SW!=800 ? 0xEE : 0x5E)`) and take the slide loop's FINAL esi — if the slide
   animation branch is skipped (pref flag 0x9a6490&0x8000000 off or 0x93f660 set), esi stays at
   window BOTTOM and those two strips are clipped invisible. Window width @4K namebase = 1449
   (native 580), window left = (3840−1449+80)/2 = 1235 (the +80 = scaled center nudge ✓).

5. **RESOLVED: left-rail internal features** — after the min-height fix landed, the rail's
   light/dark profile matches pristine COLUMN-FOR-COLUMN in native units (measured: both rails
   binned to 24 native cols, ours ÷2.5 vs pristine ÷2.8125, y-averaged over the rail span; max
   deviation <8 lum at sub-column band boundaries). The pre-fix anomaly (light band ~×0.73 of
   expected) was downstream of the SHORT window — no rail-draw defect existed. Lesson: don't
   chase secondary pixel defects inside a window whose geometry is known-wrong; fix geometry
   first, re-shoot, then re-measure. Also: judge band widths from a y-AVERAGED profile, not one
   row — the rail texture (slots) makes single rows lie by 1-2 native cols.

6. **2026-10-03 law v3 (exe 43a98bcc, awaiting user verify): M is the WINDOW height, not box_h.**
   exec_3 creates the window box_h + D tall (D = thunk_grow_box's s(btn)−btn at 0x602861, btn =
   [+0x30d0] = 20 or 0 at the clamp), so v1 above left every clamped popup D too tall and D too
   high (top 848 vs faithful 878 @4K — the "877" above is off by one; 369 vs 376 @1920). Box target
   = M − D when the popup owns its window ([+0xa3c] == popup), M when embedded in a parent (never
   grown). Thunk RELOCATED to pcave2 0x3B0 (72 B). The tall empty body and the bottom frame hidden
   behind the HUD silhouette are VANILLA (pristine BlindResearch.png), not a defect.

**Why:** the "popup centered too low" read as a positioning bug; the position law was already
correct — the HEIGHT was the mover (bottom-anchored geometry converts a height shortfall into a
placement error). Measure the anchor law before touching position code.

**How to apply:** for any in-game popup that looks content-hugging or low vs pristine, check the
min-height clamp fired (box_h ≥ floor(300·g/16)) before hunting layout sites. Related:
[[project-smac-popup-xs-baseline]], [[project-smac-popup-chrome]],
[[feedback-proportionate-scaling]].
