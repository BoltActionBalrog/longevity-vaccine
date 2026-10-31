"""Assemble thunk_minimap_force — box 8 viewport-rectangle tracking (group hud_minimap_box).

Defect (pre-existing in PRACX, user-confirmed 2026-07-06): the white viewport rectangle on
the minimap (drawn only by WorldWin_draw_box @0x4C4630, reachable only from WorldWin_on_redraw
@0x4C3EC0) vanishes/freezes when the map is scrolled/zoomed/edge-panned. frida_minimapbox.log
proved two compounding causes: (1) during edge-scroll WorldWin_on_redraw does not fire while
the view moves (box erased, no repaint), and (2) draw_box is gated on F1(0x93345c)==0 &&
F2(0x933460)==0 — a "scroll in progress" suppressor (read ONLY by draw_box) that is nonzero
mid-scroll and settles to 0 only after motion stops, by which point no clean redraw fires.

The full fix is three parts; this script assembles part B. Parts A+C are an in-place rewrite
of draw_box's gate (see patches.yaml site WorldWin_draw_box.gate):
  A: drop the F1/F2 gate so the box draws at the current view whenever draw_box runs.
  C: hide the box when the viewport spans the whole map width — (Vw + Vw3) >= mapW
     (0x93347c + 0x933484 >= 0x949870). At PRACX's extreme zoom-out the viewport wraps the
     cylindrical map fully (widthTiles == mapW == 80, frida GEOM), degenerating draw_box's
     E-W wrap branch into a broken sliver; the whole map is already visible so a full-perimeter
     box conveys nothing -> hide it. Normal zoom widthTiles = 43/29 < 80 -> unaffected.

Part B (this thunk): force WorldWin_on_redraw after a map-view change so the box tracks during
and after scroll. Detours MapWin_draw_map @0x46A550 at entry (the main-map render, called on
every scroll/zoom/pan). Reentrancy-guarded by return-address: WorldWin's own callers of
MapWin_draw_map (on_redraw @0x4C4073, UNK2 @0x4C43B2 — the minimap content render) must NOT
re-force (would recurse). A view-changed check (vs g_mm_lastX/Y) avoids redundant forces. All
caller registers are preserved across the forced call (pushad/popad) so MapWin_draw_map's own
prologue saves the true caller ebx/esi. g<=16 is irrelevant here — the fix is resolution-
independent (the box logic is native), so no scale gate.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
OFF, BUDGET = 0x5C50, 0xA0          # after thunk_worldwin_fill (0x5C00..0x5C46); globals appended below
VA = PCAVE2_VA + OFF

# cave globals (last-view snapshot for the view-changed gate); placed right after the thunk
LASTX_OFF = 0x5CF0
LASTY_OFF = 0x5CF4
g_mm_lastX = PCAVE2_VA + LASTX_OFF
g_mm_lastY = PCAVE2_VA + LASTY_OFF

ON_REDRAW   = 0x4C3EC0
WORLDWIN    = 0x8E9F60
VX          = 0x933454
VY          = 0x933458
RET_ONREDRAW = 0x4C4073             # retaddr of MapWin_draw_map call inside WorldWin_on_redraw
RET_UNK2     = 0x4C43B2             # retaddr of the call inside WorldWin_UNK2
RESUME       = 0x46A556             # after the displaced prologue (push ebp; mov ebp,esp; sub esp,0x60)

ASM = f"""
    mov eax, dword ptr [esp]
    cmp eax, {RET_ONREDRAW:#x}
    je run_prologue
    cmp eax, {RET_UNK2:#x}
    je run_prologue
    mov eax, dword ptr [{VX:#x}]
    cmp eax, dword ptr [{g_mm_lastX:#x}]
    jne do_force
    mov eax, dword ptr [{VY:#x}]
    cmp eax, dword ptr [{g_mm_lastY:#x}]
    je run_prologue
do_force:
    mov eax, dword ptr [{VX:#x}]
    mov dword ptr [{g_mm_lastX:#x}], eax
    mov eax, dword ptr [{VY:#x}]
    mov dword ptr [{g_mm_lastY:#x}], eax
    pushad
    mov ecx, {WORLDWIN:#x}
    call {ON_REDRAW:#x}
    popad
run_prologue:
    push ebp
    mov ebp, esp
    sub esp, 0x60
    jmp {RESUME:#x}
"""

def main():
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(ASM, VA)
    b = bytes(enc)
    assert len(b) <= BUDGET, f"thunk {len(b)}B exceeds budget {BUDGET}"
    assert VA + len(b) <= g_mm_lastX, f"thunk overruns globals @ {g_mm_lastX:#x}"
    print(f"thunk_minimap_force @ pcave2+{OFF:#06x} (VA {VA:#x}) = {len(b)} bytes")
    print(" ".join(f"{x:02X}" for x in b))
    print(f"g_mm_lastX @ pcave2+{LASTX_OFF:#x}  g_mm_lastY @ pcave2+{LASTY_OFF:#x}")
    print()
    print("draw_box gate (site @0x4C4648, 26B):")
    print("  orig: A1 5C 34 93 00 85 C0 0F 85 8B 01 00 00 A1 60 34 93 00 85 C0 0F 85 7E 01 00 00")
    print("  new : A1 7C 34 93 00 03 05 84 34 93 00 3B 05 70 98 94 00 0F 8D 81 01 00 00 90 90 90")
    print("MapWin_draw_map detour (site @0x46A550, 6B): 68 {abs32:thunk_minimap_force} C3  (over: 55 8B EC 83 EC 60)")

if __name__ == "__main__":
    main()
