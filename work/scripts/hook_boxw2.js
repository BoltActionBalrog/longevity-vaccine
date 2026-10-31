"use strict";
// OBSERVER ONLY (2026-07-08) — box-width COMPONENT breakdown.
//
// Follow-up to hook_boxw.js, which proved box_w_pre grows by a different factor in
// every popup (x1.00 / x1.32 / x1.49 / x1.76 at g=40) because it mixes contributions
// that scale with g (text extents, bullet sprites) with native additive constants
// (pad / gap / min-width) that do not. thunk_scale_boxw then multiplies that mixture
// by a single tuned constant M(g) (x1.875 @4K) -> Quit +10%, Council +28% over
// vanilla x g/16.
//
// This hook dumps the individual contributions so the per-component law can be
// written instead of retuning the fudge. Dialog block base = popup + iv3 + 0x21A0
// (established: dialog+0x5c == the popup-relative +0x21fc that BasePop_calc reads).
//
// Run at 3840x2160, 1600x1200 and 1024x768 (all shortcuts append to one log).
// Open: in-game Quit, then the Planetary Council dialog. Writes nothing.

globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_boxw2.log";
log("=== hook_boxw2.js (observer, box-width component breakdown) started ===");

if (requireBase()) {
  const BASEPOP_CALC = 0x00603800;
  const THUNK_BOXW   = 0x00A0C300;
  const G_SCALE      = 0x00668740;

  const DLG = 0x21A0;          // dialog block base, popup+iv3 relative
  // dialog-relative offsets read by Dialog_type16_calc_dimensions
  const D = {
    0x20: "flags_byte",
    0x2c: "min_w      (popup +0x21cc init_w)",
    0x30: "fixed_h",
    0x34: "bullet_spr_w",
    0x40: "pad",
    0x44: "gap",
    0x4c: "ncols",
    0x54: "cols",
    0x58: "rows",
    0x5c: "WIDTH  (== popup +0x21fc)",
    0x60: "height (== popup +0x2200)",
    0x64: "col_w  (= gap + bullet + maxTextW)",
    0x68: "row_h",
    0x8c: "WIDTH2 (== popup +0x222c)",
    0x90: "height2(== popup +0x2230)",
  };

  const i32 = (p, off) => p.add(off).readS32();

  function label(p) {
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

  function iv3of(p) {
    try {
      const d = p.add(0x21d0).readPointer();
      return d.isNull() ? -1 : d.add(8).readS32();
    } catch (e) { return -1; }
  }

  function dump(p, tag) {
    const iv3 = iv3of(p);
    const g = VA(G_SCALE).readS32();
    log(`${tag} "${label(p)}"  g=${g}  iv3=${iv3}  dlg_type=${i32(p, 0x2350)}`);
    if (iv3 < 0) { log("   (no dialog)"); return; }
    const base = p.add(iv3 + DLG);
    for (const off of Object.keys(D).map(Number).sort((a, b) => a - b)) {
      let v;
      try { v = base.add(off).readS32(); } catch (e) { v = "??"; }
      log(`   dlg+0x${off.toString(16).padStart(2, "0")}  ${String(v).padStart(8)}   ${D[off]}`);
    }
    log(`   popup: box_w=${i32(p, 0x30bc)} content_w=${i32(p, 0x30d8)}` +
        ` padx=${i32(p, 0x30e0)} pady=${i32(p, 0x30e4)}` +
        ` marg=${i32(p, 0x30f0)}/${i32(p, 0x30f4)}` +
        ` marg_src=${i32(p, 0x21b0)}/${i32(p, 0x21b4)}` +
        ` flags=0x${(i32(p, 0x30a8) >>> 0).toString(16)}` +
        ` xpos=${i32(p, 0x30f8)}/${i32(p, 0x30fc)}`);
  }

  const seen = {};
  let pending = null;

  Interceptor.attach(VA(BASEPOP_CALC), {
    onEnter() {
      const p = ptr(this.context.ecx);
      this.p = p;
      const key = label(p);
      seen[key] = (seen[key] || 0) + 1;
      this.pass = seen[key];
      this.fresh = this.pass <= 2;          // Popup_calculate_dimensions calls this twice
      if (this.fresh) {
        log("\n---------------------------------------------------------------");
        dump(p, `[ENTER pass${this.pass}]`);
      }
      pending = this.fresh ? p : null;
    },
    onLeave() {
      if (this.fresh) dump(this.p, `[LEAVE pass${this.pass}]`);
      pending = null;
    },
  });

  try {
    Interceptor.attach(VA(THUNK_BOXW), {
      onEnter() {
        const p = ptr(this.context.esi);
        if (pending === null || !p.equals(pending)) return;
        log(`   [PRE-THUNK] box_w_pre=${i32(p, 0x30bc)}`);
      },
    });
  } catch (e) {
    log("thunk_scale_boxw absent: " + e);
  }

  log("hooks installed. Open the in-game Quit dialog, then the Planetary Council dialog.");
}
