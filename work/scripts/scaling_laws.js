"use strict";
// Shared SCALING LAWS for Frida hooks — the JS port of work/scripts/scaling_laws.py.
//
// Load BEFORE a hook script:  frida -l frida_common.js -l scaling_laws.js -l hook_*.js
// (run-frida.bat / run-frida-at-res.bat do this for you.)
//
// ┌──────────────────────────────────────────────────────────────────────────┐
// │ scaling_laws.PY IS THE SOURCE OF TRUTH. This file is a PORT of it.       │
// │ work/tests/test_scaling_js_parity.py runs BOTH over the same sweep and   │
// │ fails on any divergence. Do not "fix" a law here — fix it there, then    │
// │ port, then run:  cd work/tests && py -m pytest -k scaling -q             │
// └──────────────────────────────────────────────────────────────────────────┘
//
// Why a shared module instead of each hook rolling its own: hook_frame9.js used to
// carry a private copy of halfDown/fwdMap/axisMap. A private copy is how the stroke
// width diverged per-element in the first place, and a differential sweep found a
// real (latent) divergence in the middle-phase clamp. One implementation, one test.
//
// Everything is published on globalThis.SL so a later -l script can use it.

(function () {
  const NATIVE_G = 16;

  // round(a/b) with exact halves going DOWN. b > 0.
  // Half-DOWN, not half-up: g/16 = 2.5 at 4K and the approved stroke there is 2px.
  const halfDown = (a, b) => Math.floor((2 * a + b - 1) / (2 * b));

  // LAW 1 — the proportionate rule. `v` must be a measured VANILLA magnitude.
  const scalePx = (v, g) => halfDown(v * g, NATIVE_G);

  // The window-dim FLOOR idiom (popup_scale_floor): dev = fl(n*g/16). The popup-
  // button 2D-zoom shrink inverts it EXACTLY with ceil(dev*16/g) (btnNativeDim),
  // so any FlatButton rect dim must be produced by THIS law, never halfDown —
  // a halfDown dim can descale to n+1 (phantom transparent row/col in the face).
  const scaleFloor = (v, g) => Math.floor((v * g) / NATIVE_G);

  // THE g a W x H screen runs at (port of scaling_laws.scale_uniform / popup_g): thunk_ensure_scale stores
  // clamp(floor(16 * min(W/1024, H/768)), 16, 40) -- the MIN of both axes, FLOORED, never height-only/rounded
  // (1280x1024 = 20, 1600x900 = 18, 16:9 up to 1366 wide = 16). The cross products compare as the asm's
  // unsigned 32-bit values (a tie takes the W axis); dim * H must stay below 2^53 (true for any screen).
  const G_MIN = 16, G_MAX = 40;
  const scaleUniform = (dim, w, h) => ((Math.imul(w, 768) >>> 0) > (Math.imul(h, 1024) >>> 0))
    ? Math.floor(((dim >>> 0) * (h >>> 0)) / 768) : Math.floor(((dim >>> 0) * (w >>> 0)) / 1024);
  const popupG = (w, h) => Math.min(G_MAX, Math.max(G_MIN, scaleUniform(16, w, h)));

  // Scanline-dither stripe law (skill scaling-frames §7): a 1px-period dither is
  // never resampled; it is re-generated at device density with period
  // P = 2T, T = stripeRows(g) device rows per stripe: 1 below g = 22 (screens under 1080 px
  // high), else max(2, g >> 4) (the pictures' scanline rule); row y carries the TOP member iff
  // y mod P < hN, hN = (P+1)>>1 = T. `override` = the one-shot g_rm_povr (2 = 1px parity law).
  // Ports of scaling_laws.stripe_rows / stripe_period / stripe_top; hooks call SL.stripePeriod,
  // never an inline period formula (the retired (g+4)>>3 gives 3 at g=22 and 6 at g=45).
  const stripeRows = (g) => g < 22 ? 1 : Math.max(2, g >> 4);
  const stripePeriod = (g, override) => override ? override : 2 * stripeRows(g);
  const DITHER_FORCE_PAIRS = { 0xC4: 0x41, 0xC6: 0x41, 0xC5: 0x41, 0xBF: 0x53 };
  // pair_top: canonical TOP (wide-band) member of a detected pair — force-pair key, else higher peak channel, then sum, then lower index
  const pairTop = (a, b, rgb) => {
    for (const k of Object.keys(DITHER_FORCE_PAIRS)) { const t = parseInt(k, 10), m = DITHER_FORCE_PAIRS[k]; if ((a === t && b === m) || (a === m && b === t)) return t; }
    const ra = rgb(a), rb = rgb(b), ka = [Math.max(...ra), ra[0] + ra[1] + ra[2], -a], kb = [Math.max(...rb), rb[0] + rb[1] + rb[2], -b];
    for (let i = 0; i < 3; i++) { if (ka[i] > kb[i]) return a; if (ka[i] < kb[i]) return b; }
    return a;
  };
  const stripeTop = (y, g, override) => {
    const p = stripePeriod(g, override);
    return (y % p) < ((p + 1) >> 1);
  };

  // LAW 4 — the canonical stroke width, from the LEVER alone. Never from a frame's
  // own dst/src ratio: that ratio is span-dependent, so two frames on one screen
  // would disagree.
  const strokeWidth = (g) => halfDown(g, NATIVE_G);

  // LAWS 1+5 — inter-row gap of a scaled option list. Pin the PITCH (what positions
  // row i) to the faithful value; the gap absorbs the rounding. Scaling the gap
  // directly breaks at g=18/26/34 because bar height and gap round independently.
  const optionRowGap = (vanillaPitch, drawnRowH, g) =>
    Math.max(0, scalePx(vanillaPitch, g) - drawnRowH);

  // LAW 2 — cumulative boundary of cell i in a run of n cells spanning `total`.
  const cum = (i, total, n) => halfDown(i * total, n);

  // LAW 2 — split `total` over `n` cells, spreading the remainder.
  // sum === total exactly; no cell off the ideal by more than 1.
  function distribute(total, n) {
    const w = new Int32Array(n);
    for (let i = 0; i < n; i++) w[i] = cum(i + 1, total, n) - cum(i, total, n);
    return w;
  }

  // LAWS 2+3 — per-cell widths of a scaled 9-slice corner band.
  // Native cell 0 is the stroke and cell 1 is the 45° bevel diagonal: BOTH are
  // chrome and render at exactly k. Cells 2..n-1 are inert interior and absorb the
  // remainder. Pinning only cell 0 gave the bevel half the stroke's weight at g=25
  // ("corners too small at 1600") and double at g=22 ("too large at 1920").
  function bandWidths(n, bandPx, k) {
    if (n <= 2 || bandPx < 2 * k) return distribute(bandPx, n);
    const w = new Int32Array(n);
    w[0] = k; w[1] = k;
    const rem = bandPx - 2 * k, m = n - 2;
    const inner = distribute(rem, m);
    for (let y = 0; y < m; y++) w[y + 2] = inner[y];
    return w;
  }

  const fwdCache = Object.create(null);

  // Native band index -> dest offset, plus the band depth B and stroke K.
  function fwdMap(n, srcN, DW, g) {
    const key = n + "|" + srcN + "|" + DW + "|" + g;
    const hit = fwdCache[key];
    if (hit) return hit;
    const B = cum(n, DW, srcN), K = strokeWidth(g);
    const w = bandWidths(n, B, K);
    const f = new Int32Array(Math.max(B, 0));
    let j = 0;
    for (let y = 0; y < n; y++) for (let c = 0; c < w[y] && j < B; c++) f[j++] = y;
    return (fwdCache[key] = { B: B, f: f, w: w, stroke: K });
  }

  // LAWS 2+3+4 — dest index -> src index for one axis of a 9-slice enlarge.
  //
  // Near band and far band carry identical widths, each anchored to its OWN outer
  // edge, so opposite strokes quantize identically (that is the 2-vs-3px wobble,
  // gone). The middle keeps the ENGINE's own NN phase floor(j*srcN/DW): resampling
  // it on a different phase re-picks which source rows duplicate, which is banding.
  //
  // Returns null when the geometry cannot support two bands AND a middle
  // (srcN >= 2n+1). At srcN == 2n the clamp bounds cross and there is no honest
  // answer — fall back to the engine's renderer rather than draw something wrong.
  function axisMap(srcN, DW, n, g) {
    if (n <= 0 || srcN < 2 * n + 1) return null;
    const m = fwdMap(n, srcN, DW, g);
    const B = m.B, f = m.f;
    if (B <= 0 || DW < 2 * B) return null;

    const lo = n, hi = srcN - 1 - n;          // guaranteed lo <= hi by the guard above
    const F = new Int32Array(DW);
    for (let j = 0; j < DW; j++) {
      if (j < B) F[j] = f[j];                                  // near band
      else if (j >= DW - B) F[j] = (srcN - 1) - f[DW - 1 - j]; // far band, mirrored
      else {
        const s = Math.floor((j * srcN) / DW);                 // engine's own NN phase
        F[j] = s < lo ? lo : (s > hi ? hi : s);
      }
    }
    return F;
  }

  // LAWS 2+3 — full-axis enlarge of a pre-rendered art plane (deswin.pcx): every
  // MEASURED line index renders at exactly K, the field absorbs the remainder via
  // distribute(). Port of scaling_laws.line_axis_map (see there for the why).
  function lineAxisMap(srcN, DW, lines, g) {
    if (srcN <= 0 || DW < srcN) return null;
    const K = strokeWidth(g);
    const isLine = new Uint8Array(srcN);
    let nL = 0;
    for (const i of lines) if (i >= 0 && i < srcN && !isLine[i]) { isLine[i] = 1; nL++; }
    const nF = srcN - nL, rem = DW - nL * K;
    let field = null;
    if (nF === 0) { if (rem !== 0) return null; }
    else { if (rem < nF) return null; field = distribute(rem, nF); }
    const F = new Int32Array(DW);
    let j = 0, fi = 0;
    for (let i = 0; i < srcN; i++) {
      const w = isLine[i] ? K : field[fi++];
      for (let c = 0; c < w; c++) F[j++] = i;
    }
    return F;
  }

  // LAW 5 — a chrome rect's far edge, derived from the CONTENT it wraps.
  // ringBottom = rowsTop + rows*pitch, NOT scale*(nativeB + inset). At g=16 this
  // collapses to vanilla's own arithmetic, making the native no-op ALGEBRAIC.
  function ringBottom(ringTop, inset, rows, pitch, scale) {
    return ringTop + Math.round(scale * inset) + rows * pitch;
  }

  // ---- TutWin directional tooltips (ports of scaling_laws.py; see there) ----
  // pf-chain constants (mirror the baked pf-align asm):
  const frameGrowDelta = (g) => Math.max(0, (g - NATIVE_G) >> 3);
  // 2026-09-18: the POPUP title pair draws FLAT (thunk_box_thick_flat) -- port of title_grow_delta.
  // frameGrowDelta stays for thunk_box_thick's one remaining user (the diplomacy talk title).
  const titleGrowDelta = (g) => 0;
  const popupPad = (v, g) => Math.floor((v * g) / NATIVE_G);
  const TUTWIN_RING_INSET = 13, TUTWIN_CONTENT_TOP = 27;
  // synthetic pf-align title stash for the title-less TutWin
  const tutwinStashLeft = (g) => scalePx(TUTWIN_RING_INSET, g) + titleGrowDelta(g);
  const tutwinStashRight = (windowW, g) => windowW - scalePx(TUTWIN_RING_INSET, g) - titleGrowDelta(g);
  const tutwinContentTop = (g) => scalePx(TUTWIN_CONTENT_TOP, g);
  // inverse of the window-dim FLOOR scale for the popup-button 2D-zoom shrink
  // (v2 2026-07-21e: CEIL — the exact inverse of dev = floor(n*g/16); v1's
  // round under-recovered when (n*g % 16)/g > 1/2, see py docstring)
  const btnNativeDim = (scaled, g) => Math.floor((scaled * NATIVE_G + g - 1) / g);
  // devfill dither re-tile height cap: the zoom's OWN mapping of the art bottom -- the device rows the
  // centre-sampled NN maps to an art row (v2 2026-10-24; top-anchored 20-row art; identity whenever artH >= nativeH)
  const btnBarTileHeight = (origHAbs, nativeH, artH) =>
    nativeH <= 0 ? origHAbs : Math.min(origHAbs, Math.floor((2 * artH * origHAbs + nativeH - 1) / (2 * nativeH)));

  // LAW 1 on the type-1 (checkbox #itemlist) popup box width (thunk_scale_boxw v4
  // arm). measuredDev ([+iv3+0x222c]) is a MIXED-space max(native xs, device text):
  // compare in ONE space instead of rescaling it wholesale (that double-scales the
  // text term — Customize Game Rules 2280 vs faithful 1705 @4K). Floor idiom
  // (popupPad) matching the baked v3 family. Identity at g<=16 is algebraic:
  // fonts are native there so measuredDev == the engine's own tw.
  const itemlistBoxWidth = (xs, measuredDev, trim, g) =>
    g <= NATIVE_G ? (measuredDev || xs) + trim
                  : Math.max(popupPad(xs, g), measuredDev) + popupPad(trim, g);

  // LAW 5 — the type-2/4 CONTAINER ring edges, title-stash-derived
  // (pf_union_align container arm): BOTH edges collinear with the title's
  // inner ring (see scaling_laws.py itemlist_container_edge_r).
  const itemlistContainerEdgeL = (titleOuterL, g) => titleOuterL + popupPad(3, g);
  const itemlistContainerEdgeR = (titleOuterR, g) => titleOuterR - popupPad(3, g);
  // LAW 5b — the TYPE-1 checkbox ring HUGS its list on all four sides
  // (pf_union_align v16; fix 16 l/r, fix 17 t/b): D -+ pad, far edges -1 at
  // g > 16 (the band map paints [l, r] x [t, b] inclusive), pad = fl(3g/16)
  // (3 at g <= 16: the engine's own ring).
  const itemlistRingHug = (listL, listT, listR, listB, g) => {
    const p = g <= NATIVE_G ? 3 : popupPad(3, g);
    const k = g > NATIVE_G ? 1 : 0;
    return [listL - p, listT - p, listR + p - k, listB + p - k];
  };

  // BaseWin true re-layout laws (option A; derivations in scaling_laws.py).
  // Window law: scale only the vanilla constants, keep the screen terms;
  // strip_h arrives already g-scaled (runtime g_console_strip_height).
  const BASEWIN_W = 758, BASEWIN_H = 490, BASEWIN_C = 726;
  const basewinWindowRect = (sw, sh, stripH, g) => {
    const gg = g > NATIVE_G ? g : NATIVE_G;
    const w = popupPad(BASEWIN_W, gg), h = popupPad(BASEWIN_H, gg);
    const x = Math.floor((sw - popupPad(BASEWIN_C, gg)) / 2);
    return [x, (sh - stripH) - h, w, h];
  };
  // Interior consumer-boundary law: floor(v*g/16) at the primitive entry,
  // each RECT edge independently (cum-position form; edges stay flush).
  const basewinPt = (v, g) => (g > NATIVE_G ? Math.floor((v * g) / NATIVE_G) : v);
  const basewinFontSize = (native, g) => (g > NATIVE_G ? popupPad(native, g) : native);
  const basewinSpriteRatio = (num, den, g) =>
    g > NATIVE_G ? [num * g, den * NATIVE_G] : [num, den];
  // Pen-return law: text writers return the advanced pen x in DEVICE space;
  // the EXT bracket descales it so chained writes re-enter native math.
  const basewinPenDescale = (xDev, g) =>
    g > NATIVE_G ? Math.floor((xDev * NATIVE_G) / g) : xDev;
  // Farm-view zoom law: compose the engine's own zoom fraction; num<=0 is
  // the -1 'unset' sentinel and normalizes to 1/1 first.
  const basewinFarmZoom = (num, den, g) => {
    if (g <= NATIVE_G) return [num, den];
    if (num <= 0) { num = 1; den = 1; }
    return [num * g, den * NATIVE_G];
  };
  // Farm-view seed law (draw_farm 0x40F21B block); raw arrives already
  // device-scaled via basewinFarmZoom when armed.
  const basewinFarmSeed = (x0, y0, x1, raw, g) => {
    const step2 = (raw >> 2) * 2;
    if (g <= NATIVE_G)
      return [step2, Math.floor((x1 - x0) / 2) - 2 * step2 + x0, 3 * step2 + 4 + y0];
    const x0d = basewinPt(x0, g), x1d = basewinPt(x1, g), y0d = basewinPt(y0, g);
    return [step2, Math.floor((x1d - x0d) / 2) - 2 * step2 + x0d,
            3 * step2 + (g >> 2) + y0d];
  };

  // Chrome-pipeline clip laws (ENERGY-band eraser class) — see scaling_laws.py.
  const blitClipVisible = (dx, dy, w, h, clip) => {
    const [l, t, r, b] = clip;
    const vx0 = Math.max(dx, l), vy0 = Math.max(dy, t);
    const vx1 = Math.min(dx + w, r), vy1 = Math.min(dy + h, b);
    if (vx0 >= vx1 || vy0 >= vy1) return null;
    return [vx0, vy0, vx1, vy1];
  };
  const blitClipContains = (dx, dy, w, h, clip) => {
    const [l, t, r, b] = clip;
    return dx >= l && dy >= t && dx + w <= r && dy + h <= b;
  };
  const remapClipBounds = (x, y, w, h, bufW, bufH, clip) => {
    const [l, t, r, b] = clip;
    return [Math.max(x, 0, l), Math.min(x + w, bufW, r),
            Math.max(y, 0, t), Math.min(y + h, bufH, b)];
  };

  // Console side-rail laws (slide_show chrome generalization) — see scaling_laws.py.
  const consoleRailArm = (destHAbs, artH, g) => g > NATIVE_G && destHAbs > artH;
  const railRightAnchor = (winWDev, xDev, g) =>
    Math.floor((winWDev * 16) / g) - (winWDev - xDev);

  // pf-align popup-type gate (v8) — see scaling_laws.py. Raw [popup+0x30ac]
  // = popup_type * 10000; only flat (0) and slide (5) take the rewrite.
  const popupFrameRewriteApplies = (raw30ac) =>
    (raw30ac >= 0 && raw30ac < 10000) || (raw30ac >= 50000 && raw30ac < 60000);

  // v9 ornate picker arm — see scaling_laws.py. Type 2/6 with a live dialog,
  // no body box, no art, and a title take the container rewrite instead.
  const ornatePickerTakesContainerArm = (raw30ac, dlgType, bodyH, art, title) =>
    ((raw30ac >= 20000 && raw30ac < 30000) ||
     (raw30ac >= 60000 && raw30ac < 70000)) &&
    dlgType !== -1 && bodyH === 0 && art === 0 && title !== 0;

  // Ornate title-box inset correction — see scaling_laws.py. Vanilla insets
  // the 6/2 title 13 native px from the window edge (l/t/r); shift by the
  // scaled difference. Identity at g<=16.
  const ornateTitleInsetDelta = (g) => ((13 * g) >> 4) - 13;
  // Faithful ornate title outer bottom (vanilla win+37; t_engine = win+13).
  const ornateTitleOuterBottom = (tEngine, g) => tEngine + ((37 * g) >> 4) - 13;
  // Ornate dialog child-x correction: the engine's s(16)+3 -> fl(19g/16).
  const ornateDialogChildX = (x, g) =>
    g <= NATIVE_G ? x : x + popupPad(3, g) - 3;
  // Ornate container-frame edges: the ornate title strokes render GROWN by
  // frameGrowDelta (thunk_box_thick), the container draws FLAT -> flush
  // against the DRAWN inner needs -+delta on top of the type-1/2/4 arm.
  const ornateContainerEdgeL = (stashL, g) =>
    itemlistContainerEdgeL(stashL, g) - titleGrowDelta(g);
  const ornateContainerEdgeR = (stashR, g) =>
    itemlistContainerEdgeR(stashR, g) + titleGrowDelta(g);

  // LAW 2 applied to a repeated stride: row i lands at its faithful rounded
  // position (port of scaling_laws.row_positions).
  function rowPositions(top, nativePitch, count, g) {
    const total = halfDown(count * nativePitch * g, NATIVE_G);
    const out = [];
    for (let i = 0; i < count; i++) out.push(top + cum(i, total, count));
    return out;
  }

  // ==== SCENARIO EDITOR (2026-08-11 arc) — ports of editor_panel_seeds /
  // diplo_editor_layout. scaling_laws.py carries the evidence + doctrine.
  function editorPanelSeeds(g) {
    const cw = scalePx(43, g), ch = scalePx(18, g);
    const colx = [], rowy = [];
    for (let i = 0; i < 5; i++) colx.push(scalePx(269 + i * 44, g));
    for (let i = 0; i < 5; i++) rowy.push(scalePx(72 + i * 19, g));
    const pal = [];
    for (const x of colx) for (const y of rowy) pal.push([x, y, x + cw, y + ch]);
    const rs = scalePx(24, g);
    // editor_red_chain_delta: the red group chained off the palette (vanilla x0 = pal[24].R + 9 = + 3 * s(3))
    const dx = g <= 16 ? 0 : scalePx(445, g) + cw + 3 * scalePx(3, g) - scalePx(497, g);
    const rcolx = [scalePx(497, g) + dx, scalePx(497 + 25, g) + dx];
    const rrowy = [scalePx(82, g), scalePx(82 + 25, g), scalePx(82 + 50, g)];
    const red = [];
    for (const x of rcolx) for (const y of rrowy) red.push([x, y, x + rs, y + rs]);
    const p3 = scalePx(3, g);
    const palUnion = [pal[0][0] - p3, pal[0][1] - p3,
                      pal[24][2] + p3, pal[24][3] + p3];
    const redUnion = [red[0][0] - p3, red[0][1] - p3,
                      red[5][2] + p3, red[5][3] + p3];
    return {
      pal: pal, red: red, palUnion: palUnion, redUnion: redUnion,
      infoLeft: redUnion[2] + p3, infoTop: redUnion[1], infoBottom: redUnion[3],
      infoPad: scalePx(4, g), infoStep: scalePx(13, g), cell: [cw, ch], redCell: rs,
    };
  }

  function diploEditorLayout(g) {
    const W = scalePx(758, g), H = scalePx(398, g);
    const i2 = scalePx(2, g), i3 = scalePx(3, g), i4 = scalePx(4, g);
    const top = scalePx(31, g), bot = scalePx(370, g);
    const bandH = scalePx(20, g);
    const third = Math.floor(W / 3), half = Math.floor(W / 2);
    const left = i4, right = W - i4;
    const span = right - left;
    const bt = Math.floor((span + i2) / 4);
    const xs = [];
    for (let k = 0; k < 4; k++) xs.push(left + k * bt);
    return {
      W: W, H: H,
      titleBand: [i4, i4, W - i4, i4 + bandH], titleInset: i3,
      listRect: [i4, top, third - i4, bot],
      listContent: [i4 + i3, top + i3, third - i4 - i3, bot - i3],
      chkRect: [half + i4, top, 2 * half - i4, bot],
      btnXs: xs, btnW: bt - i2, btnY0: H - i4 - bandH, btnY1: H - i4,
      fontDlg: scalePx(14, g), fontTitle: scalePx(16, g),
      pad2: i2, pad3: i3, pad4: i4, bandH: bandH,
    };
  }

  // ---- SELECT RESEARCH GOAL (tech_pick / TechWin), 2026-08-27 — port of tech_* ----
  // Vanilla screen-fits the window (cw = SW/cols - 20 ...) with every interior
  // constant native; law = the same arithmetic at DEVICE density (each constant
  // scaled).  The +1 gutters (1-byte incs shared by draw, W and hit-test) stay 1.
  const TECH_COLS_TABLE = [0, 1, 2, 3, 4, 5, 3, 4, 4, 5, 5, 6, 4, 5, 5, 5, 4, 5, 6, 5,
                           5, 7, 6, 6, 6, 5, 7, 7, 7, 8, 8, 8, 8, 7, 7, 7, 8, 8, 8, 8];
  const TECH_ICON_ART = 0xD7;
  const techCols = (n) => (n < TECH_COLS_TABLE.length ? TECH_COLS_TABLE[n] : 10);
  function techLayout(screenW, screenH, n, g) {
    const s = (v) => scalePx(v, g);
    const cols = techCols(n);
    const rows = Math.floor(n / cols) + (n % cols ? 1 : 0);
    let cw = n <= 8 ? Math.floor(screenW / cols) - s(0x14) : Math.floor((screenW - s(0x14)) / cols);
    cw = Math.min(cw, Math.floor(screenW / 3));
    let ch = Math.floor((cw * 3) / 2);
    ch = Math.max(ch, Math.floor(screenH / 2));
    if (ch * rows + s(0x1D) > screenH)
      ch = n <= 8 ? Math.floor(screenH / rows) - s(0x28) : Math.floor((screenH - s(0x45)) / rows);
    const W = (cw + 1) * cols + 1, H = (ch + 1) * rows + s(0x1E);
    return { cols, rows, cw, ch, W, H, x: Math.floor((screenW - W) / 2), y: Math.floor((screenH - H) / 2),
             pad: s(10), caption: s(0x1D), gridTop: s(0x1E) };
  }
  function techCellRect(idx, lay, g) {
    const s = (v) => scalePx(v, g);
    const col = idx % lay.cols, row = Math.floor(idx / lay.cols);
    const cRb = techCellInsetRb(g);
    let l = col * (lay.cw + 1) + 1, r = l + lay.cw - cRb;
    let t = row * (lay.ch + 1) + s(0x1E), b = t + lay.ch - cRb;
    l = Math.max(l, s(3)); r = Math.min(r, lay.W - s(3));
    t = Math.max(t, s(0x1D)); b = Math.min(b, lay.H - s(3));
    return [l, t, r, b];
  }
  function techHitIndex(x, y, lay, g) {
    y -= scalePx(0x1D, g);
    if (x < 0 || y < 0 || x >= lay.cols * (lay.cw + 1) || y >= lay.rows * (lay.ch + 1)) return -1;
    return Math.floor(y / (lay.ch + 1)) * lay.cols + Math.floor(x / (lay.cw + 1));
  }
  function techIconClass(cwDev, g) {
    if (cwDev >= scalePx(0xB4, g)) return -10;
    return cwDev <= scalePx(0x8C, g) ? -14 : -12;
  }
  const techIconRatio = (sc, g) => (g <= NATIVE_G ? [16 + sc, 16] : [(16 + sc) * g, 256]);
  function techIconW(sc, g) {
    const r = techIconRatio(sc, g);
    return Math.floor((TECH_ICON_ART * r[0]) / r[1]);
  }
  const techIconImms = (g) => (g <= NATIVE_G
    ? { den: 16, s10: -10, mask: 2, add: -14, shift: 4 }
    : { den: 256, s10: 6 * g - 16, mask: 2 * g, add: 2 * g - 16, shift: 8 });
  const techFontSize = (native, g) => scalePx(native, g);
  // v2: R/B inset absorbs the native +1 gutter (gap = s(4)); strip bottom = one cascade s(26);
  // fonts calibrated by CELL (find_font snaps to font_size_table, cap 40).
  const techCellInsetRb = (g) => scalePx(4, g) - 1;
  // Design Workshop FIT/SSAA plan from a trial bbox (target space): RADIAL constraint about the target centre.
  const DW_FIT_MARGIN = 8, DW_FIT_SLACK = 4, DW_FIT_MIN_FIT = 1.02;
  function dwFitPlan(bb, tn, g, ssaa, fit) {
    if (ssaa === undefined) ssaa = true; if (fit === undefined) fit = true;
    const c = tn / 2, need = g / 16;
    const r = Math.max(1.0, bb[2] - c, c - bb[0], bb[3] - c, c - bb[1]) + DW_FIT_SLACK;
    const kf = (c - DW_FIT_MARGIN) / r;
    let k, mode;
    if (ssaa && kf >= need) { k = Math.min(2 * need, kf); mode = "ssaa"; }
    else if (fit && kf > DW_FIT_MIN_FIT) { k = Math.min(need, kf); mode = (k >= need - 1e-9) ? "fit1:1" : "fit"; }
    else return { k: 1.0, W: tn * g / 16, mode: "nn", R: r, kf: kf };   // engine NN enlarge of a native-zoom render (tn multiple of 16)
    const w = Math.floor(tn * need / k + 0.5);
    return { k: tn * need / w, W: w, mode: mode, R: r, kf: kf };
  }
  // band-map thunks draw an INCLUSIVE footprint; a half-open engine rect gets far edges -1 (g>16 only).
  // Design Workshop modal button rows (x only): lower row on a 5-column grid, upper row rebuilt from it.
  function dwButtonRows(winL, winR, g) {
    const s3 = scalePx(3, g), x0 = winL + scalePx(0x1B, g);
    const span = (winR - scalePx(0x20, g) - scalePx(0x1B, g)) - x0 + s3;
    const cell = Math.trunc(span / 5);
    const lower = []; for (let i = 0; i < 5; i++) lower.push([x0 + i * cell, x0 + i * cell + cell - s3]);
    const xl = lower[4][0], rl = lower[4][1], pitchUp = (rl - xl) + s3;
    const apply = lower[0], retire = lower[4];
    return { cell: cell, channel: s3, lower: lower, upper: [apply, [apply[0] + pitchUp, apply[1] + pitchUp], [retire[0] - pitchUp, retire[1] - pitchUp], retire] };
  }
  const listboxBarReserve = (sbw, g, popupActive, rwInlist) => (!rwInlist && (popupActive === undefined || popupActive) && g > NATIVE_G) ? popupPad(sbw, g) : sbw;   // v2: rwInlist (HQ report console list bracket) -> raw, the writer already scaled it
  const listboxDialogWidth = (listWDev, sbw, g, popupActive) => listWDev + listboxBarReserve(sbw, g, popupActive);
  const nestedFramePad = (g) => (g <= NATIVE_G ? 3 : scalePx(2, g));
  const bandmapRectFromHalfOpen = (l, t, r, b, g) => (g <= NATIVE_G ? [l, t, r, b] : [l, t, r - 1, b - 1]);
  const techStripHImm = (g) => scalePx(26, g) - scalePx(3, g);
  const techFontCell = (nativeCell, g) => Math.floor((nativeCell * g) / 16);
  function techChannels(g) {
    const k = strokeWidth(g), c = techCellInsetRb(g);
    return { left: scalePx(3, g) - k, top: scalePx(0x1E, g) - scalePx(26, g), gap: c + 1, right: c + 1 - k, bottom: c + 1 - k };
  }
  function techCaptionRects(lay, g) {
    const s3 = scalePx(3, g);
    const strip = [s3, s3, lay.W - s3, s3 + techStripHImm(g)];
    return { strip, text: [strip[0] + s3, strip[1] + s3, strip[2] - s3, strip[3] - s3],
             backdrop: [0, 0, lay.W, lay.H] };
  }

  // Unit/base-renderer size-index law (scaling_laws.veh_size_scaled; thunk_hud_vehargs is the baked port):
  // the whole veh_draw/base_draw render derives from (s+16)/16, so s' = (((s+16)*g) >> 4) - 16 scales it
  // self-consistently. Identity at g<=16 and for |s|>16 (map callers pass real/device sizes).
  function vehSizeScaled(s, g) {
    if (g <= NATIVE_G || s < -16 || s > 16) return s;
    return (((s + 16) * g) >> 4) - 16;
  }

  // Parity-preserving NN enlarge for scanline-striped sprite art (console icon family;
  // 2026-09-09). Port of scaling_laws.parity_nn_row / nn_center_index / stripe_parity_vote.
  // Each device row takes its stripe phase from the shared grid (stripeTop) and samples a
  // native row of the matching parity; columns = crisp edge-clamped output-driven NN.
  const PARITY_MIN_DELTA = 4;
  const nnCenterIndex = (d, dst, src) => {
    if (dst <= 0 || src <= 0) return 0;
    return Math.min(Math.max(Math.floor(((2 * d + 1) * src) / (2 * dst)), 0), src - 1);
  };
  const stripeParityVote = (peakEven, peakOdd, sumEven, sumOdd) => {
    let d = peakOdd - peakEven;
    if (Math.abs(d) < PARITY_MIN_DELTA) {
      d = sumOdd - sumEven;
      if (Math.abs(d) < PARITY_MIN_DELTA) return -1;
    }
    return d > 0 ? 1 : 0;
  };
  const stripeParityVoteSums = (pe, ne, po, no, se, so) => {
    if (ne <= 0 || no <= 0) return -1;
    return stripeParityVote(Math.floor(pe / ne), Math.floor(po / no), Math.floor(se / ne), Math.floor(so / no));
  };
  const parityNnRow = (dy, dstH, srcH, yAbs, g, topParity) => {
    const n = nnCenterIndex(dy, dstH, srcH);
    if (g <= NATIVE_G || topParity < 0 || srcH < 2) return n;
    const want = stripeTop(yAbs, g) ? topParity : 1 - topParity;
    if (n % 2 === want) return n;
    const lo = n - 1, hi = n + 1;
    if (lo < 0) return hi;
    if (hi >= srcH) return lo;
    const exact2 = (2 * dy + 1) * srcH;
    const dlo = Math.abs((2 * lo + 1) * dstH - exact2), dhi = Math.abs((2 * hi + 1) * dstH - exact2);
    return dlo <= dhi ? lo : hi;
  };
  const parityNnRowMap = (dstH, srcH, y0, g, topParity) => {
    const out = [];
    for (let dy = 0; dy < dstH; dy++) out.push(parityNnRow(dy, dstH, srcH, y0 + dy, g, topParity));
    return out;
  };
  // v2 columns (t_rwk_parity_nn v2, 2026-09-12; ports of bilinear_axis / palette_nearest /
  // parity_hblend_pixel): the A5 bilinear's top-left-aligned 8.8 tap law on one axis, read INSIDE the
  // parity-selected native row; equal taps or a key tap keep the index verbatim, a glyph edge blends
  // the two palette entries and takes the nearest dest-palette index (never the key).
  const bilinearAxis = (d, num, den, src) => {
    if (num <= 0 || den <= 0 || src <= 0) return [0, 0, 0, 0];
    const dd = d * den;
    let i0 = Math.floor(dd / num);
    const rem = dd - i0 * num;
    i0 = Math.min(Math.max(i0, 0), src - 1);
    const i1 = Math.min(i0 + 1, src - 1);
    const f = Math.floor((rem * 256) / num);
    const near = 2 * rem >= num ? i1 : i0;
    return [i0, i1, f, near];
  };
  const paletteNearest = (c, table, key) => {
    let best = 0, bd = Infinity;
    for (let i = 0; i < 256; i++) {
      if (i === key) continue;
      const e = table[i];
      const d = (e[0] - c[0]) * (e[0] - c[0]) + (e[1] - c[1]) * (e[1] - c[1]) + (e[2] - c[2]) * (e[2] - c[2]);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  };
  const parityHblendPixel = (t0, t1, f, tn, table, key) => {
    if (tn === key) return null;
    if (t0 === t1) return t0;
    if (t0 === key) return t1;
    if (t1 === key) return t0;
    const a = table[t0], b = table[t1];
    const c = [0, 1, 2].map((i) => (a[i] * (256 - f) + b[i] * f + 128) >> 8);
    return paletteNearest(c, table, key);
  };
  // mate-keyed hatch pairs (thunk_s54_restripe v2: 0x54/0x41 list-family popups, 0xC2/0x41 report rows /
  // title band): both members > width/2 over the scanned rows; colored member on the top band.
  const HATCH_MATE_PAIRS = { 0x54: 0x41, 0xC2: 0x41 };
  const hatchKeyed = (countTop, countMate, width) => countTop > (width >> 1) && countMate > (width >> 1);
  const hatchPairFor = (counts, width) => {
    for (const top of [0x54, 0xC2]) {
      if (hatchKeyed(counts[top] || 0, counts[HATCH_MATE_PAIRS[top]] || 0, width)) return top;
    }
    return null;
  };
  const hatchRowColor = (top, y, g) => (stripeTop(y, g) ? top : HATCH_MATE_PAIRS[top]);


  // HQ report BASE STATUS rows: chrome follows content (port of bases_row_cell / bases_row_pitch /
  // bases_face_y_imm). cell = 2K + floor(38g/16); pitch = cell + s(2); y imm = cell - pitch/2 - K.
  const basesFaceH = (g) => Math.floor((38 * g) / NATIVE_G);
  const basesRowCell = (g) => 2 * strokeWidth(g) + basesFaceH(g);
  const basesRowPitch = (g) => basesRowCell(g) + scalePx(2, g);
  const basesFaceYImm = (g) => basesRowCell(g) - (basesRowPitch(g) >> 1) - strokeWidth(g);

  globalThis.SL = {
    NATIVE_G: NATIVE_G,
    techCols: techCols,
    techLayout: techLayout,
    techCellRect: techCellRect,
    techHitIndex: techHitIndex,
    techIconClass: techIconClass,
    techIconRatio: techIconRatio,
    techIconW: techIconW,
    techIconImms: techIconImms,
    techFontSize: techFontSize,
    techCaptionRects: techCaptionRects,
    techCellInsetRb: techCellInsetRb,
    bandmapRectFromHalfOpen: bandmapRectFromHalfOpen,
    listboxBarReserve: listboxBarReserve,
    nestedFramePad: nestedFramePad,
    listboxDialogWidth: listboxDialogWidth,
    dwButtonRows: dwButtonRows,
    dwFitPlan: dwFitPlan,
    techStripHImm: techStripHImm,
    techFontCell: techFontCell,
    techChannels: techChannels,
    halfDown: halfDown,
    scalePx: scalePx,
    strokeWidth: strokeWidth,
    scaleFloor: scaleFloor,
    scaleUniform: scaleUniform,
    popupG: popupG,
    vehSizeScaled: vehSizeScaled,
    stripeRows: stripeRows,
    stripePeriod: stripePeriod,
    stripeTop: stripeTop,
    nnCenterIndex: nnCenterIndex,
    stripeParityVote: stripeParityVote,
    stripeParityVoteSums: stripeParityVoteSums,
    parityNnRow: parityNnRow,
    parityNnRowMap: parityNnRowMap,
    bilinearAxis: bilinearAxis,
    paletteNearest: paletteNearest,
    parityHblendPixel: parityHblendPixel,
    HATCH_MATE_PAIRS: HATCH_MATE_PAIRS,
    hatchKeyed: hatchKeyed,
    hatchPairFor: hatchPairFor,
    hatchRowColor: hatchRowColor,
    basesFaceH: basesFaceH,
    basesRowCell: basesRowCell,
    basesRowPitch: basesRowPitch,
    basesFaceYImm: basesFaceYImm,
    pairTop: pairTop,
    optionRowGap: optionRowGap,
    cum: cum,
    distribute: distribute,
    bandWidths: bandWidths,
    fwdMap: fwdMap,
    axisMap: axisMap,
    lineAxisMap: lineAxisMap,
    ringBottom: ringBottom,
    frameGrowDelta: frameGrowDelta,
    titleGrowDelta: titleGrowDelta,
    popupPad: popupPad,
    tutwinStashLeft: tutwinStashLeft,
    tutwinStashRight: tutwinStashRight,
    tutwinContentTop: tutwinContentTop,
    btnNativeDim: btnNativeDim,
    btnBarTileHeight: btnBarTileHeight,
    itemlistBoxWidth: itemlistBoxWidth,
    itemlistContainerEdgeL: itemlistContainerEdgeL,
    itemlistContainerEdgeR: itemlistContainerEdgeR,
    itemlistRingHug: itemlistRingHug,
    basewinWindowRect: basewinWindowRect,
    basewinPt: basewinPt,
    basewinFontSize: basewinFontSize,
    basewinSpriteRatio: basewinSpriteRatio,
    basewinPenDescale: basewinPenDescale,
    basewinFarmZoom: basewinFarmZoom,
    basewinFarmSeed: basewinFarmSeed,
    blitClipVisible: blitClipVisible,
    blitClipContains: blitClipContains,
    remapClipBounds: remapClipBounds,
    consoleRailArm: consoleRailArm,
    railRightAnchor: railRightAnchor,
    popupFrameRewriteApplies: popupFrameRewriteApplies,
    ornatePickerTakesContainerArm: ornatePickerTakesContainerArm,
    ornateTitleInsetDelta: ornateTitleInsetDelta,
    ornateTitleOuterBottom: ornateTitleOuterBottom,
    ornateDialogChildX: ornateDialogChildX,
    ornateContainerEdgeL: ornateContainerEdgeL,
    ornateContainerEdgeR: ornateContainerEdgeR,
    rowPositions: rowPositions,
    editorPanelSeeds: editorPanelSeeds,
    diploEditorLayout: diploEditorLayout,
  };
})();
