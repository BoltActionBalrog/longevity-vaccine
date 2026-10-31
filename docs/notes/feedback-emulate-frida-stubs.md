---
name: feedback-emulate-frida-stubs
description: Hand-assembled (keystone/X86Writer) Frida stubs must be Unicorn-emulated against the JS law before arming — a missing push is invisible to node --check and only shows as a crash in the maintainer's run
type: feedback
---

Every hand-assembled Frida stub (keystone bytes or X86Writer) gets a Unicorn emulation harness BEFORE it is armed: drive it with the real register/stack contract, assert the callee's stack args, the return eip/esp and the preserved registers, and the arithmetic against the JS law (`SL.*`) for several g values (16/22/25/40).

**Why:** the Design Workshop v12 composite shim (2026-08-28) round-tripped cleanly through capstone and `node --check`, yet its `thunk_keyed_stretch_blit` call pushed 10 args instead of 11 (the `push ecx` src was missing) — the callee's `RET 0x2C` would have popped a saved register and crashed the maintainer's run. `_dw_crops/v12/emu_stubs.py` caught it in seconds (system `py` has unicorn; `tools\python` does not). The v9 hang (wrong primitive fed a sprite) is the same class: an unemulated stub costs a user run.

**How to apply:** keep the emulation script next to the stub source (`asm_stubs.py` + `emu_stubs.py`); stop the emulation at the call target with a UC_HOOK_CODE and compare the pushed args to the thunk's documented contract; simulate the callee's RET n and check the final eip/esp. Related: [[project-smac-design-workshop]], [[feedback-thunk-call-vs-detour]].
