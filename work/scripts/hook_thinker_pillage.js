"use strict";
// THINKER PILLAGE-BOMBARDMENT PROBE -- OBSERVER ONLY, function-ENTRY hosts only, writes nothing.
//
// Question (2026-10-30): does the uimod.dll fix for Thinker's post-pillage bombardment fire in a real game?
// Thinker's action_destroy (veh_action.cpp ~651; thinker.dll 5.5 +0xA0AC0) is the pillage routine. When an AI
// land unit pillages an at-war tile, a coin flip (do_combat) adds a BOMBARDMENT: the 24 tiles within two of the
// pillager are scanned (TableOffsetX/Y 1..24) and the first stack of the TERRITORY OWNER holding a bombardable
// unit is shelled through mod_battle_fight(veh, offset, 1, 1, 0) at +0xA13C4 -- found with Thinker's own veh_at,
// i.e. an undetected cloaked stack was hit blind. uimod.dll (thinkeraivis.cpp WrapPillageFight) retargets that one
// call: hidden from the acting faction -> no shot (returns 0; Thinker returns right after the call either way).
//
//   PILLAGE   action_destroy entry: who pillages what tile (unit, faction, target square), and on leave whether the
//             bombardment call was reached at all (tails on the coin, or no owner stack within two -> "no shot").
//   BOMBARD   the retargeted call's entry (live E8 operand at +0xA13C4: uimod.dll = the fix is installed; still
//             mod_battle_fight = NOT installed, the vanilla blind shot is measured instead): the target square from
//             the offset table, the stack there and its verdict under the stack rule (hidden-unseen / seen / plain).
//   SHOT      mod_battle_fight entry (+0xAD450) reached from inside that call: the shell was fired.
//   BLOCKED   the call returned without reaching mod_battle_fight on a hidden-unseen stack: the fix worked.
//
// Hosts: three function ENTRIES (Thinker's action_destroy and mod_battle_fight -- their live first bytes must be
// the plain `55 57 56 53` GCC prologue -- and the call's live target). thinker.dll is pinned to 5.5 by its PE
// TimeDateStamp (0x6A821052); any other build -> nothing attached. Vehs[] is read where Thinker relocated it.
// Planner hosts (added 2026-10-30 after runs with "pillages 0" on a staged scenario): Thinker's mod_enemy_veh
// entry (+0xAED10, the per-unit turn; counter only) and combat_move entry (+0x5E050, the combat planner that
// holds the pillage order; cdecl, arg1 = veh id). For every AI combat unit that starts its move on a
// sensor/airbase/borehole tile outside its own territory it logs a PLANNER line (owner, at-war, weapon offense,
// flags, order) and, on return, what the planner chose instead of pillaging -- so a run without PILLAGE lines
// still says WHY.
//
// MECHANISM, corrected 2026-10-30 from the 18:36 run (3 AI pillages, 0 bombardment calls) and Thinker's source:
// action_destroy only enters the bombardment branch (do_combat) when it is called with ON-MAP target coordinates;
// the 50% coin is inside that branch. Thinker's own AI pillage order (combat_move -> net_action_destroy(id,0,-1,-1))
// and the vanilla player/AI pillage orders pass (-1,-1) and NEVER bombard. On-map callers: action_arty on an EMPTY
// tile (the player's artillery bombarding terrain; engine 0x4CD181), the vanilla AI's artillery-terrain bombard
// (enemy_move 0x578D94 -- only for factions Thinker does not control, thinker.ini factions_enabled), and natives'
// Spore Launchers (mod_alien_move, veh_turn.cpp:436; faction 0 is never filtered by design). So with Thinker
// controlling every AI faction the WrapPillageFight filter is unreachable from AI pillaging; it is live for
// vanilla-driven factions. A staged "AI infantry on my sensor" scenario cannot exercise it.
//
// Run: desktop Thinker folder "SMACX Thinker Probe - Pillage Bombardment" -> D:\SmacxThinker\trace.bat --hook
// hook_thinker_pillage.js. In-game: be at war with a Thinker AI, keep a sensor array / airbase / borehole on your
// border tiles the AI's land units reach, and park SINGLE cloaked units of yours (undetected: one per tile, not
// next to an AI sensor) within two tiles of those improvements; end turns. The PILLAGER needs no artillery: any
// non-air combat unit (infantry included) in enemy territory on such a tile is ordered to pillage (move.cpp
// combat_move), and native life on a human faction's improved tile takes the same routine (veh_turn.cpp, faction
// 0). The TARGET stack is what must qualify: it MUST hold a unit that
// passes Thinker's can_arty(unit, true) -- stack_check type 15 (veh.cpp): a conventional combat unit that is either
// a LAND unit with the Artillery ability or any SEA combat unit; air, psi, probe and non-combat units are never
// chosen, so a cloaked plain infantry stack yields "no bombardment call". Read the SUMMARY lines first; a run with
// "pillages 0" measured nothing.

globalThis.LOG_PATH = globalThis.LOG_PATH || "D:/SmacxUi/work/frida_thinker_pillage.log";
log("=== hook_thinker_pillage.js started " + new Date().toISOString() + " ===");

// ---- engine globals / layouts (terranx.h; VEH per Thinker engine_veh.h) -------------------------------------
const VEH_SIZE = 0x34, UNIT_SIZE = 0x34, MAP_SIZE = 0x2C, CHASSIS_SIZE = 0x90;
const V_X = 0x00, V_Y = 0x02, V_FLAGS = 0x08, V_UNIT = 0x0A, V_FACTION = 0x0E, V_ORDER = 0x11,
      V_WPX0 = 0x14, V_WPY0 = 0x1C, V_VIS = 0x27, V_MOVES_SPENT = 0x28, V_ITER = 0x2A, V_NEXT = 0x30, V_PREV = 0x32;
const U_ABIL = 0x20, U_CHASSIS = 0x24, U_WEAPON = 0x25, U_CARRY = 0x28, U_PLAN = 0x2A;
const M_OWNER = 0x07, M_ITEMS = 0x08;    // MAP: int8 owner, u32 items (Thinker engine_types.h)
const BIT_AIRBASE = 0x40000, BIT_THERMAL_BORE = 0x1000000, BIT_SENSOR = 0x80000000;
const PILLAGE_ITEMS = (BIT_AIRBASE | BIT_THERMAL_BORE | BIT_SENSOR) >>> 0;   // combat_move's pillage trigger set
const VA_Factions = 0x96C9E0, FACTION_SIZE = 0x20CC, F_DIPLO = 0x18;         // Faction.diplo_status[8]
const DIPLO_PACT = 0x1, DIPLO_COMMLINK = 0x8, DIPLO_VENDETTA = 0x10;
const VA_Weapon = 0x94AE60, WEAPON_SIZE = 0x10, W_OFFENSE = 0x08;             // CWeapon.offense_value (int8)
const VFLAG_LURKER = 0x40;
const TRIAD_AIR = 2;
const ABL_HIDDEN = 0x04 | 0x40;          // ABL_CLOAKED | ABL_DEEP_PRESSURE_HULL
const VFLAG_INVISIBLE = 0x400;
const ORDER_SENTRY_BOARD = 1;
const TRIAD_LAND = 0;

const VA_Vehs = 0x952828, VA_VehSelOperand = 0x5C1A39, VA_VehCount = 0x9A64C8, VA_Units = 0x9AB868;
const VA_MapTiles = 0x94A30C, VA_MapHalfX = 0x68FAF0, VA_MapAreaX = 0x949870, VA_MapAreaY = 0x949874;
const VA_MapToggleFlat = 0x94988C, VA_ChassisTriad = 0x94A379, VA_FactionStatus = 0x9A64E8;
const VA_CurrentTurn = 0x9A64D4;

// thinker.dll 5.5 (thinkeraivis.cpp pins; TimeDateStamp 0x6A821052, SizeOfImage 0x19F000)
const THINKER_STAMP = 0x6A821052;
const OFF_action_destroy = 0xA0AC0, OFF_pillage_call = 0xA13C4, OFF_pillage_witness = 0xA13A3, OFF_mod_battle_fight = 0xAD450;
// Planner hosts (static call-graph of thinker.dll 5.5, 2026-10-30; capstone sweep of .text):
//   mod_enemy_turn (+0xAEEB0, engine site 0x528289) calls mod_enemy_veh (+0xAED10) DIRECTLY per unit, so that entry
//   fires; the engine's own enemy_turn/enemy_veh (sites 0x579703/0x579362) are bypassed and mod_enemy_move's
//   out-of-line copy (+0xAECE0) is never called (the 14:36 run: 0 calls there).
//   combat_move = +0x5E050 (size 0x5520; the only caller of net_action_destroy +0x691B0, which calls action_destroy),
//   head `8D 4C 24 04 83 E4 F0 B8` (lea ecx,[esp+4]; and esp,-16; mov eax,..). cdecl, arg1 = veh id.
const OFF_mod_enemy_veh = 0xAED10, OFF_combat_move = 0x5E050;
const ENEMY_VEH_HEAD = [0x57, 0x31, 0xFF, 0x56, 0x53, 0x83, 0xEC, 0x10];
const COMBAT_MOVE_HEAD = [0x8D, 0x4C, 0x24, 0x04, 0x83, 0xE4, 0xF0, 0xB8];
const GCC_PROLOGUE = [0x55, 0x57, 0x56, 0x53];
const WITNESS = [0x8B, 0x44, 0x24, 0x60];
// the engine's 25-entry radius-2 offset table (thinkeraivis.cpp kTableOffsetX/Y)
const TOX = [0, 1, 2, 1, 0, -1, -2, -1, 0, 2, 2, -2, -2, 1, 3, 3, 1, -1, -3, -3, -1, 4, -4, 0, 0];
const TOY = [0, -1, 0, 1, 2, 1, 0, -1, -2, -2, 2, 2, -2, -3, -1, 1, 3, 3, 1, -1, -3, 0, 0, 4, -4];

// ---- counters / state ---------------------------------------------------------------------------------------
const N = { pillages: 0, pillagesAi: 0, bombardCalls: 0, hiddenUnseen: 0, blocked: 0, shotsHidden: 0, shotsSeen: 0,
            shotsPlain: 0, declined: 0, fightsOutside: 0, enemyMoves: 0, enemyMovesAi: 0, combatMoves: 0, candidates: 0,
            spotsBump: 0, spotsEngine: 0 };
// spot_stack(veh_id, faction_id) 0x5B58E0 (cdecl; sets the faction's sight bit on every unit of the stack). A call
// returning into uimod.dll is aivis.cpp's BUMP (a filtered AI unit stepped into an unseen hidden stack); one returning
// into the exe is the engine's own spotting (adjacency, sensors, spot_all after a move).
const VA_SpotStack = 0x5B58E0;
const SPOT_STACK_HEAD = [0x55, 0x8B, 0xEC, 0x53, 0x8B, 0x5D, 0x0C];
const CANDIDATE_LINE_CAP = 300;          // PLANNER lines per run (the planner can revisit a unit several times a turn)
let fixInstalled = null;                 // true: the call targets uimod.dll; false: still mod_battle_fight
let vehsBase = null, thinker = null, uimod = null;
let pillage = null;                      // the action_destroy in flight: { veh, fac, reached }
let call = null;                         // the bombardment call in flight: { verdict, shot }

function rd32(va) { return VA(va).readS32(); }
function rdU8(va) { return VA(va).readU8(); }
function V(i) { return vehsBase.add(i * VEH_SIZE); }
function vehCount() { return rd32(VA_VehCount); }
function vehOk(i) { return i >= 0 && i < vehCount(); }
function vx(i) { return V(i).add(V_X).readS16(); }
function vy(i) { return V(i).add(V_Y).readS16(); }
function vfac(i) { return V(i).add(V_FACTION).readU8(); }
function vunit(i) { return V(i).add(V_UNIT).readS16(); }
function vorder(i) { return V(i).add(V_ORDER).readU8(); }
function vvis(i) { return V(i).add(V_VIS).readU8(); }
// UNIT.name[32] is NUL-terminated; a sized read (readUtf8String(24) / readCString(32)) returned the junk after the NUL
// too, so read to the NUL and clip
function unitName(u) { try { return u >= 0 ? VA(VA_Units).add(u * UNIT_SIZE).readUtf8String().slice(0, 31) : "?"; } catch (e) { return "?"; } }
function unitAbil(u) { return u >= 0 ? VA(VA_Units).add(u * UNIT_SIZE + U_ABIL).readU32() : 0; }
function isHuman(f) { return ((rdU8(VA_FactionStatus) >> f) & 1) !== 0; }
function isAi(f) { return f > 0 && f < 8 && !isHuman(f); }
function turn() { try { return rd32(VA_CurrentTurn); } catch (e) { return -1; } }
function inModule(m, p) { return m !== null && p.compare(m.base) >= 0 && p.compare(m.base.add(m.size)) < 0; }
function where(p) {
  if (inModule(thinker, p)) return "thinker.dll+0x" + p.sub(thinker.base).toString(16);
  if (inModule(uimod, p)) return "uimod.dll+0x" + p.sub(uimod.base).toString(16);
  return "exe 0x" + p.toString(16);
}
function describe(i) {
  if (!vehOk(i)) return "veh " + i + " (out of range)";
  return "veh " + i + " \"" + unitName(vunit(i)) + "\" fac " + vfac(i) + " at (" + vx(i) + "," + vy(i) + ")";
}
function wrapX(x) {
  if ((rd32(VA_MapToggleFlat) & 1) === 0) { const w = rd32(VA_MapAreaX); if (x < 0) x += w; else if (x >= w) x -= w; }
  return x;
}
function mapSq(x, y) {
  if (x < 0 || y < 0 || x >= rd32(VA_MapAreaX) || y >= rd32(VA_MapAreaY)) return null;
  return VA(VA_MapTiles).readPointer().add((y * rd32(VA_MapHalfX) + (x >> 1)) * MAP_SIZE);
}
function isBaseTile(sq) { return sq !== null && (sq.add(8).readU32() & 1) !== 0; }

// ---- planner-observer helpers (Thinker move.cpp combat_move's own tests, ported read-only) ------------------
function diplo(f, g) { return VA(VA_Factions).add(f * FACTION_SIZE + F_DIPLO + g * 4).readU32(); }
function atWar(f, g) { return f !== g && f >= 0 && g >= 0 && f < 8 && g < 8 && (diplo(f, g) & DIPLO_VENDETTA) !== 0; }
function hasPact(f, g) { return f >= 0 && g >= 0 && f < 8 && g < 8 && (diplo(f, g) & DIPLO_PACT) !== 0; }
function weaponOffense(u) {
  if (u < 0) return 0;
  const w = VA(VA_Units).add(u * UNIT_SIZE + U_WEAPON).readU8();
  return VA(VA_Weapon).add(w * WEAPON_SIZE + W_OFFENSE).readS8();
}
function unitTriad(u) {
  if (u < 0) return -1;
  return VA(VA_ChassisTriad).add(VA(VA_Units).add(u * UNIT_SIZE + U_CHASSIS).readU8() * CHASSIS_SIZE).readU8();
}
function itemsName(items) {
  const p = [];
  if ((items & BIT_SENSOR) !== 0) p.push("sensor");
  if ((items & BIT_AIRBASE) !== 0) p.push("airbase");
  if ((items & BIT_THERMAL_BORE) !== 0) p.push("borehole");
  return p.join("+") || "none";
}
function orderName(o) {
  const m = { 0: "none", 1: "sentry/board", 2: "hold", 24: "move-to", 25: "move", 26: "explore", 27: "road-to", 88: "ai-go-to" };
  return m[o] || ("order " + o);
}
function planName(p) { const m = { 0: "offense", 1: "combat", 2: "defense", 3: "recon" }; return m[p] || ("plan " + p); }
// the eight neighbours of (x,y) holding foreign units, as seen by faction f: "(dx,dy) fac5 2u hidden-kind SEEN|unseen"
function neighbours(x, y, f) {
  const out = [];
  for (let k = 1; k <= 8; ++k) {
    const nx = wrapX(x + TOX[k]), ny = y + TOY[k];
    const any = anyUnitAt(nx, ny);
    if (any < 0) continue;
    const top = stackTop(any);
    if (vfac(top) === f) { out.push("(" + TOX[k] + "," + TOY[k] + ") own"); continue; }
    const n = vehCount();
    let units = 0, hidden = 0, seen = 0;
    for (let i = top, g = 0; i >= 0 && i < n && g++ < 64; i = V(i).add(V_NEXT).readS16()) {
      ++units; if (hiddenKind(i)) ++hidden; if ((vvis(i) >> f) & 1) ++seen;
    }
    out.push("(" + TOX[k] + "," + TOY[k] + ") fac" + vfac(top) + " " + units + "u" + (hidden ? " " + hidden + " hidden-kind" : "") +
             (seen === units ? " SEEN" : seen ? " " + seen + " seen" : " UNSEEN") + (isBaseTile(mapSq(nx, ny)) ? " base" : ""));
  }
  return out.length ? out.join("; ") : "none";
}

// ---- the stack rule (port of aivis.cpp HiddenStack v3; the user's rule, do not relitigate) ----------------
function hiddenKind(i) {
  return (unitAbil(vunit(i)) & ABL_HIDDEN) !== 0 || (V(i).add(V_FLAGS).readU16() & VFLAG_INVISIBLE) !== 0;
}
function stackTop(i) {
  const n = vehCount();
  let top = i, guard = 0, p;
  while ((p = V(top).add(V_PREV).readS16()) >= 0 && p < n && guard++ < 4096) top = p;
  return top;
}
function stackHasHiddenCarrier(top) {
  const n = vehCount();
  for (let i = top, g = 0; i >= 0 && i < n && g++ < 4096; i = V(i).add(V_NEXT).readS16()) {
    const u = vunit(i);
    if (u >= 0 && hiddenKind(i) && VA(VA_Units).add(u * UNIT_SIZE + U_CARRY).readU8() !== 0) return true;
  }
  return false;
}
function ridesHiddenTransport(i, x, y, ocean, hiddenCarrier) {
  const n = vehCount();
  if (vorder(i) === ORDER_SENTRY_BOARD) {
    const t = V(i).add(V_WPX0).readS16();
    if (t >= 0 && t < n && t !== i && vx(t) === x && vy(t) === y && hiddenKind(t)) return true;
  }
  if (ocean && hiddenCarrier) {
    const u = vunit(i);
    if (u >= 0) {
      const ch = VA(VA_Units).add(u * UNIT_SIZE + U_CHASSIS).readU8();
      if (VA(VA_ChassisTriad).add(ch * CHASSIS_SIZE).readU8() === TRIAD_LAND) return true;
    }
  }
  return false;
}
function hiddenStack(id, f) {
  const n = vehCount();
  if (id < 0 || id >= n) return false;
  const x = vx(id), y = vy(id), sq = mapSq(x, y);
  if (sq === null || isBaseTile(sq)) return false;
  const ocean = (sq.readU8() & 0xE0) < 0x60;
  const top = stackTop(id);
  const hiddenCarrier = stackHasHiddenCarrier(top);
  let count = 0;
  for (let i = top, g = 0; i >= 0 && i < n && g++ < 4096; i = V(i).add(V_NEXT).readS16()) {
    ++count;
    if (vfac(i) === f) return false;
    if ((vvis(i) >> f) & 1) return false;
    if (hiddenKind(i)) continue;
    if (!ridesHiddenTransport(i, x, y, ocean, hiddenCarrier)) return false;
  }
  return count > 0;
}
// the stack on (x,y) by walking Vehs[] (the engine's veh_at is a hook host elsewhere; a full walk is fine here:
// bombardments are rare)
function anyUnitAt(x, y) {
  const n = vehCount();
  for (let i = 0; i < n; ++i) { try { if (vunit(i) >= 0 && vx(i) === x && vy(i) === y) return i; } catch (e) {} }
  return -1;
}
function stackSummary(top, f) {           // "3 units: 2 hidden-kind (0 seen by f), 1 plain" + names
  const n = vehCount();
  let units = 0, hidden = 0, seen = 0, names = [];
  for (let i = top, g = 0; i >= 0 && i < n && g++ < 64; i = V(i).add(V_NEXT).readS16()) {
    ++units;
    if (hiddenKind(i)) ++hidden;
    if ((vvis(i) >> f) & 1) ++seen;
    if (names.length < 4) names.push(unitName(vunit(i)) + "/f" + vfac(i));
  }
  return units + " unit(s): " + hidden + " hidden-kind, " + seen + " seen by fac " + f + " [" + names.join(", ") + "]";
}

// ---- hosts --------------------------------------------------------------------------------------------------
function bytesAre(p, want) {
  const b = Array.from(new Uint8Array(p.readByteArray(want.length)));
  return want.every((v, i) => b[i] === v) ? null : b.map(x => x.toString(16).padStart(2, "0")).join(" ");
}
function peStamp(m) {
  try { const pe = m.base.add(m.base.add(0x3C).readU32()); return pe.add(8).readU32(); } catch (e) { return 0; }
}

function install() {
  if (!requireBase()) return;
  thinker = Process.findModuleByName("thinker.dll");
  uimod = Process.findModuleByName("uimod.dll");
  if (!thinker) { log("ERROR: thinker.dll is not loaded in this process -- this probe measures Thinker; nothing installed."); return; }
  const stamp = peStamp(thinker);
  log("thinker.dll base " + thinker.base + " size 0x" + thinker.size.toString(16) + " TimeDateStamp 0x" + stamp.toString(16) +
      (uimod ? "; uimod.dll base " + uimod.base : "; uimod.dll NOT loaded") + "; game turn " + turn());
  if (stamp !== THINKER_STAMP) { log("ERROR: not thinker.dll 5.5 (0x" + THINKER_STAMP.toString(16) + ") -- the 5.5 offsets do not apply; nothing installed."); return; }

  // Vehs[] (Thinker relocates it)
  const sel = VA(VA_VehSelOperand);
  const sb = Array.from(new Uint8Array(sel.readByteArray(3)));
  if (sb[0] === 0x0F && sb[1] === 0xBF && sb[2] === 0x90) vehsBase = ptr(sel.add(3).readU32()).sub(2);
  else vehsBase = VA(VA_Vehs);
  log("Vehs[] at " + vehsBase + (vehsBase.equals(VA(VA_Vehs)) ? " (stock)" : " (relocated by Thinker, " + where(vehsBase) + ")") + ", VehCount " + vehCount());

  const fDestroy = thinker.base.add(OFF_action_destroy);
  const fFight = thinker.base.add(OFF_mod_battle_fight);
  const site = thinker.base.add(OFF_pillage_call);
  let bad;
  if ((bad = bytesAre(fDestroy, GCC_PROLOGUE)) !== null) { log("ERROR: action_destroy +0x" + OFF_action_destroy.toString(16) + " live bytes " + bad + " are not the GCC prologue -> nothing installed."); return; }
  if ((bad = bytesAre(fFight, GCC_PROLOGUE)) !== null) { log("ERROR: mod_battle_fight +0x" + OFF_mod_battle_fight.toString(16) + " live bytes " + bad + " are not the GCC prologue -> nothing installed."); return; }
  if ((bad = bytesAre(thinker.base.add(OFF_pillage_witness), WITNESS)) !== null) { log("ERROR: the bombardment witness bytes are " + bad + " -> not the 5.5 layout; nothing installed."); return; }
  if (site.readU8() !== 0xE8) { log("ERROR: +0x" + OFF_pillage_call.toString(16) + " is not a call -> nothing installed."); return; }
  const target = site.add(5 + site.add(1).readS32());
  fixInstalled = inModule(uimod, target);
  if (!fixInstalled && !target.equals(fFight)) { log("ERROR: the bombardment call targets " + where(target) + ", neither uimod.dll nor mod_battle_fight -> nothing installed."); return; }
  log("bombardment call +0x" + OFF_pillage_call.toString(16) + " -> " + where(target) +
      (fixInstalled ? "  (the uimod.dll fix IS installed: a hidden-unseen stack must come back BLOCKED)"
                    : "  (mod_battle_fight itself: the fix is NOT installed -- measuring the vanilla blind shot)"));

  Interceptor.attach(fDestroy, {
    onEnter(args) {
      const veh = args[0].toInt32(), tx = args[2].toInt32(), ty = args[3].toInt32();
      const f = vehOk(veh) ? vfac(veh) : -1;
      N.pillages++;
      if (isAi(f)) N.pillagesAi++;
      pillage = { veh: veh, fac: f, reached: false };
      log("PILLAGE  turn " + turn() + ": " + describe(veh) + (isAi(f) ? " (AI)" : isHuman(f) ? " (HUMAN -- never filtered)" : " (natives)") +
          " destroys at (" + tx + "," + ty + ")" + (tx < 0 ? " [its own tile: (-1,-1) -> the bombardment branch is NOT reachable from this call]"
                                                             : " [on-map target: the 50% coin, then the bombardment scan]"));
    },
    onLeave() {
      if (pillage && !pillage.reached) log("         -> no bombardment call (coin flip, or no owner stack within two tiles)");
      pillage = null;
    }
  });

  Interceptor.attach(target, {
    onEnter(args) {
      const veh = args[0].toInt32(), offset = args[1].toInt32();
      N.bombardCalls++;
      if (pillage) pillage.reached = true;
      call = { verdict: "plain", shot: false, veh: veh, x: -1, y: -1 };
      if (!vehOk(veh) || offset < 1 || offset > 24) { log("BOMBARD  odd args veh " + veh + " offset " + offset + " -- verdict skipped"); return; }
      const f = vfac(veh), x = wrapX(vx(veh) + TOX[offset]), y = vy(veh) + TOY[offset];
      call.x = x; call.y = y;
      const any = anyUnitAt(x, y);
      let verdict = "EMPTY tile (?)";
      if (any >= 0) {
        const top = stackTop(any);
        const hidden = hiddenStack(any, f);
        call.verdict = hidden ? "hidden-unseen" : (vvis(top) >> f) & 1 || !hiddenKind(top) ? "seen-or-plain" : "hidden-kind-seen";
        if (hidden) N.hiddenUnseen++;
        verdict = (hidden ? "HIDDEN-UNSEEN stack" : "visible target") + " -- " + stackSummary(top, f);
      }
      log("BOMBARD  turn " + turn() + ": " + describe(veh) + " offset " + offset + " -> (" + x + "," + y + "): " + verdict +
          "  [call from " + where(this.returnAddress) + "]");
    },
    onLeave(retval) {
      if (!call) return;
      const r = retval.toInt32();
      if (call.verdict === "hidden-unseen") {
        if (call.shot) { N.shotsHidden++; log("SHOT     at the HIDDEN-UNSEEN stack (" + call.x + "," + call.y + ") -- " + (fixInstalled ? "THE FIX DID NOT BLOCK IT (defect)" : "vanilla blind shot, fix not installed")); }
        else { N.blocked++; log("BLOCKED  no shell fired at the hidden-unseen stack (" + call.x + "," + call.y + "); call returned " + r + (fixInstalled ? " -- the fix worked" : " -- the engine declined on its own")); }
      } else if (call.shot) { if (call.verdict === "hidden-kind-seen") N.shotsSeen++; else N.shotsPlain++; log("SHOT     at the visible target (" + call.x + "," + call.y + ") -- legitimate; returned " + r); }
      else { N.declined++; log("         -> no shell (the engine's own combat rules declined); returned " + r); }
      call = null;
    }
  });

  // the planner observer: why an AI unit on a pillage-able tile did or did not pillage
  const fEnemyVeh = thinker.base.add(OFF_mod_enemy_veh);
  if ((bad = bytesAre(fEnemyVeh, ENEMY_VEH_HEAD)) !== null) {
    log("WARN: mod_enemy_veh +0x" + OFF_mod_enemy_veh.toString(16) + " live bytes " + bad + " are not the 5.5 head -> unit-turn counter disabled.");
  } else {
    Interceptor.attach(fEnemyVeh, {
      onEnter(args) {
        N.enemyMoves++;
        const veh = args[0].toInt32();
        if (vehOk(veh) && isAi(vfac(veh))) N.enemyMovesAi++;
      }
    });
  }
  const fCombatMove = thinker.base.add(OFF_combat_move);
  if ((bad = bytesAre(fCombatMove, COMBAT_MOVE_HEAD)) !== null) {
    log("WARN: combat_move +0x" + OFF_combat_move.toString(16) + " live bytes " + bad + " are not the 5.5 head -> PLANNER lines disabled (pillage hosts still installed).");
  } else {
    Interceptor.attach(fCombatMove, {
      onEnter(args) {
        this.cand = null;
        const veh = args[0].toInt32();
        N.combatMoves++;
        if (!vehOk(veh)) return;
        const f = vfac(veh);
        if (!isAi(f)) return;
        const x = vx(veh), y = vy(veh), sq = mapSq(x, y);
        if (sq === null) return;
        const items = sq.add(M_ITEMS).readU32() >>> 0;
        if ((items & PILLAGE_ITEMS) === 0) return;
        const owner = sq.add(M_OWNER).readS8();
        if (owner === f) return;
        N.candidates++;
        if (N.candidates > CANDIDATE_LINE_CAP) return;
        this.cand = { veh: veh, pillages: N.pillages };
        const u = vunit(veh), off = weaponOffense(u), triad = unitTriad(u);
        const flags = V(veh).add(V_FLAGS).readU16(), order = vorder(veh);
        const plan = u >= 0 ? VA(VA_Units).add(u * UNIT_SIZE + U_PLAN).readS8() : -1;
        let why = [];
        if (owner < 0) why.push("tile has NO territory owner -> never 'at enemy'");
        else if (hasPact(f, owner)) why.push("owner is a PACT partner");
        else if (!atWar(f, owner)) why.push("NOT at war with the owner (no vendetta" + ((diplo(f, owner) & DIPLO_COMMLINK) ? "" : ", no commlink") + ") -> never pillages here");
        if (off <= 0) why.push("weapon offense " + off + " -> not a combat unit, never pillages");
        if (triad === TRIAD_AIR) why.push("AIR unit -> excluded");
        if ((flags & (VFLAG_LURKER | VFLAG_INVISIBLE)) !== 0) why.push("LURKER/INVISIBLE flag -> Thinker skips the unit");
        if (order === 24 || order === 88) why.push("has a standing move order to (" + V(veh).add(V_WPX0).readS16() + "," + V(veh).add(V_WPY0).readS16() + ") -> kept unless it is there");
        log("PLANNER  turn " + turn() + ": " + describe(veh) + " on a " + itemsName(items) + " tile owned by fac " + owner +
            (owner >= 0 && isHuman(owner) ? " (human)" : "") + "; weapon offense " + off + ", " + planName(plan) + ", order " + orderName(order) +
            ", moves spent " + V(veh).add(V_MOVES_SPENT).readU8() + ", iter " + V(veh).add(V_ITER).readU8() +
            "; neighbours: " + neighbours(x, y, f) +
            (why.length ? "  !! " + why.join("; ") : "  -> pillage candidate (combat_move must find no attack/scout/patrol/base move first; then action_destroy's 50% coin)"));
      },
      onLeave(retval) {
        const c = this.cand;
        if (!c) return;
        const veh = c.veh, r = retval.toInt32();
        if (!vehOk(veh)) { log("         -> planner returned " + r + "; the unit id is gone"); return; }
        const o = vorder(veh);
        const dest = (o === 24 || o === 88) ? " to (" + V(veh).add(V_WPX0).readS16() + "," + V(veh).add(V_WPY0).readS16() + ")" : "";
        log("         -> combat_move returned " + r + (r === 0 ? " (SYNC)" : r === 1 ? " (SKIP)" : "") + ": order " + orderName(o) + dest +
            ", unit now at (" + vx(veh) + "," + vy(veh) + "), moves spent " + V(veh).add(V_MOVES_SPENT).readU8() +
            (N.pillages > c.pillages ? " -- PILLAGE entered" : " -- no pillage this call" +
              (o === 24 || o === 88 ? " (an attack/scout/patrol/base move won)" : o === 0 ? " (nothing chosen; the 50% planner coin or an earlier exit)" : "")));
      }
    });
  }

  // discoveries: spot_stack by an AI faction on a human faction's hidden-kind stack (bump vs engine spotting)
  let fSpot = VA(VA_SpotStack);
  if (fSpot.readU8() === 0xE9) { const t = fSpot.add(5 + fSpot.add(1).readS32()); log("spot_stack is detoured -> " + where(t) + "; attaching at the target"); fSpot = t; }
  if ((bad = bytesAre(fSpot, SPOT_STACK_HEAD)) !== null) {
    log("WARN: spot_stack " + fSpot + " live bytes " + bad + " are not its prologue (55 8B EC 53 8B 5D 0C) -> SPOT lines disabled.");
  } else {
    Interceptor.attach(fSpot, {
      onEnter(args) {
        const id = args[0].toInt32(), f = args[1].toInt32();
        if (!isAi(f) || !vehOk(id)) return;
        const top = stackTop(id), tf = vfac(top);
        if (!isHuman(tf) || !hiddenKind(top)) return;
        const seenBefore = (vvis(top) >> f) & 1;
        const bump = inModule(uimod, this.returnAddress);
        if (bump) N.spotsBump++; else N.spotsEngine++;
        log("SPOT     turn " + turn() + ": fac " + f + " " + (bump ? "BUMPS INTO" : "spots") + " the hidden stack at (" + vx(top) + "," + vy(top) + ") -- " +
            stackSummary(top, f) + (seenBefore ? " (already seen)" : " (NEW discovery)") + "  [from " + where(this.returnAddress) + "]");
      }
    });
  }

  Interceptor.attach(fFight, {
    onEnter() { if (call) call.shot = true; else N.fightsOutside++; }
  });

  log("installed; waiting for Thinker AI pillages (end turns in-game).");
  setInterval(summary, 60000);
}

function summary() {
  log("SUMMARY  turn " + turn() + ": fix " + (fixInstalled === null ? "unknown" : fixInstalled ? "installed" : "NOT installed") +
      "; pillages " + N.pillages + " (" + N.pillagesAi + " by AI), bombardment calls " + N.bombardCalls +
      "; hidden-unseen targets " + N.hiddenUnseen + ": BLOCKED " + N.blocked + ", SHOT " + N.shotsHidden +
      "; shots at seen cloaked " + N.shotsSeen + ", at plain units " + N.shotsPlain + ", declined by the engine " + N.declined +
      "; other mod_battle_fight calls " + N.fightsOutside +
      "; Thinker unit turns " + N.enemyMoves + " (" + N.enemyMovesAi + " AI), combat_move calls " + N.combatMoves +
      ", AI combat units starting on a sensor/airbase/borehole tile outside their territory " + N.candidates +
      "; AI discoveries of human hidden stacks: by BUMP " + N.spotsBump + ", by engine spotting " + N.spotsEngine);
  if (N.pillages === 0 && N.enemyMoves === 0) log("SUMMARY  NOTE: Thinker's unit turn never ran -- no AI turn passed yet, or Thinker does not control the AI factions (thinker.ini factions_enabled).");
  else if (N.pillages === 0 && N.combatMoves === 0) log("SUMMARY  NOTE: Thinker processed units but combat_move was never entered -- no AI combat unit was planned (the AI unit may be non-combat, flagged lurker/invisible, or carried by a transport).");
  else if (N.pillages === 0 && N.candidates === 0) log("SUMMARY  NOTE: combat_move ran for AI units but none STARTED its move on a sensor/airbase/borehole tile outside its own territory -- the pillager must begin the turn on your improvement, inside YOUR territory (a base's radius), not merely next to it.");
  else if (N.pillages === 0) log("SUMMARY  NOTE: AI units stood on pillage-able foreign tiles but none pillaged -- read the PLANNER lines: '!!' names a hard exclusion (not at war, non-combat, air, flags); without one the planner preferred an attack/scout/patrol move or lost the 50% coin -- more turns.");
  else if (N.pillages === 0) log("SUMMARY  NOTE: no pillage happened -- this run measured nothing; keep sensors/airbases/boreholes on border tiles an at-war Thinker land unit reaches.");
  else if (N.bombardCalls === 0) log("SUMMARY  NOTE: pillages happened but no bombardment call was reached -- a pillage of the unit's OWN tile passes (-1,-1) and never bombards (Thinker's AI pillage order, the player's pillage order). The branch needs an on-map target: artillery bombarding an EMPTY tile (the player; natives' Spore Launchers; the vanilla AI for factions Thinker does not control), then the 50% coin, then a territory-owner stack within two tiles holding land Artillery or a sea combat unit.");
  else if (N.hiddenUnseen === 0) log("SUMMARY  NOTE: no bombardment reached a hidden-unseen stack -- park single undetected cloaked artillery (or ships) within two tiles of those improvements.");
}

rpc.exports = { summary: function () { summary(); } };
install();
