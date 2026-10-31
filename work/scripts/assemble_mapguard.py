"""Assemble thunk_drawmap_fullguard — full map redraw when the view spans the map (group map_recentre_fullredraw).

Defect (PRACX-exposed engine bug, user shot 20260920-001142 @4K): at PRACX's whole-map zoom an
ENGINE recentre (Console_focus 0x5108A0 <- enemy_move / battle_fight_2 / alien_move ...) mangles
the map: stale close-zoom rectangle, black area with labels only, one correct band.

MapWin_focus 0x46B310 sets [MapWin+0x21A44] (Thinker: drawOnlyCursor) = 1 around
MapWin_set_center 0x46B1F0 -> MapWin_draw_map 0x46A550, which then takes its SCROLL-BLIT path:
Buffer_copy_4 self-copy by the old->new tile pixel delta (0x46A93B), GraphicWin_fill_3(.., 0) over
the exposed strips, MapWin_gen_map for those strips only. Vanilla guards that path at
0x46A55D..0x46A587 (pixel offset != 0 -> flag = 0 -> full redraw) but BEFORE
MapWin_calculate_dimensions (0x46A5A9) recomputes the view. When the view spans the map the strip
maths (raw tile delta vs tile_to_pixel's wrap-normalised delta; "delta > visible width" escape
unreachable at width = mapW+1) is wrong and the letterbox offset can be exactly 0, so the early
guard never fires.

Fix: replay the guard AFTER calculate_dimensions. Detour the 6-byte `cmp [esi+0x21A44],edi`
@0x46A5AE; clear the flag when the post-calc pixel offset is nonzero (vanilla's own predicate) or
the visible tile span covers the map on either axis (the predicate WorldWin_draw_box.gate already
uses for the width), then replay the cmp and resume at the `je` @0x46A5B4. Entry state: esi = this,
edi = 0, eax dead (both successors reload it). Pure tile-count logic -> no scale gate.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
OFF, BUDGET = 0x5CA8, 0x48         # between thunk_minimap_force (ends 0x5CA6) and g_mm_lastX (0x5CF0)
VA = PCAVE2_VA + OFF

SITE    = 0x46A5AE                  # cmp [esi+0x21a44],edi  (39 BE 44 1A 02 00)
RESUME  = 0x46A5B4                  # je 0x46AB56 (full redraw) / fallthrough = scroll-blit
MAP_W   = 0x949870
MAP_H   = 0x949874

ASM = f"""
    mov eax, dword ptr [esi + 0x1ddac]
    or  eax, dword ptr [esi + 0x1ddb0]
    jnz force
    mov eax, dword ptr [esi + 0x1ddcc]
    add eax, dword ptr [esi + 0x1ddd4]
    cmp eax, dword ptr [{MAP_W:#x}]
    jge force
    mov eax, dword ptr [esi + 0x1ddd0]
    add eax, dword ptr [esi + 0x1ddd8]
    cmp eax, dword ptr [{MAP_H:#x}]
    jl tail
force:
    mov dword ptr [esi + 0x21a44], edi
tail:
    cmp dword ptr [esi + 0x21a44], edi
    jmp {RESUME:#x}
"""

def assemble():
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    enc, _ = ks.asm(ASM, VA)
    b = bytes(enc)
    assert len(b) <= BUDGET, f"thunk {len(b)}B exceeds budget {BUDGET}"
    return b

def main():
    b = assemble()
    print(f"thunk_drawmap_fullguard @ pcave2+{OFF:#06x} (VA {VA:#x}) = {len(b)} bytes")
    print(" ".join(f"{x:02X}" for x in b))
    print()
    print(f"site @{SITE:#x} (6B): E9 {{rel32:thunk_drawmap_fullguard}} 90  (over: 39 BE 44 1A 02 00)")

if __name__ == "__main__":
    main()
