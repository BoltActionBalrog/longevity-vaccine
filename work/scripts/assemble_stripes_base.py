#!/usr/bin/env python
"""Assembler for group base_cell_stripes (2026-10-04): the base screen's tiled resource cells + queue row tile.

Above native scale (g = g_popup_scale_num > 16) every chrome stripe follows the one stripe law
(T = stripe_rows(g) rows per stripe, P = 2T = the cell g_stripe_period, top member where (y mod P) < T on the
DEST-BUFFER row grid).  Three base-screen surfaces are still tiled 1:1 from native 1-row dither textures:

  (1) the resource CELLS: Buffer_tile_2 (0x5DA9F0) of 20x20 tiles embedded in BaseWindow (loaded by BaseWin_init
      0x41F7E7.. from the interface sheet):  +0xBD4C 0x95/0x96 (yellow)   +0xBD20 0x98/0x99 (green)
      +0xBCC8 0xE0/0xE2 (blue)   +0xBCF4 0x42/0xDE (white)   +0xBC9C 0x5F/0x60 (orange)   +0xBDA4 solid 0xF0.
      Sites: BaseWin_draw_nutrients 0x41165C (pitch >= 8), BaseWin_draw_expenses x12 (the three intake bars),
      BaseWin_draw_production 0x40ECCA / 0x40ED33 (the mineral box in the bottom console).
      None of the five pairs is a thunk_fe_pair_remap family, and 0xE0 belongs to fe's UNCONDITIONAL E0/E1 family
      with a different mate (E2 here) -- fe must never walk these cells.  So the restripe is a dedicated one:
      per draw, the freshly tiled rect itself is the evidence (no pair table, no state/recolor variant can be
      missed): it is rewritten only when EVERY pixel of (rect & clip) is a strict 1-row parity dither of two
      indices; a solid tile (0xF0), art, or a rect cut to one row is left exactly as the engine drew it.
  (2) the queue's selected / hover row: BaseWin_draw_queue 0x415404 Buffer_tile of [0x78D9D0] (0xE0/0xE1, the
      file dialog's selected-row tile) / [0x78D980] (box set 27 fill, 0xAE/0xEE) into the strip canvas.  Both are
      fe's unconditional families -> a plain redirect to the existing t_tile_force.

Thunk (pcave2 0x27D00, one block):
  t_sb_tile2   drop-in for Buffer_tile_2  thiscall(ecx=dest)(src, a3, a4, x, y, W, H) RET 0x1C, DEVICE args.
               g <= 16: `push native / ret`, stack and registers untouched.  Else the native tile with the same
               args, then (pushad/popad, every register and eax = the native result preserved) the pair restripe
               of (x, y, x+W, y+H) & dest clip.
               Law: tests/test_stripes_base_asm_parity.py tile_pair_restripe (to move into scaling_laws.py).

Canonical top member = the member on EVEN dest rows.  Buffer_tile_2 maps dest row y to tile row
(y - y0 + a4) mod 20 and every caller passes a4 == y0, so that is the tile's own row-0 member whatever the cell's
origin: every cell of one sprite gets the same member on top, and at T = 1 (g < 22) the rewrite is the identity.

The 13 base-canvas sites already go through thunk_bw_tile2 / thunk_bw_piptile (native -> device args); those
adapters tail-jump to Buffer_tile_2.  Re-pointing that tail to t_sb_tile2 is an edit to existing entries and is
NOT emitted by the fragments: `py assemble_stripes_base.py --proposals` prints it, together with the two
file-dialog list-phase replacement thunks (same slots, same gates; see work/briefs/stripes_base_findings.md).

Parity: tests/test_stripes_base_asm_parity.py.  Fragments: `py assemble_stripes_base.py --fragments`.
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
GROUP = "base_cell_stripes"

# Block placement (cave_map.py 2026-10-04): the free run 0x27B60..0x27E00 between t_lb_item_stripes and g_dl_exec.
OFF_CODE = 0x27D00
OFF_LIMIT = 0x27E00

G = 0x00668740                 # g_popup_scale_num
PERIOD = 0x0066879C            # g_stripe_period
BUFFER_TILE = 0x005DA860       # thiscall(dest; src, phaseX, phaseY, dstX, dstY, w, h) RET 0x1C
BUFFER_TILE_2 = 0x005DA9F0     # thiscall(dest; sprite, a3, a4, x, y, W, H) RET 0x1C
BUFFER_COPY_4 = 0x005DFF00     # thiscall(src; dst, sx, sy, dx, dy, w, h) RET 0x1C
assert G == SE.G

SYM_NAMES = ("g_popup_scale_num", "g_stripe_period", "t_tile_force")
LOCAL_SYMS = {"Buffer_tile_2": BUFFER_TILE_2}          # not yet a patches.yaml symbol: the symbols fragment adds it
PROPOSAL_SYMS = ("g_filedlg_active", "Buffer_tile", "Buffer_copy_4", "thunk_ensure_stripes", "g_stripe_navy",
                 "g_stripe_sel", "g_filedlg_rowtile_sel")
# the two file-dialog thunks the proposals replace IN PLACE (slot start, slot limit) -- cave_map.py --at
P_ROWBG_OFF, P_ROWBG_LIMIT = 0x2F00, 0x2F50
P_COPY4_OFF, P_COPY4_LIMIT = 0x2F50, 0x2FA0
WIN_TOP_FROM_CANVAS = 0x140 - 0x444              # GraphicWin canvas +0x444 -> rRect1.top +0x140 (parent-local)


def load_syms(patches: Path | None = None) -> dict[str, int]:
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    s2v = ap.build_symbol_table(symbols, caves)
    out = {n: s2v[n] for n in SYM_NAMES + PROPOSAL_SYMS}
    for n, v in LOCAL_SYMS.items():
        assert s2v.get(n, v) == v, n
        out[n] = v
    assert out["g_popup_scale_num"] == G and out["g_stripe_period"] == PERIOD
    assert out["Buffer_tile"] == BUFFER_TILE and out["Buffer_copy_4"] == BUFFER_COPY_4
    cave = next(c for c in caves if c["id"] == "pcave2")
    assert int(cave["virtual_addr"]) == PCAVE2
    return out


# ---- asm (no `;` inside the asm text: keystone hangs on it) -------------------------------------------------------
# t_sb_tile2 (one thunk: the 256-byte gap does not hold a separate restripe entry).
# Entry stack: [esp] ret, +4 src, +8 a3, +0xC a4, +0x10 x, +0x14 y, +0x18 W, +0x1C H.  After `push esi` every arg
# is 4 higher, so seven `push [esp+0x20]` re-push H, W, y, x, a4, a3, src.  Buffer_tile_2 writes into its own arg
# slots (0x5DAA52 / 0x5DAAB7), which is why the rect is read from the CALLER's args after the call, never from the
# copies.  After the call + pushad (esi = dest, still): x +0x34, y +0x38, W +0x3C, H +0x40; pushad/popad keep
# every register, eax (Buffer_tile_2's result) included.
# The Buffer clip (+0x20..+0x2C) is always inside the buffer (Buffer_set_clip 0x5D8000 intersects with the bounds
# rect +0x30) and Buffer_tile_2 restores the caller's clip before it returns (0x5DAB70), so rect & clip is exactly
# the pixels the tile just wrote and a safe walk.  Registers after the clip: ecx = w, edx = y (first row),
# ebp = h, esi = stride (+0x4A8), edi = &px(l, t).
# Verify pass: al/ah = the first pixel of rows 0 / 1, `repe scasb` per row, xchg per row.  Rewrite pass: [esp]
# holds E (the even-dest-row member), [esp+1] O; `2 * (y mod P) < P` is (y mod P) < T.
def asm_tile2(s: dict[str, int]) -> str:
    return f"""
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      scaled
    push    {s['Buffer_tile_2']:#x}
    ret
scaled:
    push    esi
    mov     esi, ecx
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    call    {s['Buffer_tile_2']:#x}
    pushad
    mov     ebx, dword ptr [esi+0x54]
    test    ebx, ebx
    je      out
    mov     eax, dword ptr [esp+0x34]
    mov     ecx, dword ptr [esp+0x3C]
    add     ecx, eax
    cmp     eax, dword ptr [esi+0x20]
    jge     xl
    mov     eax, dword ptr [esi+0x20]
xl:
    cmp     ecx, dword ptr [esi+0x28]
    jle     xr
    mov     ecx, dword ptr [esi+0x28]
xr:
    sub     ecx, eax
    jle     out
    mov     edx, dword ptr [esp+0x38]
    mov     ebp, dword ptr [esp+0x40]
    add     ebp, edx
    cmp     edx, dword ptr [esi+0x24]
    jge     yt
    mov     edx, dword ptr [esi+0x24]
yt:
    cmp     ebp, dword ptr [esi+0x2C]
    jle     yb
    mov     ebp, dword ptr [esi+0x2C]
yb:
    sub     ebp, edx
    cmp     ebp, 2
    jl      out
    mov     esi, dword ptr [esi+0x4A8]
    mov     edi, edx
    imul    edi, esi
    add     edi, eax
    add     edi, ebx
    mov     al, byte ptr [edi]
    mov     ah, byte ptr [edi+esi]
    cmp     al, ah
    je      out
    push    edi
    push    ebp
vrow:
    push    ecx
    push    edi
    repe scasb
    pop     edi
    pop     ecx
    jne     vfail
    xchg    al, ah
    add     edi, esi
    dec     ebp
    jnz     vrow
    pop     ebp
    pop     edi
    mov     al, byte ptr [edi]
    mov     ah, byte ptr [edi+esi]
    test    dl, 1
    je      even
    xchg    al, ah
even:
    mov     ebx, dword ptr [{s['g_stripe_period']:#x}]
    push    eax
wrow:
    mov     eax, edx
    push    edx
    xor     edx, edx
    div     ebx
    add     edx, edx
    cmp     edx, ebx
    pop     edx
    mov     al, byte ptr [esp]
    jb      wtop
    mov     al, byte ptr [esp+1]
wtop:
    push    ecx
    push    edi
    rep stosb
    pop     edi
    pop     ecx
    add     edi, esi
    inc     edx
    dec     ebp
    jnz     wrow
    pop     eax
    jmp     out
vfail:
    pop     ebp
    pop     edi
out:
    popad
    pop     esi
    ret     0x1C
"""


THUNK_ORDER = ("t_sb_tile2",)
THUNK_NOTE = {
    "t_sb_tile2": "Buffer_tile_2 drop-in (RET 0x1C, device args): g<=16 native; else tile, then if (rect & clip) is a strict 1-row two-index parity dither rewrite it to the stripe law (even-row member on top)",
}


def _align(v: int, a: int = 16) -> int:
    return (v + a - 1) & ~(a - 1)


def assemble_all(syms: dict[str, int] | None = None, off_code: int = OFF_CODE) -> dict[str, tuple[int, bytes]]:
    """{name: (pcave2 offset, bytes)}."""
    s = syms or load_syms()
    src = asm_tile2(s)
    assert ";" not in src
    return {"t_sb_tile2": (off_code, SE.assemble(src, PCAVE2 + off_code))}


def names_of(layout) -> dict[str, int]:
    return {n: PCAVE2 + o for n, (o, _) in layout.items()}


def templatize(b: bytes, va: int, syms: dict[str, int], names: dict[str, int]) -> str:
    table = {v: n for n, v in syms.items()}
    table.update({v: n for n, v in names.items()})
    return SE.templatize(b, va, table)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ---- PROPOSALS: in-place replacements of two existing file-dialog thunks (NOT in the fragments) --------------------
# The LOAD/SAVE list child window stripes on its OWN buffer rows (backdrop tile at phase 0, row tiles with
# srcOffY == destY) while the frame ring around it stripes on the PARENT window's buffer rows.  The list sits at
# parent-local y = rRect1.top (Win +0x140; in-game dialog: native 32 -> 2g device px), so whenever that is not a
# multiple of P the two grids disagree and the ring's last stripe fuses with the list's first: one 4-row band
# along the list's top and bottom edge (1600x1200: screen y 290..293 and 740..743).  Fix = both list producers add
# the list's own parent-local top to the tile phase, exactly what vanilla's DatalinkWin_list_bg_fill / _row_bg do
# (srcOffY = [win+0x140] + y @0x42A127 / 0x42A179) and what the replaced Buffer_copy_4 capture did implicitly.
# `and eax, 3` is (top mod P) for P in {2, 4} -- every popup g (stripe_period: 2 below g = 22, else 4; g <= 40).
def asm_p_rowbg(s: dict[str, int]) -> str:
    return f"""
    cmp     dword ptr [{s['g_filedlg_active']:#x}], 0
    je      native
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      scaled
native:
    push    {s['Buffer_tile']:#x}
    ret
scaled:
    push    ecx
    call    {s['thunk_ensure_stripes']:#x}
    pop     ecx
    mov     eax, dword ptr [ecx{WIN_TOP_FROM_CANVAS:+#x}]
    and     eax, 3
    add     dword ptr [esp+0xC], eax
    mov     eax, dword ptr [{s['g_stripe_navy']:#x}]
    mov     edx, dword ptr [esp+4]
    cmp     edx, dword ptr [{s['g_filedlg_rowtile_sel']:#x}]
    jne     go
    mov     eax, dword ptr [{s['g_stripe_sel']:#x}]
go:
    mov     dword ptr [esp+4], eax
    jmp     native
"""


def asm_p_copy4(s: dict[str, int]) -> str:
    return f"""
    cmp     dword ptr [{s['g_filedlg_active']:#x}], 0
    je      native
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      scaled
native:
    push    {s['Buffer_copy_4']:#x}
    ret
scaled:
    call    {s['thunk_ensure_stripes']:#x}
    mov     ecx, dword ptr [esp+4]
    test    ecx, ecx
    je      done
    mov     eax, dword ptr [ecx{WIN_TOP_FROM_CANVAS:+#x}]
    and     eax, 3
    mov     edx, dword ptr [esp+0x1C]
    push    edx
    push    dword ptr [esp+0x1C]
    push    0
    push    0
    push    eax
    push    0
    push    dword ptr [{s['g_stripe_navy']:#x}]
    call    {s['Buffer_tile']:#x}
done:
    ret     0x1C
"""


def assemble_proposals(syms: dict[str, int] | None = None) -> dict[str, tuple[int, bytes, int]]:
    """{existing thunk id: (pcave2 offset, replacement bytes, slot limit)}."""
    s = syms or load_syms()
    out = {}
    for name, off, limit, fn in (("thunk_filedlg_rowbg_v6", P_ROWBG_OFF, P_ROWBG_LIMIT, asm_p_rowbg),
                                 ("thunk_copy4_stripes", P_COPY4_OFF, P_COPY4_LIMIT, asm_p_copy4)):
        src = fn(s)
        assert ";" not in src
        b = SE.assemble(src, PCAVE2 + off)
        assert off + len(b) <= limit, (name, len(b), limit - off)
        out[name] = (off, b, limit)
    return out


# ---- sites ------------------------------------------------------------------------------------------------------
# (id, function, call VA, native target, thunk, original bytes, note)
CELL_NOTE = ("call Buffer_tile_2 (20x20 mineral-cell tile, 1:1 into the strip canvas at device rects; pitch >= 8 path) "
             "-> tile, then the cell's own pair restriped to the stripe law")
SITES = [
    ("BaseWin_draw_production.cell_done", "BaseWin_draw_production", 0x40ECCA, BUFFER_TILE_2, "t_sb_tile2",
     "E8 21 BD 1C 00", CELL_NOTE),
    ("BaseWin_draw_production.cell_rest", "BaseWin_draw_production", 0x40ED33, BUFFER_TILE_2, "t_sb_tile2",
     "E8 B8 BC 1C 00", CELL_NOTE),
    ("BaseWin_draw_queue.row_tile", "BaseWin_draw_queue", 0x415404, BUFFER_TILE, "t_tile_force",
     "E8 57 54 1C 00",
     "call Buffer_tile (selected row [0x78D9D0] E0/E1 / hover row [0x78D980] AE/EE, srcOff == dest, strip canvas) "
     "-> tile, then fe's unconditional families restriped to the stripe law"),
]
RATIONALE = ("Above native scale the surface is tiled 1:1 from a native 1-row dither and nothing restripes it; the drop-in runs "
             "the native call unchanged, then rewrites the drawn rect (clipped to the dest clip) to the stripe law on the dest "
             "canvas's own row grid. g<=16: tail-jump to the native callee.")


def site_list() -> list[dict]:
    out = []
    for sid, fn, va, target, thunk, orig_hex, note in SITES:
        orig = bytes([0xE8]) + struct.pack("<i", target - (va + 5))
        assert hx(orig) == orig_hex, (sid, hx(orig), orig_hex)
        out.append({"id": sid, "function": fn, "va": va, "orig": orig, "thunk": thunk, "note": note})
    return out


# The 13 already-redirected base-canvas sites (adapter thunk -> Buffer_tile_2): listed for verify_live only.
ADAPTER_SITES = [(0x41165C, "thunk_bw_tile2")] + [(va, "thunk_bw_piptile") for va in (
    0x4132EB, 0x413390, 0x4133E7, 0x41342C, 0x413B83, 0x413C28, 0x413C8E, 0x413CD3,
    0x41444E, 0x4144E2, 0x4145B0, 0x4145F5)]


def verify_live(sites) -> list[str]:
    """Every site's original bytes must be what the PRISTINE base (.bak) holds."""
    out = []
    for s in sites:
        got = SE.base_exe_bytes(s["va"], len(s["orig"]))
        if got != s["orig"]:
            out.append(f"{s['id']} @{s['va']:#x}: base {hx(got)} != expected {hx(s['orig'])}")
    for va, _thunk in ADAPTER_SITES:
        want = bytes([0xE8]) + struct.pack("<i", BUFFER_TILE_2 - (va + 5))
        got = SE.base_exe_bytes(va, 5)
        if got != want:
            out.append(f"adapter site @{va:#x}: base {hx(got)} is not call Buffer_tile_2")
    return out


def site_yaml(sites) -> str:
    out = []
    for s in sites:
        out.append(f"""  - id: {s['id']}
    status: confirmed
    group: {GROUP}
    function: {s['function']}
    virtual_addr: {s['va']:#010x}
    length: 5
    original_bytes: "{hx(s['orig'])}"   # {s['note']}
    new_bytes:      "E8 {{rel32:{s['thunk']}}}"
    pattern: call_target_redirect
    rationale: "{RATIONALE}"
""")
    return "\n".join(out)


def roundtrip_problems(layout, syms) -> list[str]:
    """The emitted templates, resolved by the patcher's own ByteTemplate, must reproduce the assembled bytes."""
    names = names_of(layout)
    table = dict(syms)
    table.update(names)
    out = []
    for name, (off, b) in layout.items():
        tpl = templatize(b, PCAVE2 + off, syms, names)
        got = ap.ByteTemplate(tpl).resolve(PCAVE2 + off, table)
        if bytes(got) != b:
            out.append(f"{name}: template does not round-trip")
        for lit in (syms[n] for n in ("g_popup_scale_num", "g_stripe_period", "Buffer_tile_2")):
            if struct.pack("<I", lit).hex().upper() in tpl.replace(" ", ""):
                out.append(f"{name}: literal {lit:#x} left untemplatized")
    return out


def proposal_templates(syms) -> dict[str, tuple[int, str, int, int]]:
    """{id: (offset, template, length, limit)}; each template must round-trip through ByteTemplate."""
    out = {}
    for name, (off, b, limit) in assemble_proposals(syms).items():
        tpl = SE.templatize(b, PCAVE2 + off, {v: n for n, v in syms.items()})
        assert bytes(ap.ByteTemplate(tpl).resolve(PCAVE2 + off, dict(syms))) == b, name
        out[name] = (off, tpl, len(b), limit)
    return out


def main(argv) -> int:
    syms = load_syms()
    layout = assemble_all(syms)
    names = names_of(layout)
    ok = True
    end = max(o + len(b) for o, b in layout.values())
    print("; ==== base-screen cell stripes (assemble_stripes_base.py) ====")
    print(f"; block {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B); limit {OFF_LIMIT:#x}")
    if end > OFF_LIMIT:
        ok = False
        print("; OVERFLOW past the gap")
    sym_lines = [f"  {'Buffer_tile_2:':<31}{{ va: {BUFFER_TILE_2:#010x} }}"
                 "                           # __thiscall(destBuf, sprite, a3, a4, x, y, W, H); RET 0x1C; tiles a Sprite 1:1"]
    content_lines = []
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
    if "--proposals" in argv:
        print("; ---- PROPOSED in-place replacements of EXISTING entries (apply by hand) ----")
        for name, (off, tpl, n, limit) in proposal_templates(syms).items():
            print(f"; {name} @{off:#x}: {n}B (slot limit {limit:#x}, slack {limit - off - n}B)")
            print(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{tpl}\"")
        print("; thunk_bw_piptile  tail: '68 F0 A9 5D 00 C3' -> '68 {abs32:t_sb_tile2} C3'   (0 B delta)")
        print("; thunk_bw_tile2    tail: 'E9 BF 31 BC FF'    -> 'E9 {rel32:t_sb_tile2}'      (0 B delta)")
    elif "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag, "_fragment_stripes_base_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_stripes_base_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_stripes_base_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(site_yaml(sites))
        print("; fragments written to work/patches/_fragment_stripes_base_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print(site_yaml(sites))
    print(f"; group {GROUP}: members = {[s['id'] for s in sites]}, code_caves = ['pcave2']")
    print(f"; sites: {len(sites)}")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
