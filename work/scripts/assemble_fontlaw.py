#!/usr/bin/env python
"""Assembler for the FONT FACE / WEIGHT LAW helpers (group font_face_law, 2026-09-17).

PORT OF: scaling_laws.py :: font_face_law / font_direct_law / font_law_slot_key (the SOURCE OF TRUTH).
Brief: work\\FONT_FACE_WEIGHT_AUDIT.md.  Parity: tests\\test_fontlaw_asm_parity.py (Unicorn).

The engine's find_font pool keys FACE and WEIGHT on the NATIVE size (> 12 px = "Arial Narrow" bold
for variants 0/1; <= 12 px = "Arial" with weight = variant).  Every site that scaled a <= 12 native
by asking the pool for the SCALED size crossed that boundary.  These helpers are the one place the
law lives in x86; every site passes its NATIVE size + variant and gets a Font* back.

  t_font_core(slot, S, style, num, narrow)   cdecl -> eax = slot.  Idempotent per slot: re-Font_init
                     only when (num, key) differ from the slot's +0x28/+0x2C (Font_init frees the old
                     HFONT itself).  name = narrow ? g_hud_font_name_narrow : g_hud_font_name;
                     size = fl(S*num/16) (S at num <= 16).
  t_ffn_at(slot, S, v, num)     cdecl -> slot: the POOL law on a caller-owned slot (narrow = S > 12,
                     style = narrow | font_variant_flags[v]).  Used by sites with their OWN num
                     (Monument plaque) or a private slot (BaseWin base-info name).
  t_fdirect_at(slot, S, style, num) cdecl -> slot: a font vanilla Font_init's DIRECTLY ("Arial",
                     own style): scale the size only (the 0x6E84B4 Arial 14 bold family).
  t_ffn_num(S, v, num)          cdecl -> Font*: the drop-in for find_font(fl(S*num/16), v):
                     num <= 16 -> find_font(S, v); S > 12 && n <= 40 -> find_font(n, v) (the pool
                     is already Narrow+bold there, sizes snapped as before); else the shared slot
                     keyed (S, v) via t_ffn_at (no slot -> find_font(n, v), the old behaviour).
  t_ffn(S, v)                   cdecl = t_ffn_num(S, v, g_popup_scale_num): the find_font drop-in
                     for every popup-g site (tooltips, HQ report fonts, COMMLINK, PrefWin text,
                     MP lobby).
  t_fdirect_a14b()              cdecl -> the shared Arial fl(14g/16) bold slot (BaseWin buttons, the
                     HQ report / kinds console labels).

Cells (zero-init section padding; slot = Font 0x28 + num + key = 0x30):
  g_ffn_keys      15 x u32 (S | v<<8), the shared-slot key table (DATA)
  g_ffn_slots     15 x 0x30 shared slots (one per FONT_LAW_SLOT_KEYS entry, same order)
  g_font_a14b / g_font_bwname / g_font_mon_plaque / g_font_mon_btn / g_font_hof_btn   private slots

Run:  py assemble_fontlaw.py               -> prints the yaml fragments + checks
      py assemble_fontlaw.py --fragments   -> writes work\\patches\\_fragment_fontlaw_*.yaml
      py splice_fontlaw.py                 -> splices them into patches.yaml (idempotent)
"""
from __future__ import annotations

import contextlib
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
with contextlib.redirect_stdout(io.StringIO()):
    import assemble_se as SE  # noqa: E402  (assemble / templatize)
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
SECTION_END = 0x30000

# ---- engine anchors ----------------------------------------------------------
G          = 0x00668740   # g_popup_scale_num
FIND_FONT  = 0x005882F0   # find_font(size, variant) cdecl
FONT_INIT  = 0x00618F40   # Font_init(this; name, size, style) thiscall RET 0xC
NAME_A     = 0x00691B2C   # g_hud_font_name (char**) "Arial"
NAME_N     = 0x00691B30   # g_hud_font_name_narrow (char**) "Arial Narrow"
VFLAGS     = 0x0068F250   # font_variant_flags[4] = {0, 1, 2, 4}

# ---- layout (fixed; after the mon/hof block which ends 0x2D460) -----------------
OFF_KEYS    = 0x2E000
NSLOT       = len(SL.FONT_LAW_SLOT_KEYS)          # 15
STRIDE      = SL.FONT_LAW_SLOT_STRIDE             # 0x30
OFF_SLOTS   = 0x2E040                             # 15 x 0x30 = 0x2D0 -> 0x2E310
OFF_A14B    = 0x2E320
OFF_BWNAME  = 0x2E350
OFF_MONPLQ  = 0x2E380
OFF_MONBTN  = 0x2E3B0
OFF_HOFBTN  = 0x2E3E0
OFF_CODE    = 0x2E420
assert OFF_SLOTS + NSLOT * STRIDE <= OFF_A14B

G_KEYS   = PCAVE2 + OFF_KEYS
G_SLOTS  = PCAVE2 + OFF_SLOTS
G_A14B   = PCAVE2 + OFF_A14B
G_BWNAME = PCAVE2 + OFF_BWNAME
G_MONPLQ = PCAVE2 + OFF_MONPLQ
G_MONBTN = PCAVE2 + OFF_MONBTN
G_HOFBTN = PCAVE2 + OFF_HOFBTN

OFF_SE_FIT  = 0x2E414                             # g_se_fitflag: 1 when the fit loop shrank the font (-> redraw pass)
G_SE_FITFLAG = PCAVE2 + OFF_SE_FIT
assert OFF_HOFBTN + STRIDE <= OFF_SE_FIT and OFF_SE_FIT + 4 <= OFF_CODE
BUFFER_TEXT_WIDTH = 0x005DC790   # Buffer_text_width(this=Buffer; str) thiscall RET 4: the painter's own measure (font +0x52C)

# ---- the SocialWin label-fit (2026-09-17, user shot 1920x1080 175334) --------------------------------
# The engine ellipsises a FlatButton label when Buffer_text_width(label) > (button w - 6).  Vanilla's
# model buttons sit at ZERO slack ("THOUGHT CONTROL" = 140 px in Arial 14 bold vs 146 - 6), so no
# fixed size law survives GDI's per-size advance rounding at every g (fl(14*22/16) = 19 -> 195 px vs
# a 200 - 6 = 194 px button at 1920x1080).  The faithful law = the engine's own base-name fit loop:
# once SocialWin_build has built + painted the 35 buttons, measure every label drawn with the label
# Font (SocialWin fonts[1], Arial 14 bold) and step that Font's size down until every label fits (law
# scaling_laws.se_label_fit), then repaint the measured buttons.
# WHERE: SocialWin_build is MODAL -- its tail `call [vtbl+0xE4]` (Win_set_modal, 0x4B3C4A) only returns
# when the screen closes, so a fit "after the build" (v1/v2, ret-swapped through t_se_enter2) ran after
# the user had LEFT the screen (user shots 1920 183727 + 215036; the after-close repaint of 35 buttons
# of a closed window also broke the SE hotkey).  v3 hooks that call site: E8-entered with ecx = SocialWin
# and the 3 Win_set_modal args on the stack, fits, then tail-jumps into [vtbl+0xE4] (RET 0xC).
SOCIALWIN   = 0x008A6270   # SocialWin singleton
SE_SET_MODAL_SITE = 0x004B3C4A   # SocialWin_build: FF 90 E4 00 00 00 = call [eax+0xE4] (Win_set_modal) -> E8 t_se_labelfit 90
SE_VT_MODAL = 0xE4         # vtbl slot: Win_set_modal(this; a, cb, parent) thiscall RET 0xC
SE_VT_REDRAW = 0xF8        # vtbl slot: GraphicWin_redraw (what the build itself calls after every BaseButton_init)
SE_FONT1    = SOCIALWIN + 0x1EE90   # fonts[1] = the model/faction/OK-row label font (Arial 14 bold)
SE_BTN0, SE_BTN_N, SE_BTN_STRIDE = SOCIALWIN + 0x6020, 35, 0xB4C
SE_LABEL_NATIVE, SE_LABEL_MIN = 14, 8
SE_LABEL_SLACK = 6         # FlatButton_content_draw: avail = (R - L) - 6 (0x6083C6)

CELLS = [   # (name, offset, size) -- BSS: declared by symbol, zero section padding
    ("g_ffn_slots", OFF_SLOTS, NSLOT * STRIDE),
    ("g_font_a14b", OFF_A14B, STRIDE), ("g_font_bwname", OFF_BWNAME, STRIDE),
    ("g_font_mon_plaque", OFF_MONPLQ, STRIDE), ("g_font_mon_btn", OFF_MONBTN, STRIDE),
    ("g_font_hof_btn", OFF_HOFBTN, STRIDE),
    ("g_se_fitflag", OFF_SE_FIT, 4),
]


def keys_bytes() -> bytes:
    return b"".join(struct.pack("<I", s | (v << 8)) for s, v in SL.FONT_LAW_SLOT_KEYS)


DATA = [("g_ffn_keys", OFF_KEYS, keys_bytes)]


# ---- thunks -------------------------------------------------------------------
def asm_font_core() -> str:
    # (slot, S, style, num, narrow) -> eax = slot; ebx/esi/edi preserved
    return f"""
    push    ebp
    mov     ebp, esp
    push    ebx
    push    esi
    push    edi
    mov     esi, dword ptr [ebp+8]
    mov     eax, dword ptr [ebp+0xC]
    mov     ecx, dword ptr [ebp+0x10]
    shl     ecx, 8
    or      eax, ecx
    mov     ecx, dword ptr [ebp+0x18]
    shl     ecx, 16
    or      eax, ecx
    mov     edi, dword ptr [ebp+0x14]
    cmp     dword ptr [esi+0x28], edi
    jne     init
    cmp     dword ptr [esi+0x2C], eax
    je      done
init:
    mov     ebx, eax
    mov     eax, dword ptr [ebp+0xC]
    cmp     edi, 16
    jle     nat
    imul    eax, edi
    sar     eax, 4
nat:
    mov     ecx, dword ptr [{NAME_A:#x}]
    cmp     dword ptr [ebp+0x18], 0
    je      nm
    mov     ecx, dword ptr [{NAME_N:#x}]
nm:
    push    dword ptr [ebp+0x10]
    push    eax
    push    ecx
    mov     ecx, esi
    call    {FONT_INIT:#x}
    mov     dword ptr [esi+0x28], edi
    mov     dword ptr [esi+0x2C], ebx
done:
    mov     eax, esi
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    ret
"""


def asm_ffn_at() -> str:
    # (slot, S, v, num) -> eax = slot: pool face law (narrow = S > 12; style = narrow | vflags[v])
    return f"""
    push    ebp
    mov     ebp, esp
    mov     eax, dword ptr [ebp+0xC]
    xor     edx, edx
    cmp     eax, {SL.FONT_POOL_SMALL_MAX}
    jle     sm
    mov     edx, 1
sm:
    mov     ecx, dword ptr [ebp+0x10]
    mov     ecx, dword ptr [ecx*4+{VFLAGS:#x}]
    or      ecx, edx
    push    edx
    push    dword ptr [ebp+0x14]
    push    ecx
    push    eax
    push    dword ptr [ebp+8]
    call    t_font_core
    add     esp, 20
    pop     ebp
    ret
"""


def asm_fdirect_at() -> str:
    # (slot, S, style, num) -> eax = slot: "Arial" + the caller's own style, size fl(S*num/16)
    return """
    push    0
    push    dword ptr [esp+0x14]
    push    dword ptr [esp+0x14]
    push    dword ptr [esp+0x14]
    push    dword ptr [esp+0x14]
    call    t_font_core
    add     esp, 20
    ret
"""


def asm_ffn_num() -> str:
    # (S, v, num) -> eax = Font*: the find_font(fl(S*num/16), v) drop-in with the face law
    return f"""
    push    ebp
    mov     ebp, esp
    push    ebx
    push    esi
    push    edi
    mov     esi, dword ptr [ebp+8]
    mov     ebx, dword ptr [ebp+0xC]
    mov     ecx, dword ptr [ebp+0x10]
    cmp     ecx, 16
    jle     pool_native
    mov     eax, esi
    imul    eax, ecx
    sar     eax, 4
    cmp     esi, {SL.FONT_POOL_SMALL_MAX}
    jle     slot
    cmp     eax, {SL.FONT_POOL_MAX}
    jg      slot
pool_n:
    push    ebx
    push    eax
    call    {FIND_FONT:#x}
    add     esp, 8
    jmp     done
pool_native:
    push    ebx
    push    esi
    call    {FIND_FONT:#x}
    add     esp, 8
    jmp     done
slot:
    mov     edx, esi
    mov     ecx, ebx
    shl     ecx, 8
    or      edx, ecx
    xor     edi, edi
lk:
    cmp     dword ptr [edi*4+{G_KEYS:#x}], edx
    je      found
    inc     edi
    cmp     edi, {NSLOT}
    jl      lk
    mov     eax, esi
    imul    eax, dword ptr [ebp+0x10]
    sar     eax, 4
    jmp     pool_n
found:
    imul    edi, edi, {STRIDE}
    add     edi, {G_SLOTS:#x}
    push    dword ptr [ebp+0x10]
    push    ebx
    push    esi
    push    edi
    call    t_ffn_at
    add     esp, 16
done:
    pop     edi
    pop     esi
    pop     ebx
    pop     ebp
    ret
"""


def asm_ffn() -> str:
    # (S, v) -> eax = Font*: t_ffn_num(S, v, g_popup_scale_num)
    return f"""
    push    dword ptr [{G:#x}]
    push    dword ptr [esp+0xC]
    push    dword ptr [esp+0xC]
    call    t_ffn_num
    add     esp, 12
    ret
"""


def asm_fdirect_a14b() -> str:
    # () -> eax = the shared Arial fl(14g/16) bold slot (the 0x6E84B4 label-font family)
    return f"""
    push    dword ptr [{G:#x}]
    push    1
    push    14
    push    {G_A14B:#x}
    call    t_fdirect_at
    add     esp, 16
    ret
"""


def asm_se_labelfit() -> str:
    # E8-entered at SE_SET_MODAL_SITE in place of `call [eax+0xE4]`: ecx = SocialWin (kept), eax = its
    # vtbl (recomputed), stack = [ret][0][pop_wait][MainWin] = Win_set_modal's frame, left untouched.
    # ebx/esi/edi callee-saved for the build.  g <= 16 -> straight into the modal (vanilla fits by
    # construction).  The measure is the PAINTER'S OWN: Buffer_text_width on the button canvas (+0x444;
    # reads its font +0x52C == +0x970).  After a shrink every measured button is repainted through
    # vtbl+0xF8, exactly as the build repaints each button after its BaseButton_init (0x4B346E).
    return f"""
    push    ecx
    cmp     dword ptr [{G:#x}], 16
    jle     done
    push    ebx
    push    esi
    push    edi
    mov     dword ptr [{G_SE_FITFLAG:#x}], 0
    mov     edi, {SE_LABEL_NATIVE}
    imul    edi, dword ptr [{G:#x}]
    sar     edi, 4
pass_:
    mov     esi, {SE_BTN0:#x}
    mov     ebx, {SE_BTN_N}
btn:
    cmp     dword ptr [esi+0x970], {SE_FONT1:#x}
    jne     next
    mov     eax, dword ptr [esi+0xA7C]
    test    eax, eax
    je      next
    push    eax
    lea     ecx, [esi+0x444]
    call    {BUFFER_TEXT_WIDTH:#x}
    mov     ecx, dword ptr [esi+0x47C]
    sub     ecx, dword ptr [esi+0x474]
    sub     ecx, {SE_LABEL_SLACK}
    cmp     eax, ecx
    jg      shrink
next:
    add     esi, {SE_BTN_STRIDE}
    dec     ebx
    jne     btn
    jmp     fitted
shrink:
    cmp     edi, {SE_LABEL_MIN}
    jle     fitted
    dec     edi
    mov     dword ptr [{G_SE_FITFLAG:#x}], 1
    push    1
    push    edi
    push    dword ptr [{NAME_A:#x}]
    mov     ecx, {SE_FONT1:#x}
    call    {FONT_INIT:#x}
    jmp     pass_
fitted:
    cmp     dword ptr [{G_SE_FITFLAG:#x}], 0
    je      restored
    mov     esi, {SE_BTN0:#x}
    mov     ebx, {SE_BTN_N}
redraw:
    cmp     dword ptr [esi+0x970], {SE_FONT1:#x}
    jne     rnext
    cmp     dword ptr [esi+0xA7C], 0
    je      rnext
    mov     eax, dword ptr [esi]
    mov     ecx, esi
    call    dword ptr [eax+{SE_VT_REDRAW:#x}]
rnext:
    add     esi, {SE_BTN_STRIDE}
    dec     ebx
    jne     redraw
restored:
    pop     edi
    pop     esi
    pop     ebx
done:
    pop     ecx
    mov     eax, dword ptr [ecx]
    jmp     dword ptr [eax+{SE_VT_MODAL:#x}]
"""


NEW_THUNKS = [
    ("t_font_core", asm_font_core),
    ("t_ffn_at", asm_ffn_at),
    ("t_fdirect_at", asm_fdirect_at),
    ("t_ffn_num", asm_ffn_num),
    ("t_ffn", asm_ffn),
    ("t_fdirect_a14b", asm_fdirect_a14b),
    ("t_se_labelfit", asm_se_labelfit),
]


def assemble_all() -> tuple[dict[str, tuple[int, bytes]], int]:
    layout: dict[str, tuple[int, bytes]] = {}
    names = {n: PCAVE2 + OFF_CODE for n, _ in NEW_THUNKS}
    for _pass in range(4):
        off = OFF_CODE
        new_names = {}
        for name, fn in NEW_THUNKS:
            va = PCAVE2 + off
            b = SE.assemble(fn(), va, names)
            layout[name] = (off, b)
            new_names[name] = va
            off = (off + len(b) + 15) & ~15
        if new_names == names:
            break
        names = new_names
    else:
        raise RuntimeError("thunk layout did not converge")
    end = off
    for name, o, fn in DATA:
        layout[name] = (o, fn())
    return layout, end


SYMS = {G: "g_popup_scale_num", FIND_FONT: "find_font", FONT_INIT: "Font_init", G_KEYS: "g_ffn_keys",
        G_SLOTS: "g_ffn_slots", G_A14B: "g_font_a14b", G_BWNAME: "g_font_bwname",
        G_MONPLQ: "g_font_mon_plaque", G_MONBTN: "g_font_mon_btn", G_HOFBTN: "g_font_hof_btn",
        G_SE_FITFLAG: "g_se_fitflag"}


def templatize(b: bytes, va: int, names: dict[str, int]) -> str:
    syms = dict(SYMS)
    syms.update({v: n for n, v in names.items()})
    return SE.templatize(b, va, syms)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


GROUP_DESC = """\
      FONT FACE / WEIGHT LAW helpers (2026-09-17; brief work\\FONT_FACE_WEIGHT_AUDIT.md; src
      assemble_fontlaw.py; laws scaling_laws.font_face_law / font_direct_law; parity
      tests\\test_fontlaw_asm_parity.py).  The engine's find_font pool keys FACE and WEIGHT on the
      NATIVE size (> 12 px = "Arial Narrow" bold for variants 0/1, <= 12 px = "Arial" with weight =
      variant); asking the pool for a SCALED size crossed that boundary (tooltips, HQ report rows,
      COMMLINK rows, PrefWin text, the MP lobby body font all rendered Arial Narrow bold where
      vanilla is Arial regular/italic/bold).  t_ffn(S, v) is the find_font drop-in that takes the
      NATIVE size + variant: the pool for S > 12 while fl(S*g/16) <= 40 (unchanged), else a
      Font_init'd cave slot keyed (S, v) with the native face/style at fl(S*g/16).  t_fdirect_at /
      t_fdirect_a14b keep the face of fonts vanilla Font_inits directly (the Arial 14 bold button
      label 0x6E84B4).  t_se_labelfit = the SocialWin label fit at the build's Win_set_modal call
      (site SocialWin_build.set_modal, owned by se_scale).  Otherwise no sites of its own: the
      consumers are the retargeted font thunks of
      popup_bubble_font_scaling, rw_scale_shared, commlink_menu_scale, prefwin_scale,
      netwin_lobby_scale, basewin_strip_content, basewin_relayout, mon_scale and hof_scale.
      Every helper is the vanilla lookup at g <= 16."""


def main(argv: list[str]) -> int:
    layout, end = assemble_all()
    names = {n: PCAVE2 + layout[n][0] for n, _ in NEW_THUNKS}
    ok = True
    print("; ==== font_face_law bake (assemble_fontlaw.py) ====")
    print(f"; code {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B), section end {SECTION_END:#x}")
    if end > SECTION_END:
        ok = False
        print("; OVERFLOW past the section end")
    sym_lines, content_lines = [], []
    for name, off, size in CELLS:
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}   # font_face_law slot(s) (Font 0x28 + num + key)")
    for name, off, fn in DATA:
        b = fn()
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {len(b)} }}   # font_face_law DATA: shared-slot keys S|v<<8")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{hx(b)}\"")
    for name, _fn in NEW_THUNKS:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # font_face_law ({len(b)}B)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, names)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag, "_fragment_fontlaw_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_fontlaw_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_fontlaw_group.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"  - id: font_face_law\n    description: >\n{GROUP_DESC}\n    code_caves:\n      - pcave2\n"
                    f"      - menu_strip_thunks   # g_popup_scale_num\n    members: []\n")
        print("; fragments written to work/patches/_fragment_fontlaw_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
