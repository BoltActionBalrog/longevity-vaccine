---
name: project-smac-credits-interlude
description: View Credits + Interlude screen scaling (group credits_interlude_scaling) — mechanism, thunk map, pending Layer-3 verify
type: project
---

**CLOSED 2026-07-03** — MD5 **9380803a** (= verified 1417a5c2 content + this group) **user-confirmed
in-game at ALL resolutions + CHANGELOG'd**; 9380803a is the VERIFIED RELEASE LOCK.

**The credits screen is NOT a movie.** `show_credits` 0x428DF0 (callers: top_menu, Console_menu_proc,
Console_on_key_click, end_of_game) → `load_credits_a` 0x4289F0: fullscreen GraphicWin + credits2.pcx
(1024×768; credits.pcx 800×600 on the ScreenWidth==800 branch) + a 400×400 scroller sub-window @(30,200)
+ "Alpha Centauri" font 14 + 30ms timer (tick 0x428DD0 → draw 0x428C00). Interludes = `load_credits_b`
0x45F2E0 (caller `interlude` 0x5230E0): same pcx into a Buffer at obj+0xA54 + a wrapped text block.

**ROOT CAUSE of the "video in the corner": `Buffer_load_pcx` 0x5D7DE0 RESIZES its target Buffer to the
pcx dims** — the fullscreen window's buffer collapses to 1024×768, composited 1:1 top-left; the rest of
the screen shows stale menu content behind. Fix = **Thinker prior art** (refs\thinker\src\patch.cpp
1363-67, gui.cpp window_scale_load_pcx / Credits_GraphicWin_init): load into a temp buffer, resize the
target to ScreenW×ScreenH, StretchBlt-stretch anamorphically. **Check Thinker patch.cpp FIRST for any
screen-level defect — they may have already mapped the sites.**

Thunk map (pcave2 0x3A00-0x3D36, src work\scripts\assemble_credits.py, baked hex):
- `thunk_pcx_fullscreen` 0x3A00 — Buffer_load_pcx drop-in @0x5D552E (GraphicWin_load_pcx inner call =
  credits + demo splash, Thinker-precedented) + @0x45F3C2 (interlude). g≤16 tail-jmp native; else load
  via g_frame_buf (load_pcx sizes it), Buffer_resize dest SW×SH, Buffer_copy_3 stretch. Upscale-only →
  GDI NN safe (no thin-line drop concern).
- `thunk_credits_subwin` 0x3AA0 @0x428A8C — (30,200,400×400)×g/16 uniform (thinker does anamorphic
  SW/1024·SH/768 instead; we chose uniform per the plan). Must exit edi=esi+0x1234.
- `thunk_credits_font` 0x3B20 @0x428AF2 — Font_init 14×g/16; same Font measures+draws; scroll-anchored
  → NO line-box nudge.
- `thunk_credits_scroll` 0x3B50 @0x428C21 — offset = ticks×g/16 (rate tracks line height; total scroll
  time == vanilla). Scale at the READ site, never the ++ increment (no floor drift).
- `thunk_credits_fade` 0x3B70 @0x428CEE — the 8×2px fade bands redrawn ×g/16, bit-identical @g16
  (bottom band k spans [H−(2k+1)s, H−(2k−1)s) — mirrors vanilla's 1-row overhang).
- `thunk_interlude_font` 0x3C40 @0x45F382 — the 3 config_popups globals 0x945770/FC/F8 are
  find_font-table entries (variant 0/1/2 of ONE size row; row stride 0xA0 from 0x93FC58; find_font
  returns base+idx·0xA0+variant·0x28). Scaled swap: idx from the ptr, native=font_size_table[idx],
  find_font(native×g/16, v). NEVER mutate the globals ([[feedback-shared-field-per-row-doublescale]]).
- `thunk_interlude_clamp` 0x3CF0 @0x45F49A (L=min(L,25·g/16)) + `thunk_interlude_nudge` 0x3D20
  @0x45F4D0 (INTERLUDE21/22 +50·g/16).

Gotchas hit/avoided:
- **g_popup_scale_num is 0 until a popup computes it** — credits opens straight from the main menu, so
  entry thunks call `thunk_ensure_scale` (0x668760) first (thunk_faction_show precedent).
- Keystone rejects some `;` comment content inside asm blocks — strip comments before ks.asm().
- Interlude text rect derives from the fullscreen client rect with 1/6-fraction insets → auto-scales;
  only the two literals (0x19 clamp, 0x32 nudge) needed thunks.

Watch item: interlude portraits/extra sprites (text-parser list at +0xA24) may need scaling if one ever
shows up unscaled in-game.

**Music dedupe (group `credits_menu_music_dedupe`, DONE 0acf9bc7 / pristine 529bee3d, user-verified
both exes 2026-07-03 + CHANGELOG'd):** base-game bug — credits (0x428B5F, PREF_AV_BACKGROUND_MUSIC
gate) plays "fx\opening menu.wav" through its PRIVATE Wave 0x703E30 while top_menu's copy still
streams through Wave 0x945780 (0x58E3D2) → two layered instances. Fix: Wave_play_2 call @0x428B64 →
`thunk_credits_music` (pcave2 0x3D40, 23B): skip iff Wave_is_playing(0x945780) (menu track continues
through credits), else vanilla play (end-of-game / in-game credits keep music; Wave_is_playing is
null-safe on a never-loaded wave). Base-independent; PRISTINE ships it via the `--pristine` default
group set `PRISTINE_GROUPS` in apply_patches.py (also used by install.py) — extend THAT list for any
future base-game bugfix that should reach the un-PRACX'd exe.
