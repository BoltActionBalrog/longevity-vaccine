---
name: reference-faction-picker-component-map
description: faction-picker ("Choose Your Factions") element legend the maintainer labels by group number — at refs\Annotate
type: reference
---

The maintainer refers to faction-picker ("Choose Your Factions") elements by **group number** from an annotated
screenshot. Keep these in sync; the labels exist only in the image, so re-read the PNG.

- Clean shot: `D:\SmacxUi\refs\Annotate\Faction.png`
- Annotated legend: `D:\SmacxUi\refs\Annotate\Faction_annotated.png` — "FACTION SELECT MODAL – component map":
  1. Modal outer frame / border
  2. Title bar – "CHOOSE YOUR FACTIONS"
  3. Preset-roster selector buttons (one group): 3 top preview boxes — default (base-game) 7 leaders,
     expansion 7 leaders, planet button
  4. Button – PLAY SELECTED FACTION
  5. Button – PLAY RANDOM FACTION
  6. Faction name list (combobox rows + dropdown arrows)
  7. Selection indicator (arrow + highlighted row)
  8. Bottom button bar – INFO | CHANGE NAME | OK | CANCEL

Most of the picker is scaled+confirmed (see (a private note): 2.5x cap, bars, dropdown dither — all
closed at build e920df04). Open items (unstarted): N1 the dropdown-click submenu (faction list popup), N2 the
connector arrow G3→G6 (preview group → name list; NOT the item-7 in-list indicator), N3 a font in the INFO dialog.
