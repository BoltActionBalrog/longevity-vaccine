#!/usr/bin/env python
"""Assembler for the Load/Save file-dialog row-icon checker regeneration (group filedlg_rows), 2026-10-04.

The file / folder / up-folder icons of the Load/Save list (16x16 cells of Jackal.pcx, palette +10 at load) have a
face that is a 2-D CHECKERBOARD dither of palette indices 0xA3 / 0x47 (PCX 0x99 / 0x3D).  Above native scale
FileDlg_draw_row_icon 0x614C50 draws them through thunk_checkbox_scale -> Sprite_draw_2 with num/den = g/16, a
nearest-neighbour enlarge, so each 1-px check becomes a 1- or 2- (g=22/25) or 2- or 3-px (g=40) block.  A dither
is regenerated at device density, never resampled (CLAUDE.md invariant): after the native draw the checker is
rewritten as T x T device-pixel cells on the dest buffer's own grid, T = scaling_laws.stripe_rows(g) =
g_stripe_period / 2:

    pixel (x, y) in {0xA3, 0x47}  ->  0xA3 if ((x // T) + (y // T)) & 1 == 0 else 0x47

Thunk (pcave2):
  t_fdicon_checker   drop-in for thunk_checkbox_scale at the three Sprite_draw_2 sites of FileDlg_draw_row_icon:
                     thiscall(ecx = Sprite*)(dest Buffer*, key, x, y, num, den) RET 0x18.
  g <= 16 -> `push thunk_checkbox_scale / ret`, stack and registers untouched (today's path, byte for byte).
  g > 16  -> re-push the six args, call thunk_checkbox_scale (which tail-jumps Sprite_draw_2), then walk a rect and
             rewrite every 0xA3 / 0x47 pixel to the law.  pushad/popad: eax (the draw's result) and every register
             leave as the native callee left them.

The walked rect is a SUPERSET of the drawn rect, not a model of it.  Read from the engine bytes (Sprite_blit_scaled_core
0x5E4B9A, scaled path 0x5E4ECE): the blit writes [ftol(x + trimX*s), +ftol(trimW*s)) x [ftol(y' + trimY*s),
+ftol(trimH*s)) & dest clip (+0x20), s = num/den, trim rect inside the 16x16 cell, y' = y + ((16 - g) >> 1) (the
thunk_checkbox_scale nudge).  So every written pixel lies in [x, x + g) x [y', y' + g); the walk covers
[x - 1, x + g + 2) x [y' - 1, y' + g + 2) & dest clip & buffer bounds.  The rewrite is CONTENT-keyed (only 0xA3 /
0x47 change) and a pure function of the dest position (idempotent), so the slack is harmless: measured on the
1920x1080 / 1600x1200 Load shots, the row behind the icons is C4/41 (selected: E0/E1) and the text E2 -- neither
member occurs outside the icon faces, and inside the icons they occur ONLY as the checker (outline AE, glyph 41,
shadow pair 4C/D3, highlights 52/64/23).

Parity: tests/test_stripes_fdicon_asm_parity.py (Unicorn: these bytes + the real thunk_checkbox_scale from
patches.yaml).  Fragments: `py assemble_stripes_fdicon.py --fragments`.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402

PCAVE2 = 0x00A0C000
assert PCAVE2 == SE.PCAVE2
GROUP = "filedlg_rows"

# cave_map.py --at 0x27F00 (2026-10-04): FREE; prev g_dl_mono ends 0x27ED0 (a 4-byte cell is planned at 0x27ED0),
# next g_dl_immtab_main starts 0x28100.
OFF_CODE = 0x27F00
OFF_LIMIT = 0x28100

G = 0x00668740                 # g_popup_scale_num
PERIOD = 0x0066879C            # g_stripe_period (P = 2T)
SPRITE_DRAW_2 = 0x005E4B4A     # thiscall(Sprite*; dest, key, x, y, num, den) RET 0x18
CHECK_TOP, CHECK_MATE = 0xA3, 0x47
CELL = 16                      # Jackal.pcx icon cell (the thunk_checkbox_scale nudge assumes the same 16)
assert G == SE.G

SYM_NAMES = ("g_popup_scale_num", "g_stripe_period", "thunk_checkbox_scale")


def load_syms(patches: Path | None = None) -> dict[str, int]:
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    s2v = ap.build_symbol_table(symbols, caves)
    out = {n: s2v[n] for n in SYM_NAMES}
    assert out["g_popup_scale_num"] == G and out["g_stripe_period"] == PERIOD
    assert s2v["Sprite_draw_2"] == SPRITE_DRAW_2
    cave = next(c for c in caves if c["id"] == "pcave2")
    assert int(cave["virtual_addr"]) == PCAVE2
    return out


# NO comments inside the asm text (keystone hangs on `;`); the notes live here.
#
# Entry stack: [esp] ret, +4 dest, +8 key, +0xC x, +0x10 y, +0x14 num, +0x18 den; ecx = Sprite*.
# Six `push [esp+0x18]` re-push den, num, y, x, key, dest (each push moves the next arg into the same slot).
# thunk_checkbox_scale keeps ecx, rewrites its own y/num/den copies and tail-jumps Sprite_draw_2 (RET 0x18).
# After pushad, ebp = esp: dest [ebp+0x24], x [ebp+0x2C], y [ebp+0x30] (the caller's, un-nudged).
# Locals (pushed): [ebp-4] l, [ebp-8] w, [ebp-0xC] b, [ebp-0x10] T; per row [ebp-0x14] y, then the row bit.
# Guards: dest NULL (the caller passes 0 when its window arg is 0), no pixel plane (+0x54), P < 2 (the period
# cell not yet set -> no div by zero), empty rect.  Buffer: clip +0x20..+0x2C, W +0x80, H +0x84 (stored negative),
# stride +0x4A8.  `mov` keeps EFLAGS, so `xor al, ah` -> ZF selects the member without a second compare.
def asm_fdicon_checker(s: dict[str, int]) -> str:
    return f"""
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      scaled
    push    {s['thunk_checkbox_scale']:#x}
    ret
scaled:
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    push    dword ptr [esp+0x18]
    call    {s['thunk_checkbox_scale']:#x}
    pushad
    mov     ebp, esp
    mov     esi, dword ptr [ebp+0x24]
    test    esi, esi
    je      out
    cmp     dword ptr [esi+0x54], 0
    je      out
    mov     ebx, dword ptr [{s['g_stripe_period']:#x}]
    cmp     ebx, 2
    jb      out
    mov     ecx, dword ptr [{s['g_popup_scale_num']:#x}]
    mov     eax, dword ptr [ebp+0x2C]
    lea     edx, [eax+ecx+2]
    dec     eax
    cmp     eax, dword ptr [esi+0x20]
    jge     l1
    mov     eax, dword ptr [esi+0x20]
l1:
    test    eax, eax
    jns     l2
    xor     eax, eax
l2:
    cmp     edx, dword ptr [esi+0x28]
    jle     r1
    mov     edx, dword ptr [esi+0x28]
r1:
    cmp     edx, dword ptr [esi+0x80]
    jle     r2
    mov     edx, dword ptr [esi+0x80]
r2:
    sub     edx, eax
    jle     out
    push    eax
    push    edx
    mov     eax, {CELL}
    sub     eax, ecx
    sar     eax, 1
    add     eax, dword ptr [ebp+0x30]
    lea     edx, [eax+ecx+2]
    dec     eax
    cmp     eax, dword ptr [esi+0x24]
    jge     t1
    mov     eax, dword ptr [esi+0x24]
t1:
    test    eax, eax
    jns     t2
    xor     eax, eax
t2:
    cmp     edx, dword ptr [esi+0x2C]
    jle     b1
    mov     edx, dword ptr [esi+0x2C]
b1:
    mov     ecx, dword ptr [esi+0x84]
    test    ecx, ecx
    jns     b2
    neg     ecx
b2:
    cmp     edx, ecx
    jle     b3
    mov     edx, ecx
b3:
    cmp     edx, eax
    jle     out
    push    edx
    mov     ecx, ebx
    shr     ecx, 1
    push    ecx
row:
    push    eax
    xor     edx, edx
    div     ebx
    xor     ecx, ecx
    cmp     edx, dword ptr [ebp-0x10]
    setae   cl
    push    ecx
    mov     eax, dword ptr [ebp-4]
    xor     edx, edx
    div     ebx
    mov     edi, dword ptr [esi+0x4A8]
    imul    edi, dword ptr [ebp-0x14]
    add     edi, dword ptr [esi+0x54]
    add     edi, dword ptr [ebp-4]
    mov     ecx, dword ptr [ebp-8]
    pop     eax
    mov     ah, al
px:
    mov     al, byte ptr [edi]
    cmp     al, {CHECK_TOP:#x}
    je      hit
    cmp     al, {CHECK_MATE:#x}
    jne     next
hit:
    cmp     edx, dword ptr [ebp-0x10]
    setae   al
    xor     al, ah
    mov     al, {CHECK_TOP:#x}
    je      store
    mov     al, {CHECK_MATE:#x}
store:
    mov     byte ptr [edi], al
next:
    inc     edi
    inc     edx
    cmp     edx, ebx
    jb      nx
    xor     edx, edx
nx:
    dec     ecx
    jne     px
    pop     eax
    inc     eax
    cmp     eax, dword ptr [ebp-0xC]
    jl      row
out:
    mov     esp, ebp
    popad
    ret     0x18
"""


THUNK_ORDER = ("t_fdicon_checker",)
THUNK_NOTE = {
    "t_fdicon_checker": "thunk_checkbox_scale drop-in at FileDlg_draw_row_icon's 3 Sprite_draw_2 sites (RET 0x18): "
                        "g<=16 tail-jump; else draw, then regenerate the icon face's A3/47 checker as TxT device cells",
}


def assemble_all(syms: dict[str, int] | None = None, off_code: int = OFF_CODE) -> dict[str, tuple[int, bytes]]:
    s = syms or load_syms()
    src = asm_fdicon_checker(s)
    assert ";" not in src
    return {"t_fdicon_checker": (off_code, SE.assemble(src, PCAVE2 + off_code))}


def names_of(layout) -> dict[str, int]:
    return {n: PCAVE2 + o for n, (o, _) in layout.items()}


def templatize(b: bytes, va: int, syms: dict[str, int], names: dict[str, int]) -> str:
    table = {v: n for n, v in syms.items()}
    table.update({v: n for n, v in names.items()})
    return SE.templatize(b, va, table)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# (existing patches.yaml site id, call VA, pristine bytes, note).  These three sites ALREADY exist in group
# filedlg_rows with new_bytes "E8 {rel32:thunk_checkbox_scale}": the fragment REPLACES those three entries.
SITES = [
    ("FUN_00614c50.icon_folder", 0x614CC8, "E8 7D FE FC FF", "call Sprite_draw_2 (param_2==2 icon, this=0x9b9078)"),
    ("FUN_00614c50.icon_drive", 0x614D24, "E8 21 FE FC FF", "call Sprite_draw_2 (param_2==1 icon, this=0x9b9018)"),
    ("FUN_00614c50.icon_file", 0x614D7E, "E8 C7 FD FC FF", "call Sprite_draw_2 (param_2==0 icon, this=0x9b9048)"),
]
RATIONALE = ("The icon face is a 2-D checker dither (A3/47) that the g/16 nearest-neighbour enlarge turns into uneven "
             "blocks; the drop-in runs thunk_checkbox_scale unchanged, then rewrites the checker as TxT device cells "
             "(T = stripe_rows(g)) on the dest grid inside the drawn rect. g<=16: tail-jump to thunk_checkbox_scale.")


def site_list() -> list[dict]:
    out = []
    for sid, va, orig_hex, note in SITES:
        orig = bytes([0xE8]) + struct.pack("<i", SPRITE_DRAW_2 - (va + 5))
        assert hx(orig) == orig_hex, (sid, hx(orig), orig_hex)
        out.append({"id": sid, "va": va, "orig": orig, "note": note})
    return out


def verify_live(sites) -> list[str]:
    """Every site's original bytes must be what the PRISTINE base (.bak) holds."""
    out = []
    for s in sites:
        got = SE.base_exe_bytes(s["va"], len(s["orig"]))
        if got != s["orig"]:
            out.append(f"{s['id']} @{s['va']:#x}: base {hx(got)} != expected {hx(s['orig'])}")
    return out


def site_yaml(sites) -> str:
    out = []
    for s in sites:
        out.append(f"""  - id: {s['id']}
    status: confirmed
    group: {GROUP}
    function: FUN_00614c50
    virtual_addr: {s['va']:#010x}
    length: 5
    original_bytes: "{hx(s['orig'])}"                       # {s['note']}
    new_bytes:      "E8 {{rel32:t_fdicon_checker}}"
    pattern: call_target_redirect
    rationale: "{RATIONALE}"
""")
    return "\n".join(out)


def roundtrip_problems(layout, syms) -> list[str]:
    names = names_of(layout)
    table = dict(syms)
    table.update(names)
    out = []
    for name, (off, b) in layout.items():
        tpl = templatize(b, PCAVE2 + off, syms, names)
        got = ap.ByteTemplate(tpl).resolve(PCAVE2 + off, table)
        if bytes(got) != b:
            out.append(f"{name}: template does not round-trip")
        for lit in (syms[n] for n in SYM_NAMES):
            if struct.pack("<I", lit).hex().upper() in tpl.replace(" ", ""):
                out.append(f"{name}: literal {lit:#x} left untemplatized")
    return out


def main(argv) -> int:
    syms = load_syms()
    layout = assemble_all(syms)
    names = names_of(layout)
    ok = True
    end = max(o + len(b) for o, b in layout.values())
    print("; ==== file-dialog icon checker (assemble_stripes_fdicon.py) ====")
    print(f"; block {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B); limit {OFF_LIMIT:#x}")
    if end > OFF_LIMIT:
        ok = False
        print("; OVERFLOW past the gap")
    sym_lines, content_lines = [], []
    for name in THUNK_ORDER:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {GROUP} ({len(b)}B) {THUNK_NOTE[name]}")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, syms, names)}\"")
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
        with open(os.path.join(frag, "_fragment_stripes_fdicon_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_stripes_fdicon_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_stripes_fdicon_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# REPLACES the three existing filedlg_rows entries of the same ids (new_bytes only changes).\n")
            f.write(site_yaml(sites))
        print("; fragments written to work/patches/_fragment_stripes_fdicon_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print(site_yaml(sites))
    print(f"; sites: {len(sites)} (existing entries of group {GROUP}, retargeted)")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
