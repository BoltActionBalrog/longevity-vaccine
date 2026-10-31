"use strict";
// Minimap viewport-box diagnosis. The white rect on the minimap is drawn ONLY by
// WorldWin_draw_box @0x4C4630, reachable ONLY from WorldWin_on_redraw @0x4C3EC0.
// Bug: the rect disappears / stops updating when the map is scrolled/zoomed/edge-panned.
// This hook answers: during a scroll, does on_redraw fire? and does draw_box's gating
// condition (Vw!=0 && F1==0 && F2==0) still pass? -> "freeze" (no redraw) vs "disappear"
// (redraw fires but condition fails / box drawn off-window).
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_minimapbox.log";
log("=== hook_minimapbox.js started ===");
installAVHandler("minimapbox");

if (requireBase()) {
  const OFF_FLAGS = 0x239bc;      // WorldWin dirty flags
  const OFF_OX = 0x239c4, OFF_OY = 0x239c8;   // center offsets (0 in stretch branch)
  const OFF_WW = 0x4c4, OFF_WH = 0x4c8;        // window client w / h(neg)

  const gVw = VA(0x93347c);   // view width  (draw condition: != 0)
  const gF1 = VA(0x93345c);   // suppress flag 1 (draw condition: == 0)
  const gF2 = VA(0x933460);   // suppress flag 2 (draw condition: == 0)
  const gX  = VA(0x933454);   // view left tile
  const gY  = VA(0x933458);   // view top tile
  const gVw2= VA(0x933480);
  const gVw3= VA(0x933484);
  const gVh2= VA(0x933488);

  const rd = p => { try { return p.readS32(); } catch (e) { return "?"; } };
  const cond = () => (rd(gVw) !== 0 && rd(gF1) === 0 && rd(gF2) === 0);
  const gstate = () =>
    "Vw=" + rd(gVw) + " F1=" + rd(gF1) + " F2=" + rd(gF2) +
    " view=(" + rd(gX) + "," + rd(gY) + ") Vw2=" + rd(gVw2) +
    " Vw3=" + rd(gVw3) + " Vh2=" + rd(gVh2);

  let nRedraw = 0, nDrawPass = 0, nDrawFail = 0;
  let lastWin = "";

  // --- WorldWin_on_redraw: count + snapshot the object's window dims/flags ---
  Interceptor.attach(VA(0x4C3EC0), {
    onEnter() {
      nRedraw++;
      const self = this.context.ecx;
      let win = "?";
      try {
        win = "flags=0x" + (self.add(OFF_FLAGS).readU32().toString(16)) +
              " win=" + self.add(OFF_WW).readS32() + "x" + (-self.add(OFF_WH).readS32()) +
              " off=(" + self.add(OFF_OX).readS32() + "," + self.add(OFF_OY).readS32() + ")";
      } catch (e) {}
      lastWin = win;
    }
  });

  // --- WorldWin_draw_box: does it draw? ---
  Interceptor.attach(VA(0x4C4630), {
    onEnter() {
      const ok = cond();
      if (ok) nDrawPass++; else nDrawFail++;
    }
  });

  // --- poll the view rect; log when it MOVES, with redraw/draw tallies since last move ---
  let lx = rd(gX), ly = rd(gY), lVw = rd(gVw), lF1 = rd(gF1), lF2 = rd(gF2);
  log("startup " + gstate());
  setInterval(() => {
    const x = rd(gX), y = rd(gY), vw = rd(gVw), f1 = rd(gF1), f2 = rd(gF2);
    const moved = (x !== lx || y !== ly);
    const condChanged = (vw !== lVw || f1 !== lF1 || f2 !== lF2);
    if (moved || condChanged) {
      log((moved ? "VIEW-MOVED" : "COND-CHANGED") +
          " -> " + gstate() +
          " | since-last: redraw=" + nRedraw + " drawPass=" + nDrawPass +
          " drawFail=" + nDrawFail + " | " + lastWin);
      nRedraw = 0; nDrawPass = 0; nDrawFail = 0;
      lx = x; ly = y; lVw = vw; lF1 = f1; lF2 = f2;
    }
  }, 100);
}
