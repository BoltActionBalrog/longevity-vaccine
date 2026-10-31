"use strict";
// Frame-enlarge ground truth for the report screens (bake v3 residual: the row frame's RIGHT stroke
// lands 1px inside its rect at 4K and 1px outside at 1600 while top/bottom are exact).
// Logs every thunk_frame_enlarge (pcave2+0xBF80) call whose dest is the ReportWin canvas, the MainWin
// buffer or the HofWin canvas: src small buffer W/H, X/Y, num/den, g_fc_exact + g_faction_scratch_rect
// at entry, the band cells (pcave2+0xA200..0C: nx, ny, ex, ey), and AFTER the call the RENDERED extent:
// RLE of the dest row through the frame's vertical middle and the column through its horizontal
// middle (first/last non-key runs), so "covers [L, R')" vs "[L, R'-1]" vs "[L, R'+1]" is read off the
// pixels, not modelled. Also hooks the report helpers' callers so each enlarge is labelled.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_rw_frame_probe.log";
log("=== hook_rw_frame_probe.js started ===");
installAVHandler("rw_frame_probe");

if (requireBase()) {
  const PCAVE2 = 0xA0C000;
  const ENLARGE = PCAVE2 + 0xBF80, BANDMAP = PCAVE2 + 0xA210, HOLLOWFLAT = PCAVE2 + 0x140, DEVFILL = PCAVE2 + 0x42A0;
  const G_FC_EXACT = PCAVE2 + 0x2554, G_FSR = PCAVE2 + 0x1010, G_BAND = PCAVE2 + 0xA200;
  const G_SCALE = 0x668740, G_RW = 0x876478, G_HOF = 0x74DAF8, G_MAINBUF = 0x7AEC64, G_MODAL_TOP = 0x9B7AE0;
  const KEY = 9;
  const S = p => { try { return p.readS32(); } catch (e) { return -0x7fffffff; } };
  const hex = v => "0x" + (v >>> 0).toString(16);
  const staticVA = p => p.sub(globalThis.TERRANX_BASE).toUInt32() + 0x400000;
  const rect4 = p => [S(p), S(p.add(4)), S(p.add(8)), S(p.add(12))];
  function destTag(p) {
    const v = p.toUInt32();
    if (v === VA(G_RW).toUInt32() + 0x444) return "RWc";
    if (v === VA(G_HOF).toUInt32() + 0x444) return "HOFc";
    if (v === VA(G_MAINBUF).toUInt32()) return "MAIN";
    return hex(v);
  }
  function bufInfo(b) { return { data: b.add(0x54).readPointer(), pitch: S(b.add(0x4a8)), w: S(b.add(0x80)), h: -S(b.add(0x84)) }; }
  function rleRow(bi, y, x0, x1) {
    const out = []; let prev = -1, run = 0, start = 0;
    x0 = Math.max(0, x0); x1 = Math.min(bi.w, x1);
    if (y < 0 || y >= bi.h) return "y out of buffer";
    const row = bi.data.add(y * bi.pitch);
    for (let x = x0; x < x1; x++) {
      const v = row.add(x).readU8();
      if (v === prev) run++; else { if (prev >= 0) out.push([prev, start, run]); prev = v; start = x; run = 1; }
    }
    if (prev >= 0) out.push([prev, start, run]);
    return out;
  }
  function rleCol(bi, x, y0, y1) {
    const out = []; let prev = -1, run = 0, start = 0;
    y0 = Math.max(0, y0); y1 = Math.min(bi.h, y1);
    if (x < 0 || x >= bi.w) return "x out of buffer";
    for (let y = y0; y < y1; y++) {
      const v = bi.data.add(y * bi.pitch + x).readU8();
      if (v === prev) run++; else { if (prev >= 0) out.push([prev, start, run]); prev = v; start = y; run = 1; }
    }
    if (prev >= 0) out.push([prev, start, run]);
    return out;
  }
  const fmt = runs => (typeof runs === "string") ? runs : runs.map(r => r[0] + "x" + r[2] + "@" + r[1]).join(" ");
  const extent = runs => {
    if (typeof runs === "string") return runs;
    const nk = runs.filter(r => r[0] !== KEY);
    return nk.length ? "[" + nk[0][1] + ".." + (nk[nk.length - 1][1] + nk[nk.length - 1][2] - 1) + "]" : "none";
  };

  // label the caller chain: which report helper / thunk is on the stack
  let label = "";
  const CALLERS = [[PCAVE2 + 0x140, "hollow_flat"], [PCAVE2 + 0x42A0, "devfill"], [PCAVE2 + 0x22680, "t_dl_bmxt"]];
  for (const [va, name] of CALLERS) {
    Interceptor.attach(VA(va), {
      onEnter(args) {
        const g = S(VA(G_SCALE));
        if (g <= 16) return;
        this.ret = staticVA(this.context.esp.readPointer());
        const rp = args[0], rect = rect4(rp);
        label = name + "<-" + hex(this.ret) + " rect=(" + rect.join(",") + ")[" + (rect[2] - rect[0]) + "x" + (rect[3] - rect[1]) + "] dest=" + destTag(this.context.ecx) + " set=" + hex(staticVA(args[1]));
        this.lbl = label;
      },
      onLeave() { label = ""; }
    });
  }

  let n = 0;
  Interceptor.attach(VA(ENLARGE), {
    onEnter(args) {
      // thiscall: ecx = src (small scratch Buffer); stack: dest, key, X, Y, num, den
      this.dest = args[0]; this.tag = destTag(this.dest);
      if (this.tag.startsWith("0x")) { this.skip = true; return; }
      if (n++ > 400) { this.skip = true; return; }
      const src = bufInfo(this.context.ecx);
      this.X = S(args[2]); this.Y = S(args[3]); const num = S(args[4]), den = S(args[5]);
      const exact = S(VA(G_FC_EXACT)), fsr = rect4(VA(G_FSR));
      const band = [0, 4, 8, 12].map(o => S(VA(G_BAND).add(o)));
      this.dstW = exact ? fsr[2] - fsr[0] : Math.floor(src.w * num / den);
      this.dstH = exact ? fsr[3] - fsr[1] : Math.floor(src.h * num / den);
      log("ENLARGE#" + n + " " + label + " | src " + src.w + "x" + src.h + " -> dest " + this.tag + " X,Y=" + this.X + "," + this.Y + " n/d=" + num + "/" + den +
          " exact=" + exact + " fsr=(" + fsr.join(",") + ") band nx,ny,ex,ey=" + band.join(",") + " => dst " + this.dstW + "x" + this.dstH +
          " expected cover x[" + this.X + ".." + (this.X + this.dstW - 1) + "] y[" + this.Y + ".." + (this.Y + this.dstH - 1) + "]");
    },
    onLeave() {
      if (this.skip) return;
      try {
        const bi = bufInfo(this.dest);
        const ym = this.Y + (this.dstH >> 1), xm = this.X + (this.dstW >> 1);
        const row = rleRow(bi, ym, this.X - 4, this.X + this.dstW + 4);
        const col = rleCol(bi, xm, this.Y - 4, this.Y + this.dstH + 4);
        log("  RENDERED row y=" + ym + ": extent " + extent(row) + "  runs " + fmt(typeof row === "string" ? row : row.slice(0, 4)) + " ... " + fmt(typeof row === "string" ? row : row.slice(-4)));
        log("  RENDERED col x=" + xm + ": extent " + extent(col) + "  runs " + fmt(typeof col === "string" ? col : col.slice(0, 4)) + " ... " + fmt(typeof col === "string" ? col : col.slice(-4)));
      } catch (e) { log("  readback threw " + e); }
    }
  });
  log("attached: enlarge " + hex(ENLARGE) + " + 3 caller labels; g=" + S(VA(G_SCALE)));
}
