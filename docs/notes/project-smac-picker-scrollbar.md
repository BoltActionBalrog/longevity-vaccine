---
name: project-smac-picker-scrollbar
description: ProdPicker scrollbar/console-rail arc CLOSED e0db2ea8 USER-VERIFIED 2026-08-09; EXTENDED to the POPUP FAMILY 2026-08-14b..15b (rail_scrollbar_scale v2, build ecc665e0 USER-VERIFIED all-res 2026-08-15, committed): thunk_rail_gate [picker OR [vtbl+4]==Popup_show], g_rail_sb stash, rail_slide_out.hstep, sbzoom v6/btn_stripes v6
type: project
---

# ProdPicker scrollbar arc — state 2026-08-06 (opened after the picker arc closed)

User made a >20-buildable-items save; 4K shot 20260805: native ~24px track at the
window's right edge, arrows+thumb native-tiny at the top, drawn over the window's key-9
column (map shows through — that 703..738 native strip is VANILLA-transparent, magnified).

## Static RE (static report, verified against pristine 2d0b1438-base .bak)
- Class = Thinker `Scroll : GraphicWin` (engine_win.h:1295, size 0x214C), vtable 0x669D58,
  draw slot @0x669D88 → thunk_pref_sbzoom stub → ScrollBar_draw 0x6066F0 for ALL instances.
- SCALE-BLIND: all geometry = caller literals + native defaults. KEY: +0xA60 element square
  = min(w,h) drives arrow buttons AND thumb; thumb travel = len−3·btn−1 (−2 bordered), drag
  inverse mapping uses btn/2 center — ALL derive from the window rect + btn → self-adapt
  once init args scale. Range +0xA20/24 value +0xA2C are ITEM units (picker: column units,
  max = count/rows − viscols + 2 @0x4949F6) — never scale.
- Picker: sb at picker+0x7120 = 0x6AF164; embedded FlatButtons +0xAAC=0x6AFC10,
  +0x15F8=0x6B075C (0xB4C each; sprite-triple faces from g_scrollbar_sprite_block 0x791D88,
  repeat 0x32). init @0x4949DE: (x=winW−0x14 [MIXED-SPACE patched], y=0x15, w=0x18, h=0x13A,
  parent, id=0, flags=1); engage test @0x4949B1 (visCells<count); created hidden (vtbl+8).
- Draw: arrows (FlatButton redraw) → GraphicWin_clear(track color 7) → thumb_rect 0x606C50
  (writes +0xA4C cache) → fill_2 thumb → grip Sprite_draw_2 @0x6067ED num=1/den=1 → 2px
  bevel Buffer_box_2. Track-bg sprite +0xA78 presumed NULL for picker.
- Other init_inner callers: 0x4062F9 popup listbox (winW−0x2B, 0x15, 0x18, rows), 0x407EA4
  (0x147,0x15,0x18,0xD8), 0x4342B3 18-row list, + class wrappers. Mousewheel = ±1 step on
  every scrollbar via Win_on_mousewheel 0x5F8530-0x5F85E0 → step_inc/dec 0x606320/0x606440.

## Existing lever (census pass) — NOT greenfield
netwin trio gated on g_netwin_active (0xA10800): thunk_sb_width @0x6058AE (width read),
thunk_sb_xinset @0x62944D (TextScroll x-inset), thunk_sb_thumb @0x6067ED (grip blit num=g
den=16 + recenter). thunk_pref_sbzoom (pcave2+0xADB0, vtable bracket, free tail) arms the
flag per-instance — allowlist has PrefWin sliders + SUPPORT bar 0x6EABC8. SUPPORT arrows are
allowlisted in btn_gate directly. Established pattern: never scale g_scrollbar_w globally.

## Fix design (pending trace confirmation)
(a) call_target_redirect @0x4949DE gated ecx==0x6AF164: x'=winW−bp(0x14), y'=bp(0x15),
    w'=bp(0x18), h'=bp(0x13A) — everything downstream (btn square, thumb, travel, drag)
    self-adapts. g≤16 identity via bp.
(b) add 0x6AF164 to thunk_pref_sbzoom's allowlist → arms sb_thumb grip scaling per draw.
(c) arrows: pass-2 thunk_basewin_btnzoom range arm ends EXACTLY at 0x6AF164 (deliberate
    then); extend upper bound to 0x6B12B0 (=sb+0x214C) to cover the two embedded buttons.
(d) laws in scaling_laws.py first (sb rect law + identity), sweep, Unicorn, ledger-allocated
    cave space if any new thunk is needed ([[feedback-cave-ledger-lengths]] — 4th escape).

## Trace RUN 2026-08-06 (4K g=40 + 1024 g=16, frida_pp_scrollbar.log) — geometry pinned

- init @0x4949E3 ret: 4K (x=1875=winW−20 MIXED, y=21, w=24, h=314); 1024 (738,21,24,314)
  identity ✓. set_range(0,8) item units ✓. btn=+0xA60=24 both res. Interactions verified:
  arrows ±1, track page, thumb drag — all item-unit, engine math self-adapts within the rect.
- ⚠ A SECOND GEOMETRY SITE fires after init (the "resize"): 4K h 314→1163 + x 1875→1852;
  1024 h 314→415 + x 738→715. Found it: the picker SLIDE-IN/OUT helper pair 0x45DEA0 (show,
  called @0x492720) / 0x45E540 (hide, @0x492788), cdecl (picker, &sb), gated visCells<count.
  At 0x45E4C6..0x45E4F4: [sb_vtbl+0xC](w=0x18, h=esi−0xA, 0) + Win_move(winW−0x2B, 0x15) —
  the sb is parked INSIDE the right rail-art column; esi derives from the 0x7CFFxx SPRITE
  TABLE (rail art dims, tiled via Buffer_tile_2) → h is rounded to rail-tile repeats. h ratio
  4K/native = 1163/415 = 2.80 ≠ 2.5 → MIXED spaces in the formula (decode pass running).
  The rail art itself lands short of the device window edge (the transparent strip under the
  bar in the 4K shot) — rail column + sb are ONE assembly; the arc covers both.
- RESOLVED mislabel: picker+0x7B60/+0x7B50 ("page size"/"firstVis" in old notes) are the
  EMBEDDED SB's +0xA40 paging / +0xA30 repeat-delay — exec writes viscols−1 / 0 directly.
## FULL MECHANISM (decode pass 2026-08-06; symbols in terranx.h, Ghidra applied)

rail_slide_in 0x45DEA0 / rail_slide_out 0x45E540 — GENERIC cdecl(win, sb) console-rail pair
(9 show + 11 hide callers: Popup_show/hide 0x404A08/0x404AE2, popup_sb_create/remove
0x406260/0x406330 [popup sb at +0x3230, SAME geometry law], report screens, picker
show/hide 0x492720/0x492788). Siblings of slide_show/slide_hide 0x45D440/0x45D970.
- Rail art: 4 sprites at MainWin+0x216F4.. (VAs 0x7CFF14/40/6C/98) from console_x_A/x2_A.pcx:
  top cap 32×26, mid tile 32×34, bottom cap 32×25, filler 32×34; wall strip r_outer 15×529
  @0x7D0048. Strip = 47px (32 rail + 15 wall) synthesized into bufA(47 × H′_device) — MIXED:
  native width/tiles, device height.
- HEIGHT LAW: yTop = min(y1+13, max(A,y1)), A=238 (94 @800w); H′ = y2−yTop;
  N = floor((H′−44−26−25)/34); railH esi = 51+34·N; sb_h = esi−10. Verified exact:
  4K esi=1173 (y1≥238 → the +13 vanishes), native esi=425. MIXED SPACES: H′ device,
  all constants native.
- Tail (0x45E48B..0x45E4F1): bake bufA→canvas at (clientW−47, yTop−y1); sb vtbl+0xC
  resize(0x18, esi−10, 0); Win_move(clientW−0x2B, 0x15); show. KEY: the picker's exec-init
  sb rect is NEVER VISIBLE (init→redraw→hide; the rail helper re-geometries + shows) — the
  HELPER is the only geometry that matters; w=0x18 in its resize drives +0xA60 btn square.
- Anim phases (pref-gated, !MP): vertical wall rise + 32px horizontal unroll, 10ms/frame
  (g_anim_frame_ms 20>>1); steps persisted g_rail_vstep/g_rail_hstep. f2 captures the strip
  from the canvas (no re-synthesis), retracts, fills key-9, bakes the closed wall.

## FIX DESIGN v1 (picker-gated, extensible; NOT yet baked)
1. Synthesize bufA NATIVE: H_nat = ceil(H′·16/g) (floor-descale law), vanilla quantization
   on H_nat (native identity by construction) → keyed-enlarge the strip to (bp(47) × H′) at
   the BAKE (thunk_keyed_stretch_blit reusable; exact-fill semantics) at x = clientW−bp(47).
2. Helper tail: resize(bp(0x18), fl((esi_nat−10)·g/16)); move(clientW−bp(0x2B), bp(0x15)) —
   ONE cascade shared with the strip enlarge (chrome-follows-content).
3. Widget internals: w=bp(24) → btn square scales → arrows/thumb geometry follows. Grip
   sprite: add 0x6AF164 to thunk_pref_sbzoom allowlist (arms thunk_sb_thumb). Arrow faces:
   extend thunk_basewin_btnzoom range end 0x6AF164 → 0x6B12B0 (covers the two embedded
   FlatButtons 0x6AFC10/0x6B075C).
4. GATE on win==0x6A8044 && g>16 (report screens are unscaled windows — a scaled rail would
   mismatch there; popups can be allowlisted later once their rails are assessed).
5. Animations: v1 leaves the anim frames drawing the native-synthesized strip (transient
   ≤~300ms artifact at g>16) — evaluate at verification; fallback = skip anim at g>16.
6. Laws in scaling_laws.py FIRST (rail quantization + sb rect + identity), sweep, Unicorn,
   cave slots FROM THE LEDGER ([[feedback-cave-ledger-lengths]] 4th escape).

Related: [[project-smac-prodpicker]], [[project-smac-prefwin-scaling]],
[[feedback-cave-ledger-lengths]], [[feedback-frida-attach-branch-target]].


## BAKED 2026-08-07 — group `rail_scrollbar_scale`, live 442f0bb6 (AWAITING USER VERIFY)

FIX DESIGN v1 shipped essentially as drafted, with two corrections found while reading bytes:

1. **The bake call is at 0x45E4C1, not 0x45E4BB** (0x45E4BB is the `lea ecx,[ebp-0x5dc]` that
   loads `this`). Cost nothing because the site bytes were dumped before writing the yaml —
   ALWAYS dump the site bytes, never trust an address carried in prose.
2. **The 238 threshold cannot be evaluated in native space** — y1 is a SCREEN coordinate and
   only DIMENSIONS descale by 16/g (4K y1=467 → ceil(467·16/40)=187 ≠ the true native 139).
   So the gated path pins the native inset to the vanilla 13 and scales it: `yTop = y1+bp(13)`.
   That also makes vanilla's own 4K behaviour (inset 0, bar hanging 8px below the bottom cap)
   go away, and it is what makes the 5px/4px seating margins hold at every g.

### The five sites (all `[ebp+8]==0x6A8044 && g>16`; src scripts\assemble_rail_scrollbar.py)
| site | VA | len | does |
|---|---|---|---|
| ytop  | 0x45E0B7 | 8  | `yTop=y1+bp(13)`; `eax=ecx` ⇒ vstep 0 ⇒ vertical anim off |
| hstep | 0x45E351 | 6  | unroll frame count → 0 (horizontal anim off) |
| bufh  | 0x45E22C | 5  | Buffer_init h → `ceil(H′·16/g)` (quantize on NATIVE art) |
| bake  | 0x45E4C1 | 5  | Buffer_draw_2 num/den → g/16, x → `clientW−bp(47)` |
| sbfit | 0x45E4C6 | 37 | sb = `(clientW−bp(0x2B), bp(0x15), bp(0x18), fl((railH−10)·g/16))` |
Cave 0x10400-0x10547 (LEDGER-allocated, ledger updated). thunk_pref_sbzoom → v4 87B, +0x6AF164.

### Why the animations had to go (not cosmetic)
Both slide loops blit to the SCREEN buffer 0x9B7490 directly; the bake goes to the WINDOW
canvas. The last animation frame therefore WINS over the bake on screen. With a native-sized
strip buffer that would have shown the unscaled rail at exactly the resolutions where the
animation runs. Vanilla itself takes both no-animation paths whenever the step count
degenerates — which is already the case at 4K (window top ≥238 ⇒ vstep 0) and 1600×1200
(vstep 1) — so this is a vanilla-supported path, incl. the screen-clip restore at 0x45E472.
The composite still reaches the screen: the picker's caller flushes the window at 0x492728.

### Predicted geometry (law `rail_layout`, verify against these)
rail_h = **425 at every g** (the native quantization is the whole point).
4K (win 1895×1225, g=40): strip src 47×478 → enlarged; sb (1788, 52, 60, 1037); art rows
39..1102. Native (758×490): sb (715, 21, 24, 415) — matches the trace bit-exactly.
g=25: sb (1117,32,37,648). g=22: sb (983,28,33,570).

### Open watches for verification
- 1px key-9 seam at the strip bottom/right (fractional expand drops the last dest row/col,
  [[feedback-sprite-expand-drops-last-row]]) — overdraw if seen.
- Arrow faces on HOVER redraws happen OUTSIDE the pref_sbzoom bracket → may draw native. Fix
  = add 0x6AFC10/0x6B075C to thunk_btn_gate's esi statics (SUPPORT-bar precedent), NOT a
  thunk_basewin_btnzoom range extension (that would also arm the g_popup_active bracket).
- No slide flourish at g>16 for the picker (deliberate).
- popup_sb_create 0x406260 uses the SAME height law at Popup+0x3230 — the popup family's own
  scrollbars are the natural next consumer of these five thunks (just widen the gate).


## 2026-08-08 — rail VERIFIED by measurement; two ARROW defects found and baked (f6d06cbe)

User checked 442f0bb6 at 4K: rail + bar geometry correct, but three complaints, ALL about the
chevrons. Do NOT re-open the rail — it was measured, not guessed:
  strip = 117px = bp(47) (80 channel + 37 wall); bar bevel box window (1788,52) 60x1037 =
  rail_layout to the pixel; NN run-lengths through the wall are 2/3px = the 2.5x signature.
**Buffer_draw_2 0x5D84C0 really is a keyed uniform-scale blit.** Guards: `num==den` 1:1 fast
path @0x5E4C4C; the ONLY rejection is ratio > 4.0 (`fcomp qword [0x66FDC8]`, `test ah,0x41`
@0x5E4C89) — g/16 maxes at 2.5. No min source size; a plain Buffer is fine (0x5D855D is the
Buffer->Sprite adapter into Sprite_draw_2). Every vanilla DIRECT call passes 1/1, but
Sprite_blit_scaled_core RE-ENTERS it non-1:1 at 0x5E4C01 for every zoomed COMPRESSED sprite,
so the scaled path is one of the hottest in the renderer. LATENT LIMIT: the Bresenham run
table 0x9B3AD8 is 800 dwords -> a scaled source axis must stay <= 800px (native strip ~480 at
4K, fine, but it caps how far descale-then-rescale can go).

### Defect 1+2 (ghost chevron + dead up-arrow hitbox) = ONE vanilla bug
`ScrollBar_on_resize` 0x606860 (vtbl+0x34) re-derives b=min(w,h), rebuilds the thumb zone, then
resizes/moves **only the DOWN arrow +0x15F8** — at BOTH arms (0x6068DB plain, 0x606935
bordered). `+0xAAC` appears NOWHERE in the function. Latent forever: b only moves when a bar's
SHORT axis changes and vanilla only grows bars along their LONG axis. Widening the picker's bar
0x18 -> bp(0x18) is the first thing in the game that does it. The up arrow's window stayed
24x24 at the client origin, so FlatButton_content_draw centred the ZOOMED chevron against the
stale W (`x=(W-sprW)/2` @0x607F2C) and clipped it to the stale buffer -> a smaller offset GHOST
over the real chevron, and a 24x24 hit rect in the corner = "no hitbox". Ghost measured at
EXACTLY 24x24 at the client origin (shot 20260808) — the init width 0x18.
FIX `thunk_sb_arrowfit` 68B @pcave2 0x10560, both arms. ONE thunk serves both (it re-derives
the -2 border inset from [esi+0xA1C], the only difference). **SELF-GATED on [up+0x4C4] !=
target** -> emits no call at all for every other scrollbar and for the picker at g<=16
(bp(0x18)==0x18): native identity WITHOUT a g gate. No Win_move (up origin is (0,0)/(1,1) at
every size). Leaves ebp = &down for the caller.
REFUTED on the way: ScrollBar_draw draws no arrow itself (its only Sprite_draw_2 @0x6067ED is
the thumb GRIP); there is no disabled/pressed overlay (the "triple" is a 12-entry Sprite* table
0x9B8DE8 fanned into FOUR triples, one per direction, and content_draw picks exactly ONE);
the arrow draw has ZERO dependence on scroll value/range. The 0x32 read as a "sprite stride"
is `btn+0xA44 = 50`, the auto-repeat delay.

### Defect 3 (permanent hover shrink)
`FlatButton_on_mouse_move` 0x608500 (vtbl+0x44) sets hover [btn+0xA74] and repaints via
GraphicWin_redraw -> vtbl+0x30 = [0x669784] — **the SAME slot ScrollBar_draw uses** (0x6066F8 /
0x606710). Only the arming differs. The arrows were in NO allowlist: they sit just past the
picker's 9-button range, whose upper bound 0x6AF164 IS the Scroll (0x6A8BB8 + 9*0xB4C exactly).
Unarmed -> thunk_btn_shrink's gate says NO -> shrink AND KSB refill both skipped -> the engine
blits the state sprite at NATIVE size centred in the device-sized window. Persistent because
nothing repaints it until a full ScrollBar_draw; hover-LEAVE is unbracketed too.
**MY HYPOTHESIS "shrink applied, refill skipped" WAS WRONG** — both key off one `g_btn_pending`
set by one gate call, and every branch between the two detours converges (no early exit). A
one-way shrink is impossible; and a real +0x4C4 mutation would compound every redraw.
FIX `thunk_btn_gate` 172->188B: + esi statics 0x6AFC10 / 0x6B075C. This is the SAME fix the
FORCES SUPPORTED bar's arrow pair (0x6EB674/0x6EC1C0, identical Scroll offsets) already carries,
deliberately bracket-independent so hover repaints zoom too. Strictly additive: inside
ScrollBar_draw the gate already returned 1 one test later.
REJECTED: widening thunk_basewin_btnzoom's range to 0x6B12B0 — arms g_popup_active (a refcount
with 4 other consumers), would perturb the maintainer-verified ScrollBar_draw path, and corrupts a
documented "button array" range.

### Gotchas banked
- **keystone HANGS on inline `;` comments in the asm string** (cost a 120s timeout). Keep
  commentary in the Python docstring; the shipped thunks in this file have none.
- A defect present in the PRE-fix screenshot is not ours — diff the old capture before
  diagnosing. Both up-triangles existed at 442f0bb6's predecessor, just both native-sized.

Related: [[project-smac-prodpicker]], [[feedback-draw-state-multiplicity]],
[[feedback-cave-ledger-lengths]], [[feedback-sprite-expand-drops-last-row]].


## ARC CLOSED — e0db2ea8 USER-VERIFIED 2026-08-09 ("All resolutions look correct to me")
Everything below (rail geometry, arrow fit + hover gate, SB banding restripe) is confirmed
in-game at all resolutions and COMMITTED. Remaining picker items are only the deferred
watches in the maintainer's work log (map-parent gwinit variant, g=22 ledge 1px, popup-rail widening).

## 2026-08-08b — SB COLOR BANDING baked (live e0db2ea8); R-cutoff transient

User on f6d06cbe: 1600×1200 shows the recurring banding. RLE-sampled the shot (205336): arrow
faces + thumb = pair **0xF0/0xB9** (palette 240=(53,61,115)/185=(17,50,79), exact match in
frida_palette.log), trough = 0x41/0xC5 — all in irregular 1-2px NN runs. 4K HIDES this class:
2.5× NN yields regular 2/3-row runs ≈ the P=5 stripe law — never accept 4K as evidence for
dither; judge at g=22/25. Root cause: the armed ScrollBar_draw zoom + the arrows' 2dscale zoom
had NO dither-regeneration tail, and F0/B9 was in no remap family. Same day: the project rules gained
the dither invariant + scaling-sprites gained the THIRD-trap section (user-directed).

**KEY ENGINE FACT: 0xF0 is ALSO solid console art** — frida_pp_rail.log's bake row dump has a
21px 0xF0 run in the rail strip. So F0/B9 must NEVER be content-keyed (a prescan would eat
art); it is the first ONE-SHOT remap family (g_rm_f0ovr, self-clearing, set only under g>16 —
same contract as g_rm_povr). Laws: DITHER_ONESHOT_PAIRS / stripe_color_sb / pair_remap_pixel
(the last = the full v7 per-pixel model, now the checked-in Unicorn differential reference).

Fix (all Unicorn-verified in test_rail_asm_parity.py, 11 new tests; post-bake byte verifier
scratch verify_sb_banding_bake.py ALL PASSED; clean apply == live == e0db2ea8):
- **fe_pair_remap v7** 932B @0x10000 (ends 0x103A4 < rail_ytop 0x10400): + F0/B9 family,
  one-shot only, path-independent (works on force AND enlarge paths). Pre-v7 callers
  byte-behavior identical.
- **thunk_sb_restripe** 120B @0x105B0: pref_sbzoom v5's armed-path tail-jmp target — closes
  the netwin bracket, consumes the new g_sb_cur stash (ecx saved pre-call), one remap pass
  over the WHOLE sb canvas with force (content-keyed C5/41 trough) + the F0 one-shot (thumb).
  Runs for EVERY sbzoom-armed sb (PrefWin sliders, FORCES SUPPORTED, picker, DLL) — content
  keying/opt-in makes flat-art canvases byte no-ops, but formerly-banded faces will now
  stripe lawfully (the invariant working; glance at them during verify).
- **thunk_btn_stripes v4** 123B (97→123; NB the old "80B v2" ledger note was WRONG — measure):
  the two picker arrow statics (0x6AFC10/0x6B075C, below the BaseWin early-out range) arm the
  one-shot before the common devfill+remap call; arrows' own canvases restripe through the
  chain they already traverse. All other buttons byte-identical.
- **pref_sbzoom v5** 87B (same size): +6B `mov [g_sb_cur],ecx` AT the old arm target (all 7
  je displacements unchanged), tail mov+ret → jmp sb_restripe; draw-call rel32 shifts −6.
  GOTCHA: the patcher's {rel32:} placeholder is E8-only — an E9 tail-jmp needs a LITERAL rel32.
- Globals: g_sb_cur 0x10630, g_rm_f0ovr 0x10634, g_rm_f0 0x10638, g_rm_f0col 0x1063C.
- Rail strip art = multi-color stone TEXTURE (histogram-sampled), not pair dither →
  proportionate NN, deliberately untouched.

**R-CUTOFF closed as TRANSIENT** (the 4K "The Neural Amplifie"): 3-way proof — the char was
never drawn (ink ends 20px inside the cell, centering used the full 20-char width); no on-disk
path can produce it (all picker repaints funnel into patched draw_cell 0x4927C0 via vtbl+0x30
0x493C70/scroll 0x493CB0; measure+draw share one font+rect; FUN_004956D0 = the Datalinks/
Holobook window [now in terranx.h + the maintainer's work log as a future all-native scaling arc], NOT a
picker path; BaseWin_draw_production = the strip panel, fully patched). After restart the
user's hook_pp_title.js runs at 4K/1600/1024 showed len=20 single TextOut, color 0x10ff0048,
clean canvas state block — gone. Verdict: stale per-canvas text state (buf +0x51C/520/524/528
hotkey/fmt fields, H1) poisoned in that one session. hook_pp_title.js stays in scripts\; do
NOT redesign the wrap if it recurs — trace first.

ENV NOTE (the development machine, 2026-08-08): long pytest runs AV-kill the interpreter
(0xC0000005) and one apply_patches.py wedged forever inside a 1.2s yaml parse — processes
degenerate, files were always healthy. Split test runs per-file and retry; never diagnose
the yaml from a wedged process.


## 2026-08-14b — POPUP FAMILY (rail_scrollbar_scale v2), build f57fbe00 -> ecc665e0 USER-VERIFIED ALL-RES 2026-08-15 ("passes in all resolutions"), committed

Trigger: the scenario editor's SELECT SECRET PROJECT MOVIE list popup (type-16 family) showed a
native-thin rail + bar at 4K (shot 20260814) — the "natural next consumer" predicted above.
refs\pristine\SecProjSelect.png = the PRISTINE exe at 4K (PRACX x2.8125 stretch; 2/3-px runs there
are expected, NOT a dither defect) = the target look. Static (static analysis) + trace (hook_popup_sb.js,
frida_popup_sb.log 4K+1024) proof:
- popup_sb_create 0x406260 (Popup vtbl slot +0x20, from ListBox cb 0x613220) inits Popup+0x3230 via
  init_inner @0x4062F9 (clientW-0x2B, 0x15, 0x18, h) hidden; rail_slide_in(popup,&sb) fires from
  Popup_show @0x404A08/0x404A63 (count>visible) or popup_sb_create @0x406312 (if visible). [ebp+8]
  = the HEAP Popup (Popup_alloc 0x404FB0, ptr reused) -> the picker-only gate left vanilla bytes.
  Popup rect law == picker law exactly: 4K sb (1856,21,24,789) [y1=771 -> 13-inset dropped, strip
  857 device-tall of native tiles], 1024 (717,21,24,245) [pristine ref: 245 native ✓]. Popup client
  W == box w [+0x30BC]; R margin 67 native (167 @4K) holds the strip.
- FIX (src assemble_rail_scrollbar.py v2 + assemble_popup_sb.py; 121 Unicorn parity tests):
  thunk_rail_gate 22B @0x11200 = CALL helper, ZF=1 iff [ebp+8]==0x6A8044 OR [[ebp+8]]+4==Popup_show
  0x404920 (exactly the 4 Popup-family vtables 0x6695C8/0x66A8A8/0x66CB60/0x66DD84; report screens
  stay vanilla); the 5 rail thunks now `call gate / jne vanilla` (2B shorter, same slots).
  sbfit v2 stashes the fitted &sb in g_rail_sb @0x11260 -> pref_sbzoom v6 (95B, +cmp ecx,[g_rail_sb])
  arms grip zoom + sb_restripe; btn_stripes v6 (171B) arms the F0/B9 one-shot for esi==sb+0xAAC/+0x15F8
  (v5 byte-path re-derived exact for everything else). NEW site rail_slide_out.hstep @0x45E7C3 (6B,
  same shape as slide_in.hstep) -> thunk_railout_hstep 49B @0x11220: zero the hide roll-up for the
  family (it captures a NATIVE 64px column and slides it over the bp(47) strip = tear) AND clear
  g_rail_sb. GOTCHA: rail_slide_out CLOBBERS [ebp+8] at 0x45E796 (canvas ptr) -> that thunk keys on
  edi (=win, loaded 0x45E5F9); eax is LIVE across the site (push/pop). btn_gate needs nothing:
  g_popup_active>0 during the popup's arrow draws (trace popact=1).
- MOUSE WHEEL does nothing on that bar: NOT ours — vanilla has no wheel; PRACX WndProc maps the wheel
  to map ZOOM whenever the map shows (its own TODO Fix #5) and only posts VK_UP/DOWN otherwise.
- LESSON: "pristine reference" shots in refs\pristine are pristine-exe 4K captures (x2.8125); the
  defective build shot is in work\screenshots by timestamp — check which exe a shot came from (row
  pitch 19x2.8125=53 vs 19x2.5=47) before diagnosing "who enlarged this".

### 2026-08-15 — hover chevron banding (build 50903d0e, btn_stripes v7)
User's 1600x1200 shot (20260815) after f57fbe00: geometry right, thumb + DOWN arrow lawfully
striped (F0/B9, 2/1 at P=3), UP arrow NN-banded — pixel census: the up arrow was in HOVER state and
its chevron dithers **0xA2/0xEF** (palette 162/239), a pair NO fe_pair_remap family owns; the picker's
hovered chevron had the same latent hole (never captured hovered). FIX: btn_stripes v7 (214B) — every
sb arrow (statics + [g_rail_sb] dynamic) also calls thunk_ed_remap (the generic run-chain pair
restriper from the editor arc: f0/b9, a2/ef, e0/e2, c9/6d, 6d/68) before the fe call; fe∘ed is a fixed
point so the normal face is unchanged. Unicorn: chevron-shaped a2/ef + f0/b9 faces enable and restripe
at g=22/25/40 (test_scenedit_asm_parity) + v7 call-order matrix. LESSON: census the pair per STATE
(hover/pressed sprites use different pairs) — [[feedback-draw-state-multiplicity]] again.

### 2026-08-15b — "banding on the background" at 1920x1080 (build ecc665e0) — CLOSED user-verified all-res
Shot 20260815 (g=22): rows/thumb/chevrons lawful; TWO backgrounds NN-banded: (1) the rail
column CHANNEL — the whole console_x rail art (console_x.pcx rows 279..400 = top cap/mid/bottom
cap/filler) is a 1px ROW dither 0x41/0xC5 on every row with AE guide lines + cap bevels overlaid;
the g/16 keyed enlarge bands it at fractional g (2/3-runs at 4K hid it — memory's "stone texture,
deliberately untouched" was WRONG for the channel). FIX thunk_rail_bake v2 (371B, RELOCATED
0x104A0->0x11280): pass 1 marks every 41/C5 of the NATIVE strip as 0xFD (palette 253 magenta = the
pcx key colour, never art) so no geometry model of the blit is needed; blit as v1 (ret popped into
g_rail_ret, callee-clean call keeps args); pass 2 over the dest rect rewrites the mark C5-top/41-bottom
on the dest-row phase grid (law rail_channel_pixel = fe's gutter duty). fe itself was UNSAFE here:
its unconditional AE/EE family would have dashed the vertical AE guide lines. (2) the arrow FlatButton
FACE BACKGROUND is its own C2/C5 row dither (194/197; not the 41/C5 trough) — thunk_sbarrow_bg 162B
@0x11400 (law sbarrow_bg_pixel), called by btn_stripes v8 for sb arrows (statics + dynamic) before
ed_remap+fe. Unicorn: rail parity (Python NN blit stand-in; backdrop untouched, no mark survives,
AE/F0/wall pass through) + scenedit parity (arrow face). LESSON: "judge dither at g=22" applies to
EVERY enlarged surface incl. art we filed as texture — RLE the columns, don't eyeball.
