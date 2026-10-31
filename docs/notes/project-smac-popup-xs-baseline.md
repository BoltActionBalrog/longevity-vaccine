---
name: project-smac-popup-xs-baseline
description: Popup script `#xs` widths: the engine itself multiplies them by 1.5 above 1023 px, so that is the baseline a scaled popup is measured against
type: project
---

Five engine facts from the Customize Game Rules fixes (bakes c414b9f9 → d26bcf1b, 2026-07-12):

1. **Popup script `#xs`/`#ys` are 800×600-baseline.** `BasePop_start @0x601bf0` multiplies BOTH
   ×3/2 whenever `ScreenWidth > 0x3FF` (skipped if popup flag `[+0x30a8]&0x400`). Byte-identical
   in un-PRACX'd cc659f — genuine vanilla, NOT PRACX. Consequences: the stored xs `[+iv3+0x21fc]`
   is already the correct 1024-vanilla magnitude at any g>16 res (scale it ×g/16, never ×3/2
   again), and **a pristine reference screenshot of a popup may be an 800×600 capture** — its
   dimensions are then ×1.5 off the 1024 baseline (refs\pristine\MainMenu\CustomizeRules.png is
   one: 453-wide window vs true 1024-vanilla ~682). Check provenance before ratio arithmetic.

2. **d5c `[+iv3+0x222c]` (Dialog[+0x5c]) is a MIXED-space max once fonts scale**:
   `max(native xs, item text measured at the dialog's CURRENT font)`. Any consumer that rescales
   it wholesale ×g/16 double-scales the text term. Lawful form ([[project-scaling-laws-harness]]
   `scaling_laws.itemlist_box_width`): compare in ONE space —
   `box = max(xs·g>>4, d5c) + trim·g>>4`. Baked as thunk_scale_boxw v4 (pcave2 0xAF00, type-1
   arm only: dlg_type[+0x2350]==1 ∧ d5c≠0 ∧ no art; type 16 = q16 family, type −1 has d5c==0).
   Same disease family as [[feedback-shared-field-per-row-doublescale]].

3. **The #button row is positioned INSIDE BasePop_calculate_dimensions from box_w** — any box_w
   correction must run at/before the 0x603d82 thunk. A post-calc rewrite narrows the (often
   right-anchored, `#x -5 #y -5` = bottom-right corner offsets) window under already-placed
   buttons and clips the leftmost one. Prototype hooks must correct the INPUT (d5c at
   Dialog_dims_dispatch 0x6132A0 exit) instead — hook_rulesboxw.js v2 pattern.

4. **The >1023 regime has a GENUINE VANILLA collision: rows over the container's right stroke.**
   Rows end at rect boxw−9 and the SW>0x3FF arm parks the type-1 container ring's right stroke at
   boxw−9 too — drawn UNDER the rows, surviving only as dashes in the inter-row gaps (any vanilla
   player at 1024×768 saw this). The 800×600 arm has 3px clearance (rows rel 443 / stroke rel 446).
   Faithfully scaling vanilla's −2 inner-offset propagates the collision to every resolution (at 4K
   the 3px stroke kept a 1px sliver, which reads as "almost right"). Fix = pf_union_align v5
   (d26bcf1b): symmetric inner-ring arm at g>16, plus the project's ONE deliberate native-look
   override (g≤16 ∧ SW>0x3FF ∧ type-1 ∧ no-art → r = boxw−7; law
   `itemlist_container_native_fix_r`; Win11-filelock precedent, changelog-worthy as a vanilla bug).
   LESSON: "proportionate to vanilla" presumes vanilla is self-consistent — when two vanilla
   elements already collide, scaling both faithfully ships the collision; check the SOURCE-design
   regime (800×600 for popups) for the intended clearance. Also: a SW>0x3FF test is legitimate
   when it selects the engine's own bump regime for a native-constant repair — the
   [[feedback-loores-gate-on-g]] rule bans it only as a SCALING gate.

5. **One shared chrome site, per-family vanilla outcomes.** The 0x406238 body/field ring serves
   Quit (vanilla OUTER-flush with the title, 696==696), base-name, AND the type-1 checkbox
   container (vanilla flush with the title INNER stroke: pristine-4K measure container 7..670 vs
   title 4..675/7..672). Vanilla has no "relation" — it has a formula whose inputs differ per
   dialog type. Never impose one family's measured relation globally (pf-align v3 did → the
   Customize container landed on the window ring); alignment overrides need per-family arms
   (pf_union_align v4, laws `itemlist_container_edge_l/_r`). Also: g>16 popup chrome BYPASSES the
   Buffer_box_sprite entry attach (thickener thunks draw it) — runtime rect captures of scaled
   chrome need the thunk side; pristine captures still work at the entry.


**Why:** each of these masqueraded as something else (a PRACX bug, an over-wide window "defect"
that was actually lawful rows, a "third button appearing", a global-relation "fix" that broke a
sibling family). Measuring the engine first (frida_boxw2.log, frida_namewidth2.log) prevented
four wrong fixes.

**How to apply:** before scaling any popup width, log xs `[+0x21fc]` AND d5c `[+0x222c]` and ask
which space each lives in; treat 800×600-provenance pristine refs as ×0.75 of the 1024 baseline.

## Ref-space checklist (2026-08-14): refs\pristine\*.png come in THREE spaces
1. 800x600 captures (this note's origin); 2. 4K captures of the 1.5x-bumped engine (#xs law);
3. NATIVE 1024x768 renders PRACX-smooth-stretched x2.8125 into a 2880x2160 pillarbox
   (DiplomancySelect.png, the namebase ref) — blended stripe edges + pitch = 22x2.8125 prove it;
   divide device px by 2.8125 for exact vanilla proportions. Identify the space FIRST (image
   dims + content left edge 480 for pillarbox + whether stripe edges blend); a wrong space
   inverts the diagnosis (the EDITORWHO "vertical misscale" was a mixed-space artefact).
