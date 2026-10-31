"""PlanWin native render + enlarge -- the Go To / battle-plan map panel at vanilla's framing (user decision 2026-10-15,
option (b); laws scaling_laws.planwin_native_dims / planwin_enlarge).

The panel PlanWin (0x834D70, a MapWin) draws into its window canvas Buffer [[PW]+4]+PW+0x444, sized to the device
panel (597 x 297 at 4K); MapWin_calculate_dimensions 0x462980 takes the tile window from that Buffer's +0x80 / +0x84
(Win +0x4C4 / +0x4C8), and the map tiles have fixed native sizes per zoom, so no engine zoom framed a trip as vanilla
does.  Lever: while PlanWin draws, its canvas Buffer READS as vanilla's 239 x 119 -- w / h / clip (+0x20) / bounds
(+0x30) set to the native size (pixel(x,y) = data + x + y*stride, so the engine renders vanilla's exact image into
the canvas' top-left corner, same memory and stride) -- and that native image is enlarged x g/16 in place before it
reaches the screen.

Entries (function-entry detours, every caller and the Win part's vtbl+0x30 repaint 0x48BF70 go through them):
  PlanWin_render       0x48B3F0  (render + canvas -> save copy)        -> t_pw_render
  PlanWin_overlay_draw 0x48AF30  (save -> canvas, markers, lines, present @0x48B3AA) -> t_pw_overlay
  PlanWin_fit_two      0x48B630  (zoom-fit loop, calls render)        -> t_pw_fit2
  PlanWin_fit_one      0x48B8E0  (zoom-fit loop, draw_map + save copy) -> t_pw_fit1
  present call         0x48B3AA  `call [edx+0xFC]` in overlay_draw    -> t_pw_present (enlarge, device dims, present,
                                                                          native dims again)
State: depth counter (nesting: fit_two calls render), on (dims shrunk), dirty (the native corner holds a fresh native
image: set by every draw entry, cleared by the enlarge -- an enlarge of a stale corner would zoom it again).  The
outermost exit of render / fit enlarges (a Win_show / repaint between draws then shows the enlarged map); the
overlay enlarges at its present.  g <= 16, an unusable canvas (w or h outside 16..1024 or below native, no data) or a device canvas
smaller than native: everything passes through untouched.
The route line (0x48B370) and PlanWin_open's zoom are the engine's again (t_pw_line stays for the main map).

Usage: assemble_planwin_native.py      -> prints the yaml symbol + content + site lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
G = 0x00668740
PW = 0x00834D70
NATIVE_W, NATIVE_H = 239, 119
BUF = 0x444                                       # canvas Buffer within the Win part
B_CLIP, B_W, B_H, B_DATA, B_STRIDE = 0x20, 0x80, 0x84, 0x54, 0x4A8

# data cells (pcave2): depth, on, dirty, saved clip L,T,R,B + bounds L,T,R,B, saved w, saved h
DATA_OFF = 0x4570
DEPTH, ON, DIRTY, SV = (PCAVE2 + DATA_OFF + o for o in (0, 4, 8, 0xC))
DATA_SIZE = 0xC + 40

# code slots (cave_map --at, 2026-10-15): (offset, end)
SLOTS = {   # cave_map --min-gap (2026-10-15); data cells g_pw_state at 0x4570..0x45A4 (free 0x4568..0x4640)
    "enlarge": (0x27900, 0x27A00),                # free 0x278FA..0x27A00
    "native":  (0x002D0, 0x003A0),                # free 0x2C1..0x3A0
    "device":  (0x00560, 0x005D0),                # free 0x554..0x5D0
    "shrink":  (0x00940, 0x00A00),                # free 0x937..0xA00
    "state":   (0x00E00, 0x00EC0),                # free 0xDF7..0xEC0
    "wrap":    (0x0DF30, 0x0E000),                # free 0xDF2F..0xE000
    "fit":     (0x30630, 0x306C0),                # the old t_pw_zinit slot (0x3062B..0x306C0)
    "fit1":    (0x03D60, 0x03DC0),                # v2: free 0x3D57..0x3DC0 (cave_map --fit 0x60, 2026-10-15)
}
# function -> slot, in placement order within the slot
FUNCS = [
    ("t_pw_enlarge", "enlarge"),
    ("t_pw_native", "native"), ("t_pw_device", "device"),
    ("t_pw_shrink", "shrink"), ("t_pw_unshrink", "state"), ("t_pw_exit", "state"),
    ("t_pw_render", "wrap"), ("t_pw_overlay", "wrap"), ("t_pw_present", "wrap"),
    ("t_pw_fit2", "fit"), ("t_pw_fit1", "fit1"),
]

SITES = {   # id: (va, original bytes, new-bytes kind, length)
    "PlanWin_render.native":       (0x0048B3F0, "56 8B F1 6A 00", "jmp:t_pw_render", 5),
    "PlanWin_overlay_draw.native": (0x0048AF30, "55 8B EC 83 EC 2C", "jmp:t_pw_overlay", 6),
    "PlanWin_fit_two.native":      (0x0048B630, "55 8B EC 83 EC 14", "jmp:t_pw_fit2", 6),
    "PlanWin_fit_one.native":      (0x0048B8E0, "55 8B EC 83 EC 14", "jmp:t_pw_fit1", 6),
    "PlanWin_overlay_draw.present": (0x0048B3AA, "FF 92 FC 00 00 00", "call:t_pw_present", 6),
}


def _buf(reg: str = "ebx") -> str:
    """reg = the PlanWin canvas Buffer ([[PW]+4] + PW + 0x444); clobbers eax."""
    return f"""
    mov     eax, dword ptr [{PW:#x}]
    mov     eax, dword ptr [eax+4]
    lea     {reg}, [eax+{PW + BUF:#x}]
"""


def asm(name: str, a: dict) -> str:
    if name == "t_pw_enlarge":
        # in place: the native nw x nh corner -> the device dw x dh canvas, rows / columns last to first
        return f"""
    pushad
{_buf()}
    mov     ebp, esp
    sub     esp, 0x420
    mov     eax, dword ptr [ebx+{B_DATA:#x}]
    test    eax, eax
    jz      ex
    mov     dword ptr [ebp-0x18], eax
    mov     eax, dword ptr [ebx+{B_W:#x}]
    mov     dword ptr [ebp-4], eax
    mov     eax, dword ptr [ebx+{B_H:#x}]
    neg     eax
    mov     dword ptr [ebp-8], eax
    mov     eax, dword ptr [{SV + 0x20:#x}]
    mov     dword ptr [ebp-0xc], eax
    mov     eax, dword ptr [{SV + 0x24:#x}]
    neg     eax
    mov     dword ptr [ebp-0x10], eax
    mov     eax, dword ptr [ebx+{B_STRIDE:#x}]
    mov     dword ptr [ebp-0x14], eax
    xor     ecx, ecx
tb:
    lea     eax, [ecx*2+1]
    imul    eax, dword ptr [ebp-4]
    cdq
    mov     edi, dword ptr [ebp-0xc]
    add     edi, edi
    idiv    edi
    mov     edi, dword ptr [ebp-4]
    dec     edi
    cmp     eax, edi
    jle     t1
    mov     eax, edi
t1:
    mov     byte ptr [esp+ecx], al
    inc     ecx
    cmp     ecx, dword ptr [ebp-0xc]
    jl      tb
    mov     eax, dword ptr [ebp-0x10]
    dec     eax
    mov     dword ptr [ebp-0x1c], eax
rl:
    mov     eax, dword ptr [ebp-0x1c]
    lea     eax, [eax*2+1]
    imul    eax, dword ptr [ebp-8]
    cdq
    mov     edi, dword ptr [ebp-0x10]
    add     edi, edi
    idiv    edi
    mov     edi, dword ptr [ebp-8]
    dec     edi
    cmp     eax, edi
    jle     r1
    mov     eax, edi
r1:
    imul    eax, dword ptr [ebp-0x14]
    add     eax, dword ptr [ebp-0x18]
    mov     esi, eax
    mov     edi, dword ptr [ebp-0x1c]
    imul    edi, dword ptr [ebp-0x14]
    add     edi, dword ptr [ebp-0x18]
    mov     ecx, dword ptr [ebp-0xc]
colp:
    dec     ecx
    movzx   edx, byte ptr [esp+ecx]
    mov     dl, byte ptr [esi+edx]
    mov     byte ptr [edi+ecx], dl
    test    ecx, ecx
    jnz     colp
    dec     dword ptr [ebp-0x1c]
    jns     rl
    mov     dword ptr [{DIRTY:#x}], 0
ex:
    mov     esp, ebp
    popad
    ret
"""
    if name == "t_pw_native":
        # w / h / clip / bounds := native, from the saved device values (each clip/bounds edge clamped)
        clamp = "".join(f"""
    mov     eax, dword ptr [{SV + o:#x}]
    cmp     eax, {'esi' if o % 8 == 0 else 'edi'}
    cmovg   eax, {'esi' if o % 8 == 0 else 'edi'}
    mov     dword ptr [ebx+{B_CLIP + o:#x}], eax""" for o in range(0, 0x20, 4))
        return f"""
    pushad
{_buf()}
    mov     esi, dword ptr [{SV + 0x20:#x}]
    mov     eax, {NATIVE_W}
    cmp     esi, eax
    cmovg   esi, eax
    mov     edi, dword ptr [{SV + 0x24:#x}]
    neg     edi
    mov     eax, {NATIVE_H}
    cmp     edi, eax
    cmovg   edi, eax
    mov     dword ptr [ebx+{B_W:#x}], esi
    mov     eax, edi
    neg     eax
    mov     dword ptr [ebx+{B_H:#x}], eax
{clamp}
    popad
    ret
"""
    if name == "t_pw_device":
        return f"""
    pushad
{_buf()}
    lea     edi, [ebx+{B_CLIP:#x}]
    mov     esi, {SV:#x}
    mov     ecx, 8
    rep     movsd dword ptr es:[edi], dword ptr [esi]
    mov     eax, dword ptr [{SV + 0x20:#x}]
    mov     dword ptr [ebx+{B_W:#x}], eax
    mov     eax, dword ptr [{SV + 0x24:#x}]
    mov     dword ptr [ebx+{B_H:#x}], eax
    popad
    ret
"""
    if name == "t_pw_shrink":
        return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     r
    inc     dword ptr [{DEPTH:#x}]
    cmp     dword ptr [{DEPTH:#x}], 1
    jne     r
    pushad
{_buf()}
    mov     ecx, dword ptr [ebx+{B_W:#x}]
    cmp     ecx, 0x10
    jl      x
    cmp     ecx, 0x400
    jg      x
    cmp     ecx, {NATIVE_W}
    jl      x
    mov     edx, dword ptr [ebx+{B_H:#x}]
    neg     edx
    cmp     edx, 0x10
    jl      x
    cmp     edx, 0x400
    jg      x
    cmp     edx, {NATIVE_H}
    jl      x
    lea     esi, [ebx+{B_CLIP:#x}]
    mov     edi, {SV:#x}
    mov     ecx, 8
    rep     movsd dword ptr es:[edi], dword ptr [esi]
    mov     eax, dword ptr [ebx+{B_W:#x}]
    mov     dword ptr [{SV + 0x20:#x}], eax
    mov     eax, dword ptr [ebx+{B_H:#x}]
    mov     dword ptr [{SV + 0x24:#x}], eax
    mov     dword ptr [{ON:#x}], 1
    call    {a['t_pw_native']:#x}
x:
    popad
r:
    ret
"""
    if name == "t_pw_unshrink":
        # the outermost exit (depth back to 0, or never raised at g <= 16): dirty cleared, device dims restored
        return f"""
    cmp     dword ptr [{DEPTH:#x}], 0
    jle     z
    dec     dword ptr [{DEPTH:#x}]
    jnz     r
z:
    mov     dword ptr [{DIRTY:#x}], 0
    cmp     dword ptr [{ON:#x}], 0
    je      r
    call    {a['t_pw_device']:#x}
    mov     dword ptr [{ON:#x}], 0
r:
    ret
"""
    if name == "t_pw_exit":
        # the outermost draw exit: enlarge a fresh native corner, then restore the device dims
        return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     u
    cmp     dword ptr [{DEPTH:#x}], 1
    jne     u
    cmp     dword ptr [{ON:#x}], 0
    je      u
    cmp     dword ptr [{DIRTY:#x}], 0
    je      u
    call    {a['t_pw_enlarge']:#x}
u:
    push    {a['t_pw_unshrink']:#x}
    ret
"""
    if name == "t_pw_render":
        return f"""
    call    {a['t_pw_shrink']:#x}
    call    tr
    mov     dword ptr [{DIRTY:#x}], 1
    push    {a['t_pw_exit']:#x}
    ret
tr:
    push    esi
    mov     esi, ecx
    push    0
    push    0x48B3F5
    ret
"""
    if name == "t_pw_overlay":
        return f"""
    call    {a['t_pw_shrink']:#x}
    mov     dword ptr [{DIRTY:#x}], 1
    call    tr
    push    {a['t_pw_unshrink']:#x}
    ret
tr:
    push    ebp
    mov     ebp, esp
    sub     esp, 0x2c
    push    0x48AF36
    ret
"""
    if name == "t_pw_present":
        # CALLed at 0x48B3AA in place of `call [edx+0xFC]`: ecx = the Win part, edx = its vtbl; no stack args
        return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     pl
    cmp     dword ptr [{ON:#x}], 0
    je      pl
    cmp     dword ptr [{DIRTY:#x}], 0
    je      dv
    call    {a['t_pw_enlarge']:#x}
dv:
    call    {a['t_pw_device']:#x}
    push    ecx
    call    dword ptr [edx+0xfc]
    pop     ecx
    call    {a['t_pw_native']:#x}
    ret
pl:
    jmp     dword ptr [edx+0xfc]
"""
    if name in ("t_pw_fit2", "t_pw_fit1"):
        # v2 (audit 2026-10-15): at g > 16 the fit's own FORCE argument (fit_two arg 5 [ebp+0x18] -> render at
        # 0x48B898; fit_one arg 3 [ebp+0x10] -> draw_map + save copy at 0x48BA1A; read nowhere else) is set on the
        # re-pushed copy, so a fit ALWAYS draws: (1) the native corner is fresh whenever DIRTY is set -- vanilla skips
        # the draw when zoom and centre come out unchanged (0x48B8C4 / 0x48BA46), and an unconditional DIRTY then made
        # t_pw_exit enlarge an already-enlarged canvas; (2) a save Buffer re-made black (Buffer_init after a display
        # mode change) is redrawn on the same trip instead of copied under the markers (the 1080 "no terrain" shot).
        # fit_two's draw is its nested render, which sets DIRTY itself; fit_one draws inline, so its wrapper sets it.
        n, back = (5, 0x48B636) if name == "t_pw_fit2" else (3, 0x48B8E6)
        repush = "".join(f"    push    dword ptr [esp+{4 * n:#x}]\n" for _ in range(n))
        dirty = "" if name == "t_pw_fit2" else f"    mov     dword ptr [{DIRTY:#x}], 1\n"
        return f"""
    call    {a['t_pw_shrink']:#x}
{repush}    cmp     dword ptr [{G:#x}], 0x10
    jle     nf
    mov     dword ptr [esp+{4 * (n - 1):#x}], 1
nf:
    call    tr
{dirty}    call    {a['t_pw_exit']:#x}
    ret     {4 * n:#x}
tr:
    push    ebp
    mov     ebp, esp
    sub     esp, 0x14
    push    {back:#x}
    ret
"""
    raise KeyError(name)


def _assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def layout() -> dict:
    """{name: (pcave2 offset, bytes)}.  Pass 1 sizes with placeholder externals (every external is a CALL rel32 or a
    PUSH imm32 / RET, so sizes do not depend on the targets); pass 2 assembles at the real addresses."""
    dummy = {n: PCAVE2 + 0x100000 for n, _ in FUNCS}
    offs, cur = {}, {k: v[0] for k, v in SLOTS.items()}
    for name, slot in FUNCS:
        size = len(_assemble(asm(name, dummy), PCAVE2 + cur[slot]))
        offs[name] = cur[slot]
        cur[slot] = (cur[slot] + size + 0xF) & ~0xF
    for slot, (o, end) in SLOTS.items():
        assert cur[slot] <= end + 0xF and all(offs[n] + 0 < end for n, s in FUNCS if s == slot), slot
    addr = {n: PCAVE2 + o for n, o in offs.items()}
    out = {}
    for name, slot in FUNCS:
        b = _assemble(asm(name, addr), addr[name])
        end = SLOTS[slot][1]
        assert offs[name] + len(b) <= end, f"{name} overflows its slot ({offs[name] + len(b):#x} > {end:#x})"
        out[name] = (offs[name], b)
    names = [n for n, _ in FUNCS]
    for i, n in enumerate(names):
        for m in names[i + 1:]:
            (o1, b1), (o2, b2) = out[n], out[m]
            assert o1 + len(b1) <= o2 or o2 + len(b2) <= o1, (n, m)
    assert all(o + len(b) <= DATA_OFF or o >= DATA_OFF + DATA_SIZE for o, b in out.values())
    return out


def site_bytes(va: int, kind: str, n: int, addr: dict) -> bytes:
    op, tgt = kind.split(":")
    b = bytes([0xE9 if op == "jmp" else 0xE8]) + ((addr[tgt] - (va + 5)) & 0xFFFFFFFF).to_bytes(4, "little")
    return b + b"\x90" * (n - 5)


def _tpl(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b).replace("40 87 66 00", "{abs32:g_popup_scale_num}")


def main() -> int:
    lay = layout()
    addr = {n: PCAVE2 + o for n, (o, _b) in lay.items()}
    print(f"  g_pw_state:                    {{ cave: pcave2, offset: {DATA_OFF:#x}, size: {DATA_SIZE} }}   # depth, on, dirty, saved canvas clip/bounds/w/h")
    for name, (o, b) in lay.items():
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {o:#x} }}   # {len(b)}B")
    for name, (o, b) in lay.items():
        print(f"      - id: {name}\n        offset: {o:#x}\n        bytes: \"{_tpl(b)}\"")
    for sid, (va, orig, kind, n) in SITES.items():
        print(f"  site {sid} {va:#x} orig {orig} -> {' '.join(f'{x:02X}' for x in site_bytes(va, kind, n, addr))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
