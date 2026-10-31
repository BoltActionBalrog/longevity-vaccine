#!/usr/bin/env python
"""msglog_scale bake (2026-09-18): the HUD event log (MessageWin 0x7F67F8, MESSAGES view of the
centre console).  Law scaling_laws.msglog_icon_layout + font_direct_law.

  t_msg_h     0x471887 `mov edx,[0x7F67E4]` (icon sprite height read of the row-centring math)
              -> edx = fl(h g/16).
  t_msg_icon  0x4718B8 the icon Sprite_draw_2 call: x += fl(4g/16) - 4 (the engine added the native
              inset 4), then its OWN blit (law msglog_icon_pixels): shape = centre NN, shade = dest-row
              parity through the art's own pair LUT.  (v1 tailed thunk_cw_portrait: pair-granular
              parity rows combed the arrowhead diagonal.)  g<=16 / unexpected sprite -> Sprite_draw_2.
REUSED (no new code): the Font_init(hud,12,0) site 0x471DA7 -> thunk_hud_font (direct-init law).
Row stride (B-T)/5 and text indent (B-T)/4 derive from the seed-scaled rect (already scale).
g<=16: both thunks are the identity (popup_scale at g=16).

Usage: py assemble_msglog.py            (assemble + print)
       py assemble_msglog.py --splice   (also splice into ..\\patches\\patches.yaml, byte-safe)
"""
import pathlib
import sys

import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402

PCAVE2 = 0x00A0C000
BASE_OFF = 0x29A00                     # cave_map --at 0x29A00: FREE (prev t_cmb_snap ends 0x299F5, next 0x2A000)
LIMIT_OFF = 0x2A000
PS = 0x668750                          # popup_scale: eax = eax*g >> 4
G = 0x668740                           # g_popup_scale_num
SD2 = 0x5E4B4A                         # Sprite_draw_2 (native path, g<=16)
ICON_H = 0x7F67E4                      # g_msglog_icon_sprite +0x1C

ks = Ks(KS_ARCH_X86, KS_MODE_32)
THUNKS = []


def T(name, asm):
    THUNKS.append((name, asm))


# 0x471887: mov edx,[0x7F67E4]   (flag-neutral; eax = row height live)
T("t_msg_h", f"""
    pushfd
    push eax
    mov eax, dword ptr [{ICON_H:#x}]
    call {PS:#x}
    mov edx, eax
    pop eax
    popfd
    ret
""")

# 0x4718B8: call Sprite_draw_2 (ecx=sprite; [esp+4] dest, +8 key, +0xC x, +0x10 y, 1, 1; RET 0x18)
# frame: [ebp+8]=dest [ebp+0xC]=key [ebp+0x10]=x [ebp+0x14]=y
# locals: -4 dData -8 dPitch -0xC g2 -0x10 sh -0x14 x0 -0x18 y0 -0x1C dw -0x20 dh -0x24 key -0x28 jj
#         -0x2C bgL -0x30 bgD -0x34 arL -0x38 arD
T("t_msg_icon", f"""
    push eax
    mov eax, 4
    call {PS:#x}
    sub eax, 4
    add dword ptr [esp+0x10], eax
    pop eax
    cmp dword ptr [{G:#x}], 16
    jg mi_own
mi_native:
    jmp {SD2:#x}
mi_own:
    cmp dword ptr [ecx+0x10], 16
    jne mi_native
    push ebp
    mov ebp, esp
    sub esp, 0x40
    push ebx
    push esi
    push edi
    mov esi, ecx
    mov ebx, dword ptr [esi+4]
    test ebx, ebx
    je mi_done
    mov eax, dword ptr [esi+0x14]
    test eax, eax
    jns mi_shok
    neg eax
mi_shok:
    cmp eax, 3
    jl mi_done
    mov dword ptr [ebp-0x10], eax
    mov edi, dword ptr [ebp+8]
    test edi, edi
    je mi_done
    mov eax, dword ptr [edi+0x54]
    test eax, eax
    je mi_done
    mov dword ptr [ebp-4], eax
    mov eax, dword ptr [edi+0x4A8]
    test eax, eax
    jle mi_done
    mov dword ptr [ebp-8], eax
    mov eax, dword ptr [{G:#x}]
    add eax, eax
    mov dword ptr [ebp-0xC], eax
    mov eax, dword ptr [esi+0x20]
    call {PS:#x}
    add eax, dword ptr [ebp+0x10]
    js mi_done
    mov dword ptr [ebp-0x14], eax
    mov eax, dword ptr [esi+0x24]
    call {PS:#x}
    add eax, dword ptr [ebp+0x14]
    js mi_done
    mov dword ptr [ebp-0x18], eax
    mov eax, dword ptr [esi+0x10]
    call {PS:#x}
    mov dword ptr [ebp-0x1C], eax
    add eax, dword ptr [ebp-0x14]
    cmp eax, dword ptr [edi+0x80]
    jg mi_done
    mov eax, dword ptr [ebp-0x10]
    call {PS:#x}
    mov dword ptr [ebp-0x20], eax
    add eax, dword ptr [ebp-0x18]
    mov edx, dword ptr [edi+0x84]
    test edx, edx
    jns mi_dhok
    neg edx
mi_dhok:
    cmp eax, edx
    jg mi_done
    mov eax, dword ptr [ebp+0xC]
    and eax, 0xFF
    mov dword ptr [ebp-0x24], eax
    movzx eax, byte ptr [ebx+1]
    mov dword ptr [ebp-0x2C], eax
    mov edx, dword ptr [esi+0xC]
    movzx eax, byte ptr [ebx+edx]
    mov dword ptr [ebp-0x30], eax
    movzx eax, byte ptr [ebx+edx+8]
    mov dword ptr [ebp-0x38], eax
    movzx eax, byte ptr [ebx+edx*2+8]
    mov dword ptr [ebp-0x34], eax
    mov dword ptr [ebp-0x28], 0
mi_row:
    mov eax, dword ptr [ebp-0x28]
    cmp eax, dword ptr [ebp-0x20]
    jge mi_done
    mov ecx, dword ptr [0x66879c]
    shr ecx, 1
    jnz mi_tok
    inc ecx
mi_tok:
    xor edx, edx
    div ecx
    mov dword ptr [ebp-0x3C], eax
    mov eax, dword ptr [ebp-0x28]
    lea eax, [eax*2+1]
    shl eax, 4
    xor edx, edx
    div dword ptr [ebp-0xC]
    cmp eax, dword ptr [ebp-0x10]
    jl mi_syok
    mov eax, dword ptr [ebp-0x10]
    dec eax
mi_syok:
    imul eax, dword ptr [esi+0xC]
    add eax, dword ptr [esi+4]
    mov ebx, eax
    mov eax, dword ptr [ebp-0x28]
    add eax, dword ptr [ebp-0x18]
    imul eax, dword ptr [ebp-8]
    add eax, dword ptr [ebp-4]
    add eax, dword ptr [ebp-0x14]
    mov edi, eax
    xor ecx, ecx
mi_col:
    cmp ecx, dword ptr [ebp-0x1C]
    jge mi_next
    lea eax, [ecx*2+1]
    shl eax, 4
    xor edx, edx
    div dword ptr [ebp-0xC]
    cmp eax, 16
    jl mi_sxok
    mov eax, 15
mi_sxok:
    movzx eax, byte ptr [ebx+eax]
    cmp eax, dword ptr [ebp-0x24]
    je mi_skip
    test byte ptr [ebp-0x3C], 1
    jnz mi_odd
    cmp eax, dword ptr [ebp-0x30]
    jne mi_e2
    mov eax, dword ptr [ebp-0x2C]
    jmp mi_put
mi_e2:
    cmp eax, dword ptr [ebp-0x38]
    jne mi_put
    mov eax, dword ptr [ebp-0x34]
    jmp mi_put
mi_odd:
    cmp eax, dword ptr [ebp-0x2C]
    jne mi_o2
    mov eax, dword ptr [ebp-0x30]
    jmp mi_put
mi_o2:
    cmp eax, dword ptr [ebp-0x34]
    jne mi_put
    mov eax, dword ptr [ebp-0x38]
mi_put:
    mov byte ptr [edi+ecx], al
mi_skip:
    inc ecx
    jmp mi_col
mi_next:
    inc dword ptr [ebp-0x28]
    jmp mi_row
mi_done:
    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    ret 0x18
""")

OUT = {}
off = BASE_OFF
for name, asm in THUNKS:
    enc, _ = ks.asm(asm, PCAVE2 + off)
    b = bytes(enc)
    OUT[name] = (off, b)
    print(f"OK  {name:14s} @0x{off:05X} len={len(b):3d}")
    off = (off + len(b) + 15) & ~15
assert off <= LIMIT_OFF, hex(off)

pe = pefile.PE(str(config.terranx_bak()), fast_load=True)
IMG = pe.OPTIONAL_HEADER.ImageBase


def orig(va, n):
    for s in pe.sections:
        a = IMG + s.VirtualAddress
        if a <= va < a + s.SizeOfRawData:
            return s.get_data()[va - a: va - a + n]
    raise KeyError(hex(va))


# (id, function, va, length, target, note)
SITES = [
    ("msgwin_init.font",      "MessageWin_init",      0x471DA7, 5, "thunk_hud_font", "Font_init(hud,12,0) event-log font"),
    ("msgwin_draw_icon.h",    "MessageWin_draw_icon", 0x471887, 6, "t_msg_h",        "icon sprite height read (row centring)"),
    ("msgwin_draw_icon.draw", "MessageWin_draw_icon", 0x4718B8, 5, "t_msg_icon",     "icon Sprite_draw_2: inset 4 scaled, own centre-NN + dest-parity blit"),
]
assert orig(0x471887, 6) == bytes.fromhex("8B15E4677F00"), orig(0x471887, 6).hex()
for sid, fn, va, ln, tgt, note in SITES:
    if ln == 5:
        assert orig(va, 5)[0] == 0xE8, (sid, orig(va, 5).hex())

GROUP = "msglog_scale"
M_SYM = (f"  # ==== {GROUP} symbols (2026-09-18, src assemble_msglog.py) ====\n", f"# ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} cave (src assemble_msglog.py; laws scaling_laws.msglog_icon_layout / msglog_icon_pixels) ====\n", f"# ==== {GROUP} END ==== cave\n")
M_GRP = (f"  # ==== {GROUP} group ====\n", f"# ==== {GROUP} END ==== groups\n")
M_SITE = (f"  # ==== {GROUP} sites (2026-09-18; src assemble_msglog.py) ====\n", f"# ==== {GROUP} END ==== sites\n")

sym = M_SYM[0]
for name, (o, b) in OUT.items():
    sym += f"  {name}:{' ' * max(1, 29 - len(name))}{{ cave: pcave2, offset: 0x{o:05x} }}   # {GROUP} ({len(b)}B)\n"
sym += M_SYM[1]

cave = M_CAVE[0]
for name, (o, b) in OUT.items():
    cave += f"      - id: {name}\n        offset: 0x{o:05x}\n        bytes: \"" + " ".join(f"{x:02X}" for x in b) + "\"\n"
cave += M_CAVE[1]

grp = M_GRP[0] + f"""  - id: {GROUP}
    description: >
      HUD EVENT LOG (MessageWin, the MESSAGES view of the centre console) scales with the HUD:
      the direct-init Arial 12 font (font_direct_law via thunk_hud_font) and the row icon (sprite
      height scaled at the engine's own centring read, inset 4 scaled, draw = centre NN shape +
      dest-row-parity shade, law msglog_icon_pixels).  Row stride and text indent derive from the seed-scaled rect.
      Law scaling_laws.msglog_icon_layout, parity tests\\test_scaling_msglog_parity.py.
    members:
""" + "".join(f"      - {s[0]}\n" for s in SITES) + M_GRP[1]

PAD = {5: "", 6: " 90"}
site = M_SITE[0]
for sid, fn, va, ln, tgt, note in SITES:
    site += (f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {fn}\n"
             f"    virtual_addr: 0x{va:08X}\n    length: {ln}\n"
             f"    original_bytes: \"{' '.join(f'{x:02X}' for x in orig(va, ln))}\"\n"
             f"    new_bytes:      \"E8 {{rel32:{tgt}}}{PAD[ln]}\"\n"
             f"    pattern: call_target_redirect\n    # {note}\n")
site += M_SITE[1]

if "--splice" in sys.argv:
    y = pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
    data = y.read_bytes()
    nl = b"\r\n" if b"\r\n" in data[:4096] else b"\n"

    def put(data, block, markers, anchor):
        blk = block.replace("\n", nl.decode()).encode("utf-8")
        a, z = markers[0].strip("\n").encode(), markers[1].strip("\n").encode()
        if a in data:                                    # refresh in place
            s = data.index(a)
            s = data.rfind(nl, 0, s) + len(nl)
            e = data.index(z, s) + len(z)
            if data[e:e + len(nl)] == nl:
                e += len(nl)
            assert 0 < s < e
            return data[:s] + blk + data[e:]
        anc = anchor.encode()
        assert data.count(anc) == 1, anchor
        p = data.index(anc) + len(anc)
        p = data.index(nl, p) + len(nl)
        return data[:p] + blk + data[p:]

    data = put(data, sym, M_SYM, "# ==== combat_console_scale END ==== symbols")
    data = put(data, cave, M_CAVE, "# ==== combat_console_scale END ==== cave")
    data = put(data, grp, M_GRP, "# ==== combat_console_scale END ==== groups")
    data = put(data, site, M_SITE, "# ==== combat_console_scale END ==== sites")
    y.write_bytes(data)
    print("spliced into", y)
