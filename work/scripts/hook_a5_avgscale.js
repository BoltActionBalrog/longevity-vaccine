// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

'use strict';
// =====================================================================================
// A5 SOLUTION-A PROTOTYPE (validation, no binary patching): averaging upscale in the SHARED
// frame funnel, computed in JS, written over the dest -- so we can SEE in-game whether replacing
// the NN StretchBlt with a palette-aware bilinear (averaging) resample resolves the green/black
// dither cleanly. If it does, productionize as a real thunk on thunk_frame_enlarge.
//
// ROOT (confirmed by the 4 attribution logs): d690/d528/d5a0 all funnel through thunk_frame_enlarge
// (0xA0C2A0) -> StretchBlt(SRCCOPY) = nearest-neighbour, index-preserving. The frame art is a 50/50
// green(65)/black(198) dither; NN upscale x1.5625 (g25) aliases it dark on R/B. Averaging (bilinear)
// blends adjacent 65/198 texels -> the intended mid green, NN-stable -> clean at ANY scale.
//
// HOW: hook thunk_frame_enlarge. onEnter capture (src=g_frame_buf, dest, key, X, Y, num, den) for the
// FACTION box (0x940824) at g>16. onLeave: bilinear-upscale src into dest, writing ONLY where the
// NEAREST source texel is non-key (identical coverage to NN -> hollow interior / transparency intact),
// using non-key neighbours for the blended colour. Per-anchor cache -> recompute once, replay cheaply.
//
// PALETTE: index->RGB from the live GDI HPALETTE at *0x9B8178 via GetPaletteEntries (PALETTEENTRY[256],
// index i == buffer index i). Nearest-index done in JS over that LUT (cached).
//
// PATCHED build only (hooks our pcave2 thunk). Run via the shortcut at 1600x1200 (defect) AND 4K
// (regression check). The faction frames should read clean green on all edges at both.
// Navigate: %resume -> Choose Your Factions -> SELECT a faction -> quit.
// =====================================================================================

globalThis.LOG_PATH = globalThis.LOG_PATH || "D:/SmacxUi/work/frida_a5_avgscale.log";
requireBase();

const ENLARGE = 0x00A0C2A0;   // thunk_frame_enlarge funnel (src=ecx=g_frame_buf; [esp+4]=dest,+8 key,+c X,+10 Y,+14 num,+18 den)
const BOXBUF  = 0x00940824;   // faction box buffer
const HPAL_PP = 0x009B8178;   // HPALETTE* (GDI realized game palette) -- often the MENU palette, stale for faction screen
const SET_ACTIVE = 0x005FE4F0;// Palette_set_active_window(Palette* This)  cdecl, arg1 = active engine Palette*
const SYNC_PAL   = 0x005DE8F0;// Buffer_sync_to_palette(Buffer*, Palette*)  thiscall, [esp+4] = Palette*
// struct Palette { PALETTEENTRY colors[256]; ... } -> colors at offset 0; PALETTEENTRY = {r,g,b,flags} 4 bytes.

// ---- capture the LIVE engine palette (the faction screen swaps to the leader's palette) ----
let g_palObj = null;
// Validate a candidate engine Palette*: anchor on index 198 = near-black (matched both palettes), and
// require colour variety (not all-zero / not uniform garbage). Rejects bogus stack pointers.
function looksLikePalette(pU32){ try { const b = new Uint8Array(pp(pU32).readByteArray(256*4));
  const r198=b[198*4], g198=b[198*4+1], b198=b[198*4+2];
  if (!(r198<60 && g198<60 && b198<60)) return false;          // 198 must be dark
  let distinct=0; const seen={}; for (let i=0;i<256;i++){ const k=(b[i*4]<<16)|(b[i*4+1]<<8)|b[i*4+2]; if(!seen[k]){seen[k]=1;distinct++;} }
  return distinct >= 32;                                         // a real 256-palette has many distinct colours
} catch(e){ return false; } }
function safeAttach(addr, label, cbs){ try { Interceptor.attach(VA(addr), cbs); log(`[attach] ${label} @0x${addr.toString(16)} OK`); return true; }
  catch(e){ log(`[attach] ${label} @0x${addr.toString(16)} FAILED: ${e}`); return false; } }
safeAttach(SET_ACTIVE, "Palette_set_active_window", { onEnter(){ const c = arg(this.context.esp,1)>>>0; if (c && looksLikePalette(c)) g_palObj = c; } });
safeAttach(SYNC_PAL,   "Buffer_sync_to_palette",    { onEnter(){ const c = arg(this.context.esp,1)>>>0; if (c && looksLikePalette(c)) g_palObj = c; } });

// Fallback: scan the faction box Buffer object for a dword that points at a valid engine Palette
// (the Buffer has a `Palette* pPalette` field at an offset thinker mis-states, so we locate it by validation).
function findPaletteInBuffer(bufU32){ try { const b = pp(bufU32);
  for (let off=0; off<=0x600; off+=4){ let cand; try { cand = b.add(off).readU32()>>>0; } catch(e){ continue; }
    if (cand > 0x10000 && looksLikePalette(cand)){ log(`[pal] found Palette* in faction buffer at +0x${off.toString(16)} -> 0x${cand.toString(16)}`); return cand; } }
  return null; } catch(e){ return null; } }

function pp(v){ return ptr("0x" + (v>>>0).toString(16)); }
function plane(bufU32){ try { const b = pp(bufU32);
  let h = b.add(0x84).readS32(); const flip = h<0; if (flip) h = -h;
  return { base:b, data:b.add(0x54).readPointer(), stride:b.add(0x4a8).readS32(), w:b.add(0x80).readS32(), h, flip };
} catch(e){ return null; } }

// resolve a DLL export across Frida API variants (Frida 17 removed the static Module.getExportByName).
function resolveExport(dll, name){
  try { const m = Process.getModuleByName(dll); if (m){ if (m.getExportByName) return m.getExportByName(name);
        if (m.findExportByName){ const a=m.findExportByName(name); if (a) return a; } } } catch(e){}
  try { const m = Process.findModuleByName(dll); if (m && m.findExportByName){ const a=m.findExportByName(name); if (a) return a; } } catch(e){}
  try { if (Module.getGlobalExportByName) return Module.getGlobalExportByName(name); } catch(e){}
  try { if (typeof Module.getExportByName === 'function') return Module.getExportByName(dll, name); } catch(e){}
  return null;
}

// read 256 RGB entries from an engine Palette* (colors[256] PALETTEENTRY at offset 0)
function lutFromEngine(palU32){ try { const bytes = new Uint8Array(pp(palU32).readByteArray(256*4));
  const L = new Array(256); for (let i=0;i<256;i++){ L[i] = { r:bytes[i*4], g:bytes[i*4+1], b:bytes[i*4+2] }; } return L;
} catch(e){ return null; } }
// read 256 RGB entries from the GDI HPALETTE
function lutFromGDI(){ try { const hpal = VA(HPAL_PP).readPointer(); if (hpal.isNull()) return null;
  const gpe = resolveExport('gdi32.dll','GetPaletteEntries'); if (!gpe) return null;
  const GetPaletteEntries = new NativeFunction(gpe, 'uint', ['pointer','uint','uint','pointer'], 'stdcall');
  const buf = Memory.alloc(256*4); const n = GetPaletteEntries(hpal, 0, 256, buf); if (!n) return null;
  const bytes = new Uint8Array(buf.readByteArray(256*4)); const L = new Array(256);
  for (let i=0;i<256;i++){ L[i] = { r:bytes[i*4], g:bytes[i*4+1], b:bytes[i*4+2] }; } return L;
} catch(e){ return null; } }

// ---- palette LUT (index -> {r,g,b}). PREFER the live engine palette; GDI is fallback. Rebuild until
//      the engine palette is captured (Palette_set_active_window may fire after the first enlarge). ----
let LUT = null, LUT_locked = false, LUT_logged = false, LUT_source = null, lutGen = 0;
function setLUT(L, source){ if (LUT_source !== source){ LUT = L; LUT_source = source; lutGen++; nearestCache.clear();
    log(`[pal] LUT source -> ${source} (gen ${lutGen}); caches cleared.`); } else { LUT = L; } }
function buildLUT(){
  if (!g_palObj){ const p = findPaletteInBuffer(BOXBUF); if (p) g_palObj = p; }   // fallback if the hooks didn't capture
  const eng = g_palObj ? lutFromEngine(g_palObj) : null;
  const gdi = LUT_logged ? null : lutFromGDI();   // only need GDI for the one-time comparison
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

// nearest palette index for an (r,g,b), cached by packed colour key
const nearestCache = new Map();
function nearestIdx(r,g,b){
  const key = (r<<16)|(g<<8)|b;
  const hit = nearestCache.get(key); if (hit !== undefined) return hit;
  let best=0, bd=1e9;
  for (let i=0;i<256;i++){ const c=LUT[i]; const dr=c.r-r, dg=c.g-g, db=c.b-b; const d=dr*dr+dg*dg+db*db;
    if (d<bd){ bd=d; best=i; if (d===0) break; } }
  nearestCache.set(key, best); return best;
}

// per-anchor cache of computed writes: key -> { dataInt, pairs:[off,val,...] }
const writeCache = new Map();
let processed = 0, replayed = 0; const KEY9 = 9;

function averageUpscale(src, dest, key, X, Y, num, den){
  const cacheKey = `${X},${Y},${num},${den},${src.w}x${src.h}`;
  const destDataInt = dest.data.toUInt32()>>>0;
  let rec = writeCache.get(cacheKey);
  if (rec && rec.dataInt === destDataInt && rec.gen === lutGen){
    // replay
    const p = rec.pairs; for (let i=0;i<p.length;i+=2){ try { dest.data.add(p[i]).writeU8(p[i+1]); } catch(e){} }
    replayed++; return;
  }
  // read the whole src plane once (fast)
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
    const yn = (sy-y0<0.5)?y0:y1;                       // nearest src row
    for (let dxi=0; dxi<dw; dxi++){
      const dx = X+dxi; if (dx<0||dx>=dW) continue;
      const sx = dxi*sc; const x0 = Math.floor(sx); const x1 = Math.min(x0+1, sw-1); const fx = sx-x0;
      const xn = (sx-x0<0.5)?x0:x1;                     // nearest src col
      if (at(xn,yn) === KEY9) continue;                 // NN coverage: transparent -> leave backdrop
      // bilinear blend over the 4 neighbours, excluding key texels
      const s00=at(x0,y0), s10=at(x1,y0), s01=at(x0,y1), s11=at(x1,y1);
      const w00=(1-fx)*(1-fy), w10=fx*(1-fy), w01=(1-fx)*fy, w11=fx*fy;
      let r=0,g=0,b=0,wt=0;
      if (s00!==KEY9){ const c=LUT[s00]; r+=c.r*w00; g+=c.g*w00; b+=c.b*w00; wt+=w00; }
      if (s10!==KEY9){ const c=LUT[s10]; r+=c.r*w10; g+=c.g*w10; b+=c.b*w10; wt+=w10; }
      if (s01!==KEY9){ const c=LUT[s01]; r+=c.r*w01; g+=c.g*w01; b+=c.b*w01; wt+=w01; }
      if (s11!==KEY9){ const c=LUT[s11]; r+=c.r*w11; g+=c.g*w11; b+=c.b*w11; wt+=w11; }
      if (wt<=0) continue;
      const idx = nearestIdx(Math.round(r/wt), Math.round(g/wt), Math.round(b/wt));
      const off = dx + dy*dStride;
      pairs.push(off, idx);
      try { dest.data.add(off).writeU8(idx); } catch(e){}
    }
  }
  writeCache.set(cacheKey, { dataInt: destDataInt, pairs, gen: lutGen });
  processed++;
  log(`[avg] anchor X=${X} Y=${Y} ${num}/${den} src ${sw}x${sh} -> dest ${dw}x${dh}, wrote ${pairs.length/2} px`);
}

safeAttach(ENLARGE, "thunk_frame_enlarge", {
  onEnter(){ const sp=this.context.esp; const dest=arg(sp,1)>>>0;
    this.go = (dest === (BOXBUF>>>0));
    if (!this.go) return;
    this.key=arg(sp,2)|0; this.X=arg(sp,3)|0; this.Y=arg(sp,4)|0; this.num=arg(sp,5)|0; this.den=arg(sp,6)|0;
    this.src=this.context.ecx.toUInt32()>>>0;
    if (this.num <= this.den) this.go = false;          // g<=16 native no-op
  },
  onLeave(){ if (!this.go) return;
    if (!LUT_locked) buildLUT();                        // keep retrying until the ENGINE palette is captured
    if (!LUT) return;
    const src=plane(this.src), dest=plane(BOXBUF);
    if (!src||!dest||src.data.isNull()||dest.data.isNull()||src.stride<=0||dest.stride<=0) return;
    averageUpscale(src, dest, this.key, this.X, this.Y, this.num, this.den);
  }
});

log("hook_a5_avgscale (Solution-A PROTOTYPE) installed. PATCHED build only.");
log("  Choose Your Factions -> SELECT a faction -> quit. Expect clean green frames on ALL edges at g25 AND g40.");
log("  (first faction draw recomputes; later redraws replay from cache.)");
