"use strict";
// CONSOLE SAVE-UNDER STAMP probe -- observer only, fn-entry hosts only (all four verified plain
// `55 8B EC` / `56 8B F1` on the live exe 2026-09-20).
// Question: is the HUD box-5 frame seen under the base-screen name plate / citizens row the console
// save-under (t_cr_tile) stamping its HUD snapshot during a NON-HUD tile_panels call?
//   hypothesis: g_cr_armed is set by t_cr_snap / t_cr_snap_dl / t_cmb_snap and never cleared, and the
//   BaseWin-family callers pass this==MainWin (0x41E7AD pushes mode 1), so t_cr_tile's gates all pass.
// Per MainWin_tile_panels call: site, mode arg, iface mode, armed, and whether the strip's centre
// column EQUALS the snapshot before/after (after && !before == a stamp happened on this call).
// InfoWin reset/tick are logged too (the 2026-09-17 "ticker typed over the base strip" sighting).
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_console_stamp_" +
  new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + ".log";
log("=== hook_console_stamp.js started ===");
installAVHandler("console_stamp");
if (requireBase()) {
  const PCAVE2 = 0xA0C000, PCAVE2_END = 0xA0C000 + 0x40000;
  const G = VA(0x668740);
  const MW = VA(0x7AE820), STRIP = VA(0x7AEC64);
  const CRBUF = VA(PCAVE2 + 0x12790), CRL = VA(PCAVE2 + 0x12794), CRR = VA(PCAVE2 + 0x12798),
    CRB = VA(PCAVE2 + 0x1279C), CRARM = VA(PCAVE2 + 0x127A0);
  const MODE_TAB = VA(0x7AE778), MODE_IDX = VA(0x7D392C), G_BIG = VA(0x7D3930);
  const BASEWIN = VA(0x6A7628), INFOWIN = VA(0x7AD2A0);
  // own-visible bit only (Win+0x9C bit0 = what Win_is_visible 0x5F7E90 tests first); no engine calls from callbacks
  function Win_is_visible(w) { return w.add(0x9C).readU8() & 1; }
  const cave0 = VA(PCAVE2), cave1 = VA(PCAVE2_END);
  let lines = 0;
  const CAP = 1500;

  function rect(p) { return [p.readS32(), p.add(4).readS32(), p.add(8).readS32(), p.add(12).readS32()]; }
  function mode() {
    const i = MODE_IDX.readS32();
    return "mode[" + i + "]=" + ((i >= 0 && i < 16) ? MODE_TAB.add(i * 4).readS32() : "?");
  }
  // fraction of snapshot rows that equal the live strip centre column (sampled every 4th row)
  function snapMatch() {
    try {
      const buf = CRBUF.readPointer();
      if (buf.isNull()) return "nosnap";
      const L = CRL.readS32(), R = CRR.readS32(), B = CRB.readS32(), w = R - L;
      const bits = STRIP.add(0x54).readPointer(), pitch = STRIP.add(0x4A8).readS32();
      if (bits.isNull() || w <= 0 || B <= 0 || w > 4096 || B > 4096) return "bad L=" + L + " R=" + R + " B=" + B;
      let eq = 0, n = 0;
      for (let y = 0; y < B; y += 4) {
        const a = new Uint8Array(bits.add(y * pitch + L).readByteArray(w));
        const b = new Uint8Array(buf.add(y * w).readByteArray(w));
        let same = true;
        for (let i = 0; i < w; i++) if (a[i] !== b[i]) { same = false; break; }
        if (same) eq++;
        n++;
      }
      return eq + "/" + n;
    } catch (e) { return "ERR " + e.message; }
  }
  function state() {
    return "g=" + G.readS32() + " " + mode() + " big=" + G_BIG.readS32() + " armed=" + CRARM.readS32() +
      " baseVis=" + Win_is_visible(BASEWIN) + " snapLRB=" + CRL.readS32() + "," + CRR.readS32() + "," + CRB.readS32();
  }

  Interceptor.attach(VA(0x45C290), {          // MainWin_tile_panels(this, mode) RET 4
    onEnter() {
      this.on = lines < CAP;
      if (!this.on) return;
      lines++;
      const sp = this.context.esp;
      let site = this.returnAddress, wrapped = false;
      if (site.compare(cave0) >= 0 && site.compare(cave1) < 0) {   // entered via t_cr_tile: real site one frame up
        wrapped = true;
        site = sp.add(8).readPointer();
      }
      this.tag = "site=" + site + (wrapped ? " (via t_cr_tile)" : " (PLAIN)") +
        " this=" + this.context.ecx + (this.context.ecx.equals(MW) ? "=MainWin" : "") +
        " arg=" + sp.add(4).readS32();
      this.pre = snapMatch();
      log("[TILE >] " + this.tag + " " + state() + " snap==strip pre " + this.pre);
    },
    onLeave() {
      if (!this.on) return;
      // NOTE: the t_cr_tile copy runs AFTER this native returns; the stamp shows at the NEXT line's 'pre'
      log("[TILE <] native done; snap==strip " + snapMatch());
    }
  });

  Interceptor.attach(VA(0x41E790), {          // BaseWin-side console retile (mode 3 -> tile_panels(MainWin,1))
    onEnter() { if (lines < CAP) { lines++; log("[BASE retile 41e790 >] ret=" + this.returnAddress + " " + state()); } },
    onLeave() { if (lines < CAP) { lines++; log("[BASE retile 41e790 <] snap==strip " + snapMatch() + "   <-- full match while baseVis=1 == HUD stamped under the base screen"); } }
  });

  Interceptor.attach(VA(0x45D310), {          // SubInterface_set_iface_mode
    onEnter() { if (lines < CAP) { lines++; log("[IFACE set_mode] this=" + this.context.ecx + " ret=" + this.returnAddress + " " + state()); } }
  });

  let lastTick = "";
  Interceptor.attach(VA(0x458FF0), {          // InfoWin_reset
    onEnter() {
      if (lines < CAP) { lines++; log("[INFO reset] ret=" + this.returnAddress + " cur=" + INFOWIN.add(0x80).readS32() +
        " panels=" + rect(INFOWIN.add(0x10)) + " | " + rect(INFOWIN.add(0x20)) + " " + state()); }
    }
  });
  Interceptor.attach(VA(0x459150), {          // InfoWin_tick: log only gate-state CHANGES
    onEnter() {
      const s = "susp=" + INFOWIN.add(0xAC).readS32() + " " + mode() + " baseVis=" + Win_is_visible(BASEWIN);
      if (s !== lastTick && lines < CAP) { lines++; lastTick = s; log("[INFO tick gate] " + s); }
    }
  });
  log("hosts armed; " + state());
}
