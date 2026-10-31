"use strict";
// v12 BAKED verification (2026-07-09). OBSERVE ONLY -- no Frida-side fix. Confirms the two baked thunks
// (thunk_faction_wrapwidth + derived-K thunk_channel_adjust) reproduce the validated prototype exactly.
// Live exe MD5 must be 75cae700985bb62f8ede966b0a82084c.
//
// Per faction quote redraw, all read in the SAME on_redraw (no cross-hook mispairing):
//   measW  = wrap budget arriving at Buffer_wrap_height_flying AFTER thunk_faction_wrapwidth narrowed it
//   drawW  = width Buffer_write_strings wraps at AFTER thunk_faction_textmargin narrowed it
//     -> PASS requires measW == drawW  (the whole root-cause fix in one equality)
//   measB  = content_top + content_h ; drawBottom = write_strings eax
//     -> PASS requires drawBottom - measB == K = g - (g>>2) + 2*ps3 - 18
//   innerB = g_frame_inset_rect.bottom (0xA0C5DC) committed by thunk_channel_adjust THIS cycle
//     -> PASS requires innerB - drawBottom == ps3   (the uniform text->stroke gap, at EVERY quote length)
// Run 4K + 1600 + 1920 + 1024(native no-op: expect measW==drawW and the thunks inert).
// Log: work/tests/frida_factv12.log
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_factv12.log";
log("=== hook_factv12.js started (BAKED verify, observe-only) ===");

if (requireBase()) {
  const REDRAW = 0x00604AB0, WRITESTR = 0x005DB040, FLYING = 0x005DDDA0,
        POPUP = 0x009403E0, G = 0x00668740, WINBUF = 0x00940824, INSETB = 0x00A0C5DC;
  const gnow = () => ptr(VA(G)).readS32();
  const ps3f = (g) => (3 * g) >> 4;
  const Kf = (g) => g - (g >> 2) + 2 * ps3f(g) - 18;
  let drawActive = false, measW = -1, fails = 0, checks = 0;

  Interceptor.attach(VA(REDRAW), {
    onEnter() { this.f = this.context.ecx.toUInt32() === POPUP; if (this.f) drawActive = true; },
    onLeave() { if (this.f) drawActive = false; }
  });
  Interceptor.attach(VA(FLYING), {
    onEnter() {
      if (this.context.ecx.toUInt32() !== WINBUF) return;
      const w = this.context.esp.add(0x08).readS32();
      if (w > 0) measW = w;   // last non-null budget seen while measuring this quote
    }
  });
  Interceptor.attach(VA(WRITESTR), {
    onEnter() {
      this.on = drawActive && this.context.ecx.toUInt32() === WINBUF;
      if (!this.on) return;
      const p = ptr(POPUP), sp = this.context.esp;
      this.g = gnow();
      this.w = sp.add(0x10).readS32();
      this.ct = p.add(0x30e8).readS32() + p.add(0x30e0).readS32();
      this.ch = p.add(0x30d4).readS32();
    },
    onLeave() {
      if (!this.on) return;
      const g = this.g, ps3 = ps3f(g), K = Kf(g);
      const measB = this.ct + this.ch, drawB = this.context.eax.toInt32();
      const innerB = ptr(VA(INSETB)).readS32();
      const okW = (measW === this.w);
      const okK = (drawB - measB === K);
      const okGap = (innerB - drawB === ps3);
      const ok = okW && okK && okGap;
      checks++; if (!ok) fails++;
      log("g=" + g + " measW=" + measW + " drawW=" + this.w + (okW ? " [W ok]" : " [W MISMATCH]")
        + " | measB=" + measB + " drawBottom=" + drawB + " K=" + K
        + " delta=" + (drawB - measB) + (okK ? " [K ok]" : " [K MISMATCH]")
        + " | innerB=" + innerB + " gap=" + (innerB - drawB) + " ps3=" + ps3
        + (okGap ? " [gap ok]" : " [gap MISMATCH]")
        + (ok ? "   PASS" : "   *** FAIL ***"));
    }
  });
  setInterval(function () {
    if (checks) log("-- summary: " + checks + " draw(s), " + fails + " failure(s)");
  }, 15000);
  log("hook armed. Click every leader. PASS needs measW==drawW, delta==K, gap==ps3.");
}
