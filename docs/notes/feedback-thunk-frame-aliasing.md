---
name: feedback-thunk-frame-aliasing
description: Hand-assembled thunk that pushes callee-saved regs THEN uses [ebp-4/-8/-c] as locals corrupts the caller — reserve the local frame BEFORE the reg pushes.
type: feedback
---

In a hand-written stack-frame thunk, if you `push ebx/esi/edi` right after `mov ebp,esp`, the saved
registers land at `[ebp-0x04/-0x08/-0x0C]`. Do NOT then use those same offsets as local variables —
storing locals there overwrites the saved registers, and the epilogue `pop`s garbage back into the
caller's callee-saved regs → the caller faults (e.g. uses a 131 as a `this` pointer → AV).

**Why:** a function-REPLACING detour owns the full callee-saved-register contract (ebx/esi/edi/ebp must
round-trip). A Frida onLeave prototype never exposes this bug because Frida's trampoline preserves
registers itself — so "works in Frida, crashes as a thunk" points straight here.

**How to apply:** reserve the local frame FIRST, then push the regs, so saved regs sit BELOW the locals:
`push ebp; mov ebp,esp; sub esp,SIZE; push ebx; push esi; push edi` … `pop edi; pop esi; pop ebx;
mov esp,ebp; pop ebp; ret N`. Locals `[ebp-4..-SIZE]` no longer alias the saves (now at `[ebp-SIZE-4..]`).
Cheapest way to catch such a fault: a process-wide `Process.setExceptionHandler` that dumps regs+frame
(do NOT `Interceptor.attach` the detoured fn — that relocates the patched bytes). The corrupted register
values will literally equal your thunk's local values, naming the bug. See [[project-smac-a5-native-frame-thickness]],
[[feedback-thunk-disp32-offsets]], [[scaling-sprites]].
