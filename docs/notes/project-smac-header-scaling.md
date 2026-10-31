---
name: project-smac-header-scaling
description: SMAC popup title/header scaling plan — grow the box to preserve ratios, not steal gaps; box must expand repeatedly per header element
type: project
---

Active workstream (started 2026-06-04): make the popup TITLE/header bar scale proportionally at 4K. Currently the title zone is a fixed ~28px sliver with a tiny NON-scaled font (`0x7cfe8c`), out of proportion with the 2.5x-scaled rows (see [[project-smac-modal-scaling]]).

**Core principle (user directive): grow the BOX to preserve the ratios between ALL elements — never steal an existing gap.** The earlier "push the title down into the 7px panel gap + clamp" approach was rejected because that gap (title→content) and the content→button margins all need to scale too.

Levers (per `BasePop_calculate_dimensions` 0x603800 + `Popup_on_draw_background` 0x405c80, fields are byte offsets):
- `[0x30e8]` (= `param_1[0xc3a]`, sourced from style `[0x21b8]`) is the **header vertical reservation**. It feeds BOTH `content_top = [0x30e8]+[0x30e0]` (draw) AND `box_h` (`[0x30c0]`, += `[0x30ec]+[0x30e8]`). Scaling it pushes content down AND grows the box — one lever.
- Title-box DRAW height = hardcoded `0x1c`=28 at 0x40602e (`LEA ECX,[EAX+0x1a]`); scale to match the reserve.
- Title FONT = `PUSH 0x7cfe8c` at 0x40609d; replace with scaled `g_pf*`.
- Side margins: scale uniformly in [[project-smac-modal-scaling]]'s `thunk_title_margin` (drop the top-margin clamp once content is pushed down).

**SUPERSEDED:** an earlier note claimed the right edge was pinned at clamp `ScreenWidth-0x16E` so we must grow leftward. WRONG — that clamp is on `[0x21fc]` (text column width), not the box position; and the box auto-nudges (see below). The grow-left / 2*Δmargin scheme is NOT needed.

**Confirmed runtime values (Frida, Customize Game Rules @ 3840x2160, g_popup_scale_num=40):** `[0x21b8]`=`[0x30e8]`=38 (=0x26, the titled header reserve set in `Popup_calculate_dimensions` 0x404b10: 0x26 titled / 0x12 untitled), `[0x30e0]`pad_x=0, `[0x30e4]`pad_y=10, `[0x30ec]`=18, box_w=1424, box_h=1068. content_top=38.

**ANCHOR/GROWTH ALGORITHM — CONFIRMED by test (2026-06-05): the popup auto-nudges to stay fully on-screen when grown, so we CAN grow the box freely.** The popup sits at the screen's BOTTOM-RIGHT corner (it's a small 1424px buffer pinned bottom-right on the full 3840x2160 screen, NOT centered, NOT scaled-up — earlier confusion). The box GraphicWin is created in `BasePop_exec_3` at the `GraphicWin_init` call 0x60287c with x=0,y=0 + flags; `Win_init` does the placement and clamps to screen bounds. Test (grew box_w & box_h +500 at the GraphicWin_init loads): the window expanded UP and LEFT and nudged inward so it stayed fully visible (small margin appeared at the bottom-right). => no manual repositioning needed; grow box_w/box_h and the engine keeps it on-screen. Horizontal grow-left / 2*Δmargin math is therefore UNNECESSARY — just grow symmetrically/however and let the clamp re-place it.

**COORDINATION HAZARD: 0x602861 (the box_h load before GraphicWin_init) is ALREADY patched by group `popup_box_grow` (`thunk_grow_box`, cave 0x800).** Don't add a second patch there — the header box-grow must extend/modify thunk_grow_box or scale `[0x30e8]` upstream in calc_dims instead. (A test site briefly collided here; removed.)

**Current state (2026-06-05): the `popup_title_box_margin` group is DISABLED (site `Popup_on_draw_background.title_margin` status=skip).** The margin-only thunk_title_margin (sides + clamped top) is built but unused; it ALSO vanished the title text. To be reworked into the full grow-the-box approach below.

**REMAINING LEVERS for the rework:** (1) scale `[0x30e8]` in calc_dims → content down + box grows (engine re-places); (2) scale title DRAW height `0x1c` at 0x40602e; (3) scale title FONT `0x7cfe8c` at 0x40609d → `g_pf*`; (4) re-enable thunk_title_margin scaling all 4 margins uniformly (no clamp). Verify title text survives each step (screenshot).

**CAVEAT TO REMEMBER: the box will need to be expanded again each time we scale another header element** (title height, title font, any header art/sub-widgets). Each scaled element adds extent the box must grow to contain. Treat box-grow as an ongoing per-element step, not a one-time patch.
