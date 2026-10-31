# Regenerates the FlatButton corner-notch thunks of the 2D-zoom pipeline (group popup_button_2dzoom; 2026-10-24
# wave-1 fix "F33"; laws scaling_laws.btn_corner_notch / btn_bar_tile_height; guards
# tests\test_scaling_btn_corner_states.py):
#
#   thunk_btn_fillcap v3 (pcave2 0x5920, in place, 96 -> 98 B; was hand-coded, src of v2 = assemble_hud_widgets.py)
#       call-redirect of FlatButton_content_draw's 9-slice body fill @0x608118.  v2 captured the body sprite only in
#       state 0 (ebp = the draw state), so a hover / pressed / lit compose never reached devfill's corner pass and its
#       corners stayed the NN-stretched 1-px art notch (4K 2x2 / 3x2 / 2x3 / 3x3, 1080p 1x1).  v3 captures in EVERY
#       state and records the state in g_btn_fill_state; the HUD MENU / COMMLINK / WORLD / DETAIL exclusion is kept.
#       The capture stays scoped to one compose: thunk_btn_shrink clears g_btn_fill_sprite at every compose entry, and
#       g_btn_fill_state is read only while g_btn_fill_sprite != 0 (both written by the same capture).
#
#   thunk_btn_devfill v4 (pcave2 0x1660, in place, 206 -> 224 B = the whole slot to thunk_corner_punch)
#       (1) the tile height D is the CENTRE-NN art bottom (btn_bar_tile_height v2): the device rows j the engine's
#           centre-sampled stretch maps to a native art row, min(|origH|, (2*artH*|origH| + nativeH - 1) //
#           (2*nativeH)).  v3's floor(artH*|origH|/nativeH) is one row short whenever that quotient's fraction is
#           >= 1/2 (22-native buttons at g 25: 30 vs the zoomed art's 31 rows), which left the NN'd art bottom row
#           below the re-tile and the bottom notch s x (s+1).  Identity whenever artH >= nativeH (every 20-native
#           class), as v3.
#       (2) state != 0 (g_btn_fill_state): no re-tile (the hover / pressed bodies are gradient sprites, not a
#           tileable dither: fillcap v2's rule), jump to t_btn_litcorner with D in eax.  State 0: v3's re-tile + four
#           unconditional s x s punches, byte-for-byte.
#
#   t_btn_litcorner (NEW, pcave2 0x32000): the non-0-state corner pass.  s = ceil(g/16); each of the four corners
#       whose device corner pixel is already key (the zoomed 1-px art notch) is punched to an s x s key square at
#       the true corner (bottom corners at the art bottom D, as state 0).  A corner whose art has no notch is left
#       alone.  The NN image of a 1-px notch is round(dev/native) <= s px per axis, so the punch always covers it:
#       the result is exactly s x s.  Clears g_btn_fill_sprite (devfill's own exit) and returns to devfill's caller.
#       Registers: devfill's non-zero contract (eax/ebx/ecx/edx/ebp/edi free inside thunk_btn_2dscale's pushad,
#       esi preserved); flags dead.
#
# The box-sprite FlatButton family (HUD TOOLBAR, Datalinks buttons; no 9-slice body fill) is thunk_btn_ringfix's
# (assemble_ringfix.py): its KxK corner punch no longer needs a drawn ring edge.
#
# Usage: py assemble_btn_litcorner.py -> byte templates for patches.yaml (+ round-trip / slot checks).
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
FILLCAP_OFF, FILLCAP_END = 0x5920, 0x5990          # cave_map --at 0x5980: free to thunk_hud_btnfont 0x5990
DEVFILL_OFF, DEVFILL_END = 0x1660, 0x1740          # the v3 slot; thunk_corner_punch starts 0x1740
LITCORNER_OFF, LITCORNER_END = 0x32000, 0x320F0    # W1B region 0x32000..0x32FFF
FILL_STATE_OFF = 0x32140                           # g_btn_fill_state (4 B)

HUD4 = (0x7B1804, 0x7B2350, 0x7B39E8, 0x7B4534)    # MainWin MENU / COMMLINK / WORLD / DETAIL (fillcap v2's lever V)
KEY = 9

# sentinel absolutes -> yaml placeholders
SYMS = {
    "g_btn_pending": 0x11110000, "g_popup_scale_num": 0x11110010, "g_btn_origH": 0x11110020,
    "g_btn_origW": 0x11110030, "g_btn_nativeH": 0x11110040, "g_btn_tileH": 0x11110050,
    "g_btn_fill_sprite": 0x11110060, "g_btn_fill_x": 0x11110070, "g_btn_fill_y": 0x11110080,
    "g_btn_fill_w": 0x11110090, "g_btn_fill_h": 0x111100A0, "g_btn_fill_state": 0x111100B0,
    "g_corner_dx": 0x111100C0, "g_corner_off": 0x111100D0,
}
# sentinel CALL targets -> {rel32:} placeholders
CALLS = {"fill_5da9f0": 0x22220000, "thunk_corner_punch": 0x22220010}
# real VAs (branch / tail operands are never templated)
FILL_5DA9F0 = 0x5DA9F0
LITCORNER_VA = PCAVE2 + LITCORNER_OFF


def S(name):
    return f"{SYMS[name]:#x}"


def asm_fillcap(fill=0x5DA9F0):
    return f"""
    cmp  dword ptr [{S('g_btn_pending')}], 0
    je   pass
    cmp  esi, {HUD4[0]:#x}
    je   pass
    cmp  esi, {HUD4[1]:#x}
    je   pass
    cmp  esi, {HUD4[2]:#x}
    je   pass
    cmp  esi, {HUD4[3]:#x}
    je   pass
    mov  dword ptr [{S('g_btn_fill_state')}], ebp
    mov  eax, dword ptr [esp+4]
    mov  dword ptr [{S('g_btn_fill_sprite')}], eax
    mov  eax, dword ptr [esp+0x10]
    mov  dword ptr [{S('g_btn_fill_x')}], eax
    mov  eax, dword ptr [esp+0x14]
    mov  dword ptr [{S('g_btn_fill_y')}], eax
    mov  eax, dword ptr [esp+0x18]
    mov  dword ptr [{S('g_btn_fill_w')}], eax
    mov  eax, dword ptr [esp+0x1c]
    mov  dword ptr [{S('g_btn_fill_h')}], eax
pass:
    push {fill:#x}
    ret
"""


def asm_devfill(litcorner=LITCORNER_VA):
    return f"""
    cmp  dword ptr [{S('g_btn_fill_sprite')}], 0
    je   done
    mov  eax, dword ptr [{S('g_btn_origH')}]
    neg  eax
    mov  ebx, eax
    mov  ecx, dword ptr [{S('g_btn_fill_sprite')}]
    mov  ecx, dword ptr [ecx+0x1c]
    imul ecx, eax
    mov  eax, dword ptr [{S('g_btn_nativeH')}]
    test eax, eax
    jle  full
    xchg ecx, eax
    lea  eax, [ecx+eax*2-1]
    add  ecx, ecx
    cdq
    idiv ecx
    cmp  eax, ebx
    jle  got
full:
    mov  eax, ebx
got:
    mov  dword ptr [{S('g_btn_tileH')}], eax
    cmp  dword ptr [{S('g_btn_fill_state')}], 0
    jne  {litcorner:#x}
    push eax
    push dword ptr [{S('g_btn_origW')}]
    push 0
    push 0
    push 0
    push 0
    push dword ptr [{S('g_btn_fill_sprite')}]
    lea  ecx, [esi+0x444]
    call {CALLS['fill_5da9f0']:#x}
    mov  ebp, dword ptr [{S('g_popup_scale_num')}]
    add  ebp, 0xf
    sar  ebp, 4
    mov  ecx, dword ptr [esi+0x8ec]
    mov  eax, dword ptr [esi+0x4c4]
    sub  eax, ebp
    mov  dword ptr [{S('g_corner_dx')}], eax
    mov  eax, dword ptr [{S('g_btn_tileH')}]
    sub  eax, ebp
    imul eax, ecx
    mov  dword ptr [{S('g_corner_off')}], eax
    mov  ebx, dword ptr [esi+0x498]
    mov  edi, ebx
    call {CALLS['thunk_corner_punch']:#x}
    mov  edi, ebx
    add  edi, dword ptr [{S('g_corner_dx')}]
    call {CALLS['thunk_corner_punch']:#x}
    mov  edi, ebx
    add  edi, dword ptr [{S('g_corner_off')}]
    call {CALLS['thunk_corner_punch']:#x}
    mov  edi, ebx
    add  edi, dword ptr [{S('g_corner_dx')}]
    add  edi, dword ptr [{S('g_corner_off')}]
    call {CALLS['thunk_corner_punch']:#x}
    mov  dword ptr [{S('g_btn_fill_sprite')}], 0
done:
    ret
"""


def asm_litcorner():
    """Entered by devfill's jne with eax = D (the art bottom), [esp] = devfill's return."""
    return f"""
    mov  ebp, dword ptr [{S('g_popup_scale_num')}]
    add  ebp, 0xf
    sar  ebp, 4
    cmp  eax, ebp
    jl   out
    mov  edx, dword ptr [esi+0x4c4]
    cmp  edx, ebp
    jl   out
    mov  ebx, dword ptr [esi+0x498]
    test ebx, ebx
    je   out
    mov  ecx, dword ptr [esi+0x8ec]
    sub  eax, ebp
    imul eax, ecx
    sub  edx, ebp
    mov  dword ptr [{S('g_corner_dx')}], edx
    mov  dword ptr [{S('g_corner_off')}], eax
    mov  edi, ebx
    cmp  byte ptr [edi], {KEY}
    jne  c1
    call {CALLS['thunk_corner_punch']:#x}
c1:
    mov  edi, ebx
    add  edi, dword ptr [{S('g_corner_dx')}]
    cmp  byte ptr [edi+ebp-1], {KEY}
    jne  c2
    call {CALLS['thunk_corner_punch']:#x}
c2:
    lea  edx, [ebp-1]
    imul edx, ecx
    mov  edi, ebx
    add  edi, dword ptr [{S('g_corner_off')}]
    cmp  byte ptr [edi+edx], {KEY}
    jne  c3
    call {CALLS['thunk_corner_punch']:#x}
c3:
    lea  edx, [ebp-1]
    imul edx, ecx
    add  edx, ebp
    mov  edi, ebx
    add  edi, dword ptr [{S('g_corner_dx')}]
    add  edi, dword ptr [{S('g_corner_off')}]
    cmp  byte ptr [edi+edx-1], {KEY}
    jne  out
    call {CALLS['thunk_corner_punch']:#x}
out:
    mov  dword ptr [{S('g_btn_fill_sprite')}], 0
    ret
"""


def assemble(src, va):
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    return bytes(enc)


def to_template(blob, va):
    """abs32 sentinels -> {abs32:name}; E8 to a CALL sentinel -> {rel32:name}."""
    rabs = {v: k for k, v in SYMS.items()}
    rcall = {v: k for k, v in CALLS.items()}
    out, i = [], 0
    while i < len(blob):
        if blob[i] == 0xE8 and i + 5 <= len(blob):
            tgt = (va + i + 5 + int.from_bytes(blob[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in rcall:
                out += ["E8", "{rel32:%s}" % rcall[tgt]]
                i += 5
                continue
        if i + 4 <= len(blob) and int.from_bytes(blob[i:i + 4], "little") in rabs:
            out.append("{abs32:%s}" % rabs[int.from_bytes(blob[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{blob[i]:02X}")
        i += 1
    return " ".join(out)


def resolve(tpl, va, syms, calls):
    """Template -> bytes at va with the given symbol VAs (the patcher's own rules: rel32 only after E8)."""
    out = bytearray()
    for tok in tpl.split():
        if tok.startswith("{abs32:"):
            out += syms[tok[7:-1]].to_bytes(4, "little")
        elif tok.startswith("{rel32:"):
            assert out[-1] == 0xE8
            out += ((calls[tok[7:-1]] - (va + len(out) + 4)) & 0xFFFFFFFF).to_bytes(4, "little")
        else:
            out.append(int(tok, 16))
    return bytes(out)


def build():
    parts = {}
    for name, off, end, src in (("thunk_btn_fillcap", FILLCAP_OFF, FILLCAP_END, asm_fillcap()),
                                ("thunk_btn_devfill", DEVFILL_OFF, DEVFILL_END, asm_devfill()),
                                ("t_btn_litcorner", LITCORNER_OFF, LITCORNER_END, asm_litcorner())):
        va = PCAVE2 + off
        blob = assemble(src, va)
        assert off + len(blob) <= end, (name, hex(off + len(blob)), hex(end))
        tpl = to_template(blob, va)
        assert resolve(tpl, va, SYMS, CALLS) == blob, name
        parts[name] = (off, len(blob), tpl)
    return parts


def main():
    for name, (off, n, tpl) in build().items():
        print(f"{name}  {n} B @0x{off:X}..0x{off + n:X}")
        print(f'        bytes: "{tpl}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
