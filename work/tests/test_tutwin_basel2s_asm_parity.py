"""Differential: the BAKED thunk_tutwin_basel2s must agree with the Python law.

`scaling_laws.py::tutwin_base_pointer_pt` (= basewin_pt) is the source of
truth; the shipped x86 (scripts/assemble_tutwin_basel2s.py TEMPLATE, resolved
the way apply_patches resolves it) is emulated under Unicorn with a stand-in
GraphicWin_local_to_screen that records its `this`, adds an origin to both
pointed ints and TRASHES eax/ecx/edx.

Per g in [16,40] x a sweep of native centres (incl. negative clip sentinels):
  * ecx == BaseWin_g: *x/*y == origin + law(centre) on return; the helper ran
    once with the SAME this; the caller's return address was honoured and the
    two args were consumed (RET 8) -- esp == entry esp + 12
  * ecx != BaseWin_g: byte-neutral -- the helper sees the UNSCALED ints
  * g <= 16: identity even for BaseWin_g
  * yaml carries THIS template at THIS slot, and every one of the 19 sites is
    a call_target_redirect whose original bytes are the pristine E8 to
    local_to_screen

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

from scaling_laws import NATIVE_G, tutwin_base_pointer_pt  # noqa: E402
import assemble_tutwin_basel2s as ASM  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP  # noqa: E402

PAGE = 0x1000
CODE = ASM.PCAVE2_VA + ASM.SLOT_OFFSET          # 0xA0C5E0
G_ADDR = 0xDEADBE00
L2S = ASM.L2S                                    # 0x5ED240 (real VA)
CELL_ECX, CELL_COUNT, CELL_OX, CELL_OY = 0xDEADBE10, 0xDEADBE14, 0xDEADBE18, 0xDEADBE1C
STACK = 0x00200000
RETADDR = 0x004BADBD                             # the byte after tour6's first E8
BASEWIN_G = ASM.BASEWIN_G
OTHER_WIN = 0x007AE820                           # MainWin_g: must pass through untouched

CENTRE_SWEEP = (0, 7, 17, 100, 363, 394, 428, 700, 757, -3, -40)


def _blob() -> bytes:
    return ASM.resolve(ASM.TEMPLATE, CODE, {"g_popup_scale_num": G_ADDR,
                                            "GraphicWin_local_to_screen": L2S})


def _l2s_stub() -> bytes:
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    src = f"""
        mov  [{CELL_ECX:#x}], ecx
        inc  dword ptr [{CELL_COUNT:#x}]
        mov  eax, [esp+4]
        mov  ecx, [{CELL_OX:#x}]
        add  [eax], ecx
        mov  eax, [esp+8]
        mov  ecx, [{CELL_OY:#x}]
        add  [eax], ecx
        mov  eax, 0x11111111
        mov  ecx, 0x22222222
        mov  edx, 0x33333333
        ret  8
    """
    code, _ = ks.asm(src, addr=L2S)
    return bytes(code)


@pytest.fixture(scope="module")
def uc():
    blob = _blob()
    assert len(blob) == 60
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in (
        (CODE & ~(PAGE - 1), PAGE),
        (G_ADDR & ~(PAGE - 1), PAGE),
        (L2S & ~(PAGE - 1), PAGE),
        (RETADDR & ~(PAGE - 1), PAGE),
        (STACK, PAGE),
    ):
        mu.mem_map(base, size)
    mu.mem_write(CODE, blob)
    mu.mem_write(L2S, _l2s_stub())              # written ONCE (TB cache)
    return mu


def _run(mu, g: int, cx: int, cy: int, this: int, origin=(1012, 403)):
    mu.mem_write(G_ADDR, int(g).to_bytes(4, "little", signed=True))
    mu.mem_write(CELL_ECX, b"\0\0\0\0")
    mu.mem_write(CELL_COUNT, b"\0\0\0\0")
    mu.mem_write(CELL_OX, int(origin[0]).to_bytes(4, "little", signed=True))
    mu.mem_write(CELL_OY, int(origin[1]).to_bytes(4, "little", signed=True))
    xs = STACK + PAGE - 0x10                    # the caller's two stack ints
    ys = STACK + PAGE - 0x0C
    mu.mem_write(xs, int(cx).to_bytes(4, "little", signed=True))
    mu.mem_write(ys, int(cy).to_bytes(4, "little", signed=True))
    sp = STACK + PAGE - 0x40
    mu.mem_write(sp + 8, ys.to_bytes(4, "little"))   # push y*
    mu.mem_write(sp + 4, xs.to_bytes(4, "little"))   # push x*
    mu.mem_write(sp, RETADDR.to_bytes(4, "little"))  # the site's E8
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ECX, this)
    mu.emu_start(CODE, RETADDR, count=200)
    x = int.from_bytes(mu.mem_read(xs, 4), "little", signed=True)
    y = int.from_bytes(mu.mem_read(ys, 4), "little", signed=True)
    return dict(
        eip=mu.reg_read(UC_X86_REG_EIP), esp=mu.reg_read(UC_X86_REG_ESP), sp0=sp,
        x=x, y=y,
        calls=int.from_bytes(mu.mem_read(CELL_COUNT, 4), "little"),
        ecx_seen=int.from_bytes(mu.mem_read(CELL_ECX, 4), "little"),
    )


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("cx", CENTRE_SWEEP)
def test_asm_matches_the_reference_for_basewin(uc, g: int, cx: int):
    cy = (cx * 7) % 491 - 3
    r = _run(uc, g, cx, cy, BASEWIN_G)
    assert r["eip"] == RETADDR
    assert r["esp"] == r["sp0"] + 12, "ret addr + the two args must be consumed (RET 8)"
    assert r["calls"] == 1 and r["ecx_seen"] == BASEWIN_G
    assert r["x"] == 1012 + tutwin_base_pointer_pt(cx, g), (g, cx)
    assert r["y"] == 403 + tutwin_base_pointer_pt(cy, g), (g, cy)
    if g <= NATIVE_G:
        assert (r["x"], r["y"]) == (1012 + cx, 403 + cy)


@pytest.mark.parametrize("g", (16, 22, 25, 40))
@pytest.mark.parametrize("cx", CENTRE_SWEEP)
def test_asm_is_byte_neutral_for_other_windows(uc, g: int, cx: int):
    r = _run(uc, g, cx, 100, OTHER_WIN, origin=(640, 1628))
    assert r["calls"] == 1 and r["ecx_seen"] == OTHER_WIN
    assert (r["x"], r["y"]) == (640 + cx, 1628 + 100)
    assert r["esp"] == r["sp0"] + 12


def test_asm_pins_the_psych_step_at_4k(uc):
    """Shot 20260917-234627: BaseWin origin (1012,403), psych rect centre
    (428,394) native -> the line must end at (2082,1388), the PSYCH row,
    not at (1440,797) in the map view."""
    r = _run(uc, 40, 428, 394, BASEWIN_G)
    assert (r["x"], r["y"]) == (2082, 1388)


def test_yaml_carries_the_template_and_all_19_sites():
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r"thunk_tutwin_basel2s:\s*\{ cave: pcave2, offset: (0x[0-9A-Fa-f]+) \}", text)
    assert m and int(m.group(1), 16) == ASM.SLOT_OFFSET, "ledger slot != assembler slot"
    m = re.search(r"- id: thunk_tutwin_basel2s\s+offset: (0x[0-9A-Fa-f]+)\s+bytes: \"([^\"]+)\"", text)
    assert m and int(m.group(1), 16) == ASM.SLOT_OFFSET
    assert m.group(2).split() == ASM.TEMPLATE.split(), "yaml bytes != assembler template"
    for va in ASM.SITES:
        pat = (r"virtual_addr: 0x%08X\s+length: 5\s+original_bytes: \"%s\"[^\r\n]*\s+new_bytes:\s+"
               r"\"E8 \{rel32:thunk_tutwin_basel2s\}\"" % (va, ASM.site_original_bytes(va)))
        assert re.search(pat, text), f"site {va:#x} missing or wrong in patches.yaml"
