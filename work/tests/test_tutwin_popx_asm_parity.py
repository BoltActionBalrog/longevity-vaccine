"""Differential: the BAKED thunk_tutwin_popx must agree with the Python law.

`scaling_laws.py::tutwin_pop_pointer_x` is the source of truth; the x86 that
ships (scripts/assemble_tutwin_popx.py TEMPLATE_ENTRY, resolved exactly the
way apply_patches resolves it) is emulated under Unicorn with a stand-in
GraphicWin_local_to_screen that adds a MainWin origin and TRASHES eax/ecx/edx
(caller-saved -- the thunk must not rely on them across the call).

Per g in [16,40] x a sweep of rect.left x MainWin origins:
  * the two re-issued pushes sit exactly where vanilla's `push ecx; push edx`
    left them (the site's E8 pushed the return address at entry_esp; it is
    consumed, so esp == entry_esp + 4 - 8)
  * [esp] == law x, [esp+4] == the untouched centre y
  * eax (the anchor Win*, pushed by the very next site insn) and ebx (TutWin
    this) survive; resume lands on the site's next instruction
  * g <= 16: the engine helper is NOT called and x == left + 5 (the displaced
    vanilla instruction, no origin term)
  * g > 16: the helper is called ONCE with ecx == MainWin_g (0x7AE820)

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import NATIVE_G, tutwin_pop_pointer_x  # noqa: E402
import assemble_tutwin_popx as ASM  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESP,
)

PAGE = 0x1000
CODE = ASM.PCAVE2_VA + ASM.SLOT_OFFSET          # 0xA10240
RET_CELL = ASM.PCAVE2_VA + ASM.RET_CELL_OFFSET  # 0xA10290
G_ADDR = 0xDEADBE00                             # g_popup_scale_num stand-in
L2S = 0x005ED240                                # GraphicWin_local_to_screen (real VA)
L2S_ECX_CELL = 0xDEADBE10                       # the stub records its `this`
L2S_COUNT_CELL = 0xDEADBE14                     # ... and how often it ran
L2S_X_CELL = 0xDEADBE18                         # the stand-in origin the stub adds
L2S_Y_CELL = 0xDEADBE1C
STACK = 0x00200000
RETADDR = 0x004BAB60                            # site 1's next insn (push label)
ANCHOR = 0x00939284
THIS = 0x008C6E68
MAINWIN_G = 0x007AE820

LEFT_SWEEP = (0, 5, 100, 267, 289, 667, 668, 1023, 1750)
ORIGIN_SWEEP = ((0, 0), (128, 768), (640, 1628), (288, 1140), (5, 7))


def _blob() -> bytes:
    return ASM.resolve(ASM.TEMPLATE_ENTRY, CODE, {
        "g_popup_scale_num": G_ADDR,
        "g_tw_ret": RET_CELL,
        "GraphicWin_local_to_screen": L2S,
    })


def _l2s_stub() -> bytes:
    """thiscall(this, int* x, int* y) RET 8: *x += [X_CELL], *y += [Y_CELL];
    trash eax/ecx/edx. The origins live in DATA cells so the stub's code is
    written once (Unicorn caches translated blocks; rewriting executed code
    per case served stale stubs -- memory feedback-unicorn-stub-overlap)."""
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    src = f"""
        mov  [{L2S_ECX_CELL:#x}], ecx
        inc  dword ptr [{L2S_COUNT_CELL:#x}]
        mov  eax, [esp+4]
        mov  ecx, [{L2S_X_CELL:#x}]
        add  [eax], ecx
        mov  eax, [esp+8]
        mov  ecx, [{L2S_Y_CELL:#x}]
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
    assert len(blob) == 68
    assert ASM.SLOT_OFFSET + len(blob) <= ASM.RET_CELL_OFFSET
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in (
        (CODE & ~(PAGE - 1), PAGE),            # thunk + g_tw_ret cell
        (G_ADDR & ~(PAGE - 1), PAGE),          # g + stub cells
        (L2S & ~(PAGE - 1), PAGE),             # the stand-in engine helper
        (RETADDR & ~(PAGE - 1), PAGE),         # resume target (never executed)
        (STACK, PAGE),
    ):
        mu.mem_map(base, size)
    mu.mem_write(CODE, blob)
    mu.mem_write(L2S, _l2s_stub())          # written ONCE
    return mu


def _run(mu, g: int, left: int, origin: tuple[int, int], y: int = 1862):
    mu.mem_write(L2S_X_CELL, int(origin[0]).to_bytes(4, "little", signed=True))
    mu.mem_write(L2S_Y_CELL, int(origin[1]).to_bytes(4, "little", signed=True))
    mu.mem_write(G_ADDR, int(g).to_bytes(4, "little", signed=True))
    mu.mem_write(L2S_ECX_CELL, b"\0\0\0\0")
    mu.mem_write(L2S_COUNT_CELL, b"\0\0\0\0")
    mu.mem_write(RET_CELL, b"\xEE\xEE\xEE\xEE")

    sp = STACK + PAGE - 0x40
    mu.mem_write(sp, RETADDR.to_bytes(4, "little"))   # the site's E8 pushed this
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EAX, ANCHOR)
    mu.reg_write(UC_X86_REG_ECX, y)
    mu.reg_write(UC_X86_REG_EDX, left)
    mu.reg_write(UC_X86_REG_EBX, THIS)

    mu.emu_start(CODE, RETADDR, count=200)

    esp = mu.reg_read(UC_X86_REG_ESP)
    top = int.from_bytes(mu.mem_read(esp, 4), "little", signed=True)
    second = int.from_bytes(mu.mem_read(esp + 4, 4), "little", signed=True)
    calls = int.from_bytes(mu.mem_read(L2S_COUNT_CELL, 4), "little")
    ecx_seen = int.from_bytes(mu.mem_read(L2S_ECX_CELL, 4), "little")
    return dict(
        eip=mu.reg_read(UC_X86_REG_EIP), esp=esp, sp0=sp,
        x=top, y=second, calls=calls, ecx_seen=ecx_seen,
        eax=mu.reg_read(UC_X86_REG_EAX), ebx=mu.reg_read(UC_X86_REG_EBX),
    )


@pytest.mark.parametrize("g", range(NATIVE_G, 41))
@pytest.mark.parametrize("left", LEFT_SWEEP)
@pytest.mark.parametrize("origin", ORIGIN_SWEEP)
def test_asm_matches_the_reference(uc, g: int, left: int, origin):
    r = _run(uc, g, left, origin)
    assert r["eip"] == RETADDR, "did not resume at the site's next instruction"
    assert r["esp"] == r["sp0"] + 4 - 8, "stack shape != vanilla's two pushes (ret consumed)"
    assert r["eax"] == ANCHOR, "eax (anchor Win*, pushed by the next site insn) clobbered"
    assert r["ebx"] == THIS, "ebx (TutWin this) clobbered"
    assert r["y"] == 1862, "the converted centre y must pass through untouched"
    want = tutwin_pop_pointer_x(left, origin[0], g)
    assert r["x"] == want, f"g={g} left={left} origin={origin}: asm {r['x']} != law {want}"
    if g <= NATIVE_G:
        assert r["calls"] == 0, "g<=16 must be the displaced vanilla insn (no engine call)"
        assert r["x"] == left + 5
    else:
        assert r["calls"] == 1
        assert r["ecx_seen"] == MAINWIN_G, "local_to_screen must be asked about MainWin_g"


@pytest.mark.parametrize("g,inset", ((22, 6), (25, 7), (40, 12)))
def test_asm_pins_the_shipped_resolutions(uc, g: int, inset: int):
    """The 4K repro: left 667 (267 native x 2.5), strip at x=640 -> 640+667+12 = 1319,
    i.e. on the drone citizen's portrait instead of the console rail at 672."""
    r = _run(uc, g, 667, (640, 1628))
    assert r["x"] == 640 + 667 + inset
    if g == 40:
        assert r["x"] == 1319


def test_yaml_ledger_and_content_agree_with_the_assembler():
    """The yaml must carry THIS template at THIS slot (no content/ledger desync)."""
    import re
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r"thunk_tutwin_popx:\s*\{ cave: pcave2, offset: (0x[0-9A-Fa-f]+) \}", text)
    assert m and int(m.group(1), 16) == ASM.SLOT_OFFSET, "ledger slot != assembler slot"
    m = re.search(r"g_tw_ret:\s*\{ cave: pcave2, offset: (0x[0-9A-Fa-f]+) \}", text)
    assert m and int(m.group(1), 16) == ASM.RET_CELL_OFFSET, "g_tw_ret slot != assembler slot"
    m = re.search(r"- id: thunk_tutwin_popx\s+offset: (0x[0-9A-Fa-f]+)\s+bytes: \"([^\"]+)\"", text)
    assert m, "no cave content entry for thunk_tutwin_popx"
    assert int(m.group(1), 16) == ASM.SLOT_OFFSET
    assert m.group(2).split() == ASM.TEMPLATE_ENTRY.split(), "yaml bytes != assembler template"
