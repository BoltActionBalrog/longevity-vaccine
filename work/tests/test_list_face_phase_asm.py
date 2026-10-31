"""t_lbi_restripe_ph / t_dw_face_ph (assemble_list_face_phase.py): the faction-picker name list and the Design
Workshop button faces on their parent's stripe grid.

Unicorn on the assembled bytes (and the patches.yaml bytes once baked).  The callee each wrapper reaches is a stub
that records the staged phase cell, ecx and its stack at entry -- the wrapper must stage the law's phase for exactly
that call, keep the calling contract and every register.  The full pixel chain (t_lb_item_stripes -> this wrapper
-> t_tf_restripe -> the real fe) is test_tileforce_asm_parity::test_lb_item_stripes_rows_sit_on_the_picker_grid.
"""
import pathlib
import sys

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_ESP)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import assemble_list_face_phase as LF  # noqa: E402
import scaling_laws as SL  # noqa: E402

STACK, SP0 = 0x00300000, 0x00308000
WIN = 0x00500000                      # the child GraphicWin (list canvas / FlatButton); its Buffer = WIN + 0x444
RET_SITE = 0x00700010
REC = 0x00600000
ARGS = (0x11, 0x22, 0x3333, 0x4444)  # l, t, r, b
REGS = {UC_X86_REG_EBX: 0x1111, UC_X86_REG_ESI: 0x2222, UC_X86_REG_EDI: 0x3333, UC_X86_REG_EBP: 0x4444,
        UC_X86_REG_EDX: 0x5555, UC_X86_REG_EAX: 0x6666}
BUILT = LF.build()
TOPS = [(335, 0), (209, 0), (184, 0), (0, 335), (444, 0), (479, 0), (225, 0), (410, 0), (7, 7), (0, 0), (-3, 0),
        (-1, -6)]
GS = [16, 17, 18, 20, 22, 25, 32, 40]


def _stub(src: str, va: int) -> bytes:
    return LF.assemble(src, va)


def _emu(g, top1, top2):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((LF.PCAVE2, 0x30000), (STACK, 0x10000), (WIN, 0x1000), (REC, 0x1000), (0x668000, 0x1000),
                       (RET_SITE & ~0xFFF, 0x1000)):
        uc.mem_map(base, size)
    for name, (off, b) in BUILT.items():
        uc.mem_write(LF.PCAVE2 + off, b)
    uc.mem_write(LF.G, g.to_bytes(4, "little"))
    uc.mem_write(LF.G_STRIPE_PERIOD, SL.stripe_period(g).to_bytes(4, "little"))
    for cell in (LF.G_RM_YPH, LF.G_SE_YPH):
        uc.mem_write(cell, b"\x00" * 4)
    uc.mem_write(REC, b"\xEE" * 0x40)
    uc.mem_write(WIN + 0x140, (top1 & 0xFFFFFFFF).to_bytes(4, "little"))
    uc.mem_write(WIN + 0x150, (top2 & 0xFFFFFFFF).to_bytes(4, "little"))
    uc.mem_write(RET_SITE, b"\xF4")
    return uc


def _go(uc, entry, stop):
    landed = []

    def hook(u, addr, size, _):
        if addr == stop:
            landed.append(addr)
            u.emu_stop()
    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(entry, 0, count=10_000)
    assert landed == [stop]


r32 = lambda uc, a: int.from_bytes(uc.mem_read(a, 4), "little")  # noqa: E731


# ---- t_lbi_restripe_ph ---------------------------------------------------------------------------------------
def run_lbi(g, top1, top2):
    uc = _emu(g, top1, top2)
    uc.mem_write(LF.T_TF_RESTRIPE, _stub(f"""
        mov  eax, dword ptr [{LF.G_RM_YPH:#x}]
        mov  dword ptr [{REC:#x}], eax
        mov  dword ptr [{REC + 4:#x}], ecx
        mov  eax, dword ptr [esp+4]
        mov  dword ptr [{REC + 8:#x}], eax
        mov  eax, dword ptr [esp+8]
        mov  dword ptr [{REC + 12:#x}], eax
        mov  eax, dword ptr [esp+12]
        mov  dword ptr [{REC + 16:#x}], eax
        mov  eax, dword ptr [esp+16]
        mov  dword ptr [{REC + 20:#x}], eax
        mov  dword ptr [{REC + 24:#x}], esp
        mov  eax, 0x6666
        mov  ecx, 0xCCCC
        mov  edx, 0x5555
        ret  0x10
    """, LF.T_TF_RESTRIPE))
    uc.mem_write(SP0, RET_SITE.to_bytes(4, "little"))
    for i, a in enumerate(ARGS):
        uc.mem_write(SP0 + 4 + 4 * i, a.to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_ECX, WIN + 0x444)
    for r, v in REGS.items():
        uc.reg_write(r, v)
    _go(uc, LF.VA_LBI, RET_SITE)
    return uc, [r32(uc, REC + 4 * i) for i in range(7)]


@pytest.mark.parametrize("g", [g for g in GS if g > 16])
@pytest.mark.parametrize("top1, top2", TOPS)
def test_lbi_stages_the_list_top_phase_around_the_restripe(g, top1, top2):
    uc, rec = run_lbi(g, top1, top2)
    want = SL.faction_list_stripe_phase(top1, top2, g)
    assert rec[0] == want and 0 <= want < SL.stripe_period(g)
    assert rec[1] == WIN + 0x444 and tuple(rec[2:6]) == ARGS          # dest + l,t,r,b in order
    assert r32(uc, LF.G_RM_YPH) == 0                                   # cleared for every other fe caller
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0x10               # RET 0x10 from the site's call
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert uc.reg_read(r) == REGS[r]


def test_lbi_is_a_drop_in_for_t_tf_restripe():
    b = BUILT["t_lbi_restripe_ph"][1]
    assert b.endswith(b"\xC2\x10\x00")                                # the same RET 0x10 contract


# ---- t_dw_face_ph ----------------------------------------------------------------------------------------------
def run_dw(g, top1, top2):
    uc = _emu(g, top1, top2)
    uc.mem_write(LF.DW_BTNFACE, _stub(f"""
        mov  dword ptr [{REC + 4:#x}], eax
        mov  eax, dword ptr [{LF.G_SE_YPH:#x}]
        mov  dword ptr [{REC:#x}], eax
        mov  eax, dword ptr [esp+4]
        mov  dword ptr [{REC + 8:#x}], eax
        mov  dword ptr [{REC + 12:#x}], esp
        mov  dword ptr [{REC + 16:#x}], ecx
        mov  dword ptr [{REC + 20:#x}], edx
        mov  dword ptr [{REC + 24:#x}], ebx
        mov  dword ptr [{REC + 28:#x}], esi
        mov  dword ptr [{REC + 32:#x}], edi
        mov  dword ptr [{REC + 36:#x}], ebp
        xor  eax, eax
        ret  0xC
    """, LF.DW_BTNFACE))
    uc.mem_write(SP0, RET_SITE.to_bytes(4, "little"))
    for i, a in enumerate((WIN, 0x77, 0x88)):
        uc.mem_write(SP0 + 4 + 4 * i, a.to_bytes(4, "little"))
    uc.reg_write(UC_X86_REG_ESP, SP0)
    uc.reg_write(UC_X86_REG_ECX, 0x9999)
    for r, v in REGS.items():
        uc.reg_write(r, v)
    _go(uc, LF.VA_DW, RET_SITE)
    return uc, [r32(uc, REC + 4 * i) for i in range(10)]


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("top1, top2", TOPS)
def test_dw_face_ph_stages_the_button_top_phase_then_enters_btnface(g, top1, top2):
    uc, rec = run_dw(g, top1, top2)
    want = SL.dw_button_face_stripe_phase(top1, top2, g) if g > 16 else 0
    assert rec[0] == want                                               # g<=16: untouched (btnface goes native)
    # btnface is entered exactly as the 0x404220 slot entered us: same esp, same button arg, every register
    assert rec[2] == WIN and rec[3] == SP0
    assert rec[1] == REGS[UC_X86_REG_EAX] and rec[4] == 0x9999 and rec[5] == REGS[UC_X86_REG_EDX]
    assert rec[6:10] == [REGS[r] for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)]
    assert uc.reg_read(UC_X86_REG_ESP) == SP0 + 4 + 0xC


def test_dw_btndraw_jumps_to_the_staging_entry_and_btnface_is_phased():
    import assemble_dw as D
    lay, _ = D.assemble_all()
    off, b = lay["thunk_dw_btndraw"]
    assert off + len(b) <= lay["thunk_dw_btnface"][0], "btndraw outgrew its alignment slack"
    assert D.PCAVE2 + lay["thunk_dw_btnface"][0] == LF.DW_BTNFACE
    i = b.index(b"\xE9")
    assert (D.PCAVE2 + off + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) == LF.VA_DW
    src = D.asm_dw_btnface()
    assert src.count("call    thunk_se_stripe_px_ph\n") == 5 and "call    thunk_se_stripe_px\n" not in src


def test_tileforce_restripe_va_matches():
    import assemble_tileforce as TF
    lay = TF.assemble_all()
    assert TF.PCAVE2 + lay["t_tf_restripe"][0] == LF.T_TF_RESTRIPE


# ---- the measured phases (laws) ----------------------------------------------------------------------------------
def test_measured_faction_list_phases():
    """Picker list canvas parent-local tops: 4K 347-12 = 335, 1600x1200 214-5 = 209, 1920x1080 189-5 = 184 (list
    row 0 / picker frame line, shots 20261011-200837, 20261006-222044, 20261006-222202): the rows moved by
    3 / 1 / 0 -- the 4K and 1600 lists were the ones a stripe off the gaps; 1080 already matched."""
    assert SL.faction_list_stripe_phase(335, 0, 40) == 3
    assert SL.faction_list_stripe_phase(209, 0, 25) == 1
    assert SL.faction_list_stripe_phase(184, 0, 22) == 0


def test_measured_dw_button_phases():
    """1920x1080 DesignWin (frame line y 255): APPLY face 699 -> 444 mod 4 = 0 (on the grid in the shot),
    DONE row 734 -> 479 mod 4 = 3 (a stripe off in the shot), shot 20261006-201336."""
    assert SL.dw_button_face_stripe_phase(444, 0, 22) == 0
    assert SL.dw_button_face_stripe_phase(479, 0, 22) == 3


# MainWin_g-parented DW buttons (DesignWin_build: presets ids 9..0x16, slot-strip arrows 0x17/0x18): their tops are
# MainWin-local.  MainWin's canvas top = SH - fl(257 g / 16), measured as the first console-art row in the HUD
# shots 20261012-005439 (1080: 727), -005214 (1600: 799), -005135 (4K: 1518).
MAINWIN_TOP = {(1080, 22): 727, (1200, 25): 799, (2160, 40): 1518}


def test_measured_mainwin_tops_are_the_strip_window():
    for (sh, g), top in MAINWIN_TOP.items():
        assert top == sh - SL.popup_scale_floor(257, g)


# (name, g, MainWin-local top, phase): the 1080 GARRISON preset's first face row 847 (shot 20261006-201336, on the
# console grid today) - 727 = 120; the 4K slot-strip arrow = hud_unit_arrow_rects' ycen from vanilla's box6
# (T 192, B 248; vanilla arrow y 199 = 192 + (248 - 42 - 192) // 2) = 480 + (620 - 105 - 480) // 2 = 497.
MAINWIN_CHILDREN = [("preset GARRISON 1080", 22, 120, 0), ("slot arrow 4K", 40, 497, 1)]


@pytest.mark.parametrize("name, g, top, phase", MAINWIN_CHILDREN)
def test_mainwin_parented_dw_buttons_stage_their_mainwin_local_phase(name, g, top, phase):
    assert SL.dw_button_face_stripe_phase(top, 0, g) == phase
    for t1, t2 in ((top, 0), (0, top)):                     # a client child keeps it in rRect2, others in rRect1
        uc, rec = run_dw(g, t1, t2)
        assert rec[0] == phase and rec[2] == WIN and rec[3] == SP0, name


def test_arrow_4k_top_from_the_law():
    s = lambda k: SL.popup_scale_floor(k, 40)  # noqa: E731
    cf0, cf8 = s(192), s(248)
    assert SL.hud_unit_arrow_rects((s(779), cf0, s(1020), cf8), s(900), 12, 42, 40)["btn10"][1] == 497


# ---- yaml (after the bake) ---------------------------------------------------------------------------------------
def _yaml_contents():
    import apply_patches as ap
    _s, _g, caves, syms = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    return ap, dict(ap.build_symbol_table(syms, caves)), {c["id"]: c for cave in caves for c in cave.get("contents", [])}


@pytest.mark.parametrize("name", sorted(BUILT))
def test_yaml_bytes_are_the_assembler_output(name):
    ap, symtab, cs = _yaml_contents()
    if name not in cs:
        pytest.skip(f"{name} not baked yet")
    off, b = BUILT[name]
    assert int(cs[name]["offset"]) == off
    assert ap.ByteTemplate(cs[name]["bytes"]).resolve(LF.PCAVE2 + off, symtab) == b


def test_templates_round_trip():
    ap, symtab, _cs = _yaml_contents()
    table = dict(symtab)
    table.update({"t_tf_restripe": LF.T_TF_RESTRIPE})
    for name, (off, b) in BUILT.items():
        assert ap.ByteTemplate(LF.to_template(b, LF.PCAVE2 + off)).resolve(LF.PCAVE2 + off, table) == b, name
