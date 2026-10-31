"""Assemble the type-8 OptionList sprite-ratio thunks + thunk_tutwin_backdrop v2.

Group popup_optionlist8_spritezoom (2026-07-31, stack-picker fix):
  thunk_ol8_calc_ratio  @0xF560  cut 0x610AE1 (12B) OptionList_calculate_dimensions
  thunk_ol8_draw_ratio  @0xF590  cut 0x610DF1 (12B) OptionList_draw_item main pair
  thunk_ol8_box_ratio   @0xF5C0  cut 0x610FC7 (11B) OptionList_draw_item selection box
  thunk_ol8_gap         @0xF5F0  cut 0x610C84 ( 8B) OptionList_draw_item gap/stride
  thunk_ol8_textx       @0xF610  cut 0x610D98 ( 6B) OptionList_draw_item label x
  thunk_ol8_rowwidth    @0x4550  cut 0x610B82 ( 5B) OptionList_calculate_dimensions
                        row width [+0x64] (law optionlist8_row_width: grown by
                        the label-x shift textx adds, so the longest label's
                        clip edge row_x + [+0x64] moves with it, 2026-10-11)
  thunk_ol8_selbottom   @0xF9A0  cut 0x610FBC (11B) OptionList_draw_item ring bottom
                        (law optionlist8_ring_bottom: the ring's -3 is the NATIVE
                        row gap; scaled gapS - 3 rows spill into the next cell and
                        its back-erase wipes the bottom stroke.  Pushes onto the
                        caller's Buffer_box arg stack -> pop-ret-to-global +
                        jmp-[g_ol8_ret] pattern, scratch g_ol8_ret @0xF9E0.)

All are ports of scaling_laws.optionlist8_* (ratio (num*g, den*16); gap/pad the
popup_scale_floor imul;sar idiom).  Each gates on g_popup_scale_num <= 16 ->
byte-identical register outcomes (native no-op).

thunk_tutwin_backdrop v2 @0xA920 (group popups_tutwin, IN-PLACE): the ornate
arm (params == 0x6846B0, g > 16) now applies to ANY dest — devfill synth +
ornate 9-slice band-map over via thunk_box_thick_hollow — with the TutWin-only
synthetic title stash still gated on ecx == TutWin+0x444.  v1 sent every
non-TutWin ornate popup (the type-2/6 in-game family: unit-stack picker etc.)
down the plain devfill path, which zeroes the def's border sprites -> the
metal frame vanished at g > 16.

Run:  py assemble_optlist8.py   -> prints the yaml byte strings.
Parity: tests/test_optlist8_asm_parity.py emulates raw() bytes (sentinels
left in place; the yaml resolves them at apply time).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000

# sentinel imm32 -> patches.yaml placeholder (spaced 0x10 so 4-byte windows
# never alias; all inside one 0xDEADB000 page for the parity tests)
SENT = {
    0xDEADBE00: "{abs32:g_popup_scale_num}",
    0xDEADBE10: "{abs32:g_tw_dest}",
    0xDEADBE20: "{abs32:g_title_left}",
    0xDEADBE30: "{abs32:g_title_right}",
    0xDEADBE40: "{abs32:thunk_box_thick_devfill}",   # tail push (abs)
    0xDEADBEB0: "{abs32:Buffer_box_sprite}",         # keyint native tail push (abs)
    0xDEADBEE0: "{abs32:g_ol8_ret}",                 # selbottom ret-addr scratch
}
# rel32 call targets (sentinel VAs; emit() rewrites the E8 imm by target)
CALL_SENT = {
    0xDEADBE40: "{rel32:thunk_box_thick_devfill}",
    0xDEADBE50: "{rel32:thunk_box_thick_hollow}",
    0xDEADBE60: "{rel32:thunk_clamp_frame_rect}",
    0xDEADBE70: "{rel32:thunk_ensure_frame_buf}",
    0xDEADBE80: "{rel32:Buffer_resize}",
    0xDEADBE90: "{rel32:Buffer_set_clip}",
    0xDEADBEA0: "{rel32:Buffer_fill_3}",
    0xDEADBEB0: "{rel32:Buffer_box_sprite}",
    0xDEADBEC0: "{rel32:thunk_fe_bandmap}",
    0xDEADBED0: "{rel32:thunk_hollow_keyint}",
}

G = 0xDEADBE00
TW_DEST = 0xDEADBE10
TITLE_L = 0xDEADBE20
TITLE_R = 0xDEADBE30
DEVFILL = 0xDEADBE40
HOLLOW = 0xDEADBE50
CLAMP = 0xDEADBE60
ENSURE = 0xDEADBE70
RESIZE = 0xDEADBE80
SETCLIP = 0xDEADBE90
FILL3 = 0xDEADBEA0
BOXSPRITE = 0xDEADBEB0
BANDMAP = 0xDEADBEC0
KEYINT = 0xDEADBED0
OL8RET = 0xDEADBEE0

TUTWIN_BUF = 0x8C72AC        # TutWin+0x444
TUTWIN_W = 0x8C732C          # TutWin+0x4C4 (window W)
ORNATE = 0x6846B0            # the type-2/6 ornate frame def (&PTR_DAT_006846b0)

CALC_RATIO_OFF = 0xF560
DRAW_RATIO_OFF = 0xF590
BOX_RATIO_OFF = 0xF5C0
GAP_OFF = 0xF5F0
TEXTX_OFF = 0xF610
ROWWIDTH_OFF = 0x4550
TUTWIN_OFF = 0xA920


def asm_calc_ratio():
    # cut @0x610AE1 (12B): mov ecx,[esi+0x1c]; mov eax,[ebx+0x18];
    #                      imul eax,ecx; mov edi,[esi+0x20]
    # resume 0x610AED: cdq; idiv edi — then the H block @0x610AFC reuses
    # ecx/edi, so ONE scaling covers both axes.  eax was dead on entry.
    return f"""
        mov ecx, dword ptr [esi + 0x1c]
        mov edi, dword ptr [esi + 0x20]
        cmp dword ptr [{G}], 0x10
        jle L1
        imul ecx, dword ptr [{G}]
        shl edi, 4
    L1:
        mov eax, dword ptr [ebx + 0x18]
        imul eax, ecx
        ret
    """


def asm_draw_ratio():
    # cut @0x610DF1 (12B): mov ebp,[esi+0x1c]; mov eax,[eax+0x1c];
    #                      imul eax,ebp; mov ecx,[esi+0x20]
    # resume 0x610DFD: cdq; idiv ecx.  ebp/ecx stay live through the sprite
    # draw (Sprite_draw_2 args / SCALE_NUM_G/DEN_G) — scaling here scales
    # them all.  edx dead (cdq overwrites); eax = sprite ptr on entry.
    return f"""
        mov ebp, dword ptr [esi + 0x1c]
        mov ecx, dword ptr [esi + 0x20]
        cmp dword ptr [{G}], 0x10
        jle L1
        imul ebp, dword ptr [{G}]
        shl ecx, 4
    L1:
        mov eax, dword ptr [eax + 0x1c]
        imul eax, ebp
        ret
    """


def asm_box_ratio():
    # cut @0x610FC7 (11B): mov eax,[ecx+0x18]; imul eax,[esi+0x1c]; cdq;
    #                      idiv dword ptr [esi+0x20]
    # resume 0x610FD2 (mov edx,[ebp+4] — edx dead).  ecx = sprite ptr.
    return f"""
        mov eax, dword ptr [ecx + 0x18]
        imul eax, dword ptr [esi + 0x1c]
        cmp dword ptr [{G}], 0x10
        jle Lnat
        imul eax, dword ptr [{G}]
        mov edx, dword ptr [esi + 0x20]
        shl edx, 4
        push edx
        cdq
        idiv dword ptr [esp]
        pop edx
        ret
    Lnat:
        cdq
        idiv dword ptr [esi + 0x20]
        ret
    """


def asm_gap():
    # cut @0x610C84 (8B): mov edx,[ecx+0x44]; mov ebx,[ecx+0x64]; add ebx,edx
    # resume 0x610C8C: sar edx,1 (row-y offset = gap_scaled >> 1); ebx becomes
    # the column stride rowW + gap_scaled.  eax (col index) untouched.
    return f"""
        mov edx, dword ptr [ecx + 0x44]
        cmp dword ptr [{G}], 0x10
        jle L1
        imul edx, dword ptr [{G}]
        sar edx, 4
    L1:
        mov ebx, dword ptr [ecx + 0x64]
        add ebx, edx
        ret
    """


def asm_textx():
    # cut @0x610D98 (6B): lea ecx,[edx+ebx+4]; test esi,esi
    # The jne @0x610DA2 consumes the test's flags across our RET — test is
    # the LAST flag-writer here.  edx (=[esi+0x54]) dead after the lea;
    # eax ([esi] vtbl base) live — untouched.
    return f"""
        lea ecx, [edx + ebx]
        mov edx, dword ptr [{G}]
        cmp edx, 0x10
        jg L2
        mov edx, 4
        jmp L3
    L2:
        sar edx, 2
    L3:
        add ecx, edx
        test esi, esi
        ret
    """


def asm_rowwidth():
    # cut @0x610B82 (5B): add edx,ebx; mov [eax+0x64],edx
    # (edx = maxText [esi+0x5c] + 2*[D+0x40], ebx = sprite column [esi+0x54],
    # eax = D).  Resume 0x610B87 reloads eax/edx/ecx; ebx is never read again
    # before its pop; the next flag consumer (jge 0x610B98) follows its own
    # cmp -> ecx and EFLAGS are free.  No branch lands in 0x610B83..0x610B86.
    # [+0x64] += optionlist8_label_pad(g) - 4 = (g>>2) - 4 at g > 16, the
    # exact shift thunk_ol8_textx gives the label's left edge.
    return f"""
        add edx, ebx
        mov ecx, dword ptr [{G}]
        cmp ecx, 0x10
        jle L1
        sar ecx, 2
        lea edx, [edx + ecx - 4]
    L1:
        mov dword ptr [eax + 0x64], edx
        ret
    """


def asm_selbottom():
    # cut @0x610FBC (11B): mov edx,[edx+0x68]; inc edi; push eax; push eax;
    #                      lea eax,[edx+edi-3]; push eax
    # resume 0x610FC7 (the selbox_ratio cut's call).  Entry: eax=ring color,
    # edx=dialog adjustor ptr, edi=recentered sprite y, ebx=x, ecx=elem
    # sprite ptr (LIVE for the next cut — untouched), esi=list obj (LIVE).
    # This thunk pushes 3 dwords onto the CALLER's Buffer_box arg stack, so
    # the E8 ret addr is parked in g_ol8_ret (single synchronous UI draw,
    # non-reentrant) and consumed by the tail jmp — the bare-RET contract
    # (feedback-thunk-call-vs-detour) is honoured with the stack net-3.
    # (3*g)>>4 == 3 at g=16 -> bit-identical native replay, no branch.
    # Exit regs match the original byte-for-byte: eax=bottom, edx=pitch,
    # edi=y+1; flags were dead at the site (inc clobbered them natively).
    return f"""
        pop dword ptr [{OL8RET}]
        mov edx, dword ptr [edx + 0x68]
        inc edi
        push eax
        push eax
        mov eax, dword ptr [{G}]
        lea eax, [eax + eax*2]
        sar eax, 4
        neg eax
        add eax, edx
        add eax, edi
        push eax
        jmp dword ptr [{OL8RET}]
    """


def asm_childx():
    # cut @0x602B88 (7B): cmp dword ptr [esi+0x2350], -1
    # resume 0x602B8F: je 0x602c1b (ZF from our trailing cmp flows through the
    # RET).  Entry: esi=popup; eax DEAD on both onward paths (overwritten
    # immediately at 0x602ba1/0x602bc1 and 0x602c1b); edx PRESERVED via push
    # (the fallthrough tail past 0x602bcd is not fully audited); ecx/ebx/edi
    # untouched.  The just-stored dialog child x sits at caller [esp+0x10]
    # = [esp+0x18] after ret-addr + our push.  The 0x602b82 jmp lands on the
    # cut's FIRST byte (branch-target hazard audited: no targets inside).
    # Law ornate_dialog_child_x: g>16 & ornate 2/6 -> x += ps3-3, turning the
    # engine's s(16)+3 into s(16)+ps3 == fl(19g/16) EXACTLY (16g>>4 = g).
    # Identity at g<=16 and wherever ps3==3 (g<=21).
    return f"""
        push edx
        mov eax, dword ptr [{G}]
        cmp eax, 0x10
        jle L2
        mov edx, dword ptr [esi + 0x30ac]
        sub edx, 20000
        cmp edx, 10000
        jb L1
        sub edx, 40000
        cmp edx, 10000
        jae L2
    L1:
        lea edx, [eax + eax*2]
        sar edx, 4
        sub edx, 3
        add dword ptr [esp + 0x18], edx
    L2:
        pop edx
        cmp dword ptr [esi + 0x2350], -1
        ret
    """


def asm_tutwin_v3():
    # v2 (2026-07-31): ornate arm for ANY dest; TutWin keeps its synthetic
    # title stash.  Same entry contract as Buffer_box_sprite (ecx=destBuf,
    # [esp+4]=&rect, [esp+8]=&params, RET 8); tail-jmp devfill otherwise.
    # v3 (2026-08-01): the over-draw goes through thunk_hollow_keyint instead
    # of thunk_box_thick_hollow — identical except the small render's FILL
    # region is erased back to key 9 before the band-map blit, so devfill's
    # device-density interior (STEP2 tile + STEP3 P-stripe remap) survives
    # instead of being overpainted by NN-duplicated native stripes (the
    # 1600x1200 color banding; 2/3-blocks at 4K).  Edge masks intact.
    # 2026-09-18 (title_grow_delta == 0): the stash's delta term is `sar eax,31`
    # (== 0, same length) -- the pf-align chain dropped its matching delta.
    return f"""
        cmp dword ptr [esp + 8], {ORNATE}
        jne Ltail
        mov eax, dword ptr [{G}]
        cmp eax, 0x10
        jle Ltail
        mov dword ptr [{TW_DEST}], ecx
        cmp ecx, {TUTWIN_BUF}
        jne Lskip
        imul edx, eax, 0x1A
        add edx, 0xF
        shr edx, 5
        sub eax, 0x10
        sar eax, 31
        add edx, eax
        mov dword ptr [{TITLE_L}], edx
        mov eax, dword ptr [{TUTWIN_W}]
        sub eax, edx
        mov dword ptr [{TITLE_R}], eax
    Lskip:
        push dword ptr [esp + 8]
        push dword ptr [esp + 8]
        call {DEVFILL}
        mov ecx, dword ptr [{TW_DEST}]
        push dword ptr [esp + 8]
        push dword ptr [esp + 8]
        call {KEYINT}
        ret 8
    Ltail:
        push {DEVFILL}
        ret
    """


def asm_hollow_keyint():
    # Clone of thunk_box_thick_hollow (Delta=0 flavor, byte-verified against
    # the live cave entry 2026-08-01) + ONE inserted step: after the small
    # render (def fill + edge Buffer_tile_mask passes intact), erase the
    # def's FILL REGION back to key 9 — rect {0,0,smallW,smallH} inset
    # per-edge by that edge sprite's cross dim, null slices = 0, degenerate
    # spans skipped (law scaling_laws.hollow_interior_erase, which mirrors
    # Buffer_box_sprite's own final Buffer_tile inset block @0x5e2dd3).
    # The keyed band-map blit then skips the interior, so the underlying
    # devfill device-density stripes show through, and the erase boundary
    # meets the border bands exactly where the vanilla fill met them (same
    # blit, same native region — no parallel band formula).
    # Frame: sub esp,0x30 (hollow used 0x20) so the erase rect at
    # [ebp-0x30..-0x24] sits ABOVE the saved ebx/esi/edi (frame-aliasing
    # gotcha).  Contract: thiscall(ecx=dest, rect, params) RET 8; g<=16 ->
    # native Buffer_box_sprite tail (exact no-op).
    return f"""
        cmp dword ptr [{G}], 0x10
        jg Lgo
        push {BOXSPRITE}
        ret
    Lgo:
        push ebp
        mov ebp, esp
        sub esp, 0x30
        push ebx
        push esi
        push edi
        mov dword ptr [ebp - 4], ecx
        mov eax, dword ptr [ebp + 0xc]
        mov dword ptr [ebp - 8], eax
        mov esi, dword ptr [ebp + 8]
        xor ebx, ebx
        mov ecx, dword ptr [ebp - 4]
        call {CLAMP}
        mov eax, dword ptr [esi]
        sub eax, ebx
        mov dword ptr [ebp - 0xc], eax
        mov eax, dword ptr [esi + 4]
        sub eax, ebx
        mov dword ptr [ebp - 0x10], eax
        xor ecx, ecx
        mov dword ptr [ebp - 0x20], ecx
        mov dword ptr [ebp - 0x1c], ecx
        mov eax, dword ptr [esi + 8]
        sub eax, dword ptr [esi]
        add eax, ebx
        add eax, ebx
        shl eax, 4
        xor edx, edx
        div dword ptr [{G}]
        mov dword ptr [ebp - 0x18], eax
        mov eax, dword ptr [esi + 0xc]
        sub eax, dword ptr [esi + 4]
        add eax, ebx
        add eax, ebx
        shl eax, 4
        xor edx, edx
        div dword ptr [{G}]
        mov dword ptr [ebp - 0x14], eax
        call {ENSURE}
        mov edi, eax
        push dword ptr [ebp - 0x14]
        push dword ptr [ebp - 0x18]
        mov ecx, edi
        call {RESIZE}
        lea eax, [ebp - 0x20]
        push eax
        mov ecx, edi
        call {SETCLIP}
        push 9
        lea eax, [ebp - 0x20]
        push eax
        mov ecx, edi
        call {FILL3}
        push dword ptr [ebp - 8]
        lea eax, [ebp - 0x20]
        push eax
        mov ecx, edi
        call {BOXSPRITE}
        mov edx, dword ptr [ebp - 8]
        mov eax, dword ptr [edx + 0x20]
        test eax, eax
        je Lblit
        cmp edx, {ORNATE}
        jne Lgen
        mov dword ptr [ebp - 0x30], 8
        mov dword ptr [ebp - 0x2c], 8
        mov ecx, dword ptr [ebp - 0x18]
        sub ecx, 9
        mov dword ptr [ebp - 0x28], ecx
        mov ecx, dword ptr [ebp - 0x14]
        sub ecx, 6
        mov dword ptr [ebp - 0x24], ecx
        jmp Lchk
    Lgen:
        xor ecx, ecx
        mov eax, dword ptr [edx + 0x18]
        test eax, eax
        je LK1
        mov ecx, dword ptr [eax + 0x18]
    LK1:
        mov dword ptr [ebp - 0x30], ecx
        xor ecx, ecx
        mov eax, dword ptr [edx + 0x10]
        test eax, eax
        je LK2
        mov ecx, dword ptr [eax + 0x1c]
    LK2:
        mov dword ptr [ebp - 0x2c], ecx
        mov ecx, dword ptr [ebp - 0x18]
        mov eax, dword ptr [edx + 0x1c]
        test eax, eax
        je LK3
        sub ecx, dword ptr [eax + 0x18]
    LK3:
        mov dword ptr [ebp - 0x28], ecx
        mov ecx, dword ptr [ebp - 0x14]
        mov eax, dword ptr [edx + 0x14]
        test eax, eax
        je LK4
        sub ecx, dword ptr [eax + 0x1c]
    LK4:
        mov dword ptr [ebp - 0x24], ecx
    Lchk:
        mov eax, dword ptr [ebp - 0x28]
        cmp eax, dword ptr [ebp - 0x30]
        jle Lblit
        mov eax, dword ptr [ebp - 0x24]
        cmp eax, dword ptr [ebp - 0x2c]
        jle Lblit
        push 9
        lea eax, [ebp - 0x30]
        push eax
        mov ecx, edi
        call {FILL3}
    Lblit:
        push 0x10
        push dword ptr [{G}]
        push dword ptr [ebp - 0x10]
        push dword ptr [ebp - 0xc]
        push 9
        push dword ptr [ebp - 4]
        mov ecx, edi
        call {BANDMAP}
        pop edi
        pop esi
        pop ebx
        mov esp, ebp
        pop ebp
        ret 8
    """


KEYINT_OFF = 0xF630
SELBOTTOM_OFF = 0xF9A0
CHILDX_OFF = 0xFB90

THUNKS = [
    ("thunk_orn_childx", CHILDX_OFF, asm_childx),
    ("thunk_ol8_calc_ratio", CALC_RATIO_OFF, asm_calc_ratio),
    ("thunk_ol8_draw_ratio", DRAW_RATIO_OFF, asm_draw_ratio),
    ("thunk_ol8_box_ratio", BOX_RATIO_OFF, asm_box_ratio),
    ("thunk_ol8_gap", GAP_OFF, asm_gap),
    ("thunk_ol8_textx", TEXTX_OFF, asm_textx),
    ("thunk_ol8_rowwidth", ROWWIDTH_OFF, asm_rowwidth),
    ("thunk_ol8_selbottom", SELBOTTOM_OFF, asm_selbottom),
    ("thunk_hollow_keyint", KEYINT_OFF, asm_hollow_keyint),
    ("thunk_tutwin_backdrop", TUTWIN_OFF, asm_tutwin_v3),
]


def raw(off: int, asm: str) -> bytes:
    """Assembled bytes with sentinel imm32s left in place (parity tests map a
    page at 0xDEADB000 instead of resolving the placeholders)."""
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(asm, addr=PCAVE2 + off)
    return bytes(code)


def emit(name: str, off: int, asm: str) -> None:
    blob = raw(off, asm)
    out, i = [], 0
    while i < len(blob):
        # E8 rel32 to a sentinel target -> {rel32:...}
        if blob[i] == 0xE8 and i + 5 <= len(blob):
            tgt = (PCAVE2 + off + i + 5 +
                   int.from_bytes(blob[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in CALL_SENT:
                out.append("E8")
                out.append(CALL_SENT[tgt])
                i += 5
                continue
        v = int.from_bytes(blob[i:i + 4], "little") if i + 4 <= len(blob) else None
        if v in SENT:
            out.append(SENT[v])
            i += 4
            continue
        out.append(f"{blob[i]:02X}")
        i += 1
    print(f"{name}  {len(blob)} bytes @ pcave2+{off:#x} (VA {PCAVE2 + off:#x})"
          f" .. end {off + len(blob):#x}")
    print('        bytes: "' + " ".join(out) + '"')
    print()


if __name__ == "__main__":
    for name, off, fn in THUNKS:
        emit(name, off, fn())
