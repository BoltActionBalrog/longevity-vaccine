// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// hook_tutwin_fix.js v6 -- MUTATING PROTOTYPE: scale the TutWin directional tooltips.
//
// v6 (2026-07-10, after the v5 4K screenshot + pixel scans): two defects, both measured:
//   (1) ASYMMETRIC art channel (L 16px vs R 9px; pristine 13/11 = symmetric): v5 re-expanded the
//       art rect by Delta assuming the site pre-insets -- IT DOES NOT (site rect {0,0,1223,465}
//       IS the full window, inclusive). The +/-3px off-canvas clip shifted the art's inner stroke
//       3px outward on the left, 3px inward on the right. Fix: pass the rect UNCHANGED.
//   (2) NO blank space above the field: content-top = [popup+0x30e8] (27 native; [+0x21b8]=0 so
//       thunk_scale_header's titled-only path never scales it). Text Y == 30e8 at draw; field
//       T = 30e8-(ps3-Delta); ring T = 30e8-2*ps3 -- ALL content-relative. Fix at ONE point:
//       after BasePop_calculate_dimensions (0x603800 -- attach PROVEN safe by the v0 observer;
//       the no-attach zones are Popup_calculate_dimensions/Popup_on_draw_background only), scale
//       [0x30e8] vanilla 27 -> scale_px(27,g) and grow boxH [0x30c0] by the same delta so the
//       box accommodates the drop (law 5, chrome-follows-content; g<=16 no-op).
//
// v6.2: + L8 button bottom-row mirror. The 1600 hover probe proved the missing bottom highlight:
//   thunk_btn_shrink's nativeH = floor(|H|*16/g) round-trips the 20-row bar art to 19 rows at
//   fractional g (g=25/g=22; 4K is exact), clipping the art's bottom outline row at RENDER time
//   (the ring is baked into the per-state bar sprites -- no box2/hline calls fired). Pre-existing
//   baked bug for EVERY popup button at non-4K, masked on idle draws by the devfill re-tile.
//   v6.2/v6.3 papered over it with a post-draw row/band mirror; v6.4 prototypes the REAL bake
//   mechanism instead: at thunk_btn_shrink's tail, rewrite g_btn_nativeW/H (+ the shrunk canvas
//   dims) to round(orig*16/g). GLOBAL -- all popup buttons, matching the bake. BAKE = add g/2
//   before the idiv in thunk_btn_shrink (2dscale reads the same globals; one change).
//
// v5 (2026-07-10, after the v4 4K screenshot): v4's L5 never fired for the field/ring -- those
// draws route through the PF-ALIGN thunks (not devfill), and pfNeutralize forced the WHOLE chrome
// down the native g=16 path (thin art, mixed-scale engine rects, stale g_d528_left -> text X
// native). Root cause of everything left: TutWin draws NO TITLE BAND, so thunk_pf_title_stash
// never refreshes g_title_left/right and thunk_scale_header ([0xa48]!=0 gate) never scales the
// top reserve. v5 works WITH the baked chain instead of around it:
//   L5  backdrop: let devfill run (synth gets covered), then draw the ornate 6846b0 set through
//       baked thunk_box_thick_hollow @0xA0C000 (frame9 band-map enlarge, key-9, FLAT) over the
//       D-expanded window rect -> SCALED ornate art via the machinery already verified on this
//       exact sprite set (faction picker, 61x44 corner cells). Same hook FEEDS THE STASH:
//       g_title_left/right = scale_px(13,g) +/- Delta so frame_align/union_align/textfollow
//       compute TutWin's field/ring/text-X themselves at full g (chain relations, no overrides).
//   L6  top reserve [+0x21b8]: scale at tut_win ENTER (restore on LEAVE) -- content top, text Y,
//       field/ring T (copied from the engine local) and box_h all move together (law 5,
//       chrome-follows-content).
//   L7  body text X at thunk_faction_textmargin's cave entry @0xA0C6C0: for TutWin force
//       X = scale_px(13,g) + 2*ps3 (the same relation textfollow gives every titled popup;
//       TutWin misses it because of the stale stash ordering on first draw).
// v4 kept: L1 fonts, L2 button pipeline + canvas font, L3 line thickness.
//
// pf-chain constants Delta=(g-16)>>3 and ps3=(3g)>>4 mirror the BAKED asm (patches.yaml
// thunk_pf_frame_align/union_align/textfollow). BAKE NOTE: state these as a named law in
// work\scripts\scaling_laws.py (+ JS port) and run the sweep before baking any of this.
//
// Levers gate on g>16 -> native no-op. Laws via preloaded scaling_laws.js (globalThis.SL).

globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_tutwin_fix.log";
log("=== hook_tutwin_fix.js v6 started (MUTATING prototype) ===");
installAVHandler("tutwin_fix");

if (requireBase()) {
  const A_POPUPS_TUT   = VA(0x005888E0);  // popups_tutorial
  const A_TUT_WIN      = VA(0x004BDFE0);  // TutWin_tut_win
  const A_FLATBTN_DRAW = VA(0x00607E50);  // FlatButton_content_draw entry
  // WARNING: uimod.dll (winlines.cpp) byte-checks and detours this entry when display modes are bound; attaching here in
  // spawn mode makes the window-line overlay disable itself for the run (memory feedback-frida-hook-vs-dll-bytecheck).
  const A_LINE_RAW     = VA(0x005F2AC0);  // Win_window_line_raw
  const A_FIND_FONT    = VA(0x005882F0);  // find_font(size, variant) cdecl
  const A_SET_STR_FONT = VA(0x006048C0);  // BasePop_set_def_string_font cdecl
  const A_SET_DLG_FONT = VA(0x00609D20);  // Dialog_set_def_dialog_font cdecl
  const A_SET_BTN_FONT = VA(0x006074B0);  // BaseButton_set_def_font(Font*,Font*,Font*) cdecl
  const A_POPUP_SHOW   = VA(0x00404920);  // Popup_show
  const A_BUF_SET_FONT = VA(0x005DAC70);  // Buffer_set_font(this, f0, f1, f2, flags) thiscall RET 0x10
  const A_DEVFILL      = VA(0x00A102A0);  // thunk_box_thick_devfill (pcave2+0x42A0); ecx=dest, [esp+4]=&rect, [esp+8]=&params
  const A_HOLLOW       = VA(0x00A0C000);  // thunk_box_thick_hollow (pcave2+0x0): band-map 9-slice, key 9, FLAT (Delta zeroed 469118f6); thiscall(dest)(rect,params) RET 8
  const A_TEXTMARGIN   = VA(0x00A0C6C0);  // thunk_faction_textmargin (pcave2+0x6C0): E8-entered from 0x604df5; [esp]=ret, [esp+4]=str, [esp+8]=X, [esp+0xc]=Y, [esp+0x10]=width; esi=popup
  const ORNATE_SET     = VA(0x006846B0);  // the ornate box-sprite param block (tutorial/picker backdrop)

  const TUTWIN         = VA(0x008C6E68);
  const G_POPUP_SCALE  = VA(0x00668740);  // g_popup_scale_num
  const G_POPUP_ACTIVE = VA(0x00A0C530);  // g_popup_active            (pcave2+0x530)
  const G_TITLE_LEFT   = VA(0x00A0CF00);  // g_title_left              (pcave2+0xF00) -- pf-align stash
  const G_TITLE_RIGHT  = VA(0x00A0CF04);  // g_title_right             (pcave2+0xF04)
  const G_D528_LEFT    = VA(0x00A0E000);  // g_d528_left               (pcave2+0x2000) -- read-only here (log)
  const TUT_LO = VA(0x004BA000), TUT_HI = VA(0x004BF000);

  const find_font        = new NativeFunction(A_FIND_FONT,    "pointer", ["int", "int"], "mscdecl");
  const set_def_str_font = new NativeFunction(A_SET_STR_FONT, "int", ["pointer", "pointer", "pointer", "pointer"], "mscdecl");
  const set_def_dlg_font = new NativeFunction(A_SET_DLG_FONT, "int", ["pointer", "pointer", "pointer"], "mscdecl");
  const set_def_btn_font = new NativeFunction(A_SET_BTN_FONT, "int", ["pointer", "pointer", "pointer"], "mscdecl");
  const buf_set_font     = new NativeFunction(A_BUF_SET_FONT, "int", ["pointer", "pointer", "pointer", "pointer", "int"], "thiscall");
  const hollow_9slice    = new NativeFunction(A_HOLLOW,       "void", ["pointer", "pointer", "pointer"], "thiscall");

  function safe32(p) { try { return p.readS32(); } catch (e) { return null; } }
  function gval() { const v = safe32(G_POPUP_SCALE); return v === null ? 16 : v; }
  function tutAlive() { const v = safe32(TUTWIN.add(0x53d4)); return v !== null && v !== 0; }
  // pf-chain constants -- mirror the baked pf-align asm exactly (see header note)
  function pfDelta(g) { return (g - 16) >> 3; }
  function pfPs3(g)   { return (3 * g) >> 4; }

  const NATIVE_TUT_FONT_SIZE = 16;    // measured vanilla: g_text_font_v0 = font_table row 7 (size 16)
  const NATIVE_TUT_BTNFONT_SIZE = 12; // measured vanilla: popups_tutorial's BaseButton def = find_font(12,0)
  const NATIVE_LINE_TH = 4;
  const NATIVE_RING_L = 13;           // measured vanilla d5a0 ring left inset (1024 run: ring {13,21,477,170} in 490x211)

  // ---- L1: scaled tutorial body/dialog fonts + button label font --------------------------
  Interceptor.attach(A_POPUPS_TUT, {
    onLeave() {
      const g = gval();
      if (g <= 16) return;
      const sz = SL.scalePx(NATIVE_TUT_FONT_SIZE, g);       // LAW 1
      const f0 = find_font(sz, 0), f1 = find_font(sz, 1), f2 = find_font(sz, 2);
      set_def_str_font(f0, f1, f2, NULL);
      set_def_dlg_font(f0, f1, f2);
      const bsz = SL.scalePx(NATIVE_TUT_BTNFONT_SIZE, g);   // LAW 1
      const bf = find_font(bsz, 0);
      set_def_btn_font(bf, NULL, NULL);
      log("[L1 font ] g=" + g + " body 16->" + sz + " cellH=" + safe32(f0.add(0x0c)) +
          " btn 12->" + bsz + " btnCellH=" + safe32(bf.add(0x0c)));
    }
  });

  // ---- L2: TutWin button draws -- force the popup pipeline AND the scaled canvas font -----
  // + BOTTOM-ROW PROBE (1600 hover: highlight ring drew top/left/right but NOT the bottom
  // hline). While inside a TutWin button draw, trace Buffer_box_2/Buffer_hline_2 into the
  // button canvas (args + canvas dims AT CALL TIME -- if the ring rect is scaled but the call
  // lands during the SHRUNK-canvas phase, the bottom hline clips away), and dump the canvas
  // bottom rows after the draw so render-side vs composite-side is decided by data.
  const G_BTN_PENDING = VA(0x00A0C534), G_BTN_ORIGW = VA(0x00A0C538), G_BTN_ORIGH = VA(0x00A0C53C);
  const G_BTN_NATW = VA(0x00A0C540), G_BTN_NATH = VA(0x00A0C544);
  let l2logs = 0, curBtnCanvas = NULL, curBtn = NULL;
  function rowSig(data, stride, w, y) {
    // short run-length signature of canvas row y
    try {
      const row = data.add(y * stride);
      let out = [], cur = -1, n = 0;
      for (let x = 0; x < w; x++) {
        const v = row.add(x).readU8();
        if (v === cur) { n++; } else { if (n) out.push(cur.toString(16) + "x" + n); cur = v; n = 1; }
        if (out.length > 8) { out.push("..."); break; }
      }
      if (n && out.length <= 8) out.push(cur.toString(16) + "x" + n);
      return out.join(" ");
    } catch (e) { return "<err>"; }
  }
  Interceptor.attach(A_FLATBTN_DRAW, {
    onEnter() {
      this.forced = false;
      const g = gval();
      if (g <= 16) return;
      const b = this.context.ecx;
      const parent = safe32(b.add(0xc4));
      const isTut = (parent !== null && ptr(parent >>> 0).equals(TUTWIN)) || b.equals(TUTWIN.add(0xa5c));
      if (!isTut) return;
      const cur = safe32(G_POPUP_ACTIVE);
      if (cur === null) return;
      this.saved = cur;
      G_POPUP_ACTIVE.writeS32(1);
      // the label renders with the font the button CANVAS carries (content_draw never calls
      // Buffer_set_font, and TutWin's persistent buttons were fonted once at 12px).
      const bf = find_font(SL.scalePx(NATIVE_TUT_BTNFONT_SIZE, g), 0);
      buf_set_font(b.add(0x444), bf, bf, bf, 0);
      this.forced = true;
      curBtn = b; curBtnCanvas = b.add(0x444);
      if (l2logs++ < 24) {
        log("[L2 btn  ] btn=" + b + " state=" + safe32(b.add(0xab8)) +
            " canvasWH=" + safe32(b.add(0x4c4)) + "x" + safe32(b.add(0x4c8)) +
            " client=[" + safe32(b.add(0x474)) + "," + safe32(b.add(0x478)) + "," +
            safe32(b.add(0x47c)) + "," + safe32(b.add(0x480)) + "]");
      }
    },
    onLeave() {
      if (!this.forced) return;
      G_POPUP_ACTIVE.writeS32(this.saved);
      const b = curBtn;
      if (b !== NULL) {
        const W = safe32(b.add(0x4c4)), H = Math.abs(safe32(b.add(0x4c8)));
        const data = ptr((safe32(b.add(0x498)) || 0) >>> 0);
        const stride = safe32(b.add(0x8ec)) || 0;
        if (l2logs <= 24) {
          log("[L2 done ] btn=" + b + " WH=" + W + "x" + H +
              " pend=" + safe32(G_BTN_PENDING) + " orig=" + safe32(G_BTN_ORIGW) + "/" + safe32(G_BTN_ORIGH) +
              " nat=" + safe32(G_BTN_NATW) + "/" + safe32(G_BTN_NATH));
          if (!data.isNull() && stride > 0 && W > 0 && H > 2) {
            log("[L2 row0 ] " + rowSig(data, stride, W, 0));
            log("[L2 rowN2] " + rowSig(data, stride, W, H - 2));
            log("[L2 rowN1] " + rowSig(data, stride, W, H - 1));
          }
        }
      }
      curBtn = NULL; curBtnCanvas = NULL;
    }
  });

  // ---- L8 v4: thunk_btn_shrink nativeH rounding via TAIL-TARGET REDIRECT (no Interceptor) ----
  // WHY: nativeH = floor(|H|*16/g) round-trips the 20-row bar art to 19 at g=25/22 (floor is not
  // half_down's inverse; 4K exact) -> the 9-slice renders 1 row short and the art's bottom
  // outline row (hover highlight) is clipped before the zoom.
  // HOW (after two hard AVs proved Interceptor.attach at the tail kills the process even with a
  // no-op callback -- the shrink detour+resume cluster is UNTOUCHABLE, known hazard): retarget
  // the thunk's tail `push 0x607e85` imm32 at a Frida-built stub -- a 4-byte DATA write, no code
  // rewriting, the project's own call_target_redirect pattern. Stub (pushfd/pushad bracketed;
  // the baked thunk already clobbers flags before resuming, so this is extra-safe): if
  // g_btn_pending==1 && g>16 && (parent[esi+0xC4]==TutWin || esi==TutWin+0xA5C):
  //   nativeH = (|g_btn_origH|*16 + g/2) / g   (ROUND -- the half_down inverse)
  //   -> g_btn_nativeH and [esi+0x4C8] = -nativeH.  Always exits push 0x607e85; ret.
  // W unchanged (round==floor for all observed). TutWin-gated: v6.4 unGated crashed the MainWin
  // HUD buttons' bracket-compose consumers (AV @0x45ab2c) -- THE BAKE MUST GATE TOO.
  (function installL8() {
    if (!VA(0x00400000).equals(ptr(0x00400000))) { log("[L8 stub ] base relocated -> SKIP"); return; }
    const tail = VA(0x00A0C46E);                 // thunk_btn_shrink+0x6E
    const want = [0x68, 0x85, 0x7E, 0x60, 0x00, 0xC3];
    for (let i = 0; i < 6; i++) {
      if (tail.add(i).readU8() !== want[i]) { log("[L8 stub ] tail bytes mismatch -> SKIP"); return; }
    }
    const hex =
      "9C" + "60" +                      // pushfd / pushad
      "833D34C5A00001" +                 // cmp [g_btn_pending 0xA0C534],1
      "7541" +                           // jne done
      "8B0D40876600" +                   // mov ecx,[g_popup_scale_num 0x668740]
      "83F910" +                         // cmp ecx,16
      "7E36" +                           // jle done
      "8B86C4000000" +                   // mov eax,[esi+0xC4]        (parent)
      "3D686E8C00" +                     // cmp eax,0x8C6E68          (TutWin)
      "7408" +                           // je ok
      "81FEC4788C00" +                   // cmp esi,0x8C78C4          (TutWin+0xA5C embedded btn)
      "7521" +                           // jne done
      "A13CC5A000" +                     // ok: mov eax,[g_btn_origH 0xA0C53C]
      "F7D8" +                           // neg eax
      "C1E004" +                         // shl eax,4
      "8BD1" +                           // mov edx,ecx
      "D1EA" +                           // shr edx,1                 (g/2)
      "03C2" +                           // add eax,edx
      "33D2" +                           // xor edx,edx
      "F7F1" +                           // div ecx                   (rounded)
      "A344C5A000" +                     // mov [g_btn_nativeH 0xA0C544],eax
      "F7D8" +                           // neg eax
      "8986C8040000" +                   // mov [esi+0x4C8],eax       (shrunk canvas H, negative)
      "61" + "9D" +                      // popad / popfd
      "68857E6000" +                     // push 0x607e85             (original resume)
      "C3";                              // ret
    const bytes = [];
    for (let i = 0; i < hex.length; i += 2) bytes.push(parseInt(hex.substr(i, 2), 16));
    try {
      const stub = Memory.alloc(Process.pageSize);
      stub.writeByteArray(bytes);
      Memory.protect(stub, Process.pageSize, "rwx");
      globalThis._tutwin_l8stub = stub;        // retain: Memory.alloc frees on GC
      tail.add(1).writeU32(stub.toUInt32());   // retarget the push imm32
      log("[L8 stub ] tail push retargeted -> " + stub + " (rounded nativeH, TutWin-gated)");
    } catch (e) {
      log("[L8 stub ] install failed -> SKIP: " + e);
    }
  })();

  // draw primitives into the TutWin button canvas during its content draw
  let l8logs = 0;
  Interceptor.attach(VA(0x005E3203), {   // Buffer_box_2(self, rect, color_h, color_v) -- ring outline
    onEnter() {
      if (curBtnCanvas === NULL || !this.context.ecx.equals(curBtnCanvas)) return;
      if (l8logs++ > 40) return;
      const sp = this.context.esp;
      const rc = ptr(u32(arg(sp, 1)));
      log("[box2    ] ret=" + this.returnAddress + " rect=[" + rc.readS32() + "," + rc.add(4).readS32() +
          "," + rc.add(8).readS32() + "," + rc.add(12).readS32() + "] cH=" + u32(arg(sp, 2)).toString(16) +
          " cV=" + u32(arg(sp, 3)).toString(16) +
          " canvasWH=" + safe32(curBtn.add(0x4c4)) + "x" + safe32(curBtn.add(0x4c8)));
    }
  });
  Interceptor.attach(VA(0x005E1A80), {   // Buffer_hline_2(self, x0, x1, y, color)
    onEnter() {
      if (curBtnCanvas === NULL || !this.context.ecx.equals(curBtnCanvas)) return;
      if (l8logs++ > 40) return;
      const sp = this.context.esp;
      log("[hline   ] ret=" + this.returnAddress + " x0=" + argS(sp, 1) + " x1=" + argS(sp, 2) +
          " y=" + argS(sp, 3) + " c=" + u32(arg(sp, 4)).toString(16) +
          " canvasWH=" + safe32(curBtn.add(0x4c4)) + "x" + safe32(curBtn.add(0x4c8)));
    }
  });

  // ---- L3: pointer-line thickness ----------------------------------------------------------
  // v6.7: Win_window_line_raw DECOMPILED (CreatePenIndirect wrapper): arg7 = lopnWidth.x (PEN
  // WIDTH -- the thickness lever), arg8 = lopnStyle (GDI pen style; native 2 = PS_DOT). v1..v6.6
  // scaled BOTH 2->5 and style 5 = PS_NULL = INVISIBLE PEN -- the line never drew in any patched
  // run (the blink masked it in screenshots). Scale ONLY the width; never touch the style.
  const l3seen = new Set();
  Interceptor.attach(A_LINE_RAW, {
    onEnter() {
      const ra = this.returnAddress;
      if (ra.compare(TUT_LO) < 0 || ra.compare(TUT_HI) >= 0) return;
      const g = gval();
      if (g <= 16) return;
      const sp = this.context.esp;
      const p7 = sp.add(0x18);                 // pen width ([esp+0x1c] = pen STYLE, hands off)
      const v7 = p7.readS32();
      if (v7 > 0 && v7 <= NATIVE_LINE_TH) p7.writeS32(SL.scalePx(v7, g));   // LAW 1
      const key = ra.toString() + "|" + v7;
      if (!l3seen.has(key)) {
        l3seen.add(key);
        log("[L3 line ] ret=" + ra + " width " + v7 + " -> " + SL.scalePx(v7, g) +
            " style=" + sp.add(0x1c).readS32() + " (g=" + g + ")");
      }
    }
  });

  // ---- L5: backdrop = scaled ornate art + feed the pf-align stash --------------------------
  // The 0x405f77 backdrop site routes to devfill for every popup; for TutWin the params are the
  // ornate set. Let devfill paint its synth (harmless, covered next), then in onLeave:
  //   (1) draw the ornate 9-slice through baked thunk_box_thick_hollow (frame9 band-map enlarge,
  //       key-9 flat) over the rect RE-EXPANDED by Delta (the site pre-insets by Delta expecting
  //       box_thick's outward grow; hollow is flat since 469118f6) -> scaled art, full window.
  //   (2) write g_title_left/right = scale_px(13,g)+/-Delta so the DOWNSTREAM baked chain
  //       (frame_align d528 / union_align d5a0 / textfollow) computes TutWin's body chrome at
  //       full g from a FRESH stash. Chain relations then give ring L = scale_px(13,g), field
  //       L = ring L + ps3 -- the vanilla relation (16 = 13 + ps3(16)=3) at scale.
  //   Stash persistence is the same class as the pre-existing staleness (every titled popup
  //   re-stashes at its own title draw); the bake will do this at the site, gated per-popup.
  Interceptor.attach(A_DEVFILL, {
    onEnter() {
      this.doOrnate = false;
      if (!tutAlive()) return;
      if (!this.context.ecx.equals(TUTWIN.add(0x444))) return;
      const g = gval();
      if (g <= 16) return;
      const sp = this.context.esp;
      if (u32(arg(sp, 2)) !== ORNATE_SET.toUInt32()) return;
      this.rect = ptr(u32(arg(sp, 1)));
      this.g = g;
      this.doOrnate = true;
    },
    onLeave() {
      if (!this.doOrnate) return;
      const g = this.g, D = pfDelta(g);
      const W = safe32(TUTWIN.add(0x4c4));
      // (2) fresh stash for the downstream body-chrome chain
      const tl = SL.scalePx(NATIVE_RING_L, g) + D;
      const tr = W - SL.scalePx(NATIVE_RING_L, g) - D;
      G_TITLE_LEFT.writeS32(tl);
      G_TITLE_RIGHT.writeS32(tr);
      // (1) scaled ornate art over the synth. The site rect IS the full window (inclusive) --
      // pass it UNCHANGED (v5's Delta expansion clipped +/-3px off-canvas -> asymmetric channel).
      const L = this.rect.readS32(), T = this.rect.add(4).readS32();
      const R = this.rect.add(8).readS32(), B = this.rect.add(12).readS32();
      const rc = Memory.alloc(16);
      rc.writeS32(L); rc.add(4).writeS32(T);
      rc.add(8).writeS32(R); rc.add(12).writeS32(B);
      hollow_9slice(TUTWIN.add(0x444), rc, ORNATE_SET);
      log("[L5 ornat] art rect [" + L + "," + T + "," + R + "," + B + "] (unchanged)" +
          " stash TL=" + tl + " TR=" + tr + " (g=" + g + ")");
    }
  });

  // ---- L6: content top [0x30e8] -- scale post-calc, grow boxH by the same delta ------------
  // TutWin's [+0x21b8]=0, so thunk_scale_header's titled-only copy never scales the content top;
  // BasePop_calc leaves [0x30e8]=27 (vanilla). Text Y reads it at draw; field/ring T are fixed
  // pf-chain offsets below it -- so ONE scaled write moves the whole top group. boxH [0x30c0]
  // was computed WITH the native 27, so grow it by the same delta (the box accommodates the
  // drop; window height derives from boxH at show time). Gate on the native range = double-
  // scale guard (each Popup_start recomputes 30e8 fresh).
  Interceptor.attach(VA(0x00603800), {   // BasePop_calculate_dimensions (attach proven by v0 probe)
    onEnter() {
      this.pop = this.context.ecx;
    },
    onLeave() {
      if (!this.pop.equals(TUTWIN)) return;
      const g = gval();
      if (g <= 16) return;
      const v = safe32(this.pop.add(0x30e8));
      if (v === null || v <= 0 || v > 32) return;         // native-range gate
      const nv = SL.scalePx(v, g);                        // LAW 1
      const delta = nv - v;
      this.pop.add(0x30e8).writeS32(nv);
      const bh = safe32(this.pop.add(0x30c0));
      this.pop.add(0x30c0).writeS32(bh + delta);
      log("[L6 ctop ] content top " + v + " -> " + nv + " boxH " + bh + " -> " + (bh + delta));
    }
  });

  Interceptor.attach(A_TUT_WIN, {
    onEnter() {
      const sp = this.context.esp;
      this.tut = this.context.ecx;
      log("[tut_win ] ENTER label='" + (function (p) { try { return p.readCString(); } catch (e) { return "?"; } })(ptr(u32(arg(sp, 2)))) + "' g=" + gval());
    },
    onLeave() {
      const t = this.tut;
      log("[tut_win ] LEAVE boxW=" + safe32(t.add(0x30bc)) + " boxH=" + safe32(t.add(0x30c0)) +
          " contentH=" + safe32(t.add(0x30d4)) +
          " winrect=[" + safe32(t.add(0x13c)) + "," + safe32(t.add(0x140)) + "," +
          safe32(t.add(0x144)) + "," + safe32(t.add(0x148)) + "]" +
          " canvasWH=" + safe32(t.add(0x4c4)) + "x" + safe32(t.add(0x4c8)) +
          " hdr30e8=" + safe32(t.add(0x30e8)) +
          " d528L=" + safe32(G_D528_LEFT) +
          " marg=[" + safe32(t.add(0x21b0)) + "," + safe32(t.add(0x21b4)) + "]" +
          " a14=" + safe32(t.add(0xa14)) + " art2144=" + safe32(t.add(0x2144)));
    }
  });

  // ---- L7: body text X -- the textfollow relation, applied directly for TutWin -------------
  // Contract at the cave entry (E8-entered from 0x604df5): [esp]=ret, [esp+4]=str, [esp+8]=X,
  // [esp+0xc]=Y, [esp+0x10]=width; esi=popup. X = scale_px(13,g) + 2*ps3 == g_d528_left + ps3
  // with the fresh stash (field L = scale_px(13,g)+ps3). Idempotent absolute write.
  let l7logs = 0;
  Interceptor.attach(A_TEXTMARGIN, {
    onEnter() {
      if (!this.context.esi.equals(TUTWIN)) return;
      const g = gval();
      if (g <= 16) return;
      const sp = this.context.esp;
      const oldX = sp.add(8).readS32();
      const nx = SL.scalePx(NATIVE_RING_L, g) + 2 * pfPs3(g);
      sp.add(8).writeS32(nx);
      if (l7logs++ < 6) {
        log("[L7 text ] X " + oldX + " -> " + nx + " Y=" + sp.add(0xc).readS32() +
            " wrapW=" + sp.add(0x10).readS32() + " a14=" + safe32(this.context.esi.add(0xa14)) +
            " art=" + safe32(this.context.esi.add(0x2144)) + " d528L=" + safe32(G_D528_LEFT));
      }
    }
  });

  // ==== CHROME OBSERVERS (no writes) ========================================================
  const SETS = {
    "0x78d690": "d690_backdrop", "0x78d5a0": "d5a0_ring", "0x78d618": "d618_title",
    "0x78d528": "d528_body_field", "0x6846b0": "picker_ornate", "0xa0cec0": "devfill_scratch",
  };
  const bsEntry = VA(0x005E2DD3);
  const bsPatched = bsEntry.readU8() === 0xE8;
  const bsAttach = bsPatched ? VA(0x00A11740) : bsEntry;
  const bsSeen = new Set();
  Interceptor.attach(bsAttach, {
    onEnter(args) {
      if (!tutAlive()) return;
      let from, rect, par;
      if (bsPatched) { from = args[0]; rect = args[1]; par = args[2]; }
      else { from = this.returnAddress; rect = args[0]; par = args[1]; }
      const dest = this.context.ecx;
      if (!dest.equals(TUTWIN.add(0x444))) return;        // TutWin's own canvas only
      let L, T, R, B, pv;
      try {
        L = rect.readS32(); T = rect.add(4).readS32();
        R = rect.add(8).readS32(); B = rect.add(12).readS32();
        pv = "0x" + par.toUInt32().toString(16);
      } catch (e) { return; }
      const k = pv + "|" + L + "," + T + "," + R + "," + B;
      if (bsSeen.has(k)) return;
      bsSeen.add(k);
      log("[chrome  ] set=" + (SETS[pv] || pv) + " from=" + from +
          " L=" + L + " T=" + T + " R=" + R + " B=" + B + " g=" + gval());
    }
  });

  Interceptor.attach(A_POPUP_SHOW, {
    onEnter() {
      if (this.context.ecx.equals(TUTWIN)) log("[show    ] Popup_show(TutWin) fired");
    }
  });

  log("v6.7 armed: v6.6 levers + L3 FIX: scale pen WIDTH only (arg8 = PS_ style; 5=PS_NULL was " +
      "erasing the line) + probes (box_sprite " + (bsPatched ? "cave" : "native") + " attach)");
}
