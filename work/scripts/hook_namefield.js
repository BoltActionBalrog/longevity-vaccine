"use strict";
// NAME-POPUP FIELD-FRAME OBSERVER (2026-07-10). OBSERVE-ONLY: no replace, no writes, no pokes.
//
// PURPOSE. The "name your first base" popup at 1024x768 (g=16, must be a native no-op) draws its
// text-entry field frame with the RIGHT edge at screen x=787 instead of vanilla's 753 (+34), on
// TOP of the side rail and map background (refs\pristine\NameBase.png vs
// work\screenshots\terranx_pracx_1024x768_20260710-101530.png). Every baked thunk in the popup
// chrome chain gates g<=16 to a byte-exact native path (verified statically 2026-07-10), and the
// border/title/OK/body strokes are pixel-identical to vanilla — so the stray frame comes from a
// draw SITE we have not identified (draw-state multiplicity), with an input that is +34 at g=16.
// This hook logs, for EVERY Buffer_box_sprite draw: the ORIGINAL CALLER (the site), dest buffer,
// params set, and the rect — so one repro names the site and the wrong input directly.
//
// ATTACH SAFETY (see [[feedback-frida-attach-branch-target]]):
//   * Buffer_box_sprite 0x5E2DD3 is a BAKED DETOUR (`call 0xA11740`); 0x5E2DD8 is its push/ret
//     resume. BOTH untouchable. We attach at the DETOUR TARGET 0xA11740 instead — a cave function
//     entered by a plain E8, i.e. a safe host (same rule as hook_fieldrect.js's renderer entries).
//   * EVERY Buffer_box_sprite invocation funnels through it: direct native calls hit the baked E8
//     at 0x5E2DD3, and every cave chain tail-jumps via `push Buffer_box_sprite; ret` onto the same
//     entry byte. The push/ret tails leave the ORIGINAL site's return address on top, so
//     args[0] below is the true call site even for redirected draws.
//   * First insn is `cmp ecx, 0x7aec64` (6 bytes); no branch targets inside the 5-byte window
//     (jle/je targets are 0xA11750/0xA1175E). No other attach in this script touches the chain
//     (no site-hook + entry-hook soft-kill).
//
// Stack at 0xA11740 entry: [esp]=0x5E2DD8 (detour resume), [esp+4]=caller ret = args[0],
// [esp+8]=&RECT = args[1], [esp+0xC]=&BoxSpriteParams = args[2]. ecx = dest Buffer*.
//
// RUN at 1024x768 on the PATCHED exe:
//   work\run-frida-at-res.bat hook_namefield.js 1024 768 frida_log_append.js
// Start a new game and let the "name your first base" popup appear (or rename any base — same
// NAMEBASE flow). Then read work/tests/frida_namefield.log:
//   * the line(s) with set=0x78d528 and R-L ~ 519 (or any rect whose R lands ~787 on screen)
//     name the bad site in `from=`; the ~485-wide d528 line is the correct one (753).
// Known sites: 0x405d3e/0x405e9a = map-parented block; 0x405f7c/0x406159 = in-game type-0/5
// block; anything else = an unmapped drawer.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_namefield.log";
log("=== hook_namefield.js (OBSERVE-ONLY: every Buffer_box_sprite draw w/ caller site) ===");

if (requireBase()) {
  const G = 0x00668740;               // g_popup_scale_num
  const ENTRY = 0x00A11740;           // baked Buffer_box_sprite entry-detour target (cave)

  const gnow = () => ptr(VA(G)).readS32();
  const SETS = {
    "0x78d690": "d690_backdrop",
    "0x78d5a0": "d5a0_ring",
    "0x78d618": "d618_title_inner",
    "0x78d528": "d528_body_field",
    "0x78d870": "d870",
    "0x78d7f8": "d7f8",
    "0x6846b0": "picker_ornate",
  };

  const seen = {};

  Interceptor.attach(ptr(VA(ENTRY)), {
    onEnter: function (args) {
      const g = gnow();
      const dest = this.context.ecx;
      const from = args[0], rect = args[1], par = args[2];
      let L, T, R, B, pv, fv;
      try {
        L = rect.readS32(); T = rect.add(4).readS32();
        R = rect.add(8).readS32(); B = rect.add(12).readS32();
        pv = "0x" + par.toUInt32().toString(16);
        fv = "0x" + from.toUInt32().toString(16);
      } catch (e) { return; }
      if (R <= L || B <= T) return;

      // key on site+set+rect so re-draws dedup but a moved rect logs again
      const k = fv + "|" + pv + "|" + L + "," + T + "," + R + "," + B;
      if (seen[k]) return;
      seen[k] = 1;

      log("draw g=" + g
        + " from=" + fv
        + " set=" + pv + (SETS[pv] ? "(" + SETS[pv] + ")" : "")
        + " dest=0x" + dest.toUInt32().toString(16)
        + " L=" + L + " T=" + T + " R=" + R + " B=" + B
        + " w=" + (R - L + 1) + " h=" + (B - T + 1));
    }
  });
  log("attached Buffer_box_sprite entry-detour @0xa11740; g=" + gnow()
    + " -- reach the base-name popup (new game, or rename a base).");
}
