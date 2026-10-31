r"""Assemble the UNTITLED-popup chrome set (2026-09-18, version popup 4K shot
20260918-003046 vs refs\pristine\VersionNumber.png):

  thunk_untitled_stash     NEW   site 0x405F7C  (Popup_on_draw_background)
  thunk_scale_header  v2   RELOCATED menu_strip 0xBB0 -> pcave2 (push/ret site, symbol move only)
  thunk_popup_nestpads v3  RELOCATED pcave2 0x3770 -> here     (E8 site, symbol move only)

PORT OF scaling_laws.py :: untitled_virtual_title_bottom, popup_header_reserve,
nested_frame_pad(body_only), flat_art_anchor  (the SOURCE OF TRUTH).

DEFECTS (all one class: the popup has NO TITLE, [popup+0xa48]==0):
 1. Popup_on_draw_background's `je 0x4060e7` @0x405f84 skips the whole title
    block, so thunk_pf_title_stash never runs and the pf-align pair reads the
    PREVIOUS popup's g_title_left/right -> text-box right edge 178px short.
 2. thunk_scale_header v1 scaled the header reserve for TITLED popups only ->
    the untitled 18 stayed native (ring top +6 device px instead of +30 @g40).
 3. thunk_popup_nestpads v2 (list-container law scale_px(2)) also hit the
    BODY-ONLY path, where the ring nests around the d528 STROKE -> L/T/B stroke
    pitch 5 vs 7 on the pf-aligned right edge @g40.
 4. art: unkeyed -> engine x/y (frame 7px right of / 6px under the ring corner).

thunk_untitled_stash runs the SAME inset thunks the titled path runs
(thunk_popup_titleinsets / thunk_title_hmargin, selected by the engine's own
Win_is_visible(MainWin) test) on the same window rect -- one cascade, no
parallel formula -- then applies the engine's +1/-1 and stores the VIRTUAL band
L/R.  [ebp-0x14]/[ebp-0xc] are dead on the untitled path (no read after
0x4060e7).  It arms g_band_popup (artalign x law + fieldpads' keyed arm) with a
virtual g_title_bottom chosen so the keyed arm lands on the engine's own
T = content_top - ps3.  nestpads v3 pre-adds frame_grow_delta to g_field_anchor
for EVERY keyed flat/slide body-only popup (titled Quit included): artalign's
flat math still subtracts the delta of the pre-2026-07-09 GROWING ring, which
left the art delta ABOVE the flat ring (Quit 4K 928 vs 931, 1600 437 vs 438;
user shots 20260918-011743/012134).  An inapplicable untitled popup (g<=16 / faction quote / ornate) DISARMS a stale
key that matches its pointer.

SITE 0x405F7C  8B 86 48 0A 00 00  mov eax,[esi+0xa48]  (6B; not a branch target
-- census 2026-09-18; not PRACX-stomped) -> E8 {rel32:thunk_untitled_stash} 90.
CALL-entered, bare RET, returns eax = [esi+0xa48] (the site's own `test eax,eax`
follows).  pushad around the engine call; esi/ebp/ebx/edi preserved.
"""
from __future__ import annotations

import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86 import X86_OP_IMM, X86_OP_MEM
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import apply_patches as ap  # noqa: E402

PCAVE2 = 0x00A0C000
SLOT_START, SLOT_END = 0x2E6A0, 0x2E900        # pcave2 tail: cave_map FREE 0x2e690-0x30000 + live zero check 2026-09-18
SITE_VA = 0x00405F7C
FACTION_POPUP = 0x009403E0
MAINWIN = 0x007AE820
WIN_IS_VISIBLE = 0x005F7E90

NEW_SYMS = {"thunk_untitled_stash", "Win_is_visible"}


def symtab() -> dict[str, int]:
    sites, groups, caves, symbols = ap.load_patches(HERE.parent / "patches" / "patches.yaml")
    return ap.build_symbol_table(symbols, caves)


def sym_vas() -> dict[str, int]:
    st = symtab()
    want = ["g_popup_scale_num", "g_title_left", "g_title_right", "g_title_bottom", "g_band_popup",
            "g_field_anchor", "g_fp_ornart", "thunk_popup_titleinsets", "thunk_title_hmargin", "header_reserve_resume",
            "thunk_tutwin_backdrop"]
    out = {k: st[k] for k in want}
    out["Win_is_visible"] = WIN_IS_VISIBLE
    return out


def asm_untitled_stash(s: dict[str, int]) -> str:
    return f"""
    mov     eax, dword ptr [esi+0xa48]
    test    eax, eax
    jne     L_titled
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 0x10
    jle     L_off
    cmp     esi, {FACTION_POPUP:#x}
    je      L_off
    mov     eax, dword ptr [ebp-4]              /* popup type (raw/10000)            */
    test    eax, eax
    je      L_go
    cmp     eax, 5
    jne     L_off
L_go:
    pushad
    mov     eax, dword ptr [ebx]                /* ebx = &window rect [esi+0x474]    */
    mov     dword ptr [ebp-0x14], eax
    mov     eax, dword ptr [ebx+8]
    mov     dword ptr [ebp-0xc], eax
    mov     ecx, {MAINWIN:#x}
    call    {s['Win_is_visible']:#x}
    test    eax, eax
    je      L_hm
    call    {s['thunk_popup_titleinsets']:#x}
    jmp     L_st
L_hm:
    call    {s['thunk_title_hmargin']:#x}
L_st:
    mov     eax, dword ptr [ebp-0x14]
    inc     eax                                 /* the engine's 0x406027 inc         */
    mov     dword ptr [{s['g_title_left']:#x}], eax
    mov     eax, dword ptr [ebp-0xc]
    dec     eax                                 /* thunk_title_height's dec          */
    mov     dword ptr [{s['g_title_right']:#x}], eax
    mov     eax, dword ptr [{s['g_popup_scale_num']:#x}]
    lea     edx, [eax+eax*2]
    shr     edx, 4                              /* ps3                               */
    sub     eax, 0x10
    sar     eax, 31                             /* title_grow_delta == 0 (2026-09-18: title draws FLAT); shift 31 keeps the byte layout */
    mov     ecx, dword ptr [esi+0x30e8]
    add     ecx, dword ptr [esi+0x30e0]         /* content_top                       */
    lea     edx, [edx+edx*2]
    sub     ecx, edx                            /* - 3*ps3                           */
    sub     ecx, eax
    sub     ecx, eax                            /* - 2*delta                         */
    mov     dword ptr [{s['g_title_bottom']:#x}], ecx
    mov     dword ptr [{s['g_band_popup']:#x}], esi
    popad
    xor     eax, eax
    ret
L_off:
    cmp     esi, dword ptr [{s['g_band_popup']:#x}]
    jne     L_off2
    mov     dword ptr [{s['g_band_popup']:#x}], 0
L_off2:
    xor     eax, eax
L_titled:
    ret
"""


def asm_scale_header(s: dict[str, int]) -> str:
    return f"""
    mov     ecx, dword ptr [esi+0x21b8]
    cmp     dword ptr [esi+0xa48], 0
    jne     L_scale
    cmp     esi, {FACTION_POPUP:#x}
    je      L_done
    push    eax
    mov     eax, dword ptr [esi+0x30ac]
    cmp     eax, 10000
    jb      L_ok                                  /* type 0: CF=1                      */
    sub     eax, 50000
    cmp     eax, 10000                          /* type 5: CF=1                      */
L_ok:
    pop     eax                                 /* flags survive the pop             */
    jae     L_done
L_scale:
    imul    ecx, dword ptr [{s['g_popup_scale_num']:#x}]
    sar     ecx, 4
L_done:
    push    {s['header_reserve_resume']:#x}
    ret
"""


def asm_nestpads(s: dict[str, int]) -> str:
    return f"""
    push    ebx
    mov     ebx, dword ptr [{s['g_popup_scale_num']:#x}]
    cmp     ebx, 0x10
    jg      L_scaled
    mov     ebx, 3
    jmp     L_apply
L_scaled:
    cmp     dword ptr [esi+0x30d4], 0
    je      L_listpad
    cmp     dword ptr [esi+0x2350], -1
    je      L_bodypad
    cmp     dword ptr [esi+0x2144], 0
    je      L_listpad
L_bodypad:
    cmp     esi, dword ptr [{s['g_band_popup']:#x}]     /* keyed flat/slide popup (titled OR untitled) */
    jne     L_nopre
    cmp     dword ptr [{s['g_fp_ornart']:#x}], 0        /* ornate+art: fieldpads already pre-added     */
    jne     L_nopre
    push    eax
    mov     eax, ebx
    sub     eax, 0x10
    sar     eax, 31                             /* title_grow_delta == 0 (2026-09-18: title draws FLAT); shift 31 keeps the byte layout */
    add     dword ptr [{s['g_field_anchor']:#x}], eax
    pop     eax
L_nopre:
    lea     ebx, [ebx+ebx*2]
    shr     ebx, 4                              /* popup_pad(3, g)                   */
    jmp     L_apply
L_listpad:
    add     ebx, ebx
    add     ebx, 7
    shr     ebx, 4                              /* scale_px(2, g)  (v2, unchanged)   */
L_apply:
    sub     eax, ebx
    add     ecx, ebx
    mov     dword ptr [ebp-0x24], eax
    sub     edx, ebx
    add     edi, ebx
    pop     ebx
    ret
"""


def asm_backdrop_railtrim(s: dict[str, int]) -> str:
    # 2026-09-18 (law popup_backdrop_draw_right).  Call-redirect target of the d690 backdrop draw @0x405F77, in
    # front of thunk_tutwin_backdrop.  ecx=dest, [esp+4]=&rect (the DRAW copy [ebp-0x14..-8]), [esp+8]=params;
    # ebx=&window rect [esi+0x474] (live since 0x405eeb).  eax/edx are dead at the call.
    return f"""
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 0x10
    jle     L_tail
    mov     eax, [esp+4]
    mov     edx, [eax+8]
    cmp     edx, [ebx+8]
    je      L_tail
    dec     dword ptr [eax+8]
L_tail:
    push    {s['thunk_tutwin_backdrop']:#x}
    ret
"""


THUNKS = [("thunk_untitled_stash", asm_untitled_stash),
          ("thunk_scale_header", asm_scale_header),
          ("thunk_popup_nestpads", asm_nestpads),
          ("thunk_backdrop_railtrim", asm_backdrop_railtrim)]

_ks = Ks(KS_ARCH_X86, KS_MODE_32)
_cs = Cs(CS_ARCH_X86, CS_MODE_32)
_cs.detail = True


def _clean(asm: str) -> str:
    out = []
    for ln in asm.splitlines():
        ln = ln.split("/*", 1)[0].rstrip()
        if ln.strip():
            out.append(ln)
    return "\n".join(out)


def assemble_all() -> dict[str, tuple[int, bytes]]:
    s = sym_vas()
    layout: dict[str, tuple[int, bytes]] = {}
    off = SLOT_START
    for name, fn in THUNKS:
        enc, _ = _ks.asm(_clean(fn(s)), PCAVE2 + off)
        b = bytes(enc)
        assert sum(i.size for i in _cs.disasm(b, PCAVE2 + off)) == len(b), "capstone round-trip gap"
        layout[name] = (off, b)
        off = (off + len(b) + 15) & ~15
    assert off <= SLOT_END, f"code {off:#x} overruns the slot"
    return layout


def templatize(b: bytes, va: int) -> str:
    """yaml hex with {abs32:}/{rel32:} placeholders; branch operands stay literal
    (capstone reports them ABSOLUTE -- memory feedback-templatize-branch-operands)."""
    syms = {v: k for k, v in sym_vas().items()}
    out: list[str] = []
    for ins in _cs.disasm(b, va):
        raw = bytearray(ins.bytes)
        repl: list[tuple[int, str]] = []
        if ins.mnemonic == "call" and ins.size == 5 and ins.operands[0].type == X86_OP_IMM:
            tgt = ins.operands[0].imm & 0xFFFFFFFF
            assert tgt in syms, f"call to unknown VA {tgt:#x}"
            repl.append((1, "{rel32:" + syms[tgt] + "}"))
        elif ins.mnemonic.startswith("j") or ins.mnemonic == "call":
            pass
        else:
            for op in ins.operands:
                if op.type == X86_OP_IMM and ins.imm_size == 4 and (op.imm & 0xFFFFFFFF) in syms:
                    repl.append((ins.imm_offset, "{abs32:" + syms[op.imm & 0xFFFFFFFF] + "}"))
                elif (op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0
                      and (op.mem.disp & 0xFFFFFFFF) in syms):
                    repl.append((ins.disp_offset, "{abs32:" + syms[op.mem.disp & 0xFFFFFFFF] + "}"))
        pos = 0
        for o, tok in sorted(repl):
            out.extend(f"{x:02X}" for x in raw[pos:o])
            out.append(tok)
            pos = o + 4
        out.extend(f"{x:02X}" for x in raw[pos:])
    return " ".join(out)


def templates() -> dict[str, tuple[int, str, int]]:
    return {n: (o, templatize(b, PCAVE2 + o), len(b)) for n, (o, b) in assemble_all().items()}


def main() -> int:
    for name, (off, tpl, n) in templates().items():
        print(f"{name}  offset {off:#x}  {n} bytes")
        print(f'        bytes: "{tpl}"')
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
