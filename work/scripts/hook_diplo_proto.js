// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.
// SUPERSEDED by patch group diplo_talk_scale (work\scripts\assemble_diplo.py: the baked t_dp_* / t_cr_*
// thunks in pcave2; laws in scaling_laws.py "DIPLOMACY talk screen"). Its h1 = K-1 far-edge trim
// (LEVER_FILL / LEVER_TITLE / LEVER_RIGHT_FLUSH / LEVER_MEASURE and v9d LEVER_ROWRECT) is superseded too
// (2026-10-17): the speech box by scaling_laws.diplo_far_edge_trim (h1 = 1 at every g > 16; thunks
// t_dp_fill, t_dp_title_outer/_inner/_text, t_dp_textblock, t_dp_wrapwidth), the type-16 option rows by
// scaling_laws.t16_item_draw_rect (t_dp_itemrect v2).

"use strict";
// ===========================================================================
// hook_diplo_proto.js -- DIPLOMACY speech-box scaling PROTOTYPE (levers) + observe.
// v1: scales the ANCHOR (DiploTalkWin 0x733990) and the anchored popup's chrome
// so the speech box becomes vanilla x g/16.  Console-strip content is NOT touched
// yet (next sub-arc).  Laws (all vanilla x g/16, gate g>16):
//   A  anchor:  W'=fl(700g/16) H'=fl(450g/16); pos x=((SW-W')+fl(0x20g/16))/2,
//               y=SH-strip'-H'  (strip' = g_console_strip_height, already scaled)
//               (DiploTalkWin_init 0x440700 literals 0x2BC/0x1C2/0x20)
//   F  popup fill/frame rect (Popup_on_draw_background diplo branch @0x405CD5):
//               {clipL+fl(0x17g/16), clipT, clipR-fl(0x37g/16), clipB+fl(5g/16)}
//   T  title bars @0x405D53..: outer {L+fl(0x1Bg/16), T+fl(4g/16), R-fl(0x3Bg/16), T+fl(0x1Cg/16)}
//               inner = outer inset fl(3g/16)
//   X  text-block frame @0x405E36..: the -3/-7 native insets -> fl(3g/16)/fl(7g/16)
//   H  header reserve [+0x21B8] 0x26 -> fl(0x26 g/16) at BasePop_calc entry (anchored branch skips the scaler)
//   G  button band [+0x30D0] 20 -> fl(20g/16) at calc-leave + g-swap over the creation window so
//               thunk_grow_box adds 0 (box stays == anchor) and thunk_btnh_create does not re-scale
//   B  type-16 row width: anchored rows == field width (device) -> q16_fill_width takes its
//               native arm (g-swap around the E8-entered thunk 0xA1D000)
// Attach hosts (all hazard-audited): unpatched function entries + the two proven
// cave entries (0xA11740 box_sprite detour target, 0xA1D000 q16_fill_width E8-entered; NB thunk_scale_boxw
// 0xA16F00 is a push;ret target = NOT hookable).  v5 adds entries 0x6132A0 Dialog_dims_dispatch, 0x405050
// Popup_on_adjust_button_placement, 0x5DC360 Buffer_wrap_height, 0x5DCAB0 Buffer_text_line_height (push;ret
// arrivals from BAKED sites only) and the E8-entered cave entry 0x668BD0 thunk_content_frame.  No call-site hooks.
// ===========================================================================
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_diplo_proto.log";
log("=== hook_diplo_proto.js v10 (strip content) ===");
installAVHandler("diplo_proto");

const LEVER_ANCHOR = true, LEVER_FILL = true, LEVER_TITLE = true, LEVER_XFRAME = true, LEVER_BOXW = true, LEVER_HDR = true, LEVER_BAND = true, LEVER_MEASURE = true;
// v5 levers: W anchored box_w native arm (g-swap over thunk_scale_boxw), Y OK-row bottom offset -0x1e -> -fl(30g/16),
//            C art column [+0x30D8] +30E4 native -> +fl(30E4 g/16), K frame strokes via the baked thick thunks
//            (title d5a0/d618 -> thunk_box_thick, backdrop d690 + text-block d528 -> thunk_box_thick_devfill,
//            final union d5a0 -> the shared 0x406238 chain with the +-3 nest scaled at thunk_content_frame entry)
const LEVER_BOXW_ANCH = true, LEVER_OKY = true, LEVER_ARTCOL = true, LEVER_THICK = true;
// v6: P portrait at (title-outer drawn stroke right edge, 30E8 - fl(6g/16)) via the [popup+0x3168] art fn
//     (its -5/-6 are native; pristine portrait x = 30F0-5 = 28 = title outer L 27 + 1 -> "flush");
//     R the text-block pair's RIGHT edges = title pair's DRAWN edges (title thickener grows outward by
//     frameGrowDelta, body thickeners draw flat): d528'.R = (cR - fl(0x3Bg/16)) - fl(3g/16) + delta.
const LEVER_ART_XY = true, LEVER_RIGHT_FLUSH = true;
// v7 (channel + stroke verification, pixel-measured against refs\pristine\Diplomacy\Opening.png):
//     the engine's rects are HALF-OPEN (right/bottom stroke drawn at R-1/B-1) and the baked thickeners map them
//     as: thunk_box_thick (title)  L/T stroke = [E-delta, E-delta+K-1], R/B stroke = [E-1+delta, E-1+delta+K-1];
//         devfill (flat)           L/T stroke = [E, E+K-1],             R/B stroke = [E-1, E-1+K-1].
//     Vanilla drawn columns: backdrop 23 | 24-26 | title outer 27 | 28-29 | inner 30 ... 637 | 638-639 | 640 |
//     641-643 | 644 (fill R 645 excl); rows: 0 | 1-3 | 4 | 5-6 | 7 ... 24 | 25-26 | 27 | 28-31 | body outer 32 |
//     33-34 | body inner 35 | text 38.  Law: every DRAWN stroke lands at fl(vanilla_col*g/16), stroke = K:
//       title rect' = {L+delta, T+delta, R-delta-h1, B-delta-h1}   (h1 = K-1 = the scaled half-open pixel)
//       fill  rect' = {.., R-h1, ..};  body final.R = R-h1, d528'.R = final.R - fl(3g/16) (== title inner drawn)
//       body final.T = 30E8 - fl(6g/16) (vanilla 32 = 38-6), d528'.T = final.T + fl(3g/16)
//       portrait x = L + K (vanilla 28 = 27 + 1)          -- identity at g=16 for every line (delta=0, h1=0).
//     Result @4K: strokes 2px, channels backdrop->title 8 (7.5), title pair 5 (5), title->body 10 (10), body pair 5.
const LEVER_HALFOPEN = true;
// v9: Q anchored type-16 row gap (pitch law), E 30E4 field scaled (row-window y under the portrait).
const LEVER_Q16GAP = true, LEVER_E4 = true, LEVER_ROWRECT = true;

if (requireBase()) {
  const TW = 0x733990, TW_CANVAS = TW + 0x444, MW_CANVAS = 0x7AEC64;
  const G = 0x668740, SW = 0x9B7B1C, SH = 0x9B7B20, STRIP = 0x7AF59C, CUR_POP = 0x9B8D7C;
  const rd = (p, o) => { try { return ptr(p).add(o).readS32(); } catch (e) { return null; } };
  const rdu = (p, o) => { try { return ptr(p).add(o).readU32(); } catch (e) { return null; } };
  const wr = (p, o, v) => ptr(p).add(o).writeS32(v);
  const rs = (p) => { try { return ptr(p).readCString(); } catch (e) { return "<bad>"; } };
  const hex = (v) => "0x" + ((v >>> 0).toString(16));
  const gl = (a) => VA(a).readS32();
  const g = () => { try { return VA(G).readU32(); } catch (e) { return 16; } };
  const sc = (v) => Math.floor(v * g() / 16);          // vanilla x g/16, floor
  const h1 = (s) => SL.strokeWidth(s) - 1;   // v7: scaled half-open pixel (K-1); 0 at g<=23
  const rect = (p, o) => "{" + rd(p, o) + "," + rd(p, o + 4) + "," + rd(p, o + 8) + "," + rd(p, o + 12) + "}";
  const rectSz = (p, o) => rect(p, o) + "=" + (rd(p, o + 8) - rd(p, o)) + "x" + (rd(p, o + 12) - rd(p, o + 4));
  const talkOpen = () => rd(TW, 0xA94) !== -1;
  const env = () => "g=" + g() + " SW=" + gl(SW) + " SH=" + gl(SH) + " strip=" + gl(STRIP);
  const counts = {}, seen = {};
  let calcN = 0;   // v9c: BasePop_calc entry counter -> folded into the dedup key so per-popup lines repeat
  function L(tag, msg, limit) {
    limit = limit || 60; counts[tag] = counts[tag] || 0;
    const key = tag + "|" + calcN + "|" + msg; if (seen[key]) return;
    if (counts[tag] >= limit) { if (counts[tag] === limit) { log("[" + tag + "] ...limit"); counts[tag]++; } return; }
    seen[key] = 1; counts[tag]++; log("[" + tag + "] " + msg);
  }

  // ---- pending g-swap (anchored popup creation window) ------------------------------
  //  For anchored popups the box height is FIXED by the anchor: thunk_grow_box (+(scaled btnH - btnH))
  //  and thunk_btnh_create (re-scale of [+0x30D0] at the creation read) must take their native arms.
  //  Both are push;ret detour targets (unhookable), so: at BasePop_calc-leave set [+0x30D0]=sc(20)
  //  (the layout band, read for the button top-Y @0x602C49) and swap g_popup_scale_num->16 until the
  //  NEXT hook event of any kind (first draw/show after creation) or a 300ms safety timer.
  let gPending = false, gSaved = 40, gTimer = null;
  function swapG() { if (gPending) return; gSaved = g(); if (gSaved <= 16) return; VA(G).writeU32(16); gPending = true; gTimer = setTimeout(() => { if (gPending) { L("G", "timer restore"); unswapG(); } }, 300); }
  function unswapG() { if (!gPending) return; VA(G).writeU32(gSaved); gPending = false; if (gTimer) { clearTimeout(gTimer); gTimer = null; } }

  // engine calls (thiscall)
  const GraphicWin_resize = new NativeFunction(VA(0x005D5540), 'int', ['pointer', 'int', 'int', 'int'], 'thiscall');
  const Win_move          = new NativeFunction(VA(0x005ED7D0), 'int', ['pointer', 'int', 'int'], 'thiscall');
  const Buffer_sync_pal   = new NativeFunction(VA(0x005DE8F0), 'int', ['pointer', 'int'], 'thiscall');
  const GraphicWin_clear  = new NativeFunction(VA(0x005D5250), 'int', ['pointer', 'int'], 'thiscall');
  const Buffer_box_sprite = new NativeFunction(VA(0x005E2DD3), 'int', ['pointer', 'pointer', 'int'], 'thiscall');
  const rectMem = Memory.alloc(16); globalThis._diploRect = rectMem;
  // K: the baked frame-thickening thunks (drop-in Buffer_box_sprite contract: thiscall(dest; rect, params) RET 8)
  const thick_title   = new NativeFunction(VA(0x00668E00), 'int', ['pointer', 'pointer', 'int'], 'thiscall');  // thunk_box_thick (menu_strip +0xC00)
  const thick_devfill = new NativeFunction(VA(0x00A102A0), 'int', ['pointer', 'pointer', 'int'], 'thiscall');  // thunk_box_thick_devfill (pcave2 +0x42A0)
  const rectK = Memory.alloc(16); globalThis._diploRectK = rectK;
  const setRect = (m, l, t, rr, b) => { m.writeS32(l); m.add(4).writeS32(t); m.add(8).writeS32(rr); m.add(12).writeS32(b); };
  const rectVals = (m) => [m.readS32(), m.add(4).readS32(), m.add(8).readS32(), m.add(12).readS32()];
  const copyRect = (m, r) => { wr(r, 0, m.readS32()); wr(r, 4, m.add(4).readS32()); wr(r, 8, m.add(8).readS32()); wr(r, 12, m.add(12).readS32()); };
  let titleOuter = null, titleInner = null, d528Rect = null;
  function callThick(name, fn, dest, m, params) { try { fn(ptr(dest), m, params); L("K", name + " " + rectSz(m, 0), 40); } catch (e) { L("K", "EXC " + name + ": " + e); } }

  // ---- A: anchor law at DiploTalkWin_init exit ---------------------------------
  //  Each step is try/catch-logged: v1 lost the whole tail silently when a native call threw
  //  (resize took, move never happened -> box grew down-right from the native origin).
  //  Position is written straight into the Win screen rects (+0x13C main / +0x14C alt), the same
  //  fields Win_move rewrites (0x5ED82B..: relative delta on L/T/R/B); these windows are
  //  software-composited into the one HWND, so the rect IS the position.
  function step(name, fn) { try { fn(); L("A", "  ok " + name); } catch (e) { L("A", "  EXC " + name + ": " + e); } }
  Interceptor.attach(VA(0x00440700), { onLeave() {
    const s = g();
    L("A", "init exit " + env() + " before: w/h=" + rd(TW, 0x4C4) + "/" + rd(TW, 0x4C8) + " rect13C=" + rectSz(TW, 0x13C) + " rect14C=" + rectSz(TW, 0x14C) + " flags9c=" + hex(rdu(TW, 0x9c)) + " flags98=" + hex(rdu(TW, 0x98)));
    if (!LEVER_ANCHOR || s <= 16) return;
    const W = sc(700), H = sc(450);
    const x = Math.trunc(((gl(SW) - W) + sc(0x20)) / 2), y = gl(SH) - gl(STRIP) - H;
    step("resize", () => GraphicWin_resize(ptr(TW), W, H, 1));
    L("A", "  after resize: w/h=" + rd(TW, 0x4C4) + "/" + rd(TW, 0x4C8) + " rect13C=" + rectSz(TW, 0x13C) + " rect14C=" + rectSz(TW, 0x14C) + " clip=" + rectSz(TW, 0x474));
    step("Win_move(" + x + "," + y + ")", () => Win_move(ptr(TW), x, y));
    L("A", "  after move: rect13C=" + rectSz(TW, 0x13C) + " rect14C=" + rectSz(TW, 0x14C));
    if (rd(TW, 0x13C) !== x || rd(TW, 0x140) !== y) {
      step("direct rect write", () => { wr(TW, 0x13C, x); wr(TW, 0x140, y); wr(TW, 0x144, x + W); wr(TW, 0x148, y + H); });
      L("A", "  after direct: rect13C=" + rectSz(TW, 0x13C));
    }
    step("sync_pal", () => Buffer_sync_pal(ptr(TW_CANVAS), gl(0x9B8174)));
    step("clear9", () => GraphicWin_clear(ptr(TW), 9));
    step("frame", () => {
      rectMem.writeS32(rd(TW, 0x474) + sc(0x17)); rectMem.add(4).writeS32(rd(TW, 0x478));
      rectMem.add(8).writeS32(rd(TW, 0x47C) - sc(0x37)); rectMem.add(12).writeS32(rd(TW, 0x480));
      Buffer_box_sprite(ptr(TW_CANVAS), rectMem, 0x78D690);
    });
    L("A", "after: w/h=" + rd(TW, 0x4C4) + "/" + rd(TW, 0x4C8) + " clip=" + rectSz(TW, 0x474) + " screen=" + rectSz(TW, 0x13C) + " canvas w/h=" + rd(TW_CANVAS, 0x80) + "/" + rd(TW_CANVAS, 0x84) + " frame=" + rectSz(rectMem, 0));
  }});
  Interceptor.attach(VA(0x0043F2B0), {
    onEnter() { L("open", "ENTER faction=" + rd(this.context.esp, 4) + " " + env() + " TW w/h=" + rd(TW, 0x4C4) + "/" + rd(TW, 0x4C8) + " screen=" + rectSz(TW, 0x13C)); },
    onLeave() { L("open", "EXIT anchor globals win=" + hex(rdu(VA(0x9B8D04), 0)) + " w=" + gl(0x696EC4) + " h=" + gl(0x696EC8) + " btnrects DL=" + rectSz(TW, 0x2124) + " PR=" + rectSz(TW, 0x2134) + " HQ=" + rectSz(TW, 0x2144)); }
  });

  // ---- F: fill rect (GraphicWin_fill_2 0x5D5350 entry, ret 0x405D10, ecx==TW) ---
  Interceptor.attach(VA(0x005D5350), { onEnter() {
    unswapG();
    if ((this.context.ecx.toInt32() >>> 0) !== TW) return;
    if ((this.returnAddress.toInt32() >>> 0) !== 0x405D10) return;
    const r = rd(this.context.esp, 4), s = g();
    const before = rectSz(r, 0);
    if (LEVER_FILL && s > 16) {
      wr(r, 0, rd(TW, 0x474) + sc(0x17)); wr(r, 8, rd(TW, 0x47C) - sc(0x37) - h1(s)); wr(r, 12, rd(TW, 0x480) + sc(5));
    }
    L("F", "fill rect " + before + " -> " + rectSz(r, 0) + " clip=" + rectSz(TW, 0x474), 20);
  }});

  // ---- T/X: box_sprite draws on TW canvas keyed on site (0xA11740 = box_sprite detour target) ---
  Interceptor.attach(VA(0x00A11740), { onEnter() {
    unswapG();
    const d = this.context.ecx.toInt32() >>> 0;
    if (d !== TW_CANVAS) {
      if (talkOpen() && d !== MW_CANVAS) { const sp0 = this.context.esp; L("boxC", "dest=" + hex(d) + " site=" + hex(rdu(sp0, 4)) + " rect=" + rectSz(rd(sp0, 8), 0) + " set=" + hex(rd(sp0, 0xc)) + " bufWH=" + rd(d, 0x80) + "/" + rd(d, 0x84), 40); }
      return;
    }
    const sp = this.context.esp, site = rdu(sp, 4), r = rd(sp, 8), s = g();
    const before = rectSz(r, 0);
    if (s > 16) {
      const cL = rd(TW, 0x474), cT = rd(TW, 0x478), cR = rd(TW, 0x47C);
      const pop = this.context.esi.toInt32() >>> 0;             // Popup_on_draw_background's esi = popup (prologue not yet run)
      if (rdu(ptr(pop), 0xA14) !== TW) { L("box", "site=" + hex(site) + " esi not anchored popup " + hex(pop), 10); return; }
      // K: the engine's own (hairline) draw is parked on a 24x24 rect under the OK bar (composited over
      //    it later); the frame is drawn by the baked thick thunk on the scaled rect instead.
      const park = () => { if (!LEVER_THICK) return; const H = rd(TW, 0x480), x = rd(pop, 0x30F0) + 8, y = H - sc(30) - sc(20) + 8; wr(r, 0, x); wr(r, 4, y); wr(r, 8, x + 24); wr(r, 12, y + 24); };
      if (site === 0x405D3E) {                                   // d690 backdrop (rect = lever-F fill rect)
        if (LEVER_THICK) { setRect(rectK, rd(r, 0), rd(r, 4), rd(r, 8), rd(r, 12)); callThick("devfill:d690", thick_devfill, d, rectK, 0x78D690); park(); }
      }
      if (site === 0x405D96) {                                   // title outer d5a0
        if (LEVER_TITLE) { const D = SL.frameGrowDelta(s), h = h1(s); setRect(rectK, cL + sc(0x1B) + D, cT + sc(4) + D, cR - sc(0x3B) - D - h, cT + sc(0x1C) - D - h); titleOuter = rectVals(rectK);
          if (LEVER_THICK) { callThick("thick:d5a0", thick_title, d, rectK, 0x78D5A0); park(); } else copyRect(rectK, r); }
      }
      if (site === 0x405DCB) {                                   // title inner d618 = outer inset fl(3g/16)
        if (LEVER_TITLE && titleOuter) { const i = sc(3); setRect(rectK, titleOuter[0] + i, titleOuter[1] + i, titleOuter[2] - i, titleOuter[3] - i); titleInner = rectVals(rectK);
          if (LEVER_THICK) { callThick("thick:d618", thick_title, d, rectK, 0x78D618); park(); } else copyRect(rectK, r); }
      }
      if (site === 0x405E9A) {                                   // text-block d528: native -3/-3/-7 -> fl(3g/16)/fl(7g/16)
        if (LEVER_XFRAME) { const d3 = sc(3) - 3, d7 = sc(7) - 7;
          const rr = LEVER_RIGHT_FLUSH ? (cR - sc(0x3B)) - h1(s) - sc(3) : rd(r, 8) - d7;
          const tt = LEVER_HALFOPEN ? (rd(r, 4) + 3) - sc(6) + sc(3) : rd(r, 4) - d3;   // (r.T+3) == 30E8+30E0
          setRect(rectK, rd(r, 0) - d3, tt, rr, rd(r, 12) + d3); d528Rect = rectVals(rectK);
          if (LEVER_THICK) { callThick("devfill:d528", thick_devfill, d, rectK, 0x78D528); park(); } else copyRect(rectK, r); }
      }
    }
    L("box", "site=" + hex(site) + " " + before + " -> " + rectSz(r, 0) + " set=" + hex(rd(sp, 0xc)), 40);
  }});
  // ---- K tail: the final union d5a0 (diplo branch jmps into the SHARED 0x406238 site -> thunk_content_frame
  //      -> pf_union_align(a14 passthrough) -> d5a0_center -> thunk_box_thick_hollow).  The +-3 nest around
  //      the d528 rect is native (0x405EA6..0x405EB8) -> rewrite the rect to d528' +- fl(3g/16) at the
  //      chain head (thunk_content_frame entry 0x668BD0, E8-entered: [esp+4]=rect, esi=popup).
  Interceptor.attach(VA(0x00668BD0), { onEnter() {
    const p = this.context.esi.toInt32() >>> 0; if (rdu(ptr(p), 0xA14) !== TW || g() <= 16 || !d528Rect) return;
    const r = rd(this.context.esp, 4), before = rectSz(r, 0), i = sc(3);
    if (LEVER_THICK) { wr(r, 0, d528Rect[0] - i); wr(r, 4, d528Rect[1] - i); wr(r, 8, d528Rect[2] + i); wr(r, 12, d528Rect[3] + i); }
    L("Kf", "final d5a0 " + before + " -> " + rectSz(r, 0) + " (d528'=" + d528Rect.join(",") + ")", 30);
    d528Rect = null;
  }});

  // ---- B: anchored ROW-WIDTH arm.  thunk_q16_fill_width (pcave2 0x11000 = 0xA1D000, E8-called from
  //      Dialog_type16_attach @0x60D299, tail = push GraphicWin_init;ret) widens type-16 rows to
  //      max(w*g/16, box_w-2x) assuming w NATIVE.  For anchored popups w = ext_w' - margins' is ALREADY
  //      device-space (vanilla rows == w exactly), so the lawful arm is "leave w alone" == the thunk's
  //      g<=16 native path: swap g_popup_scale_num to 16 for the duration (restored in onLeave, which
  //      fires when the tail-called GraphicWin_init returns).  While the talk screen is open EVERY
  //      popup is anchored, so the gate is talkOpen().
  Interceptor.attach(VA(0x00A1D000), {
    onEnter() {
      unswapG();
      this.sw = false; const s = g(); if (!LEVER_BOXW || s <= 16 || !talkOpen()) return;
      const sp = this.context.esp;
      L("B", "q16_fill_width w(arg)=" + rd(sp, 0xc) + " count=" + rd(this.context.esi, 0x1f8) + " D+0x5c=" + rd(this.context.esi, 0x188) + " box=" + rd(this.context.esi, 0x478) + " -> native arm (g-swap)", 30);
      this.sw = true; this.g = s; VA(G).writeU32(16);
    },
    onLeave() { if (this.sw) VA(G).writeU32(this.g); }
  });

  // ---- v8 CENSUS (rows vertical): row-window GraphicWin_init args at the q16_fill_width entry, the
  //      q16_rowgap thunk (pitch/gap fields), Dialog_set_type (row-window y = g_popup_body_bottom + 30E4).
  Interceptor.attach(VA(0x00A1D000), { onEnter() {
    if (!talkOpen()) return; const sp = this.context.esp, e = this.context.esi;
    L("Rw", "row-window init x=" + rd(sp, 4) + " y=" + rd(sp, 8) + " w=" + rd(sp, 0xc) + " h=" + rd(sp, 0x10) + " D+0x60=" + rd(e, 0x18c) + " D+0x68=" + rd(e, 0x194) + " D+0x44=" + rd(e, 0x170) + " count=" + rd(e, 0x1f8), 30);
  }});
  // ---- v9b DIAG: crash 2026-08-15 at Buffer_wrap_height_flying entry (eip 0x5ddda0, ecx bad, str=0 width=0)
  //      right after the 2nd popup's [W] g-swap.  Log every entry while the talk screen is open: ecx, args,
  //      caller, popup+0xa3c (parent win = the ecx source at 0x603E36), and the popup fields the width uses.
  Interceptor.attach(VA(0x005DDDA0), { onEnter() {
    if (!talkOpen()) return;
    const sp = this.context.esp, ecx = this.context.ecx, p = rdu(VA(0x9B8CF4), 0);
    let ok = true; try { ecx.add(0x10).readS32(); } catch (e) { ok = false; }
    L("WH", "wrap_flying esi=" + this.context.esi + " ebx=" + this.context.ebx + " ecx=" + ecx + (ok ? "" : " (UNREADABLE)") + " str=" + hex(rdu(sp, 4)) + " w=" + rd(sp, 8) + " ret=" + hex(rdu(sp, 0)) + " pop=" + hex(p) + " a3c=" + hex(rdu(ptr(p), 0xa3c)) + " 30BC=" + rd(p, 0x30BC) + " 30D8=" + rd(p, 0x30D8) + " 21C8=" + rd(p, 0x21C8) + " 30E0=" + rd(p, 0x30E0) + " g=" + g() + " wSw=" + calc.wSw, 40);
  }});

  // ---- v9c DIAG: esi trail between dispatch#1 return and the wrap loop (crash = bogus esi at 0x603E36/0x603F3D).
  // (0x603D88 boxw-resume attach REMOVED: it is the pushed resume of a baked push;ret detour = hazard #5)
  for (const fa of [0x00609FA0, 0x0060A020, 0x006120B0, 0x006099D0]) {
    Interceptor.attach(VA(fa), {
      onEnter() { this.on = calc.inCalc; if (this.on) L("T", "type-arm call " + hex(fa) + " IN  ecx=" + this.context.ecx + " esi=" + this.context.esi + " a3c(esi)=" + hex(rdu(this.context.esi, 0xa3c)), 60); },
      onLeave() { if (this.on) L("T", "type-arm call " + hex(fa) + " OUT esi=" + this.context.esi + " a3c(esi)=" + hex(rdu(this.context.esi, 0xa3c)) + " ret=" + this.returnValue, 60); }
    });
  }
  Interceptor.attach(VA(0x006132A0), { onLeave() { if (calc.inCalc) L("T", "dispatch#" + calc.nDisp + " OUT esi=" + this.context.esi + " a3c(esi)=" + hex(rdu(this.context.esi, 0xa3c)) + " ret=" + this.returnValue, 60); } });
  // ---- v9 Q: the anchored/fixed-height type-16 arm (0x60d70e: flags bit0 && [D+0x30]!=0 -> [D+0x60]=[D+0x30],
  //      count=[D+0x30]/[D+0x68]) SKIPS Site B, so thunk_q16_rowgap never writes the gap and the rows draw on
  //      rowH+3 (53 @4K).  Same law as the baked thunk (scaling_laws.option_row_gap): pitch'=half_down(22g,16),
  //      [D+0x44]=max(0,pitch'-rowH); attach at 0x60d717 (eax=D, plain engine code, no branch target inside).
  //      v9c: the mid-function attach at 0x60d717 LEAKED a trampoline dword into esi (dispatch#1 OUT esi=0x2ee120f,
  //      hazard #6/#7 family) -> moved to the dispatch#1 onLeave below (D reachable from the popup, fixed arm
  //      detectable as [D+0x60]==[D+0x30]!=0; the fixed arm never touches [D+0x44] again, Site B is skipped).
  Interceptor.attach(VA(0x00A16740), {
    onEnter() { this.D = this.context.eax; this.on = talkOpen(); if (this.on) L("Rg", "q16_rowgap IN rowH=" + rd(this.D, 0x68) + " gap=" + rd(this.D, 0x44) + " count=" + rd(this.D, 0x58) + " g=" + g(), 30); },
    onLeave() { if (this.on) L("Rg", "q16_rowgap OUT pitch(ecx)=" + this.context.ecx.toInt32() + " gap=" + rd(this.D, 0x44), 30); }
  });
  Interceptor.attach(VA(0x00612970), { onEnter() {
    const p = rdu(VA(0x9B8CF4), 0); if (!p || rdu(ptr(p), 0xA14) !== TW) return;
    const sp = this.context.esp;
    L("Rt", "Dialog_set_type type=" + rd(sp, 4) + " x=" + rd(sp, 0xc) + " y=" + rd(sp, 0x10) + " body_bottom=" + rd(VA(0x9B8CE8), 0) + " 30D4=" + rd(p, 0x30D4) + " 30DC=" + rd(p, 0x30DC) + " 30E4=" + rd(p, 0x30E4) + " 30E8=" + rd(p, 0x30E8) + " 30B8=" + rd(p, 0x30B8) + " 30C4=" + rd(p, 0x30C4), 30);
  }});

  // ---- M: body-text MEASURE width.  Both flying wrap-height sites (0x603E42/0x603F3D) E8 into
  //      thunk_faction_wrapwidth (0xA12E00, entry `cmp ecx,imm32` 6B, esi=popup, [esp+8]=width) whose
  //      width came from thunk_scale_boxw's DOUBLE-scaled box_w for anchored popups (2 lines measured,
  //      4 drawn -> the text frame too short).  Proto law: width' = (W'-fl(0x37g/16)) - 30F0 - 30D8 - fl(14g/16)
  //      (native check: 645-33-135-14 = 463 ~ the measured 465-479 column).  Bake = anchored arm in boxw.
  Interceptor.attach(VA(0x00A12E00), { onEnter() {
    restoreW("wrapwidth");
    const p = this.context.esi.toInt32() >>> 0; if (rdu(ptr(p), 0xA14) !== TW || g() <= 16) return;
    const sp = this.context.esp, w0 = rd(sp, 8);
    let w1 = w0;
    if (LEVER_MEASURE) { w1 = ((rd(TW, 0x47C) - sc(0x3B)) - h1(g()) - sc(3)) - rd(p, 0x30F0) - rd(p, 0x30D8) - sc(5); wr(sp, 8, w1); }   // = d528'.R - text_x - fl(5g/16)  (vanilla 645-4-3-168-5 = 465 = box_w-30D8)
    L("M", "pop=" + hex(p) + " measure width " + w0 + " -> " + w1 + " (30F0=" + rd(p, 0x30F0) + " 30D8=" + rd(p, 0x30D8) + " 30BC=" + rd(p, 0x30BC) + ") '" + rs(rd(sp, 4)).slice(0, 30) + "'", 30);
  }});
  // ---- census: text colours + row/label writers while the talk screen is open ---------
  Interceptor.attach(VA(0x005DACB0), { onEnter() {           // Buffer_set_text_color(c, a3, a4, a5)
    if (!talkOpen()) return; const sp = this.context.esp;
    if (LEVER_THICK && LEVER_TITLE && titleInner && rdu(sp, 0) === 0x405E16 && g() > 16) {   // title text rect [ebp-0x14..] = d618' inset fl(3g/16) (engine's copy was parked)
      const bp = this.context.ebp, i = sc(3);
      bp.sub(0x14).writeS32(titleInner[0] + i); bp.sub(0x10).writeS32(titleInner[1] + i); bp.sub(0xC).writeS32(titleInner[2] - i); bp.sub(8).writeS32(titleInner[3] - i);
      L("Kt", "title text rect -> " + rectSz(bp.sub(0x14), 0), 30); titleInner = null;
    }
    L("color", "dest=" + hex(this.context.ecx.toInt32()) + " site=" + hex(rd(sp, 0)) + " c=" + rd(sp, 4) + "," + rd(sp, 8) + "," + rd(sp, 0xc) + "," + rd(sp, 0x10), 40);
  }});
  Interceptor.attach(VA(0x005DD920), { onEnter() {           // wrap_cent_4(str,x,y,w) - FlatButton/row label writer
    if (!talkOpen()) return; const sp = this.context.esp; const d = this.context.ecx.toInt32();
    L("lbl", "wrap_cent_4 dest=" + hex(d) + " site=" + hex(rd(sp, 0)) + " xy=" + rd(sp, 8) + "," + rd(sp, 0xc) + " w=" + rd(sp, 0x10) + " font=" + hex(rd(d, 0x52c)) + " color=" + rd(d, 0x53c) + " '" + rs(rd(sp, 4)).slice(0, 30) + "'", 40);
  }});
  Interceptor.attach(VA(0x005DD530), { onEnter() {           // Buffer_wrap_2 (node render)
    if (!talkOpen()) return; const sp = this.context.esp; const d = this.context.ecx.toInt32();
    L("lbl", "wrap_2 dest=" + hex(d) + " site=" + hex(rd(sp, 0)) + " a1=" + hex(rd(sp, 4)) + " a2=" + hex(rd(sp, 8)) + " font=" + hex(rd(d, 0x52c)) + " color=" + rd(d, 0x53c), 40);
  }});
  Interceptor.attach(VA(0x005DDAB0), { onEnter() {           // wrap_cent_6(str,rect)
    if (!talkOpen()) return; const sp = this.context.esp; const d = this.context.ecx.toInt32(); if ((d>>>0) === MW_CANVAS) return;
    L("lbl", "wrap_cent_6 dest=" + hex(d) + " site=" + hex(rd(sp, 0)) + " rect=" + rectSz(rd(sp, 8), 0) + " color=" + rd(d, 0x53c) + " '" + rs(rd(sp, 4)).slice(0, 30) + "'", 40);
  }});

  // ---- observe: popup dims + item rects ---------------------------------------
  // ---- W: anchored box_w NATIVE arm.  BasePop_calc @0x603D82 hands [+0x30BC] to thunk_scale_boxw
  //      (push;ret target, unhookable) which scales tw=d5c/xs x g/16 -- but for anchored popups xs = ext_w' -
  //      margins' is ALREADY device-space (1501 @4K), so box_w came out 3752 and the OK button (w=[+0x30CC]=box_w
  //      -2padx, created in exec_3) was 3752 wide with its label centred off-window.  Law = the thunk's own
  //      g<=16 native arm: swap g->16 from the FIRST Dialog_dims_dispatch return (the box_w store is next) until
  //      the first text-measure call (Buffer_wrap_height 0x5DC360 / Buffer_text_line_height 0x5DCAB0 /
  //      thunk_faction_wrapwidth 0xA12E00) or calc-leave.  Bake = an anchored arm in thunk_scale_boxw.
  // ---- C: art column [+0x30D8] = art_w' + [+0x30E4]: the +30E4 term is native (4) -> vanilla x g/16.
  const calc = { inCalc: false, p: 0, nDisp: 0, wSw: false, wG: 0 };
  // ---- P: popup art draw fn [popup+0x3168] (thunk_sprite_draw / thunk_popup_artalign wrapper; cdecl
  //      (sprite, font, dlgres, 0, x, y) -> draws at (x-5, y-6) native).  Popup ptr = [0x9B8CF4] (set just
  //      before the call @0x604C09).  Anchored & g>16: x = title-outer drawn stroke right edge
  //      ((cL+fl(0x1Bg/16)) - delta + K), y = 30E8 - fl(6g/16); +5/+6 pre-add for the thunk's native subtract.
  let artFnHooked = 0;
  function hookArtFn(fn) {
    if (!fn || artFnHooked === fn) return; artFnHooked = fn;
    L("P", "art fn [0x3168]=" + hex(fn) + " hooked");
    Interceptor.attach(ptr(fn), { onEnter() {
      const p = rdu(VA(0x9B8CF4), 0); if (!p || rdu(ptr(p), 0xA14) !== TW || g() <= 16) return;
      // cdecl 5 args (sprite, font, dlgres, x, y): the `push 0` before them feeds the RET-4 call 0x611640, so
      // at ENTRY x=[esp+0x10], y=[esp+0x14] (thunk reads them as [ebp+0x14]/[ebp+0x18] after push ebp).
      const sp = this.context.esp, s = g(), x0 = rd(sp, 0x10), y0 = rd(sp, 0x14);
      if (LEVER_ART_XY) {
        const cL = rd(TW, 0x474);
        const x = (cL + sc(0x1B)) + SL.strokeWidth(s);            // v7: title drawn stroke now AT L (rect pre-adds delta)
        const y = rd(p, 0x30E8) - sc(6);
        wr(sp, 0x10, x + 5); wr(sp, 0x14, y + 6);
      }
      L("P", "pop=" + hex(p) + " art xy (" + x0 + "," + y0 + ") -> (" + rd(sp, 0x10) + "," + rd(sp, 0x14) + ") -5/-6 => drawn (" + (rd(sp, 0x10) - 5) + "," + (rd(sp, 0x14) - 6) + ") 30F0=" + rd(p, 0x30F0) + " 30E8=" + rd(p, 0x30E8), 30);
    }});
  }
  function restoreW(where) { if (!calc.wSw) return; VA(G).writeU32(calc.wG); calc.wSw = false; L("W", "restore g=" + calc.wG + " at " + where, 30); }
  Interceptor.attach(VA(0x006132A0), {
    onEnter() {
      restoreW("dispatch-enter");
      if (!calc.inCalc) return; calc.nDisp++;
      if (calc.nDisp !== 1) return;
      const p = calc.p, e4 = rd(p, 0x30E4);
      if (LEVER_ARTCOL && g() > 16 && rd(p, 0x2144) && e4 > 0 && e4 <= 8) { const before = rd(p, 0x30D8); wr(p, 0x30D8, before - e4 + sc(e4)); L("C", "pop=" + hex(p) + " 30D8 " + before + " -> " + rd(p, 0x30D8) + " (30E4=" + e4 + " 21C4=" + rd(p, 0x21C4) + " 21C8=" + rd(p, 0x21C8) + " 30E0=" + rd(p, 0x30E0) + ")", 30); }
      // v9 E: the row-window y = g_popup_body_bottom (art bottom here) + 30E4 -> scale the FIELD (gated on its
      //       native value, idempotent; the OK-row/button-pitch consumers are (n-1)-weighted = 0 for one button).
      if (LEVER_E4 && g() > 16 && e4 > 0 && e4 <= 8) { wr(p, 0x30E4, sc(e4)); L("E", "pop=" + hex(p) + " 30E4 " + e4 + " -> " + rd(p, 0x30E4), 30); }
    },
    onLeave() {
      if (!calc.inCalc || calc.nDisp !== 1 || !LEVER_BOXW_ANCH) return;
      const s = g(); if (s <= 16) return;
      calc.wG = s; calc.wSw = true; VA(G).writeU32(16);
      const iv3 = rd(rd(calc.p, 0x21D0), 8);
      if (LEVER_Q16GAP && rd(calc.p, 0x2350) === 16) {
        const D = calc.p + 0x21D0 + rd(rd(calc.p, 0x21D0), 8), rowH = rd(D, 0x68), fixed = rd(D, 0x30);
        if (rowH > 0 && fixed > 0 && rd(D, 0x60) === fixed) {
          const pitch = Math.floor((44 * s + 15) / 32), gap = Math.max(0, pitch - rowH), before = rd(D, 0x44);
          wr(D, 0x44, gap);
          L("Q", "anchored q16 arm (at dispatch#1 OUT) rowH=" + rowH + " gap " + before + " -> " + gap + " (pitch' " + pitch + ") fixedH=" + fixed, 30);
        }
      }
      L("W", "esi=" + this.context.esi + " ebx=" + this.context.ebx + " pop=" + hex(calc.p) + " g-swap 16 over the box_w store (xs=" + rd(calc.p, iv3 + 0x21FC) + " d5c=" + rd(calc.p, iv3 + 0x222C) + ")", 30);
    }
  });
  Interceptor.attach(VA(0x005DC360), { onEnter() { restoreW("wrap_height"); } });
  Interceptor.attach(VA(0x005DCAB0), { onEnter() { restoreW("line_height"); } });
  // ---- Y: OK-row placement.  Popup_on_adjust_button_placement 0x405050 (vtbl+0x178, thiscall(&x,&y,&z))
  //      writes y = -0x1e for anchored popups (bottom-relative: OK top = box_h - 30 - band).  Native 30 -> fl(30g/16).
  //      Also the point where the G g-swap must END: exec_3's window init (grow_box) is behind us, the
  //      [+0x30D0] creation read (btnh_create 20->50) is next.
  Interceptor.attach(VA(0x00405050), {
    onEnter() { unswapG(); this.p = this.context.ecx.toInt32() >>> 0; this.py = rd(this.context.esp, 8); },
    onLeave() {
      const p = this.p; if (rdu(ptr(p), 0xA14) !== TW || g() <= 16 || !this.py) return;
      const y0 = rd(this.py, 0);
      if (LEVER_OKY && y0 === -0x1e) wr(this.py, 0, -sc(30));
      L("Y", "pop=" + hex(p) + " OK y " + y0 + " -> " + rd(this.py, 0) + " band30D0=" + rd(p, 0x30D0) + " boxWH=" + rd(p, 0x30BC) + "x" + rd(p, 0x30C0) + " btnW30CC=" + rd(p, 0x30CC), 30);
    }
  });
  Interceptor.attach(VA(0x00603800), {
    onEnter() {
      unswapG();
      const p = this.p = this.context.ecx.toInt32() >>> 0; if (rdu(ptr(p), 0xA14) !== TW || g() <= 16) return;
      calc.inCalc = true; calc.p = p; calc.nDisp = 0; calcN++;
      L("calc", "#" + calcN + " BasePop_calc enter pop=" + hex(p) + " a3c=" + hex(rdu(ptr(p), 0xa3c)) + " 30E4=" + rd(p, 0x30E4) + " 30D8=" + rd(p, 0x30D8) + " 21C4=" + rd(p, 0x21C4), 60);
      hookArtFn(rdu(ptr(p), 0x3168));
      // H: header reserve [+0x21B8] (=0x26 titled / 0x12 untitled, NATIVE — the anchored branch @0x60391A
      //    skips BasePop_calc.header_reserve_scale) -> vanilla x g/16 (gate on the native value)
      if (LEVER_HDR && (rd(p, 0x21B8) === 0x26 || rd(p, 0x21B8) === 0x12)) { const v = rd(p, 0x21B8); wr(p, 0x21B8, sc(v)); L("H", "pop=" + hex(p) + " hdr " + v + " -> " + sc(v)); }
    },
    onLeave() {
      const p = this.p; if (rdu(ptr(p), 0xA14) !== TW) return;
      restoreW("calc-leave");
      calc.inCalc = false;
      // v5: NO 30D0 write here -- the band stays native 20 through exec_3's window init (thunk_grow_box adds
      //     sc(20)-20 only when g>16 -> the g-swap makes it 0) and thunk_btnh_create scales it 20->50 at the
      //     creation read 0x602D3B AFTER 0x405050 (lever Y) restores g.  (v4 wrote 50 here and btnh_create
      //     re-scaled it to 125 -> OK window 125 tall, bar 75px too high.)
      if (LEVER_BAND && g() > 16 && rd(p, 0x30D0) === 20) { L("G", "pop=" + hex(p) + " band 30D0 stays 20; g-swap over the window-init (grow_box native arm)"); swapG(); }
      const iv3 = rd(rd(p, 0x21D0), 8);
      L("pcalc", "pop=" + hex(p) + " type=" + rd(p, 0x2350) + " anchor wh=" + rd(p, 0xA20) + "x" + rd(p, 0xA24) + " margins L/R/hdr/top=" + rd(p, 0x21B0) + "/" + rd(p, 0x21B4) + "/" + rd(p, 0x21B8) + "/" + rd(p, 0x21BC) +
        " xs=" + rd(p, iv3 + 0x21FC) + " d5c=" + rd(p, iv3 + 0x222C) + " boxWH=" + rd(p, 0x30BC) + "x" + rd(p, 0x30C0) + " 30D4/D8=" + rd(p, 0x30D4) + "/" + rd(p, 0x30D8) + " art=" + (rd(p, 0x2144) ? rd(rd(p, 0x2144), 0x18) + "x" + rd(rd(p, 0x2144), 0x1c) : "0") + " ratio=" + rd(p, 0x3104) + "/" + rd(p, 0x3108) + " title=" + (rd(p, 0xA48) ? "'" + rs(rd(p, 0xA48)) + "'" : "0"));
    }
  });
  Interceptor.attach(VA(0x00404920), { onEnter() {
    unswapG();
    const p = this.context.ecx.toInt32() >>> 0; if (rdu(ptr(p), 0xA14) !== TW) return;
    L("pshow", "pop=" + hex(p) + " win w/h=" + rd(p, 0x4C4) + "/" + rd(p, 0x4C8) + " clip=" + rectSz(p, 0x474) + " TWscreen=" + rectSz(TW, 0x13C), 30);
  }});
  Interceptor.attach(VA(0x00405B20), { onEnter() {
    unswapG();
    const p = this.context.ecx.toInt32() >>> 0; if (rdu(ptr(p), 0xA14) !== TW) return;
    const sp = this.context.esp;
    // v9d R: the row cell draws through the flat thickener whose R/B stroke is [E-1, E-1+K-1] -> the drawn
    //        cell is (K-1) taller/wider than its half-open rect (4K: 51x1497 for a 50x1496 rect, gap 4 not 5).
    //        Law: drawn == rect -> pre-shrink right/bottom by K-1 (0 at g<=22, identity at g=16).
    if (LEVER_ROWRECT && g() > 16) { const r = rd(sp, 0x10), k1 = SL.strokeWidth(g()) - 1; if (k1 > 0) { wr(r, 8, rd(r, 8) - k1); wr(r, 12, rd(r, 12) - k1); } }
    L("pitem", "pop=" + hex(p) + " buf=" + hex(rd(sp, 4)) + " a3=" + rd(sp, 8) + " idx=" + rd(sp, 0xc) + " rect=" + rectSz(rd(sp, 0x10), 0) + " diploCols=" + gl(0x8C6E5C) + "/" + gl(0x8C6E60) + " normCols=" + gl(0x8C6C9C) + "/" + gl(0x8C6CA0) + " pop3120..=" + rd(p,0x3120) + "," + rd(p,0x3124) + "," + rd(p,0x3128) + "," + rd(p,0x312c), 40);
  }});
  Interceptor.attach(VA(0x00406380), { onEnter() { unswapG(); if (talkOpen()) L("pstart", rs(rd(this.context.esp, 8)) + " ret=" + hex(rd(this.context.esp, 0)), 30); } });
  // text writers on the popup canvas (wrap widths / line pitch)
  const popCanvas = () => { const p = VA(CUR_POP).readU32(); return p ? (p + 0x444) >>> 0 : 0; };
  Interceptor.attach(VA(0x005DCF40), { onEnter() { unswapG(); if ((this.context.ecx.toInt32() >>> 0) !== popCanvas() || !talkOpen()) return; const sp = this.context.esp; L("txt", "write_l_4 site=" + hex(rd(sp, 0)) + " rect=" + rectSz(rd(sp, 8), 0) + " '" + rs(rd(sp, 4)).slice(0, 40) + "'"); } });
  Interceptor.attach(VA(0x005DD730), { onEnter() { unswapG(); if ((this.context.ecx.toInt32() >>> 0) !== popCanvas() || !talkOpen()) return; const sp = this.context.esp; L("txt", "wrap_3 site=" + hex(rd(sp, 0)) + " xy=" + rd(sp, 8) + "," + rd(sp, 0xc) + " w=" + rd(sp, 0x10) + " '" + rs(rd(sp, 4)).slice(0, 40) + "'"); } });

  // =====================================================================================
  // *** v10 STATUS (2026-08-18): STRIP LAWS VALIDATED (4K 233222 / 1600 233253 + bezel run) -- DO NOT RE-RUN FOR THE STRIP.
  //   The Sprite_draw_2 / write_cent_l_7 arg rewrites have NO clean Frida host: their entries are baked push;ret detours
  //   whose thunks key on the RETURN ADDRESS -- an attach at the cave HEAD (v10a/b) killed the COMMLINK Council face; an
  //   attach at the CALL insn (v10c) relocates the E8 so the thunk sees a trampoline ret (header text 'ÿ5', sprites gone).
  //   Prototype-only artifact: the BAKE uses call-target redirects (E8 -> adapter -> jmp native, [esp] preserved) + cuts.
  // =====================================================================================
  // v10: CONSOLE-STRIP CONTENT (DiploTalkWin's own painters onto the MainWin canvas).
  //  Laws (all vanilla x g/16, gate g>16; native insets in the rect table + painters are the
  //  MIXED-SPACE class: MainWin seeds are already device-scaled, the +-1/2/3/4/6/0x14/0x16/0x17
  //  constants and the 10/12/14 font sizes and the 1:1 sprite/flic draws were native):
  //   N  fonts +0xA1C/+0xA44/+0xA6C re-inited at fl(10/12/14 g/16) (Font_init frees the old HFONT)
  //   Rt rect table 0x20C4..0x2144 recomputed from the seeds with sc() insets (cumulative anchors
  //      where vanilla chains constants: hdr B = D80.T+fl(24g/16), body T = D80.T+fl(26g/16),
  //      centre = DC0 inset fl(7g/16), centre.B = DC0.B-fl(30g/16)); the 3 BaseButton_init x,y,w,h
  //      args rewritten from the fixed table (attach at the BaseButton_init cave entry 0xA0D090,
  //      gated on the 3 diplo call sites; the table is final there)
  //   Pc painter constants at the primitive entries (ret-address gated): box_sprite rects
  //      (0xA11740), write_cent_l_7 rects (0xA11FA0 cave head), wrap_cent_6 / wrap_3 / write_l_3 /
  //      hline_2 / get_pixel x,y,w, Sprite_draw_2 x,y + num/den=g/16 (0xA12330 cave head)
  //   Fl the two flics (news +0xAE8, bioscan +0x15CC): Flic_init x,y scaled (bio literals 26,90 ->
  //      sc; news = panel.L+sc(1), panel.T+sc(1)+H/4); Flic_draw_frame dst-bounce into a native
  //      scratch + copy_3 stretch x g/16 (thunk_band_draw law; unconditional stretch)
  //   Bz the 3 FlatButtons (DATALINKS/PROFILE/HQINFO) enter the shrink/2D-zoom frame pipeline via
  //      thunk_btn_gate (0xA169E0) -> frames zoom, labels draw at device with the scaled +0xA6C
  // =====================================================================================
  const LEVER_STRIP_FONTS = true, LEVER_STRIP_RECTS = true, LEVER_STRIP_PAINT = true, LEVER_STRIP_FLIC = true, LEVER_STRIP_BTNZOOM = true;
  const MW = 0x7AE820;
  const gv = () => (gPending ? gSaved : g());
  const scv = (v) => { const s = gv(); return s > 16 ? Math.floor(v * s / 16) : v; };
  const S = { NEWS: TW + 0xAE8, BIO: TW + 0x15CC, BTN: [TW + 0x2158, TW + 0x2CA4, TW + 0x37F0] };
  const seeds = () => ({ D80: rectVals(VA(MW + 0xD80)), D90: rectVals(VA(MW + 0xD90)), DB0: rectVals(VA(MW + 0xDB0)), DC0: rectVals(VA(MW + 0xDC0)), A8C: rectVals(VA(MW + 0xA8C)), A9C: rectVals(VA(MW + 0xA9C)) });
  const wrRect = (p, o, r) => { wr(p, o, r[0]); wr(p, o + 4, r[1]); wr(p, o + 8, r[2]); wr(p, o + 12, r[3]); };
  const rdRect = (p, o) => [rd(p, o), rd(p, o + 4), rd(p, o + 8), rd(p, o + 12)];
  const rstr = (r) => "{" + r.join(",") + "}=" + (r[2] - r[0]) + "x" + (r[3] - r[1]);
  const Font_init = new NativeFunction(VA(0x00618F40), 'int', ['pointer', 'pointer', 'int', 'int'], 'thiscall');
  const HUD_FONT_NAME = 0x691B2C;
  let stripFixed = false, flcW = 0, cfN = 0;

  // ---- N + Rt: at the FIRST BaseButton_init of DiploTalkWin_init (rects + fonts are final there) ----
  function fixStripTable() {
    const s = gv(); if (s <= 16) return;
    const e = seeds();
    const s3 = scv(3), s4 = scv(4), s6 = scv(6), s20 = scv(20), s7 = scv(7);
    if (LEVER_STRIP_FONTS) {
      const name = VA(HUD_FONT_NAME).readPointer();
      try {
        Font_init(ptr(TW + 0xA1C), name, scv(10), 0); Font_init(ptr(TW + 0xA44), name, scv(12), 0); Font_init(ptr(TW + 0xA6C), name, scv(14), 1);
        L("N", "fonts -> " + scv(10) + "/" + scv(12) + "/" + scv(14) + "b  A6C cell=" + rd(TW + 0xA6C, 0xc) + " asc=" + rd(TW + 0xA6C, 0x18));
      } catch (ex) { L("N", "EXC " + ex); }
    }
    if (!LEVER_STRIP_RECTS) return;
    // news panel width carries the faction.flc width: vanilla 20E4 = {D80.R-4-flcW-2, D80.T+4, D80.R-4, D80.B-4}
    const n0 = rdRect(TW, 0x20E4); flcW = (n0[2] - n0[0]) - 2;
    const D80 = e.D80, D90 = e.D90, DC0 = e.DC0, DB0 = e.DB0, A8C = e.A8C, A9C = e.A9C;
    const hq2144 = [D90[2] - A9C[2] + D90[0], A8C[1], A8C[0] - s3, A8C[3]];
    const hq2114 = [D90[0] + s4, D90[1] + s4, D90[2] - s4, hq2144[1] - s6];
    const r2104 = [DB0[0] + s4, DB0[1] + s4, DB0[2] - s4, DB0[3] - s4];
    const c = [DC0[0] + s7, DC0[1] + s7, DC0[2] - s7, DC0[3] - s7];           // centre after 4+3 (cumulative)
    const W = c[2] - c[0], hh = Math.trunc((W + s3) / 2);
    const dl2124 = [c[0], c[3] - s20, c[0] + hh - s3, c[3]];
    const pr2134 = [c[0] + hh, c[3] - s20, c[0] + hh - s3 + hh, c[3]];
    const c20F4 = [c[0], c[1], c[2], DC0[3] - scv(30)];                       // B -= 0x14+3 -> DC0.B - fl(30g/16) cumulative
    const nw2 = [D80[2] - s4 - scv(flcW + 2), D80[1] + s4, D80[2] - s4, D80[3] - s4];
    const bh20C4 = [D80[0] + s4, D80[1] + s4, nw2[0] - s3, D80[1] + scv(24)];
    const bb20D4 = [D80[0] + s4, D80[1] + scv(26), nw2[0] - s3, D80[3] - s4];
    L("Rt", "before: 20C4=" + rstr(rdRect(TW, 0x20C4)) + " 20D4=" + rstr(rdRect(TW, 0x20D4)) + " 20E4=" + rstr(n0) + " 20F4=" + rstr(rdRect(TW, 0x20F4)) + " 2114=" + rstr(rdRect(TW, 0x2114)) + " 2124=" + rstr(rdRect(TW, 0x2124)) + " 2134=" + rstr(rdRect(TW, 0x2134)) + " 2144=" + rstr(rdRect(TW, 0x2144)) + " flcW=" + flcW);
    wrRect(TW, 0x20C4, bh20C4); wrRect(TW, 0x20D4, bb20D4); wrRect(TW, 0x20E4, nw2); wrRect(TW, 0x20F4, c20F4); wrRect(TW, 0x2104, r2104);
    wrRect(TW, 0x2114, hq2114); wrRect(TW, 0x2124, dl2124); wrRect(TW, 0x2134, pr2134); wrRect(TW, 0x2144, hq2144);
    L("Rt", "after:  20C4=" + rstr(bh20C4) + " 20D4=" + rstr(bb20D4) + " 20E4=" + rstr(nw2) + " 20F4=" + rstr(c20F4) + " 2114=" + rstr(hq2114) + " 2124=" + rstr(dl2124) + " 2134=" + rstr(pr2134) + " 2144=" + rstr(hq2144) + " flcW'=" + scv(flcW));
    stripFixed = true;
  }
  // BaseButton_init cave entry (0x607210 -> push 0xA0D090; ret): [esp]=ret, +4 label, +8 id, +C x, +10 y, +14 w, +18 h
  Interceptor.attach(VA(0x00A0D090), { onEnter() {
    const ret = rdu(this.context.esp, 0);
    const which = ret === 0x440BDE ? 0x2124 : ret === 0x440C23 ? 0x2144 : ret === 0x440C99 ? 0x2134 : 0;
    if (!which) return;
    if (ret === 0x440BDE) fixStripTable();
    if (!stripFixed) return;
    const r = rdRect(TW, which), sp = this.context.esp;
    L("Bt", "BaseButton_init site=" + hex(ret) + " args " + rd(sp, 0xC) + "," + rd(sp, 0x10) + " " + rd(sp, 0x14) + "x" + rd(sp, 0x18) + " -> " + rstr(r));
    wr(sp, 0xC, r[0]); wr(sp, 0x10, r[1]); wr(sp, 0x14, r[2] - r[0]); wr(sp, 0x18, r[3] - r[1]);
  }});

  // ---- Pc: painter constants at the primitives (dest == MainWin canvas, ret-address gated) ----
  const fontH = (f) => { const p = rd(f, 0); return p < 0 ? rd(f, 0xC) : rd(f, 0x10) + p; };   // engine's line-height idiom
  const sprW = (sp) => rd(sp, 0x18), sprH = (sp) => rd(sp, 0x1C);
  const stripSt = { panelIdx: 0, panelRect: null, yFix: 0, yRet: 0, logoW: 0, sepY: 0, newsY: 0 };
  const onMW = (ctx) => LEVER_STRIP_PAINT && (ctx.ecx.toInt32() >>> 0) === MW_CANVAS && gv() > 16 && stripFixed;
  // box_sprite via its detour target (ecx=dest, [esp+4]=ret, [esp+8]=rect*, [esp+C]=set)
  Interceptor.attach(VA(0x00A11740), { onEnter() {
    if (!onMW(this.context)) return;
    const sp = this.context.esp, ret = rdu(sp, 4), r = rd(sp, 8), e = seeds();
    const s3 = scv(3), s4 = scv(4);
    let nr = null;
    if (ret === 0x4402F8) { const D = e.DC0; nr = [D[0] + s4, D[1] + s4, D[2] - s4, D[3] - s4]; }                    // draw_strip centre frame d5a0
    else if (ret === 0x440357) { const A = e.A8C, B = e.A9C, H = rdRect(TW, 0x2144);                                    // draw_strip HQ-button union frame d870
      nr = [Math.min(A[0], B[0], H[0]) - s3, Math.min(A[1], B[1], H[1]) - s3, Math.max(A[2], B[2], H[2]) + s3, Math.max(A[3], B[3], H[3]) + s3]; }
    else if (ret === 0x43FB0F) {                                                                                         // status panel i (local_24 split)
      const c = rdRect(TW, 0x20F4), W = c[2] - c[0], hh = Math.trunc((W + s3) / 2), i = (rd(r, 0) === c[0]) ? 0 : 1;
      nr = [c[0] + i * hh, c[1], c[0] + i * hh + hh - s3, c[3]]; stripSt.panelRect = nr; stripSt.yFix = 0; }
    else if (ret === 0x44010D) { const h = rdRect(TW, 0x2114); nr = [h[0], h[1], h[2], h[3] - s4]; }                     // HQ panel B-4
    if (nr) { L("Pc", "box site=" + hex(ret) + " " + rstr(rdRect(r, 0)) + " -> " + rstr(nr), 40); wrRect(r, 0, nr); }
  }});
  // write_cent_l_7 at its two CALL instructions (onEnter-only at a call insn = proven-safe host, lever P precedent;
  // the cave head 0xA11FA0 is a baked push;ret cluster -- NOT hooked). At the call: [esp]=str, +4=rect*, +8=len.
  function cent7Fix(ctx, site) {
    if (!onMW(ctx)) return;
    const sp = ctx.esp, r = rd(sp, 4);
    const s1 = scv(1), s3 = scv(3), s20 = scv(20);
    let nr = null;
    if (site === 0x43F6D8) { const h = rdRect(TW, 0x20C4); nr = [h[0] + s3, h[1] + s3, h[2] - s3, h[3] - s3]; }          // BIOSCAN header text
    else if (site === 0x440233) { const h = rdRect(TW, 0x2114); nr = [h[0] + s1, h[1] + s1, h[2] - s1, h[1] + s1 + s20]; } // HQ name header
    if (nr) { L("Pc", "cent7 site=" + hex(site) + " " + rstr(rdRect(r, 0)) + " -> " + rstr(nr) + " '" + rs(rd(sp, 0)).slice(0, 24) + "'", 40); wrRect(r, 0, nr); }
  }
  Interceptor.attach(VA(0x0043F6D8), { onEnter() { cent7Fix(this.context, 0x43F6D8); } });
  Interceptor.attach(VA(0x00440233), { onEnter() { cent7Fix(this.context, 0x440233); } });
  // Sprite_draw_2 at its CALL instructions (the chain head 0xA12330 is a baked push;ret cluster whose council-face
  // branch keys on [esp] -- a Frida trampoline there soft-killed the COMMLINK Council face even onEnter-only; NOT hooked).
  // At the call: ecx=sprite, [esp]=dest, +4=key, +8=x, +C=y, +10=num, +14=den.
  function sd2Fix(ctx, site) {
    if (!LEVER_STRIP_PAINT || gv() <= 16 || !stripFixed) return;
    const sp = ctx.esp;
    if (rdu(sp, 0) !== MW_CANVAS) return;
    const spr = ctx.ecx.toInt32() >>> 0, w = sprW(spr), h = sprH(spr), wd = scv(w), hd = scv(h), s = gv();
    const s1 = scv(1), s3 = scv(3), s20 = scv(20);
    let x = rd(sp, 8), y = rd(sp, 0xC);
    const ox = x, oy = y;
    if (site === 0x45D8E9) {                                                                                                // slide_show diplo tail: centre-console BEZEL art
      L("Pc", "bezel sprite " + hex(spr) + " " + w + "x" + h + " @" + x + "," + y + " num/den " + rd(sp, 0x10) + "/" + rd(sp, 0x14) + " -> x" + s + "/16", 10);
      if (rd(sp, 0x10) === 1 && rd(sp, 0x14) === 1) { wr(sp, 0x10, s); wr(sp, 0x14, 16); }
      return; }
    if (site === 0x43F778) { const b = rdRect(TW, 0x20D4); x = b[2] - 2 * wd; y = b[1] + Math.trunc(((b[3] - b[1]) - hd) / 2); }          // BIOSCAN colour bar
    else if (site === 0x43FBFB) { const p = stripSt.panelRect; stripSt.logoW = wd; if (p) { x = p[0] + s3; y = p[1] + s3 + fontH(TW + 0xA6C) + s3; } }   // faction logo
    else if (site === 0x440277) { const h2 = rdRect(TW, 0x2114); const L0 = h2[0] + s1, R0 = h2[2] - s1; x = L0 + Math.trunc(((R0 - L0) - wd) / 2); y = h2[1] + s1 + s20 + s1; }  // HQ base picture
    wr(sp, 8, x); wr(sp, 0xC, y); wr(sp, 0x10, s); wr(sp, 0x14, 16);
    L("Pc", "sprite site=" + hex(site) + " " + w + "x" + h + " @" + ox + "," + oy + " -> @" + x + "," + y + " x" + s + "/16 (" + wd + "x" + hd + ")", 40);
  }
  for (const site of [0x43F778, 0x43FBFB, 0x440277, 0x45D8E9]) Interceptor.attach(VA(site), { onEnter() { sd2Fix(this.context, site); } });
  // wrap_cent_6 0x5DDAB0 (str, rect*): faction name over the logo -> {L+s3, T+s3+s2, R-s3, T+s3+fontH}; returns bottom y
  Interceptor.attach(VA(0x005DDAB0), {
    onEnter() {
      this.fix = false;
      if (!onMW(this.context)) return;
      const sp = this.context.esp, ret = rdu(sp, 0); if (ret !== 0x43FCA7) return;
      const p = stripSt.panelRect; if (!p) return;
      const s2 = scv(2), s3 = scv(3), r = rd(sp, 8), nr = [p[0] + s3, p[1] + s3 + s2, p[2] - s3, p[1] + s3 + fontH(TW + 0xA6C)];
      L("Pc", "cent6 name " + rstr(rdRect(r, 0)) + " -> " + rstr(nr) + " '" + rs(rd(sp, 4)).slice(0, 20) + "'", 40); wrRect(r, 0, nr); this.fix = true;
    },
    onLeave(rv) { if (!this.fix) return; stripSt.yRet = rv.toInt32(); stripSt.yFix = 1; }
  });
  // status text lines: wrap_3 0x5DD730 (str,x,y,w) and write_l_3 0x5DCEA0 (str,x,y,len)
  //  vanilla after cent6: L' = L+3 + 2 + logo.w ; text x = L'+3 ; first y = ret+3 ; wrap w = (R-3-3) - x
  function statusXY(sp, hasW) {
    const p = stripSt.panelRect; if (!p) return;
    const s2 = scv(2), s3 = scv(3);
    const x = p[0] + s3 + s2 + (stripSt.logoW || 0) + s3, y0 = stripSt.yRet + s3;
    const ox = rd(sp, 8), oy = rd(sp, 0xC);
    wr(sp, 8, x);
    if (stripSt.yFix) { wr(sp, 0xC, y0); stripSt.yFix = 0; }
    if (hasW) wr(sp, 0x10, (p[2] - s3 - s3) - x);
    L("Pc", (hasW ? "wrap3 " : "wl3 ") + "@" + ox + "," + oy + " -> @" + x + "," + rd(sp, 0xC) + (hasW ? " w=" + rd(sp, 0x10) : "") + " '" + rs(rd(sp, 4)).slice(0, 20) + "'", 60);
  }
  Interceptor.attach(VA(0x005DD730), { onEnter() {
    if (!onMW(this.context)) return;
    const sp = this.context.esp, ret = rdu(sp, 0);
    if (ret === 0x43FE0C || ret === 0x43FE9C) statusXY(sp, true);
  }});
  Interceptor.attach(VA(0x005DCEA0), { onEnter() {
    if (!onMW(this.context)) return;
    const sp = this.context.esp, ret = rdu(sp, 0);
    if (ret === 0x43FF58 || ret === 0x43FFCC) { statusXY(sp, false); return; }   // Energy: line, "Might: " label (the value @0x440051 continues at the label's returned x -- untouched)
    // news panel text (name / REPUTATION / MOOD): x = L+fl(5g/16), first y = sep_y + s4 (clipped off-strip when scaled, as vanilla)
    if (ret === 0x43F8D6 || ret === 0x43F9BF || ret === 0x43FA87) {
      const n = rdRect(TW, 0x20E4);
      wr(sp, 8, n[0] + scv(5));
      // y chain mirrors vanilla's own y variable (not the writer's return): y1 = sep+4, y2 = y1 + fontH(A6C), y3 = y2 + fontH(A44)
      if (ret === 0x43F8D6) stripSt.newsY = stripSt.sepY + scv(4);
      else if (ret === 0x43F9BF) stripSt.newsY += fontH(TW + 0xA6C);
      else stripSt.newsY += fontH(TW + 0xA44);
      wr(sp, 0xC, stripSt.newsY);
      L("Pc", "news text site=" + hex(ret) + " -> @" + rd(sp, 8) + "," + rd(sp, 0xC), 20);
    }
  }});
  // news separator: get_pixel 0x5E2210 (x,y) ret 0x43F806 ; hline_2 0x5E1A80 (x0,x1,y,color) ret 0x43F81D
  Interceptor.attach(VA(0x005E2210), { onEnter() {
    if (!onMW(this.context)) return;
    const sp = this.context.esp; if (rdu(sp, 0) !== 0x43F806) return;
    const n = rdRect(TW, 0x20E4), sh = sprH(rd(TW, 0x20B4)), y = n[1] + scv(1) + scv(sh);
    stripSt.sepY = y; wr(sp, 4, n[0]); wr(sp, 8, y);
    L("Pc", "news sep y -> " + y + " (sprH " + sh + ")", 10);
  }});
  Interceptor.attach(VA(0x005E1A80), { onEnter() {
    if (!onMW(this.context)) return;
    const sp = this.context.esp; if (rdu(sp, 0) !== 0x43F81D) return;
    const n = rdRect(TW, 0x20E4), s1 = scv(1);
    wr(sp, 4, n[0] + s1); wr(sp, 8, n[2] - s1); wr(sp, 0xC, stripSt.sepY);
  }});

  // ---- Fl: the two flics ----
  const callCopy3 = new NativeFunction(VA(0x5D9610), 'void', ['pointer', 'pointer', 'int', 'int', 'int', 'int', 'int', 'int', 'int', 'int'], 'thiscall');
  const callMalloc = new NativeFunction(VA(0x64558A), 'pointer', ['uint'], 'mscdecl');
  const callBufCtor = new NativeFunction(VA(0x5D7210), 'void', ['pointer'], 'thiscall');
  const callBufResize = new NativeFunction(VA(0x5D79C0), 'void', ['pointer', 'int', 'int'], 'thiscall');
  const flicScratch = {};
  function ensureScratch(key, w, h) {
    let p = flicScratch[key];
    if (!p) { p = callMalloc(0x588); if (p.isNull()) return null; callBufCtor(p); callBufResize(p, w, h); flicScratch[key] = p; L("Fl", "scratch " + key + " " + w + "x" + h + " @" + p); }
    callBufResize(p, w, h);
    return p;
  }
  // Flic_init 0x629E50 thiscall(this; dst, name, x, y, flag) RET 0x14
  Interceptor.attach(VA(0x00629E50), { onEnter() {
    if (!LEVER_STRIP_FLIC || gv() <= 16) return;
    const fl = this.context.ecx.toInt32() >>> 0; if (fl !== S.NEWS && fl !== S.BIO) return;
    const sp = this.context.esp, ox = rd(sp, 0xC), oy = rd(sp, 0x10);
    let x = ox, y = oy;
    if (fl === S.BIO) { x = scv(ox); y = scv(oy); }
    else { const n = rdRect(TW, 0x20E4); x = n[0] + scv(1); y = n[1] + scv(1) + ((n[3] - n[1]) >> 2); }
    wr(sp, 0xC, x); wr(sp, 0x10, y);
    L("Fl", "Flic_init " + (fl === S.BIO ? "bio" : "news") + " '" + rs(rd(sp, 8)) + "' @" + ox + "," + oy + " -> @" + x + "," + y + " flag=" + rd(sp, 0x14), 20);
  }});
  const flicDraw = {
    onEnter() {
      this.doS = false;
      if (!LEVER_STRIP_FLIC) return;
      const fl = this.context.ecx.toInt32() >>> 0; if (fl !== S.NEWS && fl !== S.BIO) return;
      const s = gv(); if (s <= 16) return;
      const w = rd(fl, 0x59C), h = rd(fl, 0x5A0);
      if (w <= 0 || h <= 0 || w > 1024 || h > 1024) return;
      const scr = ensureScratch(fl === S.BIO ? "bio" : "news", w, h); if (!scr) return;
      const sp = this.context.esp;
      this.rx = rd(sp, 4); this.ry = rd(sp, 8);
      this.dstp = ptr(fl).add(0x5A8); this.oldDst = this.dstp.readPointer();
      this.dstp.writePointer(scr); wr(sp, 4, 0); wr(sp, 8, 0);
      this.doS = true; this.s = s; this.w = w; this.h = h; this.fl = fl; this.scr = scr;
    },
    onLeave(rv) {
      if (!this.doS) return;
      this.dstp.writePointer(this.oldDst);
      const fl = ptr(this.fl);
      fl.add(0x5AC).writeS32(this.rx); fl.add(0x5B0).writeS32(this.ry);
      const W = Math.floor(this.w * this.s / 16), H = Math.floor(this.h * this.s / 16);
      callCopy3(this.scr, this.oldDst, 0, 0, this.w, this.h, this.rx, this.ry, W, H);
      fl.add(0x58C).writeS32(this.rx); fl.add(0x590).writeS32(this.ry); fl.add(0x594).writeS32(this.rx + W); fl.add(0x598).writeS32(this.ry + H);
      L("Fl", "draw " + (this.fl === S.BIO ? "bio" : "news") + " @" + this.rx + "," + this.ry + " " + this.w + "x" + this.h + " -> " + W + "x" + H + " rv=" + rv.toInt32(), 12);
    }
  };
  Interceptor.attach(VA(0x0062A070), flicDraw);
  Interceptor.attach(VA(0x0062A120), flicDraw);

  // ---- Bz: thunk_btn_gate (0xA169E0, E8-called from thunk_btn_shrink; esi=button) -> YES for the 3 diplo FlatButtons ----
  Interceptor.attach(VA(0x00A169E0), {
    onEnter() { this.hit = LEVER_STRIP_BTNZOOM && S.BTN.indexOf(this.context.esi.toInt32() >>> 0) >= 0; },
    onLeave(rv) { if (this.hit) { L("Bz", "btn_gate YES for " + hex(this.context.esi.toInt32()) + " (was " + rv.toInt32() + ")", 6); rv.replace(1); } }
  });
  log("v10 strip levers: FONTS=" + LEVER_STRIP_FONTS + " RECTS=" + LEVER_STRIP_RECTS + " PAINT=" + LEVER_STRIP_PAINT + " FLIC=" + LEVER_STRIP_FLIC + " BTNZOOM=" + LEVER_STRIP_BTNZOOM);

  log("levers: ANCHOR=" + LEVER_ANCHOR + " FILL=" + LEVER_FILL + " TITLE=" + LEVER_TITLE + " XFRAME=" + LEVER_XFRAME + " BOXW=" + LEVER_BOXW + " -- open COMMLINK, talk, click through; screenshot at 4K + 1600.");
}
