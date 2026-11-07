---
name: feedback-restore-defaults-not-a-consent
description: Preferences "Restore Defaults" resets tunings only — never a consent the player gave elsewhere (update checks) and never a setting whose row is not built (HD pack without the pack); the maintainer's decision 2026-11-07
type: feedback
---

"Restore Defaults" on the Longevity Preferences tab resets TUNINGS. It must not touch (a) a setting that records a
consent the player gave elsewhere — "Check for Updates at Startup" is the installer's first-install question stored
as `[UIMod] CheckForUpdates` — and (b) a setting whose row is not built on this page (the HD-pack row without the
pack: the stored `HdPortraits` is kept, as the parent toggle already kept it).

**Why:** nothing on the button says it turns update checks on; a player who answered "no" at install and pressed the
button for other reasons had their answer silently reversed and OK persisted it (audit finding, user decision
2026-11-07). The only controls that turn the check on are the row itself and "Reset Skipped Updates", whose
confirmation popup says so.

**How to apply:** when adding a setting to the tab (skill prefwin-settings, Recipe A step 5), decide whether it is a
tuning or a consent; a consent is left out of the Restore Defaults handler with a comment saying why, and any button
that does flip it must say so in its own text or popup. A row that is conditionally built keeps its stored value in
the handler (`g_xxxRow ? default : Get()`). `work\tests\test_prefs_source.py` pins both rules at the source. Decided
(user 2026-11-07, "accept as is"): the row stays session-live like every other — a toggle survives Cancel/ESC and the
next OK on any tab persists it; do not add a reload at open/Cancel. See [[project-smac-prefwin-scaling]],
[[project-smac-update-checker]].
