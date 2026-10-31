#!/usr/bin/env python
"""W6C helpers in pcave2 0x3F000..0x3FFFF (2026-10-25 wave 6): the F2 research ring at K, and t_dl_bmxt's snapshot
bounds.  Guards: tests/test_rw_ring_asm_parity.py (Unicorn, real bytes) + tests/test_scaling_rw_tech_ring.py (law,
real image).

  t_rw_ring      detour @0x49935D (6 B `mov edx,[ebp-0x28]; mov ecx,[ebp-0x20]` -> E9 + nop), ReportWin_tech_page's
                 research bracket 2.  Vanilla insets the increment rect (bracket 1's clip, [ebp-0x28..-0x1C]) by 1 on
                 every side with inc / dec (0x499366 L, 0x499367 R, 0x499368 T, 0x499378 B) and clips bracket 2 to
                 it: bracket 1's progress art shows as a 1-px ring around bracket 2's bar-coloured interior.  The ring
                 is a 1-px stroke, so the inset is K = stroke_width(g) (law scaling_laws.rw_tech_ring_clip; K = 1 at
                 g <= 16, byte-for-byte vanilla).  Replays 0x49935D..0x49937E with K for the 1s and resumes at the
                 Buffer_set_clip call 0x49937F with the vanilla register state (eax = &rect pushed, ecx = edi,
                 edx = the new B).  The rect locals are dead after the page's inset back at 0x4993FA..0x499419.
  t_dl_snapchk   CALL helper from t_dl_bmxt, after it has staged the clamped snapshot bbox in g_dl_bx.  Returns
                 ebx = the snapshot plane when (x1 - x0) * (y1 - y0) fits it, else ebx = 0 (t_dl_bmxt then draws the
                 frame natively: no snapshot, no write past the plane, no rep movsb with a negative count).  Owns the
                 plane's allocation when t_rw_init_leave has not made one (its 4 MB VirtualAlloc failed, or the
                 bmxt ran first): 4 MB, else the old 64 KB fallback, its size recorded in g_dl_snapcap.  A plane with
                 g_dl_snapcap = 0 is t_rw_init_leave's (its only allocation, push 0x400000 -- pinned by the parity
                 test).  Keeps ecx (t_dl_bmxt's dest, the native tail's this), esi, edi; clobbers eax, edx.

  t_rw_br1       bracket 1's draw (call site 0x499328, was E8 -> t_dl_bmxt): g > 16 -> t_dl_bmxt, then t_rw_restripe of
                 the buffer clip (= the increment, Buffer +0x20) with the same set.  Bracket 1 fills the whole
                 increment, so every column has its stripe mate and the progress art lands on the device grid
                 (y % P, the page's own restripe law); bracket 2 then covers the interior and the K-row ring keeps
                 the device phase.  Without it the ring's top / bottom rows kept the enlarge's phase (no mate left
                 in a K-row run for the page's final mate-required restripe): a corner pixel of the other member at
                 1600x1200 / 1920x1080.  g <= 16: t_dl_bmxt unchanged (its own native tail).  RET 8, thiscall.

Data: g_dl_snapcap @0x3F1F0 (4 B).

Usage: py assemble_rw_ring.py   -> prints the yaml symbol + content lines and the site bytes
"""
from __future__ import annotations

import contextlib
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
with contextlib.redirect_stdout(io.StringIO()):
    import assemble_dl as AD  # noqa: E402
SE = AD.SE

PCAVE2 = AD.PCAVE2
REGION = (0x3F000, 0x40000)                 # W6C's pcave2 region
G = AD.G
RING_SITE, RING_LEN, RING_RESUME = 0x49935D, 6, 0x49937F
RING_ORIG = bytes.fromhex("8B55D8 8B4DE0".replace(" ", ""))
SNAP_BIG, SNAP_SMALL = 0x400000, 0x10000    # t_rw_init_leave's plane; the bmxt's historical 64 KB fallback

HELPERS = {     # name -> (offset, end of its slot)
    "t_rw_ring": (0x3F000, 0x3F080),
    "t_dl_snapchk": (0x3F080, 0x3F140),
    "t_rw_br1": (0x3F140, 0x3F1C0),
}
DATA = {"g_dl_snapcap": (0x3F1F0, 4)}
VA = {n: PCAVE2 + o for n, (o, _e) in {**HELPERS, **DATA}.items()}
assert VA["t_dl_snapchk"] == AD.T_DL_SNAPCHK and VA["g_dl_snapcap"] == AD.G_DL_SNAPCAP
BX = AD.BX
SNAPBUF = AD.CELL["g_dl_snapbuf"]
CAP = VA["g_dl_snapcap"]
T_DL_BMXT = PCAVE2 + 0x22680              # assemble_dl LAYOUT (pinned by the parity test)
T_RW_RESTRIPE = PCAVE2 + 0x23C20          # assemble_rw LAYOUT (pinned by the parity test)
BR1_SITE = 0x499328                       # bracket 1's Buffer_box_sprite call (was E8 -> t_dl_bmxt, site frame_499328)


def asm_ring() -> str:
    return f"""
    mov     edx, dword ptr [ebp-0x28]
    mov     ecx, dword ptr [ebp-0x20]
    mov     eax, dword ptr [ebp-0x24]
    push    esi
    mov     esi, 1
    cmp     dword ptr [{G:#x}], 16
    jle     kset
    mov     esi, dword ptr [{G:#x}]
    lea     esi, [esi*2+15]
    shr     esi, 5                      ; K = stroke_width(g) = half_down(g, 16) = (2g + 15) >> 5
kset:
    add     edx, esi
    sub     ecx, esi
    add     eax, esi
    mov     dword ptr [ebp-0x28], edx
    mov     edx, dword ptr [ebp-0x1c]
    mov     dword ptr [ebp-0x24], eax
    lea     eax, [ebp-0x28]
    mov     dword ptr [ebp-0x20], ecx
    sub     edx, esi
    pop     esi
    push    eax
    mov     ecx, edi
    mov     dword ptr [ebp-0x1c], edx
    jmp     {RING_RESUME:#x}
"""


def asm_snapchk() -> str:
    return f"""
    xor     ebx, ebx
    mov     eax, dword ptr [{BX['X1']:#x}]
    sub     eax, dword ptr [{BX['X0']:#x}]
    jle     sdone
    mov     edx, dword ptr [{BX['Y1']:#x}]
    sub     edx, dword ptr [{BX['Y0']:#x}]
    jle     sdone
    mul     edx                         ; edx:eax = the snapshot's bytes (both factors > 0)
    test    edx, edx
    jnz     sdone
    mov     ebx, dword ptr [{SNAPBUF:#x}]
    test    ebx, ebx
    jnz     known
    push    eax
    push    ecx
    push    4
    push    0x3000
    push    {SNAP_BIG:#x}
    push    0
    call    dword ptr [{AD.IAT_VIRTUALALLOC:#x}]
    mov     edx, {SNAP_BIG:#x}
    test    eax, eax
    jnz     gotp
    push    4
    push    0x3000
    push    {SNAP_SMALL:#x}
    push    0
    call    dword ptr [{AD.IAT_VIRTUALALLOC:#x}]
    mov     edx, {SNAP_SMALL:#x}
    test    eax, eax
    jnz     gotp
    pop     ecx
    pop     eax
    ret
gotp:
    mov     dword ptr [{SNAPBUF:#x}], eax
    mov     dword ptr [{CAP:#x}], edx
    mov     ebx, eax
    pop     ecx
    pop     eax
known:
    mov     edx, dword ptr [{CAP:#x}]
    test    edx, edx
    jnz     cmpc
    mov     edx, {SNAP_BIG:#x}               ; t_rw_init_leave's plane
    mov     dword ptr [{CAP:#x}], edx
cmpc:
    cmp     eax, edx
    jbe     sdone
    xor     ebx, ebx
sdone:
    ret
"""


def asm_br1() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jg      go
    jmp     {T_DL_BMXT:#x}
go:
    push    ecx
    push    dword ptr [esp+0xC]
    push    dword ptr [esp+0xC]
    call    {T_DL_BMXT:#x}
    pop     ecx
    lea     eax, [ecx+0x20]
    push    dword ptr [esp+8]
    push    eax
    push    ecx
    call    {T_RW_RESTRIPE:#x}
    ret     8
"""


ASM = {"t_rw_ring": asm_ring, "t_dl_snapchk": asm_snapchk, "t_rw_br1": asm_br1}
SYMS = {G: "g_popup_scale_num", SNAPBUF: "g_dl_snapbuf", CAP: "g_dl_snapcap", T_DL_BMXT: "t_dl_bmxt",
        T_RW_RESTRIPE: "t_rw_restripe"}


def assemble(name: str) -> bytes:
    off, end = HELPERS[name]
    b = SE.assemble(ASM[name](), PCAVE2 + off)
    assert off + len(b) <= end and REGION[0] <= off and end <= REGION[1], (name, len(b))
    return b


def template(name: str) -> str:
    off, _end = HELPERS[name]
    return SE.templatize(assemble(name), PCAVE2 + off, SYMS)


def ring_site_bytes() -> bytes:
    return b"\xE9" + struct.pack("<i", VA["t_rw_ring"] - (RING_SITE + 5)) + b"\x90" * (RING_LEN - 5)


def main() -> int:
    for name, (off, end) in HELPERS.items():
        b = assemble(name)
        print(f"; {name} {len(b)} B @{off:#x}..{off + len(b):#x} (slot to {end:#x})")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{template(name)}\"")
    print(f"; site frame_499328 @{BR1_SITE:#x}: E8 {{rel32:t_dl_bmxt}} -> E8 {{rel32:t_rw_br1}}")
    print(f"; site tech_page.research_ring @{RING_SITE:#x}: {RING_ORIG.hex(' ').upper()} -> {ring_site_bytes().hex(' ').upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
