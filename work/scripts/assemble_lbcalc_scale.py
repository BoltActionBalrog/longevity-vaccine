# Regenerates the two type-2 ListBox source-scaling thunks (group popup_type2_list_scale):
#
#   thunk_lbsrc_scale  (fix 29, NEW)  CALL-redirect @0x404E93 -- Popup_calculate_dimensions'
#       BasePop_calc call, which already went to thunk_scale_box_margin.  The popup list's layout
#       sources are scaled ONCE, right after their one writer stored them native (stride 0x13
#       @0x404CE8, gap 3 @0x404D04, indent 3 @0x404D3F), then the old target runs:
#         if g > 16 && g_popup_active && [popup+0x2350] == 2 && [D+0x48] == 0x13:
#             [D+0x48] / [D+0x44] / [D+0x34] = fl(v * g/16)      (D = popup+0x21D0+[[popup+0x21D0]+8])
#         push thunk_scale_box_margin; ret                        (the E8's return 0x404E98 stays on top)
#       Law: scaling_laws.popup_listbox_sources.  esi = ecx = popup at the site (mov ecx,esi @0x404E7D);
#       every register is preserved (eax/edx pushed), flags are dead across the call.
#
#   thunk_lbcalc_scale v5 (pcave2 0x3E00) -- the ListBox_calculate_dimensions entry detour @0x60A1E0.
#       v5 RETIRES the g_popup_active arm: its "already scaled" key 0 < stride <= 0x16 cannot tell the
#       popup's native 19 from fl(19 g/16) = 20/21/22 at g = 17/18/19, so ListBox_attach's second calc
#       scaled the popup list again (the 1600x900 Go To list ran a row past its ring, under the buttons).
#       Left: the LOAD/SAVE picker arm (g_filedlg_active, native 0x16 -> fl(22 g/16) >= 23 closes the
#       key after one pass at ANY g).  Law: scaling_laws.listbox_calc_entry_sources.
#       Displaced entry bytes (push ebx / push esi / mov esi,ecx / xor ebx,ebx) replayed at the tail;
#       resume 0x60A1E6.  ecx preserved; eax/edx dead at entry.
#
# History: v3 gate g_popup_active; v4 OR g_filedlg_active (the file picker's populate calc ran before
#   thunk_filedlg_listpitch's first-draw scale); v5 (fix 29) g_filedlg_active only.
#
# Usage: py assemble_lbcalc_scale.py -> byte strings for patches.yaml (+ the template round-trip check).
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
LBCALC_OFF = 0x3E00
LBSRC_OFF = 0xC690          # cave_map --at 0xC690: free 0xc689..0xc720 (151 B) between thunk_bw_farmorb_sd2b (ends 0xc689) and thunk_bw_btnfont (starts 0xc720)

# sentinel immediates -> yaml placeholders (never branch operands: the tail is push imm32; ret)
G_POPUP = 0x11111111
G_FILEDLG = 0x22222222
G_SCALE = 0x33333333
BOX_MARGIN = 0x44444444
PLACEHOLDERS = {
    G_POPUP: "g_popup_active",
    G_FILEDLG: "g_filedlg_active",
    G_SCALE: "g_popup_scale_num",
    BOX_MARGIN: "thunk_scale_box_margin",
}

POPUP_TYPE = 0x2350         # popup [+0x2350]: the dims-dispatch key (0x6132A0 reaches the ListBox calc for exactly 2)
POPUP_LB = 0x21D0           # the popup's ListBox sub-object; its Dialog part = this + [[this]+8]
STRIDE_NATIVE = 0x13        # scaling_laws.POPUP_LB_STRIDE_NATIVE (Popup_calc @0x404CE8)


def asm_lbsrc(g_popup=G_POPUP, g_scale=G_SCALE, box_margin=BOX_MARGIN):
    return f"""
    cmp  dword ptr [{g_scale:#x}], 0x10
    jle  tail
    cmp  dword ptr [{g_popup:#x}], 0
    je   tail
    cmp  dword ptr [esi+{POPUP_TYPE:#x}], 2
    jne  tail
    push eax
    push edx
    mov  edx, dword ptr [esi+{POPUP_LB:#x}]
    mov  edx, dword ptr [edx+8]
    lea  edx, [edx+esi+{POPUP_LB:#x}]
    cmp  dword ptr [edx+0x48], {STRIDE_NATIVE:#x}
    jne  pops
    mov  eax, dword ptr [edx+0x48]
    imul eax, dword ptr [{g_scale:#x}]
    sar  eax, 4
    mov  dword ptr [edx+0x48], eax
    mov  eax, dword ptr [edx+0x44]
    imul eax, dword ptr [{g_scale:#x}]
    sar  eax, 4
    mov  dword ptr [edx+0x44], eax
    mov  eax, dword ptr [edx+0x34]
    imul eax, dword ptr [{g_scale:#x}]
    sar  eax, 4
    mov  dword ptr [edx+0x34], eax
pops:
    pop  edx
    pop  eax
tail:
    push {box_margin:#x}
    ret
"""


def asm_lbcalc(g_filedlg=G_FILEDLG, g_scale=G_SCALE):
    return f"""
    cmp  dword ptr [{g_filedlg:#x}], 0
    je   replay
    mov  eax, dword ptr [{g_scale:#x}]
    cmp  eax, 0x10
    jle  replay
    push ecx
    push edx
    mov  edx, dword ptr [ecx]
    mov  edx, dword ptr [edx+8]
    add  edx, ecx
    mov  ecx, dword ptr [edx+0x48]
    test ecx, ecx
    jle  pops
    cmp  ecx, 0x16
    jg   pops
    imul ecx, eax
    sar  ecx, 4
    mov  dword ptr [edx+0x48], ecx
    mov  ecx, dword ptr [edx+0x44]
    imul ecx, eax
    sar  ecx, 4
    mov  dword ptr [edx+0x44], ecx
    mov  ecx, dword ptr [edx+0x34]
    imul ecx, eax
    sar  ecx, 4
    mov  dword ptr [edx+0x34], ecx
pops:
    pop  edx
    pop  ecx
replay:
    push ebx
    push esi
    mov  esi, ecx
    xor  ebx, ebx
    push 0x60A1E6
    ret
"""


ENTRIES = (("thunk_lbcalc_scale", LBCALC_OFF, asm_lbcalc), ("thunk_lbsrc_scale", LBSRC_OFF, asm_lbsrc))


def _ks(src, va):
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    return bytes(enc)


def assemble(name):
    """Sentinel-immediate bytes of one entry (what to_yaml templatizes)."""
    off, fn = next((o, f) for n, o, f in ENTRIES if n == name)
    return _ks(fn(), PCAVE2 + off)


def to_yaml(b: bytes) -> str:
    out, i = [], 0
    while i < len(b):
        if i + 4 <= len(b):
            v = int.from_bytes(b[i:i + 4], "little")
            if v in PLACEHOLDERS:
                if i and b[i - 1] in (0xE8, 0xE9) or i > 1 and b[i - 2] == 0x0F and 0x80 <= b[i - 1] <= 0x8F:
                    raise AssertionError(f"placeholder after a branch opcode at +{i:#x}")
                out.append("{abs32:" + PLACEHOLDERS[v] + "}")
                i += 4
                continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


def roundtrip_problems() -> list:
    """Every templatized entry must resolve (patcher's ByteTemplate + the real symbol table) to exactly the bytes
    keystone assembles with the REAL addresses (feedback-templatize-branch-operands)."""
    import pathlib
    import apply_patches as ap
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml")
    st = ap.build_symbol_table(symbols, caves)
    real = {"g_popup": st["g_popup_active"], "g_filedlg": st["g_filedlg_active"], "g_scale": st["g_popup_scale_num"],
            "box_margin": st["thunk_scale_box_margin"]}
    out = []
    for name, off, fn in ENTRIES:
        va = PCAVE2 + off
        kw = {k: v for k, v in real.items() if k in fn.__code__.co_varnames}
        want = _ks(fn(**kw), va)
        got = ap.ByteTemplate(to_yaml(assemble(name))).resolve(va, st)
        if got != want:
            out.append(f"{name}: template resolves to different bytes")
    return out


if __name__ == "__main__":
    for name, off, _fn in ENTRIES:
        b = assemble(name)
        print(f"{name}: {len(b)} bytes @ pcave2+{off:#x} ({PCAVE2 + off:#x})")
        print(f'        bytes: "{to_yaml(b)}"')
    probs = roundtrip_problems()
    print("roundtrip:", "OK" if not probs else probs)
