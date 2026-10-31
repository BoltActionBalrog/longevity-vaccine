// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// hook_tech_proto.js — SELECT RESEARCH GOAL (tech_pick / TechWin) scaling PROTOTYPE v3
// (2026-08-28).  Law decision: option (a) — vanilla's own screen-fit window law kept
// and evaluated at DEVICE density (every native constant x g/16), contents x g/16.
// Reference: work\_tech_static_map.md (sites), work\_tech_pixel_geometry.md (targets),
// work\_tech_patch_plan.md (site table + "Proto v1 RESULT"), laws tech_* in
// scripts\scaling_laws.py (JS port: globalThis.SL.tech*).
//
// MECHANISM (the SE-proto pattern, hook_se_scale_proto.js):
//   * the cluster 0x484A80..0x488654 + tech_pick carries ZERO patches/PRACX stomps, so
//     every native immediate is patched IN PLACE once per process (Memory.patchCode) at
//     the first tech_pick entry, when g_popup_scale_num is known.  g<=16 -> nothing is
//     touched (native no-op).  Every site's ORIGINAL bytes are verified first.
//   * chrome: the d690 backdrop site is rel32-redirected to the baked
//     thunk_box_thick_devfill; the d618 strip + d528/d578 cell sites go through
//     stub_rb1 (a COPY of the rect with R-1/B-1, then devfill).  MEASURED: devfill paints
//     the R/B strokes 1 px OUTSIDE the half-open rect (R-1..R @K=2, R @K=1) at g=22/25/40
//     on every cell + the strip (v1), and the §5 exact-fill flag did NOT move them (v2
//     read-backs) -> the constant -1 is the measured compensation, not a model.
//   * the icon blit ratio (SCALE_NUM_G/DEN_G) and iconW are realised by the imm law
//     tech_icon_imms: den 16->256, the three s-class literals -> (16+s)*g-16, sar 4->8.
//   * v2 CELL INSET LAW: `mov eax,3` @0x48646C feeds R-=3, B-=3 AND the L-clamp -> 11-byte
//     cut to stub_inset: R/B inset c_rb = s(4)-1 (absorbs the native +1 gutter: gap = s(4)),
//     L-clamp s(3).  Strip height imm = s(26)-s(3) (one cascade).
//   * v2 FONTS: find_font (0x5882F0) snaps to font_size_table (cap 40) -> the name/title
//     fonts were x2.0 @4K.  All TechWin fonts are now CELL-calibrated (target cell =
//     fl(native_cell*g/16), Font_init at the smallest nominal whose cell >= target;
//     precedent thunk_popup_setup_fonts / memory project_smac_font_calibration):
//     - 4 Font_init sites -> stub_fi (dispatch on native size+flags, rewrite the size);
//     - 8 find_font sites -> stub_ff (dispatch on native size+variant -> dedicated Font*)
//       built from the POOL font's own face + cell (v2 LOGFONT read-back: the pool fonts
//       are "Arial Narrow" bold while g_hud_font_name is "Arial" -> v2 calibrated the
//       right height in the wrong face); the variant -> Font_init style map is VERIFIED
//       per pool font via GetObjectA (weight/italic/height), precedent {1:1, 2:3} fallback;
//     - the n>8 `mov esi,edi` share (edi = pad = s(10)) -> 9-byte cut to stub_n8 so the
//       body font size stays native 10.
//   * NO Interceptor anywhere but plain function ENTRIES (tech_pick, TechWin_draw_cell,
//     Sprite_draw_mono_2, Buffer_write_strings, Buffer_wrap_cent_4 — all audited clean
//     in the census), used ONLY to log actual-vs-law.  v2 adds a CANVAS READ-BACK of the
//     drawn stroke bytes around each cell's R/B edge, the strip bottom and the window edge
//     (measure the engine; the exact-fill claim is verified from pixels, not modelled).
//
// KNOWN PROTO LIMITATIONS (bake items, see work\_tech_patch_plan.md):
//   * 1-byte `inc` gutters stay +1 (pitch = cw+1, W = ..+1, category x+1, unlock x+1):
//     the law keeps them native by design (draw/hit-test share them).
//   * n>8 overflow margin `add eax,-0x45` (imm8) overflows at g>=30 -> logged SKIP.
//   * caption text vertical centring nudge (skill scaling-text) not applied (v1 measured
//     13/12 rows above/below = vanilla's own 1-px overflow; leave).
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_tech_proto.log";
log("=== hook_tech_proto.js v3b started " + new Date().toISOString() + " ===");
installAVHandler("tech_proto");

// STUBS-BEGIN (pure JS, no Frida API; extracted + keystone/capstone-verified by tests\test_tech_stubs.py)
globalThis.TechStubs = (function () {
  function Asm(base) { this.base = base >>> 0; this.b = []; }
  Asm.prototype.at = function () { return (this.base + this.b.length) >>> 0; };
  Asm.prototype.put = function () { for (let i = 0; i < arguments.length; i++) this.b.push(arguments[i] & 0xFF); return this; };
  Asm.prototype.i32 = function (v) { v = v | 0; return this.put(v, v >> 8, v >> 16, v >> 24); };
  Asm.prototype.jmp = function (target) { this.put(0xE9); return this.i32(((target >>> 0) - (this.at() + 4)) | 0); };
  Asm.prototype.align = function (n) { while (this.b.length % n) this.b.push(0xCC); return this; };
  // C: { cRb, cL, fontInit, findFont, devfill, rbRect (16B scratch), fi: [[S, flags, N]..], ff: [[S, variant, fontPtr]..] }
  function build(base, C) {
    const a = new Asm(base), off = {};
    // stub_inset (called from the 0x48646C cut: mov eax,3 / sub ebx,eax / sub edx,eax / cmp ecx,eax)
    off.inset = a.b.length;
    a.put(0x81, 0xEB).i32(C.cRb);          // sub ebx, c_rb        (R)
    a.put(0x81, 0xEA).i32(C.cRb);          // sub edx, c_rb        (B)
    a.put(0xB8).i32(C.cL);                 // mov eax, c_l         (L clamp; flags of the cmp survive ret)
    a.put(0x3B, 0xC8);                     // cmp ecx, eax
    a.put(0xC3);                           // ret
    a.align(16);
    // stub_n8 (called from the 0x487981 cut: mov esi,edi / mov [ebp+8],12) -> body font native 10
    off.n8 = a.b.length;
    a.put(0xBE).i32(10);                   // mov esi, 10
    a.put(0xC7, 0x45, 0x08).i32(12);       // mov dword [ebp+8], 12
    a.put(0xC3);
    a.align(16);
    // stub_fi: Font_init(this=ecx; [esp+4]=name, [esp+8]=size, [esp+0xC]=flags) RET 0xC
    off.fi = a.b.length;
    for (const [S, f, N] of C.fi) {
      a.put(0x81, 0x7C, 0x24, 0x08).i32(S);   // cmp dword [esp+8], S
      a.put(0x75, 23);                        // jne next  (entry = 33 bytes: 8+2+8+2+8+5; 10 consumed)
      a.put(0x81, 0x7C, 0x24, 0x0C).i32(f);   // cmp dword [esp+0xC], flags
      a.put(0x75, 13);                        // jne next  (20 consumed)
      a.put(0xC7, 0x44, 0x24, 0x08).i32(N);   // mov dword [esp+8], N
      a.jmp(C.fontInit);                      // jmp Font_init (RETs 0xC to the site)
    }
    a.jmp(C.fontInit);                        // default: untouched
    a.align(16);
    // stub_ff: find_font([esp+4]=size, [esp+8]=variant) cdecl -> eax = Font*
    off.ff = a.b.length;
    for (const [S, v, p] of C.ff) {
      a.put(0x81, 0x7C, 0x24, 0x04).i32(S);   // cmp dword [esp+4], S
      a.put(0x75, 16);                        // jne next  (entry = 26 bytes: 8+2+8+2+5+1; 10 consumed)
      a.put(0x81, 0x7C, 0x24, 0x08).i32(v);   // cmp dword [esp+8], variant
      a.put(0x75, 6);                         // jne next  (20 consumed)
      a.put(0xB8).i32(p);                     // mov eax, Font*
      a.put(0xC3);                            // ret
    }
    a.jmp(C.findFont);                        // default: the pool
    a.align(16);
    // stub_rb1: Buffer_box_sprite(this=ecx; [esp+4]=&rect, [esp+8]=params) -> devfill with a COPY of the
    // rect whose R/B are -1 (the caller keeps its own rect; draw_cell reuses it for the content)
    off.rb1 = a.b.length;
    a.put(0x50, 0x52);                        // push eax; push edx
    a.put(0x8B, 0x54, 0x24, 0x0C);            // mov edx, [esp+0xC]  (&rect)
    a.put(0x8B, 0x02).put(0xA3).i32(C.rbRect);                 // mov eax,[edx];              mov [rb],    eax
    a.put(0x8B, 0x42, 0x04).put(0xA3).i32(C.rbRect + 4);       // mov eax,[edx+4];            mov [rb+4],  eax
    a.put(0x8B, 0x42, 0x08).put(0x48).put(0xA3).i32(C.rbRect + 8);   // mov eax,[edx+8];   dec eax; mov [rb+8],  eax
    a.put(0x8B, 0x42, 0x0C).put(0x48).put(0xA3).i32(C.rbRect + 12);  // mov eax,[edx+0xC]; dec eax; mov [rb+12], eax
    a.put(0xC7, 0x44, 0x24, 0x0C).i32(C.rbRect);   // mov dword [esp+0xC], rb   (replace the &rect arg)
    a.put(0x5A, 0x58);                        // pop edx; pop eax
    a.jmp(C.devfill);                         // jmp thunk_box_thick_devfill (RET 8 to the site)
    a.align(16);
    return { bytes: a.b, off: off, size: a.b.length };
  }
  return { build: build };
})();
// STUBS-END

if (requireBase()) {
  const SL = globalThis.SL;
  const G_SCALE = 0x668740;                 // g_popup_scale_num
  const A_SCREEN_W = 0x9B7B1C, A_SCREEN_H = 0x9B7B20;
  const A_SD_NUM = 0x696D18, A_SD_DEN = 0x696D1C;
  const A_TECH_PICK = 0x5BEB70, A_TW_CELL = 0x4863F0;
  const A_SD_MONO2 = 0x5E3E50, A_WRITE_STRINGS = 0x5DB040, A_WRAP_CENT4 = 0x5DD920;
  const BOX_SPRITE = 0x5E2DD3, FONT_INIT = 0x618F40, FIND_FONT = 0x5882F0;
  const A_FONT_NAME = 0x691B2C;             // g_hud_font_name (char**)
  const PCAVE2 = 0xA0C000;
  const T_DEVFILL = PCAVE2 + 0x42A0;        // thunk_box_thick_devfill

  let g = 16;
  const s = (v) => SL.scalePx(v, g);
  const fs = (v) => SL.techFontSize(v, g);

  // ---------------------------------------------------------------------------
  // Immediate patch table: [va, originalInsnBytes, immOffset, width, valueFn, label]
  // (bytes from the pristine .bak disasm, work\_tech_dis_*.txt; widths 1 = imm8/disp8)
  // v2: the Font_init/find_font size imms and the 0x48646C inset are NOT in this table any
  // more (stubs); 0x487DBD carries the one-cascade strip law.
  // ---------------------------------------------------------------------------
  const P = [
    // --- TechWin_exec 0x486510: pad, layout law, chrome ---
    [0x487358, "BF 0A 00 00 00", 1, 4, () => s(10), "edi=10: pad [+0xA1C] (n>8 body font share cut at 0x487981)"],
    [0x487C96, "83 E8 14", 2, 1, () => s(0x14), "cw = SW/cols - 20 (n<=8)"],
    [0x487CA1, "8D 42 EC", 2, 1, () => -s(0x14), "cw = (SW-20)/cols (n>8)"],
    [0x487D0C, "83 C2 1D", 2, 1, () => s(0x1D), "overflow test ch*rows + 0x1D > SH"],
    [0x487D1C, "83 E8 28", 2, 1, () => s(0x28), "ch = SH/rows - 40 (n<=8)"],
    [0x487D21, "83 C0 BB", 2, 1, () => -s(0x45), "ch = (SH-69)/rows (n>8)"],
    [0x487D48, "83 C0 1E", 2, 1, () => s(0x1E), "H = (ch+1)*rows + 0x1E"],
    [0x487D6C, "C7 83 6C 01 00 00 1D 00 00 00", 6, 4, () => s(0x1D), "[+0x16C] caption size"],
    [0x487DA6, "B9 03 00 00 00", 1, 4, () => s(3), "caption strip inset 3"],
    [0x487DBD, "83 C0 17", 2, 1, () => SL.techStripHImm(g), "caption strip height -> s(26)-s(3) (one cascade)"],
    [0x487DDC, "B8 03 00 00 00", 1, 4, () => s(3), "caption text inset 3"],
    // --- TechWin_draw_cell 0x4863F0 ---
    [0x48644F, "83 C0 1E", 2, 1, () => s(0x1E), "T = row*(ch+1) + 0x1E"],
    [0x48648B, "83 C0 FD", 2, 1, () => -s(3), "R clamp canvasW - 3"],
    [0x486498, "B8 1D 00 00 00", 1, 4, () => s(0x1D), "T clamp 0x1D"],
    [0x4864AD, "B8 FD FF FF FF", 1, 4, () => -s(3), "B clamp -3 - canvasH"],
    // --- on_mouse_move 0x485FC0 ---
    [0x485FCD, "83 E8 1D", 2, 1, () => s(0x1D), "hit-test y -= 0x1D"],
    // --- draw_cell_content 0x484C60 ---
    [0x484E48, "83 E9 02", 2, 1, () => s(2), "name overflow test W-2"],
    [0x484E7E, "83 E9 02", 2, 1, () => s(2), "name overflow test W-2 b"],
    [0x484EC3, "83 EA 02", 2, 1, () => s(2), "name overflow loop W-2"],
    [0x484F54, "83 EA 04", 2, 1, () => s(4), "name(n>8) measure W-4"],
    [0x484F76, "83 EA 04", 2, 1, () => s(4), "name(n>8) wrap W-4"],
    [0x484F8E, "83 C1 02", 2, 1, () => s(2), "name(n>8) x+2"],
    [0x484FAE, "83 E9 06", 2, 1, () => s(6), "name wrap W-6"],
    [0x484FB2, "83 C0 02", 2, 1, () => s(2), "name x+2"],
    [0x48507A, "83 E9 02", 2, 1, () => s(2), "category wrap W-2"],
    [0x4850DD, "3D B4 00 00 00", 1, 4, () => s(0xB4), "icon class threshold 0xB4"],
    [0x4850ED, "3D 8C 00 00 00", 1, 4, () => s(0x8C), "icon class threshold 0x8C"],
    [0x4850E4, "BB F6 FF FF FF", 1, 4, () => SL.techIconImms(g).s10, "icon s=-10 literal -> 6g-16"],
    [0x4850F6, "83 E3 02", 2, 1, () => SL.techIconImms(g).mask, "icon and ebx,2 -> 2g"],
    [0x4850F9, "83 C3 F2", 2, 1, () => SL.techIconImms(g).add, "icon add ebx,-14 -> 2g-16"],
    [0x485140, "C7 05 1C 6D 69 00 10 00 00 00", 6, 4, () => SL.techIconImms(g).den, "SCALE_DEN_G 16 -> 256"],
    [0x485183, "C1 F8 04", 2, 1, () => SL.techIconImms(g).shift, "iconW sar 4 -> 8 (pre-blit)"],
    [0x485213, "C1 F8 04", 2, 1, () => SL.techIconImms(g).shift, "iconW sar 4 -> 8 (advance)"],
    [0x4853E6, "83 E9 08", 2, 1, () => s(8), "quote wrap W-8"],
    [0x4853E9, "83 C0 04", 2, 1, () => s(4), "quote x+4"],
    // --- write_unlock_line 0x484B80 ---
    [0x484C1F, "83 E8 02", 2, 1, () => s(2), "unlock measure W-2"],
    [0x484C47, "83 E9 02", 2, 1, () => s(2), "unlock wrap W-2"],
  ];
  // cuts: [va, originalBytes, stubKey, label] -> E8 stub + NOP fill
  const CUTS = [
    [0x48646C, "B8 03 00 00 00 2B D8 2B D0 3B C8", "inset", "draw_cell R/B -= c_rb; L clamp s(3)"],
    [0x487981, "8B F7 C7 45 08 0C 00 00 00", "n8", "n>8: esi = 10 (native body font), [ebp+8] = 12"],
  ];
  // call-target redirects: [va, expectedTarget, newTargetKey, label]
  const FONT_INIT_SITES = [0x487999, 0x4879AE, 0x4879C2, 0x4879DA];
  const FIND_FONT_SITES = [0x484D4F, 0x484D5C, 0x484D6D, 0x484D7A, 0x484D8E, 0x484D9B, 0x484DA8, 0x487E3A];
  const FRAME_SITES = [[0x487D9E, "devfill", "d690 backdrop -> devfill"],
                       [0x487DD1, "rb1", "d618 caption strip -> devfill(R-1,B-1)"],
                       [0x4864D8, "rb1", "d528/d578 cell frame -> devfill(R-1,B-1)"]];
  // fonts the window requests (native size, Font_init flags) and (native size, pool variant)
  const FI_COMBOS = [[14, 0], [14, 1], [14, 2], [18, 1], [10, 0], [10, 1], [10, 2], [12, 1]];
  const FF_COMBOS = [[20, 1], [20, 2], [18, 1], [18, 2], [12, 1], [12, 2]];

  const hexOf = (p, n) => Array.from(new Uint8Array(p.readByteArray(n))).map(b => b.toString(16).padStart(2, "0").toUpperCase()).join(" ");
  const callTarget = (va) => { const b = new Uint8Array(VA(va).readByteArray(5)); return b[0] !== 0xE8 ? -1 : ((va + 5 + ((b[1] | (b[2] << 8) | (b[3] << 16) | (b[4] << 24)) | 0)) >>> 0); };
  const keep = [];                          // Frida allocations that must outlive this scope
  globalThis._techKeep = keep;
  const zalloc = (n) => { const p = Memory.alloc(n); p.writeByteArray(new Array(n).fill(0)); keep.push(p); return p; };  // heap allocs are NOT zeroed

  // ---------------------------------------------------------------------------
  // Font calibration (cell law) — runs once, before the window builds
  // ---------------------------------------------------------------------------
  const FontInit = new NativeFunction(VA(FONT_INIT), "int", ["pointer", "pointer", "int", "int"], "thiscall");
  const FindFont = new NativeFunction(VA(FIND_FONT), "pointer", ["int", "int"], "mscdecl");
  let GetObjectA = null, GetObjectType = null;
  try {
    const gdi = Process.getModuleByName("gdi32.dll");
    GetObjectA = new NativeFunction(gdi.getExportByName("GetObjectA"), "int", ["pointer", "int", "pointer"], "stdcall");
    GetObjectType = new NativeFunction(gdi.getExportByName("GetObjectType"), "uint", ["pointer"], "stdcall");
  } catch (e) { log("gdi32 exports unavailable: " + e); }
  const lfBuf = zalloc(64);
  function logfont(font) {                  // LOGFONTA of the HFONT held by a Font object (slot scanned)
    if (!GetObjectA) return null;
    for (let k = 0; k < 10; k++) {
      const h = font.add(k * 4).readPointer();
      if (h.isNull() || h.equals(ptr("0xffffffff"))) continue;
      let ty = 0; try { ty = GetObjectType(h); } catch (e) { continue; }
      if (ty !== 6) continue;               // OBJ_FONT
      if (GetObjectA(h, 60, lfBuf) <= 0) continue;
      // lfFaceName is a 32-byte buffer with stale bytes after the NUL: cut at the NUL (readCString(n) returns
      // all n bytes -> a 69-byte UTF-8 string -> Font_init's strcpy into its stack LOGFONT smashed its own frame)
      const fb = new Uint8Array(lfBuf.add(28).readByteArray(32));
      let fn = fb.indexOf(0); if (fn < 0) fn = 32;
      let face = ""; for (let i = 0; i < fn; i++) face += String.fromCharCode(fb[i]);
      return { slot: k, height: lfBuf.readS32(), weight: lfBuf.add(16).readS32(), italic: lfBuf.add(20).readU8(), face: face };
    }
    return null;
  }
  const lfStr = (l) => (l ? " lf{h " + l.height + " w " + l.weight + " i " + l.italic + " " + l.face + " @" + l.slot + "}" : " lf{?}");
  const scratch = zalloc(0x28);            // zeroed once; Font_init re-inits release the HFONT (flags bit0 = 0)
  const fontName = VA(A_FONT_NAME).readPointer();   // g_hud_font_name = "Arial" (the window's own Font_init face)
  const calibrated = {};                    // "face:S:flags" -> {ptr, N, cell, cap, c0, target}
  // Calibrate ONE font: face string ptr `name`, native size S (the metric source is the font itself unless
  // `nativeCell` is given = the pool font's own cell), Font_init style `f`.  Target cell = fl(c0*g/16);
  // nominal = the first n >= start whose cell reaches it; a dedicated zeroed Font object is Font_init'd at n.
  function calib(name, faceTag, S, f, nativeCell) {
    const key = faceTag + ":" + S + ":" + f;
    if (calibrated[key]) return calibrated[key];
    FontInit(scratch, name, S, f);
    const c0 = (nativeCell > 0) ? nativeCell : scratch.add(0xC).readS32(), cap0 = scratch.add(0x10).readS32();
    const target = SL.techFontCell(c0, g);
    const start = Math.max(S, fs(S) - 8), stop = fs(S) + 16;
    let N = -1, tried = [];
    for (let n = start; n <= stop; n++) {
      FontInit(scratch, name, n, f);
      const c = scratch.add(0xC).readS32();
      tried.push(n + ":" + c);
      if (c >= target) { N = n; break; }
    }
    if (N < 0) { N = fs(S); log("FONT CALIB WARN " + key + ": no nominal in [" + start + "," + stop + "] reaches cell " + target + " (" + tried.join(" ") + ") -> nominal " + N); }
    const obj = zalloc(0x28);
    FontInit(obj, name, N, f);
    const r = { ptr: obj, N: N, c0: c0, cap0: cap0, target: target, cell: obj.add(0xC).readS32(), cap: obj.add(0x10).readS32() };
    calibrated[key] = r;
    log("font calib " + key + ": native cell " + c0 + " cap " + cap0 + " -> target cell " + target +
        " ; nominal " + N + " cell " + r.cell + " cap " + r.cap + lfStr(logfont(obj)) + "  [" + tried.join(" ") + "]");
    return r;
  }
  const faceStrs = {};
  function faceStr(face) {                  // a C string for a face name (kept alive)
    if (!faceStrs[face]) { faceStrs[face] = Memory.allocUtf8String(face); keep.push(faceStrs[face]); }
    return faceStrs[face];
  }
  // The pool font find_font(S, v): its face, cell and the Font_init style flags that reproduce it
  function poolFont(S, v) {
    const pool = FindFont(S, v);
    const cell = pool.add(0xC).readS32();
    const lp = logfont(pool);
    if (!lp) { log("pool find_font(" + S + "," + v + ") LOGFONT unreadable -> hud face, precedent map"); return { name: fontName, face: "hud", flags: v === 2 ? 3 : 1, cell: cell }; }
    if (!/^[ -~]{1,31}$/.test(lp.face)) { log("pool find_font(" + S + "," + v + ") face not printable ASCII (" + JSON.stringify(lp.face) + ") -> hud face, precedent map"); return { name: fontName, face: "hud", flags: v === 2 ? 3 : 1, cell: cell }; }
    const name = faceStr(lp.face);
    for (const f of [0, 1, 2, 3]) {
      FontInit(scratch, name, S, f);
      const ls = logfont(scratch);
      if (ls && ls.weight === lp.weight && ls.italic === lp.italic && ls.height === lp.height) {
        log("pool find_font(" + S + "," + v + ") = Font_init(face " + lp.face + ", " + S + ", flags " + f + ")" + lfStr(lp) + " pool cell " + cell + " (scratch cell " + scratch.add(0xC).readS32() + ")");
        return { name: name, face: lp.face, flags: f, cell: cell };
      }
    }
    log("pool find_font(" + S + "," + v + ") no flags match" + lfStr(lp) + " -> precedent map");
    return { name: name, face: lp.face, flags: v === 2 ? 3 : 1, cell: cell };
  }

  // ---------------------------------------------------------------------------
  // Patching (once per process, g > 16)
  // ---------------------------------------------------------------------------
  let patched = false;
  function applyPatches() {
    if (patched) return;
    patched = true;
    // 1. fonts
    const fi = FI_COMBOS.map(([S, f]) => { const r = calib(fontName, "hud", S, f, 0); return [S, f, r.N]; });
    const ff = FF_COMBOS.map(([S, v]) => {
      let pf;
      try { pf = poolFont(S, v); } catch (e) { log("poolFont(" + S + "," + v + ") EXCEPTION " + e + " -> hud face, precedent map"); pf = { name: fontName, face: "hud", flags: v === 2 ? 3 : 1, cell: 0 }; }
      const r = calib(pf.name, pf.face, S, pf.flags, pf.cell);
      return [S, v, r.ptr.toUInt32()];
    });
    // 2. stubs
    const page = Memory.alloc(4096); keep.push(page);
    const rbRect = zalloc(16);
    const C = { cRb: SL.techCellInsetRb(g), cL: s(3), fontInit: VA(FONT_INIT).toUInt32(), findFont: VA(FIND_FONT).toUInt32(),
                devfill: VA(T_DEVFILL).toUInt32(), rbRect: rbRect.toUInt32(), fi: fi, ff: ff };
    const built = TechStubs.build(page.toUInt32(), C);
    page.writeByteArray(built.bytes);
    Memory.protect(page, 4096, "rwx");
    const stub = {}; for (const k in built.off) stub[k] = page.toUInt32() + built.off[k];
    stub.devfill = VA(T_DEVFILL).toUInt32();
    log("stubs @" + page + " size " + built.size + " offs " + JSON.stringify(built.off) + " consts cRb=" + C.cRb + " cL=" + C.cL);
    // 3. immediates
    let n = 0, skip = 0;
    for (const [va, orig, off, w, fn, label] of P) {
      const len = orig.split(" ").length;
      const live = hexOf(VA(va), len);
      if (live !== orig) { skip++; log("PATCH SKIP @0x" + va.toString(16) + " " + label + ": live " + live + " != " + orig); continue; }
      const v = fn();
      if (w === 1 && (v > 127 || v < -128)) { skip++; log("PATCH SKIP imm8 overflow @0x" + va.toString(16) + " " + label + " -> " + v); continue; }
      Memory.patchCode(VA(va), len, code => { if (w === 1) code.add(off).writeS8(v); else code.add(off).writeS32(v); });
      n++;
    }
    log("imm patches applied: " + n + "/" + P.length + (skip ? " (SKIPPED " + skip + ")" : ""));
    // 4. cuts
    for (const [va, orig, key, label] of CUTS) {
      const len = orig.split(" ").length;
      const live = hexOf(VA(va), len);
      if (live !== orig) { log("CUT SKIP @0x" + va.toString(16) + " " + label + ": live " + live); continue; }
      const rel = (stub[key] - (va + 5)) | 0;
      const bytes = [0xE8, rel & 0xFF, (rel >> 8) & 0xFF, (rel >> 16) & 0xFF, (rel >> 24) & 0xFF];
      while (bytes.length < len) bytes.push(0x90);
      Memory.patchCode(VA(va), len, code => { code.writeByteArray(bytes); });
      log("cut @0x" + va.toString(16) + " -> stub_" + key + " 0x" + stub[key].toString(16) + " (" + label + ")");
    }
    // 5. call redirects
    function redirect(va, expect, target, label) {
      const t = callTarget(va);
      if (t !== VA(expect).toUInt32()) { log("REDIRECT SKIP @0x" + va.toString(16) + " " + label + ": " + hexOf(VA(va), 5) + " -> 0x" + t.toString(16)); return 0; }
      Memory.patchCode(VA(va), 5, code => { code.add(1).writeS32((target - (va + 5)) | 0); });
      return 1;
    }
    let r = 0;
    for (const va of FONT_INIT_SITES) r += redirect(va, FONT_INIT, stub.fi, "Font_init -> stub_fi");
    log("Font_init sites -> stub_fi: " + r + "/" + FONT_INIT_SITES.length + " table " + JSON.stringify(fi));
    r = 0;
    for (const va of FIND_FONT_SITES) r += redirect(va, FIND_FONT, stub.ff, "find_font -> stub_ff");
    log("find_font sites -> stub_ff: " + r + "/" + FIND_FONT_SITES.length + " table " + JSON.stringify(ff.map(e => [e[0], e[1], "0x" + e[2].toString(16)])));
    r = 0;
    for (const [va, key, label] of FRAME_SITES) r += redirect(va, BOX_SPRITE, stub[key], label);
    log("frame sites: " + r + "/" + FRAME_SITES.length + " (devfill 0x" + stub.devfill.toString(16) + ", rb1 0x" + stub.rb1.toString(16) + " rect scratch " + rbRect + ")");
    log("laws @g=" + g + ": pad " + s(10) + " caption " + s(0x1D) + " gridTop " + s(0x1E) + " inset3 " + s(3) + " cRb " + C.cRb +
        " stripImm " + SL.techStripHImm(g) + " channels " + JSON.stringify(SL.techChannels(g)) + " icon imms " + JSON.stringify(SL.techIconImms(g)));
  }

  // ---------------------------------------------------------------------------
  // Verification hooks (entries only, log-only)
  // ---------------------------------------------------------------------------
  const rd4 = (p) => [p.readS32(), p.add(4).readS32(), p.add(8).readS32(), p.add(12).readS32()];
  const rstr = (r) => "(" + r.join(",") + ")[" + (r[2] - r[0]) + "x" + (r[3] - r[1]) + "]";
  const eq4 = (a, b) => a.length === 4 && a.every((v, i) => v === b[i]);
  let opens = 0, cellLogs = 0, iconLogs = 0, quoteLogs = 0, readbacks = 0, wrapLogs = {};
  let lay = null, sw = 0, sh = 0;

  // canvas read-back: the TechWin Buffer at +0x444 (w +0x80, h +0x84 negative, data +0x54, stride +0x4A8)
  function canvasOf(tw) {
    const cv = tw.add(0x444);
    const w = cv.add(0x80).readS32(), h = -cv.add(0x84).readS32(), stride = cv.add(0x4A8).readS32();
    const data = cv.add(0x54).readPointer();
    if (data.isNull() || w <= 0 || h <= 0 || stride < w) return null;
    return { w: w, h: h, stride: stride, data: data };
  }
  function rowBytes(cv, y, x0, x1, mark) {   // bytes x0..x1 (incl) of row y, '|' before column `mark`
    if (y < 0 || y >= cv.h) return "y out";
    let out = "";
    for (let x = Math.max(0, x0); x <= Math.min(cv.w - 1, x1); x++) out += (x === mark ? "|" : " ") + cv.data.add(y * cv.stride + x).readU8().toString(16).padStart(2, "0");
    return out.trim();
  }
  function colBytes(cv, x, y0, y1, mark) {
    if (x < 0 || x >= cv.w) return "x out";
    let out = "";
    for (let y = Math.max(0, y0); y <= Math.min(cv.h - 1, y1); y++) out += (y === mark ? "|" : " ") + cv.data.add(y * cv.stride + x).readU8().toString(16).padStart(2, "0");
    return out.trim();
  }

  Interceptor.attach(VA(A_TECH_PICK), {
    onEnter() {
      g = VA(G_SCALE).readS32();
      sw = VA(A_SCREEN_W).readS32(); sh = VA(A_SCREEN_H).readS32();
      opens++; cellLogs = 0; iconLogs = 0; quoteLogs = 0; readbacks = 0; wrapLogs = {}; lay = null;
      if (g > 16) { try { applyPatches(); } catch (e) { log("applyPatches EXCEPTION: " + e + "\n" + (e.stack || "")); } }
      const sp = this.context.esp;
      log("==== tech_pick ENTER #" + opens + " " + new Date().toISOString() + " faction=" + sp.add(4).readS32() +
          " flag=" + sp.add(8).readS32() + " ScreenW=" + sw + " ScreenH=" + sh + " g=" + g +
          (g <= 16 ? " -> NATIVE NO-OP" : " (patched)") + " ====");
    },
    onLeave(rv) { log("==== tech_pick LEAVE #" + opens + " pick=" + rv.toInt32() + " ===="); }
  });

  Interceptor.attach(VA(A_TW_CELL), {
    onEnter() {
      const tw = this.context.ecx, sp = this.context.esp;
      const idx = sp.add(4).readS32(), hil = sp.add(8).readS32();
      const n = tw.add(0xA2C).readS32();
      if (idx >= n) return;
      if (cellLogs >= 12) return;
      cellLogs++;
      try {
        const F = ["cw", 0xA14, "ch", 0xA18, "pad", 0xA1C, "cols", 0xA24, "rows", 0xA28, "n", 0xA2C, "hover", 0xA38];
        let fields = "";
        for (let i = 0; i < F.length; i += 2) fields += " " + F[i] + "=" + tw.add(F[i + 1]).readS32();
        const scr = rd4(tw.add(0x13C)), loc = rd4(tw.add(0x474));
        const cap = tw.add(0x16C).readS32();
        const cvW = tw.add(0x4C4).readS32(), cvH = tw.add(0x4C8).readS32();
        if (!lay) {
          lay = SL.techLayout(sw, sh, n, g);
          const okL = lay.cw === tw.add(0xA14).readS32() && lay.ch === tw.add(0xA18).readS32() &&
                      lay.cols === tw.add(0xA24).readS32() && lay.rows === tw.add(0xA28).readS32() &&
                      lay.pad === tw.add(0xA1C).readS32() && lay.caption === cap &&
                      eq4(loc, [0, 0, lay.W, lay.H]) && scr[0] === lay.x && scr[1] === lay.y;
          log("TECHWIN first cell:" + fields + " caption=" + cap + " screen=" + rstr(scr) + " local=" + rstr(loc) +
              " canvas=" + cvW + "x" + cvH);
          log("  LAW techLayout(" + sw + "," + sh + "," + n + "," + g + ") = " + JSON.stringify(lay) + " -> " + (okL ? "MATCH" : "MISMATCH"));
          const cr = SL.techCaptionRects(lay, g);
          log("  LAW caption strip " + rstr(cr.strip) + " text " + rstr(cr.text) + " channels " + JSON.stringify(SL.techChannels(g)));
          for (let i = 0; i < 4; i++) {
            const f = tw.add(0xBBC + i * 0x28);
            log("  F" + i + " dw[" + [0, 1, 2, 3, 4, 5, 6, 7].map(k => f.add(k * 4).readS32()).join(",") + "] cell " + f.add(0xC).readS32() +
                " cap " + f.add(0x10).readS32() + (g > 16 ? " (targets cell fl(native*g/16))" : "") + lfStr(logfont(f)));
          }
          // read-back of the chrome drawn BEFORE the cells: strip bottom/right, window right/bottom
          const cv = canvasOf(tw);
          if (cv) {
            const st = cr.strip, s3 = s(3);
            log("  READBACK strip bottom x=" + ((st[0] + st[2]) >> 1) + " rows " + (st[3] - 6) + ".." + (st[3] + 4) + " |=B: " + colBytes(cv, (st[0] + st[2]) >> 1, st[3] - 6, st[3] + 4, st[3]));
            log("  READBACK strip right y=" + ((st[1] + st[3]) >> 1) + " cols " + (st[2] - 6) + ".." + (st[2] + 4) + " |=R: " + rowBytes(cv, (st[1] + st[3]) >> 1, st[2] - 6, st[2] + 4, st[2]));
            log("  READBACK strip top-left y=" + st[1] + " cols 0.." + (st[0] + 6) + " |=L: " + rowBytes(cv, st[1] + 10, 0, st[0] + 6, st[0]) + "  rows 0.." + (st[1] + 6) + " |=T: " + colBytes(cv, st[0] + 10, 0, st[1] + 6, st[1]));
            log("  READBACK window right y=" + (lay.H >> 1) + " cols " + (lay.W - 8) + ".." + (lay.W - 1) + ": " + rowBytes(cv, lay.H >> 1, lay.W - 8, lay.W - 1, -1) +
                " ; bottom x=" + (lay.W >> 1) + " rows " + (lay.H - 8) + ".." + (lay.H - 1) + ": " + colBytes(cv, lay.W >> 1, lay.H - 8, lay.H - 1, -1) + " (s3=" + s3 + ")");
          }
        }
        const want = SL.techCellRect(idx, lay, g);
        this.want = want; this.idx = idx; this.hil = hil; this.tw = tw;
      } catch (e) { log("cell log err " + e); }
    },
    onLeave() {
      if (!this.want) return;
      const w = this.want;
      log("cell idx=" + this.idx + " hilite=" + this.hil + " LAW rect " + rstr(w) +
          " cur_L/W/bottom/y=" + [0xA40, 0xA48, 0xA44, 0xA50].map(o => this.tw.add(o).readS32()).join("/") +
          " line_h=" + this.tw.add(0xA4C).readS32());
      if (readbacks < 6) {
        readbacks++;
        const cv = canvasOf(this.tw);
        if (cv) {
          const my = (w[1] + w[3]) >> 1, mx = (w[0] + w[2]) >> 1;
          log("  READBACK idx=" + this.idx + " right y=" + my + " cols " + (w[2] - 6) + ".." + (w[2] + 4) + " |=R: " + rowBytes(cv, my, w[2] - 6, w[2] + 4, w[2]) +
              " ; left cols " + (w[0] - 4) + ".." + (w[0] + 4) + " |=L: " + rowBytes(cv, my, w[0] - 4, w[0] + 4, w[0]));
          log("  READBACK idx=" + this.idx + " bottom x=" + mx + " rows " + (w[3] - 6) + ".." + (w[3] + 4) + " |=B: " + colBytes(cv, mx, w[3] - 6, w[3] + 4, w[3]) +
              " ; top rows " + (w[1] - 4) + ".." + (w[1] + 4) + " |=T: " + colBytes(cv, mx, w[1] - 4, w[1] + 4, w[1]));
        }
      }
    }
  });

  // icon blit: Sprite_draw_mono_2(this=Sprite*; dest, key, x, y, color) from 0x4851D9
  Interceptor.attach(VA(A_SD_MONO2), {
    onEnter() {
      if (!this.returnAddress.equals(VA(0x4851DE)) || iconLogs >= 8 || !lay) return;
      iconLogs++;
      const sp = this.context.esp;
      const x = sp.add(0xC).readS32(), y = sp.add(0x10).readS32();
      const num = VA(A_SD_NUM).readS32(), den = VA(A_SD_DEN).readS32();
      const sc = SL.techIconClass(lay.cw, g), r = SL.techIconRatio(sc, g), iw = SL.techIconW(sc, g);
      log("icon blit x=" + x + " y=" + y + " num/den=" + num + "/" + den + " | LAW class " + sc + " ratio " + r[0] + "/" + r[1] +
          " iconW " + iw + " -> " + ((num === r[0] && den === r[1]) ? "MATCH" : "MISMATCH") +
          " expected x = L + (cur_W - " + iw + ")/2");
    }
  });

  // quote: Buffer_write_strings(list, x, y, w, 0) from 0x4853F5
  Interceptor.attach(VA(A_WRITE_STRINGS), {
    onEnter() {
      if (!this.returnAddress.equals(VA(0x4853FA)) || quoteLogs >= 4) return;
      quoteLogs++;
      const sp = this.context.esp;
      this.q = [sp.add(8).readS32(), sp.add(0xC).readS32(), sp.add(0x10).readS32()];
    },
    onLeave(rv) {
      if (this.q) log("quote write_strings x=" + this.q[0] + " y=" + this.q[1] + " w=" + this.q[2] + " -> bottom " + rv.toInt32() +
                      " | LAW x = L+" + s(4) + ", w = W-" + s(8));
    }
  });

  // name / category / unlock lines: Buffer_wrap_cent_4(str, x, y, w)
  const WRAP_SITES = { 0x484FC5: "name", 0x48508D: "category", 0x484C56: "unlock" };
  Interceptor.attach(VA(A_WRAP_CENT4), {
    onEnter() {
      const ra = this.returnAddress;
      for (const k in WRAP_SITES) {
        if (!ra.equals(VA(Number(k)))) continue;
        const name = WRAP_SITES[k];
        wrapLogs[name] = (wrapLogs[name] || 0) + 1;
        if (wrapLogs[name] > 3) return;
        const sp = this.context.esp;
        let str = "?"; try { str = JSON.stringify(sp.add(4).readPointer().readCString(32)); } catch (e) {}
        this.tag = name + " x=" + sp.add(8).readS32() + " y=" + sp.add(0xC).readS32() + " w=" + sp.add(0x10).readS32() + " " + str;
        return;
      }
    },
    onLeave(rv) { if (this.tag) log("wrap_cent_4 " + this.tag + " -> y' " + rv.toInt32()); }
  });

  log("attached: tech_pick 0x5beb70 (patches), draw_cell 0x4863f0, sd_mono2 0x5e3e50, write_strings 0x5db040, wrap_cent_4 0x5dd920; " +
      P.length + " imm sites + " + CUTS.length + " cuts + " + FONT_INIT_SITES.length + " Font_init + " + FIND_FONT_SITES.length +
      " find_font + " + FRAME_SITES.length + " frame sites");
}
