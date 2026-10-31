"""Unicorn parity of the W3A helpers on the SHIPPED bytes (2026-10-25 wave-3 W3A; src scripts/assemble_mirror_pairs.py,
assemble_council.py IMMTAB, assemble_scenedit.py asm_seeds):

  t_cw_rowsym   == scaling_laws.council_thirds_fixup (F43) on every state: g -4..64, remainders -3..5 (in and out of
                  the law), arbitrary rects; eax..ebp kept, lands on thunk_cw_seeds with the call's return address still
                  on the stack (a tail jump), only the five row dwords written;
  t_ed_redchain == scaling_laws.editor_red_chain_delta applied to the seeds / stash: g -4..64, fresh and stale stamps;
                  all registers AND eflags kept (the displaced `xor eax, eax` flags reach 0x45B0F5), lands on 0x45B0F5;
  thunk_ed_seeds + t_ed_redchain on the image's own bytes == editor_panel_seeds at g 16..64 (the composition);
  g_cw_immtab == assemble_council.immtab_bytes() (41 rows, the 0x427707 disp8 row in it) and thunk_cw_immfix writes
                  -sc(3) there at every g (vanilla 0xFD at g = 16); the yaml bytes == the assembler's output at the
                  pinned offsets in the W3A region 0x38000..0x38FFF; the site / tail retargets.

All on the conftest `baked_exe` bytes (sections mapped into one Unicorn per module).  Cheap: no boot.
"""
from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("keystone", reason="keystone absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pefile = pytest.importorskip("pefile", reason="pefile absent")
from unicorn import UC_ARCH_X86, UC_HOOK_MEM_WRITE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_council as AC  # noqa: E402
import assemble_mirror_pairs as MP  # noqa: E402
import assemble_scenedit as AS  # noqa: E402
import scaling_laws as SL  # noqa: E402

G_VA = 0x668740
STACK = 0x10000000
SP0 = STACK + 0x80000
RET = 0x0BADC0DE
CW = STACK + 0x40000                    # a CouncilWin stand-in (t_cw_rowsym only touches esi + 0xCDC..0xD0F)
REGS = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
        UC_X86_REG_EBP)
MW = 0x7AE820
MW_PAL, MW_RED = MW + 0xADC, MW + 0xC6C


@pytest.fixture(scope="module")
def symtab():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return ap.build_symbol_table(symbols, caves)


@pytest.fixture(scope="module")
def img(baked_exe):
    data = Path(baked_exe).read_bytes()
    pe = pefile.PE(data=data)
    ib = pe.OPTIONAL_HEADER.ImageBase
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for sct in pe.sections:
        va = ib + sct.VirtualAddress
        mu.mem_map(va, (max(sct.Misc_VirtualSize, sct.SizeOfRawData) + 0xFFF) & ~0xFFF)
        mu.mem_write(va, sct.get_data())
    mu.mem_map(STACK, 0x100000)
    return mu


def r32(mu, a):
    return struct.unpack("<i", bytes(mu.mem_read(a, 4)))[0]


def w32(mu, a, v):
    mu.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))


def _syms(symtab):
    return {n: symtab[n] for n in MP.SYM_PH}


def _run(mu, va, until, regs, count=20000):
    """Enter va by a CALL (return address RET on the stack); run to `until`; -> (writes outside the stack)."""
    sp = SP0
    w32(mu, sp, RET)
    for r, v in regs.items():
        mu.reg_write(r, v & 0xFFFFFFFF)
    mu.reg_write(UC_X86_REG_ESP, sp)
    writes = []
    h = mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, a, addr, s, v, u: writes.append((addr, s))
                    if not (SP0 - 0x200 <= addr < SP0 + 8) else None)
    try:
        mu.emu_start(va, until, count=count)
    finally:
        mu.hook_del(h)
    assert mu.reg_read(UC_X86_REG_EIP) == until
    return writes


# ---------------------------------------------------------------- yaml == assembler, placement, wiring
@pytest.mark.parametrize("name", list(MP.HELPERS))
def test_yaml_bytes_are_the_assembler(img, symtab, name):
    off, end = MP.HELPERS[name]
    va = MP.PCAVE2 + off
    assert symtab[name] == va and MP.REGION[0] <= off < end <= MP.REGION[1], "pinned in the W3A region"
    want = MP.assemble(name, _syms(symtab))
    assert bytes(img.mem_read(va, len(want))) == want
    assert bytes(img.mem_read(va + len(want), MP.PCAVE2 + end - va - len(want))) == bytes(MP.PCAVE2 + end - va - len(want))
    nxt = [n for n, v in symtab.items() if va < v < MP.PCAVE2 + end and n != name]
    assert not nxt, f"{name}'s slot holds {nxt}"


def test_wiring(img, symtab, bak_bytes):
    """0x427784 (was E8 -> thunk_cw_seeds) calls t_cw_rowsym, which tails thunk_cw_seeds; thunk_ed_seeds (the bake ==
    assemble_scenedit's output, its only change the tail push) resumes through t_ed_redchain, which resumes 0x45B0F5;
    the pristine site is vanilla's Font_init call."""
    pe = pefile.PE(data=bak_bytes)
    raw = pe.get_memory_mapped_image()
    assert raw[0x427784 - 0x400000:0x427789 - 0x400000] == bytes.fromhex("E8B7171F00")
    rel = struct.unpack("<i", bytes(img.mem_read(0x427785, 4)))[0]
    assert img.mem_read(0x427784, 1) == b"\xE8" and 0x427789 + rel == symtab["t_cw_rowsym"]
    assert AS.SEEDS_TAIL == symtab["t_ed_redchain"] and AS.PCAVE2 + AS.OFF_SEEDS == symtab["thunk_ed_seeds"]
    seeds = AS.assemble(AS.asm_seeds(), symtab["thunk_ed_seeds"])
    assert bytes(img.mem_read(symtab["thunk_ed_seeds"], len(seeds))) == seeds
    assert seeds.count(b"\x68" + struct.pack("<I", symtab["t_ed_redchain"]) + b"\xC3") == 1
    assert seeds.count(b"\x68" + struct.pack("<I", AS.SEEDS_RESUME)) == 0


def test_cw_immtab_has_the_disp8_row(img, symtab):
    tab = AC.immtab_bytes()
    assert bytes(img.mem_read(symtab["g_cw_immtab"], len(tab))) == tab and len(tab) == 41 * 16 + 4
    rows = [struct.unpack_from("<IIII", tab, 16 * k) for k in range(41)]
    assert (0x427707, 3, 0, 2) in rows
    assert symtab["g_cw_immtab"] + len(tab) <= symtab["thunk_cw_enter"]


@pytest.mark.parametrize("g", [16, 17, 18, 22, 24, 25, 30, 40, 64])
def test_cw_immfix_writes_the_disp8(img, symtab, bak_bytes, g):
    """The image's own thunk_cw_immfix (VirtualProtect flagged done) writes -sc(3) into the lea's disp8 at 0x427707
    -- the pristine 0xFD at g = 16 -- and the thirds block then reads one s(3) everywhere."""
    w32(img, G_VA, g)
    w32(img, symtab["g_cw_vpdone"], 1)
    _run(img, symtab["thunk_cw_immfix"], RET, {UC_X86_REG_ESI: 0x1234}, count=200000)
    want = -SL.dp(3, g)
    assert struct.unpack("<b", bytes(img.mem_read(0x427707, 1)))[0] == want
    pe = pefile.PE(data=bak_bytes)
    assert pe.get_memory_mapped_image()[0x427707 - 0x400000] == 0xFD
    for site in (0x4276F1, 0x427728, 0x427753):                  # the three `add eax, 3` -- the same s(3)
        assert img.mem_read(site, 1)[0] == SL.dp(3, g)


# ---------------------------------------------------------------- t_cw_rowsym
def _row(rnd, g, rem):
    """A thirds_engine-shaped row (or garbage) with VOTE.R - third[2].R == rem."""
    L = rnd.randrange(-50, 3000)
    w = rnd.randrange(1, 900)
    s3 = SL.dp(3, max(g, 16))
    top, bot = rnd.randrange(-100, 2000), rnd.randrange(-100, 2200)
    t = [(L + k * (w + s3), top, L + k * (w + s3) + w, bot) for k in range(3)]
    if rnd.random() < 0.2:                                        # not even engine-shaped
        t = [tuple(rnd.randrange(-5000, 5000) for _ in range(4)) for _ in range(3)]
    full = (L, top, t[2][2] + rem, bot)
    return full, t


def test_rowsym_is_the_law(img, symtab):
    rnd = random.Random(43)
    va, tail = symtab["t_cw_rowsym"], symtab["thunk_cw_seeds"]
    seen = set()
    for case in range(1500):
        g = rnd.choice(list(range(-4, 65)) + [16, 17, 24, 25, 40])
        rem = rnd.choice(range(-3, 6))
        full, t = _row(rnd, g, rem)
        w32(img, G_VA, g)
        for k in range(3):
            img.mem_write(CW + 0xCD4 + 16 * k, struct.pack("<4i", *t[k]))
        img.mem_write(CW + 0xD04, struct.pack("<4i", *full))
        regs = {r: rnd.getrandbits(32) for r in REGS}
        regs[UC_X86_REG_ESI] = CW
        writes = _run(img, va, tail, regs)
        got = [tuple(r32(img, CW + 0xCD4 + 16 * k + 4 * i) for i in range(4)) for k in range(3)]
        want = SL.council_thirds_fixup(full[2], t, g)
        assert got == want, (case, g, rem, t, got, want)
        assert tuple(r32(img, CW + 0xD04 + 4 * i) for i in range(4)) == full
        for r in REGS:
            assert img.reg_read(r) == regs[r], (case, r)
        assert img.reg_read(UC_X86_REG_ESP) == SP0 and r32(img, SP0) == RET, "a tail jump: the call's return address"
        allowed = {CW + o for o in (0xCDC, 0xCE4, 0xCEC, 0xCF4, 0xCFC)}
        assert {a for a, _s in writes} <= allowed and all(s == 4 for _a, s in writes), case
        seen.add((g > 16, 0 <= rem <= 2, got != t))
    assert (True, True, True) in seen and (True, False, False) in seen and (False, True, False) in seen


@pytest.mark.parametrize("g", range(16, 65))
def test_rowsym_on_the_engine_row_is_council_button_row(img, symtab, g):
    """For the engine's own row (council_button_row's thirds_engine, i.e. the imm table applied), the thunk's output IS
    the law's mirrored thirds, for four console widths (all three remainders)."""
    va, tail = symtab["t_cw_rowsym"], symtab["thunk_cw_seeds"]
    w32(img, G_VA, g)
    for extra in range(4):
        con = (655, 165, 1907 + extra, 430)
        row = SL.council_button_row(con, g)
        for k in range(3):
            img.mem_write(CW + 0xCD4 + 16 * k, struct.pack("<4i", *row["thirds_engine"][k]))
        img.mem_write(CW + 0xD04, struct.pack("<4i", *row["full"]))
        _run(img, va, tail, {UC_X86_REG_ESI: CW})
        got = [tuple(r32(img, CW + 0xCD4 + 16 * k + 4 * i) for i in range(4)) for k in range(3)]
        assert got == row["thirds"], (g, extra)


# ---------------------------------------------------------------- t_ed_redchain
def _ed_state(img, rnd, g, stamp):
    pal = [tuple(rnd.randrange(-100, 3000) for _ in range(4)) for _ in range(25)]
    red = [tuple(rnd.randrange(-100, 3000) for _ in range(4)) for _ in range(6)]
    for k, r in enumerate(pal):
        img.mem_write(MW_PAL + 16 * k, struct.pack("<4i", *r))
    for k, r in enumerate(red):
        img.mem_write(MW_RED + 16 * k, struct.pack("<4i", *r))
    p3 = rnd.randrange(0, 20)
    redu = tuple(rnd.randrange(-100, 3000) for _ in range(4))
    info = tuple(rnd.randrange(-100, 3000) for _ in range(3))
    return pal, red, p3, redu, info


def test_redchain_is_the_law(img, symtab):
    rnd = random.Random(1025)
    va = symtab["t_ed_redchain"]
    for case in range(800):
        g = rnd.choice(list(range(-4, 65)) + [16, 17, 40])
        stamp = g if rnd.random() < 0.8 else rnd.randrange(0, 70)
        pal, red, p3, redu, info = _ed_state(img, rnd, g, stamp)
        w32(img, G_VA, g)
        w32(img, symtab["g_ed_stamp"], stamp)
        w32(img, symtab["g_ed_p3"], p3)
        img.mem_write(symtab["g_ed_redu"], struct.pack("<4i", *redu))
        img.mem_write(symtab["g_ed_info"], struct.pack("<3i", *info))
        regs = {r: rnd.getrandbits(32) for r in REGS}
        regs[UC_X86_REG_ESI] = MW
        fl = rnd.choice((0x202, 0x246, 0x283, 0xA97))
        img.reg_write(UC_X86_REG_EFLAGS, fl)
        _run(img, va, AS.SEEDS_RESUME, regs)
        live = g > 16 and stamp == g
        d = (pal[24][2] + 3 * p3 - red[0][0]) if live else 0
        got_red = [tuple(r32(img, MW_RED + 16 * k + 4 * i) for i in range(4)) for k in range(6)]
        assert got_red == [(r[0] + d, r[1], r[2] + d, r[3]) for r in red], case
        assert tuple(r32(img, symtab["g_ed_redu"] + 4 * i) for i in range(4)) == (redu[0] + d, redu[1], redu[2] + d,
                                                                                    redu[3])
        assert tuple(r32(img, symtab["g_ed_info"] + 4 * i) for i in range(3)) == (info[0] + d, info[1], info[2])
        assert [tuple(r32(img, MW_PAL + 16 * k + 4 * i) for i in range(4)) for k in range(25)] == pal
        for r in REGS:
            assert img.reg_read(r) == regs[r], (case, r)
        assert img.reg_read(UC_X86_REG_EFLAGS) & 0xCD5 == fl & 0xCD5, "flags reach 0x45B0F5 intact"
        assert img.reg_read(UC_X86_REG_ESP) == SP0, "entered by thunk_ed_seeds' push + ret, left by its own: balanced"


@pytest.mark.parametrize("g", [16] + list(range(17, 65)))
def test_seeds_then_redchain_is_editor_panel_seeds(img, symtab, g):
    """The image's thunk_ed_seeds (entered as from the 0x45B0ED detour; thunk_ed_immfix runs too, VirtualProtect flagged
    done) and its new tail t_ed_redchain: the 31 seed RECTs and the union / info stash are editor_panel_seeds(g) --
    the red group chained off the palette -- and at g = 16 nothing is written (vanilla's own seeds stand)."""
    w32(img, G_VA, g)
    w32(img, symtab["g_vp_done"], 1)
    w32(img, symtab["g_ed_stamp"], 0)
    img.mem_write(MW_PAL, b"\xCC" * 400)
    img.mem_write(MW_RED, b"\xCC" * 96)
    sp = SP0
    img.reg_write(UC_X86_REG_ESP, sp)
    img.reg_write(UC_X86_REG_ESI, MW)
    img.emu_start(symtab["thunk_ed_seeds"], AS.SEEDS_RESUME, count=500000)
    assert img.reg_read(UC_X86_REG_EIP) == AS.SEEDS_RESUME and img.reg_read(UC_X86_REG_ESP) == sp
    assert img.reg_read(UC_X86_REG_EAX) == 0 and img.reg_read(UC_X86_REG_ECX) == MW + 0x21E2C
    if g <= 16:
        assert bytes(img.mem_read(MW_RED, 96)) == b"\xCC" * 96 and bytes(img.mem_read(MW_PAL, 400)) == b"\xCC" * 400
        return
    s = SL.editor_panel_seeds(g)
    assert [tuple(r32(img, MW_PAL + 16 * k + 4 * i) for i in range(4)) for k in range(25)] == s["pal"]
    assert [tuple(r32(img, MW_RED + 16 * k + 4 * i) for i in range(4)) for k in range(6)] == s["red"]
    assert tuple(r32(img, symtab["g_ed_palu"] + 4 * i) for i in range(4)) == s["pal_union"]
    assert tuple(r32(img, symtab["g_ed_redu"] + 4 * i) for i in range(4)) == s["red_union"]
    assert tuple(r32(img, symtab["g_ed_info"] + 4 * i) for i in range(3)) == (s["info_left"], s["info_top"],
                                                                              s["info_bottom"])
    assert r32(img, symtab["g_ed_stamp"]) == g
