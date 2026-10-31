---
name: feedback-frida-hook-vs-dll-bytecheck
description: A Frida hook on a function entry that uimod.dll byte-checks at startup makes that DLL feature disable itself under the trace
type: feedback
---

Never attach a Frida probe to an address uimod.dll byte-checks at install (memcmp of an entry or call site).
Frida rewrites the entry before the DLL's install runs (spawn mode), the memcmp fails, and the feature
silently turns itself off for that run -- the 2026-10-07 camera rows vanished from the prefs page only
under the trace because hook_modernctl.js hooked Console_center 0x515400, which modernctl.cpp checks.

**Why:** the failure looks like an engine/PRACX stomp and sends you hunting the wrong culprit.
**How to apply:** before adding a probe host, grep `src\uimod\src\*.cpp` for its VA (kVA_* constants);
if the DLL checks it, observe through a neighbour (the caller's origin change, the callee) instead, or
DEFER the attach until after the DLL has bound (hook_dragscroll.js attaches gen_map 0x469CA0 from the
first Win_update_screen call -- every install-time memcmp has run by then; a function entry only, never an
interior address: onLeave swaps [esp], which mid-prologue is a local). When a DLL feature reports a
byte-check failure, first ask whether that launch was a Frida trace -- and before reading ANY profile
number, read the feature's `installed` log line for that session (2026-10-10: two profiler runs measured
PRACX's stock redraw because mapscroll had disabled itself; make every Bind() name the failing site).
Related: [[feedback-frida-attach-branch-target]], [[feedback-uimod-shared-dll-gate]].
