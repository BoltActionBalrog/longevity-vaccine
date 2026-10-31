r"""Assemble the popup screen-edge gap thunks.

PORT OF: scaling_laws.py :: popup_edge_anchor_offset() / popup_edge_anchor_shift()
         and faction_picker_origin() / faction_quote_x()   (the SOURCE OF TRUTH).

DEFECT FIXED (2026-10-11, 4K shot terranx_pracx_3840x2160_20261011-125213, Pause
dump rect [2130,1561,3835,2155]): BasePop_exec_3 places a popup whose x/y request
([popup+0x30F8] / [+0x30FC]) is NEGATIVE against the far screen edge,
`pos = span - box + req`, and the requests are NATIVE gaps -- Script.txt `#x -5
#y -5` on every pre-game setup popup (CUSTOMNAMES "Customize Your Faction",
RULES, DIFFICULTY, FACTION, ...), -20 on the BATTLE* prompts, Console_go_to's
set_loc(-10,-10), NetMsg 0x7FFF80's x = -5. Vanilla adds them raw, so at 4K the
Customize popup hugged the corner at 5 device px while the faction picker it
pairs with sits at (5,5) native -- both now keep fl(5g/16) (12 at g=40).

thunk_popup_edge_anchor  (92 B, pcave2 + 0x50B0)
    SITE 0x602B49 (7 B `8B 06 8B CE FF 50 30` mov eax,[esi]; mov ecx,esi;
    call [eax+0x30]) -> `E8 rel32; 90 90`. 0x602B49 is the JOIN of every
    placement branch (main / flag-2 / child-popup arms, all of which write
    BOTH [+0x30B4] and [+0x30B8] first), so ONE correction there covers all
    of them: for each axis whose request is in (-0x1000, 0), the placed
    coordinate gets (law - req) added (popup_edge_anchor_shift). The request
    fields are never written (exec_3 runs more than once per popup -- a scaled
    field would compound). g<=16: no change. edx preserved; eax/ecx are the
    replayed `mov eax,[esi]; mov ecx,esi`; the vtbl call is a tail jmp
    [eax+0x30], so it returns to the site's 90 90 -> 0x602B50. Flags dead.

thunk_fac_origin  (49 B, pcave2 + 0x5110)
    SITE 0x488BDF (FactionPickWin_build `call GraphicWin_init`), retargeted
    from thunk_factionwin_graphicwin: ensure g (pushad/thunk_ensure_scale/
    popad -- the chained thunk does it again, idempotent), x [esp+4] and
    y [esp+8] = popup_scale_floor(v, g), then push/ret into
    thunk_factionwin_graphicwin (w/h scaling unchanged). g == 16: identity.

thunk_fac_quote_x  (33 B, pcave2 + 0x5150)
    SITE 0x589A02 (thumb_routine `call BasePop_set_loc(5, 0x136)`),
    retargeted from thunk_factionwin_quoteloc: g>16 -> x [esp+4] =
    popup_scale_floor(x, g) (the quote box stays flush with the picker's
    left edge), then push/ret into thunk_factionwin_quoteloc (y unchanged).

SLOTS: pcave2 0x50A2..0x51AF was free (cave_map --at 2026-10-11: between
thunk_hud_fcache ends 0x50A2 and thunk_hud_slotw 0x51B0).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

EDGE_TEMPLATE = (
    "52 "                                   # push edx
    "8B 15 {abs32:g_popup_scale_num} "      # mov  edx,[g]
    "83 FA 10 "                             # cmp  edx,16
    "7E 48 "                                # jle  done
    "8B 8E F8 30 00 00 "                    # mov  ecx,[esi+0x30F8]   x request
    "85 C9 "                                # test ecx,ecx
    "7D 1A "                                # jge  skipx              (centre / literal)
    "81 F9 00 F0 FF FF "                    # cmp  ecx,-0x1000
    "7E 12 "                                # jle  skipx
    "89 C8 "                                # mov  eax,ecx
    "F7 D8 "                                # neg  eax                m = -req
    "0F AF C2 "                             # imul eax,edx            m*g
    "C1 F8 04 "                             # sar  eax,4              fl(m*g/16)
    "01 C8 "                                # add  eax,ecx            fl - m = req - law
    "29 86 B4 30 00 00 "                    # sub  [esi+0x30B4],eax   placed x += law - req
    # skipx:
    "8B 8E FC 30 00 00 "                    # mov  ecx,[esi+0x30FC]   y request
    "85 C9 "                                # test ecx,ecx
    "7D 1A "                                # jge  done
    "81 F9 00 F0 FF FF "                    # cmp  ecx,-0x1000
    "7E 12 "                                # jle  done
    "89 C8 "                                # mov  eax,ecx
    "F7 D8 "                                # neg  eax
    "0F AF C2 "                             # imul eax,edx
    "C1 F8 04 "                             # sar  eax,4
    "01 C8 "                                # add  eax,ecx
    "29 86 B8 30 00 00 "                    # sub  [esi+0x30B8],eax   placed y += law - req
    # done:
    "5A "                                   # pop  edx
    "8B 06 "                                # mov  eax,[esi]          (displaced)
    "89 F1 "                                # mov  ecx,esi            (displaced)
    "FF 60 30"                              # jmp  [eax+0x30]         (displaced call, tail)
)

ORIGIN_TEMPLATE = (
    "60 "                                   # pushad
    "E8 {rel32:thunk_ensure_scale} "        # g valid (>= 16) before the first build
    "61 "                                   # popad
    "8B 44 24 04 "                          # mov  eax,[esp+4]        x
    "0F AF 05 {abs32:g_popup_scale_num} "   # imul eax,[g]
    "C1 F8 04 "                             # sar  eax,4
    "89 44 24 04 "                          # mov  [esp+4],eax
    "8B 44 24 08 "                          # mov  eax,[esp+8]        y
    "0F AF 05 {abs32:g_popup_scale_num} "   # imul eax,[g]
    "C1 F8 04 "                             # sar  eax,4
    "89 44 24 08 "                          # mov  [esp+8],eax
    "68 {abs32:thunk_factionwin_graphicwin} C3"   # push/ret: w/h + flags, then GraphicWin_init
)

QUOTE_TEMPLATE = (
    "83 3D {abs32:g_popup_scale_num} 10 "   # cmp  dword [g],16
    "7E 12 "                                # jle  out                (g<=16 or not yet set)
    "8B 44 24 04 "                          # mov  eax,[esp+4]        x
    "0F AF 05 {abs32:g_popup_scale_num} "   # imul eax,[g]
    "C1 F8 04 "                             # sar  eax,4
    "89 44 24 04 "                          # mov  [esp+4],eax
    # out:
    "68 {abs32:thunk_factionwin_quoteloc} C3"     # push/ret: y, then BasePop_set_loc
)

EDGE_OFFSET = 0x50B0
ORIGIN_OFFSET = 0x5110
QUOTE_OFFSET = 0x5150
RESERVED = (0x50A2, 0x51B0)              # [lo, hi)
PCAVE2_VA = 0x00A0C000

SITE_EDGE = 0x00602B49
SITE_EDGE_ORIGINAL = "8B 06 8B CE FF 50 30"
SITE_ORIGIN = 0x00488BDF
SITE_QUOTE = 0x00589A02

THUNKS = (
    ("thunk_popup_edge_anchor", EDGE_OFFSET, EDGE_TEMPLATE, 92),
    ("thunk_fac_origin", ORIGIN_OFFSET, ORIGIN_TEMPLATE, 49),
    ("thunk_fac_quote_x", QUOTE_OFFSET, QUOTE_TEMPLATE, 33),
)


def resolve(template: str, va: int, symbols: dict[str, int]) -> bytes:
    """Resolve {abs32:}/{rel32:} placeholders the way apply_patches does,
    for a thunk placed at `va`. rel32 is relative to the END of the field."""
    out = bytearray()
    for tok in template.split():
        m = re.fullmatch(r"\{(abs32|rel32):(\w+)\}", tok)
        if not m:
            out.append(int(tok, 16))
            continue
        kind, name = m.groups()
        target = symbols[name]
        if kind == "abs32":
            out += target.to_bytes(4, "little")
        else:
            here = va + len(out) + 4
            out += ((target - here) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


ZERO_SYMS = {"g_popup_scale_num": 0, "thunk_ensure_scale": 0,
             "thunk_factionwin_graphicwin": 0, "thunk_factionwin_quoteloc": 0}


def main() -> int:
    end = 0
    for name, off, tpl, size in THUNKS:
        n = len(resolve(tpl, PCAVE2_VA + off, ZERO_SYMS))
        assert n == size, f"{name}: {n} B != {size}"
        assert RESERVED[0] <= off and off + n <= RESERVED[1], f"{name} leaves the reserved range"
        assert off >= end, f"{name} overlaps the previous thunk"
        end = off + n
        print(f"{name}  {n} bytes @ pcave2+0x{off:X}..0x{off + n:X}")
        print(f'        bytes: "{tpl}"')
        print()
    # branch bookkeeping (edge thunk): jle done = 0x48, jge/jle skipx = 0x1A/0x12
    body = resolve(EDGE_TEMPLATE, 0, ZERO_SYMS)
    done = body.index(bytes.fromhex("5A 8B 06"))
    assert 12 + 0x48 == done, "jle done displacement"           # rel8 counts from the insn END
    skipx = body.index(bytes.fromhex("8B 8E FC 30 00 00"))
    assert 22 + 0x1A == skipx and 30 + 0x12 == skipx, "x-arm displacements"
    assert 58 + 0x1A == done and 66 + 0x12 == done, "y-arm displacements"

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scaling_laws import popup_edge_anchor_shift  # noqa: E402
    for g in range(16, 41):
        for req in (-1, -5, -10, -20, -0xFFF):
            have = 0 if g <= 16 else -((((-req) * g) >> 4) + req)
            assert have == popup_edge_anchor_shift(req, g), (g, req)
    print("template arithmetic == scaling_laws.popup_edge_anchor_shift for g in [16,40]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
