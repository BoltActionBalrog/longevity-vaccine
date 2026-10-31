# Regenerates the W3A helpers in pcave2 0x38000..0x38FFF (2026-10-25 wave-3 W3A; guards
# tests/test_mirror_pairs_asm_parity.py + tests/test_scaling_mirror_pairs.py):
#
#   t_cw_rowsym    (F43; law scaling_laws.council_button_row "thirds" / council_thirds_fixup) -- the Council YES / NO /
#                  ABSTAIN row.  CouncilWin_exec's E8 @0x427784 (the first Font_init, already redirected to
#                  thunk_cw_seeds) is retargeted here; esi = CouncilWin, the row block 0x427661..0x427776 has just
#                  written the VOTE rect [+0xD04] and the thirds [+0xCD4] / [+0xCE4] / [+0xCF4] (its four native 3s
#                  all in g_cw_immtab once the disp8 @0x427707 row is there -- assemble_council.IMMTAB).  g > 16: the
#                  remainder rem = VOTE.R - third[2].R (0..2; anything else = an unscaled row, left alone) is
#                  distributed as popup_button_row_bounds does it -- d1 = rem >> 1, e = rem - d1: third[0].R += d1,
#                  third[1].L += d1, third[1].R += e, third[2].L += e, third[2].R += rem -- so the row's outer edges
#                  sit on the VOTE's and the widths are a palindrome.  Then (every g) push + ret to thunk_cw_seeds
#                  with every register as it came (eax / ecx / edx saved; flags are dead at a call).
#   t_ed_redchain  (the red-brush flanks; law scaling_laws.editor_red_chain_delta) -- thunk_ed_seeds' tail
#                  (`push 0x45B0F5; ret` -> `push t_ed_redchain; ret`, its only change: assemble_scenedit asm_seeds
#                  TAIL).  g > 16 and the stash fresh for this g (g_ed_stamp): delta = pal[24].R + 3 * s(3) -
#                  red[0].L (vanilla's red x0 = pal[24].R + 9, `add edi, 9` @0x45B073); the 6 red seed RECTs'
#                  L / R, the red-union stash L / R and the info-left stash move by delta (the engine builds the
#                  buttons from the seeds, thunk_ed_painter copies the stash at draw).  pushfd / pushad around it:
#                  the displaced `xor eax, eax; lea ecx, [esi+0x21E2C]` results reach 0x45B0F5 intact.
#
# Usage: py assemble_mirror_pairs.py   -> prints the yaml symbol + content lines
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
REGION = (0x38000, 0x39000)                        # W3A's pcave2 region
# placeholders -> yaml symbols (the shipped bytes carry {abs32:<sym>})
PH = {
    0x11111111: "g_popup_scale_num",
    0x22222222: "thunk_cw_seeds",
    0x33333333: "g_ed_stamp",
    0x44444444: "g_ed_p3",
    0x55555555: "g_ed_redu",
    0x66666666: "g_ed_info",
}
SYM_PH = {v: k for k, v in PH.items()}
# CouncilWin field offsets (terranx.h: btn_thirds[3] +0xCD4 stride 0x10, btn_full +0xD04)
CW_T0R, CW_T1L, CW_T1R, CW_T2L, CW_T2R, CW_VOTER = 0xCDC, 0xCE4, 0xCEC, 0xCF4, 0xCFC, 0xD0C
# MainWin statics (assemble_scenedit: MW_PAL = MainWin+0xADC paletteSeed[25], MW_RED = +0xC6C redSeed[6])
MW_PAL24_R = 0x7AE820 + 0xADC + 24 * 16 + 8        # = MainWin + 0xC64, vanilla's `mov edi, [esi+0xC64]`
MW_RED = 0x7AE820 + 0xC6C
SEEDS_RESUME = 0x45B0F5
RED_CHAIN_PADS = 3                                  # EDITOR_RED_CHAIN 9 = 3 * EDITOR_UNION_PAD

HELPERS = {     # name -> (offset, end of its slot)
    "t_cw_rowsym": (0x38000, 0x38060),
    "t_ed_redchain": (0x38060, 0x380E0),
}
SITES = [   # (id, va, new_bytes, note) -- call-target retargets owned in patches.yaml
    ("CouncilWin_exec.seed_table", 0x427784, "E8 {rel32:t_cw_rowsym}", "was {rel32:thunk_cw_seeds}; t_cw_rowsym tails there"),
]


def asm_rowsym(syms: dict | None = None) -> str:
    s = syms or SYM_PH
    return f"""
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 0x10
    jle     tail
    push    eax
    push    ecx
    push    edx
    mov     eax, dword ptr [esi+{CW_VOTER:#x}]
    sub     eax, dword ptr [esi+{CW_T2R:#x}]
    cmp     eax, 2
    ja      done
    mov     ecx, eax
    shr     ecx, 1
    mov     edx, eax
    sub     edx, ecx
    add     dword ptr [esi+{CW_T0R:#x}], ecx
    add     dword ptr [esi+{CW_T1L:#x}], ecx
    add     dword ptr [esi+{CW_T1R:#x}], edx
    add     dword ptr [esi+{CW_T2L:#x}], edx
    add     dword ptr [esi+{CW_T2R:#x}], eax
done:
    pop     edx
    pop     ecx
    pop     eax
tail:
    push    {s['thunk_cw_seeds']:#x}
    ret
"""


def asm_redchain(syms: dict | None = None) -> str:
    s = syms or SYM_PH
    return f"""
    pushfd
    pushad
    mov     eax, dword ptr [{s['g_popup_scale_num']:#x}]
    cmp     eax, 0x10
    jle     out
    cmp     eax, dword ptr [{s['g_ed_stamp']:#x}]
    jne     out
    mov     ecx, dword ptr [{s['g_ed_p3']:#x}]
    imul    ecx, ecx, {RED_CHAIN_PADS}
    mov     edx, dword ptr [{MW_PAL24_R:#x}]
    add     edx, ecx
    sub     edx, dword ptr [{MW_RED:#x}]
    je      out
    mov     edi, {MW_RED:#x}
    mov     ecx, 6
lp:
    add     dword ptr [edi], edx
    add     dword ptr [edi+8], edx
    add     edi, 16
    dec     ecx
    jne     lp
    mov     edi, {s['g_ed_redu']:#x}
    add     dword ptr [edi], edx
    add     dword ptr [edi+8], edx
    mov     edi, {s['g_ed_info']:#x}
    add     dword ptr [edi], edx
out:
    popad
    popfd
    push    {SEEDS_RESUME:#x}
    ret
"""


ASM = {"t_cw_rowsym": asm_rowsym, "t_ed_redchain": asm_redchain}


def assemble(name: str, syms: dict | None = None) -> bytes:
    """The helper's bytes at its VA; `syms` maps the PH symbol names to real VAs (default: the placeholders)."""
    off, end = HELPERS[name]
    b = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(ASM[name](syms), PCAVE2 + off)[0])
    assert off + len(b) <= end and REGION[0] <= off and end <= REGION[1], (name, len(b))
    return b


def template(name: str) -> str:
    """The yaml bytes: each placeholder dword -> {abs32:<sym>}."""
    b = assemble(name)
    out, i = [], 0
    while i < len(b):
        word = int.from_bytes(b[i:i + 4], "little") if i + 4 <= len(b) else None
        if word in PH:
            out.append(f"{{abs32:{PH[word]}}}")
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    tpl = " ".join(out)
    assert all(int.to_bytes(k, 4, "little").hex() not in bytes.fromhex(
        "".join(t for t in tpl.split() if not t.startswith("{"))).hex() for k in PH), tpl
    return tpl


def main() -> int:
    for name, (off, end) in HELPERS.items():
        b = assemble(name)
        print(f"; {name} {len(b)} B @{off:#x}..{off + len(b):#x} (slot to {end:#x})")
        print(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}")
        print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{template(name)}\"")
    for sid, va, nb, note in SITES:
        print(f"; site {sid} @{va:#x}: new_bytes \"{nb}\"   # {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
