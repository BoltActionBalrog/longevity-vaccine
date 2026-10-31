// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// v44 = v43 + the two KEYED-MODE pixel handlers as detectors. v43's census
// solved it: file stream ALIVE (all freads ret=1), frame 0 dispatches
// 0xF1FA/2 -> COLOR_256 -> BYTE_RUN, and a BRUN decoder visibly ran (the
// 745x 1-byte packet-count freads) — but NOT 0x62A500. Flic flags bit1
// (+0x5B4) is not a "draw once" marker: it is the KEYED/TRANSPARENT
// decode mode (why the flic keeps a canvas bg patch), and turn.flc runs
// with it SET, so sub-chunks dispatch through the keyed table @0x62AEF0
// (byte map @0x62AF08), not the direct table v42 instrumented:
//   type 7  -> stub 0x62AD6E -> 0x62B190 keyed SS2      (NEW detector)
//   type 13 -> 0x62AD86 gated canvas->dst bg restore    (blit det. ✓ had)
//   type 15 -> stub 0x62AD7A -> 0x62AF40 keyed BYTE_RUN (NEW detector —
//              the actual frame-0 banner painter)
//   type 16 -> stub 0x62ADF7 -> 0x62B670 keyed COPY     (kcopy det. ✓ had)
// Both new targets: clean prologues, plain-E8 stubs (mov ecx,esi; call),
// PRACX greps clean. v42's direct-table detectors kept (harmless).
// ----------------------------------------------------------------------
// v43 = v42 + decode-level GROUND-TRUTH probes after v42 STILL showed no
// banner and STILL zero paint detectors fired ("SKIP (no paint) gate=0
// rv=0" on every static refresh). Static analysis is now EXHAUSTED and
// every link checks out (turn.flc frame 0 = COLOR_256+BYTE_RUN parsed
// from disk; Flic_rewind seeks the frame-0 offset [+0xA64] and zeroes
// frameIdx; the bit1-clear sub-chunk dispatch maps type 15 -> 0x62AE30 ->
// E8 0x62A500; 0x62A500's prologue is clean with that single E8 caller)
// — so the failure is RUNTIME state. Prime suspect: the flic's FILE
// stream (+0x5B8) is dead/misplaced in-game, so the 16-byte header fread
// @0x62A0F9 and the 6-byte sub-header freads return garbage -> everything
// falls to the ja/skip-fseek path -> engine paints nothing on the static
// refreshes; the natively-visible banner would then be PERSISTENT pixels
// from one earlier successful draw that v41/v42's bounce redirected into
// the scratch and dropped... except no successful draw logged all session.
// [TB2]/[TB3] decide it:
//   [TB2] Flic_decode_chunk 0x62ACD0 fn-entry, ecx==turn flic: logs the
//         chunk hdr type word[+4] + count word[+6] (frame vs sub level,
//         garbage shows immediately). Cap 24.
//   [TB3] CRT fread 0x646178 fn-entry+leave, gated file arg ==
//         [flic+0x5B8] while inside a bounced draw: logs size*count and
//         the RETURN (items read; 0 = dead stream). Cap 30.
//   [TB]  SKIP/draw lines now append file=+0x5B8 idx=+0xA10 cnt=+0xA1A
//         o64/o68 seek anchors — a null/odd FILE* is visible at a glance.
// ----------------------------------------------------------------------
// v42 = v41 with COMPLETE paint-detector coverage after v41 dropped the
// banner entirely (user: band gone, TURN COMPLETE text still there — the
// text is banner_refresh's own Buffer write, independent of the flic).
// v41 RUN GROUND TRUTH (4K, g=40): armed ✓, canvas recapture ✓, then
// "[TB] band draw SKIP (no paint) ret=0x45c4cc gate=0 rv=0" on every
// static refresh — yet the UNHOOKED engine paints the banner on those
// same gate=0 draws. ⇒ v41's core assumption was WRONG: decoded frames
// do NOT go through the canvas. The pixel chunk handlers write dst
// DIRECTLY (ungated); the canvas only ever holds the Flic_init bg patch,
// and the gated canvas->dst blit @0x62ADED is a BACKGROUND RESTORE
// (erase band to bg), not the frame painter. Frame 0 paints via the
// BYTE_RUN handler, which v41 had no detector for -> banner composed
// into the scratch and the mirror skipped the stretch.
// FULL pixel-writer census (sub-chunk dispatch @0x62AF18 via byte map
// @0x62AF30, chunk types 4..18; frame-level table @0x62AEF0):
//   covered in v41:  canvas->dst bg-restore blit (copy_4 ret 0x62ADF2),
//                    0x62B670 keyed direct-write (frame-level slot 4),
//                    Buffer_fill 0x5D8240 (type 13 BLACK @0x62AE91)
//   ADDED in v42:    0x62A500 type 15 BYTE_RUN (E8 @0x62AE32) — frame 0!
//                    0x62A720 type 7  SS2 delta (E8 @0x62AE26)
//                    0x62AB80 type 16 COPY     (E8 @0x62AE9A)
//   no pixels:       0x62AEA1 skip/fseek (types 4,11,12,18 + unknowns)
// All three new detectors: fn-entry at plain-E8 thiscall(ecx=flic)
// targets, gated ecx==turn flic; PRACX grepped clean. [TB] lines now tag
// WHICH detectors fired (census while verifying).
// ----------------------------------------------------------------------
// v41 = v40 with three fixes after v40 DIED AT LOAD (log tell: "started"
// logged but no "armed" line, no [TB], no [hb] — every lever below the S
// section, incl. S v4 itself, never installed; the band drew native):
//   FIX 1 (the killer): NativeFunction abi 'cdecl' is INVALID in Frida on
//     x86 — the ABI string for caller-cleans cdecl is 'mscdecl'. The throw
//     at construction aborted script load mid-file. LESSON: a missing
//     final "armed" log line = the script threw partway; wrap new lever
//     installs in try/catch that LOGS, so a partial build is visible.
//   FIX 2 (v21 lever-Y law — mirror the engine's DRAW DECISION): the
//     full-frame handler stores the dirty rect BEFORE the gate check
//     (0x62AD9E..B4 then cmp byte[esi],0 @0x62ADBA), so dirty fields are
//     no paint signal, and with the flash pref OFF the static path can
//     decode frame 0 with gate==0 = engine paints NOTHING. v40 stretched
//     on retval==0 alone -> would repaint stale scratch over intentional
//     clears at the ~9Hz banner_refresh cadence (lever-Y class). v41
//     stretches only when a PAINT DETECTOR fired during the bounced call:
//       (a) Buffer_copy_4 ret==0x62ADF2  = gated full-frame blit ran
//       (b) Flic_decode_delta 0x62B670 entry, ecx==turn flic (E8 @0x62ADF9)
//       (c) Buffer_fill 0x5D8240 entry while bounced (black-frame handler
//           E8s it; generic fn, gate on bounceActive first)
//     All three = fn-entry at plain-E8 targets, no site hooks in their
//     chains (hazard-audited; PRACX greps clean).
//   FIX 3: seed the scratch from the canvas bg patch at creation so a
//     first gate==0/delta cycle composes over sane content, and the
//     scratch is the band's persistent native framebuffer thereafter
//     (delta frames accumulate exactly like the engine's dst).
// v40 header (design + static decode) below, still accurate otherwise.
// ----------------------------------------------------------------------
// v40 = v35 (the levers-only baseline; deferred-click defect since CLOSED —
// PRACX scroll spin, prax.dll 7fd2e711) with lever S REPLACED: S v3 -> S v4,
// the TURN COMPLETE band fix (queue item 1).
// WHY S v3 was insufficient: it mirrored only the FULL-FRAME chunk blit
// (Buffer_copy_4 ret 0x62ADF2). The settled band = the last DELTA flash
// frame, and Flic_decode_delta (0x62B670) writes pixel runs DIRECTLY into
// dst [flic+0x5A8] at dstX/dstY (+0x5AC/+0x5B0), native 233x23 — no blit
// site to mirror; ditto the black-frame handler (Buffer_fill @0x62AE39).
// STATIC DECODE 2026-07-05 (all recorded in terranx.h):
//   - Flic_draw_frame 0x62A070 AND Flic_draw_frame_once 0x62A120 are
//     PARALLEL BODIES (not wrapper+impl): both store their x,y args ->
//     +0x5AC/+0x5B0 then run Flic_decode_chunk; EVERY chunk handler writes
//     via dst+those fields; keyed pixels read the canvas (+4) bg patch.
//   - Flic_advance/Flic_rewind only file-seek — no draw, no bypass.
//   - banner_refresh's anim branch args [MainWin+0x24AFC/+0x24B00] ARE
//     flic+0x5AC/+0x5B0 (0x7D331C/0x7D3320) — both branches pass the
//     stored (seed-scaled) band pos; no separate anim-coord fixup needed.
// S v4 DESIGN (dst-bounce; NO patches inside the flic core — the v18-20
// adjacency breakage + v27-32 soft-kill both lived there):
//   v4a: fix the canvas bg CONTENT. Flic_init's capture (copy_4 strip ->
//        canvas @ret 0x62A04B) grabs a native-SIZE 233x23 crop of the
//        SCALED band area = wrong content (left ~40% of the band). Redo it
//        as a copy_3 SHRINK of the full scaled band rect -> canvas. The
//        strip backdrop is itself native art x g/16, so the inverse-ratio
//        shrink + the final stretch round-trips ~losslessly.
//   v4b: fn-entry hooks on BOTH draw entries, gated this==0x7D2D70 && g>16:
//        onEnter repoint dst -> a native-size scratch Buffer (crt_malloc +
//        Buffer_ctor + Buffer_resize, the thunk_ensure_scratch recipe) and
//        zero the x,y args -> ALL chunk paths compose in the scratch;
//        onLeave restore dst + dstX/dstY, then ONE Buffer_copy_3 stretch
//        scratch -> strip at (realX, realY, w*g/16, h*g/16) + dirty-rect
//        fields (+0x58C..+0x598) set to the scaled rect. retval!=0 = decode
//        bailed -> restore only, no stretch.
// Frida safety: fn-entry attaches only (0x62A070 proven by v23's T12; both
// entries E8-called; neither in PRACX's _cx table — refs\pracx grepped);
// single listener on 0x5DFF00 (S v3's is removed, not stacked).
// All other levers byte-identical to v35. Verify needs the banner to
// CHANGE STATE in-game (end a turn) — idle screens never redraw it.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_hudfonts.log";
log("=== hook_hudframes44.js started ===");
installAVHandler("hudframes44");

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
  const SW_FONTS = new Set([0x8C6A98, 0x8C6AC0, 0x8C6AE8, 0x7AFD50]);
  const TICKER_FONT = 0x7AD2F8;
  const HUD_BUFS = new Set([0x7AEC64, 0x8C59AC]);
  const seen = new Set();
  let nA = 0, nB = 0, nC = 0, nE = 0, nF = 0, nG = 0, nH = 0, nJ = 0, nK = 0, logged = 0;
  function emit(key, line) {
    if (seen.has(key)) return;
    seen.add(key);
    if (++logged <= 450) log(line);
  }
  function hx(v) { return "0x" + (v >>> 0).toString(16); }
  function D(n, g) { return Math.floor(n * g / 16) - n; }

  // ================= levers (v8, silent) =================
  Interceptor.attach(VA(0x618F40), {
    onEnter() {
      const c = this.context, tgt = staticOf(c.ecx);
      if (!SW_FONTS.has(tgt) && tgt !== TICKER_FONT) return;
      const g = G();
      if (g <= 16) return;
      const szp = c.esp.add(8), nat = szp.readS32();
      if (nat > 16) return;
      szp.writeS32(Math.floor(nat * g / 16));
      if (tgt === TICKER_FONT) nF++; else nA++;
    }
  });
  const X11_RETS = new Set([0x4b84fd, 0x4b8350]);
  [0x5594F0, 0x55AF20].forEach(function (fn) {
    Interceptor.attach(VA(fn), {
      onEnter() {
        const c = this.context;
        const buf = staticOf(c.esp.add(4).readPointer());
        if (!HUD_BUFS.has(buf)) return;
        const ret = staticOf(this.returnAddress);
        const g = G();
        if (g > 16 && X11_RETS.has(ret)) {
          const xp = c.esp.add(0xC);
          xp.writeS32(xp.readS32() + D(11, g));
        }
        const sp = c.esp.add(0x14), s = sp.readS32();
        if (g > 16 && s <= 16 && s >= -16) {
          sp.writeS32(Math.floor((s + 16) * g / 16) - 16);
          nC++;
        }
      }
    });
  });
  Interceptor.attach(VA(0x5592D0), {
    onEnter() {
      const c = this.context;
      if (staticOf(c.esp.readPointer()) !== 0x559DEA) return;
      const buf = staticOf(c.ebp.add(8).readPointer());
      if (!HUD_BUFS.has(buf)) return;
      if (c.esp.add(4).readS32() > 0) return;
      const g = G();
      if (g <= 16) return;
      if (c.esp.add(8).readS32() !== 1 || c.esp.add(0xC).readS32() !== 4) return;
      c.esp.add(8).writeS32(g);
      c.esp.add(0xC).writeS32(64);
      nB++;
    }
  });
  Interceptor.attach(VA(0x4B4E28), {
    onEnter() {
      const g = G();
      if (g <= 16) return;
      const c = this.context;
      if (c.edx.toInt32() !== 0x4B) return;
      c.edx = ptr(Math.floor(0x4B * g / 16));
      nE++;
    }
  });
  Interceptor.attach(VA(0x4B4EA8), {
    onEnter() {
      const g = G();
      if (g <= 16) return;
      const c = this.context;
      if (c.eax.toInt32() !== 0x38) return;
      c.eax = ptr(Math.floor(64 * g / 16) - 8);
      nG++;
    }
  });
  Interceptor.attach(VA(0x4B815B), {
    onEnter() {
      const g = G();
      if (g <= 16) return;
      const c = this.context;
      if (c.eax.toInt32() !== 0x32) return;
      c.eax = ptr(Math.floor(61 * g / 16) - 11);
      nH++;
    }
  });

  // ================= lever N: content-anchor joins =================
  let nN = 0;
  function join(va, fn) {
    Interceptor.attach(VA(va), {
      onEnter() {
        const g = G();
        if (g <= 16) return;
        fn(this.context, g);
        nN++;
      }
    });
  }
  function esi3(c, g) { if (c.esi.toInt32() === 3) c.esi = ptr(Math.floor(3 * g / 16)); }
  const radd = function (reg, n) { return function (c, g) { c[reg] = ptr(c[reg].toInt32() + D(n, g)); }; };
  const rsub = function (reg, n) { return function (c, g) { c[reg] = ptr(c[reg].toInt32() - D(n, g)); }; };
  join(0x4b4d84, esi3);
  join(0x4b6a1f, esi3);
  join(0x4b6b82, radd('esi', 2));
  join(0x4b6b88, radd('edx', 1));
  join(0x4b6bcb, radd('ebx', 3));
  join(0x4b6bf2, rsub('ebx', 4));
  join(0x4b7f05, radd('ebx', 2));
  join(0x4b8001, rsub('ebx', 2));
  join(0x45bf86, function (c, g) {
    c.eax = ptr(c.eax.toInt32() + D(3, g));
    c.ecx = ptr(c.ecx.toInt32() + D(3, g));
  });
  join(0x4593a1, function (c, g) {
    c.ecx = ptr(c.ecx.toInt32() + D(7, g));
    c.edi = ptr(c.edi.toInt32() + D(7, g));
    c.eax = ptr(c.eax.toInt32() - D(32, g) - D(7, g));
    c.ebx = ptr(c.ebx.toInt32() - D(7, g));
  });
  join(0x4593ca, radd('edx', 3));
  join(0x456395, function (c, g) {
    c.ebx = ptr(c.ebx.toInt32() + D(5, g));
    c.ecx = ptr(c.ecx.toInt32() + D(5, g));
  });
  join(0x4b80d9, esi3);
  join(0x4b8230, radd('edi', 5));
  join(0x4b8295, rsub('eax', 5));
  join(0x4b86e6, function (c, g) {
    if (c.edx.toInt32() !== 27) return;
    c.edx = ptr(c.eax.toInt32() + Math.floor(19 * g / 16) + 1);
  });

  // ================= lever J: 9-slice frame thickening =================
  const THUNK_HOLLOW_FLAT = VA(0xA0C140);
  const callHollowFlat = new NativeFunction(THUNK_HOLLOW_FLAT, 'void',
                                            ['pointer', 'pointer', 'pointer'], 'thiscall');
  const NAT = {
    0x4b6a0e: [140, 60, 241, 189],
    0x4b6a46: [143, 63, 238, 186],
    0x4b4d73: [8, 60, 136, 248],
    0x4b4dab: [11, 63, 133, 245],
    0x4b80ce: [139, 192, 764, 248],
    0x4b8106: [142, 195, 761, 245],
    0x45bf3e: [782, 211, 1017, 249],
    0x45bf66: [785, 214, 901, 246],
    0x45bd88: [266, 70, 759, 168],
    0x45be28: [266, 70, 759, 168],
    0x45bd99: [269, 73, 495, 165],
    0x45bdaa: [498, 73, 724, 165],
    0x45910d: [269, 73, 495, 165],
    0x4564a7: [269, 73, 495, 165]
  };
  const lRect = Memory.alloc(16);
  const FC_EXACT = VA(0xA0E554);
  const FC_RECT = VA(0xA0D010);
  let callOrigBS = null;
  const origBS = Interceptor.replaceFast(VA(0x5E2DD3), new NativeCallback(
    function (self, rect, params) {
      const dest = staticOf(self);
      if (!HUD_BUFS.has(dest)) {
        callOrigBS(self, rect, params);
        return;
      }
      const site = staticOf(this.returnAddress);
      const g = G();
      if (g > 16) {
        nJ++;
        let rc = rect;
        const nat = NAT[site];
        if (nat) {
          lRect.writeS32(Math.floor(nat[0] * g / 16));
          lRect.add(4).writeS32(Math.floor(nat[1] * g / 16));
          lRect.add(8).writeS32(Math.floor(nat[2] * g / 16));
          lRect.add(0xC).writeS32(Math.floor(nat[3] * g / 16));
          rc = lRect;
        }
        FC_RECT.writeS32(rc.readS32());
        FC_RECT.add(4).writeS32(rc.add(4).readS32());
        FC_RECT.add(8).writeS32(rc.add(8).readS32());
        FC_RECT.add(0xC).writeS32(rc.add(0xC).readS32());
        FC_EXACT.writeS32(1);
        callHollowFlat(self, rc, params);
        FC_EXACT.writeS32(0);
        return;
      }
      callOrigBS(self, rect, params);
    }, 'void', ['pointer', 'pointer', 'pointer'], 'thiscall'));
  callOrigBS = new NativeFunction(origBS, 'void',
                                  ['pointer', 'pointer', 'pointer'], 'thiscall');

  // ============ lever W: baked shrink/2dscale bracket arming ============
  const POPUP_ACTIVE = VA(0xA0C530);   // g_popup_active (pcave2+0x530)
  const BRACKET_BTNS = new Set([0x7AF620, 0x7B016C, 0x7B0CB8, 0x7B1804,
                                0x7B2350, 0x7B39E8, 0x7B4534]);
  let bracketOn = false, nW = 0, armedBtnS = 0;

  // ===== lever V: void the fillcap capture for sprite-content buttons =====
  const SPRITE_BTNS = new Set([0x7B1804, 0x7B2350, 0x7B39E8, 0x7B4534]);
  const FILL_SPRITE = VA(0xA0D600);    // g_btn_fill_sprite (pcave2+0x1600)
  let nV = 0;
  Interceptor.attach(VA(0x5DA9F0), {
    onEnter() {
      if (!bracketOn) return;
      if (!SPRITE_BTNS.has(armedBtnS)) return;
      if (FILL_SPRITE.readS32() === 0) return;
      FILL_SPRITE.writeS32(0);
      nV++;
    }
  });

  // ============ lever K (+Q): box_2 outline thickening ============
  const callBox2 = new NativeFunction(VA(0x5E3203), 'void',
                                      ['pointer', 'pointer', 'int', 'int'], 'thiscall');
  const kRect = Memory.alloc(16);
  let inK = false;
  Interceptor.attach(VA(0x5E3203), {
    onEnter() {
      const c = this.context;
      this.doK = false;
      if (inK) return;
      const dest = staticOf(c.ecx);
      let hud = HUD_BUFS.has(dest);
      if (!hud && !bracketOn) {   // Q: skip while bracket composes native
        const r = staticOf(c.esp.readPointer());
        if (r >= 0x608200 && r < 0x608300) {
          try { hud = staticOf(c.esi.add(0xC4).readPointer()) === 0x7AE820; } catch (e) {}
        }
      }
      if (!hud) return;
      const g = G();
      if (g <= 16) return;
      this.doK = true;
      this.self = c.ecx;
      const rc = c.esp.add(4).readPointer();
      this.L = rc.readS32(); this.T = rc.add(4).readS32();
      this.R = rc.add(8).readS32(); this.B = rc.add(0xC).readS32();
      this.cH = c.esp.add(8).readS32(); this.cV = c.esp.add(0xC).readS32();
      this.n = Math.ceil(g / 16);
    },
    onLeave() {
      if (!this.doK) return;
      inK = true;
      for (let i = 1; i < this.n; i++) {
        kRect.writeS32(this.L + i); kRect.add(4).writeS32(this.T + i);
        kRect.add(8).writeS32(this.R - i); kRect.add(0xC).writeS32(this.B - i);
        callBox2(this.self, kRect, this.cH, this.cV);
      }
      inK = false;
      nK++;
    }
  });

  let nR = 0, nS = 0;

  // ==== T2: lever R (M/I label font) + lever W arming + T30 state watch ====
  const T30_BTNS = { 0x7B1804: "MENU", 0x7B2350: "COMMLINK",
                     0x7B39E8: "WORLD", 0x7B4534: "DETAIL" };
  const t30state = {};
  Interceptor.attach(VA(0x607E50), {
    onEnter() {
      const c = this.context;
      const btn = staticOf(c.ecx);
      const g = G();
      this.armed = false;
      if ((btn === 0x7AF620 || btn === 0x7B016C) && g > 16) {
        callSetFont(c.ecx.add(0x444), VA(0x7CFEB4), ptr(0), ptr(0), 0);
        nR++;
      }
      if (BRACKET_BTNS.has(btn) && g > 16 && POPUP_ACTIVE.readS32() === 0) {
        POPUP_ACTIVE.writeS32(1);
        this.armed = true;
        this.btnPtr = c.ecx;
        bracketOn = true;
        armedBtnS = btn;         // lever V keys the devfill suppression on this
        nW++;
      }
      // T30: log the button state-machine field on CHANGE (cheap). If the
      // deferred click is a stuck state, the WORLD/DETAIL entry will show
      // e.g. 0->2 on down with no 2->0 until the mouse leaves.
      const nm = T30_BTNS[btn];
      if (nm !== undefined) {
        try {
          const st = c.ecx.add(0xAB8).readS32();
          if (t30state[btn] !== st) {
            log("[T30] " + nm + " state " +
                (t30state[btn] === undefined ? "?" : t30state[btn]) + "->" + st);
            t30state[btn] = st;
          }
        } catch (e) {}
      }
    },
    onLeave() {
      if (this.armed) {
        if (POPUP_ACTIVE.readS32() !== 0) {
          POPUP_ACTIVE.writeS32(0);
          emit("T15L|" + staticOf(this.btnPtr).toString(16),
               "[T15] LATE disarm btn=" + hx(staticOf(this.btnPtr)));
        }
        bracketOn = false;
        armedBtnS = 0;
      }
    }
  });
  const callSetFont = new NativeFunction(VA(0x5DAC70), 'void',
                                         ['pointer', 'pointer', 'pointer', 'pointer', 'int'], 'thiscall');

  // v33 EARLY DISARM host: GraphicWin_fill 0x5D5250 — plain-E8-called as
  // content_draw's first op, after the shrink gate consumed the flag.
  let nW15 = 0;
  Interceptor.attach(VA(0x5D5250), {
    onEnter() {
      if (bracketOn && staticOf(this.returnAddress) === 0x607EC8 &&
          POPUP_ACTIVE.readS32() === 1) {
        POPUP_ACTIVE.writeS32(0);
        nW15++;
      }
    }
  });

  // ============ lever X v2: box-10 planet button init positions ============
  const CAVE_ARM = VA(0xA0D000);
  let nT9 = 0, savedArm = 0;
  Interceptor.attach(VA(0x45AD14), {     // rect-load before btn 0x3EE pushes
    onEnter() {
      savedArm = CAVE_ARM.readS32();
      CAVE_ARM.writeS32(0);
      nT9++;
    }
  });
  Interceptor.attach(VA(0x45ADC4), {     // after btn 0x3EF init call
    onEnter() {
      CAVE_ARM.writeS32(savedArm);
    }
  });

  // ============ lever Z: band text rect (Spot slot 5) ============
  Interceptor.attach(VA(0x5FAC00), {
    onEnter() {
      this.doZ = false;
      if (!this.context.ecx.equals(VA(0x7D3854))) return;   // MainWin+0x25034
      if (this.context.esp.add(4).readS32() !== 5) return;
      this.doZ = true;
      this.rc = this.context.esp.add(0xC).readPointer();
    },
    onLeave() {
      if (!this.doZ) return;
      const g = G();
      const rc = this.rc;
      const L = rc.readS32(), T = rc.add(4).readS32();
      const R = rc.add(8).readS32(), B = rc.add(0xC).readS32();
      if (g <= 16) return;
      if (R - L !== 233 || B - T !== 23) return;      // already fully scaled
      const W = Math.floor(233 * g / 16), H = Math.floor(23 * g / 16);
      if (L > 1024) {                                  // mixed: pos scaled, dims native
        rc.add(8).writeS32(L + W); rc.add(0xC).writeS32(T + H);
      } else {                                         // fully native
        rc.writeS32(Math.floor(L * g / 16)); rc.add(4).writeS32(Math.floor(T * g / 16));
        rc.add(8).writeS32(Math.floor(L * g / 16) + W); rc.add(0xC).writeS32(Math.floor(T * g / 16) + H);
      }
    }
  });

  // ============== lever S v4: turn.flc band — full-path dst-bounce ==============
  // (design + static-decode notes in the file header; v41 fixes 1-3 applied)
  let nSskip = 0;
  try {
    const callCopy3 = new NativeFunction(VA(0x5D9610), 'void',
      ['pointer', 'pointer', 'int', 'int', 'int', 'int', 'int', 'int', 'int', 'int'], 'thiscall');
    const callMalloc = new NativeFunction(VA(0x64558A), 'pointer', ['uint'], 'mscdecl');
    const callBufCtor = new NativeFunction(VA(0x5D7210), 'void', ['pointer'], 'thiscall');
    const callBufResize = new NativeFunction(VA(0x5D79C0), 'void', ['pointer', 'int', 'int'], 'thiscall');
    const TURN_FLIC = VA(0x7D2D70);
    const TURN_CANVAS = VA(0x7D2D74);
    const TURN_CANVAS_ST = 0x7D2D74;
    let sScratch = NULL;
    let bounceActive = false, bouncePaint = [];   // tags of paint paths that ran
    function ensureBandScratch(w, h) {   // thunk_ensure_scratch recipe, JS-side
      if (sScratch.isNull()) {
        const p = callMalloc(0x588);
        if (p.isNull()) return NULL;
        callBufCtor(p);
        callBufResize(p, w, h);
        // FIX 3: seed with the canvas bg patch — the scratch is the band's
        // persistent native framebuffer from here on (deltas accumulate)
        callCopy3(TURN_CANVAS, p, 0, 0, w, h, 0, 0, w, h);
        sScratch = p;
      }
      callBufResize(sScratch, w, h);     // early-outs when already w x h
      return sScratch;
    }

    // v4a: canvas bg recapture at Flic_init + paint detector (a)
    Interceptor.attach(VA(0x5DFF00), {   // Buffer_copy_4(this=src; dst, sx,sy, dx,dy, w,h)
      onEnter() {
        this.doCap = false;
        const ret = staticOf(this.returnAddress);
        if (ret === 0x62ADF2) {                                // gated bg-restore blit RAN
          if (bounceActive) bouncePaint.push("blit");
          return;
        }
        if (ret !== 0x62A04B) return;                          // Flic_init bg capture
        const sp = this.context.esp;
        const dst = sp.add(4).readPointer();
        if (staticOf(dst) !== TURN_CANVAS_ST) return;          // menu flics untouched
        const g = G();
        if (g <= 16) return;
        this.doCap = true; this.g = g;
        this.src = this.context.ecx; this.dst = dst;
        this.sx = sp.add(8).readS32(); this.sy = sp.add(0xC).readS32();
        this.w = sp.add(0x18).readS32(); this.h = sp.add(0x1C).readS32();
      },
      onLeave() {
        if (!this.doCap) return;
        const W = Math.floor(this.w * this.g / 16), H = Math.floor(this.h * this.g / 16);
        // redo the engine's 1:1 grab as a shrink of the FULL scaled band area
        callCopy3(this.src, this.dst, this.sx, this.sy, W, H, 0, 0, this.w, this.h);
        log("[TB] canvas recapture: strip(" + this.sx + "," + this.sy + " " + W + "x" + H +
            ") ->shrink-> canvas " + this.w + "x" + this.h + " g=" + this.g);
      }
    });

    // paint detectors (b,d,e,f): the direct-to-dst pixel chunk handlers —
    // all plain-E8 thiscall(ecx=flic); tags feed the [TB] census
    function flicPaintDetector(tag) {
      return {
        onEnter() {
          if (this.context.ecx.equals(TURN_FLIC)) bouncePaint.push(tag);
        }
      };
    }
    Interceptor.attach(VA(0x62B670), flicPaintDetector("kcopy"));   // keyed type 16 COPY
    Interceptor.attach(VA(0x62AF40), flicPaintDetector("kbrun"));   // keyed type 15 BYTE_RUN — frame 0's painter
    Interceptor.attach(VA(0x62B190), flicPaintDetector("kss2"));    // keyed type 7 SS2 delta
    Interceptor.attach(VA(0x62A500), flicPaintDetector("brun"));    // direct-mode type 15
    Interceptor.attach(VA(0x62A720), flicPaintDetector("ss2"));     // direct-mode type 7
    Interceptor.attach(VA(0x62AB80), flicPaintDetector("copy16"));  // direct-mode type 16
    // paint detector (c): Buffer_fill, E8-called by the black-frame handler @0x62AE91
    Interceptor.attach(VA(0x5D8240), {
      onEnter() {
        if (bounceActive && this.context.ecx.equals(sScratch)) bouncePaint.push("black");
      }
    });

    // [TB2] decode census: every chunk header the turn flic dispatches
    let nTB2 = 0;
    Interceptor.attach(VA(0x62ACD0), {   // Flic_decode_chunk(this=flic; hdr*)
      onEnter() {
        if (!this.context.ecx.equals(TURN_FLIC)) return;
        if (nTB2 >= 24) return;
        nTB2++;
        const hdr = this.context.esp.add(4).readPointer();
        let t = -1, n = -1, sz = -1;
        try { sz = hdr.readS32(); t = hdr.add(4).readU16(); n = hdr.add(6).readU16(); } catch (e) {}
        log("[TB2] chunk type=" + hx(t) + " size=" + sz + " cnt=" + n +
            (bounceActive ? " (bounced)" : ""));
      }
    });
    // [TB3] the turn flic's own file reads during a bounced draw
    let nTB3 = 0;
    Interceptor.attach(VA(0x646178), {   // CRT fread(dest, size, count, FILE*)
      onEnter() {
        this.doT3 = false;
        if (!bounceActive || nTB3 >= 30) return;
        const sp = this.context.esp;
        const file = sp.add(0x10).readPointer();
        if (!file.equals(TURN_FLIC.add(0x5B8).readPointer())) return;
        this.doT3 = true;
        this.sz = sp.add(8).readS32() * sp.add(0xC).readS32();
      },
      onLeave(retval) {
        if (!this.doT3) return;
        nTB3++;
        log("[TB3] fread " + this.sz + "B -> ret=" + retval.toInt32());
      }
    });

    // v4b: dst-bounce on both draw entries
    const bandDraw = {
      onEnter() {
        this.doS = false;
        const c = this.context;
        if (!c.ecx.equals(TURN_FLIC)) return;
        const g = G();
        if (g <= 16) return;
        const fl = c.ecx;
        const w = fl.add(0x59C).readS32(), h = fl.add(0x5A0).readS32();
        if (w <= 0 || h <= 0 || w > 1024 || h > 256) return;   // sanity: header dims
        const scr = ensureBandScratch(w, h);
        if (scr === NULL || scr.isNull()) return;
        const sp = c.esp;
        this.rx = sp.add(4).readS32(); this.ry = sp.add(8).readS32();
        this.dstp = fl.add(0x5A8);
        this.oldDst = this.dstp.readPointer();
        this.dstp.writePointer(scr);
        sp.add(4).writeS32(0); sp.add(8).writeS32(0);          // compose at scratch 0,0
        this.doS = true; this.g = g; this.w = w; this.h = h;
        this.fl = fl; this.scr = scr;
        this.gate = fl.readU8();
        bounceActive = true; bouncePaint = [];
      },
      onLeave(retval) {
        if (!this.doS) return;
        bounceActive = false;
        this.dstp.writePointer(this.oldDst);                   // restore dst
        const fl = this.fl;
        fl.add(0x5AC).writeS32(this.rx);                       // restore stored pos —
        fl.add(0x5B0).writeS32(this.ry);                       // the static branch re-reads it
        // mirror the engine's draw decision — stretch only if a pixel
        // path actually wrote the (bounced) dst during this call
        if (retval.toInt32() !== 0 || bouncePaint.length === 0) {
          if (++nSskip <= 6)
            log("[TB] band draw SKIP (no paint) ret=" + hx(staticOf(this.returnAddress)) +
                " gate=" + this.gate + " rv=" + retval.toInt32() +
                " file=" + fl.add(0x5B8).readPointer() +
                " idx=" + fl.add(0xA10).readS32() + "/" + fl.add(0xA1A).readU16() +
                " o64=" + fl.add(0xA64).readS32() + " o68=" + fl.add(0xA68).readS32());
          return;
        }
        const W = Math.floor(this.w * this.g / 16), H = Math.floor(this.h * this.g / 16);
        callCopy3(this.scr, this.oldDst, 0, 0, this.w, this.h, this.rx, this.ry, W, H);
        fl.add(0x58C).writeS32(this.rx);      fl.add(0x590).writeS32(this.ry);
        fl.add(0x594).writeS32(this.rx + W);  fl.add(0x598).writeS32(this.ry + H);
        nS++;
        if (nS <= 12)
          log("[TB] band draw ret=" + hx(staticOf(this.returnAddress)) + " @" + this.rx + "," +
              this.ry + " " + this.w + "x" + this.h + " -> " + W + "x" + H +
              " gate=" + this.gate + " paint=[" + bouncePaint.join(",") + "] g=" + this.g);
      }
    };
    Interceptor.attach(VA(0x62A070), bandDraw);   // Flic_draw_frame
    Interceptor.attach(VA(0x62A120), bandDraw);   // Flic_draw_frame_once (parallel body)
  } catch (e) {
    log("[TB] S v4 INSTALL FAIL: " + e);          // FIX 1 lesson: never die silently
  }

  // ============ T28: mouse-window resolver (change-triggered, cheap) ============
  const WIN_NAME = {
    0x7AF620: "M", 0x7B016C: "I", 0x7B0CB8: "TOOLBAR", 0x7B1804: "MENU",
    0x7B2350: "COMMLINK", 0x7B39E8: "WORLD", 0x7B4534: "DETAIL",
    0x7AE820: "MAINWIN"
  };
  let lastMouseWin = -1, t28logged = 0;
  Interceptor.attach(VA(0x5F6F10), {    // Win_get_mouse_window(int* x, int* y)
    onEnter() {
      this.px = this.context.esp.add(4).readPointer();
      this.py = this.context.esp.add(8).readPointer();
    },
    onLeave(retval) {
      const w = staticOf(retval);
      if (w === lastMouseWin) return;
      lastMouseWin = w;
      let pos = "?";
      try { pos = this.px.readS32() + "," + this.py.readS32(); } catch (e) {}
      const nm = WIN_NAME[w];
      if (++t28logged <= 200)
        log("[T28] mousewin=" + (nm !== undefined ? nm : hx(w)) + " @" + pos);
    }
  });

  setInterval(function () {
    log("[hb] A=" + nA + " B=" + nB + " C'=" + nC + " E=" + nE + " F=" + nF +
        " G=" + nG + " H=" + nH + " J=" + nJ + " K=" + nK + " N=" + nN +
        " R=" + nR + " S=" + nS + " W=" + nW + " Wd=" + nW15 +
        " X=" + nT9 + " V=" + nV);
  }, 5000);
  log("v44 armed (v43 + keyed-mode paint detectors kbrun/kss2), g=" + G());
}
