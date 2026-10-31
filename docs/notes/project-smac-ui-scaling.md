---
name: project-smac-ui-scaling
description: SMAC UI scaling patcher: standalone in-place binary patcher for PRACX-patched GOG terranx.exe that bakes UI scaling into the binary
type: project
---

**Product goal:** ship a standalone in-place patcher (pracxpatch.exe-style) that modifies the maintainer's `terranx.exe` so the UI is legible on modern high-DPI displays. Audience: SMAC players on 4K/high-DPI monitors who already run PRACX; distributable via alphacentauri2.info / Reddit / GOG forums. Hundreds-to-thousands of potential users.

**STATUS UPDATE (2026-05-29):** main menu + titled submenus are **visually complete and resolution-independent** (font, text centering, full-strip hit-test, title+separator on submenus, no bottom gap). Plus the patcher now bundles the **Windows 11 24H2 crash fix** (self-contained spinlock, confirmed in-game — [[project-smac-win11-24h2-fix]]) and gained `{abs32}` placeholders + `skippable` groups for mod coexistence ([[project-smac-patcher-v02]]). Current full-patch MD5 `27cb07f01e9272639d90afa7cc409c22`. Everything routes through `scale_uniform` (runtime `min(W/1024,H/768)`); the ONE hard-coded value left is the decoration gate (`0xF00`). Patcher artifacts in `D:\SmacxUi\work\` (apply_patches.py, assemble_thunks.py, patches\patches.yaml). See [[project-smac-menu-strip-scaling]] for the menu coupling map.

**>>> NEXT STEPS (set 2026-05-29) <<<**
1. **Decoration gate** (tabled): make `0x4AE673` resolution-independent (`JNZ`→`JB` so it draws at any width ≥1024 instead of the hard-coded 3840). BLOCKED on a safety check first: static-search who writes `[reg+0xa1c]` (which screen populates the deco slots) and whether `[+0xa28]/[+0xa34]` are initialized outside the `==800/==1024` branches — if not, opening the gate could draw garbage-positioned decorations. Main-menu slots are NULL (deco inert there). NOTE: this writer search is NOT yet done — `find_field_writes.out` does NOT contain the `+0xa1c` writers, so run a fresh `MOV [reg+0xa1c]` scan (don't re-check that file). Details in the "Open questions" correction below.
2. **Next piece of work:** **background/layout elements not scaled on the planet-customization screen** ("erosive forces" + "native life-form abundance" selections). HEAD-START (found 2026-05-29): the screen is **`custom_planet @ 0x0058C2A0`** — already in `scan_resolution.out` with **6 ScreenWidth reads** (the `==800 / else-1024` hardcoded-literal layout pattern → the unscaled elements live in its 1024 branch). It calls `SetupWin_do_menu_2` (so its menu strips are already scaled by `menu_strip_scaling`; the UNSCALED parts are `custom_planet`'s OWN background/layout draws). Relevant param globals (Thinker names, now in terranx.h): `MapErosiveForces 0x94A2AC`, `MapNativeLifeForms 0x94A2B8`, `MapOceanCoverage 0x94A2A4`, `WorldBuilder 0x9502A8`. Start by disassembling `custom_planet` and walking the 6 ScreenWidth-conditional sites for layout literals to scale (same approach as `init_report_screen` in the v0.1 plan).

**Architectural insight — UI literals are COUPLED, never patch one without its siblings (learned 2026-05-27 via empirical test):**
Each clickable UI element has at least three coupled values that must scale together: (1) the **visual sprite dimensions** baked at boot via `Sprite_extract_2` reading hardcoded (x, y, w, h) rects out of `iface.pcx`, (2) the **logical layout width** used for both text centering and Spot hit-test sizing, and (3) the **item position** coordinates. Patching the logical width (literal `300` in `SetupWin_do_menu_rightside` at `0x4ADFA5`) without scaling the visual sprite produces a demonstrable misalignment: the click zone and text-centering rectangle widen, the visual background strip stays the same, and text appears shifted right and clipped at the screen edge. **Patcher schema therefore needs the concept of patch groups** — a set of related sites that must all apply or none do. Until that schema lands, sites discovered as "logical-only" are marked `status: partial` with a `do_not_apply_alone: true` flag and a `paired_with: [TODO: find sibling site]` note.

**End-to-end pipeline verification (2026-05-27):** the patcher round-trip is proven working — `patches.yaml` → MD5 check → PE section table → anchor/original byte verification → atomic write with backup → runtime behavior change in the launched game. Confirmed by patching the menu-item width literal: text visibly shifted right by ~150 pixels on the main menu after applying. Restored via `--restore` after observation. Frida hook captured per-call state and confirmed `gateRes=true` post-patch (the resolution-conditional was opened as designed).

**Project invariant — vanilla UI parity (locked 2026-05-27):**
The patcher must preserve every UI behavior present in the vanilla game, including conditional features that only fire at specific resolutions (e.g., the per-item decoration in `SetupWin_draw_item` that only renders when `ScreenWidth == 800 || ScreenWidth == 0x400` — small, possibly invisible at a glance, still counts). For every patch site we catalog, verify behavior parity at the target resolution — preferably via Frida runtime trace, not decomp inspection alone. Pattern-matching on decompilation has already produced one false positive ("highlight broken at modern res" when in fact only an optional decoration was gated). Don't repeat that.

**v0.1 scoping decisions (locked 2026-05-26):**
- **Target binary**: PRACX-patched GOG terranx.exe only (MD5 `2d0b1438eb73f98519134d7a4f6bc054`, 2024-08-19, 3,084,288 bytes). MD5-check on apply; refuse on mismatch. Do NOT support unpatched GOG, original 1999 CD, Steam, or Planetary Pack.
- **Scaling strategy**: hijack SMAC's existing 800x600/1024x768 resolution-conditional pattern by patching the literals in the `else` (1024x768) branch with scaled values.
- **Delivery**: standalone exe, patches terranx.exe in place after backup. Familiar shape for SMAC mod users.
- **Aspect ratio**: deferred. SMAC is 4:3 native; modern displays are 16:9. Choice between letterboxing and distortion is a v0.2 question — flag if a decision starts to get baked in by accident.

**Critical empirical finding from the resolution-pattern scan (refines the strategy above):**
- `*ScreenWidth` (`0x9B7B1C`) and `*ScreenHeight` (`0x9B7B20`) are read by 87 functions, written by 2.
- PRACX writes both globals to the maintainer's PRACX-configured render resolution at startup. **The patcher does NOT touch them.**
- The 87 reader functions split by usage shape:
  - **7 high-readers (5+ reads each)** do parametric math (`pos = base + ScreenWidth - offset`). These auto-rescale with the global. **Zero patches needed.**
  - **~65 low-readers (1-2 reads each)** do `if (ScreenWidth == 800) {small layout} else {1024x768 layout}` with hardcoded literals. On any modern resolution they fall through to the 1024x768 branch, which is why UI elements look small scattered across a 4K screen. **These are the v0.1 patch sites.**
- Estimated total patcher surface: **150-300 byte patches** across ~65 functions.

**Open questions / TODOs (CURRENT — replaces the now-resolved earlier list):**
- **(immediate pickup)** Text rendering inside the scaled menu strips is still vanilla-sized and positioned ~too high vertically. Investigate `Buffer_write_cent_l_7` / `Buffer_set_font` call sites in `SetupWin_draw_item`. Per `setup_win_inspect.out` line 209, the text-draw site is `Buffer_write_cent_l_7(pcVar2, &local_14, sVar3)`. Font size probably comes from a Font object set via `Buffer_set_font`. Find where the font's scale/size is configured.
- **Generalize to other SetupWin-based menus**: `config_game`, `custom_planet`, `size_of_planet`, `map_menu` all use `SetupWin_do_menu_rightside`. The same 8-site patch group should apply unchanged. Spot-check at least one. If they each create a fresh SetupWin instance, all our [+0x1198]/[+0x119C] field reads at the same VAs fire and the patches generalize for free.
- **Build the layout-literal scanner (the bulk work)** — `extract_patch_sites.py` currently only flags instructions touching `ScreenWidth/Height` globals or the literals `{800, 1024, 600, 768}`. It misses the actual layout literals inside `else` branches of resolution conditionals (e.g., the `0x2a, 0x54, 0x7e` X-coords in `init_report_screen`'s 1024 branch). Need a second pass that: (a) finds each resolution-conditional branch, (b) walks the else body, (c) records every immediate in 0..2048 range.
- **Decoration array `+0xa1c..+0xa24` — main-menu slots ARE NULL (Frida-confirmed 2026-05-29).** The original "NULL/dead code on TOPMENU" note was correct; a brief mis-correction claiming otherwise was reverted. Frida `frida_setupwin.log`: `deco[0..2]=0x0`, `drew=false` for every item. The applied gate patch `SetupWin_draw_item.decoration_gate.cmp_1024_to_3840` @ `0x4AE66E` (`CMP EAX,0x400`→`0xF00`) fires (`gateRes=true`) but the inner null check skips the draw — so on the main menu it is **inert and harmless**. It only matters on SetupWin screens that populate the slots (faction picker / difficulty / etc.); those remain an open follow-up. **NOT the cause of the visible main-menu mangle.**
- **REAL cause of the "mangled first-three strips" (Frida-confirmed 2026-05-29): a vertical-spacing mismatch.** Strip *backgrounds* (`do_menu_rightside`) stack at scaled **210px** spacing (dstPos Y 0,210,420,…). But the *per-item text + refresh* in `SetupWin_draw_item` comes from the **`Spot` rects, which are still at vanilla 75px spacing** (text rects: item0 top=33, item1=108, item2=183, … step 75). So all 7 labels render in Y 33–505 and pile onto background strips 0–2 (y0–630); lower strips get no text. The `Spot` rects drive both text layout AND click hit-testing, so both are wrong. **Fix: scale the Spot rect Y position/height to the 210 step.** Need to find where the spots are added in `do_menu_rightside` (Spot_init @ `0x4ADDCA`; spot-add Y step likely reads unscaled `[+0x119c]`=75).
- **PRACX coexistence**: identify regions PRACX has already patched; avoid stomping its hooks. Worth a focused diff of `terranx.exe` vs the canonical un-PRACXed GOG hash (`4b19c1fe3266b5ebc4305cd182ed6e864e3a1c4a` per Thinker's docs) — that's a precise PRACX patch map. **NOT BLOCKING** because the apply-time padding check on `_SELFMOD` would catch any collision, but worth doing eventually.

**Resolved since the earlier list:**
- Patches.yaml schema for groups + code caves + symbols + `{rel32:NAME}` placeholders + PE VirtualSize extension — see [[project-smac-patcher-v02]].
- The menu-item-strip "sibling literal" hypothesis — the strip is FLC-driven, not literal-driven; the right approach is per-consumer thunks, not finding a sibling literal. See [[project-smac-openitem-strip]] and [[feedback-menu-strip-coupling]].
- The 0x4ADFA5 `MOV EAX, 0x12C` site is now `status: confirmed` as a group member, not `partial`. Promoted as part of `menu_strip_scaling`.

**Workflow corrections worth remembering:**
- DirectDraw methods are NOT in the import table — they're dispatched through COM vtables on `IDirectDrawSurface`. Not directly relevant to this patcher (we modify coordinate math, not blit calls), but earlier strategy notes assumed otherwise.
- Always apply Thinker's address-bindings to the Ghidra project up front as the first move. Names → ~80% coverage → massive force multiplier on every downstream decomp. Done for this project 2026-05-26.

**Canonical artifacts (live state):**
- Running symbol table (named functions/types/patch candidates): `D:\SmacxUi\work\symbols\terranx.h`
- Patch database (the patcher's input): `D:\SmacxUi\work\patches\patches.yaml`
- Patcher itself: `D:\SmacxUi\work\scripts\apply_patches.py` (driver: `run-apply-patches.bat`, default = dry-run, `--apply` to commit, `--restore` to roll back from `terranx.exe.bak`)
- Frida runtime-verification hook: `D:\SmacxUi\work\scripts\hook_setupwin.js` (driver: `run-frida-setupwin.bat`, self-elevates via UAC, spawns terranx under Frida; logs tee to `D:\SmacxUi\work\frida_setupwin.log`)
- Ghidra project with Thinker names applied: `D:\SmacxUi\work\ghidra-projects\terranx`
- Resolution-scan output (87-function dump with instruction context): `D:\SmacxUi\work\scan_resolution.out`
- Tier-1 patch-site extract (raw): `D:\SmacxUi\work\patch_sites_tier1.out`
- Baseline numbers (function counts, memory blocks, GDI surface, anchor strings): [[project-smacx-baseline]]

**Development PRACX config (2026-05-27):**
ScreenWidth=3840, ScreenHeight=2160, WindowWidth=3840, WindowHeight=2160 (explicit, not `<DEFAULT>`); MainFontSize=16, InterludeFontSize=16; DirectDraw=0. This is the controlled-input config we design patches against. Verified via Frida that PRACX writes these values to `*0x9B7B1C` / `*0x9B7B20` at startup. The previous `.ini` (defaults + small font) is preserved at `Alpha Centauri.Ini.old`.

**Why:** User wants the UI legible on 4K. PRACX already handles render-resolution scaling but does NOT scale UI element sizes — original 1024x768 element sizes get scattered across the larger render area. The patcher closes that gap by patching the layout literals so the 1024x768 branch actually produces a scaled layout.

**Scope:** v0.1 = PRACX-GOG only, hijack 1024x768 branch, in-place patcher. The 87-function scan is the load-bearing strategic input — don't relitigate "where do we patch" without consulting it. The cheap workarounds mentioned earlier (lower PRACX render res, bump `MainFontSize`) remain as escape hatches but the patcher is the shipping product.

Related: (a private note), [[reference-smac-modding]], [[project-smacx-baseline]], [[feedback-pyghidra-ghidra-12]], [[project-smac-menu-strip-scaling]], [[project-smac-patcher-v02]], [[project-smac-openitem-strip]], [[feedback-menu-strip-coupling]], [[feedback-buffer-resize-per-blit]], [[feedback-dual-purpose-thunk]], [[feedback-smac-aspect-ratio]]
