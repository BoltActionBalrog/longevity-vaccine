---
name: feedback-terranx-h-symbol-format
description: Rule — record every newly-confirmed symbol in work/symbols/terranx.h immediately, in the narrative-less one-line format, and apply it to the Ghidra DB
type: feedback
---

When we confirm a new symbol during RE (function addr/name/signature, global, or struct field offset), add it to `D:\SmacxUi\work\symbols\terranx.h` **in the same change** AND apply it to the Ghidra project via `run-apply-local-symbols.bat --apply`. Don't leave a confirmed symbol only in a note or a decompile dump.

`terranx.h` is **symbols only — narrative-less**. No rationale/status/"tried-failed"/code-site annotations/cave inventories (those go to `docs/notes/` or `work\patches\*.yaml`). Three line shapes (origin = `thinker` | `observed` | `guess`):
- Function: `extern <ret> <name>(<args>);  // addr: 0xADDR  <origin>  <conv/RET-imm/brief>`
- Global:   `extern <type> <name>;         // addr: 0xADDR  <origin>  <brief>`
- Field:    `// field: <Struct> +0xOFF <type> <name>  <brief>`

Use `()` for unknown args. Adopt Ghidra/Thinker's authoritative name instead of inventing a synonym.

**Why:** the file is parsed by `apply_local_symbols.py` and meant to be parsed by others; the old mixed free-form tables were unparseable and had drifted out of sync with the Ghidra DB. A single uniform format keeps it both human- and machine-readable.
**How to apply:** the three line shapes above are the spec. Validate with a `--apply` dry-run; `skip_named` rows flag name forks to reconcile. Related: [[project-smac-ui-scaling]], [[feedback-yaml-utf8-encoding]].
