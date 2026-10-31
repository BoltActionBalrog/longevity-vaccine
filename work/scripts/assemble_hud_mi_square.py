"""Assemble t_hud_mi_square -- the HUD M / I / TOOLBAR column windows (fix 23, fix 23b).

PORT OF: scaling_laws.py :: hud_mi_column(), hud_mi_btn_rect(), hud_toolbar_rect()
(the SOURCE OF TRUTH; regenerate the yaml bytes from here, never hand-edit).

SITE: none of its own.  thunk_hud_seedscale (pcave2 0x4D00, call-redirected from MainWin_build's console2_A
Buffer_load_pcx call @0x459E8A) ends `popad; popfd; push imm32; ret`; its imm32 is retargeted from Buffer_load_pcx
to this thunk, which runs right after the 97-dword seed table is floored x g/16 and before any reader of the M / I /
TOOLBAR seed rects (BaseButton_init's arg loads @0x45A960 (I) / 0x45A9EB (M) / 0x45AA76 (TOOLBAR); the scenario-editor
info rect's right edge @0x45B491 (= I.l - s(3), t_ed_info_right since fix 24); the TutWin tour centres @0x4BD69D /
0x4BD718 much later).  The pre-detour
derivation (0x459B0A..0x459B78: M, I, TOOLBAR from the centre console +0xDA0) has already run on native values.

LAW: at g > 16, with s = s(20) = fl(20g/16) and every edge as seedscale floored it:
  column  l = r - s for M (+0xA2C), I (+0xA3C) and TOOLBAR (+0xA4C); r = fl(754g/16) stays (right-anchored)
  M       t = b - s            (anchored at its TOOLBAR-facing bottom fl(95g/16))
  I       b = t + s            (anchored at its TOOLBAR-facing top fl(143g/16))
  TOOLBAR rows unchanged (fl(100g/16), fl(138g/16))
M and I are s(20) squares, where the FlatButton 2D zoom's CEIL inverse is exactly 20 (the default art's rows / cols):
both faces fill and M == I at every g; the three windows share one left and one right edge.  g <= 16: no store
(seedscale itself is a no-op there; vanilla windows).

CONTRACT: entered by seedscale's `ret` with the call-redirect frame intact ([esp] = 0x459E8F, Buffer_load_pcx's
4 args above it, ecx = the Buffer `this`); every register and the flags are preserved (pushfd / pushad) and it
tail-jumps Buffer_load_pcx with push / ret.  Only the five dwords +0xA2C (M.l), +0xA30 (M.t), +0xA3C (I.l),
+0xA48 (I.b), +0xA4C (TOOLBAR.l) change.

SLOT: pcave2 0x2320 (cave_map.py --at / --fit 2026-10-23: free 0x2319..0x2370 between thunk_sprite_scale_nn and
what was then thunk_filedlg_rects; no abs32 / rel32 reference into it in the b7043354 bake).  2026-10-25 W2D moved
thunk_filedlg_rects to 0x37800, so the free run after this thunk now reaches g_filedlg_active (0x23A0).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

from scaling_laws import (BTN_BAR_NATIVE_H, HUD_MI_SEED_FIELDS, HUD_TOOLBAR_OBJ, HUD_TOOLBAR_SEED_FIELD,
                          NATIVE_G)

MAINWIN = 0x7AE820
CODE_VA = 0xA0C000 + 0x2320
SLOT_LIMIT = 0x50

M_OBJ, I_OBJ = 0x7AF620, 0x7B016C
BASE = MAINWIN + HUD_MI_SEED_FIELDS[M_OBJ]                    # +0xA2C: M l, t, r, b
M_OFF = 0
I_OFF = HUD_MI_SEED_FIELDS[I_OBJ] - HUD_MI_SEED_FIELDS[M_OBJ]             # +0x10
TB_OFF = HUD_TOOLBAR_SEED_FIELD - HUD_MI_SEED_FIELDS[M_OBJ]               # +0x20
assert (I_OFF, TB_OFF) == (0x10, 0x20) and HUD_TOOLBAR_OBJ == 0x7B0CB8

# sentinel imm32 -> patches.yaml placeholder
SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}", 0xDEADBE10: "{abs32:Buffer_load_pcx}"}

L, T, R, B = 0, 4, 8, 12


def _set(dst: int, src: int, op: str) -> str:
    """[base + dst] = [base + src] op s"""
    return f"""
    mov  eax, dword ptr [edx + {src:#x}]
    {op}  eax, ecx
    mov  dword ptr [edx + {dst:#x}], eax"""


ASM = f"""
    pushfd
    pushad
    mov  ecx, dword ptr [0xDEADBE00]
    cmp  ecx, {NATIVE_G:#x}
    jle  out
    imul ecx, ecx, {BTN_BAR_NATIVE_H:#x}
    sar  ecx, 4
    mov  edx, {BASE:#x}
    {_set(M_OFF + L, M_OFF + R, 'sub')}
    {_set(I_OFF + L, I_OFF + R, 'sub')}
    {_set(TB_OFF + L, TB_OFF + R, 'sub')}
    {_set(M_OFF + T, M_OFF + B, 'sub')}
    {_set(I_OFF + B, I_OFF + T, 'add')}
out:
    popad
    popfd
    push 0xDEADBE10
    ret
"""


def assemble(va: int = CODE_VA) -> bytes:
    code, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(ASM, addr=va)
    return bytes(code)


def template(blob: bytes) -> str:
    out, i = [], 0
    while i < len(blob):
        for sent, name in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(name)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    return " ".join(out)


def main() -> int:
    blob = assemble()
    assert len(blob) <= SLOT_LIMIT, f"{len(blob)} B does not fit the 0x2320..0x2370 slot"
    print(f"t_hud_mi_square  {len(blob)} bytes @ {CODE_VA:#x} (slot limit {SLOT_LIMIT})")
    print()
    print('        bytes: "' + template(blob) + '"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
