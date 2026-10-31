// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// SOCIAL ENGINEERING scaling prototype v1.
// Mechanism (work\_se_patch_plan.md): SocialWin_build 0x4B2740 is build+MODAL EXEC
// (returns only on close), so the transform chokepoint is SocialWin_model_reset
// 0x4AECE0 — called after tables/window/backdrop, BEFORE the 35 BaseButton_init
// calls, which consume the tables ⇒ buttons are born scaled, zero pokes.
// Window+backdrop scale via 7 builder imm32 literals; painter insets via 72 more
// one-time Memory.patchCode sites. Laws via globalThis.SL (scaling_laws.js prelude).
// Pass-1 accepted leftovers (flagged in plan): native-size sprite icons & lock-widget
// art, native-thickness frame strokes, native-density slider tile pattern (tiled,
// never resampled — device-density regeneration is pass 2).
// v2 (work\_se_patch_plan_v2.md): + first-repaint repair pass at SocialWin_repaint
// 0x4B19A0 — (a) canvas repair: FlatButton canvases compose scaled-W x NATIVE-20-H
// (engine h-adjust; root cause moot) -> GraphicWin_resize(w,h,skip=1) per button from
// the scaled tables, font quad +0x52C..+0x538 snapshot/restored; (b) sprite-struct
// enlarge: NN centre-map the pixel planes x g/16 and rewrite data/pitch/blit/canvas
// fields — every draw anchor (digit bottom-anchor, centered icons, arrow-button art)
// reads sprite fields, so all self-correct. Band "digits" are SPRITES, not text.
// v3: face-rect repair replaces the v2 canvas resize (buffers were always right;
// the native-20 face was the button's +0x474 local/clip rect + the +0x4C4/+0x4C8
// copies — poked to the button's OWN buffer dims, no creation-order mapping);
// bogus mask notes removed (0x2C-stride sprites have no +0x30 field); per-button
// observe dump on first repair for ground truth.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_se_proto.log";
// v4: 4K pixel-measure shows the face crops at EXACTLY native 20 rows while 13C/474/
// 4C4/4C8/buffer all read 50 — prime suspect = client rect +0x14C (labeled-window
// h-adjust). v4 dumps it (all 35 this time), auto-stretches a same-w/short-h client
// rect to buffer h, and one-shots a canvas pixel-column run-length at the label draw
// to discriminate composite-crop vs short-draw.
// v5 armed the FlatButton zoom bracket (g_faction_active) — faces now fill their
// windows with device-density stripes (v5 run-length: strict 1-row 174/238 over all
// 50 rows = the baked dither family, not a zoom). v6: the v5 run proved label text
// and row icons draw AFTER the bar in DEVICE space -> F1 re-scaled, the 3 label-draw
// patches restored, rowH pin dropped; society state icons enlarged on FIRST DRAW
// keyed by the live sprite ptr at 0x4B1878 (no array-layout guessing); sd2 call-site
// observers log dims + x/y at the 4 icon sites to settle band/spartans placement.
// v7 — icons weren't gone, they were UNDER the full-height buttons: the y-anchors
// subtract sprite CANVAS h (+0x1C), proven exactly by the v6 log (digit y 164->145 =
// -(32-13); icons 120->71). Per-array canvas policy: icons keep canvas NATIVE
// (anchor stays at the vanilla line, art grows into the row), digits/arrows keep it
// scaled (their anchors track it correctly). Society rows draw from the SAME icon
// array (the "society state array" was a phantom) — ptr-keyed enlarge kept as dedupe.
// Relaxed pitch sanity (blit-w>pitch digit variants pad with the sprite's key).
// v9 — v8 proved: icon draws continue every paint but land no pixels when blit >
// canvas (v7's native-canvas policy = engine void-draw); v6's scaled-canvas icons
// rendered, just anchored high. So: canvas SCALED everywhere + per-site Y rewrites
// (band icons bottom-aligned to the row's digit line; spartans canvas-delta shift;
// society absolute-centered in the row button). Sprite enlarge moved BEFORE button
// creation (model_reset transform) so the arrow chevron buttons copy ENLARGED art.
// v10 — ROOT CAUSE of the v9 regressions: the five "metrics" are ALIASES of sprite
// struct fields (+0x2E30/+0x2E34 = icon#0 canvas w/h @0x2E18+0x18/+0x1C;
// +0x2C70 = digit#4 blit-w @0x2C60+0x10; +0x3DA8/+0x3DAC = lock#0 canvas w/h
// @0x3D90+0x18/+0x1C — the lock art IS 24x14). The engine derives layout FROM art
// dims; the metric loop + enlargeInventory each scaled the same fields = double
// (rowH 26->65->162, lock canvas 24->60->150 = the giant indented bars, digit#4
// blit 7->17 = strip garble) — on the FIRST open, no reopen needed. So:
//   (a) metric loop DELETED — the sprite enlarge alone sets those fields once;
//   (b) sd2 Y rewrites DELETED — with canvas+blit cleanly scaled the engine's own
//       canvas-h anchor math is vanilla x g/16 by construction (observers log-only);
//   (c) arrows +0x3DE8 NOT enlarged — chevrons take the PROVEN gate route instead:
//       thunk_btn_gate_pre hook HITs the 6 SE arrow FlatButton statics (the
//       label-less state-sprite class: GOVERNOR chevrons/unit-row arrows precedent)
//       so the shrink/2D-zoom pipeline scales their faces;
//   (d) same hook MISSes MENU 0x7B1804 / COMMLINK 0x7B2350 (faces already
//       device-scaled by thunk_hudmenu_sd2; the armed bracket was re-enlarging
//       them = the HUD banding — the exact Council-button class) + gate census log;
//   (e) sprites restored to their saved native structs on SE close (no persistent
//       engine-state mutation; every open starts pristine).
// v11 — v10 run: layout fully correct (all five alias dwords single-scaled) and
// sd2 args sane, but the end-of-paint strip row is flat interior = the enlarged-
// sprite draws land ZERO pixels (true of every prior variant too; v6's "rendered"
// was never pixel-verified). The one invariant all void states share: a blit-sized
// plane with pitch=s(blitW) under a larger declared canvas. Native sprites keep
// pitch == canvas w with a canvas-dimensioned plane (arrow dump: pitch 20 ==
// canvas 20). v11 restores that invariant — plane = s(cw) x s(ch), key-filled,
// enlarged ink at top-left, pitch = s(cw) — and instruments the sd2 sites with
// dest ptr/dims/clip + a post-call pixel probe of the dest row, so a still-void
// result names its mechanism (clip rect vs engine early-out vs wrong dest).
// v12 — v11 run: dest/clip PERFECT (dest = SocialWin canvas 0x8a66b4, clip wide
// open) and STILL void ⇒ Sprite_draw_2 does not read the plane as raw pitch*rows;
// it decodes a structured/compressed format (the vanilla +/- digit draws 17 wide
// from a pitch-7 13-canvas plane — impossible raw; the LOCK art from our raw plane
// RENDERED via its non-sd2 blitter; the v9 chevrons drew our raw planes as garble
// via theirs). A raw NN-enlarged plane decodes as an immediate terminator = void.
// So: STOP hand-feeding sd2. v12 = the in-tree sd2-ratio law ((1,1)->(g,16),
// precedents thunk_checkbox_scale / thunk_bw_sd2 basewin_sprite_ratio /
// thunk_nw_toggle / thunk_sb_thumb): sd2-fed sprites (digits+icons) keep data/
// pitch/blit NATIVE and only canvas w/h scale (pure layout metadata = the rowH/
// iconGap/sldInset aliases the layout needs; anchors then vanilla x g/16 by the
// canvas-h law); the 5 sd2 call sites (now + hover 0x4B16A1) rewrite num/den to
// (g,16). Locks keep the v11 plane-enlarge (their blitter reads raw planes —
// user-verified rendering). MENU/COMMLINK gate MISS now CONDITIONAL on the armed
// bracket (v11 regression: unconditional MISS killed their normal zoom-composed
// backgrounds pre-SE). Mid-paint deferred pixel probe replaces the v11 onLeave
// probe (Interceptor onLeave at a mid-function CALL site never fires).
// v13 — v12 run: ratio applied (n/d=40/16 logged per draw), dest correct, STILL
// flat at BOTH probe rows (native- and scaled-height) ⇒ neither draw form lands.
// The working precedent (thunk_checkbox_scale: same fn, same (g,16) rewrite,
// renders) differs from our draws in exactly one way: untouched sprite structs.
// Suspect: the scaled CANVAS w/h fields void the sd2 draw. v13 = discrimination
// matrix at the band-digit/band-icon sites — first 4 draws per site cycle:
//   A canvas SCALED + ratio g/16  (v12 baseline, expect void)
//   B canvas NATIVE + ratio g/16  (checkbox config, expect scaled render)
//   C canvas NATIVE + ratio 1/1   (pure vanilla control, expect native render)
//   D canvas SCALED + ratio 1/1   (does canvas alone void an unscaled draw?)
// with the deferred pixel probe after each; swapped canvases re-scale at the next
// hook event (probePending) so layout reads stay scaled outside the call window.
// v14 — v13 run: ALL FOUR variants void, including C = a byte-perfect vanilla call
// (native struct, 1/1 ratio, dest+clip+chain all verified transparent). A vanilla
// call that voids means the fault is NOT in anything we mutate. Two classes left:
// (a) the E8 at the site no longer targets sd2 (live site-stomp — the
//     feedback_pracx_site_stomp class; "cluster clean" was a STATIC claim), or
// (b) sd2's body rejects on state not yet read.
// v14 instruments both: log the LIVE bytes + resolved E8 target of every sd2 site
// at attach time; variant E (draw 5) disarms g_faction_active around one call;
// and a REPLAY at paint#2 end calls Sprite_draw_2 directly (NativeFunction,
// game thread) with a temp-restored NATIVE icon into the SocialWin canvas at
// (300,300) n/d=1/1 and again at (500,300) n/d=g/16, probing pixels after each —
// replay lands => painter-context fault; replay voids => dest/body fault.
// v15 — v14 run: THE REPLAY LANDED (native pixels at 300,300; engine-scaled pixels
// at 500,~310..355 — the (g,16) ratio path works, offsets scale with it), while
// the painter's identical calls void MID-PAINT. Eliminated by data: bracket flag
// (variant E voided), repair-storm (paint#2+ runs no repairs, still voids),
// site-stomp, chain, args, sprite state. Remaining: DEST STATE that differs
// mid-paint vs end-of-paint. v15 measures it: full dest header +0x00..+0x60 at a
// mid-paint band draw AND at the end-of-paint replay (diff = the blocking field);
// plus mid-paint DIRECT calls at (300,300) and at the painter's own (x,y) with a
// native icon — position-dependence test (clip-rect class if same-xy voids while
// 300,300 lands mid-paint).
// v16 — v15 run: SOLVED. HDR mid-paint vs replay-time differ ONLY at +0x20..+0x2C
// (band clip rect 65,10..1555,185 — icons sit inside it). MIDTEST-samexy (direct
// call at the painter's own x,y) LANDED mid-paint and the painter's own draw at
// the same spot a moment later put NOTHING over it. Sole remaining difference =
// the Interceptor.attach ON THE CALL INSTRUCTION at each sd2 site (since v6 = when
// the icons vanished): Frida treats the attach address as a function entry and
// installs its return trampoline by overwriting [esp] — at a CALL site [esp] is
// the first pushed ARG (dest), not a return address. sd2 got a bogus Buffer*,
// clipped everything, and ret 0x18 popped the trampoline slot (= why onLeave
// never fired). The probe voided every draw it observed. v16: site attaches
// REMOVED; the (g,16) ratio is a byte-patch of each site's two `push 1`.
// v17 — v16 run: ICONS BACK (user). Four polish items, all measured on the 4K shot:
//  (1) label text 4px high in every FlatButton (pristine: ink-centred, -1.5px):
//      thunk_btntext_nudge @0x608441 lifts labels by (g-16)*3/16 = 4 @g40 whenever
//      g_faction_active is armed — a faction-picker law riding on the flag we borrow.
//      Fix: flip its `je passthrough` (pcave2+0x1397: 74->EB) while the SE bracket is
//      armed, restore at close. The bake's own g_social_active never triggers it.
//  (2) digit overlaps icon: the post-digit advance is [+0x2C70]+1 where +0x2C70 is
//      the digit[4] blit w (native 7, must stay native for the sd2 ratio) — advance
//      7+s(1) vs vanilla-proportion s(7)+s(1). Fix: the two [+0x2C70] READS in the
//      band painter (0x4AF7D8 advance, 0x4AF633 row-width) become MOV r32,imm32=s(7).
//  (3) button faces show a 1px dither at 4K (devfill re-tiles at device res; the
//      fe_pair_remap pair table has no SE pairs): per-draw pair detection + P-law
//      restripe of the whole button canvas at the label-draw entry 0x4B17A0 (fires
//      per FlatButton draw, face composed, label not yet drawn). Law SL.stripeTop.
//  (4) slider label bars + fill bars are Buffer_tile of 14x14 socwin tiles at
//      native 1px density: rebuild each pure-pair tile as a w x 2P striped tile
//      (Buffer_resize + direct rows) at transform; Buffer_tile's absolute anchoring
//      keeps the phase = dest y. Tiles load once per process -> H==2P is the
//      already-done check. Non-pair tiles are logged and left alone.
// v18 — v17 run CONFIRMED by measurement (label offset -1.0 vs pristine -1.5; faces
// and slider bars 3/2 stripes; digit gap proportional). Remaining native-density
// surfaces = the MODAL's own Buffer_box_sprite draws (1px strokes, 1px dither body
// and ring) — the console panels beside it already read K=2 strokes + P stripes
// because their dest is the MainWin buffer, which the baked thunk_hud_boxframe
// entry detour (0x5E2DD3 prologue, HUD-dest-gated) thickens; SocialWin-canvas dests
// pass through native. v18 = the thunk_pref_boxframe dispatch WITHOUT its rect
// scaling (SE rects are already device): the 11 modal-canvas sites are rel32-
// redirected to thunk_box_thick_hollow_flat (hollow d5a0: no outward grow, butting
// cells keep their footprint) or thunk_box_thick_devfill (filled d618 title bands +
// the d690 backdrop: bevel + device-density interior + P restripe tail). Sites are
// verified live (E8 -> 0x5E2DD3) before patching; thunks gate g<=16 -> native.
// v19 — v18 run: chrome CONFIRMED (strokes 2px = K, body 3/2, bevel intact), reopen
// pixel-identical, hover panel proportionate. Hover RING measured 2px top/left vs
// 3px bottom/right = the NN remainder on the state sprite's 1px edge rows (the user's
// suspicion). Fix = the remainder-distribution law "pin chrome cells to K": in the
// restripe pass, each edge's non-pair run (the ring) keeps its OUTER K=strokeWidth(g)
// rows/cols as drawn and the inner remainder is re-striped; a ring thinner than K
// (fractional g where NN gave 1) is grown by repeating its innermost row. Logged
// per edge before/after for every ringed draw. ALSO: the lock art's own dithered
// background (blue pair) was NN-enlarged with the plane -> 2/3 banding around the
// key. enlargeSprite gains the §7 regeneration tail for the locks: pair detected
// from the native plane's rows 0/1, every pair pixel of the enlarged plane rewritten
// to the P-law stripe of its DEST row (lock table top + plane row) so it fuses with
// the P-striped bar tiles beside it.
// v20 — 1600/1920 runs (user: ring inconsistent, bottom ring MISSING at 1600;
// buttons' scanlines inconsistent). MEASURED: every normal button canvas at g=25
// ends in 2 KEY rows (backdrop shows through), the hovered button's bottom ring
// sits in those rows. Two causes, both bracket round-trip: (a) my table rects
// gave the buttons h=32 at g=25 (per-edge halfDown of T and B) while the shrink
// descales with ceil(h*16/g) = 21 native -> 20 art rows + 1 transparent gap row;
// (b) the engine's fractional expand drops the LAST dest row ([[feedback-sprite-
// expand-drops-last-row]]). Fix (a) = FlatButton rect DIMS produced by the FLOOR
// idiom the shrink inverts exactly (SL.scaleFloor: 31 @g25, 27 @g22, 50 @g40) —
// T/L keep their scaled edges, B/R = T/L + fl(h/w*g/16). Fix (b) = overdraw the
// trailing key row(s) with the last drawn row BEFORE the ring pin (the "overdraw
// the final dest row yourself" law). Also: the g=25 log never saw a top ring at
// hook time although the shot has one -> a SECOND hover draw path bypasses
// 0x4B17A0 (draw-state multiplicity). v20 adds a zero-Interceptor setInterval
// watcher over the 29 button canvases that logs (and fixes) any change the hook
// did not make. Lock plane pair now = mode of even rows / mode of odd rows (rows
// 0/1 are the bevel border, the dither is inside).
// v21 - v20 CONFIRMED @1600 (user; ring + bottom rows fixed, lock pair 190/180).
// New: SOCIETY rows (10 stacked FlatButtons, vanilla y=0x1D + 22*i, h 20) showed
// gaps alternating 4/3 @g25 = per-edge halfDown of each top. Law option_row_gap
// (scaling_laws): pin the PITCH to scalePx(22,g) (34 @g25, 30 @g22, 55 @g40), the
// gap absorbs the rounding, the stack end drifts <=3px. T_i = T_0 + i*pitch.
// v22 - v21 CONFIRMED (uniform society pitch) but the SOCIETY panel frame kept its
// scaled vanilla bottom while the stack end drifted up -> too much black below the
// last row. Anchor the chrome to the CONTENT (LAW 5): panel bottom = last row bottom
// + s(3) (vanilla 250 = 247 + 3); SPARTANS box top = panel bottom + s(3) (vanilla
// 253 = 250 + 3), its height preserved. Rows keep their v21 positions.
// v23 — v22 MEASURED (1920 shot, g=22): rows/pitch exact, panel bottom + SPARTANS
// took the derived values, but the two channels the user asked to equalise read
// top 2 / bottom 4 free rows. Cause: the frame thunks draw the bottom stroke on
// row B INCLUSIVE (rows B-K+1..B; measured at K=1 g22 and K=2 g25; top stroke
// starts at T) — the drawn frame is H+1 tall, so "B = lastB + s(3)" leaves one
// extra free row plus the K-1 the stroke does not cover. The band bottom is the
// painter's own T + s(23) (site 0x4af261 = s(0x17)-s(3) on top of the s(3) inset),
// so topFree = t0 - (T + s(23)) - 1 is computed from the same arithmetic the
// painter runs, and the panel bottom is placed so bottomFree == topFree:
// B = lastB + topFree + (K - 1). SPARTANS top = B + 1 + s(3) (vanilla's 3 free
// rows between the panel stroke and the SPARTANS stroke, scaled). The 1600 shot
// of 00:14 was byte-identical to v21 (SPARTANS at s(253)=395) — needs a re-run;
// v23 logs the rects at the two painters' entries so a run is self-verifying.
log("=== hook_se_scale_proto.js v23 started === " + new Date().toISOString());
installAVHandler("se_proto");

if (requireBase()) {
  const SL = globalThis.SL;
  const G_SCALE = 0x668740;         // g_popup_scale_num (cave menu_strip_thunks+0x540)
  const G_REGIONS = 0x7af5a0;       // MainWin region rects (already HUD-scaled)
  const NAME_HUD = 0x691b2c, NAME_AN = 0x691b30;   // char** font-name globals

  let g = 16;
  const s = v => SL.scalePx(v, g);  // LAW 1 half-down: every value = vanilla x g/16

  const Buffer_resize = new NativeFunction(VA(0x5d79c0), "int",
    ["pointer", "int", "int"], "thiscall");                    // RET 8; h POSITIVE
  const Font_init = new NativeFunction(VA(0x618f40), "int",
    ["pointer", "pointer", "int", "int"], "thiscall");   // (slot, name, size, style)
  const Win_redraw = new NativeFunction(VA(0x5d5a70), "int",
    ["pointer"], "fastcall");                            // generic GraphicWin redraw

  function rd(p) { return [p.readS32(), p.add(4).readS32(), p.add(8).readS32(), p.add(12).readS32()]; }
  function wr(p, r) { p.writeS32(r[0]); p.add(4).writeS32(r[1]); p.add(8).writeS32(r[2]); p.add(12).writeS32(r[3]); }
  const scaleRectEdges = p => wr(p, rd(p).map(s));   // absolute edges: per-edge scalePx

  // ---------------------------------------------------------------------------
  // Code patches: [staticAddr, immOff, width(1|4), a, b] → imm := s(a) − s(b)
  // (b covers composed edges: total-on-base sites and pure negatives a=0.)
  // Full derivation per site: work\_se_patch_plan.md.
  // ---------------------------------------------------------------------------
  const PATCHES = [
    // builder literals: window x-base / y-anchor / h / w pushes + backdrop L,R,B
    [0x4b3297, 1, 4, 0, 0x321], [0x4b32ae, 2, 4, 0x162, 0],
    [0x4b32d2, 1, 4, 0x162, 0], [0x4b32d7, 1, 4, 0x341, 0],
    [0x4b32fd, 3, 4, 0x17, 0], [0x4b3307, 3, 4, 0x30a, 0], [0x4b330e, 3, 4, 0x162, 0],
    // master painter union-frame outsets
    [0x4b1a08, 1, 4, 3, 0], [0x4b1a65, 1, 4, 3, 0],
    // society panel
    [0x4af234, 2, 1, 3, 0], [0x4af23d, 2, 1, 3, 0], [0x4af240, 2, 1, 3, 0],
    [0x4af246, 2, 1, 3, 0], [0x4af261, 2, 1, 0x17, 3],
    // band painter (incl. locked-row placeholder branch + icon advances)
    [0x4af36d, 2, 1, 3, 0], [0x4af376, 2, 1, 3, 0], [0x4af379, 2, 1, 3, 0],
    [0x4af37f, 2, 1, 3, 0], [0x4af39a, 2, 1, 0x17, 3], [0x4af489, 1, 4, 0x16, 0],
    [0x4af4ca, 2, 1, 0x16, 0], [0x4af4dd, 2, 1, 0x16, 0], [0x4af628, 2, 1, 1, 0],
    [0x4af7de, 3, 1, 1, 0], [0x4af858, 3, 1, 1, 0],
    // spartans box
    [0x4af915, 2, 1, 3, 0], [0x4af918, 2, 1, 3, 0], [0x4af91b, 2, 1, 3, 0],
    [0x4af927, 2, 1, 3, 0], [0x4af936, 2, 1, 0x17, 3], [0x4afa07, 2, 1, 0, 0x14],
    [0x4afa77, 2, 1, 2, 0],
    // center console
    [0x4afbb0, 2, 1, 0x14, 0], [0x4afc5f, 2, 1, 2, 0], [0x4afc81, 1, 4, 3, 0],
    // SOCIAL EFFECTS text
    [0x4b049b, 2, 1, 3, 0], [0x4b049e, 2, 1, 3, 0], [0x4b04ad, 2, 1, 3, 0],
    [0x4b04b8, 2, 1, 3, 0], [0x4b04bb, 2, 1, 0x17, 3], [0x4b0544, 2, 1, 2, 0],
    [0x4b0575, 2, 1, 0x14, 0], [0x4b057b, 2, 1, 0xF, 0x14], [0x4b0586, 2, 1, 3, 0],
    // hover panel
    [0x4b10dc, 2, 1, 3, 0], [0x4b10df, 2, 1, 3, 0], [0x4b10ee, 2, 1, 3, 0],
    [0x4b10f9, 2, 1, 3, 0], [0x4b10fc, 2, 1, 0x17, 3], [0x4b11c6, 2, 1, 2, 0],
    [0x4b11f4, 1, 4, 3, 0], [0x4b1465, 2, 1, 3, 0], [0x4b1696, 2, 1, 0x10, 0],
    [0x4b16b6, 3, 1, 0x10, 0], [0x4b1700, 1, 4, 0, 0x10],
    // button label draw — DEVICE space (v5 run proved the bracket scales only the
    // face bar; label/icons/values draw after the restore at device scale)
    [0x4b1866, 1, 1, 5, 0], [0x4b1898, 2, 1, 0x25, 0], [0x4b1956, 2, 1, 3, 0],
  ];
  // slider trio (identical shapes at ECON/LABS/PSYCH addrs)
  const SLIDER_ROWS = [
    [[0x4b08f9, 0x4b0b59, 0x4b0da9], 2, 1, 3, 0],
    [[0x4b08fc, 0x4b0b5c, 0x4b0dac], 2, 1, 3, 0],
    [[0x4b0902, 0x4b0b62, 0x4b0db2], 2, 1, 0x1a, 3],
    [[0x4b0905, 0x4b0b65, 0x4b0db5], 2, 1, 3, 0],
    [[0x4b0919, 0x4b0b79, 0x4b0dc9], 2, 1, 3, 0],
    [[0x4b0927, 0x4b0b87, 0x4b0dd7], 2, 1, 0x1a, 3],
    [[0x4b092a, 0x4b0b8a, 0x4b0dda], 2, 1, 0x17, 3],
  ];
  for (const [addrs, off, w, a, b] of SLIDER_ROWS)
    for (const addr of addrs) PATCHES.push([addr, off, w, a, b]);

  let codePatched = false;
  function applyCodePatches() {
    if (codePatched) return;
    codePatched = true;
    let n = 0, skip = 0;
    for (const [addr, off, width, a, b] of PATCHES) {
      const sv = s(a) - s(b);
      if (width === 1 && (sv > 127 || sv < -128)) { skip++; log("PATCH SKIP imm8 overflow @0x" + addr.toString(16) + " -> " + sv); continue; }
      Memory.patchCode(VA(addr), off + width, code => {
        if (width === 1) code.add(off).writeS8(sv); else code.add(off).writeS32(sv);
      });
      n++;
    }
    log("code patches applied: " + n + "/" + PATCHES.length + (skip ? " (SKIPPED " + skip + ")" : ""));
    // v17: the two band-painter READS of the digit blit-w alias [+0x2C70] (native 7,
    // stays native for the sd2 ratio) become `MOV r32, s(7)` — MOV r32,[EDI+disp32]
    // (8B 87/97 70 2C 00 00, 6B) -> B8/BA imm32 + NOP.
    for (const [va, orig, opc] of [[0x4af7d8, [0x8b, 0x87], 0xb8], [0x4af633, [0x8b, 0x97], 0xba]]) {
      const b = new Uint8Array(VA(va).readByteArray(6));
      if (b[0] !== orig[0] || b[1] !== orig[1] || b[2] !== 0x70 || b[3] !== 0x2c) { log("MOVIMM SKIP @0x" + va.toString(16)); continue; }
      Memory.patchCode(VA(va), 6, code => {
        code.writeU8(opc); code.add(1).writeS32(s(7)); code.add(5).writeU8(0x90);
      });
    }
    log("digit-w alias reads -> imm s(7)=" + s(7));
  }

  // ---------------------------------------------------------------------------
  // Fonts (builder inits them BEFORE model_reset; re-init scaled at transform)
  // [slotOffset, namePtrVA, size, style, dw0AfterOrNull]
  // ---------------------------------------------------------------------------
  const FONTS = [
    [0x1ee68, NAME_HUD, 14, 1, null], [0x1ee90, NAME_HUD, 14, 1, null],
    [0x1eeb8, NAME_AN, 14, 1, null], [0x1eee0, NAME_AN, 14, 1, null],
    [0x1ef08, NAME_HUD, 12, 0, null],
    [0x1ef30, NAME_HUD, 11, 1, 3], [0x1ef58, NAME_HUD, 11, 0, 3],
    [0x1ef80, NAME_AN, 14, 1, null], [0x1efa8, NAME_AN, 14, 1, null],
  ];
  function rescaleFonts(obj) {
    for (const [slot, nameVA, size, style, dw0] of FONTS) {
      const namePtr = VA(nameVA).readPointer();
      Font_init(obj.add(slot), namePtr, s(size), style);
      if (dw0 !== null) obj.add(slot).writeS32(s(dw0));   // line-pad px (builder writes 3 after init)
    }
    log("fonts re-inited x" + FONTS.length);
  }

  // ---------------------------------------------------------------------------
  // The transform — at SocialWin_model_reset entry, before any button exists.
  // ---------------------------------------------------------------------------
  const MODAL_TABLE_RECTS = [
    0x1f060,
    ...Array.from({ length: 10 }, (_, i) => 0x1f070 + i * 0x10),
    ...Array.from({ length: 4 },  (_, i) => 0x1f110 + i * 0x10),
    ...Array.from({ length: 16 }, (_, i) => 0x1f150 + i * 0x10),
    0x1f2a0, 0x1f2b0, 0x1f2c0, 0x1f2d0,
  ];

  function transform(obj) {
    // -- modal-local tables: scale edges --
    for (const off of MODAL_TABLE_RECTS) scaleRectEdges(obj.add(off));
    // v20: FlatButton rect DIMS by the FLOOR idiom (the shrink's exact inverse):
    // society rows x10 (143x20), option buttons x16 (146x20), OK/RESET/CANCEL (162x20).
    const BTN_RECTS = [
      ...Array.from({ length: 10 }, (_, i) => [0x1f070 + i * 0x10, 143, 20]),
      ...Array.from({ length: 16 }, (_, i) => [0x1f150 + i * 0x10, 146, 20]),
      [0x1f2b0, 162, 20], [0x1f2c0, 162, 20], [0x1f2d0, 162, 20],
    ];
    for (const [off, w, h] of BTN_RECTS) {
      const q = rd(obj.add(off));
      wr(obj.add(off), [q[0], q[1], q[0] + SL.scaleFloor(w, g), q[1] + SL.scaleFloor(h, g)]);
    }
    log("button rect dims pinned: " + SL.scaleFloor(146, g) + "x" + SL.scaleFloor(20, g) + " (native round-trip " +
        Math.ceil(SL.scaleFloor(20, g) * 16 / g) + ")");
    // v21: SOCIETY rows on a UNIFORM pitch (law option_row_gap: pitch = scalePx(22)).
    const rowPitch = SL.scalePx(22, g), rowH = SL.scaleFloor(20, g), t0 = rd(obj.add(0x1f070))[1];
    for (let i = 0; i < 10; i++) {
      const q = rd(obj.add(0x1f070 + i * 0x10));
      wr(obj.add(0x1f070 + i * 0x10), [q[0], t0 + i * rowPitch, q[2], t0 + i * rowPitch + rowH]);
    }
    log("society rows: pitch " + rowPitch + " h " + rowH + " gap " + (rowPitch - rowH) + " t0 " + t0);
    // v23: SOCIETY panel bottom + SPARTANS box follow the row stack; the two free
    // channels (band stroke -> first row, last row -> panel stroke) are made EQUAL.
    // Frame strokes (measured g22/g25): top stroke rows T..T+K-1, bottom stroke rows
    // B-K+1..B (inclusive B). Band bottom = T + s(23) (painter arithmetic).
    const FRAME_BOTTOM_INCL = 1;                                 // measured: bottom stroke ends ON row B
    const K = SL.strokeWidth(g);
    const soc = rd(obj.add(0x1f060)), lastB = t0 + 9 * rowPitch + rowH;
    const bandB = soc[1] + s(23);
    const topFree = t0 - bandB - FRAME_BOTTOM_INCL;
    soc[3] = lastB + topFree + (K - 1);
    wr(obj.add(0x1f060), soc);
    const spa = rd(obj.add(0x1f2a0)), spaH = spa[3] - spa[1];
    spa[1] = soc[3] + FRAME_BOTTOM_INCL + s(3); spa[3] = spa[1] + spaH;
    wr(obj.add(0x1f2a0), spa);
    log("society panel: T " + soc[1] + " bandB " + bandB + " t0 " + t0 + " topFree " + topFree + " | lastB " + lastB +
        " -> B " + soc[3] + " (K=" + K + ", bottomFree " + (soc[3] - K + 1 - lastB) + ") | SPARTANS " + spa +
        " (free rows above " + (spa[1] - soc[3] - 1) + " = s(3)=" + s(3) + ")");

    // -- console tables: rebuild the builder derivation with scaled constants --
    const R = i => VA(G_REGIONS + i * 4).readS32();
    const r0 = [R(0), R(1), R(2), R(3)];      // left console region
    const r1 = [R(4), R(5), R(6), R(7)];      // right console region
    const r2 = [R(8), R(9), R(10), R(11)];    // center region
    const rs = [R(12), R(13), R(14), R(15)];  // slider strip region
    wr(obj.add(0x1f250), [r1[0] + s(4), r1[1] + s(4), r1[2] - s(4), r1[3] - s(4)]);   // fx box
    wr(obj.add(0x1f2e0), [r2[0] + s(4), r2[1] + s(4), r2[2] - s(4), r2[3] - s(4)]);   // center box
    const L = r0[0] + s(7), T = rs[1] + s(7), Rr = rs[2] - s(7), B = rs[3] - s(7);
    const colW = (((Rr - L - s(4)) / 3) | 0) - s(3);
    const sldE = [L, T, L + colW, B];
    const sldP = [L + colW + s(3), T, L + 2 * colW + s(3), B];
    const sldL = [sldP[2] + s(3), T, Rr, B];             // LABS absorbs the remainder (builder law)
    wr(obj.add(0x1f260), sldE); wr(obj.add(0x1f280), sldP); wr(obj.add(0x1f270), sldL);
    wr(obj.add(0x1f290), [r0[0] + s(4), r0[1] + s(4), r0[2] - s(4), T - s(6)]);       // hover box
    // arrow table order (trace-verified): 0,1=ECON l/r · 2,3=LABS l/r · 4,5=PSYCH l/r
    const sldForArrow = [sldE, sldE, sldL, sldL, sldP, sldP];
    for (let i = 0; i < 6; i++) {
      const q = sldForArrow[i];
      wr(obj.add(0x1f000 + i * 0x10), (i % 2 === 0)
        ? [q[0] + s(3), q[1] + s(3), q[0] + s(0x17), q[1] + s(0x17)]
        : [q[2] - s(0x17), q[1] + s(3), q[2] - s(3), q[1] + s(0x17)]);
    }
    // lock table order (trace-verified): ECON, PSYCH, LABS
    const lockOrder = [sldE, sldP, sldL];
    for (let i = 0; i < 3; i++) {
      const q = lockOrder[i];
      wr(obj.add(0x1efd0 + i * 0x10), [q[0] + s(3), q[3] - s(0x11), q[0] + s(0x1b), q[3] - s(3)]);
    }
    lockPhaseY = lockOrder[0][3] - s(0x11);                     // lock blit top (all three share a row)

    // (v10: metric loop deleted — those five dwords are sprite struct fields;
    // enlargeInventory below is their one and only owner.)

    rescaleFonts(obj);

    // enlarge sprites HERE — before BaseButton_init runs, so buttons that copy
    // sprite structs at creation (arrow chevrons) copy the ENLARGED art. The
    // repaint-hook call remains as reopen safety (Map-deduped).
    enlargeInventory(obj);
    restripeTiles(obj);

    log("TRANSFORM done: g=" + g +
        " band0=" + rd(obj.add(0x1f110)) + " opt0=" + rd(obj.add(0x1f150)) +
        " sldE=" + rd(obj.add(0x1f260)) + " arrows0=" + rd(obj.add(0x1f000)) +
        " rowH=" + obj.add(0x2e34).readS32());
  }

  // ---------------------------------------------------------------------------
  // v2 repair pass — at SocialWin_repaint entry (idempotent, cheap when clean).
  // ---------------------------------------------------------------------------
  // v3: buffers were ALWAYS created right (table-fed) — the 20px face comes from
  // the button's LOCAL/CLIP rect +0x474 (and the +0x4C4/+0x4C8 W/−H copies) staying
  // native-H after the engine's h-adjust. Fix = poke them to the button's OWN buffer
  // dims — no creation-order mapping, no resize (the v2 mapping guess swapped widths).
  const BTN0 = 0x6020, BTN_STRIDE = 0xb4c, BTN_COUNT = 35;
  let btnObserved = false;
  function repairCanvases(obj) {
    let fixed = 0, created = 0;
    const dump = !btnObserved;
    for (let bi = 0; bi < BTN_COUNT; bi++) {
      const btn = obj.add(BTN0 + bi * BTN_STRIDE);
      const canvas = btn.add(0x444);
      const bw = canvas.add(0x80).readS32(), bh = -canvas.add(0x84).readS32();
      if (bw <= 0 || bw > 4096 || bh <= 0 || bh > 4096) continue;   // not created yet
      created++;
      const lr = rd(btn.add(0x474));
      const cli = rd(btn.add(0x14c));
      if (dump) log("btn#" + bi + " 13C=" + rd(btn.add(0x13c)) + " 14C=" + cli + " 474=" + lr +
                    " 4C4/4C8=" + btn.add(0x4c4).readS32() + "/" + btn.add(0x4c8).readS32() +
                    " buf=" + bw + "x" + bh);
      let did = false;
      // client rect carrying the native h-adjust: same width, shorter height -> stretch to buffer h
      if (cli[2] - cli[0] === bw && cli[3] - cli[1] > 0 && cli[3] - cli[1] < bh) {
        wr(btn.add(0x14c), [cli[0], cli[1], cli[0] + bw, cli[1] + bh]);
        if (fixed < 3) log("btn#" + bi + " client rect " + cli + " -> h=" + bh);
        did = true;
      }
      if (!(lr[0] === 0 && lr[1] === 0 && lr[2] === bw && lr[3] === bh &&
            btn.add(0x4c4).readS32() === bw && btn.add(0x4c8).readS32() === -bh)) {
        wr(btn.add(0x474), [0, 0, bw, bh]);
        btn.add(0x4c4).writeS32(bw);
        btn.add(0x4c8).writeS32(-bh);
        did = true;
      }
      if (did) { Win_redraw(btn); fixed++; }
    }
    if (created === BTN_COUNT && dump) btnObserved = true;   // latch only after ALL dumped
    if (fixed) log("face repair: " + fixed + "/" + created + " buttons");
  }

  // ---------------------------------------------------------------------------
  // v17: device-density scanline stripes for the FlatButton faces (skill
  // scaling-frames §7 + the §7b per-draw pair rule). Host = the label-draw entry
  // 0x4B17A0 (vtbl+0x14; called per FlatButton draw after the face is composed,
  // before the label). Pair detected per draw from one face column; every pixel
  // of the pair is rewritten to the P-law stripe for its canvas row (SL.stripeTop).
  // ---------------------------------------------------------------------------
  function detectPair(u8, stride, H, x) {
    const cnt = new Map();
    for (let y = 0; y < H; y++) { const v = u8[y * stride + x]; cnt.set(v, (cnt.get(v) || 0) + 1); }
    const top2 = [...cnt.entries()].sort((p, q) => q[1] - p[1]).slice(0, 2);
    if (top2.length < 2) return null;
    const a = top2[0][0], b = top2[1][0];
    if (top2[0][1] + top2[1][1] < 0.6 * H) return null;
    let run = 0, prev = -1, first = -1;                       // alternation: runs <= 3 (1px, or NN-zoomed)
    for (let y = 0; y < H; y++) {
      const v = u8[y * stride + x];
      if (v !== a && v !== b) { prev = -1; run = 0; continue; }
      if (first < 0) first = v;
      if (v === prev) { if (++run > 3) return null; } else { prev = v; run = 1; }
    }
    return [first, first === a ? b : a];                       // [top member, bottom member]
  }
  function restripeBuffer(buf, colFrac) {
    const data = buf.add(0x54).readPointer(), stride = buf.add(0x4a8).readS32();
    const W = buf.add(0x80).readS32(), H = -buf.add(0x84).readS32();
    if (data.isNull() || W <= 0 || H <= 0 || stride < W) return null;
    const u8 = new Uint8Array(data.readByteArray(stride * H));
    const pair = detectPair(u8, stride, H, Math.max(1, Math.min(W - 2, Math.floor(W * colFrac))));
    if (!pair) return null;
    const [top, bot] = pair;
    // v20 (b): the engine's fractional expand leaves the LAST dest row(s) key —
    // overdraw them with the last drawn row (art continues; a ring's bottom row
    // survives), at most 2 rows. Key = the canvas key index (9).
    const KEY = 9;
    let kb = 0;
    const rowKey = y => { let n = 0; for (let x = 4; x < W - 4; x++) if (u8[y * stride + x] === KEY) n++; return n >= 0.9 * (W - 8); };
    while (kb < 2 && H - 1 - kb > 0 && rowKey(H - 1 - kb)) kb++;
    if (kb) {
      const srcRow = H - 1 - kb;
      for (let y = H - kb; y < H; y++) for (let x = 0; x < W; x++) u8[y * stride + x] = u8[srcRow * stride + x];
      lastOverdraw = kb;
    } else lastOverdraw = 0;
    for (let y = 0; y < H; y++) {
      const c = SL.stripeTop(y, g, 0) ? top : bot, o = y * stride;
      for (let x = 0; x < W; x++) { const v = u8[o + x]; if (v === top || v === bot) u8[o + x] = c; }
    }
    const ring = pinRing(u8, stride, W, H, top, bot);
    data.writeByteArray(u8.buffer);
    return ring ? [top, bot, ring] : pair;
  }
  // v19: pin the state-sprite RING (non-pair edge rows/cols, NN-zoomed to 2..3px at
  // 4K) to K = strokeWidth(g) on all four edges. Returns the measured depths or null.
  function pinRing(u8, stride, W, H, top, bot) {
    const K = SL.strokeWidth(g);
    const isPair = v => v === top || v === bot;
    const m = 8;                                                // corner margin for the probes
    if (W < 4 * m || H < 4 * m) return null;
    const rowRing = y => { let n = 0; for (let x = m; x < W - m; x++) if (!isPair(u8[y * stride + x])) n++; return n >= 0.9 * (W - 2 * m); };
    const colRing = x => { let n = 0; for (let y = m; y < H - m; y++) if (!isPair(u8[y * stride + x])) n++; return n >= 0.9 * (H - 2 * m); };
    let dT = 0, dB = 0, dL = 0, dR = 0;
    while (dT < 8 && rowRing(dT)) dT++;
    while (dB < 8 && rowRing(H - 1 - dB)) dB++;
    while (dL < 8 && colRing(dL)) dL++;
    while (dR < 8 && colRing(W - 1 - dR)) dR++;
    if (!dT && !dB && !dL && !dR) return null;
    const stripe = y => SL.stripeTop(y, g, 0) ? top : bot;
    // trim: inner remainder -> stripes; grow: repeat the innermost ring row/col
    for (let y = K; y < dT; y++) for (let x = K; x < W - K; x++) u8[y * stride + x] = stripe(y);
    for (let y = H - dB; y < H - K; y++) for (let x = K; x < W - K; x++) u8[y * stride + x] = stripe(y);
    for (let x = K; x < dL; x++) for (let y = K; y < H - K; y++) u8[y * stride + x] = stripe(y);
    for (let x = W - dR; x < W - K; x++) for (let y = K; y < H - K; y++) u8[y * stride + x] = stripe(y);
    if (dT && dT < K) for (let y = dT; y < K; y++) for (let x = 0; x < W; x++) u8[y * stride + x] = u8[(dT - 1) * stride + x];
    if (dB && dB < K) for (let y = H - K; y < H - dB; y++) for (let x = 0; x < W; x++) u8[y * stride + x] = u8[(H - dB) * stride + x];
    if (dL && dL < K) for (let x = dL; x < K; x++) for (let y = 0; y < H; y++) u8[y * stride + x] = u8[y * stride + dL - 1];
    if (dR && dR < K) for (let x = W - K; x < W - dR; x++) for (let y = 0; y < H; y++) u8[y * stride + x] = u8[y * stride + W - dR];
    return [dT, dB, dL, dR, K];
  }
  const btnStripeSeen = {}, btnRingSeen = {};
  let lastOverdraw = 0;
  // v20: zero-Interceptor canvas watcher — detects button-canvas writes that did
  // NOT pass through the 0x4B17A0 hook (the hover draw path at g=25 never showed a
  // top ring at hook time, yet the shot has one). Signature = rows 0,1,H-2,H-1.
  const hookSig = {};
  function canvasSig(buf) {
    try {
      const data = buf.add(0x54).readPointer(), stride = buf.add(0x4a8).readS32();
      const W = buf.add(0x80).readS32(), H = -buf.add(0x84).readS32();
      if (data.isNull() || W <= 0 || H < 4) return null;
      let h = 0;
      for (const y of [0, 1, H - 2, H - 1]) { const r = new Uint8Array(data.add(y * stride).readByteArray(W)); for (let x = 0; x < W; x++) h = (h * 31 + r[x]) | 0; }
      return h;
    } catch (e) { return null; }
  }
  function colIdxRuns(buf, x) {
    const data = buf.add(0x54).readPointer(), stride = buf.add(0x4a8).readS32(), H = -buf.add(0x84).readS32();
    let runs = [], prev = -1, start = 0;
    for (let y = 0; y < H; y++) { const v = data.add(y * stride + x).readU8(); if (v !== prev) { if (prev >= 0) runs.push(prev + "x" + (y - start)); prev = v; start = y; } }
    runs.push(prev + "x" + (H - start));
    return runs.join(" ");
  }
  let watchLogs = 0;
  setInterval(() => {
    if (g <= 16 || VA(G_FACTION_ACTIVE).readS32() !== 1) return;
    const obj = VA(0x8a6270);
    for (let i = 0; i < 29; i++) {
      const btn = obj.add(0x6020 + i * 0xb4c);
      let cv;
      try { cv = btn.add(0x444); if (cv.add(0x54).readPointer().isNull()) continue; } catch (e) { continue; }
      const sig = canvasSig(cv);
      if (sig === null || sig === hookSig[i]) continue;
      if (watchLogs < 12) {
        watchLogs++;
        log("WATCH btn#" + i + " canvas changed outside the hook: col W/2 = " + colIdxRuns(cv, cv.add(0x80).readS32() >> 1) +
            " | col 3 = " + colIdxRuns(cv, 3));
      }
      try { restripeBuffer(cv, 0.25); } catch (e) {}
      hookSig[i] = canvasSig(cv);
    }
  }, 120);
  Interceptor.attach(VA(0x4b17a0), {
    onEnter() {
      if (g <= 16) return;
      try {
        const sp = this.context.esp;
        const btn = sp.add(4).readPointer(), id = sp.add(0xc).readS32();
        const pair = restripeBuffer(btn.add(0x444), 0.25);
        const n = (btnStripeSeen[id] = (btnStripeSeen[id] || 0) + 1);
        const ringed = pair && pair.length === 3;
        if (n <= 2 || n % 50 === 0 || (ringed && (btnRingSeen[id] = (btnRingSeen[id] || 0) + 1) <= 3))
          log("btn#" + id + " draw " + n + " restripe " + (pair ? "pair " + pair[0] + "/" + pair[1] : "SKIP (no pair)") +
              " P=" + SL.stripePeriod(g, 0) + (lastOverdraw ? " overdrew " + lastOverdraw + " key row(s)" : "") +
              (ringed ? " RING T/B/L/R=" + pair[2].slice(0, 4).join("/") + " -> K=" + pair[2][4] : ""));
        hookSig[id] = canvasSig(btn.add(0x444));
      } catch (e) { log("restripe err " + e); }
    }
  });

  // v17: slider tiles (6 Buffers at obj+0x3EF0.. stride 0x588, 14x14 socwin cells):
  // rebuild each pure 2-row dither tile as W x 2P stripes. Buffer_tile anchors at
  // the dest grid (srcOff==dest), so phase = dest y; H==2P marks an already-done tile.
  const TILES = [0x3ef0, 0x4478, 0x4a00, 0x4f88, 0x5510, 0x5a98];
  function restripeTiles(obj) {
    const P = SL.stripePeriod(g, 0), TH = 2 * P;
    for (const off of TILES) {
      try {
        const buf = obj.add(off);
        const W = buf.add(0x80).readS32(), H = -buf.add(0x84).readS32();
        let data = buf.add(0x54).readPointer(), stride = buf.add(0x4a8).readS32();
        if (data.isNull() || W <= 0 || H <= 0) { log("tile+" + off.toString(16) + " skip " + W + "x" + H); continue; }
        if (H === TH) continue;
        const r0 = [], r1 = [];
        for (let x = 0; x < W; x++) { r0.push(data.add(x).readU8()); r1.push(data.add(stride + x).readU8()); }
        const a = r0[0], b = r1[0];
        const pure = a !== b && r0.every(v => v === a) && r1.every(v => v === b) &&
                     H >= 3 && data.add(2 * stride).readU8() === a;
        log("tile+" + off.toString(16) + " " + W + "x" + H + " rows0/1=" + a + "/" + b +
            (pure ? " pure -> " + W + "x" + TH : " NOT pure: " + r0.slice(0, 7) + " | " + r1.slice(0, 7)));
        if (!pure) continue;
        Buffer_resize(buf, W, TH);
        data = buf.add(0x54).readPointer(); stride = buf.add(0x4a8).readS32();
        for (let y = 0; y < TH; y++) {
          const c = SL.stripeTop(y, g, 0) ? a : b;
          for (let x = 0; x < W; x++) data.add(y * stride + x).writeU8(c);
        }
      } catch (e) { log("tile+" + off.toString(16) + " err " + e); }
    }
  }

  // sprite-struct enlarge: NN centre-map (matches the engine's centre-aligned NN
  // stretch; SE icon art is flat pixel art per the dither census — no banded pairs)
  const enlargedPlanes = new Map();           // spriteAddr -> our plane ptr
  const savedSprites = new Map();             // spriteAddr -> original 0x2C struct bytes
  const keepAlive = [];
  function centreMap(dst, src) {
    const m = new Int32Array(dst);
    for (let j = 0; j < dst; j++) m[j] = Math.min(src - 1, (((2 * j + 1) * src) / (2 * dst)) | 0);
    return m;
  }
  // keepCanvas=true: leave +0x18/+0x1C native so canvas-h-derived anchors stay at
  // their vanilla line and the art grows down/right into the (scaled) row — the v6
  // log proved anchors subtract canvas h exactly (digit y 164->145 = -(32-13)).
  // v11: the plane is CANVAS-dimensioned with pitch == canvas w — the native
  // invariant every extracted sprite carries (arrow dump: pitch 20 == canvas 20;
  // blit is just the inked subregion at the plane's top-left). Every prior void
  // state shipped a blit-sized plane with pitch=s(blitW) under a larger declared
  // canvas; restore the invariant: alloc s(cw)*s(ch) key-filled, ink at (0,0).
  let pitchLogN = 0;
  let lockPhaseY = 0;                                          // dest y of the lock blits (set by transform)
  function enlargeSprite(sp, keepCanvas, phaseY) {
    let data;
    try { data = sp.add(4).readPointer(); } catch (e) { return 0; }
    if (data.isNull()) return 0;                               // filename-backed variant: pcBits NULL forever
    const pitch = sp.add(0xc).readS32();
    const bw = sp.add(0x10).readS32(), bh = sp.add(0x14).readS32();
    const cw = sp.add(0x18).readS32(), ch = sp.add(0x1c).readS32();
    const key = sp.add(8).readS32() & 0xff;
    if (bw <= 0 || bw > 64 || bh <= 0 || bh > 64 || pitch <= 0 || pitch > 4096) return 0;   // layout sanity
    if (cw <= 0 || cw > 64 || ch <= 0 || ch > 64) return 0;
    const tag = enlargedPlanes.get(sp.toString());
    if (tag && data.equals(tag)) return 0;                     // already ours (re-check survives reopen)
    if (pitchLogN < 6) {
      pitchLogN++;
      log("native sprite @" + sp + " pitch=" + pitch + " blit=" + bw + "x" + bh + " canvas=" + cw + "x" + ch);
    }
    const rowBytes = Math.min(bw, pitch);                       // some digit variants have blit w > pitch
    let src;
    try { src = new Uint8Array(data.readByteArray(pitch * bh)); } catch (e) { return 0; }
    const w2 = s(bw), h2 = s(bh);
    const cw2 = s(cw), ch2 = s(ch);
    const cmap = centreMap(w2, bw), rmap = centreMap(h2, bh);
    const out = new Uint8Array(cw2 * ch2).fill(key);
    for (let y = 0; y < h2; y++) {
      const srow = rmap[y] * pitch, drow = y * cw2;
      for (let x = 0; x < w2; x++) {
        const sx = cmap[x];
        out[drow + x] = sx < rowBytes ? src[srow + sx] : key;
      }
    }
    if (phaseY !== undefined && bh >= 3) {                     // §7: regenerate the plane's dither at device density
      const mode = rows => { const c = new Map(); let best = -1, bc = 0, tot = 0; for (const y of rows) for (let x = 0; x < rowBytes; x++) { const v = src[y * pitch + x]; if (v === key) continue; tot++; const n = (c.get(v) || 0) + 1; c.set(v, n); if (n > bc) { bc = n; best = v; } } return [best, bc, tot]; };
      const ev = mode(Array.from({ length: bh }, (_, y) => y).filter(y => y % 2 === 0));
      const od = mode(Array.from({ length: bh }, (_, y) => y).filter(y => y % 2 === 1));
      const a = ev[0], b = od[0];
      if (a !== b && a >= 0 && b >= 0 && ev[1] >= 0.4 * ev[2] && od[1] >= 0.4 * od[2]) {
        let n = 0;
        for (let y = 0; y < h2; y++) {
          const c = SL.stripeTop(phaseY + y, g, 0) ? a : b, o = y * cw2;
          for (let x = 0; x < w2; x++) { const v = out[o + x]; if (v === a || v === b) { out[o + x] = c; n++; } }
        }
        log("lock plane restriped pair " + a + "/" + b + " phaseY=" + phaseY + " px=" + n);
      } else log("lock plane: no dominant even/odd pair (" + a + "/" + b + ") — left NN");
    }
    const plane = Memory.alloc(cw2 * ch2);
    plane.writeByteArray(out.buffer);
    keepAlive.push(plane);
    if (!savedSprites.has(sp.toString()))
      savedSprites.set(sp.toString(), sp.readByteArray(0x2c));   // restore-on-close
    sp.add(4).writePointer(plane);
    sp.add(0xc).writeS32(cw2);                                  // pitch == canvas w (native invariant)
    sp.add(0x10).writeS32(w2); sp.add(0x14).writeS32(h2);
    if (!keepCanvas) { sp.add(0x18).writeS32(cw2); sp.add(0x1c).writeS32(ch2); }
    enlargedPlanes.set(sp.toString(), plane);
    return 1;
  }
  // v9: canvas fields SCALED everywhere — v8 proved the engine void-draws when
  // blit > canvas (v7's native-canvas icons never landed a pixel), while v6's
  // scaled-canvas icons rendered (only anchored high). Anchors are fixed at the
  // call sites instead (y rewrites below).
  // v12: sd2-fed sprites get CANVAS-ONLY scaling — data/pitch/blit stay native
  // (sd2 decodes its own format; the call-site (g,16) ratio does the enlarge).
  // Canvas w/h are layout metadata: scaling them IS the rowH/iconGap/etc. scaling.
  const sd2Scaled = new Set();
  function canvasScaleSprite(sp) {
    const key = sp.toString();
    if (savedSprites.has(key)) return 0;                       // already done this open
    const cw = sp.add(0x18).readS32(), ch = sp.add(0x1c).readS32();
    if (cw <= 0 || cw > 64 || ch <= 0 || ch > 64) return 0;    // layout sanity / not extracted
    savedSprites.set(key, sp.readByteArray(0x2c));             // restore-on-close
    sp.add(0x18).writeS32(s(cw)); sp.add(0x1c).writeS32(s(ch));
    sd2Scaled.add(key);
    return 1;
  }
  let arrowsLogged = false;
  function enlargeInventory(obj) {
    let n = 0;
    // arrows +0x3DE8 EXCLUDED — native art; the gate-pre HIT routes their faces
    // through the shrink/2D-zoom pipeline (the GOVERNOR-chevron pattern).
    for (const [base, stride, count] of [[0x2bb0, 0x2c, 14], [0x2e18, 0x2c, 90]])
      for (let i = 0; i < count; i++) n += canvasScaleSprite(obj.add(base + i * stride));
    for (let i = 0; i < 2; i++) n += enlargeSprite(obj.add(0x3d90 + i * 0x2c), false, lockPhaseY);  // locks: raw-blitter
    if (!arrowsLogged) {
      arrowsLogged = true;
      for (let i = 0; i < 6; i++) {
        const sp = obj.add(0x3de8 + i * 0x2c);
        log("arrow[" + i + "] (native, untouched) @" + sp + " data=" + sp.add(4).readPointer() +
            " pitch=" + sp.add(0xc).readS32() +
            " blit=" + sp.add(0x10).readS32() + "x" + sp.add(0x14).readS32() +
            " canvas=" + sp.add(0x18).readS32() + "x" + sp.add(0x1c).readS32());
      }
    }
    log("sprites enlarged: " + n + " (saved " + savedSprites.size + " originals)" +
        " metricAlias iconGap/rowH=" + obj.add(0x2e30).readS32() + "/" + obj.add(0x2e34).readS32() +
        " bigIconW=" + obj.add(0x2c70).readS32() +
        " sldInset/H=" + obj.add(0x3da8).readS32() + "/" + obj.add(0x3dac).readS32());
  }
  function restoreSprites() {
    let n = 0;
    for (const [addr, bytes] of savedSprites) { ptr(addr).writeByteArray(bytes); n++; }
    savedSprites.clear();
    enlargedPlanes.clear();
    sd2Scaled.clear();
    if (n) log("SE close: " + n + " sprite structs restored to native");
  }

  // buffer run-length helper: palette indices along a row segment
  function rowRuns(dataPtr, stride, y, x0, x1) {
    let runs = [], prev = -1, start = x0;
    for (let x = x0; x < x1; x++) {
      const v = dataPtr.add(y * stride + x).readU8();
      if (v !== prev) { if (prev >= 0) runs.push(prev + ":" + start + ".." + x); prev = v; start = x; }
    }
    runs.push(prev + ":" + start + ".." + x1);
    return runs.join(" ");
  }
  function colRuns(dataPtr, stride, x, y0, y1) {
    let runs = [], prev = -1, start = y0;
    for (let y = y0; y < y1; y++) {
      const v = dataPtr.add(y * stride + x).readU8();
      if (v !== prev) { if (prev >= 0) runs.push(prev + ":" + start + ".." + y); prev = v; start = y; }
    }
    runs.push(prev + ":" + start + ".." + y1);
    return runs.join(" ");
  }

  let paintN = 0;
  Interceptor.attach(VA(0x4b19a0), {
    onEnter() {
      if (g <= 16) return;
      const obj = this.context.ecx;
      paintN++;
      try { repairCanvases(obj); } catch (e) { log("REPAIR ERROR: " + e); }
    },
    onLeave() {
      if (g <= 16 || paintN > 6) return;
      try {
        const obj = VA(0x8a6270);
        const cv = obj.add(0x444);
        const data = cv.add(0x54).readPointer(), stride = cv.add(0x4a8).readS32();
        // band0 icon row: local y=150, x 60..620 (icons logged at x~505 y=120..165)
        log("paint#" + paintN + " END canvas row y=150: " + rowRuns(data, stride, 150, 60, 620));
      } catch (e) { log("rowdump err " + e); }
    }
  });

  // slider painters: dump the ACTUAL drawn geometry from the MainWin buffer
  const SLIDERS = [[0x4b08a0, "econ", 0x1f260], [0x4b0b00, "labs", 0x1f270], [0x4b0d50, "psych", 0x1f280]];
  const sldSeen = {};
  for (const [va, name, tOff] of SLIDERS) {
    Interceptor.attach(VA(va), {
      onEnter() { this.obj = this.context.ecx; },
      onLeave() {
        if (g <= 16) return;
        const n = (sldSeen[name] = (sldSeen[name] || 0) + 1);
        if (n > 2) return;
        try {
          const t = rd(this.obj.add(tOff));
          const mb = VA(0x7aec64);
          const data = mb.add(0x54).readPointer(), stride = mb.add(0x4a8).readS32();
          const midX = (t[0] + t[2]) >> 1;
          log("slider " + name + " #" + n + " rect=" + t +
              " sldBarXInset=" + this.obj.add(0x3da8).readS32() + " sldBarH=" + this.obj.add(0x3dac).readS32());
          log("  col x=" + midX + ": " + colRuns(data, stride, midX, t[1], t[3]));
          log("  row y=" + (t[3] - 20) + ": " + rowRuns(data, stride, t[3] - 20, t[0], t[2]));
        } catch (e) { log("sld dump err " + e); }
      }
    });
  }

  // sd2 call-site observers — v10 LOG-ONLY. With blit AND canvas cleanly scaled at
  // transform (single owner, no metric-loop double), the engine's own canvas-h anchor
  // math is vanilla x g/16 by construction; measure before rewriting anything.
  // Args at the call instruction: [esp]=dest [esp+4]=key [esp+8]=x [esp+0xC]=y.
  const SD2_SITES = [
    [0x4af7d3, "band-digit"],
    [0x4af84d, "band-icon"],
    [0x4afb1d, "spartans-icon"],
    [0x4b1878, "society-state"],
    [0x4b16a1, "hover-icon"],
  ];
  // v16: the (g,16) sd2 ratio is applied by PATCHING each site's two `push 1`
  // (den pushed first, num second — args dest,key,x,y,num,den) at build time,
  // exactly as the bake will. NO Interceptor at a CALL instruction, ever again.
  const SD2_RATIO = [                                           // [denPushVA, numPushVA]
    [0x4af79d, 0x4af7a4],                                       // band-digit
    [0x4af82e, 0x4af832],                                       // band-icon
    [0x4afafd, 0x4afb03],                                       // spartans-icon
    [0x4b1676, 0x4b167e],                                       // hover-icon
    [0x4b1856, 0x4b185a],                                       // society-state
  ];
  let sd2Patched = false;
  function applySd2RatioPatches() {
    if (sd2Patched) return;
    sd2Patched = true;
    let n = 0;
    for (const [denVA, numVA] of SD2_RATIO) {
      for (const [va, imm] of [[denVA, 16], [numVA, g]]) {
        const b = new Uint8Array(VA(va).readByteArray(2));
        if (b[0] !== 0x6a || b[1] !== 0x01) { log("SD2 RATIO SKIP @0x" + va.toString(16) + " bytes=" + b[0].toString(16) + " " + b[1].toString(16)); continue; }
        Memory.patchCode(VA(va), 2, code => { code.add(1).writeS8(imm); });
        n++;
      }
    }
    log("sd2 ratio pushes patched: " + n + "/" + (SD2_RATIO.length * 2) + " -> num=" + g + " den=16");
  }
  // v18: modal-canvas Buffer_box_sprite sites -> the existing thick/devfill thunks.
  const T_HOLLOW_FLAT = 0xa0c000 + 0x140, T_DEVFILL = 0xa0c000 + 0x42a0;
  const FRAME_SITES = [                                         // [callVA, set, target]
    [0x4af226, "d5a0", T_HOLLOW_FLAT], [0x4af35f, "d5a0", T_HOLLOW_FLAT], [0x4af904, "d5a0", T_HOLLOW_FLAT],
    [0x4af26f, "d618", T_DEVFILL], [0x4af3a8, "d618", T_DEVFILL], [0x4af47e, "d618", T_DEVFILL],
    [0x4af4a7, "d618", T_DEVFILL], [0x4af4e9, "d618", T_DEVFILL], [0x4af94a, "d618", T_DEVFILL],
    [0x4afa13, "d618", T_DEVFILL],
    [0x4b3315, "d690", T_DEVFILL],                              // builder backdrop
  ];
  let framesPatched = false;
  function applyFrameRedirects() {
    if (framesPatched) return;
    framesPatched = true;
    let n = 0;
    for (const [va, set, tgt] of FRAME_SITES) {
      const b = new Uint8Array(VA(va).readByteArray(5));
      const cur = va + 5 + ((b[1] | (b[2] << 8) | (b[3] << 16) | (b[4] << 24)) | 0);
      if (b[0] !== 0xe8 || (cur >>> 0) !== 0x5e2dd3) { log("FRAME SKIP @0x" + va.toString(16) + " " + set + " bytes=" + Array.from(b).map(x => x.toString(16)).join(" ")); continue; }
      Memory.patchCode(VA(va), 5, code => { code.add(1).writeS32(tgt - (va + 5)); });
      n++;
    }
    log("frame sites redirected: " + n + "/" + FRAME_SITES.length + " (hollow_flat=" + VA(T_HOLLOW_FLAT) + " devfill=" + VA(T_DEVFILL) + ")");
  }
  // v14: verify the LIVE call instruction at each site (site-stomp check) at
  // BUILD time — PRACX rewrites sites at STARTUP ([[feedback-pracx-site-stomp]]).
  // v16: the sites are no longer attached, so every one MUST read E8 -> sd2.
  let sitesChecked = false;
  function checkSites() {
    if (sitesChecked) return;
    sitesChecked = true;
    for (const [site, name] of SD2_SITES) {
      try {
        const p = VA(site);
        const b = new Uint8Array(p.readByteArray(5));
        let tgt = "NOT-E8 (STOMPED?)";
        if (b[0] === 0xe8) tgt = p.add(5).add(p.add(1).readS32()).toString();
        log("site " + name + " @" + p + " bytes=" +
            Array.from(b).map(x => x.toString(16).padStart(2, "0")).join(" ") +
            " -> " + tgt + " (sd2=" + VA(0x5e4b4a) + ")");
      } catch (e) { log("site check err " + name + ": " + e); }
    }
  }
  // build entry: learn g, apply one-time code patches, and ARM the FlatButton
  // 2D-zoom bracket for the whole SE modal (build = modal exec; onLeave = close).
  // g_faction_active (pcave2+0x12D0) is an OR-flag of thunk_btn_gate with the
  // smallest blast radius — the bake gets its own g_social_active.
  const G_FACTION_ACTIVE = 0xa0d2d0;
  // v17: thunk_btntext_nudge (pcave2+0x1390) = `cmp [g_faction_active],0; je +0x14`
  // -> the faction-only label lift. Flip the je to jmp while SE borrows the flag.
  const NUDGE_JE = 0xa0c000 + 0x1390 + 7;
  function setBtnNudge(on) {
    const cur = VA(NUDGE_JE).readU8();
    const want = on ? 0x74 : 0xeb;
    if (cur === want) return;
    if (cur !== 0x74 && cur !== 0xeb) { log("NUDGE byte unexpected " + cur.toString(16) + " - untouched"); return; }
    Memory.patchCode(VA(NUDGE_JE), 1, code => code.writeU8(want));
    log("btntext_nudge " + (on ? "RE-ARMED (74)" : "DISARMED for SE (EB)"));
  }
  Interceptor.attach(VA(0x4b2740), {
    onEnter() {
      g = VA(G_SCALE).readS32();
      checkSites();
      if (g > 16) {
        applyCodePatches();
        applySd2RatioPatches();
        applyFrameRedirects();
        setBtnNudge(false);
        VA(G_FACTION_ACTIVE).writeS32(1);
      }
      log("BUILD enter: g=" + g + (g <= 16 ? " -> native no-op" : " (btn zoom bracket ARMED)"));
    },
    onLeave() {
      if (g > 16) {
        VA(G_FACTION_ACTIVE).writeS32(0);
        setBtnNudge(true);
        try { restoreSprites(); } catch (e) { log("RESTORE ERROR: " + e); }
        log("SE closed (bracket disarmed, sprites native)");
      }
    }
  });

  // ---------------------------------------------------------------------------
  // v10 gate-pre hook (thunk_btn_gate_pre @pcave2+0x13760, an E8-entered bare-RET
  // CALL-helper; entry = 6-byte CMP, no branch into bytes 1..4 — attach-safe):
  //   HIT  the 6 SE slider-arrow FlatButtons (obj+0x6020 + [29..34]*0xB4C =
  //        [0x8C0A2C, 0x8C4DF4)) — label-less state-sprite buttons whose windows
  //        are scaled but whose art drew native 1:1; the gate v6 precedent class.
  //   MISS MENU 0x7B1804 / COMMLINK 0x7B2350 — faces already device-scaled by
  //        thunk_hudmenu_sd2; the armed bracket was double-enlarging them (banding).
  //   Census: log the first distinct buttons the gate sees while the SE bracket is
  //   armed, with the verdict actually returned.
  // ---------------------------------------------------------------------------
  const GATE_PRE = 0xa0c000 + 0x13760;
  const ARROW_LO = VA(0x8c0a2c), ARROW_HI = VA(0x8c4df4);
  const BTN_MENU = VA(0x7b1804), BTN_COMMLINK = VA(0x7b2350);
  const gateSeen = new Set();
  Interceptor.attach(VA(GATE_PRE), {
    onEnter() { this.btn = this.context.esi; },
    onLeave(retval) {
      const btn = this.btn;
      let forced = "";
      if (btn.compare(ARROW_LO) >= 0 && btn.compare(ARROW_HI) < 0) {
        retval.replace(ptr(1)); forced = " ->HIT(se-arrow)";
      } else if ((btn.equals(BTN_MENU) || btn.equals(BTN_COMMLINK)) &&
                 VA(G_FACTION_ACTIVE).readS32() === 1) {
        // v12: MISS ONLY while the SE bracket is armed — the zoom pipeline IS their
        // normal background-scaling path (v11's standing MISS left them native-small
        // on the plain HUD); the MISS only has to block the double-zoom during SE.
        retval.replace(ptr(0)); forced = " ->MISS(hud, se-armed)";
      }
      if (VA(G_FACTION_ACTIVE).readS32() === 1 && gateSeen.size < 24 && !gateSeen.has(btn.toString())) {
        gateSeen.add(btn.toString());
        log("gate btn=" + btn + " eax=" + retval.toInt32() + forced);
      }
    }
  });

  // v23: paint-time readback of the two rects (what the painters actually use).
  let painterLogs = 0;
  for (const [va, name, off] of [[0x4af1e0, "SOCIETY panel", 0x1f060], [0x4af8c0, "SPARTANS box", 0x1f2a0]]) {
    Interceptor.attach(VA(va), {
      onEnter() {
        if (g <= 16 || painterLogs >= 8) return;
        painterLogs++;
        try { log("PAINT " + name + " rect " + rd(this.context.ecx.add(off))); } catch (e) { log("PAINT log err " + e); }
      }
    });
  }

  // model_reset entry: transform once per build (gate = native opt0_0.x seed)
  Interceptor.attach(VA(0x4aece0), {
    onEnter() {
      if (g <= 16) return;
      const obj = this.context.ecx;
      if (obj.add(0x1f150).readS32() !== 0x1d) return;   // tables already scaled (or not SE build path)
      try { transform(obj); } catch (e) { log("TRANSFORM ERROR: " + e); }
    }
  });

  log("attached: build 0x4b2740 (patches), model_reset 0x4aece0 (transform), repaint 0x4b19a0 (repair); " + PATCHES.length + " patch sites");
}
