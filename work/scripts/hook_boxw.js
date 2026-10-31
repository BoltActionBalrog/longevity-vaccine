"use strict";
// OBSERVER ONLY (2026-07-08) — box-width law audit.
//
// Question: is the popup box width `vanilla x g/16`, or is the tuned constant
// g_boxw_num (=30, x1.875) mis-scaling popups whose pre-value is contaminated
// differently than the Planetfall popup it was tuned on?
//
// Logs, per BasePop_calculate_dimensions call:
//   - the INPUTS the box-width formula consumes (art dims + art scale num/den,
//     padX/padY and their native sources [+0x21c0]/[+0x21c4], the element text
//     widths [+0x21fc]/[+0x222c], init_w [+0x21cc], margins),
//   - box_w_pre  (what the engine computed, just before thunk_scale_boxw), and
//   - box_w_final (after the thunk + margin add).
//
// DUAL-MODE. The script detects at load whether it is running on the patched exe
// or the PRISTINE base (terranx_pristine.exe == terranx_PRACX.exe.bak == 2d0b1438):
//   * patched  -> .pcave2 is mapped, g_popup_scale_num holds 16..40. Captures
//                 box_w_pre at the cave thunk's entry and PASS/FAILs each popup
//                 against the recorded vanilla width x g/16.
//   * pristine -> neither the cave nor the lever exists (reading them can throw or
//                 return section padding). Nothing cave-related is touched; the run
//                 simply RECORDS the vanilla geometry.
// Never infer "vanilla" from the patched exe at g=16 — a leaky g<=16 gate would
// silently feed a patched value into the baseline (thunk_scale_boxw v1 did exactly
// that: its gate keyed on ScreenWidth>0x3FF, and 1024 == 0x400 slips it).
// See memory feedback-pristine-baseline-trace.
//
// Run:  work\run-frida.bat hook_boxw.js                    (patched, at desktop res)
//       work\run-frida-pristine.bat hook_boxw.js 1024 768  (TRUE vanilla baseline)
// Then open the popups of interest. Nothing is written to game memory.

globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_boxw.log";
log("=== hook_boxw.js (observer, box-width law audit) started ===");

if (requireBase()) {
  const BASEPOP_CALC = 0x00603800;   // __fastcall(ecx = popup)
  const POPUP_CALC   = 0x00404B10;   // wrapper; clamps width to ScreenWidth-0x16E
  const THUNK_BOXW   = 0x00A0C300;   // pcave2+0x300 (patched exe only); esi = popup
  const G_SCALE      = 0x00668740;   // g_popup_scale_num
  const G_BOXW_NUM   = 0x00668C30;   // menu_strip_thunks(0x668200)+0xA30 (patched exe only)
  const POPUP_SHOW   = 0x00404920;   // Popup_show -> Win_move @0x4049C1 positions the box
  const WIN_MOVE     = 0x005ED7D0;   // Win_move(this; x, y) -- rect at +0x14c/150/154/158
  const SCREEN_W     = 0x009B7B1C;   // ScreenWidth

  // ---- mode detection: is this the patched exe or the pristine base? ----------
  // The lever lives in the cave; on pristine that address is section padding (or
  // unmapped). Treat "not a sane 16..40" as pristine and never touch cave memory.
  const PATCHED = (function () {
    try {
      const v = VA(G_SCALE).readS32();
      return v >= 16 && v <= 40;
    } catch (e) { return false; }
  })();
  // On pristine there is no scale lever; the engine is natively 16/16.
  const gNow = () => (PATCHED ? VA(G_SCALE).readS32() : 16);
  try {
    const m = Process.mainModule;
    log(`MODULE: ${m.name}  base=${m.base}  size=${m.size} (0x${m.size.toString(16)})` +
        `   [patched terranx_PRACX.exe ~3112960 / pristine terranx_pristine.exe 3084288]`);
  } catch (e) {}
  log(PATCHED
    ? "MODE: PATCHED exe (cave present, g_popup_scale_num live)  <-- THIS is the build to verify"
    : "MODE: PRISTINE base (no cave, no lever) — recording the TRUE vanilla baseline");

  const F = {
    list_flag:  0x0A14,   // [0x285]  != 0 -> list popup
    override_w: 0x0A20,   // [0x288]
    flags:      0x30A8,   // [0xc2a]
    art_obj:    0x2144,   // [0x851]
    art_flag:   0x2190,   // [0x864]  (adds padY into content_W)
    init_w:     0x21CC,   // [0x873]  -1 => auto-size
    dlg:        0x21D0,   // [0x874]  -> iVar3 = [[dlg]+8]
    padx_src:   0x21C0,   // [0x870]  native pad source
    pady_src:   0x21C4,   // [0x871]
    marg_l_src: 0x21B0,
    marg_r_src: 0x21B4,
    padx:       0x30E0,   // [0xc38]  = padx_src * 3/2 when ScreenWidth > 1023
    pady:       0x30E4,   // [0xc39]
    content_w:  0x30D8,   // [0xc36]  = art_w*num/den + padx + (art_flag ? pady : 0)
    content_h:  0x30DC,
    box_w:      0x30BC,   // [0xc2f]
    box_h:      0x30C0,
    marg_l:     0x30F0,   // [0xc3c]  added to box_w at the end
    marg_r:     0x30F4,   // [0xc3d]
    art_num:    0x3104,   // [0xc41]
    art_den:    0x3108,   // [0xc42]
  };

  const i32 = (p, off) => p.add(off).readS32();

  function label(p) {
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

  // element text widths: popup + iVar3 + 0x21fc / +0x222c, iVar3 = [[popup+0x21d0]+8]
  function textWidths(p) {
    try {
      const dlg = p.add(F.dlg).readPointer();
      if (dlg.isNull()) return { iv3: -1, w21fc: -1, w222c: -1 };
      const iv3 = dlg.add(8).readS32();
      return {
        iv3,
        w21fc: p.add(iv3 + 0x21fc).readS32(),
        w222c: p.add(iv3 + 0x222c).readS32(),
      };
    } catch (e) {
      return { iv3: -2, w21fc: -2, w222c: -2 };
    }
  }

  function artDims(p) {
    try {
      const a = p.add(F.art_obj).readPointer();
      if (a.isNull()) return { w: 0, h: 0 };
      return { w: a.add(0x18).readS32(), h: a.add(0x1c).readS32() };
    } catch (e) {
      return { w: -1, h: -1 };
    }
  }

  function snap(p, tag) {
    const t = textWidths(p);
    const a = artDims(p);
    const parts = [
      `${tag} popup=${p} "${label(p)}"`,
      `  g=${gNow()}${PATCHED ? "" : " (pristine: native)"}  ScreenWidth=${VA(SCREEN_W).readS32()}`,
      `  list=${i32(p, F.list_flag)} flags=0x${(i32(p, F.flags) >>> 0).toString(16)}` +
        ` init_w=${i32(p, F.init_w)} override_w=${i32(p, F.override_w)}`,
      `  art canvas=${a.w}x${a.h} num/den=${i32(p, F.art_num)}/${i32(p, F.art_den)} art_flag=${i32(p, F.art_flag)}`,
      `  padx_src=${i32(p, F.padx_src)} pady_src=${i32(p, F.pady_src)} -> padx=${i32(p, F.padx)} pady=${i32(p, F.pady)}`,
      `  content_w=${i32(p, F.content_w)} content_h=${i32(p, F.content_h)}`,
      `  text iv3=${t.iv3} w[21fc]=${t.w21fc} w[222c]=${t.w222c}`,
      `  marg src L/R=${i32(p, F.marg_l_src)}/${i32(p, F.marg_r_src)} live L/R=${i32(p, F.marg_l)}/${i32(p, F.marg_r)}`,
      `  box_w=${i32(p, F.box_w)} box_h=${i32(p, F.box_h)}`,
      `  content_top[30e8]=${i32(p, 0x30e8)} bot_marg[30ec]=${i32(p, 0x30ec)}` +
        ` hdr_src[21b8]=${i32(p, 0x21b8)} botmarg_src[21bc]=${i32(p, 0x21bc)}` +
        ` [21c8]=${i32(p, 0x21c8)}`,
      `  win rect L=${i32(p, 0x14c)} T=${i32(p, 0x150)} R=${i32(p, 0x154)} B=${i32(p, 0x158)}` +
        `  clientWH=${i32(p, 0x4c4)}x${i32(p, 0x4c8)}`,
    ];
    log(parts.join("\n"));
  }

  // dedup on the label text (popups reuse the same heap ptr across opens)
  const seen = {};
  let pending = null;

  Interceptor.attach(VA(BASEPOP_CALC), {
    onEnter(args) {
      const p = ptr(this.context.ecx);
      this.p = p;
      const key = label(p) + "|" + i32(p, F.list_flag);
      this.key = key;
      this.fresh = !seen[key];
      if (this.fresh) {
        seen[key] = 1;
        log("\n---------------------------------------------------------------");
        snap(p, "[ENTER]");
      }
      pending = this.fresh ? p : null;
    },
    onLeave() {
      if (this.fresh) {
        snap(this.p, "[LEAVE]");
        try {
          const g = gNow();
          const bw = i32(this.p, F.box_w);
          const bh = i32(this.p, F.box_h);
          const isFactionQuote = this.p.equals(ptr(0x9403e0));
          if (isFactionQuote) log("  >> this is g_faction_quote_popup (0x9403e0)");
          if (!PATCHED) {
            log(`  >> VANILLA BASELINE  box_w=${bw} box_h=${bh}  content_w=${i32(this.p, F.content_w)} content_top=${i32(this.p, 0x30e8)}  (faithful box_w @g = ${bw}*g/16)`);
          } else {
            // Faithful anchors captured from the PRISTINE base (terranx_pristine.exe,
            // 2d0b1438) 2026-07-08. box_w @ 1024 -> its g/16 is the faithful target.
            // Keyed by popup ADDR (the faction-quote title field is non-text garbage).
            const BASE = {
              "0x9403e0": { box_w: 722, box_h: 193, content_w_4k: 331, content_top: 18 },  // faction quote
            };
            const b = BASE[this.p.toString()];
            if (b) {
              const faithful = (b.box_w * g) / 16;
              const err = 100 * (bw / faithful - 1);
              const verdict = Math.abs(err) < 1.5 ? "PASS" : "FAIL";
              log(`  >> ${verdict} box_w  vanilla=${b.box_w} x ${g}/16 = ${faithful.toFixed(1)} ; actual=${bw} ; err ${err.toFixed(2)}%`);
              log(`  >> box_h actual=${bh} (pristine 4K=473) ; content_w actual=${i32(this.p, F.content_w)} (pristine 4K=${b.content_w_4k}) ; content_top actual=${i32(this.p, 0x30e8)} (pristine=${b.content_top})`);
            } else {
              log(`  >> final box_w=${bw} box_h=${bh} (no PRISTINE baseline recorded for this popup yet)`);
            }
          }
        } catch (e) {}
      }
      pending = null;
    },
  });

  // Patched exe only: catch box_w BEFORE thunk_scale_boxw rewrites it.
  // On pristine neither the cave nor g_boxw_num exists — do not read or attach.
  if (PATCHED) {
    try {
      const g_num = VA(G_BOXW_NUM).readS32();
      log(`g_boxw_num = ${g_num} (40 => M(g) == g, a true g/16 for thunk_q16_fill_width)`);
      Interceptor.attach(VA(THUNK_BOXW), {
        onEnter() {
          const p = ptr(this.context.esi);
          if (pending === null || !p.equals(pending)) return;
          log(`  [PRE-THUNK] box_w_pre=${i32(p, F.box_w)}`);
        },
      });
    } catch (e) {
      log("WARNING: patched mode but thunk_scale_boxw not attachable: " + e);
    }
  } else {
    log("pristine: skipping the cave thunk hook and g_boxw_num read entirely.");
  }

  // ---- centering: capture the popup box's actual window rect ----------------
  // frame_center should land at ScreenWidth/2 regardless of box_w. If it doesn't,
  // the box origin (not the width) is the defect. Only log GraphicWin_init calls
  // made from inside Popup_show, so the popup's own box window is the one we see.
  let inShow = 0;
  Interceptor.attach(VA(POPUP_SHOW), {
    onEnter() {
      inShow++;
      try {
        const p = ptr(this.context.ecx);
        const sw = VA(SCREEN_W).readS32();
        const bw = i32(p, F.box_w);
        log(`\n[SHOW] "${label(p)}" box_w=${bw} ScreenWidth=${sw}` +
            `  centered origin would be x=${((sw - bw) / 2).toFixed(1)}`);
      } catch (e) {}
    },
    onLeave() { inShow--; },
  });

  Interceptor.attach(VA(WIN_MOVE), {
    onEnter() {
      if (inShow <= 0) return;
      const self = ptr(this.context.ecx);
      const sp = this.context.esp;
      this.x = sp.add(4).readS32();
      this.y = sp.add(8).readS32();
      this.self = self;
    },
    onLeave() {
      if (inShow <= 0 || !this.self) return;
      const sw = VA(SCREEN_W).readS32();
      const L = this.self.add(0x14c).readS32(), T = this.self.add(0x150).readS32();
      const R = this.self.add(0x154).readS32(), B = this.self.add(0x158).readS32();
      const c = (L + R) / 2;
      log(`  [WIN_MOVE] arg x=${this.x} y=${this.y} -> rect L=${L} T=${T} R=${R} B=${B}` +
          ` (w=${R - L})  center=${c.toFixed(1)} vs ScreenWidth/2=${sw / 2}` +
          `  => ${(c - sw / 2).toFixed(1)} px off-centre`);
    },
  });

  log("hooks installed. Open the in-game Quit dialog, then the Planetary Council dialog.");
}
