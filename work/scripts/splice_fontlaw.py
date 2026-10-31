#!/usr/bin/env python
"""Splice the font_face_law fragments (assemble_fontlaw.py --fragments) into work/patches/patches.yaml.
Idempotent + re-spliceable (marker blocks stripped and re-inserted).  UTF-8 + newline preserving
(feedback-yaml-utf8-encoding).

  symbols : + the fontlaw cells/thunks (after the mon_scale symbols block)
  contents: + the 6 thunks + the key table (after the mon_scale contents block; pcave2 0x2E000..0x2E5B0)
  groups  : + font_face_law (after the hof_bake group block; no member sites)
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "patches" / "patches.yaml"
FRAG = HERE.parent / "patches"
MARK = "# ==== fontlaw_bake"


def frag(name: str) -> str:
    return (FRAG / f"_fragment_fontlaw_{name}.yaml").read_text(encoding="utf-8")


def insert_after(text: str, anchor: str, block: str, what: str) -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit(f"splice: {what}: anchor found {n} times")
    i = text.index(anchor)
    j = text.index("\n", i) + 1
    return text[:j] + block + text[j:]


def strip_blocks(text: str) -> tuple[str, int]:
    pat = re.compile(r"^[ ]*# ==== fontlaw_bake (symbols|contents|group)\b[^\n]*\n.*?^[ ]*# ==== fontlaw_bake END ==== \1[^\n]*\n",
                     re.M | re.S)
    return pat.subn("", text)


def main() -> int:
    raw = PATCHES.read_bytes()
    nl = "\r\n" if b"\r\n" in raw[:4096] else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    resplice = MARK in text
    if resplice:
        text, n = strip_blocks(text)
        if n != 3:
            sys.exit(f"splice: re-splice expected 3 marker blocks, stripped {n}")
        if MARK in text:
            sys.exit("splice: stray fontlaw_bake marker survived the strip")

    block = (f"  {MARK} symbols (2026-09-17 font face/weight law helpers, src assemble_fontlaw.py) ====\n"
             + frag("symbols").rstrip("\n") + "\n"
             f"  {MARK} END ==== symbols\n")
    text = insert_after(text, "  # ==== mon_scale END ====", block, "symbols anchor")

    block = (f"      {MARK} contents (2026-09-17 font face/weight law helpers; src assemble_fontlaw.py --fragments, "
             "splice scripts\\splice_fontlaw.py; parity tests\\test_fontlaw_asm_parity.py) ====\n"
             "      # 0x2E000 g_ffn_keys (15 x u32 S|v<<8); 0x2E040 g_ffn_slots (15 x 0x30 keyed Font slots); 0x2E320.. five\n"
             "      # private slots (a14b / bwname / mon_plaque / mon_btn / hof_btn); code 0x2E420..0x2E5B0: t_font_core,\n"
             "      # t_ffn_at, t_fdirect_at, t_ffn_num, t_ffn, t_fdirect_a14b.  Design in assemble_fontlaw.py's docstring.\n"
             + frag("cave").rstrip("\n") + "\n"
             f"      {MARK} END ==== contents\n")
    text = insert_after(text, "      # ==== mon_scale contents END ====", block, "contents anchor")

    gblock = (f"  {MARK} group ====\n" + frag("group").rstrip("\n") + "\n"
              f"  {MARK} END ==== group\n")
    text = insert_after(text, "  # ==== hof_bake END ==== group", gblock, "group anchor")

    PATCHES.write_bytes(text.replace("\n", nl).encode("utf-8"))
    print(f"{'re-' if resplice else ''}spliced: font_face_law symbols + contents + group")
    return 0


if __name__ == "__main__":
    sys.exit(main())
