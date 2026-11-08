---
name: feedback-fumbled-consent-defaults-restrictive
description: The installer's update-check question ("[Y/n]") treats any answer that is not Enter/y/yes as NO; the maintainer accepted that on purpose (2026-11-07) -- a fumbled consent falls to the more private setting. Do not re-propose re-asking or taking the default.
type: feedback
---

The installer's "Check for updates when the game starts? [Y/n]" question (install.py `ask_update_checks`) enables the check only for Enter, `y` or `yes`; every other answer (n, no, a mistyped letter such as `g`) disables it. The maintainer tested with "G", saw it disable, and decided it stays that way.

**Why:** "Considering fumbled consent defaults to a more restrictive and private setting, this isn't going to be a problem." The question is a consent; an unclear answer must not turn the check on. The same rule already governs the resolution and shortcut questions.

**How to apply:** do not add a re-ask loop or make an unrecognised answer take the yes default; do not re-propose it. If a new yes/no consent question is added, follow the same rule: only an explicit yes (or Enter where Enter is documented as yes) enables; everything else is the restrictive choice. Related: [[feedback-restore-defaults-not-a-consent]], [[feedback-no-installer-changelog-lines]].
