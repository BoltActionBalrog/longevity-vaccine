// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// HQ report screens -- kinds 0,3..8 prototype v4 (2026-09-07) = v2 levers + v4 levers + the v3 grand probe.
// v4 (from the grand-probe run 4K+1600): ROWS_V4 = console button builds in ReportIf_activate (GOVERNOR/BEST BASES, mode
// tabs, sat tabs, ATTACK!, governor + automate lists: native 20-px rows -> s()), satellite orbit frame/radius/dots,
// bases CITIZENS/GARRISON icon steps/clamps/offsets, Hall of Fame window/content/rects/painter insets; hooks = G brackets
// (citizen faces, HOF faction picture, sat planet), sat planet recentre, HOF content-right poke, HOF backdrop copy_4 ->
// copy_3 stretches (Interceptor.replace), HOF button rects (BaseButton_init args) + faces (Sprite_draw_2 n/d) + CLOSE gate
// admission. Canvas dumps are now prefixed by g.
// v3 was: Runs ON the baked base
// (rw_scale_shared/tech + listbox_hover_clamp, live MD5 06cb2739). One walk of every page (F3..F8 with every mode/sat tab,
// clicks, keys, Hall of Fame) at 4K and at one non-4K resolution feeds the OFFLINE prototyping of every remaining page.
//
// v2 LEVERS (unchanged, applied at init_report_screen's return): 256 imm rows (s(a)-s(b), identity-checked against
// vanilla), 3 magic-div caves (projects /54, units /43, projects row y), 2 imm32 caves (bases x+0x3C, intel x+0x7D).
// v3 CHANGE: the unit/base ICON size levers are BYTE POKES of the four `push -6/-8` size immediates at the report call
// sites (0x4a0e01/0x49dc3b/0x49df44/0x49ea70 -> SL.vehSizeScaled) instead of call-site Interceptor hooks (hazard #7:
// a hooked call site whose callee entry is baked-detoured -- veh_draw/base_draw carry thunk_hud_vehargs -- displaces
// the entry's stack view; the v2 hooks never fired in any run anyway).
// v3 PROBE (block at the end): the 2026-09-02 draw census (every primitive into RWc/MAIN/HOFc with ret site, dedup 24
// per site), object dumps per paint (ReportWin/ReportIf/HofWin fields), CANVAS DUMPS to work\_rw_dumps\*.raw (pitch-
// strided 8bpp + the buffer's RGBQUAD[256] at +0xA4) per kind/mode/sat view, after clicks, sat animation, HOF paints;
// Spot_add hit rects + Spot_check results (hit-area laws); on_l/dbl/r_click + on_key + selection state; HOF vtbl paint/
// button/click; the satellite Flic objects (hex) and Flic_init/draw_frame; the frame-enlarge probe (capped).
// DROPPED from v2's tail: LISTFIX caves + BTNGATE/ICONBLIT probes (baked v7), the F2 list ROWTEXT probe + WHEEL hover
// reset (baked v6; the cave attach offsets were stale after every bake).
// Attach set audited 2026-09-07 (scratchpad audit/audit_attach.py): function entries only; no call-site hooks; nothing
// in a push;ret cluster head/resume; ScrollBar_init_inner (now the rw_stash detour) dropped.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_report_kinds_proto.log";
log("=== hook_report_kinds_proto.js v13 (attack explosion patch rows + table-draw G bracket; K-stroke frames, toggle seams, wheel diag; label fonts, console-list wheel, bar residue; console buttons/titles/list bars, slide rails, rail scrollbar, sat orbit, citizens/garrison, CHEATED font, Hall of Fame) + grand probe started ===");
installAVHandler("report_kinds_proto");

if (requireBase()) {
  const G_SCALE = 0x668740;
  // g_popup_scale_num is 0 at process start (run 1 disarmed itself): read it LIVE and apply the table at
  // init_report_screen's return (desktop_init; the rw bake's own lever runs there too), once.
  const gNow = () => VA(G_SCALE).readS32();
  let g = gNow();
  const s = v => { const t = 2 * v * g + 15; return v >= 0 ? (t >> 5) : -(((2 * (-v) * g + 15) >> 5)); };   // scale_px, sign-symmetric
  const hex = v => "0x" + (v >>> 0).toString(16);
  const _caves = [];
  function makeCave(hexStr) {
    const b = []; for (let i = 0; i < hexStr.length; i += 2) b.push(parseInt(hexStr.substr(i, 2), 16));
    const p = Memory.alloc(4096); _caves.push(p); Memory.protect(p, 4096, "rwx"); p.writeByteArray(b); return p;
  }
  function d32(v) { v = v | 0; return [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff]; }
  function jmpTo(siteVA, target, totalLen, expectHex) {
    const p = VA(siteVA);
    const cur = Array.from(new Uint8Array(p.readByteArray(totalLen))).map(x => x.toString(16).padStart(2, "0")).join("");
    if (cur !== expectHex) { log("DETOUR guard FAIL @" + hex(siteVA) + " have " + cur + " want " + expectHex); return false; }
    Memory.protect(p, totalLen, "rwx");
    const b = [0xE9].concat(d32(target.sub(p.add(5)).toInt32()));
    while (b.length < totalLen) b.push(0x90);
    p.writeByteArray(b); return true;
  }

  // ---------------- imm rows: [addr, width, a, b, label]  value = s(a)-s(b) ----------------
  const ROWS = [
    // ===== ReportWin canvas painters (dest RW+0x444, clip already scaled) =====
    // kind 3 ENERGY FUN_0049bcd0: title/column insets, list-rect insets, maintenance ListBox rect
    [0x49bcff, 1, 3, 0, "e: L+3"], [0x49bd0e, 1, 3, 0, "e: T+3"], [0x49bd1a, 1, 0, 3, "e: R-3"], [0x49bd2a, 1, 9, 0, "e: title B = T+lineH+9"],
    [0x49bd30, 1, 3, 0, "e: +3"], [0x49bd39, 1, 2, 0, "e: body top +2"], [0x49bd53, 1, 9, 0, "e: +lineH+9"], [0x49bd60, 1, 3, 0, "e: +3"],
    [0x49bd69, 1, 2, 0, "e: col gap +2"], [0x49bd81, 1, 2, 0, "e: col gap +2"], [0x49bd9c, 1, 0, 3, "e: textB-3"],
    [0x49bfb4, 1, 6, 0, "e: text x+6"], [0x49bfb7, 1, 6, 0, "e: text y+6"], [0x49bfca, 1, 0xc, 0, "e: text w-0xC"],
    [0x49c823, 1, 0xa, 0, "e: +10"],
    [0x49cc00, 1, 6, 0, "e: list +6"], [0x49cc0c, 1, 6, 0, "e: list +6"], [0x49cc0f, 1, 3, 0, "e: list +3"], [0x49cc1d, 1, 3, 0, "e: list -3"],
    [0x49cc22, 1, 3, 0, "e: list +3"], [0x49cc25, 1, 0xc, 0, "e: list w-0xC"], [0x49cc34, 1, 3, 0, "e: list -3"], [0x49cc64, 4, 3, 0, "e: list row +3 (imm32)"],
    // kind 4 BASES FUN_0049d540: cell 0x28, top +0x22, pitch cell+2, rows (h-6)/pitch, production column; the garrison
    // -0x20/-0x12/-0x2D offsets are paired with UNSCALED clamps (0x22/0x28 in decompile lines 466..627) -> left native in v1
    [0x49d591, 4, 0x28, 0, "b: cell 0x28 (fields +59A0/A4)"], [0x49d5bc, 1, 0x22, 0, "b: top = T+lineH+0x22"], [0x49d5e4, 1, 9, 0, "b: +9"],
    [0x49d5ef, 1, 0, 3, "b: -3"], [0x49d5f5, 1, 3, 0, "b: +3"], [0x49d60a, 1, 3, 0, "b: +3"], [0x49d613, 1, 2, 0, "b: pitch = cell+2"],
    [0x49d61f, 1, 3, 0, "b: +3"], [0x49d622, 1, 0x28, 0, "b: +cell"], [0x49d62b, 1, 0x28, 0, "b: +cell"], [0x49d62e, 1, 2, 0, "b: +2"],
    [0x49d689, 1, 2, 0, "b: +2"], [0x49d693, 1, 6, 0, "b: rows=(h-6)/pitch"], [0x49da27, 1, 3, 0, "b: row rect +3"],
    [0x49dbf0, 4, 0x3e, 0, "b: base icon box w 0x3E"], [0x49dc2c, 4, 0x2e, 0, "b: base icon box h 0x2E"],
    [0x49dd55, 1, 5, 0, "b: name x+5"], [0x49dd72, 1, 5, 0, "b: name y+5"], [0x49dec8, 1, 0x14, 0, "b: +0x14"],
    [0x49df00, 4, 0xc0, 0, "b: production col x+0xC0"], [0x49df42, 1, 4, 0, "b: +4"], [0x49df89, 1, 2, 0, "b: -2"],
    [0x49dfb7, 1, 4, 0, "b: +4"], [0x49dfba, 1, 8, 0, "b: +8"], [0x49dffa, 1, 2, 0, "b: -2"], [0x49e01b, 1, 4, 0, "b: +4"], [0x49e01e, 1, 8, 0, "b: +8"],
    // kind 5 PROJECTS FUN_0049eb10: header, cell h 0x36 (field), rows (h-5)/cell [cave], colW (w-6)/2-1, icon/text insets
    [0x49eb37, 1, 3, 0, "p: +3"], [0x49eb43, 1, 3, 0, "p: +3"], [0x49eb46, 1, 3, 0, "p: -3"], [0x49eb5c, 1, 9, 0, "p: title +9"],
    [0x49eb63, 4, 0x36, 0, "p: cell h 0x36 (+59A4)"], [0x49eb6e, 1, 5, 0, "p: rows=(h-5)/cell"], [0x49eb94, 1, 6, 0, "p: colW=(w-6)/2-1"],
    [0x49ee77, 1, 2, 0, "p: +2"],
    [0x49ef75, 1, 2, 0, "p: icon -2"], [0x49ef99, 1, 2, 0, "p: icon x+2"], [0x49efb3, 1, 2, 0, "p: -2"], [0x49efb6, 1, 5, 0, "p: text +5"], [0x49efd3, 1, 7, 0, "p: text +7"],
    // kind 6 SATELLITES FUN_0049f350 (table view): header, column split +-0x32, cell insets; orbit view frame 0x240x0xD2 left native (art)
    [0x49f372, 1, 3, 0, "s: +3"], [0x49f389, 1, 3, 0, "s: +3"], [0x49f396, 1, 3, 0, "s: -3"], [0x49f3aa, 1, 9, 0, "s: title +9"],
    [0x49f513, 1, 0x32, 0, "s: col +0x32"], [0x49f516, 1, 0, 0x32, "s: col -0x32"], [0x49f525, 1, 2, 0, "s: -2"], [0x49f54f, 1, 0, 4, "s: -4"],
    [0x49f5a2, 1, 2, 0, "s: +2"],
    // kind 7 UNITS FUN_004a08e0: header, pitch 0x2B (3 sites) + rows /0x2B [cave], name column 0x66, stats -0x40 (overflow)
    [0x4a0908, 1, 3, 0, "u: +3"], [0x4a0910, 1, 3, 0, "u: +3"], [0x4a091f, 1, 0, 3, "u: -3"], [0x4a0936, 1, 9, 0, "u: title +9"], [0x4a0942, 1, 2, 0, "u: +2"],
    [0x4a0945, 1, 0x2b, 0, "u: pitch 0x2B"], [0x4a0d39, 4, 0x2b, 0, "u: pitch 0x2B (mov)"], [0x4a1114, 1, 0x2b, 0, "u: pitch 0x2B (add mem)"],
        [0x4a0de1, 1, 0x15, 0, "u: +0x15"], [0x4a0de4, 1, 2, 0, "u: +2"], [0x4a0e6c, 4, 0x66, 0, "u: name col x 0x66"], [0x4a0eea, 1, 0x28, 0, "u: +0x28"], [0x4a10e3, 1, 2, 0, "u: -2"],
    // kind 8 SCORE FUN_004a1140: header, text insets, legend x-0x32
    [0x4a1170, 1, 3, 0, "sc: +3"], [0x4a1173, 1, 3, 0, "sc: +3"], [0x4a118b, 1, 0, 3, "sc: -3"], [0x4a118f, 1, 9, 0, "sc: title +9"], [0x4a1198, 1, 3, 0, "sc: -3"], [0x4a11a4, 1, 2, 0, "sc: +2"],
    [0x4a12cf, 1, 4, 0, "sc: +4"], [0x4a12d4, 1, 4, 0, "sc: +4"], [0x4a12ed, 1, 0, 8, "sc: -8"], [0x4a21d6, 1, 0x32, 0, "sc: legend x-0x32"],
    // kind 0 INTEL FUN_004a2210: header, text insets, dossier column offsets, treaty matrix
    [0x4a2238, 1, 3, 0, "i: +3"], [0x4a2240, 1, 3, 0, "i: +3"], [0x4a224f, 1, 0, 3, "i: -3"], [0x4a2269, 1, 9, 0, "i: title +9"], [0x4a2275, 1, 2, 0, "i: +2"], [0x4a2281, 1, 3, 0, "i: -3"],
    [0x4a2379, 1, 4, 0, "i: +4"], [0x4a237d, 1, 4, 0, "i: +4"], [0x4a2394, 1, 0, 8, "i: -8"], [0x4a2426, 4, 0x9e, 0, "i: col x+0x9E"],
    [0x4a303e, 1, 0x14, 0, "i: +0x14"], [0x4a3129, 1, 0x14, 0, "i: matrix +0x14"],         // ===== ReportIf console painters (dest MainWin 0x7AEC64, HUD regions already scaled) =====
    // energy 0x4a84a0
    [0x4a84d4, 1, 6, 0, "ce: L cursor x+6"], [0x4a84d7, 1, 6, 0, "ce: y+6"], [0x4a84ed, 1, 0xc, 0, "ce: w-0xC"], [0x4a8504, 1, 0xc, 0, "ce: h-0xC"], [0x4a852e, 1, 6, 0, "ce: title h lineH+6"],
    [0x4a8623, 1, 2, 0, "ce: list top +2"], [0x4a8649, 1, 3, 0, "ce: list +3"], [0x4a8656, 1, 3, 0, "ce: list +3"], [0x4a868c, 1, 3, 0, "ce: list +3"],
    [0x4a8a99, 1, 0xa, 0, "ce: centre title y+10"],
    [0x4a8bee, 1, 6, 0, "ce: R cursor x+6"], [0x4a8bf1, 1, 6, 0, "ce: y+6"], [0x4a8c05, 1, 0xc, 0, "ce: w-0xC"], [0x4a8c14, 1, 0xc, 0, "ce: h-0xC"], [0x4a8c1d, 1, 6, 0, "ce: title h +6"],
    [0x4a8cd8, 1, 2, 0, "ce: list top +2"], [0x4a8cfe, 1, 3, 0, "ce: +3"], [0x4a8d0b, 1, 3, 0, "ce: +3"], [0x4a8d41, 1, 3, 0, "ce: +3"],     // bases 0x4a9050 (governor panel L, base locator R)
    [0x4a90aa, 1, 9, 0, "cb: gov y+9"], [0x4a90b3, 1, 0x28, 0, "cb: gov +0x28"], [0x4a90b6, 1, 6, 0, "cb: +6"], [0x4a90c1, 1, 0x12, 0, "cb: -0x12"], [0x4a90d1, 1, 0x2e, 0, "cb: -0x2E"],
    [0x4a90d4, 1, 6, 0, "cb: x+6"], [0x4a90e5, 1, 0xc, 0, "cb: w-0xC"], [0x4a90f3, 1, 0x1a, 0, "cb: title box h 0x1A"], [0x4a9112, 1, 6, 0, "cb: -6"], [0x4a919e, 1, 3, 0, "cb: +3"],
    [0x4a9ccd, 1, 0xa, 0, "cb: centre title y+10"],
    [0x4a9e01, 1, 6, 0, "cb: R x+6"], [0x4a9e04, 1, 6, 0, "cb: R y+6"], [0x4a9e19, 1, 0xc, 0, "cb: w-0xC"], [0x4a9e26, 1, 0xc, 0, "cb: h-0xC"], [0x4a9e42, 1, 6, 0, "cb: title h +6"],
    [0x4a9e58, 4, 3, 0, "cb: locator inset +3 (imm32)"], [0x4a9e5d, 4, 0, 3, "cb: locator inset -3 (imm32)"], [0x4a9e94, 1, 3, 0, "cb: +3"], [0x4a9e9c, 1, 3, 0, "cb: +3"],     // projects 0x4aa0b0
    [0x4aa16a, 1, 6, 0, "cp: x+6"], [0x4aa16d, 1, 6, 0, "cp: y+6"], [0x4aa182, 1, 0xc, 0, "cp: w-0xC"], [0x4aa199, 1, 0xc, 0, "cp: h-0xC"], [0x4aa1a3, 1, 6, 0, "cp: title h +6"],
    [0x4aa1c8, 1, 6, 0, "cp: body -6"], [0x4aa1cb, 1, 2, 0, "cp: body +2"], [0x4aa1f2, 1, 3, 0, "cp: +3"], [0x4aa1ff, 1, 3, 0, "cp: +3"], [0x4aa5c6, 1, 0xa, 0, "cp: centre title y+10"],
    [0x4aa64e, 1, 6, 0, "cp: R x+6"], [0x4aa651, 1, 6, 0, "cp: R y+6"], [0x4aa666, 1, 0xc, 0, "cp: w-0xC"], [0x4aa673, 1, 0xc, 0, "cp: h-0xC"], [0x4aa68f, 1, 6, 0, "cp: title h +6"],
    [0x4aa6a5, 4, 3, 0, "cp: locator +3"], [0x4aa6aa, 4, 0, 3, "cp: locator -3"], [0x4aa6e1, 1, 3, 0, "cp: +3"], [0x4aa6ee, 1, 3, 0, "cp: +3"],     // satellites 0x4aa970 (select faction / select satellite target panels, inline button group)
    [0x4aa9a3, 1, 6, 0, "cs: x+6"], [0x4aa9a6, 1, 6, 0, "cs: y+6"], [0x4aa9bb, 1, 0xc, 0, "cs: w-0xC"], [0x4aa9d2, 1, 0, 0xc, "cs: h-0xC"], [0x4aaa0c, 1, 0, 8, "cs: -8"],
    [0x4aab65, 1, 6, 0, "cs: x+6"], [0x4aab68, 1, 6, 0, "cs: y+6"], [0x4aab7d, 1, 0xc, 0, "cs: w-0xC"], [0x4aab94, 1, 0xc, 0, "cs: h-0xC"], [0x4aab9e, 1, 6, 0, "cs: title h +6"],
    [0x4aabc3, 1, 6, 0, "cs: body -6"], [0x4aabc6, 1, 2, 0, "cs: body +2"], [0x4aabed, 1, 3, 0, "cs: +3"], [0x4aabfa, 1, 3, 0, "cs: +3"], [0x4aaf01, 1, 0xa, 0, "cs: centre title y+10"],
    [0x4aaf99, 1, 6, 0, "cs: R x+6"], [0x4aaf9c, 1, 6, 0, "cs: R y+6"], [0x4aafb0, 1, 0xc, 0, "cs: w-0xC"], [0x4aafbf, 1, 0, 0xc, "cs: h-0xC"], [0x4aaff9, 1, 0, 8, "cs: -8"],
    [0x4ab13f, 1, 6, 0, "cs: x+6"], [0x4ab142, 1, 6, 0, "cs: y+6"], [0x4ab156, 1, 0xc, 0, "cs: w-0xC"], [0x4ab162, 1, 0xc, 0, "cs: h-0xC"], [0x4ab16b, 1, 6, 0, "cs: title h +6"],
    [0x4ab199, 1, 2, 0, "cs: +2"], [0x4ab19c, 1, 6, 0, "cs: -6"], [0x4ab1c5, 1, 3, 0, "cs: +3"], [0x4ab1d5, 1, 3, 0, "cs: +3"],     [0x4ab295, 1, 9, 0, "cs: target btn x+9"], [0x4ab298, 1, 0x20, 0, "cs: target btn +0x20"], [0x4ab2a8, 1, 0x12, 0, "cs: target btn w-0x12"], [0x4ab362, 1, 0x14, 0, "cs: target btn h 0x14"],
    [0x4ab49c, 1, 0x16, 0, "cs: row step 0x16"],     // units 0x4ab600
    [0x4ab623, 1, 6, 0, "cu: x+6"], [0x4ab626, 1, 6, 0, "cu: y+6"], [0x4ab63b, 1, 0xc, 0, "cu: w-0xC"], [0x4ab652, 1, 0xc, 0, "cu: h-0xC"], [0x4ab65c, 1, 6, 0, "cu: title h +6"],
    [0x4ab681, 1, 6, 0, "cu: body -6"], [0x4ab684, 1, 2, 0, "cu: body +2"], [0x4ab6ab, 1, 3, 0, "cu: +3"], [0x4ab6b8, 1, 3, 0, "cu: +3"],     [0x4ab7a7, 1, 3, 0, "cu: text +3"], [0x4ab7aa, 1, 4, 0, "cu: text +4"], [0x4ab7b3, 1, 0, 8, "cu: -8"],     [0x4aba95, 1, 5, 0, "cu: y+=5"], [0x4abc13, 1, 0xa, 0, "cu: centre title y+10"],
    [0x4abc9b, 1, 6, 0, "cu: R x+6"], [0x4abc9e, 1, 6, 0, "cu: R y+6"], [0x4abcb2, 1, 0xc, 0, "cu: w-0xC"], [0x4abcc1, 1, 0xc, 0, "cu: h-0xC"], [0x4abcca, 1, 6, 0, "cu: title h +6"],
    [0x4abcef, 1, 6, 0, "cu: body -6"], [0x4abcf2, 1, 2, 0, "cu: body +2"], [0x4abd1c, 1, 3, 0, "cu: +3"], [0x4abd1f, 1, 3, 0, "cu: +3"],     // score 0x4abe70
    [0x4abe90, 1, 6, 0, "csc: x+6"], [0x4abe93, 1, 6, 0, "csc: y+6"], [0x4abea8, 1, 0xc, 0, "csc: w-0xC"], [0x4abebf, 1, 0, 0xc, "csc: h-0xC"], [0x4ac046, 1, 0xa, 0, "csc: centre title y+10"],
    [0x4ac0ce, 1, 6, 0, "csc: R x+6"], [0x4ac0d1, 1, 6, 0, "csc: R y+6"], [0x4ac0e5, 1, 0xc, 0, "csc: w-0xC"], [0x4ac0f1, 1, 0, 0xc, "csc: h-0xC"],
    // intel 0x4ac140
    [0x4ac1af, 1, 6, 0, "ci: x+6"], [0x4ac1b2, 1, 6, 0, "ci: y+6"], [0x4ac1c4, 1, 0xc, 0, "ci: w-0xC"], [0x4ac1de, 1, 0xc, 0, "ci: h-0xC"], [0x4ac209, 1, 6, 0, "ci: title h +6"],
    [0x4ac2d3, 1, 2, 0, "ci: +2"], [0x4ac2f3, 1, 3, 0, "ci: +3"], [0x4ac300, 1, 3, 0, "ci: +3"], [0x4ac336, 1, 3, 0, "ci: +3"], [0x4ac5fe, 1, 0xa, 0, "ci: centre title y+10"],
    [0x4ac64f, 1, 6, 0, "ci: R x+6"], [0x4ac652, 1, 6, 0, "ci: R y+6"], [0x4ac666, 1, 0xc, 0, "ci: w-0xC"], [0x4ac675, 1, 0xc, 0, "ci: h-0xC"], [0x4ac67e, 1, 6, 0, "ci: title h +6"],
    [0x4ac741, 1, 2, 0, "ci: +2"], [0x4ac761, 1, 3, 0, "ci: +3"], [0x4ac76e, 1, 3, 0, "ci: +3"], [0x4ac7a4, 1, 3, 0, "ci: +3"],
  ];

  // ===== v4 rows (2026-09-07, from the grand-probe run: 4K g=40 + 1600 g=25 logs, canvas dumps, decompiles) =====
  // Same row law/format as ROWS ([addr, width, a, b, label] -> s(a)-s(b); sign follows the ENCODED immediate).
  const ROWS_V4 = [
    // --- ReportIf_activate 0x4A41D0: console button builds that the shared bake left native (y/h 20-px rows inside the
    //     already-scaled HUD panels; x/w derive from the panel rect). GOVERNOR/BEST BASES toggles (0xd0a/0xd0b),
    //     bases mode tabs (0x8b3..0x8b5, ReportWin canvas), sat tabs (0xd3c/0xd3d), ATTACK! (0xd3e), governor list
    //     (0xcef.. 7 rows), automate-units list (3 rows). Split seams -1/+1 (dec/lea) left native (1px).
    [0x4a4734, 1, 9, 0, "gov toggle x = panel+9"], [0x4a4737, 1, 9, 0, "gov toggle y = panel+9"], [0x4a4749, 1, 0x12, 0, "gov toggle w = panel-0x12"],
    [0x4a47a3, 1, 0x14, 0, "GOVERNOR h 0x14"], [0x4a4851, 1, 0x14, 0, "BEST BASES h 0x14"],
    [0x4a490d, 1, 3, 0, "mode tabs x = clipL+3"], [0x4a491d, 1, 0xb, 0, "mode tabs y = clipT+lineH+0xb"], [0x4a492f, 1, 6, 0, "mode tabs w = clipW-6"],
    [0x4a4970, 1, 0x14, 0, "PRODUCTION h"], [0x4a49a3, 1, 0, 2, "PRODUCTION R = third-2"], [0x4a4a49, 1, 0x14, 0, "CITIZENS h"], [0x4a4b1b, 1, 0x14, 0, "GARRISON h"], [0x4a4b57, 1, 2, 0, "GARRISON L = 2*third+2"],
    [0x4a4c1e, 1, 3, 0, "sat tabs x = clipL+3"], [0x4a4c2d, 1, 0xb, 0, "sat tabs y = clipT+lineH+0xb"], [0x4a4c46, 1, 6, 0, "sat tabs w = clipW-6"],
    [0x4a4c84, 1, 0x14, 0, "SAT SUMMARY h"], [0x4a4ca2, 1, 0, 1, "SAT SUMMARY R = half-1"], [0x4a4d51, 1, 0x14, 0, "ATTACK VIEW h"], [0x4a4d7e, 1, 1, 0, "ATTACK VIEW L = half+1"],
    [0x4a4e5a, 1, 0, 6, "ATTACK! B = textB-6"], [0x4a4e5d, 1, 0, 0x1a, "ATTACK! T = textB-0x1a"],
    [0x4a4f07, 1, 9, 0, "gov list x = panel+9"], [0x4a4f0a, 1, 0x23, 0, "gov list y = panel+0x23"], [0x4a4f1b, 1, 0x12, 0, "gov list w = panel-0x12"],
    [0x4a4f60, 1, 0x14, 0, "gov btn1 h"], [0x4a4fdb, 1, 0x16, 0, "gov y += 0x16"], [0x4a504e, 1, 0x14, 0, "gov btn2 h"], [0x4a50c9, 1, 0x16, 0, "gov y += 0x16"],
    [0x4a513f, 1, 0x14, 0, "gov btn3 h"], [0x4a51b7, 1, 0x16, 0, "gov y += 0x16"], [0x4a522a, 1, 0x14, 0, "gov btn4 h"], [0x4a52a5, 1, 0x16, 0, "gov y += 0x16"],
    [0x4a5318, 1, 0x14, 0, "gov btn5 h"], [0x4a5393, 1, 0x16, 0, "gov y += 0x16"], [0x4a53d2, 1, 0x14, 0, "gov btn6 h"], [0x4a544d, 1, 0x16, 0, "gov y += 0x16"], [0x4a548c, 1, 0x14, 0, "gov btn7 h"],
    [0x4a5505, 1, 9, 0, "unit list x = panel+9"], [0x4a5508, 1, 0x20, 0, "unit list y = panel+0x20"], [0x4a551e, 1, 0x12, 0, "unit list w = panel-0x12"],
    [0x4a555d, 1, 0x14, 0, "unit btn1 h"], [0x4a55d8, 1, 0x16, 0, "unit y += 0x16"], [0x4a5617, 1, 0x14, 0, "unit btn2 h"], [0x4a5692, 1, 0x16, 0, "unit y += 0x16"], [0x4a56df, 1, 0x14, 0, "unit btn3 h"],
    // --- kind 6 satellites FUN_0049f350 orbit view: frame 0x240x0xd2 centred in the clip (+0x14 y), inset +-3, orbit radius
    //     h/2-10, satellite dots 2x2 (FUN_0049fe40). The planet flic blit is scaled by the G bracket + recentred (hooks).
    [0x49fa5c, 4, 0x240, 0, "sat frame w (field 59A0)"], [0x49fa63, 4, 0, 0x240, "sat frame x = (clipL+clipR-0x240)/2"], [0x49fa6d, 4, 0xd2, 0, "sat frame h (field 59A4)"],
    [0x49fa87, 4, 0, 0xd2, "sat frame y = (clipT+textB-0xd2)/2"], [0x49fa9a, 1, 0x14, 0, "sat frame y+0x14"], [0x49faa7, 4, 0xd2, 0, "sat frame B = y+0xd2"], [0x49fab4, 4, 0x240, 0, "sat frame R = x+0x240"],
    [0x49fb8b, 1, 3, 0, "sat frame inset L+3"], [0x49fb8e, 1, 3, 0, "sat frame inset T+3"], [0x49fb92, 4, 0, 3, "sat frame inset R/B-3"], [0x49fc17, 1, 0, 10, "orbit radius = h/2-10"],
    [0x49ff65, 1, 2, 0, "sat dot w 2"], [0x49ff67, 1, 2, 0, "sat dot h 2"],
    // --- kind 4 bases FUN_0049d540 CITIZENS/GARRISON columns (the rows v1 dropped): now that the face blits (G bracket) and
    //     the veh_draw size (poke) scale, the icon steps/clamps/offsets scale with them.
    [0x49e3b9, 4, 0x22, 0, "citizens step 0x22 (few)"], [0x49e3cb, 4, 0xe2, 0, "citizens budget R-L-0xe2"], [0x49e3d9, 1, 0x22, 0, "citizens step clamp 0x22"], [0x49e3dd, 4, 0x22, 0, "citizens step 0x22 (clamped)"],
    [0x49e3f7, 1, 0, 0x20, "citizens x0 = R+step-0x20"], [0x49e3fa, 1, 0x12, 0, "citizens y = rowB-0x12"],
    [0x49e9cb, 4, 0x28, 0, "garrison step 0x28 (few)"], [0x49e9da, 4, 0xe8, 0, "garrison budget R-L-0xe8"], [0x49e9e9, 1, 0x28, 0, "garrison step clamp 0x28"], [0x49e9ed, 4, 0x28, 0, "garrison step 0x28 (clamped)"],
    [0x49ea03, 1, 0, 0x2d, "garrison x0 = R+step-0x2d"],
    // --- Hall of Fame load_hoficons 0x448400 (wide branch): logical canvas 800x600, content origin 0x77/0x50, window
    //     0x400x0x300 at ((SW-0x400)/2, SH-0x300), the 24 rect immediates, +0x10d shared by two rects. (+0x77 imm8 for
    //     +0xA2C overflows at g=40 -> field poke at load_hoficons leave.)
    [0x448441, 4, 0x320, 0, "hof canvas w 800"], [0x44844b, 4, 0x258, 0, "hof canvas h 600"], [0x44845a, 4, 0x77, 0, "hof content x 0x77"], [0x4484c0, 4, 0x50, 0, "hof content y 0x50"],
    [0x4484fc, 4, 0, 0x400, "hof win x = (SW-0x400)/2"], [0x448511, 4, 0, 0x300, "hof win y = SH-0x300"], [0x448516, 4, 0x300, 0, "hof win h 0x300"], [0x44851d, 4, 0x400, 0, "hof win w 0x400"],
    [0x448586, 4, 0x10d, 0, "hof r1.T/r2.T 0x10d"], [0x448590, 4, 0x1e, 0, "hof r0.L"], [0x44859a, 4, 0x10e, 0, "hof r0.T"], [0x4485a4, 4, 0x123, 0, "hof r0.R"], [0x4485ae, 4, 0x147, 0, "hof r0.B"],
    [0x4485b8, 4, 0x12f, 0, "hof r1.L"], [0x4485c8, 4, 0x21d, 0, "hof r1.R"], [0x4485d2, 4, 0x183, 0, "hof r1.B"], [0x4485dc, 4, 0x228, 0, "hof r2.L"], [0x4485ec, 4, 0x2fa, 0, "hof r2.R"], [0x4485f6, 4, 0x21f, 0, "hof r2.B"],
    [0x448600, 4, 0x15, 0, "hof r3.L (cat row)"], [0x44860a, 4, 0x7b, 0, "hof r3.T"], [0x448614, 4, 0x303, 0, "hof r3.R"], [0x44861e, 4, 0xed, 0, "hof r3.B"],
    [0x448628, 4, 0x4c, 0, "hof r4.L (fac row)"], [0x448632, 4, 0x27, 0, "hof r4.T"], [0x44863c, 4, 0x2d4, 0, "hof r4.R"],
    [0x44864c, 4, 0x128, 0, "hof r5.L"], [0x448656, 4, 0x187, 0, "hof r5.T"], [0x448660, 4, 0x224, 0, "hof r5.R"], [0x44866a, 4, 0x248, 0, "hof r5.B"],
    // --- Hall of Fame painter 0x448D90: crest inset, analysis text insets, category band, panel titles, score rows.
    //     (The two backdrop copy_4 pushes 0x400/0x300 and 800/600 stay native = SOURCE dims for the stretch replacement.)
    [0x449041, 1, 9, 0, "hof crest x = r5.L+9"], [0x449050, 1, 0xa, 0, "hof crest y = r5.T+10"], [0x449093, 1, 3, 0, "hof analysis x+3"], [0x449096, 1, 3, 0, "hof analysis y+3"],
    [0x4490af, 1, 6, 0, "hof analysis w-6"], [0x4490be, 1, 6, 0, "hof analysis h-6"],
    [0x449efb, 1, 0x15, 0, "hof band h 0x15"], [0x449f0e, 1, 0x14, 0, "hof band w = tw+0x14"], [0x449f11, 1, 0xf, 0, "hof band y = +0xf"], [0x449f31, 4, 0x186, 0, "hof band x = -tw/2+0x186"],
    [0x449f4e, 1, 0x10, 0, "hof title y = +0x10"], [0x449f66, 4, 0x320, 0, "hof title centre w 800"],
    [0x44a052, 4, 0xf7, 0, "hof panel title y +0xf7"], [0x44a058, 1, 0x1c, 0, "hof TOP5 x +0x1c"], [0x44a070, 4, 0x109, 0, "hof TOP5 w 0x109"],
    [0x44a0ca, 4, 0xf7, 0, "hof panel title y +0xf7"], [0x44a0cf, 4, 0x12e, 0, "hof MAP x +0x12e"], [0x44a0ea, 4, 0xf0, 0, "hof MAP w 0xf0"],
    [0x44a139, 4, 0xf7, 0, "hof panel title y +0xf7"], [0x44a13e, 4, 0x227, 0, "hof ANALYSIS x +0x227"], [0x44a159, 4, 0xd4, 0, "hof ANALYSIS w 0xd4"],
    [0x44a1f0, 1, 3, 0, "hof score row y+3"], [0x44a463, 1, 6, 0, "hof score row step +6"],
  ];
  { const seen = {}; for (const r of ROWS) seen[r[0]] = 1; let dup = 0; for (const r of ROWS_V4) { if (seen[r[0]]) { log("ROWS_V4 DUPLICATE " + hex(r[0]) + " " + r[4]); dup++; } else { seen[r[0]] = 1; ROWS.push(r); } } log("v4 rows merged: " + ROWS_V4.length + " (dup " + dup + ") -> " + ROWS.length); }
  // ===== v5 rows (2026-09-07 evening, from the v4 run + user shots) =====
  const ROWS_V5 = [
    // console panel TITLE y = strip.T + 4 (the `add reg,4` right before each Buffer_write_cent_l_5 title; v1b had lumped
    // these with the pointer-stride `add reg,4` loop rows -- the disasm shows `mov ebx,[esi+0x10]; add ebx,4; push ebx`)
    [0x4a85de, 1, 4, 0, "energy BASE EXPENDITURES title y+4"], [0x4a8c93, 1, 4, 0, "energy MAINTENANCE COSTS title y+4"],
    [0x4a9f38, 1, 4, 0, "bases BASE LOCATOR title y+4"], [0x4aa28b, 1, 4, 0, "projects PROJECT DESCRIPTION title y+4"],
    [0x4aac89, 1, 4, 0, "sat SELECT FACTION TARGET title y+4"], [0x4ab256, 1, 4, 0, "sat SELECT SATELLITE TARGET title y+4"],
    [0x4ab744, 1, 4, 0, "units UNIT TYPES title y+4"], [0x4abdb2, 1, 4, 0, "units AUTOMATE UNITS title y+4"],
    [0x4ac286, 1, 4, 0, "intel left title y+4"], [0x4ac6f4, 1, 4, 0, "intel right title y+4"],
    // Hall of Fame CLOSE rect (load_hoficons): x=+0x22a, y=+0x22c, w=0xce, h=0x16 (were missing in v4 -> native rect at (851,756))
    [0x448c85, 4, 0x22c, 0, "hof CLOSE y +0x22c"], [0x448c8b, 4, 0x22a, 0, "hof CLOSE x +0x22a"], [0x448c9d, 4, 0xce, 0, "hof CLOSE w 0xce"], [0x448ca3, 1, 0x16, 0, "hof CLOSE h 0x16"],
  ];
  // ===== v12 rows (2026-09-08, satellites save): SELECT FACTION TARGET buttons (RI+0x13778.. x7, built in ReportIf_activate
  // with a native cursor: x=panel+9, y=panel+0x20, w=panel-0x12, h=0x14, y+=0x16 per faction)
  const ROWS_V12 = [
    [0x4a5755, 1, 9, 0, "faction-target x = panel+9"], [0x4a5758, 1, 0x20, 0, "faction-target y = panel+0x20"], [0x4a576a, 1, 0x12, 0, "faction-target w = panel-0x12"],
    [0x4a58a6, 1, 0x14, 0, "faction-target h 0x14"], [0x4a591f, 1, 0x16, 0, "faction-target y += 0x16"],
  ];
  for (const r of ROWS_V12) ROWS.push(r);
  // ===== v13 rows: satellite ATTACK explosion (sat_expl_start 0x49FFD0): patch origin = sat dot - (0x15,0x17), patch/update
  // rect 0x2B x 0x2F (background save Buffer_init + copy_4 + the e318/e31c update rect); the sprite frames draw through the
  // scale globals (bracketed in the hooks).
  const ROWS_V13 = [
    [0x4a0063, 1, 0, 0x17, "expl y = satY-0x17"], [0x4a0080, 1, 0, 0x15, "expl x = satX-0x15"], [0x4a008b, 1, 0x2b, 0, "expl R = x+0x2b"], [0x4a008e, 1, 0x2f, 0, "expl B = y+0x2f"],
    [0x4a0090, 1, 0x2f, 0, "expl patch Buffer_init h 0x2f"], [0x4a0092, 1, 0x2b, 0, "expl patch Buffer_init w 0x2b"], [0x4a00b3, 1, 0x2f, 0, "expl patch copy h 0x2f"], [0x4a00b5, 1, 0x2b, 0, "expl patch copy w 0x2b"],
  ];
  for (const r of ROWS_V13) ROWS.push(r);
  { const seen = {}; for (const r of ROWS) seen[r[0]] = 1; let dup = 0; for (const r of ROWS_V5) { if (seen[r[0]]) { log("ROWS_V5 DUPLICATE " + hex(r[0]) + " " + r[4]); dup++; } else { seen[r[0]] = 1; ROWS.push(r); } } log("v5 rows merged: " + ROWS_V5.length + " (dup " + dup + ") -> " + ROWS.length); }
  // ---------------- caves (scratchpad asm_kinds_caves.py, Unicorn ALL-OK g16/22/25/40) ----------------
  const CAVES = [
    // site, total bytes, expected original hex, cave hex
    [0x49eb6f, 12, "b8f712da4bf7e9c1fa048bc2", "53bb360000000faf1d408766008d1c5d0f000000c1fb0589c899f7fb5b89c2687beb4900c3", "projects rows = h / s(0x36)"],
    [0x49ee8f, 22, "8d3cc500000000898e140a00002bf88b45cc8d44f802", "898e140a00008bbea459000051b9020000000faf0d408766008d0c4d0f000000c1f90501cf0faff88b45cc01f801c85968a5ee4900c3", "projects row y = top + i*(cell+s2) + s2"],
    [0x4a0974, 12, "b883bea02ff7e9c1fa038bc2", "53bb2b0000000faf1d408766008d1c5d0f000000c1fb0589c899f7fb5b89c26880094a00c3", "units rows = h / s(0x2B)"],
  ];
  // v2 imm32 caves for the two GEOMETRY imm8 overflows (position-independent: push resume; ret). Built at arm time
  // from s() so one table serves every g. Flags: the displaced test/push sequence is replayed verbatim after the add.
  const hx = a => a.map(x => (x & 0xff).toString(16).padStart(2, "0")).join("");
  const CAVES2 = () => [
    // bases: add edx,0x3c / test eax,eax (5B) @0x49e129 -> add edx,imm32; test eax,eax; push 0x49e12e; ret
    [0x49e129, 5, "83c23c85c0", hx([0x81, 0xC2].concat(d32(s(0x3c)), [0x85, 0xC0, 0x68], d32(0x49e12e), [0xC3])), "bases name x+s(0x3C)"],
    // intel: add eax,0x7d / push ebx / push eax (5B) @0x4a3407 -> add eax,imm32; push ebx; push eax; push 0x4a340c; ret
    [0x4a3407, 5, "83c07d5350", hx([0x05].concat(d32(s(0x7d)), [0x53, 0x50, 0x68], d32(0x4a340c), [0xC3])), "intel text x+s(0x7D)"],
  ];

  let armedOnce = false;
  function arm() {
    if (armedOnce) return; armedOnce = true;
    g = gNow();
    if (g <= 16) { log("g=" + g + " <= 16: proto disarmed (native identity). Frame probe still active."); return; }
    let applied = 0, skipped = 0, overflow = 0, ident = 0;
    for (const [addr, w, a, b, label] of ROWS) {
      const p = VA(addr), want = s(a) - s(b), vanilla = a - b;
      const cur = w === 4 ? p.readS32() : p.readS8();
      if (cur !== vanilla) { log("IDENT skip @" + hex(addr) + " have " + cur + " expect vanilla " + vanilla + " (" + label + ")"); ident++; continue; }
      if (w === 1 && (want < -128 || want > 127)) { log("OVERFLOW skip @" + hex(addr) + " " + label + " -> " + want); overflow++; continue; }
      Memory.protect(p, 4, "rwx");
      if (w === 4) p.writeS32(want); else p.writeS8(want);
      applied++;
    }
    let caves = 0;
    for (const [site, len, expect, code, label] of CAVES.concat(CAVES2())) {
      const c = makeCave(code);
      if (jmpTo(site, c, len, expect)) { caves++; log("CAVE " + label + " @" + hex(site) + " -> " + c); }
    }
    // v3: unit/base row ICON size = byte pokes of the `push imm8` size args at the 4 report call sites (law
    // scaling_laws.veh_size_scaled: s' = (((s+16)*g)>>4)-16; the baked thunk_hud_vehargs only serves the HUD buffers).
    let icons = 0;
    for (const [addr, sz, label] of [[0x4a0e01, -6, "units veh_draw"], [0x49dc3b, -6, "bases base_draw"], [0x49df44, -8, "bases veh_draw(prod)"], [0x49ea70, -8, "bases veh_draw(garrison)"]]) {
      const p = VA(addr);
      if (p.sub(1).readU8() !== 0x6A || p.readS8() !== sz) { log("ICON skip @" + hex(addr) + " " + label + " bytes " + p.sub(1).readU8().toString(16) + " " + p.readS8()); continue; }
      const nz = SL.vehSizeScaled(sz, g);
      if (nz < -128 || nz > 127) { log("ICON overflow @" + hex(addr) + " " + label + " -> " + nz); continue; }
      Memory.protect(p, 4, "rwx"); p.writeS8(nz); icons++;
      log("ICON " + label + " @" + hex(addr) + " size " + sz + " -> " + nz + " at g=" + g);
    }
    log("v2 applied " + applied + "/" + ROWS.length + " rows (ident-skip " + ident + ", overflow-skip " + overflow + "), caves " + caves + "/" + (CAVES.length + 2) + ", icon pokes " + icons + "/4 at g=" + g);
  }
  Interceptor.attach(VA(0x4A3460), { onLeave() { arm(); } });     // init_report_screen (desktop_init) -> g valid, before any page
  if (g > 16) arm();                                                  // attached late (spawn-less)? apply now

  // ======================= v3 GRAND PROBE: draw census + object/canvas dumps + hit paths + HOF + satellites =======================
  // One walk of every page at a resolution feeds the offline prototyping of kinds 0,3..8 + Hall of Fame. Attach set audited
  // 2026-09-07 (scratchpad audit/audit_attach.py): function ENTRIES only (the 2026-09-02 census set minus ScrollBar_init_inner,
  // whose entry is now the rw_stash detour) + clean new entries; no call-site hooks, nothing in a push;ret cluster head/resume.
  {
    const G_RW = 0x876478, G_RI = 0x885F38, G_HOF = 0x74DAF8;
    const RW_END = 0x885F38, RI_END = 0x885F38 + 0x20400, HOF_END = 0x74DAF8 + 0xC000;
    const G_KIND = 0x885F40, G_ITEM = 0x885F30, G_FACT = 0x8A4160;
    const G_SCREENW = 0x9b7b1c, G_SCREENH = 0x9b7b20, G_STRIPH = 0x7af59c;
    const G_REGIONS = 0x7af5a0, G_MAINBUF = 0x7aec64, G_MAINCLIP = 0x7aec94, G_WIDE = 0x8a4168;
    const G_MODAL_TOP = 0x9B7AE0, G_IFACE_TBL = 0x7AE778, G_IFACE_IDX = 0x7D392C;
    const G_SCALE_NUM = 0x696D18, G_SCALE_DEN = 0x696D1C, G_MAPZ_NUM = 0x691E6C, G_MAPZ_DEN = 0x691E70;
    const FONT_TBL = 0x93FC58;
    const DUMP_DIR = "D:/SmacxUi/work/_rw_dumps/";
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
    let inPainter = 0, hofOpen = false;
    function active() {
      const mt = safeU32(VA(G_MODAL_TOP));
      if (mt === VA(G_RW).toUInt32() || mt === VA(G_HOF).toUInt32()) return true;
      const idx = safeS32(VA(G_IFACE_IDX), -1);
      if (idx >= 0 && idx < 32 && safeS32(VA(G_IFACE_TBL).add(idx * 4)) === 5) return true;
      return inPainter > 0 || hofOpen;
    }
    const inReportCode = ret => (ret >= 0x448000 && ret < 0x44C000) || (ret >= 0x496000 && ret < 0x4AE000);

    // ---------------- canvas dumps: raw 8bpp rows (pitch-strided) + the buffer's synced RGBQUAD[256] at +0xA4 ----------------
    const MAX_DUMPS = 150; let ndump = 0; const dumpCount = {};
    function dumpBuf(buf, name, cap) {
      name = "g" + gval() + "_" + name;   // v4: keyed by g so a second-resolution run never overwrites the first
      const n = (dumpCount[name] = (dumpCount[name] || 0) + 1);
      if (n > cap || ndump >= MAX_DUMPS) return;
      try {
        const w = safeS32(buf.add(0x80)), h = -safeS32(buf.add(0x84)), pitch = safeS32(buf.add(0x4a8)), data = buf.add(0x54).readPointer();
        if (w <= 0 || h <= 0 || w > 8192 || h > 8192 || pitch < w || data.isNull()) { log("DUMP skip " + name + " w=" + w + " h=" + h + " pitch=" + pitch); return; }
        const fn = name + "_" + n + ".raw";
        const f = new File(DUMP_DIR + fn, "wb");
        f.write(data.readByteArray(pitch * h));
        f.write(buf.add(0xA4).readByteArray(1024));
        f.close(); ndump++;
        log("DUMP " + fn + " w=" + w + " h=" + h + " pitch=" + pitch + " bytes=" + (pitch * h) + "+1024pal dest=" + destTag(buf) + " k=" + kind() + " g=" + gval());
      } catch (e) { log("DUMP " + name + " threw " + e); }
    }
    const RWC = () => VA(G_RW).add(0x444), HOFC = () => VA(G_HOF).add(0x444), MAINB = () => VA(G_MAINBUF);

    // ---------------- site census ----------------
    const sites = {};   // key prim@ret -> {prim, ret, n, uniq:{sig:count}, first:kind}
    const CAP = 24;
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
    function A(va, prim, fn, fnLeave) {
      try {
        const cb = { onEnter(args) { try { fn.call(this, args, this.context); } catch (e) { log("hook " + prim + " threw " + e); } } };
        if (fnLeave) cb.onLeave = function (r) { try { fnLeave.call(this, r); } catch (e) { log("leave " + prim + " threw " + e); } };
        Interceptor.attach(VA(va), cb);
      } catch (e) { log("ATTACH FAIL " + prim + " " + hex(va) + ": " + e); }
    }
    const S = p => safeS32(p);
    const arg = (sp, n) => sp.add(4 * n);           // [esp+4n] (onEnter, n>=1)
    const zoomSig = () => " mapzoom=" + S(VA(G_MAPZ_NUM)) + "/" + S(VA(G_MAPZ_DEN)) + " G=" + S(VA(G_SCALE_NUM)) + "/" + S(VA(G_SCALE_DEN));

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
    // copy_4 (0x5DFF00) is Interceptor.replace'd by the v4 HOF lever below -> no census attach on it.
    A(0x55AF20, "base_draw", function (a, c) { rec("base_draw", c, arg(c.esp, 1).readPointer(), "base=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " size=" + S(arg(c.esp, 5)) + " fl=" + hex(S(arg(c.esp, 6))) + zoomSig()); });
    A(0x5594F0, "veh_draw", function (a, c) { rec("veh_draw", c, arg(c.esp, 1).readPointer(), "veh=" + S(arg(c.esp, 2)) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " size=" + S(arg(c.esp, 5)) + " fl=" + hex(S(arg(c.esp, 6))) + zoomSig()); });
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
    // widgets (ScrollBar_init_inner 0x6054D0 is the rw_stash detour since bake v1 -> not attached; attach_rect covers the report bars)
    A(0x60A670, "ListBox_attach", function (a, c) { rec("ListBox_attach", c, null, "ecx=" + hex(c.ecx.toUInt32()) + " edx=" + hex(c.edx.toUInt32()) + " st=" + [1, 2, 3, 4].map(i => hex(safeU32(arg(c.esp, i)))).join(",")); });
    A(0x605840, "ScrollBar_attach_rect", function (a, c) { rec("ScrollBar_attach_rect", c, null, "sb=" + destTag(c.ecx) + " r=" + rstr(arg(c.esp, 1).readPointer()) + " parent=" + destTag(arg(c.esp, 2).readPointer()) + " id=" + S(arg(c.esp, 3)) + " fl=" + S(arg(c.esp, 4))); });
    A(0x607210, "BaseButton_init", function (a, c) { rec("BaseButton_init", c, null, "btn=" + destTag(c.ecx) + " " + strAt(arg(c.esp, 1).readPointer(), 24) + " a3=" + S(arg(c.esp, 2)) + " xywh=" + [3, 4, 5, 6].map(i => S(arg(c.esp, i))).join(",") + " parent=" + destTag(arg(c.esp, 7).readPointer())); });
    A(0x629E50, "Flic_init", function (a, c) { rec("Flic_init", c, arg(c.esp, 1).readPointer(), "flic=" + destTag(c.ecx) + " " + strAt(arg(c.esp, 2).readPointer(), 40) + " xy=" + S(arg(c.esp, 3)) + "," + S(arg(c.esp, 4)) + " a6=" + S(arg(c.esp, 5))); });
    A(0x62A070, "Flic_draw_frame", function (a, c) { rec("Flic_draw_frame", c, null, "flic=" + destTag(c.ecx) + " wh=" + S(c.ecx.add(0x59c)) + "x" + S(c.ecx.add(0x5a0)) + " xy=" + S(arg(c.esp, 1)) + "," + S(arg(c.esp, 2))); });
    // hit rects: Spot_add(self, idx, flag, X, Y, W, H) thiscall; Spot_check(self, x, y, int* pos, int* type) -> idx
    A(0x5FA960, "Spot_add", function (a, c) { rec("Spot_add", c, c.ecx, "idx=" + S(arg(c.esp, 1)) + " fl=" + S(arg(c.esp, 2)) + " xywh=" + [3, 4, 5, 6].map(i => S(arg(c.esp, i))).join(",")); });
    let nspot = 0;
    A(0x5FAB00, "Spot_check", function (a, c) {
      this.ret = retVA(c); if (!inReportCode(this.ret) || nspot++ > 400) { this.skip = 1; return; }
      this.x = S(arg(c.esp, 1)); this.y = S(arg(c.esp, 2)); this.pp = arg(c.esp, 3).readPointer(); this.pt = arg(c.esp, 4).readPointer(); this.spot = destTag(c.ecx);
    }, function (r) {
      if (this.skip) return;
      log("SPOTCHECK " + this.spot + " xy=" + this.x + "," + this.y + " -> " + r.toInt32() + " pos=" + (this.pp.isNull() ? "-" : S(this.pp)) + " type=" + (this.pt.isNull() ? "-" : S(this.pt)) + " <-" + hex(this.ret) + " k=" + kind());
    });

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
      log("rw.cells btn_w/h+59A0/A4=" + S(o.add(0x59a0)) + "/" + S(o.add(0x59a4)) + " card_w=" + S(o.add(0x59a8)) + " sel=" + S(o.add(0x59ac)) + "/" + S(o.add(0x59b0)) + " basemask+59B4=" + hex(S(o.add(0x59b4))) + " unitmask+59F4=" + hex(S(o.add(0x59f4))) +
          " sortcol=" + S(o.add(0x5a08)) + " grp1sel=" + S(o.add(0x7c8c)) + " satsel=" + S(o.add(0x9f04)) + " modeTabSel(8a4178)=" + S(VA(0x8a4178)) + " unitFilter=" + S(VA(0x8a417c)) + " sortmode(87be80)=" + S(VA(0x87be80)));
      log("rw.scroll active=" + S(o.add(0xc0f8)) + " pos/min/max/page=" + [0xc0fc, 0xc100, 0xc104, 0xc108].map(x => S(o.add(x))).join("/") + " rowRect+E258=" + rstr(o.add(0xe258)) + " need/reinit=" + S(o.add(0xe26c)) + "/" + S(o.add(0xe270)) + " grp1row+7BF8=" + rstr(o.add(0x7bf8)));
      log("rw.btn id9=" + btnR(G_RW, 0x6560) + " id1=" + btnR(G_RW, 0x70ac) + " mode8B3/4/5=" + btnR(G_RW, 0x7c9c) + btnR(G_RW, 0x87e8) + btnR(G_RW, 0x9334) + " satD3C/D3D/D3E=" + btnR(G_RW, 0x9f14) + btnR(G_RW, 0xaa60) + btnR(G_RW, 0xb5ac));
      log("rw.energyList+5A0C: rect=" + rstr(o.add(0x5a0c + 0x474)) + " rowH+68=" + S(o.add(0x5a0c + 0x68)) + " +48=" + S(o.add(0x5a0c + 0x48)));
      if (kind() === 6) log("rw.sat orbit E2A0=" + rstr(o.add(0xe2a0)) + " E2B0=" + rstr(o.add(0xe2b0)) + " flicWH=" + S(o.add(0xf3d0)) + "x" + S(o.add(0xf3d4)) + " nSat=" + S(o.add(0xf918)) + " flic+E8A8 wh=" + S(o.add(0xe8a8 + 0x59c)) + "x" + S(o.add(0xe8a8 + 0x5a0)) + " flic+EE34 wh=" + S(o.add(0xee34 + 0x59c)) + "x" + S(o.add(0xee34 + 0x5a0)));
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
      log("hof.closeRect+22A..=" + ivec(o.add(0x22a), 4).join(",") + " +A894..=" + ivec(o.add(0xa894), 6).map(v => hex(v)).join(","));
    }
    function geomHash() {
      const o = VA(G_RW), r = VA(G_RI);
      let h = kind() | 0;
      for (const off of [0x474, 0x5974, 0xe258, 0x7bf8]) { const q = rect4(o.add(off)); h = ((h * 31) + q[0] + q[1] * 7 + q[2] * 13 + q[3] * 17) | 0; }
      for (const off of [0x5980, 0x59a0, 0x59a4, 0x59a8, 0xe268, 0xc104, 0xc108, 0x7c8c, 0x9f04, 0x59ac, 0x59b0]) h = ((h * 31) + S(o.add(off))) | 0;
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
      A(va, name, function () {
        inPainter++; const n = (pn[name] = (pn[name] || 0) + 1);
        if (n <= 3 || n % 50 === 0) log("PAINTER " + name + " #" + n + " k=" + kind() + " g=" + gval());
        if (name === "sat_anim" && n <= 2) {
          try {
            const o = VA(G_RW);
            log("FLIC+EE34 hex: " + hexdump(o.add(0xee34), { length: 0x5b0, header: false, ansi: false }).replace(/\n/g, " | "));
            log("FLIC+E8A8 hex: " + hexdump(o.add(0xe8a8), { length: 0x5b0, header: false, ansi: false }).replace(/\n/g, " | "));
          } catch (e) { log("flic hexdump threw " + e); }
        }
      }, function () {
        inPainter--;
        if (name.startsWith("ri_") && name !== "ri_chrome") dumpBuf(MAINB(), "main_" + name, 2);
        if (name === "sat_anim") dumpBuf(RWC(), "rw_sat_anim", 3);
        if (name === "sat_expl") dumpBuf(RWC(), "rw_sat_expl", 2);
        if (name === "bl_blink") dumpBuf(RWC(), "rw_bl_blink", 1);
      });
    }
    let lastHash = null, paintN = 0; const dumped = {};
    A(0x496d00, "rw_paint_dispatch", function () { inPainter++; paintN++; this.k = kind(); }, function () {
      inPainter--;
      const h = geomHash();
      const key = this.k + ":" + S(VA(G_RW).add(0x7c8c)) + ":" + S(VA(G_RW).add(0x9f04));
      if (h !== lastHash || !dumped[key]) { lastHash = h; rwDump("paint#" + paintN + " k=" + this.k + " hash=" + h); }
      const first = !dumped[key]; dumped[key] = (dumped[key] || 0) + 1;
      if (first || dumped[key] <= 2 || h !== lastHash) dumpBuf(RWC(), "rw_k" + this.k + "_m" + S(VA(G_RW).add(0x7c8c)) + "_s" + S(VA(G_RW).add(0x9f04)), 3);
    });
    A(0x4a3950, "show_page", function (a, c) { this.k = S(arg(c.esp, 1)); summary("before show_page k=" + this.k); log("show_page kind=" + this.k + "(" + (KINDNAME[this.k] || "?") + ") faction=" + S(arg(c.esp, 2)) + " data=" + S(arg(c.esp, 3))); inPainter++; },
      function () { inPainter--; riDump("post-show_page k=" + this.k); dumpBuf(MAINB(), "main_showpage_k" + this.k, 2); });
    A(0x4a41d0, "ReportIf_activate", function (a, c) { this.on = S(arg(c.esp, 1)); log("ReportIf_activate(" + this.on + ") " + envLine()); if (!this.on) summary("deactivate"); inPainter++; }, function () { inPainter--; });
    A(0x4a3fc0, "ri_on_redraw", function () { const n = (pn.ri_on_redraw = (pn.ri_on_redraw || 0) + 1); if (n <= 3) log("ri_on_redraw #" + n); });
    A(0x4a3930, "rw_close", function () { log("rw_close " + envLine()); summary("close k=" + kind()); });
    A(0x4a5f00, "rw_show", function () { log("rw_show " + envLine()); });
    A(0x4a5f20, "rw_hide", function () { log("rw_hide " + envLine()); });
    // input paths (all clean function entries; after-state + canvas dumps on leave)
    let nclick = 0;
    function selState() { const o = VA(G_RW); return "sel=" + S(o.add(0x59ac)) + "/" + S(o.add(0x59b0)) + " basemask=" + hex(S(o.add(0x59b4))) + " unitmask=" + hex(S(o.add(0x59f4))) + " item=" + S(VA(G_ITEM)) + " grp1=" + S(o.add(0x7c8c)) + " satsel=" + S(o.add(0x9f04)) + " blink=" + S(VA(0x8a4184)) + "," + S(VA(0x8a4188)); }
    A(0x496e10, "rw_on_l_click", function (a, c) { this.xy = S(arg(c.esp, 1)) + "," + S(arg(c.esp, 2)); log("CLICK L k=" + kind() + " xy=" + this.xy + " before " + selState()); },
      function (r) { log("CLICK L leave ret=" + r.toInt32() + " after " + selState()); if (nclick++ < 12) dumpBuf(RWC(), "rw_click_k" + kind(), 4); });
    A(0x497a60, "rw_on_dbl_click", function (a, c) { log("CLICK DBL k=" + kind() + " xy=" + S(arg(c.esp, 1)) + "," + S(arg(c.esp, 2)) + " " + selState()); });
    A(0x497f00, "rw_on_r_click", function (a, c) { log("CLICK R k=" + kind() + " xy=" + S(arg(c.esp, 1)) + "," + S(arg(c.esp, 2)) + " " + selState()); });
    A(0x498280, "rw_on_key", function (a, c) { log("KEY k=" + kind() + " a1=" + S(arg(c.esp, 1)) + " a2=" + hex(S(arg(c.esp, 2))) + " a3=" + S(arg(c.esp, 3))); });
    A(0x4a5f40, "ri_map_spot_click", function (a, c) { log("ri_map_spot_click a1=" + S(arg(c.esp, 1)) + " a2=" + S(arg(c.esp, 2)) + " k=" + kind()); });
    A(0x4986d0, "rw_on_button", function (a, c) { log("rw_on_button id=" + S(arg(c.esp, 1)) + " k=" + kind()); });
    A(0x4989f0, "rw_on_group_changed", function (a, c) { log("rw_on_group_changed a1=" + S(arg(c.esp, 1)) + " a2=" + S(arg(c.esp, 2)) + " k=" + kind()); });
    A(0x498180, "rw_sb_pos_a", function (a, c) { log("rw_sb_pos_changed(a) pos=" + S(arg(c.esp, 1)) + " k=" + kind()); });
    A(0x498200, "rw_sb_pos_b", function (a, c) { log("rw_sb_pos_changed(b) pos=" + S(arg(c.esp, 1)) + " k=" + kind()); });
    A(0x49d490, "rw_energy_listsel", function (a, c) { log("rw_energy_listsel a1=" + S(arg(c.esp, 1)) + " a2=" + S(arg(c.esp, 2)) + " " + selState()); });
    A(0x4a6050, "ri_list_selected", function (a, c) { log("ri_list_selected a1=" + S(arg(c.esp, 1)) + " a2=" + S(arg(c.esp, 2)) + " k=" + kind()); });
    A(0x4a0260, "sat_attack", function () { log("sat_attack popup " + selState()); });
    A(0x4a0810, "sat_edit", function () { log("sat_edit " + selState()); });

    // ---------------- Hall of Fame ----------------
    let hofHooked = false;
    A(0x44ae50, "hall_of_fame", function (a, c) {
      hofOpen = true; log("hall_of_fame(" + S(arg(c.esp, 1)) + ") " + envLine());
      if (!hofHooked) {
        hofHooked = true;
        try {
          const vt = VA(G_HOF).readPointer(); const slots = {};
          for (const off of [0x04, 0x08, 0x30, 0x44, 0x48, 0x4c, 0x58, 0x64, 0x70, 0xb0, 0xb8, 0x124]) slots[off.toString(16)] = hex(staticVA(vt.add(off).readPointer()));
          log("HOF vtbl=" + hex(staticVA(vt)) + " slots=" + JSON.stringify(slots));
          const paint = vt.add(0x30).readPointer();
          Interceptor.attach(paint, { onEnter() { inPainter++; const n = (pn.hof_paint = (pn.hof_paint || 0) + 1); if (n <= 3) log("PAINTER hof_paint #" + n + " @" + hex(staticVA(paint))); }, onLeave() { inPainter--; if (pn.hof_paint <= 3) hofDump("post-paint#" + pn.hof_paint); dumpBuf(HOFC(), "hof_paint", 4); } });
          const onbtn = vt.add(0xb0).readPointer();
          Interceptor.attach(onbtn, { onEnter() { log("hof_on_button id=" + S(this.context.esp.add(4)) + " sel=" + S(VA(G_HOF).add(0xa918))); }, onLeave() { hofDump("post-button"); dumpBuf(HOFC(), "hof_button", 6); } });
          const onclk = staticVA(vt.add(0x4c).readPointer());
          if (onclk >= 0x448000 && onclk < 0x44C000) Interceptor.attach(vt.add(0x4c).readPointer(), { onEnter() { log("hof_on_l_click xy=" + S(this.context.esp.add(4)) + "," + S(this.context.esp.add(8))); } });
          else log("hof on_l_click slot is shared (" + hex(onclk) + ") -> not hooked");
        } catch (e) { log("HOF vtbl hook failed: " + e); }
      }
    }, function () { hofDump("hall_of_fame returned"); summary("HOF close"); hofOpen = false; });
    A(0x448400, "load_hoficons", function () { log("load_hoficons enter " + envLine()); }, function () { hofDump("post-load_hoficons"); });
    A(0x4A3460, "init_report_screen", function () { }, function () { riDump("post-init_report_screen"); });
    A(0x496960, "rw_win_init", function () { }, function () { rwDump("post-win_init"); });

    setInterval(() => { const n = Object.keys(sites).length; if (n) log("tick: " + n + " sites, kind=" + kind() + " active=" + active() + " dumps=" + ndump); }, 15000);
    log("grand probe attached: " + TXT.length + " text writers, " + PAINTERS.length + " painters, dumps -> " + DUMP_DIR + "; " + envLine());
  }
  // ======================= v4 LEVERS (hooks): G brackets, satellite recentre, Hall of Fame window =======================
  // All hosts are function entries (audited 2026-09-07: 0x49fe40 / 0x5D8290 / 0x5DFF00 clean; blit_core / Sprite_draw_2 /
  // BaseButton_init are the same detoured entries the census already hooks; thunk_btn_gate_pre is the E8 helper the run-7
  // probe hooked). No call-site hooks. Interceptor.replace on Buffer_copy_4 (clean entry) = the bake shape (E8 retarget).
  {
    const RW = 0x876478, RI = 0x885F38, HOF = 0x74DAF8, PC = 0xA0C000;
    const G_NUM = VA(0x696D18), G_DEN = VA(0x696D1C);
    const S32 = p => { try { return p.readS32(); } catch (e) { return -0x7fffffff; } };
    const sva = p => p.sub(globalThis.TERRANX_BASE).toUInt32() + 0x400000;
    const retOf = ctx => sva(ctx.esp.readPointer());
    const once = {}; const L1 = (k, m) => { if (!once[k]) { once[k] = 1; log(m); } };
    function gEnter(self, tag) { const gg = gNow(); if (gg <= 16) return; self.gsave = [G_NUM.readS32(), G_DEN.readS32()]; G_NUM.writeS32(gg); G_DEN.writeS32(16); L1("G" + tag, "V4 G bracket armed for " + tag + " (was " + self.gsave.join("/") + ")"); }
    function gLeave(self) { if (self.gsave) { G_NUM.writeS32(self.gsave[0]); G_DEN.writeS32(self.gsave[1]); self.gsave = null; } }
    function att(va, name, cb) { try { Interceptor.attach(VA(va), cb); log("V4 attached " + name + " @" + hex(va)); } catch (e) { log("V4 ATTACH FAIL " + name + " @" + hex(va) + ": " + e); } }

    // (1) G bracket on Sprite_blit_scaled_core for the fixed-size sprite blits: bases CITIZENS faces (0x49e80b/0x49e8cf,
    //     30x38 talent/drone faces) and the Hall of Fame faction picture (0x44907b, 233x124).
    const GRETS = { 0x49e80b: "citizens face A", 0x49e8cf: "citizens face B", 0x44907b: "hof faction picture" };
    const CAT_LO = HOF + 0x5a04, FAC_LO = HOF + 0xa5c, STRIDE = 0xb4c;
    const isHofBtnCanvas = dest => { const b = dest - 0x444; const c = b - CAT_LO, f = b - FAC_LO; return (c >= 0 && c < 6 * STRIDE && c % STRIDE === 0) || (f >= 0 && f < 7 * STRIDE && f % STRIDE === 0); };
    att(0x5E4B9A, "blit_core G bracket", {
      onEnter() { const r = retOf(this.context); const tag = GRETS[r]; if (tag) gEnter(this, tag); },
      onLeave() { gLeave(this); }
    });
    // (2) satellites orbit view: the planet flic frame is drawn by Buffer_draw(canvas, key, e2a0, e2a4) from FUN_0049fe40
    //     (painter first frame + sat_anim_daemon + sat_expl_start) with G=1/1 -> bracket G, and recentre e2a0/e2a4 for the
    //     scaled size at FUN_0049fe40 entry (e2a8/e2ac = frame centre, f3d0/f3d4 = flic w/h).
    // v5: Buffer_draw is 0x5D8370 (FUN_0049fe40 calls it @0x49ff38; 0x5D8290 in v4 was the wrong entry). Same bracket also
    //     serves the Hall of Fame category/faction button ICONS (BaseButton sprite faces drawn through Buffer_draw into the
    //     button canvases -- no Sprite_draw_2 site touches them, so the v4 n/d rewrite never applied).
    att(0x5D8370, "Buffer_draw G bracket (sat planet + hof icons)", {
      onEnter() {
        const r = retOf(this.context), dest = this.context.esp.add(4).readPointer().toUInt32();
        if (r >= 0x49fe40 && r < 0x49ffb6 && S32(VA(0x885F40)) === 6) gEnter(this, "sat planet <-" + hex(r));
        else if (isHofBtnCanvas(dest)) gEnter(this, "hof icon <-" + hex(r) + " src " + S32(this.context.ecx.add(0x80)) + "x" + S32(this.context.ecx.add(0x84)));
      },
      onLeave() { gLeave(this); }
    });
    // v13: the attack explosion frames (sat_expl_step 0x4A0100..0x4A024F) draw through Sprite_draw_multi_table_dest_2
    //      0x616730 / Sprite_draw_table 0x5E8FF5 = the SCALE_NUM_G/DEN_G-driven table blit -> same G bracket keyed on the
    //      return address (the step's Buffer_draw patch RESTORE must stay 1/1 -- it is not bracketed).
    for (const [va, nm] of [[0x616730, "draw_multi_table_dest_2"], [0x5E8FF5, "Sprite_draw_table"]])
      att(va, nm + " G bracket (explosion)", {
        onEnter() { const r = retOf(this.context); if (r >= 0x4a0100 && r < 0x4a0250) gEnter(this, "explosion <-" + hex(r) + " via " + nm); },
        onLeave() { gLeave(this); }
      });
    att(0x49fe40, "sat draw recentre", {
      onEnter() {
        const gg = gNow(); if (gg <= 16) return;
        const o = this.context.ecx; if (o.toUInt32() !== VA(RW).toUInt32()) return;
        const w = S32(o.add(0xf3d0)), h = S32(o.add(0xf3d4)); if (w <= 0 || w > 2048 || h <= 0 || h > 2048) return;
        const nx = S32(o.add(0xe2a8)) - (s(w) >> 1), ny = S32(o.add(0xe2ac)) - (s(h) >> 1);
        o.add(0xe2a0).writeS32(nx); o.add(0xe2a4).writeS32(ny);
        L1("satc", "V4 sat planet recentred: flic " + w + "x" + h + " -> " + s(w) + "x" + s(h) + " at (" + nx + "," + ny + ") frame=(" + [0, 4, 8, 12].map(k => S32(o.add(0xe2b0 + k))).join(",") + ")");
      }
    });
    // (3) Hall of Fame: +0xA2C (content right = 0x77+800, imm8 overflow) from the scaled fields at load_hoficons' return.
    att(0x448400, "load_hoficons content-right poke", {
      onLeave() {
        const gg = gNow(); if (gg <= 16) return;
        const o = VA(HOF);
        o.add(0xa2c).writeS32(S32(o.add(0xa24)) + s(800));   // v5: +0xA1C is reused as the button cell width by then (v4 wrote 267)
        o.add(0xa30).writeS32(S32(o.add(0xa28)) + s(600));
        log("V4 hof fields: canvas " + S32(o.add(0xa1c)) + "x" + S32(o.add(0xa20)) + " content (" + [0xa24, 0xa28, 0xa2c, 0xa30].map(k => S32(o.add(k))).join(",") + ") win=(" + [0, 4, 8, 12].map(k => S32(o.add(0x474 + k))).join(",") + ") pos=(" + [0, 4, 8, 12].map(k => S32(o.add(0x13c + k))).join(",") + ")");
      }
    });
    // (4) Hall of Fame backdrops: the three 1:1 Buffer_copy_4 blits (frame.pcx 1024x768 @0x448e01, hof.pcx 800x600 @0x448e37,
    //     the saved world-map pcx into r1 @0x448fd1) become Buffer_copy_3 stretches to the scaled rects. Bake shape = E8
    //     retargets to a cave calling copy_3; proto = Interceptor.replace on the (clean) copy_4 entry, chaining to the
    //     original for every other caller.
    globalThis.RW_LISTRECTS = {};
    const COPY4 = VA(0x5DFF00), COPY3 = VA(0x5D9610);
    const copy4 = new NativeFunction(COPY4, "int", ["pointer", "pointer", "int", "int", "int", "int", "int", "int"], "thiscall");
    const copy3 = new NativeFunction(COPY3, "int", ["pointer", "pointer", "int", "int", "int", "int", "int", "int", "int", "int"], "thiscall");
    let nhofcopy = 0;
    try {
      Interceptor.replace(COPY4, new NativeCallback(function (self, dest, sx, sy, dx, dy, w, h) {
        try {
          const r = sva(this.returnAddress), gg = gNow();
          if (self.toUInt32() === 0x7aec64 && r >= 0x60B000 && r < 0x60D000) globalThis.RW_LISTRECTS[dest.toUInt32()] = [sx, sy, w, h];   // v10: ListBox bg copy from MAIN (console list @0x60c426; the RW-canvas list's is @0x60bbbf from RWc): list rect in MainWin coords
          if (gg > 16 && (r === 0x448e01 || r === 0x448e37 || r === 0x448fd1)) {
            let sw = w, sh = h, dw = s(w), dh = s(h);
            if (r === 0x448fd1) { sw = S32(self.add(0x80)); sh = -S32(self.add(0x84)); dw = w; dh = h; }
            if (nhofcopy++ < 12) log("V4 hof copy_4 @" + hex(r) + " -> copy_3 src " + sw + "x" + sh + " -> (" + dx + "," + dy + ") " + dw + "x" + dh);
            return copy3(self, dest, sx, sy, sw, sh, dx, dy, dw, dh);
          }
        } catch (e) { log("V4 copy_4 replacement threw " + e); }
        return copy4(self, dest, sx, sy, dx, dy, w, h);
      }, "int", ["pointer", "pointer", "int", "int", "int", "int", "int", "int"], "thiscall"));
      log("V4 copy_4 replacement installed");
    } catch (e) { log("V4 copy_4 replace FAILED: " + e); }
    // (5) Hall of Fame buttons: the 6 category (0x4f cells, ret 0x448995) and 7 faction (0x46, ret 0x448bc4) BaseButton_init
    //     rects: w/h -> s(), x/y re-centred for the scaled cell ((cell-native)/2 was computed with the native size).
    const HOFBTN = { 0x448995: 0x4f, 0x448bc4: 0x46 };
    att(0x607210, "hof BaseButton_init rects", {
      onEnter() {
        const gg = gNow(); if (gg <= 16) return;
        const r = retOf(this.context), nat = HOFBTN[r]; if (!nat) return;
        const sp = this.context.esp, sz = s(nat), d = (sz - nat) >> 1;
        sp.add(0xC).writeS32(S32(sp.add(0xC)) - d); sp.add(0x10).writeS32(S32(sp.add(0x10)) - d); sp.add(0x14).writeS32(sz); sp.add(0x18).writeS32(sz);
        L1("hb" + r, "V4 hof buttons @" + hex(r) + ": cell " + nat + " -> " + sz + " (shift -" + d + "), first at (" + S32(sp.add(0xC)) + "," + S32(sp.add(0x10)) + ")");
      }
    });
    // (6) Hall of Fame button FACES: FlatButton_draw's Sprite_draw_2(face, canvas, key, 0, 0, n, d) @ret 0x607f48 gets
    //     n/d = g/16 for the category/faction button canvases (the t_rw_iconblit mechanism; bake = extend its dest ranges).
    att(0x5E4B4A, "hof button face n/d", {
      onEnter() {
        const gg = gNow(); if (gg <= 16) return;
        const sp = this.context.esp; if (retOf(this.context) !== 0x607f48) return;
        if (!isHofBtnCanvas(sp.add(4).readPointer().toUInt32())) return;
        sp.add(0x14).writeS32(gg); sp.add(0x18).writeS32(16);
        L1("hface", "V4 hof button face n/d -> " + gg + "/16 (sprite " + S32(this.context.ecx.add(0x18)) + "x" + S32(this.context.ecx.add(0x1c)) + ")");
      }
    });
    // (7) Hall of Fame CLOSE (HOF+0x9dcc, bevel box-sprite FlatButton): admit it to popup_button_2dzoom by forcing
    //     thunk_btn_gate_pre's result (E8 helper; onLeave retval). Bake = one more static in the gate's table.
    // v5: admit every bevel-face FlatButton the report builds outside the shared bake's 4 statics: GOVERNOR/BEST BASES,
    //     the 7 governor + 3 automate-units list buttons (MainWin parent), the bases mode tabs, the sat tabs, ATTACK!
    //     (ReportWin parent) and the Hall of Fame CLOSE. Without the HIT their faces render 20 native rows in the scaled
    //     rect (the "vertically clipped" blue bars). Bake = more statics / a range test in thunk_btn_gate_pre.
    const ADMIT = {};
    for (const off of [0xd138, 0xdc84, 0x1bf9c, 0x1cae8, 0x1d634]) ADMIT[VA(RI).toUInt32() + off] = "RI+" + off.toString(16);
    for (let i = 0; i < 7; i++) ADMIT[VA(RI).toUInt32() + 0xe7d0 + i * 0xb4c] = "gov" + i;
    for (const off of [0x7c9c, 0x87e8, 0x9334, 0x9f14, 0xaa60, 0xb5ac]) ADMIT[VA(RW).toUInt32() + off] = "RW+" + off.toString(16);
    ADMIT[VA(HOF).toUInt32() + 0x9dcc] = "hof CLOSE";
    for (let i = 0; i < 7; i++) ADMIT[VA(RI).toUInt32() + 0x13778 + i * 0xb4c] = "sat faction-target " + i;   // v12
    for (let i = 0; i < 5; i++) ADMIT[VA(RI).toUInt32() + 0x18720 + i * 0xb4c] = "sat satellite-target " + i;  // v12
    att(PC + 0x24070, "btn gate admissions", {
      onEnter() { this.tag = gNow() > 16 ? ADMIT[this.context.esi.toUInt32()] : undefined; },
      onLeave(r) { if (this.tag) { L1("adm" + this.tag, "V5 gate admit " + this.tag + ": " + r.toInt32() + " -> 1"); r.replace(1); } }
    });
    log("V4 levers installed");
  }
  // ======================= v5 LEVERS: console list bars, slide rails, rail scrollbar, CHEATED font =======================
  {
    const RW = 0x876478, PC = 0xA0C000;
    const S32 = p => { try { return p.readS32(); } catch (e) { return -0x7fffffff; } };
    const once = {}; const L1 = (k, m) => { if (!once[k]) { once[k] = 1; log(m); } };
    function att(va, name, cb) { try { Interceptor.attach(VA(va), cb); log("V5 attached " + name + " @" + hex(va)); } catch (e) { log("V5 ATTACH FAIL " + name + " @" + hex(va) + ": " + e); } }
    // (1) console LIST scrollbars: the shared bake redirects only the LABS console's scroll_small/scroll_normal calls to
    //     t_rw_scrollsmall (g_scrollbar_w 12 -> s(12), inlist=1 -> t_rw_sbinit stashes the bar into g_rail_sb) /
    //     t_rw_scrollnormal (inlist=0). The energy (2 lists), bases (1) and intel (2) consoles call the same pair at their
    //     own sites -> same E8 retargets (zero Interceptor, the thunks self-gate on g). NB one g_rail_sb cell: on a
    //     two-list console the LAST attached bar gets the rail treatment (proto limitation, logged).
    const SMALL = PC + 0x23e00, NORMAL = PC + 0x23e40, SCROLL_SMALL = 0x5883D0, SCROLL_NORMAL = 0x588340;
    function retarget(site, target, expect, label) {
      const p = VA(site);
      try {
        if (p.readU8() !== 0xE8) { log("V5 retarget " + label + " @" + hex(site) + ": not a CALL"); return; }
        const cur = site + 5 + p.add(1).readS32();
        if (cur !== expect) { log("V5 retarget " + label + " @" + hex(site) + ": target " + hex(cur) + " != " + hex(expect) + " (skip)"); return; }
        Memory.protect(p, 5, "rwx"); p.add(1).writeS32(target - (site + 5));
        log("V5 retarget " + label + " @" + hex(site) + " -> " + hex(target));
      } catch (e) { log("V5 retarget " + label + " threw " + e); }
    }
    for (const [site, name] of [[0x4a8664, "energy listA scroll_small"], [0x4a8d19, "energy listB scroll_small"], [0x4a915b, "bases list scroll_small"], [0x4ac30e, "intel listA scroll_small"], [0x4ac77c, "intel listB scroll_small"]]) retarget(site, SMALL, SCROLL_SMALL, name);
    for (const [site, name] of [[0x4a892b, "energy listA scroll_normal"], [0x4a8ffc, "energy listB scroll_normal"], [0x4a9ad8, "bases list scroll_normal"], [0x4ac48e, "intel listA scroll_normal"], [0x4ac95c, "intel listB scroll_normal"]]) retarget(site, NORMAL, SCROLL_NORMAL, name);
    // (2) slide rails ("floating border art"): the report window's slide_show/slide_hide draw the 4 fixed 15x529/8x529 rail
    //     strips 1/1 at native offsets from the GROWN window's edges. Same fix as the popup/diplo wrappers: arm the filedlg
    //     rail gate (g_filedlg_active=1, g_fd_winbuf=&win+0x444) around the two calls for win==ReportWin so
    //     thunk_filedlg_railscale/railslide scale + re-anchor them; restore the prior cells after.
    const G_FDACT = VA(PC + 0x23A0), G_FDBUF = VA(PC + 0x25E0);
    for (const [va, name] of [[0x45D440, "slide_show"], [0x45D970, "slide_hide"]]) {
      att(va, name + " rail arm", {
        onEnter() {
          const win = this.context.esp.add(4).readPointer().toUInt32();
          if (win !== VA(RW).toUInt32() || gNow() <= 16) return;
          this.save = [S32(G_FDACT), S32(G_FDBUF)]; G_FDACT.writeS32(1); G_FDBUF.writeS32(win + 0x444);
          L1("rail" + name, "V5 " + name + "(ReportWin): rail gate armed (was " + this.save.join("/") + ")");
        },
        onLeave() { if (this.save) { G_FDACT.writeS32(this.save[0]); G_FDBUF.writeS32(this.save[1]); this.save = null; } }
      });
    }
    // (3) the ReportWin list scrollbar (RW+0xC10C, parked by rail_slide_in/out = the console-rail assembly): admit
    //     ReportWin to thunk_rail_gate by poking its ProdPicker compare (imm32 at +5: `push eax; mov eax,[ebp+8]; cmp eax,imm32`)
    //     while the report is active (the picker cannot be open meanwhile). Bake = a third compare in the gate.
    const GATE_IMM = VA(PC + 0x11205), PICKER = 0x6A8044;
    function railGate(on) {
      try {
        if (VA(PC + 0x11204).readU8() !== 0x3D) { L1("rg", "V5 rail gate: unexpected byte " + VA(PC + 0x11204).readU8().toString(16)); return; }
        const cur = GATE_IMM.readU32();
        if (on && cur === PICKER) { Memory.protect(VA(PC + 0x11200), 32, "rwx"); GATE_IMM.writeU32(VA(RW).toUInt32()); log("V5 rail gate -> ReportWin"); }
        else if (!on && cur === VA(RW).toUInt32()) { GATE_IMM.writeU32(PICKER); log("V5 rail gate -> ProdPicker (restored)"); }
      } catch (e) { log("V5 rail gate threw " + e); }
    }
    att(0x4a41d0, "ReportIf_activate rail gate", {
      onEnter() { this.on = S32(this.context.esp.add(4)); if (this.on && gNow() > 16) railGate(true); },
      onLeave() { if (!this.on) railGate(false); }
    });
    let nrail = 0;
    for (const [va, name] of [[0x45DEA0, "rail_slide_in"], [0x45E540, "rail_slide_out"]])
      att(va, name, { onEnter() { if (nrail++ < 40) { const sp = this.context.esp; log("V5 " + name + " win=" + hex(S32(sp.add(4))) + " sb=" + hex(S32(sp.add(8))) + " gateimm=" + hex(GATE_IMM.readU32()) + " g_rail_sb=" + hex(S32(VA(PC + 0x11260)))); } } });
    // (4) CHEATED! font: the score painter loads [0x8a40f0] (the report table's f32) -> the rw swap asks find_font(s(32)) but
    //     the font table tops out at 40 -> 40 px at every g (the "pristine size"). Build a dedicated Font (Font_init on a
    //     0x28-byte scratch, "Arial Narrow" like the popup arc's scaled fonts) at s(32) and point the load at it
    //     (`mov ecx,[0x8a40f0]` 6B -> `mov ecx,imm32; nop`). Bake = the same Font_init at init + the imm32 poke.
    const FONT_INIT = new NativeFunction(VA(0x618F40), "void", ["pointer", "pointer", "int", "int"], "thiscall");
    let cheatFont = null;
    function buildCheatFont() {
      if (cheatFont) return;
      const gg = gNow(); if (gg <= 16) return;
      const site = VA(0x4a216e);
      const cur = Array.from(new Uint8Array(site.readByteArray(6))).map(x => x.toString(16).padStart(2, "0")).join("");
      if (cur !== "8b0df0408a00") { log("V5 cheat font: site bytes " + cur + " (skip)"); return; }
      try {
        cheatFont = Memory.alloc(0x40); _caves.push(cheatFont); cheatFont.writeByteArray(new Array(0x40).fill(0));
        const size = s(32);
        FONT_INIT(cheatFont, VA(PC + 0x800), size, 0);
        Memory.protect(site, 6, "rwx");
        site.writeByteArray([0xB9].concat(d32(cheatFont.toUInt32()), [0x90]));
        log("V5 cheat font: Font_init(Arial Narrow, " + size + ", 0) at " + cheatFont + " (cell h " + S32(cheatFont.add(0xC)) + "), score set_font load repointed");
      } catch (e) { log("V5 cheat font threw " + e); }
    }
    att(0x4A3460, "init_report_screen cheat font", { onLeave() { buildCheatFont(); } });
    log("V5 levers installed");
  }
  // ======================= v6 LEVERS: admitted-button label font, console-list mouse wheel, list bar hide =======================
  {
    const RW = 0x876478, RI = 0x885F38, PC = 0xA0C000;
    const S32 = p => { try { return p.readS32(); } catch (e) { return -0x7fffffff; } };
    const U32 = p => { try { return p.readU32(); } catch (e) { return 0; } };
    const once = {}; const L1 = (k, m) => { if (!once[k]) { once[k] = 1; log(m); } };
    function att(va, name, cb) { try { Interceptor.attach(VA(va), cb); log("V6 attached " + name + " @" + hex(va)); } catch (e) { log("V6 ATTACH FAIL " + name + " @" + hex(va) + ": " + e); } }
    // (1) label font: the shared bake pokes its scaled f11 Font* (g_rw_font) into the `push 0x6e84b4` (Buffer_set_font) of
    //     its 4 admitted buttons only. The v5-admitted buttons keep the fixed 11-px label font -> "unscaled font". Same
    //     poke for GOVERNOR/BEST BASES, mode tabs, sat tabs, ATTACK!, 7 governor + 3 automate list buttons (imm32 at push+1).
    const FONT_SITES = [0x4a47f0, 0x4a48a8, 0x4a49dd, 0x4a4ab1, 0x4a4b91, 0x4a4ce1, 0x4a4db6, 0x4a4ea9, 0x4a4fb0, 0x4a509e, 0x4a518c, 0x4a527a, 0x4a5368, 0x4a5422, 0x4a54dc, 0x4a55ad, 0x4a5667, 0x4a572c,
      0x4a58ef /* v12: faction-target loop */, 0x4ab3b9 /* v12: satellite-target loop (console painter) */];
    function pokeLabelFonts() {
      const gg = gNow(); if (gg <= 16) return;
      const f = U32(VA(PC + 0x25714)); if (!f) { log("V6 label font: g_rw_font empty (skip)"); return; }
      let n = 0;
      for (const site of FONT_SITES) {
        const p = VA(site);
        if (p.readU8() !== 0x68 || p.add(1).readU32() !== 0x6e84b4) { log("V6 label font: unexpected bytes @" + hex(site)); continue; }
        Memory.protect(p, 5, "rwx"); p.add(1).writeU32(f); n++;
      }
      log("V6 label font: " + n + "/" + FONT_SITES.length + " push sites -> g_rw_font " + hex(f));
    }
    att(0x4A3460, "init_report_screen label fonts", { onLeave() { pokeLabelFonts(); } });
    // (2) mouse wheel over the console LISTS on the energy (2 lists) and bases (1 list) pages: the baked wheel helpers
    //     t_rw_wheel_down/up only serve kind 2 (one stashed bar). Here: at the helper's entry, for kind 3/4 with the report
    //     modal and no popup, hit-test the cursor against the console ListBox elements' screen rects (+0x13C) and step the
    //     bar under the cursor (ScrollBar_on_chevron(bar, 1|2) + parent redraw + hover invalidate = the helper's own body).
    //     Bar = the ListBox element's Win-layer vertical bar [elem+0x43C] (vtable-checked). Bake = a kind-3/4 branch in the
    //     helpers with a per-list table. The helper then falls through to its DL chain (no-op for the report).
    // v8: the console ListBox ELEMENTS are RI+0xA2D0 / RI+0xAE24 (ListBox_attach's ecx = element+0xA60; the list canvases
    //     RI+0xA75C/RI+0xB2B0 = element+0x48C) -- v6/v7 hit-tested RI+0xAD30/0xB884 = garbage rects (log run 4). The rect
    //     field is confirmed at runtime from candidates (+0x13C window rect, +0x14C, +0x474) by plausibility.
    const LISTS = [[RI + 0xA2D0, "console list A"], [RI + 0xAE24, "console list B"]];
    const RECT_OFFS = [0x13c, 0x14c, 0x474];
    const plausible = r => r[0] >= 0 && r[1] >= 0 && r[2] > r[0] && r[3] > r[1] && r[2] <= 4096 && r[3] <= 2304;
    function findBar(el) {
      const b = el.add(0x43c).readPointer();
      if (!b.isNull() && U32(b) === VA(SB_VTBL).toUInt32()) return b;
      for (let o = 0x400; o < 0x480; o += 4) { try { const q = el.add(o).readPointer(); if (!q.isNull() && U32(q) === VA(SB_VTBL).toUInt32()) return q; } catch (e) { } }
      return null;
    }
    const SB_VTBL = 0x669D58, MODAL_TOP = 0x9B7AE0, BASEPOP = 0x9B8D7C, KIND = 0x885F40, HWND = 0x9B7B28;
    const user32 = Process.getModuleByName("user32.dll");
    const GetCursorPos = new NativeFunction(user32.getExportByName("GetCursorPos"), "int", ["pointer"], "stdcall");
    const ScreenToClient = new NativeFunction(user32.getExportByName("ScreenToClient"), "int", ["pointer", "pointer"], "stdcall");
    const chevron = new NativeFunction(VA(0x606B20), "int", ["pointer", "int"], "thiscall");
    const ptbuf = Memory.alloc(16); _caves.push(ptbuf);
    function cursor() {
      if (!GetCursorPos(ptbuf)) return null;
      const h = VA(HWND).readPointer(); if (!h.isNull()) ScreenToClient(h, ptbuf);
      return [ptbuf.readS32(), ptbuf.add(4).readS32()];
    }
    let nwheel = 0;
    function wheel(dirName) {
      const k = S32(VA(KIND));
      if (!(k === 3 || k === 4)) return;
      if (S32(VA(BASEPOP)) !== 0 || U32(VA(MODAL_TOP)) !== VA(RW).toUInt32()) return;
      const c = cursor(); if (!c) return;
      const mw = [S32(VA(0x7ae820 + 0x13c)), S32(VA(0x7ae820 + 0x140))];              // MainWin screen origin
      const cm = [c[0] - mw[0], c[1] - mw[1]];
      // v9: the console list bar + its ListBox part come from the shared bake's own stash (t_rw_sbinit: g_rw_sb /
      //     g_rw_sbparent, written at the list's ScrollBar_init_inner while inlist=1 -- the v5 scroll_small retargets arm
      //     it for the energy/bases/intel consoles); the list rect is the (sx,sy,w,h) of ListBox_draw's MainWin background
      //     copy (copy_4 @0x60bbbf) captured in the copy_4 replacement, keyed by the list canvas (element+0x444).
      const bar = VA(PC + 0x2570c).readPointer(), part = VA(PC + 0x25710).readPointer();
      const canvas = part.isNull() ? 0 : part.add(0x444).toUInt32();   // v11: canvas = ListBox part + 0x444 = element + 0x48C (run 8: captured 0x890694 vs computed 0x89064c)
      const rr = globalThis.RW_LISTRECTS[canvas];
      if (nwheel < 40) log("V6 wheel " + dirName + " k=" + k + " cursor " + c.join(",") + " mainwin " + cm.join(",") + " bar " + bar + " part " + part + " canvas " + hex(canvas) + " rect " + (rr ? rr.join(",") : "none") + " rects " + JSON.stringify(globalThis.RW_LISTRECTS));
      if (bar.isNull() || part.isNull() || U32(bar) !== VA(SB_VTBL).toUInt32()) { if (nwheel++ < 20) log("V6 wheel: no stashed bar/part"); return; }
      if (!rr) { if (nwheel++ < 20) log("V6 wheel: no rect captured for the list canvas"); return; }
      if (!(cm[0] >= rr[0] && cm[0] < rr[0] + rr[2] && cm[1] >= rr[1] && cm[1] < rr[1] + rr[3])) { if (nwheel++ < 20) log("V6 wheel: cursor not over the list"); return; }
      if (S32(bar.add(0xC4)) === 0) { if (nwheel++ < 20) log("V6 wheel: bar hidden"); return; }
      if (S32(bar.add(0xA24)) <= S32(bar.add(0xA20))) { if (nwheel++ < 20) log("V6 wheel: bar has no range"); return; }
      const btn = dirName === "up" ? 1 : 2;
      chevron(bar, btn);
      const redraw = new NativeFunction(part.readPointer().add(0xFC).readPointer(), "void", ["pointer"], "thiscall");
      redraw(part);
      try { const el = part.sub(0x48); const adj = el.readPointer().add(8).readS32(); part.add(adj + 0xA8).writeS32(-1); } catch (e) { }
      if (nwheel++ < 20) log("V6 wheel " + dirName + " -> stashed list (bar " + bar + " value " + S32(bar.add(0xA2C)) + "/" + S32(bar.add(0xA24)) + ")");
    }
    // both helpers read the emulated key at [esp+0x68] (0x26 = up, 0x28 = down; [esp+0x6C] must be 0) -- same here.
    for (const [off, nm] of [[0x23ec0, "down-site"], [0x23f80, "up-site"]])
      att(PC + off, "t_rw_wheel " + nm + " (kinds 3/4)", { onEnter() {
        try {
          const sp = this.context.esp; if (S32(sp.add(0x6C)) !== 0) return;
          const key = S32(sp.add(0x68)); if (key !== 0x26 && key !== 0x28) return;
          wheel(key === 0x26 ? "up" : "down");
        } catch (e) { log("V6 wheel threw " + e); }
      } });
    // (3) the report list bar's RESIDUE: scroll_hide (rail_slide_out) captures the bar column from the screen and, with the
    //     gated roll-up count 0, bakes that captured column (bar image included) into the window canvas -> the top chevron
    //     + thumb stay painted on every later page (score, projects, ...). Proto: save the pristine right-border column of
    //     the ReportWin canvas once (first ReportIf_activate(1), before any bar) and restore it after every scroll_hide of
    //     the report window. Bake = skip the capture-bake for ReportWin and redraw the border column instead.
    let colSave = null, colGeom = null;
    function canvas() { const b = VA(RW).add(0x444); return { data: b.add(0x54).readPointer(), pitch: S32(b.add(0x4a8)), w: S32(b.add(0x80)), h: -S32(b.add(0x84)) }; }
    function saveColumn() {
      if (colSave) return; const gg = gNow(); if (gg <= 16) return;
      const c = canvas(); if (c.w <= 0 || c.h <= 0 || c.data.isNull()) return;
      const x0 = Math.max(0, c.w - s(47) - 4), cw = c.w - x0;
      colSave = Memory.alloc(cw * c.h); _caves.push(colSave); colGeom = { x0, cw, h: c.h, pitch: c.pitch, data: c.data };
      for (let y = 0; y < c.h; y++) Memory.copy(colSave.add(y * cw), c.data.add(y * c.pitch + x0), cw);
      log("V6 rail column saved: x " + x0 + ".." + c.w + " h " + c.h);
    }
    function restoreColumn(tag) {
      if (!colSave) return;
      try { const c = canvas(); if (c.w !== colGeom.x0 + colGeom.cw || c.h !== colGeom.h) { log("V6 rail column: canvas changed, no restore"); return; }
        for (let y = 0; y < c.h; y++) Memory.copy(c.data.add(y * c.pitch + colGeom.x0), colSave.add(y * colGeom.cw), colGeom.cw);
        L1("colr" + tag, "V6 rail column restored (" + tag + ")"); } catch (e) { log("V6 rail column restore threw " + e); }
    }
    att(0x4a41d0, "ReportIf_activate column save", { onEnter() { if (S32(this.context.esp.add(4))) { saveColumn(); restoreColumn("activate"); } } });
    att(0x45E540, "scroll_hide column restore", {
      onEnter() { this.rw = this.context.esp.add(4).readPointer().toUInt32() === VA(RW).toUInt32(); },
      onLeave() { if (this.rw) restoreColumn("scroll_hide"); }
    });
    log("V6 levers installed");
  }
  // ======================= v7 LEVERS: K-stroke frames on the kinds pages, toggle seams =======================
  {
    const RI = 0x885F38, PC = 0xA0C000;
    const S32 = p => { try { return p.readS32(); } catch (e) { return -0x7fffffff; } };
    const once = {}; const L1 = (k, m) => { if (!once[k]) { once[k] = 1; log(m); } };
    function att(va, name, cb) { try { Interceptor.attach(VA(va), cb); log("V7 attached " + name + " @" + hex(va)); } catch (e) { log("V7 ATTACH FAIL " + name + " @" + hex(va) + ": " + e); } }
    // (1) every Buffer_box_sprite the seven canvas painters draw into the report canvas (page backdrop, title strip, column
    //     boxes, list rows/cells, selected-row rings, the orbit frame) still goes to vanilla box_sprite = 1-px strokes at
    //     every g (measured 4K: rows 1 px, law stroke_width(40) = 2; the console panels, drawn through the baked MAIN
    //     detour, measure 2). Retarget the 32 E8 sites to thunk_box_thick_devfill = the dither-safe box-sprite thickener
    //     (drop-in signature; K strokes + device-density interior, the F2/popup language) -- zero Interceptor, bake shape.
    const BOX_SPRITE = 0x5E2DD3, DEVFILL = PC + 0x42A0;
    const BOX_SITES = [0x49bdab, 0x49bdbb, 0x49bdcb, 0x49bddb, 0x49bdeb, 0x49bdfb,                       // energy: backdrop, title, 2 column heads, 2 column bodies
      0x49d653, 0x49d663, 0x49d676, 0x49dad7, 0x49dae7, 0x49daf7, 0x49db18, 0x49db28, 0x49db8b,          // bases: backdrop/title/body, selected row+icon rings, row + icon cells, garrison
      0x49ebbe, 0x49ebce, 0x49ef3b, 0x49ef56,                                                          // projects: backdrop, title, cells (2 sets)
      0x49f3b0, 0x49f3c0, 0x49fb79,                                                                    // satellites: backdrop, title, orbit frame
      0x4a0954, 0x4a0964, 0x4a0d7d, 0x4a0d98,                                                          // units: backdrop, title, rows (2 sets)
      0x4a11b3, 0x4a11c3, 0x4a11d3,                                                                    // score: backdrop, title, body
      0x4a228a, 0x4a229a, 0x4a22aa];                                                                   // intel: backdrop, title, body
    function retargetFrames() {
      const gg = gNow(); if (gg <= 16) { log("V7 frames: g<=16, vanilla box_sprite kept"); return; }
      let n = 0;
      for (const site of BOX_SITES) {
        const p = VA(site);
        if (p.readU8() !== 0xE8) { log("V7 frames: not a CALL @" + hex(site)); continue; }
        const cur = site + 5 + p.add(1).readS32();
        if (cur !== BOX_SPRITE) { log("V7 frames: @" + hex(site) + " targets " + hex(cur) + " (skip)"); continue; }
        Memory.protect(p, 5, "rwx"); p.add(1).writeS32(DEVFILL - (site + 5)); n++;
      }
      log("V7 frames: " + n + "/" + BOX_SITES.length + " box_sprite sites -> thunk_box_thick_devfill (K=" + s(1) + ")");
    }
    att(0x4A3460, "init_report_screen frame retargets", { onLeave() { retargetFrames(); } });
    // (2) toggle-pair seams: GOVERNOR|BEST BASES split at W/2 with native -1/+1 (dec/lea) and SATELLITE SUMMARY|ORBITAL ATTACK
    //     VIEW at W/2 with -1/+1 -> seams 3 and 4 px at 4K instead of s(2)=5 (the F2 TECHNOLOGY|BASES law: seam s(2), equal
    //     halves). Rewrite the BaseButton_init args at entry: left w = (W-s2)>>1; right x = L+w+s2, w = W-w-s2 (W=[RI+0x14],
    //     L=[RI+0xC] = the row computed by the builder). Bake = split caves like the TECH/BASES ones.
    const SEAM = { 0x4a47ed: "L", 0x4a48a5: "R", 0x4a4cde: "L", 0x4a4db3: "R" };
    att(0x607210, "toggle seams", {
      onEnter() {
        const gg = gNow(); if (gg <= 16) return;
        const ret = this.context.esp.readPointer().sub(globalThis.TERRANX_BASE).toUInt32() + 0x400000, side = SEAM[ret]; if (!side) return;
        const sp = this.context.esp, W = S32(VA(RI + 0x14)), L = S32(VA(RI + 0xC)), s2 = s(2), wl = (W - s2) >> 1;
        if (side === "L") { sp.add(0x14).writeS32(wl); }
        else { sp.add(0xC).writeS32(L + wl + s2); sp.add(0x14).writeS32(W - wl - s2); }
        L1("seam" + ret, "V7 seam @" + hex(ret) + " " + side + ": x=" + S32(sp.add(0xC)) + " w=" + S32(sp.add(0x14)) + " (W " + W + " s2 " + s2 + ")");
      }
    });
    log("V7 levers installed");
  }
  // ---------------- frame-enlarge probe (see hook_rw_frame_probe.js) ----------------
  {
    const PCAVE2 = 0xA0C000;
    const ENLARGE = PCAVE2 + 0xBF80, G_FC_EXACT = PCAVE2 + 0x2554, G_FSR = PCAVE2 + 0x1010, G_BAND = PCAVE2 + 0xA200;
    const G_RW = 0x876478, G_HOF = 0x74DAF8, G_MAINBUF = 0x7AEC64, KEY = 9;
    const S = p => { try { return p.readS32(); } catch (e) { return -0x7fffffff; } };
    const staticVA = p => p.sub(globalThis.TERRANX_BASE).toUInt32() + 0x400000;
    const rect4 = p => [S(p), S(p.add(4)), S(p.add(8)), S(p.add(12))];
    function destTag(p) {
      const v = p.toUInt32();
      if (v === VA(G_RW).toUInt32() + 0x444) return "RWc";
      if (v === VA(G_HOF).toUInt32() + 0x444) return "HOFc";
      if (v === VA(G_MAINBUF).toUInt32()) return "MAIN";
      return hex(v);
    }
    function bufInfo(b) { return { data: b.add(0x54).readPointer(), pitch: S(b.add(0x4a8)), w: S(b.add(0x80)), h: -S(b.add(0x84)) }; }
    function rle(get, a0, a1) {
      const out = []; let prev = -1, run = 0, start = 0;
      for (let i = a0; i < a1; i++) { const v = get(i); if (v === prev) run++; else { if (prev >= 0) out.push([prev, start, run]); prev = v; start = i; run = 1; } }
      if (prev >= 0) out.push([prev, start, run]); return out;
    }
    const fmt = runs => runs.map(r => r[0] + "x" + r[2] + "@" + r[1]).join(" ");
    const extent = runs => { const nk = runs.filter(r => r[0] !== KEY); return nk.length ? "[" + nk[0][1] + ".." + (nk[nk.length - 1][1] + nk[nk.length - 1][2] - 1) + "]" : "none"; };
    let label = "";
    for (const [va, name] of [[PCAVE2 + 0x140, "hollow_flat"], [PCAVE2 + 0x42A0, "devfill"], [PCAVE2 + 0x22680, "t_dl_bmxt"]]) {
      Interceptor.attach(VA(va), {
        onEnter(args) {
          if (gNow() <= 16) return;
          const rect = rect4(args[0]);
          label = name + "<-" + hex(staticVA(this.context.esp.readPointer())) + " rect=(" + rect.join(",") + ")[" + (rect[2] - rect[0]) + "x" + (rect[3] - rect[1]) + "] dest=" + destTag(this.context.ecx) + " set=" + hex(staticVA(args[1]));
        },
        onLeave() { label = ""; }
      });
    }
    let n = 0;
    Interceptor.attach(VA(ENLARGE), {
      onEnter(args) {
        this.dest = args[0]; this.tag = destTag(this.dest);
        if (this.tag.startsWith("0x") || n++ > 250) { this.skip = true; return; }
        const src = bufInfo(this.context.ecx);
        this.X = args[2].toInt32(); this.Y = args[3].toInt32(); const num = args[4].toInt32(), den = args[5].toInt32();
        const exact = S(VA(G_FC_EXACT)), fsr = rect4(VA(G_FSR)), band = [0, 4, 8, 12].map(o => S(VA(G_BAND).add(o)));
        this.dstW = exact ? fsr[2] - fsr[0] : Math.floor(src.w * num / den);
        this.dstH = exact ? fsr[3] - fsr[1] : Math.floor(src.h * num / den);
        log("ENLARGE#" + n + " " + label + " | src " + src.w + "x" + src.h + " -> " + this.tag + " X,Y=" + this.X + "," + this.Y + " n/d=" + num + "/" + den + " exact=" + exact +
            " fsr=(" + fsr.join(",") + ") band nx,ny,ex,ey=" + band.join(",") + " => dst " + this.dstW + "x" + this.dstH + " expect x[" + this.X + ".." + (this.X + this.dstW - 1) + "] y[" + this.Y + ".." + (this.Y + this.dstH - 1) + "]");
      },
      onLeave() {
        if (this.skip) return;
        try {
          const bi = bufInfo(this.dest), ym = this.Y + (this.dstH >> 1), xm = this.X + (this.dstW >> 1);
          if (ym >= 0 && ym < bi.h) {
            const row = rle(x => bi.data.add(ym * bi.pitch + x).readU8(), Math.max(0, this.X - 4), Math.min(bi.w, this.X + this.dstW + 4));
            log("  RENDERED row y=" + ym + ": extent " + extent(row) + "  " + fmt(row.slice(0, 4)) + " ... " + fmt(row.slice(-4)));
          }
          if (xm >= 0 && xm < bi.w) {
            const col = rle(y => bi.data.add(y * bi.pitch + xm).readU8(), Math.max(0, this.Y - 4), Math.min(bi.h, this.Y + this.dstH + 4));
            log("  RENDERED col x=" + xm + ": extent " + extent(col) + "  " + fmt(col.slice(0, 4)) + " ... " + fmt(col.slice(-4)));
          }
        } catch (e) { log("  readback threw " + e); }
      }
    });
  }
  log("ready: v13 levers + grand probe; g at load=" + g + " (v2 table + icon pokes applied at init_report_screen return)");
}
