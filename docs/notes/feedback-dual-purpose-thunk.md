---
name: feedback-dual-purpose-thunk
description: When two related values need scaling but only one binary site is convenient to patch, fold both transformations into a single 21-byte thunk that exploits MSVC __thiscall's callee-saved register convention.
type: feedback
---

**Pattern:** if you need to scale a register value at a code site that's hard to patch directly (e.g., the only available bytes are mid-instruction-sequence with no spare slot), look upstream/downstream for an UNRELATED 6-byte instruction you ARE patching, and fold the extra transformation into that thunk.

**Concrete example (load-bearing for the menu_strip_scaling patch, 2026-05-28):**
The GraphicWin_init `height` arg comes from EAX as computed at `0x4ADE1C: ADD EAX, EDI`. EAX is then consumed at:
- `0x4ADE48 SUB ECX, EAX` (Y position)
- `0x4ADE4A PUSH EAX` (height arg push)

There's no patchable instruction between `0x4ADE1C` and `0x4ADE48` that gives us a clean 5+ byte slot to insert a CALL — every byte in that range is doing essential work. But we ALSO needed to patch `0x4ADE25 MOV EDI, [ESI+0x1198]` (6 bytes) to return a scaled value in EDI. That patch site happens to sit between EAX's computation and EAX's consumption.

**Solution:** make the thunk at `0x4ADE25` do TWO things:

```asm
thunk_load_strip_w_into_edi:    ; called from 0x4ADE25 (in place of MOV EDI, [...])
    call scale_uniform           ; EAX (= menu_total_height) → scaled in place
    push eax                     ; save scaled_menu_height
    mov  eax, [esi + 0x1198]
    call scale_uniform           ; EAX = scaled_W
    mov  edi, eax
    pop  eax                     ; restore scaled_menu_height into EAX
    ret
```

21 bytes total. On return, EAX holds scaled menu_total_height (consumed correctly by both 0x4ADE48 SUB ECX, EAX and 0x4ADE4A PUSH EAX) AND EDI holds scaled strip_W (consumed at 0x4ADE37 SUB EDX, EDI).

**Why it works:**
1. **`scale_uniform` preserves ECX/EDX/EBX** via internal push/pop. So the first call's clobber of those registers in the thunk's own frame doesn't leak.
2. **MSVC __thiscall convention**: EAX is caller-saved (return value), so the caller never expects EAX preserved across a CALL. Modifying EAX inside our thunk is legal.
3. **The chain of ADD EAX, EDI → ... → SUB ECX, EAX → PUSH EAX** all uses EAX without touching it intermediately. Scaling EAX once in the middle, with no other instruction reading it between the scale and the use, is fine.

**How to apply:**
1. When you have a tight cluster of register-dependent computations and need to inject a scaling step, audit the data-flow: find the last write of each register before the consumption you want to influence.
2. If you're already patching a 5+ byte instruction in that window, prefer growing that thunk over inserting a brand-new patch site. Less invasive, fewer anchors to maintain.
3. Watch the calling convention: only do this if the registers involved are caller-saved at the patch site OR if your thunk explicitly preserves the callee-saved ones.

**When NOT to use this pattern:**
- If the registers involved span complex flag-dependent code (Jcc after the patch site), don't risk losing flags through CALL.
- If the chained transformations could be implemented at separate sites without bloating the patch group's site count meaningfully, prefer separate thunks for clarity.

Related: [[project-smac-menu-strip-scaling]], [[project-smac-patcher-v02]], [[feedback-buffer-resize-per-blit]]
