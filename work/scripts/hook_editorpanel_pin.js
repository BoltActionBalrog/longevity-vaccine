"use strict";
// hook_editorpanel_pin.js — pin the editor-HUD middle panel geometry + info-text font.
// Questions this answers (one run per resolution):
//   A. Ground-truth MainWin seed rects (+0xADC palette, +0xC6C red, +0xD4C/+0xD5C/+0xD6C
//      unions/info, +0xDA0 rcConsoleCenter) at g=40 vs g=25 — proves the scaled-anchor +
//      native-dims composition.
//   B. Which font is live when painter_editor_info (0x45B550) draws — via
//      Buffer_text_line_height retval + the actual write_l_3 coords inside the painter.
// NO-ATTACH honored: FlatButton_content_draw 0x607E50 entry (baked patch), 0x607E7F detour,
// Font_init 0x618F40, GraphicWin_init 0x5D4EF0.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_editorpanel_pin.log";
log("=== hook_editorpanel_pin.js started ===");

if (requireBase()) {
  const rect = p => "(" + p.readS32() + "," + p.add(4).readS32() + ","
    + p.add(8).readS32() + "," + p.add(12).readS32() + ")";
  let dumped = false;
  let inPainter = false;

  // MainWin_draw_center_mode 0x45BC50 — thiscall, ecx=MainWin_g. Dump seeds once in editor mode.
  Interceptor.attach(VA(0x45BC50), {
    onEnter() {
      const self = this.context.ecx;
      let mode = -1;
      try { mode = self.add(0x1E8FC).readS32(); } catch (e) {}
      if (mode !== 0x3EA || dumped) return;
      dumped = true;
      try {
        log("[center_mode] mode=0x3ea ScreenWidth=" + VA(0x9b7b1c).readS32());
        log("  rcConsoleCenter+0xDA0=" + rect(self.add(0xDA0)));
        log("  spriteCell dims +0x21E18/1C = " + self.add(0x21E18).readS32()
          + "x" + self.add(0x21E1C).readS32());
        for (let i = 0; i < 25; i++)
          log("  paletteSeed[" + i + "]=" + rect(self.add(0xADC + i * 16)));
        for (let i = 0; i < 6; i++)
          log("  brushSeed[" + i + "]=" + rect(self.add(0xC6C + i * 16)));
        log("  paletteUnion+0xD4C=" + rect(self.add(0xD4C)));
        log("  brushUnion+0xD5C=" + rect(self.add(0xD5C)));
        log("  editorInfoRect+0xD6C=" + rect(self.add(0xD6C)));
      } catch (e) { log("  dump failed: " + e); }
    }
  });

  // painter_editor_info 0x45B550 — bracket it so the two hooks below only log inside it.
  Interceptor.attach(VA(0x45B550), {
    onEnter() {
      inPainter = true;
      try {
        log("[info_painter] self=" + this.context.ecx
          + " rect+0xD6C=" + rect(this.context.ecx.add(0xD6C)));
      } catch (e) { log("[info_painter] enter (rect unreadable)"); }
    },
    onLeave() { inPainter = false; log("[info_painter] leave"); }
  });

  // Buffer_text_line_height 0x5DCAB0 — retval = live font line height (native ~13-16, scaled ~2.5x).
  Interceptor.attach(VA(0x5DCAB0), {
    onEnter() { this.take = inPainter; this.buf = this.context.ecx; },
    onLeave(retval) {
      if (this.take) log("  [line_height] buf=" + this.buf + " -> " + u32(retval));
    }
  });

  // Buffer_write_l_3 0x5DCEA0 — thiscall(self; str, x, y, len): the info lines' actual coords.
  Interceptor.attach(VA(0x5DCEA0), {
    onEnter() {
      if (!inPainter) return;
      const sp = this.context.esp;
      let s = "?";
      try { s = sp.add(4).readPointer().readCString(); } catch (e) {}
      log("  [write_l_3] \"" + s + "\" x=" + argS(sp, 2) + " y=" + argS(sp, 3));
    }
  });

  log("hooks installed: center_mode 0x45BC50, info_painter 0x45B550, line_height, write_l_3");
}
