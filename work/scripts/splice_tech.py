#!/usr/bin/env python
"""Splice the tech_scale fragments (assemble_tech.py --fragments) into
work/patches/patches.yaml.  Idempotent + re-spliceable (marker blocks are stripped and
re-inserted).  UTF-8 + newline preserving (feedback-yaml-utf8-encoding).

  symbols : + the tech_scale symbols (after the se_scale symbols block)
  contents: + the new thunks/data (after the se_scale contents block; pcave2 length 0x1A000 unchanged,
            the tail 0x16E00..0x177B0 was free per cave_map.py --fit)
  groups  : + tech_scale (after the se_scale group)
  sites   : + the tech_scale sites (after the se_scale sites block)
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "patches" / "patches.yaml"
FRAG = HERE.parent / "patches"
MARK = "# ==== tech_scale"

GROUP = """
  # ==== tech_scale group ====
  - id: tech_scale
    description: >
      SELECT RESEARCH GOAL (tech_pick / TechWin) scales to the runtime popup scale
      (prototype hook_tech_proto.js v3b, USER-VERIFIED 4K/1600/1920 pixel-measured 2026-08-28;
      src assemble_tech.py; laws scaling_laws.tech_*).  Option (a): vanilla's own screen-fit
      window law evaluated at device density -- 36 exec/painter/hit-test immediates via a
      runtime imm table (VirtualProtect bootstrap; HD kind s(a)-s(b), LIN kind for the icon
      ratio literals with the native restored at g<=16); the cell R/B inset = s(4)-1 (11-byte
      cut) so gap and right/bottom channel = s(4) while the shared `inc` gutters stay native;
      strip bottom one cascade s(26); n>8 overflow margin via a 6-byte cut (imm8 overflow);
      fonts CELL-calibrated (Font_init sizes rewritten, find_font replaced by dedicated cave
      Font objects built with config_popups' face/flags law) because find_font snaps to
      font_size_table (cap 40); chrome through thunk_box_thick_devfill, the strip/cell rects
      passed with R-1/B-1 (measured spill).  Every thunk is a native no-op at g<=16.
    code_caves:
      - pcave2
      - menu_strip_thunks   # g_popup_scale_num
    members:
{members}
  # ==== tech_scale END ==== group
"""


def frag(name: str) -> str:
    return (FRAG / f"_fragment_tech_{name}.yaml").read_text(encoding="utf-8")


def insert_after(text: str, anchor: str, block: str, what: str) -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit(f"splice: {what}: anchor found {n} times")
    i = text.index(anchor)
    j = text.index("\n", i) + 1
    return text[:j] + block + text[j:]


def strip_blocks(text: str) -> tuple[str, int]:
    pat = re.compile(r"^[ ]*# ==== tech_scale (symbols|contents|group|sites)\b[^\n]*\n.*?^[ ]*# ==== tech_scale END ==== \1[^\n]*\n",
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
            sys.exit("splice: stray tech_scale marker survived the strip")
    if "length: 0x1A000" not in text:
        sys.exit("splice: pcave2 length 0x1A000 not found (the tech block needs the SE-grown section)")

    block = (f"  {MARK} symbols (2026-08-28 tech bake, src assemble_tech.py) ====\n" + frag("symbols").rstrip("\n") + "\n"
             f"  {MARK} END ==== symbols\n")
    text = insert_after(text, "  # ==== se_scale END ==== symbols", block, "symbols anchor")

    block = (f"      {MARK} contents (2026-08-28 tech bake; src assemble_tech.py, REGENERATE FROM THERE; parity tests\\test_tech_asm_parity.py) ====\n"
             "      # Tail block 0x16E00..: vpdone/vpold cells, rb1 rect copy, fi cache (8 x 16), scratch Font, ff cache (6 x 0x40\n"
             "      # = S/v/g + a Font object), g_tech_immtab 580B (36 x 16 + terminator) @0x17100, + 9 thunks @0x17400..0x177B0\n"
             "      # (enter/immfix/inset/n8/n8ch/rb1/calib/fi/ff).  Design in assemble_tech.py's docstring; _tech_patch_plan.md has the evidence.\n"
             + frag("cave").rstrip("\n") + "\n"
             f"      {MARK} END ==== contents\n")
    text = insert_after(text, "      # ==== se_scale END ==== contents", block, "contents anchor")

    site_ids = re.findall(r"^  - id: (\S+)", frag("sites"), flags=re.M)
    members = "\n".join(f"      - {sid}" for sid in site_ids)
    text = insert_after(text, "  # ==== se_scale END ==== group", GROUP.format(members=members), "group anchor")

    block = (f"  {MARK} sites (2026-08-28 tech bake; src assemble_tech.py) ====\n" + frag("sites").rstrip("\n") + "\n"
             f"  {MARK} END ==== sites\n")
    text = insert_after(text, "  # ==== se_scale END ==== sites", block, "sites anchor")

    PATCHES.write_bytes(text.replace("\n", nl).encode("utf-8"))
    print(f"{'re-' if resplice else ''}spliced: {len(site_ids)} sites, group tech_scale")
    return 0


if __name__ == "__main__":
    sys.exit(main())
