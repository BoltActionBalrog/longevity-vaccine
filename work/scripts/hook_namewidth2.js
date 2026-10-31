"use strict";
// NAME-POPUP WIDTH-CHAIN PROBE v2 (2026-07-10). OBSERVE-ONLY: no replace, no writes.
//
// v1 (hook_namewidth.js) attached inside Popup_calculate_dimensions (0x404b7f / 0x404bd0) and
// Popup_on_draw_background (0x406183) — all three placement-audited clean (whole-image scan: no
// branch, jcc, short-jump, or dword literal lands in any 5-byte window), all callbacks read-only —
// and yet EVERY v1 run (3/3, both exes) visibly REMOVED modal text and stripped the Quit modal to
// its default OK button, collapsing Dialog[+0x5C] to the 480 default and destroying the very value
// under measurement. The namefield probe (single attach at the Buffer_box_sprite entry) ran clean
// on the same exe/res/launch minutes earlier (d5c=514 measured = matches the no-Frida screenshot).
// Mechanism unproven, correlation perfect: DO NOT attach inside those two functions. v2 uses the
// PROVEN attach shape and reads the whole width chain from the popup object at draw time instead.
//
// ATTACH (auto per exe):
//   * PATCHED exe:  0x5E2DD3 is a baked E8 detour -> attach at its cave target 0xA11740
//                   (hook_namefield.js's proven host). [esp]=0x5E2DD8 resume, so args[0]=caller
//                   ret, args[1]=&RECT, args[2]=&params.
//   * PRISTINE exe: 0x5E2DD3 is the native Buffer_box_sprite entry (push ecx/ebx/ebp/esi/edi —
//                   five 1-byte pushes, exactly the 5-byte patch; no branch targets in the window,
//                   whole-image-audited). args[0]=&RECT, args[1]=&params, caller=this.returnAddress.
//   ecx = dest Buffer* in both. Popups draw into their own buffer at popup+0x444, so
//   popup = dest-0x444; validated by requiring [popup+0x21d0] to be a readable pointer whose
//   [+8] (iv3) is a sane small offset. Non-popup dests log rect-only lines.
//
// RUN at 1024x768 on BOTH exes (PRISTINE first):
//   desktop "SMACX Frida PRISTINE 1024x768" / "SMACX Frida Trace 1024x768"  (both repointed), or
//   work\run-frida-pristine.bat hook_namewidth2.js 1024 768 frida_log_append.js
//   work\run-frida-at-res.bat  hook_namewidth2.js 1024 768 frida_log_append.js
// Reach the base-name popup (new game, or rename a base), then quit. Diff the CHAIN lines between
// the exe=PRISTINE and exe=PATCHED runs: the first differing field names the culprit. The name
// popup is the static Popup object whose buffer (dest) is ~0x1a4378 (popup 0x1a3f34), ring drawn
// from site 0x40623d with set=d5a0.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_namewidth2.log";
log("=== hook_namewidth2.js (OBSERVE-ONLY, box-sprite-entry attach, width chain at draw) ===");

if (requireBase()) {
  const gnow = () => { try { return ptr(VA(0x668740)).readS32(); } catch (e) { return -1; } };
  const entryByte = ptr(VA(0x5E2DD3)).readU8();
  const PATCHED = (entryByte === 0xE8);
  const ATTACH = PATCHED ? 0xA11740 : 0x5E2DD3;
  log("exe=" + (PATCHED ? "PATCHED" : "PRISTINE") + " entrybyte=0x" + entryByte.toString(16)
    + " attach=0x" + ATTACH.toString(16));

  const SETS = {
    "0x78d690": "d690_backdrop", "0x78d5a0": "d5a0_ring", "0x78d618": "d618_title",
    "0x78d528": "d528_body_field", "0x6846b0": "picker_ornate",
  };
  const S32 = (p, off) => { try { return p.add(off).readS32(); } catch (e) { return null; } };
  const seen = {};

  Interceptor.attach(ptr(VA(ATTACH)), {
    onEnter: function (args) {
      let from, rect, par;
      if (PATCHED) { from = args[0]; rect = args[1]; par = args[2]; }
      else { from = this.returnAddress; rect = args[0]; par = args[1]; }
      let L, T, R, B, pv, fv;
      try {
        L = rect.readS32(); T = rect.add(4).readS32();
        R = rect.add(8).readS32(); B = rect.add(12).readS32();
        pv = "0x" + par.toUInt32().toString(16);
        fv = "0x" + from.toUInt32().toString(16);
      } catch (e) { return; }
      if (R <= L || B <= T) return;
      if (!SETS[pv]) return;                       // popup chrome sets only
      const k = fv + "|" + pv + "|" + L + "," + T + "," + R + "," + B;
      if (seen[k]) return;
      seen[k] = 1;

      const dest = this.context.ecx;
      let chain = "";
      try {
        const p = dest.sub(0x444);                 // popup = dest buffer - 0x444
        const dlg = p.add(0x21d0).readPointer();
        const iv3 = dlg.add(8).readS32();
        if (iv3 > 0 && iv3 < 0x10000) {
          const b = p.add(iv3);
          chain = " | popup=0x" + p.toUInt32().toString(16)
            + " type=" + S32(p, 0x2350)
            + " d2c=" + S32(b, 0x21fc) + " d5c=" + S32(b, 0x222c) + " d2230=" + S32(b, 0x2230)
            + " init_x=" + S32(p, 0x21cc)
            + " boxw=" + S32(p, 0x30bc) + " contw=" + S32(p, 0x30d8)
            + " padx=" + S32(p, 0x30e0) + " pady=" + S32(p, 0x30e4)
            + " art=0x" + (S32(p, 0x2144) >>> 0).toString(16)
            + " num=" + S32(p, 0x3104) + " den=" + S32(p, 0x3108);
          const art = p.add(0x2144).readPointer();
          if (!art.isNull()) chain += " artw18=" + S32(art, 0x18);
        }
      } catch (e) { /* non-popup dest: rect-only line */ }

      log("draw g=" + gnow() + " from=" + fv + " set=" + pv + "(" + SETS[pv] + ")"
        + " dest=0x" + dest.toUInt32().toString(16)
        + " L=" + L + " T=" + T + " R=" + R + " B=" + B
        + " w=" + (R - L + 1) + " h=" + (B - T + 1) + chain);
    }
  });
  log("attached; reach the base-name popup (new game, or rename a base), then quit.");
}
