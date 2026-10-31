#!/usr/bin/env python
"""Splice the Design Workshop bake fragments (assemble_dw.py --fragments) into work/patches/patches.yaml.
Idempotent + re-spliceable (marker blocks are stripped and re-inserted; the three IN-PLACE cave upgrades
are byte-line replacements keyed by content id).  UTF-8 + newline preserving (feedback-yaml-utf8-encoding).

  symbols : + the dw symbols/cells (after the tech_scale symbols block)
  contents: + the 39 thunks + g_dw_immtab (after the tech_scale contents block); pcave2 length 0x1A000 -> 0x22000
            (code tail 0x177C0..0x19290, data cells 0x1A000..0x20000); IN PLACE: thunk_popup_nestpads v2,
            thunk_orn_childx v2, thunk_btn_gate_pre v4 (bytes lines replaced)
  groups  : + dw_scale / wheel_scroll / popup_listbox_reserve / picker_grid_leave_present (after the tech_scale group)
  sites   : + the 78 sites (after the tech_scale sites block)
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "patches" / "patches.yaml"
FRAG = HERE.parent / "patches"
MARK = "# ==== dw_bake"

GROUPS = {
    "dw_scale": """
      DESIGN WORKSHOP (DesignWin + the stack PartPicker) scales to the runtime popup scale
      (prototype hook_dw_scale_proto.js v15l, USER-VERIFIED 4K/1920/1600 2026-08-29; src
      assemble_dw.py; parity tests\\test_dw_asm_parity.py).  114 builder/painter/picker immediates via a
      runtime imm table at DesignWin_exec entry (VirtualProtect bootstrap; HD/FLOOR/CEIL/VEH kinds,
      identity at g<=16); deswin.pcx re-rendered at device density after DesignWin_build (dither
      families/variants/strokes MEASURED from the plane, line-pinned axis maps, every vertical pair
      regenerated on the P-law stripe -- never resampled); the 25 FlatButton faces through the SE
      restripe (thunk_se_rowdraw) + a DW HIT prefix in thunk_btn_gate_pre; unit renders: the Caviar
      target grown 256^2 -> 1024^2 (option E, global), every DW/picker Caviar_draw TRIAL-renders at
      native zoom, plans (law dw_fit_plan, radial) and renders at zoom*k, composited by the shim as
      SSAA (box filter + palette nearest) or keyed stretch; n x n voxel footprint per part; ctx clip
      = whole target for gated draws; picker cell law (absolute native coords x g/16), click descale,
      container/cell frames through thunk_box_thick_hollow_flat with R-1/B-1 rects, cell/tile/slot
      fills restriped (pairs 196/65, 197/65, 194/65, 191/83); rails armed at the window's own slide
      calls; picker bracket (canvas cell, rail-gate retarget, g_popup_active).  Every thunk is a
      native no-op at g<=16 (1024 measured).""",
    "wheel_scroll": """
      Mouse wheel = one chevron press on the modal's scrollbar (VANILLA BEHAVIOUR CHANGE, user decision
      2026-08-29; ungated).  PRACX turns a notch into posted VK_UP/VK_DOWN pairs with lParam 0, which the
      pickers/popups treat as SELECTION moves; at WinProc's WM_KEYDOWN/KEYUP `call Win_get_active_target`
      a synthetic arrow (lParam 0) on a PartPicker / ProdPicker / Popup rail / FileDlg / TextScroll /
      PrefSub with an engaged bar becomes ScrollBar_on_chevron + present (and is swallowed); real keys
      (scan code in lParam) pass untouched.  Src assemble_dw.py (thunk_wheel_down/up).""",
    "popup_listbox_reserve": """
      Popup family: the type-2 listbox popup's scrollbar RESERVE (law listbox_bar_reserve) -- every
      g_scrollbar_w consumer in the popup-list path (ListBox_calculate_dimensions, GraphicWin
      canvas/bar layout, Win client<->window conversions, Win bar creation, ScrollBar_init/_init_v
      width) loads the SHARED global live and scales it x g/16 under g_popup_active && g>16 (Select
      Special Ability @1920: dialog 845 -> 852, box 899 -> 907); the Win-layer HEAP ScrollBar is
      registered in g_rail_sb at creation (after ScrollBar_init_v) and cleared at Popup_hide so
      thunk_pref_sbzoom/thunk_btn_stripes regenerate its grip/chevron dither at device density
      (the bare zoom banded).  Also thunk_popup_nestpads v2 (law nested_frame_pad) and thunk_orn_childx
      v2 (law ornate_dialog_child_x pad_x) in place.  Src assemble_dw.py.""",
    "picker_grid_leave_present": """
      VANILLA BUG: PartPicker_on_click un-hovers the last cell when the pointer leaves the grid via
      draw_cell(hover, 0) WITHOUT the vtbl+0xFC present the in-grid path does -> the display keeps the
      hover highlight until another present covers it (at 4K a 13-px strip outside the preview's
      recomposite stayed stale).  The call site presents the window right after that draw.  Runs at
      every g.  Src assemble_dw.py (thunk_dw_gridleave).""",
}


def frag(name: str) -> str:
    return (FRAG / f"_fragment_dw_{name}.yaml").read_text(encoding="utf-8")


def insert_after(text: str, anchor: str, block: str, what: str) -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit(f"splice: {what}: anchor found {n} times")
    i = text.index(anchor)
    j = text.index("\n", i) + 1
    return text[:j] + block + text[j:]


def strip_blocks(text: str) -> tuple[str, int]:
    pat = re.compile(r"^[ ]*# ==== dw_bake (symbols|contents|group|sites)\b[^\n]*\n.*?^[ ]*# ==== dw_bake END ==== \1[^\n]*\n",
                     re.M | re.S)
    return pat.subn("", text)


def replace_inplace(text: str, inplace_yaml: str) -> tuple[str, int]:
    n = 0
    for m in re.finditer(r"      - id: (\S+)\n        offset: (\S+)\n        bytes: \"([^\"]*)\"", inplace_yaml):
        cid, off, new = m.group(1), m.group(2), m.group(3)
        pat = re.compile(r"(      - id: " + re.escape(cid) + r"\n        offset: (\S+)\n        bytes: )\"[^\"]*\"")
        mm = list(pat.finditer(text))
        if len(mm) != 1:
            sys.exit(f"splice: in-place {cid}: found {len(mm)} content entries")
        if int(mm[0].group(2), 16) != int(off, 16):
            sys.exit(f"splice: in-place {cid}: yaml offset {mm[0].group(2)} != fragment {off}")
        text = text[:mm[0].start()] + mm[0].group(1) + f"\"{new}\"" + text[mm[0].end():]
        n += 1
    return text, n


def main() -> int:
    raw = PATCHES.read_bytes()
    nl = "\r\n" if b"\r\n" in raw[:4096] else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    resplice = MARK in text
    if resplice:
        text, n = strip_blocks(text)
        if n != 4:
            sys.exit(f"splice: re-splice expected 4 marker blocks, stripped {n}")
        if MARK in text:
            sys.exit("splice: stray dw_bake marker survived the strip")
    old_len = "length: 0x1A000            # (grown 0x14000->0x1A000 2026-08-25 se_scale bake"
    new_len = ("length: 0x22000            # (grown 0x1A000->0x22000 2026-08-29 dw bake, src assemble_dw.py: code tail 0x177C0..0x19290 (39 thunks), "
               "data cells 0x1A000..0x20000 (imm table, SSAA colour cache 16K, backdrop census); prior: grown 0x14000->0x1A000 2026-08-25 se_scale bake")
    if old_len in text:
        text = text.replace(old_len, new_len, 1)
    elif new_len not in text:
        sys.exit("splice: pcave2 length line not found (expected the SE-grown 0x1A000 or the dw-grown 0x22000)")

    block = (f"  {MARK} symbols (2026-08-29 Design Workshop bake, src assemble_dw.py) ====\n" + frag("symbols").rstrip("\n") + "\n"
             f"  {MARK} END ==== symbols\n")
    text = insert_after(text, "  # ==== tech_scale END ==== symbols", block, "symbols anchor")

    block = (f"      {MARK} contents (2026-08-29 Design Workshop bake; src assemble_dw.py, REGENERATE FROM THERE; parity tests\\test_dw_asm_parity.py) ====\n"
             "      # Code tail 0x177C0..0x19290: 39 thunks (dw_scale: enter/immfix/pk bracket/cell/click/frame/bm/restripe/pickcell/tilecell/\n"
             "      # slotcell/btndraw/ssaa/shim/ovl/E stubs x4/fp caves x2/fpset/clip/resetguard/fit/axismap/backdrop/build x2; picker_grid_leave_\n"
             "      # present: gridleave; popup_listbox_reserve: lbres x4/sbv/hide; wheel_scroll: wheel_down/up).  Data 0x1A000..0x20000: cells,\n"
             "      # Caviar header snapshot, g_dw_immtab (114 x 16), SSAA candidates/present/colour cache, backdrop census.  Design in\n"
             "      # assemble_dw.py's docstring; work\\_dw_bake_plan.md + _dw_static_map.md have the evidence.\n"
             + frag("cave").rstrip("\n") + "\n"
             f"      {MARK} END ==== contents\n")
    text = insert_after(text, "      # ==== tech_scale END ==== contents", block, "contents anchor")
    text, n_inplace = replace_inplace(text, frag("inplace"))
    if n_inplace != 3:
        sys.exit(f"splice: expected 3 in-place upgrades, did {n_inplace}")

    sites_yaml = frag("sites")
    site_groups = re.findall(r"^  - id: (\S+)\n    status: \S+\n    group: (\S+)", sites_yaml, flags=re.M)
    gblock = [f"  {MARK} group ====\n"]
    for gid, desc in GROUPS.items():
        members = "\n".join(f"      - {sid}" for sid, grp in site_groups if grp == gid)
        gblock.append(f"  - id: {gid}\n    description: >{desc}\n    code_caves:\n      - pcave2\n      - menu_strip_thunks   # g_popup_scale_num\n    members:\n{members}\n")
    gblock.append(f"  {MARK} END ==== group\n")
    text = insert_after(text, "  # ==== tech_scale END ==== group", "".join(gblock), "group anchor")

    block = (f"  {MARK} sites (2026-08-29 Design Workshop bake; src assemble_dw.py) ====\n" + sites_yaml.rstrip("\n") + "\n"
             f"  {MARK} END ==== sites\n")
    text = insert_after(text, "  # ==== tech_scale END ==== sites", block, "sites anchor")

    PATCHES.write_bytes(text.replace("\n", nl).encode("utf-8"))
    print(f"{'re-' if resplice else ''}spliced: {len(site_groups)} sites, groups {', '.join(GROUPS)}, {n_inplace} in-place upgrades")
    return 0


if __name__ == "__main__":
    sys.exit(main())
