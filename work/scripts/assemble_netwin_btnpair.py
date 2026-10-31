# Regenerates t_nw_btnpair (group netwin_lobby_scale; 2026-10-24 wave-1 fix 27; law scaling_laws.netwin_btn_pair;
# guard tests\test_scaling_netwin_btnpair.py) and thunk_nw_rectscale v2 (its 5-byte CALL before the popad).
#
# The MULTIPLAYER SETUP lobby's LAUNCH GAME (NetWin +0xC34, FlatButton 0x80F674) and CANCEL (+0xC44, 0x8101C0) are
# a vanilla pair: (317, 212, 553, 232) and (556, 212, 792, 232) -- 236 wide each, a 3-px seam.  thunk_nw_rectscale
# floors every rect-table dword alone, so each width is fl(R g/16) - fl(L g/16): 236 g/16 rounded either way, and the
# two differ by 1 px at g 21/26/27/30/37 (2560x1440: 442 | 443).  t_nw_btnpair, CALLed from rectscale after the
# table scale (ebx = NetWin), keeps the pair's outer edges on their floor images (LAUNCH.L = fl(317g/16), the left
# column's content edge; CANCEL.R = fl(792g/16)) and gives both the SAME width w = (R - L - fl(3g/16)) >> 1, the odd
# px going to the seam (fl(3g/16) or one more):  LAUNCH.R = L + w, CANCEL.L = R - w.  Rows untouched (both share
# fl(212g/16) / fl(232g/16)).  g <= 16: vanilla (the law is also the identity there: 475 - 3 = 2 x 236).
# Every register is free (rectscale's popad follows); flags dead.
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
BTNPAIR_OFF, BTNPAIR_END = 0x320F0, 0x32140       # W1B region 0x32000..0x32FFF
RECTSCALE_OFF = 0x4850
RECTSCALE_END = 0x48D0                             # thunk_nw_font starts 0x48D0 (cave_map --at 0x48C3: free)
G_SCALE = 0x11111111

LAUNCH_RECT, CANCEL_RECT = 0xC34, 0xC44            # NetWin rect table: (L, T, R, B) dwords
RECTSCALE_V1 = ("60 8D BB 24 0A 00 00 B9 C4 00 00 00 8B 07 E8 {rel32:popup_scale} 89 07 83 C7 04 49 75 F1 B8 03 00 00 00 "
                "E8 {rel32:popup_scale} 8B 8B 74 04 00 00 03 C8 89 8B 14 0A 00 00 8B 8B 78 04 00 00 03 C8 89 8B 18 0A "
                "00 00 8B 93 7C 04 00 00 2B D0 89 93 1C 0A 00 00 B8 1A 00 00 00 E8 {rel32:popup_scale} 89 83 6C 01 00 "
                "00 03 83 18 0A 00 00 89 83 20 0A 00 00 61 8B 4E 0C 8B 56 04 C3")
RECTSCALE_TAIL = "61 8B 4E 0C 8B 56 04 C3"        # popad; replayed mov ecx,[esi+0xC] / mov edx,[esi+4]; ret
RECTSCALE_V2 = RECTSCALE_V1[:-len(RECTSCALE_TAIL)] + "E8 {rel32:t_nw_btnpair} " + RECTSCALE_TAIL


def asm_btnpair(g=G_SCALE):
    return f"""
    mov  ecx, dword ptr [{g:#x}]
    cmp  ecx, 0x10
    jle  done
    lea  eax, [ecx+ecx*2]
    sar  eax, 4
    mov  edx, dword ptr [ebx+{CANCEL_RECT + 8:#x}]
    sub  edx, dword ptr [ebx+{LAUNCH_RECT:#x}]
    sub  edx, eax
    sar  edx, 1
    mov  eax, dword ptr [ebx+{LAUNCH_RECT:#x}]
    add  eax, edx
    mov  dword ptr [ebx+{LAUNCH_RECT + 8:#x}], eax
    mov  eax, dword ptr [ebx+{CANCEL_RECT + 8:#x}]
    sub  eax, edx
    mov  dword ptr [ebx+{CANCEL_RECT:#x}], eax
done:
    ret
"""


def template():
    blob = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(asm_btnpair(), PCAVE2 + BTNPAIR_OFF)[0])
    assert BTNPAIR_OFF + len(blob) <= BTNPAIR_END
    tpl = " ".join(f"{b:02X}" for b in blob).replace("11 11 11 11", "{abs32:g_popup_scale_num}")
    assert tpl.count("{abs32:g_popup_scale_num}") == 1
    return blob, tpl


def main():
    blob, tpl = template()
    n2 = sum(4 if t.startswith('{') else 1 for t in RECTSCALE_V2.split())
    assert n2 == 120 and RECTSCALE_OFF + n2 <= RECTSCALE_END, n2
    print(f"t_nw_btnpair  {len(blob)} B @0x{BTNPAIR_OFF:X}..0x{BTNPAIR_OFF + len(blob):X}")
    print(f'        bytes: "{tpl}"')
    print(f"thunk_nw_rectscale v2  {n2} B @0x{RECTSCALE_OFF:X}..0x{RECTSCALE_OFF + n2:X}")
    print(f'        bytes: "{RECTSCALE_V2}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
