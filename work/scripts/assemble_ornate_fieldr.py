#!/usr/bin/env python
"""ornate_field_right (2026-09-19): the ORNATE popups' text-field right inset scales (vanilla x g/16).

PORT OF: scaling_laws.ornate_field_right_sub.  Parity: tests\\test_ornate_fieldr_asm_parity.py.

DEFECT (user 4K shots 20260919-164709 / -170335, also in 20260917-234627; geometry read from the live game by
uimod debugdump: TutWin W 1599 @g40, 998 @g25, anchors 32/1567 and 20/978 symmetric): the tutorial window's text
field + ring sat right of centre -- ring ON the ornate border's inner green line (right channel 0, left 13 px @4K).
CAUSE: Popup_on_draw_background builds the field R as winR - 10 and, for the ornate types 2/6 only, `sub ecx,9`
@0x40612C.  thunk_popup_fieldR scales the 10; the 9 stayed NATIVE.  Titled ornate popups never see it (fieldpads'
keyed ornate arm replaces ecx from g_title_right), but an UNTITLED ornate popup with a body box (TutWin: type 2,
+0x30D4 != 0, +0xA48 == 0) takes the engine arithmetic since pf-align v8 (2026-08-01), and thunk_untitled_stash
disarms the key for ornate types right after the backdrop, so the keyed arm cannot be borrowed.
   measured field insets L/R: 40/26 @g40, 25/20 @g25   (vanilla 16/16)
LAW: the left inset is fl(19g/16) - ps3 (the engine's own [+0x30f0] margin, floor-scaled); the right is
fl(10g/16) + X - ps3, so X = fl(19g/16) - fl(10g/16) makes the two sides EQUAL by the neighbour's own cascade
(9 at g=16; 13/14/22 @g22/25/40 -- a bare fl(9g/16) is 1 px short at g=22).
FIX: t_orn_fieldsub heads the 0x40612F site (E8 -> thunk_popup_fieldpads): g>16, type 2/6 (edx, live from
0x40611F), popup NOT keyed -> ecx -= X - 9; then the unchanged fieldpads.
v2 (fix 26 v2, 2026-10-24): X carries + ORNATE_HALF_OPEN -- the inclusive-drawn field box on vanilla's half-open
axis x <-> W - 1 - x (law ornate_field_right_sub).

Usage: py assemble_ornate_fieldr.py [--splice]
"""
from __future__ import annotations

import pathlib
import sys

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
OFF = 0x2FE20                          # cave_map: free after thunk_bandmap_orn (ends 0x2FE03)
LIMIT = 0x30000
G = 0x668740
G_BAND_POPUP = PCAVE2 + 0x2708
FIELDPADS = PCAVE2 + 0x13A30
SITE = 0x0040612F

ASM = f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     of_pass
    cmp     edx, 6
    je      of_orn
    cmp     edx, 2
    jne     of_pass
of_orn:
    cmp     esi, dword ptr [{G_BAND_POPUP:#x}]
    je      of_pass
    push    eax
    mov     eax, dword ptr [{G:#x}]
    imul    eax, eax, 19
    sar     eax, 4
    sub     ecx, eax
    mov     eax, dword ptr [{G:#x}]
    imul    eax, eax, 10
    sar     eax, 4
    lea     ecx, [ecx+eax+{9 - SL.ORNATE_HALF_OPEN}]
    pop     eax
of_pass:
    push    0x7A111111
    ret
"""


def build() -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(ASM, PCAVE2 + OFF)
    b = bytes(enc)
    assert OFF + len(b) <= LIMIT
    return b


def templ(b: bytes) -> str:
    hexs = " ".join(f"{x:02X}" for x in b)
    assert hexs.count("11 11 11 7A") == 1
    hexs = hexs.replace("11 11 11 7A", "{abs32:thunk_popup_fieldpads}")
    for va, name in ((G, "g_popup_scale_num"), (G_BAND_POPUP, "g_band_popup")):
        le = " ".join(f"{x:02X}" for x in va.to_bytes(4, "little"))
        assert le in hexs, name
        hexs = hexs.replace(le, "{abs32:%s}" % name)
    return hexs


GROUP = "ornate_field_right"
M_SYM = (f"  # ==== {GROUP} symbols (2026-09-19, src assemble_ornate_fieldr.py) ====\n", f"# ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} cave (src assemble_ornate_fieldr.py; law scaling_laws.ornate_field_right_sub) ====\n", f"# ==== {GROUP} END ==== cave\n")
SITE_OLD = 'new_bytes:      "E8 {rel32:thunk_popup_fieldpads} 90 90'
SITE_NEW = 'new_bytes:      "E8 {rel32:t_orn_fieldsub} 90 90'
# the superseded (ineffective) tutwin_right block + its site retarget
DEAD_MARKS = (("  # ==== tutwin_right symbols", "# ==== tutwin_right END ==== symbols"),
              ("      # ==== tutwin_right cave", "# ==== tutwin_right END ==== cave"))
DEAD_SITE = ('new_bytes:      "E8 {rel32:t_tw_right}"', 'new_bytes:      "E8 {rel32:thunk_backdrop_railtrim}"')


def main() -> int:
    b = build()
    print(f"OK  t_orn_fieldsub @0x{OFF:05X} len={len(b)}")
    if "--splice" not in sys.argv:
        return 0
    y = pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
    data = y.read_bytes()
    nl = b"\r\n" if b"\r\n" in data[:4096] else b"\n"
    for a, z in DEAD_MARKS:                                   # remove the superseded block (idempotent)
        a, z = a.encode(), z.encode()
        if a in data:
            s = data.index(a)
            e = data.index(z, s) + len(z)
            if data[e:e + len(nl)] == nl:
                e += len(nl)
            assert 0 < s < e
            data = data[:s] + data[e:]
    if DEAD_SITE[0].encode() in data:
        assert data.count(DEAD_SITE[0].encode()) == 1
        data = data.replace(DEAD_SITE[0].encode(), DEAD_SITE[1].encode())

    sym = M_SYM[0] + f"  t_orn_fieldsub:                {{ cave: pcave2, offset: {OFF:#07x} }}   # {GROUP} ({len(b)}B): heads the 0x40612F fieldpads site; unkeyed ornate popups: the engine's native `sub ecx,9` -> fl(19g/16)-fl(10g/16)\n" + M_SYM[1]
    cave = (M_CAVE[0] +
            "      # 0x40612C `sub ecx,9` (ornate types 2/6) was the one unscaled constant of the text-field R: TutWin (untitled ornate + body box)\n"
            "      # drew its field/ring right of centre (insets 40/26 @g40, 25/20 @g25).  X = fl(19g/16) - fl(10g/16) mirrors the LEFT margin's own\n"
            "      # cascade.  Keyed (titled) ornate popups are skipped: fieldpads' ornate arm replaces ecx for them.\n"
            f"      - id: t_orn_fieldsub\n        offset: {OFF:#07x}\n        bytes: \"{templ(b)}\"\n" + M_CAVE[1])

    def put_block(data, block, markers, anchor):
        blk = block.replace("\n", nl.decode()).encode("utf-8")
        a, z = markers[0].strip("\n").encode(), markers[1].strip("\n").encode()
        if a in data:
            s = data.index(a)
            s = data.rfind(nl, 0, s) + len(nl)
            e = data.index(z, s) + len(z)
            if data[e:e + len(nl)] == nl:
                e += len(nl)
            assert 0 < s < e
            return data[:s] + blk + data[e:]
        anc = anchor.encode()
        assert data.count(anc) == 1, anchor
        p = data.index(anc) + len(anc)
        p = data.index(nl, p) + len(nl)
        return data[:p] + blk + data[p:]

    data = put_block(data, sym, M_SYM, "# ==== frame_bandmap_ornate END ==== symbols")
    data = put_block(data, cave, M_CAVE, "# ==== frame_bandmap_ornate END ==== cave")
    old, new = SITE_OLD.encode(), SITE_NEW.encode()
    if new not in data:
        assert data.count(old) == 1, "fieldpads site new_bytes not found exactly once"
        data = data.replace(old, new)
    y.write_bytes(data)
    print("spliced into", y)
    return 0


if __name__ == "__main__":
    sys.exit(main())
