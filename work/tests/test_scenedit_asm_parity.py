"""Differential: the scenario-editor bake thunks vs the Python laws, emulated.

Eight thunks ship for the scenedit arc (assemble_scenedit.py):

  thunk_ed_linestep    su(13,g) line step / native tail-jmp
  thunk_diplo_bracket  g_popup_active refcount around DiploEditWin_exec
  thunk_diplo_btnfont  font0 stamp before the sole diplo button render
  thunk_ed_painter     law unions/info-rect copy at painter entry
  thunk_ed_seeds       25+6 seed rects + union/info stash (editor_panel_seeds)
  thunk_ed_immfix      VP bootstrap + 31-imm su() rewrite (identity at g=16)
  thunk_ed_remap       face-pair chain detection + phase restripe
                       (editor_face_chain_credits / _enable / _remap_pixel)
  thunk_diplo_pdsclear VANILLA pds-leak fix: clear PopupDialogState, jmp dtor
  thunk_btn_gate v7 / thunk_btn_stripes v5 (in-place upgrades)

Every thunk is emulated on its REAL assembled bytes at its REAL VA.
Skips if keystone/unicorn are absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone not installed")
unicorn = pytest.importorskip("unicorn", reason="unicorn not installed")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc, UcError  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_ESI, UC_X86_REG_ESP)

import assemble_scenedit as A  # noqa: E402

STACK = 0x00B00000
DATA = 0x00C00000
MARKER = 0x00DEAD00

GS = [17, 22, 25, 32, 40]


def _ks(asm, va=0):
    from keystone import KS_ARCH_X86, KS_MODE_32, Ks
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm, va)
    return bytes(enc)


def _mk(g):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(0x400000, 0x300000)          # engine (.text/_SELFMOD/.rdata)
    uc.mem_map(0x780000, 0x80000)           # MainWin + editor button statics
    uc.mem_map(A.PCAVE2, 0x12000)           # pcave2 (grown 0x11000->0x12000 2026-08-14)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(DATA, 0x40000)
    uc.mem_map(MARKER & ~0xFFF, 0x1000)
    uc.mem_write(A.G_SCALE, int(g).to_bytes(4, "little"))
    uc.mem_write(A.ENSURE_SCALE, b"\xC3")   # ensure_scale stub (EAX-only)
    return uc


def _run(uc, va, code, *, esp=STACK + 0x8000, regs=(), until=MARKER,
         push_ret=True, count=2_000_000):
    uc.mem_write(va, code)
    if push_ret:
        esp -= 4
        uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, esp)
    for r, v in regs:
        uc.reg_write(r, v & 0xFFFFFFFF)
    uc.emu_start(va, until, count=count)
    return uc


def _r32(uc, addr):
    return int.from_bytes(uc.mem_read(addr, 4), "little")


# --------------------------------------------------------------- linestep
@pytest.mark.parametrize("g", [16] + GS)
def test_linestep(g):
    uc = _mk(g)
    uc.mem_write(A.LINE_HEIGHT, b"\xB8\x37\x00\x00\x00\xC3")   # native stub: 0x37
    code = A.assemble(A.asm_linestep(), A.PCAVE2 + A.OFF_LINESTEP)
    _run(uc, A.PCAVE2 + A.OFF_LINESTEP, code)
    eax = uc.reg_read(UC_X86_REG_EAX)
    if g <= 16:
        assert eax == 0x37                    # tail-jmp'd the native callee
    else:
        assert eax == SL.scale_px(13, g)


# ---------------------------------------------------------------- bracket
@pytest.mark.parametrize("g", [16, 25, 40])
def test_bracket(g):
    uc = _mk(g)
    # exec stub: record g_popup_active + arg, then thiscall RET 4
    stub = _ks(
        f"mov eax, dword ptr [{A.G_POPUP_ACT:#x}]\n"
        f"mov dword ptr [{DATA + 0x10:#x}], eax\n"
        "mov eax, [esp+4]\n"
        f"mov dword ptr [{DATA + 0x14:#x}], eax\n"
        "mov eax, 0x77\n"
        "ret 4\n", A.DIPLO_EXEC)
    uc.mem_write(A.DIPLO_EXEC, stub)
    code = A.assemble(A.asm_bracket(), A.PCAVE2 + A.OFF_BRACKET)
    # emulate the call site: [ret][arg]
    esp = STACK + 0x8000
    uc.mem_write(esp - 8, MARKER.to_bytes(4, "little"))
    uc.mem_write(esp - 4, (0xCAFE).to_bytes(4, "little"))
    uc.mem_write(A.PCAVE2 + A.OFF_BRACKET, code)
    uc.reg_write(UC_X86_REG_ESP, esp - 8)
    uc.emu_start(A.PCAVE2 + A.OFF_BRACKET, MARKER, count=10000)
    assert _r32(uc, DATA + 0x14) == 0xCAFE          # arg reached the callee
    assert uc.reg_read(UC_X86_REG_EAX) == 0x77      # retval preserved
    assert uc.reg_read(UC_X86_REG_ESP) == esp       # RET 4 semantics kept
    inside = _r32(uc, DATA + 0x10)
    after = _r32(uc, A.G_POPUP_ACT)
    if g > 16:
        assert inside == 1 and after == 0           # armed during, disarmed after
    else:
        assert inside == 0 and after == 0           # native path never arms


# --------------------------------------------------------------- pdsclear
@pytest.mark.parametrize("g", [16, 40])
def test_pdsclear(g):
    # g-INDEPENDENT by design: the pds=6 leak is vanilla's, native included.
    uc = _mk(g)
    # dtor stub: record ecx (this), return a token
    stub = _ks(
        f"mov dword ptr [{DATA + 0x20:#x}], ecx\n"
        "mov eax, 0x99\n"
        "ret\n", A.DIPLO_DTOR)
    uc.mem_write(A.DIPLO_DTOR, stub)
    uc.mem_write(A.PDS, (6).to_bytes(4, "little"))          # the leaked state
    code = A.assemble(A.asm_pdsclear(), A.PCAVE2 + A.OFF_PDSCLEAR)
    assert len(code) == 12
    esp = STACK + 0x8000
    _run(uc, A.PCAVE2 + A.OFF_PDSCLEAR, code, esp=esp,
         regs=[(UC_X86_REG_ECX, 0xBEEF)])
    assert _r32(uc, A.PDS) == 0                             # leak cleared
    assert _r32(uc, DATA + 0x20) == 0xBEEF                  # dtor got its this
    assert uc.reg_read(UC_X86_REG_EAX) == 0x99              # dtor retval kept
    assert uc.reg_read(UC_X86_REG_ESP) == esp               # plain CALL/RET balance


# ---------------------------------------------------------------- btnfont
@pytest.mark.parametrize("g", [16, 22, 40])
def test_btnfont(g):
    uc = _mk(g)
    # v2: t_ffn(12, 0) (the face-law drop-in; NATIVE args) -- record the args, return a fake font
    ff = _ks(f"mov eax, dword ptr [esp+4]\nmov dword ptr [{DATA + 0x3000:#x}], eax\nmov eax, dword ptr [esp+8]\n"
             f"mov dword ptr [{DATA + 0x3004:#x}], eax\nmov eax, 0xF00D\nret\n", A.T_FFN)
    try:
        uc.mem_map(A.T_FFN & ~0xFFF, 0x1000)
    except Exception:  # noqa: BLE001
        pass
    uc.mem_write(A.T_FFN, ff)
    vtbl = DATA + 0x1000
    fn = DATA + 0x1100
    btn = DATA + 0x2000
    uc.mem_write(fn, b"\xC3")
    uc.mem_write(vtbl + 0xF8, fn.to_bytes(4, "little"))
    code = A.assemble(A.asm_btnfont(), A.PCAVE2 + A.OFF_BTNFONT)
    _run(uc, A.PCAVE2 + A.OFF_BTNFONT, code,
         regs=[(UC_X86_REG_EAX, vtbl), (UC_X86_REG_EDI, btn),
               (UC_X86_REG_ECX, btn)])
    font0 = _r32(uc, btn + 0x970)
    assert font0 == (0xF00D if g > 16 else 0)
    if g > 16:
        assert (_r32(uc, DATA + 0x3000), _r32(uc, DATA + 0x3004)) == (12, 0)     # the NATIVE default label font (Arial 12 regular)


# ---------------------------------------------------------------- painter
def _paint_setup(uc, *, mode=0x3EA, stamp=None, g=40):
    mw = A.MAINWIN
    uc.mem_write(mw + 0x1E8FC, int(mode).to_bytes(4, "little"))
    s = SL.editor_panel_seeds(g)
    for i, v in enumerate(s["pal_union"]):
        uc.mem_write(A.G_ED_PALU + 4 * i, v.to_bytes(4, "little", signed=True))
    for i, v in enumerate(s["red_union"]):
        uc.mem_write(A.G_ED_REDU + 4 * i, v.to_bytes(4, "little", signed=True))
    for i, v in enumerate((s["info_left"], s["info_top"], s["info_bottom"])):
        uc.mem_write(A.G_ED_INFO + 4 * i, v.to_bytes(4, "little", signed=True))
    st = stamp if stamp is not None else g
    uc.mem_write(A.G_ED_STAMP, int(st).to_bytes(4, "little"))
    for off in range(0xD4C, 0xD7C, 4):
        uc.mem_write(mw + off, (0xDEAD).to_bytes(4, "little"))
    return s


@pytest.mark.parametrize("g", [25, 40])
def test_painter_writes_law_rects(g):
    uc = _mk(g)
    s = _paint_setup(uc, g=g)
    code = A.assemble(A.asm_painter(), A.PCAVE2 + A.OFF_PAINTER)
    esp = STACK + 0x8000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))   # caller ret of the vfn
    _run(uc, A.PCAVE2 + A.OFF_PAINTER, code, esp=esp, push_ret=False,
         regs=[(UC_X86_REG_ECX, A.MAINWIN)], until=A.PAINTER_RESUME,
         count=10000)
    mw = A.MAINWIN
    got_pal = [_r32(uc, mw + 0xD4C + 4 * i) for i in range(4)]
    got_red = [_r32(uc, mw + 0xD5C + 4 * i) for i in range(4)]
    assert got_pal == list(s["pal_union"])
    assert got_red == list(s["red_union"])
    assert _r32(uc, mw + 0xD6C) == s["info_left"]
    assert _r32(uc, mw + 0xD70) == s["info_top"]
    assert _r32(uc, mw + 0xD78) == s["info_bottom"]
    assert _r32(uc, mw + 0xD74) == 0xDEAD             # RIGHT edge stays engine's
    # vanilla prologue contract at the resume point
    assert uc.reg_read(UC_X86_REG_ESP) == esp - 0x14
    assert uc.reg_read(UC_X86_REG_EBP) == esp - 4
    assert uc.reg_read(UC_X86_REG_ECX) == A.MAINWIN


@pytest.mark.parametrize("why,mode,stamp,g,ecx", [
    ("wrong window", 0x3EA, 40, 40, DATA + 0x3000),
    ("wrong mode", 0x123, 40, 40, A.MAINWIN),
    ("native g", 0x3EA, 40, 16, A.MAINWIN),
    ("stale stamp", 0x3EA, 25, 40, A.MAINWIN),
])
def test_painter_noop_paths(why, mode, stamp, g, ecx):
    uc = _mk(g)
    if ecx != A.MAINWIN:
        uc.mem_write(ecx + 0x1E8FC, int(mode).to_bytes(4, "little"))
    _paint_setup(uc, mode=mode, stamp=stamp, g=max(g, 17))
    code = A.assemble(A.asm_painter(), A.PCAVE2 + A.OFF_PAINTER)
    esp = STACK + 0x8000
    uc.mem_write(esp, MARKER.to_bytes(4, "little"))
    _run(uc, A.PCAVE2 + A.OFF_PAINTER, code, esp=esp, push_ret=False,
         regs=[(UC_X86_REG_ECX, ecx)], until=A.PAINTER_RESUME, count=10000)
    for off in range(0xD4C, 0xD7C, 4):
        assert _r32(uc, A.MAINWIN + off) == 0xDEAD, why


# ------------------------------------------------------------------ seeds
@pytest.mark.parametrize("g", [16] + GS)
def test_seeds_match_the_law(g):
    """thunk_ed_seeds and its tail t_ed_redchain (2026-10-25 W3A: the seeds' `push; ret` resumes through it -- the red
    group chained off the palette, assemble_mirror_pairs.py) == editor_panel_seeds."""
    import assemble_mirror_pairs as MP
    uc = _mk(g)
    uc.mem_map(A.PCAVE2 + 0x38000, 0x1000)          # the W3A region (pcave2 grown to 0x3C000)
    syms = {"g_popup_scale_num": A.G_SCALE, "thunk_cw_seeds": 0, "g_ed_stamp": A.G_ED_STAMP, "g_ed_p3": A.G_ED_P3,
            "g_ed_redu": A.G_ED_REDU, "g_ed_info": A.G_ED_INFO}
    assert A.SEEDS_TAIL == MP.PCAVE2 + MP.HELPERS["t_ed_redchain"][0]
    uc.mem_write(A.SEEDS_TAIL, MP.assemble("t_ed_redchain", syms))
    uc.mem_write(A.THUNK_ED_IMMFIX, b"\xC3")          # immfix tested separately
    uc.mem_write(A.MW_PAL, b"\xCC" * (25 * 16))
    uc.mem_write(A.MW_RED, b"\xCC" * (6 * 16))
    code = A.assemble(A.asm_seeds(), A.PCAVE2 + A.OFF_SEEDS)
    _run(uc, A.PCAVE2 + A.OFF_SEEDS, code, push_ret=False,
         regs=[(UC_X86_REG_ESI, A.MAINWIN)], until=A.SEEDS_RESUME,
         count=200000)
    # displaced-instruction replay contract
    assert uc.reg_read(UC_X86_REG_EAX) == 0
    assert uc.reg_read(UC_X86_REG_ECX) == A.MAINWIN + 0x21E2C
    assert uc.reg_read(UC_X86_REG_ESI) == A.MAINWIN
    if g <= 16:
        assert uc.mem_read(A.MW_PAL, 25 * 16) == b"\xCC" * 400
        assert uc.mem_read(A.MW_RED, 6 * 16) == b"\xCC" * 96
        assert _r32(uc, A.G_ED_STAMP) == 0
        return
    s = SL.editor_panel_seeds(g)
    for i, rect in enumerate(s["pal"]):
        got = [_r32(uc, A.MW_PAL + 16 * i + 4 * k) for k in range(4)]
        assert got == list(rect), f"pal[{i}]"
    for i, rect in enumerate(s["red"]):
        got = [_r32(uc, A.MW_RED + 16 * i + 4 * k) for k in range(4)]
        assert got == list(rect), f"red[{i}]"
    assert [_r32(uc, A.G_ED_PALU + 4 * i) for i in range(4)] == list(s["pal_union"])
    assert [_r32(uc, A.G_ED_REDU + 4 * i) for i in range(4)] == list(s["red_union"])
    assert _r32(uc, A.G_ED_INFO) == s["info_left"]
    assert _r32(uc, A.G_ED_INFO + 4) == s["info_top"]
    assert _r32(uc, A.G_ED_INFO + 8) == s["info_bottom"]
    assert _r32(uc, A.G_ED_STAMP) == g


# ----------------------------------------------------------------- immfix
def _immfix_env(uc, *, gpa_null=False):
    lla = 0x66A000
    gpa = 0x66A020
    vps = 0x66A040
    uc.mem_write(lla, _ks("mov eax, 0x12340000\nret 4\n", lla))
    if gpa_null:
        uc.mem_write(gpa, _ks("xor eax, eax\nret 8\n", gpa))
    else:
        uc.mem_write(gpa, _ks(f"mov eax, {vps:#x}\nret 8\n", gpa))
    uc.mem_write(vps, _ks("mov eax, 1\nret 16\n", vps))
    uc.mem_write(A.IAT_LOADLIB, lla.to_bytes(4, "little"))
    uc.mem_write(A.IAT_GETPROC, gpa.to_bytes(4, "little"))
    uc.mem_write(A.G_ED_IMMTAB, A.immtab_bytes())
    for addr, _n, kind in A.IMMTAB:
        uc.mem_write(addr, b"\xCC" * (4 if kind == 1 else 1))


@pytest.mark.parametrize("g", [16, 22, 40])
def test_immfix_writes_su_values(g):
    uc = _mk(g)
    _immfix_env(uc)
    code = A.assemble(A.asm_immfix(), A.THUNK_ED_IMMFIX)
    _run(uc, A.THUNK_ED_IMMFIX, code, count=100000)
    assert _r32(uc, A.G_VP_DONE) == 1
    for addr, native, kind in A.IMMTAB:
        want = SL.scale_px(native, g)
        if kind == 1:
            assert _r32(uc, addr) == want, f"{addr:#x}"
        elif kind == 0:
            assert uc.mem_read(addr, 1)[0] == want & 0xFF, f"{addr:#x}"
        else:
            assert uc.mem_read(addr, 1)[0] == (-want) & 0xFF, f"{addr:#x}"
        if g == 16:   # identity: byte-restores vanilla
            v = want if kind != 2 else (-native) & 0xFFFFFFFF
            assert (v & 0xFF) == ((native if kind != 2 else -native) & 0xFF)


def test_immfix_bails_clean_when_bootstrap_fails():
    uc = _mk(40)
    _immfix_env(uc, gpa_null=True)
    code = A.assemble(A.asm_immfix(), A.THUNK_ED_IMMFIX)
    _run(uc, A.THUNK_ED_IMMFIX, code, count=100000)
    assert _r32(uc, A.G_VP_DONE) == 0
    for addr, _n, kind in A.IMMTAB:      # ZERO writes on the bail path
        assert uc.mem_read(addr, 1)[0] == 0xCC, f"{addr:#x}"


# ---------------------------------------------------------------- ed_remap
def _face(uc, cols, *, w=None, h=None, stride=None):
    """Install a fake button Buffer at DATA and its pixels from columns."""
    w = w if w is not None else len(cols)
    h = h if h is not None else len(cols[0])
    stride = stride if stride is not None else w + 7
    buf = DATA + 0x8000
    pix = DATA + 0x10000
    img = bytearray(stride * h)
    for x, col in enumerate(cols):
        for y, v in enumerate(col):
            img[y * stride + x] = v
    uc.mem_write(pix, bytes(img))
    uc.mem_write(buf + 0x54, pix.to_bytes(4, "little"))
    uc.mem_write(buf + 0x80, len(cols).to_bytes(4, "little"))
    uc.mem_write(buf + 0x84, (-h).to_bytes(4, "little", signed=True))
    uc.mem_write(buf + 0x4A8, stride.to_bytes(4, "little"))
    uc.mem_write(A.G_FE_DST, buf.to_bytes(4, "little"))
    uc.mem_write(A.G_FE_W, int(w).to_bytes(4, "little"))
    uc.mem_write(A.G_FE_H, int(h).to_bytes(4, "little"))
    return pix, stride, h


def _model(cols, g):
    w = len(cols)
    credits = SL.editor_face_chain_credits(cols, g)
    flags = SL.editor_face_enable(credits, w)
    out = []
    for col in cols:
        out.append([SL.editor_face_remap_pixel(v, y, g, **flags)
                    for y, v in enumerate(col)])
    return out, flags


def _run_remap(uc, g):
    code = A.assemble(A.asm_edremap(), A.THUNK_ED_REMAP)
    _run(uc, A.THUNK_ED_REMAP, code, count=8_000_000)


def _check(uc, pix, stride, cols, g):
    want, flags = _model(cols, g)
    h = len(cols[0])
    img = uc.mem_read(pix, stride * h)
    for x in range(len(cols)):
        for y in range(h):
            got = img[y * stride + x]
            assert got == want[x][y], \
                f"g={g} ({x},{y}): {cols[x][y]:02x} -> {got:02x} " \
                f"want {want[x][y]:02x} flags={flags}"


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


@pytest.mark.parametrize("g", [22, 25, 40])
@pytest.mark.parametrize("top,bot", list(SL.EDITOR_FACE_PAIRS.items()))
def test_edremap_restripes_each_family(g, top, bot):
    uc = _mk(g)
    w, h = SL.scale_px(43, g), SL.scale_px(18, g)
    cols = _nn_cols(top, bot, w, h, g, region_top=2, region_h=h - 4)
    pix, stride, _ = _face(uc, cols)
    _run_remap(uc, g)
    _check(uc, pix, stride, cols, g)
    # and the family really did enable (guards a silent no-op "pass")
    _w, flags = _model(cols, g)
    assert any(flags.values())


@pytest.mark.parametrize("g", [25, 40])
def test_edremap_leaves_solid_art_alone(g):
    uc = _mk(g)
    w, h = SL.scale_px(24, g), SL.scale_px(24, g)
    cols = [[0xC9] * (h // 2) + [0x6D] * (h - h // 2) for _ in range(w)]
    pix, stride, _ = _face(uc, cols)
    _run_remap(uc, g)
    _check(uc, pix, stride, cols, g)          # model says: untouched
    img = uc.mem_read(pix, stride * h)
    assert img[0] == 0xC9 and img[(h - 1) * stride] == 0x6D


@pytest.mark.parametrize("g", [22, 40])
def test_edremap_e1_strays_fold_into_e0e2(g):
    uc = _mk(g)
    w, h = SL.scale_px(43, g), SL.scale_px(18, g)
    cols = _nn_cols(0xE0, 0xE2, w, h, g)
    for x in range(0, w, 5):                  # sprinkle E1 strays
        cols[x][h // 2] = 0xE1
    pix, stride, _ = _face(uc, cols)
    _run_remap(uc, g)
    _check(uc, pix, stride, cols, g)
    img = uc.mem_read(pix, stride * h)
    for x in range(len(cols)):                # no E1 survives an enabled e0/e2
        for y in range(h):
            assert img[y * stride + x] != 0xE1


@pytest.mark.parametrize("g", [25, 40])
def test_edremap_red_arbitration(g):
    uc = _mk(g)
    w, h = SL.scale_px(24, g), SL.scale_px(24, g)
    for top, bot in ((0xC9, 0x6D), (0x6D, 0x68)):
        cols = _nn_cols(top, bot, w, h, g)
        pix, stride, _ = _face(uc, cols)
        _run_remap(uc, g)
        _check(uc, pix, stride, cols, g)


def test_edremap_g16_and_null_are_noops():
    uc = _mk(16)
    cols = _nn_cols(0xF0, 0xB9, 20, 20, 16)
    pix, stride, h = _face(uc, cols)
    before = bytes(uc.mem_read(pix, stride * h))
    _run_remap(uc, 16)
    assert bytes(uc.mem_read(pix, stride * h)) == before
    uc2 = _mk(40)
    uc2.mem_write(A.G_FE_DST, (0).to_bytes(4, "little"))
    code = A.assemble(A.asm_edremap(), A.THUNK_ED_REMAP)
    _run(uc2, A.THUNK_ED_REMAP, code, count=1000)   # must just return


@pytest.mark.parametrize("g", [40])
def test_edremap_clamps_w_to_buffer(g):
    uc = _mk(g)
    w, h = 30, 30
    cols = _nn_cols(0xA2, 0xEF, w, h, g)
    pix, stride, _ = _face(uc, cols)
    uc.mem_write(A.G_FE_W, (w + 500).to_bytes(4, "little"))   # oversized rect
    _run_remap(uc, g)
    _check(uc, pix, stride, cols, g)          # clamped to buf W == model


# ----------------------------------------------------------- btn_gate v7
def _gate_bytes():
    prefix = A.assemble(A.GATE_PREFIX, A.PCAVE2 + 0xA9E0)
    v6 = bytes(int(x, 16) for x in A.BTN_GATE_V6.split())
    return prefix + v6


@pytest.mark.parametrize("esi,want", [
    (0x7B7264, 1),            # editor range lo
    (0x7CD097, 1),            # editor range hi-1
    (0x7B7263, 0),            # below range -> v6 body -> plain no
    (0x7CD098, 0),            # at range end -> v6 body
    (0x7B5080, 1),            # v6 static (below the new range)
    (DATA + 0x100, 0),        # neutral button, no flags
])
def test_gate_v7(esi, want):
    uc = _mk(40)
    code = _gate_bytes()
    # neutral esi zone + zeroed flag globals (all inside mapped regions)
    for flag in (A.PCAVE2 + 0x530, 0xA10800, 0xA0D2D0, 0xA0E3A0):
        uc.mem_write(flag, b"\x00" * 4)
    _run(uc, A.PCAVE2 + 0xA9E0, code, regs=[(UC_X86_REG_ESI, esi)],
         count=1000)
    assert uc.reg_read(UC_X86_REG_EAX) == want


def test_gate_v7_popup_active_still_wins():
    uc = _mk(40)
    uc.mem_write(A.G_POPUP_ACT, (1).to_bytes(4, "little"))
    for flag in (0xA10800, 0xA0D2D0, 0xA0E3A0):
        uc.mem_write(flag, b"\x00" * 4)
    _run(uc, A.PCAVE2 + 0xA9E0, _gate_bytes(),
         regs=[(UC_X86_REG_ESI, DATA + 0x100)], count=1000)
    assert uc.reg_read(UC_X86_REG_EAX) == 1


# -------------------------------------------------------- btn_stripes v5
def _stripes_env(uc):
    log = DATA + 0x20000
    uc.mem_write(log, b"\x00" * 64)

    def stub(ident, va, ret="ret"):
        return _ks(
            f"mov eax, dword ptr [{log:#x}]\n"
            f"mov dword ptr [{log:#x}+4+eax*4], {ident}\n"
            f"inc dword ptr [{log:#x}]\n"
            f"{ret}\n", va)

    for ident, name in ((1, "thunk_btn_devfill"), (2, "thunk_ed_remap"),
                        (3, "thunk_fe_pair_remap"), (4, "thunk_sbarrow_bg")):
        va = A.STRIPES_SYMS.get(name, SBARROW_BG_TEST)
        uc.mem_write(va, stub(ident, va))
    uc.mem_write(FACE_OWN_TEST, _face_own_code())          # v14: the REAL t_face_own (position-independent) in the window
    return log


SBARROW_BG_TEST = A.PCAVE2 + 0x11400      # thunk_sbarrow_bg (assemble_popup_sb.SBARROW_BG_OFF)
FACE_OWN_TEST = A.PCAVE2 + 0x11800        # t_face_own (assemble_face_own, live at 0x3E640) copied into the mapped window
_FACE_OWN = []


def _face_own_code():
    """assemble_face_own.asm_face_own assembled at FACE_OWN_TEST: relative branches only, absolute operands are engine
    cells (g_stripe_period 0x66879C) and button fields, so the copy behaves as the shipped bytes do."""
    if not _FACE_OWN:
        import assemble_face_own as FO
        _FACE_OWN.append(FO.assemble(FO.asm_face_own(), FACE_OWN_TEST))
    return _FACE_OWN[0]
RW_SBARROWS_TEST = A.PCAVE2 + 0xC980      # t_rw_sbarrows (assemble_popup_sb.T_RW_SBARROWS_OFF, pinned): stubbed "not an rw arrow"


@pytest.mark.parametrize("esi,calls", [
    (0x7B7264, [1, 2, 3]),          # editor button: devfill, ED, remap
    (0x7CD098, [1, 3]),             # just past the range: no ED pass
    (DATA + 0x100, [1, 3]),         # generic popup button
    (0x6B4DE8, []),                 # BaseWin early-out
])
def test_stripes_v5_call_order(esi, calls):
    uc = _mk(40)
    log = _stripes_env(uc)
    code = A.resolve_template(A.BTN_STRIPES_V5_TEMPLATE,
                              A.PCAVE2 + A.STRIPES_OFF, A.STRIPES_SYMS)
    uc.mem_write(A.PCAVE2 + 0x538, (100).to_bytes(4, "little"))  # g_btn_origW
    uc.mem_write(A.PCAVE2 + 0x53C,                               # g_btn_origH
                 (-40).to_bytes(4, "little", signed=True))       # stored NEG
    uc.mem_write(A.PCAVE2 + 0x12D0, b"\x00" * 4)                 # faction off
    _run(uc, A.PCAVE2 + A.STRIPES_OFF, code,
         regs=[(UC_X86_REG_ESI, esi)], count=10000)
    n = _r32(uc, log)
    got = [_r32(uc, log + 4 + 4 * i) for i in range(n)]
    assert got == calls
    if calls:                        # the g_fe_* staging happened before both
        assert _r32(uc, A.G_FE_W) == 100
        assert _r32(uc, A.G_FE_H) == 40            # g_fe_h = NEG(origH)


# --------------------------------------------------------------------------
# btn_stripes v7 (2026-08-15, src assemble_popup_sb.py): the console-rail
# scrollbar arrows (picker statics + the rail-fitted popup bar's dynamic pair)
# take the ED pass too -- their HOVER chevron dithers 0xA2/0xEF, which no fe
# family owns (1600x1200 shot 20260815-001842).
# --------------------------------------------------------------------------
import assemble_popup_sb as P  # noqa: E402

G_RAIL_SB_TEST = A.PCAVE2 + 0x11260
G_RM_YPH_TEST = A.PCAVE2 + 0x103FC        # fe_pair_remap v8 row-phase cell (btn_stripes v13)
BTN_TOP1, BTN_TOP2 = 7, 30                # the button's rRect1.top / rRect2.top (+0x140 / +0x150)
POPUP_SB_TEST = DATA + 0x30000            # a heap-like popup's embedded ScrollBar


def _stripes_v7_bytes():
    blob = bytearray(P.assemble(P.asm_btn_stripes(True, True), A.PCAVE2 + P.STRIPES_OFF))
    va = A.PCAVE2 + P.STRIPES_OFF
    absmap = {k: v[7:-1] for k, v in P.SENT.items()}
    syms = dict(A.STRIPES_SYMS)
    syms["g_rail_sb"] = G_RAIL_SB_TEST
    syms["thunk_sbarrow_bg"] = SBARROW_BG_TEST
    syms["t_rw_sbarrows"] = RW_SBARROWS_TEST
    syms["g_popup_scale_num"] = A.G_SCALE
    syms["g_ab_w"] = A.PCAVE2 + P.G_AB_OFF
    syms["g_ab_h"] = A.PCAVE2 + P.G_AB_OFF + 4
    syms["g_rm_yph"] = G_RM_YPH_TEST
    syms["t_face_own"] = FACE_OWN_TEST
    i = 0
    while i + 4 <= len(blob):
        v = int.from_bytes(blob[i:i + 4], "little")
        if v in absmap:
            blob[i:i + 4] = syms[absmap[v]].to_bytes(4, "little"); i += 4
        elif blob[i] == 0xE8 and i + 5 <= len(blob):
            rel = int.from_bytes(blob[i + 1:i + 5], "little", signed=True)
            tgt = (va + i + 5 + rel) & 0xFFFFFFFF
            if tgt in P.REL:
                real = syms[P.REL[tgt][7:-1]]
                blob[i + 1:i + 5] = ((real - (va + i + 5)) & 0xFFFFFFFF).to_bytes(4, "little")
                i += 5
            else:
                i += 1
        else:
            i += 1
    return bytes(blob)


@pytest.mark.parametrize("esi,rail_sb,calls", [
    (0x7B7264, 0, [1, 2, 3]),                     # editor button: devfill, ED, remap
    (0x7CD098, 0, [1, 3]),                        # just past the range: no ED pass
    (DATA + 0x100, 0, [1, 3]),                    # generic popup button
    (0x6B4DE8, 0, []),                            # BaseWin early-out
    (P.ARROW_UP, 0, [1, 4, 2, 3]),                # picker up arrow (static): +bg, ED
    (P.ARROW_DN, 0, [1, 4, 2, 3]),                # picker down arrow (static)
    (POPUP_SB_TEST + 0xAAC, POPUP_SB_TEST, [1, 4, 2, 3]),    # fitted popup bar: up
    (POPUP_SB_TEST + 0x15F8, POPUP_SB_TEST, [1, 4, 2, 3]),   # fitted popup bar: down
    (POPUP_SB_TEST + 0xAAC, 0, [1, 3]),           # same object, bar NOT fitted -> generic
    (POPUP_SB_TEST, POPUP_SB_TEST, [1, 3]),       # the bar itself is not an arrow
    (P.HUD_LOC_GLOBE, 0, [1, 2, 3]),              # v9: HUD base-locator globe (MainWin static): ED pass (E0/E2 pressed face)
    (P.HUD_LOC_GRID, 0, [1, 2, 3]),               # v9: HUD base-locator grid
    (P.HUD_LOC_GLOBE - 0xB4C, 0, [1, 3]),         # its MainWin neighbour: generic
    (P.RW_SAT_ATTACK, 0, [1, 2, 3]),              # v10: satellite report ATTACK! (ReportWin static): ED pass (C9/6D red face)
    (P.RW_SAT_ATTACK - 0xB4C, 0, [1, 3]),         # its group neighbour (ORBITAL ATTACK VIEW tab, AE/EE): generic
    (P.RW_SAT_ATTACK + 0xB4C, 0, [1, 3]),         # just past the group: generic
    (P.DW_ARROW_UP, 0, [1, 4, 2, 3]),             # v12: negotiation-window chat-bar up arrow: like the picker statics
    (P.DW_ARROW_DN, 0, [1, 4, 2, 3]),             # v12: its down arrow
    (P.DW_ARROW_UP + 4, 0, [1, 3]),               # v12: a near miss: generic
])
def test_stripes_v8_call_order(esi, rail_sb, calls):
    uc = _mk(40)
    log = _stripes_env(uc)
    uc.mem_write(A.PCAVE2 + 0x538, (100).to_bytes(4, "little"))  # g_btn_origW
    uc.mem_write(A.PCAVE2 + 0x53C,                               # g_btn_origH
                 (-40).to_bytes(4, "little", signed=True))       # stored NEG
    uc.mem_write(A.PCAVE2 + 0x12D0, b"\x00" * 4)                 # faction off
    uc.mem_write(G_RAIL_SB_TEST, int(rail_sb).to_bytes(4, "little"))
    uc.mem_write(RW_SBARROWS_TEST, bytes([0x31, 0xC0, 0xC3]))   # t_rw_sbarrows stub: xor eax,eax; ret (no rw bar)
    uc.mem_write(A.PCAVE2 + 0x10634, b"\x00" * 4)                # g_rm_f0ovr
    # v13: the button's parent-local top, and an fe stub that also records g_rm_yph at its call
    try:
        uc.mem_map(esi & ~0xFFF, 0x2000)          # v14: t_face_own reads [esi+0xC4] too
    except UcError:
        pass
    uc.mem_write(esi + 0x140, BTN_TOP1.to_bytes(4, "little"))
    uc.mem_write(esi + 0x150, BTN_TOP2.to_bytes(4, "little"))
    fe_va = A.STRIPES_SYMS["thunk_fe_pair_remap"]
    uc.mem_write(fe_va, _ks(
        f"mov eax, dword ptr [{log:#x}]\n"
        f"mov dword ptr [{log:#x}+4+eax*4], 3\n"
        f"inc dword ptr [{log:#x}]\n"
        f"mov eax, dword ptr [{G_RM_YPH_TEST:#x}]\n"
        f"mov dword ptr [{log:#x}+0x3C], eax\n"
        "ret\n", fe_va))
    uc.mem_write(log + 0x3C, b"\xFF" * 4)
    _run(uc, A.PCAVE2 + P.STRIPES_OFF, _stripes_v7_bytes(),
         regs=[(UC_X86_REG_ESI, esi)], count=10000)
    n = _r32(uc, log)
    got = [_r32(uc, log + 4 + 4 * i) for i in range(n)]
    assert got == calls
    if calls:      # v13: phase staged for the plain path only (law btn_face_stripe_phase), cleared after
        assert _r32(uc, log + 0x3C) == (BTN_TOP1 + BTN_TOP2 if calls == [1, 3] else 0)
        assert _r32(uc, G_RM_YPH_TEST) == 0
    if calls:
        assert _r32(uc, A.G_FE_W) == 100
        assert _r32(uc, A.G_FE_H) == 40
    # the F0 one-shot arms for exactly the arrows
    is_arrow = esi in (P.ARROW_UP, P.ARROW_DN, P.DW_ARROW_UP, P.DW_ARROW_DN) or (rail_sb and esi in (rail_sb + 0xAAC, rail_sb + 0x15F8))
    assert _r32(uc, A.PCAVE2 + 0x10634) == (1 if is_arrow else 0)


#: v14 (W9A): the own-top faces -- a child of PrefWin (parent +0xC4 == 0x8578D8) or one of the SE society rows
#: [0x8B829C, +10 * 0xB4C) -- and their near misses (the SE OK row either side, a PrefWin slider's arrow button)
OWN_CASES = [(DATA + 0x100, 0x8578D8, True), (DATA + 0x100, 0x8578D8 + 4, False), (DATA + 0x100, 0, False),
             (0x8B829C, 0, True), (0x8B829C + 9 * 0xB4C, 0x8A6270, True), (0x8B829C - 0xB4C, 0x8A6270, False),
             (0x8B829C + 10 * 0xB4C, 0x8A6270, False), (0x862064 + 0xAAC, 0x862064, False)]


@pytest.mark.parametrize("p", [2, 4, 6])
@pytest.mark.parametrize("h", [20, 21, 22, 27, 30, 31, 33, 37, 50, 1, 0])
@pytest.mark.parametrize("esi,parent,own", OWN_CASES)
@pytest.mark.parametrize("state", [(-1, 0, 0, 0), (2, 0, 0, 0), (1, 1, 1, 1), (-1, 0, 1, 0), (-1, 0, 0, 1),
                                   (-1, 1, 0, 0), (3, 1, 0, 0)])
def test_stripes_v14_stages_the_own_top_phase(p, h, esi, parent, own, state):
    """v14 plain path (law btn_face_phase): an own-top face stages own_face_stripe_phase(h, g, pressed) -- h the
    canvas's device height (-[+0x4C8]), pressed = flatbutton_draw_state == 2 -- every other button v13's parent-local
    top, byte for byte; the cell is cleared after the fe call and the call order is v13's."""
    uc = _mk(40)
    log = _stripes_env(uc)
    try:
        uc.mem_map(esi & ~0xFFF, 0x2000)
    except UcError:
        pass
    uc.mem_write(A.PCAVE2 + 0x538, (100).to_bytes(4, "little"))
    uc.mem_write(A.PCAVE2 + 0x53C, (-h).to_bytes(4, "little", signed=True))
    uc.mem_write(A.PCAVE2 + 0x12D0, b"\x00" * 4)
    uc.mem_write(G_RAIL_SB_TEST, b"\x00" * 4)
    uc.mem_write(RW_SBARROWS_TEST, bytes([0x31, 0xC0, 0xC3]))
    uc.mem_write(P.G_STRIPE_PERIOD, p.to_bytes(4, "little"))
    t1, t2 = 37, 5
    uc.mem_write(esi + 0x140, t1.to_bytes(4, "little", signed=True))
    uc.mem_write(esi + 0x150, t2.to_bytes(4, "little", signed=True))
    uc.mem_write(esi + 0xC4, parent.to_bytes(4, "little"))
    uc.mem_write(esi + 0x4C8, (-h).to_bytes(4, "little", signed=True))
    for off, v in zip((0xAB8, 0xA74, 0xA18, 0xA9C), state):
        uc.mem_write(esi + off, v.to_bytes(4, "little", signed=True))
    fe_va = A.STRIPES_SYMS["thunk_fe_pair_remap"]
    uc.mem_write(fe_va, _ks(f"mov eax, dword ptr [{G_RM_YPH_TEST:#x}]\nmov dword ptr [{log:#x}+0x3C], eax\nret\n", fe_va))
    regs = [(UC_X86_REG_ESI, esi), (UC_X86_REG_EBX, 0x5A5A0001), (UC_X86_REG_EDI, 0x5A5A0002),
            (UC_X86_REG_EBP, 0x5A5A0003)]
    _run(uc, A.PCAVE2 + P.STRIPES_OFF, _stripes_v7_bytes(), regs=regs, count=20000)
    staged = _r32(uc, log + 0x3C)
    g = {2: 20, 4: 25, 6: 48}[p]                         # a g whose period is p (the thunk reads only the cell)
    assert SL.stripe_period(g) == p
    st = SL.flatbutton_draw_state(*state)
    assert SL.own_top_face(esi, parent) == own
    want = SL.btn_face_phase(esi, parent, t1, t2, h, g, st)
    if own:
        assert staged == want == SL.own_face_stripe_phase(h, g, st == 2), (staged, want)
    else:
        assert staged == t1 + t2 and want == (t1 + t2) % p
    assert _r32(uc, G_RM_YPH_TEST) == 0
    assert [uc.reg_read(r) for r, _v in regs] == [v for _r, v in regs], "esi / ebx / edi / ebp preserved"


@pytest.mark.parametrize("p", [2, 4, 6])
@pytest.mark.parametrize("t1,t2", [(7, 30), (0, 0), (-3, 0), (-8, 0), (5, -9), (0, -1), (-37, 2)])
def test_stripes_v13_stages_the_parent_phase(p, t1, t2):
    """v13 plain path: a non-negative parent-local top is staged raw; a negative one is reduced in the thunk
    (cdq / idiv P, + P -> 1..P) so fe's unsigned `div` sees (row + cell) on the same grid as the floor modulus
    (law btn_face_stripe_phase).  The cell is cleared after the fe call."""
    uc = _mk(40)
    log = _stripes_env(uc)
    esi = DATA + 0x100
    uc.mem_write(A.PCAVE2 + 0x538, (100).to_bytes(4, "little"))
    uc.mem_write(A.PCAVE2 + 0x53C, (-40).to_bytes(4, "little", signed=True))
    uc.mem_write(A.PCAVE2 + 0x12D0, b"\x00" * 4)
    uc.mem_write(G_RAIL_SB_TEST, b"\x00" * 4)
    uc.mem_write(RW_SBARROWS_TEST, bytes([0x31, 0xC0, 0xC3]))
    uc.mem_write(P.G_STRIPE_PERIOD, p.to_bytes(4, "little"))
    uc.mem_write(esi + 0x140, t1.to_bytes(4, "little", signed=True))
    uc.mem_write(esi + 0x150, t2.to_bytes(4, "little", signed=True))
    fe_va = A.STRIPES_SYMS["thunk_fe_pair_remap"]
    uc.mem_write(fe_va, _ks(f"mov eax, dword ptr [{G_RM_YPH_TEST:#x}]\nmov dword ptr [{log:#x}+0x3C], eax\nret\n", fe_va))
    _run(uc, A.PCAVE2 + P.STRIPES_OFF, _stripes_v7_bytes(), regs=[(UC_X86_REG_ESI, esi)], count=10000)
    staged = _r32(uc, log + 0x3C)
    top = t1 + t2
    if top >= 0:
        assert staged == top
    else:
        assert 1 <= staged <= p
    for row in range(3 * p):                       # what fe_pair_remap v8 computes: (row + cell) mod P, unsigned
        assert (row + staged) % p == (row + top) % p
    assert _r32(uc, G_RM_YPH_TEST) == 0


def _chevron_cols(top, bot, g, fill=0x30):
    """A scrollbar chevron: 16x11 native triangle NN-zoomed x g/16 into a bp(24)
    square button, dithered top/bot on alternating NATIVE rows (the sprite's own
    1px pair), everything else `fill` (solid: must pass through)."""
    b = SL.scale_px(24, g)
    w = h = b
    cols = [[fill] * h for _ in range(w)]
    sw, sh = SL.scale_px(16, g), SL.scale_px(11, g)
    x0, y0 = (b - sw) // 2, (b - sh) // 2
    for yy in range(sh):
        src_row = (yy * 16) // g
        half = ((yy + 1) * sw) // (2 * sh)          # triangle: widens downward
        v = top if src_row % 2 == 0 else bot
        for xx in range(sw // 2 - half, sw // 2 + half + 1):
            if 0 <= xx < sw:
                cols[x0 + xx][y0 + yy] = v
    return cols


@pytest.mark.parametrize("g", [22, 25, 40])
@pytest.mark.parametrize("top,bot", [(0xA2, 0xEF), (0xF0, 0xB9)])
def test_edremap_restripes_a_scrollbar_chevron(g, top, bot):
    """The real thunk_ed_remap bytes on an arrow-shaped face: the hover pair
    (A2/EF) and the normal pair (F0/B9) both enable and come out lawful; the
    solid surround is untouched (guards the 2*w credit threshold for the small
    chevron -- an arrow is far narrower than an editor face)."""
    uc = _mk(g)
    cols = _chevron_cols(top, bot, g)
    pix, stride, _ = _face(uc, cols)
    _run_remap(uc, g)
    _check(uc, pix, stride, cols, g)
    _w, flags = _model(cols, g)
    key = "a2" if top == 0xA2 else "f0"
    assert flags[key], flags


def _attack_face_cols(g, label_rows=(0x41,)):
    """The satellite report's ATTACK! FlatButton as btn_stripes hands it to
    thunk_ed_remap (v10): the whole bevel face is the red 1px pair C9 (top) /
    6D NN-zoomed x g/16 (the 1920x1080 shot's 1,2,1,1,2,1 runs), with the black
    0x41 label glyphs in the middle rows and a solid stroke column each side."""
    w, h = SL.scale_px(200, g), SL.scale_px(22, g)
    cols = _nn_cols(0xC9, 0x6D, w, h, g)
    for x in range(w):
        cols[x][0] = cols[x][h - 1] = 0x41            # top/bottom stroke rows
    for x in (0, w - 1):
        cols[x] = [0x41] * h
    y0, y1 = h // 3, (2 * h) // 3
    for x in range(w // 3, (2 * w) // 3, 3):           # glyph-like black columns
        for y in range(y0, y1):
            cols[x][y] = 0x41
    return cols


@pytest.mark.parametrize("g", [22, 25, 40])
def test_edremap_restripes_the_attack_face(g):
    """v10: the real thunk_ed_remap bytes on the ATTACK! face -- the red family
    enables (c9, never the pressed m68 mate) and every C9/6D pixel becomes a
    lawful P stripe; the black label / strokes pass through untouched."""
    uc = _mk(g)
    cols = _attack_face_cols(g)
    pix, stride, h = _face(uc, cols)
    _run_remap(uc, g)
    _check(uc, pix, stride, cols, g)
    want, flags = _model(cols, g)
    assert flags["c9"] and not flags["m68"], flags
    img = uc.mem_read(pix, stride * h)
    for x in range(len(cols)):
        for y in range(h):
            v = img[y * stride + x]
            if cols[x][y] == 0x41:
                assert v == 0x41
            else:
                assert v == (0xC9 if SL.stripe_top(y, g) else 0x6D), (x, y, v)


def _arrow_face(g, chevron=(0xF0, 0xB9)):
    """A zoomed arrow face: C2/C5 row-dither background NN-banded, chevron pair
    on top (a triangle), a 1px bevel of 0xC4 around the edge (must pass through)."""
    b = SL.scale_px(24, g)
    cols = []
    for x in range(b):
        col = []
        for y in range(b):
            src = (y * 16) // g
            v = 0xC2 if src % 2 == 0 else 0xC5
            if x == 0 or y == 0 or x == b - 1 or y == b - 1:
                v = 0xC4
            col.append(v)
        cols.append(col)
    chev = _chevron_cols(chevron[0], chevron[1], g, fill=None)
    for x in range(b):
        for y in range(b):
            if chev[x][y] is not None:
                cols[x][y] = chev[x][y]
    return cols


@pytest.mark.parametrize("g", [22, 25, 40])
def test_sbarrow_bg_restripes_the_face_background_only(g):
    uc = _mk(g)
    cols = _arrow_face(g)
    pix, stride, h = _face(uc, cols)
    uc.mem_write(A.PCAVE2 + P.G_AB_OFF, b"\x00" * 8)
    code = P.assemble(P.asm_sbarrow_bg(), SBARROW_BG_TEST)
    blob = bytearray(code)
    absmap = {k: v[7:-1] for k, v in P.SENT.items()}
    real = {"g_fe_dst": A.G_FE_DST, "g_fe_w": A.G_FE_W, "g_fe_h": A.G_FE_H,
            "g_popup_scale_num": A.G_SCALE, "g_ab_w": A.PCAVE2 + P.G_AB_OFF,
            "g_ab_h": A.PCAVE2 + P.G_AB_OFF + 4}
    i = 0
    while i + 4 <= len(blob):
        v = int.from_bytes(blob[i:i + 4], "little")
        if v in absmap:
            blob[i:i + 4] = real[absmap[v]].to_bytes(4, "little"); i += 4
        else:
            i += 1
    _run(uc, SBARROW_BG_TEST, bytes(blob), regs=[(UC_X86_REG_ESI, 0x1234), (UC_X86_REG_EDI, 0x5678)],
         count=4_000_000)
    assert uc.reg_read(UC_X86_REG_ESI) == 0x1234 and uc.reg_read(UC_X86_REG_EDI) == 0x5678
    img = uc.mem_read(pix, stride * h)
    for x, col in enumerate(cols):
        for y, v in enumerate(col):
            want = SL.sbarrow_bg_pixel(v, y, g)
            assert img[y * stride + x] == want, (g, x, y, hex(v), hex(img[y * stride + x]), hex(want))
    # and at fractional g it really rewrote something (the NN background is not
    # already lawful; at g=40 the 2.5x NN is phase-aligned with P=5 -- "4K hides it")
    if g != 40:
        assert any(SL.sbarrow_bg_pixel(v, y, g) != v for col in cols for y, v in enumerate(col))
