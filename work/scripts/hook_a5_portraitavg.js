// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

'use strict';
// =====================================================================================
// A5 SOLUTION-A, AIMED AT THE CONFIRMED PORTRAIT PATH (validation, no patching).
//
// Census + struct dump (2026-06-16) confirmed LIVE: the leader portrait is drawn by Sprite_draw_2
// (0x5E4B4A), THISCALL: ecx=Sprite*, stack = dest, key, x, y, num, den. For the faction popup:
//   dest = 0x940824 (faction box), key=9, x=10, y=12, scale = 25/16 (g25, fractional).
//   Sprite struct: data=[ecx+0x4], stride=[ecx+0x10]=131, width=[ecx+0x18]=131, height=[ecx+0x1c]=157.
// The engine NN-scales this 131x157 source x(num/den); at fractional g25 the ~1px green edge (idx
// 31/34) drops/thins on R/B -> the dark backdrop shows = the A5 defect.
//
// FIX (averaging, re-aimed): on onLeave (after the engine NN draw) recompute the placed region with a
// palette-aware bilinear average of the SOURCE sprite, writing only where the nearest source texel is
// non-key (identical silhouette/transparency). The thin green edge then BLENDS into the output instead
// of being dropped. Reusable for any scaled sprite.
//
// PATCHED build. Run via shortcut at 1600x1200 (defect) AND 4K (regression). Navigate:
// %resume -> Choose Your Factions -> SELECT a faction -> quit.
// =====================================================================================

globalThis.LOG_PATH = globalThis.LOG_PATH || "D:/SmacxUi/work/frida_a5_portraitavg.log";
requireBase();

const SPR_DRAW2 = 0x005E4B4A; // thiscall: ecx=Sprite*, [+4]dest, [+8]key, [+c]x, [+10]y, [+14]num, [+18]den
const BOXBUF    = 0x00940824; // faction box
const HPAL_PP   = 0x009B8178;
const SET_ACTIVE= 0x005FE4F0;
const SYNC_PAL  = 0x005DE8F0;

function pp(v){ return ptr("0x" + (v>>>0).toString(16)); }
let g_palObj = null;
function looksLikePalette(pU32){ try { const b = new Uint8Array(pp(pU32).readByteArray(256*4));
  const r198=b[198*4], g198=b[198*4+1], b198=b[198*4+2];
  if (!(r198<60 && g198<60 && b198<60)) return false;
  let distinct=0; const seen={}; for (let i=0;i<256;i++){ const k=(b[i*4]<<16)|(b[i*4+1]<<8)|b[i*4+2]; if(!seen[k]){seen[k]=1;distinct++;} }
  return distinct >= 32;
} catch(e){ return false; } }
function safeAttach(addr, label, cbs){ try { Interceptor.attach(VA(addr), cbs); log(`[attach] ${label} @0x${addr.toString(16)} OK`); return true; }
  catch(e){ log(`[attach] ${label} @0x${addr.toString(16)} FAILED: ${e}`); return false; } }
safeAttach(SET_ACTIVE, "Palette_set_active_window", { onEnter(){ const c = arg(this.context.esp,1)>>>0; if (c && looksLikePalette(c)) g_palObj = c; } });
safeAttach(SYNC_PAL,   "Buffer_sync_to_palette",    { onEnter(){ const c = arg(this.context.esp,1)>>>0; if (c && looksLikePalette(c)) g_palObj = c; } });

function findPaletteInBuffer(bufU32){ try { const b = pp(bufU32);
  for (let off=0; off<=0x600; off+=4){ let cand; try { cand = b.add(off).readU32()>>>0; } catch(e){ continue; }
    if (cand > 0x10000 && looksLikePalette(cand)){ log(`[pal] found Palette* in buffer at +0x${off.toString(16)} -> 0x${cand.toString(16)}`); return cand; } }
  return null; } catch(e){ return null; } }

// dest is a Buffer (data@+0x54, w@+0x80, h@+0x84 neg=top-down, stride@+0x4a8)
function destPlane(bufU32){ try { const b = pp(bufU32);
  let h = b.add(0x84).readS32(); const flip = h<0; if (flip) h = -h;
  return { data: b.add(0x54).readPointer(), stride: b.add(0x4a8).readS32(), w: b.add(0x80).readS32(), h, flip };
} catch(e){ return null; } }
// src is a Sprite (data@+0x4, stride@+0x10, w@+0x18, h@+0x1c) -- tightly packed 8-bit
function spritePlane(ecxU32){ try { const b = pp(ecxU32);
  const w = b.add(0x18).readS32(), h = b.add(0x1c).readS32(); let stride = b.add(0x10).readS32();
  if (stride <= 0) stride = w;
  return { data: b.add(0x4).readPointer(), stride, w, h };
} catch(e){ return null; } }

function lutFromEngine(palU32){ try { const bytes = new Uint8Array(pp(palU32).readByteArray(256*4));
  const L = new Array(256); for (let i=0;i<256;i++){ L[i] = { r:bytes[i*4], g:bytes[i*4+1], b:bytes[i*4+2] }; } return L;
} catch(e){ return null; } }
function resolveExport(dll, name){
  try { const m = Process.getModuleByName(dll); if (m){ if (m.getExportByName) return m.getExportByName(name);
        if (m.findExportByName){ const a=m.findExportByName(name); if (a) return a; } } } catch(e){}
  try { const m = Process.findModuleByName(dll); if (m && m.findExportByName){ const a=m.findExportByName(name); if (a) return a; } } catch(e){}
  try { if (Module.getGlobalExportByName) return Module.getGlobalExportByName(name); } catch(e){}
  try { if (typeof Module.getExportByName === 'function') return Module.getExportByName(dll, name); } catch(e){}
  return null;
}
function lutFromGDI(){ try { const hpal = VA(HPAL_PP).readPointer(); if (hpal.isNull()) return null;
  const gpe = resolveExport('gdi32.dll','GetPaletteEntries'); if (!gpe) return null;
  const GetPaletteEntries = new NativeFunction(gpe, 'uint', ['pointer','uint','uint','pointer'], 'stdcall');
  const buf = Memory.alloc(256*4); const n = GetPaletteEntries(hpal, 0, 256, buf); if (!n) return null;
  const bytes = new Uint8Array(buf.readByteArray(256*4)); const L = new Array(256);
  for (let i=0;i<256;i++){ L[i] = { r:bytes[i*4], g:bytes[i*4+1], b:bytes[i*4+2] }; } return L;
} catch(e){ return null; } }

let LUT = null, LUT_locked = false, LUT_logged = false, LUT_source = null, lutGen = 0;
function setLUT(L, source){ if (LUT_source !== source){ LUT = L; LUT_source = source; lutGen++; nearestCache.clear();
    log(`[pal] LUT source -> ${source} (gen ${lutGen}); caches cleared.`); } else { LUT = L; } }
function buildLUT(){
  if (!g_palObj){ const p = findPaletteInBuffer(BOXBUF); if (p) g_palObj = p; }
  const eng = g_palObj ? lutFromEngine(g_palObj) : null;
  const gdi = LUT_logged ? null : lutFromGDI();
  if (!LUT_logged && (eng || gdi)){
    const s = (L,i)=> L ? `${i}=(${L[i].r},${L[i].g},${L[i].b})` : `${i}=?`;
    const idxs = [65,198,34,196,31,9];
    log(`[pal] ENGINE(0x${(g_palObj||0).toString(16)}): ${idxs.map(i=>s(eng,i)).join(" ")}`);
    log(`[pal] GDI(0x9b8178)  : ${idxs.map(i=>s(gdi,i)).join(" ")}`);
    LUT_logged = true;
  }
  if (eng){ setLUT(eng, 'engine'); LUT_locked = true; return true; }
  if (!LUT){ const g = gdi || lutFromGDI(); if (g){ setLUT(g, 'gdi'); return true; } }
  return LUT !== null;
}

const nearestCache = new Map();
function nearestIdx(r,g,b){
  const key = (r<<16)|(g<<8)|b;
  const hit = nearestCache.get(key); if (hit !== undefined) return hit;
  let best=0, bd=1e9;
  for (let i=0;i<256;i++){ const c=LUT[i]; const dr=c.r-r, dg=c.g-g, db=c.b-b; const d=dr*dr+dg*dg+db*db;
    if (d<bd){ bd=d; best=i; if (d===0) break; } }
  nearestCache.set(key, best); return best;
}

const writeCache = new Map();
let processed = 0, replayed = 0;

function averageUpscale(src, dest, KEY, X, Y, num, den){
  const destDataInt = dest.data.toUInt32()>>>0;
  const cacheKey = `${X},${Y},${num},${den},${src.w}x${src.h}->${destDataInt}`;
  let rec = writeCache.get(cacheKey);
  if (rec && rec.dataInt === destDataInt && rec.gen === lutGen){
    const p = rec.pairs; for (let i=0;i<p.length;i+=2){ try { dest.data.add(p[i]).writeU8(p[i+1]); } catch(e){} }
    replayed++; return;
  }
  const sStride = src.stride>>>0, sw = src.w, sh = src.h;
  const sbytes = new Uint8Array(src.data.readByteArray(sStride*sh));
  const at = (x,y)=> sbytes[x + y*sStride];
  const dw = Math.round(sw*num/den), dh = Math.round(sh*num/den);
  const dStride = dest.stride>>>0, dW = dest.w, dH = dest.h;
  const pairs = [];
  const sc = den/num;
  for (let dyi=0; dyi<dh; dyi++){
    const dy = Y+dyi; if (dy<0||dy>=dH) continue;
    const sy = dyi*sc; const y0 = Math.floor(sy); const y1 = Math.min(y0+1, sh-1); const fy = sy-y0;
    const yn = (sy-y0<0.5)?y0:y1;
    for (let dxi=0; dxi<dw; dxi++){
      const dx = X+dxi; if (dx<0||dx>=dW) continue;
      const sx = dxi*sc; const x0 = Math.floor(sx); const x1 = Math.min(x0+1, sw-1); const fx = sx-x0;
      const xn = (sx-x0<0.5)?x0:x1;
      if (at(xn,yn) === KEY) continue;
      const s00=at(x0,y0), s10=at(x1,y0), s01=at(x0,y1), s11=at(x1,y1);
      const w00=(1-fx)*(1-fy), w10=fx*(1-fy), w01=(1-fx)*fy, w11=fx*fy;
      let r=0,g=0,b=0,wt=0;
      if (s00!==KEY){ const c=LUT[s00]; r+=c.r*w00; g+=c.g*w00; b+=c.b*w00; wt+=w00; }
      if (s10!==KEY){ const c=LUT[s10]; r+=c.r*w10; g+=c.g*w10; b+=c.b*w10; wt+=w10; }
      if (s01!==KEY){ const c=LUT[s01]; r+=c.r*w01; g+=c.g*w01; b+=c.b*w01; wt+=w01; }
      if (s11!==KEY){ const c=LUT[s11]; r+=c.r*w11; g+=c.g*w11; b+=c.b*w11; wt+=w11; }
      if (wt<=0) continue;
      const idx = nearestIdx(Math.round(r/wt), Math.round(g/wt), Math.round(b/wt));
      const off = dx + dy*dStride;
      pairs.push(off, idx);
      try { dest.data.add(off).writeU8(idx); } catch(e){}
    }
  }
  writeCache.set(cacheKey, { dataInt: destDataInt, pairs, gen: lutGen });
  processed++;
  log(`[avg] portrait X=${X} Y=${Y} ${num}/${den} src ${sw}x${sh} stride=${sStride} -> dest ${dw}x${dh}, wrote ${pairs.length/2} px`);
}

let firstSeen = false;
safeAttach(SPR_DRAW2, "Sprite_draw_2", {
  onEnter(){
    const sp = this.context.esp;
    const dest = arg(sp,1)>>>0, key = arg(sp,2)|0, x = arg(sp,3)|0, y = arg(sp,4)|0, num = arg(sp,5)|0, den = arg(sp,6)|0;
    this.go = (dest === (BOXBUF>>>0) && num > den && den > 0);
    if (!this.go) return;
    this.ecx = this.context.ecx.toUInt32()>>>0;
    this.dest = dest; this.key = key; this.x = x; this.y = y; this.num = num; this.den = den;
    if (!firstSeen){ firstSeen = true; const s = spritePlane(this.ecx);
      log(`[seen] portrait Sprite@0x${this.ecx.toString(16)} ${s?`${s.w}x${s.h} stride=${s.stride} data=0x${s.data.toUInt32().toString(16)}`:'?'} key=${key} x=${x} y=${y} ${num}/${den}`); }
  },
  onLeave(){
    if (!this.go) return;
    if (!LUT_locked) buildLUT();
    if (!LUT) return;
    const src = spritePlane(this.ecx), dest = destPlane(this.dest);
    if (!src||!dest||src.data.isNull()||dest.data.isNull()||src.stride<=0||dest.stride<=0||src.w<=0||src.h<=0) return;
    averageUpscale(src, dest, this.key, this.x, this.y, this.num, this.den);
  }
});

log("hook_a5_portraitavg (Solution-A on the CONFIRMED portrait path) installed. PATCHED build only.");
log("  Choose Your Factions -> SELECT a faction -> quit. Expect a clean green hug on ALL portrait edges at g25 AND g40.");
