---
name: project-smac-endgame-screens
description: Retirement Holobook + end-game Replay scaling: built, audited, merged on integration/endgame-scale, INSTALLED 2026-11-15 (exe 1a10929b), awaiting the maintainer's in-game check
type: project
---

**ARC CLOSED 2026-11-15: MERGED to master (dd8f5fa, fast-forward from integration/endgame-scale; + the Replay analysis docs f32950d) and PUSHED to origin 2026-11-15.**
master's lock = the installed exe 166795d3 (Thinker cbe1b177). Both screens user-checked in game at 4K / 1920x1080 /
1600x1200 / 1024x768 and re-measured from the shots (Replay map L=R exact, T/B within 2 px, all rows drawn).
CHANGELOG 1.0.1 lines added (the maintainer's wording for the scaling line; the replay-map row bug as a base-game fix).
Previous live build kept as `terranx_PRACX.exe.baa1e5d7.bak`. Worktrees and branches removed; pristine references
committed and pushed (fa44162, refs\pristine\EndGame). Possible
same vanilla row bug on the main map's whole-world zoom-out / HUD minimap: reported, never investigated.

User decisions (2026-11-15):
- Holobook: Hall of Fame letterbox; fonts at vanilla's SNAPPED size x num/16 ([[feedback-font-law-snapped-size]]);
  no line-pitch override (decided after the in-game look: keep); vanilla line breaks (lever: the earlier of the vanilla
  and the scaled break); CLOSE/BACK bevels stay at the popup g above 40, like the HOF.
- Replay: map option A (the engine's zoom fit); the window grows 4:3 where the map would clip a row, only where the
  map is drawn, never past the screen.

Plans and maps: `work\_hb_static_map.md`, `work\_replay_static_map.md`. Audit: 5 reviewers + 1 on the fix commits;
every finding fixed or accepted (artbox stripe runs < 1% off-grid: look for it in game).
