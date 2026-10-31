"use strict";
// Quit-modal BOX-HEIGHT composition probe.
// FINDING (1024-native vs 4K screenshot alignment, 2026-07-03): rows/band/art all placed
// faithfully, OK bar bottom-anchored (OK_bottom == box_bottom - B_margin exactly), but the
// BOX is ~24px TALLER than faithful @4K (native band->window-bottom 282 -> faithful 705,
// actual ~729) -> the excess pools between the rows and OK (gap 46 vs faithful 20).
// 24 == 16*(g-16)/16 @g40 -> prime suspect: a native 16 (2x8 pad?) scaled where vanilla
// keeps it native. This probe dumps the popup reserve fields + every GraphicWin_init during
// the Quit popup so the composition can be reconstructed exactly.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_quit_boxh.log";
log("=== frida_quit_boxh.js started ===");

if (requireBase()) {
  const G_SCALE = 0x668740;                  // g_popup_scale_num
  const BASEPOP_CALC = 0x00603800;           // BasePop_calculate_dimensions (thiscall ecx=popup)
  const TYPE16_CALC = 0x0060D380;            // Dialog_type16_calc_dimensions
  const TYPE16_ATTACH = 0x0060D1F0;          // Dialog_type16_attach
  const GWIN_INIT = 0x005D4EF0;              // GraphicWin_init(this; x,y,w,h,...)

  function popupId(p) {
    for (const off of [0xa48, 0x2188]) {
      try {
        const sp = p.add(off).readPointer();
        if (!sp.isNull()) {
          const s = sp.readAnsiString(40);
          if (s && s.trim().length) return s.trim();
        }
      } catch (e) {}
    }
    return "?";
  }

  function dumpPopup(tag, t) {
    const f = (o) => t.add(o).readS32();
    log("[" + tag + "] this=" + t + " id='" + popupId(t) + "' g=" + VA(G_SCALE).readS32());
    log("  box w[30bc]=" + f(0x30bc) + " h[30c0]=" + f(0x30c0) +
        " content[30c4]=" + f(0x30c4) + " [30c8]=" + f(0x30c8) +
        " [30cc]=" + f(0x30cc) + " [30d0]=" + f(0x30d0));
    log("  [30d4]=" + f(0x30d4) + " [30d8]=" + f(0x30d8) + " [30dc]=" + f(0x30dc) +
        " padX[30e0]=" + f(0x30e0) + " [30e4]=" + f(0x30e4) +
        " header[30e8]=" + f(0x30e8) + " footer[30ec]=" + f(0x30ec) +
        " [30f0]=" + f(0x30f0) + " [30f4]=" + f(0x30f4));
    log("  margins L[21b0]=" + f(0x21b0) + " R[21b4]=" + f(0x21b4) +
        " T[21b8]=" + f(0x21b8) + " B[21bc]=" + f(0x21bc) + " [21c8]=" + f(0x21c8));
    log("  art-x chain [30b0]=" + f(0x30b0) + " [30b4]=" + f(0x30b4) + " [30b8]=" + f(0x30b8) +
        " [21c0]=" + f(0x21c0) + " [21c4]=" + f(0x21c4) + " art*[2144]=" + f(0x2144));
  }

  let quitPopup = null;

  Interceptor.attach(VA(BASEPOP_CALC), {
    onEnter() { this.t = this.context.ecx; },
    onLeave() {
      const id = popupId(this.t);
      if (id.indexOf("ALPHA CENTAURI") < 0 && id.indexOf("quit") < 0) return;
      quitPopup = this.t;
      dumpPopup("basepop_calc:out", this.t);
    }
  });

  // type-16 calc: ecx = the Dialog-owning window; dump the Dialog row fields on leave.
  Interceptor.attach(VA(TYPE16_CALC), {
    onEnter() { this.w = this.context.ecx; },
    onLeave() {
      const w = this.w;
      try {
        const vt = w.readPointer();
        const adj = vt.add(8).readPointer().toInt32();   // adjustor slot (D = w + adj pattern)
        log("[t16calc:out] win=" + w + " vtbl=" + vt + " adj8=" + adj);
      } catch (e) {}
      // known working offsets from the fillwidth work: D = win+0x12c; engine reads w at [win+0x188]
      const r = (o) => { try { return w.add(o).readS32(); } catch (e) { return "?"; } };
      log("  D[+0x44]gap=" + r(0x12c + 0x44) + " D[+0x5c]=" + r(0x12c + 0x5c) +
          " D[+0x60]total=" + r(0x12c + 0x60) + " D[+0x64]=" + r(0x12c + 0x64) +
          " D[+0x68]pitch=" + r(0x12c + 0x68) + " D[+0xcc]count=" + r(0x12c + 0xcc));
    }
  });

  // every window created during the type-16 attach: rows + OK geometry at the source
  let inAttach = false;
  Interceptor.attach(VA(TYPE16_ATTACH), {
    onEnter() { inAttach = true; log("[t16attach] enter"); },
    onLeave() { inAttach = false; log("[t16attach] leave"); }
  });
  Interceptor.attach(VA(GWIN_INIT), {
    onEnter(args) {
      // rows/OK init from popup/dialog code (0x600000..0x615000) or inside the attach
      const ret = this.returnAddress.sub(VA(0x400000)).toUInt32() + 0x400000;
      if (!inAttach && (ret < 0x600000 || ret > 0x615000)) return;
      log("[gwin_init] this=" + this.context.ecx +
          " x=" + args[0].toInt32() + " y=" + args[1].toInt32() +
          " w=" + args[2].toInt32() + " h=" + args[3].toInt32() +
          " ret=0x" + ret.toString(16) + (inAttach ? " (attach)" : ""));
    }
  });

  // art-sprite draw (image left-flush law): native default [popup+0x3168] = sprite_draw_func
  // (0x404860, draws at x-5/y-6 1:1). args: sprite, window, res, x, y.
  Interceptor.attach(VA(0x00404860), {
    onEnter(args) {
      const sp = args[0];
      let dims = "?";
      try { dims = sp.add(0x10).readS32() + "x" + sp.add(0x14).readS32(); } catch (e) {}
      log("[artdraw] sprite=" + sp + " (" + dims + ") win=" + args[1] +
          " x=" + args[3].toInt32() + " y=" + args[4].toInt32() +
          " -> frame at (" + (args[3].toInt32() - 5) + "," + (args[4].toInt32() - 6) + ")");
    }
  });

  log("hooks armed (basepop_calc dump + t16 calc/attach + gwin_init census + artdraw)");
}
