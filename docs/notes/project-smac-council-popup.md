---
name: project-smac-council-popup
description: Planetary Council pair CLOSED user-verified all-res (build 798b1660) — propose-picker mixed-space max double-scale + Council-button double-enlarge; the judge-at-the-flip-g lesson
type: project
---

**ARC CLOSED 2026-08-21, USER-VERIFIED "perfect at all resolutions", build 798b1660 (both fixes), committed.** The pre-existing Planetary Council pair (reported 2026-08-20, bisect-proven independent of diplo_talk_scale).

## Fix 1 — propose-picker too wide (`council_t16_measure`, site @0x60D5CE → `thunk_t16_measure_native` @pcave2+0xCD40)

**Root cause (the MIXED-SPACE MAX class, sibling of [[project-scaling-laws-harness]]'s itemlist_box_width):** the type-16 row measure (Dialog_type16_calc 0x60D380, `Buffer_text_width` call @0x60D5CE) ran with the dialog font — DEVICE at g>16 via the popups_normal font rewires — and its max-of-rows W entered the engine's `d5c = max(xs_clamped 658, W+3)−3` against a NATIVE term; thunk_scale_boxw's v3 arm then ×g/16'd the winner → double-scale whenever the measured branch wins (council propose: W=812 dev @g40 → row window 2030, box 2279 vs lawful 1886). Fix = measure with the native font `[0x9403D8]` (swap `[ecx+0x52C]`, measure, restore, RET 4; g≤16 tail-jumps the real fn = byte-path identity). Law `scaling_laws.t16_row_measure_width` + goldens.

**Why:** it was NOT font sublinearity — the calibrated 2.5× font measures linearly. Descale-then-rescale is UNSOUND for this class: the device value must never enter the engine max at all; enforce the native-input contract at the SOURCE (the measure), not in the consumer thunk (d5c has other native-semantics consumers: union frame 0x406238, wrap `idiv` budget 0x60D5FB).

**How to apply — JUDGE AT THE FLIP g:** a mixed max is branch-stable until the device term overtakes the native term. Here the native branch still won at g=25 → the defect was INVISIBLE at 1600×1200 and only expressed at 4K. "Verify at 4K + one non-4K" does not certify this class at the non-4K res — find/compute the flip g and judge above it. (Converse of [[project-smac-popup-scale-derivation]]'s g22<g25 lesson: each class has its own worst res.)

## Fix 2 — Council-button pressed-state banding (`council_btn_exclude`, `thunk_btn_gate_pre` @pcave2+0xC080)

The two COMMLINK Council FlatButtons (0x7FE80C SP / 0x7FF358 MP twin, stride 0xB4C, buffer +0x444=0x7FEC50) are drawn ALREADY device-scaled by thunk_hudmenu_sd2/hm_synth_core; thunk_btn_gate v8's popup-bracket label tail re-enlarged them ×g/16 on every pressed repaint (pressed ≈ only while the popup is up) → 2.5× applied twice = 5/7-8-px dither runs. Fix = 25B MISS wrapper ahead of the gate ([[feedback-wrap-dont-relocate-helper]] pattern: built-exe census found exactly ONE E8 caller, thunk_btn_shrink, repointed via `{rel32:thunk_btn_gate_pre}`; the v8 gate untouched). Never fix a double transform with a restripe family — remove the second owner.

## Diagnosis lessons (three wrong verdicts before the right one)

1. "Vanilla occlusion bug" — killed by the maintainer's pristine refs\pristine\Council.png (measure the pristine before accepting any vanilla-blame verdict).
2. "#xs ×1.5 bump compounding" — killed by the width probe: the engine's floor(3x/2) parse bump (0x601DAA/#xs, 0x601E31/#ys, guard ScreenWidth>=0x400) is ACTIVE at 1024, so bumped values ARE the vanilla-1024 baseline — [[project-smac-popup-xs-baseline]] reconfirmed, the parse-site debump is permanently WITHDRAWN. Sibling popups on the same screen (PROTOCOL election 633→1582, one-button 755→1886) were exactly lawful — a lawful sibling pins the defect delta precisely.
3. What settled it: hook_council_width.js (Interceptor at 0x404B10 + 0x603800 only — audited clean; ZERO hooks near the button cluster per [[feedback-frida-attach-branch-target]] hazard #5) at 4K AND 1024, + pixel-measuring the 4K screenshot. The g=16 run through OUR patched exe gives the vanilla baseline directly (byte-path no-op) — cheaper than a pristine-exe session when the g≤16 gates are trusted.

Engine facts banked in terranx.h: g_popup_font_native 0x9403D8, def-dialog font triple 0x9B8EC0/C4/C8, Dialog_set_def_dialog_font 0x609D20, the 0x60D618..0x60D6EC d5c formula, votes-panel x = ScreenW/2 + fl(512·g/16) − winW_dev (the 0x400 constant already scales live — panel was never the defect). Vanilla's ~13-native-px frame tuck under the panel with long rows is vanilla-faithful — do not "fix" it.

Probe gotcha: BasePop Dialog cells sit at popup+iv3+0x21FC/0x222C — a probe assuming iv3=0 reads garbage (the hook_council_width.js D2c=2/D5c=0 artifact); read box OUTPUTS (+0x30bc family) instead, they need no iv3.
