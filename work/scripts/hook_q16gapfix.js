// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE (mutating) for the QUIT-class (type-16) option-row GAP.
//
// DEFECT (user, 4K): the two Quit buttons sit too close together.
// MEASURED (work/tests/frida_q16gap.log):
//     pristine g=16 : pitch 22 = rowH 19 + gap 3   drawn bar 20  -> visible gap 2
//     patched  g=25 : pitch 34 = rowH 31 + gap 3   drawn bar 31  -> visible gap 3
//     patched  g=40 : pitch 53 = rowH 50 + gap 3   drawn bar 50  -> visible gap 3  (want 5)
// [+0x44] is a constant 3 at every g -- it never scaled. The bar height already
// does (scale_px(20,g) == 31 and 50, matching the engine exactly).
//
// THE LAW (scaling_laws.py :: option_row_gap -- SL.optionRowGap here; do NOT
// re-derive it locally). The engine positions row i on a UNIFORM stride
//     pitch = [+0x68] + [+0x44]      and reserves content_h = pitch * count,
// so the PITCH is the quantity that must equal vanilla * g/16. Pin it, and let
// the gap absorb the rounding:
//     gap' = scale_px(22, g) - rowH68
// Scaling the gap directly (scale_px(2,g)) is the obvious move and is WRONG:
// bar height and gap round independently, so their sum leaves the faithful
// pitch at g = 18, 26, 34. See test_scaling_laws.py and WHY.md.
//
// At g=16 the calc still measures with Buffer_text_height (19), so
// gap' = 22 - 19 = 3 = the vanilla field value -- an algebraic native no-op.
// We nevertheless GATE on g>16, matching thunk_quit_rowpitch's own gate, so the
// native path executes literally untouched.
//
// WHERE. The calc (0x60d380, type-16 exclusive) writes the gap-dependent WIDTHS
// (0x60d6d4 -> [+0x64], 0x60d6e6 -> [+0x5c]) BEFORE it reaches the pitch at
// Site B (0x60d731). Writing the field here in onLeave therefore leaves those
// widths on their vanilla gap -- which is what we want, since thunk_q16_fill_width
// overwrites both at attach anyway. The bake will patch Site B for the same reason.
//
// Only the calc's ENTRY is attached (baked call-redirects at 0x60d641/0x60d658
// are static bytes, not Frida hooks -- no soft-kill pair). See
// feedback-frida-attach-branch-target.
//
// Run:  work\run-frida.bat hook_q16gapfix.js     (ESC -> Quit)  at 4K, 1600, 1920, 1024.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_q16gapfix.log";
globalThis.LOG_APPEND = true;
log("=== hook_q16gapfix.js (MUTATING prototype: type-16 option-row gap) ===");

if (typeof SL === "undefined") {
  throw new Error("scaling_laws.js prelude not loaded -- run via run-frida.bat, " +
                  "never re-inline the laws into a hook");
}

if (requireBase()) {
  const G       = 0x00668740;    // g_popup_scale_num (16..40)
  const A_CALC  = 0x0060D380;    // Dialog_type16_calc_dimensions
  const A_BACK  = 0x00405B20;    // Popup_on_dialog_item_back_draw (verification only)

  const VANILLA_PITCH = 22;      // pristine: text_height 19 + gap 3   (MEASURED)

  const gnow = () => ptr(VA(G)).readS32();

  Interceptor.attach(VA(A_CALC), {
    onEnter() { this.self = this.context.ecx; },
    onLeave() {
      try {
        const g = gnow();
        if (g <= 16) return;                               // native no-op, untouched

        const adj  = this.self.readPointer().add(8).readS32();   // vbase adjustor
        const b    = this.self.add(adj);
        const gapA = b.add(0x44), rowA = b.add(0x68),
              cntA = b.add(0x58), conA = b.add(0x60);

        const oldGap = gapA.readS32();
        const rowH   = rowA.readS32();
        const count  = cntA.readS32();
        if (rowH <= 0 || count <= 0) return;

        // STALE GUARD: only Site B (content = (rowH+gap)*count) is ours. Site A
        // (fixed-height mode, [+0x60] = [+0x30]) must be left alone.
        if (conA.readS32() !== (rowH + oldGap) * count) {
          log("skip: content60 != (rowH+gap)*count -- Site A / fixed-height mode");
          return;
        }

        const newGap = SL.optionRowGap(VANILLA_PITCH, rowH, g);
        gapA.writeS32(newGap);                       // draw loop reads this (0x60d8f3)
        conA.writeS32((rowH + newGap) * count);      // box reserve follows the pitch

        log("FIX g=" + g + " rowH=" + rowH + " count=" + count +
            " gap " + oldGap + " -> " + newGap +
            "  pitch " + (rowH + oldGap) + " -> " + (rowH + newGap) +
            "  (faithful pitch = " + SL.scalePx(VANILLA_PITCH, g) + ")" +
            "  content60 -> " + conA.readS32());
      } catch (e) { log("CALC onLeave error " + e); }
    }
  });

  // Verification: the rects the bars are actually drawn into.
  let prevTop = null;
  Interceptor.attach(VA(A_BACK), function () {
    try {
      const rp = this.context.esp.add(0x10).readPointer();
      if (rp.isNull()) return;
      const T = rp.add(4).readS32(), B = rp.add(0xc).readS32();
      const stride = (prevTop === null) ? null : T - prevTop;
      log("ROW top=" + T + " barH=" + (B - T) +
          (stride === null ? "" : " stride=" + stride +
                                  " VISIBLE_GAP=" + (stride - (B - T))));
      prevTop = T;
    } catch (e) {}
  });

  log("attached calc 0x60d380 (mutating) + back_draw 0x405b20 (observe). g=" + gnow());
}
