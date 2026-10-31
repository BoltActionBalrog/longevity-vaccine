// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// AI perception filter -- Frida PROTOTYPE (runtime memory only; nothing on disk changes).
// Vanilla bug: the AI's per-unit planner enemy_move (0x56B5B0) finds foreign units through veh_at /
// veh_who / anything_at / stack_check, none of which consult VEH+0x27 (per-faction visibility), so
// Cloaking / Deep Pressure Hull / scenario-invisible units are fully known to it.
//
// MODE "probe"  (default): observe only. Counts the queries that WOULD be filtered and logs every AI
//                          order_veh step into a hidden stack plus what vanilla did with it.
// MODE "filter": (1) the 128 E8 call sites to those four primitives INSIDE enemy_move are re-pointed
//                    (process memory) at wrappers that report a tile empty when its whole foreign stack
//                    is ability/flag-hidden AND unseen by the planning faction (never bases, never
//                    humans, never natives);
//                (2) order_veh (0x5947C0): an AI unit stepping into such a stack discovers it
//                    (spot_stack), has its order cleared and does not attack -- enemy_turn's loop
//                    re-enters enemy_move, which now sees the stack (vanilla does this for the local
//                    human only; AI movers fall through to a blind attack).
// Select with a pre-script that sets globalThis.AIVIS_MODE = "filter" (scripts\aivis_mode_filter.js).

const MODE = globalThis.AIVIS_MODE === "filter" ? "filter" : "probe";
const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "");
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_aivis_" + MODE + "_" + stamp + ".log";
log("=== hook_aivis_proto.js started, MODE=" + MODE + " ===");
installAVHandler("aivis");

// ---- engine layout (terranx.h "AI unit visibility + net upkeep") --------------------------------
const A = {
  enemy_move: 0x0056B5B0, enemy_move_end: 0x00579208,
  veh_at: 0x005BFE90, veh_who: 0x00500250, anything_at: 0x005798E0, stack_check: 0x005B9580,
  order_veh: 0x005947C0, spot_stack: 0x005B58E0,
  message_data: 0x00592EE0, process_message: 0x00534400,
  Vehs: 0x00952828, VehCount: 0x009A64C8, Units: 0x009AB868,
  MapTiles: 0x0094A30C, MapHalfX: 0x0068FAF0, MapAreaX: 0x00949870, MapAreaY: 0x00949874,
  MapToggleFlat: 0x0094988C, DirDX: 0x0066EF50, DirDY: 0x0066EF74,
  FactionStatus: 0x009A64E8, CurrentPlayer: 0x00939284, NetIsServer: 0x0093E8C0,
};
const VEH_SZ = 0x34, UNIT_SZ = 0x34, MAP_SZ = 0x2C;
const ABL_HIDDEN = 0x04 | 0x40;      // ABL_CLOAKED | ABL_DEEP_PRESSURE_HULL
const VFLAG_INVISIBLE = 0x400;
const NET_BIT_AIVIS = 1;             // settings bitmask bit 0 (msg 0x4303 p3); p4 = magic
const NET_MAGIC = 0x4C4D0001;        // 'LM' + version 1

const SITES = {
  veh_who: [0x56e746, 0x574788, 0x575665, 0x5759ed, 0x575a01, 0x575ead, 0x57632a],
  anything_at: [0x56db28, 0x56eb9f, 0x56ee50, 0x56f471, 0x56f7d4, 0x56fbb5, 0x5700a0, 0x5724c9,
    0x572bab, 0x572e68, 0x574507, 0x5773f1, 0x578c5c],
  stack_check: [0x56bd35, 0x56ccf2, 0x56d1ce, 0x56dd9f, 0x56e170, 0x56e483, 0x56e570, 0x56e66c,
    0x56e856, 0x56ead3, 0x56eaef, 0x56f186, 0x56f31e, 0x56f602, 0x56f618, 0x56f706, 0x56f868,
    0x56fcbf, 0x571159, 0x571236, 0x57142e, 0x571459, 0x5715ca, 0x5715e2, 0x571640, 0x57166a,
    0x571697, 0x57175a, 0x571772, 0x57178e, 0x5717dd, 0x571aba, 0x571d05, 0x5723d7, 0x5723e8,
    0x572554, 0x572564, 0x572751, 0x5728df, 0x5734ea, 0x57377b, 0x573af5, 0x573c15, 0x573dc4,
    0x574d88, 0x574dc5, 0x575183, 0x5751e9, 0x575240, 0x57534f, 0x576391, 0x576783, 0x57679b,
    0x576dda, 0x57779f, 0x5778a9, 0x577b3f, 0x577bae, 0x577be0, 0x577d24, 0x577d6d, 0x577df1,
    0x577e08, 0x577ecb, 0x577edf, 0x577f30, 0x577f44, 0x577f66, 0x577f7d, 0x578056, 0x57815d,
    0x578241, 0x578355, 0x5783e3, 0x578440, 0x57849e, 0x5784c3, 0x578653, 0x5791ce],
  veh_at: [0x56ccbe, 0x56d1c5, 0x56dd52, 0x56e137, 0x56e47a, 0x56e84d, 0x56eabc, 0x56ec8d,
    0x56f074, 0x56f5a6, 0x56fc6d, 0x57024b, 0x571a69, 0x571cfc, 0x57203f, 0x572116, 0x57229b,
    0x57253d, 0x57270e, 0x5728ce, 0x573ac7, 0x573bfd, 0x573d95, 0x57517a, 0x575237, 0x575346,
    0x576379, 0x57754a, 0x579157],
};

const KEEP = [];                     // retain every NativeCallback / NativeFunction (GC)
const stats = { em: 0, veh_at: 0, veh_who: 0, anything_at: 0, stack_check: 0, bump: 0 };
let lastStats = "";

if (requireBase()) {
  const vehs = VA(A.Vehs), units = VA(A.Units);
  const fVehAt = new NativeFunction(VA(A.veh_at), "int", ["int", "int"], "mscdecl");
  const fVehWho = new NativeFunction(VA(A.veh_who), "int", ["int", "int"], "mscdecl");
  const fAnyAt = new NativeFunction(VA(A.anything_at), "int", ["int", "int"], "mscdecl");
  const fStackCheck = new NativeFunction(VA(A.stack_check), "int",
    ["int", "int", "int", "int", "int"], "mscdecl");
  const fSpotStack = new NativeFunction(VA(A.spot_stack), "void", ["int", "int"], "mscdecl");
  KEEP.push(fVehAt, fVehWho, fAnyAt, fStackCheck, fSpotStack);

  const vehCount = () => VA(A.VehCount).readS32();
  const V = (id) => vehs.add(id * VEH_SZ);
  const isHuman = (f) => ((VA(A.FactionStatus).readU8() >> f) & 1) !== 0;

  function mapSq(x, y) {
    if (x < 0 || y < 0 || x >= VA(A.MapAreaX).readS32() || y >= VA(A.MapAreaY).readS32()) return null;
    return VA(A.MapTiles).readPointer().add((y * VA(A.MapHalfX).readS32() + (x >> 1)) * MAP_SZ);
  }

  // True iff EVERY unit stacked with veh `id` is foreign to `f`, hidden by ability/flag, and unseen
  // by `f`, on a non-base tile. One visible (or own) unit exposes the whole tile.
  function hiddenStack(id, f) {
    const n = vehCount();
    if (id < 0 || id >= n) return false;
    const sq = mapSq(V(id).readS16(), V(id).add(2).readS16());
    if (sq === null || (sq.add(8).readU32() & 1) !== 0) return false;      // base tile
    let top = id, guard = 0;
    for (let p = V(top).add(0x32).readS16(); p >= 0 && p < n && guard++ < 2048;
         p = V(top).add(0x32).readS16()) top = p;
    guard = 0;
    for (let i = top; i >= 0 && i < n && guard++ < 2048; i = V(i).add(0x30).readS16()) {
      const v = V(i);
      if (v.add(0x0E).readU8() === f) return false;
      const unit = v.add(0x0A).readS16();
      const abil = unit >= 0 ? units.add(unit * UNIT_SZ + 0x20).readU32() : 0;
      const hiddenKind = (abil & ABL_HIDDEN) !== 0 || (v.add(8).readU16() & VFLAG_INVISIBLE) !== 0;
      if (!hiddenKind) return false;
      if (((v.add(0x27).readU8() >> f) & 1) !== 0) return false;
    }
    return true;
  }

  // ---- viewer context: the AI faction whose enemy_move is running (-1 = no filtering) ----------
  let viewer = -1;
  const viewerStack = [];
  Interceptor.attach(VA(A.enemy_move), {
    onEnter(args) {
      viewerStack.push(viewer);
      const id = args[0].toInt32();
      const f = (id >= 0 && id < vehCount()) ? V(id).add(0x0E).readU8() : -1;
      viewer = (f > 0 && f < 8 && !isHuman(f)) ? f : -1;   // natives (0) + humans: vanilla
      stats.em++;
    },
    onLeave() { viewer = viewerStack.length ? viewerStack.pop() : -1; },
  });

  function note(kind, x, y, extra) {
    stats[kind]++;
    if (stats[kind] <= 40)
      log("[" + MODE + "] " + kind + " viewer=" + viewer + " (" + x + "," + y + ") " + extra);
  }

  const wVehAt = new NativeCallback(function (x, y) {
    const r = fVehAt(x, y);
    if (viewer >= 0 && r >= 0 && hiddenStack(r, viewer)) {
      note("veh_at", x, y, "veh=" + r);
      if (MODE === "filter") return -1;
    }
    return r;
  }, "int", ["int", "int"], "mscdecl");

  function tileHidden(x, y) {
    const v = fVehAt(x, y);
    return v >= 0 && hiddenStack(v, viewer);
  }
  const wVehWho = new NativeCallback(function (x, y) {
    const r = fVehWho(x, y);
    if (viewer >= 0 && r >= 0 && r !== viewer && tileHidden(x, y)) {
      note("veh_who", x, y, "owner=" + r);
      if (MODE === "filter") return -1;
    }
    return r;
  }, "int", ["int", "int"], "mscdecl");
  const wAnyAt = new NativeCallback(function (x, y) {
    const r = fAnyAt(x, y);
    if (viewer >= 0 && r >= 0 && r !== viewer && tileHidden(x, y)) {
      note("anything_at", x, y, "owner=" + r);
      if (MODE === "filter") return -1;
    }
    return r;
  }, "int", ["int", "int"], "mscdecl");
  const wStackCheck = new NativeCallback(function (id, type, a3, a4, a5) {
    if (viewer >= 0 && id >= 0 && id < vehCount() && V(id).add(0x0E).readU8() !== viewer &&
        hiddenStack(id, viewer)) {
      note("stack_check", V(id).readS16(), V(id).add(2).readS16(), "veh=" + id + " type=" + type);
      if (MODE === "filter") return 0;
    }
    return fStackCheck(id, type, a3, a4, a5);
  }, "int", ["int", "int", "int", "int", "int"], "mscdecl");
  KEEP.push(wVehAt, wVehWho, wAnyAt, wStackCheck);

  // ---- re-point enemy_move's call sites (byte-checked; all-or-nothing) ---------------------------
  const plan = [["veh_at", wVehAt], ["veh_who", wVehWho], ["anything_at", wAnyAt],
                ["stack_check", wStackCheck]];
  let ok = true, total = 0;
  for (const [name] of plan)
    for (const s of SITES[name]) {
      const p = VA(s);
      const tgt = p.add(5).add(p.add(1).readS32());
      if (p.readU8() !== 0xE8 || !tgt.equals(VA(A[name]))) {
        ok = false;
        log("!! site " + s.toString(16) + " is not `call " + name + "` (op=" + p.readU8().toString(16) +
            " tgt=" + tgt + ") -- call-site filter NOT installed");
      }
      total++;
    }
  if (ok) {
    for (const [name, cb] of plan)
      for (const s of SITES[name]) {
        const p = VA(s);
        Memory.patchCode(p.add(1), 4, (code) => {
          code.writeS32(cb.sub(p.add(5)).toInt32());
        });
      }
    log("call sites re-pointed: " + total + " (mode " + MODE + ")");
  }

  // ---- order_veh: the AI bump ---------------------------------------------------------------------
  const fOrderVeh = new NativeFunction(VA(A.order_veh), "int", ["int", "int", "int"], "mscdecl");
  KEEP.push(fOrderVeh);
  const wOrderVeh = new NativeCallback(function (id, dir, a3) {
    let bump = -1, tx = 0, ty = 0, f = -1;
    if (id >= 0 && id < vehCount() && dir >= 0 && dir < 8) {
      f = V(id).add(0x0E).readU8();
      if (f > 0 && f < 8 && !isHuman(f)) {
        tx = V(id).readS16() + VA(A.DirDX).add(dir * 4).readS32();
        ty = V(id).add(2).readS16() + VA(A.DirDY).add(dir * 4).readS32();
        if ((VA(A.MapToggleFlat).readU32() & 1) === 0) {
          const w = VA(A.MapAreaX).readS32();
          if (tx < 0) tx += w; else if (tx >= w) tx -= w;
        }
        const sq = mapSq(tx, ty);
        if (sq !== null && (sq.add(8).readU32() & 3) === 2) {        // units, no base
          const v = fVehAt(tx, ty);
          if (v >= 0 && hiddenStack(v, f)) bump = v;
        }
      }
    }
    if (bump < 0) return fOrderVeh(id, dir, a3);

    stats.bump++;
    const before = "veh=" + id + " fac=" + f + " (" + V(id).readS16() + "," + V(id).add(2).readS16() +
                   ")->(" + tx + "," + ty + ") hidden veh=" + bump + " of fac=" +
                   V(bump).add(0x0E).readU8() + " order=" + V(id).add(0x11).readS8();
    if (MODE === "filter") {
      fSpotStack(bump, f);                 // discover the stack (sets VEH+0x27 + the tile bit)
      V(id).add(0x11).writeS8(0);          // clear the order, like the engine's human-only reveal path
      log("[filter] BUMP " + before + " -> revealed, move cancelled");
      return 0;
    }
    const n0 = vehCount();
    const r = fOrderVeh(id, dir, a3);
    const alive = vehCount() === n0;
    log("[probe] BUMP " + before + " -> vanilla ret=" + r + (alive ?
        " mover now (" + V(id).readS16() + "," + V(id).add(2).readS16() + ") order=" +
        V(id).add(0x11).readS8() : " (unit count changed " + n0 + "->" + vehCount() + ": combat)"));
    return r;
  }, "int", ["int", "int", "int"], "mscdecl");
  KEEP.push(wOrderVeh);
  Interceptor.replace(VA(A.order_veh), wOrderVeh);

  // ---- net carrier probe: server's NEXT-UPKEEP broadcast, msg 0x4303 p3/p4 (never fires in SP) ----
  Interceptor.attach(VA(A.message_data), {
    onEnter() {
      const sp = this.context.esp;
      if ((sp.add(4).readU32() & 0xFFFF) !== 0x4303) return;
      log("[net] send 0x4303 phase=" + sp.add(0x0C).readS32() + " turn=" + sp.add(0x10).readS32() +
          " p3=" + sp.add(0x14).readU32().toString(16) + " p4=" + sp.add(0x18).readU32().toString(16));
      if (MODE === "filter" && VA(A.NetIsServer).readS32() !== 0) {
        sp.add(0x14).writeU32(NET_BIT_AIVIS);
        sp.add(0x18).writeU32(NET_MAGIC);
      }
    },
  });
  Interceptor.attach(VA(A.process_message), {
    onEnter() {
      const msg = this.context.esp.add(4).readPointer();
      try {
        if (msg.readU16() !== 0x4303) return;
        log("[net] recv 0x4303 from=" + msg.add(4).readS32() + " phase=" + msg.add(0x10).readS32() +
            " p3=" + msg.add(0x18).readU32().toString(16) + " p4=" + msg.add(0x1C).readU32().toString(16));
      } catch (e) { /* not a message pointer */ }
    },
  });

  setInterval(() => {
    const s = JSON.stringify(stats);
    if (s !== lastStats) { lastStats = s; log("stats " + s); }
  }, 5000);
  log("installed: enemy_move viewer ctx, order_veh bump, net probes");
}
