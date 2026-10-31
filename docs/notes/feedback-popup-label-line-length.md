---
name: feedback-popup-label-line-length
description: A DLL-generated popup label file must keep every PHYSICAL line short (<= ~96 chars): the engine's script-line reader has a fixed stack buffer sized for vanilla's <= 106-char lines; one 330-char body line smashed the stack (crash at the main menu, fault EIP = our own text)
type: feedback
---

**Never put a long popup body on one physical line in a generated label file.** The engine's
text reader (`text_open`/line get behind `pops_18`) copies each physical line into a fixed
stack buffer sized for `script.txt`'s lines (longest vanilla line: 106 in script.txt, 174 in
conceptsx.txt). The first in-game run of the update prompt (2026-09-27, scenario `base`) wrote a
~330-character body line; the game hard-crashed the moment the menu appeared, WER fault offset
`0x6f662066` = ASCII "f fo" from "...off for good..." -- the return address was our own text.

**Why:** consecutive body lines are JOINED by the engine with a space (2,461 wrapped paragraph
lines in vanilla script.txt, only 24 end with a space), so wrapping costs nothing; `^` is the
explicit line break. Long lines are the one thing vanilla files never contain, so nothing in
the engine defends against them.

**How to apply:** `update_core.h` `BuildLabelFile` wraps the body at spaces to
`kMaxPhysLine = 96` (hard-breaks a longer word); `test_update_core.py` pins the cap and that
joining the lines with one space gives the sanitised body back. Any other generated script
text (aivis's GETOUT file copies vanilla lines, so it is safe) must do the same. A crash whose
fault address decodes as ASCII is a stack smash by text: look for the longest string you emit.
