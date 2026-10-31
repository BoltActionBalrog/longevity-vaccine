// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE (correct direction): the QUIT (type-16) box width 1831 is the tuned,
// user-approved proportion (thunk_scale_boxw M(g)=30/16 at g40). The ONLY defect is
// that row_w[+0x64] (the option-bar width) is derived from the Dialog sub-object's
// text/field widths, NOT from the scaled popup box_w -- so it stays 977 while the box
// grows to 1831 -> bars ~half width. Before scaling, row_w == box_w == 977 exactly.
// FIX: apply thunk_scale_boxw's IDENTICAL M(g) multiplier to row_w at the type-16
// calc exit, so it tracks the box (977 -> 1831 at g40), staying flush with OK.
//   M(g) = 16 + (g_boxw_num-16)*(g-16)/24 ,  row_w' = (row_w * M) >> 4
// 0x60d380 is the type-16-exclusive calc, so no type check needed. LOOK in-game:
// do the option bars now span the box, flush with the OK bar?
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_quit_rowwproto.log";
log("=== hook_quit_rowwproto.js started ===");

const G_SCALE = 0x668740;   // g_popup_scale_num (project cave copy)
const G_BOXW  = 0x668C30;   // g_boxw_num (=30)

if (requireBase()) {
  Interceptor.attach(VA(0x60d380), {
    onEnter() { this.self = this.context.ecx; },
    onLeave() {
      try {
        const g = VA(G_SCALE).readS32();
        if (g <= 16) return;
        const boxw = VA(G_BOXW).readS32();
        const M = 16 + Math.trunc((boxw - 16) * (g - 16) / 24);   // matches thunk idiv-by-24
        const self = this.self;
        const base = self.add(self.readPointer().add(8).readS32());
        const old = base.add(0x64).readS32();
        const neu = (old * M) >> 4;
        base.add(0x64).writeS32(neu);
        log("row_w " + old + " -> " + neu + "  (g=" + g + " M=" + M + ")");
      } catch (e) { log("err " + e); }
    }
  });
  log("attached row_w-scale proto");
}
