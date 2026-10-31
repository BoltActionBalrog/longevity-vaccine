---
name: feedback-templatize-branch-operands
description: when auto-templatizing assembled bytes into patches.yaml placeholders, never touch branch (jmp/jcc/call) operands from capstone — they are ABSOLUTE targets, not the encoded rel32; round-trip the emitted hex through the patcher before baking
type: feedback
---

Build 1a2da25b (2026-08-22 council bake) hard-crashed on council open: `thunk_cw_seeds`' tail
`jmp Font_init` shipped as `E9 {abs32:Font_init}` — capstone reports a rel8/rel32 branch
operand as its resolved ABSOLUTE target, so an operand-driven templatizer that maps "IMM ==
symbol VA" to `{abs32:}` silently writes an absolute address into a relative field (EIP =
thunk+5+0x618F40 = 0x1038244, esp garbage, crash reached "from ntdll" per WER).  The same
hit `jmp Sprite_draw_2` and `jmp Buffer_box_sprite`.  The Unicorn parity suite emulates the
RAW keystone bytes, so the templating step was the one link no test covered.

**Why:** the yaml's `{rel32:}` is accepted only after `E8`; `{abs32:}` is for `push imm32` /
`mov`/`cmp` immediates and `[disp32]` memory operands.  Branch encodings are relative; only
`call` gets a `{rel32:}` placeholder, every other branch stays literal (engine targets) or is
written as `push {abs32:sym}; ret` (relocation-safe cave tails).

**How to apply:** in any assembler with a templatize/placeholder pass (`assemble_council.py`
is the reference): skip every `j*`/`call` mnemonic in the operand scan; then ALWAYS run the
round-trip check before splicing — `ap.ByteTemplate(hex).resolve(va, symtab) == assembled
bytes` for every entry (`roundtrip_problems()` / `test_template_roundtrip_is_exact`), plus
"no placeholder token follows an E9/0F8x byte".  When a bake crashes, the crash catcher
pattern (`hook_council_crash.js`: AV handler + numbered thunk entry/leave trace) names the
last live thunk in one run — disassemble THAT thunk's live bytes before theorizing.
Related: [[feedback-cave-ledger-lengths]], [[feedback-thunk-call-vs-detour]], (a private note).
