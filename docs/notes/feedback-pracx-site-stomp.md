---
name: feedback-pracx-site-stomp
description: PRACX rewrites specific exe call sites at STARTUP (pracx.cpp hook tables) — baked site patches at those addresses are silently dead at runtime; check pracx.cpp before baking, and audit gate-correct-but-no-effect defects against it
type: feedback
---

PRACX (prax.dll) patches the loaded exe image at startup from three tables in `refs\pracx\shared\pracx.cpp` (~line 2375): `m_astHooks` (writes its thunk's rel32 at addr..addr+3 — the listed address is the rel32 FIELD, i.e. site+1), `m_astChanges` (arbitrary byte writes), `m_astApi` (4-byte data-pointer swaps). Whatever we bake at those bytes is overwritten every launch — the on-disk patch stays intact, tests stay green, and the runtime silently runs PRACX's code instead.

**Why:** The slice-4 yield-orb adapters (bw4 farm sites 0x40F7DA/0x40F81A/0x40F84C/0x40F8A8) were baked, gate-audited, and trace-verified for inputs — yet never executed in any build, because PRACX owns those four rel32s (gray unworked-resources wrappers). Cost: the orbs stayed native through three build cycles and the dead redirects masqueraded as live coverage.

**How to apply:**
- Before baking ANY site patch, grep the SMACX-column addresses in pracx.cpp's three tables for overlap with the target bytes (audit script pattern: intersect yaml `virtual_addr`+`length` with hook addr+4 / change addr+size / api addr+4). As of 2026-07-21 the full-yaml audit found only the four farm sites — new patches near PRACX's touch points (map draw 0x46xxxx, zoom/scroll 0x515xxx/0x50Exxx, WinProc/BitBlt 0x5D5C70/0x5F018x, movie 0x403BE0, draw_farm 0x40F53F-0x40F548 + the four sprite calls) need the check most.
- When a baked patch's gates are all correct but behavior doesn't change, READ THE LIVE PROCESS BYTES at the site (Frida readByteArray) before theorizing — a 0x6C8Exxxx / non-cave call target means PRACX owns it.
- Work AROUND owned sites, don't fight them: PRACX wrappers forward args verbatim, so rewriting already-pushed args (or globals the callee reads) from a detour on an adjacent PRACX-untouched instruction achieves the same effect (the basewin_farm_orbs pattern).
- PRACX addresses are also NEVER Frida-attach targets ([[feedback-frida-attach-branch-target]]).

Related: [[project-smac-base-screen]] (the yield-orb instance), [[project-smac-pracx-load-mechanism]].
