---
name: feedback-thunk-disp32-offsets
description: Hand-assembled x86 thunks: struct offsets >= 0x80 MUST use disp32 ModRM, not disp8 — disp8 sign-extends and reads a negative offset (silent garbage -> crash)
type: feedback
---

When hand-assembling a thunk byte template (in `assemble_thunks.py`), a memory operand `[reg + disp]` with **disp ≥ 0x80** (or ≤ −0x81) MUST be encoded with the **disp32** ModRM form, NOT disp8. A disp8 is a SIGNED byte: `0x80` decodes as −128, so `8B 47 80` ("mov eax,[edi+0x80]") actually reads `[edi−0x80]` — wrong address, silently. Common SMAC Buffer fields live at +0x80 (W) / +0x84 (H), right at this boundary.

- Wrong: `8B 47 80` (disp8) → reads [edi−0x80]
- Right: `8B 87 80 00 00 00` (disp32) → reads [edi+0x80]

The disp32 form = same opcode, ModRM byte with mod=10 (e.g. 0x47→0x87 for EDI base/EAX reg), then the offset as 4 little-endian bytes. Offsets that DO fit a signed byte (−0x80..+0x7F, e.g. `[ebp-4]`, `[ebp+0x1C]`) are fine as disp8.

**Why:** caused a hard crash in `thunk_deco_soft_update` (see [[project-smac-menu-strip-scaling]]) — three `[edi+0x80]`/`[edi+0x84]` reads encoded as disp8 fed garbage to scale_x/scale_y → junk GraphicWin_soft_update region → fault. The sibling deco-blit thunk was fine because all its offsets were small `[ebp+..]` values.

**How to apply:** when writing a thunk template, scan every `[reg+disp]` operand; if `disp >= 0x80`, force disp32. Cross-check against the engine's own encoding of the same field — the original SMAC code already uses disp32 there (e.g. `8B 8F 80 00 00 00`), so copy its ModRM/disp width. Better: verify the assembled thunk's first instruction bytes against the binary after apply (a quick disassemble-and-compare catches this immediately). Related thunk-authoring gotchas: [[feedback-dual-purpose-thunk]], [[feedback-buffer-resize-per-blit]].
