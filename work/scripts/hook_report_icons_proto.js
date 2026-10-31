// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// hook_report_icons_proto.js v4 (2026-09-10) -- HQ report screens: console icon family, citizen faces,
// BASE STATUS row geometry. Runs on the BAKED build (rw_scale_kinds v1b, live 40f00bb3); every lever
// sits on TOP of the bake. v1 (2026-09-09) user-run at 1600/1920/4K: faces bracket OK, icon parity
// redraw OK on the 14 tab buttons + crest (banding gone), locator globe/grid still banded (census:
// 24x24 ReportWin FlatButtons through the 2D-zoom path), and the user reported the citizen faces not
// lining up with the row strokes (measured: box = s(40)+1 rows, face = floor(38g/16) -> 0..2 short).
//
// (1) CITIZENS faces: G bracket on the six blit_core sites the bake leaves native (specialists).
// (2) Console icon family (7 kind tabs, 7 faction tabs incl. crest): parity-preserving NN redraw
//     after Sprite_draw_2 (scaling_laws.parity_nn_row). v2: stripe phase on the PARENT's row grid via
//     the button's window rect top [btn+0x140] (v1 used +0x478 = 0: button-local).
// (3) v2 BASE LOCATOR globe/grid (ReportWin FlatButtons 0x883030 / 0x883B7C, 24x24 art, 2D-zoomed):
//     capture their 1:1 state-sprite draw, then after thunk_btn_stripes (the zoom pipeline's tail)
//     redraw the full-size canvas with the parity-preserving NN -- the same treatment as the tabs.
// (4) v2 BASE STATUS rows -- chrome follows content (scaling_laws.bases_row_cell/_pitch/_face_y_imm):
//     cell = 2K + floor(38g/16) poked over the three walker-scaled cell immediates (0x49D591 imm32,
//     0x49D622 / 0x49D62B imm8) and the face-y immediate (0x49E3FA imm8) after the bake's init walk;
//     + the 32 kinds K-frame sites (Buffer_box_sprite -> thunk_box_thick_devfill) get the half-open
//     -> inclusive R-1/B-1 the shared row frame already applies (t_rw_rowframe), so every K-frame on
//     the kinds pages draws exactly its rect (measured +1 row/col at every g).
// (5) CENSUS unchanged (every draw into a report-owned dest, once per (prim, ret, dest)).
//
// Attach set: function ENTRIES only -- Sprite_draw_2 0x5E4B4A, blit_core 0x5E4B9A, Buffer_draw_2
// 0x5D84C0, Buffer_draw 0x5D8370, Buffer_copy_3 0x5D9610, init_report_screen 0x4A3460 (the kinds
// proto's frame-retarget host; its onLeave runs AFTER t_rw_init_leave's walk), thunk_box_thick_devfill
// 0xA102A0 and thunk_btn_stripes 0xA0EFD0 (E8 helpers, entry attach). No call-site attaches, no
// engine calls from callbacks, every attach in try/catch.
//
// v3: (3) rewritten -- the locator buttons are BEVEL FlatButtons (3x20 caps + 67x20 body tile + an 18x18 icon at
//     1:1, then the 2D-zoom); the banded blue box is the body tile's dither pair, which no fe_pair_remap family
//     owns. Lever: capture the NATIVE 24x24 canvas at the zoom's Buffer_copy_3, census its row-dither pair, and
//     after thunk_btn_stripes rewrite that pair on the zoomed canvas to the device stripe law (pair_top member on
//     the top band, stripe phase on the parent grid) -- the fe_pair_remap law for one more family, logged so the
//     bake can hardcode it. (4a) also LOGS every K-frame rect at g=16 (no change) so a 1024x768 run measures
//     the native half-open convention per axis against the pristine shot (v2's R-1 made the row box 1 col
//     narrower than the law at 1600/1920 while B-1 was right).
// v4: the two ReportWin 24x24 buttons hold only dark pairs (C2/C5, F0/B9) at every draw -- the light-blue globe box
//     (53x31 native) is NOT theirs: the locator panel's globe/grid are MainWin HUD FlatButtons zoomed by the same 2D
//     pipeline. Lever (3) is now GENERIC: every button canvas the pipeline stretches (Buffer_copy_3 called from the
//     cave, src <= 128 px) is pair-censused; after thunk_btn_stripes any dominant pair that no fe_pair_remap family
//     owns is restriped on the parent grid. Finds the buttons (logged with their static VA + pair) and fixes them.
// Walk (1600x1200): F4 base status, GOVERNOR | BEST BASES, hover the globe/grid buttons, F2, F5, then quit: F4 base status -> PRODUCTION, CITIZENS (bottom row =
// Transcend), GARRISON; GOVERNOR | BEST BASES (locator buttons); click a kind tab, hover another;
// F2 / F5 / F7. Screenshot each, then quit. Log: D:\SmacxUi\work\frida_report_icons.log.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_report_icons.log";
log("=== hook_report_icons_proto.js v4 started ===");
installAVHandler("report_icons");

if (requireBase()) {
  const SL = globalThis.SL;
  const LAW_OK = !!(SL && SL.parityNnRow && SL.nnCenterIndex && SL.stripeParityVote && SL.basesRowCell && SL.basesFaceYImm);
  if (!LAW_OK) log("!! scaling_laws.js prelude lacks the v2 laws -- levers (2)(3)(4) DISARMED");

  const RI = 0x885F38, RW = 0x876478, RI_END = RI + 0x1E300, RW_END = RW + 0x10000, PC = 0xA0C000;
  const G_SCALE = 0x668740, G_NUM = 0x696D18, G_DEN = 0x696D1C, G_KEY = 0x696D14;
  const FT_LO = RI + 0x80, FT_HI = FT_LO + 7 * 0xB4C, KT_LO = RI + 0x5384, KT_HI = KT_LO + 7 * 0xB4C;
  const LOCATOR_BTNS = [RW + 0xCBB8, RW + 0xD704];          // 0x883030 / 0x883B7C (census v1: canvases 0x883474 / 0x883FC0)
  const DEVFILL = PC + 0x42A0, BTN_STRIPES = PC + 0x2FD0, BOX_SPRITE = 0x5E2DD3;
  const BOX_SITES = [0x49bdab, 0x49bdbb, 0x49bdcb, 0x49bddb, 0x49bdeb, 0x49bdfb,
    0x49d653, 0x49d663, 0x49d676, 0x49dad7, 0x49dae7, 0x49daf7, 0x49db18, 0x49db28, 0x49db8b,
    0x49ebbe, 0x49ebce, 0x49ef3b, 0x49ef56, 0x49f3b0, 0x49f3c0, 0x49fb79,
    0x4a0954, 0x4a0964, 0x4a0d7d, 0x4a0d98, 0x4a11b3, 0x4a11c3, 0x4a11d3, 0x4a228a, 0x4a229a, 0x4a22aa];
  const BOX_RETS = {}; for (const s of BOX_SITES) BOX_RETS[s + 5] = s;

  const S32 = p => { try { return p.readS32(); } catch (e) { return -0x7fffffff; } };
  const hex = v => "0x" + (v >>> 0).toString(16);
  const gNow = () => { const v = S32(VA(G_SCALE)); return v > 0 ? v : 16; };
  const sva = p => p.sub(globalThis.TERRANX_BASE).toUInt32() + 0x400000;
  const retOf = ctx => sva(ctx.esp.readPointer());
  const once = {};
  const L1 = (k, m) => { if (!once[k]) { once[k] = 1; log(m); } };
  function att(va, name, cb) {
    try { Interceptor.attach(VA(va), cb); log("attached " + name + " @" + hex(va)); }
    catch (e) { log("ATTACH FAIL " + name + " @" + hex(va) + ": " + e); }
  }
  const vaRI = VA(RI).toUInt32(), vaRIend = VA(RI_END).toUInt32(), vaRW = VA(RW).toUInt32(), vaRWend = VA(RW_END).toUInt32();
  const isReportDest = d => (d >= vaRI && d < vaRIend) || (d >= vaRW && d < vaRWend);
  const toStatic = d => d - vaRI + RI;
  const tabBtnOf = d => { const s = toStatic(d) - 0x444; return ((s >= FT_LO && s < FT_HI) || (s >= KT_LO && s < KT_HI)) ? d - 0x444 : 0; };
  const locatorBtnOf = d => { const s = toStatic(d) - 0x444; return LOCATOR_BTNS.indexOf(s) >= 0 ? d - 0x444 : 0; };

  // ---- (5) census ----------------------------------------------------------------------------
  const seen = {};
  function census(prim, c, dest, sig) {
    if (!isReportDest(dest)) return;
    const r = retOf(c); const k = prim + "@" + hex(r) + "/" + hex(dest);
    if (seen[k]) return; seen[k] = 1;
    const dp = ptr(dest);
    log("CENSUS " + prim + " ret=" + hex(r) + " dest=" + hex(toStatic(dest)) + (tabBtnOf(dest) ? "(tab btn)" : locatorBtnOf(dest) ? "(locator btn)" : "") +
        " canvas=" + S32(dp.add(0x80)) + "x" + (-S32(dp.add(0x84))) + " " + sig + " g=" + gNow());
  }
  const sprSig = (c, spr) => "spr blit=" + S32(spr.add(0x10)) + "x" + S32(spr.add(0x14)) + " canvas=" + S32(spr.add(0x18)) + "x" + S32(spr.add(0x1c)) +
    " off=" + S32(spr.add(0x20)) + "," + S32(spr.add(0x24)) + " key=" + S32(c.esp.add(8)) + " xy=" + S32(c.esp.add(0xC)) + "," + S32(c.esp.add(0x10)) +
    " n/d=" + S32(c.esp.add(0x14)) + "/" + S32(c.esp.add(0x18));
  const bufSig = (c, src, n) => "src buf=" + S32(src.add(0x80)) + "x" + (-S32(src.add(0x84))) + " args=" +
    Array.from({ length: n }, (_, i) => S32(c.esp.add(8 + 4 * i))).join(",");

  // ---- (1) faces: G bracket on the six unbracketed blit_core sites ---------------------------
  const FACE_RETS = { 0x49e4d6: "face@49E4D1", 0x49e572: "face@49E56D", 0x49e609: "face@49E604", 0x49e686: "face@49E681", 0x49e74a: "face@49E745", 0x49e972: "face@49E96D" };
  function gEnter(self, tag) {
    const gg = gNow(); if (gg <= 16) return;
    const N = VA(G_NUM), D = VA(G_DEN);
    self.gsave = [N.readS32(), D.readS32()]; N.writeS32(gg); D.writeS32(16);
    L1("G" + tag, "G bracket armed: " + tag + " g=" + gg);
  }
  function gLeave(self) { if (self.gsave) { VA(G_NUM).writeS32(self.gsave[0]); VA(G_DEN).writeS32(self.gsave[1]); self.gsave = null; } }
  att(0x5E4B9A, "blit_core (faces bracket + census)", {
    onEnter() {
      const c = this.context; const dest = c.esp.add(4).readU32();
      census("blit_core", c, dest, sprSig(c, c.ecx) + " G=" + S32(VA(G_NUM)) + "/" + S32(VA(G_DEN)));
      const t = FACE_RETS[retOf(c)]; if (t) gEnter(this, t);
    },
    onLeave() { gLeave(this); }
  });

  // ---- (2)+(3) parity-preserving sprite redraw into a FlatButton canvas ----------------------
  // j = { spr, btn (ptr), x, y, num, den, g }  -- canvas = btn+0x444, dims [btn+0x4C4] / -[btn+0x4C8]
  function redraw(j) {
    const spr = j.spr, sw = S32(spr.add(0x10)), sh = S32(spr.add(0x14));
    let pitch = S32(spr.add(0xC)); if (pitch <= 0) pitch = sw;
    if (sw <= 0 || sh <= 0 || sw > 512 || sh > 512 || pitch < sw) return "bad src dims";
    const data = spr.add(4).readPointer(); if (data.isNull()) return "null plane";
    const skey = spr.add(8).readU8();
    const offL = S32(spr.add(0x20)), offT = S32(spr.add(0x24));
    const dW = Math.floor(sw * j.num / j.den), dH = Math.floor(sh * j.num / j.den);
    const px = j.x + Math.floor(offL * j.num / j.den), py = j.y + Math.floor(offT * j.num / j.den);
    const dest = j.btn.add(0x444);
    const dData = dest.add(0x54).readPointer(), dPitch = S32(dest.add(0x4A8)), bw = S32(j.btn.add(0x4C4)), bh = -S32(j.btn.add(0x4C8));
    if (dData.isNull() || bw <= 0 || bh <= 0 || dPitch < bw || bw > 4096 || bh > 4096) return "bad dest " + bw + "x" + bh + " pitch " + dPitch;
    const pal = new Uint8Array(dest.add(0xA4).readByteArray(1024));
    const src = new Uint8Array(data.readByteArray(pitch * sh));
    let pe = 0, po = 0, se = 0, so = 0, ne = 0, no = 0;
    for (let y = 0; y < sh; y++) for (let x = 0; x < sw; x++) {
      const v = src[y * pitch + x]; if (v === skey) continue;
      const r = pal[v * 4 + 2], gch = pal[v * 4 + 1], b = pal[v * 4], pk = Math.max(r, gch, b), sm = r + gch + b;
      if (y & 1) { po += pk; so += sm; no++; } else { pe += pk; se += sm; ne++; }
    }
    const top = (ne && no) ? SL.stripeParityVote(pe / ne, po / no, se / ne, so / no) : -1;
    const btnTop = S32(j.btn.add(0x140));                                  // Win +0x13C rect: parent-local T (v2)
    const keyIdx = VA(G_KEY).readU8();
    const blank = new Uint8Array(bw).fill(keyIdx);
    for (let y = 0; y < bh; y++) dData.add(y * dPitch).writeByteArray(blank.buffer);
    const x0 = Math.max(px, 0), x1 = Math.min(px + dW, bw);
    if (x1 > x0) {
      const cols = new Int32Array(x1 - x0);
      for (let X = x0; X < x1; X++) cols[X - x0] = SL.nnCenterIndex(X - px, dW, sw);
      for (let dy = 0; dy < dH; dy++) {
        const Y = py + dy; if (Y < 0 || Y >= bh) continue;
        const sy = SL.parityNnRow(dy, dH, sh, btnTop + Y, j.g, top);
        const rowp = dData.add(Y * dPitch + x0);
        const seg = new Uint8Array(rowp.readByteArray(x1 - x0));
        const base = sy * pitch;
        for (let i = 0; i < seg.length; i++) { const v = src[base + cols[i]]; if (v !== skey) seg[i] = v; }
        rowp.writeByteArray(seg.buffer);
      }
    }
    return "ok src=" + sw + "x" + sh + " -> " + dW + "x" + dH + " at " + px + "," + py + " canvas " + bw + "x" + bh +
      " vote peak " + (pe / (ne || 1)).toFixed(1) + "/" + (po / (no || 1)).toFixed(1) + " -> top parity " + top +
      " rect=(" + [0, 4, 8, 12].map(k => S32(j.btn.add(0x13C + k))).join(",") + ") P=" + SL.stripePeriod(j.g, 0);
  }
  att(0x5E4B4A, "Sprite_draw_2 (icon redraw + census)", {
    onEnter() {
      const c = this.context; const dest = c.esp.add(4).readU32();
      census("Sprite_draw_2", c, dest, sprSig(c, c.ecx));
      const num = S32(c.esp.add(0x14)), den = S32(c.esp.add(0x18)), gg = gNow(), x = S32(c.esp.add(0xC)), y = S32(c.esp.add(0x10));
      const b = tabBtnOf(dest);
      if (LAW_OK && gg > 16 && b && num > den && den > 0)
        this.job = { spr: c.ecx, btn: ptr(b), x: x, y: y, num: num, den: den, g: gg, ret: retOf(c), btnva: toStatic(b) };
    },
    onLeave() {
      if (!this.job) return;
      const j = this.job; let r;
      try { r = redraw(j); } catch (e) { r = "ERR " + e; }
      L1("icon" + hex(j.btnva) + ":" + j.spr.toString(), "ICON btn=" + hex(j.btnva) + " spr=" + j.spr + " ret=" + hex(j.ret) + " n/d=" + j.num + "/" + j.den + " " + r);
    }
  });
  // (3) v4: GENERIC zoomed-button restripe -- census every canvas the 2D pipeline stretches, restripe unknown pairs
  const KNOWN_PAIRS = { "224:225": 1, "174:238": 1, "185:240": 1, "65:196": 1, "65:198": 1, "65:197": 1, "83:191": 1 };   // fe_pair_remap v7 families (E0/E1, AE/EE, F0/B9, C4/41, C6/41, C5/41, BF/53)
  const zoomNative = {}, zoomCount = {}, zoomRs = {};                    // canvas runtime ptr -> {a, b, top}
  function pairCensus(bytes, w, h, pitch, keyIdx) {
    const cnt = {};
    for (let x = 0; x < w; x++) for (let y = 0; y + 2 < h; y++) {
      const v0 = bytes[y * pitch + x], v1 = bytes[(y + 1) * pitch + x], v2 = bytes[(y + 2) * pitch + x];
      if (v0 === keyIdx || v1 === keyIdx || v0 === v1 || v0 !== v2) continue;          // a 2-row period: v0 v1 v0
      const k = (v0 < v1 ? v0 : v1) + ":" + (v0 < v1 ? v1 : v0); cnt[k] = (cnt[k] || 0) + 1;
    }
    return Object.keys(cnt).map(k => [k, cnt[k]]).sort((p, q) => q[1] - p[1]);
  }
  const vaPC = VA(PC).toUInt32(), vaPCend = VA(PC + 0x2B000).toUInt32();
  att(0x5D9610, "Buffer_copy_3 (census + zoomed-canvas pair census)", {
    onEnter() {
      const c = this.context; const dest = c.esp.add(4).readU32();
      census("Buffer_copy_3", c, dest, bufSig(c, c.ecx, 8));
      const r = c.esp.readPointer().toUInt32(); if (r < vaPC || r >= vaPCend || !LAW_OK || gNow() <= 16) return;   // the cave's KSB only
      const src = c.ecx, w = S32(src.add(0x80)), h = -S32(src.add(0x84)), pitch = S32(src.add(0x4A8));
      if (w <= 0 || h <= 0 || w > 128 || h > 128 || pitch < w) return;
      const data = src.add(0x54).readPointer(); if (data.isNull()) return;
      const bytes = new Uint8Array(data.readByteArray(pitch * h)); const keyIdx = VA(G_KEY).readU8();
      const pal = new Uint8Array(src.add(0xA4).readByteArray(1024));
      const rgb = i => [pal[i * 4 + 2], pal[i * 4 + 1], pal[i * 4]];
      const key = src.toString(); const cen = pairCensus(bytes, w, h, pitch, keyIdx);
      zoomCount[key] = (zoomCount[key] || 0) + 1; zoomNative[key] = null;
      const sv = src.toUInt32() - vaRI + RI;
      if (!cen.length) { if (zoomCount[key] <= 3) log("ZOOM canvas=" + hex(sv) + " #" + zoomCount[key] + " native " + w + "x" + h + ": no 2-row pair"); return; }
      const ab = cen[0][0].split(":").map(Number); const a = ab[0], b = ab[1]; const top = SL.pairTop(a, b, rgb); const known = !!KNOWN_PAIRS[cen[0][0]];
      zoomNative[key] = { a: a, b: b, top: top, known: known };
      if (zoomCount[key] <= 3) log("ZOOM canvas=" + hex(sv) + " #" + zoomCount[key] + " native " + w + "x" + h + " pairs " + cen.slice(0, 4).map(p => p[0] + "x" + p[1]).join(" ") +
         " -> " + hex(a) + "/" + hex(b) + " rgb " + rgb(a) + " / " + rgb(b) + " top=" + hex(top) + (known ? " (known family)" : " (UNKNOWN -> restripe)"));
    }
  });
  att(BTN_STRIPES, "thunk_btn_stripes (unknown-pair restripe)", {
    onEnter() { if (LAW_OK) this.btn = ptr(this.context.esi.toUInt32()); },
    onLeave() {
      if (!this.btn) return;
      const gg = gNow(); const btn = this.btn, dest = btn.add(0x444); const nat = zoomNative[dest.toString()];
      if (gg <= 16 || !nat || nat.known) return;
      const dData = dest.add(0x54).readPointer(), dPitch = S32(dest.add(0x4A8)), bw = S32(btn.add(0x4C4)), bh = -S32(btn.add(0x4C8));
      if (dData.isNull() || bw <= 0 || bh <= 0 || dPitch < bw || bw > 1024 || bh > 1024) return;
      const btnTop = S32(btn.add(0x140)); const mate = nat.top === nat.a ? nat.b : nat.a; let n = 0;
      for (let y = 0; y < bh; y++) {
        const want = SL.stripeTop(btnTop + y, gg, 0) ? nat.top : mate;
        const rowp = dData.add(y * dPitch); const seg = new Uint8Array(rowp.readByteArray(bw)); let ch = false;
        for (let x = 0; x < bw; x++) { const v = seg[x]; if ((v === nat.a || v === nat.b) && v !== want) { seg[x] = want; ch = true; n++; } }
        if (ch) rowp.writeByteArray(seg.buffer);
      }
      const k = dest.toString(); zoomRs[k] = (zoomRs[k] || 0) + 1;
      if (zoomRs[k] <= 3) log("RESTRIPE btn=" + hex(btn.toUInt32() - vaRI + RI) + " canvas " + bw + "x" + bh + " pair " + hex(nat.a) + "/" + hex(nat.b) + " top " + hex(nat.top) + " rewrote " + n + " px, P=" + SL.stripePeriod(gg, 0) + " btnTop=" + btnTop);
    }
  });

  // ---- (4) BASE STATUS rows: chrome follows content -------------------------------------------
  // (a) the 32 kinds K-frame sites: half-open rect -> inclusive renderer (R-1 / B-1, restored after)
  att(DEVFILL, "thunk_box_thick_devfill (kinds K-frames half-open fix)", {
    onEnter() {
      const c = this.context; const site = BOX_RETS[retOf(c)]; if (site === undefined) return;
      const rect = c.esp.add(4).readPointer(); const gg = gNow();
      L1("box" + hex(site) + "@" + gg, "K-frame rect @" + hex(site) + " g=" + gg + " rect=(" + [0, 4, 8, 12].map(k => S32(rect.add(k))).join(",") + ")" + (gg > 16 ? " -> R-1/B-1" : " (native, unchanged)"));
      if (gg <= 16) return;
      this.fix = { rect: rect, R: rect.add(8).readS32(), B: rect.add(12).readS32() };
      rect.add(8).writeS32(this.fix.R - 1); rect.add(12).writeS32(this.fix.B - 1);
    },
    onLeave() { if (this.fix) { this.fix.rect.add(8).writeS32(this.fix.R); this.fix.rect.add(12).writeS32(this.fix.B); } }
  });
  // (b) cell + face-y immediates, poked after the bake's init walk (init_report_screen's return)
  function pokeBasesRows() {
    const gg = gNow(); if (!LAW_OK || gg <= 16) { log("BASES rows: g=" + gg + " law=" + LAW_OK + " -> no poke"); return; }
    const cell = SL.basesRowCell(gg), imm = SL.basesFaceYImm(gg);
    const pokes = [[0x49D591, 4, cell, "cell imm32 (0x28)"], [0x49D622, 1, cell, "+cell x (0x28)"], [0x49D62B, 1, cell, "+cell y (0x28)"], [0x49E3FA, 1, imm, "face y imm (0x12)"]];
    for (const [va, w, v, nm] of pokes) {
      const p = VA(va); Memory.protect(p, 4, "rwx");
      const old = w === 4 ? p.readS32() : p.readS8();
      if (w === 4) p.writeS32(v); else p.writeS8(v);
      log("BASES rows poke " + nm + " @" + hex(va) + ": " + old + " -> " + v);
    }
    log("BASES rows: g=" + gg + " K=" + SL.strokeWidth(gg) + " face=" + SL.basesFaceH(gg) + " cell=" + cell + " pitch=" + SL.basesRowPitch(gg) + " yimm=" + imm);
  }
  att(0x4A3460, "init_report_screen (bases row pokes after the init walk)", { onLeave() { try { pokeBasesRows(); } catch (e) { log("BASES rows poke ERR " + e); } } });

  // ---- census-only entries -----------------------------------------------------------------------
  att(0x5D84C0, "Buffer_draw_2 (census)", { onEnter() { const c = this.context; census("Buffer_draw_2", c, c.esp.add(4).readU32(), bufSig(c, c.ecx, 5)); } });
  att(0x5D8370, "Buffer_draw (census)", { onEnter() { const c = this.context; census("Buffer_draw", c, c.esp.add(4).readU32(), bufSig(c, c.ecx, 3)); } });

  log("hook_report_icons_proto.js v4 armed: faces x6, icon parity redraw (FT/KT, parent grid), locator redraw x2, K-frame half-open x32, bases row pokes; g=" + gNow() + " law=" + LAW_OK);
}
