---
name: project-smac-a5-portrait-frame
description: A5 faction quote-box portrait green-frame clips to black on right/bottom @1600x1200 — root cause = OUR frame patches
type: project
---

A5 defect: the faction "Choose Your Factions" quote-box LEADER PORTRAIT (Sprite_draw_2 @0x5E4B4A from BasePop_on_redraw 0x604AB0, 131x157 sprite scaled g/16 into box buffer 0x940824) loses its green frame on the RIGHT + BOTTOM at 1600x1200 (g25) — gold ends into a ~18px black band. Fine at 4K (g40) + 1920x1080 (g22).

CORRECTED ROOT CAUSE (2026-06-14, user-verified twice): PRISTINE draws a COMPLETE green frame hugging the portrait on all 4 sides (vanilla terranx.exe cc659f AND PRACX base .bak; confirmed at 1600x1200 via work\run-pristine-1600x1200.bat, and refs\pristine\FactionSelect_Drones.png vanilla high-res). My earlier "no frame on right/bottom by design / frame is proportional, NOT the bug" conclusion was WRONG — do not repeat it.

The bug is OURS: the faction-quote frame patches ([[project-smac-modal-scaling]] family — thunk_d528_inset's popup_scale(4) LEFT push, the concentric inset, thunk_box_thick_hollow stroke-thicken) moved the quote frame's left/bottom VISIBLE stroke off the portrait. Rect-level gap is proportional (~10px@g40 / 6px@g25) but the d528/d5a0 9-slice LEFT-corner visible inset is drawn ~NATIVE (~6px, NOT scaled by g) and the portrait gold NN-underfills at small g → at g25 the fixed corner inset is proportionally huge → ~18px black band, no hugging stroke. The recent "PORTRAIT-LEFT-OVERLAP fix / +popup_scale(4) clear of the portrait" over-corrected — pristine WANTS the stroke butting the gold.

TEST 2026-06-15 RULED OUT the push: a one-NOP build (MD5 74efcd85) backed out ONLY `local_38.left += popup_scale(4)` in thunk_d528_inset (01 18 -> 90 90), so the outer d5a0 left edge = native (butts the portrait). User tested @1600x1200: NO improvement, right border still black. So the "+popup_scale(4) clear / overlap fix over-corrected" theory is WRONG. Reverted to 897fdc84.

REFINED FINDING (box-buffer gap scans frida_faction_portraitgap.log, exact coords — TRUSTWORTHY): the defect is the RIGHT (vertical) green stroke COLLAPSING/DARKENING, not a position shift. g40 RIGHT: bright green idx 65 ~13px hugs portrait (x347 vs right 348). g25 RIGHT: NO idx 65 — content -> dark idx 198 -> only ~2px dark idx 34 -> blue panel 196 (the dark 198 between portrait and stroke = the "black band"). BOTTOM hugs green at both g (g25 green starts y255 vs bottom 257) — so the bottom is far less broken; visible bottom-black is likely the gap BELOW the portrait (bottom 257 vs box bottom 291), not a missing stroke. RIGHT is the primary defect.

NEXT (not push position): why does the RIGHT vertical stroke collapse to ~2px dark at g25 while the horizontal bottom renders full green? Suspects: thunk_box_thick_hollow_flat in-place thicken on vertical strokes; inner d528 vs outer d5a0 right strokes overlapping/cancelling; NN-scaling sampling dark dither columns at g25. Get PRISTINE box-buffer scan in same coords (hook_faction_portraitgap.js is base-game-addr only -> runs on pristine; needs a pristine-exe frida runner).

Runtime pins: g40 portrait X=20 Y=12 out 328x393 box 1805x455; g25 X=10 Y=12 out 205x245 box 1126x291. Tools built: work\run-pristine-1600x1200.bat; work\scripts\hook_faction_portraitgap.js + run-frida-portraitgap.bat + launcher shortcuts "SMACX PortraitGap 4K/1600x1200"; refs\pristine\FactionSelect_Drones.png. See the maintainer's work log A5 + (a private note) + [[project-smac-modal-scaling]].
