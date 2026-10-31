// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE of the Quit type-16 row-overlap fix (validate before building a thunk).
// Root cause: type-16 calc 0x60d380 sizes the row PITCH from Buffer_text_HEIGHT
// (0x5dca80, ink height ~34@g40) at 0x60d641, but the draw loop sizes each bar's
// rect.height from Buffer_text_LINE_height (0x5dcab0, ~50@g40). stride<height => overlap.
// FIX = calc should use line_height for the pitch. Here we do it live in 0x60d380 onLeave.
//
// v2: guard NativeFunction construction (a load-time throw would skip the attach and
// leave the log empty, as happened in run 1); log every calc firing so we can see it hit.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_quit_fixproto.log";
log("=== hook_quit_fixproto.js v3 started ===");

// g_popup_scale_num = the PROJECT cave copy (menu_strip_thunks+0x540), set by thunk_ensure_scale
// on the popup path. NOT the engine pair 0x696D18/1C (only set transiently in keyed sprite blits;
// it reads 1 outside them — that's why v2's gate saw g=1 and bailed).
const G_POPUP_SCALE_NUM = 0x668740;
function fld(p, o) { try { return p.add(o).readS32(); } catch (e) { return null; } }

// lazy, guarded line-height fn: try thiscall, fall back to mscdecl-with-ecx via a stub.
let _lineH = null, _lineHErr = null;
function lineHeight(buf) {
  if (_lineHErr) return null;
  try {
    if (_lineH === null) _lineH = new NativeFunction(VA(0x005DCAB0), 'int', ['pointer'], 'thiscall');
    return _lineH(buf);
  } catch (e) { _lineHErr = e; log("lineHeight NativeFunction error: " + e); return null; }
}

if (requireBase()) {
  let fires = 0;
  Interceptor.attach(VA(0x0060D380), {   // Dialog_type16_calc_dimensions (QUIT)
    onEnter() { this.self = this.context.ecx; },
    onLeave(retval) {
      try {
        const self = this.self;
        const vt = self.readPointer();
        const adj = vt.add(8).readS32();           // [[self]+8]
        const base = self.add(adj);
        const g = VA(G_POPUP_SCALE_NUM).readS32();
        const count = fld(base, 0xcc);
        fires++;
        log("calc FIRE #" + fires + " g=" + g + " (engine0x696D18=" +
            VA(0x696D18).readS32() + ") ret=" + retval.toInt32() +
            " adj=" + adj + " count=" + count +
            " H68=" + fld(base, 0x68) + " gap44=" + fld(base, 0x44) +
            " cnt58=" + fld(base, 0x58) + " total60=" + fld(base, 0x60));
        if (g <= 16) return;                        // native no-op gate (invariant)
        if (!count || count <= 0) return;           // calc returned 7 (no rows)
        const off4 = vt.add(4).readU32();           // self + [[self]+4] + 0x444 = row Buffer
        const buf = self.add(off4).add(0x444);
        const lh = lineHeight(buf);
        if (lh === null) return;
        const cur68 = fld(base, 0x68), gap = fld(base, 0x44), cnt58 = fld(base, 0x58);
        if (lh > cur68) base.add(0x68).writeS32(lh);
        const new68 = fld(base, 0x68);
        const newTotal = (new68 + gap) * (cnt58 > 0 ? cnt58 : count);
        base.add(0x60).writeS32(newTotal);
        log("  PATCHED lineH=" + lh + " oldH68=" + cur68 + " newH68=" + new68 +
            " oldTotal=" + fld(base, 0x60) + "->newTotal60=" + newTotal);
      } catch (e) { log("onLeave error " + e); }
    }
  });
  log("attached to 0x60d380");
}
