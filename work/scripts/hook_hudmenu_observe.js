"use strict";
// ===========================================================================
// hook_hudmenu_observe.js -- OBSERVER-ONLY (2026-07-07). The MENU dropdown +
// COMMLINK panel scaling is now BAKED into the exe (group commlink_menu_scale,
// live MD5 fad779d8). This script applies NO levers -- it only reads back the
// values the baked thunks already wrote, so running it on the baked exe does
// NOT double-apply. Use the plain "SMACX <res>" shortcuts for a clean visual
// check; use this only to confirm the bake fired.
//   [OBS layout] MENU widget geometry fields AFTER thunk_menu_layout ran
//   [OBS synth]  hm_synth_core fired (dest / rect / detected pair)  -- proves
//                the strip-synthesis path is live
//   [OBS mw]     COMMLINK box rect w/h AFTER thunk_comm_gwinit ran
// ⚠ Do NOT run any hook_hudmenu_scale.js (the pre-bake prototype) on this exe:
//    it would apply the levers a SECOND time (double-scale).
// ===========================================================================
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_hudmenu_observe.log";
log("=== hook_hudmenu_observe.js (OBSERVER, baked exe) ===");

if (requireBase()) {
  const layout_show   = VA(0x004032A0);
  const Sprite_blit_core = VA(0x005E4B9A);
  const hm_synth_core = VA(0x00A125D0);          // pcave2+0x65D0
  const menu_win = 0x9380DC, menu_buf = 0x938520;
  const comm_win = 0x7FD648, MW_BUF = 0x7FDA8C;
  const g_popup_scale = VA(0x00668740);

  const rd=(p,o)=>{try{return ptr(p).add(o).readS32();}catch(e){return null;}};
  function ps(){try{return g_popup_scale.readU32();}catch(e){return 16;}}

  // MENU geometry: read the fields the baked thunk_menu_layout wrote (post-detour).
  let menuLogged=false;
  Interceptor.attach(layout_show, { onLeave(){
    const p=this.mw; if (!p) return;
    if (menuLogged) return; menuLogged=true;
    log("[OBS layout] g="+ps()+" win=0x"+(p>>>0).toString(16)+
        " w(+0x1104)="+rd(p,0x1104)+" spotW(+0x1130)="+rd(p,0x1130)+
        " rowH(+0x1134)="+rd(p,0x1134)+" margin(+0x1108)="+rd(p,0x1108));
  }, onEnter(){ this.mw=this.context.ecx.toInt32()>>>0; }});

  // hm_synth_core(dst,dx,dy,num,den,spr): prove the synthesis path is live.
  let synthN=0;
  Interceptor.attach(hm_synth_core, { onEnter(){
    if (synthN>=12) return; synthN++;
    const sp=this.context.esp;
    const dst=rd(sp,0x04)>>>0, dx=rd(sp,0x08), dy=rd(sp,0x0c);
    const num=rd(sp,0x10), den=rd(sp,0x14), spr=rd(sp,0x18)>>>0;
    let tag="?"; if (dst===menu_buf) tag="MENU"; else if (dst===MW_BUF) tag="COMM";
    else if (dst===0x7FEC50) tag="Council"; else if (dst===0x7FF79C) tag="MP-btn";
    log("[OBS synth] "+tag+" dst=0x"+dst.toString(16)+" @("+dx+","+dy+") "+num+"/"+den+
        " spr=0x"+spr.toString(16));
  }});

  // COMMLINK box rect after the baked build (read via first MW blit).
  let mwLogged=false;
  Interceptor.attach(Sprite_blit_core, { onEnter(){
    if (mwLogged) return;
    const dest=rd(this.context.esp,0x04)>>>0; if (dest!==MW_BUF) return;
    mwLogged=true;
    log("[OBS mw] g="+ps()+" box w(+0xa40)="+rd(comm_win,0xa40)+" h(+0xa44)="+rd(comm_win,0xa44)+
        " winW(+0x4c4)="+rd(comm_win,0x4c4)+" -winH(+0x4c8)="+rd(comm_win,0x4c8));
  }});

  log("observer armed: layout_show + hm_synth_core + MW blit (NO levers applied)");
}
