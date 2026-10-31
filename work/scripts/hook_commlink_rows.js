// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// ===========================================================================
// hook_commlink_rows.js -- COMMLINK per-faction ROW text + Spot hit-rects.
// Runs on the BAKED exe (commlink_menu_scale group is live: box/strips/Council/
// VOTES already scaled). This trace (a) OBSERVES the whole row chain and
// (b) PROTOTYPES the fix behind LEVER flags. Nothing here touches what the
// bake already scales; every lever is gated on a NATIVE-valued input, so it
// is idempotent across the hover-repaint storm.
//   [row]     commlink_draw_faction_row entry: faction/row#/native rect
//   [setfont] Buffer_set_font post-thunk (0x5DAC80): the font that will land
//             in MW_BUF+0x52C (was thunk_comm_setfont's hm_scalefont applied?)
//   [wl4]/[wr6] Buffer_write_l_4 / write_right_l_6 with dest==MW_BUF: rect
//             + font slot BEFORE/AFTER the lever
//   [spot+]   Spot_add on the COMMLINK spot list (obj+0x28AC): native args
//   [spot?]   Spot_check on that list: input (x,y) + result -> proves the
//             coordinate space the mouse arrives in
//   [mm]      commlink_on_mouse_move args
// ===========================================================================
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_commlink_rows.log";
log("=== hook_commlink_rows.js ===");
installAVHandler("commlink_rows");

const LEVER_RECT  = true;   // rewrite the row text rect (write_l_4/write_right_l_6)
const LEVER_SPOT  = true;   // scale Spot_add x/y/w/h for the COMMLINK list
const LEVER_FONT  = true;   // if the baked setfont thunk left the row font native, scale it here

if (requireBase()) {
  const COMM_WIN = 0x7FD648, MW_BUF = 0x7FDA8C, SPOTS = COMM_WIN + 0x28AC, ROW_FONT = COMM_WIN + 0x285C;
  const FONT_TABLE = 0x93FC58, FONT_SIZE_TABLE=[40,36,32,24,22,20,18,16,14,12,10,8];
  const g_scale = VA(0x00668740);
  const find_font = new NativeFunction(VA(0x005882F0), 'pointer', ['int','int']);
  const rd=(p,o)=>{try{return ptr(p).add(o).readS32();}catch(e){return null;}};
  const wr=(p,o,v)=>ptr(p).add(o).writeS32(v);
  function ps(){try{return g_scale.readU32();}catch(e){return 16;}}
  const sc=(v,s)=>(v*s+8)>>4;
  function rowY(y,s){ if (y<6) return sc(y,s); const k=Math.floor((y-6)/18), r=(y-6)%18; return sc(6,s)+k*sc(18,s)+sc(r,s); }
  const clampSz=(v)=>Math.max(8,Math.min(40,v));
  function decodeFont(p){
    if (!p) return "0";
    const off=(p>>>0)-FONT_TABLE;
    if (off<0 || off>=12*0xA0) return "0x"+(p>>>0).toString(16)+"(off-table cell+0xC="+rd(p,0x0c)+" +0x8="+rd(p,0x8)+" +0x10="+rd(p,0x10)+")";
    const idx=Math.floor(off/0xA0), variant=Math.floor((off%0xA0)/0x28);
    return "idx"+idx+"(sz"+FONT_SIZE_TABLE[idx]+")/v"+variant+" cell+0xC="+rd(p,0x0c);
  }
  const hex=(v)=>"0x"+((v>>>0).toString(16));

  // ---- [row] draw_faction_row entry ------------------------------------
  let rowN=0;
  Interceptor.attach(VA(0x00478630), { onEnter(){
    if (rowN>=40) return; rowN++;
    const sp=this.context.esp, r=rd(sp,0x0c);
    log("[row] g="+ps()+" self="+hex(this.context.ecx.toInt32())+" faction="+rd(sp,4)+" row#="+rd(sp,8)+
        " rect={"+rd(r,0)+","+rd(r,4)+","+rd(r,8)+","+rd(r,12)+"} winW(+0x4c4)="+rd(COMM_WIN,0x4c4)+
        " rowH(+0x1158)="+rd(COMM_WIN,0x1158)+" hover(+0x1168)="+rd(COMM_WIN,0x1168));
  }});

  // ---- [setfont] post-thunk: 0x5DAC80 = jne target, eax = f0 as the thunk left it
  let sfN=0;
  Interceptor.attach(VA(0x005DAC80), { onEnter(){
    const b=this.context.ecx.toInt32()>>>0; if (b!==MW_BUF) return;
    const s=ps(); const f=this.context.eax.toInt32();
    let note="";
    if (LEVER_FONT && s>16 && (f>>>0)===ROW_FONT){
      // baked hm_scalefont did NOT replace it -> off-table cell->pt-3 law here as a lever
      const cell=rd(f,0x0c); const pt=(cell>3?cell-3:cell);
      const nf=find_font(clampSz(sc(pt,s)),1);
      this.context.eax=nf; note=" LEVER-> "+decodeFont(nf.toInt32());
    }
    if (sfN<12){ sfN++; log("[setfont] MW_BUF g="+s+" f0="+decodeFont(f)+" f1="+hex(rd(this.context.esp,8))+" f2="+hex(rd(this.context.esp,0xc))+note); }
  }});

  // ---- rect lever shared by both writers --------------------------------
  function rectLever(tag, ctx){
    const b=ctx.ecx.toInt32()>>>0; if (b!==MW_BUF) return;
    const sp=ctx.esp, r=rd(sp,8);
    const L=rd(r,0),T=rd(r,4),R=rd(r,8),B=rd(r,12); const s=ps();
    let note=" font+0x52c="+decodeFont(rd(b,0x52c));
    if (LEVER_RECT && s>16 && (B-T)===18){          // NATIVE gate: scaled rows are sc(18)>18 tall
      // L = 0+7+3 native inset ; R = winW(scaled) - 10 native ; T/B native row band
      const nL=sc(L,s), nT=rowY(T,s), nR=R+10-sc(10,s), nB=nT+sc(18,s);
      wr(r,0,nL); wr(r,4,nT); wr(r,8,nR); wr(r,12,nB);
      note+=" LEVER-> {"+nL+","+nT+","+nR+","+nB+"}";
    }
    return "["+tag+"] g="+s+" rect={"+L+","+T+","+R+","+B+"} str='"+(()=>{try{return ptr(rd(sp,4)).readCString();}catch(e){return "?";}})()+"'"+note;
  }
  let wN=0;
  Interceptor.attach(VA(0x005DCF40), { onEnter(){ const m=rectLever("wl4",this.context); if (m && wN<40){wN++; log(m);} }});
  Interceptor.attach(VA(0x005DD450), { onEnter(){ const m=rectLever("wr6",this.context); if (m && wN<40){wN++; log(m);} }});

  // ---- [spot+] Spot_add on the COMMLINK list ----------------------------
  let saN=0;
  Interceptor.attach(VA(0x005FA960), { onEnter(){
    const self=this.context.ecx.toInt32()>>>0; if (self!==SPOTS) return;
    const sp=this.context.esp, s=ps();
    const idx=rd(sp,4),type=rd(sp,8),x=rd(sp,0xc),y=rd(sp,0x10),w=rd(sp,0x14),h=rd(sp,0x18);
    let note="";
    if (LEVER_SPOT && s>16 && type===1 && h===18){    // NATIVE gate
      const nx=sc(x,s), ny=rowY(y,s), nw=(x+w)+10-sc(10,s)-nx, nh=sc(18,s);
      wr(sp,0xc,nx); wr(sp,0x10,ny); wr(sp,0x14,nw); wr(sp,0x18,nh);
      note=" LEVER-> ("+nx+","+ny+" "+nw+"x"+nh+")";
    }
    if (saN<40){ saN++; log("[spot+] g="+s+" idx="+idx+" type="+type+" ("+x+","+y+" "+w+"x"+h+") n(+8)="+rd(self,8)+" cap(+4)="+rd(self,4)+note); }
  }});

  // ---- [spot?] Spot_check on the COMMLINK list ---------------------------
  let scN=0;
  Interceptor.attach(VA(0x005FAB00), { onEnter(){
    const self=this.context.ecx.toInt32()>>>0; this.mine=(self===SPOTS); if(!this.mine) return;
    const sp=this.context.esp; this.x=rd(sp,4); this.y=rd(sp,8); this.pPos=rd(sp,0xc); this.pType=rd(sp,0x10);
  }, onLeave(ret){
    if (!this.mine || scN>=40) return; scN++;
    log("[spot?] in=("+this.x+","+this.y+") -> ret="+ret.toInt32()+" pos="+(this.pPos?rd(this.pPos,0):"-")+" type="+(this.pType?rd(this.pType,0):"-"));
  }});

  // ---- [mm] commlink_on_mouse_move -------------------------------------
  let mmN=0;
  Interceptor.attach(VA(0x00477E70), { onEnter(){
    if (mmN>=20) return; mmN++;
    const sp=this.context.esp;
    log("[mm] self="+hex(this.context.ecx.toInt32())+" x="+rd(sp,4)+" y="+rd(sp,8)+" winX(+0x?)... hover="+rd(COMM_WIN,0x1168));
  }});

  log("armed: row/setfont/wl4/wr6/spot+/spot?/mm  levers rect="+LEVER_RECT+" spot="+LEVER_SPOT+" font="+LEVER_FONT);
}
