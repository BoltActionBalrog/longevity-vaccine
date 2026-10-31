"use strict";
// THINKER KSB DOUBLE-ZOOM PROBE v2 -- OBSERVER ONLY, function-ENTRY hosts only, writes nothing.
//
// Symptom (user, 2026-10-28, workspace D:\SmacxThinker at 4K): under Thinker 5.5 the base screen's nerve-staple
// button (btn16 Buffer @0x6C06EC, 48x48 art, enlarged IN PLACE to 120x120 by thunk_staple_coverage) and EVERY
// scenario-editor palette icon draw a ~6.25x zoomed crop of their top-left corner (2.5 x 2.5). Thinker's
// render_high_detail=0 cures both. v1 (two runs, 2026-10-29) showed the staple thunk's INPUTS identical in both
// states (same source, 48x48 -> 120x120, same first row) and both logs capped at 600 lines before the base
// screen; so the fault is downstream of the thunk (someone stretches the already-enlarged buffer again with the
// native 48x48 rect) or in data past row 0. v2 therefore:
//   - never caps a line that touches a WATCHED buffer: btn16 0x6C06EC, or any Buffer whose W is 20, 24 or 48
//     (the palette icons and the button art), as source or destination;
//   - logs a CONTENT SIGNATURE of btn16 at every touch: the number of non-key, non-zero bytes in columns 48..119
//     of rows 0..47 (non-zero there = the buffer already holds ENLARGED art) and a hash of the 48x48 corner;
//   - logs TWO caller frames (return address + the frame above it, read from [ebp+4] of the host) so a stretch
//     from a cave thunk shows which engine or Thinker function invoked that thunk;
//   - keeps the generic census of every other stretch but caps it at 300 lines.
//   COPY3  Buffer_copy_3 (0x5D9610, GDI StretchBlt; thiscall this=src): src/dst W/H (+0x80/+0x84, H negative),
//          rects, return value, callers.   KSB thunk_ksb_v2 (pcave2+0xEDA0) 11 args.   STAPLE
//          thunk_staple_coverage (pcave2+0xE000) 10 args + signature.   BAND thunk_btn_bandstripe (pcave2+0xC800).
// Run: desktop "SMACX Thinker Probe - Icons at Zoom" (render_high_detail at Thinker's default ON): zoom the map
// fully OUT, open a base screen and the scenario editor, quit.

globalThis.LOG_PATH = globalThis.LOG_PATH || "D:/SmacxUi/work/frida_thinker_ksb.log";
log("=== hook_thinker_ksb.js v2 started " + new Date().toISOString() + " ===");

const PCAVE2 = 0xA0C000, PCAVE2_END = 0xA0C000 + 0x40000;   // patches.yaml code_caves.pcave2.virtual_addr
const VA_Buffer_copy_3 = 0x5D9610;
const VA_ksb_v2 = PCAVE2 + 0xEDA0, VA_staple = PCAVE2 + 0xE000, VA_bandstripe = PCAVE2 + 0xC800;
const VA_BTN16 = 0x6C06EC;
const BUF_W = 0x80, BUF_H = 0x84, BUF_DATA = 0x54, BUF_STRIDE = 0x4A8;
const WATCH_W = { 20: 1, 24: 1, 48: 1 };
let thinker = null;
const N = { copy3: 0, copy3Fail: 0, copy3Shrink: 0, ksb: 0, staple: 0, band: 0, watched: 0 };
let logged = 0;
const LIMIT = 300;

function where(p) {
  if (thinker && p.compare(thinker.base) >= 0 && p.compare(thinker.base.add(thinker.size)) < 0) return "thinker.dll+0x" + p.sub(thinker.base).toString(16);
  const v = p.sub(globalThis.TERRANX_BASE).toInt32() + 0x400000;
  if (v >= PCAVE2 && v < PCAVE2_END) return "cave 0x" + v.toString(16);
  return "exe 0x" + v.toString(16);
}
function callers(ctx, ret) {
  // the host's own return address, then the caller's return address read through the host's frame (ebp chain)
  let s = where(ret);
  try {
    const ebp = ctx.ebp;
    const up = ebp.add(4).readPointer();
    if (up.compare(ptr(0x400000)) > 0) s += " < " + where(up);
    const ebp2 = ebp.readPointer();
    const up2 = ebp2.add(4).readPointer();
    if (up2.compare(ptr(0x400000)) > 0) s += " < " + where(up2);
  } catch (e) {}
  return s;
}
function staticVA(p) { const v = p.sub(globalThis.TERRANX_BASE).toInt32() + 0x400000; return (v > 0x400000 && v < 0xC00000) ? v : 0; }
function isBuf(p) {
  try {
    if (p.compare(ptr(0x10000)) < 0) return false;
    const w = p.add(BUF_W).readS32(), h = p.add(BUF_H).readS32();
    return w > 0 && w < 8192 && h !== 0 && Math.abs(h) < 8192;
  } catch (e) { return false; }
}
function bufW(p) { try { return p.add(BUF_W).readS32(); } catch (e) { return -1; } }
function bufStr(p) {
  if (!isBuf(p)) return p + "(not a Buffer)";
  const v = staticVA(p);
  return p + (v ? "(static 0x" + v.toString(16) + ")" : "") + " W=" + p.add(BUF_W).readS32() + " H=" + p.add(BUF_H).readS32() + " stride=" + p.add(BUF_STRIDE).readS32();
}
function watched(p) { return isBuf(p) && (staticVA(p) === VA_BTN16 || WATCH_W[bufW(p)] === 1); }
// btn16 signature: bytes in columns 48..119 of rows 0..47 that are neither 0 nor the key (9), + hash of the corner
function signature(p) {
  try {
    const data = p.add(BUF_DATA).readPointer(), stride = p.add(BUF_STRIDE).readS32();
    if (stride < 48 || stride > 4096) return "sig: stride " + stride + " ?";
    let right = 0, hash = 2166136261 >>> 0, corner = 0;
    for (let y = 0; y < 48; ++y) {
      const row = new Uint8Array(data.add(y * stride).readByteArray(Math.min(stride, 120)));
      for (let x = 0; x < row.length; ++x) {
        if (x < 48) { hash = Math.imul(hash ^ row[x], 16777619) >>> 0; if (row[x] !== 0 && row[x] !== 9) corner++; }
        else if (row[x] !== 0 && row[x] !== 9) right++;
      }
    }
    return "sig: corner48 hash=" + hash.toString(16) + " painted=" + corner + " cols48..119 painted=" + right + (right > 0 ? " (ENLARGED ART PRESENT)" : "");
  } catch (e) { return "sig: unreadable " + e; }
}
function plainEntry(va, name) {
  const p = VA(va);
  const b = Array.from(new Uint8Array(p.readByteArray(4)));
  const ok = b[0] === 0x55 || (b[0] >= 0x50 && b[0] <= 0x57) || (b[0] === 0x83 && b[1] === 0xEC);
  log("  " + name + " @0x" + va.toString(16) + " bytes " + b.map(x => x.toString(16).padStart(2, "0")).join(" ") + (ok ? "" : " -> not a plain prologue, NOT hooked"));
  return ok ? p : null;
}
function say(s, important) {
  if (important) { N.watched++; log(s); return; }
  if (logged++ < LIMIT) log(s);
}

if (requireBase()) {
  thinker = Process.findModuleByName("thinker.dll");
  log("thinker.dll " + (thinker ? thinker.base + " size 0x" + thinker.size.toString(16) : "NOT loaded (control run without Thinker)"));
  const btn16 = VA(VA_BTN16);
  log("btn16 at start: " + bufStr(btn16) + " " + signature(btn16));

  const c3 = plainEntry(VA_Buffer_copy_3, "Buffer_copy_3");
  if (c3) Interceptor.attach(c3, {
    onEnter(args) {
      const src = this.context.ecx, sp = this.context.esp;
      const a = []; for (let i = 1; i <= 9; i++) a.push(sp.add(i * 4).readS32());
      const dst = ptr(a[0] >>> 0);
      this.info = { src: src, dst: dst, rect: a.slice(1), who: callers(this.context, this.returnAddress),
                    imp: watched(src) || watched(dst), sigBefore: (staticVA(src) === VA_BTN16 || staticVA(dst) === VA_BTN16) ? signature(btn16) : null };
      N.copy3++;
      if (a[3] > a[7] || a[4] > a[8]) N.copy3Shrink++;
    },
    onLeave(rv) {
      const i = this.info; if (!i) return;
      const r = rv.toInt32(); if (r !== 0) N.copy3Fail++;
      let line = "COPY3  src " + bufStr(i.src) + " -> dst " + bufStr(i.dst) + " srcRect(" + i.rect.slice(0, 4).join(",") + ") dstRect(" + i.rect.slice(4, 8).join(",") + ") ret=" + r + " from " + i.who;
      if (i.sigBefore) line += "\n       btn16 before: " + i.sigBefore + "\n       btn16 after:  " + signature(btn16);
      say(line, i.imp);
    }
  });

  function argsLine(ctx, n) {
    const sp = ctx.esp; const a = []; for (let i = 1; i <= n; i++) a.push(sp.add(i * 4).readU32());
    const bufs = a.map((v, i) => isBuf(ptr(v)) ? "a" + (i + 1) + "=" + bufStr(ptr(v)) : null).filter(Boolean).join("; ");
    const imp = a.some(v => watched(ptr(v)));
    return { text: a.map(v => "0x" + v.toString(16)).join(" ") + (bufs ? "  [" + bufs + "]" : ""), imp: imp, touchesBtn16: a.some(v => staticVA(ptr(v)) === VA_BTN16) };
  }
  const k = plainEntry(VA_ksb_v2, "thunk_ksb_v2");
  if (k) Interceptor.attach(k, {
    onEnter(args) {
      N.ksb++;
      const a = argsLine(this.context, 11);
      this.imp = a.imp; this.btn = a.touchesBtn16;
      say("KSB    args " + a.text + " from " + callers(this.context, this.returnAddress) + (a.touchesBtn16 ? "\n       btn16 before: " + signature(btn16) : ""), a.imp);
    },
    onLeave(rv) { if (this.btn) log("KSB    ... btn16 after:  " + signature(btn16)); }
  });
  const s = plainEntry(VA_staple, "thunk_staple_coverage");
  if (s) Interceptor.attach(s, {
    onEnter(args) {
      N.staple++;
      const a = argsLine(this.context, 10);
      log("STAPLE args " + a.text + " from " + callers(this.context, this.returnAddress) + "\n       btn16 before: " + signature(btn16));
    },
    onLeave(rv) { log("STAPLE ... btn16 after:  " + signature(btn16)); }
  });
  const bnd = plainEntry(VA_bandstripe, "thunk_btn_bandstripe");
  if (bnd) Interceptor.attach(bnd, {
    onEnter(args) {
      N.band++;
      const a = argsLine(this.context, 11);
      say("BAND   args " + a.text + " from " + callers(this.context, this.returnAddress), a.imp);
    }
  });

  log("installed; zoom the map fully out, open a base screen and the scenario editor, then quit.");
  setInterval(function () {
    log("SUMMARY copy3=" + N.copy3 + " (shrink " + N.copy3Shrink + ", failed " + N.copy3Fail + ") ksb=" + N.ksb + " staple=" + N.staple + " bandstripe=" + N.band + " watched-lines=" + N.watched + (logged >= LIMIT ? " (generic line cap reached)" : "") + "; btn16 now: " + signature(btn16));
  }, 15000);
}
rpc.exports = { summary: function () { log("SUMMARY copy3=" + N.copy3 + " (shrink " + N.copy3Shrink + ", failed " + N.copy3Fail + ") ksb=" + N.ksb + " staple=" + N.staple + " bandstripe=" + N.band + " watched-lines=" + N.watched); } };
