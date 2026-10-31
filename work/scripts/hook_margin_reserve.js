// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// Prototype: popup right-margin scrollbar-reserve fix.
// THEORY: native box margins [this+0x21b0]=L(33) / [this+0x21b4]=R(67) are scaled xg/16 by
// thunk_scale_box_margin, but R embeds a FIXED 32px scrollbar reserve the backdrop draw never
// scales -> surplus 32*(g-16)/16 of dead space on the right of every popup (48px @4K).
// FIX under test: after the thunk scales R, subtract 32*(g-16)>>4 (i.e. scale only R-32, keep +32).
// Probe also logs every popup's NATIVE margins to confirm 33/67 is universal across types.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_margin_reserve.log";
log("=== hook_margin_reserve.js started ===");

if (requireBase()) {
  const G_SCALE = 0x668740;            // g_popup_scale_num (cave copy)
  const SITE_CALC = 0x00404e93;        // Popup_calculate_dimensions -> (our) thunk_scale_box_margin call site
  const FOOTER_BUMP = 0xA0CDD0;        // thunk_faction_footer_bump entry, pcave2+0xDD0 (tail of scale_box_margin; esi=this, margins scaled)

  function popupId(p) {                // identify by title/body text, not ptr (popups reuse the heap ptr)
    for (const off of [0xa48, 0x2188]) {
      try {
        const sp = p.add(off).readPointer();
        if (!sp.isNull()) {
          const s = sp.readAnsiString(40);
          if (s && s.trim().length) return s.trim();
        }
      } catch (e) {}
    }
    return "?";
  }

  // 1) PROBE: native margins before scaling
  Interceptor.attach(VA(SITE_CALC), {
    onEnter() {
      const t = this.context.esi;      // this (esi live at the call; ecx==esi fastcall)
      this.popup = t;
      const g = VA(G_SCALE).readS32();
      log("[calc] g=" + g + " this=" + t +
          " L[21b0]=" + t.add(0x21b0).readS32() +
          " R[21b4]=" + t.add(0x21b4).readS32() +
          " T[21b8]=" + t.add(0x21b8).readS32() +
          " B[21bc]=" + t.add(0x21bc).readS32() +
          " id='" + popupId(t) + "'");
    },
    onLeave() {
      const t = this.popup;
      log("[calc:out] boxw[30bc]=" + t.add(0x30bc).readS32() +
          " boxh[30c0]=" + t.add(0x30c0).readS32() +
          " Lm[30f0]=" + t.add(0x30f0).readS32());
    }
  });

  // 2) v3 margin rewrite RETIRED (2026-07-03): the "loose" x g/16 margins were correct all
  // along -- vanilla puts the 23px rail art INSIDE the side margins (L 33 = 23 rail + 10 gap,
  // R 67 = 32 outer gap + 23 rail + 12 gap), so once the rails scale x g/16 the baked thunk's
  // L=82/R=167 are exactly pristine-proportionate (rail 57 + gap 25 / gap 80 + rail 57 + gap 30).
  // v3's tightened margins (45/79) collide with the scaled rails -> "border images overlapping".
  // Keeping the FOOTER_BUMP attach as a log-only probe of the thunk's scaled values.
  Interceptor.attach(VA(FOOTER_BUMP), function () {
    const t = this.context.esi;
    const g = VA(G_SCALE).readS32();
    log("[margins] g=" + g + " (thunk x g/16, untouched)" +
        " L=" + t.add(0x21b0).readS32() +
        " R=" + t.add(0x21b4).readS32() +
        " B=" + t.add(0x21bc).readS32());
  });

  // 3) RAIL CENSUS + PROTOTYPE: popup side-rail chrome cut off below 529px (same class as
  // filedlg P1: window outgrew the fixed 15/8x529 strip art, drawn 1/1). The baked fix
  // (thunk_filedlg_railscale/railslide at the slide_show/slide_hide sites) is identity-gated
  // g_filedlg_active && dest==g_fd_winbuf, so popup windows stay native. PROTOTYPE: while a
  // popup runs slide_show/slide_hide, point the gate at ITS window buffer (win+0x444) so the
  // existing thunks scale its rails; restore on leave. Census logs confirm the draw path.
  const G_FD_ACTIVE = 0xA0E3A0;        // g_filedlg_active, pcave2+0x23A0
  const G_FD_WINBUF = 0xA0E5E0;        // g_fd_winbuf, pcave2+0x25E0
  const SLIDE_SHOW = 0x0045D440;
  const SLIDE_HIDE = 0x0045D970;
  const SPRITE_DRAW2 = 0x005E4B4A;
  const RAIL_SPRITES = [0x7CFFC4, 0x7CFFF0, 0x7D001C, 0x7D0048];

  function armGate(label) {
    return {
      onEnter(args) {
        const act = VA(G_FD_ACTIVE).readS32();
        if (act !== 0) { log("[rails] " + label + ": filedlg active, leave gate alone"); return; }
        if (VA(G_SCALE).readS32() <= 16) return;
        const win = args[0];             // cdecl arg1 = GraphicWin*
        this.armed = true;
        this.savedBuf = VA(G_FD_WINBUF).readPointer();
        VA(G_FD_WINBUF).writePointer(win.add(0x444));
        VA(G_FD_ACTIVE).writeS32(1);
        log("[rails] " + label + " win=" + win + " -> gate armed (buf=" + win.add(0x444) + ")");
      },
      onLeave() {
        if (!this.armed) return;
        VA(G_FD_ACTIVE).writeS32(0);
        VA(G_FD_WINBUF).writePointer(this.savedBuf);
        log("[rails] gate restored");
      }
    };
  }
  Interceptor.attach(VA(SLIDE_SHOW), armGate("slide_show"));
  Interceptor.attach(VA(SLIDE_HIDE), armGate("slide_hide"));

  // census: which sites draw the rail strips for the popup, at what dims/scale/dest
  const seen = new Set();
  Interceptor.attach(VA(SPRITE_DRAW2), {
    onEnter(args) {
      const self = this.context.ecx.toUInt32();
      if (RAIL_SPRITES.indexOf(self) < 0) return;
      const ret = this.returnAddress.sub(VA(0x400000)).add(0x400000);
      const key = ret.toString() + "/" + args[0] + "/" + args[4] + ":" + args[5];
      if (seen.has(key)) return;
      seen.add(key);
      log("[census] rail sprite=" + ptr(self) + " ret=" + ret + " dest=" + args[0] +
          " x=" + args[2].toInt32() + " y=" + args[3].toInt32() +
          " num=" + args[4].toInt32() + " den=" + args[5].toInt32());
    }
  });

  // 4) PROTOTYPE: popup chrome INSETS -- the d690 frame + title band must ABUT the scaled rails.
  // Popup_on_draw_background composes them from the window rect with NATIVE deltas for in-game
  // type-0/5 popups: d690 L+=0x17 (23 = rail width), R-=0x37 (55 = rail 23 + gap 32), B+=5
  // (0x405f24..0x405f3c); title band L+=0x1a (rail+3), R-=0x3a (0x405ff1..0x406000). With rails
  // scaled x g/16 the band/frame stick out past + under them (user shot 2026-07-03). Twin of
  // thunk_filedlg_insets: scale the deltas with railscale's IDENTICAL floor cascade.
  const SITE_D690 = 0x00405F77;   // call Buffer_box_sprite(&rect, d690) [redirected]; rect ptr at [esp], dest buf = ecx, popup = esi
  const SITE_D5A0 = 0x00406048;   // call [redirected -> pf_title_stash]; title-band rect at [esp]
  function railLdev(g) { return ((15 * g) >> 4) + ((8 * g) >> 4); }      // left rail pair device extent
  function railRanchor(bufW, g) {                                       // right rail pair device x (railscale's double floor)
    return Math.floor((Math.floor(bufW * 16 / g) - 55) * g / 16);
  }

  Interceptor.attach(VA(SITE_D690), function () {
    const g = VA(G_SCALE).readS32();
    if (g <= 16) return;
    const t = this.context.esi;
    const rect = this.context.esp.readPointer();
    const buf = this.context.ecx;
    const L = rect.readS32(), T = rect.add(4).readS32(), R = rect.add(8).readS32(), B = rect.add(0xc).readS32();
    const bufW = buf.add(0x80).readS32();
    log("[insets] d690 popup=" + t + " rect=" + L + "," + T + "," + R + "," + B + " bufW=" + bufW);
    if (L !== 0x17) return;                                  // only the in-game delta branch (L was 0 + 0x17)
    if (t.equals(ptr(0x9403e0))) { log("[insets] skip faction quote"); return; }
    const nL = railLdev(g), nR = railRanchor(bufW, g), nB = B - 5 + ((5 * g) >> 4);
    rect.writeS32(nL); rect.add(8).writeS32(nR); rect.add(0xc).writeS32(nB);
    // the pushed rect is a COPY ([ebp-0x14]); the ORIGINAL block ([ebp-0x24..-0x18], 0x10 below)
    // stays live -- the body TEXT-FIELD frame derives its right edge from it ([ebp-0x1c]-10+3
    // @0x406116/0x406132). Rewrite it too or the field frame keeps the native -0x37 inset and
    // protrudes past the scaled rails (user shot 2026-07-03 "text field's frame too wide").
    const orig = rect.sub(0x10);
    orig.writeS32(nL); orig.add(8).writeS32(nR); orig.add(0xc).writeS32(nB);
    log("[insets] d690 -> " + nL + "," + T + "," + nR + "," + nB + " (copy+original)");
  });

  Interceptor.attach(VA(SITE_D5A0), function () {
    const g = VA(G_SCALE).readS32();
    if (g <= 16) return;
    const t = this.context.esi;
    const rect = this.context.esp.readPointer();
    const buf = this.context.ecx;
    const L = rect.readS32(), R = rect.add(8).readS32();
    const bufW = buf.add(0x80).readS32();
    log("[insets] d5a0 popup=" + t + " L=" + L + " R=" + R + " bufW=" + bufW);
    if (L !== 0x1b) return;                                  // 0x1a in-game delta + the inc edx
    if (t.equals(ptr(0x9403e0))) return;
    const p3 = (3 * g) >> 4;
    const nL = railLdev(g) + p3 + 1, nR = railRanchor(bufW, g) - p3 - 1;
    rect.writeS32(nL); rect.add(8).writeS32(nR);
    log("[insets] d5a0 -> L=" + nL + " R=" + nR);
    // d618 inner band, d528 title area + caption all DERIVE from this rect downstream
    // (inner_margin thunk + pf_title_stash read it after this call) -> they follow automatically.
  });

  log("hooks armed (calc probe + margins log-only + rail gate + chrome insets prototype)");
}
