"use strict";
// THINKER AI PERCEPTION TRACE -- OBSERVER ONLY, function-ENTRY hosts only, writes nothing.
//
// Question (Thinker compat decision 5, option 2 "measure first", 2026-10-28): does Thinker 5.5's planner act on
// cloaked / Deep-Pressure-Hull stacks the planning faction has NEVER SEEN? Vanilla does (the aivis filter in
// uimod.dll fixes that for the vanilla planner, but it is byte-check-disabled under Thinker because Thinker
// replaces enemy_move / order_veh / action_* wholesale). Thinker's planner reads Vehs[] directly, so a read
// census cannot catch it; this trace measures OUTCOMES at the function entries Thinker itself owns:
//
//   TURN     mod_enemy_turn(faction): census of hidden-kind foreign units unseen by that faction, with the
//            stack rule verdict (the same v3 rule as aivis.cpp HiddenStack). Zero hidden-unseen stacks all run
//            = the scenario had nothing to be blind to -> the run measured nothing (said so at the end).
//   HEADING  mod_enemy_move(veh) leave: the unit now carries a go-to whose destination is ON / next to / two
//            tiles from a hidden-unseen stack (base destinations skipped: aircraft going home are not evidence).
//   STEP     Thinker's order_veh(veh, dir, flag) entry: the mover's next tile holds a hidden-unseen stack
//            (a bump or a blind attack, both are "the AI walked exactly there").
//   ATTACK   mod_battle_fight_2(veh, dir, tx, ty, ...) entry: the target tile holds a hidden-unseen stack
//            (blind) or a SEEN hidden-kind stack (legitimate -- logged too, so the two can be compared).
//   SPOTTED  a hidden-kind unit's visibility byte gained a bit (the engine's spot rules fired): tells
//            "it was seen, then attacked" apart from "attacked blind".
//   READ     engine primitives veh_at / anything_at / veh_who / stack_check called while a Thinker move is
//            being planned, landing on a hidden-unseen stack: how much of Thinker's knowledge still flows
//            through the primitives the DLL CAN filter (return address says thinker.dll vs terranx.exe).
//   VANILLA  vanilla enemy_move entry under Thinker (its fallback for player patrol units / veh < 0).
//
// Thinker's functions have no symbols; their entries are read LIVE from the call/jump operands Thinker wrote
// into the exe (patch.cpp write_call/write_jump sites), each verified to land inside thinker.dll:
//   0x579362 -> mod_enemy_move   0x528289 -> mod_enemy_turn   0x506ADE -> mod_battle_fight_2
//   0x5947C0 (E9) -> Thinker's order_veh
// Engine hosts are attached only when their live first bytes are a plain `55 8B EC` prologue.
// Unit array: Thinker's modify_unit_limit relocates Vehs[] into thinker.dll's .bss -- resolved the way the
// DLL's ModernCtlVehs does (the disp32 of veh_selectable's `movsx edx,[eax+Vehs+2]` at 0x5C1A39).
//
// Run: D:\SmacxThinker\trace.bat (desktop "SMACX Thinker AI Trace") -> work\scripts\run_frida_thinker.py
// starts thinker.exe in the workspace, attaches once thinker.dll + uimod.dll are loaded, logs to
// work\frida_thinker_aivis_<UTC>.log. Load a save with cloaked / DPH units of yours inside Thinker AI
// territory, end turns, then close the game. Read the log's SUMMARY block first.

globalThis.LOG_PATH = globalThis.LOG_PATH || "D:/SmacxUi/work/frida_thinker_aivis.log";
log("=== hook_thinker_aivis.js started " + new Date().toISOString() + " ===");

// ---- engine globals / layouts (terranx.h; VEH per Thinker engine_veh.h) -------------------------------------
const VEH_SIZE = 0x34, UNIT_SIZE = 0x34, MAP_SIZE = 0x2C, CHASSIS_SIZE = 0x90;
const V_X = 0x00, V_Y = 0x02, V_FLAGS = 0x08, V_UNIT = 0x0A, V_FACTION = 0x0E, V_ORDER = 0x11,
      V_WPX0 = 0x14, V_WPY0 = 0x1C, V_VIS = 0x27, V_NEXT = 0x30, V_PREV = 0x32;
const U_ABIL = 0x20, U_CHASSIS = 0x24, U_CARRY = 0x28;
const ABL_HIDDEN = 0x04 | 0x40;          // ABL_CLOAKED | ABL_DEEP_PRESSURE_HULL
const VFLAG_INVISIBLE = 0x400;
const ORDER_SENTRY_BOARD = 1, ORDER_MOVE_TO = 0x18, ORDER_MOVE_TO_B = 0x58;   // go-to family (aivis.cpp)
const TRIAD_LAND = 0;

const VA_Vehs = 0x952828, VA_VehSelOperand = 0x5C1A39, VA_VehCount = 0x9A64C8, VA_Units = 0x9AB868;
const VA_MapTiles = 0x94A30C, VA_MapHalfX = 0x68FAF0, VA_MapAreaX = 0x949870, VA_MapAreaY = 0x949874;
const VA_MapToggleFlat = 0x94988C, VA_ChassisTriad = 0x94A379, VA_FactionStatus = 0x9A64E8;
const VA_DirDX = 0x66EF50, VA_DirDY = 0x66EF74;
const VA_CurrentTurn = 0x9A64D4;         // *CurrentTurn (Thinker engine.h); display only

// Thinker-written call/jump sites -> Thinker function entries (patch.cpp v5.5)
const SITE_mod_enemy_turn = 0x528289, SITE_mod_enemy_move = 0x579362, SITE_mod_battle_fight_2 = 0x506ADE;
const SITE_order_veh_jmp = 0x5947C0;
// engine hosts (plain prologues on the baked exe; verified live before attaching)
const VA_enemy_move = 0x56B5B0, VA_veh_at = 0x5BFE90, VA_anything_at = 0x5798E0, VA_veh_who = 0x500250,
      VA_stack_check = 0x5B9580;

// ---- counters / state ---------------------------------------------------------------------------------------
const N = { turns: 0, moves: 0, headOn: 0, headAdj: 0, headNear: 0, steps: 0, attacksBlind: 0, attacksSeen: 0,
            spotted: 0, vanilla: 0, reads: {}, readsThinker: 0, readsExe: 0, turnsWithTargets: 0 };
let ctx = { veh: -1, fac: -1, turnFac: -1 };
let hiddenIds = [];                      // hidden-kind unit ids (rebuilt per turn, every 64 planned moves, and on any VehCount change)
let visSnap = new Map();                 // veh id -> visibility byte
let headSeen = new Set();                // "veh:x:y" dedup per turn
let readLogged = 0;
let vehsBase = null;
let thinker = null;
let lastCount = -1;                      // veh_kill COMPACTS Vehs[] (memmove + VehCount--): every id-keyed state above the
let curStep = null;                      //   killed slot is stale afterwards (audit 2026-10-28) -> rebuilt on any count change
N.nativeHits = 0; N.countChanges = 0;

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
function unitName(u) { try { return u >= 0 ? VA(VA_Units).add(u * UNIT_SIZE).readUtf8String(24) : "?"; } catch (e) { return "?"; } }
function unitAbil(u) { return u >= 0 ? VA(VA_Units).add(u * UNIT_SIZE + U_ABIL).readU32() : 0; }
function isHuman(f) { return ((rdU8(VA_FactionStatus) >> f) & 1) !== 0; }
function isAi(f) { return f > 0 && f < 8 && !isHuman(f); }
function turn() { try { return rd32(VA_CurrentTurn); } catch (e) { return -1; } }
function inThinker(p) { return thinker !== null && p.compare(thinker.base) >= 0 && p.compare(thinker.base.add(thinker.size)) < 0; }
function where(p) { return inThinker(p) ? "thinker.dll+0x" + p.sub(thinker.base).toString(16) : "exe 0x" + p.toString(16); }

function mapSq(x, y) {
  if (x < 0 || y < 0 || x >= rd32(VA_MapAreaX) || y >= rd32(VA_MapAreaY)) return null;
  return VA(VA_MapTiles).readPointer().add((y * rd32(VA_MapHalfX) + (x >> 1)) * MAP_SIZE);
}
function isBaseTile(sq) { return sq !== null && (sq.add(8).readU32() & 1) !== 0; }
function tileDist(x1, y1, x2, y2) {       // the DLL's measure: (|dx| + |dy|) / 2 with x wrap
  let dx = Math.abs(x1 - x2);
  const w = rd32(VA_MapAreaX);
  if ((rd32(VA_MapToggleFlat) & 1) === 0 && dx > w / 2) dx = w - dx;
  return ((dx + Math.abs(y1 - y2)) / 2) | 0;
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
// true iff the stack holding `id` is hidden from faction f: every unit hidden-kind or loaded in a hidden-kind
// transport, all foreign, no base tile, no unit carrying f's seen bit.
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
// the stack on (x,y), via the engine's own lookup is a hook host -- walk Vehs instead (cheap: hiddenIds only)
function hiddenUnseenAt(x, y, f) {
  for (const i of hiddenIds) {
    if (!vehOk(i) || vx(i) !== x || vy(i) !== y) continue;
    if (vfac(i) !== f && hiddenStack(i, f)) return i;
  }
  return -1;
}
function hiddenKindAt(x, y, f) {           // any hidden-kind foreign unit there (seen or not)
  for (const i of hiddenIds) if (vehOk(i) && vx(i) === x && vy(i) === y && vfac(i) !== f) return i;
  return -1;
}

// Natives (faction 0) carry VFLAG_INVISIBLE while lurking: they are hidden-kind too, but not the question asked
// (the player's cloaked / DPH units), so they are kept out of the verdicts and counted apart.
function rebuildHiddenIds() {
  hiddenIds = [];
  const n = vehCount();
  for (let i = 0; i < n; ++i) {
    try { if (vunit(i) >= 0 && vfac(i) !== 0 && hiddenKind(i)) hiddenIds.push(i); else if (vunit(i) >= 0 && vfac(i) === 0 && hiddenKind(i)) N.nativeHits++; } catch (e) {}
  }
  visSnap.clear();
  for (const i of hiddenIds) visSnap.set(i, vvis(i));
  lastCount = n;
}
// true (and everything id-keyed rebuilt) when units were created or killed since the last look
function countChanged(when) {
  if (vehCount() === lastCount) return false;
  N.countChanges++;
  log("COUNT    turn " + turn() + ": VehCount " + lastCount + " -> " + vehCount() + " " + when + " -> ids rebuilt, this verdict dropped");
  rebuildHiddenIds();
  return true;
}
function diffVisibility(when) {
  for (const i of hiddenIds) {
    if (!vehOk(i)) continue;
    const now = vvis(i), was = visSnap.get(i);
    if (was !== undefined && now !== was) {
      const gained = now & ~was;
      if (gained) {
        N.spotted++;
        log("SPOTTED  turn " + turn() + ": hidden veh " + i + " \"" + unitName(vunit(i)) + "\" fac " + vfac(i) + " at (" + vx(i) + "," + vy(i) +
            ") now seen by factions mask 0x" + gained.toString(16) + " (vis " + was.toString(16) + "->" + now.toString(16) + ") -- " + when);
      }
    }
    visSnap.set(i, now);
  }
}
function describe(i) {
  return "veh " + i + " \"" + unitName(vunit(i)) + "\" fac " + vfac(i) + " at (" + vx(i) + "," + vy(i) + ")";
}

// ---- resolution of Thinker's entries from the live exe -----------------------------------------------------
function callTarget(site, name) {
  const p = VA(site);
  const op = p.readU8();
  if (op !== 0xE8 && op !== 0xE9) { log("  " + name + ": site 0x" + site.toString(16) + " is " + op.toString(16) + ", not E8/E9 -> not hooked"); return null; }
  const t = p.add(5 + p.add(1).readS32());
  if (!inThinker(t)) { log("  " + name + ": site 0x" + site.toString(16) + " targets " + t + " outside thinker.dll -> not hooked"); return null; }
  log("  " + name + " = " + where(t) + "  (from site 0x" + site.toString(16) + ")");
  return t;
}
function engineEntry(va, name) {
  const p = VA(va);
  const b = Array.from(new Uint8Array(p.readByteArray(3)));
  if (b[0] !== 0x55 || b[1] !== 0x8B || b[2] !== 0xEC) {
    log("  " + name + " @0x" + va.toString(16) + ": live bytes " + b.map(x => x.toString(16).padStart(2, "0")).join(" ") + " are not a plain prologue -> not hooked");
    return null;
  }
  return p;
}

function install() {
  if (!requireBase()) return;
  thinker = Process.findModuleByName("thinker.dll");
  if (!thinker) { log("ERROR: thinker.dll is not loaded in this process -- this trace measures Thinker; nothing installed."); return; }
  log("thinker.dll base " + thinker.base + " size 0x" + thinker.size.toString(16) + "; game turn " + turn());

  // Vehs[] (Thinker relocates it)
  const sel = VA(VA_VehSelOperand);
  const sb = Array.from(new Uint8Array(sel.readByteArray(3)));
  if (sb[0] === 0x0F && sb[1] === 0xBF && sb[2] === 0x90) vehsBase = ptr(sel.add(3).readU32()).sub(2);
  else vehsBase = VA(VA_Vehs);
  log("Vehs[] at " + vehsBase + (vehsBase.equals(VA(VA_Vehs)) ? " (stock)" : " (relocated by Thinker, " + where(vehsBase) + ")") + ", VehCount " + vehCount());

  log("resolving Thinker entries:");
  const fEnemyTurn = callTarget(SITE_mod_enemy_turn, "mod_enemy_turn");
  const fEnemyMove = callTarget(SITE_mod_enemy_move, "mod_enemy_move");
  const fBattle2 = callTarget(SITE_mod_battle_fight_2, "mod_battle_fight_2");
  const fOrderVeh = callTarget(SITE_order_veh_jmp, "order_veh (Thinker)");

  if (fEnemyTurn) Interceptor.attach(fEnemyTurn, {
    onEnter(args) {
      const f = args[0].toInt32();
      ctx.turnFac = f;
      if (N.turns > 0) summary();                          // a normal game exit never reaches the rpc summary
      N.turns++;
      headSeen.clear();
      rebuildHiddenIds();
      if (!isAi(f)) { log("TURN     " + turn() + " fac " + f + " (" + (isHuman(f) ? "human" : "native") + ") -- not measured"); return; }
      let unseen = 0, lines = [];
      for (const i of hiddenIds) {
        if (vfac(i) === f) continue;
        const seen = (vvis(i) >> f) & 1;
        const hs = !seen && hiddenStack(i, f);
        if (!seen) unseen++;
        lines.push("    " + describe(i) + (seen ? " SEEN by fac " + f : hs ? " UNSEEN, stack hidden" : " UNSEEN, but stack NOT hidden (mixed stack / base tile)"));
      }
      if (unseen) N.turnsWithTargets++;
      log("TURN     " + turn() + " fac " + f + " (Thinker AI): " + hiddenIds.length + " hidden-kind unit(s) on the map, " + unseen + " unseen by this faction");
      for (const l of lines) log(l);
    }
  });

  if (fEnemyMove) Interceptor.attach(fEnemyMove, {
    onEnter(args) {
      const v = args[0].toInt32();
      ctx.veh = v;
      ctx.fac = vehOk(v) ? vfac(v) : -1;
      N.moves++;
      if ((N.moves & 63) === 0) { rebuildHiddenIds(); }
      countChanged("before planning veh " + v);
      diffVisibility("before planning " + (vehOk(v) ? describe(v) : "veh " + v));
    },
    onLeave(retval) {
      const v = ctx.veh, f = ctx.fac;
      ctx.veh = -1; ctx.fac = -1;
      if (countChanged("while planning veh " + v)) return;   // the mover may have been disbanded: its slot is another unit now
      if (!vehOk(v) || !isAi(f)) return;
      diffVisibility("while planning " + describe(v));
      const o = vorder(v);
      if (o !== ORDER_MOVE_TO && o !== ORDER_MOVE_TO_B) return;
      const wx = V(v).add(V_WPX0).readS16(), wy = V(v).add(V_WPY0).readS16();
      if (wx < 0 || wy < 0) return;
      const dsq = mapSq(wx, wy);
      if (isBaseTile(dsq)) return;                       // going home: not evidence
      let best = -1, bestD = 99;
      for (const i of hiddenIds) {
        if (!vehOk(i) || vfac(i) === f || ((vvis(i) >> f) & 1) || !hiddenStack(i, f)) continue;
        const d = tileDist(vx(i), vy(i), wx, wy);
        if (d < bestD) { bestD = d; best = i; }
      }
      if (best < 0 || bestD > 2) return;
      const key = v + ":" + wx + ":" + wy;
      if (headSeen.has(key)) return;
      headSeen.add(key);
      if (bestD === 0) N.headOn++; else if (bestD === 1) N.headAdj++; else N.headNear++;
      log("HEADING  turn " + turn() + ": " + describe(v) + " order " + o.toString(16) + " goes to (" + wx + "," + wy + "), " +
          (bestD === 0 ? "ON" : bestD === 1 ? "NEXT TO" : "TWO TILES FROM") + " unseen hidden " + describe(best));
    }
  });

  // HEADING at the STEP instead of at mod_enemy_move's exit: Thinker's internal calls to mod_enemy_move are
  // INLINED (first run 2026-10-29: 28 AI turns, "moves planned 0" -- only the out-of-line copy the exe's
  // call site reaches carries the symbol), so the committed go-to is read here, where every step executes.
  function headingAtStep(v, f) {
    const o = vorder(v);
    if (o !== ORDER_MOVE_TO && o !== ORDER_MOVE_TO_B) return;
    const wx = V(v).add(V_WPX0).readS16(), wy = V(v).add(V_WPY0).readS16();
    if (wx < 0 || wy < 0) return;
    if (isBaseTile(mapSq(wx, wy))) return;
    let best = -1, bestD = 99;
    for (const i of hiddenIds) {
      if (!vehOk(i) || vfac(i) === f || ((vvis(i) >> f) & 1) || !hiddenStack(i, f)) continue;
      const d = tileDist(vx(i), vy(i), wx, wy);
      if (d < bestD) { bestD = d; best = i; }
    }
    if (best < 0 || bestD > 2) return;
    const key = v + ":" + wx + ":" + wy;
    if (headSeen.has(key)) return;
    headSeen.add(key);
    if (bestD === 0) N.headOn++; else if (bestD === 1) N.headAdj++; else N.headNear++;
    log("HEADING  turn " + turn() + ": " + describe(v) + " order " + o.toString(16) + " goes to (" + wx + "," + wy + "), " +
        (bestD === 0 ? "ON" : bestD === 1 ? "NEXT TO" : "TWO TILES FROM") + " unseen hidden " + describe(best) + " (read at its step)");
  }

  if (fOrderVeh) Interceptor.attach(fOrderVeh, {
    onEnter(args) {
      const v = args[0].toInt32(), dir = args[1].toInt32();
      if (!vehOk(v) || dir < 0 || dir > 7) return;
      const f = vfac(v);
      if (!isAi(f)) return;
      N.moves++;                                   // AI steps executed (mod_enemy_move itself is inlined away)
      if ((N.moves & 63) === 0) rebuildHiddenIds();
      countChanged("before a step of veh " + v);
      headingAtStep(v, f);
      let tx = vx(v) + rd32(VA_DirDX + dir * 4);
      const ty = vy(v) + rd32(VA_DirDY + dir * 4);
      if ((rd32(VA_MapToggleFlat) & 1) === 0) { const w = rd32(VA_MapAreaX); if (tx < 0) tx += w; else if (tx >= w) tx -= w; }
      const h = hiddenUnseenAt(tx, ty, f);
      if (h < 0) return;
      N.steps++;
      this.step = { v: v, f: f, h: h, tx: tx, ty: ty, visBefore: vvis(h), n0: vehCount() };
      curStep = this.step;                                 // the ATTACK hook judges on visBefore, not on a bit the step itself set
      log("STEP     turn " + turn() + ": " + describe(v) + " moves dir " + dir + " INTO (" + tx + "," + ty + ") holding unseen hidden " + describe(h) +
          " (called from " + where(this.returnAddress) + ")");
    },
    onLeave(retval) {
      if (!this.step) return;
      const s = this.step;
      curStep = null;
      if (vehCount() !== s.n0) { log("STEP     ... result " + retval.toInt32() + ": VehCount changed during the step (a unit died) -> outcome not attributed"); countChanged("after the step"); return; }
      const alive = vehOk(s.h) && vx(s.h) === s.tx && vy(s.h) === s.ty;
      log("STEP     ... result " + retval.toInt32() + ": hidden veh " + s.h + (alive ? " still there, vis " + s.visBefore.toString(16) + "->" + vvis(s.h).toString(16) : " gone from that tile (killed or moved)") +
          "; mover now at (" + (vehOk(s.v) ? vx(s.v) + "," + vy(s.v) : "?") + ")");
      diffVisibility("after the step");
    }
  });

  if (fBattle2) Interceptor.attach(fBattle2, {
    onEnter(args) {
      const v = args[0].toInt32(), tx = args[2].toInt32(), ty = args[3].toInt32();
      if (!vehOk(v)) return;
      const f = vfac(v);
      if (!isAi(f)) return;
      if (curStep && curStep.v === v && curStep.tx === tx && curStep.ty === ty && vehOk(curStep.h)) {
        // the step that is executing walked into this stack: judge on the bit as it was BEFORE the step
        const blind = ((curStep.visBefore >> f) & 1) === 0;
        if (blind) N.attacksBlind++; else N.attacksSeen++;
        log("ATTACK   turn " + turn() + ": " + describe(v) + " attacks (" + tx + "," + ty + ") = hidden " + describe(curStep.h) +
            (blind ? " BLIND (unseen when the step began" + (((vvis(curStep.h) >> f) & 1) ? ", spotted by the step itself)" : ")") : " that fac " + f + " had seen before the step (legitimate)") +
            " (from " + where(this.returnAddress) + ")");
        return;
      }
      const hu = hiddenUnseenAt(tx, ty, f);
      if (hu >= 0) { N.attacksBlind++; log("ATTACK   turn " + turn() + ": " + describe(v) + " attacks (" + tx + "," + ty + ") = UNSEEN hidden " + describe(hu) + " BLIND (from " + where(this.returnAddress) + ")"); return; }
      const hk = hiddenKindAt(tx, ty, f);
      if (hk >= 0) { N.attacksSeen++; log("ATTACK   turn " + turn() + ": " + describe(v) + " attacks (" + tx + "," + ty + ") = hidden-kind " + describe(hk) + " that fac " + f + " HAS seen (legitimate)"); }
    }
  });

  // engine primitives, counted only while a Thinker move is being planned
  function readHook(name, p, tileArgs) {
    if (!p) return;
    N.reads[name] = 0;
    Interceptor.attach(p, {
      onEnter(args) {
        // the viewer: the unit being planned when mod_enemy_move's symbol is reached, else (inlined planning)
        // the faction whose turn mod_enemy_turn is running, for calls coming from thinker.dll
        let viewer = ctx.fac;
        if (viewer < 0 && inThinker(this.returnAddress) && isAi(ctx.turnFac)) viewer = ctx.turnFac;
        if (viewer < 0 || !isAi(viewer)) return;
        let hit = -1;
        if (tileArgs) hit = hiddenUnseenAt(args[0].toInt32(), args[1].toInt32(), viewer);
        else { const s = args[0].toInt32(); if (vehOk(s) && vfac(s) !== viewer && hiddenStack(s, viewer)) hit = s; }
        if (hit < 0) return;
        N.reads[name]++;
        if (inThinker(this.returnAddress)) N.readsThinker++; else N.readsExe++;
        if (readLogged < 40) {
          readLogged++;
          log("READ     turn " + turn() + ": " + name + " on unseen hidden " + describe(hit) + " by fac " + viewer +
              (ctx.veh >= 0 ? " while planning " + describe(ctx.veh) : " during its turn") + " (from " + where(this.returnAddress) + ")");
        }
      }
    });
  }
  readHook("veh_at", engineEntry(VA_veh_at, "veh_at"), true);
  readHook("anything_at", engineEntry(VA_anything_at, "anything_at"), true);
  readHook("veh_who", engineEntry(VA_veh_who, "veh_who"), true);
  readHook("stack_check", engineEntry(VA_stack_check, "stack_check"), false);

  const pVan = engineEntry(VA_enemy_move, "enemy_move (vanilla)");
  if (pVan) Interceptor.attach(pVan, {
    onEnter(args) {
      N.vanilla++;
      if (N.vanilla <= 20) { const v = args[0].toInt32(); log("VANILLA  turn " + turn() + ": vanilla enemy_move(" + v + ")" + (vehOk(v) ? " " + describe(v) : "") + " from " + where(this.returnAddress)); }
    }
  });

  log("installed; waiting for AI turns (end a turn in-game).");
  setInterval(summary, 60000);
}

function summary() {
  const reads = Object.keys(N.reads).map(k => k + "=" + N.reads[k]).join(" ");
  log("SUMMARY  turn " + turn() + ": AI turns " + N.turns + " (" + N.turnsWithTargets + " with unseen hidden stacks), moves planned " + N.moves +
      "; HEADING on/adjacent/two " + N.headOn + "/" + N.headAdj + "/" + N.headNear + "; STEP into unseen " + N.steps +
      "; ATTACK blind " + N.attacksBlind + " / on seen cloaked " + N.attacksSeen + "; SPOTTED " + N.spotted +
      "; engine READs on unseen stacks: " + reads + " (from thinker.dll " + N.readsThinker + ", from exe " + N.readsExe + "); vanilla enemy_move " + N.vanilla +
      "; VehCount changes " + N.countChanges + "; lurking natives seen in censuses " + N.nativeHits + " (excluded from every verdict)");
  if (N.turns > 0 && N.turnsWithTargets === 0)
    log("SUMMARY  NOTE: no AI turn had a hidden-unseen stack to be blind to -- this run measured nothing; park cloaked/DPH units in Thinker AI territory and retry.");
}

rpc.exports = { summary: function () { summary(); } };
install();
