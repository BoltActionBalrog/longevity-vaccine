"use strict";
// hook_tutwin.js -- OBSERVER-ONLY probe: tutorial / directional-tooltip window (TutWin) scaling levers.
//
// Proves (one run, crash-land tooltip at new-game start):
//   Q1  the tooltip is TutWin_tut_map/tut_win -> Popup_start("TUTOR") -> BasePop_calculate_dimensions,
//       and our boxw lever widens [popup+0x30bc] while the popups_tutorial fonts stay native.
//   Q2  which fonts popups_tutorial installs (g_text_font_v0/v1/v2 cell heights).
//   Q3  g_popup_active is 1 during the initial FlatButton draw (inside exec_3) but 0 on hover
//       redraws after tut_win returns -> our shrink/zoom pipeline stops firing -> clipped buttons.
//   Q4  the pointer line: Win_window_line_raw endpoints + the (2,2) thickness args.
//
// No writes. Run on the PATCHED exe (cave globals are read with a guard so a pristine run won't crash).

globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_tutwin.log";
log("=== hook_tutwin.js started ===");
installAVHandler("tutwin");

if (requireBase()) {
  const A_TUT_WIN        = VA(0x004BDFE0);  // TutWin_tut_win (thiscall)
  const A_TUT_MAP        = VA(0x004BE650);  // TutWin_tut_map (thiscall)
  const A_DRAW_ARROW     = VA(0x004BDEA0);  // TutWin_draw_arrow (fastcall)
  const A_POPUPS_TUT     = VA(0x005888E0);  // popups_tutorial
  const A_POPUPS_NORM    = VA(0x00588460);  // popups_normal
  const A_BASEPOP_CALC   = VA(0x00603800);  // BasePop_calculate_dimensions (this=ecx)
  const A_FLATBTN_DRAW   = VA(0x00607E50);  // FlatButton_content_draw entry (thunk_btn_shrink detour is at +0x2F -- do NOT attach there)
  // WARNING: uimod.dll (winlines.cpp) byte-checks and detours this entry when display modes are bound; attaching here in
  // spawn mode makes the window-line overlay disable itself for the run (memory feedback-frida-hook-vs-dll-bytecheck).
  const A_LINE_RAW       = VA(0x005F2AC0);  // Win_window_line_raw (thiscall; x,y,x2,y2,color,a7,a8)

  const G_SCREEN_W       = VA(0x009B7B1C);
  const G_SCREEN_H       = VA(0x009B7B20);
  const G_POPUP_SCALE    = VA(0x00668740);  // g_popup_scale_num (menu_strip_thunks+0x540); patched exe only
  const G_POPUP_ACTIVE   = VA(0x00A0C530);  // g_popup_active (pcave2+0x530); patched exe only
  const G_TEXT_FONT_V0   = VA(0x00945770);
  const G_TEXT_FONT_V1   = VA(0x009457FC);
  const G_TEXT_FONT_V2   = VA(0x009457F8);

  // TutWin static VA range: retaddr gate for Win_window_line_raw
  const TUT_LO = VA(0x004BA000), TUT_HI = VA(0x004BF000);

  const t0 = Date.now();
  function ts() { return "t+" + (Date.now() - t0) + "ms"; }
  function safe32(p) { try { return p.readS32(); } catch (e) { return null; } }
  function g()      { const v = safe32(G_POPUP_SCALE);  return v === null ? "n/a" : v; }
  function active() { const v = safe32(G_POPUP_ACTIVE); return v === null ? "n/a" : v; }
  function cstr(p)  { try { return p.isNull() ? "<null>" : p.readCString(); } catch (e) { return "<bad>"; } }
  function fontInfo(fp) {
    // Font: +0x0C cell_height, +0x10 glyph_height
    if (fp === null || fp === 0) return "font=NULL";
    const p = ptr(fp >>> 0);
    const ch = safe32(p.add(0x0c)), gh = safe32(p.add(0x10));
    return "font=" + p + " cellH=" + ch + " glyphH=" + gh;
  }

  let inTut = false;

  // ---- Q1/Q4: the two TutWin entries -------------------------------------------------
  Interceptor.attach(A_TUT_MAP, {
    onEnter() {
      const sp = this.context.esp;
      log("[tut_map ] " + ts() + " this=" + this.context.ecx +
          " label='" + cstr(arg(sp, 1) ? ptr(u32(arg(sp, 1))) : NULL) + "'" +
          " tile=(" + argS(sp, 2) + "," + argS(sp, 3) + ") a5=" + argS(sp, 4) +
          " spr=" + ptr(u32(arg(sp, 5))) + " a7=" + argS(sp, 6) +
          " tile2=(" + argS(sp, 7) + "," + argS(sp, 8) + ")");
    }
  });

  Interceptor.attach(A_TUT_WIN, {
    onEnter() {
      const sp = this.context.esp;
      this.tut = this.context.ecx;
      inTut = true;
      log("[tut_win ] " + ts() + " ENTER this=" + this.tut +
          " anchor=" + ptr(u32(arg(sp, 1))) +
          " label='" + cstr(ptr(u32(arg(sp, 2)))) + "'" +
          " xy=(" + argS(sp, 3) + "," + argS(sp, 4) + ") flags=0x" + u32(arg(sp, 6)).toString(16) +
          " xy2=(" + argS(sp, 7) + "," + argS(sp, 8) + ")" +
          " SW=" + safe32(G_SCREEN_W) + " SH=" + safe32(G_SCREEN_H) +
          " g=" + g() + " active=" + active());
    },
    onLeave() {
      const t = this.tut;
      log("[tut_win ] " + ts() + " LEAVE boxW[+30bc]=" + safe32(t.add(0x30bc)) +
          " boxH[+30c0]=" + safe32(t.add(0x30c0)) +
          " btnH[+30d0]=" + safe32(t.add(0x30d0)) +
          " contentH[+30d4]=" + safe32(t.add(0x30d4)) +
          " dlgFont[+a3c]={" + fontInfo(safe32(t.add(0xa3c))) + "}" +
          " bodyFont[+3110]={" + fontInfo(safe32(t.add(0x3110))) + "}" +
          " arrow from=(" + safe32(t.add(0x538c)) + "," + safe32(t.add(0x5390)) + ")" +
          " to=(" + safe32(t.add(0x5384)) + "," + safe32(t.add(0x5388)) + ")" +
          " armed=" + safe32(t.add(0x53a4)) +
          " active=" + active() + "  <-- window stays up non-modally after this");
    }
  });

  // ---- Q2: the two style configurators ------------------------------------------------
  Interceptor.attach(A_POPUPS_TUT, {
    onEnter() {
      log("[style   ] " + ts() + " popups_TUTORIAL: v0={" + fontInfo(safe32(G_TEXT_FONT_V0)) + "}" +
          " v1={" + fontInfo(safe32(G_TEXT_FONT_V1)) + "} v2={" + fontInfo(safe32(G_TEXT_FONT_V2)) + "}");
    }
  });
  Interceptor.attach(A_POPUPS_NORM, {
    onEnter() { log("[style   ] " + ts() + " popups_NORMAL"); }
  });

  // ---- Q1: box math --------------------------------------------------------------------
  Interceptor.attach(A_BASEPOP_CALC, {
    onEnter() {
      this.pop = this.context.ecx;
      this.w0 = safe32(this.pop.add(0x30bc));
    },
    onLeave() {
      const p = this.pop;
      log("[calc    ] " + ts() + " popup=" + p + (inTut ? " (TUT)" : "") +
          " boxW " + this.w0 + " -> " + safe32(p.add(0x30bc)) +
          " boxH=" + safe32(p.add(0x30c0)) +
          " btnH[+30d0]=" + safe32(p.add(0x30d0)) +
          " contentH=" + safe32(p.add(0x30d4)) +
          " art[+2144]=" + safe32(p.add(0x2144)) +
          " opts[+2274]=" + safe32(p.add(0x2274)) +
          " dlgFont={" + fontInfo(safe32(p.add(0xa3c))) + "}" +
          " bodyFont={" + fontInfo(safe32(p.add(0x3110))) + "}" +
          " g=" + g() + " active=" + active());
    }
  });

  // ---- Q3: every FlatButton content draw, content-deduped ------------------------------
  const seen = new Set();
  let btnDraws = 0;
  Interceptor.attach(A_FLATBTN_DRAW, {
    onEnter() {
      btnDraws++;
      const b = this.context.ecx;
      const label = cstr(ptr((safe32(b.add(0xa80)) || 0) >>> 0));
      const state = safe32(b.add(0xab8));
      const act = active();
      const cw = safe32(b.add(0x4c4)), chh = safe32(b.add(0x4c8));   // client/canvas dims (h negative)
      const r = [safe32(b.add(0x474)), safe32(b.add(0x478)), safe32(b.add(0x47c)), safe32(b.add(0x480))];
      const key = b.toString() + "|" + label + "|" + state + "|" + act + "|" + cw + "x" + chh;
      if (seen.has(key)) return;
      seen.add(key);
      log("[btnDraw ] " + ts() + " btn=" + b + " label='" + label + "' state[+ab8]=" + state +
          " client=[" + r.join(",") + "] canvasWH=" + cw + "x" + chh +
          " active=" + act + " g=" + g() + (inTut ? " (TUT)" : ""));
    }
  });

  // ---- Q4: pointer-line primitive, gated to TutWin callers ------------------------------
  Interceptor.attach(A_LINE_RAW, {
    onEnter() {
      const ra = this.returnAddress;
      if (ra.compare(TUT_LO) < 0 || ra.compare(TUT_HI) >= 0) return;
      const sp = this.context.esp;
      log("[lineRaw ] " + ts() + " ret=" + ra + " win=" + this.context.ecx +
          " (" + argS(sp, 1) + "," + argS(sp, 2) + ")->(" + argS(sp, 3) + "," + argS(sp, 4) + ")" +
          " color=0x" + u32(arg(sp, 5)).toString(16) +
          " a7=" + argS(sp, 6) + " a8=" + argS(sp, 7) + "   <-- a7/a8 = thickness levers");
    }
  });

  // arrow blink liveness (dedup on endpoints)
  const arrowSeen = new Set();
  Interceptor.attach(A_DRAW_ARROW, {
    onEnter() {
      const t = this.context.ecx;
      if (safe32(t.add(0x53a4)) === 0) return;
      const key = [safe32(t.add(0x538c)), safe32(t.add(0x5390)), safe32(t.add(0x5384)), safe32(t.add(0x5388))].join(",");
      if (arrowSeen.has(key)) return;
      arrowSeen.add(key);
      log("[arrow   ] " + ts() + " from=(" + safe32(t.add(0x538c)) + "," + safe32(t.add(0x5390)) +
          ") to=(" + safe32(t.add(0x5384)) + "," + safe32(t.add(0x5388)) + ")");
    }
  });

  setInterval(function () {
    log("[.pulse  ] " + ts() + " btnDraws=" + btnDraws + " distinct=" + seen.size + " active=" + active());
  }, 5000);

  log("hooks installed: tut_map/tut_win/popups_tut+norm/calc/btnDraw/lineRaw/arrow");
}
