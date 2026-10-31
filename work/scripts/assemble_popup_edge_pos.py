r"""Assemble the POSITIVE popup screen-edge gap thunks (group popup_edge_positive_scale).

PORT OF: scaling_laws.py :: tutwin_place() / tutwin_window_h() / popup_positive_loc()
         (the SOURCE OF TRUTH). The negative (far-edge) requests are
         assemble_popup_edge.py's (thunk_popup_edge_anchor at the exec_3 join).

DEFECTS FIXED (2026-10-17):
  * TutWin (crash-land LANDFALL, the 54 map hints, the TOURs): TutWin_tut_win places
    the box with NATIVE gaps (x 5 from the side, y 8 from the bottom) and from the BOX
    height [+0x30C0] -- but BasePop_exec_3's box_grow (thunk_grow_box at 0x602861)
    creates the window D = fl(btnH*g/16) - btnH taller (30 at 4K), so the bottom rail
    sat 22 px below the screen at 4K and 1 px from it at 1920x1080.
  * Script #x/#y (BasePop_start's atoi parse): FACTIONX's list at device (5,5) while its
    quote box already sat at fl(5g/16) (thunk_fac_quote_x).
  * (NetMsg_g, "Operations Director" notices: set_loc(0x1000, 8) -> y 8 device. Left
    unscaled since 2026-10-22: t_netmsg_loc is backed out, see below.)

THE WINDOW-HEIGHT SOURCE (t_tw_gap). The placement runs between TutWin's two exec_3
passes. Pass 1 is BasePop_exec_3(1, 0) (0x4BE29D push ebx=0; push 1): exec_3 runs
vtbl+0x168 (Popup_calculate_dimensions -> BasePop_calculate_dimensions) and returns at
0x6027AF (`mov eax,[esp+0x40]; test; jne 0x6037DE`) BEFORE the window's GraphicWin_init
at 0x60287C. So no window exists for this box yet: the canvas [+0x4C8] is the PREVIOUS
tooltip's (or 0 on the first) and must not be read. The window height is derived from
the grow law instead: winH = [+0x30C0] + fl([+0x30D0]*g/16) - [+0x30D0], the same
[+0x30D0] box_grow reads -- pass 2 re-runs the same calc (0x405020 rewrites 20, the
font is installed once before both passes) and nothing between its calc (0x60279B)
and box_grow (0x602861) writes 0x30C0/0x30D0 (vtbl+0x16c is a bare RET). TutWin is its
own window ([+0xA3C] == self; Popup_start parent arg 0) and never anchored ([+0xA14]
cleared by BasePop_start: its flags 0x4000/0/0x40 lack 0x100000), so the growth always
fires (t_dp_growbox_gate's diplomacy exemption cannot apply).

t_tw_gap  (126 B, pcave2 + 0xB840)
    SITE 0x4BE38C (5 B `8B 45 20 85 C0` mov eax,[ebp+0x20]; test eax,eax) -> E8 rel32.
    The join of both x arms (0x4BE363 jmp lands on it). g>16: dx = fl(5g/16) - 5; the
    left arm (x == 5) adds dx to x [ebp+0x10] and attach_x [+0x538C], the right arm
    subtracts it; winH as above; bottom arm (attach_y [+0x5390] == y [ebp+0x14]):
    y = attach_y = SH [ebp-0x18] - winH - fl(8g/16); top arm: attach_y = y + winH (y =
    ty/8 is proportional and stays). Replays the 5 displaced bytes so the `jl` at
    0x4BE391 gets its flags and eax; ecx/edx preserved. The arrow2 copy (0x4BE393) and
    the first Win_window_line_raw run after it, so the pointer line follows.

t_scrloc_x / t_scrloc_y  (37 B each, pcave2 + 0x1330 / 0x1358)
    SITES 0x601E91 / 0x601EDF (6 B `89 86 F8|FC 30 00 00` mov [esi+0x30F8|FC],eax) ->
    E8 rel32 90. eax = atoi(#x|#y), the 0x2000 KEEP already branched away. Stores
    popup_positive_loc(eax, g): 0 < v < 0x1000 and g > 16 -> fl(v*g/16), else v.
    Each parse rewrites the field from the text, so nothing compounds. eax is dead
    (0x601E97 / 0x601EE5 jmp to the parse loop's `call 0x5FD570`); flags dead.

t_netmsg_loc  BACKED OUT 2026-10-22 (fix 18, user decision). It redirected NetMsg_pop's
    `call BasePop_set_loc(+0x537C, +0x5380)` at 0x47A94F through popup_positive_loc. No
    visible case was verified: "Bases cannot be built adjacent" takes the ticker path
    0x47ABBA and never reaches 0x47A94F; only the rare a4 = 1/2 notices (UPKEEP, VOTING,
    multiplayer AWAIT) do. The site is vanilla's call again and NetMsg_g's literal y = 8
    stays unscaled until a visible case is verified; its pcave2 0xC690..0xC6D9 slot is
    free (zero-filled by the whole-cave write).

SLOTS (cave_map --at, 2026-10-17): 0xB840 free 0xB831..0xB8C0 (thunk_bw_tile2 /
thunk_bw_fill2); 0x1330 + 0x1358 free 0x132F..0x1390 (thunk_faction_show /
thunk_btntext_nudge).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_popup_edge import resolve  # noqa: E402  (the shared {abs32:}/{rel32:} resolver)

TW_TEMPLATE = (
    "50 51 52 "                             # push eax / ecx / edx
    "8B 0D {abs32:g_popup_scale_num} "      # mov  ecx,[g]
    "83 F9 10 "                             # cmp  ecx,16
    "7E 67 "                                # jle  out                 (native: replay only)
    "8D 04 89 "                             # lea  eax,[ecx+ecx*4]     5g
    "C1 F8 04 "                             # sar  eax,4               fl(5g/16)
    "83 E8 05 "                             # sub  eax,5               dx = gap - 5
    "83 7D 10 05 "                          # cmp  dword [ebp+0x10],5  left arm placed x = 5
    "75 0B "                                # jne  right
    "01 45 10 "                             # add  [ebp+0x10],eax      x
    "01 86 8C 53 00 00 "                    # add  [esi+0x538C],eax    attach_x
    "EB 09 "                                # jmp  ydo
    # right:
    "29 45 10 "                             # sub  [ebp+0x10],eax
    "29 86 8C 53 00 00 "                    # sub  [esi+0x538C],eax
    # ydo:
    "8B 96 D0 30 00 00 "                    # mov  edx,[esi+0x30D0]    btnH (what box_grow reads)
    "89 D0 "                                # mov  eax,edx
    "0F AF C1 "                             # imul eax,ecx
    "C1 F8 04 "                             # sar  eax,4               fl(btnH*g/16)
    "29 D0 "                                # sub  eax,edx             D (grow)
    "03 86 C0 30 00 00 "                    # add  eax,[esi+0x30C0]    winH = boxH + D
    "8B 96 90 53 00 00 "                    # mov  edx,[esi+0x5390]    attach_y
    "3B 55 14 "                             # cmp  edx,[ebp+0x14]      == y -> bottom arm
    "75 18 "                                # jne  top
    "8B 55 E8 "                             # mov  edx,[ebp-0x18]      SH
    "29 C2 "                                # sub  edx,eax
    "C1 E1 03 "                             # shl  ecx,3               8g
    "C1 F9 04 "                             # sar  ecx,4               fl(8g/16)
    "29 CA "                                # sub  edx,ecx             y = SH - winH - gap
    "89 55 14 "                             # mov  [ebp+0x14],edx
    "89 96 90 53 00 00 "                    # mov  [esi+0x5390],edx
    "EB 0B "                                # jmp  out
    # top:
    "8B 55 14 "                             # mov  edx,[ebp+0x14]      y (= ty/8, kept)
    "01 C2 "                                # add  edx,eax
    "89 96 90 53 00 00 "                    # mov  [esi+0x5390],edx    attach_y = y + winH
    # out:
    "5A 59 58 "                             # pop  edx / ecx / eax
    "8B 45 20 "                             # mov  eax,[ebp+0x20]      (displaced)
    "85 C0 "                                # test eax,eax             (displaced: flags for the jl)
    "C3"                                    # ret  -> 0x4BE391
)


def _scrloc(field: str) -> str:
    return (
        "83 3D {abs32:g_popup_scale_num} 10 "   # cmp  dword [g],16
        "7E 15 "                                # jle  store
        "85 C0 "                                # test eax,eax
        "7E 11 "                                # jle  store              (0 / negative: untouched)
        "3D 00 10 00 00 "                       # cmp  eax,0x1000
        "7D 0A "                                # jge  store              (centre sentinel and up)
        "0F AF 05 {abs32:g_popup_scale_num} "   # imul eax,[g]
        "C1 F8 04 "                             # sar  eax,4
        # store:
        f"89 86 {field} 30 00 00 "              # mov  [esi+0x30F8|FC],eax (displaced store)
        "C3"                                    # ret  -> the site's 90, then jmp parse loop
    )


SCRLOC_X_TEMPLATE = _scrloc("F8")
SCRLOC_Y_TEMPLATE = _scrloc("FC")


TW_OFFSET = 0xB840
SCRLOC_X_OFFSET = 0x1330
SCRLOC_Y_OFFSET = 0x1358
PCAVE2_VA = 0x00A0C000

# (name, offset, template, size, free range [lo, hi) per cave_map --at)
THUNKS = (
    ("t_tw_gap", TW_OFFSET, TW_TEMPLATE, 126, (0xB831, 0xB8C0)),
    ("t_scrloc_x", SCRLOC_X_OFFSET, SCRLOC_X_TEMPLATE, 37, (0x132F, 0x1390)),
    ("t_scrloc_y", SCRLOC_Y_OFFSET, SCRLOC_Y_TEMPLATE, 37, (0x132F, 0x1390)),
)

# (site VA, original bytes, new-bytes template)
SITE_TW = 0x004BE38C
SITE_TW_ORIGINAL = "8B 45 20 85 C0"
SITE_SCRLOC_X = 0x00601E91
SITE_SCRLOC_X_ORIGINAL = "89 86 F8 30 00 00"
SITE_SCRLOC_Y = 0x00601EDF
SITE_SCRLOC_Y_ORIGINAL = "89 86 FC 30 00 00"
SITES = (
    (SITE_TW, SITE_TW_ORIGINAL, "E8 {rel32:t_tw_gap}"),
    (SITE_SCRLOC_X, SITE_SCRLOC_X_ORIGINAL, "E8 {rel32:t_scrloc_x} 90"),
    (SITE_SCRLOC_Y, SITE_SCRLOC_Y_ORIGINAL, "E8 {rel32:t_scrloc_y} 90"),
)

G_ADDR = 0x00668740                      # g_popup_scale_num
SET_LOC = 0x00601B80                     # BasePop_set_loc
SYMS = {"g_popup_scale_num": G_ADDR}

# The documented asm, for the keystone cross-check of the hand encoding.
TW_ASM = """
push eax; push ecx; push edx
mov ecx, dword ptr [{g}]
cmp ecx, 16
jle out
lea eax, [ecx+ecx*4]
sar eax, 4
sub eax, 5
cmp dword ptr [ebp+0x10], 5
jne right
add dword ptr [ebp+0x10], eax
add dword ptr [esi+0x538C], eax
jmp ydo
right:
sub dword ptr [ebp+0x10], eax
sub dword ptr [esi+0x538C], eax
ydo:
mov edx, dword ptr [esi+0x30D0]
mov eax, edx
imul eax, ecx
sar eax, 4
sub eax, edx
add eax, dword ptr [esi+0x30C0]
mov edx, dword ptr [esi+0x5390]
cmp edx, dword ptr [ebp+0x14]
jne top
mov edx, dword ptr [ebp-0x18]
sub edx, eax
shl ecx, 3
sar ecx, 4
sub edx, ecx
mov dword ptr [ebp+0x14], edx
mov dword ptr [esi+0x5390], edx
jmp out
top:
mov edx, dword ptr [ebp+0x14]
add edx, eax
mov dword ptr [esi+0x5390], edx
out:
pop edx; pop ecx; pop eax
mov eax, dword ptr [ebp+0x20]
test eax, eax
ret
"""

SCRLOC_ASM = """
cmp dword ptr [{g}], 16
jle store
test eax, eax
jle store
cmp eax, 0x1000
jge store
imul eax, dword ptr [{g}]
sar eax, 4
store:
mov dword ptr [esi+{field}], eax
ret
"""

def documented_asm(name: str) -> str:
    g = f"{G_ADDR:#x}"
    return {
        "t_tw_gap": TW_ASM.format(g=g),
        "t_scrloc_x": SCRLOC_ASM.format(g=g, field="0x30F8"),
        "t_scrloc_y": SCRLOC_ASM.format(g=g, field="0x30FC"),
    }[name]


def blob(name: str) -> bytes:
    for n, off, tpl, _size, _free in THUNKS:
        if n == name:
            return resolve(tpl, PCAVE2_VA + off, SYMS)
    raise KeyError(name)


def _model_tw(g: int, sw: int, sh: int, box_w: int, box_h: int, btn_h: int, ty: int,
              left: bool, bottom: bool):
    """The template's arithmetic, op for op, applied to vanilla's placement."""
    half = box_w // 2
    x, ax = (5, 5 + half) if left else (sw - box_w - 5, sw - half - 5)
    y = sh - box_h - 8 if bottom else ty // 8
    ay = y if bottom else y + box_h
    if g <= 16:
        return x, y, ax, ay
    dx = ((5 * g) >> 4) - 5
    if x == 5:
        x, ax = x + dx, ax + dx
    else:
        x, ax = x - dx, ax - dx
    win_h = ((btn_h * g) >> 4) - btn_h + box_h
    if ay == y:
        y = ay = sh - win_h - ((8 * g) >> 4)
    else:
        ay = y + win_h
    return x, y, ax, ay


def main() -> int:
    from scaling_laws import popup_positive_loc, tutwin_place

    for name, off, tpl, size, (lo, hi) in THUNKS:
        n = len(blob(name))
        assert n == size, f"{name}: {n} B != {size}"
        assert lo <= off and off + n <= hi, f"{name} leaves its free range"
        print(f"{name}  {n} bytes @ pcave2+0x{off:X}..0x{off + n:X}")
        print(f'        bytes: "{tpl}"')
        print()
    assert SCRLOC_X_OFFSET + 37 <= SCRLOC_Y_OFFSET, "scrloc thunks overlap"

    try:
        from keystone import KS_ARCH_X86, KS_MODE_32, Ks
        import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
    except ImportError:
        print("keystone absent: hand encoding NOT cross-checked")
    else:
        ks = Ks(KS_ARCH_X86, KS_MODE_32)
        for name, off, _tpl, _size, _free in THUNKS:
            va = PCAVE2_VA + off
            want = bytes(ks.asm(documented_asm(name), va)[0])
            assert blob(name) == want, f"{name}: template != keystone({name} asm)"
        print("hand encodings == keystone(documented asm) for all 3 thunks")

    for g in range(16, 41):
        for sw, sh in ((1024, 768), (1600, 900), (1920, 1080), (1600, 1200), (3840, 2160)):
            for box_w, box_h, btn_h in ((480, 211, 20), (1224, 527, 20), (672, 199, 0)):
                for left in (True, False):
                    for bottom in (True, False):
                        ty = sh * 3 // 4
                        assert _model_tw(g, sw, sh, box_w, box_h, btn_h, ty, left, bottom) == \
                            tutwin_place(sw, sh, box_w, box_h, btn_h, ty, left, bottom, g), \
                            (g, sw, sh, box_w, box_h, left, bottom)
        for v in (-0x1001, -20, -5, -1, 0, 1, 5, 8, 10, 20, 40, 0x136, 0xFFF, 0x1000, 0x1001, 0x2000):
            have = v if (g <= 16 or not 0 < v < 0x1000) else (v * g) >> 4
            assert have == popup_positive_loc(v, g), (g, v)
    print("template arithmetic == scaling_laws.tutwin_place / popup_positive_loc for g in [16,40]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
