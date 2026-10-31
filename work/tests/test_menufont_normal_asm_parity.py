"""Differential: the BAKED thunk_popnorm_menufont must agree with the Python law.

`scaling_laws.py::menu_font_request` is the source of truth; the x86 that ships
(scripts/assemble_menufont_normal.py TEMPLATE, resolved exactly the way
apply_patches resolves it) is emulated under Unicorn with a stand-in find_font
that records its (size, variant) args, returns a Font* derived from them and
TRASHES ecx/edx + the arithmetic flags (cdecl caller-saved).

Per g in [0,48]:
  * g <= 16: find_font is NOT called; [g_menu_font] == the site's ecx (the
    displaced `mov [g_menu_font],ecx`)
  * g  > 16: find_font called ONCE with the law's (size, variant);
    [g_menu_font] == its return; a NULL return falls back to ecx
  * every GPR and EFLAGS survive (CALL-entered helper inside popups_normal's
    live frame), esp == entry + 4 (bare RET consumed the E8 return address)

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

from scaling_laws import NATIVE_G, menu_font_request  # noqa: E402
import assemble_menufont_normal as ASM  # noqa: E402

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

PAGE = 0x1000
CODE = ASM.PCAVE2_VA + ASM.SLOT_OFFSET          # 0xA107B0
G_ADDR = 0xDEADBE00                             # g_popup_scale_num stand-in
MENU_FONT = 0xDEADBE04                          # g_menu_font stand-in
FF_COUNT = 0xDEADBE10
FF_SIZE = 0xDEADBE14
FF_VARIANT = 0xDEADBE18
FF_NULL = 0xDEADBE1C                            # nonzero -> the stub returns NULL
FIND_FONT = 0x005882F0
STACK = 0x00200000
RETADDR = 0x005886C6                            # the site's trailing NOP
NATIVE_FONT = 0x009400E0                        # what popups_normal holds in ecx
FONT_BASE = 0x00940000

REGS = {
    UC_X86_REG_EAX: 0x0A0A0A0A, UC_X86_REG_ECX: NATIVE_FONT, UC_X86_REG_EDX: 0x0D0D0D0D,
    UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_EBP: 0x0E0E0E0E, UC_X86_REG_ESI: 0x05050505,
    UC_X86_REG_EDI: 0x0000000F,
}
FLAGS_IN = 0x00000A97 & ~0x400 | 0x2            # CF PF AF ZF SF OF set, DF clear


def _blob() -> bytes:
    return ASM.resolve(ASM.TEMPLATE, CODE, {
        "g_popup_scale_num": G_ADDR, "g_menu_font": MENU_FONT, "find_font": FIND_FONT,
    })


def _ff_stub() -> bytes:
    """cdecl(size, variant): record args; eax = FONT_BASE + size*4 + variant, or 0 when
    [FF_NULL]; trash ecx/edx/flags. Written ONCE (memory feedback-unicorn-stub-overlap)."""
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    src = f"""
        inc  dword ptr [{FF_COUNT:#x}]
        mov  ecx, [esp+4]
        mov  [{FF_SIZE:#x}], ecx
        mov  edx, [esp+8]
        mov  [{FF_VARIANT:#x}], edx
        lea  eax, [ecx*4+edx+{FONT_BASE:#x}]
        cmp  dword ptr [{FF_NULL:#x}], 0
        je   done
        xor  eax, eax
    done:
        mov  ecx, 0x22222222
        mov  edx, 0x33333333
        cmp  ecx, edx
        ret
    """
    code, _ = ks.asm(src, addr=FIND_FONT)
    return bytes(code)


@pytest.fixture(scope="module")
def uc():
    blob = _blob()
    assert len(blob) == 49
    assert ASM.SLOT_OFFSET + len(blob) <= ASM.SLOT_END
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in (
        (CODE & ~(PAGE - 1), PAGE),
        (G_ADDR & ~(PAGE - 1), PAGE),
        (FIND_FONT & ~(PAGE - 1), PAGE),       # also holds RETADDR (never executed)
        (STACK, PAGE),
    ):
        mu.mem_map(base, size)
    mu.mem_write(CODE, blob)
    mu.mem_write(FIND_FONT, _ff_stub())
    return mu


def _rd(mu, addr: int) -> int:
    return int.from_bytes(mu.mem_read(addr, 4), "little")


def _run(mu, g: int, null: bool = False):
    mu.mem_write(G_ADDR, int(g).to_bytes(4, "little", signed=True))
    mu.mem_write(MENU_FONT, b"\xEE\xEE\xEE\xEE")
    for cell in (FF_COUNT, FF_SIZE, FF_VARIANT):
        mu.mem_write(cell, b"\0\0\0\0")
    mu.mem_write(FF_NULL, (1 if null else 0).to_bytes(4, "little"))
    sp = STACK + PAGE - 0x80
    mu.mem_write(sp, RETADDR.to_bytes(4, "little"))
    mu.reg_write(UC_X86_REG_ESP, sp)
    for r, v in REGS.items():
        mu.reg_write(r, v)
    mu.reg_write(UC_X86_REG_EFLAGS, FLAGS_IN)
    mu.emu_start(CODE, RETADDR, count=200)
    return sp


@pytest.mark.parametrize("null", (False, True))
@pytest.mark.parametrize("g", range(0, 49))
def test_asm_matches_the_reference(uc, g: int, null: bool):
    sp = _run(uc, g, null)
    assert uc.reg_read(UC_X86_REG_EIP) == RETADDR
    assert uc.reg_read(UC_X86_REG_ESP) == sp + 4, "bare RET must consume exactly the E8 return"
    for r, v in REGS.items():
        assert uc.reg_read(r) == v, f"register {r} clobbered"
    assert uc.reg_read(UC_X86_REG_EFLAGS) & 0xCD5 == FLAGS_IN & 0xCD5, "EFLAGS not transparent"

    want = menu_font_request(g)
    if want is None:
        assert g <= NATIVE_G
        assert _rd(uc, FF_COUNT) == 0, "g<=16 must be the displaced store (no engine call)"
        assert _rd(uc, MENU_FONT) == NATIVE_FONT
        return
    assert _rd(uc, FF_COUNT) == 1
    assert (_rd(uc, FF_SIZE), _rd(uc, FF_VARIANT)) == want
    if null:
        assert _rd(uc, MENU_FONT) == NATIVE_FONT, "NULL find_font must fall back to ecx"
    else:
        assert _rd(uc, MENU_FONT) == FONT_BASE + want[0] * 4 + want[1]


@pytest.mark.parametrize("g,size", ((22, 22), (25, 25), (40, 40), (48, 40)))
def test_asm_pins_the_shipped_resolutions(uc, g: int, size: int):
    _run(uc, g)
    assert (_rd(uc, FF_SIZE), _rd(uc, FF_VARIANT)) == (size, 1)


def test_both_writers_ask_for_the_same_font():
    """thunk_menu_layout (the OTHER g_menu_font writer) must carry the same request:
    cmp eax,40 / mov eax,40 / push 1 / push eax / call find_font / ... / mov [g_menu_font],eax.
    A tour must leave the dropdowns exactly as the layout made them."""
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r"- id: thunk_menu_layout\s+offset: 0x[0-9A-Fa-f]+\s+bytes: \"([^\"]+)\"", text)
    assert m, "no cave content entry for thunk_menu_layout"
    body = " ".join(m.group(1).split())
    assert "83 F8 28 7E 05 B8 28 00 00 00 6A 01 50 E8" in body
    assert "A3 68 7B 9B 00" in body


def test_yaml_ledger_content_and_site_agree_with_the_assembler():
    text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    m = re.search(r"thunk_popnorm_menufont:\s*\{ cave: pcave2, offset: (0x[0-9A-Fa-f]+) \}", text)
    assert m and int(m.group(1), 16) == ASM.SLOT_OFFSET, "ledger slot != assembler slot"
    m = re.search(r"- id: thunk_popnorm_menufont\s+offset: (0x[0-9A-Fa-f]+)\s+bytes: \"([^\"]+)\"", text)
    assert m, "no cave content entry for thunk_popnorm_menufont"
    assert int(m.group(1), 16) == ASM.SLOT_OFFSET
    assert m.group(2).split() == ASM.TEMPLATE.split(), "yaml bytes != assembler template"
    m = re.search(r"virtual_addr: 0x005886C1\s+length: 6\s+original_bytes: \"89 0D 68 7B 9B 00\"[^\n]*\s+"
                  r"new_bytes:\s+\"E8 \{rel32:thunk_popnorm_menufont\} 90\"", text)
    assert m, "site 0x5886C1 missing or not the 6-byte CALL+NOP form"
