// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// Design Workshop (DesignWin 0x71F2B0) scaling PROTOTYPE v1 — Frida, zero mid-function
// attaches. Facts + laws: work\_dw_static_map.md (§PROBE RESULTS), _dw_source_map.md §8,
// _dw_pixel_geometry.md, memory project-smac-design-workshop.
//
// LEVERS (all one-time Memory.patchCode immediates applied at the first DesignWin_exec
// with g>16, before its DesignWin_build; the builder then produces scaled tables itself,
// so the part-box click Spots, the 25 BaseButton_init rects and the GraphicWin_init
// window geometry are all born scaled — no post-hoc rect surgery):
//   W1 window: h imm 0x258 -> s(600) (h = s(600) - strip_dev); w = [pcx w] -> MOV ecx,imm
//      CEIL(623 g/16) (railscale floor-descales it back to exactly 623); x nudge 0x20 -> s(32).
//   W2 backdrop: after build, deswin.pcx (623x368) is re-rendered at device density into
//      BOTH the pcx Buffer (Buffer_resize; the painters restore box backgrounds from it with
//      Buffer_copy_2 at the scaled rects) and the window canvas: centre-aligned NN for art,
//      every vertical dither pair regenerated on the P-law stripe (SL.stripeTop) — never
//      resampled; rows past the image = key 9 (transparent over the console ears).
//   M  modal table: preview/part-box literals, button-row insets 0x1B/0x20/0x14/3/6
//      (button HEIGHT by SL.scaleFloor = the shrink's exact inverse).
//   C  console overlays: seed insets 3/4/7/0x15/0x18/8, preset buttons h 0x15 pitch 0x17,
//      slot-strip cell insets 3/2/+0xF/+0xC, draw_flash insets/offsets, title-box insets.
//   F  fonts: 3 private Font_init sizes (10/12/16) + leadings (3/5/4); painter-local fonts
//      (title 18, slot 10, flash 12/12b). Button labels already use g_popup_title_font.
//   Z  Caviar zooms x g/16 (preview 0.14, chassis 0.05, weapon 0.15/0.06/0.08, armor 0.07,
//      reactor 0.2, picker 0.06/0.1/0.2); preview veh_draw size 0xE -> (14+16)g/16-16.
//   R  rails: the window's own slide_show/slide_hide E8 sites 0x43D1BE/0x43D1FA ->
//      thunk_popup_railshow/railhide (arm the popup rail gate; SE v2 / diplo recipe).
//   B  FlatButton 2D-zoom bracket: thunk_btn_gate_pre HIT range retargeted at the 25 DesignWin
//      FlatButtons for the modal's lifetime (v1 borrowed g_faction_active -> MENU/COMMLINK
//      double-enlarge banding; see setGateRange). Bake = a third HIT prefix.
// v3 (adversarial dither audit work\_dw_dither_audit.md, 2026-08-28):
//   D1 backdrop classifier: FAMILY test (a family pixel with a different family member directly
//      above or below is a pair member) replaces v1's up==dn&&up2==v test, which could never
//      classify a dither row next to a stroke -> 13,183 native px went out NN = the 3-px
//      black/navy beads along every disc grid line and the k3/n2/k3 frame bands (#4-#7).
//      Families + stroke rows/cols are MEASURED from the pcx at run time (census-verified).
//   D2 strokes: the pcx axes are enlarged with SL.lineAxisMap (every measured stroke row/col
//      renders at exactly K=strokeWidth(g), the field absorbs the remainder via distribute) —
//      v1's centre-aligned NN gave 2/3-px verticals at 4K and 1/2-px separator pairs at g=25/22.
//   D3 button faces: per-draw P-law restripe of every DesignWin FlatButton canvas at the
//      item-draw slot entry 0x404220 (vtbl+0x14 default stub; MainWin's slot is the same stub,
//      so the 14 presets + 2 arrows come through it too) + a 120 ms canvas watcher for draws that
//      bypass it (SE v17/v20 recipe: pair detected per draw from one face column, ring pinned to
//      K, trailing key rows overdrawn). The 2D-zoom bracket's thunk_btn_devfill re-tiles at 1 px
//      (the FACTION parity language) which reads flat at 4K.
//   D4 union frame: the master painter's Buffer_box_sprite site 0x437B89 (d5a0, canvas dest,
//      thunk_hud_boxframe is HUD-dest gated) -> thunk_box_thick_hollow_flat; its +-3 inset -> s(3).
//   D5 chrome density DECISION: the modal keeps the popup-class P law for its (12,12,16)/black
//      chrome (the console's presets-grid/arrow-cell tile is the HUD-locked 1-px language; the
//      seam crop shows stone art between them, not dither-on-dither). Judge at g=25.
//   v4 (user run of v3: slot cells shrink along the strip, disc grid ragged at g=22/25, 4K post-close AV):
//   D6 PHASE VARIANTS: an index that is not a family but lives on ONE row parity (>=95%) and sits
//      between two rows of the SAME family colour (>=80%) is a dither-row substitute (census: 187
//      (11,18,24) = the disc grid lines, even rows only, sandwiched by black; the ring stroke 34 is
//      correctly excluded: 2685/960 parity split). v3 passed it through NN so the line also landed
//      on black-phase rows = the dotted/ragged grid. A variant classifies like a family member:
//      its own colour on its parity's phase, its mate on the other (offline sim: 2-on/1-off in
//      phase at g=25, 3/2 at g=40).
//   D7 slot strip 0x43D510: the cell inset `mov edi,2` x2 was scaled but its four partners were not
//      (cellW `-2` disp8 @0x43D5EB, empty-branch stride `lea [ecx+2]` @0x43D880, restore `mov esi,2`
//      @0x43D890 (empty) / @0x43DCCC (unit)) -> every cell shrank by 2*(s(2)-2) = 6 px @4K, 2 px
//      @1600/1920 (measured 179x125 -> 125x71 across the ten cells at 4K). All five now s(2).
//   D8 HEAPCHK: HeapValidate over every process heap at each checkpoint (build enter/leave, backdrop,
//      exec enter/leave, paints, first button draws, slide/onmode leave, 400 ms poll while open);
//      the FIRST failing label brackets the writer that overruns (the 4K post-close AV is an ntdll
//      free-list Flink/Blink check: `mov ecx,[ecx]; mov edx,[edx+4]; cmp ecx,edx` on 0x53949494).
//      BUFPITCH logs the button-canvas pitch source once per size (bufInfo's +0x4A8 vs (w+3)&~3).
//   v5 (user run of v4 at 4K: cells uniform = D7 LANDED; disc lawful; but HEAPCHK FAIL between idle
//      polls after paint#1 (no AV logged), hovered cell fill = NN beat of (13,28,48)/black, selected
//      cell fill ABSENT (the container's 1-px C6/41 tile shows through the ring)):
//   D9 BRACKET TRACE of the HUD box-sprite pipeline: cave-thunk ENTRIES thunk_hud_boxframe 0xA11740
//      (MainWin-dest gate; table lookup by RETURN ADDRESS -> unknown sites pass the caller's rect
//      to thunk_box_thick_hollow_flat with [0xA0E554]=1), hollow_flat 0xA0C140, devfill 0xA0E2A0,
//      fe_pair_remap 0xA1C000, plus DesignWin painter entries slot_strip 0x43D510 / draw_flash
//      0x43DD50 / iface mouse-move 0x43D350 / hover-bubble 0x43D290 — args logged (dest, rect,
//      params, ret) and HeapValidate after EVERY call: the first FAIL names the overrunning draw.
//      PARAMS lines dump d528/d550/d578/d5a0 (10 dwords + the fill Sprite's dims) at exec enter.
//   v6 (user run of v5 at 4K, trace `_dw_crops\v3\_v5run.txt`): (a) the SELECTED cell was drawn with
//      params 0x78d5f0 = d528 + 5*40: `mov edi,2` @0x43D726 is DUAL-PURPOSE (`mov edi,2; mov eax,edi`
//      -> eax = STATE index 2 (selected) AND edi = the inset 2); scaling it to s(2) selected state 5.
//      D7' the 9-byte site becomes `push s2; pop edi; push 2; pop eax; jmp` (state 2, inset s(2)).
//      (b) the HOVER params d550 fill pair (13,28,48)/black is not in fe_pair_remap's pair table ->
//      NN beat (3/2/3/3). D10 restripe that cell's interior in the MainWin buffer after its
//      hollow_flat draw (bake: extend the remap pair table / DW-keyed pair). (c) the heap FAIL sits
//      right after two devfill draws into 0x8C72AC = TutWin canvas (TutWin 0x8C6E68 + 0x444), the
//      tutorial popup that opens with the workshop (1599x412 backdrop) - every hooked call passed its
//      own check, so the writer is in the UNHOOKED TutWin paint (or the preview animation tick).
//      D11 brackets: cave ENTRIES (onEnter-only: tail-chained thunks must not get their return
//      address rewritten) thunk_btn_stripes/btn_devfill/tutwin_fonts/tutwin_line/tutwin_backdrop/
//      tutwin_ctop/build_scaled_fonts/bandmap_blit/bilinear_blit + engine entries TutWin_tut_win
//      0x4BDFE0 / draw_arrow 0x4BDEA0 / on_button_clicked 0x4BDCC0 / popups_tutorial 0x5888E0 /
//      DesignWin_draw_unit_preview 0x436090 / Caviar_draw 0x617230 (enter+leave), plus a 100 ms
//      heap poll while the workshop is open.
//   v7 (user run of v6 at 4K "looks correct": D7' selected fill back, D10 hover restripe OK; heap
//      FIRST FAIL = 'leave draw_unit_preview #11', last ok 'leave Caviar_draw #24' -> the write is in
//      the preview painter's TAIL after Caviar_draw on the 11th 40 ms tick; TutWin_draw_arrow #4 was
//      logged in between with no check of its own passing -> it runs on ANOTHER THREAD (blink timer)):
//   D12 fine brackets on draw_unit_preview's 21 internal callees (entries, none baked-detoured;
//      skipped: veh_draw/Buffer_set_font/write_cent_l_7 = detour families, CRT strcat/itoa = hot,
//      static-buffer string ops) — checks only while inside the painter and from tick >= 5; every
//      HEAPCHK label now carries tid= (Process.getCurrentThreadId) and the check's duration is
//      accumulated (max/avg logged at exec leave). The 120 ms canvas watcher is OFF as a control
//      (it writes from the Frida thread; no WATCH line fired in the v6 run, so it is not the writer).
//   v8 (v7 4K run: FIRST FAIL = 'pv-leave Caviar_reset #14 tick 11', enter clean -> the writer IS
//      Caviar_reset 0x618470 (the preview's call @0x436366, arg 0). It is NOT per-object: it clears the
//      GLOBAL Caviar render target - z-plane [0x9B9100] = malloc(0x20000) = 256x256x2 (stride 256 baked:
//      `shl esi,8`, `add ebx,0x200`), Buffers 0x9B9108/0x9B96B0, dirty rect 0x9B9690 minx / 0x9B9694 miny /
//      0x9B9698 maxx / 0x9B969C maxy - and memsets rows miny..maxy of the plane WITHOUT clipping the rect.
//      With the preview zoom 0.14 -> 0.35 @4K the rotating model's dirty rect passes row 256 on tick 11 and
//      the memset runs off the block = the heap corruption (post-close AV). ENGINE LIMIT: Caviar renders
//      into a hard 256x256 target, so Caviar zoom x g/16 is unsafe for large models at g=40.
//   D13 PROBE: per Caviar_draw site log dst/x/y/zoom and the dirty rect after the draw (running max per
//      site); at Caviar_reset entry CLAMP the rect to [0,256) (log "CAVIAR CLAMP") so the plane cannot be
//      overrun while measuring. Buffer 0x9B9108/0x9B96B0 dims logged once. All D9/D11/D12 brackets
//      REMOVED (the fill-pipeline/TutWin/preview hooks are done; a cave-thunk hook broke the quit modal's
//      art for the user - only the hollow_flat hook (needed by D10) remains, to test whether it is the one).
//      Decision pending the numbers: enlarge the Caviar target (stride census) vs render native + enlarge blit.
//   v9 (v8 4K run: preview dirty rect saturates 256x256 at zoom 0.35 (clamped 433x, `*** EXCEEDS 256`);
//      quit-modal art back once the cave-thunk hooks were gone): the Caviar target is a HARD 256x256 and
//      growing it would need the rasterizer's row tables -> NOT attempted. DESIGN (Z'): every DesignWin
//      Caviar zoom stays NATIVE (the Z levers are REMOVED) so each render fits the target exactly as
//      vanilla, and the enlargement moves to Caviar_draw's composite: the Buffer_draw_2 call @0x6175F4
//      (target 0x9B9108 -> dst, key 9, X-128, Y-128, num 1, den 1; the engine's own flag-0x20 mode
//      already renders x2 and composites at 1/2 = "render then scale at the composite" is a native idiom)
//      is redirected to a Frida-emitted shim: ebp (Caviar object, live at the call) == DesignWin's
//      Caviar 0x731A4C && g>16 -> X,Y -= 8*(g-16)*num/den (keeps the draw point = the target centre
//      fixed), num *= g, den *= 16, tail-jmp thunk_frame_enlarge 0xA17F80 (Buffer_draw_2 drop-in:
//      StretchBlt keyed NN into the shared scratch + clip-aware keyed copy-out, RET 0x18); else plain
//      Buffer_draw_2 (map/HUD vehdraw composites untouched). The aux composite 0x5D8EE0 @0x6175AC
//      (target2 0x9B96B0 with a colour table) is left 1:1 for this run - judge whether it matters.
//      The Caviar_reset clamp stays as a guard. BAKE: a pcave2 thunk with the same body + the E8 retarget.
//   v10 (v9 4K: HANG inside the first Caviar_draw (chassis icon) - the shim path never returns):
//      WATCHDOG run: onEnter-only hooks (log + lastSeen) on thunk_frame_enlarge 0xA17F80, the
//      keyed_stretch trampoline 0x668670 / ksb_v2 0xA1ADA0 / ensure_scratch 0x6686D0, Buffer_resize
//      0x5D79C0, Buffer_copy_3, thunk_draw2_clipkey 0xA180A0, Buffer_draw_2 0x5D84C0 (only while inside a
//      Caviar_draw), + the shim's argument snapshot at thunk_frame_enlarge entry and a hexdump of the
//      emitted shim; a 500 ms watchdog logs the last stage seen. TEMPORARY (cave-entry hooks).
//   v11: v9/v10 HANG = wrong primitive: thunk_frame_enlarge is the 9-slice BAND-MAP enlarger (bandmap_blit +
//      fe_pair_remap with band tables), not a keyed stretch - a Caviar sprite with zeroed bands spins it. The
//      shim now CALLs thunk_keyed_stretch_blit (0x668670 -> ksb_v2: ensure_scratch, Buffer_resize, Buffer_copy_3
//      StretchBlt, draw2_clipkey keyed copy-out; RET 0x2C) with (target, dst, 0,0,256,256, X-8(g-16)/den,
//      Y-8(g-16)/den, 16g/den, 16g/den, key) then RET 0x18. Watchdog hooks kept for this run.
//   v12 (user run of v11 4K+1600: unit renders "correct and faithful to pristine"; three asks):
//   (1) SELECTED slot fill at 1600 (g=25) is an NN beat (2,1,2,1,2,2,1 of (14,34,67)/(27,33,31), user
//      shot 193057): the d578 pair reaches the MainWin dest through hud_boxframe->hollow_flat like the
//      hover pair and is NOT restriped by the baked remap either -> D10 now restripes d578 too (bake:
//      both pairs into the remap table / a DW-keyed restripe).
//   (2) PART PICKER (chassis/weapon shots 193002/193009): window already scaled (canvas dims) but its
//      grid/fonts/frames/scrollbar/icons all native. Levers: cell rect law = ABSOLUTE native coords
//      x g/16 (x0=s(col*108+27) x1=s(col*108+132) y0=s(row*94+4) y1=s(row*94+95); no accumulation)
//      via a stub entered by a JMP at 0x433D84 (the lea/shl arithmetic) back to 0x433DC6; inset
//      `mov ecx,3` -> s(3); container frame L 0x17 -> s(0x17), R inset `add edi,-0x37` -> stub (s(55)
//      overflows imm8 at g=40); fonts push 10/12 -> s(); both Buffer_box_sprite E8s (cell 0x433E2C,
//      container 0x434285) -> thunk_box_thick_hollow_flat (D4 recipe; the picker canvas is not a HUD
//      dest); on_click vtbl slot 0x66B2FC -> descale stub (x,y * 16/g then the native hit test);
//      scrollbar = the popup-family rail recipe: thunk_rail_gate's ProdPicker imm is retargeted at the
//      live stack picker for the modal's lifetime (rail_slide_in -> sbfit re-fits the bar, grip zoom,
//      arrow stripes) + g_popup_active++ (diplo bracket) for the arrows' 2D zoom; empty cells' tile
//      0x6B33F8 fill restriped at the P law (dither law). The composite shim gate becomes DEST-based
//      (DW canvas 0x71F6F4 || picker canvas) so the picker's own Caviar (+0x2B9C, stack) enlarges too.
//   (3) UNIT IMAGE QUALITY experiments (the aliasing is the voxel rasterizer's own point sampling at a
//      zoom far below the model's voxel density; enlarging its 256^2 output NN reproduces it at device
//      density). FIT: every gated Caviar_draw first TRIAL-renders at native zoom with the composite
//      suppressed, reads the rasterizer's result bbox (ctx 0x9BB478 +8..+0x14) = native extent E at
//      this angle, then renders at zoom*k, k=min(g/16, 240/(1.06E)) and composites at W=256*(g/16)/k
//      (k==g/16 -> a 1:1 copy = true device-density render; preview at 4K: k~1.7 + 1.47x NN residual).
//      SSAA: when 2x device density fits (icons), render at 2x and 2x2 box-average with a palette
//      nearest-match (JS composite, candidates = the render's own indices, coverage >= 1/2). Engine
//      facts: aux composite 0x5D8EE0 never runs for DW draws (flag 6 -> +0xa4=0); Caviar_reset(1)
//      keeps the dirty rect, reset(0) memsets + zeroes it; ALL 89 code refs to the target globals live
//      in 0x616D00..0x618F40 (the rasterizer 0x639E60 takes ctx) -> a 512^2 target is a cluster-local
//      ~22-site patch (option E, not armed).
//   v13/v13a: option E = Caviar target TN^2 (tN in dw_mode.txt; 17 imms + 4 stubs at load, STUBCHK guards the
//      GC-freed-page bug that crashed v13). v14 (user 4K run of v13a: E works, but ~1 fps and the pod tank
//      see-through): (1) SSAA composite moved to a CModule (was 1144 ms/frame in JS on the 512-px preview);
//      (2) FOOTPRINT cave: the plotter's fixed 2x2 big-mode block -> n x n, n = max(2, ceil(zoom*partScale))
//      per part for gated draws (hook at 0x63E950), vanilla n=2 otherwise; site 0x6649B4, resume 0x664A29.
// NOT in v12 (known): title-box
// text row offsets; slot-strip veh_draw size (-10, the HUD C' lever already scales HUD-buffer
// dests); selected-slot fill unmeasured (needs a shot with a slot selected).
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_dw_proto.log";
log("=== hook_dw_scale_proto.js v15l started " + new Date().toISOString() + " ===");
globalThis.WP = { armed: false, addr: null, hits: [] };
Process.setExceptionHandler(function (details) {
  if (globalThis.WP.armed && details.type !== "access-violation") {                  // v15b: hardware write-watchpoint trap on the listbox width dword
    try { const c = details.context; globalThis.WP.hits.push(c.eip.toString() + " val=" + globalThis.WP.addr.readS32() + " type=" + details.type); } catch (e) { globalThis.WP.hits.push("err " + e); }
    return true;
  }
  if (details.type !== "access-violation") return false;
  try {
    const c = details.context;
    log("=== ACCESS VIOLATION (dw_proto) eip=" + c.eip + " esp=" + c.esp + " addr=" + details.memory?.address + " op=" + details.memory?.operation);
    try { log("  bytes@eip: " + Array.from(new Uint8Array(c.eip.readByteArray(12))).map(b => b.toString(16).padStart(2, "0")).join(" ")); } catch (e) {}
    try {
      const bt = Thread.backtrace(c, Backtracer.FUZZY);
      log("  backtrace(FUZZY): " + bt.slice(0, 24).map(a => { const m = Process.findModuleByAddress(a); return a + (m ? "(" + m.name + "+0x" + a.sub(m.base).toString(16) + ")" : ""); }).join(" "));
    } catch (e) { log("  backtrace failed: " + e); }
    for (let i = 0; i < 16; i++) { try { log("  [esp+0x" + (i * 4).toString(16) + "] = " + c.esp.add(i * 4).readPointer()); } catch (e) {} }
  } catch (e) {}
  return false;
});

if (requireBase()) {
  const SL = globalThis.SL;
  if (!SL) throw new Error("scaling_laws.js prelude missing");
  const G_OBJ = 0x71F2B0, G_SCALE = 0x668740, G_STRIPH = 0x7AF59C, G_SCREENW = 0x9B7B1C, G_SCREENH = 0x9B7B20;
  const G_MAINBUF = 0x7AEC64, G_PALETTE = 0x94C590, G_CURRENT = 0x733970;
  const A_EXEC = 0x43E9A0, A_BUILD = 0x43C270, A_MASTER = 0x4379A0, A_ONMODE = 0x43D120;
  const A_SLIDESHOW = 0x45D440, A_SLIDEHIDE = 0x45D970;
  const PCAVE2 = 0xA0C000;
  const T_RAILSHOW = PCAVE2 + 0x3550, T_RAILHIDE = PCAVE2 + 0x44D0;
  const G_FACTION_ACTIVE = PCAVE2 + 0x12D0;
  const KEY = 9;

  const Buffer_resize = new NativeFunction(VA(0x5D79C0), "int", ["pointer", "int", "int"], "thiscall");  // h POSITIVE
  // D8: heap validation checkpoints (kernel32 HeapValidate over every process heap)
  const k32 = Process.getModuleByName("kernel32.dll");
  const HeapValidate = new NativeFunction(k32.getExportByName("HeapValidate"), "int", ["pointer", "uint", "pointer"]);
  const GetProcessHeaps = new NativeFunction(k32.getExportByName("GetProcessHeaps"), "uint", ["uint", "pointer"]);
  let heapBad = false, heapChecks = 0, heapLastOk = "(none)", heapMsMax = 0, heapMsSum = 0;
  function heapCheck(label, quiet) {
    try {
      label = label + " tid=" + Process.getCurrentThreadId();
      const t0 = Date.now();
      const n = GetProcessHeaps(0, NULL);
      const arr = Memory.alloc(4 * Math.max(1, n));
      const m = GetProcessHeaps(n, arr);
      const bad = [];
      for (let i = 0; i < m; i++) { const h = arr.add(4 * i).readPointer(); if (!HeapValidate(h, 0, NULL)) bad.push(h); }
      heapChecks++;
      const dt = Date.now() - t0; heapMsSum += dt; if (dt > heapMsMax) heapMsMax = dt;
      if (bad.length) {
        if (!heapBad) log("HEAPCHK " + label + " FAIL heaps " + bad.join(",") + " (FIRST failure; last ok = '" + heapLastOk + "'; " + heapChecks + " checks so far)");
        heapBad = true;
      } else { heapLastOk = label; if (!quiet) log("HEAPCHK " + label + " ok (" + m + " heaps)"); }
    } catch (e) { log("HEAPCHK " + label + " error " + e); }
  }

  let g = 16;
  const s = v => SL.scalePx(v, g);
  function safeS32(p, d) { try { return p.readS32(); } catch (e) { return (d === undefined ? -0x7fffffff : d); } }
  function safeU32(p) { try { return p.readU32(); } catch (e) { return 0; } }
  function safeF32(p) { try { return p.readFloat(); } catch (e) { return NaN; } }
  function rect4(p) { return [safeS32(p), safeS32(p.add(4)), safeS32(p.add(8)), safeS32(p.add(12))]; }
  function rstr(p) { const r = rect4(p); return "(" + r.join(",") + ") [" + (r[2] - r[0]) + "x" + (r[3] - r[1]) + "]"; }
  function hex(v) { return "0x" + (v >>> 0).toString(16); }
  function pal(i) { const p = VA(G_PALETTE).add((i & 0xff) * 4); const v = safeU32(p); return [v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff]; }
  function learnG() {
    let v = safeS32(VA(G_SCALE), 0);
    if (v <= 0) { const sh = safeS32(VA(G_SCREENH), 768); v = Math.max(16, Math.min(40, Math.floor(16 * sh / 768))); }
    g = v;
  }
  function envStr() {
    return "ScreenW=" + safeS32(VA(G_SCREENW)) + " ScreenH=" + safeS32(VA(G_SCREENH)) + " g=" + g + " stripH=" + safeS32(VA(G_STRIPH));
  }

  // ---------------------------------------------------------------------------
  // Immediate patch table. [addr, immOff, width(1|4), value-fn, label]
  // width 1 = imm8/disp8 (range-checked), 4 = imm32. Value fns close over g.
  // ---------------------------------------------------------------------------
  // every value-fn carries .nat = the NATIVE immediate the site must hold before patching
  // (self-verifying: a wrong offset/encoding is skipped and logged, never written)
  const S = (a, b) => Object.assign(() => s(a) - (b ? s(b) : 0), { nat: a - (b || 0) });
  const NEG = a => Object.assign(() => -s(a), { nat: -a });
  const FLOAT = z => Object.assign(() => z * g / 16, { nat: z });                       // written as f32
  const VEH = sz => Object.assign(() => Math.min(48, Math.floor((sz + 16) * g / 16) - 16), { nat: sz });   // veh_draw size lever (HUD C' law); zoom (size+16)/16 capped at the engine's 4x (>4x blits are REJECTED — project_smac_stale_scale_float_crash)
  const FLOORH = h => Object.assign(() => SL.scaleFloor(h, g), { nat: h });             // FlatButton height: shrink's exact inverse
  const CEILW = w => Object.assign(() => Math.ceil(w * g / 16), { nat: w });            // window width: railscale floor-descale round-trips
  const P = [];
  const add = (addr, off, w, fn, label, kind) => P.push({ addr, off, w, fn, label, kind: kind || "int" });
  // --- builder 0x43C270: fonts + leadings ---
  add(0x43C2B7, 1, 1, S(10), "F0 size 10");        add(0x43C2D2, 2, 4, S(3), "F0 leading 3");
  add(0x43C2E6, 1, 1, S(12), "F1 size 12");        add(0x43C2F0, 2, 4, S(5), "F1 leading 5");
  add(0x43C304, 1, 1, S(16), "F2 size 16");        add(0x43C30E, 2, 4, S(4), "F2 leading 4");
  // --- builder: part boxes + preview literals ---
  add(0x43C314, 1, 4, S(0x1E), "box L 0x1E");      add(0x43C319, 1, 4, S(7), "box T 7");        add(0x43C31E, 1, 4, S(0x81), "box R 0x81");
  add(0x43C323, 6, 4, S(0x8C), "preview L");        add(0x43C32D, 6, 4, S(9), "preview T");      add(0x43C337, 6, 4, S(0x1C3), "preview R");
  add(0x43C341, 6, 4, S(0x140), "preview B");
  add(0x43C35D, 6, 4, S(0x5C), "box0 B 0x5C");     add(0x43C36D, 6, 4, S(0x65), "box1 T 0x65");  add(0x43C37D, 6, 4, S(0xBA), "box1 B 0xBA");
  add(0x43C393, 1, 4, S(0x118), "box2/5 B 0x118"); add(0x43C398, 1, 4, S(0x1CE), "box R-col L"); add(0x43C39D, 1, 4, S(0x231), "box R-col R");
  add(0x43C3A2, 6, 4, S(0xC3), "box2 T 0xC3");     add(0x43C3C4, 6, 4, S(0x5C), "box3 B 0x5C");  add(0x43C3D4, 6, 4, S(0x65), "box4 T 0x65");
  add(0x43C3E4, 6, 4, S(0xBA), "box4 B 0xBA");     add(0x43C3FC, 6, 4, S(0xC3), "box5 T 0xC3");
  // --- builder: console overlay insets ---
  add(0x43C44E, 2, 1, S(4), "slotStrip L+4");
  add(0x43C495, 2, 1, S(3), "flash L+3");  add(0x43C49A, 1, 4, NEG(3), "flash R/B-3");  add(0x43C4A1, 2, 1, S(3), "flash T+3");
  add(0x43C4E5, 2, 1, S(4), "title L+4");  add(0x43C4EA, 1, 4, NEG(4), "title R/B-4");  add(0x43C4F1, 2, 1, S(4), "title T+4");
  add(0x43C51C, 2, 1, S(4), "rcont L+4");  add(0x43C51F, 2, 1, S(4), "rcont T+4");      add(0x43C522, 2, 1, S(4), "rcont R-4");  add(0x43C527, 2, 1, S(4), "rcont B-4");
  add(0x43C52A, 2, 1, S(7, 4), "presets L+3"); add(0x43C530, 2, 1, S(7, 4), "presets T+3"); add(0x43C536, 2, 1, S(7, 4), "presets R-3"); add(0x43C542, 2, 1, S(7, 4), "presets B-3");
  add(0x43C556, 2, 1, S(0x15), "presets title h 0x15"); add(0x43C56F, 2, 1, S(0x18, 0x15), "presets area T +3");
  // --- builder: preset buttons + arrows ---
  add(0x43C770, 2, 1, S(3), "preset w +3"); add(0x43C78E, 2, 1, S(3), "preset w -3"); add(0x43C7BA, 1, 1, S(0x15), "preset h 0x15");
  add(0x43C824, 2, 1, S(0x17), "preset pitch 0x17"); add(0x43C841, 3, 1, S(3), "preset col +3");
  add(0x43C879, 2, 1, S(8), "left arrow +8");
  // --- builder: modal button rows ---
  add(0x43C8D3, 2, 1, S(0x1B), "btn x0 +0x1B"); add(0x43C8DF, 2, 1, S(0x20), "btn R -0x20"); add(0x43C8E2, 2, 1, S(0x1B), "btn R -0x1B");
  add(0x43C8EA, 2, 1, S(0x14), "btn B -0x14");  add(0x43C8ED, 2, 1, S(3), "btn cell +3");  add(0x43C900, 2, 1, FLOORH(0x14), "btn h 0x14 (floor)", "neg");
  add(0x43C911, 3, 1, NEG(3), "btn cell -3");   add(0x43C927, 2, 1, S(3), "btn pitch +3"); add(0x43C972, 2, 1, NEG(6), "upper row -6");
  // v14t (user 1600 shot 022448: upper-row channels 5 px vs lower 7): the upper row's pitch is recomputed AFTER
  // the loop from the advanced cursors, (R-x0)+3 for PROTO and (x0-R)-3 for RETIRE ALL; these two +-3 were
  // still native -> upper pitch short by s(3)-3. LAW dw_button_rows (scaling_laws): every row shares pitch = cell.
  add(0x43C9B2, 2, 1, S(3), "PROTO pitch +3");  add(0x43CA27, 2, 1, S(3), "RETIRE ALL pitch -3 (sub)");
  // --- builder: window ---
  add(0x43C6A3, 1, 4, S(600), "window h 600");  add(0x43C6CA, 0, 0, CEILW(623), "window w 623 (MOV imm)", "movimm_ecx");
  add(0x43C70F, 2, 1, S(0x20), "window x nudge 0x20");
  // --- painters: title box / master / part boxes / abil ---
  add(0x434708, 1, 1, S(18), "title font 18"); add(0x434732, 1, 4, S(3), "title inset 3");
  add(0x437A26, 1, 4, S(3), "master presets-title inset 3");
  add(0x437B65, 1, 4, S(3), "master union-frame inset 3 (D4)");
  add(0x434CC5, 1, 4, NEG(5), "chassis icon -5"); add(0x435066, 1, 4, NEG(5), "weapon icon -5"); add(0x435508, 1, 4, NEG(5), "armor icon -5"); add(0x4359A8, 1, 4, NEG(5), "reactor icon -5");
  add(0x434E72, 2, 1, S(3), "chassis stats +3"); add(0x43528E, 2, 1, S(3), "weapon stats +3"); add(0x43570A, 2, 1, S(3), "armor stats +3");
  add(0x435BAF, 2, 1, S(2), "abil1 title y+2"); add(0x435BC0, 1, 4, S(5), "abil1 title x+-5"); add(0x435E5F, 2, 1, S(2), "abil2 title y+2"); add(0x435E70, 1, 4, S(5), "abil2 title x+-5");
  // --- painters: preview ---
  add(0x43621C, 1, 4, S(0xBB), "preview veh x 0xBB"); add(0x436246, 1, 4, S(0x8C), "preview veh y 0x8C"); add(0x436274, 1, 1, VEH(14), "preview veh size 0xE");
  add(0x4363EC, 1, 4, S(0x2D), "preview name inset 0x2D"); add(0x437268, 2, 1, S(0x14), "DATA x +0x14");
  // --- Caviar zooms (push imm32 float) ---
  for (const [a, z, l] of [[0x434D0A, 0.05, "chassis"], [0x435099, 0.15, "weapon a"], [0x4350F6, 0.15, "weapon b"], [0x435101, 0.06, "weapon c"], [0x435108, 0.08, "weapon d"],
                           [0x435557, 0.07, "armor"], [0x4359FA, 0.2, "reactor"], [0x4362BA, 0.14, "preview"],
                           [0x432A4B, 0.06, "picker chassis"], [0x433240, 0.1, "picker armor"], [0x4335CC, 0.2, "picker reactor"]])
    { /* v9: Caviar zooms stay NATIVE - the target is a hard 256x256; enlargement happens at the composite (Z') */ }
  // --- painters: slot strip ---
  add(0x43D5B3, 2, 1, S(3), "slot R-3"); add(0x43D5B6, 2, 1, S(3), "slot L+3"); add(0x43D5C2, 2, 1, S(3), "slot B-3"); add(0x43D5CD, 2, 1, S(2), "slot cellW +2");
  add(0x43D5E0, 2, 1, S(3), "slot T+3"); add(0x43D5F4, 1, 1, S(10), "slot font 10"); add(0x43D739, 1, 4, S(2), "slot inset 2 (hover/normal)");
  // D7': 0x43D726 `mov edi,2; mov eax,edi; jmp 0x43d741` (9 B) -> `push s2; pop edi; push 2; pop eax; jmp 0x43d741; nop`
  P.push({ addr: 0x43D726, kind: "raw", label: "slot selected: state 2 + inset s(2) split", nat: [0xBF, 2, 0, 0, 0, 0x8B, 0xC7, 0xEB, 0x12],
           fn: () => [0x6A, s(2) & 0xFF, 0x5F, 0x6A, 0x02, 0x58, 0xEB, 0x13, 0x90] });
  add(0x43D8E1, 2, 1, S(12), "slot icon y+0xC"); add(0x43D8EA, 2, 1, S(15), "slot icon x+0xF"); add(0x43DAEF, 2, 1, S(3), "slot name x+3"); add(0x43DAF2, 2, 1, S(3), "slot name r-3");
  add(0x43DCBE, 2, 1, S(2), "slot pitch +2 (unit)");   add(0x43DCCC, 1, 4, S(2), "slot restore 2 (unit)");     // D7
  add(0x43D880, 2, 1, S(2), "slot pitch +2 (empty)");  add(0x43D890, 1, 4, S(2), "slot restore 2 (empty)");    // D7
  add(0x43D5EB, 3, 1, NEG(2), "slot cellW -2");                                                             // D7: cellW = (span+s2)/10 - s2
  // --- painters: draw_flash ---
  add(0x43DE9A, 1, 4, S(3), "flash inset a"); add(0x43DED2, 1, 4, S(3), "flash inset b"); add(0x43DF55, 1, 1, S(12), "flash font 12"); add(0x43DF68, 1, 1, S(12), "flash font 12b");
  // --- v12 part picker (stack PartPicker; exec 0x433F70, draw_cell 0x433D60, on_click 0x433820) ---
  add(0x43406F, 1, 1, S(10), "picker font 10"); add(0x434081, 1, 1, S(12), "picker font 12 bold");
  add(0x433E37, 1, 4, S(3), "picker cell inset 3"); add(0x434271, 3, 4, S(0x17), "picker frame L 0x17");
  P.push({ addr: 0x433D84, kind: "raw", label: "picker cell rect law -> stub", nat: [0x8B, 0x8E, 0x6C, 0x2B, 0x00, 0x00], fn: () => jmpRel(0x433D84, stubs.cell, 6) });
  P.push({ addr: 0x434266, kind: "raw", label: "picker frame R inset s(55) -> stub", nat: [0x83, 0xC7, 0xC9, 0x51, 0x52],
           fn: () => { for (const o of FRAME_OFFS.S55) stubs.frame.add(o).writeU32(s(0x37)); return jmpRel(0x434266, stubs.frame, 5); } });
  P.push({ addr: 0x66B2FC, kind: "raw", label: "picker vtbl+0x44 on_click -> descale stub", nat: [0x20, 0x38, 0x43, 0x00], fn: () => le32(stubs.click) });
  add(0x43DF87, 2, 1, S(3), "flash half +3"); add(0x43DF95, 3, 1, NEG(3), "flash half -3"); add(0x43DFD4, 2, 1, NEG(0x25), "flash veh y-0x25"); add(0x43DFDD, 2, 1, NEG(0x32), "flash veh x-0x32");
  add(0x43E001, 2, 1, S(3), "flash text +3 a"); add(0x43E014, 2, 1, S(3), "flash text +3 b"); add(0x43E10B, 1, 4, S(2), "flash name +2"); add(0x43E279, 2, 1, S(3), "flash stats +3");

  let patched = false;
  function applyPatches() {
    if (patched) return;
    patched = true;
    let n = 0, skip = 0;
    for (const p of P) {
      try {
        if (p.kind === "raw") {
          const cur = Array.from(new Uint8Array(VA(p.addr).readByteArray(p.nat.length)));
          if (cur.join() !== p.nat.join()) { skip++; log("PATCH SKIP raw bytes mismatch " + p.label + " @" + hex(p.addr) + " read " + cur.map(b => b.toString(16)).join(" ")); continue; }
          const v = p.fn();
          Memory.patchCode(VA(p.addr), v.length, code => code.writeByteArray(v));
          log("PATCH " + p.label + " @" + hex(p.addr) + " -> " + v.map(b => b.toString(16).padStart(2, "0")).join(" ")); n++; continue;
        }
        if (p.kind === "movimm_ecx") {
          const b = new Uint8Array(VA(p.addr).readByteArray(6));
          if (!(b[0] === 0x8B && b[1] === 0x8E && b[2] === 0xEC && b[3] === 0x3C)) { skip++; log("PATCH SKIP movimm bytes @" + hex(p.addr)); continue; }
          const v = p.fn();
          Memory.patchCode(VA(p.addr), 6, code => { code.writeU8(0xB9); code.add(1).writeS32(v); code.add(5).writeU8(0x90); });
          log("PATCH " + p.label + " @" + hex(p.addr) + " -> mov ecx," + v); n++; continue;
        }
        if (p.kind === "float") {
          const v = p.fn();
          const of = VA(p.addr).add(p.off).readFloat();
          if (Math.abs(of - p.fn.nat) > 1e-6) { skip++; log("PATCH SKIP float mismatch " + p.label + " @" + hex(p.addr) + " read " + of); continue; }
          Memory.patchCode(VA(p.addr), p.off + 4, code => code.add(p.off).writeFloat(v));
          n++; continue;
        }
        let v = p.fn();
        let expect = p.fn.nat;
        if (p.kind === "neg") { v = -v; expect = -expect; }
        const orig = p.w === 1 ? VA(p.addr).add(p.off).readS8() : VA(p.addr).add(p.off).readS32();
        if (orig !== expect) { skip++; log("PATCH SKIP native mismatch " + p.label + " @" + hex(p.addr) + "+" + p.off + " read " + orig + " expect " + expect); continue; }
        if (p.w === 1 && (v > 127 || v < -128)) { skip++; log("PATCH SKIP imm8 overflow " + p.label + " @" + hex(p.addr) + " -> " + v); continue; }
        Memory.patchCode(VA(p.addr), p.off + p.w, code => { if (p.w === 1) code.add(p.off).writeS8(v); else code.add(p.off).writeS32(v); });
        n++;
      } catch (e) { skip++; log("PATCH ERROR " + p.label + " @" + hex(p.addr) + ": " + e); }
    }
    log("immediates patched: " + n + "/" + P.length + (skip ? " (SKIPPED " + skip + ")" : "") + " g=" + g +
        " s(3)=" + s(3) + " s(4)=" + s(4) + " s(20)=" + s(20) + " floor20=" + SL.scaleFloor(20, g) + " W'=" + Math.ceil(623 * g / 16) + " s(600)=" + s(600));    try { verifyStubPages("first-exec"); } catch (e) { log("STUBCHK err " + e); }
  }

  // rails: E8 rel32 redirects (verify the live targets first — PRACX stomp check)
  let railsDone = false;
  function applyRails() {
    if (railsDone) return;
    railsDone = true;
    for (const [va, want, tgt, name] of [[0x43D1BE, A_SLIDESHOW, T_RAILSHOW, "slide_show->railshow"], [0x43D1FA, A_SLIDEHIDE, T_RAILHIDE, "slide_hide->railhide"]]) {
      const b = new Uint8Array(VA(va).readByteArray(5));
      const cur = (va + 5 + ((b[1] | (b[2] << 8) | (b[3] << 16) | (b[4] << 24)) | 0)) >>> 0;
      if (b[0] !== 0xE8 || cur !== want) { log("RAIL SKIP @" + hex(va) + " bytes=" + Array.from(b).map(x => x.toString(16)).join(" ") + " cur=" + hex(cur)); continue; }
      Memory.patchCode(VA(va), 5, code => code.add(1).writeS32(tgt - (va + 5)));
      log("RAIL " + name + " @" + hex(va) + " -> " + hex(tgt));
    }
  }
  // D4: the union frame's Buffer_box_sprite site (canvas dest) -> thunk_box_thick_hollow_flat
  // (SE v18 recipe; the thunk gates g<=16 -> native). Verified live E8 -> 0x5E2DD3 first.
  const T_HOLLOW_FLAT = PCAVE2 + 0x140, A_BOX_SPRITE = 0x5E2DD3;
  let frameDone = false;
  function applyFrameRedirect() {
    if (frameDone) return;
    // v14r LAW bandmap_rect_from_halfopen: the picker's Buffer_box_sprite rects are HALF-OPEN (the empty-cell
    // Buffer_tile_2 fills W=R-L, set_clip culls col R) but thunk_box_thick_hollow_flat band-maps an INCLUSIVE
    // footprint -> 264x228 frames for 263x227 law rects, and the tile repaint after a scroll leaves col R / row B
    // of stroke behind (weapon picker "phantom frame strokes", shot 015255 vs pristine WeaponBottom.png).
    // Both sites now E8 -> a stub that hands the thunk a scratch COPY of the rect with R-1/B-1 (Unicorn-checked;
    // template from scratchpad: 54 B, S fixups @8/45 (+0), 17 (+4), 27 (+8), 37 (+12), jmp rel32 @50).
    const bmScratch = Memory.alloc(16); RETAINED.push(bmScratch); const S = bmScratch.toInt32();
    const bmCode = [0x8b, 0x44, 0x24, 0x04, 0x8b, 0x10, 0x89, 0x15, 0, 0, 0, 0, 0x8b, 0x50, 0x04, 0x89, 0x15, 0, 0, 0, 0, 0x8b, 0x50, 0x08, 0x4a, 0x89, 0x15, 0, 0, 0, 0, 0x8b, 0x50, 0x0c, 0x4a, 0x89, 0x15, 0, 0, 0, 0, 0xc7, 0x44, 0x24, 0x04, 0, 0, 0, 0, 0xe9, 0, 0, 0, 0];
    const bmStub = allocStub(bmCode, { S0: [8, 45], S4: [17], S8: [27], S12: [37] }, { S0: S, S4: S + 4, S8: S + 8, S12: S + 12 });
    Memory.patchCode(bmStub.add(50), 4, c => c.writeS32(T_HOLLOW_FLAT - (bmStub.toInt32() + 54)));
    E_STUBS.push({ nm: "BM", a: 0x433E2C, p: bmStub, code: Array.from(new Uint8Array(bmStub.readByteArray(54))) });
    for (const va of [0x433E2C, 0x434285]) {                                        // v12: picker cell + container frames
      const b = new Uint8Array(VA(va).readByteArray(5));
      const cur = (va + 5 + ((b[1] | (b[2] << 8) | (b[3] << 16) | (b[4] << 24)) | 0)) >>> 0;
      if (b[0] !== 0xE8 || cur !== A_BOX_SPRITE) { log("FRAME SKIP picker site @" + hex(va) + " bytes=" + Array.from(b).map(x => x.toString(16)).join(" ") + " cur=" + hex(cur)); continue; }
      Memory.patchCode(VA(va), 5, code => code.add(1).writeS32(bmStub.toInt32() - (va + 5)));
      log("FRAME picker box_sprite @" + hex(va) + " -> R-1/B-1 stub " + bmStub + " -> thunk_box_thick_hollow_flat " + hex(T_HOLLOW_FLAT));
    }
    frameDone = true;
    const va = 0x437B89;
    const b = new Uint8Array(VA(va).readByteArray(5));
    const cur = (va + 5 + ((b[1] | (b[2] << 8) | (b[3] << 16) | (b[4] << 24)) | 0)) >>> 0;
    if (b[0] !== 0xE8 || cur !== A_BOX_SPRITE) { log("FRAME SKIP @" + hex(va) + " bytes=" + Array.from(b).map(x => x.toString(16)).join(" ") + " cur=" + hex(cur)); return; }
    Memory.patchCode(VA(va), 5, code => code.add(1).writeS32(T_HOLLOW_FLAT - (va + 5)));
    log("FRAME union-frame box_sprite @" + hex(va) + " -> thunk_box_thick_hollow_flat " + hex(T_HOLLOW_FLAT));
  }
  // v2: FlatButton 2D-zoom bracket via thunk_btn_gate_pre's HIT RANGE (the SE/Council bake
  // form), NOT the g_faction_active flag: the flag forced YES for every labelled button
  // incl. MENU/COMMLINK, whose faces thunk_hudmenu_sd2 already draws device-scaled ->
  // double-enlarge banding on the HUD (user report 2026-08-28; = the Council MISS lesson).
  // The v3 prefix's first range (SE statics [0x8AC290,0x8C4DF4) @pcave2+0x16DA2/+0x16DAA)
  // is retargeted at DesignWin's 25 FlatButtons while the modal runs, restored on close.
  const GATE_LO = PCAVE2 + 0x16DA0 + 2, GATE_HI = PCAVE2 + 0x16DA0 + 10;
  const SE_LO = 0x8AC290, SE_HI = 0x8C4DF4;
  const DW_LO = G_OBJ + 0xCEC, DW_HI = G_OBJ + 0xCEC + 0x19 * 0xB4C;
  function setGateRange(on) {
    const lo = VA(GATE_LO).readU32(), hi = VA(GATE_HI).readU32();
    const [wantLo, wantHi] = on ? [DW_LO, DW_HI] : [SE_LO, SE_HI];
    const [expLo, expHi] = on ? [SE_LO, SE_HI] : [DW_LO, DW_HI];
    if (lo === wantLo && hi === wantHi) return;
    if (lo !== expLo || hi !== expHi) { log("GATE range unexpected " + hex(lo) + ".." + hex(hi) + " — untouched"); return; }
    const lb = VA(GATE_LO).sub(2).readU8(), hb = VA(GATE_HI).sub(2).readU8();
    if (lb !== 0x81 || hb !== 0x81) { log("GATE opcode unexpected — untouched"); return; }
    Memory.patchCode(VA(GATE_LO), 4, code => code.writeU32(wantLo));
    Memory.patchCode(VA(GATE_HI), 4, code => code.writeU32(wantHi));
    log("GATE range " + (on ? "-> DesignWin buttons " : "-> restored SE ") + hex(wantLo) + ".." + hex(wantHi));
  }

  // ---------------------------------------------------------------------------
  // W2: backdrop re-render at device density (pcx Buffer + window canvas)
  // ---------------------------------------------------------------------------
  function centreMap(dst, src) { const m = new Int32Array(dst); for (let i = 0; i < dst; i++) m[i] = Math.min(src - 1, Math.floor((i + 0.5) * src / dst)); return m; }
  function bufInfo(buf) {
    const w = safeS32(buf.add(0x80)); let h = safeS32(buf.add(0x84)); if (h < 0) h = -h;
    const data = buf.add(0x54).readPointer();
    const p2 = safeS32(buf.add(0x4A8));
    const pitch = (p2 >= w && p2 <= w + 8) ? p2 : ((w + 3) & ~3);
    return { w, h, data, pitch, p2 };
  }
  function renderBackdrop(obj) {
    const pcx = obj.add(0x13C6C);
    const si = bufInfo(pcx);
    if (si.w !== 623 || si.h !== 368 || si.data.isNull()) { log("BACKDROP: pcx not native (" + si.w + "x" + si.h + ") — skipped"); return; }
    const sw = si.w, sh = si.h, sp = si.pitch;
    const src = new Uint8Array(si.data.readByteArray(sp * sh));
    const W = Math.ceil(623 * g / 16), H = s(368);
    // D1/D2: MEASURE the plane. Dither families = indices covering >= 2% of the plane whose max
    // vertical run is <= 2 (census: black 65, navy 196, chrome 198). Strokes = rows/cols carrying
    // a run >= 60 of non-family, non-key pixels (census rows 0,4,94,98,188,192,282; cols
    // 23,27,131,135,455,459,563,567). Both are logged so a drift from the census is visible.
    const cnt = new Int32Array(256), vrun = new Int32Array(256);
    for (let x = 0; x < sw; x++) { let prev = -1, run = 0; for (let y = 0; y < sh; y++) { const v = src[y * sp + x]; cnt[v]++; run = (v === prev) ? run + 1 : 1; prev = v; if (run > vrun[v]) vrun[v] = run; } }
    const FAM = new Uint8Array(256), famList = [];
    for (let v = 0; v < 256; v++) if (v !== KEY && cnt[v] >= 0.02 * sw * sh && vrun[v] <= 2) { FAM[v] = 1; famList.push(v + "(" + pal(v).join(",") + ")x" + cnt[v] + "/vr" + vrun[v]); }
    // D6: PHASE VARIANTS (see header) — one-parity, family-sandwiched non-family indices.
    const cntE = new Int32Array(256), cntS = new Int32Array(256);
    for (let y = 0; y < sh; y++) for (let x = 0; x < sw; x++) {
      const v = src[y * sp + x]; if (v === KEY || FAM[v]) continue;
      if ((y & 1) === 0) cntE[v]++;
      if (y > 0 && y < sh - 1) { const u = src[(y - 1) * sp + x], d = src[(y + 1) * sp + x]; if (u === d && FAM[u]) cntS[v]++; }
    }
    const VAR = new Uint8Array(256), varList = [];
    for (let v = 0; v < 256; v++)
      if (v !== KEY && !FAM[v] && cnt[v] >= 40 && Math.max(cntE[v], cnt[v] - cntE[v]) >= 0.95 * cnt[v] && cntS[v] >= 0.8 * cnt[v]) {
        VAR[v] = 1; varList.push(v + "(" + pal(v).join(",") + ")x" + cnt[v] + (cntE[v] * 2 >= cnt[v] ? "/even" : "/odd"));
      }
    const FL = v => v >= 0 && (FAM[v] === 1 || VAR[v] === 1);
    const isInk = v => v !== KEY && !FAM[v] && !VAR[v];
    const lineRows = [], lineCols = [];
    for (let y = 0; y < sh; y++) { let run = 0, best = 0; for (let x = 0; x < sw; x++) { run = isInk(src[y * sp + x]) ? run + 1 : 0; if (run > best) best = run; } if (best >= 60) lineRows.push(y); }
    for (let x = 0; x < sw; x++) { let run = 0, best = 0; for (let y = 0; y < sh; y++) { run = isInk(src[y * sp + x]) ? run + 1 : 0; if (run > best) best = run; } if (best >= 60) lineCols.push(x); }
    const xmL = SL.lineAxisMap(sw, W, lineCols, g), ymL = SL.lineAxisMap(sh, H, lineRows, g);
    const xm = xmL || centreMap(W, sw), ym = ymL || centreMap(H, sh);
    log("BACKDROP measure: families " + famList.join(" ") + " | stroke rows " + lineRows.join(",") + " | stroke cols " + lineCols.join(",") +
        " | variants " + (varList.join(" ") || "none") + " | K=" + SL.strokeWidth(g) + " maps " + (xmL ? "line-pinned" : "NN-FALLBACK") + "/" + (ymL ? "line-pinned" : "NN-FALLBACK"));
    // classify: a family pixel with a DIFFERENT family member directly above or below is a pair
    // member -> [evenRowColour, oddRowColour] by native parity. (v1's up==dn&&up2==v test could
    // never classify a row next to a stroke: 13,183 px went out NN = the disc beads, audit #4-#7.)
    const isPair = new Uint8Array(sw * sh), evc = new Uint8Array(sw * sh), odc = new Uint8Array(sw * sh);
    let npair = 0, nfamMiss = 0;
    for (let y = 0; y < sh; y++) for (let x = 0; x < sw; x++) {
      const v = src[y * sp + x];
      if (!FL(v)) continue;
      const up = y > 0 ? src[(y - 1) * sp + x] : -1, dn = y < sh - 1 ? src[(y + 1) * sp + x] : -1;
      const mate = (FL(up) && up !== v) ? up : ((FL(dn) && dn !== v) ? dn : -1);       // D6: variants pair like family
      if (mate < 0) { nfamMiss++; continue; }
      const i = y * sw + x;
      isPair[i] = 1; npair++;
      if ((y & 1) === 0) { evc[i] = v; odc[i] = mate; } else { evc[i] = mate; odc[i] = v; }
    }
    const out = new Uint8Array(W * H);
    let nregen = 0;
    for (let yd = 0; yd < H; yd++) {
      const ys = ym[yd], top = SL.stripeTop(yd, g, 0), o = yd * W;
      for (let xd = 0; xd < W; xd++) {
        const xs = xm[xd], i = ys * sw + xs;
        if (isPair[i]) { out[o + xd] = top ? evc[i] : odc[i]; nregen++; }
        else out[o + xd] = src[ys * sp + xs];
      }
    }
    // (1) window canvas: image rows; rows below the image are LEFT AS THE ENGINE FILLED THEM
    //     (vanilla's canvas is taller than the pcx too — whatever GraphicWin_init put there is the law)
    const ci = bufInfo(obj.add(0x444));
    if (ci.data.isNull() || ci.w <= 0 || ci.h <= 0) { log("BACKDROP: canvas unreadable"); return; }
    const cw = Math.min(ci.w, W);
    let fillHist = {};
    for (let y = 0; y < ci.h; y++) {
      if (y < H) ci.data.add(y * ci.pitch).writeByteArray(out.subarray(y * W, y * W + cw));
      else if (y === H || y === ci.h - 1) { const row = new Uint8Array(ci.data.add(y * ci.pitch).readByteArray(ci.w)); for (const v of row) fillHist[v] = (fillHist[v] || 0) + 1; }
    }
    // (2) pcx Buffer -> device size at the FULL canvas height: painters restore box backgrounds
    //     from it with Buffer_copy_2 at scaled rects (bottom button row / union frame reach below
    //     the image rows), so it must cover every row the canvas has; rows >= H copy the canvas's own fill.
    const HP = Math.max(H, ci.h);
    Buffer_resize(pcx, W, HP);
    const di = bufInfo(pcx);
    if (di.w !== W || di.h !== HP || di.data.isNull()) { log("BACKDROP: pcx resize failed (" + di.w + "x" + di.h + ")"); return; }
    for (let y = 0; y < HP; y++) {
      if (y < H) di.data.add(y * di.pitch).writeByteArray(out.subarray(y * W, (y + 1) * W));
      else if (y < ci.h) di.data.add(y * di.pitch).writeByteArray(ci.data.add(y * ci.pitch).readByteArray(cw));
    }
    log("BACKDROP: pcx 623x368 -> image " + W + "x" + H + ", pcx buf " + di.w + "x" + di.h + " pitch " + di.pitch + "; canvas " + ci.w + "x" + ci.h +
        " pitch " + ci.pitch + " engine fill below image: " + JSON.stringify(fillHist) + "; pair px native=" + npair + " (family px unpaired=" + nfamMiss + ") regen=" + nregen + " P=" + SL.stripePeriod(g, 0));
  }

  // ---------------------------------------------------------------------------
  // D3: device-density P-law stripes for the 25 DesignWin FlatButton faces (skill
  // scaling-frames §6/§7 + the §7b per-draw pair rule; SE v17/v19/v20 recipe). Host = the
  // item-draw slot entry 0x404220 (vtbl+0x14 default stub `xor eax,eax; ret 0xC`, called per
  // FlatButton draw after the face is composed, before the label; args [esp+4]=btn,
  // [esp+0xC]=id). Filtered on btn in [DW_LO, DW_HI). Pair detected per draw from one face
  // column; every pair pixel rewritten to SL.stripeTop for its canvas row; the state-sprite
  // ring pinned to K; trailing key rows overdrawn. A 120 ms watcher re-stripes any DW canvas
  // that changed outside the hook.
  // ---------------------------------------------------------------------------
  const A_ITEMDRAW = 0x404220;
  function detectPair(u8, stride, H, x) {
    const cnt = new Map();
    for (let y = 0; y < H; y++) { const v = u8[y * stride + x]; cnt.set(v, (cnt.get(v) || 0) + 1); }
    const top2 = [...cnt.entries()].sort((p, q) => q[1] - p[1]).slice(0, 2);
    if (top2.length < 2) return null;
    let a = top2[0][0], b = top2[1][0];
    if (a === KEY || b === KEY) return null;
    { const t = SL.pairTop(a, b, pal); if (t !== a) { b = a; a = t; } }   // v14g: canonical TOP member (law pair_top), never the histogram majority
    if (top2[0][1] + top2[1][1] < 0.6 * H) return null;
    let run = 0, prev = -1, first = -1;                       // alternation: runs <= 3 (1px, or NN-zoomed)
    for (let y = 0; y < H; y++) {
      const v = u8[y * stride + x];
      if (v !== a && v !== b) { prev = -1; run = 0; continue; }
      if (first < 0) first = v;
      if (v === prev) { if (++run > 3) return null; } else { prev = v; run = 1; }
    }
    return [a, b];                                            // v14g: [top, mate] by law pair_top (was: first-seen member = phase-dependent)
  }
  let lastOverdraw = 0;
  const pitchSeen = new Set();
  function restripeBuffer(buf, colFrac) {
    const bi = bufInfo(buf);
    const pk = bi.w + "x" + bi.h;
    if (!pitchSeen.has(pk)) { pitchSeen.add(pk); log("BUFPITCH btn canvas " + pk + " +0x4A8=" + bi.p2 + " used=" + bi.pitch); }
    const data = bi.data, stride = bi.pitch, W = bi.w, H = bi.h;
    if (data.isNull() || W <= 0 || H <= 0 || stride < W) return null;
    const u8 = new Uint8Array(data.readByteArray(stride * H));
    const pair = detectPair(u8, stride, H, Math.max(1, Math.min(W - 2, Math.floor(W * colFrac))));
    if (!pair) return null;
    const [top, bot] = pair;
    let kb = 0;
    const rowKey = y => { let n = 0; for (let x = 4; x < W - 4; x++) if (u8[y * stride + x] === KEY) n++; return n >= 0.9 * (W - 8); };
    while (kb < 2 && H - 1 - kb > 0 && rowKey(H - 1 - kb)) kb++;
    if (kb) { const srcRow = H - 1 - kb; for (let y = H - kb; y < H; y++) for (let x = 0; x < W; x++) u8[y * stride + x] = u8[srcRow * stride + x]; }
    lastOverdraw = kb;
    for (let y = 0; y < H; y++) {
      const c = SL.stripeTop(y, g, 0) ? top : bot, o = y * stride;
      for (let x = 0; x < W; x++) { const v = u8[o + x]; if (v === top || v === bot) u8[o + x] = c; }
    }
    const ring = pinRing(u8, stride, W, H, top, bot);
    data.writeByteArray(u8.buffer);
    return ring ? [top, bot, ring] : pair;
  }
  function pinRing(u8, stride, W, H, top, bot) {
    const K = SL.strokeWidth(g);
    const isPair = v => v === top || v === bot;
    const m = 8;
    if (W < 4 * m || H < 4 * m) return null;
    const rowRing = y => { let n = 0; for (let x = m; x < W - m; x++) if (!isPair(u8[y * stride + x])) n++; return n >= 0.9 * (W - 2 * m); };
    const colRing = x => { let n = 0; for (let y = m; y < H - m; y++) if (!isPair(u8[y * stride + x])) n++; return n >= 0.9 * (H - 2 * m); };
    let dT = 0, dB = 0, dL = 0, dR = 0;
    while (dT < 8 && rowRing(dT)) dT++;
    while (dB < 8 && rowRing(H - 1 - dB)) dB++;
    while (dL < 8 && colRing(dL)) dL++;
    while (dR < 8 && colRing(W - 1 - dR)) dR++;
    if (!dT && !dB && !dL && !dR) return null;
    const stripe = y => SL.stripeTop(y, g, 0) ? top : bot;
    for (let y = K; y < dT; y++) for (let x = K; x < W - K; x++) u8[y * stride + x] = stripe(y);
    for (let y = H - dB; y < H - K; y++) for (let x = K; x < W - K; x++) u8[y * stride + x] = stripe(y);
    for (let x = K; x < dL; x++) for (let y = K; y < H - K; y++) u8[y * stride + x] = stripe(y);
    for (let x = W - dR; x < W - K; x++) for (let y = K; y < H - K; y++) u8[y * stride + x] = stripe(y);
    if (dT && dT < K) for (let y = dT; y < K; y++) for (let x = 0; x < W; x++) u8[y * stride + x] = u8[(dT - 1) * stride + x];
    if (dB && dB < K) for (let y = H - K; y < H - dB; y++) for (let x = 0; x < W; x++) u8[y * stride + x] = u8[(H - dB) * stride + x];
    if (dL && dL < K) for (let x = dL; x < K; x++) for (let y = 0; y < H; y++) u8[y * stride + x] = u8[y * stride + dL - 1];
    if (dR && dR < K) for (let x = W - K; x < W - dR; x++) for (let y = 0; y < H; y++) u8[y * stride + x] = u8[y * stride + W - dR];
    return [dT, dB, dL, dR, K];
  }
  const btnStripeSeen = {}, btnRingSeen = {}, hookSig = {};
  let dwActive = false, watchLogs = 0, pickerCanvas = 0;   // v12: the live PartPicker canvas Buffer (0 = none)
  function canvasSig(buf) {
    try {
      const bi = bufInfo(buf);
      if (bi.data.isNull() || bi.w <= 0 || bi.h < 4) return null;
      let h = 0;
      for (const y of [0, 1, bi.h - 2, bi.h - 1]) { const r = new Uint8Array(bi.data.add(y * bi.pitch).readByteArray(bi.w)); for (let x = 0; x < bi.w; x++) h = (h * 31 + r[x]) | 0; }
      return h;
    } catch (e) { return null; }
  }
  function btnIndexOf(btn) {
    const a = btn.sub(VA(G_OBJ)).toInt32() - 0xCEC;
    return (a >= 0 && a < 0x19 * 0xB4C && a % 0xB4C === 0) ? a / 0xB4C : -1;
  }
  Interceptor.attach(VA(A_ITEMDRAW), {
    onEnter() {
      if (g <= 16 || !dwActive) return;
      try {
        const sp = this.context.esp;
        const btn = sp.add(4).readPointer(), id = sp.add(0xC).readS32();
        const bi = btnIndexOf(btn);
        if (bi < 0) return;
        const cv = btn.add(0x444);
        const pair = restripeBuffer(cv, 0.25);
        const n = (btnStripeSeen[bi] = (btnStripeSeen[bi] || 0) + 1);
        const ringed = pair && pair.length === 3;
        if (n <= 2 || n % 50 === 0 || (ringed && (btnRingSeen[bi] = (btnRingSeen[bi] || 0) + 1) <= 2))
          log("btn#" + bi + " (id " + id + ") draw " + n + " restripe " + (pair ? "pair " + pair[0] + "(" + pal(pair[0]).join(",") + ")/" + pair[1] + "(" + pal(pair[1]).join(",") + ")" : "SKIP (no pair)") +
              " P=" + SL.stripePeriod(g, 0) + (lastOverdraw ? " overdrew " + lastOverdraw + " key row(s)" : "") +
              (ringed ? " RING T/B/L/R=" + pair[2].slice(0, 4).join("/") + " -> K=" + pair[2][4] : ""));
        hookSig[bi] = canvasSig(cv);
        if (n <= 2) heapCheck("btn#" + bi + " draw " + n, true);
      } catch (e) { log("restripe err " + e); }
    }
  });
  const WATCHER = false;   // v7 control: OFF
  setInterval(() => {
    if (!WATCHER) return;
    if (g <= 16 || !dwActive) return;
    try {
      for (let i = 0; i < 0x19; i++) {
        const cv = VA(G_OBJ).add(0xCEC + i * 0xB4C + 0x444);
        let sig;
        try { if (cv.add(0x54).readPointer().isNull()) continue; sig = canvasSig(cv); } catch (e) { continue; }
        if (sig === null || sig === hookSig[i]) continue;
        const pair = restripeBuffer(cv, 0.25);
        if (watchLogs < 12) { watchLogs++; log("WATCH btn#" + i + " canvas changed outside the hook -> restripe " + (pair ? pair[0] + "/" + pair[1] : "SKIP (no pair)")); }
        hookSig[i] = canvasSig(cv);
      }
    } catch (e) { log("WATCH error: " + e); }
  }, 120);

  // ---------------------------------------------------------------------------
  // dumps / render trace (measurement, zero-Interceptor)
  // ---------------------------------------------------------------------------
  const RECTS = [["gw.screen+13C", 0x13c], ["gw.local+474", 0x474], ["titleBox", 0xA4C], ["presetsTitle", 0xA6C], ["presetsArea", 0xA7C], ["rightContainer", 0xA8C],
    ["preview", 0xA9C], ["box0", 0xAAC], ["box1", 0xABC], ["box2", 0xACC], ["box3", 0xADC], ["box4", 0xAEC], ["box5", 0xAFC], ["slotStrip", 0xB0C], ["flashBox", 0xB1C],
    ["btn0.RETIRE", 0xB4C], ["btn1.APPLY", 0xB5C], ["btn4.Done", 0xB8C], ["btn5.Rename", 0xB9C], ["btn8.Cancel", 0xBCC], ["leftArrow", 0xCBC], ["rightArrow", 0xCCC]];
  function dump(obj, tag) {
    log("---- DUMP (" + tag + ") " + envStr() + " ----");
    log("canvas w/h=" + safeS32(obj.add(0x4C4)) + "/" + safeS32(obj.add(0x4C8)) + " pcx w/h=" + safeS32(obj.add(0x13CEC)) + "/" + safeS32(obj.add(0x13CF0)));
    for (const [n, off] of RECTS) log("RECT " + n + " = " + rstr(obj.add(off)));
    for (const i of [0, 4, 9, 16, 23, 24]) {
      const b = obj.add(0xCEC + i * 0xB4C);
      log("BTN#" + i + " local=" + rstr(b.add(0x474)) + " parentRel=" + rstr(b.add(0x13C)) + " canvas=" + safeS32(b.add(0x4C4)) + "x" + safeS32(b.add(0x4C8)));
    }
    for (let i = 0; i < 3; i++) { const f = obj.add(0x14540 + i * 0x28); let d = []; for (let j = 0; j < 8; j++) d.push(safeS32(f.add(j * 4))); log("FONT F" + i + " dw0..7: " + d.join(",")); }
    log("caviar zoom=" + safeF32(obj.add(0x1279C + 0xD5)).toFixed(4) + " unit=" + safeS32(obj.add(0x141F8)));
  }
  function runsCol(bi, x, y0, y1) { const out = []; let cur = -1, st = y0; for (let y = y0; y < y1; y++) { const v = bi.data.add(y * bi.pitch + x).readU8(); if (v !== cur) { if (cur >= 0) out.push([st, y - 1, cur]); cur = v; st = y; } } if (cur >= 0) out.push([st, y1 - 1, cur]); return out; }
  function runsRow(bi, y, x0, x1) { const out = []; let cur = -1, st = x0; for (let x = x0; x < x1; x++) { const v = bi.data.add(y * bi.pitch + x).readU8(); if (v !== cur) { if (cur >= 0) out.push([st, x - 1, cur]); cur = v; st = x; } } if (cur >= 0) out.push([st, x1 - 1, cur]); return out; }
  function fmtRuns(runs, maxN) { const n = Math.min(runs.length, maxN || 90); const sarr = []; for (let i = 0; i < n; i++) { const [a, b, v] = runs[i]; sarr.push(a + (b !== a ? ".." + b : "") + "=" + v + "(" + pal(v).join(",") + ")"); } if (runs.length > n) sarr.push("...+" + (runs.length - n)); return sarr.join(" "); }
  function trace(obj, tag) {
    try {
      const bi = bufInfo(obj.add(0x444));
      if (bi.data.isNull() || bi.w <= 0 || bi.h <= 0) return;
      const b0 = rect4(obj.add(0xAAC)), b4 = rect4(obj.add(0xB8C)), pv = rect4(obj.add(0xA9C));
      const cl = (v, hi) => Math.min(hi - 1, Math.max(0, v));
      log("TRACE canvas " + tag + " " + bi.w + "x" + bi.h);
      log("TRACE col x=" + cl((b0[0] + b0[2]) >> 1, bi.w) + " (box0 centre) y " + cl(b0[1] - 12, bi.h) + "..: " + fmtRuns(runsCol(bi, cl((b0[0] + b0[2]) >> 1, bi.w), cl(b0[1] - 12, bi.h), cl(b0[3] + 12, bi.h)), 80));
      log("TRACE col x=" + cl((pv[0] + pv[2]) >> 1, bi.w) + " (preview centre) y 0..: " + fmtRuns(runsCol(bi, cl((pv[0] + pv[2]) >> 1, bi.w), 0, cl(pv[1] + 60, bi.h)), 60));
      log("TRACE row y=" + cl((b4[1] + b4[3]) >> 1, bi.h) + " (lower btn row mid): " + fmtRuns(runsRow(bi, cl((b4[1] + b4[3]) >> 1, bi.h), 0, bi.w), 120));
      log("TRACE row y=" + cl((b0[1] + b0[3]) >> 1, bi.h) + " (box0 mid): " + fmtRuns(runsRow(bi, cl((b0[1] + b0[3]) >> 1, bi.h), 0, cl(b0[2] + 12, bi.w)), 60));
      const mi = bufInfo(VA(G_MAINBUF));
      const pa = rect4(obj.add(0xA7C)), ss = rect4(obj.add(0xB0C)), fb = rect4(obj.add(0xB1C));
      if (!mi.data.isNull()) {
        log("TRACE console col x=" + cl(pa[0] + 20, mi.w) + " (presets col0 left edge+20) y " + cl(pa[1] - 40, mi.h) + "..: " + fmtRuns(runsCol(mi, cl(pa[0] + 20, mi.w), cl(pa[1] - 40, mi.h), cl(pa[3] + 8, mi.h)), 100));
        log("TRACE console row y=" + cl(ss[1] + s(3) + s(12), mi.h) + " (slot name row): " + fmtRuns(runsRow(mi, cl(ss[1] + s(3) + s(12), mi.h), cl(ss[0] - 8, mi.w), cl(ss[2] + 8, mi.w)), 120));
        log("TRACE console row y=" + cl((fb[1] + fb[3]) >> 1, mi.h) + " (flash mid): " + fmtRuns(runsRow(mi, cl((fb[1] + fb[3]) >> 1, mi.h), cl(fb[0] - 8, mi.w), cl(fb[2] + 8, mi.w)), 80));
      }
    } catch (e) { log("TRACE error: " + e); }
  }

  // ---------------------------------------------------------------------------
  // hooks (function entries only)
  // ---------------------------------------------------------------------------
  Interceptor.attach(VA(A_EXEC), {
    onEnter() {
      learnG();
      log("EXEC enter faction=" + safeS32(this.context.esp.add(4)) + " unit=" + safeS32(this.context.esp.add(8)) + " | " + envStr());
      heapCheck("exec-enter");
      if (g > 16) { applyPatches(); applyRails(); applyFrameRedirect(); installCaviarShim(); setGateRange(true); dwActive = true; heapCheck("exec-enter patched"); dumpCellParams(); }
      else log("g<=16 -> native no-op");
    },
    onLeave() {
      dwActive = false;
      if (g > 16) setGateRange(false);
      heapCheck("exec-leave");
      { const sites = Object.entries(cvSite).map(([k, v]) => k + ":" + v.n + "x max " + v.maxw + "x" + v.maxh + " x[" + v.minx + "," + v.maxx + "] y[" + v.miny + "," + v.maxy + "] clipped=" + v.clipped + " modes=" + JSON.stringify(v.modes)).join(" | ");
        log("CAVIAR summary: draws " + cvDraws + " clamps " + cvClamps + " trial renders " + fitMsN + " avg " + (fitMsN ? (fitMsSum / fitMsN).toFixed(2) : "?") + " ms | ssaa composites " + ssaaMsN + " avg " + (ssaaMsN ? (ssaaMsSum / ssaaMsN).toFixed(2) : "?") + " ms | target " + TN + " | footprint " + (fpArmed ? JSON.stringify(fpStats) : "OFF") + " clip overrides " + clipOverrides + " | " + sites); }
      log("HEAPCHK timing: " + heapChecks + " checks, max " + heapMsMax + " ms, avg " + (heapChecks ? (heapMsSum / heapChecks).toFixed(2) : "?") + " ms");
      log("EXEC leave");
    }
  });
  Interceptor.attach(VA(A_BUILD), {
    onEnter() { learnG(); this.obj = this.context.ecx; log("BUILD enter " + envStr() + (patched ? " (patched)" : " (unpatched)")); heapCheck("build-enter"); },
    onLeave() {
      heapCheck("build-leave");
      if (g > 16 && patched) { try { renderBackdrop(this.obj); } catch (e) { log("BACKDROP ERROR: " + e); } heapCheck("post-backdrop"); }
      dump(this.obj, "post-build");
      const w = safeS32(this.obj.add(0x4C4)), h = -safeS32(this.obj.add(0x4C8)), r = rect4(this.obj.add(0x13C));
      log("WINDOW LAW: canvas " + w + "x" + h + " expect " + Math.ceil(623 * g / 16) + "x" + (s(600) - safeS32(VA(G_STRIPH))) + "; screen " + r + " expect x=" +
          Math.floor((safeS32(VA(G_SCREENW)) - w + s(0x20)) / 2) + " y=" + (safeS32(VA(G_SCREENH)) - safeS32(VA(G_STRIPH)) - h));
      const b0 = rect4(this.obj.add(0xAAC)), b1 = rect4(this.obj.add(0xABC)), b3 = rect4(this.obj.add(0xADC));
      log("BOX LAW: box0 " + (b0[2] - b0[0]) + "x" + (b0[3] - b0[1]) + " box1 " + (b1[2] - b1[0]) + "x" + (b1[3] - b1[1]) + " box3 " + (b3[2] - b3[0]) + "x" + (b3[3] - b3[1]) +
          " pitch " + (b1[1] - b0[1]) + " (native 99x85 pitch 94 -> x" + (g / 16).toFixed(4) + ")");
    }
  });
  let paintN = 0, needTrace = false, traceObj = null;
  Interceptor.attach(VA(A_MASTER), {
    onEnter() { paintN++; if (paintN <= 2 || paintN % 20 === 0) { log("paint#" + paintN); } if (paintN <= 3) { needTrace = true; traceObj = this.context.ecx; } },
    onLeave() { heapCheck("paint#" + paintN + "-leave", !(paintN <= 5 || paintN % 20 === 0)); }
  });
  Interceptor.attach(VA(A_ONMODE), {
    onEnter() { this.mode = safeS32(this.context.esp.add(4)); log("ONMODE enter=" + this.mode + " win.screen=" + rstr(this.context.ecx.sub(0xA14).add(0x13C))); },
    onLeave() { heapCheck("onmode(" + this.mode + ")-leave"); }
  });
  for (const [name, va] of [["slide_show", A_SLIDESHOW], ["slide_hide", A_SLIDEHIDE]]) {
    Interceptor.attach(VA(va), {
      onEnter() { const win = this.context.esp.add(4).readPointer(); if (win.equals(VA(G_OBJ))) log(name + " (DesignWin) ret=" + this.returnAddress + " fdwinbuf=" + hex(safeU32(VA(PCAVE2 + 0x25E0))) + " canvasW=" + safeS32(win.add(0x4C4))); }
    });
  }
  for (const [name, va] of [["slide_show", A_SLIDESHOW], ["slide_hide", A_SLIDEHIDE]]) {          // D8 (second attach: onLeave only)
    Interceptor.attach(VA(va), {
      onEnter() { this.dw = this.context.esp.add(4).readPointer().equals(VA(G_OBJ)); },
      onLeave() { if (this.dw) heapCheck(name + "-leave"); }
    });
  }
  // ---------------------------------------------------------------------------
  // D9: bracket trace (see header). Hosts are cave thunk ENTRIES (entered by CALL / detour
  // push-ret; never a baked-detour family) and DesignWin painter entries.
  // ---------------------------------------------------------------------------
  const T_HUDBOX_E = 0xA11740, T_HOLLOW_FLAT_E = 0xA0C140, T_DEVFILL_E = 0xA0E2A0, T_REMAP_E = 0xA1C000;
  function spriteStr(p) {
    try {
      if (p.isNull()) return "0";
      return hex(p.toInt32()) + "{data=" + hex(safeU32(p.add(4))) + " key=" + p.add(8).readU8() + " pitch=" + safeS32(p.add(0xC)) +
        " blit=" + safeS32(p.add(0x10)) + "x" + safeS32(p.add(0x14)) + " canvas=" + safeS32(p.add(0x18)) + "x" + safeS32(p.add(0x1C)) +
        " off=" + safeS32(p.add(0x20)) + "," + safeS32(p.add(0x24)) + " mask=" + hex(safeU32(p.add(0x30))) + "}";
    } catch (e) { return "?" + e; }
  }
  function paramsStr(pp) {
    try {
      const d = []; for (let i = 0; i < 10; i++) d.push(hex(safeU32(pp.add(4 * i))));
      const fill = pp.add(0x20).readPointer();
      return hex(pp.toInt32()) + "[" + d.join(" ") + "] fill=" + spriteStr(fill) + " TL=" + spriteStr(pp.readPointer());
    } catch (e) { return "?" + e; }
  }
  function dumpCellParams() { for (const a of [0x78D528, 0x78D550, 0x78D578, 0x78D5A0]) log("PARAMS " + hex(a) + " " + paramsStr(VA(a))); }
  const thunkSeen = {};
  for (const [name, va, base] of [["hollow_flat", T_HOLLOW_FLAT_E, 4]]) {          // v8: only the D10 host remains
    Interceptor.attach(VA(va), {
      onEnter() {
        if (!dwActive) return;
        this.on = true;
        const sp = this.context.esp;
        const n = (thunkSeen[name] = (thunkSeen[name] || 0) + 1);
        try {
          if (base < 0) {
            this.lbl = name + " #" + n + " ret=" + hex(sp.readU32()) + " ecx=" + hex(this.context.ecx.toInt32());
          } else {
            const rp = sp.add(base).readPointer(), pp = sp.add(base + 4).readPointer();
            const r = [0, 4, 8, 12].map(o => safeS32(rp.add(o)));
            const ppv = pp.toInt32(), dv = this.context.ecx.toInt32();
            this.hover = (name === "hollow_flat" && ((dv === 0x7AEC64 && (ppv === 0x78D550 || ppv === 0x78D578)) || (pickerCanvas !== 0 && dv === pickerCanvas))) ? { dest: this.context.ecx, r, tag: hex(ppv) + (dv === pickerCanvas ? "@picker" : "@hud") } : null;   // v12: + selected d578, + picker cells
            this.lbl = name + " #" + n + " ret=" + hex(sp.add(base - 4).readU32()) + " dest=" + hex(this.context.ecx.toInt32()) + " params=" + hex(pp.toInt32()) +
              " rect=(" + r.join(",") + ") [" + (r[2] - r[0]) + "x" + (r[3] - r[1]) + "]" + (name === "hud_boxframe" ? " hudflag=" + safeU32(VA(0xA0E554)) : "");
          }
          if (n <= 60) log("THUNK " + this.lbl);
        } catch (e) { this.lbl = name + " #" + n + " (args unreadable " + e + ")"; }
      },
      onLeave() {
        if (!this.on) return;
        heapCheck("after " + this.lbl, true);
        if (this.hover) { try { restripeHoverCell(this.hover.dest, this.hover.r, undefined, this.hover.tag); } catch (e) { log("HOVER restripe err " + e); } }
      }
    });
  }
  // D10: the d550 (hover) fill pair is not in the baked remap table -> P-law restripe of the cell
  // interior (inset K+2 from the frame) in the MainWin buffer, phase = buffer row (SL.stripeTop).
  let hoverLogs = 0;
  function restripeHoverCell(buf, r, inset, tag) {
    const bi = bufInfo(buf); if (bi.data.isNull()) return;
    const K = SL.strokeWidth(g), ins = (inset === undefined) ? K + 2 : inset, x0 = Math.max(0, r[0] + ins), y0 = Math.max(0, r[1] + ins), x1 = Math.min(r[2] - ins, bi.w), y1 = Math.min(r[3] - ins, bi.h);
    tag = tag || "";
    const W = x1 - x0, H = y1 - y0; if (W < 8 || H < 8) return;
    const u8 = new Uint8Array(W * H);
    for (let y = 0; y < H; y++) u8.set(new Uint8Array(bi.data.add((y0 + y) * bi.pitch + x0).readByteArray(W)), y * W);
    const pair = detectPair(u8, W, H, Math.max(1, Math.floor(W * 0.15)));
    if (!pair) { if (hoverLogs++ < 12) log("HOVER restripe SKIP (no pair) " + tag + " rect " + r.join(",")); return; }
    const [a, b] = pair;
    for (let y = 0; y < H; y++) { const c = SL.stripeTop(y0 + y, g, 0) ? a : b, o = y * W; for (let x = 0; x < W; x++) { const v = u8[o + x]; if (v === a || v === b) u8[o + x] = c; } }
    for (let y = 0; y < H; y++) bi.data.add((y0 + y) * bi.pitch + x0).writeByteArray(u8.subarray(y * W, (y + 1) * W));
    if (hoverLogs++ < 12 || (tag.indexOf("picker") >= 0 || tag === "tile") && pickerLogs++ < 200) log("HOVER restripe " + tag + " pair " + a + "(" + pal(a).join(",") + ")/" + b + "(" + pal(b).join(",") + ") rect " + r.join(",") + " P=" + SL.stripePeriod(g, 0));
  }
  // D11: bracket the TutWin paint + preview animation. Cave thunks: onEnter ONLY.
  for (const [name, va] of []) {                                                    // v8: cave brackets off
    Interceptor.attach(VA(va), {
      onEnter() { if (!dwActive) return; const n = (thunkSeen[name] = (thunkSeen[name] || 0) + 1); if (n <= 4) log("CAVE " + name + " #" + n + " ret=" + hex(this.context.esp.readU32()) + " ecx=" + hex(this.context.ecx.toInt32())); heapCheck("enter " + name + " #" + n, true); }
    });
  }
  for (const [name, va] of []) {                                                    // v8: engine brackets off
    Interceptor.attach(VA(va), {
      onEnter() { if (!dwActive) return; this.on = true; const n = (thunkSeen[name] = (thunkSeen[name] || 0) + 1); if (n <= 4) log("ENTER " + name + " #" + n + " ret=" + hex(this.context.esp.readU32())); heapCheck("enter " + name + " #" + n, true); },
      onLeave() { if (this.on) heapCheck("leave " + name + " #" + thunkSeen[name], true); }
    });
  }
  // v8: poll100 off
  // D12: draw_unit_preview internals (callee ENTRIES; see header). Checks only inside the painter, tick >= 5.
  let pvDepth = 0, pvTicks = 0;
  Interceptor.attach(VA(0x436090), {
    onEnter() { if (!dwActive) return; this.on = true; pvTicks++; pvDepth++; if (pvTicks <= 3 || pvTicks % 10 === 0) log("PV tick #" + pvTicks + " tid=" + Process.getCurrentThreadId()); },
    onLeave() { if (this.on) pvDepth--; }
  });
  const PV = [["construct_model", 0x43BF50], ["vehdraw_construct_armor", 0x4C3090], ["f57d510", 0x57D510], ["f57d7d0", 0x57D7D0], ["f57e040", 0x57E040],
              ["f5a5a60", 0x5A5A60], ["f5b9f20", 0x5B9F20], ["f5c13b0", 0x5C13B0], ["f5c17d0", 0x5C17D0], ["f5c1d50", 0x5C1D50], ["f5d95e0_copy", 0x5D95E0],
              ["Buffer_write_l", 0x5DB580], ["Buffer_write_cent_l_2", 0x5DB720], ["Buffer_write_l_3", 0x5DCEA0], ["Buffer_wrap_cent_6", 0x5DDAB0],
              ["f6169a0", 0x6169A0], ["Caviar_overlay", 0x6171A0], ["Caviar_set_angle", 0x618370], ["Caviar_set_zoom", 0x6183B0], ["Caviar_reset", 0x618470], ["f645dd0", 0x645DD0]];
  for (const [name, va] of []) {                                                    // v8: PV brackets off (PV list kept for reference)
    Interceptor.attach(VA(va), {
      onEnter() {
        if (!dwActive || pvDepth <= 0 || pvTicks < 5) return;
        this.on = true;
        const n = (thunkSeen["pv:" + name] = (thunkSeen["pv:" + name] || 0) + 1);
        if (n <= 2) log("PV " + name + " #" + n + " ret=" + hex(this.context.esp.readU32()) + " ecx=" + hex(this.context.ecx.toInt32()) + " args=" + [4, 8, 12, 16].map(o => hex(safeU32(this.context.esp.add(o)))).join(","));
        heapCheck("pv-enter " + name + " #" + n + " tick " + pvTicks, true);
      },
      onLeave() { if (this.on) heapCheck("pv-leave " + name + " #" + thunkSeen["pv:" + name] + " tick " + pvTicks, true); }
    });
  }
  // ---------------------------------------------------------------------------
  // v12 Z'': Caviar composite shim (keystone bytes from _dw_crops/v12/asm_stubs.py; gate = DEST
  // buffer: DesignWin canvas 0x71F6F4 or the live PartPicker canvas, g>16) + the render-quality
  // experiments FIT / SSAA (see header). The shim reads its law from a data page the JS writes
  // per draw: [fitW] = composite size (0 = suppress the blit), [fitOff] = fitW/2 - 128.
  // ---------------------------------------------------------------------------
  // A/B MODE FILE: D:/SmacxUi/work/dw_mode.txt holds one word -> nn (v11 look: native render, NN x g/16) |
  // fit (option A) | ssaa (A + option B on the icons). Missing/unreadable file = ssaa. Logged as "MODE".
  // Optional second word = number of consecutive PREVIEW frames to dump (the 256^2 target read at
  // Caviar_reset entry, before it is cleared) into _dw_crops/v12/frames/<mode>_<nnn>.raw + palette.raw
  // + frames.log (zoom', k, W, matrix) for the jitter analysis (v12/jitter.py).
  let DW_MODE = "ssaa", DUMP_FRAMES = 0, DUMP_SKIP = 0, TN = 256;   // third word = preview frames to SKIP before dumping (25/s); tN = option E target size (t512 / t1024)
  try { const w = File.readAllText("D:/SmacxUi/work/dw_mode.txt").trim().toLowerCase().split(/\s+/); const t = w[0]; if (["nn", "fit", "ssaa"].includes(t)) DW_MODE = t; else log("MODE file has '" + t + "' (expected nn|fit|ssaa) -> ssaa"); if (w[1]) DUMP_FRAMES = parseInt(w[1], 10) || 0; if (w[2]) DUMP_SKIP = parseInt(w[2], 10) || 0; for (const t of w) { const m = /^t(\d+)$/.exec(t); if (m) TN = parseInt(m[1], 10); } } catch (e) { log("MODE file not read (" + e + ") -> ssaa"); }
  const FIT = DW_MODE !== "nn";        // render-to-fit: Caviar zoom x k, k = min(g/16, 240/(E*1.06)); composite W = 256*(g/16)/k
  const SSAA = DW_MODE === "ssaa";     // when 2x device density fits the 256^2 target (icons): render at 2x, 2x2 box-average (JS composite)
  // ---------------------------------------------------------------------------
  // OPTION E (v13): grow the Caviar render target from 256^2 to TN^2. Applied at script LOAD (the engine
  // allocates the target in its global init, long before the workshop). Census (_dw_unit_quality_options.md
  // + v12 dis_*): the row tables are descriptor-driven (0x63F9B0), so the size lives in: the init's
  // `mov esi,0x100` (Buffer_init dims, descriptor w/h/z-pitch, ctx clip w/h, row-loop stride), the
  // z-plane malloc/memset, the ctx clip R/B 0xFF, the row-loop bound 0x400, the per-object clip fields
  // (ctor/attach/set: 0xFF/0x100), Caviar_draw's composite window (+-0x80/0x100, half mode -0x40),
  // Caviar_overlay's -0x80, and Caviar_reset's z stride (shl 8 / 0x200). Sites whose disp8 cannot hold
  // the new value go through keystone stubs (asm_e.py). Every site is byte-verified; any mismatch aborts
  // E (TN falls back to 256) so the rest of the proto stays consistent.
  // EWIN: 39 bytes, site 0x61730d len 27
  const EWIN_CODE = [0x8d, 0xb9, 0x77, 0x77, 0x77, 0x77, 0x89, 0x54, 0x24, 0x4c, 0x8d, 0xb0, 0x77, 0x77, 0x77, 0x77, 0x8d, 0x4c, 0x24, 0x40, 0x8d, 0x97, 0x66, 0x66, 0x66, 0x66, 0x51, 0x8d, 0x86, 0x66, 0x66, 0x66, 0x66, 0x68, 0x28, 0x73, 0x61, 0x00, 0xc3];
  const EWIN_OFFS = {'FULL': [22, 29], 'HALFNEG': [2, 12]};
  // EOVL: 20 bytes, site 0x6171e7 len 8
  const EOVL_CODE = [0x81, 0xc1, 0x77, 0x77, 0x77, 0x77, 0x6a, 0x01, 0x81, 0xc2, 0x77, 0x77, 0x77, 0x77, 0x68, 0xef, 0x71, 0x61, 0x00, 0xc3];
  const EOVL_OFFS = {'HALFNEG': [2, 10]};
  // EHALFA: 34 bytes, site 0x61757b len 25
  const EHALFA_CODE = [0x05, 0x55, 0x55, 0x55, 0x55, 0x8b, 0x51, 0x54, 0x8b, 0x8c, 0x24, 0x8c, 0x00, 0x00, 0x00, 0x52, 0x6a, 0x02, 0x6a, 0x01, 0x81, 0xc1, 0x55, 0x55, 0x55, 0x55, 0x50, 0x51, 0x68, 0xa4, 0x75, 0x61, 0x00, 0xc3];
  const EHALFA_OFFS = {'QNEG': [1, 22]};
  // EHALFB: 22 bytes, site 0x6175da len 12
  const EHALFB_CODE = [0x81, 0xc1, 0x55, 0x55, 0x55, 0x55, 0x6a, 0x01, 0x81, 0xc2, 0x55, 0x55, 0x55, 0x55, 0x51, 0x52, 0x68, 0xec, 0x75, 0x61, 0x00, 0xc3];
  const EHALFB_OFFS = {'QNEG': [2, 10]};

  const RETAINED = [];                                     // v13a: Memory.alloc pages are GC-FREED when unreferenced -> every stub page must be retained
  const E_STUBS = [];                                      // { nm, a, p, code(with fixups) } for the first-exec re-verify
  function allocStub(code, offs, fixups) {
    const p = Memory.alloc(Process.pageSize); RETAINED.push(p);
    Memory.patchCode(p, code.length, c => { c.writeByteArray(code); for (const [k, addr] of Object.entries(fixups)) for (const o of (offs[k] || [])) c.add(o).writeU32(addr >>> 0); });
    return p;
  }
  // FP: 125 bytes, site 0x6649b4 len 6 -> resume 0x664a29 (no stack use)
  const FP_CODE = [0x8a, 0x3c, 0x04, 0x83, 0xc7, 0x03, 0x8b, 0x35, 0xbc, 0xe6, 0x9b, 0x00, 0x8a, 0x04, 0x1e, 0x8a, 0x5f, 0xfd, 0x89, 0x0d, 0x70, 0x71, 0x71, 0x71, 0x89, 0xe9, 0x03, 0x0d, 0xa8, 0xe6, 0x9b, 0x00, 0x89, 0xce, 0x03, 0x35, 0x84, 0x71, 0x71, 0x71, 0x3b, 0x35, 0x88, 0x71, 0x71, 0x71, 0x73, 0x42, 0x89, 0xee, 0x01, 0xf6, 0x03, 0x35, 0xa4, 0xe6, 0x9b, 0x00, 0x8a, 0x25, 0x90, 0x71, 0x71, 0x71, 0x88, 0x25, 0x78, 0x71, 0x71, 0x71, 0x8a, 0x25, 0x74, 0x71, 0x71, 0x71, 0x66, 0x3b, 0x16, 0x73, 0x05, 0x66, 0x89, 0x16, 0x88, 0x01, 0x83, 0xc6, 0x02, 0x41, 0xfe, 0xcc, 0x75, 0xee, 0x03, 0x35, 0x7c, 0x71, 0x71, 0x71, 0x03, 0x0d, 0x80, 0x71, 0x71, 0x71, 0xfe, 0x0d, 0x78, 0x71, 0x71, 0x71, 0x75, 0xd4, 0x8b, 0x0d, 0x70, 0x71, 0x71, 0x71, 0xe9, 0x44, 0x44, 0x44, 0x44];
  const FP_OFFS = {'SAVE_ECX': [20, 116], 'N': [72], 'NY': [60], 'ROWS': [66, 108], 'ZROW': [96], 'DROW': [102], 'SPAN': [36], 'DEND': [42], 'RET': [121]};
  // FP2: 105 bytes, site 0x664c64 len 6 -> resume 0x664cc6 (no stack use; esp = voxel counter)
  const FP2_CODE = [0x01, 0xd9, 0x89, 0x0d, 0x8c, 0x71, 0x71, 0x71, 0x03, 0x0d, 0xa8, 0xe6, 0x9b, 0x00, 0x89, 0xcb, 0x03, 0x1d, 0x84, 0x71, 0x71, 0x71, 0x3b, 0x1d, 0x88, 0x71, 0x71, 0x71, 0x73, 0x46, 0x8b, 0x1d, 0x8c, 0x71, 0x71, 0x71, 0x01, 0xdb, 0x03, 0x1d, 0xa4, 0xe6, 0x9b, 0x00, 0x8a, 0x25, 0x90, 0x71, 0x71, 0x71, 0x88, 0x25, 0x78, 0x71, 0x71, 0x71, 0x8a, 0x25, 0x74, 0x71, 0x71, 0x71, 0x66, 0x3b, 0x13, 0x73, 0x05, 0x66, 0x89, 0x13, 0x88, 0x01, 0x83, 0xc3, 0x02, 0x41, 0xfe, 0xcc, 0x75, 0xee, 0x03, 0x1d, 0x7c, 0x71, 0x71, 0x71, 0x03, 0x0d, 0x80, 0x71, 0x71, 0x71, 0xfe, 0x0d, 0x78, 0x71, 0x71, 0x71, 0x75, 0xd4, 0xe9, 0x44, 0x44, 0x44, 0x44];
  const FP2_OFFS = {'N': [58], 'NY': [46], 'ROWS': [52, 94], 'ZROW': [82], 'DROW': [88], 'SPAN': [18], 'DEND': [24], 'IDX': [4, 32], 'RET': [101]};
  // v14 FOOTPRINT: the 8-bit voxel plotter (0x6647F0) has two footprints only - 1 px when zoom*partScale
  // <= 0.5 (mode bit0) and a FIXED 2x2 block otherwise. On-screen voxel spacing is zoom*partScale px, so a
  // one-voxel-thick hollow shell (colony pod tank, part scale ~6) goes see-through once spacing > 2 px
  // (v13a 4K preview zoom' 0.7 -> ~4 px). The cave plots an n x n block, n = [FP_N] (2 = vanilla, set per
  // part by the 0x63E950 hook: max(2, ceil(zoom*partScale)) for gated draws, clamped to 8). Bottom-overflow
  // guarded (SPAN/DEND); no stack use (esp is the shade-table base inside the plotter).
  const FP = { N: 16, SAVE: 20, ROWS: 24, ZROW: 28, DROW: 32, SPAN: 36, DEND: 40, IDX: 44, NY: 48 };   // N = NX (cols), NY = rows           // stubData offsets
  let pickerLogs = 0;
  let fpArmed = false, fpCur = "2x2", fpGatedPart = false; const fpStats = {};
  function applyFootprint() {                             // v14b: BOTH big-mode blocks of the full plotter (flag&4 path @0x6649B4, plain path @0x664C64)
    const sites = [["FP", 0x6649B4, [0x8a, 0x3c, 0x04, 0x83, 0xc7, 0x03], FP_CODE, FP_OFFS, 0x664A29], ["FP2", 0x664C64, [0x03, 0xcb, 0x66, 0x3b, 0x14, 0x4d], FP2_CODE, FP2_OFFS, 0x664CC6]];
    for (const [nm, a, nat] of sites) {
      const cur = Array.from(new Uint8Array(VA(a).readByteArray(6)));
      if (cur.join() !== nat.join()) { log("FP ABORT: " + nm + " site @" + hex(a) + " bytes " + cur.map(b => b.toString(16)).join(" ")); return; }
    }
    const fix = {}; for (const k of Object.keys(FP)) fix[k === "SAVE" ? "SAVE_ECX" : k] = stubData.add(FP[k]).toInt32();
    stubData.add(FP.N).writeU32(2); stubData.add(FP.NY).writeU32(2); stubData.add(FP.DEND).writeU32(0);
    for (const [nm, a, nat, code, offs, resume] of sites) {
      const p = allocStub(code, offs, fix);
      const ro = offs.RET[0]; Memory.patchCode(p.add(ro), 4, c => c.writeS32(resume - (p.toInt32() + ro + 4)));
      E_STUBS.push({ nm, a, p, code: Array.from(new Uint8Array(p.readByteArray(code.length))) });
      Memory.patchCode(VA(a), 6, c => { c.writeU8(0xE9); c.add(1).writeS32(p.toInt32() - (a + 5)); c.add(5).writeU8(0x90); });
      log("FP: footprint cave " + nm + " armed @" + hex(a) + " -> " + p + " (resume " + hex(resume) + ")");
    }
    fpArmed = true;
  }
  function fpSet(nx, ny) {                                // per-part footprint (target already bound); nx cols, ny rows
    const pitch = safeU32(VA(0x9BE6B0)), zp = safeU32(VA(0x9BE6B4)), base = safeU32(VA(0x9BE6A8));
    stubData.add(FP.N).writeU32(nx); stubData.add(FP.NY).writeU32(ny); stubData.add(FP.ZROW).writeU32((2 * zp - 2 * nx) >>> 0); stubData.add(FP.DROW).writeU32((pitch - nx) >>> 0);
    stubData.add(FP.SPAN).writeU32(((ny - 1) * pitch + (nx - 1)) >>> 0); stubData.add(FP.DEND).writeU32((base + pitch * TN) >>> 0);
    fpCur = nx + "x" + ny;
  }
  // v14 NATIVE SSAA composite (CModule; the bake ports this to asm). Same law as the v12/v13 JS version:
  // per output pixel, box [b0,b1) per axis with b0=floor(d*TN/W), mean RGB of the non-key samples,
  // coverage >= 1/2 else keyed, nearest palette index among the render's OWN indices via a 6-bit RGB cache.
  const cmSsaa = new CModule(`
typedef unsigned char u8; typedef short i16;
int ssaa(const u8 *src, int sp, int tn, u8 *dst, int dp, int L, int T, int R, int B, int left, int top, int W,
         const u8 *pal, i16 *inv, int key, int sx0, int sy0, int sx1, int sy1) {
  u8 present[256]; int cand[256]; int nc = 0, i, x, y, dx, dy, wrote = 0;
  for (i = 0; i < 256; i++) present[i] = 0;
  for (y = sy0; y <= sy1; y++) { const u8 *row = src + y * sp; for (x = sx0; x <= sx1; x++) present[row[x]] = 1; }
  present[key & 255] = 0;
  for (i = 0; i < 256; i++) if (present[i]) cand[nc++] = i;
  if (nc == 0) return 0;
  for (i = 0; i < (1 << 18); i++) inv[i] = -1;
  int dy0 = (sy0 * W) / tn, dy1 = ((sy1 + 1) * W + tn - 1) / tn, dx0 = (sx0 * W) / tn, dx1 = ((sx1 + 1) * W + tn - 1) / tn;
  if (dy0 < 0) dy0 = 0; if (dx0 < 0) dx0 = 0; if (dy1 > W) dy1 = W; if (dx1 > W) dx1 = W;
  for (dy = dy0; dy < dy1; dy++) {
    int Y = top + dy; if (Y < T || Y >= B) continue;
    int s0 = (dy * tn) / W, s1 = ((dy + 1) * tn) / W; if (s1 < s0 + 1) s1 = s0 + 1; if (s1 > tn) s1 = tn;
    u8 *drow = dst + Y * dp;
    for (dx = dx0; dx < dx1; dx++) {
      int X = left + dx; if (X < L || X >= R) continue;
      int t0 = (dx * tn) / W, t1 = ((dx + 1) * tn) / W; if (t1 < t0 + 1) t1 = t0 + 1; if (t1 > tn) t1 = tn;
      int n = 0, tot = 0, rs = 0, gs = 0, bs = 0, sy, sx;
      for (sy = s0; sy < s1; sy++) { const u8 *row = src + sy * sp; for (sx = t0; sx < t1; sx++) { int v = row[sx]; tot++; if (v == key) continue; n++; rs += pal[v * 4]; gs += pal[v * 4 + 1]; bs += pal[v * 4 + 2]; } }
      if (n == 0 || n * 2 < tot) continue;
      int rr = rs / n, gg = gs / n, bb = bs / n, k = ((rr >> 2) << 12) | ((gg >> 2) << 6) | (bb >> 2);
      int best = inv[k];
      if (best < 0) { int bd = 0x7fffffff; best = cand[0]; for (i = 0; i < nc; i++) { int c = cand[i], dr = pal[c * 4] - rr, dg = pal[c * 4 + 1] - gg, db = pal[c * 4 + 2] - bb, d = dr * dr + dg * dg + db * db; if (d < bd) { bd = d; best = c; } } inv[k] = (i16)best; }
      drow[X] = (u8)best; wrote++;
    }
  }
  return wrote;
}
`);
  RETAINED.push(cmSsaa);                                  // v14a: a CModule is FREED on GC like Memory.alloc - NativeFunction holds only the raw code address (v14 4K run: every composite AV'd)
  const ssaaNative = new NativeFunction(cmSsaa.ssaa, "int", ["pointer", "int", "int", "pointer", "int", "int", "int", "int", "int", "int", "int", "int", "pointer", "pointer", "int", "int", "int", "int", "int"]);
  const ssaaInvBuf = Memory.alloc((1 << 18) * 2); RETAINED.push(ssaaInvBuf);
  function applyTargetE() {
    if (TN === 256) return;
    if (TN !== 512 && TN !== 1024) { log("E: unsupported target " + TN + " -> 256"); TN = 256; return; }
    const N = TN, L2 = Math.log2(N);
    if (safeU32(VA(0x9B9100)) !== 0) { log("E: TOO LATE - z-plane already allocated at " + hex(safeU32(VA(0x9B9100))) + " -> 256"); TN = 256; return; }
    const imms = [
      [0x6188B1 + 1, 4, 0x100, N, "init Buffer_init dims/descriptor/ctx w,h/row stride (esi)"],
      [0x618A91 + 1, 4, 0x20000, N * N * 2, "init z-plane malloc"],
      [0x618BA9 + 1, 4, 0x10000, N * N, "init z-plane memset16 count"],
      [0x618C67 + 1, 4, 0xFF, N - 1, "init ctx clip R/B"],
      [0x618CB4 + 1, 4, 0x400, N * 4, "init row-table loop bound"],
      [0x61728D + 1, 4, 0xFF, N - 1, "Caviar_draw obj clip R/B"], [0x6172A8 + 1, 4, 0x100, N, "Caviar_draw obj clip W/H"],
      [0x61735E + 1, 4, 0x80, N / 2, "Caviar_draw window centre x"], [0x617365 + 1, 4, 0x80, N / 2, "Caviar_draw window centre y"],
      [0x616ED4 + 1, 4, 0xFF, N - 1, "ctor clip R/B"], [0x616EEB + 1, 4, 0x100, N, "ctor clip W/H"],
      [0x6170C5 + 1, 4, 0xFF, N - 1, "attach clip R/B"], [0x6170DB + 1, 4, 0x100, N, "attach clip W/H"],
      [0x6183FC + 1, 4, 0xFF, N - 1, "set_target clip R/B"], [0x618410 + 1, 4, 0x100, N, "set_target clip W/H"],
      [0x618497 + 2, 1, 8, L2, "reset z row shift"], [0x6184DD + 2, 4, 0x200, N * 2, "reset z row stride"]];
    const stubSites = [
      ["EWIN", 0x61730D, 27, EWIN_CODE, EWIN_OFFS, [0x8d, 0x79, 0x80, 0x89, 0x54, 0x24, 0x4c, 0x8d, 0x70, 0x80]],
      ["EOVL", 0x6171E7, 8, EOVL_CODE, EOVL_OFFS, [0x83, 0xc1, 0x80, 0x6a, 0x01, 0x83, 0xc2, 0x80]],
      ["EHALFA", 0x61757B, 25, EHALFA_CODE, EHALFA_OFFS, [0x83, 0xc0, 0xc0, 0x8b, 0x51, 0x54]],
      ["EHALFB", 0x6175DA, 12, EHALFB_CODE, EHALFB_OFFS, [0x83, 0xc1, 0xc0, 0x6a, 0x01, 0x83, 0xc2, 0xc0]]];
    // verify everything first
    for (const [a, w, nat] of imms) { const cur = w === 1 ? VA(a).readU8() : VA(a).readU32(); if (cur !== nat) { log("E ABORT: imm @" + hex(a) + " is " + hex(cur) + " expected " + hex(nat)); TN = 256; return; } }
    for (const [nm, a, len, code, offs, nat] of stubSites) { const cur = Array.from(new Uint8Array(VA(a).readByteArray(nat.length))); if (cur.join() !== nat.join()) { log("E ABORT: " + nm + " site @" + hex(a) + " bytes " + cur.map(b => b.toString(16)).join(" ")); TN = 256; return; } }
    for (const [a, w, nat, v, label] of imms) Memory.patchCode(VA(a), w, c => { if (w === 1) c.writeU8(v); else c.writeU32(v >>> 0); });
    const fix = { FULL: N >>> 0, HALFNEG: (-(N / 2)) >>> 0, QNEG: (-(N / 4)) >>> 0 };
    for (const [nm, a, len, code, offs] of stubSites) {
      const p = allocStub(code, offs, fix);
      if (E_STUBS.some(e => e.p.equals(p))) { log("E ABORT: stub page " + p + " reused for " + nm + " (GC?)"); TN = 256; return; }
      E_STUBS.push({ nm, a, p, code: Array.from(new Uint8Array(p.readByteArray(code.length))) });
      Memory.patchCode(VA(a), len, c => { const rel = (p.toInt32() - (a + 5)) | 0; c.writeU8(0xE9); c.add(1).writeS32(rel); for (let i = 5; i < len; i++) c.add(i).writeU8(0x90); });
      log("E stub " + nm + " @" + hex(a) + " -> " + p);
    }
    log("E: Caviar render target " + N + "x" + N + " armed (" + imms.length + " immediates + " + stubSites.length + " stubs); z-plane " + (N * N * 2) + " B");
  }
  log("MODE " + DW_MODE + " (FIT=" + FIT + " SSAA=" + SSAA + ") dump frames=" + DUMP_FRAMES + " after skipping " + DUMP_SKIP + " target=" + TN);
  applyTargetE();
  function verifyStubPages(tag) {                          // v13a: catch page reuse/overwrite (the v13 4K crash) instead of executing foreign bytes
    const pages = RETAINED.map(p => p.toString()); const uniq = new Set(pages);
    let ok = uniq.size === pages.length;
    for (const e of E_STUBS) { const cur = Array.from(new Uint8Array(e.p.readByteArray(e.code.length))); if (cur.join() !== e.code.join()) { ok = false; log("STUBCHK " + tag + ": E stub " + e.nm + " @" + e.p + " OVERWRITTEN"); } }
    log("STUBCHK " + tag + ": " + pages.length + " pages, " + uniq.size + " distinct, E stubs " + E_STUBS.length + " -> " + (ok ? "ok" : "*** FAIL ***"));
    return ok;
  }
  const FRAME_DIR = "D:/SmacxUi/work/_dw_crops/v12/frames/";
  let dumpLeft = DUMP_FRAMES, dumpN = 0, curDraw = null, dumpLog = null;
  function dumpFrame() {
    try {
      const src = bufInfo(VA(CV_BUF)); if (src.data.isNull()) return;
      if (!dumpLog) { dumpLog = new File(FRAME_DIR + "frames.log", "a"); const pf = new File(FRAME_DIR + "palette.raw", "wb"); pf.write(VA(G_PALETTE).readByteArray(1024)); pf.close(); }
      const name = DW_MODE + "_" + String(dumpN).padStart(3, "0") + ".raw";
      const f = new File(FRAME_DIR + name, "wb"); f.write(src.data.readByteArray(TN * src.pitch)); f.close();
      const mtx = []; for (let i = 0; i < 9; i++) mtx.push(safeF32(curDraw.cv.add(0x38 + 4 * i)).toFixed(4));
      dumpLog.write(name + " unit=" + safeS32(VA(G_OBJ).add(0x141F8)) + " N=" + TN + " g=" + g + " mode=" + curDraw.mode + " zoom=" + curDraw.z.toFixed(4) + " k=" + curDraw.k.toFixed(3) + " W=" + curDraw.W + " zoom'=" + (curDraw.z * curDraw.k).toFixed(4) + " pitch=" + src.pitch + " bbox=" + ctxBBox().join(",") + " mtx=" + mtx.join(",") + " t=" + Date.now() + "\n"); dumpLog.flush();
      dumpN++; dumpLeft--;
      if (dumpLeft === 0) { log("DUMP done: " + dumpN + " preview frames in " + FRAME_DIR); dumpLog.close(); dumpLog = null; }
    } catch (e) { log("DUMP error " + e); dumpLeft = 0; }
  }
  const ARM_POPUP_ACTIVE = true;   // picker modal: g_popup_active++ (diplo-bracket recipe) so the scrollbar arrows 2D-zoom
  const A_COMPOSITE = 0x6175F4, A_COMPOSITE_RET = 0x6175F9, A_BUFFER_DRAW_2 = 0x5D84C0, DW_CANVAS = G_OBJ + 0x444, CV_CTX = 0x9BB478;
  // SHIM: 117 bytes
  const SHIM_CODE = [0x8b, 0x44, 0x24, 0x04, 0x3d, 0xf4, 0xf6, 0x71, 0x00, 0x74, 0x08, 0x3b, 0x05, 0x11, 0x11, 0x11, 0x11, 0x75, 0x5c, 0xa1, 0x40, 0x87, 0x66, 0x00, 0x83, 0xf8, 0x10, 0x7e, 0x52, 0xa1, 0x22, 0x22, 0x22, 0x22, 0x85, 0xc0, 0x74, 0x46, 0x53, 0x56, 0x57, 0x89, 0xc7, 0x8b, 0x1d, 0x33, 0x33, 0x33, 0x33, 0x8b, 0x54, 0x24, 0x24, 0x83, 0xfa, 0x02, 0x75, 0x04, 0xd1, 0xef, 0xd1, 0xfb, 0xbe, 0x00, 0x01, 0x00, 0x00, 0xff, 0x74, 0x24, 0x14, 0x57, 0x57, 0x8b, 0x44, 0x24, 0x28, 0x29, 0xd8, 0x50, 0x8b, 0x44, 0x24, 0x28, 0x29, 0xd8, 0x50, 0x56, 0x56, 0x6a, 0x00, 0x6a, 0x00, 0xff, 0x74, 0x24, 0x34, 0x51, 0xb8, 0x70, 0x86, 0x66, 0x00, 0xff, 0xd0, 0x5f, 0x5e, 0x5b, 0xc2, 0x18, 0x00, 0x68, 0xc0, 0x84, 0x5d, 0x00, 0xc3];
  const SHIM_OFFS = {'PICKER': [13], 'FITW': [30], 'FITOFF': [45]};
  // CELL: 100 bytes
  const CELL_CODE = [0x8b, 0x8e, 0x6c, 0x2b, 0x00, 0x00, 0x89, 0xdf, 0x29, 0xc7, 0x89, 0xf8, 0x99, 0xf7, 0xf9, 0x6b, 0xc0, 0x5e, 0x6b, 0xd2, 0x6c, 0x8d, 0x48, 0x04, 0x8d, 0x78, 0x5f, 0x8d, 0x82, 0x84, 0x00, 0x00, 0x00, 0x83, 0xc2, 0x1b, 0x56, 0x8b, 0x35, 0x40, 0x87, 0x66, 0x00, 0x0f, 0xaf, 0xce, 0x01, 0xc9, 0x83, 0xc1, 0x0f, 0xc1, 0xe9, 0x05, 0x0f, 0xaf, 0xfe, 0x01, 0xff, 0x83, 0xc7, 0x0f, 0xc1, 0xef, 0x05, 0x0f, 0xaf, 0xc6, 0x01, 0xc0, 0x83, 0xc0, 0x0f, 0xc1, 0xe8, 0x05, 0x0f, 0xaf, 0xd6, 0x01, 0xd2, 0x83, 0xc2, 0x0f, 0xc1, 0xea, 0x05, 0x5e, 0x89, 0x4d, 0xf4, 0x89, 0x7d, 0xfc, 0x68, 0xc6, 0x3d, 0x43, 0x00, 0xc3];
  const CELL_OFFS = {};
  // CLICK: 54 bytes
  const CLICK_CODE = [0xa1, 0x40, 0x87, 0x66, 0x00, 0x83, 0xf8, 0x10, 0x7e, 0x26, 0x52, 0x8b, 0x44, 0x24, 0x08, 0xc1, 0xe0, 0x04, 0x99, 0xf7, 0x3d, 0x40, 0x87, 0x66, 0x00, 0x89, 0x44, 0x24, 0x08, 0x8b, 0x44, 0x24, 0x0c, 0xc1, 0xe0, 0x04, 0x99, 0xf7, 0x3d, 0x40, 0x87, 0x66, 0x00, 0x89, 0x44, 0x24, 0x0c, 0x5a, 0x68, 0x20, 0x38, 0x43, 0x00, 0xc3];
  const CLICK_OFFS = {};
  // FRAME: 14 bytes
  const FRAME_CODE = [0x81, 0xef, 0x44, 0x44, 0x44, 0x44, 0x51, 0x52, 0x68, 0x6b, 0x42, 0x43, 0x00, 0xc3];
  const FRAME_OFFS = {'S55': [2]};
  const stubData = Memory.alloc(64); RETAINED.push(stubData);   // +0 fitW u32, +4 fitOff i32, +8 picker canvas u32
  const fitW = stubData, fitOff = stubData.add(4), pickerSlot = stubData.add(8);
  fitW.writeU32(0); fitOff.writeS32(0); pickerSlot.writeU32(0);
  const stubs = {};
  stubs.shim = allocStub(SHIM_CODE, SHIM_OFFS, { PICKER: pickerSlot.toInt32(), FITW: fitW.toInt32(), FITOFF: fitOff.toInt32() });
  { let o = -1; for (let i = 0; i + 4 < SHIM_CODE.length; i++) if (SHIM_CODE[i] === 0xbe && SHIM_CODE[i + 1] === 0x00 && SHIM_CODE[i + 2] === 0x01 && SHIM_CODE[i + 3] === 0x00 && SHIM_CODE[i + 4] === 0x00) { o = i; break; }
    if (o < 0) log("SHIM: srcW imm not found"); else Memory.patchCode(stubs.shim.add(o + 1), 4, c => c.writeU32(TN)); }
  stubs.cell = allocStub(CELL_CODE, CELL_OFFS, {});
  stubs.click = allocStub(CLICK_CODE, CLICK_OFFS, {});
  stubs.frame = allocStub(FRAME_CODE, FRAME_OFFS, {});   // S55 imm patched at apply time (needs g)
  // v14t OVL (user 1920 shot 022659: Probability Sheath = SHIELDING icon too large + a translucent grey
  // RECTANGLE over the whole preview clip). Caviar_overlay 0x6171A0 (DW icon @0x4355AC / preview @0x43635B /
  // picker armor cell @0x4332F1, armor idx 5 only) fills the target with bg 0x18, Caviar_draw(flag|8 = no
  // engine composite, no reset), then ITS OWN blit `call 0x5D94B0 @0x6171F8` (dst, key=bg, X-TN/2, Y-TN/2,
  // num 1, den 1, table 0x6EEF7C: dst = table[src<<8|dst], engine-scaled through SCALE_NUM/DEN like every
  // zoomed sprite). Two defects: (1) the FIT trial's Caviar_reset(0) refilled the target with key 9, so every
  // background pixel missed the bg key and went through the table = the rectangle (whole dst clip);
  // (2) the wrapper's 1:1 blit never scaled the k-zoomed render = the giant sheath. Fix: refill the target
  // with the wrapper's bg after the trial reset, plan with ssaa=false (the table cannot ride the SSAA
  // composite), and this ONE-SHOT stub in front of the blit: X,Y -= [OFF] (= W/2 - TN/2), num=[NUM],
  // den=[DEN] (W/TN reduced), [ON] cleared on consumption; vanilla pass-through when not armed. Unicorn-
  // checked (scratch ovl_stub.py). BAKE: same stub as a pcave2 thunk armed by the Caviar_draw FIT thunk.
  const OVL_CODE = [0xa1, 0x11, 0x11, 0x11, 0x11, 0x85, 0xc0, 0x74, 0x29, 0xc7, 0x05, 0x11, 0x11, 0x11, 0x11, 0x00, 0x00, 0x00, 0x00, 0xa1, 0x22, 0x22, 0x22, 0x22, 0x29, 0x44, 0x24, 0x0c, 0x29, 0x44, 0x24, 0x10, 0xa1, 0x33, 0x33, 0x33, 0x33, 0x89, 0x44, 0x24, 0x14, 0xa1, 0x44, 0x44, 0x44, 0x44, 0x89, 0x44, 0x24, 0x18, 0xe9, 0x00, 0x00, 0x00, 0x00];
  const OVL_OFFS = { ON: [1, 11], OFF: [20], NUM: [33], DEN: [42] };
  const A_OVL_BLIT = 0x6171F8, A_OVL_BLIT_TGT = 0x5D94B0, A_OVL_RET = 0x6171D4;
  const ovlData = Memory.alloc(16); RETAINED.push(ovlData); ovlData.writeU32(0);   // +0 ON, +4 OFF, +8 NUM, +12 DEN
  stubs.ovl = allocStub(OVL_CODE, OVL_OFFS, { ON: ovlData.toInt32(), OFF: ovlData.add(4).toInt32(), NUM: ovlData.add(8).toInt32(), DEN: ovlData.add(12).toInt32() });
  Memory.patchCode(stubs.ovl.add(51), 4, c => c.writeS32(A_OVL_BLIT_TGT - (stubs.ovl.toInt32() + 55)));
  E_STUBS.push({ nm: "OVL", a: A_OVL_BLIT, p: stubs.ovl, code: Array.from(new Uint8Array(stubs.ovl.readByteArray(OVL_CODE.length))) });
  const gcd = (a, b) => b ? gcd(b, a % b) : a;
  let ovlShim = null;
  // v15g: the last 2 px of the ability-list channel (engine-measured @1024/1920/1600, popup-local: vanilla frame 16 /
  // rows 19; ours 21/27 @g22, 23/30 @g25 vs lawful 22/26, 25/30). Two in-place cave edits (no attaches):
  //  (1) thunk_popup_nestpads v2 (LAW nested_frame_pad): pad = scale_px(2) at g>16 instead of floor(3g/16) - the thick
  //      chain draws the K stroke OUTSIDE the rect, so the visible channel == pad; vanilla's is 3-1 = 2. 38 -> 40 B, the
  //      2 extra bytes land in the zeroed tail (next occupant 0x37A0). Emulated (scratch nest_childx_v2.py).
  //  (2) thunk_orn_childx v2 (LAW ornate_dialog_child_x pad_x): the +ps3-3 compensation only when [popup+0x30e0] != 0
  //      (the native-3 carrier of the stack-picker family); the ability listbox has 0 and was pushed +1. 67 -> 76 B in
  //      the zeroed tail (next occupant thunk_pf_union_align 0xFBE0). Emulated. BAKE: both as thunk v2 in patches.yaml.
  // v15h: the ability list's scrollbar is NOT the popup rail (+0x3230) but the Win layer's HEAP ScrollBar ([popup+0x2794]
  // is a heap address; created @0x5EC3AB when the element's rail callback returns 0) - vanilla's plain 20-px bar. None of
  // the rail thunks see it (they gate on the rail_slide_in sites) and thunk_sb_thumb (grip zoom) is netwin-gated. Proto:
  // (1) SBI above scales ScrollBar_init's width arg under the popup gate (bar 50 px @4K, x = clientW from WC2);
  // (2) a copy of thunk_sb_thumb (72 B, live cave bytes; two push+ret tails) with the gate widened to netwin || g_popup_active, redirected
  // from the grip blit site 0x6067ED. Arrow buttons are b=min(w,h) squares (auto); their chevron zoom = thunk_btn_shrink
  // under g_popup_active - verify in the run, else add the bar to pref_sbzoom's dynamic allowlist (g_rail_sb).
  (function applySbThumbPopup() {
    if (true) { log("SBTHUMB OFF (v15k): the heap bar is registered in g_rail_sb instead -> pref_sbzoom v6 armed path = netwin bracket (thunk_sb_thumb) + thunk_sb_restripe + btn_stripes v6 arrows; the bare copy NN-banded the grip/chevrons (1920 shot 152314 measured runs 1,2,1,1,2)"); return; }
    const site = 0x6067ED, thumb = PCAVE2 + 0x4BB0, G_NETWIN = PCAVE2 + 0x4800;
    const cur = new Uint8Array(VA(site).readByteArray(5)); const tgt = VA(site).add(5).add(new Int32Array(cur.buffer.slice(1, 5))[0]);
    if (cur[0] !== 0xE8 || !tgt.equals(VA(thumb))) { log("SBTHUMB SKIP: site " + hex(site) + " -> " + tgt + " (expected thunk_sb_thumb " + hex(thumb) + ")"); return; }
    const body = Array.from(new Uint8Array(VA(thumb).add(9).readByteArray(63)));                     // after `cmp [netwin],0; je +0x39`: 9..71 = gated body + BOTH tails (push scale_nn;ret @60, push Sprite_draw_2;ret @66 = the je/jle target). v15h copied 57 B and dropped the second tail -> the gated-off path (first bar at boot) fell off the stub into zeros: hard crash (log 22:14 eip=stub+0x4b)
    const le = v => [v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF];
    const code = [0x83, 0x3d, ...le(G_NETWIN), 0x00, 0x75, 0x09, 0x83, 0x3d, ...le(PCAVE2 + 0x530), 0x00, 0x74, 0x39, ...body]   // g_popup_active (G_POPUP_ACTIVE is declared later: TDZ);
    if (body.length !== 63 || body[56] !== 0xC3 || body[62] !== 0xC3 || body[57] !== 0x68 || body[0] !== 0xA1) { log("SBTHUMB SKIP: unexpected thunk body " + body.slice(0, 4).map(b => b.toString(16)).join(" ")); return; }
    const p = allocStub(code, {}, {});
    E_STUBS.push({ nm: "SBTHUMB", a: site, p, code: Array.from(new Uint8Array(p.readByteArray(code.length))) });
    Memory.patchCode(VA(site), 5, c => c.add(1).writeS32(p.toInt32() - (site + 5)));
    log("SBTHUMB grip-zoom @" + hex(site) + " -> " + p + " (thunk_sb_thumb copy gated netwin || g_popup_active)");
  })();
  (function applyNestChildxV2() {
    const edits = [["nestpads v2", PCAVE2 + 0x3770, [0x53, 0x8b, 0x1d, 0x40, 0x87, 0x66, 0x00, 0x83, 0xfb, 0x10, 0x7f, 0x07, 0xbb, 0x03, 0x00, 0x00, 0x00, 0xeb, 0x06, 0x8d, 0x1c, 0x5b, 0xc1, 0xeb, 0x04, 0x29, 0xd8, 0x01, 0xd9, 0x89, 0x45, 0xdc, 0x29, 0xda, 0x01, 0xdf, 0x5b, 0xc3, 0, 0],
        [83, 139, 29, 64, 135, 102, 0, 131, 251, 16, 127, 7, 187, 3, 0, 0, 0, 235, 8, 1, 219, 131, 195, 7, 193, 235, 4, 41, 216, 1, 217, 137, 69, 220, 41, 218, 1, 223, 91, 195]],
      ["orn_childx v2", PCAVE2 + 0xFB90, [0x52, 0xa1, 0x40, 0x87, 0x66, 0x00, 0x83, 0xf8, 0x10, 0x7e, 0x2f, 0x8b, 0x96, 0xac, 0x30, 0x00, 0x00, 0x81, 0xea, 0x20, 0x4e, 0x00, 0x00, 0x81, 0xfa, 0x10, 0x27, 0x00, 0x00, 0x72, 0x0e, 0x81, 0xea, 0x40, 0x9c, 0x00, 0x00, 0x81, 0xfa, 0x10, 0x27, 0x00, 0x00, 0x73, 0x0d, 0x8d, 0x14, 0x40, 0xc1, 0xfa, 0x04, 0x83, 0xea, 0x03, 0x01, 0x54, 0x24, 0x18, 0x5a, 0x83, 0xbe, 0x50, 0x23, 0x00, 0x00, 0xff, 0xc3, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [82, 161, 64, 135, 102, 0, 131, 248, 16, 126, 56, 139, 150, 172, 48, 0, 0, 129, 234, 32, 78, 0, 0, 129, 250, 16, 39, 0, 0, 114, 14, 129, 234, 64, 156, 0, 0, 129, 250, 16, 39, 0, 0, 115, 22, 131, 190, 224, 48, 0, 0, 0, 116, 13, 141, 20, 64, 193, 250, 4, 131, 234, 3, 1, 84, 36, 24, 90, 131, 190, 80, 35, 0, 0, 255, 195]]];
    for (const [nm, va, nat, code] of edits) {
      const cur = Array.from(new Uint8Array(VA(va).readByteArray(nat.length)));
      if (cur.join() !== nat.join()) { log("NESTCX SKIP " + nm + " @" + hex(va) + ": bytes differ: " + cur.map(b => b.toString(16)).join(" ")); continue; }
      Memory.patchCode(VA(va), code.length, c => c.writeByteArray(code));
      log("NESTCX " + nm + " patched in place @" + hex(va) + " (" + nat.length + " -> " + code.length + " B)");
    }
  })();
  // v15c LBRES (LAW listbox_bar_reserve, scaling_laws): the type-2 ListBox popup's scrollbar reserve. ListBox_calculate_
  // dimensions adds g_scrollbar_w (20) NATIVE to the dialog width w5c when the rows overflow (0x60A63D; multi-column twin
  // @0x60A614; the flags&2 per-column subtract @0x60A659) while every other term scales -> Select Special Ability
  // @1920: w5c 825+20 = 845 vs lawful 852, box 899 vs 907, frame R / rail zone squeezed by 20*(g/16-1) (hardware
  // watchpoint: writers 0x60A432 = 825, 0x60A640 = 845). Three call-helpers replace the g_scrollbar_w loads: load
  // live, then imul g / sar 4 when g_popup_active && g>16 (thunk_lbcalc_minw's gate; the global is SHARED - never a
  // literal 20). Each site is followed by add/sub or cdq/idiv, so the stub's flags are dead. Unicorn-checked
  // (scratch lbres_stub.py). UNGATED by DW (any listbox popup) - it is the popup family's law, baked with its own group.
  const LBRES_ECX = [139, 13, 212, 141, 155, 0, 131, 61, 48, 197, 160, 0, 0, 116, 19, 131, 61, 64, 135, 102, 0, 16, 126, 10, 15, 175, 13, 64, 135, 102, 0, 193, 249, 4, 195];
  const LBRES_EAX = [161, 212, 141, 155, 0, 131, 61, 48, 197, 160, 0, 0, 116, 19, 131, 61, 64, 135, 102, 0, 16, 126, 10, 15, 175, 5, 64, 135, 102, 0, 193, 248, 4, 195];
  const LBRES_EBP = [139, 45, 212, 141, 155, 0, 131, 61, 48, 197, 160, 0, 0, 116, 19, 131, 61, 64, 135, 102, 0, 16, 126, 10, 15, 175, 45, 64, 135, 102, 0, 193, 253, 4, 195];
  const LBRES_EDX = [139, 21, 212, 141, 155, 0, 131, 61, 48, 197, 160, 0, 0, 116, 19, 131, 61, 64, 135, 102, 0, 16, 126, 10, 15, 175, 21, 64, 135, 102, 0, 193, 250, 4, 195];
  // v15d: v15c scaled the reserve in the dialog width, but the WIN layer consumed it native again: the client<->window
  // conversions (flags 4/8 = has V/H bar; 0x5EEE95/AA add, 0x5EEF85/9A sub, 0x5EF066/7C add, 0x5EF126/3C sub), the
  // GraphicWin canvas/bar layout (0x5D503E, 0x5D51EB, 0x5D6246) and the Win bar creation (0x5EC342 ebp, 0x5EC3F5 ecx)
  // -> rows canvas 832 = 852-20 (lawful 825) and a 20-px rail window. Same helper family, same gate, every site is a
  // 5/6-byte load followed by mov/add/sub/test (flags dead). 13 sites total = every g_scrollbar_w consumer in the
  // popup-list path; ScrollBar_attach/init (0x6058AE/0x605938/0x605984, other classes; netwin thunks) and the wrap
  // budget (thunk_item_wrap_budget) are left as they are.
  (function installListboxReserve() {
    const L6 = r => [0x8b, r, 0xd4, 0x8d, 0x9b, 0x00];
    const sites = [["LBR1", 0x60A632, L6(0x0d), LBRES_ECX], ["LBR2", 0x60A609, L6(0x0d), LBRES_ECX], ["LBR3", 0x60A650, [0xa1, 0xd4, 0x8d, 0x9b, 0x00], LBRES_EAX],
      ["GW1", 0x5D503E, L6(0x0d), LBRES_ECX], ["GW2", 0x5D51EB, L6(0x0d), LBRES_ECX], ["GW3", 0x5D6246, L6(0x0d), LBRES_ECX], ["WC1", 0x5EC342, L6(0x2d), LBRES_EBP], ["WC2", 0x5EC3F5, L6(0x0d), LBRES_ECX],
      ["CV1", 0x5EEE95, L6(0x15), LBRES_EDX], ["CV2", 0x5EEEAA, L6(0x15), LBRES_EDX], ["CV3", 0x5EEF85, L6(0x15), LBRES_EDX], ["CV4", 0x5EEF9A, L6(0x15), LBRES_EDX],
      ["CV5", 0x5EF066, [0xa1, 0xd4, 0x8d, 0x9b, 0x00], LBRES_EAX], ["CV6", 0x5EF07C, L6(0x15), LBRES_EDX], ["CV7", 0x5EF126, [0xa1, 0xd4, 0x8d, 0x9b, 0x00], LBRES_EAX], ["CV8", 0x5EF13C, L6(0x15), LBRES_EDX],
      ["SBI", 0x6058E9, L6(0x15), LBRES_EDX],   // v15h: ScrollBar_init's bar-width arg (the HEAP bar the Win layer creates for listbox popups: user 4K shot 150640, 20-px bar)
      ["SBIV", 0x605938, [0xa1, 0xd4, 0x8d, 0x9b, 0x00], LBRES_EAX]];   // v15j: the VERTICAL variant ScrollBar_init_v 0x605910 (called @0x5EC427 for the Win V bar [+0x43c]) loads its WIDTH here; 0x6058E9 is the H variant's height. v15i shot 151737: bar still 20 wide at x=clientW inside the 50-px reserve
    const stubs2 = {};
    for (const [nm, site, nat, code] of sites) {
      const cur = Array.from(new Uint8Array(VA(site).readByteArray(nat.length)));
      if (cur.join() !== nat.join()) { log("LBRES SKIP " + nm + " @" + hex(site) + ": bytes " + cur.map(b => b.toString(16)).join(" ")); continue; }
      const key = code === LBRES_ECX ? "ecx" : code === LBRES_EAX ? "eax" : code === LBRES_EBP ? "ebp" : "edx";
      if (!stubs2[key]) { stubs2[key] = allocStub(code, {}, {}); E_STUBS.push({ nm: "LBRES_" + key, a: site, p: stubs2[key], code: Array.from(new Uint8Array(stubs2[key].readByteArray(code.length))) }); }
      const p = stubs2[key];
      Memory.patchCode(VA(site), nat.length, c => { c.writeU8(0xE8); c.add(1).writeS32(p.toInt32() - (site + 5)); for (let i = 5; i < nat.length; i++) c.add(i).writeU8(0x90); });
      log("LBRES " + nm + " @" + hex(site) + " -> " + p + " (g_scrollbar_w load scaled x g/16 when popup active & g>16)");
    }
  })();
  const jmpRel = (site, target, len) => { const b = [0xE9]; const rel = (target.toInt32() - (site + 5)) | 0; for (let i = 0; i < 4; i++) b.push((rel >>> (8 * i)) & 0xFF); while (b.length < len) b.push(0x90); return b; };
  const le32 = p => { const v = p.toInt32(); return [v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF]; };
  log("STUBS shim=" + stubs.shim + " cell=" + stubs.cell + " click=" + stubs.click + " frame=" + stubs.frame + " data=" + stubData);
  applyFootprint();
  verifyStubPages("load");
  let caviarShim = null;
  function installCaviarShim() {
    if (caviarShim) return;
    try {
      const cur = new Uint8Array(VA(A_COMPOSITE).readByteArray(5));
      const tgt = VA(A_COMPOSITE_RET).add(new Int32Array(cur.buffer.slice(1, 5))[0]);
      if (cur[0] !== 0xE8 || !tgt.equals(VA(A_BUFFER_DRAW_2))) { log("SHIM SKIP: composite site is not E8 Buffer_draw_2 (" + Array.from(cur).map(b => b.toString(16)).join(" ") + ")"); return; }
      Memory.patchCode(VA(A_COMPOSITE), 5, code => { code.writeU8(0xE8); code.add(1).writeS32(stubs.shim.sub(VA(A_COMPOSITE_RET)).toInt32()); });
      caviarShim = stubs.shim;
      fitW.writeU32(16 * g); fitOff.writeS32(8 * g - TN / 2);
      log("SHIM Caviar composite @" + hex(A_COMPOSITE) + " -> " + stubs.shim + " (gate dst==DW canvas " + hex(DW_CANVAS) + " || dst==picker canvas, g>16; blit thunk_keyed_stretch_blit src 256^2 -> dst (X-[fitOff], Y-[fitOff], [fitW] sq); [fitW]=0 suppresses)");
      const ob = new Uint8Array(VA(A_OVL_BLIT).readByteArray(5));
      const otgt = VA(A_OVL_BLIT).add(5).add(new Int32Array(ob.buffer.slice(1, 5))[0]);
      if (ob[0] !== 0xE8 || !otgt.equals(VA(A_OVL_BLIT_TGT))) log("OVL SKIP: overlay blit site is not E8 " + hex(A_OVL_BLIT_TGT) + " (" + Array.from(ob).map(b => b.toString(16)).join(" ") + ")");
      else { Memory.patchCode(VA(A_OVL_BLIT), 5, code => code.add(1).writeS32(stubs.ovl.sub(VA(A_OVL_BLIT).add(5)).toInt32())); ovlShim = stubs.ovl; log("OVL Caviar_overlay blit @" + hex(A_OVL_BLIT) + " -> one-shot stub " + stubs.ovl + " -> " + hex(A_OVL_BLIT_TGT) + " (armed per gated overlay draw: X,Y-=[OFF], num/den=[NUM]/[DEN])"); }
    } catch (e) { log("SHIM ERROR " + e + "\n" + (e.stack || "")); }
  }
  // --- FIT / SSAA: Caviar_draw entry hook (engine fn; hooked since v6). Every gated draw first does a
  // TRIAL render at native zoom with the composite suppressed (measure, don't model: the rasterizer's
  // result bbox ctx+8..+0x14 gives the native extent E at THIS angle), then the real render at zoom*k.
  const cvDraw = new NativeFunction(VA(0x617230), "int", ["pointer", "pointer", "int", "int", "int"], "thiscall");
  const cvReset = new NativeFunction(VA(0x618470), "void", ["pointer", "int"], "thiscall");
  const cvFill2 = new NativeFunction(VA(0x5DFB50), "void", ["pointer", "int"], "thiscall");   // Buffer_fill_2(self, colour): whole buffer
  const ctxBBox = () => { const c = VA(CV_CTX).readPointer(); return [safeS32(c.add(8)), safeS32(c.add(0xC)), safeS32(c.add(0x10)) + 1, safeS32(c.add(0x14)) + 1]; };
  const CV_MINX = 0x9B9690, CV_MINY = 0x9B9694, CV_MAXX = 0x9B9698, CV_MAXY = 0x9B969C, CV_PLANE = 0x9B9100, CV_BUF = 0x9B9108, CV_BUF2 = 0x9B96B0;
  const cvRect = () => [safeS32(VA(CV_MINX)), safeS32(VA(CV_MINY)), safeS32(VA(CV_MAXX)), safeS32(VA(CV_MAXY))];
  const cvSite = {}; let cvDraws = 0, cvClamps = 0, cvBufLogged = false, trialDepth = 0, fitMsSum = 0, fitMsN = 0;
  // v12b: Caviar_draw's tail ALWAYS Buffer_fills the target with key 9 (Caviar_reset, both args) before it
  // returns, so an SSAA composite at onLeave reads an empty target ("ssaa px=0" = the missing chassis +
  // reactor icons, user shot 201806). The composite therefore runs at the Caviar_reset ENTRY of the real draw.
  let ssaaPending = null;
  let ssaaMsSum = 0, ssaaMsN = 0, colorTabDumped = false, ssaaZeroLogs = 0;
  function ssaaComposite(dstPtr, x, y, W) {
    const t0 = Date.now();
    const src = bufInfo(VA(CV_BUF)); if (src.data.isNull()) return -1;
    const dst = bufInfo(dstPtr); if (dst.data.isNull()) return -2;
    const cl = [0, 4, 8, 12].map(o => safeS32(dstPtr.add(0x20 + o)));
    const L = Math.max(0, cl[0]), T = Math.max(0, cl[1]), R = Math.min(dst.w, cl[2]), B = Math.min(dst.h, cl[3]);
    const bb = ctxBBox(); const sx0 = Math.max(0, bb[0]), sy0 = Math.max(0, bb[1]), sx1 = Math.min(TN - 1, bb[2]), sy1 = Math.min(TN - 1, bb[3]);
    if (sx1 < sx0 || sy1 < sy0) return 0;
    const wrote = ssaaNative(src.data, src.pitch, TN, dst.data, dst.pitch, L, T, R, B, x - (W >> 1), y - (W >> 1), W, VA(G_PALETTE), ssaaInvBuf, KEY, sx0, sy0, sx1, sy1);
    if (wrote === 0 && ssaaZeroLogs++ < 12) {                                       // v14i: why did a composite write nothing?
      let nonkey = 0; for (let yy = sy0; yy <= sy1; yy += 4) { const row = new Uint8Array(src.data.add(yy * src.pitch + sx0).readByteArray(sx1 - sx0 + 1)); for (let i = 0; i < row.length; i += 2) if (row[i] !== KEY) nonkey++; }
      let zff = 0, zn = 0; try { const zb = safeU32(VA(CV_PLANE)); for (let yy = sy0; yy <= sy1; yy += 4) { for (let xx = sx0; xx <= sx1; xx += 4) { const z = ptr(zb).add((yy * TN + xx) * 2).readU16(); zn++; if (z === 0xFFFF) zff++; } } } catch (e) { zff = -1; }
      let rampS = "?"; try { const ctxp = safeU32(VA(0x9BB478)), rp = safeU32(ptr(ctxp).add(0x50)); rampS = hex(rp) + " row12[40..48]=" + Array.from(new Uint8Array(ptr(rp).add(12 * 256 + 40).readByteArray(8))).join(",") + " cur=" + hex(safeU32(VA(0x9BB470))) + " curflags=" + hex(safeU32(ptr(safeU32(VA(0x9BB470)) || 4).add(4))); } catch (e) { rampS = "err " + e; }
      log("SSAA ZERO: z-plane in bbox: " + zff + "/" + zn + " == 0xFFFF (untouched) | ramp " + rampS);
      log("SSAA ZERO: bbox " + [sx0, sy0, sx1, sy1].join(",") + " nonkey(sampled)=" + nonkey + " dst " + dst.w + "x" + dst.h + " clip " + [L, T, R, B].join(",") + " left/top " + (x - (W >> 1)) + "," + (y - (W >> 1)) + " W=" + W + " dirty " + cvRect().join(",") + " reset-from " + (ssaaPending ? hex(ssaaPending.resetRet) + " arg=" + ssaaPending.resetArg : "?"));
    }
    ssaaMsSum += Date.now() - t0; ssaaMsN++;
    return wrote;
  }
  Interceptor.attach(VA(0x617230), {
    onEnter() {
      if (!dwActive) return;
      if (trialDepth > 0) { this.trial = true; return; }
      this.on = true; this.ret = this.context.esp.readU32(); this.cv = this.context.ecx;
      this.dst = safeU32(this.context.esp.add(4)); this.x = safeS32(this.context.esp.add(8)); this.y = safeS32(this.context.esp.add(12)); this.flag = safeS32(this.context.esp.add(16));
      this.ovl = (this.flag & 8) !== 0 && this.ret === A_OVL_RET;   // v14t: Caviar_overlay's inner draw (its own table blit follows the return)
      ovlData.writeU32(0);                                            // disarm the one-shot stub before every draw
      if (!cvBufLogged) { cvBufLogged = true; for (const b of [CV_BUF, CV_BUF2]) { const bi = bufInfo(VA(b)); log("CAVIAR target " + hex(b) + " " + bi.w + "x" + bi.h + " pitch " + bi.pitch + " plane=" + hex(safeU32(VA(CV_PLANE))) + " (malloc 0x20000 = 256x256x2)"); } }
      let W = TN * g / 16, k = 1, mode = "nn", E = 0, bbN = null, bg = -1;
      const gated = g > 16 && (this.dst === DW_CANVAS || (pickerCanvas !== 0 && this.dst === pickerCanvas));
      gatedActive = gated && (FIT || SSAA); plotFull = 0; plotClip = 0;
      this.z = safeF32(this.cv.add(0xD5));
      if (gated && (FIT || SSAA) && this.z > 0) {
        const t0 = Date.now();
        // the trial must leave the object as it found it: Caviar_draw mutates +0x14..+0x101 (dst/model
        // slots, the flag&4 centring `+0x2c.. -= centre` accumulator, +0xa4, the clip fields) -> snapshot
        // the header around the trial, then reset(0) so the target/z-plane are clean for the real render.
        const snap = this.cv.add(0x14).readByteArray(0x100);
        fitW.writeU32(0); trialDepth++;
        if (this.ovl) { try { const tb = bufInfo(VA(CV_BUF)); if (!tb.data.isNull()) bg = tb.data.readU8(); } catch (e) { log("OVL bg read err " + e); } }   // the wrapper's bg fill (pixel 0,0)
        try { cvDraw(this.cv, ptr(this.dst), this.x, this.y, this.flag); cvReset(this.cv, 0); if (this.ovl && bg >= 0) cvFill2(VA(CV_BUF), bg); } catch (e) { log("FIT trial error " + e); }   // v14t: reset(0) refills with key 9 -> restore the overlay's bg key
        trialDepth--;
        this.cv.add(0x14).writeByteArray(snap);
        bbN = ctxBBox(); E = Math.max(1, bbN[2] - bbN[0], bbN[3] - bbN[1]);
        fitMsSum += Date.now() - t0; fitMsN++;
        // v14s LAW dw_fit_plan (scaling_laws): RADIAL constraint about the target centre — the extent law let the
        // Rover Formers crane (E=158, far edge 104 px off-centre) cross the 1024 target at x5 -> clipped plotter twin
        // (vanilla 2x2) -> see-through arm (shot 020648). SSAA factor now eases from 2 down to 1 instead of popping.
        const plan = SL.dwFitPlan(bbN, TN, g, SSAA && !this.ovl, FIT); k = plan.k; W = plan.W; mode = plan.mode; this.planR = plan.R;   // v14t: overlay draws never ssaa (table blit)
        if (mode !== "nn") { this.savedZoom = this.z; this.cv.add(0xD5).writeFloat(this.z * k); }
      }
      this.k = k; this.W = W; this.mode = mode; this.E = E; this.bbN = bbN; this.gated = gated;
      if (this.ovl && gated) {                                        // v14t: arm the one-shot overlay-blit stub for this draw
        const d = gcd(W, TN); this.ovlBg = bg; this.ovlNum = W / d; this.ovlDen = TN / d;
        ovlData.add(4).writeS32(Math.floor(W / 2) - TN / 2); ovlData.add(8).writeU32(this.ovlNum); ovlData.add(12).writeU32(this.ovlDen);
        if (ovlShim) ovlData.writeU32(1); else if ((ovlNoShimLogs = (ovlNoShimLogs || 0) + 1) <= 3) log("OVL: gated overlay draw but the blit stub is not installed (ret " + hex(this.ret) + ")");
      }
      curDraw = { ret: this.ret, cv: this.cv, z: this.z, k, W, mode };
      if (mode === "ssaa") { fitW.writeU32(0); this.ssaa = true; ssaaPending = { cv: this.cv, dst: this.dst, x: this.x, y: this.y, W, n: -8, done: false }; }
      else { fitW.writeU32(W); fitOff.writeS32(Math.floor(W / 2) - TN / 2); }
    },
    onLeave() {
      if (this.trial || !this.on) return;
      gatedActive = false;
      if (this.ovl && this.gated && ovlLogs++ < 8) log("OVL draw ret=" + hex(this.ret) + " bg=" + this.ovlBg + " mode=" + this.mode + " k=" + this.k.toFixed(3) + " W=" + this.W + " -> blit num/den " + this.ovlNum + "/" + this.ovlDen + " off " + (Math.floor(this.W / 2) - TN / 2) + " armed=" + ovlData.readU32());
      if (this.savedZoom !== undefined) this.cv.add(0xD5).writeFloat(this.savedZoom);
      cvDraws++;
      const bb = ctxBBox(), clipped = bb[0] < 0 || bb[1] < 0 || bb[2] > TN || bb[3] > TN;
      let ssaaN = -9;
      if (this.ssaa) { if (ssaaPending && !ssaaPending.done) log("SSAA UNCONSUMED (no Caviar_reset inside the draw?) ret=" + hex(this.ret)); ssaaN = ssaaPending ? ssaaPending.n : -7; ssaaPending = null; }
      const r = cvRect(), w = r[2] - r[0], h = r[3] - r[1], key = hex(this.ret);
      const st = cvSite[key] || (cvSite[key] = { n: 0, maxw: 0, maxh: 0, maxx: 0, maxy: 0, minx: 1e9, miny: 1e9, clipped: 0, modes: {} });
      st.n++; st.maxw = Math.max(st.maxw, w); st.maxh = Math.max(st.maxh, h); st.maxx = Math.max(st.maxx, r[2]); st.maxy = Math.max(st.maxy, r[3]); st.minx = Math.min(st.minx, r[0]); st.miny = Math.min(st.miny, r[1]);
      if (clipped) st.clipped++; st.modes[this.mode] = (st.modes[this.mode] || 0) + 1;
      if (st.n <= 3 || clipped || cvDraws % 100 === 0)
        log("FIT draw ret=" + key + " obj=" + hex(this.cv.toInt32()) + " dst=" + hex(this.dst) + " at " + this.x + "," + this.y + " flag=" + this.flag + " zoom=" + this.z.toFixed(4) +
            (this.gated ? " | trial bbox " + (this.bbN ? this.bbN.join(",") : "-") + " E=" + this.E + " R=" + (this.planR === undefined ? "-" : this.planR.toFixed(0)) + " -> mode=" + this.mode + " k=" + this.k.toFixed(3) + " W=" + this.W + " zoom'=" + (this.z * this.k).toFixed(4) : " | ungated") +
            " | real bbox " + bb.join(",") + (clipped ? " *** CLIPPED ***" : "") + (this.ssaa ? " ssaa px=" + ssaaN : "") + " dirty=(" + r.join(",") + ")" + (this.gated ? " plot full=" + plotFull + " clip=" + plotClip + (lastClipLog ? " ctxclip " + lastClipLog : "") : ""));
    }
  });
  let gatedActive = false, plotFull = 0, plotClip = 0, lastClipLog = "", clipOverrides = 0, ovlLogs = 0, ovlNoShimLogs = 0;
  // v14c: Caviar_draw builds the ctx clip (+0x38..+0x4C) as IntersectRect(composite window, dst clip rect)
  // mapped 1:1 into target space - with the TN target and a W<TN composite that clip is too small (a tall
  // unit crosses it near the top of the preview) and any part crossing it is rasterized by the CLIPPED
  // plotter twin 0x664000 (vanilla 2x2). For gated draws the FIT law guarantees the model fits the target
  // and the composite clips against dst itself -> give the rasterizer the whole target (what Caviar_draw
  // computes when the dst clip is unbounded: L=T=0, R=B=W=H=TN).
  Interceptor.attach(VA(0x639E60), {
    onEnter() {
      if (!gatedActive) return;
      const ctx = safeU32(VA(0x9BB478)); if (!ctx) return;
      const c = ptr(ctx), cur = [0x38, 0x3C, 0x40, 0x44, 0x48, 0x4C].map(o => safeS32(c.add(o)));
      const ov = [0x9C0B08, 0x9C0B0C, 0x9C0B10, 0x9C0B14, 0x9C0B18, 0x9C0B1C].map(a => safeS32(VA(a)));
      lastClipLog = cur.join(",") + (trialDepth ? "(trial)" : "") + " ov " + ov.join(",");
      if (cur[0] !== 0 || cur[1] !== 0 || cur[2] !== TN || cur[3] !== TN) {
        clipOverrides++;
        if (clipOverrides <= 6 || clipOverrides % 500 === 0) log("CLIP override #" + clipOverrides + " ctx clip " + cur.join(",") + " -> 0,0," + TN + "," + TN + (trialDepth ? " (trial)" : ""));
        c.add(0x38).writeS32(0); c.add(0x3C).writeS32(0); c.add(0x40).writeS32(TN); c.add(0x44).writeS32(TN); c.add(0x48).writeS32(TN); c.add(0x4C).writeS32(TN);
      }
    }
  });
  Interceptor.attach(VA(0x6647F0), { onEnter() { plotFull++; } });                    // v14c: 8-bit plotter twins - which one each part took
  Interceptor.attach(VA(0x664000), { onEnter() { plotClip++; if (gatedActive && trialDepth === 0 && plotClip <= 3) log("PLOT CLIPPED twin used by a gated part (2x2 footprint) #" + plotClip); } });
  Interceptor.attach(VA(0x63E950), {                                                  // v14: Caviar_rasterize_part entry -> is this a gated part?
    onEnter() {
      if (!fpArmed) return;
      fpGatedPart = trialDepth === 0 && !!curDraw && curDraw.mode !== "nn";
      this.prod = fpGatedPart ? this.context.esp.add(4 + 6 * 4).readFloat() * safeF32(VA(0x9C0B00)) : 0;
      lastProd = this.prod;
      if ((!fpGatedPart && fpCur !== "2x2") || stubData.add(FP.DEND).readU32() === 0) fpSet(2, 2);   // v14k: DEND must be valid BEFORE any block (was 0 until the first non-2x2 part -> nothing plotted)
    }
  });
  let lastProd = 0;
  // v14d: the footprint is the PROJECTED voxel cube's bbox, per screen axis and per pose: 0x63FA80 leaves the
  // part matrix (rotation x partScale x zoom) as 8.8 ints - screen-x row 0x9C0A40/42/44, screen-y row
  // 0x9C0A46/48/4A (shorts), depth row 0x9C0A4C/50/54 - and 0x6404F0 (called next, before the plot) builds the
  // run tables from them. nx = ceil(sum|x row|/256), ny = ceil(sum|y row|/256): lattice neighbours (one axis
  // step) and diagonal neighbours (two) are both covered, at every rotation. n = ceil(zoom*partScale) (v14b)
  // was the axis-aligned spacing only -> 1-2 px gaps opened at oblique angles ("pixels poking through").
  Interceptor.attach(VA(0x6404F0), {
    onEnter() {
      if (!fpArmed || !fpGatedPart) return;
      const r = o => VA(0x9C0A40 + o).readS16();
      const fx = (Math.abs(r(0)) + Math.abs(r(2)) + Math.abs(r(4))) / 256, fy = (Math.abs(r(6)) + Math.abs(r(8)) + Math.abs(r(10))) / 256;
      const nx = Math.min(8, Math.max(2, Math.ceil(fx - 1e-3))), ny = Math.min(8, Math.max(2, Math.ceil(fy - 1e-3)));
      const key = nx + "x" + ny; fpStats[key] = (fpStats[key] || 0) + 1;
      if (fpStats[key] <= 2 || fpStats[key] % 1000 === 0) log("FP part prod=" + lastProd.toFixed(2) + " projected voxel fx=" + fx.toFixed(2) + " fy=" + fy.toFixed(2) + " -> " + key + " (draw ret=" + hex(curDraw.ret) + " mode=" + curDraw.mode + ")");
      if (key !== fpCur || stubData.add(FP.DEND).readU32() === 0) fpSet(nx, ny);
    }
  });
  Interceptor.attach(VA(0x618470), {                                                  // Caviar_reset entry: SSAA composite (target still intact) + clamp the dirty rect
    onEnter() {
      if (dumpLeft > 0 && curDraw && curDraw.ret === 0x436302 && trialDepth === 0 && this.context.ecx.equals(curDraw.cv)) { if (DUMP_SKIP > 0) { DUMP_SKIP--; if (DUMP_SKIP === 0) log("DUMP starting now"); } else dumpFrame(); curDraw = null; }
      if (ssaaPending && !ssaaPending.done && this.context.ecx.equals(ssaaPending.cv)) {
        ssaaPending.done = true; ssaaPending.resetRet = this.context.esp.readU32(); ssaaPending.resetArg = safeS32(this.context.esp.add(4));
        if (!colorTabDumped) { colorTabDumped = true; try { const f = new File("D:/SmacxUi/work/_dw_crops/v14/colortab.raw", "wb"); const ctxp = safeU32(VA(0x9BB478)), ramp = ctxp ? safeU32(ptr(ctxp).add(0x50)) : 0; if (!ramp) throw new Error("no ctx ramp"); f.write(ptr(ramp).readByteArray(0x1800)); f.close(); log("DUMP ramp table from ctx+0x50 = " + hex(ramp) + " (0x9BE6BC=" + hex(safeU32(VA(0x9BE6BC))) + ")"); const pf = new File("D:/SmacxUi/work/_dw_crops/v14/palette.raw", "wb"); pf.write(VA(G_PALETTE).readByteArray(1024)); pf.close(); log("DUMP colortab 24x256 + palette -> _dw_crops/v14"); } catch (e) { log("DUMP colortab err " + e); } }
        try { ssaaPending.n = ssaaComposite(ptr(ssaaPending.dst), ssaaPending.x, ssaaPending.y, ssaaPending.W); } catch (e) { log("SSAA error " + e + "\n" + (e.stack || "")); }
      }
      const r = cvRect();
      if (r[0] < 0 || r[1] < 0 || r[2] > TN || r[3] > TN) {
        cvClamps++;
        if (cvClamps <= 6 || cvClamps % 100 === 0) log("CAVIAR CLAMP #" + cvClamps + " reset(arg=" + safeS32(this.context.esp.add(4)) + ") dirty=(" + r.join(",") + ") -> [0,256)");
        VA(CV_MINX).writeS32(Math.max(0, Math.min(TN, r[0]))); VA(CV_MINY).writeS32(Math.max(0, Math.min(TN, r[1])));
        VA(CV_MAXX).writeS32(Math.max(0, Math.min(TN, r[2]))); VA(CV_MAXY).writeS32(Math.max(0, Math.min(TN, r[3])));
      }
    }
  });
  for (const [name, va] of []) {                                                    // v8: painter brackets off
    Interceptor.attach(VA(va), {
      onEnter() {
        if (!dwActive) return;
        this.on = true;
        const n = (thunkSeen[name] = (thunkSeen[name] || 0) + 1);
        if (n <= 6) log("ENTER " + name + " #" + n + (name === "slot_strip" ? " hovered=" + safeS32(VA(G_OBJ).add(0xCE0)) + " unit=" + safeS32(VA(G_OBJ).add(0x141F8)) : ""));
        heapCheck("enter " + name + " #" + n, true);
      },
      onLeave() { if (this.on) heapCheck("leave " + name + " #" + thunkSeen[name], true); }
    });
  }
  // ---------------------------------------------------------------------------
  // v12 PART PICKER (stack PartPicker, exec 0x433F70; see header). Entry hooks only; the geometry
  // levers are immediates/stubs applied with the rest of P at first exec.
  // ---------------------------------------------------------------------------
  const T_RAIL_GATE = PCAVE2 + 0x11200, G_POPUP_ACTIVE = PCAVE2 + 0x530;
  let railGateOff = -1, pickerObj = 0, pickerN = 0;
  function railGateImm(val) {
    const b = new Uint8Array(VA(T_RAIL_GATE).readByteArray(32));
    if (railGateOff < 0) for (let i = 0; i < 28; i++) if (b[i] === 0x44 && b[i + 1] === 0x80 && b[i + 2] === 0x6A && b[i + 3] === 0x00) { railGateOff = i; break; }
    if (railGateOff < 0) { log("RAILGATE: ProdPicker imm not found in thunk_rail_gate: " + Array.from(b).map(x => x.toString(16).padStart(2, "0")).join(" ")); return; }
    Memory.patchCode(VA(T_RAIL_GATE + railGateOff), 4, c => c.writeU32(val >>> 0));
    log("RAILGATE thunk_rail_gate imm @+" + railGateOff + " = " + hex(val));
  }
  const pickerCellRect = (t, idx) => {
    const first = safeS32(t.add(0x2B60)), cols = Math.max(1, safeS32(t.add(0x2B6C))), rel = idx - first, row = Math.floor(rel / cols), col = rel % cols;
    return [s(col * 108 + 27), s(row * 94 + 4), s(col * 108 + 132), s(row * 94 + 95)];
  };
  let wheelPicker = 0, wheelN = 0;                                                    // v14t: live PartPicker for the wheel->chevron hook (UNGATED: vanilla behaviour change)
  Interceptor.attach(VA(0x433F70), {                                                  // PartPicker_exec entry (probe host since the static map)
    onEnter() {
      wheelPicker = this.context.ecx.toInt32(); this.wheel = true;
      if (!dwActive || g <= 16) return;
      this.on = true; pickerN++;
      pickerObj = this.context.ecx.toInt32(); pickerCanvas = (pickerObj + 0x444) >>> 0; pickerSlot.writeU32(pickerCanvas);
      const a = [4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44].map(o => safeS32(this.context.esp.add(o)));
      log("PICKER #" + pickerN + " exec obj=" + hex(pickerObj) + " canvas=" + hex(pickerCanvas) + " args x=" + a[0] + " y=" + a[1] + " faction=" + a[2] + " type=" + a[3] + " cur=" + a[4] + " parts=" + a.slice(5, 10).join(",") + " | tile 0x6B33F8 " + spriteStr(VA(0x6B33F8)) + " | canvas dims " + safeS32(VA(0x71F774)) + "x" + (-safeS32(VA(0x71F778))));
      railGateImm(pickerObj);
      if (ARM_POPUP_ACTIVE) { VA(G_POPUP_ACTIVE).writeS32(safeS32(VA(G_POPUP_ACTIVE)) + 1); log("PICKER g_popup_active -> " + safeS32(VA(G_POPUP_ACTIVE))); }
      heapCheck("picker-enter");
      pickerDrawn = false; lastHoverIdx = -1; setTimeout(() => { pickerDrawn = true; log("PICKER census armed (hover now)"); }, 1500);
    },
    onLeave() {
      if (this.wheel) wheelPicker = 0;
      if (!this.on) return;
      const win = ptr(pickerObj);
      log("PICKER #" + pickerN + " leave result=" + this.context.eax.toInt32() + " sel=" + safeS32(win.add(0x2B80)) + " first=" + safeS32(win.add(0x2B60)) + " count=" + safeS32(win.add(0x2B74)) + " vis=" + safeS32(win.add(0x2B64)) + " cols=" + safeS32(win.add(0x2B6C)) +
          " | win rect " + [0x30, 0x34, 0x38, 0x3C].map(o => safeS32(win.add(o))).join(",") + " | sb rect " + [0x30, 0x34, 0x38, 0x3C].map(o => safeS32(win.add(0xA14 + o))).join(","));
      if (ARM_POPUP_ACTIVE) { const v = safeS32(VA(G_POPUP_ACTIVE)); VA(G_POPUP_ACTIVE).writeS32(Math.max(0, v - 1)); }
      railGateImm(0x6A8044);
      pickerCanvas = 0; pickerSlot.writeU32(0); pickerObj = 0;
      heapCheck("picker-leave");
    }
  });
  let cellLogs = 0, leaveFixN = 0;
  Interceptor.attach(VA(0x433D60), {                                                  // PartPicker_draw_cell (plain thiscall; no PRACX/patch site inside)
    onEnter() {
      if (!dwActive || g <= 16 || !pickerObj) return;
      const t = this.context.ecx; this.t = t; this.idx = safeS32(this.context.esp.add(4)); this.sel = safeS32(this.context.esp.add(8));
      this.clipIn = rect4(t.add(0x444 + 0x20)); this.hoverEvt = pickerDrawn;   // v14h: after the first full draw, sel=1 draws + the unhover redraw
      const first = safeS32(t.add(0x2B60)), vis = safeS32(t.add(0x2B64)), count = safeS32(t.add(0x2B74));
      this.inRange = this.idx >= first && this.idx < first + vis; this.empty = this.inRange && this.idx >= count; this.on = true;
      this.ret = this.returnAddress.toInt32();
    },
    onLeave() {
      if (!this.on) return;
      // v14q GRID-LEAVE PRESENT: vanilla on_click 0x433820 un-hovers the last cell when the pointer leaves the grid (or
      // lands on an empty slot) via the 0x433905 path -> draw_cell(hover,0) @0x433914 -> hover=-1 -> ret, WITHOUT the
      // vtbl+0xFC present the in-grid path (0x4338F8) does. The canvas is right but the display keeps the hover until
      // some other present covers it; at 4K only the preview's 30 fps recomposite (x<2308) does, leaving the 13-px
      // strip outside it stale. Present the window right after that draw. (Bake: thunk the 0x433914 call site.)
      if (this.sel === 0 && this.ret === 0x433919) {
        try { const fn = this.t.readPointer().add(0xFC).readPointer(); new NativeFunction(fn, "void", ["pointer"], "thiscall")(this.t); leaveFixN++; if (leaveFixN <= 6) log("LEAVEFIX present after grid-leave unhover idx=" + this.idx + " (draw ret " + hex(this.ret) + ")"); }
        catch (e) { log("LEAVEFIX err " + e); }
      } else if (this.sel === 0 && leaveFixN <= 6 && this.ret !== 0x4338EE && this.ret !== 0x4339EC && this.ret !== 0x433CA2 && this.ret !== 0x433CB2 && this.ret !== 0x434370 /* full repaint */) log("LEAVEFIX note: sel=0 draw from unlisted ret " + hex(this.ret));
      if (!this.inRange) return;
      const r = pickerCellRect(this.t, this.idx);
      if (cellLogs++ < 8) log("PICKER cell idx=" + this.idx + " sel=" + this.sel + (this.empty ? " EMPTY(tile)" : "") + " law rect " + r.join(","));
      if (this.empty) { try { restripeHoverCell(this.t.add(0x444), r, 0, "tile"); } catch (e) { log("PICKER tile restripe err " + e); } }
      if (this.hoverEvt && hoverCensus++ < 40) {                                    // v14h: which columns did this draw (re)paint?
        try {
          const bi = bufInfo(this.t.add(0x444)), K = SL.strokeWidth(g), y0 = r[1] + K + 2, y1 = r[3] - K - 2;
          const colDom = x => { const c = new Map(); for (let y = y0; y < y1; y += 2) { const v = bi.data.add(y * bi.pitch + x).readU8(); c.set(v, (c.get(v) || 0) + 1); } return [...c.entries()].sort((p, q) => q[1] - p[1]).slice(0, 2).map(e => e[0]).join("/"); };
          const runs = (xa, xb) => { const out = []; let cur = null, n = 0; for (let x = xa; x < xb; x++) { const d = colDom(x); if (d === cur) n++; else { if (cur !== null) out.push(cur + "x" + n); cur = d; n = 1; } } out.push(cur + "x" + n); return out.join(" "); };
          log("CELLCENSUS idx=" + this.idx + " sel=" + this.sel + " lastHover=" + lastHoverIdx + " law " + r.join(",") + " clipIn " + this.clipIn.join(",") + " clipNow " + rect4(this.t.add(0x444 + 0x20)).join(",") +
              " | L[" + r[0] + ".." + (r[0] + 24) + ") " + runs(r[0], r[0] + 24) + " | R[" + (r[2] - 24) + ".." + r[2] + ") " + runs(r[2] - 24, r[2]) + " | T rows " + [r[1], r[1] + 1, r[1] + 2, r[1] + 8, r[1] + 14].map(y => bi.data.add(y * bi.pitch + r[0] + 40).readU8()).join(",") + " | B rows " + [r[3] - 15, r[3] - 9, r[3] - 3, r[3] - 2, r[3] - 1].map(y => bi.data.add(y * bi.pitch + r[0] + 40).readU8()).join(","));
        } catch (e) { log("CELLCENSUS err " + e); }
      }
      if (this.sel === 1) lastHoverIdx = this.idx; else if (this.hoverEvt) lastUnhover = r;
    }
  });
  let hoverCensus = 0, lastHoverIdx = -1, pickerDrawn = false, lastUnhover = null, screenCensus = 0;
  let flipLogs = 0;
  Interceptor.attach(VA(0x5DFF00), {                                                  // v14l: Buffer_copy_4 = the screen->display flip at the tail of Win_update_screen; which rect actually reaches the display?
    onEnter() {
      if (!dwActive || g <= 16 || !pickerObj || !pickerDrawn || this.context.ecx.toInt32() !== 0x9B7490 || flipLogs++ >= 24) return;
      const a = [1, 2, 3, 4, 5, 6, 7].map(i => safeS32(this.context.esp.add(4 * i)));
      log("FLIP screen->display dst=" + hex(a[0]) + " src " + a[1] + "," + a[2] + " dst " + a[3] + "," + a[4] + " size " + a[5] + "x" + a[6] + (lastUnhover ? " | pending unhover cell " + lastUnhover.join(",") : ""));
    }
  });
  const localToScreen = new NativeFunction(VA(0x5ED240), "void", ["pointer", "pointer", "pointer"], "thiscall");   // GraphicWin_local_to_screen(this, int* x, int* y)
  Interceptor.attach(VA(0x5D56B0), {                                                  // v14k: window PRESENT (vtbl+0xFC -> 0x404290 -> here): after it, does the SCREEN buffer match the picker canvas?
    onEnter() { this.on = dwActive && g > 16 && !!pickerObj && pickerDrawn && this.context.ecx.toInt32() === pickerObj && !!lastUnhover; },
    onLeave() {
      if (!this.on || screenCensus++ >= 12) return;
      try {
        const win = ptr(pickerObj), r = lastUnhover, K = SL.strokeWidth(g);
        const px = Memory.alloc(8); RETAINED.push(px); px.writeS32(0); px.add(4).writeS32(0); localToScreen(win, px, px.add(4)); const sx = px.readS32(), sy = px.add(4).readS32();   // engine's own mapping (parent-relative child window)
        const scr = bufInfo(VA(0x9B7490)), cv = bufInfo(win.add(0x444)), y0 = r[1] + K + 2, y1 = r[3] - K - 2;   // 0x9B7490 = the screen surface Win_update_screen flips
        const dom = (bi, ox, oy, x) => { const c = new Map(); for (let y = y0; y < y1; y += 2) { const v = bi.data.add((oy + y) * bi.pitch + ox + x).readU8(); c.set(v, (c.get(v) || 0) + 1); } return [...c.entries()].sort((p, q) => q[1] - p[1]).slice(0, 2).map(e => e[0]).join("/"); };
        const runs = (bi, ox, oy) => { const out = []; let cur = null, n = 0; for (let x = r[2] - 24; x < r[2]; x++) { const d = dom(bi, ox, oy, x); if (d === cur) n++; else { if (cur !== null) out.push(cur + "x" + n); cur = d; n = 1; } } out.push(cur + "x" + n); return out.join(" "); };
        log("SCREENCENSUS after present: cell law " + r.join(",") + " win screen origin " + sx + "," + sy + " screenbuf " + scr.w + "x" + scr.h + " | canvas R: " + runs(cv, 0, 0) + " | screen R: " + runs(scr, sx, sy) + " | dirty 0x9b7a30 " + [0x9B7A30, 0x9B7A34, 0x9B7A40, 0x9B7A44].map(a => safeS32(VA(a))).join(","));
        log("PAINT counts: " + [...paintSeen.entries()].map(e => e[1] + "x " + e[0].replace("PAINT ", "")).join(" || ")); paintSeen.clear();
        displayCensus(r, sx, sy, "present-leave"); for (const ms of [150, 400, 900]) setTimeout(() => { try { displayCensus(r, sx, sy, "+" + ms + "ms"); } catch (e) { log("DISPLAYCENSUS err " + e); } }, ms);
        lastUnhover = null; pendTag = "cell " + r.join(",") + " screen " + [r[0] + sx, r[1] + sy, r[2] + sx, r[3] + sy].join(",") + " origin " + sx + "," + sy; pendUntil = Date.now() + 1500;
      } catch (e) { log("SCREENCENSUS err " + e); }
    }
  });
  // v14p: read the DISPLAY itself (GDI GetPixel on the screen DC, fullscreen => client origin 0,0) next to the screen DIB,
  // for the R frame band of the unhovered cell at one row: which surface carries the stale 13-px hover tail, and when?
  const u32m = Process.getModuleByName("user32.dll"), g32m = Process.getModuleByName("gdi32.dll");
  const GetDC = new NativeFunction(u32m.getExportByName("GetDC"), "pointer", ["pointer"]);
  // v14t WHEEL (VANILLA BEHAVIOUR CHANGE, user decision 2026-08-29; ungated): PRACX turns a wheel notch into posted
  // VK_UP/VK_DOWN WM_KEYDOWN/KEYUP pairs with lParam 0 (pracx.cpp:1183-1189) -> PartPicker_on_key moves the SELECTION
  // by a row and scrolls only as a side effect. Wanted: a notch = one chevron press. Proto: hook user32 PostMessageA/W at
  // the PRACX boundary; while a PartPicker is live, a synthetic KEYDOWN VK_UP/VK_DOWN becomes ScrollBar vtbl+0xB0
  // (0x606B20: value -+1 clamped to the range, notify picker vtbl+0xC0 = first_idx = cols*value + GraphicWin_redraw,
  // bar redraw; self-guarded when the bar is not engaged, count<=18) + picker vtbl+0xFC present, and the message (and
  // the matching KEYUP) is rewritten to WM_NULL. Real keys carry a scan code in lParam (bits 16-23) and pass untouched.
  // BAKE: exe-side detour in the engine's WM_KEYDOWN path with a generic engaged-ScrollBar-child walk (agent map pending).
  // v14u: the v14t PostMessage rewrite pressed the chevron from INSIDE a Frida callback -> the picker's whole redraw
  // (cells -> Caviar draws) ran with every Interceptor hook suppressed on that thread (Frida ignores hooks while a JS
  // callback runs) -> native-size icons until a hover redrew a cell normally (user 4K shot). Now the BAKE mechanism
  // itself: native thunks replacing `call Win_get_active_target` at WinProc's WM_KEYDOWN (0x5F07B0) and WM_KEYUP
  // (0x5F07F0) cases (agent map 2026-08-29; both sites live==.bak, outside PRACX's stomps; lParam is only alive here -
  // App_on_key_message never reads it). Thunk: call 0x5F6A50; if target && [esp+0x6C](lParam)==0 && wParam in
  // {VK_UP,VK_DOWN} && modal top [0x9B7AE0] is a PartPicker (sb +0xA14) or ProdPicker (sb +0x7120) with an engaged bar
  // (sb+0xC4 != 0, range max > min): KEYDOWN -> ScrollBar_on_chevron 0x606B20 (btn 1|2) + picker vtbl+0xFC present;
  // both -> eax=0 (WinProc skips the vtbl+0x138 dispatch). Real keys carry a scan code -> untouched. Emulated for every
  // branch (scratch wheel_stub.py). The PostMessage hook below is now LOG-ONLY.
  // v14x (user: the SELECT SPECIAL ABILITY list must wheel-scroll too, selection untouched): class table v2 (scratch
  // wheel_stub2.py, emulated every branch) — g_current_basepop [0x9B8D7C] is preferred over the modal top (the popup
  // is the basepop; [0x9B7AE0] is the popup only when [popup+0xA14]==0); Popup 0x6695C8 / 0x66A8A8 -> sb = [pop+0x2794]
  // (the list Win's +0x43C slot: the rail once the list overflows, the heap bar otherwise, 0 when the list fits);
  // FileDlg 0x669EC8 +0x3DD8, TextScroll 0x66ADC8 +0xA20, PrefWin sub-dialog 0x66C3D8 +0xEF0; PartPicker/ProdPicker
  // as before. ScrollBar_on_chevron clears [0x9B8DDC] -> ListBox_on_scrolling(id -1, value) moves ONLY the first
  // visible row (the key path sets it and drags the selection). Every class's vtbl+0xFC == 0x404290 present.
  const WHD_CODE = [232, 75, 106, 95, 240, 133, 192, 15, 132, 221, 0, 0, 0, 131, 124, 36, 108, 0, 15, 133, 210, 0, 0, 0, 139, 84, 36, 104, 131, 250, 38, 116, 9, 131, 250, 40, 15, 133, 192, 0, 0, 0, 83, 86, 87, 139, 53, 124, 141, 155, 0, 133, 246, 117, 14, 139, 53, 224, 122, 155, 0, 133, 246, 15, 132, 162, 0, 0, 0, 139, 14, 129, 249, 200, 149, 102, 0, 116, 80, 129, 249, 168, 168, 102, 0, 116, 72, 141, 190, 20, 10, 0, 0, 129, 249, 184, 178, 102, 0, 116, 68, 141, 190, 32, 113, 0, 0, 129, 249, 80, 162, 102, 0, 116, 54, 141, 190, 216, 61, 0, 0, 129, 249, 200, 158, 102, 0, 116, 40, 141, 190, 32, 10, 0, 0, 129, 249, 200, 173, 102, 0, 116, 26, 141, 190, 240, 14, 0, 0, 129, 249, 216, 195, 102, 0, 116, 12, 235, 72, 139, 190, 148, 39, 0, 0, 133, 255, 116, 62, 131, 191, 196, 0, 0, 0, 0, 116, 53, 139, 143, 36, 10, 0, 0, 59, 143, 32, 10, 0, 0, 126, 39, 187, 1, 0, 0, 0, 131, 250, 38, 116, 5, 187, 2, 0, 0, 0, 83, 137, 249, 232, 73, 106, 96, 240, 139, 22, 137, 241, 255, 146, 252, 0, 0, 0, 49, 192, 95, 94, 91, 195, 95, 94, 91, 195];
  const WHU_CODE = [232, 75, 106, 95, 240, 133, 192, 15, 132, 188, 0, 0, 0, 131, 124, 36, 108, 0, 15, 133, 177, 0, 0, 0, 139, 84, 36, 104, 131, 250, 38, 116, 9, 131, 250, 40, 15, 133, 159, 0, 0, 0, 83, 86, 87, 139, 53, 124, 141, 155, 0, 133, 246, 117, 14, 139, 53, 224, 122, 155, 0, 133, 246, 15, 132, 129, 0, 0, 0, 139, 14, 129, 249, 200, 149, 102, 0, 116, 80, 129, 249, 168, 168, 102, 0, 116, 72, 141, 190, 20, 10, 0, 0, 129, 249, 184, 178, 102, 0, 116, 68, 141, 190, 32, 113, 0, 0, 129, 249, 80, 162, 102, 0, 116, 54, 141, 190, 216, 61, 0, 0, 129, 249, 200, 158, 102, 0, 116, 40, 141, 190, 32, 10, 0, 0, 129, 249, 200, 173, 102, 0, 116, 26, 141, 190, 240, 14, 0, 0, 129, 249, 216, 195, 102, 0, 116, 12, 235, 39, 139, 190, 148, 39, 0, 0, 133, 255, 116, 29, 131, 191, 196, 0, 0, 0, 0, 116, 20, 139, 143, 36, 10, 0, 0, 59, 143, 32, 10, 0, 0, 126, 6, 49, 192, 95, 94, 91, 195, 95, 94, 91, 195];
  const A_WH_DOWN = 0x5F07B0, A_WH_UP = 0x5F07F0, A_GET_TARGET = 0x5F6A50, A_CHEVRON = 0x606B20;
  (function installWheelThunks() {
    const sites = [["WHD", A_WH_DOWN, WHD_CODE, [[0, A_GET_TARGET], [210, A_CHEVRON]]], ["WHU", A_WH_UP, WHU_CODE, [[0, A_GET_TARGET]]]];
    for (const [nm, site, code, calls] of sites) {
      const cur = new Uint8Array(VA(site).readByteArray(5));
      const tgt = VA(site).add(5).add(new Int32Array(cur.buffer.slice(1, 5))[0]);
      if (cur[0] !== 0xE8 || !tgt.equals(VA(A_GET_TARGET))) { log("WHEEL SKIP " + nm + ": site " + hex(site) + " is not `call Win_get_active_target` (" + Array.from(cur).map(b => b.toString(16)).join(" ") + ")"); continue; }
      const p = allocStub(code, {}, {});
      for (const [o, t] of calls) { if (code[o] !== 0xE8) { log("WHEEL " + nm + ": no E8 at stub+" + o); } Memory.patchCode(p.add(o + 1), 4, c => c.writeS32(t - (p.toInt32() + o + 5))); }
      E_STUBS.push({ nm, a: site, p, code: Array.from(new Uint8Array(p.readByteArray(code.length))) });
      Memory.patchCode(VA(site), 5, c => c.add(1).writeS32(p.toInt32() - (site + 5)));
      log("WHEEL thunk " + nm + " @" + hex(site) + " -> " + p + " (synthetic VK_UP/DOWN -> chevron on the modal PartPicker/ProdPicker/Popup rail/FileDlg/TextScroll; ungated)");
    }
  })();
  // v14v PROBE (log-only): the SELECT SPECIAL ABILITY popup (flat type-16 list + popup rail) draws its rows ~2 native px
  // right of the field frame at 1920 (user shot 130235 vs pristine SpecialAbility.png: inner stroke->rows 5 px where s(2..3)
  // belongs, rows->scrollbar 3 px where ~6 belongs, row width faithful 600). Rows x = Dialog child x = the margin sum
  // [30b4]+[30f0]+[30e0]+[30d8] -> g_popup_dialog_x 0x9B8CEC (BasePop_calc 0x604292). Log every term + the field stash
  // + the type-16 attach args so the law can be stated from numbers. Hosts: BasePop_calculate_dimensions 0x603800 and
  // Dialog_type16_attach 0x60D1F0 entries (both live==.bak; the baked sites are inside the bodies).
  const PCAVE2_ = 0xA0C000;
  const popupId = p => { for (const off of [0xa48, 0x2188]) { try { const sp = p.add(off).readPointer(); if (!sp.isNull()) { const t = sp.readAnsiString(48); if (t && t.trim().length) return t.trim(); } } catch (e) { } } return "?"; };
  let bpCalcLogs = 0, t16Logs = 0, dumpDone = {}, nfLogs = 0;
  // v15e: the nested list frame rect as it leaves thunk_popup_nestpads (0x406220 = first original instruction after the
  // NOP sled; ebp frame: [ebp-0x24]=L [ebp-0x20]=T [ebp-0x1c]=R(set by the 2nd instr) [ebp-0x18]=B; ecx = R live) with the
  // list rect it came from ([ebp-0x44..-0x38]) and the title/band stash -> the draw-chain offset becomes a number.
  if (false) Interceptor.attach(VA(0x406220), {                                       // v15f: REMOVED (user: UI elements vanished on the v15e run; rect captured: L=22 R=882 @g22 for list 26..878)
    onEnter() {
      if (nfLogs++ >= 30) return;
      const bp = this.context.ebp, f = o => safeS32(bp.sub(o)), t = this.context.esi;
      log("[NESTFRAME] popup=" + hex(t.toInt32()) + " id='" + popupId(t) + "' g=" + g + " list rect L,T,R,B=" + [0x44, 0x40, 0x3c, 0x38].map(f).join(",") + " -> frame rect L,T,R(ecx),B=" + f(0x24) + "," + f(0x20) + "," + this.context.ecx.toInt32() + "," + f(0x18) +
          " | band_left[g]=" + safeS32(VA(0xA0C000 + 0x2700)) + " field_anchor=" + safeS32(VA(0xA0C000 + 0x2704)) + " band_popup=" + hex(safeU32(VA(0xA0C000 + 0x2708))) + " title_rect(g_fc)=" + [0, 4, 8, 12].map(o => safeS32(VA(0xA0C000 + 0x2544 + o))).join(","));
    }
  });
  // v15a: stage sampler for the listbox width chain. Dialog fields of the ListBox sit at popup+0x2DA0 (vbtable adjust
  // 0xB88 from ListBox this = popup+0x2218): [+0x2c] min/wrap width = popup+0x2DCC (== the BasePop "[+0x222c]" term),
  // w5c +0x2DFC, w64 +0x2E04, h60 +0x2E00, rows58 +0x2DF8, cols54 +0x2DF4, xs +0x2D9C. Measured 845 = 600*22/16 + 20
  // (g_scrollbar_w native) -> find the stage that adds the 20 after the scaled 825.
  let curPop = 0, lbwN = 0;
  const lbw = (t, tag) => { const f = o => safeS32(ptr(t).add(o)); log("[LBW] " + tag + " pop=" + hex(t) + " [2c]=" + f(0x2DCC) + " w5c=" + f(0x2DFC) + " w64=" + f(0x2E04) + " h60=" + f(0x2E00) + " rows58=" + f(0x2DF8) + " cols54=" + f(0x2DF4) + " xs=" + f(0x2D9C) + " box_w=" + f(0x30bc) + " g_sbw=" + safeS32(VA(0x9B8DD4)) + " count=" + f(0x2E3C)); };
  Interceptor.attach(VA(0x601BF0), { onEnter() { this.t = this.context.ecx.toInt32(); }, onLeave() { curPop = this.t; if (lbwN++ < 200) lbw(this.t, "BasePop_start leave"); } });
  Interceptor.attach(VA(0x60C920), { onEnter() { if (curPop && lbwN++ < 200) { this.on = true; lbw(curPop, "Dialog_item enter"); } }, onLeave() { if (this.on) lbw(curPop, "Dialog_item leave"); } });
  Interceptor.attach(VA(0x60C9B0), { onEnter() { if (curPop && lbwN++ < 200) { this.on = true; lbw(curPop, "ListBox_update_changes enter"); } }, onLeave() { if (this.on) lbw(curPop, "ListBox_update_changes leave"); } });
  Interceptor.attach(VA(0x406260), { onEnter() { if (lbwN++ < 200) { this.on = true; lbw(this.context.ecx.toInt32(), "popup_sb_create enter"); } }, onLeave() { if (this.on) lbw(curPop, "popup_sb_create leave"); } });
  Interceptor.attach(VA(0x404920), { onEnter() { this.pop = this.context.ecx.toInt32(); if (lbwN++ < 200) { this.on = true; lbw(this.pop, "Popup_show enter"); } }, onLeave() { if (this.on) lbw(curPop, "Popup_show leave"); armHeapBar(this.pop, "Popup_show leave"); } });
  // v15k: register the Win-layer HEAP ScrollBar ([popup+0x2794], vtbl 0x669D58) in g_rail_sb (pcave2+0x11260) for the
  // popup's lifetime -> thunk_pref_sbzoom v6 arms every ScrollBar_draw of it (grip via thunk_sb_thumb under the netwin
  // bracket, then thunk_sb_restripe regenerates the F0/B9 grip dither at device density) and thunk_btn_stripes v6 arms
  // its two arrow children (+0xAAC/+0x15F8: F0/B9 + hover A2/EF chevrons restriped). Same mechanism as the popup rail
  // (thunk_rail_sbfit's stash); cleared at Popup_hide. BAKE: the stash write joins the LBRES group's bar creation site
  // (after ScrollBar_init_v @0x5EC427) and the clear joins Popup_hide / the popup bracket.
  const G_RAIL_SB = PCAVE2 + 0x11260, SB_VTBL = 0x669D58;
  function heapBarOf(pop) {
    try { const sb = VA(pop + 0x2794).readPointer(); if (sb.isNull()) return 0; if (sb.readPointer().toInt32() !== SB_VTBL) return 0;
      const a = sb.toInt32(); if (a >= pop && a < pop + 0x4000) return 0; return a; } catch (e) { return 0; }
  }
  function armSb(sb, why) {
    if (!sb) return;
    try { if (VA(sb).readPointer().toInt32() !== SB_VTBL) return; } catch (e) { return; }
    const old = VA(G_RAIL_SB).readU32(); if (old === sb) return;
    VA(G_RAIL_SB).writeU32(sb); log("[RAILSB] " + why + ": g_rail_sb " + hex(old) + " -> heap bar " + hex(sb));
  }
  function armHeapBar(pop, why) { armSb(heapBarOf(pop), why + " (popup " + hex(pop) + ")"); }
  // v15l: the first paint happens INSIDE Popup_show (v15k log: arm at Popup_show leave, user: grip native until the
  // first scroll) -> register at the bar's CREATION: ScrollBar_init_v leave (0x605910; Win V-bar creator @0x5EC427),
  // gated g_popup_active && g>16 (the same gate that scaled its width at 0x605938). Popup_show leave stays as fallback.
  Interceptor.attach(VA(0x605910), { onEnter() { this.sb = this.context.ecx.toInt32(); },
    onLeave() { if (VA(G_POPUP_ACTIVE).readS32() !== 0 && VA(0x668740).readS32() > 16) armSb(this.sb, "ScrollBar_init_v leave"); } });
  Interceptor.attach(VA(0x404A80), { onEnter() { const pop = this.context.ecx.toInt32(); const sb = heapBarOf(pop); const cur = VA(G_RAIL_SB).readU32();
    if (sb && cur === sb) { VA(G_RAIL_SB).writeU32(0); log("[RAILSB] Popup_hide: g_rail_sb " + hex(sb) + " -> 0"); } } });
  // v14w: popup-LOCAL pixel census of the ability list (canvas +0x444) 1.5 s after layout: RLE of a row through the
  // first option bar, a row through the 6th bar, and a column at x=8 / x=canvasW-8 -> band/field strokes, bars,
  // scrollbar in the popup's own space (the screen shot cannot give the window origin).
  function rle(data, pitch, x0, x1, y, step) {
    const out = []; let prev = -1, start = x0, n = 0;
    for (let x = x0; x < x1; x += step) { const v = data.add(y * pitch + x).readU8(); if (v !== prev) { if (n) out.push(start + ":" + n + "x" + prev); prev = v; start = x; n = 0; } n++; }
    if (n) out.push(start + ":" + n + "x" + prev);
    return out.join(" ");
  }
  function rleCol(data, pitch, x, y0, y1) {
    const out = []; let prev = -1, start = y0, n = 0;
    for (let y = y0; y < y1; y++) { const v = data.add(y * pitch + x).readU8(); if (v !== prev) { if (n) out.push(start + ":" + n + "x" + prev); prev = v; start = y; n = 0; } n++; }
    if (n) out.push(start + ":" + n + "x" + prev);
    return out.join(" ");
  }
  function dumpPopup(t, id) {
    try {
      const b = bufInfo(t.add(0x444)); if (b.data.isNull() || b.w <= 0 || b.h <= 0 || b.w > 4096 || b.h > 4096) { log("[PDUMP] '" + id + "' degenerate canvas " + b.w + "x" + b.h); return; }
      const f = o => safeS32(t.add(o));
      log("[PDUMP] '" + id + "' canvas " + b.w + "x" + b.h + " pitch " + b.pitch + " g=" + g + " win rect(+0x474..) " + [0x474, 0x478, 0x47c, 0x480].map(o => f(o)).join(",") + " 30e8=" + f(0x30e8) + " 30ec=" + f(0x30ec) + " box " + f(0x30bc) + "x" + f(0x30c0) +
          " sb rect(+0x3230+0x474..) " + [0x474, 0x478, 0x47c, 0x480].map(o => f(0x3230 + o)).join(",") + " sb parent=" + hex(safeU32(t.add(0x3230 + 0xC4))) + " range " + f(0x3230 + 0xA20) + ".." + f(0x3230 + 0xA24) + " val " + f(0x3230 + 0xA2C) + " flags98=" + hex(safeU32(t.add(0x3230 + 0x98))));
      const lw = t.add(0x2358), sbp = safeU32(t.add(0x2794));
      log("[PDUMP] SCREEN popup " + [0x13C, 0x140, 0x144, 0x148].map(o => f(o)).join(",") + " | list win " + [0x13C, 0x140, 0x144, 0x148].map(o => safeS32(lw.add(o))).join(",") + " canvas " + safeS32(lw.add(0x4C4)) + "x" + (-safeS32(lw.add(0x4C8))) + " vtbl=" + hex(safeU32(lw)) + " first=" + f(0x21E8) + " vis=" + f(0x21EC) + " count=" + f(0x2E3C) + " sel=" + f(0x2E5C) +
          " | rail ptr [+0x2794]=" + hex(sbp) + (sbp ? " rail screen " + [0x13C, 0x140, 0x144, 0x148].map(o => safeS32(ptr(sbp).add(o))).join(",") + " range " + safeS32(ptr(sbp).add(0xA20)) + ".." + safeS32(ptr(sbp).add(0xA24)) + " val " + safeS32(ptr(sbp).add(0xA2C)) : "") +
          " | dialog_x=" + safeS32(VA(0x9B8CEC)) + " 30f0=" + f(0x30f0) + " 30d8=" + f(0x30d8) + " 30e0=" + f(0x30e0) + " 21c8=" + f(0x21c8) + " 21cc=" + f(0x21cc) + " 222c=" + f(0x222c) + " 2230=" + f(0x2230));
      try {   // v14z: the ListBox/Dialog width fields (vbtable-adjusted: ListBox this = popup+0x2218, Dialog fields at +0x188; iv3 = 0xBA0) + canvas screen origins
        const D = t.add(0x23A0), dfl = [0x20, 0x2c, 0x30, 0x34, 0x40, 0x44, 0x48, 0x54, 0x58, 0x5c, 0x60, 0x64, 0x68, 0xcc].map(o => o.toString(16) + "=" + safeS32(D.add(o))).join(" ");
        const px = Memory.alloc(16); RETAINED.push(px); px.writeS32(0); px.add(4).writeS32(0); localToScreen(t, px, px.add(4)); const ox = px.readS32(), oy = px.add(4).readS32();
        px.add(8).writeS32(0); px.add(12).writeS32(0); localToScreen(lw, px.add(8), px.add(12)); const lx = px.add(8).readS32(), ly = px.add(12).readS32();
        log("[PDUMP] FIELDS xs[+0x2D9C]=" + f(0x2D9C) + " tw222c[+0x2DCC]=" + f(0x2DCC) + " th2230[+0x2DD0]=" + f(0x2DD0) + " g_scrollbar_w=" + safeS32(VA(0x9B8DD4)) + " Dialog{" + dfl + "} | popup canvas origin " + ox + "," + oy + " list canvas origin " + lx + "," + ly + " (list-popup dx=" + (lx - ox) + ")");
      } catch (e) { log("[PDUMP] fields err " + e); }
      const y1 = f(0x30e8) + Math.floor(12 * g / 16), y2 = y1 + Math.floor(5 * 27 * g / 16), yt = Math.floor(36 * g / 16);
      for (const y of [yt, y1, y2, Math.floor(b.h / 2)]) if (y >= 0 && y < b.h) log("[PDUMP] row y=" + y + ": " + rle(b.data, b.pitch, 0, b.w, y, 1));
      for (const x of [8, Math.floor(b.w / 2), b.w - 8]) if (x >= 0 && x < b.w) log("[PDUMP] col x=" + x + ": " + rleCol(b.data, b.pitch, x, 0, b.h));
    } catch (e) { log("[PDUMP] err " + e); }
  }
  Interceptor.attach(VA(0x603800), {
    onEnter() {
      this.t = this.context.ecx; if (lbwN++ < 200) lbw(this.t.toInt32(), "BasePop_calc enter");
      if (false && safeS32(this.t.add(0x2D9C)) === 600 && safeS32(this.t.add(0x2E3C)) > 12) {       // v15b watchpoint (done: writers 0x60A432/0x60A640) - disarmed
        try {
          const tid = Process.getCurrentThreadId(); const th = Process.enumerateThreads().find(x => x.id === tid);
          globalThis.WP.addr = this.t.add(0x2DCC); globalThis.WP.hits = []; th.setHardwareWatchpoint(0, globalThis.WP.addr, 4, "w"); globalThis.WP.armed = true; this.wp = th;
          log("[WP] armed on " + globalThis.WP.addr + " thread " + tid);
        } catch (e) { log("[WP] arm failed: " + e); }
      }
    },
    onLeave() {
      if (this.wp) { try { this.wp.unsetHardwareWatchpoint(0); } catch (e) { log("[WP] unset err " + e); } globalThis.WP.armed = false; log("[WP] hits: " + (globalThis.WP.hits.length ? globalThis.WP.hits.join(" | ") : "none")); }
      if (lbwN++ < 200) { lbw(this.t.toInt32(), "BasePop_calc leave"); if (safeS32(this.t.add(0x2D9C)) === 600) log("[LBW] raw popup+0x2D90..0x2E40: " + Array.from({ length: 44 }, (_, i) => "+" + (0x2D90 + 4 * i).toString(16) + "=" + safeS32(this.t.add(0x2D90 + 4 * i))).join(" ")); }
      if (bpCalcLogs++ >= 40) return;
      const t = this.t, f = o => safeS32(t.add(o));
      log("[bpcalc] popup=" + hex(t.toInt32()) + " vtbl=" + hex(safeU32(t)) + " id='" + popupId(t) + "' g=" + g + " box_w[30bc]=" + f(0x30bc) + " box_h[30c0]=" + f(0x30c0) +
          " 30b4=" + f(0x30b4) + " 30f0=" + f(0x30f0) + " 30e0=" + f(0x30e0) + " 30d8=" + f(0x30d8) + " 30d4=" + f(0x30d4) + " 30dc=" + f(0x30dc) + " 30e8=" + f(0x30e8) + " 30ec=" + f(0x30ec) + " 30f4=" + f(0x30f4) +
          " 21b0=" + f(0x21b0) + " 21b4=" + f(0x21b4) + " 21c0=" + f(0x21c0) + " 21c4=" + f(0x21c4) + " 21c8=" + f(0x21c8) + " 21cc=" + f(0x21cc) + " 21fc=" + f(0x21fc) + " art[2144]=" + hex(safeU32(t.add(0x2144))) + " a3c=" + hex(safeU32(t.add(0xa3c))) +
          " dialog_x[9B8CEC]=" + safeS32(VA(0x9B8CEC)) + " win rect(+0x474..) " + [0x474, 0x478, 0x47c, 0x480].map(o => f(o)).join(",") + " sb parent=" + hex(safeU32(t.add(0x3230 + 0xC4))) + " sb range " + f(0x3230 + 0xA20) + ".." + f(0x3230 + 0xA24) + " value " + f(0x3230 + 0xA2C));
      const id = popupId(t); if (/special ability/i.test(id) && !dumpDone[t.toInt32() + ":" + id]) { dumpDone[t.toInt32() + ":" + id] = true; setTimeout(() => dumpPopup(t, id), 1500); setTimeout(() => dumpPopup(t, id + " (t+6s)"), 6000); }
    }
  });
  Interceptor.attach(VA(0x60D1F0), {
    onEnter() {
      if (t16Logs++ >= 40) return;
      const d = this.context.ecx.add(0x12c), f = o => safeS32(d.add(o)), sp = this.context.esp;
      log("[t16attach] dialog=" + hex(this.context.ecx.toInt32()) + " parent=" + hex(safeU32(sp.add(4))) + " x=" + safeS32(sp.add(8)) + " y=" + safeS32(sp.add(12)) + " flags=" + hex(safeU32(sp.add(16))) +
          " D: w5c=" + f(0x5c) + " itemw64=" + f(0x64) + " h60=" + f(0x60) + " pitch68=" + f(0x68) + " gap44=" + f(0x44) + " ind34=" + f(0x34) + " count_cc=" + f(0xcc) + " box_w34c=" + f(0x34c) + " box_h350=" + f(0x350) +
          " | dialog_x[9B8CEC]=" + safeS32(VA(0x9B8CEC)) + " field stash L=" + safeS32(VA(PCAVE2_ + 0x44BC)) + " R=" + safeS32(VA(PCAVE2_ + 0x44C0)) + " boxw=" + safeS32(VA(PCAVE2_ + 0x44C4)) + " modal_top=" + hex(safeU32(VA(0x9B7AE0))) + " basepop=" + hex(safeU32(VA(0x9B8D7C))));
    }
  });
  for (const nm of ["PostMessageA", "PostMessageW"]) {                             // log-only: correlate notches with the thunk's effect
    let ex = null; try { ex = u32m.getExportByName(nm); } catch (e) { }
    if (!ex) continue;
    Interceptor.attach(ex, {
      onEnter(args) {
        const msg = args[1].toInt32(), wp = args[2].toInt32(), lp = args[3].toInt32();
        if (!wheelPicker || lp !== 0 || (wp !== 0x26 && wp !== 0x28) || msg !== 0x100) return;
        if (wheelN++ < 12) { const t = ptr(wheelPicker), sb = t.add(0xA14); log("WHEEL synthetic " + (wp === 0x26 ? "VK_UP" : "VK_DOWN") + " posted (" + nm + "): picker first_idx=" + safeS32(t.add(0x2B60)) + " sel=" + safeS32(t.add(0x2B80)) + " sb value=" + safeS32(sb.add(0xA2C)) + " engaged=" + (safeU32(sb.add(0xC4)) !== 0) + " modal_top=" + hex(safeU32(VA(0x9B7AE0)))); }
      }
    });
  }
  const ReleaseDC = new NativeFunction(u32m.getExportByName("ReleaseDC"), "int", ["pointer", "pointer"]);
  const GetPixel = new NativeFunction(g32m.getExportByName("GetPixel"), "uint32", ["pointer", "int", "int"]);
  let palInv = null;
  function palIndexOf(cr) {                                                          // COLORREF 0x00BBGGRR -> palette index (first match) or "?rrggbb"
    if (!palInv) { palInv = new Map(); for (let i = 255; i >= 0; i--) { const c = pal(i); palInv.set(c[0] | (c[1] << 8) | (c[2] << 16), i); } }
    const v = palInv.get(cr & 0xffffff); return v === undefined ? "?" + (cr & 0xffffff).toString(16) : String(v);
  }
  const runStr = arr => { const out = []; let cur = null, n = 0; for (const v of arr) { if (v === cur) n++; else { if (cur !== null) out.push(cur + "x" + n); cur = v; n = 1; } } out.push(cur + "x" + n); return out.join(" "); };
  function displayCensus(r, sx, sy, tag) {
    const K = SL.strokeWidth(g), ym = r[1] + K + 2 + (((r[3] - r[1]) >> 2) & ~1);       // one row inside the band, even offset (dither phase fixed)
    const scr = bufInfo(VA(0x9B7490)); const dib = [], disp = [];
    const hdc = GetDC(ptr(0)); if (hdc.isNull()) { log("DISPLAYCENSUS " + tag + ": GetDC(0) failed"); return; }
    for (let x = r[2] - 24; x < r[2]; x++) { dib.push(String(scr.data.add((sy + ym) * scr.pitch + sx + x).readU8())); disp.push(palIndexOf(GetPixel(hdc, sx + x, sy + ym))); }
    ReleaseDC(ptr(0), hdc);
    log("DISPLAYCENSUS " + tag + ": cell " + r.join(",") + " row " + ym + " R band x[" + (r[2] - 24) + ".." + r[2] + ") | DIB: " + runStr(dib) + " | DISPLAY: " + runStr(disp) + (dib.join() === disp.join() ? " | SAME" : " | DIFFER"));
  }
  // v14m: the engine's own Buffer_copy_4 flip never fires on this build (v14l) - the display is refreshed by WM_PAINT
  // (engine InvalidateRect -> PRACX passthrough -> BeginPaint.rcPaint -> BitBlt at 0x5F018C). Log every rect on that
  // path while an unhover is pending so the 13-px stale tail can be pinned to the stage that under-covers it.
  let pendTag = "", pendUntil = 0, paintLogs = 0, paintLast = "", paintRep = 0; const paintSeen = new Map();
  const pend = () => (Date.now() < pendUntil ? " | pending " + pendTag : "");
  const paintOn = () => dwActive && g > 16 && !!pickerObj && pickerDrawn && paintLogs < 200;
  const rectS = p => (p.isNull() ? "NULL" : [0, 4, 8, 12].map(o => p.add(o).readS32()).join(","));
  const modOf = a => { const m = Process.findModuleByAddress(a); return m ? m.name + "+" + hex(a.sub(m.base).toInt32()) : hex(a.toInt32()); };
  function paintLog(line) {                                                         // v14o: the 30 fps preview flip+blit pair alternates - suppress any line already seen 3x (counts dumped by SCREENCENSUS)
    const key = line.replace(/ \| pending .*$/, ""), n = (paintSeen.get(key) || 0) + 1; paintSeen.set(key, n);
    if (n > 3) return;
    paintLogs++; log(line + (n === 3 ? " (further repeats suppressed)" : ""));
  }
  Interceptor.attach(Process.getModuleByName("user32.dll").getExportByName("InvalidateRect"), {
    onEnter(args) { if (paintOn()) paintLog("PAINT InvalidateRect rect " + rectS(args[1]) + " erase " + args[2].toInt32() + " ret " + modOf(this.returnAddress) + pend()); }
  });
  Interceptor.attach(Process.getModuleByName("user32.dll").getExportByName("BeginPaint"), {
    onEnter(args) { this.ps = args[1]; this.on = paintOn(); },
    onLeave() { if (this.on) paintLog("PAINT BeginPaint rcPaint " + rectS(this.ps.add(8)) + pend()); }
  });
  for (const nm of ["BitBlt", "StretchBlt"]) Interceptor.attach(Process.getModuleByName("gdi32.dll").getExportByName(nm), {
    onEnter(args) { if (paintOn()) paintLog("PAINT " + nm + " dst " + args[1].toInt32() + "," + args[2].toInt32() + " " + args[3].toInt32() + "x" + args[4].toInt32() + " src " + args[6].toInt32() + "," + args[7].toInt32() + (nm === "StretchBlt" ? " " + args[8].toInt32() + "x" + args[9].toInt32() : "") + " ret " + modOf(this.returnAddress) + pend()); }
  });
  Interceptor.attach(VA(0x5EFD20), {                                                 // engine screen-flip routine Win_flip_rect(rect*) (ends at the PRACX-redirected BitBlt 0x5F018B): who asks for which rect?
    onEnter() { if (paintOn()) { const rp = this.context.esp.add(4).readPointer(); paintLog("PAINT flip 0x5EFD20 rect " + (rp.isNull() ? "NULL(all)" : rectS(rp)) + " clip[9BC2D0] " + rectS(VA(0x9BC2D0)) + " ret " + modOf(this.returnAddress) + pend()); } }
  });
  let lastOpen = 0;
  setInterval(function () {
    try {
      if (dwActive && g > 16) heapCheck("poll", true);
      const cur = safeU32(VA(G_CURRENT));
      if (cur !== lastOpen) { lastOpen = cur; log("POLL current=" + hex(cur)); }
      if (needTrace && traceObj !== null) { needTrace = false; trace(traceObj, "paint#" + paintN); }
    } catch (e) { log("POLL error: " + e); }
  }, 400);
  log("armed v14: " + P.length + " immediates (applied at first exec with g>16), rails, union-frame redirect, gate range; hooks exec/build/master/onmode/slide/itemdraw(0x404220) + 120ms button watcher + HEAPCHK checkpoints + D9/D11 bracket trace (fill pipeline + TutWin + preview + 100ms poll) + D7' state/inset split + D10 hover restripe + Z'' dst-gated composite shim + v14t OVL overlay-blit stub + v14u WHEEL->chevron WinProc thunks (ungated) + upper-row pitch levers + FIT/SSAA render experiments (FIT=" + FIT + " SSAA=" + SSAA + ") + PART PICKER levers (cell law stub, click descale, frames, fonts, rail gate retarget, popup_active bracket=" + ARM_POPUP_ACTIVE + ") + D13 clamp (watcher OFF)");
}
