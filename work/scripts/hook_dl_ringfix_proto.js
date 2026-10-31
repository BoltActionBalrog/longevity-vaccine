// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// DL hover-ring overdraw PROTOTYPE — zero-Interceptor poll (btn-zoom chain is Frida-untouchable).
// Implements the exact bake law over the zoomed button canvas, idempotently, every 150ms:
//   K = ceil(g/16)
//   per-edge stroke color read from the button's BoxSpriteParams edge-strip ART
//     (top: row0[w/2]; bottom: row(h-1)[w/2]; left: col0[h/2]; right: col(w-1)[h/2])
//   color 7 (pass-through) or 9 (key) => edge has no stroke, skip
//   draw K-thick strokes full-length on the canvas edges, then punch 4 KxK key-9 corner
//   notches iff the TL corner art's (0,0) is keyed (the vanilla chamfer, scaled).
// Self-gates: only the hover set carries a stroke, so idle/pressed are untouched by the art gate.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_dl_ringfix.log";
log("=== hook_dl_ringfix_proto.js started ===");

if (requireBase()) {
  const DLWIN  = VA(0x703EA0);
  const BTN0   = DLWIN.add(0x2A3C);
  const STRIDE = 0xB4C, NBTN = 18;
  const NAMES  = i => (i === 16 ? "BACK" : i === 17 ? "EXIT" : "wing" + i);
  const G      = VA(0x668740);

  function rd32(p) { try { return p.readU32(); } catch (e) { return null; } }
  function okPtr(v) { return v !== null && v >= 0x10000 && v < 0x7FF00000; }

  // strip sprite: data +0x4, pitch +0xC, w +0x10, h +0x14
  function stripColor(spv, mode) {
    if (!okPtr(spv)) return -1;
    const sp = ptr(spv);
    const data = rd32(sp.add(4)), pitch = rd32(sp.add(0xC));
    const w = rd32(sp.add(0x10)), h = rd32(sp.add(0x14));
    if (!okPtr(data) || !(w > 0 && w < 512 && h > 0 && h < 512 && pitch >= w)) return -1;
    try {
      const dp = ptr(data);
      if (mode === "top")    return dp.add((w >> 1)).readU8();
      if (mode === "bottom") return dp.add(pitch * (h - 1) + (w >> 1)).readU8();
      if (mode === "left")   return dp.add(pitch * (h >> 1)).readU8();
      /* right */            return dp.add(pitch * (h >> 1) + w - 1).readU8();
    } catch (e) { return -1; }
  }

  const loggedOnce = {};
  function apply(i) {
    const b = BTN0.add(i * STRIDE);
    const g = rd32(G);
    if (g === null || g <= 16) return;
    // draw-state law (content_draw 0x607EC8)
    let s = rd32(b.add(0xAB8)) | 0;
    if (s < 0 || s >= 3) {
      if (rd32(b.add(0xA9C)) || rd32(b.add(0xA18))) s = 2;
      else s = rd32(b.add(0xA74)) ? 1 : 0;
    }
    if (rd32(b.add(0xAD4 + s * 4))) return;               // stateSprite path, no box face
    const bp = rd32(b.add(0xAC8 + s * 4));
    if (!okPtr(bp)) return;
    const params = ptr(bp);
    const colT = stripColor(rd32(params.add(0x10)), "top");
    const colB = stripColor(rd32(params.add(0x14)), "bottom");
    const colL = stripColor(rd32(params.add(0x18)), "left");
    const colR = stripColor(rd32(params.add(0x1C)), "right");
    const live = c => c >= 0 && c !== 7 && c !== 9;
    if (!live(colT) && !live(colB) && !live(colL) && !live(colR)) return;  // ringless state
    // canvas
    const canvas = b.add(0x444);
    const data = rd32(canvas.add(0x54)), stride = rd32(canvas.add(0x4A8));
    const W = rd32(canvas.add(0x80));
    let H = rd32(canvas.add(0x84)) | 0; if (H < 0) H = -H;
    if (!okPtr(data) || !(W > 8 && W < 4096 && H > 8 && H < 4096 && stride >= W)) return;
    const dp = ptr(data);
    const K = (g + 15) >> 4;
    try {
      const hrow = c => { const a = new Uint8Array(W); a.fill(c); return a.buffer; };
      if (live(colT)) { const r = hrow(colT); for (let y = 0; y < K; y++) dp.add(y * stride).writeByteArray(r); }
      if (live(colB)) { const r = hrow(colB); for (let y = H - K; y < H; y++) dp.add(y * stride).writeByteArray(r); }
      if (live(colL)) for (let y = 0; y < H; y++) for (let x = 0; x < K; x++) dp.add(y * stride + x).writeU8(colL);
      if (live(colR)) for (let y = 0; y < H; y++) for (let x = W - K; x < W; x++) dp.add(y * stride + x).writeU8(colR);
      // corner notches (vanilla chamfer): punch KxK key-9 iff TL corner art is keyed at (0,0)
      const tl = rd32(params);
      if (okPtr(tl)) {
        const tld = rd32(ptr(tl).add(4));
        if (okPtr(tld) && ptr(tld).readU8() === 9) {
          for (let y = 0; y < K; y++)
            for (let x = 0; x < K; x++) {
              dp.add(y * stride + x).writeU8(9);
              dp.add(y * stride + (W - 1 - x)).writeU8(9);
              dp.add((H - 1 - y) * stride + x).writeU8(9);
              dp.add((H - 1 - y) * stride + (W - 1 - x)).writeU8(9);
            }
        }
      }
      const key = i + ":" + s;
      if (!loggedOnce[key]) {
        loggedOnce[key] = 1;
        log("[ringfix] " + NAMES(i) + " state" + s + " K=" + K + " canvas " + W + "x" + H +
            " colors T/B/L/R=" + [colT, colB, colL, colR].join("/"));
      }
    } catch (e) { log("[ringfix] " + NAMES(i) + " write failed: " + e); }
  }

  setInterval(() => { for (let i = 0; i < NBTN; i++) apply(i); }, 150);
  let beats = 0;
  setInterval(() => { if (++beats <= 12) log("[hb] alive g=" + rd32(G)); }, 5000);
  log("=== ringfix poll armed (150ms, art-gated, K=ceil(g/16)) ===");
}
