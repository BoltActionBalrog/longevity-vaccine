"use strict";
// hook_scenedit_census.js — census trace for tonight's two targets:
//   (1) scenario-editor DIPLOMACY popup (unscaled modal box / list / bottom buttons)
//   (2) scenario-editor HUD middle panel (tile palette, brush buttons, info text)
// Logs every DISTINCT window creation, pcx load, and sprite-atlas extract with the
// STATIC caller VA so builder call sites fall out of one run.
// NO-ATTACH honored: Font_init 0x618F40 (entry is baked-detoured by Font_init.hud_fontobj),
// GraphicWin_init 0x5D4EF0 (SEH prologue, Frida-untouchable) — Win_init catches its work.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_scenedit_census.log";
log("=== hook_scenedit_census.js started ===");

if (requireBase()) {
  // runtime addr -> static VA string
  const SVA = p => "0x" + p.sub(TERRANX_BASE).add(0x400000).toString(16);
  const seen = new Set();
  const once = (key, msg) => { if (!seen.has(key)) { seen.add(key); log(msg); } };

  const logGlobals = tag => {
    try {
      log("[globals " + tag + "] ScreenWidth=" + VA(0x9b7b1c).readS32()
        + " scale_num[0x696D18]=" + VA(0x696D18).readS32()
        + " scale_den[0x696D1C]=" + VA(0x696D1C).readS32());
    } catch (e) { log("[globals " + tag + "] unreadable: " + e); }
  };
  setTimeout(() => logGlobals("t+8s"), 8000);

  // Win_init 0x5EBD80 — thiscall(self; x, y, w, h, flags, parent).
  // Every GraphicWin_init routes through here, so this is the one window-geometry census point.
  Interceptor.attach(VA(0x5EBD80), {
    onEnter() {
      const sp = this.context.esp, ret = SVA(this.returnAddress);
      const x = argS(sp, 1), y = argS(sp, 2), w = argS(sp, 3), h = argS(sp, 4);
      const flags = arg(sp, 5), parent = arg(sp, 6);
      once("wi|" + ret + "|" + x + "|" + y + "|" + w + "|" + h,
        "[Win_init] caller=" + ret + " self=" + this.context.ecx
        + " x=" + x + " y=" + y + " w=" + w + " h=" + h
        + " flags=0x" + flags.toString(16) + " parent=0x" + parent.toString(16));
    }
  });

  // Popup_start 0x406380 — cdecl(script name). Timeline marker for the diplo dialog.
  Interceptor.attach(VA(0x406380), {
    onEnter() {
      let name = "?";
      try { name = this.context.esp.add(4).readPointer().readCString(); } catch (e) {}
      log("[Popup_start] script=\"" + name + "\" caller=" + SVA(this.returnAddress));
      logGlobals("popup");
    }
  });

  // Buffer_load_pcx 0x5D7DE0 — thiscall(self; name, pal, a4, len). Finds the palette art.
  Interceptor.attach(VA(0x5D7DE0), {
    onEnter() {
      let name = "?";
      try { name = this.context.esp.add(4).readPointer().readCString(); } catch (e) {}
      const ret = SVA(this.returnAddress);
      once("px|" + ret + "|" + name,
        "[load_pcx] name=\"" + name + "\" caller=" + ret + " self=" + this.context.ecx);
    }
  });

  // Sprite_extract_2 0x5E39A0 — thiscall(self; src, a3, x, y, w, h, a8). Atlas literals.
  Interceptor.attach(VA(0x5E39A0), {
    onEnter() {
      const sp = this.context.esp, ret = SVA(this.returnAddress);
      const x = argS(sp, 3), y = argS(sp, 4), w = argS(sp, 5), h = argS(sp, 6);
      once("sx|" + ret + "|" + x + "|" + y + "|" + w + "|" + h,
        "[extract2] caller=" + ret + " atlas(x=" + x + " y=" + y + " w=" + w + " h=" + h + ")");
    }
  });

  // OptionList_attach 0x610540 — thiscall(self=Dialog+0xb14; parent, x, y, flags).
  // If the diplo checkbox column is an OptionList this logs its computed dims.
  Interceptor.attach(VA(0x610540), {
    onEnter() {
      const sp = this.context.esp;
      this.selfP = this.context.ecx;
      this.hdr = "[OptionList_attach] caller=" + SVA(this.returnAddress)
        + " x=" + argS(sp, 2) + " y=" + argS(sp, 3) + " flags=0x" + arg(sp, 4).toString(16);
    },
    onLeave() {
      let dims = "";
      try {
        const dlg = this.selfP.sub(0xb14);
        dims = " item_w[dlg+0x5c]=" + dlg.add(0x5c).readS32()
             + " area_h[dlg+0x60]=" + dlg.add(0x60).readS32()
             + " pitch[dlg+0x68]=" + dlg.add(0x68).readS32();
      } catch (e) { dims = " dims unreadable"; }
      log(this.hdr + dims);
    }
  });

  log("hooks installed: Win_init, Popup_start, Buffer_load_pcx, Sprite_extract_2, OptionList_attach");
}
