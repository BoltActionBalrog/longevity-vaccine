"""Assemble the MENU dropdown strip column map (W9C F55, 2026-10-27): PORT of scaling_laws.menu_strip_zones /
menu_strip_col_map / menu_strip_synth.  Guards: tests/test_menu_strip_asm_parity.py (these bytes under the real image
against the laws), tests/test_scaling_menu_dropdown_lines.py (the real MENU widget drawn end to end).

The in-game MENU dropdown (g_console_menu_win 0x9380DC, buffer 0x938520) stacks menu2.pcx strips (title 139 x 6, rows
139 x 18) drawn by Sprite_draw_2 -> thunk_hudmenu_sd2 -> (post-blit) hm_synth_core, whose floor-NN column DDA at
(sc(18), 18) left the side lines 1 | 2 px wide and the rows 1-2 px off the window width.  Now:

  t_mc_synth  thunk_hudmenu_sd2's post-blit call (was `call hm_synth_core`), stdcall (dst, dx, dy, num, den, spr) RET
              0x18.  dst == the MENU buffer 0x938520, g > 16 and the sprite's blit width [spr+0x10] == 139: the zone
              layout menu_strip_zones(g) into g_mc_w / g_mc_r (= W - b) / g_mc_i / g_mc_k / g_mc_m, g_mc_on = 1, the
              core called with the same six args, g_mc_on = 0.  Anything else: a tail jump to hm_synth_core with the
              stack untouched.  eax / ecx / edx are the core's (dead at the caller); ebx / esi / edi / ebp kept.
  t_mc_dims   CALL helper in hm_synth_core (its dest-width block, same length + nops): eax = (sw * num + den / 2) /
              den exactly as the block computed it, or g_mc_w while g_mc_on; stored to the core's [ebp-0x2C].
              edx is clobbered as the block clobbered it.
  t_mc_col    CALL helper in hm_synth_core's column loop (same length + nops): eax = the DDA column ebx clamped to
              sw - 1 exactly as the block did, or, while g_mc_on, menu_strip_col_map(j) for j = x - dx (edx = x,
              [ebp+0xC] = dx): j >= W - b -> 138; else the left half (j <= R - 1 - j) zone by zone -- fill
              mirror_nn(j, 4, i), line 4, interior 5 + mirror_nn(j - i - K, 128, M) -- and the right half 137 - left(R
              - 1 - j); mirror_nn is t_rsb_mnn (eax = k, ebx = src_n, ecx = dst_n).  ebx / ecx / edx / esi / edi kept.
Cells (BSS): g_mc_on, g_mc_w, g_mc_r, g_mc_i, g_mc_k, g_mc_m (pcave2 0x3F200..0x3F218).

Usage: py assemble_menu_strip.py -> the yaml content + symbol lines.
"""
from __future__ import annotations

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard)

import assemble_hudmenu_scale as HM

PCAVE2 = 0xA0C000
REGION = (0x3F1F5, 0x3F400)                        # W9C's pcave2 region A
SENT = {"g_popup_scale_num": 0x7EAD0100, "hm_synth_core": 0x7EAD0200, "t_rsb_mnn": 0x7EAD0300}
LAYOUT = {"t_mc_dims": (0x3F220, 0x3F250), "t_mc_col": (0x3F250, 0x3F2E0), "t_mc_synth": (0x3F2E0, 0x3F400)}
CELLS = {"g_mc_on": 0x3F200, "g_mc_w": 0x3F204, "g_mc_r": 0x3F208, "g_mc_i": 0x3F20C, "g_mc_k": 0x3F210,
         "g_mc_m": 0x3F214}
MENU_BUF = HM.MENU_BUF
assert (HM.T_MC_DIMS, HM.T_MC_COL, HM.T_MC_SYNTH) == tuple(PCAVE2 + LAYOUT[n][0]
                                                         for n in ("t_mc_dims", "t_mc_col", "t_mc_synth"))


def va(name: str) -> int:
    if name in LAYOUT:
        return PCAVE2 + LAYOUT[name][0]
    if name in CELLS:
        return PCAVE2 + CELLS[name]
    return SENT[name]


def asm_dims() -> str:
    return f"""
    mov eax, dword ptr [ebp-0x10]
    imul eax, dword ptr [ebp+0x14]
    mov edx, ecx
    sar edx, 1
    add eax, edx
    xor edx, edx
    div ecx
    cmp dword ptr [{va("g_mc_on"):#x}], 0
    je dims_keep
    mov eax, dword ptr [{va("g_mc_w"):#x}]
dims_keep:
    mov dword ptr [ebp-0x2C], eax
    ret
"""


def asm_col() -> str:
    on, r, i, k, m = (va(n) for n in ("g_mc_on", "g_mc_r", "g_mc_i", "g_mc_k", "g_mc_m"))
    mnn = va("t_rsb_mnn")
    return f"""
    cmp dword ptr [{on:#x}], 0
    jne col_law
    mov eax, ebx
    cmp eax, dword ptr [ebp-0x10]
    jl col_ret
    mov eax, dword ptr [ebp-0x10]
    dec eax
col_ret:
    ret
col_law:
    push ebx
    push ecx
    push edx
    mov eax, edx
    sub eax, dword ptr [ebp+0xC]
    mov edx, dword ptr [{r:#x}]
    cmp eax, edx
    jl col_body
    mov eax, {0x8A:#x}
    jmp col_out
col_body:
    lea ecx, [edx-1]
    sub ecx, eax
    xor edx, edx
    cmp eax, ecx
    jle col_left
    mov eax, ecx
    inc edx
col_left:
    push edx
    mov ecx, dword ptr [{i:#x}]
    cmp eax, ecx
    jge col_nofill
    mov ebx, 4
    call {mnn:#x}
    jmp col_got
col_nofill:
    sub eax, ecx
    cmp eax, dword ptr [{k:#x}]
    jge col_int
    mov eax, 4
    jmp col_got
col_int:
    sub eax, dword ptr [{k:#x}]
    mov ebx, {0x80:#x}
    mov ecx, dword ptr [{m:#x}]
    call {mnn:#x}
    add eax, 5
col_got:
    pop edx
    test edx, edx
    jz col_out
    neg eax
    add eax, {0x89:#x}
col_out:
    pop edx
    pop ecx
    pop ebx
    ret
"""


def asm_synth() -> str:
    """Zones (menu_strip_zones): W = (139 g + 8) >> 4, K = b = (2 g + 15) >> 5, R = W - b; i = 1.. ascending while
    M = R - 2 i - 2 K > 0, key (max(dF, dI), dF + dI, dF) strictly smaller replaces (an exact tie keeps the smaller i),
    dF = |16 i - 4 g|, dI = |16 M - 128 g|.  Frame: pushad, ebp = esp (args +0x24..+0x38); -4 best max, -8 best sum,
    -0xC best dF."""
    G = va("g_popup_scale_num")
    on, w, r, i, k, m = (va(n) for n in ("g_mc_on", "g_mc_w", "g_mc_r", "g_mc_i", "g_mc_k", "g_mc_m"))
    absv = """
    cdq
    xor eax, edx
    sub eax, edx"""
    return f"""
    cmp dword ptr [esp+4], {MENU_BUF:#x}
    jne syn_pass
    cmp dword ptr [{G:#x}], 0x10
    jle syn_pass
    mov eax, dword ptr [esp+0x18]
    test eax, eax
    je syn_pass
    cmp dword ptr [eax+0x10], {0x8B:#x}
    je syn_menu
syn_pass:
    push {va("hm_synth_core"):#x}
    ret
syn_menu:
    pushad
    mov ebp, esp
    sub esp, 0x10
    mov ecx, dword ptr [{G:#x}]
    imul eax, ecx, {0x8B:#x}
    add eax, 8
    sar eax, 4
    mov dword ptr [{w:#x}], eax
    lea edx, [ecx*2+15]
    sar edx, 5
    mov dword ptr [{k:#x}], edx
    sub eax, edx
    mov dword ptr [{r:#x}], eax
    mov dword ptr [ebp-4], 0x7FFFFFFF
    mov dword ptr [{i:#x}], 1
    mov esi, 1
syn_try:
    mov edi, dword ptr [{r:#x}]
    mov eax, esi
    add eax, dword ptr [{k:#x}]
    add eax, eax
    sub edi, eax
    jle syn_chosen
    mov eax, esi
    shl eax, 4
    mov edx, ecx
    shl edx, 2
    sub eax, edx{absv}
    mov ebx, eax
    mov eax, edi
    shl eax, 4
    mov edx, ecx
    shl edx, 7
    sub eax, edx{absv}
    mov edx, eax
    add edx, ebx
    cmp eax, ebx
    jge syn_max
    mov eax, ebx
syn_max:
    cmp eax, dword ptr [ebp-4]
    jl syn_take
    jg syn_next
    cmp edx, dword ptr [ebp-8]
    jl syn_take
    jg syn_next
    cmp ebx, dword ptr [ebp-0xC]
    jge syn_next
syn_take:
    mov dword ptr [ebp-4], eax
    mov dword ptr [ebp-8], edx
    mov dword ptr [ebp-0xC], ebx
    mov dword ptr [{i:#x}], esi
    mov dword ptr [{m:#x}], edi
syn_next:
    inc esi
    jmp syn_try
syn_chosen:
    mov dword ptr [{on:#x}], 1
    push dword ptr [ebp+0x38]
    push dword ptr [ebp+0x34]
    push dword ptr [ebp+0x30]
    push dword ptr [ebp+0x2C]
    push dword ptr [ebp+0x28]
    push dword ptr [ebp+0x24]
    call {va("hm_synth_core"):#x}
    mov dword ptr [{on:#x}], 0
    mov esp, ebp
    popad
    ret 0x18
"""


ASM = {"t_mc_dims": asm_dims, "t_mc_col": asm_col, "t_mc_synth": asm_synth}
ORDER = list(LAYOUT)


def assemble(name: str, resolve: dict | None = None) -> bytes:
    src = ASM[name]()
    assert ";" not in src
    if resolve:
        for n, s in SENT.items():
            src = src.replace(f"{s:#x}", f"{resolve[n]:#x}")
    off, end = LAYOUT[name]
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(src, PCAVE2 + off)[0])
    assert REGION[0] <= off and off + len(b) <= end <= REGION[1], (name, hex(off), len(b))
    return b


def template(name: str) -> str:
    off, _end = LAYOUT[name]
    b = assemble(name)
    base = PCAVE2 + off
    rev = {v: k for k, v in SENT.items()}
    rev.update({PCAVE2 + o: n for n, (o, _e) in LAYOUT.items()})
    cells = {PCAVE2 + o: n for n, o in CELLS.items()}
    out, i = [], 0
    while i < len(b):
        if i + 4 <= len(b):
            word = int.from_bytes(b[i:i + 4], "little")
            if i >= 1 and b[i - 1] == 0xE8:
                tgt = (base + i + 4 + int.from_bytes(b[i:i + 4], "little", signed=True)) & 0xFFFFFFFF
                if tgt in rev:
                    out.append(f"{{rel32:{rev[tgt]}}}")
                    i += 4
                    continue
            if word in rev:
                out.append(f"{{abs32:{rev[word]}}}")
                i += 4
                continue
            if word in cells:
                out.append(f"{{abs32:{cells[word]}}}")
                i += 4
                continue
        out.append(f"{b[i]:02X}")
        i += 1
    tpl = " ".join(out)
    for s in SENT.values():
        assert s.to_bytes(4, "little").hex(" ").upper() not in tpl, (name, hex(s))
    return tpl


def main() -> int:
    for name in ORDER:
        off, end = LAYOUT[name]
        print(f"; {name} {len(assemble(name))} B @{off:#x} (slot to {end:#x})")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{template(name)}\"")
    for n, o in CELLS.items():
        print(f"  {n + ':':<31}{{ cave: pcave2, offset: {o:#x}, size: 4 }}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
