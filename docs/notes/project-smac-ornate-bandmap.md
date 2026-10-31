---
name: project-smac-ornate-bandmap
description: Ornate frame (def 0x6846B0, corner canvas 61x44) band map: per-side stroke cell + outer-key re-key — BAKED 2026-09-19 exe 5c095931 (src assemble_bandmap_ornate.py), AWAITING re-verify of EVERY ornate menu; plain blit byte-identical
type: project
---

**CLOSED 2026-09-19 commit 5b58698 (live exe 7d407602). MEASURED on the maintainer's shots: breakthrough window + stack picker at 4K and 1600 -> green line K on all four sides, rim 0, margins 8/10/10/0 @g40 and 5/6/6/0 @g25; stack-picker title/container relation unchanged; faction picker (NO ornate frame — my earlier note was wrong) byte-identical to 09-18. Was: BAKED 5c095931, awaiting the re-verify of every ornate menu
(user decision: "fix for all menus, we will reverify each one").**

**Defects (measured on the tech-breakthrough shots 20260919, found while double-checking stroke scaling):**
the ornate border's inner green line drew 2/3 px left/right @4K and 1/2 @1600 + 1920 (vanilla 1/1), and a dark rim
(4 px @4K/1600, 1-3 @1920) showed outside the metal where vanilla is transparent.

**One cause:** `band_widths` pins cells 0 and 1 of a corner band to K (stroke + bevel on every PLAIN def). On the ornate
def those cells are TRANSPARENT MARGIN (art = margin 3-4 key | metal 4-5 | green line 1 | key interior), so the margin
collapsed to 2K + remainder and the real stroke fell in the remainder zone; the far band MIRRORS the near widths but the
art is asymmetric (line = cell 7 from the left, cell 8 from the right), so opposite sides rounded differently. The old
law reproduces the measured 1/2, 1/2, 2/3 exactly (asserted in the parity test). The rim = the two-pass ornate backdrop
(`thunk_tutwin_backdrop`: devfill underlay inset only by the stroke width, then metal keyed over it).

**Fix (laws `chrome_band_widths` / `axis_map_chrome` / `ornate_outer_key`; parity tests\test_bandmap_ornate_asm_parity.py):**
- `thunk_bandmap_blit` stays BYTE-IDENTICAL -> no plain frame can move. `thunk_frame_enlarge`'s one E8 to it now hits
  `thunk_bandmap_sel`: corner canvas == 61x44 -> `thunk_bandmap_orn`, else the old blit.
- `thunk_bandmap_orn` = the old blit's OWN SOURCE with asserted string edits (`derive()`): one chrome cell per side
  (x 7/8, y 7/5 — read off the ENGINE's native render, NOT the pcx grid: my 296,711 61x44 crop disagrees by 2 on the
  right/bottom), separate far table, and a post-pass that writes the key wherever the mapped source is key walking
  inward from each dest edge (margin + corner cut-outs; holes inside the metal keep the underlay).
- The file dialog's ornate OUTER goes through the BILINEAR path, not the band map — untouched by this (unmeasured).

**Re-verify list (user):** in-game ornate popups (type 2/6: unit-stack picker, etc.), TutWin tutorial windows, the faction
picker's ornate frame, the tech breakthrough window; rect-level laws written against the old render
(`tutwin_stash_left/right`, `ornate_container_edge`, `popup_art_ornate_x_adjust`, the ornate title inset) may now sit
+-1 px relative to the metal. See [[project-smac-tech-breakthrough]], [[feedback-remainder-distribution]],
[[project-smac-frame9-enlarge]].
