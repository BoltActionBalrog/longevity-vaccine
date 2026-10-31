// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE: is the QUIT (type-16) box over-widened by thunk_scale_boxw?
// The type-16 calc already scales box_w (977 fits the scaled content; row_w[+0x64]
// = box_w = 977). thunk_scale_boxw then multiplies it 977->1831 (generic non-list),
// but row_w stays 977 -> bars half-width + box over-wide. Hypothesis: EXCLUDE type-16
// from that multiply (leave box_w = 977) and both fix at once.
// This hook UNDOES the widen for type-16: capture box_w at the scale site (before the
// thunk), restore it right after. If the box becomes snug with full-width bars flush
// with OK -> hypothesis confirmed. If it becomes too NARROW (text/OK clipped) -> 977 is
// native and the real fix is the opposite (widen row_w to the box). LOOK in-game.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_quit_widthproto.log";
log("=== hook_quit_widthproto.js started ===");

function rd(p, off) { try { return p.add(off).readS32(); } catch (e) { return null; } }

if (requireBase()) {
  let lastPop = null, lastBefore = null;
  Interceptor.attach(VA(0x603d82), function () {      // thunk_scale_boxw call site (esi=popup), BEFORE the multiply
    lastPop = this.context.esi;
    lastBefore = rd(lastPop, 0x30bc);
  });
  Interceptor.attach(VA(0x603d88), function () {      // AFTER the multiply
    const pop = this.context.esi;
    const type = rd(pop, 0x2350);
    const after = rd(pop, 0x30bc);
    if (type === 16 && lastPop && pop.equals(lastPop) && lastBefore) {
      pop.add(0x30bc).writeS32(lastBefore);           // undo the widen
      log("type16 box_w RESTORED " + after + " -> " + lastBefore);
    }
  });
  log("attached width-undo proto");
}
