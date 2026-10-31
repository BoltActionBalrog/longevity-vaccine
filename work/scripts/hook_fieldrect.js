"use strict";
// FIELD-RECT OBSERVER (2026-07-09). OBSERVE-ONLY: no replace, no writes, no pokes.
//
// PURPOSE. The Quit modal's text box is TWO concentric frame draws. Their per-side insets are
// L/T/R/B = 4/4/4/2 at g=22, 5/5/5/6 at g=25, 10/10/10/10 at g=40 (measured from the stroke
// census rects). They are not a scaled constant: the OUTER and INNER rects are computed and
// rounded INDEPENDENTLY, so the residual between them falls wherever the two roundings land.
// Symmetric at 4K by luck; 2px off at 1920; 1px the other way at 1600.
//
// To fix it faithfully (patched = vanilla x g/16, per CLAUDE.md) we need VANILLA's per-side
// insets. The stroke census cannot see them: at g<=16 the four renderers early-out to a plain
// Buffer_box_sprite and never call thunk_frame_enlarge, so no census line exists. This hook
// attaches at the RENDERER ENTRIES instead, which run at every g including native.
//
// SAFETY (see [[feedback-frida-attach-branch-target]]):
//   * Buffer_box_sprite @0x5E2DD3 is a BAKED DETOUR SITE (`call 0xa11740`) and 0x5E2DD8 is that
//     detour's push;ret RESUME address. BOTH are untouchable. Do not attach there.
//   * The four renderers are cave FUNCTIONS entered by a plain E8 from the popup draw code, so
//     their entries are safe hosts. onEnter only (a call-site/entry attach must never use
//     onLeave semantics we do not need here anyway).
//   * Each renderer's first insn is `cmp dword [g_popup_scale_num], 0x10` (7 bytes) and its
//     `jle` target lies past entry+5, so no branch target sits inside the patch window.
//
// Reads: ecx = dest Buffer*, [esp+4] = RECT*, [esp+8] = BoxSpriteParams*.
// The params VA identifies the sprite set (0x78d690 backdrop, 0x78d5a0 ring, 0x78d618 title
// inner, 0x78d528 body/field, 0x6846b0 ornate picker).
//
// RUN AT 1024x768 FIRST (that is the vanilla baseline), then 1920x1080, then 3840x2160.
//   run-frida-at-res.bat hook_fieldrect.js 1024 768 frida_log_append.js
// Open the QUIT modal each time (in-game: MENU -> Quit, or the main-menu Quit).
// Then: py work\scripts\check_fieldrect.py
// Log: work/tests/frida_fieldrect.log
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_fieldrect.log";
log("=== hook_fieldrect.js (OBSERVE-ONLY: per-draw frame rects, all g incl. native) ===");

if (requireBase()) {
  const G = 0x00668740;
  const RENDERERS = [
    [0x00668E00, "box_thick"],
    [0x00A0C000, "hollow"],
    [0x00A0C140, "hollow_flat"],
    [0x00A12C00, "intK"],
  ];

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

  RENDERERS.forEach(function (r) {
    const addr = r[0], tag = r[1];
    Interceptor.attach(ptr(VA(addr)), {
      onEnter: function (args) {
        const g = gnow();
        const dest = this.context.ecx;
        const rect = args[0], par = args[1];
        let L, T, R, B, pv;
        try {
          L = rect.readS32(); T = rect.add(4).readS32();
          R = rect.add(8).readS32(); B = rect.add(12).readS32();
          pv = "0x" + par.toUInt32().toString(16);
        } catch (e) { return; }
        if (R <= L || B <= T) return;

        // one line per (g, tag, params, size) — popups redraw constantly
        const k = g + "|" + tag + "|" + pv + "|" + (R - L) + "x" + (B - T);
        if (seen[k]) return;
        seen[k] = 1;

        log("rect g=" + g + " " + tag
          + " set=" + pv + (SETS[pv] ? "(" + SETS[pv] + ")" : "")
          + " dest=0x" + dest.toUInt32().toString(16)
          + " L=" + L + " T=" + T + " R=" + R + " B=" + B
          + " w=" + (R - L + 1) + " h=" + (B - T + 1));
      }
    });
    log("attached " + tag + " @0x" + addr.toString(16));
  });

  log("g=" + gnow() + "  -- open the QUIT modal. Two concentric frames draw into the popup buffer.");
  log("The pair to look for: a d528/d618 rect nested inside a d5a0/d618 rect on the SAME dest.");
}
