"""Differential: the BAKED positive popup edge-gap thunks must agree with the Python laws.

`scaling_laws.py::tutwin_place / tutwin_window_h / popup_positive_loc` are the source
of truth; the x86 that ships (patches.yaml cave contents + site bytes, resolved by the
patcher's own ByteTemplate / symbol table -- the exact bytes the bake writes) runs under
Unicorn, spliced into the PRISTINE engine code from the .bak.

  * t_tw_gap: the pristine TutWin_tut_win placement block 0x4BE2A7..0x4BE38C runs first
    (vanilla's branch decisions), then the patched site + thunk, then the pristine arrow2
    copy to 0x4BE3BA. Sweep g in {0, 12} + [16,40] x 8 resolutions x kinds 0..6 x a
    target grid x box sizes x btnH {20, 0}: (x, y, attach_x, attach_y) == tutwin_place,
    vanilla byte for byte at g <= 16, the jl at 0x4BE391 sees [ebp+0x20]'s sign, eax ==
    [ebp+0x20], ecx/edx preserved, arrow2 copies the patched attach point, and the result
    does not depend on the canvas [+0x4C8] (stale between TutWin's two passes).
  * the static facts behind reading the window height off the grow law instead of the
    canvas (TutWin's pass 1 is exec_3(1,0), which returns before the window exists; the
    fields the thunk reads are not touched between there and box_grow).
  * t_scrloc_x / t_scrloc_y: isolated and inside the real parse tail; census values,
    the 0x2000 KEEP, the 0x1000 centre, 0 and negatives untouched; only the field written.
  * NetMsg_pop's set_loc call 0x47A94F is VANILLA (fix 6's t_netmsg_loc backed out 2026-10-22,
    user decision: no visible case verified): no site touches it, the .bak bytes there are
    `call BasePop_set_loc`, and no cave content or symbol named t_netmsg_loc remains.
  * Script.txt / xscript.txt: the positive #x/#y label set.

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import (  # noqa: E402
    NATIVE_G, POPUP_LOC_CENTRE, POPUP_LOC_KEEP, TUTWIN_EDGE_GAP_X, TUTWIN_EDGE_GAP_Y,
    popup_button_row_growth, popup_positive_loc, popup_scale_floor, tutwin_place,
    tutwin_window_h,
)
import apply_patches as ap  # noqa: E402
import assemble_popup_edge_pos as ASM  # noqa: E402
import config  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent -- asm parity unverified")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

PAGE = 0x1000
G_ADDR = ASM.G_ADDR
SET_LOC = ASM.SET_LOC
THUNK_NAMES = ("t_tw_gap", "t_scrloc_x", "t_scrloc_y")
G_SWEEP = (0, 12) + tuple(range(NATIVE_G, 41))
RESOLUTIONS = ((800, 600), (1024, 768), (1280, 1024), (1600, 900), (1920, 1080),
               (1600, 1200), (2560, 1440), (3840, 2160))

TW_BLOCK = 0x004BE2A7                    # mov ebx,[ebp-0x18] (after the measure pass returns)
TW_SITE = ASM.SITE_TW                    # 0x4BE38C
TW_JL = 0x004BE391                       # jl 0x4BE3BA (reads the replayed test's flags)
TW_END = 0x004BE3BA                      # after the arrow2 copy
OBJ = 0x01000000                         # the TutWin (esi)
FRAME = 0x01100000                       # ebp
STACK_TOP = 0x010F0000


def _i32(v: int) -> bytes:
    return int(v & 0xFFFFFFFF).to_bytes(4, "little")


def _rd(mu, va: int) -> int:
    return int.from_bytes(mu.mem_read(va, 4), "little", signed=True)


def _num(v) -> int:
    return int(v, 16) if isinstance(v, str) else int(v)


# --- the bytes the bake writes -------------------------------------------------------

@pytest.fixture(scope="module")
def baked():
    """{name: (va, bytes)} for the 4 thunks + {site_va: (original, new_bytes)} -- resolved
    from patches.yaml by the patcher itself (ByteTemplate + build_symbol_table)."""
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = ap.build_symbol_table(doc["symbols"], doc["code_caves"])
    thunks = {}
    for cave in doc["code_caves"]:
        base = _num(cave["virtual_addr"])
        for c in cave.get("contents", []) or []:
            if c["id"] in THUNK_NAMES:
                va = base + _num(c["offset"])
                thunks[c["id"]] = (va, ap.ByteTemplate(c["bytes"]).resolve(va, symtab), c["bytes"])
    sites = {}
    for s in doc["sites"]:
        if s.get("group") == "popup_edge_positive_scale":
            va = _num(s["virtual_addr"])
            sites[va] = (s, bytes.fromhex(s["original_bytes"]),
                         ap.ByteTemplate(s["new_bytes"]).resolve(va, symtab))
    return {"thunks": thunks, "sites": sites, "symtab": symtab, "doc": doc}


def test_yaml_matches_the_assembler(baked):
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    assert baked["symtab"]["g_popup_scale_num"] == G_ADDR
    assert baked["symtab"]["BasePop_set_loc"] == SET_LOC
    for name, off, tpl, size, _free in ASM.THUNKS:
        va, blob, raw = baked["thunks"][name]
        assert va == ASM.PCAVE2_VA + off, f"{name}: cave content slot != assembler slot"
        assert raw.split() == tpl.split(), f"{name}: yaml bytes != assembler template"
        assert blob == ASM.blob(name) and len(blob) == size, name
        m = re.search(rf"\n  {name}:\s*\{{ cave: pcave2, offset: (0x[0-9A-Fa-f]+) \}}", text)
        assert m and int(m.group(1), 16) == off, f"{name}: ledger slot != assembler slot"
    assert set(baked["sites"]) == {va for va, _o, _n in ASM.SITES}
    for va, orig, new_tpl in ASM.SITES:
        s, o, n = baked["sites"][va]
        assert s["status"] == "confirmed"
        assert o == bytes.fromhex(orig), f"0x{va:X}: original bytes"
        assert s["new_bytes"].split() == new_tpl.split(), f"0x{va:X}: new bytes"
        assert len(n) == s["length"] == len(o)


def test_sites_match_the_pristine_exe(baked, bak_bytes):
    for va, (s, orig, new) in baked["sites"].items():
        assert bak_bytes[va - 0x400000: va - 0x400000 + len(orig)] == orig, f"0x{va:X}"
        tgt = va + 5 + int.from_bytes(new[1:5], "little", signed=True)
        name = re.search(r"rel32:(\w+)", s["new_bytes"]).group(1)
        assert new[0] == 0xE8 and tgt == baked["thunks"][name][0], f"0x{va:X} -> {name}"


# --- laws ------------------------------------------------------------------------------

@pytest.mark.parametrize("g,gx,gy", ((16, 5, 8), (22, 6, 11), (25, 7, 12), (40, 12, 20)))
def test_tutwin_gap_pins(g: int, gx: int, gy: int):
    """1024x768 / 1920x1080 / 1600x1200 / 4K."""
    sw, sh = 3840, 2160
    for left, bottom in ((True, True), (False, True)):
        x, y, ax, ay = tutwin_place(sw, sh, 1000, 500, 20, 0, left, bottom, g)
        assert (x if left else sw - 1000 - x) == gx
        assert sh - (y + tutwin_window_h(500, 20, g)) == gy
    assert popup_scale_floor(TUTWIN_EDGE_GAP_X, g) == gx and popup_scale_floor(TUTWIN_EDGE_GAP_Y, g) == gy


@pytest.mark.parametrize("g", (0, 8, 12, 16))
def test_laws_are_vanilla_at_low_res(g: int):
    for sw, sh in RESOLUTIONS:
        for left in (True, False):
            for bottom in (True, False):
                x, y, ax, ay = tutwin_place(sw, sh, 491, 211, 20, 300, left, bottom, g)
                vx = 5 if left else sw - 491 - 5
                vax = 5 + 245 if left else sw - 245 - 5
                vy = sh - 211 - 8 if bottom else 300 // 8
                assert (x, y, ax, ay) == (vx, vy, vax, vy if bottom else vy + 211)
    for v in (-20, -5, 0, 5, 40, 0xFFF, 0x1000, 0x2000):
        assert popup_positive_loc(v, g) == v
    assert tutwin_window_h(211, 20, g) == 211


def test_4k_bottom_rail_repro():
    """Vanilla at 4K: y = 2160 - boxH - 8 while the window is boxH + 30 -> 22 px below the
    screen; 1920x1080 (g=22): 1 px from the edge. The law puts it fl(8g/16) above."""
    for g, over in ((40, 22), (22, -1)):
        d = popup_button_row_growth(20, g)
        assert 8 - d == -over
        x, y, _, _ = tutwin_place(3840, 2160, 1000, 527, 20, 0, True, True, g)
        assert 2160 - (y + 527 + d) == popup_scale_floor(8, g)


# --- t_tw_gap: pristine placement block + the patched join ---------------------------

class TwRig:
    """Two emulators -- the pristine exe and the baked one -- so no translated block of one
    build is ever reused by the other (Unicorn caches TBs across host-side code writes)."""

    def __init__(self, bak: bytes, baked):
        va, blob, _ = baked["thunks"]["t_tw_gap"]
        self.thunk_va = va
        self.mus = {}
        for patched in (False, True):
            mu = Uc(UC_ARCH_X86, UC_MODE_32)
            for base, size in ((0x004BE000, 2 * PAGE), (va & ~(PAGE - 1), 2 * PAGE),
                               (G_ADDR & ~(PAGE - 1), PAGE), (OBJ, 0x10000),
                               (STACK_TOP - 0x10000, 0x20000 + 0x10000)):
                mu.mem_map(base, size)
            mu.mem_write(0x004BE000, bak[0xBE000:0xC0000])
            if patched:
                mu.mem_write(TW_SITE, baked["sites"][TW_SITE][2])
                mu.mem_write(va, blob)
            mu.hook_add(UC_HOOK_CODE, self._snap, begin=TW_SITE, end=TW_SITE)
            mu.hook_add(UC_HOOK_CODE, self._snap, begin=TW_JL, end=TW_JL)
            self.mus[patched] = mu
        self.snaps = {}

    REGS = (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_EDI,
            UC_X86_REG_ESI, UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS)

    def _snap(self, mu, addr, _size, _ud):
        """Registers on reaching the site and the jl. ONE emu_start per run with ONE fixed
        `until`: Unicorn chains cached translation blocks past a stop address that differs
        from the one they were translated under, so staged emu_start calls are unreliable."""
        self.snaps[addr] = {r: mu.reg_read(r) for r in self.REGS}

    def run(self, *, g, sw, sh, kind, tx, ty, box_w, box_h, btn_h, x2=3, canvas_h=None,
            patched=True):
        mu = self.mus[patched]
        mu.mem_write(G_ADDR, _i32(g))
        mu.mem_write(OBJ, b"\0" * 0x10000)
        mu.mem_write(FRAME - 0x40, b"\0" * 0x80)
        for off, v in ((-0x18, sh), (-0x14, sw), (0x10, tx), (0x14, ty), (0x1C, kind),
                       (0x20, x2), (0x24, 77)):
            mu.mem_write(FRAME + off, _i32(v))
        for off, v in ((0x30BC, box_w), (0x30C0, box_h), (0x30D0, btn_h), (0x5388, ty),
                       (0x4C4, box_w), (0x4C8, -(canvas_h if canvas_h is not None else 0)),
                       (0x539C, -1), (0x53A0, -1), (0x5394, -1), (0x5398, -1)):
            mu.mem_write(OBJ + off, _i32(v))
        esp = STACK_TOP - 0x100
        for reg, v in ((UC_X86_REG_ESI, OBJ), (UC_X86_REG_EBP, FRAME), (UC_X86_REG_ESP, esp),
                       (UC_X86_REG_EAX, 0x1111), (UC_X86_REG_ECX, 0x2222), (UC_X86_REG_EDX, 0x3333),
                       (UC_X86_REG_EBX, 0x4444), (UC_X86_REG_EDI, 0x5555)):
            mu.reg_write(reg, v)
        self.snaps = {}
        mu.emu_start(TW_BLOCK, TW_END, count=3000)
        assert mu.reg_read(UC_X86_REG_EIP) == TW_END
        assert set(self.snaps) == {TW_SITE, TW_JL}, "site and jl each reached once"
        keep = (UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_EDI,
                UC_X86_REG_ESI, UC_X86_REG_EBP)
        s0, s1 = self.snaps[TW_SITE], self.snaps[TW_JL]
        pre = {r: s0[r] for r in keep}
        at_jl = {"eax": s1[UC_X86_REG_EAX], "flags": s1[UC_X86_REG_EFLAGS],
                 "esp": s1[UC_X86_REG_ESP], "regs": {r: s1[r] for r in keep}}
        out = tuple(_rd(mu, a) for a in (FRAME + 0x10, FRAME + 0x14, OBJ + 0x538C, OBJ + 0x5390))
        arrow2 = tuple(_rd(mu, OBJ + o) for o in (0x5394, 0x5398, 0x539C, 0x53A0))
        return out, at_jl, pre, esp, arrow2


@pytest.fixture(scope="module")
def tw(bak_bytes, baked):
    return TwRig(bak_bytes, baked)


def _boxes(g: int, sw: int):
    gg = max(g, NATIVE_G)
    return ((popup_scale_floor(491, gg), popup_scale_floor(211, gg)),   # the crash-land LANDFALL box
            (popup_scale_floor(250, gg), popup_scale_floor(96, gg)),    # a short hint
            (min(sw - 40, popup_scale_floor(700, gg)), popup_scale_floor(380, gg)))


def _sweep(tw, g: int, sw: int, sh: int):
    n = 0
    for kind in range(7):
        for box_w, box_h in _boxes(g, sw):
            for btn_h in (20, 0):
                for tx in (0, sw // 7, sw // 3, sw // 2, sw * 2 // 3, sw - 1):
                    for ty in (0, sh // 9, sh // 3, sh * 5 // 8, sh * 4 // 5, sh - 1):
                        kw = dict(g=g, sw=sw, sh=sh, kind=kind, tx=tx, ty=ty,
                                  box_w=box_w, box_h=box_h, btn_h=btn_h)
                        van, _, _, _, _ = tw.run(**kw, patched=False)
                        left, bottom = van[0] == TUTWIN_EDGE_GAP_X, van[3] == van[1]
                        got, at_jl, pre, esp, arrow2 = tw.run(**kw)
                        want = tutwin_place(sw, sh, box_w, box_h, btn_h, ty, left, bottom, g)
                        assert got == want, (kw, left, bottom, van, got, want)
                        if g <= NATIVE_G:
                            assert got == van, ("native no-op", kw)
                        assert at_jl["eax"] == 3, "replayed mov eax,[ebp+0x20]"
                        assert at_jl["regs"] == pre, "ecx/edx/ebx/edi/esi/ebp must survive"
                        assert at_jl["esp"] == esp
                        assert arrow2 == (3, 77, got[2], got[3]), "arrow2 copies the patched attach"
                        n += 1
    return n


@pytest.mark.parametrize("sw,sh", RESOLUTIONS)
@pytest.mark.parametrize("g", G_SWEEP)
def test_tw_gap_matches_tutwin_place(tw, g: int, sw: int, sh: int):
    assert _sweep(tw, g, sw, sh) == 7 * 3 * 2 * 36


@pytest.mark.parametrize("x2", (-1, -0x80000000, 0, 1, 0x7FFFFFFF))
@pytest.mark.parametrize("g", (16, 25, 40))
def test_tw_gap_keeps_the_jl_flags(tw, g: int, x2: int):
    """`jl 0x4BE3BA` must see `test eax,eax` on [ebp+0x20] (x2): negative -> no arrow2."""
    out, at_jl, _, _, arrow2 = tw.run(g=g, sw=3840, sh=2160, kind=0, tx=100, ty=100,
                                      box_w=1227, box_h=527, btn_h=20, x2=x2)
    fl = at_jl["flags"]
    sf, of, zf = (fl >> 7) & 1, (fl >> 11) & 1, (fl >> 6) & 1
    assert at_jl["eax"] & 0xFFFFFFFF == x2 & 0xFFFFFFFF
    assert of == 0 and sf == (x2 < 0) and zf == (x2 == 0)
    if x2 < 0:
        assert arrow2 == (-1, -1, -1, -1), "arrow2 must stay unset"
    else:
        assert arrow2 == (x2, 77, out[2], out[3])


@pytest.mark.parametrize("g", (22, 25, 40))
def test_tw_gap_ignores_the_stale_canvas(tw, g: int):
    """Between the two passes the canvas [+0x4C8] is the PREVIOUS tooltip's window (or 0
    on the first show): the placement must not depend on it."""
    kw = dict(g=g, sw=3840, sh=2160, kind=0, tx=200, ty=300, box_w=1227, box_h=527, btn_h=20)
    ref = tw.run(**kw)[0]
    for stale in (0, 300, 527, 527 + popup_button_row_growth(20, g), 1400):
        assert tw.run(**kw, canvas_h=stale)[0] == ref, stale


# --- why the window height comes from the grow law, not the canvas -------------------

def _disasm(bak: bytes, start: int, end: int):
    cs = pytest.importorskip("capstone")
    md = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_32)
    md.detail = True
    return list(md.disasm(bak[start - 0x400000:end - 0x400000], start))


def _writes_field(ins, disp: int) -> bool:
    import capstone.x86 as X
    for op in ins.operands:
        if op.type == X.X86_OP_MEM and op.mem.disp == disp and op.access & 2:
            return True
    return False


def test_tutwin_pass1_is_measure_only(bak_bytes):
    """TutWin's first exec_3 is exec_3(1, 0) and exec_3 returns for a2 != 0 BEFORE the
    window's GraphicWin_init and box_grow: at the placement no window exists for this box,
    so the canvas [+0x4C8] cannot carry its grown height."""
    b = bak_bytes
    assert b[0xBE29D:0xBE2A2] == bytes.fromhex("53 6A 01 8B CE")       # push ebx(=0) ; push 1 ; mov ecx,esi
    assert b[0xBE2A2] == 0xE8 and 0x4BE2A7 + int.from_bytes(b[0xBE2A3:0xBE2A7], "little", signed=True) == 0x602600
    ins = _disasm(b, 0x4BE00B, 0x4BE29D)
    assert ins[0].mnemonic == "xor" and ins[0].op_str == "ebx, ebx"
    assert not any(i.op_str.startswith("ebx,") and i.mnemonic in ("mov", "xor", "add", "sub", "pop", "lea")
                   for i in ins[1:]), "ebx stays 0 up to the pass-1 call"
    # exec_3: [esp+0x40] is a2 (4 pushes + 0x2C frame); nonzero -> 0x6037DE xor eax,eax; epilogue
    assert b[0x2027A9:0x2027B1] == bytes.fromhex("8B 44 24 40 85 C0 0F 85")
    assert 0x6027B5 + int.from_bytes(b[0x2027B1:0x2027B5], "little", signed=True) == 0x6037DE
    assert b[0x2037DE:0x2037E0] == bytes.fromhex("33 C0")
    # the box_grow load and the window creation both lie past that exit
    assert b[0x202861:0x202867] == bytes.fromhex("8B 8E C0 30 00 00")
    assert b[0x20287C] == 0xE8 and 0x602881 + int.from_bytes(b[0x20287D:0x202881], "little", signed=True) == 0x5D4EF0
    creators = {0x5D4EF0, 0x5D7670, 0x5D79C0, 0x5D5540}   # GraphicWin_init, Buffer_init, Buffer_resize, GraphicWin_resize
    for i in _disasm(b, 0x602600, 0x6027B5):
        if i.mnemonic == "call" and i.op_str.startswith("0x"):
            assert int(i.op_str, 16) not in creators, f"window creation before the a2 exit @0x{i.address:X}"


def test_window_height_fields_are_stable_until_box_grow(bak_bytes, baked):
    """The thunk reads [+0x30C0] / [+0x30D0] at 0x4BE38C; box_grow reads them at 0x602861 in
    pass 2, after pass 2's own calc (vtbl+0x168 @0x60279B). Nothing in either window writes
    them, the only call in between is vtbl+0x16c (a bare RET for TutWin), and no patch site
    lands in either window (so the pristine analysis is the shipped one)."""
    for start, end in ((0x4BE2A7, 0x4BE38C), (0x6027A1, 0x602861)):
        for i in _disasm(bak_bytes, start, end):
            assert not (_writes_field(i, 0x30C0) or _writes_field(i, 0x30D0)), f"0x{i.address:X}"
    calls = [i for i in _disasm(bak_bytes, 0x6027A1, 0x602861) if i.mnemonic == "call"]
    assert [c.op_str for c in calls] == ["dword ptr [eax + 0x16c]"]
    vt = 0x0066DD84                                          # TutWin_vtbl
    slot = lambda k: int.from_bytes(bak_bytes[vt + k - 0x400000:vt + k + 4 - 0x400000], "little")
    assert slot(0x16C) == 0x404280 and bak_bytes[0x4280] == 0xC3
    assert slot(0x168) == 0x404B10                          # Popup_calculate_dimensions
    assert slot(0x174) == 0x405020                          # -> [+0x30D0] = 0x14 (0x40503F)
    assert bak_bytes[0x503F:0x5049] == bytes.fromhex("C7 81 D0 30 00 00 14 00 00 00")
    for s in baked["doc"]["sites"]:
        if s.get("status") != "confirmed":
            continue
        va = _num(s["virtual_addr"])
        lo, hi = va, va + int(s["length"])
        for a, b in ((0x4BE2A7, 0x4BE38C), (0x6027A1, 0x602861)):
            assert hi <= a or lo >= b, f"site {s['id']} patches the analysed window"


def test_grow_reads_the_same_field(baked):
    """box_grow (t_dp_growbox_gate -> thunk_grow_box) adds fl([+0x30D0]*g/16) - [+0x30D0]
    unless [+0xA14] is the diplomacy window: the law popup_button_row_growth on the field
    t_tw_gap reads. TutWin's Popup_start flags never carry 0x100000, so BasePop_start
    clears [+0xA14] (0x601C71) and the gate always grows."""
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r"- id: thunk_grow_box\s+offset: \S+\s+bytes: \"([^\"]+)\"", text)
    assert m and "8B 86 D0 30 00 00 8B D0 0F AF 05 {abs32:g_popup_scale_num} C1 F8 04 2B C2 " \
                 "8B 8E C0 30 00 00 03 C8" in m.group(1)


def test_tutwin_popup_start_flags_keep_a14_clear(bak_bytes):
    b = bak_bytes
    assert b[0xBE04B:0xBE052] == bytes.fromhex("C7 45 F0 40 00 00 00")   # 0x40
    assert b[0xBE054:0xBE057] == bytes.fromhex("89 5D F0")               # ebx = 0
    assert b[0xBE059:0xBE060] == bytes.fromhex("C7 45 F0 00 40 00 00")   # 0x4000
    assert b[0x201C69:0x201C7B] == bytes.fromhex("F7 C3 00 00 10 00 75 0A C7 86 14 0A 00 00 00 00 00 00")


# --- t_scrloc_x / t_scrloc_y -----------------------------------------------------------

SCRIPT_VALUES = (5, 10, 20, 40, 1, 0xFFF, 0, -1, -5, -20, -0xFFF, -0x1000,
                 POPUP_LOC_CENTRE, POPUP_LOC_CENTRE + 1, POPUP_LOC_KEEP, 0x7FFFFFFF, -0x80000000)


@pytest.fixture(scope="module")
def parse_rig(bak_bytes, baked):
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((0x00601000, 2 * PAGE), (0x00A0D000, PAGE), (G_ADDR & ~(PAGE - 1), PAGE),
                       (OBJ, 0x10000), (STACK_TOP - 0x10000, 0x20000)):
        mu.mem_map(base, size)
    mu.mem_write(0x00601000, bak_bytes[0x201000:0x203000])
    for va, (_s, _o, new) in baked["sites"].items():
        if 0x601000 <= va < 0x603000:
            mu.mem_write(va, new)
    for name in ("t_scrloc_x", "t_scrloc_y"):
        va, blob, _ = baked["thunks"][name]
        mu.mem_write(va, blob)
    return mu


def _parse(mu, start: int, field: int, g: int, v: int):
    mu.mem_write(G_ADDR, _i32(g))
    mu.mem_write(OBJ + 0x30F0, b"\xAA" * 0x20)
    esp = STACK_TOP - 0x200
    for reg, val in ((UC_X86_REG_EAX, v), (UC_X86_REG_ESI, OBJ), (UC_X86_REG_ESP, esp),
                     (UC_X86_REG_EBX, 0xB0B0), (UC_X86_REG_ECX, 0xC0C0), (UC_X86_REG_EDX, 0xD0D0),
                     (UC_X86_REG_EDI, 0xE0E0), (UC_X86_REG_EBP, 0xF0F0)):
        mu.reg_write(reg, val)
    mu.emu_start(start, 0x00601D05, count=100)            # the parse loop head (both arms jmp there)
    assert mu.reg_read(UC_X86_REG_ESP) == esp
    for reg, val in ((UC_X86_REG_EBX, 0xB0B0), (UC_X86_REG_ECX, 0xC0C0), (UC_X86_REG_EDX, 0xD0D0),
                     (UC_X86_REG_EDI, 0xE0E0), (UC_X86_REG_EBP, 0xF0F0), (UC_X86_REG_ESI, OBJ)):
        assert mu.reg_read(reg) == val
    raw = bytes(mu.mem_read(OBJ + 0x30F0, 0x20))
    other = raw[:field - 0x30F0] + raw[field - 0x30F0 + 4:]
    assert other == b"\xAA" * 0x1C, "only the parsed field may be written"
    return raw[field - 0x30F0:field - 0x30F0 + 4]


@pytest.mark.parametrize("axis,start,field", (("x", 0x00601E86, 0x30F8), ("y", 0x00601ED4, 0x30FC)))
@pytest.mark.parametrize("g", G_SWEEP)
def test_script_loc_parse(parse_rig, axis: str, start: int, field: int, g: int):
    """The real parse tail (`cmp eax,0x2000; je loop; <site>; jmp loop`) + the thunk."""
    for v in SCRIPT_VALUES:
        got = _parse(parse_rig, start, field, g, v)
        if v == POPUP_LOC_KEEP:
            assert got == b"\xAA" * 4, "0x2000 KEEP must not store"
        else:
            assert int.from_bytes(got, "little", signed=True) == popup_positive_loc(v, g), (axis, g, v)
            if v <= 0 or v >= POPUP_LOC_CENTRE or g <= NATIVE_G:
                assert int.from_bytes(got, "little", signed=True) == v, "must pass through"


@pytest.mark.parametrize("g,want", ((16, 5), (22, 6), (25, 7), (40, 12)))
def test_factionx_list_flush_with_quote_box(parse_rig, g: int, want: int):
    from scaling_laws import faction_quote_x
    got = int.from_bytes(_parse(parse_rig, 0x00601E86, 0x30F8, g, 5), "little", signed=True)
    assert got == want == faction_quote_x(g)


# --- NetMsg_pop set_loc: vanilla (t_netmsg_loc backed out) ---------------------------------

NETMSG_SITE = 0x0047A94F                 # NetMsg_pop `call BasePop_set_loc(+0x537C, +0x5380)`
NETMSG_SITE_END = NETMSG_SITE + 5


def test_netmsg_set_loc_site_is_vanilla(bak_bytes, baked):
    """Fix 18 (2026-10-22, user decision) backed out fix 6's t_netmsg_loc: NetMsg_g's literal y = 8
    stays unscaled until a visible case is verified ("Bases cannot be built adjacent" takes the ticker
    path 0x47ABBA and never reaches 0x47A94F).  No site may overlap the call, so the bake leaves the
    .bak's `call BasePop_set_loc` there; the cave content and the symbol are gone."""
    assert bak_bytes[0x7A94F:0x7A954] == bytes.fromhex("E8 2C 72 18 00")
    assert 0x0047A954 + int.from_bytes(bak_bytes[0x7A950:0x7A954], "little", signed=True) == SET_LOC
    for site in baked["doc"]["sites"]:
        va = _num(site["virtual_addr"])
        n = max(_num(site.get("length", 0)), len(str(site.get("original_bytes", "")).split()))
        assert va + n <= NETMSG_SITE or va >= NETMSG_SITE_END, ("a site overlaps 0x47A94F", site["id"])
    assert "t_netmsg_loc" not in baked["symtab"]
    for cave in baked["doc"]["code_caves"]:
        assert all(c["id"] != "t_netmsg_loc" for c in cave.get("contents", []) or [])
    assert "NetMsg_pop.set_loc_args" not in {m for g in baked["doc"]["groups"] for m in g.get("members", [])}


def test_netmsg_ctor_census(bak_bytes):
    """The only two NetMessage instances and their ctor constants (x, y, a3)."""
    b = bak_bytes
    assert b[0x7A770:0x7A77E] == bytes.fromhex("6A 00 6A 08 68 00 10 00 00 B9 38 53 80 00")  # NetMsg_g (0x1000, 8, 0)
    assert b[0x7A7A0:0x7A7AB] == bytes.fromhex("6A 01 6A 28 6A FB B9 80 FF 7F 00")          # 0x7FFF80 (-5, 40, 1)
    # NetMsg_ctor: y = [ebp+0xC] -> +0x5380, x = [ebp+8] -> +0x537C
    assert b[0x7AD26:0x7AD35] == bytes.fromhex("8B 4D 0C 8B 45 08 8B 55 10 89 8E 80 53 00 00")
    assert b[0x7AD38:0x7AD3E] == bytes.fromhex("89 86 7C 53 00 00")


# --- script census -------------------------------------------------------------------------

EXPECTED_POSITIVE = {"NEWBASE": (10, 40), "FIRSTBASE": (10, 40), "CHATASK": (5, 40),
                     "BATTLEPAUSE": (20, 20), "FACTIONX": (5, 5)}


def _script_census(path: pathlib.Path):
    label, pos, neg = None, {}, set()
    for line in path.read_text(encoding="latin-1").splitlines():
        m = re.match(r"#([A-Z0-9_]+)\s*$", line)
        if m:
            label = m.group(1)
            continue
        m = re.match(r"#([xyXY])[ \t]+(-?\d+)", line)
        if m:
            v = int(m.group(2))
            if v > 0:
                pos.setdefault(label, {})[m.group(1).lower()] = v
            else:
                neg.add(v)
    return {k: (d.get("x"), d.get("y")) for k, d in pos.items()}, neg


@pytest.mark.parametrize("name", ("Script.txt", "xscript.txt"))
def test_script_positive_label_census(name: str):
    p = config.game_dir(required=False) / name
    if not p.is_file():
        pytest.skip(f"{name} not in the game folder")
    pos, neg = _script_census(p)
    assert pos == EXPECTED_POSITIVE, "a new positive #x/#y literal: check what places it"
    assert all(0 < v < POPUP_LOC_CENTRE for xy in pos.values() for v in xy)
    assert neg <= {-5, -20}, "negatives are the join thunk's (popup_edge_anchor_offset)"
