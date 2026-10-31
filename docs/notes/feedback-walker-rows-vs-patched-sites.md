---
name: feedback-walker-rows-vs-patched-sites
description: A proto's imm rows and a bake's detours over the same bytes conflict at RUNTIME (the walker rewrites the detour's rel32) — check every walker row against every patched site mechanically; plus the minidump recipe for a plain-binary crash
type: feedback
---

The rw_scale_kinds v1a bake crashed opening F2 with EIP inside a zero-filled data cell (0xA27B20) that nothing in the file referenced. The proto scaled the BEST BASES toggle height by patching the imm8 of `add ecx, 0x14` at 0x4A4851 (an imm ROW the walker rewrites at runtime); the bake then DISPLACED that instruction into the gov_split2 seam cave and put `E9 rel32` at 0x4A484F. The row stayed in the table, so at g=40 the walker stored s(0x14)=0x32 over byte 1 of the rel32: `E9 CC C2 58 00` became `E9 CC 32 58 00` = jmp 0xA27B20. Two sat-split rows (0x4A4CA2 / 0x4A4D7E) were the same class.

**Why:** every offline check passed — byte identity vs pristine, instruction boundaries, Unicorn laws — because the conflict only exists after the walker runs over the patched image. A row and a site are two independent ledgers writing the same bytes; nothing compared them.

**How to apply:** when a bake displaces or rewrites an instruction the proto patched by row, DROP the row (the cave carries the law) and name it in an explicit covered-rows dict. Keep the mechanical guard: `assemble_rw.row_site_conflicts` (assembler main fails) + `test_no_walker_row_inside_any_patched_site` (every yaml site, all groups); the only tolerated overlap is the imm32 field of a `mov r32, imm32` rewrite. Crash-dump recipe for the plain binary: `%LOCALAPPDATA%\CrashDumps\terranx_PRACX.exe.<pid>.dmp` exists per crash; `pip install minidump`, then read the exception stream's ThreadContext RVA as an x86 CONTEXT (Edi..Esp at +0x9C, Eip at +0xB8, Esp at +0xC4) and dump the stack from that Esp — the thread list's context is post-fault (ntdll) and useless. A stale return address just below ESP names the function that was running. See [[feedback-vp-window-sized-from-tables]], [[project-smac-report-screens]], [[feedback-bake-port-fidelity]].
