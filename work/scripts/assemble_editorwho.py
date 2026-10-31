#!/usr/bin/env python
# Keystone assembler for the EDITORWHO picker fix (2026-08-14):
#   * thunk_q16_fill_width @ pcave2+0x11000 -- CURRENT = v6 (2026-09-29, content-anchored
#     width, see the thunk below); the v4 notes that follow are history.
#     v4 (RELOCATED from 0x4420 — v3 was
#     139B with 5B slack to g_rm_force@0x44B0; census: the ONLY consumer is the
#     E8 {rel32:} @0x60d299, so the symbol move retargets it).  v4 = v3 + the
#     pds gate: when the fieldpads stash matches this popup's box_w BUT
#     PopupDialogState [0x6A721C] == 6 (the list family), take the box arm
#     (box_w - 2x) instead of the field mirror — the list family's rows ARE
#     the content area (x == Lmargin), the mirror degenerates to full-flush
#     and overran the right inner frame + rail (SELECT A FACTION, 4K: mirror
#     1502 vs lawful 1492; box arm right edge = box_w - x = vanilla*g/16
#     exactly).  Stash still consumed (boxw cleared) on BOTH paths — v3
#     semantics.  Law scaling_laws.q16_fill_width; vectors
#     tests/test_scaling_editorwho.py; ground truth
#     frida_scenedit_popupdiag.log (4K + native runs 2026-08-14).
#   * thunk_s54_restripe @ pcave2+0x13BA0 (v2 2026-09-12: + the report row/title-band pair
#     0xC2/0x41, mate-keyed the same way; relocated from 0x110A0) — wraps devfill's fe_pair_remap
#     call (devfill v2's {rel32:thunk_fe_pair_remap} retargeted to this):
#     calls fe first (unchanged behavior for every existing family), then
#     restripes the pds=6 list-family backdrop pair 0x54/0x41 that
#     fe deliberately excludes (0x41 partners C4/C6/C5 + solid fills).
#     MATE-KEYED BOTH WAYS (feedback-dither-pair-ambiguity): over <=8 scanned
#     rows BOTH members must exceed w/2 (1px row-alternating hatch ~4w each;
#     solid 0x54 art or solid 0x41 pre-fill never fires).  When keyed, BOTH
#     members rewrite to the row colour (the rect is the freshly tiled mask —
#     pure pair by construction; the title band / rows / buttons draw later
#     on top).  Reuses fe's just-computed clamped walk bounds g_rm_xend/yend
#     (same call, same rect).  Laws scaling_laws.s54_hatch_keyed /
#     s54_row_color (P=(g+4)>>3, hN=(P+1)>>1, colored member on top).
#     CALL-helper, same contract as fe: preserves ebx/esi/edi/ebp, clobbers
#     eax/ecx/edx.  g<=16 -> ret after fe (devfill only calls under g>16).
# Regenerate if any referenced cave offset moves.
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PCAVE2 = 0xA0C000
PDS = 0x006A721C          # engine PopupDialogState (thinker) — fixed VA

SENT = {
    0x71111111: "{abs32:g_popup_scale_num}",
    0x72111111: "{abs32:g_boxw_num}",
    0x73111111: "{abs32:g_field_L}",
    0x73222222: "{abs32:g_field_R}",
    0x73333333: "{abs32:g_field_boxw}",
    0x74111111: "{abs32:GraphicWin_init}",
    0x7A111111: "{abs32:g_fe_dst}",
    0x7A222222: "{abs32:g_fe_x}",
    0x7A333333: "{abs32:g_fe_y}",
    0x7A444444: "{abs32:g_fe_w}",
    0x7A555555: "{abs32:g_fe_h}",
    0x7B111111: "{abs32:g_rm_xend}",
    0x7B222222: "{abs32:g_rm_yend}",
}
CALL_SENT = {
    0x75333333: "{rel32:thunk_fe_pair_remap}",
}

THUNKS = []
def thunk(name, offset, asm):
    THUNKS.append((name, offset, asm))

# ============ thunk_q16_fill_width v6 @ 0x11000 ============
# esi = the t16 attach self = popup+0x2C44; D = esi+0x12c.  Entered by E8
# @0x60d299 (through t_dp_q16gate) in place of `call GraphicWin_init`; args
# x,y,w,h at [esp+4..0x10]; tail re-pushes GraphicWin_init and RETs into it
# (native call contract, v2/v3 idiom).  Clobbers eax only (dead at the site).
# v6 (2026-09-29, law scaling_laws.q16_fill_width v6): W = box_w - right margin
# - x = [popup+0x30BC] - [popup+0x30F4] - x, the span the OK / CANCEL bar ends
# on (BasePop_exec_3 0x602C51 anchors it at -[+0x30F4]).  Replaces max(w*g/16,
# arm2): w is contaminated by the device row gap on the attach's calc pass (rows
# 5 px short of the OK bar at 4K), the field mirror overshot the bar on text
# popups, the box arm assumed symmetric margins.  The fieldpads stash and
# g_boxw_num are no longer read.  64 B in the 152 B slot (the rest stays zero).
# v5 (2026-09-28): the count gate is count >= 1 (a one-row list widens too).
thunk("thunk_q16_fill_width", 0x11000, """
    cmp     dword ptr [0x71111111], 0x10
    jle     native
    mov     eax, [esi+0x1f8]
    cmp     eax, 1
    jl      native
    mov     eax, [esi+0x478]
    sub     eax, [esi+0x4b0]
    sub     eax, [esp+4]
    cmp     eax, [esp+0xC]
    jle     native
    mov     [esp+0xC], eax
    mov     [esi+0x188], eax
    mov     [esi+0x190], eax
native:
    push    0x74111111
    ret
""")

# ============ thunk_s54_restripe v3 @ 0x13BA0 ============
# v3 (2026-10-17, fix 7 -- law scaling_laws.force_prescan_bounds): the prescan is clamped to the dest
# BUFFER exactly like fe v9's (v2 read min(h,8) rows x w columns from max(x,0)/max(y,0) unchecked: a
# half-open rect staged inclusive or a frame near / below the buffer bottom read past the plane).
# Byte-identical keying for every in-bounds frame; the dead `mov eax,[g]` + nop before the period
# load are gone.  379B, ends 0x13D1B < thunk_hud_baseargs 0x13D20.
# v2 (2026-09-12, HQ report rows/title band -- sweep items F/G; laws scaling_laws.HATCH_MATE_PAIRS /
# hatch_pair_for / hatch_row_color): a SECOND mate-keyed hatch pair 0xC2/0x41 (palette 194 (13,28,48)
# over black -- the report pages' BASE STATUS entry boxes, list rows and title band, and the Design
# Workshop's hovered slot d550), which devfill STEP2 tiles 1:1 at every resolution.  0xC2 is ALSO the
# top member of the scrollbar-arrow face dither 0xC2/0xC5 (thunk_btn_stripes' own pass), so it stays
# out of fe's content-keyed families: the mate rule (both members > w/2 over <=8 rows) is what keeps a
# C2/C5 face -- no 0x41 at all -- and any solid 0xC2 surface untouched.  The prescan counts 0x54 (ebx),
# 0x41 (ebp) and 0xC2 ([esp] local); the mate must dominate for either pair, then 0x54 is tried first
# (a freshly tiled mask is pure pair -- at most one top member can dominate).  The keyed top byte rides
# in [esp+4] through the walk; the walk is v1's with `cmp al, top` in place of `cmp al, 0x54`.
# RELOCATED 0x110A0 -> 0x13BA0 (v1 314B had 38B slack to thunk_rail_gate @0x11200; cave_map --fit:
# 0x13B94..0x14000 free after thunk_popup_fieldpads).  Sole consumer = devfill v2's retargeted
# {rel32:thunk_s54_restripe} (symbol-resolved), so the move is the symbol offset.
thunk("thunk_s54_restripe", 0x13BA0, """
    call    0x75333333
    cmp     dword ptr [0x71111111], 0x10
    jle     ret0
    push    ebx
    push    esi
    push    edi
    push    ebp
    sub     esp, 8
    mov     dword ptr [esp], 0
; ---- prescan: <=8 rows of the dest rect, count 0x54 (ebx), 0x41 (ebp), 0xC2 ([esp]) ----
; v3: the scanned block is clamped to the BUFFER exactly as fe's (law scaling_laws.force_prescan_bounds):
;     columns [x0, min(x0+w, W)), rows [y0, min(y0+min(h,8), H)); empty -> out.  Clip NOT applied.
    mov     ebx, [0x7A111111]
    test    ebx, ebx
    jz      out
    mov     esi, [ebx+0x54]
    test    esi, esi
    jz      out
    mov     edx, [ebx+0x4a8]
    mov     ecx, [0x7A333333]
    test    ecx, ecx
    jge     y0ok
    xor     ecx, ecx
y0ok:
    mov     ebp, [ebx+0x84]
    neg     ebp
    sub     ebp, ecx
    imul    ecx, edx
    add     esi, ecx
    mov     eax, [0x7A222222]
    test    eax, eax
    jge     x0ok
    xor     eax, eax
x0ok:
    add     esi, eax
    neg     eax
    add     eax, [ebx+0x80]
    mov     edi, [0x7A444444]
    cmp     edi, eax
    jle     wok
    mov     edi, eax
wok:
    test    edi, edi
    jle     out
    mov     ecx, [0x7A555555]
    cmp     ecx, 8
    jle     hs
    mov     ecx, 8
hs:
    cmp     ecx, ebp
    jle     hs2
    mov     ecx, ebp
hs2:
    test    ecx, ecx
    jle     out
    xor     ebx, ebx
    xor     ebp, ebp
prow:
    dec     ecx
    js      pdone
    push    ecx
    push    esi
    mov     ecx, edi
ppix:
    dec     ecx
    js      prowd
    mov     al, [esi+ecx]
    cmp     al, 0x54
    jne     p41
    inc     ebx
    jmp     ppix
p41:
    cmp     al, 0x41
    jne     pc2
    inc     ebp
    jmp     ppix
pc2:
    cmp     al, 0xC2
    jne     ppix
    inc     dword ptr [esp+8]
    jmp     ppix
prowd:
    pop     esi
    pop     ecx
    add     esi, edx
    jmp     prow
pdone:
    mov     eax, edi
    shr     eax, 1
    cmp     ebp, eax
    jle     out
    mov     byte ptr [esp+4], 0x54
    cmp     ebx, eax
    jg      keyed
    mov     byte ptr [esp+4], 0xC2
    cmp     dword ptr [esp], eax
    jle     out
keyed:
; ---- keyed: walk the same clamped bounds fe just computed (same call/rect); top byte in [esp+4] ----
    mov     esi, [0x7A111111]
    mov eax, dword ptr [0x66879c]
    mov     ebx, eax
    mov     edi, [0x7A333333]
    test    edi, edi
    jge     yc
    xor     edi, edi
yc:
    cmp     edi, [esi+0x24]
    jge     rowl
    mov     edi, [esi+0x24]
rowl:
    cmp     edi, [0x7B222222]
    jge     out
    mov     eax, edi
    xor     edx, edx
    div     ebx
    lea     ecx, [ebx+1]
    shr     ecx, 1
    cmp     edx, ecx
    mov     dl, byte ptr [esp+4]
    jl      coldone
    mov     dl, 0x41
coldone:
    mov     eax, [esi+0x4a8]
    imul    eax, edi
    add     eax, [esi+0x54]
    mov     ecx, [0x7A222222]
    test    ecx, ecx
    jge     xc
    xor     ecx, ecx
xc:
    cmp     ecx, [esi+0x20]
    jge     xs
    mov     ecx, [esi+0x20]
xs:
    lea     ebp, [eax+ecx]
xlp:
    cmp     ecx, [0x7B111111]
    jge     nrow
    mov     al, [ebp]
    cmp     al, byte ptr [esp+4]
    je      wr
    cmp     al, 0x41
    jne     sk
wr:
    mov     [ebp], dl
sk:
    inc     ebp
    inc     ecx
    jmp     xlp
nrow:
    inc     edi
    jmp     rowl
out:
    add     esp, 8
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
ret0:
    ret
""")

def assemble(name_want=None):
    """Assemble THUNKS with sentinels left in place; returns {name: (offset, bytes)}."""
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    out = {}
    for name, offset, asm in THUNKS:
        if name_want and name != name_want:
            continue
        src = "\n".join(l.split(";")[0] for l in asm.splitlines())
        enc, _ = ks.asm(src, PCAVE2 + offset)
        out[name] = (offset, bytes(enc))
    return out


ks = Ks(KS_ARCH_X86, KS_MODE_32)
cs = Cs(CS_ARCH_X86, CS_MODE_32)

for name, offset, asm in (THUNKS if __name__ == "__main__" else []):
    va = PCAVE2 + offset
    src = "\n".join(l.split(";")[0] for l in asm.splitlines())
    enc, _ = ks.asm(src, va)
    b = bytes(enc)
    parts = []
    for ins in cs.disasm(b, va):
        raw = ins.bytes
        hexs = " ".join(f"{x:02X}" for x in raw)
        if raw[0] in (0xE8, 0xE9) and len(raw) == 5:
            tgt = (ins.address + 5 + int.from_bytes(raw[1:], "little", signed=True)) & 0xFFFFFFFF
            if tgt in CALL_SENT:
                hexs = f"{raw[0]:02X} " + CALL_SENT[tgt]
        else:
            for sent, ph in SENT.items():
                sb = " ".join(f"{x:02X}" for x in sent.to_bytes(4, "little"))
                if sb in hexs:
                    hexs = hexs.replace(sb, ph)
        parts.append(hexs)
    yaml_bytes = " ".join(parts)
    print(f"==== {name} @ pcave2+0x{offset:X} (VA 0x{va:X}) len={len(b)} ends 0x{offset+len(b):X} ====")
    print(f'  bytes: "{yaml_bytes}"')
    print()
