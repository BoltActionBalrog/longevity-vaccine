---
name: feedback-pristine-baseline-trace
description: Capture vanilla-baseline traces on the PRISTINE exe, not the patched exe at g=16
type: feedback
---

When a fix needs a measured VANILLA baseline (native geometry, reserve fields, font metrics), trace the **pristine binary**, not the patched exe at 1024×768 — even though every lever is designed to be a g≤16 no-op.

**Why:** a buggy lo-res gate silently leaks a patched value into the "native" numbers and the derived vanilla law is poisoned (this exact gate-slip class has happened: the 0x3FF ScreenWidth gates). The maintainer called this out 2026-07-03 during the Quit box-height work.

**How to apply:** `work\run-frida-pristine.bat <hook.js> <W> <H> [pre.js]` — self-elevates FIRST, then sets `SMACX_EXE_NAME=terranx_pristine.exe` (an env var set before elevation is lost — Start-Process -Verb RunAs starts a fresh environment), then chains to run-frida-at-res.bat. `terranx_pristine.exe` = copy of the .bak (MD5 2d0b1438) in the game dir; recreate with `Copy-Item` if missing. Hooks attach by engine-function address so they run unchanged; our cave globals (e.g. g_popup_scale_num @0x668740) read 0 on pristine — expected, log-only. Related: [[feedback-loores-gate-on-g]], (a private note).
