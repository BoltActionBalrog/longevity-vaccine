"""Assemble the popup button-row remainder distribution (fix 19, group popup_btnrow_distribute).

PORT OF: scaling_laws.py :: popup_button_row_bounds() / popup_button_row_slot()  (the SOURCE OF TRUTH;
regenerate the yaml bytes from here, never hand-edit).

VANILLA (BasePop_calculate_dimensions 0x603FD5..0x604012): button_width [+0x30CC] =
(box_w - 2*pad_x - (n-1)*gap) / n, n = [+0x30B0]; the idiv's remainder is dropped.  BasePop_exec_3 then places
the row RIGHT-anchored (x = -[+0x30F4], the content right margin; slot j from the right at x - j*(w+gap); the
engine resolves a negative x as the button's right edge = parent right + x), so the whole remainder lands on the
LEFT: the row starts 1-2 px inside the list it sits under and ends flush (4K Customize Game Rules +1, 1080p +2,
1600x900 +1; at g = 16 every measured row divides exactly).

LAW: the row keeps its span [R - T - (n-1)*gap, R) (T = n*w + rem, the calc's own numerator) and its gaps; slot i's
cell is [b(i), b(i+1)) with the mirrored remainder distribution b(k) = cum(k) for 2k <= n, T - cum(n-k) above
(scaling_laws.popup_button_row_bounds): both ends flush, widths within 1 px, symmetric whenever the remainder
allows (every odd n; even n with an even remainder).

TWO THUNKS:
  t_btnrow_stash  call-redirect of `mov [esi+0x30cc], eax` @0x604012 (6 B -> E8 rel32 90): the store, then
                  g_btnrow_popup = esi, g_btnrow_rem = edx (the idiv remainder).  Registers and flags untouched.
  t_btnrow_init   call-redirect of the three row BaseButton_init calls in BasePop_exec_3 (0x602D66 OK, id -1,
                  unless flag 0x10000; 0x6030DC the custom #button loop, ids 1..; 0x60342B Cancel, id -2, flag
                  0x40 -- the row reads [custom ...][OK][Cancel] from left to right).  g > 16, esi == g_btnrow_popup, the w arg
                  == [+0x30CC], 0 <= rem < n (unsigned: rem 0 and n = 1 are the identity by construction), x < 0
                  on the slot grid (xl - x = j*(w+gap), j < n, xl = -[+0x30F4]): x' = xl - T + b(i+1) - j*gap,
                  w' = b(i+1) - b(i), i = n-1-j.  Anything else (g <= 16, a stale stash, a left-anchored row, an
                  off-grid x) reaches BaseButton_init untouched.  pushad / popad: only the x and w args change.
  t_btnrow_bound  t_btnrow_init's CALL helper: eax = k -> b(k) (ebx = T, ecx = n).

SLOTS (cave_map --at / --fit, 2026-10-22; zero bytes, no abs32 / rel32 reference in the image): t_btnrow_stash +
g_btnrow_popup / g_btnrow_rem in 0x1020..0x1070 (g_faction_scratch_rect 0x1010 + 16 ends 0x1020), t_btnrow_init in
0x2052..0x2100 (t_slide_rail_s1 0x2020 + 50 ends 0x2052), t_btnrow_bound in 0x6DBE..0x6E00 (after t_rw_tabbtn_nath).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
STASH_OFF, INIT_OFF = 0x1020, 0x2054           # free 0x1020..0x1070 / 0x2052..0x2100 (see SLOTS)
BOUND_OFF = 0x6DC0                             # free 0x6DBE..0x6E00 after t_rw_tabbtn_nath (0x6D70, 78 B)
POPUP_OFF, REM_OFF = 0x1040, 0x1044           # g_btnrow_popup / g_btnrow_rem (data, inside the 0x1020 gap)
INIT_LIMIT = 0x2100 - INIT_OFF

SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}", 0xDEADBE10: "{abs32:BaseButton_init}",
        0xDEADBE20: "{abs32:g_btnrow_popup}", 0xDEADBE30: "{abs32:g_btnrow_rem}"}

STASH_ASM = r"""
    mov  dword ptr [esi + 0x30cc], eax   /* the displaced store: button width            */
    mov  dword ptr [0xDEADBE20], esi     /* g_btnrow_popup                               */
    mov  dword ptr [0xDEADBE30], edx     /* g_btnrow_rem = the idiv remainder            */
    ret
"""

INIT_ASM = r"""
    cmp  dword ptr [0xDEADBE00], 0x10    /* g <= 16: vanilla                             */
    jg   go
tail:
    push 0xDEADBE10                      /* BaseButton_init                              */
    ret
out:
    popad
    jmp  tail
go:
    cmp  esi, dword ptr [0xDEADBE20]     /* the popup the last calc sized                */
    jne  tail
    pushad                               /* args: x [esp+0x2c], w [esp+0x34]             */
    mov  ebx, dword ptr [esp + 0x34]
    cmp  ebx, dword ptr [esi + 0x30cc]   /* w arg == the calc's button width             */
    jne  out
    mov  ecx, dword ptr [esi + 0x30b0]   /* n                                            */
    mov  eax, dword ptr [0xDEADBE30]     /* rem                                          */
    cmp  eax, ecx
    jae  out                             /* 0 <= rem < n (so n >= 1; rem 0 = identity)   */
    mov  edi, dword ptr [esp + 0x2c]     /* x: right-anchored rows only                  */
    test edi, edi
    jns  out
    mov  ebp, ebx
    add  ebp, dword ptr [esi + 0x30e4]   /* stride w + gap                               */
    jle  out
    mov  eax, dword ptr [esi + 0x30f4]
    neg  eax                             /* xl = -right margin                           */
    sub  eax, edi                        /* d = xl - x                                   */
    jl   out
    xor  edx, edx
    div  ebp
    test edx, edx                        /* on the slot grid                             */
    jne  out
    cmp  eax, ecx
    jae  out
    mov  edi, eax                        /* j (slots from the right)                     */
    imul ebx, ecx
    add  ebx, dword ptr [0xDEADBE30]     /* T = n*w + rem                                */
    mov  eax, ecx
    sub  eax, edi                        /* i + 1 = n - j                                */
    call BOUND_VA
    mov  ebp, eax                        /* b(i+1)                                       */
    mov  eax, ecx
    sub  eax, edi
    dec  eax                             /* i                                            */
    call BOUND_VA                        /* b(i)                                         */
    neg  eax
    add  eax, ebp
    mov  dword ptr [esp + 0x34], eax     /* w' = b(i+1) - b(i)                           */
    mov  eax, edi
    imul eax, dword ptr [esi + 0x30e4]
    neg  eax
    add  eax, ebp
    sub  eax, ebx
    sub  eax, dword ptr [esi + 0x30f4]
    mov  dword ptr [esp + 0x2c], eax     /* x' = xl - T + b(i+1) - j*gap                 */
    jmp  out
"""

# t_btnrow_bound: eax = k -> b(k) (ebx = T, ecx = n; edx dies; everything else kept)
BOUND_ASM = r"""
    lea  edx, [eax + eax]
    cmp  edx, ecx
    jle  hd                              /* 2k <= n: cum(k)                              */
    neg  eax
    add  eax, ecx
    call hd
    neg  eax
    add  eax, ebx                        /* T - cum(n - k)                               */
    ret
hd:                                      /* eax = k -> half_down(k*T, n)                 */
    imul eax, ebx
    add  eax, eax
    add  eax, ecx
    dec  eax
    xor  edx, edx
    push ecx
    add  ecx, ecx
    div  ecx
    pop  ecx
    ret
"""


def assemble(src: str, va: int) -> bytes:
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, addr=va)
    return bytes(code)


def template(blob: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(blob):
        if blob[i] == 0xE8 and i + 5 <= len(blob) and \
                (va + i + 5 + int.from_bytes(blob[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF == PCAVE2 + BOUND_OFF:
            out.append("E8 {rel32:t_btnrow_bound}")
            i += 5
            continue
        for sent, name in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(name)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    return " ".join(out)


def stash_bytes() -> bytes:
    return assemble(STASH_ASM, PCAVE2 + STASH_OFF)


def init_bytes() -> bytes:
    return assemble(INIT_ASM.replace("BOUND_VA", f"{PCAVE2 + BOUND_OFF:#x}"), PCAVE2 + INIT_OFF)


def bound_bytes() -> bytes:
    return assemble(BOUND_ASM, PCAVE2 + BOUND_OFF)


def main() -> int:
    s, t, b = stash_bytes(), init_bytes(), bound_bytes()
    assert STASH_OFF + len(s) <= POPUP_OFF, "the stash overlaps its data"
    assert len(t) <= INIT_LIMIT, (len(t), INIT_LIMIT)
    assert BOUND_OFF + len(b) <= 0x6E00, len(b)
    print(f"t_btnrow_stash  {len(s)} B @pcave2 {STASH_OFF:#x}; g_btnrow_popup {POPUP_OFF:#x}, g_btnrow_rem {REM_OFF:#x}")
    print('        bytes: "' + template(s, PCAVE2 + STASH_OFF) + '"')
    print(f"t_btnrow_init   {len(t)} B @pcave2 {INIT_OFF:#x} (limit {INIT_LIMIT})")
    print('        bytes: "' + template(t, PCAVE2 + INIT_OFF) + '"')
    print(f"t_btnrow_bound  {len(b)} B @pcave2 {BOUND_OFF:#x} (ends {BOUND_OFF + len(b):#x}, limit 0x6E00)")
    print('        bytes: "' + template(b, PCAVE2 + BOUND_OFF) + '"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
