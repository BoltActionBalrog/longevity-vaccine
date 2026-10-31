"""Unicorn parity for the ORNATE band-map blit (assemble_bandmap_ornate.py) against the laws
scaling_laws.chrome_band_widths / axis_map_chrome / ornate_outer_key.

  * bm_axis (the derived one) == axis_map_chrome, every index, g 17..40 x spans, both ornate axes;
  * the WHOLE blit over a synthetic ornate-shaped frame == keyed band-map copy + the outer-key re-key, including
    a clipped dest and an underlay that must survive everywhere except outside the metal;
  * the selector sends only the 61x44 corner canvas to the ornate blit;
  * the verified plain blit's source is untouched by the derivation (its own parity file covers its bytes);
  * fix 26 v2: bm_axis' 4th extra arg `skip` == axis_map_chrome(.., skip) for skip 0 and 1 on both axes, and every
    x map is MONOTONE non-decreasing (the v1 far[b] seam sampled hi-1 between two hi columns); the whole blit with
    g_orn_mirror = 1 == the per-row law ornate_popup_row_map (t_orn_rowcls / t_orn_oc) over an art with mirror rows
    (the straight edge) AND ornament / clamp rows: the green line mirrors about the half-open axis x <-> W - 1 - x
    on every row, a mirror row's margins and metal are equal, a non-mirror row keeps every source column;
  * fix 26 v3/v4: the row classes are BLOCKS (the ornament's foot joins the CORNER, the lower half's doubled-line rows
    start the DUP block), an opaque blit is all MIRROR, and the asm mutants of the classes (no foot link, no DUP
    block, no CORNER shift) are killed by the per-row blit parity.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
pytest.importorskip("keystone")
pytest.importorskip("unicorn")
from unicorn import Uc, UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EDX, UC_X86_REG_ESP  # noqa: E402

import assemble_bandmap as AB  # noqa: E402
import assemble_bandmap_ornate as AO  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0xA0C000
STACK = 0x00B00000
DATA = 0x00C00000
G_VAR, NXV, NYV, DSTW, DSTH, FEW, FEH, MIRROR = (DATA + 0x100 + 4 * i for i in range(8))
FWDX, FWDY, FARX, FARY = DATA + 0x1000, DATA + 0x1100, DATA + 0x1200, DATA + 0x1300
FX, FY = DATA + 0x2000, DATA + 0x6000
SRCOBJ, DSTOBJ = DATA + 0x8000, DATA + 0x9000
SRCPIX, DSTPIX = 0x00D00000, 0x00E00000
RET = 0x00A00010
OLD_BLIT, FALLBACK = 0x00A00100, 0x00A00200
REAL = {0x71111111: NXV, 0x71222222: NYV, 0x71333333: FWDX, 0x71444444: FWDY, 0x71555555: FX, 0x71666666: FY,
        0x71777777: G_VAR, 0x71888888: DSTW, 0x71999999: DSTH, 0x71AAAAAA: FEW, 0x71BBBBBB: FEH,
        0x72111111: FALLBACK, 0x72222222: FALLBACK, 0x73111111: FARX, 0x73222222: FARY,
        0x73333333: OLD_BLIT, 0x73444444: PCAVE2 + AO.OFF_ORN, 0x73555555: MIRROR, 0x73666666: FALLBACK}
G_RANGE = list(range(17, 41))
SPANS = [300, 431, 756, 859, 1024, 1375, 2400]


def resolve(b: bytes) -> bytes:
    for s, real in REAL.items():
        b = b.replace(s.to_bytes(4, "little"), real.to_bytes(4, "little"))
    return b


@pytest.fixture(scope="module")
def emu():
    out = AO.build()
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(0x00A00000, 0x100000)
    mu.mem_map(STACK, 0x100000)
    mu.mem_map(DATA, 0x100000)
    mu.mem_map(SRCPIX, 0x100000)
    mu.mem_map(DSTPIX, 0x800000)
    code = {}
    for name, (off, b) in out.items():
        rb = resolve(b)
        mu.mem_write(PCAVE2 + off, rb)
        code[name] = (PCAVE2 + off, rb)
    va, data = code["thunk_bandmap_orn"]
    bm_axis = None
    for i in range(len(data) - 5):
        if data[i] == 0xE8:
            tgt = va + i + 5 + int.from_bytes(data[i + 1:i + 5], "little", signed=True)
            if va < tgt < va + len(data):
                bm_axis = tgt
                break
    assert bm_axis
    return {"mu": mu, "code": code, "bm_axis": bm_axis}


def run_axis(emu, n, dst_n, src_n, k, c_near, c_far, skip=0):
    mu = emu["mu"]
    sp = STACK + 0x80000
    args = [n, dst_n, src_n, k, FWDX, FX, c_near, c_far, FARX, skip]
    mu.mem_write(sp, struct.pack("<I10i", RET, *args))
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EBP, STACK + 0x90000)
    mu.mem_write(FWDX, b"\x00" * 0x400)
    mu.mem_write(FX, b"\x00" * 0x2000)
    mu.emu_start(emu["bm_axis"], RET, count=80_000_000)
    eax, edx = mu.reg_read(UC_X86_REG_EAX), mu.reg_read(UC_X86_REG_EDX)
    out = list(struct.unpack(f"<{dst_n}H", bytes(mu.mem_read(FX, dst_n * 2)))) if eax else []
    return eax, edx, out


@pytest.mark.parametrize("skip", (0, 1))
@pytest.mark.parametrize("axis", ("x", "y"))
def test_scaling_ornate_axis_matches_the_law(emu, axis, skip):
    n = SL.ORNATE_BAND[0 if axis == "x" else 1]
    c_near, c_far = SL.ORNATE_STROKE_CELL[axis]
    bad, checked = [], 0
    for g in G_RANGE:
        k = SL.stroke_width(g)
        for span in SPANS:
            src = max(2 * n + 1, span * 16 // g)
            py = SL.axis_map_chrome(src, span, n, g, c_near, c_far, skip)
            eax, edx, out = run_axis(emu, n, span, src, k, c_near, c_far, skip)
            if py is None:
                if eax:
                    bad.append(("asm accepted what the law rejects", g, span))
                continue
            if not eax:
                if SL.cum(n, span, src) <= 255:
                    bad.append(("asm rejected", g, span))
                continue
            checked += 1
            if edx != SL.cum(n, span, src) or out != py:
                first = next((i for i, (a, b) in enumerate(zip(out, py)) if a != b), None)
                bad.append((g, span, src, edx, first))
    assert not bad, bad[:6]
    assert checked > 100


@pytest.mark.parametrize("g", G_RANGE)
def test_scaling_ornate_stroke_is_k_on_both_sides_and_margins_are_proportionate(g):
    k = SL.stroke_width(g)
    for axis, n, margins in (("x", 61, (3, 4)), ("y", 44, (4, 0))):
        c_near, c_far = SL.ORNATE_STROKE_CELL[axis]
        dst = SL.scale_px(550 if axis == "x" else 600, g)
        src = dst * 16 // g
        m = SL.axis_map_chrome(src, dst, n, g, c_near, c_far)
        assert m is not None and m == sorted(m) and m[0] == 0 and m[-1] == src - 1
        assert m.count(c_near) == k and m.count(src - 1 - c_far) == k              # the green line: K, both sides
        near_margin = sum(m.count(i) for i in range(margins[0]))
        far_margin = sum(m.count(src - 1 - i) for i in range(margins[1]))
        assert abs(near_margin - margins[0] * g / 16) <= 1 and abs(far_margin - margins[1] * g / 16) <= 1
        old = SL.axis_map(src, dst, n, g)                                            # the defect this replaces
        if axis == "x" and g in (22, 25, 40):                                         # measured 1/2, 1/2, 2/3 px left/right
            assert old.count(c_near) != old.count(src - 1 - c_far)


def ornate_src(w, h, key, mx=(3, 4), my=(4, 0)):
    """margin(key) | metal 4 | green 1 | key interior with a few opaque 'content' pixels; corner cut-outs keyed;
    one key HOLE inside the metal (must NOT be re-keyed: it is not connected to the outside)."""
    metal, green, inner = 70, 21, 200
    src = [[key] * w for _ in range(h)]
    for y in range(my[0], h - my[1]):
        for x in range(mx[0], w - mx[1]):
            dl, dr, dt, db = x - mx[0], (w - mx[1] - 1) - x, y - my[0], (h - my[1] - 1) - y
            d = min(dl, dr, dt, db)
            if d < 4:
                src[y][x] = metal
            elif d == 4:
                src[y][x] = green
    for cy, cx in ((my[0], mx[0]), (my[0], w - mx[1] - 1), (h - my[1] - 1, mx[0]), (h - my[1] - 1, w - mx[1] - 1)):
        src[cy][cx] = key                                        # corner cut-outs (1 px)
    src[h // 2][mx[0] + 2] = key                                 # a hole INSIDE the metal
    src[h // 2][w // 2] = inner
    return src


def run_blit(emu, g, src, dst_w, dst_h, dst_x, dst_y, buf_w, buf_h, key, underlay, mirror=0):
    mu = emu["mu"]
    sh, sw = len(src), len(src[0])
    spitch, dpitch = sw + 3, buf_w + 5
    mu.mem_write(SRCPIX, b"".join(bytes(r) + b"\xEE" * 3 for r in src))
    mu.mem_write(DSTPIX, bytes([underlay]) * (dpitch * buf_h))
    for obj, pix, w, h, pitch in ((SRCOBJ, SRCPIX, sw, sh, spitch), (DSTOBJ, DSTPIX, buf_w, buf_h, dpitch)):
        mu.mem_write(obj, b"\x00" * 0x600)
        mu.mem_write(obj + 0x54, struct.pack("<I", pix))
        mu.mem_write(obj + 0x80, struct.pack("<2i", w, -h))
        mu.mem_write(obj + 0x4A8, struct.pack("<i", pitch))
    mu.mem_write(G_VAR, struct.pack("<8i", g, SL.ORNATE_BAND[0], SL.ORNATE_BAND[1], 0, 0, 0, 0, mirror))
    sp = STACK + 0x80000
    mu.mem_write(sp, struct.pack("<I11i", RET, SRCOBJ, DSTOBJ, 0, 0, sw, sh, dst_x, dst_y, dst_w, dst_h, key))
    mu.reg_write(UC_X86_REG_ESP, sp)
    hit = {}

    def hook(u, addr, size, _):
        if addr == FALLBACK:
            hit["fallback"] = True
            u.emu_stop()

    h = mu.hook_add(UC_HOOK_CODE, hook)
    try:
        mu.emu_start(emu["code"]["thunk_bandmap_orn"][0], RET, count=400_000_000)
    finally:
        mu.hook_del(h)
    assert not hit, "ornate blit fell back"
    assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x2C
    assert struct.unpack("<2i", bytes(mu.mem_read(NXV, 8))) == (0, 0)             # one-shot consumed
    assert struct.unpack("<i", bytes(mu.mem_read(MIRROR, 4)))[0] == mirror           # read, never written
    raw = bytes(mu.mem_read(DSTPIX, dpitch * buf_h))
    return [list(raw[y * dpitch: y * dpitch + buf_w]) for y in range(buf_h)], [raw[y * dpitch + buf_w] for y in range(buf_h)]


def expect_blit(g, src, dst_w, dst_h, dst_x, dst_y, buf_w, buf_h, key, underlay, mirror=0):
    sh, sw = len(src), len(src[0])
    fy = SL.axis_map_chrome(sh, dst_h, 44, g, *SL.ORNATE_STROKE_CELL["y"])
    if mirror:
        per = {sy: SL.ornate_popup_row_map(src, sy, dst_w, g, key) for sy in set(fy)}
        fx = [per[fy[y]] for y in range(dst_h)]
    else:
        fx = [SL.axis_map_chrome(sw, dst_w, 61, g, *SL.ORNATE_STROKE_CELL["x"])] * dst_h
    bx, by = SL.cum(61, dst_w, sw), SL.cum(44, dst_h, sh)
    rows = [[underlay] * buf_w for _ in range(buf_h)]

    def put(x, y, v):
        if 0 <= dst_x + x < buf_w and 0 <= dst_y + y < buf_h and 0 <= x:
            rows[dst_y + y][dst_x + x] = v

    for y in range(dst_h):
        for x in range(dst_w):
            v = src[fy[y]][fx[y][x]]
            if v != key:
                put(x, y, v)
    for x, y in SL.ornate_outer_key(src, fx, fy, bx, by, key):
        put(x, y, key)
    return rows


@pytest.mark.parametrize("g", (17, 22, 25, 31, 40))
def test_scaling_ornate_blit_rekeys_only_outside_the_metal(emu, g):
    key, underlay = 9, 0x41
    dst_w, dst_h = SL.scale_px(220, g), SL.scale_px(150, g)
    src = ornate_src(dst_w * 16 // g, dst_h * 16 // g, key)
    got, guard = run_blit(emu, g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay)
    want = expect_blit(g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay)
    assert got == want
    assert set(guard) == {underlay}                                               # never past the dest row's width
    row = got[4 + dst_h // 2]
    k, p = SL.stroke_width(g), 6
    left_key = next(i for i, v in enumerate(row[p:]) if v != key)
    assert abs(left_key - 3 * g / 16) <= 1                                         # the margin is transparent, no rim
    assert row[p + left_key] == 70 and row[:p] == [underlay] * p                   # metal starts right after it; outside the rect untouched
    assert row.count(21) == 2 * k                                                  # green line K on the left + K on the right
    hole = [v for v in row[p + left_key: p + left_key + 5 * k + 12] if v == underlay]
    assert hole, "the key hole inside the metal must keep the underlay (not connected to the outside)"
    assert got[4 + dst_h // 2][p + dst_w // 2] in (200, underlay)


def test_scaling_ornate_blit_clipped_dest(emu):
    g, key, underlay = 25, 9, 0x41
    dst_w, dst_h = SL.scale_px(220, g), SL.scale_px(150, g)
    src = ornate_src(dst_w * 16 // g, dst_h * 16 // g, key)
    for dx, dy, bw, bh in ((-7, -5, dst_w - 20, dst_h - 9), (0, 0, dst_w, dst_h), (3, 2, dst_w // 2, dst_h // 2)):
        got, guard = run_blit(emu, g, src, dst_w, dst_h, dx, dy, bw, bh, key, underlay)
        assert got == expect_blit(g, src, dst_w, dst_h, dx, dy, bw, bh, key, underlay), (dx, dy, bw, bh)
        assert set(guard) == {underlay}


def test_scaling_ornate_opaque_key_skips_the_rekey(emu):
    g = 25
    dst_w, dst_h = SL.scale_px(220, g), SL.scale_px(150, g)
    src = ornate_src(dst_w * 16 // g, dst_h * 16 // g, 9)
    got, _ = run_blit(emu, g, src, dst_w, dst_h, 0, 0, dst_w, dst_h, -1, 0x41)
    fx = SL.axis_map_chrome(len(src[0]), dst_w, 61, g, *SL.ORNATE_STROKE_CELL["x"])
    fy = SL.axis_map_chrome(len(src), dst_h, 44, g, *SL.ORNATE_STROKE_CELL["y"])
    assert got == [[src[fy[y]][fx[x]] for x in range(dst_w)] for y in range(dst_h)]


def test_scaling_selector_routes_only_the_ornate_canvas(emu):
    mu = emu["mu"]
    sel = emu["code"]["thunk_bandmap_sel"][0]
    for nx, ny, want in ((61, 44, PCAVE2 + AO.OFF_ORN), (6, 6, OLD_BLIT), (61, 6, OLD_BLIT), (44, 61, OLD_BLIT), (0, 0, OLD_BLIT)):
        mu.mem_write(NXV, struct.pack("<2i", nx, ny))
        sp = STACK + 0x80000
        mu.mem_write(sp, struct.pack("<I", RET))
        mu.reg_write(UC_X86_REG_ESP, sp)
        hit = {}

        def hook(u, addr, size, _):
            if addr in (OLD_BLIT, PCAVE2 + AO.OFF_ORN):
                hit["at"] = addr
                u.emu_stop()

        h = mu.hook_add(UC_HOOK_CODE, hook)
        try:
            mu.emu_start(sel, RET, count=100)
        finally:
            mu.hook_del(h)
        assert hit.get("at") == want and mu.reg_read(UC_X86_REG_ESP) == sp        # stack untouched: a pure tail jump
        assert struct.unpack("<2i", bytes(mu.mem_read(NXV, 8))) == (nx, ny)       # not consumed by the selector


def test_scaling_plain_blit_source_is_untouched_and_yaml_carries_the_ornate_bytes():
    import re
    plain = dict((n, s) for n, _o, s in AB.THUNKS)["thunk_bandmap_blit"]
    assert "cum_tail" in plain and "ax_pass" not in plain and "pp_probe" not in plain
    y = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    if "frame_bandmap_ornate" not in y:
        pytest.skip("not spliced yet")
    for name, (off, b) in AO.build().items():
        m = re.search(r"- id: %s\r?\n\s+offset: (0x[0-9a-fA-F]+)\r?\n\s+bytes: \"([^\"]+)\"" % name, y)
        assert m and int(m.group(1), 16) == off and m.group(2) == AO.templ(b, name), name
    assert "E8 {rel32:thunk_bandmap_sel} E8 {rel32:thunk_fe" in y and "E8 {rel32:thunk_bandmap_blit} E8" not in y


def ornate_src_v2(w, h, key):
    """ornate_src (straight edge: right = left + one key column) plus the kinds of rows the real ornate art has near
    its corners (audit26, audit26b): ORNAMENT rows -- the right side one ART column wider than the left between the
    key edge and the green line; the ornament's FOOT -- a row with the straight edge's key / line pattern whose outer
    art continues the ornament above it (it must join the CORNER block: audit26b F1); and CLAMP rows in the lower
    half: art in the right's outermost column and a doubled line (they start the DUP block, which runs to the end)."""
    src = ornate_src(w, h, key, mx=(3, 4), my=(4, 0))
    metal, orn, green = 70, 75, 21
    for y in range(6, 12):                                # ornament rows: right cols 1..7 art, col 8 the line
        for c in range(1, 8):
            src[y][w - 1 - c] = orn
        src[y][w - 1] = key
        src[y][w - 1 - 8] = green
    for c in range(4, 8):                                 # the foot: straight pattern, ornament colour
        src[12][w - 1 - c] = orn
    for y in range(h - 9, h - 5):                         # clamp rows: art at the outermost column, line doubled
        for c in range(0, 7):
            src[y][w - 1 - c] = orn
        src[y][w - 1 - 7] = green
        src[y][w - 1 - 8] = green
    for y, (kl, kr) in ((h - 2, (18, 19)), (h - 1, (20, 20))):   # the bottom edge's last rows (audit26c N1): no line,
        src[y] = [key] * kl + [metal] * (w - kl - kr) + [key] * kr   # the extra key column / none at all (PLAIN)
    return src


def law_art(src, key):
    """Four one-row art rows for the law tests: straight (mirror), ornament (corner), straight, clamp (lower half:
    doubled line, art in the outermost column -> the DUP block)."""
    straight = [key] * 3 + [70] * 4 + [21] + [0] * (src - 17) + [21] + [70] * 4 + [key] * 4
    corner = [key] + [75] * 6 + [21] + [0] * (src - 17) + [21] + [75] * 7 + [key]
    clamp = [key] * 3 + [70] * 4 + [21] + [0] * (src - 17) + [21, 21] + [75] * 7
    return [straight, corner, list(straight), clamp]


@pytest.mark.parametrize("g", G_RANGE)
def test_scaling_ornate_x_maps_are_monotone(g):
    """S1 (audit26): every x map the ornate blit can use is monotone non-decreasing -- skip 0 / 1 (axis_map_chrome),
    the mirror-row map and the corner / dup row maps -- for a sweep of widths.  The v1 seam (far[b] = n + 1) sampled hi - 1
    between two hi columns at the far band's inner edge."""
    c_near, c_far = SL.ORNATE_STROKE_CELL["x"]
    key = 9
    for w_nat in list(range(200, 1000, 13)) + [634]:
        W = SL.scale_px(w_nat, g)
        src = ((W - 1) * 16) // g
        maps = [SL.axis_map_chrome(src, W, 61, g, c_near, c_far, s) for s in (0, 1)]
        art = law_art(src, key)
        maps += [SL.ornate_popup_row_map(art, y, W, g, key) for y in range(len(art))]
        for m in maps:
            assert m is not None and all(m[i] <= m[i + 1] for i in range(W - 1)), (g, W)
            assert m[0] == 0 and m[-1] <= src - 1


@pytest.mark.parametrize("g", G_RANGE)
def test_scaling_ornate_popup_law_mirrors_the_green_line(g):
    """fix 26 v2 law: on a mirror row the right green line's columns are exactly {W - 1 - x : x in the left line's}
    (the half-open axis), K wide, and so are the transparent margin and the metal; the near band and the middle are
    axis_map_chrome's verbatim; the far band never samples the art's outermost (extra key) column.  On an ornament
    row (CORNER, O4) the line is at the same columns and the outer cells are the old map's, column 7 dropped; on a
    clamp row (DUP) the old outer cells and the line, the duplicate line column dropped."""
    c_near, c_far = SL.ORNATE_STROKE_CELL["x"]
    k, key = SL.stroke_width(g), 9
    for w_nat in range(250, 960, 37):
        W = SL.scale_px(w_nat, g)
        src = ((W - 1) * 16) // g
        b = SL.cum(61, W, src)
        old = SL.axis_map_chrome(src, W, 61, g, c_near, c_far)
        art = law_art(src, key)
        straight, corner, clamp = art[0], art[1], art[3]
        assert [SL.ornate_popup_row_class(art, y, key) for y in range(4)] == ["mirror", "corner", "mirror", "dup"]
        for y, row in ((0, straight), (1, corner), (3, clamp)):
            m = SL.ornate_popup_row_map(art, y, W, g, key)
            drawn = [row[m[x]] for x in range(W)]
            left = [x for x in range(b) if drawn[x] == 21]
            right = [x for x in range(W - b, W) if drawn[x] == 21]
            assert len(left) == k and right == sorted(W - 1 - x for x in left), (g, W, left, right)
            assert m[:W - b] == old[:W - b]
            far_src = set(m[W - b:])
            if row is straight:
                kl = next(x for x in range(W) if drawn[x] != key)
                kr = next(x for x in range(W) if drawn[W - 1 - x] != key)
                assert kl == kr, (g, W, kl, kr)                       # transparent margins mirrored
                assert src - 1 not in far_src                          # the extra key column is never sampled
            elif row is corner:                                        # O4: the old outer cells, column 7 dropped
                d = SL.ornate_popup_outer_width(src, W, g)
                assert m[W - d:] == old[W - d:] and set(old[W - b:]) - far_src <= {src - 8}
            elif row is clamp:                                         # DUP: the old outer cells, the duplicate line column dropped
                assert m[W - b:] == [v + (1 if W - 1 - j < SL.ornate_popup_line_end(src, W, g) else 0)
                                     for j, v in zip(range(W - b, W), SL.ornate_popup_axis_map_x(src, W, g)[W - b:])]
                assert all(src - 1 - c in far_src for c in range(8)) and src - 9 not in far_src
    assert SL.axis_map_chrome(src, W, 61, g, c_near, c_far, 0) == old


@pytest.mark.parametrize("g", (17, 18, 22, 25, 31, 40))
def test_scaling_ornate_popup_blit_matches_the_per_row_law(emu, g):
    """The whole blit with g_orn_mirror = 1 == ornate_popup_row_map per dest row (t_orn_rowcls + t_orn_oc) + the
    per-row outer-key re-key, over an art with straight, ornament and clamp rows; the drawn green line mirrors about
    x <-> W - 1 - x on a straight row; with the flag 0 the old map is reproduced byte for byte outside nothing."""
    key, underlay = 9, 0x41
    dst_w, dst_h = SL.scale_px(220, g), SL.scale_px(150, g)
    src = ornate_src_v2(dst_w * 16 // g, dst_h * 16 // g, key)
    got, guard = run_blit(emu, g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay, mirror=1)
    assert got == expect_blit(g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay, mirror=1)
    assert set(guard) == {underlay}
    row = got[4 + dst_h // 2][6:6 + dst_w]
    left = [x for x in range(dst_w // 2) if row[x] == 21]
    right = [x for x in range(dst_w // 2, dst_w) if row[x] == 21]
    assert len(left) == SL.stroke_width(g) and right == sorted(dst_w - 1 - x for x in left)
    off, _ = run_blit(emu, g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay, mirror=0)
    assert off == expect_blit(g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay, mirror=0)
    b = SL.cum(61, dst_w, len(src[0]))
    for y in range(dst_h + 12):                       # the mirror only touches the far x band
        assert got[y][:6 + dst_w - b] == off[y][:6 + dst_w - b]




def test_scaling_ornate_popup_row_classes_are_blocks():
    """audit26b F1: the classes come in BLOCKS of the art -- the ornament's foot (a straight-pattern row whose outer
    art continues the ornament above) is CORNER, everything from the lower half's first doubled-line row down is DUP
    (whatever its own pattern), and a straight row next to a corner row it shares no outer art with stays MIRROR;
    an opaque blit (key -1) is all MIRROR (F4: t_orn_rowcls leaves E = 0 for key -1)."""
    key = 9
    src = ornate_src_v2(200, 120, key)
    cls = [SL.ornate_popup_row_class(src, y, key) for y in range(len(src))]
    assert cls[6:13] == ["corner"] * 7 and cls[5] == "mirror" and cls[13] == "mirror"
    yd = SL.ornate_popup_dup_start(src, key)
    assert yd == len(src) - 9 and cls[yd:] == ["dup"] * 8 + ["plain"] and "dup" not in cls[:yd]
    assert set(cls[13:len(src) // 2 - 1]) == {"mirror"}    # (h // 2: ornate_src's metal hole fails the pattern)
    assert {SL.ornate_popup_row_class(src, y, -1) for y in range(len(src))} == {"mirror"}
    for g in (17, 25, 40):
        W = SL.scale_px(200, g) + 1
        assert all(SL.ornate_popup_row_map(src, y, W, g, -1) == SL.ornate_popup_axis_map_x(200, W, g) for y in range(len(src)))


@pytest.mark.parametrize("g", (18, 25, 40))
def test_scaling_ornate_popup_opaque_blit_is_all_mirror(emu, g):
    """F4: key -1 with g_orn_mirror = 1 -- the asm copies every pixel through the MIRROR map on every row, which is
    ornate_popup_row_map(.., key=-1)."""
    dst_w, dst_h = SL.scale_px(220, g), SL.scale_px(150, g)
    src = ornate_src_v2(dst_w * 16 // g, dst_h * 16 // g, 9)
    got, _ = run_blit(emu, g, src, dst_w, dst_h, 0, 0, dst_w, dst_h, -1, 0x41, mirror=1)
    fy = SL.axis_map_chrome(len(src), dst_h, 44, g, *SL.ORNATE_STROKE_CELL["y"])
    fx = {sy: SL.ornate_popup_row_map(src, sy, dst_w, g, -1) for sy in set(fy)}
    assert got == [[src[fy[y]][fx[fy[y]][x]] for x in range(dst_w)] for y in range(dst_h)]


#: asm mutants of the fix 26 v3 classes: (thunk, byte offset, the bytes it must start with there, the mutant bytes)
CLASS_MUTANTS = {
    "nolink": ("t_orn_rnb", 0, "31C085FF78", "31C085C0C3"),          # the foot never joins the CORNER block (F1)
    "nodup": ("t_orn_rcls", 0x43, "740347EBD9", "909047EBD9"),        # no DUP block: the clamp is CORNER-mapped (F3)
    "noplain": ("t_orn_rplain", 0, "5753", "31C0C3"),                 # no PLAIN class: the last row's right key run short (N1)
    "nocorner": ("t_orn_rowcls", 66, "8955A4", "909090"),             # D stays 0: the corner rows mirror (O4 lost)
}


@pytest.mark.parametrize("mutant", sorted(CLASS_MUTANTS))
def test_scaling_ornate_popup_class_mutants_are_killed(emu, mutant):
    """Each asm mutant of the row classes draws something the law does not (g = 25, the art with ornament, foot and
    clamp rows) -- so the per-row blit parity above really pins the foot link, the DUP block and the CORNER shift."""
    name, off, want, new = CLASS_MUTANTS[mutant]
    va, orig = emu["code"][name]
    assert orig[off:off + len(bytes.fromhex(want))] == bytes.fromhex(want), (mutant, orig[off:off + 6].hex())
    mu = emu["mu"]
    g, key, underlay = 25, 9, 0x41
    dst_w, dst_h = SL.scale_px(220, g), SL.scale_px(150, g)
    src = ornate_src_v2(dst_w * 16 // g, dst_h * 16 // g, key)
    mu.mem_write(va + off, bytes.fromhex(new))
    mu.ctl_remove_cache(va, va + len(orig))
    try:
        got, _ = run_blit(emu, g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay, mirror=1)
    finally:
        mu.mem_write(va, orig)
        mu.ctl_remove_cache(va, va + len(orig))
    assert got != expect_blit(g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay, mirror=1)


def _key_runs(row, key):
    run = lambda r: next((i for i, v in enumerate(r) if v != key), len(r))  # noqa: E731
    return run(row), run(row[::-1])


@pytest.mark.parametrize("g", G_RANGE)
def test_scaling_ornate_popup_law_key_runs_symmetric_where_vanilla_is(g):
    """audit26c N1: every source row whose outer key runs are equal (vanilla symmetric: the PLAIN bottom row) or whose
    right run is the left's + 1 with no line (the extra key column: the row above it) draws equal key runs L == R
    at every g -- the law (ornate_popup_row_map)."""
    key = 9
    W = SL.scale_px(220, g)
    src = ornate_src_v2(W * 16 // g, SL.scale_px(150, g) * 16 // g, key)
    for y in (len(src) - 2, len(src) - 1):
        m = SL.ornate_popup_row_map(src, y, W, g, key)
        kl, kr = _key_runs([src[y][x] for x in m], key)
        assert kl == kr, (g, y, kl, kr)


@pytest.mark.parametrize("g", (17, 20, 25, 36, 40))
def test_scaling_ornate_popup_blit_key_runs_symmetric_bottom_rows(emu, g):
    """audit26c N1 on the asm: the blit's last dest rows (the PLAIN row and the row above it) carry equal outer key
    runs, and the noplain mutant (CLASS_MUTANTS) is killed by the parity below."""
    key, underlay = 9, 0x41
    dst_w, dst_h = SL.scale_px(220, g), SL.scale_px(150, g)
    src = ornate_src_v2(dst_w * 16 // g, dst_h * 16 // g, key)
    got, _ = run_blit(emu, g, src, dst_w, dst_h, 6, 4, dst_w + 20, dst_h + 12, key, underlay, mirror=1)
    fy = SL.axis_map_chrome(len(src), dst_h, 44, g, *SL.ORNATE_STROKE_CELL["y"])
    for y in range(dst_h):
        if fy[y] >= len(src) - 2:
            kl, kr = _key_runs(got[4 + y][6:6 + dst_w], key)
            assert kl == kr and kl > 0, (g, y, fy[y], kl, kr)
