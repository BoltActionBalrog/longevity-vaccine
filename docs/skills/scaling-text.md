---
name: scaling-text
description: Use when scaling up UI text in the SMACX patcher (any popup/dialog/button/title/row font enlarged via popup_scale), when installing or retargeting ANY font thunk (find_font / Font_init), or when a scaled label overflows / ellipsises.
---

# Scaling text in the SMACX UI

When a font is enlarged (popup_scale, ~2.5× @4K), **vertically-centred** text sits visibly
**too low**. This is not a layout bug — the text is geometrically centred. The engine's
centred writers centre on the font's **line-box** (ascent+descent), but the visible glyph
**ink** (caps, no descenders) rides high in that box. The offset scales linearly with font
size: ~1px native (invisible), ~3px at 2.5× (visible). Correct it with a small upward nudge.

## When it applies — and when it does NOT

The bias exists only when the writer centres on the **line-box**. Some writers centre on the
**tight glyph height** they measure themselves — those are already ink-centred and need NO nudge.
So **identify the centring source first, and always test before committing.**

- **Needs the nudge:** text centred on the **line-box** in a fixed slot with a **scaled** font.
- **Already ink-centred — do NOT nudge:** writers that centre on the font's **cap box**.
  - `Buffer_write_cent_l_7` centres Font+0x10 (tmAscent - tmInternalLeading) and draws TA_BASELINE at its bottom:
    for vanilla's face (Arial bold) the cap ink lands within +-1 px of vanilla x g/16 at every g with NO nudge
    (popup title, 2026-10-18 fix 14 -- the old `(g-16)>>3` lift was calibrated to the Arial Narrow g_pf0 title).
- **Already ink-centred — do NOT nudge:** writers/callers that measure the tight glyph bbox.
  - e.g. FlatButton labels: `FlatButton_content_draw` measures its own text height and centres on
    it, so nudging made the text sit too **high** (tested, reverted). Counter-example, not a case.
- **Immune (anchored, not centred):** top/left/**baseline**-anchored text — list rows, wrapped
  body paragraphs. Position comes from a baseline or line-pitch, not slot-centring.

## Fix pattern

`call_target_redirect` the centred-text draw (or its preceding `Buffer_set_font`) to a cave
thunk that **subtracts `N=(g-16)/8`** from the vertical coordinate, then tail-jmps the real
function (`push <fn>; ret`) with the stack frame intact.

- `N=(g-16)/8` ≈ 3px @4K, **0 at g≤16** (lo-res no-op) — it tracks the border grow Δ.
- Adjust whichever the writer consumes: a RECT's top+bottom (re-centred by the writer), or a
  pre-computed centred-Y arg on the stack — subtract `N` directly.
- Tune via the shift: `sar ,3` (/8, ~3px) → `sar ,2` (/4, ~7px) for more.

**Do NOT bake the offset into the font itself** — that would also shift every top/left-anchored
field (rows, body) that is currently correct. The bias is real only at centred-writer call
sites, so the correct granularity is one per-call-site thunk. There are very few.

## Worked examples (this repo)

- **Title (RETIRED 2026-10-18, fix 14)** — `thunk_title_textnudge` @ redirect `0x4060aa` subtracted
  `N` from text rect `[ebp-0x10]`/`[ebp-8]` for the Arial Narrow `g_pf0` title. The title now keeps
  vanilla's font (`0x7CFE8C`, law-scaled by thunk_hud_font) and the writer's cap-box centring is
  already within +-1 px of vanilla x g/16 (GDI-measured, g 17..40): N = 0, site status skip (group
  `popup_title_font_retired`). Measure before you nudge.
- **Buttons (did NOT need it)** — `thunk_btntext_nudge` @ `0x608441` (`Buffer_wrap_cent_4`).
  Built it, but FlatButton already ink-centres → text sat too high → reverted (group
  `popup_button_textnudge` left `status: skip`). The lesson above.

# Face and weight: the font law (2026-09-17 audit — 17 sites had regressed; do not re-regress)

**Rule: a scaled font keeps the face and weight vanilla gives it at the NATIVE size. Only the
pixel size changes.** Brief: `work\FONT_FACE_WEIGHT_AUDIT.md`. Laws: `scaling_laws.font_face_law`,
`font_direct_law`, `font_scaled_size`, `find_font_snap`. Helpers: group `font_face_law`
(`work\scripts\assemble_fontlaw.py`, pcave2 0x2E000..). Parity: `tests\test_fontlaw_asm_parity.py`.

## Why the pool lies about scaled sizes

`find_font(size, variant)` (config_popups 0x588BB0) chooses FACE and WEIGHT from the size it is
asked for: **> 12 px → "Arial Narrow" bold** (variant 2 = bold-italic), **≤ 12 px → "Arial" with
weight = variant**. It also snaps to the table {40,36,32,24,22,20,18,16,14,12,10,8} (ties → larger)
and clamps at 40. So `find_font(fl(12·g/16), 0)` — the obvious port of a vanilla `find_font(12, 0)`
— returns Arial Narrow **bold** at any g > 16. That single mistake was the whole audit: tooltips,
HQ report rows, COMMLINK rows, PrefWin text and the MP-lobby body font all went bold+narrow.

## How to install a scaled font (the only three shapes)

1. **Vanilla calls `find_font(S, v)`** → call **`t_ffn(S, v)`** with the NATIVE S and v (cdecl,
   drop-in). It returns the pool font while `S > 12` and `fl(S·g/16) ≤ 40`, else a keyed cave
   Font slot `Font_init`'d with the native face/style at `fl(S·g/16)`. Never hand it a scaled S.
   Private slot with its own num: `t_ffn_at` / `t_ffn_num`.
2. **Vanilla calls `Font_init(font; name, S, style)` directly** → keep `name` and `style`, scale
   only S: `Font_init(font; name, fl(S·g/16), style)`. For the shared Arial-14-bold button label
   family (`0x6E84B4`) use **`t_fdirect_a14b`**; for another direct family `t_fdirect_at(slot,
   S, style, num)`. Do not route a direct-init font through the pool: the pool would re-face it.
3. **Vanilla reuses a Font object** (`[0x9B8DA8]` trio, scratch fonts) → reuse the scaled twin
   that was built from the same native trio; never build a "comfortable" size.

Facts you will otherwise re-probe: the default FlatButton label Font `0x7D3948` is created as
TNR 12 and re-inited **Arial 12 regular** at startup; PrefWin buttons and the HUD M/I buttons use
`0x6E84B4` / `0x7CFE8C` = **Arial 14 bold**; `[0x9B8E34]` is NULL. Variants 0 and 1 are the same
face above 12 px, so a v0↔v1 swap there is not a regression; below 12 px it is.

## Measure with the face the game has

**GDI emulation of any game font: `AddFontResourceExA(<game dir>\arialn.ttf, FR_PRIVATE)` and NOTHING else from the
Arial Narrow family.** The game registers only `arialn.ttf`, so in-game "Arial Narrow bold" (pool fonts > 12 px,
g_pf*, list rows) is GDI's SYNTHETIC bold of the regular face, ~9% wider than `arialnb.ttf`; with no Narrow loaded
Windows silently falls back to Arial. Check `GetTextFaceA` == "Arial Narrow" before trusting a width.
[[feedback-game-font-synthetic-bold]]

## Verify at a NON-4K resolution

Face flips happen at the 12-px boundary and the 40-px clamp, both reached at different g. A 4K
shot proves the size; a 1600×1200 (g=25) or 1920×1080 (g=22) shot proves the face. Measure stem
width against the vanilla shot, do not eyeball "looks bold" (two earlier passes were fooled).

# Zero-slack labels: fit at runtime, never a fixed size

`FlatButton_content_draw` ellipsises when `Buffer_text_width(label) > (R−L) − 6` (0x6083C6).
Vanilla's SE model buttons have ZERO slack ("THOUGHT CONTROL" 140 px in a 140 px budget), and GDI's
advance rounding is not linear in size (Arial bold 14→140, 19→195, 21→208, 35→349), so **no
`fl(S·g/16)` survives at every g** (19 px → 195 vs a 194 px budget at 1920). The faithful law is
the engine's own base-name idiom (`scaling_laws.se_label_fit`, thunk `t_se_labelfit`): after the
buttons are built, measure each label with **the painter's own measure on the button canvas**
(`Buffer_text_width`, font +0x52C == +0x970 — not `Font_width`), step the label Font down until
every label fits, then **repaint the measured buttons** (vtbl+0xF8, what the build does after
each `BaseButton_init`). Face/weight stay native.

# Where to hook: a builder can be MODAL

`SocialWin_build`'s tail is `push MainWin / push pop_wait / push 0 / call [vtbl+0xE4]` =
`Win_set_modal`: it returns only when the screen CLOSES. A fit placed "after the build call" runs
after the user has left (two wasted builds + a broken hotkey from the after-close repaint). Before
hooking after any `X_build`, disassemble its tail; a `call [vtbl+0xE4]` / `pop_wait` push means
hook **that call site** (`FF 90 E4 00 00 00` → `E8 thunk 90`, ecx = window, args intact, tail
`mov eax,[ecx]; jmp [eax+0xE4]`). Memory: [[feedback-modal-builder-hook-before-set-modal]].
