"use strict";
// COMBAT (BattleWin) console GEOMETRY probe -- observer only, fn-entry hosts only.
// Runs UNCHANGED on the patched exe AND the pristine exe (every host below has a plain entry on
// both; the baked-detour entries Sprite_draw_2 / veh_draw / Buffer_box_sprite / Font_init /
// Buffer_set_font / Buffer_write_cent_l_5 are deliberately NOT hosts -- their effect is MEASURED
// from the strip buffer instead).
//
// What it records (static map: work\_cmb_static_map.md):
//   [INIT]   BattleWin_init 0x4219E0: the 8 rects (+0x30..+0x9C) derived from seeds D80/DC0
//   [STATUS] BattleWin_on_status 0x422CC0 (open/close), slide_show/slide_hide flag-2 bezel swap,
//            MainWin_tile_panels big-centre flag
//   [REPORT] BattleWin_battle_report 0x421B50: args, rects, seeds, both faction portrait Sprite
//            dims, the 3 local Font_init'd fonts (frame [ebp-0xC4/-0xEC/-0x9C]) metrics
//   [TEXT]   every Buffer_wrap_3 / wrap_cent_4 / wrap_cent_6 / find_font / Buffer_set_clip called
//            FROM battle_report (return-address gated): site, string, x/y/w or rect, the strip's
//            current font + line height, and the returned y
//   [PIX]    on battle_report leave: per-box stroke run-lengths + content bounding boxes measured
//            in the strip buffer
//   [DUMP]   raw strip-buffer dumps (idle-before / report-after / hide-after) + palette, for
//            offline PNG rendering: py scripts\_cmb_dump_to_png.py
const STAMP = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
const OUTDIR = "D:/SmacxUi/work/_cmb_probe/";
globalThis.LOG_PATH = OUTDIR + "combat_geom_" + STAMP + ".log";
log("=== hook_combat_geom.js started ===");
installAVHandler("combat_geom");
if (requireBase()) {
  const STRIP = VA(0x7AEC64), MAINWIN = VA(0x7AE820);
  const SW = VA(0x9B7B1C), SH = VA(0x9B7B20);
  const PAL = VA(0x94C590);
  const BIG = VA(0x7D3930);
  const REPORT_LO = 0x421B50, REPORT_HI = 0x422BFB;
  const exeName = Process.mainModule.name;
  const patched = (function () {        // .pcave2 present?
    try { return VA(0x5E2DD3).readU8() === 0xE8; } catch (e) { return false; }
  })();
  function gNow() {
    if (patched) { const g = VA(0x668740).readS32(); if (g >= 16 && g <= 40) return g; }
    return 16;
  }
  log("exe=" + exeName + " patched=" + patched + " screen=" + SW.readS32() + "x" + SH.readS32());

  const sva = a => "0x" + ptr(a).sub(TERRANX_BASE).add(0x400000).toString(16);
  function rect(p) { return [p.readS32(), p.add(4).readS32(), p.add(8).readS32(), p.add(12).readS32()]; }
  function cstr(p, n) {
    try {
      if (p.isNull()) return "(null)";
      const b = new Uint8Array(p.readByteArray(n)); let s = "";
      for (let i = 0; i < b.length && b[i] !== 0; i++) s += (b[i] >= 32 && b[i] < 127) ? String.fromCharCode(b[i]) : "?";
      return JSON.stringify(s);
    } catch (e) { return "(unreadable)"; }
  }
  function fontInfo(f) {
    try {
      if (f.isNull()) return "null";
      const a = f.readS32(), c = f.add(0xC).readS32(), d = f.add(0x10).readS32();
      const lineH = a < 0 ? c : d + a;                 // engine line-height idiom
      return f + "{+0=" + a + " +C=" + c + " +10=" + d + " lineH=" + lineH + " hfont=" + f.add(8).readPointer() + "}";
    } catch (e) { return f + "{unreadable}"; }
  }
  function stripFont() { try { return fontInfo(STRIP.add(0x52C).readPointer()); } catch (e) { return "?"; } }
  function spriteInfo(s) {
    try { return s + "{w=" + s.add(0x18).readS32() + " h=" + s.add(0x1C).readS32() + " b8=" + s.add(8).readU8() + " bC=" + s.add(0xC).readU8() + " pitch=" + s.add(0xC).readS32() + " w10=" + s.add(0x10).readS32() + " h14=" + s.add(0x14).readS32() + "}"; }
    catch (e) { return s + "{unreadable}"; }
  }
  function seeds() {
    const o = {};
    [["A1C", 0xA1C], ["D3C", 0xD3C], ["D80", 0xD80], ["D90", 0xD90], ["DA0", 0xDA0], ["DB0", 0xDB0],
     ["DC0", 0xDC0], ["DD0", 0xDD0]].forEach(k => { o[k[0]] = rect(MAINWIN.add(k[1])).join(","); });
    return JSON.stringify(o);
  }
  function bwRects(self) {
    const o = {};
    [0x30, 0x40, 0x50, 0x60, 0x70, 0x90].forEach(off => { o["+" + off.toString(16)] = rect(self.add(off)).join(","); });
    return JSON.stringify(o);
  }

  // ---------- strip buffer access ----------
  function stripGeom() {
    const bits = STRIP.add(0x54).readPointer();
    const pitch = STRIP.add(0x4A8).readS32();
    const w = STRIP.add(0x80).readS32();
    let h = STRIP.add(0x84).readS32(); if (h < 0) h = -h;
    if (bits.isNull() || pitch < w || pitch > w + 8 || w < 600) return null;
    return { bits: bits, pitch: pitch, w: w, h: h };
  }
  let dumpN = 0;
  function dumpStrip(tag) {
    try {
      const s = stripGeom(); if (s === null || dumpN >= 12) return;
      const name = OUTDIR + "strip_" + STAMP + "_" + (dumpN++) + "_" + tag + "_" + s.w + "x" + s.h + ".bin";
      const f = new File(name, "wb");
      f.write(PAL.readByteArray(1024));
      for (let y = 0; y < s.h; y++) f.write(s.bits.add(y * s.pitch).readByteArray(s.w));
      f.flush(); f.close();
      log("[DUMP] " + name + " clip=" + rect(STRIP.add(0x20)) + " big=" + BIG.readS32());
    } catch (e) { log("[DUMP] failed: " + e.message); }
  }
  function rowBytes(s, y, x0, x1) { return new Uint8Array(s.bits.add(y * s.pitch + x0).readByteArray(x1 - x0)); }
  function rle(arr, max) {
    const out = []; let i = 0;
    while (i < arr.length && out.length < max) { let j = i; while (j < arr.length && arr[j] === arr[i]) j++; out.push(arr[i] + "x" + (j - i)); i = j; }
    return out.join(" ");
  }
  function measureBox(s, name, r) {
    const L = Math.max(0, r[0]), T = Math.max(0, r[1]), R = Math.min(s.w, r[2] + 1), B = Math.min(s.h, r[3] + 1);
    if (R - L < 12 || B - T < 12) { log("[PIX] " + name + " rect=" + r + " degenerate"); return; }
    const my = (T + B) >> 1, mx = (L + R) >> 1;
    const lx0 = Math.max(0, L - 8);
    const col = []; for (let y = Math.max(0, T - 8); y < Math.min(s.h, T + 24); y++) col.push(s.bits.add(y * s.pitch + mx).readU8());
    const colB = []; for (let y = Math.max(0, B - 24); y < Math.min(s.h, B + 8); y++) colB.push(s.bits.add(y * s.pitch + mx).readU8());
    log("[PIX] " + name + " rect=" + r + "  L-edge row" + my + " from x" + lx0 + ": " + rle(rowBytes(s, my, lx0, Math.min(s.w, L + 24)), 12));
    log("[PIX] " + name + "  R-edge to x" + Math.min(s.w, R + 8) + ": " + rle(rowBytes(s, my, Math.max(0, R - 24), Math.min(s.w, R + 8)), 12));
    log("[PIX] " + name + "  T-edge col" + mx + " from y" + Math.max(0, T - 8) + ": " + rle(col, 12) + "   B-edge to y" + Math.min(s.h, B + 8) + ": " + rle(colB, 12));
    // content bbox: pixels that are not one of the interior's 2 dominant (fill) indices
    const inset = 8, hist = new Uint32Array(256);
    for (let y = T + inset; y < B - inset; y++) { const rw = rowBytes(s, y, L + inset, R - inset); for (let i = 0; i < rw.length; i++) hist[rw[i]]++; }
    const order = Array.from(hist.keys()).sort((a, b) => hist[b] - hist[a]);
    const f0 = order[0], f1 = order[1];
    function bbox(x0, x1) {
      let bx0 = 1e9, by0 = 1e9, bx1 = -1, by1 = -1, n = 0;
      for (let y = T + inset; y < B - inset; y++) {
        const rw = rowBytes(s, y, x0, x1);
        for (let i = 0; i < rw.length; i++) if (rw[i] !== f0 && rw[i] !== f1) {
          n++; if (x0 + i < bx0) bx0 = x0 + i; if (x0 + i > bx1) bx1 = x0 + i; if (y < by0) by0 = y; if (y > by1) by1 = y;
        }
      }
      return n ? (bx0 + "," + by0 + ".." + bx1 + "," + by1 + " (" + (bx1 - bx0 + 1) + "x" + (by1 - by0 + 1) + ", n=" + n + ")") : "none";
    }
    log("[PIX] " + name + "  fill=" + f0 + "/" + f1 + " content bbox whole=" + bbox(L + inset, R - inset) +
      " | leftHalf=" + bbox(L + inset, mx) + " | rightHalf=" + bbox(mx, R - inset));
    // per-row occupancy profile of each half (text line pitch falls out of the run pattern)
    function rowsProfile(x0, x1) {
      const occ = [];
      for (let y = T + inset; y < B - inset; y++) { const rw = rowBytes(s, y, x0, x1); let o = 0; for (let i = 0; i < rw.length; i++) if (rw[i] !== f0 && rw[i] !== f1) { o = 1; break; } occ.push(o); }
      return "y" + (T + inset) + ": " + rle(occ, 60);
    }
    log("[PIX] " + name + "  rows leftHalf  " + rowsProfile(L + inset, mx));
    log("[PIX] " + name + "  rows rightHalf " + rowsProfile(mx, R - inset));
  }

  // ---------- hosts ----------
  let reportDepth = 0, reports = 0, selfBW = null, idleDumped = false;
  const REPORT_CAP = 6;

  Interceptor.attach(VA(0x4219E0), {
    onEnter() { this.self = this.context.ecx; },
    onLeave() { log("[INIT] BattleWin_init self=" + sva(this.self) + " rects=" + bwRects(this.self) + " seeds=" + seeds() + " g=" + gNow()); }
  });

  Interceptor.attach(VA(0x422CC0), {
    onEnter() {
      const on = this.context.esp.add(4).readS32();
      log("[STATUS] BattleWin_on_status(" + on + ") ret=" + sva(this.returnAddress) + " big=" + BIG.readS32() + " g=" + gNow());
      if (on !== 0 && !idleDumped) { idleDumped = true; dumpStrip("idle_before_combat"); }
    }
  });

  function slide(name, va, sprVA) {
    Interceptor.attach(VA(va), {
      onEnter() {
        const sp = this.context.esp;
        this.flag = sp.add(8).readS32() & 0xFF;
        this.on = (this.flag & 2) !== 0;
        if (!this.on) return;
        log("[STATUS] " + name + "(win=" + sp.add(4).readPointer() + ", flag=" + this.flag + ") ret=" + sva(this.returnAddress) +
          " bezel sprite " + sva(VA(sprVA)) + "=" + spriteInfo(VA(sprVA)) + " at D3C=" + MAINWIN.add(0xD3C).readS32() + "," + MAINWIN.add(0xD40).readS32() +
          " big=" + BIG.readS32() + (patched ? " g_cr_armed=" + VA(0xA0C000 + 0x127A0).readS32() : ""));
      },
      onLeave() { if (this.on) { log("[STATUS] " + name + " leave big=" + BIG.readS32()); dumpStrip(name + "_leave"); } }
    });
  }
  slide("slide_show", 0x45D440, 0x7D177C);
  slide("slide_hide", 0x45D970, 0x7D1750);

  Interceptor.attach(VA(0x45C290), {
    onEnter() {
      if (!this.context.ecx.equals(MAINWIN)) return;
      log("[STATUS] MainWin_tile_panels ret=" + sva(this.returnAddress) + " big=" + BIG.readS32() + " clip=" + rect(STRIP.add(0x20)));
    }
  });

  Interceptor.attach(VA(0x421B50), {
    onEnter() {
      reportDepth++; reports++;
      this.log = reports <= REPORT_CAP;
      if (!this.log) return;
      const sp = this.context.esp, self = this.context.ecx; selfBW = self;
      const a = []; for (let i = 1; i <= 5; i++) a.push(sp.add(4 * i).readS32());
      log("\n[REPORT #" + reports + "] battle_report self=" + sva(self) + " args(att,def,a3,a4,flags)=" + a + " ret=" + sva(this.returnAddress) +
        " screen=" + SW.readS32() + "x" + SH.readS32() + " g=" + gNow() + " big=" + BIG.readS32());
      log("[REPORT] rects=" + bwRects(self));
      log("[REPORT] seeds=" + seeds());
      for (let k = 0; k < 2; k++) {
        try {
          const veh = a[k], fac = VA(0x952836).add(veh * 0x34).readU8(), proto = VA(0x952832).add(veh * 0x34).readS16();
          let spr;
          if (fac !== 0) spr = VA(0x78EDF0).add(fac * 0x65C);
          else spr = VA({ 9: 0x76DC30, 10: 0x78A4A0, 14: 0x779570, 15: 0x7AC000, 19: 0x787E70 }[proto] || 0x779200);
          log("[REPORT] side" + k + " veh=" + veh + " faction=" + fac + " proto=" + proto + " portrait=" + sva(spr) + spriteInfo(spr));
        } catch (e) { log("[REPORT] side" + k + " portrait read failed: " + e.message); }
      }
    },
    onLeave() {
      reportDepth--;
      if (!this.log) return;
      try {
        const s = stripGeom();
        if (s !== null && selfBW !== null) {
          measureBox(s, "portraitL(+50)", rect(selfBW.add(0x50)));
          measureBox(s, "portraitR(+60)", rect(selfBW.add(0x60)));
          measureBox(s, "unitL(+30)", rect(selfBW.add(0x30)));
          measureBox(s, "unitR(+40)", rect(selfBW.add(0x40)));
        }
      } catch (e) { log("[PIX] failed: " + e.message); }
      if (reports <= 3) dumpStrip("report" + reports + "_leave");
    }
  });

  function inReport(ra) {
    const v = ptr(ra).sub(TERRANX_BASE).add(0x400000).toUInt32();
    return reportDepth > 0 && reports <= REPORT_CAP && v >= REPORT_LO && v <= REPORT_HI;
  }
  function localFonts(ctx) {
    // at a callee ENTRY ebp is still battle_report's frame
    const bp = ctx.ebp;
    return "f0[ebp-C4]=" + fontInfo(bp.sub(0xC4)) + " f2[ebp-EC]=" + fontInfo(bp.sub(0xEC)) + " f1[ebp-9C]=" + fontInfo(bp.sub(0x9C));
  }
  let fontsLogged = 0;
  function textHost(name, va, kind) {
    Interceptor.attach(VA(va), {
      onEnter() {
        this.on = inReport(this.returnAddress) && this.context.ecx.equals(STRIP);
        if (!this.on) return;
        const sp = this.context.esp, str = sp.add(4).readPointer();
        let geo;
        if (kind === "rect") geo = "rect=" + rect(sp.add(8).readPointer());
        else geo = "x=" + sp.add(8).readS32() + " y=" + sp.add(12).readS32() + " w=" + sp.add(16).readS32();
        this.head = "[TEXT] " + name + " site=" + sva(this.returnAddress) + " " + geo + " str=" + cstr(str, 96) +
          " font=" + stripFont() + " clip=" + rect(STRIP.add(0x20));
        if (fontsLogged !== reports) { fontsLogged = reports; log("[FONTS] " + localFonts(this.context)); }
      },
      onLeave(rv) { if (this.on) log(this.head + " -> ret " + rv.toInt32()); }
    });
  }
  textHost("Buffer_wrap_3", 0x5DD730, "xyw");
  textHost("Buffer_wrap_cent_4", 0x5DD920, "xyw");
  textHost("Buffer_wrap_cent_6", 0x5DDAB0, "rect");

  Interceptor.attach(VA(0x5882F0), {
    onEnter() {
      this.on = inReport(this.returnAddress);
      if (this.on) { const sp = this.context.esp; this.a = sp.add(4).readS32() + "," + sp.add(8).readS32(); this.site = sva(this.returnAddress); }
    },
    onLeave(rv) { if (this.on) log("[TEXT] find_font(" + this.a + ") site=" + this.site + " -> " + fontInfo(rv)); }
  });

  Interceptor.attach(VA(0x5D8000), {
    onEnter() {
      if (!inReport(this.returnAddress) || !this.context.ecx.equals(STRIP)) return;
      log("[TEXT] Buffer_set_clip site=" + sva(this.returnAddress) + " rect=" + rect(this.context.esp.add(4).readPointer()));
    }
  });

  log("hosts armed. Fight ONE battle (attack with any unit), let the console slide back, then quit.");
}
