// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// BAND-FIX PROTOTYPE (2026-07-06) — ACTIVE LEVERS, prototype of the two banding fixes.
// Evidence base: frida_band_census.log + flc_census.py (both defects = 1px scanline
// dither pairs beaten by fractional NN — skill scaling-frames §7).
//   [MC] MENU/COMMLINK band: after the baked 2dscale stretch (thunk_keyed_stretch_blit,
//        dest ∈ HUD button buffers), re-stripe pixels ∈ {0xC8,0x92} at device density
//        (P-law, 0x92 on top — the sprite's even rows). Scoped to the 4 HUD sprite
//        buttons: C8/C9 are legit art shading elsewhere (pair-ambiguity rule).
//   [TB] TURN banner: after thunk_band_draw's Buffer_copy_3 stretch, re-stripe the dest
//        rect with the pair read DYNAMICALLY from the native scratch (flash frames
//        recolor the same layout with a different pair per frame). Key 0x09-substituted
//        backdrop + 0x65 border pixels pass through untouched.
// Both levers: g<=16 no-op by construction (stretch sites only run at g>16).
// Attach-safety: fn-entry hooks only, onLeave on fn-entry (NOT call-insn) = safe.
// NOTE: baked btn_stripes/fe_pair_remap only touch E0/E1+AE/EE(+keyed navy) — disjoint
// from C8/92, no double-apply. Nothing else remaps the band rect.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_band_fixproto.log";
log("=== hook_band_fixproto.js started ===");
installAVHandler("band_fixproto");

function hex(v) { return "0x" + (v >>> 0).toString(16); }

if (requireBase()) {
  const G_SCALE = VA(0x668740);            // g_popup_scale_num
  const KSB = VA(0x668670);                // thunk_keyed_stretch_blit
  const C3 = VA(0x5D9610);                 // Buffer_copy_3 entry (thiscall ecx=src)
  const CAVE = 0x00A0C000;
  const BAND_LO = VA(CAVE + 0x4E80).toUInt32(), BAND_HI = VA(CAVE + 0x4F84).toUInt32();
  const BTN = {};
  BTN[VA(0x7B1804).add(0x444).toUInt32()] = "MENU";
  BTN[VA(0x7B2350).add(0x444).toUInt32()] = "COMMLINK";
  BTN[VA(0x7B39E8).add(0x444).toUInt32()] = "WORLD";
  BTN[VA(0x7B4534).add(0x444).toUInt32()] = "DETAIL";

  const counts = {};
  function bump(k) { counts[k] = (counts[k] || 0) + 1; }

  // Re-stripe pixels ∈ {a,b} of buffer buf in rect (rx,ry,rw,rh) to the device-density
  // P-law: y%P < hN -> top else bot. Phase = OWNING BUFFER row (phase law).
  // trustRect: clip width to the stride only, NOT the buffer W/H fields — during the
  // 2dscale bracket the button buffer's dim fields still hold the SHRUNKEN native size
  // while the plane already holds the stretched content (the v1 top/bottom-half bug).
  function restripe(buf, rx, ry, rw, rh, a, b, top, bot, trustRect) {
    const data = buf.add(0x54).readU32();
    const stride = buf.add(0x4a8).readS32();
    const bw = buf.add(0x80).readS32();
    let bh = buf.add(0x84).readS32(); if (bh < 0) bh = -bh;
    if (!data || stride <= 0) return "(no plane)";
    const g = G_SCALE.readS32();
    if (g <= 16) return "(g<=16)";
    const P = SL.stripePeriod(g, 0), hN = (P + 1) >> 1;
    const x0 = Math.max(rx, 0), y0 = Math.max(ry, 0);
    const x1 = Math.min(rx + rw, trustRect ? stride : bw);
    const y1 = Math.min(ry + rh, trustRect ? ry + rh : bh);
    if (rh > 512 || rw > 4096) return "(rect insane " + rw + "x" + rh + ")";
    if (x1 <= x0 || y1 <= y0) return "(clipped out)";
    const base = ptr(hex(data));
    let n = 0;
    for (let y = y0; y < y1; y++) {
      const rowp = base.add(y * stride + x0);
      const raw = rowp.readByteArray(x1 - x0);
      if (!raw) return "(read fail)";
      const row = new Uint8Array(raw);
      const c = (y % P) < hN ? top : bot;
      let dirty = false;
      for (let x = 0; x < row.length; x++) {
        const v = row[x];
        if (v === a || v === b) { if (v !== c) { row[x] = c; dirty = true; } n++; }
      }
      if (dirty) rowp.writeByteArray(row.buffer);
    }
    return "P=" + P + "/" + hN + " remapped=" + n + " rect=(" + x0 + "," + y0 + ".." + x1 + "," + y1 + ")";
  }

  // --- [MC] HUD sprite-button post-stretch re-stripe (pair C8/92, 92 on top) ---
  Interceptor.attach(KSB, {
    onEnter() {
      const sp = this.context.esp;
      const dest = u32(arg(sp, 2));
      this.name = BTN[dest];
      if (!this.name) return;
      this.dest = ptr(hex(dest));
      this.dx = argS(sp, 7); this.dy = argS(sp, 8);
      this.dw = argS(sp, 9); this.dh = argS(sp, 10);
    },
    onLeave() {
      if (!this.name) return;
      bump("mc_" + this.name);
      const r = restripe(this.dest, this.dx, this.dy, this.dw, this.dh, 0xC8, 0x92, 0x92, 0xC8, true);
      if ((counts["mc_" + this.name] || 0) <= 3) log("[MC] " + this.name + " " + r);
    }
  });

  // --- [TB] banner post-stretch re-stripe, pair detected from the native scratch ---
  Interceptor.attach(C3, {
    onEnter() {
      const sp = this.context.esp;
      const ret = sp.readU32();
      this.band = ret >= BAND_LO && ret < BAND_HI;
      if (!this.band) return;
      this.scr = this.context.ecx;
      this.dst = ptr(hex(u32(arg(sp, 1))));
      this.sw = argS(sp, 4); this.sh = argS(sp, 5);
      this.dx = argS(sp, 6); this.dy = argS(sp, 7);
      this.dw = argS(sp, 8); this.dh = argS(sp, 9);
    },
    onLeave() {
      if (!this.band) return;
      bump("tb");
      try {
        // pair from two adjacent interior rows, mid-band (edges are key/border)
        const data = this.scr.add(0x54).readU32();
        const stride = this.scr.add(0x4a8).readS32();
        const base = ptr(hex(data));
        const xm = this.sw >> 1, yA = this.sh >> 1, yB = yA + 1;
        const vA = base.add(yA * stride + xm).readU8();
        const vB = base.add(yB * stride + xm).readU8();
        if (vA === vB || vA === 9 || vB === 9 || vA === 0x65 || vB === 0x65) {
          if (counts.tb <= 5) log("[TB] skip (no pair: " + hex(vA) + "/" + hex(vB) + ")");
          return;
        }
        // top = the member on the EVEN native row (matches the band sprite's 92-on-top)
        const top = (yA % 2 === 0) ? vA : vB;
        const bot = (top === vA) ? vB : vA;
        const r = restripe(this.dst, this.dx, this.dy, this.dw, this.dh, vA, vB, top, bot);
        if (counts.tb <= 8) log("[TB] pair=" + hex(vA) + "/" + hex(vB) + " top=" + hex(top) + " " + r);
      } catch (e) { log("[TB] err " + e); }
    }
  });

  setInterval(function () { log("...alive " + JSON.stringify(counts) + " g=" + G_SCALE.readS32()); }, 5000);
  log("armed: KSB@" + KSB + " C3@" + C3 + " bandret=[" + hex(BAND_LO) + "," + hex(BAND_HI) + ")");
}
