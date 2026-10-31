# Regenerates the W10S armed NON-RAIL scrollbar helpers in pcave2 0x3E700..0x3EBBF (2026-10-27 wave-10 W10S, F56, the
# user-approved fix: "a regression from vanilla -- pristine thumbs are 1|1 in their bars"; v4/v5 = CENTRING ONLY, the user's
# decision of 2026-10-27; laws scaling_laws.sb_nonrail_gate / sb_nonrail_grip_rect / sb_arrow_plate / sb_nonrail_arrow,
# on rail_grip_span + mirror_nn_src; guards tests/test_nonrail_sb_asm_parity.py, tests/test_scaling_nonrail_sb_laws.py
# and tests/test_scaling_nonrail_sb_e2e.py).
#
# The armed scrollbars OUTSIDE the rail family (the four Prefs Audio / Visual sliders and uimod.dll's, the MP lobby
# chat, the base FACILITIES / SUPPORTED lists, the popup heap list bars, the HQ report's left list ...) lay their thumb
# grip and both arrow plates on ONE span, centred in the bar, on both axes (the sliders are horizontal):
#
#   t_nrs_gate   CALL helper, eax = an object -> ZF = 1 iff sb_nonrail_gate: g > 16, it is a ScrollBar (its vtable's
#                +0x34 is ScrollBar_on_resize -- the exe's vtable and uimod.dll's private copies alike) and it is NOT a
#                rail-family identity (t_rsb_israil's list -- the ProdPicker / ReportWin statics, FileDlg+0x3DD8,
#                PartPicker+0xA14, Popup+0x3230 of their parents -- fitted or not).  Every register kept.
#   t_nrs_grip   t_rsb_grip's non-rail tail (was `push t_sbt_grip; ret`; t_sbt_grip's contract, esi = the ScrollBar in
#                ScrollBar_draw, ecx = the grip Sprite, the thumb rect L/T/R/B at [esp+0x28..]): a gated bar's plain
#                memory grip (t_rsb_grip's sprite guards) is laid by sb_nonrail_grip_rect -- (ox, w) =
#                rail_grip_span(R - L, sw, g), (oy, h) = rail_grip_span(B - T, sh, g) (t_rsb_wspan) -- and drawn by
#                t_rsb_gripdraw (mirror-exact, keyed, its pair restriped); anything else -> t_sbt_grip, stack untouched.
#   t_nrs_zoom   t_rsb_zoom's non-rail tail (was `push thunk_btn_bandstripe; ret` after fwd_pop; the KSB contract RET
#                0x2C, esi = the FlatButton): an arrow (+0xAAC / +0x15F8) of a gated bar is zoomed in place by
#                sb_nonrail_arrow v5 -- the native plate square [c0, c0 + F) on rail_grip_span(aw, F, g) on both axes,
#                its pixels a plain NN of the plate at its new size (the deployed keyed stretch's centre-NN with the
#                mirror-exact tie-break, mirror_nn_src / t_rsb_mnn), key margins; anything else (and every
#                guard) -> thunk_btn_bandstripe with the stack and registers untouched.  It cannot hand the existing
#                stretch the new rect: thunk_keyed_stretch_blit copies out KEYED (its key pixels leave the dest as it
#                was), so an in-place stretch of the plate alone would leave the old native pixels in the margins and
#                under the plate's key corners.
#
# Cells (BSS, zero-init; non-reentrant UI draw; sides <= MAXN = 128): g_nrs_ct 128 B (the table, dest index -> native
# index, 0xFF = key), g_nrs_row 128 B (the native row copy).
#
# Usage: py assemble_nonrail_sb.py   -> prints the yaml symbol + content lines
from __future__ import annotations

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

import assemble_rail_sym as RS

PCAVE2 = 0xA0C000
REGION = (0x3E700, 0x3F000)                        # W10S's pcave2 region

SENT = {
    "g_popup_scale_num": 0x7EAD0100,
    "t_rsb_wspan": 0x7EAD0300,
    "t_rsb_mnn": 0x7EAD0400,
    "t_rsb_gripdraw": 0x7EAD0500,
    "t_sbt_grip": 0x7EAD0600,
    "thunk_btn_bandstripe": 0x7EAD0700,
}

LAYOUT = {
    "t_nrs_gate": (0x3E700, 0x3E780),
    "t_nrs_grip": (0x3E780, 0x3E820),
    "t_nrs_zoom": (0x3E820, 0x3EAC0),
}
CELLS = {"g_nrs_ct": (0x3EAC0, 0x80), "g_nrs_row": (0x3EB40, 0x80)}
MAXN = 0x80                        # native / dest arrow side bound (the tables): every armed bar's arrow is <= 50 px
ORDER = list(LAYOUT)

SB_ON_RESIZE, SB_ON_RESIZE_SLOT = 0x606860, 0x34
SB_UP, SB_DN = RS.SB_UP, RS.SB_DN
KEY = 9


def va(name: str) -> int:
    if name in LAYOUT:
        return PCAVE2 + LAYOUT[name][0]
    if name in CELLS:
        return PCAVE2 + CELLS[name][0]
    return SENT[name]


# NO comments inside the asm text (keystone hangs on `;`); the notes live in the docstrings.

def asm_gate() -> str:
    """eax = obj -> ZF.  The rail identities exactly as t_rsb_israil lists them (its statics, then the parent-keyed
    members), without its fit test: an unfitted family bar keeps its old paths too.  A null vtable / parent vtable is
    not a ScrollBar / not a family parent."""
    G = va("g_popup_scale_num")
    return f"""
    push ecx
    push edx
    cmp dword ptr [{G:#x}], 0x10
    jle no
    mov ecx, dword ptr [eax]
    test ecx, ecx
    je no
    cmp dword ptr [ecx+{SB_ON_RESIZE_SLOT:#x}], {SB_ON_RESIZE:#x}
    jne no
    cmp eax, {RS.PICKER_SB:#x}
    je no
    cmp eax, {RS.REPORT_SB:#x}
    je no
    mov ecx, dword ptr [eax+0xC4]
    test ecx, ecx
    je yes
    lea edx, [ecx+{RS.PARTPICKER_SB:#x}]
    cmp eax, edx
    jne not_pp
    cmp dword ptr [ecx], {RS.PARTPICKER_VTBL:#x}
    je no
not_pp:
    lea edx, [ecx+0x3DD8]
    cmp eax, edx
    jne not_fd
    cmp dword ptr [ecx], {RS.FILEDLG_VTBL:#x}
    je no
not_fd:
    lea edx, [ecx+0x3230]
    cmp eax, edx
    jne yes
    mov edx, dword ptr [ecx]
    test edx, edx
    je yes
    cmp dword ptr [edx+4], {RS.POPUP_SHOW:#x}
    je no
yes:
    cmp eax, eax
    pop edx
    pop ecx
    ret
no:
    test esp, esp
    pop edx
    pop ecx
    ret
"""


def asm_grip() -> str:
    """Entry = t_sbt_grip's: [esp] ScrollBar_draw's return, +4 dest, +8 key, +0xC x, +0x10 y, +0x14 num, +0x18 den,
    ecx = the grip Sprite, esi = the ScrollBar; the thumb rect L/T/R/B at [esp+0x28/0x2C/0x30/0x34].  After pushad (ebp
    = esp): args +0x24.., rect +0x48/+0x4C/+0x50/+0x54.  t_rsb_grip's sprite guards (pcBits set, no draw offsets, blit
    dims == canvas dims, w <= 256); each span must fit (w > 0, off >= 0) and w <= 256 (t_rsb_gripdraw's table).
    Out: x, y, w (the num slot), h (the den slot) -> t_rsb_gripdraw."""
    return f"""
    push eax
    mov eax, esi
    call {va("t_nrs_gate"):#x}
    pop eax
    jne pass_on
    pushad
    mov ebp, esp
    cmp dword ptr [ecx+4], 0
    je refuse
    cmp dword ptr [ecx+0x20], 0
    jne refuse
    cmp dword ptr [ecx+0x24], 0
    jne refuse
    mov ebx, dword ptr [ecx+0x18]
    cmp ebx, dword ptr [ecx+0x10]
    jne refuse
    mov edx, dword ptr [ecx+0x1C]
    cmp edx, dword ptr [ecx+0x14]
    jne refuse
    test edx, edx
    jle refuse
    test ebx, ebx
    jle refuse
    cmp ebx, 0x100
    jg refuse
    mov esi, ecx
    mov eax, ebx
    mov ecx, dword ptr [ebp+0x50]
    sub ecx, dword ptr [ebp+0x48]
    call {va("t_rsb_wspan"):#x}
    test eax, eax
    jle refuse
    test ecx, ecx
    js refuse
    cmp eax, 0x100
    jg refuse
    add ecx, dword ptr [ebp+0x48]
    mov edi, ecx
    mov ebx, eax
    mov eax, dword ptr [esi+0x1C]
    mov ecx, dword ptr [ebp+0x54]
    sub ecx, dword ptr [ebp+0x4C]
    call {va("t_rsb_wspan"):#x}
    test eax, eax
    jle refuse
    test ecx, ecx
    js refuse
    add ecx, dword ptr [ebp+0x4C]
    mov dword ptr [ebp+0x2C], edi
    mov dword ptr [ebp+0x30], ecx
    mov dword ptr [ebp+0x34], ebx
    mov dword ptr [ebp+0x38], eax
    popad
    push {va("t_rsb_gripdraw"):#x}
    ret
refuse:
    popad
pass_on:
    push {va("t_sbt_grip"):#x}
    ret
"""


def asm_zoom() -> str:
    """v5 (USER DECISION 2026-10-27: centring only).  Entry (KSB contract, RET 0x2C): +4 dst buf, +8 src buf, +0xC sx,
    +0x10 sy, +0x14 wn, +0x18 hn, +0x1C dx, +0x20 dy, +0x24 aw, +0x28 ah, +0x2C key; esi = the FlatButton.  After
    pushad (ebp = esp) the args sit at +0x24..+0x4C.
    Guards (any failure -> thunk_btn_bandstripe, untouched): an arrow of a gated bar; sx = sy = dx = dy = 0, dst ==
    src, wn == hn in 1..MAXN, aw == ah in wn..MAXN, a pixel plane, its stride >= aw; something drawn; w > 0, off >= 0;
    every table entry <= its row (the rows are written bottom-up in place, each from a native row at or above it).
    Locals (ebp-): 4 stride, 8 data, 0xC x0, 0x10 x1 (last), 0x14 y0, 0x18 y1 (last), 0x1C F, 0x20 c0, 0x24 w,
    0x28 off, 0x2C y (rows), 0x30 dest row ptr.
    The table: g_nrs_ct[k] = c0 + mirror_nn_src(k - off, F, w) (t_rsb_mnn) for k in [off, off + w) -- a plain NN of
    the plate, the deployed sampling's centre-NN with the mirror-exact tie-break (v5) --, 0xFF (key) elsewhere; the
    same table for both axes (the plate is square)."""
    CT, ROW = va("g_nrs_ct"), va("g_nrs_row")
    WS, MNN = va("t_rsb_wspan"), va("t_rsb_mnn")
    return f"""
    push eax
    push edx
    mov eax, dword ptr [esi+0xC4]
    test eax, eax
    je fwd_pop
    lea edx, [eax+{SB_UP:#x}]
    cmp esi, edx
    je is_arrow
    lea edx, [eax+{SB_DN:#x}]
    cmp esi, edx
    jne fwd_pop
is_arrow:
    call {va("t_nrs_gate"):#x}
    jne fwd_pop
    pop edx
    pop eax
    pushad
    mov ebp, esp
    sub esp, 0x40
    mov eax, dword ptr [ebp+0x2C]
    or eax, dword ptr [ebp+0x30]
    or eax, dword ptr [ebp+0x3C]
    or eax, dword ptr [ebp+0x40]
    jne bail
    mov eax, dword ptr [ebp+0x24]
    cmp eax, dword ptr [ebp+0x28]
    jne bail
    mov ecx, dword ptr [ebp+0x34]
    cmp ecx, dword ptr [ebp+0x38]
    jne bail
    test ecx, ecx
    jle bail
    cmp ecx, {MAXN:#x}
    jg bail
    mov edx, dword ptr [ebp+0x44]
    cmp edx, dword ptr [ebp+0x48]
    jne bail
    cmp edx, ecx
    jl bail
    cmp edx, {MAXN:#x}
    jg bail
    mov edi, dword ptr [ebp+0x24]
    mov ebx, dword ptr [edi+0x54]
    test ebx, ebx
    je bail
    mov eax, dword ptr [edi+0x4A8]
    cmp eax, edx
    jl bail
    mov dword ptr [ebp-4], eax
    mov dword ptr [ebp-8], ebx
    mov dword ptr [ebp-0xC], 0x7FFFFFFF
    mov dword ptr [ebp-0x10], -1
    mov dword ptr [ebp-0x14], 0x7FFFFFFF
    mov dword ptr [ebp-0x18], -1
    xor edi, edi
bb_y:
    cmp edi, dword ptr [ebp+0x34]
    jge bb_done
    mov esi, edi
    imul esi, dword ptr [ebp-4]
    add esi, dword ptr [ebp-8]
    xor ecx, ecx
bb_x:
    cmp ecx, dword ptr [ebp+0x34]
    jge bb_ny
    cmp byte ptr [esi+ecx], {KEY}
    je bb_nx
    cmp ecx, dword ptr [ebp-0xC]
    jge bb_a
    mov dword ptr [ebp-0xC], ecx
bb_a:
    cmp ecx, dword ptr [ebp-0x10]
    jle bb_b
    mov dword ptr [ebp-0x10], ecx
bb_b:
    cmp edi, dword ptr [ebp-0x14]
    jge bb_c
    mov dword ptr [ebp-0x14], edi
bb_c:
    mov dword ptr [ebp-0x18], edi
bb_nx:
    inc ecx
    jmp bb_x
bb_ny:
    inc edi
    jmp bb_y
bb_done:
    mov eax, dword ptr [ebp-0x10]
    test eax, eax
    js bail
    sub eax, dword ptr [ebp-0xC]
    inc eax
    mov ecx, dword ptr [ebp-0x18]
    sub ecx, dword ptr [ebp-0x14]
    inc ecx
    mov edx, dword ptr [ebp-0xC]
    cmp eax, ecx
    jge pl_x
    mov eax, ecx
    mov edx, dword ptr [ebp-0x14]
pl_x:
    mov dword ptr [ebp-0x1C], eax
    mov dword ptr [ebp-0x20], edx
    mov ecx, dword ptr [ebp+0x44]
    call {WS:#x}
    test eax, eax
    jle bail
    test ecx, ecx
    js bail
    mov dword ptr [ebp-0x24], eax
    mov dword ptr [ebp-0x28], ecx
    mov ebx, dword ptr [ebp-0x1C]
    mov ecx, eax
    xor edi, edi
tb_loop:
    cmp edi, dword ptr [ebp+0x44]
    jge tb_done
    mov al, 0xFF
    mov edx, edi
    sub edx, dword ptr [ebp-0x28]
    js tb_put
    cmp edx, ecx
    jge tb_put
    mov eax, edx
    call {MNN:#x}
    add eax, dword ptr [ebp-0x20]
tb_put:
    mov byte ptr [{CT:#x}+edi], al
    inc edi
    jmp tb_loop
tb_done:
    xor ecx, ecx
ip_loop:
    cmp ecx, dword ptr [ebp+0x48]
    jge ip_ok
    movzx eax, byte ptr [{CT:#x}+ecx]
    cmp eax, 0xFF
    je ip_next
    cmp eax, ecx
    jg bail
ip_next:
    inc ecx
    jmp ip_loop
ip_ok:
    mov eax, dword ptr [ebp+0x48]
    mov dword ptr [ebp-0x2C], eax
row_y:
    dec dword ptr [ebp-0x2C]
    js zdone
    mov edi, dword ptr [ebp-0x2C]
    imul edi, dword ptr [ebp-4]
    add edi, dword ptr [ebp-8]
    mov eax, dword ptr [ebp-0x2C]
    movzx eax, byte ptr [{CT:#x}+eax]
    cmp eax, 0xFF
    jne row_copy
    xor ecx, ecx
key_row:
    cmp ecx, dword ptr [ebp+0x44]
    jge row_y
    mov byte ptr [edi+ecx], {KEY}
    inc ecx
    jmp key_row
row_copy:
    imul eax, dword ptr [ebp-4]
    add eax, dword ptr [ebp-8]
    xor ecx, ecx
cp_loop:
    cmp ecx, dword ptr [ebp+0x34]
    jge cp_done
    mov dl, byte ptr [eax+ecx]
    mov byte ptr [{ROW:#x}+ecx], dl
    inc ecx
    jmp cp_loop
cp_done:
    xor ecx, ecx
px_loop:
    cmp ecx, dword ptr [ebp+0x44]
    jge row_y
    movzx eax, byte ptr [{CT:#x}+ecx]
    mov dl, {KEY}
    cmp eax, 0xFF
    je px_put
    mov dl, byte ptr [{ROW:#x}+eax]
px_put:
    mov byte ptr [edi+ecx], dl
    inc ecx
    jmp px_loop
zdone:
    mov esp, ebp
    popad
    ret 0x2C
bail:
    mov esp, ebp
    popad
    push {va("thunk_btn_bandstripe"):#x}
    ret
fwd_pop:
    pop edx
    pop eax
    push {va("thunk_btn_bandstripe"):#x}
    ret
"""


ASM = {"t_nrs_gate": asm_gate, "t_nrs_grip": asm_grip, "t_nrs_zoom": asm_zoom}


def assemble(name: str, resolve: dict[str, int] | None = None) -> bytes:
    """The thunk's bytes at its pcave2 VA.  `resolve` maps sentinel names to real VAs (a bake's symbol table) for
    execution; without it the sentinels stay in (template use)."""
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
    """The yaml bytes: sentinels / the region's own thunks -> {abs32:NAME} (a disp32 / imm32 / push) or {rel32:NAME}
    (after E8 only); the cells -> {abs32:NAME}."""
    off, _end = LAYOUT[name]
    b = assemble(name)
    base = PCAVE2 + off
    rev = {v: k for k, v in SENT.items()}
    rev.update({PCAVE2 + o: n for n, (o, _e) in LAYOUT.items()})
    cells = {PCAVE2 + o: n for n, (o, _sz) in CELLS.items()}
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
    for s in SENT.values():                        # no sentinel survives as raw bytes
        assert s.to_bytes(4, "little").hex(" ").upper() not in tpl, (name, hex(s))
    for o, _sz in CELLS.values():                  # nor a cell address
        assert (PCAVE2 + o).to_bytes(4, "little").hex(" ").upper() not in tpl, (name, hex(o))
    return tpl


def main() -> int:
    for name in ORDER:
        off, end = LAYOUT[name]
        b = assemble(name)
        print(f"; {name} {len(b)} B @{off:#x}..{off + len(b):#x} (slot to {end:#x})")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{template(name)}\"")
    for n, (o, sz) in CELLS.items():
        print(f"  {n + ':':<31}{{ cave: pcave2, offset: {o:#x}, size: {sz:#x} }}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
