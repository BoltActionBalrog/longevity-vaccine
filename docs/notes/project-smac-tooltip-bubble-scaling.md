---
name: project-smac-tooltip-bubble-scaling
description: SMAC mouseover tooltip ("bubble") font + border scaling — DONE build 0b81d7a8 (user-confirmed in-game); global font lever + 2-thunk solid-border inset
type: project
---

Mouseover tooltips in SMAC (e.g. the Faction-Select preview-box hover labels "The Original SMAC Factions" /
"The New Factions" / "Mix Old and New Factions") are the engine's **"bubble"** feature. They were unscaled
(tiny native ~12px font + fixed 1px border) at high res. **DONE build 0b81d7a8** (2026-06-28, user-confirmed
in-game @4K + non-4K, CHANGELOG'd, MD5-locked). (15d4583b = font-only step; 604f12f9 = border v1 with the gap bug.)

KEY: every bubble in the whole game renders through ONE global font ptr `g_bubble_font` @ **0x9B7A54**.
`config_popups` (0x588AA0) set it to `find_font(0xc,0)` (~12px Arial) regardless of resolution = the bug.
- Tooltip text is attached to controls via `BaseButton_set_bubble_text` (0x607550) — faction preview boxes
  id 0x100/0x101/0x102 in `FactionPickWin_build` use labels.txt strings 0x116c/0x1170/0x1174 (the strings live
  in **labels.txt**, NOT a binary literal — can't xref them in the exe).
- `Win_set_bubble_text` (0x5F83D0) computes the bubble BOX from the font: margin = Font_width(font, @0x696E00)*2,
  line height from font[3]/[4]+[0], centred over the anchor rect + clamped to ScreenWidth. Rect → `g_bubble_rect`
  (0x9B6E38 {l,t,r,b}), text → `g_bubble_text` (0x9B7A50).
- `overlay_compositor` (0x5EFD20, was FUN_005efd20) paints it each frame: Buffer_box_2 border (color @0x696D30)
  + 1px inset + Buffer_fill_3 + Buffer_set_font(g_bubble_font) + Buffer_write_cent_l_7.

So the WHOLE bubble (box geometry + text) derives from `g_bubble_font` → scaling that one ptr scales everything.

FIX = group `popup_bubble_font_scaling`, one site: `config_popups.bubble_font` @0x588F42 (was `MOV [0x9b7a54],ECX`,
6 bytes) → `CALL thunk_bubble_font; NOP`. `thunk_bubble_font` (menu_strip_thunks+0xD40, 34B): pushad; ensure
scale; EAX=popup_scale(12)=12*g/16; find_font(EAX,0); store → g_bubble_font; popad; ret. g≤16 → find_font(12,0) =
byte-identical no-op. Stack-neutral (the later bulk `ADD ESP,0x2c` that cleans config_popups' pending find_font
args stays correct). font_size_table {40,36,32,24,22,20,18,16,14,12,10,8}: g40→30→nearest 32, g25→18, g22→16.

GOTCHA: do NOT mutate the size-12 Font object (`DAT_009403dc = find_font(0xc,0)`) — it's shared with other UI;
only the bubble PTR is repointed. `config_popups` is the SOLE writer of g_bubble_font (1 caller, system_init), and
its Font_init loop populates font_object_table before this site, so find_font is valid.

BORDER (group `popup_bubble_frame_scaling`, build 0b81d7a8): `overlay_compositor` (0x5EFD20) draws the frame as
Buffer_box_2 (a 1px OUTLINE — 2 Buffer_hline_2 + 2 Buffer_vline_2, NOT a fill — confirmed by decompiling 0x5E3203)
→ inset 1px → Buffer_fill_3 interior, with the fill flush against the outline = a **1px ring**. KEY GOTCHA that bit
me: I first assumed box_2 *fills* (terranx.h even said so — WRONG) and built v1 (604f12f9) that just inset Buffer_fill_3
by N. That left box_2's 1px outline at the outer edge but pulled the fill N-1 px inward → a **1px transparent
background gap** at the top edge (user caught it @4K). The earlier Frida trace (idx-255 single row/col) could NOT
distinguish outline-vs-fill (a mid-edge scan looks identical either way) — the in-game gap was the discriminator.
v2 FIX (the live one): `thunk_bubble_inset_fill` (menu_strip_thunks+0xD70, site `overlay_compositor.bubble_inset_fill`
@0x5EFD68) replaces the interleaved inset-by-1 + the fill_3 call: (1) `Buffer_fill_3(0x9B7490, outer rect 0x9B6E38,
border color [0x696D30])` — fill OUTER SOLID with border color (covers box_2's outline + the would-be gap); (2) inset
all 4 edges by **N=max(1,popup_scale(1))=floor(g/16)**; (3) `Buffer_fill_3(.., 0x9B6E38, fill color [0x9B7A64])` —
fill interior. = solid N-px border, no gap. `thunk_bubble_restore` (+0xDD0, site @0x5EFEA1) undoes the inset by the
SAME N (else g_bubble_rect shrinks every frame). Border grows **INWARD** (the fills stay within the stored outer
rect) so the stored rect still bounds the box = clean clear, no ghosting. GOTCHA: the restore block has an interleaved
`TEST EDI,EDI` feeding a later `JZ` — the thunk preserves EDI and the site replays `TEST EDI,EDI` after the CALL.
fill_3 is callee-clean (RET 8). N: 1px native/g≤16, 1px @1600(g25)/1920(g22), 2px @4K(g40) — modest but faithful
(floor); at N=1 the two fills are pixel-identical to the native outline+fill. See (a private note).
