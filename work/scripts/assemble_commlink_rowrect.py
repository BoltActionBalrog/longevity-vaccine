"""thunk_comm_rowrect — COMMLINK per-faction row text rect + Spot hit-rect scaling.

Bake of the user-verified prototype hook_commlink_rows.js (4K g=40 + 1600x1200 g=25,
2026-08-15). commlink_draw_faction_row 0x478630 builds the row's text rect at
[ebp-0x24..-0x18] = {L=rect.x0+7+3, T=y, R=rect.x1-7-3, B=y+18} (native insets on a
MIXED rect: x1 = winW [+0x4c4] is already device-scaled by thunk_comm_gwinit; y is the
native 6+18k cursor) and, at the SP/MP merge point 0x4786f7, holds the same four values
in eax=L edx=T esi=R ecx=B just before pushing the type-1 Spot_add(faction,1,L,T,R-L,B-T).
Both text writes (write_l_4 @0x47884C, write_right_l_6 @0x478BD0) read the stack rect.

Detour @0x4786f7 (push/ret; displaced 6B: 2B CA 2B F0 51 56 = sub ecx,edx / sub esi,eax /
push ecx / push esi; resume 0x4786fd). One transform, from NATIVE inputs, feeds all three consumers:
    L' = sc(L)                       (sc = round(v*g/16), helper hm_sc)
    T' = rowY(T), B' = rowY(B)       (uniform row pitch, helper hm_rowY — same law that
                                      relocates the row strips in thunk_hudmenu_sbc)
    R' = W - sc(W - R)               (right inset scaled from the opposite edge; W=[ebx+0x4c4])
g<=16 -> native no-op. Idempotent: the rect is rebuilt from the native cursor every
repaint (Spot list killed + re-added each commlink_redraw). ebx=self, ebp=frame.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0x00A0C000
OFF    = 0x11500
VA     = PCAVE2 + OFF
G      = 0x668740          # g_popup_scale_num
HM_SC  = PCAVE2 + 0x5D60   # eax = round(eax*g/16), clobbers edx
HM_ROWY= PCAVE2 + 0x5D70   # eax = rowY(eax), clobbers edx (preserves ebx/ecx)
RESUME = 0x004786FD

ASM = f"""
    cmp dword ptr [{G:#x}], 16
    jle native
    push edx
    push ecx
    call {HM_SC:#x}
    mov dword ptr [ebp-0x24], eax
    push eax
    mov eax, dword ptr [ebx+0x4c4]
    sub eax, esi
    call {HM_SC:#x}
    mov esi, dword ptr [ebx+0x4c4]
    sub esi, eax
    mov dword ptr [ebp-0x1c], esi
    pop ecx
    pop eax
    call {HM_ROWY:#x}
    mov dword ptr [ebp-0x18], eax
    xchg eax, ecx
    pop edx
    push eax
    mov eax, edx
    call {HM_ROWY:#x}
    mov edx, eax
    mov dword ptr [ebp-0x20], edx
    pop eax
native:
    sub ecx, edx
    sub esi, eax
    push ecx
    push esi
    jmp {RESUME:#x}
"""

def main():
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, n = ks.asm(ASM, VA)
    b = bytes(enc)
    print(f"thunk_comm_rowrect @ pcave2+{OFF:#x} (VA {VA:#x}) {len(b)}B, {n} insns")
    print(" ".join(f"{x:02X}" for x in b))
    return b

if __name__ == "__main__":
    main()
