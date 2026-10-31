"use strict";
// OBSERVER ONLY (2026-07-08) -- faction-quote frame-stroke + portrait diagnostic.
//
// Diagnoses the four user-reported defects on the faction-selection QUOTE box (4K):
//   (1) the margin between the TWO frame strokes around the quote box is too large,
//   (2) the quote box sits too HIGH,
//   (3) the faction-leader PORTRAIT is flush with the INNER stroke of the quote frame
//       instead of the OUTER stroke (it should be flush with the OUTER),
//   (4) inter-stroke margins generally look wrong.
//
// The quote box is a CONCENTRIC double-frame: an OUTER d5a0 union stroke and an INNER
// d528 stroke, drawn into the faction window buffer 0x940824 (= popup 0x9403e0 + 0x444).
// The leader portrait is a keyed sprite blit into the same buffer.
//
// Capture is by DEST-BUFFER identity (0x940824), so it works on BOTH exes despite the
// different draw paths:
//   * PRISTINE: strokes draw DIRECTLY via Buffer_box_sprite(dest=0x940824, &rect).
//   * PATCHED : the thick-frame mechanism renders each stroke small into g_frame_buf,
//               then Buffer_draw_2(src=g_frame_buf, dest=0x940824, X,Y,num,den) places
//               it scaled. We reconstruct the on-screen rect from X,Y + native w,h x num/den.
//   * Portrait: Sprite_draw_2(dest=0x940824, x,y,num,den). On PATCHED the 0x5E4B4A entry
//               is a baked push-imm32;ret detour into the Sprite_draw_2 entry-chain head
//               (NEVER attach onto the detour cluster -- see feedback-frida-attach-branch-target);
//               we read the detour target and hook the head, whose entry sees the same stack.
//
// All frame/portrait rects are WINDOW-LOCAL (relative to the winbuf); add the window
// origin (win rect L/T) for screen coordinates. Everything below is READ-ONLY.
//
// DUAL-MODE by MODULE NAME (authoritative -- not the g<=16 lever, which reads stale at
// script load): terranx_pristine.exe => PRISTINE, terranx_PRACX.exe => PATCHED.
//
// Run (single shared log, 4K then pristine appended):
//   work\run-frida-at-res.bat  hook_factionquote.js 3840 2160                        (PATCHED, truncates)
//   work\run-frida-pristine.bat hook_factionquote.js 1024  768 frida_log_append.js   (PRISTINE, appends)
// Then open the faction-selection screen so the quote box + leader portrait render.

globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_factionquote.log";
log("=== hook_factionquote.js (observer, faction-quote frame/portrait) started ===");

if (requireBase()) {
  const POPUP_DRAW_BG  = 0x00405C80;   // Popup_on_draw_background(ecx=popup)
  const BASEPOP_REDRAW = 0x00604AB0;   // BasePop_on_redraw(ecx=popup)
  const BUF_BOX_SPRITE = 0x005E2DD3;   // Buffer_box_sprite(ecx=dest; [esp+4]=&rect, [esp+8]=params)
  const BUF_DRAW_2     = 0x005D84C0;   // Buffer_draw_2(ecx=src; dest,key,X,Y,num,den) RET 0x18
  const SPRITE_DRAW_2  = 0x005E4B4A;   // Sprite_draw_2(ecx=self; dest,key,x,y,num,den)
  const FQ_POPUP       = 0x009403E0;   // g_faction_quote_popup (static singleton)
  const FQ_BUF         = 0x00940824;   // faction winbuf = FQ_POPUP + 0x444
  const G_FRAME_BUF    = 0x00668F10;   // Buffer* scratch for the thick-frame render (PATCHED only)
  const G_SCALE        = 0x00668740;   // g_popup_scale_num

  const PATCHED = !/pristine/i.test(Process.mainModule.name);
  const gNow = () => { try { return PATCHED ? VA(G_SCALE).readS32() : 16; } catch (e) { return 16; } };
  log(`MODULE: ${Process.mainModule.name}  size=0x${Process.mainModule.size.toString(16)}` +
      `  MODE: ${PATCHED ? "PATCHED (terranx_PRACX)" : "PRISTINE (terranx_pristine)"}`);

  const i32 = (p, off) => ptr(p).add(off).readS32();
  const rd  = (esp, n) => esp.add(n * 4).readS32();          // 1-based stack arg
  const rnd = (x) => Math.round(x);
  // runtime return-addr / pointer -> static VA (image base 0x400000)
  const sVA = (rt) => { try { return "0x" + (u32(rt.sub(TERRANX_BASE).add(0x400000)) >>> 0).toString(16); } catch (e) { return "?"; } };

  // BoxSpriteParams* globals identify WHICH concentric frame a box draw is.
  const PARAMS = {
    "0x78d690": "d690-backdrop",
    "0x78d5a0": "d5a0-OUTER",    // union / outer quote stroke
    "0x78d618": "d618-title-in",
    "0x78d528": "d528-INNER",    // content / inner quote stroke
  };
  const paramLabel = (pRaw) => { const s = sVA(ptr(pRaw)); return (PARAMS[s] || "params") + "@" + s; };
  const MIN_SPRITE = 40;        // skip the 9-slice frame-tile sprites (6x6 corners / 24x6 edges)
  let tilesSkipped = 0;

  // ---- accumulation (content-deduped: the popup redraws every frame) ----------
  const items = [];         // {tag, kind:'frame'|'portrait', L,T,R,B, note}
  const seen  = new Set();
  let lastSummaryCount = -1;
  let structDone = false;
  let framebuf = 0;         // *g_frame_buf, resolved lazily (PATCHED)
  let pendingNative = null; // native {w,h} from the last box_sprite render into framebuf

  function resolveFramebuf() {
    if (PATCHED && framebuf === 0) { try { framebuf = VA(G_FRAME_BUF).readU32() >>> 0; } catch (e) {} }
    return framebuf;
  }

  function add(tag, kind, L, T, R, B, note) {
    const key = tag + "|" + L + "," + T + "," + R + "," + B;
    if (seen.has(key)) return;
    seen.add(key);
    items.push({ tag, kind, L, T, R, B, note: note || "" });
    log(`  [${tag}] ${kind}  rect L=${L} T=${T} R=${R} B=${B}  (w=${R - L} h=${B - T})  ${note || ""}`);
  }

  function snapStruct(pRaw) {
    if (structDone) return;
    structDone = true;
    const p = ptr(pRaw);
    const wl = i32(p, 0x14c), wt = i32(p, 0x150), wr = i32(p, 0x154), wb = i32(p, 0x158);
    log("\n=========== FACTION QUOTE popup 0x9403e0 geometry ===========");
    log(`  g=${gNow()}   win rect L=${wl} T=${wt} R=${wr} B=${wb}  (w=${wr - wl} h=${wb - wt})`);
    log(`  box_w[30bc]=${i32(p, 0x30bc)}  box_h[30c0]=${i32(p, 0x30c0)}`);
    log(`  content_w[30d8]=${i32(p, 0x30d8)}  content_h[30dc]=${i32(p, 0x30dc)}`);
    log(`  content_top[30e8]=${i32(p, 0x30e8)}  bot_marg[30ec]=${i32(p, 0x30ec)}`);
    const bw = bufWH(FQ_BUF);
    log(`  winbuf 0x940824 dims = ${bw.w} x ${bw.h} (h stored negative; abs=${Math.abs(bw.h)})`);
    log("  NOTE: frame/portrait rects are WINDOW-LOCAL (add win L/T for screen coords).\n");
  }

  function summary(trigger) {
    if (items.length === lastSummaryCount) return;
    lastSummaryCount = items.length;
    // outer -> inner by area (largest first)
    const frames = items.filter(it => it.kind === "frame").slice()
      .sort((a, b) => ((b.R - b.L) * (b.B - b.T)) - ((a.R - a.L) * (a.B - a.T)));
    const ports = items.filter(it => it.kind === "portrait");
    log(`\n----- SUMMARY (${trigger})  frames=${frames.length} portraits=${ports.length} g=${gNow()}  (frame-tiles skipped=${tilesSkipped}) -----`);
    frames.forEach((f, i) => {
      const rank = i === 0 ? "OUTERMOST" : "inner#" + i;
      log(`  frame[${i}] ${rank}  [${f.tag}]  L=${f.L} T=${f.T} R=${f.R} B=${f.B}  w=${f.R - f.L} h=${f.B - f.T}  ${f.note}`);
    });
    for (let i = 1; i < frames.length; i++) {
      const o = frames[i - 1], n = frames[i];
      log(`    channel frame[${i - 1}]->[${i}]:  left=${n.L - o.L}  top=${n.T - o.T}  right=${o.R - n.R}  bottom=${o.B - n.B}  (px between the two strokes)`);
    }
    ports.forEach((p, i) => {
      log(`  portrait[${i}] [${p.tag}]  top T=${p.T}  L=${p.L} R=${p.R} B=${p.B}  w=${p.R - p.L} h=${p.B - p.T}  ${p.note}`);
      frames.forEach((f, fi) =>
        log(`      portrait.top(${p.T}) - frame[${fi}].top(${f.T}) = ${p.T - f.T}   (0 => portrait flush with frame[${fi}] top)`));
    });
    log("----- end summary -----\n");
  }

  // ---- struct snapshot + summary flush brackets ------------------------------
  function bracket(addr, name) {
    Interceptor.attach(VA(addr), {
      onEnter() {
        if ((u32(this.context.ecx) >>> 0) === FQ_POPUP) { this.fq = true; snapStruct(this.context.ecx); }
      },
      onLeave() { if (this.fq) summary(name + " leave"); },
    });
  }
  bracket(POPUP_DRAW_BG, "draw_bg");
  bracket(BASEPOP_REDRAW, "redraw");

  // ---- frames: DIRECT path (pristine) + native-render capture (patched) ------
  Interceptor.attach(VA(BUF_BOX_SPRITE), {
    onEnter() {
      const esp = this.context.esp;
      const dest = u32(this.context.ecx) >>> 0;
      const rectp = esp.add(4).readPointer();
      const params = rd(esp, 2) >>> 0;            // [esp+8] = BoxSpriteParams*
      const caller = esp.readPointer();           // [esp] = return addr
      const L = rectp.readS32(), T = rectp.add(4).readS32(), R = rectp.add(8).readS32(), B = rectp.add(0xc).readS32();
      if (dest === FQ_BUF) {
        add("box_sprite/direct", "frame", L, T, R, B,
            `${paramLabel(params)}  caller=${sVA(caller)}  (pristine path)`);
      } else if (PATCHED && resolveFramebuf() && dest === framebuf) {
        // small native render into the scratch -> remember for the paired Buffer_draw_2
        pendingNative = { w: R - L, h: B - T, params, caller };
      }
    },
  });

  // ---- frames: SCALED placement (patched) via Buffer_draw_2(src=g_frame_buf) --
  Interceptor.attach(VA(BUF_DRAW_2), {
    onEnter() {
      const esp = this.context.esp;
      const dest = rd(esp, 1) >>> 0;
      if (dest !== FQ_BUF) return;
      const src = u32(this.context.ecx) >>> 0;
      const X = rd(esp, 3), Y = rd(esp, 4), num = rd(esp, 5), den = rd(esp, 6);
      // TRUE blitted size = the source buffer's actual dims x num/den (num/den=1/1 here,
      // so the frame is placed 1:1 from g_frame_buf at its rendered size). This is the
      // reliable R/B -- the pendingNative pairing catches the wrong box_sprite.
      const bw = bufWH(src);
      const bufW = bw.w, bufH = Math.abs(bw.h);
      const d = den || 16, sw = rnd(bufW * num / d), sh = rnd(bufH * num / d);
      const plabel = pendingNative ? paramLabel(pendingNative.params) : "params?";
      const caller = pendingNative ? sVA(pendingNative.caller) : sVA(esp.readPointer());
      const pn = pendingNative ? `pairedNative=${pendingNative.w}x${pendingNative.h}` : "unpaired";
      pendingNative = null;
      add("draw_2/scaled", "frame", X, Y, X + sw, Y + sh,
          `${plabel}  num/den=${num}/${den} srcBufWH=${bufW}x${bufH} (${pn}) blitCaller=${caller}`);
    },
  });

  // ---- portrait via Sprite_draw_2 (hook the chain head on patched) -----------
  let spriteHook = VA(SPRITE_DRAW_2);
  try {
    const b0 = VA(SPRITE_DRAW_2).readU8();
    if (PATCHED && b0 === 0x68) {                 // push imm32 ; ret  (esp-neutral detour)
      const tgt = VA(SPRITE_DRAW_2).add(1).readU32() >>> 0;
      spriteHook = ptr(tgt);
      log(`  Sprite_draw_2 @0x5e4b4a detoured (push 0x${tgt.toString(16)}; ret) -> hooking chain head @0x${tgt.toString(16)}`);
    } else if (PATCHED) {
      log(`  WARNING: patched but 0x5e4b4a first byte = 0x${b0.toString(16)} (expected 0x68 push detour); hooking entry directly`);
    }
  } catch (e) { log("  Sprite_draw_2 detour probe threw: " + e); }
  Interceptor.attach(spriteHook, {
    onEnter() {
      const esp = this.context.esp;
      const dest = rd(esp, 1) >>> 0;
      if (dest !== FQ_BUF) return;
      const self = u32(this.context.ecx) >>> 0;
      const x = rd(esp, 3), y = rd(esp, 4), num = rd(esp, 5), den = rd(esp, 6);
      let w = -1, h = -1;
      try { const sp = ptr(self); w = sp.add(0x10).readS32(); h = sp.add(0x14).readS32(); } catch (e) {}
      // drop the 9-slice frame-tile sprites (6x6 corners / 24x6 edges) -- pure noise
      if (Math.max(w, h) < MIN_SPRITE) { tilesSkipped++; return; }
      const d = den || 16, sw = rnd(w * num / d), sh = rnd(h * num / d);
      add("sprite/portrait", "portrait", x, y, x + sw, y + sh,
          `num/den=${num}/${den} spriteWH=${w}x${h} sprite=0x${self.toString(16)} caller=${sVA(esp.readPointer())}`);
    },
  });

  // ---- PATCHED-only: capture the INPUT rect at each thunk-chain stage --------
  // So the fix can be written as exact vanilla x g/16, not a re-tuned delta.
  // Pipeline (faction quote): d5a0 OUTER  content_frame -> (union_align skip) -> d5a0_center -> thick
  //                           d528 INNER  d528_inset    -> channel_adjust      -> (frame_align skip) -> devfill
  if (PATCHED) {
    const T_CONTENT_FRAME = 0x00668BD0;   // menu_strip_thunks + 0x9D0  (d5a0 engine-in)
    const T_D5A0_CENTER   = 0x00A12900;   // pcave2 + 0x6900 (RELOCATED 2026-07-08)  (d5a0 g/16 setter)
    const T_D528_INSET    = 0x00A0C620;   // pcave2 + 0x620            (d528 engine-in)
    const T_CHANNEL_ADJ   = 0x00A12A00;   // pcave2 + 0x6A00 (RELOCATED 2026-07-08)  (d528 g/16 setter, g_frame_inset_rect)
    const G_INSET_RECT    = 0x00A0C5D0;   // pcave2 + 0x5D0            (16-byte scratch RECT)

    const rectAt = (p) => `L=${p.readS32()} T=${p.add(4).readS32()} R=${p.add(8).readS32()} B=${p.add(0xc).readS32()}`;
    const stageSeen = new Set();
    const stage = (tag, getRect) => {
      if (stageSeen.has(tag)) return;      // dedup (redraws)
      stageSeen.add(tag);
      try { log(`  [STAGE ${tag}] rect ${rectAt(getRect())}  g=${gNow()}`); } catch (e) { log(`  [STAGE ${tag}] read threw: ${e}`); }
    };

    Interceptor.attach(VA(T_CONTENT_FRAME), {
      onEnter() { if ((u32(this.context.ecx) >>> 0) === FQ_BUF || (u32(this.context.esi) >>> 0) === FQ_POPUP)
                    stage("d5a0 ENGINE-IN (content_frame)", () => this.context.esp.add(4).readPointer()); },
    });
    Interceptor.attach(VA(T_D5A0_CENTER), {
      onEnter() { stage("d5a0 PRE-THICK (d5a0_center)", () => this.context.esp.add(4).readPointer()); },
    });
    Interceptor.attach(VA(T_D528_INSET), {
      onEnter() { if ((u32(this.context.esi) >>> 0) === FQ_POPUP)
                    stage("d528 ENGINE-IN (d528_inset)", () => this.context.esp.add(4).readPointer()); },
    });
    Interceptor.attach(VA(T_CHANNEL_ADJ), {
      onEnter() { stage("d528 PRE-CHANNEL (channel_adjust, g_frame_inset_rect)", () => VA(G_INSET_RECT)); },
    });
    log("  PATCHED stage-input hooks installed (content_frame/d5a0_center/d528_inset/channel_adjust).");
  }

  log("hooks installed. Open the faction-selection screen (quote box + leader portrait).");
}
