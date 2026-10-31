"""F34: a flat type-2 #listbox popup's ring hugs its list window on all four sides (thunk_pf_union_align v18).

Law (scaling_laws.py, the source of truth): listbox_ring_takes_hug_arm (the gate: dialog type 2, no body text, no art,
the flat / slide family) + itemlist_ring_hug (ring = D -+ fl(3g/16), the far edges drawn inclusive), D = the list
window -- the type-2 calc writes Dialog[+0x5c] = the list width BEFORE the first draw, so the 0x406205 path's D is
the list window at every draw point.

Vanilla (pristine .bak, 1024x768): list [33, 753) x [38, 263), ring strokes cols 30 / 755, rows 35 / 265 -- D -+ 3 on
every side, ring -> list 2 | 2 | 2 | 2.  The defect (deployed 03fe23b9, user shots 20261024-233521 4K / -233621
1080): v7..v17 drew the type-2 ring on the title inner, so ring -> list was 6 | 9 (T 3, B 4) at 4K, 4 | 5 at 1080;
the rows and buttons themselves are vanilla x g/16 (list x = fl(33g/16), w = fl(720g/16), flush with the buttons).

Proof (popup_listbox_emu.py on image_emu.py: the REAL Go To builder, Console_go_to's own sequence, every engine
function and cave thunk running for real, in the engine's call order -- the ring is drawn at BasePop_exec_3 0x602B49
BEFORE the attach at 0x602BFE; the lifecycle item adds the modal's own re-layouts, the full popup redraw and the Sort
branch's second show):
  * the drawn ring strokes == itemlist_ring_hug(list window) on all four sides, one stroke thickness, the four
    channels equal, at g 17 (lifecycle: every snapshot) / 18 / 22 / 25 / 40;
  * the rows and the button row stay flush (fix 19) and the list window is the box reserve (fix 29);
  * g = 16 renders pixel-identical to the pristine .bak (popup + every child window);
  * the mutant with the v18 container test removed (the v17 type-2 title-inner arm, in memory on the bake) fails.

COST (~40 s serial, 7 image runs in 7 tests; xdist splits by test, the slowest item ~12 s): each run boots the image
(~1 s) and draws Go To (~4 s at g 16-25, ~10 s at 4K, ~12 s for the g = 17 lifecycle's two shows and four
re-layouts).  The unit layer
(test_pfalign_asm_parity.py, ms) covers every g 17..40, both families and every gate; this module only proves what
the unit layer cannot -- the D the real draw sees at each draw point.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

np = pytest.importorskip("numpy", reason="numpy absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("pefile", reason="pefile absent")

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

RING = 31                         # the ring's palette index (flat popup, every g)
#: v18's container-arm test `cmp dword [esi+0x2350], 2 / je hug2` (7 + 6 bytes) -- NOPped in the v17 mutant
V18_GATE = bytes.fromhex("83BE5023000002") + b"\x0f\x84"

_RUNS: dict = {}


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def images(tmp_path_factory, symtab, baked_exe, bak_path):
    """{'after': the bake (conftest's shared baked_exe), 'pristine': the .bak, 'mutant': the bake with v18's type-2
    test NOPped (in memory; the v17 type-2 outcome: the title-inner container arm)}."""
    import pefile
    data = bytearray(Path(baked_exe).read_bytes())
    pe = pefile.PE(data=bytes(data), fast_load=True)
    va = symtab["thunk_pf_union_align"]
    off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
    code = bytes(data[off:off + 0x240])
    k = code.find(V18_GATE)
    assert k > 0 and code.find(V18_GATE, k + 1) == -1, "the v18 container test is not in the shipped union"
    data[off + k:off + k + 13] = b"\x90" * 13
    d = tmp_path_factory.mktemp("lb_ring_hug")
    (d / "mutant.exe").write_bytes(bytes(data))
    return {"after": str(baked_exe), "pristine": str(bak_path), "mutant": str(d / "mutant.exe")}


def _render(images, which, g, lifecycle=False):
    key = (which, g, lifecycle)
    if key in _RUNS:
        return _RUNS[key]
    import image_emu as E
    import popup_listbox_emu as P

    from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP
    snaps, bwins = [], []

    class R(P.Run):
        def _modal(self, e):
            snaps.append((self.phase, E.canvas_of(e, self.pop)))
            P.Run._modal(self, e)

        def _btn(self, e):
            if e.r32(e.reg(UC_X86_REG_ESP)) in P.BTN_RETS and self.phase == "show1":
                bwins.append(e.reg(UC_X86_REG_ECX))
            P.Run._btn(self, e)

    r = R(images[which], g, "GOTO", lifecycle=lifecycle)
    e = r.e
    snaps.append(("end", E.canvas_of(e, r.pop)))
    kids = {}
    for lw in r.lists:
        kids[lw["win"]] = E.canvas_of(e, lw["win"])
    btns = sorted((e.s32(w + 0x13C), e.s32(w + 0x140), e.s32(w + 0x444 + 0x38)) for w in bwins)   # placed x, y, w
    out = dict(g=r.g, snaps=snaps, lists=list(r.lists), btns=btns, reserve=r.reserve, popwin=r.popwin, kids=kids)
    r.e.uc = None
    r.e = None
    _RUNS[key] = out
    return out


def _runs(line, v):
    out, i, n = [], 0, len(line)
    while i < n:
        if line[i] == v:
            j = i
            while j < n and line[j] == v:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def ring_around(c, lw):
    """The ring strokes nearest the list window on each side: (l0, l1), (r0, r1), (t0, t1), (b0, b1) half-open."""
    l, t, r, b = lw["x"], lw["y"], lw["x"] + lw["w"], lw["y"] + lw["h"]
    row = _runs(c[(t + b) // 2], RING)
    col = _runs(c[:, (l + r) // 2], RING)
    left = max((s for s in row if s[1] <= l), key=lambda s: s[1])
    right = min((s for s in row if s[0] >= r), key=lambda s: s[0])
    top = max((s for s in col if s[1] <= t), key=lambda s: s[1])
    bot = min((s for s in col if s[0] >= b), key=lambda s: s[0])
    return left, right, top, bot


def assert_hug(c, lw, g):
    left, right, top, bot = ring_around(c, lw)
    l, t, r, b = lw["x"], lw["y"], lw["x"] + lw["w"], lw["y"] + lw["h"]
    law = SL.itemlist_ring_hug(l, t, r, b, g)                       # inclusive far edges at g > 16
    assert (left[0], top[0], right[1] - 1, bot[1] - 1) == law, (left, right, top, bot, law)
    k = {left[1] - left[0], right[1] - right[0], top[1] - top[0], bot[1] - bot[0]}
    assert len(k) == 1, ("stroke thickness differs per side", left, right, top, bot)
    ch = (l - left[1], right[0] - r, t - top[1], bot[0] - b)
    assert len(set(ch)) == 1, ("ring -> list channels", ch)
    assert ch[0] == SL.popup_pad(3, g) - k.pop()
    return ch


@pytest.mark.parametrize("g", (18, 22, 25, 40))
def test_goto_ring_hugs_the_list(images, g):
    """Every side's ring stroke at list -+ fl(3g/16) (far edges inclusive), one thickness, four equal channels;
    rows and buttons flush; the list is the box reserve."""
    out = _render(images, "after", g)
    assert out["g"] == g
    lw = out["lists"][-1]
    for phase, c in out["snaps"]:
        assert_hug(c, lw, g)
    assert lw["h"] == out["reserve"]
    # fix 19: the button row spans the list window (the remainder law), flush on both sides -- untouched by v18
    btn = out["btns"]
    assert len(btn) == 5 and len({y for _x, y, _w in btn}) == 1
    assert btn[0][0] == lw["x"] and btn[-1][0] + btn[-1][2] == lw["x"] + lw["w"], (btn, lw)
    if g == 40:
        # the user's 4K shot geometry: list [82, 1882) x [95, 652) popup-local, ring strokes 75-76 / 1887-1888 /
        # 88-89 / 657-658 -> 5 | 5 | 5 | 5 (was 74-75 / 1891-1892 / 90-91 / 656-657: 6 | 9 | 3 | 4)
        _g40_values(out)


def _g40_values(out):
    lw = out["lists"][-1]
    assert (lw["x"], lw["y"], lw["w"], lw["h"]) == (82, 95, 1800, 557)
    c = out["snaps"][-1][1]
    assert ring_around(c, lw) == ((75, 77), (1887, 1889), (88, 90), (657, 659))
    assert assert_hug(c, lw, 40) == (5, 5, 5, 5)


def test_goto_lifecycle_g17_every_draw_point(images):
    """g = 17 through the modal's own re-layouts (full redraw, ListBox_update_changes, a re-attach), exec_3 to its
    end and the Sort branch's second show on the same popup: the ring hugs the list at every snapshot."""
    out = _render(images, "after", 17, lifecycle=True)
    assert out["g"] == 17
    phases = [p for p, _c in out["snaps"]]
    assert phases[0] == "show1" and "show2" in phases and phases[-1] == "end"
    for lw in out["lists"]:
        assert (lw["x"], lw["y"], lw["w"], lw["h"]) == tuple(out["lists"][0][k] for k in ("x", "y", "w", "h"))
    for phase, c in out["snaps"]:
        assert_hug(c, out["lists"][-1], 17)


def test_goto_g16_is_pristine(images):
    """g = 16: the popup canvas and the list window's canvas are pixel-identical to the pristine .bak's."""
    a = _render(images, "pristine", 16)
    b = _render(images, "after", 16)
    assert a["g"] in (0, 16) and b["g"] == 16
    for (pa, ca), (pb, cb) in zip(a["snaps"], b["snaps"]):
        assert ca.shape == cb.shape and (ca == cb).all(), (pa, pb)
    la, lb = a["lists"][-1], b["lists"][-1]
    assert {k: la[k] for k in ("x", "y", "w", "h")} == {k: lb[k] for k in ("x", "y", "w", "h")}
    ka, kb = a["kids"][la["win"]], b["kids"][lb["win"]]
    assert ka.shape == kb.shape and (ka == kb).all()
    # vanilla D -+ 3: ring strokes 30 / 755, 35 / 265 around [33, 753) x [38, 263) (the half-open draw)
    assert ring_around(a["snaps"][-1][1], la) == ((30, 31), (755, 756), (35, 36), (265, 266))


def test_mutant_v17_type2_arm_fails(images):
    """The harness sees the defect: with v18's type-2 test removed the ring is back on the title inner at 1080
    (ring -> list 4 | 5 for the four-sided 3 | 3 | 3 | 3)."""
    out = _render(images, "mutant", 22)
    c = out["snaps"][-1][1]
    lw = out["lists"][-1]
    with pytest.raises(AssertionError):
        assert_hug(c, lw, 22)
    left, right, _t, _b = ring_around(c, lw)
    assert (lw["x"] - left[1], right[0] - (lw["x"] + lw["w"])) == (4, 5)
