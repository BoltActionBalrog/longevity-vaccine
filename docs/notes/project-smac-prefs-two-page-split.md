---
name: project-smac-prefs-two-page-split
description: Longevity Preferences tab: the owner's two-page split (2026-11-12) — page membership is FIXED whatever packs are installed; page 1 = program/controls/rules + slider frame, page 2 = portraits + HD art rows; never propose a conditional layout
type: project
---

Owner decision, 2026-11-12, while reviewing rtru's PR #2 on longevity-vaccine (basehd + Preferences page; see (a private note)). It was first put to the PR author as a requirement.

**The rule (owner's words):** "split consistently such that, no matter what packs a user has installed, all the settings will always be on the same page, even if some settings might not be present."

**The split he approved ("Yes, use it"):**
- Page 1, today's order: display mode + Constrain Mouse, update row, the mouse group (Modern Control Set + child, the drag cells, the two camera rows), the cloak group (3 rows), the airdrop row; then the slider frame (Base Font Size, Drag Hold Time).
- Page 2: the portrait group (Enable Custom Portraits, HD Portrait Pack row, Add Scanlines), then one row per HD art hook.
- Two pages always, flipped by the stock More button (which must read "Back" on page 2, as the engine does on its own tab 6). Absent rows close up within their page; no row ever changes page.

**Why:** a player must find a setting in the same place on every install. He rejected as "too aggressive" my first proposal, a CONDITIONAL split (one page with no art pack, two pages with one), because rows would change page depending on what is installed.

**How to apply:** never propose a Preferences layout whose page membership depends on installed packs or bound features. A new non-art setting goes on page 1 (room for 14 lines with the frame 23 native px higher; 12 used), a new art toggle on page 2. The capacity numbers come from the PR's overlap formula and a layout emulation, not an in-game measurement. Related: [[project-smac-prefs-row-pitch-decision]], [[project-smac-prefwin-scaling]].
