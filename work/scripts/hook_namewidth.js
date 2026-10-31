"use strict";
// ============================================================================
// !! DO NOT RUN -- KEPT ONLY AS A HAZARD RECORD (Frida attach hazard #6) !!
// Despite the "observe-only" design below and a clean whole-image placement
// audit, attaching at these mid-function sites inside Popup_calculate_dimensions
// / Popup_on_draw_background EMPTIED popup content on BOTH exes, 3/3 runs
// (user: "removing the text from a lot of modals... removed all the buttons
// from the quit modal except for OK"). Mechanism never identified. Those two
// functions are NO-ATTACH zones; measure popup state from the Buffer_box_sprite
// entry instead -- see hook_namewidth2.js (the working v2) and memory
// feedback-frida-attach-branch-target hazard #6. Its width readings (d5c
// 514/479) were artifacts of the emptied popups; the real value is 480 in both
// exes (frida_namewidth2.log).
// ============================================================================
// NAME-POPUP WIDTH-CHAIN DIFFERENTIAL PROBE (2026-07-10). OBSERVE-ONLY: no replace, no writes.
//
// PURPOSE. Runtime probe hook_namefield.js proved the base-name popup's stray right stroke at
// 1024x768 (g=16) is the FIELD RING drawn at 0x40623d with rect R = [esi+0x21cc] + Dialog[+0x5C]
// + 3, where Dialog[+0x5C] (= [esi+iv3+0x222c], the stored field width) is ~514 patched vs ~479
// vanilla (+35). Every static suspect (art-ratio NOP 0x404b6f, minw clamp 0x404bc4, fieldR/
// fieldpads/nestpads thunks, lbcalc/minw/item_wrap g>16 gates) is provably identity at g=16 --
// so the +35 enters through a path we haven't modelled. This probe MEASURES the width chain at
// three sites that are NATIVE AND BYTE-IDENTICAL in both exes; run it once on the PRISTINE exe
// and once on the PATCHED exe and diff the logs: the first value that differs names the culprit.
//
// SITES (all instruction boundaries in BOTH exes; no branch target lands inside any 5-byte
// attach window; none overlaps a baked patch -- the 0x404b6f NOP sled ends at 0x404b7c and the
// 0x404bc4 imm ends at 0x404bc9):
//   A0 0x404b7f  Popup_calculate_dimensions, after `add eax,ecx`:
//                eax = art_w(x ratio in pristine; ratio elided by our NOP in patched) + padx.
//   A1 0x404bd0  the store `mov [edx+0x21fc],ecx` = Dialog[+0x2C] (requested width, clamped).
//                edx = popup + iv3. Logs the stored value + every input.
//   B  0x406183  Popup_on_draw_background block 2, ring path (only runs when [esi+0x2350]!=-1):
//                logs init_x [+0x21cc], Dialog[+0x2C]/[+0x5C]/[+0x2230], box w [+0x30bc],
//                content w [+0x30d8], pads [+0x30e0]/[+0x30e4].
//
// RUN at 1024x768, BOTH exes (PRISTINE first -- feedback_pristine_baseline_trace):
//   work\run-frida-at-res.bat hook_namewidth.js 1024 768 frida_log_append.js
// Reach the base-name popup (new game, or rename any base), then close the game.
// The exe is tagged per run (byte probe at 0x404b6f: 0x0F=pristine imul, 0x90=patched NOP).
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_namewidth.log";
log("=== hook_namewidth.js (OBSERVE-ONLY width-chain probe, dual-exe) ===");

if (requireBase()) {
  const G = 0x00668740;                 // g_popup_scale_num (cave; reads 0/garbage on pristine -- fine)
  const gnow = () => ptr(VA(G)).readS32();
  const tagByte = ptr(VA(0x404b6f)).readU8();
  const EXE = (tagByte === 0x0f) ? "PRISTINE" : (tagByte === 0x90 ? "PATCHED" : ("UNKNOWN(0x" + tagByte.toString(16) + ")"));
  log("exe=" + EXE + " g@attach=" + gnow());

  const S32 = (p, off) => { try { return p.add(off).readS32(); } catch (e) { return "ERR"; } };
  const PTR = (p, off) => { try { return p.add(off).readPointer(); } catch (e) { return null; } };
  let seqA = 0, seqB = 0;

  // A0: eax = art term + padx (art_w already multiplied by [0x3104]/[0x3108] in pristine only)
  Interceptor.attach(ptr(VA(0x404b7f)), {
    onEnter: function () {
      const c = this.context, esi = c.esi;
      const art = PTR(esi, 0x2144);
      log("A0 g=" + gnow()
        + " popup=0x" + esi.toUInt32().toString(16)
        + " artterm+padx=" + c.eax.toInt32()
        + " art=0x" + (art ? art.toUInt32().toString(16) : "0")
        + " art_w18=" + (art && !art.isNull() ? S32(art, 0x18) : "-")
        + " art_w10=" + (art && !art.isNull() ? S32(art, 0x10) : "-")
        + " num=" + S32(esi, 0x3104) + " den=" + S32(esi, 0x3108)
        + " padx=" + S32(esi, 0x30e0));
    }
  });

  // A1: store Dialog[+0x2C] <- ecx  (edx = popup + iv3)
  Interceptor.attach(ptr(VA(0x404bd0)), {
    onEnter: function () {
      const c = this.context, esi = c.esi, edx = c.edx;
      log("A1#" + (seqA++) + " g=" + gnow()
        + " popup=0x" + esi.toUInt32().toString(16)
        + " STORE d2c=" + c.ecx.toInt32()
        + " old_d2c=" + S32(edx, 0x21fc)
        + " d5c=" + S32(edx, 0x222c)
        + " d2230=" + S32(edx, 0x2230)
        + " init_x=" + S32(esi, 0x21cc)
        + " screenw_edi=" + c.edi.toInt32());
    }
  });

  // B: ring path read in Popup_on_draw_background block 2
  Interceptor.attach(ptr(VA(0x406183)), {
    onEnter: function () {
      const c = this.context, esi = c.esi;
      const dlg = PTR(esi, 0x21d0);
      const iv3 = (dlg && !dlg.isNull()) ? S32(dlg, 8) : "ERR";
      const base = (typeof iv3 === "number") ? esi.add(iv3) : null;
      log("B#" + (seqB++) + " g=" + gnow()
        + " popup=0x" + esi.toUInt32().toString(16)
        + " type=" + S32(esi, 0x2350)
        + " iv3=0x" + (typeof iv3 === "number" ? iv3.toString(16) : iv3)
        + " init_x=" + S32(esi, 0x21cc)
        + (base ? (" d2c=" + S32(base, 0x21fc)
                 + " d5c=" + S32(base, 0x222c)
                 + " d2230=" + S32(base, 0x2230)) : " (dlg ERR)")
        + " boxw=" + S32(esi, 0x30bc)
        + " contw=" + S32(esi, 0x30d8)
        + " padx=" + S32(esi, 0x30e0)
        + " pady=" + S32(esi, 0x30e4));
    }
  });

  log("attached A0@0x404b7f A1@0x404bd0 B@0x406183 -- reach the base-name popup, then quit.");
}
