"""Differential: t_gv_bodyb (W9C F54, 2026-10-27), the BAKED bytes under Unicorn, against
scaling_laws.popup_body_box_bottom.

t_gv_bodyb sits on Popup_on_draw_background's d528 body-box call 0x406154 in front of thunk_d528_inset.  For every g
(8..64), popup identity (the faction-quote popup 0x9403E0 or another), dialog field [+0x2350] (-1 or an element) and art
[+0x2144] (0 or a sprite): the body rect's B [ebp-0x28] afterwards == popup_body_box_bottom(B, dialog, art, popup, g);
L / T / R untouched; then control reaches thunk_d528_inset with the stack exactly as the site's call left it (the
return address and both args), every register and EFLAGS as on entry.  Also: the yaml bytes are the assembler's, the
site 0x406154 calls t_gv_bodyb, and nothing else calls it.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("keystone", reason="keystone absent")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_body_box as BB  # noqa: E402
import scaling_laws as SL  # noqa: E402


def _live():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    out = {}
    for c in caves:
        for e in c.get("contents") or []:
            va = int(c["virtual_addr"]) + int(e["offset"])
            out[e["id"]] = (va, bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(va, sym)), e)
    return out, sym, _s


LIVE, SYM, SITES = _live()
VA, CODE, ENTRY = LIVE["t_gv_bodyb"]
G = SYM["g_popup_scale_num"]
TARGET = SYM["thunk_d528_inset"]
STACK, FRAME, POP2 = 0x00200000, 0x00300000, 0x00500000
RECT = FRAME - 0x34
SITE_RET = 0x00406159


def run(g, popup, dialog, art, flags):
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for p in sorted({VA & ~0xFFF, (VA + len(CODE)) & ~0xFFF, G & ~0xFFF, TARGET & ~0xFFF, popup & ~0xFFF,
                     (popup + 0x2400) & ~0xFFF}):
        try:
            mu.mem_map(p, 0x1000)
        except unicorn.UcError:
            pass
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(FRAME - 0x1000, 0x2000)
    mu.mem_write(VA, CODE)
    mu.mem_write(TARGET, b"\xF4")
    mu.mem_write(G, struct.pack("<i", g))
    mu.mem_write(popup + 0x2350, struct.pack("<i", dialog))
    mu.mem_write(popup + 0x2144, struct.pack("<I", art))
    rect = (40, 50, 600, 300)
    mu.mem_write(RECT, struct.pack("<4i", *rect))
    sp = STACK
    mu.mem_write(sp, struct.pack("<3I", SITE_RET, RECT, 0x78D528))
    regs = {UC_X86_REG_EAX: 0xA1A1A1A1, UC_X86_REG_EBX: 0xB2B2B2B2, UC_X86_REG_ECX: popup + 0x444,
            UC_X86_REG_EDX: 0xD4D4D4D4, UC_X86_REG_ESI: popup, UC_X86_REG_EDI: 0xE5E5E5E5, UC_X86_REG_EBP: FRAME}
    for r, v in regs.items():
        mu.reg_write(r, v)
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_EFLAGS, flags)
    reached = []
    mu.hook_add(UC_HOOK_CODE, lambda m, a, s, u: (reached.append(1), m.emu_stop()), begin=TARGET, end=TARGET)
    mu.emu_start(VA, TARGET + 0x100, count=10_000)
    assert reached
    assert mu.reg_read(UC_X86_REG_ESP) == sp and bytes(mu.mem_read(sp, 12)) == struct.pack("<3I", SITE_RET, RECT,
                                                                                             0x78D528)
    assert all(mu.reg_read(r) == v for r, v in regs.items())
    assert mu.reg_read(UC_X86_REG_EFLAGS) & 0xCD5 == flags & 0xCD5
    got = struct.unpack("<4i", bytes(mu.mem_read(RECT, 16)))
    return rect, got


@pytest.mark.parametrize("g", list(range(8, 65)))
def test_body_rect_bottom_is_the_law(g):
    for popup in (SL.FACTION_QUOTE_POPUP, POP2):
        for dialog in (-1, 0, 3):
            for art in (0, 0x00777000):
                for flags in (0x202, 0x2C3):
                    rect, got = run(g, popup, dialog, art, flags)
                    want = rect[:3] + (SL.popup_body_box_bottom(rect[3], dialog, art, popup, g),)
                    assert got == want, (g, hex(popup), dialog, hex(art))


def test_yaml_is_the_assembler_and_the_site_calls_it():
    assert " ".join(str(ENTRY["bytes"]).split()) == BB.template("t_gv_bodyb")
    site = [s for s in SITES if int(s.get("virtual_addr", 0) or 0) == BB.SITE]
    assert len(site) == 1 and " ".join(site[0]["new_bytes"].split()) == "E8 {rel32:t_gv_bodyb}"
    callers = [k for k, (va, b, _e) in LIVE.items() for i in range(len(b) - 4)
               if b[i] in (0xE8, 0xE9) and (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True))
               & 0xFFFFFFFF == VA]
    assert callers == []
