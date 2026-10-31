#!/usr/bin/env python
"""Splice the Datalinks bake fragments (assemble_dl.py --fragments) into work/patches/patches.yaml.
Idempotent + re-spliceable (marker blocks stripped and re-inserted).  UTF-8 + newline preserving
(feedback-yaml-utf8-encoding).

  symbols : + the dl cells/thunks (after the dw_bake symbols block)
  contents: + the 33 thunks + the two imm tables; pcave2 length 0x22000 -> 0x2A000;
            IN PLACE: thunk_sb_restripe head `mov [g_netwin_active],0` -> `mov eax,[g_dl_exec];
            mov [g_netwin_active],eax` (10B, eax dead at entry) = the DL netwin re-assert;
            since 2026-10-17 (fix 7) the head is the clamped `dec` of a counted bracket (SB_RC,
            assemble_rail_scrollbar.asm_sb_restripe) and is left as is -- no re-assert needed;
            the two wheel_scroll sites' new_bytes retargeted thunk_wheel_* -> t_dl_wheel_*
            (the DL cascade heads chain back to the dw thunks for every non-DL context)
  groups  : + dl_scale (after the dw_bake group block)
  sites   : + the 71 sites (after the dw_bake sites block)
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "patches" / "patches.yaml"
FRAG = HERE.parent / "patches"
MARK = "# ==== dl_bake"

GROUP_DESC = """
      DATALINKS (DatalinkWin 0x703EA0: category list + hyperlinked pages + console sub-interface)
      scales to the runtime popup scale (prototype hook_dl_scale_proto.js v12l, USER-VERIFIED +
      adversarially pixel-audited 4K/1600 2026-08-30; src assemble_dl.py; parity
      tests\\test_dl_asm_parity.py).  351 builder/painter/tech immediates via TWO runtime imm tables
      (VirtualProtect bootstrap; kinds HD/MUL2/MUL3/BIAS1/NUMG/DEN16/FLOAT/VEH/PTR, identity at
      g<=16): MAIN applied once at DatalinkWin_build, TECH applied at DatalinkWin_open and REVERTED
      at its return because 0x496BB0..0x49BD00 is ReportWin-shared code (the F8 report screens stay
      native; every tech-range thunk also gates on g_dl_exec).  45 frame draws through the DW
      band-map stubs (R-1/B-1, law bandmap_rect_from_halfopen): hollow d5a0/d528/d5f0 ->
      thunk_box_thick_hollow_flat, filled d618/d690 -> thunk_box_thick_devfill; the 10 CLIP-gated
      connector-bracket draws through t_dl_bmxt (snapshot/restore outside the dest clip + the
      g_fc_exact exact-fill so the bracket's bottom stroke lands at B-2..B-1 = the chevron tip law).
      Backdrop/list dither restriped at the P law (t_dl_restripe: pair by member prescan - 196/65
      navy, 174/238 selected, 65/198 backdrop with the DL's 65-top parity - canonical member on
      stripe-top rows); Buffer_tile list rows re-striped at the two tile sites; content_union
      restriped after render_topic's three frames.  Tech page: RW textB/lineH bracket + iface
      mode-8 force at the two DL call sites; chevrons zoomed g:16 at the 5 Sprite_blit_scaled_core
      sites; the mono icon recoloured to the category text colour (band-histogram argmax); button
      label/title/category fonts repointed to the DL's scaled Font objects via PTR imm rows; hover
      frame +s(3); 6 imm8-overflow register fixups.  FlatButton box-sprite faces get the NATIVE
      rect when thunk_btn_shrink flagged the draw (BACK/EXIT hover clip).  The DL ListBox Win_init
      runs inside a g_popup_active bracket (scrollbar width/zoom at attach); g_netwin_active is
      held around build+exec (arrow/wing button zoom approval) and RE-ASSERTED by thunk_sb_restripe's
      new head after each scrollbar restripe.  Console save-under: t_cr_snap_dl on the DL iface
      vtbl slot 0 snapshots the inter-panel gap on enter; the existing t_cr_tile restores it after
      tile_panels at exit (the diplo exit-residue class).  2026-08-30 addendum: the FACTION
      PROFILES leader portrait is enlarged g:16 through the A5 palette-aware bilinear resampler
      (t_dl_portrait re-pushes Sprite_draw_2's num/den as g:16 and, for exactly that call, pokes
      thunk_portrait_avg's dest-gate imm to the DL canvas; t_dl_portw scales the profile-text x
      advance to the drawn width), and the mouse wheel chevron-scrolls the Datalinks bars (category
      list first, then the visible page/console text scroller) instead of moving the list selection
      (t_dl_wheel_down/up chain in FRONT of the dw wheel thunks at the two WinProc sites - the
      wheel_scroll group's new_bytes retargeted here).  Every lever is a native no-op at g<=16
      (the wheel, like the DW wheel_scroll it extends, is an ungated vanilla behaviour change)."""

OLD_LEN = "length: 0x22000            # (grown 0x1A000->0x22000 2026-08-29 dw bake, src assemble_dw.py: code tail 0x177C0..0x19290 (39 thunks), data cells 0x1A000..0x20000 (imm table, SSAA colour cache 16K, backdrop census); prior: grown 0x14000->0x1A000 2026-08-25 se_scale bake"
MID_LEN = ("length: 0x2A000            # (grown 0x22000->0x2A000 2026-08-30 dl bake, src assemble_dl.py: code 0x22000..0x23050 (29 thunks), "
           "cells 0x27E00, imm tables 0x28100/0x28CE0; prior: grown 0x1A000->0x22000 2026-08-29 dw bake, 0x14000->0x1A000 2026-08-25 se bake")
MID2_LEN = ("length: 0x2A000            # (grown 0x22000->0x2A000 2026-08-30 dl bake, src assemble_dl.py: code 0x22000..0x2324B (33 thunks incl. the portrait/wheel addendum), "
            "cells 0x27E00, imm tables 0x28100/0x28CE0; prior: grown 0x1A000->0x22000 2026-08-29 dw bake, 0x14000->0x1A000 2026-08-25 se bake")
NEW_LEN = ("length: 0x2B000            # (grown 0x2A000->0x2B000 2026-08-30 dl article-flow cache; 0x22000->0x2A000 2026-08-30 dl bake, src assemble_dl.py: code 0x22000..~0x23500 (35 thunks incl. portrait/wheel + article-flow), "
           "cells 0x27E00, imm tables 0x28100/0x28CE0, flow cache 0x2A000; prior: grown 0x1A000->0x22000 2026-08-29 dw bake, 0x14000->0x1A000 2026-08-25 se bake")

SB_OLD = 'bytes: "C7 05 {abs32:g_netwin_active} 00 00 00 00 83 3D'
SB_NEW = 'bytes: "A1 {abs32:g_dl_exec} A3 {abs32:g_netwin_active} 83 3D'
# fix 7 (2026-10-17): sbzoom v11 incs the flag, the restripe head decs it (clamped at 0) -- the
# third accepted form; a counted bracket needs no DL re-assert, so this splice leaves it alone.
SB_RC = 'bytes: "83 3D {abs32:g_netwin_active} 00 7E 06 FF 0D {abs32:g_netwin_active} 83 3D'

# the DW wheel_scroll sites' targets: the DL cascade heads chain to the DW thunks for non-DL contexts
W_SWAPS = (
    ("E8 {rel32:thunk_wheel_down}", "E8 {rel32:t_dl_wheel_down}", "wheel keydown site"),
    ("E8 {rel32:thunk_wheel_up}", "E8 {rel32:t_dl_wheel_up}", "wheel keyup site"),
)


def frag(name: str) -> str:
    return (FRAG / f"_fragment_dl_{name}.yaml").read_text(encoding="utf-8")


def insert_after(text: str, anchor: str, block: str, what: str) -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit(f"splice: {what}: anchor found {n} times")
    i = text.index(anchor)
    j = text.index("\n", i) + 1
    return text[:j] + block + text[j:]


def strip_blocks(text: str) -> tuple[str, int]:
    pat = re.compile(r"^[ ]*# ==== dl_bake (symbols|contents|group|sites)\b[^\n]*\n.*?^[ ]*# ==== dl_bake END ==== \1[^\n]*\n",
                     re.M | re.S)
    return pat.subn("", text)


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
            sys.exit("splice: stray dl_bake marker survived the strip")

    if OLD_LEN in text:
        text = text.replace(OLD_LEN, NEW_LEN, 1)
    elif MID_LEN in text:
        text = text.replace(MID_LEN, NEW_LEN, 1)
    elif MID2_LEN in text:
        text = text.replace(MID2_LEN, NEW_LEN, 1)
    elif NEW_LEN not in text:
        sys.exit("splice: pcave2 length line not found (expected the dw-grown 0x22000 or a dl-grown form)")

    # sb_restripe head: netwin re-assert (identity when g_dl_exec == 0)
    if SB_OLD in text:
        text = text.replace(SB_OLD, SB_NEW, 1)
    elif SB_NEW not in text and SB_RC not in text:
        sys.exit("splice: thunk_sb_restripe head not found in any of its three forms")

    # wheel sites -> the DL cascade heads (idempotent)
    for old, new, what in W_SWAPS:
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            sys.exit(f"splice: {what} new_bytes not found in either form")

    block = (f"  {MARK} symbols (2026-08-30 Datalinks bake, src assemble_dl.py) ====\n" + frag("symbols").rstrip("\n") + "\n"
             f"  {MARK} END ==== symbols\n")
    text = insert_after(text, "  # ==== dw_bake END ==== symbols", block, "symbols anchor")

    block = (f"      {MARK} contents (2026-08-30 Datalinks bake; src assemble_dl.py, REGENERATE FROM THERE; parity tests\\test_dl_asm_parity.py) ====\n"
             "      # Code 0x22000..0x2324B: 33 thunks (immfix walker + main/tech entries, build/exec brackets, restripe core,\n"
             "      # cu detour, bm/bmdf/bmt/bmxt frame stubs, tile wrappers, hover, arrowzoom, mono, btnrect, techwrap,\n"
             "      # wininit bracket, t_cr_snap_dl, 6 regfix detours, portrait bilinear wrapper + width lever, 2 wheel\n"
             "      # cascade heads).  Cells 0x27E00; imm tables 0x28100 (main, 190 rows)\n"
             "      # / 0x28CE0 (tech, 168 rows incl. the 6 PTR label-font repoints; the title/category repoints dropped 2026-09-17, font audit 3.13).  Design in assemble_dl.py's docstring.\n"
             + frag("cave").rstrip("\n") + "\n"
             f"      {MARK} END ==== contents\n")
    text = insert_after(text, "      # ==== dw_bake END ==== contents", block, "contents anchor")

    sites_yaml = frag("sites")
    site_ids = re.findall(r"^  - id: (\S+)", sites_yaml, flags=re.M)
    members = "\n".join(f"      - {sid}" for sid in site_ids)
    gblock = (f"  {MARK} group ====\n"
              f"  - id: dl_scale\n    description: >{GROUP_DESC}\n    code_caves:\n      - pcave2\n"
              f"      - menu_strip_thunks   # g_popup_scale_num\n    members:\n{members}\n"
              f"  {MARK} END ==== group\n")
    text = insert_after(text, "  # ==== dw_bake END ==== group", gblock, "group anchor")

    block = (f"  {MARK} sites (2026-08-30 Datalinks bake; src assemble_dl.py) ====\n" + sites_yaml.rstrip("\n") + "\n"
             f"  {MARK} END ==== sites\n")
    text = insert_after(text, "  # ==== dw_bake END ==== sites", block, "sites anchor")

    PATCHES.write_bytes(text.replace("\n", nl).encode("utf-8"))
    print(f"{'re-' if resplice else ''}spliced: {len(site_ids)} sites, group dl_scale, sb_restripe head swapped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
