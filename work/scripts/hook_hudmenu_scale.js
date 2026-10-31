// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// ===========================================================================
// hook_hudmenu_scale.js -- MENU dropdown SIZE + POSITION (crisp native scale).
//   COMMLINK: position-only for now (its size is baked at build time).
//
// MENU dropdown (window 0x9380DC, buffer 0x938520) native render:
//   title sprite 139x6 @(0,0); row sprite 139x18 x10 @ y=6,24..168; text @ x=8,
//   y=9,27..171. All native 1/1. Sizing fields: +0x441 w=139, +0x44d rowH=18,
//   +0x442 margin=6 (MenuWidget_layout_show 0x4032A0).
//
// SCALE (g/16 = g_popup_scale_num/16, gate g>16, idempotent from vanilla consts):
//   (1) fields *g/16  -> buffer+rect+hit-test scale together; Y auto-anchors
//       (layout's own y = (DAT240-DAT248) - scaledH + SH).
//   (2) title/row Sprite_draw_2 into the buffer: pos *g/16, num/den = g/16.
//   (3) item text: pos *g/16; g_menu_font repointed to a scaled font.
//   (4) X override = (SW - scaledStripW)/2 (fixes native-1024 centering).
// COMM position: right edge at (SW+stripW)/2, bottom at scaled strip top.
// ===========================================================================
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_hudmenu_scale.log";
log("=== hook_hudmenu_scale.js v1 (MENU size+pos, COMM pos) ===");

if (requireBase()) {
  const Win_move      = VA(0x005ED7D0);
  const layout_show   = VA(0x004032A0);
  const Sprite_draw_2 = VA(0x005E4B4A);
  const Buffer_wmfr_l = VA(0x005DCAE0);
  const find_font_a   = VA(0x005882F0);
  const menu_win = 0x9380DC, comm_win = 0x7FD648;
  const menu_buf = 0x938520;
  const g_menu_font = VA(0x009B7B68);
  const g_af240 = VA(0x007AF240), g_af248 = VA(0x007AF248);
  const g_popup_scale = VA(0x00668740);
  const ScreenWidth = VA(0x009B7B1C), ScreenHeight = VA(0x009B7B20);
  const MENUWIN = ptr(menu_win).toString(), COMMWIN = ptr(comm_win).toString();

  const find_font = new NativeFunction(find_font_a, 'pointer', ['int','int']); // cdecl (x86 default)
  const FONT_VARIANT = 1;                 // menu font variant (native = find_font(0x10, ?)) -- tune if weight wrong
  const SCALE_SPRITE_POS = false;         // field-scale already moves the render's step; don't double-scale
  const SCALE_TEXT_X     = true;          // text X inset is NATIVE (8) -> scale to track pristine (8*g/16)
  const NORMALIZE_TEXT_Y = true;          // row0 draws 9px low @g40 (intra 16 vs 7); rewrite Y to uniform formula
  const LOG_POS = false;
  globalThis.__CENSUS_MENUS = true;       // log distinct menu widgets + buffers (find COMMLINK dropdown)

  const rd=(p,o)=>{try{return ptr(p).add(o).readS32();}catch(e){return null;}};
  const wr=(p,o,v)=>{try{ptr(p).add(o).writeS32(v);}catch(e){}};
  function ps(){try{return g_popup_scale.readU32();}catch(e){return 16;}}
  function sw(){return ScreenWidth.readS32();} function sh(){return ScreenHeight.readS32();}
  const sc=(v,s)=>Math.round(v*s/16);
  const clampSz=(n)=> n>40?40:(n<8?8:n);
  // LAW OF UNIFORM ROW PITCH: both panels stack native 18px strips after a 6px
  // title. Per-value rounding (sc(6+18k+r)) makes strip seams drift 1px and each
  // strip restarts its NN phase -> the row-seam banding at s=22/25 (invisible at
  // 4K only because 18*40/16=45 is exact). Quantize: y = sc(6) + k*sc(18) + sc(r).
  function rowY(y,s){ if (y<6) return sc(y,s); const k=Math.floor((y-6)/18), r=(y-6)%18; return sc(6,s)+k*sc(18,s)+sc(r,s); }

  // §7 STRIP SYNTHESIS (skill scaling-frames; same class as the button bands /
  // TURN banner, lock e638e7b8). Two proven facts drive this (2026-07-07):
  //  (1) multi.pcx ground truth: row strips are STRICT 1px pairs (comm rows
  //      {187,55}, footer {72,138}, 187/72 on EVEN rows); title = structural art.
  //  (2) the engine's scaled expander (Sprite_fill_scaling_table Bresenham +
  //      y-table getter 0x5EABBF) DROPS THE LAST DEST ROW at fractional scales --
  //      the row stays key-9 in the buffer and the MAP bleeds through (the red
  //      streaks; hidden at 4K only because the gap lands on the dark phase).
  // So: after each strip blit, re-synthesize the WHOLE dest rect ourselves:
  // clean NN row/col mapping (covers the dropped row), pair pixels remapped to
  // the device-density law (P=SL.stripePeriod(g), light=P>>1 rows first -- bit-identical
  // to the engine's exact 2.5x output at 4K), structural pixels NN-placed,
  // key pixels skipped (transparency preserved). Phase keys on the DEST BUFFER
  // row so all strips share one continuous panel-wide pattern.
  // Detect the pair from the NATIVE sprite (per-blit content key -- pair-
  // ambiguity rule): strict 1px alternation around two adjacent mid rows.
  function spritePair(base, pitch, w, h, key){
    try {
      const xm=w>>1;
      const px=(y)=>base.add(y*pitch+xm).readU8();
      for (const yA of [h>>1, (h>>1)-1]){
        const yB=yA+1; if (yA<1 || yB+1>=h) continue;
        const vA=px(yA), vB=px(yB);
        if (vA===vB || vA===key || vB===key) continue;
        if (px(yA-1)!==vB || px(yB+1)!==vA) continue;   // not a strict 1px pair here
        const light=(yA%2===0)?vA:vB;                    // even-native-row member
        return {a:vA, b:vB, light:light, dark:(light===vA)?vB:vA};
      }
      return null;
    } catch(e){ return null; }
  }
  let synthLogN=0;
  function synthStrip(bufAddr, dx, dy, num, den, spr){
    try {
      const g=ps(); if (g<=16) return;
      const sdata=spr.add(0x4).readU32();
      const spitch=spr.add(0xc).readS32();
      const sw=spr.add(0x10).readS32(), sh=spr.add(0x14).readS32();
      const key=spr.add(0x8).readU8();
      if (!sdata || spitch<=0 || sw<3 || sh<2 || sw>2048 || sh>256) return;
      const buf=ptr(bufAddr>>>0);
      const data=buf.add(0x54).readU32();
      const stride=buf.add(0x4a8).readS32();
      const bw=buf.add(0x80).readS32();
      let bh=buf.add(0x84).readS32(); if (bh<0) bh=-bh;   // stored NEGATIVE (feedback rule)
      if (!data || stride<=0) return;
      const sbase=ptr(sdata>>>0), dbase=ptr(data>>>0);
      const pair=spritePair(sbase, spitch, sw, sh, key);
      const W=Math.round(sw*num/den), H=Math.round(sh*num/den);
      const x0=Math.max(dx,0), y0=Math.max(dy,0);
      const x1=Math.min(dx+W,bw), y1=Math.min(dy+H,bh);
      if (x1<=x0 || y1<=y0) return;
      if (synthLogN<10){ synthLogN++;
        log("[synth] spr=0x"+spr.toString(16).slice(-8)+" "+sw+"x"+sh+" -> ("+dx+","+dy+") "+W+"x"+H+
            (pair?(" pair="+pair.a+"/"+pair.b):" (no pair)")); }
      const P=SL.stripePeriod(g), lightN=P>>1;
      // src rows once; src col per dest col
      const srows=[]; for (let r=0;r<sh;r++) srows.push(new Uint8Array(sbase.add(r*spitch).readByteArray(sw)));
      const cols=new Int32Array(x1-x0);
      for (let c=x0;c<x1;c++){ let v=Math.floor((c-dx)*den/num); if (v>=sw) v=sw-1; cols[c-x0]=v; }
      for (let y=y0;y<y1;y++){
        let sr=Math.floor((y-dy)*den/num); if (sr>=sh) sr=sh-1;
        const srow=srows[sr];
        const tex=(y%P)<lightN ? pair && pair.light : pair && pair.dark;
        const rowp=dbase.add(y*stride+x0);
        const out=new Uint8Array(rowp.readByteArray(x1-x0));  // seed with current (key px keep it)
        for (let i=0;i<out.length;i++){
          let v=srow[cols[i]];
          if (pair && (v===pair.a||v===pair.b)) v=tex;
          if (v!==key) out[i]=v;
        }
        rowp.writeByteArray(out.buffer);
      }
    } catch(e){ if (synthLogN<12){ synthLogN++; log("[synth] err "+e); } }
  }

  // repoint g_menu_font to a scaled font, once per distinct scale
  let lastScale=0;
  function ensureFont(s){
    if (s===lastScale || s<=16) return; lastScale=s;
    try { const sz=clampSz(sc(16,s)); const f=find_font(sz,FONT_VARIANT);
      g_menu_font.writePointer(f);
      log("[font] g_menu_font -> find_font("+sz+","+FONT_VARIANT+") = "+f);
    } catch(e){ log("[font] err "+e); }
  }

  const MW=139, MRH=18, MMARGIN=6;

  // (1) geometry fields (idempotent from vanilla constants)
  Interceptor.attach(layout_show, { onEnter(){
    const s=ps(); if (s<=16) return; ensureFont(s);
    const p=this.context.ecx;
    wr(p,0x441*4, sc(MW,s));       // resize/buffer width
    wr(p,0x44c*4, sc(MW,s));       // spot/hit width (FUN_004031a0 reads this for Spot_add W)
    wr(p,0x44d*4, sc(MRH,s));      // rowH (pitch: render step + spot Y/H)
    wr(p,0x442*4, sc(MMARGIN,s));  // top margin
    // CENSUS: log each distinct menu widget (find the COMMLINK dropdown's win+buf+count)
    if (globalThis.__CENSUS_MENUS){
      globalThis.__seenW = globalThis.__seenW || {};
      const key=(p.toInt32())>>>0;
      if (!globalThis.__seenW[key]){ globalThis.__seenW[key]=1;
        const buf=rd(p,0x444), cnt=rd(p,0xa18);
        log("[menu widget] win=0x"+key.toString(16)+" buf(+0x444)=0x"+((buf>>>0).toString(16))+" count(+0xa18)="+cnt); }
    }
    if (!globalThis.__lg){ globalThis.__lg=1;
      log("[layout_show] fields w="+sc(MW,s)+" rowH="+sc(MRH,s)+" margin="+sc(MMARGIN,s)+" s="+s); }
  }});

  // (2) title/row sprite blits into the menu buffer
  let sprN=0;
  Interceptor.attach(Sprite_draw_2, { onEnter(){
    const dest=rd(this.context.esp,0x04); if ((dest>>>0)!==menu_buf) return;
    const s=ps(); if (s<=16) return;
    const x=rd(this.context.esp,0x0c), y=rd(this.context.esp,0x10);
    if (LOG_POS && sprN<14){ sprN++; log("  [spr in] x="+x+" y="+y); }
    if (SCALE_SPRITE_POS){
      wr(this.context.esp,0x0c, sc(x,s));
      wr(this.context.esp,0x10, rowY(y,s));   // uniform row pitch (see rowY)
    }
    // Row strips: stretch exactly sc(18)/18 so strips tile seamlessly with
    // identical NN phase. NB the MENU render passes ALREADY-SCALED y (it steps
    // by the scaled layout fields, y = sc(6)+k*sc(18)) -- the old native-y test
    // (y-6)%18 never matched at s=22/25, so MENU strips kept the drifting g/16
    // stretch = the seam banding. Match on the scaled pitch + native blit_h 18.
    // NB Sprite_draw_2 is THISCALL, ECX=sprite ([esp+8] is the KEY) -- reading
    // the sprite from the stack broke the h gate AND fed garbage to the pair
    // detect (the zero-diff MENU run of 2026-07-07).
    const spr=this.context.ecx, sprH=rd(spr,0x14);
    const T=sc(6,s), R=sc(18,s);
    let num=s, den=16;
    if (sprH===18 && y>=T && (y-T)%R===0){ num=R; den=18; }
    wr(this.context.esp,0x14, num); wr(this.context.esp,0x18, den);
    this.rs={x:(SCALE_SPRITE_POS?sc(x,s):x), y:(SCALE_SPRITE_POS?rowY(y,s):y), num:num, den:den, spr:spr};
  }, onLeave(){
    if (this.rs) synthStrip(menu_buf, this.rs.x, this.rs.y, this.rs.num, this.rs.den, this.rs.spr);
  }});

  // (3) item text into the menu buffer.
  //   Fonts are stored ON the buffer: +0x52c f0, +0x530 f1, +0x534 f2 (selected per
  //   markup style at +0x510). Buffer_wmfr_l takes NO font arg -> g_menu_font repoint
  //   was a no-op. Scale = override the three font slots with scaled font_table_v0 rows.
  const FONT_TABLE = 0x0093FC58;          // font_table_v0: idx*0xA0 + variant*0x28, Font size 0x28
  const CENSUS_FONT = false;              // native slots: only +0x52c = find_font(16,1) cell=20 (idx7/v1)
  const SCALE_FONT  = true;               // override +0x52c with find_font(16*g/16, 1)
  // decode a font pointer against font_table_v0 -> "idx/variant" or "off-table"
  function decodeFont(p){
    if (p===null||p===0) return "0";
    const off=(p>>>0)-FONT_TABLE;
    if (off<0 || off>=12*0xA0) return "0x"+(p>>>0).toString(16)+"(off-table)";
    const idx=Math.floor(off/0xA0), variant=Math.floor((off%0xA0)/0x28), rem=(off%0xA0)%0x28;
    return "idx"+idx+"/v"+variant+(rem?("+"+rem):"");
  }
  const FONT_SIZE_TABLE=[40,36,32,24,22,20,18,16,14,12,10,8];
  // scaled font row for a native slot: keep its variant, size = nativeSize*g/16 -> nearest row
  function scaledFontFor(p, s){
    const off=(p>>>0)-FONT_TABLE; if (off<0||off>=12*0xA0) return null;
    const idx=Math.floor(off/0xA0), variant=Math.floor((off%0xA0)/0x28);
    const nativeSize=FONT_SIZE_TABLE[idx]||16;
    const want=clampSz(sc(nativeSize,s));
    return find_font(want, variant);  // find_font snaps to nearest row, same variant
  }
  let txtN=0, fontLogged=false;
  Interceptor.attach(Buffer_wmfr_l, { onEnter(){
    const dest=(this.context.ecx.toInt32())>>>0; if (dest!==menu_buf) return;
    const s=ps(); if (s<=16) return;
    const b=this.context.ecx;
    if (CENSUS_FONT && !fontLogged){ fontLogged=true;
      const f0=rd(b,0x52c), f1=rd(b,0x530), f2=rd(b,0x534), fl=rd(b,0x538), st=rd(b,0x510);
      const ch=(p)=>{const v=rd(p,0x0c);return v===null?"?":v;};
      log("[menu font] +52c="+decodeFont(f0)+"(cell="+ch(f0)+") +530="+decodeFont(f1)+"(cell="+ch(f1)+
          ") +534="+decodeFont(f2)+"(cell="+ch(f2)+") +538flags="+fl+" +510style="+st);
    }
    if (SCALE_FONT){
      // IDEMPOTENCE GATE (double-scale feedback rule): the widget's draw
      // (FUN_00403340) calls Buffer_set_font(DAT_00945764)=find_font(16,1) ONCE
      // per redraw, then draws all rows. Rewriting the slot from its CURRENT
      // value re-scales per ROW (16->22->32->40 within one redraw = the giant
      // overlapped rows at s=22/25; invisible at 4K only because 40 clamps).
      // Only rewrite when the slot holds the NATIVE menu font.
      const NATIVE_MENU_FONT = FONT_TABLE + 7*0xA0 + 0x28;   // idx7/v1 = find_font(16,1)
      const p=rd(b,0x52c);
      if (p===NATIVE_MENU_FONT){ const nf=scaledFontFor(p,s); if(nf) ptr(b).add(0x52c).writePointer(nf); }
    }
    const x=rd(this.context.esp,0x08), y=rd(this.context.esp,0x0c);
    if (LOG_POS && txtN<14){ txtN++; log("  [txt in] x="+x+" y="+y); }
    if (SCALE_TEXT_X) wr(this.context.esp,0x08, sc(x,s));
    if (NORMALIZE_TEXT_Y){
      // engine draws row0's text at margin+16 (font-metric baseline) but rows>=1 at
      // sprite_y+7 -> GAME sits 9px low. Rewrite EVERY row to the uniform formula
      // margin + rowIdx*rowH + intra (intra = vanilla 3 * g/16). rowIdx from incoming y.
      // incoming y is ALREADY scaled (rect table at widget+0xa2c is rebuilt from
      // the fields layout_show persisted); y = margin + i*rowH + (rowH-fontH)/2.
      // ROUND (not floor): the centering term is a sub-half-row fraction that
      // floor() turns into an off-by-one row when fontH>rowH (the overlap bug).
      const margin=sc(MMARGIN,s), rowH=sc(MRH,s), intra=Math.floor(3*s/16);
      const rowIdx=Math.round((y-margin)/rowH);
      if (rowIdx>=0) wr(this.context.esp,0x0c, margin + rowIdx*rowH + intra);
    }
  }});

  // CENSUS: full draw inventory for the COMMLINK box (MultiWin 0x7fd648).
  //   Text goes to buffer 0x7fda8c (MultiWin+0x444); "Council" button to 0x7fec50.
  //   Log every sprite blit + text draw into those buffers, with src dims + caller.
  const COMM_BUFS = { "0x7fda8c":"MW+444", "0x7fec50":"Council-btn" };
  const CENSUS_COMM = false;
  if (CENSUS_COMM){
    const seen = {};
    // sprite blits: Sprite_draw_2([esp+4]=dest, [+8]=src, [+c]=x, [+10]=y, [+14]=num, [+18]=den)
    Interceptor.attach(Sprite_draw_2, { onEnter(){
      const dest=(rd(this.context.esp,0x04)>>>0), k="0x"+dest.toString(16);
      if (!COMM_BUFS[k]) return;
      const src=rd(this.context.esp,0x08)>>>0;
      const x=rd(this.context.esp,0x0c), y=rd(this.context.esp,0x10);
      const num=rd(this.context.esp,0x14), den=rd(this.context.esp,0x18);
      // sprite src dims: +0x10 w, +0x14 h (blit fields)
      const sw_=rd(src,0x10), sh_=rd(src,0x14);
      let caller="?";
      try{ caller="0x"+(this.returnAddress.sub(globalThis.TERRANX_BASE).toUInt32()+0x400000).toString(16);}catch(e){}
      const key="spr|"+k+"|"+x+","+y+"|"+sw_+"x"+sh_+"|"+caller;
      if (seen[key]) return; seen[key]=1;
      log("[COMM spr] dest="+k+"("+COMM_BUFS[k]+") src="+sw_+"x"+sh_+" @"+x+","+y+" num/den="+num+"/"+den+" <- "+caller);
    }});
    // text draws
    const va=(a)=>{ try{ return "0x"+(a.sub(globalThis.TERRANX_BASE).toUInt32()+0x400000).toString(16);}catch(e){return "?";} };
    Interceptor.attach(Buffer_wmfr_l, { onEnter(){
      const dest=(this.context.ecx.toInt32())>>>0, k="0x"+dest.toString(16);
      if (dest===menu_buf || !COMM_BUFS[k]) return;
      let str=""; try{ str=ptr(this.context.esp).add(0x04).readPointer().readCString()||""; }catch(e){}
      const b=this.context.ecx;
      const x=rd(this.context.esp,0x08), y=rd(this.context.esp,0x0c);
      const f0=rd(b,0x52c), f1=rd(b,0x530), f2=rd(b,0x534);
      const key="txt|"+k+"|"+str;
      if (seen[key]) return; seen[key]=1;
      log("[COMM txt] dest="+k+"("+COMM_BUFS[k]+") str=\""+str+"\" @"+x+","+y+
          " f0="+decodeFont(f0)+" f1="+decodeFont(f1)+" f2="+decodeFont(f2)+" <- "+va(this.returnAddress));
      // one-shot backtrace on "NO CONTACTS" -> reveals the box redraw function
      if (!globalThis.__btDone && str.toUpperCase().indexOf("CONTACT")>=0){ globalThis.__btDone=true;
        const bt=Thread.backtrace(this.context, Backtracer.FUZZY).map(va);
        log("[COMM bt] "+bt.slice(0,12).join(" <- "));
      }
    }});
    // one-shot: dump MultiWin box geometry live
    globalThis.__dumpedMW = globalThis.__dumpedMW || false;
    const dumpMW=()=>{ if (globalThis.__dumpedMW) return; globalThis.__dumpedMW=true;
      const w=comm_win;
      log("[COMM box] MultiWin 0x"+w.toString(16)+" +a40(boxW)="+rd(w,0xa40)+" +a44(boxH)="+rd(w,0xa44)+
          " +4c4(winW)="+rd(w,0x4c4)+" +4c8(-winH)="+rd(w,0x4c8)+" +a38.x="+rd(w,0xa38)+" +a3c.y="+rd(w,0xa3c)); };
    Interceptor.attach(Sprite_draw_2, { onEnter(){ const d=(rd(this.context.esp,0x04)>>>0); if(COMM_BUFS["0x"+d.toString(16)]) dumpMW(); }});
  }

  // ==== COMMLINK box (MultiWin 0x7fd648) SCALING ====================
  //   Built once by commlink_win_build 0x479f90; redrawn by FUN_00479330.
  //   Frame/rows blit via Sprite_blit_scaled_core (reads scale from globals
  //   0x696D18/0x696D1C) into buf MW+0x444; layout stacks y by native sprite
  //   heights, x=0. Text via Buffer_wmfr_l (header find_font(12,1), votes +0x285c).
  const GraphicWin_init_2 = VA(0x005D50A0);
  const Sprite_blit_core  = VA(0x005E4B9A);
  const BaseButton_init   = VA(0x00607210);
  const SCALE_NUM_G = VA(0x00696D18), SCALE_DEN_G = VA(0x00696D1C);
  const MW_RECT = (comm_win + 0xa38) >>> 0;     // rect struct: +0=x +4=y +8=w +0xc=h
  const MW_BUF  = 0x7fda8c;                      // = comm_win + 0x444
  const MW_BOXW = 138, MW_BOXH = 156;           // vanilla box (0xa40=0x8a, 0xa44 computed)
  const STAGE1_BOX = true;                       // scale box size + frame sprites

  if (STAGE1_BOX){
    // (A) box buffer/window size: scale rect w/h at init (runs once at build).
    //   Persist the scaled dims -- a settle-time re-init reads +0xa40/+0xa44, so
    //   restoring native there rebuilds a native buffer (regression). Leave scaled.
    Interceptor.attach(GraphicWin_init_2, { onEnter(){
      const s=ps(); if (s<=16) return;
      let r=null;
      const a0=rd(this.context.esp,0x04); if ((a0>>>0)===MW_RECT) r=a0>>>0;
      const ec=this.context.ecx.toInt32()>>>0; if (ec===MW_RECT) r=ec;
      if (r===null) return;
      const w=rd(r,0x08), h=rd(r,0x0c);
      wr(r,0x08, sc(w,s)); wr(r,0x0c, sc(h,s));
      log("[MW init] box "+w+"x"+h+" -> "+sc(w,s)+"x"+sc(h,s)+" s="+s);
    }});

    // (A2) COMMLINK sub-buttons (Council etc.): parent==window -> scale x,w,h.
    //   BaseButton_init(ecx=btn; [esp+4]text,+8 a3,+0xc x,+0x10 y,+0x14 w,+0x18 h,+0x1c parent,+0x20 a9)
    //   y is built as (scaledBoxH - NATIVE slack); reconstruct the proportional y:
    //   y_final = y*g/16 + Hs*(16-g)/16  (Hs = scaled boxH = +0xa44). See notes.
    Interceptor.attach(BaseButton_init, { onEnter(){
      const s=ps(); if (s<=16) return;
      const parent=rd(this.context.esp,0x1c)>>>0; if (parent!==comm_win) return;
      const Hs=rd(comm_win,0xa44)||0;
      const y=rd(this.context.esp,0x10);
      wr(this.context.esp,0x0c, sc(rd(this.context.esp,0x0c),s));            // x
      wr(this.context.esp,0x10, Math.round(y*s/16) + Math.round(Hs*(16-s)/16)); // y (corrected)
      wr(this.context.esp,0x14, sc(rd(this.context.esp,0x14),s));            // w
      wr(this.context.esp,0x18, sc(rd(this.context.esp,0x18),s));            // h
      const btn=this.context.ecx.toInt32()>>>0, buf=(btn+0x444)>>>0;
      globalThis.__commBtnBufs = globalThis.__commBtnBufs || {};
      globalThis.__commBtnBufs["0x"+buf.toString(16)]=1;
      log("[MW btn] obj=0x"+btn.toString(16)+" buf=0x"+buf.toString(16)+" Hs="+Hs+" y:"+y+"->"+rd(this.context.esp,0x10)+" s="+s);
    }});

    // (B) frame/row sprite blits into the MW buffer: pixel-scale + x,y*g/16
    //   __thiscall: ECX=sprite; stack [esp+4]=dest_buf, [esp+8]=key, [esp+0xc]=x, [esp+0x10]=y.
    //   Core reads scale from SCALE_NUM_G/SCALE_DEN_G globals; set them for MW blits.
    const BLIT_LOG = true;                        // one-shot: log dest/x/y of first MW-region blits
    let blitN=0;
    Interceptor.attach(Sprite_blit_core, { onEnter(){
      const dest=rd(this.context.esp,0x04)>>>0; if (dest!==MW_BUF) return;
      const s=ps(); if (s<=16) return;
      if (BLIT_LOG && blitN<12){ blitN++;
        log("[MW blit] dest=0x"+dest.toString(16)+" spr=0x"+(this.context.ecx.toInt32()>>>0).toString(16)+
            " key="+rd(this.context.esp,0x08)+" x="+rd(this.context.esp,0x0c)+" y="+rd(this.context.esp,0x10)); }
      // scale pixels via globals (restore onLeave). Row strips (y=6+18k) get the
      // uniform pitch: y=T+k*R and stretch num/den = R/18 EXACTLY, so strips tile
      // seamlessly with identical NN phase (kills the row-seam banding at s=22/25).
      // Width overflows by a clipped px or two -- uniform, invisible.
      this.oN=SCALE_NUM_G.readS32(); this.oD=SCALE_DEN_G.readS32(); this.did=true;
      const x=rd(this.context.esp,0x0c), y=rd(this.context.esp,0x10);
      const spr=this.context.ecx, sprH=rd(spr,0x14);
      let num=s, den=16;
      // gate on blit_h too: the footer (h=0x1c) starts at a row boundary (y=150)
      // but is NOT an 18px row -- it keeps the plain g/16
      if (y>=6 && (y-6)%18===0 && sprH===18){ num=sc(18,s); den=18; }
      SCALE_NUM_G.writeS32(num); SCALE_DEN_G.writeS32(den);
      wr(this.context.esp,0x0c, sc(x,s));
      wr(this.context.esp,0x10, rowY(y,s));
      this.rs={x:sc(x,s), y:rowY(y,s), num:num, den:den, spr:spr};
    }, onLeave(){ if (this.did){ SCALE_NUM_G.writeS32(this.oN); SCALE_DEN_G.writeS32(this.oD); }
      if (this.rs) synthStrip(MW_BUF, this.rs.x, this.rs.y, this.rs.num, this.rs.den, this.rs.spr); }});
  }

  // ==== STAGE 2: COMMLINK box TEXT (font + position) ====
  //   VOTES  -> cent_l_5 0x5DD020 (ecx=buf): [+8]x=0 [+c]y=iVar6+10 [+10]w=0x8a.
  //   header -> cent_l_7 0x5DD130 (ecx=buf): rect{L=0,T=iVar6,R=+0x4c4(scaled),B}.
  //   fonts via Buffer_set_font 0x5DAC70 (ecx=buf, f0/f1/f2). header=find_font(12,1)
  //   [table], votes=off-table Font_init font.
  const cent_l_5      = VA(0x005DD020);
  const cent_l_7      = VA(0x005DD130);
  const Buffer_setfont= VA(0x005DAC70);
  const STAGE2_TEXT = true;
  const FONT_CENSUS = true;
  if (STAGE2_TEXT){
    // off-table fonts: map via cell height (+0x0C) -> scaled table font, same variant guess
    function scaleAnyFont(p, s){
      if (!p) return null;
      const off=(p>>>0)-FONT_TABLE;
      if (off>=0 && off<12*0xA0) return scaledFontFor(p,s);   // table font
      const cell=rd(p,0x0c); if (cell===null||cell<=0) return null;
      // cell height ~= point size + 3 for these HUD fonts; recover point, scale, keep variant 1
      const nativePt = cell>3 ? cell-3 : cell;
      return find_font(clampSz(sc(nativePt, s)), 1);
    }
    const isCommBtn=(d)=>{ const m=globalThis.__commBtnBufs; return !!(m && m["0x"+(d>>>0).toString(16)]); };
    // fonts (also census)
    Interceptor.attach(Buffer_setfont, { onEnter(){
      const dest=this.context.ecx.toInt32()>>>0; if (dest!==MW_BUF && !isCommBtn(dest)) return;
      const s=ps(); if (s<=16) return;
      // args: [esp+4]=f0 [esp+8]=f1 [esp+0xc]=f2
      for (const o of [0x04,0x08,0x0c]){
        const p=rd(this.context.esp,o); if(!p) continue;
        if (FONT_CENSUS && !globalThis.__mwFontLog){ globalThis.__mwFontLog=globalThis.__mwFontLog||[]; }
        const nf=scaleAnyFont(p,s);
        if (FONT_CENSUS){ log("[MW setfont] slot+"+o.toString(16)+" p=0x"+(p>>>0).toString(16)+
            " "+decodeFont(p)+" cell="+rd(p,0x0c)+" -> "+(nf?("0x"+(nf.toInt32()>>>0).toString(16)):"null")); }
        if (nf) wr(this.context.esp,o, nf.toInt32());
      }
    }});
    // VOTES (MW_BUF): scale width + y.
    // Button text (btnbuf): DO NOT TOUCH -- it arrives via FlatButton_content_draw ->
    //   Buffer_wrap_cent_4 -> this fn, and FlatButton computes x/y/w from the ALREADY-
    //   SCALED 303x45 button window. Re-scaling y (18 -> 45) pushed the text below the
    //   45px buffer bottom = clipped invisible (the missing-"Council" bug).
    Interceptor.attach(cent_l_5, { onEnter(){
      const dest=this.context.ecx.toInt32()>>>0;
      const s=ps(); if (s<=16) return;
      if (dest===MW_BUF){
        const y=rd(this.context.esp,0x0c), w=rd(this.context.esp,0x10);
        wr(this.context.esp,0x0c, rowY(y,s));   // VOTES y=strip cursor+10: same row pitch
        wr(this.context.esp,0x10, sc(w,s));
      } else if (isCommBtn(dest)){
        // scaled slot-centred text sits (g-16)/8 low (skill scaling-text) -- nudge up
        const y=rd(this.context.esp,0x0c);
        wr(this.context.esp,0x0c, y - ((s-16)>>3));
      }
    }});
    // Council button TEXT font: nothing ever calls Buffer_set_font on the button
    //   buffer (census-confirmed), so its font slot (+0x52c) keeps the native cell-15
    //   (12pt) font and "Council" draws unscaled. Repoint the slot to the scaled table
    //   font at each FlatButton_content_draw entry -- BEFORE the text path runs, so its
    //   centering math also uses the scaled font. Idempotent (target derived from
    //   NATIVE 12pt, never from the current slot).
    const FlatButton_content_draw = VA(0x00607E50);
    Interceptor.attach(FlatButton_content_draw, { onEnter(){
      const obj=this.context.ecx.toInt32()>>>0;
      const buf=(obj+0x444)>>>0; if (!isCommBtn(buf)) return;
      const s=ps(); if (s<=16) return;
      const nf=find_font(clampSz(sc(12,s)), 1);
      if (nf) wr(buf,0x52c, nf.toInt32());
    }});
    // header position: scale rect top/bottom (y); left/right already scaled via +0x4c4
    Interceptor.attach(cent_l_7, { onEnter(){
      const dest=this.context.ecx.toInt32()>>>0; if (dest!==MW_BUF) return;
      const s=ps(); if (s<=16) return;
      const r=rd(this.context.esp,0x08); if (r===null) return;
      const t=rd(r,0x04), b=rd(r,0x0c);
      wr(r,0x04, rowY(t,s)); wr(r,0x0c, rowY(b,s));   // header rect: same row pitch
    }});

    // Council button FRAME (FlatButton_content_draw 0x607e50). CENSUS-CONFIRMED:
    //   steady-state draw is the ELSE branch -- a single CONTENT sprite (button+0xad4[state],
    //   e.g. MultiWin+0xfdc) drawn CENTERED in the window via the call at 0x607f43 (ret 0x607f48):
    //     Sprite_draw_2(buf, key, (winW-sprW)/2, -((sprH+winH_neg)/2), 1,1)   [ECX=sprite]
    //   Natively the 121x18 face exactly fills the 121x18 window (x=y=0). BaseButton scaled the
    //   window to 303x45, but the face stays 121x18 -> small sprite mid-window. FIX: scale the
    //   sprite pixels g/16 and recenter on the SCALED dims so it refills the window.
    //   (The 9-slice branch [b10] only fires ONCE pre-ad4 during build and is immediately
    //    overpainted by the GraphicWin_fill+content redraw -> never visible; leave it alone.)
    const ELSE_RET = VA(0x00607F48);   // ret addr of the else-branch content-sprite call
    const SCALE_BTN_FACE = true;       // restored: face fills the scaled window (confirmed correct)
    Interceptor.attach(Sprite_draw_2, { onEnter(){
      if (!SCALE_BTN_FACE) return;
      const dest=rd(this.context.esp,0x04)>>>0; if (!isCommBtn(dest)) return;
      const s=ps(); if (s<=16) return;
      if (!this.returnAddress.equals(ELSE_RET)) return;      // content sprite only
      const spr=this.context.ecx;                            // thiscall: sprite in ECX
      const sprW=rd(spr,0x18), sprH=rd(spr,0x1c); if (sprW===null||sprH===null) return;
      const win=(dest-0x444)>>>0;
      const winW=rd(win,0x4c4), winHneg=rd(win,0x4c8);        // +0x4c8 = -winH
      const scW=sc(sprW,s), scH=sc(sprH,s);
      wr(this.context.esp,0x0c, (winW - scW) >> 1);          // x centered on scaled sprite
      wr(this.context.esp,0x10, -((scH + winHneg) >> 1));    // y centered (mirror engine)
      wr(this.context.esp,0x14, s);                          // num
      wr(this.context.esp,0x18, 16);                         // den
      // face art = strict 1px pairs per state (multi.pcx: idle {136,190}, hover
      // {220,221}, pressed {89,92}) + structural edge rows -> same §7 class as
      // the panel strips; re-synthesize post-blit (de-band + cover the engine's
      // dropped last row). Text draws after the face, so it lands on top.
      this.rs={buf:dest, x:(winW-scW)>>1, y:-((scH+winHneg)>>1), num:s, den:16, spr:spr};
    }, onLeave(){
      if (this.rs) synthStrip(this.rs.buf, this.rs.x, this.rs.y, this.rs.num, this.rs.den, this.rs.spr);
    }});

    // --- FULL REDRAW SEQUENCE (uncapped): find the LAST draw into the button buffer. ---
    //   Hypothesis: a settle-time redraw repaints the face but the text path is skipped/clipped,
    //   overwriting "Council". Log every FlatButton draw + whether its text path reaches wrap_cent.
    const CENSUS_BTNSEQ = true;
    if (CENSUS_BTNSEQ){
      const FBcd = VA(0x00607E50), Bwc4 = VA(0x005DD920);
      let seq=0;
      Interceptor.attach(FBcd, { onEnter(){
        const obj=this.context.ecx.toInt32()>>>0; if (((obj+0x444)>>>0)!==0x7fec50) return;
        const s=ps(); if (s<=16) return; if (seq>=40) return;
        this.did=true; this.n=++seq; this.tp=(rd(obj,0xa7c)||0)>>>0; this.ab8=rd(obj,0xab8);
        // vcall gate: (**(*(+0xc4)+0x14))(obj,text,+0xa78) -> nonzero SKIPS text
        this.wc4="no";
      }, onLeave(){
        if (!this.did) return;
        log("[SEQ#"+this.n+"] FlatButton draw  +a7c=0x"+this.tp.toString(16)+" ab8="+this.ab8+"  wrap_cent="+this.wc4);
      }});
      Interceptor.attach(Bwc4, { onEnter(){
        const buf=this.context.ecx.toInt32()>>>0; if (buf!==0x7fec50) return;
        let str=""; try{ const tp=rd(this.context.esp,0x04); if(tp) str=ptr(tp>>>0).readCString()||""; }catch(e){}
        globalThis.__lastWrap="#"+seq+" \""+str+"\"";
        // mark the enclosing FlatButton draw as having reached wrap_cent
        log("   -> wrap_cent(\""+str+"\") x="+rd(this.context.esp,0x08)+" y="+rd(this.context.esp,0x0c)+" w="+rd(this.context.esp,0x10));
      }});
      log("[SEQ] last wrap will be shown; watch for a trailing FlatButton draw with wrap_cent=no");
    }
  }

  // (4) position: MENU X (Y auto via scaled fields), COMM X+Y (native size)
  Interceptor.attach(Win_move, { onEnter(){
    const t=this.context.ecx, sp=this.context.esp, ts=t.toString(), s=ps();
    if (s<=16) return;
    const stripW=Math.floor(1024*s/16);
    if (ts===MENUWIN){ wr(sp,0x04, Math.floor((sw()-stripW)/2)); return; }
    if (ts===COMMWIN){
      const winW=rd(t,0x4c4)||0, winH=-(rd(t,0x4c8)||0);
      const stripH=Math.abs(g_af248.readS32()-g_af240.readS32());
      wr(sp,0x04, Math.floor((sw()+stripW)/2)-winW);
      wr(sp,0x08, sh()-stripH-winH);
      return;
    }
  }});

  // CENSUS: capture the COMMLINK dropdown window ptr (shown when COMMLINK clicked)
  if (globalThis.__CENSUS_MENUS){
    const Win_show = VA(0x005ED9D0);
    const KNOWN = { // thinker engine.cpp window globals
      "0x6fec80":"CouncilWin","0x73acd8":"DiploWin","0x7fd648":"MultiWin/commlink-panel",
      "0x7f67f8":"MessageWin","0x876478":"ReportWin","0x8a6270":"SocialWin","0x9380dc":"MENU-dropdown",
    };
    Interceptor.attach(Win_show, { onEnter(){
      const w=(this.context.ecx.toInt32())>>>0, k="0x"+w.toString(16);
      // window screen rect: +0x13c left, +0x140 top, +0x144 right, +0x148 bottom
      const L=rd(w,0x13c), T=rd(w,0x140), R=rd(w,0x144), B=rd(w,0x148);
      if (L===null) return;
      // COMMLINK dropdown opens UPWARD from its bottom-HUD button -> right side, above the console
      if (!(L > sw()*0.65 && T > sh()*0.4 && B < sh()*0.78)) return;
      const nm=KNOWN[k]||"?"; let caller="?";
      try{ caller="0x"+(this.returnAddress.sub(globalThis.TERRANX_BASE).toUInt32()+0x400000).toString(16);}catch(e){}
      const w4c4=rd(w,0x4c4), w4c8=rd(w,0x4c8);
      log("[Win_show TR] win="+k+" ("+nm+") rect=["+L+","+T+","+R+","+B+"] winW="+w4c4+" -winH="+w4c8+" <- "+caller);
    }});
  }

  log("hooks: layout_show(fields+font) + Sprite_draw_2(menu) + text(menu) + Win_move(pos)");
}
