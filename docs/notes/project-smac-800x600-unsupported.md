---
name: project-smac-800x600-unsupported
description: User decision 2026-10-22 -- 800x600 is NOT offered by the game and NOT officially supported; never ask the maintainer to test it
type: project
---

800x600 is not offered by the game's resolution choices, and the maintainer will not test it or officially support it ("No user
will ever run it"). Never put 800x600 on an in-game checklist or ask for an 800x600 shot.

**Why:** 2026-10-22, after the bug-sweep deploy (exe b0464831) whose checklist listed 800x600 items (main-menu strip
size, planet-customisation preview from fix 15).

**How to apply:** keep emulation tests that cover 800x600 where they already exist (they are cheap and guard the g <= 16
path), but do not design work around it and do not ask for in-game verification there. The lowest resolution the maintainer
verifies is 1024x768 (the baseline, [[project-smac-scaling-baseline-1024]]); 16:9 native-scale widescreens (1280x720,
1366x768) remain in scope.
