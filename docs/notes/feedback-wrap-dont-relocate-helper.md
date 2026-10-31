---
name: feedback-wrap-dont-relocate-helper
description: When a shared cave helper must grow and can't in place, wrap it at the ONE caller that needs new behaviour instead of relocating it — a hardcoded E8/E9 caller (not a {rel32:} placeholder) silently breaks on relocation
type: feedback
---

fe_pair_remap needed ~118B more for the 0x41/0x54 list-hatch pair (EDITORWHO picker, 2026-08-14)
with 92B slack. Relocating it looked free ("all callers use {rel32:}") — the consumer census of the
BUILT exe (scan for E8/E9/abs32 to its VA) found 4 callers, one being sb_restripe's HARDCODED
`E8 D9 F9 FF FF` (a cave-internal call written as literal bytes, invisible to a placeholder grep).
Solution: thunk_s54_restripe WRAPS fe (calls it, then does the new work) and only devfill's
`{rel32:thunk_fe_pair_remap}` placeholder retargets to the wrapper; fe stays put.

**Why:** cave-internal calls are often literal rel32 bytes; relocation retargets only placeholders.
The 26l base-screen lesson (census the built exe) and this one are the same failure class.

**How to apply:**
- Before moving ANY cave symbol: census the built exe for E8/E9/abs32 refs to its VA
  (`work\scripts\cave_map.py --at` for neighbours; a byte scan for consumers).
- If any consumer is a literal, don't relocate — wrap at the caller that needs the change, or
  give the helper a jump-stub at its old address.
- Prefer wrappers whenever the change is "helper + extra tail for one family": the other callers
  keep their exact bytes and their verified behaviour by construction.
- A jump-stub/trampoline at the old address only preserves ENTRY. Interior-literal refs (a
  self-modifying write to `helper+5` = a `cmp imm32` operand) now hit the stub's bytes: rail_gate v4
  (2026-09-26p) left `push; ret` at 0x11200 and the DW picker bracket's `mov [gate+5], ecx`
  overwrote the `ret` -> every DW part picker crashed at g>16 (fixed 2026-09-27, exe ed30ac8b).
  Census `+N` literals too (grep assemblers for `_IMM =` / `+ 5`), derive such addresses from the
  owner's assembled bytes, and rely on test_patch_integrity::test_self_modifying_writes_land_on_an_operand.
See [[feedback-cave-ledger-lengths]], [[project-smac-scenario-editor]].
