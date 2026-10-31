"""t_lbi_restripe_ph / t_dw_face_ph -- two more child canvases on their parent's stripe grid (2026-10-14).

Every stripe above native follows ONE grid per buffer (scaling_laws.stripe_top on the dest row), and a child
canvas whose rows are regenerated from its OWN row 0 lands a stripe off its parent wherever its parent-local
top (Win +0x140 + +0x150) is not a multiple of P.  btn_stripes v13 (FlatButton faces), t_rowbox_ph (popup
option rows) and thunk_se_rowdraw_ph (SE faces) already phase from that top; two writers still did not:

  (1) the CHOOSE YOUR FACTIONS name list -- t_lb_item_stripes (assemble_tileforce.py) restripes the ListBox
      canvas through t_tf_restripe -> thunk_fe_pair_remap with g_rm_yph = 0, while the in-list gaps are the
      Buffer_copy_4 capture of FactionPickWin's canvas.  Rows one stripe off at 4K (list top 335, shot
      20261011-200837) and 1600x1200 (209, 20261006-222044); on the grid at 1920x1080 (184, 20261006-222202).
      t_lbi_restripe_ph wraps t_tf_restripe (same thiscall(dest)(l,t,r,b) RET 0x10): g_rm_yph = the canvas's
      parent-local top reduced to [0, P) (dest = Win+0x444, so the fields are [ecx-0x304] + [ecx-0x2F4]),
      call, clear.  t_lb_item_stripes' one restripe call is retargeted to it (same 5 bytes).  Law
      scaling_laws.faction_list_stripe_phase.  Only t_lb_item_stripes reaches it, and only while
      g_faction_active and g > 16 (P valid).
  (2) the Design Workshop's buttons -- thunk_dw_btnface is the SE face restripe built phased=False.  Built
      phased=True its 5 stripe rows go through thunk_se_stripe_px_ph (y + g_se_yph); t_dw_face_ph is
      thunk_se_rowdraw_ph's staging verbatim with the tail retargeted to thunk_dw_btnface, and thunk_dw_btndraw's
      `jmp thunk_dw_btnface` now lands on it (short -> near jmp, +3 B inside its 5 B of alignment slack).
      Measured 1920x1080 (20261006-201336): DONE row one stripe off, APPLY on the grid.  Ids 0..8 are
      DesignWin's children; the 14 presets (9..0x16) and the slot-strip arrows (0x17/0x18) are MainWin_g's, so
      they phase by their MainWin-local top (presets on the console grid today: phase 0, unchanged).  Law
      scaling_laws.dw_button_face_stripe_phase.  g_se_yph is shared with SocialWin: both stage it on every
      draw before the only reader runs, and the two screens are never drawn inside each other.

Usage: assemble_list_face_phase.py      -> prints the yaml symbol + content lines
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
OFF, END = 0x3730, 0x37A0           # cave_map --fit: 0x3721..0x37A0 free (the old thunk_popup_nestpads v2 slot's tail)
OFF_DW, END_DW = 0x2F5C0, 0x2F600   # t_dw_face_ph: cave_map --fit 64: free between t_ntw_nostripe and g_bmo_farx
G = 0x00668740                      # g_popup_scale_num
G_STRIPE_PERIOD = 0x0066879C        # g_stripe_period
G_RM_YPH = PCAVE2 + 0x103FC         # thunk_fe_pair_remap v8 row-phase cell
G_SE_YPH = PCAVE2 + 0x2FFFC         # thunk_se_stripe_px_ph's phase cell
T_TF_RESTRIPE = PCAVE2 + 0x27AA0    # assemble_tileforce t_tf_restripe (thiscall(dest)(l,t,r,b) RET 0x10)
DW_BTNFACE = PCAVE2 + 0x17E70       # assemble_dw thunk_dw_btnface
VA_LBI, VA_DW = PCAVE2 + OFF, PCAVE2 + OFF_DW

ABS = {G: "{abs32:g_popup_scale_num}", G_STRIPE_PERIOD: "{abs32:g_stripe_period}", G_RM_YPH: "{abs32:g_rm_yph}",
       G_SE_YPH: "{abs32:g_se_yph}"}
REL = {T_TF_RESTRIPE: "{rel32:t_tf_restripe}"}


def asm_lbi_restripe_ph() -> str:
    return f"""
    push    eax
    push    edx
    mov     eax, dword ptr [ecx-0x304]
    add     eax, dword ptr [ecx-0x2F4]
    cdq
    idiv    dword ptr [{G_STRIPE_PERIOD:#x}]
    test    edx, edx
    jge     ok
    add     edx, dword ptr [{G_STRIPE_PERIOD:#x}]
ok:
    mov     dword ptr [{G_RM_YPH:#x}], edx
    pop     edx
    pop     eax
    push    dword ptr [esp+0x10]
    push    dword ptr [esp+0x10]
    push    dword ptr [esp+0x10]
    push    dword ptr [esp+0x10]
    call    {T_TF_RESTRIPE:#x}
    and     dword ptr [{G_RM_YPH:#x}], 0
    ret     0x10
"""


def asm_dw_face_ph() -> str:
    import assemble_se as SE
    src = SE.asm_se_rowdraw_ph(own=False)   # W9A's own-top ask is SE's society column only; the DW copy keeps the parent grid
    old = "jmp     thunk_se_rowdraw\n"
    assert src.count(old) == 1, "asm_se_rowdraw_ph tail changed"
    return src.replace(old, f"jmp     {DW_BTNFACE:#x}\n")


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def to_template(b: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):   # {rel32:} only after E8; the E9 to thunk_dw_btnface stays raw (fixed VA)
            tgt = (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in REL:
                out += [f"{b[i]:02X}", REL[tgt]]
                i += 5
                continue
        if i + 4 <= len(b) and int.from_bytes(b[i:i + 4], "little") in ABS:
            out.append(ABS[int.from_bytes(b[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


def build() -> dict:
    lbi = assemble(asm_lbi_restripe_ph(), VA_LBI)
    dw = assemble(asm_dw_face_ph(), VA_DW)
    assert OFF + len(lbi) <= END, f"t_lbi_restripe_ph {len(lbi)}B overflows its slot"
    assert OFF_DW + len(dw) <= END_DW, f"t_dw_face_ph {len(dw)}B overflows its slot"
    return {"t_lbi_restripe_ph": (OFF, lbi), "t_dw_face_ph": (OFF_DW, dw)}


def main() -> int:
    for name, (off, b) in build().items():
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {len(b)}B")
    for name, (off, b) in build().items():
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{to_template(b, PCAVE2 + off)}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
