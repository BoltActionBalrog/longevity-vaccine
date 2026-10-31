"""Type-1 popup gaps (W1A, 2026-10-24): fix 25a (dialog -> button-row span), fix 25b (the title band on vanilla's
half-open rows) and F35 (the option-row frame on vanilla's half-open footprint).

PORTS OF scaling_laws.py (the SOURCE OF TRUTH; regenerate the yaml bytes from here, never hand-edit):

  t_btn_vgap          popup_box_h_btn_pad / popup_dialog_btn_span
  t_band_bdraw        title_band_draw_rect
  thunk_title_height  popup_title_band_rows (v2, in place)
  t_rowbox_trim       option_row_frame_site_rect

t_btn_vgap (pcave2 0x31000) -- SITE BasePop_calculate_dimensions 0x60421C `mov ecx, [esi+0x30E4]` (8B 8E E4 30 00 00)
  -> `call t_btn_vgap` + NOP: the SECOND [+0x30E4] add into box_h (the btn_h != 0 branch; the first add @0x60420A, the
  dialog != 0 branch, stays).  0x604222..0x60422F consume ecx as vanilla does.  Reached only on the no-anchor path
  ([+0xA14] == 0) by the fall-through of `je 0x604230` @0x60421A; no branch targets 0x60421D..0x604221.  Flags are dead
  (0x604230.. rewrites them before any test).  ecx = popup_box_h_btn_pad: g > 16, [+0x30D4] == 0, [+0x30C4] != 0,
  [+0x30A8] & 0x400 clear (tested as the byte [+0x30A9] & 4) -> fl(2 (3 src / 2) g/16) - [+0x30E4], src = [+0x21C4],
  computed as 0xA0C250 computes [+0x30E4] (`lea; sar 1`, then popup_scale); else [+0x30E4].  CONTRACT: entered by E8,
  bare `ret`; ecx out; eax saved / restored around popup_scale (which writes eax and flags only); no memory written.

t_band_bdraw (pcave2 0x31050) -- the tail of thunk_pf_title_stash (outer d5a0, the 0x406048 call, returns 0x40604D)
  and of thunk_inner_margin (inner d618, the 0x406078 call, returns 0x40607D): their `push {abs32:...}; ret` imm32 is
  {abs32:t_band_bdraw} (same length).  g > 16: thunk_box_thick_flat draws a stack COPY of the rect with b - 1; the
  engine's rect is never written (the inner inset 0x406050.. and the title text 0x406080.. read it after each draw).
  g <= 16: tail-jump thunk_box_thick_flat unchanged.  CONTRACT == Buffer_box_sprite / thunk_box_thick_flat: ecx = dest
  buffer (passed through), [esp] = ret, [esp+4] = &rect, [esp+8] = BoxSpriteParams*, RET 8; eax clobbered (both
  callers reload it from the frame); ebx, esi, edi, ebp are thunk_box_thick_flat's callee-saved contract.

thunk_title_height v2 (menu_strip_thunks 0xBD0, in place: 43 B slot, v2 33 B) -- SITE 0x40602E (unchanged): eax =
  frame.top + 3 on entry; the caller stores eax -> rect.top and, after its `dec ecx` @0x406033, ecx -> rect.bottom.
  v2: eax = frame.top + fl(4g/16), ecx = frame.top + fl(28g/16) + 1 (v1: eax + fl(24g/16) + 1); replays the displaced
  `dec edx`; no gate (identity at g = 16: frame.top + 4 / + 28 + 1).  The stack slot under the return address is used
  for one push / pop.  Every other register as v1.

t_rowbox_trim (pcave2 0x310A0) -- SITE FUN_00405b20.option_frame 0x405BF6: its rel32 -> t_rowbox_trim (was
  t_rowbox_ph), which tail-jumps t_rowbox_ph.  g > 16, the popup ([ebp-4], stored @0x405B30 on every path that reaches
  the site) not dialog type 16 ([+0x2350]) and not DiploTalkWin-anchored ([+0xA14] != 0x733990), the rows
  t_dp_itemrect has not trimmed: dec the LOCAL rect's r and b ([esp+4] = &[ebp-0x14], dead after the draw: 0x405BFB..
  reads no rect field).  CONTRACT == t_rowbox_ph's: thiscall, ecx = dest, 2 args, RET 8 (tail jump, the stack is the
  site's); eax clobbered (the site's eax is &local, dead; the native fn sets eax = 1 after).

Usage: assemble_type1_gaps.py   -> prints the symbol lines, the content entries and the site bytes
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from keystone import KS_ARCH_X86, KS_MODE_32, Ks
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

from scaling_laws import (DIPLO_TALK_ANCHOR, NATIVE_G, OPTION_ROW_TRIMMED_TYPE, POPUP_FLAG_PAD_UNSCALED,
                          POPUP_TITLE_BAND_BOTTOM, POPUP_TITLE_BAND_TOP)

PCAVE2 = 0x00A0C000
MENU = 0x00668200                       # menu_strip_thunks (virtual_addr)
G = 0x00668740                          # g_popup_scale_num
POPUP_SCALE = 0x00668750                # popup_scale: eax = eax * g >> 4 (writes eax, flags)

T_BTN_VGAP = PCAVE2 + 0x31000
T_BAND_BDRAW = PCAVE2 + 0x31050
T_ROWBOX_TRIM = PCAVE2 + 0x310A0
REGION_END = PCAVE2 + 0x32000           # W1A's pcave2 region 0x31000..0x31FFF
THUNK_TITLE_HEIGHT = MENU + 0xBD0
TITLE_HEIGHT_SLOT_END = MENU + 0xBFB    # v1's 43 B (thunk_box_thick starts 0xC00)

# fixed VAs of the thunks these tail into (cross-checked against the yaml symbol table by the parity test)
THUNK_BOX_THICK_FLAT = PCAVE2 + 0x2E840
T_ROWBOX_PH = PCAVE2 + 0x11040

SITE_BTN_VGAP = 0x0060421C
SITE_BTN_VGAP_ORIG = "8B 8E E4 30 00 00"
SITE_ROWBOX = 0x00405BF6

ABS = {G: "{abs32:g_popup_scale_num}", THUNK_BOX_THICK_FLAT: "{abs32:thunk_box_thick_flat}",
       T_ROWBOX_PH: "{abs32:t_rowbox_ph}"}
REL = {POPUP_SCALE: "{rel32:popup_scale}", THUNK_BOX_THICK_FLAT: "{rel32:thunk_box_thick_flat}"}

assert POPUP_FLAG_PAD_UNSCALED == 0x400 and NATIVE_G == 16 and OPTION_ROW_TRIMMED_TYPE == 0x10


def asm_btn_vgap() -> str:
    return f"""
    mov     ecx, dword ptr [esi+0x30E4]
    cmp     dword ptr [{G:#x}], {NATIVE_G:#x}
    jle     done
    cmp     dword ptr [esi+0x30D4], 0
    jne     done
    cmp     dword ptr [esi+0x30C4], 0
    je      done
    test    byte ptr [esi+0x30A9], {POPUP_FLAG_PAD_UNSCALED >> 8:#x}
    jne     done
    push    eax
    mov     eax, dword ptr [esi+0x21C4]
    lea     eax, [eax+eax*2]
    sar     eax, 1
    add     eax, eax
    call    {POPUP_SCALE:#x}
    sub     eax, ecx
    mov     ecx, eax
    pop     eax
done:
    ret
"""


def asm_band_bdraw() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], {NATIVE_G:#x}
    jle     tail
    mov     eax, dword ptr [esp+4]
    push    dword ptr [eax+12]
    push    dword ptr [eax+8]
    push    dword ptr [eax+4]
    push    dword ptr [eax]
    dec     dword ptr [esp+12]
    mov     eax, esp
    push    dword ptr [esp+0x18]
    push    eax
    call    {THUNK_BOX_THICK_FLAT:#x}
    add     esp, 16
    ret     8
tail:
    push    {THUNK_BOX_THICK_FLAT:#x}
    ret
"""


def asm_title_height() -> str:
    return f"""
    lea     ecx, [eax-3]
    imul    eax, dword ptr [{G:#x}], {POPUP_TITLE_BAND_BOTTOM}
    sar     eax, 4
    lea     eax, [eax+ecx+1]
    push    eax
    imul    eax, dword ptr [{G:#x}], {POPUP_TITLE_BAND_TOP}
    sar     eax, 4
    add     eax, ecx
    pop     ecx
    dec     edx
    ret
"""


def asm_rowbox_trim() -> str:
    return f"""
    cmp     dword ptr [{G:#x}], {NATIVE_G:#x}
    jle     go
    mov     eax, dword ptr [ebp-4]
    cmp     dword ptr [eax+0x2350], {OPTION_ROW_TRIMMED_TYPE:#x}
    je      go
    cmp     dword ptr [eax+0xA14], {DIPLO_TALK_ANCHOR:#x}
    je      go
    mov     eax, dword ptr [esp+4]
    dec     dword ptr [eax+8]
    dec     dword ptr [eax+12]
go:
    push    {T_ROWBOX_PH:#x}
    ret
"""


THUNKS = (  # (name, asm builder, va, slot end)
    ("t_btn_vgap", asm_btn_vgap, T_BTN_VGAP, T_BAND_BDRAW),
    ("t_band_bdraw", asm_band_bdraw, T_BAND_BDRAW, T_ROWBOX_TRIM),
    ("t_rowbox_trim", asm_rowbox_trim, T_ROWBOX_TRIM, REGION_END),
    ("thunk_title_height", asm_title_height, THUNK_TITLE_HEIGHT, TITLE_HEIGHT_SLOT_END),
)


def assemble(src: str, va: int) -> bytes:
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(src, va)
    b = bytes(enc)
    assert sum(i.size for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b, va)) == len(b)
    return b


def to_template(b: bytes, va: int) -> str:
    out, i = [], 0
    while i < len(b):
        if b[i] == 0xE8 and i + 5 <= len(b):   # the patcher takes {rel32:} after E8 only
            tgt = (va + i + 5 + int.from_bytes(b[i + 1:i + 5], "little", signed=True)) & 0xFFFFFFFF
            if tgt in REL:
                out += ["E8", REL[tgt]]
                i += 5
                continue
        if i + 4 <= len(b) and int.from_bytes(b[i:i + 4], "little") in ABS:
            out.append(ABS[int.from_bytes(b[i:i + 4], "little")])
            i += 4
            continue
        out.append(f"{b[i]:02X}")
        i += 1
    return " ".join(out)


#: thunk_title_height v1 (da1474af and before): eax = frame.top + popup_scale(4), ecx = eax + popup_scale(24) + 1
TITLE_HEIGHT_V1 = ("8B C8 B8 04 00 00 00 0F AF 05 {abs32:g_popup_scale_num} C1 F8 04 03 C1 83 E8 03 B9 18 00 00 00 "
                   "0F AF 0D {abs32:g_popup_scale_num} C1 F9 04 8D 4C 08 01 4A C3")


def disarm_edits(rd, st: dict) -> list:
    """[(va, bytes)] that turn the three W1A fixes off in a baked image (= the da1474af geometry), for the tests'
    mutants: the 0x60421C site back to `mov ecx, [esi+0x30E4]`, the two title-band tails back to
    thunk_box_thick_flat, thunk_title_height v1, the 0x405BF6 rel32 back to t_rowbox_ph.  rd(va, n) reads the image;
    st is the yaml symbol table."""
    import struct
    import apply_patches as ap
    e = [(SITE_BTN_VGAP, bytes.fromhex(SITE_BTN_VGAP_ORIG.replace(" ", "")))]
    tail_new = bytes([0x68]) + struct.pack("<I", st["t_band_bdraw"]) + bytes([0xC3])
    tail_old = bytes([0x68]) + struct.pack("<I", st["thunk_box_thick_flat"]) + bytes([0xC3])
    for name in ("thunk_pf_title_stash", "thunk_inner_margin"):
        b = rd(st[name], 160)
        i = b.find(tail_new)
        assert i >= 0 and b.find(tail_new, i + 1) < 0, name
        e.append((st[name] + i, tail_old))
    e.append((st["thunk_title_height"], bytes(ap.ByteTemplate(TITLE_HEIGHT_V1).resolve(st["thunk_title_height"], st))))
    assert rd(SITE_ROWBOX, 1) == bytes([0xE8])
    e.append((SITE_ROWBOX + 1, struct.pack("<i", st["t_rowbox_ph"] - (SITE_ROWBOX + 5))))
    return e


def build() -> dict:
    """name -> (va, bytes, yaml template)."""
    out = {}
    for name, fn, va, end in THUNKS:
        b = assemble(fn(), va)
        assert va + len(b) <= end, f"{name} {len(b)} B overflows its slot ({end - va} B)"
        out[name] = (va, b, to_template(b, va))
    return out


def main() -> int:
    for name, (va, b, tmpl) in build().items():
        cave, base = ("menu_strip_thunks", MENU) if va < PCAVE2 else ("pcave2", PCAVE2)
        print(f"# {name}: {cave} {va - base:#x}, {len(b)} B")
        print(f'        bytes: "{tmpl}"')
    print(f'site {SITE_BTN_VGAP:#x}: original_bytes "{SITE_BTN_VGAP_ORIG}" -> new_bytes "E8 {{rel32:t_btn_vgap}} 90"')
    print(f'site {SITE_ROWBOX:#x}: new_bytes "E8 {{rel32:t_rowbox_trim}}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
