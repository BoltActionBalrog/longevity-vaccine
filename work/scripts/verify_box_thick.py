"""Capstone-verify the hand-assembled thunk_box_thick + thunk_ensure_frame_buf.

Resolves the {rel32:NAME}/{abs32:NAME} placeholders to real targets so branch
displacements and absolute pushes decode meaningfully, then disassembles at the
intended cave VA. Run with the bundled python.
"""
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

CAVE_VA = 0x00668200
SYM = {
    "g_popup_scale_num": CAVE_VA + 0x540,
    "Buffer_box_sprite": 0x005E2DD3,
    "Buffer_resize":     0x005D79C0,
    "Buffer_set_clip":   0x005D8000,
    "Buffer_fill_3":     0x005DFCD0,
    "Buffer_draw_2":     0x005D84C0,
    "thunk_ensure_frame_buf": CAVE_VA + 0xCE0,
    "thunk_box_thick":   CAVE_VA + 0xC00,
    "g_frame_buf":       CAVE_VA + 0xD10,
    "thunk_title_textnudge": CAVE_VA + 0xD20,
    "thunk_btntext_nudge":   CAVE_VA + 0xD40,
    "Buffer_set_font":   0x005DAC70,
    "Buffer_wrap_cent_4": 0x005DD920,
}

THUNK_BTNTEXT_NUDGE = (
    "50"                                    # push eax
    " A1 {abs32:g_popup_scale_num}"         # mov eax,[g]
    " 83 E8 10"                             # sub eax,16
    " C1 F8 03"                             # sar eax,3   -> N=(g-16)/8
    " 29 44 24 10"                          # sub [esp+0x10],eax  ; button label centred-Y arg -= N
    " 58"                                   # pop eax
    " 68 {abs32:Buffer_wrap_cent_4} C3"     # push writer; ret (tail-jmp, args intact)
)

THUNK_TITLE_TEXTNUDGE = (
    "51"                                    # push ecx
    " 8B 0D {abs32:g_popup_scale_num}"      # mov ecx,[g]
    " 83 E9 10"                             # sub ecx,16
    " C1 F9 03"                             # sar ecx,3   -> N=(g-16)/8
    " 29 4D F0"                             # sub [ebp-0x10],ecx   ; text top  -= N
    " 29 4D F8"                             # sub [ebp-8],ecx      ; text bot  -= N
    " 59"                                   # pop ecx (restore this=edi)
    " 68 {abs32:Buffer_set_font} C3"        # push Buffer_set_font; ret (tail-jmp, args intact)
)

THUNK_BOX_THICK = (
    "83 3D {abs32:g_popup_scale_num} 10"   # cmp [g_popup_scale_num], 16
    " 7F 06"                                # jg .hires (skip native push/ret = 6 bytes)
    " 68 {abs32:Buffer_box_sprite} C3"      # native: push real fn; ret (tail-jmp)
    # .hires:
    " 55 8B EC 83 EC 20 53 56 57"           # push ebp;mov ebp,esp;sub esp,0x20;push ebx,esi,edi
    " 89 4D FC"                             # [ebp-4]=dest (ecx)
    " 8B 45 0C 89 45 F8"                    # [ebp-8]=params ([ebp+0xc])
    " 8B 75 08"                             # esi=rectPtr ([ebp+8])
    " A1 {abs32:g_popup_scale_num} 83 E8 10 C1 E8 03 8B D8"  # ebx = (g-16)/8 = Delta (grow-outward px)
    " 8B 06 2B C3 89 45 F4"                 # [ebp-0xc]=L'=L-Delta (rect[0]-ebx)
    " 8B 46 04 2B C3 89 45 F0"              # [ebp-0x10]=T'=T-Delta (rect[1]-ebx)
    " 33 C9 89 4D E0 89 4D E4"              # xor ecx,ecx; smallRect.left=0; .top=0
    " 8B 46 08 2B 06 03 C3 03 C3 C1 E0 04"  # eax=(R-L)+2*Delta; <<4
    " 33 D2 F7 35 {abs32:g_popup_scale_num}"# xor edx; div [g] -> eax=smallW
    " 89 45 E8"                             # smallRect.right=smallW ([ebp-0x18])
    " 8B 46 0C 2B 46 04 03 C3 03 C3 C1 E0 04"  # eax=(B-T)+2*Delta; <<4
    " 33 D2 F7 35 {abs32:g_popup_scale_num}"# div [g] -> eax=smallH
    " 89 45 EC"                             # smallRect.bottom=smallH ([ebp-0x14])
    " E8 {rel32:thunk_ensure_frame_buf} 8B F8"  # edi=frameBuf
    " FF 75 EC FF 75 E8 8B CF E8 {rel32:Buffer_resize}"   # Buffer_resize(fb,smallW,smallH)
    " 8D 45 E0 50 8B CF E8 {rel32:Buffer_set_clip}"       # Buffer_set_clip(fb,&smallRect)
    " 6A 41 8D 45 E0 50 8B CF E8 {rel32:Buffer_fill_3}"   # Buffer_fill_3(fb,&smallRect,0x41)
    " FF 75 F8 8D 45 E0 50 8B CF E8 {rel32:Buffer_box_sprite}"  # Buffer_box_sprite(fb,&smallRect,params)
    " 6A 10 FF 35 {abs32:g_popup_scale_num} FF 75 F0 FF 75 F4 6A FF FF 75 FC 8B CF E8 {rel32:Buffer_draw_2}"  # Buffer_draw_2(fb,dest,-1,L',T',g,16)
    " 5F 5E 5B 8B E5 5D C2 08 00"           # pop edi,esi,ebx; leave; ret 8
)

THUNK_ENSURE_FRAME_BUF = (
    "A1 {abs32:g_frame_buf}"
    " 85 C0 75 1B"
    " 68 88 05 00 00"
    " E8 {rel32:crt_malloc} 83 C4 04"
    " 8B C8 50"
    " E8 {rel32:Buffer_ctor} 58"
    " A3 {abs32:g_frame_buf}"
    " C3"
)
SYM["crt_malloc"] = 0x0064558A
SYM["Buffer_ctor"] = 0x005D7210


def resolve(tmpl, base_va):
    """Return raw bytes; placeholders resolved relative to where each lands."""
    toks = tmpl.replace("\n", " ").split()
    # First pass: compute length by treating each placeholder as 4 bytes.
    out = bytearray()
    i = 0
    # We need addresses of placeholders to resolve rel32; do a two-pass.
    # Pass 1: build a list of ("byte",v) or ("rel32"/"abs32", name) and offsets.
    items = []
    for t in toks:
        if t.startswith("{"):
            kind, name = t[1:-1].split(":")
            items.append((kind, name, len(out)))
            out += b"\x00\x00\x00\x00"
        else:
            items.append(("byte", int(t, 16), len(out)))
            out.append(int(t, 16))
    # Pass 2: fill placeholders.
    for kind, name, off in items:
        if kind == "byte":
            continue
        target = SYM[name]
        if kind == "abs32":
            val = target & 0xFFFFFFFF
        elif kind == "rel32":
            # E8 is the byte right before off; call_va = base+off-1
            call_site = base_va + off - 1
            val = (target - (call_site + 5)) & 0xFFFFFFFF
        out[off:off+4] = val.to_bytes(4, "little")
    return bytes(out)


def show(name, tmpl, base_va):
    code = resolve(tmpl, base_va)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    print(f"\n===== {name} @ 0x{base_va:08x}  ({len(code)} bytes) =====")
    for ins in md.disasm(code, base_va):
        raw = " ".join(f"{b:02x}" for b in ins.bytes)
        print(f"  0x{ins.address:08x}  {raw:<26}  {ins.mnemonic} {ins.op_str}")
    end = base_va + len(code)
    print(f"  end = 0x{end:08x}  (offset 0x{end-CAVE_VA:x})")


show("thunk_box_thick", THUNK_BOX_THICK, SYM["thunk_box_thick"])
show("thunk_ensure_frame_buf", THUNK_ENSURE_FRAME_BUF, SYM["thunk_ensure_frame_buf"])
show("thunk_title_textnudge", THUNK_TITLE_TEXTNUDGE, SYM["thunk_title_textnudge"])
show("thunk_btntext_nudge", THUNK_BTNTEXT_NUDGE, SYM["thunk_btntext_nudge"])
