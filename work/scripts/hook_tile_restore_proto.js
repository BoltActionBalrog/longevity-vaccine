// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// ============================================================================
// hook_tile_restore_proto.js v5 — SAVE-UNDER fix for the diplo-exit console
// residue.  Root cause (v1-v4 forensics): the diplomacy flow paints the
// inter-panel gap of the console strip (dev y DA0.B..DB0.T, x D80.R..D90.L)
// and the exit restore (MainWin_tile_panels big=0) never repaints it — its
// normal-mode rects exclude the gap, and the 24x24 tile texture [0x78D6B0]
// is a flat backdrop that cannot reproduce the scaled pcx ledge art anyway.
// Fix = the popup save-under pattern: SNAPSHOT the gap band from the canvas
// when diplomacy opens (DiploTalkIface_on_mode ENTER, before any diplo
// draw), RESTORE it on every normal-mode tile_panels while a snapshot is
// live, then canvas->screen soft_update.  g<=16: no-op (vanilla restore is
// correct at native).
//
// Attach set (all previously proven safe): 0x440380 on_mode entry,
// 0x45C290 tile_panels entry (onLeave), NativeFunction GraphicWin_soft_update.
// ============================================================================
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_tile_restore.log";
log("=== hook_tile_restore_proto.js v5 (save-under) ===");
installAVHandler("tile_restore");

if (requireBase()) {
  const MAINWIN = VA(0x7AE820);
  const CANVAS = VA(0x7AEC64);          // MainWin+0x444 Buffer
  const G_BIG = VA(0x7D3930);           // g_console_big_center
  const G_NUM = VA(0x668740);           // g_popup_scale_num

  const softUpdate = new NativeFunction(VA(0x5D5720), "void",
    ["pointer", "int", "int", "int", "int"], "thiscall");

  function rect4(p) { return [p.readS32(), p.add(4).readS32(), p.add(8).readS32(), p.add(12).readS32()]; }
  function canvasInfo() {
    const data = CANVAS.add(0x54).readPointer();
    if (data.isNull()) return null;
    const stride = CANVAS.add(0x4A8).readS32();
    const w = CANVAS.add(0x80).readS32();
    let h = CANVAS.add(0x84).readS32(); if (h < 0) h = -h;
    return { data: data, stride: stride, w: w, h: h };
  }
  // the full inter-panel centre column the diplo flow can touch (big tile,
  // status panels, bezel sprite): x D80.R..D90.L, y strip-top..DB0.T+1.
  // Restoring it at tile_panels time is safe: panel painters run AFTER
  // tile_panels in every paint flow and repaint their own rects on top.
  // (+2 rows at the bottom: the engine tiles rects inset by 1, so DB0's top
  // row is never re-tiled — the dark line at canvas y 470.)
  function gapRect() {
    const d80 = rect4(MAINWIN.add(0xD80)), d90 = rect4(MAINWIN.add(0xD90));
    const db0 = rect4(MAINWIN.add(0xDB0));
    return [d80[2], 0, d90[0], db0[1] + 2];    // L=D80.R T=0 R=D90.L B=DB0.T+2
  }

  let saved = null;                     // {rect, rows: Uint8Array[], stride}
  function snapshotGap() {
    const c = canvasInfo();
    if (!c) return;
    const r = gapRect();
    const L = Math.max(r[0], 0), T = Math.max(r[1], 0),
          R = Math.min(r[2], c.w), B = Math.min(r[3], c.h);
    if (R <= L || B <= T) { log("snapshot: degenerate gap " + r); return; }
    const rows = [];
    for (let y = T; y < B; y++)
      rows.push(new Uint8Array(c.data.add(y * c.stride + L).readByteArray(R - L)));
    saved = { L: L, T: T, R: R, B: B, rows: rows };
    log("snapshot gap (" + L + "," + T + ")-(" + R + "," + B + ")  " + (R - L) + "x" + (B - T));
  }
  function restoreGap(tag) {
    if (!saved) return false;
    const c = canvasInfo();
    if (!c) return false;
    for (let y = saved.T; y < saved.B; y++)
      c.data.add(y * c.stride + saved.L).writeByteArray(saved.rows[y - saved.T].buffer);
    softUpdate(MAINWIN, saved.L, saved.T, saved.R - saved.L, saved.B - saved.T);
    log("restore gap [" + tag + "] (" + saved.L + "," + saved.T + ")-(" + saved.R + "," + saved.B + ")");
    return true;
  }

  // DiploTalkIface_on_mode(enter): ENTER fires before any diplo draw
  Interceptor.attach(VA(0x440380), {
    onEnter() {
      const en = this.context.esp.add(4).readS32();
      const g = G_NUM.readS32() || 16;
      if (g <= 16) return;
      if (en) snapshotGap();
      log("on_mode(" + (en ? "ENTER" : "LEAVE") + ")");
    }
  });

  // MainWin_tile_panels: after every NORMAL-mode pass while a snapshot is
  // live, put the gap band back (the pass just repainted around it).
  Interceptor.attach(VA(0x45C290), {
    onEnter() { this.big = G_BIG.readS32(); },
    onLeave() {
      const g = G_NUM.readS32() || 16;
      if (g <= 16 || this.big) return;
      try { restoreGap("tile_panels"); } catch (e) { log("restore failed: " + e); }
    }
  });

  log("v5 armed: gap save-under (snapshot on diplo enter, restore on normal tile_panels)");
}
