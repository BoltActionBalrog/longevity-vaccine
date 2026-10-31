---
name: project-smac-datalinks
description: Datalinks encyclopedia screen — ARC CLOSED, USER-VERIFIED ALL-RES 2026-09-01 build 43f0c3d9 (dl_scale + portrait/wheel + flow-scroll + poke-addr + palette-source + key-exclusion + btn_ringfix hover ring)
type: project
---

# Datalinks (DatalinkWin 0x703EA0) — BAKED 2026-08-30, build **dff1321b20fa16477c08eac3b362b49a**

## 2026-09-22c wheel v2: the article's own scroll box takes the notch under the cursor (live bd2bae0b, USER-VERIFIED all res, COMMITTED+PUSHED 94815eb)
- User rule: the category picker captures the wheel ANYWHERE on the screen, except that over an article with a sub-scroll box (or over the article window) the sub-scroll captures it. The old head always took the list's bar first, so a long article under a long list could never be wheel-scrolled.
- t_dl_wheel_down v2 (415B, src assemble_dl.py asm_dl_wheel_down; PINNED at pcave2+0x13DB0 via assemble_dl.PINNED because the 352 B slot at 0x230B0 was outgrown and splice_dl.py is not re-runnable -- the entry was ported byte-safely; 0x230B0..0x23210 is FREE): reads the cursor (IAT GetCursorPos/ScreenToClient + G_HWND, as t_bw/t_ntw do), tests cursor - DL origin (+0x13C) against right_container +0x103B4 (DL-local, device after the build walker) -> try TS_FULL/TS_LOWER/TS_LOWER800 (visible +0x9C bit0 && bar open && max > min); else cursor - MainWin origin against the console text box +0x10374 -> try TS_CONSOLE; else (or nothing engaged under the cursor) the old order: list bar first, then any visible engaged TS. `try_ts` is a local helper that drops its own return address on a hit. ebx (chevron id) is fixed before the cursor calls clobber edx.
- t_rw_wheel_down chains to it by a LITERAL E9 rel32 (assemble_rw.DL_WHEEL_DOWN + the yaml tail bytes `E9 A8 FC FE FF`); t_dl_wheel_up unchanged at 0x23210. No uimod.dll change: PRACX posts the Datalinks arrows itself (the DL vtbl is not in wheel.cpp's capture set).
- Parity: test_dl_asm_parity.py wheel_env(cursor=) with IAT stubs; 28 wheel tests incl. half-open panel edges, hidden-text fallback, console-box routing, off-panel = list.

## 2026-09-19 tech-page side-button regression FIX (live da5dc96f, COMMITTED+PUSHED 07d202a, CLOSED; user-shot + MEASURED 4K/1600: groups -8.40/-8.32 native vs box centre = vanilla -8.0; F2 tree unchanged; 1920 not shot)
- Symptom (user shots): prereq/leads-to buttons + connectors below the centre box (+225 dev px at 1600, +26 at 4K; box itself correct). Vanilla law (measured on pristine): box centre fixed, side groups a constant 8 native ABOVE it, independent of box height/facility lines.
- Root cause: 7b4588e (2026-09-04 rw_scale_shared) t_rw_init_leave permanently stores DEVICE textB (RW+0x5980) / lineH (RW+0xE268); t_dl_techwrap still relative-scaled them, and its `<=800`/`<=64` magnitude guards made it resolution-dependent (4K textB skipped by accident). See [[feedback-shared-field-one-owner]].
- Fix: techwrap scales only the vanilla state `textB + 0x35 == win_h (RW+0xA20)` (law scaling_laws.dl_tech_inputs; thunk 192->186B same offset 0x22d60, nothing moved). splice_dl.py is NO LONGER re-runnable (pcave2 length line grew) — port single entries byte-safely instead.

## 2026-08-30c addendum: article flow-scroll VANILLA-bug fix (user 4K shot)
- **Symptom**: scrolling an article re-flowed its line breaks mid-scroll, and the top line could be
  raw markup ("Collectors=90003>") — a $LINK tag's tail with the opener scrolled off. **Root cause**:
  conceptsx/help text hard-wraps paragraphs across FILE lines and tags straddle them ($LINK<Solar ⏎
  Collectors=90003>); TextList nodes = file lines; `Buffer_write_strings` renders them as a FLOW
  (payload flag 0 = continue the previous line; g_wrap_width_used carries x, buf+0x51C the tag parse);
  the scrolled TextScroll_draw entered that flow at node k with FRESH state → different breaks +
  orphaned tag halves. Scroll unit was a NODE (finish wrote bar max = node count → TS+0x1444).
- **Fix (site ts.flowdraw @0x629C26 E8→t_ts_flowdraw + t_ts_cache, group dl_scale)**: for the 4 DL
  TextScrolls with first_line k≥0: lazy cache (g_ts_flowcache pcave2+0x2A000, keyed ts/width/headptr/
  count — self-heals on article switch and bar-reserve width flips) stores per PARAGRAPH HEAD (idx 0
  or payload flag≠0) its cum_px = H0 − H(head..end), both via the engine's own
  Buffer_write_strings_height (0x5DAD70, thiscall RET 0xC, flags&2 keeps cursor); repoints bar range
  min0/max=totalLines−visible/page=visible−1 (TS+0x1440/44/60, AFTER finish so no stomp). Draw: clamp
  k, pick last head with cum_px ≤ k·lineH, set list cursor to it, y0 = cum_px − k·lineH ≤ 0 (GDI
  TextOutA clips negative y — verified in Buffer_write_raw_l 0x5DBD00). Breaks now always match the
  canonical top-down flow; links bounded like vanilla (flow starts at the paragraph, not article, top).
  Negative k (bottom-anchored consoles) and non-DL TSs pass through untouched. pcave2 → 0x2B000.
- **OPEN (diagnosed only): BACK/EXIT hover highlight stroke non-uniform** (4K measured: top 2/left 2/
  right 3/bottom 1px): the DL buttons render native + NN 2D zoom (popup_button_2dzoom); centre-aligned
  NN duplicates the native 1px bevel unevenly + bottom hits the last-row-drop class. Fix direction:
  post-zoom device-density border overdraw (or edge regeneration); WING_FACES sets (0x78D960/88/B0)
  are RUNTIME-built (not in the file image) — probe the hover set composition first.

## 2026-09-01d hover-ring FIX BAKED (build 43f0c3d9, commit 7ea079e)
- thunk_btn_ringfix @pcave2+0x1C800 (678B, src assemble_ringfix.py, law scaling_laws.btn_ring_k, parity test_ringfix_parity.py): thunk_btn_2dscale's internal E8 (pcave2+0x4D1) retargeted stripes->ringfix; wrapper calls thunk_btn_stripes then overdraws K=ceil(g/16) strokes, per-edge colour from the BoxSpriteParams strip art (7/9 = no stroke -> idle/pressed untouched), KxK key-9 notches when corner art keyed + any edge drew. PROCESS WIN: prototyped by runtime-injecting the IDENTICAL assembled bytes (hook_dl_ringfix_proto2.js patches the one rel32 to a retained RWX stub — the tail-retarget-as-DATA pattern; a poll-write proto LOST the redraw race and must not be trusted for draw-path fixes). Pixel-measured shots (4K: 3px uniform) / 014808 (1600: 2px uniform), zero 225, notches ok.
- VERIFIED on the baked build 2026-09-01 (plain launches, 4 screenshots, all measured): 4K + 1600 frames BYTE-IDENTICAL (PNG MD5) to the proto shots; 1920 g22 EXIT ring 2px uniform on all four edges (thickness set {2}, perimeter carries only ring 120/164/212 + face stripes — zero pair-mate), 2x2 key notches at all four corners; 1024 g16 native 1px ring + 1x1 corner key = no-op gate holds. Idle BACK next to hovered EXIT unchanged in the same shots. **ARC CLOSED.**

## 2026-09-01c hover-border ROOT CAUSE (probe complete, fix NOT yet built)
- Probe: hook_dl_hoverbevel.js — ZERO-Interceptor setInterval poll (the popup-button-zoom chain is Frida-untouchable per [[feedback-frida-attach-branch-target]]); runs at g=16/25/40. State fields found: FlatButton +0xA74 hover, +0xA9C pressed, +0xAB8 forced 0..2; draw state law decoded from disasm 0x607EC8.
- DL BACK/EXIT/wings draw via the BoxSpriteParams path (+0xAC8[state] = 0x78D960/88/B0 shared with the HUD toolbar; Buffer_box_sprite through baked t_dl_btnrect @0x607F60=pcave2+0x22CF0) and this path SKIPS the bevel loop (jmp 0x608365). Bevel fields +0xA88/8C/90 = 73/147/2 are UNUSED for these buttons.
- The hover ring art is CLEAN at every g: 1px solid idx 224 strokes on all four edges (corners 6x6 keyed, strips 24x6/6x24, interior idx 7 pass-through), identical at g16 and g40 — NO 225 anywhere in art or engine draw.
- ROOT CAUSE of the asymmetry: TWO stacked defects of OUR 2dzoom pipeline. (1) NN zoom duplicates the 1px ring unevenly (top/left 2 dev px, bottom/right 3 at g40 — centre-NN phase). (2) thunk_fe_pair_remap treats blue 0xE0/0xE1 (=224/225) UNCONDITIONALLY (patches.yaml ~line 2342: 'E0/E1 + teal AE/EE unconditional, navy 41/C4 content-keyed') — the post-zoom restripe converts the SOLID-224 ring into P-law stripe bands: top/left rows land in 224 bands (bright), bottom/right in 225 bands (dark). The DL hover ring is the first surface with a legitimate solid 224 stroke through that tail = the [[feedback-dither-pair-ambiguity]] class (navy already got the mate-presence pre-scan; E0/E1 never did).
- FIX PLAN (next): post-2dscale ring OVERDRAW — gate g_btn_pending path + boxParams face + state!=0 + g>16; draw the ring at device density (uniform K per scaling_laws band law, color 224, half-open/butt laws) over the zoomed content rect (known inside 2dscale). Runs AFTER the remap so it repairs both defects; tiny blast radius (no change to fe_pair_remap). The principled alternative — mate-presence keying for E0/E1 in fe_pair_remap — would need a full popup/file-menu re-verify (their faces genuinely carry E0/E1); hold unless the class resurfaces. Pressed state: face is legit E0/E1 stripes (remap correct); check whether pressed ALSO has a ring needing the overdraw when building.

## 2026-09-01b portrait key-exclusion fix (build 6744ff0c) — the REAL root cause
- The palette-source fix below did not cure the junk (4K shot: same speckle at g40). Root cause = the A5 reserved-black class the maintainer remembered: key idx 9 = RGB (9,0,0) ~ black, so dark shadow blends nearest-mapped to the TRANSPARENCY index; the keyed composite punched map-holes through the face ((17,56,84) ocean speckle). Fix: nearest search skips i==key. RULE: exclude reserved/special indices from any palette quantizer's candidate set.
- The dest+0xA4 palette source is kept (robust) but its stale-table diagnosis was an unconfirmed hypothesis.

## 2026-09-01 portrait palette-source fix (build 482793d0)
- First real in-game bilinear run showed junk colors over dithered/blended regions (Morgan 1600 shot): the resampler's palette was the fixed global 0x94c590 (live on MENU screens, stale in-game). Fix: read the DEST buffer's synced DIB color table at dest+0xA4 (Buffer_sync_to_palette fills it on every GraphicWin+0x444 draw setup) for BOTH the blend and the nearest search — self-consistent AND display-true in every screen context; channel order cancels. LESSON: an 8-bit palette assumption validated in one screen context is NOT portable — the identity-maps-to-itself property hides a wrong table until the first real blend; the buffer's own +0xA4 table is the only per-context display truth. test_resampler_parity.py now locks this.
- Verify: portrait at 1600 + 4K (4K bilinear never seen), faction-QUOTE portrait unchanged (same thunk), chevrons after a faction page.

## 2026-08-31 portrait poke-address fix (build e048aa5b)
- The 30b addendum's t_dl_portrait poked the WRONG address: PAVG_GATE_IMM was PCAVE2+0xCA05 = thunk_chev_coverage+5, not thunk_portrait_avg's `cmp eax,0x940824` imm at PCAVE2+0xA05 (thunk @0xA00, entry mov eax,[esp+4] = 4B). Consequences: bilinear never engaged -> portrait drew plain NN (user 1600 shot banding; full-row/col duplicate ratio 0.362/0.358 = 9/25 NN signature), and each faction-profile view at g>16 permanently overwrote chev_coverage's prologue in memory (latent tech-page crash). Parity used the constant symbolically = couldn't catch it. Fixed in assemble_dl.py + re-splice; only t_dl_portrait bytes changed (both imms -> 0xA0CA05). LESSON: a runtime POKE address into another thunk is outside every guard — derive poke targets from the yaml cave offsets (thunk offset + instr offset), never from a separate constant.
- Verify: portrait bilinear-smooth at 1600+4K; tech-page chevrons clean AFTER a faction profile view.

## 2026-08-30b addendum (same day, user request): leader portrait + wheel scroll
- **FACTION PROFILES leader portrait** (the one un-scaled element; the proto deliberately kept it 1:1):
  `t_dl_portrait` = E8 redirect @0x430DA3 (draw_faction's `Sprite_draw_2(dest,key,x,y,1,1)`): g>16 →
  re-push the 6 args with num=g/den=16 and, around exactly that call, POKE the A5 bilinear resampler's
  dest-gate imm (`thunk_portrait_avg` @Sprite_draw_2 entry; the imm32 of `cmp eax,0x940824` lives at
  **pcave2+0xCA05** = 0xA0CA05) to the DL canvas 0x7042E4, restore 0x940824 after → the enlarge is
  palette-aware BILINEAR (its guards fall back to NN on any oddity). No exec bracket, no nesting hazard.
  `t_dl_portw` = 6B detour @0x430DA8: the profile-text x advance (`x + spriteW + s(5)`) substitutes the
  DRAWN width **fl(w·g/16) — the resampler's idiv law, NOT scale_px** (half-up would over-advance 1px).
- **Wheel = scroll, never select** (extends the DW wheel_scroll vanilla change): the two WinProc
  wheel_scroll sites' new_bytes retargeted (splice W_SWAPS) to `t_dl_wheel_down/up` cascade heads that
  CHAIN to the dw thunks for every non-DL context (BASEPOP≠0 or MODAL_TOP≠0x703EA0). DL path: synthetic
  VK_UP/DOWN (lParam==0) → chevron-press the first ENGAGED bar — category list's heap V-bar
  **[LISTWIN+0x43C] = [0x71394C]** first, else the VISIBLE page TextScroll (+0x10514 full / +0x15C54
  lower / +0x187F4 800-only / console +0x130B4; visibility = **Win+0x9C bit0**, from Win_hide 0x5EDCD0's
  guard — an engaged bar on a HIDDEN TS must be skipped) — then `call [win vtbl+0xFC]` present
  (LISTWIN vtbl 0x67041C+0xFC = GraphicWin_present_default 0x404290). Swallowed (eax=0) even when
  nothing is engaged; the KEYUP twin always swallowed; real arrow keys (scan code in lParam) pass.
- 71 sites, 33 thunks, code ends pcave2+0x2324B; parity 53 tests (portrait gate/args/restore, portw
  vs the idiv law, wheel list/TS-fallback/hidden-TS/chain/non-wheel-key/keyup scenarios).

# Prior build db6a35371d13e5b1637d151d4f2abccc (the dl_scale bake proper)

**State: baked + committed; L1 suite green; proto (hook_dl_scale_proto.js v12l) was user-verified and
adversarially pixel-audited at 4K + 1600 (strokes K=2 all edges vs native 1px refs, stripes P-law
canonical both res, chevron tip==stem, console ledge clean). REMAINING: one post-bake in-game verify
at 4K + 1600 (the bake is a port of the proto; parity-tested, not yet human-verified in-game).**
Shortcuts → hook_dl_observe.js (⚠ hook_dl_scale_proto.js now DOUBLE-APPLIES — never run it on db6a3537+).

## Bake architecture (src work\scripts\assemble_dl.py; splice_dl.py; parity tests\test_dl_asm_parity.py — 37 tests)
- **351 immediates in TWO runtime tables** (extracted from the proto by dl_extract_imms.py → dl_imms_gen.py;
  kinds HD/MUL2/MUL3/BIAS1/NUMG/DEN16/FLOAT/VEH/PTR, all identity at g=16): MAIN (189) applied once at
  DatalinkWin_build entry; TECH (162 + 8 PTR font repoints) applied at DatalinkWin_open entry and
  **REVERTED (walker g=16) at its return** — 0x496BB0..0x49BD00 is ReportWin-SHARED code (F8 screens stay
  native). Every tech-range thunk additionally gates on the g_dl_exec cell.
- **45 frame sites** → DW band-map stubs (R−1/B−1): t_dl_bm/bmdf (builder/list/draw_page), t_dl_bmt
  (tech HF, exec-gated), **t_dl_bmxt** (the 10 clip-gated bracket draws: snapshot bbox → restore outside
  the dest clip after the thick draw + g_fc_exact exact-fill via g_faction_scratch_rect so the bracket's
  bottom stroke lands at B−2..B−1 = the chevron-tip law; 64K VirtualAlloc'd snapshot plane).
- **t_dl_restripe** (own routine, NOT fe_pair_remap — fe's backdrop family is C6-top, DL parity is 65-top):
  pair by member prescan (C4→196/65, AE|EE→174/238, C6→65/198), canonical member on stripe-top rows,
  P=(g+4)>>3 phase=absolute y, dominance bail pairSum*4<area. Called at: build leave (whole canvas),
  t_dl_cu detour @0x42C094 (content_union, after render_topic's 3 frames, before the painter switch —
  replaces the proto's 14 painter-entry restripes), and the two Buffer_tile wrappers (0x42A140/0x42A1F7).
- Tech page: t_dl_techwrap at the 2 DL call sites of 0x498B30 (RW+0x5980/+0xE268 scale bracket + iface
  mode-8 force); t_dl_arrowzoom at the 5 Sprite_blit_scaled_core sites (SCALE_NUM/DEN=g:16 bracket);
  t_dl_mono @0x49A2CF (band-histogram argmax → remap idx 0x0F); t_dl_hover @0x49B2F1 (s(3) stub);
  rf5/rf6 imm8-overflow regfixes (52/58) — all g_dl_exec-gated. rf1–rf4 = terraform 75/100/103×2 (DL-private).
- t_dl_btnrect @0x607F60: native-sized face rect when g_btn_pending (BACK/EXIT hover clip fix).
- t_dl_wininit @0x5EBD80: ecx==0x713510 (DL ListBox) → g_popup_active++ bracket via ret-swap.
- **Console save-under**: t_cr_snap_dl on DL iface vtbl 0x66AF30 slot 0 (clone of diplo t_cr_snap, shares
  g_cr_* cells); existing t_cr_tile restores after tile_panels — kills the ledge residue (diplo
  exit-residue class: MainWin_tile_panels restores positionally from the NATIVE art).
- **thunk_sb_restripe head swapped in place** (10B, eax dead): `mov [netwin],0` → `mov eax,[g_dl_exec];
  mov [netwin],eax` = the post-sbzoom netwin re-assert (chevron zoom survives) — identity for non-DL users.
- netwin=1 held across build + exec (arrow/wing button zoom via btn_gate's netwin flag).
- pcave2 grown 0x22000→0x2A000: code 0x22000..0x23050 (29 thunks), cells 0x27E00, tables 0x28100/0x28CE0.

## Engine facts worth keeping
- DatalinkWin_open 0x429180 thiscall RET 8, 26 callers → entry detour + ret-swap (DW pattern).
- render_topic 0x42BF10: d690@0x42C020 (native, mixed-space+clip) → d528@0x42C03E → d618@0x42C051 →
  painter switch @0x42C094 (`mov eax,[ebp-4]; cmp eax,0xF; ja`), per-case direct E8 calls (no jump table).
- ReportWin_tech_connector 0x49B450: pair boxes drawn under per-row clips; the box bottom edge IS the
  chevron stem; the arrow tip = B_incl−1..B_incl. Slots RW+0x595C..0x5970 = up to 6 leads-to rows in
  pairs (57,58)/(59,5C)/(5A,5B); partial redraws loop ONE call site per pair.
- The thick hollow_flat render treats its (R−1/B−1) rect half-open AND floor-quantizes short → bottom
  edges land ~3px high at g=25 without exact-fill (the "chevron slid low" defect class).
- The window at 1600 sits at (175,47) — canvas→screen offset is +175/+47 (NOT +2; a mis-mapped offset
  produced a phantom "spine overshoot" diagnosis on 2026-08-30).
- Vanilla stripe parity: 65-top over 198 for the backdrop (audited pristine + user-verified) — OPPOSITE
  of fe_pair_remap's C6-top popup language. Never route DL restripes through fe_pair_remap.
- Proto history (v1–v12l) incl. the crash-hunt (saved-reg trampoline clobber, watchpoint hazard) lives in
  hook_dl_scale_proto.js's header and git; the v12k DIAG scope lesson is in feedback_edit_script_slice_guard.

## Post-bake verify checklist (user, 4K + 1600)
Open Datalinks (F1 or diplo DATALINKS): list scroll/select/hover + chevrons (hover them), a tech page
(both columns, hover leads-to: tip==stem, no shrink), ALL CATEGORIES/concept/faction pages, BACK/EXIT
hover, wing buttons, close → console ledge clean; plus a ReportWin F8 tech screen (must be NATIVE —
the tech-range revert) and one non-DL popup sanity. ADDENDUM items: a faction page's leader portrait
(scaled ×g/16, bilinear-smooth not blocky, profile text starts just right of it, no overlap); wheel on
a LONG category list (ALL CATEGORIES) scrolls the list without moving the selection; wheel on a long
article (a concept page) scrolls the text; wheel still works in the DW part pickers / popup lists /
Load-Save (the non-DL chain regression). 4K passed 2026-08-30 pre-addendum ("no serious problems");
1600 still pending. Then mark CLOSED here + the maintainer's work log.
