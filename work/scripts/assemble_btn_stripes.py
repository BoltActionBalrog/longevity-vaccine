"""Assemble + cross-check thunk_btn_stripes (FlatButton bar -> stripe-law dither).

After c592d318 the popup/filedlg option ROWS render their scanline dither as uniform
period-P stripes (thunk_fe_pair_remap law, P=(g+4)>>3), but the FlatButton OK/CANCEL
bars still showed the 1px device pair (thunk_btn_devfill re-tile) — a visible regime
mismatch (4K Quit screenshot: rows 2/3-run period-5, OK bar 1px ae/ee). And the
HOVER/PRESSED states (body sprite swapped by state index ebp: 1=0x77a990, 2=0x77aa14,
non-tileable highlight sprites devfill deliberately skips) kept the raw NN zoom — any
scanline pairs inside them banded like the old rows.

thunk_btn_stripes v2: drop-in for thunk_btn_2dscale's `call thunk_btn_devfill`
(inside its pushad, esi=button, only called while g_btn_pending i.e. g>16):
  - g_faction_active -> set g_rm_povr=2 (one-shot P override in thunk_fe_pair_remap:
    P=2/hN=1 = the 1px PARITY law, top colour on even rows — the dropdown/dither
    treatment) so the faction buttons keep the screen's 1px device-density language
    for EVERY state. v1 skipped faction entirely — but the probe (frida_btn_bands.log
    2026-07-03) showed the HOVER sprite 0x77a990 is ae/ee dither + solid 0xE0 edge
    rows and the PRESSED sprite 0x77aa14 is pure 0xE0/0xE1 dither, both NN-banded
    at fractional g = the user-reported banding on OK/INFO/CANCEL/CHANGE NAME.
    Normal state: devfill re-tiles 1px ae/ee phase ae-on-even -> the parity remap is
    a no-op on it. Known minor collateral: the hover sprite's 2-3px solid E0 edge
    rows dither to E0/E1 on odd rows (vs banded whole bars before — accepted).
  - else (popup/filedlg): natural P -> period-P stripes matching the option rows.
  Common: call devfill (normal state: 1px re-tile + corner punch; hover/pressed:
  no-op, sprite never captured), then thunk_fe_pair_remap over the WHOLE button
  buffer: g_fe_dst=&(esi+0x444) embedded Buffer, x/y=0, w=g_btn_origW,
  h=NEG(g_btn_origH) (stored negative), g_fe_src=0 (navy family OFF — bar pairs
  ae/ee + e0/e1 are unconditional in the remap). Pair pixels become lawful stripes;
  gradient/text/key-9 corner pixels pass through untouched.
Emits yaml-ready hex with placeholders; cross-checks the hand template against keystone.

RETIRED (2026-10-10): this emits the 123 B v4; the shipped thunk_btn_stripes is v12 (297 B),
owned by scripts\\assemble_popup_sb.py (asm_btn_stripes; pinned to patches.yaml by
tests\\test_stale_sources.py). Kept as history only; running it exits non-zero.
"""
import sys
sys.exit("assemble_btn_stripes.py is SUPERSEDED by assemble_popup_sb.py "
         "(thunk_btn_stripes v12); it emits the retired v4 and must not be run.")
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
THUNK_OFF = 0x2FD0
THUNK_VA  = PCAVE2_VA + THUNK_OFF

SYMS = {
    "g_faction_active":    PCAVE2_VA + 0x12D0,
    "g_rm_povr":           PCAVE2_VA + 0x2FCC,
    "g_rm_f0ovr":          PCAVE2_VA + 0x10634,  # v7 F0/B9 one-shot (sb-face pair)
    "thunk_btn_devfill":   PCAVE2_VA + 0x1660,
    "g_fe_dst":            PCAVE2_VA + 0x2FA0,
    "g_fe_x":              PCAVE2_VA + 0x2FA4,
    "g_fe_y":              PCAVE2_VA + 0x2FA8,
    "g_fe_w":              PCAVE2_VA + 0x2FAC,
    "g_fe_h":              PCAVE2_VA + 0x2FB0,
    "g_fe_src":            PCAVE2_VA + 0x2FC4,
    "g_btn_origW":         PCAVE2_VA + 0x538,
    "g_btn_origH":         PCAVE2_VA + 0x53C,
    "thunk_fe_pair_remap": PCAVE2_VA + 0x10000,  # v7 (relocated 0xC1C0->0x10000 2026-08-06)
}

# v3 (2026-07-21c): BaseWin FlatButton range EARLY-OUT — no devfill re-tile, no
# remap. The basewin11 census proved devfill's 1:1 native full-bleed overpainted
# the whole zoomed bar (the 20-row wood/scanline art repeating at y=20/40 =
# the "stamp lines"); the BaseWin treatment is thunk_btn_bandstripe v4's
# KSB zoom + per-state pair restripe, which this early-out leaves visible.
# Popup/filedlg/faction buttons byte-identical (their art is flat dither —
# devfill re-tile + remap IS correct there). CALL-entered -> bare RET.
BASEWIN_BTN_LO = 0x6B4DE8
BASEWIN_BTN_HI = 0x6C4670

# v4 (2026-08-08 sb banding fix): the two ProdPicker scrollbar arrow FlatButton
# statics arm the fe_pair_remap v7 F0/B9 one-shot before the common remap call —
# their faces dither the sb pair 0xF0/0xB9, which is NEVER content-keyed (0xF0
# is solid console art elsewhere). Every other button byte-path identical to v2.
ARROW_UP = 0x6AFC10
ARROW_DN = 0x6B075C

ASM = r"""
    cmp     esi, 0x6B4DE8
    jb      cont
    cmp     esi, 0x6C4670
    jae     cont
    ret
cont:
    cmp     esi, 0x6AFC10
    je      sbarrow
    cmp     esi, 0x6B075C
    jne     nof0
sbarrow:
    mov     dword ptr [{g_rm_f0ovr}], 1
nof0:
    cmp     dword ptr [{g_faction_active}], 0
    je      common
    mov     dword ptr [{g_rm_povr}], 2
common:
    call    {thunk_btn_devfill}
    lea     eax, [esi+0x444]
    mov     [{g_fe_dst}], eax
    xor     eax, eax
    mov     [{g_fe_x}], eax
    mov     [{g_fe_y}], eax
    mov     [{g_fe_src}], eax
    mov     eax, [{g_btn_origW}]
    mov     [{g_fe_w}], eax
    mov     eax, [{g_btn_origH}]
    neg     eax
    mov     [{g_fe_h}], eax
    call    {thunk_fe_pair_remap}
    ret
"""

# hand template (yaml-ready); cross-checked against keystone below
TEMPLATE = ("81 FE E8 4D 6B 00 72 09 81 FE 70 46 6C 00 73 01 C3 "
            "81 FE 10 FC 6A 00 74 08 81 FE 5C 07 6B 00 75 0A "
            "C7 05 {abs32:g_rm_f0ovr} 01 00 00 00 "
            "83 3D {abs32:g_faction_active} 00 74 0A C7 05 {abs32:g_rm_povr} 02 00 00 00 "
            "E8 {rel32:thunk_btn_devfill} "
            "8D 86 44 04 00 00 A3 {abs32:g_fe_dst} 31 C0 A3 {abs32:g_fe_x} A3 {abs32:g_fe_y} "
            "A3 {abs32:g_fe_src} A1 {abs32:g_btn_origW} A3 {abs32:g_fe_w} A1 {abs32:g_btn_origH} "
            "F7 D8 A3 {abs32:g_fe_h} E8 {rel32:thunk_fe_pair_remap} C3")


def resolve_template(tpl, base_va):
    out = bytearray()
    for tok in tpl.split():
        if tok.startswith("{abs32:"):
            out += SYMS[tok[7:-1]].to_bytes(4, "little")
        elif tok.startswith("{rel32:"):
            target = SYMS[tok[7:-1]]
            out += ((target - (base_va + len(out) + 4)) & 0xFFFFFFFF).to_bytes(4, "little")
        else:
            out.append(int(tok, 16))
    return bytes(out)


def main():
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    asm = ASM
    for name, va in SYMS.items():
        asm = asm.replace("{%s}" % name, "0x%08X" % va)
    clean = "\n".join(ln.split(";", 1)[0].rstrip() for ln in asm.splitlines() if ln.split(";", 1)[0].strip())
    enc, count = ks.asm(clean, THUNK_VA)
    ksbytes = bytes(enc)
    tbytes = resolve_template(TEMPLATE, THUNK_VA)
    print(f"; thunk_btn_stripes @ VA 0x{THUNK_VA:X} (pcave2 +0x{THUNK_OFF:X})")
    print(f"; keystone: {len(ksbytes)} bytes, {count} statements; template: {len(tbytes)} bytes")
    if ksbytes == tbytes:
        print("; CROSS-CHECK OK — template == keystone")
        print(TEMPLATE)
        return 0
    print("; MISMATCH")
    print("; ks : " + ksbytes.hex(" ").upper())
    print("; tpl: " + tbytes.hex(" ").upper())
    return 1


if __name__ == "__main__":
    sys.exit(main())
