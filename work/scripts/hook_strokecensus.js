"use strict";
// STROKE CENSUS (2026-07-09) — the bake's before/after ORACLE. OBSERVE-ONLY.
//
// Measures, for every frame the engine enlarges, the ACTUAL visible thickness of the near
// and far strokes on each axis, by reading the destination pixels. No model, no assumption
// about how the blit maps src->dst. Works unchanged on the SHIPPED exe and on the baked one:
//
//   BEFORE (shipped uniform-NN enlarge)   expect near != far  (2,1) at g=22/25, (3,2) at 4K
//   AFTER  (baked band map)               expect near == far == K = half_down(g,16)
//
// WHY MEASURE RATHER THAN MODEL. thunk_keyed_stretch_blit routes through Buffer_copy_3, which
// dispatches through surface vtables — the src->dst index mapping is NOT statically derivable
// from our bytes. A python model of it agreed with two screenshots, which is corroboration,
// not proof. This reads the pixels.
//
// HOW. thunk_frame_enlarge @0xA0F0A0 is thiscall(ecx = the finished native scratch)(dest, key,
// X, Y, num, den) and ALREADY stashes the post-exact-fill blit geometry into g_fe_dst/x/y/w/h
// right before the blit. So: save ecx onEnter, read the globals + dest pixels onLeave.
//
// Sample a column through the MIDDLE of the top/bottom edges (away from the corners, whose
// chamfer is transparent) and a row through the middle of the left/right edges. For that
// column the dest pixel at row j is src[F(j)][sx]. Count the leading run equal to src row 0
// => the near stroke; the trailing run equal to src row srcH-1 => the far stroke. If src rows
// 0 and 1 carry the same colour at that sample the edge is unmeasurable there -> reported as
// -1 rather than guessed.
//
// SAFETY. Pure Interceptor.attach on a cave FUNCTION entry (push ebp; ...), no replace, no
// pokes, no writes. onLeave is legal here because this is a function entry ([esp] = return
// address), not a call-instruction attach. See [[feedback-frida-attach-branch-target]].
//
// Run:  run-frida-at-res.bat hook_strokecensus.js <W> <H> frida_log_append.js
//       at 3840x2160, 1600x1200, 1920x1080 and 1024x768 (the last MUST report 1/1 everywhere).
// Then: py work\scripts\check_stroke_census.py
// Log:  work/tests/frida_strokecensus.log
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_strokecensus.log";
log("=== hook_strokecensus.js (OBSERVE-ONLY: measure real stroke thickness per frame) ===");

if (requireBase()) {
  const A_ENLARGE = 0x00A0F0A0;
  const G         = 0x00668740;
  // stashed by thunk_frame_enlarge immediately before the blit (post exact-fill override)
  const G_FE_DST = 0x00A0EFA0, G_FE_X = 0x00A0EFA4, G_FE_Y = 0x00A0EFA8,
        G_FE_W   = 0x00A0EFAC, G_FE_H = 0x00A0EFB0;

  const gnow = () => ptr(VA(G)).readS32();
  const rd   = (a) => ptr(VA(a)).readS32();

  function bufInfo(b) {
    const w = b.add(0x80).readS32();
    let h = b.add(0x84).readS32(); if (h < 0) h = -h;      // stored NEGATIVE
    return { w: w, h: h, data: b.add(0x54).readPointer(), stride: b.add(0x4a8).readS32() };
  }
  const px = (bi, x, y) => bi.data.add(y * bi.stride + x).readU8();

  // Count the leading run of dest cells equal to the src's outermost cell, and the trailing
  // run equal to its innermost. Returns [near, far]; -1 where the sample cannot discriminate.
  function measure(getDest, getSrc, dstN, srcN) {
    const s0 = getSrc(0), s1 = getSrc(1);
    const sL = getSrc(srcN - 1), sP = getSrc(srcN - 2);
    let near = -1, far = -1;
    if (s0 !== s1) {
      near = 0;
      while (near < dstN && getDest(near) === s0) near++;
    }
    if (sL !== sP) {
      far = 0;
      while (far < dstN && getDest(dstN - 1 - far) === sL) far++;
    }
    return [near, far];
  }

  const seen = {};
  let n = 0;

  Interceptor.attach(ptr(VA(A_ENLARGE)), {
    onEnter: function () { this.src = this.context.ecx; },
    onLeave: function () {
      const g = gnow();
      let src, dst, X, Y, W, H;
      try {
        src = bufInfo(this.src);
        const dp = ptr(rd(G_FE_DST));
        if (dp.isNull()) return;
        dst = bufInfo(dp);
        X = rd(G_FE_X); Y = rd(G_FE_Y); W = rd(G_FE_W); H = rd(G_FE_H);
      } catch (e) { return; }
      if (!src.data || src.data.isNull() || !dst.data || dst.data.isNull()) return;
      if (W <= 4 || H <= 4 || src.w <= 2 || src.h <= 2) return;
      if (X < 0 || Y < 0 || X + W > dst.w || Y + H > dst.h) return;   // clipped: don't measure

      // one line per distinct (src dims, dst dims, dest buffer)
      const key = src.w + "x" + src.h + "|" + W + "x" + H + "|" + dst.data;
      if (seen[key]) return;
      seen[key] = 1;

      let vert = [-1, -1], horiz = [-1, -1];
      try {
        const sx = src.w >> 1, dx = X + (W >> 1);            // mid of the top/bottom edges
        vert = measure((j) => px(dst, dx, Y + j), (i) => px(src, sx, i), H, src.h);
        const sy = src.h >> 1, dy = Y + (H >> 1);            // mid of the left/right edges
        horiz = measure((i) => px(dst, X + i, dy), (i) => px(src, i, sy), W, src.w);
      } catch (e) { return; }

      n++;
      log("frame g=" + g
        + " src=" + src.w + "x" + src.h + " dst=" + W + "x" + H
        + " at=(" + X + "," + Y + ")"
        + " destbuf=0x" + rd(G_FE_DST).toString(16)
        + " strokeY=" + vert[0] + "/" + vert[1]
        + " strokeX=" + horiz[0] + "/" + horiz[1]
        + ((vert[0] > 0 && vert[1] > 0 && vert[0] !== vert[1]) ||
           (horiz[0] > 0 && horiz[1] > 0 && horiz[0] !== horiz[1]) ? "   WOBBLE" : ""));
    }
  });

  log("attached thunk_frame_enlarge @0xa0f0a0 (observe-only)  g=" + gnow());
  log("Walk: main menu -> Quit modal -> file picker -> faction picker -> HUD.");
  log("strokeY/strokeX are near/far. Shipped: expect unequal at g>16. Baked: expect K/K.");
  log("K = " + (typeof SL !== "undefined" ? SL.strokeWidth(gnow()) : "(SL prelude not loaded)"));
  setInterval(function () { log("-- frames measured: " + n); }, 20000);
}
