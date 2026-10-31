"""Assemble thunk_pf_union_align v3 + thunk_pf_frame_align v3 -- the popup
BODY-frame <-> TITLE-frame alignment pair.

PORT OF: scaling_laws.py :: body_outer_edge_r/_l, body_inner_edge_r/_l
(the SOURCE OF TRUTH; sweep = test_scaling_laws.py "body/channel/misalignment").

DEFECT (user report 2026-07-10, 4K quit modal + pristine reference): the body
text-box's outer right stroke sat 4px LEFT of the title box's -- vanilla has
them flush (pristine trace: title ring [27,4,696,28], body ring [233,32,696,61],
both R=696). 4 = 1px engine floor-lag (-pad(10)+pad(3)+pad(3) != -pad(4) at
g=40) + 3px unmatched title grow: thunk_box_thick draws the title strokes
delta=(g-16)>>3 OUTSIDE their rect, while the body thickeners draw FLAT since
the 2026-07-09 channel fix removed delta from thunk_box_thick_hollow. The v2.x
aligns were compensations written against the OLD growing hollow ("right =
g_title_right" only landed flush because the draw re-added delta), and v2.2/2.4
skipped art popups entirely (a LEFT-edge problem: full-width span over the
image) -- throwing away the right-edge alignment with it.

THE LAW (drawn edges, both pairs, every g):
    union.r = title.r + delta                   (flat draw lands ON the title's
    union.l = title.l - delta   (no art)         grown stroke)
    d528.r  = title.r - (ps3 - delta)           (one channel pad(3) inside)
    d528.l  = title.l + (ps3 - delta)  (no art)
    ART popups ([popup+0x2144] != 0): keep the engine's art-aware LEFT; only
    the right edge is title-derived. Channel stays pad(3) -- the 2026-07-09
    fix is preserved.

v5 (2026-07-12, user 1024x768 report): the type-1 arm is now SYMMETRIC —
container.r = title_r - ps3 (v4's extra -floor(2g/16) faithfully scaled
vanilla's -2, which is the >1023-regime bug that parks the right stroke at
boxw-9, under the itemlist rows; rows end there too, leaving stroke dashes).
NEW native arm: at g<=16 && type-1 && no-art && ScreenWidth>0x3FF the right
stroke is redrawn at boxw-7 (= the title inner ring = the 800x600 design
clearance) — the one deliberate native-look override in the chrome family
(vanilla-bug fix).  RETIRED in v15 (fix 16): see below.

v6 (2026-07-12, scenario #FACTION channel report): the container arm's gate
widens dlg_type==1 -> {1,2}. Pristine 1024 measure of the type-2 #FACTION
listbox: its ring is collinear with the title INNER stroke on the left
(x=514 == title inner, EXACT) and inner-2 on the right — the SAME container
relation as type-1, NOT the quit-family outer-flush law the v5 fallthrough
applied (drawn ring landed on the title OUTER column, x=12 vs faithful ~19
@4K — the user's "channel too large" between the faction bars and the frame).
The g<=16 native-fix arm stays TYPE-1 ONLY: vanilla type-2 has no
rows-over-stroke collision (rows are indent-inset inside the area) and the
user confirmed 1024 #FACTION is faithful.

v7 (2026-07-16, namebase field-ring report): the container arm's gate widens
{1,2} -> {1,2,4} (`cmp edx,3` after the dec; type 3 does not exist in the
Dialog_set_type switch, so the admitted range is exactly the real types
1/2/4). Pristine 1024 measure of the type-4 base-name field ring
(refs/pristine/NameBase.png): LEFT collinear with the title INNER stroke
(native 268 == inner, EXACT), RIGHT at inner-2 (753 vs 755) — the SAME
relation as type-2, and the same accepted symmetric form ships (both edges
on the inner column; the -2 stays dropped, the type-2 precedent). The v6
fallthrough drew it on the title OUTER column (user 4K shot ...231720:
field 1299/2537 == outer, faithful 1306/2530 == inner). Third instance of
the per-family-arm census lesson — types 1, 2 and 4 all share the
title-INNER container relation; only the quit/type-16 family is outer-flush.
The g<=16 native-fix arm stays TYPE-1 ONLY (vanilla type-4 is faithful at
native — the pristine ref IS the 1024 render). Type-4-with-art keeps the
quit law, as v6 did for type-2-with-art.

v8 (2026-08-01, stack-picker frame report): BOTH thunks gain a POPUP-TYPE
gate right after the concentric check (law popup_frame_rewrite_applies):
raw [esi+0x30ac] = popup_type*10000; only the FLAT (0) and SLIDE (5)
families — the ones every prior law was censused on — take the rewrite.
The ORNATE type-6/2 in-game family (unit-stack picker) lays its frame from
the content-margin sum [popup+0x30f0], which ALREADY scales (trace
2026-07-31: 47@g40 / 29@g25 ~= 19 native x g/16); the quit-law fallthrough
parked the picker frame on the title OUTER column (l = titleL - delta =
7 dev @4K, user shots 204905/222634). Unsigned band test, no division;
type 1000 (hidden sentinel) and future types also pass through. Both
thunks RELOCATED (the gate outgrew both slots): union 0xB000 -> 0xF7A0,
frame 0xA800 -> 0xF8F0.

v9 (2026-08-01b, user rejected the v8-companion title rewrite — "you
shrunk the title box"): the TITLE keeps its engine geometry (title stash
back to stash-only, v3 == v1 semantics) and the UNION thunk instead gains
an ORNATE PICKER arm (law ornate_picker_takes_container_arm): type 6/2 +
live dialog ([0x2350] != -1) + no body box ([0x30d4] == 0) + no art + a
title string ([0xa48] != 0) take the SAME container rewrite as types
1/2/4 — l/r = title stash +- ps3 (itemlist_container_edge_l/r).  Same
final draw site (0x406238) and same title-inner d618 pipeline as the
user-verified type-1/2/4 popups, so the flush optics are identical by
construction; screenshot check: required left shift +7 @g40 / +4 @g25 ==
ps3 exactly.  Ornate popups WITH a body box or art still pass through.
The FRAME (d528) thunk keeps the v8 gate unchanged (pickers have no body
box).  Union RELOCATED again (arm outgrew the slot): 0xF7A0 -> 0xF9F0.

v10 union (2026-08-01f, "the frame stroke on the unit box is not quite
flush with the inner stroke of the title box"): the ornate arm no longer
shares the type-1/2/4 container tail.  The ornate title strokes render
through thunk_box_thick, which draws them frame_grow_delta(g) OUTSIDE
their rect (measured 4K shot 140121: outer 1155 / inner 1162 — ps3 apart,
both grown), while the container frame draws FLAT; the borrowed flat-title
arm therefore landed the frame delta INSIDE the drawn inner (1165/2673 vs
1162/2676, +-3 = +-delta @g40, symmetric).  Ornate edges are now
stash -+ (ps3 - delta) — laws ornate_container_edge_l/r, the same
compensation the quit family carries.  Identity vs v9 for all g < 24.
Types 1/2/4 (flat-drawn titles, user-verified flush) are UNCHANGED.
Union RELOCATED (arm outgrew the 0xF9F0 slot): 0xF9F0 -> 0xFBE0.

v11 union (2026-10-03, "the frame around the text overlaps the frame outside
it", 4K shot 20261003-233707 vs pristine BlindResearch.png): the type-1/2/4
container arm gains the engine's own discriminator, the body text box
[+0x30d4].  With body text the ring is UnionRect(F, D) +- 3 = one pitch
OUTSIDE the d528 text box, on the title OUTER column; the dlg_type-only gate
drew it on the inner column, over the text box.  Body text -> quit law, and
the ring top takes ps3 instead of nestpads' list pad (laws
union_ring_takes_container_arm / union_ring_top).  RELOCATED 0xFBE0 -> 0xC1C0
(the 464-byte slot before thunk_pp_layout is freed).

v12 union (2026-10-04, 1024x768 shot 20261004-005534): the g<=16 native-fix
arm carries the same gate.  It moves the type-1 ring's right stroke from
boxw-9 to boxw-7 because vanilla parks it under the itemlist rows -- true
only for a popup with NO body text.  With body text vanilla's ring is the
UnionRect at boxw-4 (pristine BlindResearch.png x=846), already clear of the
rows; the arm pulled it onto the text box at boxw-7 (x=843).

v13 union (2026-10-04, base-screen RENAME popup, 4K shot 20261004-011133 +
Pause dump: type 60000, margins 47/52, body 50, title stash 32/1717): an
ORNATE 6/2 popup with a live dialog AND a body text box passed through, so
its ring was the engine local = text box -+ nestpads' list pad (35 / 1715
local @g40: 3 / 2 px inside the title outer 32 / 1717, pitch 5).  Vanilla
(1024 shot 20261004-011211, g=16 is the engine's own draw): ring == title
OUTER, text box == title INNER, both sides.  The ornate arm now sends that
shape to the v11 UnionRect code: ring l/r = title stash, top pitch ps3 (law
ornate_union_takes_outer_arm).  Ornate body-only / art / untitled popups
still pass through; the d528 text box itself is untouched.

v15 union (2026-10-18, fix 16; user decision "Hug the list"): a TYPE-1
checkbox list with no body text box and no art (law itemlist_ring_takes_hug_arm)
takes its ring from the engine's own dialog rect D, read from the caller's
frame ([ebp-0x44] l / [ebp-0x3c] r, built at 0x40619D..0x4061AD; the ring site
0x406238 -> thunk_gv_frameskip -> thunk_content_frame -> here keeps ebp):
    l = D.l - ps3,   r = D.r + ps3 - 1     (law itemlist_ring_hug; r: see v17 --
                                            D.r is calc_reserve's width at draw time)
-1 = bandmap_rect_from_halfopen (the band-map ring draws [l, r] inclusive), so
the drawn insets are ps3 on BOTH sides; t/b: v16 below (were the engine local).  The arm sits
before the popup-type gate: vanilla's D path ignores [+0x30ac], so the flat,
slide and ornate families all hug (the ornate picker arm keeps every other
dialog type).  Types 2/4 keep the title-inner container arm.  Was: both edges
on the title inner (8/13 px @4K main menu, 8/11 in game).
The g<=16 NATIVE-FIX arm is REMOVED (g<=16 -> pass): its premise, "vanilla
parks the right stroke under the rows at boxw-9", was our own list-width
override at g=16 (the committed thunk_list_fill_width / its Frida prototype,
ScreenWidth>0x3FF gate: row window 660 instead of vanilla's 657, bars
[10, 670) under stroke col 669; fix 10 re-gated it).  Pristine keeps the bars
2 px clear of the stroke (3/3 in every layout); the arm drew R at boxw-7 = 750
vs vanilla 693 in game at 1024x768.

v16 union (2026-10-18, fix 17; the same user decision on all four sides): the
hug arm's t/b come from D too, [ebp-0x40] t / [ebp-0x38] b (0x4061A7 /
0x4061AD; untouched on the [+0x30d4] == 0 path the arm admits):
    t = D.t - ps3,   b = D.b + ps3 - 1     (law itemlist_ring_hug)
so the drawn insets are ps3 on all four sides (T == B == L == R; vanilla
3/3/3/3 at g = 16).  v15 kept the engine local (D -+ nestpads' scale_px(2)):
D-relative T/B = s(2) / s(2)+1 (5/6 @4K, 2/3 @1600x900 -- T under vanilla's
native 3).  Same 494 B in place (the two local loads became the two D loads).

v17 union (2026-10-22, fix 18; IN-GAME REGRESSION of v15/v16): their premise
"D.r = list x + [+0x5c] IS the row bar" is false at draw time.  D.r at draw
time is calc_reserve's width (the draw precedes the attach): BasePop_exec_3
redraws the popup at 0x602B49 (thunk_popup_edge_anchor -> [vtbl+0x30]
BasePop_on_redraw 0x604AB0 -> [vtbl+0x180] Popup_on_draw_background), and
Dialog_set_type only attaches the list at 0x602BFE, where
thunk_list_fill_width writes [+0x5c] = the list width.  At g > 16 the calc's
[+0x5c] is the measured device text: the ring ended halfway across the rows
(4K Customize Game Rules R 3052 vs the rows' 3798; Governor 2417 vs 2738).
The v15/v16 harness ran the background AFTER the attach slice, so it read the
post-attach value and passed.  The hug uses the list law:
    r = D.l + s(vanilla [+0x5c]) + ps3 - 1     (> 1 row; else D.r + ps3 - 1)
(laws itemlist_ring_list_r / itemlist_ring_hug) via `call t_boxw_t1_term`
-> t_t1_list_w, the arithmetic thunk_list_fill_width v4 itself calls -- the
same law through the same gates (g > 16, > 1 row; the attach's DiploEditWin
owned arm cannot reach a popup ring).  l/t/b unchanged.  527 B in place
(ends 0xC3CF < thunk_rail_wall 0xC3D0).

v9 frame (2026-10-11, ACTION_ITEMS ornate text-box residue; #RENAME 4K shot
20261004-014333: title outer/inner 1078/1085, ring 1078, text box 1086 ->
ring->box pitch 8 left vs 7 right; 1600 shot -014355: 274/278 vs box 279):
the ornate d528 text box was engine-laid at [+0x30f0] - ps3 = fl(19g/16) -
ps3, one floor-lag right of the title inner stash + ps3 (lag 1 at every g in
17..40 except 32).  New ORNATE arm (laws ornate_text_box_takes_inner_arm /
ornate_text_box_edge_l): type 2/6, no art, titled, margin == fl(19g/16) ->
local.l += stash_l + 2*ps3 - margin.  It MUTATES the engine local (no
repoint): the body-only ring (0x4061FA -> nestpads, pad ps3) is built from
the same local and lands on the title OUTER column, vanilla's relation (it
sat 1 px inside it); the v13 UnionRect ring reads the stash, unaffected.
v9b (same day, audit): the arm also stores the moved left in g_d528_left and
keys it with g_d528_popup = esi (cleared at EVERY frame_align entry), and
thunk_pf_textfollow v3 (ASM_TEXTFOLLOW below, now owned here) moves the
body text X to g_d528_left + ps3 for that popup -- the text keeps one ps3
pitch inside the box on the left, like the right side; the draw width is
untouched, so no line break changes.  RELOCATED (outgrew the 176 B slot
against thunk_ol8_selbottom @0xF9A0): 0xF8F0 -> 0x30700, old slot zeros.

title-stash v4 (2026-08-01c, "channels between the title frame's
upper and side edges and the edge of the modal are wrong"): the ornate
6/2 title chain's l/t/r insets are native 13 at every g (+9+3+1 / +9+4)
-> the stash thunk gains an ORNATE INSET arm shifting the engine rect's
l/t/r by ornate_title_inset_delta(g) = s(13)-13 before stashing; the
picker frame (stash + ps3) then lands at ~s(16) = the faithful channel.
Bottom stays engine (its 0x1c is already banding-scaled; the list block
sits right beneath).

SITES. Tail of thunk_content_frame (union, ring draw 0x406238) and tail of
thunk_channel_adjust (d528 draw 0x406154). Entry contract unchanged from v2:
[esp]=ret, [esp+4]=&rect(local), [esp+8]=params, ecx=dest (PRESERVE), esi=popup;
eax/edx scratch. Gates unchanged: g<=16 / faction singleton 0x9403e0 /
[esi+0xa14]!=0 (concentric) -> passthrough. Tails unchanged: union -> push
thunk_d5a0_center (non-faction falls through to thunk_box_thick_hollow, FLAT);
d528 -> push thunk_box_thick_devfill.

RELOCATED (v3 outgrew both old slots): union 0x2020 -> 0xA780, frame 0xF48 ->
0xA800. Old slots are dead space (all references go through placeholders).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

# sentinel imm32 -> patches.yaml placeholder
SENT = {
    0xDEADBE00: "{abs32:g_popup_scale_num}",
    0xDEADBE04: "{abs32:g_title_left}",
    0xDEADBE08: "{abs32:g_title_right}",
    0xDEADBE0C: "{abs32:g_title_bottom}",
    0xDEADBE10: "{abs32:g_pf_union_l}",
    0xDEADBE14: "{abs32:g_pf_union_t}",
    0xDEADBE18: "{abs32:g_pf_union_r}",
    0xDEADBE1C: "{abs32:g_pf_union_b}",
    0xDEADBE20: "{abs32:thunk_d5a0_center}",
    0xDEADBE30: "{abs32:g_pf_align_l}",
    0xDEADBE34: "{abs32:g_pf_align_t}",
    0xDEADBE38: "{abs32:g_pf_align_r}",
    0xDEADBE3C: "{abs32:g_pf_align_b}",
    0xDEADBE40: "{abs32:g_d528_left}",
    0xDEADBE44: "{abs32:thunk_box_thick_devfill}",
    0xDEADBE48: "{abs32:ScreenWidth}",
    0xDEADBE4C: "{abs32:thunk_box_thick_flat}",   # the title draw 2026-09-18..10-24 (now 0xDEADBE5C, t_band_bdraw)
    0xDEADBE50: "{abs32:g_d528_popup}",
    0xDEADBE54: "{abs32:Buffer_write_strings}",
    0xDEADBE58: "{abs32:g_d528_engx}",
    0xDEADBE5C: "{abs32:t_band_bdraw}",          # the title draw since 2026-10-24 W1A: t_band_bdraw (b - 1) -> flat
}

ASM_UNION = r"""
    mov  eax, dword ptr [0xDEADBE00]    /* g_popup_scale_num                     */
    cmp  eax, 0x10
    jle  pass                           /* g <= 16 -> native (v15: the v5-v14    */
                                        /* boxw-7 native-fix arm is gone)        */
    cmp  esi, 0x9403e0                  /* faction-quote singleton               */
    je   pass
    mov  eax, [esi + 0xa14]             /* concentric flag                       */
    test eax, eax
    jne  pass
    /* v15/v16/v17 HUG arm (laws itemlist_ring_takes_hug_arm / itemlist_ring_hug
       / itemlist_ring_list_r; user decision 2026-10-18 "Hug the list"): a
       type-1 checkbox list, no art, no body text box -> the ring is the LIST
       WINDOW -+ ps3 on ALL FOUR sides.  l/t/b from the caller's dialog rect D
       (Popup_on_draw_background builds it at 0x40619D..0x4061AD: [ebp-0x44]
       l = list x, [ebp-0x40] t = the y cursor, [ebp-0x38] b = t + the dialog
       height); r from the list law (v17), NOT [ebp-0x3c] = l + [+0x5c]: the
       draw precedes the attach, so [+0x5c] is calc_reserve's width there.
       The far edges come in by one: the band-map ring draws [l, r] x [t, b]
       INCLUSIVE (bandmap_rect_from_halfopen), so the drawn insets are ps3 on
       every side.  v16 (fix 17): t/b were the engine local (nestpads'
       scale_px(2): D-relative T = s(2), B = s(2) + 1).
       Every popup family: vanilla's D path does not read [+0x30ac].            */
    cmp  dword ptr [esi + 0x2350], 1
    jne  notone
    cmp  dword ptr [esi + 0x2144], 0
    jne  notone
    cmp  dword ptr [esi + 0x30d4], 0
    jne  notone
hug2:
    /* v18 (F34): a FLAT / SLIDE type-2 listbox enters here from the container
       arm (law listbox_ring_takes_hug_arm; its gates -- no art, no body text,
       family 0 / 5 -- are the typeok path's).  Same four-sided hug.          */
    mov  eax, dword ptr [0xDEADBE00]
    lea  edx, [eax + eax*2]
    sar  edx, 4                         /* ps3 = popup_pad(3, g)                 */
    mov  eax, [ebp - 0x40]              /* D.t                                   */
    sub  eax, edx
    mov  dword ptr [0xDEADBE14], eax    /* union.t = D.t - ps3                   */
    mov  eax, [ebp - 0x38]              /* D.b                                   */
    lea  eax, [eax + edx - 1]
    mov  dword ptr [0xDEADBE1C], eax    /* union.b = D.b + ps3 - 1               */
    /* v17 (fix 18): the RIGHT edge hugs the list window thunk_list_fill_width
       WILL give the list.  This draw runs at BasePop_exec_3 0x602B49
       (BasePop_on_redraw -> here), BEFORE Dialog_set_type attaches the list
       at 0x602BFE: D.r = D.l + Dialog[+0x5c] is still calc_reserve's measured
       width (device text at g > 16), not the list (4K Rules: ring R 3052 vs
       the list's 3798).  Same law, same gates as the attach: > 1 row ->
       D.l + s(vanilla [+0x5c]) from t_boxw_t1_term -> t_t1_list_w, the ONE
       owner of that arithmetic; a single row keeps D.r (the attach leaves
       [+0x5c] as measured).  The DiploEditWin owned arm of the attach is
       unreachable here (its parent is never a popup's [+0xa3c]).             */
    mov  eax, [ebp - 0x3c]              /* D.r (single row: as is)               */
    push ebx
    push edx
    /* v18: type 2 keeps D.r -- its calc (BasePop_calc pass 1) wrote [+0x5c] =
       the list width before this draw, and the attach builds the window from
       it (D == the list window at every draw, every g).                       */
    cmp  dword ptr [esi + 0x2350], 1
    jne  keepdr
    mov  edx, [esi + 0x21d0]
    mov  edx, [edx + 8]                 /* iv3                                   */
    cmp  dword ptr [esi + edx + 0x229c], 1   /* Dialog[+0xcc] rows               */
    jle  keepdr
    call T1_TERM                        /* ebx = s(vanilla [+0x5c]) = list w     */
    mov  eax, [ebp - 0x44]
    add  eax, ebx                       /* D.l + list w                          */
keepdr:
    pop  edx
    pop  ebx
    lea  eax, [eax + edx - 1]
    mov  dword ptr [0xDEADBE18], eax    /* union.r = list r + ps3 - 1            */
    mov  eax, [ebp - 0x44]              /* D.l                                   */
    sub  eax, edx                       /* union.l = D.l - ps3                   */
    jmp  storel
notone:
    /* v8 popup-type gate (law popup_frame_rewrite_applies): raw [esi+0x30ac]
       = popup_type*10000. FLAT (0) and SLIDE (5) families take the v2-v7
       rewrite; v9: ornate 6/2 in PICKER shape (live dialog, no body box,
       no art, has title) takes the CONTAINER arm; other ornate popups lay
       their frame from the already-scaled margin sum -> pass through.      */
    mov  eax, [esi + 0x30ac]
    cmp  eax, 10000
    jb   typeok                         /* type 0                                */
    sub  eax, 50000
    cmp  eax, 10000
    jb   typeok                         /* type 5                                */
    /* v9 ornate picker arm (law ornate_picker_takes_container_arm)             */
    add  eax, 30000                     /* eax = raw - 20000                     */
    cmp  eax, 10000
    jb   ornchk                         /* type 2                                */
    sub  eax, 40000                     /* eax = raw - 60000                     */
    cmp  eax, 10000
    jae  pass                           /* not type 6 either -> engine arithmetic*/
ornchk:
    cmp  dword ptr [esi + 0x2350], -1   /* no live dialog -> engine              */
    je   pass
    cmp  dword ptr [esi + 0x2144], 0    /* art sprite -> engine                  */
    jne  pass
    cmp  dword ptr [esi + 0xa48], 0     /* no title = no stash this call -> engine*/
    je   pass
    mov  eax, [esp + 4]                 /* &local rect: t/b kept, l/r container  */
    mov  edx, [eax + 4]
    mov  dword ptr [0xDEADBE14], edx    /* union.t = local.t                     */
    mov  edx, [eax + 0xc]
    mov  dword ptr [0xDEADBE1C], edx    /* union.b = local.b                     */
    /* v13 (law ornate_union_takes_outer_arm): ornate + dialog + BODY text box =
       the engine's UnionRect path -> the ring nests the d528 box on the title
       OUTER column (was: pass, engine local = box -+ the list pad).           */
    cmp  dword ptr [esi + 0x30d4], 0
    jne  unionbody
    /* v10 (2026-08-01f "frame not quite flush with the title inner"): the
       ornate title strokes render GROWN by delta=(g-16)>>3 (thunk_box_thick
       9-slice draws OUTSIDE its rect; measured 4K: outer 1155/inner 1162 =
       ps3 apart, frame flat at stash+ps3 = inner+3 = inner+delta), while
       this container draws FLAT.  Land on the DRAWN inner stroke:
       edges = stash -+ (ps3 - delta) -- laws ornate_container_edge_l/r.
       Types 1/2/4 (flat-drawn titles, user-verified flush) keep +-ps3.   */
    mov  eax, dword ptr [0xDEADBE00]
    lea  edx, [eax + eax*2]
    sar  edx, 4                         /* ps3 = popup_pad(3, g)                 */
    sub  eax, 0x10
    sar  eax, 31                        /* title_grow_delta == 0 (2026-09-18: title draws FLAT); shift 31 keeps the byte layout */
    sub  edx, eax                       /* D = ps3 - delta (>= 0 for g in 17..40)*/
    /* v14 (2026-10-16, SELECT A FACTION): vanilla's list ring R = box_w - margin_r
       + 3, flush with the title inner only when margin_r is the canonical 19;
       subtract the scaled excess (law ornate_picker_container_edge_r).          */
    mov  eax, dword ptr [0xDEADBE00]
    imul eax, eax, 19
    sar  eax, 4                         /* fl(19g/16)                            */
    sub  eax, [esi + 0x30f4]            /* - margin_r (device)                   */
    add  eax, dword ptr [0xDEADBE08]    /* + g_title_right                       */
    sub  eax, edx
    mov  dword ptr [0xDEADBE18], eax    /* union.r = ornate_picker_container_edge_r */
    mov  eax, dword ptr [0xDEADBE04]    /* g_title_left                          */
    add  eax, edx                       /* ornate_container_edge_l               */
    jmp  storel
typeok:
    mov  eax, [esp + 4]                 /* &local rect                           */
    mov  edx, [eax + 4]
    mov  dword ptr [0xDEADBE14], edx    /* union.t = local.t                     */
    mov  edx, [eax + 0xc]
    mov  dword ptr [0xDEADBE1C], edx    /* union.b = local.b                     */
    mov  edx, dword ptr [esi + 0x2350]  /* dlg_type: 1 checkbox / 2 listbox / 4 text-entry */
    dec  edx
    cmp  edx, 3                         /* v7: {1,2,4} take the container arm (3 nonexistent) */
    ja   quitlaw                        /* unsigned: -1/0/16 -> quit law         */
    cmp  dword ptr [esi + 0x2144], 0    /* WITH art -> quit-family law           */
    jne  quitlaw
    /* v11 (law union_ring_takes_container_arm): a body text box ([+0x30d4]) puts
       the ring on the UnionRect path -- it nests the d528 box on the title OUTER
       column (quit law), and its top takes the stroke pitch ps3 instead of the
       list pad scale_px(2) nestpads applied (law union_ring_top).              */
    cmp  dword ptr [esi + 0x30d4], 0
    je   container
unionbody:
    mov  eax, dword ptr [0xDEADBE00]
    lea  edx, [eax + eax*2]
    sar  edx, 4                         /* ps3 = popup_pad(3, g)                 */
    lea  eax, [eax + eax + 7]
    sar  eax, 4                         /* scale_px(2, g)                        */
    sub  edx, eax
    sub  dword ptr [0xDEADBE14], edx    /* union.t = local.t - (ps3 - listpad)   */
    jmp  quitlaw
container:
    /* v18 (F34, law listbox_ring_takes_hug_arm): a type-2 listbox hugs its list
       window like type 1 (vanilla: D -+ 3 on every side, NOT the title inner --
       pristine Go To ring 30 / 755 vs title inner 30 / 757).  Type 4 stays.     */
    cmp  dword ptr [esi + 0x2350], 2
    je   hug2
    /* -- v5 TYPE-1 arm (v9: also the ornate picker): container collinear with   */
    /* the title INNER ring, BOTH edges (the title pair keeps channel == pad(3), */
    /* so derive from the stash + the same arithmetic). v4's extra -floor(2g/16) */
    /* faithfully scaled vanilla's -2, but that -2 is the >1023-regime bug that  */
    /* parks the stroke under the itemlist rows (rows end at boxw-9).            */
    mov  eax, dword ptr [0xDEADBE00]
    lea  edx, [eax + eax*2]
    sar  edx, 4                         /* ps3 = popup_pad(3, g)                 */
    mov  eax, dword ptr [0xDEADBE08]    /* g_title_right                         */
    sub  eax, edx
    mov  dword ptr [0xDEADBE18], eax    /* union.r = itemlist_container_edge_r   */
    mov  eax, dword ptr [0xDEADBE04]    /* g_title_left                          */
    add  eax, edx                       /* itemlist_container_edge_l             */
    jmp  storel
quitlaw:
    mov  edx, dword ptr [0xDEADBE00]
    sub  edx, 0x10
    sar  edx, 31                        /* title_grow_delta == 0 (2026-09-18: title draws FLAT); shift 31 keeps the byte layout */
    mov  eax, dword ptr [0xDEADBE08]    /* g_title_right                         */
    add  eax, edx
    mov  dword ptr [0xDEADBE18], eax    /* union.r = body_outer_edge_r           */
    mov  eax, [esi + 0x2144]            /* art Sprite*                           */
    test eax, eax
    jne  art
    mov  eax, dword ptr [0xDEADBE04]    /* g_title_left                          */
    sub  eax, edx                       /* body_outer_edge_l                     */
    jmp  storel
art:
    mov  eax, [esp + 4]
    mov  eax, [eax]                     /* art: keep the art-aware local left    */
storel:
    mov  dword ptr [0xDEADBE10], eax    /* union.l                               */
    mov  dword ptr [esp + 4], 0xDEADBE10
pass:
    push 0xDEADBE20                     /* thunk_d5a0_center                     */
    ret
"""

# v17: the hug arm calls t_boxw_t1_term (its VA is the box assembler's; the yaml carries it as {rel32:}), so the
# union is assembled at its real slot VA.  v18 (F34) outgrew the 0xC1C0..0xC3D0 slot (thunk_rail_wall) by 17 B:
# RELOCATED to pcave2 0x35000 (wave-2 W2B region 0x35000..0x35FFF); the old slot is dead space (zeros).
from assemble_scale_boxw import HELPER_VA as T1_TERM_VA   # noqa: E402  t_boxw_t1_term (pcave2 0xA294)
UNION_VA = 0x00A0C000 + 0x35000
UNION_SLOT_END = 0x00A0C000 + 0x35300                      # the W2B region holds t_title_hmargin2 at 0x35300
ASM_UNION = ASM_UNION.replace("T1_TERM", f"{T1_TERM_VA:#x}")
CALLS = {T1_TERM_VA: "t_boxw_t1_term"}

ASM_FRAME = r"""
    mov  dword ptr [0xDEADBE50], 0      /* g_d528_popup: no ornate text key yet  */
    mov  eax, dword ptr [0xDEADBE00]    /* g_popup_scale_num                     */
    cmp  eax, 0x10
    jle  pass
    cmp  esi, 0x9403e0
    je   pass
    mov  eax, [esi + 0xa14]
    test eax, eax
    jne  pass
    /* v8 popup-type gate -- same as the union (law popup_frame_rewrite_applies) */
    mov  eax, [esi + 0x30ac]
    cmp  eax, 10000
    jb   typeok
    sub  eax, 50000
    cmp  eax, 10000
    jb   typeok
    /* v9 ORNATE arm (law ornate_text_box_takes_inner_arm / ornate_text_box_edge_l):
       type 2/6 + no art + a title this call + the canonical margin fl(19g/16)
       -> the engine LOCAL left gets its margin term swapped for the title
       anchor: l += stash_l + 2*ps3 - [+0x30f0].  The local itself is moved
       (not a scratch repoint) so the engine's body-only ring, nested ps3
       around this same local, follows onto the title OUTER column.          */
    add  eax, 30000                     /* eax = raw - 20000                     */
    cmp  eax, 10000
    jb   ornchk                         /* type 2                                */
    sub  eax, 40000                     /* eax = raw - 60000                     */
    cmp  eax, 10000
    jae  pass                           /* not ornate either -> engine           */
ornchk:
    cmp  dword ptr [esi + 0x2144], 0    /* art -> engine (art-aware left)        */
    jne  pass
    cmp  dword ptr [esi + 0xa48], 0     /* no title = stale stash -> engine      */
    je   pass
    mov  eax, dword ptr [0xDEADBE00]    /* g                                     */
    imul edx, eax, 19
    sar  edx, 4                         /* fl(19g/16) = the canonical margin     */
    cmp  edx, [esi + 0x30f0]
    jne  pass                           /* other margin -> engine arithmetic     */
    lea  edx, [eax + eax*2]
    sar  edx, 4                         /* ps3                                   */
    add  edx, edx                       /* 2*ps3                                 */
    add  edx, dword ptr [0xDEADBE04]    /* + g_title_left                        */
    sub  edx, [esi + 0x30f0]            /* - margin                              */
    mov  eax, [esp + 4]                 /* &local_38                             */
    push edx                            /* the shift                             */
    mov  edx, dword ptr [0xDEADBE00]
    lea  edx, [edx + edx*2]
    sar  edx, 4                         /* ps3                                   */
    add  edx, [eax]                     /* engine text X = engine box l + ps3    */
    mov  dword ptr [0xDEADBE58], edx    /* g_d528_engx: the text X this key fits */
    pop  edx
    add  [eax], edx                     /* local.l = ornate_text_box_edge_l      */
    mov  edx, [eax]
    mov  dword ptr [0xDEADBE40], edx    /* g_d528_left: the body text follows    */
    mov  dword ptr [0xDEADBE50], esi    /* g_d528_popup = this popup (text key)  */
    jmp  pass
typeok:
    mov  eax, [esp + 4]                 /* &local_38                             */
    mov  edx, [eax + 4]
    mov  dword ptr [0xDEADBE34], edx    /* align.t = local.t                     */
    mov  edx, [eax + 0xc]
    mov  dword ptr [0xDEADBE3C], edx    /* align.b = local.b                     */
    mov  eax, dword ptr [0xDEADBE00]
    lea  edx, [eax + eax*2]
    sar  edx, 4                         /* ps3 = popup_pad(3, g)                 */
    sub  eax, 0x10
    sar  eax, 31                        /* title_grow_delta == 0 (2026-09-18: title draws FLAT); shift 31 keeps the byte layout */
    sub  edx, eax                       /* D2 = ps3 - delta (>= 0 for g in 17..40)*/
    mov  eax, dword ptr [0xDEADBE08]    /* g_title_right                         */
    sub  eax, edx
    mov  dword ptr [0xDEADBE38], eax    /* align.r = body_inner_edge_r           */
    mov  eax, [esi + 0x2144]
    test eax, eax
    jne  art
    mov  eax, dword ptr [0xDEADBE04]    /* g_title_left                          */
    add  eax, edx                       /* body_inner_edge_l                     */
    jmp  storel
art:
    mov  eax, [esp + 4]
    mov  eax, [eax]                     /* art: keep the art-aware local left    */
storel:
    mov  dword ptr [0xDEADBE30], eax    /* align.l                               */
    mov  dword ptr [0xDEADBE40], eax    /* g_d528_left (textfollow gates art out)*/
    mov  dword ptr [esp + 4], 0xDEADBE30
pass:
    push 0xDEADBE44                     /* thunk_box_thick_devfill               */
    ret
"""


# thunk_pf_textfollow v3 (2026-10-11; v1/v2 lived in assemble_council.py, which now lists it OWNED_ELSEWHERE):
# thunk_faction_textmargin's tail at the BODY-TEXT Buffer_write_strings (0x604DF5).  [esp]=ret, [esp+4]=str,
# [esp+8]=X, [esp+0xc]=Y, [esp+0x10]=width; ecx=dest (preserve), esi=popup; eax/edx scratch.
# v2 semantics for flat/slide (law popup_textfollow_applies): X = g_d528_left + ps3.  v3 ORNATE arm (law
# ornate_textfollow_applies): type 2/6 and g_d528_popup == esi (set ONLY by frame_align v9's ornate arm, cleared
# at every frame_align entry) AND the engine X == g_d528_engx (the engine text X that arm saw: a later popup at the
# same heap address that drew no d528 keeps its own engine X) -> the same X = g_d528_left + ps3, i.e. the text moves with the text box by the
# same 1 px.  WIDTH is NOT touched: the draw wraps at the same width as before (and as the measure), so every
# line break is unchanged -- the right wrap limit moves left with the text.
ASM_TEXTFOLLOW = r"""
    cmp  esi, 0x9403e0                  /* faction-quote singleton               */
    je   tail
    mov  eax, [esi + 0xa14]             /* anchored / ext window                 */
    test eax, eax
    jne  tail
    mov  eax, [esi + 0x2144]            /* art popup: art-aware X                */
    test eax, eax
    jne  tail
    mov  eax, [esi + 0x30ac]
    cmp  eax, 10000
    jb   ok                             /* type 0                                */
    sub  eax, 50000
    cmp  eax, 10000
    jb   ok                             /* type 5                                */
    add  eax, 30000                     /* raw - 20000                           */
    cmp  eax, 10000
    jb   orn                            /* type 2                                */
    sub  eax, 40000                     /* raw - 60000                           */
    cmp  eax, 10000
    jae  tail
orn:
    cmp  dword ptr [0xDEADBE50], esi    /* frame_align v9 moved THIS popup's box */
    jne  tail
    mov  eax, dword ptr [0xDEADBE58]    /* ...and for THIS engine text X: a later */
    cmp  eax, [esp + 8]                 /* popup at the same address that skipped */
    jne  tail                           /* frame_align keeps the engine X         */
ok:
    mov  eax, dword ptr [0xDEADBE00]
    cmp  eax, 0x10
    jle  tail
    lea  edx, [eax + eax*2]
    sar  edx, 4                         /* ps3                                   */
    mov  eax, dword ptr [0xDEADBE40]    /* g_d528_left                           */
    add  eax, edx
    mov  dword ptr [esp + 8], eax       /* X = g_d528_left + ps3                 */
tail:
    push 0xDEADBE54                     /* Buffer_write_strings                  */
    ret
"""


ASM_TITLE = r"""
    /* v4 = v3 stash-only + the ORNATE INSET arm (law ornate_title_inset_delta;
       user 2026-08-01c "channels between the title frame's upper and side
       edges and the edge of the modal are wrong"): vanilla insets the 6/2
       title box 13 native px from the window edge on l/t/r (+9+3+1 sides,
       +9+4 top; pristine sides 12.1 / top ~14, frame 16) but those chain
       constants stay native at g>16 -> shift the engine rect's l/t/r by
       s(13)-13.  BOTTOM stays engine (banding already scales its 0x1c; the
       list block sits right beneath -- s(37) would cross the ring top).
       The v2 rewrite (REVERTED) derived the box from frame quantities and
       SHRUNK it; this arm is a pure uniform inset scale.                  */
    mov  eax, dword ptr [0xDEADBE00]    /* g_popup_scale_num                     */
    cmp  eax, 0x10
    jle  tail
    cmp  esi, 0x9403e0                  /* faction-quote singleton               */
    je   tail
    mov  edx, [esi + 0x30ac]
    sub  edx, 20000
    cmp  edx, 10000
    jb   arm                            /* type 2                                */
    sub  edx, 40000
    cmp  edx, 10000
    jae  stash                          /* not type 6 either -> stash only       */
arm:
    /* v7 (2026-08-23c, law ornate_title_rect): the band lands at s(13) /
       s(37) popup-local WHATEVER the engine top.  v4-v6 added s(13)-13 to a
       rect top assumed native-13, but the engine chain at g>16 is 9+ps3+3
       (15 @g25, 19 @g40) -> band 2/6px low (4K probe: 38..98 vs 32..92; the
       field channel + "text crowding" were this).  b' = s(37) (v5 wrote
       t_engine + s(37) - 13 = the same value only when t_engine == 13).    */
    imul edx, eax, 37
    sar  edx, 4                         /* b' = fl(37g/16)                       */
    mov  eax, [esp + 4]                 /* &rect                                 */
    mov  [eax + 12], edx
    mov  eax, dword ptr [0xDEADBE00]    /* reload g                              */
    imul eax, eax, 13
    sar  eax, 4                         /* s(13)                                 */
    mov  edx, [esp + 4]
    sub  eax, [edx + 4]                 /* delta = s(13) - t_engine (0 at g=16)  */
    add  [edx], eax                     /* l += delta                            */
    add  [edx + 4], eax                 /* t  = s(13)                            */
    inc  eax                            /* v9 (fix 26 v2, ORNATE_HALF_OPEN): the
                                           inclusive-drawn R stroke on vanilla's
                                           half-open axis W-1-s(13)              */
    sub  [edx + 8], eax                 /* r -= delta + 1                        */
stash:
    mov  eax, [esp + 4]
    mov  edx, [eax]
    mov  dword ptr [0xDEADBE04], edx    /* g_title_left                          */
    mov  edx, [eax + 8]
    mov  dword ptr [0xDEADBE08], edx    /* g_title_right                         */
    /* v6 (2026-08-23 council_scale): stash the POST-arm bottom too.  The
       fieldpads band-anchored arm anchored on thunk_band_stash's PRE-arm
       bottom (g_band_bottom), which the ornate bottom arm above moves
       afterwards -> stale by fl(37g/16)-13-s(0x1c) (zero channel @g25,
       1px @g40).  Law popup_field_top reads this one.                      */
    mov  edx, [eax + 12]
    mov  dword ptr [0xDEADBE0C], edx    /* g_title_bottom                        */
tail:
    push 0xDEADBE5C                     /* t_band_bdraw -> thunk_box_thick_flat  */
    ret
"""


def template(asm: str, va: int = 0) -> tuple:
    """(blob, yaml byte template): abs32 sentinels -> {abs32:}, a call to a CALLS helper -> E8 {rel32:}."""
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(asm, addr=va)
    blob = bytes(code)

    out, i = [], 0
    while i < len(blob):
        if blob[i] == 0xE8 and i + 5 <= len(blob):
            tgt = (va + i + 5 + int.from_bytes(blob[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in CALLS:
                out.append("E8 {rel32:%s}" % CALLS[tgt])
                i += 5
                continue
        for sent, ph in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(ph)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    return blob, " ".join(out)


def _emit(name: str, asm: str, va: int = 0) -> None:
    blob, tmpl = template(asm, va)
    print(f"{name}  {len(blob)} bytes")
    print()
    print('        bytes: "' + tmpl + '"')
    print()


def main() -> int:
    blob, _t = template(ASM_UNION, UNION_VA)
    assert UNION_VA + len(blob) <= UNION_SLOT_END, "v18 overruns its slot 0x35000..0x35300"
    _emit("thunk_pf_union_align v18", ASM_UNION, UNION_VA)
    _emit("thunk_pf_frame_align v9", ASM_FRAME)
    _emit("thunk_pf_textfollow v3", ASM_TEXTFOLLOW)
    _emit("thunk_pf_title_stash v9", ASM_TITLE)

    # sanity: the asm arithmetic, evaluated the way the bytes evaluate it
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import (
        body_inner_edge_l, body_inner_edge_r,
        body_outer_edge_l, body_outer_edge_r,
        itemlist_container_edge_l, itemlist_container_edge_r,
        itemlist_ring_hug, title_grow_delta,
    )

    T_L, T_R = 65, 1932            # a real 4K title-band stash
    for g in range(17, 41):
        delta = title_grow_delta(g)
        ps3 = (3 * g) >> 4
        assert T_R + delta == body_outer_edge_r(T_R, g), g
        assert T_L - delta == body_outer_edge_l(T_L, g), g
        assert T_R - (ps3 - delta) == body_inner_edge_r(T_R, g), g
        assert T_L + (ps3 - delta) == body_inner_edge_l(T_L, g), g
        assert ps3 - delta >= 0, g
        # v5 type-1 arm arithmetic (symmetric: both edges on the inner ring)
        assert T_L + ps3 == itemlist_container_edge_l(T_L, g), g
        assert T_R - ps3 == itemlist_container_edge_r(T_R, g), g
        # v10 ornate arm arithmetic: edges = stash -+ (ps3 - delta)
        from scaling_laws import ornate_container_edge_l, ornate_container_edge_r
        assert T_L + (ps3 - delta) == ornate_container_edge_l(T_L, g), g
        assert T_R - (ps3 - delta) == ornate_container_edge_r(T_R, g), g
        # v14 ornate picker right edge: + fl(19g/16) - margin_r (signed)
        from scaling_laws import ornate_picker_container_edge_r
        for mr in (0, (19 * g) >> 4, (21 * g) >> 4, 200):
            assert ((g * 19) >> 4) - mr + T_R - (ps3 - delta) == ornate_picker_container_edge_r(T_R, mr, g), (g, mr)
    # v8 gate arithmetic == the law, evaluated the way the bytes evaluate it
    # (unsigned: raw<10000, or (raw-50000) as u32 < 10000)
    from scaling_laws import popup_frame_rewrite_applies
    for raw in (0, 9999, 10000, 20000, 49999, 50000, 59999, 60000, 10000000):
        asm_take = raw < 10000 or ((raw - 50000) & 0xFFFFFFFF) < 10000
        assert asm_take == popup_frame_rewrite_applies(raw), raw
    # v9 ornate-band arithmetic == the law's type band, evaluated the way the
    # bytes do (eax carries raw-50000 when the band test starts)
    from scaling_laws import ornate_picker_takes_container_arm
    for raw in (0, 9999, 10000, 19999, 20000, 29999, 30000, 49999, 50000,
                59999, 60000, 69999, 70000, 10000000):
        if raw < 10000 or ((raw - 50000) & 0xFFFFFFFF) < 10000:
            continue                       # 0/5 took typeok before the band test
        asm_orn = (((raw - 20000) & 0xFFFFFFFF) < 10000
                   or ((raw - 60000) & 0xFFFFFFFF) < 10000)
        assert asm_orn == ornate_picker_takes_container_arm(raw, 8, 0, 0, 1), raw
    # the non-type gates mirror the law's remaining args
    assert not ornate_picker_takes_container_arm(60000, -1, 0, 0, 1)
    assert not ornate_picker_takes_container_arm(60000, 8, 120, 0, 1)
    assert not ornate_picker_takes_container_arm(60000, 8, 0, 0x12345, 1)
    assert not ornate_picker_takes_container_arm(60000, 8, 0, 0, 0)
    assert ornate_picker_takes_container_arm(20000, 2, 0, 0, 1)
    # title-stash v4 inset arm == the law, evaluated the way the bytes do
    from scaling_laws import ornate_title_inset_delta, popup_pad
    assert ornate_title_inset_delta(16) == 0                 # native identity
    for g in range(17, 41):
        assert ((13 * g) >> 4) - 13 == ornate_title_inset_delta(g), g
        # the v9 frame then sits at ~ the faithful s(16) channel (<=1 floor lag)
        frame_ch = 13 + ornate_title_inset_delta(g) + popup_pad(3, g)
        assert 0 <= ((16 * g) >> 4) - frame_ch <= 1, g
    assert ornate_title_inset_delta(40) == 19                # 4K: 13 -> 32
    # v5 bottom law: faithful outer height s(37)-s(13) restored; identity at 16
    from scaling_laws import ornate_title_outer_bottom
    assert ornate_title_outer_bottom(13, 16) == 37           # native identity
    for g in range(17, 41):
        b = ornate_title_outer_bottom(13, g)                 # win-rel, t_engine=13
        t = 13 + ornate_title_inset_delta(g)
        assert b - t == ((37 * g) >> 4) - ((13 * g) >> 4), g # outer h = s(37)-s(13)
        # the scaled title ink (find_font 12 -> ~s(29..30)) fits the inner slot
        assert (b - popup_pad(3, g) * 2) - (t + popup_pad(3, g) * 2) >= (30 * g) // 40, g
    assert ornate_title_outer_bottom(13, 40) == 92           # 4K: room to ring@107
    # v7 arm == law ornate_title_rect on the ENGINE top (9+ps3+3 at g>16): s(13)/s(37)
    from scaling_laws import ornate_title_engine_top, ornate_title_rect, popup_scale_floor
    assert ornate_title_engine_top(16) == 13 and ornate_title_engine_top(25) == 15 and ornate_title_engine_top(40) == 19
    for g in range(16, 41):
        t = ornate_title_engine_top(g)
        rect = ornate_title_rect(t, t, 1000 - t, g)
        if g == 16:
            assert rect == (13, 13, 987, 37)
        else:
            assert rect == (popup_scale_floor(13, g), popup_scale_floor(13, g), 999 - popup_scale_floor(13, g), popup_scale_floor(37, g)), g
    assert ornate_title_rect(19, 19, 1722, 40) == (32, 32, 1708, 92)     # 4K probe 2026-08-23c (was 38,38,1703,98); v9: R on the half-open axis
    # the type-2/4 container law at g=16 == the native title-inner ring
    assert itemlist_container_edge_l(4, 16) == 7
    assert itemlist_container_edge_r(675, 16) == 672
    # v16 hug arm, evaluated the way the bytes do: l/t = D.l/D.t - ps3, r/b = D.r/D.b + ps3 - 1 (g > 16);
    # g = 16 is the engine's own ring (pristine 1024: bars [10, 667) -> ring [7, 670), D -+ 3 on every side)
    assert itemlist_ring_hug(10, 52, 667, 448, 16) == (7, 49, 670, 451)
    for g in range(17, 41):
        ps3 = (3 * g) >> 4
        for dl, dt, dr, db in ((25, 95, 1667, 887), (82, 117, 1724, 909), (13, 52, 916, 484), (47, 117, 1689, 909)):
            l, t, r, b = itemlist_ring_hug(dl, dt, dr, db, g)
            assert (l, t, r, b) == (dl - ps3, dt - ps3, dr + ps3 - 1, db + ps3 - 1), g
            assert dl - l == r + 1 - dr == dt - t == b + 1 - db == ps3, g   # drawn insets equal (inclusive footprint)
    # v9 frame ornate arm == law ornate_text_box_edge_l, evaluated the way the bytes do
    from scaling_laws import ornate_text_box_edge_l, ornate_text_box_takes_inner_arm
    for g in range(17, 41):
        m = (19 * g) >> 4
        stash = (13 * g) >> 4
        local = m - ((3 * g) >> 4)                       # engine: margin - ps3 (no other addends)
        asm_l = local + (stash + 2 * ((3 * g) >> 4) - m)
        assert asm_l == ornate_text_box_edge_l(local, m, stash, g) == body_inner_edge_l(stash, g), g
        assert ornate_text_box_takes_inner_arm(60000, 0, 1, m, g)
        assert not ornate_text_box_takes_inner_arm(60000, 0, 1, m + 1, g)
    print("asm arithmetic == scaling_laws body-edge laws for every g in [17,40]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
