---
name: feedback-keystone-semicolon-separator
description: Keystone reads ';' as an instruction SEPARATOR, not a comment -- a ';'-commented asm source hangs the assembler; comment with '#' and strip before ks.asm
type: feedback
---

Keystone (the `keystone` Python module used by `work\scripts\assemble_*.py`) treats `;` as the
x86 statement separator. An asm source with `; comment` tails hands the comment text to the
parser as instructions and the process hangs (observed 2026-10-11, assemble_uimod_preload.py:
>120 s, killed).

**Why:** Keystone's x86 parser follows the LLVM MC convention where `;` separates statements on a
line; it has no comment syntax of its own.

**How to apply:** write comments with `#` in the ASM string and strip them before assembling
(`line.split('#', 1)[0]` per line, as `assemble_uimod_preload.py` does), or keep comments
outside the string. Always run the assembler under `timeout` so a parser hang cannot block a
session. Verify bytes with capstone afterwards (an inline string inside code disassembles as
garbage past the `call` that skips it -- expected). See [[project-smac-nonnative-fullscreen-flashing]].
