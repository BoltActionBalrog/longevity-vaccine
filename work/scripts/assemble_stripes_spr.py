#!/usr/bin/env python
"""Assembler + law + preview for the small-sprite dither regeneration (group sprite_stripes), 2026-10-05.

Two families of small keyed sprites are drawn by the engine's Sprite_draw_2 at num/den = g/16 (plain nearest
neighbour), so the 1-row dither baked into their art comes out as uneven runs (1,2,1,1,2 at g = 22; 2,3 at 40):

  (1) Social Engineering: the 90 effect / SOCIETY icons (socwin.pcx 26x26 grid) and the 10 digits (13x13),
      five sites -> thunk_se_sd2;
  (2) the diplomacy console faction logos (<faction>.pcx (436,457) 65x50), one site -> t_dp_sd2_logo.

MEASURED (socwin.pcx, the 14 faction pcx; palette +10 at load): the art is pixel art under a 1-row scanline
overlay.  Dither = vertical A,B,A,B alternation, per column; no 2-D checker.  Every pair index ALSO occurs as a
solid / edge colour in the same sprite, the pairs differ per icon colour variant (98/1A, 67/69, E0/E1, C4/41, ...),
several pairs share a member, and anti-aliased edge texels belong to no pair.  So no index test and no per-sprite
vote can separate dither from art: the classification must be per TEXEL, on the native sprite.

Thunks (pcave2):
  t_spr_stripes   Sprite_draw_2 drop-in (thiscall ecx = Sprite*; dest, key, x, y, num, den; RET 0x18), reached as the
                  jmp TAIL of thunk_se_sd2 and t_dp_sd2_logo.
    num <= den -> `push Sprite_draw_2 / ret`, stack and registers untouched (the native path, byte for byte).
    num >  den -> re-push the six args and CALL Sprite_draw_2: the engine draws exactly as today (silhouette, key
                  skip, clip, every pixel).  Then a post-pass walks the NATIVE sprite column by column: a texel is
                  DITHER iff it lies in a vertical window of four rows A,B,A,B (A != B, neither the key) -- the
                  committed rule of t_sbt_zoom / btn_dither_marks -- AND its left or right neighbour texel does too
                  (a scanline is a row property; a lone alternating column is art).  Pass 1 (t_spr_stripes) writes
                  each texel's mate into a stack plane; pass 2 (t_spr_paint, its own cave run: no single free run
                  holds both) paints.  For a dither texel the pass visits exactly the
                  dest pixels the engine filled from that texel -- the engine's OWN run table g_sprite_scale_runs
                  (0x9B3AD8, the table its expand loop walks; valid iff the cache pair 0x696D20/24 equals num/den)
                  from the engine's own origin (x + (off * g >> 4)) -- and rewrites a pixel ONLY IF it still holds
                  that texel's index, to the pair's TOP member where (dest row mod P) < T, else its mate
                  (P = g_stripe_period, T = P / 2).  TOP = the brighter member by r + g + b of the dest buffer's own
                  colour table (+0xA4), ties -> the lower index: the bright stripe of every icon lands on the same
                  dest-buffer rows as the chrome's (pair_top), whatever row parity the artist used per icon.
  It cannot touch a non-dither pixel: the only pixels visited are those mapped from a texel inside an A,B,A,B window,
  and each is written only if it equals that texel's index (so a wrong map, a clipped pixel or a foreign drawer
  degrades to "no change").  Nothing is blended, no row is reordered: shape = the engine's NN, shade = dest row.

Every refusal (no pixel plane, filename-backed sprite, engine table not built for this ratio, origin left / above
the buffer, sprite lower than 4 rows or over 0xD00 texels / 0x320 per axis, period cell < 2) leaves the engine's draw
as it is.  The plain-NN port below reproduces the user's SE shots pixel for pixel (19 icons each at 1920x1080 and
1600x1200, 2 at 3840x2160: 0 mismatching pixels).

The laws at the bottom (sd2_runs / sd2_rect / sd2_draw / spr_marks / spr_pair_top / spr_synth) are the SPEC; they
belong in scaling_laws.py (this module may not edit it).  sd2_runs / sd2_draw are a port of the engine bytes
(0x5EB20F, 0x5E4ECE..0x5E57FA) and are checked against the REAL bytes under Unicorn in the parity test.

Parity: tests/test_stripes_spr_asm_parity.py.  Fragments: `py assemble_stripes_spr.py --fragments`.
Preview:  `py assemble_stripes_spr.py --preview`  -> work/_portrait_preview/stripes_spr/.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
GROUP = "sprite_stripes"

# cave_map.py --min-gap 0x100 (2026-10-05): free runs 0x0F9E4..0x0FB90 (428 B) and 0x21E7A..0x22000 (390 B).  No
# single free run holds both passes, so the paint pass is its own thunk; move either by editing SLOTS only.
SLOTS = {                      # name: (offset, exclusive limit)
    "t_spr_stripes": (0xF9E4, 0xFB90),
    "t_spr_paint": (0x21E7C, 0x22000),
}
OFF_CODE = SLOTS["t_spr_stripes"][0]
THUNK_ORDER = ("t_spr_stripes", "t_spr_paint")
MAX_TEXELS = 0xD00             # the stack mate plane: one byte per native texel (65 x 50 logo cell = 3250)
FRAME = 0x48 + MAX_TEXELS      # < one page: no stack probe needed

G = 0x00668740                 # g_popup_scale_num
PERIOD = 0x0066879C            # g_stripe_period (P = 2T)
SPRITE_DRAW_2 = 0x005E4B4A     # thiscall(Sprite*; dest, key, x, y, num, den) RET 0x18
CACHE_NUM = 0x00696D20         # g_sprite_scale_cache_num
CACHE_DEN = 0x00696D24         # g_sprite_scale_cache_den
RUNS = 0x009B3AD8              # g_sprite_scale_runs[0x320]: dest run length per source index, current ratio
RUNS_MAX = 0x320
QUAD = 4                       # rows of the vertical A,B,A,B window
NATIVE_G = 16

SYM_NAMES = ("g_popup_scale_num", "g_stripe_period", "Sprite_draw_2")
THUNK_NOTE = {
    "t_spr_stripes": "Sprite_draw_2 drop-in (RET 0x18), jmp tail of thunk_se_sd2 / t_dp_sd2_logo: engine draw, then mark the native sprite's vertical A,B,A,B dither texels (stack mate plane) and call t_spr_paint; num <= den -> push Sprite_draw_2 / ret",
    "t_spr_paint": "pass 2 of t_spr_stripes (called inside its frame, plain ret): dest pixels the engine filled from a dither texel -> the pair's brighter member on stripe-top rows / its mate below, through the engine's own run table g_sprite_scale_runs",
}


def load_syms(patches: Path | None = None) -> dict[str, int]:
    import apply_patches as ap
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    s2v = ap.build_symbol_table(symbols, caves)
    out = {n: s2v[n] for n in SYM_NAMES}
    assert out["g_popup_scale_num"] == G and out["g_stripe_period"] == PERIOD and out["Sprite_draw_2"] == SPRITE_DRAW_2
    cave = next(c for c in caves if c["id"] == "pcave2")
    assert int(cave["virtual_addr"]) == PCAVE2
    return out


# ---- asm --------------------------------------------------------------------------------------------------------
# NO comments inside the asm text (keystone hangs on `;`); the notes live here.
#
# Entry: ecx = Sprite*, [esp] ret, +4 dest, +8 key, +0xC x, +0x10 y, +0x14 num, +0x18 den.
# Native gate on the ARGS (thunk_se_sd2 writes num = g, den = 16 at every g; t_dp_sd2_logo never arrives at g <= 16).
# Scaled: push ecx (the Sprite*, the engine clobbers it), six `push [esp+0x1C]` re-push den, num, y, x, key, dest,
# call Sprite_draw_2 (callee-clean), pop ecx -> the stack is the entry stack again.  pushad / popad: eax (the draw's
# result) and every register leave as the engine left them (ecx = the Sprite*; it is caller-saved).
# Frame: ebp = esp after pushad -> +0x24 dest, +0x28 key, +0x2C x, +0x30 y, +0x34 num, +0x38 den.  esi = Sprite*,
# edi = dest Buffer*.  Locals:
#   -4 xs  -8 xe  -0xC ys  -0x10 ye      the engine rect & dest clip (+0x20..+0x2C) & buffer (W +0x80, H +0x84 negative)
#   -0x14 c  -0x18 dx (dest x of column c's run)  -0x1C rows left  -0x20 dy (dest y of the row's run)
#   -0x24 chain rows left (byte), -0x23 top, -0x22 mate
#   -0x28 / -0x2C the column run clipped [x0, x1)   -0x30 pitch (+0xC)  -0x34 dest plane (+0x54)  -0x38 stride (+0x4A8)
#   -0x3C Y0  -0x44 / -0x48 the row run clipped [y, y1)
# Guards (all -> out, the engine draw stays): dest NULL / no plane; cache pair != (num, 16) (the engine rejected the
# ratio or bailed before the table was current; the engine sets the pair from the args it drew with, so this also
# pins den = 16); filename-backed sprite ([+0] != 0: the engine drew
# through its canvas path) or no pcBits (+4); P < 2 (divisor); w not in 1..0x320, h not in 4..0x320 (table length /
# no window fits); X0 or Y0 negative (ftol truncates toward zero, the floor below would differ; such a draw is partly
# off the buffer anyway).
# Sprite: pcBits +4, pitch +0xC, blit w +0x10, blit h +0x14, draw offsets +0x20 / +0x24 (the fields the engine blit
# reads at 0x5E4ECE..0x5E4F25).  X0 = x + (off * num >> 4) = ftol(x + off * num / 16) for a non-negative sum.
# Column walk = t_sbt_zoom's pass 1: a window test at row r reads rows r..r+3 (only while 4 rows remain); the chain
# counter marks the 4 rows of the window.  Brightness: (b + g + r) of RGBQUAD [edi + i*4 + 0xA4]; ecx = sum(A) - sum(B),
# A stays top when ecx > 0, or ecx == 0 and A < B.
# Stripe row: 2 * (Y mod P) >= P <=> bottom (stripe_top's hN = P / 2 for the even P the cell holds).
def asm_spr_stripes(s: dict[str, int], paint: int) -> str:
    return f"""
    mov eax, dword ptr [esp+0x14]
    cmp eax, dword ptr [esp+0x18]
    jg scaled
    push {s['Sprite_draw_2']:#x}
    ret
scaled:
    push ecx
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    call {s['Sprite_draw_2']:#x}
    pop ecx
    pushad
    mov ebp, esp
    sub esp, {FRAME:#x}
    mov esi, ecx
    mov edi, dword ptr [ebp+0x24]
    test edi, edi
    jne have_dest
out0:
    mov esp, ebp
    popad
    ret 0x18
have_dest:
    mov eax, dword ptr [edi+0x54]
    test eax, eax
    je out0
    mov dword ptr [ebp-0x34], eax
    mov ebx, dword ptr [ebp+0x34]
    cmp ebx, dword ptr [{CACHE_NUM:#x}]
    jne out0
    cmp dword ptr [{CACHE_DEN:#x}], 16
    jne out0
    cmp dword ptr [esi], 0
    jne out
    cmp dword ptr [esi+4], 0
    je out
    cmp dword ptr [{s['g_stripe_period']:#x}], 2
    jl out
    mov ecx, dword ptr [esi+0x10]
    lea eax, [ecx-1]
    cmp eax, {RUNS_MAX - 1}
    ja out
    mov eax, dword ptr [esi+0x14]
    lea edx, [eax-{QUAD}]
    cmp edx, {RUNS_MAX - QUAD}
    ja out
    imul eax, ecx
    cmp eax, {MAX_TEXELS}
    ja out
    mov eax, dword ptr [esi+0x20]
    imul eax, ebx
    sar eax, 4
    add eax, dword ptr [ebp+0x2C]
    js out
    mov dword ptr [ebp-0x18], eax
    imul ecx, ebx
    sar ecx, 4
    add ecx, eax
    cmp eax, dword ptr [edi+0x20]
    jge xs_ok
    mov eax, dword ptr [edi+0x20]
xs_ok:
    mov dword ptr [ebp-4], eax
    cmp ecx, dword ptr [edi+0x28]
    jle xe_a
    mov ecx, dword ptr [edi+0x28]
xe_a:
    cmp ecx, dword ptr [edi+0x80]
    jle xe_b
    mov ecx, dword ptr [edi+0x80]
xe_b:
    mov dword ptr [ebp-8], ecx
    mov eax, dword ptr [esi+0x24]
    imul eax, ebx
    sar eax, 4
    add eax, dword ptr [ebp+0x30]
    jns y_ok
out:
    mov esp, ebp
    popad
    ret 0x18
y_ok:
    mov dword ptr [ebp-0x3C], eax
    mov ecx, dword ptr [esi+0x14]
    imul ecx, ebx
    sar ecx, 4
    add ecx, eax
    cmp eax, dword ptr [edi+0x24]
    jge ys_ok
    mov eax, dword ptr [edi+0x24]
ys_ok:
    mov dword ptr [ebp-0xC], eax
    cmp ecx, dword ptr [edi+0x2C]
    jle ye_a
    mov ecx, dword ptr [edi+0x2C]
ye_a:
    mov eax, dword ptr [edi+0x84]
    neg eax
    cmp ecx, eax
    jle ye_b
    mov ecx, eax
ye_b:
    mov dword ptr [ebp-0x10], ecx
    mov eax, dword ptr [esi+0xC]
    mov dword ptr [ebp-0x30], eax
    and dword ptr [ebp-0x14], 0
mcol:
    mov ecx, dword ptr [ebp-0x14]
    mov ebx, dword ptr [esi+4]
    add ebx, ecx
    lea edi, [ebp+ecx-{FRAME:#x}]
    and dword ptr [ebp-0x24], 0
    mov eax, dword ptr [esi+0x14]
    mov dword ptr [ebp-0x1C], eax
mrow:
    cmp dword ptr [ebp-0x1C], {QUAD}
    jl mnoquad
    mov ecx, dword ptr [ebp-0x30]
    mov al, byte ptr [ebx]
    mov dl, byte ptr [ebx+ecx]
    cmp al, dl
    je mnoquad
    cmp al, byte ptr [ebp+0x28]
    je mnoquad
    cmp dl, byte ptr [ebp+0x28]
    je mnoquad
    cmp al, byte ptr [ebx+ecx*2]
    jne mnoquad
    lea ecx, [ecx+ecx*2]
    cmp dl, byte ptr [ebx+ecx]
    jne mnoquad
    xor al, dl
    mov byte ptr [ebp-0x23], al
    mov byte ptr [ebp-0x24], {QUAD}
mnoquad:
    mov al, byte ptr [ebx]
    cmp byte ptr [ebp-0x24], 0
    je mstore
    dec byte ptr [ebp-0x24]
    xor al, byte ptr [ebp-0x23]
mstore:
    mov byte ptr [edi], al
    add ebx, dword ptr [ebp-0x30]
    add edi, dword ptr [esi+0x10]
    dec dword ptr [ebp-0x1C]
    jnz mrow
    inc dword ptr [ebp-0x14]
    mov eax, dword ptr [ebp-0x14]
    cmp eax, dword ptr [esi+0x10]
    jl mcol
    call {paint:#x}
    jmp out
"""


# t_spr_paint: pass 2, CALLED by t_spr_stripes inside its frame (ebp, esi = Sprite*; every local above is set; it
# uses ebx / edi / eax / ecx / edx freely -- the caller's popad restores them -- and returns with a plain ret).
# Per column c: the dest run [dx, dx + runs[c]) cut to [xs, xe); per row r: the run [dy, dy + runs[r]) cut to [ys, ye).
# A texel is painted when it is marked (M != its index) AND its left or right neighbour texel is marked.
def asm_spr_paint(s: dict[str, int]) -> str:
    return f"""
    mov eax, dword ptr [ebp+0x24]
    mov eax, dword ptr [eax+0x4A8]
    mov dword ptr [ebp-0x38], eax
    and dword ptr [ebp-0x14], 0
col:
    mov ecx, dword ptr [ebp-0x14]
    mov eax, dword ptr [ebp-0x18]
    mov edx, dword ptr [ecx*4+{RUNS:#x}]
    add edx, eax
    mov dword ptr [ebp-0x18], edx
    cmp eax, dword ptr [ebp-4]
    jge cx0
    mov eax, dword ptr [ebp-4]
cx0:
    cmp edx, dword ptr [ebp-8]
    jle cx1
    mov edx, dword ptr [ebp-8]
cx1:
    mov dword ptr [ebp-0x28], eax
    mov dword ptr [ebp-0x2C], edx
    cmp eax, edx
    jge nextcol
    mov ebx, dword ptr [esi+4]
    add ebx, ecx
    lea edi, [ebp+ecx-{FRAME:#x}]
    mov eax, dword ptr [ebp-0x3C]
    mov dword ptr [ebp-0x20], eax
    mov eax, dword ptr [esi+0x14]
    mov dword ptr [ebp-0x1C], eax
row:
    mov ecx, dword ptr [esi+0x14]
    sub ecx, dword ptr [ebp-0x1C]
    mov ecx, dword ptr [ecx*4+{RUNS:#x}]
    mov eax, dword ptr [ebp-0x20]
    add ecx, eax
    mov dword ptr [ebp-0x20], ecx
    cmp eax, dword ptr [ebp-0xC]
    jge ry0
    mov eax, dword ptr [ebp-0xC]
ry0:
    cmp ecx, dword ptr [ebp-0x10]
    jle ry1
    mov ecx, dword ptr [ebp-0x10]
ry1:
    mov dword ptr [ebp-0x44], eax
    mov dword ptr [ebp-0x48], ecx
    movzx eax, byte ptr [ebx]
    movzx edx, byte ptr [edi]
    cmp al, dl
    je nomark
    mov ecx, dword ptr [ebp-0x14]
    test ecx, ecx
    jz nright
    mov cl, byte ptr [edi-1]
    cmp cl, byte ptr [ebx-1]
    jne isd
nright:
    mov ecx, dword ptr [ebp-0x14]
    inc ecx
    cmp ecx, dword ptr [esi+0x10]
    jge nomark
    mov cl, byte ptr [edi+1]
    cmp cl, byte ptr [ebx+1]
    je nomark
isd:
    push esi
    push edi
    mov edi, dword ptr [ebp+0x24]
    movzx ecx, byte ptr [edi+eax*4+0xA4]
    movzx esi, byte ptr [edi+eax*4+0xA5]
    add ecx, esi
    movzx esi, byte ptr [edi+eax*4+0xA6]
    add ecx, esi
    movzx esi, byte ptr [edi+edx*4+0xA4]
    sub ecx, esi
    movzx esi, byte ptr [edi+edx*4+0xA5]
    sub ecx, esi
    movzx esi, byte ptr [edi+edx*4+0xA6]
    sub ecx, esi
    pop edi
    pop esi
    jg atop
    jl swap
    cmp eax, edx
    jb atop
swap:
    xchg eax, edx
atop:
    mov byte ptr [ebp-0x23], al
    mov byte ptr [ebp-0x22], dl
yl:
    mov eax, dword ptr [ebp-0x44]
    cmp eax, dword ptr [ebp-0x48]
    jge nomark
    xor edx, edx
    div dword ptr [{s['g_stripe_period']:#x}]
    add edx, edx
    cmp edx, dword ptr [{s['g_stripe_period']:#x}]
    mov dl, byte ptr [ebp-0x23]
    jl ytop
    mov dl, byte ptr [ebp-0x22]
ytop:
    mov eax, dword ptr [ebp-0x44]
    imul eax, dword ptr [ebp-0x38]
    add eax, dword ptr [ebp-0x34]
    mov ecx, dword ptr [ebp-0x28]
    mov dh, byte ptr [ebx]
xl:
    cmp byte ptr [eax+ecx], dh
    jne xn
    mov byte ptr [eax+ecx], dl
xn:
    inc ecx
    cmp ecx, dword ptr [ebp-0x2C]
    jl xl
    inc dword ptr [ebp-0x44]
    jmp yl
nomark:
    add ebx, dword ptr [ebp-0x30]
    add edi, dword ptr [esi+0x10]
    dec dword ptr [ebp-0x1C]
    jnz row
nextcol:
    inc dword ptr [ebp-0x14]
    mov eax, dword ptr [ebp-0x14]
    cmp eax, dword ptr [esi+0x10]
    jl col
    ret
"""


def assemble_all(syms: dict[str, int] | None = None) -> dict[str, tuple[int, bytes]]:
    import assemble_se as SE
    assert PCAVE2 == SE.PCAVE2 and G == SE.G and SPRITE_DRAW_2 == SE.SD2
    s = syms or load_syms()
    paint_va = PCAVE2 + SLOTS["t_spr_paint"][0]
    out = {}
    for name, src in (("t_spr_stripes", asm_spr_stripes(s, paint_va)), ("t_spr_paint", asm_spr_paint(s))):
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
    return out


def slot_problems(layout, patches: Path | None = None) -> list[str]:
    """The thunk inside its slot; no live cave entry or cave symbol of another module inside its span."""
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


# ---- the hooks: the jmp tails of two EXISTING cave entries (emitted for review, never applied here) -------------
def _jmp_rel(frm_off: int, to_va: int) -> str:
    """`E9 rel32` at pcave2 offset frm_off -> to_va, as literal bytes (ByteTemplate takes {rel32:} after E8 only)."""
    return hx(b"\xE9" + struct.pack("<i", to_va - (PCAVE2 + frm_off + 5)))


def retargets(patches: Path | None = None) -> list[dict]:
    """[{entry, jmp_off, old, new}]: the LAST five bytes of each live entry must be `jmp Sprite_draw_2`."""
    import apply_patches as ap
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    symtab = dict(ap.build_symbol_table(symbols, caves))
    cave = next(c for c in caves if c["id"] == "pcave2")
    out = []
    for entry in ("thunk_se_sd2", "t_dp_sd2_logo"):
        e = next(c for c in cave["contents"] if c["id"] == entry)
        off = int(e["offset"])
        b = bytes(ap.ByteTemplate(" ".join(str(e["bytes"]).split())).resolve(PCAVE2 + off, symtab))
        jmp_off = off + len(b) - 5
        old = _jmp_rel(jmp_off, SPRITE_DRAW_2)
        new = _jmp_rel(jmp_off, PCAVE2 + OFF_CODE)
        state = "ok" if hx(b[-5:]) == old else ("already retargeted" if hx(b[-5:]) == new else "UNEXPECTED TAIL " + hx(b[-5:]))
        out.append({"entry": entry, "offset": off, "len": len(b), "jmp_off": jmp_off, "old": old, "new": new, "state": state})
    return out


def site_yaml(rts) -> str:
    lines = [f"# {GROUP}: NO new exe sites.  The hooks are the jmp tails of two existing pcave2 cave entries",
             "# (apply by hand; 0 byte delta each; rationale in work/briefs/stripes_spr_findings.md).  The new bytes are a",
             f"# literal rel32 to t_spr_stripes at pcave2 {OFF_CODE:#x}: re-run this module if the thunk moves.", "#"]
    for r in rts:
        lines += [f"#   - id: {r['entry']}          (pcave2 {r['offset']:#x}, {r['len']} B; the jmp is its last 5 bytes, at {r['jmp_off']:#x})",
                  f"#       old: {r['old']}        (jmp Sprite_draw_2)", f"#       new: {r['new']}        (jmp t_spr_stripes)", "#"]
    lines += ["# and the group to add:", "#", f"#   - id: {GROUP}",
              "#     members: []            # no sites; reached via the two jmp tails above", "#     code_caves: [pcave2]"]
    return "\n".join(lines) + "\n"


# ==== the laws (to be moved into scaling_laws.py) ================================================================
def sd2_runs(num: int, den: int = NATIVE_G, n: int = RUNS_MAX) -> list[int]:
    """Port of the engine's run-table builder 0x5EB20F (Sprite_fill_scaling_table) for an ENLARGE num > den > 1:
    dest pixels per source index, the same table for columns and rows.  q = num // den, rem = num % den;
    err = rem - 2 * den (+ num when q is odd); per entry err += 2 * rem and the entry is q + 1 (err -= 2 * den)
    when err > 0, else q.  NOT centre-aligned sampling and not floor(i * num / den) differences: measured, and
    checked against the real bytes in the parity test."""
    assert num > den > 1
    q, rem = divmod(num, den)
    err = rem - 2 * den + (num if q & 1 else 0)
    out = []
    for _ in range(n):
        err += 2 * rem
        if err > 0:
            out.append(q + 1)
            err -= 2 * den
        else:
            out.append(q)
    return out


def sd2_rect(x: int, y: int, num: int, *, w: int, h: int, lo: int = 0, to: int = 0):
    """The engine's scaled dest rect before the clip (0x5E4ECE..0x5E4F43, den = 16): origin ftol(x + off * s),
    size ftol(dim * s), s = num / 16 (exact in float32); dest x, y are NOT scaled.  ftol truncates toward zero."""
    def trunc16(v):
        return v // NATIVE_G if v >= 0 else -((-v) // NATIVE_G)
    return trunc16(x * NATIVE_G + lo * num), trunc16(y * NATIVE_G + to * num), (w * num) // NATIVE_G, (h * num) // NATIVE_G


def sd2_cells(x: int, y: int, num: int, *, w: int, h: int, lo: int = 0, to: int = 0, clip=None):
    """Yield (X, Y, r, c): every dest pixel the engine's expand blit maps, with its source texel -- the run table
    laid from the unclipped origin, cut at the rect's right / bottom edge (the last run is trimmed, a texel past it
    is dropped) and at the dest clip (half-open l, t, r, b)."""
    x0, y0, dw, dh = sd2_rect(x, y, num, w=w, h=h, lo=lo, to=to)
    runs = sd2_runs(num, n=max(w, h))
    xs, ys, xe, ye = x0, y0, x0 + dw, y0 + dh
    if clip is not None:
        xs, ys, xe, ye = max(xs, clip[0]), max(ys, clip[1]), min(xe, clip[2]), min(ye, clip[3])
    yy = y0
    for r in range(h):
        y1 = yy + runs[r]
        xx = x0
        for c in range(w):
            x1 = xx + runs[c]
            for Y in range(max(yy, ys), min(y1, ye)):
                for X in range(max(xx, xs), min(x1, xe)):
                    yield X, Y, r, c
            xx = x1
        yy = y1


def sd2_draw(dest: bytearray, stride: int, rows, key: int, x: int, y: int, num: int, *, lo: int = 0, to: int = 0,
             clip=None) -> None:
    """Sprite_draw_2 at num/16 > 1 into dest (the engine's keyed expand blit): plain nearest neighbour through the
    run table; key texels skipped."""
    h, w = len(rows), len(rows[0])
    for X, Y, r, c in sd2_cells(x, y, num, w=w, h=h, lo=lo, to=to, clip=clip):
        v = rows[r][c]
        if v != key:
            dest[Y * stride + X] = v


def spr_column_marks(rows, key: int) -> dict:
    """{(r, c): mate} for every texel that lies in a vertical window of four rows A,B,A,B (A != B, neither the key)
    of its column; its mate is the window's other member: scaling_laws.column_dither_marks (the one column rule)."""
    return SL.column_dither_marks(rows, key)


def spr_marks(rows, key: int) -> dict:
    """{(r, c): mate} for every DITHER texel of a native sprite: a column-marked texel (spr_column_marks) whose left
    or right neighbour texel is column-marked too.  A scanline dither is a ROW property: an isolated column that
    happens to alternate (the cross-hatched SE icons, a textured logo) is art and stays plain NN -- regenerating it
    alone shifts it against its unmarked neighbours (measured: speckle on socwin icon row 2)."""
    m = spr_column_marks(rows, key)
    return {(r, c): mate for (r, c), mate in m.items() if (r, c - 1) in m or (r, c + 1) in m}


def spr_pair_top(a: int, b: int, rgb) -> int:
    """The stripe-TOP member of a sprite row pair: the brighter by r + g + b of the dest buffer's colour table, ties
    -> the lower index.  `rgb(i)` -> (r, g, b).  (On every measured pair of socwin.pcx and the 14 faction logos this
    is scaling_laws.pair_top's member, except where pair_top's peak-channel key and the channel sum disagree --
    counted in the parity test.)"""
    sa, sb = sum(rgb(a)), sum(rgb(b))
    if sa != sb:
        return a if sa > sb else b
    return min(a, b)


def spr_synth(dest: bytearray, stride: int, rows, key: int, x: int, y: int, g: int, rgb, *, lo: int = 0, to: int = 0,
              clip=None) -> None:
    """t_spr_stripes at g > 16: the engine draw, then every dest pixel mapped from a dither texel (and still holding
    that texel's index) takes the pair's top where scaling_laws.stripe_top(dest row, g), else the mate."""
    h, w = len(rows), len(rows[0])
    sd2_draw(dest, stride, rows, key, x, y, g, lo=lo, to=to, clip=clip)
    if h < QUAD or w > RUNS_MAX or h > RUNS_MAX or w * h > MAX_TEXELS:
        return
    x0, y0, _dw, _dh = sd2_rect(x, y, g, w=w, h=h, lo=lo, to=to)
    if x0 < 0 or y0 < 0:
        return
    marks = spr_marks(rows, key)
    for X, Y, r, c in sd2_cells(x, y, g, w=w, h=h, lo=lo, to=to, clip=clip):
        mate = marks.get((r, c))
        if mate is None:
            continue
        v = rows[r][c]
        if dest[Y * stride + X] != v:
            continue
        top = spr_pair_top(v, mate, rgb)
        dest[Y * stride + X] = top if SL.stripe_top(Y, g) else (v ^ mate ^ top)


# ==== measured art (reads the game's pcx files; palette +10 at load) =============================================
SOCWIN_ICON_GRID = (1, 1, 27, 26)          # x0, y0, step, cell: 10 rows x 9 variants (SocialWin_build's extract)
SOCWIN_DIGITS = (0x115, (0x6F, 0x7D), 0xE, 13, 5)   # x0, ys, step, cell, count per row
LOGO_RECT = (436, 457, 65, 50)             # load_faction_art: g_faction_art[f] + 0x2C
FACTIONS = ("Gaians", "Hive", "Univ", "Morgan", "Spartans", "Believe", "Peace",
            "Cyborg", "Pirates", "Drone", "Angels", "Fungboy", "Caretake", "Usurper")
PCX_KEY = 9                                # pcx index 255 + 10


def load_pcx(name: str):
    import config
    from PIL import Image
    im = Image.open(os.path.join(str(config.game_dir()), name))
    w, h = im.size
    d = im.tobytes()
    return [[(d[yy * w + xx] + 10) & 0xFF for xx in range(w)] for yy in range(h)]


def crop(a, x, y, w, h):
    return [r[x:x + w] for r in a[y:y + h]]


def trim(cell, key: int = PCX_KEY):
    """(rows, lo, to): the cell cut to the bounding box of its non-key texels, as Sprite_extract stores it (blit
    w / h +0x10 / +0x14 with draw offsets +0x20 / +0x24), or None for an empty cell."""
    ys = [i for i, r in enumerate(cell) if any(v != key for v in r)]
    if not ys:
        return None
    xs = [i for i in range(len(cell[0])) if any(r[i] != key for r in cell)]
    return [r[xs[0]:xs[-1] + 1] for r in cell[ys[0]:ys[-1] + 1]], xs[0], ys[0]


def measured_sprites() -> dict:
    """{class: {name: cell}}: the untrimmed native cells of every sprite the six sites draw."""
    soc = load_pcx("socwin.pcx")
    x0, y0, step, cell = SOCWIN_ICON_GRID
    icons = {f"icon_r{r}c{c}": crop(soc, x0 + step * c, y0 + step * r, cell, cell) for r in range(10) for c in range(9)}
    dx0, dys, dstep, dcell, dn = SOCWIN_DIGITS
    digits = {f"digit{i + 2}_{'green' if k == 0 else 'red'}": crop(soc, dx0 + dstep * i, yy, dcell, dcell)
              for k, yy in enumerate(dys) for i in range(dn)}
    logos = {}
    for f in FACTIONS:
        try:
            logos[f"logo_{f}"] = crop(load_pcx(f + ".pcx"), *LOGO_RECT)
        except OSError:
            pass
    return {"se_icons": icons, "se_digits": {k: v for k, v in digits.items() if trim(v)}, "logos": logos}


def census(cell, key: int = PCX_KEY) -> dict:
    """Per-sprite facts: non-key texels, dither texels, pairs, pair indices that also occur as non-dither texels,
    and texels of a 1-px 2-D checker (differs from its 4 neighbours, which are all equal)."""
    h, w = len(cell), len(cell[0])
    marks = spr_marks(cell, key)
    pairs, members = {}, set()
    for (r, c), mate in marks.items():
        k = tuple(sorted((cell[r][c], mate)))
        pairs[k] = pairs.get(k, 0) + 1
        members.update(k)
    solid = sum(1 for r in range(h) for c in range(w) if cell[r][c] in members and (r, c) not in marks)
    chk = sum(1 for r in range(1, h - 1) for c in range(1, w - 1)
              if cell[r][c] != key and cell[r][c - 1] == cell[r][c + 1] == cell[r - 1][c] == cell[r + 1][c] != cell[r][c])
    return {"nonkey": sum(v != key for r in cell for v in r), "dither": len(marks), "pairs": pairs,
            "pair_index_as_art": solid, "checker": chk}


# ==== preview ====================================================================================================
PREVIEW_DIR = Path(__file__).resolve().parent.parent / "_portrait_preview" / "stripes_spr"
PALETTE_BIN = Path(__file__).resolve().parent.parent / "_portrait_preview" / "hd" / "game_palette_rgbquad.bin"
PREVIEW_G = (18, 22, 25, 40)
BG_INDEX = 0xC4                            # the SE panel's navy (13, 23, 36)


def load_palette():
    d = PALETTE_BIN.read_bytes()
    return [(d[i * 4 + 2], d[i * 4 + 1], d[i * 4]) for i in range(256)]


def _render_sheet(sprites: list, g: int, pal, cols: int, proposed: bool):
    """One canvas of native cells laid on a (cell * g / 16 + pad) grid; returns (bytearray, w, h)."""
    cw = max(len(s[0]) for _n, s in sprites)
    ch = max(len(s) for _n, s in sprites)
    pw, ph = (cw * g) // 16 + 6, (ch * g) // 16 + 6
    rows_n = (len(sprites) + cols - 1) // cols
    W, H = cols * pw + 6, rows_n * ph + 6
    dest = bytearray([BG_INDEX]) * (W * H)
    rgb = lambda i: pal[i]  # noqa: E731
    for k, (_name, cell) in enumerate(sprites):
        t = trim(cell)
        if t is None:
            continue
        rows, lo, to = t
        x, y = 6 + (k % cols) * pw, 6 + (k // cols) * ph
        if proposed:
            spr_synth(dest, W, rows, PCX_KEY, x, y, g, rgb, lo=lo, to=to, clip=(0, 0, W, H))
        else:
            sd2_draw(dest, W, rows, PCX_KEY, x, y, g, lo=lo, to=to, clip=(0, 0, W, H))
    return dest, W, H


def _to_image(dest, W, H, pal):
    from PIL import Image
    im = Image.frombytes("P", (W, H), bytes(dest))
    im.putpalette([ch for rgb in pal for ch in rgb])
    return im.convert("RGB")


def preview(out_dir: Path | None = None) -> list[Path]:
    """Side-by-side 'today (plain NN)' | 'proposed' sheets at 1:1 and a 4x zoom, per sprite class and g."""
    from PIL import Image, ImageDraw
    out_dir = Path(out_dir or PREVIEW_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    pal = load_palette()
    classes = measured_sprites()
    zoom_pick = {
        "se_icons": ["icon_r1c2", "icon_r3c1", "icon_r4c3", "icon_r6c5", "icon_r0c2", "icon_r2c7", "icon_r8c1", "icon_r5c8"],
        "se_digits": list(classes["se_digits"])[:8],
        "logos": [n for n in ("logo_Gaians", "logo_Hive", "logo_Spartans", "logo_Usurper") if n in classes["logos"]],
    }
    cols = {"se_icons": 9, "se_digits": 4, "logos": 5}
    written = []
    for cname, sprites in classes.items():
        items = list(sprites.items())
        for g in PREVIEW_G:
            for tag, sel, z in (("1x", items, 1), ("4x", [(n, sprites[n]) for n in zoom_pick[cname]], 4)):
                ncols = cols[cname] if z == 1 else min(4, len(sel))
                a = _to_image(*_render_sheet(sel, g, pal, ncols, False), pal)
                b = _to_image(*_render_sheet(sel, g, pal, ncols, True), pal)
                if z != 1:
                    a = a.resize((a.width * z, a.height * z), Image.NEAREST)
                    b = b.resize((b.width * z, b.height * z), Image.NEAREST)
                sheet = Image.new("RGB", (a.width + b.width + 24, a.height + 22), (40, 40, 40))
                sheet.paste(a, (8, 18))
                sheet.paste(b, (a.width + 16, 18))
                d = ImageDraw.Draw(sheet)
                d.text((8, 3), f"TODAY (plain NN)  g={g}  T={SL.stripe_rows(g)}  {tag}", fill=(255, 255, 255))
                d.text((a.width + 16, 3), f"PROPOSED (dither texels regenerated)  g={g}  {tag}", fill=(255, 255, 255))
                p = out_dir / f"{cname}_g{g}_{tag}.png"
                sheet.save(p)
                written.append(p)
    return written


def main(argv) -> int:
    if "--preview" in argv:
        for p in preview():
            print(p)
        return 0
    if "--census" in argv:
        for cname, sprites in measured_sprites().items():
            for n, cell in sprites.items():
                f = census(cell)
                pairs = " ".join(f"{a:02X}/{b:02X}:{k}" for (a, b), k in sorted(f["pairs"].items(), key=lambda kv: -kv[1]))
                print(f"{cname:9} {n:16} nonkey {f['nonkey']:5} dither {f['dither']:4} pair-index-as-art {f['pair_index_as_art']:4} "
                      f"checker {f['checker']:2}  {pairs}")
        return 0
    syms = load_syms()
    layout = assemble_all(syms)
    ok = True
    print("; ==== small-sprite dither regeneration (assemble_stripes_spr.py) ====")
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
    sym_line, content = "\n".join(sym_lines), "\n".join(content_lines)
    for p in roundtrip_problems(layout, syms):
        ok = False
        print("; TEMPLATE:", p)
    rts = retargets()
    for r in rts:
        print(f"; RETARGET {r['entry']} jmp @{r['jmp_off']:#x}: {r['old']} -> {r['new']}  [{r['state']}]")
        if r["state"].startswith("UNEXPECTED"):
            ok = False
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        for suffix, text in (("symbols", sym_line + "\n"), ("cave", content + "\n"), ("sites", site_yaml(rts))):
            with open(os.path.join(frag, f"_fragment_stripes_spr_{suffix}.yaml"), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        print("; fragments written to work/patches/_fragment_stripes_spr_*.yaml")
    else:
        print(sym_line)
        print(content)
        print(site_yaml(rts))
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
