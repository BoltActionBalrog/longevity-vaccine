"""Scenario-editor palette faces: thunk_ed_remap FORCE path (2026-10-06) -- Unicorn differential.

Defect (audit stripes_icon_findings.md B3): three palette cells (sheet k = 1, 11, 22; x3 states = 9 faces)
never reach the run-chain detector's 2*w credit bar because the black glyph cuts their dither into short
chains, so they stay engine-NN (uneven 1/2 runs) at every fractional g.  The audit's looser detector
(chains >= 3, credits >= w) was REJECTED: it fires on cell 21 (the diagonal hatch, which has no column
dither at all) at every g -- a false positive on the served set.

Law (scaling_laws.editor_face_enable(..., forced=True) / editor_face_forced): the 31 editor FlatButtons
[EDITOR_BTN_LO, EDITOR_BTN_HI) are restriped UNCONDITIONALLY (threshold 0, chain law untouched).  Ground
truth from interface.pcx: all 93 faces (25 palette x 3 states at (350+44*(k%8), 245+57*(k//8)+19*s) 43x18,
6 brush x 3 states at (465+25*i, 438+25*s) 24x24) carry their pair indices ONLY on a row-parity mask
(0 violations), so a phase restripe of every pair pixel IS the regeneration of that mask at device density.
Every other caller (HUD locator statics, satellite ATTACK!, scrollbar chevrons) keeps the detector verbatim.

Port: thunk_ed_remap reads the button (saved esi at [esp+8]) after the column scan; in range -> edx = 0
before the five credit compares.  setge replaces the jl/mov-byte flag writes and the dead
`mov eax,[g_popup_scale_num]` + `nop` fossil goes, so the thunk grows 901 -> 909 B inside its 912 B slot
(0x10C60..0x10FF0, cave_map: next occupant thunk_diplo_pdsclear 0x10FF0).

This test runs the REAL yaml bytes (today) and the proposed bytes (assembled in memory from the exact
source edits) at g = 16, 17, 18, 21, 22, 25, 32, 40 over every served face; the editor faces come from the
game's interface.pcx (skipped if the game dir is absent), the others are the synthetic fixtures of
test_scenedit_asm_parity.  Skips if keystone/unicorn are absent.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone not installed")
unicorn = pytest.importorskip("unicorn", reason="unicorn not installed")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_scenedit as A  # noqa: E402

STACK = 0x00B00000
DATA = 0x00C00000
MARKER = 0x00DEAD00
GS = [16, 17, 18, 21, 22, 25, 32, 40]
SLOT = A.SLOTS[A.OFF_EDREMAP] - A.OFF_EDREMAP          # 0x390 = 912 B
EDITOR_ESI = [A.EDITOR_LO + n * 0xB4C for n in (0, 1, 24, 25, 30)]      # palette 0/1/24, brush 0/5
OTHER_ESI = [A.EDITOR_LO - 1, A.EDITOR_HI, 0x7B39E8, 0x881A24, 0x6AFC10, DATA + 0x100]

# ---------------------------------------------------------------- the proposed source edit (exact text)
OLD1 = """    mov     eax, dword ptr [{G_SCALE}]
    mov eax, dword ptr [0x66879c]
    nop
"""
NEW1 = """    mov eax, dword ptr [0x66879c]
"""
OLD2 = """    add     edx, edx
    cmp     [{CRED0}], edx
    jl      f1
    mov     byte ptr [{FL0}], 1
f1:
    cmp     [{CRED4}], edx
    jl      f2
    mov     byte ptr [{FL1}], 1
f2:
    cmp     [{CRED8}], edx
    jl      f3
    mov     byte ptr [{FL2}], 1
f3:
"""
NEW2 = """    add     edx, edx
    mov     eax, [esp+8]
    cmp     eax, {LO}
    jb      thr
    cmp     eax, {HI}
    jae     thr
    xor     edx, edx
thr:
    cmp     [{CRED0}], edx
    setge   byte ptr [{FL0}]
    cmp     [{CRED4}], edx
    setge   byte ptr [{FL1}]
    cmp     [{CRED8}], edx
    setge   byte ptr [{FL2}]
"""


def edits():
    """(old, new) text pairs applied to assemble_scenedit.asm_edremap()'s source -- the brief's edit list.
    1: drop the dead scale read + nop fossil (6 B).  2: editor range -> threshold 0; setge flag writes."""
    k = dict(G_SCALE=f"{A.G_SCALE:#x}", CRED0=f"{A.G_ED_CRED:#x}", CRED4=f"{A.G_ED_CRED + 4:#x}",
             CRED8=f"{A.G_ED_CRED + 8:#x}", FL0=f"{A.G_ED_FL:#x}", FL1=f"{A.G_ED_FL + 1:#x}",
             FL2=f"{A.G_ED_FL + 2:#x}", LO=f"{A.EDITOR_LO:#x}", HI=f"{A.EDITOR_HI:#x}")
    return [(OLD1.format(**k), NEW1.format(**k)), (OLD2.format(**k), NEW2.format(**k))]



def proposed_asm():
    src = A.asm_edremap()
    for old, new in edits():
        if src.count(old) == 0 and new in src:    # edit already applied to the assembler (2026-10-06)
            continue
        assert src.count(old) == 1, old
        src = src.replace(old, new)
    return src


def yaml_today_bytes():
    txt = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r"- id: thunk_ed_remap\n\s+offset: 0x10C60\n\s+bytes: \"([0-9A-F ]+)\"", txt)
    assert m, "thunk_ed_remap content entry not found in patches.yaml"
    return bytes(int(x, 16) for x in m.group(1).split())


TODAY = yaml_today_bytes()
PROPOSED = A.assemble(proposed_asm(), A.THUNK_ED_REMAP)


# ---------------------------------------------------------------- the law (today + proposed)
def enable_forced(credits, w):
    """The proposed scaling_laws.editor_face_enable(credits, w, forced=True): threshold 0."""
    try:
        return SL.editor_face_enable(credits, w, forced=True)
    except TypeError:                       # scaling_laws not yet edited: local port of the edit
        def c(top, bot):
            return credits.get((min(top, bot), max(top, bot)), 0)
        c_c9, c_68 = c(0xC9, 0x6D), c(0x6D, 0x68)
        c9 = c_c9 >= 0 and c_c9 >= c_68
        return {"f0": True, "a2": True, "e2": True, "c9": c9, "m68": (not c9) and c_68 >= 0}


def law(cols, g, forced):
    w = len(cols)
    credits = SL.editor_face_chain_credits(cols, g)
    flags = enable_forced(credits, w) if forced else SL.editor_face_enable(credits, w)
    if g <= 16:
        return [list(col) for col in cols], flags
    return [[SL.editor_face_remap_pixel(v, y, g, **flags) for y, v in enumerate(col)] for col in cols], flags


# ---------------------------------------------------------------- faces
def _game_pcx(name):
    try:
        import config
        from PIL import Image
        p = os.path.join(str(config.game_dir()), name)
        if not os.path.exists(p):
            return None
        im = Image.open(p)
        w, h = im.size
        d = im.tobytes()
        return [[(d[y * w + x] + 10) & 0xFF for x in range(w)] for y in range(h)]
    except Exception:
        return None


def editor_faces():
    """{name: (columns, native w, native h)} -- the 93 real faces, or {} without the game."""
    sheet = _game_pcx("interface.pcx")
    if sheet is None:
        return {}
    out = {}

    def cell(x0, y0, w, h):
        return [[sheet[y0 + yy][x0 + xx] for yy in range(h)] for xx in range(w)]
    for k in range(25):
        for st in range(3):
            out[f"pal{k:02d}_s{st}"] = (cell(350 + 44 * (k % 8), 245 + 57 * (k // 8) + 19 * st, 43, 18), 43, 18)
    for i in range(6):
        for st in range(3):
            out[f"red{i}_s{st}"] = (cell(465 + 25 * i, 438 + 25 * st, 24, 24), 24, 24)
    return out


def nn_zoom(cols, W, H):
    """The engine's button zoom (thunk_ksb_v2 -> GDI StretchBlt): centre-aligned NN, measured
    (pixel-exact against the 1600x1200 shot 20261004-203624 on all 25 un-/re-striped cells)."""
    sw, sh = len(cols), len(cols[0])
    return [[cols[min(((2 * X + 1) * sw) // (2 * W), sw - 1)][min(((2 * Y + 1) * sh) // (2 * H), sh - 1)]
             for Y in range(H)] for X in range(W)]


PAD = 0x41        # the native canvas rows/cols outside the sprite: black on the 1080 shot (pre-fill), a non-member


def zoomed(face, g):
    """What thunk_ed_remap sees: the seed cell is scale_px(w) x scale_px(h); thunk_btn_shrink descales it with
    btn_native_dim (ceil), the sprite is drawn at (0,0) of that native canvas (a pad row/column appears whenever
    the ceil over-recovers, e.g. 43x19 at g=22, measured on the 1080 shot), then the whole canvas is zoomed back
    by centre-aligned NN."""
    cols, w, h = face
    if g <= 16:
        return [list(c) for c in cols]
    W, H = SL.scale_px(w, g), SL.scale_px(h, g)
    nw, nh = SL.btn_native_dim(W, g), SL.btn_native_dim(H, g)
    assert nw >= w and nh >= h, (g, w, h, nw, nh)
    nat = [[PAD] * nh for _ in range(nw)]
    for x in range(w):
        for y in range(h):
            nat[x][y] = cols[x][y]
    return nn_zoom(nat, W, H)


def _nn_cols(top, bot, w, h, g, region_top=0, region_h=None, fill=0x30):
    if region_h is None:
        region_h = h - region_top
    cols = []
    for _x in range(w):
        col = []
        for y in range(h):
            if region_top <= y < region_top + region_h:
                src = ((y - region_top) * 16) // g
                col.append(top if src % 2 == 0 else bot)
            else:
                col.append(fill)
        cols.append(col)
    return cols


def _chevron_cols(top, bot, g, fill=0x30):
    b = SL.scale_px(24, g)
    cols = [[fill] * b for _ in range(b)]
    sw, sh = SL.scale_px(16, g), SL.scale_px(11, g)
    x0, y0 = (b - sw) // 2, (b - sh) // 2
    for yy in range(sh):
        src_row = (yy * 16) // g
        half = ((yy + 1) * sw) // (2 * sh)
        v = top if src_row % 2 == 0 else bot
        for xx in range(sw // 2 - half, sw // 2 + half + 1):
            if 0 <= xx < sw:
                cols[x0 + xx][y0 + yy] = v
    return cols


def _attack_face_cols(g):
    w, h = SL.scale_px(200, g), SL.scale_px(22, g)
    cols = _nn_cols(0xC9, 0x6D, w, h, g)
    for x in range(w):
        cols[x][0] = cols[x][h - 1] = 0x41
    for x in (0, w - 1):
        cols[x] = [0x41] * h
    y0, y1 = h // 3, (2 * h) // 3
    for x in range(w // 3, (2 * w) // 3, 3):
        for y in range(y0, y1):
            cols[x][y] = 0x41
    return cols


def other_faces(g):
    """The non-editor served set (synthetic, as test_scenedit_asm_parity models them) + solid art."""
    gg = max(g, 17)
    return {
        "chevron_a2ef": _chevron_cols(0xA2, 0xEF, gg),
        "chevron_f0b9": _chevron_cols(0xF0, 0xB9, gg),
        "attack_c96d": _attack_face_cols(gg),
        "locator_e0e2": _nn_cols(0xE0, 0xE2, SL.scale_px(24, gg), SL.scale_px(24, gg), gg, region_top=2,
                                 region_h=SL.scale_px(24, gg) - 4, fill=0xC4),
        "solid_f0_console": [[0xF0] * SL.scale_px(20, gg) for _ in range(SL.scale_px(30, gg))],
        "solid_red_halves": [[0xC9] * (SL.scale_px(24, gg) // 2) + [0x6D] * (SL.scale_px(24, gg) - SL.scale_px(24, gg) // 2)
                             for _ in range(SL.scale_px(24, gg))],
    }


# ---------------------------------------------------------------- emulation
_UC = {}          # one Uc per (g, byte variant), reused: ~3,000 fresh instances exhaust Unicorn's address space
                  # (AV in mem_map); keyed by the variant because Unicorn keeps JIT blocks for code rewritten at
                  # the same VA (today's bytes would run the proposed translation)


def _mk(g, code=b""):
    uc = _UC.get((g, id(code)))
    if uc is None:
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(0x400000, 0x300000)
        uc.mem_map(0x780000, 0x80000)
        uc.mem_map(A.PCAVE2, 0x30000)
        uc.mem_map(STACK, 0x10000)
        uc.mem_map(DATA, 0x40000)
        uc.mem_map(MARKER & ~0xFFF, 0x1000)
        uc.mem_write(A.G_SCALE, int(g).to_bytes(4, "little"))
        uc.mem_write(0x66879C, int(SL.stripe_period(g)).to_bytes(4, "little"))   # g_stripe_period cell
        _UC[(g, id(code))] = uc
    uc.mem_write(A.G_ED_CRED, b"\x00" * 0x40)           # the thunk re-zeroes these itself; belt and braces
    return uc


def _face(uc, cols):
    w, h = len(cols), len(cols[0])
    stride = w + 7
    buf, pix = DATA + 0x8000, DATA + 0x10000
    img = bytearray(stride * h)
    for x, col in enumerate(cols):
        for y, v in enumerate(col):
            img[y * stride + x] = v
    uc.mem_write(pix, bytes(img))
    uc.mem_write(buf + 0x54, pix.to_bytes(4, "little"))
    uc.mem_write(buf + 0x80, w.to_bytes(4, "little"))
    uc.mem_write(buf + 0x84, (-h).to_bytes(4, "little", signed=True))
    uc.mem_write(buf + 0x4A8, stride.to_bytes(4, "little"))
    uc.mem_write(A.G_FE_DST, buf.to_bytes(4, "little"))
    uc.mem_write(A.G_FE_W, w.to_bytes(4, "little"))
    uc.mem_write(A.G_FE_H, h.to_bytes(4, "little"))
    return pix, stride


def run_thunk(code, cols, g, esi):
    """Returns (output columns, registers-preserved, esp-restored)."""
    uc = _mk(g, code)
    pix, stride = _face(uc, cols)
    w, h = len(cols), len(cols[0])
    uc.mem_write(A.THUNK_ED_REMAP, code)           # identical bytes every time within this instance
    esp = STACK + 0x8000 - 4
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    regs = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: esi, UC_X86_REG_EDI: 0x33333333, UC_X86_REG_EBP: 0x44444444}
    uc.reg_write(UC_X86_REG_ESP, esp)
    for r, v in regs.items():
        uc.reg_write(r, v)
    uc.emu_start(A.THUNK_ED_REMAP, MARKER, count=20_000_000)
    img = uc.mem_read(pix, stride * h)
    out = [[img[y * stride + x] for y in range(h)] for x in range(w)]
    ok_regs = all(uc.reg_read(r) == v for r, v in regs.items())
    ok_esp = uc.reg_read(UC_X86_REG_ESP) == esp + 4
    return out, ok_regs, ok_esp


# ---------------------------------------------------------------- tests
def test_source_in_sync_and_slot():
    assert A.assemble(A.asm_edremap(), A.THUNK_ED_REMAP) == TODAY, "assemble_scenedit.asm_edremap != yaml"
    assert len(TODAY) in (901, 909)                  # 901 B before the v2 bake, 909 B since 2026-10-06
    assert len(PROPOSED) <= SLOT, (len(PROPOSED), SLOT)
    assert len(PROPOSED) == 909
    # the g<=16 gate is the first instruction (cmp [g_popup_scale_num], 0x10 / jle r0) -- same opcode bytes;
    # its rel32 moves with the growth and must land on the final ret
    assert PROPOSED[:9] == TODAY[:9] == bytes.fromhex("833d408766001" "00f8e")
    rel = int.from_bytes(PROPOSED[9:13], "little")
    assert PROPOSED[13 + rel - 1 + 0] == 0xC3 or PROPOSED[13 + rel] == 0xC3


FACES = editor_faces()
needs_game = pytest.mark.skipif(not FACES, reason="interface.pcx not reachable (game dir)")


@needs_game
def test_ground_truth_parity_pure():
    """Every pair pixel of all 93 faces sits on the row-parity mask -> a force restripe regenerates, never damages."""
    tops = {0xB9: 0, 0xF0: 1, 0xA2: 0, 0xEF: 1, 0xE0: 0, 0xE2: 1, 0xE1: 1, 0xC9: 0, 0x68: 1}
    assert len(FACES) == 93
    for name, (cols, w, h) in FACES.items():
        members = {v for col in cols for v in col if v in tops or v == 0x6D}
        for col in cols:
            for y, v in enumerate(col):
                if v == 0xE1:              # one stray on pal02_s2 row 6: owned by the e0/e2 family, phase-folded
                    continue
                if v in tops:
                    assert (y & 1) == tops[v], (name, y, hex(v))
                elif v == 0x6D:            # 6D: bottom of c9/6d (odd), top of 6d/68 (even)
                    assert (y & 1) == (1 if 0xC9 in members else 0), (name, y)
                else:
                    assert v == 0xC6 or v in (0xBC, 0xC5, 0xA4, 0xC4, 0x53, 0x54), (name, hex(v))


@needs_game
@pytest.mark.parametrize("g", GS)
def test_editor_faces_forced_equal_law(g):
    """Proposed bytes with an editor esi: output == forced law on all 93 real faces; registers/stack kept."""
    misses_fixed = 0
    for i, (name, face) in enumerate(FACES.items()):
        cols = zoomed(face, g)
        esi = EDITOR_ESI[i % len(EDITOR_ESI)]
        out, ok_regs, ok_esp = run_thunk(PROPOSED, cols, g, esi)
        want, flags = law(cols, g, forced=True)
        assert ok_regs and ok_esp, name
        assert out == want, (g, name, flags)
        if g > 16:
            today_want, _ = law(cols, g, forced=False)
            if today_want != want:
                misses_fixed += 1
                assert name[:5] in ("pal01", "pal11", "pal21", "pal22"), (g, name)
            # every pair pixel is now on the stripe grid (no 1/2-row NN beat survives)
            for col in out:
                for y, v in enumerate(col):
                    if v in (0xF0, 0xA2, 0xE0, 0xC9):
                        assert SL.stripe_top(y, g) or (v == 0xC9 and not flags["c9"]), (name, y, hex(v))
                    if v in (0xB9, 0xEF, 0xE2, 0x68):
                        assert not SL.stripe_top(y, g), (name, y, hex(v))
    if g > 16:
        # cells 1 / 11 / 22 (detector misses) + 21 (hatch) x 3 states; at exactly 2x (g=32) the a2/ef and e0/e2
        # faces' raw NN is already phase-aligned with their canonical tops, so only the f0/b9 state changes there
        assert misses_fixed == (4 if g == 32 else 12), misses_fixed


@needs_game
@pytest.mark.parametrize("g", GS)
def test_editor_faces_today_equal_today_law(g):
    """The yaml bytes reproduce the law of their state: detector-gated before the v2 bake, forced since 2026-10-06."""
    applied = TODAY == PROPOSED
    for i, (name, face) in enumerate(FACES.items()):
        cols = zoomed(face, g)
        out, ok_regs, ok_esp = run_thunk(TODAY, cols, g, EDITOR_ESI[i % len(EDITOR_ESI)])
        want, _ = law(cols, g, forced=applied)
        assert ok_regs and ok_esp and out == want, (g, name)


@pytest.mark.parametrize("g", GS)
def test_other_callers_byte_identical(g):
    """Outside the editor range the proposed bytes match today's output pixel for pixel AND the law."""
    faces = dict(other_faces(g))
    if FACES:                                         # editor-shaped art under a foreign esi: still detector-gated
        for k in ("pal01_s0", "pal11_s1", "pal21_s2", "pal22_s0", "red1_s1", "pal00_s0"):
            faces[k] = zoomed(FACES[k], g)
    for name, cols in faces.items():
        for esi in OTHER_ESI:
            new, ok_regs, ok_esp = run_thunk(PROPOSED, cols, g, esi)
            old, ok_regs2, ok_esp2 = run_thunk(TODAY, cols, g, esi)
            assert ok_regs and ok_esp and ok_regs2 and ok_esp2, (name, hex(esi))
            assert new == old, (g, name, hex(esi))
            want, _ = law(cols, g, forced=False)
            assert new == want, (g, name, hex(esi))


@pytest.mark.parametrize("esi", [A.EDITOR_LO, A.EDITOR_HI - 1, A.EDITOR_LO - 1, A.EDITOR_HI])
def test_range_edges(esi):
    """Half-open [EDITOR_LO, EDITOR_HI): the pixel-exact edge of the force path on a weak (missed-shaped) face."""
    g = 25
    cols = (zoomed(FACES["pal01_s0"], g) if FACES
            else _nn_cols(0xF0, 0xB9, SL.scale_px(43, g), SL.scale_px(18, g), g, region_top=20, region_h=6, fill=0xC6))
    out, _, _ = run_thunk(PROPOSED, cols, g, esi)
    forced = A.EDITOR_LO <= esi < A.EDITOR_HI
    assert out == law(cols, g, forced=forced)[0]
    if not forced:
        assert out == run_thunk(TODAY, cols, g, esi)[0]


def test_g16_noop_both():
    cols = _nn_cols(0xF0, 0xB9, 43, 18, 16)
    for esi in EDITOR_ESI[:1] + OTHER_ESI[:1]:
        for code in (TODAY, PROPOSED):
            out, ok_regs, ok_esp = run_thunk(code, cols, 16, esi)
            assert ok_regs and ok_esp and out == cols


def test_null_dest_returns():
    uc = _mk(40, PROPOSED)
    uc.mem_write(A.G_FE_DST, bytes(4))
    uc.mem_write(A.THUNK_ED_REMAP, PROPOSED)
    esp = STACK + 0x8000 - 4
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, A.EDITOR_LO)
    uc.emu_start(A.THUNK_ED_REMAP, MARKER, count=1000)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4


SHOTS = {   # (res, file, g, MainWin strip offset on the screen (dx, dy) -- measured)
    "1600x1200": ("terranx_pracx_1600x1200_20261004-203624.png", 25, 0, 799),
    "1920x1080": ("terranx_pracx_1920x1080_20261004-203825.png", 22, 256, 727),
}


@needs_game
@pytest.mark.parametrize("res", sorted(SHOTS))
def test_model_matches_the_shots(res):
    """Measure, don't model: the padded-native centre-NN zoom + today's law reproduce all 25 palette cells
    (any of the 3 states) and the 6 brush cells of the shot exactly -- the 4 un-restriped cells raw, the 21
    restriped ones through the law (g=25: 43x18 native, no pad; g=22: 43x19, one black pad row)."""
    fname, g, dx, dy = SHOTS[res]
    shot = ROOT / "screenshots" / "scanlines_after_20261004" / res / fname
    if not shot.exists():
        pytest.skip(f"{shot} absent")
    from PIL import Image
    pal = (ROOT / "_portrait_preview" / "hd" / "game_palette_rgbquad.bin").read_bytes()
    inv = {}
    for i in range(256):
        inv.setdefault((pal[i * 4 + 2], pal[i * 4 + 1], pal[i * 4 + 0]), i)
    im = Image.open(shot).convert("RGB")
    px = im.load()
    seeds = SL.editor_panel_seeds(g)

    def read(l, t, W, H):
        return [[inv.get(px[l + dx + X, t + dy + Y], -1) for Y in range(H)] for X in range(W)]

    def norm(cols):                                   # index 0 and 0x41 are both (0,0,0): compare as black
        return [[0x41 if v == 0 else v for v in col] for col in cols]

    raw_cells, law_cells = 0, 0
    for k in range(25):
        l, t, _r, _b = seeds["pal"][k]
        W, H = seeds["cell"]
        got = norm(read(l, t, W, H))
        hit = None
        for st in range(3):                            # the shot's cell 0 is the SELECTED (s2) face
            z = zoomed(FACES[f"pal{k:02d}_s{st}"], g)
            want, flags = law(z, g, forced=False)
            if got == norm(want):
                hit = (flags, z)
                break
        assert hit is not None, (res, k)
        flags, z = hit
        if any(flags.values()):
            law_cells += 1
        else:
            raw_cells += 1
            assert got == norm(z)
    assert (raw_cells, law_cells) == (4, 21)
    for i in range(6):
        l, t, _r, _b = seeds["red"][i]
        R = seeds["red_cell"]
        got = norm(read(l, t, R, R))
        assert any(got == norm(law(zoomed(FACES[f"red{i}_s{st}"], g), g, forced=False)[0]) for st in range(3)), (res, i)
