"""Assemble the bottom-HUD strip-panel seed-rect thunk (group basewin_strip_scale)
plus thunk_hud_vehargs v2 (relocated from pcave2 0x50B0 — the zoom-guard grew it
past its 128B slot).

thunk_bw_striprects — call-target redirect of BaseWin_init's shared-font
  Font_init call @0x41F2A1 (E8 9A 9C 1F 00 -> Font_init 0x618F40). Runs AFTER
  the whole strip seed block (0x41EEB0..0x41F29B) and BEFORE any consumer
  (CHANGE/HURRY/red-button inits read the seeds later in BaseWin_init).
  g>16: rewrites all 13 strip panel rects + the 0x40e6c queue-hdr copy from the
  LIVE MainWin region globals (0x7AF5A0 A / 0x7AF5B0 S / 0x7AF5C0 C /
  0x7AF5D0 G — already device-scaled by the closed HUD work; never re-derive)
  with every native additive constant scaled fl(k*g/16). Port of
  scaling_laws.basewin_strip_seed_rects (parity: test_striprects_asm_parity).
  g<=16: straight fall-through (the vanilla block's output is untouched — also
  covers the ScreenWidth==800 alternate seed branch, which implies g==16).
  Tail-jmps Font_init with ecx/args/ret untouched (pushad/popad bracket).

thunk_hud_vehargs v2 — byte-compatible with v1 (hud_widgets_scale, entry detour
  of veh_draw 0x5594F0) plus ONE new gate: the size-sentinel rewrite is SKIPPED
  when the engine zoom globals are armed ([g_map_zoom_num] >= 1) AND the caller
  ret addr lies in the BaseWin range [0x408490,0x420000). BaseWin_draw_production
  /flash set g_map_zoom_num = 3*panelW/4, den=100 (self-scaling unit portrait by
  device panel width) and pass size=1 — v1 rewrote that sentinel to a fixed size
  and starved the zoom path (the tiny clipped unit picture). Garrison/supported
  call with zoom unset -> still rewritten. Map-screen StatusWin callers are
  outside the range -> untouched semantics.

Output: yaml `bytes:` lines to paste into patches.yaml (sentinel 0xDEADBE00 ->
{abs32:g_popup_scale_num}). Slots: striprects @0xD120, vehargs v2 @0xD500;
section end 0xD800. Regenerate from this script; do not hand-edit the yaml.
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0xA0C000
STRIPRECTS_OFF = 0xD120
VEHARGS_OFF = 0xD500
SECTION_END = 0xE000   # grown 0xD800->0xE000 2026-07-25d (strip slice-2a content)

SENT = {0xDEADBE00: "{abs32:g_popup_scale_num}"}

S = {
    "g_popup_scale_num": 0xDEADBE00,   # sentinel (resolves 0x668740)
    "g_popup_scale_real": 0x668740,    # v1 vehargs hardcoded the real addr; keep
    "Font_init": 0x618F40,
    "BaseWin_g": 0x6A7628,
    "g_map_zoom_num": 0x691E6C,
    "REGION_A": 0x7AF5A0,              # production+queue column
    "REGION_S": 0x7AF5B0,              # forces supported
    "REGION_C": 0x7AF5C0,              # plate + citizens
    "REGION_G": 0x7AF5D0,              # garrison
    "STRIP_CANVAS": 0x7AEC64,
    "STATUS_CANVAS": 0x8C59AC,
    "VEH_DRAW_RESUME": 0x5594F6,
    "STATUSWIN_RET_A": 0x4B84FD,
    "STATUSWIN_RET_B": 0x4B8350,
    "BASEWIN_LO": 0x408490,
    "BASEWIN_HI": 0x420000,
}

# scaled-constant table: k -> esp slot (after `sub esp,0x40`)
KS_SLOTS = [(1, 0x00), (2, 0x04), (3, 0x08), (4, 0x0C), (7, 0x10), (10, 0x14),
            (0x14, 0x18), (0x17, 0x1C), (0x19, 0x20), (0x2D, 0x24),
            (0x3A, 0x28), (0x3E, 0x2C), (0x30, 0x34)]
SLOT = {k: off for k, off in KS_SLOTS}
TA_TOP = 0x30                          # scratch: turnsA.top (esp slot, not a k)

BW = S["BaseWin_g"]


def f(off: int) -> int:
    """Static address of BaseWin_g field `off` (single instance)."""
    return BW + off


def asm_striprects() -> str:
    A, Sg, C, G = S["REGION_A"], S["REGION_S"], S["REGION_C"], S["REGION_G"]
    L = []
    add = L.append
    add(f"pushad")
    add(f"mov esi, dword ptr [{S['g_popup_scale_num']:#x}]")
    add("cmp esi, 0x10")
    add("jle done")
    add("sub esp, 0x40")
    for k, slot in KS_SLOTS:
        add(f"imul eax, esi, {k}")
        add("sar eax, 4")
        add(f"mov dword ptr [esp+{slot:#x}], eax")

    def gv(addr, sk, sign, store, keep=None):
        """eax = [addr] +/- s(sk); store to field; optionally copy to reg."""
        add(f"mov eax, dword ptr [{addr:#x}]")
        add(f"{'add' if sign > 0 else 'sub'} eax, dword ptr [esp+{SLOT[sk]:#x}]")
        add(f"mov dword ptr [{store:#x}], eax")
        if keep:
            add(f"mov {keep}, eax")

    def rv(reg, sk, sign, store, keep_slot=None):
        """eax = reg +/- s(sk); store."""
        add(f"mov eax, {reg}")
        add(f"{'add' if sign > 0 else 'sub'} eax, dword ptr [esp+{SLOT[sk]:#x}]")
        add(f"mov dword ptr [{store:#x}], eax")
        if keep_slot is not None:
            add(f"mov dword ptr [esp+{keep_slot:#x}], eax")

    # -- production +0x40c6c: [Al+s4, At+s4, 7(Ar-Al)//12 - s4, Ab-s4]
    gv(A + 0, 4, +1, f(0x40C6C))
    gv(A + 4, 4, +1, f(0x40C70))
    add(f"mov eax, dword ptr [{A + 8:#x}]")
    add(f"sub eax, dword ptr [{A + 0:#x}]")
    add("imul eax, eax, 7")
    add("mov ecx, 12")
    add("cdq")
    add("idiv ecx")
    add(f"sub eax, dword ptr [esp+{SLOT[4]:#x}]")
    add(f"mov dword ptr [{f(0x40C74):#x}], eax")
    add("mov ebx, eax")                                   # ebx = prod.r
    gv(A + 12, 4, -1, f(0x40C78), keep="edi")             # edi = prod.b
    # -- garrison +0x40c2c: [Gl, Gt+s4, Gr-s4, Gb-s4]
    add(f"mov eax, dword ptr [{G + 0:#x}]")
    add(f"mov dword ptr [{f(0x40C2C):#x}], eax")
    add("mov ebp, eax")                                   # ebp = garr.l (= Gl)
    gv(G + 4, 4, +1, f(0x40C30))
    gv(G + 8, 4, -1, f(0x40C34))
    gv(G + 12, 4, -1, f(0x40C38))
    # -- turnsB (HURRY) +0x40dfc: [prod.r+s3, prod.b-s23, garr.l-s7, prod.b-s3]
    rv("ebx", 3, +1, f(0x40DFC))
    rv("edi", 0x17, -1, f(0x40E00))
    rv("ebp", 7, -1, f(0x40E04))
    rv("edi", 3, -1, f(0x40E08))
    # -- turnsA (CHANGE) +0x40dec: [prod.r+s3, prod.b-s45, garr.l-s7, prod.b-s25]
    rv("ebx", 3, +1, f(0x40DEC))
    rv("edi", 0x2D, -1, f(0x40DF0), keep_slot=TA_TOP)
    rv("ebp", 7, -1, f(0x40DF4))
    rv("edi", 0x19, -1, f(0x40DF8))
    # -- queue outer +0x40c9c: [prod.r+s4, At+s4, Ar-s4, turnsA.t-s7]
    rv("ebx", 4, +1, f(0x40C9C))
    gv(A + 4, 4, +1, f(0x40CA0))
    gv(A + 8, 4, -1, f(0x40CA4))
    add(f"mov eax, dword ptr [esp+{TA_TOP:#x}]")
    add(f"sub eax, dword ptr [esp+{SLOT[7]:#x}]")
    add(f"mov dword ptr [{f(0x40CA8):#x}], eax")
    # -- queue hdr +0x40c7c: [prod.r+s7, At+s7, Ar-s7, t+s20]
    rv("ebx", 7, +1, f(0x40C7C))
    gv(A + 4, 7, +1, f(0x40C80))
    add(f"add eax, dword ptr [esp+{SLOT[0x14]:#x}]")
    add(f"mov dword ptr [{f(0x40C88):#x}], eax")
    gv(A + 8, 7, -1, f(0x40C84))
    # -- queue list +0x40c8c: [hdr.l, hdr.b+s2, hdr.r, turnsA.t-s10]
    add(f"mov eax, dword ptr [{f(0x40C7C):#x}]")
    add(f"mov dword ptr [{f(0x40C8C):#x}], eax")
    add(f"mov eax, dword ptr [{f(0x40C88):#x}]")
    add(f"add eax, dword ptr [esp+{SLOT[2]:#x}]")
    add(f"mov dword ptr [{f(0x40C90):#x}], eax")
    add(f"mov eax, dword ptr [{f(0x40C84):#x}]")
    add(f"mov dword ptr [{f(0x40C94):#x}], eax")
    add(f"mov eax, dword ptr [esp+{TA_TOP:#x}]")
    add(f"sub eax, dword ptr [esp+{SLOT[10]:#x}]")
    add(f"mov dword ptr [{f(0x40C98):#x}], eax")
    # -- +0x40e6c..78 = copy of queue hdr (vanilla block writes it; keep it live)
    for src, dst in ((0x40C7C, 0x40E6C), (0x40C80, 0x40E70),
                     (0x40C84, 0x40E74), (0x40C88, 0x40E78)):
        add(f"mov eax, dword ptr [{f(src):#x}]")
        add(f"mov dword ptr [{f(dst):#x}], eax")
    # -- pop (citizens) +0x40c5c: [Cl+s4, Cb-s58, Cr-s62, Cb-s4]
    gv(C + 0, 4, +1, f(0x40C5C))
    gv(C + 12, 0x3A, -1, f(0x40C60), keep="ebx")          # ebx = pop.t
    gv(C + 8, 0x3E, -1, f(0x40C64), keep="edi")           # edi = pop.r
    gv(C + 12, 4, -1, f(0x40C68), keep="ebp")             # ebp = pop.b
    # -- plate +0x40cac: [Cl+s4, Ct+s4, Cr-s4, pop.t-s4+s1]
    gv(C + 0, 4, +1, f(0x40CAC))
    gv(C + 4, 4, +1, f(0x40CB0))
    gv(C + 8, 4, -1, f(0x40CB4))
    add("mov eax, ebx")
    add(f"sub eax, dword ptr [esp+{SLOT[4]:#x}]")
    add(f"add eax, dword ptr [esp+{SLOT[1]:#x}]")
    add(f"mov dword ptr [{f(0x40CB8):#x}], eax")
    # -- red button frame +0x40e2c: [pop.r+s7, pop.t+s3, l+s48, t+s48]
    #    SIZE-ANCHORED (vanilla Cr-7/pop.b-3 = l/t+48 at native); 48=3*16 ->
    #    exact CEIL descale round-trip at every g.  NO -1 here: the art
    #    window is w = r-l off these same fields, so a field -1 shrinks
    #    frame AND art together (ring channels unchanged, art 1px under
    #    proportion).  Ring channel symmetry is fixed at the frame DRAW
    #    instead (t_info_btnframe, law basewin_redbtn_frame).
    rv("edi", 7, +1, f(0x40E2C))
    add(f"add eax, dword ptr [esp+{SLOT[0x30]:#x}]")
    add(f"mov dword ptr [{f(0x40E34):#x}], eax")
    rv("ebx", 3, +1, f(0x40E30))
    add(f"add eax, dword ptr [esp+{SLOT[0x30]:#x}]")
    add(f"mov dword ptr [{f(0x40E38):#x}], eax")
    # -- supported outer +0x40b7c: [Sl+s4, St+s4, Sr-s4, Sb-s4]
    gv(Sg + 0, 4, +1, f(0x40B7C))
    gv(Sg + 4, 4, +1, f(0x40B80))
    gv(Sg + 8, 4, -1, f(0x40B84))
    gv(Sg + 12, 4, -1, f(0x40B88))
    # -- supported hdr +0x40b5c: [Sl+s7, St+s7, Sr-s7, t+s20]
    gv(Sg + 0, 7, +1, f(0x40B5C))
    gv(Sg + 4, 7, +1, f(0x40B60))
    add(f"add eax, dword ptr [esp+{SLOT[0x14]:#x}]")
    add(f"mov dword ptr [{f(0x40B68):#x}], eax")
    gv(Sg + 8, 7, -1, f(0x40B64))
    # -- supported list +0x40b6c: [hdr.l, hdr.b+s2, hdr.r, Sb-s7]
    add(f"mov eax, dword ptr [{f(0x40B5C):#x}]")
    add(f"mov dword ptr [{f(0x40B6C):#x}], eax")
    add(f"mov eax, dword ptr [{f(0x40B68):#x}]")
    add(f"add eax, dword ptr [esp+{SLOT[2]:#x}]")
    add(f"mov dword ptr [{f(0x40B70):#x}], eax")
    add(f"mov eax, dword ptr [{f(0x40B64):#x}]")
    add(f"mov dword ptr [{f(0x40B74):#x}], eax")
    gv(Sg + 12, 7, -1, f(0x40B78))
    add("add esp, 0x40")
    add("done:")
    add("popad")
    add(f"jmp {S['Font_init']:#x}")
    return "\n".join(L)


def asm_vehargs_v2() -> str:
    """v1 (hud_widgets_scale, yaml 0x50B0) + the zoom/BaseWin-caller skip gate.
    Stack at entry: [esp]=thunk ret (0x5594F5), [esp+4]=caller ret,
    [esp+8]=buf, [esp+0x10]=x, [esp+0x18]=size."""
    return f"""
        mov eax, dword ptr [esp+8]
        cmp eax, {S['STRIP_CANVAS']:#x}
        je chk_g
        cmp eax, {S['STATUS_CANVAS']:#x}
        jne fin
    chk_g:
        mov eax, dword ptr [{S['g_popup_scale_real']:#x}]
        cmp eax, 0x10
        jle fin
        mov edx, dword ptr [esp+4]
        cmp edx, {S['STATUSWIN_RET_A']:#x}
        je xinset
        cmp edx, {S['STATUSWIN_RET_B']:#x}
        jne size_gate
    xinset:
        imul edx, eax, 0xb
        sar edx, 4
        sub edx, 0xb
        add dword ptr [esp+0x10], edx
    size_gate:
        cmp dword ptr [{S['g_map_zoom_num']:#x}], 1
        jl do_size
        mov edx, dword ptr [esp+4]
        cmp edx, {S['BASEWIN_LO']:#x}
        jb do_size
        cmp edx, {S['BASEWIN_HI']:#x}
        jb fin
    do_size:
        mov edx, dword ptr [esp+0x18]
        cmp edx, 0x10
        jg fin
        cmp edx, -0x10
        jl fin
        add edx, 0x10
        imul edx, eax
        sar edx, 4
        sub edx, 0x10
        mov dword ptr [esp+0x18], edx
    fin:
        add esp, 4
        push ebp
        mov ebp, esp
        sub esp, 0x2c
        push {S['VEH_DRAW_RESUME']:#x}
        ret
    """


def emit(name: str, off: int, asm: str) -> int:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(asm, addr=PCAVE2_VA + off)
    blob = bytes(code)
    out, i = [], 0
    while i < len(blob):
        for sent, tok in SENT.items():
            if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") == sent:
                out.append(tok)
                i += 4
                break
        else:
            out.append(f"{blob[i]:02X}")
            i += 1
    print(f"{name}  {len(blob)} bytes @ pcave2+{off:#x} (VA {PCAVE2_VA + off:#x})"
          f" .. end {off + len(blob):#x}")
    print('        bytes: "' + " ".join(out) + '"')
    print()
    return len(blob)


def raw(name: str, off: int, asm: str) -> bytes:
    """Assembled bytes with the sentinel left in place (for parity tests)."""
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(asm, addr=PCAVE2_VA + off)
    return bytes(code)


def main() -> int:
    n1 = emit("thunk_bw_striprects", STRIPRECTS_OFF, asm_striprects())
    assert STRIPRECTS_OFF + n1 <= VEHARGS_OFF, "striprects overruns the vehargs slot"
    n2 = emit("thunk_hud_vehargs (v2)", VEHARGS_OFF, asm_vehargs_v2())
    assert VEHARGS_OFF + n2 <= SECTION_END, "vehargs v2 overruns the section"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
