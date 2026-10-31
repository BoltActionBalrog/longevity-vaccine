"""Assemble thunk_worldwin_fill — box 8 (minimap / WorldWin) stretch-to-fill fix.

Defect (2026-07-06, 4K screenshot terranx_pracx_3840x2160_20260706-154906.png vs
refs/pristine/WorldMap.png): the lower-right minimap renders a small NATIVE-size world
map centered in the (correctly scaled) box, with a thick black margin all around —
pristine fills the box edge-to-edge.

Root cause (WorldWin_on_redraw @0x4C3EC0, decompiled): the minimap has an off-screen
map-render buffer sized to the whole planet at the main-map zoom (+0xa14 buf_w /
+0xa18 buf_h) and a window client rect (+0x4c4 win_w / +0x4c8 win_h, h stored NEGATIVE).
The tail branches:
    if (buf_w <= win_w && -win_h >= buf_h)  ->  center buffer 1:1 (Buffer_copy_4), else
                                                stretch buffer -> window (Buffer_copy_3).
Natively the whole-map buffer overflows the 239x119 window, so it always stretch-fills.
Our hud_console_scale seedtable scales the WorldWin rect (0x7AF51C..528 = MainWin+0xCFC..
D08, copied into the rect by WorldWin_init @0x4C49A0) x g/16 -> 597x297 @4K, but the map
buffer stays native. Now the native buffer FITS the enlarged window -> the center-1:1
branch fires -> small map, black margins.

Fix: make the center-vs-stretch DECISION resolution-independent by comparing the buffer
scaled x g/16 (buf * g >> 4) against the window. A map that overflowed the native window
still overflows the scaled window -> stretch-fills it (the stretch dest is win_w / -win_h,
already the scaled rect, so it fills the box at any resolution; the tile<->pixel maps and
the white location box both read win dims when the center offsets 0x239c4/0x239c8 are 0,
which the stretch branch sets, so they track the filled map too). g<=16 -> the displaced
instruction runs and we resume the ORIGINAL compare unchanged (byte-identical native).

Detour: 6-byte `push abs32; ret` at 0x4C411E (over MOV ECX,[ESI+0xa14]) into this thunk
in pcave2. ESI = WorldWin `this` throughout the fn; EBX = 0 const; EAX/ECX/EDX are dead
at the site (freshly loaded by the compares that follow). No return address is placed on
the stack (push/ret consumes it) -> no ret-leak class hazard.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
OFF, BUDGET = 0x5C00, 0x80        # tail after hud band re-stripe (ends 0x5BF9); 0x5C00..0x6000 free
VA = PCAVE2_VA + OFF

G = 0x668740                       # g_popup_scale_num (menu_strip_thunks+0x540 mirror; height-based, clamp 16..40)
NATIVE_RESUME  = 0x4C4124          # MOV EAX,[ESI+0x4c4] — resume the original compare
STRETCH_BRANCH = 0x4C41B6          # the Buffer_copy_3 stretch-to-window path

ASM = f"""
    mov eax, dword ptr [{G:#x}]
    cmp eax, 16
    jle native
    mov ecx, dword ptr [esi+0xa14]
    imul ecx, eax
    sar ecx, 4
    cmp dword ptr [esi+0x4c4], ecx
    jl stretch
    mov ecx, dword ptr [esi+0xa18]
    imul ecx, eax
    sar ecx, 4
    mov edx, dword ptr [esi+0x4c8]
    neg edx
    cmp edx, ecx
    jl stretch
native:
    mov ecx, dword ptr [esi+0xa14]
    jmp {NATIVE_RESUME:#x}
stretch:
    jmp {STRETCH_BRANCH:#x}
"""

def main():
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(ASM, VA)
    b = bytes(enc)
    assert len(b) <= BUDGET, f"thunk {len(b)}B exceeds budget {BUDGET}"
    hexs = " ".join(f"{x:02X}" for x in b)
    print(f"thunk_worldwin_fill @ pcave2+{OFF:#06x} (VA {VA:#x}) = {len(b)} bytes")
    print(hexs)
    # site detour bytes (informational): push abs32; ret at 0x4C411E over the 6-byte MOV
    print()
    print("site 0x4C411E new_bytes: 68 {abs32:thunk_worldwin_fill} C3   (over: 8B 8E 14 0A 00 00)")

if __name__ == "__main__":
    main()
