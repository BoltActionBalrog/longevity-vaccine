# Regenerates thunk_filedlg_insets v2 (pcave2 0x3200) — the FileDlg_layout Path B
# backdrop-rect inset scaler (group filedlg_chrome_rails, PART 2).
#
# Detoured from 0x407527 (27-byte block replaced by push/ret + NOPs); runs with
# the caller's ebp frame intact; resumes at 0x407542 (push 0x78d690).
# Vanilla deltas on the window rect before the d690 dither-backdrop draw:
#   L += 0x17 (23 = rail artW 15+8), R -= 0x37 (55 = rails 23 + scrollbar gap
#   0x20), B += 0xa. The vanilla RELATIONSHIP is backdrop-edge == rail-start on
#   both sides, so at g>16 each delta is computed with the rails' OWN floor
#   cascade, never an independent floor of the summed constant:
#   LEFT  = (15g>>4)+(8g>>4)  — the strips' composed device extent
#             (floor(23g/16) exceeds it by 1 at some g → 1px gap).
#   RIGHT = R' := L + floor((floor(bufW*16/g) − 55) * g/16), bufW from
#             [g_fd_winbuf]+0x80 — the IDENTICAL width source + double-floor
#             thunk_filedlg_railscale applies to the right strips, so the
#             backdrop's green stroke abuts the rails' left edge at ANY g.
#             (v1's plain floor(55g/16) over-shot the rail start by <=2px and
#             the rails swallowed the ~2px stroke; user-caught @1600x1200.)
#   B     = floor(10g/16).
# Exit contract (matched to the resume): edx = &rect (lea [ebp-0x1c]), eax =
# new B (the resume re-stores it into [ebp-0x10]; harmless dup), ecx clobbered
# (resume overwrites), flags dead.
#
# Usage: py assemble_filedlg_insets.py   -> prints the byte string for the
# patches.yaml cave entry (placeholders marked).
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

G_SCALE  = 0x668740     # g_popup_scale_num          -> {abs32:g_popup_scale_num}
G_WINBUF = 0xA0E5E0     # g_fd_winbuf                -> {abs32:g_fd_winbuf}
RESUME   = 0x407542     # filedlg_pathb_resume       -> {rel-free: push {abs32}/ret}
THUNK_VA = 0xA0F200     # pcave2 (0xA0C000) + 0x3200

ASM = f"""
    mov  eax, dword ptr [{G_SCALE:#x}]
    cmp  eax, 0x10
    jg   scaled
    add  dword ptr [ebp-0x1c], 0x17
    sub  dword ptr [ebp-0x14], 0x37
    mov  eax, dword ptr [ebp-0x10]
    add  eax, 0x0a
    jmp  store
scaled:
    imul ecx, eax, 15
    shr  ecx, 4
    imul edx, eax, 8
    shr  edx, 4
    add  ecx, edx
    mov  eax, dword ptr [{G_WINBUF:#x}]
    mov  eax, dword ptr [eax+0x80]
    shl  eax, 4
    xor  edx, edx
    div  dword ptr [{G_SCALE:#x}]
    sub  eax, 0x37
    imul eax, dword ptr [{G_SCALE:#x}]
    shr  eax, 4
    add  eax, dword ptr [ebp-0x1c]
    mov  dword ptr [ebp-0x14], eax
    add  dword ptr [ebp-0x1c], ecx
    mov  eax, dword ptr [{G_SCALE:#x}]
    imul ecx, eax, 10
    shr  ecx, 4
    mov  eax, dword ptr [ebp-0x10]
    add  eax, ecx
store:
    mov  dword ptr [ebp-0x10], eax
    lea  edx, [ebp-0x1c]
    push {RESUME:#x}
    ret
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)
enc, _ = ks.asm(ASM, THUNK_VA)
b = bytes(enc)
print(f"{len(b)} bytes @ {THUNK_VA:#x}")
print(" ".join(f"{x:02X}" for x in b))
