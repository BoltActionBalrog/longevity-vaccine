// PROBE (no writes): what face / size / weight is the engine's DEFAULT FlatButton label font?
//
// Background (font audit 2026-09-13, work\FONT_FACE_WEIGHT_AUDIT.md s1 "second engine fact"): the static
// trace says the BaseButton default label font [0x9B8E34] is the static Font 0x7D3948, Font_init'd
// "Times New Roman", 12, style 0 at 0x6195F5..0x619600.  Audit findings 4-8 (COUNCIL/MP-time, Preferences,
// scenario diplo, TutWin TOUR/Close, HUD M/I button labels) rest on that trace.
//
// v2 (2026-09-17): v1 attached inside Font_init at the baked detour's resume address 0x618F45 and the game
// crashed at boot (AV in ListBox init 0x5FA992 after the first Font_inits) -- attach placement hazard, see
// memory feedback-frida-attach-branch-target.  v1's partial log already showed the static Font being inited
// "Times New Roman" 12 regular and then RE-inited "Arial" 12 regular during startup.  v2 touches NO engine
// code: only the gdi32 import.
//   (1) gdi32!CreateFontIndirectA: every LOGFONT the engine creates (face, height, weight, italic).  When the
//       return address is Font_init's call site 0x619049, ESI holds Font_init's `this` (mov [esi+8],eax follows),
//       so every line names the Font object being initialised; the static 0x7D3948 is flagged.
//   (2) after 8 / 30 / 90 s: [0x9B8E34] -> Font -> +8 HFONT -> GetObjectA(LOGFONTA) = the LIVE default button
//       font, plus a few known FlatButtons' +0x970 (PrefWin #0, COUNCIL, MP-time, HUD M/I) once they exist.
//
// Run at 1024x768 so every scaled-font lever is a native no-op (g = 16):
//   work\run-frida-at-res.bat hook_btnfont_probe.js 1024 768   (the desktop "SMACX Frida Trace 1024x768" shortcut)
//   %resume, let the main menu come up, open Preferences once before the 30 s mark, then quit.
//   Read D:/SmacxUi/work/frida_btnfont_probe.log: the "DEFAULT BUTTON FONT" lines are the answer.
"use strict";

globalThis.LOG_PATH = "D:/SmacxUi/work/frida_btnfont_probe.log";
(function () {
  let f = null;
  globalThis.log = function (msg) {
    if (f === null) f = new File(globalThis.LOG_PATH, "w");
    const line = "" + msg; console.log(line); f.write(line + "\n"); f.flush();
  };
})();
log("=== hook_btnfont_probe.js v2 @ " + new Date().toISOString() + " ===");
installAVHandler("btnfont_probe");

if (requireBase()) {
  const DEFAULT_FONT_PTR = ptr(0x9B8E34);      // BaseButton default label Font* (g_default_button_font)
  const STATIC_FONT = 0x7D3948;                // the static Font the trace says it points at
  const FONT_INIT_CFI_RET = 0x619049;          // Font_init: the instruction after `call [CreateFontIndirectA]`; esi = this
  const gdi = Process.getModuleByName("gdi32.dll");
  const GetObjectA = new NativeFunction(gdi.getExportByName("GetObjectA"), "int", ["pointer", "int", "pointer"], "stdcall");
  const CreateFontIndirectA = gdi.getExportByName("CreateFontIndirectA");
  let n = 0;

  function lfText(lf) {   // LOGFONTA: lfHeight i32 @0, lfWeight i32 @16, lfItalic u8 @20, lfFaceName char[32] @28
    const h = lf.readS32(), w = lf.add(16).readS32(), it = lf.add(20).readU8();
    let face = "?";
    try { face = lf.add(28).readCString(); } catch (e) {}      // no length arg: stops at the NUL (readCString(n) returns ALL n bytes)
    return `face="${face}" height=${h} weight=${w}${w >= 700 ? " (BOLD)" : " (regular)"} italic=${it}`;
  }
  function fontText(fontPtr) {
    try {
      const hf = fontPtr.add(8).readPointer();
      if (hf.isNull()) return "HFONT null";
      const lf = Memory.alloc(64);
      const got = GetObjectA(hf, 60, lf);
      return got ? lfText(lf) : "GetObjectA failed";
    } catch (e) { return "unreadable: " + e; }
  }

  // (1) every LOGFONT the engine creates; Font_init's `this` from ESI when called from Font_init
  Interceptor.attach(CreateFontIndirectA, {
    onEnter(args) {
      this.txt = lfText(args[0]);
      const ra = this.returnAddress.toUInt32() >>> 0;
      let who = "caller ret=0x" + ra.toString(16);
      if (ra === FONT_INIT_CFI_RET) {
        const self = this.context.esi.toUInt32() >>> 0;
        who = "Font_init this=0x" + self.toString(16) + (self === STATIC_FONT ? "  <<< DEFAULT BUTTON FONT (static 0x7D3948)" : "");
      }
      this.who = who;
    },
    onLeave(ret) {
      log(`CreateFontIndirectA #${++n}: ${this.txt} -> hfont=${ret}  ${this.who}`);
    }
  });

  // (2) the live default font pointer + a few known FlatButtons' label fonts, after startup
  function report(tag) {
    try {
      const fp = DEFAULT_FONT_PTR.readPointer();
      log(`DEFAULT BUTTON FONT [0x9B8E34] = ${fp}${fp.toUInt32() === STATIC_FONT ? " (== static 0x7D3948)" : ""}: ${fontText(fp)}   [${tag}]`);
    } catch (e) { log("default font read failed: " + e); }
    const btns = [[0x858338, "PrefWin FlatButton #0"], [0x7FE80C, "COUNCIL button (MultiWin)"], [0x7FF358, "MP-time button (MultiWin)"],
                  [0x7AF620, "HUD M button"], [0x7B016C, "HUD I button"]];
    for (const [va, name] of btns) {
      try {
        const fp = ptr(va).add(0x970).readPointer();
        log(`  ${name} +0x970 = ${fp}: ${fp.isNull() ? "null" : fontText(fp)}   [${tag}]`);
      } catch (e) { log(`  ${name}: unreadable`); }
    }
  }
  setTimeout(() => report("8s after attach"), 8000);
  setTimeout(() => report("30s after attach"), 30000);
  setTimeout(() => report("90s after attach"), 90000);
  log("installed: CreateFontIndirectA tap only (no engine-code hooks); default-font reports at 8/30/90 s. Open Preferences once before the 30 s report.");
}
