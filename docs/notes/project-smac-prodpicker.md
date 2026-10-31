---
name: project-smac-prodpicker
description: Base production picker (ProdPicker) scaling arc — CLOSED 2026-08-06 user-verified all-res at e828237a (passes 1-5c); deferred: scrollbar >20 items, map-parent gwinit variant
type: project
---

# Base production picker (ProdPicker) — arc state 2026-08-02

**Status: investigation DONE, trace BUILT (`work\scripts\hook_prodpicker.js`, shortcuts repointed, append-log mode). NOT yet run. No fix designed yet.**

## Identity (all in terranx.h; Ghidra renamed)
- NOT `base_build` 0x4F81A0 (that's pure AI choose-logic). The dialog is **ProdPicker**, a window class embedded in BaseWin: static object **0x6A8044** (= BaseWin_g+0xA1C), ctor 0x492420, `ProdPicker_exec` 0x494700 (modal), driver `BaseWin_production` 0x417040 (sole exec caller @0x417771).
- Two open variants: base-screen (GraphicWin_init @0x494915, **parent=&BaseWin_g**) vs map/HUD (@0x494960, parent=MapWin child). Two button sets: HELP/WORKSHOP/OK/CANCEL vs queue-editor HELP/OK/REPLACE/INSERT/DELETE/CANCEL (btn ids in terranx.h).

## Defect (4K, g=40, patched a58804a4)
Window box + column widths scale (derived from BaseWin w/h → screen); **row pitch stays native 108** (`+0xA838` seed, ctor @0x492689 — THE lever: cell rects, facility icon = pitch·3/7, unit zoom = pitch·2/3 all key off it), fonts native (name 12 fixed @0x4939DB, stats max(10,colw/15) @0x493A4B, buttons 14 fixed @0x493A61), buttons native 100×20 at y=pitch·4+8 centered from *scaled* width → row floats over map at window right edge (~2850..3590,843..894 measured). Stray "1" tab above top-right unresolved (candidates: native scrollbar init @0x4949DE (w−0x14,0x15,0x18,0x13A); FUN_49D540; Caviar flag) — trace hook decides.

## Patch-surface census results (don't re-derive)
- ProdPicker/BaseWin_production bodies are **byte-pristine** — all misbehavior comes from shared callees.
- PRACX: no sites in the picker; startup-stomps bytes in its draw tree at 0x55953E (veh_draw) + 0x55AF62 (base_draw) — read LIVE bytes near those.
- Our groups on its path: BasePop_exec_3 @0x417BFD (RETOOLPENALTY confirm popup only) carries the whole popup lever stack incl. OK-GAP `thunk_btn_vcenter`; **`thunk_basewin_gwinit` child arm (parent==BaseWin_g → x,y,w,h ×g/16) fires for the picker's OWN init in the base-screen variant only** — prime suspect for variant-dependent breakage; buttons (parent=picker) escape it. `thunk_btn_gate` will zoom picker buttons via g_popup_active only inside the retool popup bracket — the picker itself is NOT a BasePop, so its buttons currently get NO zoom (consistent with tiny buttons). fe_pair_remap (ungated) will process its dithers.
- Cave space: pcave2 tail 596 B free + freed interior slots (~522 B @+0x37F6, ~330 B @+0x3EB2, ~300 B @+0xAFF4); growing the section +4 KB is the established fallback.

## Trace (hook_prodpicker.js → work\frida_prodpicker.log, append mode)
Captures per open: env (SW/SH/g/BaseWin rect), grid snapshot @0x4939CE (all +0xA810..+0xA838 fields), window-init pre-thunk args (0x494915/0x494960/0x4176E1 call sites — GraphicWin_init entry 0x5D4EF0 is Frida-untouchable, hence call-site attach), BaseButton_init (entry 0x607210, picker-gated, site-id via retaddr map) + ScrollBar_init_inner args, **post-init rects** of picker/scrollbar/9 button slots at first cell draw (pre vs post = detects our gwinit thunk firing), per-cell clip rects @0x49285F, Font_init sizes, veh_draw/facility icon args + zoom globals, "1"-tab census (FUN_49D540 marker, Caviar_draw site, entry-byte-checked text-outs).
**Drive list: both open variants + queue editor + scroll + select + flag anim, at 4K AND ≥1 non-4K** (shortcuts: 3840/1920/1600/1024 all repointed). 1024 run = g=16 no-op sanity (native constants already statically confirmed; pristine-exe baseline `terranx_pristine.exe` 72f6afc8 available if numbers disagree).

## v1 trace run 2026-08-03 @4K (TAINTED but corroborated) — three defects now SEPARATED

v1 violated attach hazards (see [[feedback-frida-attach-branch-target]] — BaseButton_init + cent_l_7 are baked `68 imm32 C3` detours; nine call sites had detoured callees) so the dialog drew and closed instantly without appearing. Numbers are therefore formally unproven pending the clean v2 run, BUT are corroborated by the maintainer's screenshot (logged button row y=440 + BaseWin.y=403 = 843 == measured 843; logged colw 362 == measured column pitch; logged cell h 105 == measured).

Measured @4K g=40: BaseWin canvas 1895×1225 device (= native 758×490 × 2.5 — 758 is the known BaseWin gate constant ✓). grid: cols=5 visRows=4 colw=362 pitch=108 winW=1895 count=5. Fonts: big/stats=24, button=14, cellName garbage (tainted read; static says 12).

**(A) Row pitch never scales.** pitch=pitchSeed=108 native while the window is device-sized → 4 rows × 108 = 432 of a 1225-tall window = the squashed rows + huge empty body. Vanilla check: 4×108=432, button row 440..460, native window h 490 → vanilla FILLS the window exactly. So `pitch = 108 × g/16` restores vanilla proportion by construction (270 @g=40 → 4 rows = 1080, buttons 1088..1138 < 1225 ✓).

**(B) ROOT CAUSE of the displaced button row = OUR OWN double-scale.** The picker's GraphicWin_init args are `(0,0,BaseWin.w,-BaseWin.h)` = (0,0,1895,1225) — **already device-space** (read from BaseWin's scaled canvas). `thunk_basewin_gwinit`'s child arm (parent==BaseWin_g → x,y,w,h ×g/16) then scales them AGAIN → picker canvas = **4737×3062** (= 1895×2.5, 1225×2.5), larger than the 3840×2160 screen. Button x centering reads `picker+0x4C4` = the inflated 4737: `(4737 − 103·6 − 32)/2 = 2043` and `+5·103 = 2558` — **exactly the logged btn rects**. Cells meanwhile use winW=1895. Two spaces in one dialog. The child arm assumes NATIVE child coords; this child is pre-scaled → exempt it (or make the picker pass native). Buttons themselves escape the thunk (parent=picker, not BaseWin_g) and stay native 100×20 ✓.

**(C) Fonts:** cellName 12 and button 14 are FIXED; stats/big = max(N, colw/15) which already scales with colw (24 @4K vs 10 native ≈ ×2.4) — so only the two fixed ones are truly broken.

Also settled: scrollbar never inited (count=5 < visCells=20) so the stray "1" tab is NOT the scrollbar; FUN_49D540 never fired → most likely a MAP element behind the oversized window, not picker chrome (v2 confirms). Cell-rect law and icon laws confirmed exactly: `rect={col*colw+0x1B, row*pitch+4, (col+1)*colw+0x18, row*pitch+pitch+1}`, facility icon px = pitch*3/7 (46), unit zoom num = pitch*2/3 (72) — these need no further hooks.

## v2 CLEAN RUN 2026-08-03 @4K — v1's numbers PROVEN, defect (B) quantified

Entry-only v2 ran with the dialog DISPLAYING normally (v1's vanishing was its own forbidden attaches, now confirmed by removal). Every v1 number reproduced bit-identically: BaseWin canvas 1895×-1225 origin (1012,403); grid cols=5 visRows=4 colw=362 pitch=pitchSeed=108; picker canvas POST-init **4737×-3062** vs derived pre-thunk args (0,0,1895,1225) → the ×g/16 double-scale is CONFIRMED, and picker+0x13C/+0x474 both read (0,0,0x1281,0xbf6) = the inflated size (so the clip is inflated too).

**The rightward shift, quantified.** Buttons (queue variant, 6) sit at picker-x 2043..2658 → screen 3055..3670 on a 3840 screen, while the GRID's right edge is 1834 → screen 2846. Recompute the vanilla centering with the TRUE width instead of the inflated one: `(1895 − 103·6 − 32)/2 = 622`, `+5·103 = 1137` → row spans 622..1237, centre 929.5 vs grid centre 930.5 — **perfectly centred under the grid**. So fixing (B) alone re-centres the row; no button-position law of our own is needed.

Font structs read directly (Font_init is detoured — never hook its sites): field[6]=size, field[3]=line height. cellName size=12 lh=15, big=23 lh=30, stats=21 lh=28, button=13 lh=16. Confirms cellName 12 / button 14 are FIXED-native (should be 30 / 35 at g=40) while big/stats already track colw.

Still OPEN: no non-4K run yet (MANDATORY); the map-parent variant (gwinit site 0x494960, parent = MapWin child, where the child arm should NOT fire → canvas should be un-inflated) has never been exercised — both v1 opens and the v2 open all went through the base-screen site 0x494915. v2 bug fixed in v3: entry hooks read args off EBP before the prologue ran (id=198722 garbage) — args are at [esp+4] at a function entry.

## FOUR-RESOLUTION MEASUREMENT COMPLETE 2026-08-03 (clean entry-only runs) — laws DERIVED

| res | g | BaseWin canvas | picker canvas (POST) | colw | pitch | btn x (leftmost..btn0) |
|---|---|---|---|---|---|---|
| 3840×2160 | 40 | 1895×1225 | **4737×3062** | 362 | 108 | 2043..2558 |
| 1600×1200 | 25 | 1184×765 | **1850×1195** | 220 | 108 | 600..1115 |
| 1920×1080 | 22 | 1042×673 | **1432×925** | 192 | 108 | 391..906 |
| 1024×768 | 16 | 758×490 | 758×490 (identity) | 135 | 108 | 54..569 |

All verified by `scratch\verify_laws.py` — every row OK:
- `BaseWin canvas = fl(758·g/16) × fl(490·g/16)` (native 758×490 confirmed at g=16; 758 is the known bw-adapter gate constant).
- **`picker canvas = fl(BaseWin·g/16)` = the DOUBLE-SCALE**, identity at g=16 so the lo-res gate works; the picker's init args are already device-space and `thunk_basewin_gwinit`'s child arm re-scales them.
- `colw = (BaseWin_w − 81)/5` — computed from the TRUE width, so the GRID is correctly sized at every res.
- **`pitch = 108` at every g** — never scales. Every cell interior is resolution-INVARIANT: cell h 105, facility icon 46 (=pitch·3/7), unit zoom num 72 (=pitch·2/3).
- Button row `x_leftmost = (W − 103·n − 32)/2`, step 103, `y = pitch·4+8 = 440`, w=100, h=20 — vanilla math, but fed the INFLATED W. Shift = (W_pick − W_base)/2 = 1421 / 333 / 195 / **0** px. **Feeding the TRUE width re-centres the row under the grid at every res** (grid centre 930.5/575.5/505.5/363.0 vs row centre 929.5/574.5/503.5/361.5, ≤2px) — so fixing the double-scale re-centres the buttons with NO button-position law of our own.
- Fonts (read from the Font structs; Font_init is detoured — never hook its sites): cellName + button metrics are **byte-identical at all four resolutions** = fixed 12 / 14. `big` is effectively constant 24 (max(24,colw/15) — floor dominates) and has no reader. `stats` = max(10, colw/15) DOES track resolution (10/12/14/24 at g=16/22/25/40) but lands ~1 short of proportionate 10·g/16 (=10/13/15/25).

Proportionate targets (vanilla × g/16) for the fix: pitch 108→270/168/148, btn w 100→250/156/137, btn h 20→50/31/27, step 103→257/160/141, row-gap 8, pad 32, cellName 12→30/18/16, btnFont 14→35/21/19, stats 10→25/15/13 (g=40/25/22).

STILL OPEN: (i) the map-parent variant (gwinit site 0x494960) has never been exercised — all four runs entered via the base-screen site 0x494915 (caller 0x417776, queueMode=1); under a MapWin parent the child arm should NOT fire, so the double-scale may be variant-specific. (ii) the stray "1" tab: FUN_49D540 never fired at any res; the only picker-gated text-outs were write_l_3 at a fixed (3,3)/(3,15) from ret 0x5c99d8/0x5c9a58 (outside the picker) — so it is very likely NOT picker chrome.

## FIX BAKED 2026-08-03 (live c65d7e70) — awaiting in-game verification

Group `prodpicker_relayout`: 13 sites, 4 new pcave2 thunks (tail 0xFDB0..0xFF17) + `thunk_basewin_gwinit` v4 (272B). Laws `prodpicker_*` in scaling_laws.py; assembler `scripts\assemble_prodpicker.py`; sweep 6739 green, L1 9390 passed.
- **gwinit v4**: `cmp ecx,0x6A8044 / je chain` at the child arm — ONE compare fixes both the oversized canvas and the button row (the centring math reads [picker+0x4C4]).
- **thunk_pp_layout** @0xA1BDB0, site 0x4939A4 (replaces the 12-byte pitch-copy pair): pitch = fl(108g/16), colw = (W − fl(0x51g/16))/5. Register contract: leaves eax = W − marginS so the engine's own `idiv edi` recomputes the column count consistently.
- **thunk_pp_font / font10** @0xA1BE00 / 0xA1BE30: Font_init call-target redirects. `big` (0x493A13) deliberately NOT redirected (colw-driven AND has no reader).
- **thunk_pp_btn** @0xA1BE60, all 9 BaseButton_init sites: full button-row law. KEY TRICK — button position is INIT ORDER, not slot index, and a counter would go stale; instead invert the caller's own arithmetic, `k = (x_caller − xl_nat)/103`, since the caller's btn_w field and pad stay untouched. Stateless.
- Verified by Unicorn end-to-end against the law module for g 16..40 × counts 4/5/6 × every position (0 mismatches) and by re-reading the LIVE exe's 13 rel32s.

**PASS 2 (live 15f0248a, 2026-08-03)** — pass 1 was user-checked at 4K: every predicted geometry number hit exactly, but the button CONTENT still drew at the native 20px art height inside the correct 250×50 windows (measured: lavender band only picker-y 1101..1122 of a 1100..1150 window) → labels vertically clipped. Cause: the picker is not a BasePop, so `g_popup_active` never armed and its FlatButtons passed NO zoom gate — the only scaled button family in the game drawing unzoomed. Fix: `thunk_basewin_btnzoom` v5 (83B) gains a second range arm for [0x6A8BB8, 0x6AF164) (= picker+0xB74 .. its ScrollBar at +0x7120) sharing the bracket epilogue with the BaseWin arm; NO btnfont swap on that arm (the picker sets its own scaled font). Safe because the zoom chain DESCALES the scaled canvas to the native art (btn_native_dim, ceil(dev·16/g)) and KSB-refills — it changes rendering, never the window rect.
⚠ v5's growth silently overran `thunk_scale_reject_uncache` @pcave2+0xB430 (a later, unrelated arc); the assembler's own slot assert could not see it. Relocated 0xB430→0xB300, verified in the built exe (8 call sites moved, 0 stale). Lesson in [[feedback-cave-ledger-lengths]].

REUSABLE LESSON: when vanilla's own layout math is correct and only its INPUT is corrupted, fix the input — the button row needed no position law of ours, just an un-inflated width. And when a per-item index isn't available at a hook, check whether the caller's own arithmetic can be INVERTED to recover it instead of adding state.

DEFERRED (stage 2): draw_cell's rect insets (0x1B/4/0x18/1) are still native → grid ~40px left of faithful at 4K, inter-cell gaps 3px instead of 7. `prodpicker_cell_rect` in the law module already states the correct form.

## Fix-design leads (untested — verify against trace first)
- Scale the single pitch seed (108×g/16 at ctor or the +0xA820 copy site @0x4939A4) and most cell content follows proportionally; fonts ×g/16 per [[feedback-font-metric-sublinearity]] rules; buttons need w/h/y ×g/16 (x-centering already uses scaled width); scrollbar native consts ×g/16.
- Must state laws in `scaling_laws.py` first and port ([[project-scaling-laws-harness]]); vis_rows=3+(ScreenWidth>800) is resolution-conditional — keep semantics.
- Watch [[feedback-remainder-distribution]] on 5-column split (w−81)/5 and [[feedback-shared-field-per-row-doublescale]] on the +0xA838 seed (written once in ctor, ctor runs once per BaseWin ctor — an exec-entry detour re-scaling +0xA820 per open is safer than mutating the seed).

## PASS 3 BAKED 2026-08-03 (live 3f199551) — native additive constants inside device space

Pass 2 was user-checked at 4K + 1600×1200: buttons no longer clipped (labels fill them). Three
defects remained, ALL the same class — a NATIVE additive constant living inside an already
device-space window:
1. **Grid art displaced LEFT** — `ProdPicker_draw_cell`'s rect insets (0x1B/4/0x18/1) never scaled.
2. **Large BLACK band down the RIGHT** — the outer frame is native `0x17` .. `W−0x4E`, so it ran
   past the grid's right edge (g=25: grid ends 1079, frame ran to 1129). Vanilla's gutter is a
   symmetric 4px each side; ours had become 4 left / **50** right.
3. **Button-box frame stroke unscaled + mis-positioned** — pass 1 rewrote the *pushed args* to
   `BaseButton_init`, but the frame is drawn LATER from four locals the caller derives with its own
   native arithmetic and then outsets by a native 3. Rewriting args can never move it.

Three thunks, three sites (all verified by re-reading the LIVE exe, not the yaml):
- `thunk_pp_frame` @0xA0F800 ← site 0x494993 (7B `mov [ebp-0x3C],0x17`, +2 NOP)
- `thunk_pp_cellrect` @0xA0F840 ← site 0x492829 (21B inset block, +16 NOP; the thunk performs the
  two `mov [ebp-0xC]/[ebp-8]` stores itself)
- `thunk_pp_btnframe` @0xA0F8A0 ← site 0x494F54 (5B `mov eax,3`; ends `xchg edx,esi / xor eax,eax`
  so the caller's four ±eax outsets become no-ops)
Sweep 6740 green, L1 9394 passed, Unicorn 0 mismatches g=16..40.

**THE LAW THAT SAVED IT (would have shipped wrong).** The first draft scaled the frame's two
constants in place — correct at 4K, but the sweep showed the two gutters drifting up to **4px
apart** at g=28/30/37/39, because the grid's right edge is `5·colw` and `colw` FLOORS, shedding
pixels that a window-derived frame doesn't ([[feedback-remainder-distribution]]). Both frame thunks
now derive the chrome rect from the CONTENT they wrap (LAW 5 chrome-follows-content, skill
`scaling-layout`), never from the window:
```python
def prodpicker_frame_rect(colw, win_h, g):
    gut = basewin_pt(PRODPICKER_CELL_GUTTER, g)          # 4 native
    return (basewin_pt(PRODPICKER_CELL_L, g) - gut, 0,
            5 * colw + basewin_pt(PRODPICKER_CELL_R, g) + gut, win_h)
```
Gutters are equal BY CONSTRUCTION at every g (4/5/6/10 at g=16/22/25/40, both sides), and g=16
collapses algebraically to vanilla (`27−4 = 23`; `5·135+24+4 = 703 = W−55`) — a proof, not a test
that happens to pass. Verified rects: (23,703) g=16 / (32,968) g=22 / (36,1098) g=25 / (57,1760) g=40.
`prodpicker_btn_frame` derives from `prodpicker_button_rects` ± `basewin_pt(3,g)` for the same reason.

Cave occupancy for 0x3800..0x391B was proven free from patches.yaml (ALL groups — content entries
AND symbol spans) **and** empirically from the live exe BEFORE wiring, per the 0xB430 collision one
pass earlier. It was genuinely free (nearest occupants 0x37A0..0x37F6 and 0x3A00).

STILL AWAITING: user verification of pass 3 at 4K + ≥1 non-4K. Then CHANGELOG.md gets its first
line for this arc (one consolidated player-facing line, per [[feedback-changelog-vanilla-baseline]]).
Still deferred: the scrollbar geometry is native (`init @0x4949DE` at `(w−0x14, 0x15, 0x18, 0x13A)`)
— only visible with >20 buildable items; and the map-parent open variant (gwinit site 0x494960) has
still never been exercised at any resolution.

## PASS 4 BAKED 2026-08-04 (live b1a897e4) — stroke weight + art-flush left edge

User verified pass 3 at ALL FOUR resolutions: the three pass-3 fixes landed, but frame strokes
wrong two ways (pixel-measured from the 4 shots vs refs\pristine\BaseProduction.png — pristine is
a 4K NN-stretched capture: frame band = 2px green / 8px navy / 2px green ≈ native 1/3/1 × 2.8):

1. **Hairline strokes at every g.** All three picker 9-slice draws — grid frame 0x4949A0, cell
   outline 0x492889 (×20), button-box frame 0x494F7C — called plain `Buffer_box_sprite`, whose
   edges tile at NATIVE cross-thickness. Fix: `thunk_pp_boxsprite` (35B @pcave2+0x3930 = 0xA0F930),
   call-target redirect at all 3 sites = thunk_pref_boxframe's dispatch MINUS rect scaling (picker
   rects already device-space from pass 3): `[params+0x20]!=0 → thunk_box_thick_devfill(0xA102A0)
   else thunk_box_thick_hollow_flat(0xA0C140)` — K=half_down(g,16)-wide band-map strokes, the
   user-approved stroke law of every other frame; g≤16 → plain 0x5E2DD3.
2. **"Left stroke too bright" at g=22/25.** The bright pixel is the **BaseWin console frame's own
   left stroke** — `basewin_console_frame_rect.left == bp(0x17)` = 31@g22 / 35@g25, measured at
   exactly those device columns in the shots. Vanilla draws picker frame and console frame
   COINCIDENT at x=23; pass-3's `L = bp(27)−bp(4)` sits 1px right of `bp(23)` at g=22/25 (equal at
   g=16/40 — why only those two resolutions showed it). Fix: `thunk_pp_frame` **v2**:
   `L = bp(0x17)` exactly (art-flush; flush neighbors share ONE floor cascade,
   [[feedback-floor-descale-roundtrip]] / [[feedback-match-opposite-edge-margin]]); R mirrors the
   stroke-to-grid gutter on the grid's right edge and **K cancels out of the rect**:
   `R = 5·colw + bp(0x18) + bp(0x1B) − bp(0x17)`. g=16 identity algebraic (23; 675+24+27−23=703).
   4K unchanged (57/1760); g=22 (32,968)→(31,969); g=25 (36,1098)→(35,1099).

Law `prodpicker_frame_rect` v2 + sweep asserts (art-flush `fl == bp(0x17)`; visible gutters
`grid_l−fl−K == fr−K−grid_r` equal ∀g; gutter within ±2 of bp(3)). Unicorn: v2 thunk vs law,
200 cases (g 16..40 × 8 colw), identity + ecx/edx/ebx/esp preservation — 0 fails. Sweep 6740
green; full L1 exit 0 (dry-run site pin 677→680); clean apply == live == **b1a897e4**;
independent binary verify ALL PASSED (verify_pass4.py).

LESSON (diagnosis): the "mystery bright bevel" was OUR OWN base-screen console frame — when a
stroke defect appears only at some resolutions, check which of our own neighbors shares the
column at g=16 and whether the two cascades split identically (`bp(a)−bp(b) ≠ bp(a−b)`).

KNOWN 1px WATCH: at g=22 the base scene's ledge art brushes/overdraws the picker's bottom frame
row across the width (vanilla has the same overlap only where the tank sprite pokes over the
corner). Not addressed; ask at verification whether it reads as a defect.

STILL AWAITING: user verification of pass 4 at 4K + ≥1 non-4K (left edge no longer bright at
1920/1600; strokes now weighted like every other scaled frame at 4K). Then the arc's CHANGELOG
line. Scrollbar + map-parent variant still deferred as before.

## PASS 5 OPEN 2026-08-05 — label-y + hit-box (user checked pass 4: strokes GOOD)

Two defects: (1) cell text "still too low", (2) "hit boxes not aligned, maybe native sized".
MEASURED (4K shot vs pristine, cell-interior-normalized): TITLE ~7px from top vs ~15
proportional — cause CONFIRMED: title rect (L, T+5, R, T+3m+5), native +5 at 0x492ac5/0x492ad0.
Bottom stats block gap ~5px vs ~9-10 — bottom-anchored y = B−h, h from SCALED font metrics
([[feedback-font-metric-sublinearity]]); exact flow needs runtime numbers.
HIT BOXES: select = 0x4941C0 (vtbl+0x4C of vtable 0x66a250; LOCAL coords; args x=[esp+4]
y=[esp+8] — historical "[select] item=" log values were actually X COORDS): col = x/colw,
row = y/pitch — scaled fields, NO inset subtraction → right bp(0x1B)/bottom bp(4) band of every
drawn cell selects the neighbor. Proportionally == vanilla (20% of colw) — NOT native-sized,
a vanilla misalignment that 4K magnifies in absolute px. Candidate: subtract bp(0x1B)/bp(4)
at g>16. Right-click menu 0x493EA0 consumes +0xA774 set by 0x4941C0 → one fix covers both.
draw_cell text stack (static .bak, per cell): set big font a9c → title 0x5DDAB0 rect
(L,T+5,R,T+3m+5); set stats font aec → rect2 (L+2,T,R−2,B), h=0x5DC360(text,w), y=B−h, desc
0x5DDAB0; y−=lh, name write_cent_l_7 0x492bfb; unit branch builds "N turns\nA-B-C" →
write_cent_l_7 0x492e5b rect=cell (its vertical semantics UNRESOLVED statically — engine's
y=T+(B−T−[font+0x10])/2 contradicts observed bottom placement in BOTH pristine and patched;
don't re-derive, trace it). PATCH-LAYER FACTS: 0x5DD130 entry-detoured (thunk_comm_cent7,
gate ecx==0x7FDA8C commlink); 0x5DCAE0 entry-detoured (thunk_menu_text @0xA121A0, gate
ecx==0x938520 menu) — picker text passes through vanilla; 0x5DDAB0/0x5DC360/0x5DC7C0 clean.
hook_prodpicker.js v3 READY: text-geometry via 0x5DDAB0+0x5DC360 entries + 0xA121A0
detour-target entry (all 3 windows branch-target-audited); [select] logs x,y.

## PASS 5 BAKED 2026-08-05 (live 5696ec0e) — awaiting user verify

v3 trace runs (4K + 1024, user edge-clicked) pinned everything:
- TEXT STACK per cell (runtime truth): title 0x5DDAB0 rect (L, T+1+5, R, T+3m+5), write y =
  rect.top (10 native / 16 @4K). Bottom block: h = Buffer_wrap_height(text, w) = n_lines·m,
  m = stats f0>=0 ? f4+f0 : lh (10 native / 23 @4K — SUBLINEAR vs proportional 25);
  "1-1-2" 0x5DDAB0 at y1 = (B−1)−h (98/248); "22 turns" write_cent_l_7 in one-line band
  (y1−m..y1) → y2 = y1−m+(m−f4)/2 — EXACT at both res (89/226). The static "centers both
  axes in full cell rect" contradiction was resolved by the runtime rects: the 0x492E5B
  write_cent never fires in these modes; the band rect is what write_cent receives.
  f0 is a runtime-cached line-pad (starts −1, becomes 3 after first use) — NOT scaled.
- FIXES (4 thunks, group prodpicker_relayout, all Unicorn-verified vs laws):
  thunk_pp_titlepad @0x39B0 (20B cut 0x492AC2): pad 5 → bp(6)−1 (total offset bp(6); ebx
  preserved — item idx). thunk_pp_measure @0xFF20 (redirect 0x492B6D wrapping 0x5DC360 ret 8):
  h' = h·(bp(11)−1)/m → each line anchors bp(11)/line above cell bottom; m read live only for
  n. thunk_pp_hity @0x3960 (7B cut 0x4941CA — NOT 0x4941C3: prologue pushes interleave, cut
  after them; ecx dead) + thunk_pp_hitx @0x3980 (17B cut 0x4941D9; ecx=old-sel LIVE,
  preserved; edx-only scratch): hit col/row subtract bp(0x1B)/bp(4) at g>16 = hit grid aligns
  to DRAWN cells (DELIBERATE improvement over vanilla's 20%-band skew, g≤16 bit-exact).
- Laws prodpicker_title_pad / prodpicker_stats_h / prodpicker_hit_cell (+_idiv trunc-to-zero
  helper); sweep + L1 green (pin 680→684); clean apply == live == 5696ec0e; verify_pass5.py
  ALL PASSED. Symbols: ProdPicker_select_from_xy (old "select(item)" arg was the X COORD),
  GraphicWin_local_to_screen 0x5ED240, wrap_height convention; Ghidra labels applied.
- LESSON (tooling): Unicorn caches translated blocks — a fake callee whose immediate is
  rewritten per-case goes stale; make stubs read their return value from DATA.
Pass-5 user verdict (2026-08-05): title/stats/scaled-res hits GOOD; 1024 still
mis-hits (vanilla's own skew, deliberately kept) + cell-field banding inconsistent across res.

## PASS 5b USER-VERIFIED 2026-08-05 (live 5ee78e37) — hit alignment at NATIVE too, CLOSED

User asked for the 1024 hit skew fixed as well → the g≤16 gate REMOVED from thunk_pp_hity
(27→22B) / thunk_pp_hitx (37→32B): select mapping subtracts bp(4)/bp(0x1B) at EVERY g (bp is
identity at g=16 → native 4/0x1B). THE one sanctioned exception to the native-no-op invariant
(deliberate vanilla-bug fix, user-requested). prodpicker_hit_cell unconditional; tests assert
drawn-cell alignment ∀g 16..40; sweep+L1 green; Unicorn OK; clean apply == live == 5ee78e37.
USER-VERIFIED same evening ("the hit fix is good"). CHANGELOG: picker added to the base-screen
line + its own vanilla hit-skew Fixes line.

## PASS 5c USER-VERIFIED 2026-08-06 (live e828237a) — "all resolutions look great"; ARC CLOSED

ProdPicker arc CLOSED (passes 1-5c all user-verified all-res). DEFERRED items: (1) scrollbar
native geometry @0x4949DE — only inits with >20 buildable items, never seen in a session, will
render native-thin when it appears; (2) map-parent gwinit variant 0x494960 (flag 0x1000020)
never exercised — all sessions used the base-screen site 0x494915/0x1004020 (confirmed via the
gw_clear flags in the 2026-08-06 field trace); (3) g=22 bottom-ledge 1px accepted-by-silence;
(4) ornate border art (popup-family-wide, LOW).

⚠ First bake 854fc1e8 HARD-CRASHED: v6's relocation target 0xE380 sat inside g_staple_scratch's
2304B runtime BSS 0xE360..0xEC60 (staple-coverage 48×48 capture, zero on disk, symbol sizeless) —
my contents+symbols+file-zeros occupancy scan couldn't see it; the pcave2 length: LEDGER declared
it. 4th escape of the ledger class → [[feedback-cave-ledger-lengths]] updated: ALLOCATE FROM THE
LEDGER; scratch symbols now declare size: (staple 0x900/chev 0x190/arrow 0x1F8 — arrow had NO
symbol) so the overlap guard sees true spans. Fix: pcave2 grown 0x10000→0x11000, v6 → +0x10000
(bytes VA-independent), full chain re-verified (Unicorn/L1/census/verify_pass5c ALL PASSED).

Trace frida_pp_field.log (run-frida-ppfield.bat @1600; shortcuts repointed to hook_pp_field.js;
⚠ the first attempt loaded the OLD v3 hook via shortcut — check the log FILENAME) OVERTURNED
the screenshot-era model. Engine ground truth:
- My palette-resolve vs iface.pcx was WRONG (base screen uses a different active palette than
  those files) — engine pairs: unsel 0xC4/0x41, sel 0xBF/0x53, grid gutter 0x41/0xC5. LESSON:
  palette-mapping a screenshot against a guessed .pcx palette is a MODEL; sample the buffer.
- ALL cell draws are devfill-FILLED (not hollow): unsel params 78D528 fill = 24×24 c4/41 tile,
  sel 78D578 fill = 24×24 bf/53, grid-frame stack-copy fill = 10×10 41/c5 tiled over the whole
  grid interior. GraphicWin_clear(picker,9) at open; per-select only the two affected cells
  redraw (their fill re-tile covers ghosts — no restore pass).
- The unselected field was ALREADY P-striped by devfill STEP3's v5 remap (canvas 41,c4,c4 @g25
  = P3/hN2 exact — my screenshot "beat" read was a MISREAD of uniform 1,2 runs). The real
  defects: 0xBF/0x53 and 0x41/0xC5 weren't in the remap's pair table → stayed 1px device
  density → "inconsistent banding".
FIX = thunk_fe_pair_remap v6 (866B, RELOCATED 0xC1C0→0xE380, 3 {rel32:} callers, old slot
zeros, 4 globals @0x39E0 in the titlepad-gap): force-path dest pre-scan counts C4/C6/C5/BF and
stripes the dominating pair (> w/2 content-keyed per draw → no other screen changes; 0x41
arbitration navy→bd→C5, well-defined by pigeonhole exclusivity). Laws DITHER_FORCE_PAIRS/
stripe_period/stripe_top/dither_force_mate (golden vector = the logged column); parity tests
updated (REMAP_VA; sentinels 0x7D→0x7F to clear assemble_clipfix's family in the shared test
emulator); Unicorn ALL OK; L1 green; verify_pass5c.py ALL PASSED (built-exe caller census).
AWAITING VERIFY: 1600+4K selected cell + gutters striped like unsel, 1024 unchanged, one
shared-remap screen (filedlg/Quit) spot-checked.

CHANGELOG after user confirms; g=22 ledge watch, scrollbar, map-parent variant still deferred.
