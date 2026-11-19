"""Assemble the three find_font(popup_scale(12), 0) sites onto the font face law (2026-11-10).

PORT OF: scaling_laws.py :: FILEDLG_TEXT_FONT / LOBBY_CHAT_FONT -> font_face_law_font(12, 0, g).

Vanilla draws all three in Arial 12 REGULAR (FileDlg: refs/pristine/Save.png glyph-exact; lobby chat: the probed
0x7D3948).  v1 asked the pool for find_font(popup_scale(12), 0), which snaps to 14+ from g = 18 = Arial Narrow BOLD.
They now call t_ffn(12, 0) (assemble_fontlaw.py): Arial fl(12g/16) regular on the shared (12, 0) slot.

  thunk_filedlg_dlgfont   pcave2 0x2620  call-redirect @0x407737 Dialog_set_dialog_font(&0x7CFEB4)  (file list)
  thunk_filedlg_editfont  pcave2 0x2660  call-redirect @0x407813 Buffer_set_font(&0x7CFEB4)         (filename field)
  thunk_nw_chatfont       pcave2 0x4A90  E8 @0x482A63; sets the lobby chat TextScroll / EditLine font1, then the
                                         displaced MOV ESI,[EBX+0x3978]

g <= 16: byte-for-byte the v1 pass-through (the jle skips the whole swap).  Each slot shrinks (49 -> 40, 49 -> 40,
48 -> 39 B); the freed tails are zero (whole-cave write).

Run:  py assemble_font_face_sites.py   -> checks + prints the yaml byte templates
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0xA0C000


def _font_push(native_variant) -> str:
    s, v = native_variant
    return f"6A {v:02X} 6A {s:02X} "


def _set_font_tpl(tail: str) -> str:
    return (
        "81 3D {abs32:g_popup_scale_num} 10 00 00 00 "   # cmp [g],16
        "7E 16 "                                         # jle tail (native font untouched)
        "51 "                                            # push ecx (thiscall self of the tail callee)
        + _font_push(SL.FILEDLG_TEXT_FONT) +             # push v; push S
        "E8 {rel32:t_ffn} "                              # t_ffn(S, v) -- cdecl, clobbers eax/ecx/edx
        "83 C4 08 "                                      # add esp,8
        "59 "                                            # pop ecx
        "85 C0 "                                         # test eax,eax
        "74 04 "                                         # je tail
        "89 44 24 04 "                                   # mov [esp+4],eax  (the font arg)
        "68 {abs32:" + tail + "} C3"                     # tail: push callee; ret
    )


TEMPLATES = {
    "thunk_filedlg_dlgfont": (0x2620, _set_font_tpl("Dialog_set_dialog_font")),
    "thunk_filedlg_editfont": (0x2660, _set_font_tpl("Buffer_set_font")),
    "thunk_nw_chatfont": (0x4A90, (
        "A1 {abs32:g_popup_scale_num} "                  # mov eax,[g]
        "83 F8 10 "                                      # cmp eax,16
        "7E 16 "                                         # jle displaced
        + _font_push(SL.LOBBY_CHAT_FONT) +               # push v; push S
        "E8 {rel32:t_ffn} "                              # t_ffn(S, v)
        "83 C4 08 "                                      # add esp,8
        "A3 A8 BD 80 00 "                                # mov [0x80BDA8],eax  (TextScroll font1)
        "A3 48 E9 80 00 "                                # mov [0x80E948],eax  (EditLine font1)
        "8B B3 78 39 00 00 "                             # displaced: mov esi,[ebx+0x3978]
        "C3")),
}
# thunk_tutwin_fonts v2 (2026-11-10): the call-redirect at BOTH popups_tutorial sites (popt 0x48C324, tut_win
# 0x4BE083).  Runs popups_tutorial (native installs), then at g > 16 re-installs the string, dialog AND button
# default triples at find_font(g, 0/1/2) (law tutorial_popup_font_law; scale_px(16, g) == g exactly).  v1 skipped
# the button triple, so every tutor.txt popup's OK/CANCEL kept the native Arial Narrow 16 bold.  Args stay on the
# stack until one add esp at the end (all callees cdecl) -- that pays for the third call inside the v1 slot.
TEMPLATES["thunk_tutwin_fonts"] = (0xA890, (
    "E8 {rel32:popups_tutorial} "                        # popups_tutorial()  (vanilla installs, native)
    "A1 {abs32:g_popup_scale_num} "                      # mov eax,[g]
    "83 F8 10 "                                          # cmp eax,16
    "7E 43 "                                             # jle done (native style untouched)
    "53 56 57 "                                          # push ebx; push esi; push edi
    "8B D8 "                                             # mov ebx,eax            (size = g)
    "6A 00 53 E8 {rel32:find_font} 8B F0 "               # esi = find_font(g, 0)
    "6A 01 53 E8 {rel32:find_font} 8B F8 "               # edi = find_font(g, 1)
    "6A 02 53 E8 {rel32:find_font} 8B D8 "               # ebx = find_font(g, 2)
    "6A 00 53 57 56 E8 {rel32:BasePop_set_def_string_font} "   # (v0, v1, v2, 0)
    "53 57 56 E8 {rel32:Dialog_set_def_dialog_font} "          # (v0, v1, v2)
    "53 57 56 E8 {rel32:BasePop_set_def_button_font} "         # (v0, v1, v2)   NEW in v2
    "83 C4 40 "                                          # add esp,0x40  (3 x 8 + 16 + 12 + 12)
    "5F 5E 5B "                                          # pop edi; pop esi; pop ebx
    "C3"))                                               # done: ret
SLOT_END = {"thunk_filedlg_dlgfont": 0x2651, "thunk_filedlg_editfont": 0x2691, "thunk_nw_chatfont": 0x4AC0,
            "thunk_tutwin_fonts": 0xA8F0}          # next: thunk_tutwin_line @0xA8F0 (cave_map --at 0xA890)

DUMMY = {"g_popup_scale_num": 0x668740, "t_ffn": 0xA3A570, "Dialog_set_dialog_font": 0x609C60,
         "Buffer_set_font": 0x5DAC70, "popups_tutorial": 0x5888E0, "find_font": 0x5882F0,
         "BasePop_set_def_string_font": 0x6048C0, "Dialog_set_def_dialog_font": 0x609D20,
         "BasePop_set_def_button_font": 0x6049C0}


def resolve(tpl: str, va: int, sym=None) -> bytes:
    sym = sym or DUMMY
    out = bytearray()
    for tok in tpl.split():
        if tok.startswith("{abs32:"):
            out += sym[tok[7:-1]].to_bytes(4, "little")
        elif tok.startswith("{rel32:"):
            out += ((sym[tok[7:-1]] - (va + len(out) + 4)) & 0xFFFFFFFF).to_bytes(4, "little")
        else:
            out.append(int(tok, 16))
    return bytes(out)


KS_SRC = {
    "thunk_filedlg_dlgfont": """
        jle tail
        push ecx
        push {v}
        push {s}
        call {t_ffn:#x}
        add esp, 8
        pop ecx
        test eax, eax
        je tail
        mov dword ptr [esp+4], eax
    tail:
        push {callee:#x}
        ret
    """,
    "thunk_nw_chatfont": """
        mov eax, dword ptr [{g:#x}]
        cmp eax, 16
        jle disp
        push {v}
        push {s}
        call {t_ffn:#x}
        add esp, 8
        mov dword ptr [0x80BDA8], eax
        mov dword ptr [0x80E948], eax
    disp:
        mov esi, dword ptr [ebx+0x3978]
        ret
    """,
    "thunk_tutwin_fonts": """
        call {popups_tutorial:#x}
        mov eax, dword ptr [{g:#x}]
        cmp eax, 16
        jle done
        push ebx
        push esi
        push edi
        mov ebx, eax
        push 0
        push ebx
        call {find_font:#x}
        mov esi, eax
        push 1
        push ebx
        call {find_font:#x}
        mov edi, eax
        push 2
        push ebx
        call {find_font:#x}
        mov ebx, eax
        push 0
        push ebx
        push edi
        push esi
        call {string:#x}
        push ebx
        push edi
        push esi
        call {dialog:#x}
        push ebx
        push edi
        push esi
        call {button:#x}
        add esp, 0x40
        pop edi
        pop esi
        pop ebx
    done:
        ret
    """,
}


def main() -> int:
    for name, (off, tpl) in TEMPLATES.items():
        va = PCAVE2 + off
        b = resolve(tpl, va)
        assert off + len(b) <= SLOT_END[name], (name, len(b))
        if name == "thunk_tutwin_fonts":
            assert b[0xD] == 0x7E and 0xF + b[0xE] == len(b) - 1, "jle -> ret"
            assert SL.tutorial_popup_font_law(0, 16) == SL.font_face_law_font(SL.TUTORIAL_POPUP_FONT_NATIVE, 0, 16)
            from keystone import Ks, KS_ARCH_X86, KS_MODE_32
            import ks_guard  # noqa: F401
            src = KS_SRC[name].format(popups_tutorial=DUMMY["popups_tutorial"], g=DUMMY["g_popup_scale_num"],
                                      find_font=DUMMY["find_font"], string=DUMMY["BasePop_set_def_string_font"],
                                      dialog=DUMMY["Dialog_set_def_dialog_font"],
                                      button=DUMMY["BasePop_set_def_button_font"])
            enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
            # v1's `8B /r` reg-reg movs are kept (keystone picks the equivalent `89 /r`): compare instructions
            from capstone import Cs, CS_ARCH_X86, CS_MODE_32
            md = Cs(CS_ARCH_X86, CS_MODE_32)

            def ins(code):
                return [(i.address, i.mnemonic, i.op_str) for i in md.disasm(code, va)]
            assert len(bytes(enc)) == len(b) and ins(bytes(enc)) == ins(b), (name, bytes(enc).hex(" "), b.hex(" "))
            print(f"{name} @ pcave2+{off:#06x}: {len(b)} B (slot ends {SLOT_END[name]:#x})")
            print(f'        bytes: "{tpl}"')
            continue
        # every exit branch lands where the comments say
        if name != "thunk_nw_chatfont":
            tail = len(b) - 6                     # push imm32; ret
            assert b[tail] == 0x68, name
            assert b[10] == 0x7E and 12 + b[11] == tail, name
            assert b[28] == 0x74 and 30 + b[29] == tail, name
        else:
            assert b[8] == 0x7E and 10 + b[9] == len(b) - 7, name
        try:
            from keystone import Ks, KS_ARCH_X86, KS_MODE_32
            import ks_guard  # noqa: F401
            nat = SL.FILEDLG_TEXT_FONT if name.startswith("thunk_filedlg") else SL.LOBBY_CHAT_FONT
            callee = DUMMY["Buffer_set_font"] if name == "thunk_filedlg_editfont" else DUMMY["Dialog_set_dialog_font"]
            src = KS_SRC["thunk_nw_chatfont" if name == "thunk_nw_chatfont" else "thunk_filedlg_dlgfont"]
            src = src.format(g=DUMMY["g_popup_scale_num"], t_ffn=DUMMY["t_ffn"], s=nat[0], v=nat[1], callee=callee)
            if name == "thunk_nw_chatfont":
                enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
                assert bytes(enc) == b, (name, bytes(enc).hex(" "), b.hex(" "))
            else:   # v1's long-form gate `81 3D g imm32` kept byte-for-byte; keystone checks the rest
                assert b[:10] == bytes.fromhex("813D") + DUMMY["g_popup_scale_num"].to_bytes(4, "little") + (16).to_bytes(4, "little")
                enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va + 10)
                assert bytes(enc) == b[10:], (name, bytes(enc).hex(" "), b[10:].hex(" "))
        except ImportError:
            print("  (keystone not installed -- skipping the encoding cross-check)")
        print(f"{name} @ pcave2+{off:#06x}: {len(b)} B (slot ends {SLOT_END[name]:#x})")
        print(f'        bytes: "{tpl}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
