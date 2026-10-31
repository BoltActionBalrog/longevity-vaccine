'use strict';
// Diagnose the transparent BAND between the two title border strokes on the PATCHED binary.
//
// On the patched binary both title 9-slice draws are redirected to thunk_box_thick (cave
// @ 0x668e00). At its entry: ecx = DEST popup buffer (this), [esp]=retaddr (outer 0x40604d /
// inner 0x40607d), [esp+4]=RECT*, [esp+8]=BoxSpriteParams*.
// We read the dest rect, let the thunk run, then sample a VERTICAL strip down the middle of the
// box on the DEST buffer to read the actual palette indices: outer-stroke / band / inner-stroke /
// center / ... — this tells us the band's index vs the center (title-fill) index, and whether the
// band is the transparent key (9).
//
// Buffer struct: +0x54 data ptr, +0x4a8 stride, +0x80 W, +0x84 H.

globalThis.LOG_PATH = "D:/SmacxUi/work/frida_box_thickness.log";
requireBase();

const THUNK_BOX_THICK = 0x668e00;

function readBuf(bufU32) {
  try {
    const buf = ptr("0x" + (bufU32 >>> 0).toString(16));
    let data = buf.add(0x54).readPointer();
    const stride = buf.add(0x4a8).readS32();
    const W = buf.add(0x80).readS32();
    const H = buf.add(0x84).readS32();
    return { data, stride, W, H };
  } catch (e) { log("  buf read err " + e); return null; }
}

// Vertical strip down x=midcol, rows T-3..B+3 : reveals stroke/band/center indices.
function dumpVerticalStrip(bufU32, L, T, R, B) {
  const bi = readBuf(bufU32);
  if (!bi || bi.data.isNull()) { log("  data null"); return; }
  const xs = [L, L + 2, L + 4, L + 6, L + 8, ((L + R) >> 1)];
  log(`  buf data=0x${bi.data.toString(16)} stride=${bi.stride} W=${bi.W} H=${bi.H}`);
  log(`  cols sampled: ${xs.join(",")}   (rows T-3..B+3)`);
  const hist = {};
  for (let y = T - 3; y <= B + 3; y++) {
    const cells = [];
    for (const x of xs) {
      let v = -1; try { v = bi.data.add(y * bi.stride + x).readU8(); } catch (e) {}
      cells.push(v < 0 ? "??" : v.toString(16).padStart(2, "0"));
      if (v >= 0) hist[v] = (hist[v] || 0) + 1;
    }
    log(`   y=${String(y).padStart(4)}: ${cells.join(" ")}`);
  }
  const top = Object.entries(hist).sort((a, b) => b[1] - a[1]).slice(0, 12)
    .map(([k, n]) => `0x${Number(k).toString(16)}:${n}`).join("  ");
  log(`  -- index histogram: ${top}`);
}

const seen = {};
Interceptor.attach(VA(THUNK_BOX_THICK), {
  onEnter() {
    const sp = this.context.esp;
    const ret = arg(sp, 0) >>> 0;          // [esp] = original return addr
    let tag = null;
    if (ret === 0x40604d) tag = "OUTER d5a0";
    else if (ret === 0x40607d) tag = "INNER d618";
    else tag = "ret0x" + ret.toString(16);
    if (seen[tag]) { this.skip = true; return; }
    seen[tag] = true;
    const rectp = ptr("0x" + (arg(sp, 1) >>> 0).toString(16));
    let L = 0, T = 0, R = 0, Bv = 0;
    try { L = rectp.readS32(); T = rectp.add(4).readS32(); R = rectp.add(8).readS32(); Bv = rectp.add(0xc).readS32(); } catch (e) {}
    log(`\n===== ${tag}  (ret 0x${ret.toString(16)}) =====`);
    log(`  dest rect = [L=${L} T=${T} R=${R} B=${Bv}]  -> w=${R - L} h=${Bv - T}`);
    log(`  dest buf = 0x${this.context.ecx.toString(16)}`);
    this.buf = this.context.ecx; this.L = L; this.T = T; this.R = R; this.B = Bv;
  },
  onLeave() {
    if (this.skip || this.buf === undefined) return;
    dumpVerticalStrip(u32(this.buf), this.L, this.T, this.R, this.B);
    this.buf = undefined;
  }
});

log('[hook_box_thickness] armed on thunk_box_thick @ 0x668e00 — %resume, open Customize Game Rules, then quit.');
