---
name: project-smac-a5-native-frame-thickness
description: A5 (faction leader-portrait green frame -> BLACK on RIGHT+BOTTOM @1600x1200/g25). 2026-06-17 LARGELY FIXED: thunk_portrait_avg (entry-detour at Sprite_draw_2 0x5E4B4A) replaces the engine's NN scale of the 131x157 portrait sprite with a palette-aware bilinear AVERAGE so the thin baked-in green frame blends instead of dropping at fractional g25. The prior CRASH was a stack-frame aliasing bug (locals overwrote the saved ebx/esi/edi slots -> caller AV at 0x604c81); fixed by reserving the frame BEFORE the reg pushes. Build b644aab3: no crash, frame hugs all edges @1600x1200 (user-verified). REMAINING: minor corner artifact (deferred) + 4K visual pass. Do NOT lock MD5 yet.
type: project
---

# A5: faction leader-portrait green frame blacks on RIGHT + BOTTOM @1600x1200 (g25)

## Current state (2026-06-17) — A5 DONE / CONFIRMED / CLOSED
Build **b644aab3** (MD5 LOCKED in patches.yaml target.patched_md5): `thunk_portrait_avg` detour ENABLED, **no crash**,
green portrait frame **hugs all edges at BOTH 1600x1200 AND 4K (user-verified)**. Regression updated (site count 85→86,
md5 lock 897fdc84→b644aab3 — both deliberate; Layer 1 green) and CHANGELOG line added. CLOSED.
The "small square in the corner where two strokes meet" was assessed and **ruled NOT a bug** (user agreed): the entire
131x157 portrait — backdrop pattern, face, AND baked green bevel frame with its corners — is one sprite, resampled
UNIFORMLY by g/16 in the thunk, so the corner cannot be "unscaled"; it's the faithful magnification of a tiny corner
detail that also exists (smaller) in pristine. Zoomed crops confirm it has the same soft/averaged/scanline-banded quality
as the rest of the frame, not a crisp native overlay. (Only nuance: our bilinear blends the corner stroke against the
adjacent black slightly differently than pristine's NN — cosmetic, accepted.)

## PRODUCTIONIZED — build b644aab3, thunk_portrait_avg (919 bytes)
The averaging fix is a real binary patch: **`thunk_portrait_avg`** (pcave2 +0xA00, **919 bytes**, ends pcave2 +0xD97,
section 0x1000), an **entry-detour at `Sprite_draw_2` (0x5E4B4A)**. Site overwrites 8 bytes with
`68 {abs32:thunk_portrait_avg} C3 90 90` (esp-neutral push/ret jump). Gate `dest==0x940824 && num>den` + validity
guards (den>0, src w/h/data, dest data/stride): match → palette-aware bilinear average (reads Sprite src
data@+0x4/stride@+0x10/w@+0x18/h@+0x1c, palette @0x94c590 colors[256], writes dest@+0x54), `ret 0x18`; no match / guard
fail → 2 displaced movs + `push 0x5E4B52; ret` (the original NN draw). Authored in asm + keystone via
`work\scripts\assemble_resampler.py`.

### The crash (builds a02c02b7 / bffd8684) was a STACK-FRAME ALIASING bug — root-caused empirically, NOT the guards
Two front-loaded Frida runs cracked it (the disassembly looked fine; the bug was register-save layout):
- **Probe** (`hook_a5_portraitprobe.js`): enumerated every `Sprite_draw_2` into box 0x940824. ONLY the clean 131x157
  portrait @25/16 fires the thunk; its source is fully readable and dest writes are in-bounds. So **inputs were never
  the problem** — disproving the "dropped guards / OOB" theory. (KEY ASYMMETRY: an onLeave Frida prototype's bad read is
  a catchable JS exception that leaves the process alive; the native thunk's same read is a hard AV. But here neither
  applied — the read was fine.)
- **AV-capture** (`hook_a5_avcapture.js`, process-wide `Process.setExceptionHandler`, NO Interceptor.attach on the
  detoured fn): caught the fault at **0x604c81** (the BasePop caller) doing `mov eax,[esi+0x30d8]` with **esi=0x83**.
  The corrupted regs held **esi=131, edi=131, ebx=0x7309558** = the thunk's own **sstride / src.w / src.data** locals.
- ROOT CAUSE: prologue was `push ebp; mov ebp,esp; push ebx; push esi; push edi; sub esp,0x90` — saving ebx/esi/edi into
  `[ebp-0x04/-0x08/-0x0C]`, the SAME slots then overwritten by locals sdata/sstride/sw. The epilogue `pop edi/esi/ebx`
  restored garbage into the caller's callee-saved regs → caller used esi=0x83 as `this` → AV.
- FIX: reserve the frame BEFORE pushing — `push ebp; mov ebp,esp; sub esp,0x90; push ebx; push esi; push edi` (saved regs
  now at `[ebp-0x94..-0x9C]`, locals stop at -0x90); epilogue `pop edi; pop esi; pop ebx; mov esp,ebp; pop ebp; ret 0x18`.
  No local renumbering needed. Frida's onLeave never hit this because Frida's trampoline preserves registers.
- LESSON: **a function-REPLACING thunk owns the full callee-saved-register contract** — verify the save slots don't alias
  ebp-relative locals. When porting an onLeave post-processor to a replacement thunk, the frame layout (not just the
  guards) must be correct, and the cheapest way to find such a fault is a process-wide AV handler that dumps regs+frame.

## CENSUS-CONFIRMED portrait draw path (2026-06-16, hook_a5_spritecensus.js — LIVE, not static)
The sprite-path averaging prototype (hook_a5_spriteavg.js) installed but NEVER FIRED — the prior "portrait draws via
Sprite_blit_scaled_core @131x157" was a STATIC decompile claim, never confirmed live. A live census of all four blit
primitives nailed it: the portrait is drawn by **`Sprite_draw_2` (0x5E4B4A) into the faction box (0x940824) at scale
25/16 (g25), top-left x=10 y=12**, which falls into `Sprite_blit_scaled_core` (0x5E4B9A) with the same x/y/gscale. Two
assumptions were WRONG and broke the first re-aim: (1) **the source (ecx=0x790e14) is a SPRITE struct, not a Buffer** —
width is at Sprite+0x18, NOT Buffer+0x80, so the dims gate read 0x0 and never matched; (2) **`Sprite_draw_2` is
thiscall** (ecx=Sprite*; stack = dest, key, x, y, num, den) — its arg2 is the KEY (=9), NOT a spriteId (terranx.h sig is
wrong). The faction FRAMES, by contrast, render native into temp 0x7494c30/0x7495d88 then Buffer_copy_3 StretchBlt-up
then Buffer_draw_2 into the box (the funnel) — a DIFFERENT path from the portrait. Correct re-gate for the portrait =
`dest==0x940824 && num>den`. BLOCKER for averaging: must map the Sprite pixel storage (data ptr/dims/stride) — dumping
via hook_a5_portraitdump.js (hooks Sprite_draw_2, dumps the Sprite struct + probes pointer fields for the bitmap).

## What draws the portrait frame (static audit + terranx.h, 2026-06-15) — the reframe
- The **leader portrait AND its green picture-frame are drawn via `Sprite_draw_2` (0x5E4B4A)** from popup field
  `[+0x2144]` (terranx.h:105), NN-scaled by the engine scale (`SCALE_NUM_G`/`SCALE_DEN_G` @0x696D18/0x696D1C),
  **NOT** by `Buffer_box_sprite`. The green frame is **baked into the 131x157 source sprite** (idx 65=green, 198=black).
- The **five** `Buffer_box_sprite` draws to the faction box 0x940824 are ALL backdrop/title/quote frames, ALL already
  patched, and ALL sit to the RIGHT of the portrait (so they frame the quote, not the portrait):
  - d690 @0x405f77 backdrop -> thunk_box_thick_hollow_flat
  - d5a0 @0x406048 outer    -> thunk_box_thick
  - d618 @0x406078 title inner-border -> thunk_inner_margin   (d618 is the TITLE frame, NOT the portrait frame)
  - d528 @0x406154 quote inner -> thunk_d528_inset
  - d5a0 @0x406238 content -> thunk_content_frame
- Geometry @g25: portrait right=x215 / bottom=y257; d5a0 L=224, d528 L=227 -> a ~9px gap sits between the portrait
  edge and the nearest quote frame. Screenshot readout (MangledSmacx.png @g25): portrait gold -> BLACK(198) ~17px ->
  green text-frame(34) -> blue panel(196).

## Solution-A (averaging in the frame funnel) — DISPROVEN for A5 (2026-06-16)
Prototype `work\scripts\hook_a5_avgscale.js` replaced the NN StretchBlt in thunk_frame_enlarge with a palette-aware
bilinear average for the faction box. Ran clean (correct engine palette) -> ZERO visual change. WHY: with the corrected
palette the box frames are NOT a green/black-aliasing dither (65/198 = black); they're correctly dark. And the green
border that blacks out is on the PORTRAIT SPRITE (drawn via Sprite_draw_2 0x5E4B4A / Sprite_blit_scaled_core 0x5E4B9A),
a path the funnel never touches. So the "dither aliasing in the shared funnel" mechanism below is also SUSPECT and must
be re-diagnosed with correct color labels. NEXT: re-instrument with green=31/34, black=65/198; isolate exactly which
pixels are green @g40 and black @g25 around the portrait; determine if the portrait sprite's own edge (its scaling) or
the d5a0/d528 quote-frame green line is the culprit. Averaging may still be the tool but on the SPRITE path, not the
funnel -- pending that diagnosis.

## (SUSPECT — see Solution-A note above) prior "CONFIRMED mechanism" (2026-06-16, hook_a5_attribution.js)
**Fractional-scale aliasing of dithered frame art, introduced by OUR render-small-then-StretchBlt-upscale path.**
- The defect is SCALE-FACTOR dependent: patched g40 (x2.5) the region around the portrait reads GREEN (portrait R-edge
  RLE `35x2 65x12`, B dark:bright=0.02); patched g25 (x1.5625) the SAME region reads BLACK (R-edge RLE `...198x9 31x2
  198x1`, B dark:bright=2.20). Same art, different scale.
- Source-side dump proves it: the **d690 backdrop 9-slice art is a 50/50 green/black dither** (`SRC edge dither 65:336
  198:336` every edge). Our thunk renders it SMALL into g_frame_buf then StretchBlt-upscales x(g/16). At x2.5 the dither
  allocates evenly -> green; at x1.5625 the fractional vertical resample lands dark-phase rows on R/B -> black. All three
  faction frames (d690/d528/d5a0) funnel through the same enlarge->StretchBlt (Buffer_copy_3).
- **Pristine never StretchBlts.** It renders the faction popup at a FIXED native 722x193 (IDENTICAL at 4K and 1600 in the
  logs, gEff=16, frames "native"), and PRACX upscales the whole composite ONCE -> one clean resample -> solid green hug
  (the maintainer-verified .bak look). So OUR per-frame StretchBlt is the introducer.
- Resolves the old contradiction: pristine does NOT per-element scale the portrait (draws it native); patched DOES
  (Sprite_draw_2 key=9, scale g/16). The portrait's own beveled edge participates but the dominant R/B black is the
  dithered backdrop/frame art aliasing around it, not the sprite alone.

## Fix fork (awaiting user decision 2026-06-16)
1. (lean) **De-dither at fractional scale**: before the StretchBlt, snap g_frame_buf's green/black dither to solid green,
   gated faction-popup + non-integer g (g<=16 native). Surgical; keeps our scaling architecture; frame goes solid-green at
   odd resolutions. NOTE this is DIFFERENT from the earlier ruled-out "de-dither" (that was ruled out when we wrongly
   thought the black was base-game dither, not our StretchBlt) -- now the StretchBlt-aliasing root is confirmed.
2. **Emulate pristine**: stop per-frame StretchBlt for this popup; render native + ride PRACX's clean whole-frame upscale.
   Bigger change; unwinds some faction-popup font/box scaling; hinges on pristine's faction popup being acceptable @1600.

Trace tool kept: `work\scripts\hook_a5_attribution.js` + 4 logs `work\frida_a5_<patched|pristine>_<WxH>.log`. Launcher
shortcuts "A5 Trace - {Patched|Pristine} {1600x1200|4K}" -> `work\run-a5-trace.bat` (self-elevates, sets build, per-run
log, re-applies patched after pristine runs).

## Palette (CORRECTED 2026-06-16 from the LIVE engine palette @0x94c590 == GDI @0x9b8178, identical)
**65 = (0,0,0) PURE BLACK** | 198 = (12,12,16) near-black | **31 = (49,78,44) green** | **34 = (35,59,34) green** |
196 = (13,23,36) blue | 9 = (9,0,0) key. Read via Buffer_sync_to_palette (Palette* arg) + GetPaletteEntries; both
agree. **The old "65 = bright green" note was WRONG and misdirected the whole dither-aliasing analysis.** Consequence:
the d690 backdrop "65/198 dither" is black+near-black = the (correct) dark window backdrop, NOT an aliasing green frame.
The greens that hug/frame are 31/34, drawn elsewhere. To get a palette: hook Buffer_sync_to_palette (0x5DE8F0), its
[esp+4] = Palette* (struct starts PALETTEENTRY colors[256]); Palette_set_active_window (0x5FE4F0) is NOT Frida-hookable
("unable to intercept"). Buffer also has a Palette* field (scan the buffer object + validate; thinker's struct offset
is wrong).

## Ruled out (do not revisit)
- **d690 router / d690 as the culprit (2026-06-15):** routed the faction-box d690 backdrop draw to NATIVE
  Buffer_box_sprite (build a93a898a). In-game @g25 = NO change; @4K = no regression. The old "per-draw attribution
  nailed it to d690" was wrong — d690's `[8]FILL=0x75f3e0` is a DEGENERATE 0x0 sprite (interior is flat fill_param=7,
  it paints nothing in the gap), so rerouting it can't change the gap. The gate fired correctly (ecx==0x940824 at
  d690 was already proven by the prior trace). Reverted -> 897fdc84.
- **thunk_d690_backdrop (null fill + border-only render), build 1f9016eb:** regressed in-game (white inner frame =
  the known "null the fill -> white hatch" artifact) and the black persisted. Reverted.
- **"PRACX populates the fill / hooks leader portraits":** false. d690 is the generic Popup_on_draw_background
  backdrop for ALL popups; BoxSpriteParams are filled at RUNTIME, not a PRACX mod.
- **Variant-pick (engine swaps to a smaller pre-rendered portrait at low g):** false — live source sprite is the
  SAME 131x157 at g40 and g25.
- **De-dither / snap-bright the d528/d5a0 stroke:** dead — d528/d5a0 are the QUOTE frame, right of the portrait,
  not the portrait's green frame.

See (a private note), [[project-smac-a5-portrait-frame]], [[project-smac-frame-strip-key]],
[[project-smac-snapped-border]], [[feedback-proportionate-scaling]], [[feedback-smac-all-resolutions]].
