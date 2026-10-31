// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// =====================================================================================
// LOAD/SAVE FILE-PICKER -- SCALING PROTOTYPE (mutates live; see the skill's "prototype the
// fix in Frida and SEE it before writing asm").
//
// The picker is a bespoke native modal: FileDlg_layout creates a 334x393 GraphicWin and
// fills a 17-dword window-LOCAL rect array, then FileDlg_build_widgets lays the widgets out
// inside it. Everything renders 1:1 (tiny at hi-res). This prototype applies the TWO most
// faithful levers and nothing else, so we can see which elements honour them:
//   (1) scale the main window buffer (GraphicWin_init w/h) by g/16, recenter on its old center
//   (2) scale the 17-dword rect array (entries 1..16; leave [0]=flags) by g/16
//
// What we EXPECT to learn: the window/frame and the OK/CANCEL/list rectangles should grow;
// things driven by a separate native magnitude (button-label font, list row pitch, the title
// font, the jackal.pcx folder icons) will LAG -> those become the next levers. A clean
// proportionate result needs every element on the same g/16 factor (see proportionate rule).
//
//   GraphicWin_init   0x5D4EF0  thiscall(ecx=self, x,y,w,h on stack)
//   FileDlg_layout    0x407410 .. 0x407A80  (gate: only scale the window it creates)
//   FileDlg_build_w   0x6139B0  thiscall(ecx=Dialog, a1, win, rects17=[esp+c])
//   g_popup_scale_num 0x668740  (g; 16=native). g<=16 -> native no-op (low-res gate).
//
// Run: work\run-frida-at-res.bat hook_loaddlg_scaleproto.js 3840 2160   (then LOAD)
//      work\run-frida-at-res.bat hook_loaddlg_scaleproto.js 1600 1200
// =====================================================================================

globalThis.LOG_PATH = "D:/SmacxUi/work/frida_loaddlg_scaleproto.log";
log("=== hook_loaddlg_scaleproto.js started ===");
installAVHandler("loaddlg_proto");

const GW_INIT      = 0x005D4EF0;
const DLG_BUILD    = 0x006139B0;
const LAYOUT_LO    = 0x00407410;
const LAYOUT_HI    = 0x00407A80;
const SCREEN_W     = 0x009B7B1C;
const SCREEN_H     = 0x009B7B20;
const G_NUM        = 0x00668740;

function rd(va) { try { return VA(va).readS32(); } catch (e) { return -1; } }

if (requireBase()) {
  const den = 16;
  // g_popup_scale_num is 0 until a screen initializes -> read it LIVE per call, not at install.
  function gnow() { const g = rd(G_NUM); return (g >= 16) ? g : 16; }   // g<=16 -> native no-op
  function sc(v, num) { return Math.round(v * num / den); }
  log("[proto] installed; g read live per-call (g<=16 -> no-op).");

  // ---- (1) scale the main window buffer created inside FileDlg_layout ----
  Interceptor.attach(VA(GW_INIT), {
    onEnter() {
      const ret = this.returnAddress;          // who called GraphicWin_init (runtime addr)
      const base = VA(0x400000);               // module load base
      const rva = ret.sub(base).add(0x400000).toInt32() >>> 0;  // -> static VA space
      if (rva < LAYOUT_LO || rva >= LAYOUT_HI) return;  // only the picker's main window
      const num = gnow();
      if (num === den) { log("[gw_init] (no-op g=16) caller=0x" + rva.toString(16)); return; }
      const sp = this.context.esp;
      const px = sp.add(0x4), py = sp.add(0x8), pw = sp.add(0xc), ph = sp.add(0x10);
      const x = px.readS32(), y = py.readS32(), w = pw.readS32(), h = ph.readS32();
      const nw = sc(w, num), nh = sc(h, num);
      // recenter on the original center so it stays where it was, just bigger
      const nx = x - ((nw - w) >> 1), ny = y - ((nh - h) >> 1);
      pw.writeS32(nw); ph.writeS32(nh); px.writeS32(nx); py.writeS32(ny);
      log("[gw_init SCALED] caller=0x" + rva.toString(16) +
          "  x,y,w,h " + x + "," + y + "," + w + "," + h +
          " -> " + nx + "," + ny + "," + nw + "," + nh +
          "  screen=" + rd(SCREEN_W) + "x" + rd(SCREEN_H));
    }
  });

  // ---- (2) scale the 17-dword window-local rect array ----
  Interceptor.attach(VA(DLG_BUILD), {
    onEnter() {
      const sp = this.context.esp;
      const num = gnow();
      const rects = ptr("0x" + (arg(sp, 3) >>> 0).toString(16)); // [esp+c]
      if (rects.isNull()) { log("[build] rects NULL"); return; }
      let before = [], after = [];
      try {
        for (let i = 0; i < 17; i++) before.push(rects.add(i * 4).readS32());
        if (num !== den) {
          for (let i = 1; i < 17; i++) rects.add(i * 4).writeS32(sc(before[i], num)); // skip [0]=flags
        }
        for (let i = 0; i < 17; i++) after.push(rects.add(i * 4).readS32());
      } catch (e) { log("[build] rect rw failed: " + e); return; }
      log("[build] rects @" + rects + "\n   before=[" + before.join(",") + "]" +
          (num === den ? "  (no-op)" : "\n   after =[" + after.join(",") + "]"));
    }
  });

  log("hook_loaddlg_scaleproto installed. %resume -> main menu -> LOAD (and/or in-game SAVE) -> observe -> quit.");
}
