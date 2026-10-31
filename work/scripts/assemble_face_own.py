"""Own-top FlatButton face stripes (W9A, 2026-10-27).

PORTS OF scaling_laws.py (the SOURCE OF TRUTH; regenerate the yaml bytes from here, never hand-edit):

  t_face_own      own_top_face + own_face_stripe_phase + flatbutton_draw_state   (helper, pcave2 0x3E640)

User decisions 2026-10-27 (W9A): every PrefWin FlatButton face, and the Social Engineering screen's right column, anchors
its stripes to its OWN top like vanilla -- the "ownc" law (open with vanilla's row-0 colour: the pair's top member AE /
E0 normally, its mate E1 when pressed; close on the other member where the face height allows).  Every other FlatButton
keeps the parent grid (thunk_btn_stripes v13), byte-identical in behaviour; g <= 16 never reaches it.  (The Off toggles'
row spacing stays as deployed: the user dropped W9A's label-column pitch, 2026-10-27.)

t_face_own -- helper.  In: edx = a FlatButton.  Out: CF = 1 and edx = its own-top phase in [0, P) when it is an
  own_top_face (parent [+0xC4] == PrefWin_g, or edx in the SE society column [0x8B829C, +10 * 0xB4C)); CF = 0 and edx
  unchanged otherwise.  Every other register preserved.  The face height is its canvas's (-[+0x4C8]: the device height,
  restored by thunk_btn_2dscale before its stripes chain runs and the canvas SE's restripe reads); T = P / 2 from the
  cell g_stripe_period (P >= 2 whenever a caller runs: both gate on g > 16).  The phase loop is the law's search
  narrowed to the phases that open on the top member (ph < T: the first run is T - ph, the last row's position in the
  period q = (h - 1 + ph) mod P must be >= T, the last run q - T + 1); ascending ph with a strict `>` keeps the longer
  first run on a tie.  The draw state is FlatButton_content_draw's (flatbutton_draw_state); state 2 adds T.
  Callers: thunk_btn_stripes v14 (assemble_popup_sb.py, its plain fe path: `mov edx, esi / call t_face_own / mov eax,
  edx / jc phok`, else the v13 parent-local top) and thunk_se_rowdraw_ph v2 (assemble_se.py, the SE face restripe's
  vtable entry: `call t_face_own / jc ok`, else the parent-local top).

Placement: pcave2 0x3E640 in W9A's region 0x3E640..0x3EFFF (cave_map --at 0x3E640: free from t_pref_tabrow's end
0x3E63A to t_rw_ring 0x3F000).

Usage: assemble_face_own.py   -> prints the yaml content entries
"""
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

import scaling_laws as SL

PCAVE2 = 0xA0C000
T_FACE_OWN_OFF, REGION_END = 0x3E640, 0x3F000
T_FACE_OWN = PCAVE2 + T_FACE_OWN_OFF
G_STRIPE_PERIOD = 0x66879C
PREFWIN = 0x8578D8
OFF_STATE, OFF_HOVER, OFF_PRESS_A, OFF_PRESS_B = 0xAB8, 0xA74, 0xA18, 0xA9C
assert SL.OWN_FACE_PARENT == PREFWIN and SL.FLATBUTTON_SIZE == 0xB4C


def asm_face_own() -> str:
    return f"""
        cmp  edx, {SL.SE_OWN_FACE_LO:#x}
        jb   pref
        cmp  edx, {SL.SE_OWN_FACE_HI:#x}
        jb   own
    pref:
        cmp  dword ptr [edx + 0xC4], {PREFWIN:#x}
        je   own
        clc
        ret
    own:
        pushad
        mov  ecx, dword ptr [{G_STRIPE_PERIOD:#x}]
        mov  ebx, ecx
        shr  ebx, 1
        xor  ebp, ebp
        test ebx, ebx
        jz   state
        mov  edi, dword ptr [edx + 0x4C8]
        neg  edi
        dec  edi
        jl   state
        push 0
        xor  esi, esi
    lp:
        cmp  esi, ebx
        jae  ldone
        lea  eax, [edi + esi]
        xor  edx, edx
        div  ecx
        cmp  edx, ebx
        jb   nxt
        sub  edx, ebx
        inc  edx
        mov  eax, ebx
        sub  eax, esi
        cmp  eax, edx
        jbe  mn
        mov  eax, edx
    mn:
        cmp  eax, dword ptr [esp]
        jbe  nxt
        mov  dword ptr [esp], eax
        mov  ebp, esi
    nxt:
        inc  esi
        jmp  lp
    ldone:
        add  esp, 4
    state:
        mov  esi, dword ptr [esp + 0x14]
        mov  eax, dword ptr [esi + {OFF_STATE:#x}]
        cmp  eax, 3
        jb   havest
        mov  eax, 2
        cmp  dword ptr [esi + {OFF_PRESS_B:#x}], 0
        jne  havest
        cmp  dword ptr [esi + {OFF_PRESS_A:#x}], 0
        jne  havest
        xor  eax, eax
        cmp  dword ptr [esi + {OFF_HOVER:#x}], 0
        setne al
    havest:
        cmp  eax, 2
        jne  wr
        add  ebp, ebx
    wr:
        mov  dword ptr [esp + 0x14], ebp
        popad
        stc
        ret
    """


THUNKS = (("t_face_own", asm_face_own, T_FACE_OWN, PCAVE2 + REGION_END),)


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def to_template(b: bytes) -> str:
    """No placeholders: every operand is a button field or the fixed cell g_stripe_period; branches are internal."""
    return " ".join(f"{x:02X}" for x in b)


def build() -> dict:
    """name -> (va, bytes, yaml template)."""
    out = {}
    for name, fn, va, end in THUNKS:
        b = assemble(fn(), va)
        assert va + len(b) <= end, f"{name} {len(b)} B overflows its slot ({end - va} B)"
        out[name] = (va, b, to_template(b))
    return out


def main() -> int:
    for name, (va, b, tmpl) in build().items():
        print(f"# {name}: pcave2 {va - PCAVE2:#x}, {len(b)} B (ends {va - PCAVE2 + len(b):#x})")
        print(f'        bytes: "{tmpl}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
