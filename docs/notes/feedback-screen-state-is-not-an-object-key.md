---
name: feedback-screen-state-is-not-an-object-key
description: A screen/global state flag ("talk open", "editor active", iface mode) is never a proxy for a per-object property (anchored, modal, owner) — read the object's own field through whatever register reaches it
type: feedback
---

When a thunk needs "is THIS popup/window the special one" and the object is "not in a register",
do not substitute a screen-state global. Find the object through the register that IS live (a
subobject pointer with a known fixed offset — `esi - 0x2230` from the Dialog_type16_attach this,
`esi - 0x1800` from the Dialog_type16_calc this) and test the engine's own condition on the
object's field.

**Why:** 2026-09-26 (exe 282472ae): the diplomacy bake's type-16 wrappers keyed "anchored speech box"
on talkOpen (`[DiploTalkWin+0xA94] != -1`). Any ORDINARY popup raised while the talk is open (the
#ASKSEEDESIGN prompt after a tech trade) matched too and drew native-width rows beside a scaled OK
bar. The screen state was true for the whole talk; the object property (BasePop +0xA14 != 0) was
false for that popup. Sibling of [[feedback-gate-flag-refcount]] and
[[feedback-site-keyed-table-shared-painter]]: a state that outlives the object it was meant to
describe becomes a key for every later object.

**How to apply:** when writing a gate, ask "what does the ENGINE test to take the branch I am
mirroring?" and test exactly that field (here BasePop_calc 0x60391A / exec_3 0x602677 test
`[+0xA14] != 0`). If the object truly is unreachable at the site, move the gate to a site where it is
reachable, or stash the object pointer at a site that has it and key on identity — never on a
global that merely correlates. Census: grep every assembler source for the screen-state address
(0x734424 here) before calling a bake done. See [[project-smac-diplo-talk-screen]].
