---
name: project-smac-codecave-section
description: How to get more code-cave space in the SMACX patcher — the menu_strip_thunks cave is full; use the new appended PE section pcave2 / creates_section
type: project
---

The original code cave `menu_strip_thunks` (_SELFMOD tail, VA 0x668200–0x669000) is **FULL** — it hard-ends at VA 0x669000 where `.rdata` begins, so it cannot be extended. When a thunk doesn't fit (e.g. a 212-byte clone with only ~169B free), do **not** do fill-parameter gymnastics — use the second cave.

**`pcave2`** — a brand-new RWX PE section appended to the binary at VA **0xA0C000** (RVA 0x60c000, raw 0x2f1000, 0x1000 bytes, Characteristics 0xE0000020). Reachable by rel32 from `.text` (~0x60b000, well within ±2GB). Declared in `patches.yaml` `code_caves` with `creates_section: true` + `new_section_name` + `virtual_addr` + `length`; symbols reference it like any cave (`{ cave: pcave2, offset: 0xNN }`). It can call back into `menu_strip_thunks` helpers via abs/rel placeholders (cross-section is fine).

**Patcher capability (built 2026-06-05, build 357119e4):** `apply_patches.py` now supports `creates_section`. `plan_new_section()` validates header room (81 free section-header slots; need 1) + section-aligned VA past the image, and the apply phase appends a 40-byte section header @file 0x338, bumps `NumberOfSections` 8→9 and `SizeOfImage`, and appends zero-filled raw data at EOF, then writes cave contents there. The game still loads (PRACX already self-modifies, so RWX is accepted). First user: `thunk_box_thick_hollow` for the d528 option-block frame.

**Why:** cave exhaustion bit twice; a second cave permanently removes the constraint. **How to apply:** for any future thunk too big for `menu_strip_thunks`, put it in `pcave2` (plenty of room: 0x1000, ~212B used). Bump `length` if pcave2 itself fills. See (a private note), [[project-smac-menu-strip-scaling]].
