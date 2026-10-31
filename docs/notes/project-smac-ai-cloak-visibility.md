---
name: project-smac-ai-cloak-visibility
description: AI perception filter arc (vanilla bug: AI ignores Cloaking/Deep Pressure Hull) — COMMITTED c34738c, uimod.dll aivis.cpp; user decisions, engine spotting rules, net-flag carrier, chronological log (newest entries at the bottom supersede earlier guesses)
type: project
---

**Arc opened 2026-09-18. Status: investigation + design done, NO code written yet.**
Vanilla bug (not ours): AI targets/avoids cloaked + Deep Pressure Hull units as if visible. No community fix
exists (Scient: none; OpenSMACX: none; WtP README:774 just DISABLED DPH; Thinker 5.4 only gates its own
`choose_defender` move.cpp:315 on `is_visible`, its threat map move.cpp:840 ignores it). Clones:
refs\scient-unofficial-smacx-patch, refs\OpenSMACX, refs\thinker-doer (gitignored).

**2026-09-18 later: Frida prototype first (no bake yet): `work\scripts\hook_aivis_proto.js` (MODE probe
default; pre-script `aivis_mode_filter.js` = filter). Run via `work\run-frida-at-res.bat hook_aivis_proto.js 3840 2160 [aivis_mode_filter.js]`.**
Census result: ALL 14 inline Vehs loops in enemy_move scan the AI's OWN faction (the one enemy scan ~0x56F25D
already honours the bit) and there are NO inline map veh-bit/owner-nibble reads -> the filter is exactly 128 E8
call sites inside enemy_move (29 veh_at 0x5BFE90, 7 veh_who 0x500250, 13 anything_at 0x5798E0, 79 stack_check)
re-pointed at wrappers; zoc_* deliberately untouched (move legality must match execution). Bump = order_veh ENTRY
wrapper (veh,dir,_): target tile via DirDX 0x66EF50 / DirDY 0x66EF74; action() 0x4CF740 ignores order_veh's
result so a cancelled bump re-enters enemy_move via enemy_turn's loop (cap 0x20). All hosts' live entry bytes are
plain prologues; PRACX touches none. Final DLL port = same shape (rel32 rewrites + order_veh entry detour).

**2026-09-18 (latest): restriction LIFTED. DLL port WRITTEN + builds clean, NOT DEPLOYED** — `src\uimod\src\aivis.cpp/.h`
(128 rel32 rewrites + WrapEnemyMove at both enemy_move callers 0x512842/0x579362 + order_veh/process_message entry
detours over the shared 9-byte SEH prologue + send-site 0x52902A wrapper), init.cpp, prefs.cpp row id 0x63
"AI Cannot See Cloaked Units", ini `[UIMod] AiRespectsCloak` default 1. Launcher trace shortcuts -> hook_aivis_proto.js
(probe). Deploy only AFTER the maintainer's probe log is read (a deployed DLL breaks the probe's byte checks). Open list in
the maintainer's work log "AI PERCEPTION FILTER".

**Frida runs 2026-09-18 (user, mag-tube line of cloaked units in AI territory):** PROBE = 42 veh_at + 58 stack_check
reads of never-seen stacks, 1 order_veh step into one -> vanilla blind attack (VehCount 58->57); the maintainer's other
vanilla kills did NOT pass through order_veh => deliberate attacks go via enemy_move's direct battle_fight calls
(my "adjacency spotting explains them" guess was wrong — units stayed unseen all run). FILTER = 1 BUMP revealed +
cancelled, only that unit later attacked, the rest never found; veh_at 235 / anything_at 3577 filtered, stack_check 0
(never fed once veh_at is -1). Known leak: Path_find reads the map itself, so AI routes still bend around hidden
units without "knowing". **DLL 0f428156 DEPLOYED** (backup uimod.dll.7a19103f.bak); awaiting in-game verify. Trace
shortcuts still point at the Frida FILTER proto — don't run them with the new DLL deployed (double hooks).

**User test of DLL 0f428156 (2026-09-18): setting clearly works (off = AI zeroes in and kills), but ON the AI PATHS
AROUND the hidden units so it almost never bumps.** Cause: Path_find 0x59A530 (two inline sites 0x59AE58 /
0x59B6EF: `test byte [eax+8],2 ; jne` then owner nibble vs faction/pact -> tile impassable; faction = arg7
[ebp+0x1C]) and Path_move 0x59BC10's greedy fallback (0x59BFA6 `mov al,[eax+edx*4+8] ; test al,3`, ecx = tile,
faction [ebp-0xC]). FIX = third hook group in aivis.cpp: 6-byte site detours -> naked stubs -> PathTileHidden(tile,
faction) (x,y recovered from the tile pointer: idx/MapHalfX, x = 2*(idx%half)+(y&1)); compiled stubs disassembled +
checked. Row pitch set to 20 native (stock CheckList rowH logged 50 px @g40). **DLL 68feade5 DEPLOYED, awaiting
verify.** Note the same inline test leaks cloaked-unit positions to a HUMAN's go-to routing too (left vanilla).

**Human path leak CLOSED too (user decision 2026-09-18: "regardless of the setting")** — PathTileHidden applies to
human factions unconditionally in SP/hotseat/PBEM; in NET games it rides net bit 1 (kNetBitHumanPath, always set by
a mod host) because peers execute each other's go-to steps and must path identically. Discovery for humans = the
engine's own order_veh reveal path (SPOTTED popup). **DLL cf43ce1f DEPLOYED, awaiting verify.**

**User: "Everything works" (AI filter + bump + paths + human path fix, DLL cf43ce1f). Next leak = DIPLOMACY
withdrawal.** territory(owner,intruder,flags,&base,&cnt) 0x55EB80 is the single intruder counter for BOTH directions
(AI: communicate x4, enemy_diplomacy, make_treaty, demand_withdrawal's TURNABOUT; human reply: do_withdrawal's moved
count -> WITHDRAW vs NOWITHDRAW popup) and has NO visibility test => yes, the AI complains about cloaked units it
never saw (decompile; not yet observed in-game). The commlink menu item itself (id 9) is gated only on treaty/truce,
not on units. FIX = diplomacy group in aivis.cpp: territory()'s whose_territory call 0x55ED62 and do_withdrawal's
base_find_2 call 0x5491A3 re-pointed; a stack hidden from the territory OWNER is not counted and not teleported
(design choice: sneaking units are not yanked home). Human owner = always (net bit 1, renamed kNetBitHumanLeaks),
AI owner = checkbox. **DLL 0d7b1003 DEPLOYED, awaiting verify.**

**2026-09-18 later: ALL groups USER-VERIFIED in-game on the PRACX exe (filter, bump, paths, human path,
diplomacy); vanilla terranx.exe log check PASSED (all four groups install, prefs tab self-disables). DLL 0d7b1003
deployed. CHANGELOG written (Fixes + Mod settings). UNCOMMITTED: src\uimod\src\aivis.cpp/.h (untracked), init.cpp,
prefs.cpp, uimod.vcxproj, the maintainer's work log, CHANGELOG.md, terranx.h, .gitignore. The maintainer's work log now has two special
categories the maintainer asked for: COMPATIBILITY (Thinker partial-coverage log line NOT WRITTEN, Scient check, prefs
page off-PRACX) and NETWORKING (done LAST: two-machine carrier check + every older MP-only item moved there).
Launcher trace shortcuts still point at the Frida FILTER proto (don't run with the DLL deployed).**

**SUBMARINE test (user, 2026-09-18): three DPH transports (non-cloaked cargo / cloaked cargo / empty) all found
at once with the setting ON.** Engine spotting rule (spot_all ~0x5B77xx, decompiled): a mover scans 25 tiles (2-tile
radius; 49 with a sensor) and marks a hidden stack SEEN if the stack has >1 unit (`stack_check(stack,1)!=1`), or the
observer has ABL 0x2 / stands in own territory on a sensor tile, or the factions lack COMMLINK (diplo bit 8); hidden-
kind is tested on ONE unit and the WHOLE stack gets the bit. So loaded transports are legitimately spotted at 2 tiles.
REAL BUG fixed: HiddenStack v1 demanded EVERY unit be hidden-kind, so a never-seen sub with plain cargo read as visible
-> v2 = "some unit hidden-kind AND no unit has the viewer's seen bit". Empty sub unexplained -> added `[UIMod]
AiVisDebug=1` (set in the maintainer's ini) logging `aivis dbg: ... -> reason` whenever a planning AI reads a stack holding a
hidden-kind unit that the filter let through. **DLL 140d6aa7 DEPLOYED, awaiting the maintainer's sub re-test + log.**

**STACK RULE v3 = USER'S RULE (2026-09-18, overrides my v2 "any hidden-kind unit"):** a stack is hidden ONLY if every
unit is hidden-kind itself OR is LOADED in a hidden-kind transport (order ORDER_SENTRY_BOARD=1 with waypoint_x[0]
VEH+0x14 = a hidden-kind transport on the same tile; fallback for editor-placed cargo: LAND-triad unit on an ocean
tile when the stack has a hidden-kind carrier, UNIT+0x28 carry_capacity, Chassis triad 0x94A379 stride 0x90). Plus
the unchanged gates: all foreign, non-base tile, no unit with the viewer's seen bit. **DLL df8d7502 DEPLOYED with
AiVisDebug=1 in the maintainer's ini; awaiting the submarine re-test + log (turn the ini key off before release testing).**

**Sub re-test log (2026-09-18): the filter was NOT at fault — EVERY lone hidden unit on the map (the lone sub (2,52)
AND all the mag-tube cloaked units, same coords that were unseen in the first probe) carried faction 4's seen bit
= the ENGINE spotted them. Open question: which spot_all rule (mover Deep Radar ABL 0x2 / mover on a sensor tile in
own territory / no commlink) — likely own-territory sensors now that AI units walk up to them. Added debug-only
spot_all tracer (6 call sites 0x4CCFC3 0x511655 0x5230BA 0x57B813 0x598D3E 0x5C04EE -> WrapSpotAllDbg, armed only
with AiVisDebug=1): logs `SPOTTED veh .. by fac .. veh .. -> rule: ...` at the moment a bit appears. Seen bits
PERSIST in saves, so a re-test needs FRESH hidden units. DLL 0acf3307 deployed; awaiting that log. is_sensor =
0x5BF010, diplo status table 0x96C9F8 [observer*0x833+other], bit 8 = commlink.**

**Tracer result (2026-09-18): the spotters were AI units with DEEP RADAR (ABL 0x2, cost 0 in alphax.txt so AI designs
carry it freely: "Clean String Cruiser/Copter" abil 0x10002) + the multi-unit rule; the territory-sensor rule never
fired. spot_all: normal mover scans 25 offsets (first 9 unconditional), sensor mover 49 (first 25 unconditional);
"sensor mover" = has_abil 2 OR (is_sensor(tile) AND tile in own territory). USER DECISION: keep those engine rules,
DOCUMENT them in the Datalinks (work\scripts\patch_helptext.py -> helpx.txt #ABILDESC2/#ABILDESC6, applied to the dev
install, backup helpx.txt.longevity.bak; release installer must run it — no text step in the patcher yet), and add
option "Cloaked Transport Hides Its Cargo" (prefs row id 0x64, ini CloakedTransportHidesCargo, default 1 [my choice,
flagged], net bit 2): WrapSpotAllStackCount at spot_all's stack_check site 0x5B7810 does not count units loaded in a
hidden-kind transport (RidesHiddenTransport shared with HiddenStack). DLL f18b5feb deployed, awaiting verify.**

**CORRECTION (2026-09-19, user's in-game tests + re-read): hidden-stack detection is ADJACENT-ONLY.** spot_all has two
unit-spotting loops: the 9-tile ring (decompile lines ~642-1017) holds ALL the hidden-stack rules (Deep Radar, sensor,
multi-unit, no-commlink); the radius-2 ring (index 9..24) spots a stack only if the unit it tests is NOT hidden-kind.
My earlier "within two squares" was WRONG. The tested unit = what stack_fix 0x5B8E10 returns for the tile (sites
0x5B743D adjacent, 0x5B7FCA radius-2): if that is plain CARGO, the whole sub is an ordinary visible stack seen from 2
squares (trace: loaded sub (79,55) seen from (79,51)) -> the cargo option v1 (count only) could not work. v2 adds
WrapSpotAllStackFix at both sites: a passenger of a hidden-kind transport is answered with the TRANSPORT (pure
StackFixAdjusted; the tracer never calls the engine's stack_fix, it can reorder stacks). is_sensor 0x5BF010 = the
MOVER'S OWN tile has the sensor flag (MAP+8 bit 31) [or a base-related fallback] AND the tile is in the mover's own
territory — i.e. the unit must stand ON the sensor, as the maintainer observed. Help text v2 says "moves next to it" for all
three rules (patch_helptext.py rebuilds from the backup when it finds the v1 marker). DLL c0f09e90 deployed; tracer
line now shows stack / counts-as / judged-by unit / dist. Awaiting verify.**

**2026-09-19: USER-VERIFIED in-game: two stacked cloaked units ARE seen by any unit moving adjacent (non-Deep-Radar
too); a Deep Radar unit 2 tiles away does NOT see them -> hidden detection = adjacent only. Help text v3 (three
entries now: #ABILDESC1 Deep Radar, #ABILDESC2 Cloaking, #ABILDESC6 DPH) carries this. Labels: AI row reworded by
user to "AI Cannot See Cloaked Units Until Actually Discovered"; cargo row nested (kChkSubIndent 18 native).
OPEN BUG: after that label change the maintainer reports "the preferences tab totally disappeared" though uimod.log says
"Longevity tab built". Hypothesis (UNPROVEN): rows are child windows above the page and the long label's row reached
over the tab-button column. Mitigation in DLL 7ac94b17: RowW() clamps each row short of TabX and logs
`prefs: row x= want= tabX= ... -> w=`. Read those numbers + get a screenshot before theorising further.**

**2026-09-19 log read: prefs tab was FINE (user mis-saw; tabX=33 is LEFT of the rows at x=256, so my overlap theory
was wrong; RowW clamp is a harmless no-op). Cargo option v2 WORKS: `stack=3, counts as 1, judged by veh 91
hiddenKind=1`. Every spotting = dist 1 by a DEEP RADAR AI unit ("Clean String Cruiser", "Deep Copter"),
fresh marks gained (not stale). OPEN QUESTION: why do AI ships arrive adjacent to never-seen subs so
fast — old add_goal entries from earlier sightings at the same coords, patrol chance, or an unfiltered knowledge
path? Added debug `HEADING fac .. veh .. goes to (x,y), which is ON/next to UNSEEN hidden veh ..` (WrapEnemyMove ->
DebugDestination, go-to orders 0x18/0x58, waypoint_x/y[0] = VEH+0x14/+0x1C). DLL c0dfaf0f deployed. Test needs
FRESH subs at NEW coordinates (goals are positional and persist in saves).**

**2026-09-19 (later) log: all 3 moved subs WERE re-spotted (each by an adjacent Deep Radar "Clean String Cruiser";
one merely survived). HEADING lines: Cruiser 79 went to (3,49) = adjacent to the sub stack's OLD tile (3,51) as well
as its new (4,50) -> consistent with an old positional goal, NOT proof of a leak; still open. LAND TRANSPORT BUG
found: cloaked hovertank transport + passenger at (10,56) `counts as 2`, spotted by a NON-radar "Clean String
Chopper" via the multi-unit rule. Cause (hypothesis from code order, not yet traced): spot_all calls wake_stack
0x5B6060 (sites 0x5B7631 / 0x5B84A0) on the observed stack BEFORE the count at 0x5B7810; waking clears the passenger's
ORDER_SENTRY_BOARD and on LAND nothing else says "aboard" (at sea my land-unit-on-ocean fallback hid this). FIX in DLL
47d4ee02: WrapSpotAllWake snapshots the riders of a hidden-kind transport, calls wake_stack, then ROLLS BACK those
riders' order + state dword (they stay aboard; the transport still wakes) and the count also honours the snapshot.
Tracer now dumps `units[id:order:wp0:hidden]` per spotted stack to verify. Awaiting user re-test.**

**2026-09-19 re-test (DLL 47d4ee02): GOOD. Two NEW subs parked within 2 tiles of Deep Radar ships = never spotted
(adjacent-only confirmed for AI observers too); the cloaked hovertank transport next to an enemy base = NOT spotted
(wake rollback works); only spotting of a sub = an old one at (74,56) by an ADJACENT Deep Radar cruiser, dump
`88:o01:w87 89:o01:w87 87:o00` proves passengers carry order 1 + wp0 = transport id. HEADING lines all pointed at
(11,55) / (8,30) = almost certainly the AI's own BASES (aircraft going home; transport was parked beside a base) ->
false positives; diagnostic now ignores base destinations (DLL 9e444fc6). No evidence of a knowledge leak so far.**

**COMMITTED + PUSHED c34738c (2026-09-19), uimod.dll 9e444fc6 deployed, AiVisDebug key removed from the dev ini. All hook groups user-verified in-game on the PRACX exe. REMAINING: NETWORKING two-machine check, COMPATIBILITY items (Thinker partial-coverage log line not written; helpx patch under other mods; installer must run patch_helptext.py), launcher trace shortcuts still point at the Frida FILTER proto (conflicts with the DLL).** Ghidra symbol apply DONE 2026-09-19 (23 data labels; nothing tracked changed, project is gitignored).

**User decisions (do not relitigate):**
- Deep Radar / own-sensor / multi-unit detection of hidden units stays as the engine has it; it gets documented.
- Hidden-stack rule = the v3 rule above (every unit cloaked, or uncloaked units loaded in a cloaked transport).
- Scope = ONLY ability/flag-hidden units (ABL_CLOAKED 0x4, ABL_DEEP_PRESSURE_HULL 0x40, VFLAG_INVISIBLE 0x400)
  whose visibility bit is unset for the viewing AI. NOT general fog-of-war for the AI.
- Logic lives in uimod.dll; default ON; checkbox = new row on the Longevity page (Recipe A2, id 0x63).
- Net games: FOLLOW THE SERVER's setting, carried in the exact message that precedes the AI turn, as a
  BITMASK (room for future net-critical settings).
- Build compat in NOW for vanilla terranx.exe / Thinker / Scient: no cave VAs, byte-checked entry detours,
  self-disable + log on mismatch; ini key works everywhere, checkbox only where the Longevity tab exists.
- Bump semantics required: AI unit walking into a hidden unit must DISCOVER it and RE-EVALUATE, not blunder on.

**Engine facts (pristine decompile; symbols in terranx.h "AI unit visibility + net upkeep"):**
- VEH+0x27 (array 0x95284F) per-faction visibility byte is maintained for AI factions too: spot_all 0x5B6260
  classes the mover hidden on has_abil 0x40 / 4 / flags&0x400. Only 73 code refs exe-wide; enemy_move 0x56B5B0
  (56 KB) reads it at 2 sites (0x56CBBD, 0x56F25D) vs ~200 blind queries (79 stack_check, 29 veh_at,
  13 anything_at, 7 veh_who, 23 zoc_*, + inline Vehs loops needing a site census).
- Loop: enemy_turn -> enemy_veh 0x579240 { enemy_move (decide; but ALSO calls battle_fight/probe/action_*
  directly) -> action (execute) } repeated while moves remain, cap 0x20 iterations then veh_skip.
- **order_veh 0x5947C0 bump is HUMAN-ONLY:** target VFLAG_INVISIBLE -> order=0 + spot_stack + cancel for ANY
  mover (site ~0x596CB8). But an ability-hidden target unseen by the mover (else-branch ~0x596D6x) does
  `if (!(g_93E904 & 1) || mover != CurrentPlayerFaction) goto normal attack path` -> an AI mover just ATTACKS.
  So the filter alone would make AIs auto-attack cloaked units they "didn't see". Need a 2nd hook there: AI
  mover + filter on -> order=0, spot_stack(target, mover_faction), exit WITHOUT the FX_play/SPOTTED popup.
  Re-evaluation then comes free from the enemy_veh loop (bit now set -> no repeat bump).
- Filter design: viewer-faction context set at enemy_move entry/cleared at exit; detour the query primitives so
  a non-base tile whose whole foreign stack is ability-hidden AND unseen reads empty; never in bases, never
  for humans.

**Bit lifetime / AI "memory" (decompiled 2026-09-18):** spot_all only ORs bits in. The bit is CLEARED for all
factions by order_veh's `unspot_stack(mover)` on every successful move of a non-native unit (~0x598193), then
spot_all re-evaluates at the new tile under cloak rules -> a spotted cloaked unit stays known exactly until it
next MOVES. battle_fight_2 0x506AF0 sets the ATTACKER's bit (single veh, not its stack) for the defender faction
when param_6 (local human is a party / omniscient) and add_goal(def_faction,0x10,2,x,y) at the battle tile;
enemy_strategy 0x561080 already honours the bit when adding type-6 goals on enemy units (~0x561830). No per-unit
count memory exists; goals are the only persistence. Strategic/production strength tallies are NOT filtered by
our design (stay omniscient as vanilla). Design choice: one revealed unit exposes the whole tile's stack.

**Netcode (hybrid, NOT pure authority):** humans = lock/ACTION/EXEC/synch via server (g_net_is_server 0x93E8C0).
AI turns = REPLICATED: net_upkeep 0x5290A0 phase UPKEEP5 calls enemy_turn for every AI faction on EVERY peer
(no server gate; enemy_veh's net branch is local-human-faction only), then UPKEEP6/7 21 checksums
(message_big_data 0x2307) -> server NetDaemon_synch resync on mismatch ("Failed GAME/MAP/BASES checksum").
**Flag carrier:** net_upkeep_phase 0x528EA0 server broadcast `message_data(0x4303,0,phase,turn,0,0)`; client
handler in NetDaemon_process_message 0x534400 ("From Server: NEXT UPKEEP") reads only msg words [2],[4],[5]
-> p3/p4 (msg +0x18/+0x1C) are FREE. Plan: p3 = settings bitmask (bit0 = AI cloak filter), p4 = magic/version;
vanilla server sends 0/0 = all off = exactly vanilla behaviour. Unverified: order_veh's synch_veh gating, RNG sync.

Related: [[project-smac-uimod-dll]], [[feedback-uimod-shared-dll-gate]], (a private note).

## 2026-09-19 — flag mark, nested prefs, Survey Pod rule (DLL 213fe0a1, user-verified, committed)
- **Spotted-cloak flag mark**: red "!" with white stroke (art: `work/art/cloak_seen_mark.svg`; user rejected eye+! as unreadable at flag size, chose bare mark + white stroke). Drawn as 3 clipped `Buffer_fill_3` rects (native 5x10: stroke 1, bar 3x5, gap 1, dot 3x2; each rounds with a >=1 px floor) at flag+(19S, 1S). Colours = static palette 0xF9 red / 0xFF white.
- **One hook covers map + all stack views**: every flag draw goes through `veh_draw` 0x5594F0 (28 callers). Its ENTRY is owned by our patcher (thunk_hud_vehargs) -> hook the LAST draw call inside it, 0x55A11D (`call Buffer_write_cent_l_7`, thiscall RET 0xC), reached only when a flag was drawn. Read veh_draw's live frame via ebp: +8 buf, +0x10/+0x14 final flag x,y, +0x18 size (HUD views arrive pre-scaled), +4 caller ret (map 0x467183 / veh_scoot 0x55AAFF 0x55ACE0 0x55AE6D = one flag speaks for the stack; list views per unit). **TRAP: [ebp+0xC] (veh id) low byte is clobbered at 0x559C7D -> use [ebp-0x14]/0x34.** veh >= 2048 = veh_fake scratch slot, skip.
- Shows for OWN hidden-kind units seen by a non-pact, non-native faction, and FOREIGN hidden-kind units carrying our seen bit; never in bases. Pref row id 0x65 "Show Alert Icon on Detected Cloaked Units", `[UIMod] CloakAlertIcon`, display-only (not in the net mask). Toggle must repaint BOTH draw_map(1) and `StatusWin_redraw` 0x4B9EA0(this=0x8C5568) — HUD panels cache their image.
- **Nested rows follow the parent** (user decision): AI row off -> cargo + icon forced off; on -> both on; child clicks ignored while parent off; forced off at ini load too.
- **spot_all REVERSE path** (measured, decompile lines ~565-660): a hidden MOVER is revealed only to an adjacent stack whose judged unit has Deep Radar, or with no commlink; adjacent BASE never reveals a hidden mover with commlink. The mover's own stack size and sensors never count there. So a cloaked unit stepping into a double stack is NOT revealed by its own move — only when an enemy later MOVES adjacent (stack rule is forward-only). Tracer logs `REVEALED ITSELF` for this path (AiVisDebug=1).
- **is_sensor returns 2**: base with Geosynchronous Survey Pod (fac 41) -> base tile + 8 tiles at dx,dy in {0,2} = nine VIRTUAL sensor sites (radius-2 effects blanket the base radius). For the cloak rule ("mover stands ON a sensor in own territory") that lattice was 9 arbitrary tiles (user test: plane at (25,23) saw, neighbour tile did not). **Fix (user decision: no checkbox, gated by the parent, too obtuse to explain)**: wrap ONLY spot_all's mover-tile call 0x5B63A1 -> whole 21-tile radius of a pod base owned by the tile's owner. Never change is_sensor itself (14 other callers: combat bonus, AI terraform, pathing). Net bit 3 (`kNetBitPodRadius`), host mask now 0x0F with everything on.
- Datalinks help text v7: sensor bullet = "...sensor array inside its own territory, or within range of one of its bases that has a {Geosynchronous Survey Pod}. It then counts as having Deep Radar. Being merely in range of a sensor array is not enough."
- Flag mark USER-VERIFIED at 4K and all other resolutions (2026-09-19).

## 2026-09-19 (later): GETOUT extra reply -- BUILT, awaiting in-game verify (DLL 7e4d3dac (was 76b89d5b before rowindent), uncommitted)
- AI's withdraw demand = `communicate` 0x54FFD0 (esi=AI, edi=human): label "GETOUT"+rand 1..5, `X_pops_11` call at 0x5503E1, returns 0-based reply index (0 withdraw -> do_withdrawal at 0x55046F, 1 likewise, 2/-1 refuse).
- Popups have NO per-option mask; vary replies by label. `X_pops_18` only tries alienI/alienu script files when filename is SCRIPT; any other filename goes straight to `pops_18`.
- Ours: when the human has unseen hidden units in the AI's land (SP only), copy the #GETOUTn block from the engine's source file into generated `uimod_getout.txt` with reply 0's text + " (Including undetected cloaked troops)" inserted 2nd; reply 1 sets g_withdrawAll (WrapWithdrawBaseFind stops skipping), indices remapped. MP not offered (do_withdrawal runs on every peer via msg 0x244A).
- Known residual: do_withdrawal's one-tile-hop pre-pass (land protos with cargo, 0x549031..) never calls base_find_2, so it is not gated by the hidden test.
- 76b89d5b: BOTH the withdraw reply and the "only if you likewise" reply get an "all" twin (replies 0 w, 1 w-all, 2 likewise, 3 likewise-all, 4 refuse -> stock 0,0,1,1,2); g_wantAll is consumed by the wrapped do_withdrawal(ai,human) sites 0x55046F / 0x5505EB only, the AI's reciprocal 0x550632 stays filtered. User saw the first build in-game: "looking good".
- 76b89d5b: suffix shortened to " (Including undetected cloaked troops)" -- talk-window reply rows are ONE line, ~90 chars fit (the long suffix clipped the likewise twin at 4K).
- 2026-09-20 CLOSED: GETOUT twin replies user-verified all res, suffix " (Including undetected cloaked troops)", DLL 14ae5dae, committed. do_withdrawal + territory() skip OCEAN tiles in vanilla ((tile[0]&0xE0)<0x60 -> continue): ships/subs are never counted or withdrawn; user chose to leave that.

## 2026-10-30 -- AIRDROP DIVERSION (aivis.cpp "airdrop diversion" group; workspace DLL e9c208ed; drops USER-VERIFIED 2026-10-30, CHANGELOG written; PUSHED master 0e35163)
- Base-game leak: a drop onto a tile holding units the player could not see was refused with #DROPUNIT ("an area
  containing other factions' units") -> presence revealed. User's design: divert to the first free neighbour (DirDX
  order; free = land, no non-pact units, no non-pact base; own/pact squares fine), reveal the stack to the dropper,
  popup "Our unit was diverted by a cloaked defender occupying the drop zone!" (fog case: "... an unseen defender
  ..."); no free neighbour -> today's DROPUNIT, nothing revealed; an already-revealed unit -> untouched.
- Mechanics that matter: action_airdrop (engine 0x4CC360, cdecl veh,tx,ty,flags) flags bit0 = interactive popups,
  bit1 = EXECUTE (without it the call is a check: refusals apply, returns 1, nothing moves; MP checks with 1 then
  executes the broadcast with 2 on every peer; SP passes 3) -> probe candidates with flags&~3, execute the first
  allowed with the real flags, reveal and popup only on flags&2. Refusal order range -> sea -> units: divert only
  for a LAND target within drop_range 0x500320 (else out-of-range probing becomes a cloak detector); the diverted
  square is never refused for range (Rules->max_airdrop_rng 0x949740 raised by one around the candidate calls,
  user rule); any other refusal -> next square. Under Thinker the detour sits on Thinker's own action_airdrop
  (+0x96670; its planner calls it directly, the engine entry is its write_jump). Fog extension (user): human
  factions only; AI keeps the cloaked rule (no fog in vanilla). FOG IS PER UNIT (audit 2026-10-30): MAP +4 is
  "ever explored" (set-only, copied by map trades, never cleared) -> UnseenStack(tgt,f) = every unit's sight bit
  (Veh+0x27 bit f) clear, none own; omniscient 0x80 excepted.
- ZOC scope (engine bytes 0x4CC5CF..E3, 2026-10-30): action_airdrop applies zoc_move 0x5C8D40 to NON-COMBAT units only
  (weapon offense 0 -> NONCOMDROP); zoc_sea 0x5C8BA0 per unit = f's sight bit, else (SP only) no VFLAG_INVISIBLE 0x400.
  An unseen stack therefore blocks every candidate for a non-combat drop in SP (-> DROPUNIT = vanilla); combat units
  skip ZOC on a drop -> the diversion is a combat-drop feature (user accepted). MP: only seen units exert.
- Setting (user 2026-10-30): "Air Drops Divert Around Unseen Defenders" (prefs id 0x79, [UIMod] AirdropDiversion=1,
  AirdropActive(): SP local, MP the host's kNetBitAirdrop 1<<4). Replaced "Brighten Scanlines" (0x6F retired; bright
  scanlines always on). MP residual accepted: a peer whose sight bits differ at the execute runs the original.
- Residuals: all candidates refused by the engine -> DROPUNIT (= vanilla); a neighbour holding a second hidden stack is
  skipped silently (inferable by walk order; ACCEPTED by the maintainer 2026-10-30, stays).

## 2026-10-29 -- THINKER HALF (thinkeraivis.cpp; built, awaiting the maintainer's verify)
- Under Thinker the core group used to FAIL (0x579362 is Thinker's write_call to mod_enemy_move, 0x5947C0 its write_jump
  to its own order_veh) and the early return skipped paths/diplomacy/net too. Now the core accepts those two as
  Thinker's (TransfersIntoThinker), re-points only Console_veh_turn's call, and `thinkeraivis.cpp` ports the filter
  into thinker.dll 5.5 itself (Thinker's planner reads Vehs[] directly): wrappers on non_ally_in_tile / stack_search /
  allow_combat (all call sites), register-forwarding stubs on the two unit-loop at_war calls (artillery scoring,
  move_upkeep census), Thinker's `enemy_move` .data pointer -> WrapEnemyMove, bump detour on Thinker's order_veh.
  Measured need: 4 blind artillery attacks + go-tos converging on unseen stacks (trace 2026-10-29). Details, residuals
  and the manage_player_units design point: [[project-smac-thinker-compat]] + the maintainer's work log "DECISION 5".

**Zone of control, user rule 2026-10-30 (BUILT, AUDITED, USER-VERIFIED 2026-10-30; not yet committed):** a HUMAN faction's hidden-kind unit (cloaked / deep pressure hull / scenario-invisible) that faction X has not seen exerts no ZOC on X (X human or AI, natives included); once seen it does. Why: order_veh's ZOC refusal reveals the blockers only to the LOCAL HUMAN (spot_loc loop + ZOCMSG tutorial text); an AI mover is refused silently and Thinker re-planned the same step up to 17x/turn inside a ring of the maintainer's cloaked units. How: aivis.cpp entry-detours zoc_any 0x5C89F0 (10-byte prologue) / zoc_veh 0x5C8AC0 / zoc_sea 0x5C8BA0 (6-byte); the original answers first, a nonzero answer with the cloak setting on is recomputed by ports that skip units hidden-kind AND unseen AND human-owned (never on base tiles; tile-level only when the whole stack is exempt). thinkeraivis.cpp detours Thinker 5.5's mod_zoc_any +0x70820 / _veh +0x70940 / _sea +0x709E0 (NearbyTiles table + call graph; mod_zoc_move +0x70B10 -> mod_zoc_sea) onto AiVisZocAdjust. AI-OWNED hidden units unchanged (literal rule). Tests: work/tests/test_zoc_hidden_rule.py. helpx DETECT text gained a ZOC sentence; live install re-patched 2026-10-30 (marker v8 -- a DETECT text change must bump HELPX_MARK or the patcher reports 'already patched').
Audit 2026-10-30 clean after fixes (log buffer, base garrison exerts in the sea port too, broken-link guard, caller-count test). DLL de0d6967 deployed to D:\SmacxThinker\game (bak e9c208ed); user verified in-game 2026-10-30; live helpx.txt re-patched (v8).
