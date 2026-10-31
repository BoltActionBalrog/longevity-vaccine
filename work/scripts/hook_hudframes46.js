"use strict";
// v46 = OBSERVER ONLY. The ENTIRE v35 HUD lever set is now BAKED into the
// exe (build 680a2941, 2026-07-06):
//   - group hud_turn_band     (233a3cf4): TURN COMPLETE banner dst-bounce
//   - group hud_widgets_scale (680a2941): A/F fonts (Font_init object-gated
//     entry detour), B FontCache mul, C' veh/base_draw args, E/G/H fallbacks,
//     N x16 joins, J box frames, K cell ring, R M/I font, W gate v4,
//     V fillcap v2. X/Z/Q not baked (inert/no-op/subsumed — see
//     assemble_hud_widgets.py + memory project-smac-hud-scaling).
// Running ANY earlier hook (v35..v45) now DOUBLE-APPLIES levers. This script
// only watches:
//   [TBo] turn-flic draws (dirty rect == scaled proves thunk_band_draw ran)
//   [FO]  first few gated Font_init hits (proves thunk_hud_fontobj fires)
//   [hb]  heartbeat
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_hudfonts.log";
log("=== hook_hudframes46.js started ===");
installAVHandler("hudframes46");

if (requireBase()) {
  const BASE = VA(0x400000);
  function staticOf(p) {
    try {
      const off = p.sub(BASE).toUInt32();
      if (off < 0x700000) return 0x400000 + off;
    } catch (e) {}
    return 0;
  }
  function G() {
    const sh = VA(0x9B7B20).readS32();
    return Math.min(40, Math.max(16, Math.floor(16 * sh / 768)));
  }
  let nS = 0, nFO = 0;
  const TURN_FLIC = VA(0x7D2D70);
  const bandObs = {
    onEnter() {
      this.doL = this.context.ecx.equals(TURN_FLIC) && nS < 6;
      if (this.doL) {
        const sp = this.context.esp;
        this.x = sp.add(4).readS32(); this.y = sp.add(8).readS32();
      }
    },
    onLeave() {
      if (!this.doL) return;
      nS++;
      const fl = TURN_FLIC;
      log("[TBo] band draw @" + this.x + "," + this.y +
          " dirty=" + fl.add(0x58C).readS32() + "," + fl.add(0x590).readS32() +
          ".." + fl.add(0x594).readS32() + "," + fl.add(0x598).readS32());
    }
  };
  Interceptor.attach(VA(0x62A070), bandObs);
  Interceptor.attach(VA(0x62A120), bandObs);

  // Font_init observer: with thunk_hud_fontobj baked, HUD font objects should
  // arrive here with ALREADY-SCALED heights (the thunk rewrote [esp+8] before
  // the displaced prologue resumes) — attach at the RESUME point is unsafe;
  // observe at Buffer text level instead? Keep it simple: log the 3 MainWin
  // StatusWin font objects' cell heights on a timer.
  const FONTS = [0x8C6A98, 0x8C6AC0, 0x8C6AE8, 0x7AFD50, 0x7AD2F8];
  setInterval(function () {
    if (nFO >= 3) return;
    nFO++;
    let line = "[FO] font cellH:";
    FONTS.forEach(function (f) {
      try { line += " " + VA(f).add(0xC).readS32(); } catch (e) { line += " ?"; }
    });
    log(line + " g=" + G());
  }, 15000);
  log("v46 armed (OBSERVER ONLY — all HUD levers baked in 680a2941), g=" + G());
}
