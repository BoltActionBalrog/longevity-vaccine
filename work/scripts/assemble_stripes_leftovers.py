#!/usr/bin/env python
"""Stripe-rule leftovers (group hud_backdrop_stripes), 2026-10-06: the HUD console backdrop + the devfill ring.

(a) HUD console SIDE-EDGE dotted columns.  MainWin_build blits the loaded console2_A.pcx (1024 x 257, palette
    +10 at load) into the strip window buffer with Buffer_copy_3 @0x459F65 (GDI StretchBlt; MEASURED centre-aligned
    NN on both axes: scaling_laws.nn_center_index, 97-99 % of the top strip rows of the 4K / 1080 shots, the rest
    overdrawn).  The art's vertical dotted separators (native columns 2 / 3, 245, 260, 763, 778, 1019: 1-row
    A,B,A,B dither, pairs 0F/8B and 1A/4F) come out as 3/2 runs at g = 40, 1/2 at g = 22 -- the one surface the
    console_tile_stripes group did not reach (the tiles cover the panel interiors; the separators are backdrop).
    Site 0x459F65 is unpatched (patches.yaml + _site_overlap: free).

    t_hud_backdrop  Buffer_copy_3 drop-in: thiscall ecx = src Buffer*; (dst, srcX, srcY, srcW, srcH, dstX, dstY,
                    dstW, dstH) RET 0x24.  g <= 16 -> `push Buffer_copy_3 / ret` (stack and registers untouched).
                    Else the engine blit runs with the same args (every pixel as today), then, if it returned 0
                    (success) and the args describe an in-bounds enlarge on both axes: per NATIVE column, mark the
                    texels of a vertical A,B,A,B window (A != B, neither the key 9: the committed column rule of
                    t_sbt_zoom / t_spr_stripes -- WITHOUT t_spr's neighbour condition, because the separators ARE
                    lone columns) with their mate and the pair's TOP (scaling_laws.pair_top: peak channel, then
                    channel sum, then the lower index, read from the dest buffer's colour table +0xA4), and rewrite
                    every dest pixel the StretchBlt filled from a marked texel (centre-NN inverse map, cut to the
                    dest clip) to TOP where stripe_top(dest-buffer row) else the mate -- only if the pixel still
                    holds the texel's index (a foreign draw or a wrong map degrades to no change).
    t_hb_col        one native column: mark pass (stack planes M = mate-or-texel, TP = top) + the dest-column run.
    t_hb_paint      one dest column: rows cut to the clip, stripe phase on the ABSOLUTE dest row (dstY + y).
    t_hb_setup      once per call: both rects inside their buffers, bases / pitches, the clip cut to the dest rect.
    Refusals (engine draw stays): copy failed (ret != 0), null dst / planes, period cell < 2, negative offsets,
    srcW 1..0x1000, srcH 4..0x200, dst dims 1..0x4000, not an enlarge on either axis, either rect out of its
    buffer, empty clip intersection.

(b) Base-screen buttons flanking GOVERNOR -- NOT built: see `--chev-model` and the brief.  The measured buttons
    are BaseWin btn18 / btn19 (0x6C1940 / 0x6C248C), routed by thunk_btn_bandstripe's bchev tail to
    thunk_chev_coverage: the user's deliberate exception.  Their three-tone columns (84 / 85 / C7 / DD) are the
    coverage filter's redmean blends, reproduced by scaling_laws.chevron_coverage_filter.

(c) ReportWin frames (F2 energy page): devfill's STEP3 (thunk_s54_restripe -> fe force path) is staged from the
    INSET rect [L+N, R-(N+1)] x [T+N, B-(N+1)], N = (g+15)>>4, while STEP1 (hollow_flat) draws the stroke K =
    stroke_width(g) wide.  N > K at g = 22 (2 vs 1) and the right / bottom insets are one deeper: a ring of
    STEP1's NN-banded fill survives between the stroke and the restriped interior (1080: the band's first fill
    column + last rows, the window's x = 514 and x = 1403..1404; 1600x1200: the right / bottom rows only).
    Fix = stage the FULL frame rect (the pair-member rewrite never touches a stroke, bevel or corner index):
    `--proposals` prints the exact 50-byte splice of the live cave entry thunk_box_thick_devfill (42 B + 8 NOPs,
    0 byte delta; the laws: devfill_stage_rect / devfill_frame_model below).

Parity: tests/test_stripes_leftovers_asm_parity.py.  Fragments: `py assemble_stripes_leftovers.py --fragments`.
Preview: `--preview` -> work/_portrait_preview/stripes_leftovers/.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
GROUP = "hud_backdrop_stripes"

# cave_map.py --fit (2026-10-06): free runs 0xA76B..0xA890 (293 B; 0x23ABF..0x23C20 was taken by t_dl_tile_ph while
# this was written), 0xFC5E..0xFDB0 (338 B), 0x218B1..0x21A00
# (335 B).  No run holds the whole thing; four thunks, each 16-aligned inside its run.  Move by editing SLOTS.
SLOTS = {                       # name: (offset, exclusive limit)
    "t_hud_backdrop": (0xA770, 0xA890),
    "t_hb_col": (0xFC60, 0xFDB0),
    "t_hb_paint": (0x218C0, 0x21930),
    "t_hb_setup": (0x21930, 0x21A00),      # the same free run as t_hb_paint, after it
}
THUNK_ORDER = ("t_hud_backdrop", "t_hb_col", "t_hb_paint", "t_hb_setup")

G = 0x00668740                  # g_popup_scale_num
PERIOD = 0x0066879C             # g_stripe_period (P = 2T)
BUFFER_COPY_3 = 0x005D9610      # thiscall(src; dst, srcX, srcY, srcW, srcH, dstX, dstY, dstW, dstH) RET 0x24
SITE = 0x00459F65               # MainWin_build: call Buffer_copy_3 (the console pcx -> strip window buffer)
SITE_ORIG = "E8 A6 F6 17 00"
KEY = 9                         # pcx index 255 + 10
QUAD = 4
MAX_SRC_H = 0x200               # stack planes: one byte per native row, two planes
FRAME = 0x48 + 2 * MAX_SRC_H    # locals + M + TP (< one page)
NATIVE_G = 16

SYM_NAMES = ("g_popup_scale_num", "g_stripe_period", "Buffer_copy_3")
THUNK_NOTE = {
    "t_hud_backdrop": "Buffer_copy_3 drop-in (RET 0x24) at MainWin_build 0x459F65: g<=16 push native/ret; else the engine stretch, then every vertical A,B,A,B dither texel of the console pcx regenerated on the stripe law in the strip buffer",
    "t_hb_col": "one native column of t_hud_backdrop: mark pass (stack planes mate / top via pair_top on the dest colour table) + the centre-NN dest-column run",
    "t_hb_paint": "one dest column of t_hud_backdrop: rows cut to the dest clip, pair top on stripe-top rows (absolute dest row), mate below, only where the pixel still holds the texel",
    "t_hb_setup": "t_hud_backdrop's once-per-call setup: both rects inside their buffers, rect bases / pitches, the dest clip cut to the dest rect (eax = 0 -> nothing to do)",
}


def load_syms(patches: Path | None = None) -> dict[str, int]:
    import apply_patches as ap
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    s2v = ap.build_symbol_table(symbols, caves)
    out = {n: s2v[n] for n in SYM_NAMES}
    assert out["g_popup_scale_num"] == G and out["g_stripe_period"] == PERIOD and out["Buffer_copy_3"] == BUFFER_COPY_3
    cave = next(c for c in caves if c["id"] == "pcave2")
    assert int(cave["virtual_addr"]) == PCAVE2
    return out


# ---- asm --------------------------------------------------------------------------------------------------------
# NO comments inside the asm text (keystone hangs on `;`); the notes live here.
#
# t_hud_backdrop.  Entry: ecx = src Buffer*, [esp] ret, +4 dst, +8 srcX, +0xC srcY, +0x10 srcW, +0x14 srcH,
# +0x18 dstX, +0x1C dstY, +0x20 dstW, +0x24 dstH.  Scaled: push ecx, nine `push [esp+0x28]` re-push dstH .. dst,
# call Buffer_copy_3 (callee-clean RET 0x24), pop ecx -> the entry stack again; pushad / popad: eax (the copy's
# result) and every register leave as the engine left them.  Frame: ebp = esp after pushad -> +0x24 dst, +0x28
# srcX, +0x2C srcY, +0x30 srcW, +0x34 srcH, +0x38 dstX, +0x3C dstY, +0x40 dstW, +0x44 dstH.
# Locals: -4 src rect base (data + srcY*pitchS + srcX)  -8 dst rect base  -0xC pitchS  -0x10 pitchD  -0x14 c
# -0x18 dcur (dest column cursor)  -0x1C ys  -0x20 ye  -0x24 xs  -0x28 xe (rect-relative, cut to the dest clip)
# -0x2C P  -0x48 rows left (srcW / srcH / dstW / dstH / dstY / dst are read from their arg slots)
# -0x4C chain (byte) -0x4B xor (byte) -0x4A top (byte).  Planes: M at [ebp-0x248, ebp-0x48), TP at
# [ebp-0x448, ebp-0x248).  Buffer fields: clip +0x20..+0x2C, data +0x54, W +0x80, H +0x84 (negative), colour
# table +0xA4 (RGBQUAD), stride +0x4A8.
def asm_hud_backdrop(s: dict[str, int], col: int, setup: int) -> str:
    return f"""
    cmp dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg scaled
    push {s['Buffer_copy_3']:#x}
    ret
scaled:
    push ecx
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    push dword ptr [esp+0x28]
    call {s['Buffer_copy_3']:#x}
    pop ecx
    pushad
    mov ebp, esp
    sub esp, {FRAME:#x}
    test eax, eax
    jne out
    mov esi, ecx
    mov edi, dword ptr [ebp+0x24]
    test edi, edi
    je out
    cmp dword ptr [esi+0x54], 0
    je out
    cmp dword ptr [edi+0x54], 0
    je out
    mov eax, dword ptr [{s['g_stripe_period']:#x}]
    cmp eax, 2
    jl out
    mov dword ptr [ebp-0x2C], eax
    mov eax, dword ptr [ebp+0x28]
    or eax, dword ptr [ebp+0x2C]
    or eax, dword ptr [ebp+0x38]
    or eax, dword ptr [ebp+0x3C]
    js out
    mov eax, dword ptr [ebp+0x30]
    lea edx, [eax-1]
    cmp edx, 0xFFF
    ja out
    mov eax, dword ptr [ebp+0x34]
    lea edx, [eax-{QUAD}]
    cmp edx, {MAX_SRC_H - QUAD}
    ja out
    mov eax, dword ptr [ebp+0x40]
    lea edx, [eax-1]
    cmp edx, 0x3FFF
    ja out
    mov eax, dword ptr [ebp+0x44]
    lea edx, [eax-1]
    cmp edx, 0x3FFF
    ja out
    cmp eax, dword ptr [ebp+0x34]
    jle out
    mov eax, dword ptr [ebp+0x40]
    cmp eax, dword ptr [ebp+0x30]
    jle out
    call {setup:#x}
    test eax, eax
    je out
    and dword ptr [ebp-0x14], 0
    and dword ptr [ebp-0x18], 0
cloop:
    call {col:#x}
    inc dword ptr [ebp-0x14]
    mov eax, dword ptr [ebp-0x14]
    cmp eax, dword ptr [ebp+0x30]
    jl cloop
out:
    mov esp, ebp
    popad
    ret 0x24
"""


# t_hb_setup: CALLED once inside the frame (esi = src Buffer*, edi = dst Buffer*): both rects inside their buffers
# (else eax = 0), the rect bases / pitches, the clip cut to [xs, xe) x [ys, ye) rect-relative (empty -> eax = 0).
def asm_hb_setup() -> str:
    return f"""
    xor eax, eax
    mov ecx, dword ptr [ebp+0x28]
    add ecx, dword ptr [ebp+0x30]
    cmp ecx, dword ptr [esi+0x80]
    jg sdone
    mov ecx, dword ptr [ebp+0x2C]
    add ecx, dword ptr [ebp+0x34]
    mov edx, dword ptr [esi+0x84]
    neg edx
    cmp ecx, edx
    jg sdone
    mov ecx, dword ptr [ebp+0x38]
    add ecx, dword ptr [ebp+0x40]
    cmp ecx, dword ptr [edi+0x80]
    jg sdone
    mov ecx, dword ptr [ebp+0x3C]
    add ecx, dword ptr [ebp+0x44]
    mov edx, dword ptr [edi+0x84]
    neg edx
    cmp ecx, edx
    jg sdone
    mov ecx, dword ptr [esi+0x4A8]
    mov dword ptr [ebp-0xC], ecx
    imul ecx, dword ptr [ebp+0x2C]
    add ecx, dword ptr [esi+0x54]
    add ecx, dword ptr [ebp+0x28]
    mov dword ptr [ebp-4], ecx
    mov ecx, dword ptr [edi+0x4A8]
    mov dword ptr [ebp-0x10], ecx
    imul ecx, dword ptr [ebp+0x3C]
    add ecx, dword ptr [edi+0x54]
    add ecx, dword ptr [ebp+0x38]
    mov dword ptr [ebp-8], ecx
    mov ecx, dword ptr [edi+0x20]
    sub ecx, dword ptr [ebp+0x38]
    jns xs_ok
    xor ecx, ecx
xs_ok:
    mov dword ptr [ebp-0x24], ecx
    mov ecx, dword ptr [edi+0x28]
    sub ecx, dword ptr [ebp+0x38]
    cmp ecx, dword ptr [ebp+0x40]
    jle xe_ok
    mov ecx, dword ptr [ebp+0x40]
xe_ok:
    mov dword ptr [ebp-0x28], ecx
    cmp ecx, dword ptr [ebp-0x24]
    jle sdone
    mov ecx, dword ptr [edi+0x24]
    sub ecx, dword ptr [ebp+0x3C]
    jns ys_ok
    xor ecx, ecx
ys_ok:
    mov dword ptr [ebp-0x1C], ecx
    mov ecx, dword ptr [edi+0x2C]
    sub ecx, dword ptr [ebp+0x3C]
    cmp ecx, dword ptr [ebp+0x44]
    jle ye_ok
    mov ecx, dword ptr [ebp+0x44]
ye_ok:
    mov dword ptr [ebp-0x20], ecx
    cmp ecx, dword ptr [ebp-0x1C]
    jle sdone
    inc eax
sdone:
    ret
"""


# t_hb_col: CALLED inside t_hud_backdrop's frame (ebp); plain ret; uses eax/ebx/ecx/edx/esi/edi freely (popad).
# Mark pass = t_spr_stripes' column walk: a window test at row r reads rows r..r+3 (only while 4 rows remain);
# when it hits, xor = A ^ B, top = ptop(A, B), chain = 4; each row stores M[r] = texel ^ (chain ? xor : 0)
# (= the mate when marked, the texel itself when not) and TP[r] = top while the chain runs.
# Dest-column run: dcur advances while nn_center_index(dcur, dstW, srcW) == c (the map is monotone and, for an
# enlarge, hits every source column), each dest column inside [xs, xe) painted by t_hb_paint.
# ptop / pk: key(i) = (peak(rgb) << 20) | (sum(rgb) << 8) | (255 - i) from the dest colour table; A is top iff
# key(A) >= key(B) -- exactly scaling_laws.pair_top's order (peak, then sum, then the lower index).
def asm_hb_col(paint: int) -> str:
    return f"""
    mov ecx, dword ptr [ebp-0x14]
    mov ebx, dword ptr [ebp-4]
    add ebx, ecx
    lea edi, [ebp-{0x48 + MAX_SRC_H:#x}]
    lea esi, [ebp-{0x48 + 2 * MAX_SRC_H:#x}]
    mov byte ptr [ebp-0x4C], 0
    mov eax, dword ptr [ebp+0x34]
    mov dword ptr [ebp-0x48], eax
mrow:
    cmp dword ptr [ebp-0x48], {QUAD}
    jl mnoquad
    mov ecx, dword ptr [ebp-0xC]
    mov al, byte ptr [ebx]
    mov dl, byte ptr [ebx+ecx]
    cmp al, dl
    je mnoquad
    cmp al, {KEY}
    je mnoquad
    cmp dl, {KEY}
    je mnoquad
    cmp al, byte ptr [ebx+ecx*2]
    jne mnoquad
    lea ecx, [ecx+ecx*2]
    cmp dl, byte ptr [ebx+ecx]
    jne mnoquad
    mov cl, al
    xor cl, dl
    mov byte ptr [ebp-0x4B], cl
    call ptop
    mov byte ptr [ebp-0x4A], al
    mov byte ptr [ebp-0x4C], {QUAD}
mnoquad:
    mov al, byte ptr [ebx]
    cmp byte ptr [ebp-0x4C], 0
    je mstore
    dec byte ptr [ebp-0x4C]
    xor al, byte ptr [ebp-0x4B]
    mov dl, byte ptr [ebp-0x4A]
    mov byte ptr [esi], dl
mstore:
    mov byte ptr [edi], al
    add ebx, dword ptr [ebp-0xC]
    inc edi
    inc esi
    dec dword ptr [ebp-0x48]
    jnz mrow
pcol:
    mov eax, dword ptr [ebp-0x18]
    cmp eax, dword ptr [ebp+0x40]
    jge pdone
    lea eax, [eax*2+1]
    imul eax, dword ptr [ebp+0x30]
    xor edx, edx
    mov ecx, dword ptr [ebp+0x40]
    add ecx, ecx
    div ecx
    cmp eax, dword ptr [ebp-0x14]
    jne pdone
    mov eax, dword ptr [ebp-0x18]
    cmp eax, dword ptr [ebp-0x24]
    jl padv
    cmp eax, dword ptr [ebp-0x28]
    jge padv
    call {paint:#x}
padv:
    inc dword ptr [ebp-0x18]
    jmp pcol
pdone:
    ret
ptop:
    push esi
    push ebx
    push edi
    mov esi, dword ptr [ebp+0x24]
    movzx ebx, al
    movzx edi, dl
    push ebx
    call pk
    push eax
    mov ebx, edi
    call pk
    pop ecx
    pop edx
    cmp ecx, eax
    jae ptop_a
    mov edx, edi
ptop_a:
    mov eax, edx
    pop edi
    pop ebx
    pop esi
    ret
pk:
    lea ecx, [esi+ebx*4+0xA4]
    movzx eax, byte ptr [ecx]
    movzx edx, byte ptr [ecx+1]
    cmp eax, edx
    jae pk1
    mov eax, edx
pk1:
    movzx edx, byte ptr [ecx+2]
    cmp eax, edx
    jae pk2
    mov eax, edx
pk2:
    shl eax, 20
    movzx edx, byte ptr [ecx]
    shl edx, 8
    add eax, edx
    movzx edx, byte ptr [ecx+1]
    shl edx, 8
    add eax, edx
    movzx edx, byte ptr [ecx+2]
    shl edx, 8
    add eax, edx
    mov edx, 255
    sub edx, ebx
    add eax, edx
    ret
"""


# t_hb_paint: dest column d = [ebp-0x18], rows y in [ys, ye): sy = nn_center_index(y, dstH, srcH); T = the texel;
# M[sy] == T -> unmarked.  Else pix = TP[sy] where 2 * ((dstY + y) mod P) < P (stripe_top), else T ^ M[sy] ^ TP[sy]
# (the other member); written only if the dest pixel still equals T.
def asm_hb_paint() -> str:
    return f"""
    mov edi, dword ptr [ebp-0x1C]
prow:
    cmp edi, dword ptr [ebp-0x20]
    jge pdone
    lea eax, [edi*2+1]
    imul eax, dword ptr [ebp+0x34]
    xor edx, edx
    mov ecx, dword ptr [ebp+0x44]
    add ecx, ecx
    div ecx
    mov ecx, eax
    imul ecx, dword ptr [ebp-0xC]
    add ecx, dword ptr [ebp-4]
    add ecx, dword ptr [ebp-0x14]
    mov dl, byte ptr [ecx]
    mov cl, byte ptr [ebp+eax-{0x48 + MAX_SRC_H:#x}]
    cmp cl, dl
    je pnext
    mov ch, byte ptr [ebp+eax-{0x48 + 2 * MAX_SRC_H:#x}]
    mov eax, edi
    add eax, dword ptr [ebp+0x3C]
    push edx
    xor edx, edx
    div dword ptr [ebp-0x2C]
    add edx, edx
    cmp edx, dword ptr [ebp-0x2C]
    pop edx
    jl ptopw
    xor ch, cl
    xor ch, dl
ptopw:
    mov eax, edi
    imul eax, dword ptr [ebp-0x10]
    add eax, dword ptr [ebp-8]
    add eax, dword ptr [ebp-0x18]
    cmp byte ptr [eax], dl
    jne pnext
    mov byte ptr [eax], ch
pnext:
    inc edi
    jmp prow
pdone:
    ret
"""


def assemble_all(syms: dict[str, int] | None = None) -> dict[str, tuple[int, bytes]]:
    import assemble_se as SE
    assert PCAVE2 == SE.PCAVE2 and G == SE.G
    s = syms or load_syms()
    col_va = PCAVE2 + SLOTS["t_hb_col"][0]
    paint_va = PCAVE2 + SLOTS["t_hb_paint"][0]
    setup_va = PCAVE2 + SLOTS["t_hb_setup"][0]
    out = {}
    for name, src in (("t_hud_backdrop", asm_hud_backdrop(s, col_va, setup_va)), ("t_hb_col", asm_hb_col(paint_va)),
                      ("t_hb_paint", asm_hb_paint()), ("t_hb_setup", asm_hb_setup())):
        assert ";" not in src
        off = SLOTS[name][0]
        out[name] = (off, SE.assemble(src, PCAVE2 + off))
    return out


def names_of(layout) -> dict[str, int]:
    return {n: PCAVE2 + o for n, (o, _) in layout.items()}


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def templatize(b: bytes, va: int, syms: dict[str, int], names: dict[str, int] | None = None) -> str:
    import assemble_se as SE
    table = {v: n for n, v in syms.items()}
    table.update({v: n for n, v in (names or {}).items()})
    return SE.templatize(b, va, table)


def roundtrip_problems(layout, syms) -> list[str]:
    import apply_patches as ap
    out = []
    names = names_of(layout)
    table = dict(syms)
    table.update(names)
    for name, (off, b) in layout.items():
        tpl = templatize(b, PCAVE2 + off, syms, names)
        got = ap.ByteTemplate(tpl).resolve(PCAVE2 + off, table)
        if bytes(got) != b:
            out.append(f"{name}: template does not round-trip")
        for lit in (syms[n] for n in SYM_NAMES):
            if struct.pack("<I", lit).hex().upper() in tpl.replace(" ", ""):
                out.append(f"{name}: literal {lit:#x} left untemplatized")
    return out


def slot_problems(layout, patches: Path | None = None) -> list[str]:
    """Each thunk inside its slot; no live cave entry or cave symbol of another module inside its span."""
    import apply_patches as ap
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    symtab = ap.build_symbol_table(symbols, caves)
    cave = next(c for c in caves if c["id"] == "pcave2")
    out = []
    for name, (off, b) in layout.items():
        lo, hi = off, off + len(b)
        if not (SLOTS[name][0] <= lo and hi <= SLOTS[name][1]):
            out.append(f"{name}: {lo:#x}..{hi:#x} leaves its slot {SLOTS[name][0]:#x}..{SLOTS[name][1]:#x}")
        for e in cave["contents"]:
            if e["id"] in layout:
                continue
            eo = int(e["offset"])
            n = sum(4 if tok.startswith("{") else 1 for tok in str(e["bytes"]).split())
            if eo < hi and lo < eo + n:
                out.append(f"{name}: {lo:#x}..{hi:#x} overlaps live entry {e['id']} {eo:#x}..{eo + n:#x}")
        for sym, va in symtab.items():
            if sym not in layout and PCAVE2 + lo <= va < PCAVE2 + hi:
                out.append(f"{name}: symbol {sym} ({va - PCAVE2:#x}) lies inside {lo:#x}..{hi:#x}")
    return out


# ---- the one exe site -------------------------------------------------------------------------------------------
SITES = [("MainWin_build.console_backdrop", "MainWin_build", SITE, BUFFER_COPY_3, "t_hud_backdrop", SITE_ORIG,
          "call Buffer_copy_3 (console2_A.pcx 1024x257 -> the strip window buffer at window dims, GDI StretchBlt) -> "
          "the same stretch, then the art's vertical 1-row dither (panel-edge dotted separators) regenerated on the stripe law")]
RATIONALE = ("The console backdrop is a GDI StretchBlt (centre-aligned NN) of native 1-row dither art, and nothing restripes "
             "the columns the panel tiles do not cover; the drop-in runs the native blit unchanged, then rewrites every dest "
             "pixel mapped from a vertical A,B,A,B texel of the pcx to the pair's top on stripe-top rows of the strip "
             "buffer and its mate below (scaling_laws.stripe_top / pair_top). g<=16: tail-jump to the native callee.")


def site_list() -> list[dict]:
    out = []
    for sid, fn, va, target, thunk, orig_hex, note in SITES:
        orig = bytes([0xE8]) + struct.pack("<i", target - (va + 5))
        assert hx(orig) == orig_hex, (sid, hx(orig), orig_hex)
        out.append({"id": sid, "function": fn, "va": va, "orig": orig, "thunk": thunk, "note": note})
    return out


def verify_live(sites) -> list[str]:
    import assemble_se as SE
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
    function: {s['function']}
    virtual_addr: {s['va']:#010x}
    length: 5
    original_bytes: "{hx(s['orig'])}"   # {s['note']}
    new_bytes:      "E8 {{rel32:{s['thunk']}}}"
    pattern: call_target_redirect
    rationale: "{RATIONALE}"
""")
    return "\n".join(out)


# ==== the laws: scaling_laws "stripe regeneration" section (fix 7, 2026-10-17) ===================================
# stretchblt_centre_nn, column_dither_marks, pair_top_by_colour, vertical_dither_regen (dest-driven), devfill_inset,
# devfill_stage_rect live in scaling_laws.py.  hb_synth below is the SOURCE-driven restatement of
# vertical_dither_regen the preview renders; the parity test requires the two to agree.
def hb_synth(dest: bytearray, stride: int, src_rows, g: int, rgb, *, sx: int = 0, sy: int = 0, sw: int, sh: int,
             dx: int, dy: int, dw: int, dh: int, clip, key: int = KEY) -> None:
    """t_hud_backdrop at g > 16: the engine stretch, then every dest pixel mapped (centre NN) from a marked texel,
    inside the dest clip (half-open l, t, r, b, buffer space) and still holding the texel's index, takes the
    pair's top where scaling_laws.stripe_top(dest-buffer row, g), else the mate."""
    SL.stretchblt_centre_nn(dest, stride, src_rows, sx=sx, sy=sy, sw=sw, sh=sh, dx=dx, dy=dy, dw=dw, dh=dh)
    if g <= NATIVE_G or not (dw > sw and dh > sh) or sh < QUAD or sh > MAX_SRC_H:
        return
    marks = SL.column_dither_marks(src_rows, key, rect=(sx, sy, sw, sh))
    xs, xe = max(0, clip[0] - dx), min(dw, clip[2] - dx)
    ys, ye = max(0, clip[1] - dy), min(dh, clip[3] - dy)
    for y in range(ys, ye):
        r = SL.nn_center_index(y, dh, sh)
        for x in range(xs, xe):
            c = SL.nn_center_index(x, dw, sw)
            mate = marks.get((r, c))
            if mate is None:
                continue
            v = src_rows[sy + r][sx + c]
            o = (dy + y) * stride + dx + x
            if dest[o] != v:
                continue
            top = SL.pair_top_by_colour(v, mate, rgb)
            dest[o] = top if SL.stripe_top(dy + y, g) else (v ^ mate ^ top)


# ---- (c) devfill STEP3: stage the full frame rect -----------------------------------------------------------------
def devfill_stage_rect(rect, g: int, *, proposed: bool):
    """(x, y, w, h) staged into g_fe_* by devfill STEP3 for the (inclusive-R/B) frame rect.  proposed (= the live
    bytes since 2026-10-06): scaling_laws.devfill_stage_rect, the whole frame; not proposed: the history, the
    SL.devfill_inset scratch rect, inclusive.  g <= 16: devfill is native (no staging)."""
    if proposed:
        return SL.devfill_stage_rect(rect)
    l, t, r, b = rect
    n = SL.devfill_inset(g)
    return l + n, t + n, (r - (n + 1)) - (l + n) + 1, (b - (n + 1)) - (t + n) + 1


def devfill_frame_model(rect, g: int, top: int, mate: int, stroke: int, *, proposed: bool, k_right: int | None = None):
    """A devfill frame on a blank canvas as rows (bytearrays), inclusive rect (L, T, R, B), fill pair (top, mate):
    STEP1 = hollow_flat: strokes K = stroke_width(g) on the left / top, k_right (measured: one less at fractional g;
    default K) on the right / bottom, fill = the native 1-row dither centre-NN enlarged (dest rows alternate by the
    engine's map); STEP2 = the 1-row tile at 1:1 over the inset rect (half-open); STEP3 = every pair pixel of the
    staged rect to hatch_row_color.  Returns (rows, width, height) of a canvas exactly the frame's size."""
    l, t, r, b = rect
    w, h = r - l + 1, b - t + 1
    k = SL.stroke_width(g)
    kr = k if k_right is None else k_right
    rows = [bytearray([stroke]) * w for _ in range(h)]
    nh = max(2, round(h * 16 / g))                     # native rows of the frame (fill rows alternate 1:1)
    for y in range(h):
        for x in range(w):
            if y < k or x < k or y > h - 1 - kr or x > w - 1 - kr:
                continue
            nat = SL.nn_center_index(y, h, nh)
            rows[y][x] = top if (nat & 1) == 0 else mate
    n = SL.devfill_inset(g)
    for y in range(t + n, b - (n + 1)):               # STEP2 half-open [T+N, B-(N+1))
        for x in range(l + n, r - (n + 1)):
            rows[y - t][x - l] = top if ((y & 1) == 0) else mate
    sx, sy, sw, sh = devfill_stage_rect(rect, g, proposed=proposed)
    for y in range(sy, sy + sh):
        for x in range(sx, sx + sw):
            v = rows[y - t][x - l]
            if v in (top, mate):
                rows[y - t][x - l] = top if SL.stripe_top(y, g) else mate
    return rows, w, h


def devfill_proposal(patches: Path | None = None) -> dict:
    """The exact token splice of the live thunk_box_thick_devfill entry: {offset, old, new, entry_len}."""
    import apply_patches as ap
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    cave = next(c for c in caves if c["id"] == "pcave2")
    e = next(c for c in cave["contents"] if c["id"] == "thunk_box_thick_devfill")
    toks = str(e["bytes"]).split()
    old = ("A1 {abs32:g_devfill_rect} A3 {abs32:g_fe_x} 8B 15 {abs32:g_devfill_rect_R} 29 C2 42 89 15 {abs32:g_fe_w} "
           "A1 {abs32:g_devfill_rect_T} A3 {abs32:g_fe_y} 8B 15 {abs32:g_devfill_rect_B} 29 C2 42 89 15 {abs32:g_fe_h}").split()
    new = ("8B 7D F8 8B 07 A3 {abs32:g_fe_x} 8B 57 08 29 C2 42 89 15 {abs32:g_fe_w} 8B 47 04 A3 {abs32:g_fe_y} "
           "8B 57 0C 29 C2 42 89 15 {abs32:g_fe_h} 90 90 90 90 90 90 90 90").split()
    nb = lambda ts: sum(4 if x.startswith("{") else 1 for x in ts)  # noqa: E731
    assert nb(old) == nb(new) == 50
    idx = -1
    applied = False
    for i in range(len(toks) - len(old) + 1):
        if toks[i:i + len(old)] == old:
            idx = i
            break
    if idx < 0:                                   # applied 2026-10-06: the live entry already carries the new run
        for i in range(len(toks) - len(new) + 1):
            if toks[i:i + len(new)] == new:
                idx, applied = i, True
                break
    byte_off = nb(toks[:idx]) if idx >= 0 else -1
    return {"entry": "thunk_box_thick_devfill", "offset": int(e["offset"]), "tok_index": idx, "byte_off": byte_off,
            "old": " ".join(old), "new": " ".join(new), "entry_len": nb(toks), "found": idx >= 0, "applied": applied,
            "patched_tokens": (toks if applied else toks[:idx] + new + toks[idx + len(old):]) if idx >= 0 else None}


# ---- (b) evidence: the chevron coverage fingerprint ----------------------------------------------------------------
CHEV_MEASURED = {
    (22, "1920x1080 ...011213 x=818 rows 130..149"): "84 84 DD 85 84 C7 84 85 DD 84 DD 85 84 C7 84 85 C7 84 DD 84",
    (25, "1600x1200 ...011037 x=664 rows 122..141"): "C7 84 85 C7 84 85 C7 84 84 C7 84 84 C7 84 84 C7 85 85 C7 6D",
}


def chev_model(pal) -> list[str]:
    """scaling_laws.chevron_coverage_filter over a pure 1-row 84/C7 column (the chevron face dither) at the
    g of each measured shot; the longest run of consecutive measured tones found in the model column."""
    out = []
    for (g, label), seq in CHEV_MEASURED.items():
        meas = seq.split()
        best = (0, "", 0, 0)
        for s in (16, 17, 18, 19, 20):
            d = (s * g) // 16
            for phase in (0, 1):
                src = [[(0x84 if ((r + phase) & 1) == 0 else 0xC7)] * s for r in range(s)]
                col = [f"{v:02X}" for v in (row[s // 2] for row in SL.chevron_coverage_filter(src, pal, d, key=9))]
                for i in range(len(meas)):
                    for j in range(len(col)):
                        n = 0
                        while i + n < len(meas) and j + n < len(col) and meas[i + n] == col[j + n]:
                            n += 1
                        if n > best[0]:
                            best = (n, " ".join(col), s, phase)
        out.append(f"g={g} {label}: measured {seq}\n   model S={best[2]} phase={best[3]}: {best[1]}\n"
                   f"   longest common run of consecutive tones: {best[0]} of {len(meas)}")
    return out


# ==== preview ====================================================================================================
PREVIEW_DIR = Path(__file__).resolve().parent.parent / "_portrait_preview" / "stripes_leftovers"
PALETTE_BIN = Path(__file__).resolve().parent.parent / "_portrait_preview" / "hd" / "game_palette_rgbquad.bin"
PREVIEW_G = (22, 25, 40)
CONSOLE_PCX = "console2_A.pcx"
CONSOLE_W, CONSOLE_H = 1024, 257
ZOOM_COLS = ((0, 14), (240, 266), (758, 784), (1010, 1024))     # native column spans around the separators
ZOOM_ROWS = (120, 180)


def load_palette():
    d = PALETTE_BIN.read_bytes()
    return [(d[i * 4 + 2], d[i * 4 + 1], d[i * 4]) for i in range(256)]


def load_console():
    import config
    from PIL import Image
    im = Image.open(os.path.join(str(config.game_dir()), CONSOLE_PCX))
    w, h = im.size
    d = im.tobytes()
    return [[(d[yy * w + xx] + 10) & 0xFF for xx in range(w)] for yy in range(h)]


def _img(rows_bytes, w, h, pal):
    from PIL import Image
    im = Image.frombytes("P", (w, h), bytes(rows_bytes))
    im.putpalette([ch for rgb in pal for ch in rgb])
    return im.convert("RGB")


def preview(out_dir: Path | None = None) -> list[Path]:
    from PIL import Image, ImageDraw
    out_dir = Path(out_dir or PREVIEW_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    pal = load_palette()
    rgb = lambda i: pal[i]  # noqa: E731
    src = load_console()
    written = []
    for g in PREVIEW_G:
        dw, dh = (CONSOLE_W * g) // 16, (CONSOLE_H * g) // 16
        today = bytearray(dw * dh)
        SL.stretchblt_centre_nn(today, dw, src, sx=0, sy=0, sw=CONSOLE_W, sh=CONSOLE_H, dx=0, dy=0, dw=dw, dh=dh)
        prop = bytearray(dw * dh)
        hb_synth(prop, dw, src, g, rgb, sw=CONSOLE_W, sh=CONSOLE_H, dx=0, dy=0, dw=dw, dh=dh, clip=(0, 0, dw, dh))
        a, b = _img(today, dw, dh, pal), _img(prop, dw, dh, pal)
        sheet = Image.new("RGB", (dw, 2 * dh + 40), (40, 40, 40))
        sheet.paste(a, (0, 18))
        sheet.paste(b, (0, dh + 38))
        d = ImageDraw.Draw(sheet)
        d.text((4, 3), f"TODAY (StretchBlt centre NN)  g={g}  T={SL.stripe_rows(g)}  1x  (panel interiors are tiled over in-game)", fill=(255, 255, 255))
        d.text((4, dh + 23), f"PROPOSED (t_hud_backdrop: vertical A,B,A,B texels regenerated)  g={g}  1x", fill=(255, 255, 255))
        p = out_dir / f"console_g{g}_1x.png"
        sheet.save(p)
        written.append(p)
        crops = []
        for (c0, c1) in ZOOM_COLS:
            x0, x1 = (c0 * g) // 16, (c1 * g) // 16
            y0, y1 = (ZOOM_ROWS[0] * g) // 16, (ZOOM_ROWS[1] * g) // 16
            ca = a.crop((x0, y0, x1, y1)).resize(((x1 - x0) * 4, (y1 - y0) * 4), Image.NEAREST)
            cb = b.crop((x0, y0, x1, y1)).resize(((x1 - x0) * 4, (y1 - y0) * 4), Image.NEAREST)
            crops.append((ca, cb, c0, c1))
        W = sum(ca.width + 12 for ca, _cb, _c0, _c1 in crops) + 12
        H = max(ca.height for ca, _cb, _c0, _c1 in crops)
        sheet = Image.new("RGB", (W, 2 * H + 48), (40, 40, 40))
        d = ImageDraw.Draw(sheet)
        d.text((4, 3), f"TODAY g={g} 4x: native columns {ZOOM_COLS}, rows {ZOOM_ROWS}", fill=(255, 255, 255))
        d.text((4, H + 27), f"PROPOSED g={g} 4x", fill=(255, 255, 255))
        x = 12
        for ca, cb, c0, c1 in crops:
            sheet.paste(ca, (x, 20))
            sheet.paste(cb, (x, H + 44))
            x += ca.width + 12
        p = out_dir / f"console_g{g}_4x.png"
        sheet.save(p)
        written.append(p)
    # (c) devfill ring: a report title band (native 300 x 20, pair C2/41, stroke 1D) and a window corner (C6/41, 1A)
    for g in PREVIEW_G:
        k = SL.stroke_width(g)
        kr = max(0, k - 1) if g % 16 else k            # measured: the right / bottom stroke loses a pixel at fractional g
        panels = []
        for (nw, nh, top, mate, stroke, label) in ((300, 20, 0xC2, 0x41, 0x1D, "title band C2/41"),
                                                   (120, 60, 0xC6, 0x41, 0x1A, "window edge C6/41")):
            rect = (0, 0, (nw * g) // 16 - 1, (nh * g) // 16 - 1)
            for proposed in (False, True):
                rows, w, h = devfill_frame_model(rect, g, top, mate, stroke, proposed=proposed, k_right=kr)
                panels.append((label, proposed, _img(b"".join(rows), w, h, pal)))
        H = max(im.height for _l, _p, im in panels)
        W = max(im.width for _l, _p, im in panels)
        sheet = Image.new("RGB", (2 * W + 36, 2 * H + 60), (40, 40, 40))
        d = ImageDraw.Draw(sheet)
        for i, (label, proposed, im) in enumerate(panels):
            cx, cy = 12 + (W + 12) * (1 if proposed else 0), 20 + (H + 20) * (i // 2)
            sheet.paste(im, (cx, cy))
            d.text((cx, cy - 14), f"{'PROPOSED' if proposed else 'TODAY'} g={g} K={k} N={SL.devfill_inset(g)}: {label}", fill=(255, 255, 255))
        p = out_dir / f"devfill_g{g}_1x.png"
        sheet.save(p)
        written.append(p)
        # 4x: the LEFT-TOP corner of every panel (the ring lives on the frame's edges), today beside proposed
        crops = [(label, proposed, im.crop((0, 0, min(60, im.width), min(48, im.height))).resize((min(60, im.width) * 4, min(48, im.height) * 4), Image.NEAREST))
                 for label, proposed, im in panels]
        cw, ch = max(c.width for _l, _p, c in crops), max(c.height for _l, _p, c in crops)
        sheet4 = Image.new("RGB", (2 * cw + 36, 2 * ch + 60), (40, 40, 40))
        d = ImageDraw.Draw(sheet4)
        for i, (label, proposed, c) in enumerate(crops):
            cx, cy = 12 + (cw + 12) * (1 if proposed else 0), 20 + (ch + 20) * (i // 2)
            sheet4.paste(c, (cx, cy))
            d.text((cx, cy - 14), f"{'PROPOSED' if proposed else 'TODAY'} g={g} 4x top-left corner: {label}", fill=(255, 255, 255))
        p = out_dir / f"devfill_g{g}_4x.png"
        sheet4.save(p)
        written.append(p)
    return written


def main(argv) -> int:
    if "--preview" in argv:
        for p in preview():
            print(p)
        return 0
    if "--chev-model" in argv:
        for line in chev_model(load_palette()):
            print(line)
        return 0
    if "--proposals" in argv:
        pr = devfill_proposal()
        print(f"; patches.yaml cave entry {pr['entry']} @pcave2+{pr['offset']:#x} ({pr['entry_len']} B): token run found = {pr['found']}, "
              f"at byte offset +{pr['byte_off']:#x} (token index {pr['tok_index']})")
        print(f";   old: {pr['old']}")
        print(f";   new: {pr['new']}")
        return 0 if pr["found"] else 1
    syms = load_syms()
    layout = assemble_all(syms)
    ok = True
    print("; ==== stripe-rule leftovers (assemble_stripes_leftovers.py) ====")
    for p in slot_problems(layout):
        ok = False
        print("; SLOT:", p)
    names = names_of(layout)
    sym_lines, content_lines = [], []
    for name in THUNK_ORDER:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {GROUP} ({len(b)}B) {THUNK_NOTE[name]}")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, syms, names)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x} (slot ends {SLOTS[name][1]:#x}, {SLOTS[name][1] - off - len(b)}B spare)")
    for p in roundtrip_problems(layout, syms):
        ok = False
        print("; TEMPLATE:", p)
    sites = site_list()
    for p in verify_live(sites):
        ok = False
        print("; LIVE MISMATCH:", p)
    sym_line, content = "\n".join(sym_lines), "\n".join(content_lines)
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        for suffix, text in (("symbols", sym_line + "\n"), ("cave", content + "\n"), ("sites", site_yaml(sites))):
            with open(os.path.join(frag, f"_fragment_stripes_leftovers_{suffix}.yaml"), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        print("; fragments written to work/patches/_fragment_stripes_leftovers_*.yaml")
    else:
        print(sym_line)
        print(content)
        print(site_yaml(sites))
    print(f"; group {GROUP}: members = {[s['id'] for s in sites]}, code_caves = ['pcave2']")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
