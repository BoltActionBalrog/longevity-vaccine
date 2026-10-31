"""Assemble thunk_tutbtn_post v3 -- the 2D-zoom shrink's dim-descale fixup.

PORT OF: scaling_laws.py :: btn_native_dim()  (the SOURCE OF TRUTH, v2 CEIL).

v2 (@0xAA60, 120B) rounded g_btn_nativeH only ("W untouched -- round==floor
for all seen"). Two problems surfaced 2026-07-21e (1600x1200 report):

  (1) W was never lawed at all: thunk_btn_shrink's raw floor stood. The
      BaseWin GOVERNOR chevrons are FIXED-ART 20x20 state-sprite buttons
      (window w/h = the sprite's own dims, BaseWin_init +0xc9e4); their W
      descaled fl(31*16/25) = 19, the KSB declared a 19-wide source and the
      art's 20th column -- the bright right border -- was never sampled
      ("chevron overlapped by the button on its right"). 9-slice buttons
      self-heal (they re-render at the believed width); fixed art cannot.
  (2) round is not the inverse of the FLOOR forward every window family
      actually ships (popup_scale_floor / gwinit imul-sar4): it under-
      recovers whenever (n*g mod 16)/g > 1/2 (238@g25 -> 237, 20@g23 -> 19).
      CEIL is exact at every g (the all-resolutions rule) and agrees with
      v1-round on every previously user-verified dim (20/22-native at
      g=22/25/40), so no approved screen moves.

v3 = v2 with (a) both H and W descaled by CEIL `(dim*16 + g - 1) / g`,
(b) RELOCATED 0xAA60 -> 0x4000 (grew 120 -> 143; the old slot ends flush
against thunk_pref_gwinit @0xAAE0; 0x4000 is the measured-free 672B gap left
by fe_pair_remap v4 -> v5 @0xC1C0). The TutWin canvas-font tail is byte-
identical. thunk_btn_shrink's tail `push {abs32:thunk_tutbtn_post}` re-
resolves to the new slot; the old 0xAA60 bytes are zeroed by the section.

Runs BEFORE FlatButton_content_draw's render (shrink's tail target), so the
9-slice/state-sprite render, the KSB src dims and [esi+0x4c4/0x4c8] all see
the same corrected native -- no consumer mix.
"""
from pathlib import Path
import sys

TEMPLATE = (
    "9C 60 "                                   # pushfd; pushad
    "83 3D {abs32:g_btn_pending} 01 "          # cmp [g_btn_pending],1
    "75 74 "                                   # jne exit
    "8B 0D {abs32:g_popup_scale_num} "         # mov ecx,[g]
    "83 F9 10 "                                # cmp ecx,16
    "7E 69 "                                   # jle exit
    # H: nativeH = ceil(|origH|*16 / g), store neg to [esi+0x4c8]
    "A1 {abs32:g_btn_origH} "                  # mov eax,[g_btn_origH]
    "F7 D8 "                                   # neg eax
    "C1 E0 04 "                                # shl eax,4
    "01 C8 "                                   # add eax,ecx
    "48 "                                      # dec eax
    "33 D2 "                                   # xor edx,edx
    "F7 F1 "                                   # div ecx
    "A3 {abs32:g_btn_nativeH} "                # mov [g_btn_nativeH],eax
    "F7 D8 "                                   # neg eax
    "89 86 C8 04 00 00 "                       # mov [esi+0x4c8],eax
    # W: nativeW = ceil(origW*16 / g)          (NEW in v3)
    "A1 {abs32:g_btn_origW} "                  # mov eax,[g_btn_origW]
    "C1 E0 04 "                                # shl eax,4
    "01 C8 "                                   # add eax,ecx
    "48 "                                      # dec eax
    "33 D2 "                                   # xor edx,edx
    "F7 F1 "                                   # div ecx
    "A3 {abs32:g_btn_nativeW} "                # mov [g_btn_nativeW],eax
    "89 86 C4 04 00 00 "                       # mov [esi+0x4c4],eax
    # TutWin-only canvas font. v4 (2026-09-17, audit finding 3.7): the TOUR/Close buttons draw with the
    # engine's default label Font 0x7D3948 = Arial 12 REGULAR (probe hook_btnfont_probe.js); t_ffn(12, 0)
    # = Arial fl(12g/16) regular on the (12,0) slot -- v3 asked the pool for scale_px(12,g) = Arial Narrow bold.
    "8B 86 C4 00 00 00 "                       # mov eax,[esi+0xc4]
    "3D 68 6E 8C 00 "                          # cmp eax,TutWin 0x8c6e68
    "74 08 "                                   # je font
    "81 FE C4 78 8C 00 "                       # cmp esi,TutWin+0xA5C
    "75 1C "                                   # jne exit
    "6A 00 6A 0C "                             # font: push 0; push 12   (NATIVE size + variant)
    "E8 {rel32:t_ffn} "
    "83 C4 08 "                                # add esp,8
    "8D 8E 44 04 00 00 "                       # lea ecx,[esi+0x444]
    "6A 00 50 50 50 "                          # push 0; push eax x3
    "E8 {rel32:Buffer_set_font} "
    "61 9D "                                   # exit: popad; popfd
    "68 {abs32:t_btn_nath_pin} "               # v5 (2026-10-22 fix 19): tail -> the pin (was push 0x607e85)
    "C3"
)

# t_btn_nath_pin (110 B @0x3EF0, 2026-10-24 wave-1 fix 27: + the NetWin lobby LAUNCH GAME / CANCEL compares, in place,
# 0x3F5E..0x3F60 zero; was 94 B = fix 22b = fix 21's admit byte-for-byte: fix 22's HUD M / I compares removed, in
# place at fix 22's slot; fix 21: 94 B @0xB2A0, that slot is free; was t_rw_tabbtn_nath 78 B @0x6D70, fix 19; law
# scaling_laws.flatbutton_zoom_src_h / flatbutton_nath_pinned): thunk_tutbtn_post's tail.
# The four HQ console tab buttons (ReportIf 0x885F38 + 0xBA0C / 0xC558 / 0xD138 / 0xDC84; rw_tab_pair's channel
# law) and the six CouncilWin buttons ([0x6FFA14, 0x703DDC), CouncilWin + 0xD94 stride 0xB4C; council_btn_h =
# s(23) - s(3)) and the NetWin lobby's LAUNCH GAME / CANCEL (0x80F674 / 0x8101C0; their rows are the rect table's
# two floored edges fl(232g/16) - fl(212g/16), netwin_btn_h) are vanilla 0x14 high with the default 20-row art, but
# their device height is not fl(20g/16), so the CEIL inverse above recovers 21 (22: tabs at g=19) native rows; the
# art is top-anchored and the zoom mapped the bottom device rows to the key row (Council: 2 rows short at g
# 26/30/31/35/37/39, 1 row at g 19/21/23; lobby: 27 of 28 rows at 1920x1080).
# Pin their zoom source to vanilla's own 0x14 (g_btn_nativeH and [esi+0x4C8] = -0x14) when the 2D zoom is armed
# (g_btn_pending == 1 && g > 16).  Registers untouched; flags saved.
# Every other button passes through: an object list because the default art is also worn by vanilla-0x16 buttons
# (faction picker text buttons, Load/Save OK / CANCEL) whose 2-row key band is vanilla's.  The HUD M / I buttons
# (MainWin FlatButtons[0] / [1] 0x7AF620 / 0x7B016C) are NOT pinned (fix 22b, the user's symmetry rule: a pin fills
# each to its own window, and the floor-of-both-edges windows differed by a row).  Fix 23 makes them s(20) squares at
# the source (hud_mi_btn_rect, t_hud_mi_square = thunk_hud_seedscale's tail), where the CEIL inverse is already 20.
TABNATH_TEMPLATE = (
    "9C "                                      # pushfd
    "83 3D {abs32:g_btn_pending} 01 "          # cmp [g_btn_pending],1
    "75 5D "                                   # jne out
    "83 3D {abs32:g_popup_scale_num} 10 "      # cmp [g],0x10
    "7E 54 "                                   # jle out
    "81 FE 44 19 89 00 "                       # cmp esi,0x891944   TECHNOLOGY
    "74 38 "                                   # je hit
    "81 FE 90 24 89 00 "                       # cmp esi,0x892490   BASES
    "74 30 "                                   # je hit
    "81 FE 70 30 89 00 "                       # cmp esi,0x893070   GOVERNOR
    "74 28 "                                   # je hit
    "81 FE BC 3B 89 00 "                       # cmp esi,0x893BBC   BEST BASES
    "74 20 "                                   # je hit
    "81 FE 74 F6 80 00 "                       # cmp esi,0x80F674   NetWin LAUNCH GAME (fix 27)
    "74 18 "                                   # je hit
    "81 FE C0 01 81 00 "                       # cmp esi,0x8101C0   NetWin CANCEL (fix 27)
    "74 10 "                                   # je hit
    "81 FE 14 FA 6F 00 "                       # cmp esi,0x6FFA14   CouncilWin FlatButton[0]
    "72 1C "                                   # jb out
    "81 FE DC 3D 70 00 "                       # cmp esi,0x703DDC   past FlatButton[5]
    "73 14 "                                   # jae out
    "C7 05 {abs32:g_btn_nativeH} 14 00 00 00 " # hit: mov [g_btn_nativeH],0x14
    "C7 86 C8 04 00 00 EC FF FF FF "           # mov [esi+0x4c8],-0x14
    "9D "                                      # out: popfd
    "68 85 7E 60 00 "                          # push 0x607e85 (original resume)
    "C3"
)
TABNATH_OFFSET = 0x3EF0   # fix 22's slot, kept (cave_map: free 0x3EE2..0x3F60, thunk_lbcalc_minw ends 0x3EE2)
TABNATH_END = 0x3F60

# dummy resolution values only for the structural disasm check
DUMMY = {
    "g_btn_pending": 0xA0C534, "g_popup_scale_num": 0x668740,
    "g_btn_origH": 0xA0C53C, "g_btn_nativeH": 0xA0C544,
    "g_btn_origW": 0xA0C538, "g_btn_nativeW": 0xA0C540,
    "find_font": 0x619560, "Buffer_set_font": 0x5D80E0, "t_ffn": 0xA3A570,
    "t_btn_nath_pin": 0xA0C000 + 0x3EF0,
}
BASE_VA = 0xA10000  # pcave2 VA 0xA0C000 + 0x4000


def resolve(tpl: str, base_va: int) -> bytes:
    out = bytearray()
    for tok in tpl.split():
        if tok.startswith("{abs32:"):
            out += DUMMY[tok[7:-1]].to_bytes(4, "little")
        elif tok.startswith("{rel32:"):
            target = DUMMY[tok[7:-1]]
            out += ((target - (base_va + len(out) + 4)) & 0xFFFFFFFF).to_bytes(4, "little")
        else:
            out.append(int(tok, 16))
    return bytes(out)


def main() -> int:
    blob = resolve(TEMPLATE, BASE_VA)
    n = len(blob)
    print(f"thunk_tutbtn_post v4  {n} bytes (slot 0x4000..0x{0x4000+n-1:04X}, "
          f"free gap ends 0x42A0)")
    assert n == 0x87, n
    assert 0x4000 + n <= 0x42A0

    # branch displacement audit: every exit branch lands on the popad
    exit_off = blob.index(bytes.fromhex("619D68"))
    assert blob[exit_off + 3:exit_off + 7] == DUMMY["t_btn_nath_pin"].to_bytes(4, "little"), "tail -> the pin"
    assert blob[0x09] == 0x75 and 0x0B + blob[0x0A] == exit_off, "jne(pending)"
    assert blob[0x14] == 0x7E and 0x16 + blob[0x15] == exit_off, "jle(g)"
    assert blob[0x61] == 0x75 and 0x63 + blob[0x62] == exit_off, "jne(tutwin)"
    assert blob[0x59] == 0x74 and blob[0x5A] == 0x08, "je(font)"

    # structural disasm (capstone if available)
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
        md = Cs(CS_ARCH_X86, CS_MODE_32)
        for ins in md.disasm(blob, BASE_VA):
            print(f"  {ins.address - BASE_VA:04x}  {ins.mnemonic:8s} {ins.op_str}")
    except ImportError:
        print("  (capstone not installed -- skipping disasm dump)")

    # law parity: the asm's ceil == scaling_laws.btn_native_dim for every
    # (dim, g); and the H path's neg round-trip is sign-correct.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import btn_native_dim, popup_scale_floor
    for g in range(17, 41):
        for nat in range(4, 700):
            dev = popup_scale_floor(nat, g)
            asm = (dev * 16 + g - 1) // g          # the div ecx result
            assert asm == btn_native_dim(dev, g) == nat, (nat, g)
    # the chevron signature: 20-native @ g=25 recovers 20 (v0 floor said 19)
    assert (popup_scale_floor(20, 25) * 16) // 25 == 19
    assert btn_native_dim(popup_scale_floor(20, 25), 25) == 20
    print("asm ceil == scaling_laws.btn_native_dim (exact floor-inverse) "
          "for g 17..40, n 4..699")

    print()
    print('        bytes: "' + TEMPLATE + '"')

    # ---- t_btn_nath_pin ----
    tva = DUMMY["t_btn_nath_pin"]
    tb = resolve(TABNATH_TEMPLATE, tva)
    assert len(tb) == 110, len(tb)
    assert TABNATH_OFFSET + len(tb) <= TABNATH_END
    out_off = len(tb) - 7                       # popfd; push 0x607e85; ret
    assert tb[out_off:] == bytes.fromhex("9D68857E6000C3")
    hit_off = tb.index(bytes.fromhex("C705"))
    for off, op in ((0x08, 0x75), (0x11, 0x7E), (0x49, 0x72), (0x51, 0x73)):
        assert tb[off] == op and off + 2 + tb[off + 1] == out_off, ("exit branch", hex(off))
    for off in (0x19, 0x21, 0x29, 0x31, 0x39, 0x41):
        assert tb[off] == 0x74 and off + 2 + tb[off + 1] == hit_off, ("hit branch", hex(off))
    objs = [int.from_bytes(tb[o + 2:o + 6], "little") for o in (0x13, 0x1B, 0x23, 0x2B, 0x33, 0x3B)]
    from scaling_laws import (RW_TAB_BTN_OBJECTS, COUNCIL_BTN_RANGE, BTN_BAR_NATIVE_H, HUD_MI_BTN_OBJECTS,
                              NETWIN_BTN_OBJECTS, flatbutton_nath_pinned, flatbutton_zoom_src_h)
    assert tuple(objs) == RW_TAB_BTN_OBJECTS + NETWIN_BTN_OBJECTS, [hex(o) for o in objs]
    assert not any(o.to_bytes(4, "little") in tb for o in HUD_MI_BTN_OBJECTS), "HUD M / I are not pinned"
    rng = tuple(int.from_bytes(tb[o + 2:o + 6], "little") for o in (0x43, 0x4B))
    assert rng == COUNCIL_BTN_RANGE, [hex(o) for o in rng]
    assert tb[hit_off + 6:hit_off + 10] == BTN_BAR_NATIVE_H.to_bytes(4, "little")
    assert tb[hit_off + 16:hit_off + 20] == (-BTN_BAR_NATIVE_H & 0xFFFFFFFF).to_bytes(4, "little")

    def asm_pins(esi):                          # the admit the bytes encode == the law's, on every boundary
        return esi in objs or rng[0] <= esi < rng[1]
    probes = set(RW_TAB_BTN_OBJECTS) | {o + d for o in RW_TAB_BTN_OBJECTS for d in (-1, 1, 0xB4C)}
    probes |= {o + d for o in HUD_MI_BTN_OBJECTS for d in (0, -1, 1, -0xB4C, 0xB4C)}   # all misses (fix 22b)
    assert not any(asm_pins(o) or flatbutton_nath_pinned(o) for o in HUD_MI_BTN_OBJECTS)
    probes |= {rng[0] - 1, rng[0], rng[1] - 1, rng[1], rng[0] + 0xB4C * 5, 0x82B988}
    probes |= {o + d for o in NETWIN_BTN_OBJECTS for d in (0, -1, 1, -0xB4C, 0xB4C)}   # fix 27: pinned (exact objects)
    assert all(asm_pins(o) and flatbutton_nath_pinned(o) for o in NETWIN_BTN_OBJECTS)
    for esi in probes:
        assert asm_pins(esi) == flatbutton_nath_pinned(esi), hex(esi)
        assert flatbutton_zoom_src_h(esi, 38, 30) == (20 if asm_pins(esi) else 21), hex(esi)
    try:
        from keystone import Ks, KS_ARCH_X86, KS_MODE_32
        import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
        ks_src = f"""
            pushfd
            cmp dword ptr [{DUMMY['g_btn_pending']:#x}], 1
            jne out
            cmp dword ptr [{DUMMY['g_popup_scale_num']:#x}], 0x10
            jle out
            cmp esi, {RW_TAB_BTN_OBJECTS[0]:#x}
            je hit
            cmp esi, {RW_TAB_BTN_OBJECTS[1]:#x}
            je hit
            cmp esi, {RW_TAB_BTN_OBJECTS[2]:#x}
            je hit
            cmp esi, {RW_TAB_BTN_OBJECTS[3]:#x}
            je hit
            cmp esi, {NETWIN_BTN_OBJECTS[0]:#x}
            je hit
            cmp esi, {NETWIN_BTN_OBJECTS[1]:#x}
            je hit
            cmp esi, {COUNCIL_BTN_RANGE[0]:#x}
            jb out
            cmp esi, {COUNCIL_BTN_RANGE[1]:#x}
            jae out
        hit:
            mov dword ptr [{DUMMY['g_btn_nativeH']:#x}], {BTN_BAR_NATIVE_H:#x}
            mov dword ptr [esi+0x4c8], {-BTN_BAR_NATIVE_H}
        out:
            popfd
            push 0x607e85
            ret
        """
        enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(ks_src, tva)
        assert bytes(enc) == tb, "hand-encoded t_btn_nath_pin != keystone"
        print("t_btn_nath_pin == keystone encoding")
    except ImportError:
        print("  (keystone not installed -- skipping the encoding cross-check)")
    print(f"t_btn_nath_pin  {len(tb)} bytes (slot 0x{TABNATH_OFFSET:X}..0x{TABNATH_OFFSET + len(tb):X})")
    print('        bytes: "' + TABNATH_TEMPLATE + '"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
