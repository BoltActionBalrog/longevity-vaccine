---
name: feedback-changelog-vanilla-baseline
description: CHANGELOG baseline is VANILLA, not our last build — never log fixes to our own unreleased regressions, and don't itemize every element we scale
type: feedback
---

`work\CHANGELOG.md` describes changes **relative to VANILLA (the last thing a player actually ran)**, never
relative to our own previous build. Nothing has been released yet, so a bug we introduced and then fixed is
invisible to every reader and must NOT get a line. Nor does each element we scale: from vanilla a player
expects "the menus scale," not an inventory of every frame, gap, stroke, and dither corrected on the way.

**Why:** the changelog ships with the patcher. It is read by someone upgrading from the last RELEASE. By
2026-07-10 it had grown to 110+ lines, most of them "Fixed <thing> drawing wrong at 4K" — regressions of our
own unreleased work that no user ever saw. The maintainer cut it: *"considering we haven't released, no user has
ever seen those bugs... From vanilla users expect that menus will be up-scaled. We don't need to call out
every element that we up-scale."* Pruned to ~20 lines grouped by subsystem.

**How to apply:**
- Before adding a line, ask: *would a player upgrading from the last RELEASE notice this describes something
  new to them?* If they never saw the bug, delete it.
- **Consolidate**: one line per screen/subsystem ("The in-game HUD now scales to any resolution"). When a
  change refines something already listed, EDIT that line; only add a line for something genuinely new.
- Genuine **pre-existing** bugs (vanilla's, PRACX's, Win11 24H2's) DO get a line — say whose bug it was.
  Bugs our own scaling caused (e.g. the multiplayer "Unable to allocate draw buffer" crash) do not.
- Our fix history belongs in git, `patches.yaml`, and these notes — not the changelog.

A written project rule. Related: [[project-smac-ui-scaling]].

**Wording (2026-09-26):** the changelog is shown to players on the release website, so its copy rule applies: never "original game"/"original-game bug" — say "the unmodded game" / "a bug in the unmodded game" ("base-game bug" is fine).

**PRACX only (2026-09-26):** support for the non-PRACX (plain `terranx.exe`) game was DROPPED. Never write "works on the un-modded executable too", "ships on both executables" or similar in the changelog or on the site; the claims were stripped.
