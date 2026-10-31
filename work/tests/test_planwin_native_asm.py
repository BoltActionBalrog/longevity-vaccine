"""PlanWin native render + enlarge (assemble_planwin_native.py; laws scaling_laws.planwin_native_dims / planwin_enlarge).

Unicorn on the patches.yaml bytes of every t_pw_* thunk and of the five sites, over a PlanWin-shaped object whose
canvas Buffer ([[PW]+4]+PW+0x444: clip +0x20, bounds +0x30, data +0x54, w +0x80, h +0x84 (negative), stride +0x4A8)
is a real pixel buffer.  The original bodies behind the entry detours are stubs placed at each trampoline's return
address: they draw a known native pattern at the dims they SEE (as draw_map does through calc_dims), log those dims,
and run the original epilogue -- fit_two's stub also calls render through its patched entry (the engine's nesting),
overlay_draw's stub calls t_pw_present the way the patched site 0x48B3AA does, with a Win vtbl whose +0xFC present
captures the canvas.  Checks: every draw sees vanilla's 239 x 119 at g > 16; the present sees the device dims and the
exact NN enlargement of the native image; after every entry the canvas fields are the device ones again, the state
cells are back to zero, the stack is balanced and the callee-saved registers survive; g <= 16 and an unusable canvas
pass through untouched.
"""
import pathlib
import struct
import sys

import pytest
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESI,
                               UC_X86_REG_ESP)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import assemble_planwin_native as AN  # noqa: E402
import scaling_laws as SL  # noqa: E402

WOFF = 0x1000                                   # [[PW]+4]: the Win part's offset in PlanWin
VBASE = 0x05000000                              # [PW] -> its virtual-base table
WIN = AN.PW + WOFF
BUF = WIN + AN.BUF
VT = 0x05001000                                 # the Win part's vtbl ([WIN])
DATA = 0x06000000
STRIDE = 1024
HALT = 0x05002000
DRAW, LOGWH, PRESENT = 0x0048C000, 0x0048C100, 0x0048C200
LOG = 0x05003000                                # [LOG] = count, then (w, h) pairs
CAP = 0x07000000                                # the present's capture of the canvas (STRIDE-wide rows)
CAPWH = 0x05004000                              # w, h seen by the present
ARGS = 0x05005000
STACK = 0x00300000


def _yaml():
    import apply_patches as ap
    sites, _g, caves, syms = ap.load_patches(ROOT / "patches" / "patches.yaml")
    symtab = dict(ap.build_symbol_table(syms, caves))
    cs = {c["id"]: c for cave in caves for c in cave.get("contents", [])}
    code = {}
    for name, _slot in AN.FUNCS:
        c = cs[name]
        code[name] = (int(c["offset"]), ap.ByteTemplate(c["bytes"]).resolve(AN.PCAVE2 + int(c["offset"]), symtab))
    site = {}
    by_id = {s["id"]: s for s in sites}
    for sid, (va, _orig, _kind, n) in AN.SITES.items():
        s = by_id[sid]
        site[sid] = (int(str(s["virtual_addr"]), 0), ap.ByteTemplate(s["new_bytes"].split("#")[0]).resolve(va, symtab))
    return code, site, symtab, sites, cs, syms


CODE, SITE, SYMTAB, SITE_LIST, CONTENTS, SYMS = _yaml()


def _ks(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    return bytes(enc)


def _stubs() -> dict:
    """{va: bytes} for the original-body stubs and helpers."""
    draw = f"""
        pushad
        call    {LOGWH:#x}
        mov     ecx, dword ptr [{BUF + 0x80:#x}]
        mov     edx, dword ptr [{BUF + 0x84:#x}]
        neg     edx
        xor     edi, edi
    yl:
        cmp     edi, edx
        jge     yd
        xor     esi, esi
    xl:
        cmp     esi, ecx
        jge     xd
        lea     eax, [esi*8]
        sub     eax, esi
        mov     ebx, edi
        imul    ebx, ebx, 13
        add     eax, ebx
        mov     ebx, edi
        imul    ebx, ebx, {STRIDE}
        add     ebx, dword ptr [{BUF + 0x54:#x}]
        mov     byte ptr [ebx+esi], al
        inc     esi
        jmp     xl
    xd:
        inc     edi
        jmp     yl
    yd:
        popad
        ret
    """
    logwh = f"""
        push    eax
        push    ecx
        mov     ecx, dword ptr [{LOG:#x}]
        mov     eax, dword ptr [{BUF + 0x80:#x}]
        mov     dword ptr [{LOG + 4:#x}+ecx*8], eax
        mov     eax, dword ptr [{BUF + 0x84:#x}]
        mov     dword ptr [{LOG + 8:#x}+ecx*8], eax
        inc     dword ptr [{LOG:#x}]
        pop     ecx
        pop     eax
        ret
    """
    present = f"""
        pushad
        mov     eax, dword ptr [{BUF + 0x80:#x}]
        mov     dword ptr [{CAPWH:#x}], eax
        mov     eax, dword ptr [{BUF + 0x84:#x}]
        mov     dword ptr [{CAPWH + 4:#x}], eax
        mov     esi, {DATA:#x}
        mov     edi, {CAP:#x}
        mov     ecx, {STRIDE * 400 // 4:#x}
        rep     movsd dword ptr es:[edi], dword ptr [esi]
        popad
        ret
    """
    render_back = f"""
        call    {DRAW:#x}
        add     esp, 4
        pop     esi
        ret
    """
    overlay_back = f"""
        call    {DRAW:#x}
        mov     ecx, {WIN:#x}
        mov     edx, dword ptr [ecx]
        call    {SYMTAB['t_pw_present']:#x}
        mov     esp, ebp
        pop     ebp
        ret
    """
    fit2_back = f"""
        mov     eax, dword ptr [ebp+8]
        mov     dword ptr [{ARGS:#x}], eax
        mov     eax, dword ptr [ebp+0xc]
        mov     dword ptr [{ARGS + 4:#x}], eax
        mov     eax, dword ptr [ebp+0x10]
        mov     dword ptr [{ARGS + 8:#x}], eax
        mov     eax, dword ptr [ebp+0x14]
        mov     dword ptr [{ARGS + 12:#x}], eax
        mov     eax, dword ptr [ebp+0x18]
        mov     dword ptr [{ARGS + 16:#x}], eax
        call    {LOGWH:#x}
        mov     ecx, {AN.PW:#x}
        call    0x48B3F0
        mov     esp, ebp
        pop     ebp
        ret     0x14
    """
    fit1_back = f"""
        mov     eax, dword ptr [ebp+8]
        mov     dword ptr [{ARGS:#x}], eax
        mov     eax, dword ptr [ebp+0xc]
        mov     dword ptr [{ARGS + 4:#x}], eax
        mov     eax, dword ptr [ebp+0x10]
        mov     dword ptr [{ARGS + 8:#x}], eax
        call    {DRAW:#x}
        mov     esp, ebp
        pop     ebp
        ret     0xc
    """
    # engine-faithful variants (v2): like vanilla, a fit whose zoom + centre come out unchanged does NOT draw unless
    # its force argument is set (fit_two [ebp+0x18] -> render @0x48B898; fit_one [ebp+0x10] -> draw @0x48BA1A)
    fit2_cond = fit2_back.replace(f"""        call    {LOGWH:#x}
        mov     ecx, {AN.PW:#x}
        call    0x48B3F0""", f"""        call    {LOGWH:#x}
        cmp     dword ptr [ebp+0x18], 0
        je      nd
        mov     ecx, {AN.PW:#x}
        call    0x48B3F0
    nd:""")
    fit1_cond = fit1_back.replace(f"""        call    {DRAW:#x}""", f"""        cmp     dword ptr [ebp+0x10], 0
        je      nd
        call    {DRAW:#x}
    nd:""")
    assert fit2_cond != fit2_back and fit1_cond != fit1_back
    base = {DRAW: _ks(draw, DRAW), LOGWH: _ks(logwh, LOGWH), PRESENT: _ks(present, PRESENT),
            0x48B3F5: _ks(render_back, 0x48B3F5), 0x48AF36: _ks(overlay_back, 0x48AF36)}
    always = {**base, 0x48B636: _ks(fit2_back, 0x48B636), 0x48B8E6: _ks(fit1_back, 0x48B8E6)}
    cond = {**base, 0x48B636: _ks(fit2_cond, 0x48B636), 0x48B8E6: _ks(fit1_cond, 0x48B8E6)}
    return always, cond


STUBS, STUBS_COND = _stubs()


def dev_dims(g):
    return (SL.PLANWIN_NATIVE_W * g) // 16, (SL.PLANWIN_NATIVE_H * g) // 16


def make(g, dw, dh, data=DATA, stubs=None):
    stubs = STUBS if stubs is None else stubs
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((AN.PCAVE2, 0x31000), (0x488000, 0x8000), (0x668000, 0x1000), (AN.PW & ~0xFFF, 0x30000),
                       (VBASE, 0x10000), (DATA, STRIDE * 1100), (CAP, STRIDE * 1100), (STACK - 0x10000, 0x20000)):
        uc.mem_map(base, size)
    for _n, (o, b) in CODE.items():
        uc.mem_write(AN.PCAVE2 + o, b)
    for sid, (va, b) in SITE.items():
        if sid != "PlanWin_overlay_draw.present":        # the overlay stub calls t_pw_present itself
            uc.mem_write(va, b)
    for va, b in stubs.items():
        uc.mem_write(va, b)
    w = lambda a, v: uc.mem_write(a, struct.pack("<i", v))
    w(0x668740, g)
    w(AN.PW, VBASE)
    w(VBASE + 4, WOFF)
    w(WIN, VT)
    w(VT + 0xFC, PRESENT)
    for i, v in enumerate((0, 0, dw, dh, 0, 0, dw, dh)):        # clip, bounds
        w(BUF + 0x20 + 4 * i, v)
    w(BUF + 0x54, data)
    w(BUF + 0x80, dw)
    w(BUF + 0x84, -dh)
    w(BUF + 0x4A8, STRIDE)
    uc.mem_write(DATA, bytes([0xEE]) * (STRIDE * 1100))
    w(HALT, 0)
    return uc


def run(uc, entry, ecx, args=()):
    sp = STACK
    for a in reversed(args):
        sp -= 4
        uc.mem_write(sp, struct.pack("<I", a))
    sp -= 4
    uc.mem_write(sp, struct.pack("<I", HALT))
    regs = {UC_X86_REG_ESP: sp, UC_X86_REG_ECX: ecx, UC_X86_REG_EBX: 0xB0B, UC_X86_REG_ESI: 0x5151,
            UC_X86_REG_EDI: 0xD1D1, UC_X86_REG_EBP: 0xEBEB}
    for r, v in regs.items():
        uc.reg_write(r, v)
    hit = []
    h = uc.hook_add(UC_HOOK_CODE, lambda u, a, s, _: (hit.append(a), u.emu_stop()) if a == HALT else None)
    try:
        uc.emu_start(entry, 0, count=60_000_000)
    finally:
        uc.hook_del(h)
    assert hit == [HALT]
    assert uc.reg_read(UC_X86_REG_ESP) == STACK
    assert (uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI),
            uc.reg_read(UC_X86_REG_EBP)) == (0xB0B, 0x5151, 0xD1D1, 0xEBEB)


def r32(uc, a):
    return struct.unpack("<i", uc.mem_read(a, 4))[0]


def seen(uc):
    n = r32(uc, LOG)
    return [(r32(uc, LOG + 4 + 8 * i), -r32(uc, LOG + 8 + 8 * i)) for i in range(n)]


def fields(uc):
    return [r32(uc, BUF + 0x20 + 4 * i) for i in range(8)] + [r32(uc, BUF + 0x80), r32(uc, BUF + 0x84)]


def state(uc):
    return [r32(uc, a) for a in (AN.DEPTH, AN.ON, AN.DIRTY)]


def pattern(nw, nh):
    return [[(x * 7 + y * 13) & 0xFF for x in range(nw)] for y in range(nh)]


def canvas(uc, base, dw, dh):
    raw = bytes(uc.mem_read(base, STRIDE * dh))
    return [list(raw[y * STRIDE:y * STRIDE + dw]) for y in range(dh)]


GS = [17, 18, 20, 22, 24, 25, 28, 32, 36, 40]


@pytest.mark.parametrize("g", GS)
def test_fit_two_nests_render_at_native_and_enlarges_once(g):
    dw, dh = dev_dims(g)
    uc = make(g, dw, dh)
    before = fields(uc)
    run(uc, 0x48B630, AN.PW, (11, 22, 33, 44, 55))
    nw, nh = SL.planwin_native_dims(dw, dh, g)
    assert (nw, nh) == (239, 119)
    assert seen(uc) == [(nw, nh), (nw, nh)]                     # fit_two's own view and the nested render's
    assert [r32(uc, ARGS + 4 * i) for i in range(5)] == [11, 22, 33, 44, 1]   # v2: force (arg 5) set at g > 16
    assert fields(uc) == before and state(uc) == [0, 0, 0]
    assert canvas(uc, DATA, dw, dh) == SL.planwin_enlarge(pattern(nw, nh), dw, dh)


@pytest.mark.parametrize("g", GS)
def test_overlay_presents_the_enlarged_image_at_device_dims(g):
    dw, dh = dev_dims(g)
    uc = make(g, dw, dh)
    before = fields(uc)
    run(uc, 0x48AF30, AN.PW + 0x22050)
    assert seen(uc) == [(239, 119)]
    assert (r32(uc, CAPWH), -r32(uc, CAPWH + 4)) == (dw, dh)    # the present sees the device canvas
    assert canvas(uc, CAP, dw, dh) == SL.planwin_enlarge(pattern(239, 119), dw, dh)
    assert fields(uc) == before and state(uc) == [0, 0, 0]


@pytest.mark.parametrize("g", [22, 25, 40])
@pytest.mark.parametrize("entry,args", [(0x48B3F0, ()), (0x48B8E0, (7, 8, 9))])
def test_render_and_fit_one_leave_the_enlarged_map(g, entry, args):
    dw, dh = dev_dims(g)
    uc = make(g, dw, dh)
    before = fields(uc)
    run(uc, entry, AN.PW, args)
    assert seen(uc) == [(239, 119)]
    assert canvas(uc, DATA, dw, dh) == SL.planwin_enlarge(pattern(239, 119), dw, dh)
    assert fields(uc) == before and state(uc) == [0, 0, 0]
    if args:
        assert [r32(uc, ARGS + 4 * i) for i in range(3)] == list(args[:2]) + [1]   # v2: force (arg 3) set at g > 16


@pytest.mark.parametrize("g", GS)
@pytest.mark.parametrize("entry,args", [(0x48B630, (11, 22, 33, 44, 0)), (0x48B8E0, (7, 8, 0))])
@pytest.mark.parametrize("stale", ["enlarged", "black"])
def test_a_fit_always_draws_a_fresh_native_image(g, entry, args, stale):
    """Audit 2026-10-15. Vanilla skips a fit's draw when zoom + centre come out unchanged (force 0): v1 then still
    marked the corner dirty and t_pw_exit enlarged the ALREADY-enlarged canvas (a zoom of a zoom), and a save Buffer
    re-made black after a display-mode change stayed black under the markers (the 1080 "no terrain" shot).  v2 sets
    the fit's own force argument: the canvas is always the fresh enlargement of vanilla's native image."""
    dw, dh = dev_dims(g)
    uc = make(g, dw, dh, stubs=STUBS_COND)
    if stale == "enlarged":
        old = SL.planwin_enlarge([[(x * 3 + y * 5 + 1) & 0xFF for x in range(239)] for y in range(119)], dw, dh)
    else:
        old = [[0] * dw for _ in range(dh)]
    for y, row in enumerate(old):
        uc.mem_write(DATA + y * STRIDE, bytes(row))
    before = fields(uc)
    run(uc, entry, AN.PW, args)
    assert canvas(uc, DATA, dw, dh) == SL.planwin_enlarge(pattern(239, 119), dw, dh)
    assert fields(uc) == before and state(uc) == [0, 0, 0]


@pytest.mark.parametrize("g", [8, 12, 16])
@pytest.mark.parametrize("entry,args,n", [(0x48B630, (11, 22, 33, 44, 0), 5), (0x48B8E0, (7, 8, 0), 3)])
def test_native_fits_keep_the_engines_force_argument(g, entry, args, n):
    """g <= 16: the fit wrappers pass every argument through untouched (vanilla's skip stays vanilla's)."""
    uc = make(g, 239, 119, stubs=STUBS_COND)
    run(uc, entry, AN.PW, args)
    assert [r32(uc, ARGS + 4 * i) for i in range(n)] == list(args)


@pytest.mark.parametrize("g", [8, 12, 16])
def test_native_resolutions_pass_through(g):
    dw, dh = 239, 119
    uc = make(g, dw, dh)
    before = fields(uc)
    run(uc, 0x48B630, AN.PW, (1, 2, 3, 4, 5))
    run(uc, 0x48AF30, AN.PW + 0x22050)
    assert seen(uc) == [(dw, dh)] * 3
    assert canvas(uc, DATA, dw, dh) == pattern(dw, dh)
    assert fields(uc) == before and state(uc) == [0, 0, 0]


@pytest.mark.parametrize("dw,dh", [(200, 297), (597, 100), (2000, 297), (12, 12)])
def test_unusable_canvas_passes_through(dw, dh):
    uc = make(40, dw, dh)
    before = fields(uc)
    run(uc, 0x48B630, AN.PW, (1, 2, 3, 4, 5))
    run(uc, 0x48AF30, AN.PW + 0x22050)
    assert seen(uc) == [(dw, dh)] * 3
    assert fields(uc) == before and state(uc) == [0, 0, 0]


def test_null_data_skips_the_enlarge():
    """The enlarge alone on a canvas with no pixel data: no fault, and DIRTY stays set (nothing was enlarged); the
    outermost unshrink clears it."""
    uc = make(40, 597, 297, data=0)
    uc.mem_write(AN.DEPTH, struct.pack("<iii", 1, 1, 1))
    uc.mem_write(AN.SV, struct.pack("<10i", 0, 0, 597, 297, 0, 0, 597, 297, 597, -297))
    run(uc, SYMTAB["t_pw_enlarge"], 0)
    assert r32(uc, AN.DIRTY) == 1                               # nothing done, nothing claimed


def test_law_native_dims_and_enlarge_shape():
    assert SL.planwin_native_dims(597, 297, 40) == (239, 119)
    assert SL.planwin_native_dims(373, 185, 25) == (239, 119)
    assert SL.planwin_native_dims(239, 119, 16) == (239, 119)
    assert SL.planwin_native_dims(100, 50, 40) == (100, 50)
    img = SL.planwin_enlarge(pattern(239, 119), 597, 297)
    assert len(img) == 297 and len(img[0]) == 597
    assert img[0][0] == 0 and img[-1][-1] == pattern(239, 119)[-1][-1]


def test_yaml_is_the_assembler_output_and_the_sites_point_at_it():
    lay = AN.layout()
    addr = {n: AN.PCAVE2 + o for n, (o, _b) in lay.items()}
    for name, (o, b) in lay.items():
        assert CODE[name] == (o, b), name
        assert SYMTAB[name] == AN.PCAVE2 + o
    by_id = {s["id"]: s for s in SITE_LIST}
    for sid, (va, orig, kind, n) in AN.SITES.items():
        s = by_id[sid]
        assert int(str(s["virtual_addr"]), 0) == va and int(s["length"]) == n
        assert bytes.fromhex(s["original_bytes"].split("#")[0]) == bytes.fromhex(orig)
        assert SITE[sid][1] == AN.site_bytes(va, kind, n, addr), sid
    assert SYMTAB["g_pw_state"] == AN.PCAVE2 + AN.DATA_OFF


def test_the_old_panel_levers_are_gone():
    """The panel matches vanilla now: its route line is the engine's 1-px dashed line (enlarged with the map) and
    PlanWin_open's zoom is the engine's -14; t_pw_line stays for the MAIN map's dashed order lines."""
    ids = {s["id"] for s in SITE_LIST}
    assert "PlanWin_overlay_draw.route_line" not in ids and "PlanWin_open.zoom_init" not in ids
    assert "t_pw_zinit" not in CONTENTS and "t_pw_zinit" not in SYMTAB
    assert "MapWin_direct_dest_line.dash_line" in ids and "t_pw_line" in CONTENTS


def test_the_original_entry_bytes_are_relocated_exactly():
    """Each trampoline replays the displaced prologue and returns to the next original instruction."""
    import config
    import pefile
    pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)
    rd = lambda va, n: pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)
    for sid, (va, orig, _k, n) in AN.SITES.items():
        assert rd(va, n) == bytes.fromhex(orig), sid
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    dis = lambda b, va: [(i.mnemonic, i.op_str) for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)]
    for name, back, va in (("t_pw_render", 0x48B3F5, 0x48B3F0), ("t_pw_overlay", 0x48AF36, 0x48AF30),
                           ("t_pw_fit2", 0x48B636, 0x48B630), ("t_pw_fit1", 0x48B8E6, 0x48B8E0)):
        pro = dis(rd(va, back - va), va)                                  # the displaced original instructions
        o, b = CODE[name]
        tail = dis(b, AN.PCAVE2 + o)[-(len(pro) + 2):]
        assert tail == pro + [("push", hex(back)), ("ret", "")], name
