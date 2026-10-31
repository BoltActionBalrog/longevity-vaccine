// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE LEVER v2 (2026-07-12) — type-1 checkbox popup box width, v4 law preview.
//
// Fixes the Customize Game Rules over-widening (box 2280 vs faithful 1705 @4K).
// Root cause (frida_boxw2.log 2026-07-12): for dlg_type==1 popups the measured
// width d5c [+iv3+0x222c] = max(#xs, item text at the CURRENT font) — MIXED
// space once our fonts scale — and baked thunk_scale_boxw v3 rescales it
// wholesale ×g/16, double-scaling the text term.
//
// LAW: scaling_laws.py::itemlist_box_width (source of truth; the BAKE ports it
// exactly, comparing in device space inside the thunk).
//
// v1 LESSON (user screenshot 20260712-110320): rewriting [+0x30bc] at
// BasePop_calc onLeave is TOO LATE — the #button row is positioned INSIDE
// BasePop_calculate_dimensions from box_w, and this window is right-anchored
// (#x -5), so the late narrowing clipped "Standard Rules" off the left edge
// while OK/CANCEL kept their old screen x. The in-thunk bake cannot have this
// ordering problem (thunk runs before the button layout), but the prototype
// must prove the full look, so v2 corrects the INPUT instead:
//
//   at Dialog_dims_dispatch (0x6132A0, entry byte-verified clean) onLeave,
//   for the gated regime, d5c := max(xs, ceil(d5c*16/g))  — the native-
//   equivalent measure. The baked v3 then computes (max(cw,tw)+trim)*g/16
//   from a native tw, box comes out lawful, and buttons/rows lay out from it.
//
// ceil-descale is a PROTOTYPE approximation (±1 native px when the text term
// dominates); the bake compares in device space and is exact. Idempotent:
// dispatch re-measures d5c from the font on every calc pass, so the rewrite
// always starts from a fresh engine value (no compounding).
//
// Gates: g>16, dlg_type[+0x2350]==1, no art [+0x2144]==0, d5c!=0, and only
// while inside BasePop_calculate_dimensions (pending popup, stashed at entry).
//
// RUN at 4K + 1920 + 1600 + 1024: GAME RULES -> Customize Rules. Expect the
// box flush around rows AND the full three-button row (Standard Rules | OK |
// CANCEL) inside it; 1024 byte-identical. Quit/Difficulty must log [skip].

globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_rulesboxw.log";
log("=== hook_rulesboxw.js v2 (type-1 box width; input-side lever at dims dispatch) ===");

if (requireBase()) {
  const BASEPOP_CALC = 0x00603800;
  const DIMS_DISPATCH = 0x006132A0;
  const THUNK_BOXW   = 0x00A0C300;   // presence gate: pristine exe -> observe only
  const G_SCALE      = 0x00668740;

  const i32 = (p, off) => p.add(off).readS32();

  let thunkPresent = false;
  try { VA(THUNK_BOXW).readU8(); thunkPresent = true; } catch (e) {}
  if (!thunkPresent) {
    log("thunk_scale_boxw absent (pristine exe?) -> OBSERVER ONLY, no writes");
  }

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

  let pending = null;   // popup ptr while inside BasePop_calculate_dimensions

  Interceptor.attach(VA(BASEPOP_CALC), {
    onEnter() {
      this.p = ptr(this.context.ecx);
      pending = this.p;
    },
    onLeave() {
      const p = this.p, g = VA(G_SCALE).readS32();
      const iv3 = iv3of(p);
      const box = i32(p, 0x30bc);
      const d5c = iv3 >= 0 ? i32(p, iv3 + 0x222c) : -1;
      const xs  = iv3 >= 0 ? i32(p, iv3 + 0x21fc) : -1;
      log(`[calc-done] "${label(p)}" g=${g} type=${i32(p, 0x2350)} xs=${xs} d5c=${d5c} box_w=${box}`);
      pending = null;
    },
  });

  Interceptor.attach(VA(DIMS_DISPATCH), {
    onLeave() {
      const p = pending;
      if (p === null) return;
      const g = VA(G_SCALE).readS32();
      const type = i32(p, 0x2350);
      const art = i32(p, 0x2144);
      const iv3 = iv3of(p);
      if (iv3 < 0) return;
      const d5c = i32(p, iv3 + 0x222c);
      const xs  = i32(p, iv3 + 0x21fc);

      if (g <= 16 || type !== 1 || d5c === 0 || art !== 0) {
        log(`[skip] "${label(p)}" g=${g} type=${type} d5c=${d5c} art=${art !== 0}`);
        return;
      }
      // native-equivalent measure: max(xs, descaled device text)
      const nat = Math.max(xs, Math.ceil((d5c * 16) / g));
      if (!thunkPresent || nat === d5c) {
        log(`[observe] "${label(p)}" g=${g} xs=${xs} d5c=${d5c} nat=${nat}`);
        return;
      }
      p.add(iv3 + 0x222c).writeS32(nat);
      log(`[FIX-INPUT] "${label(p)}" g=${g} xs=${xs} d5c ${d5c} -> ${nat}` +
          ` (law box = ${SL.itemlistBoxWidth(xs, d5c, 22, g)} for trim 22)`);
    },
  });

  log("lever installed. GAME RULES -> Customize Rules; glance Quit + Difficulty (must [skip]).");
}
