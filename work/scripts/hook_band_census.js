"use strict";
// BAND-CENSUS evidence probe (2026-07-06) — OBSERVER ONLY, writes nothing.
// Targets the two open banding defects on the baked 5bab9446 exe:
//   (1) MENU/COMMLINK state-sprite banding @1600x1200 (g=25): capture the 106x14 band
//       sprite art at the state-sprite blit site (Sprite_draw_2 ret==0x607F48) AND the
//       full native-composed button buffer at the 2dscale stretch input
//       (thunk_keyed_stretch_blit entry, dest ∈ HUD button buffers) — per-index count +
//       max-vertical-run census decides pair-remap vs resample (skill scaling-frames §7b).
//   (2) TURN COMPLETE banner @1920x1080 (g=22): capture the native 233x23 scratch at
//       thunk_band_draw's final Buffer_copy_3 stretch (ret ∈ [pcave2+0x4E80,+0x4F84)).
//       Offline flc_census.py already proved frame 0 = 1px scanline dither pair C9/94
//       (per-frame pairs in the flash anim) — this validates the composed scratch live.
// Attach-safety: fn-entry hooks only, all plain-E8/push-ret-reached engine or cave fns
// (Sprite_draw_2 entry is PRACX-called at exact entry = OK; no site hooks anywhere, so
// the v27-32 soft-kill combo cannot form). See feedback-frida-attach-branch-target.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_band_census.log";
log("=== hook_band_census.js started ===");
installAVHandler("band_census");

function hex(v) { return "0x" + (v >>> 0).toString(16); }

// Generic per-index census of an 8bpp region: top counts, max vertical run,
// % pixels in vertical runs <=2, top vertical transitions.
function regionCensus(base, stride, w, h) {
  const raw = base.readByteArray(stride * (h - 1) + w);
  if (!raw) return "(read fail)";
  const a = new Uint8Array(raw);
  const cnt = {}, maxrun = {}, trans = {};
  let le2 = 0, tot = 0;
  for (let x = 0; x < w; x++) {
    let run = 0, prev = -1;
    for (let y = 0; y < h; y++) {
      const v = a[y * stride + x];
      cnt[v] = (cnt[v] || 0) + 1;
      if (v === prev) { run++; }
      else {
        if (prev >= 0) {
          tot += run; if (run <= 2) le2 += run;
          if (!(maxrun[prev] >= run)) maxrun[prev] = run;
          const k = prev < v ? prev + "-" + v : v + "-" + prev;
          trans[k] = (trans[k] || 0) + 1;
        }
        run = 1;
      }
      prev = v;
    }
    if (prev >= 0) { tot += run; if (run <= 2) le2 += run; if (!(maxrun[prev] >= run)) maxrun[prev] = run; }
  }
  const top = Object.keys(cnt).sort((p, q) => cnt[q] - cnt[p]).slice(0, 8);
  const tt = Object.keys(trans).sort((p, q) => trans[q] - trans[p]).slice(0, 5);
  return w + "x" + h +
    " idx{" + top.map(k => hex(+k) + ":n=" + cnt[k] + ",vrun=" + (maxrun[k] || h)).join(" ") + "}" +
    " le2=" + (100 * le2 / Math.max(tot, 1)).toFixed(1) + "%" +
    " trans{" + tt.map(k => k.split("-").map(v => hex(+v)).join("<->") + ":" + trans[k]).join(" ") + "}";
}

function dumpRows(tag, base, stride, w, h) {
  if (w > 320 || h > 64) { log(tag + " (dump skipped " + w + "x" + h + ")"); return; }
  for (let y = 0; y < h; y++) {
    const row = base.add(y * stride).readByteArray(w);
    if (!row) { log(tag + " y" + y + " (read fail)"); return; }
    log(tag + " y" + (y < 10 ? "0" : "") + y + " " +
      Array.from(new Uint8Array(row)).map(v => (v < 16 ? "0" : "") + v.toString(16)).join(""));
  }
}

if (requireBase()) {
  const G_SCALE = VA(0x668740);            // g_popup_scale_num
  const PAL = VA(0x94c590);                // PALETTEENTRY[256] (r,g,b,flags)
  const SD2 = VA(0x5E4B4A);                // Sprite_draw_2 entry (thiscall ecx=Sprite; dest,key,x,y,num,den)
  const SD2_STATE_RET = VA(0x607F48).toUInt32();  // ret of the FlatButton state-sprite site 0x607F43
  const KSB = VA(0x668670);                // thunk_keyed_stretch_blit (src,dest,sx,sy,sw,sh,dx,dy,dw,dh,key)
  const C3 = VA(0x5D9610);                 // Buffer_copy_3 entry (thiscall ecx=src; dst,sx,sy,sw,sh,dx,dy,dw,dh)
  const CAVE = 0x00A0C000;
  const BAND_LO = VA(CAVE + 0x4E80).toUInt32(), BAND_HI = VA(CAVE + 0x4F84).toUInt32();  // thunk_band_draw
  const RECAP_LO = BAND_HI, RECAP_HI = VA(CAVE + 0x4FF4).toUInt32();                     // thunk_band_recapture
  // HUD button statics (FlatButton objects; window buffer at +0x444)
  const BTN = {};
  BTN[VA(0x7B1804).add(0x444).toUInt32()] = "MENU";
  BTN[VA(0x7B2350).add(0x444).toUInt32()] = "COMMLINK";
  BTN[VA(0x7B39E8).add(0x444).toUInt32()] = "WORLD";
  BTN[VA(0x7B4534).add(0x444).toUInt32()] = "DETAIL";

  let palDone = false;
  function dumpPal() {
    if (palDone) return; palDone = true;
    for (let i = 0; i < 256; i += 16) {
      let s = "[PAL] " + hex(i) + ":";
      for (let j = 0; j < 16; j++) {
        const e = PAL.add((i + j) * 4);
        s += " (" + e.readU8() + "," + e.add(1).readU8() + "," + e.add(2).readU8() + ")";
      }
      log(s);
    }
    log("[PAL] g=" + G_SCALE.readS32());
  }

  const counts = {};
  function bump(k) { counts[k] = (counts[k] || 0) + 1; }
  const seen = new Set();
  function once(k) { if (seen.has(k)) return false; seen.add(k); return true; }
  const dumpN = {};
  function mayDump(k, cap) { dumpN[k] = (dumpN[k] || 0) + 1; return dumpN[k] <= cap; }

  // --- (1a) state-sprite blits at the 0x607F43 site (arrives via cave push;ret chain) ---
  // v2 (pressed-state census): ALSO match any Sprite_draw_2 whose dest is a HUD button
  // buffer regardless of return site — the pressed state may draw through a different
  // site; the logged ret identifies it.
  Interceptor.attach(SD2, {
    onEnter() {
      const sp = this.context.esp;
      const ret = sp.readU32();
      const destChk = u32(arg(sp, 1));
      if (ret !== SD2_STATE_RET && !BTN[destChk]) return;
      bump("sd2_state");
      dumpPal();
      const spr = this.context.ecx;
      // authoritative layout (reference-smac-sprite-struct-fields): data+0x4 key+0x8
      // pitch+0xC blitW+0x10 blitH+0x14 canvas+0x18/+0x1C offs+0x20/+0x24
      let data = ptr(0), pitch = 0, w = 0, h = 0, info = "?";
      try {
        data = ptr(hex(spr.add(0x4).readU32()));
        pitch = spr.add(0xC).readS32();
        w = spr.add(0x10).readS32();
        h = spr.add(0x14).readS32();
        info = "key8=" + spr.add(0x8).readU8() +
          " pitch=" + pitch + " blit=" + w + "x" + h +
          " canvas=" + spr.add(0x18).readS32() + "x" + spr.add(0x1C).readS32() +
          " offs=(" + spr.add(0x20).readS32() + "," + spr.add(0x24).readS32() + ")";
      } catch (e) { info = "(struct read err)"; }
      const dest = u32(arg(sp, 1));
      const line = "[SD2] ret=" + hex(ret) + " spr=" + spr + " " + info +
        " dest=" + hex(dest) + (BTN[dest] ? "(" + BTN[dest] + "buf)" : "") +
        " keyArg=" + argS(sp, 2) + " xy=(" + argS(sp, 3) + "," + argS(sp, 4) +
        ") num/den=" + argS(sp, 5) + "/" + argS(sp, 6);
      if (!once(line)) return;
      log(line);
      if (w > 0 && h > 0 && pitch >= w && !data.isNull()) {
        try {
          log("[SD2]   census " + regionCensus(data, pitch, w, h));
          if (mayDump("spr" + spr.toString(), 1)) dumpRows("[SD2]   " + spr, data, pitch, w, h);
        } catch (e) { log("[SD2]   (census err " + e + ")"); }
      }
    }
  });

  // --- (1b) native composed button buffer at the 2dscale stretch input ---
  Interceptor.attach(KSB, {
    onEnter() {
      const sp = this.context.esp;
      const dest = u32(arg(sp, 2));
      const name = BTN[dest];
      if (!name) return;
      bump("ksb_btn");
      dumpPal();
      const src = u32(arg(sp, 1));
      const raw = [];
      for (let i = 1; i <= 11; i++) raw.push(argS(sp, i));
      const sx = argS(sp, 3), sy = argS(sp, 4), sw = argS(sp, 5), sh = argS(sp, 6);
      log("[KSB] " + name + " ret=" + hex(sp.readU32()) + " src=" + hex(src) +
        " dest=" + hex(dest) + " args=" + raw.join(","));
      try {
        const b = ptr(hex(src));
        const data = b.add(0x54).readU32();
        const stride = b.add(0x4a8).readS32();
        const bw = b.add(0x80).readS32();
        let bh = b.add(0x84).readS32(); if (bh < 0) bh = -bh;
        if (!data || stride <= 0 || sw <= 0 || sh <= 0) return;
        const base = ptr(hex(data)).add(sy * stride + sx);
        // v2: dedup on CONTENT, not dims — the pressed state re-composes the same-size
        // window with different art; sample a mid-row so each state gets its own census.
        let sig = "";
        const midRow = base.add((sh >> 1) * stride).readByteArray(Math.min(sw, 24));
        if (midRow) sig = Array.from(new Uint8Array(midRow)).map(v => v.toString(16)).join("");
        const k = "KSB " + name + " " + sw + "x" + sh + ">" + argS(sp, 9) + "x" + argS(sp, 10) + " " + sig;
        if (!once(k)) return;
        log("[KSB]   srcbuf " + bw + "x" + bh + " stride=" + stride + " data=" + hex(data) + " sig=" + sig);
        log("[KSB]   census(native window) " + regionCensus(base, stride, sw, sh));
        if (mayDump("ksb" + name, 6)) dumpRows("[KSB]   " + name, base, stride, sw, sh);
      } catch (e) { log("[KSB]   (err " + e + ")"); }
    }
  });

  // --- (2) TURN banner: thunk_band_draw's Buffer_copy_3 stretch of the native scratch ---
  Interceptor.attach(C3, {
    onEnter() {
      const sp = this.context.esp;
      const ret = sp.readU32();
      const inBand = ret >= BAND_LO && ret < BAND_HI;
      const inRecap = ret >= RECAP_LO && ret < RECAP_HI;
      if (!inBand && !inRecap) return;
      bump(inBand ? "c3_band" : "c3_recap");
      dumpPal();
      const args = [];
      for (let i = 1; i <= 9; i++) args.push(argS(sp, i));
      log((inBand ? "[TB] band stretch" : "[TB] recapture shrink") +
        " ret=" + hex(ret) + " src(ecx)=" + this.context.ecx +
        " (dst,sx,sy,sw,sh,dx,dy,dw,dh)=" + args.join(","));
      if (!inBand) return;
      try {
        const b = this.context.ecx;   // g_band_scratch: native flic framebuffer
        const data = b.add(0x54).readU32();
        const stride = b.add(0x4a8).readS32();
        const w = b.add(0x80).readS32();
        let h = b.add(0x84).readS32(); if (h < 0) h = -h;
        if (data && stride > 0 && w > 0 && h > 0) {
          const base = ptr(hex(data));
          log("[TB]   scratch census " + regionCensus(base, stride, w, h));
          if (mayDump("tb", 4)) dumpRows("[TB]   scratch", base, stride, w, h);
        }
      } catch (e) { log("[TB]   (err " + e + ")"); }
    }
  });

  setInterval(function () { log("...alive " + JSON.stringify(counts) + " g=" + G_SCALE.readS32()); }, 5000);
  log("armed: SD2@" + SD2 + " KSB@" + KSB + " C3@" + C3 +
    " bandret=[" + hex(BAND_LO) + "," + hex(BAND_HI) + ")");
}
