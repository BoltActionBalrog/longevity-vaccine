---
name: feedback-unicorn-patch-before-run
description: Unicorn caches translated code blocks: a mem_write to code that already ran is IGNORED -- patch thunks / call sites right after E.boot, before any e.call
type: feedback
---

When prototyping a thunk by writing its bytes and its call-site `E8` into an image_emu image, write them **right
after `E.boot`**, before the first `e.call`. Unicorn keeps the translated block of any code that already executed;
a later `uc.mem_write` to that code changes memory but the stale translation keeps running -- the patched site reads
correctly back from memory and the thunk is simply never entered.

**Why:** 2026-11-07, the COMMLINK spot prototype patched 0x478C0C after `commlink_win_build` (which had already run
the site in its own repaints): the site bytes read back right, the thunk never hit, and the spots stayed native --
looked like a thunk bug for a round.

**How to apply:** give emulator helpers a `pre=` callback run straight after boot (tests/commlink_mp_emu.py `panel(...,
pre=...)`, the lobby tests' boot wrapper) and do every code patch there; `observe` hooks are fine at any time.
Related: [[feedback-emulate-engine-call-order]], [[feedback-emulate-frida-stubs]].
