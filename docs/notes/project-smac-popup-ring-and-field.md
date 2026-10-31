---
name: project-smac-popup-ring-and-field
description: Popup min-height is the WINDOW (box M - D), body ring column depends on body text not dialog type (UnionRect path = title OUTER, incl. ornate base-screen popups), type-4 text-entry field width scaled at attach — exe 54a505ec, user-verified 2026-10-04
type: project
---

**CLOSED 2026-10-04, exe 54a505ec (carries two other lines of work too), user-verified by screenshots at 1024 / 1600 / 1920 / 4K.** Four fixes that started from "Confirm Research Priorities runs far below its OK button":

1. **The tall empty body under OK and the bottom frame hidden behind the HUD are VANILLA** (pristine `refs\pristine\BlindResearch.png`): min box height 300, bottom-anchored on the console strip, box bottom ~10 native behind the HUD silhouette. Ours was only D too tall — see [[project-smac-namebase-popup]] item 6 (law `ingame_popup_min_boxh` v3, thunk at pcave2 0x3B0).

2. **Which column the body ring sits on is decided by BODY TEXT, not dialog type** (engine 0x4060E7..0x406238, law `union_ring_takes_container_arm`):
   - no body text (`[+0x30d4]==0`) + dialog → ring = dialog ±3 = title INNER column (Customize Game Rules, scenario #FACTION, #FIRSTBASE — the three popups the old type-{1,2,4} gate was measured on);
   - body text + dialog + no art → ring = UnionRect(text box, dialog) ±3 = title OUTER column, one pitch outside the d528 text box (#TECHRANDOM, #RENAME);
   - body text only / art → OUTER (quit family).
   `thunk_pf_union_align` v11–v13 (pcave2 0xC1C0, src `assemble_pf_align.py`): type-1/2/4 with body text → quit law + ring top pitch ps3 (`union_ring_top`: nestpads gives that path the list pad scale_px(2), 5 vs 7 @4K); the g≤16 native-fix arm takes the same no-body-text gate (it had pulled the ring's right stroke onto the text box at 1024); ORNATE 6/2 + live dialog + body text (base-screen popups) no longer passes through (`ornate_union_takes_outer_arm`).

3. **Type-4 text-entry field width** (group `popup_type4_field_width`, thunks `thunk_t4_winw`/`thunk_t4_colw` at pcave2 0xFBE0/0xFC20, src `assemble_type4_width.py`): the dialog is max(native #xs `[+0x2c]`, device-measured content) wide, so the EditLine's black field kept its native pixel width at every g. Scaled IN REGISTER at the three attach reads (0x611B84, 0x611C95, 0x611CF5); `[+0x2c]` stays native (shared with box width / wrap budget). Fixed-width (anchored) dialogs pass through.

**Why:** each was "looks roughly right at 4K" and wrong by a few px against `vanilla × g/16`; the ring one because a gate keyed on a proxy (dialog type) that happened to hold for the popups it was measured on.

**How to apply:**
- A popup chrome gate must be the ENGINE's own discriminator (read the branch at the draw site), not a property that correlated in the samples.
- The `uimod_debug.flag` Pause dump gave type 60000 for the base-screen rename popup in one keypress — my guess (`[+0xa14]` anchored) was wrong. Ask for the dump before theorising about which gate skips a popup.
- KNOWN, left alone: every ornate popup's text box L is 1 px right of the title inner (`[+0x30f0]`−ps3 vs stash+ps3) because `thunk_pf_frame_align` passes ornate through. A popup whose scaled box lands in [M−D, M) is up to D−1 taller than vanilla × g/16 (ESC quit confirm at 4K unseen). `assemble_pf_align.py`'s built-in self-check asserts a stale title_grow_delta (fails at g=24 at HEAD); the Unicorn parity test is the real check.
- NOT exercised: a text entry inside the diplomacy talk (anchored → engine path), a multi-field type-4 popup, a type-2 list popup with body text.
- The raw `terranx.exe` (desktop `Pristine.lnk`) corrupts LIVE game state on every save on Win11 24H2 (legacy header branch copies the garbage header over 0x9A6490); scenario-editor undo saves trigger it per edit. Use `run-pristine-*.bat` (terranx_pristine.exe) for references.

Related: [[project-smac-popup-chrome]], [[project-smac-untitled-popup]], [[feedback-copied-gate-needs-own-rationale]], [[feedback-proportionate-scaling]].
