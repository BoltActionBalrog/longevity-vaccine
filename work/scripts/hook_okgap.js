"use strict";
// OBSERVER (v3, 2026-07-03): the OK-gap law (A/B) + Quit art flush laws (C) are BAKED
// into build 95b68156 (groups popup_button_vcenter v2 / popup_btnrow_center v2 /
// popup_art_align, art-y law v5 + fieldpads v3 band-anchored field top: T =
// g_band_bottom + 2*(p3+Delta) -> title/field drawn margin = p3 exactly). This hook no longer WRITES anything -- it logs the
// baked engine's numbers against the law predictions so a Frida run doubles as a
// Layer-2 numeric check. (The old mutating prototype would DOUBLE-APPLY on the baked
// exe -- part B subtracted a footer/4 the baked thunk no longer adds. Do not resurrect.)
//
// Laws (pristine-1024-trace + user-approved prototype, all identity at g=16):
//   A) [30e4] = popup_scale(3*[21c4]/2)          (15 @4K, 6 native)
//   B) OK-bar gap above the rows = floor(9g/16)  (22 @4K, 14 @g25, 12 @g22, 9 native)
//   C) art x = bandL + 5 + floor(g/16)           (art frame flush with title outer stroke)
//      art y = fieldT - floor(3g/16) - floor((g-16)/8) + 6   (v5: the Delta term is the
//      frame thunk's outward stroke grow -- 3 @4K / 1 @g25 / 0 @g22, the v4 residual)
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_okgap.log";
log("=== hook_okgap.js (observer v2, baked-build check) started ===");

if (requireBase()) {
  const G_SCALE = 0x668740;            // g_popup_scale_num
  const VPAD_AFTER = 0x00603974;       // NOP pad after the baked [esi+0x30e4] store
  const VCENTER_RESUME = 0x00602C51;   // resume point after thunk_btn_vcenter v2
  const BASEPOP_CALC = 0x00603800;     // BasePop_calculate_dimensions (thiscall ecx=popup)
  const TYPE16_ATTACH = 0x0060D1F0;    // Dialog_type16_attach
  const GWIN_INIT = 0x005D4EF0;        // GraphicWin_init(this; x,y,w,h,...)
  const G_BAND_LEFT = 0x00A0E700;      // g_band_left (relocated with artalign v5)
  const G_FIELD_ANCHOR = 0x00A0E704;   // g_field_anchor
  const G_BAND_POPUP = 0x00A0E708;     // g_band_popup (key; consumed by thunk_popup_artalign)

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

  // A) verify the baked [30e4] equals popup_scale(3*[21c4]/2)
  Interceptor.attach(VA(VPAD_AFTER), function () {
    const esi = this.context.esi;
    let g = VA(G_SCALE).readS32();
    if (g < 16) g = 16;
    const got = esi.add(0x30e4).readS32();
    const want = (((3 * esi.add(0x21c4).readS32()) >> 1) * g) >> 4;
    log("[vpad] [30e4]=" + got + " want=" + want + (got === want ? " OK" : " *** MISMATCH") +
        " (g=" + g + ")");
  });

  // B) log the baked button-row Y (thunk_btn_vcenter v2 already applied +3g/16-3)
  Interceptor.attach(VA(VCENTER_RESUME), function () {
    const g = VA(G_SCALE).readS32();
    const y = this.context.esp.add(0x14).readS32();
    log("[btnrow] y=" + y + " (baked; g=" + g + ")");
  });

  // ---- numbers-only census ----
  Interceptor.attach(VA(BASEPOP_CALC), {
    onEnter() { this.t = this.context.ecx; },
    onLeave() {
      const t = this.t, f = (o) => t.add(o).readS32();
      log("[calc:out] this=" + t + " id='" + popupId(t) + "'" +
          " box_h[30c0]=" + f(0x30c0) + " [30d0]=" + f(0x30d0) + " [30d4]=" + f(0x30d4) +
          " [30e4]=" + f(0x30e4) + " footer[30ec]=" + f(0x30ec) + " [30f0]=" + f(0x30f0));
    }
  });

  // C) log the art draw AFTER thunk_popup_artalign already adjusted x/y (we attach on
  // thunk_sprite_draw 0x6688B0, artalign's tail target) + the law expectation from the
  // baked globals. NOTE: by the time this fires the key was consumed; the stash globals
  // still hold the last values, which is exactly what the laws need for the check.
  Interceptor.attach(VA(0x006688B0), {
    onEnter(args) {
      const sp = args[0];
      let dims = "?";
      try { dims = sp.add(0x10).readS32() + "x" + sp.add(0x14).readS32(); } catch (e) {}
      const g = VA(G_SCALE).readS32();
      const x = args[3].toInt32(), y = args[4].toInt32();
      let expect = "";
      if (g > 16) {
        const ex = VA(G_BAND_LEFT).readS32() + 5 + (g >> 4);
        const ey = VA(G_FIELD_ANCHOR).readS32() - ((3 * g) >> 4) - ((g - 16) >> 3) + 6;
        expect = " want x=" + ex + " y=" + ey +
                 (x === ex && y === ey ? " OK" : " (unkeyed popup or *** MISMATCH)");
      }
      log("[artdraw] sprite=" + sp + " (" + dims + ") win=" + args[1] +
          " x=" + x + " y=" + y + " -> frame at (" + (x - 5) + "," + (y - 6) + ")" +
          expect + " key=" + VA(G_BAND_POPUP).readPointer());
    }
  });

  let inAttach = false;
  Interceptor.attach(VA(TYPE16_ATTACH), {
    onEnter() { inAttach = true; },
    onLeave() { inAttach = false; }
  });
  Interceptor.attach(VA(GWIN_INIT), {
    onEnter(args) {
      const ret = this.returnAddress.sub(VA(0x400000)).toUInt32() + 0x400000;
      if (!inAttach && (ret < 0x600000 || ret > 0x615000)) return;
      log("[gwin_init] this=" + this.context.ecx +
          " x=" + args[0].toInt32() + " y=" + args[1].toInt32() +
          " w=" + args[2].toInt32() + " h=" + args[3].toInt32() +
          " ret=0x" + ret.toString(16) + (inAttach ? " (attach)" : ""));
    }
  });

  log("observer hooks armed (no writes; verifies baked laws A/B/C)");
}
