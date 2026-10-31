#!/usr/bin/env python
"""Assembler for the council vote-chip stripe law (group council_scale, thunk t_si_chip), 2026-10-04.

Above native scale every stripe field is T = scaling_laws.stripe_rows(g) device rows per member, P = 2T
(cell g_stripe_period, VA 0x66879C), top member on dest-buffer rows where (y mod P) < T.  thunk_cw_chip
(assemble_council.asm_cw_chip) tiles the chip fill 1:1 from the native 1-row yellow/orange tile at EVERY scale
("chips keep the 1px device-stripe language").  The whole game now follows the one rule, so at T >= 2 the chip
fill must be T rows per member.

Why a wrapper and not an edit of asm_cw_chip: thunk_cw_chip sits in the council block's consecutive layout
(0x13670, 225 B, next thunk 16-aligned behind it); growing it moves every later council thunk, and
thunk_flag_restripe (0x13850) / thunk_sd_reblit_wrap (0x139D0) are referenced by literal offset from
assemble_artreblit.py.  t_si_chip leaves thunk_cw_chip untouched and is the new CALL target of the 5 chip sites.

Why not a pair remap of the finished chip: the chip bevel is the SAME index as the fill's top member
(refs/pristine/Council/Vote.png: bevel column + rows F5, fill rows F5 / 65), so no index test separates fill from
bevel once the frame is down.  The order has to be the chip's own: fill, then frame, then mask.

t_si_chip  drop-in for Buffer_box_sprite at the 5 chip sites: thiscall(ecx = dest)(RECT*, params*) RET 8
  P <= 2 (T == 1: every g <= 21) or g <= 16: `push thunk_cw_chip / ret` -- stack and registers untouched, so the
      result is byte-identical to today's.
  else: 1. CALL thunk_cw_chip (the 3-pass 1-row chip; also what builds the lazy fill and leaves the fill-nulled
           params copy SCR_B = g_cw_chipscr + 40 behind);
        2. hollow chip ([params+0x20] == 0), no dest pixels, or rect & clip under 2 x 8 px: done;
        3. sample the pair on the dest at the centre column of (rect & clip): a = the pixel on the EVEN row
           nearest the centre, b = the row below; a == b, or the row below that != a (not a 1-row field): done;
        4. every {a, b} pixel of (rect & clip) -> a if (y mod P) < T else b   (the bevel's a pixels go too);
        5. CALL thunk_box_thick_hollow_flat(dest, rect, SCR_B) again -- the same call pass 2 made, so every
           bevel pixel is rewritten and the border pieces' padding is back in the mask colour;
        6. every mask-colour ([params+0x24], when <= 0xFF) pixel of (rect & clip) -> the same stripe colour
           (what Buffer_tile_mask did from the 1-row tile).
Law: council_chip_law in tests/test_stripes_icon_asm_parity.py (to be moved into scaling_laws.py with the
"Chips keep the 1px device-stripe language" comment; the edit is in work/briefs/stripes_icon_findings.md).
Fragments: `py assemble_stripes_icon.py --fragments`.
"""
from __future__ import annotations

import contextlib
import io
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import apply_patches as ap  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_se as SE  # noqa: E402

PCAVE2 = 0x00A0C000
assert PCAVE2 == SE.PCAVE2
GROUP = "council_scale"

# cave_map.py --at 0x27C00 (2026-10-04): FREE, prev t_lb_item_stripes ends 0x27B60, next g_dl_exec 0x27E00.
OFF_CODE = 0x29CA0
OFF_LIMIT = 0x29EB0

G = 0x00668740                 # g_popup_scale_num
PERIOD = 0x0066879C            # g_stripe_period
BOX_SPRITE = 0x005E2DD3        # the chip sites' native callee
SCR_B_OFF = 40                 # g_cw_chipscr + 40: thunk_cw_chip's fill-nulled params copy
MIN_W, MIN_H = 2, 8

SYM_NAMES = ("g_popup_scale_num", "g_stripe_period", "thunk_cw_chip", "thunk_box_thick_hollow_flat", "g_cw_chipscr")


def load_syms(patches: Path | None = None) -> dict[str, int]:
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    s2v = ap.build_symbol_table(symbols, caves)
    out = {n: s2v[n] for n in SYM_NAMES}
    assert out["g_popup_scale_num"] == G and out["g_stripe_period"] == PERIOD
    out["Buffer_box_sprite"] = s2v["Buffer_box_sprite"]
    assert out["Buffer_box_sprite"] == BOX_SPRITE
    return out


# NO comments inside the asm text (keystone hangs on `;`).
# Frame: [ebp+8] rect, [ebp+0xC] params; locals -4 dest, -8 x0, -0xC y0, -0x10 x1, -0x14 y1, -0x18 a, -0x1C b.
# si_pass (local subroutine, reads the frame): bl / bh = the two indices to replace, edi = dest.  Clobbers
# eax, ecx, edx, esi.  y0 >= 0 (clamped), so the unsigned `div` by P is the row's phase.
def asm_si_chip(s: dict[str, int]) -> str:
    scr_b = s["g_cw_chipscr"] + SCR_B_OFF
    return f"""
    cmp     dword ptr [{s['g_stripe_period']:#x}], 2
    jle     native
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      law
native:
    push    {s['thunk_cw_chip']:#x}
    ret
law:
    push    ebp
    mov     ebp, esp
    sub     esp, 0x1C
    push    ebx
    push    esi
    push    edi
    mov     dword ptr [ebp-4], ecx
    push    dword ptr [ebp+0xC]
    push    dword ptr [ebp+8]
    call    {s['thunk_cw_chip']:#x}
    mov     esi, dword ptr [ebp+0xC]
    cmp     dword ptr [esi+0x20], 0
    je      fin
    mov     edi, dword ptr [ebp-4]
    cmp     dword ptr [edi+0x54], 0
    je      fin
    mov     esi, dword ptr [ebp+8]
    mov     eax, dword ptr [esi]
    cmp     eax, dword ptr [edi+0x20]
    jge     xl
    mov     eax, dword ptr [edi+0x20]
xl:
    test    eax, eax
    jns     xl2
    xor     eax, eax
xl2:
    mov     dword ptr [ebp-8], eax
    mov     eax, dword ptr [esi+4]
    cmp     eax, dword ptr [edi+0x24]
    jge     yt
    mov     eax, dword ptr [edi+0x24]
yt:
    test    eax, eax
    jns     yt2
    xor     eax, eax
yt2:
    mov     dword ptr [ebp-0xC], eax
    mov     eax, dword ptr [esi+8]
    cmp     eax, dword ptr [edi+0x28]
    jle     xr
    mov     eax, dword ptr [edi+0x28]
xr:
    cmp     eax, dword ptr [edi+0x80]
    jle     xr2
    mov     eax, dword ptr [edi+0x80]
xr2:
    mov     dword ptr [ebp-0x10], eax
    sub     eax, dword ptr [ebp-8]
    cmp     eax, {MIN_W}
    jl      fin
    mov     eax, dword ptr [esi+0xC]
    cmp     eax, dword ptr [edi+0x2C]
    jle     yb
    mov     eax, dword ptr [edi+0x2C]
yb:
    mov     edx, dword ptr [edi+0x84]
    test    edx, edx
    jns     hpos
    neg     edx
hpos:
    cmp     eax, edx
    jle     yb2
    mov     eax, edx
yb2:
    mov     dword ptr [ebp-0x14], eax
    mov     ecx, eax
    sub     eax, dword ptr [ebp-0xC]
    cmp     eax, {MIN_H}
    jl      fin
    add     ecx, dword ptr [ebp-0xC]
    shr     ecx, 1
    and     ecx, -2
    imul    ecx, dword ptr [edi+0x4A8]
    add     ecx, dword ptr [edi+0x54]
    mov     eax, dword ptr [ebp-8]
    add     eax, dword ptr [ebp-0x10]
    shr     eax, 1
    add     ecx, eax
    mov     edx, dword ptr [edi+0x4A8]
    movzx   eax, byte ptr [ecx]
    movzx   ebx, byte ptr [ecx+edx]
    cmp     eax, ebx
    je      fin
    cmp     al, byte ptr [ecx+edx*2]
    jne     fin
    mov     dword ptr [ebp-0x18], eax
    mov     dword ptr [ebp-0x1C], ebx
    mov     bh, al
    call    si_pass
    push    {scr_b:#x}
    push    dword ptr [ebp+8]
    mov     ecx, dword ptr [ebp-4]
    call    {s['thunk_box_thick_hollow_flat']:#x}
    mov     edi, dword ptr [ebp-4]
    mov     esi, dword ptr [ebp+0xC]
    mov     eax, dword ptr [esi+0x24]
    cmp     eax, 0xFF
    ja      fin
    mov     bl, al
    mov     bh, al
    call    si_pass
fin:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     8
si_pass:
    mov     ecx, dword ptr [ebp-0xC]
py:
    cmp     ecx, dword ptr [ebp-0x14]
    jge     pdone
    mov     eax, ecx
    xor     edx, edx
    div     dword ptr [{s['g_stripe_period']:#x}]
    mov     eax, dword ptr [{s['g_stripe_period']:#x}]
    shr     eax, 1
    cmp     edx, eax
    mov     eax, dword ptr [ebp-0x18]
    jb      ptop
    mov     eax, dword ptr [ebp-0x1C]
ptop:
    mov     edx, ecx
    imul    edx, dword ptr [edi+0x4A8]
    add     edx, dword ptr [edi+0x54]
    mov     esi, dword ptr [ebp-8]
px:
    cmp     esi, dword ptr [ebp-0x10]
    jge     pnext
    mov     ah, byte ptr [edx+esi]
    cmp     ah, bl
    je      pw
    cmp     ah, bh
    jne     pn
pw:
    mov     byte ptr [edx+esi], al
pn:
    inc     esi
    jmp     px
pnext:
    inc     ecx
    jmp     py
pdone:
    ret
"""


THUNK_ORDER = ("t_si_chip",)
THUNK_NOTE = {
    "t_si_chip": "Buffer_box_sprite drop-in at the 5 vote-chip sites (RET 8): P<=2 or g<=16 -> thunk_cw_chip untouched; "
                 "else thunk_cw_chip, then the chip fill at the stripe law (pair remap, frame again, mask -> stripe)",
}


def assemble_all(syms: dict[str, int] | None = None, off_code: int = OFF_CODE) -> dict[str, tuple[int, bytes]]:
    s = syms or load_syms()
    src = asm_si_chip(s)
    assert ";" not in src
    return {"t_si_chip": (off_code, SE.assemble(src, PCAVE2 + off_code))}


def names_of(layout) -> dict[str, int]:
    return {n: PCAVE2 + o for n, (o, _) in layout.items()}


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def templatize(b: bytes, va: int, syms: dict[str, int]) -> str:
    """yaml hex with {abs32:}/{rel32:} for the symbol operands.  SE.templatize inspects operands with capstone
    (calls -> rel32, data / imm operands -> abs32).  The SCR_B operand is g_cw_chipscr + 40, which no symbol
    names, so it stays a literal -- the same literal thunk_cw_chip's own template carries (68 D8 E9 A1 00)."""
    table = {v: n for n, v in syms.items() if n != "Buffer_box_sprite"}
    return SE.templatize(b, va, table)


# ---- sites: the 5 chip sites of CouncilWin_draw_column, today `E8 {rel32:thunk_cw_chip}` ------------------------
SITES = [
    ("CouncilWin_draw_column.chip_da00", 0x4261AA, "vote chip da00"),
    ("CouncilWin_draw_column.chip_d9d8", 0x4261D6, "vote chip d9d8"),
    ("CouncilWin_draw_column.chip_da28_a", 0x426203, "vote chip da28"),
    ("CouncilWin_draw_column.chip_da28_b", 0x426230, "vote chip da28"),
    ("CouncilWin_draw_column.chip_da28_c", 0x42625C, "vote chip da28"),
]


def site_list() -> list[dict]:
    return [{"id": sid, "va": va, "note": note,
             "orig": bytes([0xE8]) + struct.pack("<i", BOX_SPRITE - (va + 5))} for sid, va, note in SITES]


def verify_live(sites) -> list[str]:
    """Every site's original bytes must be what the PRISTINE base (.bak) holds: call Buffer_box_sprite."""
    out = []
    for s in sites:
        got = SE.base_exe_bytes(s["va"], 5)
        if got != s["orig"]:
            out.append(f"{s['id']} @{s['va']:#x}: base {hx(got)} != expected {hx(s['orig'])}")
    return out


def site_yaml(sites) -> str:
    out = ["  # REPLACEMENT new_bytes for the 5 EXISTING council_scale chip sites (same ids; today E8 {rel32:thunk_cw_chip}).\n"
           "  # Not new sites: apply by changing each entry's new_bytes target (and assemble_council.py SITES).\n"]
    for s in sites:
        out.append(f"""  - id: {s['id']}
    status: confirmed
    group: {GROUP}
    function: CouncilWin_draw_column
    virtual_addr: {s['va']:#010x}
    length: 5
    original_bytes: "{hx(s['orig'])}"   # call Buffer_box_sprite ({s['note']})
    new_bytes:      "E8 {{rel32:t_cw_chiphalf}}"   # 2026-10-25 W5B: the half-open wrapper around t_si_chip (assemble_council_mirror.py)
    pattern: call_target_redirect
""")
    return "\n".join(out)


def roundtrip_problems(layout, syms) -> list[str]:
    table = dict(syms)
    table.update(names_of(layout))
    out = []
    for name, (off, b) in layout.items():
        tpl = templatize(b, PCAVE2 + off, syms)
        got = ap.ByteTemplate(tpl).resolve(PCAVE2 + off, table)
        if bytes(got) != b:
            out.append(f"{name}: template does not round-trip")
        for n in SYM_NAMES:
            if struct.pack("<I", syms[n]).hex().upper() in tpl.replace(" ", ""):
                out.append(f"{name}: literal {n} left untemplatized")
    return out


def main(argv) -> int:
    syms = load_syms()
    layout = assemble_all(syms)
    ok = True
    end = max(o + len(b) for o, b in layout.values())
    print("; ==== council vote-chip stripe law (assemble_stripes_icon.py) ====")
    print(f"; block {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B); limit {OFF_LIMIT:#x}")
    if end > OFF_LIMIT:
        ok = False
        print("; OVERFLOW past the gap")
    sym_lines, content_lines = [], []
    for name in THUNK_ORDER:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {GROUP} ({len(b)}B) {THUNK_NOTE[name]}")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, syms)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    for p in roundtrip_problems(layout, syms):
        ok = False
        print("; TEMPLATE:", p)
    sites = site_list()
    for p in verify_live(sites):
        ok = False
        print("; LIVE MISMATCH:", p)
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        for kind, text in (("symbols", "\n".join(sym_lines) + "\n"), ("cave", "\n".join(content_lines) + "\n"),
                           ("sites", site_yaml(sites))):
            with open(os.path.join(frag, f"_fragment_stripes_icon_{kind}.yaml"), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        print("; fragments written to work/patches/_fragment_stripes_icon_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print(site_yaml(sites))
    print(f"; sites (existing entries retargeted): {len(sites)}")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
