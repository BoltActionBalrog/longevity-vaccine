"use strict";
// DATALINKS-FROM-BASE CONSOLE RESIDUE probe -- observer only, plain fn-entry hosts only (entries
// verified undetoured on live exe bd2bae0b 2026-09-23; no patches.yaml site within entry-4..+16).
// Bug: base screen -> production right-click -> Help -> Datalinks article -> exit leaves HUD
// console-box residue in the band between the citizens row and the unit-stack box (shot
// screenshots\_Problems\DatalinksFromProd.png).
// Hypothesis (a): t_cr_snap_dl snaps a CORRECT band on entry (mode 3 -> 8), slide_show(…,2) re-tiles
// DC0 natively (band goes bad @site 0x45D913, big=1 passthrough), and on exit release_iface_mode
// pops idx BEFORE slide_hide's tile_panels @0x45DE41, so t_cr_tile sees mode 3 and its {0,4} gate
// skips the restore. Control: HUD -> Datalinks -> exit restores at 0x45DE41 with mode 0.
// Per event: iface mode stack, big, armed, the predicted t_cr_tile gate, and the GAP BAND
// (rows DA0.B..snapB, cols [L,R)) compared to the snapshot and to the band captured at DL entry.
// Strip dumps -> work\_dlhelp_probe\*.bin; render with: py scripts\_cmb_dump_to_png.py _dlhelp_probe
const STAMP = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
const OUTDIR = "D:/SmacxUi/work/_dlhelp_probe/";
globalThis.LOG_PATH = OUTDIR + "dl_help_stamp_" + STAMP + ".log";
log("=== hook_dl_help_stamp.js started ===");
installAVHandler("dl_help_stamp");
if (requireBase()) {
  const PCAVE2 = 0xA0C000, PCAVE2_END = 0xA0C000 + 0x40000;
  const G = VA(0x668740), PAL = VA(0x94C590);
  const MW = VA(0x7AE820), STRIP = VA(0x7AEC64);
  const CRBUF = VA(PCAVE2 + 0x12790), CRL = VA(PCAVE2 + 0x12794), CRR = VA(PCAVE2 + 0x12798),
    CRB = VA(PCAVE2 + 0x1279C), CRARM = VA(PCAVE2 + 0x127A0);
  const MODE_TAB = VA(0x7AE778), MODE_IDX = VA(0x7D392C), G_BIG = VA(0x7D3930);
  const cave0 = VA(PCAVE2), cave1 = VA(PCAVE2_END);
  const DL_MODE = 8;
  let lines = 0;
  const CAP = 3000;
  function L_(s) { if (lines < CAP) { lines++; log(s); } }

  function rect(p) { return [p.readS32(), p.add(4).readS32(), p.add(8).readS32(), p.add(12).readS32()]; }
  function modeAt(i) { return (i >= 0 && i < 16) ? MODE_TAB.add(i * 4).readS32() : -999; }
  function curMode() { return modeAt(MODE_IDX.readS32()); }
  function stack() {
    const i = MODE_IDX.readS32(), a = [];
    for (let k = 0; k <= i && k < 16; k++) a.push(modeAt(k));
    return "idx=" + i + " stack=[" + a.join(",") + "]";
  }
  function seeds() {
    return ["D80", 0xD80, "D90", 0xD90, "DA0", 0xDA0, "DB0", 0xDB0, "DC0", 0xDC0, "DD0", 0xDD0]
      .reduce((s, v, i, a) => (i % 2 ? s : s + a[i] + "=" + rect(MW.add(a[i + 1])).join(",") + " "), "");
  }
  // t_cr_tile v2b gate, predicted from live state (ecx==MainWin, armed==1, big==0, mode&0xFB==0)
  function gate(ecx) {
    const f = [];
    if (!ecx.equals(MW)) f.push("ecx");
    if (CRARM.readS32() !== 1) f.push("armed");
    if (G_BIG.readS32() !== 0) f.push("big");
    if ((curMode() & 0xFB) !== 0) f.push("mode" + curMode());
    return f.length ? "SKIP(" + f.join("+") + ")" : "RESTORE";
  }
  function state() {
    return "g=" + G.readS32() + " " + stack() + " big=" + G_BIG.readS32() + " armed=" + CRARM.readS32() +
      " snapLRB=" + CRL.readS32() + "," + CRR.readS32() + "," + CRB.readS32();
  }

  // ---------- strip + band ----------
  function stripGeom() {
    const bits = STRIP.add(0x54).readPointer();
    const pitch = STRIP.add(0x4A8).readS32();
    const w = STRIP.add(0x80).readS32();
    let h = STRIP.add(0x84).readS32(); if (h < 0) h = -h;
    if (bits.isNull() || pitch < w || pitch > w + 8 || w < 600) return null;
    return { bits: bits, pitch: pitch, w: w, h: h };
  }
  // the gap band: rows [DA0.bottom, snapB) x cols [snapL, snapR) (falls back to DB0.top if no snap)
  function bandRect() {
    const s = stripGeom(); if (s === null) return null;
    let L = CRL.readS32(), R = CRR.readS32(), B = CRB.readS32();
    const da0 = rect(MW.add(0xDA0)), db0 = rect(MW.add(0xDB0));
    if (R <= L || B <= 0) { L = rect(MW.add(0xD80))[2]; R = rect(MW.add(0xD90))[0]; B = db0[1] + 2; }
    const T = Math.max(0, da0[3]);
    if (R <= L || B <= T || R > s.w || B > s.h) return null;
    return { s: s, L: L, R: R, T: T, B: B };
  }
  function readBand() {
    const b = bandRect(); if (b === null) return null;
    const w = b.R - b.L, out = new Uint8Array(w * (b.B - b.T));
    for (let y = b.T; y < b.B; y++) out.set(new Uint8Array(b.s.bits.add(y * b.s.pitch + b.L).readByteArray(w)), (y - b.T) * w);
    return { r: b, px: out };
  }
  function hash(px) { let h = 2166136261; for (let i = 0; i < px.length; i++) { h ^= px[i]; h = Math.imul(h, 16777619); } return (h >>> 0).toString(16); }
  function hist(px) {   // top-4 palette indices: residue = black fill + frame-line colours, bezel = many greys
    const c = new Map(); for (let i = 0; i < px.length; i++) c.set(px[i], (c.get(px[i]) || 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(e => e[0] + ":" + (100 * e[1] / px.length).toFixed(0) + "%").join(" ") + " n=" + c.size;
  }
  function eqFrac(a, b) { if (!a || !b || a.length !== b.length) return "n/a"; let e = 0; for (let i = 0; i < a.length; i++) if (a[i] === b[i]) e++; return (100 * e / a.length).toFixed(1) + "%"; }
  function snapBand(b) {   // the same band rows out of g_cr_buf (snapshot rows 0..B-1, stride R-L)
    try {
      const buf = CRBUF.readPointer(); if (buf.isNull() || b === null) return null;
      const w = b.r.R - b.r.L, out = new Uint8Array(w * (b.r.B - b.r.T));
      for (let y = b.r.T; y < b.r.B; y++) out.set(new Uint8Array(buf.add(y * w).readByteArray(w)), (y - b.r.T) * w);
      return out;
    } catch (e) { return null; }
  }
  let enterBand = null;   // band captured at DL entry, before the snap and before slide_show
  function band(tag) {
    try {
      const b = readBand(); if (b === null) return "band=n/a";
      return "band[" + b.r.L + ".." + b.r.R + " x " + b.r.T + ".." + b.r.B + "] h=" + hash(b.px) +
        " ==snap " + eqFrac(b.px, snapBand(b)) + " ==entry " + eqFrac(b.px, enterBand ? enterBand.px : null) +
        " hist{" + hist(b.px) + "}";
    } catch (e) { return "band ERR " + e.message; }
  }

  // ---------- dumps ----------
  let dumpN = 0;
  const DUMP_CAP = 16;
  const tagCount = {};
  function dumpStrip(tag, perTag) {
    try {
      tagCount[tag] = (tagCount[tag] || 0) + 1;
      if (tagCount[tag] > (perTag || 1) || dumpN >= DUMP_CAP) return;
      const s = stripGeom(); if (s === null) return;
      const name = OUTDIR + "strip_" + STAMP + "_" + (dumpN++) + "_" + tag + "_" + s.w + "x" + s.h + ".bin";
      const f = new File(name, "wb");
      f.write(PAL.readByteArray(1024));
      for (let y = 0; y < s.h; y++) f.write(s.bits.add(y * s.pitch).readByteArray(s.w));
      f.flush(); f.close();
      L_("[DUMP] " + name + " clip=" + rect(STRIP.add(0x20)) + " big=" + G_BIG.readS32());
    } catch (e) { L_("[DUMP] failed: " + e.message); }
  }
  function dumpSnap(tag) {
    try {
      if (dumpN >= DUMP_CAP) return;
      const buf = CRBUF.readPointer(); if (buf.isNull()) return;
      const w = CRR.readS32() - CRL.readS32(), h = CRB.readS32();
      if (w <= 0 || h <= 0 || w > 4096 || h > 4096) return;
      const name = OUTDIR + "strip_" + STAMP + "_" + (dumpN++) + "_" + tag + "_" + w + "x" + h + ".bin";
      const f = new File(name, "wb");
      f.write(PAL.readByteArray(1024));
      f.write(buf.readByteArray(w * h));
      f.flush(); f.close();
      L_("[DUMP] " + name + " (g_cr_buf snapshot)");
    } catch (e) { L_("[DUMP snap] failed: " + e.message); }
  }
  let snapHashAtEnter = "";
  function snapHash() {
    try {
      const buf = CRBUF.readPointer(); if (buf.isNull()) return "nobuf";
      const n = (CRR.readS32() - CRL.readS32()) * CRB.readS32();
      if (n <= 0 || n > 16 << 20) return "bad";
      return hash(new Uint8Array(buf.readByteArray(n)));
    } catch (e) { return "ERR"; }
  }

  // ---------- hosts ----------
  let inDL = false, dlFromMode = -1;
  Interceptor.attach(VA(0x45C290), {          // MainWin_tile_panels(this, arg) RET 4
    onEnter() {
      const sp = this.context.esp;
      let site = this.returnAddress, wrapped = false;
      // t_cr_tile PASS-THROUGH jmps to us (ret = the real site); its RESTORE path CALLs us (ret in the cave)
      if (site.compare(cave0) >= 0 && site.compare(cave1) < 0) { wrapped = true; site = sp.add(8).readPointer(); }
      this.site = site;
      this.tag = "site=" + site + (wrapped ? " (t_cr_tile RESTORE path)" : " (direct/pass-through)") +
        " this=" + this.context.ecx + (this.context.ecx.equals(MW) ? "=MainWin" : "") + " arg=" + sp.add(4).readS32();
      L_("[TILE >] " + this.tag + " " + state() + " clip=" + rect(STRIP.add(0x20)) +
        " gate~" + gate(this.context.ecx) + " " + band());
    },
    onLeave() {
      // t_cr_tile's restore copy runs AFTER this native returns -> visible at the next event's band
      L_("[TILE <] " + this.tag + " " + band());
      if (inDL || dlFromMode >= 0) dumpStrip("tile_" + this.site.sub(TERRANX_BASE).toString(16) + "_m" + curMode(), 1);
    }
  });

  Interceptor.attach(VA(0x45D310), {          // SubInterface_set_iface_mode(this) -- pushes this+4 mode
    onEnter() {
      this.newMode = this.context.ecx.add(4).readS32();
      this.from = curMode();
      L_("[IFACE set >] this=" + this.context.ecx + " newMode=" + this.newMode + " ret=" + this.returnAddress + " " + state());
      if (this.newMode === DL_MODE) {
        enterBand = readBand();
        snapHashAtEnter = snapHash();
        L_("  DL ENTER from mode " + this.from + ": entry " + band());
        dumpStrip("dl_enter_pre_m" + this.from, 2);
      }
    },
    onLeave() {
      L_("[IFACE set <] newMode=" + this.newMode + " " + state() + " " + band());
      if (this.newMode === DL_MODE) {
        inDL = true; dlFromMode = this.from;
        const h = snapHash();
        L_("  snap " + (h !== snapHashAtEnter ? "FRESH" : "UNCHANGED") + " (" + snapHashAtEnter + " -> " + h + ")");
        dumpSnap("snap_from_m" + this.from);
        dumpStrip("dl_enter_post_m" + this.from, 2);
      }
    }
  });

  Interceptor.attach(VA(0x45D380), {          // SubInterface_release_iface_mode(this) -- pops idx, then on_mode(0)
    onEnter() {
      this.leaving = curMode();
      this.to = modeAt(MODE_IDX.readS32() - 1);
      L_("[IFACE release >] this=" + this.context.ecx + " leaving=" + this.leaving + " to=" + this.to +
        " ret=" + this.returnAddress + " " + state() + " " + band());
      if (this.leaving === DL_MODE) dumpStrip("dl_exit_pre_to_m" + this.to, 2);
    },
    onLeave() {
      L_("[IFACE release <] left=" + this.leaving + " " + state() + " " + band() +
        (this.leaving === DL_MODE ? "   <-- ==entry ~100% = restored; low = RESIDUE" : ""));
      if (this.leaving === DL_MODE) { dumpStrip("dl_exit_post_to_m" + this.to, 2); inDL = false; }
    }
  });

  Interceptor.attach(VA(0x44CB60), {          // help_topic(cat, item) cdecl -> DatalinkWin_open
    onEnter() {
      const sp = this.context.esp;
      const r = this.returnAddress.sub(TERRANX_BASE).toInt32();   // module-relative: 0x417DC8 -> 0x17DC8
      L_("[HELP topic] cat=" + sp.add(4).readS32() + " item=" + sp.add(8).readS32() + " ret=" + this.returnAddress +
        ([0x17DC8, 0x17DD8, 0x17E22].indexOf(r) >= 0 ? " = BaseWin_production picker Help" : "") + " " + state() + " " + band());
    }
  });

  Interceptor.attach(VA(0x45D970), {          // slide_hide(win, flags) cdecl; flags 2 = big-centre console tail
    onEnter() {
      const sp = this.context.esp;
      this.flags = sp.add(8).readS32();
      L_("[SLIDE_HIDE >] win=" + sp.add(4).readPointer() + " flags=" + this.flags + " ret=" + this.returnAddress + " " + state());
    },
    onLeave() { L_("[SLIDE_HIDE <] flags=" + this.flags + " " + state() + " " + band()); }
  });

  let baseRedraws = 0;
  Interceptor.attach(VA(0x41E790), {          // BaseWin_on_redraw (tile_panels(MainWin,1) @0x41E7AD)
    onEnter() { this.on = dlFromMode >= 0 && baseRedraws < 6; if (this.on) L_("[BASE redraw >] ret=" + this.returnAddress + " " + state()); },
    onLeave() {
      if (!this.on) return;
      L_("[BASE redraw <] " + band());
      if (baseRedraws++ < 2) dumpStrip("base_redraw_post", 2);
    }
  });

  L_("hosts armed; " + state() + " seeds " + seeds());
  L_("REPRO: (1) base screen -> right-click a production item -> Help -> exit Datalinks -> back at base;" +
     " (2) control: close base, HUD -> Datalinks -> exit.");
}
