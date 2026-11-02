---
name: feedback-no-maintainer-paths-as-instructions
description: Never state the maintainer's own disk paths (D:\SmacxUi, the GOG Galaxy install) in public/player text as if they would work for users
type: feedback
---

Never write the maintainer's actual disk paths in public or player-facing text (README, release notes, installer messages, docs) in a way that reads as an instruction that should work for users. "Clone to `D:\SmacxUi`" and example game paths shaped like the maintainer's own install are both out. If a tool really does hardcode a maintainer path, describe it generically ("the maintainer's checkout folder") and say how to work around it. Examples must be obviously generic.

**Why:** the maintainer, 2026-11-01, reviewing the public longevity-vaccine README. A player or contributor copying such a path gets something that only works on the maintainer's machine, and it exposes the operator's layout.

**How to apply:** check every public README/notes/installer string for `D:\`, `SmacxUi` or `GOG Galaxy` before committing. The exported tree still has ~130 files hardcoding the checkout path, which is a known gap. Related: (a private note), (a private note).
