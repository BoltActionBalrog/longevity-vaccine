---
name: feedback-no-installer-changelog-lines
description: The installer gets NO changelog lines -- it is a net-new program, not a change to the game
type: feedback
---

`work\CHANGELOG.md` tracks changes to the GAME only. The installer (INSTALL.bat, the folder picker, the module
picker, the Thinker set-up, the shortcut offer, installer fixes) gets no lines at all, in any release (user
2026-11-04: "The installer is a net new program and does not need to be tracked as a change to the game").

**Why:** the changelog's reader is a player comparing the game to the last release; the installer is the vehicle,
not the game.

**How to apply:** never add an installer line; when an existing line mixes game and installer facts, keep the game
part only. The in-game update prompt, Preferences switches and anything the DLL does in the game are game changes
and do get lines. Complements [[feedback-changelog-vanilla-baseline]].
