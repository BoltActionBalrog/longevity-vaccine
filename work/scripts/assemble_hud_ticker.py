"""HUD ticker rows at vanilla x g/16 (2026-10-12) -- group hud_ticker_rows.

The notification ticker above the console strip (TextScroll MainWin+0x1EACC = 0x7CD2EC, canvas Buffer 0x7CD730) is
built by 0x4595C0: TextScroll_attach(x, y = [MainWin+0xD38] - 4*L, w, h = 4*L, ...) with L = the strip font's
line height, and TextScroll_draw lays its entries BOTTOM-UP (ebx = h; ebx -= Buffer_wrap_height(str, w) per
entry).  Vanilla L = 15 (pristine 1024 trace frida_notify_text_terranx_pristine_20261012T065306Z.log: y -18,
h 60, wrap_h 15, text at y 45).  Scaled, the engine reads the SCALED font's L (36 at 4K vs 15 x 2.5 = 37.5) five
times, so the text sat ~8 px low and its glyph bodies slid under the console's raised posts.

  t_ticker_attach  call redirect at 0x459626 (the ticker's TextScroll_attach): y / h = scaling_laws.hud_ticker_window
                   (the vanilla window's two edges, one floor each; h never below the engine's own 4*L_scaled, so
                   4 scaled lines always fit and the update routine 0x629490 never enables the scrollbar);
                   tail-jmp TextScroll_attach 0x6292D0.
  t_ticker_wraph   call redirect at 0x629C79 (Buffer_wrap_height inside TextScroll_draw): the real height, then for
                   the ticker canvas only: rows = h / L_scaled, the entry's bottom ebx is matched to row k
                   (scaling_laws.hud_ticker_row_top), and the step returned is ebx - top(k + rows) so every row top
                   is vanilla's x g/16 under one floor.  Any other TextScroll / g <= 16: the engine's own value.

v2 (2026-10-15, user decision): the whole ticker rises HUD_TICKER_LIFT_NATIVE = 4 native px at EVERY g, so the
bottom row's descenders clear the console strip art (vanilla clips them at 1024 too -- a vanilla-bug fix, the one
exception to the g <= 16 no-op).  g > 16: YN subtracts 4*15 + 4.  g <= 16: t_ticker_attach lowers the engine's own
y arg by 4 (scaling_laws.hud_ticker_native_y) -- done unconditionally at entry, the g > 16 path overwrites the arg.
The rows are bottom-anchored in the canvas, so t_ticker_wraph needs nothing at g <= 16.

Usage: assemble_hud_ticker.py      -> prints the yaml symbol + content lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
ATTACH_OFF, WRAPH_OFF, END = 0x30500, 0x30560, 0x30630   # cave_map: 0x304B1.. free up to t_pw_fit2 (0x30630)
G = 0x00668740                      # g_popup_scale_num
D38 = 0x007AF558                    # MainWin+0xD38 (device-space under the HUD seed table)
TICKER_BUF = 0x007CD730             # ticker TextScroll 0x7CD2EC + 0x444
TS_ATTACH = 0x006292D0              # TextScroll_attach (thiscall)
WRAP_H = 0x005DC360                 # Buffer_wrap_height (thiscall str, w; RET 8)
SITE_ATTACH, SITE_WRAPH = 0x00459626, 0x00629C79
LN, ROWS = 15, 4
LIFT = 4                            # scaling_laws.HUD_TICKER_LIFT_NATIVE

# ceil(D38 * 16 / g) - 4*LN - LIFT -> eax  (D38 >= 0; g > 16) = scaling_laws.hud_ticker_bottom_native
YN = f"""
    mov     eax, dword ptr [{D38:#x}]
    shl     eax, 4
    add     eax, dword ptr [{G:#x}]
    dec     eax
    cdq
    idiv    dword ptr [{G:#x}]
    sub     eax, {ROWS * LN + LIFT}
"""


def asm_attach() -> str:
    # entry: [esp] ret, [esp+4] x, [esp+8] y, [esp+0xC] w, [esp+0x10] h ...; ecx = the ticker
    # the lift first: it IS the g <= 16 result (hud_ticker_native_y); g > 16 overwrites [esp+8] below
    return f"""
    sub     dword ptr [esp+8], {LIFT}
    cmp     dword ptr [{G:#x}], 0x10
    jle     go
    push    eax
    push    edx
    {YN}
    mov     edx, eax
    sub     edx, {ROWS * LN}
    imul    edx, dword ptr [{G:#x}]
    sar     edx, 4
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    mov     dword ptr [esp+0x10], eax
    sub     eax, edx
    cmp     eax, dword ptr [esp+0x18]
    jge     hok
    mov     eax, dword ptr [esp+0x18]
hok:
    mov     dword ptr [esp+0x18], eax
    pop     edx
    pop     eax
go:
    jmp     {TS_ATTACH:#x}
"""


def asm_wraph() -> str:
    # entry: [esp] ret, [esp+4] str, [esp+8] w; ecx = edi = the dest Buffer; ebx = the entry's bottom (canvas y)
    return f"""
    push    dword ptr [esp+8]
    push    dword ptr [esp+8]
    call    {WRAP_H:#x}
    cmp     dword ptr [{G:#x}], 0x10
    jle     out
    cmp     edi, {TICKER_BUF:#x}
    jne     out
    test    eax, eax
    jle     out
    push    eax
    push    ecx
    push    edx
    push    esi
    push    ebp
    mov     ecx, dword ptr [edi+0x52C]
    mov     edx, dword ptr [ecx]
    test    edx, edx
    js      lcell
    add     edx, dword ptr [ecx+0x10]
    jmp     lhave
lcell:
    mov     edx, dword ptr [ecx+0xC]
lhave:
    test    edx, edx
    jle     keep
    mov     ecx, edx
    cdq
    idiv    ecx
    test    eax, eax
    jle     keep
    mov     esi, eax
    {YN}
    mov     ebp, eax
    mov     eax, ebp
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    add     eax, dword ptr [edi+0x84]
    mov     ecx, eax
    xor     edx, edx
kloop:
    imul    eax, edx, {LN}
    neg     eax
    add     eax, ebp
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    sub     eax, ecx
    cmp     eax, ebx
    jle     kfound
    inc     edx
    cmp     edx, {2 * ROWS + 1}
    jl      kloop
    jmp     keep
kfound:
    add     edx, esi
    imul    eax, edx, {LN}
    neg     eax
    add     eax, ebp
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    sub     eax, ecx
    neg     eax
    add     eax, ebx
    mov     dword ptr [esp+0x10], eax
keep:
    pop     ebp
    pop     esi
    pop     edx
    pop     ecx
    pop     eax
out:
    ret     8
"""


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def build() -> dict:
    a = assemble(asm_attach(), PCAVE2 + ATTACH_OFF)
    w = assemble(asm_wraph(), PCAVE2 + WRAPH_OFF)
    assert ATTACH_OFF + len(a) <= WRAPH_OFF, f"t_ticker_attach {len(a)}B overflows"
    assert WRAPH_OFF + len(w) <= END, f"t_ticker_wraph {len(w)}B overflows"
    return {"t_ticker_attach": (ATTACH_OFF, a), "t_ticker_wraph": (WRAPH_OFF, w)}


def to_template(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b).replace("40 87 66 00", "{abs32:g_popup_scale_num}")


def main() -> int:
    for name, (off, b) in build().items():
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {len(b)}B")
    for name, (off, b) in build().items():
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{to_template(b)}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
