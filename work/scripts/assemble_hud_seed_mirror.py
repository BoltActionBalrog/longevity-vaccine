#!/usr/bin/env python
"""F32 (2026-10-25): the HUD strip's right console panel on the mirror grid -- thunk_hud_seedscale v2 + g_hud_seedtable v2.

DEFECT: thunk_hud_seedscale (pcave2 0x4D00, call-redirected from MainWin_build's console2_A Buffer_load_pcx @0x459E8A)
floored each of the 97 seed / derived rect dwords alone.  The left panel +0xD80 (4, 56, 245, 252) and the right panel
+0xD90 (779, 56, 1020, 252) are vanilla's exact mirror pair (4 + 1020 = 245 + 779 = the strip width), but
fl(245g/16) + fl(779g/16) is one less than the strip's fl(1024g/16) = 64g at every g that is not a multiple of 16, so
the right panel's left edge -- and the whole inner chain every console screen derives from it (HUD, the F2..F8
report consoles, PROFILE, Council / Datalinks / diplomacy / base / design / social consoles, the F6 target lists) --
sat 1 px left of the mirror; where 1020g/16 is fractional the outer edge too.

LAW: scaling_laws.hud_seed_x / hud_seed_scaled -- the right-panel x fields (HUD_SEED_MIRROR_FIELDS: the panel rect and
every x MainWin_build derives from it before the detour) take W' - fl((1024 - x)g/16), the device mirror, which with
W' = 64g is the ceil image (x*g + 15) >> 4.  Every other dword keeps its floor.

PORT:
  g_hud_seedtable v2 (0x4D90, 196 B in place, same order): bit 15 of a word marks a mirror field (offsets are < 0x1000,
      the 0xFFFF terminator is never a marked word).
  thunk_hud_seedscale v2 (0x4D00, 129 -> 139 B in place, slot 0x4D00..0x4D90): the loop's word load keeps the original
      `movzx / cmp dx, 0xFFFF / je` (keystone re-encodes the cmp as its 4-byte imm8 form), then `btr edx, 15;
      sbb edi, edi; and edi, 15` (edi = 15 for a marked word, else 0) and `add eax, edi` between the imul and the sar.
      Every other byte is the v1 thunk's (the jle over the loop grows by 10; edi is pushad-saved and reloaded by the
      strip-rect tail).  Table values are all >= 0, so (v*g + 15) >> 4 is the ceil.  Its tail pushes t_hud_btnpair.
  t_hud_btnpair (NEW, 56 B @0x36000, the W2C region; law scaling_laws.hud_map_btn_pair): the WORLD / DETAIL map
      buttons keep their outer edges on the mirror grid and share one width (R - L - s(2)) >> 1, the odd px in the
      seam.  pushfd / pushad transparent; only +0xA94 / +0xA9C change; tail push t_hud_mi_square.
  t_box9_outer (NEW, 84 B @0x36040; law scaling_laws.hud_box9_outer_rect): call-redirect @0x45BF39, the box-9 outer
      frame nested fl(3g/16) inside the right panel on both sides, right edge exclusive.
  t_hb_mirror (NEW, 292 B @0x360A0; law scaling_laws.hud_backdrop_col_map): the console backdrop's Buffer_copy_3
      drop-in @0x459F65, wrapping t_hud_backdrop; the right-half centre-NN tie columns take their left neighbour, so the
      GDI stretch (ties to the upper texel) becomes mirror-symmetric.
  (thunk_hud_boxframe v4 / g_hud_nat_table, the box-9 inner frame's exclusive right edge: assemble_hud_widgets.py J.)

Fragments: `py assemble_hud_seed_mirror.py` prints every yaml bytes line and checks it against patches.yaml.  Guard:
tests/test_scaling_hud_seed_mirror.py (laws + Unicorn parity from the baked bytes + the real MainWin_build and paint).
"""
from __future__ import annotations

import os
import re
import struct
import sys
from pathlib import Path

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, os.path.dirname(__file__))
from scaling_laws import (HUD_BOX9_OUTER_INSET, HUD_BOX9_OUTER_NATIVE, HUD_MAP_BTN_FIELDS,  # noqa: E402
                          HUD_SEED_MIRROR_FIELDS, NATIVE_G)

PCAVE2 = 0xA0C000
MAINWIN = 0x7AE820
SEEDSCALE_OFF, SEEDTABLE_OFF = 0x4D00, 0x4D90
BTNPAIR_OFF, BTNPAIR_LIMIT = 0x36000, 0x40      # W2C region 0x36000..0x36FFF (cave_map --at 0x36000: FREE)
SLOT_LIMIT = SEEDTABLE_OFF - SEEDSCALE_OFF          # 0x90: the table follows the thunk
MIRROR_FLAG = 0x8000

#: g_hud_seedtable v1 (the 97 MainWin offsets + 0xFFFF), in its baked order.
SEEDTABLE_V1 = [
    0xD7C, 0xD80, 0xD84, 0xD88, 0xD8C, 0xD90, 0xD94, 0xD98, 0xD9C, 0xDA0, 0xDA4, 0xDA8, 0xDAC, 0xDB0, 0xDB4, 0xDB8,
    0xDBC, 0xA5C, 0xA60, 0xA64, 0xA68, 0xA6C, 0xA70, 0xA74, 0xA78, 0xDE0, 0xDE4, 0xDE8, 0xDEC, 0xDF0, 0xDF4, 0xDF8,
    0xDFC, 0xD2C, 0xD30, 0xD34, 0xD38, 0xDC0, 0xDC4, 0xDC8, 0xDCC, 0xDD0, 0xDD4, 0xDD8, 0xDDC, 0xD3C, 0xD40, 0xD44,
    0xD48, 0xA2C, 0xA30, 0xA34, 0xA38, 0xA3C, 0xA40, 0xA44, 0xA48, 0xA4C, 0xA50, 0xA54, 0xA58, 0xD1C, 0xD20, 0xD24,
    0xD28, 0xCDC, 0xCE0, 0xCE4, 0xCE8, 0xCEC, 0xCF0, 0xCF4, 0xCF8, 0xCCC, 0xCD0, 0xCD4, 0xCD8, 0xA7C, 0xA80, 0xA84,
    0xA88, 0xCFC, 0xD00, 0xD04, 0xD08, 0xA9C, 0xAA0, 0xAA4, 0xAA8, 0xA8C, 0xA90, 0xA94, 0xA98, 0xD0C, 0xD10, 0xD14,
    0xD18]
TERMINATOR = 0xFFFF

#: thunk_hud_seedscale v1 as baked (yaml template form), split around the loop it rewrites.
V1_HEAD = ("9C 60 E8 {rel32:thunk_ensure_scale} 8B 0D {abs32:g_popup_scale_num} 83 F9 10 7E 67 "
           "BE 20 E8 7A 00 BB {abs32:g_hud_seedtable}")
V1_LOOP = "0F B7 13 66 81 FA FF FF 74 11 8B 04 16 0F AF C1 C1 F8 04 89 04 16 83 C3 02 EB E5"
V1_TAIL = ("B8 00 04 00 00 0F AF C1 C1 F8 04 BA 01 01 00 00 0F AF D1 C1 FA 04 8B 3D {abs32:ScreenWidth} 2B F8 D1 FF "
           "89 BE 1C 0A 00 00 03 F8 89 BE 24 0A 00 00 8B 3D {abs32:ScreenHeight} 89 BE 28 0A 00 00 2B FA "
           "89 BE 20 0A 00 00 61 9D 68 {abs32:t_hud_mi_square} C3")
V2_TAIL_TARGET = "{abs32:t_hud_btnpair}"         # v2: seedscale -> t_hud_btnpair -> t_hud_mi_square -> Buffer_load_pcx
V1_JLE = "7E 67"

LOOP_ASM = """
lp:
    movzx edx, word ptr [ebx]
    cmp   dx, 0xFFFF
    je    done
    btr   edx, 15
    sbb   edi, edi
    and   edi, 15
    mov   eax, dword ptr [esi+edx]
    imul  eax, ecx
    add   eax, edi
    sar   eax, 4
    mov   dword ptr [esi+edx], eax
    add   ebx, 2
    jmp   lp
done:
"""


def _hex(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def _tlen(t: str) -> int:
    """Byte length of a yaml template string ({abs32:..} / {rel32:..} = 4 bytes)."""
    return sum(4 if tok.startswith("{") else 1 for tok in t.split())


def loop_bytes() -> bytes:
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(LOOP_ASM, addr=PCAVE2 + SEEDSCALE_OFF + _tlen(V1_HEAD))
    return bytes(code)


def seedscale_template() -> str:
    loop = loop_bytes()
    grow = len(loop) - _tlen(V1_LOOP)
    jle = f"7E {0x67 + grow:02X}"
    assert 0x67 + grow < 0x80
    head = V1_HEAD.replace(V1_JLE, jle, 1)
    assert head != V1_HEAD
    return f"{head} {_hex(loop)} {V1_TAIL.replace('{abs32:t_hud_mi_square}', V2_TAIL_TARGET)}"


def seedtable_words() -> list:
    assert len(SEEDTABLE_V1) == 97 and len(set(SEEDTABLE_V1)) == 97
    assert set(HUD_SEED_MIRROR_FIELDS) <= set(SEEDTABLE_V1)
    return [o | MIRROR_FLAG if o in HUD_SEED_MIRROR_FIELDS else o for o in SEEDTABLE_V1] + [TERMINATOR]


def seedtable_template() -> str:
    return _hex(b"".join(struct.pack("<H", w) for w in seedtable_words()))


# t_hud_btnpair (port of scaling_laws.hud_map_btn_pair): entered by seedscale's `ret` with the call-redirect frame
# intact; pushfd / pushad transparent; g > 16: w = (DETAIL.r - WORLD.l - fl(2g/16)) >> 1, WORLD.r = WORLD.l + w,
# DETAIL.l = DETAIL.r - w (the outer edges are already on the mirror grid); tail push t_hud_mi_square / ret.  Only
# +0xA94 and +0xA9C change.
WORLD, DETAIL = HUD_MAP_BTN_FIELDS
assert DETAIL - WORLD == 0x10
SEAM = 960 - 958                                          # vanilla DETAIL.l - WORLD.r
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}", 0xDEADBE10: "{abs32:t_hud_mi_square}"}
BTNPAIR_ASM = f"""
    pushfd
    pushad
    mov  ecx, dword ptr [0xDEADBE00]
    cmp  ecx, {NATIVE_G:#x}
    jle  out
    imul ecx, ecx, {SEAM:#x}
    sar  ecx, 4
    mov  edx, {MAINWIN + WORLD:#x}
    mov  eax, dword ptr [edx + 0x18]
    sub  eax, dword ptr [edx]
    sub  eax, ecx
    sar  eax, 1
    mov  ecx, dword ptr [edx]
    add  ecx, eax
    mov  dword ptr [edx + 8], ecx
    mov  ecx, dword ptr [edx + 0x18]
    sub  ecx, eax
    mov  dword ptr [edx + 0x10], ecx
out:
    popad
    popfd
    push 0xDEADBE10
    ret
"""


def _template(asm: str, off: int, sent: dict, limit: int) -> str:
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(asm, addr=PCAVE2 + off)
    blob, out, i = bytes(code), [], 0
    while i < len(blob):
        for s, name in sent.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == s:
                out.append(name)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    t = " ".join(out)
    assert _tlen(t) <= limit, (hex(off), _tlen(t), limit)
    return t


def btnpair_template() -> str:
    return _template(BTNPAIR_ASM, BTNPAIR_OFF, SENT, BTNPAIR_LIMIT)


# t_box9_outer (F32 v2, port of scaling_laws.hud_box9_outer_rect): call-redirect from the box-9 painter's outer
# Buffer_box_sprite call @0x45BF39 (MainWin_draw_box9; the rect arg is the painter's own local [ebp-0x14], not a
# seed).  g > 16: rect := (P.l + s3, fl(211g/16), P.r - s3 - 1, fl(249g/16)), P = MainWin +0xD90 l / r (device, on the
# mirror grid), s3 = fl(3g/16); then tail-jump Buffer_box_sprite (thunk_hud_boxframe passes an unlisted site's rect to
# the inclusive renderer).  eax / ecx / edx / ebx preserved; the callee clobbers the flags anyway.
BOX9_OFF, BOX9_LIMIT = 0x36040, 0x60
BOX9_SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}", 0xDEADBE20: "{abs32:Buffer_box_sprite}"}
BOX9_ASM = f"""
    cmp  dword ptr [0xDEADBE00], {NATIVE_G:#x}
    jle  go
    push eax
    push ecx
    push edx
    push ebx
    mov  edx, dword ptr [esp + 0x14]
    mov  eax, dword ptr [0xDEADBE00]
    imul ecx, eax, {HUD_BOX9_OUTER_INSET:#x}
    sar  ecx, 4
    mov  ebx, dword ptr [{MAINWIN + 0xD90:#x}]
    add  ebx, ecx
    mov  dword ptr [edx], ebx
    mov  ebx, dword ptr [{MAINWIN + 0xD98:#x}]
    sub  ebx, ecx
    dec  ebx
    mov  dword ptr [edx + 8], ebx
    imul ebx, eax, {HUD_BOX9_OUTER_NATIVE[1]:#x}
    sar  ebx, 4
    mov  dword ptr [edx + 4], ebx
    imul ebx, eax, {HUD_BOX9_OUTER_NATIVE[3]:#x}
    sar  ebx, 4
    mov  dword ptr [edx + 0xC], ebx
    pop  ebx
    pop  edx
    pop  ecx
    pop  eax
go:
    push 0xDEADBE20
    ret
"""


def box9_template() -> str:
    return _template(BOX9_ASM, BOX9_OFF, BOX9_SENT, BOX9_LIMIT)


# t_hb_mirror (F32 v2 @0x360A0, port of scaling_laws.hud_backdrop_col_map / hud_backdrop_tie_cols): the Buffer_copy_3 drop-in
# at MainWin_build 0x459F65 (RET 0x24; ecx = src Buffer*; +4 dst, +8 srcX, +0xC srcY, +0x10 srcW, +0x14 srcH,
# +0x18 dstX, +0x1C dstY, +0x20 dstW, +0x24 dstH).  g <= 16: push t_hud_backdrop / ret (its own native pass-through).
# Else: re-push the nine args, call t_hud_backdrop (the GDI stretch + the stripe-law restripe, unchanged), then, if it
# returned 0 and the dest rect is an in-buffer horizontal enlarge: for every dest column d with 2d + 1 > dstW and
# (2d + 1) * srcW divisible by 2 * dstW (a right-half centre-NN tie, which GDI sent to the upper texel), copy dest
# column d - 1 over d on the blit's rows, both columns inside the dest clip, rows cut to it.  pushad / popad: eax (the
# copy's result) and every register as the engine left them.  Frame (ebp = esp after pushad): +0x24 dst ..
# +0x44 dstH.  Buffer: clip l/t/r/b +0x20..+0x2C, data +0x54, W +0x80, H +0x84 (negative), stride +0x4A8.
MIRROR_OFF, MIRROR_LIMIT = 0x360A0, 0x140
MIRROR_SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}", 0xDEADBE30: "{abs32:t_hud_backdrop}"}
MIRROR_ASM = f"""
    cmp  dword ptr [0xDEADBE00], {NATIVE_G:#x}
    jg   scaled
    push 0xDEADBE30
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
    mov  eax, 0xDEADBE30
    call eax
    pop  ecx
    pushad
    mov  ebp, esp
    test eax, eax
    jne  out
    mov  edi, dword ptr [ebp+0x24]
    test edi, edi
    je   out
    cmp  dword ptr [edi+0x54], 0
    je   out
    mov  esi, dword ptr [ebp+0x40]
    mov  eax, dword ptr [ebp+0x30]
    test eax, eax
    jle  out
    cmp  esi, eax
    jle  out
    cmp  esi, 0x4000
    ja   out
    mov  eax, dword ptr [ebp+0x38]
    or   eax, dword ptr [ebp+0x3C]
    js   out
    mov  eax, dword ptr [ebp+0x38]
    add  eax, esi
    cmp  eax, dword ptr [edi+0x80]
    jg   out
    mov  eax, dword ptr [ebp+0x3C]
    add  eax, dword ptr [ebp+0x44]
    mov  edx, dword ptr [edi+0x84]
    neg  edx
    cmp  eax, edx
    jg   out
    lea  ebx, [esi+1]
    shr  ebx, 1
dloop:
    cmp  ebx, esi
    jge  out
    lea  eax, [ebx*2+1]
    imul eax, dword ptr [ebp+0x30]
    xor  edx, edx
    lea  ecx, [esi+esi]
    div  ecx
    test edx, edx
    jne  dnext
    mov  ecx, dword ptr [ebp+0x38]
    add  ecx, ebx
    lea  eax, [ecx-1]
    cmp  eax, dword ptr [edi+0x20]
    jl   dnext
    cmp  ecx, dword ptr [edi+0x28]
    jge  dnext
    mov  eax, dword ptr [ebp+0x3C]
    cmp  eax, dword ptr [edi+0x24]
    jge  y0ok
    mov  eax, dword ptr [edi+0x24]
y0ok:
    mov  edx, dword ptr [ebp+0x3C]
    add  edx, dword ptr [ebp+0x44]
    cmp  edx, dword ptr [edi+0x2C]
    jle  y1ok
    mov  edx, dword ptr [edi+0x2C]
y1ok:
    push esi
    push ebx
    mov  esi, eax
    imul esi, dword ptr [edi+0x4A8]
    add  esi, dword ptr [edi+0x54]
    add  esi, ecx
    mov  ebx, edx
    sub  ebx, eax
    jle  rdone
rl:
    mov  al, byte ptr [esi-1]
    mov  byte ptr [esi], al
    add  esi, dword ptr [edi+0x4A8]
    dec  ebx
    jnz  rl
rdone:
    pop  ebx
    pop  esi
dnext:
    inc  ebx
    jmp  dloop
out:
    popad
    ret  0x24
"""


def mirror_template() -> str:
    return _template(MIRROR_ASM, MIRROR_OFF, MIRROR_SENT, MIRROR_LIMIT)


def main() -> int:
    t = seedscale_template()
    n = _tlen(t)
    assert n <= SLOT_LIMIT, f"{n} B does not fit 0x4D00..0x4D90"
    print(f"thunk_hud_seedscale v2  {n} bytes @ {PCAVE2 + SEEDSCALE_OFF:#x} (slot {SLOT_LIMIT:#x})")
    print('        bytes: "' + t + '"')
    tb = seedtable_template()
    print(f"g_hud_seedtable v2  {_tlen(tb)} bytes @ {PCAVE2 + SEEDTABLE_OFF:#x}")
    print('        bytes: "' + tb + '"')
    bp = btnpair_template()
    print(f"t_hud_btnpair  {_tlen(bp)} bytes @ {PCAVE2 + BTNPAIR_OFF:#x}")
    print('        bytes: "' + bp + '"')
    b9 = box9_template()
    print(f"t_box9_outer  {_tlen(b9)} bytes @ {PCAVE2 + BOX9_OFF:#x}")
    print('        bytes: "' + b9 + '"')
    mr = mirror_template()
    print(f"t_hb_mirror  {_tlen(mr)} bytes @ {PCAVE2 + MIRROR_OFF:#x}")
    print('        bytes: "' + mr + '"')
    # self-check against the yaml when run in the tree
    y = Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
    if y.is_file():
        text = y.read_text(encoding="utf-8")
        for name, off, want in (("thunk_hud_seedscale", SEEDSCALE_OFF, t), ("g_hud_seedtable", SEEDTABLE_OFF, tb),
                                ("t_hud_btnpair", BTNPAIR_OFF, bp), ("t_box9_outer", BOX9_OFF, b9),
                                ("t_hb_mirror", MIRROR_OFF, mr)):
            m = re.search(r'- id: %s\r?\n\s*offset: 0x%X\r?\n\s*bytes: "([^"]+)"' % (name, off), text)
            print(f"yaml {name}: {'MATCH' if m and m.group(1) == want else 'DIFFERS'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
