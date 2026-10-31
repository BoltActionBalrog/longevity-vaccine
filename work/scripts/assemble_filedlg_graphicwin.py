# Regenerates thunk_filedlg_graphicwin v3 — the file-picker window GraphicWin_init
# call-redirect @0x4074f1 (FileDlg_layout; group filedlg_geometry).
#
# Entry stack: [esp]=ret(0x4074f6) [esp+4]=x [esp+8]=y [esp+0xc]=w [esp+0x10]=h;
# ecx = window (thiscall, preserved). Tail = push GraphicWin_init / ret.
#
# Vanilla (FileDlg_layout 0x407453..0x4074ef), with CH = g_console_strip_height:
#   x = (SW-0x13c)/2 - (console visible ? 0x17 : 0)      (cdq/sub/sar: truncating)
#   in-game  (console visible): w=0x18a h=0x191  y=SH-CH-0x191
#   main-menu                 : w=0x14e h=0x189  y=SH-CH-0x192
# CH is NOT 0 at the main menu: its one writer is MainWin_build's literal 0xD5 (0x459726), scaled to fl(213g/16)
# by thunk_hud_seedscale in the same build (g_hud_seedtable holds +0xD7C), and MainWin_build runs from
# system_init (0x58F1D1), which control_game calls (0x52AA39) before top_menu (0x52AC4A). The 1366x768 shot
# 20261022-210249 shows it: the main-menu window at y = 768 - 213 - 0x192 = 153.
# The in-game window's BOTTOM abuts the console top, and its visible part
# (window minus the 32px right scrollbar gap) is centred on SW/2; the main-menu window sits 9 above that top and
# its centre 9 right of SW/2.
# v1 screen-centred both paths: below 4K the scaled window then reached past
# the scaled console top and the HUD hid the OK/CANCEL row.
# v2 (law scaling_laws.filedlg_window_origin): in-game anchored as below; the main menu stayed screen-centred on
#   the belief that CH was 0 there (it is fl(213g/16)): 4K (1502, 589) vs vanilla x g/16 (1525, 623).
# v3 (2026-10-22 fix 19): BOTH paths take vanilla's anchors, scaled:
#   w,h  -> s(w), s(h)
#   x    -> c - s(c - x),  c = SW>>1   (vanilla's centre offset, scaled)
#   y    -> T - s(T - y),  T = SH - CH (vanilla's console-top anchor, scaled; CH is device via hud_seedscale)
# g<=16 -> native (gate on g_popup_scale_num). fix 10 (2026-10-18): the gate was SW<=1024, so at g=16 on a
# 1280..1366-wide screen the main-menu window was screen-centred instead of vanilla's bottom anchor
# (1280x768: (473,187) vs vanilla (482,153)). The gate keeps the 10-byte imm32 cmp encoding (81 3D disp32 imm32).
# popup_scale clobbers only EAX.
#
# Usage: py assemble_filedlg_graphicwin.py -> byte string with {abs32:}/{rel32:}
# placeholders for the patches.yaml cave entry.
import sys
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

SW, SH, CH = 0x11111111, 0x22222222, 0x33333333
POPUP_SCALE = 0x44444444
GWIN_INIT = 0x55555555
G_NUM = 0x66666666
PLACEHOLDERS = {
    G_NUM: "{abs32:g_popup_scale_num}",
    SW: "{abs32:ScreenWidth}",
    SH: "{abs32:ScreenHeight}",
    CH: "{abs32:g_console_strip_height}",
    GWIN_INIT: "{abs32:GraphicWin_init}",
}
THUNK_VA = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0xA16E50   # pcave2 (0xA0C000) + 0xAE50

# cmp dword ptr [g_popup_scale_num], 0x10 as the 10-byte imm32 form (keystone would emit the 7-byte imm8 form)
G_GATE = (".byte 0x81, 0x3D, " + ", ".join(f"{b:#04x}" for b in G_NUM.to_bytes(4, "little"))
          + ", 0x10, 0x00, 0x00, 0x00")

ASM = f"""
    {G_GATE}
    jle  tail
    push ecx
    mov  eax, dword ptr [esp+0x10]
    call {POPUP_SCALE:#x}
    mov  dword ptr [esp+0x10], eax
    mov  eax, dword ptr [esp+0x14]
    call {POPUP_SCALE:#x}
    mov  dword ptr [esp+0x14], eax
    mov  ecx, dword ptr [{SW:#x}]
    sar  ecx, 1
    mov  eax, ecx
    sub  eax, dword ptr [esp+0x8]
    call {POPUP_SCALE:#x}
    sub  ecx, eax
    mov  dword ptr [esp+0x8], ecx
    mov  ecx, dword ptr [{SH:#x}]
    sub  ecx, dword ptr [{CH:#x}]
    mov  eax, ecx
    sub  eax, dword ptr [esp+0xc]
    call {POPUP_SCALE:#x}
    sub  ecx, eax
    mov  dword ptr [esp+0xc], ecx
    pop  ecx
tail:
    push {GWIN_INIT:#x}
    ret
"""


def assemble(va=THUNK_VA):
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(ASM, va)
    return bytes(enc)


def to_yaml(b: bytes, va=THUNK_VA) -> str:
    out, i = [], 0
    while i < len(b):
        if i + 4 <= len(b):
            v = int.from_bytes(b[i:i + 4], "little")
            if v in PLACEHOLDERS:
                out.append(PLACEHOLDERS[v]); i += 4; continue
            if b[i - 1:i] == b"\xE8" and i > 0 and (va + i + 4 + v) & 0xFFFFFFFF == POPUP_SCALE:
                out.append("{rel32:popup_scale}"); i += 4; continue
        out.append(f"{b[i]:02X}"); i += 1
    return " ".join(out)


if __name__ == "__main__":
    b = assemble()
    print(f"{len(b)} bytes @ {THUNK_VA:#x}")
    print(to_yaml(b))
