"use strict";
// HUD geometry probe: which windows compose the bottom console strip, with what
// rects, at the current resolution. Census of Win_init/GraphicWin_init(_2) during
// startup + g_console_strip_height transitions + NC-redraw margin dump + NetMsg text.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_hudgeom.log";
log("=== hook_hudgeom.js started ===");
installAVHandler("hudgeom");

if (requireBase()) {
  const BASE = globalThis.TERRANX_BASE;
  const toStatic = p => "0x" + (p.sub(BASE).toUInt32() + 0x400000).toString(16);

  // known static window objects -> annotate `this`
  const OBJS = [
    ["MapWin(Console)", 0x9156B0, 0x939E58],
    ["MainWin",         0x7AE820, 0x7AF620],
    ["StatusWin",       0x8C5568, 0x8C6E68],
    ["TutWin",          0x8C6E68, 0x8C8000],
    ["MessageWin",      0x7F67F8, 0x7F9F58],
    ["NetMsg",          0x805338, 0x80A6F8],
    ["InfoWin",         0x7AD2A0, 0x7AE820],
    ["WorldWin",        0x8E9F60, 0x8EC000],
  ];
  function annot(thisP) {
    const s = thisP.sub(BASE).toUInt32() + 0x400000;
    for (const [n, lo, hi] of OBJS)
      if (s >= lo && s < hi) return n + "+0x" + (s - lo).toString(16);
    return "";
  }

  const gCH   = VA(0x7AF59C);   // g_console_strip_height
  const gSW   = VA(0x9B7B1C);   // ScreenWidth
  const gSH   = VA(0x9B7B20);   // ScreenHeight
  const gPS   = VA(0x668740);   // g_popup_scale_num
  const state = () => "[CH=" + gCH.readS32() + " SW=" + gSW.readS32() +
                      " SH=" + gSH.readS32() + " g=" + gPS.readS32() + "]";

  // --- 1. g_console_strip_height transition watch (poll) ---
  let lastCH = gCH.readS32();
  log("startup " + state());
  setInterval(() => {
    const v = gCH.readS32();
    if (v !== lastCH) { log("g_console_strip_height " + lastCH + " -> " + v); lastCH = v; }
  }, 200);

  // --- 2. window-init census ---
  const seen = new Set();
  function census(tag, thisP, x, y, w, h, nameP, ret) {
    const key = tag + "|" + toStatic(ret) + "|" + thisP + "|" + w + "x" + h;
    if (seen.has(key)) return;
    seen.add(key);
    let nm = "";
    try { if (!nameP.isNull()) nm = nameP.readUtf8String(24); } catch (e) {}
    log(tag + " this=" + toStatic(thisP) + (annot(thisP) ? " <" + annot(thisP) + ">" : "") +
        " x=" + x + " y=" + y + " w=" + w + " h=" + h +
        (nm ? " name='" + nm + "'" : "") + " ret=" + toStatic(ret) + " " + state());
  }
  // Win_init(this, x,y,w,h, name, a7, parent, menu, bs)
  Interceptor.attach(VA(0x5EBD80), {
    onEnter() {
      const sp = this.context.esp;
      census("Win_init", this.context.ecx, argS(sp, 1), argS(sp, 2), argS(sp, 3), argS(sp, 4),
             sp.add(5 * 4).readPointer(), this.returnAddress);
    }
  });
  // GraphicWin_init(this, x,y,w,h, name, a7, parent, menu, bs)
  Interceptor.attach(VA(0x5D4EF0), {
    onEnter() {
      const sp = this.context.esp;
      census("GraphicWin_init", this.context.ecx, argS(sp, 1), argS(sp, 2), argS(sp, 3), argS(sp, 4),
             sp.add(5 * 4).readPointer(), this.returnAddress);
    }
  });
  // GraphicWin_init_2(this, RECT*, name, a4, parent, menu, bs)
  Interceptor.attach(VA(0x5D50A0), {
    onEnter() {
      const sp = this.context.esp;
      const r = sp.add(4).readPointer();
      let x = 0, y = 0, w = 0, h = 0;
      try { x = r.readS32(); y = r.add(4).readS32(); w = r.add(8).readS32(); h = r.add(12).readS32(); } catch (e) {}
      census("GraphicWin_init_2", this.context.ecx, x, y, w, h,
             sp.add(2 * 4).readPointer(), this.returnAddress);
    }
  });

  // --- 3. HUD builder entry/exit markers (bracket the strip-height write) ---
  for (const [name, va] of [["Console_init", 0x51D890], ["MapWin_init", 0x470920],
                            ["MapWin_init_2", 0x470A90], ["StatusWin_init", 0x4B9FC0],
                            ["load_interface", 0x455610]]) {
    Interceptor.attach(VA(va), {
      onEnter() { log(">> " + name + " " + state()); },
      onLeave() { log("<< " + name + " " + state()); }
    });
  }

  // --- 4. NC redraw: dump the Win-base margin fields the strip draw reads ---
  let ncSeen = 0;
  Interceptor.attach(VA(0x50F960), {
    onEnter() {
      if (ncSeen++ >= 3) return;
      const sp = this.context.esp;
      const nc = sp.add(4).readPointer();
      const mode = argS(sp, 2);
      const sub = this.context.ecx.sub(0x23d94);
      let f = "?";
      try {
        const delta = sub.readPointer().add(4).readS32();
        const b = sub.add(delta);
        f = "+114=" + b.add(0x114).readS32() + " +118=" + b.add(0x118).readS32() +
            " +140=" + b.add(0x140).readS32() + " +148=" + b.add(0x148).readS32() +
            " +150=" + b.add(0x150).readS32() + " +158=" + b.add(0x158).readS32() +
            " +4c4=" + b.add(0x4c4).readS32() + " +4c8=" + b.add(0x4c8).readS32();
      } catch (e) {}
      const wh = bufWH(nc.toUInt32());
      log("NC_redraw mode=" + mode + " ncbuf=" + wh.w + "x" + wh.h +
          " this=" + toStatic(this.context.ecx) + " " + f + " " + state());
    }
  });

  // --- 5. chat/notification ticker ---
  Interceptor.attach(VA(0x47A890), {
    onEnter() {
      const sp = this.context.esp;
      let txt = "";
      try { txt = sp.add(4).readPointer().readUtf8String(64); } catch (e) {}
      log("NetMsg_pop this=" + toStatic(this.context.ecx) + " label='" + txt +
          "' delay=" + argS(sp, 2) + " " + state());
    }
  });

  log("hooks armed " + state());
}
