---
name: project-smac-thinker-startup-check
description: Thinker Mod startup dialog (off-pin Thinker build) - settled design, user rulings, build state on feat/thinker-update
type: project
---

The Thinker Mod startup check: when thinker.dll is loaded but is not the pinned build (PE stamp + size in version.h), uimod.dll shows its own dialog in PreInit: [Update now] [Not now] [Don't ask me again]. Design (settled 2026-11-14, every sentence user-approved): `work/briefs/thinker-runtime-error-design.md` v8 (history in `...-history-v1-v6.md`). Sibling design for the installer side: `work/briefs/thinker-updater-design.md`.

**User rulings that shape it (do not re-propose the alternatives):**
- Detection is two questions only: is Thinker present, is it the pinned build. No build categories, NO archive of Thinker builds (the author ships dev builds weekly). The label is wording only.
- Update now offers to replace ANY build (dev and custom included); always offers the latest Longevity first; a downgrade is offered but flagged ("This is a downgrade! ...").
- One dialog only (no second "manual" dialog, no download-page button, no Quit button). Fallback boxes instead.
- Don't ask me again = our own version in `[UIMod] ThinkerMismatchDontAsk`; cleared by any install of Longevity (same-version reinstall too), by Reset Skipped Updates, never by Restore Defaults; wording says "until you next update Longevity Vaccine".
- Thinker's download page = its GitHub release page for the pinned tag; Dropbox only for a one-build link the author provides. We never host Thinker. Shipping stock thinker.ini copies in the installer is fine.
- A dev-build pin is named by date ("Thinker Mod rel. Nov 9 2025"), never "development build".
- thinker.ini on replacement: merge into the new stock file, unknown settings appended commented out; thinker_user.ini: unknown lines commented in place; backups all kept, timestamped.
- If the Design Workshop memory patch cannot apply, stop the game (never "avoid the Design Workshop").

**Why:** an off-pin Thinker makes our Thinker-touching patches unsafe; the player must be told before the game window and given a way to fix it.

**How to apply:** state as of 2026-11-15: the DLL side AND the installer/updater side (Thinker download, ini merge, `--fix-thinker`, start-the-game offers, installer wording sweep + scan test) are on branch `feat/thinker-update`, pushed to origin, master merged in (cf9e4aa, after 9304933 reverted a stale pre-rebase copy of f3b6db5). The maintainer ran the whole in-game walkthrough (`work/briefs/thinker-ingame-walkthrough.md`, Parts 1-11) on pre-merge builds and passed it. 2026-11-15: master fast-forwarded to 110ecb2 and pushed (the branch is fully on master). CHANGELOG lines committed (22102f2). NOT yet done: an in-game re-check of the MERGED build (the maintainer deferred it to the next rebuild). Next planned feature: an "Other community mods" installer screen offering Thinker when absent (wording proposed in chat, not approved, not built). Later in-game offer wording (short Thinker step, fatal "cannot run" line, no "(strongly recommended)" in the fatal case) is in design doc §17-18. See [[project-smac-thinker-compat]], (a private note).
