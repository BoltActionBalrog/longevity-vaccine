"""Console tab pairs v2 (2026-10-17): Unicorn parity of the assemble_rw / assemble_rw_kinds caves against
scaling_laws.rw_tab_pair / rw_tab_inset / rw_console_inset_w / rw_sat_tabs.

The defect (4K shot 20261017-121433, x760 y1700): the F2 TECHNOLOGY|BASES channels read L5 R7 T5 B7 at 4K (L3 R6 T3 B5 at
1920x1080) against vanilla's 2/2/2/2 (refs/pristine/HQData/Tech.png / 2.8125): the tab box drew INCLUSIVE (+1 R/B), its far
edge was L + s(6) + W - s(0xC) instead of R - s(6), and the buttons came from an independent s(9)/s(0x12)/s(0x14) cascade.
F4 GOVERNOR|BEST BASES: the same disease (4K L5 R6 T5 B6, 1600x1200 L3 R2 T3 B3).

Covers: every new/changed cave from its REAL assembled bytes at its REAL VA -- g=16 identity against the displaced
PRISTINE bytes (registers, stack, written fields), the law at g = 17..40 over random panel regions, register/stack
contracts; t_rw_insetv at every g; the site table (redirect targets, detour lengths on instruction boundaries, the
covered walker rows gone, no branch target inside a skipped span)."""
from __future__ import annotations

import random
import struct

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

import scaling_laws as SL
from test_rw_asm_parity import AR, Emu, SP0, VA, r32, r32s, w32  # noqa: F401
import assemble_rw_kinds as RK
import assemble_se as SE

s = SL.scale_px
RI = AR.RI
REGS = ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp")
RECT = RI + 0x1E1C8
_cs = Cs(CS_ARCH_X86, CS_MODE_32)
GL = (17, 18, 20, 22, 25, 28, 29, 33, 36, 40)
RNG = random.Random(0x7AB5)
REGIONS = [(4, 56, 245, 252), (10, 140, 612, 630), (8, 180, 609, 671)] + \
          [(x, y, x + w, y + h) for x, y, w, h in ((RNG.randrange(0, 400), RNG.randrange(0, 900), RNG.randrange(150, 801),
                                                    RNG.randrange(120, 600)) for _ in range(6))]


def _region(e, reg):
    for i, v in enumerate(reg):
        w32(e.uc, RI + 0x20 + 4 * i, v)


def _rect(e):
    return struct.unpack("<4i", bytes(e.uc.mem_read(RECT, 16)))


def _state(e, esp0):
    st = {r: e.reg(r) for r in REGS}
    lo = min(st["esp"], esp0)
    st["stack"] = bytes(e.uc.mem_read(lo, esp0 + 0x10 - lo))
    st["cursor"] = bytes(e.uc.mem_read(RI + 0xC, 16))
    st["rect"] = bytes(e.uc.mem_read(RECT, 16))
    return st


# ---- t_rw_insetv ------------------------------------------------------------------------------
@pytest.mark.parametrize("g", list(range(12, 49)))
def test_insetv_values_and_contract(g):
    gc = max(g, 16)
    for code in (1, 2, 3, 6, 0x1A, 0x23, 0, -1):
        e = Emu(g)
        esp = SP0 - 8
        e.uc.mem_write(esp, struct.pack("<Ii", 0x11223344, code))
        e.uc.mem_write(0x11223344, b"\xf4")
        try:
            e.run(VA["t_rw_insetv"], 0x11223344, esp=esp, ebx=0xB, ecx=0xC, edx=0xD, esi=0xE, edi=0xF, ebp=0xA, count=200)
        except Exception:  # noqa: BLE001
            pass
        want = SL.rw_tab_inset(gc) if code == 0 else SL.rw_console_box_inset(gc) if code == -1 else s(code, gc)
        assert e.reg("eax") == want and e.reg("esp") == SP0
        assert (e.reg("ebx"), e.reg("ecx"), e.reg("edx"), e.reg("esi"), e.reg("edi"), e.reg("ebp")) == (0xB, 0xC, 0xD, 0xE, 0xF, 0xA)
    if g <= 16:
        assert SL.rw_tab_inset(gc) == 9 and SL.rw_console_box_inset(gc) == 6


# ---- the split caves: law at g > 16 -----------------------------------------------------------
SPLITS = [  # (thunk, site, native resume, law resume, which, esp in, esp out)
    ("t_rw_tabsplit1", 0x4A45B6, 0x4A45BC, 0x4A45D9, 0, SP0 - 8, SP0),
    ("t_rw_tabsplit2", 0x4A4675, 0x4A467C, 0x4A4693, 1, SP0 - 8, SP0),
    ("t_rwk_gov_split1", 0x4A478D, 0x4A4793, 0x4A47B0, 0, SP0 - 8, SP0),
    ("t_rwk_gov_split2", 0x4A484F, 0x4A4857, 0x4A486B, 1, SP0, SP0 - 4),
]


@pytest.mark.parametrize("g", GL)
@pytest.mark.parametrize("thunk,site,nres,lres,which,esp_in,esp_out", SPLITS)
def test_split_caves_write_the_law_rect(g, thunk, site, nres, lres, which, esp_in, esp_out):
    for reg in REGIONS:
        e = Emu(g)
        _region(e, reg)
        e.uc.mem_write(RECT, b"\xEE" * 16)
        e.run(VA[thunk], lres, esp=esp_in, eax=0x1234, ebx=0x42, ecx=0x3333, edx=0x4444, esi=RI, edi=0x5555, ebp=0x6666, count=400)
        box, left, right = SL.rw_tab_pair(reg, g)
        assert _rect(e) == (left if which == 0 else right)
        assert (e.reg("ebx"), e.reg("esi"), e.reg("edi"), e.reg("ebp"), e.reg("esp")) == (0x42, RI, 0x5555, 0x6666, esp_out)
        if thunk == "t_rwk_gov_split2":                                   # `push ebx` = BaseButton_init's first argument
            assert r32(e.uc, esp_out) == 0x42
        ch = SL.rw_tab_channels(reg, g)
        assert ch["L"] == ch["R"] == ch["T"] == ch["B"] == ch["seam"] == s(2, g)


@pytest.mark.parametrize("thunk,site,nres,lres,which,esp_in,esp_out", SPLITS)
def test_split_caves_identity_at_16(thunk, site, nres, lres, which, esp_in, esp_out):
    """g=16: from the cave entry to the NATIVE resume == the displaced pristine bytes (registers + stack)."""
    for w in (223, 224, 561):
        seed = dict(eax=w if which == 0 else w >> 1, ebx=0x42, ecx=55, edx=100, esi=RI, edi=0x5555, ebp=0x6666)
        e = Emu(16); w32(e.uc, RI + 0x14, w)
        e.uc.mem_write(esp_in - 0x20, bytes(0x40))
        e.uc.mem_write(site, SE.base_exe_bytes(site, nres - site))
        e.run(site, nres, esp=esp_in, count=100, **seed)
        want = _state(e, esp_in)
        e = Emu(16); w32(e.uc, RI + 0x14, w)
        e.uc.mem_write(esp_in - 0x20, bytes(0x40))
        e.run(VA[thunk], nres, esp=esp_in, count=100, **seed)
        assert _state(e, esp_in) == want


# ---- the cursor / width detours ----------------------------------------------------------------
# (thunk, site, len, seed(e, reg) -> regs, law(regs, reg, g) -> {reg: value} the g>16 path must produce)
def _seed_labs_w(e, reg):
    w32(e.uc, RI + 0x20 + 8, reg[2])
    return dict(eax=reg[0], edx=reg[2], edi=RI + 0x20, esi=RI, ecx=0x777, ebx=0x42, ebp=0x6666)


def _seed_labs_h(e, reg):
    return dict(eax=reg[3] - reg[1], ecx=reg[1], edx=0x0BADF00D, esi=RI, edi=RI + 0x20, ebx=0x42, ebp=0x6666)


def _seed_labs_rw(e, reg):
    return dict(eax=reg[2] - reg[0], edx=reg[0], ecx=0x777, esi=RI, ebx=RI + 0x30, edi=0x5555, ebp=0x6666)


def _seed_labs_rh(e, reg):
    return dict(ecx=reg[3] - reg[1], eax=reg[1], edx=0x9999, esi=RI, ebx=RI + 0x30, edi=0x5555, ebp=0x6666)


def _seed_ops(e, reg):
    _region(e, reg)
    return dict(eax=reg[2] - reg[0], ebx=reg[0], ecx=reg[0] + 15, edx=reg[1] + 15, esi=RI, edi=RI + 0x20, ebp=0x6666)


def _seed_ops_lx(e, reg):
    _region(e, reg)
    return dict(eax=0x1111, ebx=reg[0], ecx=reg[0], edx=0x2222, esi=RI, edi=RI + 0x20, ebp=0x6666)


def _seed_ops_lw(e, reg):
    _region(e, reg)
    return dict(eax=0x1111, ebx=reg[0], ecx=reg[0] + 15, edx=reg[1] + 15, esi=RI, edi=RI + 0x20, ebp=0x6666)


def _seed_govlist(e, reg):
    _region(e, reg)
    return dict(eax=0x1111, ebx=0, ecx=reg[0], edx=reg[1], esi=RI, edi=0x5555, ebp=0x6666)


CLIP_L, CLIP_R = 0x87BDEC, 0x87BDF4


def _seed_sat_w(e, reg):
    w32(e.uc, CLIP_L, reg[0]); w32(e.uc, CLIP_R, reg[2])
    return dict(eax=0x1111, ebx=0, ecx=0x8802F8, edx=reg[2], edi=reg[0], esi=RI, ebp=0x6666)


def _seed_modes_w(e, reg):
    w32(e.uc, CLIP_L, reg[0]); w32(e.uc, CLIP_R, reg[2])
    return dict(eax=0x1111, ebx=0, ecx=reg[2], edx=0x2222, edi=0x5555, esi=RI, ebp=0x6666)


def _w(reg):
    return reg[2] - reg[0]


DETOURS = [
    # v2 (2026-10-17 console chain): the content box far edges mirror C = rw_console_box_inset (was s(6))
    ("t_rw_labs_w", 0x4A7032, 7, _seed_labs_w, lambda r, g: {"edx": SL.rw_console_box_w(_w(r), g)}),
    ("t_rw_labs_h", 0x4A704A, 9, _seed_labs_h, lambda r, g: {"eax": SL.rw_console_box_w(r[3] - r[1], g), "ecx": RI + 0xBA0C}),
    ("t_rw_labs_rw", 0x4A7A78, 9, _seed_labs_rw, lambda r, g: {"eax": SL.rw_console_box_w(_w(r), g)}),
    ("t_rw_labs_rh", 0x4A7A8F, 9, _seed_labs_rh, lambda r, g: {"ecx": SL.rw_console_box_w(r[3] - r[1], g)}),
    ("t_rwk_ops_w", 0x4A90DD, 9, _seed_ops, lambda r, g: {"eax": SL.rw_console_box_w(_w(r), g), "edi": RECT}),
    ("t_rwk_ops_lx", 0x4A90A8, 6, _seed_ops_lx, lambda r, g: {"edx": r[0] + SL.rw_tab_inset(g), "cur_x": r[0] + SL.rw_tab_inset(g)}),
    ("t_rwk_ops_lw", 0x4A90BA, 8, _seed_ops_lw, lambda r, g: {"eax": _w(r) - 2 * SL.rw_tab_inset(g)}),
    ("t_rwk_govlist", 0x4A4F05, 26, _seed_govlist, lambda r, g: {"cur_x": r[0] + SL.rw_tab_inset(g), "cur_y": r[1] + s(0x23, g),
                                                                  "cur_w": _w(r) - 2 * SL.rw_tab_inset(g), "ecx": r[0]}),
    ("t_rwk_sat_w", 0x4A4C42, 8, _seed_sat_w, lambda r, g: {"cur_w": SL.rw_console_inset_w(_w(r), 3, g)}),
    ("t_rwk_modes_w", 0x4A4927, 9, _seed_modes_w, lambda r, g: {"ecx": SL.rw_console_inset_w(_w(r), 3, g)}),
]


# registers the cave uses as scratch that vanilla's resume path overwrites before reading (verified by disassembly):
# 0x4A7039 -> mov eax,[edi+0xC] (0x4A703C); 0x4A90AE -> lea eax,[edx+0x28] (0x4A90B1); 0x4A4C4A / 0x4A4930 -> call
# 0x62B810 (xor eax,eax first; eax no argument)
DEAD = {"t_rw_labs_w": ("eax",), "t_rwk_ops_lx": ("eax",), "t_rwk_sat_w": ("eax",), "t_rwk_modes_w": ("eax",)}


def _run_detour(e, start, until, regs):
    e.uc.mem_write(RI + 0xC, b"\xCC" * 16)
    e.uc.mem_write(SP0 - 0x40, bytes(0x50))
    e.run(start, until, esp=SP0, count=300, **regs)
    st = _state(e, SP0)
    st["cur_x"], st["cur_y"], st["cur_w"], st["cur_h"] = struct.unpack("<4i", st["cursor"])
    return st


@pytest.mark.parametrize("thunk,site,ln,seed,law", DETOURS)
def test_detour_identity_at_16_vs_pristine(thunk, site, ln, seed, law):
    """g=16 (and below): the cave == the displaced pristine bytes -- every register, the live stack, the cursor + rect."""
    for g in (12, 16):
        for reg in REGIONS[:4]:
            e = Emu(g); regs = seed(e, reg)
            e.uc.mem_write(site, SE.base_exe_bytes(site, ln))
            want = _run_detour(e, site, site + ln, regs)
            e = Emu(g); regs = seed(e, reg)
            got = _run_detour(e, VA[thunk], site + ln, regs)
            for r in DEAD.get(thunk, ()):                 # dead at the resume (overwritten before any read): free scratch
                got.pop(r); want.pop(r)
            assert got == want, thunk


@pytest.mark.parametrize("g", GL)
@pytest.mark.parametrize("thunk,site,ln,seed,law", DETOURS)
def test_detour_law(g, thunk, site, ln, seed, law):
    """g>16: the cave's outputs follow the law; every OTHER register / the stack / the cursor match the displaced pristine
    bytes run under the walker's row values -- i.e. only the scaled quantity changes."""
    for reg in REGIONS:
        e = Emu(g); regs = seed(e, reg)
        got = _run_detour(e, VA[thunk], site + ln, regs)
        want = {k: v for k, v in law(reg, g).items() if v is not None}
        for k, v in want.items():
            assert got[k] == v & 0xFFFFFFFF if k in REGS else got[k] == v, (thunk, k, got[k], v)
        assert got["esp"] == SP0 - (4 if thunk == "t_rw_labs_w" else 0)
        if thunk == "t_rw_labs_w":
            assert r32(e.uc, SP0 - 4) == 0                                      # vanilla's `push 0` survives
        for r in ("ebx", "esi", "ebp"):
            assert got[r] == regs[r] & 0xFFFFFFFF


@pytest.mark.parametrize("g", GL)
def test_detour_chain_draws_the_law_box(g):
    """The labs/ops box rect built from the caves' w is the law's tab box: {L+C, T+C, (L+C) + w, T+C+s(0x1A)}."""
    for reg in REGIONS:
        e = Emu(g); regs = _seed_labs_w(e, reg)
        st = _run_detour(e, VA["t_rw_labs_w"], 0x4A7039, regs)
        box, _l, _r = SL.rw_tab_pair(reg, g)
        C = SL.rw_console_box_inset(g)
        assert (reg[0] + C, reg[0] + C + st["edx"]) == (box[0], box[2])
        e = Emu(g); regs = _seed_ops(e, reg)
        st = _run_detour(e, VA["t_rwk_ops_w"], 0x4A90E6, regs)
        assert reg[0] + C + st["eax"] == box[2]


# ---- the site table -----------------------------------------------------------------------------
NEW_REDIRECTS = {0x4A7094: "t_rwk_boxforce", 0x4A70BF: "t_rw_rowframe", 0x4A7AD6: "t_rw_rowframe", 0x4A7B01: "t_rw_rowframe",
                 0x4A3EA4: "t_rw_rowframe", 0x4A3EB4: "t_rw_rowframe"}
NEW_REDIRECTS.update({va: "t_rw_rowframe" for va, _fn, _w in AR.D528_SITES})   # 2026-10-17 console chain: 24 d528 boxes
COVERED_ROWS = (0x4A7038, 0x4A7052, 0x4A7A80, 0x4A7A97, 0x4A45CC, 0x4A47A3, 0x4A90E5, 0x4A90AA, 0x4A90C1, 0x4A4F07,
                0x4A4F0A, 0x4A4F1B, 0x4A4C46, 0x4A492F, 0x4A4851)


def _sites():
    return {st["va"]: st for st in AR.site_list(VA)}


def test_new_redirects_target_the_half_open_helpers():
    sites = _sites()
    for va, thunk in NEW_REDIRECTS.items():
        st = sites[va]
        assert st["pattern"] == "call_target_redirect" and st["new"] == f"E8 {{rel32:{thunk}}}"
        assert st["orig"] == bytes([0xE8]) + struct.pack("<i", AR.BOX_SPRITE - (va + 5)) == SE.base_exe_bytes(va, 5)


def test_detour_sites_shape():
    sites = _sites()
    for thunk, site, ln, _seed, _law in DETOURS + [(t, s_, n - s_, None, None) for t, s_, n, *_ in SPLITS]:
        st = sites[site]
        assert st["pattern"] == "detour_inplace" and len(st["orig"]) == ln and st["orig"] == SE.base_exe_bytes(site, ln)
        b = SE.base_exe_bytes(site, ln + 16)
        assert site + ln in {i.address + i.size for i in _cs.disasm(b, site)}, f"{thunk}: {site:#x}+{ln} cuts an instruction"
        assert st["new"].startswith("E9 ") and f"(E9 -> {thunk})" in st["note"]


def test_covered_rows_left_the_walker_table():
    rows = {r[0] for r in AR.rw_rows()}
    for site in COVERED_ROWS:
        assert site not in rows, hex(site)
    tuples = []
    for st in AR.site_list(VA):
        toks = st["new"].split()
        first = int(toks[0], 16) if toks and not toks[0].startswith("{") else -1
        tuples.append((st["va"], sum(4 if x.startswith("{") else 1 for x in toks), first, st["id"]))
    chain = [(site, 0, 0, AR.K['K_W4'] if w == 4 else 0) for site, w, *_ in AR.CHAIN_ROWS]
    assert AR.row_site_conflicts(AR.rw_rows() + AR.tech_rows() + chain, tuples) == []
    for site in AR.CHAIN_SITES:                          # the chain rows are t_rw_immsum's, never also an HD row
        assert site not in rows, hex(site)


def test_rw_table_keeps_its_footprint():
    """the cells after the tech table are referenced by literal VA elsewhere (G_RW_INLIST 0x27488, G_RW_SBS 0x27564).
    2026-10-25 F44: the two tables' joint footprint stays 6836 + the tech table; the tech table took 32 B of the rw
    table's zero tail (+2 rows) and ends where it did."""
    assert len(AR.RW_TAB) == AR.RW_TAB_LEN == 6836 - 32
    assert AR.TAB_TECH == AR.PCAVE2 + 0x26A30 and AR.TAB_TECH + len(AR.TECH_TAB) == AR.PCAVE2 + 0x27474
    assert AR.CELL["g_rw_inlist"] == AR.PCAVE2 + 0x27488 and AR.CELL["g_rw_sbs"] == AR.PCAVE2 + 0x27564


def _resync_starts(code: bytes, lo: int) -> set:
    """Instruction starts of a RESYNCHRONISING linear sweep: where capstone stops (data, e.g. the 0x4A6FF0 jump table),
    skip one byte and carry on, so the sweep covers the whole range (a plain sweep stops at 0x4A6FDC)."""
    starts, off = set(), 0
    while off < len(code):
        n = 0
        for ins in _cs.disasm(code[off:], lo + off):
            starts.add(ins.address)
            n = ins.address + ins.size - (lo + off)
        off += n if n else 1
    return starts


def test_no_branch_lands_inside_a_skipped_span():
    """The g>16 paths resume PAST vanilla code (the split caves skip the four rect stores; every detour skips its
    displaced bytes) and every redirect rewrites a call's rel32: no jump / call / dword literal anywhere in the report
    code may land strictly inside one of those spans.  A direct branch is decoded at EVERY byte offset (rel8 jcc/jmp,
    rel32 jmp/call/jcc); a hit counts unless the resynchronising sweep puts its offset strictly inside another
    instruction (a mid-instruction decode, not code)."""
    spans = [(site, lres) for _t, site, _n, lres, *_ in SPLITS] + [(site, site + ln) for _t, site, ln, *_ in DETOURS]
    spans += [(va, va + 5) for va in NEW_REDIRECTS]
    lo, hi = 0x496000, 0x4AD000
    code = SE.base_exe_bytes(lo, hi - lo)
    starts = _resync_starts(code, lo)
    bad = []
    for off in range(len(code) - 1):
        op, t = code[off], None
        if op in (0xE8, 0xE9) and off + 5 <= len(code):
            t = lo + off + 5 + struct.unpack_from("<i", code, off + 1)[0]
        elif (op == 0xEB or 0x70 <= op <= 0x7F):
            t = lo + off + 2 + struct.unpack_from("<b", code, off + 1)[0]
        elif op == 0x0F and 0x80 <= code[off + 1] <= 0x8F and off + 6 <= len(code):
            t = lo + off + 6 + struct.unpack_from("<i", code, off + 2)[0]
        if t is not None and any(a < t < b for a, b in spans) and lo + off in starts:
            bad.append((hex(lo + off), hex(t)))
    for off in range(len(code) - 3):
        v = struct.unpack_from("<I", code, off)[0]
        bad += [("lit", hex(lo + off)) for a, b in spans if a < v < b]
    assert not bad, bad
    assert max(starts) > 0x4AC000 and 0x4A7032 in starts and 0x4AC752 in starts    # the sweep reaches past the table


def test_pins_are_inside_their_reservations():
    layout, _cells, _end, names = AR.assemble_all()
    for name in ("t_rw_tabpair", "t_rw_insetv", "t_rw_labs_w", "t_rw_labs_h", "t_rw_labs_rh",
                 "t_rwk_ops_w", "t_rwk_govlist", "t_rwk_ops_lw", "t_rwk_ops_lx", "t_rw_immsum"):
        off, b = layout[name]
        assert off == RK.PINNED[name] and off + len(b) <= RK.PINNED_END[name], name
    assert layout["t_rw_btnr"][0] == 0x24830 and layout["t_rwk_sat_split1"][0] == 0x24B10   # FROZEN neighbours kept
