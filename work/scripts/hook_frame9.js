// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE v3 (2026-07-09): keep the engine's own 9-slice render; fix only the ENLARGE.
// Runtime-only: the exe on disk stays at the 75cae700 lock. Kill the game to revert.
//
// WHAT v2 GOT WRONG
//   v2 re-rendered the 9-slice from the raw BoxSpriteParams sprite slots. That meant reinterpreting
//   canvas vs blit dims, off_x/off_y, key handling and tile phase -- and getting every one right.
//   It painted the edge sprite's 0x07 body-fill rows, which the engine leaves transparent, so a
//   band of body colour leaked inside the stroke: 1px on the near edges, 3px on the far edges
//   (the t=2,3,2,3,2,3 vector showing through). Wrong colours in strokes and channels.
//   The engine already renders this frame correctly at native size. Don't re-derive it.
//
// WHAT THIS DOES
//   Render into the scratch EXACTLY as the shipped thunks do (same prefill, same Buffer_box_sprite,
//   same native size). Then replace the uniform NN enlarge with a per-axis 9-SLICE MAP:
//
//     cum(v) = floor((v*g + 7)/16)       round-half-down;  K = cum(1)
//     fwd[j] = native band row feeding dest offset j        (j < B = cum(N))
//
//     F(j) = fwd[j]                                j < B          near band: outer row -> K px
//            (srcN-1) - fwd[DW-1-j]                j >= DW-B      far  band: outer row -> K px
//            N + floor((j-B)*(srcN-2N)/(DW-2B))    otherwise      middle: stretch
//
//   Both bands are carried at fixed depth by the SAME map, each anchored to its OWN outer edge, so
//   opposite strokes quantize identically -- that is the 2-vs-3px wobble, gone. Only the middle
//   stretches. DW is the rect span exactly, so the frame fills its rect by construction and
//   g_fc_exact becomes unnecessary (we neither read nor set it).
//
//   Nothing snaps the rect, so an ODD channel survives: the faction quote's ps3=7 is untouched.
//   At g=16, cum is the identity and F(j)=j -> byte-identical to vanilla, no gate needed.
//   Colours are whatever the engine painted. Rows it leaves transparent stay transparent.
//
//   N (native band depth) = the corner sprite's canvas dims, per axis. 6x6 for the simple frames,
//   61x44 for the picker's ornate window frame. That is the ONLY thing still read from the sprites,
//   and it is a size, not a pixel.
//
// DITHER PARITY (the 1600x1200 banding, root-caused 2026-07-09)
//   The shipped renderers all end in thunk_frame_enlarge, whose tail stashes g_fe_dst/x/y/w/h +
//   g_fe_src and CALLS thunk_fe_pair_remap: the device-density stripe law (P=SL.stripePeriod(g), row colour
//   by y mod P) that rewrites the three dither pairs (blue E0/E1, teal AE/EE, navy 41/C4
//   content-keyed on a C4 scan of the src scratch). v3 never calls frame_enlarge, so the scratch's
//   1px dither interiors were NN-resampled raw by our emit -> run-length beat (blue=2/black=1
//   drifting to blue=1/black=2 every ~20 rows at g=25). Invisible at 4K (2.5 is a clean 2/3
//   alternation), banded at fractional g. Fix: replicate the enlarge epilogue exactly -- stash the
//   g_fe_* globals and call thunk_fe_pair_remap after the emit. Same law, same content keys.
//   We also consume g_fc_exact (write 0) exactly where frame_enlarge would have: its setters arm
//   it immediately before calling a renderer we replaced, and leaving it armed hands a stale
//   exact-fill override to the next unrelated frame_enlarge caller.
//
// Log: work/tests/frida_frame9.log
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_frame9.log";
log("=== hook_frame9.js started (v3: engine renders, we remap the enlarge) ===");

// ---- BISECT SWITCHES ------------------------------------------------------------------------
const PASSTHRU    = false;  // true -> call the originals; proves the hook set itself is inert
const ONLY_SIMPLE = false;  // true -> synthesize 6x6 sets only; ornate picker frame runs as today
// ---------------------------------------------------------------------------------------------

if (requireBase()) {
  const G = 0x00668740;
  const A_RESIZE = 0x005D79C0, A_SETCLIP = 0x005D8000, A_FILL3 = 0x005DFCD0,
        A_BOXSPR = 0x005E2DD3, A_ENSUREBUF = 0x00668EE0,
        A_HLINE = 0x005E1A80, A_PUTPX = 0x005E2330;
  // pcave2 (VA 0xA0C000) frame-enlarge remap machinery, from patches.yaml offsets
  const A_PAIR_REMAP = 0x00A10000;     // thunk_fe_pair_remap (0x4000): plain CALL, no args, clobbers eax/ecx/edx
  const G_FE_DST = 0x00A0EFA0, G_FE_X = 0x00A0EFA4, G_FE_Y = 0x00A0EFA8,
        G_FE_W   = 0x00A0EFAC, G_FE_H = 0x00A0EFB0, G_FE_SRC = 0x00A0EFC4;
  const G_FC_EXACT = 0x00A0E554;       // exact-fill one-shot (0x2554): consumed here as frame_enlarge would

  const Buffer_resize     = new NativeFunction(ptr(VA(A_RESIZE)),   'void', ['pointer','int','int'], 'thiscall');
  const Buffer_set_clip   = new NativeFunction(ptr(VA(A_SETCLIP)),  'void', ['pointer','pointer'], 'thiscall');
  const Buffer_fill_3     = new NativeFunction(ptr(VA(A_FILL3)),    'void', ['pointer','pointer','int'], 'thiscall');
  const Buffer_box_sprite = new NativeFunction(ptr(VA(A_BOXSPR)),   'void', ['pointer','pointer','pointer'], 'thiscall');
  const ensure_frame_buf  = new NativeFunction(ptr(VA(A_ENSUREBUF)),'pointer', [], 'mscdecl');
  const Buffer_hline_2    = new NativeFunction(ptr(VA(A_HLINE)),    'void', ['pointer','int','int','int','int'], 'thiscall');
  const Buffer_put_pixel  = new NativeFunction(ptr(VA(A_PUTPX)),    'void', ['pointer','int','int','int'], 'thiscall');
  const fe_pair_remap     = new NativeFunction(ptr(VA(A_PAIR_REMAP)), 'void', [], 'mscdecl');

  const scratchRect = Memory.alloc(16);
  const gnow = () => ptr(VA(G)).readS32();

  // ---- the 9-slice axis map -------------------------------------------------------------------
  // The band map MUST be derived from the ACTUAL src->dst ratio (DW/srcN), not from g/16.
  // srcN = floor(DW*16/g) carries its own rounding, so g/16 and DW/srcN are different scales:
  //   g=40  DW/srcN=2.500   cum(6)/6 via g/16 = 15/6 = 2.500  agree  <- 4K hid this
  //   g=25  DW/srcN=1.5625  cum(6)/6 via g/16 =  9/6 = 1.500  corner reads SMALL
  //   g=22  DW/srcN=1.3755  cum(6)/6 via g/16 =  8/6 = 1.333  corner reads SMALL
  // Deriving cum from DW/srcN makes the bands and the stretched middle share one scale, so the
  // corner joins its edges seamlessly at every resolution and the stroke is round(DW/srcN).
  // ---- the laws live in the SHARED PRELUDE scripts/scaling_laws.js (globalThis.SL) ------------
  // This hook used to carry a private copy of halfDown/fwdMap/axisMap. A private copy is exactly
  // how the stroke width diverged per-element in the first place, and a JS<->Python differential
  // sweep later found the copy disagreeing with the reference by one pixel in the middle-phase
  // clamp. One implementation, one test: work/tests/test_scaling_js_parity.py drives THIS module
  // through node and diffs every integer against work/scripts/scaling_laws.py (the source of
  // truth). Never re-inline the math here -- test_scaling_js_parity asserts you haven't.
  if (typeof SL === "undefined") {
    throw new Error("scaling_laws.js prelude not loaded (frida -l frida_common.js "
                  + "-l scaling_laws.js -l hook_frame9.js)");
  }
  const halfDown = SL.halfDown;
  const fwdMap   = (n, srcN, DW) => SL.fwdMap(n, srcN, DW, gnow());
  const axisMap  = (srcN, DW, n) => SL.axisMap(srcN, DW, n, gnow());

  function cornerBand(par) {                    // native band depth = corner canvas, per axis
    const tl = par.readPointer();
    if (tl.isNull()) return null;
    try {
      const cw = tl.add(0x18).readS32(), ch = tl.add(0x1c).readS32();
      if (cw <= 0 || ch <= 0 || cw > 512 || ch > 512) return null;
      return { nx: cw, ny: ch };
    } catch (e) { return null; }
  }

  // ---- run-length emit through the engine's clip-aware primitives -----------------------------
  // hline is a NO-OP when x0==x1, hence the put_pixel fallback for singleton runs.
  function emitRow(dest, y, x0, cols, n, key) {
    let i = 0;
    while (i < n) {
      const c = cols[i];
      let j = i + 1;
      while (j < n && cols[j] === c) j++;
      if (c !== key) {
        if (j - i === 1) Buffer_put_pixel(dest, x0 + i, y, c);
        else Buffer_hline_2(dest, x0 + i, x0 + j - 1, y, c);
      }
      i = j;
    }
  }

  // ---- FACTION LIST RING flush-bottom (2026-07-09, "empty space below Peacekeepers") -----------
  // Vanilla builds the list ring rect as (L-3, T-3, R+21, B+3) from the NATIVE list rect fields
  // [esi+0x86ac..b8], and natively B-T=130 with rows 7*19=133 -> B+3 == T+133: the ring's bottom
  // edge IS the rows' end, flush by construction (0x489741..0x48977f). Scaled, that identity
  // breaks: the ring scales (B+3) keeping its fraction while the rows land at T_s + 7*floor(pitch)
  // (fraction floored twice) -> ~4px void at g=25, +2 more once v3 fills the rect exactly (the
  // shipped NN shortfall used to hide them). Fix: rebuild the identity with the SAME quantities
  // the rows use -- Dialog's scaled top + 7*pitch([esi+0x8704]) -- captured at the unique ring
  // call site 0x48977F and consumed by the next core() draw. g<=16 never sets pending (vanilla is
  // already flush). The Dialog's scaled rect offset inside the object at [esi+0x86bc] is found by
  // value-scan once and logged for the bake.
  // NO site hook: a site attach at the baked call-redirect 0x48977F combined with our
  // Interceptor.replace on the renderers framecover tail-jumps into is the v33 SOFT-KILL combo
  // (see [[feedback-frida-attach-branch-target]]) -- the picker stopped drawing and clicking
  // crashed. Instead the picker WINDOW is located once by value-scan: its buffer 0x822b5c is a
  // global (stable across runs/sessions), so the window base W is the address where
  // [W+0x8704]=row pitch (small int), [W+0x86b0]=native list top, [W+0x86bc]=Dialog vtable ptr.
  // FactionPickWin GLOBAL @0x822718 (disasm 0x58a755: mov ecx,0x822718 before the exec call).
  // The NATIVE list rect lives at +0x86ac..b8 (L/T/R/B); NOT scaled in place (no writeback).
  // The list-ring's LOCAL rect is (L-3, T-3, R+21, B+3) built at 0x489741 -- the +3 bottom is a
  // native chrome slack below where the rows END (rows fill T..B). framecover then scales the
  // WHOLE rect by scale_uniform, turning that 3px slack into scale*3 (~5px @1600). Restore the
  // additive-constant law: the slack must stay = stroke K, not scale*3.
  const A_PICKWIN = 0x00822718;
  let pickLogged = false;
  function pickNativeListTB() {
    const W = ptr(VA(A_PICKWIN));
    try {
      const T = W.add(0x86b0).readS32(), B = W.add(0x86b8).readS32();
      if (!pickLogged) {
        pickLogged = true;
        log("pickwin nativeT/B=" + T + "/" + B + " (L/R=" + W.add(0x86ac).readS32()
          + "/" + W.add(0x86b4).readS32() + ")");
      }
      if (T > 0 && B > T + 40 && B - T < 400) return { T, B };
    } catch (e) { log("pickwin read failed: " + e); }
    return null;
  }

  // The row pitch is NOT at a fixed window offset. FactionPickWin_build stores it with
  //   0x48924b  mov eax,[ebx]          ; ebx = esi+0x86bc -> the Dialog's VPTR
  //   0x48924d  mov ecx,[eax+8]        ; ecx = VIRTUAL-BASE ADJUSTOR
  //   0x489250  mov [ecx+esi+0x8704],0x13
  // so pitchAddr = W + [[W+0x86bc]+8] + 0x8704. (rowgap is the same base + 0x8700.)
  const NATIVE_PITCH = 19;
  let pitchLogged = false;
  function findPitch(su) {
    const W = ptr(VA(A_PICKWIN));
    try {
      const adj = W.add(0x86bc).readPointer().add(8).readS32();
      if (adj < 0 || adj > 0x10000) return null;
      const p = W.add(adj + 0x8704).readS32();
      if (!pitchLogged) {
        pitchLogged = true;
        log("pitch @W+0x" + (adj + 0x8704).toString(16) + " (adj=0x" + adj.toString(16) + ") = " + p
          + "  gap@+0x" + (adj + 0x8700).toString(16) + " = " + W.add(adj + 0x8700).readS32()
          + "  faithful su*19=" + (su * NATIVE_PITCH).toFixed(2));
      }
      if (p >= 8 && p <= 200) return p;
    } catch (e) { log("pitch read failed: " + e); }
    return null;
  }

  const seen = {};
  function core(dest, rectPtr, par, deltaFromG, prefillKey, blitKey, tag) {
    const g = gnow();
    // Consume the exact-fill one-shot exactly where the shipped chain (via frame_enlarge) would
    // have: its setters arm it immediately before this call. Leaving it armed hands a stale
    // override to the next real frame_enlarge caller. Exact fill is structural here (DW IS the
    // rect span), so the value itself is unused.
    if (!PASSTHRU && g > 0x10) ptr(VA(G_FC_EXACT)).writeS32(0);
    const nb = cornerBand(par);
    // g<=16 is the identity; synthetic devfill sets (0xa0cec0) have no corner sprite.
    if (PASSTHRU || g <= 0x10 || !nb || (ONLY_SIMPLE && (nb.nx !== 6 || nb.ny !== 6))) {
      Buffer_box_sprite(dest, rectPtr, par);
      return;
    }

    const D = deltaFromG ? ((g - 16) >> 3) : 0;
    let dh = dest.add(0x84).readS32(); if (dh < 0) dh = -dh;
    const dw = dest.add(0x80).readS32();
    if (rectPtr.add(8).readS32()  > dw - 1 - D) rectPtr.add(8).writeS32(dw - 1 - D);
    if (rectPtr.add(12).readS32() > dh - 1 - D) rectPtr.add(12).writeS32(dh - 1 - D);

    const X  = rectPtr.readS32() - D,        Y  = rectPtr.add(4).readS32() - D;
    const Xr = rectPtr.add(8).readS32() + D;
    let   Yb = rectPtr.add(12).readS32() + D;

    // list-ring bottom slack: the d5a0 draw on the PICKER window buffer below the title ring.
    // Everything below derives from the INCOMING rect + the native list T/B -- no pitch, no
    // Dialog scan, no screen-res literal (so it holds under scale_uniform != g/16, e.g. 1920).
    //   ringTop_n = T-3   ringBot_n = B+3   rowsEnd_n = B      span_n = (B+3)-(T-3)
    //   scale     = (Yb - Y) / span_n                          (whatever framecover applied)
    //   Yb_new    = Y + scale*(B - T + 3) + K                  (rows end, then a K-wide slack)
    // At g=16 scale=1 and K=1 -> Yb_new = Y + (B-T+3) + 1 = Y + span_n = Yb. Exact no-op. The
    // native 3px slack is an ADDITIVE constant: it must not scale ([[feedback-match-opposite-edge-margin]]).
    if (par.toUInt32() === 0x78d5a0 && dest.toUInt32() === 0x00822b5c && Y > 100) {
      const nt = pickNativeListTB();
      if (nt) {
        const spanN = (nt.B + 3) - (nt.T - 3);          // native ring span
        const su = (Yb - Y) / spanN;                    // whatever framecover applied (NOT g/16)
        const pitch = findPitch(su);
        if (pitch) {
          // rowsTop = ringTop + su*3; ring bottom follows the ROWS, exactly as vanilla does.
          const nyb = Y + Math.round(su * 3) + 7 * pitch;
          log("listring flush: Y=" + Y + " Yb=" + Yb + " -> " + nyb + " (su=" + su.toFixed(4)
            + " pitch=" + pitch + " faithful=" + (su * NATIVE_PITCH).toFixed(2)
            + " reclaimed=" + (Yb - nyb) + "px)");
          if (nyb < Yb && nyb > Y + 8) { Yb = nyb; rectPtr.add(12).writeS32(Yb - D); }
        }
      }
    }
    const DW = Xr - X + 1, DH = Yb - Y + 1;               // exact fill, by construction

    // native scratch size, exactly as the shipped thunks compute it
    const srcW = Math.max(2 * nb.nx, (DW * 16 / g) | 0);
    const srcH = Math.max(2 * nb.ny, (DH * 16 / g) | 0);
    const FX = axisMap(srcW, DW, nb.nx), FY = axisMap(srcH, DH, nb.ny);
    if (!FX || !FY) { Buffer_box_sprite(dest, rectPtr, par); return; }

    const k = tag + "|" + dest.toUInt32().toString(16) + "|" + par.toUInt32().toString(16);
    if (!seen[k]) {
      seen[k] = 1;
      const mx = fwdMap(nb.nx, srcW, DW), my = fwdMap(nb.ny, srcH, DH);
      log(tag + " par=0x" + par.toUInt32().toString(16) + " dest=0x" + dest.toUInt32().toString(16)
        + " rect=[" + X + "," + Y + "," + Xr + "," + Yb + "] D=" + D
        + " band=" + nb.nx + "x" + nb.ny + " src=" + srcW + "x" + srcH + " dst=" + DW + "x" + DH
        + " corner=" + mx.B + "x" + my.B + " stroke=" + mx.stroke + "/" + my.stroke
        + " ratio=" + (DW / srcW).toFixed(4) + "/" + (DH / srcH).toFixed(4)
        + " cornerScale=" + (mx.B / nb.nx).toFixed(4) + "/" + (my.B / nb.ny).toFixed(4));
    }

    // ---- render into the scratch EXACTLY as the shipped thunk does ------------------------------
    const buf = ensure_frame_buf();
    Buffer_resize(buf, srcW, srcH);
    scratchRect.writeS32(0); scratchRect.add(4).writeS32(0);
    scratchRect.add(8).writeS32(srcW); scratchRect.add(12).writeS32(srcH);
    Buffer_set_clip(buf, scratchRect);
    Buffer_fill_3(buf, scratchRect, prefillKey);
    Buffer_box_sprite(buf, scratchRect, par);

    // ---- our enlarge: 9-slice map per axis, key-skipped, run-length emitted ---------------------
    const sdata = buf.add(0x54).readPointer();
    const sstride = buf.add(0x4a8).readS32();
    if (sdata.isNull() || sstride < srcW) { Buffer_box_sprite(dest, rectPtr, par); return; }

    const cols = new Uint8Array(DW);
    let lastSy = -1, srcRow = null;
    for (let j = 0; j < DH; j++) {
      const sy = FY[j];
      if (sy !== lastSy) {                       // one readByteArray per DISTINCT source row
        srcRow = new Uint8Array(sdata.add(sy * sstride).readByteArray(srcW));
        lastSy = sy;
      }
      for (let i = 0; i < DW; i++) cols[i] = srcRow[FX[i]];
      emitRow(dest, Y + j, X, cols, DW, blitKey);
    }

    // ---- CORNER DIAGNOSTIC (2026-07-09): dump what WE just left in the dest TL corner ----------
    // The 1600 screenshot shows the quote-box ring corner OPEN (no chamfer diagonal), but the
    // native sprite has a 1f diag at (1,1) and the band map assigns it >=1px. Either our emit
    // drops it, or a LATER draw overpaints it. Dumping the dest block right after our emit and
    // comparing with the final screenshot separates the two. Small-band sets only.
    if (nb.nx <= 8 && nb.ny <= 8 && !seen[k + "|c"]) {
      seen[k + "|c"] = 1;
      const mx2 = fwdMap(nb.nx, srcW, DW), my2 = fwdMap(nb.ny, srcH, DH);
      log("  bandwidths x=[" + Array.from(mx2.w).join(",") + "] y=[" + Array.from(my2.w).join(",") + "]");
      try {
        const ddata = dest.add(0x54).readPointer(), dstride = dest.add(0x4a8).readS32();
        if (!ddata.isNull() && dstride > 0) {
          const bx = Math.min(mx2.B + 3, DW), by = Math.min(my2.B + 3, DH);
          for (let j = 0; j < by; j++) {
            const row = new Uint8Array(ddata.add((Y + j) * dstride + X).readByteArray(bx));
            log("  cnr y" + (Y + j) + ": " + Array.from(row).map(b => ("0" + b.toString(16)).slice(-2)).join(" "));
          }
        }
      } catch (e) { log("  cnr dump failed: " + e); }
    }

    // ---- dither parity: the frame_enlarge epilogue, verbatim -----------------------------------
    // Stash the blit geometry + the src scratch (for the remap's navy C4 content scan) and run
    // thunk_fe_pair_remap over the dest rect. It rewrites ONLY the three dither-pair colours to
    // the device-density stripe law; strokes/bevels/art/text pass through untouched.
    ptr(VA(G_FE_DST)).writeU32(dest.toUInt32());
    ptr(VA(G_FE_X)).writeS32(X);
    ptr(VA(G_FE_Y)).writeS32(Y);
    ptr(VA(G_FE_W)).writeS32(DW);
    ptr(VA(G_FE_H)).writeS32(DH);                // POSITIVE height; the remap negates dest +0x84 itself
    ptr(VA(G_FE_SRC)).writeU32(buf.toUInt32());
    fe_pair_remap();
  }

  function install(addr, deltaFromG, prefillKey, blitKey, tag) {
    Interceptor.replace(ptr(VA(addr)), new NativeCallback(
      function (dest, rectPtr, par) { core(dest, rectPtr, par, deltaFromG, prefillKey, blitKey, tag); },
      'void', ['pointer','pointer','pointer'], 'thiscall'));
    log("replaced " + tag + " @0x" + addr.toString(16));
  }

  install(0x00668E00, true,  0x41, -1, "box_thick(title)");
  install(0x00A0C000, true,  0x09,  9, "hollow(outer)");
  install(0x00A0C140, false, 0x09,  9, "hollow_flat(body)");
  install(0x00A12C00, false, 0x09,  9, "intK(faction)");

  log("g=" + gnow() + "  (band map now derives from DW/srcW, not g/16)");
  log("Walk: main menu -> Quit modal -> file picker -> faction picker -> HUD.");
}
