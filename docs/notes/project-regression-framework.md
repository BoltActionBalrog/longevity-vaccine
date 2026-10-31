---
name: project-regression-framework
description: where the modal regression-testing framework lives and how to run both layers
type: project
---

Modal regression framework lives entirely under `D:\SmacxUi\work\tests\` (built 2026-06-07). Two layers guarding patcher work on new modals from breaking finished ones:

- **Layer 1 (static, automated, <1s, no game):** pytest suite. `run-tests.bat` or `PY -m pytest work\tests -q` (PY = bundled `tools\python\python.exe`; needs pytest, installed). The bat's trailing `pause` was REMOVED 2026-07-03 (user request) after it hung two background runs at "Press any key" — safe for automation now, but the analyzeHeadless.bat pause gotcha still stands. Adding a group also requires updating test_apply_md5.py's EXPECTED_ELIGIBLE_GROUPS + the "Will write: N site(s)" count, alongside target.patched_md5. Imports production `apply_patches.py`/`config.py` in place via conftest `sys.path`. Checks vs pristine `.bak` + live `patches.yaml`: every confirmed site's anchor/original bytes, every cave (padding/fit/overlap/section-bump/new-section), symbol existence, every code thunk disassembles + ends in control transfer, and **apply→`target.patched_md5` byte-exact lock** + the 19 eligible groups. test files: test_patch_integrity / test_apply_md5 / test_thunk_disasm.

- **Layer 2 (runtime NUMERIC snapshots, semi-auto — you navigate):** `probe_modal.js` (Frida) hooks Popup_on_draw_background(0x405c80) for the popup struct fields (box/window/content/margins/band/header/footer/screen_rect/dialog) + BaseButton_init(0x607210) for buttons (id/x/y/w/h). Writes `snapshots\<slug>@<WxH>.json`. Capture via `run-capture-<WxH>.bat` (self-elevates, sets res via run-at-resolution.ps1, passes `-FridaDir ..\scripts -FridaHook "..\tests\probe_modal.js"` so probe stays under tests/ unprod-modified). **Navigate DIRECTLY to the target modal** — buttons accumulate globally, so detouring through a screen that doesn't hit 0x405c80 (Datalinks/external windows) leaks its buttons forward. `compare_snapshots.py` = same-resolution numeric diff (±2px, exact for scale_num/branch/title/row_count/button-count); `--update` re-baselines snapshots→golden. goldens (`*.json`) committed in `golden\`, `snapshots\` gitignored. **PIXEL/PNG capture was REMOVED 2026-06-07** (numpy/pillow not needed by Layer 2) — see [[project-smac-l2-pixel-capture]].

RULE confirmed by user 2026-06-07: **all new testing files go under a single `tests\` folder** (don't scatter into scripts/). See [[feedback-testing-files-under-tests]].

KEY FACT discovered: `patches.yaml` `patched_md5` was stale (27cb07f0); current full patch set applied to pristine 2d0b1438 produces **339edc01** (= live binary). Updated patched_md5 to 339edc01 — the Layer-1 MD5 test asserts against it, so update it whenever patch output changes intentionally.

Groups have NO `status` field; gating is site-level (`sites[].status`). 3 groups skip on pristine base (popup_bar_fill, win11_24h2_cs_zeroinit, popup_button_font_scaling) → 19/22 eligible. See (a private note).
