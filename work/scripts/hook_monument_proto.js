// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// Planetary Monument -- SCALING PROTOTYPE v1 (Frida levers; see it in-game before any bake bytes).
// Static map: work\_mon_static_map.md.  Census proof (4K, 2026-09-13): work\frida_monument_census.log.
//
// LOOK (user decision 2026-09-13): the screen occupies the WHOLE display; the 1024x768 art is scaled
// UNIFORMLY to the full screen height (4:3 preserved), centred, black letterbox at the sides (and
// top/bottom when the g cap binds). No per-axis distortion anywhere.
//
// SCALE SOURCE (toggle): FULLHEIGHT=true  -> num/den = ScreenH/768 (exact full height; 2.8125 at 4K)
//                        FULLHEIGHT=false -> num/den = g/16 (the popup scale; 2.5 at 4K, 120-px bars top+bottom)
// Every scaled value = vanilla x num/den through SL.halfDown (scaling_laws.js, the one JS port). g<=16 -> no-op.
//
// LEVERS (all at clean hosts; hazard audit in _mon_probe_design.md):
//   W  window: after load_monicons -> GraphicWin_resize(MonWin, SW, SH, 1) [clean 0x5D5540], rect +0x13C := screen,
//      canvas cleared black (GraphicWin_clear, the build's own last step), content rect +0xA24.. := letterbox + s(112,84..).
//   T  rect tables A(17)/B(6)/C(7): dev = letterbox + s(native) where native = dev_vanilla - (112,84).
//   B  copy_4 -> copy_3 (GDI StretchBlt, centre-aligned NN; bilinear is a bake-stage upgrade) for the 4 monument
//      sites: FAR backdrop @0x4760E2, NEAR backdrop @0x4737E9, NEAR 600x360 picture @0x475F37 / @0x47605D.
//   G  SCALE_NUM_G/DEN_G bracket on Sprite_blit_scaled_core keyed on the 9 monument return sites (icons, picture,
//      banners, glyphs, emblem, 3 hover re-blits) -- the HOF-proto host (user-verified 2026-09-07).
//   N  buttons: MOVED to letterbox + s(824,747) at NATIVE size (face zoom + label font = bake stage, gate admission).
//   -  text: font is whatever [0x8A40BC] holds (the rw bake's scaled report font, 2.5x at 4K); rect/wrap from table A.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_monument_proto.log";
log("=== hook_monument_proto.js v7d started ===");
installAVHandler("monument_proto");

if (requireBase()) try {
  const FULLHEIGHT = true;

  const G_MONWIN = 0x7F9F58, OFF_CANVAS = 0x444, OFF_WINR = 0x474, OFF_WINPOS = 0x13C, OFF_CLIENT = 0x14C;
  const OFF_BTN0 = 0x0A58, OFF_BTN1 = 0x15A4, OFF_STATE = 0xA4C, OFF_SEL = 0xA54;
  const OFF_TBL_A = 0x3134, OFF_TBL_B = 0x334C, OFF_TBL_C = 0x366C;
  const VA_LOADMON = 0x472230, VA_MONDRAW = 0x4736E0, VA_MONUMENT = 0x476A50;
  const G_SCREENW = 0x9B7B1C, G_SCREENH = 0x9B7B20, G_SCALE = 0x668740, G_WIDE = 0x8A4168;
  const G_NUM = 0x696D18, G_DEN = 0x696D1C;
  const NAT_W = 1024, NAT_H = 768, ORG_X = 112, ORG_Y = 84;

  const S32 = p => { try { return p.readS32(); } catch (e) { return -0x7fffffff; } };
  const hex = v => "0x" + (v >>> 0).toString(16);
  const sva = p => p.sub(globalThis.TERRANX_BASE).toUInt32() + 0x400000;
  const retOf = ctx => sva(ctx.esp.readPointer());
  const MW = () => VA(G_MONWIN);
  const rect4 = p => [S32(p), S32(p.add(4)), S32(p.add(8)), S32(p.add(12))];
  const rstr = p => { const r = rect4(p); return "(" + r.join(",") + ")[" + (r[2] - r[0]) + "x" + (r[3] - r[1]) + "]"; };
  const wr4 = (p, r) => { for (let i = 0; i < 4; i++) p.add(4 * i).writeS32(r[i]); };
  const once = {}; const L1 = (k, m) => { if (!once[k]) { once[k] = 1; log(m); } };

  const SL = globalThis.SL;
  if (!SL || typeof SL.halfDown !== "function") log("!!! scaling_laws.js not loaded (SL.halfDown missing) -- run via run-frida-at-res.bat");

  // ---- scale state (recomputed at every load_monicons leave; the screen size never changes mid-session) ----
  let NUM = 1, DEN = 1, LX = 0, LY = 0, ARMED = false;
  const sc = v => (v >= 0 ? SL.halfDown(v * NUM, DEN) : -SL.halfDown(-v * NUM, DEN));
  function computeScale() {
    const g = S32(VA(G_SCALE)), SW = S32(VA(G_SCREENW)), SH = S32(VA(G_SCREENH));
    if (g <= 16 || S32(VA(G_WIDE)) === 0) { NUM = 1; DEN = 1; LX = 0; LY = 0; ARMED = false; return; }
    // den is ALWAYS 16: the engine's sprite scaler and our baked Sprite_draw_2 chain (thunk_hudmenu_sd2 ->
    // thunk_portrait_avg) assume n/16; v2's 2160/768 overran the dest (AV inside Buffer_draw_2, then a heap-corruption
    // crash in Win_update_screen). Full height = floor(16*SH/768)/16 = the UNCLAMPED popup g (45 at 4K, 25 at 1600, 22 at 1080p).
    if (FULLHEIGHT) { NUM = Math.floor(16 * SH / NAT_H); DEN = 16; } else { NUM = g; DEN = 16; }
    if (NUM <= 16) { NUM = 1; DEN = 1; LX = 0; LY = 0; ARMED = false; return; }
    LX = (SW - sc(NAT_W)) >> 1; LY = (SH - sc(NAT_H)) >> 1;
    ARMED = true;
    log("PROTO scale: g=" + g + " screen=" + SW + "x" + SH + " num/den=" + NUM + "/" + DEN + " (" + (NUM / DEN).toFixed(4) +
        ") content " + sc(NAT_W) + "x" + sc(NAT_H) + " letterbox=(" + LX + "," + LY + ")");
  }

  // ---- engine calls (clean entries; NativeFunction from onLeave is the proven HOF-proto shape) ----
  const gwResize = new NativeFunction(VA(0x5D5540), "int", ["pointer", "int", "int", "int"], "thiscall");
  const gwClear = new NativeFunction(VA(0x5D5250), "void", ["pointer", "int"], "thiscall");
  const findFont = new NativeFunction(VA(0x5882F0), "pointer", ["int", "int"]);   // cdecl(size, style) = Frida's default ia32 ABI ("cdecl" is NOT a valid abi name: v4-v4e died silently here)
  const COPY4 = VA(0x5DFF00), COPY3 = VA(0x5D9610);
  const copy4 = new NativeFunction(COPY4, "int", ["pointer", "pointer", "int", "int", "int", "int", "int", "int"], "thiscall");
  const copy3 = new NativeFunction(COPY3, "int", ["pointer", "pointer", "int", "int", "int", "int", "int", "int", "int", "int"], "thiscall");
  // B lever history: v1 copy_3 (GDI StretchBlt) colour-matched across the two DIB colour tables -> monzoom's purple key
  // window became palette index 9 (transparent: the map showed through), the FLC's became grey. v2 Buffer_draw_2 with
  // num/den 2160/768 overran the dest (AV) -> heap corruption -> crash in Win_update_screen. v3: a self-contained
  // INDEX-PRESERVING nearest-neighbour blit in JS (floor phase, dest-clipped, sub-rect capable). ~1 s per full backdrop
  // at 4K in QuickJS -- prototype only; the bake uses a cave thunk (scale_nn / bilinear class) with den 16.
  function nnBlit(src, dest, sx, sy, sw, sh, dx, dy, dw, dh) {
    const sPitch = S32(src.add(0x4a8)), sData = src.add(0x54).readPointer();
    const dPitch = S32(dest.add(0x4a8)), dW = S32(dest.add(0x80)), dH = -S32(dest.add(0x84)), dData = dest.add(0x54).readPointer();
    if (sData.isNull() || dData.isNull() || sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0) { log("PROTO nnBlit: bad args"); return; }
    const x0 = Math.max(dx, 0), y0 = Math.max(dy, 0), x1 = Math.min(dx + dw, dW), y1 = Math.min(dy + dh, dH);
    if (x1 <= x0 || y1 <= y0) { log("PROTO nnBlit: fully clipped"); return; }
    const n = x1 - x0, colmap = new Int32Array(n), row = new Uint8Array(n);
    for (let i = 0; i < n; i++) colmap[i] = Math.min(sw - 1, Math.floor((x0 - dx + i) * sw / dw));
    let lastSy = -1, srcRow = null;
    for (let y = y0; y < y1; y++) {
      const syy = sy + Math.min(sh - 1, Math.floor((y - dy) * sh / dh));
      if (syy !== lastSy) { srcRow = new Uint8Array(sData.add(syy * sPitch + sx).readByteArray(sw)); lastSy = syy; }
      for (let i = 0; i < n; i++) row[i] = srcRow[colmap[i]];
      dData.add(y * dPitch + x0).writeByteArray(row.buffer);
    }
  }

  // v6 RESAMPLER (user decision 2026-09-13: options C/D): separable Lanczos-3 (KERNEL="lanczos3") or bilinear
  // ("bilinear") enlarge in RGB, then Floyd-Steinberg error-diffusion into the DEST palette at device density.
  // Source/dest are 8-bpp index planes with their own DIB colour tables (+0xA4, b,g,r,x); the 15-bit LUT maps
  // averaged RGB to the nearest dest index (never the key 9). No static storage in the CModule (read-only here);
  // every table lives in JS-allocated retained pages. Kernel tap tables are built in JS (Math.sin) per (src,dst) size.
  const KERNEL = "lanczos3";      // "lanczos3" (D) | "bilinear" (C)
  const DITHER = 1;               // 1 = error diffusion at device density, 0 = nearest palette match (proto v4e look)
  let cm = null, resample = null, buildLut = null;
  try {
    cm = new CModule(`
      typedef unsigned char u8;
      int probe_r(const u8* p) { return p[0] + p[1023]; }
      void probe_w(u8* p) { p[0] = 1; p[32767] = 2; }
      void build_lut(const u8* pal, u8* lut) {
        int i, k;
        for (i = 0; i < 32768; i++) {
          int r = (i >> 10) & 31, g = (i >> 5) & 31, b = i & 31;
          int best = 0, bd = 1 << 30;
          r = (r << 3) | (r >> 2); g = (g << 3) | (g >> 2); b = (b << 3) | (b >> 2);
          for (k = 0; k < 256; k++) {
            int db, dg, dr, d;
            if (k == 9) continue;
            db = pal[k * 4] - b; dg = pal[k * 4 + 1] - g; dr = pal[k * 4 + 2] - r;
            d = dr * dr + dg * dg + db * db;
            if (d < bd) { bd = d; best = k; }
          }
          lut[i] = (u8)best;
        }
      }
      /* separable resample: horizontal pass into tmp (12-bit per channel, signed for ringing), vertical pass + FS dither */
      void resample(const u8* src, int spitch, int sx, int sy, int sw, int sh, const u8* spal,
                    u8* dst, int dpitch, int dW, int dH, int dx, int dy, int dw, int dh, const u8* dpal, const u8* lut,
                    int taps, const int* cidx, const short* cw, const int* ridx, const short* rw,
                    short* tmp, int* err, int dither) {
        int x0, y0, x1, y1, r, i, t, j, ew;
        int *e0, *e1, *es;
        if (sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0 || dw > 4096 || sh > 768 || dh > 2200 || taps > 6) return;
        x0 = dx < 0 ? 0 : dx; y0 = dy < 0 ? 0 : dy; x1 = dx + dw > dW ? dW : dx + dw; y1 = dy + dh > dH ? dH : dy + dh;
        for (r = 0; r < sh; r++) {
          const u8* row = src + (sy + r) * spitch + sx;
          short* o = tmp + r * dw * 3;
          for (i = 0; i < dw; i++) {
            int ab = 0, ag = 0, ar = 0;
            const int* ci = cidx + i * taps; const short* wt = cw + i * taps;
            for (t = 0; t < taps; t++) { const u8* p = spal + row[ci[t]] * 4; int w = wt[t]; ab += p[0] * w; ag += p[1] * w; ar += p[2] * w; }
            o[i * 3] = (short)(ab >> 4); o[i * 3 + 1] = (short)(ag >> 4); o[i * 3 + 2] = (short)(ar >> 4);
          }
        }
        ew = dw + 2; e0 = err; e1 = err + ew * 3;
        for (i = 0; i < ew * 3; i++) { e0[i] = 0; e1[i] = 0; }
        for (j = 0; j < dh; j++) {
          int y = dy + j;
          const int* ri = ridx + j * taps; const short* wt = rw + j * taps;
          u8* d = dst + y * dpitch;
          for (i = 0; i < ew * 3; i++) e1[i] = 0;
          for (i = 0; i < dw; i++) {
            int x = dx + i, ab = 0, ag = 0, ar = 0, b, g, rr, idx;
            for (t = 0; t < taps; t++) { const short* p = tmp + (ri[t] * dw + i) * 3; int w = wt[t]; ab += p[0] * w; ag += p[1] * w; ar += p[2] * w; }
            b = ab >> 12; g = ag >> 12; rr = ar >> 12;
            if (dither) { b += e0[(i + 1) * 3] >> 4; g += e0[(i + 1) * 3 + 1] >> 4; rr += e0[(i + 1) * 3 + 2] >> 4; }
            if (b < 0) b = 0; if (b > 255) b = 255; if (g < 0) g = 0; if (g > 255) g = 255; if (rr < 0) rr = 0; if (rr > 255) rr = 255;
            idx = lut[((rr >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)];
            if (y >= y0 && y < y1 && x >= x0 && x < x1) d[x] = (u8)idx;
            if (dither) {
              const u8* q = dpal + idx * 4;
              int eb = (b - q[0]) * 16, eg = (g - q[1]) * 16, er = (rr - q[2]) * 16;
              e0[(i + 2) * 3] += eb * 7 / 16; e0[(i + 2) * 3 + 1] += eg * 7 / 16; e0[(i + 2) * 3 + 2] += er * 7 / 16;
              e1[i * 3] += eb * 3 / 16; e1[i * 3 + 1] += eg * 3 / 16; e1[i * 3 + 2] += er * 3 / 16;
              e1[(i + 1) * 3] += eb * 5 / 16; e1[(i + 1) * 3 + 1] += eg * 5 / 16; e1[(i + 1) * 3 + 2] += er * 5 / 16;
              e1[(i + 2) * 3] += eb / 16; e1[(i + 2) * 3 + 1] += eg / 16; e1[(i + 2) * 3 + 2] += er / 16;
            }
          }
          es = e0; e0 = e1; e1 = es;
        }
      }
    `);
    globalThis.MON_CM = cm;   // RETAIN: the CModule's code is freed the moment its last JS reference dies (v4b-v4d lesson)
    buildLut = new NativeFunction(cm.build_lut, "void", ["pointer", "pointer"]);
    globalThis.MON_PROBE_R = new NativeFunction(cm.probe_r, "int", ["pointer"]);
    globalThis.MON_PROBE_W = new NativeFunction(cm.probe_w, "void", ["pointer"]);
    resample = new NativeFunction(cm.resample, "void",
      ["pointer", "int", "int", "int", "int", "int", "pointer", "pointer", "int", "int", "int", "int", "int", "int", "int", "pointer", "pointer",
       "int", "pointer", "pointer", "pointer", "pointer", "pointer", "pointer", "int"]);
    log("PROTO CModule resampler compiled (kernel=" + KERNEL + " dither=" + DITHER + ")");
  } catch (e) { log("PROTO CModule FAILED (" + e + ") -- falling back to the JS NN blit"); cm = null; }
  let lutBuilt = false;
  const TAPS = KERNEL === "bilinear" ? 2 : 6;
  // retained scratch: LUT 32K, tmp 4096x768x3 int16, err 2x(4096+2)x3 int32, col/row tap tables (6 taps), self-test pal
  globalThis.MON_SCRATCH = [Memory.alloc(32768), Memory.alloc(4096 * 768 * 3 * 2), Memory.alloc(2 * 4098 * 3 * 4),
                            Memory.alloc(4096 * 6 * 4), Memory.alloc(4096 * 6 * 2), Memory.alloc(2200 * 6 * 4), Memory.alloc(2200 * 6 * 2), Memory.alloc(1024)];
  const LUT = MON_SCRATCH[0], TMP = MON_SCRATCH[1], ERR = MON_SCRATCH[2], CIDX = MON_SCRATCH[3], CW = MON_SCRATCH[4], RIDX = MON_SCRATCH[5], RW = MON_SCRATCH[6];
  // kernel tap tables (JS): centre-aligned, edge-clamped, weights normalised to 256
  const tapCache = {};
  function kern(x) {
    const ax = Math.abs(x);
    if (KERNEL === "bilinear") return ax < 1 ? 1 - ax : 0;
    if (ax >= 3) return 0; if (ax < 1e-6) return 1;
    const px = Math.PI * x; return 3 * Math.sin(px) * Math.sin(px / 3) / (px * px);
  }
  function taps(nSrc, nDst) {
    const key = nSrc + ":" + nDst;
    if (tapCache[key]) return tapCache[key];
    const idx = new Int32Array(nDst * TAPS), wts = new Int16Array(nDst * TAPS);
    for (let i = 0; i < nDst; i++) {
      const c = (i + 0.5) * nSrc / nDst - 0.5, base = Math.floor(c) - (TAPS / 2 - 1);
      const w = []; let sum = 0;
      for (let t = 0; t < TAPS; t++) { const v = kern(c - (base + t)); w.push(v); sum += v; }
      let isum = 0, imax = 0;
      for (let t = 0; t < TAPS; t++) { const q = Math.round(256 * w[t] / sum); wts[i * TAPS + t] = q; isum += q; if (Math.abs(q) > Math.abs(wts[i * TAPS + imax])) imax = t; }
      wts[i * TAPS + imax] += 256 - isum;
      for (let t = 0; t < TAPS; t++) idx[i * TAPS + t] = Math.min(nSrc - 1, Math.max(0, base + t));
    }
    return (tapCache[key] = { idx: idx.buffer, wts: wts.buffer });
  }
  function ensureLut(dest) { if (!lutBuilt) { buildLut(dest.add(0xA4), LUT); lutBuilt = true; } }
  function doResample(sData, sPitch, sx, sy, sw, sh, spal, dest, dx, dy, dw, dh, what) {
    const dPitch = S32(dest.add(0x4a8)), dW = S32(dest.add(0x80)), dH = -S32(dest.add(0x84)), dData = dest.add(0x54).readPointer();
    if (dData.isNull() || sData.isNull()) { log("PROTO resample " + what + ": null data"); return false; }
    if (dw > 4096 || sh > 768 || dh > 2200) { log("PROTO resample " + what + ": size out of scratch range " + dw + "x" + dh + " sh=" + sh); return false; }
    ensureLut(dest);
    const ct = taps(sw, dw), rt = taps(sh, dh);
    CIDX.writeByteArray(ct.idx); CW.writeByteArray(ct.wts); RIDX.writeByteArray(rt.idx); RW.writeByteArray(rt.wts);
    resample(sData, sPitch, sx, sy, sw, sh, spal, dData, dPitch, dW, dH, dx, dy, dw, dh, dest.add(0xA4), LUT, TAPS, CIDX, CW, RIDX, RW, TMP, ERR, DITHER);
    return true;
  }
  // Buffer -> Buffer enlarge (backdrops, near picture); source colour table = the source Buffer's own (+0xA4)
  function bufBlit(src, dest, sx, sy, sw, sh, dx, dy, dw, dh) {
    if (!resample) return nnBlit(src, dest, sx, sy, sw, sh, dx, dy, dw, dh);
    const sPitch = S32(src.add(0x4a8)), sData = src.add(0x54).readPointer();
    L1("bufargs", "PROTO bufBlit args src=" + src + " data=" + sData + " pitch=" + sPitch + " s(" + sx + "," + sy + " " + sw + "x" + sh + ") dest=" + dest + " d(" + dx + "," + dy + " " + dw + "x" + dh + ")");
    // source colours come from the DEST (display) table: vanilla copies these indices 1:1, so both share the game palette;
    // the FLC still's own +0xA4 table is NOT the display palette (Buffer_init'd, never synced) -> v6 rendered it all blue
    try { if (!doResample(sData, sPitch, sx, sy, sw, sh, dest.add(0xA4), dest, dx, dy, dw, dh, "buf")) nnBlit(src, dest, sx, sy, sw, sh, dx, dy, dw, dh); }
    catch (e) { log("PROTO resample(buf) FAILED " + e); nnBlit(src, dest, sx, sy, sw, sh, dx, dy, dw, dh); }
  }
  // Sprite (data +0x4, stride +0x10, w +0x18, h +0x1c; game palette) -> Buffer enlarge (the far picture; opaque art only)
  function sprBlit(spr, dest, dx, dy, dw, dh) {
    if (!resample) return;
    const sData = spr.add(0x4).readPointer(), sPitch = S32(spr.add(0x10)), sw = S32(spr.add(0x18)), sh = S32(spr.add(0x1c));
    if (sData.isNull() || sw <= 0 || sh <= 0 || sPitch < sw) { log("PROTO sprBlit: bad sprite " + sw + "x" + sh + " pitch " + sPitch); return; }
    L1("sprargs", "PROTO sprBlit args spr=" + spr + " data=" + sData + " pitch=" + sPitch + " " + sw + "x" + sh + " dest=" + dest + " d(" + dx + "," + dy + " " + dw + "x" + dh + ")");
    try { doResample(sData, sPitch, 0, 0, sw, sh, dest.add(0xA4), dest, dx, dy, dw, dh, "spr"); }
    catch (e) { log("PROTO resample(spr) FAILED " + e); }
  }
  if (resample) {
    try {
      const pal = MON_SCRATCH[7], S = Memory.alloc(64 * 32), D = Memory.alloc(256 * 128), SB = Memory.alloc(0x500), DB = Memory.alloc(0x500);
      MON_SCRATCH.push(S, D, SB, DB);
      for (let i = 0; i < 256; i++) { pal.add(i * 4).writeU8(i); pal.add(i * 4 + 1).writeU8(i); pal.add(i * 4 + 2).writeU8(i); }
      for (let y = 0; y < 32; y++) for (let x = 0; x < 64; x++) S.add(y * 64 + x).writeU8(x * 4);
      // fake Buffers: data +0x54, w +0x80, h +0x84 (neg), pitch +0x4a8, pal +0xA4
      SB.add(0x54).writePointer(S); SB.add(0x80).writeS32(64); SB.add(0x84).writeS32(-32); SB.add(0x4a8).writeS32(64); Memory.copy(SB.add(0xA4), pal, 1024);
      DB.add(0x54).writePointer(D); DB.add(0x80).writeS32(256); DB.add(0x84).writeS32(-128); DB.add(0x4a8).writeS32(256); Memory.copy(DB.add(0xA4), pal, 1024);
      bufBlit(SB, DB, 0, 0, 64, 32, 10, 10, 200, 100);
      lutBuilt = false;
      log("PROTO CModule self-test OK: sample row=" + Array.from(new Uint8Array(D.add(50 * 256 + 10).readByteArray(24))).join(","));
    } catch (e) { log("PROTO CModule self-test FAILED: " + e + " -> JS NN fallback"); resample = null; }
  }
  // Blue text panel: regenerated scanlines at device density (scaling-frames s7: P=SL.stripePeriod(g), light rows on top
  // hN=(P+1)>>1). Detected per blit from the SOURCE (rows where index 230 covers >= 300 px = the light rows; the
  // dark rows between them are dithered dark blues -> mapped NN from the matching native dark row). Never hardcoded
  // (s7 state rule); both monzoom variants carry rows 127..174.
  function synthPanel(src, dest, dx, dy, dw, dh) {
    try {
      const sPitch = S32(src.add(0x4a8)), sData = src.add(0x54).readPointer(), sw = S32(src.add(0x80)), sh = -S32(src.add(0x84));
      const dPitch = S32(dest.add(0x4a8)), dW = S32(dest.add(0x80)), dH = -S32(dest.add(0x84)), dData = dest.add(0x54).readPointer();
      // PALETTE-INDEPENDENT detection (the engine remaps every asset into the game palette on load, so the art's
      // index 230 is some other index at runtime): a light row = a row where ONE index covers >= 300 px; the panel =
      // the longest run of such rows spaced exactly 2 apart sharing that index (the s7 per-draw detection rule).
      const dom = [];
      for (let y = 0; y < sh; y++) {
        const row = new Uint8Array(sData.add(y * sPitch).readByteArray(sw));
        const cnt = new Int32Array(256); for (let x = 0; x < sw; x++) cnt[row[x]]++;
        let bi = 0; for (let i = 1; i < 256; i++) if (cnt[i] > cnt[bi]) bi = i;
        if (cnt[bi] >= 300) { let lo = sw, hi = -1; for (let x = 0; x < sw; x++) if (row[x] === bi) { if (x < lo) lo = x; hi = x; } dom.push({ y: y, idx: bi, lo: lo, hi: hi, cnt: cnt }); }
        else dom.push({ y: y, idx: -1, lo: 0, hi: -1, cnt: cnt });
      }
      // true alternation: the row BETWEEN two light rows must carry almost none of the light index (a solid block such
      // as the purple keyed picture window has every row uniform and must NOT match)
      const alt = (i, k) => dom[i + 1] && dom[i + 1].cnt[dom[i].idx] < 100 && dom[k].y === dom[i].y + 2;
      let best = [];
      for (let i = 0; i < dom.length; i++) {
        if (dom[i].idx < 0) continue;
        const run = [dom[i]]; let j = i;
        while (j + 2 < dom.length && dom[j + 2].idx === dom[i].idx && alt(j, j + 2)) { run.push(dom[j + 2]); j += 2; }
        if (run.length > best.length) best = run;
      }
      const lrows = best, LIGHT = best.length ? best[0].idx : -1;
      if (lrows.length < 4) { log("PROTO panel: no scanline panel found (best run " + lrows.length + " rows, " + dom.length + " uniform rows)"); return; }
      const ny0 = lrows[0].y, ny1 = lrows[lrows.length - 1].y + 2;   // native rows [ny0, ny1): light,dark,...,light,dark
      const P = SL.stripePeriod(NUM, 0), hN = (P + 1) >> 1;
      const Y0 = dy + sc(ny0), Y1 = dy + sc(ny1);
      const cache = {};
      for (let y = Y0; y < Y1; y++) {
        if (y < 0 || y >= dH) continue;
        const k = Math.min(lrows.length - 1, Math.floor((y - Y0) / P)), ph = (y - Y0) % P;
        const lr = lrows[k], X0 = dx + sc(lr.lo), X1 = dx + sc(lr.hi + 1), w = X1 - X0;
        if (w <= 0) continue;
        let line;
        if (ph < hN) { line = new Uint8Array(w); line.fill(LIGHT); }
        else {
          const ndark = Math.min(ny1 - 1, lr.y + 1);
          if (!cache[ndark]) {
            const srow = new Uint8Array(sData.add(ndark * sPitch).readByteArray(sw)), out = new Uint8Array(w);
            for (let i = 0; i < w; i++) out[i] = srow[Math.min(sw - 1, lr.lo + Math.floor(i * (lr.hi + 1 - lr.lo) / w))];
            cache[ndark] = out;
          }
          line = cache[ndark];
        }
        const xs = Math.max(0, X0), xe = Math.min(dW, X1);
        if (xe > xs) dData.add(y * dPitch + xs).writeByteArray(line.buffer.slice(xs - X0, xe - X0));
      }
      L1("panel", "PROTO panel scanlines: native rows " + ny0 + ".." + (ny1 - 1) + " (" + lrows.length + " light rows, cols " + lrows[0].lo + ".." + lrows[0].hi + " / last " + lrows[lrows.length - 1].lo + ".." + lrows[lrows.length - 1].hi + ") lightIdx=" + LIGHT + " -> device rows " + Y0 + ".." + (Y1 - 1) + " P=" + P + " light=" + hN);
    } catch (e) { log("PROTO panel threw " + e); }
  }


  function att(va, name, cb) { try { Interceptor.attach(VA(va), cb); log("attached " + name + " @" + hex(va)); } catch (e) { log("ATTACH FAIL " + name + " @" + hex(va) + ": " + e); } }

  // ================================================================ W + T + N : after the build
  function scaleRect(p, tag) {
    const r = rect4(p);
    // vanilla dev = (112,84) + native800; scaled dev = (LX + s(112), LY + s(84)) + s(native800)  [each literal scaled
    // independently, exactly as the bake's imm rows will]. v1 forgot the s(112)/s(84) term -> everything sat 315/236 px off at 4K.
    const ox = LX + sc(ORG_X), oy = LY + sc(ORG_Y);
    const n = [ox + sc(r[0] - ORG_X), oy + sc(r[1] - ORG_Y), ox + sc(r[2] - ORG_X), oy + sc(r[3] - ORG_Y)];
    wr4(p, n);
    return tag + " " + "(" + r.join(",") + ")->(" + n.join(",") + ")[" + (n[2] - n[0]) + "x" + (n[3] - n[1]) + "]";
  }
  att(VA_LOADMON, "load_monicons", {
    onEnter() { this.self = this.context.ecx; },
    onLeave(r) {
      try {
        if (r.toInt32() !== 0) { log("PROTO load_monicons failed (" + r.toInt32() + "), nothing applied"); return; }
        computeScale(); lutBuilt = false;   // the canvas colour table is re-synced per open
        if (!ARMED) { log("PROTO g<=16 or narrow mode: native no-op"); return; }
        const o = MW(), SW = S32(VA(G_SCREENW)), SH = S32(VA(G_SCREENH));
        // W: whole-screen window, black canvas
        const before = "win+13C=" + rstr(o.add(OFF_WINPOS)) + " +14C=" + rstr(o.add(OFF_CLIENT)) + " +474=" + rstr(o.add(OFF_WINR)) + " flags9C=" + hex(S32(o.add(0x9c)));
        const rr = gwResize(o, SW, SH, 1);
        wr4(o.add(OFF_WINPOS), [0, 0, SW, SH]);
        wr4(o.add(OFF_WINR), [0, 0, SW, SH]);
        gwClear(o, 0);
        log("PROTO W: GraphicWin_resize -> " + rr + " | before " + before + " | after win+13C=" + rstr(o.add(OFF_WINPOS)) +
            " +14C=" + rstr(o.add(OFF_CLIENT)) + " +474=" + rstr(o.add(OFF_WINR)) + " canvas=" + S32(o.add(OFF_CANVAS + 0x80)) + "x" + S32(o.add(OFF_CANVAS + 0x84)) +
            " pitch=" + S32(o.add(OFF_CANVAS + 0x4a8)));
        // content rect (each literal scaled independently, as the bake's imm rows will)
        wr4(o.add(0xa24), [LX + sc(ORG_X), LY + sc(ORG_Y), LX + sc(912), LY + sc(684)]);
        log("PROTO content+A24=" + rstr(o.add(0xa24)) + " (vanilla (112,84,912,684))");
        // T: rect tables
        const lines = [];
        const namesA = ["picFar", "text", "picNear"];
        for (let i = 0; i < 17; i++) lines.push(scaleRect(o.add(OFF_TBL_A + i * 0x10), i < 3 ? namesA[i] : "icon" + (i - 3)));
        for (let i = 0; i < 6; i++) lines.push(scaleRect(o.add(OFF_TBL_B + i * 0x10), "banner" + i));
        for (let i = 0; i < 7; i++) lines.push(scaleRect(o.add(OFF_TBL_C + i * 0x10), i < 6 ? "glyph" + i : "emblem"));
        for (const l of lines) log("PROTO T " + l);
        // N v5: buttons SCALED. (a) child window resized to s(200)xs(21) and moved to (LX+s(824), LY+s(747)) [parent-local
        // +0x13C]; (b) admitted to the popup-button-2dzoom chain via thunk_btn_gate_pre (below) so the bevel face is
        // rendered at the scaled cell instead of 20 native rows; (c) label font stamped on the button canvas (+0x444+0x52C)
        // = find_font(floor(14*num/16), 1) -- the HOF/BaseWin btnfont law (native label font 0x6E84B4 = 14 bold).
        const bw = sc(200), bh = sc(21), bx = LX + sc(824), by = LY + sc(747);
        const lf = findFont(Math.floor(14 * NUM / 16), 1);
        for (const [off, nm] of [[OFF_BTN0, "CLOSE"], [OFF_BTN1, "BACK"]]) {
          const b = o.add(off), rr2 = gwResize(b, bw, bh, 1);
          wr4(b.add(OFF_WINPOS), [bx, by, bx + bw, by + bh]);
          wr4(b.add(OFF_WINR), [0, 0, bw, bh]);
          if (!lf.isNull()) b.add(OFF_CANVAS + 0x52c).writePointer(lf);
          // the build painted the face+label at NATIVE size (redraw @0x47355E/0x47365D) before our resize and font stamp,
          // then hid the button; the painter's Win_show reuses that canvas -> idle label stayed native until a hover
          // redraw. Repaint now through the object's own vtbl+0xF8 (GraphicWin_redraw 0x5D5A70, clean).
          try { const redraw = new NativeFunction(b.readPointer().add(0xF8).readPointer(), "void", ["pointer"], "thiscall"); redraw(b); }
          catch (e) { log("PROTO N " + nm + " redraw threw " + e); }
          log("PROTO N " + nm + ": resize -> " + rr2 + " +13C=" + rstr(b.add(OFF_WINPOS)) + " canvas=" + S32(b.add(OFF_CANVAS + 0x80)) + "x" + S32(b.add(OFF_CANVAS + 0x84)) +
              " labelFont=" + (lf.isNull() ? "null" : hex(lf.toUInt32()) + " cap" + S32(lf.add(0x10))) + " (find_font(" + Math.floor(14 * NUM / 16) + ",1)) redrawn");
        }
      } catch (e) { log("PROTO load_monicons leave threw " + e); }
    }
  });

  // ================================================================ B : backdrops + near picture stretch
  const BACKDROP = { 0x4760e7: "FAR backdrop (flc still)", 0x4737ee: "NEAR backdrop (monzoom)" };
  const PICTURE = { 0x475f3c: "NEAR picture (faction3)", 0x476062: "NEAR picture (monbig/faction3 kill)" };
  let ncopy = 0;
  try {
    Interceptor.replace(COPY4, new NativeCallback(function (self, dest, sx, sy, dx, dy, w, h) {
      try {
        if (ARMED) {
          const r = sva(this.returnAddress);
          if (BACKDROP[r]) {
            const t0 = Date.now(); bufBlit(self, dest, 0, 0, NAT_W, NAT_H, LX, LY, sc(NAT_W), sc(NAT_H));
            if (r === 0x4737ee) synthPanel(self, dest, LX, LY, sc(NAT_W), sc(NAT_H));
            if (ncopy++ < 8) log("PROTO B " + BACKDROP[r] + " @" + hex(r) + ": copy_4 " + w + "x" + h + " -> " + (resample ? KERNEL + "+FS" : "JS NN") + " index blit at (" + LX + "," + LY + ") " + sc(NAT_W) + "x" + sc(NAT_H) + " in " + (Date.now() - t0) + " ms");
            return 0;
          }
          if (PICTURE[r]) {
            const t0 = Date.now(); bufBlit(self, dest, sx, sy, w, h, dx, dy, sc(w), sc(h));
            if (ncopy++ < 8) log("PROTO B " + PICTURE[r] + " @" + hex(r) + ": copy_4 src(" + sx + "," + sy + ") " + w + "x" + h + " at (" + dx + "," + dy + ") -> JS NN index blit " + sc(w) + "x" + sc(h) + " in " + (Date.now() - t0) + " ms");
            return 0;
          }
        }
      } catch (e) { log("PROTO copy_4 replacement threw " + e); }
      return copy4(self, dest, sx, sy, dx, dy, w, h);
    }, "int", ["pointer", "pointer", "int", "int", "int", "int", "int", "int"], "thiscall"));
    log("PROTO copy_4 replacement installed (4 monument sites -> copy_3)");
  } catch (e) { log("PROTO copy_4 replace FAILED: " + e); }

  // ================================================================ G : sprite blits at the 9 monument sites
  const GSITES = {
    0x47625d: "icon", 0x4763a2: "picture(far)", 0x47643a: "banner L", 0x47649e: "banner R", 0x47651a: "glyph", 0x47658c: "emblem",
    0x4768f8: "hover own-pic", 0x476937: "hover big-pic", 0x476993: "hover faction-pic"
  };
  const GN = VA(G_NUM), GD = VA(G_DEN);
  att(0x5E4B9A, "Sprite_blit_scaled_core G bracket", {
    onEnter() {
      if (!ARMED) return;
      const r = retOf(this.context), tag = GSITES[r]; if (!tag) return;
      if (PIC_RETS[r]) {
        this.picRet = r; this.spr = this.context.ecx; this.dest = this.context.esp.add(4).readPointer();
        this.px = S32(this.context.esp.add(0xc)); this.py = S32(this.context.esp.add(0x10));
      }
      this.gsave = [GN.readS32(), GD.readS32()];
      GN.writeS32(NUM); GD.writeS32(DEN);
      const spr = this.context.ecx, sp = this.context.esp;
      L1("G" + r, "PROTO G " + tag + " @" + hex(r) + ": sprite " + S32(spr.add(0x18)) + "x" + S32(spr.add(0x1c)) + " at (" + S32(sp.add(0xc)) + "," + S32(sp.add(0x10)) + ") G " + this.gsave.join("/") + " -> " + NUM + "/" + DEN);
    },
    onLeave() {
      if (this.gsave) { GN.writeS32(this.gsave[0]); GD.writeS32(this.gsave[1]); this.gsave = null; }
      // v4: the 160x97 far picture (painter + 3 hover re-blits) is OPAQUE art -> overdraw the engine's NN result with
      // the bilinear average at the same rect (bake stage = thunk_sprite_bilinear at these call sites).
      if (!ARMED || !this.picRet) return;
      // +1 col/row: the engine's G-scaled blit paints ONE extra garbage column/row past sc(w)/sc(h) at fractional scales
      // (the reddish column at x=1692+450 in the 2026-09-13 21:43 shot) -- the overdraw hides it; the bake's own thunk sizes exactly.
      try { sprBlit(this.spr, this.dest, this.px, this.py, sc(S32(this.spr.add(0x18))) + 1, sc(S32(this.spr.add(0x1c))) + 1); }
      catch (e) { log("PROTO far-picture overdraw threw " + e); }
    }
  });
  // capture the far-picture blit args in onEnter (same attach: extend via a second attach on the same entry is NOT
  // allowed, so the fields are set inside the bracket's onEnter below via PIC_RETS)
  const PIC_RETS = { 0x4763a2: 1, 0x4768f8: 1, 0x476937: 1, 0x476993: 1 };

  // ================================================================ N(b): 2dzoom gate admission for the two FlatButtons
  // thunk_btn_gate_pre (rw_scale_shared E8 helper, pcave2+0x24230 in the live yaml; entry = `cmp esi, <static>` chain,
  // esi = the button object). Returning 1 admits the button to popup_button_2dzoom (scaled bevel face). Same host the
  // HOF proto v5 used (user-verified 2026-09-08 at its then-offset 0x24070); offset re-checked in the live exe 2026-09-13.
  const GATE_VA = 0xA0C000 + 0x24230;
  let gateN = 0;
  att(GATE_VA, "thunk_btn_gate_pre (button admission)", {
    onEnter() {
      this.tag = null;
      if (!ARMED) return;
      const b = this.context.esi.toUInt32(), mw = MW().toUInt32();
      if (b === mw + OFF_BTN0) this.tag = "CLOSE"; else if (b === mw + OFF_BTN1) this.tag = "BACK";
    },
    onLeave(r) { if (this.tag) { if (gateN++ < 6) log("PROTO N gate admit " + this.tag + ": " + r.toInt32() + " -> 1"); r.replace(1); } }
  });

  // ================================================================ N(c): button FACE restripe (scaling-frames s7b)
  // The bevel face is a 1-px red/black scanline dither; the 2dzoom chain's NN enlarge beats it into 2/3-px runs (the
  // "banded red button", 2026-09-13 22:57 shot). Regenerate at device density: P=SL.stripePeriod(g), top member hN=(P+1)>>1 rows.
  // Host = Buffer_wrap_cent_4 0x5DD920 ENTRY (clean; the label writer FlatButton_draw calls LAST, after the face) filtered
  // on dest == a monument button canvas -> the face is complete and the label is not yet drawn (the label is black =
  // a pair member, so restriping AFTER it would eat the text). Pair detected PER DRAW from the canvas (state rule:
  // idle/hover/pressed faces differ), never hardcoded.
  let rsN = 0;
  function restripeButton(buf, tag, ctx) {
    const w = S32(buf.add(0x80)), h = -S32(buf.add(0x84)), pitch = S32(buf.add(0x4a8)), data = buf.add(0x54).readPointer();
    if (data.isNull() || w <= 0 || h <= 0) return;
    const P = SL.stripePeriod(NUM, 0), hN = (P + 1) >> 1;
    if (P <= 2) return;
    // column census: collapse the mid column into runs; a scanline face = >= 6 runs alternating between exactly two
    // indices with every run <= P+1 rows (the NN-enlarged 1-px dither is 2..3-px runs at g45, 1..2 at g22/25)
    const x = w >> 1, col = new Uint8Array(w > 0 ? h : 0);
    for (let y = 0; y < h; y++) col[y] = data.add(y * pitch + x).readU8();
    const runs = []; let cur = col[0], len = 1;
    for (let y = 1; y < h; y++) { if (col[y] === cur) len++; else { runs.push([cur, len]); cur = col[y]; len = 1; } }
    runs.push([cur, len]);
    let a = -1, b = -1, y0 = -1, pos = 0, bestStart = -1, bestLen = 0;
    for (let i = 0; i < runs.length; i++) {
      let j = i, ok = true, pa = runs[i][0], pb = -1;
      while (j < runs.length && runs[j][1] <= P + 1) { const v = runs[j][0]; if (v !== pa) { if (pb < 0) pb = v; else if (v !== pb) break; } j++; }
      if (pb >= 0 && j - i >= 6 && j - i > bestLen) { bestLen = j - i; bestStart = i; a = pa; b = pb; }
    }
    if (a < 0) { L1("rs-none" + tag, "PROTO N restripe " + tag + ": no alternating pair in column " + x + " runs=" + runs.slice(0, 12).map(r => r[0] + "x" + r[1]).join(" ")); return; }
    for (let i = 0; i < bestStart; i++) pos += runs[i][1];
    y0 = pos;
    // DETERMINISTIC phase: the darker member on top (pristine MonumentFar/Close: face row 0 = (32,8,6) idx 201, then
    // red idx 109). Reading the phase off the canvas flashed at 1600x1200: the engine re-tiles the idle fill between
    // composites with a shifting phase, and v7c copied whichever member happened to be first.
    const lum = i => { const q = buf.add(0xA4 + i * 4); return q.readU8() * 114 + q.add(1).readU8() * 587 + q.add(2).readU8() * 299; };
    const top = lum(a) <= lum(b) ? a : b, bot = (top === a) ? b : a;
    let n = 0;
    for (let y = 0; y < h; y++) {
      const row = new Uint8Array(data.add(y * pitch).readByteArray(w));
      const c = ((y % P) < hN) ? top : bot;
      let changed = false;
      for (let i = 0; i < w; i++) if (row[i] === a || row[i] === b) { if (row[i] !== c) { row[i] = c; changed = true; } n++; }
      if (changed) data.add(y * pitch).writeByteArray(row.buffer);
    }
    if (rsN++ < 12) log("PROTO N restripe#" + rsN + " " + tag + ": pair " + a + "/" + b + " (top " + top + ") over " + w + "x" + h + " P=" + P + " hN=" + hN + " pixels=" + n +
       " ret=" + (ctx ? hex(retOf(ctx)) : "?") + " col-after=" + colRuns(buf, x));
  }
  // column run-length of an 8-bpp Buffer at x (diagnostic for the stripe pitch)
  function colRuns(buf, x) {
    try {
      const h = -S32(buf.add(0x84)), pitch = S32(buf.add(0x4a8)), data = buf.add(0x54).readPointer();
      const out = []; let cur = -1, n = 0;
      for (let y = 0; y < h; y++) { const v = data.add(y * pitch + x).readU8(); if (v === cur) n++; else { if (cur >= 0) out.push(cur + "x" + n); cur = v; n = 1; } }
      out.push(cur + "x" + n); return out.slice(0, 14).join(" ");
    } catch (e) { return "err " + e; }
  }
  const G_SCREENBUF = 0x9B7490;   // the composite target seen in the census (Buffer_draw_2 dest)
  let diagN = 0;
  setInterval(function () {
    if (!ARMED || diagN++ > 40) return;
    try {
      const b0 = MW().add(OFF_BTN0), c0 = b0.add(OFF_CANVAS), r = rect4(b0.add(OFF_WINPOS));
      const sb = VA(G_SCREENBUF), sx = r[0] + ((r[2] - r[0]) >> 1);
      // screen column at the button's x, rows r.top..r.bottom
      const sPitch = S32(sb.add(0x4a8)), sData = sb.add(0x54).readPointer();
      const out = []; let cur = -1, n = 0;
      for (let y = r[1]; y < r[3]; y++) { const v = sData.add(y * sPitch + sx).readU8(); if (v === cur) n++; else { if (cur >= 0) out.push(cur + "x" + n); cur = v; n = 1; } }
      out.push(cur + "x" + n);
      log("DIAG CLOSE canvas col=" + colRuns(c0, (S32(c0.add(0x80)) >> 1)) + " | screen col(" + sx + ")=" + out.slice(0, 14).join(" ") + " state=" + S32(MW().add(OFF_STATE)));
    } catch (e) { log("DIAG threw " + e); }
  }, 5000);
  // Host = Buffer_draw_2 0x5D84C0 ENTRY (clean; the window compositor copies every child canvas to the screen through
  // it, src = ecx). Keyed on src == a monument button canvas: covers EVERY face path by construction (sprite states,
  // the tiled bevel fill of the idle face, focus rings) at the last moment before the pixels reach the screen. The
  // label (index 0) is not a stripe member, so it passes through untouched.
  att(0x5D84C0, "Buffer_draw_2 (button face restripe at composite)", {
    onEnter() {
      if (!ARMED) return;
      const d = this.context.ecx.toUInt32(), mw = MW().toUInt32();
      if (d === mw + OFF_BTN0 + OFF_CANVAS) restripeButton(this.context.ecx, "CLOSE", this.context);
      else if (d === mw + OFF_BTN1 + OFF_CANVAS) restripeButton(this.context.ecx, "BACK", this.context);
    }
  });

  // ================================================================ lifecycle log
  att(VA_MONUMENT, "monument", {
    onEnter() { log("ENTRY monument(" + S32(this.context.esp.add(4)) + ") g=" + S32(VA(G_SCALE)) + " screen=" + S32(VA(G_SCREENW)) + "x" + S32(VA(G_SCREENH))); },
    onLeave() { log("LEAVE monument"); }
  });
  let drawN = 0;
  // v4 F: plaque font law. The painter does Buffer_set_font(canvas, [0x8A40BC]) itself @0x473761; [0x8A40BC] is
  // ReportInfc fonts[1] = f12 = find_font(12, 0) in vanilla (the rw bake swaps it to its own scaled font). Swap the
  // global to find_font(floor(12*num/16), 0) for the duration of the paint, restore after. 33 px at 4K (<= the 40 cap).
  const G_PLAQUE_FONT = 0x8A40BC;
  att(VA_MONDRAW, "MonumentWin_draw", {
    onEnter() {
      drawN++; this.st = S32(MW().add(OFF_STATE));
      if (!ARMED) return;
      try {
        const fp = VA(G_PLAQUE_FONT); this.fontSave = fp.readPointer();
        const size = Math.floor(12 * NUM / 16), nf = findFont(size, 0);
        if (!nf.isNull()) { fp.writePointer(nf); L1("font", "PROTO F plaque font: [0x8A40BC] " + hex(this.fontSave.toUInt32()) + " (cap " + S32(this.fontSave.add(0x10)) + ") -> find_font(" + size + ",0)=" + hex(nf.toUInt32()) + " cap " + S32(nf.add(0x10)) + " cell " + S32(nf.add(0xc))); }
        else { this.fontSave = null; log("PROTO F find_font(" + size + ",0) returned null"); }
      } catch (e) { log("PROTO F threw " + e); this.fontSave = null; }
    },
    onLeave() {
      if (this.fontSave) { try { VA(G_PLAQUE_FONT).writePointer(this.fontSave); } catch (e) {} }
      const o = MW();
      log("DRAW #" + drawN + " view=" + (this.st === 0 ? "far" : "near") + " sel=" + S32(o.add(OFF_SEL)) + " win+13C=" + rstr(o.add(OFF_WINPOS)) +
          " canvas=" + S32(o.add(OFF_CANVAS + 0x80)) + "x" + S32(o.add(OFF_CANVAS + 0x84)) + " text=" + rstr(o.add(0x3144)) + " picNear=" + rstr(o.add(0x3154)) +
          " CLOSE+13C=" + rstr(o.add(OFF_BTN0 + OFF_WINPOS)) + " BACK+13C=" + rstr(o.add(OFF_BTN1 + OFF_WINPOS)));
    }
  });
  log("PROTO v7d armed: FULLHEIGHT=" + FULLHEIGHT + " (levers W window, T tables, B copy_3 stretch, G sprite bracket, N buttons moved)");
} catch (e) { log("!!! PROTO TOP-LEVEL EXCEPTION (every later lever is DEAD): " + e + " " + (e && e.stack)); }
