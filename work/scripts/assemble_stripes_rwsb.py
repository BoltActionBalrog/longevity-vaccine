#!/usr/bin/env python
"""Assembler for the HQ energy report's OWN list scrollbar (group report_energy_list_bar), 2026-10-05.

THE BAR.  The energy/budget report (g_reportwin_kind 3, painter ReportWin_draw_energy 0x49BCD0) builds, on
every repaint with a base or facility selected, the ListBox ReportWin+0x5A0C in the right column
(ListBox_close 0x49CC46 / Dialog_init_3 0x49CC58 / ListBox_item xN / ListBox_attach(ReportWin, x, y,
0x81020) 0x49D450 / set_selected_id 0x49D45C / show 0x49D477).  Its scrollbar is the Win layer's HEAP V bar
(Win_create_scrollbars 0x5EC3AB..0x5EC427 -> ScrollBar_init_v, parent = the list's Win part
ReportWin+0x5A54), kept in that Win's scroll_vert field: the STATIC cell 0x87C308
(= 0x876478 + 0x5A0C + 0x48 + 0x43C), nulled again by the Win close (0x5EB75A).

THE DEFECT.  Nothing scales it.  The list is built outside the console-list bracket (g_rw_inlist == 0,
g_scrollbar_w == 20 native) and outside every popup / file-dialog gate (thunk_list_gate), so the bar is
20 px wide at every resolution (18-px art measured at 1600x900, 1920x1080 and 1600x1200), no cell ever
holds its pointer (t_rw_sbinit stashes only under g_rw_inlist, thunk_dw_sbv only under thunk_list_gate),
thunk_pref_sbzoom therefore draws it through the native ScrollBar_draw and t_rw_sbarrows refuses its arrows:
native grip, native chevrons, native 1-row F0/B9 + C2/C5 dither at every g.

THE FIX reuses the console-list recipe (t_rw_scrollsmall .. t_rw_scrollnormal) and the existing art path:

  t_rwsb_begin   CALL redirect @0x49CC58 (call Dialog_init_3).  g > 16, no console bracket open, no
                 popup / file-dialog gate: g_scrollbar_w <- floor(g_scrollbar_w * g / 16) (law
                 scaling_laws.listbox_bar_reserve: the same heap V bar as the popup lists and the main-menu
                 LOAD list), the live value saved in g_rwsb_sbw.  Then Dialog_init_3 by tail-jump: stack and
                 every register untouched on every path.  The bracket spans the ListBox_item wrap budget
                 (0x60C938), calc_dims, GraphicWin_init, Win_create_scrollbars and ScrollBar_init_v, exactly
                 like the console lists' own bracket.
  t_rwsb_end     CALL helper @0x49D475 (`mov ecx,esi / call [eax+4]`, 5 B, the list window's show = the
                 painter's last call).  Runs the two instructions with the caller's stack (its own return
                 address dropped first, so the callee sees the pushed arg exactly where vanilla put it),
                 then restores g_scrollbar_w from g_rwsb_sbw and resumes at 0x49D47A.  One site only, so the
                 resume address is a constant: nothing is carried in a cell across the callee.
  g_rwsb_sbw     the saved live width; 0 = no bracket open (also the nesting guard).

and two EDITS to existing thunks, emitted here as ready-to-paste templates (this module never writes them):

  thunk_pref_sbzoom v10   + `cmp ecx,[0x87C308] / je go` (8 B): the bar joins the armed draw
                          (g_netwin_active bracket = thunk_sb_thumb grip zoom + btn_gate netwin branch for the
                          arrows, then thunk_sb_restripe: F0/B9 one-shot + keyed trough families).
  t_rw_sbarrows v3        + `mov eax,esi / sub eax,[0x87C308] / cmp eax,0xAAC / je hit / cmp eax,0x15F8 /
                          je hit` (22 B, fills the slot to 0xCA00 exactly): the two arrow FlatButtons are
                          admitted to the zoom on hover / pressed redraws (thunk_btn_gate_pre) and to the
                          F0 one-shot + thunk_sbarrow_bg + thunk_ed_remap restripe (thunk_btn_stripes).

Stateless on purpose: the admission compares against the Win's own scroll_vert field, which the engine nulls
when the list window closes, so there is no stash, no stale heap pointer and no single-owner cell to lose
(the g_rail_sb / g_rw_sb history).  A null field never matches: ecx is a live object, and esi - 0 is never
0xAAC / 0x15F8.

g <= 16: t_rwsb_begin changes nothing (so t_rwsb_end restores nothing); the two edited thunks only add an
admission whose consumers (thunk_sb_thumb, thunk_btn_shrink, thunk_sb_restripe) are themselves g-gated.

Parity: tests/test_stripes_rwsb_asm_parity.py.  Fragments: `py assemble_stripes_rwsb.py --fragments`.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
assert PCAVE2 == SE.PCAVE2
GROUP = "report_energy_list_bar"

# Block placement (cave_map.py --min-gap 0x60, 2026-10-05): the free run 0xF794..0xF8F0 (348 B) between
# thunk_hollow_keyint (ends 0xF794) and thunk_pf_frame_align (starts 0xF8F0).
OFF_CODE = 0xF7A0
OFF_LIMIT = 0xF8F0

G = 0x00668740                     # g_popup_scale_num
G_SBW = 0x009B8DD4                 # g_scrollbar_w (shared runtime global: read live, never baked)
DIALOG_INIT_3 = 0x00609470         # thiscall(list; RECT*, flags) RET 8
RW = 0x00876478                    # ReportWin_g
G_MODAL_TOP = 0x009B7AE0
RW_ENERGY_LIST = RW + 0x5A0C       # the energy page's ListBox
RW_ENERGY_LISTWIN = RW_ENERGY_LIST + 0x48          # its Win part (canvas = +0x444 = RW+0x5E98, census-measured)
RW_ENERGY_VBAR = RW_ENERGY_LISTWIN + 0x43C         # that Win's scroll_vert: the heap V bar, 0 when closed
assert RW_ENERGY_VBAR == 0x0087C308
ARROW_UP, ARROW_DN = 0xAAC, 0x15F8                 # the two arrow FlatButtons inside a ScrollBar
SITE_BEGIN, SITE_END, END_RESUME = 0x0049CC58, 0x0049D475, 0x0049D47A

SYM_NAMES = ("g_popup_scale_num", "g_scrollbar_w", "g_rw_inlist", "thunk_list_gate", "Dialog_init_3",
             "g_rw_sbs", "g_rw_sbparents", "thunk_pref_sbzoom", "t_rw_sbarrows")
SBZOOM_OFF, SBZOOM_LIMIT = 0x880, 0x940            # thunk_pref_sbzoom slot (next: t_pw_shrink 0x940 -- cave_map, fix 7)
SBARROWS_OFF, SBARROWS_LIMIT = 0xC980, 0xCA00      # t_rw_sbarrows slot (next: thunk_chev_coverage 0xCA00)


def load_patches():
    _sites, _groups, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    return caves, ap.build_symbol_table(symbols, caves)


def load_syms() -> dict[str, int]:
    caves, s2v = load_patches()
    out = {n: s2v[n] for n in SYM_NAMES}
    assert out["g_popup_scale_num"] == G and out["g_scrollbar_w"] == G_SBW and out["Dialog_init_3"] == DIALOG_INIT_3
    assert out["thunk_pref_sbzoom"] == PCAVE2 + SBZOOM_OFF and out["t_rw_sbarrows"] == PCAVE2 + SBARROWS_OFF
    return out


def live_entry(name: str) -> tuple[int, str]:
    """(cave offset, byte template) of a cave contents entry exactly as patches.yaml carries it."""
    caves, _ = load_patches()
    for c in caves:
        for e in c.get("contents") or []:
            if e.get("id") == name:
                return int(e["offset"]), " ".join(str(e["bytes"]).split())
    raise KeyError(name)


# ---- law ---------------------------------------------------------------------------------------------------------
def energy_list_bar_width(sbw: int, g: int) -> int:
    """LAW (to live in scaling_laws.py next to listbox_bar_reserve): the width the energy report's heap V bar is
    built with = the live g_scrollbar_w x g/16, floor, above native scale; the native value at g <= 16.  One
    scale step only: under a popup / file-dialog gate the READERS (thunk_lbres_*) scale and the writer must
    not (shared field, one owner)."""
    return SL.listbox_bar_reserve(sbw, g, popup_active=True)


# ---- new thunks --------------------------------------------------------------------------------------------------
# NO comments inside the asm text (keystone hangs on `;`).
#
# t_rwsb_begin.  Entered by the site's own CALL: [esp] = ret, +4 RECT*, +8 flags, ecx = the list.  Nothing is
# pushed that is not popped before the tail-jump, so Dialog_init_3 sees the site's frame.  eax is saved (the
# site computed nothing in it that survives the call, but the contract here is "every register").
# thunk_list_gate returns ZF=0 iff g_popup_active || g_filedlg_active and preserves every register.
def asm_begin(s: dict[str, int], cell: int) -> str:
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     go
    cmp     dword ptr [{cell:#x}], 0
    jne     go
    cmp     dword ptr [{s['g_rw_inlist']:#x}], 0
    jne     go
    call    {s['thunk_list_gate']:#x}
    jne     go
    push    eax
    mov     eax, dword ptr [{G_SBW:#x}]
    mov     dword ptr [{cell:#x}], eax
    imul    eax, dword ptr [{G:#x}]
    sar     eax, 4
    mov     dword ptr [{G_SBW:#x}], eax
    pop     eax
go:
    jmp     {DIALOG_INIT_3:#x}
"""


# t_rwsb_end.  Entered by `call` from 0x49D475 with [esp] = 0x49D47A, +4 = the arg vanilla pushed at 0x49D463,
# eax = the list Win's vtable, esi = the list Win.  `add esp,4` drops our return address so the virtual sees
# vanilla's stack; it cleans its own arg; we resume at the constant 0x49D47A (pop edi / pop esi / pop ebx /
# mov esp,ebp / pop ebp / ret) with eax as the virtual left it.
def asm_end(cell: int) -> str:
    return f"""
    add     esp, 4
    mov     ecx, esi
    call    dword ptr [eax+4]
    push    eax
    mov     eax, dword ptr [{cell:#x}]
    test    eax, eax
    jz      done
    mov     dword ptr [{G_SBW:#x}], eax
    mov     dword ptr [{cell:#x}], 0
done:
    pop     eax
    push    {END_RESUME:#x}
    ret
"""


THUNK_ORDER = ("t_rwsb_begin", "t_rwsb_end")
THUNK_NOTE = {
    "t_rwsb_begin": "Dialog_init_3 redirect @0x49CC58: g>16, no console bracket, no popup/filedlg gate -> g_scrollbar_w x g/16 (saved in g_rwsb_sbw); tail-jump",
    "t_rwsb_end": "CALL helper @0x49D475 (mov ecx,esi / call [eax+4]): run the show, restore g_scrollbar_w, resume 0x49D47A",
}
CELL_NAME = "g_rwsb_sbw"


def _align(v: int, a: int = 16) -> int:
    return (v + a - 1) & ~(a - 1)


def assemble_all(syms: dict[str, int] | None = None, off_code: int = OFF_CODE):
    """({name: (pcave2 offset, bytes)}, cell offset).  The cell sits after the code, dword-aligned."""
    s = syms or load_syms()
    cell_off = off_code + 0x80
    for _pass in range(3):
        layout, off = {}, off_code
        for name in THUNK_ORDER:
            src = asm_begin(s, PCAVE2 + cell_off) if name == "t_rwsb_begin" else asm_end(PCAVE2 + cell_off)
            assert ";" not in src
            layout[name] = (off, SE.assemble(src, PCAVE2 + off))
            off = _align(off + len(layout[name][1]))
        if off == cell_off:
            return layout, cell_off
        cell_off = off
    raise RuntimeError("layout did not converge")


def names_of(layout, cell_off) -> dict[str, int]:
    out = {n: PCAVE2 + o for n, (o, _) in layout.items()}
    out[CELL_NAME] = PCAVE2 + cell_off
    return out


def templatize(b: bytes, va: int, syms: dict[str, int], names: dict[str, int]) -> str:
    table = {syms[n]: n for n in ("g_popup_scale_num", "g_scrollbar_w", "g_rw_inlist", "thunk_list_gate")}
    table.update({v: n for n, v in names.items()})
    return SE.templatize(b, va, table)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ---- the two edits to existing thunks ----------------------------------------------------------------------------
def sbzoom_text(v10: bool) -> str:
    """thunk_pref_sbzoom as assemble_popup_sb.asm_sbzoom() writes it (v9), optionally with the v10 admission
    inserted as the last test before the native `jmp ScrollBar_draw`."""
    import assemble_popup_sb as PS
    src = PS.asm_sbzoom()
    tail = f"        jmp  {PS.SB_DRAW}\n    go:"
    assert src.count(tail) == 1
    if v10:
        src = src.replace(tail, f"        cmp  ecx, dword ptr [{RW_ENERGY_VBAR}]\n        je   go\n" + tail)
    return src


def sbzoom_template(v10: bool) -> str:
    import assemble_popup_sb as PS
    va = PCAVE2 + SBZOOM_OFF
    return PS.to_template(PS.assemble(sbzoom_text(v10), va), va)


def sbarrows_text(s: dict[str, int], v3: bool) -> str:
    """t_rw_sbarrows (assemble_rw_kinds.asm_rw_sbarrows, v2) with the v3 test for the energy list bar's arrows
    placed first: it needs neither the modal-top gate nor a parent check (the field is the live Win's own)."""
    new = f"""
    mov     eax, esi
    sub     eax, dword ptr [{RW_ENERGY_VBAR:#x}]
    cmp     eax, {ARROW_UP:#x}
    je      hit
    cmp     eax, {ARROW_DN:#x}
    je      hit
""" if v3 else ""
    sbs, par = s["g_rw_sbs"], s["g_rw_sbparents"]
    return f"""
    push    edx
{new}    mov     eax, dword ptr [{G_MODAL_TOP:#x}]
    cmp     eax, {RW:#x}
    jne     miss
    mov     eax, dword ptr [{sbs:#x}]
    test    eax, eax
    jz      slot1
    mov     edx, dword ptr [eax+0xC4]
    cmp     edx, dword ptr [{par:#x}]
    jne     slot1
    add     eax, 0xAAC
    cmp     esi, eax
    je      hit
    add     eax, 0xB4C
    cmp     esi, eax
    je      hit
slot1:
    mov     eax, dword ptr [{sbs + 4:#x}]
    test    eax, eax
    jz      miss
    mov     edx, dword ptr [eax+0xC4]
    cmp     edx, dword ptr [{par + 4:#x}]
    jne     miss
    add     eax, 0xAAC
    cmp     esi, eax
    je      hit
    add     eax, 0xB4C
    cmp     esi, eax
    je      hit
miss:
    xor     eax, eax
    pop     edx
    ret
hit:
    mov     eax, 1
    pop     edx
    ret
"""


def sbarrows_bytes(s: dict[str, int], v3: bool) -> bytes:
    return SE.assemble(sbarrows_text(s, v3), PCAVE2 + SBARROWS_OFF)


def sbarrows_template(s: dict[str, int], v3: bool) -> str:
    b = sbarrows_bytes(s, v3)
    out = hx(b)
    for name in ("g_rw_sbs", "g_rw_sbparents"):               # the live entry's own token convention (slot 0 only)
        lit = hx(struct.pack("<I", s[name]))
        assert out.count(lit) == 1, name
        out = out.replace(lit, "{abs32:" + name + "}")
    return out


def resolve(tpl: str, va: int, s2v: dict[str, int]) -> bytes:
    return bytes(ap.ByteTemplate(tpl).resolve(va, s2v))


def edits(syms: dict[str, int] | None = None) -> list[dict]:
    """The two in-place edits: name, slot, old/new template, anchor check (old == the live yaml entry)."""
    s = syms or load_syms()
    _caves, s2v = load_patches()
    out = []
    for name, off, limit, old, new in (
            ("thunk_pref_sbzoom", SBZOOM_OFF, SBZOOM_LIMIT, sbzoom_template(False), sbzoom_template(True)),
            ("t_rw_sbarrows", SBARROWS_OFF, SBARROWS_LIMIT, sbarrows_template(s, False), sbarrows_template(s, True))):
        live_off, live = live_entry(name)
        va = PCAVE2 + off
        old_b, new_b, live_b = resolve(old, va, s2v), resolve(new, va, s2v), resolve(live, va, s2v)
        out.append({"name": name, "off": off, "limit": limit, "old": old, "new": new, "live": live,
                    "old_len": len(old_b), "new_len": len(new_b), "new_bytes": new_b, "old_bytes": old_b,
                    "anchor_ok": live_off == off and live_b == old_b, "applied": live_b == new_b,
                    "fits": off + len(new_b) <= limit})
    return out


# ---- sites -------------------------------------------------------------------------------------------------------
RATIONALE = ("The energy report's own list builds the Win layer's heap V scrollbar outside every scale gate (no console "
             "bracket, no popup / file-dialog gate): 20 px wide with native art at every resolution. The pair brackets the "
             "list build with g_scrollbar_w x g/16 (law listbox_bar_reserve), exactly like the console lists' "
             "scroll_small .. scroll_normal bracket; g<=16 and gated contexts are untouched.")


def site_list() -> list[dict]:
    begin = bytes([0xE8]) + struct.pack("<i", DIALOG_INIT_3 - (SITE_BEGIN + 5))
    assert hx(begin) == "E8 13 C8 16 00"
    return [
        {"id": "ReportWin_draw_energy.list_bar_begin", "function": "ReportWin_draw_energy", "va": SITE_BEGIN, "orig": begin,
         "thunk": "t_rwsb_begin", "pattern": "call_target_redirect",
         "note": "call Dialog_init_3 (the energy list's rect) -> open the bar-width bracket, then the same call"},
        {"id": "ReportWin_draw_energy.list_bar_end", "function": "ReportWin_draw_energy", "va": SITE_END,
         "orig": bytes.fromhex("8BCEFF5004"), "thunk": "t_rwsb_end", "pattern": "call_helper",
         "note": "mov ecx,esi / call [eax+4] (show the list window, the painter's last call) -> the same, then close the bracket; resumes 0x49D47A"},
    ]


def verify_live(sites) -> list[str]:
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
    pattern: {s['pattern']}
    rationale: "{RATIONALE}"
""")
    return "\n".join(out)


def roundtrip_problems(layout, cell_off, syms) -> list[str]:
    names = names_of(layout, cell_off)
    table = dict(syms)
    table.update(names)
    out = []
    for name, (off, b) in layout.items():
        tpl = templatize(b, PCAVE2 + off, syms, names)
        if resolve(tpl, PCAVE2 + off, table) != b:
            out.append(f"{name}: template does not round-trip")
        for lit in (syms["g_popup_scale_num"], syms["g_scrollbar_w"], syms["g_rw_inlist"], names[CELL_NAME]):
            if struct.pack("<I", lit).hex().upper() in tpl.replace(" ", ""):
                out.append(f"{name}: literal {lit:#x} left untemplatized")
    return out


def main(argv) -> int:
    syms = load_syms()
    layout, cell_off = assemble_all(syms)
    names = names_of(layout, cell_off)
    ok = True
    end = cell_off + 4
    print("; ==== HQ energy report: own list scrollbar (assemble_stripes_rwsb.py) ====")
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
    sym_lines.append(f"  {CELL_NAME + ':':<31}{{ cave: pcave2, offset: {cell_off:#x}, size: 4 }}   # {GROUP}: the live g_scrollbar_w saved by t_rwsb_begin; 0 = no bracket open")
    print(f"; {CELL_NAME} @{cell_off:#x} (4B, zero padding)")
    for p in roundtrip_problems(layout, cell_off, syms):
        ok = False
        print("; TEMPLATE:", p)
    sites = site_list()
    for p in verify_live(sites):
        ok = False
        print("; LIVE MISMATCH:", p)
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag, "_fragment_stripes_rwsb_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_stripes_rwsb_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_stripes_rwsb_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(site_yaml(sites))
        print("; fragments written to work/patches/_fragment_stripes_rwsb_*.yaml")
    else:
        print("\n".join(sym_lines))
        print("\n".join(content_lines))
        print(site_yaml(sites))
    print(f"; group {GROUP}: members = {[s['id'] for s in sites]}, code_caves = ['pcave2']")
    print("; ---- EDITS to existing cave entries (apply by hand; this script does not write them) ----")
    for e in edits(syms):
        state = "ALREADY APPLIED" if e["applied"] else ("anchor OK (old == live yaml)" if e["anchor_ok"] else "ANCHOR MISMATCH")
        if not (e["applied"] or e["anchor_ok"]) or not e["fits"]:
            ok = False
        print(f"; {e['name']} @{e['off']:#x}: {e['old_len']}B -> {e['new_len']}B (+{e['new_len'] - e['old_len']}), "
              f"slot ends {e['limit']:#x}, spare after {e['limit'] - e['off'] - e['new_len']}B; {state}")
        print(f";   old: \"{e['old']}\"")
        print(f";   new: \"{e['new']}\"")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
