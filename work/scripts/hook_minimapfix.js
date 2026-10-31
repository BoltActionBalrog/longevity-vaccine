// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE v2 fix for the minimap viewport-box vanishing on scroll/zoom/edge-pan.
// v1 defeated itself: forcing on_redraw from INSIDE the MapWin_draw_map interceptor made
// its nested draw_box call skip the draw_box interceptor (Frida per-thread reentrancy
// suppression), so the F1/F2 gate-bypass never ran for forced redraws -> box still gone.
//
// Diagnosis recap (frida_minimapbox.log): the white rect is drawn ONLY by WorldWin_draw_box
// @0x4C4630 (via WorldWin_on_redraw @0x4C3EC0), gated on
//   Vw(0x93347c)!=0 && F1(0x93345c)==0 && F2(0x933460)==0.
// F1/F2 are a "scroll-in-progress" suppressor (read ONLY by draw_box), nonzero mid-scroll,
// 0 only when settled; and during edge-scroll on_redraw doesn't fire at all -> box erased
// with no repaint.
//
// v2 fix:
//  (A) draw_box gate bypass for NATURAL (non-nested) calls: interceptor zeroes F1/F2 for the
//      duration of draw_box (save/restore; BaseWin readers unaffected).
//  (B) force a minimap redraw after each MAIN-map render (MapWin_draw_map) when the view
//      moved, and MANUALLY zero F1/F2 around that forced onRedraw (the nested draw_box
//      interceptor is suppressed, so we can't rely on (A) there). Reentrancy-guarded.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_minimapfix.log";
log("=== hook_minimapfix.js (prototype v2) started ===");
installAVHandler("minimapfix");

if (requireBase()) {
  const WW = VA(0x8E9F60);            // WorldWin object (static; passed as `this`)
  const onRedraw = new NativeFunction(VA(0x4C3EC0), 'void', ['pointer'], 'thiscall');
  const gF1 = VA(0x93345c), gF2 = VA(0x933460), gVw = VA(0x93347c);
  const gX  = VA(0x933454), gY = VA(0x933458);
  const gVw2 = VA(0x933480), gVw3 = VA(0x933484), gVh2 = VA(0x933488);
  const gMapW = VA(0x949870), gMapH = VA(0x949874);
  const gZn = VA(0x691E6C), gZd = VA(0x691E70);

  let inRedraw = false;
  let nForce = 0, nBoxNat = 0;
  const geomSeen = new Set();

  const zeroGate = () => { const a = gF1.readS32(), b = gF2.readS32();
                           if (a) gF1.writeS32(0); if (b) gF2.writeS32(0); return [a, b]; };
  const restoreGate = s => { if (s[0]) gF1.writeS32(s[0]); if (s[1]) gF2.writeS32(s[1]); };

  // (A) natural draw_box calls: bypass the transient gate + GEOM CAPTURE (dedup'd)
  Interceptor.attach(VA(0x4C4630), {
    onEnter() {
      this.g = zeroGate(); nBoxNat++;
      const Vx = gX.readS32(), Vy = gY.readS32(), Vw = gVw.readS32();
      const Vw2 = gVw2.readS32(), Vw3 = gVw3.readS32(), Vh2 = gVh2.readS32();
      const mapW = gMapW.readS32(), mapH = gMapH.readS32();
      const x2t = Vw3 + Vx + Vw, y2t = Vh2 + Vw2 + Vy;
      const key = Vw + "|" + Vw3 + "|" + gZn.readS32();   // distinct zoom states
      if (!geomSeen.has(key)) {
        geomSeen.add(key);
        log("GEOM Vx=" + Vx + " Vy=" + Vy + " Vw=" + Vw + " Vw2=" + Vw2 + " Vw3=" + Vw3 +
            " Vh2=" + Vh2 + " | x2tile=" + x2t + " y2tile=" + y2t +
            " widthTiles=" + (x2t - Vx) + " | mapW=" + mapW + " mapH=" + mapH +
            " zoom=" + gZn.readS32() + "/" + gZd.readS32() +
            (x2t - Vx >= mapW ? "  <<< SPANS-FULL-WIDTH" : ""));
      }
    },
    onLeave() { restoreGate(this.g); }
  });

  // (B) after each main-map render, force a minimap redraw if the view moved
  let lastX = null, lastY = null;
  Interceptor.attach(VA(0x46A550), {
    onLeave() {
      if (inRedraw) return;                        // nested (minimap's own content render)
      const x = gX.readS32(), y = gY.readS32();
      if (x === lastX && y === lastY) return;      // view unchanged
      lastX = x; lastY = y;
      const g = zeroGate();                         // gate down for the whole forced redraw
      inRedraw = true;
      try { onRedraw(WW); } finally { inRedraw = false; restoreGate(g); }
      nForce++;
    }
  });

  setInterval(() => {
    log("tally: forced=" + nForce + " boxNatural=" + nBoxNat +
        " view=(" + gX.readS32() + "," + gY.readS32() + ") Vw=" + gVw.readS32() +
        " F1=" + gF1.readS32() + " F2=" + gF2.readS32());
  }, 2000);

  log("prototype v2 armed");
}
