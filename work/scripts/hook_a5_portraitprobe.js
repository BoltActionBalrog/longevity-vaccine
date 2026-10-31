'use strict';
// =====================================================================================
// A5 PROBE — enumerate EVERY Sprite_draw_2 call into the faction box (dest==0x940824),
// to find which call the function-REPLACING thunk mishandles (-> crash).
//
// WHY: the validated fix was an onLeave post-processor. If a NON-portrait call also hits
// dest==0x940824 && num>den but has odd/garbage source dims (or a source ptr that isn't a
// full w*h plane), the prototype's readByteArray() throws a CATCHABLE JS exception -> Frida
// swallows it, the process lives, and the native draw already rendered it. The native thunk
// doing the SAME out-of-bounds read takes a hard AV -> crash. The prototype only LOGGED the
// 131x157 portrait but PROCESSED every matching call silently.
//
// This run is OBSERVATIONAL: the detour is skipped (build 9c28dfee, non-crashing). We log
// every dest==0x940824 Sprite_draw_2 with the exact fields the thunk reads, validate the
// source is a real readable w*h plane, and project the thunk's max source-read and dest-write
// offsets to flag anything that would AV.
//
// Run on the PATCHED build at 1600x1200 (defect) AND 4K. Navigate:
//   %resume -> Choose Your Factions -> SELECT a faction -> quit.
// =====================================================================================

globalThis.LOG_PATH = "D:/SmacxUi/work/frida_a5_portraitprobe.log";
log("=== hook_a5_portraitprobe.js started ===");

const SPR_DRAW2 = 0x005E4B4A; // thiscall: ecx=Sprite*, [+4]dest,[+8]key,[+c]x,[+10]y,[+14]num,[+18]den
const BOXBUF    = 0x00940824; // faction box dest Buffer

function pp(v){ return ptr("0x" + (v>>>0).toString(16)); }

// Read a candidate plane and report whether it's readable + how many distinct byte values it
// holds in the first N bytes (a real pixel plane shows many; garbage/unmapped throws).
function planeProbe(dataPtr, nbytes){
  try {
    const n = Math.min(nbytes>>>0, 4096);
    const b = new Uint8Array(dataPtr.readByteArray(n));
    const seen = {}; let distinct = 0;
    for (let i=0;i<b.length;i++){ if(!seen[b[i]]){ seen[b[i]]=1; distinct++; } }
    return { ok:true, distinct, n };
  } catch(e){ return { ok:false, err:String(e) }; }
}

function destPlane(bufU32){
  try { const b = pp(bufU32);
    let h = b.add(0x84).readS32(); const flip = h<0; if (flip) h=-h;
    return { data: b.add(0x54).readPointer(), stride: b.add(0x4a8).readS32(),
             w: b.add(0x80).readS32(), h, flip };
  } catch(e){ return null; }
}

const seenCalls = new Map();   // dedup key -> count
let total = 0, distinctTuples = 0;

if (requireBase()) {
  Interceptor.attach(VA(SPR_DRAW2), {
    onEnter(){
      const sp = this.context.esp;
      const dest = arg(sp,1)>>>0;
      if (dest !== (BOXBUF>>>0)) return;            // only the faction box
      total++;
      const ecx = this.context.ecx.toUInt32()>>>0;
      const key = argS(sp,2), x = argS(sp,3), y = argS(sp,4);
      const num = argS(sp,5), den = argS(sp,6);

      // source Sprite fields the thunk reads
      let sw=0, sh=0, sstride=0, sdata=0, sfields="?";
      try { const b = pp(ecx);
        sw = b.add(0x18).readS32(); sh = b.add(0x1c).readS32();
        sstride = b.add(0x10).readS32(); sdata = b.add(0x4).readPointer().toUInt32()>>>0;
        sfields = `w=${sw} h=${sh} stride=${sstride} data=0x${sdata.toString(16)}`;
      } catch(e){ sfields = "READ-FAIL "+e; }

      const dedup = `ecx=${ecx.toString(16)}|${sw}x${sh}|st${sstride}|${num}/${den}|@${x},${y}|k${key}`;
      const prev = seenCalls.get(dedup);
      if (prev !== undefined){ seenCalls.set(dedup, prev+1); return; }  // already reported this distinct tuple
      seenCalls.set(dedup, 1);
      distinctTuples++;

      const wouldFire = (num > den && den > 0 && sw>0 && sh>0 && sdata!==0);
      const effStride = (sstride>0) ? sstride : sw;       // thunk's sstride fallback
      const dest_g = destPlane(dest);

      log("");
      log(`[#${distinctTuples}] Sprite_draw_2 -> faction box  ${sfields}  key=${key} x=${x} y=${y} ${num}/${den}  thunkFires=${wouldFire}`);
      if (dest_g) log(`     dest: data=0x${dest_g.data.toUInt32().toString(16)} stride=${dest_g.stride} w=${dest_g.w} h=${dest_g.h} flip=${dest_g.flip}`);

      if (wouldFire){
        // The thunk reads source up to index (sh-1)*effStride + (sw-1). Probe that the source
        // plane is actually readable across its FULL extent (this is the read the native thunk
        // does that the Frida prototype could swallow as a JS exception).
        const needBytes = (sh-1)*effStride + sw;       // last byte the bilinear can touch +1
        const headProbe = planeProbe(pp(sdata), 4096);
        let tailOk=false, tailErr="";
        try { pp(sdata).add(needBytes-1).readU8(); tailOk=true; }
        catch(e){ tailErr = String(e); }
        log(`     SRC plane: head4k=${headProbe.ok?`OK distinct=${headProbe.distinct}`:`UNREADABLE ${headProbe.err}`}  fullExtent=${needBytes}B tail=${tailOk?"OK":("UNREADABLE "+tailErr)}`);
        if (!tailOk) log(`     *** CRASH CANDIDATE: thunk would read source byte +${needBytes-1} which is UNMAPPED -> native AV ***`);

        // Project the thunk's dest write extent and compare to dest.w/h bounds.
        if (dest_g){
          const dw = Math.trunc(sw*num/den), dh = Math.trunc(sh*num/den);
          const maxRow = y + dh - 1, maxCol = x + dw - 1;
          const rowOOB = (maxRow >= dest_g.h), colOOB = (maxCol >= dest_g.w);
          log(`     dest write: dw=${dw} dh=${dh} -> maxRow=${maxRow}/${dest_g.h} maxCol=${maxCol}/${dest_g.w}  rowOOB=${rowOOB} colOOB=${colOOB}`);
          // thunk bounds-checks row<dest.h and col<dest.w per-pixel, so OOB here is clamped (not a crash)
          // but a NEGATIVE dest.h (positive +0x84) means the thunk no-ops -> note it.
          if (dest_g.flip === false) log(`     NOTE: dest +0x84 is POSITIVE -> thunk's neg() yields negative height -> all rows skipped (no-op, not crash)`);
        }
      }
    }
  });
  log("probe installed. Choose Your Factions -> SELECT a faction -> quit. Then read frida_a5_portraitprobe.log");
}
