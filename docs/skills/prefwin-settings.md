---
name: prefwin-settings
description: Use when adding a setting, tab, or widget to the SMACX Preferences window (PrefWin), or when editing/polishing the Longevity Mod Preferences page before release.
---

# Adding settings to the SMACX Preferences window

The "Longevity Mod Preferences" tab (verified 2026-07-12, exe 3e5aba89) is the template for
every mod setting we add. The working reference implementation is
`src\uimod\src\prefs.cpp` — its 40-line header comment is the mechanism writeup; read it
alongside this skill. The feature is a **two-half design**:

1. **exe half (baked, patches.yaml + `work\scripts\assemble_prefwin.py`)** — the prefwin
   scaling machinery (GraphicWin_init entry gate, FlatButton/ScrollBar zoom stubs, slider
   internals gate), the **DLL widget registry** cave slots, and any per-setting cave
   global the game code must read (e.g. `g_map_font_pct` @0xA1712C read by
   `thunk_map_font`).
2. **DLL half (`src\uimod\src\prefs.cpp`)** — builds the widgets with the ENGINE's own
   classes at PrefWin build time, wraps four PrefWin vtable slots for behavior, and
   persists to `[UIMod]` in `Alpha Centauri.ini`.

Most new settings only touch the DLL half. You need the exe half only for a **new cave
global** the game reads, or a **second slider** (see Limits below).

## PrefWin ground truth (all confirmed, also in `work\symbols\terranx.h`)

| What | Where |
|---|---|
| PrefWin object (static) | 0x8578D8 · vtable 0x66D424 |
| PrefWin_build | 0x48D840; sole caller desktop_init call site 0x58EED5 -- but desktop_init runs AGAIN on a game load (0x51BC14/0x51AD08): PrefWin is re-inited, every child (ours too) torn down, the tab group reset. `BuildWidgets` re-inits ours on every build (ctors/vtables/hooks once) |
| current tab id | PrefWin+0xA14 (set by group-sel vtbl+0xB8 before command vtbl+0xB0) |
| tab ButtonGroup | 0x8577F0 · ButtonGroup_add 0x62B850 |
| vtable slots we wrap | +0x30 refresh · +0x64 on_key · +0xB0 command · +0xC4 slider_changed |
| FlatButton | ctor 0x607CF0 · BaseButton_init 0x607210 (text,id,x,y,w,h,parent,0) · size 0xB4C · font ptr +0x970 · forced draw state +0xAB8 · id +0xA78 |
| ScrollBar | ctor 0x6051D0 · init 0x6058D0 (x,y,w,parent,id) · set_range 0x6059B0 · set_pos 0x605D20 · value +0xA2C · size 0x214C |
| layout statics (NATIVE units) | tab x/y0/w 0x85788C/90/94, h 0x686B88; label x/y0/w/h 0x8578B4/BC/0x686B8C/90; slider x/y0/w 0x8578CC/D0/0x8578B8; bottom shift 0x872CA8; audio frame rect 0x8577D8/DC/E0/E4 |
| slider-area frame | `thunk_pref_boxframe` @0xA16D00, Buffer_box_sprite contract: (buf=PrefWin+0x444, rect NATIVE, params 0x78D690) — it scales ×g/16 itself |
| DLL widget registry (cave) | g_dll_pref_lo/hi/slider @0xA17120/24/28 — zero = self-disabled |
| widget id space | 0..6 tabs, 0x50..0x5E stock controls, **ours: 0x5F tab, 0x60 slider, 0x61 label, 0x62 checkbox row, 0x63 AI-cloak row, 0x64 cargo row, 0x65 alert-icon row, 0x66/0x67/0x68 display-mode cells (Fullscreen/Borderless/Windowed, one line), 0x69/0x6A "Drag Hold Time" label/slider, 0x6B RETIRED (Shift+Click Instant Move, removed 2026-10-07; never reuse), 0x6C/0x6D update row + Subscribe button, 0x6E "Add Scanlines", 0x6F RETIRED (Brighten Scanlines, removed 2026-10-30; never reuse), 0x70/0x71 user portraits + HD pack, 0x72/0x73 "Modern Control Set" + "Right-Click Drags to Move", 0x74/0x75 the map-drag cells, 0x76/0x77 "Left Click Keeps the View" + "Closing a Base Keeps the View", 0x78 "Constrain Mouse to Window", 0x79 "Air Drops Divert Around Unseen Defenders" → next free 0x7A** (every id is a `kXxxId = 0x..` constant in prefs.cpp; `test_airdrop_divert.py::test_prefs_widget_ids_are_unique` fails on a collision -- the 2026-10-30 one came from this ledger omitting 0x78) |
| option-row budget | 15 rows (k = 0..14, the display-mode row INCLUDED) above the slider frame at 1024+; `kOptRow0 = 1` (no blank row); the slider block sits `kSliderBlockDy` (44 native) lower than the stock layout and its frame is two rows (`kSliderFrameH` 48 native) -- the stock 'More' button belongs to the two-page stock tabs only and is never on our tab; the `!! OVERLAPS THE FRAME` log is the guard (it fires at ScreenWidth 800, where the frame moves up 50 native -- an unsupported baseline, accepted) |
| disabling a widget | the engine has NO disabled state: grey = ScrollBar/FlatButton colour+sprite fields set around the draw (prefs.cpp SetHoldSliderEnabled), inert = our private-vtable +0x50/+0xA4/+0xB0 early-outs, tooltip = Win_set_bubble_text from a +0x44 override (never the +0x98&0x200000 input gate: it blocks mouse-move too) |

## Recipe A — add a control to the existing Longevity page (the common case)

All in `src\uimod\src\prefs.cpp`:

1. **Pick the next free id** (0x78+) and add a `kXxxId` constant.
2. **Add storage to `struct Widgets`** (FlatButton 0xC00 padded, ScrollBar 0x2200 padded).
   The registry lo/hi covers `sizeof(g_w)`, so growing the struct auto-extends zoom
   coverage for FlatButtons — no exe change.
3. **Construct it in `BuildWidgets()`** with the engine ctor/init shims (the
   `__fastcall(self, edx_dummy, ...)` thiscall idiom), parented to PrefWin, using
   **NATIVE-unit coordinates read from the engine layout statics** — never hardcode
   scaled pixels; the baked GraphicWin_init entry gate scales children of PrefWin at the
   construction boundary. Then `WinHide` it (the refresh wrapper owns visibility).
4. **Show/hide in `WrapRefresh`** under the existing `OurTabActive()` branch, and
   `WinRedraw` it after the frame draw.
5. **Behavior**: value changes arrive in `WrapCommand` (button ids) or `WrapSlider`
   (slider ids). Follow the volume-slider semantics: **live-apply on change, persist only
   on OK (id 0x5C) / Enter (key 0xD in `WrapOnKey`); ESC/Cancel = session-only; Restore
   Defaults (id 0x5A) resets to the mod default** and `set_pos`'s the widget. A single slider
   chevron click notifies vtbl+0xC0 (`WrapScrolled`), not +0xC4 — route new slider ids there too.
   **Value readout** = the engine's own tooltip, not a label: `Win_set_bubble_text` 0x5F83D0
   (owner, persistent text buffer, SCREEN anchor rect) / `Win_clear_bubble_text` 0x5F8500 — it sizes,
   places (centred over the anchor, bottom on its top, x clamped), erases and repaints itself, and the
   patcher already scales its font/border. Our sliders share a private ScrollBar vtable hooking +0x50
   press / +0x54 release / +0xB0 chevron (`SliderBubbleUpdate` in prefs.cpp); "held" =
   g_pressed_win_l ∈ {slider, +0xAAC, +0x15F8}. Unverified in-game at writing.
6. **Persistence**: clone the `LoadPct`/`SavePct` pattern — one `[UIMod]` key per setting
   in `Alpha Centauri.ini` (`GetPrivateProfileIntA`/`WritePrivateProfileStringA`).
7. **Static text label**: make it a FlatButton, pin `+0xAB8 = 0` (content_draw honors the
   forced state BEFORE hover/pressed resolve → never reacts), and swallow its id at the
   top of `WrapCommand`.

## Recipe A2 — a stock-looking option row (checkbox + label), the traced law

The option rows (`prefs.cpp` `CheckContentDraw` / `RowLabelY`; the law was verified exact at 4K/1600/1920 on
2026-09-13 on the then "Large F4 Base Indicators" row, since 2026-10-11 an ini-only setting -- the row made way
for "Constrain Mouse to Window" under the display-mode cells) are the template for any on/off setting:

- **Widget**: a FlatButton with a **PRIVATE vtable copy** (the whole 0x180-byte FlatButton table — a
  0x168 copy hard-crashed the save load) whose +0x30 content_draw is ours: clear the canvas to the
  transparency key, `Sprite_draw_2` the engine's CheckList box sprite (0x779504 off / 0x779530 on, 18 px)
  at (0,0) with num/den = g/16, then `Buffer_write_l_3` the label. The engine's own press/release →
  `WrapCommand(id)` toggles it; a PrefWin on_lclick wrap does NOT receive the click.
- **Font**: the stock rows draw with the popups' scaled body font `scratch0_font` (pcave2+0x810; cell law
  `(20g)>>4` → Arial Narrow bold nominal 26@g25 / 23@g22 / 41@g40) — read that Font object, never
  re-derive by size (find_font snaps to a table and misses 25).
- **Label placement = the engine's CheckList painter, traced (hook_chkrow_observer):** the stock rows
  (`CheckList_draw_item` 0x60F030) draw the box at `rowTop + ((max(rowH,lineH) − 18)>>1) + ((16−g)>>1)`
  and the label through **`Buffer_wrap_2`** (NOT the rect writer) whose first line starts at the rect
  top = `rowTop + windowFont.descent` with no cap-height centring. So with our box at y=0:
  `ty = descW − boxDy`, `descW = [[PrefWin+0x913C+0x1C+0x970]+0x1C]` (the Map page CheckList's window
  font, == its Buffer font), `rowH = [PrefWin+0x913C+0xA34+0x68]`, read LIVE at every draw (6/5/5 at
  4K/1600/1920). Label x = `(23g)>>4`. Both writers end in the same `Buffer_write_multi_font_raw_l`, so
  no writer-specific offset exists. A model that centred cap height in the rect was 4/2/2 px low.
- **Persist** like the slider: one `[UIMod]` ini key, live-apply on toggle, saved with OK, Restore Defaults
  resets. If game code must read it, reserve a cave dword in assemble_prefwin.py's tail block (the F4 ring:
  `g_big_f4` @0xA17170, read by `t_rwk_blink`, loaded from the ini-only `[UIMod] BigF4Indicators`).
- **A child row** (nested one `kChkSubIndent` in) that means nothing while its parent state is off reads
  dimmed (`dim` in `CheckContentDraw`) and `WrapCommand` ignores its clicks -- e.g. "Constrain Mouse to
  Window" outside Fullscreen (`VidModeFullscreenRunning()`); repaint it when the parent state changes.

## Recipe B — a second tab

- Tab rows pitch 0x16 native; ours sits at y0+0x84 (the blank row under Map Preferences)
  and the DLL moved Gamma Correction from y0+0x9A to y0+0xB0 (imm patch @0x48DD03).
  Another tab means finding it a row: move Gamma again (edit `gammaNew`) or place beside.
- Build the FlatButton with a new tab id, `ButtonGroup_add` it to 0x8577F0.
- The engine's page show/hide switches (0x48FFB0/0x490140) have **no case for unknown
  ids → they show NOTHING**: your refresh-wrapper branch on `[PrefWin+0xA14] == yourId`
  is the entire page mechanism. Keep per-page widget sets disjoint and hide the other
  page's set in the same branch.
- Keyboard up/down tab cycling skips DLL tabs (engine switch, accepted limitation).

## Gotchas that already bit us (do not re-learn)

- **PrefWin is rebuilt on a game load.** A widget built "once" is torn down (flags +0x9C = 0, Win_show no-op) by the second PrefWin_build and never comes back -- the whole Longevity page vanished (2026-09-26). New widgets: construct under `first`, init on EVERY `BuildWidgets` call.

- **Shared-DLL gate**: uimod.dll loads into the PRISTINE exe too. Anything touching cave
  VAs must stay behind `Pcave2Present()` or the pristine game AVs at desktop_init. After
  ANY change, run BOTH exes and check both uimod.log lines
  ([[feedback-uimod-shared-dll-gate]]).
- **find_font pointer identity**: `find_font(size,variant)` (0x5882F0, cdecl) returns a
  pointer into a STATIC font table — same args → same pointer whose CONTENT is
  re-initialized later. Pointer change-detects never fire. `WrapRefresh` therefore
  unconditionally syncs our font slots from stock button 0 (0x858338+0x970) and
  `WinRedraw`s the tab every refresh. Keep new text widgets inside that sync.
- **Build-time font**: widgets composite once before the first refresh; set the scaled
  font (`find_font((14*g)>>4, 1)` at g>16) in `BuildWidgets` too, or they render native
  until the first redraw.
- **Byte-checked patches only**: every in-place code patch verifies expected bytes first
  and logs + aborts the whole feature on mismatch (GOG update safety). Keep that
  discipline for new patch sites.
- **Registry slots first**: `BuildWidgets` fills g_dll_pref_lo/hi/slider BEFORE any
  ctor/init call, so construction already rides the baked gates.

## Limits requiring the exe half (assemble_prefwin.py + patches.yaml rebake)

- **A second ScrollBar** -- DLL-only way (the "Drag Hold Time" slider, unverified in-game at
  writing): give it a PRIVATE copy of the ScrollBar vtable (0x669D58, 0x170 B) whose +0x30 draw
  sets `g_dll_pref_slider` = self around the original slot and restores it; point the slot at it
  around its ctor/init too (gwinit slkid). Rows go at the audio page's pitch 0x16. The exe way:
  `g_dll_pref_slider` is a SINGLE slot consumed by the sbzoom
  stub and the gwinit slider-internals gate. Either widen it to a lo/hi range in
  `asm_gwinit`/`asm_sbzoom` or add a slot — then rebake (`assemble_prefwin.py`, update
  cave bytes + `patched_md5` in patches.yaml, `run-apply-patches.bat --restore` then
  `--apply`, fix `test_apply_md5.py` expectations).
- **A new cave global read by game code** (the `g_map_font_pct` pattern): reserve it in
  the tail block (layout constants in assemble_prefwin.py; free space runs to
  CAVE_LIMIT 0xB800), have the DLL write it, thunk reads it. State the law in
  `work\scripts\scaling_laws.py` first and add an emulation parity test
  (`work\tests\test_mapfont_asm_parity.py` is the template).
- **A widget class we haven't mapped** (e.g. the stock checkbox class): pull its
  ctor/init from the PrefWin_build (0x48D840) decompile, record symbols in terranx.h,
  and check zoom coverage — the baked zoom stubs repoint only the FlatButton and
  ScrollBar vtables; a new class needs its own scaling audit.

## Build · deploy · verify

```
src\uimod\build.bat                    (Release Win32; MSBuild from VS2022)
copy src\uimod\build\Release\uimod.dll "<GAME_DIR>\uimod.dll"
cd work\tests && py -m pytest -q       (if the exe half changed)
```

Verify at 4K + 1920×1080 (or 1600×1200) + 1024×768 (native no-op: g≤16), on BOTH exes
(uimod.log: "prefs tab hook installed"+"Longevity tab built" on PRACX; "Longevity tab
disabled" on pristine). Walk every tab to/from ours (no residue), and OK / ESC /
Restore Defaults / restart-persistence for each new setting.
