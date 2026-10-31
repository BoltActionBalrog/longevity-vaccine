---
name: feedback-vp-window-sized-from-tables
description: A table-driven imm walker's VirtualProtect window is part of the table's contract — derive it from the rows and assert coverage; a constant window crashed the rw_scale_kinds v1 bake on game load
type: feedback
---

The imm-row walker `t_dl_immfix` stores into .text through every row site, so every row must lie inside a page range that was VirtualProtect'd first. Its own bootstrap covers 0x429000..0x49C000; report-only rows rely on `t_rw_init_leave` opening a second window at 0x49C000. That second window was a CONSTANT (0xD000, sized for the F2 rows) — the rw_scale_kinds bake appended 400 rows reaching 0x4AC7A4, every offline test passed (Unicorn maps the whole image writable), and the shipped exe crashed on game LOAD at the walker's first store past 0x4A9000 (fault 0xA2E163 = `mov byte ptr [eax], cl`).

**Why:** the emulator harness cannot see page protections, so the only offline defence is arithmetic: the window must be a FUNCTION of the tables, with an assertion that every row (site .. site+width) lies in the union of the walker's windows. A written note ("rows past 0x49C000 need their own VP") existed and was not enough — the check has to be mechanical.

**How to apply:** `assemble_rw.vp_len()` sizes the window page-rounded past the last stored byte of both tables and asserts coverage; `test_report_init_vp_window_covers_every_walked_row` (test_rw_kinds_parity.py) emulates the bootstrap through IAT stubs and checks the pushed (page, len, PAGE_EXECUTE_READWRITE, vpold). Any new walker/table pair (DL, tech, kinds, future groups) needs the same: never a literal length. Diagnosis recipe for a plain-binary crash: `Get-WinEvent` Application log -> fault offset + 0x400000 -> `cave_map.py --at <pcave2 offset>` -> `_disasm_live.py`. See [[project-smac-report-screens]], [[feedback-cave-ledger-lengths]], [[feedback-emulate-frida-stubs]].
