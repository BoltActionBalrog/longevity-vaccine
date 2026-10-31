---
name: project-smac-openitem-strip
description: The main-menu item strip is data-driven from openitem.flc, not a binary literal — affects v0.1 patcher strategy for SetupWin_do_menu_rightside
type: project
---

The visible "menu-item background strip" rendered behind each entry in SMAC's main menu (and other SetupWin-based menus) is NOT a hardcoded sprite extracted from `iface.pcx`. It's an animated FLC asset at `D:\GOGGalaxy\Games\Alpha Centauri\openitem.flc`.

**FLC header (verified by reading file 2026-05-27):**
- Magic 0xAF12 (Autodesk Animator FLC), 12 frames, 354×75 px, 8 bpp, 55,651 bytes total.

**Runtime path:**
1. `SetupWin_do_menu_rightside` (`0x4ADB70`) calls `Buffer_init(.., 75, 354)` to pre-allocate a Buffer subobject embedded in SetupWin at `this+0x1118`.
2. Calls `FUN_00629e50(.., "openitem.flc", this+0x1118)` — the FLC loader.
3. Loader parses the FLC header, writes width=354 to the Buffer's `+0x80` (= SetupWin `+0x1198`) and height=75 to `+0x84` (= `+0x119c`), then decodes 12 frames into the pixel buffer.
4. `SetupWin_draw_item` (`0x4AE4D0`) blits via `Buffer_copy_4(.., *(this+0x1198), -*(this+0x119c))` — reads width/height back from the Buffer subobject.

**Why this matters for the patcher:**
The logical menu-item rect width (300) at `0x4ADFA5` in `SetupWin_do_menu_rightside` controls hit-test and text centering. The strip's visible width (354) is encoded in the FLC file — it never appears as a binary literal. A scan of all 10,016 functions for `MOV [reg+0x1198], imm` returned zero hits, confirming the field is populated indirectly from the parsed FLC stream.

**The 354/300 ratio = 1.18 is deliberate:** the strip extends ~27 px past the click rect on each side. Any v0.1 scaling of the rect (e.g., 300→600) needs the strip to scale in proportion (354→708) or text spills past the visible strip.

**Three feasible approaches to scale the strip (none is a simple literal swap):**
1. **Asset replacement** — produce a scaled `openitem.flc` (e.g., 708×150). Outside the binary patcher's scope but cleanest visual result. Requires FLC encoder/decoder.
2. **Loader patch** — modify `FUN_00629e50` (or the FLC parser it calls) to multiply width/height by N before storing. Requires finding the actual store instruction (small displacement relative to Buffer base, not to SetupWin).
3. **Draw-site patch** — modify the `Buffer_copy_4` call sites in `SetupWin_draw_item` and `SetupWin_do_menu_rightside` to pass scaled width. Risks distortion of decorative end-caps.

**v0.1 patch status implication:**
`SetupWin_do_menu_rightside.menu_item_width_300_to_600` at `0x4ADFA5` (currently `status: partial / do_not_apply_alone: true`) has no paired sibling literal in the binary. Either keep it parked, or pair it with one of the three approaches above. Don't expect to find a `paired_with` literal — the search has been exhausted.

**Why:** The earlier hypothesis (a sibling sprite-width literal somewhere in `load_interface` or its callees) was based on the assumption that all UI assets are PCX-extracted via `Sprite_extract_2`. They're not — animated UI elements use FLC. This is the dominant non-obvious gotcha for future patch-site analysis.

**How to apply:** When a UI-element width/height field can't be located as a binary literal, suspect a data-file source. Check for `*.flc` references in the surrounding `SetupWin_*` / `BaseWin_*` ctor/init. The FLC format documentation: 128-byte header, width at file-offset +8 (uint16), height at +10 (uint16), magic at +4 (0xAF12 for FLC, 0xAF11 for FLI). 23 FLC files ship with SMAC at the game root.

**Other FLC-driven UI elements likely:** any SetupWin / BaseWin / GraphicWin field whose width/height field can't be located as a binary literal. List all `.flc` references in the binary for an inventory.

Related: [[project-smac-ui-scaling]], [[project-smacx-baseline]]
