---
name: feedback-unicorn-stub-overlap
description: Unicorn parity tests — a recording stub written at a real helper's VA must fit that helper's slot (else it overwrites the next helper's stub) and re-stubbed code needs ctl_remove_cache; symptoms are READ_UNMAPPED faults at a mid-instruction eip
type: feedback
---

When a parity test stubs an ENGINE-ADJACENT cave helper at its real VA (e.g. t_ffn @0x2E570 and t_fdirect_a14b @0x2E590, 32 bytes apart), a stub body longer than the slot silently overwrites the neighbour's stub; Unicorn then executes a spliced instruction stream and dies with UcError errno 6 (READ_UNMAPPED) at a mid-instruction eip and stale register values (rw test 2026-09-17: the 34-byte t_ffn stub ran over the a14b stub at +0x20).

**Why:** the helper block packs thunks 16-aligned; stubs are free-form asm and nobody checks their length against the slot.
**How to apply:** at a real helper VA write only a 5-byte `jmp STUB+off` and put the body in the test's STUB area; and after re-writing bytes at an address a cached Unicorn instance has already executed, call `uc.ctl_remove_cache(va, va+len)` (or `ctl_flush_tb`) — the mon/hof tests do this in `_reset`, the rw `Emu.stub` now does it per stub. When a fault's eip is not an instruction boundary, disassemble the bytes AT the eip and trace the last instructions with UC_HOOK_CODE before theorising. Related: [[feedback-emulate-frida-stubs]], [[project-smac-font-face-weight-audit]].

**Companion (2026-09-17, t_se_enter2 v1): a recording stub that preserves registers the REAL callee clobbers proves nothing.** The parity stub for thunk_se_immfix was `inc [rec]; ret`; the real walker clobbers eax/ecx/edx, so the wrapper that forgot `push ecx / pop ecx` around it passed every test and handed SocialWin_build a stack address as `this` (AV 0x4B2780 on opening the screen). **How to apply:** every stub standing in for an engine function or a cave helper must trash eax/ecx/edx (`mov eax/ecx/edx, 0xBAD`) unless the callee is documented to preserve them; when porting a wrapper, copy the register discipline of the thunk it replaces (asm_se_enter had the push/pop) before changing anything else.
