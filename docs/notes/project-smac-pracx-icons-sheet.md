---
name: project-smac-pracx-icons-sheet
description: Issue #7 PRACX unworked-yield icons: GOG ships PRACX without its Icons.pcx; the installer adds PRACX 1.11's art (owner chose shipping it over generating, 2026-11-14)
type: project
---

longevity-vaccine issue #7 (KiPhish, 2026-11-13): PRACX's "Show Unworked City Resources" draws nothing on GOG. Cause: GOG's Planetary Pack installs PRACX 1.11 (uninstaller, change log, pracxpatch.exe present) but keeps the STOCK Icons.pcx; PRACXLoadIcons copies 42 rects (24 grey yield icons + 18 map-view swatches) out of it, and on GOG's sheet they are blank. Not a Longevity bug; fixed anyway since GOG+PRACX is our target. The fix is `work\scripts\patch_icons.py` + `work\art\pracx_icons_overlay.pcx`, run by install.py on install/update, undone on uninstall. It writes ONLY a sheet whose pixels match a known stock sheet (KNOWN_STOCK); every PRACX variant, custom sheet and the colour-blind sheet is left alone.

**Decision (owner, 2026-11-14):** ship PRACX 1.11's art as is ("Let's go with PRACX 1.11 Art"), knowing its grey icons are recoloured cut-outs of the game's newicons.pcx (an adversarial review found this; the PROVENANCE file says so). The alternative he declined: generate the icons at install time from the player's own newicons.pcx (colour map + 1-px outline + speck filter, 99.6% pixel match; comparison at `work\briefs\issue7-icons-side-by-side.png`).

**Why:** his call between visual fidelity and not shipping EA-derived pixels.

**Public source too (owner, 2026-11-14):** after the in-game check, the overlay goes to the public repo ("we will want to publish to the public repo"); test_publish_source pins `work/art/pracx_icons_overlay.pcx` + its PROVENANCE as exported.

**Status 2026-11-14:** user-confirmed in game from a fresh install of the player zip (4K, 1600x1200, 1024x768); pushed to smacx-ui master as 453cb74 with the CHANGELOG line (1.0.1, PRACX fixes). Pixel check: grey icons 1:1 at g16, 62 px at g25, 100 px at g40 from the 40-px cells, uniform NN; PRACX swaps only the sprite pointer, so they ride the farm-orb (g,16) ratio. NOTE: `scaling_laws.engine_scale_runs(25,16)` does NOT reproduce the on-screen 1-or-2 run order at g25 on this path (it sums to 63, the screen shows 62) -- the port is unverified for Sprite_draw_2 enlargement; measure, don't trust it there. The installer-fix idea "record a skipped on-disk pack in the receipt" was DECLINED by the maintainer ("we don't need to do that").

**How to apply:** do not re-propose generating the art, or the on-disk-pack receipt fix. If the art ever changes, move the old EXPECTED_RESULT into PREVIOUS_RESULTS so sheets patched by the earlier release are still recognised. The CHANGELOG line waits for in-game confirmation ([[feedback-changelog-vanilla-baseline]]); phrase it as GOG's bug.
