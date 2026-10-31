---
name: project-smac-thinker-compat
description: Thinker compatibility pass — Thinker never modifies terranx.exe on disk (runtime in-memory patcher), so the "thinker" target has the VANILLA hash and collisions are FATAL (exit_fail), not skipped; release 5.5 staged at refs\thinker-release\v5.5, source clone at tag v5.5
type: project
---

**State 2026-09-26:** Thinker 5.5 release (2026-08-16) downloaded by the maintainer and extracted to
`refs\thinker-release\v5.5\` (gitignored): `thinker.dll` MD5 5af21362, `thinker.exe` MD5 eafd7be7,
`thinker.ini`, `alphax.txt`, `smac_mod\{alphax,conceptsx,helpx,tutor}.txt`, `basenames\`. Source clone
`refs\thinker` moved from v5.4 to **tag v5.5** (headers grew ~1,400 lines = new symbols for terranx.h;
re-run apply_thinker_names.py). Nothing in-game tested yet. Sweep checklist: the maintainer's work log
"THINKER COMPATIBILITY SWEEP".

**How Thinker installs (read from src/launch.cpp + Technical.md, not assumed):** `thinker.exe`
CreateProcess("terranx.exe", CREATE_SUSPENDED) → VirtualAllocEx/WriteProcessMemory("thinker.dll") →
CreateRemoteThread(LoadLibraryA) → waits for DllMain → ResumeThread. The DLL patches the image in
memory (Scient's patchdata.h 3,127 triples FIRST, then ~867 write_call/jump/bytes/offset). The exe on
disk is untouched. Exe name is hardcoded `terranx.exe`; PRACX+Thinker means a PRACX exe named that.
Thinker detects PRACX by `strcmp((char*)0x668165,"prax")` → reduced_mode (no video mode / smooth scroll).

**Consequences (the plan pivot):**
- `targets.thinker` / `pracx_thinker` "pending: measurement" stubs are mis-modelled: there is no
  Thinker exe hash to measure — base = cc659f (vanilla) or 2d0b1438 (PRACX). Detection must be by
  folder contents (thinker.dll/thinker.exe present) or by uimod.dll at runtime, never by hash.
- Our on-disk patcher sees pristine bytes → applies EVERY group. Thinker then verifies against OUR
  bytes: write_bytes = exact old; write_call = E8/FF15 opcode; write_offset = 0x68; write_jump = 16-aligned
  or E9; patchdata = old||new. Any overlap → `exit_fail` MessageBox, game never starts. So the 5 colliding
  groups (win11_24h2_filelock_fix, menu_strip_scaling, credits_interlude_scaling, basewin_interior_slice2,
  dw_scale) must be EXCLUDED from a Thinker build, not left to skip.
- Load order: thinker.dll is fully initialised before our CRT-initterm loader stub → `GetModuleHandle
  ("thinker.dll")` works at uimod Init (the maintainer's work log "not loaded yet" note is wrong).
- Scient's v2.0 BINARY half is bundled in Thinker; its TEXT half (helpx.txt) is optional — patch_helptext.py
  must not assume Scient text under Thinker.
- 5.4→5.5 patch surface: patchdata identical; write calls 862→867 (new function-entry jumps: council notify,
  sat_attack, spying, break_treaty, game/map init+shutdown, scenario_setup, tech_*, save_map daemon) — none
  in patches.yaml. 5.5 also adds a main-menu "Change Options" button and a combat fog-of-war render crash
  fix: both touch screens we own → check in the ownership pass.

**Next steps:** (1) re-create the lost `thinker_overlap.py` static check under work\scripts + a test;
(2) remodel targets as group-exclusion overlays selected by folder check; split atomic groups (dw_scale
loses 55 sites over one byte); (3) per-screen ownership (setup planet preview, interlude, credits);
(4) scratch game copy + thinker.exe launch; Ctrl+F4 shows version; uimod.log detection line; sweep items.
Never test on the live install ([[feedback-never-test-installer-on-live-game]]).
Related: [[project-smac-win11-24h2-fix]], [[project-smac-punishment-sphere]], [[project-smac-riot-defection-fix]],
[[project-smac-ai-cloak-visibility]], [[project-smac-patcher-v02]].

**State 2026-10-28 (compat work started):** scope = PRACX + Thinker ONLY (user). Workspace `D:\SmacxThinker\`
(outside git): `game\` = live GOG copy minus every Longevity file, clean PRACX base as `terranx.exe` (2d0b1438) +
clean prax.dll + Thinker 5.5 extracted; `baseline\` = pristine copy; `env.bat` exports SMACX_GAME_DIR /
SMACX_EXE_NAME. README.md there lists the removals. Thinker v5.5 is still the newest release; upstream master has 9
unreleased commits (to 2026-10-21) -- clone stays on tag v5.5. `thinker_overlap.py` is confirmed LOST (not in git,
the scratch quarantine, or anywhere else) -> rebuild under work\scripts with a test; the 2026-09-21
collision numbers are stale. Conflict rule: [[feedback-thinker-conflicts-user-decides]].

**Measured 2026-10-28 (rebuilt `work\scripts\thinker_overlap.py` + test, exe 5a3e20b0, PRACX mode):** both caves clean;
9 collisions in 4 groups, ALL open user decisions: menu_strip_scaling 3/25 + credits_interlude_scaling 3/9 (Thinker's
`render_high_detail`, default on, scales those screens itself; 3 FATAL exit_fail + 3 CLOBBER), basewin_interior_slice2
2/112 (unconditional set_font / eco_damage call redirects, CLOBBER), dw_scale 1/55 (Scient triple 0x618A94 inside our
Caviar imm32, FATAL for the atomic group). `win11_24h2_filelock_fix` does NOT collide (the 2026-09-21 note was wrong).
DLL side (heuristic `--dll` pass): aivis, hudmovesfix, pssphere, update auto_save, movie prefs_get_2 sites are Thinker
jump/call targets -> those DLL features go inert under Thinker unless chained; also user decisions. Parser facts: Thinker
forces smooth_scrolling=0 under PRACX; its unit-array operand table only verifies AFTER the Scient pass (17 operands) --
emulate in Thinker's order. Report copy: `work\briefs\thinker_overlap_2026-10-28.md` (gitignored).

**Smoke harness REMOVED 2026-10-30 (user: no value shown for a long time; smoke_launch.py / smoke.bat / smoke-last.json
deleted, run_frida_thinker.py carries its own process helpers; NO automatic launch after a deploy any more -- the
no-launch rule has no exception left).** Was 2026-10-28 (user: start-only, never a game driver): `work\scripts\smoke_launch.py` +
`D:\SmacxThinker\smoke.bat` -- launches, finds the game by parent PID, reads/answers MessageBoxes (OK > Cancel > No),
window up 15 s = PASS, closes (main menu ignores WM_CLOSE -> TerminateProcess). Baseline PASS-WITH-DIALOGS: PRACX +
Thinker 5.5 starts in the workspace; the dialog is Thinker's own first-run VLC prompt. Window class `JackalClass`.
**Installed-build run 2026-10-28:** install.py into the workspace (exe 5a3e20b0, 127/134 groups) -> smoke FAIL with
Thinker's box "Error while patching address 00618A94" = the Scient triple in Caviar.E_imm_618a92, exactly the first
guard the ordered emulation predicts; exit code 1 before uimod.dll loads. Diagnosis chain CONFIRMED. Movie playback:
Thinker's mod_amovie_project calls amovie_project_2 (our player) when MoviePlayerPath is empty, launches VLC when an
external player is configured, skips movies on "No" -- an ownership decision, not a byte conflict. Installer wording
("start terranx.exe", "terranx.exe starts the unmodified game") is wrong in a Thinker folder -> open item.

**USER DECISIONS 2026-10-28 (canonical text: the maintainer's work log THINKER block):** exe collisions (1) dw_scale, (2) menu strip,
(3) credits/interlude = "apply after Thinker" (site excluded from the on-disk patch under Thinker, uimod.dll writes our
bytes at runtime after thinker.dll's verify pass, verified + logged; for (3) Thinker keeps the two background sites so its
Ctrl+F4 version label stays); (4) base screen = CHAIN (our thunk scales args, then calls Thinker's hook). DLL side: (5) aivis
= RE-IMPLEMENT against Thinker's planner (thinker.dll 5.5 pinned); (6) hudmovesfix = relocation-aware byte check;
(7) pssphere = test in the workspace, decide from the result. (8) movie ownership = A2 SILENT: installer blanks
`[Alpha Centauri] MoviePlayerPath` on every run (Thinker present or not; game/PRACX never read it), no notice; the maintainer's
stated assumption "uninstall restores vanilla + Thinker behaviour" must be made true (save prev value in [Longevity],
restore on --uninstall if still blank) -- today --uninstall never touches [Alpha Centauri].

**IMPLEMENTED 2026-10-28 (decisions 1-4, 6, 8; nothing committed yet; canonical detail: the maintainer's work log THINKER
"IMPLEMENTED"):** yaml schema 0.4 -- `pracx_thinker` is a folder-detected OVERLAY (`requires_files: [thinker.dll]`,
PRACX's base hash, `exe: terranx.exe`, `launcher: thinker.exe`, `exclude_sites` = the 4 FATAL sites, lock 00d74f0f);
`thinker` target deleted. `resolve_target(present_files=)` everywhere (installer, preflight, CLI). uimod.dll
`thinkercompat.cpp` + GENERATED `thinker_sites.h` (`gen_thinker_sites.py`; test fails on drift) applies the excluded
sites after Thinker (also without Thinker), restores 0x4AE710, chains the two bw2 thunks into Thinker's functions via
trampolines copied from the baked cave; hudmovesfix follows the relocated VEH[]. Installer: Thinker wording, launcher
shortcut, movie key blank every run / deleted on uninstall. Workspace smoke PASS (exe 00d74f0f, DLL 53b1e87a): 5
sites applied, 2 chains, pssphere chain fired, hudmovesfix live. OPEN: user's in-game pass under Thinker (then the
CHANGELOG line), decision 7's display check, decision 5 (aivis vs Thinker) NOT STARTED -- scoped: Thinker's planner
reads `Vehs[]` directly (move.cpp 46 / veh.cpp 152 reads vs a handful of veh_at calls), so it needs detours inside
thinker.dll, its own multi-session arc. DW crash fact:
Scient's Caretaker/Usurper Workshop fix is the single z-plane malloc byte; our thunk_dw_resetguard clamp makes the overrun
impossible in our build (alien ART still unverified -> in-game item).

**Decision 5 pivot 2026-10-28 (user: "measure option 2 first"):** before patching Thinker, measure whether its planner
acts on unseen cloaked/DPH stacks at all (source already checks is_visible/visibility at move.cpp:315/1481/2228/2913,
path.cpp:215). Built `work\scripts\hook_thinker_aivis.js` (observer; Thinker fn entries read LIVE from the E8/E9
operands Thinker writes: 0x528289 mod_enemy_turn, 0x579362 mod_enemy_move, 0x506ADE mod_battle_fight_2, 0x5947C0 E9 ->
Thinker's order_veh; Vehs[] via the 0x5C1A39 operand; HiddenStack v3 ported to JS) + `run_frida_thinker.py` (launcher-
aware: start thinker.exe, attach once thinker.dll + uimod.dll are loaded -- `frida -f` cannot spawn through a launcher)
+ `D:\SmacxThinker\trace.bat` + desktop "SMACX Thinker AI Trace". Staged, NOT committed. Options on the table if a gap
shows: upstream PR to induktio (MIT), engine-side visibility data Thinker honours, source fork, binary detours (worst).
thinker.dll 5.5 exports only DllMain/ThinkerModule (no symbols); MinGW .eh_fram present. Awaiting the maintainer's run + log.

**2026-10-28 (user's 4K pass under Thinker, workspace):** planet screens / setup preview RIGHT; Thinker's
render_base_info eco-damage line draws scaled through our bw2 chain (RIGHT; its satellite/staple/riot lines unseen,
save has none); DW wheel no double scroll; HUD Moves fix live. DECISION 7 RESULT = FAIL -> fixed as OPTION C (user):
Thinker write_jumps base_compute 0x4EC3B0 to its own C++ base_compute, which calls mod_base_energy DIRECTLY, so
the 0x4EB560 chain never ran (log 'no current would-be totals'). pssphere.cpp now also re-points the 0x4EC3B0 E9 to
WrapBaseCompute (Thinker's base_compute, then PsychCore(mod_base_energy, runReal=false) when it recomputed / cache
stale; g_cacheGen skips a double run). No byte of thinker.dll written; would-be totals = Thinker's psych without the
sphere. DLL c31e4c96 deployed to the WORKSPACE only (uimod.dll.53b1e87a.bak beside it); user check pending.
OPEN: nerve-staple button (btn16, thunk_staple_coverage) AND every scenario-editor palette icon draw a ~6x zoomed
crop of their top-left under Thinker (PRACX refs 115624 / 222247 right) = KSB enlarge applied twice (2.5x2.5) or a
Buffer_copy_3 failure leaving scratch; static sweep: no Thinker write in Buffer/Sprite code or near the thunks;
bisect render_high_detail=0 added to the workspace thinker.ini (commented), result pending. Thinker's
window_scale_load_pcx only reaches Credits + demosplash (GraphicWin_load_pcx's 2 callers).
Trace tooling: hook_thinker_aivis.js + run_frida_thinker.py + D:\SmacxThinker\trace.bat + desktop Thinker\ folder
shortcut; aivis measurement (decision 5, option 2) NOT yet run by the maintainer.

**2026-10-28:** option C VERIFIED by the maintainer (sphere row, PSYCH, F4 right). Bisect POSITIVE: render_high_detail=0
cures BOTH the staple button and the editor palette crops -> cause inside Thinker's render block; only its MapWin
zoom-out detailed-tiles patch (16 cmp sites 0x4636AE..0x466444) is live on both screens -> hypothesis: shrink ratios
through our detoured stretcher / KSB scratch; probe work\scripts\hook_thinker_ksb.js (Buffer_copy_3 0x5D9610 thiscall
this=src, ksb_v2 pcave2+0xEDA0, staple pcave2+0xE000, bandstripe pcave2+0xC800); user zoom test pending. aivis under
Thinker read the STOCK Vehs (dead copy) -> "!" never drew; fixed with g_vehs = ModernCtlVehs() (DLL 17c28310, workspace).
NEW REQUEST: nerve-staple badge + would-be row (design questions in the maintainer's work log). Thinker's satellite lines not seen on
Survival Base (open). User rule 2026-10-28: INDEPENDENT REVIEW every fix (5 static passes launched round 1).
**Audit round 1 (2026-10-28, 4 of 5 in):** FIXED in DLL fa998024 (workspace): pssphere would-be pass now SNAPSHOTS the
whole BASE record (0x134) and restores it (Thinker's mod_base_energy accumulates energy_intake_2 -- a 3rd pass cannot
restore it); superdrone NOP bytes restored only inside the draw_pop would-be window; sanity check = engine invariant;
aivis 2048 literals gone; generator refuses intra-core rel32; FF15 `90 E8` windows accepted. OPEN user decisions:
A1 hudmovesfix site A dead under Thinker (Thinker replaces action_go_to); A3 cargo/pod groups live while the parent
filter is inert; B1/B2 installer overlay-by-exe-name + re-patch on target flip (clear fixes, queued), B3 relaunch
offer, B4 PRACX res check for pracx_thinker, B5 uninstall deletes Thinker's own blank, B6 uninstall trusts any .bak;
C4 Thinker's pop-size text shows real zeros under the badged row; D1 overlay exe not self-sufficient without the DLL
(Caviar); D2 Thinker-added-later exit_fail wording.
**Installer audit fixes DONE 2026-10-28 (uncommitted, suites green):** overlay resolved by exe NAME too (Thinker only
starts terranx.exe; a PRACX exe under another name beside thinker.dll gets plain PRACX + a printed note); re-patch from
.bak when the live build is not the folder's configuration (Thinker added/removed); preflight accepts a same-base sibling
build; relaunch via mod_exe (thinker.exe); resolution check for every prax.dll configuration; uninstall restores only
shipping-target bases. USER DECISIONS: movie-key override is NEVER unwound (B5 closed); boot guard for a failed uimod.dll
load = message + exit + "reinstall" (approved in principle, patcher work pending); HUD Moves under Thinker: retest the
one-step crawl, then chain Thinker's action_go_to at the engine entry (same pattern as base_compute).
**2026-10-29:** BOOT GUARD DONE -- thunk_uimod_preload v2 at pcave2 0x35340 (code) +
g_boot_strings 0x35440 (data) + g_boot_msg 0x35800 (BSS); LoadLibraryA(uimod) failure -> MessageBox (DLL name, Windows
error, reinstall) -> ExitProcess(1); verified in the real game (dialog with error 126, then exit). NEW LOCKS: pracx
677a55d5, pracx_thinker c4c0240a (exe hashes changed; thinker_sites.h regenerated). HUD Moves under Thinker: Thinker's
action_go_to is vanilla logic (no repaint) -> chained at the engine entry's E9 (WrapActionGoTo), DLL a68129fb in the
workspace (previous builds kept as uimod.dll.<md5>.bak). CHANGELOG line added. Installer fixes B1-B4, B6 done with
tests. Everything UNCOMMITTED. Open for the maintainer: cloak "!" retest, HUD Moves retest (one coastal step), zoom test +
hook_thinker_ksb.js probe (render_high_detail=0 still set in the workspace thinker.ini), staple badge glyph, which
"resource rectangles", Thinker's satellite lines / pop-size text placement, scenario-rules popup placement, aivis trace.
**Audit round 2 DONE (2026-10-29):** installer: replaced exe kept beside as <exe>.replaced-<md5>, launcher
candidate wins the receipt, rename note gated (_thinker_needs_renaming), play-note wording, update uses the current id
(185 installer tests green). DLL: WrapActionGoTo repaints for any cleared order (not just MOVE_TO); thunk address pins
in test_uimod_preload_thunk. Final workspace: exe c4c0240a, uimod.dll 11e8a860 (smoke PASS). Known edge G1 (Thinker
base_psych=0 + stapled sphere base shows leftover superdrones) deferred to the staple-badge feature. ALL UNCOMMITTED
(26 paths). Morning checklist at the top of the maintainer's work log's Thinker block.
**DECISION 5 MEASURED 2026-10-29 (AI trace v2, war run, frida_thinker_aivis_20261029.log):** Thinker 5.5's planner
DOES attack cloaked/DPH units it has never seen -- 4 BLIND attacks (fac 4 on the unseen sub veh 70 at (4,46) x3, unseen
veh 44 at (8,46)), all from thinker.dll+0xad524 (one combat-move site), 0 SPOTTED, 14 go-tos next to / 18 two tiles
from unseen stacks, 0 engine reads on unseen stacks (direct Vehs[] reads). Probe lesson: Thinker's internal calls to
mod_enemy_move are INLINED (only the exe's call site reaches the symbol) -> read the go-to at Thinker's order_veh entry.
Options for the maintainer: upstream PR (induktio, MIT), engine-side data Thinker honours, fork, binary detours.
Closed: "resource rectangles" (streaming artefact), scenario-rules popup placement (Thinker's own menu). SUPPORT tab
under Thinker = Thinker's render_high_detail BaseWin_draw_support replacing draw_farm's two calls to the engine's
0x408EB0 -> user: neutralise; thinkercompat.cpp kUndo[] restores the engine callee at runtime (same pattern available
for any Thinker write_call we decide to undo).
**DECISION 5 = OPTION 2 (user 2026-10-29): pinned detours in thinker.dll 5.5; upstream = THINKER FORK backlog (new
the maintainer's work log section).** Symbol map w/o symbols: work\scripts\thinker_symbols.py (patch_setup's (site,func) immediates
joined with patch.cpp names: 142 functions; trace-confirmed). Blind attacks = combat_move's artillery branch (reads
Vehs[] directly, then mod_battle_fight +0xAD450); go-tos toward unseen stacks = non_ally_in_tile / stack_search /
move_upkeep enemy maps. Helpers inline within move.cpp -> per-site detours inside combat_move / move_upkeep, located by
call graph from mod_enemy_turn (+0xAEEB0) + source fingerprints. Next: locate those functions, enumerate the reads,
build thinkeraivis.cpp (MD5-pinned 5af21362).
**DECISION 5 IMPLEMENTED 2026-10-29 (uimod.dll 54fa7d52 in the workspace after the independent audit -- no blocker;
exact-entry pins for 0x5947C0/0x579362, action_destroy residual, PARTIAL log -- smoke PASS, awaiting the maintainer's trace +
in-game verify):** `src\uimod\src\thinkeraivis.cpp` -- pinned to thinker.dll 5.5 by PE TimeDateStamp 0x6A821052 +
SizeOfImage 0x19F000, every site byte-checked before any write. Surface (all Vehs-loop diplomacy calls classified with
work\scripts\thinker_locate.py): non_ally_in_tile +0x561F0 (10 E8 sites), stack_search +0x54AA0 (3), allow_combat
+0x55A90 (1) -> cdecl wrappers ("hidden from f" = nothing there / attack allowed); at_war +0x23210 inside
combat_move's artillery loop (+0x60ED9, v in ebx) and move_upkeep's census (+0x66FAA, veh in esi) -> naked stubs
forwarding the register ("not at war" for a hidden unit); Thinker's `enemy_move` function pointer (.data +0xE5404,
== 0x56B5B0) -> aivis's WrapEnemyMove (engine fallback filtered); Thinker's order_veh +0x99790 (prologue 55 B8 3C 54
00 00, 6 relocatable bytes) -> the bump (AiVisBump). aivis.cpp's core group is Thinker-aware (0x579362 = Thinker's
E8, 0x5947C0 = its E9 accepted; only 0x512842 re-pointed) so paths / diplomacy / net groups now install under Thinker
too. Residuals left as Thinker has them: defender_count/garrison_count, allow_airdrop, mod_zoc_sea's SP rule (leaks to
humans too -- user decision), strategic tallies. Gate = AI factions only -- USER DECIDED 2026-10-29 "leave it AI-only"
(manage_player_units humans unfiltered; closed). USER VERIFIED 2026-10-29 on 54fa7d52: bump ("!" mark, no attack),
GETOUT twin replies back under Thinker, checkbox off restores Thinker's hunting. AI TRACE RE-RUN 2026-10-30 (war,
91 AI turns): ATTACK blind 0 (was 4), STEP into unseen 10 = 10 bumps (spot + cancel), SPOTTED 10, engine reads 0.
DECISION 5 CLOSED; CHANGELOG cloaking line extended to Thinker. Still uncommitted with the rest of the Thinker pass.
**2026-10-30 later (uncommitted, workspace DLL c82959d0):** defender_count = keep (user); PILLAGE bombardment fixed
(WrapPillageFight on the loop's mod_battle_fight +0xA13C4; audit clean; a skipped shot also skips the pillage, as
Thinker's own fight path does); AIRDROP DIVERSION designed (entry detour on action_airdrop 0x4CC360 / chain under
Thinker; first free DirDX-order neighbour; spot_stack + popp("uimod_airdrop","DROPDIVERTED") ; DROPUNIT when no free
tile or already revealed) -- IMPLEMENTED (DLL d353fd53, awaiting the maintainer's checks). LESSONS from its audit:
action_airdrop's flags = bit0 interactive (popups), bit1 EXECUTE (without it the call is a check that returns 1 and
moves nothing; MP checks with 1 locally then executes the broadcast with 2 on every peer; SP passes 3) -> any side
effect (reveal) only on flags&2, probe candidates silently with flags&~3; the engine refuses range -> sea -> units,
so a diversion must only happen when the TARGET would have passed the pre-unit refusals (land target within the
engine's drop_range 0x500320) or dropping on out-of-range squares becomes a cloak detector; the diverted square is
never refused for range (Rules->max_airdrop_rng 0x949740 raised by one around the candidate calls, user rule) and a
candidate refused for any other reason is skipped for the next (silent probe); Thinker's planner calls its OWN action_airdrop (+0x96670) directly -> detour Thinker's entry, not the
engine's E9. Thinker's allow_airdrop has_pact +0x55D4C (index in ebx) is stubbed so its AI attempts and is diverted.
**2026-10-30: the Thinker in-game pass is COMPLETE** (last item: Thinker's own options-menu checkbox popups "look fine").
Interlude Esc = base-game bug fixed (interludekey.cpp, verified). Open only: THINKER FORK backlog (upstream PR), MP
under Thinker (networking section, last), three documented residuals in thinkeraivis.cpp. Committing 2026-10-30.
**2026-10-30 user verdicts:** SUPPORT tab fine; the support-view undo also CURED the staple-button/editor-palette double
zoom (icons-at-zoom CLOSED); Alt+Tab exit no longer reproducible (CLOSED); D2 (Thinker added after our install) =
LEAVE. ZOC: engine zoc_any/zoc_veh have no visibility test, zoc_sea = MultiplayerActive + VFLAG_INVISIBLE, identical to
Thinker's ports -> cloaked units DO exert ZOC in vanilla; nothing to fix. G1 already covered (PsychCore clears the
staple too). OPEN: interlude first-Esc glitch under Thinker (is it PRACX too? user to check); pop-size text C4 and the
version-label decisions. **THINKER TEXT module** `src\uimod\src\thinkertext.cpp` (DLL a1c4ef46 in the workspace after its audit,
USER-VERIFIED at 4K + 1920x1080 2026-10-30 (Thinker's version label is drawn only while GameHalted = credits from the
MAIN MENU; in-game credits never had it); version label KEPT on a scaled margin x=floor(20g/16),
y=H-floor(32g/16) (user); 'S' gate = dest == BaseWin canvas 0x6A7A6C && width [0x6A7AEC] > 758, the family's own observable): Thinker reaches Buffer_write_l_3 / Buffer_write_right_l_5 through .data function pointers (+0xE456C /
+0xE4550) -> swapped for __fastcall-shaped thiscall wrappers that re-anchor x,y = popup_scale_floor(v, g) for the 7
base-screen sites (satellite N/M/E, stockpile, Pop/boom/staple; native coords measured by probe), pass the eco-damage
line through (already scaled by our chain) and handle the "Thinker Mod v5.5 / date" label at +0x3E59A per kVersionLabel
('K' FINAL, user 2026-10-30: keep it on the scaled margin). Pinned 5.5 + FF15 site checks; test test_thinker_text_sites.py
(completeness over every call through either pointer). LESSON: for a DLL that calls the engine through its own
function-pointer table, swap the POINTER and dispatch on the return address -- no engine detour, no trampolines.
C4 "keep the would-be totals": lending the record around Thinker's painter was WRONG (its golden_age/pop-boom read the
lent totals -> false colour/boom; user: unacceptable). FINAL: no lend; thinkertext.cpp mode 'N' RENUMBERS the formatted
"Pop:" string (four integer runs -> would-be T/W/D/S from pssphere's PsSphereWouldBePop); the painter keeps the live
record. Kept from the audit: lazy would-be passes use runReal=false (a real mod_base_energy pass outside the snapshot
inflates energy_intake_2); ThinkerRange re-resolves a late thinker.dll. LESSON: when a foreign painter derives several
things from one record, lend nothing -- rewrite the one output you own.
The Thinker launcher folder's resolution shortcuts -> D:\SmacxThinker\run-at-res.bat <W> <H> -> run-at-resolution.ps1 -GameExe
thinker.exe -WaitExe terranx.exe (new param: wait on the game the launcher started, not the launcher) -SwitchDesktop
(new param: ChangeDisplaySettings to WxH BEFORE the launch, restored in finally). WHY: thinker.dll's init_video_config
reads GetSystemMetrics in DllMain, before PRACX's mode switch, so a 1080p test run under the mode-switch launcher left
Thinker believing 4K: its credits/interlude backgrounds stretched to 4K (top-left quarter visible; measured by
correlating the shot with credits2.pcx, 0.993) and its version label off screen. Every earlier non-4K Thinker run had
this; engine-side layout was unaffected (the engine ran at the ini resolution). USER-VERIFIED 2026-10-30 after the fix:
1080p credits from the main menu (full-frame background + label on its scaled margin) and base text fine; -SwitchDesktop
and the restores worked live. Thinker text module + label margin CONFIRMED at 4K + 1920x1080. Test: work\tests\test_thinker_aivis_sites.py (completeness: every E8 to a wrapped function is listed).
LESSONS: GCC bool returns are al-only -> mask before use; Thinker reaches engine functions through .data function
POINTERS (swap the pointer, not a call site); GCC's engine-faction/owner reads: `[reg+0xE]` = VEH faction, `[reg+7]` =
MAP owner, `[reg+4]` = BASE faction -- the discriminator between unit knowledge and tile ownership.
**2026-10-30 pillage probe:** `hook_thinker_pillage.js` (observer) proves WrapPillageFight in a live game: PILLAGE (action_destroy
+0xA0AC0 entry) / BOMBARD (live target of the retargeted call +0xA13C4, verdict by the stack rule) / SHOT (mod_battle_fight +0xAD450
entry reached inside it) / BLOCKED. Desktop Thinker folder "SMACX Thinker Probe - Pillage Bombardment". The AI pillages only on its
planner's call + a coin flip, so the check needs a war with sensors/airbases/boreholes on reachable border tiles and single
undetected cloaked units within two tiles; a run with "pillages 0" measured nothing.

**Pillage-bombardment fix: trigger corrected 2026-10-30.** Thinker's action_destroy enters its bombardment branch (50% coin, type-15 scan for the territory owner's land-Artillery / sea-combat stacks within 2 of the attacker) ONLY when called with on-map target coordinates. Thinker's AI pillage order (combat_move -> net_action_destroy(id,0,-1,-1)) never bombards. On-map callers: action_arty on an empty tile (player), vanilla enemy_move's artillery-terrain bombard (only factions Thinker does not control), natives' Spore Launchers (faction 0 unfiltered by design). So WrapPillageFight is unreachable from AI pillaging while Thinker controls every AI faction; live for vanilla-driven factions. Kept, harmless. Probe hook_thinker_pillage.js: hosts action_destroy, the retargeted call, mod_battle_fight, mod_enemy_veh +0xAED10 (counter), combat_move +0x5E050 (PLANNER lines). mod_enemy_move's out-of-line copy +0xAECE0 is never called (inlined). Observation: AI infantry on the player's sensors re-planned up to 17x/turn with move orders and never moved (ZOC or hidden-stack bump) -- undiagnosed.
Bump under Thinker VERIFIED in-game 2026-10-30 (probe run, turns 7-19): 11 spot_stack calls by faction 4 on the player's cloaked units, all returning into uimod.dll (the bump), all NEW, 0 by engine spotting; the boxed-in AI infantry's 17x/turn re-plan loop = failed odds after discovery, not a missed discovery.
**2026-10-30 (evening):** ZOC rule committed f96dec3. Decisions: Thinker version label KEPT on the scaled margin (final); airdrop diversion's silent skip of a second hidden neighbour ACCEPTED. Residuals explained to the maintainer: defender/garrison_count only ever count the AI's own / pact tiles; nuclear_move's buster tally hides nothing (missile chassis cannot cloak or submerge); plans_upkeep mil_strength is omniscient like vanilla's. Datalinks text: install.py now applies patch_helptext (game folder + smac_mod, every install/update run, restored on --uninstall; payload + tests); the marker-bump rule is test-pinned. Moot display-modes note deleted. THINKER VERSION WARNING BUILT + AUDITED (thinkerversion.cpp, DLL e3f29e9e in the workspace; installer warn_thinker_build; audit fixes: un-relabelled Cancel never dismisses, token = version/stamp-size, VirtualQuery-safe string scan, uninstall restores text before the refusal): the maintainer's exact wording, no feature named, OK / Don't Show Again (only the latter persists; token = our version + Thinker stamp, so either changing re-shows); the Thinker pin lives once in version.h / version.py (THINKER_SUPPORTED_*). Test switch [UIMod] ThinkerVersionWarnTest=1 is SET in the workspace ini for the maintainer's check -- remove after. The maintainer accepted the three planner residuals as by design. OPEN: user verification of the dialog; MP under Thinker; THINKER FORK upstream backlog.
