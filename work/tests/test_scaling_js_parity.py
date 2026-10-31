"""Differential: the Frida JS port must agree with the Python reference, exactly.

WHY. `scaling_laws.py` is the source of truth, but the pixels a human signs off on
are drawn by `scaling_laws.js` running inside Frida, and later by hand-written x86
in a code cave. "Source of truth" is a claim about a relationship between programs;
until something checks that relationship it is a comment, not a fact.

This test makes it a fact for the Python<->JS boundary. It drives the SAME module
the game loads (`scripts/scaling_laws.js`, via node) over the same sweep the Python
gets in `test_scaling_laws.py`, and compares every integer.

It has already earned its keep: the first run found the two ports disagreeing by one
pixel in the middle-phase clamp whenever `src == 2n` (bounds crossing: Python's
min(max(s,lo),hi) returned `hi`, the JS ternary returned `lo`). Neither was right —
there is no middle when the bands overlap — so both now reject that geometry and
fall back to the engine's renderer. Nothing on screen ever hit it; the ornate 61px
corner never draws at a 157px span. It would have hit the day someone reused the
band map for a small ornate frame, and no amount of staring at 4K would have found it.

The same rig extends to the baked asm: feed a Frida numeric snapshot of the thunk's
outputs into `compare()` against the same reference.

Skips (does not fail) when node is absent, so the suite still runs on a box without it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import (  # noqa: E402
    axis_map,
    band_widths,
    cum,
    distribute,
    half_down,
    itemlist_box_width,
    itemlist_container_edge_l,
    itemlist_container_edge_r,
    line_axis_map,
    option_row_gap,
    popup_scale_floor,
    ring_bottom,
    scale_px,
    stripe_period,
    stripe_rows,
    stripe_top,
    stroke_width,
    parity_nn_row_map,
    stripe_parity_vote,
    bases_face_h,
    bases_row_cell,
    bases_row_pitch,
    bases_face_y_imm,
    stripe_parity_vote_sums,
    bilinear_axis,
    parity_hblend_pixel,
    hatch_row_color,
    hatch_pair_for,
)

JS_MODULE = SCRIPTS / "scaling_laws.js"

# Same input space as the Python sweep. Kept in one place so the two cannot drift.
G_RANGE = list(range(16, 41))
# screens for the popup_g parity: the named ones (16:9 / 16:10 / 5:4 / 4:3 / portrait / the 4:3 ties) + a coarse grid
POPUP_G_SCREENS = ([[640, 480], [800, 600], [1024, 768], [1088, 816], [1152, 864], [1280, 720], [1280, 800],
                    [1280, 1024], [1366, 768], [1440, 900], [1600, 900], [1600, 1200], [1680, 1050], [1920, 1080],
                    [1920, 1200], [2048, 1536], [2560, 1080], [2560, 1440], [2560, 2048], [3440, 1440],
                    [3840, 2160], [5120, 2880], [7680, 4320], [768, 1024], [1080, 1920], [0, 0], [1, 1]]
                   + [[w, h] for w in range(320, 7681, 184) for h in range(240, 4321, 136)])
BAND_DEPTHS = [3, 6, 8, 44, 61]
SPANS = list(range(150, 2401, 7))


def _node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node not on PATH — JS parity unverified on this box")
    return exe


def _run_js_sweep() -> list[dict]:
    """Load the REAL prelude the game loads, sweep it, emit JSON."""
    harness = textwrap.dedent(f"""
        globalThis.globalThis = globalThis;
        require({json.dumps(str(JS_MODULE))});
        const SL = globalThis.SL;
        const G = {json.dumps(G_RANGE)};
        const NS = {json.dumps(BAND_DEPTHS)};
        const SPANS = {json.dumps(SPANS)};
        const POPUP_G_SCREENS = {json.dumps(POPUP_G_SCREENS)};
        const out = [];
        for (const g of G) for (const n of NS) for (const span of SPANS) {{
            const src = Math.max(2 * n, (span * 16 / g) | 0);
            const F = SL.axisMap(src, span, n, g);
            const m = SL.fwdMap(n, src, span, g);
            out.push({{
                g, n, span, src,
                stroke: SL.strokeWidth(g),
                B: m.B,
                widths: Array.from(m.w),
                map: F === null ? null : Array.from(F),
            }});
        }}
        // scalar laws too
        const scal = {{
            popupG: [],
            halfDown: [],
            distribute: [],
            ringBottom: [],
            scalePx: [],
            optionRowGap: [],
            itemlistBoxWidth: [],
            itemlistContainer: [],
            btnBarTileHeight: [],
            basewin: [],
            clip: [],
            scenedit: [],
            stripe: [],
            stripeLaw: [],
            bandmap: [],
            dwrows: [],
            lbres: [],
            nestpad: [],
            dwfit: [],
            lineAxis: [],
            scaleFloor: [],
            vehSizeScaled: [],
            tech: [],
            parityNn: [],
            vote: [],
            basesRow: [],
            voteSums: [],
            hblend: [],
            hblendPx: [],
            hatch: [],
            hatchKey: [],
        }};
        for (const g of G) for (const v of [20, 143, 146, 162]) scal.scaleFloor.push(SL.scaleFloor(v, g));
        for (const g of G) for (const v of [-17, -8, -7, -6, -4, 0, 4, 16, 20]) scal.vehSizeScaled.push(SL.vehSizeScaled(v, g));
        // SELECT RESEARCH GOAL (tech_pick) laws: layout / cell rects / hit-test / icon / caption
        for (const g of G) for (const [sw, sh] of [[1024,768],[1920,1080],[1600,1200],[3840,2160],[800,600]])
            for (const n of [1, 2, 3, 4, 7, 8, 9, 12, 16, 25, 40]) {{
                const lay = SL.techLayout(sw, sh, n, g);
                const cap = SL.techCaptionRects(lay, g);
                scal.tech.push({{
                    g, sw, sh, n, lay,
                    cells: [0, 1, n - 1].map(i => SL.techCellRect(i, lay, g)),
                    hits: [[0, 0], [lay.cw + 5, lay.caption + 5], [lay.W - 2, lay.H - 2], [-1, 40]]
                          .map(p => SL.techHitIndex(p[0], p[1], lay, g)),
                    icon: SL.techIconClass(lay.cw, g),
                    ratio: SL.techIconRatio(SL.techIconClass(lay.cw, g), g),
                    iconW: SL.techIconW(SL.techIconClass(lay.cw, g), g),
                    imms: SL.techIconImms(g),
                    v2: [SL.techCellInsetRb(g), SL.techStripHImm(g), SL.techChannels(g),
                         [16, 20, 22, 24].map(c => SL.techFontCell(c, g))],
                    fonts: [14, 18, 20, 10, 12].map(v => SL.techFontSize(v, g)),
                    strip: cap.strip, text: cap.text, backdrop: cap.backdrop,
                }});
            }}
        for (const g of G) for (const rc of [[67, 245, 330, 472], [0, 0, 105, 91], [877, 715, 1140, 942]])
            scal.bandmap.push(SL.bandmapRectFromHalfOpen(rc[0], rc[1], rc[2], rc[3], g));
        for (const g of G) scal.nestpad.push(SL.nestedFramePad(g));
        for (const g of G) scal.lbres.push([SL.listboxBarReserve(20, g), SL.listboxBarReserve(20, g, false), SL.listboxDialogWidth(825, 20, g)]);
        for (const g of G) for (const lr of [[0, 623], [200, 823], [1188, 2745], [668, 1626], [386, 1225]])
            {{ const r = SL.dwButtonRows(lr[0], lr[1], g); scal.dwrows.push([r.cell, r.channel].concat(r.lower.flat(), r.upper.flat())); }}
        for (const g of G) for (const bb of [[458, 420, 616, 555], [461, 390, 582, 552], [452, 447, 574, 566], [491, 493, 531, 535], [300, 300, 724, 724], [0, 0, 1024, 1024], [510, 510, 514, 514]])
            {{ const p = SL.dwFitPlan(bb, 1024, g); scal.dwfit.push([p.mode, p.W, p.k]); }}
        // scanline stripe law: period + top-member phase over a 3-period window
        for (const g of G) {{
            scal.stripe.push(SL.stripePeriod(g, 0));
            for (let y = 0; y < 30; y++) scal.stripe.push(SL.stripeTop(y, g, 0) ? 1 : 0);
        }}
        // stripe_rows / stripe_period / stripe_top over the unclamped nums too (Monument / Hall of Fame
        // reach 72) and the one-shot override (g_rm_povr), the laws the hooks call instead of (g+4)>>3
        for (let g = 1; g <= 96; g++) for (const ov of [0, 2, 6]) {{
            const row = [SL.stripeRows(g), SL.stripePeriod(g, ov)];
            for (let y = 0; y < 24; y++) row.push(SL.stripeTop(y, g, ov) ? 1 : 0);
            scal.stripeLaw.push(row);
        }}
        // line-pinned full-axis enlarge (deswin.pcx rows / cols at both width laws)
        for (const g of G) for (const [src, lines] of [[368, [0, 4, 94, 98, 188, 192, 282]], [623, [23, 27, 131, 135, 455, 459, 563, 567]], [12, [0, 11]]])
            for (const dst of [SL.scalePx(src, g), Math.ceil(src * g / 16)]) {{
                const F = SL.lineAxisMap(src, dst, lines, g);
                scal.lineAxis.push(F === null ? null : Array.from(F));
            }}
        for (const g of G) {{
            scal.scenedit.push(SL.editorPanelSeeds(g));
            scal.scenedit.push(SL.diploEditorLayout(g));
        }}
        for (let b = 1; b < 40; b++) for (let a = 0; a < 60; a++) scal.halfDown.push(SL.halfDown(a, b));
        for (const g of G) for (const v of [1, 2, 3, 19, 20, 22, 47]) scal.scalePx.push(SL.scalePx(v, g));
        // the QUIT type-16 row gap, over the same vanilla geometry the thunk uses
        for (const g of G) scal.optionRowGap.push(SL.optionRowGap(22, SL.scalePx(20, g), g));
        // the type-1 checkbox box width (Customize Game Rules), mixed-space tw
        for (const g of G) for (const [xs, text] of [[660, 356], [660, 900], [300, 356]]) {{
            const dev = Math.max(xs, SL.popupPad(text, g));
            scal.itemlistBoxWidth.push(SL.itemlistBoxWidth(xs, dev, 22, g));
        }}
        // the type-2/4 container ring edges (title-stash-derived) + the type-1 hug ring
        for (const g of G) {{
            scal.itemlistContainer.push(SL.itemlistContainerEdgeL(65, g));
            scal.itemlistContainer.push(SL.itemlistContainerEdgeR(1932, g));
        }}
        for (const g of G) for (const [dl, dt, dr, db] of [[10, 52, 667, 448], [33, 59, 690, 470], [25, 95, 1667, 887], [82, 117, 1724, 909]]) {{
            scal.itemlistContainer.push(...SL.itemlistRingHug(dl, dt, dr, db, g));
        }}
        // devfill dither re-tile height cap over both window classes (22- and 20-native)
        for (const g of G) for (const nat of [20, 22]) {{
            const orig = SL.scalePx(nat, g);
            scal.btnBarTileHeight.push(SL.btnBarTileHeight(orig, SL.btnNativeDim(orig, g), 20));
        }}
        // BaseWin true re-layout laws (window + interior boundary + font + sprite)
        for (const g of G) {{
            for (const [sw, sh, strip] of [[1024,768,213],[1920,1080,292],[1600,1200,332],[3840,2160,532]])
                scal.basewin.push(SL.basewinWindowRect(sw, sh, strip, g));
            for (const v of [-2000, -16, -1, 0, 7, 89, 234, 401, 490, 758])
                scal.basewin.push(SL.basewinPt(v, g));
            for (const s of [10, 12, 14]) scal.basewin.push(SL.basewinFontSize(s, g));
            for (const [n, d] of [[1,1],[1,2],[3,1]]) scal.basewin.push(SL.basewinSpriteRatio(n, d, g));
            for (const x of [0, 23, 199, 473, 1183, 1857]) scal.basewin.push(SL.basewinPenDescale(x, g));
            for (const [n, d] of [[-1,-1],[0,7],[1,1],[2,3]]) scal.basewin.push(SL.basewinFarmZoom(n, d, g));
            for (const raw of [51, 126]) scal.basewin.push(SL.basewinFarmSeed(70, 20, 540, raw, g));
        }}
        // chrome-pipeline clip laws (ENERGY-band eraser class)
        {{
            const CLIPS = [[415,650,1747,872],[0,0,1895,1225],[50,50,50,50],[100,200,900,800]];
            const BLITS = [[57,0,1700,1010],[415,0,100,650],[414,649,2,2],[0,0,2000,2000],
                           [150,250,100,100],[890,790,50,50],[57,0,1700,1222]];
            for (const c of CLIPS) for (const [dx,dy,w,h] of BLITS) {{
                scal.clip.push(SL.blitClipVisible(dx, dy, w, h, c));
                scal.clip.push(SL.blitClipContains(dx, dy, w, h, c));
                scal.clip.push(SL.remapClipBounds(dx, dy, w, h, 1895, 1225, c));
            }}
            for (const g of G) for (const [hh, aa] of [[1225,529],[984,529],[490,529],[530,529]])
                scal.clip.push(SL.consoleRailArm(hh, aa, g));
            for (const g of G) for (const [ww, off] of [[758,23],[758,15],[640,23],[754,8]]) {{
                const wd = Math.floor(ww * g / 16);
                scal.clip.push(SL.railRightAnchor(wd, wd - off, g));
            }}
            for (const raw of [0, 9999, 10000, 20000, 49999, 50000, 59999, 60000, 10000000])
                scal.clip.push(SL.popupFrameRewriteApplies(raw));
            for (const raw of [0, 9999, 20000, 25000, 30000, 50000, 60000, 65000, 70000])
                for (const dlg of [-1, 8])
                    for (const [bh, art, ti] of [[0, 0, 1], [120, 0, 1], [0, 5, 1], [0, 0, 0]])
                        scal.clip.push(SL.ornatePickerTakesContainerArm(raw, dlg, bh, art, ti));
            for (const g of G) scal.clip.push(SL.ornateTitleInsetDelta(g));
            for (const g of G) {{
                scal.clip.push(SL.ornateTitleOuterBottom(13, g));
                scal.clip.push(SL.ornateDialogChildX(16 + (g > 16 ? g - 16 + 3 : 3), g));
                scal.clip.push(SL.ornateContainerEdgeL(65, g));
                scal.clip.push(SL.ornateContainerEdgeR(1932, g));
            }}
        }}
        for (const n of [1, 2, 3, 6, 7, 12, 44, 61]) for (const t of [0, 1, 5, 130, 133, 203, 977, 2400])
            scal.distribute.push(Array.from(SL.distribute(t, n)));
        for (const [su, pitch] of [[1.0, 19], [1.40625, 26], [1.5625, 29], [2.5, 47]])
            scal.ringBottom.push(SL.ringBottom(Math.round(su * 131), 3, 7, pitch, su));
        // parity-preserving NN enlarge (console icon family)
        for (const g of G) for (const sh of [1, 2, 3, 5, 12, 29, 35, 38, 70]) for (const y0 of [0, 1, 2, 5]) for (const top of [-1, 0, 1])
            scal.parityNn.push(SL.parityNnRowMap(Math.floor(sh * g / 16), sh, y0, g, top));
        for (const v of [[22, 50, 60, 120], [153, 140, 315, 357], [100, 102, 200, 260], [100, 101, 200, 201], [10, 10, 30, 30]])
            scal.vote.push(SL.stripeParityVote(v[0], v[1], v[2], v[3]));
        for (const g of G) scal.basesRow.push([SL.basesFaceH(g), SL.basesRowCell(g), SL.basesRowPitch(g), SL.basesFaceYImm(g)]);
        for (const v of [[220, 10, 500, 10, 600, 1200], [1530, 10, 1400, 10, 3150, 3570], [1000, 10, 1020, 10, 2000, 2600], [1000, 10, 1010, 10, 2000, 2010], [0, 0, 5, 1, 0, 0], [7, 3, 9, 3, 20, 30]])
            scal.voteSums.push(SL.stripeParityVoteSums(v[0], v[1], v[2], v[3], v[4], v[5]));
        // console icon v2 columns + mate-keyed hatch pairs (2026-09-12)
        for (const g of G) for (const src of [1, 2, 3, 29, 35, 115]) {{
            const n = Math.floor(src * g / 16);
            for (let d = 0; d < n; d++) scal.hblend.push(SL.bilinearAxis(d, g, 16, src));
        }}
        const TAB = []; for (let i = 0; i < 256; i++) TAB.push([(i * 37) & 255, (i * 91) & 255, (i * 53) & 255]);
        for (const t0 of [9, 10, 0xE6, 0xBB]) for (const t1 of [9, 10, 0xBB, 0x37]) for (const f of [0, 77, 128, 200, 255]) for (const tn of [t0, t1])
            scal.hblendPx.push(SL.parityHblendPixel(t0, t1, f, tn, TAB, 9));
        for (const g of G) for (let y = 0; y < 12; y++) scal.hatch.push([SL.hatchRowColor(0x54, y, g), SL.hatchRowColor(0xC2, y, g)]);
        for (const c of [{{0xC2: 256, 0x41: 256}}, {{0x54: 256, 0x41: 256}}, {{0xC2: 256, 0xC5: 256}}, {{0xC2: 512}}, {{0x41: 512}}, {{0x54: 33, 0x41: 33}}, {{0x54: 32, 0x41: 33}}])
            scal.hatchKey.push(SL.hatchPairFor(c, 64));
        // the g a W x H screen runs at (scaling_laws.popup_g / scale_uniform)
        for (const [w, h] of POPUP_G_SCREENS) scal.popupG.push([SL.popupG(w, h), SL.scaleUniform(16, w, h), SL.scaleUniform(213, w, h)]);
        // JSON Lines into a TEMP FILE (path = argv[1]), one frame per line +
        // a final SCALARS line. Two transport pathologies on this box
        // (2026-07-19, 256GB RAM so not OOM): (a) a single ~200MB
        // JSON.stringify payload reproducibly ACCESS-VIOLATES CPython 3.12's
        // C json scanner; (b) the ~200MB stdout pipe capture corrupts a line
        // NON-deterministically (~1 in 40k, different line each run). Small
        // per-line parses from a real file avoid both. Same data, same shapes.
        const fs = require("fs");
        const fd = fs.openSync(process.argv[1], "w");
        for (const f of out) fs.writeSync(fd, JSON.stringify(f) + "\\n");
        fs.writeSync(fd, "SCALARS " + JSON.stringify(scal) + "\\n");
        fs.closeSync(fd);
    """)
    last_err = None
    for _attempt in range(3):  # retries: BOTH transport pathologies are transient —
        # the corrupted line above AND a silent node death (rc!=0, EMPTY stderr,
        # reproduced 2026-08-08: 3 back-to-back sweeps gave OK/crash/crash while
        # bare `node -e` stayed stable; same ~200MB-write class as the others).
        # A REAL harness error (bad JS, missing export) prints to stderr and
        # still fails fast below.
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="sl_sweep_")
        os.close(fd)
        try:
            proc = subprocess.run([_node(), "-e", harness, path],
                                  capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                if not proc.stderr:
                    last_err = f"node died rc={proc.returncode} with empty stderr"
                    continue
                pytest.fail(f"node harness failed:\n{proc.stderr[:2000]}")
            frames: list = []
            scalars = None
            try:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("SCALARS "):
                            scalars = json.loads(line[len("SCALARS "):])
                        else:
                            frames.append(json.loads(line))
            except json.JSONDecodeError as e:
                last_err = e
                continue
            assert scalars is not None, "harness emitted no SCALARS line"
            return {"frames": frames, "scalars": scalars}
        finally:
            os.unlink(path)
    pytest.fail(f"JS sweep transport failed 3 attempts in a row: {last_err}")


@pytest.fixture(scope="module")
def js():
    if not JS_MODULE.exists():
        pytest.skip("scripts/scaling_laws.js missing")
    return _run_js_sweep()


def test_js_module_is_the_one_the_hooks_load():
    """Guard against the test validating a copy while the game runs something else."""
    assert JS_MODULE.exists(), "scripts/scaling_laws.js is the prelude the hooks load"
    src = JS_MODULE.read_text(encoding="utf-8")
    assert "globalThis.SL" in src, "the prelude must publish globalThis.SL"
    for fn in ("popupG", "scaleUniform", "halfDown", "scalePx", "strokeWidth", "optionRowGap", "cum",
               "distribute", "bandWidths", "fwdMap", "axisMap", "ringBottom",
               "itemlistBoxWidth", "itemlistContainerEdgeL", "itemlistContainerEdgeR",
               "itemlistRingHug", "btnBarTileHeight",
               "basewinWindowRect", "basewinPt", "basewinFontSize",
               "basewinSpriteRatio", "basewinPenDescale", "basewinFarmZoom",
               "basewinFarmSeed", "blitClipVisible", "blitClipContains",
               "remapClipBounds", "consoleRailArm", "railRightAnchor",
               "popupFrameRewriteApplies", "ornatePickerTakesContainerArm",
               "ornateTitleInsetDelta", "ornateTitleOuterBottom",
               "ornateDialogChildX", "ornateContainerEdgeL",
               "ornateContainerEdgeR", "rowPositions", "editorPanelSeeds",
               "diploEditorLayout"):
        assert fn in src, f"scaling_laws.js is missing {fn}"


def test_hooks_do_not_carry_a_private_copy_of_the_math():
    """A private copy is how the laws diverge. Hooks must consume the prelude.

    (`hook_frame9.js` used to define its own halfDown/fwdMap/axisMap.)
    """
    offenders = []
    for hook in SCRIPTS.glob("hook_*.js"):
        text = hook.read_text(encoding="utf-8", errors="replace")
        for fn in ("function fwdMap", "function axisMap"):
            if fn in text:
                offenders.append(f"{hook.name}: defines {fn}")
        # the retired stripe period P = (g+4)>>3 (3 at g=22, 6 at g=45): call SL.stripePeriod / SL.stripeRows
        for ln, line in enumerate(text.splitlines(), 1):
            if re.search(r"\+\s*4\s*\)\s*>>\s*3", line):
                offenders.append(f"{hook.name}:{ln}: inline stripe period `(g + 4) >> 3` (use SL.stripePeriod)")
    assert not offenders, (
        "hooks must use the shared prelude (SL.*), not a private copy:\n  "
        + "\n  ".join(offenders)
    )


def test_scenedit_laws_agree(js):
    """Scenario-editor laws (2026-08-11): panel seeds + diplo modal layout."""
    from scaling_laws import diplo_editor_layout, editor_panel_seeds

    got = js["scalars"]["scenedit"]
    assert len(got) == 2 * len(G_RANGE)
    for i, g in enumerate(G_RANGE):
        jp, jd = got[2 * i], got[2 * i + 1]
        pp = editor_panel_seeds(g)
        pd = diplo_editor_layout(g)
        assert jp["pal"] == [list(r) for r in pp["pal"]], f"pal @g={g}"
        assert jp["red"] == [list(r) for r in pp["red"]], f"red @g={g}"
        assert jp["palUnion"] == list(pp["pal_union"]), f"pal_union @g={g}"
        assert jp["redUnion"] == list(pp["red_union"]), f"red_union @g={g}"
        assert (jp["infoLeft"], jp["infoTop"], jp["infoBottom"], jp["infoPad"], jp["infoStep"]) \
            == (pp["info_left"], pp["info_top"], pp["info_bottom"], pp["info_pad"],
                pp["info_step"]), f"info @g={g}"
        assert jp["cell"] == list(pp["cell"]) and jp["redCell"] == pp["red_cell"], f"cells @g={g}"
        assert (jd["W"], jd["H"]) == (pd["W"], pd["H"]), f"diplo WH @g={g}"
        assert jd["titleBand"] == list(pd["title_band"]), f"title_band @g={g}"
        assert jd["listRect"] == list(pd["list_rect"]), f"list_rect @g={g}"
        assert jd["listContent"] == list(pd["list_content"]), f"list_content @g={g}"
        assert jd["chkRect"] == list(pd["chk_rect"]), f"chk_rect @g={g}"
        assert jd["btnXs"] == list(pd["btn_xs"]), f"btn_xs @g={g}"
        assert (jd["btnW"], jd["btnY0"], jd["btnY1"]) \
            == (pd["btn_w"], pd["btn_y0"], pd["btn_y1"]), f"buttons @g={g}"
        assert (jd["fontDlg"], jd["fontTitle"]) \
            == (pd["font_dlg"], pd["font_title"]), f"fonts @g={g}"
        assert (jd["pad2"], jd["pad3"], jd["pad4"], jd["bandH"], jd["titleInset"]) \
            == (pd["pad2"], pd["pad3"], pd["pad4"], pd["band_h"], pd["title_inset"]), f"pads @g={g}"


def test_popup_g_agrees(js):
    """SL.popupG / SL.scaleUniform == scaling_laws.popup_g / scale_uniform on every screen: a hook's notion of the g
    a resolution runs at is the patcher's (the min of both axes, floored -- never a height-only private model)."""
    from scaling_laws import popup_g, scale_uniform

    want = [[popup_g(w, h), scale_uniform(16, w, h), scale_uniform(213, w, h)] for w, h in POPUP_G_SCREENS]
    assert js["scalars"]["popupG"] == want
    assert {(w, h): g for (w, h), (g, *_r) in zip(POPUP_G_SCREENS, want)
            if (w, h) in ((1280, 1024), (1600, 900), (1366, 768), (1920, 1080))} ==         {(1280, 1024): 20, (1600, 900): 18, (1366, 768): 16, (1920, 1080): 22}


def test_scalar_laws_agree(js):
    """halfDown, distribute, ringBottom — integer-for-integer."""
    py_hd = [half_down(a, b) for b in range(1, 40) for a in range(0, 60)]
    assert js["scalars"]["halfDown"] == py_hd

    py_dist = [
        list(distribute(t, n))
        for n in [1, 2, 3, 6, 7, 12, 44, 61]
        for t in [0, 1, 5, 130, 133, 203, 977, 2400]
    ]
    assert js["scalars"]["distribute"] == py_dist

    py_ring = [
        ring_bottom(round(su * 131), 3, 7, pitch, su)
        for su, pitch in [(1.0, 19), (1.40625, 26), (1.5625, 29), (2.5, 47)]
    ]
    assert js["scalars"]["ringBottom"] == py_ring

    py_spx = [scale_px(v, g) for g in G_RANGE for v in (1, 2, 3, 19, 20, 22, 47)]
    assert js["scalars"]["scalePx"] == py_spx

    # The QUIT type-16 row gap. A JS/Python split here means the Frida prototype
    # and the baked thunk would space the two Quit buttons differently.
    py_gap = [option_row_gap(22, scale_px(20, g), g) for g in G_RANGE]
    assert js["scalars"]["optionRowGap"] == py_gap

    # The scanline stripe law (period + phase). A split here means a Frida
    # restripe and the baked restripe_core would band differently at g=22/25.
    py_stripe = []
    for g in G_RANGE:
        py_stripe.append(stripe_period(g))
        py_stripe.extend(1 if stripe_top(y, g) else 0 for y in range(30))
    assert js["scalars"]["stripe"] == py_stripe

    # stripe_rows / stripe_period / stripe_top incl. the unclamped nums and the override
    py_law = []
    for g in range(1, 97):
        for ov in (0, 2, 6):
            py_law.append([stripe_rows(g), stripe_period(g, ov)] + [1 if stripe_top(y, g, ov) else 0 for y in range(24)])
    assert js["scalars"]["stripeLaw"] == py_law

    # line-pinned full-axis enlarge (Design Workshop backdrop strokes)
    py_la = []
    for g in G_RANGE:
        for src_n, lines in ((368, [0, 4, 94, 98, 188, 192, 282]), (623, [23, 27, 131, 135, 455, 459, 563, 567]), (12, [0, 11])):
            for dst in (scale_px(src_n, g), -(-src_n * g // 16)):
                py_la.append(line_axis_map(src_n, dst, lines, g))
    assert js["scalars"]["lineAxis"] == py_la

    # The FLOOR dim idiom the popup-button shrink inverts exactly (btn_native_dim).
    py_fl = [popup_scale_floor(v, g) for g in G_RANGE for v in (20, 143, 146, 162)]
    assert js["scalars"]["scaleFloor"] == py_fl

    # The unit/base icon size-index law (HQ report pages, thunk_hud_vehargs). A split here means the
    # kinds proto and the baked entry thunk would size the row icons differently.
    from scaling_laws import veh_size_scaled
    py_vs = [veh_size_scaled(v, g) for g in G_RANGE for v in (-17, -8, -7, -6, -4, 0, 4, 16, 20)]
    assert js["scalars"]["vehSizeScaled"] == py_vs

    # The type-1 checkbox box width (Customize Game Rules fix).
    py_ilb = [
        itemlist_box_width(xs, max(xs, popup_scale_floor(text, g)), 22, g)
        for g in G_RANGE
        for xs, text in [(660, 356), (660, 900), (300, 356)]
    ]
    assert js["scalars"]["itemlistBoxWidth"] == py_ilb

    # The type-2/4 container ring edges (title-stash-derived) + the type-1 hug ring (fix 16).
    from scaling_laws import itemlist_ring_hug
    py_ilc = []
    for g in G_RANGE:
        py_ilc.append(itemlist_container_edge_l(65, g))
        py_ilc.append(itemlist_container_edge_r(1932, g))
    for g in G_RANGE:
        for dl, dt, dr, db in ((10, 52, 667, 448), (33, 59, 690, 470), (25, 95, 1667, 887), (82, 117, 1724, 909)):
            py_ilc.extend(itemlist_ring_hug(dl, dt, dr, db, g))
    assert js["scalars"]["itemlistContainer"] == py_ilc

    # devfill dither re-tile height cap (picker 22-native vs popup 20-native).
    from scaling_laws import btn_bar_tile_height, btn_native_dim
    py_bth = [
        btn_bar_tile_height(scale_px(nat, g), btn_native_dim(scale_px(nat, g), g), 20)
        for g in G_RANGE
        for nat in (20, 22)
    ]
    assert js["scalars"]["btnBarTileHeight"] == py_bth

    # BaseWin re-layout laws — window rect, interior boundary, font, sprite ratio.
    from scaling_laws import (basewin_farm_seed, basewin_farm_zoom,
                              basewin_font_size, basewin_pen_descale,
                              basewin_pt, basewin_sprite_ratio,
                              basewin_window_rect)
    py_bw: list = []
    for g in G_RANGE:
        for sw, sh, strip in ((1024, 768, 213), (1920, 1080, 292),
                              (1600, 1200, 332), (3840, 2160, 532)):
            py_bw.append(list(basewin_window_rect(sw, sh, strip, g)))
        for v in (-2000, -16, -1, 0, 7, 89, 234, 401, 490, 758):
            py_bw.append(basewin_pt(v, g))
        for s in (10, 12, 14):
            py_bw.append(basewin_font_size(s, g))
        for num, den in ((1, 1), (1, 2), (3, 1)):
            py_bw.append(list(basewin_sprite_ratio(num, den, g)))
        for x in (0, 23, 199, 473, 1183, 1857):
            py_bw.append(basewin_pen_descale(x, g))
        for num, den in ((-1, -1), (0, 7), (1, 1), (2, 3)):
            py_bw.append(list(basewin_farm_zoom(num, den, g)))
        for raw in (51, 126):
            py_bw.append(list(basewin_farm_seed(70, 20, 540, raw, g)))
    assert js["scalars"]["basewin"] == py_bw

    # chrome-pipeline clip laws
    from scaling_laws import (blit_clip_contains, blit_clip_visible,
                              remap_clip_bounds)
    py_clip: list = []
    for c in ((415, 650, 1747, 872), (0, 0, 1895, 1225), (50, 50, 50, 50),
              (100, 200, 900, 800)):
        for dx, dy, w, h in ((57, 0, 1700, 1010), (415, 0, 100, 650),
                             (414, 649, 2, 2), (0, 0, 2000, 2000),
                             (150, 250, 100, 100), (890, 790, 50, 50),
                             (57, 0, 1700, 1222)):
            vis = blit_clip_visible(dx, dy, w, h, c)
            py_clip.append(list(vis) if vis is not None else None)
            py_clip.append(blit_clip_contains(dx, dy, w, h, c))
            py_clip.append(list(remap_clip_bounds(dx, dy, w, h, 1895, 1225, c)))
    from scaling_laws import console_rail_arm, rail_right_anchor
    for g in G_RANGE:
        for hh, aa in ((1225, 529), (984, 529), (490, 529), (530, 529)):
            py_clip.append(console_rail_arm(hh, aa, g))
    for g in G_RANGE:
        for ww, off in ((758, 23), (758, 15), (640, 23), (754, 8)):
            wd = ww * g // 16
            py_clip.append(rail_right_anchor(wd, wd - off, g))
    from scaling_laws import popup_frame_rewrite_applies
    for raw in (0, 9999, 10000, 20000, 49999, 50000, 59999, 60000, 10000000):
        py_clip.append(popup_frame_rewrite_applies(raw))
    from scaling_laws import ornate_picker_takes_container_arm, ornate_title_inset_delta
    for raw in (0, 9999, 20000, 25000, 30000, 50000, 60000, 65000, 70000):
        for dlg in (-1, 8):
            for bh, art, ti in ((0, 0, 1), (120, 0, 1), (0, 5, 1), (0, 0, 0)):
                py_clip.append(ornate_picker_takes_container_arm(raw, dlg, bh, art, ti))
    for g in G_RANGE:
        py_clip.append(ornate_title_inset_delta(g))
    from scaling_laws import (ornate_dialog_child_x, ornate_title_outer_bottom,
                              ornate_container_edge_l, ornate_container_edge_r)
    for g in G_RANGE:
        py_clip.append(ornate_title_outer_bottom(13, g))
        py_clip.append(ornate_dialog_child_x(16 + (g - 16 + 3 if g > 16 else 3), g))
        py_clip.append(ornate_container_edge_l(65, g))
        py_clip.append(ornate_container_edge_r(1932, g))
    assert js["scalars"]["clip"] == py_clip


def test_stroke_band_and_widths_agree(js):
    """K, B and the per-cell band widths must match at every (g, n, span)."""
    bad = []
    for e in js["frames"]:
        g, n, span, src = e["g"], e["n"], e["span"], e["src"]
        if stroke_width(g) != e["stroke"]:
            bad.append(("stroke", g, n, span))
        py_b = cum(n, span, src)
        if py_b != e["B"]:
            bad.append(("B", g, n, span, e["B"], py_b))
        py_w = list(band_widths(n, py_b, stroke_width(g))) if py_b > 0 else []
        if py_b > 0 and py_w != e["widths"]:
            bad.append(("widths", g, n, span, e["widths"], py_w))
    assert not bad, f"{len(bad)} divergences, first 5: {bad[:5]}"


def test_axis_map_agrees_everywhere(js):
    """The whole map, every index. This is the one that found the clamp bug."""
    bad = []
    for e in js["frames"]:
        g, n, span, src = e["g"], e["n"], e["span"], e["src"]
        py = axis_map(src, span, n, g)
        js_map = e["map"]
        if (py is None) != (js_map is None):
            bad.append(("nullity", g, n, span, js_map is None, py is None))
        elif py is not None and list(py) != js_map:
            i = next(k for k, (a, b) in enumerate(zip(py, js_map)) if a != b)
            bad.append(("map", g, n, span, f"idx {i}: py={py[i]} js={js_map[i]}"))
    assert not bad, f"{len(bad)} divergences, first 5: {bad[:5]}"


def test_degenerate_geometry_is_rejected_by_both(js):
    """src == 2n has no honest middle (clamp bounds cross). BOTH ports must return
    null and let the engine draw it, rather than each picking a different pixel."""
    for n in (6, 61):
        assert axis_map(2 * n, 8 * n, n, 25) is None
    seen = [e for e in js["frames"] if e["src"] == 2 * e["n"]]
    assert seen, "sweep never exercised src == 2n — the guard is untested"
    assert all(e["map"] is None for e in seen), "JS must reject src == 2n"


def test_dw_fit_plan_agrees(js):
    from scaling_laws import dw_fit_plan
    bbs = ((458, 420, 616, 555), (461, 390, 582, 552), (452, 447, 574, 566), (491, 493, 531, 535), (300, 300, 724, 724), (0, 0, 1024, 1024), (510, 510, 514, 514))
    got = js["scalars"]["dwfit"]
    assert len(got) == len(G_RANGE) * len(bbs)
    i = 0
    for g in G_RANGE:
        for bb in bbs:
            p = dw_fit_plan(bb, 1024, g)
            m, w, k = got[i]; i += 1
            assert (m, w) == (p["mode"], p["W"]), f"dwfit @g={g} bb={bb}"
            assert abs(k - p["k"]) < 1e-12, f"dwfit k @g={g} bb={bb}"


def test_nested_frame_pad_agrees(js):
    from scaling_laws import nested_frame_pad
    assert js["scalars"]["nestpad"] == [nested_frame_pad(g) for g in G_RANGE]


def test_listbox_bar_reserve_agrees(js):
    from scaling_laws import listbox_bar_reserve, listbox_dialog_width
    py = [[listbox_bar_reserve(20, g), listbox_bar_reserve(20, g, popup_active=False), listbox_dialog_width(825, 20, g)] for g in G_RANGE]
    assert js["scalars"]["lbres"] == py


def test_dw_button_rows_agrees(js):
    from scaling_laws import dw_button_rows
    lrs = ((0, 623), (200, 823), (1188, 2745), (668, 1626), (386, 1225))
    py = []
    for g in G_RANGE:
        for lr in lrs:
            r = dw_button_rows(lr[0], lr[1], g)
            py.append([r["cell"], r["channel"]] + [v for b in r["lower"] for v in b] + [v for b in r["upper"] for v in b])
    assert js["scalars"]["dwrows"] == py


def test_bandmap_rect_from_halfopen_agrees(js):
    from scaling_laws import bandmap_rect_from_halfopen
    py = [list(bandmap_rect_from_halfopen(*rc, g)) for g in G_RANGE
          for rc in ((67, 245, 330, 472), (0, 0, 105, 91), (877, 715, 1140, 942))]
    assert js["scalars"]["bandmap"] == py


def test_tech_laws_agree(js):
    """SELECT RESEARCH GOAL laws (2026-08-27): layout, cell rects, hit-test, icon
    ratio/imms, fonts, caption rects — the JS the proto hook runs vs the reference."""
    from scaling_laws import (tech_caption_rects, tech_cell_rect, tech_font_size,
                              tech_hit_index, tech_icon_class, tech_icon_imms,
                              tech_icon_ratio, tech_icon_w, tech_layout, tech_cell_inset_rb, tech_strip_h_imm,
                              tech_channels, tech_font_cell)

    got = js["scalars"]["tech"]
    assert len(got) == len(G_RANGE) * 5 * 11
    for rec in got:
        g, sw, sh, n = rec["g"], rec["sw"], rec["sh"], rec["n"]
        lay = tech_layout(sw, sh, n, g)
        jl = rec["lay"]
        assert (jl["cols"], jl["rows"], jl["cw"], jl["ch"], jl["W"], jl["H"], jl["x"], jl["y"],
                jl["pad"], jl["caption"], jl["gridTop"]) == \
            (lay["cols"], lay["rows"], lay["cw"], lay["ch"], lay["W"], lay["H"], lay["x"], lay["y"],
             lay["pad"], lay["caption"], lay["grid_top"]), f"layout @g={g} {sw}x{sh} n={n}"
        assert rec["cells"] == [list(tech_cell_rect(i, lay, g)) for i in (0, 1, n - 1)], f"cells @g={g} n={n}"
        pts = [(0, 0), (lay["cw"] + 5, lay["caption"] + 5), (lay["W"] - 2, lay["H"] - 2), (-1, 40)]
        assert rec["hits"] == [tech_hit_index(x, y, lay, g) for x, y in pts], f"hits @g={g} n={n}"
        sc = tech_icon_class(lay["cw"], g)
        assert rec["icon"] == sc and rec["ratio"] == list(tech_icon_ratio(sc, g)) \
            and rec["iconW"] == tech_icon_w(sc, g), f"icon @g={g} n={n}"
        im = tech_icon_imms(g)
        assert rec["imms"] == {"den": im["den"], "s10": im["s10"], "mask": im["mask"],
                               "add": im["add"], "shift": im["shift"]}, f"imms @g={g}"
        assert rec["fonts"] == [tech_font_size(v, g) for v in (14, 18, 20, 10, 12)], f"fonts @g={g}"
        cap = tech_caption_rects(lay, g)
        assert rec["v2"] == [tech_cell_inset_rb(g), tech_strip_h_imm(g), tech_channels(g),
                             [tech_font_cell(c, g) for c in (16, 20, 22, 24)]], f"v2 laws @g={g}"
        assert (rec["strip"], rec["text"], rec["backdrop"]) == \
            (list(cap["strip"]), list(cap["text"]), list(cap["backdrop"])), f"caption @g={g} n={n}"


def test_parity_nn_agrees(js):
    """The console icon enlarge: a JS/Python split here means the Frida prototype and the baked
    thunk would pick different native rows -> different stripe phase -> banding in one of them."""
    py = [parity_nn_row_map((sh * g) // 16, sh, y0, g, top)
          for g in G_RANGE for sh in [1, 2, 3, 5, 12, 29, 35, 38, 70] for y0 in [0, 1, 2, 5] for top in (-1, 0, 1)]
    assert js["scalars"]["parityNn"] == py
    assert js["scalars"]["vote"] == [stripe_parity_vote(*v) for v in
                                     [[22, 50, 60, 120], [153, 140, 315, 357], [100, 102, 200, 260], [100, 101, 200, 201], [10, 10, 30, 30]]]


def test_bases_row_laws_agree(js):
    py = [[bases_face_h(g), bases_row_cell(g), bases_row_pitch(g), bases_face_y_imm(g)] for g in G_RANGE]
    assert js["scalars"]["basesRow"] == py


def test_parity_hblend_and_hatch_laws_agree(js):
    """t_rwk_parity_nn v2 columns and thunk_s54_restripe v2 pairs: the Frida prototypes and the baked thunks
    must pick the same taps, the same blended index and the same keyed pair."""
    py = [list(bilinear_axis(d, g, 16, src)) for g in G_RANGE for src in [1, 2, 3, 29, 35, 115] for d in range((src * g) // 16)]
    assert js["scalars"]["hblend"] == py
    tab = [((i * 37) & 255, (i * 91) & 255, (i * 53) & 255) for i in range(256)]
    px = [parity_hblend_pixel(t0, t1, f, tn, tab, 9) for t0 in (9, 10, 0xE6, 0xBB) for t1 in (9, 10, 0xBB, 0x37)
          for f in (0, 77, 128, 200, 255) for tn in (t0, t1)]
    assert js["scalars"]["hblendPx"] == px
    assert js["scalars"]["hatch"] == [[hatch_row_color(0x54, y, g), hatch_row_color(0xC2, y, g)] for g in G_RANGE for y in range(12)]
    cases = [{0xC2: 256, 0x41: 256}, {0x54: 256, 0x41: 256}, {0xC2: 256, 0xC5: 256}, {0xC2: 512}, {0x41: 512}, {0x54: 33, 0x41: 33}, {0x54: 32, 0x41: 33}]
    assert js["scalars"]["hatchKey"] == [hatch_pair_for(c, 64) for c in cases]


def test_vote_sums_agree(js):
    vs = [[220, 10, 500, 10, 600, 1200], [1530, 10, 1400, 10, 3150, 3570], [1000, 10, 1020, 10, 2000, 2600], [1000, 10, 1010, 10, 2000, 2010], [0, 0, 5, 1, 0, 0], [7, 3, 9, 3, 20, 30]]
    assert js["scalars"]["voteSums"] == [stripe_parity_vote_sums(*v) for v in vs]
