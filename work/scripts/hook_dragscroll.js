"use strict";
// hook_dragscroll.js -- OBSERVER: why PRACX's drag map scroll (right OR middle button, per [UIMod] MapDragButton)
// feels delayed. PRACX's drag (prax.dll PRACXCheckScroll) spins its own loop:
//   PRACXGetCursorPos -> dx = last - p -> DoScroll: MapWin_draw_map (0x46A550; on the patched exe detoured by
//   thunk_minimap_force, which also runs WorldWin_on_redraw 0x4C3EC0) -> Win_update_screen 0x5F7320 ->
//   Win_flip_rect 0x5EFD20 (NOT hooked: movie.cpp pokes its entry) -> back to PRACXGetCursorPos.
// A STEP = Win_update_screen called from prax.dll (DoScroll calls it only when the view actually moved). Each step
// splits into: render = last prax cursor read -> update entry (map render + minimap force), update = inside
// Win_update_screen, flip = update exit -> next prax cursor read (Win_flip_rect = the present). Per drag it logs
// those (avg/max), the step rate, how far the pointer travelled per step (= how far the map trails it), and the
// delay from the press / first move to the first step. v1 counted every prax cursor read as a step (PRACX polls
// the cursor when idle and spins while a held drag is still): useless.
const STAMP = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_dragscroll_" + STAMP + ".log";
log("=== hook_dragscroll.js v4 started (per-pass profile + every render classified by trigger) ===");
installAVHandler("dragscroll");
if (requireBase()) {
  const main = Process.enumerateModules()[0];
  log("exe: " + main.name + " (" + main.path + ")");
  const k32 = Process.getModuleByName("kernel32.dll");
  const QPC = new NativeFunction(k32.getExportByName("QueryPerformanceCounter"), "int", ["pointer"]);
  const QPF = new NativeFunction(k32.getExportByName("QueryPerformanceFrequency"), "int", ["pointer"]);
  const qbuf = Memory.alloc(8);                       // module-lifetime (kept referenced: not GC-freed)
  QPF(qbuf);
  const freq = qbuf.readU64().toNumber();
  function ms() { QPC(qbuf); return qbuf.readU64().toNumber() * 1000 / freq; }

  const user32 = Process.getModuleByName("user32.dll");
  let prax = null;
  function inPrax(ra) {
    if (!prax) prax = Process.findModuleByName("prax.dll");
    return prax !== null && ra.compare(prax.base) >= 0 && ra.compare(prax.base.add(prax.size)) < 0;
  }
  function stat() { return { n: 0, sum: 0, max: 0 }; }
  function add(s, v) { s.n++; s.sum += v; if (v > s.max) s.max = v; }
  function fmt(s) { return s.n ? (s.sum / s.n).toFixed(1) + "/" + s.max.toFixed(1) : "-"; }

  let drag = null;                 // the drag being measured
  let tCursor = -1, cx = 0, cy = 0; // last prax cursor read (time + point)
  let tUpdEnd = -1;                 // end of the last step's Win_update_screen (awaiting the flip)
  let tPress = -1, tFirstMove = -1, pressBtn = "";
  function flush(reason) {
    if (!drag) return;
    const d = drag; drag = null;
    if (d.steps < 2) return;
    const span = d.tLast - d.tFirst;
    log("DRAG " + pressBtnOf(d) + "(" + reason + ") " + span.toFixed(0) + " ms, " + d.steps + " steps = " +
        (d.steps * 1000 / Math.max(span, 1)).toFixed(1) + " steps/s | ms avg/max: interval " + fmt(d.interval) +
        ", render " + fmt(d.render) + " (of which minimap " + fmt(d.mm) + "), update " + fmt(d.update) +
        ", flip " + fmt(d.flip) + " | pointer travel per step " + fmt(d.travel) + " px" +
        (d.pressToStep >= 0 ? " | press -> first step " + d.pressToStep.toFixed(0) + " ms" : "") +
        (d.moveToStep >= 0 ? ", first move -> first step " + d.moveToStep.toFixed(0) + " ms" : ""));
    log("    per-step pass ms avg/max: " + PASSES.map(([, n]) => n + " " + (d.pass[n] ? fmt(d.pass[n]) : "-")).join(", "));
  }
  function pressBtnOf(d) { return d.btn ? d.btn + " " : ""; }

  Interceptor.attach(user32.getExportByName("GetCursorPos"), {
    onEnter(args) { this.mine = inPrax(this.returnAddress); this.p = args[0]; },
    onLeave() {
      if (!this.mine) return;
      const t = ms();
      if (tUpdEnd >= 0 && drag) { add(drag.flip, t - tUpdEnd); }
      tUpdEnd = -1;
      tCursor = t;
      cx = this.p.readS32(); cy = this.p.add(4).readS32();
      for (const [, name] of PASSES) passInStep[name] = 0;     // count only what runs inside a step's render
      mmInStep = 0;
    }
  });

  let inUpdate = false, mmInStep = 0;
  // the render's passes (plain entries on both exes; none patched by us; gen_map's prologue is byte-CHECKED by the
  // DLL, hence its deferred attach below). Inclusive times, summed per
  // step: gen_map contains the others, so read them as shares of gen_map, not as a sum.
  const PASSES = [[0x469CA0, "gen_map"], [0x4632D0, "terrain"], [0x4688E0, "overlays"], [0x466CA0, "vehicles"],
                  [0x467DE0, "base_names"], [0x469720, "legend"], [0x4698D0, "wars"], [0x5DFF00, "buf_copy"]];
  const passInStep = {};
  const passInRender = {};        // the same passes, per gen_map call (every render, not just drag steps)
  for (const [va, name] of PASSES) {
    passInStep[name] = 0; passInRender[name] = 0;
    if (name === "gen_map") continue;          // gen_map gets its own render logger below
    Interceptor.attach(VA(va), {
      onEnter() { this.t = ms(); },
      onLeave() { const d = ms() - this.t; passInStep[name] += d; passInRender[name] += d; }
    });
  }
  // every render (MapWin_gen_map 0x469CA0, called by MapWin_draw_map), classified by what triggered it: a frame in
  // prax.dll = PRACX's scroll loop (drag if a drag button is down, else edge scroll); otherwise the game's own
  // movement (keyboard, recentre, click) with its caller chain. Logs each non-drag render; drag renders are
  // summarised per drag above, plus a per-render line only for the first 3 of each drag.
  const CON = VA(0x9156B0);
  let btnDown = false, dragRenderLines = 0;
  const kinds = {};
  // DEFERRED: uimod.dll's mapscroll feature memcmps gen_map's 6-byte prologue in its init-time Bind() and disables
  // itself when the check fails -- a Frida jmp planted here at spawn made every earlier profile measure PRACX's
  // stock full redraw instead of the DLL's strips (see memory feedback_frida_hook_vs_dll_bytecheck). The entry is
  // attached from the first Win_update_screen call, which is after every DLL feature has bound. Attaching inside
  // the prologue instead is NOT an option: onLeave swaps the return slot at [esp], which mid-prologue is a local.
  let genMapAttached = false;
  function attachGenMap() {
    if (genMapAttached) return;
    genMapAttached = true;
    log("gen_map hook attached (deferred past uimod.dll's byte checks)");
    Interceptor.attach(VA(0x469CA0), {
    onEnter() {
      this.t = ms();
      for (const [, n] of PASSES) passInRender[n] = 0;
      const bt = Thread.backtrace(this.context, Backtracer.FUZZY).slice(0, 8);
      const viaPrax = bt.some(a => inPrax(a));
      this.kind = viaPrax ? (btnDown ? "DRAG" : "EDGE") : "GAME";
      this.chain = viaPrax ? "" : " via " + bt.slice(0, 5).map(a => where(a)).join(" < ");
      this.off = CON.add(0x1DDAC).readS32() + "," + CON.add(0x1DDB0).readS32();
      this.ctr = CON.add(0x1DD9C).readS32() + "," + CON.add(0x1DDA0).readS32();
    },
    onLeave() {
      const d = ms() - this.t;
      passInStep.gen_map += d;
      const k = kinds[this.kind] || (kinds[this.kind] = stat());
      add(k, d);
      if (this.kind === "DRAG" && dragRenderLines >= 3) return;
      if (this.kind === "DRAG") dragRenderLines++;
      log("  RENDER " + this.kind + " " + d.toFixed(1) + " ms (terrain " + passInRender.terrain.toFixed(1) +
          ", units+bases " + passInRender.vehicles.toFixed(1) + ", names " + passInRender.base_names.toFixed(1) +
          ") centre " + this.ctr + " pixel offset " + this.off + this.chain);
    }
    });
  }
  setInterval(function () {
    const ks = Object.keys(kinds);
    if (!ks.length) return;
    log("RENDER TOTALS ms avg/max: " + ks.map(k => k + " x" + kinds[k].n + " " + fmt(kinds[k])).join(" | "));
    for (const k of ks) delete kinds[k];
  }, 5000);
  function where(a) {
    const m = Process.findModuleByAddress(a);
    return m ? m.name + "+0x" + a.sub(m.base).toString(16) : a.toString();
  }
  Interceptor.attach(VA(0x4C3EC0), {      // WorldWin_on_redraw (thunk_minimap_force runs it on each main render)
    onEnter() { this.t = ms(); },
    onLeave() { mmInStep += ms() - this.t; }
  });
  Interceptor.attach(VA(0x5F7320), {      // Win_update_screen
    onEnter() {
      attachGenMap();                       // first screen update: every DLL feature has bound by now
      this.mine = inPrax(this.returnAddress);
      if (!this.mine) return;
      const t = ms();
      if (drag && t - drag.tLast > 400) flush("gap");
      if (!drag) {
        drag = { tFirst: t, tLast: t, steps: 0, btn: pressBtn, interval: stat(), render: stat(), mm: stat(), pass: {},
                 update: stat(), flip: stat(), travel: stat(), px: null, py: null,
                 pressToStep: tPress >= 0 ? t - tPress : -1, moveToStep: tFirstMove >= 0 ? t - tFirstMove : -1 };
        tPress = -1; tFirstMove = -1;
      } else {
        add(drag.interval, t - drag.tLast);
      }
      if (tCursor >= 0) add(drag.render, t - tCursor);
      add(drag.mm, mmInStep);
      mmInStep = 0;
      for (const [, name] of PASSES) {
        if (!drag.pass[name]) drag.pass[name] = stat();
        add(drag.pass[name], passInStep[name]);
        passInStep[name] = 0;
      }
      if (drag.px !== null) add(drag.travel, Math.hypot(cx - drag.px, cy - drag.py));
      drag.px = cx; drag.py = cy;
      drag.tLast = t;
      drag.steps++;
      this.t = t;
    },
    onLeave() {
      if (!this.mine || !drag) return;
      const t = ms();
      add(drag.update, t - this.t);
      tUpdEnd = t;
    }
  });

  const DOWN = { 0x204: "right", 0x207: "middle" }, UP = { 0x205: 1, 0x208: 1 };
  for (const name of ["DispatchMessageA", "DispatchMessageW"]) {
    Interceptor.attach(user32.getExportByName(name), {
      onEnter(args) {
        const msg = args[0].add(4).readU32();
        if (DOWN[msg]) { tPress = ms(); tFirstMove = -1; pressBtn = DOWN[msg]; mmInStep = 0; btnDown = true; dragRenderLines = 0; }
        else if (UP[msg]) { flush("release"); tPress = -1; tFirstMove = -1; btnDown = false; }
        else if (msg === 0x200 && tPress >= 0 && tFirstMove < 0) tFirstMove = ms();
      }
    });
  }
  setInterval(function () { if (drag && ms() - drag.tLast > 400) flush("idle"); }, 500);
  log("hooks installed (prax.dll " + (Process.findModuleByName("prax.dll") ? "loaded" : "not yet loaded") + ")");
}
