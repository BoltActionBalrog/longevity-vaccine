"""W10S F56: the armed NON-RAIL scrollbar thunks (scripts/assemble_nonrail_sb.py) run from the BAKED bytes under Unicorn
and equal the laws in scaling_laws.py (sb_nonrail_gate / sb_nonrail_grip_rect / sb_arrow_plate / sb_nonrail_arrow v5,
centring only), at every g 17..40 and every bar class (2026-10-27; user-approved fix of a regression from vanilla).

  t_nrs_gate   ZF == sb_nonrail_gate: g > 16, a ScrollBar (the exe's vtable, or a private COPY of it as uimod.dll's
               sliders carry), not a rail-family identity -- the ProdPicker / ReportWin statics, FileDlg+0x3DD8,
               PartPicker+0xA14, Popup+0x3230 of their parents, fitted OR unfitted; every register kept
  t_nrs_grip   entered the way the game enters it (thunk_sb_thumb -> t_rsb_grip -> its non-rail tail): a gated bar's
               grip lands on sb_nonrail_grip_rect (rail_grip_span per axis, centred in the thumb rect, square for a
               square thumb), drawn mirror-exact by t_rsb_gripdraw with its pair restriped; a rail-family bar (fitted:
               t_rsb_grip's own path; unfitted) and a non-ScrollBar keep their old canvases byte for byte
  t_nrs_zoom   entered through t_rsb_zoom (its non-rail tail): a gated bar's arrow equals sb_nonrail_arrow v5 pixel
               for pixel -- the native plate square on the law span, a plain NN of it with the mirror-exact tie-break
               (mirror_nn_src via t_rsb_mnn) -- for vertical scanline plates, horizontal ones (the Prefs sliders), the
               12-px bars' solid glyphs and noise plates, every register kept; anything else (a rail arrow keeps
               t_rsb_zoom, a non-arrow, a non-ScrollBar parent, g <= 16, a non-square native, a plate left of its law
               offset) reaches thunk_btn_bandstripe with the caller's frame untouched
plus the yaml pin (the t_nrs_* entries ARE the assembler's templates, inside the W10S region; t_rsb_grip / t_rsb_zoom
carry the two retargets and nothing else changed in them) and the zoom CHAIN from W2D's t_btn_edgeprobe.
~ms per case; one Unicorn per test function, the image mapped once per module.
"""
from __future__ import annotations

import pathlib
import random
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
pytest.importorskip("keystone", reason="keystone absent")
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_nonrail_sb as NR  # noqa: E402
import assemble_rail_sym as RS  # noqa: E402
import assemble_stripes_btn as SB  # noqa: E402
import test_rail_sym_asm_parity as RT  # noqa: E402  (its Unicorn Rig and family fixture)

KEY = 9
MARKER = RT.MARKER
REGS = RT.REGS
SB_VTBL = 0x669D58
GS = list(range(17, 41))
CLASSES = ((20, 18), (12, 10), (24, 22), (16, 14))      # (vanilla bar, plate / grip sprite)


@pytest.fixture(scope="module")
def image(baked_exe):
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    symtab = ap.build_symbol_table(symbols, caves)
    pe = pefile.PE(str(baked_exe), fast_load=True)
    img = bytes(pe.get_memory_mapped_image())
    pe.close()
    return img, symtab


def _bars(rig):
    """{name: (bar, gated)} -- real ScrollBar objects (vtable 0x669D58, or a heap COPY of it like uimod.dll's sliders)
    with parents, the rail family's identities fitted AND unfitted (t_rsb_israil's fixture, now with the ScrollBar
    vtable), and objects that are not ScrollBars."""
    out = {}
    for name, (bar, _rail) in RT._family(rig).items():
        rig.w32(bar, SB_VTBL)
        family = name in ("picker", "report", "filedlg", "filedlg_unfitted", "partpicker", "partpicker_unfitted",
                          "popup", "popup_unfitted")
        out[name] = (bar, not family)              # wrong offsets / other vtables / heap bar / orphan: ScrollBars too
    copy = rig.alloc(0x200)
    rig.mu.mem_write(copy, bytes(rig.mu.mem_read(SB_VTBL, 0x170)))
    parent = rig.alloc(0x8000)
    rig.w32(parent, 0x669BE8)
    for name, vt in (("exe_vtbl", SB_VTBL), ("dll_copy", copy)):
        bar = rig.alloc(0x3000)
        rig.w32(bar, vt)
        rig.w32(bar + 0xC4, parent)
        out[name] = (bar, True)
    lone = rig.alloc(0x3000)
    rig.w32(lone, SB_VTBL)
    out["parentless"] = (lone, True)
    for name, vt in (("null_vtbl", 0), ("popup_vtbl", 0x6695C8), ("flatbutton_like", 0x669BE8)):
        o = rig.alloc(0x3000)
        rig.w32(o, vt)
        rig.w32(o + 0xC4, parent)
        out[name] = (o, False)
    return out


# ---- t_nrs_gate ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", [8, 16, 17, 22, 25, 40])
def test_gate_is_the_law(image, g):
    rig = RT.Rig(image, g)
    for name, (bar, gated) in _bars(rig).items():
        rig.run(NR.va("t_nrs_gate"), [MARKER], {UC_X86_REG_EAX: bar, UC_X86_REG_ECX: 0x55, UC_X86_REG_EDX: 0x66})
        is_sb = name not in ("null_vtbl", "popup_vtbl", "flatbutton_like")
        family = is_sb and not gated
        assert rig.zf() == SL.sb_nonrail_gate(g, is_sb, family) == (gated and g > 16), (g, name)
        assert [rig.mu.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, *REGS)] == \
            [bar, 0x55, 0x66, *REGS.values()], name


def test_gate_refuses_exactly_t_rsb_israils_identities():
    """The rail identities t_nrs_gate refuses are t_rsb_israil's, read off both assemblies (statics + parent-keyed)."""
    gate, israil = NR.assemble("t_nrs_gate"), RS.assemble("t_rsb_israil")
    for imm in (RS.PICKER_SB, RS.REPORT_SB, RS.PARTPICKER_VTBL, RS.FILEDLG_VTBL, RS.POPUP_SHOW):
        assert imm.to_bytes(4, "little") in gate and imm.to_bytes(4, "little") in israil, hex(imm)
    for off in (RS.PARTPICKER_SB, 0x3DD8, 0x3230):
        assert b"\x8D\x91" + off.to_bytes(4, "little") in gate, hex(off)       # lea edx, [ecx + bar offset]
    assert (SL.SB_ON_RESIZE, SL.SB_ON_RESIZE_SLOT) == (NR.SB_ON_RESIZE, NR.SB_ON_RESIZE_SLOT)


# ---- t_nrs_grip (through t_rsb_grip) ---------------------------------------------------------------------------------
def _grip(rig, w=18, h=18):
    """A grip sprite: key corners, F0 / B9 row dither inside, a solid 0xBD border column (the rail test's art)."""
    rows = [[0xFE if (x, y) in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)) else 0xBD if x in (0, w - 1)
             else (0xF0 if y % 2 == 0 else 0xB9) for x in range(w)] for y in range(h)]
    spr, data = rig.alloc(0x100), rig.alloc(w * h)
    rig.mu.mem_write(data, bytes(v for r in rows for v in r))
    rig.mu.mem_write(spr, bytes(0x40))
    rig.w32(spr + 4, data)
    rig.mu.mem_write(spr + 8, bytes([0xFE]))
    for off, v in ((0xC, w), (0x10, w), (0x14, h), (0x18, w), (0x1C, h)):
        rig.w32(spr + off, v)
    return spr, rows


@pytest.mark.parametrize("g", GS)
def test_grip_lands_on_the_law(image, g):
    rig = RT.Rig(image, g)
    bars = _bars(rig)
    bad = []
    for nv, sv in CLASSES:
        n = (nv * g) >> 4
        for (tw, th), (sw, sh) in (((n, n), (sv, sv)), ((n, n + 7), (sv, sv)), ((n, n), (sv, sv - 2))):
            spr, art = _grip(rig, sw, sh)
            T = 2 * g + 1
            rect = (0, T, tw, T + th)
            vx = (tw - sw) // 2 - (sw * (g - 16) >> 5)          # what thunk_sb_thumb hands its tail
            vy = T + (th - sh) // 2 - (sh * (g - 16) >> 5)
            pair = SB.sb_grip_pair(art)
            for name, (bar, gated) in bars.items():
                if name in ("picker", "report", "filedlg", "partpicker", "popup"):
                    continue                                   # fitted rail bars: t_rsb_grip's own path (W3B's test)
                planes = []
                for entry in (RS.va("t_rsb_grip"), rig.sym["t_sbt_grip"]):
                    dest, data = _buffer(rig, tw, T + th + 8, tw + 8, 0x41)
                    RT._enter_grip(rig, entry, bar, spr, dest, rect, vx, vy, g, 16)
                    planes.append(rig.plane(data, tw, T + th + 8, tw + 8))
                ours, old = planes
                if not gated:
                    if ours != old:
                        bad.append(("not gated but changed", name, nv, tw, th))
                    continue
                x, y, w, h = SL.sb_nonrail_grip_rect(rect, sw, sh, g)
                for yy in range(T + th + 8):
                    want = []
                    for xx in range(tw):
                        if x <= xx < x + w and y <= yy < y + h:
                            s = art[SL.mirror_nn_src(yy - y, sh, h)][SL.mirror_nn_src(xx - x, sw, w)]
                            want.append(0x41 if s == 0xFE else SB.sb_grip_pixel(s, yy, g, pair))
                        else:
                            want.append(0x41)
                    if list(ours[yy]) != want:
                        bad.append(("grip row", name, nv, tw, th, sw, sh, yy))
                        break
                # symmetric on both axes (the thumb rect's channels equal), and w == h for a square thumb / sprite
                if (tw - w) % 2 or (th - h) % 2 or x != (tw - w) // 2 or y - T != (th - h) // 2:
                    bad.append(("grip not centred", name, nv, (x, y, w, h)))
                if tw == th and sw == sh and w != h:
                    bad.append(("grip not square", name, nv, w, h))
    assert not bad, bad[:6]


@pytest.mark.parametrize("g", [22, 25, 40])
def test_grip_refuses_unusual_sprites_like_t_rsb_grip(image, g):
    """A gated bar with a grip that is not a plain memory sprite keeps t_sbt_grip's path (what reaches scale_nn)."""
    rig = RT.Rig(image, g)
    bar = _bars(rig)["exe_vtbl"][0]
    rig.stub(rig.sym["thunk_sprite_scale_nn"], 0x18)
    for name, spr in RT._odd_sprites(rig).items():
        seen = []
        for entry in (RS.va("t_rsb_grip"), rig.sym["t_sbt_grip"]):
            dest, _data = rig.buffer(60, 200, 64, 0x41)
            rig.hits.clear()
            RT._enter_grip(rig, entry, bar, spr, dest, (0, 40, 52, 92), 9, 50, g, 16)
            seen.append([[h[2][1] == dest] + h[2][2:7] for h in rig.hits])
        assert seen[0] == seen[1] and seen[0], (name, seen)


# ---- t_nrs_zoom (through t_rsb_zoom) ---------------------------------------------------------------------------------
def _plate(kind, f, rnd):
    """An f x f plate: 'v' rows striped (ground C5 / C2, a triangle F0 / B9 with BA edge pixels, 29 corner outline) --
    the vertical bars' arrows; 'h' the same transposed (the sliders'); 'glyph' a solid BF triangle on key with a key
    last row (the 12-px bars' arrows); 'noise' random pixels from a small palette (candidate overflow, ties)."""
    if kind == "noise":
        pal = [0x10 + i for i in range(12)] + [KEY]
        return [[rnd.choice(pal) for _ in range(f)] for _ in range(f)]
    rows = []
    for y in range(f):
        row = []
        for x in range(f):
            half = (f - 1) / 2
            depth = y - 2
            inside = depth >= 0 and abs(x - half) <= depth * 0.55 and y < f - 1
            edge = depth >= 0 and abs(abs(x - half) - depth * 0.55) < 0.6 and y < f - 1
            if kind == "glyph":
                row.append(0xBF if inside else (0xE3 if edge else KEY) if y < f - 1 else KEY)
                continue
            if (x, y) in ((0, 0), (f - 1, 0), (0, f - 1), (f - 1, f - 1)):
                row.append(KEY)
            elif x in (0, f - 1) or y in (0, f - 1):
                row.append(0x29)
            elif edge:
                row.append(0xBA)
            elif inside:
                row.append(0xF0 if y % 2 == 0 else 0xB9)
            else:
                row.append(0xC5 if y % 2 == 0 else 0xC2)
        rows.append(row)
    if kind == "h":
        rows = [list(r) for r in zip(*rows)]
    return rows


def _native(plate, wn, c0, stride):
    f = len(plate)
    rows = []
    for y in range(wn):
        row = bytearray([KEY]) * stride
        if c0 <= y < c0 + f:
            row[c0:c0 + f] = bytes(plate[y - c0])
        rows.append(bytes(row))
    return rows


def _buffer(rig, w, h, stride, fill):
    """rig.buffer, but ONE reused allocation per rig (thousands of zooms per test would exhaust the heap)."""
    if not hasattr(rig, "_zbuf"):
        rig._zbuf = (rig.alloc(0x600), rig.alloc(0x10000))
    buf, data = rig._zbuf
    assert stride * h + 64 <= 0x10000
    rig.mu.mem_write(data, bytes([fill]) * (stride * h))
    for off, v in ((0x54, data), (0x80, w), (0x84, -h), (0x4A8, stride), (0x20, 0), (0x24, 0), (0x28, w),
                   (0x2C, h), (0x30, 0), (0x34, 0), (0x38, w), (0x3C, h)):
        rig.w32(buf + off, v)
    return buf, data


def _zoom(rig, btn, native, wn, aw, stride, entry=None):
    buf, data = _buffer(rig, wn, wn, stride, 0x77)
    for y, r in enumerate(native):
        rig.mu.mem_write(data + y * stride, r)
    rig.hits.clear()
    frame = [MARKER, buf, buf, 0, 0, wn, wn, 0, 0, aw, aw, 0xFFFFFFFF]
    sp = rig.run(entry or RS.va("t_rsb_zoom"), frame, {UC_X86_REG_ESI: btn})
    assert rig.mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x2C
    return sp, frame, rig.plane(data, aw, aw, stride)


def _cases(g, rnd):
    """(kind, aw, wn, c0, f): every bar class at its scaled width, both native-dim rules (fl / ceil of aw*16/g), the
    plate centred the FlatButton way, plus off-centre starts (some bail: off < c0)."""
    out = []
    for nv, sv in CLASSES:
        aw = (nv * g) >> 4
        for wn in sorted({(aw * 16) // g, -(-aw * 16 // g)}):
            for kind in ("v", "h", "glyph", "noise"):
                out.append((kind, aw, wn, (wn - sv) // 2, sv))
            out.append(("v", aw, wn, max(0, (wn - sv) // 2 - 1), sv))
            out.append(("h", aw, wn, wn - sv, sv))
    out.append(("noise", 40, 40, 3, 30))
    return out


@pytest.mark.parametrize("g", GS)
def test_zoom_is_the_law(image, g):
    rig = RT.Rig(image, g)
    rnd = random.Random(g)
    bars = _bars(rig)
    rig.stub(rig.sym["thunk_btn_bandstripe"], 0x2C)
    bad, laid, kinds = [], 0, set()
    for kind, aw, wn, c0, f in _cases(g, rnd):
        plate = _plate(kind, f, rnd)
        stride = aw + 4
        native = _native(plate, wn, c0, stride)
        law = SL.sb_nonrail_arrow([list(r[:wn]) for r in native], wn, wn, aw, aw, g)
        for name, (bar, gated) in bars.items():
            if name in ("picker", "report", "filedlg", "partpicker", "popup"):
                continue                                         # fitted rail bars: t_rsb_zoom's own path
            for off in (RS.SB_UP, RS.SB_DN, 0x2000):
                btn = bar + off
                rig.w32(btn + 0xC4, bar)
                sp, frame, ours = _zoom(rig, btn, native, wn, aw, stride)
                if not gated or off == 0x2000 or law is None:
                    if len(rig.hits) != 1 or rig.hits[0][1] != sp or rig.hits[0][2][:12] != frame:
                        bad.append(("not forwarded intact", kind, name, hex(off), aw, wn, c0))
                    continue
                if rig.hits:
                    bad.append(("gated arrow forwarded", kind, name, aw, wn, c0))
                    continue
                laid += 1
                kinds.add(kind)
                if [list(r) for r in ours] != law:
                    bad.append(("zoom != law", kind, name, hex(off), aw, wn, c0))
                if [rig.mu.reg_read(r) for r in REGS] != list({**REGS, UC_X86_REG_ESI: btn}.values()):
                    bad.append(("registers", kind, name))
    assert laid and {"v", "h", "glyph"} <= kinds and not bad, (kinds, bad[:6])


@pytest.mark.parametrize("g", [17, 20, 22, 25, 30, 40])
def test_zoom_forwards_the_guards(image, g):
    """g <= 16 / a non-square native / a non-square dest / a sub-buffer origin / two buffers / nothing drawn ->
    thunk_btn_bandstripe with the frame untouched (and the law agrees where it is the law's refusal)."""
    rig = RT.Rig(image, g)
    bar = _bars(rig)["exe_vtbl"][0]
    btn = bar + RS.SB_UP
    rig.w32(btn + 0xC4, bar)
    rig.stub(rig.sym["thunk_btn_bandstripe"], 0x2C)
    aw = (20 * g) >> 4
    wn = (aw * 16) // g
    buf, data = rig.buffer(aw, aw, aw + 4, KEY)
    buf2, _ = rig.buffer(aw, aw, aw + 4, KEY)
    big, bigdata = rig.buffer(0x81, 0x81, 0x84, 0x40)                 # every pixel drawn: only the size refuses
    for label, frame in (("non-square native", [MARKER, buf, buf, 0, 0, wn, wn - 1, 0, 0, aw, aw, 0xFFFFFFFF]),
                         ("non-square dest", [MARKER, buf, buf, 0, 0, wn, wn, 0, 0, aw, aw - 1, 0xFFFFFFFF]),
                         ("origin", [MARKER, buf, buf, 0, 1, wn, wn, 0, 0, aw, aw, 0xFFFFFFFF]),
                         ("two buffers", [MARKER, buf, buf2, 0, 0, wn, wn, 0, 0, aw, aw, 0xFFFFFFFF]),
                         ("nothing drawn", [MARKER, buf, buf, 0, 0, wn, wn, 0, 0, aw, aw, 0xFFFFFFFF]),
                         ("over 128 px", [MARKER, big, big, 0, 0, 0x81, 0x81, 0, 0, 0x81, 0x81, 0xFFFFFFFF])):
        rig.hits.clear()
        sp = rig.run(RS.va("t_rsb_zoom"), frame, {UC_X86_REG_ESI: btn})
        assert len(rig.hits) == 1 and rig.hits[0][1] == sp and rig.hits[0][2][:12] == frame, label
    assert SL.sb_nonrail_arrow([[KEY] * wn] * wn, wn, wn, aw, aw, g) is None
    assert SL.sb_nonrail_arrow([[0x40] * 0x81] * 0x81, 0x81, 0x81, 0x81, 0x81, g) is None
    rig.set_g(16)
    rig.hits.clear()
    frame = [MARKER, buf, buf, 0, 0, 20, 20, 0, 0, 20, 20, 0xFFFFFFFF]
    sp = rig.run(RS.va("t_rsb_zoom"), frame, {UC_X86_REG_ESI: btn})
    assert len(rig.hits) == 1 and rig.hits[0][2][:12] == frame
    assert SL.sb_nonrail_arrow([[0x40] * 20] * 20, 20, 20, 20, 20, 16) is None


@pytest.mark.parametrize("g", [22, 25, 40])
def test_zoom_chain_from_the_edge_probe(image, g):
    """2dscale's zoom call enters W2D's t_btn_edgeprobe -> t_rsb_zoom -> t_nrs_zoom: a gated non-rail arrow is zoomed
    by the law and never reaches the stretch; the probe's per-compose state is reset as before."""
    rig = RT.Rig(image, g)
    sym = rig.sym
    rig.stub(sym["thunk_btn_bandstripe"], 0x2C)
    rnd = random.Random(7)
    bar = _bars(rig)["dll_copy"][0]
    aw = (20 * g) >> 4
    wn = -(-aw * 16 // g)
    stride = aw + 4
    plate = _plate("h", 18, rnd)
    native = _native(plate, wn, (wn - 18) // 2, stride)
    btn = bar + RS.SB_DN
    rig.w32(btn + 0xC4, bar)
    buf, data = rig.buffer(wn, wn, stride, 0x77)
    for y, r in enumerate(native):
        rig.mu.mem_write(data + y * stride, r)
    rig.w32(btn + 0x498, data)
    rig.w32(btn + 0x8EC, stride)
    rig.w32(sym["g_btn_fill_sprite"], 0)
    rig.w32(sym["g_btn_tileH"], 0x1234)
    rig.w32(sym["g_btn_edge_mask"], 0xFF)
    rig.hits.clear()
    frame = [MARKER, buf, buf, 0, 0, wn, wn, 0, 0, aw, aw, 0xFFFFFFFF]
    sp = rig.run(sym["t_btn_edgeprobe"], frame, {UC_X86_REG_ESI: btn})
    assert rig.mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x2C
    assert rig.r32(sym["g_btn_tileH"]) == 0 and rig.r32(sym["g_btn_edge_mask"]) == 0
    assert not rig.hits
    law = SL.sb_nonrail_arrow([list(r[:wn]) for r in native], wn, wn, aw, aw, g)
    assert [list(r) for r in rig.plane(data, aw, aw, stride)] == law


# ---- the yaml pin + the retargets ------------------------------------------------------------------------------------
def test_yaml_is_the_assembler_and_the_retargets_are_wired():
    _s, _g, caves, _sym = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    cave = next(c for c in caves if c["id"] == "pcave2")
    assert int(cave["length"]) >= NR.REGION[1]
    ent = {e["id"]: e for e in cave["contents"]}
    for name in NR.ORDER:
        off, end = NR.LAYOUT[name]
        assert int(ent[name]["offset"]) == off and NR.REGION[0] <= off < end <= NR.REGION[1]
        assert str(ent[name]["bytes"]).split() == NR.template(name).split(), name
    for e in cave["contents"]:                                   # nothing else inside the W10S region
        if e["id"] not in NR.ORDER:
            assert not NR.REGION[0] <= int(e["offset"]) < NR.REGION[1], e["id"]
    for n, (o, sz) in NR.CELLS.items():
        assert int(_sym[n]["offset"]) == o and int(_sym[n]["size"]) == sz and NR.REGION[0] <= o < o + sz <= NR.REGION[1]
    toks = lambda n: " ".join(str(ent[n]["bytes"]).split())                            # noqa: E731
    # the two retargets: t_rsb_grip's pass-on and t_rsb_zoom's fwd_pop, each the only change in its thunk
    assert toks("t_rsb_grip").endswith("61 68 {abs32:t_nrs_grip} C3") and "t_sbt_grip" not in toks("t_rsb_grip")
    z = toks("t_rsb_zoom")
    assert z.endswith("5A 58 68 {abs32:t_nrs_zoom} C3") and z.count("{abs32:thunk_btn_bandstripe}") == 1
    assert toks("t_nrs_grip").endswith("61 68 {abs32:t_sbt_grip} C3")
    assert toks("t_nrs_zoom").count("{abs32:thunk_btn_bandstripe}") == 2
