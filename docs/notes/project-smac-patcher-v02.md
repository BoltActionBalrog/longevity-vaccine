---
name: project-smac-patcher-v02
description: patches.yaml v0.2 schema additions: symbols, code_caves (with optional VirtualSize extension), groups; patcher resolves {rel32:NAME} placeholders at apply-time
type: project
---

The SMAC UI scaling patcher schema (`D:\SmacxUi\work\patches\patches.yaml`) was extended on 2026-05-28 with three top-level concepts to support multi-site atomic patches that include code-cave thunks.

**Top-level YAML keys (in addition to the original `sites`):**
- **`symbols`**: name → address mapping. Each entry has either `va: <absolute>` (engine functions, globals) or `cave: <id>, offset: <int>` (cave-resident thunks). Resolved at apply-time.
- **`code_caves`**: RWX regions for new thunk bytes. Each cave has `section`, `virtual_addr`, `length`, `expected_padding` (list of bytes that count as "unused"; default `[0x00]`), `extends_section_virtual_size` (bool — bumps the host section's VirtualSize via PE header rewrite to make the region executable), and an ordered `contents` list of named sub-blocks.
- **`groups`**: atomic patch sets. Each group has `members` (site IDs) and `code_caves` (cave IDs). All-or-none semantics: if any member or referenced cave fails verification, the entire group is skipped.

**Byte-template syntax (for `original_bytes`, `new_bytes`, cave `contents[*].bytes`):** whitespace-separated tokens. Each is either a 2-char hex pair (1 literal byte) or `{rel32:SYMBOL_NAME}` (4-byte rel32 displacement; the patcher checks the byte before the placeholder is `0xE8` for CALL, then computes `target_va - (rel32_va + 4)` and emits little-endian signed bytes).

**Per-site `group:` field**: an optional string. If set, the site applies only when its group is eligible.

**`{abs32:SYMBOL}` placeholder (added 2026-05-29):** 4-byte ABSOLUTE VA of the symbol (little-endian, unsigned) — for absolute memory operands like `lock cmpxchg [var],ecx` (`F0 0F B1 0D {abs32:var}`). No E8-precedence rule (unlike rel32). Implemented in `ByteTemplate` alongside rel32.

**`skippable` flag (added 2026-05-29) — non-critical patches for mod coexistence:** set `skippable: true` on a site OR a group. A skippable patch that FAILS verification (e.g. another mod already modified that code) is reported with a calm `[skip]` line and a `Note:` summary, and does NOT abort the run — the rest of the patch set still applies. A CRITICAL (non-skippable) failure still prints `[FAIL]` and aborts with no changes (unchanged dev-safety behavior). The patcher only counts non-skippable failures toward the abort. Used by the `win11_24h2_filelock_fix` group so users who already run Thinker/another static patcher on the CRT file-lock sites get a quiet skip instead of a contention warning, while a contention on a UI site still warns+aborts. See [[project-smac-win11-24h2-fix]].

**Why `extends_section_virtual_size` matters:** PRACX's `_SELFMOD` section has VirtualSize=0x415D but RawSize=0x5000. Bytes past VirtualSize are file-only and NOT loaded by the OS. The largest contiguous padding run inside the loaded region is 15 bytes — far too small for any meaningful thunk. So caves placed past VirtualSize must bump it; the patcher rewrites the section header's Misc_VirtualSize field (file offset = section_header_offset + 8, 4 bytes LE) during apply. For the menu_strip_thunks cave at 0x668200 (256 bytes), VirtualSize gets bumped from 0x415D to 0x4300. The 45 bytes between 0x66815D and 0x66818A are PRACX-authored but past PRACX's intended VirtualSize — they're inert (no code path targets them), so bumping VirtualSize loads them harmlessly.

**Why:** The previous single-site-flat schema couldn't express the menu-strip scaling patch, which requires (a) coordinated literal patches at 4 call sites in 2 functions, (b) ~175 bytes of new thunk code in RWX memory, and (c) the section-header tweak to make that memory loadable. The new schema makes each of these first-class.

**How to apply:** When designing future patches that involve more than a one-site literal swap, model them as a group with one or more sites and optional cave dependencies. The patcher will verify all members atomically and skip the group cleanly if anything fails. Existing single-site flat entries continue to work unchanged. The schema additions are purely additive.

**Test status (2026-05-28):** Patch successfully applied; new MD5 `6f30b90b0a59709fe1d12db78dac1456`. Static verification of all 5 sites + cave passes. All relative-call displacements verified by hand-computing target VAs from the emitted bytes (scale_uniform = 0x668200, thunk_scale_rect_width = 0x668260, thunk_strip_blit_stretched = 0x668280, Buffer_copy_3 = 0x5D9610). Runtime visual verification pending — needs an in-game launch through PRACX at the maintainer's render resolution.

Related: [[project-smac-ui-scaling]], [[project-smac-openitem-strip]], [[feedback-smac-aspect-ratio]]
