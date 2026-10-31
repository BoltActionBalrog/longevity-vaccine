---
name: project-smac-monument-screen
description: Planetary Monument screen (F9; far pyramid view + near plaque view) scaling arc — ARC CLOSED: BAKED 2026-09-14 as mon_scale (patched_md5 ec11b091, src assemble_mon.py), USER-CONFIRMED at 4K/1600/1080p + CHANGELOG; proto v7d was measured-correct; user decided full-height 4:3 letterbox for this AND Hall of Fame
type: project
---

**Status 2026-09-14: BAKED as group `mon_scale` (patches.yaml patched_md5 ec11b09137e19b432e5c270dd655984c, 1133 sites, pcave2
grown 0x2B000->0x2D000; src `work\scripts\assemble_mon.py`, laws `scaling_laws.py` "PLANETARY MONUMENT", tests
`tests\test_scaling_mon.py` + `tests\test_mon_asm_parity.py` all green) -- USER-CONFIRMED 2026-09-14 at 4K + 1600 + 1080p (19 shots measured:
letterbox exact, faces 3/3 | 2/1 dark-on-top every state); CHANGELOG line added. ARC CLOSED (live exe ec11b091). Apply via
run-apply-patches.bat. Bake shape (proto levers verbatim): t_mon_build wraps
monument()'s one `call load_monicons` (window resize+clear, content rect, tables A/B/C, buttons resize/move/font/redraw);
copy_4 sites -> Lanczos-3 + FS resampler thunk (t_mon_resample; LUT per open from the DEST canvas table); near backdrop + panel
scanline synthesis (t_mon_panel); keyed sprites -> thunk_sprite_scale_nn at num/16, opaque pictures -> the resampler; plaque
font detour; CLOSE/BACK admitted via t_mon_gate wrapped at thunk_btn_shrink's E8 (rw region full, gate_pre untouched); faces
restriped by a detour at Buffer_draw_2 ENTRY keyed on the two canvases. The Frida shortcuts still carry the proto -- never run
it on the baked exe. LESSONS in the maintainer's work log (Unicorn ctl_remove_cache for rewritten stubs; 15-bit-exact palettes for LUT
property tests; the law guard's substring scan). NEXT after the check: CHANGELOG line, then the Hall of Fame bake (same design,
HOF_BRIEF.md). Earlier: PROTO v7d measured-correct at 4K + 1600 + 1080p (window/tables/backdrops/panel/buttons); stripe phase law = darker member on top (pristine row 0); NEXT = bake.** Earlier v7c: (far/near 'look great', buttons scaled + scanline faces restriped at composite time). Bake next; laws listed in the maintainer's work log. Earlier:  census RUN at 4K confirmed the static map exactly; PROTO v1 `hook_monument_proto.js` armed on all shortcuts (whole-screen window via GraphicWin_resize 0x5D5540 + +0x13C/+0x474 pokes, FULLHEIGHT num/den=SH/768 because the g=40 cap gives only 1920 of 2160 at 4K, tables = letterbox + s(native), copy_4->copy_3, G bracket at sbc entry keyed on 9 rets, buttons moved). AWAITING user shots. Files: `work\_mon_static_map.md` (authoritative engine
map), `work\_mon_probe_design.md` (attach audit script), `work\scripts\hook_monument_census.js` v2 (gitignored,
on disk), decompiles `work\_mon_dec_*.txt` / `_mon_dis_*.txt`. Symbols in `terranx.h` "Planetary Monument" section.

**USER DECISION 2026-09-13:** both full-screen menus — Hall of Fame ([[project-smac-report-screens]], `work\HOF_BRIEF.md`) and
the Monument — get the **full-height 4:3, centred, letterboxed** look: window s(1024)xs(768), uniform scale, no per-axis
distortion of text or images. This closes HOF's tabled "full-screen vs g cap" question.

**Engine facts (static, all-observed):** `MonumentWin_g` 0x7F9F58 (GraphicWin 0x36DC B, vtbl 0x66C880); `monument(int)`
0x476A50 cdecl: arg 0 = F9 / menu id 0x110 (Console_on_key_click @0x51A852, Console_menu_proc @0x51C327) -> FAR view;
arg 1 = the 16 `mon_*` milestone triggers -> NEAR plaque view (gated on GameState/movie prefs). **The two flows differ ONLY
in that argument**; build (`load_monicons` 0x472230, fastcall) and painter (`MonumentWin_draw` 0x4736E0, fork on +0xA4C
@0x47378F) are identical. View state = +0xA4C (0 far / 1 near, alias 0x7FA9A4); selection +0xA54 / `Monuments[fac].selected`.
Wide branch: `GraphicWin_init((SW-1024)/2, SH-768, 1024, 768)` bottom-anchored (same shape as HOF); content rect
(112,84,912,684); all rect tables authored in 800x600 space and translated in place (+0x3134 A: far pic window
(319,202,479,299)c, text (256,131,771,175)dev... , near pic window -> dev (213,202,813,562) = 600x360; +0x334C B banners;
+0x366C C glyphs + emblem). `monument.flc` = 13-frame zoom-in still decoded ONCE at build into +0x20FC (frames advanced
= milestone count; NO animation, NO Time callback); far backdrop = copy_4 1:1 @0x4760E2. Near backdrop = monzoom1.pcx
(count<5) / monzoom2.pcx into +0x2684, copy_4 @0x4737E9; near picture = `monbigN.pcx` 600x360 1:1 (no monbig13 -> faction3.pcx
path); plaque text = TextList_load("monument", KEY) + `Buffer_write_strings` @0x475E8D into +0x3144 with font [0x8A40BC];
blue box is part of the pcx art (no fill/box calls on this screen). Far sprites (44x42 icons, 160x97 picture, banners,
58x50 glyphs, emblem) go through `Sprite_blit_scaled_core` — a baked-detoured entry, Frida-invisible -> recovered from
canvas dumps + the object's rect tables. Two FlatButtons +0xA58 CLOSE / +0x15A4 BACK share id 0x3E7 (gate on address),
rect (824,747) 200x21 wide, bevel triple 0x78DC80/58/30 (same as HOF CLOSE). Handlers: lclick 0x476780, move 0x476850,
key 0x476A00 (any key = back/close), button 0x4769B0. Latent vanilla OOB: far icon loop runs 15 over 14 rects (H1).

**Probe design lessons:** the attach audit diffed the first 8 bytes of every candidate entry live vs .bak (not a yaml grep):
Sprite_draw_2, Sprite_blit_scaled_core, Buffer_set_font, BaseButton_init, write_cent_l_5/7, multi_font_raw_l are NOW baked
detours — `hook_report_census.js` is stale. PRACX `_cx(A,B)`: A = SMAC terran.exe address, B = SMACX; the 0x47xxxx hits in
pracx.cpp are the SMAC column (0 real hits). `terranx.h` double-claims 0x616730 (Time_stop vs Sprite_draw_multi_table_dest_2).

**Pristine refs:** `refs\pristine\HQData\MonumentClose.png` / `MonumentFar.png` (2.8125x PRACX shots = exactly the target look:
1024 native wide content, full height, letterboxed). Offline-decoded FLC frames + monzoom/monicons PNGs were in the session
scratch (regenerate with flc_census.py's decoders + PIL).

**Next:** user runs the probe (4K + 1600 + 1920 + pristine 1024, F9 flow + a fresh-milestone flow), then port the HOF proto
levers (window/content/backdrop copy_4->copy_3 or bilinear, button cells, btn gate) into a `mon_scale` bake alongside HOF.

**2026-10-18 (fix 11, user-approved):** num = min(floor(16*ScreenH/768), floor(16*ScreenW/1024)) via scale_uniform(16) (was height-only): on screens narrower than 4:3 (1280x1024) the art no longer overflows -- 1280x960 letterboxed top/bottom, BACK/CLOSE on screen; byte-identical at 4:3 and wider. Only 'taller than 4K' (num > 40) still differs from the popup chrome's stripe T.
