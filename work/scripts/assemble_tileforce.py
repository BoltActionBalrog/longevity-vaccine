#!/usr/bin/env python
"""Assembler for the console 1:1-tile restripe (group console_tile_stripes), 2026-10-04.

Above native scale (g = g_popup_scale_num > 16) every chrome stripe field follows the one stripe law
(scaling_laws.stripe_rows / stripe_period / stripe_top, per pixel scaling_laws.pair_remap_pixel).  Two
surfaces are still tiled 1:1 from a native 1-row dither texture with no restripe afterwards:

  (1) the console backdrop texture (pair 0xC6/0x41): six Buffer_tile calls of the 24x24 tile
      [0x78D6B0] into the MainWin strip canvas 0x7AEC64 -- MainWin_tile_panels x4, BaseWin_draw_garrison,
      DesignWin_draw_slot_strip;
  (2) the HUD centre message panel (pair 0xC4/0x41): MessageWin_draw_bg's Buffer_box_sprite(d7f8), whose
      fill cell tiles 1:1 (the ListBox background callback, also run per row under a one-row clip).

Thunks (pcave2, one block):
  t_tile_force    drop-in for Buffer_tile   thiscall(ecx=dest)(src, phaseX, phaseY, dstX, dstY, w, h) RET 0x1C
  t_msg_bgforce   drop-in for Buffer_box_sprite thiscall(ecx=dest)(RECT* half-open l,t,r,b; params) RET 8
  t_tf_restripe   shared tail: thiscall(ecx=dest)(l, t, r, b) RET 0x10; preserves eax/ebx/esi/edi/ebp
Both drop-ins: g <= 16 -> `push native / ret` with the stack and every register untouched (native no-op);
else the native callee runs with the same args, then t_tf_restripe intersects the drawn rect with the dest
buffer's clip (+0x20..+0x2C), stages it into g_fe_dst/x/y/w/h, sets g_rm_force and calls thunk_fe_pair_remap.

Why the rect is clipped HERE and not left to fe's own clamp: fe clamps its WALK to the clip, but its force
prescan (the content key: colored member > w/2 over <= 8 rows) reads the first rows of the STAGED rect whether
or not they are inside the clip.  The message-panel callback redraws the whole window rect under a one-row
clip, so the unclipped prescan would key on rows this draw never touched.  Staging rect & clip makes the
prescan read exactly the pixels the native callee just wrote; the stripe phase is the dest-buffer row
(y mod P), so moving the staged origin does not move the pattern.

Why thunk_fe_pair_remap and not thunk_s54_restripe (the entry thunk_box_thick_devfill STEP3 calls): s54 is
fe + a second, mate-keyed pass for the 0x54/0x41 and 0xC2/0x41 hatches of popup/report masks.  Both fields
here are fe's own content-keyed families (backdrop C6/41, navy C4/41), so the extra pass can only ever be a
no-op or a false positive on console art; t_rwk_boxforce (same canvas, same C6/41 field) is the precedent.

Parity: tests/test_tileforce_asm_parity.py (Unicorn, these bytes + the assembled thunk_fe_pair_remap vs
scaling_laws.pair_remap_pixel).  Fragments: `py assemble_tileforce.py --fragments`.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402
import assemble_list_face_phase as LFP  # noqa: E402

PCAVE2 = 0x00A0C000
assert PCAVE2 == SE.PCAVE2
GROUP = "console_tile_stripes"

# Block placement (cave_map.py 2026-10-04): the free run 0x278F7..0x27E00 between thunk_art_reblit_body
# (ends 0x278F7) and g_dl_exec (0x27E00).  Started at 0x27A00, not 0x27900, to leave thunk_art_reblit_body
# 265 B of growth.  No free run at or above 0x2D700 holds the block (largest there: 0x2DF5E..0x2E000, 162 B).
OFF_CODE = 0x27A00
OFF_LIMIT = 0x27E00

# ---- engine VAs (verified against assemble_dl.py / assemble_se.py / assemble_rw_kinds.py and patches.yaml) ----
G = 0x00668740                 # g_popup_scale_num
BUFFER_TILE = 0x005DA860       # thiscall(dest; src, phaseX, phaseY, dstX, dstY, w, h) RET 0x1C
BOX_SPRITE = 0x005E2DD3        # thiscall(dest; RECT*, params) RET 8
assert BOX_SPRITE == SE.BOX_SPRITE and G == SE.G

# Buffer fields: clip RECT +0x20 (l) +0x24 (t) +0x28 (r) +0x2C (b), data +0x54
SYM_NAMES = ("g_popup_scale_num", "Buffer_tile", "Buffer_box_sprite", "thunk_fe_pair_remap",
             "g_fe_dst", "g_fe_x", "g_fe_y", "g_fe_w", "g_fe_h", "g_rm_force",
             "g_faction_active", "t_fac_item_pre", "t_fac_rowpost")
LB_DRAW_ITEM = 0x0060B530      # ListBox_draw_item: thiscall(list part; item) RET 4 (entry = the baked filedlg detour)


def load_syms(patches: Path | None = None) -> dict[str, int]:
    """Every referenced symbol's VA from patches.yaml (the patcher's own loader)."""
    _sites, _groups, caves, symbols = ap.load_patches(Path(patches or ap.DEFAULT_PATCHES))
    s2v = ap.build_symbol_table(symbols, caves)
    out = {n: s2v[n] for n in SYM_NAMES}
    assert out["g_popup_scale_num"] == G and out["Buffer_tile"] == BUFFER_TILE and out["Buffer_box_sprite"] == BOX_SPRITE
    cave = next(c for c in caves if c["id"] == "pcave2")
    assert int(cave["virtual_addr"]) == PCAVE2
    return out


# ---- asm ----------------------------------------------------------------------------------------------------
# NO comments inside the asm text (keystone hangs on `;`); the notes live here.
#
# t_tile_force.  Entry stack: [esp] ret, +4 src, +8 phaseX, +0xC phaseY, +0x10 dstX, +0x14 dstY, +0x18 w,
# +0x1C h.  After `push esi` every arg is 4 higher, so seven `push [esp+0x20]` re-push h, w, dstY, dstX,
# phaseY, phaseX, src.  Buffer_tile pops them (RET 0x1C) and leaves the dest clip as it found it.  Then, with
# [esp] = saved esi: b = dstY + h and r = dstX + w are both `[esp+0x18] + [esp+0x20]` (one push between them),
# t and l are both `[esp+0x20]` (two / three pushes down).  eax (Buffer_tile's result) is never written here
# and t_tf_restripe preserves it.
def asm_tile_force(s: dict[str, int], restripe_va: int) -> str:
    return f"""
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      scaled
    push    {s['Buffer_tile']:#x}
    ret
scaled:
    push    esi
    mov     esi, ecx
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    mov     ecx, esi
    call    {s['Buffer_tile']:#x}
    mov     edx, dword ptr [esp+0x18]
    add     edx, dword ptr [esp+0x20]
    push    edx
    mov     edx, dword ptr [esp+0x18]
    add     edx, dword ptr [esp+0x20]
    push    edx
    push    dword ptr [esp+0x20]
    push    dword ptr [esp+0x20]
    mov     ecx, esi
    call    {restripe_va:#x}
    pop     esi
    ret     0x1C
"""


# t_msg_bgforce.  Entry stack: [esp] ret, +4 RECT*, +8 params.  The rect is COPIED to the stack before the
# native call (b, r, t, l pushed -> [esp] l, +4 t, +8 r, +0xC b): the copy is both the record of what the
# native box was asked to draw (no assumption that the callee leaves the caller's RECT alone) and, untouched
# by the RET 8 callee, the four stack args of t_tf_restripe.  params: +8 at entry, +0xC after `push esi`,
# +0x1C after the four rect pushes.  Unlike t_rwk_boxforce there is no dec/inc of R/B: this dest takes the
# real half-open native box, so the restriped rect is [l, r) x [t, b) as passed.
def asm_msg_bgforce(s: dict[str, int], restripe_va: int) -> str:
    return f"""
    cmp     dword ptr [{s['g_popup_scale_num']:#x}], 16
    jg      scaled
    push    {s['Buffer_box_sprite']:#x}
    ret
scaled:
    push    esi
    mov     esi, ecx
    mov     eax, dword ptr [esp+8]
    push    dword ptr [eax+0xC]
    push    dword ptr [eax+8]
    push    dword ptr [eax+4]
    push    dword ptr [eax]
    push    dword ptr [esp+0x1C]
    push    eax
    mov     ecx, esi
    call    {s['Buffer_box_sprite']:#x}
    mov     ecx, esi
    call    {restripe_va:#x}
    pop     esi
    ret     8
"""


# t_tf_restripe: thiscall(ecx = dest Buffer*)(l, t, r, b) RET 0x10.  After `push eax`: l +8, t +0xC, r +0x10,
# b +0x14.  No pixel data (+0x54 == 0: Buffer_tile's own "nothing to draw into" case) or an empty rect & clip
# -> nothing staged, g_rm_force never set (a set-but-unconsumed flag would hijack the next frame_enlarge).
# Only reached under g > 16 (fe's g <= 16 early-out would otherwise leave the flag set).
def asm_tf_restripe(s: dict[str, int]) -> str:
    return f"""
    push    eax
    cmp     dword ptr [ecx+0x54], 0
    je      out
    mov     eax, dword ptr [esp+8]
    cmp     eax, dword ptr [ecx+0x20]
    jge     xl
    mov     eax, dword ptr [ecx+0x20]
xl:
    mov     edx, dword ptr [esp+0x10]
    cmp     edx, dword ptr [ecx+0x28]
    jle     xr
    mov     edx, dword ptr [ecx+0x28]
xr:
    sub     edx, eax
    jle     out
    mov     dword ptr [{s['g_fe_x']:#x}], eax
    mov     dword ptr [{s['g_fe_w']:#x}], edx
    mov     eax, dword ptr [esp+0xC]
    cmp     eax, dword ptr [ecx+0x24]
    jge     yt
    mov     eax, dword ptr [ecx+0x24]
yt:
    mov     edx, dword ptr [esp+0x14]
    cmp     edx, dword ptr [ecx+0x2C]
    jle     yb
    mov     edx, dword ptr [ecx+0x2C]
yb:
    sub     edx, eax
    jle     out
    mov     dword ptr [{s['g_fe_y']:#x}], eax
    mov     dword ptr [{s['g_fe_h']:#x}], edx
    mov     dword ptr [{s['g_fe_dst']:#x}], ecx
    mov     dword ptr [{s['g_rm_force']:#x}], 1
    call    {s['thunk_fe_pair_remap']:#x}
out:
    pop     eax
    ret     0x10
"""


def asm_lb_item_stripes(s: dict[str, int], restripe_va: int) -> str:
    """ListBox_draw_item drop-in at its seven call sites (thiscall ecx = list part, [esp+4] = item, RET 4).
    The faction picker's name list is a ListBox whose row background is painted by its parent's
    item-back-draw virtual at device density from the native 1-row AE/EE (selected: E0/E1) dither, and no
    restripe ever ran (trace frida_faction_rows_20261005T055551: listbox canvas 1065x325 @4K, rows 1/1, the
    C6/41 gaps already 2/2).  While g_faction_active and g > 16: draw the item natively, then restripe the
    list canvas (list part + [vtbl+4] + 0x444; W +0x80, H +0x84 stored negative) through t_tf_restripe,
    which clips to the canvas clip -- the item rect draw_item just set.  Otherwise the native callee,
    untouched: every other ListBox in the game keeps its own path.  2026-10-14: the restripe call goes through
    t_lbi_restripe_ph (assemble_list_face_phase.py), which stages the canvas's parent-local top in g_rm_yph so
    the rows sit on FactionPickWin's grid (law faction_list_stripe_phase); restripe_va is that wrapper's VA.
    2026-10-25 W2D F40b (assemble_edge_stroke.py, law faction_row_face): the draw_item call enters t_fac_item_pre
    (clears g_fr_pending, then jmp ListBox_draw_item) and the restripe call t_fac_rowpost (the corner background
    back, t_lbi_restripe_ph = restripe_va, then the name row's K hover bands under the text ink) -- both same-size
    CALLs; the native tail below is unchanged."""
    return f"""
    cmp dword ptr [{s['g_faction_active']:#x}], 0
    je native
    cmp dword ptr [{G:#x}], 16
    jle native
    push esi
    mov esi, ecx
    push dword ptr [esp+8]
    call {s['t_fac_item_pre']:#x}
    mov eax, dword ptr [esi]
    mov eax, dword ptr [eax+4]
    lea ecx, [esi+eax+0x444]
    mov eax, dword ptr [ecx+0x84]
    test eax, eax
    jns hpos
    neg eax
hpos:
    push eax
    push dword ptr [ecx+0x80]
    push 0
    push 0
    call {s['t_fac_rowpost']:#x}
    pop esi
    ret 4
native:
    push {LB_DRAW_ITEM:#x}
    ret
"""


THUNK_ORDER = ("t_tile_force", "t_msg_bgforce", "t_tf_restripe", "t_lb_item_stripes")
THUNK_NOTE = {
    "t_tile_force": "Buffer_tile drop-in (RET 0x1C): g<=16 native; else tile, then force-restripe the tiled rect",
    "t_msg_bgforce": "Buffer_box_sprite drop-in (RET 8): g<=16 native; else box, then force-restripe its half-open rect",
    "t_tf_restripe": "shared tail thiscall(dest)(l,t,r,b) RET 0x10: rect & clip -> g_fe_*, g_rm_force, thunk_fe_pair_remap",
    "t_lb_item_stripes": "ListBox_draw_item drop-in (RET 4): faction picker only (g_faction_active, g>16) -> draw the item, then restripe the list canvas inside its clip",
}


def _align(v: int, a: int = 16) -> int:
    return (v + a - 1) & ~(a - 1)


def assemble_all(syms: dict[str, int] | None = None, off_code: int = OFF_CODE) -> dict[str, tuple[int, bytes]]:
    """{name: (pcave2 offset, bytes)}.  Two passes: the drop-ins call t_tf_restripe, laid out after them."""
    s = syms or load_syms()
    restripe_va = PCAVE2 + off_code
    layout: dict[str, tuple[int, bytes]] = {}
    for _pass in range(4):
        off = off_code
        new: dict[str, tuple[int, bytes]] = {}
        for name in THUNK_ORDER:
            va = PCAVE2 + off
            src = {"t_tile_force": lambda: asm_tile_force(s, restripe_va),
                   "t_msg_bgforce": lambda: asm_msg_bgforce(s, restripe_va),
                   "t_tf_restripe": lambda: asm_tf_restripe(s),
                   "t_lb_item_stripes": lambda: asm_lb_item_stripes(s, LFP.VA_LBI)}[name]()
            assert ";" not in src
            new[name] = (off, SE.assemble(src, va))
            off = _align(off + len(new[name][1]))
        stable = new == layout and restripe_va == PCAVE2 + new["t_tf_restripe"][0]
        layout, restripe_va = new, PCAVE2 + new["t_tf_restripe"][0]
        if stable:
            return layout
    raise RuntimeError("layout did not converge")


def names_of(layout) -> dict[str, int]:
    return {**{n: PCAVE2 + o for n, (o, _) in layout.items()}, "t_lbi_restripe_ph": LFP.VA_LBI}


def templatize(b: bytes, va: int, syms: dict[str, int], names: dict[str, int]) -> str:
    """yaml hex with {abs32:}/{rel32:} for every operand that is a known symbol VA (SE.templatize: capstone
    operand inspection; calls -> rel32, data/imm operands -> abs32; there are no literal cross-thunk jumps)."""
    table = {v: n for n, v in syms.items()}
    table.update({v: n for n, v in names.items()})
    return SE.templatize(b, va, table)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ---- sites ------------------------------------------------------------------------------------------------------
# (id, function, call VA, native target, thunk, original bytes, note)
TILE_NOTE = "call Buffer_tile (24x24 console backdrop tile [0x78D6B0] 1:1 into the strip canvas) -> tile, then C6/41 law stripes"
SITES = [
    ("MainWin_tile_panels.tile_d80", "MainWin_tile_panels", 0x45C2DA, BUFFER_TILE, "t_tile_force", "E8 81 E5 17 00", TILE_NOTE),
    ("MainWin_tile_panels.tile_centre", "MainWin_tile_panels", 0x45C31A, BUFFER_TILE, "t_tile_force", "E8 41 E5 17 00", TILE_NOTE),
    ("MainWin_tile_panels.tile_side", "MainWin_tile_panels", 0x45C358, BUFFER_TILE, "t_tile_force", "E8 03 E5 17 00", TILE_NOTE),
    ("MainWin_tile_panels.tile_d90", "MainWin_tile_panels", 0x45C388, BUFFER_TILE, "t_tile_force", "E8 D3 E4 17 00", TILE_NOTE),
    ("BaseWin_draw_garrison.console_tile", "BaseWin_draw_garrison", 0x410490, BUFFER_TILE, "t_tile_force", "E8 CB A3 1C 00", TILE_NOTE),
    ("DesignWin_draw_slot_strip.console_tile", "DesignWin_draw_slot_strip", 0x43D592, BUFFER_TILE, "t_tile_force", "E8 C9 D2 19 00", TILE_NOTE),
    ("MessageWin_draw_bg.box_d7f8", "MessageWin_draw_bg", 0x471FB3, BOX_SPRITE, "t_msg_bgforce", "E8 1B 0E 17 00",
     "call Buffer_box_sprite (d7f8 filled box, fill cell tiled 1:1) -> box, then C4/41 law stripes inside the clip"),
] + [
    (f"{fn}.draw_item_{va:x}", fn, va, LB_DRAW_ITEM, "t_lb_item_stripes", oh,
     "call ListBox_draw_item -> the same, then (faction picker only) the item's rows restriped to the stripe law")
    for fn, va, oh in (("ListBox_on_key_down", 0x60B2FF, "E8 2C 02 00 00"), ("ListBox_on_key_down", 0x60B32C, "E8 FF 01 00 00"),
                       ("ListBox_on_mouse_move", 0x60CDC2, "E8 69 E7 FF FF"), ("ListBox_on_mouse_move", 0x60CDEF, "E8 3C E7 FF FF"),
                       ("ListBox_on_redraw", 0x60C577, "E8 B4 EF FF FF"), ("ListBox_on_scrolling", 0x60C663, "E8 C8 EE FF FF"),
                       ("ListBox_on_scrolling", 0x60C677, "E8 B4 EE FF FF"))
]
RATIONALE = ("Above native scale the surface is tiled 1:1 from a native 1-row dither and nothing restripes it; the drop-in runs "
             "the native call unchanged, then thunk_fe_pair_remap's force path over the drawn rect (clipped to the dest clip) "
             "rewrites the pair to the stripe law on the dest canvas's own row grid. g<=16: tail-jump to the native callee.")


def site_list() -> list[dict]:
    out = []
    for sid, fn, va, target, thunk, orig_hex, note in SITES:
        orig = bytes([0xE8]) + struct.pack("<i", target - (va + 5))
        assert hx(orig) == orig_hex, (sid, hx(orig), orig_hex)      # the E8 really targets the native callee
        out.append({"id": sid, "function": fn, "va": va, "orig": orig, "thunk": thunk, "note": note})
    return out


def verify_live(sites) -> list[str]:
    """Every site's original bytes must be what the PRISTINE base (.bak) holds."""
    out = []
    for s in sites:
        got = SE.base_exe_bytes(s["va"], len(s["orig"]))
        if got != s["orig"]:
            out.append(f"{s['id']} @{s['va']:#x}: base {hx(got)} != expected {hx(s['orig'])}")
    return out


def site_yaml(sites) -> str:
    out = []
    for s in sites:
        out.append(f"""  - id: {s['id']}
    status: confirmed
    group: {GROUP}
    function: {s['function']}
    virtual_addr: {s['va']:#010x}
    length: 5
    original_bytes: "{hx(s['orig'])}"   # {s['note']}
    new_bytes:      "E8 {{rel32:{s['thunk']}}}"
    pattern: call_target_redirect
    rationale: "{RATIONALE}"
""")
    return "\n".join(out)


def roundtrip_problems(layout, syms) -> list[str]:
    """The emitted templates, resolved by the patcher's own ByteTemplate, must reproduce the assembled bytes."""
    names = names_of(layout)
    table = dict(syms)
    table.update(names)
    out = []
    for name, (off, b) in layout.items():
        tpl = templatize(b, PCAVE2 + off, syms, names)
        got = ap.ByteTemplate(tpl).resolve(PCAVE2 + off, table)
        if bytes(got) != b:
            out.append(f"{name}: template does not round-trip")
        for lit in (syms[n] for n in SYM_NAMES):
            if struct.pack("<I", lit).hex().upper() in tpl.replace(" ", ""):
                out.append(f"{name}: literal {lit:#x} left untemplatized")
    return out


def main(argv) -> int:
    syms = load_syms()
    layout = assemble_all(syms)
    names = names_of(layout)
    ok = True
    end = max(o + len(b) for o, b in layout.values())
    print("; ==== console 1:1-tile restripe (assemble_tileforce.py) ====")
    print(f"; block {OFF_CODE:#x}..{end:#x} ({end - OFF_CODE}B); limit {OFF_LIMIT:#x}")
    if end > OFF_LIMIT:
        ok = False
        print("; OVERFLOW past the gap")
    sym_lines, content_lines = [], []
    for name in THUNK_ORDER:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {GROUP} ({len(b)}B) {THUNK_NOTE[name]}")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, syms, names)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    for p in roundtrip_problems(layout, syms):
        ok = False
        print("; TEMPLATE:", p)
    sites = site_list()
    for p in verify_live(sites):
        ok = False
        print("; LIVE MISMATCH:", p)
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag, "_fragment_tileforce_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_tileforce_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_tileforce_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(site_yaml(sites))
        print("; fragments written to work/patches/_fragment_tileforce_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print(site_yaml(sites))
    print(f"; group {GROUP}: members = {[s['id'] for s in sites]}, code_caves = ['pcave2']")
    print(f"; sites: {len(sites)}")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
