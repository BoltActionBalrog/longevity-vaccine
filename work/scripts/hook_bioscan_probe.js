"use strict";
// DIPLOMACY BIOSCAN figure probe -- OBSERVER ONLY, function-ENTRY hosts only.
// Host bytes verified on the live exe b67475a1 (2026-09-21, scripts\_disasm_live.py):
//   Flic_init        0x629E50  53 55 56          (plain)
//   Flic_draw_frame  0x62A070  56 8B F1          (plain)
//   Buffer_copy_3    0x5D9610  51 53 55 56       (plain; = GDI StretchBlt)
//   thunk_art_flic   pcave2+0x29F20 = 0xA35F20   83 3D .. (E8-called from the 3 diplo flic sites)
//   No uimod.dll / prax.dll detour sits on any of them (uimod hooks thunk_art_reblit's ENTRY -- not a host here).
//
// QUESTION.  Inside the diplomacy console strip the BIOSCAN figure's rect shows irregular scanline runs
// (2,2,2,2,1,1,4,2 measured at 1600x1200 on shot 20260921-003916) while the panel outside it is lawful
// (P=SL.stripePeriod(g) -> 2/1).  dip_?_n.flc is 61x146 with a KEY-9 background: the figure is meant to sit keyed over
// the panel.  t_dp_flicdraw (pcave2+0x12000) bounces each frame through a NATIVE scratch Buffer
// ([g_dp_scr_bio]), then Buffer_copy_3 stretches the WHOLE 61x146 rect by g/16 into the DiploTalkWin canvas,
// then thunk_art_flic re-blits that rect OPAQUE (key 0x100) through thunk_art_reblit.  What does the scratch
// hold where the art is key?
//   H1  the flic decodes in KEYED mode ([flic+0x5B4] bit1): key texels take the flic's OWN canvas patch
//       (Flic+4, captured from the already DEVICE-scaled dst at Flic_init) -> a device-density 2/1 stripe
//       patch is stretched x g/16 and parity-re-blitted -> irregular runs.   (scratch: no index 9, striped)
//   H2  the scratch keeps index 9 -> the opaque re-blit paints near-black over the panel. (scratch: index 9)
//   H3  the frame's own art paints navy/black rows behind the figure and the re-blit misplaces them.
//       (scratch: non-9 rows that also differ from the flic canvas patch)
// Every stage logs the SAME three dst columns (ref = just left of the rect, edge = backdrop strip inside the
// rect, mid = through the figure) as an index run-length + a dark/bright run string, so one run at ONE
// non-4K resolution decides H1/H2/H3 and shows at which stage the runs go irregular:
//   [INIT]        Flic_init args + the flic canvas patch after the capture
//   [DECODE]      Flic_draw_frame into the scratch: scratch census + columns + per-row key map
//   [STRETCH pre] dst columns under the rect BEFORE the StretchBlt (the lawful panel)
//   [STRETCH post] dst columns after the StretchBlt (before the re-blit)
//   [REBLIT post] dst columns after thunk_art_reblit (= what the screenshot shows)
// Run: run-frida-at-res.bat hook_bioscan_probe.js 1600 1200   (and 1920 1080, 3840 2160 for the control);
// open diplomacy with any faction, let the figure animate a few seconds, close it, quit.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_bioscan_" +
  new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + ".log";
log("=== hook_bioscan_probe.js started ===");
installAVHandler("bioscan");
if (requireBase()) {
  const PCAVE2 = 0xA0C000;
  const G = VA(0x668740);                                  // g_popup_scale_num
  const TW = 0x733990;                                     // DiploTalkWin
  const FLIC_NEWS = VA(TW + 0xAE8), FLIC_BIO = VA(TW + 0x15CC);
  const TW_CANVAS = VA(TW + 0x444);                        // GraphicWin canvas Buffer (draw-context buffer)
  const SCR_NEWS = VA(PCAVE2 + 0x1157C), SCR_BIO = VA(PCAVE2 + 0x11580);   // g_dp_scr_news / g_dp_scr_bio cells
  const FLIC_INIT = VA(0x629E50), FLIC_DRAW = VA(0x62A070), BUF_COPY_3 = VA(0x5D9610);
  const ART_FLIC = VA(PCAVE2 + 0x2D560);     // v2 (exe 70d8dc2f, 2026-09-21); was +0x29F20 on b67475a1
  const ART_BIOINIT = VA(PCAVE2 + 0x2D460), G_BIO_UNDER = VA(PCAVE2 + 0x2D6C0);
  const SITES = { 0x43F59B: "DiploTalkWin_open.news_first_draw", 0x43F231: "DiploTalkWin_bioscan_tick.draw",
                  0x43F274: "DiploTalkWin_news_tick.draw" };
  const KEY = 9;
  const CAP = 5000, FULL_PER_FLIC = 4, THIN_EVERY = 40;
  let lines = 0;
  const counts = { bio: 0, news: 0 };
  const seenIdx = new Set();

  function hx(p) { return "0x" + u32(p).toString(16); }
  function which(flic) { return flic.equals(FLIC_BIO) ? "bio" : flic.equals(FLIC_NEWS) ? "news" : null; }
  function scratchOf(tag) { return (tag === "bio" ? SCR_BIO : SCR_NEWS).readPointer(); }
  function out(s) { if (lines++ < CAP) log(s); }
  function g() { return G.readS32(); }
  function P() { return SL.stripePeriod(g(), 0); }         // lawful panel stripe pitch (scaling_laws.stripe_period)

  // ---- Buffer readers (data +0x54, w +0x80, h +0x84 NEGATIVE, pitch +0x4A8, RGBQUAD table +0xA4 b,g,r,0) ----
  function buf(p) {
    const h = p.add(0x84).readS32();
    return { p: p, data: p.add(0x54).readPointer(), w: p.add(0x80).readS32(), h: Math.abs(h), hraw: h,
             pitch: p.add(0x4A8).readS32() };
  }
  function bufStr(b) { return hx(b.p) + " data=" + hx(b.data) + " w=" + b.w + " h=" + b.hraw + " pitch=" + b.pitch; }
  function lumaTable(b) {                                  // 256 lumas from the buffer's own DIB colour table
    const t = new Uint8Array(b.p.add(0xA4).readByteArray(1024));
    const L = new Array(256);
    for (let i = 0; i < 256; i++) L[i] = (t[i * 4 + 2] * 299 + t[i * 4 + 1] * 587 + t[i * 4] * 114) / 1000;
    return { L: L, t: t };
  }
  function column(b, x, y0, y1) {
    const ys = Math.max(0, y0), ye = Math.min(b.h, y1);
    const v = new Uint8Array(Math.max(0, ye - ys));
    for (let y = ys; y < ye; y++) v[y - ys] = b.data.add(y * b.pitch + x).readU8();
    return { y0: ys, v: v };
  }
  function rle(v) {                                        // "c6*2 1f*1 ..."
    const o = [];
    let i = 0;
    while (i < v.length) {
      let j = i;
      while (j < v.length && v[j] === v[i]) j++;
      o.push(v[i].toString(16) + "*" + (j - i));
      seenIdx.add(v[i]);
      i = j;
    }
    return o.join(" ");
  }
  function darkBright(v, L) {                              // two-tone runs on luma vs the column's mid-range
    if (!v.length) return "";
    let lo = 255, hi = 0;
    for (const i of v) { lo = Math.min(lo, L[i]); hi = Math.max(hi, L[i]); }
    if (hi - lo < 8) return "flat";
    const mid = (lo + hi) / 2, runs = [];
    let cur = L[v[0]] > mid, n = 0;
    for (const i of v) { const b = L[i] > mid; if (b === cur) n++; else { runs.push((cur ? "B" : "d") + n); cur = b; n = 1; } }
    runs.push((cur ? "B" : "d") + n);
    return runs.join(",");
  }
  function colLine(stage, tag, b, name, x, y0, y1, L) {
    if (x < 0 || x >= b.w) { out("[" + stage + " " + tag + "] " + name + " x=" + x + " OUT OF BUFFER"); return; }
    const c = column(b, x, y0, y1);
    out("[" + stage + " " + tag + "] " + name + " x=" + x + " y=" + c.y0 + ".." + (c.y0 + c.v.length) +
        "  runs=" + darkBright(c.v, L) + "  idx=" + rle(c.v));
  }
  // three dst columns around the flic rect (dx,dy,dw,dh device): ref just LEFT of the rect, edge inside the
  // backdrop strip, mid through the figure; rows dy-4 .. dy+dh+4 so the seam with the panel is visible
  function dstColumns(stage, tag, dstp, dx, dy, dw, dh) {
    const b = buf(dstp), L = lumaTable(b).L;
    const m = Math.max(1, (2 * g()) >> 4);
    colLine(stage, tag, b, "ref ", dx - 4, dy - 4, dy + dh + 4, L);
    colLine(stage, tag, b, "edge", dx + m, dy - 4, dy + dh + 4, L);
    colLine(stage, tag, b, "mid ", dx + (dw >> 1), dy - 4, dy + dh + 4, L);
  }
  // scratch / canvas census: distinct indices, key-9 share, per-row key map (K = all key, k = some, . = none)
  function census(stage, tag, b, label) {
    const hist = new Uint32Array(256);
    let keyN = 0, rows = "";
    for (let y = 0; y < b.h; y++) {
      const r = new Uint8Array(b.data.add(y * b.pitch).readByteArray(b.w));
      let k = 0;
      for (const i of r) { hist[i]++; if (i === KEY) k++; }
      keyN += k;
      rows += (k === b.w) ? "K" : (k > 0) ? "k" : ".";
    }
    let distinct = 0;
    for (let i = 0; i < 256; i++) if (hist[i]) distinct++;
    out("[" + stage + " " + tag + "] " + label + " " + bufStr(b) + " distinct=" + distinct +
        " key9=" + keyN + "/" + (b.w * b.h) + " rowmap=" + rows);
  }
  function scratchColumns(stage, tag, b, L) {
    colLine(stage, tag, b, "col2 ", 2, 0, b.h, L);
    colLine(stage, tag, b, "colq ", b.w >> 2, 0, b.h, L);
    colLine(stage, tag, b, "colmid", b.w >> 1, 0, b.h, L);
  }
  function flicState(f) {
    return "key=" + f.readU8() + " flags=" + hx(f.add(0x5B4).readU32()) + " w=" + f.add(0x59C).readS32() +
      " h=" + f.add(0x5A0).readS32() + " dst=" + hx(f.add(0x5A8).readU32()) + " dstXY=" + f.add(0x5AC).readS32() +
      "," + f.add(0x5B0).readS32() + " frame=" + f.add(0xA10).readS32() +
      " dirty=" + [0x58C, 0x590, 0x594, 0x598].map(o => f.add(o).readS32()).join(",");
  }
  function dstTag(p) {
    if (p.equals(TW_CANVAS)) return "DiploTalkWin.canvas";
    if (p.equals(SCR_BIO.readPointer())) return "g_dp_scr_bio";
    if (p.equals(SCR_NEWS.readPointer())) return "g_dp_scr_news";
    return "?";
  }
  function palLine() {
    const b = buf(TW_CANVAS), t = lumaTable(b).t;
    const o = [];
    for (const i of Array.from(seenIdx).sort((a, c) => a - c))
      o.push(i.toString(16) + "=(" + t[i * 4 + 2] + "," + t[i * 4 + 1] + "," + t[i * 4] + ")");
    out("[PAL] DiploTalkWin.canvas +0xA4 rgb of every index seen: " + o.join(" "));
  }

  out("g=" + g() + " lawful panel P=" + P() + " TW.canvas=" + hx(TW_CANVAS) + " scr_bio=" + hx(SCR_BIO.readU32()) +
      " scr_news=" + hx(SCR_NEWS.readU32()));

  // ---- [INIT] Flic_init(this; dst, name, x, y, flag) RET 0x14 -- x,y already scaled by t_dp_flinit_* ----
  Interceptor.attach(FLIC_INIT, {
    onEnter() {
      this.tag = which(this.context.ecx);
      if (!this.tag) return;
      const sp = this.context.esp;
      this.f = this.context.ecx;
      let name = "?";
      try { name = sp.add(8).readPointer().readUtf8String(); } catch (e) {}
      out("[INIT " + this.tag + "] Flic_init dst=" + hx(arg(sp, 1)) + " (" + dstTag(sp.add(4).readPointer()) + ") name=" +
          name + " x,y=" + argS(sp, 3) + "," + argS(sp, 4) + " flag=" + argS(sp, 5) + " g=" + g());
    },
    onLeave() {
      if (!this.tag) return;
      const f = this.f;
      out("[INIT " + this.tag + "] after: " + flicState(f));
      try {                                                // Flic+4 = the flic's own canvas Buffer (bg patch)
        const cb = buf(f.add(4));
        if (!cb.data.isNull() && cb.w > 0 && cb.h > 0 && cb.w <= 1024 && cb.h <= 1024) {
          census("INIT", this.tag, cb, "flic.canvas(+4)");
          scratchColumns("INIT", this.tag, cb, lumaTable(buf(TW_CANVAS)).L);
        } else out("[INIT " + this.tag + "] flic.canvas(+4) " + bufStr(cb) + " (not readable)");
      } catch (e) { out("[INIT " + this.tag + "] flic.canvas ERR " + e.message); }
    }
  });

  // ---- [DECODE] Flic_draw_frame(this; x, y) RET 8 -- dst is the scratch when entered via t_dp_flicdraw ----
  Interceptor.attach(FLIC_DRAW, {
    onEnter() {
      this.tag = which(this.context.ecx);
      if (!this.tag) return;
      const n = ++counts[this.tag];
      this.full = n <= FULL_PER_FLIC;
      this.thin = !this.full && (n % THIN_EVERY === 0);
      if (!this.full && !this.thin) { this.tag = null; return; }
      const f = this.context.ecx, sp = this.context.esp;
      this.f = f;
      this.dst = f.add(0x5A8).readPointer();
      out("[DECODE " + this.tag + "] #" + n + " Flic_draw_frame x,y=" + argS(sp, 1) + "," + argS(sp, 2) +
          " from=" + hx(this.returnAddress) + " dst=" + dstTag(this.dst) + " " + flicState(f));
    },
    onLeave() {
      if (!this.tag) return;
      try {
        const b = buf(this.dst);
        if (this.dst.equals(TW_CANVAS)) { out("[DECODE " + this.tag + "] drew NATIVELY into the window canvas (no scratch)"); return; }
        census("DECODE", this.tag, b, "scratch");
        if (this.full) scratchColumns("DECODE", this.tag, b, lumaTable(buf(TW_CANVAS)).L);
      } catch (e) { out("[DECODE " + this.tag + "] ERR " + e.message); }
    }
  });

  // ---- [STRETCH] Buffer_copy_3(this=src; dst, sx, sy, sw, sh, dx, dy, dw, dh) = StretchBlt ----
  Interceptor.attach(BUF_COPY_3, {
    onEnter() {
      const src = this.context.ecx;
      this.tag = src.equals(SCR_BIO.readPointer()) ? "bio" : src.equals(SCR_NEWS.readPointer()) ? "news" : null;
      if (!this.tag) return;
      if (counts[this.tag] > FULL_PER_FLIC && counts[this.tag] % THIN_EVERY !== 0) { this.tag = null; return; }
      const sp = this.context.esp;
      this.dstp = sp.add(4).readPointer();
      this.r = [argS(sp, 6), argS(sp, 7), argS(sp, 8), argS(sp, 9)];
      out("[STRETCH " + this.tag + "] Buffer_copy_3 src=" + hx(src) + " dst=" + hx(this.dstp) + " (" + dstTag(this.dstp) +
          ") srcRect=" + [argS(sp, 2), argS(sp, 3), argS(sp, 4), argS(sp, 5)].join(",") + " dstRect=" + this.r.join(",") +
          " expect dw,dh=" + ((61 * g()) >> 4) + "," + ((146 * g()) >> 4) + " from=" + hx(this.returnAddress));
      dstColumns("STRETCH pre", this.tag, this.dstp, this.r[0], this.r[1], this.r[2], this.r[3]);
    },
    onLeave() {
      if (!this.tag) return;
      dstColumns("STRETCH post", this.tag, this.dstp, this.r[0], this.r[1], this.r[2], this.r[3]);
    }
  });

  // ---- [REBLIT] thunk_art_flic(this=flic; x, y) RET 8 -- after it returns the re-blit has run ----
  Interceptor.attach(ART_FLIC, {
    onEnter() {
      this.tag = which(this.context.ecx);
      if (!this.tag) return;
      const n = counts[this.tag] + 1;                      // this call's Flic_draw_frame is about to be #n
      if (n > FULL_PER_FLIC && n % THIN_EVERY !== 0) { this.tag = null; return; }
      const sp = this.context.esp;
      this.f = this.context.ecx;
      const site = u32(this.returnAddress);
      out("[REBLIT " + this.tag + "] thunk_art_flic x,y=" + argS(sp, 1) + "," + argS(sp, 2) + " site=" + hx(site) +
          " " + (SITES[site] || "?"));
    },
    onLeave() {
      if (!this.tag) return;
      const f = this.f;
      const dx = f.add(0x58C).readS32(), dy = f.add(0x590).readS32();
      const dw = f.add(0x594).readS32() - dx, dh = f.add(0x598).readS32() - dy;
      out("[REBLIT post " + this.tag + "] dirty rect " + [dx, dy, dw, dh].join(",") + " " + flicState(f));
      if (dw > 0 && dh > 0) dstColumns("REBLIT post", this.tag, f.add(0x5A8).readPointer(), dx, dy, dw, dh);
      if (counts[this.tag] + 1 === FULL_PER_FLIC) palLine();
    }
  });

  // ---- [BIOINIT] thunk_art_bioinit(this=flic; dst, name, x, y, flag) RET 0x14 -- v2 acceptance: canvas all 9 + save-under ----
  Interceptor.attach(ART_BIOINIT, {
    onEnter() { this.f = this.context.ecx; },
    onLeave() {
      try {
        const cb = buf(this.f.add(4));
        let nine = 0, n = 0;
        for (let y = 0; y < cb.h; y++) { const r = new Uint8Array(cb.data.add(y * cb.pitch).readByteArray(cb.w)); for (const i of r) { n++; if (i === KEY) nine++; } }
        const u = G_BIO_UNDER.readPointer();
        let us = "none";
        if (!u.isNull()) { const ub = buf(u); us = bufStr(ub); colLine("BIOINIT", "bio", ub, "under.col2", 2, 0, ub.h, lumaTable(buf(TW_CANVAS)).L); }
        out("[BIOINIT bio] flic.canvas key9=" + nine + "/" + n + " (want all)  save-under=" + us + " " + flicState(this.f));
      } catch (e) { out("[BIOINIT bio] ERR " + e.message); }
    }
  });

  setInterval(() => out("[alive] bio=" + counts.bio + " news=" + counts.news + " lines=" + lines), 10000);
  log("hooks installed: Flic_init, Flic_draw_frame, Buffer_copy_3, thunk_art_flic (" + hx(ART_FLIC) + "), thunk_art_bioinit (" + hx(ART_BIOINIT) + ")");
}
