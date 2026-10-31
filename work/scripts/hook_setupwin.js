// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// hook_setupwin.js — NetWin MULTIPLAYER SETUP lobby: prove the build chain live.
// Run 1: PROTO=false — census GraphicWin_init/Win_center/BaseButton_init/attach args,
//        dump the rect table at first draw, dedup-log find_font + sprite blit sites.
// Run 2: PROTO=true  — live-prototype the scale (rects source-keyed to native values).
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_setupwin.log";

const PROTO = false; // NEVER re-enable against the patched exe — the netwin_lobby_scale group now scales in-binary; PROTO on top double-scales BaseButton args.

log("=== hook_setupwin.js started (PROTO=" + PROTO + ") ===");
installAVHandler("setupwin");

if (requireBase()) {
  const NETWIN        = VA(0x0080A6F8);
  const SETUP_LOBBY   = VA(0x00482490);
  const NETWIN_DRAW   = VA(0x00481AD0);
  const GWIN_INIT     = VA(0x005D4EF0);
  const WIN_CENTER    = VA(0x005ED5C0);
  const BTN_INIT      = VA(0x00607210);
  const TSCROLL_ATT   = VA(0x006292D0);
  const EDITLN_ATT    = VA(0x00614FE0);
  const FIND_FONT     = VA(0x005882F0);
  const SPR_DRAW2     = VA(0x005E4B4A);
  const SPR_BLIT_CORE = VA(0x005E4B9A);
  const SCREEN_W      = VA(0x009B7B1C);
  const SCREEN_H      = VA(0x009B7B20);

  // the popup scale this screen runs at, from the screen size (works on pristine too, where g_popup_scale_num
  // is never written): SL.popupG = scaling_laws.popup_g, min of both axes, floored (scaling_laws.js prelude)
  function calcG() {
    return SL.popupG(SCREEN_W.readS32(), SCREEN_H.readS32());
  }

  // lobby code range: NetWin draw/build fns live in 0x47F000..0x484000
  const LOBBY_LO = VA(0x0047F000), LOBBY_HI = VA(0x00484000);
  function retInLobby(ra) { return ra.compare(LOBBY_LO) >= 0 && ra.compare(LOBBY_HI) < 0; }

  let inLobby = false;
  let drawCount = 0;
  let rectsScaled = false;
  const seen = new Set();
  function once(key, msg) { if (!seen.has(key)) { seen.add(key); log(msg); } }
  function hx(p) { return "0x" + p.toString(16); }

  // native rect table from the static map (offset -> [L,T,R,B]); A14 excluded (derived from client)
  const NATIVE_RECTS = {};
  function put(off, r) { NATIVE_RECTS[off] = r; }
  put(0xA34, [7, 0x24, 0x134, 0x38]);
  put(0xA24, [7, 0x3A, 0x134, 0x180]);
  put(0xA54, [0x13D, 0x24, 0x319, 0x38]);
  put(0xA64, [0x13A, 0x21, 0x31C, 0xEB]);
  for (let r = 0; r < 7; r++) {
    const y = 0x3A + r * 0x16, y2 = y + 0x14;
    put(0xC54 + r * 16, [0x13D, y, 0x14D, y2]);
    put(0xBC4 + r * 16, [0x14F, y, 0x15F, y2]);
    put(0xA74 + r * 16, [0x161, y, 0x213, y2]);
    put(0xAE4 + r * 16, [0x215, y, 0x2A1, y2]);
    put(0xB54 + r * 16, [0x2A3, y, 0x319, y2]);
  }
  put(0xC34, [0x13D, 0xD4, 0x229, 0xE8]);
  put(0xC44, [0x22C, 0xD4, 0x318, 0xE8]);
  put(0xCC4, [0x13D, 0xF1, 0x319, 0x162]);
  put(0xCD4, [0x13D, 0x164, 0x319, 0x180]);
  put(0xCF4, [7, 0x189, 0x319, 0x19D]);
  put(0xD14, [0x1B, 0x19F, 0x18F, 0x251]);
  put(0xD24, [0x1A5, 0x19F, 0x319, 0x251]);
  // union/outer rects A44/CE4/D04 + A14 dumped but never proto-scaled (derived)
  const DUMP_ONLY = [0xA14, 0xA44, 0xCE4, 0xD04];

  function rd4(off) {
    const p = NETWIN.add(off);
    return [p.readS32(), p.add(4).readS32(), p.add(8).readS32(), p.add(12).readS32()];
  }
  function dumpRects(tag) {
    log("--- rect table (" + tag + ") titleH=" + NETWIN.add(0x16C).readS32() + " ---");
    const offs = Object.keys(NATIVE_RECTS).map(Number).concat(DUMP_ONLY).sort((a, b) => a - b);
    for (const off of offs) {
      const v = rd4(off);
      const n = NATIVE_RECTS[off];
      const flag = n ? (v.join(",") === n.join(",") ? " =native" : " DIFFERS(native " + n.join(",") + ")") : " (derived)";
      log("  +0x" + off.toString(16) + "  {" + v.join(",") + "}" + flag);
    }
  }
  function protoScaleRects(g) {
    if (rectsScaled) return;
    rectsScaled = true;
    let n = 0;
    for (const off of Object.keys(NATIVE_RECTS).map(Number)) {
      const v = rd4(off);
      const nat = NATIVE_RECTS[off];
      if (v.join(",") !== nat.join(",")) { log("  proto SKIP +0x" + off.toString(16) + " not native"); continue; }
      const p = NETWIN.add(off);
      for (let i = 0; i < 4; i++) p.add(i * 4).writeS32(Math.floor(nat[i] * g / 16));
      n++;
    }
    const th = NETWIN.add(0x16C);
    if (th.readS32() === 0x1A) th.writeS32(Math.floor(0x1A * g / 16));
    // derived rects: recompute from their build formulas over the now-scaled table
    function unionPad(dst, srcs) {
      let L = 1e9, T = 1e9, R = -1e9, B = -1e9;
      for (const s of srcs) {
        const v = rd4(s);
        L = Math.min(L, v[0]); T = Math.min(T, v[1]);
        R = Math.max(R, v[2]); B = Math.max(B, v[3]);
      }
      const p = NETWIN.add(dst);
      p.writeS32(L - 3); p.add(4).writeS32(T - 3);
      p.add(8).writeS32(R + 3); p.add(12).writeS32(B + 3);
    }
    unionPad(0xA44, [0xA24, 0xA34]);
    unionPad(0xCE4, [0xCC4, 0xCD4]);
    unionPad(0xD04, [0xCF4, 0xD14, 0xD24]);
    // title bar A14 = {3,3,winW-3,3+titleH} in the scaled client
    const winW = Math.floor(800 * g / 16);
    const a14 = NETWIN.add(0xA14);
    a14.writeS32(3); a14.add(4).writeS32(3);
    a14.add(8).writeS32(winW - 3); a14.add(12).writeS32(3 + th.readS32());
    log("proto: scaled " + n + " rects + titleH + 4 derived, g=" + g);
  }

  Interceptor.attach(SETUP_LOBBY, {
    onEnter() {
      inLobby = true;
      drawCount = 0;
      rectsScaled = false;
      log("NetWin_setup_lobby ENTER this=" + hx(this.context.ecx.toUInt32()) +
          " NetWin=" + NETWIN + " screen=" + SCREEN_W.readS32() + "x" + SCREEN_H.readS32() +
          " g=" + calcG());
    },
    onLeave(rv) { inLobby = false; log("NetWin_setup_lobby LEAVE ret=" + rv); }
  });

  Interceptor.attach(GWIN_INIT, {
    onEnter() {
      if (!inLobby) return;
      const sp = this.context.esp, ecx = this.context.ecx;
      const x = arg(sp, 1), y = arg(sp, 2), w = arg(sp, 3), h = arg(sp, 4);
      log("GraphicWin_init ecx=" + hx(ecx.toUInt32()) + (ecx.equals(NETWIN) ? " (NetWin)" : "") +
          " x=" + x + " y=" + y + " w=" + w + " h=" + h + " ret=" + this.returnAddress);
      if (PROTO && ecx.equals(NETWIN) && w === 800 && h === 600) {
        const g = calcG();
        sp.add(0x0C).writeS32(Math.floor(800 * g / 16));
        sp.add(0x10).writeS32(Math.floor(600 * g / 16));
        log("proto: NetWin GraphicWin_init -> " + Math.floor(800 * g / 16) + "x" + Math.floor(600 * g / 16));
      }
    }
  });

  Interceptor.attach(WIN_CENTER, {
    onEnter() {
      if (inLobby) log("Win_center ecx=" + hx(this.context.ecx.toUInt32()) + " ret=" + this.returnAddress);
    }
  });

  Interceptor.attach(BTN_INIT, {
    onEnter() {
      if (!inLobby) return;
      const sp = this.context.esp;
      let txt = "?";
      try { txt = sp.add(4).readPointer().readCString(); } catch (e) {}
      log("BaseButton_init ecx=" + hx(this.context.ecx.toUInt32()) + " text='" + txt +
          "' x=" + arg(sp, 3) + " y=" + arg(sp, 4) + " w=" + arg(sp, 5) + " h=" + arg(sp, 6) +
          " ret=" + this.returnAddress);
      if (PROTO && retInLobby(this.returnAddress)) {
        const g = calcG();
        for (let i = 3; i <= 6; i++) sp.add(4 * i).writeS32(Math.floor(arg(sp, i) * g / 16));
        log("proto: BaseButton scaled");
      }
    }
  });

  function attachDump(addr, name) {
    Interceptor.attach(addr, {
      onEnter() {
        if (!inLobby) return;
        const sp = this.context.esp;
        const a = [];
        for (let i = 1; i <= 8; i++) a.push(arg(sp, i));
        log(name + " ecx=" + hx(this.context.ecx.toUInt32()) + " args=[" + a.join(",") + "] ret=" + this.returnAddress);
        if (PROTO && retInLobby(this.returnAddress)) {
          const g = calcG();
          for (let i = 1; i <= 4; i++) sp.add(4 * i).writeS32(Math.floor(a[i - 1] * g / 16));
          log("proto: " + name + " x/y/w/h scaled");
        }
      }
    });
  }
  attachDump(TSCROLL_ATT, "TextScroll_attach");
  attachDump(EDITLN_ATT, "EditLine_attach");

  Interceptor.attach(FIND_FONT, {
    onEnter() {
      if (!inLobby) return;
      const sp = this.context.esp;
      const size = arg(sp, 1), variant = arg(sp, 2);
      once("ff:" + this.returnAddress + ":" + size,
           "find_font(" + size + "," + variant + ") ret=" + this.returnAddress);
      if (PROTO && size <= 16 && retInLobby(this.returnAddress)) sp.add(4).writeS32(Math.floor(size * calcG() / 16));
    }
  });

  Interceptor.attach(NETWIN_DRAW, {
    onEnter() {
      if (!inLobby) return;
      drawCount++;
      if (drawCount === 1) {
        dumpRects("first NetWin_draw");
        if (PROTO) { protoScaleRects(calcG()); dumpRects("after proto scale"); }
      }
      if (drawCount <= 3 || drawCount % 50 === 0) log("NetWin_draw #" + drawCount);
    }
  });

  Interceptor.attach(SPR_DRAW2, {
    onEnter() {
      if (!inLobby) return;
      const sp = this.context.esp;
      once("sd2:" + this.returnAddress,
           "Sprite_draw_2 self=" + hx(this.context.ecx.toUInt32()) + " dest=" + hx(u32(arg(sp, 1))) +
           " key=" + arg(sp, 2) + " x=" + arg(sp, 3) + " y=" + arg(sp, 4) +
           " num=" + arg(sp, 5) + " den=" + arg(sp, 6) + " ret=" + this.returnAddress);
    }
  });
  Interceptor.attach(SPR_BLIT_CORE, {
    onEnter() {
      if (!inLobby) return;
      const sp = this.context.esp;
      once("sbc:" + this.returnAddress,
           "Sprite_blit_scaled_core ecx=" + hx(this.context.ecx.toUInt32()) +
           " a1=" + hx(u32(arg(sp, 1))) + " a2=" + hx(u32(arg(sp, 2))) +
           " a3=" + arg(sp, 3) + " a4=" + arg(sp, 4) + " ret=" + this.returnAddress);
    }
  });

  log("hooks installed; navigate: Main Menu -> Multiplayer -> (protocol) -> lobby, then quit.");
}
