---
name: project-smac-codecave-section
description: How to get more code-cave space in the SMACX patcher — the menu_strip_thunks cave is full; use the new appended PE section pcave2 / creates_section
type: project
---

**2026-11-07: pcave2 grown 0x40000 -> 0x41000 (the MP region 0x40000..0x40FFF: netwin_frame_strokes + commlink_mp_spots).** Every 0x1000 block from 0x31000 up is a WAVE's reserved region (W1A 0x31.., W1B 0x32.., fix 28 0x33.., W2A 0x34.., W2C 0x36.., W2D 0x37.., W3A 0x38.., W3B 0x39000..0x3AFFF, W4C 0x3B.., W5A 0x3C.., W5B/W8T 0x3D.., W6A/W10S 0x3E.., W6C/W7R/W9C 0x3F..): cave_map `--fit` reports their unused TAILS as FREE, but they are not yours -- test_rail_sym_asm_parity asserts nothing else lives in W3B's block. New work grows the section (edit `length:` + a history note). Two parity tests map the WHOLE cave with a fixed length (test_stripes_dlphase_asm_parity, test_stripes_rwsb_asm_parity) -- raise them with it.

**2026-11-08: pcave2 grown 0x41000 -> 0x44000 (MP polish: the COMMLINK column map, MP header zone law and title rows; ships in 1.0.0).**

The original code cave `menu_strip_thunks` (_SELFMOD tail, VA 0x668200–0x669000) is **FULL** — it hard-ends at VA 0x669000 where `.rdata` begins, so it cannot be extended. When a thunk doesn't fit (e.g. a 212-byte clone with only ~169B free), do **not** do fill-parameter gymnastics — use the second cave.

**`pcave2`** — a brand-new RWX PE section appended to the binary at VA **0xA0C000** (RVA 0x60c000, raw 0x2f1000, 0x1000 bytes, Characteristics 0xE0000020). Reachable by rel32 from `.text` (~0x60b000, well within ±2GB). Declared in `patches.yaml` `code_caves` with `creates_section: true` + `new_section_name` + `virtual_addr` + `length`; symbols reference it like any cave (`{ cave: pcave2, offset: 0xNN }`). It can call back into `menu_strip_thunks` helpers via abs/rel placeholders (cross-section is fine).

**Patcher capability (built 2026-06-05, build 357119e4):** `apply_patches.py` now supports `creates_section`. `plan_new_section()` validates header room (81 free section-header slots; need 1) + section-aligned VA past the image, and the apply phase appends a 40-byte section header @file 0x338, bumps `NumberOfSections` 8→9 and `SizeOfImage`, and appends zero-filled raw data at EOF, then writes cave contents there. The game still loads (PRACX already self-modifies, so RWX is accepted). First user: `thunk_box_thick_hollow` for the d528 option-block frame.

**Why:** cave exhaustion bit twice; a second cave permanently removes the constraint. **How to apply:** for any future thunk too big for `menu_strip_thunks`, put it in `pcave2` (plenty of room: 0x1000, ~212B used). Bump `length` if pcave2 itself fills. See (a private note), [[project-smac-menu-strip-scaling]].
