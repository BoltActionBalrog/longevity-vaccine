// hook_prodpicker.js v2 — ground-truth trace of the base production picker (ProdPicker).
//
// v1 POSTMORTEM (2026-08-03): v1 logged good geometry but the dialog closed instantly and
// never displayed. Cause was v1's OWN attach set, not the engine. Audit of the live exe:
//   * BaseButton_init 0x607210        = baked `push 0xa0d090; ret` detour  -> untouchable (hazard #5)
//   * Buffer_write_cent_l_7 0x5DD130  = baked `push 0xa11fa0; ret` detour  -> untouchable
//     (v1's entry-byte guard only tested E9/E8 and missed the 0x68 push form)
//   * call sites whose CALLEE entry is baked-detoured (hazard #7a): 0x417BFD->BasePop_exec_3,
//     0x494915/0x494960/0x4176E1->GraphicWin_init, the four Font_init sites, 0x492CDB->veh_draw.
//     Signature seen in the log: cellName font "size" read back as 0x02ED000F = a Frida
//     trampoline dword (hazard #7's value family).
//
// v2 RULE: **function ENTRIES only, all verified undetoured, keyed on this.returnAddress.**
// Zero mid-function attaches, zero call-site attaches -> the site-hook + detoured-entry
// combination that causes silent non-execution cannot arise. Everything v1 measured from a
// forbidden site is instead read from persistent struct state at a clean host, or is already
// pinned by a formula v1's numbers confirmed exactly:
//     cell rect = {col*colw+0x1B, row*pitch+4, (col+1)*colw+0x18, row*pitch+pitch+1}
//     facility icon size = pitch*3/7          unit zoom num = pitch*2/3  (g_map_zoom_num)
// so those hooks are simply gone rather than re-hosted.
//
// Attach set (all confirmed `clean` against the live exe by scratchpad audit_attach.py):
//   0x494700 ProdPicker_exec        entry+leave : open/close, args, env, full field dump
//   0x4927C0 ProdPicker_draw_cell   entry       : one post-init window/button/font dump per open
//   0x493C70 ProdPicker_draw_visible entry      : redraw marker (proves the dialog painted)
//   0x4941C0 select / 0x494280 page_nav / 0x4945D0 on_button_clicked : interaction proof
//   0x6054D0 ScrollBar_init_inner   entry       : only fires if item_count > vis_cells
//   0x49D540 FUN_49D540             entry       : "1"-tab candidate
//   0x5DCEA0 write_l_3 / 0x5DD3B0 write_right_l_5 entry : "1"-tab text census (picker-gated)
//
// DRIVE LIST (per resolution): open the picker from the HUD CHANGE button AND from inside the
// base screen; open the queue editor (QUEUE list); scroll if the list is long enough; select a
// couple of different items; let the selected unit's flag animate; then CANCEL out.
//
// v3 DRIVE LIST (2026-08-05, label-y + hit-box pass): at 4K AND at 1024x768 —
//   open the picker, let it draw once (text geometry logs itself), then CLICK deliberately:
//   (a) just inside the LEFT edge of a cell's drawn border, (b) just inside its RIGHT edge,
//   (c) just under its TOP border, (d) near the cell centre. Note which cell highlights.
//   Then CANCEL out. The [select] lines + [write]/[wrect]/[measure] lines are the deliverable.

"use strict";
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_prodpicker.log";
log("=== hook_prodpicker.js v3 started ===");
installAVHandler("prodpicker");

if (requireBase()) {
  const PICKER = 0x6A8044;                 // BaseWin_g+0xA1C
  const FONTS = [[0xA9C, "cellName"], [0xAC4, "big"], [0xAEC, "stats"], [0xB14, "button"]];
  const hex = v => "0x" + u32(v).toString(16);
  const sVA = p => { try { return "0x" + p.sub(TERRANX_BASE).add(0x400000).toString(16); } catch (e) { return "" + p; } };
  const rd32 = va => { try { return VA(va).readS32(); } catch (e) { return NaN; } };

  let inPicker = false, openSeq = 0, dumped = false;
  const caps = {}, seen = new Set();
  const capped = (t, m) => { const k = openSeq + ":" + t; caps[k] = (caps[k] || 0) + 1; return caps[k] > m; };
  const once = k => seen.has(k) ? false : (seen.add(k), true);
  const dwords = (p, off, n) => {
    const o = [];
    for (let i = 0; i < n; i++) { try { o.push(hex(p.add(off + 4 * i).readU32())); } catch (e) { o.push("?"); } }
    return o.join(",");
  };

  function env(tag) {
    const bw = rd32(0x6A7AEC), bh = rd32(0x6A7AF0);
    log("[env " + tag + "] ScreenW=" + rd32(0x9B7B1C) + " ScreenH=" + rd32(0x9B7B20) + " g=" + rd32(0x668740) +
        " | BaseWin canvas w=" + bw + " h=" + bh + " origin=(" + rd32(0x6A7764) + "," + rd32(0x6A7768) + ")" +
        " | picker gwinit ARGS(derived, pre-thunk) = (0,0," + bw + "," + (-bh) + ")");
  }

  function winRect(p, label) {
    try {
      log("  [win " + label + "] @" + sVA(p) + " w=" + p.add(0x4C4).readS32() + " h=" + p.add(0x4C8).readS32() +
          " +0x13C=[" + dwords(p, 0x13C, 4) + "] clip+0x474=[" + dwords(p, 0x474, 4) + "]");
    } catch (e) { log("  [win " + label + "] unreadable " + e); }
  }

  function fullDump(why) {
    const pk = VA(PICKER);
    log("[dump — " + why + "]");
    // grid fields (persist after build_items; v1 read these mid-function, v2 reads them here)
    log("  [grid] cols=" + pk.add(0xA810).readS32() + " visRows=" + pk.add(0xA814).readS32() +
        " count=" + pk.add(0xA818).readS32() + " colw=" + pk.add(0xA81C).readS32() +
        " pitch=" + pk.add(0xA820).readS32() + " winW=" + pk.add(0xA824).readS32() +
        " winH=" + pk.add(0xA828).readS32() + " visCells=" + pk.add(0xA82C).readS32() +
        " pitchSeed=" + pk.add(0xA838).readS32());
    winRect(pk, "picker(POST-init: compare w/h vs derived ARGS above)");
    log("  [picker hdr +0x100..+0x180] " + dwords(pk, 0x100, 32));
    winRect(pk.add(0x7120), "scrollbar");
    const n = pk.add(0xB6C).readS32();
    for (let i = 0; i < 9; i++) {
      const b = pk.add(0xB74 + i * 0xB4C);
      try {
        log("  [btn " + i + (i < n ? "" : "(unused)") + "] r=(" + b.add(0x13C).readS32() + "," + b.add(0x140).readS32() +
            "," + b.add(0x144).readS32() + "," + b.add(0x148).readS32() + ") w=" + b.add(0x4C4).readS32() +
            " h=" + b.add(0x4C8).readS32());
      } catch (e) {}
    }
    log("  [fields] btn_count=" + n + " btn_w=" + pk.add(0xB70).readS32() +
        " queue_mode=" + pk.add(0xB68).readS32() + " sel=" + pk.add(0xA774).readS32() +
        " firstVis=" + pk.add(0xA77C).readS32());
    // Font structs read directly — Font_init is detoured, so its call sites are off-limits.
    FONTS.forEach(f => log("  [font " + f[1] + " @" + hex(PICKER + f[0]) + "] " + dwords(pk, f[0], 10)));
    log("  [zoom globals] mapZoomNum=" + rd32(0x691E6C) + " den=" + rd32(0x691E70) +
        "  (expect num == pitch*2/3; facility icon px == pitch*3/7)");
    // Cell rects are pinned by a formula v1 confirmed exactly; print predictions, don't hook.
    const cw = pk.add(0xA81C).readS32(), pt = pk.add(0xA820).readS32();
    log("  [cell rect law] col0row0=(" + (0 * cw + 0x1B) + ",4," + (1 * cw + 0x18) + "," + (pt + 1) +
        ")  col4row3=(" + (4 * cw + 0x1B) + "," + (3 * pt + 4) + "," + (5 * cw + 0x18) + "," + (4 * pt + 1) + ")");
  }

  Interceptor.attach(VA(0x494700), {          // ProdPicker_exec — clean entry (push ebp)
    onEnter() {
      inPicker = true; openSeq++; dumped = false;
      const sp = this.context.esp;
      log("\n=== ProdPicker_exec OPEN #" + openSeq + " ecx=" + hex(this.context.ecx) +
          " base=" + hex(arg(sp, 1)) + " faction=" + argS(sp, 2) +
          " saveWin=" + hex(arg(sp, 3)) + " queueMode=" + argS(sp, 4) +
          " caller=" + sVA(this.returnAddress));
      env("open");
    },
    onLeave(rv) {
      log("=== ProdPicker_exec CLOSE #" + openSeq + " ret=" + rv.toInt32() +
          " (-9999 = cancelled/no choice)\n");
      inPicker = false;
    }
  });

  Interceptor.attach(VA(0x4927C0), {          // draw_cell entry — host for the one-shot dump
    onEnter() { if (!dumped) { dumped = true; fullDump("first cell draw, open #" + openSeq); } }
  });
  Interceptor.attach(VA(0x493C70), {          // draw_visible entry — proves the dialog painted
    onEnter() { if (!capped("drawvis", 6)) log("[draw_visible] firstVis=" + VA(PICKER).add(0xA77C).readS32()); }
  });
  // NB: at a function ENTRY the prologue has NOT run, so EBP still belongs to the caller —
  // v2 read args off ebp and logged garbage (id=198722). Args live at [esp+4], [esp+8].
  // v3: 0x4941C0 is select-from-xy: row = y/pitch, col = x/colw (LOCAL coords, no inset
  // subtraction — vanilla maps the gutters/insets to the neighbor cell). Log the raw x,y so
  // the user's edge-clicks pin the hit-box skew numerically.
  Interceptor.attach(VA(0x4941C0), {
    onEnter() {
      if (capped("sel", 40)) return;
      const sp = this.context.esp, x = argS(sp, 1), y = argS(sp, 2);
      const pk = VA(PICKER), cw = pk.add(0xA81C).readS32(), pt = pk.add(0xA820).readS32();
      log("[select] x=" + x + " y=" + y + " -> col=" + Math.floor(x / cw) + " row=" + Math.floor(y / pt) +
          "  (visual col-origin=" + (Math.floor(x / cw) * cw + Math.floor(0x1B * rd32(0x668740) / 16)) + ")");
    }
  });
  Interceptor.attach(VA(0x494280), {
    onEnter() {
      if (!capped("page", 12))
        log("[page_nav] delta=" + argS(this.context.esp, 1) + " firstVis=" + VA(PICKER).add(0xA77C).readS32());
    }
  });
  Interceptor.attach(VA(0x4945D0), {
    onEnter() { log("[button_clicked] id=" + argS(this.context.esp, 1)); }
  });

  // ---- v3 (2026-08-05): cell-text geometry — the "label sits low" defect ----
  // draw_cell text stack (static, .bak): title via 0x5DDAB0 rect=(L,T+5,R,T+3m+5) [+5 NATIVE];
  // then rect2=(L+2,T,R-2,B), h=0x5DC360(text,w), y=B-h, desc via 0x5DDAB0; y-=lh, name via
  // write_cent_l_7; unit stats "N turns\nA-B-C" via write_cent_l_7 rect=cell. All metrics come
  // from the SCALED fonts (sublinearity suspect). Which call draws which string + the final y
  // is ambiguous statically -> capture all of it, per open, at 4K AND at 1024 (native law).
  // ATTACH NOTES: 0x5DDAB0 + 0x5DC360 entries verified clean (live==bak, scratchpad audit).
  // write_cent_l_7 0x5DD130 AND inner writer 0x5DCAE0 are baked-detoured (comm_cent7 /
  // menu_text) -> attach at the DETOUR TARGET 0xA121A0 = thunk_menu_text entry = the effective
  // wmfr_l entry (entered only via the push/ret stub; first insn is 6-byte cmp; no branch
  // targets inside the 5-byte window; picker ecx != menu buffer so the thunk passes through).
  const CELLBUF = 0x6A8488;               // picker+0x444 — draw_cell's ecx for every cell text
  const isCellBuf = ctx => ctx.ecx.equals(VA(CELLBUF));
  function fontInfo(bufVa) {
    try {
      const f = VA(bufVa).add(0x52C).readPointer();
      return "f0=" + f.readS32() + " lh=" + f.add(0xC).readS32() +
             " f4=" + f.add(0x10).readS32() + " size=" + f.add(0x18).readS32();
    } catch (e) { return "font=?"; }
  }
  Interceptor.attach(VA(0x5DDAB0), {      // multiline write into rect (title + desc)
    onEnter() {
      if (!inPicker || !isCellBuf(this.context) || capped("txtgeo", 160)) return;
      const sp = this.context.esp, s = tryStr(arg(sp, 1));
      let r = "?";
      try { const p = ptr("0x" + u32(arg(sp, 2)).toString(16)); r = dwords(p, 0, 4); } catch (e) {}
      const k = "wr:" + sVA(this.returnAddress) + ":" + s + ":" + r;
      if (once(k)) log("[wrect ret=" + sVA(this.returnAddress) + "] \"" + (s || "?") +
                       "\" rect=[" + r + "] " + fontInfo(CELLBUF));
    }
  });
  Interceptor.attach(VA(0x5DC360), {      // wrapped-text height measure (feeds y = B - h)
    onEnter() {
      if (!inPicker || !isCellBuf(this.context) || capped("txtgeo", 160)) { this.skip = true; return; }
      this.s = tryStr(arg(this.context.esp, 1));
      this.w = argS(this.context.esp, 2);
    },
    onLeave(rv) {
      if (this.skip) return;
      const k = "ms:" + this.s + ":" + this.w + ":" + rv.toInt32();
      if (once(k)) log("[measure] \"" + (this.s || "?") + "\" w=" + this.w + " -> h=" + rv.toInt32() +
                       " " + fontInfo(CELLBUF));
    }
  });
  Interceptor.attach(VA(0xA121A0), {      // effective wmfr_l entry (final resolved x,y per line)
    onEnter() {
      if (!inPicker || !isCellBuf(this.context) || capped("txtgeo", 160)) return;
      const sp = this.context.esp, s = tryStr(arg(sp, 1));
      const k = "wm:" + sVA(this.returnAddress) + ":" + s + ":" + argS(sp, 2) + ":" + argS(sp, 3);
      if (once(k)) log("[write ret=" + sVA(this.returnAddress) + "] \"" + (s || "?") +
                       "\" x=" + argS(sp, 2) + " y=" + argS(sp, 3) + " " + fontInfo(CELLBUF));
    }
  });

  // Icon scale, measured at CLEAN callee entries keyed on returnAddress (both verified
  // undetoured). The zoom globals are set per-cell, so the one-shot dump reads them too early.
  Interceptor.attach(VA(0x617230), {          // Caviar_draw — unit model
    onEnter() {
      if (sVA(this.returnAddress) !== "0x492d74" || capped("caviar", 3)) return;
      const sp = this.context.esp;
      log("[unit-icon] caviar x=" + argS(sp, 2) + " y=" + argS(sp, 3) +
          " zoomNum=" + rd32(0x691E6C) + " den=" + rd32(0x691E70) +
          "  (law: num == pitch*2/3 == " + Math.floor(VA(PICKER).add(0xA820).readS32() * 2 / 3) + ")");
    }
  });
  Interceptor.attach(VA(0x5E3E00), {          // facility/SP icon draw (explicit size arg)
    onEnter() {
      if (sVA(this.returnAddress) !== "0x492f57" || capped("fac", 3)) return;
      const sp = this.context.esp, a = [];
      for (let i = 1; i <= 8; i++) a.push(hex(arg(sp, i)));
      log("[facility-icon] args=" + a.join(",") +
          "  (law: size == pitch*3/7 == " + Math.floor(VA(PICKER).add(0xA820).readS32() * 3 / 7) + ")");
    }
  });
  Interceptor.attach(VA(0x6054D0), {          // ScrollBar_init_inner — clean entry
    onEnter() {
      if (!inPicker) return;
      const sp = this.context.esp, a = [];
      for (let i = 1; i <= 7; i++) a.push(hex(arg(sp, i)));
      log("[scrollbar_init] ecx=" + hex(this.context.ecx) + " ret=" + sVA(this.returnAddress) + " args=" + a.join(","));
    }
  });

  // ---- "1"-tab census (cent_l_7 is detoured -> not hooked; these two are clean) ----
  Interceptor.attach(VA(0x49D540), {
    onEnter() { if (!capped("f49d540", 3)) log("[FUN_49D540] ecx=" + hex(this.context.ecx) + " ret=" + sVA(this.returnAddress)); }
  });
  function tryStr(u) {
    try { const s = ptr("0x" + u32(u).toString(16)).readCString(32); if (s && /^[\x20-\x7e]+$/.test(s)) return s; } catch (e) {}
    return null;
  }
  [[0x5DCEA0, "write_l_3"], [0x5DD3B0, "write_right_l_5"]].forEach(t => {
    Interceptor.attach(VA(t[0]), {
      onEnter() {
        if (!inPicker || capped("txt", 80)) return;
        const sp = this.context.esp, s = tryStr(arg(sp, 1));
        const k = "txt:" + t[1] + ":" + s + ":" + argS(sp, 2) + ":" + argS(sp, 3);
        if (once(k)) log("[text " + t[1] + "] \"" + (s || "?") + "\" x=" + argS(sp, 2) + " y=" + argS(sp, 3) +
                         " ret=" + sVA(this.returnAddress));
      }
    });
  });

  log("hook_prodpicker v3: " + "14 hooks installed (clean entries + the 0xA121A0 detour-target entry).");
}
