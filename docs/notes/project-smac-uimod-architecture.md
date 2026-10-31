---
name: project-smac-uimod-architecture
description: Strategic direction — port the UIMod toward a hybrid binary-patch + DLL architecture (binary stays surgical; DLL for code volume)
type: project
---

DIRECTION SET 2026-06-22 (user decision): the SMACX UIMod will move toward a **hybrid** architecture, NOT stay all-static-binary-patch and NOT wholesale-rewrite to a DLL.

**Rule:** keep **binary patching surgical** — small, in-place, MD5-lockable fixes to the game's OWN UI-layout/draw math, where staying out of PRACX's hooked sites is easy. **Reach for a PRACX-style DLL** (C++, loaded so it can cooperate with / be last-writer over PRACX) when a feature needs CODE VOLUME, must win/cooperate with PRACX at runtime, or wants C++ ergonomics (escapes the hand-assembly footguns: see [[feedback-thunk-frame-aliasing]], [[feedback-thunk-disp32-offsets]]).

**Why:** our UIMod is inherently a PRACX-dependent layer (we fix the UI PRACX renders), and all-binary-patch makes us fight that layer in asm — PRACX is the runtime last-writer (the movie "intercept-above" dance, [[project-smac-movie-player]]); code space is finite (_SELFMOD full, appended .pcave2); static patches are MD5-bound to 2d0b1438 (update-fragile). What binary patching is best at and we KEEP: surgical in-place edits + the MD5/eligible-group/site-count regression harness (a byte-exact drift tripwire — but a change-detector, NOT a correctness oracle; in-game verify @4K+non-4K stays the only correctness gate). The DLL layer forfeits that static lock (runtime output).

**Full brief (canonical):** `D:\SmacxUi\work\DLL_PORT_BRIEF.md` — decision rule, open design questions (bootstrap/injection alongside PRACX since pracxpatch already owns the exe-hook slot → chain-load/proxy/own-hook + load-order choice; testing-rigor replacement; two-module coordination; addon-DLL vs fork/contribute-upstream), and the concrete FIRST STEP: prototype the thinnest DLL-addon bootstrap that loads after PRACX, confirm it can read PRACX state/hook one fn, port ONE simple existing fix, decide go/no-go on that evidence. NOT started. Caveat: this does NOT unblock native movies (PRACX owns DirectDraw regardless). Tracked in the maintainer's work log (ARCHITECTURE / STRATEGIC).
