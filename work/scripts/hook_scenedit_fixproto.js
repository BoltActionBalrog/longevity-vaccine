// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// hook_scenedit_fixproto.js — RUNTIME PROTOTYPE of the two scenario-editor fixes.
// See it in-game before any byte is baked (scaling-layout skill step 4).
//
//   FIX 1 (diplo modal, DiploEditWin_exec 0x4DB080): every native immediate
//     scaled per scaling_laws.diplo_editor_layout — window/panels/fonts/buttons.
//     Derived splits (W/3, W/2, (span+2)/4) stay engine-side arithmetic.
//   FIX 2 (editor HUD panel): rewrite the palette/red seed arrays at 0x45B0ED
//     (post-derivation, pre-consumption; no branch targets in the 5-byte window)
//     from SL.editorPanelSeeds — the engine then builds buttons, unions, frames,
//     info rect, and hit rects from the corrected seeds. Painter font
//     find_font(10)@0x45B5D6 and the info-inset const 4@0x45B607 imm-patched.
//
// v2 additions: painter VARIANT fonts f1/f2 (the {…} spans), frame-stroke
// thickening via retargeting 6 Buffer_box_sprite sites to the baked
// thunk_pp_boxsprite dispatcher, diplo button bar/label zoom via the
// g_popup_active refcount bracket around DiploEditWin_exec.
// v3 additions: palette/red engraved icon FACES scale via thunk_btn_gate HIT
// override (route the 31 editor FlatButtons through the shrink/2D-zoom pipeline
// that already scales the unit-row arrows buttons[8..10]).
// v4 additions (both user-flagged 2026-08-12): FIX 2c — engine builds the frame
// unions/info rect from scaled seeds with NATIVE +-3 pads; overwrite +0xD4C/
// +0xD5C/+0xD6C(l,t,b) with the law rects at painter entry 0x45BC50. FIX 2d —
// info-text line step was the scaled font's sublinear OWN metric; substitute
// su(13,g) at Buffer_text_line_height inside painter_editor_info only.
// v5 additions (user-flagged 2026-08-12, "Cover Map" hover worst): FIX 2e — the
// NN-zoomed editor icon faces band; the baked btn_stripes/fe_pair_remap runs on
// them but their stripe pairs aren't in the remap's family set. Evidence-driven:
// detect each face's pair from the live buffer; F0/B9 -> arm the baked one-shot;
// new pair -> JS restripe with the remap's own P-law, logging measured indices
// for the bake.
// STILL NOT in this prototype (bake-time work): the info rect's right-edge -3,
// the CheckList container's own chrome.
//
// All patches verify the vanilla byte before writing (PRACX site-stomp rule) and
// are gated g>16 (native no-op).
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_scenedit_fixproto.log";
log("=== hook_scenedit_fixproto.js started (PROTOTYPE) ===");

if (requireBase()) {
  const su = (v, g) => SL.scalePx(v, g);
  const neg8 = v => (0x100 - v) & 0xFF;
  let applied = false;
  const DIAG = true;            // verify geometry + banding; strip after
  let diploActive = false;      // true across DiploEditWin_exec (gates cold DIAG hooks)

  const currentG = () => {
    const h = VA(0x9B7B20).readS32();
    return Math.max(16, Math.min(40, Math.floor((16 * h) / 768)));
  };

  // {va, off, size, expect, f(g), what} — expect = vanilla imm (byte-verified).
  const IMM = [
    // ---- DiploEditWin_exec 0x4DB080 ----
    { va: 0x4DB092, off: 1, size: 1, expect: 0x0E,  f: g => su(14, g),  what: "diplo font 14" },
    { va: 0x4DB0B0, off: 1, size: 4, expect: 0x18E, f: g => su(398, g), what: "diplo push H" },
    { va: 0x4DB0B5, off: 1, size: 4, expect: 0x2F6, f: g => su(758, g), what: "diplo push W" },
    { va: 0x4DB0C6, off: 6, size: 4, expect: 0x2F6, f: g => su(758, g), what: "diplo field W" },
    { va: 0x4DB0D0, off: 6, size: 4, expect: 0x18E, f: g => su(398, g), what: "diplo field H" },
    { va: 0x4DB1AC, off: 1, size: 4, expect: 4,     f: g => su(4, g),   what: "title band inset 4" },
    { va: 0x4DB1CB, off: 2, size: 1, expect: 0x14,  f: g => su(20, g),  what: "title band h 20" },
    { va: 0x4DB1DF, off: 1, size: 4, expect: 3,     f: g => su(3, g),   what: "title text inset 3" },
    { va: 0x4DB200, off: 1, size: 1, expect: 0x10,  f: g => su(16, g),  what: "title font 16" },
    { va: 0x4DB26F, off: 2, size: 1, expect: 4,     f: g => su(4, g),   what: "list right -4" },
    { va: 0x4DB275, off: 3, size: 4, expect: 4,     f: g => su(4, g),   what: "list left 4" },
    { va: 0x4DB27F, off: 3, size: 4, expect: 0x172, f: g => su(370, g), what: "list bottom 370" },
    { va: 0x4DB286, off: 3, size: 4, expect: 0x1F,  f: g => su(31, g),  what: "list top 31" },
    { va: 0x4DB298, off: 1, size: 4, expect: 3,     f: g => su(3, g),   what: "list content inset 3" },
    { va: 0x4DB41F, off: 3, size: 4, expect: 0x172, f: g => su(370, g), what: "chk bottom 370" },
    { va: 0x4DB428, off: 3, size: 4, expect: 0x1F,  f: g => su(31, g),  what: "chk top 31" },
    { va: 0x4DB432, off: 2, size: 1, expect: 4,     f: g => su(4, g),   what: "chk left +4" },
    { va: 0x4DB435, off: 2, size: 1, expect: 4,     f: g => su(4, g),   what: "chk right -4" },
    { va: 0x4DB67D, off: 2, size: 1, expect: 4,     f: g => su(4, g),   what: "btn left +4" },
    { va: 0x4DB680, off: 2, size: 1, expect: 4,     f: g => su(4, g),   what: "btn right -4" },
    { va: 0x4DB68B, off: 2, size: 1, expect: 2,     f: g => su(2, g),   what: "btn span +2" },
    { va: 0x4DB68E, off: 2, size: 1, expect: 4,     f: g => su(4, g),   what: "btn bottom -4" },
    { va: 0x4DB6A0, off: 2, size: 1, expect: 0xEC,  f: g => neg8(su(20, g)), what: "btn h -20" },
    { va: 0x4DB6A3, off: 3, size: 1, expect: 0xFE,  f: g => neg8(su(2, g)),  what: "btn w trim -2" },
    { va: 0x4DB708, off: 2, size: 1, expect: 2,     f: g => su(2, g),   what: "btn gap #1" },
    { va: 0x4DB76F, off: 2, size: 1, expect: 2,     f: g => su(2, g),   what: "btn gap #2" },
    { va: 0x4DB7D6, off: 2, size: 1, expect: 2,     f: g => su(2, g),   what: "btn gap #3" },
    // ---- painter_editor_info 0x45B550 ----
    // THREE find_font(0xA) calls: f0 @0x45B5D5, f2 @0x45B5C9, f1 @0x45B5BC.
    // The {…} spans of the info lines render in the VARIANT fonts f1/f2 —
    // scaling only f0 left the File/Rainfall/PLAY-mode values native (v1 bug).
    { va: 0x45B5D6, off: 0, size: 1, expect: 0x0A,  f: g => su(10, g),  what: "info font f0" },
    { va: 0x45B5CA, off: 0, size: 1, expect: 0x0A,  f: g => su(10, g),  what: "info font f2" },
    { va: 0x45B5BD, off: 0, size: 1, expect: 0x0A,  f: g => su(10, g),  what: "info font f1" },
    { va: 0x45B607, off: 0, size: 4, expect: 4,     f: g => su(4, g),   what: "info inset 4" },
  ];

  // Buffer_box_sprite call sites to retarget onto thunk_pp_boxsprite
  // (pcave2+0x3930 = VA 0xA0F930): the baked already-scaled-rect dispatcher —
  // [params+0x20]!=0 -> thunk_box_thick_devfill else thunk_box_thick_hollow_flat
  // (K-wide strokes), g<=16 -> plain native. Same E8 contract as 0x5E2DD3 (RET 8).
  const BOX_SPRITE = 0x5E2DD3, PP_BOXSPRITE = 0xA0F930;
  const FRAME_SITES = [
    { va: 0x4DB11F, what: "diplo outer d690" },
    { va: 0x4DB1D4, what: "diplo title band d528" },
    { va: 0x4DB28D, what: "diplo list panel d528" },
    { va: 0x45BCCF, what: "editor palette frame d5a0" },
    { va: 0x45BCEE, what: "editor brush frame d5a0" },
    { va: 0x45B5F8, what: "editor info frame d528" },
  ];

  function retargetFrames() {
    for (const s of FRAME_SITES) {
      const site = VA(s.va);
      const relOld = BOX_SPRITE - (s.va + 5);
      if (site.readU8() !== 0xE8 || site.add(1).readS32() !== relOld) {
        log("  SKIP frame site " + s.what + " @0x" + s.va.toString(16)
          + ": not a call to Buffer_box_sprite (bytes drifted?)");
        continue;
      }
      const relNew = PP_BOXSPRITE - (s.va + 5);
      Memory.patchCode(site.add(1), 4, code => code.writeS32(relNew));
      log("  [frame] " + s.what + " -> thunk_pp_boxsprite");
    }
  }

  function applyImms(g) {
    let ok = 0, skip = 0;
    for (const p of IMM) {
      const a = VA(p.va + p.off);
      const cur = p.size === 4 ? a.readU32() : a.readU8();
      if (cur !== p.expect) {
        log("  SKIP " + p.what + " @0x" + p.va.toString(16)
          + ": found 0x" + cur.toString(16) + " expect 0x" + p.expect.toString(16));
        skip++;
        continue;
      }
      const nv = p.f(g) >>> 0;
      Memory.patchCode(a, p.size, code => {
        if (p.size === 4) code.writeU32(nv); else code.writeU8(nv & 0xFF);
      });
      ok++;
    }
    log("[imm] applied " + ok + "/" + IMM.length + " (skipped " + skip + ") for g=" + g);
  }

  // FIX 2 seed rewrite — 0x45B0ED: after both seed-derivation loops, before the
  // union zeroing and BaseButton_init loops. esi==MainWin there, but we address
  // the static global directly.
  Interceptor.attach(VA(0x45B0ED), {
    onEnter() {
      const g = currentG();
      if (g <= 16) return;                      // native no-op gate
      if (!applied) { applyImms(g); retargetFrames(); applied = true; }
      const s = SL.editorPanelSeeds(g);
      const MW = VA(0x7AE820);
      const wr = (base, rects) => rects.forEach((r, i) => {
        const p = base.add(i * 16);
        p.writeS32(r[0]); p.add(4).writeS32(r[1]);
        p.add(8).writeS32(r[2]); p.add(12).writeS32(r[3]);
      });
      wr(MW.add(0xADC), s.pal);
      wr(MW.add(0xC6C), s.red);
      log("[seeds] g=" + g + " pal0=(" + s.pal[0] + ") pal24=(" + s.pal[24]
        + ") red0=(" + s.red[0] + ") cell=" + s.cell + " red_cell=" + s.redCell);
    }
  });

  // FIX 2b — palette/red engraved icon FACES. The 25 palette + 6 red FlatButtons
  // (statics MainWin+0x8A44=0x7B7264 .. red[5]) install their icon as stateSprites
  // (+0xAD4/+0xAD8/+0xADC) drawn NATIVE-size (num=den=1) centered in the (now
  // seed-scaled) button buffer -> a native-size glyph floating in a scaled slot.
  // Route them through thunk_btn_gate's HIT so the proven shrink -> render-native ->
  // StretchBlt-zoom -> stripes pipeline enlarges the WHOLE button buffer (icon
  // included) x g/16 -- the identical mechanism that already scales buttons[8..10]
  // (unit-row arrows) via the gate's esi statics. These are non-BaseWin contiguous
  // statics, so an esi RANGE -> unconditional HIT is sound (the memory "no esi RANGE"
  // warning is specifically a BaseWin range routed to the a7c content-check, which
  // disarmed the a7c==0 chevron stateSprites -- not applicable here).
  //
  // Prototype = override the gate's return in onLeave (a real CALL from
  // thunk_btn_shrink, so onLeave fires). The bake adds an esi-range prefix to the
  // gate body. Generous bounds [0x7B7264, 0x7CD0C8) provably cover all 31 editor
  // buttons and no other known button (M/T/I + arrows are all BELOW 0x7B7264); DIAG
  // logs the exact distinct in-range addresses so the baked range is MEASURED.
  const GATE = VA(0xA169E0);                    // thunk_btn_gate (pcave2 0xA0C000 + 0xA9E0)
  const PAL_LO = 0x7B7264;                       // palette[0] = MainWin+0x8A44
  const RED_HI = 0x7CD0C8;                        // red[0]=0x7C8CD0 + 6*0xB4C (generous upper bound)
  const gateSeen = new Set();
  Interceptor.attach(GATE, {
    onLeave(retval) {
      const esi = this.context.esi.toUInt32();
      if (esi >= PAL_LO && esi < RED_HI) {
        retval.replace(ptr(1));                   // force HIT -> shrink/2D-zoom the icon
        if (DIAG && !gateSeen.has(esi)) {
          gateSeen.add(esi);
          log("[gate] editor btn HIT esi=0x" + esi.toString(16)
            + " (#" + gateSeen.size + ")");
        }
      }
    }
  });

  // FIX 2e — icon-face STRIPE BANDING (user-flagged 2026-08-12, "Cover Map" hover
  // worst). The gate HIT routes the 31 editor buttons through shrink/NN-zoom, so
  // their striped console-art faces band ([[feedback-dither-no-resample-on-upscale]]
  // — my "engraved glyphs need no tail" call was wrong about the FACES). The baked
  // pipeline ALREADY calls thunk_btn_stripes -> fe_pair_remap on them (outside the
  // BaseWin early-out), but the remap only restripes its known pair families; the
  // editor faces' pairs aren't in the set (same story as the pre-v4 sb arrows).
  // Evidence-driven per [[feedback-dither-pair-ambiguity]] + "sample the buffer":
  //   onEnter (pre-remap, banding visible): detect the face's alternating pair
  //     from the live buffer. Pair==F0/B9 -> arm the baked one-shot g_rm_f0ovr
  //     (exactly what btn_stripes v4 does for the two sb arrows). Pair already in
  //     a baked family -> nothing (remap covers it). NEW pair -> stash for onLeave.
  //   onLeave (post-remap): JS-restripe the stashed pair with the SAME law the
  //     remap uses (P=SL.stripePeriod(g), hN=(P+1)>>1, y%P<hN -> top member; top = the
  //     chain-start member, i.e. the art's own first band). Logs pair indices +
  //     palette RGBs so the bake (fe_pair_remap v8 family / btn_stripes v5 arm)
  //     gets MEASURED indices, never guessed.
  const BTN_STRIPES = VA(0xA0EFD0);        // thunk_btn_stripes (pcave2 + 0x2FD0)
  const G_RM_F0OVR = VA(0xA1C634);         // fe_pair_remap v7 F0/B9 one-shot arm
  // pairs the baked remap already handles (unconditional, content-keyed, or armed)
  const BAKED_PAIRS = new Set(["e0/e1", "ae/ee", "41/c4", "41/c6", "41/c5", "53/bf", "b9/f0"]);
  const pairKey = (a, b) => (a < b ? a : b).toString(16) + "/" + (a > b ? a : b).toString(16);
  const stripesLogged = new Set();

  function detectFacePair(btn, P) {
    // dominant two-value alternating run chain over sampled columns
    const data = btn.add(0x498).readPointer();
    const w = btn.add(0x4c4).readS32();
    let h = btn.add(0x4c8).readS32(); if (h < 0) h = -h;
    const stride = btn.add(0x8ec).readS32();
    if (data.isNull() || w <= 0 || h <= 4 || h > 4000) return null;
    const credit = {};                     // key -> {runs, firstVotes:{val:n}}
    for (let i = 0; i < 12; i++) {
      const x = Math.floor((w * (2 * i + 1)) / 24);
      // column run-lengths
      const runs = [];
      let prev = -1, len = 0;
      for (let y = 0; y < h; y++) {
        const v = data.add(y * stride + x).readU8();
        if (v === prev) len++;
        else { if (prev >= 0) runs.push([prev, len]); prev = v; len = 1; }
      }
      if (prev >= 0) runs.push([prev, len]);
      // alternating chains of two values, run lengths <= P+1
      let c0 = -1, c1 = -1, chain = 0, first = -1;
      const flush = () => {
        if (chain >= 6 && c0 !== 9 && c1 !== 9) {
          const k = pairKey(c0, c1);
          if (!credit[k]) credit[k] = { runs: 0, firstVotes: {} };
          credit[k].runs += chain;
          credit[k].firstVotes[first] = (credit[k].firstVotes[first] || 0) + 1;
        }
        c0 = c1 = -1; chain = 0; first = -1;
      };
      for (const [v, len] of runs) {
        if (len > P + 1) { flush(); continue; }
        if (chain === 0) { c0 = v; chain = 1; first = v; }
        else if (chain === 1) { if (v !== c0) { c1 = v; chain = 2; } else { flush(); c0 = v; chain = 1; first = v; } }
        else if (v === (chain % 2 === 0 ? c0 : c1)) chain++;
        else { flush(); c0 = v; chain = 1; first = v; }
      }
      flush();
    }
    let best = null;
    for (const k in credit)
      if (!best || credit[k].runs > credit[best].runs) best = k;
    if (!best || credit[best].runs < 24) return null;
    const [a, b] = best.split("/").map(s => parseInt(s, 16));
    const fv = credit[best].firstVotes;
    let top = a;
    for (const v in fv) if (fv[v] > (fv[top] || 0)) top = parseInt(v);
    if (top !== a && top !== b) top = a;
    return { a: a, b: b, top: top, key: best, runs: credit[best].runs };
  }

  function restripeFace(btn, pair, P, hN) {
    const data = btn.add(0x498).readPointer();
    const w = btn.add(0x4c4).readS32();
    let h = btn.add(0x4c8).readS32(); if (h < 0) h = -h;
    const stride = btn.add(0x8ec).readS32();
    const mate = pair.top === pair.a ? pair.b : pair.a;
    for (let y = 0; y < h; y++) {
      const want = (y % P) < hN ? pair.top : mate;
      const rowPtr = data.add(y * stride);
      const row = new Uint8Array(rowPtr.readByteArray(w));
      let dirty = false;
      for (let x = 0; x < w; x++) {
        const v = row[x];
        if ((v === pair.a || v === pair.b) && v !== want) { row[x] = want; dirty = true; }
      }
      if (dirty) rowPtr.writeByteArray(row.buffer);
    }
  }

  Interceptor.attach(BTN_STRIPES, {
    onEnter() {
      this.fix = null;
      const esi = this.context.esi.toUInt32();
      if (esi < PAL_LO || esi >= RED_HI) return;
      const g = currentG();
      if (g <= 16) return;
      const P = SL.stripePeriod(g, 0);
      const btn = ptr(esi);
      const pair = detectFacePair(btn, P);
      const lkey = pair ? esi.toString(16) + ":" + pair.key : esi.toString(16) + ":none";
      if (!pair) {
        if (DIAG && !stripesLogged.has(lkey)) { stripesLogged.add(lkey); log("[stripe] btn=0x" + esi.toString(16) + " no pair detected (solid/keyed face?)"); }
        return;
      }
      if (pair.key === "b9/f0") {
        G_RM_F0OVR.writeU32(1);            // arm the baked family — remap restripes it
        if (DIAG && !stripesLogged.has(lkey)) { stripesLogged.add(lkey); log("[stripe] btn=0x" + esi.toString(16) + " pair f0/b9 -> armed baked one-shot (runs=" + pair.runs + ")"); }
        return;
      }
      if (BAKED_PAIRS.has(pair.key)) {
        if (DIAG && !stripesLogged.has(lkey)) { stripesLogged.add(lkey); log("[stripe] btn=0x" + esi.toString(16) + " pair " + pair.key + " -> baked family, remap covers"); }
        return;
      }
      this.fix = { btn: btn, pair: pair, P: P, hN: (P + 1) >> 1, esi: esi, lkey: lkey };
    },
    onLeave() {
      if (!this.fix) return;
      const f = this.fix;
      restripeFace(f.btn, f.pair, f.P, f.hN);
      if (DIAG && !stripesLogged.has(f.lkey)) {
        stripesLogged.add(f.lkey);
        log("[stripe] btn=0x" + f.esi.toString(16) + " NEW pair " + f.pair.key
          + " top=" + f.pair.top.toString(16) + " (" + rgb(f.pair.top) + ") mate rgb=("
          + rgb(f.pair.top === f.pair.a ? f.pair.b : f.pair.a) + ") runs=" + f.pair.runs
          + " -> JS restriped P=" + f.P);
      }
    }
  });

  // FIX 2c — frame UNIONS + info rect. MainWin_build derives +0xD4C/+0xD5C/+0xD6C
  // from the (now scaled) seeds with its own NATIVE +-3/+-4 arithmetic, so the
  // channel between the buttons and the engraved frame strokes stayed ~1px at
  // every g (user-flagged 2026-08-12; measured: stroke at cell-3, native pad).
  // Overwrite the three rects with the law values (SL.editorPanelSeeds pal_union/
  // red_union/info l,t,b) at PAINTER entry — after every engine rebuild, before
  // the frames draw @0x45BCCF/EE and painter_editor_info consumes +0xD6C. The
  // info rect's RIGHT edge stays the engine's (follows the live M/T/I seed,
  // already scaled). Idempotent per frame; g<=16 or mode!=0x3EA -> untouched.
  let unionLoggedG = 0;
  Interceptor.attach(VA(0x45BC50), {          // MainWin_draw_center_mode (thiscall)
    onEnter() {
      const self = this.context.ecx;
      let mode = -1;
      try { mode = self.add(0x1E8FC).readS32(); } catch (e) { return; }
      if (mode !== 0x3EA) return;
      const g = currentG();
      if (g <= 16) return;
      const s = SL.editorPanelSeeds(g);
      const wr4 = (p, r) => { p.writeS32(r[0]); p.add(4).writeS32(r[1]);
                              p.add(8).writeS32(r[2]); p.add(12).writeS32(r[3]); };
      wr4(self.add(0xD4C), s.palUnion);
      wr4(self.add(0xD5C), s.redUnion);
      const info = self.add(0xD6C);
      info.writeS32(s.infoLeft); info.add(4).writeS32(s.infoTop);
      info.add(12).writeS32(s.infoBottom);      // +8 (right) = engine's, already scaled
      if (DIAG && unionLoggedG !== g) {
        unionLoggedG = g;
        log("[union] g=" + g + " pal=(" + s.palUnion + ") red=(" + s.redUnion
          + ") info l/t/b=" + s.infoLeft + "/" + s.infoTop + "/" + s.infoBottom
          + " (right kept=" + info.add(8).readS32() + ")");
      }
    }
  });

  // FIX 2d — info-text LINE STEP. painter_editor_info advances y by
  // Buffer_text_line_height (native 13); with the fonts imm-scaled to su(10,g)
  // the step became the scaled font's OWN metric — sublinear (29 @g=40 vs
  // lawful 32), orphaning the bottom margin at 4K while g=25 landed snug by
  // accident ([[feedback-font-metric-sublinearity]], user-flagged 2026-08-12).
  // Substitute the law step su(13,g) (= SL.editorPanelSeeds().infoStep) for
  // line-height calls INSIDE the painter only; g<=16 -> live metric (identity).
  let inInfoPainter = false;
  Interceptor.attach(VA(0x45B550), {          // painter_editor_info
    onEnter() { inInfoPainter = true; },
    onLeave() { inInfoPainter = false; }
  });
  Interceptor.attach(VA(0x5DCAB0), {          // Buffer_text_line_height
    onLeave(retval) {
      if (!inInfoPainter) return;
      const g = currentG();
      if (g <= 16) return;
      retval.replace(ptr(su(13, g)));
    }
  });

  // Diplo bottom buttons: raise the popup-active DEPTH refcount (pcave2 g_popup_active
  // @0xA0C530) across DiploEditWin_exec so thunk_btn_gate says "zoom" — the baked
  // FlatButton pipeline back-computes native dims (ceil(dev*16/g): 465x50 -> exactly
  // 186x20 vanilla), renders bar+label native, and NN-zooms x(g/16). Refcount (not
  // bool) so popups nested inside the modal stay correct.
  const G_POPUP_ACTIVE = VA(0xA0C530);
  const find_font = new NativeFunction(VA(0x5882F0), 'pointer', ['int', 'int']);
  let scaledBtnFont = null;
  let winThis = null;                    // DiploEditWin this-ptr (ecx @0x4DB080), for DIAG bar sampling
  // Font line height = [f+0x10]+[f] (if [f]>=0) else [f+0xc]  (Buffer_text_line_height 0x5DCAB0)
  const lineHeight = f => {
    if (f.isNull()) return -1;
    const f0 = f.readS32();
    return f0 >= 0 ? f.add(0x10).readS32() + f0 : f.add(0xc).readS32();
  };
  Interceptor.attach(VA(0x4DB080), {
    onEnter() {
      const g = currentG();
      this.armed = g > 16;
      winThis = this.context.ecx;
      if (this.armed) {
        diploActive = true;
        G_POPUP_ACTIVE.writeU32(G_POPUP_ACTIVE.readU32() + 1);
        scaledBtnFont = find_font(su(14, g), 1);   // ready before any button builds
        log("[diplo] exec enter — popup_active -> " + G_POPUP_ACTIVE.readU32()
          + "  btnfont=find_font(" + su(14, g) + ",1)=" + scaledBtnFont);
        if (DIAG) {
          // Row pitch = line height of the dialog font (popup_list_rowheight -> Buffer_text_line_height).
          // Compare native vs scaled to see if the pitch is proportionate or sublinear.
          const span = su(370, g) - su(31, g);
          for (const flag of [0, 1]) {
            const lhN = lineHeight(find_font(14, flag));
            const lhS = lineHeight(find_font(su(14, g), flag));
            log("[pitch] flag=" + flag + " nativeLH=" + lhN + " scaledLH=" + lhS
              + " scale_px(nativeLH)=" + su(lhN, g) + "  ->13rows=" + (13 * lhS)
              + " vs container span=" + span + " (fill " + (100 * 13 * lhS / span).toFixed(0)
              + "%, headroom " + (span - 13 * lhS) + "px)");
          }
        }
      }
    },
    onLeave() {
      if (this.armed) {
        const v = G_POPUP_ACTIVE.readU32();
        if (v > 0) G_POPUP_ACTIVE.writeU32(v - 1);
        scaledBtnFont = null;
        diploActive = false;
        log("[diplo] exec leave — popup_active -> " + G_POPUP_ACTIVE.readU32());
      }
    }
  });

  // Diplo BUTTON LABEL font — stamp font0 (button+0x970) at each button's BUILD-TIME
  // redraw site, BEFORE the (only) render runs. The bar zooms via btn_shrink/2dscale
  // (popup_active armed here); the label writer (Buffer_wrap_cent_4 @0x608441) draws
  // AFTER the 2dscale onto the scaled canvas using font0 — native/tiny unless swapped.
  // The buttons draw ONCE at build (call [eax+0xf8] right after BaseButton_init) and
  // the modal loop never redraws them (DiploEditWin_update only touches CheckList items,
  // content_draw sets no font), so a post-build stamp was never used. These 4 sites are
  // COLD (diplo-only) — no hot-function instrumentation, so startup/cinematic untouched.
  const REDRAW_SITES = [
    { va: 0x4DB6EF, btn: 0x4df8, what: "Atrocity" },
    { va: 0x4DB756, btn: 0x42ac, what: "Integrity" },
    { va: 0x4DB7BB, btn: 0x3760, what: "Clear" },
    { va: 0x4DB822, btn: 0x20c8, what: "OK" },
  ];
  for (const s of REDRAW_SITES) {
    Interceptor.attach(VA(s.va), {
      onEnter() {
        if (!scaledBtnFont) return;
        const btn = this.context.edi;   // edi = button this-ptr at the redraw call
        btn.add(0x970).writePointer(scaledBtnFont);
        log("[btnfont] " + s.what + " font0<-scaled @redraw");
      }
    });
  }

  // ==================== DIAG (verify geometry + banding; strip after) ====================
  // Answers the two open questions with runtime ground truth, not static reasoning:
  //   (1) do the 4 buttons ride too low?  -> BaseButton_init args (leftX/topY/w/h) vs window H
  //   (2) do the checkbox rows under-fill the scaled container?  -> CheckList object dump
  //   (3) do the button bars band?  -> run-length of a bar column, palette-resolved
  // All three hook COLD sites (diplo-modal-only) -> no cinematic/hot-fn instrumentation.
  const PAL = VA(0x94C590);              // g_main_palette PALETTEENTRY[256] (r,g,b,flags)
  function rgb(idx) {
    const p = PAL.add(idx * 4);
    return p.readU8() + "," + p.add(1).readU8() + "," + p.add(2).readU8();
  }
  // Button embedded Buffer @ btn+0x444: data@+0x54 w@+0x80 h@+0x84(neg) stride@+0x4a8.
  function sampleBar(btn, label) {
    const data = btn.add(0x498).readPointer();
    const w = btn.add(0x4c4).readS32();
    let h = btn.add(0x4c8).readS32(); if (h < 0) h = -h;
    const stride = btn.add(0x8ec).readS32();
    if (w <= 0 || h <= 0 || h > 4000 || data.isNull()) { log(label + " (bad dims w=" + w + " h=" + h + ")"); return; }
    const x = w >> 1;
    let out = label + " w=" + w + " h=" + h + " stride=" + stride + " col@x=" + x + " |";
    let prev = -1, cnt = 0;
    const push = () => { if (prev >= 0) out += " " + prev.toString(16) + "(" + rgb(prev) + ")x" + cnt; };
    for (let y = 0; y < h; y++) {
      const idx = data.add(y * stride + x).readU8();
      if (idx === prev) cnt++; else { push(); prev = idx; cnt = 1; }
    }
    push();
    log(out);
  }

  if (DIAG) {
    // (1) button rects — BaseButton_init 0x607210 call sites (cold). Interceptor fires
    //     BEFORE the call executes, so args start at [esp] (no ret addr pushed yet):
    //     [esp+8]=leftX [esp+0xc]=topY [esp+0x10]=w [esp+0x14]=h (window-local).
    const BTN_INIT_SITES = [
      { va: 0x4DB6E6, what: "Atrocity" }, { va: 0x4DB74D, what: "Integrity" },
      { va: 0x4DB7B4, what: "Clear" },    { va: 0x4DB81B, what: "OK" },
    ];
    for (const s of BTN_INIT_SITES) {
      Interceptor.attach(VA(s.va), {
        onEnter() {
          if (!diploActive) return;
          const sp = this.context.esp;
          const lx = sp.add(0x8).readS32(), ty = sp.add(0xc).readS32();
          const w = sp.add(0x10).readS32(), h = sp.add(0x14).readS32();
          const H = su(398, currentG());
          log("[btnrect] " + s.what + " x=" + lx + " y=" + ty + " w=" + w + " h=" + h
            + "  topY/H=" + (ty / H).toFixed(4) + " (vanilla 374/398=0.9397) botGap=" + (H - (ty + h)));
        }
      });
    }

    // (2) banding — sample each button bar column at DiploEditWin_update (0x4DADA0, cold,
    //     modal-loop only; the built+zoomed bars persist in each button's embedded Buffer).
    const BTN_OFFS = [
      { off: 0x4df8, what: "Atrocity" }, { off: 0x42ac, what: "Integrity" },
      { off: 0x3760, what: "Clear" },    { off: 0x20c8, what: "OK" },
    ];
    let barsSampled = false;
    Interceptor.attach(VA(0x4DADA0), {          // DiploEditWin_update, ecx=win (== winThis)
      onEnter() {
        if (!diploActive || barsSampled || !winThis) return;
        barsSampled = true;
        for (const b of BTN_OFFS) sampleBar(winThis.add(b.off), "[band] " + b.what);
      }
    });
  }

  log("hooks installed: seed-rewrite @0x45B0ED, palette/red btn_gate HIT override @0xA169E0,"
    + " union/info-rect law write @0x45BC50, info line-step su(13,g) @0x5DCAB0,"
    + " face-stripe detect/restripe @thunk_btn_stripes 0xA0EFD0,"
    + " diplo btn-zoom bracket @0x4DB080, 4 cold btnfont redraw-site hooks (g>16 only)"
    + (DIAG ? " + DIAG (rects/chklist/bands/gate/union/stripe)" : ""));
}
