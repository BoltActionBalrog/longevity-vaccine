// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// hook_prefwin_scale.js — PROTOTYPE v19: scale the PREFERENCES window (PrefWin @0x8578D8)
// v19: FRAME STROKES measured 1px native at 4K (law: K=half_down(g,16)=2) — the chrome stub
//     tailed into plain Buffer_box_sprite whose entry detour (thunk_hud_boxframe) thickens
//     HUD dests only. Now dispatch like thunk_factionwin_framecover: [params+0x20] filled ->
//     thunk_box_thick_devfill (device-density dither interior), hollow ->
//     thunk_box_thick_hollow_flat (band-map K-wide strokes). g<=16 still plain-native.
// v18: RAIL CHROME (the framing art left/right/top of the window). The rails draw through
//     slide_show/slide_hide's rail-strip sites, which the baked filedlg_chrome_rails group
//     already scales (railscale: 4 settled sites; railslide: 8 animation sites) behind the
//     g_filedlg_active + g_fd_winbuf identity gate. Popups arm that gate via the baked
//     wrappers thunk_popup_railshow/railhide at THEIR slide call sites — do the same for the
//     PrefWin family: call_target_redirect the 4 sites (show 0x48fc66/0x492700, hide
//     0x48ff12/0x4927a0) to the baked wrappers. Wrappers are window-agnostic ([esp+4]=win),
//     g<=16 -> byte-identical native tail. (v11's entry-hook arming attempt is superseded.)
// v17: sliders — arrow windows scaled at GWinit (zoom now round-trips; v16's mangle was the
//     zoom engaging on NATIVE 12x20 windows); nub via ScrollBar_draw vtable gate stub setting
//     g_netwin_active around the 4 PrefWin sliders' draws (activates baked thunk_sb_thumb).
// v16: BUTTON ART = the proven popup zoom machinery instead of per-primitive scaling. v15's
//     tile-H scale REPEATED the 20px band pattern 2.5x (striped highlight), left the native
//     end caps covering only rows 0..19 (edge clipping), and labels stayed tiny until a hover
//     redraw (build-time text predates the show-time font fix). Fix: the baked
//     thunk_btn_shrink/thunk_btn_2dscale pair (render whole button NATIVE, NN-zoom x g/16 —
//     caps/band/highlight/states all consistent; text draws after the zoom, crisp) is gated
//     on g_popup_active — so swap the ONE FlatButton vtable draw slot [0x669784]=0x607e50
//     (data write, no Interceptor) to a stub that sets g_popup_active=1 around the real draw
//     for ecx in the PrefWin button cluster [0x858338..0x872140] only. SCALE_BANDS -> false
//     (v15 hooks stay as census; scaling there would corrupt the native render pass). Labels:
//     force vtbl+0xF8 redraw of all 15 buttons after prefFontFix at show enter.
// v15: BUTTON BAND HEIGHT. Measured (4K shot + pristine): the translucent fill band inside
//     every button is drawn TOP-ANCHORED at native ~20px into the 50px button buffer (my v13
//     btnROW sampled y=25 = BELOW the band — the band IS in the buffer, rows 0..~19). +0xA84
//     is the fill COLOR (=19, coincidence), not a height. The drawer receives a NATIVE height
//     (BaseButton_init's h arg stays native; only GraphicWin_init's copy gets scaled by us).
//     -> census entry hooks on Buffer_fill_3/Buffer_fill/Buffer_tile_2/Buffer_box_2 gated on
//     the 15 button buffers (entries verified un-detoured; plain-E8-called) + SPECULATIVE
//     scale of the clear case (top-anchored h 16..24 -> y,h x g/16). If none fires for the
//     band, the drawer is the un-attachable Sprite_draw_2 path -> byte-patch next round.
// v14: (a) the "unscaled pristine backdrop" overlay = the REPAINT helpers 0x491810 (right
//     panel, site 0x49184d), 0x491860 (gamma frame, 0x4918b1) and full-refresh FUN_00491c00
//     (0x491c42/0x491c8c) rebuilding the SAME rects from the native globals AFTER the scaled
//     show-time paint -> extend the E8 retarget to those four sites (same stub; rects rebuilt
//     native per call so idempotent). (b) right-side checkbox x art: PrefWin pages draw rows
//     via generic FUN_0060f030 whose two checkbox-sprite draws 0x60f41c/0x60f457 are the
//     patch set's status:skip pair ("popups never reach them") — PrefWin DOES. Retarget both
//     to a stub replicating baked thunk_checkbox_scale (num/den 1,1 -> g,16; y += (16-g)/2),
//     tail-jmp FUN_005e4b4a. If the x stays tiny after this, it's a FONT glyph, not a sprite.
// v13: THE MISSING BACKDROP WAS HAZARD #7 TOO. The five Buffer_box_sprite SITE hooks
//     (0x48fb19..0x48fc01) sat on calls into the baked-detoured entry 0x5E2DD3
//     (thunk_hud_boxframe) -> displaced stack: the frame + BOTH opaque interior panels never
//     drew (v12 bufrow: PREFBUF all key-9 = map shows through), and the "tiny native panel"
//     at rel(256,10,457x376) was the thunk drawing from displaced native dwords. Fix: NO
//     Interceptor on that chain — Memory.patchCode retargets each E8 to a hand-assembled RWX
//     stub scaling rect L,T,R,B in place (x g/16, g<=16 no-op), then jmp to the real entry.
//     Rects rebuild from native globals each call (0x686b7c/80/84, 0x8577d8..e4, 0x857884..c0)
//     -> idempotent. Also: font write reverted to slot1 ONLY (v12's all-four write coincided
//     with rows 4-6 losing their labels entirely); btnROW buffer forensics added; rails
//     arming stays OFF (bisect: armed/off both transparent — it never painted anything).
// v12: labels+names PROVEN intact (hazard #7 fixed by v11); remaining: (a) translucent-mesh
//     interior -> rails arming OFF (borrowed the FILE DIALOG's translucent aesthetic) + buffer
//     row forensics; (b) flat fill still native-20 tall -> btnDUMP field hunt; (c) tiny labels
//     on selected/disabled states -> write all four font slots; (d) page-width double-scale ->
//     stop scaling w at Dialog_init_2 (baked thunk_list_fill_width owns it).
// v11: HAZARD (new, to be recorded): Frida site hook + hooked/detoured callee ENTRY on one
//     chain displaces the entry-side stack with 0x2EExxxxx trampoline dwords (v10 proof:
//     Dialog_init_2 ENTRY ret/x garbage; same value family as the rect corruption AND the
//     "ÿ5" button labels — the "mystery mover" was OUR OWN hook interplay). Retreat: no call
//     sites hooked on any chain whose entry we also touch. Build scaling now = ONE
//     GraphicWin_init entry hook (self + parent==PrefWin gates); Dialog_init_2 gated on the 7
//     static page addrs; BaseButton/slider/census/site-capture hooks all deleted.
// v2: page-attach moved from the 7 three-byte dispatch-site hooks (one wild-jumped -> Quick
//     Start crash, minidump 42356) to ONE clean entry hook at FUN_0060e800 gated on win==PrefWin.
// v9: restored the deleted `let showDepth` (strict-mode ReferenceError silently killed the
//     show hook = v8's repair never ran).
// v10: window now visible+placed; three defects from the 4K shot (vs refs\pristine):
//     (1) page panel repainted at NATIVE rect -> Dialog_init_2 ENTRY hook gated on the 7
//         captured page-Dialog ptrs (all scaling moved there; catches every re-init path);
//     (2) button labels tiny + fill only font-high -> write btn+0x970 font slot at show
//         (thunk_comm_btnfont mechanism; Buffer_box_sprite/FlatButton-draw entries are
//         baked-detoured NO-ATTACH, so slot writes at show entry instead);
//     (3) checkbox-x glyphs native size -> find_font entry CENSUS to locate their font source.
// Consumer-boundary scaling: all globals/literals stay NATIVE; every final x/y/w/h/rect/font-size
// is scaled x g/16 at the call sites inside PrefWin_build (0x48D840) and PrefWin_show (0x48FA00).
// g<=16 -> no mutation anywhere (native identity). Idempotent by construction (args rebuilt per call).
//
// Vanilla ground truth (validated against refs\pristine\Preferences.png, 1024x768 capture):
//   window x=ScrW/2-350 y=ScrH-618 w=778 h=390 ; left col buttons rel(33,10) 214x20 pitch 22;
//   gamma +154; Restore/OK/Cancel y = 383-69/46/23; pages Dialog_init_2(256,10,457,376);
//   sliders (382, 288+22k, w328); chrome rects (23,0,723,390)(27,4,719,386)(30,7,250,383)
//   (253,7,716,383) gamma(256,287,543,379); fonts 10/12/14pt.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_prefwin_scale.log";
log("=== hook_prefwin_scale.js started ===");
installAVHandler("prefwin_scale");

if (requireBase()) {
  const G_PSN = VA(0x668740);        // g_popup_scale_num
  const SH = VA(0x9b7b20);           // ScreenHeight
  const SW = VA(0x9b7b1c);           // ScreenWidth
  const PREFWIN = VA(0x8578d8);
  // rail-arming globals (pcave2 @0xA0C000)
  const G_FDACT = VA(0xa0c000 + 0x23a0);   // g_filedlg_active
  const G_FDBUF = VA(0xa0c000 + 0x25e0);   // g_fd_winbuf

  function gval() {
    let g = G_PSN.readS32();
    const der = Math.max(16, Math.min(40, Math.floor(16 * SH.readS32() / 768)));
    if (g !== der) log("WARN g_popup_scale_num=" + g + " but derived=" + der + " (SH=" + SH.readS32() + ") — using global");
    return g;
  }
  const S = (v, g) => Math.floor(v * g / 16);

  // generic: scale N consecutive dword stack args starting at [esp+off] (call-site attach: [esp]=arg1)
  function scaleStackArgs(siteVA, label, offsets, extraCheck) {
    Interceptor.attach(VA(siteVA), {
      onEnter() {
        try {
          const g = gval();
          if (g <= 16) return;
          const sp = this.context.esp;
          if (extraCheck && !extraCheck(sp, this.context)) { log(label + " @" + siteVA.toString(16) + " GATE-MISS"); return; }
          const before = offsets.map(o => sp.add(o).readS32());
          offsets.forEach(o => sp.add(o).writeS32(S(sp.add(o).readS32(), g)));
          const after = offsets.map(o => sp.add(o).readS32());
          log(label + " @0x" + siteVA.toString(16) + " g=" + g + "  " + JSON.stringify(before) + " -> " + JSON.stringify(after));
        } catch (e) { log(label + " hook ERROR: " + e); }
      }
    });
  }

  // ---- BUILD (PrefWin_build 0x48D840, runs once at desktop_init) ----

  // v11 HAZARD RETREAT: hooking a CALL SITE whose callee entry carries a hook (Frida OR a baked
  // E8 detour) displaces the entry-side stack with trampoline dwords — proven by v10's
  // Dialog_init_2 ENTRY reading ret/x = 0x2EExxxxx trampoline addrs, the SAME value family as
  // the "mystery" rect corruption AND (as "ÿ5" strings) the button-label garbage. So: NO site
  // hook may coexist with a hooked/detoured callee entry. All child-window scaling moves to ONE
  // entry hook at GraphicWin_init 0x5D4EF0 (audited: no baked patch at entry; all its callers
  // in our set are now unhooked): thiscall(this; x,y,w,h,name*,a7,parent*,menu*,border*).
  //   gate A: ecx==PREFWIN            -> window law x'=ScrW/2-S(350) y'=ScrH-S(618) w'/h'=S
  //   gate B: parent[esp+0x1C]==PREFWIN -> child law x,y,w,h *= g/16 (buttons, sliders, etc.)
  //           EXCEPT ret in [0x60e800,0x60f000) — the page-attach inner init arrives there via
  //           the baked thunk_list_fill_width tail-jmp with its own (defective) w law; leave it.
  // Also a census: log every PrefWin child init (this, ret, name string, dims) — if a name arg
  // is already garbage HERE with clean callers, the corruption is upstream, not our attaches.
  const prefButtons = [];            // children with native button dims (w 214/120, h 20)
  const prefSliders = [];            // the 4 ScrollBar widgets (native 328x20)
  const P_ATTACH_LO = VA(0x60e800), P_ATTACH_HI = VA(0x60f000);
  Interceptor.attach(VA(0x5d4ef0), {
    onEnter() {
      try {
        const sp = this.context.esp;
        const me = this.context.ecx;
        const isPref = me.equals(PREFWIN);
        const parent = sp.add(0x1C).readPointer();
        // v17: slider INTERNALS (arrow mini-buttons) init with parent==the slider widget.
        // Scale them so the zoom round-trips (v16's mangled left arrow = zoom engaging on a
        // NATIVE 12x20 window: 12*16/40=4px render blown back up). Gate every arg on native
        // plausibility — if the ctor passed a scaled-derived coordinate, leave it and log.
        if (!isPref && !parent.equals(PREFWIN)) {
          if (prefSliders.some(s => s.equals(parent))) {
            const g = gval();
            const a = [4, 8, 0xC, 0x10].map(o => sp.add(o).readS32());
            let scaled = [];
            if (g > 16) {
              [4, 8, 0xC, 0x10].forEach((o, k) => {
                const v = sp.add(o).readS32();
                const nativeOk = (k < 2) ? (v >= 0 && v <= 340) : (v > 0 && v <= 40);
                if (nativeOk) { sp.add(o).writeS32(S(v, g)); scaled.push(k); }
              });
            }
            log("GWinit slider-child " + me + " of " + parent + " ret=" + sp.readPointer() +
                " (" + a[0] + "," + a[1] + " " + a[2] + "x" + a[3] + ") -> (" +
                [4, 8, 0xC, 0x10].map(o => sp.add(o).readS32()).join(",") + ") scaledArgs=" + JSON.stringify(scaled));
          }
          return;
        }
        const ret = sp.readPointer();
        const g = gval();
        const x = sp.add(4).readS32(), y = sp.add(8).readS32(), w = sp.add(0xC).readS32(), h = sp.add(0x10).readS32();
        const namePtr = sp.add(0x14).readPointer();
        let name = "";
        try { name = namePtr.isNull() ? "<null>" : namePtr.readCString(24); } catch (e) { name = "<unreadable " + namePtr + ">"; }
        if (isPref) {
          if (g > 16) {
            const nx = Math.floor(SW.readS32() / 2) - S(350, g);
            const ny = SH.readS32() - S(618, g);
            sp.add(4).writeS32(nx); sp.add(8).writeS32(ny);
            sp.add(0xC).writeS32(S(w, g)); sp.add(0x10).writeS32(S(h, g));
          }
          log("GWinit SELF g=" + g + " (" + x + "," + y + " " + w + "x" + h + ") -> (" + sp.add(4).readS32() + "," + sp.add(8).readS32() +
              " " + sp.add(0xC).readS32() + "x" + sp.add(0x10).readS32() + ") name=\"" + name + "\"");
          return;
        }
        const viaAttach = ret.compare(P_ATTACH_LO) >= 0 && ret.compare(P_ATTACH_HI) < 0;
        if (h === 20 && (w === 214 || w === 120) && !prefButtons.some(b => b.equals(me))) prefButtons.push(me);
        if (h === 20 && w === 328 && !prefSliders.some(s => s.equals(me))) prefSliders.push(me);
        if (!viaAttach && g > 16) [4, 8, 0xC, 0x10].forEach(o => sp.add(o).writeS32(S(sp.add(o).readS32(), g)));
        log("GWinit child " + me + " ret=" + ret + (viaAttach ? " [attach-path, untouched]" : "") +
            " g=" + g + " (" + x + "," + y + " " + w + "x" + h + ") -> (" + sp.add(4).readS32() + "," + sp.add(8).readS32() +
            " " + sp.add(0xC).readS32() + "x" + sp.add(0x10).readS32() + ") name=\"" + name + "\"");
      } catch (e) { log("GWinit entry ERROR: " + e); }
    }
  });

  // find_font sites: [esp]=size, [esp+4]=variant. v10: also record the variant each build
  // request uses (needed to re-request the same font family at show time — the hazard rules
  // forbid onLeave at call-site attaches, so we can't capture the returned ptr here).
  const ffVariants = {};           // native size -> variant seen at the build sites
  [0x48d90a, 0x48d918, 0x48d927, 0x48d936, 0x48d944, 0x48d953, 0x48d962]
    .forEach(a => scaleStackArgs(a, "find_font", [0],
      sp => { ffVariants[sp.readS32()] = sp.add(4).readS32(); return true; }));

  // v11: BaseButton_init and slider CALL-SITE hooks REMOVED — their callee entry 0x607210 is
  // the baked thunk_factionwin_button detour, and Frida-site + detoured-entry on one chain is
  // the displaced-stack hazard (v10's ret=0x2EExxxxx proof). Buttons/sliders now scale through
  // the GraphicWin_init entry hook above; prefButtons is filled there by native button dims.

  // Dialog_init_2 (0x609300, thiscall(this; x,y,w,h,listPtr) — stores x/y/w/h at +0x24..+0x30).
  // The page panel painted at its NATIVE rect: a later path RE-INITS the shown page with native
  // constants (inline-rebuild class). v11: gate on the 7 page-Dialog STATIC addresses (embedded
  // in the PrefWin globals region — confirmed in the v10 log, same static class as PREFWIN
  // itself), so no site hooks are needed anywhere on this chain and the entry stack is clean.
  // Entry audited clean (no baked patch at 0x609300).
  const PAGE_DIALOGS = [0x85dc80, 0x85e7a8, 0x85f2d0, 0x85fdf8, 0x860920, 0x861448, 0x861f70].map(a => VA(a));
  Interceptor.attach(VA(0x609300), {
    onEnter() {
      try {
        if (!PAGE_DIALOGS.some(d => d.equals(this.context.ecx))) return;
        const g = gval();
        const sp = this.context.esp;            // entry attach: [esp]=ret, args at +4
        const ret = sp.readPointer();
        // v12: do NOT scale w ([esp+0xC]) — the baked thunk_list_fill_width scales the page
        // child window's w from Dialog+0x2c ([DR-0xa08]) when SW>1023; scaling w here gave the
        // 2855-wide double-scale (1142 x 2.5, confirmed live in the v11 log). Leave w native
        // (457); the thunk then produces the lawful 1142. Watch the row text width in-game: if
        // rows now truncate at 457px, some consumer reads +0x2c directly and needs its own site.
        const before = [4, 8, 0xC, 0x10].map(o => sp.add(o).readS32());
        if (g > 16) [4, 8, 0x10].forEach(o => sp.add(o).writeS32(S(sp.add(o).readS32(), g)));
        const after = [4, 8, 0xC, 0x10].map(o => sp.add(o).readS32());
        log("Dialog_init_2 ENTRY this=" + this.context.ecx + " ret=" + ret + " g=" + g + " " +
            JSON.stringify(before) + " -> " + JSON.stringify(after));
      } catch (e) { log("Dialog_init_2 entry ERROR: " + e); }
    }
  });

  // v11: the find_font entry census is REMOVED — it entry-hooked the callee of our 7 hooked
  // find_font sites (site+entry hazard). The one clean run's yield: the pref-open path makes NO
  // fresh find_font calls for the checkbox glyph (its font is cached somewhere) — trace later.

  // page attach: v1 hooked the 7 three-byte `CALL [EDX+4]` dispatch sites — one of them
  // (0x48ee82) wild-jumped into trampoline space (hard crash on Quick Start, minidump-proven:
  // regs matched the call's inputs, EIP=0xE8BDF350). The recorded hazard class — do NOT attach
  // at these dispatch sites. All pages funnel through FUN_0060e800 (type-1 element init,
  // thiscall: this=elem+0xa34 iface; stack (win,x,y,flags)); its ENTRY is clean (the baked
  // thunk_list_fill_width redirect sits at +0xA1, outside the 5-byte window).
  // Also LOG the data-region fields thunk_list_fill_width consumes ([DR-0xa08] "native width",
  // count [DR-0x968]) — on popups DR-0xa08 = popup+0x21fc, but PrefWin pages are NOT popups,
  // so measure what it really holds before trusting any w law.
  Interceptor.attach(VA(0x60e800), {
    onEnter() {
      try {
        const sp = this.context.esp;
        const win = sp.add(4).readPointer();
        if (!win.equals(PREFWIN)) return;
        const g = gval();
        const ecx = this.context.ecx;
        const vptr = ecx.sub(0xa34).readPointer();
        const adj = vptr.add(8).readS32();
        const DR = ecx.add(adj);
        const natW = DR.sub(0xa08).readS32(), w = DR.sub(0x9d8).readS32(),
              h = DR.sub(0x9d4).readS32(), cnt = DR.sub(0x968).readS32();
        const x = sp.add(8).readS32(), y = sp.add(0xC).readS32();
        if (g > 16) { sp.add(8).writeS32(S(x, g)); sp.add(0xC).writeS32(S(y, g)); }
        log("page_attach(60e800) g=" + g + " xy " + x + "," + y + " -> " + S(x, g) + "," + S(y, g) +
            " | DR=" + DR + " adj=0x" + adj.toString(16) + " natW[-a08]=" + natW +
            " w[-9d8]=" + w + " h[-9d4]=" + h + " count[-968]=" + cnt);
      } catch (e) { log("page_attach hook ERROR: " + e); }
    }
  });

  // v11: slider call-site hooks removed — the slider's child window inits with parent==PrefWin
  // and now scales through the GraphicWin_init entry hook (keeping the sites would double-scale).
  // If the slider keeps separate native x/y/w copies for thumb math, that shows up as a thumb
  // misposition on the Audio/Visual page — measure there before adding anything.

  // ---- SHOW (PrefWin_show 0x48FA00, every open) ----
  // v3 BISECT: softlock with NO window visible -> suspects are the show-path mutations.
  // SCALE_SHOW=false keeps build scaling but makes show hooks LOG-ONLY (no rect writes, no rail arming).
  const SCALE_SHOW = true;   // v8: re-enabled — the invisibility was the rect-X corruption (now repaired at show entry)

  // trace show entry/leave + page arg + nesting (is the 2nd show nested inside the 1st?)
  // v5: also bracket the rect13c corruption — snapshot at show enter, and arm a write-watch
  // on PrefWin+0x13c..+0x148 for the duration of the show path to catch the writer's EIP.
  // v8: REPAIR instead of chasing the mover. Something scribbles a packed point over the
  // hidden window's rect X between build and show (v7's 18-site caller hunt wedged Quick
  // Start — abandoned). Popup_show natively re-asserts its position on EVERY show; give
  // PrefWin the same shape: at show entry, rewrite the outer rect to the lawful position
  // (direct +0x13c..+0x148 writes — exactly Win_move's non-caption body, no call needed).
  function repairPrefRect() {
    const g = gval();
    if (g <= 16) return;                          // native: leave everything alone
    const sw = SW.readS32(), sh = SH.readS32();
    const w = dw(PREFWIN, 0x144) - dw(PREFWIN, 0x13c);   // preserved width (L may be garbage; w survives)
    const h = dw(PREFWIN, 0x148) - dw(PREFWIN, 0x140);
    const nx = Math.floor(sw / 2) - S(350, g);
    const ny = sh - S(618, g);
    const before = r4(PREFWIN, 0x13c);
    PREFWIN.add(0x13c).writeS32(nx);
    PREFWIN.add(0x144).writeS32(nx + w);
    PREFWIN.add(0x140).writeS32(ny);
    PREFWIN.add(0x148).writeS32(ny + h);
    log("show-repair rect [" + before + "] -> [" + r4(PREFWIN, 0x13c) + "]");
  }
  // v9: `let showDepth` had been deleted in the v7 cleanup — strict-mode ReferenceError killed
  // this onEnter silently (Frida eats callback exceptions), so v8's repair never ran. Declare it,
  // and try/catch-log so a dead callback can never be silent again.
  let showDepth = 0;
  // v10: write each pref button's label font slot (btn+0x970) to the scaled font, the same slot
  // the baked thunk_comm_btnfont writes for COMMLINK buttons. Buttons seed the slot from the
  // native def-font at init (labels drew tiny + the flat fill is font-height-derived). We call
  // find_font ourselves (cdecl 0x5882F0, nearest-size match) on the game thread at show entry.
  // Provisional native size 14 (the build requests 10,12x3,14x3; buttons are the bold trio) —
  // the old-slot dump below is the measurement that confirms or corrects this next round.
  const findFont = new NativeFunction(VA(0x5882f0), 'pointer', ['int', 'int'], 'mscdecl');
  let dumpedOldFont = false;
  function prefFontFix() {
    const g = gval();
    if (g <= 16 || prefButtons.length === 0) return;
    const variant = (14 in ffVariants) ? ffVariants[14] : 0;
    const nf = findFont(S(14, g), variant);
    if (nf.isNull()) { log("prefFontFix: find_font(" + S(14, g) + "," + variant + ") = NULL, skipping"); return; }
    let wrote = 0;
    prefButtons.forEach((btn, i) => {
      // v13: write font1 ONLY (v11-proven: labels drew). v12's all-four write coincided with
      // rows 4-6 losing their labels entirely — slots +0x974..97C are natively 0 for these
      // buttons; seeding them changed the draw path. The tiny state-label question is
      // re-examined via btnROW forensics once chrome is correct.
      const olds = [0, 4, 8, 0xC].map(o => btn.add(0x970 + o).readPointer());
      if (!dumpedOldFont && !olds[0].isNull()) {
        dumpedOldFont = true;
        const d = [];
        for (let k = 0; k < 16; k++) d.push(olds[0].add(4 * k).readS32());
        log("old btn font @" + olds[0] + " dwords: " + JSON.stringify(d));
      }
      let w0 = false;
      if (!olds[0].isNull() && !olds[0].equals(nf)) { btn.add(0x970).writePointer(nf); w0 = true; }
      if (w0) wrote++;
      let nm = "<?>";
      try { const np = btn.add(0xA7C).readPointer(); nm = np.isNull() ? "<null>" : np.readCString(20); } catch (e) { }
      log("btn[" + i + "] " + btn + " name=\"" + nm + "\" fonts [" + olds.join(",") + "] -> " + nf);
    });
    log("prefFontFix: wrote " + wrote + "/" + prefButtons.length + " button font slots (find_font(" + S(14, g) + "," + variant + "))");
    // v12: field forensics on two buttons (idle btn[0], tiny-label btn[6] Gamma) — find which
    // field still holds the NATIVE fill height 20 (the flat fill draws 20px inside the 50px
    // window) and any state flags. Dump the Win rects + the BaseButton extension block.
    [0, 6].forEach(i => {
      if (i >= prefButtons.length) return;
      const b = prefButtons[i];
      const hex = (o, n) => { const a = []; for (let k = 0; k < n; k++) a.push((b.add(o + 4 * k).readU32() >>> 0).toString(16)); return a.join(","); };
      log("btnDUMP[" + i + "] rect13c=[" + r4(b, 0x13c) + "] rect14c=[" + r4(b, 0x14c) + "] rect474=[" + r4(b, 0x474) + "]");
      log("btnDUMP[" + i + "] bufWH=" + dw(b, 0x4c4) + "x" + dw(b, 0x4c8) + " A14..A50=" + hex(0xA14, 16));
      log("btnDUMP[" + i + "] A54..A90=" + hex(0xA54, 16) + " A94..AB4=" + hex(0xA94, 9));
    });
  }
  // v16: build-time button renders predate prefFontFix (labels tiny until a hover redraw) —
  // after fixing the font slots, drive each button's own refresh virtual (vtbl+0xF8, the same
  // call FUN_00491c00 uses); with the zoom gate + new font in place the redraw is correct.
  const redrawFns = {};
  function btnRedrawAll() {
    let n = 0;
    prefButtons.forEach((btn, i) => {
      try {
        const fnp = btn.readPointer().add(0xF8).readPointer();
        const key = fnp.toString();
        if (!redrawFns[key]) redrawFns[key] = new NativeFunction(fnp, 'void', ['pointer'], 'thiscall');
        redrawFns[key](btn);
        n++;
      } catch (e) { log("btnRedraw[" + i + "] ERROR: " + e); }
    });
    // v17: sliders too — their build-time render predates the zoom gates (tiny nub persists
    // until a repaint otherwise). Same refresh virtual.
    prefSliders.forEach((sl, i) => {
      try {
        const fnp = sl.readPointer().add(0xF8).readPointer();
        const key = fnp.toString();
        if (!redrawFns[key]) redrawFns[key] = new NativeFunction(fnp, 'void', ['pointer'], 'thiscall');
        redrawFns[key](sl);
        n++;
      } catch (e) { log("sliderRedraw[" + i + "] ERROR: " + e); }
    });
    log("btnRedrawAll: refreshed " + n + "/" + (prefButtons.length + prefSliders.length));
  }
  Interceptor.attach(VA(0x48fa00), {
    onEnter() {
      try {
        showDepth++;
        log("PrefWin_show ENTER page=" + this.context.esp.add(4).readS32() + " depth=" + showDepth);
        if (showDepth === 1) { installBoxSpriteRedirect(); repairPrefRect(); prefFontFix(); btnRedrawAll(); snapshotWinSys("show_enter"); }
      } catch (e) { log("PrefWin_show hook ERROR: " + e); }
    },
    onLeave() {
      try { log("PrefWin_show LEAVE depth=" + showDepth); showDepth--; }
      catch (e) { log("PrefWin_show leave ERROR: " + e); }
    }
  });

  // v13: Buffer_box_sprite chrome (frame x2 d690, interior panels x2 d7f8, gamma frame d690).
  // The callee entry 0x5E2DD3 is baked-detoured (thunk_hud_boxframe): Interceptor SITE hooks
  // here are hazard #7 and silently killed every one of these draws. Instead, retarget each
  // E8 rel32 (Memory.patchCode = the project's own call_target_redirect pattern, no trampoline)
  // to a hand-assembled stub: scale rect L,T,R,B in place x g/16 (g<=16 no-op), jmp real entry.
  // The rect is rebuilt on the caller's stack from NATIVE globals every call -> idempotent.
  // 5 show-time sites + the repaint helpers (right panel 0x49184d, gamma 0x4918b1) + the
  // full-refresh pair in FUN_00491c00 — all rebuild their rect from the native layout globals.
  const BOX_SITES = [0x48fb19, 0x48fb29, 0x48fb39, 0x48fbb7, 0x48fc01,
                     0x49184d, 0x4918b1, 0x491c42, 0x491c8c];
  let boxRedirected = false;
  function installBoxSpriteRedirect() {
    if (boxRedirected || !SCALE_SHOW) return;
    boxRedirected = true;
    const g = gval();
    if (g <= 16) { log("boxsprite-redirect: g<=16, leaving native"); return; }
    const target = VA(0x5e2dd3);
    // v19: after scaling the rect, DON'T tail into plain Buffer_box_sprite (native 1px
    // strokes stretched in length only — user-flagged; measured 1px vs law K=half_down(g,16)).
    // Dispatch on the sprite-set fill field [params+0x20] like thunk_factionwin_framecover:
    // filled -> thunk_box_thick_devfill (device-density dither interior + thick strokes),
    // hollow -> thunk_box_thick_hollow_flat (band-map K-wide strokes, flat footprint).
    // Both are RET 8 drop-ins for a Buffer_box_sprite call with their own g<=16 native tails;
    // our g<=16 path still goes straight to the plain entry (zero delta at low res).
    const HOLLOW_FLAT = VA(0xa0c000 + 0x140);   // thunk_box_thick_hollow_flat
    const DEVFILL = VA(0xa0c000 + 0x42a0);      // thunk_box_thick_devfill v2
    const stub = Memory.alloc(Process.pageSize);
    globalThis._bsStub = stub;                 // pin — Memory.alloc frees on GC
    const d32 = v => [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff];
    const code = [
      0x50, 0x51, 0x52,                                     //  0: push eax/ecx/edx
      0x8B, 0x44, 0x24, 0x10,                               //  3: mov eax,[esp+0x10]  (rect*)
      0x8B, 0x0D, ...d32(G_PSN.toUInt32()),                 //  7: mov ecx,[g_popup_scale_num]
      0x83, 0xF9, 0x10,                                     // 13: cmp ecx,16
      0x7E, 0x47,                                           // 16: jle -> native pops (@89)
      0x8B, 0x10,       0x0F, 0xAF, 0xD1, 0xC1, 0xFA, 0x04, 0x89, 0x10,        // 18: L
      0x8B, 0x50, 0x04, 0x0F, 0xAF, 0xD1, 0xC1, 0xFA, 0x04, 0x89, 0x50, 0x04,  // 28: T
      0x8B, 0x50, 0x08, 0x0F, 0xAF, 0xD1, 0xC1, 0xFA, 0x04, 0x89, 0x50, 0x08,  // 40: R
      0x8B, 0x50, 0x0C, 0x0F, 0xAF, 0xD1, 0xC1, 0xFA, 0x04, 0x89, 0x50, 0x0C,  // 52: B
      0x5A, 0x59, 0x58,                                     // 64: pop edx/ecx/eax
      0x50,                                                 // 67: push eax
      0x8B, 0x44, 0x24, 0x0C,                               // 68: mov eax,[esp+0xC]  (params)
      0x83, 0x78, 0x20, 0x00,                               // 72: cmp dword [eax+0x20],0
      0x58,                                                 // 76: pop eax
      0x75, 0x05,                                           // 77: jne filled (@84)
      0xE9, 0, 0, 0, 0,                                     // 79: jmp thunk_box_thick_hollow_flat
      0xE9, 0, 0, 0, 0,                                     // 84: jmp thunk_box_thick_devfill
      0x5A, 0x59, 0x58,                                     // 89: native: pop edx/ecx/eax
      0xE9, 0, 0, 0, 0                                      // 92: jmp Buffer_box_sprite entry
    ];
    code.splice(80, 4, ...d32(HOLLOW_FLAT.sub(stub.add(79 + 5)).toInt32() >>> 0));
    code.splice(85, 4, ...d32(DEVFILL.sub(stub.add(84 + 5)).toInt32() >>> 0));
    code.splice(93, 4, ...d32(target.sub(stub.add(92 + 5)).toInt32() >>> 0));
    stub.writeByteArray(code);
    Memory.protect(stub, Process.pageSize, 'r-x');
    let ok = 0;
    BOX_SITES.forEach(a => {
      const site = VA(a);
      if (site.readU8() !== 0xE8 || !site.add(5).add(site.add(1).readS32()).equals(target)) {
        log("boxsprite-redirect: site 0x" + a.toString(16) + " bytes UNEXPECTED, skipped");
        return;
      }
      const rel = stub.sub(site.add(5)).toInt32();
      Memory.patchCode(site, 5, p => { p.writeU8(0xE8); p.add(1).writeS32(rel); });
      ok++;
    });
    log("boxsprite-redirect: stub @" + stub + " armed at " + ok + "/" + BOX_SITES.length + " sites (g=" + g + ")");
    installCheckboxRedirect(g);
  }

  // v14: PrefWin page rows draw their checkbox x sprite via FUN_0060f030's two
  // FUN_005e4b4a(dest,sprite,x,y,num,den) calls with hardcoded num/den=1,1 (the pair the
  // baked set left status:skip — popups use the 0x405bd4 custom-draw path instead, PrefWin
  // does not). Retarget both to a stub replicating baked thunk_checkbox_scale: num=g, den=16,
  // y += (16-g)/2 (native 16px sprite re-centered in the scaled row), tail-jmp FUN_005e4b4a.
  const CB_SITES = [0x60f41c, 0x60f457];
  function installCheckboxRedirect(g) {
    const target = VA(0x5e4b4a);
    const stub = Memory.alloc(Process.pageSize);
    globalThis._cbStub = stub;                 // pin — Memory.alloc frees on GC
    const d32 = v => [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff];
    const gAddr = d32(G_PSN.toUInt32());
    const code = [
      0x50,                                    // push eax
      0xB8, 0x10, 0x00, 0x00, 0x00,            // mov eax,16
      0x2B, 0x05, ...gAddr,                    // sub eax,[g_popup_scale_num]
      0xD1, 0xF8,                              // sar eax,1            (= (16-g)/2, 0 at g=16)
      0x01, 0x44, 0x24, 0x14,                  // add [esp+0x14],eax   (y)
      0xA1, ...gAddr,                          // mov eax,[g_popup_scale_num]
      0x89, 0x44, 0x24, 0x18,                  // mov [esp+0x18],eax   (num)
      0xC7, 0x44, 0x24, 0x1C, 0x10, 0x00, 0x00, 0x00,  // mov dword [esp+0x1C],16 (den)
      0x58,                                    // pop eax
      0xE9, 0, 0, 0, 0                         // jmp FUN_005e4b4a
    ];
    const jmpOff = code.length - 5;
    code.splice(jmpOff + 1, 4, ...d32(target.sub(stub.add(jmpOff + 5)).toInt32() >>> 0));
    stub.writeByteArray(code);
    Memory.protect(stub, Process.pageSize, 'r-x');
    let ok = 0;
    CB_SITES.forEach(a => {
      const site = VA(a);
      if (site.readU8() !== 0xE8 || !site.add(5).add(site.add(1).readS32()).equals(target)) {
        log("checkbox-redirect: site 0x" + a.toString(16) + " bytes UNEXPECTED, skipped");
        return;
      }
      const rel = stub.sub(site.add(5)).toInt32();
      Memory.patchCode(site, 5, p => { p.writeU8(0xE8); p.add(1).writeS32(rel); });
      ok++;
    });
    log("checkbox-redirect: stub @" + stub + " armed at " + ok + "/" + CB_SITES.length + " sites (g=" + g + ")");
  }

  // ---- v16: PrefWin buttons route through the baked popup zoom (thunk_btn_shrink @0x607e7f
  // + thunk_btn_2dscale @0x608365, gated on g_popup_active @pcave2+0x530). The one vtable
  // slot holding FlatButton_content_draw (0x607e50) is [0x669784]; repoint it (data write) to
  // a stub that sets the gate for ecx in the PrefWin widget cluster only, forwards, clears.
  const G_POPUP_ACTIVE = VA(0xa0c530);
  function installBtnZoomGate() {
    const slot = VA(0x669784);
    const cd = VA(0x607e50);
    if (!slot.readPointer().equals(cd)) {
      log("btn-zoom-gate: vtable slot holds " + slot.readPointer() + " (expected " + cd + "), SKIPPING");
      return;
    }
    const stub = Memory.alloc(Process.pageSize);
    globalThis._zoomStub = stub;               // pin — Memory.alloc frees on GC
    const d32 = v => [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff];
    const code = [
      0x81, 0xF9, ...d32(VA(0x858338).toUInt32()),          //  0: cmp ecx, first pref button
      0x72, 0x22,                                           //  6: jb plain
      0x81, 0xF9, ...d32(VA(0x872140).toUInt32()),          //  8: cmp ecx, last pref button
      0x77, 0x1A,                                           // 14: ja plain
      0xC7, 0x05, ...d32(G_POPUP_ACTIVE.toUInt32()), 0x01, 0x00, 0x00, 0x00,  // 16: mov [ga],1
      0xE8, 0, 0, 0, 0,                                     // 26: call content_draw
      0xC7, 0x05, ...d32(G_POPUP_ACTIVE.toUInt32()), 0x00, 0x00, 0x00, 0x00,  // 31: mov [ga],0
      0xC3,                                                 // 41: ret
      0xE9, 0, 0, 0, 0                                      // 42: plain: jmp content_draw
    ];
    code.splice(27, 4, ...d32(cd.sub(stub.add(26 + 5)).toInt32() >>> 0));
    code.splice(43, 4, ...d32(cd.sub(stub.add(42 + 5)).toInt32() >>> 0));
    stub.writeByteArray(code);
    Memory.protect(stub, Process.pageSize, 'r-x');
    Memory.patchCode(slot, 4, p => p.writePointer(stub));
    log("btn-zoom-gate: vtable slot 0x669784 -> stub @" + stub + " (gate " + VA(0x858338) + ".." + VA(0x872140) + ")");
  }
  installBtnZoomGate();

  // v17: the slider NUB is a grip sprite drawn 1:1 by ScrollBar_draw (site 0x6067ED, already
  // baked-redirected to thunk_sb_thumb which scales+recenters it — but gated on
  // g_netwin_active). ScrollBar_draw also drives the arrow buttons (vtbl+0xF8 from inside).
  // Swap the one ScrollBar_draw vtable slot [0x669d88] to a stub that sets g_netwin_active=1
  // around the draw for the FOUR PrefWin sliders only: sb_thumb scales the nub, and btn_gate's
  // netwin branch approves the label-less arrows for the shrink/2D-zoom.
  const G_NETWIN_ACTIVE = VA(0xa10800);
  const SLIDER_ADDRS = [0x862064, 0x8641b0, 0x8662fc, 0x868448];
  function installSliderZoomGate() {
    const slot = VA(0x669d88);
    const sbd = VA(0x6066f0);
    if (!slot.readPointer().equals(sbd)) {
      log("slider-zoom-gate: vtable slot holds " + slot.readPointer() + " (expected " + sbd + "), SKIPPING");
      return;
    }
    const stub = Memory.alloc(Process.pageSize);
    globalThis._sbStub = stub;                 // pin — Memory.alloc frees on GC
    const d32 = v => [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff];
    const code = [
      0x81, 0xF9, ...d32(VA(SLIDER_ADDRS[0]).toUInt32()), 0x74, 0x1D,   //  0: cmp/je go(@37)
      0x81, 0xF9, ...d32(VA(SLIDER_ADDRS[1]).toUInt32()), 0x74, 0x15,   //  8
      0x81, 0xF9, ...d32(VA(SLIDER_ADDRS[2]).toUInt32()), 0x74, 0x0D,   // 16
      0x81, 0xF9, ...d32(VA(SLIDER_ADDRS[3]).toUInt32()), 0x74, 0x05,   // 24
      0xE9, 0, 0, 0, 0,                                                 // 32: jmp ScrollBar_draw
      0xC7, 0x05, ...d32(G_NETWIN_ACTIVE.toUInt32()), 0x01, 0x00, 0x00, 0x00,  // 37: mov [nw],1
      0xE8, 0, 0, 0, 0,                                                 // 47: call ScrollBar_draw
      0xC7, 0x05, ...d32(G_NETWIN_ACTIVE.toUInt32()), 0x00, 0x00, 0x00, 0x00,  // 52: mov [nw],0
      0xC3                                                              // 62: ret
    ];
    code.splice(33, 4, ...d32(sbd.sub(stub.add(32 + 5)).toInt32() >>> 0));
    code.splice(48, 4, ...d32(sbd.sub(stub.add(47 + 5)).toInt32() >>> 0));
    stub.writeByteArray(code);
    Memory.protect(stub, Process.pageSize, 'r-x');
    Memory.patchCode(slot, 4, p => p.writePointer(stub));
    log("slider-zoom-gate: vtable slot 0x669d88 -> stub @" + stub);
  }
  installSliderZoomGate();

  // v18: route the PrefWin family's slide calls through the baked rail-scale wrappers.
  const RAILSHOW = VA(0xa0c000 + 0x3550);   // thunk_popup_railshow
  const RAILHIDE = VA(0xa0c000 + 0x44d0);   // thunk_popup_railhide
  function installRailRedirects() {
    const jobs = [
      { site: 0x48fc66, orig: VA(0x45d440), thunk: RAILSHOW, tag: "show@PrefWin_show" },
      { site: 0x492700, orig: VA(0x45d440), thunk: RAILSHOW, tag: "show@0x4926xx" },
      { site: 0x48ff12, orig: VA(0x45d970), thunk: RAILHIDE, tag: "hide@PrefWin_hide" },
      { site: 0x4927a0, orig: VA(0x45d970), thunk: RAILHIDE, tag: "hide@0x4926xx" },
    ];
    let ok = 0;
    jobs.forEach(j => {
      const site = VA(j.site);
      if (site.readU8() !== 0xE8 || !site.add(5).add(site.add(1).readS32()).equals(j.orig)) {
        log("rail-redirect: site 0x" + j.site.toString(16) + " (" + j.tag + ") bytes UNEXPECTED, skipped");
        return;
      }
      const rel = j.thunk.sub(site.add(5)).toInt32();
      Memory.patchCode(site, 5, p => { p.writeU8(0xE8); p.add(1).writeS32(rel); });
      ok++;
    });
    log("rail-redirect: " + ok + "/4 slide sites -> baked rail wrappers");
  }
  installRailRedirects();

  // ---- v15: button-band census + speculative fix. The band drawer writes a native-height
  // (~20px) top-anchored region into the button's own buffer. Hook the un-detoured fill/tile
  // primitives at ENTRY, gate on the 15 button buffers, log (fn, ret, args), and scale the
  // unambiguous band case in place (y,h x g/16; g<=16 no-op by gval gate).
  const SCALE_BANDS = false;   // v16: zoom machinery owns the art; hooks below are census-only
  function btnBufIndex(ecx) {
    for (let i = 0; i < prefButtons.length; i++) if (ecx.equals(prefButtons[i].add(0x444))) return i;
    return -1;
  }
  const bandSeen = {};
  function bandLog(key, msg) {
    bandSeen[key] = (bandSeen[key] || 0) + 1;
    if (bandSeen[key] <= 4) log(msg);
  }
  // Buffer_fill_3(this; rect*, color)
  Interceptor.attach(VA(0x5dfcd0), {
    onEnter() {
      try {
        if (prefButtons.length === 0) return;
        const i = btnBufIndex(this.context.ecx);
        if (i < 0) return;
        const g = gval(), sp = this.context.esp;
        const rect = sp.add(4).readPointer(), color = sp.add(8).readS32();
        const b = [0, 4, 8, 12].map(o => rect.add(o).readS32());
        const h = b[3] - b[1];
        let did = "";
        if (SCALE_BANDS && g > 16 && b[1] <= 2 && h >= 16 && h <= 24) {
          rect.add(4).writeS32(S(b[1], g));
          rect.add(12).writeS32(S(b[3], g));
          did = " BAND-SCALED -> [" + [0, 4, 8, 12].map(o => rect.add(o).readS32()) + "]";
        }
        bandLog("f3:" + this.returnAddress, "fill_3 btn[" + i + "] ret=" + this.returnAddress + " rect=[" + b + "] color=" + color + did);
      } catch (e) { log("fill_3 hook ERROR: " + e); }
    }
  });
  // Buffer_fill(this; x, y, w, h, color)
  Interceptor.attach(VA(0x5d8240), {
    onEnter() {
      try {
        if (prefButtons.length === 0) return;
        const i = btnBufIndex(this.context.ecx);
        if (i < 0) return;
        const g = gval(), sp = this.context.esp;
        const a = [4, 8, 0xC, 0x10, 0x14].map(o => sp.add(o).readS32());
        let did = "";
        if (SCALE_BANDS && g > 16 && a[1] <= 2 && a[3] >= 16 && a[3] <= 24) {
          sp.add(8).writeS32(S(a[1], g));
          sp.add(0x10).writeS32(S(a[3], g));
          did = " BAND-SCALED y/h -> " + S(a[1], g) + "/" + S(a[3], g);
        }
        bandLog("fl:" + this.returnAddress, "fill btn[" + i + "] ret=" + this.returnAddress + " xywh=[" + a.slice(0, 4) + "] color=" + a[4] + did);
      } catch (e) { log("fill hook ERROR: " + e); }
    }
  });
  // Buffer_tile_2(this; src, a3, a4, x, y, W, H)
  Interceptor.attach(VA(0x5da9f0), {
    onEnter() {
      try {
        if (prefButtons.length === 0) return;
        const i = btnBufIndex(this.context.ecx);
        if (i < 0) return;
        const g = gval(), sp = this.context.esp;
        const a = [4, 8, 0xC, 0x10, 0x14, 0x18, 0x1C].map(o => sp.add(o).readS32());
        let did = "";
        const y = a[4], H = a[6];
        if (SCALE_BANDS && g > 16 && y <= 2 && H >= 16 && H <= 24) {
          sp.add(0x14).writeS32(S(y, g));
          sp.add(0x1C).writeS32(S(H, g));
          did = " BAND-SCALED y/H -> " + S(y, g) + "/" + S(H, g);
        }
        bandLog("t2:" + this.returnAddress, "tile_2 btn[" + i + "] ret=" + this.returnAddress + " src=" + a[0].toString(16) + " a3/a4=" + a[1] + "/" + a[2] + " xyWH=[" + a.slice(3) + "]" + did);
      } catch (e) { log("tile_2 hook ERROR: " + e); }
    }
  });
  // Buffer_box_2(this; rect*, cH, cV) — outline; LOG-ONLY
  Interceptor.attach(VA(0x5e3203), {
    onEnter() {
      try {
        if (prefButtons.length === 0) return;
        const i = btnBufIndex(this.context.ecx);
        if (i < 0) return;
        const sp = this.context.esp;
        const rect = sp.add(4).readPointer();
        const b = [0, 4, 8, 12].map(o => rect.add(o).readS32());
        bandLog("b2:" + this.returnAddress, "box_2 btn[" + i + "] ret=" + this.returnAddress + " rect=[" + b + "] cH=" + sp.add(8).readS32() + " cV=" + sp.add(0xC).readS32());
      } catch (e) { log("box_2 hook ERROR: " + e); }
    }
  });

  // ---- v4 DIAGNOSTICS: window composites through GraphicWin_on_paint (vtbl+0x124), which
  // clips children vs the PARENT (MapWin) rect. Snapshot everything at slide time.
  const MAPWIN_G = VA(0x9156b0);
  const GAMEPREFS = VA(0x9a6490);
  const ANIM_SUPP = VA(0x93f660);
  const PREFBUF = PREFWIN.add(0x444);
  const dw = (p, o) => p.add(o).readS32();
  const r4 = (p, o) => [0, 4, 8, 12].map(k => dw(p, o + k)).join(",");

  // v12: pixel forensics on the window buffer — the interior renders as a translucent scanline
  // mesh instead of pristine's opaque panel. Run-length three rows and histogram them: if the
  // mesh alternates <dark,9> pairs the backdrop art/remap put TRANSPARENT (key-9) members into
  // the fill; the row pattern says which mechanism (scanline synthesis = whole rows keyed).
  function rleRow(y) {
    try {
      const data = PREFBUF.add(0x54).readPointer();
      const stride = PREFBUF.add(0x4a8).readS32();
      const w = PREFBUF.add(0x80).readS32();
      if (data.isNull() || stride <= 0 || w <= 0) { log("rleRow(" + y + "): bad buf data=" + data + " stride=" + stride + " w=" + w); return; }
      const row = data.add(y * stride).readByteArray(Math.min(w, 1400));
      const b = new Uint8Array(row);
      const hist = {};
      for (let i = 0; i < b.length; i++) hist[b[i]] = (hist[b[i]] || 0) + 1;
      const top = Object.entries(hist).sort((p, q) => q[1] - p[1]).slice(0, 6).map(e => e[0] + "x" + e[1]).join(" ");
      let rle = "", cur = b[700], n = 1, parts = 0;
      for (let i = 701; i < 800 && parts < 20; i++) {
        if (b[i] === cur) n++; else { rle += cur + ":" + n + " "; cur = b[i]; n = 1; parts++; }
      }
      rle += cur + ":" + n;
      log("bufrow y=" + y + " top[" + top + "] mid700-800 RLE: " + rle);
    } catch (e) { log("rleRow ERROR: " + e); }
  }

  // v13: per-button buffer forensics — histogram each button's own buffer mid-row to tell
  // "label never drawn" (fill index only) from "drawn but invisible" (glyph indices present).
  function btnRows() {
    prefButtons.forEach((btn, i) => {
      try {
        const buf = btn.add(0x444);
        const data = buf.add(0x54).readPointer();
        const stride = buf.add(0x4a8).readS32();
        const w = buf.add(0x80).readS32();
        const h = Math.abs(buf.add(0x84).readS32());
        if (data.isNull() || stride <= 0 || w <= 0 || h <= 0) { log("btnROW[" + i + "] bad buf w=" + w + " h=" + h); return; }
        [10, h >> 1, h - 5].forEach(y => {
          const b = new Uint8Array(data.add(y * stride).readByteArray(Math.min(w, 600)));
          const hist = {};
          for (let k = 0; k < b.length; k++) hist[b[k]] = (hist[b[k]] || 0) + 1;
          const top = Object.entries(hist).sort((p, q) => q[1] - p[1]).slice(0, 5).map(e => e[0] + "x" + e[1]).join(" ");
          log("btnROW[" + i + "] " + w + "x" + h + " y=" + y + " top[" + top + "]");
        });
      } catch (e) { log("btnROW[" + i + "] ERROR: " + e); }
    });
  }

  function snapshotWinSys(tag) {
    try {
      const inner = MAPWIN_G.readPointer();
      const mapwin = inner.isNull() ? ptr(0) : MAPWIN_G.add(inner.add(4).readS32());
      log("SNAP[" + tag + "] PrefWin rect474=[" + r4(PREFWIN, 0x474) + "] buf4c4=" + dw(PREFWIN, 0x4c4) + "x" + dw(PREFWIN, 0x4c8) +
          " flags98=0x" + (dw(PREFWIN, 0x98) >>> 0).toString(16) + " flags9c=0x" + (dw(PREFWIN, 0x9c) >>> 0).toString(16));
      log("SNAP[" + tag + "] PrefWin rect13c=[" + r4(PREFWIN, 0x13c) + "] rect14c=[" + r4(PREFWIN, 0x14c) + "]");
      if (!mapwin.isNull()) {
        log("SNAP[" + tag + "] MapWin@" + mapwin + " rect474=[" + r4(mapwin, 0x474) + "] rect13c=[" + r4(mapwin, 0x13c) +
            "] rect14c=[" + r4(mapwin, 0x14c) + "] flags98=0x" + (dw(mapwin, 0x98) >>> 0).toString(16));
      }
      log("SNAP[" + tag + "] GamePrefs=0x" + (GAMEPREFS.readS32() >>> 0).toString(16) +
          " slideBit(0x8000000)=" + ((GAMEPREFS.readS32() & 0x8000000) !== 0) + " animSupp[93f660]=" + ANIM_SUPP.readS32());
    } catch (e) { log("SNAP ERROR: " + e); }
  }

  // every composite of PrefWin's buffer, anywhere (dest, pos, scale)
  let bd2Count = 0;
  Interceptor.attach(VA(0x5d84c0), {
    onEnter() {
      try {
        if (!this.context.ecx.equals(PREFBUF)) return;
        bd2Count++;
        if (bd2Count <= 12 || bd2Count % 128 === 0) {
          const sp = this.context.esp;
          log("Buffer_draw_2(PrefWinBuf) #" + bd2Count + " dest=" + sp.add(4).readPointer() +
              " key=" + sp.add(8).readS32() + " x=" + sp.add(0xC).readS32() + " y=" + sp.add(0x10).readS32() +
              " num/den=" + sp.add(0x14).readS32() + "/" + sp.add(0x18).readS32());
        }
      } catch (e) { log("bd2 ERROR: " + e); }
    }
  });

  // every compositor paint of PrefWin (default vtbl+0x124)
  let opCount = 0;
  Interceptor.attach(VA(0x5d5cf0), {
    onEnter() {
      try {
        if (!this.context.ecx.equals(PREFWIN)) return;
        opCount++;
        if (opCount <= 8 || opCount % 256 === 0) {
          const clip = this.context.esp.add(4).readPointer();
          log("GraphicWin_on_paint(PrefWin) #" + opCount + " clip=[" + (clip.isNull() ? "null" : r4(clip, 0)) + "]");
        }
      } catch (e) { log("on_paint ERROR: " + e); }
    }
  });

  // slide_show rail arming (thunk_popup_railshow pattern), entry attach @0x45D440.
  // v12: ARM_RAILS=false — PRIME SUSPECT for the translucent-mesh interior. Arming
  // g_filedlg_active makes the baked file-dialog machinery treat PREFBUF as a file-dialog
  // backdrop, whose aesthetic IS a synthesized translucent scanline dither written INTO the
  // buffer (persists after disarm). Pristine PrefWin is OPAQUE. Also: pixel-forensic the
  // buffer right before the slide and again 3s later.
  const ARM_RAILS = false;
  Interceptor.attach(VA(0x45d440), {
    onEnter(args) {
      this.armed = false;
      const win = args[0];
      if (!win.equals(PREFWIN)) return;
      // v18: if the rail-redirect wrapper armed the gate, we're inside its bracket here.
      log("slide_enter rail-gate: g_filedlg_active=" + G_FDACT.readS32() + " g_fd_winbuf=" + G_FDBUF.readPointer() +
          " (expect 1 / " + PREFWIN.add(0x444) + " when armed)");
      snapshotWinSys("slide_enter");
      [60, 487, 900].forEach(rleRow);
      setTimeout(() => {
        snapshotWinSys("slide+3s"); log("counts: on_paint=" + opCount + " buf_draws=" + bd2Count);
        [60, 487, 900].forEach(rleRow);
        btnRows();
      }, 3000);
      const g = G_PSN.readS32();
      if (g <= 16) return;
      if (!ARM_RAILS) { log("slide_show(PrefWin) g=" + g + " (rails NOT armed, v12 bisect)"); return; }
      if (G_FDACT.readS32() !== 0) { log("slide_show(PrefWin): filedlg already active, NOT arming"); return; }
      if (!SCALE_SHOW) { log("slide_show(PrefWin) g=" + g + " (LOG-ONLY, not arming)"); return; }
      this.saved = G_FDBUF.readPointer();
      G_FDBUF.writePointer(win.add(0x444));
      G_FDACT.writeS32(1);
      this.armed = true;
      log("slide_show(PrefWin) ARMED rails g=" + g + " winbuf=" + win.add(0x444));
    },
    onLeave() {
      if (this.armed) {
        G_FDACT.writeS32(0);
        G_FDBUF.writePointer(this.saved);
        log("slide_show(PrefWin) DISARMED");
      }
    }
  });

  log("all hooks installed (g now=" + G_PSN.readS32() + ", SW=" + SW.readS32() + ", SH=" + SH.readS32() + ")");
}
