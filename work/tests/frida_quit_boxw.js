'use strict';
// QUIT (#48) box-width composition probe -- stage-2 evidence for the content-keyed
// box width. Load AFTER frida_common.js:
//   frida -f <exe> -l ..\scripts\frida_common.js -l frida_quit_boxw.js
// Then open the QUIT popup (in-game ESC -> Quit) once per resolution.
//
// Captures, per popup that reaches BasePop_calculate_dimensions:
//   A. at the thunk_scale_boxw site 0x603d82: box_w BEFORE the multiply, plus the
//      width-composition inputs (content_w [0x30d8], pad_x [0x30e0], margins,
//      dialog type [0x2350], option count [0x2274]) -- and box_w AFTER (0x603d88).
//   B. at OptionList_calculate_dimensions (0x610970) exit: the type-8 Dialog's
//      measured fields ([+0x44] gap, [+0x5c] text w, [+0x60] total, [+0x64] row w,
//      [+0x68] pitch, [+0x70] measure font) -- confirms the qdlg_font swap fired.
//   C. at the OptionList_attach GraphicWin_init site 0x6105ec: the x,y,w,h args
//      (x parent-relative? w widened by thunk_q8_fill_width?).
// Output: appended JSON lines in frida_quit_boxw.log next to this script.

globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_quit_boxw.log";

const SITE_BOXW   = 0x603d82;   // thunk_scale_boxw call site (esi = popup)
const SITE_RESUME = 0x603d88;   // after the displaced instr (box_w final for this pass)
const OPTLIST_CALC = 0x610970;  // thiscall, ecx = Dialog subobj+0x70
const SITE_WININIT = 0x6105ec;  // OptionList_attach call GraphicWin_init site
const G_SCALE = 0x668740;

function j(tag, obj) {
  obj.tag = tag;
  obj.g = VA(G_SCALE).readS32();
  const line = JSON.stringify(obj);
  console.log(line);
  const f = new File(globalThis.LOG_PATH, "a");
  f.write(line + "\n");
  f.close();
}
function rd(p, off) { try { return p.add(off).readS32(); } catch (e) { return null; } }
function hx(v) { return v === null ? null : "0x" + (v >>> 0).toString(16); }

// A. box-width composition at the scale site
Interceptor.attach(VA(SITE_BOXW), function () {
  const pop = this.context.esi;
  this._pop = pop;
  const dlg = rd(pop, 0x21d0);
  let iface = null, d = {};
  if (dlg) {
    try {
      iface = ptr(hx(dlg)).readS32() ? ptr(hx(dlg)).add(8).readS32() : null; // [vtbl? ] -- adjustor read below via popup-relative fields instead
    } catch (e) {}
  }
  j("boxw_before", {
    title: (function () { const t = rd(pop, 0xa48); try { return t ? ptr(hx(t)).readUtf8String(24) : null; } catch (e) { return null; } })(),
    box_w: rd(pop, 0x30bc), box_h: rd(pop, 0x30c0),
    content_w_30d8: rd(pop, 0x30d8), pad_x_30e0: rd(pop, 0x30e0),
    margin_l_30f0: rd(pop, 0x30f0), margin_r_30f4: rd(pop, 0x30f4),
    content_top_30e8: rd(pop, 0x30e8), content_h_30c4: rd(pop, 0x30c4),
    dialog_type_2350: rd(pop, 0x2350), option_count_2274: rd(pop, 0x2274),
    dlg_req_w_2c: rd(pop, 0x21d0 + 0x2c), dlg_text_w_5c: rd(pop, 0x21d0 + 0x5c),
    dlg_total_60: rd(pop, 0x21d0 + 0x60), dlg_row_w_64: rd(pop, 0x21d0 + 0x64),
    dlg_pitch_68: rd(pop, 0x21d0 + 0x68), dlg_gap_44: rd(pop, 0x21d0 + 0x44),
    dlg_font_70: hx(rd(pop, 0x21d0 + 0x70)), pop_font_a3c: hx(rd(pop, 0xa3c)),
  });
});
Interceptor.attach(VA(SITE_RESUME), function () {
  const pop = this.context.esi;
  j("boxw_after", { box_w: rd(pop, 0x30bc) });
});

// B. type-8 measure results
Interceptor.attach(VA(OPTLIST_CALC), {
  onEnter(args) { this.sub = this.context.ecx; },
  onLeave(ret) {
    // fields on the Dialog base = subobj - 0x70
    const dlgBase = this.sub.sub(0x70);
    j("optlist_calc", {
      gap_44: rd(dlgBase, 0x44), text_w_5c: rd(dlgBase, 0x5c),
      total_60: rd(dlgBase, 0x60), row_w_64: rd(dlgBase, 0x64),
      pitch_68: rd(dlgBase, 0x68), font_70: hx(rd(dlgBase, 0x70)),
      count_cc: rd(dlgBase, 0xcc), req_w_2c: rd(dlgBase, 0x2c),
      sprite_max_w_54: rd(dlgBase, 0x54), sprite_max_h_58: rd(dlgBase, 0x58),
    });
  },
});

// C. the row-window init args (after thunk_q8_fill_width has run: hook INSIDE
// GraphicWin_init so we see the final values; the thunk tail-jumps there).
Interceptor.attach(VA(SITE_WININIT), function () {
  const sp = this.context.esp;
  j("row_wininit", {
    x: sp.add(4).readS32(), y: sp.add(8).readS32(),
    w: sp.add(0xc).readS32(), h: sp.add(0x10).readS32(),
  });
});
