---
name: project-smac-council-screen
description: PLANETARY COUNCIL session screen + its popups (tally, PROTOCOL DIRECTOR, Cast-a-Vote, WhoToVote, DiploBribe) — CLOSED user-verified all-res, build 90cb1601, committed; bake mechanism, v1-v6 history, lessons, deferred items
type: project
---

# Planetary Council session-screen scaling — CLOSED

**Final state (2026-08-23): group `council_scale`, build 90cb1601, USER-VERIFIED "all fixes landed at all resolutions", COMMITTED.** Src `work\scripts\assemble_council.py` (+ `splice_council.py`, title_stash v7 in `assemble_pf_align.py`); parity `tests\test_council_asm_parity.py` + sweep `test_scaling_council.py` (173 council cases); probe/crash-catcher `work\scripts\hook_council_crash.js` (gitignored; THUNKS table pinned to 90cb1601). Full run-by-run history: the maintainer's work log git history (deleted at close per file convention) + the superseded-build chain in the patched_md5 comment.

## Mechanism inventory (condensed BAKE RECORD)
- Tally screen (CouncilWin 0x6FEC80, symbols in terranx.h): thunk_cw_enter (@0x4284CA, g_council_active bracket + one-time VirtualProtect imm unlock), 40 painter/exec immediates = dp(A)−dp(B) runtime table, thunk_cw_seeds (law council_seed_rects), thunk_cw_texty, thunk_cw_portrait/logo (sd2 num=g den=16 + thunk_parity_reblit — pair-granular centre-NN scanline regeneration), frames/chips through the box_thick family (3-pass chip: fill→hollow frame→tile_mask), thunk_cw_backdrop37, thunk_btn_gate_pre v2 (6 FlatButton faces HIT).
- Cast-a-Vote: thunk_gv_arthead v2 ([popup+0x3168] head; council-active & ornate & art & no-body → thunk_sprite_draw with device seeds and **y −= dp(6)−6**, else t_dp_artalign), thunk_gv_frameskip (empty-body frame hide, user-directed divergence), thunk_flag_restripe (@0x5E4C01 = the ONE filename-backed-art chokepoint, content-gated pair-LUT; covers the PD modal too).
- Talk popups: textfollow v2, artalign v6, fieldpads v9 (ornate = engine arm), title_stash v7 (ornate band at s(13)/s(37), law ornate_title_rect), thunk_sd_reblit_wrap (bribe portrait parity-reblit; faction-quote buffer excluded).
- Cave: pcave2 tail 0x12940..0x13B94; g_flag_lut @0x12C00 needs BIT 8 CLEAR (xor ebx,0x100 toggles).

## Key lessons (v1-v6)
- **v1 crash 1a2da25b**: templatize() emitted branch operands as {abs32:} → [[feedback-templatize-branch-operands]] + test_template_roundtrip_is_exact.
- **v3/v4 detours**: fitted corrections against an ASSUMED window origin; the 4K popup-local probe (run 23c) showed the engine chain [30e8]/T/union/text was proportionate all along — only the ornate band was 6px low (title_stash added s(13)−13 to an engine top of 9+ps3+ceil(g/16), not 13). **Probe popup-local coordinates before touching laws.**
- **v6 UN-flag 9px low (the arc's last defect)**: thunk_sprite_draw applies vanilla's NATIVE draw offset x−5,y−6 (bytes 83 E9 05 83 EA 06, parity with sprite_draw_func 0x404860) to already-DEVICE seeds → art low by dp(6)−6 (9@g40, 3@g25, 0@g16). CLASS: a native additive constant applied after device-scaled seeds under-shifts by dp(c)−c — same family as [[project-smac-netwin-lobby]]'s "native additive constants must scale". Hidden while band+field were also ~6px low; v5's band fix exposed it. Fix scoped to the gv armed branch; the SHARED thunk_sprite_draw untouched (every other popup's laws were derived with the native −6 in place). Law council_castvote_art v2.
- **Pristine-reference coordinate space**: refs\pristine\Council\BadCastVote.png is a 1024×768 capture PRACX whole-screen-stretched to 4K (×2.8125 = 2160/768). Identify a ref's space from an INVARIANT (flag native height 118 = 332/2.8125 = 295/2.5), then compare RELATIONS (band-gap, row-gap) across shots — no popup origin needed. Two independent relations agreeing on the same shift pins a translation defect and its size.

## Deferred / open (never flagged by the maintainer)
- CouncilWin slide_show/hide rail arming @0x426FF6/0x427039 (diplo precedent) — only if a native side-bar shows during the council open/close slide; wrap the two E8s with thunk_popup_railshow/railhide.
- Cast-a-Vote art X residual: measured +3.7 dev @g40 vs vanilla ≠ the dp(5)−5=7 model (x seed sum [30e0]+[30f0]+[21c8] unattributed). User passed this placement in v28 and at close. **PROBE before ever touching** — an unattributed compensation is eyeballing.
- Pre-existing (bisect-proven on e197205b, not ours): none left open here; see [[project-smac-council-popup]] for the earlier pair (type-16 measure + button double-enlarge, 798b1660).
