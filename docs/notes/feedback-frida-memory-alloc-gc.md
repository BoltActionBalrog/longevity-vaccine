---
name: feedback-frida-memory-alloc-gc
description: Frida Memory.alloc pages AND CModule objects are FREED when the JS reference is garbage-collected — retain every one in a module-level array; a NativeFunction holds only the raw address
type: feedback
---

`Memory.alloc()` in Frida returns a page that lives only as long as the JS `NativePointer` is referenced. A `const p = Memory.alloc(...)` inside a loop or function is freed at GC and the NEXT alloc hands back the SAME page, overwriting the code the patched sites already jump into.

**Why:** DW proto v13 (2026-08-29) hard-crashed at 4K load: all four option-E Caviar stubs AND the composite shim logged the same address `0x3b00000` (v12 had four distinct pages). The first HUD unit draw jumped into what was now shim bytes → `Buffer_draw_2` entered with `this`=0x7e2 and a garbage return address. The same fact had been recorded once before, buried inside [[feedback-frida-attach-branch-target]] ("retain it on globalThis"), and was not applied when `allocStub` was hoisted into a loop.

**Bit a second time (v14, 2026-08-29):** `const cmSsaa = new CModule(...)` referenced only to build a `NativeFunction` → after the script's top-level scope finished, the CModule was collected and its code page freed; every composite then threw `access violation accessing 0x1e` and the workshop icons vanished. Reproduced in the notepad harness (`scratch/cmod_gc_test.py`: unretained + `gc()` → AV; retained → works).

**How to apply:** push every `Memory.alloc` result AND every `CModule` into a module-level `RETAINED` array (or `globalThis`) at the alloc site itself — inside the helper, never at the caller. Log every stub address and assert they are DISTINCT; keep a copy of each stub's bytes and re-verify them at first exec (`verifyStubPages` in hook_dw_scale_proto.js) so a reuse aborts loudly instead of executing foreign bytes. A synchronous scratch buffer consumed before the function returns (e.g. the HEAPCHK handle array) is the only case that may stay unretained. Related: [[feedback-emulate-frida-stubs]] (emulation cannot catch this — the bytes were right, the page was not), [[project-smac-design-workshop]].

## CModule too (2026-09-13, monument proto v4b-v4d): a `CModule` is FREED the moment its last JS reference dies

QuickJS is refcounted: `let cm = new CModule(...)` inside the `if (requireBase()) { ... }` block is released when the
block's top-level execution ends unless a CLOSURE captures `cm` — the NativeFunctions built from `cm.fn` hold only raw
addresses. Symptom: the load-time self-test (inside the block) passes, then every call from a hook executes freed/reused
pages: "access violation accessing 0x1/0x0", "arithmetic error" from a function with no division, and eventually a hard
crash (garbage ran on the game thread before Frida's call guard caught the fault). Offline it never reproduced because the
test called the functions inside the same block. **Rule:** `globalThis.MON_CM = cm` (or push it into the module-level
retain array) right after construction, same as every Memory.alloc page. Offline check: build in a block, end the block,
`gc()`, then call.
