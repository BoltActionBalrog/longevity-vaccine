---
name: feedback-no-external-movie-player
description: Hard requirement — the movie solution must play IN-PROCESS, never spawn an external app like PRACX's playuv15
type: feedback
---

HARD REQUIREMENT (owner, restated 2026-06-28): the cinematic-playback fix must play movies
**in-process**, rendering into the game's own window. It must NOT spawn an external application —
spawning `movies\playuv15.exe` is exactly the PRACX behavior we are eliminating (it causes the
disruptive desktop-resolution change + focus/z-order issues).

**Why:** an external player is a separate process with its own window/display device; that is the
root of the resolution drop and the disruption the whole effort exists to remove. "Just point
PRACX's MoviePlayerCommand at a better external player (mpv, etc.)" is OFF the table for the
shipped solution, even though mpv would be higher quality — it still violates the in-process rule.

**How to apply:** design playback as an in-process decoder (libav in `uimod.dll`) that blits frames
to the game window (phWnd) — see [[project-smac-movie-player]] CONVERGED PLAN.
Do not propose external players. (The MCI/AVI built-in path is acceptable because it is
in-process, but the chosen design is our own in-process decoder.)
