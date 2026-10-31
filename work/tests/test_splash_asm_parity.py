"""Differential: t_splash_blit (group splash_scale) must implement scaling_laws "STARTUP SPLASH".

The two logo.pcx Buffer_copy_4 calls (Win_init_class 0x5F0482, GraphicsMgr_set_mode 0x635706) are
redirected to t_splash_blit.  Run from each real site with the caller's 7 args pushed:

  * num = splash_scale_num(W, H) <= 16 -> Buffer_copy_4 is entered with ecx = src and the caller's
    stack byte-identical (return address = site + 5, the 7 args untouched);
  * else -> Buffer_sync_to_palette(dest, [g_active_palette]) first, then t_mon_resample with exactly
    (sdata, spitch, sx, sy, sw, sh, dest, dx, dy, dw, dh) = (src+0x54, src+0x4A8, the caller's sx/sy/w/h,
    dest, splash_rect), g_mon_lut_ok == 0 at the resample (the LUT is rebuilt for this palette) and after,
    the LUT search range [g_mon_lut_lo, g_mon_lut_hi) == [SPLASH_PAL_LO, SPLASH_PAL_HI) at the resample
    (the logo's own entries) and back to the default [0, 256) after (t_splash_lut_on / t_splash_lut_off),
    eax = 0, RET 0x1C, ebx/esi/edi/ebp preserved.

The callees are stubbed (ret n) and observed through UC_HOOK_CODE.  Bytes come from patches.yaml
resolved with the real symbol table; the assembler script must reproduce them exactly.  The resampler
itself is covered by test_mon_asm_parity.py.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent - asm parity unverified")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

SITES = {"Win_init_class.splash_blit": 0x5F0482, "GraphicsMgr_set_mode.splash_blit": 0x635706}
COPY4, SYNC = 0x5DFF00, 0x5DE8F0
ACTIVE_PAL = 0x9B8180
PAL_OBJ = 0x9B9000
SCREEN = 0x9B7490                    # g_screen_buffer (the real dest)
SRC = 0x00300000                     # the local logo Buffer
STACK = 0x00200000


def _int(v):
    return int(v, 16) if isinstance(v, str) else v


def _load():
    doc = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
    symtab = dict(ap.build_symbol_table(doc["symbols"], doc["code_caves"]))
    thunk = None
    helpers = {}
    for cave in doc["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] in ("t_splash_blit", "t_splash_lut_on", "t_splash_lut_off"):
                va = _int(cave["virtual_addr"]) + _int(c["offset"])
                code = ap.ByteTemplate(c["bytes"]).resolve(va, symtab)
                if c["id"] == "t_splash_blit":
                    thunk = (va, code)
                else:
                    helpers[c["id"]] = (va, code)
    assert thunk, "t_splash_blit content entry not found"
    assert set(helpers) == {"t_splash_lut_on", "t_splash_lut_off"}
    sites = {}
    for s in doc["sites"]:
        if s["id"] in SITES:
            va = _int(s["virtual_addr"])
            assert va == SITES[s["id"]] and s["group"] == "splash_scale"
            sites[s["id"]] = ap.ByteTemplate(s["new_bytes"]).resolve(va, symtab)
    assert set(sites) == set(SITES)
    return (thunk[0], thunk[1], sites, symtab["t_mon_resample"], symtab["g_mon_lut_ok"], helpers,
            symtab["g_mon_lut_lo"], symtab["g_mon_lut_hi"])


THUNK_VA, THUNK_CODE, SITE_CODE, RESAMPLE, LUT_OK, HELPERS, LUT_LO, LUT_HI = _load()


def _run(site_id, W, H, sw=800, sh=600, sx=0, sy=0, lut_ok=1):
    site = SITES[site_id]
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((THUNK_VA & ~0xFFF, 0x2000), (site & ~0xFFF, 0x1000), (COPY4 & ~0xFFF, 0x1000),
                       (SYNC & ~0xFFF, 0x1000), (RESAMPLE & ~0xFFF, 0x1000), (LUT_OK & ~0xFFF, 0x1000),
                       (LUT_LO & ~0xFFF, 0x1000), (HELPERS["t_splash_lut_on"][0] & ~0xFFF, 0x1000),
                       (SCREEN & ~0xFFF, 0x3000), (SRC, 0x1000), (STACK, 0x10000)):
        try:
            uc.mem_map(base, size)
        except unicorn.UcError:
            pass                                       # overlapping pages already mapped
    uc.mem_write(THUNK_VA, THUNK_CODE)
    uc.mem_write(site, SITE_CODE[site_id])
    uc.mem_write(site + 5, b"\xF4")
    uc.mem_write(COPY4, b"\xC2\x1C\x00")
    uc.mem_write(SYNC, b"\xC2\x04\x00")
    uc.mem_write(RESAMPLE, b"\xC2\x2C\x00")
    for va, code in HELPERS.values():
        uc.mem_write(va, code)
    uc.mem_write(LUT_OK, struct.pack("<i", lut_ok))
    uc.mem_write(LUT_LO, struct.pack("<ii", 0, 256))
    uc.mem_write(ACTIVE_PAL, struct.pack("<I", PAL_OBJ))
    uc.mem_write(SCREEN + 0x80, struct.pack("<ii", W, -H))
    uc.mem_write(SCREEN + 0x54, struct.pack("<I", 0x12340000))
    uc.mem_write(SRC + 0x80, struct.pack("<ii", sw, -sh))
    uc.mem_write(SRC + 0x54, struct.pack("<I", 0x05550000))
    uc.mem_write(SRC + 0x4A8, struct.pack("<i", sw))
    # the caller's pushes (vanilla order): h, w, dy, dx, sy, sx, dest
    nx, ny = SL._trunc_half(W - sw), SL._trunc_half(H - sh)
    args = [SCREEN, sx, sy, nx, ny, sw, sh]
    esp0 = STACK + 0x8000
    esp = esp0 - 4 * len(args)
    uc.mem_write(esp, struct.pack("<7i", *args))
    regs = {UC_X86_REG_ESP: esp, UC_X86_REG_ECX: SRC, UC_X86_REG_EBX: 0xB0B0B0B0, UC_X86_REG_ESI: 0x51515151,
            UC_X86_REG_EDI: 0xD1D1D1D1, UC_X86_REG_EBP: 0xEBEBEBEB, UC_X86_REG_EAX: 0xDEAD}
    for r, v in regs.items():
        uc.reg_write(r, v)
    seen = {}

    def hook(u, addr, _size, _ud):
        sp = u.reg_read(UC_X86_REG_ESP)
        if addr == COPY4:
            seen["copy4"] = (u.reg_read(UC_X86_REG_ECX), struct.unpack("<8I", u.mem_read(sp, 32)))
        elif addr == SYNC:
            seen["sync"] = (u.reg_read(UC_X86_REG_ECX), struct.unpack("<I", u.mem_read(sp + 4, 4))[0])
        elif addr == RESAMPLE:
            seen["resample"] = struct.unpack("<11i", u.mem_read(sp + 4, 44))
            seen["lut_at_resample"] = struct.unpack("<i", u.mem_read(LUT_OK, 4))[0]
            seen["range_at_resample"] = struct.unpack("<ii", u.mem_read(LUT_LO, 8))
            seen["order"] = "sync" in seen

    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(site, site + 5, count=400)
    assert uc.reg_read(UC_X86_REG_EIP) == site + 5
    assert uc.reg_read(UC_X86_REG_ESP) == esp0           # callee-cleanup RET 0x1C
    for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
        assert uc.reg_read(r) == regs[r]
    seen["eax"] = uc.reg_read(UC_X86_REG_EAX)
    seen["lut_after"] = struct.unpack("<i", uc.mem_read(LUT_OK, 4))[0]
    seen["range_after"] = struct.unpack("<ii", uc.mem_read(LUT_LO, 8))
    seen["args"] = args
    return seen


RES = [(3840, 2160), (2560, 1440), (1600, 1200), (1920, 1080), (1280, 1024), (1366, 768), (1024, 768),
       (800, 600), (1280, 720), (1440, 900), (1680, 1050), (2560, 1080), (3440, 1440), (7680, 4320),
       (5120, 2880), (1152, 864), (1024, 1280), (1088, 816), (1104, 828)]


@pytest.mark.parametrize("site_id", list(SITES))
@pytest.mark.parametrize("W,H", RES)
def test_thunk_matches_law(site_id, W, H):
    s = _run(site_id, W, H)
    if not SL.splash_armed(W, H):
        assert "resample" not in s and "sync" not in s
        assert s["range_after"] == (0, 256) and s["lut_after"] == 1                  # nothing touched
        ecx, stack = s["copy4"]
        assert ecx == SRC
        assert stack[0] == SITES[site_id] + 5                         # returns straight to the caller
        assert [struct.unpack("<i", struct.pack("<I", v))[0] for v in stack[1:]] == s["args"]
        x, y, w, h = SL.splash_rect(W, H, 800, 600)
        assert (s["args"][3], s["args"][4], s["args"][5], s["args"][6]) == (x, y, w, h)
        return
    assert "copy4" not in s
    assert s["sync"] == (SCREEN, PAL_OBJ) and s["order"]
    x, y, w, h = SL.splash_rect(W, H, 800, 600)
    assert s["resample"] == (0x05550000, 800, 0, 0, 800, 600, SCREEN, x, y, w, h)
    assert s["lut_at_resample"] == 0 and s["lut_after"] == 0
    assert s["range_at_resample"] == (SL.SPLASH_PAL_LO, SL.SPLASH_PAL_HI) == (10, 246)
    assert s["range_after"] == (0, 256)
    assert s["eax"] == 0


@pytest.mark.parametrize("sw,sh,sx,sy", [(640, 480, 0, 0), (1024, 768, 0, 0), (800, 600, 3, 5), (17, 9, 0, 0)])
def test_other_source_sizes_follow_the_law(sw, sh, sx, sy):
    """A replaced logo.pcx of any size: the caller's own w/h/sx/sy go through, scaled by the same num."""
    s = _run("Win_init_class.splash_blit", 3840, 2160, sw=sw, sh=sh, sx=sx, sy=sy)
    x, y, w, h = SL.splash_rect(3840, 2160, sw, sh)
    assert s["resample"] == (0x05550000, sw, sx, sy, sw, sh, SCREEN, x, y, w, h)


def test_degenerate_screen_is_the_native_blit():
    s = _run("GraphicsMgr_set_mode.splash_blit", 0, 0)
    assert "copy4" in s and "resample" not in s


def test_assembler_matches_yaml():
    import assemble_splash as asp
    assert asp.VA == THUNK_VA
    assert asp.assemble() == THUNK_CODE
    assert asp.T_MON_RESAMPLE == RESAMPLE and asp.G_MON_LUT_OK == LUT_OK
    assert (asp.G_MON_LUT_LO, asp.G_MON_LUT_HI) == (LUT_LO, LUT_HI) and LUT_HI == LUT_LO + 4
    for name, (va, code) in asp.assemble_helpers().items():
        assert HELPERS[name] == (va, code), name
    for sid, _fn, va in asp.SITES:
        assert SITE_CODE[sid] == b"\xE8" + struct.pack("<i", THUNK_VA - (va + 5))
