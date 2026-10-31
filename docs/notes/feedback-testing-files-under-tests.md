---
name: feedback-testing-files-under-tests
description: keep all testing/regression files in one tests folder, not scattered
type: feedback
---

All files for testing must live under a single `tests\` folder (for SMACXUi: `D:\SmacxUi\work\tests\`) — not split across `scripts\` and elsewhere.

**Why:** user explicitly corrected an initial plan that scattered Layer-1 pytest files into `tests\` and Layer-2 capture scripts into `scripts\` (2026-06-07).

**How to apply:** put probes, drivers, comparators, fixtures, goldens, and the runner wrapper all under `tests\`. Reuse production code by importing it in place (conftest `sys.path.insert(scripts)`), don't copy it. See [[project-regression-framework]].
