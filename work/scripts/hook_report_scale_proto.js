// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// HQ report screens (ReportWin/ReportIf) scaling prototype.
// Static/source/pixel maps: work\_rw_static_map.md / _rw_source_map.md / _rw_pixel_geometry.md.
// Probe ground truth: _rw_static_map.md §PROBE RESULTS.
//
// v1 LEVER SET (the frame + fonts, one-shot at startup) — attach init_report_screen
// 0x4A3460 onLeave (its tail calls win_init 0x496960, so by its return BOTH ReportIf's
// 15-font table AND ReportWin's window geometry fields exist):
//   (a) enlarge the ReportWin window (fields +0xA1C/+0xA20 base w/h -> scaled; recenter
//       +0xA14, anchor +0xA18 = ScreenH - H - s(0xD4) so it tracks the SCALED console
//       strip, which ALSO lifts the window clear of the console occlusion) + call
//       GraphicWin_resize(win, W+s(0x4E), H, 1) to grow the canvas buffer + window rect;
//   (b) rescale the two content rects the painters clip to: +0x5974 clip {s(0x1A),s(3),
//       W+s(0x14),textB} with textB=+0x5980=H-s(0x35); +0x5984 title rect {s(0x17),0,
//       W+s(0x17),H};
//   (c) swap the 15-font table (+0x1E180[i], find_font(s(size),style)) to scaled fonts,
//       then recompute the two cached font-12 line heights +0xE268 (ReportWin) / +0x1C
//       (ReportIf) by the engine's own metric formula.
// v1 does NOT touch per-page content geometry (row cells, cards, bars, console tabs) —
// those are recomputed per paint from native immediates; the imm tables (work\_rw_painter_imms.md)
// come in v2. v1 proves the window/frame/font scaling + occlusion fix and shows, per page,
// how much cascades from the scaled clip. Everything is logged so a run is self-diagnosing.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_report_proto.log";
// v2 (2026-09-02): v1 grew the window but GraphicWin_resize keeps the OLD top-left, so the
// window ran ~100px off the screen bottom + behind the console (rRect1 1299 vs SH 1200) and
// stayed left-anchored. Fix: after resize, write the window screen rect +0x13C to the centred
// + strip-anchored position (winB = SH - live_stripH); anchor now reads 0x7AF59C not s(0xD4).
// Tech page (kind 2) card stays under-scaled until the dl_scale TECH table is applied per the
// §3 contract (deferred) — v2 verifies the FRAME on the non-tech pages.
// v3 (2026-09-02): + TECH PAGE (kind 2). Drives the EXISTING dl_scale TECH walker
// (t_dl_immfix_tech) from a ReportWin bracket on the three card painters — patches
// NOTHING in the 0x498B9B..0x49BCAE no-attach range (per _rw_source_map §3). See the
// v3 block below. Prereqs (window/clip/textB/lineH/fonts) come from v2's field-writes.
// v4 (2026-09-02): (a) DECOUPLE geometry from fonts — the walker now ALWAYS runs (card/
// frame/connector geometry is font-independent); when DL's embedded tech fonts are unbuilt
// (font[0]=0 until DL is first opened) we restore the 8 PTR sites to NATIVE so the card uses
// native (built) fonts instead of crashing on null Fonts. (b) SCALE the bottom DATALINKS/CLOSE
// buttons via ReportIf_activate's build imms (poked in the startup one-shot). Header icon/text-box
// remain bake-level (no-attach zone + imm8 overflow + sprite/font thunks) — NOT done here.
// v5 (2026-09-02): F2 tech CARD size — the walker only rewrites the Datalinks branch of tech_page;
// the F2 branch (0x498C5A+) sets the card its own way. Poked the 5 imm32 card-size sites so the card
// box + 6 prereq/leads-to buttons scale (they cascade from +0x59A0/+0x59A4).
// v6 (2026-09-02): BUTTON LABEL FONT. 0x6E84B4 is fixed line-height 16 (title/category fonts already
// scale game-side; this one does not). Build a scaled clone find_font(16*g/16,0) and repoint the 6
// tech-button + 2 bottom-button (DATALINKS/CLOSE) set-font sites at it. Remaining tech-page items
// (header-band height, icon centring, 9-slice frame thickness, bottom-button clip) are imm8-overflow
// / sprite / frame concerns = the BAKE pass, not proto pokes.
// v7 (2026-09-03): CONSOLE research bars. Investigation (per user "console mostly unscaled"): the kind-2
// console painter FUN_004a7000 is MOSTLY field-based and already scales (panels from HUD-scaled region
// rects; text from the scaled +0x1E180 font table + line-height +0x1C). The one clearly-native, self-
// contained defect = the right-panel research bars (native height 0xf). Poke the 9 `83 /r 0F` bar sites
// to s(0xf) (overflow-safe at g=40). The tab-bar box 0x1a + list-offset 0x20 are button-coupled (toggle
// ids 0x92/0x93 read the painter's shared scratch +0x1e1c8/cc) -> left for the bake.
// v8 (2026-09-03): CAVES — the four remaining items, coded (no more pokes-only ceiling):
//  (1)+(2) DATALINKS/CLOSE face+frame: params-clone surgery, face band → tiled center slice (see the
//      BTN FACE section below). (3) card too high: card top = a18+0x46+0x62+0x1D chain, all native →
//      fixed by the header caves. (4) header band box + brain icon: Cave_B1/B2 (band imm32) + Cave_C
//      (icon num 0x40→s imm32) + 6 scaled insets. Caves Unicorn-verified (emu_rw_caves.py ALL-OK).
//      Card-CENTER icon sites 0x49A2A4/A8/C3/CF/DA are walker/bake-covered (t_dl_mono + t_dl_rf6 +
//      imm rows) — deliberately NOT touched here (double-scale hazard, feedback-bake-port-fidelity).
log("=== hook_report_scale_proto.js v9.8 === " + new Date().toISOString());
installAVHandler("report_proto");

if (requireBase() && VA(0x4a3460).readU8() === 0xe9) {
  // 2026-09-04: the report screens are BAKED (rw_scale_shared/tech: init_report_screen entry is an E9
  // detour). Running this proto on top would double-scale the window lever and clash with the baked
  // caves -> refuse. Use the plain shortcuts to verify the bake; keep this file as the bake's source of truth.
  log("REPORT SCREENS ARE BAKED in this exe (E9 @0x4A3460) -> proto DISARMED (nothing hooked)");
} else if (requireBase()) {
  const SL = globalThis.SL;
  const G_SCALE = 0x668740;               // g_popup_scale_num
  const G_SCREENW = 0x9b7b1c, G_SCREENH = 0x9b7b20;
  const G_RW = 0x876478, G_RI = 0x885F38;

  const A_IRS = 0x4a3460;                  // init_report_screen (this=ReportIf), one-time
  const find_font = new NativeFunction(VA(0x5882f0), "pointer", ["int", "int"], "mscdecl"); // (size,style)->Font*
  const GraphicWin_resize = new NativeFunction(VA(0x5d5540), "int",
    ["pointer", "int", "int", "int"], "thiscall");                    // (self,w,h,a4)

  let g = 16;
  let scaledBtnFp = null;                   // scaled clone of the fixed button font 0x6E84B4
  const s = v => SL.scalePx(v, g);         // LAW 1 half-down: coords/margins/additives
  const sf = v => SL.scaleFloor(v, g);     // window/canvas dims (descale-exact)

  // --- v8 cave infrastructure: RWX caves + 5-byte JMP detours (proto equivalents of the
  // bake's thunks, for the imm8-overflow sites that CANNOT be poked in place). Every alloc
  // is retained in _caves (feedback-frida-memory-alloc-gc: unreferenced Memory.alloc pages
  // are GC-freed under the live JMP). Caves are hand-assembled byte arrays; each one's
  // structure is emulation-checked offline before arming (feedback-emulate-frida-stubs). ---
  const _caves = [];
  function makeCave(bytes) {
    const p = Memory.alloc(4096);
    _caves.push(p);                          // retain forever
    Memory.protect(p, 4096, "rwx");
    p.writeByteArray(bytes);
    return p;
  }
  // little-endian imm32/rel32 encoder
  function d32(v) { v = v | 0; return [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff]; }
  // Patch a 5-byte JMP rel32 at `fromVA` -> `toPtr`, NOP-padding to `totalLen` (the full
  // length of the clobbered original instructions, so no instruction is left half-written).
  function jmpPatch(fromVA, toPtr, totalLen) {
    const from = VA(fromVA);
    Memory.protect(from, totalLen, "rwx");
    const rel = toPtr.sub(from.add(5)).toInt32();
    const b = [0xe9].concat(d32(rel));
    for (let i = 5; i < totalLen; i++) b.push(0x90);
    from.writeByteArray(b);
  }
  // rel32 for a JMP placed INSIDE a cave at cave+off, returning to exe VA `backVA`
  function relFromCave(cavePtr, off, backVA) {
    return d32(VA(backVA).sub(cavePtr.add(off + 5)).toInt32());
  }
  // cave = body bytes + `jmp backVA` tail
  function caveWithJmp(body, backVA) {
    const p = Memory.alloc(4096);
    _caves.push(p);
    Memory.protect(p, 4096, "rwx");
    p.writeByteArray(body.concat([0xe9, 0, 0, 0, 0]));
    p.add(body.length + 1).writeS32(VA(backVA).sub(p.add(body.length + 5)).toInt32());
    return p;
  }

  function safeS32(p, d) { try { return p.readS32(); } catch (e) { return (d === undefined ? -0x7fffffff : d); } }
  function rstr(p) { const r = [safeS32(p), safeS32(p.add(4)), safeS32(p.add(8)), safeS32(p.add(12))]; return "(" + r.join(",") + ") [" + (r[2] - r[0]) + "x" + (r[3] - r[1]) + "]"; }

  // native (size,style) of the 15 fonts (init_report_screen order)
  const FONTS = [[10, 0], [12, 0], [12, 2], [12, 1], [14, 0], [14, 2], [14, 1],
                 [16, 0], [16, 2], [16, 1], [11, 0], [26, 0], [18, 2], [22, 0], [32, 0]];

  // engine's line-height read: font[0]<0 ? font[3] : font[4]+font[0]
  function fontLineH(fp) {
    const f0 = safeS32(fp);
    return f0 < 0 ? safeS32(fp.add(12)) : (safeS32(fp.add(16)) + f0);
  }

  Interceptor.attach(VA(A_IRS), {
    onLeave() {
      g = safeS32(VA(G_SCALE), 16);
      const SW = safeS32(VA(G_SCREENW)), SH = safeS32(VA(G_SCREENH));
      const rw = VA(G_RW), ri = VA(G_RI);
      log("--- init_report_screen onLeave: g=" + g + " ScreenW=" + SW + " ScreenH=" + SH + " ---");
      log("PRE  rw.a1c/a20(w/h)=" + safeS32(rw.add(0xa1c)) + "/" + safeS32(rw.add(0xa20)) +
          " a14/a18(x/y)=" + safeS32(rw.add(0xa14)) + "/" + safeS32(rw.add(0xa18)) +
          " clip+5974=" + rstr(rw.add(0x5974)) + " title+5984=" + rstr(rw.add(0x5984)) +
          " textB+5980=" + safeS32(rw.add(0x5980)) + " lineH+e268=" + safeS32(rw.add(0xe268)) +
          " rRect1+13c=" + rstr(rw.add(0x13c)));
      if (g <= 16) { log("g<=16 -> native no-op gate"); return; }

      // --- (a) window enlarge + anchor ---
      const W0 = safeS32(rw.add(0xa1c)), H0 = safeS32(rw.add(0xa20));   // vanilla 650 / 553(wide)
      const W = sf(W0), H = sf(H0);
      // anchor the window BOTTOM to the live SCALED console strip (0x7AF59C) so it butts
      // the console instead of running off-screen; vanilla law winB = SH - strip (0xD4 =
      // native strip height). x centres the CONTENT (650), matching vanilla.
      const strip = safeS32(VA(0x7af59c), s(0xd4));
      const x = ((SW - W) / 2) | 0, y = SH - H - strip;
      rw.add(0xa1c).writeS32(W); rw.add(0xa20).writeS32(H);   // a1c read by draw_units columns
      rw.add(0xa14).writeS32(x); rw.add(0xa18).writeS32(y);

      // --- (b) content rects ---
      // clip +0x5974 {L,T,R,B}
      rw.add(0x5974).writeS32(s(0x1a));
      rw.add(0x5978).writeS32(s(3));
      rw.add(0x597c).writeS32(W + s(0x14));
      rw.add(0x5980).writeS32(H - s(0x35));                            // textB
      // title rect +0x5984 {0x17,0,W+0x17,H}
      rw.add(0x5984).writeS32(s(0x17));
      rw.add(0x5988).writeS32(0);
      rw.add(0x598c).writeS32(W + s(0x17));
      rw.add(0x5990).writeS32(H);

      // --- (c) font-table swap ---
      const swapped = [];
      for (let i = 0; i < FONTS.length; i++) {
        const [sz, st] = FONTS[i];
        let fp;
        try { fp = find_font(s(sz), st); } catch (e) { fp = null; }
        if (fp && !fp.isNull()) { ri.add(0x1e180 + i * 4).writePointer(fp); swapped.push(s(sz)); }
        else swapped.push("FAIL");
      }
      // recompute cached font-12 line heights (fonts[1] = find_font(12,0) alias 0x8A40BC)
      const f12 = ri.add(0x1e184).readPointer();
      let lh = 15;
      try { lh = fontLineH(f12); } catch (e) {}
      rw.add(0xe268).writeS32(lh);          // ReportWin row pitch source
      ri.add(0x1c).writeS32(lh);            // ReportIf console line height

      // --- resize the canvas + window, then REPOSITION (resize keeps the old top-left) ---
      const Wout = W + s(0x4e);
      let rc = -999;
      try { rc = GraphicWin_resize(rw, Wout, H, 1); } catch (e) { log("resize threw: " + e); }
      // window rect = GraphicWin_init(a14-0x17, a18, W+0x4E, H): screen rect +0x13C.
      const winL = x - s(0x17), winT = y;
      rw.add(0x13c).writeS32(winL);
      rw.add(0x140).writeS32(winT);
      rw.add(0x144).writeS32(winL + Wout);
      rw.add(0x148).writeS32(winT + H);

      // --- bottom DATALINKS(id9)/CLOSE(id1) buttons: scale ReportIf_activate's build imms
      // (0x4A4397..0x4A4523; built once per open, AFTER this startup one-shot). They read the
      // scaled clip/textB fields (0x87BDEC/F4/F8 = RW+0x5974/597C/5980, already set above) for
      // position; only the height 0x14 + insets 7/0x4B/0x96 are native. Poke them scaled. 0x4B
      // is a disp8 (lea [ecx+0x4B]) -> imm8-overflows at g=40, skip+flag there. ---
      try {
        Memory.protect(VA(0x4a43a0), 0x200, "rwx");
        VA(0x4a43ab).writeU8(s(7) & 0xff);        // row top y = textB + s(7)   (disp8; s(7)<=17)
        VA(0x4a43b9).writeU8(s(0x14) & 0xff);     // group-row bottom = top + s(0x14)  (imm8; <=50)
        VA(0x4a442b).writeU8(s(0x14) & 0xff);     // id1 CLOSE height = y + s(0x14)
        VA(0x4a44e8).writeU8(s(0x14) & 0xff);     // id9 DATALINKS height = y + s(0x14)
        VA(0x4a43d2).writeS32((-s(0x96)) | 0);    // right reserve = ...- s(0x96)  (disp32, any width)
        // v9: row left inset 0x4B is a disp8 (lea edx,[ecx+0x4B]) -> overflows for g>=28. Cave
        // detour (10 B displaced: 8D 51 4B / 2B F9 / A3 7C E0 87 00; straight-line, no branch
        // lands inside): lea edx,[ecx+s(0x4B)] (disp32); sub edi,ecx; mov [0x87E07C],eax; jmp back.
        const li = s(0x4b);
        let liHow = "NOT armed (guard)";
        if (VA(0x4a43ba).readU8() === 0x8d && VA(0x4a43bb).readU8() === 0x51 && VA(0x4a43bc).readU8() === 0x4b) {
          const cL = caveWithJmp([0x8d, 0x91].concat(d32(li), [0x2b, 0xf9], [0xa3, 0x7c, 0xe0, 0x87, 0x00]), 0x4a43c4);
          jmpPatch(0x4a43ba, cL, 10);
          liHow = "cave@" + cL;
        }
        // v9.1: the DATALINKS|CLOSE gap = centre-1 / centre+1 (`dec eax` @0x4A4420; `dec eax; inc edi`
        // @0x4A44D6) = 2px native -> s(2) split a/b (remainder law). Two straight-line caves.
        const gap = s(2), ga = gap >> 1, gb = gap - ga;
        let gapHow = "NOT armed";
        const g1 = [0x2b, 0xc2, 0x89, 0x96, 0xc8, 0xe1, 0x01, 0x00, 0x48], g2 = [0x2b, 0xc2, 0x48, 0x47, 0x89, 0x8e, 0xcc, 0xe1, 0x01, 0x00];
        const same = (va, arr) => arr.every((b, i) => VA(va + i).readU8() === b);
        if (same(0x4a4418, g1) && same(0x4a44d4, g2)) {
          const cg1 = caveWithJmp([0x2b, 0xc2, 0x89, 0x96, 0xc8, 0xe1, 0x01, 0x00, 0x2d].concat(d32(ga)), 0x4a4421);   // sub eax,edx; mov [esi+1e1c8],edx; sub eax,a
          const cg2 = caveWithJmp([0x2b, 0xc2, 0x2d].concat(d32(gb), [0x81, 0xc7], d32(gb), [0x89, 0x8e, 0xcc, 0xe1, 0x01, 0x00]), 0x4a44de); // sub eax,edx; sub eax,b; add edi,b; mov [esi+1e1cc],ecx
          jmpPatch(0x4a4418, cg1, 9); jmpPatch(0x4a44d4, cg2, 10);
          gapHow = "caves " + cg1 + "/" + cg2;
        }
        log("BTN scaled: h=" + s(0x14) + " topY=+" + s(7) + " leftInset=+" + li + " (" + liHow + ")" +
            " rightReserve=-" + s(0x96) + " gap=" + gap + " (" + ga + "+" + gb + ", " + gapHow + ")");
      } catch (e) { log("BTN poke threw: " + e); }

      // --- F2 tech-card SETUP (tech_page F2 branch @0x498C5A+, which the DL walker does NOT reach:
      // it lives in the mode!=8 branch; the walker only rewrites the mode==8 DL branch). Scale the
      // card cell dims + centring so the card box AND the 6 prereq/leads-to buttons (which read
      // +0x59A0/+0x59A4) scale. All 5 are imm32 (no overflow). Disasm-confirmed. ---
      try {
        Memory.protect(VA(0x498c60), 0x120, "rwx");
        VA(0x498c67).writeS32(s(0xbe));   // 0x498C66 mov edx,0xBE -> btn_w(+0x59A0) & card_w(+0x59A8)
        VA(0x498c8c).writeS32(s(0x28));   // 0x498C86 mov [+0x59A4],0x28 -> btn_h
        VA(0x498cde).writeS32(-s(0xbe));  // 0x498CDC lea eax,[edx-0xBE] -> card centring span
        VA(0x498cf1).writeS32(s(0xae));   // 0x498CEF add edi,0xAE -> card rect height (+0xA34)
        VA(0x498cfc).writeS32(s(0xbe));   // 0x498CFB add eax,0xBE -> card rect right (+0xA30)
        log("F2card scaled: cell_w=" + s(0xbe) + " cell_h=" + s(0x28) + " card_h=" + s(0xae) +
            " (header box height 0x46 + offsets NOT yet scaled — pending full map)");
      } catch (e) { log("F2card poke threw: " + e); }

      // --- button LABEL font: 0x6E84B4 is a FIXED-size (line-h 16) font shared by 53 sites, so it
      // can't be resized globally. Build a scaled clone via find_font(16*g/16,0) and repoint the
      // button set-font sites at it. The tech-button 6 sites (0x4997B7..) are repointed per-apply in
      // techFontsToNative (below); the two BOTTOM buttons are one-shot here. title/category fonts
      // ([0x8A40D4]/[0x8A40C8]) already scale with resolution game-side -> leave native. ---
      try {
        const bsz = Math.round(16 * g / 16);
        const bp = find_font(bsz, 0);
        if (bp && !bp.isNull()) {
          scaledBtnFp = bp;
          Memory.protect(VA(0x4a4470), 0xd0, "rwx");
          VA(0x4a4473).writePointer(bp);   // id1 CLOSE   Buffer_set_font push operand
          VA(0x4a452c).writePointer(bp);   // id9 DATALINKS Buffer_set_font push operand
          log("BTNfont scaled: find_font(" + bsz + ",0)=" + bp + " -> 2 bottom + 6 tech buttons");
        } else log("BTNfont find_font failed");
      } catch (e) { log("BTNfont threw: " + e); }

      // --- v7 CONSOLE (kind-2 tech console painter FUN_004a7000): the console is MOSTLY field-based
      // (panels derive from the HUD-scaled region rects +0x20..+0x5C; text uses the scaled +0x1E180
      // font table + scaled line-height +0x1C) so it already scales. The one clearly-native, self-
      // contained defect is the RESEARCH BARS (right panel EXPLORE/DISCOVER/BUILD/CONQUER): their
      // height + label advance are a hardcoded 0xf, and the per-row base is `((h)/4)-0xf`. All 9 are
      // `83 /r ib` imm8 (s(0xf)=37 at g=40, no overflow), so poking the code once holds for every
      // repaint at every resolution. The tab-bar box 0x1a + list-offset 0x20 are NOT touched here:
      // the TECHNOLOGY/BASES toggle buttons (ids 0x92/0x93) take their rects from the painter's shared
      // scratch +0x1e1c8/+0x1e1cc across a function boundary — scaling the box desyncs them, so that
      // coupling belongs in the bake. Disasm-confirmed sites (imm = insn+2): row-base sub @0x4a7cbb;
      // bar height/advance pairs @0x4a7de7/0x4a7e4c, 0x4a7f84/0x4a7fe9, 0x4a8121/0x4a8186,
      // 0x4a82bd/0x4a8322. ---
      try {
        const barS = s(0xf) & 0xff;                      // bar height / advance, half-down ×g/16
        const BAR_SITES = [0x4a7cbb, 0x4a7de7, 0x4a7e4c, 0x4a7f84, 0x4a7fe9,
                           0x4a8121, 0x4a8186, 0x4a82bd, 0x4a8322];
        Memory.protect(VA(0x4a7cb0), 0x4a8330 - 0x4a7cb0, "rwx");
        let ok = 0;
        for (const site of BAR_SITES) {
          // sanity: every site must be `83 /r 0F` (opcode 0x83, imm8 0x0F) before we poke it
          if (VA(site).readU8() === 0x83 && VA(site + 2).readU8() === 0x0f) {
            VA(site + 2).writeU8(barS); ok++;
          } else log("CON bar site 0x" + site.toString(16) + " unexpected bytes -> skipped");
        }
        log("CON research bars scaled: 0xf -> " + s(0xf) + " (" + ok + "/" + BAR_SITES.length + " sites)");
      } catch (e) { log("CON bar poke threw: " + e); }

      // --- v8 HEADER caves + insets (F2-only block 0x498C5A..0x498F20; the DL walker never touches
      // it — grep-verified). Fixes THREE user items at once: (a) the band box behind "RESEARCHING…"
      // (height 0x46 + wide-extension 0x62 + inner-box x 0x43), (b) the brain icon (draw num 0x40 →
      // s(0x40) so it scales ×g/16, and its +3 anchors → s(3) so it re-centres in the taller band),
      // (c) the CARD sitting too high in the modal — card top = a18 + 0x46 + 0x62 + 0x1D chain, all
      // previously native (197px instead of ~492 at g=40). The three >127 sites become imm32 CAVES
      // (Unicorn-verified: scratchpad emu_rw_caves.py ALL-OK at g=17/22/25/40, both B2 mask states,
      // C stack contract); the small insets are in-place imm8 pokes (all ≤127 at g=40). ---
      try {
        const g8 = (va, want) => {
          const b = VA(va).readU8();
          if (b !== want) log("v8 guard FAIL @0x" + va.toString(16) + " byte=0x" + b.toString(16) + " want=0x" + want.toString(16));
          return b === want;
        };
        if (g8(0x498c99, 0x8d) && g8(0x498c9b, 0x46) && g8(0x498ccf, 0x83) && g8(0x498cd1, 0x62) && g8(0x498e43, 0x6a) && g8(0x498e44, 0x40)) {
          // Cave_B1 @0x498C99 (9B: lea edi,[eax+0x46]; add eax,3; add ebx,0x43):
          //   lea edi,[eax+s(0x46)]; add eax,s(3); add ebx,s(0x43); jmp 0x498CA2
          const c1 = caveWithJmp([0x8d, 0xb8].concat(d32(s(0x46)), [0x05], d32(s(3)), [0x81, 0xc3], d32(s(0x43))), 0x498ca2);
          jmpPatch(0x498c99, c1, 9);
          // Cave_B2 @0x498CCF (5B: and eax,0x62; push 0): the AND's operand is a 0/-1 mask, so
          //   and eax,imm32 s(0x62) preserves the conditional exactly. + relocated push 0.
          const c2 = caveWithJmp([0x25].concat(d32(s(0x62)), [0x6a, 0x00]), 0x498cd4);
          jmpPatch(0x498ccf, c2, 5);
          // Cave_C @0x498E43 (6B: push 0x40; push eax; mov eax,[ebp-0x34]): icon target px 0x40 →
          //   s(0x40) imm32 (den stays the native source dim → draw = exactly s(64) px).
          const c3 = caveWithJmp([0x68].concat(d32(s(0x40)), [0x50, 0x8b, 0x45, 0xcc]), 0x498e49);
          jmpPatch(0x498e43, c3, 6);
          // in-place imm8 insets (guarded on the original byte)
          const poke8 = (va, want, val) => {
            if (VA(va).readU8() === (want & 0xff)) { VA(va).writeU8(val & 0xff); return 1; }
            log("v8 poke guard FAIL @0x" + va.toString(16)); return 0;
          };
          Memory.protect(VA(0x498c80), 0x200, "rwx");
          let n = 0;
          n += poke8(0x498c85, 0x03, s(3));      // lea ebx,[ecx+3]: icon/inner-box x anchor
          n += poke8(0x498cb0, 0xfd, -s(3));     // add eax,-3: band right inset
          n += poke8(0x498cbc, 0xfd, -s(3));     // lea eax,[edi-3]: band bottom inset
          n += poke8(0x498cdb, 0x1d, s(0x1d));   // lea edi,[eax+edi+0x1D]: band→card gap
          n += poke8(0x498d4f, 0x03, s(3));      // header text x inset
          n += poke8(0x498d60, 0x05, s(5));      // header text y inset
          // v9: the TEXT BOX (0x498E6C, rect [ebp-0x6C]) bottom is the ABSOLUTE-y imm32 0x2F at
          // 0x498D06 (= native clipTop 3 + 0x2C) and the striped SPACER (0x4991C8) top is 0x31 at
          // 0x498D0D (= 3 + 0x2E). v8 only scaled the outer band + spacer bottom, so the text box
          // stayed 44px tall while its 2 lines of scaled text grew. imm32 fields -> poke directly.
          const cTop = VA(G_RW + 0x5978).readS32();      // scaled clip top written by the v2 lever
          const poke32 = (va, want, val) => {
            if (VA(va).readS32() === want) { VA(va).writeS32(val); return 1; }
            log("v9 poke32 guard FAIL @0x" + va.toString(16)); return 0;
          };
          let m = 0;
          m += poke32(0x498d09, 0x2f, cTop + s(0x2c));   // text box bottom
          m += poke32(0x498d10, 0x31, cTop + s(0x2e));   // spacer top
          Memory.protect(VA(0x499100), 0x100, "rwx");
          m += poke8(0x49911e, 0x03, s(3));      // no-research branch: spacer x0 = x+3
          m += poke8(0x499177, 0x05, s(5));      // header line-2 y: ([y+3]+5)
          m += poke8(0x499181, 0x03, s(3));      // header line-2 y: +lineH+3
          log("v9 HEADER text box: bottom=" + (cTop + s(0x2c)) + " spacerTop=" + (cTop + s(0x2e)) +
              " (clipTop " + cTop + ", native 0x2F/0x31) pokes " + m + "/5");
          log("v8 HEADER armed: B1@" + c1 + " B2@" + c2 + " C@" + c3 + " insets " + n + "/6" +
              " s46=" + s(0x46) + " s43=" + s(0x43) + " s62=" + s(0x62) + " s1d=" + s(0x1d) +
              " icon=" + s(0x40) + "px (cardTopChain " + (s(0x46) + s(0x62) + s(0x1d)) + " was 197)");
        } else log("v8 HEADER NOT armed (guard mismatch — bytes not pristine?)");
      } catch (e) { log("v8 HEADER threw: " + e); }

      // ===================== v9 CONSOLE (kind-2 console, map: _rw_console_tech_map.md) =====================
      // Painter FUN_004A7000 (per repaint) + ReportIf_activate builders (per open): every rect is
      // FIELD-derived from the HUD-scaled region rects; only the native additive constants below are
      // still 16-space. All pokes guard on the pristine byte; two imm8 overflows get caves.
      try {
        const ri = VA(G_RI);
        const rd = o => ri.add(o).readS32();
        const pk8 = (va, want, val) => {
          if (VA(va).readU8() === (want & 0xff)) { VA(va).writeU8(val & 0xff); return 1; }
          log("v9 pk8 guard FAIL @0x" + va.toString(16) + " have " + VA(va).readU8().toString(16)); return 0;
        };
        const pk32 = (va, want, val) => {
          if (VA(va).readS32() === want) { VA(va).writeS32(val); return 1; }
          log("v9 pk32 guard FAIL @0x" + va.toString(16)); return 0;
        };
        Memory.protect(VA(0x4a7000), 0x1500, "rwx");
        Memory.protect(VA(0x4a4200), 0x1a00, "rwx");
        let c = 0, tot = 0;
        const P = (va, want, val) => { tot++; c += pk8(va, want, val); };
        // --- painter: left panel cursor, tab-area box, list box, list rect, row pitch (map §D) ---
        P(0x4a7023, 0x06, s(6));   P(0x4a7026, 0x06, s(6));
        P(0x4a7038, 0x0c, s(12));  P(0x4a7052, 0x0c, s(12));
        P(0x4a708b, 0x1a, s(0x1a));                     // tab-area box h
        P(0x4a70a4, 0x02, s(2));   P(0x4a70a7, 0x06, s(6));
        P(0x4a70cf, 0x20, s(0x20)); P(0x4a70d2, 0xe0, -s(0x20));   // list content top / h
        tot++; c += pk32(0x4a70f8, -3, -s(3));
        P(0x4a70fe, 0x03, s(3));   P(0x4a7108, 0x03, s(3));
        P(0x4a713c, 0x03, s(3));                        // row pitch = lineH + s(3)
        // --- painter: right panel cursor + bar block insets (map §A; the 9x 0xF are v7) ---
        P(0x4a7a67, 0x06, s(6));   P(0x4a7a6a, 0x06, s(6));
        P(0x4a7a80, 0x0c, s(12));  P(0x4a7a97, 0x0c, s(12));
        P(0x4a7abb, 0x06, s(6));   P(0x4a7ae6, 0x02, s(2));  P(0x4a7ae9, 0x06, s(6));
        P(0x4a7c2f, 0xfc, -s(4));  P(0x4a7c40, 0x04, s(4));
        P(0x4a7ca0, 0xfe, -s(2));  P(0x4a7ca3, 0x03, s(3));  P(0x4a7cba, 0xfa, -s(6));
        P(0x4a7dc8, 0x08, s(8));
        P(0x4a7f33, 0x02, s(2));   P(0x4a80d0, 0x02, s(2));  P(0x4a8267, 0x02, s(2));  P(0x4a8408, 0x02, s(2));
        // --- painter: centre title y (+10) and the 0x4C crest inset (mask form, overflows -> cave) ---
        P(0x4a7737, 0x0a, s(10));
        let ttl = "cave NOT armed";
        if (VA(0x4a75ff).readU8() === 0x83 && VA(0x4a7600).readU8() === 0xe0 && VA(0x4a7601).readU8() === 0x4c &&
            VA(0x4a7602).readU8() === 0x03 && VA(0x4a7603).readU8() === 0xc8) {
          const cv = caveWithJmp([0x25].concat(d32(s(0x4c)), [0x03, 0xc8]), 0x4a7604);   // and eax,s(0x4C); add ecx,eax
          jmpPatch(0x4a75ff, cv, 5); ttl = "cave@" + cv;
        }
        // --- activate: TECHNOLOGY/BASES toggles 0x92/0x93 (map §E) — rect + fixed font -> scaled clone ---
        P(0x4a455c, 0x09, s(9));   P(0x4a455f, 0x09, s(9));  P(0x4a4571, 0x12, s(0x12));
        P(0x4a45cc, 0x14, s(0x14)); P(0x4a4677, 0x14, s(0x14));
        let tf = 0;
        if (scaledBtnFp) {
          for (const fa of [0x4a461a, 0x4a46d2]) {
            if (VA(fa).readU32() === 0x6e84b4) { VA(fa).writePointer(scaledBtnFp); tf++; }
          }
        }
        // --- activate: faction tabs + the player's crest button (map §C) ---
        P(0x4a5aef, 0x05, s(5));   P(0x4a5af2, 0x25, s(0x25));
        P(0x4a5b19, 0x05, s(5));   P(0x4a5b1c, 0x25, s(0x25));
        P(0x4a5b77, 0x1d, s(0x1d));
        P(0x4a5b33, 0x0f, s(0xf)); P(0x4a5b36, 0x0f, s(0xf));
        let crest = "cave NOT armed";
        if (VA(0x4a5b43).readU8() === 0x83 && VA(0x4a5b44).readU8() === 0xc1 && VA(0x4a5b45).readU8() === 0x46 &&
            VA(0x4a5b46).readU8() === 0x83 && VA(0x4a5b47).readU8() === 0xc0 && VA(0x4a5b48).readU8() === 0x46) {
          const cv = caveWithJmp([0x81, 0xc1].concat(d32(s(0x46)), [0x05], d32(s(0x46))), 0x4a5b49);   // add ecx/eax, s(0x46)
          jmpPatch(0x4a5b43, cv, 6); crest = "cave@" + cv;
        }
        // --- activate: kind-tab button size = sprite dims x g/16 (map §G.2; the sprite's own dims stay native) ---
        let kt = "NOT armed";
        if (VA(0x4a42e0).readU8() === 0x8b && VA(0x4a42e1).readU8() === 0x8e && VA(0x4a42e6).readU8() === 0x8b && VA(0x4a42e7).readU8() === 0x96) {
          VA(0x4a42e0).writeByteArray([0xb9].concat(d32(s(0x24)), [0x90]));   // mov ecx, s(h)
          VA(0x4a42e6).writeByteArray([0xba].concat(d32(s(0x1e)), [0x90]));   // mov edx, s(w)
          kt = s(0x1e) + "x" + s(0x24);
        }
        // --- init_report_screen tables (already built natively by now -> rewrite the FIELDS) ---
        const wide = rd(0x1e230);
        const sL = rd(0x40), sT = rd(0x44), sB = rd(0x4c);            // tab-strip region
        const cL = rd(0x50), cB = rd(0x5c);                            // centre region
        const x0n = 16 + (wide ? 1 : 0), stepn = 9 + (wide ? 3 : 0) + 0x1e;
        const xs = [];
        for (let i = 0; i < 7; i++) { const x = sL + s(x0n + i * stepn); ri.add(0xa298 + 4 * i).writeS32(x); xs.push(x); }
        const ty = ((sT + sB) - s(0x24)) >> 1;
        ri.add(0xa2cc).writeS32(ty);
        const seeds = wide ? [0, 0x2a, 0x54, 0x7e, 0xa8, 0xd2, 0xfc] : [0, 0x25, 0x4a, 0x6f, 0x94, 0xb9, 0xde];
        const fxs = [];
        for (let f = 0; f < 7; f++) { const x = cL + s(seeds[f] + (wide ? 0x2b : 0) + 0x2e); ri.add(0x60 + 4 * f).writeS32(x); fxs.push(x); }
        const fy = cB - s(0x28);
        ri.add(0x7c).writeS32(fy);
        log("v9 CONSOLE pokes " + c + "/" + tot + " titleInset " + ttl + " crest " + crest + " kindtab " + kt +
            " toggleFont " + tf + "/2 wide=" + wide + " strip=(" + sL + "," + sT + ".." + sB + ") tabX=[" + xs.join(",") + "] tabY=" + ty +
            " facX=[" + fxs.join(",") + "] facY=" + fy);
        // --- research bars: bypass the HUD render-small->stretch detour (banding) at the 8 call sites ---
        let nb = 0;
        for (const site of BAR_SITES) {
          const rel = VA(site + 1).readS32();
          if (VA(site).readU8() === 0xe8 && (site + 5 + rel) === 0x5e2dd3) {
            VA(site + 1).writeS32(barCave.sub(VA(site + 5)).toInt32()); nb++;
          } else log("v9 BAR site guard FAIL @0x" + site.toString(16) + " target 0x" + (site + 5 + rel).toString(16));
        }
        log("v9 BARS: " + nb + "/8 sites -> native draw cave " + barCave + " + P-law restripe at painter exit (P=" +
            SL.stripePeriod(g) + ")");
        // v9.2 HEADER STROKES: the outer band (0x498D9B, set 0x78D5A0) and the text box (0x498E6C, set
        // 0x78D550) are plain `call Buffer_box_sprite` -> 1px strokes at every g (measured 1px @g25/g40;
        // pristine 3px/2.8125 = 1 native -> K=strokeWidth(g)). The DL-mode header draws the same sets
        // through t_dl_bmxt (hollow_flat render + exact-fill + fe_pair_remap: navy text-box field is a
        // remap family) -> redirect these two sites there (gated on g_dl_exec = my bracket; 4MB store).
        let hs = 0;
        for (const site of [0x498d9b, 0x498e6c]) {
          const tgt = site + 5 + VA(site + 1).readS32();
          if (VA(site).readU8() === 0xe8 && tgt === 0x5e2dd3) { VA(site + 1).writeS32(VA(T_DL_BMXT).sub(VA(site + 5)).toInt32()); hs++; }
          else log("v9.2 HDR stroke site guard FAIL @0x" + site.toString(16) + " target 0x" + tgt.toString(16));
        }
        log("v9.2 HEADER strokes: " + hs + "/2 sites -> t_dl_bmxt (K=" + SL.strokeWidth(g) + ")");
        // v9.5 BUTTON-ROW FRAME + WINDOW BORDER (FRAME trace: from 0x496CD5 / 0x496C96 in the ReportWin
        // show path FUN_00496960): row frame = grp1 rect (RW+0x7BF8 = 0x87E070..7C) grown by a NATIVE 3
        // (`add ebx,-3` 0x496CA8, `add ecx,-3` 0x496CAB, `mov ebx,3` 0x496CBB) then Buffer_box_sprite
        // (canvas, rect, 0x78D5A0) @0x496CD0; window border = Buffer_box_sprite(canvas, +0x5984,
        // 0x78D690) @0x496C91. Both 1px at every g (measured). Fix: grow -> s(3) (stroke K + channel
        // s(3)-K = s(2): 2+5 @g40, 2+3 @g25, 1+3 @g22 = pristine 1:2) and route both draws through
        // thunk_box_thick_hollow_flat (pcave2+0x140; g<=16 -> native; flat footprint, K stroke inward,
        // fe_pair_remap tail) — the same renderer the popup/DL frames use.
        try {
          Memory.protect(VA(0x496c80), 0x80, "rwx");
          let rf = 0;
          rf += pk8(0x496caa, 0xfd, -s(3));
          rf += pk8(0x496cad, 0xfd, -s(3));
          if (VA(0x496cbb).readU8() === 0xbb) { rf += pk32(0x496cbc, 3, s(3)); } else log("v9.5 guard FAIL @0x496cbb");
          // v9.6: the frame is drawn on the STORED rect grown in place, then shrunk back: L/T += ebx (the
          // poked 3 -> s(3), fine) but R/B += imm32 -3 @0x496CE6 -> net +4 per redraw = the creep.
          if (VA(0x496ce6).readU8() === 0xb8) { rf += pk32(0x496ce7, -3, -s(3)); } else log("v9.6 guard FAIL @0x496ce6");
          let rs = 0;
          // v9.7: the WINDOW BORDER set 0x78D690 is the FILLED backdrop (1px 0x41/0xC6 scanline dither over
          // the whole canvas). hollow_flat's render-small->stretch NN-beat that field at fractional g
          // (user: banding at non-4K; 4K's 2.5x hid it) and fe's navy family is content-keyed on 0xC4.
          // Use thunk_box_thick_devfill (pcave2+0x42A0: STEP1 hollow_flat bevel, STEP2 device-density
          // re-tile of the fill, STEP3 forced P-stripe remap = the popup-backdrop language) for it;
          // the hollow row frame (d5a0) keeps hollow_flat.
          // v9.8 HALF-OPEN LAW (feedback-half-open-draw-rects): vanilla Buffer_box_sprite draws the rect
          // half-open (last stroke row/col = B-1 / R-1) but the thick renderer covers [L..R]x[T..B]
          // INCLUSIVE (measured: bottom + right channels = s(2)+1 at g22/25/40, top/left = s(2)). The
          // row-frame call goes through a CALL-HELPER cave (scratchpad asm_halfopen.py, Unicorn-checked:
          // ebx preserved, esp clean, rect restored) that decrements R/B in place for the draw, calls
          // hollow_flat with re-pushed args, restores R/B -> the stored rect's grow/shrink round trip
          // stays exact and the drawn extent = vanilla x scale on all four sides.
          const hfBytes = []; for (let i = 0; i < "538b5c2408ff4b08ff4b0cff74240c53b840c1a000ffd0ff4308ff430c5bc20800".length; i += 2) hfBytes.push(parseInt("538b5c2408ff4b08ff4b0cff74240c53b840c1a000ffd0ff4308ff430c5bc20800".substr(i, 2), 16));
          const hoCave = makeCave(hfBytes);
          for (const [site, thunk] of [[0x496cd0, hoCave.toUInt32()], [0x496c91, PCAVE2 + 0x42a0]]) {
            const tgt = site + 5 + VA(site + 1).readS32();
            if (VA(site).readU8() === 0xe8 && tgt === 0x5e2dd3) { VA(site + 1).writeS32(VA(thunk).sub(VA(site + 5)).toInt32()); rs++; }
            else log("v9.5 frame site guard FAIL @0x" + site.toString(16) + " target 0x" + tgt.toString(16));
          }
          log("v9.8 ROW FRAME grow 3 -> " + s(3) + " (pokes " + rf + "/4), row frame -> half-open helper " + hoCave + " -> hollow_flat, window border/backdrop -> devfill (" + rs + "/2 sites, K=" + SL.strokeWidth(g) + ")");
        } catch (e) { log("v9.5 threw: " + e); }
      } catch (e) { log("v9 CONSOLE threw: " + e + " | " + e.stack); }

      log("POST rw.a1c/a20(w/h)=" + W + "/" + H + " a14/a18(x/y)=" + x + "/" + y +
          " outerW=" + Wout + " resize_rc=" + rc);
      log("POST clip+5974=" + rstr(rw.add(0x5974)) + " title+5984=" + rstr(rw.add(0x5984)) +
          " textB=" + safeS32(rw.add(0x5980)) + " lineH=" + lh);
      log("POST rRect1+13c=" + rstr(rw.add(0x13c)) + " client+14c=" + rstr(rw.add(0x14c)) +
          " canvasWH +4c4/+4c8=" + safeS32(rw.add(0x4c4)) + "/" + safeS32(rw.add(0x4c8)));
      log("POST fonts s(size)=" + swapped.join(",") + " lineH(f12)=" + lh);
    }
  });

  // paint-time watcher: log the live window/clip on the FIRST paint of each kind so a
  // run shows how each page laid out against the scaled frame (dest-keyed, cheap).
  const G_KIND = 0x885F40, A_RWPAINT = 0x496d00;
  const KN = { 0: "intel", 2: "tech", 3: "energy", 4: "bases", 5: "projects", 6: "sat", 7: "units", 8: "score" };
  const kseen = {};
  Interceptor.attach(VA(A_RWPAINT), {
    onLeave() {
      const k = safeS32(VA(G_KIND));
      if (kseen[k]) return; kseen[k] = 1;
      const rw = VA(G_RW);
      log("PAINT k=" + k + "(" + (KN[k] || "?") + ") clip=" + rstr(rw.add(0x5974)) +
          " rRect1=" + rstr(rw.add(0x13c)) + " cells 59A0/59A4/59A8=" +
          safeS32(rw.add(0x59a0)) + "/" + safeS32(rw.add(0x59a4)) + "/" + safeS32(rw.add(0x59a8)) +
          " rowRect+E258=" + rstr(rw.add(0xe258)));
    }
  });

  // =====================================================================
  // v3 (2026-09-02): TECH PAGE (kind 2). The tech card is the DL-shared code
  // GEN.TECH_LO/HI (0x498B9B..0x49BC94) that dl_scale already scales correctly
  // while Datalinks is open. Per the _rw_source_map §3 contract we PATCH NOTHING
  // in that no-attach range — instead we DRIVE the existing dl_scale TECH walker
  // from a ReportWin bracket: set g_dl_immg=g, run t_dl_immfix_tech (applies the
  // 162 geometric rows + 8 font PTR rows scaled), set g_dl_exec=1 (the baked
  // frame/arrow/mono thunks fire scaled), then revert on paint-leave (immg=16 ->
  // walker writes the native values back). v2 already scaled the prerequisites
  // that DL's t_dl_techwrap normally supplies (window/clip +0x5974, textB +0x5980,
  // lineH +0xE268, fonts) — so the card geometry + fonts should land at g.
  // Bracket the three card painters (all §5-SAFE entries), depth-counted so a
  // nested call (tech_page -> tech_connector) never reverts mid-paint.
  const PCAVE2 = 0xa0c000;
  const G_DL_IMMG = PCAVE2 + 0x27e10;   // 0xA33E10
  const G_DL_EXEC = PCAVE2 + 0x27e00;   // 0xA33E00
  const G_NETWIN  = PCAVE2 + 0x4800;    // 0xA10800
  const A_IMMFIX_TECH = PCAVE2 + 0x22190; // t_dl_immfix_tech (mov esi,TAB_TECH; jmp t_dl_immfix)
  const DL_FONTS = [0x71401c, 0x714094, 0x7140bc]; // DL F0/F3/F4 (PTR-row targets; sized lazily on DL open)
  const A_TECH_PAGE = 0x498b30, A_TECH_HOVER = 0x49b220, A_TECH_CONN = 0x49b450;
  // the 8 font-PTR sites the walker repoints (assemble_dl PTR_ROWS). When DL's fonts aren't
  // built (font[0]=0), we immediately rewrite these back to their NATIVE operands so the tech
  // page uses the (native, already-built) tech fonts — geometry still scales, no null-font crash.
  const FONT_PUSH = [0x4997b7, 0x4998f9, 0x499a3b, 0x499bab, 0x499d82, 0x499f08]; // push 0x6E84B4 (button label)

  const immfix_tech = new NativeFunction(VA(A_IMMFIX_TECH), "void", [], "mscdecl");

  // Are DL's embedded tech fonts sized? A built Font's font[0] is a signed line-metric (~-40..40);
  // an unbuilt slot reads 0. Checked ONCE at load — if unbuilt, we keep the tech fonts native.
  let techFontsOk = true;
  for (const fa of DL_FONTS) {
    let f0 = 0, f4 = 0, bad = false;
    try { f0 = VA(fa).readS32(); f4 = VA(fa).add(0x10).readS32(); } catch (e) { bad = true; }
    if (bad || f0 === 0 || Math.abs(f0) > 200) techFontsOk = false;
    log("DLfont @0x" + fa.toString(16) + " font[0]=" + (bad ? "THREW" : f0) + " font[4]=" + f4);
  }
  log(techFontsOk ? "DL fonts BUILT -> tech PTR rows use them (scaled fonts)"
                  : "DL fonts UNBUILT -> geometry scales but tech fonts kept NATIVE (no crash; font scaling TODO)");

  // Undo the walker's 8 PTR-row writes. Title/category -> NATIVE globals (they already scale
  // with resolution game-side). The 6 button-label sites -> the SCALED clone if we built one
  // (else native fallback). Opcodes/lengths match what the walker wrote (5-byte A1/68 forms).
  function techFontsToNative() {
    try {
      Memory.protect(VA(0x4997b0), 0x49a160 - 0x4997b0, "rwx");
      VA(0x499fe3).writeU8(0xa1); VA(0x499fe4).writeU32(0x8a40d4); // title: mov eax,[0x8A40D4] (game-scaled)
      VA(0x49a14a).writeU8(0xa1); VA(0x49a14b).writeU32(0x8a40c8); // category: mov eax,[0x8A40C8]
      for (const s of FONT_PUSH) {
        if (scaledBtnFp) VA(s + 1).writePointer(scaledBtnFp);     // push <scaled button font>
        else VA(s + 1).writeU32(0x6e84b4);                        // push 0x6E84B4 (native fallback)
      }
    } catch (e) { log("techFontsToNative threw: " + e); }
  }

  let techDepth = 0, techApplied = false, techLogged = false;
  function techApply() {
    const g = safeS32(VA(G_SCALE), 16);
    if (g <= 16) return false;
    VA(G_DL_IMMG).writeS32(g);
    immfix_tech();                       // apply scaled TECH imms (card/frame/connector GEOMETRY + PTR fonts)
    if (!techFontsOk) techFontsToNative(); // keep tech fonts native until we build scaled ones
    VA(G_DL_EXEC).writeS32(1);           // arm the baked tech-range frame/arrow/mono thunks
    VA(G_NETWIN).writeS32(1);            // match t_dl_exec_enter
    if (!techLogged) {
      techLogged = true;
      const rw = VA(G_RW);
      log("TECH applied g=" + g + " immg=" + safeS32(VA(G_DL_IMMG)) + " exec=" + safeS32(VA(G_DL_EXEC)) +
          " fonts=" + (techFontsOk ? "scaled" : "native") +
          " btn_w/h/card 59A0/59A4/59A8=" + safeS32(rw.add(0x59a0)) + "/" + safeS32(rw.add(0x59a4)) +
          "/" + safeS32(rw.add(0x59a8)) + " techContent+A14=" + rstr(rw.add(0xa14)) +
          " card+A28=" + rstr(rw.add(0xa28)));
      // one-time: dump the NATIVE tech Font structs so we can find their point-size field and
      // build scaled equivalents next iteration. title/category are Font* @[global]; button is
      // the Font object itself @0x6E84B4.
      const fdump = (label, fp) => {
        try {
          const ws = [];
          for (let i = 0; i < 10; i++) ws.push(fp.add(i * 4).readS32());
          log("NATIVEfont " + label + " @" + fp + " dw[0..9]=" + ws.join(","));
        } catch (e) { log("NATIVEfont " + label + " unreadable: " + e); }
      };
      try { fdump("title[8A40D4]", VA(0x8a40d4).readPointer()); } catch (e) {}
      try { fdump("categ[8A40C8]", VA(0x8a40c8).readPointer()); } catch (e) {}
      fdump("button@6E84B4", VA(0x6e84b4));
    }
    return true;
  }
  function techRevert() {
    VA(G_DL_IMMG).writeS32(16);
    immfix_tech();                       // walker writes the NATIVE values back (geometry + font sites)
    VA(G_DL_EXEC).writeS32(0);
    VA(G_NETWIN).writeS32(0);
  }
  function techBracket(addr, nm) {
    Interceptor.attach(VA(addr), {
      onEnter() {
        const k = safeS32(VA(G_KIND));
        if (k !== 2) { this._skip = true; return; }   // only the tech page
        if (techDepth === 0) techApplied = techApply();
        techDepth++;
      },
      onLeave() {
        if (this._skip) return;
        techDepth--;
        if (techDepth === 0 && techApplied) { techRevert(); techApplied = false; }
        if (techDepth === 0 && hdrDraws.length) {
          try { restripeDraws(hdrDraws, "HDR"); } catch (e) { log("hdr restripe threw: " + e + " | " + e.stack); }
          hdrDraws = [];
        }
      }
    });
  }
  techBracket(A_TECH_PAGE, "tech_page");
  techBracket(A_TECH_HOVER, "tech_hover");
  techBracket(A_TECH_CONN, "tech_conn");

  // =====================================================================
  // v8 BUTTON FACE (DATALINKS id9 / CLOSE id1). Measured at 4K: the frame outline spans the
  // full scaled 56px rect but the striped FACE band is exactly 20px = native 0x14 — the face is
  // a native-thickness CAP of the button's Buffer_box_sprite 9-slice (content_draw 0x607E50,
  // boxParams path @0x607F4D). Fix: clone the 10-dword params per button/state and put the face
  // band into slot 8 (CENTER), which Buffer_box_sprite TILES across the whole rect — tiling, not
  // stretching, so the stripe pattern stays clean (dither rule). The clone is installed by
  // repointing the BUTTON's own +0xAC8[state] field → shared params templates untouched, other
  // buttons unaffected. If the art turns out to live in the stateSprite (+0xAD4) or bevel
  // (+0xAE0/+0xB10) paths instead, the dump below says so and nothing is modified.
  const BTN_FACE = [["DATALINKS", 0x87c9d8], ["CLOSE", 0x87d524]];
  const btnClones = new Set();
  let btnFaceRuns = 0;
  function sliceDims(sp) {
    try {
      return sp.add(0x10).readS32() + "x" + sp.add(0x14).readS32() +
             "/c" + sp.add(0x18).readS32() + "x" + sp.add(0x1c).readS32();
    } catch (e) { return "?"; }
  }
  function btnFaceFix() {
    if (g <= 16 || btnFaceRuns >= 3) return;
    btnFaceRuns++;
    for (const [nm, ba] of BTN_FACE) {
      const b = VA(ba);
      for (let st = 0; st < 3; st++) {
        try {
          const bpp = b.add(0xac8 + st * 4);
          const bp = bpp.readPointer();
          let ss = ptr(0), co = ptr(0);
          try { ss = b.add(0xad4 + st * 4).readPointer(); co = b.add(0xb10 + st * 4).readPointer(); } catch (e) {}
          if (btnClones.has(bp.toString())) continue;         // already ours
          log("BTNART " + nm + " st" + st + " params=" + bp + " stateSprite=" + ss + " cornerTL=" + co);
          if (bp.isNull()) continue;
          let best = null, bestA = 0;
          const desc = [];
          for (let i = 0; i < 9; i++) {
            let sp = ptr(0);
            try { sp = bp.add(i * 4).readPointer(); } catch (e) {}
            if (sp.isNull()) { desc.push(i + ":0"); continue; }
            desc.push(i + ":" + sliceDims(sp));
            if (i < 8) {
              try {
                const a = sp.add(0x18).readS32() * sp.add(0x1c).readS32();
                if (a > bestA) { bestA = a; best = sp; }
              } catch (e) {}
            }
          }
          log("BTNART " + nm + " st" + st + " slots " + desc.join(" "));
          const center = bp.add(8 * 4).readPointer();
          if (center.isNull() && best) {
            const clone = Memory.alloc(0x40);
            _caves.push(clone);
            Memory.copy(clone, bp, 0x28);
            clone.add(8 * 4).writePointer(best);              // face band → tiled center
            bpp.writePointer(clone);
            btnClones.add(clone.toString());
            log("BTNART " + nm + " st" + st + " FACE-FIX installed: center=faceband " + best + " (" + sliceDims(best) + ")");
          } else if (!center.isNull()) {
            log("BTNART " + nm + " st" + st + " center already set (" + sliceDims(center) + ") — face is not the cap; NOT modified");
          }
        } catch (e) { log("BTNART " + nm + " st" + st + " threw: " + e); }
      }
    }
  }
  // ReportIf_activate 0x4A41D0 (§5-SAFE, outside the no-attach zone): buttons are (re)built here.
  Interceptor.attach(VA(0x4a41d0), {
    onEnter(args) { this.on = args[0].toInt32(); inActivate = !!this.on; },
    onLeave() {
      inActivate = false;
      if (!this.on) { techSb = null; VA(G_RAIL_SB).writePointer(NULL); wheelCells.writePointer(NULL); wheelCells.add(4).writePointer(NULL); return; }   // deactivate: drop the stashes
      try { btnFaceFix(); } catch (e) { log("btnFaceFix threw: " + e); }
      // v9.1 probe: the 1px outline + 2px channel around DATALINKS/CLOSE is the WIN border painter
      // (0x5F2EE9: [+0x128] nested box_2 outlines, colours [+0x120]/[+0x124], into nc buffer [+0xB4]);
      // dump the border fields + rects so the next pass can scale the offset (3) and stroke (K).
      try {
        for (const [nm, va] of [["DATALINKS", 0x87c9d8], ["CLOSE", 0x87d524]]) {
          const b = VA(va);
          const f = o => safeS32(b.add(o));
          log("BTNWIN " + nm + " flags+98=0x" + (f(0x98) >>> 0).toString(16) + " +0x100.." + [0x100, 0x104, 0x108, 0x10c, 0x110, 0x114, 0x118, 0x11c, 0x120, 0x124, 0x128, 0x12c, 0x130].map(o => "+" + o.toString(16) + "=" + f(o)).join(" ") +
              " rect13c=" + rstr(b.add(0x13c)) + " rect14c=" + rstr(b.add(0x14c)) + " canvas4c4/4c8=" + f(0x4c4) + "/" + f(0x4c8) +
              " nc+b4=" + b.add(0xb4).readPointer() + " ncWH=" + (b.add(0xb4).readPointer().isNull() ? "-" : safeS32(b.add(0xb4).readPointer().add(0x80)) + "/" + safeS32(b.add(0xb4).readPointer().add(0x84))));
        }
      } catch (e) { log("BTNWIN probe threw: " + e); }
    }
  });


  // ===================== v9 CONSOLE runtime machinery =====================
  // (a) Research bars: the 8 Buffer_box_sprite call sites in the kind-2 painter get redirected to
  // barCave = the 5 displaced prologue bytes of 0x5E2DD3 + jmp 0x5E2DD8, i.e. the NATIVE 9-slice
  // draw at the (already scaled) rect, skipping the bake's thunk_hud_boxframe (render-small ->
  // GDI stretch = the banding). The native draw tiles the 24x24 P2 fill 1:1 (1px period, absolutely
  // anchored to dest y). At painter exit the recorded rects are RESTRIPED with the P-law
  // (scaling_laws.js stripeTop: y mod P < hN -> top member), pair detected PER DRAW from the set's
  // fill Buffer rows 0/1 (never hardcoded), dark-member pair resolved by the vertical mate.
  const BAR_SITES = [0x4a7df2, 0x4a7e31, 0x4a7f8f, 0x4a7fce, 0x4a812c, 0x4a816b, 0x4a82c8, 0x4a8307];
  const barCave = caveWithJmp([0x51, 0x53, 0x55, 0x56, 0x57], 0x5e2dd8);
  let barDraws = [];
  let barLogs = 0;
  Interceptor.attach(barCave, {
    onEnter(args) {
      try {
        const r = args[0];
        barDraws.push({ dest: this.context.ecx, params: args[1],
          x0: r.readS32(), y0: r.add(4).readS32(), x1: r.add(8).readS32(), y1: r.add(12).readS32() });
      } catch (e) { log("bar record threw: " + e); }
    }
  });
  function pairOf(params) {
    const fill = params.add(0x20).readPointer();
    if (fill.isNull()) return null;
    const data = fill.add(0x54).readPointer(), stride = fill.add(0x4a8).readS32();
    if (data.isNull() || stride <= 0) return null;
    const top = data.readU8(), bot = data.add(stride).readU8();
    if (top === bot || top === 9 || bot === 9) return null;
    return { top: top, bot: bot };
  }
  function restripeBars() { restripeDraws(barDraws, "BAR"); }
  // generic P-law restripe of recorded 9-slice draws (bars, header spacer): pair per draw from the
  // set's fill Buffer; phase = dest-buffer row (scaling_laws.js stripeTop)
  function restripeDraws(draws, tag) {
    const gg = safeS32(VA(G_SCALE), 16);
    if (gg <= 16 || draws.length === 0) return;
    // group draws by identical rect (EMPTY + FULL share one rect; FULL is clip-limited)
    const groups = new Map();
    for (const d of draws) {
      const k = d.dest.toString() + ":" + d.x0 + "," + d.y0 + "," + d.x1 + "," + d.y1;
      let gI = groups.get(k);
      if (!gI) { gI = { dest: d.dest, x0: d.x0, y0: d.y0, x1: d.x1, y1: d.y1, pairs: [] }; groups.set(k, gI); }
      const p = pairOf(d.params);
      if (p && !gI.pairs.some(q => q.top === p.top && q.bot === p.bot)) gI.pairs.push(p);
    }
    let bars = 0, px = 0;
    for (const gI of groups.values()) {
      const dest = gI.dest;
      const W = dest.add(0x80).readS32(), H = Math.abs(dest.add(0x84).readS32());
      const pitch = dest.add(0x4a8).readS32(), data = dest.add(0x54).readPointer();
      if (data.isNull() || pitch <= 0 || gI.pairs.length === 0) continue;
      const x0 = Math.max(gI.x0, 0), x1 = Math.min(gI.x1, W), y0 = Math.max(gI.y0, 0), y1 = Math.min(gI.y1, H);
      if (x1 <= x0 || y1 <= y0) continue;
      // v9.2 MATE-REQUIRED rule (feedback-dither-pair-ambiguity, the v9.1 spacer "white strip"): a
      // pixel is rewritten ONLY if its pair-MATE occurs within +-R rows of the same column. A
      // genuine dither (native 1px, or NN-banded runs <=3) always has its mate within R=4; a SOLID
      // line of a member colour (the spacer's edge-art column 0x45, the nub's highlight) never does
      // and passes through untouched. The mate also selects the pair when a dark index is shared.
      const R = 4;
      const w = x1 - x0, ya = Math.max(y0 - R, 0), yb = Math.min(y1 + R, H);
      const rows = [];
      for (let y = ya; y < yb; y++) rows.push(new Uint8Array(data.add(y * pitch + x0).readByteArray(w)));
      const tops = gI.pairs.map(p => p.top), bots = gI.pairs.map(p => p.bot);
      const mateNear = (yy, x, mate) => {
        for (let d = 1; d <= R; d++) {
          const a = yy - d - ya, b = yy + d - ya;
          if (a >= 0 && rows[a][x] === mate) return true;
          if (b < rows.length && rows[b][x] === mate) return true;
        }
        return false;
      };
      for (let y = y0; y < y1; y++) {
        const r = rows[y - ya];
        const wantTop = SL.stripeTop(y, gg);
        let changed = false;
        for (let x = 0; x < w; x++) {
          const v = r[x];
          let k = -1;
          for (let i = 0; i < tops.length; i++) {           // which pair? the one whose MATE is nearby
            if (v === tops[i] && mateNear(y, x, bots[i])) { k = i; break; }
            if (v === bots[i] && mateNear(y, x, tops[i])) { k = i; break; }
          }
          if (k < 0) continue;                               // not a dither pixel (solid art / other index)
          const nv = wantTop ? tops[k] : bots[k];
          if (nv !== v) { r[x] = nv; changed = true; px++; }
        }
        if (changed) data.add(y * pitch + x0).writeByteArray(r);
      }
      bars++;
      if (barLogs < 12) { barLogs++; log(tag + " restriped dest=" + dest + " rect=(" + gI.x0 + "," + gI.y0 + "," + gI.x1 + "," + gI.y1 + ") pairs=" +
        gI.pairs.map(p => "0x" + p.top.toString(16) + "/0x" + p.bot.toString(16)).join(" ")); }
    }
    if (barLogs < 16 && bars) { barLogs++; log(tag + "S restriped: " + bars + " rects, " + px + " px rewritten (g=" + gg + " P=" + SL.stripePeriod(gg) + ")"); }
  }
  // kind-2 console painter: reset the record on entry, restripe on exit (before the console flip)
  Interceptor.attach(VA(0x4a7000), {
    onEnter() { barDraws = []; },
    onLeave() { try { restripeBars(); } catch (e) { log("restripeBars threw: " + e + " | " + e.stack); } barDraws = []; }
  });

  // (b) stateSprite FlatButtons of the console (7 kind tabs @RI+0x5384, 7 faction tabs incl. the
  // player's crest @RI+0x80; stride 0xB4C): the icon blit at 0x607F43 = Sprite_draw_2(dest,key,x,y,1,1)
  // centred 1:1. The site is call-redirected to thunk_faction_portrait (pcave2+0x2100) -> hook that
  // entry, gate on the DEST button range, and pass num=g/den=16 with the centre recomputed for the
  // scaled sprite (W=[btn+0x4C4], H=-[btn+0x4C8]). Scrollbar arrows are NOT in the range (they take
  // the 2dzoom pipeline via the gate below).
  const T_FACTION_PORTRAIT = PCAVE2 + 0x2100;
  const FT_LO = G_RI + 0x80, FT_HI = G_RI + 0x80 + 7 * 0xb4c;          // faction tabs
  const KT_LO = G_RI + 0x5384, KT_HI = G_RI + 0x5384 + 7 * 0xb4c;      // kind tabs
  let iconLogs = 0;
  Interceptor.attach(VA(T_FACTION_PORTRAIT), {
    onEnter(args) {
      try {
        const gg = safeS32(VA(G_SCALE), 16);
        if (gg <= 16) return;
        const btn = args[0].toUInt32() - 0x444;
        const isFT = btn >= FT_LO && btn < FT_HI, isKT = btn >= KT_LO && btn < KT_HI;
        if (!isFT && !isKT) return;
        if (args[4].toInt32() !== 1 || args[5].toInt32() !== 1) return;     // only the native 1:1 call
        const spr = this.context.ecx;
        const sw = spr.add(0x18).readS32(), sh = spr.add(0x1c).readS32();
        const W = ptr(btn).add(0x4c4).readS32(), H = -ptr(btn).add(0x4c8).readS32();
        const dw = Math.floor(sw * gg / 16), dh = Math.floor(sh * gg / 16);
        args[2] = ptr((W - dw) >> 1); args[3] = ptr((H - dh) >> 1); args[4] = ptr(gg); args[5] = ptr(16);
        if (iconLogs < 24) { iconLogs++; log("ICON " + (isKT ? "kindtab" : "factiontab") + " btn=0x" + btn.toString(16) +
          " spr=" + spr + " " + sw + "x" + sh + " canvas " + W + "x" + H + " -> " + dw + "x" + dh + " at (" + ((W - dw) >> 1) + "," + ((H - dh) >> 1) + ")"); }
      } catch (e) { log("ICON hook threw: " + e); }
    }
  });

  // (c) list scrollbar (map §F.1): the ListBox child's own bar, w = g_scrollbar_w (12, set by scroll_small
  // @0x4A7114 and restored by scroll_normal @0x4A75C9). Scale the SHARED global only inside that
  // window, then stash the bar into the bake's g_rail_sb (pcave2+0x11260) so pref_sbzoom (grip zoom +
  // sb_restripe) and btn_stripes (arrow dither one-shot) arm exactly as for the popup family; the two
  // arrow FlatButtons (sb+0xAAC/+0x15F8) get the 2dzoom gate HIT below.
  const G_RAIL_SB = PCAVE2 + 0x11260, G_SCROLLBAR_W = 0x9b8dd4, SCROLL_VTBL = 0x669d58;
  let techSb = null, inTechList = false, sbLogs = 0;
  Interceptor.attach(VA(0x5883d0), {          // scroll_small
    onLeave() {
      const gg = safeS32(VA(G_SCALE), 16);
      if (gg > 16 && this.returnAddress.toUInt32() === 0x4a7119) {
        VA(G_SCROLLBAR_W).writeS32(SL.scalePx(12, gg));
        if (sbLogs < 4) { sbLogs++; log("SB g_scrollbar_w 12 -> " + SL.scalePx(12, gg) + " for the tech list attach"); }
      }
    }
  });
  Interceptor.attach(VA(0x60a670), {          // ListBox_attach
    onEnter() { this.tech = this.returnAddress.toUInt32() === 0x4a758c; if (this.tech) inTechList = true; },
    onLeave() { if (this.tech) inTechList = false; }
  });
  // v9.1: ScrollBar_attach 0x605890 has ONE caller (TextScroll 0x629464) — the ListBox child's bar is
  // built through ScrollBar_init_inner 0x6054D0 (9 callers) -> hook that (this=sb, args x,y,w,h,parent,id,flags).
  // v9.2 MOUSE WHEEL for the tech/bases list: PRACX turns wheel notches into synthetic VK_UP/DOWN
  // (lParam scan code 0) at the WinProc WM_KEYDOWN/KEYUP sites 0x5F07B0/0x5F07F0, which the bake
  // already chains through t_dl_wheel_down/up (Datalinks) -> thunk_wheel_down/up (Workshop/popups).
  // Report branch = the same thunk shape (assemble_dw.py asm_wheel / assemble_dl.py asm_dl_wheel_*),
  // gated basepop==0 && modal top==ReportWin && kind==2 && captured bar: chevron-press the list bar
  // (ScrollBar_chevron 0x606B20, 1=up 2=down) when engaged ([sb+0xC4]) and ranged, present the bar's
  // parent (vtbl+0xFC), eat the key; KEYUP twin eaten. Everything else chains to the DL thunks.
  // Position-independent bytes (scratchpad asm_wheel_rw.py: keystone + 12 Unicorn cases ALL-OK).
  const wheelCells = Memory.alloc(16); _caves.push(wheelCells);          // +0 sb, +4 parent
  wheelCells.writePointer(NULL); wheelCells.add(4).writePointer(NULL);
  function hexBytes(h, cellSb, cellParent) {
    const b = []; for (let i = 0; i < h.length; i += 2) b.push(parseInt(h.substr(i, 2), 16));
    const sub = (needle, val) => {
      for (let i = 0; i + 4 <= b.length; i++) {
        if (b[i] === needle[0] && b[i + 1] === needle[1] && b[i + 2] === needle[2] && b[i + 3] === needle[3]) { b.splice(i, 4, ...d32(val)); }
      }
    };
    sub([0x11, 0x11, 0x11, 0x11], cellSb); sub([0x22, 0x22, 0x22, 0x22], cellParent);
    return b;
  }
  {
    const cs = wheelCells.toUInt32(), cp = wheelCells.add(4).toUInt32();
    const wd = makeCave(hexBytes("833d7c8d9b00000f8595000000813de07a9b00786487000f8585000000833d405f880002757ca11111111185c07473b8506a5f00ffd085c07467837c246c0075608b54246883fa26740583fa2875525356578b3d1111111183bfc400000000743d8b8f240a00003b8f200a00007e2fbb0100000083fa267405bb020000005389f9b8206b6000ffd08b35222222228b1689f1ff92fc00000031c05f5e5bc35f5e5bc368b0f0a200c3", cs, cp));
    const wu = makeCave(hexBytes("833d7c8d9b00007541813de07a9b00786487007535833d405f880002752ca11111111185c07423b8506a5f00ffd085c07417837c246c0075108b54246883fa26740583fa28750231c0c36810f2a200c3", cs, cp));
    let armed = 0;
    for (const [site, want, cave] of [[0x5f07b0, 0xa2f0b0, wd], [0x5f07f0, 0xa2f210, wu]]) {
      const tgt = site + 5 + VA(site + 1).readS32();
      if (VA(site).readU8() === 0xe8 && tgt === want) {
        Memory.protect(VA(site), 8, "rwx"); VA(site + 1).writeS32(cave.sub(VA(site + 5)).toInt32()); armed++;
      } else log("WHEEL site guard FAIL @0x" + site.toString(16) + " target 0x" + tgt.toString(16));
    }
    log("v9.2 WHEEL caves armed " + armed + "/2: down@" + wd + " up@" + wu + " cells@" + wheelCells + " (chain -> t_dl_wheel_down/up)");
  }
  Interceptor.attach(VA(0x6054d0), {          // ScrollBar_init_inner (this=sb)
    onEnter(args) {
      if (!inTechList) return;
      const sb = this.context.ecx;
      const vt = safeS32(sb, 0);
      techSb = sb;
      wheelCells.writePointer(sb); wheelCells.add(4).writePointer(args[4]);   // wheel target + present target
      const gg = safeS32(VA(G_SCALE), 16);
      if (gg > 16) VA(G_RAIL_SB).writePointer(sb);
      if (sbLogs < 16) { sbLogs++; log("SB tech list bar " + sb + " vtbl=0x" + (vt >>> 0).toString(16) + (vt === SCROLL_VTBL ? "(Scroll)" : "(?)") +
        " x=" + args[0].toInt32() + " y=" + args[1].toInt32() + " w=" + args[2].toInt32() + " h=" + args[3].toInt32() +
        " parent=" + args[4] + " id=" + args[5].toInt32() + " flags=0x" + args[6].toUInt32().toString(16) +
        " g_scrollbar_w=" + safeS32(VA(G_SCROLLBAR_W)) + (gg > 16 ? " -> g_rail_sb stashed (arrows " + sb.add(0xaac) + "/" + sb.add(0x15f8) + ")" : "")); }
    }
  });

  // v9.2 probe: the 1px outline + 2px channel around the row is the generic Win border painter
  // 0x5F2CF0 (single caller 0x5D68A8; loops [+0x128] nested Buffer_box_2 with colours +0x120/+0x124
  // into buffer [+0xC0], rects from +0x150/+0x158). Dump the geometry for the two buttons so the
  // K-stroke + s(3)-offset overdraw can be written against measured fields, not a model.
  let bpLogs = 0;
  Interceptor.attach(VA(0x5f2cf0), {
    onEnter(args) {
      const w = this.context.ecx.toUInt32();
      if (w !== 0x87c9d8 && w !== 0x87d524) return;
      if (bpLogs++ >= 6) return;
      try {
        const b = this.context.ecx, f = o => safeS32(b.add(o));
        const buf = b.add(0xc0).readPointer();
        log("BTNBORDER " + (w === 0x87c9d8 ? "DATALINKS" : "CLOSE") + " arg0=" + args[0] + " buf+c0=" + buf +
            (buf.isNull() ? "" : " bufWH=" + safeS32(buf.add(0x80)) + "/" + safeS32(buf.add(0x84)) + " pitch=" + safeS32(buf.add(0x4a8))) +
            " buf+b4=" + b.add(0xb4).readPointer() + " +148.." + [0x148, 0x14c, 0x150, 0x154, 0x158, 0x15c, 0x160, 0x164, 0x168].map(o => "+" + o.toString(16) + "=" + f(o)).join(" ") +
            " +104=" + f(0x104) + " +120/124/128=" + f(0x120) + "/" + f(0x124) + "/" + f(0x128) + " +11c=" + f(0x11c) + " +130=" + f(0x130));
      } catch (e) { log("BTNBORDER probe threw: " + e); }
    }
  });

  // --- v9 BUTTON FACE, the real mechanism: DATALINKS/CLOSE are bevel-path FlatButtons (BTNART:
  // params=0, stateSprite=0, cornerTL=0x77A8E0..) = the default interface.pcx 3x20 caps + 67x20
  // body tiled at NATIVE 20 rows over the canvas top; rows 20..|H| stay key-9 (transparent). The
  // bake already owns this exact case for popup buttons: popup_button_2dzoom = thunk_btn_shrink
  // @0x607E7F (native-dims draw) -> fillcap @0x608118 -> thunk_btn_2dscale @0x608365 (KSB zoom +
  // devfill re-tile at device density + pair remap). Its gate = thunk_btn_gate_pre (pcave2+0x16DA0,
  // esi=button, eax=1 HIT; single E8 caller pcave2+0x40B does test eax). Proto: force HIT for the
  // two statics via retval (bake form = two `cmp esi,imm32; je hit` prefix rows in gate_pre).
  const T_BTN_GATE_PRE = PCAVE2 + 0x16da0;   // 0xA22DA0
  // v9: + the TECHNOLOGY/BASES toggles (BaseButtons RI+0xBA0C/+0xC558, box-triple faces = the popup
  // OK/CANCEL case the pipeline is verified on) + the tech list's two scrollbar arrows (dynamic).
  const BTN_HIT = new Set([0x87c9d8, 0x87d524, G_RI + 0xba0c, G_RI + 0xc558]);
  const btnHit = esi => BTN_HIT.has(esi) || (techSb !== null && (esi === techSb.add(0xaac).toUInt32() || esi === techSb.add(0x15f8).toUInt32()));
  let gateHits = 0;
  Interceptor.attach(VA(T_BTN_GATE_PRE), {
    onEnter() { this.hit = btnHit(this.context.esi.toUInt32()); },
    onLeave(rv) {
      if (this.hit && rv.toInt32() === 0) {
        rv.replace(ptr(1));
        if (gateHits++ < 24) log("BTNGATE HIT esi=" + this.context.esi + " -> 2dzoom pipeline (g=" + safeS32(VA(G_SCALE)) + ")");
      }
    }
  });

  // --- v8.1 CRASH FIX: the dl_scale bake's t_dl_bmxt (0xA2E680, the Buffer_box_sprite wrapper
  // at the 10 tech-bracket frame sites incl. the F2 header band 0x4991C8/0x499253) snapshots the
  // canvas under bbox(rect-2,+4) into g_dl_snapbuf [0xA33E78] = ONE 64KB VirtualAlloc, no bounds
  // check (assemble_dl.py asm_dl_bmxt). v8 scales the band height 0x46 -> s(0x46): at 4K the band
  // bbox is ~1610 x ~136 px = ~219KB > 64KB -> rep movsb ran off the store (AV @0xA2E7B4, 4K F2).
  // Native height fit by ~14KB of luck. Proto fix: pre-seed the store with a retained 4MB buffer
  // (the thunk allocates only when the cell is 0, so seeding before any DL/F2 draw replaces it;
  // if DL already allocated its 64KB this session we overwrite the pointer and leak 64KB — proto).
  // BAKE NOTE: rw_scale must grow g_dl_snapbuf (size by dest W*H, or lazy realloc on bbox bytes).
  const G_DL_SNAPBUF = 0xa33e78, T_DL_BMXT = 0xa2e680;   // G_DL_EXEC 0xA33E00 declared above
  const SNAP_BYTES = 4 << 20;
  {
    const snap = Memory.alloc(SNAP_BYTES);
    _caves.push(snap);                       // retain forever (feedback-frida-memory-alloc-gc)
    const prev = VA(G_DL_SNAPBUF).readPointer();
    VA(G_DL_SNAPBUF).writePointer(snap);
    log("v8.1 g_dl_snapbuf seeded: " + snap + " (" + SNAP_BYTES + " bytes; prev=" + prev + ")");
  }
  // probe: log every t_dl_bmxt entry's bbox bytes (first 16) — sizes the bake's store and proves the fit
  let bmxtLogs = 0;
  // v9.1: the F2 header SPACER (0x4991C8 + 0x499253, same rect, 2 param sets) goes through the DL
  // bake's t_dl_bmxt -> thunk_box_thick_hollow_flat (render-small -> GDI stretch) and its 24x24 P2
  // fill bands like the bars did (fe_pair_remap owns none of these pairs). Record the two draws
  // here and restripe them at tech_page exit with the same per-draw-pair P-law walk as the bars.
  // v9.3: + the TEXT BOX draw (0x498E6C -> ret 0x498E71, set 0x78D550): its navy/black field came
  // out of the bmxt render-small->stretch NN-beaten (measured 2/1/2/1/2/2 @g25, 3/2/3/3/4/2 @g40) —
  // fe_pair_remap's navy family is content-keyed on the small render's top rows (frame art there),
  // so it left the field alone. Same per-draw-pair P-law restripe as the spacer; text glyphs and
  // strokes are other indices and pass through.
  const HDR_SPACER_RETS = new Set([0x4991cd, 0x499258, 0x498e71]);
  let hdrDraws = [];
  Interceptor.attach(VA(T_DL_BMXT), {
    onEnter(args) {
      try {
        const ra = this.returnAddress.toUInt32();
        if (HDR_SPACER_RETS.has(ra) && safeS32(VA(G_DL_EXEC)) !== 0) {
          const r = args[0];
          hdrDraws.push({ dest: this.context.ecx, params: args[1],
            x0: r.readS32(), y0: r.add(4).readS32(), x1: r.add(8).readS32(), y1: r.add(12).readS32() });
        }
      } catch (e) { log("hdr record threw: " + e); }
      if (bmxtLogs >= 16) return;
      try {
        const dest = this.context.ecx, r = args[0];
        const W = safeS32(dest.add(0x80)), H = Math.abs(safeS32(dest.add(0x84)));
        const x0 = Math.max(safeS32(r) - 2, 0), y0 = Math.max(safeS32(r.add(4)) - 2, 0);
        const x1 = Math.min(safeS32(r.add(8)) + 4, W), y1 = Math.min(safeS32(r.add(12)) + 4, H);
        const bytes = Math.max(x1 - x0, 0) * Math.max(y1 - y0, 0);
        bmxtLogs++;
        log("BMXT from " + this.returnAddress + " exec=" + safeS32(VA(G_DL_EXEC)) + " rect=" + rstr(r) +
            " bbox=" + (x1 - x0) + "x" + (y1 - y0) + " bytes=" + bytes +
            (bytes > SNAP_BYTES ? " *** OVERFLOWS store ***" : (bytes > 0x10000 ? " (>64KB: needs seeded store)" : "")));
      } catch (e) { log("BMXT probe threw: " + e); }
    }
  });

  // v9.3 TRACE: who draws the 1px frame around the DATALINKS/CLOSE row? (not the buttons' art, not the
  // Win border painter 0x5F2CF0 — never entered for them). Log every outline/line primitive of row
  // width while ReportWin is the modal top: Buffer_box_2 (rect,c_h,c_v), Buffer_box (x0,y0,x1,y1,..),
  // Buffer_hline_2 (x0,x1,y,c), Buffer_vline_2 (x,y0,y1,c) — dest, args, return address.
  const G_MODAL_TOP = 0x9b7ae0;
  let frLogs = 0;
  // the row frame is painted at ReportIf_activate time (Win_show of the buttons), BEFORE ReportWin
  // becomes the modal top, and hover repaints never redraw it -> gate on activate-in-progress too
  let inActivate = false;
  const reportTop = () => inActivate || safeS32(VA(G_MODAL_TOP)) === G_RW;
  Interceptor.attach(VA(0x5e3203), { onEnter(args) {          // Buffer_box_2(rect, c_h, c_v)
    if (!reportTop() || frLogs >= 40) return;
    try { const r = args[0]; if (r.isNull()) return; const w = r.add(8).readS32() - r.readS32(); if (w < 150) return;
      frLogs++; log("FRAME box_2 dest=" + this.context.ecx + " rect=" + rstr(r) + " c=" + args[1].toInt32() + "/" + args[2].toInt32() + " from " + this.returnAddress); } catch (e) {}
  } });
  Interceptor.attach(VA(0x5e3193), { onEnter(args) {          // Buffer_box(x0,y0,x1,y1,c_h,c_v)
    if (!reportTop() || frLogs >= 40) return;
    const w = args[2].toInt32() - args[0].toInt32(); if (w < 150) return;
    frLogs++; log("FRAME box dest=" + this.context.ecx + " (" + args[0].toInt32() + "," + args[1].toInt32() + "," + args[2].toInt32() + "," + args[3].toInt32() + ") c=" + args[4].toInt32() + "/" + args[5].toInt32() + " from " + this.returnAddress);
  } });
  Interceptor.attach(VA(0x5e1bf0), { onEnter(args) {          // Buffer_vline_2(x,y0,y1,c)
    if (!reportTop() || frLogs >= 40) return;
    const h = args[2].toInt32() - args[1].toInt32(); if (h < 20 || h > 120) return;
    frLogs++; log("FRAME vline dest=" + this.context.ecx + " x=" + args[0].toInt32() + " y=" + args[1].toInt32() + ".." + args[2].toInt32() + " c=" + args[3].toInt32() + " from " + this.returnAddress);
  } });
  Interceptor.attach(VA(0x5d8240), { onEnter(args) {          // Buffer_fill(x,y,w,h,c) — thin row-wide fills
    if (!reportTop() || frLogs >= 40) return;
    const w = args[2].toInt32(), h = args[3].toInt32(); if (w < 300 || h > 4) return;
    frLogs++; log("FRAME fill dest=" + this.context.ecx + " (" + args[0].toInt32() + "," + args[1].toInt32() + " " + w + "x" + h + ") c=" + args[4].toInt32() + " from " + this.returnAddress);
  } });
  Interceptor.attach(VA(0x5e1a80), { onEnter(args) {          // Buffer_hline_2(x0,x1,y,c)
    if (!reportTop() || frLogs >= 40) return;
    const w = args[1].toInt32() - args[0].toInt32(); if (w < 300) return;
    frLogs++; log("FRAME hline dest=" + this.context.ecx + " x=" + args[0].toInt32() + ".." + args[1].toInt32() + " y=" + args[2].toInt32() + " c=" + args[3].toInt32() + " from " + this.returnAddress);
  } });

  // v9.4 TRACE: 9-slice frames. Every Buffer_box_sprite enters the bake's thunk_hud_boxframe
  // (0xA11740) via the prologue E8 at 0x5E2DD3: at thunk entry [esp]=0x5E2DD8, [esp+4]=the ORIGINAL
  // caller's return, [esp+8]=rect, [esp+0xC]=params, ecx=dest. Log row-width draws while ReportWin
  // is the modal top (dest, rect, params set, caller).
  Interceptor.attach(VA(0xa11740), { onEnter() {
    if (!reportTop() || frLogs >= 40) return;
    try {
      const sp = this.context.esp, r = sp.add(8).readPointer();
      if (r.isNull()) return;
      const w = r.add(8).readS32() - r.readS32(), h = r.add(12).readS32() - r.add(4).readS32();
      if (w < 150 || h > 200) return;
      frLogs++; log("FRAME box_sprite dest=" + this.context.ecx + " rect=" + rstr(r) + " params=" + sp.add(0xc).readPointer() + " from " + sp.add(4).readPointer());
    } catch (e) {}
  } });

  log("attached: init_report_screen 0x4A3460 (one-shot lever + v8 header caves) + rw_paint watcher + " +
      "TECH bracket (tech_page/hover/conn -> dl_scale walker; geometry ALWAYS scales, fonts " +
      (techFontsOk ? "scaled" : "native-until-sized") + ") + ReportIf_activate 0x4A41D0 (v8 button-face fix) + t_dl_bmxt 0xA2E680 probe (v8.1) + btn_gate_pre HIT for DATALINKS/CLOSE/toggles/sb-arrows + painter 0x4A7000 bar restripe + icon blit + scrollbar stash (v9) + wheel caves 0x5F07B0/F0 + header stroke bmxt + border probe (v9.2)");
}
