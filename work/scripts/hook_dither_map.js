"use strict";
// DITHER-MAP evidence probe (2026-07-03): root-cause the scanline banding seen in
// refs\MangledSmacx.png (Customize Game Rules @1920x1080, g=22) and "a wide variety of
// other menus". Answers, in ONE run per resolution:
//   Q1: which frame-enlarge calls (caller retaddr + dest rect) paint the banded title
//       band vs the banded light-blue row bars.
//   Q2: what palette index the d690 backdrop FILL uses (params[8] @ +0x20) — is it
//       solid 0x41? (decides blanket vs opt-in for the generalized remap)
//   Q3: whether the option-row bars flow through thunk_frame_enlarge, Buffer_tile,
//       thunk_keyed_stretch_blit (direct), or thunk_sprite_scale_nn.
//   Q4: per-pair histogram + MAX VERTICAL RUN in every NN-enlarged source art buffer:
//       runs <=2 for {41,C4,E0,E1,AE,EE} everywhere => pure scanline dither => a
//       blanket pair-remap is safe by construction.
// Observer only — writes nothing.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_dither_map.log";
log("=== hook_dither_map.js started ===");
installAVHandler("dither_map");

const PAIRS = [0x41, 0xC4, 0xE0, 0xE1, 0xAE, 0xEE];

function hex(v) { return "0x" + (v >>> 0).toString(16); }

// Walk a Buffer's pixel plane: count + max vertical run per pair index.
// Buffer: data +0x54, stride +0x4a8, w +0x80, h +0x84 (h stored NEGATIVE).
function pairHisto(buf) {
  try {
    const data = buf.add(0x54).readU32();
    const stride = buf.add(0x4a8).readS32();
    const w = buf.add(0x80).readS32();
    let h = buf.add(0x84).readS32(); if (h < 0) h = -h;
    if (!data || stride <= 0 || w <= 0 || h <= 0) return "(no plane)";
    if (w * h > 1200000) return "(skipped " + w + "x" + h + ")";
    const plane = ptr("0x" + (data >>> 0).toString(16)).readByteArray(stride * h);
    if (!plane) return "(read fail)";
    const a = new Uint8Array(plane);
    const cnt = {}, maxrun = {}, currun = {};
    for (const p of PAIRS) { cnt[p] = 0; maxrun[p] = 0; }
    for (let x = 0; x < w; x++) {
      for (const p of PAIRS) currun[p] = 0;
      for (let y = 0; y < h; y++) {
        const v = a[y * stride + x];
        for (const p of PAIRS) {
          if (v === p) { cnt[p]++; currun[p]++; if (currun[p] > maxrun[p]) maxrun[p] = currun[p]; }
          else currun[p] = 0;
        }
      }
    }
    let s = w + "x" + h;
    for (const p of PAIRS) if (cnt[p]) s += " " + hex(p) + ":n=" + cnt[p] + ",vrun=" + maxrun[p];
    return s;
  } catch (e) { return "(err " + e + ")"; }
}

// Distinct-index census of the first rows of a Buffer (for the d690 fill tile).
function fillCensus(buf, rows) {
  try {
    const data = buf.add(0x54).readU32();
    const stride = buf.add(0x4a8).readS32();
    const w = buf.add(0x80).readS32();
    let h = buf.add(0x84).readS32(); if (h < 0) h = -h;
    if (!data || stride <= 0 || w <= 0 || h <= 0) return "(no plane)";
    const n = Math.min(rows, h);
    const seen = {};
    const base = ptr("0x" + (data >>> 0).toString(16));
    for (let y = 0; y < n; y++)
      for (let x = 0; x < w; x++) {
        const v = base.add(y * stride + x).readU8();
        seen[v] = (seen[v] || 0) + 1;
      }
    return w + "x" + h + " rows0.." + (n - 1) + " idx{" +
      Object.keys(seen).map(k => hex(+k) + ":" + seen[k]).join(",") + "}";
  } catch (e) { return "(err " + e + ")"; }
}

if (requireBase()) {
  const G_SCALE = VA(0x668740);
  const CAVE = 0x00A0C000;
  const FE = VA(CAVE + 0x30A0);           // thunk_frame_enlarge
  const FE_END = VA(CAVE + 0x315E);
  const G_FILEDLG = VA(CAVE + 0x23A0);    // g_filedlg_active
  const G_BILIN = VA(CAVE + 0x2940);      // g_fd_bilinear
  const G_EXACT = VA(CAVE + 0x2554);      // g_fc_exact
  const G_FE_DST = VA(CAVE + 0x2FA0), G_FE_X = VA(CAVE + 0x2FA4), G_FE_Y = VA(CAVE + 0x2FA8),
        G_FE_W = VA(CAVE + 0x2FAC), G_FE_H = VA(CAVE + 0x2FB0);
  const KSB = VA(0x668670);               // thunk_keyed_stretch_blit
  const NN = VA(CAVE + 0x2150);           // thunk_sprite_scale_nn
  const BOX = VA(0x5e2dd3);               // Buffer_box_sprite (thiscall ecx=dest)
  const TILE = VA(0x5DA860);              // Buffer_tile (thiscall ecx=dest, 7 stack args, arg1=sprite)
  const PAL = VA(0x94c590);               // PALETTEENTRY[256]
  const D690 = VA(0x78d690).toUInt32(), D528 = VA(0x78d528).toUInt32(),
        D5A0 = VA(0x78d5a0).toUInt32(), D618 = VA(0x78d618).toUInt32();

  function tagP(u) {
    const v = u >>> 0;
    return v === D690 ? "d690" : v === D528 ? "d528" : v === D5A0 ? "d5a0" : v === D618 ? "d618" : hex(v);
  }
  let palDone = false;
  function dumpPal() {
    if (palDone) return; palDone = true;
    let s = "PALETTE:";
    for (const p of PAIRS) {
      const e = PAL.add(p * 4);
      s += " " + hex(p) + "=(" + e.readU8() + "," + e.add(1).readU8() + "," + e.add(2).readU8() + ")";
    }
    log(s + " g=" + G_SCALE.readS32());
  }

  const seen = new Set();
  function once(key) { if (seen.has(key)) return false; seen.add(key); return true; }
  const counts = {};
  function bump(k) { counts[k] = (counts[k] || 0) + 1; }

  // --- Q1/Q4: thunk_frame_enlarge — caller, args, flags, src pair histogram, dest stash ---
  Interceptor.attach(FE, {
    onEnter() {
      dumpPal();
      bump("frame_enlarge");
      const sp = this.context.esp;
      this.ret = sp.readU32();
      this.src = this.context.ecx;
      this.dest = u32(arg(sp, 1));
      this.key = argS(sp, 2);
      this.flags = "fdlg=" + G_FILEDLG.readS32() + " bilin=" + G_BILIN.readS32() + " exact=" + G_EXACT.readS32();
    },
    onLeave() {
      const k = "FE " + hex(this.ret) + " " + hex(this.dest) + " " +
        G_FE_W.readS32() + "x" + G_FE_H.readS32();
      if (!once(k)) return;
      log("[FE] ret=" + hex(this.ret) + " dest=" + hex(this.dest) +
        " dst(x,y,w,h)=(" + G_FE_X.readS32() + "," + G_FE_Y.readS32() + "," +
        G_FE_W.readS32() + "," + G_FE_H.readS32() + ") key=" + this.key +
        " " + this.flags + " src[" + pairHisto(this.src) + "]");
    }
  });

  // --- Q2: Buffer_box_sprite — params tag, rect, dest; d690 fill census ---
  Interceptor.attach(BOX, {
    onEnter() {
      bump("box_sprite");
      const sp = this.context.esp;
      const rc = ptr("0x" + u32(arg(sp, 1)).toString(16));
      const params = u32(arg(sp, 2));
      const ret = sp.readU32();
      let rect = "?";
      try {
        rect = rc.readS32() + "," + rc.add(4).readS32() + "," + rc.add(8).readS32() + "," + rc.add(12).readS32();
      } catch (e) {}
      const k = "BOX " + hex(ret) + " " + tagP(params);
      if (!once(k)) return;
      let fill = "";
      if ((params >>> 0) === D690 || (params >>> 0) === D528 || (params >>> 0) === D618) {
        try {
          const f = ptr("0x" + params.toString(16)).add(0x20).readU32();
          fill = f ? " fill@" + hex(f) + "[" + fillCensus(ptr("0x" + (f >>> 0).toString(16)), 4) + "]" : " fill=NULL";
        } catch (e) { fill = " fill(err)"; }
      }
      log("[BOX] ret=" + hex(ret) + " params=" + tagP(params) + " dest=" + hex(this.context.ecx.toUInt32()) +
        " rect=(" + rect + ")" + fill);
    }
  });

  // --- Q3: Buffer_tile — sprite identity/dims + dest ---
  Interceptor.attach(TILE, {
    onEnter() {
      bump("tile");
      const sp = this.context.esp;
      const ret = sp.readU32();
      const spr = u32(arg(sp, 1));
      const k = "TILE " + hex(ret) + " " + hex(spr);
      if (!once(k)) return;
      let dims = "?", col = "";
      try {
        const b = ptr("0x" + spr.toString(16));
        const w = b.add(0x80).readS32(); let h = b.add(0x84).readS32(); if (h < 0) h = -h;
        dims = w + "x" + h;
        const data = b.add(0x54).readU32(), stride = b.add(0x4a8).readS32();
        if (data && stride > 0) {
          const base = ptr("0x" + (data >>> 0).toString(16));
          const out = [];
          for (let y = 0; y < Math.min(h, 8); y++) out.push(hex(base.add(y * stride).readU8()));
          col = " col0=" + out.join(",");
        }
      } catch (e) {}
      log("[TILE] ret=" + hex(ret) + " dest=" + hex(this.context.ecx.toUInt32()) + " sprite=" + hex(spr) +
        " " + dims + col + " args=(" + argS(sp, 2) + "," + argS(sp, 3) + "," + argS(sp, 4) + "," +
        argS(sp, 5) + "," + argS(sp, 6) + "," + argS(sp, 7) + ")");
    }
  });

  // --- Q3: direct thunk_keyed_stretch_blit callers (skip calls from inside frame_enlarge) ---
  Interceptor.attach(KSB, {
    onEnter() {
      bump("ksb");
      const sp = this.context.esp;
      const ret = sp.readU32();
      const r = ptr("0x" + ret.toString(16));
      if (r.compare(FE) >= 0 && r.compare(FE_END) < 0) return;  // frame_enlarge's own blit
      const srcW = argS(sp, 5), srcH = argS(sp, 6), dstW = argS(sp, 9), dstH = argS(sp, 10);
      const k = "KSB " + hex(ret) + " " + srcW + "x" + srcH + ">" + dstW + "x" + dstH;
      if (!once(k)) return;
      const src = u32(arg(sp, 1));
      log("[KSB-direct] ret=" + hex(ret) + " src=" + hex(src) + " dest=" + hex(u32(arg(sp, 2))) +
        " " + srcW + "x" + srcH + " -> " + dstW + "x" + dstH + " at(" + argS(sp, 7) + "," + argS(sp, 8) +
        ") key=" + argS(sp, 11) + " src[" + pairHisto(ptr("0x" + src.toString(16))) + "]");
    }
  });

  // --- Q3: thunk_sprite_scale_nn direct callers ---
  Interceptor.attach(NN, {
    onEnter() {
      bump("nn");
      const sp = this.context.esp;
      const ret = sp.readU32();
      const k = "NN " + hex(ret);
      if (!once(k)) return;
      log("[NN] ret=" + hex(ret) + " a1..a6=(" + argS(sp, 1) + "," + argS(sp, 2) + "," + argS(sp, 3) +
        "," + argS(sp, 4) + "," + argS(sp, 5) + "," + argS(sp, 6) + ")");
    }
  });

  log("hooks installed (FE=" + FE + " KSB=" + KSB + " NN=" + NN + ")");
  setInterval(function () {
    log("...alive " + JSON.stringify(counts));
  }, 5000);
}
