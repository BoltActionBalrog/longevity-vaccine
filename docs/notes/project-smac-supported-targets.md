---
name: project-smac-supported-targets
description: Public release targets are the PRACX exe and PRACX+Thinker ONLY (Thinker without PRACX is NOT a target, user 2026-10-28); vanilla terranx.exe is a dev tool, Scient's patch is not a target
type: project
---

The mod supports exactly two public targets: the PRACX-patched exe and Thinker. The plain vanilla `terranx.exe` is a developer tool only (Win11 crash fix, clean baseline; decision 2026-09-27), and Scient's patch is not a target. The maintainer restated this on 2026-10-03 when I listed "Scient's patch and vanilla exe checks" as queued work from a stale COMPATIBILITY section in the maintainer's work log (since corrected).

**Why:** the maintainer made the call to limit scope; older notes still spoke of adding Scient's and vanilla as targets.

**How to apply:** do not propose, plan or list work for Scient's patch or a public vanilla target. Vanilla-exe checks are only dev sanity launches (DLL loads, features disable cleanly). Compatibility work means Thinker: [[project-smac-thinker-compat]].

**Refinement (user, 2026-10-28):** "Thinker" means PRACX + Thinker only. Thinker on the plain vanilla exe is not a shipping target; drop the `thinker` yaml target and keep `pracx_thinker`. Rule for that work: [[feedback-thinker-conflicts-user-decides]].
