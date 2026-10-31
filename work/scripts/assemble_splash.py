#!/usr/bin/env python
"""Assembler for the startup SPLASH bake (group splash_scale, 2026-10-11): logo.pcx scaled to the screen.

Vanilla draws the 800x600 Firaxis splash with a 1:1 Buffer_copy_4 0x5DFF00 (thiscall src Buffer; dest, sx, sy,
dx, dy, w, h; RET 0x1C) centred on g_screen_buffer 0x9B7490 after Buffer_fill_2(0), at two sites:

  Win_init_class.splash_blit        0x5F0482  (startup)
  GraphicsMgr_set_mode.splash_blit  0x635706  (a mode set with flags != 0; Win_flip_rect follows)

Both calls are redirected (call_target_redirect, 5 B each) to ONE thunk, t_splash_blit:

  num = splash_scale_num(W, H) = min(floor(16*H/768), floor(16*W/1024)) from the DEST Buffer's own dims
        (+0x80 width, -[+0x84] height: the screen buffer was just resized to ScreenWidth x ScreenHeight).
  num <= 16 -> tail-jmp to Buffer_copy_4 with the caller's args (the vanilla blit, untouched).
  else      -> Buffer_sync_to_palette(dest, [g_active_palette]) (Win_flip_rect's own sync, done before the
               resample so dest+0xA4 is the display table the src indices mean), t_splash_lut_on
               (g_mon_lut_ok := 0 -- the Monument's cached LUT belongs to another palette -- and the LUT
               search range := [SPLASH_PAL_LO, SPLASH_PAL_HI) = the logo's own entries 10..245), then
               t_mon_resample (Lanczos-3 + FS, scaling_laws.mon_resample) of the whole src into
               splash_rect: s(w) x s(h) centred >> 1, t_splash_lut_off (g_mon_lut_ok := 0 again, range
               := the default [0, 256) the Monument / Hall of Fame search), eax = 0, ret 0x1C.

The resampler is the Monument's (stdcall, RET 0x2C, preserves ebx/esi/edi/ebp, lazily mallocs its scratch,
clips to the dest, bails on bad dims).  Laws: scaling_laws "STARTUP SPLASH".  Parity:
tests/test_splash_asm_parity.py (Unicorn).  Slots: pcave2 0x30A00..0x30B00 (t_dp_status_fit follows);
the two range helpers at 0xDEF0 / 0xDF10, next to the range cells g_mon_lut_lo / g_mon_lut_hi
(assemble_mon.PLACED_DATA, 0xDEE0 / 0xDEE4).
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import assemble_se as SE  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
OFF, BUDGET = 0x30A00, 0x100          # 0x30A00..0x30B00 (t_dp_status_fit starts 0x30B00)
VA = PCAVE2 + OFF
OFF_ON, OFF_OFF, HELPER_BUDGET = 0xDEF0, 0xDF10, 0x20
VA_ON, VA_OFF = PCAVE2 + OFF_ON, PCAVE2 + OFF_OFF

COPY4 = 0x005DFF00                    # Buffer_copy_4 (thiscall src; dest, sx, sy, dx, dy, w, h) RET 0x1C
SYNC = 0x005DE8F0                     # Buffer_sync_to_palette (thiscall buf; pal) RET 4
ACTIVE_PAL = 0x009B8180               # g_active_palette (Palette*)
T_MON_RESAMPLE = PCAVE2 + 0x2BA20     # (sdata, spitch, sx, sy, sw, sh, dest, dx, dy, dw, dh) RET 0x2C
G_MON_LUT_OK = PCAVE2 + 0x2D3A4
G_MON_LUT_LO, G_MON_LUT_HI = PCAVE2 + 0xDEE0, PCAVE2 + 0xDEE4     # assemble_mon.PLACED_DATA

SITES = [   # (id, function, call VA)
    ("Win_init_class.splash_blit", "Win_init_class", 0x005F0482),
    ("GraphicsMgr_set_mode.splash_blit", "GraphicsMgr_set_mode", 0x00635706),
]


def _hd(reg: str) -> str:
    """reg = half_down(reg * num, 16) with num in ebx (scaling_laws.mon_s)."""
    return f"imul {reg}, ebx\n    lea {reg}, [{reg}*2+15]\n    sar {reg}, 5\n"


ASM = f"""
    push    ebx
    push    esi
    push    edi
    push    ebp
    mov     ebp, esp
    mov     esi, ecx
    mov     edi, dword ptr [ebp+0x14]
    test    edi, edi
    jz      native
    mov     eax, dword ptr [edi+0x84]
    neg     eax
    test    eax, eax
    jle     native
    shl     eax, 4
    cdq
    mov     ecx, 0x300
    idiv    ecx
    mov     ebx, eax
    mov     eax, dword ptr [edi+0x80]
    test    eax, eax
    jle     native
    shl     eax, 4
    cdq
    mov     ecx, 0x400
    idiv    ecx
    cmp     eax, ebx
    jge     have_num
    mov     ebx, eax
have_num:
    cmp     ebx, 16
    jle     native
    push    dword ptr [{ACTIVE_PAL:#x}]
    mov     ecx, edi
    call    {SYNC:#x}
    call    {VA_ON:#x}
    mov     eax, dword ptr [ebp+0x2C]
    {_hd('eax')}
    push    eax
    mov     edx, dword ptr [edi+0x84]
    neg     edx
    sub     edx, eax
    sar     edx, 1
    mov     eax, dword ptr [ebp+0x28]
    {_hd('eax')}
    push    eax
    push    edx
    mov     ecx, dword ptr [edi+0x80]
    sub     ecx, eax
    sar     ecx, 1
    push    ecx
    push    edi
    push    dword ptr [ebp+0x2C]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp+0x1C]
    push    dword ptr [ebp+0x18]
    push    dword ptr [esi+0x4A8]
    push    dword ptr [esi+0x54]
    call    {T_MON_RESAMPLE:#x}
    call    {VA_OFF:#x}
    xor     eax, eax
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    ret     0x1C
native:
    mov     ecx, esi
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
    jmp     {COPY4:#x}
"""



def _asm_range(lo: int, hi: int) -> str:
    """CALL helper: g_mon_lut_ok := 0 (rebuild the LUT) and the LUT search range := [lo, hi). Flags/regs
    are untouched; bare ret."""
    return f"""
    mov     dword ptr [{G_MON_LUT_OK:#x}], 0
    mov     dword ptr [{G_MON_LUT_LO:#x}], {lo}
    mov     dword ptr [{G_MON_LUT_HI:#x}], {hi}
    ret
"""


ASM_ON = _asm_range(SL.SPLASH_PAL_LO, SL.SPLASH_PAL_HI)     # t_splash_lut_on: the logo's own entries
ASM_OFF = _asm_range(0, 256)                                # t_splash_lut_off: the Monument default

SYMS = {T_MON_RESAMPLE: "t_mon_resample", G_MON_LUT_OK: "g_mon_lut_ok", SYNC: "Buffer_sync_to_palette",
        ACTIVE_PAL: "g_active_palette"}
TEMPLATE_SYMS = {T_MON_RESAMPLE: "t_mon_resample", G_MON_LUT_OK: "g_mon_lut_ok", G_MON_LUT_LO: "g_mon_lut_lo",
                 G_MON_LUT_HI: "g_mon_lut_hi", VA_ON: "t_splash_lut_on", VA_OFF: "t_splash_lut_off"}


def assemble() -> bytes:
    b = SE.assemble(ASM, VA)
    assert len(b) <= BUDGET, f"t_splash_blit {len(b)}B exceeds the {BUDGET:#x} slot"
    return b


def assemble_helpers() -> dict[str, tuple[int, bytes]]:
    """{name: (VA, bytes)} of the two range helpers."""
    out = {}
    for name, va, src in (("t_splash_lut_on", VA_ON, ASM_ON), ("t_splash_lut_off", VA_OFF, ASM_OFF)):
        b = SE.assemble(src, va)
        assert len(b) <= HELPER_BUDGET, f"{name} {len(b)}B exceeds its {HELPER_BUDGET:#x} slot"
        out[name] = (va, b)
    return out


def template() -> str:
    """yaml hex: cave symbols as {abs32:}/{rel32:} placeholders (engine VAs stay literal unless named)."""
    return SE.templatize(assemble(), VA, TEMPLATE_SYMS)


def helper_templates() -> dict[str, str]:
    return {n: SE.templatize(b, va, TEMPLATE_SYMS) for n, (va, b) in assemble_helpers().items()}


def site_original(va: int) -> bytes:
    return b"\xE8" + struct.pack("<i", COPY4 - (va + 5))


def main() -> int:
    b = assemble()
    print(f"t_splash_blit @ pcave2+{OFF:#x} (VA {VA:#x}) = {len(b)} B")
    print(template())
    for n, (va, hb) in assemble_helpers().items():
        print(f"{n} @ pcave2+{va - PCAVE2:#x} = {len(hb)} B")
        print(helper_templates()[n])
    for sid, _fn, va in SITES:
        orig = SE.base_exe_bytes(va, 5)
        assert orig == site_original(va), (sid, orig.hex())
        print(f"{sid} @{va:#x}: {orig.hex(' ').upper()} -> E8 {{rel32:t_splash_blit}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
