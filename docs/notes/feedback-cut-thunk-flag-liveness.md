---
name: feedback-cut-thunk-flag-liveness
description: Cut/detour thunks must preserve EFLAGS — vanilla keeps flags live across flag-neutral instructions; a thunk replacing a neutral original must be pushfd/popfd flag-transparent
type: feedback
---

**THE LAW (discovered via the draw_queue.listx5 regression, 2026-07-25e):** the engine's compiled code keeps EFLAGS live across flag-neutral instructions — draw_queue's `MOV EAX,5` sits BETWEEN `CMP ScreenWidth,EBX` (0x4152e6) and its consuming `JNZ` (0x4152ed). Our sc() gate (`cmp [g]/jle/imul/sar`) inside a cut thunk clobbered ZF there → the wrong branch ran at EVERY resolution including g=16, where the whole patch is supposed to be a byte-identical no-op. The symptom (queue slots shifted down + bottom slot clipped at 1024) looked like a layout bug; it was a flags bug.

**Why:** x86 flag liveness spans any number of flag-neutral instructions (mov/lea/push/pop/movzx/cdq...). A cut that replaces only neutral bytes still sits inside a live cmp→jcc window whenever the original block happened to fall there — and nothing about the cut's own semantics warns you.

**How to apply:**
- A thunk replacing a flag-NEUTRAL original must be flag-TRANSPARENT: `pushfd` at entry, `popfd` before the resume, NO flag-writer after the last `popfd`. Pop-ret thunks whose arg pushes must remain on the stack route flags through a memory cell instead (`pushfd; pop [FLAGC]` … `push [FLAGC]; popfd`).
- A cut whose original ENDS with a live cmp/test must REPRODUCE that exact flag-writer as its LAST flag-writing instruction.
- Classify with capstone: WRITERS (add/sub/cmp/test/imul/sar/…), CONSUMERS (jcc/setcc/cmovcc/adc/sbb/pushfd/…), NEUTRAL (mov/lea/push/pop/cdq/…); scan forward from the cut end to find whether a consumer is reached before a writer.
- Permanent guards exist — extend them for any new cut family: `work\tests\test_strip_flag_liveness.py` (static liveness audit) and `work\tests\test_strip_g16_identity.py` (whole-function Unicorn trace-equivalence, pristine vs live at g=16 — the executable form of "1024 must be vanilla"; per-cut diffing false-positives on dead registers, function level is the right granularity).

Related: [[feedback-thunk-call-vs-detour]], [[feedback-thunk-frame-aliasing]], [[project-smac-base-screen]].
