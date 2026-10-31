---
name: feedback-thunk-call-vs-detour
description: To scale the SAME instruction at multiple call sites with different resume addresses, use a CALL-return helper (not a detour-JMP) so ONE thunk serves all sites
type: feedback
---

When the same machine instruction must be patched identically at **multiple sites that have different resume addresses**, prefer a **CALL-based helper** over the usual detour-JMP.

- Detour-JMP (`68 {abs32:thunk} C3` = push+ret, the standard `detour_inplace` here) tail-JMPs back to a **hard-coded resume VA** baked into the thunk → needs a SEPARATE thunk per site.
- CALL-based: replace the instruction's slot with `E8 {rel32:helper}` + NOP-pad to the original length, and have the helper do the work and **`RET`**. It returns to right after the call wherever it was called from → **one helper serves every site** with the same register convention.

Concrete case (2026-06-23, build `dbf02fc6`): the faction list pitch/gap MOV-imm stores (`MOV [ecx+esi+0x8704],0x13` / `MOV [eax+esi+0x8700],3`, 11 bytes each) appear at the build site AND two inline rebuild blocks. The build's `thunk_factionwin_pitch`/`rowgap` are detour-JMPs (resume 0x48925b/0x48926b), unusable at the rebuilds. New `thunk_rebuild_pitch`/`thunk_rebuild_gap` (pcave2 0x1930/0x1980) do the identical math but `RET`, so each covers BOTH rebuild blocks. Slot: `E8 {rel32:helper} 90 90 90 90 90 90` (5+6=11). Pattern label `instruction_to_thunk_call_plus_nop`.

**Why:** avoids 1 thunk per site (here 4 thunks → 2), and the helper's correctness is verified once.

**How to apply:** (1) confirm all sites share the register convention for the operands (e.g. ecx/eax=base, esi=window). (2) Confirm the clobbered regs are DEAD after the original instruction at every site (the helper may clobber what the call ABI allows; `popup_scale` here only touches EAX). (3) NOP-pad the slot to the original length and check no branch targets land inside it. (4) Verify rel32 follows `E8` (the assembler forbids rel32 after `E9`). See [[feedback-scaling-inline-rebuild-paths]], [[feedback-dual-purpose-thunk]], [[feedback-thunk-frame-aliasing]].

**THE INVERSE BUG (2026-07-04, a0da407d → fixed 15470723): an E8-CALL-entered thunk MUST consume the pushed return address** — end with a bare `RET` (returns to site+5, typically the pad NOP, falls into the resume point) or pop it explicitly. `thunk_nw_rectscale` was entered by `E8` but ended detour-style (`push resume; ret`), leaking the ret addr on the stack. **The leak is invisible to rendering and to esp** (the host function's `mov esp,ebp` epilogue repairs esp) — but the epilogue's `pop edi/esi/ebx` shift one slot, so the CALLER's callee-saved regs come back as garbage: multiplayer_init's esi(=1) became 0x4829D3 and the LAUNCH GAME retcheck (`cmp eax,esi; jl`) silently bounced to the main menu at every resolution, despite all visual verifies passing. Diagnostic signature: a caller register holding a code address just after the patched callee returns = a leaked/shifted stack slot. LESSON: every screen lock needs a FUNCTIONAL pass (enter → act → exit → consequences), not just visual verification.

**3rd instance (2026-07-06, hud_widgets_scale N thunks, build 680a2941 → hotfix 5bab9446):** all 15 push-resume-tail N-join detours omitted the consume — every join execution leaked the E8 ret addr; WER dump showed EIP=0 with esi/edi = site+5 of n10/n11 (register pops shifted, exactly the LAUNCH GAME shape). CHECKLIST RULE: for EVERY E8-entered thunk, classify the tail before assembling — (a) bare RET (call-helper, 5B site, resume==site+5), (b) add esp,4 + displaced + push resume + ret (detour with patchlen>5 or displaced instrs), (c) tail-jmp to a real callee whose own RET n consumes it (call-redirect). A push-resume tail WITHOUT the add esp,4 is never correct.
