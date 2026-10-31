---
name: feedback-proto-cave-offsets-after-bake
description: A Frida proto that attaches to cave THUNK offsets goes stale on the next bake (thunks move); the stale attach throws at load and silently kills every attach after it -- re-check offsets against patches.yaml before each run
type: feedback
---

Every bake can move cave thunks (a grown thunk shifts its neighbours: bake v6 grew `t_rw_wheel_down` 175->188B and `t_rw_wheel_up` moved pcave2+0x23f70 -> +0x23f80). A proto script still attaching at the OLD offset lands mid-function; Frida's `Interceptor.attach` throws at script load, and because the script is straight-line top-level code, EVERY attach/cave after that statement is skipped — no error in the log, just missing line families (runs 5/6 of the kinds proto 2026-09-07: zero REDRAW/PRESENT/ENLARGE/LISTFIX lines, no `ready`; cost two user runs).

**Why:** thunk offsets are ledger data (`patches.yaml` cave ledger), not stable addresses; a proto file written before a bake carries pre-bake numbers.

**How to apply:** (1) after ANY bake, before re-arming a proto, cross-check every `PC + 0x…`/`PCAVE2 + 0x…` it uses against the yaml ledger (scratch one-liner: regex the ledger, print `offset -> symbol`; anything not a ledger entry = stale). (2) Wrap every proto `Interceptor.attach` in `try/catch` that LOGS the error — a silent partial arm is worse than a loud failure. (3) When a run's log lacks a line family that a previous run had, suspect a load-time throw FIRST (compare per-family counts across archived runs), not the game. Related: [[feedback-frida-attach-branch-target]], [[feedback-frida-readcstring-fixed-buffers]].
