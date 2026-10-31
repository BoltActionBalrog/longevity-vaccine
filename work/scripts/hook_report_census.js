"use strict";
// HQ report screens — ALL-KINDS draw census + geometry dumps (runs on the BAKED base: rw_scale_shared
// already swaps the 15-font table / lineH / window rect, so what this logs for kinds 0,3..8 + Hall of
// Fame is the residual NATIVE geometry each remaining page still carries).
//
// One session walks every page: F2 (control, baked) F3 F4 (+ the 3 mode tabs 0x8B3..0x8B5, click a
// base row, dbl-click nothing) F5 F6 (ATTACK + SURVEY tabs, let the orbit animate a few seconds) F7 F8,
// arrow keys to cycle, a faction tab or two, wheel over lists, then HQ menu -> Hall of Fame (click a
// category + faction), and optionally a commlink PROFILE (kind 0). Quit.
//
// What is logged (gated on ReportWin / HofWin modal or iface mode 5):
//   D <prim> @0xRET dest=<RWc|MAIN|HOFc|RW+off|RI+off|HOF+off|ptr> <args> k=<kind>   first 10 DISTINCT
//   arg-sets per (prim, ret) site, then counts only; SUMMARY table on every page switch / HOF close.
//   Primitives: box_sprite (set name), box_2/box, fill_3/fill/GraphicWin_fill_3, hline/vline, tile/tile_2/
//   tile_mask, Sprite_draw_2, blit_scaled_core (+scale globals), draw_mono_scaled, draw_table_scaled,
//   Buffer_draw_2, copy_3 (stretch), copy_4, base_draw, veh_draw, every Buffer_write_*/wrap_* text
//   writer (string, x/y or rect, font idx/variant/cap), set_font, set_clip, ListBox_attach,
//   ScrollBar_init_inner/attach_rect, BaseButton_init (inline rebuilds), Flic_init/draw_frame.
//   Object dumps (ReportWin / ReportIf / HofWin fields) on every page paint whose geometry hash changed.
// Attach set: engine primitives + report entries/painters only. NOTHING inside 0x498B9B..0x49BCAE
// (dl_scale interior, no-attach) — the kind-2 tech painter entry 0x498B30 is outside it.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_report_census.log";
log("=== hook_report_census.js started ===");
installAVHandler("report_census");

if (requireBase()) {
  const G_RW = 0x876478, G_RI = 0x885F38, G_HOF = 0x74DAF8;
  const RW_END = 0x885F38, RI_END = 0x885F38 + 0x20400, HOF_END = 0x74DAF8 + 0xC000;
  const G_KIND = 0x885F40, G_ITEM = 0x885F30, G_FACT = 0x8A4160;
  const G_SCREENW = 0x9b7b1c, G_SCREENH = 0x9b7b20, G_SCALE = 0x668740, G_STRIPH = 0x7af59c;
  const G_REGIONS = 0x7af5a0, G_MAINBUF = 0x7aec64, G_MAINCLIP = 0x7aec94, G_WIDE = 0x8a4168;
  const G_MODAL_TOP = 0x9B7AE0, G_IFACE_TBL = 0x7AE778, G_IFACE_IDX = 0x7D392C;
  const G_SCALE_NUM = 0x696D18, G_SCALE_DEN = 0x696D1C;
  const FONT_TBL = 0x93FC58;
  const KINDNAME = { 0: "intel", 2: "tech", 3: "energy", 4: "base-status", 5: "projects", 6: "satellites", 7: "units", 8: "score" };
  const SETNAME = { 0x78d528: "d528", 0x78d550: "d550", 0x78d578: "d578", 0x78d5a0: "d5a0", 0x78d5c8: "d5c8",
    0x78d5f0: "d5f0", 0x78d618: "d618", 0x78d690: "d690", 0x78d960: "d960", 0x78d980: "d980", 0x78d9a8: "d9a8",
    0x78da50: "da50", 0x78dac8: "dac8", 0x78db18: "db18", 0x78db40: "db40", 0x78db90: "db90", 0x78dbb8: "dbb8",
    0x78dc08: "dc08", 0x78dc30: "dc30", 0x78dc58: "dc58", 0x78dc80: "dc80" };

  function safeS32(p, d) { try { return p.readS32(); } catch (e) { return (d === undefined ? -0x7fffffff : d); } }
  function safeU32(p) { try { return p.readU32(); } catch (e) { return 0; } }
  function gval() { return safeS32(VA(G_SCALE), -1); }
  function kind() { return safeS32(VA(G_KIND)); }
  function rect4(p) { return [safeS32(p), safeS32(p.add(4)), safeS32(p.add(8)), safeS32(p.add(12))]; }
  function rstr(p) { const r = rect4(p); return "(" + r.join(",") + ")[" + (r[2] - r[0]) + "x" + (r[3] - r[1]) + "]"; }
  function ivec(p, n) { const a = []; for (let i = 0; i < n; i++) a.push(safeS32(p.add(i * 4))); return a; }
  function btnR(base, off) { return rstr(VA(base).add(off).add(0x474)); }
  function hex(v) { return "0x" + (v >>> 0).toString(16); }
  function staticVA(p) { return p.sub(globalThis.TERRANX_BASE).toUInt32() + 0x400000; }
  function retVA(ctx) { return staticVA(ctx.esp.readPointer()); }   // onEnter: [esp] = return address
  function strAt(p, n) {
    try { if (p.isNull()) return "<null>"; let s = p.readCString(n || 40); const i = s.indexOf("\0"); if (i >= 0) s = s.slice(0, i); return JSON.stringify(s); } catch (e) { return "<bad>"; }
  }
  function fontInfo(fp) {
    if (!fp || fp.isNull()) return "f=null";
    const v = fp.toUInt32(), base = VA(FONT_TBL).toUInt32();
    const d = v - base;
    if (d >= 0 && d < 12 * 0xA0) return "f[" + Math.floor(d / 0xA0) + "." + Math.floor((d % 0xA0) / 0x28) + "]cap" + safeS32(fp.add(0x10));
    return "f@" + hex(v) + "cap" + safeS32(fp.add(0x10));
  }
  function bufFont(b) { try { return fontInfo(b.add(0x52c).readPointer()); } catch (e) { return "f?"; } }
  function destTag(p) {
    const v = p.toUInt32();
    const rw = VA(G_RW).toUInt32(), ri = VA(G_RI).toUInt32(), hof = VA(G_HOF).toUInt32(), mb = VA(G_MAINBUF).toUInt32();
    if (v === rw + 0x444) return "RWc";
    if (v === hof + 0x444) return "HOFc";
    if (v === mb) return "MAIN";
    if (v >= rw && v < VA(RW_END).toUInt32()) return "RW+" + (v - rw).toString(16);
    if (v >= ri && v < VA(RI_END).toUInt32()) return "RI+" + (v - ri).toString(16);
    if (v >= hof && v < VA(HOF_END).toUInt32()) return "HOF+" + (v - hof).toString(16);
    return hex(v);
  }
  function active() {
    const mt = safeU32(VA(G_MODAL_TOP));
    if (mt === VA(G_RW).toUInt32() || mt === VA(G_HOF).toUInt32()) return true;
    const idx = safeS32(VA(G_IFACE_IDX), -1);
    if (idx >= 0 && idx < 32 && safeS32(VA(G_IFACE_TBL).add(idx * 4)) === 5) return true;
    return inPainter > 0;
  }
  let inPainter = 0, hofOpen = false;

  // ---------------- site census ----------------
  const sites = {};   // key prim@ret -> {prim, ret, n, uniq:{sig:count}, first:kind}
  const CAP = 10;
  function rec(prim, ctx, dest, sig) {
    if (!active()) return;
    const ret = retVA(ctx);
    const key = prim + "@" + ret.toString(16);
    let s = sites[key];
    if (!s) s = sites[key] = { prim, ret, n: 0, uniq: {}, nu: 0, k: kind() };
    s.n++;
    const dt = dest ? destTag(dest) : "-";
    const full = dt + " " + sig;
    if (s.uniq[full] === undefined) {
      s.nu++;
      if (s.nu <= CAP) { s.uniq[full] = 1; log("D " + prim + " @" + hex(ret) + " dest=" + full + " k=" + kind() + (hofOpen ? " HOF" : "")); }
      else s.uniq[full] = 1;
    } else s.uniq[full]++;
  }
  function summary(tag) {
    const keys = Object.keys(sites).sort((a, b) => sites[a].ret - sites[b].ret);
    log("==== SUMMARY (" + tag + ") " + keys.length + " sites ====");
    for (const k of keys) { const s = sites[k]; log("S " + hex(s.ret) + " " + s.prim + " n=" + s.n + " distinct=" + s.nu + " firstKind=" + s.k); }
    log("==== END SUMMARY ====");
  }
  function A(va, prim, fn) {
    try { Interceptor.attach(VA(va), { onEnter(args) { try { fn.call(this, args, this.context); } catch (e) { log("hook " + prim + " threw " + e); } } }); }
    catch (e) { log("ATTACH FAIL " + prim + " " + hex(va) + ": " + e); }
  }
  const S = p => safeS32(p);
  const arg = (sp, n) => sp.add(4 * n);           // [esp+4n] (onEnter, n>=1)

  // frames / fills / lines
  A(0x5E2DD3, "box_sprite", function (a, c) {
    const rp = arg(c.esp, 1).readPointer(), ps = arg(c.esp, 2).readPointer();
    rec("box_sprite", c, c.ecx, "r=" + rstr(rp) + " set=" + (SETNAME[staticVA(ps)] || hex(staticVA(ps))));
  });
  A(0x5E3203, "box_2", function (a, c) { rec("box_2", c, c.ecx, "r=" + rstr(arg(c.esp, 1).readPointer()) + " col=" + S(arg(c.esp, 2)) + "/" + S(arg(c.esp, 3))); });
  A(0x5E3193, "box", function (a, c) { rec("box", c, c.ecx, "xyxy=" + [1, 2, 3, 4].map(i => S(arg(c.esp, i))).join(",") + " col=" + S(arg(c.esp, 5)) + "/" + S(arg(c.esp, 6))); });
  A(0x5DFCD0, "fill_3", function (a, c) { rec("fill_3", c, c.ecx, "r=" + rstr(arg(c.esp, 1).readPointer()) + " col=" + S(arg(c.esp, 2))); });
  A(0x5D8240, "fill", function (a, c) { rec("fill", c, c.ecx, "xywh=" + [1, 2, 3, 4].map(i => S(arg(c.esp, i))).join(",") + " col=" + S(arg(c.esp, 5))); });
  A(0x5D5440, "gw_fill_3", function (a, c) { rec("gw_fill_3", c, c.ecx.add(0x444), "xywh=" + [1, 2, 3, 4].map(i => S(arg(c.esp, i))).join(",") + " col=" + S(arg(c.esp, 5))); });
  A(0x5E1A80, "hline", function (a, c) { rec("hline", c, c.ecx, "x0x1y=" + [1, 2, 3].map(i => S(arg(c.esp, i))).join(",") + " col=" + S(arg(c.esp, 4))); });
  A(0x5E1BF0, "vline", function (a, c) { rec("vline", c, c.ecx, "xy0y1=" + [1, 2, 3].map(i => S(arg(c.esp, i))).join(",") + " col=" + S(arg(c.esp, 4))); });
  // tiles
  function tileSig(c) { const sp = arg(c.esp, 1).readPointer(); return "spr=" + hex(staticVA(sp)) + "[" + S(sp.add(0x80)) + "x" + S(sp.add(0x84)) + "] off=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3)) + " xywh=" + [4, 5, 6, 7].map(i => S(arg(c.esp, i))).join(","); }
  A(0x5DA860, "tile", function (a, c) { rec("tile", c, c.ecx, tileSig(c)); });
  A(0x5DA9F0, "tile_2", function (a, c) { rec("tile_2", c, c.ecx, tileSig(c)); });
  A(0x5DA6C0, "tile_mask", function (a, c) { rec("tile_mask", c, c.ecx, "fill=" + hex(staticVA(arg(c.esp, 1).readPointer())) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3)) + " ph=" + S(arg(c.esp, 4)) + "," + S(arg(c.esp, 5)) + " wh=" + S(arg(c.esp, 6)) + "x" + S(arg(c.esp, 7)) + " mask=" + S(arg(c.esp, 8))); });
  // sprites / blits
  function sprWH(p) { return "[" + S(p.add(0x18)) + "x" + S(p.add(0x1c)) + "]"; }
  A(0x5E4B4A, "Sprite_draw_2", function (a, c) { rec("Sprite_draw_2", c, arg(c.esp, 1).readPointer(), "spr=" + hex(staticVA(c.ecx)) + sprWH(c.ecx) + " key=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " n/d=" + S(arg(c.esp, 5)) + "/" + S(arg(c.esp, 6))); });
  A(0x5E4B9A, "blit_core", function (a, c) { rec("blit_core", c, arg(c.esp, 1).readPointer(), "src=" + hex(staticVA(c.ecx)) + sprWH(c.ecx) + " key=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " G=" + S(VA(G_SCALE_NUM)) + "/" + S(VA(G_SCALE_DEN))); });
  A(0x5E3E00, "draw_mono_scaled", function (a, c) { rec("draw_mono_scaled", c, arg(c.esp, 1).readPointer(), "spr=" + hex(staticVA(c.ecx)) + sprWH(c.ecx) + " key=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " col=" + S(arg(c.esp, 5)) + " n/d=" + S(arg(c.esp, 6)) + "/" + S(arg(c.esp, 7))); });
  A(0x5E8FA5, "draw_table_scaled", function (a, c) { rec("draw_table_scaled", c, arg(c.esp, 1).readPointer(), "spr=" + hex(staticVA(c.ecx)) + sprWH(c.ecx) + " key=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " n/d=" + S(arg(c.esp, 5)) + "/" + S(arg(c.esp, 6))); });
  A(0x5D84C0, "Buffer_draw_2", function (a, c) { rec("Buffer_draw_2", c, arg(c.esp, 1).readPointer(), "src=" + hex(staticVA(c.ecx)) + "[" + S(c.ecx.add(0x80)) + "x" + S(c.ecx.add(0x84)) + "] key=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " n/d=" + S(arg(c.esp, 5)) + "/" + S(arg(c.esp, 6))); });
  A(0x5D9610, "copy_3", function (a, c) { rec("copy_3", c, arg(c.esp, 1).readPointer(), "src=" + hex(staticVA(c.ecx)) + "[" + S(c.ecx.add(0x80)) + "x" + S(c.ecx.add(0x84)) + "] s=" + [2, 3, 4, 5].map(i => S(arg(c.esp, i))).join(",") + " d=" + [6, 7, 8, 9].map(i => S(arg(c.esp, i))).join(",")); });
  A(0x5DFF00, "copy_4", function (a, c) { rec("copy_4", c, arg(c.esp, 1).readPointer(), "src=" + hex(staticVA(c.ecx)) + "[" + S(c.ecx.add(0x80)) + "x" + S(c.ecx.add(0x84)) + "] sxy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3)) + " dxy=" + S(arg(c.esp, 4)) + "," + S(arg(c.esp, 5)) + " wh=" + S(arg(c.esp, 6)) + "x" + S(arg(c.esp, 7))); });
  A(0x55AF20, "base_draw", function (a, c) { rec("base_draw", c, arg(c.esp, 1).readPointer(), "base=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " size=" + S(arg(c.esp, 5)) + " fl=" + hex(S(arg(c.esp, 6)))); });
  A(0x5594F0, "veh_draw", function (a, c) { rec("veh_draw", c, arg(c.esp, 1).readPointer(), "veh=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " size=" + S(arg(c.esp, 5)) + " fl=" + hex(S(arg(c.esp, 6)))); });
  // text writers (thiscall ecx=Buffer)
  const TXT = [
    [0x5DCEA0, "write_l_3", c => strAt(arg(c.esp, 1).readPointer()) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3))],
    [0x5DCF40, "write_l_4", c => strAt(arg(c.esp, 1).readPointer()) + " r=" + rstr(arg(c.esp, 2).readPointer())],
    [0x5DD020, "write_cent_l_5", c => strAt(arg(c.esp, 1).readPointer()) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3)) + " w=" + S(arg(c.esp, 4))],
    [0x5DD130, "write_cent_l_7", c => strAt(arg(c.esp, 1).readPointer()) + " r=" + rstr(arg(c.esp, 2).readPointer())],
    [0x5DD250, "write_cent_l_8", c => strAt(arg(c.esp, 1).readPointer()) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3))],
    [0x5DD300, "write_right_l_4", c => strAt(arg(c.esp, 1).readPointer()) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3)) + " a5=" + S(arg(c.esp, 4))],
    [0x5DD3B0, "write_right_l_5", c => strAt(arg(c.esp, 1).readPointer()) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3))],
    [0x5DD450, "write_right_l_6", c => strAt(arg(c.esp, 1).readPointer()) + " r=" + rstr(arg(c.esp, 2).readPointer())],
    [0x5DD730, "wrap_3", c => strAt(arg(c.esp, 1).readPointer()) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3)) + " w=" + S(arg(c.esp, 4))],
    [0x5DD920, "wrap_cent_4", c => strAt(arg(c.esp, 1).readPointer()) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3)) + " w=" + S(arg(c.esp, 4))],
    [0x5DDAB0, "wrap_cent_6", c => strAt(arg(c.esp, 1).readPointer()) + " r=" + rstr(arg(c.esp, 2).readPointer())],
    [0x5DB580, "write_l(font)", c => fontInfo(arg(c.esp, 1).readPointer()) + " " + strAt(arg(c.esp, 2).readPointer()) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4))],
    [0x5DB720, "write_cent_l_2(font)", c => fontInfo(arg(c.esp, 1).readPointer()) + " " + strAt(arg(c.esp, 2).readPointer()) + " r=" + rstr(arg(c.esp, 3).readPointer())],
    [0x5DBC00, "wrap_cent_3(font)", c => fontInfo(arg(c.esp, 1).readPointer()) + " " + strAt(arg(c.esp, 2).readPointer()) + " r=" + rstr(arg(c.esp, 3).readPointer())],
    [0x5DB040, "write_strings", c => "list=" + hex(arg(c.esp, 1).readPointer().toUInt32()) + " xy=" + S(arg(c.esp, 2)) + "," + S(arg(c.esp, 3)) + " w=" + S(arg(c.esp, 4))],
  ];
  for (const [va, name, sig] of TXT) A(va, name, function (a, c) { rec(name, c, c.ecx, bufFont(c.ecx) + " " + sig(c)); });
  A(0x5DAC70, "set_font", function (a, c) { rec("set_font", c, c.ecx, [1, 2, 3, 4].map(i => fontInfo(arg(c.esp, i).readPointer())).join(" ")); });
  A(0x5D8000, "set_clip", function (a, c) { rec("set_clip", c, c.ecx, "r=" + rstr(arg(c.esp, 1).readPointer())); });
  // widgets
  A(0x60A670, "ListBox_attach", function (a, c) { rec("ListBox_attach", c, null, "ecx=" + hex(c.ecx.toUInt32()) + " edx=" + hex(c.edx.toUInt32()) + " st=" + [1, 2, 3, 4].map(i => hex(safeU32(arg(c.esp, i)))).join(",")); });
  A(0x6054D0, "ScrollBar_init_inner", function (a, c) { rec("ScrollBar_init_inner", c, null, "sb=" + destTag(c.ecx) + " xywh=" + [1, 2, 3, 4].map(i => S(arg(c.esp, i))).join(",") + " parent=" + destTag(arg(c.esp, 5).readPointer()) + " a=" + S(arg(c.esp, 6)) + "," + S(arg(c.esp, 7))); });
  A(0x605840, "ScrollBar_attach_rect", function (a, c) { rec("ScrollBar_attach_rect", c, null, "sb=" + destTag(c.ecx) + " r=" + rstr(arg(c.esp, 1).readPointer()) + " parent=" + destTag(arg(c.esp, 2).readPointer()) + " id=" + S(arg(c.esp, 3)) + " fl=" + S(arg(c.esp, 4))); });
  A(0x607210, "BaseButton_init", function (a, c) { rec("BaseButton_init", c, null, "btn=" + destTag(c.ecx) + " " + strAt(arg(c.esp, 1).readPointer(), 24) + " a3=" + S(arg(c.esp, 2)) + " xywh=" + [3, 4, 5, 6].map(i => S(arg(c.esp, i))).join(",") + " parent=" + destTag(arg(c.esp, 7).readPointer())); });
  A(0x629E50, "Flic_init", function (a, c) { rec("Flic_init", c, arg(c.esp, 1).readPointer(), "flic=" + destTag(c.ecx) + " " + strAt(arg(c.esp, 2).readPointer(), 40) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " a6=" + S(arg(c.esp, 5))); });
  A(0x62A070, "Flic_draw_frame", function (a, c) { rec("Flic_draw_frame", c, null, "flic=" + destTag(c.ecx) + " wh=" + S(c.ecx.add(0x59c)) + "x" + S(c.ecx.add(0x5a0)) + " xy=" + S(arg(c.esp, 1)) + "," + S(arg(c.esp, 2))); });

  // ---------------- object dumps ----------------
  function envLine() {
    return "env: ScreenW=" + S(VA(G_SCREENW)) + " ScreenH=" + S(VA(G_SCREENH)) + " g=" + gval() + " stripH=" + S(VA(G_STRIPH)) +
      " wide=" + S(VA(G_WIDE)) + " kind=" + kind() + "(" + (KINDNAME[kind()] || "?") + ") item=" + S(VA(G_ITEM)) + " faction=" + S(VA(G_FACT)) +
      " modalTop=" + destTag(VA(G_MODAL_TOP).readPointer());
  }
  function rwDump(tag) {
    const o = VA(G_RW);
    log("---- RW DUMP (" + tag + ") ---- " + envLine());
    log("rw.win+474=" + rstr(o.add(0x474)) + " +13C=" + rstr(o.add(0x13c)) + " canvas=" + S(o.add(0x4c4)) + "x" + S(o.add(0x4c8)) +
        " clip+5974=" + rstr(o.add(0x5974)) + " textB=" + S(o.add(0x5980)) + " lineH+E268=" + S(o.add(0xe268)) + " scratchA14..=" + ivec(o.add(0xa14), 4).join(","));
    log("rw.cells btn_w/h+59A0/A4=" + S(o.add(0x59a0)) + "/" + S(o.add(0x59a4)) + " card_w=" + S(o.add(0x59a8)) + " sel=" + S(o.add(0x59ac)) + "/" + S(o.add(0x59b0)) +
        " sortcol=" + S(o.add(0x5a08)) + " grp1sel=" + S(o.add(0x7c8c)) + " satsel=" + S(o.add(0x9f04)) + " modeTabSel(8a4178)=" + S(VA(0x8a4178)) + " unitFilter=" + S(VA(0x8a417c)));
    log("rw.scroll active=" + S(o.add(0xc0f8)) + " pos/min/max/page=" + [0xc0fc, 0xc100, 0xc104, 0xc108].map(x => S(o.add(x))).join("/") + " rowRect+E258=" + rstr(o.add(0xe258)) + " need/reinit=" + S(o.add(0xe26c)) + "/" + S(o.add(0xe270)) + " grp1row+7BF8=" + rstr(o.add(0x7bf8)));
    log("rw.btn id9=" + btnR(G_RW, 0x6560) + " id1=" + btnR(G_RW, 0x70ac) + " mode8B3/4/5=" + btnR(G_RW, 0x7c9c) + btnR(G_RW, 0x87e8) + btnR(G_RW, 0x9334) + " satD3C/D3D/D3E=" + btnR(G_RW, 0x9f14) + btnR(G_RW, 0xaa60) + btnR(G_RW, 0xb5ac));
    log("rw.energyList+5A0C: rect=" + rstr(o.add(0x5a0c + 0x474)) + " rowH+68=" + S(o.add(0x5a0c + 0x68)) + " +48=" + S(o.add(0x5a0c + 0x48)));
    if (kind() === 6) log("rw.sat orbit E2A0=" + rstr(o.add(0xe2a0)) + " E2B0=" + rstr(o.add(0xe2b0)) + " flicWH=" + S(o.add(0xf3d0)) + "x" + S(o.add(0xf3d4)) + " nSat=" + S(o.add(0xf918)) + " flic+E8A8 wh=" + S(o.add(0xe8a8 + 0x59c)) + "x" + S(o.add(0xe8a8 + 0x5a0)));
  }
  function riDump(tag) {
    const o = VA(G_RI);
    log("---- RI DUMP (" + tag + ") ---- " + envLine());
    log("ri.kind=" + S(o.add(8)) + " cursor=" + ivec(o.add(0xc), 4).join(",") + " lineH+1C=" + S(o.add(0x1c)) + " listMode=" + S(o.add(0x1e1d8)) +
        " panelL=" + rstr(o.add(0x20)) + " panelR=" + rstr(o.add(0x30)) + " strip=" + rstr(o.add(0x40)) + " center=" + rstr(o.add(0x50)));
    log("ri.tabs kindX=" + ivec(o.add(0xa298), 7).join(",") + " y=" + S(o.add(0xa2cc)) + " spr=" + S(o.add(0x4fac)) + "x" + S(o.add(0x4fb0)) + " facX=" + ivec(o.add(0x60), 7).join(",") + " y=" + S(o.add(0x7c)));
    log("ri.fonts=" + ivec(o.add(0x1e180), 15).map(v => fontInfo(ptr(v >>> 0))).join(" "));
    log("ri.toggles 92/93=" + btnR(G_RI, 0xba0c) + btnR(G_RI, 0xc558) + " D0A/D0B=" + btnR(G_RI, 0xd138) + btnR(G_RI, 0xdc84) +
        " gov=" + [0xe7d0, 0xf31c, 0xfe68, 0x109b4, 0x11500, 0x1204c, 0x12b98].map(x => btnR(G_RI, x)).join("") +
        " unit=" + [0x1bf9c, 0x1cae8, 0x1d634].map(x => btnR(G_RI, x)).join("") + " list+A2D0 rect=" + rstr(o.add(0xa2d0 + 0x474)));
    log("hudRegions=" + ivec(VA(G_REGIONS), 16).join(",") + " mainBuf=" + S(VA(G_MAINBUF).add(0x80)) + "x" + S(VA(G_MAINBUF).add(0x84)) + " clip=" + rstr(VA(G_MAINCLIP)));
  }
  function hofDump(tag) {
    const o = VA(G_HOF);
    log("---- HOF DUMP (" + tag + ") ---- " + envLine());
    log("hof.win+474=" + rstr(o.add(0x474)) + " +13C=" + rstr(o.add(0x13c)) + " canvas=" + S(o.add(0x4c4)) + "x" + S(o.add(0x4c8)) + " A14..A30=" + ivec(o.add(0xa14), 8).join(",") +
        " lineH+A44=" + S(o.add(0xa44)) + " wide=" + S(o.add(0xa48)) + " sel=" + S(o.add(0xa918)) + " vtbl=" + hex(staticVA(o.readPointer())));
    log("hof.rects=" + [0, 1, 2, 3, 4, 5].map(i => rstr(o.add(0xb42c + i * 0x10))).join(" "));
    log("hof.catBtns=" + [0, 1, 2, 3, 4, 5].map(i => btnR(G_HOF, 0x5a04 + i * 0xb4c)).join("") + " facBtns=" + [0, 1, 2, 3, 4, 5, 6].map(i => btnR(G_HOF, 0xa5c + i * 0xb4c)).join("") + " close=" + btnR(G_HOF, 0x9dcc));
  }
  function geomHash() {
    const o = VA(G_RW), r = VA(G_RI);
    let h = kind() | 0;
    for (const off of [0x474, 0x5974, 0xe258, 0x7bf8]) { const q = rect4(o.add(off)); h = ((h * 31) + q[0] + q[1] * 7 + q[2] * 13 + q[3] * 17) | 0; }
    for (const off of [0x5980, 0x59a0, 0x59a4, 0x59a8, 0xe268, 0xc104, 0xc108, 0x7c8c, 0x9f04]) h = ((h * 31) + S(o.add(off))) | 0;
    for (const off of [0x20, 0x30, 0x40, 0x50]) { const q = rect4(r.add(off)); h = ((h * 31) + q[0] + q[1] * 7 + q[2] * 13 + q[3] * 17) | 0; }
    return h;
  }

  // ---------------- report lifecycle / painters ----------------
  const ENTRIES = [["report_intel", 0x4acbd0], ["report_labs", 0x4ac9a0], ["report_energy", 0x4ac9f0], ["report_ops", 0x4aca40],
    ["report_projects", 0x4aca90], ["report_sat", 0x4acae0], ["report_security", 0x4acb30], ["report_score", 0x4acb80]];
  for (const [name, va] of ENTRIES) A(va, name, function () { log("ENTRY " + name + "  " + envLine()); });
  const PAINTERS = [["rw_intel", 0x4a2210], ["rw_tech", 0x498b30], ["rw_energy", 0x49bcd0], ["rw_ops", 0x49d540], ["rw_projects", 0x49eb10],
    ["rw_sat", 0x49f350], ["rw_units", 0x4a08e0], ["rw_score", 0x4a1140], ["ri_intel", 0x4ac140], ["ri_labs", 0x4a7000], ["ri_energy", 0x4a84a0],
    ["ri_ops", 0x4a9050], ["ri_projects", 0x4aa0b0], ["ri_sat", 0x4aa970], ["ri_units", 0x4ab600], ["ri_score", 0x4abe70], ["ri_chrome", 0x4a3d20],
    ["bl_blink", 0x4a4060], ["sat_anim", 0x49ffc0], ["sat_expl", 0x4a0250]];
  const pn = {};
  for (const [name, va] of PAINTERS) {
    try {
      Interceptor.attach(VA(va), {
        onEnter() { inPainter++; const n = (pn[name] = (pn[name] || 0) + 1); if (n <= 3 || n % 50 === 0) log("PAINTER " + name + " #" + n + " k=" + kind() + " g=" + gval()); },
        onLeave() { inPainter--; }
      });
    } catch (e) { log("ATTACH FAIL painter " + name + ": " + e); }
  }
  let lastHash = null, paintN = 0; const dumped = {};
  Interceptor.attach(VA(0x496d00), {          // ReportWin painter dispatch
    onEnter() { inPainter++; paintN++; this.k = kind(); },
    onLeave() {
      inPainter--;
      const h = geomHash();
      if (h !== lastHash || !dumped[this.k]) { lastHash = h; dumped[this.k] = 1; rwDump("paint#" + paintN + " k=" + this.k + " hash=" + h); }
    }
  });
  Interceptor.attach(VA(0x4a3950), {          // ReportIf show_page(kind, faction, data)
    onEnter() { const sp = this.context.esp; this.k = S(sp.add(4)); summary("before show_page k=" + this.k); log("show_page kind=" + this.k + "(" + (KINDNAME[this.k] || "?") + ") faction=" + S(sp.add(8)) + " data=" + S(sp.add(12))); inPainter++; },
    onLeave() { inPainter--; riDump("post-show_page k=" + this.k); }
  });
  Interceptor.attach(VA(0x4a41d0), {          // ReportIf activate(on)
    onEnter() { this.on = S(this.context.esp.add(4)); log("ReportIf_activate(" + this.on + ") " + envLine()); if (!this.on) summary("deactivate"); inPainter++; },
    onLeave() { inPainter--; }
  });
  A(0x4a3fc0, "ri_on_redraw", function () { const n = (pn.ri_on_redraw = (pn.ri_on_redraw || 0) + 1); if (n <= 3) log("ri_on_redraw #" + n); });
  // click-path inline rebuilds (dest-keyed census already catches the draws; log the dispatch)
  A(0x496e10, "rw_on_l_click", function (a, c) { log("rw_on_l_click k=" + kind() + " xy=" + S(arg(c.esp, 1)) + "," + S(arg(c.esp, 2))); });
  A(0x4986d0, "rw_on_button", function (a, c) { log("rw_on_button id=" + S(arg(c.esp, 1)) + " k=" + kind()); });
  A(0x4989f0, "rw_on_group_changed", function (a, c) { log("rw_on_group_changed a1=" + S(arg(c.esp, 1)) + " a2=" + S(arg(c.esp, 2)) + " k=" + kind()); });
  A(0x498180, "rw_sb_pos_a", function (a, c) { log("rw_sb_pos_changed(a) pos=" + S(arg(c.esp, 1)) + " k=" + kind()); });
  A(0x498200, "rw_sb_pos_b", function (a, c) { log("rw_sb_pos_changed(b) pos=" + S(arg(c.esp, 1)) + " k=" + kind()); });
  A(0x4a6050, "ri_list_selected", function (a, c) { log("ri_list_selected a1=" + S(arg(c.esp, 1)) + " a2=" + S(arg(c.esp, 2)) + " k=" + kind()); });
  A(0x4a0260, "sat_attack", function () { log("sat_attack popup"); });

  // ---------------- Hall of Fame ----------------
  let hofPainterHooked = false;
  Interceptor.attach(VA(0x44ae50), {
    onEnter() {
      hofOpen = true; log("hall_of_fame(" + S(this.context.esp.add(4)) + ") " + envLine());
      if (!hofPainterHooked) {
        hofPainterHooked = true;
        try {
          const vt = VA(G_HOF).readPointer(); const slots = {};
          for (const off of [0x04, 0x08, 0x30, 0x4c, 0x64, 0xb0, 0xb8, 0x124]) slots[off.toString(16)] = hex(staticVA(vt.add(off).readPointer()));
          log("HOF vtbl=" + hex(staticVA(vt)) + " slots=" + JSON.stringify(slots));
          const paint = vt.add(0x30).readPointer();
          Interceptor.attach(paint, { onEnter() { inPainter++; const n = (pn.hof_paint = (pn.hof_paint || 0) + 1); if (n <= 3) log("PAINTER hof_paint #" + n + " @" + hex(staticVA(paint))); }, onLeave() { inPainter--; if (pn.hof_paint <= 2) hofDump("post-paint#" + pn.hof_paint); } });
          const onbtn = vt.add(0xb0).readPointer();
          Interceptor.attach(onbtn, { onEnter() { log("hof_on_button id=" + S(this.context.esp.add(4))); } });
        } catch (e) { log("HOF vtbl hook failed: " + e); }
      }
    },
    onLeave() { hofDump("hall_of_fame returned"); summary("HOF close"); hofOpen = false; }
  });
  Interceptor.attach(VA(0x448400), { onLeave() { hofDump("post-load_hoficons"); } });
  Interceptor.attach(VA(0x4a3460), { onLeave() { riDump("post-init_report_screen"); } });
  Interceptor.attach(VA(0x496960), { onLeave() { rwDump("post-win_init"); } });

  setInterval(() => { const n = Object.keys(sites).length; if (n) log("tick: " + n + " sites, kind=" + kind() + " active=" + active()); }, 15000);
  log("attached: census on " + Object.keys(SETNAME).length + " set names, " + TXT.length + " text writers, " + PAINTERS.length + " painters; " + envLine());
}
