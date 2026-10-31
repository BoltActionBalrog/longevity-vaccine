"use strict";
// v5 OBSERVER-ONLY. The v3/v4 scrollbar prototype levers are now BAKED in build be257016
// (thunk_sb_xinset/thunk_sb_width/thunk_sb_thumb + thunk_btn_gate v3) — the active hooks were
// REMOVED because running them against the patched exe would DOUBLE-scale (baked thunk + hook).
// This version only logs, safe on patched or pristine.

globalThis.LOG_PATH = "D:/SmacxUi/work/frida_nwchatfont.log";
log("=== hook_nwchatfont.js v5 (observer only; scrollbar levers are baked) ===");

if (requireBase()) {
  const G_SCALE  = VA(0x668740);    // g_popup_scale_num
  const G_NETWIN = VA(0xA10800);    // g_netwin_active (baked flag, pcave2+0x4800)
  const TS       = VA(0x80B438);    // chat TextScroll widget
  let thumbLogs = 0;

  // scrollbar attach args as the engine (post-thunk) sees them
  Interceptor.attach(VA(0x6058B3), function () {
    log("sb attach width (post-thunk eax) = " + this.context.eax.toInt32());
  });

  // thumb blit args after thunk_sb_thumb ran (attach INSIDE the thunk's tail target)
  Interceptor.attach(VA(0x5E4B4A), function () {   // Sprite_draw_2 entry
    const sp = this.context.esp;
    if (G_NETWIN.readS32() !== 0 && thumbLogs < 6) {
      thumbLogs++;
      log("Sprite_draw_2: spr=" + this.context.ecx + " x=" + sp.add(0xC).readS32() +
          " y=" + sp.add(0x10).readS32() + " num=" + sp.add(0x14).readS32() +
          "/" + sp.add(0x18).readS32());
    }
  });

  // post-attach confirmation of the baked chat font
  Interceptor.attach(VA(0x482A69), function () {
    log("post-attach: g=" + G_SCALE.readS32() +
        " TS font1@+0x970=" + TS.add(0x970).readPointer());
  });

  log("armed (observers only)");
}
