---
name: feedback-pyghidra-ghidra-12
description: pyghidra + Ghidra 12.1 workflow gotchas for the SMACX RE project — save/transaction conflicts, Jython removal, C++ header parsing limits
type: feedback
---

Three non-obvious traps hit while standing up the pyghidra workflow for terranx.exe analysis. Each cost ~10-20 minutes of debugging on 2026-05-26 and isn't documented anywhere obvious.

**1. Do not call `program.save()` inside the `pyghidra.open_program()` context.** The context manager already commits on exit; an explicit `save()` inside it raises `java.io.IOException: Unable to lock due to active transaction`. Confusingly, the auto-save still completes — the traceback is loud but the changes persist. Just don't call save() explicitly.

**2. Ghidra 12.1 dropped Jython.** `.py` scripts passed via `analyzeHeadless -postScript script.py` fail with `Ghidra was not started with PyGhidra. Python is not available`. The working pattern is: standalone Python script that does `import pyghidra; pyghidra.start()` then uses the Ghidra API directly, invoked from a `.bat` wrapper that sets `JAVA_HOME` and `GHIDRA_INSTALL_DIR`. No analyzeHeadless involved.

**3. Ghidra's C parser cannot parse Thinker's headers wholesale.** `engine.h` and friends `#include <set> <map> <vector> <string>` etc. CParser is C-only and aborts before reaching any typedefs. For type/signature application from Thinker, extract individual typedef lines (regex `^typedef.*;`) and parse them one at a time, with manual forward-decls for the struct types they reference. Phase-1 (name-only) Thinker application via simple regex on `.cpp` address bindings already works — phase-2 (types) is the open problem.

**Why:** Each was a real time sink and is easy to re-encounter on the next pyghidra script. Trap #1 specifically produces a scary stack trace that suggests data loss when in fact nothing was lost.

**How to apply:** When writing any pyghidra script in this project, treat the open_program context as the transaction boundary — no explicit save. When writing scripts that need types from Thinker, plan for per-typedef parsing, not bulk header import. If a script claims to fail at save, verify with a separate read-only script before re-running.

Related: [[project-smac-ui-scaling]]
