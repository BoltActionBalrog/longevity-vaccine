---
name: project-smac-dl-esi-clobber-crash
description: Crash after a secret project (AV @0x4742BB in MonumentWin_draw near painter) = OUR Datalinks walker entries returned esi = the imm-table VA since the 2026-08-30 dl bake; fixed exe 050459e5 2026-09-20 (NOT committed, awaiting user verify); saves may hold the poisoned Monument record
type: project
---

User 2026-09-20 (1920x1080 session, exe 7e9e2768): secret project completes -> movie -> Datalinks opens -> Ctrl-Q -> crash. Evidence kept in `work/tests/crash_20260920_secretproject_ctrlq/` (WER dump, event log, uimod.log, the crashed exe).

**Root cause (ours, latent 3 weeks):** `t_dl_immfix_main` / `t_dl_immfix_tech` were `mov esi, TABLE; jmp t_dl_immfix`; the walker's own `push esi ... pop esi` therefore saved and restored the TABLE pointer, so every Datalinks open (t_dl_build_enter / t_dl_exec_enter / t_dl_exec_leave save only ecx/edx) returned `esi = 0xA34CE0` (g_dl_immtab_tech) to the engine caller. Almost no caller keeps esi live across Datalinks; the secret-project-complete flow does, and stores it as the Monument record param (dump: `Monuments[5]` (0x94CA08, stride 0x4F4) record 5 (0x38 each) +8 = 0xA34CE0). The plaque painter then indexes `Facility[70 + param]` (0x9A5888 + param*0x30) -> AV. Ctrl-Q merely closed Datalinks.

**Fix:** entries = `push esi; mov esi,TABLE; call t_dl_immfix; pop esi; ret` (13B in the same 16B slots). Guard: `test_dl_asm_parity.test_immfix_walker` asserts esi/ebx/edi/ebp survive (the old bytes fail with esi=10702048).

**How to apply:** a garbage value that EQUALS one of our cave VAs in engine data = a register we leaked; search the assemblers for `mov <callee-saved>, imm` before a tail-jump into a helper that does its own save. Every CALL-helper entry must be tested for callee-saved register survival, not just for its effect ([[feedback-thunk-call-vs-detour]], [[feedback-cut-thunk-flag-liveness]]). Saves written after such an event can carry the poisoned Monument record (F9 plaque of that milestone would AV) — a load-time sanitiser is an open idea.
