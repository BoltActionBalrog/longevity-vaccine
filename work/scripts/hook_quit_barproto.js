// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE #2 (draw-site lever): scaling row_w[+0x64] at the calc exit fired but did
// NOT move pixels -> [+0x64] is the logical/hit-test rect, not the drawn bar. The drawn
// option-bar background comes through item_back_draw (0x405b20), reached by the indirect
// call at 0x60da9a (return addr 0x60da9d). The width probe found its rect at callee
// [esp+0x10] -> {L,T,R,B} = {0,1,977,51} etc. Here we widen that rect's RIGHT edge in
// place by thunk_scale_boxw's SAME M(g) factor (R' = L + (R-L)*M/16), so the bar spans
// the scaled box (977 -> 1831 at g40), flush with OK. If the bar visibly grows to meet
// the OK bar -> this is the lever and we bake it at 0x60da9a's rect build. LOOK in-game.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_quit_barproto.log";
log("=== hook_quit_barproto.js started ===");

const G_SCALE = 0x668740;   // g_popup_scale_num
const G_BOXW  = 0x668C30;   // g_boxw_num (=30)

if (requireBase()) {
  let logged = 0;
  Interceptor.attach(VA(0x405b20), function () {
    const sp = this.context.esp;
    if (sp.readU32() !== 0x60da9d) return;          // gate: the type-16 row-bar draw
    const g = VA(G_SCALE).readS32();
    if (g <= 16) return;
    const boxw = VA(G_BOXW).readS32();
    const M = 16 + Math.trunc((boxw - 16) * (g - 16) / 24);
    try {
      const rectp = sp.add(0x10).readPointer();
      const L = rectp.add(0).readS32();
      const R = rectp.add(8).readS32();
      const Rn = L + (((R - L) * M) >> 4);
      rectp.add(8).writeS32(Rn);
      if (logged++ < 6) log("bar R " + R + " -> " + Rn + " (L=" + L + " g=" + g + " M=" + M + ")");
    } catch (e) { if (logged++ < 6) log("err " + e); }
  });
  log("attached bar-width draw-site proto");
}
