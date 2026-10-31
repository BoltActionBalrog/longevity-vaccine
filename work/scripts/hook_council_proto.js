// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// ===========================================================================
// hook_council_proto.js — PLANETARY COUNCIL screen scaling PROTOTYPE v1.
// Phase 1: geometry + fonts + portrait/logo sprite zoom + text placement.
// (Phase 2 — frame thickness K + chip/backdrop fill device-density restripe
//  via the baked box_thick family — comes after geometry verifies.)
//
// Laws: scaling_laws.py council_* section (this file is a PORT; the sweep in
// tests\test_scaling_council.py pins every rect).  All sc() = fl(v*g/16),
// identity + zero patches at g<=16.
//
// LEVERS
//  S  seed table: STUB + call_target_redirect of the Font_init E8 @0x427784
//     (first call after the merge; ESI=CWIN there; nothing in
//     0x427661..0x427784 reads the seed fields — that stretch only copies
//     conRect into propBox 0xBB4, which the seed set skips).  The stub emits
//     63 absolute `mov [esi+disp32],imm32` writes (council_seed_rects,
//     position fl + pinned size) then tail-jmps the real 0x618F40.
//     WHY NOT AN ATTACH: runs 3-5 proved a mid-function onEnter-only attach
//     permanently replaces [esp]-at-the-hook with a Frida island pointer
//     (0x2eX0b0f family, hazard #2/#7 signature) — at 0x427661 that slot is
//     a live exec-frame dword; at 0x426b25 it was repaint's saved-EDI slot
//     (the run-3/4/5 crash chain).  NO mid-function Interceptor, ever.
//  I  imm rewrites (Memory.patchCode at first exec entry, g>16 only):
//     button-row 3/4/0x14 constants, window 0x32C/0x18B/0x30C, the six
//     Font_init sizes + the b04 line pad, painter 3/4/10/0x14/2 constants,
//     repaint 4/0x17/3 + banner 3.
//  B  repaint backdrop right inset 0x37: imm8 can't hold sc(0x37)=137 ->
//     STUB + redirect of the Buffer_box_sprite E8 @0x426b4e.  The rect goes
//     by pointer ([esp+4] at stub entry, [ebp-0x10] at the site); the stub
//     does `sub dword [rect+8], dp(0x37)-0x37` then tail-jmps 0x5E2DD3
//     (the baked hud_boxframe detour there executes normally — same shape
//     as lever P over the sd2 detour).
//  P  portrait/logo Sprite_draw_2 call sites 0x425F3C/0x426105: runtime
//     call_target_redirect (NO Interceptor — Sprite_draw_2's entry carries
//     the baked portrait_avg detour, hazard #7 forbids hooking its call
//     sites) to hand-assembled RWX stubs: num/den -> g/16, x/y PASS THROUGH
//     (v6: the v5 run proved this sd2 path draws AT the args — num/den only
//     zooms content; the args are already device); logo re-centered by
//     (cw - dp(cw))/2; stub tail-jmps the real entry (detour intact).
//  T  leader-name y: the +4 lea chains the NATIVE [portrait+0x1c] — every
//     candidate attach sits between arg pushes (hazard #2), so the
//     set_text_color call @0x425F83 is call_target_redirected to a stub
//     that rewrites [ebp+8] = [ebp-0x14] + dp(ph) + sc(4) (EBX=faction,
//     ESI=CouncilWin live) then tail-jmps 0x5DACB0.  Line 2 + the logo y
//     chain off [ebp+8], so one fix covers all three.
//  G  v7 button FACE art (the run-7 "button art"): the 6 CouncilWin
//     FlatButtons render their 9-slice with the ctor-DEFAULT pieces (only
//     T/TL/TR exist, 67x20/3x20/3x20 native) so the face is a native 20px
//     bar at the top of the 50px scaled rect — the EXACT defect class the
//     baked popup_button_2dzoom pipeline solves (patches.yaml quote: "20-dev-
//     px bar at the top of a 50px button").  thunk_btn_shrink (entry detour
//     at FlatButton_content_draw 0x607E7F, body @pcave2+0x400) gates on an
//     E8 to thunk_btn_gate_pre (@pcave2+0xC080); council-session buttons are
//     not popup-armed (no exec_3 modal), so it never fires.  Lever G
//     call_target_redirects that E8 (@0xA0C40B, live-bytes verified first)
//     to a stub: HIT (eax=1) when ESI is one of the 6 buttons
//     [CWIN+0xD94, +6*0xB4C), else tail-jmp the original gate_pre.  The
//     armed pipeline renders the bar native, KSB-zooms to device, and
//     thunk_btn_stripes restripes the dither at device density (the proven
//     path of every popup OK/CANCEL button — dither invariant included).
//  V  v8/v9 Cast-a-Vote (#GOVVOTE "Eligible Candidates") modal:
//     (a) ART POSITION (v9): the UN-flag art rides t_dp_artalign ->
//         thunk_popup_artalign, whose y law is QUOTE-BOX semantics
//         (g_field_anchor) — on GOVVOTE it lands the art overlapping the
//         title band.  Art SIZE is already lawful (native ~200x120 x g/16;
//         pristine 4K = x45/16 unclamped = 556 confirms the native).  The
//         x/y SEEDS handed to [popup+0x3168] are DEVICE-scaled already
//         (run-8 proof: [30e8]=117=dp(38)+dp(9), baked header_reserve_
//         resume; v8's dp(seed-5)+5 double-scaled — art at winT+277).  Fix
//         = per-INSTANCE [popup+0x3168] override to a PASS-THROUGH stub:
//         gated popup -> thunk_sprite_draw 0x6688B0 with args untouched
//         (the engine's own seeds reproduce the pristine relations: flush-
//         left with the rows, tucked under the band); non-matching [esp+8]
//         -> t_dp_artalign 0xA1E6E8 (original chain).  The engine store
//         @0x404BDE is SKIP-IF-SET, so the arming attach RESTORES
//         t_dp_artalign on any non-matching popup carrying the stub
//         (heap-ptr reuse safety).
//         v13 + SCANLINE RESTRIPE: the flag field is 1px scanline dither
//         built at the 1024 baseline; the sd2 num/16 NN zoom bands it at
//         fractional g (run-12, g=25).  The prior modal-class image fix
//         (thunk_portrait_avg bilinear @ the 0x5E4B4A entry) gates on
//         dest==0x940824 (faction-quote buffer) — the user's "branch-
//         specific" hunch, confirmed — and bilinear is wrong for scanlines
//         anyway (vanilla BUILDS the flag at device size = crisp 1px
//         rows).  The armed stub now CALLS thunk_sprite_draw (re-pushed
//         args, add esp,0x14 — it is plain-RET) then rewrites the PAIR
//         pixels of the drawn rect ((x-5,y-6), ceil(src*g/16)) at 1px
//         device pitch; pair colors read from src art rows 0/1 (content-
//         derived); logo/laurel pixels untouched; g<=16 identity.
//     (b) EMPTY-TEXT FRAME HIDE (deliberate divergence from vanilla, THIS
//         popup only, all resolutions): art popups with a list skip the
//         UnionRect ([+0x2144]!=0 @0x4061d0) so BOTH frame draws box the
//         empty body-text rect — d528 E8 @0x406154 (-> thunk_d528_inset
//         0xA0C620) and final d5a0 E8 @0x406238 (-> thunk_content_frame
//         0x668BD0).  Both E8s are live-byte verified then redirected to
//         stubs: esi==g_gv_popup -> RET 8 (Buffer_box_sprite 0x5E2DD3 is
//         callee-clean; vanilla disasm shows no add esp,8 after either
//         site), else tail-jmp the baked thunk verbatim.
//     ARMING: Interceptor at Popup_on_draw_background ENTRY 0x405C80
//     (fastcall this=ecx; prologue 55 8B EC... verified clean in the built
//     exe, PRACX-clean, no yaml site near entry): title [+0xa48]
//     case-insens == "eligible candidates" (CharUpperA uppercases in place
//     after draw 1) && art [+0x2144]!=0 -> g_gv_popup=this + install the
//     art stub; else clear/restore.  Strokes draw INSIDE the same call
//     after onEnter, art draws after return — per-draw arming is
//     synchronous with both consumers.
//  F  v10/v11 PHASE 2 frames/dither: the 9 CouncilWin-dest Buffer_box_
//     sprite E8 sites, live-verified then call_target_redirected.
//     d528 sites @0x425EE9/0x426286/0x426BD2 -> thunk_box_thick_devfill
//     0xA102A0; d5a0 @0x426B7B -> thunk_box_thick_hollow_flat 0xA0C140;
//     d690 backdrop @0x426B4E rides stubB, whose tail is now devfill.
//     CHIP sites (da00 @0x4261AA, d9d8 @0x4261D6, da28 @0x426203/0x426230/
//     0x42625C) -> stubChip (v11): the chip bevel is 2-3 NATIVE px
//     (pristine Vote.png measured), so devfill's popup-tuned K/K+1 STEP2
//     inset tiled INSIDE the scaled bevel — run-10's "color artifacting on
//     the left/right of the abstain element" (stripe rows overwriting the
//     bevel's inner columns; top/bottom invisible, stripes run parallel).
//     stubChip ORDER-SWAPS instead of chasing the centre-aligned-NN bevel
//     edge: (1) fill = Buffer_box_sprite(dest, K/K+1-inset rect, borders-
//     NULLED params copy) — STEP2's own mechanism, a 1:1 device-density
//     tile (dither invariant); (2) frame = hollow_flat(dest, ORIGINAL
//     rect, fill-NULLED params copy) — the thick bevel draws OVER the tile
//     edge; (3) v12 MASK pass — the chip border pieces are FAT (thin bevel
//     + interior PADDING; vanilla Buffer_tile_masks the fill over each
//     piece, decompile 0x5E2DD3), so the fill-nulled frame pass exposed
//     raw padding (run-11 "massive white outlines", flat 0xC0 grey):
//     Buffer_tile_mask 0x5DA6C0 (fill, L,T, L,T, w,h, params[9]) over the
//     WHOLE rect re-masks the padding with the 1:1 device fill; bevel +
//     center stripes are not the mask color and stay; tile phase is dest-
//     anchored (box_sprite passes pos==phase) so all passes align.
//     Routing is STATIC per site
//     (never dispatch on [params+0x20] — chip fills are lazy-built, null
//     pre-first-draw).  The 3 console-dest sites (ecx=0x7AEC64) stay with
//     the baked hud_frames machinery.  Judge dither at g=22/25.
//
// ATTACH AUDIT 2026-08-22 v5 (v8: + 0x405C80 Popup_on_draw_background entry,
// diff-verified clean): Interceptor set = FUNCTION ENTRIES ONLY, all
// diff-verified pristine (no baked detours): 0x427230 exec, 0x426AA0 repaint,
// 0x426FA0 show_hide, 0x425DB0 draw_column, 0x426470 draw_proposal.  The v2-v4
// mid-function attaches (0x427661 seed / 0x426b25 blever / 0x426FC0 preloop)
// are GONE — each permanently replaced its [esp]-at-hook slot with a Frida
// island pointer (0x2eX0b0f, page offset constant across runs; caught
// red-handed by canary2 at prop-in in runs 4+5; the post-vote AV @0x5d6ad4
// was the exec-frame slot poisoned by the seed attach).  Everything else is
// imm/rel32 BYTE patching — call_target_redirect, no trampolines anywhere in
// the draw chain.
// ===========================================================================
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_council_proto.log";
log("=== hook_council_proto.js v28 (talk popups: v25 fixes A [textfollow ornate bypass] + B [artalign x + ornate inset delta] + v26 B-y [fieldpads engine-T arm for ornate] + v27 C [ornate field R anchored to the drawn band] USER-VERIFIED 'positioning perfect'; + fix D = popup leader-portrait parity-reblit tail at thunk_sprite_draw (measured engine rect) for the bribe-screen banding) ===");
const LEVER_SEEDS = true, LEVER_IMMS = true, LEVER_BACKDROP37 = true,
      LEVER_SPRITES = true, LEVER_TEXTY = true, LEVER_BTNGATE = true,
      LEVER_CASTVOTE = true, LEVER_FRAMES = true;

// 2026-08-22 BAKED as group council_scale (build 1a2da25b, src assemble_council.py).
// This prototype is HISTORY: on the baked exe the seed-table site 0x427784 no
// longer calls Font_init, so refuse to arm (double-application would re-redirect
// the baked E8s to Frida stubs and detach the parity-reblit tails).
function bakedGuard() {
  try {
    const site = VA(0x00427784);
    const tgt = (site.add(1).readS32() + site.toUInt32() + 5) >>> 0;
    if (site.readU8() !== 0xE8 || tgt !== 0x00618F40) {
      log("=== hook_council_proto.js: BAKED exe detected (0x427784 -> 0x" + tgt.toString(16) +
          ", not Font_init) — prototype DISABLED; the council arc ships in patches.yaml group council_scale ===");
      return false;
    }
  } catch (e) { log("bakedGuard err " + e); return false; }
  return true;
}
if (requireBase() && bakedGuard()) {
  const CWIN = 0x006FEC80;
  const A_G = 0x00668740, A_SW = 0x009B7B1C, A_SH = 0x009B7B20, A_STRIP = 0x007AF59C;
  const A_GOV = 0x009a6614;

  const g = () => { try { return VA(A_G).readU32(); } catch (e) { return 16; } };
  const dp = (v) => { const s = g(); return s <= 16 ? v : Math.floor(v * s / 16); };
  const rd = (p, o) => ptr(p).add(o).readS32();
  const env = () => "g=" + g() + " SW=" + VA(A_SW).readS32() + " SH=" + VA(A_SH).readS32() +
                    " strip=" + VA(A_STRIP).readS32();
  const cw = VA(CWIN);
  const rect4 = (p) => p.readS32() + "," + p.add(4).readS32() + "," + p.add(8).readS32() + "," + p.add(12).readS32();

  // ---- vptr integrity checkpoints (crash forensics 2026-08-22) ------------
  // AV @0x426fd3: show_hide's loop `call [vptr+4]` on the 6 FlatButtons at
  // CWIN+0xD94 (+k*0xB4C) hit a garbage vptr.  Exec's own head virtual-calls
  // all six successfully, so the stomp lands between mid-exec and show.
  // Log the six vptrs at each checkpoint; at show entry, repair any outlier
  // to the majority vtable (and dump the stomped bytes) so the run survives.
  const FB0 = 0xD94, FBSTRIDE = 0xB4C;
  function vptrs() {
    const v = [];
    for (let k = 0; k < 6; k++) v.push(rd(cw, FB0 + k * FBSTRIDE) >>> 0);
    return v;
  }
  const counts = {}, seen = {};
  function ckpt(tag) {
    try {
      L("vptr:" + tag, vptrs().map(x => "0x" + x.toString(16)).join(" "), 8);
    } catch (e) { L("vptr:" + tag, "err " + e, 8); }
  }
  // detect + repair + forensic-dump; returns true if a stomp was found
  let vtblGood = 0;
  function repairStomp(tag) {
    try {
      const v = vptrs();
      if (!vtblGood) {
        // learn the healthy vtable from the first checkpoint (all six agree)
        if (v.every(x => x === v[0])) vtblGood = v[0];
        return false;
      }
      let bad = false;
      for (let k = 0; k < 6; k++) {
        if (v[k] === vtblGood) continue;
        bad = true;
        const fb = cw.add(FB0 + k * FBSTRIDE);
        log("[STOMP@" + tag + "] flatbtn" + k + " vptr=0x" + v[k].toString(16) +
            " (good 0x" + vtblGood.toString(16) + ")");
        log(hexdump(fb.sub(0x20), { length: 0x60, header: true, ansi: false }));
        fb.writeU32(vtblGood);
      }
      return bad;
    } catch (e) { log("[STOMP@" + tag + "] err " + e); return false; }
  }

  // rich AV handler (frida_common's installAVHandler lacks registers)
  Process.setExceptionHandler(function (details) {
    if (details.type !== "access-violation") return false;
    try {
      const c = details.context;
      log("=== ACCESS VIOLATION (council_proto v28) ===");
      try {
        log("  mem: " + details.memory.operation + " @0x" +
            u32(details.memory.address).toString(16));
      } catch (e) {}
      for (const r of ["eip", "esp", "ebp", "eax", "ebx", "ecx", "edx", "esi", "edi"])
        log("  " + r + "=0x" + u32(c[r]).toString(16));
      try {
        const hex = Array.from(new Uint8Array(c.eip.readByteArray(16)))
          .map(b => b.toString(16).padStart(2, "0")).join(" ");
        log("  bytes@eip: " + hex);
      } catch (e) {}
      for (let i = 0; i < 12; i++) {
        try {
          log("  [esp+0x" + (i * 4).toString(16) + "] = 0x" +
              c.esp.add(i * 4).readU32().toString(16));
        } catch (e) {}
      }
      // council forensics: vptrs + the flatbtn EDI points into (if any)
      try {
        log("  vptrs: " + vptrs().map(x => "0x" + x.toString(16)).join(" "));
        const d = u32(c.edi) - (cw.toUInt32() + FB0);
        if (d >= 0 && d < 6 * FBSTRIDE)
          log("  edi = flatbtn" + Math.floor(d / FBSTRIDE) + "+0x" +
              (d % FBSTRIDE).toString(16) + "\n" +
              hexdump(c.edi.sub(0x20), { length: 0x60, header: true, ansi: false }));
      } catch (e) {}
    } catch (e) {}
    return false; // let the OS terminate
  });
  function L(tag, msg, limit) {
    limit = limit || 40; counts[tag] = counts[tag] || 0;
    const key = tag + "|" + msg; if (seen[key]) return;
    if (counts[tag] >= limit) return;
    seen[key] = 1; counts[tag]++; log("[" + tag + "] " + msg);
  }

  // ---- I: immediate rewrite table -----------------------------------------
  // kinds: i8 (unsigned-encode signed byte), i32 (little-endian dword)
  function IMMS() {
    const s3 = dp(3), s4 = dp(4), s17 = dp(0x17), band = s17 - s3;
    return [
      // exec: console-rect insets + button-row derivation
      [0x42768b + 2, "i8", s4], [0x427690 + 1, "i32", -s4], [0x42769d + 2, "i8", s4],
      [0x4276b9 + 2, "i8", s3], [0x4276bc + 2, "i8", s3],
      [0x4276c2 + 2, "i8", -band], [0x4276c8 + 2, "i8", s3], [0x4276cb + 2, "i8", -s3],
      [0x4276ef + 2, "i8", s3], [0x427726 + 2, "i8", s3], [0x427751 + 2, "i8", s3],
      // window init
      [0x4279c4 + 3, "i32", dp(0x18B)], [0x4279cb + 2, "i32", dp(0x18B)],
      [0x4279db + 1, "i32", -dp(0x30C)], [0x427a14 + 1, "i32", dp(0x32C)],
      // fonts (push imm8 sizes; b7c=20, adc/ab4/b54=14, b04/b2c=12) + b04 pad 5
      [0x427760 + 1, "i8", dp(20)], [0x427791 + 1, "i8", dp(14)], [0x4277a7 + 1, "i8", dp(14)],
      [0x4277bc + 1, "i8", dp(12)], [0x4277dc + 1, "i8", dp(12)], [0x4277f2 + 1, "i8", dp(14)],
      [0x4277ca + 6, "i32", dp(5)],
      // column painter: logo gap 10, chip 3/3/3/-0x14, votes lift 0x14
      // (name-y +4 is owned by the texty stub — it rewrites [ebp+8] whole)
      [0x4260ad + 3, "i8", dp(10)],
      [0x426116 + 2, "i8", s3], [0x42611f + 2, "i8", s3], [0x42612f + 2, "i8", s3],
      [0x426132 + 2, "i8", -band], [0x42637e + 1, "i32", band],
      // proposal painter: header band 0x14, +2, body 3, tally 2/2
      [0x4264c2 + 2, "i8", dp(0x14)], [0x42659a + 2, "i8", dp(2)],
      [0x4265b6 + 1, "i32", s3], [0x426743 + 2, "i8", dp(2)], [0x426746 + 2, "i8", dp(2)],
      // repaint: console-box 4s, backdrop L 0x17 + inner 4, banner 3
      [0x426aee + 2, "i8", s4], [0x426afc + 2, "i8", s4], [0x426aff + 2, "i8", s4],
      [0x426b02 + 2, "i8", s4], [0x426b3a + 3, "i32", dp(0x17)], [0x426b5c + 1, "i32", s4],
      [0x426bdd + 1, "i32", s3],
    ];
  }
  let immsApplied = false, stubsBuilt = false;
  function applyImms() {
    if (g() <= 16) return;
    if (!immsApplied) {
      immsApplied = true;
      if (LEVER_IMMS) {
        // live-bytes pre-dump: catch any baked/PRACX rewrite at our sites
        // (the imm audit was done against the PRISTINE Ghidra project)
        for (const [va] of IMMS()) {
          try {
            const b = Array.from(new Uint8Array(VA(va).sub(4).readByteArray(12)))
              .map(x => x.toString(16).padStart(2, "0")).join(" ");
            log("[live] 0x" + (va - 4).toString(16) + ": " + b);
          } catch (e) {}
        }
        let n = 0;
        for (const [va, kind, val] of IMMS()) {
          try {
            Memory.patchCode(VA(va), 4, (code) => {
              if (kind === "i8") code.writeU8(val & 0xFF);
              else code.writeS32(val);
            });
            n++;
          } catch (e) { L("imm", "FAIL 0x" + va.toString(16) + ": " + e); }
        }
        L("imm", "applied " + n + "/" + IMMS().length + " " + env());
      }
    }
    if (!stubsBuilt) {
      stubsBuilt = true;
      try { buildStubs(); }
      catch (e) { log("[stub] BUILD FAIL: " + e + "\n" + (e.stack || "")); }
    }
  }

  // ---- P + T: hand-assembled stubs + call_target_redirects ----------------
  // (no Interceptor anywhere in the draw chain — see the audit header)
  function le32(v) { return [v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF]; }

  // lever V shared state (set by buildStubs, read by the 0x405C80 attach)
  const T_DP_ARTALIGN = 0x00A1E6E8;     // pcave2+0x126e8, the [popup+0x3168] chain head
  let gvMemPtr = null, stubArtAddr = 0, pdMemPtr = null;

  function buildStubs() {
    const gAddr = VA(0x00668740).toUInt32();
    const govAddr = VA(0x009a6614).toUInt32();
    const sd2 = VA(0x005E4B4A).toUInt32();
    const stc = VA(0x005DACB0).toUInt32();
    const fontInit = VA(0x00618F40).toUInt32();
    const boxSprite = VA(0x005E2DD3).toUInt32();
    const DEVFILL = 0x00A102A0;      // thunk_box_thick_devfill  (pcave2+0x42A0)
    const HOLLOWFLAT = 0x00A0C140;   // thunk_box_thick_hollow_flat (pcave2+0x140)
    const TILEMASK = 0x005DA6C0;     // Buffer_tile_mask (thiscall, 8 args, RET 0x20)
    const page = Memory.alloc(Process.pageSize);
    globalThis._councilStubs = page;             // retain — alloc frees on GC
    const base = page.toUInt32();
    // v17 gv flag-restripe LUTs (DEST-space pairs, MEASURED): the canvas
    // manager shifts every PCX index +10 mod 256 on load (the 10 reserved
    // Windows system-palette slots; proven by hof_*.pcx runtime-palette
    // dumps + the [sd1] dest histogram).  council_sm.pcx pair census
    // (odd row = bright, even = dark; globally phase-coherent):
    //   field  250->230 x7575 (98%)  -> dest 0x04 <-> 0xF0
    //   logo   245->33  x763 (100%)  -> dest 0xFF <-> 0x2B
    //   laurel  64->36  x358 (100%)  -> dest 0x4A <-> 0x2E
    // EXCLUDED per dither-pair-ambiguity: pcx 180 (dest 0xBE) mates 50/50
    // with 0xF0/0x51 — left identity (residue ~460px logo-edge shading).
    // toBright at +0 (even rect rows), toDark at +0x100; page-aligned base
    // has bit 8 clear so `xor ebx,0x100` toggles between them.
    const lutPage = Memory.alloc(Process.pageSize);
    globalThis._councilLuts = lutPage;
    const lutBright = lutPage.toUInt32();
    {
      const tb = new Array(256), td = new Array(256);
      for (let i = 0; i < 256; i++) { tb[i] = i; td[i] = i; }
      tb[0xF0] = 0x04; tb[0x2B] = 0xFF; tb[0x2E] = 0x4A;
      td[0x04] = 0xF0; td[0xFF] = 0x2B; td[0x4A] = 0x2E;
      lutPage.writeByteArray(tb);
      lutPage.add(0x100).writeByteArray(td);
    }
    let off = 0;
    const put = (bytes) => { page.add(off).writeByteArray(bytes); off += bytes.length; };
    const here = () => base + off;
    function jmpTo(target) {
      const rel = target - (here() + 5);
      put([0xE9, ...le32(rel)]);
    }

    // -- portrait stub --
    // v6: NO x/y descale.  The v5 run proved this sd2 path draws AT the x/y
    // args unmodified (portraits landed at exactly x*16/g device — bunched
    // 0.4x left); num/den only zooms the sprite content.  The caller's args
    // are already device-space (seed rects) — pass them through, set only
    // num=g, den=16.
    // v23: the dither-regeneration tail is a Frida attach AT THIS STUB's
    // entry (armReblit) — the pcBits sd2 path blits inside
    // Sprite_blit_scaled_core's own pixel loop, so no downstream Buffer_*
    // primitive can be intercepted (v22's marker proved it: consumed by an
    // unrelated button-face StretchBlt).
    const stubPortrait = here();
    put([0x51]);                                 // push ecx
    put([0x8B, 0x0D, ...le32(gAddr)]);           // mov ecx,[g]
    put([0x89, 0x4C, 0x24, 0x18]);               // num = g
    put([0xC7, 0x44, 0x24, 0x1C, 0x10, 0, 0, 0]);// den = 16
    put([0x59]);
    jmpTo(sd2);

    // -- logo stub: recenter x by (cw - dp(cw))/2 (the caller centers with
    //    the NATIVE canvas width; drawn width is dp(cw), so shift left by
    //    half the growth).  v6: no x/y descale here either. --
    const stubLogo = here();
    put([0x51]);                                 // push ecx (sprite)
    put([0x8B, 0x0D, ...le32(gAddr)]);           // mov ecx,[g]
    put([0x8B, 0x04, 0x24]);                     // mov eax,[esp]      (sprite)
    put([0x8B, 0x40, 0x18]);                     // mov eax,[eax+0x18] (canvas w)
    put([0x0F, 0xAF, 0xC1]);                     // imul eax,ecx
    put([0xC1, 0xF8, 0x04]);                     // sar eax,4          (dp(cw))
    put([0x8B, 0x14, 0x24]);                     // mov edx,[esp]
    put([0x8B, 0x52, 0x18]);                     // mov edx,[edx+0x18] (cw)
    put([0x2B, 0xD0]);                           // sub edx,eax        (cw-dp(cw), <0)
    put([0xD1, 0xFA]);                           // sar edx,1
    put([0x01, 0x54, 0x24, 0x10]);               // add [esp+0x10],edx (x += delta)
    put([0x89, 0x4C, 0x24, 0x18]);               // num = g
    put([0xC7, 0x44, 0x24, 0x1C, 0x10, 0, 0, 0]);// den = 16
    put([0x59]);
    jmpTo(sd2);

    // -- texty stub (replaces the set_text_color call @0x425F83): rewrite
    //    [ebp+8] = [ebp-0x14] + dp([portrait+0x1c]) + sc(4), then tail-jmp --
    const stubTexty = here();
    put([0xA1, ...le32(govAddr)]);               // mov eax,[gov]
    put([0x31, 0xC9]);                           // xor ecx,ecx
    put([0x39, 0xD8]);                           // cmp eax,ebx (faction)
    put([0x0F, 0x94, 0xC1]);                     // sete cl
    put([0x8D, 0x0C, 0x59]);                     // lea ecx,[ecx+ebx*2]  (idx)
    put([0x8B, 0x84, 0x8E, 0x54, 0x0D, 0, 0]);   // mov eax,[esi+ecx*4+0xd54]
    put([0x8B, 0x40, 0x1C]);                     // mov eax,[eax+0x1c]   (ph)
    put([0x8B, 0x0D, ...le32(gAddr)]);           // mov ecx,[g]
    put([0x0F, 0xAF, 0xC1]);                     // imul eax,ecx
    put([0xC1, 0xF8, 0x04]);                     // sar eax,4            (dp(ph))
    put([0x03, 0x45, 0xEC]);                     // add eax,[ebp-0x14]   (T+1 dev)
    put([0x05, ...le32(dp(4))]);                 // add eax,sc(4)
    put([0x89, 0x45, 0x08]);                     // mov [ebp+8],eax
    put([0x8B, 0xCF]);                           // mov ecx,edi  (0x5DACB0 is
                                                 // THISCALL: site does mov ecx,edi
                                                 // @0x425f7e; we clobbered ecx)
    jmpTo(stc);

    // -- seed stub (replaces the Font_init call @0x427784): 63 absolute
    //    mov [esi+disp32],imm32 writes of the scaled seed table, then
    //    tail-jmp the real Font_init.  Regs/flags untouched (mov only);
    //    idempotent (absolute dp values), so re-exec of the council is fine --
    const stubSeed = here();
    {
      const wr = (disp, val) => put([0xC7, 0x86, ...le32(disp), ...le32(val)]);
      const w = dp(98), h = dp(282), cw3 = dp(120), ch3 = dp(323);
      wr(0xBA4, dp(245)); wr(0xBA8, dp(355)); wr(0xBAC, dp(538)); wr(0xBB0, dp(378));
      wr(0xBC4, dp(30)); wr(0xBCC, dp(750)); wr(0xBD0, dp(27));
      for (let c = 0; c < 7; c++) {
        const oL = dp(OUTER_L[c]), oT = dp(OUTER_T[c]);
        const ow = (c === 3) ? cw3 : w, oh = (c === 3) ? ch3 : h;
        wr(0xBF4 + c * 0x20, oL); wr(0xBF8 + c * 0x20, oT);
        wr(0xBFC + c * 0x20, oL + ow); wr(0xC00 + c * 0x20, oT + oh);
        const iL = dp(INNER_L[c]), iT = dp(29);
        wr(0xC04 + c * 0x20, iL); wr(0xC08 + c * 0x20, iT);
        wr(0xC0C + c * 0x20, iL + w); wr(0xC10 + c * 0x20, iT + h);
      }
    }
    jmpTo(fontInit);

    // -- B stub (replaces the Buffer_box_sprite call @0x426b4e): rect ptr is
    //    at [esp+4]; retarget its right edge W-0x37 -> W-dp(0x37).
    //    v10 (lever F): tail = thunk_box_thick_devfill instead of the native
    //    entry, so the d690 backdrop gets the thick frame + device-density
    //    interior restripe too (the thunk self-gates g<=16 -> native). --
    const stubB = here();
    put([0x50]);                                 // push eax
    put([0x8B, 0x44, 0x24, 0x08]);               // mov eax,[esp+8] (rect ptr)
    put([0x81, 0x68, 0x08, ...le32(dp(0x37) - 0x37)]); // sub dword [eax+8],delta
    put([0x58]);                                 // pop eax
    jmpTo(LEVER_FRAMES ? DEVFILL : boxSprite);

    // -- btnGate stub (v7, lever G): council-session FlatButton HIT wrapper.
    //    Called (E8, bare-RET CALL-helper) from inside the baked
    //    thunk_btn_shrink's pushad bracket with ESI = the button; contract:
    //    clobbers EAX+flags only, ESI preserved.  HIT for the 6 CouncilWin
    //    FlatButtons, else defer to the original thunk_btn_gate_pre verbatim
    //    (its COMMLINK-Council MISS pair + the real v8 gate stay intact). --
    const BTN_LO = cw.add(0xD94).toUInt32();          // buttons[0]
    const BTN_HI = BTN_LO + 6 * 0xB4C;                // past buttons[5]
    const gatePre = VA(0x00A18080).toUInt32();        // pcave2+0xC080
    const stubBtnGate = here();
    put([0x81, 0xFE, ...le32(BTN_LO)]);               // cmp esi, BTN_LO
    put([0x72, 0x0E]);                                // jb  tail
    put([0x81, 0xFE, ...le32(BTN_HI)]);               // cmp esi, BTN_HI
    put([0x73, 0x06]);                                // jae tail
    put([0xB8, 0x01, 0x00, 0x00, 0x00]);              // mov eax,1  (HIT)
    put([0xC3]);                                      // ret
    jmpTo(gatePre);                                   // tail: original gate_pre

    // -- lever V stubs: Cast-a-Vote (GOVVOTE) modal --------------------------
    // g_gv_popup: 4B data slot (never executed — the preceding stub ends in
    // a jmp and every stub is entered only via its redirect).
    const gvMem = here();
    put([0, 0, 0, 0]);
    // g_pd_popup: 4B data slot (v18) — the PROTOCOL DIRECTOR proposal popup,
    // armed per-draw by the same 0x405C80 attach (title match), consumed by
    // stubFlagDraw at thunk_popup_artalign's tail.
    const pdMem = here();
    put([0, 0, 0, 0]);

    // stroke-skip stubs, E8-entered at the two Buffer_box_sprite sites in
    // Popup_on_draw_background (esi = popup at both, vanilla disasm).  Skip
    // = RET 8 (0x5E2DD3 is callee-clean: no add esp,8 after either site);
    // pass = tail-jmp the CURRENT baked target verbatim.
    const dInset = 0x00A0C620;                        // thunk_d528_inset
    const cFrame = 0x00668BD0;                        // thunk_content_frame
    const stubStrokeA = here();
    put([0x3B, 0x35, ...le32(gvMem)]);                // cmp esi,[g_gv_popup]
    put([0x75, 0x03]);                                // jne tail
    put([0xC2, 0x08, 0x00]);                          // ret 8   (skip draw)
    jmpTo(dInset);
    const stubStrokeB = here();
    put([0x3B, 0x35, ...le32(gvMem)]);                // cmp esi,[g_gv_popup]
    put([0x75, 0x03]);                                // jne tail
    put([0xC2, 0x08, 0x00]);                          // ret 8   (skip draw)
    jmpTo(cFrame);

    // art-position stub, installed per-INSTANCE into [popup+0x3168] by the
    // arming attach.  v9 PASS-THROUGH: the RUN-8 [gv] ARMED dump proved the
    // x/y seeds are DEVICE-scaled already (hdr30e8=117 = dp(38)+dp(9) from
    // the baked header_reserve_resume store; m30f0=47 likewise) — v8's
    // dp(seed-5)+5 was a DOUBLE-SCALE (art drew at winT+277, measured 1000,
    // = the double-scale prediction exactly).  The engine's own seeds
    // preserve every vanilla relation (art flush-left with the rows, tucked
    // under the title band — the pristine layout); the ONLY defect was the
    // t_dp_artalign -> thunk_popup_artalign quote-box override.  So: gated
    // popup -> jmp thunk_sprite_draw with the args UNTOUCHED; anything else
    // -> the original chain head.  Clobbers ecx+flags (within artalign's
    // documented eax/ecx/edx scratch contract).
    const spriteDraw = 0x006688B0;                    // thunk_sprite_draw
    const stubArt = here();
    // v13: gv art = draw (pass-through seeds, v9) + SCANLINE RESTRIPE.
    // The flag field is 1px scanline dither built at the 1024 baseline;
    // the sd2 num/16 NN zoom bands it at fractional g (run-12 report,
    // g=25).  The prior modal-class image fix (thunk_portrait_avg
    // bilinear) gates on dest==0x940824 (faction-quote buffer) — misses
    // this popup — and bilinear is wrong for scanlines anyway (vanilla
    // BUILDS the flag at device size = crisp 1px rows).  Doctrine fix:
    // after the draw, rewrite the PAIR pixels in the drawn rect at 1px
    // device pitch.  Pair = src art rows 0/1 (read from the sprite data —
    // content-derived, no hardcoded indices); non-pair pixels (logo,
    // laurel) untouched.  Phase: device row0 <- src row0 color (NN floor
    // maps dst 0 to src 0).  thunk_sprite_draw is plain-RET (caller
    // cleans) — we call it with re-pushed args + add esp,0x14, and our
    // stub plain-RETs the same way.
    put([0x8B, 0x4C, 0x24, 0x08]);                    // mov ecx,[esp+8]
    put([0x3B, 0x0D, ...le32(gvMem)]);                // cmp ecx,[g_gv_popup]
    put([0x75, 0x0F]);                                // jne chain (+15)
    put([0xA1, ...le32(gAddr)]);                      // mov eax,[g]
    put([0x83, 0xF8, 0x10]);                          // cmp eax,0x10
    put([0x7F, 0x0A]);                                // jg armed (+10)
    jmpTo(spriteDraw);                                // g<=16: identity draw
    // chain:
    jmpTo(T_DP_ARTALIGN);                             // non-gv: original head
    // armed: (label shared with stubFlagDraw v18 — draw + LUT restripe;
    // reads args relative to ESP only and plain-RETs, so it serves both
    // entries: the [0x3168] call (gv) and artalign's push/ret tail (pd))
    const stubArtArmed = here();
    put([0x55, 0x53, 0x56, 0x57]);                    // push ebp/ebx/esi/edi
    put([0xFF, 0x74, 0x24, 0x24]);                    // push y
    put([0xFF, 0x74, 0x24, 0x24]);                    // push x
    put([0xFF, 0x74, 0x24, 0x24]);                    // push res
    put([0xFF, 0x74, 0x24, 0x24]);                    // push window
    put([0xFF, 0x74, 0x24, 0x24]);                    // push sprite
    callTo(spriteDraw);                               // real draw (plain RET)
    put([0x83, 0xC4, 0x14]);                          // add esp,0x14
    // v17: pair-mate LUT restripe in DEST index space (v15's 0xFA/0xE6 were
    // the PCX's OWN palette slots — the [sd1] diag proved the canvas manager
    // remaps +10 mod 256 on load, so the dest field pair is 0x04/0xF0 and
    // v15 matched nothing).  Three measured pairs (field/logo/laurel — see
    // the LUT builder comment above); every pixel is rewritten through the
    // row-parity LUT (identity for non-pair indices, so the 0x41/0x54 row
    // stripes under the art's left overhang and the 0x23 border stay
    // untouched).  Phase: rect row 0 = the art's top border row (measured:
    // dest rows y0/y0+1 hold the doubled border) -> even rows = toBright
    // (first content row = src row 1 = bright, like vanilla).
    // Still ZERO sprite-bits deref (filename-backed variant, pcBits NULL).
    put([0x8B, 0x74, 0x24, 0x14]);                    // mov esi,[esp+0x14] sprite (srcW/H only)
    // dw/dh = ceil(src * g / 16)
    put([0x8B, 0x0D, ...le32(gAddr)]);                // mov ecx,[g]
    put([0x8B, 0x46, 0x10]);                          // mov eax,[esi+0x10] srcW
    put([0x0F, 0xAF, 0xC1]);                          // imul eax,ecx
    put([0x83, 0xC0, 0x0F]);                          // add eax,15
    put([0xC1, 0xE8, 0x04]);                          // shr eax,4
    put([0x8B, 0xF8]);                                // mov edi,eax  dw
    put([0x8B, 0x46, 0x14]);                          // mov eax,[esi+0x14] srcH
    put([0x85, 0xC0]);                                // test eax,eax
    put([0x79, 0x02]);                                // jns +2
    put([0xF7, 0xD8]);                                // neg eax
    put([0x0F, 0xAF, 0xC1]);                          // imul eax,ecx
    put([0x83, 0xC0, 0x0F]);                          // add eax,15
    put([0xC1, 0xE8, 0x04]);                          // shr eax,4
    put([0x8B, 0xD0]);                                // mov edx,eax  dh
    // row0 ptr = data + (y-6)*pitch + (x-5)
    put([0x8B, 0x4C, 0x24, 0x18]);                    // mov ecx,[esp+0x18] window
    put([0x81, 0xC1, 0x44, 0x04, 0x00, 0x00]);        // add ecx,0x444 buffer
    put([0x8B, 0xA9, 0xA8, 0x04, 0x00, 0x00]);        // mov ebp,[ecx+0x4A8] pitch
    put([0x8B, 0x44, 0x24, 0x24]);                    // mov eax,[esp+0x24] y
    put([0x83, 0xE8, 0x06]);                          // sub eax,6
    put([0x0F, 0xAF, 0xC5]);                          // imul eax,ebp
    put([0x03, 0x41, 0x54]);                          // add eax,[ecx+0x54] data
    put([0x03, 0x44, 0x24, 0x20]);                    // add eax,[esp+0x20] x
    put([0x83, 0xE8, 0x05]);                          // sub eax,5
    put([0x8B, 0xF0]);                                // mov esi,eax row ptr
    put([0xBB, ...le32(lutBright)]);                  // mov ebx,toBright (row 0 = even)
    // rowloop:
    put([0x85, 0xD2]);                                // test edx,edx
    put([0x74, 0x1F]);                                // jz rs_done
    put([0x56]);                                      // push esi
    put([0x57]);                                      // push edi
    // colloop:
    put([0x85, 0xFF]);                                // test edi,edi
    put([0x74, 0x0C]);                                // jz colend
    put([0x0F, 0xB6, 0x06]);                          // movzx eax,byte [esi]
    put([0x8A, 0x04, 0x03]);                          // mov al,[ebx+eax]  LUT
    put([0x88, 0x06]);                                // mov [esi],al
    put([0x46]);                                      // inc esi
    put([0x4F]);                                      // dec edi
    put([0xEB, 0xF0]);                                // jmp colloop
    // colend:
    put([0x5F]);                                      // pop edi
    put([0x5E]);                                      // pop esi
    put([0x03, 0xF5]);                                // add esi,ebp
    put([0x81, 0xF3, 0x00, 0x01, 0x00, 0x00]);        // xor ebx,0x100 toggle LUT
    put([0x4A]);                                      // dec edx
    put([0xEB, 0xDD]);                                // jmp rowloop
    // rs_done:
    put([0x5F, 0x5E, 0x5B, 0x5D]);                    // pop edi/esi/ebx/ebp
    put([0xC3]);                                      // ret (caller cleans)

    // -- v18: stubFlagDraw — PROTOCOL DIRECTOR flag restripe port ----------
    // Installed by retargeting the abs32 of thunk_popup_artalign's tail
    // transfer (push thunk_sprite_draw; ret @0xA0F7F0, live-verified) — the
    // SINGLE exit both its armed (quote-box override) and passthrough
    // branches converge on, and t_dp_artalign's every path funnels into
    // artalign (disasm: jmp 0xA0F7A0).  Entered by push/ret tail-jump, so
    // the frame is identical to a [0x3168] call: [esp]=engine ret, args
    // (sprite,window,res,x,y) at +4..+0x18 — and x/y here are artalign's
    // FINAL values, so the restripe rect is the drawn rect by construction
    // (no positioning code touched; the pd popup's verified-good layout
    // stays).  Gate: window==g_pd_popup (armed per-draw, heap-reuse safe)
    // && g>16; everything else (faction quote box, every other titled
    // popup) -> thunk_sprite_draw untouched.  Armed -> stubArt's shared
    // draw+LUT-restripe tail.
    const stubFlagDraw = here();
    put([0x8B, 0x4C, 0x24, 0x08]);                    // mov ecx,[esp+8] window
    put([0x3B, 0x0D, ...le32(pdMem)]);                // cmp ecx,[g_pd_popup]
    put([0x75, 0x0A]);                                // jne pass (+10)
    put([0xA1, ...le32(gAddr)]);                      // mov eax,[g]
    put([0x83, 0xF8, 0x10]);                          // cmp eax,0x10
    put([0x7F, 0x05]);                                // jg armed (+5)
    jmpTo(spriteDraw);                                // pass/native: original
    jmpTo(stubArtArmed);                              // armed: shared v17 tail

    // -- lever F v11: chip scratch (data, never executed) + stubChip -------
    function callTo(target) {
      const rel = target - (here() + 5);
      put([0xE8, ...le32(rel)]);
    }
    const scratchA = here(); put(new Array(40).fill(0));  // borders-nulled params
    const scratchB = here(); put(new Array(40).fill(0));  // fill-nulled params
    const scratchR = here(); put(new Array(16).fill(0));  // inset rect
    // drop-in (ecx=dest, [esp+4]=rect, [esp+8]=params, RET 8):
    //   fill-first (STEP2 mechanism: Buffer_box_sprite with borders nulled =
    //   1:1 device tile over the K/K+1 inset), then hollow_flat frame ON TOP
    //   of the tile edge with the ORIGINAL rect.  Adopts a lazily-built fill
    //   sprite back into the real params so it is built at most once.
    const stubChip = here();
    put([0x83, 0x3D, ...le32(gAddr), 0x10]);          // cmp [g],0x10
    put([0x7F, 0x06]);                                // jg scaled
    put([0x68, ...le32(boxSprite)]);                  // push Buffer_box_sprite
    put([0xC3]);                                      // ret (native tail)
    // scaled:
    put([0x55, 0x53, 0x56, 0x57]);                    // push ebp/ebx/esi/edi
    put([0x8B, 0xE9]);                                // mov ebp,ecx  (dest)
    put([0x8B, 0x74, 0x24, 0x18]);                    // mov esi,[esp+0x18] params
    put([0xBF, ...le32(scratchA)]);                   // mov edi,scratchA
    put([0xB9, 0x0A, 0x00, 0x00, 0x00]);              // mov ecx,10
    put([0xF3, 0xA5]);                                // rep movsd
    put([0x8B, 0x74, 0x24, 0x18]);                    // mov esi,[esp+0x18]
    put([0xBF, ...le32(scratchB)]);                   // mov edi,scratchB
    put([0xB9, 0x0A, 0x00, 0x00, 0x00]);              // mov ecx,10
    put([0xF3, 0xA5]);                                // rep movsd
    put([0xBF, ...le32(scratchA)]);                   // mov edi,scratchA
    put([0x31, 0xC0]);                                // xor eax,eax
    put([0xB9, 0x08, 0x00, 0x00, 0x00]);              // mov ecx,8
    put([0xF3, 0xAB]);                                // rep stosd (null borders)
    put([0xC7, 0x05, ...le32(scratchB + 0x20), 0, 0, 0, 0]); // scratchB.fill=0
    put([0xA1, ...le32(gAddr)]);                      // mov eax,[g]
    put([0x83, 0xC0, 0x0F]);                          // add eax,15
    put([0xC1, 0xE8, 0x04]);                          // shr eax,4    K
    put([0x8B, 0x54, 0x24, 0x14]);                    // mov edx,[esp+0x14] rect
    put([0x8B, 0x0A]);                                // mov ecx,[edx]
    put([0x01, 0xC1]);                                // add ecx,eax
    put([0x89, 0x0D, ...le32(scratchR)]);             // L+K
    put([0x8B, 0x4A, 0x04]);                          // mov ecx,[edx+4]
    put([0x01, 0xC1]);                                // add ecx,eax
    put([0x89, 0x0D, ...le32(scratchR + 4)]);         // T+K
    put([0x40]);                                      // inc eax      K+1
    put([0x8B, 0x4A, 0x08]);                          // mov ecx,[edx+8]
    put([0x29, 0xC1]);                                // sub ecx,eax
    put([0x89, 0x0D, ...le32(scratchR + 8)]);         // R-(K+1)
    put([0x8B, 0x4A, 0x0C]);                          // mov ecx,[edx+0xC]
    put([0x29, 0xC1]);                                // sub ecx,eax
    put([0x89, 0x0D, ...le32(scratchR + 12)]);        // B-(K+1)
    put([0x68, ...le32(scratchA)]);                   // push scratchA (params)
    put([0x68, ...le32(scratchR)]);                   // push scratchR (rect)
    put([0x8B, 0xCD]);                                // mov ecx,ebp
    callTo(boxSprite);                                // fill tile (RET 8 cleans)
    put([0x68, ...le32(scratchB)]);                   // push scratchB (params)
    put([0xFF, 0x74, 0x24, 0x18]);                    // push [esp+0x18] (rect)
    put([0x8B, 0xCD]);                                // mov ecx,ebp
    callTo(HOLLOWFLAT);                               // frame on top (RET 8)
    // v12 mask pass: the chip border pieces are FAT (thin bevel + interior
    // PADDING) and vanilla Buffer_tile_masks the fill OVER each piece — the
    // fill-nulled frame pass exposed the raw padding (run-11 "massive white
    // outlines", the flat 0xC0 grey).  Re-run the mask at DEVICE density
    // over the whole rect: Buffer_tile_mask(fill, L,T, L,T, w,h, params[9])
    // replaces padding-colored pixels with the 1:1 fill; bevel + center
    // stripes are not the mask color and stay.  Tile phase is dest-anchored
    // (box_sprite passes pos==phase everywhere), so all passes align.
    put([0x8B, 0x54, 0x24, 0x18]);                    // mov edx,[esp+0x18] params
    put([0x8B, 0x42, 0x20]);                          // mov eax,[edx+0x20] fill
    put([0x85, 0xC0]);                                // test eax,eax
    put([0x74, 0x27]);                                // jz done (skip 39 bytes)
    put([0x8B, 0x4A, 0x24]);                          // mov ecx,[edx+0x24] mask
    put([0x51]);                                      // push mask
    put([0x8B, 0x54, 0x24, 0x18]);                    // mov edx,[esp+0x18] rect
    put([0x8B, 0x4A, 0x0C]);                          // mov ecx,[edx+0xC]
    put([0x2B, 0x4A, 0x04]);                          // sub ecx,[edx+4]
    put([0x51]);                                      // push h
    put([0x8B, 0x4A, 0x08]);                          // mov ecx,[edx+8]
    put([0x2B, 0x0A]);                                // sub ecx,[edx]
    put([0x51]);                                      // push w
    put([0xFF, 0x72, 0x04]);                          // push [edx+4]  y phase
    put([0xFF, 0x32]);                                // push [edx]    x phase
    put([0xFF, 0x72, 0x04]);                          // push [edx+4]  y
    put([0xFF, 0x32]);                                // push [edx]    x
    put([0x50]);                                      // push fill
    put([0x8B, 0xCD]);                                // mov ecx,ebp
    callTo(TILEMASK);                                 // callee cleans 0x20
    // done:
    put([0x5F, 0x5E, 0x5B, 0x5D]);                    // pop edi/esi/ebx/ebp
    put([0xC2, 0x08, 0x00]);                          // ret 8

    Memory.protect(page, Process.pageSize, "rwx");

    // call_target_redirects (E8 rel32 rewrites; byte patches, no hooks)
    function redirect(siteVA, target, label) {
      try {
        const site = VA(siteVA);
        Memory.patchCode(site, 5, (code) => {
          code.writeU8(0xE8);
          code.add(1).writeS32(target - (site.toUInt32() + 5));
        });
        L("stub", label + " redirected @0x" + siteVA.toString(16));
      } catch (e) { L("stub", label + " FAIL: " + e); }
    }
    if (LEVER_SPRITES) {
      redirect(0x00425F3C, stubPortrait, "portrait");
      redirect(0x00426105, stubLogo, "logo");
      armReblit(stubPortrait, "portrait", false); // v23 parity-reblit tails
      armReblit(stubLogo, "logo", true);
    }
    if (LEVER_TEXTY) redirect(0x00425F83, stubTexty, "texty");
    if (LEVER_SEEDS) redirect(0x00427784, stubSeed, "seed");
    if (LEVER_BACKDROP37) redirect(0x00426b4e, stubB, "backdrop37");
    if (LEVER_BTNGATE) {
      // Verify the LIVE shape of the baked thunk_btn_shrink before repointing
      // (PRACX-stomp lesson: never trust the ledger, read the bytes): body
      // starts pushad @pcave2+0x400, the gate E8 sits at +0xB and must
      // currently target thunk_btn_gate_pre.
      const e8site = 0x00A0C40B;
      const b0 = VA(0x00A0C400).readU8(), op = VA(e8site).readU8();
      const curTgt = VA(e8site).add(1).readS32() + VA(e8site).toUInt32() + 5;
      if (b0 !== 0x60 || op !== 0xE8 || (curTgt >>> 0) !== gatePre) {
        L("stub", "btnGate SKIPPED: live shrink bytes unexpected (b0=0x" +
          b0.toString(16) + " op=0x" + op.toString(16) + " tgt=0x" +
          (curTgt >>> 0).toString(16) + " want=0x" + gatePre.toString(16) + ")");
      } else {
        redirect(e8site, stubBtnGate, "btnGate");
      }
    }
    // live-byte verify an E8 site before repointing (PRACX-stomp lesson):
    // it must currently be E8 -> the expected target.
    const ckE8 = (site, want, label) => {
      const op = VA(site).readU8();
      const tgt = (VA(site).add(1).readS32() + site + 5) >>> 0;
      if (op !== 0xE8 || tgt !== want) {
        L("stub", label + " SKIPPED: live E8 @0x" + site.toString(16) +
          " op=0x" + op.toString(16) + " tgt=0x" + tgt.toString(16) +
          " want=0x" + want.toString(16));
        return false;
      }
      return true;
    };
    if (LEVER_CASTVOTE) {
      if (ckE8(0x00406154, dInset, "gvStrokeA")) redirect(0x00406154, stubStrokeA, "gvStrokeA");
      if (ckE8(0x00406238, cFrame, "gvStrokeB")) redirect(0x00406238, stubStrokeB, "gvStrokeB");
      gvMemPtr = ptr(gvMem);
      stubArtAddr = stubArt;
      L("stub", "gv armed-machinery ready (gvMem=0x" + gvMem.toString(16) +
        " stubArt=0x" + stubArt.toString(16) + ")");
      // v18 pd port: retarget artalign's tail push imm32 (68 B0 88 66 00 =
      // push thunk_sprite_draw @0xA0F7F0+1) -> stubFlagDraw.  Live-verify
      // the full 5 bytes first (PRACX-stomp lesson).
      const pdSite = 0x00A0F7F0;
      const pb = [0, 1, 2, 3, 4].map(i => VA(pdSite + i).readU8());
      const want = [0x68, 0xB0, 0x88, 0x66, 0x00];
      if (pb.every((v, i) => v === want[i])) {
        Memory.patchCode(VA(pdSite + 1), 4, (code) => code.writeU32(stubFlagDraw));
        pdMemPtr = ptr(pdMem);
        L("stub", "pd artalign tail retargeted @0x" + pdSite.toString(16) +
          " -> stubFlagDraw=0x" + stubFlagDraw.toString(16));
      } else {
        L("stub", "pd SKIPPED: live artalign tail bytes " +
          pb.map(v => v.toString(16).padStart(2, "0")).join(" ") +
          " != push thunk_sprite_draw");
      }
    }
    if (LEVER_FRAMES) {
      // -- lever F (v10/v11, phase 2): the 9 CouncilWin-dest Buffer_box_
      //    sprite sites.  Popup-family sets (d528/d690, 1-native-px border,
      //    navy fill) -> thunk_box_thick_devfill DIRECT; d5a0 (hollow band)
      //    -> thunk_box_thick_hollow_flat DIRECT.  CHIP sets (da28/d9d8/
      //    da00) -> stubChip (v11): the chip bevel is 2-3 NATIVE px
      //    (pristine Vote.png pixel-measured) so devfill's popup-tuned
      //    K/K+1 inset lands the STEP2 tile INSIDE the scaled bevel — the
      //    run-10 "color artifacting on the left/right of the abstain
      //    element" (stripe rows overwriting the bevel's inner columns;
      //    top/bottom invisible because the 1px stripes run parallel).
      //    stubChip ORDER-SWAPS instead of chasing the NN-mapped bevel
      //    edge: (1) fill pass = Buffer_box_sprite(dest, K/K+1-inset rect,
      //    borders-NULLED params copy) — the exact STEP2 mechanism, a 1:1
      //    device-density tile (dither invariant; corners stay clean at
      //    inset K); (2) frame pass = thunk_box_thick_hollow_flat(dest,
      //    ORIGINAL rect, fill-NULLED params copy) — the thick bevel draws
      //    OVER the tile edge, so the seam cannot exist by construction.
      //    Static per-site routing (chip fills are LAZY-BUILT — null
      //    [params+0x20] pre-first-draw... note the fill pass tiles a
      //    NULL fill as a no-op on the very first draw; the frame still
      //    renders and the interior back-fills on the next repaint tick).
      //    CONSOLE-dest sites (0x4264DD/0x4265AB/0x426B14, ecx=0x7AEC64)
      //    are NOT touched — the baked hud_frames entry detour owns them.
      //    The d690 backdrop @0x426B4E routes via stubB's devfill tail. --
      const FILL_SITES = [
        0x00425EE9,   // col painter: column frame d528
        0x00426286,   // col painter: d528
        0x00426BD2,   // repaint: d528
      ];
      const CHIP_SITES = [
        0x004261AA,   // col painter: chip da00
        0x004261D6,   // col painter: chip d9d8
        0x00426203,   // col painter: chip da28
        0x00426230,   // col painter: chip da28
        0x0042625C,   // col painter: chip da28
      ];
      for (const s of FILL_SITES)
        if (ckE8(s, boxSprite, "frameFill")) redirect(s, DEVFILL, "frameFill@0x" + s.toString(16));
      for (const s of CHIP_SITES)
        if (ckE8(s, boxSprite, "chip")) redirect(s, stubChip, "chip@0x" + s.toString(16));
      if (ckE8(0x00426B7B, boxSprite, "frameHollow"))
        redirect(0x00426B7B, HOLLOWFLAT, "frameHollow@0x426b7b");
    }
    L("stub", "stubs @0x" + base.toString(16) + " len=" + off);
  }

  // ---- S: seed-table geometry (consumed by stubSeed above) ----------------
  const OUTER_L = [30, 130, 230, 330, 452, 552, 652];
  const OUTER_T = [53, 45, 37, 29, 37, 45, 53];
  const INNER_L = [32, 135, 238, 341, 444, 547, 650];

  // ---- exec entry: apply imms before the seed writes run ------------------
  // conRect 0x7AF5C0 tracking: run-5 dump proved the exec-time button
  // derivation used box.B=420 while every repaint's re-derived box.B=356 —
  // the console proposal rect CHANGES between exec's one-shot button bake
  // and the first repaint (that is the vote-button clip, not a scale error).
  // Log it at exec entry and per-repaint to pin which value is the stale one.
  const conR = () => rect4(VA(0x007AF5C0));
  Interceptor.attach(VA(0x00427230), {
    onEnter() {
      applyImms();
      log("[exec] " + env() + " conRect=" + conR());
      ckpt("exec-in");
      repairStomp("exec-in");          // learns the healthy vtable value
    },
    onLeave() { ckpt("exec-out"); repairStomp("exec-out"); }
  });

  // ---- show_hide: bracket the nested repaint --------------------------------
  // show_hide(1) runs `call [CWIN.vptr+0x30]` (the repaint) BEFORE its
  // FlatButton loop — run 2 proved the stomp happens inside that nested call
  // (vptrs OK at entry, crash in the loop).  Checkpoint at entry AND at the
  // loop head 0x426fc0 (post-repaint; relocation audited: xor esi,esi +
  // add edi,0x380 = 8 bytes relocate whole, jl target 0x426fc8 untouched).
  Interceptor.attach(VA(0x00426FA0), {
    onEnter() {
      const arg = this.context.esp.add(4).readS32();
      const bad = repairStomp("show-entry");
      log("[show_hide] arg=" + arg + (bad ? " REPAIRED" : " vptrs OK") + " " + env());
    }
  });
  // (v5: the 0x426FC0 preloop attach is GONE — it was itself a mid-function
  //  [esp] poisoner, and with the seed/blever attaches removed there is no
  //  smash left to repair.  The canaries below stay as WATCHDOGS: any
  //  [SMASH2@...] line in a v5 run is a NEW writer, not the old one.)

  // ---- stack canary: catch the caller-frame smash red-handed ---------------
  // Run 3 registers: show_hide's saved-EDI (+4) and RET (+0x14) slots were
  // overwritten (values 0x2eb0xxx stepping -0x100 per +0x10 of stack) while
  // +8/+0xC/+0x10 stayed intact, and repaint's pop edi restored a smashed
  // slot.  Snapshot the 16 dwords of caller frames at repaint entry; diff at
  // every painter boundary and repaint leave.
  const CANARY_DW = 16;
  let canBase = null, canSnap = null;
  // canary2: repaint's own saved-reg slots.  Prologue = push ebp; sub esp,0x10;
  // push ebx; push esi; push edi -> saved EDI/ESI/EBX at entryESP-0x20/-0x1C/-0x18.
  // Run 3+4 proved the corruption is repaint's saved-EDI slot (pop edi restores
  // a heap pointer, page offset 0xb0f both runs); it sits below canary1.
  let can2Base = null, can2Snap = null;
  function canaryArm(esp) {
    canBase = esp.add(4);                     // [esp]=ret; +4.. = caller frames
    canSnap = [];
    for (let i = 0; i < CANARY_DW; i++) canSnap.push(canBase.add(i * 4).readU32());
    can2Base = esp.sub(0x20);                 // [+0]=svEDI [+4]=svESI [+8]=svEBX
  }
  const CAN2_NAMES = ["savedEDI", "savedESI", "savedEBX"];
  // v6: LOG-ONLY — the v5 crash was the restore itself.  After repaint
  // returns, the bases point at DEAD stack that live code reuses; "restoring"
  // snap values there poisoned the column-draw frames (crash regs esi=0x80
  // ebp=ebx=0x6fec80 were literally the snap values; AV addr 0x4e4 =
  // 0x80+0x464).  Checks now write NOTHING and the bases are nulled at
  // repaint-out so post-repaint painter calls skip entirely.
  function canary2Check(tag) {
    if (!can2Base || !can2Snap) return;
    try {
      for (let i = 0; i < 3; i++) {
        const now = can2Base.add(i * 4).readU32();
        if (now !== can2Snap[i]) {
          log("[SMASH2@" + tag + "] " + CAN2_NAMES[i] + ": 0x" +
              can2Snap[i].toString(16) + " -> 0x" + now.toString(16));
          can2Snap[i] = now;                    // report each change once
        }
      }
    } catch (e) { log("[SMASH2@" + tag + "] err " + e); }
  }
  function canaryCheck(tag) {
    if (!canSnap) return;
    try {
      for (let i = 0; i < CANARY_DW; i++) {
        const now = canBase.add(i * 4).readU32();
        if (now !== canSnap[i]) {
          log("[SMASH@" + tag + "] frame+0x" + (4 + i * 4).toString(16) +
              ": 0x" + canSnap[i].toString(16) + " -> 0x" + now.toString(16));
          canSnap[i] = now;                   // report each smash once
        }
      }
    } catch (e) { log("[SMASH@" + tag + "] err " + e); }
  }

  // ---- painter brackets: pin the smash/stomp to one invocation --------------
  Interceptor.attach(VA(0x00425DB0), {   // draw_column(faction)
    onEnter() {
      this.f = this.context.esp.add(4).readS32();
      canaryCheck("col" + this.f + "-in"); canary2Check("col" + this.f + "-in");
      if (repairStomp("col" + this.f + "-in")) log("[col" + this.f + "-in] REPAIRED");
    },
    onLeave() {
      canaryCheck("col" + this.f + "-out"); canary2Check("col" + this.f + "-out");
      if (repairStomp("col" + this.f + "-out")) log("[col" + this.f + "-out] REPAIRED");
    }
  });
  Interceptor.attach(VA(0x00426470), {   // draw_proposal
    onEnter() { canaryCheck("prop-in"); canary2Check("prop-in"); if (repairStomp("prop-in")) log("[prop-in] REPAIRED"); },
    onLeave() { canaryCheck("prop-out"); canary2Check("prop-out"); if (repairStomp("prop-out")) log("[prop-out] REPAIRED"); }
  });

  // (lever B lives in buildStubs — redirect @0x426b4e, no attach)

  // ---- observe: repaint + FlatButton identity dump ------------------------
  let dumped = false;
  Interceptor.attach(VA(0x00426AA0), {
    onEnter() {
      L("repaint", env() + " immsApplied=" + immsApplied + " conRect=" + conR(), 10);
      ckpt("repaint");
      canaryArm(this.context.esp);
      // the prologue is about to push these exact values into the watched slots
      can2Snap = [u32(this.context.edi), u32(this.context.esi), u32(this.context.ebx)];
      if (dumped) return;
      dumped = true;
      try {
        log("[dump] CWin buf w/h=" + rd(cw, 0x4C4) + "/" + rd(cw, 0x4C8) +
            " clip474=" + rect4(cw.add(0x474)));
        log("[dump] banner=" + rect4(cw.add(0xBA4)) + " propBox=" + rect4(cw.add(0xBB4)) +
            " btnFull=" + rect4(cw.add(0xD04)));
        for (let c = 0; c < 7; c++)
          log("[dump] col" + c + " outer=" + rect4(cw.add(0xBF4 + c * 0x20)) +
              " inner=" + rect4(cw.add(0xC04 + c * 0x20)));
        for (let b = 0; b < 3; b++)
          log("[dump] btn" + b + "=" + rect4(cw.add(0xCD4 + b * 0x10)));
        for (let i = 0; i < 6; i++) {
          const fb = cw.add(0xD94 + i * 0xB4C);
          log("[dump] flatbtn" + i + " rect13C=" + rect4(fb.add(0x13C)) +
              " rect14C=" + rect4(fb.add(0x14C)) + " clip474=" + rect4(fb.add(0x474)));
        }
        for (let f = 0; f < 6; f++) {
          const fp = cw.add(0xAB4 + f * 0x28);
          log("[dump] font+0x" + (0xAB4 + f * 0x28).toString(16) + " " +
              [0, 4, 0xc, 0x10, 0x14, 0x18].map(o => fp.add(o).readS32()).join(","));
        }
      } catch (e) { log("[dump] err " + e); }
    },
    onLeave() {
      // DISARM, no checks: at onLeave the watched slots are already below ESP
      // (dead + Frida's own onLeave machinery runs on this stack) — reading
      // them is noise; the painter brackets inside the repaint are the real
      // coverage.  Nulling the bases makes post-repaint painter calls skip.
      canBase = null; canSnap = null; can2Base = null; can2Snap = null;
      repairStomp("repaint-out");
    }
  });

  // ---- V: Cast-a-Vote arming — Popup_on_draw_background ENTRY (fastcall
  // this=ecx).  Per-draw, content-keyed (heap-ptr reuse safe): match ->
  // g_gv_popup=this + install the art stub into [this+0x3168] (only over
  // t_dp_artalign — anything else is logged, not clobbered); mismatch ->
  // clear the key if it names this ptr + restore t_dp_artalign if this
  // instance carries our stub (the engine store @0x404BDE is skip-if-set
  // and will NOT undo us).  Strokes draw inside this very call after
  // onEnter; art draws right after it returns — arming is synchronous.
  let gvArmedFor = 0;
  Interceptor.attach(VA(0x00405C80), {
    onEnter() {
      if (!gvMemPtr) return;                    // stubs not built yet
      try {
        const p = ptr(this.context.ecx.toUInt32());
        const pu = p.toUInt32();
        let match = false, matchPD = false;
        const tp = p.add(0xa48).readPointer();
        const artP = p.add(0x2144).readU32();
        if (!tp.isNull() && artP !== 0) {
          const s = tp.readAnsiString();
          const sl = s ? s.toLowerCase() : "";
          match = sl === "eligible candidates";
          if (!match) {
            // v19: the pd/flag gate keys on the ART CONTENT (sprite
            // filename), NOT the popup title — run-18 [pd-title] proved the
            // proposal popup's [+0xa48] is the generic window title
            // "Sid Meier's ALPHA CENTAURI" (the band text is a different
            // field).  Content key = any popup drawing the UN flag through
            // artalign gets the restripe, and it survives localization.
            const nmP = ptr(artP).readPointer();
            const nm = nmP.isNull() ? "" : (nmP.readAnsiString() || "");
            matchPD = nm.toLowerCase().endsWith("council_sm.pcx");
            if (!matchPD) L("pd-art", "unmatched art popup: title=\"" + s +
                            "\" art=\"" + nm + "\" [0x3168]=0x" +
                            p.add(0x3168).readU32().toString(16), 12);
          }
        }
        const cur = p.add(0x3168).readU32();
        // v18: PROTOCOL DIRECTOR — arm the pd slot for stubFlagDraw (the
        // restripe rides artalign's tail; the [0x3168] override is NOT for
        // this popup — restore it if the reused ptr still carries it).
        if (pdMemPtr) {
          if (matchPD) {
            pdMemPtr.writeU32(pu);
            if (gvMemPtr.readU32() === pu) gvMemPtr.writeU32(0);
            if (cur === stubArtAddr) p.add(0x3168).writeU32(T_DP_ARTALIGN);
            if (gvArmedFor !== -pu) {
              gvArmedFor = -pu;   // negative = pd armed (one-shot log key)
              L("gv", "ARMED-PD popup=0x" + pu.toString(16) + " (flag restripe via artalign tail)");
            }
            return;
          }
          if (pdMemPtr.readU32() === pu && !matchPD) pdMemPtr.writeU32(0);
        }
        if (match) {
          gvMemPtr.writeU32(pu);
          if (cur === T_DP_ARTALIGN) {
            p.add(0x3168).writeU32(stubArtAddr);
          } else if (cur !== stubArtAddr) {
            L("gv", "NOT installing art stub: [0x3168]=0x" + cur.toString(16) +
              " (expected t_dp_artalign)");
          }
          if (gvArmedFor !== pu) {
            gvArmedFor = pu;
            // measure-the-engine dump: the art stub's law assumes the x/y
            // seeds ([30e0]+[30f0]+[21c8], [30e8]+[30e0]) are NATIVE.
            L("gv", "ARMED popup=0x" + pu.toString(16) +
              " m30e0=" + p.add(0x30e0).readS32() +
              " m30f0=" + p.add(0x30f0).readS32() +
              " m21c8=" + p.add(0x21c8).readS32() +
              " hdr30e8=" + p.add(0x30e8).readS32() +
              " artAdv30d8=" + p.add(0x30d8).readS32() +
              " contentH30d4=" + p.add(0x30d4).readS32() +
              " ratio=" + p.add(0x3104).readS32() + "/" + p.add(0x3108).readS32() +
              " artWH=" + p.add(0x2144).readPointer().add(0x18).readS32() + "x" +
                          p.add(0x2144).readPointer().add(0x1c).readS32() +
              " parentA3C=0x" + p.add(0xa3c).readU32().toString(16) +
              " ext=0x" + p.add(0xa14).readU32().toString(16) +
              " type=" + p.add(0x30ac).readS32());
          }
        } else {
          if (gvMemPtr.readU32() === pu) gvMemPtr.writeU32(0);
          if (cur === stubArtAddr) {
            p.add(0x3168).writeU32(T_DP_ARTALIGN);
            L("gv", "RESTORED [0x3168] on reused popup 0x" + pu.toString(16));
          }
          if (gvArmedFor === pu) gvArmedFor = 0;
        }
      } catch (e) { L("gv", "err " + e); }
    }
  });

  // ---- v16 DIAG: measure the gv art draw (run-15 = crash-free, STILL
  // banded).  Statically verified since: pair indices 0xFA/0xE6 match the
  // MASTER palette.pcx slots (250=(0,0,128), 230=(53,61,115) — identical to
  // council_sm.pcx, no canvas-manager remap); walk offsets data+0x54/
  // pitch+0x4A8 == thunk_fe_pair_remap's proven walk; dest window+0x444
  // embedded Buffer == thunk_sprite_draw's own dest.  Everything models
  // correct — so MEASURE the engine: attach at thunk_sprite_draw ENTRY
  // (cave 0x6688B0, prologue 55 8B EC 8B 4D 14 = 3 whole instrs, entry-only
  // target, PRACX never touches caves), gated window==g_gv_popup.
  //   onEnter  : if a prior gv draw was recorded, re-read ITS rect first =
  //              state the stub left AFTER draw+restripe (the cleanest
  //              post-restripe bracket: next-draw entry).
  //   onLeave  : dest rect content PRE-restripe (the stub restripes after
  //              this thunk returns) — histogram + first rows.
  //   +500ms   : one delayed re-read = what the frame settled to.
  // Answers in one run: (a) is the drawn rect where we walk it and does it
  // hold 0xFA/0xE6, (b) does the restripe write at all, (c) does a later
  // draw overwrite it.
  const SD_THUNK = 0x006688B0;
  let sdN = 0, sdPrev = null;
  function sdRect(tag, data, pitch, x0, y0, dw, dh) {
    const hist = {};
    for (let r = 0; r < dh; r++) {
      const row = new Uint8Array(data.add((y0 + r) * pitch + x0).readByteArray(dw));
      for (let i = 0; i < dw; i++) hist[row[i]] = (hist[row[i]] || 0) + 1;
    }
    const top = Object.entries(hist).sort((a, b) => b[1] - a[1]).slice(0, 8);
    log(tag + " histo " + top.map(e => "0x" + (+e[0]).toString(16) + ":" + e[1]).join(" "));
    for (let r = 0; r < 6; r++) {
      const row = new Uint8Array(data.add((y0 + r) * pitch + x0).readByteArray(24));
      log(tag + " row" + r + " " +
          Array.from(row).map(v => v.toString(16).padStart(2, "0")).join(" "));
    }
  }
  // v20: dest-space LUTs for the JS-side restripe (same pairs as the asm
  // stub; parity-forcing => IDEMPOTENT — double-applying with the asm
  // restripe is a no-op).  Applied to ANY council_sm.pcx draw at g>16, so
  // whichever [0x3168]/artalign variant a popup carries, the flag gets
  // restriped as long as the draw flows through thunk_sprite_draw.  Run-19
  // proved the PD popup's [+0x2144] holds space_sm.pcx (a starfield) while
  // it DISPLAYS the flag — the popup-field key was wrong; keying on the
  // DRAWN sprite is the ground-truth gate.
  const LUT_B_JS = new Uint8Array(256), LUT_D_JS = new Uint8Array(256);
  for (let i = 0; i < 256; i++) { LUT_B_JS[i] = i; LUT_D_JS[i] = i; }
  LUT_B_JS[0xF0] = 0x04; LUT_B_JS[0x2B] = 0xFF; LUT_B_JS[0x2E] = 0x4A;
  LUT_D_JS[0x04] = 0xF0; LUT_D_JS[0xFF] = 0x2B; LUT_D_JS[0x4A] = 0x2E;
  function jsRestripe(win, sprite, x, y) {
    const g = VA(0x00668740).readS32();
    if (g <= 16) return;
    const buf = win.add(0x444);
    const data = buf.add(0x54).readPointer();
    const pitch = buf.add(0x4A8).readS32();
    if (data.isNull() || pitch <= 0) return;
    const sw = sprite.add(0x10).readS32();
    let sh = sprite.add(0x14).readS32(); if (sh < 0) sh = -sh;
    const dw = Math.ceil(sw * g / 16), dh = Math.ceil(sh * g / 16);
    if (dw <= 0 || dh <= 0 || dw > 2048 || dh > 2048) return;
    const x0 = x - 5, y0 = y - 6;
    for (let r = 0; r < dh; r++) {
      const lut = (r & 1) ? LUT_D_JS : LUT_B_JS;
      const p = data.add((y0 + r) * pitch + x0);
      const ab = p.readByteArray(dw);
      const row = new Uint8Array(ab);
      let changed = false;
      for (let i = 0; i < dw; i++) {
        const v = lut[row[i]];
        if (v !== row[i]) { row[i] = v; changed = true; }
      }
      if (changed) p.writeByteArray(ab);
    }
  }
  Interceptor.attach(VA(SD_THUNK), {
    onEnter(args) {
      this.gv = false; this.flag = false;
      // v28 FIX D (user, shot 224848: "color banding on the leader portrait in
      // the bribe screen" — pixel stats: NN column duplication every 2-3px +
      // duplicate-row clusters on a 36-row beat = the 2-row scanline dither
      // RESAMPLED; the tally portrait behind it, v23 parity-reblit, has 0).
      // The popup art draws through THIS thunk -> engine NN blit 0x5e4b4a
      // (forbidden to hook) at (x-5, y-6), dest = win+0x444, num=g den=16.
      // Same tail as the tally: compute the dest rect, snapshot, and after
      // the engine blit MEASURE it (ceil-1 height, engine-owned) and run the
      // v22 parity-forced re-blit over the measured rect.  Only pcBits-backed
      // art (leader portraits); named .pcx art keeps its own path.
      this.rb = null; this.rbSnap = null;
      try {
        const gg = VA(0x00668740).readS32();
        const spr = args[0], w0 = args[1].toUInt32();
        if (gg > 16 && w0 && !spr.isNull()) {
          const sData = spr.add(4).readPointer();
          const bw = spr.add(0x10).readS32(), bh = spr.add(0x14).readS32();
          const sPitch = spr.add(0xC).readS32();
          if (!sData.isNull() && bw > 0 && bh > 0 && bw <= 400 && bh <= 400 && sPitch >= bw) {
            const offx = spr.add(0x20).readS32(), offy = spr.add(0x24).readS32();
            const dest = ptr(w0).add(0x444);
            const key = spr.add(8).readU8();
            const x0 = args[3].toInt32() - 5 + Math.floor(offx * gg / 16);
            const y0 = args[4].toInt32() - 6 + Math.floor(offy * gg / 16);
            const dw = Math.ceil(bw * gg / 16), dh = Math.ceil(bh * gg / 16);
            this.rb = { sData, sPitch, srcX: 0, srcY: 0, sw: bw, sh: bh, dest, key, x0, y0, dw, dh, num: gg, den: 16 };
            this.rbSnap = rbSnapshot(dest, x0, y0, dw, dh);
          }
        }
      } catch (e) { L("reblit", "popup-art onEnter err " + e); this.rb = null; }
      if (!gvMemPtr) return;
      const w = args[1].toUInt32();
      // v20 census: every popup-art draw, dedup'd on name+window+coords
      let nm = "";
      try {
        const nmP = args[0].readPointer();
        nm = nmP.isNull() ? "" : (nmP.readAnsiString() || "");
      } catch (e) {}
      this.x = args[3].toInt32();
      this.y = args[4].toInt32();
      L("sdcensus", "name=" + nm + " win=0x" + w.toString(16) +
        " x=" + this.x + " y=" + this.y, 24);
      if (w === 0) return;
      this.win = ptr(w);
      this.sprite = args[0];
      this.flag = nm.toLowerCase().endsWith("council_sm.pcx");
      if (w !== gvMemPtr.readU32() && !(pdMemPtr && w === pdMemPtr.readU32())) return;
      this.gv = true;
      if (sdPrev) {
        const p = sdPrev; sdPrev = null;
        try { sdRect("[sd" + p.n + "-nextdraw]", p.data, p.pitch, p.x0, p.y0, p.dw, p.dh); }
        catch (e) { log("[sd" + p.n + "-nextdraw] err " + e); }
      }
    },
    onLeave() {
      if (this.rb) {   // v28 fix D tail
        try {
          const r = this.rb;
          const m = this.rbSnap ? rbMeasure(this.rbSnap) : null;
          L("reblit-measure", "popup-art computed " + r.x0 + "," + r.y0 + " " + r.dw + "x" + r.dh +
            (!m ? " (no snapshot)" : m.w <= 0 ? " measured: NO CHANGE (dest already held it)"
                                             : " measured " + m.x + "," + m.y + " " + m.w + "x" + m.h), 16);
          if (m && m.w > 0 && m.h > 0 && Math.abs(m.x - r.x0) <= 1 && Math.abs(m.y - r.y0) <= 1 &&
              Math.abs(m.w - r.dw) <= 1 && Math.abs(m.h - r.dh) <= 1) {
            r.x0 = m.x; r.y0 = m.y; r.dw = m.w; r.dh = m.h;   // the ENGINE's rect, not the model
          }
          parityReblit(r);
          L("reblit", "popup-art parity-reblit " + r.dw + "x" + r.dh + " @" + r.x0 + "," + r.y0 +
            " src " + r.sw + "x" + r.sh + " key=" + r.key + " g=" + r.num, 16);
        } catch (e) { L("reblit", "popup-art onLeave err " + e); }
      }
      // v20: content-keyed JS restripe — fires for EVERY council_sm draw,
      // independent of which arming slot (if any) matched.
      if (this.flag) {
        try { jsRestripe(this.win, this.sprite, this.x, this.y); }
        catch (e) { L("sdcensus", "jsRestripe err " + e); }
      }
      if (!this.gv || sdN >= 6) return;
      sdN++;
      const n = sdN, tag = "[sd" + n + "]";
      try {
        const g = VA(0x00668740).readS32();
        const buf = this.win.add(0x444);
        const data = buf.add(0x54).readPointer();
        const pitch = buf.add(0x4A8).readS32();
        const bw = buf.add(0x80).readS32(), bh = buf.add(0x84).readS32();
        const nmP = this.sprite.readPointer();
        const nm = nmP.isNull() ? "<null>" : nmP.readAnsiString();
        const sw = this.sprite.add(0x10).readS32();
        let sh = this.sprite.add(0x14).readS32(); if (sh < 0) sh = -sh;
        const dw = Math.ceil(sw * g / 16), dh = Math.ceil(sh * g / 16);
        const x0 = this.x - 5, y0 = this.y - 6;
        log(tag + " x=" + this.x + " y=" + this.y + " sprite=" + this.sprite +
            " name=" + nm + " pcBits=" + this.sprite.add(4).readPointer() +
            " sw/sh=" + sw + "/" + sh + " dw/dh=" + dw + "/" + dh +
            " data=" + data + " pitch=" + pitch + " bw/bh=" + bw + "/" + bh);
        if (data.isNull() || pitch <= 0 || dw <= 0 || dh <= 0) {
          log(tag + " SKIP rect read (degenerate)"); return;
        }
        sdRect(tag + " PRE", data, pitch, x0, y0, dw, dh);
        sdPrev = { n: n, data: data, pitch: pitch, x0: x0, y0: y0, dw: dw, dh: dh };
        const win = this.win;
        setTimeout(() => {
          try {
            if (gvMemPtr.readU32() !== win.toUInt32()) {
              log(tag + " POST skipped (popup gone)"); return;
            }
            sdRect(tag + " POST500", win.add(0x444 + 0x54).readPointer(),
                   pitch, x0, y0, dw, dh);
          } catch (e) { log(tag + " POST err " + e); }
        }, 500);
      } catch (e) { log(tag + " err " + e); }
    }
  });

  // ---- v21: CALLSTACK TRACE + blit-level restripe ------------------------
  // Run-20 proved the PROTOCOL DIRECTOR modal is invisible to ALL popup
  // machinery: a full session produced ZERO [sdcensus]/[pd-art]/ARMED lines
  // — it never passes Popup_on_draw_background 0x405C80 and never calls
  // thunk_sprite_draw.  Stop guessing paths; trace the actual draw.
  // Chokepoints (entry-only attaches, none on the forbidden list, PRACX
  // grep clean): Buffer_draw_2 0x5D84C0 (keyed uniform-scale blit,
  // thiscall src; dest,key,X,Y,num,den) and Buffer_copy_3 0x5D9610 (GDI
  // StretchBlt path, thiscall src; dst,srcX,srcY,srcW,srcH,dstX,dstY,
  // dstW,dstH) — every scaled blit of the 200x120 flag must pass one of
  // them — plus Buffer_load_pcx 0x5D7DE0 (name-gated) for the load site.
  // Each match logs a BACKTRACE.  And since the blit hands us the exact
  // dest rect, restripe it right there (content-gated: src rows 1/2 col 2
  // must hold the flag pair raw 250/230 or remapped 4/240 — space_sm and
  // other 200x120 art never match), which fixes the flag through ANY path
  // while the trace names the real site for the bake.
  function btStr(ctx) {
    try {
      return Thread.backtrace(ctx, Backtracer.ACCURATE).slice(0, 10)
        .map(a => {
          const m = Process.findModuleByAddress(a);
          if (m && m.name.toLowerCase().indexOf("terranx") === 0) return a.toString();
          return m ? (m.name + "+0x" + a.sub(m.base).toString(16)) : a.toString();
        }).join(" ");
    } catch (e) { return "bt-err " + e; }
  }
  function bufIsFlag(src) {
    try {
      const data = src.add(0x54).readPointer();
      const pitch = src.add(0x4A8).readS32();
      if (data.isNull() || pitch < 200) return false;
      const b1 = data.add(pitch + 2).readU8(), b2 = data.add(2 * pitch + 2).readU8();
      return (b1 === 250 && b2 === 230) || (b1 === 4 && b2 === 240);
    } catch (e) { return false; }
  }
  function restripeRect(destBuf, x0, y0, dw, dh) {
    const data = destBuf.add(0x54).readPointer();
    const pitch = destBuf.add(0x4A8).readS32();
    if (data.isNull() || pitch <= 0 || dw <= 0 || dh <= 0 || dw > 2048 || dh > 2048) return;
    for (let r = 0; r < dh; r++) {
      const lut = (r & 1) ? LUT_D_JS : LUT_B_JS;
      const p = data.add((y0 + r) * pitch + x0);
      const ab = p.readByteArray(dw);
      const row = new Uint8Array(ab);
      let changed = false;
      for (let i = 0; i < dw; i++) {
        const v = lut[row[i]];
        if (v !== row[i]) { row[i] = v; changed = true; }
      }
      if (changed) p.writeByteArray(ab);
    }
  }
  // v22/v23: parity-forced re-blit — dither regeneration for the council
  // portrait/logo enlarges (our own stubPortrait/stubLogo levers introduced
  // the enlarge with no regeneration tail; a banded result is a defect by
  // definition).  Per-faction art has per-faction palettes, so no fixed
  // pair LUT can cover it.  Instead: redraw every dest row from the SOURCE
  // using the engine's centre-aligned NN column map, and pick rows via
  // centre-NN at PAIR granularity with dest parity choosing bright/dark
  // within the pair.  Source scanline pairs are two shadings of the same
  // image row, so the parity swap costs nothing; solid regions are parity-
  // invariant; the result is strict single-pixel alternation at device
  // density.  Keyed pixels (src==key) are skipped so the background
  // survives.  g<=16 is a native no-op (armReblit gates num>den).
  // o = {sData, sPitch, srcX, srcY, sw, sh, dest(Buffer*), key, x0, y0,
  //      dw, dh, num, den}
  function parityReblit(o) {
    const sData = o.sData, sPitch = o.sPitch;
    const dData = o.dest.add(0x54).readPointer();
    const dPitch = o.dest.add(0x4A8).readS32();
    if (sData.isNull() || sPitch <= 0 || dData.isNull() || dPitch <= 0) return;
    const dW = o.dest.add(0x80).readS32(), dH = Math.abs(o.dest.add(0x84).readS32());
    if (o.dw <= 0 || o.dh <= 0 || o.dw > 2048 || o.dh > 2048) return;
    const rows = new Array(o.sh);
    const rowAt = (r) => rows[r] || (rows[r] = new Uint8Array(
      sData.add((o.srcY + r) * sPitch + o.srcX).readByteArray(o.sw)));
    // centre-aligned NN maps (the MEASURED engine map — never floor(i*sw/dw))
    const mapC = o.num ? ((i) => Math.floor(((2 * i + 1) * o.den) / (2 * o.num)))
                       : ((i) => Math.floor(((2 * i + 1) * o.sw) / (2 * o.dw)));
    const colMap = new Int32Array(o.dw);
    for (let i = 0; i < o.dw; i++) {
      const sx = mapC(i);
      colMap[i] = sx < 0 ? 0 : (sx >= o.sw ? o.sw - 1 : sx);
    }
    // Row selection: centre-NN at PAIR granularity, then dest parity picks
    // bright/dark within the pair — parity-strict, pair-monotone, full
    // coverage, <=1 native-pair positional error (simulated g=17/22/25/40).
    const pMax = (o.sh - 1) >> 1;
    for (let jj = 0; jj < o.dh; jj++) {
      const dy = o.y0 + jj;
      if (dy < 0 || dy >= dH) continue;
      let p = o.num ? Math.floor(((2 * jj + 1) * o.den) / (4 * o.num))
                    : Math.floor(((2 * jj + 1) * o.sh) / (4 * o.dh));
      if (p < 0) p = 0; else if (p > pMax) p = pMax;
      let r = 2 * p + (jj & 1);
      if (r >= o.sh) r = o.sh - 1;
      const srow = rowAt(r);
      let iw = o.dw;
      if (o.x0 + iw > dW) iw = dW - o.x0;
      if (iw <= 0) continue;
      const dp0 = dData.add(dy * dPitch + o.x0);
      const ab = dp0.readByteArray(iw);
      const drow = new Uint8Array(ab);
      let changed = false;
      for (let i = 0; i < iw; i++) {
        const v = srow[colMap[i]];
        if (v === o.key) continue;
        if (drow[i] !== v) { drow[i] = v; changed = true; }
      }
      if (changed) dp0.writeByteArray(ab);
    }
  }
  // v23: attach at OUR stub's entry.  The stub is CALLed from the council
  // column painter and tail-jumps into sd2, so Frida's onLeave fires when
  // sd2 returns = right after the pcBits blit (Sprite_blit_scaled_core's own
  // pixel loop — no downstream Buffer_* primitive exists to intercept).
  // onEnter captures the caller's args (thiscall: ecx=sprite; [esp+4]=dest
  // Buffer*, +8 key, +0xC x, +0x10 y) and replicates the stub's own x shift
  // for the logo; the dest rect is COMPUTED (x+dp(off_x), y+dp(off_y),
  // ceil(blit_w*g/16)) AND MEASURED (diff of a dest snapshot around it) —
  // the measured bbox is logged against the computed rect so the rect law
  // is verified, not modelled.
  // v28: the snapshot/measure pair (armReblit's inline version, lifted so the
  // popup-art tail at SD_THUNK measures the engine rect the same way).
  function rbSnapshot(dest, x0, y0, dw, dh) {
    const dData = dest.add(0x54).readPointer(), dPitch = dest.add(0x4A8).readS32();
    const dW = dest.add(0x80).readS32(), dH = Math.abs(dest.add(0x84).readS32());
    const M = 4;
    const sx0 = Math.max(0, x0 - M), sy0 = Math.max(0, y0 - M);
    const sx1 = Math.min(dW, x0 + dw + M), sy1 = Math.min(dH, y0 + dh + M);
    if (dData.isNull() || dPitch <= 0 || sx1 <= sx0 || sy1 <= sy0 || (sy1 - sy0) > 600) return null;
    const snap = [];
    for (let yy = sy0; yy < sy1; yy++)
      snap.push(new Uint8Array(dData.add(yy * dPitch + sx0).readByteArray(sx1 - sx0)));
    return { snap, sx0, sy0, sx1, sy1, dData, dPitch };
  }
  function rbMeasure(s) {
    let bx0 = 1e9, by0 = 1e9, bx1 = -1, by1 = -1;
    for (let yy = s.sy0; yy < s.sy1; yy++) {
      const now = new Uint8Array(s.dData.add(yy * s.dPitch + s.sx0).readByteArray(s.sx1 - s.sx0));
      const was = s.snap[yy - s.sy0];
      for (let i = 0; i < now.length; i++) {
        if (now[i] !== was[i]) {
          const xx = s.sx0 + i;
          if (xx < bx0) bx0 = xx; if (xx > bx1) bx1 = xx;
          if (yy < by0) by0 = yy; if (yy > by1) by1 = yy;
        }
      }
    }
    return bx1 < 0 ? { x: 0, y: 0, w: 0, h: 0 } : { x: bx0, y: by0, w: bx1 - bx0 + 1, h: by1 - by0 + 1 };
  }
  function armReblit(stubAddr, label, isLogo) {
    if (!stubAddr) return;
    try {
      Interceptor.attach(ptr(stubAddr), {
        onEnter(args) {
          this.rb = null;
          try {
            const g = VA(0x00668740).readS32();
            if (g <= 16) return;
            const spr = ptr(this.context.ecx.toUInt32());
            const esp = this.context.esp;
            const dest = esp.add(4).readPointer();
            const key = esp.add(8).readS32();
            let x = esp.add(0xC).readS32();
            const y = esp.add(0x10).readS32();
            const sData = spr.add(4).readPointer();
            if (sData.isNull()) { L("reblit", label + " pcBits NULL"); return; }
            const sPitch = spr.add(0xC).readS32();
            const bw = spr.add(0x10).readS32(), bh = spr.add(0x14).readS32();
            const cw = spr.add(0x18).readS32(), ch = spr.add(0x1C).readS32();
            const offx = spr.add(0x20).readS32(), offy = spr.add(0x24).readS32();
            if (bw <= 0 || bh <= 0 || bw > 400 || bh > 400 || sPitch < bw) return;
            if (isLogo) x += Math.floor((cw - ((cw * g) >> 4)) / 2);   // stubLogo's recenter
            const x0 = x + Math.floor(offx * g / 16), y0 = y + Math.floor(offy * g / 16);
            const dw = Math.ceil(bw * g / 16), dh = Math.ceil(bh * g / 16);
            this.rb = { sData, sPitch, srcX: 0, srcY: 0, sw: bw, sh: bh, dest, key,
                        x0, y0, dw, dh, num: g, den: 16 };
            // snapshot a margin around the computed rect for the measured bbox
            const dData = dest.add(0x54).readPointer(), dPitch = dest.add(0x4A8).readS32();
            const dW = dest.add(0x80).readS32(), dH = Math.abs(dest.add(0x84).readS32());
            const M = 4;
            const sx0 = Math.max(0, x0 - M), sy0 = Math.max(0, y0 - M);
            const sx1 = Math.min(dW, x0 + dw + M), sy1 = Math.min(dH, y0 + dh + M);
            if (!dData.isNull() && dPitch > 0 && sx1 > sx0 && sy1 > sy0 && (sy1 - sy0) <= 600) {
              const snap = [];
              for (let yy = sy0; yy < sy1; yy++)
                snap.push(new Uint8Array(dData.add(yy * dPitch + sx0).readByteArray(sx1 - sx0)));
              this.snap = { snap, sx0, sy0, sx1, sy1, dData, dPitch };
            }
            L("reblit", label + " spr=" + spr + " blit=" + bw + "x" + bh + " canvas=" + cw + "x" + ch +
              " off=" + offx + "," + offy + " pitch=" + sPitch + " key=" + key +
              " -> computed rect " + x0 + "," + y0 + " " + dw + "x" + dh + " g=" + g, 16);
          } catch (e) { L("reblit", label + " onEnter err " + e); this.rb = null; }
        },
        onLeave() {
          if (!this.rb) return;
          try {
            if (this.snap) {
              const s = this.snap;
              let bx0 = 1e9, by0 = 1e9, bx1 = -1, by1 = -1;
              for (let yy = s.sy0; yy < s.sy1; yy++) {
                const now = new Uint8Array(s.dData.add(yy * s.dPitch + s.sx0).readByteArray(s.sx1 - s.sx0));
                const was = s.snap[yy - s.sy0];
                for (let i = 0; i < now.length; i++) {
                  if (now[i] !== was[i]) {
                    const xx = s.sx0 + i;
                    if (xx < bx0) bx0 = xx; if (xx > bx1) bx1 = xx;
                    if (yy < by0) by0 = yy; if (yy > by1) by1 = yy;
                  }
                }
              }
              const r = this.rb;
              L("reblit-measure", label + " computed " + r.x0 + "," + r.y0 + " " + r.dw + "x" + r.dh +
                (bx1 < 0 ? " measured: NO CHANGE (dest already held it)"
                         : " measured " + bx0 + "," + by0 + " " + (bx1 - bx0 + 1) + "x" + (by1 - by0 + 1)), 16);
            }
            parityReblit(this.rb);
          } catch (e) { L("reblit", label + " onLeave err " + e); }
        }
      });
      L("stub", label + " parity-reblit tail attached @0x" + stubAddr.toString(16));
    } catch (e) { L("stub", label + " parity-reblit attach FAIL: " + e); }
  }
  let btN = 0;
  Interceptor.attach(VA(0x005D84C0), {   // Buffer_draw_2
    onEnter(args) {
      this.hit = false;
      const src = ptr(this.context.ecx.toUInt32());
      let w = 0, h = 0;
      try { w = src.add(0x80).readS32(); h = Math.abs(src.add(0x84).readS32()); } catch (e) { return; }
      if (w !== 200 || h !== 120) return;
      const num = args[4].toInt32(), den = args[5].toInt32();
      const isFlag = bufIsFlag(src);
      if (btN < 12) {
        btN++;
        log("[bt-draw2] src=" + src + " flag=" + isFlag + " dest=" + args[0] +
            " key=" + args[1].toInt32() + " X=" + args[2].toInt32() +
            " Y=" + args[3].toInt32() + " num/den=" + num + "/" + den +
            "\n  " + btStr(this.context));
      }
      if (isFlag && num > den) {
        this.hit = true;
        this.dest = args[0];
        this.x0 = args[2].toInt32();
        this.y0 = args[3].toInt32();
        this.dw = Math.ceil(200 * num / den);
        this.dh = Math.ceil(120 * num / den);
      }
    },
    onLeave() {
      if (!this.hit) return;
      try { restripeRect(this.dest, this.x0, this.y0, this.dw, this.dh); }
      catch (e) { L("bt", "draw2 restripe err " + e); }
    }
  });
  Interceptor.attach(VA(0x005D9610), {   // Buffer_copy_3 (StretchBlt)
    onEnter(args) {
      this.hit = false;
      const srcW = args[3].toInt32(), srcH = args[4].toInt32();
      if (srcW !== 200 || Math.abs(srcH) !== 120) return;
      const src = ptr(this.context.ecx.toUInt32());
      const isFlag = bufIsFlag(src);
      const dstW = args[7].toInt32(), dstH = args[8].toInt32();
      if (btN < 12) {
        btN++;
        log("[bt-copy3] src=" + src + " flag=" + isFlag + " dst=" + args[0] +
            " srcXY=" + args[1].toInt32() + "," + args[2].toInt32() +
            " dstXY=" + args[5].toInt32() + "," + args[6].toInt32() +
            " dstWH=" + dstW + "x" + dstH + "\n  " + btStr(this.context));
      }
      if (isFlag && dstW > srcW) {
        this.hit = true;
        this.dest = args[0];
        this.x0 = args[5].toInt32();
        this.y0 = args[6].toInt32();
        this.dw = dstW;
        this.dh = Math.abs(dstH);
      }
    },
    onLeave() {
      if (!this.hit) return;
      try { restripeRect(this.dest, this.x0, this.y0, this.dw, this.dh); }
      catch (e) { L("bt", "copy3 restripe err " + e); }
    }
  });
  Interceptor.attach(VA(0x005D7DE0), {   // Buffer_load_pcx
    onEnter(args) {
      try {
        const nm = args[0].isNull() ? "" : (args[0].readAnsiString() || "");
        if (nm.toLowerCase().indexOf("council_sm") < 0 &&
            nm.toLowerCase().indexOf("space_sm") < 0) return;
        L("bt-load", "load_pcx name=" + nm + " self=0x" +
          this.context.ecx.toUInt32().toString(16) + "\n  " + btStr(this.context), 8);
      } catch (e) {}
    }
  });

  // ---- v24 PROBE (observe-only, zero behaviour change): the council "talk"
  // popups vs the pristine refs (refs\pristine\Council\WhoToVote.png /
  // DiploBribe.png, 2026-08-22).  Pixel-measured defects @g25:
  //   WhoToVote (player's own faction, NO visible portrait): body text
  //     starts ~225 NATIVE px right of the field-box left (pristine: flush,
  //     ~3.5) and overruns the box's right stroke — a phantom art column.
  //     The run-23 log shows [+0x2144]!=0 with an EMPTY sprite name for it
  //     and an empty-name draw at (21,63) — so the engine/our thunks size a
  //     column from a portrait-less sprite ([eax+0x18] canvas_w @0x404B66).
  //   DiploBribe (Gaian portrait): portrait drawn ~4 native LEFT of the
  //     title-band stroke (pristine: frame flush, +0.4) and ~5 native HIGH;
  //     text-field frame ~11 native left / ~4 native high of the pristine
  //     band-anchored relation; rows/OK are lawful (174 vs 176 native under
  //     the band) — i.e. NEITHER popup_art_align's x/y law NOR fieldpads'
  //     band-anchored T fired for this popup (key unarmed, or consumed).
  // Measure, don't model: three ENTRY-ONLY attaches (each swept: no yaml
  // site, no LE-token hit in any new_bytes, not in pracx.cpp, not on the
  // forbidden list; 0x404B10 = the hook_council_width.js precedent; t_dp_
  // artalign is OUR cave fn reached only via `call [esi+0x3168]`; Buffer_
  // write_strings is reached by thunk_faction_textmargin's TAIL-JMP so
  // [esp]=0x604dfa at entry exactly like vanilla).
  const PCAVE2 = 0x00A0C000;
  const G_BAND_LEFT = PCAVE2 + 0x2700, G_FIELD_ANCHOR = PCAVE2 + 0x2704,
        G_BAND_POPUP = PCAVE2 + 0x2708, G_BAND_BOTTOM = PCAVE2 + 0x270C;
  const bandState = () => {
    try {
      return "bandKey=0x" + VA(G_BAND_POPUP).readU32().toString(16) +
             " bandL=" + VA(G_BAND_LEFT).readS32() +
             " bandB=" + VA(G_BAND_BOTTOM).readS32() +
             " fieldT=" + VA(G_FIELD_ANCHOR).readS32();
    } catch (e) { return "bandState err " + e; }
  };
  const popTitle = (p) => {
    try { const t = ptr(p).add(0xa48).readPointer(); return t.isNull() ? "" : (t.readAnsiString() || ""); }
    catch (e) { return "?"; }
  };
  const sprDesc = (sp) => {
    if (!sp) return "art=0";
    const s = ptr(sp);
    try {
      const nmP = s.readPointer();
      const nm = nmP.isNull() ? "" : (nmP.readAnsiString() || "");
      return "art=0x" + sp.toString(16) + "('" + nm + "' pcBits=0x" + s.add(4).readU32().toString(16) +
             " key=" + s.add(8).readS32() + " pitch=" + s.add(0xc).readS32() +
             " blit=" + s.add(0x10).readS32() + "x" + s.add(0x14).readS32() +
             " canvas=" + s.add(0x18).readS32() + "x" + s.add(0x1c).readS32() +
             " off=" + s.add(0x20).readS32() + "," + s.add(0x24).readS32() + ")";
    } catch (e) { return "art=0x" + sp.toString(16) + "(unreadable)"; }
  };
  const popFields = (p) => {
    let dlg = "";
    try { const iv3 = rd(rd(p, 0x21D0), 8); dlg = " xs21FC=" + rd(p, iv3 + 0x21FC) + " d5c222C=" + rd(p, iv3 + 0x222C); } catch (e) { dlg = " dlg=?"; }
    return "30D8=" + rd(p, 0x30D8) + " 30E0=" + rd(p, 0x30E0) + " 30E4=" + rd(p, 0x30E4) +
           " 30E8=" + rd(p, 0x30E8) + " 30F0=" + rd(p, 0x30F0) + " 30F4=" + rd(p, 0x30F4) +
           " 21C8=" + rd(p, 0x21C8) + " 21CC=" + rd(p, 0x21CC) +
           " box=" + rd(p, 0x30BC) + "x" + rd(p, 0x30C0) + " contentH=" + rd(p, 0x30D4) +
           " ratio=" + rd(p, 0x3104) + "/" + rd(p, 0x3108) + dlg +
           " a14=0x" + (rd(p, 0xa14) >>> 0).toString(16) + " a3c=0x" + (rd(p, 0xa3c) >>> 0).toString(16) +
           " type2350=" + rd(p, 0x2350) + " [3168]=0x" + (rd(p, 0x3168) >>> 0).toString(16);
  };
  // (1) Popup_calculate_dimensions 0x404B10 (fastcall ecx=popup): the art
  //     column [+0x30d8] and the sprite it was sized from, after BOTH
  //     BasePop_calc passes.
  Interceptor.attach(VA(0x00404B10), {
    onEnter() { this.p = this.context.ecx.toUInt32(); },
    onLeave() {
      const p = this.p; if (!p) return;
      try {
        L("probe-calc", "pop=0x" + p.toString(16) + " '" + popTitle(p) + "' " +
          sprDesc(rd(p, 0x2144) >>> 0) + " " + popFields(p) + " g=" + g(), 40);
      } catch (e) { L("probe-calc", "err " + e, 8); }
    }
  });
  // ---- v25 FIXES (laws scaling_laws.popup_textfollow_applies /
  //      popup_art_x; run-24 verdicts) --------------------------------------
  //  A  thunk_pf_textfollow (pcave2+0x2090) overrides body-text X with
  //     g_d528_left+ps3 for every titled art-less popup, but g_d528_left is
  //     refreshed ONLY by thunk_pf_frame_align, which v8-gates on FLAT/SLIDE
  //     — the ornate University popup drew at the PD popup's stale 368+4.
  //     Proto fix = the SAME gate: for ornate (raw [+0x30ac] 2/6 band) &&
  //     no art && self-parent, swap g->16 at the thunk's entry so its own
  //     g>16 gate falls through (engine X untouched), and restore g at
  //     Buffer_write_strings entry (the thunk's single exit, push/ret —
  //     straight-line code in between, nothing else reads g).  Bake shape =
  //     add the popup_frame_rewrite_applies band test to textfollow.
  //  B  thunk_popup_artalign x = g_band_left + 5 + (g>>4) anchors to the
  //     band rect stashed @0x40603D — but thunk_pf_title_stash's ornate arm
  //     shifts that rect l/t/r by ornate_title_inset_delta(g) AFTER the
  //     stash (run 24 @g25: bandL 15, art drawn 16, stroke 22-23 = 15+7).
  //     Proto fix = add the delta to g_band_left at t_dp_artalign entry
  //     when the key is armed for this (ornate) popup; the thunk consumes
  //     the key + value in this very call.  y unchanged (law verified:
  //     fieldT 62 -> drawn 57 = measured).  Bake shape = ornate arm in
  //     thunk_popup_artalign.
  //  B-y (OPEN): ornate band bottom piece overhang -> fieldpads band-
  //     anchored T leaves a zero channel; needs the g=16 measurement
  //     (title-stash + fieldpads probes below) before a law is written.
  const ornateType = (p) => { try { const t = ptr(p).add(0x30ac).readU32(); return (t >= 20000 && t < 30000) || (t >= 60000 && t < 70000); } catch (e) { return false; } };
  const ornDelta = (s) => s <= 16 ? 0 : ((13 * s) >> 4) - 13;   // scaling_laws.ornate_title_inset_delta
  let tfSwap = { on: false, g: 0 };
  let bandPre = { pop: 0, l: 0, r: 0 };   // v27: the ornate band rect PRE-shift, per popup (title_stash entry)
  const tfRestore = (where) => {
    if (!tfSwap.on) return;
    VA(A_G).writeU32(tfSwap.g); tfSwap.on = false;
    L("fixA", "g restored=" + tfSwap.g + " at " + where, 40);
  };
  // (2) t_dp_artalign 0xA1E6E8 (the [popup+0x3168] chain head; cdecl args
  //     sprite/[esp+4] win/[esp+8] res/[esp+0xC] x/[esp+0x10] y/[esp+0x14]):
  //     the band key + anchors BEFORE artalign consumes them, and the
  //     engine's own x/y seeds.  The final drawn x/y lands in [sdcensus].
  //     v25: + fix B (ornate inset delta onto g_band_left).
  Interceptor.attach(VA(T_DP_ARTALIGN), {
    onEnter() {
      try {
        const sp = this.context.esp;
        const pop = VA(0x9B8CF4).readU32();
        const win = sp.add(8).readU32();
        L("probe-art", "pop=0x" + pop.toString(16) + " '" + popTitle(pop) + "' win=0x" + win.toString(16) +
          " seeds x=" + sp.add(0x10).readS32() + " y=" + sp.add(0x14).readS32() +
          " res=" + sp.add(0xC).readS32() + " " + sprDesc(sp.add(4).readU32()) + " " + bandState() +
          (pop ? " 30F0=" + rd(pop, 0x30F0) + " 30E0=" + rd(pop, 0x30E0) + " 30E8=" + rd(pop, 0x30E8) + " 21C8=" + rd(pop, 0x21C8) : "") +
          " g=" + g(), 40);
        const s = g();
        if (s > 16 && win && VA(G_BAND_POPUP).readU32() === win && ornateType(win)) {
          const d = ornDelta(s), bl = VA(G_BAND_LEFT).readS32();
          VA(G_BAND_LEFT).writeS32(bl + d);
          L("fixB", "ornate popup 0x" + win.toString(16) + " '" + popTitle(win) + "': g_band_left " + bl + " -> " + (bl + d) +
            " (delta " + d + ") => art x seed " + (bl + d + 5 + (s >> 4)) + " drawn " + (bl + d + (s >> 4)), 40);
        }
      } catch (e) { L("probe-art", "err " + e, 8); }
    }
  });
  // (2b) fix A (the textfollow ornate bypass) RETIRED 2026-10-11: it attached at pcave2+0x2090, the v1/v2
  //      textfollow slot (now zeros), and forced g=16 so the thunk skipped ornate popups.  The baked
  //      thunk_pf_textfollow v3 (pcave2+0x308A0, src assemble_pf_align.py) gates ornate popups itself and
  //      follows frame_align v9's moved text box (laws ornate_textfollow_applies / ornate_text_x); forcing
  //      g=16 under this trace would undo that.  No attach here any more.
  // (2c) B-y PROBES: the ornate band rect as handed to the title draw
  //      (thunk_pf_title_stash entry, E8 @0x406048: [esp+4]=rect pre-shift,
  //      esi=popup) and fieldpads' inputs/outputs (thunk_popup_fieldpads
  //      entry, E8 @0x40612F: ebx=engine field-T source, edi=L src, ecx=R
  //      src; outputs [ebp-0x30]=T [ebp-0x34]=L [ebp-0x2c]=R on the caller's
  //      frame).  At g=16 these are the NATIVE rects -> the overhang law.
  Interceptor.attach(VA(PCAVE2 + 0xF18), {
    onEnter() {
      try {
        const p = this.context.esi.toUInt32();
        const r = this.context.esp.add(4).readPointer();
        bandPre = { pop: p, l: r.readS32(), r: r.add(8).readS32() };
        L("probe-band", "pop=0x" + p.toString(16) + " '" + popTitle(p) + "' ornate=" + ornateType(p) +
          " rect=" + rect4(r) + " (pre-shift; ornate draws l/t +" + ornDelta(g()) + ", r -" + ornDelta(g()) + ") " + bandState() + " g=" + g(), 40);
      } catch (e) { L("probe-band", "err " + e, 8); }
    }
  });
  //  v26 FIX B-y (law scaling_laws.popup_field_top): fieldpads' band-
  //  anchored arm (T = B + 2(ps3+Delta)) is gated on esi==g_band_popup only;
  //  for the ORNATE family the band's bottom piece draws ~3px lower and the
  //  engine's T source [30e8] is already scaled, so the arm produced a
  //  ZERO channel (run 25 pixels: stroke rows 423-426, field/portrait top
  //  427).  Proto fix = hide the key from fieldpads (zero g_band_popup for
  //  the duration of the call, restore in onLeave — artalign still needs
  //  it) so the default arm T = ebx - ps3 runs.  Bake shape = the
  //  popup_frame_rewrite_applies band test in fieldpads' keyed arm.
  Interceptor.attach(VA(PCAVE2 + 0x4550), {
    onEnter() {
      this.hid = false;
      try {
        const c = this.context;
        this.p = c.esi.toUInt32(); this.bp = c.ebp;
        this.in = "ebx(Tsrc)=" + c.ebx.toInt32() + " edi(Lsrc)=" + c.edi.toInt32() + " ecx(Rsrc)=" + c.ecx.toInt32();
        if (g() > 16 && this.p && ornateType(this.p) && VA(G_BAND_POPUP).readU32() === this.p) {
          VA(G_BAND_POPUP).writeU32(0); this.hid = true;
        }
        // v27 FIX C (law scaling_laws.popup_field_right_src_ornate): the
        // engine's ornate `sub ecx,9` @0x40612c stays NATIVE on top of the
        // scaled -10 (thunk_popup_fieldR), so the field/union/list-row right
        // edges sit 6px past the band strokes @g25.  Vanilla: field R ==
        // band INNER, union == band OUTER (both sides).  Rewrite ecx (R src)
        // in-register: R' = bandPreR - ornDelta (the drawn band), field R =
        // R' - ps3 + Delta (band inner, thick-grown; field draws flat),
        // ecx = field R - ps3.  L (edi) untouched: the engine's [30f0]
        // term lands on the inner stroke already.  Bake shape = ornate arm
        // in thunk_popup_fieldpads reading the title stash.
        this.fixC = "";
        if (g() > 16 && this.p && ornateType(this.p) && bandPre.pop === this.p) {
          const s = g(), ps3 = (3 * s) >> 4, Delta = (s - 16) >> 3;
          const rDrawn = bandPre.r - ornDelta(s);
          const want = rDrawn - 2 * ps3 + Delta;
          const was = c.ecx.toInt32();
          c.ecx = ptr(want);
          this.fixC = " [fixC: Rsrc " + was + " -> " + want + " (band pre R " + bandPre.r + " drawn R' " + rDrawn +
            ") => field R " + (want + ps3) + " union R " + (want + 2 * ps3) + "]";
        }
      } catch (e) { this.in = "err " + e; }
    },
    onLeave() {
      try {
        if (this.hid) VA(G_BAND_POPUP).writeU32(this.p);
        const bp = this.bp;
        L("probe-field", "pop=0x" + this.p.toString(16) + " '" + popTitle(this.p) + "' ornate=" + ornateType(this.p) +
          (this.hid ? " [fixBy: band arm bypassed]" : "") + (this.fixC || "") +
          " " + this.in + " -> T=" + bp.sub(0x30).readS32() + " L=" + bp.sub(0x34).readS32() + " R=" + bp.sub(0x2c).readS32() +
          " " + bandState() + " g=" + g(), 40);
      } catch (e) { L("probe-field", "err " + e, 8); }
    }
  });
  // (2d) v26 PROBE: the body OUTER-UNION d5a0 rect as handed to the final
  //      draw (thunk_content_frame entry 0x668BD0 = menu_strip_thunks+0x9D0,
  //      E8 @0x406238 — the lever-V stubStrokeB tail-jmps here too;
  //      [esp+4]=rect, esi=popup).  Run-25 shot A: the University popup's
  //      union stroke sits 2px LEFT of the band stroke (277 vs 279);
  //      pristine WhoToVote has them flush.
  Interceptor.attach(VA(0x00668BD0), {
    onEnter() {
      try {
        const p = this.context.esi.toUInt32();
        const r = this.context.esp.add(4).readPointer();
        L("probe-union", "pop=0x" + p.toString(16) + " '" + popTitle(p) + "' ornate=" + ornateType(p) +
          " rect=" + rect4(r) + " 30D4=" + rd(p, 0x30D4) + " 2350=" + rd(p, 0x2350) + " " + bandState() +
          " fieldL/R=" + VA(PCAVE2 + 0x44BC).readS32() + "/" + VA(PCAVE2 + 0x44C0).readS32() + " g=" + g(), 40);
      } catch (e) { L("probe-union", "err " + e, 8); }
    }
  });
  // (3) Buffer_write_strings 0x5DB040 (popup BODY text; [esp+4]=strings,
  //     [esp+8]=X, [esp+0xC]=Y, [esp+0x10]=width; ecx=dest Buffer): the
  //     rendered text X = [30e0]+[30f0]+[21c8]+[30d8] per terranx.h.
  //     v25: restores the fix-A g swap first.
  Interceptor.attach(VA(0x005DB040), {
    onEnter() {
      tfRestore("write_strings");
      try {
        const sp = this.context.esp;
        const pop = VA(0x9B8CF4).readU32();
        let s0 = "";
        try { const lst = sp.add(4).readPointer(); const s = lst.readPointer(); s0 = s.isNull() ? "" : (s.readAnsiString() || ""); } catch (e) { s0 = "?"; }
        L("probe-text", "pop=0x" + pop.toString(16) + " '" + popTitle(pop) + "' ret=0x" + sp.readU32().toString(16) +
          " X=" + sp.add(8).readS32() + " Y=" + sp.add(0xC).readS32() + " W=" + sp.add(0x10).readS32() +
          " dest=0x" + this.context.ecx.toUInt32().toString(16) +
          (pop ? " " + popFields(pop) : "") + " " + bandState() + " '" + s0.slice(0, 40) + "'", 40);
      } catch (e) { L("probe-text", "err " + e, 8); }
    }
  });
  L("probe", "v25 talk-popup probes + fixes armed (calc 0x404B10 / artalign 0x" + T_DP_ARTALIGN.toString(16) +
    " [fixB] / title_stash 0x" + (PCAVE2 + 0xF18).toString(16) +
    " / fieldpads 0x" + (PCAVE2 + 0x4550).toString(16) + " / write_strings 0x5DB040)");

  log("hooks armed (levers S,I,B,P,T,G,V,F + v16 diag + v21 blit trace + v23 stub-entry parity-reblit + v25-v28 talk-popup fixes A/B/B-y/C/D [D = popup portrait parity-reblit] + union probe). " + env());
}
