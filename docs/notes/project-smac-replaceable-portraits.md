---
name: project-smac-replaceable-portraits
description: Replaceable leader/native-life portraits + portraits-hd pack (licence confirmed 2026-11-06, ships from 1.0.0). Prefs tree under "Enable Custom Portraits" (renamed from "Enable User Portraits" 2026-11-07); the SETTING decides the order (pack first when on, then the player's portraits\, then vanilla). Built, audited 2026-10-03; Phase 5 in-game matrix next
type: project
---

Plan (approved 2026-09-29): a private planning document. Phases 0 (Frida measure) → 1 law+port+previews (user sign-off gate) → 2 pack builder (gate: user states art source/licence) → 3a loader+load-time bake → 3b draw-time enlarge + PortraitScanlines pref → 4 installer/release → 5 user in-game matrix. Three independent read-only reviewers (correctness / security / UX) at the end of EVERY phase 1–4, findings in work\briefs\portraits-phase<N>-review.md.

Source art: `dist\portraits-hd-src\alpha centauri (N).png` (gitignored). N→faction: 1 caretake, 2 usurper, 3 spartans, 4 hive, 5 pirates, 6 cyborg, 7 drone, 8 angels, 9 univ, 10 morgan, 11 peace, 12 fungboy, 13 believe, 14 gaians. The 4 slots (council small/big, diplomacy, datalink) are the SAME full picture at different sizes; HD ≈ 6.8× datalink interior. Morgan/usurper/caretake are off-framed → builder crops to registered vanilla framing.

**Why:** user wants any player to drop in their own portraits without the module; the module is just curated images.

**How to apply:**
- Layout: the pack lives only in `portraits\hd\` (the installer never writes or prunes elsewhere, nor through junctions). Lookup order is decided by the "Use Turovetsky's HD Portrait Pack" setting: pack first when on (and the manifest is present), then the player's `portraits\` png/jpg, then vanilla. This is user decision 2026-10-03; it superseded "player always wins".
- Both substitution points are required: a load-time bake (detour load_faction_art 0x453710) for g≤16, and the PortraitDraw branch for g>16. The g>16 path resamples from RGB, never from the dithered bake.
- Scanlines default ON with a pref toggle (user decision).
- The WIC decoder is pinned to PNG/JPEG CLSIDs.
- Phase-0 probe: work\scripts\hook_portrait_palette.js, hosted on the SD2 cave target 0xA12330.

Phase 0 DONE 2026-09-30. Every portrait draw (all consumers, g=16 and g=40) uses a dest palette identical to g_main_palette; it differs from the sheet palettes in 30 entries → quantize into g_main_palette / dest+0xA4. The faction-0 slot is empty but still drawn (skip null sprites). The big-council slot was not yet observed.

Native-life portraits were brought INTO scope by the maintainer on 2026-09-30 (Phase 3c). They are the BT*.pcx files (BTwrm, BTisl, BTchi, BTsealrk, BTsporlnch, BTfungtow; each 96×115). They are filename-backed: the blit core loads them into scratch 0x9B6080, then thunk_art_core 0xA28AB0 draws them. The faction-0 empty-slot draw is vanilla's PROFILE report (0x4A241A) and is harmless.

Phase 1 BUILT 2026-09-30, not committed. Law block in scaling_laws.py; port in portrait_law.h; tests test_portrait_rgb_port.py and test_build_portraits_hd.py. The preview script is art/preview_replacement_portraits.py, writing to _portrait_preview/hd (gitignored). The builder is art/build_portraits_hd.py; its dry-run registers all 14 at NCC 0.74–0.96. The review triage is in work/briefs/portraits-phase1-review.md. Awaiting the maintainer on three things: preview sign-off, the scanline mode (OVERLAY = vanilla model, darker; MEAN = brightness kept), and the art licence.

On 2026-09-30 the maintainer picked BOTH scanline looks as Preferences rows. They are "Add Scanlines" (id 0x6E, [UIMod] PortraitScanlines) with "Brighten Scanlines" nested under it (id 0x6F, PortraitScanlinesBright), following the cloak rows' parent/child pattern; both default ON. PortraitScanMode() in portrait.cpp maps them to OFF / OVERLAY / MEAN. Deployed DLL 66cd802e (backup uimod.dll.75f3c570.bak). The rows sit on page rows optRow0+6/+7, native y 173..214 against a slider frame top of 287. USER-VERIFIED 2026-09-30 at 4K and at 1024x768: the 1024 run was Borderless, so its shots are 3840x2160 files with a 4:3 pillarbox. The toggles and the persistence across a restart were verified too. Nothing reads the settings until Phase 3 (the replacement draw).

2026-09-30, phases 2-4 BUILT (not committed, not deployed yet):
- Pack: dist\portraits-hd, 14 images + manifest + PROVENANCE. The credit text is the tracked file work\art\portraits-hd-PROVENANCE.txt: artist Turovetsky, who must be credited by handle + https://www.youtube.com/@Turovetsky + https://x.com/turovetsky.
- DLL: portrait.cpp (B1 load_faction_art detour + B2 + native-life art_core detour) and portrait_files.cpp (WIC, max 2048 px per side).
- Installer: the pack goes to portraits\hd only, with a prune; the README goes to portraits\.
- Review triage: work\briefs\portraits-phase3-review.md.
- Prefs tree (user request 2026-09-30): "Enable Custom Portraits" (0x70, CustomPortraits; "Enable User Portraits" until 2026-11-07: the HD pack is not the player's own art, user) is the parent of "Use Turovetsky's HD Portrait Pack" (0x71, HdPortraits; renamed 2026-10-03; the row exists only when portraits\hd\pack-manifest.json does) and "Add Scanlines" (0x6E). All default ON. 2026-10-30: "Brighten Scanlines" (0x6F) REMOVED (id retired, never reuse; the PortraitScanlinesBright key is gone) -- replacement scanlines are always the brightness-keeping kind (PortraitScanMode = off | MEAN); its row slot went to the airdrop-diversion setting (0x79).
- DEPLOYED 2026-10-03: DLL e2b92ae0 + the pack in <game>\portraits\hd + portraits\README.txt. The full test suite passed. Phase 5 (the maintainer's in-game matrix) is next.
- LICENCE CONFIRMED 2026-11-06 (user: the artist approved "on all fronts"): GPL-3.0-or-later + credit + distribution, recorded in work\art\portraits-hd-PROVENANCE.txt and THIRD_PARTY.md; the pack was WITHHELD 2026-11-04..06 (guide, CHANGELOG, website) and is re-added for 1.0.0 (portraits-hd 1.0.0, first release). release.py refuses a built pack whose PROVENANCE still says provisional. Website restore = branch website/restore-portraits-hd-pack (website session).

2026-10-03, after the full audit (work/briefs/portraits-full-audit.md):
- DEPLOYED DLL 7366fb24, the rebuilt pack in portraits/hd, and portraits/LONGEVITY_PORTRAITS_README.txt (renamed from README.txt). The full test suite passed (2 release-test failures were fixed and rerun).
- The COUNCIL slots are UNFRAMED: their edges are picture. Diplomacy, datalink and native life carry a 1-px frame. Assuming every slot was framed left a ring of vanilla pixels (the maintainer's 4K council shot).
- Phase 5 (the maintainer's in-game matrix) is next.

User decisions on 2026-10-03:
- The player-facing name is "Turovetsky's HD Portrait Pack" everywhere (renamed by the maintainer 2026-11-06 from "Longevity HD Portrait Pack"): installer, update prompt (update_core.h), the Preferences row "Use Turovetsky's HD Portrait Pack", changelog, guide, PROVENANCE, THIRD_PARTY, website. It takes no article ("the"/"your") in sentences. The module id stays portraits-hd, the ini key HdPortraits.
- The art licence is GPL-3.0-or-later. SUPERSEDED 2026-11-06: no longer provisional -- the artist confirmed it (see LICENCE CONFIRMED above) and the pack ships from 1.0.0.
- portraits-hd stays 0.1.0 for a mock update test. The first public release ships as 0.2.0 (owner decision 2026-10-31); pack versions stay independent of the product's.
- the maintainer's work log (Release prep) records the 0.2.0 decision and the website update. The licence blocker (and the `--without portraits-hd` releases 0.2.0..0.2.2) ended 2026-11-06.
- DLL 264b3b35 is deployed (the rename).

VERIFIED 2026-10-03 by measured screenshot audits, bit-exact to the law in every portrait instance:
- Covered: 4K (19 instances) plus 1920x1080 and 1600x1200 (~140), every slot incl. diplomacy, all three scan modes, pack on/off, native-life fallback, Enable Custom Portraits off (vanilla), and the no-pack run (no HD row, no crash).
- Still unverified: the 1024x768 matrix (only the council bake), and the Preferences page at 1600/800.
- Open colour items for the USER to decide: F1, a ~-2/255 darkening from floor-rounded diffusion; F2, a green tint on bright neutrals. Recommended fix: replacements only.
- A CHANGELOG line was added.

- The combat console is the bottom HUD panel during a fight (two portraits + the units' stats). It was verified at 1920x1080 and 1600x1200 in all modes; the second auditor mislabelled it "HUD unit portrait".

- USER DECISION 2026-10-03: no 1024x768 verification matrix (too slow; regression risk at native res is ~zero outside the console). The single 1024 council shot was bit-exact to the native bake.
- Logging: [UIMod] DebugLog=1 (init.cpp UimodDbg) now gates the developer lines (prefs RowW/chkrow/value bubble/portrait-row layout, the portrait settings-change line). A real row overlap and the replacement/failure lines still log for everyone. DLL 85315a17 deployed.
- uimod.log rotates to .old at >1 MB once per launch; one .old only (~2 MB total). GAP: there is no per-write cap within a session. A per-write rotation check was proposed to the maintainer.

- SHARED FILES (2026-10-03): the popup-art session is adding an "_sm" event-picture smooth enlarge in scaling_laws.py (art_field_*), portrait_law.h (FieldEnlarge etc.) and portrait.cpp (a second one-shot mark in ArtCorePreInner plus the g_artSprView branch of Draw); no commit of the shared files without the maintainer, using hunk-level staging or a joint commit.

- COLOUR OPTION B APPROVED and BUILT 2026-10-03 (not deployed): symmetric rounding of the replacement path's error diffusion. Law portrait_shr_round, port ShrRound in Finish; 85% damping kept, vanilla Enlarge unchanged. Flat-grey brightness bias goes from -1.96 to +0.37. F2 (green tint) was deliberately left.

- DEPLOYED 2026-10-03: DLL c1dbb5c3, a joint build of option B + the popup session's _sm event-picture smoothing (backup uimod.dll.85315a17.bak). The maintainer's shots were taken on the OLD 85315a17 (a pre-B baseline).

- OPTION B VERIFIED 2026-10-03 (audit 3): 21/21 after-shot portraits at 4K + 1920 are bit-exact to the new law, and 19/19 before-shots to the old one. The mean shift went from about -2.3 to about 0. F2 remains, as accepted.

Related: [[project-smac-smooth-portraits]], [[feedback-dither-no-resample-on-upscale]].

**Scanline rule (2026-10-03, user):** portraits match the popup pictures: above native, scanlines are art_scan_rows(num,den) = max(2, num//den) device rows thick, phase counted from the first interior row (dark iff ((u//T)&1) != bright); native = 1 row. Applies to replacements AND the vanilla smooth enlarge. DLL 6a48fd7c deployed (also carries the 2-row popup-picture law); review 4 (12 shots, 4K + 1080): all 24 portrait draws bit-exact vs the new law, stripes exactly 2 rows, popup picture matches. Not shot: big council slot, g>=48. Open question: the diplomacy left-panel bioscan photo (own leader, not a portrait slot) still alternates 1 row.

**2026-10-04 re-blit v2 (exe 6462bb7b, DLL b4907eea):** every patcher re-blit (thunk_art_reblit_body pcave2 0x27640, stubs at 0x29C80/0x13360) draws 2-row scanlines (art_reblit_row v2 = art_frame_rows + art_scan_near). review 5: base picture, colour bar, BIOSCAN figure, picker, popups bit-exact at 4K + 1080. Version logo ac_logo_sm goes through the DLL field enlarge (any *_sm). Vanilla native-life face VERIFIED bit-exact (4K shot 20261004, Btisl via portrait_enlarge). Trade-offs logged in the maintainer's work log (g<24 skipped rows on NN path; unframed bar ends). Diplomacy panel backdrop still on its own stripe_period law (2/3 runs at 4K), not 2-row.

**Option B DEFERRED (user 2026-10-04):** all chrome (stripe_period P=(g+4)>>3 surfaces) to move to 2-row + pictures onto the dest-buffer phase grid, later. Brief work/briefs/scanlines-2row-everywhere.md; the maintainer's work log entry.

**Committed + pushed 2026-10-04:** 3aa9f34 (exe-coupled: art re-blit v2, patches.yaml, laws) and 1af2ae4 (portraits / HD pack / DLL b4907eea). Earlier 'not committed' lines above are history.
