---
name: project-smac-quit-type8-optionlist
description: Quit-modal 4K fix — type-16 Dialog (rowpitch + fillwidth + OK-gap law v2 CLOSED, final build 95b68156, user-confirmed + CHANGELOG'd); type-8 design kept for genuine type-8 popups (q8 overrun spot-check open); #48 box width resolved (M(g) box correct)
type: project
---

**ALL QUIT FIXES CLOSED (2026-07-03, final build `95b68156`, USER-CONFIRMED + CHANGELOG'd; rowpitch/fillwidth built as `0b358e27`, OK-gap + art-align added through the f7d13698→95b68156 chain):**
1. **Rowpitch** (group `popup_quit_type16_rowpitch`, carried from b55e0869): both `Buffer_text_height` calls in the type-16 calc (0x60d641/0x60d658) → `thunk_quit_rowpitch` (pcave2 0x34D0, 21B gated tail-call to `Buffer_text_line_height`) so pitch == drawn bar height. Prototype user-confirmed rows separate @4K.
2. **Fillwidth** (NEW group `popup_quit_type16_fillwidth`): `Dialog_type16_attach` (0x60d1f0, RET 0x10) creates the row window at the MEASURED text width (GraphicWin_init @0x60d299, w pushed from [esi+0x188]=Dialog[+0x5c]; **Dialog base D = esi+0x12c**, adjustor [vtbl+8]=0xb5c off esi−0xa30) while the box grew ×M(g)=16+(g_boxw_num−16)(g−16)/24 → bars ~53% of the box. **THE LAW (GraphicWin_init census @1600×1200): the OK bar inits at measured_content × M(g) (1035 = 789×21>>4 exactly)** → site 0x60d299 → `thunk_q16_fill_width` (pcave2 0x34F0, 89B): W'=(w×M)>>4 to the w ARG + D[+0x5c]/D[+0x64], ONLY-WIDEN, count([esi+0x1f8])>1, g≤16 native; ecx (window this) preserved via push/pop around the idiv. Prototype hook_quit_fillproto.js v5 USER-CONFIRMED @4K+1600+1920.
- **#48 box width RESOLVED**: the M(g)-scaled box (977→1831 @4K) is CORRECT — the maintainer rejected un-scaled 977 as "not wide enough" vs pristine. The over-wide impression came from the half-width bars.
- **GOTCHA that cost two dead prototypes**: `box_w − 2×x` (the type-8 q8_fill_width law) OVERRAN the modal's right edge at non-4K — by attach time `[popup+0x30bc]` (= D[+0x34c]) already includes the ASYMMETRIC L/R margins (82/167 @4K), so it is NOT the drawn-content anchor. Also: widening the row_w field or the draw rect alone moves NO pixels — the row WINDOW BUFFER clips them; the lever is the window's GraphicWin_init w. **OPEN: thunk_q8_fill_width still uses box_w−2x — check a genuine type-8 story-choice popup's bars vs OK right edge during verify; switch to ×M(g) if it overruns.**
- **Inter-row GAP: CLOSED 2026-07-10 (lock `d7ef0a65`, group `popup_quit_type16_rowgap`, user-verified).**
  NOT "×g/16 the gap" as this note used to say — that is the TRAP. Rows sit on a uniform stride
  `pitch = [D+0x68] rowH + [D+0x44] gap`; rowH already scales (rowpitch fix) but the gap field is a
  struct-copy default (no immediate init in .text) reading a CONSTANT 3 at every g, so 50px bars sat 3px
  apart @4K (vanilla: 20px bars, 2px apart). Scaling the gap proportionately (`half_down(2g,16)` = 2/3/3/5)
  matches the engine at 4K/1600/1920 **and lands rows 1px off at g=18/26/34** — rowH and gap round
  independently. LAW = pin the PITCH, let the gap absorb the rounding (`scaling_laws.py::option_row_gap`):
  `pitch'=half_down(22g,16)`, `gap'=max(0,pitch'-rowH)`; identity at g=16 (22−19=3 = the vanilla field).
  TWO read sites: calc Site B `0x60d731` AND the draw loop `0x60d8f3`, which re-reads the FIELD to rebuild
  its own pitch + a per-row `gap>>1` offset — so the thunk must WRITE `[D+0x44]`; patching only the calc
  grows the box and never moves the bars. `thunk_q16_rowgap` 43B @pcave2+0xA740 (src assemble_q16gap.py),
  Unicorn-verified vs the reference (tests\test_q16gap_asm_parity.py). See WHY.md §9,
  [[feedback-remainder-distribution]].
- Remaining polish (defer): dither-regime mismatch between selected/unselected bars.

**OK-GAP ROOT-CAUSED + BAKED 2026-07-03 (pristine 1024 trace via [[feedback-pristine-baseline-trace]]; prototype user-approved 4K/1600/1920, BAKED into build f7d13698: btn_vpad_scale → NEW helper popup_scale_3half @pcave2+0x250, thunk_btn_vcenter v2 42B in place @0x220 adds popup_scale(3)−3; hook_okgap.js converted to a no-write OBSERVER of the baked laws — do NOT resurrect the mutating version against f7d13698+):**
Native law: `OK_y = box_h − footer − padX − btnH + 3` with `box_h = rows_bottom + [30e4] + btnH + footer` ⇒ **gap above OK = [30e4]+3 = 9 native** (pristine: box_h 284, footer 50, [30d0]=[30d4]=20, [30e4]=6, rows 164+44, OK y 217; 4K cross-check exact: 666=511+10+20+125, 555=521+31+3). The engine is self-consistent at scale — `thunk_grow_box` grows the WINDOW by popup_scale(btnH)−btnH = +30 @4K = exactly the button's own growth, so NO placement correction is needed. Both defects are OURS:
1. `BasePop_calc.btn_vpad_scale` (0x603963): `[30e4] = popup_scale([21c4])` **dropped vanilla's ×3/2** → 10 @4K (faithful 15 = popup_scale(3·[21c4]/2)) and **4 vs vanilla 6 at g=16** (latent native no-op violation; [21c4]=4 stays native at all res).
2. `thunk_btn_vcenter` (pcave2+0x220, site 0x602c49): the +footer/4 (+31 @4K) is a tuned heuristic from BEFORE box-grow was fixed — pure error now.
Lawful fix: (A) [30e4] = (3·[21c4]/2)·g/16 **scale-last** (scale-first loses 1px at g=22); (B) vcenter delta → +(popup_scale(3)−3). Predicted @4K: gap 44→22 (=9×g/16), box_h 671, window 701, below-bar 118 ≈ 47×2.5 faithful; @1024 = pristine exact. **Moves the button row in EVERY popup** (Customize/Difficulty/story) — verify vs PRISTINE, not the prior build. Bake plan: retarget btn_vpad_scale's call to new helper `popup_scale_3half` (11B: lea eax,[eax+eax*2]; sar eax,1; call popup_scale; ret — pcave2+0x250, fits before clamp_frame_rect@0x260); vcenter v2 in place at 0x220 (42B ≤ 64B slot; inner: push edx; mov edx,eax; mov eax,3; call popup_scale; sub eax,3; add eax,edx; pop edx; JLE disp→0x13). popup_scale = menu_strip+0x550 (0x668750), clobbers EAX only, identity at g=16.

**Quit 4K audit (2026-07-02)** — build **d490e018** was built for a TYPE-8 option list, but a follow-up
Frida trace (frida_quit_boxw.log) DISPROVED that: the real Quit popup ("Sid Meier's ALPHA CENTAURI",
box_w 977→1831 @g40) is **`[+0x2350] dialog_type = 16`, NOT 8**, and `[+0x2274]=0` at g40/25/22. All four
stage-1 thunks gate on type==8 / live in the type-8 calc `0x610970` + attach `0x610540`, so they are
**INERT for Quit** (harmless — gates fail closed). DISPATCH TABLE READ 2026-07-02 (byte table 0x613310,
dword targets 0x6132f8, index = dialog_type−1): type1→0x60ED10, type2→0x60A1E0, type4→**0x612150**,
type8→0x610970, **type16 (QUIT) → `0x60D380`** (adjustor `add ecx,0x44`). So BOTH earlier calc claims were
wrong: 0x612150 is dialog_type **4** (the name-prompt), and the real Quit calc is **`0x60D380`** — which the
FIRST census never hooked (that's why no Quit calc appeared; the ListBox/textelem hits were ambient UI).
`0x60D380` (FULLY DISASSEMBLED from .bak) is structurally the option-list calc: `+0xcc` count gate (ret 7 if
0), same **measure-font triple `+0x70/+0x74/+0x78` → 0x5dac70** as type-8, plus a column-grid divide
(`+0x4c` rows/col, `+0x58` cols); row total → Dialog `+0x60` → popup `+0x30c4` content_h.
GROUND-TRUTH row geometry (row_back_draw 0x405b20, 3 res): stride(top-delta)=34/23/22 @g40/25/22 but drawn
bar height=50/31/27, so rows OVERLAP + 2nd clipped ~18%; **content_h `+0x30c4` = row_count × stride**
(68=2×34 etc.), composed in BasePop_calculate_dimensions 0x603800 (content_h write @0x603c76 = Dialog[+0x60];
per-type jump table @0x6042d4). Stride tracks the FONT line-height (~15 native) while the bar draws taller
(~20 native) = **measure≠draw**. OPEN linchpin: is the 50px bar height font-derived (→fix = correct
Dialog[+0x70] measure font for type16, same family as the type-8 stage-1 thunk_qdlg_font but gated type==8)
or a fixed sprite/box (→fix = force the row vertical STEP = row height in the type-16 layout/attach)?
Resolve via the UPDATED hook_quit_rows.js (now hooks 0x60d380 + logs item_back_draw returnAddress = the
stride-computing layout caller) — one more run, then the fix is a confirmed one-pass re-target.

**CENSUS RUN 2 (2026-07-03, 4K+1600) CONFIRMED**: type16_calc_QUIT `0x60d380` fires for Quit, **count=2**,
rowWidth_64=977/789 (=box_w_before), **mfont70=0xa0c810 CONSTANT across res** (measure inputs don't scale).
FULL STATIC MAP of the calc tail (all from .bak): `0x60d380` writes the row total **Dialog[+0x60]** at two
branches — Site A @0x60d717 (flags[+0x20]&1 && [+0x30]≠0: fixed-height mode, [+0x60]=[+0x30]) and **Site B
@0x60d731 (Quit's branch): `[+0x60] = ([+0x68] rowHeight + [+0x44] gap) × [+0x58] count`**. Attach =
**FUN_0060d1f0** (calls calc @0x60d224, creates container win via 0x5d4ef0, copies text style). content_h
`popup+0x30c4` = Dialog[+0x60] (BasePop_calc 0x603800 @0x603c76, src = [popup+item+0x2230] = dialog+0x60).
THE SPLIT: stride(top-step)=content_h/count=[+0x68]+[+0x44]=34 @g40 (font-metric-derived, from the
non-scaling measure inputs) BUT the rect passed to item_back_draw (0x405b20) has **height=50** (scaled),
set by the DRAW-LOOP caller — item_back_draw itself does NOT compute height, it just renders the passed
rect via 0x5e2dd3 (type!=1 path; the 0x5e4b4a sprite draw is type==1 only). So 50 (drawn) ≠ 34 (stride)
= the overlap. REMAINING UNKNOWN: the draw-loop that emits rect.top(+=34)/rect.height(=50) — its
returnAddress capture misfired run 2 (logged self); hook now uses Thread.backtrace (ACCURATE) — ONE more
Quit run gives the caller VA + where 50 originates. FIX SHAPES (pick after that): (a) measure==draw —
make Dialog[+0x70] measure font = the scaled draw font for type16 (extend thunk_qdlg_font's type==8 gate),
so [+0x68] comes out = drawn height, stride=height; or (b) patch Site B @0x60d731 so [+0x60] = drawnRowH ×
count (drawnRowH = vanilla ~20 × g/16). (a) is the type-8-precedent, minimal, but unproven; (b) is direct
but needs the 50 source. box-width #48 still separate (box_w composition @0x603c21-0x603c66 + jump table
0x6042d4 on dialog_type+1).

**ROOT CAUSE FOUND (2026-07-03, census run 3 backtrace + static — fully grounded in NAMED fns)**: the
type-16 draw loop is FUN@~0x60d9xx (backtrace: item_back_draw 0x405b20 called via [item_vtbl+0x2c] @0x60da9a,
ret 0x60da9d). It sizes each option-bar rect.height with **Buffer_text_line_height (0x5dcab0) @0x60da0a**
(=50 @g40). But the calc 0x60d380 computes the row-height [+0x68] that feeds the PITCH/content_h/stride with
**Buffer_text_height (0x5dca80) @0x60d641** (=~34 @g40). `Buffer_text_line_height` (terranx.h: "row-pitch
source") > `Buffer_text_height` (ink height); the gap magnifies with g → stride(34) < bar height(50) →
overlap 16/8/5px @g40/25/22 + 2nd-row clip. **THE FIX = make the calc use line_height for the pitch**:
thunk at the 0x60d641 CALL that, gated on g_popup_scale_num (>16), calls Buffer_text_line_height (0x5dcab0)
instead of Buffer_text_height (0x5dca80) — MUST gate (naked redirect changes native pitch = violates the
g<=16 no-op invariant). Then [+0x68]=line_height, pitch=height, content_h=height*count, stride=height →
no overlap/clip. g_popup_scale_num global = 0x696D18 (num) / 0x696D1C (den 16). 0x60d380 is type-16-EXCLUSIVE
(dispatch-confirmed) so the thunk touches only Quit-class popups. Residual check before "done": the draw
height has an `imul edx,ebx` @0x60da11 (multi-sub-row factor ebx) — for Quit count=2/simple ebx is likely 1;
PROTOTYPE in Frida (override [+0x68]=line_height in 0x60d380 onLeave, re-derive [+0x60]) to SEE rows separate
at 4K AND unchanged at native BEFORE writing the thunk (skill: prototype before asm). Buffer_text_height=
0x5DCA80, Buffer_text_line_height=0x5DCAB0, Buffer_text_width=0x5DC790 (all thinker-named, thiscall self-only). The stage-1
thunks stay dormant (correct for a genuine type-8 popup if one exists) unless repurposed. Below is the
ORIGINAL (mistargeted) type-8 design, kept for reference / for real type-8 popups:

**Architecture discovered (all statically verified, symbols in terranx.h + patches.yaml):**
- Generic popups pick a Dialog TYPE at `[popup+0x2350]`: multi-option (`[+0x2274]>1 && [+0xa14]==0`) ⇒ **type 8**
  (set @0x60266d in BasePop_exec_3). `Dialog_set_type` 0x612970 (sole caller 0x602bfe) stores it → `Dialog[+0x180]`;
  `Dialog_dims_dispatch` 0x6132A0 byte-table: type 1→0x60ED10 (checkbox/text-elem, where ALL our old row levers live),
  2→0x60A1E0 (ListBox), **8→OptionList_calculate_dimensions 0x610970** (a THIRD path we'd never patched), 4→0x612150, 16→0x60D380.
- Type sub-objects are vtable shells; **adjustor `[vtbl+8]` (−0x70 for type 8) points fields back to the shared Dialog base**
  (validated on 3 field pairs). OptionList fields: gap [+0x44], sprite max w/h [+0x54/58] (×[+0x1c]/[+0x20]), text w [+0x5c],
  total [+0x60] (copied → popup [0x30c4] content reserve), row w [+0x64], **pitch [+0x68] = gap + max(text lineH, spriteH)**,
  measure font [+0x70] (= `popup[+0xa3c]`), count [+0xcc], config width [+0x2c] (NOT measured — safe from font changes).
- **Root causes**: (C) rows measured with the native ~24px `[+0xa3c]` font but DRAWN at 40pt (g_pf0 family) → pitch 36 under
  37px ink, rows overlap, 2nd option clipped; gap never scaled. (B) `OptionList_attach` 0x610540 creates the row window at the
  measured text width → bars 47.7% of box vs the **vanilla law: bars span the box content width, flush with the OK bar (95%)**.
- **Fix (group popup_optionlist_type8_scale, 4 sites + 4 pcave2 thunks @0x3400-0x34C8)**: thunk_qdlg_font (@0x602bf3, edx holds
  the type at the site) → type-8 measure font = g_pf0 (**measure==draw law**); thunk_q8_pitchgap/totalgap (@0x610b62/0x610bcf)
  scale the gap addend ×g/16 IN-REGISTER (field never written → re-derived per pass, no compounding); thunk_q8_fill_width
  (@0x6105ec) row window w = box_w([popup+0x30bc], read [R+0x448]) − 2×x-arg, only-widen guarded, stores w arg + [+0x5c] + [+0x64].

**CRITICAL calibration gotcha**: `refs\pristine\Quit.png` is a ~892px-wide PRACX **window** ⇒ engine's SMALL **800-branch** UI.
Faithful 4K multiplier vs that capture = **×3.75** (engine ×1.5 at ≥1024, × our g40/16=2.5) — NOT ×2.5. Elements measuring
~3.75-3.85× (picture, title bar, OK height) are CORRECT; fonts ~4.1× ink = the V2-table design. Never re-judge those.

**Stage 2 open (#48)**: box 4.30× vs 3.75 target (+~260px @4K) + content-left inset 59px vs faithful ~11px — the non-list
×1.875 (`g_boxw_num`) heuristic on a partly-scaled base. Probe ready: `work\tests\frida_quit_boxw.js` logs box_w before/after
the scale site + composition inputs + type-8 measured fields + row-window init args. Redesign the non-list branch for type-8
popups from those numbers (box_w composition @0x603c21-0x603c66: ebp left-column + [0x30e0] margin + max(dialog w, art [0x30d8])).
Minor deferred polish: selected-bar vs unselected/OK dither regimes differ; strokes 2px=floor(2.5).

Related: [[project-smac-modal-scaling]], [[feedback-shared-field-per-row-doublescale]], [[feedback-match-opposite-edge-margin]],
[[project-smac-popup-scale-derivation]], (a private note).
