// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE #3 v2: v1 fired but boxw[D+0xeec] read 0 -> the static presumption
// D==container (popup+0x21d0) is wrong; the runtime adjustor lands elsewhere (count@+0xcc
// was right, so D itself IS the Dialog base -- only the box_w displacement is unknown).
// v2 stops guessing: capture the POPUP base at the thunk_scale_boxw site (esi=popup, so
// popup+0x30bc is the authoritative scaled box_w = 1831 @4K), widen from THAT, and log
// (a) box_w's offset relative to D and (b) a +/-0x2000 dword scan for the same value,
// so the asm thunk gets a PROVEN displacement instead of a derived one.
// v3: v2 CONFIRMED at 4K (bars flush with OK; box_w found at D+0x34c == popup+0x30bc,
// value 2080 = 1831 + margins 82+167 folded in by attach time). v3 additionally logs the
// attach's ESI at the init call site (call preserves esi -> readable in the callee) and
// its delta to D, plus box_w read D-relative -- the exact displacements the asm thunk
// at 0x60d299 will use. Run at a NON-4K res for the all-resolutions check.
// v5 (the LAW, from the v4 census @1600x1200): the OK bar inits at w=1035 = 789*21>>4 =
// measured_content x M(g) -- the SAME multiplier+rounding thunk_scale_boxw applies to the
// box (4K check: 977*30>>4 = 1831 = the box figure exactly). v3's box_w-2x gave 1088,
// 53px wider than OK = the reported right-side overrun ([D+0x34c]=1190 includes the
// ASYMMETRIC margins 51/104, so it was the wrong anchor). Fix: Wn = (w * M(g)) >> 4,
// M = 16 + (g_boxw_num-16)*(g-16)/24 -- bars == OK bar width by construction at every g.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_quit_fillproto.log";
log("=== hook_quit_fillproto.js v5 started ===");

const G_SCALE = 0x668740;   // g_popup_scale_num
const G_BOXW  = 0x668C30;   // g_boxw_num (=30)

if (requireBase()) {
  let lastD = null;
  Interceptor.attach(VA(0x60d380), function () {          // type-16 calc: capture Dialog base
    const self = this.context.ecx;
    lastD = self.add(self.readPointer().add(8).readS32());
  });
  Interceptor.attach(VA(0x5d4ef0), function () {          // GraphicWin_init
    const sp = this.context.esp;
    if (sp.readU32() !== 0x60d29e) return;                // gate: the type-16 row-window init
    const g = VA(G_SCALE).readS32();
    if (g <= 16 || !lastD) return;
    try {
      const count = lastD.add(0xcc).readS32();
      const x = sp.add(4).readS32();
      const w = sp.add(0xc).readS32();
      const boxw = lastD.add(0x34c).readS32();            // info only (includes margins)
      const M = 16 + Math.trunc((VA(G_BOXW).readS32() - 16) * (g - 16) / 24);
      const Wn = (w * M) >> 4;                            // == thunk_scale_boxw's math
      log("rowwin init: x=" + x + " w=" + w + " count=" + count +
          " boxw=" + boxw + " M=" + M + " g=" + g);
      if (count <= 1 || Wn <= w) return;                  // only-widen
      sp.add(0xc).writeS32(Wn);                           // w arg
      lastD.add(0x5c).writeS32(Wn);                       // item/text rect width
      lastD.add(0x64).writeS32(Wn);                       // row bar width
      log("WIDENED w " + w + " -> " + Wn);
    } catch (e) { log("err " + e); }
  });
  log("attached type-16 fill-width proto v2");
}
