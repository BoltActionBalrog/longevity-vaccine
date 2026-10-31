// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// PROTOTYPE (2026-07-09): uniform integer-K frame strokes for EVERY popup frame, with the
// fractional pixel spent on the ELEMENT'S OUTER EXTENT instead of on a channel or a stroke.
// Runtime-only: the exe on disk stays at the 75cae700 lock. Kill the game to revert.
//
// THE LAW
//   K = (g+7)>>4  = round_half_down(g/16).  Over the whole clamp g in [16,40] this is K=1 for
//   g<=24 and K=2 for g in [25,40] -- K NEVER exceeds 2, so "multiple of K" == "even".
//
//   Uniform strokes need dstW = srcW*K exactly (then every source pixel maps to exactly K dest
//   pixels, so both edge strokes are K for ANY span).  Exact rect fill needs dstW = span.  Those
//   two conflict IFF span % K != 0 -- and NN dumps the whole remainder onto one source pixel,
//   which is an edge stroke.  (Verified by simulation: exact-fill with srcW=round/floor/ceil all
//   give edge strokes (2,1) or (3,2) on every odd span.)
//
//   RESOLUTION: snap the RECT to the K-lattice, then span % K == 0 and the conflict vanishes.
//   Both strokes land at exactly K, the frame fills its rect exactly, and the <=1px error shows
//   up as the element's outer extent moving -- never as a stroke width and never as a channel.
//   Because EVERY frame in EVERY popup snaps to the SAME lattice, inner margins are differences
//   of even coordinates and cannot wobble by one pixel.
//   At K=1 (all g<=24: 1920x1080, 1024x768) the snap is a no-op by construction.
//
// SNAP DIRECTION: floor all four coords to even, AFTER the clamp. Flooring R/B can only move them
// inward, so a rect clamped to the dest bitmap stays clamped. (Ceiling R would push past the bound.)
//
// The 3 shipped renderers are the same function modulo (Delta, prefill key, blit key):
//   thunk_box_thick             0x668E00  D=(g-16)>>3  prefill 0x41  key -1   <- TITLE boxes
//   thunk_box_thick_hollow      0xA0C000  D=(g-16)>>3  prefill 0x09  key  9   <- OUTER union frames
//   thunk_box_thick_hollow_flat 0xA0C140  D=0          prefill 0x09  key  9   <- bodies / lists / rows
//   thunk_frame_intK            0xA12C00  D=0          prefill 0x09  key  9   <- faction quote (now redundant)
// All four are replaced here by one core, so thunk_dfstep1_dispatch's routing becomes irrelevant
// and hook_intkglobal.js must NOT be loaded alongside this script.
//
// g_fc_exact (0xA0E554) forces thunk_frame_enlarge to override dstW/dstH from the UNSNAPPED rect.
// Under integer-K that reintroduces the fractional phase, so the core clears it before enlarging.
// It becomes unnecessary: with an even span the natural path already fills the rect exactly.
// The 3 setters (filedlg_frame, factionwin_framecover, hud_widgets) each fixed a REAL far-edge
// shortfall under the fractional renderer -> re-verify those surfaces: file picker, faction
// picker, HUD widgets.
//
// Log: work/tests/frida_intksnap.log
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_intksnap.log";
log("=== hook_intksnap.js started (PROTOTYPE: lattice-snapped integer-K frames) ===");

// ---- BISECT SWITCHES -------------------------------------------------------------------
// The prototype changes THREE things at once (integer-K ratio, lattice snap, g_fc_exact clear).
// Two regressions showed up at 4K, so isolate before theorising:
//   SNAP=false, CLEAR_FC=false  -> integer-K only. Is the quote frame still 4px high / gap 6?
//   SNAP=true,  CLEAR_FC=false  -> + lattice. Does the file-picker title channel come back right?
//   SNAP=true,  CLEAR_FC=true   -> the full prototype (what was just run).
const SNAP = true;
const CLEAR_FC = true;
// -----------------------------------------------------------------------------------------

if (requireBase()) {
  const G = 0x00668740, FC_EXACT = 0x00A0E554;
  const A_RESIZE = 0x005D79C0, A_SETCLIP = 0x005D8000, A_FILL3 = 0x005DFCD0,
        A_BOXSPR = 0x005E2DD3, A_ENSUREBUF = 0x00668EE0, A_ENLARGE = 0x00A0F0A0;

  const Buffer_resize   = new NativeFunction(ptr(VA(A_RESIZE)),  'void', ['pointer','int','int'], 'thiscall');
  const Buffer_set_clip = new NativeFunction(ptr(VA(A_SETCLIP)), 'void', ['pointer','pointer'], 'thiscall');
  const Buffer_fill_3   = new NativeFunction(ptr(VA(A_FILL3)),   'void', ['pointer','pointer','int'], 'thiscall');
  const Buffer_box_sprite = new NativeFunction(ptr(VA(A_BOXSPR)),'void', ['pointer','pointer','pointer'], 'thiscall');
  const ensure_frame_buf  = new NativeFunction(ptr(VA(A_ENSUREBUF)),'pointer', [], 'mscdecl');
  // thunk_frame_enlarge: thiscall(ecx=src) (dest, key, X, Y, num, den), RET 0x18
  const frame_enlarge = new NativeFunction(ptr(VA(A_ENLARGE)), 'void',
      ['pointer','pointer','int','int','int','int','int'], 'thiscall');

  const scratchRect = Memory.alloc(16);
  const gnow = () => ptr(VA(G)).readS32();

  let stats = {};
  function note(tag, span, K, snapped) {
    const k = tag + " K=" + K + (snapped ? " snapped" : " exact");
    stats[k] = (stats[k] || 0) + 1;
  }

  // Per-draw rect trace. The pixels say the faction quote frame moved UP 4px and its
  // outer<->inner gap went 7->6, which a <=1px lattice snap CANNOT do -- so one of the
  // assumptions below is false. Log the actual numbers instead of reasoning about them.
  //   dest        which buffer (0x940824 = faction quote winbuf)
  //   raw         rect as the caller passed it
  //   clamped     after the R/B clamp (this WRITES BACK into the caller's rect)
  //   snapped     after floor-to-even
  //   D/X/Y       delta and the draw origin  (Y must be EVEN when D==0)
  const seen = {};
  function trace(tag, dest, raw, clamped, snapped, D, X, Y, K, srcW, srcH) {
    const key = tag + "|" + dest;
    seen[key] = (seen[key] || 0) + 1;
    if (seen[key] > 4) return;             // first 4 draws per (tag,dest) only
    const r = (a) => "[" + a.join(",") + "]";
    log(tag + " dest=0x" + dest.toString(16) + " K=" + K + " D=" + D
      + " raw=" + r(raw) + " clamp=" + r(clamped) + " snap=" + r(snapped)
      + " X=" + X + " Y=" + Y + (D === 0 && (Y & 1) ? " *** Y ODD w/ D=0 ***" : "")
      + " src=" + srcW + "x" + srcH);
  }

  // One shared core. Mirrors the shipped thunks instruction-for-instruction except:
  //   (a) the rect is floored to the K-lattice after the clamp,
  //   (b) srcW = span/K  (exact -- no rounding, because span % K == 0), and
  //   (c) the enlarge ratio is num=K / den=1 instead of num=g / den=16.
  function core(dest, rectPtr, paramsPtr, deltaFromG, prefillKey, blitKey, tag) {
    const g = gnow();
    if (g <= 0x10) {                       // native no-op, byte-identical to vanilla
      Buffer_box_sprite(dest, rectPtr, paramsPtr);
      return;
    }
    const K = (g + 7) >> 4;
    const D = deltaFromG ? ((g - 16) >> 3) : 0;
    const raw = [rectPtr.readS32(), rectPtr.add(4).readS32(),
                 rectPtr.add(8).readS32(), rectPtr.add(12).readS32()];

    // --- clamp (thunk_clamp_frame_rect, reimplemented: it needs esi/ebx we can't set from JS) ---
    const dw = dest.add(0x80).readS32();
    let dh = dest.add(0x84).readS32();
    if (dh < 0) dh = -dh;                  // height is stored NEGATIVE (top-down buffers)
    if (rectPtr.add(8).readS32()  > dw - 1 - D) rectPtr.add(8).writeS32(dw - 1 - D);
    if (rectPtr.add(12).readS32() > dh - 1 - D) rectPtr.add(12).writeS32(dh - 1 - D);
    const clamped = [rectPtr.readS32(), rectPtr.add(4).readS32(),
                     rectPtr.add(8).readS32(), rectPtr.add(12).readS32()];

    // --- THE SNAP: floor all four to the K-lattice (no-op when K==1) ---
    let L = rectPtr.readS32(), T = rectPtr.add(4).readS32(),
        R = rectPtr.add(8).readS32(), B = rectPtr.add(12).readS32();
    const rawW = (R - L) + 2 * D;
    if (SNAP && K > 1) {
      const m = ~(K - 1);                  // K is 1 or 2 across the whole clamp -> mask is exact
      L &= m; T &= m; R &= m; B &= m;
    }
    const spanW = (R - L) + 2 * D, spanH = (B - T) + 2 * D;
    if (spanW < K * 3 || spanH < K * 3) {  // degenerate rect: leave it to the engine
      Buffer_box_sprite(dest, rectPtr, paramsPtr);
      return;
    }
    note(tag, spanW, K, spanW !== rawW);

    const X = L - D, Y = T - D;
    const srcW = spanW / K, srcH = spanH / K;      // exact: spanW % K == 0 by construction
    trace(tag, dest.toUInt32(), raw, clamped, [L, T, R, B], D, X, Y, K, srcW, srcH);

    const buf = ensure_frame_buf();
    Buffer_resize(buf, srcW, srcH);
    scratchRect.writeS32(0);
    scratchRect.add(4).writeS32(0);
    scratchRect.add(8).writeS32(srcW);
    scratchRect.add(12).writeS32(srcH);
    Buffer_set_clip(buf, scratchRect);
    Buffer_fill_3(buf, scratchRect, prefillKey);
    Buffer_box_sprite(buf, scratchRect, paramsPtr);

    if (CLEAR_FC) ptr(VA(FC_EXACT)).writeS32(0);   // integer-K supersedes exact-fill; see header
    frame_enlarge(buf, dest, blitKey, X, Y, K, 1);
  }

  function install(addr, deltaFromG, prefillKey, blitKey, tag) {
    // 'thiscall': first declared arg IS ecx (the dest Buffer), then the 2 stack args; callee-clean.
    Interceptor.replace(ptr(VA(addr)), new NativeCallback(
      function (dest, rectPtr, paramsPtr) {
        core(dest, rectPtr, paramsPtr, deltaFromG, prefillKey, blitKey, tag);
      }, 'void', ['pointer','pointer','pointer'], 'thiscall'));
    log("replaced " + tag + " @0x" + addr.toString(16));
  }

  install(0x00668E00, true,  0x41, -1, "box_thick(title)");
  install(0x00A0C000, true,  0x09,  9, "hollow(outer)");
  install(0x00A0C140, false, 0x09,  9, "hollow_flat(body)");
  install(0x00A12C00, false, 0x09,  9, "intK(faction)");

  log("g=" + gnow() + "  K=" + ((gnow() + 7) >> 4) + "  (K==1 -> snap is a no-op)");
  log("Open: main menu, Quit modal, file picker, faction picker, HUD. Watch TITLE box strokes.");
  setInterval(function () {
    const keys = Object.keys(stats);
    if (keys.length) log("-- draws: " + keys.map((k) => k + "=" + stats[k]).join("  "));
  }, 15000);
}
