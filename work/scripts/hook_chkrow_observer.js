// OBSERVER (no writes), two open items in ONE run (v3):
//  A. PrefWin CheckList row vs uimod.dll's Longevity row (label y).  v2 (2026-09-13) PROVED the stock rows
//     never call Buffer_write_l_4: the label goes through Buffer_wrap_2 (first line at rect.top = rowTop +
//     window-font descent), box y = rowTop + ((rowB-18)>>1) + ((16-g)>>1) -> label - box = 6/5/5 at
//     g=40/25/22, the pixel-measured targets. v3 also hooks Buffer_wrap_2's entry to log that rect + font.
//  B. BASE LOCATOR ring vs the minimap base box. v2 showed the boxes are NOT drawn on the WorldWin canvas
//     0x8EA3A4: WorldWin_on_redraw copies the map render (WW+0xFA4) onto the embedded CONSOLE's canvas
//     (WW + [[WW+0x152C]+4] + 0x1970), runs WorldWin_draw_bases there, copies that onto WW+0xA1C, then
//     (via thunk_worldwin_fill) centres 1:1 or stretches it onto the window canvas -- while the ring is
//     stamped straight onto the window canvas at blink_x/y. So v3 logs, per base tile that draws anything:
//     its (px,py) + every box/fill/line primitive on ANY of the three buffers (with the call site); the
//     WorldWin fit fields (+0xA14/+0xA18 render size, +0x4C4/+0x4C8 window size); every Buffer_copy_4 and
//     the two 0x5E3503/0x5E3563 blits issued inside WorldWin_on_redraw (raw args); and the ring stamps.
//
// HOOK HOSTS ARE FUNCTION ENTRIES ONLY (feedback_frida_attach_branch_target; the v1 mid-function attach
// AV'd at 1600). Every host's first bytes were checked: none is a baked push/ret or E8 detour.
//
// Run: the desktop 'SMACX Frida Trace*' shortcuts (run-frida-at-res.bat hook_chkrow_observer.js W H).
//   %resume, open Preferences -> Map Preferences -> Longevity Mod Preferences -> Cancel;
//   then open the report screen with the BASE LOCATOR (F4), let the ring blink ~3 s, close; quit.
//   Log: D:/SmacxUi/work/frida_chkrow_<UTC time>.log (one file per run; nothing is overwritten).
"use strict";

(function () {
  const t = new Date().toISOString().replace(/[-:]/g, "").replace(/\..*$/, "").replace("T", "-");
  globalThis.LOG_PATH = "D:/SmacxUi/work/frida_chkrow_" + t + ".log";
  let f = null;
  globalThis.log = function (msg) {
    if (f === null) f = new File(globalThis.LOG_PATH, "w");
    const line = "" + msg; console.log(line); f.write(line + "\n"); f.flush();
  };
})();
log("=== hook_chkrow_observer.js v4 @ " + new Date().toISOString() + " -> " + globalThis.LOG_PATH + " ===");
installAVHandler("chkrow");

if (requireBase()) {
  const PCAVE2 = 0x00A0C000;
  const PREF_LO = 0x008578D8, PREF_HI = 0x008578D8 + 0xB000;   // PrefWin_g static object
  const dllLo = ptr(PCAVE2 + 0xB120), dllHi = ptr(PCAVE2 + 0xB124);
  const gScale = ptr(0x00668740);
  const CHK_DRAW = 0x0060F030, WL4 = 0x005DCF40, WL3 = 0x005DCEA0, WRAP2 = 0x005DD530, CHK_SCALE = 0x00668C40;
  const LIST_WIN = 0x1C, LIST_DLG = 0xA34;
  // ring / minimap
  const WW = 0x008E9F60, WORLD_CANVAS = WW + 0x444;             // WorldWindow object / its window canvas 0x8EA3A4
  const WW_ONREDRAW = 0x004C3EC0, DRAW_BASES = 0x00469B40, DRAW_BASE_TILE = 0x00467190;
  const COPY4 = 0x005DFF00, BLIT_A = 0x005E3503, BLIT_B = 0x005E3563;
  const T_RWK_BLINK = PCAVE2 + 0x6E30, T_RWK_BLINKTILE = PCAVE2 + 0x24F70;   // v13: blink pinned at 0x6E30; the tile stash took its old slot
  const BLINK_X = ptr(0x008A4184), BLINK_Y = ptr(0x008A4188), BLINK_STATE = ptr(0x008A4180), BIG_F4 = ptr(PCAVE2 + 0xB170);
  let curList = null, n = 0;
  let inTile = null, inRedraw = false, pass = 0, ringN = 0, tilesThisPass = 0;
  const MAX_PASSES = 8, MAX_RINGS = 16;

  function u(p) { return p.toUInt32() >>> 0; }
  function inPref(v) { return v >= PREF_LO && v < PREF_HI; }
  function inDll(v) {
    let lo = 0, hi = 0;
    try { lo = dllLo.readU32() >>> 0; hi = dllHi.readU32() >>> 0; } catch (e) {}
    return lo !== 0 && v >= lo && v <= hi + 0x1000;
  }
  function consoleCanvas() {   // WW + [[WW+0x152C]+4] + 0x1970 (the console's GraphicWin part + 0x444)
    try { return (WW + ptr(ptr(WW + 0x152C).readU32() >>> 0).add(4).readU32() + 0x1970) >>> 0; } catch (e) { return 0; }
  }
  function bufName(v) {
    if (inPref(v)) return "PREF+0x" + (v - PREF_LO).toString(16);
    if (inDll(v)) return "DLL";
    if (v === WORLD_CANVAS) return "WINDOW_CANVAS";
    if (v === WW + 0xA1C) return "WW+0xA1C";
    if (v === WW + 0xFA4) return "WW+0xFA4(render)";
    if (v === consoleCanvas()) return "CONSOLE_CANVAS";
    return "0x" + v.toString(16);
  }
  function isMinimapBuf(v) { return v === WORLD_CANVAS || v === WW + 0xA1C || v === WW + 0xFA4 || v === consoleCanvas(); }
  function font(fp) {
    try {
      const v = u(fp); if (!v) return "font=null";
      const p = ptr(v);
      return `font=0x${v.toString(16)} pad=${p.readS32()} hfont=0x${p.add(8).readU32().toString(16)} cell=${p.add(0xC).readS32()} capH=${p.add(0x10).readS32()} intL=${p.add(0x14).readS32()} asc=${p.add(0x18).readS32()} desc=${p.add(0x1C).readS32()}`;
    } catch (e) { return "font=?"; }
  }
  function sprH(sp) { try { const v = u(sp); return v ? ptr(v).add(0x1C).readS32() : -1; } catch (e) { return -2; } }
  function sprWH(sp) { try { const v = u(sp); return v ? `w18=${ptr(v).add(0x18).readS32()} h1C=${ptr(v).add(0x1C).readS32()} w10=${ptr(v).add(0x10).readS32()} h14=${ptr(v).add(0x14).readS32()}` : "spr=null"; } catch (e) { return "spr=?"; } }
  function str(p) { try { return JSON.stringify(p.readCString(40)); } catch (e) { return "?"; } }
  function g() { try { return gScale.readS32(); } catch (e) { return "?"; } }
  function rd(p) { try { return p.readS32(); } catch (e) { return "?"; } }
  function rdo(base, off) { try { return ptr(base + off).readS32(); } catch (e) { return "?"; } }
  function hex(p) { return "0x" + u(p).toString(16); }
  function rect(r) { return `(${r.readS32()},${r.add(4).readS32()},${r.add(8).readS32()},${r.add(12).readS32()})`; }
  function attachEntry(name, va, cb) {
    try { Interceptor.attach(ptr(va), cb); } catch (e) { log("ATTACH FAIL " + name + " @0x" + va.toString(16) + ": " + e); }
  }
  function tileHeader() {   // print the pending base_tile line once, on its first primitive
    if (inTile !== null && !inTile.printed) { inTile.printed = true; log(inTile.hdr); }
  }

  // ---------------- A. PrefWin CheckList rows ----------------
  attachEntry("CheckList_draw_item", CHK_DRAW, {
    onEnter(args) {
      const self = u(this.context.ecx);
      if (!inPref(self)) { curList = null; return; }
      curList = self;
      const p = ptr(self);
      const dlg = p.add(LIST_DLG), win = p.add(LIST_WIN);
      log(`painter #${++n} list=${bufName(self)} row=${args[0].toInt32()} g=${g()} rowH=${dlg.add(0x68).readS32()} gap=${dlg.add(0x44).readS32()} indent=${dlg.add(0x34).readS32()} stride=${dlg.add(0x48).readS32()} listY=${dlg.add(0x40).readS32()} | winfont: ${font(win.add(0x970).readPointer())} | sprOff h=${sprH(p.add(0x10).readPointer())} sprOn h=${sprH(p.add(0x14).readPointer())}`);
    },
    onLeave() { curList = null; }
  });
  attachEntry("thunk_checkbox_scale", CHK_SCALE, {   // [esp+4]=dest [esp+8]=key [esp+C]=x [esp+10]=y [esp+14]=num [esp+18]=den, ecx=sprite
    onEnter() {
      const sp = this.context.esp, dest = u(sp.add(4).readPointer());
      if (curList === null && !inDll(dest) && !inPref(dest)) return;
      const ret = u(this.returnAddress);
      const who = (ret === 0x60F421 || ret === 0x60F45C) ? "painter's own box draw" : "other site";
      log(`  chk_scale @ret=0x${ret.toString(16)} (${who}) dest=${bufName(dest)} x=${sp.add(0xC).readS32()} y=${sp.add(0x10).readS32()} num=${sp.add(0x14).readS32()} den=${sp.add(0x18).readS32()} sprite h=${sprH(this.context.ecx)}`);
    }
  });
  attachEntry("Buffer_write_l_4", WL4, {            // (str, rect*, len); ecx=Buffer, font at Buffer+0x52C
    onEnter(args) {
      const buf = u(this.context.ecx);
      if (curList === null && !inDll(buf) && !inPref(buf)) return;
      log(`  write_l_4 @ret=${hex(this.returnAddress)} buf=${bufName(buf)} rect=${rect(args[1])} ${font(this.context.ecx.add(0x52C).readPointer())} str=${str(args[0])}`);
    }
  });
  attachEntry("Buffer_wrap_2", WRAP2, {             // (str, rect*); ecx=Buffer; first line at rect.top
    onEnter(args) {
      const buf = u(this.context.ecx);
      if (curList === null && !inDll(buf) && !inPref(buf)) return;
      log(`  wrap_2 @ret=${hex(this.returnAddress)} buf=${bufName(buf)} rect=${rect(args[1])} ${font(this.context.ecx.add(0x52C).readPointer())} str=${str(args[0])}`);
    }
  });
  attachEntry("Buffer_write_l_3", WL3, {            // (str, x, y, len)
    onEnter(args) {
      const buf = u(this.context.ecx);
      if (!inDll(buf) && !inPref(buf)) return;
      log(`  write_l_3 @ret=${hex(this.returnAddress)} buf=${bufName(buf)} x=${args[1].toInt32()} y=${args[2].toInt32()} ${font(this.context.ecx.add(0x52C).readPointer())} str=${str(args[0])}`);
    }
  });

  // ---------------- B. BASE LOCATOR ring vs the minimap base box ----------------
  attachEntry("WorldWin_on_redraw", WW_ONREDRAW, {
    onEnter() {
      inRedraw = true;
      if (pass < MAX_PASSES) log(`ww_on_redraw self=${hex(this.context.ecx)} g=${g()} render=${rdo(WW, 0xA14)}x${rdo(WW, 0xA18)} win=${rdo(WW, 0x4C4)}x${rdo(WW, 0x4C8)} console_canvas=0x${consoleCanvas().toString(16)} blink_state=${rd(BLINK_STATE)} blink=(${rd(BLINK_X)},${rd(BLINK_Y)}) big_f4=${rd(BIG_F4)}`);
    },
    onLeave() { inRedraw = false; }
  });
  attachEntry("WorldWin_draw_bases", DRAW_BASES, {
    onEnter() { pass++; tilesThisPass = 0; if (pass <= MAX_PASSES) log(`draw_bases pass #${pass} g=${g()} blink=(${rd(BLINK_X)},${rd(BLINK_Y)})`); },
    onLeave() { if (pass <= MAX_PASSES) log(`  (pass #${pass}: ${tilesThisPass} base tiles visited)`); }
  });
  attachEntry("MapWin_draw_base_tile", DRAW_BASE_TILE, {   // thiscall(self, x, y, px, py, faction); self = the console
    onEnter(args) {
      tilesThisPass++;
      if (pass > MAX_PASSES) { inTile = null; return; }
      inTile = { printed: false, hdr: `  base_tile self=${hex(this.context.ecx)} tile=(${args[0].toInt32()},${args[1].toInt32()}) px=${args[2].toInt32()} py=${args[3].toInt32()} faction=${args[4].toInt32()}` };
    },
    onLeave() { inTile = null; }
  });
  const PRIMS = [
    ["box_2",   0x005E3203, (a) => `rect=${rect(a[0])} ch=${a[1].toInt32()} cv=${a[2].toInt32()}`],
    ["box",     0x005E3193, (a) => `x0=${a[0].toInt32()} y0=${a[1].toInt32()} x1=${a[2].toInt32()} y1=${a[3].toInt32()} ch=${a[4].toInt32()} cv=${a[5].toInt32()}`],
    ["fill_3",  0x005DFCD0, (a) => `rect=${rect(a[0])} c=${a[1].toInt32()}`],
    ["fill",    0x005D8240, (a) => `x=${a[0].toInt32()} y=${a[1].toInt32()} w=${a[2].toInt32()} h=${a[3].toInt32()} c=${a[4].toInt32()}`],
    ["hline_2", 0x005E1A80, (a) => `x0=${a[0].toInt32()} x1=${a[1].toInt32()} y=${a[2].toInt32()} c=${a[3].toInt32()}`],
    ["vline_2", 0x005E1BF0, (a) => `x=${a[0].toInt32()} y0=${a[1].toInt32()} y1=${a[2].toInt32()} c=${a[3].toInt32()}`],
  ];
  for (const [name, va, fmt] of PRIMS) {
    attachEntry(name, va, {
      onEnter(args) {
        if (inTile === null) return;
        const buf = u(this.context.ecx);
        if (!isMinimapBuf(buf)) return;
        let d; try { d = fmt(args); } catch (e) { d = "(fmt failed)"; }
        tileHeader();
        log(`    ${name} @ret=${hex(this.returnAddress)} buf=${bufName(buf)} ${d}`);
      }
    });
  }
  // composition blits inside WorldWin_on_redraw (raw args; Buffer_copy_4 = (dst, srcX, srcY, dstX, dstY, w, h))
  const BLITS = [["copy_4", COPY4, 7], ["blit_5e3503", BLIT_A, 7], ["blit_5e3563", BLIT_B, 7]];
  for (const [name, va, argc] of BLITS) {
    attachEntry(name, va, {
      onEnter(args) {
        if (!inRedraw || pass > MAX_PASSES) return;
        const src = u(this.context.ecx);
        const dst = u(args[0]);
        if (!isMinimapBuf(src) && !isMinimapBuf(dst)) return;
        const raw = []; for (let i = 0; i < argc; i++) raw.push(args[i].toInt32());
        log(`  ${name} @ret=${hex(this.returnAddress)} src=${bufName(src)} dst=${bufName(dst)} args=[${raw.join(",")}]`);
      }
    });
  }
  const G_BLINK_TILE = ptr(PCAVE2 + 0x279B8), CONSOLE_FLAGS = ptr(0x008EB48C + 0x1DD70), SCALE_NN = PCAVE2 + 0x2150;
  function sprAll(sp) { try { const v = u(sp); const q = ptr(v); return v ? `w10=${q.add(0x10).readS32()} h14=${q.add(0x14).readS32()} w18=${q.add(0x18).readS32()} h1C=${q.add(0x1C).readS32()} offx20=${q.add(0x20).readS32()} offy24=${q.add(0x24).readS32()}` : "spr=null"; } catch (e) { return "spr=?"; } }
  attachEntry("t_rwk_blink", T_RWK_BLINK, {   // v13 in: ecx=sprite, [esp+4]=dest [esp+8]=key [esp+C]=x [esp+10]=y (the blink point)
    onEnter() {
      if (ringN >= MAX_RINGS) return;
      const sp = this.context.esp;
      log(`ring stamp #${++ringN} @ret=${hex(this.returnAddress)} g=${g()} big_f4=${rd(BIG_F4)} dest=${bufName(u(sp.add(4).readPointer()))} x=${sp.add(0xC).readS32()} y=${sp.add(0x10).readS32()} blink=(${rd(BLINK_X)},${rd(BLINK_Y)}) state=${rd(BLINK_STATE)} tile=(${rd(G_BLINK_TILE)},${rd(G_BLINK_TILE.add(4))}) console_flags=0x${(CONSOLE_FLAGS.readU32() >>> 0).toString(16)} win=${rdo(WW, 0x4C4)}x${rdo(WW, 0x4C8)} buf=${rdo(WW, 0xA14)}x${rdo(WW, 0xA18)} off=(${rdo(WW, 0x239C4)},${rdo(WW, 0x239C8)}) sprite ${sprAll(this.context.ecx)}`);
    }
  });
  attachEntry("t_rwk_blinktile", T_RWK_BLINKTILE, {   // redirect @0x4974B2: [esp+4]=tx [esp+8]=ty -> g_blink_tile
    onEnter(args) { log(`blink tile stash: tx=${args[0].toInt32()} ty=${args[1].toInt32()} (ReportWin_on_lclick @ret=${hex(this.returnAddress)})`); }
  });
  attachEntry("thunk_sprite_scale_nn", SCALE_NN, {   // v13 big path out: (dest,key,x,y,num,den), ecx=sprite; x,y = the thunk's placement
    onEnter(args) {
      if (u(args[0]) !== WORLD_CANVAS || ringN > MAX_RINGS) return;
      log(`  -> scale_nn x=${args[2].toInt32()} y=${args[3].toInt32()} num=${args[4].toInt32()} den=${args[5].toInt32()} sprite ${sprAll(this.context.ecx)}`);
    }
  });
  log("installed A: CheckList_draw_item, thunk_checkbox_scale, Buffer_write_l_4, Buffer_wrap_2, Buffer_write_l_3; B: WorldWin_on_redraw (+fit fields, copy_4 / 0x5E3503 / 0x5E3563 blits), WorldWin_draw_bases, MapWin_draw_base_tile + box/fill/line prims on the console/WW+0xA1C/window buffers, t_rwk_blink. (entries only)");
  log("Do: Preferences -> Map Preferences -> Longevity Mod Preferences -> Cancel; then the BASE LOCATOR report (F4), wait ~3 s of blinking, close; quit.");
}
