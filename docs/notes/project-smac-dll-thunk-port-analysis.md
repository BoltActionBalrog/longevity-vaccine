---
name: project-smac-dll-thunk-port-analysis
description: DLL thunk-port architecture analysis (DROPPED 2026-06-24) — why migrating asm thunks to C++ was decided against; retained reasoning + candidate spec if ever revisited
type: project
---

Architecture analysis for moving binary-patch thunk logic into `uimod.dll`. Owner DROPPED this
as an action item 2026-06-24 ("doesn't make sense anymore") — the existing corpus is
working/locked/multi-res-verified and no existing thunk ports cleanly (see findings). The DLL
stays a LATENT option for FUTURE new code-volume/last-writer features (per the decision rule),
just not for migrating the current corpus. Reasoning retained here so it isn't re-derived if the
topic ever resurfaces.
See [[project-smac-uimod-architecture]], [[project-smac-uimod-dll]], [[project-smac-pracx-load-mechanism]].

**Why dropped:** porting trivial thunks to C++ buys little (the corpus already works + is
MD5-locked), no existing thunk is a whole-method wrap so the cleaner vtable path doesn't apply,
and re-porting risks regressing finished work. Net negative right now.

**Key findings:**
- A static site→thunk link is `E8 rel32` resolved at APPLY time against a static symbol table
  (`apply_patches.py:126`). A DLL function has no fixed address → a static `E8 rel32` CANNOT
  reach it. So DLL ports must install hooks at RUNTIME (last-writer, after PRACX), computing
  rel32 themselves. You cannot "keep the site static, move just the thunk to the DLL."
- The clean split is BY FEATURE, not by atom: a fix is binary-patch XOR DLL-hook. A DLL hook
  replaces BOTH the site and the thunk (the DLL re-creates the redirect at the same VA at Init,
  as last-writer). Don't bisect one fix across both layers (worst of both).
- NONE of the ~50 existing thunks is a whole-method wrap — they are surgical mid-function or
  single-call-site edits. So a clean C++ VTABLE-SLOT SWAP does not map onto any existing thunk.
  Porting an existing thunk = runtime INLINE DETOUR, not vtable swap. (vtable swap is the right
  tool only for a FUTURE new whole-method behavior.) FlatButton vtable @0x669754,
  content_draw=vtable[0x30]@0x607E50 exists, but our FlatButton thunks edit its middle.
- Leave the existing locked corpus where it is (working, MD5-locked, multi-res verified). Use
  the DLL for NEW last-writer/code-volume work. No big-bang migration.

**Chosen prototype candidate (fully spec'd, ready to build):** `thunk_btntext_nudge`
(pcave2+0x1390). Site `FlatButton_content_draw.faction_label_nudge` @0x608441, 5-byte
call-redirect, orig `call Buffer_wrap_cent_4 (0x5DD920)`. Math `y -= (g-16)*3/16` gated on
`g_faction_active(0xA0D2D0)!=0 && g_popup_scale_num(0x668740)>16`. Ports with NO naked asm:
`__thiscall`→MSVC `__fastcall` with dummy edx, callee-cleanup 0x10 bridges cleanly. A/B without
yaml surgery: DLL loads last and overwrites our OWN static `call thunk` at 0x608441 (cave thunk
goes dead) — friendly stand-in for overriding PRACX. Prove via wrong-value (`y-=40`) jump test.

**If ever revisited:** the plan file has the full file list + verification steps for the
`thunk_btntext_nudge` prototype. But this is DROPPED, not tabled — re-confirm with the owner that
they want to migrate corpus thunks at all before building; the standing decision is to leave the
binary-patch corpus as-is and use the DLL only for NEW features.
