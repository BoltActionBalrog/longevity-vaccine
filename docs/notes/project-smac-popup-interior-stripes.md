---
name: project-smac-popup-interior-stripes
description: Popup flat-black interiors (devfill 1px) + type-16 rows-vs-OK width laws — mirror law for no-art popups, wM for ART popups (field sits right of art); a4ceb34b VERIFIED RELEASE LOCK
type: project
---

# Popup interior stripes + q16 width laws (CLOSED: build **a4ceb34b** v3 = VERIFIED RELEASE LOCK,
2026-07-04 user all-res sign-off "Perfect", CHANGELOG'd, committed)

**v2 ced623e3 user-verified good at ALL resolutions EXCEPT SP Quit** (rows overran the frame): SP Quit
is an ART popup — its prompt field sits RIGHT of the art ({593..1920} in a 2080 box @4K), so the mirror
law computed rows = 593+1920−2·82 = 2350 > box 2080 (frida gwin x=82 w=2350; OK = 1831 = wM = 977·30>>4).
**LAW: the field-mirror is only lawful when the rows sit inside the field's horizontal span — art popups
([popup+0x2144]≠0) must take the wM arm (== the OK bar's law).** Fix (v3): fieldpads v5 (148B, RELOCATED
0x43A0→0x4550, measured — 29B check outgrew the 128B slot against q16 @0x4420) stashes g_field_L=R=0 when
art present (boxw still stashed so the gate matches); q16's mirror arm goes negative and its SIGNED max
(`7D` jge, verified in disasm) picks wM. WIMPOUT (no art, mirror 1200) + menu popups untouched.
Probe gotcha: v2's trace had no [q16_fill]/[DEVFILL] lines because hook_wimpout.js still watched the
FREED v1 slots (0x3EF0/0xE00) — re-pointed at 0x4420/0x42A0; when a thunk relocates, sweep the probes.

**v1 ffb6dd8d CRASHED on first popup close (user report + AV @0xa0f631 in frida_wimpout.log):** the
railhide g_field_boxw-clear prepend grew it 110→120B — the yaml LEDGER said 100B, the real thunk was 110
(an earlier prepend) — so the tail landed under g_popup_railsave @0x3630, a runtime DATA slot railshow
writes: the pointer store zeroed the tail bytes → jle into garbage. LESSONS: (1) **measure a thunk's
actual byte length before growing it in place — never trust ledger lengths**; (2) code laid over a
symbol-only offset is invisible to content-vs-content checks — data slots have no content entry; NEW
pytest `test_cave_contents_do_not_overlap` models cave symbols without a same-start content entry as
4-byte spans and catches the class (proved on the crashing layout). Fix: railhide v3 RELOCATED
0x35C0→0x44D0 (120B, callers are {abs32:} refs; old slot zeros, g_popup_railsave stays 0x3630).

User report: refs\MangledSmacx.png (in-game MP quit `#WIMPOUT`, downscaled 4K capture — a ⅔-bilinear
capture turns 1px dither into the pair-average flat colour, e.g. (6,6,8) = avg of (0,0,0)/(13,13,17);
recognize that signature) vs refs\pristine\Multiplayer\Quit.png (pristine, GPU-stretched 1024 capture).
Ground truth: work\frida_wimpout.log (probe work\scripts\hook_wimpout.js — RLE pixel dumps of popup+0x444,
GWinit census, q16/devfill/pf-chain fire logs; wired to all 4 launcher trace shortcuts).

## Defect 1 — interior reads flat black at 4K (ALL popups, NOT a recent regression)
- Every popup's d690 backdrop AND d528 body-inner render via `thunk_box_thick_devfill` (shared sites:
  d690 draw 0x405f77 + channel_adjust/pf_frame_align d528) whose STEP2 tiles the fill mask 1:1 at
  device res → **1px scanlines** (dump: interior = 1px 0x41/0xC6; prompt field = 1px 0x41/0xC4) since
  the A5 quote-box wiring. The P-stripe popup dither language (c592d318) never reached them; the maintainer's
  new pristine ref set made it visible. SP Quit "looked fine" at sign-offs = same 1px, unnoticed.
- FIX: devfill v2 (pcave2 0x42A0, 250B) STEP3 stages g_fe_dst/x/y/w/h from the inset scratch rect
  (g_devfill_rect 0xEF0 — clamped by hollow_flat's clamp_frame_rect already), sets one-shot `g_rm_force`,
  calls fe_pair_remap; **v4 remap** (0x4000, 650B): force path pre-scans the DEST rect (counts C4 AND
  C6 over ≤8 rows, >w/2 ⇒ pair on — content-keyed, solid fills stay) and adds the **backdrop pair
  0x41/0xC6** (force path ONLY; the frame-enlarge path is v3-identical). Faction-quote winbuf
  **0x940824** (= 0x9403e0+0x444) skips STEP3 — the picker's approved language is 1px (A5 lock).
- "Pure black above the band" = the scaled solid-0x41 title-ring pre-fill — vanilla-proportionate
  (0x41 IS (0,0,0) in the in-game palette; navy only in the menu palette). Re-judge after striping.
- src `scripts\assemble_devfill_stripes.py` (keystone; sentinel→placeholder emit).

## Defect 2 — WIMPOUT rows wider than OK + flush under the field's right stroke
- q16 v2 max-law took the `box_w−2x` arm (WIMPOUT box is PROMPT-driven under scaled measurement:
  box 1449, w5c 531 → wM 995 < 1285) while OK = 1200. **In-game popup boxes are ASYMMETRIC** (vanilla
  abutment: rail 23 left vs rail+gap 55 right ×g/16) so box_w−2x overruns right (the recorded q8
  gotcha). The OK bar is the LAW: dump proved OK = exact mirror inside the FIELD content (82..1282 in
  field 66..1298, 16px margins) — anchor the RELATION.
- FIX: fieldpads v4 (0x43A0) stashes field L/R (pre-grow; symmetric stroke-grow cancels in the mirror)
  + popup box_w → g_field_L/R/boxw (draw precedes attach ✓ log-proven); q16 v3 (0x4420) box arm →
  `g_field_L+g_field_R−2x` when `[D+0x34c]==g_field_boxw`, else symmetric box_w−2x (menu popups);
  consume-on-use + railhide clears the stash (+10B prepend). Quit keeps wM=1831 (max), HOST/JOIN keeps
  1205 (menu arm) — no regression by construction.

## Gotchas / laws (reusable)
- `rep movsd` fails keystone — write `rep movsd dword ptr es:[edi], dword ptr [esi]`.
- Hex-editing yaml thunks is safe when no jcc SPANS the insertion (fieldpads) — else bump the
  displacements (q16: two early `jle tail` +0x1E). {rel32:} placeholders recompute at apply ✓ prepends fine.
- pcave2 grown 0x4000→0x4800 (section raw auto-aligns to 0x5000); freed slots 0xE00/0x3800/0x3860/0x3EF0
  zero on clean apply.
- WIMPOUT popupId collides with SP Quit ('Sid Meier's ALPHA CENTAURI' both) — dedup dumps per-id miss
  the second popup; key on box_w too next time.

Related: [[project-smac-multiplayer-type2-crash]] (q16 v2 history), [[project-smac-popup-chrome]]
(fieldpads/railhide), [[project-smac-filedlg-dither-synthesis]] + [[feedback-dither-pair-ambiguity]]
(stripe law), [[project-smac-a5-native-frame-thickness]] (quote-box 1px stays).
