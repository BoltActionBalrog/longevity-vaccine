#!/usr/bin/env python
"""Splice the se_scale fragments (assemble_se.py --fragments) into
work/patches/patches.yaml.  Idempotent + RE-SPLICEABLE: if the marker blocks are
already present they are stripped and re-inserted from the fresh fragments (v2
2026-08-25b: the slide-rail arms + backdrop/window imm laws changed the thunk
bytes, the site list and the gate_pre tail offset).  UTF-8 + newline preserving
(feedback-yaml-utf8-encoding: never round-trip the yaml through a
default-encoding open()).

What it does:
  code_caves: pcave2 length 0x14000 -> 0x1A000 (the tail block lives past 0x14000)
  symbols   : + the se_scale symbols (after the council_scale symbols block);
              thunk_btn_gate_pre symbol -> the new tail offset (v3, 69B)
  contents  : + the new thunks/data (after the council_scale contents block);
              thunk_btn_gate_pre v3 offset+bytes (old 0x13760 slot freed)
  groups    : + se_scale (after the council_scale group)
  sites     : + the se_scale sites (after the council_scale sites block)
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "patches" / "patches.yaml"
FRAG = HERE.parent / "patches"
MARK = "# ==== se_scale"

GROUP = """
  # ==== se_scale group ====
  - id: se_scale
    description: >
      SOCIAL ENGINEERING screen scales to the runtime popup scale (prototype
      hook_se_scale_proto.js v23, USER-VERIFIED 4K/1600/1920 pixel-measured 2026-08-25;
      src assemble_se.py; laws scaling_laws.se_*).  Modal: every rect-table edge x g/16
      (half-down), FlatButton dims re-pinned to the floor idiom (the shrink's exact
      inverse), SOCIETY rows on a uniform pitch, panel bottom / SPARTANS box anchored
      to the row stack with equal free channels; 92 painter/builder immediates
      (insets, font sizes, the digit-w alias reads) via a runtime imm table
      (VirtualProtect bootstrap like scenedit/council); console tables rebuilt from the
      HUD-scaled region globals; sd2 icon/digit draws num=g den=16 with canvas-only
      sprite scaling; lock art centre-NN + dither regenerated at device density; slider
      tiles rebuilt W x 2P; FlatButton faces P-striped + ring pinned to K at the
      row-draw vtable slot; the 35 SE FlatButtons take the shrink/2D-zoom pipeline
      (btn_gate_pre v3 HIT range); modal chrome through the box_thick family.  v2
      (2026-08-25b): the modal SLIDES, so its side "pillars" are the generic slide
      rails -- the popup rail gate is armed around SocialWin_show_hide's own
      slide_show/slide_hide calls (railscale/railslide scale them) and the backdrop
      L/R + window-width imms follow the rails' floor cascades (laws se_window_w /
      se_backdrop_rect) so the frame abuts the rails at every g.  Every thunk is a
      native no-op at g<=16 (imm table = identity).
    code_caves:
      - pcave2
      - menu_strip_thunks   # g_popup_scale_num
    members:
{members}
  # ==== se_scale END ==== group
"""


def frag(name: str) -> str:
    return (FRAG / f"_fragment_se_{name}.yaml").read_text(encoding="utf-8")


def frag_entries(text: str) -> dict[str, tuple[str, str]]:
    out = {}
    for m in re.finditer(r"- id: (\S+)\n\s+offset: (\S+)\n\s+bytes: \"([^\"]*)\"", text):
        out[m.group(1)] = (m.group(2), m.group(3))
    return out


def must_replace(text: str, old: str, new: str, what: str) -> str:
    n = text.count(old)
    if n != 1:
        sys.exit(f"splice: {what}: expected exactly 1 occurrence, found {n}")
    return text.replace(old, new)


def insert_after(text: str, anchor: str, block: str, what: str) -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit(f"splice: {what}: anchor found {n} times")
    i = text.index(anchor)
    j = text.index("\n", i) + 1
    return text[:j] + block + text[j:]


def strip_blocks(text: str) -> tuple[str, int]:
    """Remove every marker-delimited se_scale block (symbols/contents/group/sites)."""
    pat = re.compile(r"^[ ]*# ==== se_scale (symbols|contents|group|sites)\b[^\n]*\n.*?^[ ]*# ==== se_scale END ==== \1[^\n]*\n",
                     re.M | re.S)
    text, n = pat.subn("", text)
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
            sys.exit("splice: stray se_scale marker survived the strip")
    entries = frag_entries(frag("cave"))
    gp_off, gp_bytes = entries["thunk_btn_gate_pre"]

    # ---- code cave length -------------------------------------------------
    old_len = "    length: 0x14000            # (grown 0x11000->0x12000"
    if old_len in text:
        text = must_replace(text, old_len,
                            "    length: 0x1A000            # (grown 0x14000->0x1A000 2026-08-25 se_scale bake, src assemble_se.py: "
                            "0x14000-0x15C00 data cells + imm table + lock planes, 0x15C00-0x16E00 the 13 SE thunks; "
                            "prior: grown 0x11000->0x12000",
                            "pcave2 length")
    elif "length: 0x1A000            # (grown 0x14000->0x1A000" not in text:
        sys.exit("splice: pcave2 length line not recognised")

    # ---- symbols ----------------------------------------------------------
    sym_lines = [ln for ln in frag("symbols").splitlines() if ln.strip() and not ln.lstrip().startswith("thunk_btn_gate_pre:")]
    block = (f"  {MARK} symbols (2026-08-25 se bake, src assemble_se.py) ====\n" + "\n".join(sym_lines) + "\n"
             f"  {MARK} END ==== symbols\n")
    text = insert_after(text, "  # ==== council_scale END ==== symbols", block, "symbols anchor")
    old_gp = "  thunk_btn_gate_pre:            { cave: pcave2, offset: 0x13760, size: 47 }   # v2 2026-08-22"
    if old_gp in text:
        text = must_replace(text, old_gp,
                            f"  thunk_btn_gate_pre:            {{ cave: pcave2, offset: {gp_off}, size: 69 }}   # v3 2026-08-25 (se_scale, "
                            "RELOCATED 0x13760 -> tail, old slot zeros; src assemble_se.py): 22B HIT prefix for esi in [0x8AC290,0x8C4E0C) = "
                            "the 35 SocialWin FlatButtons (faces through the shrink/2D-zoom pipeline), then v2 VERBATIM. v2 2026-08-22",
                            "gate_pre symbol")
    else:
        pat = re.compile(r"(  thunk_btn_gate_pre:            \{ cave: pcave2, offset: )0x[0-9A-Fa-f]+(, size: 69 \}   # v3 2026-08-25)")
        if len(pat.findall(text)) != 1:
            sys.exit("splice: thunk_btn_gate_pre v3 symbol line not found exactly once")
        text = pat.sub(lambda m: m.group(1) + gp_off + m.group(2), text)

    # ---- cave contents ----------------------------------------------------
    new_entries = "\n".join(
        f"      - id: {i}\n        offset: {o}\n        bytes: \"{b}\"" for i, (o, b) in entries.items() if i != "thunk_btn_gate_pre")
    block = (f"      {MARK} contents (2026-08-25 se bake; src assemble_se.py, REGENERATE FROM THERE; parity tests\\test_se_asm_parity.py) ====\n"
             "      # Tail block 0x14000..: g_se_vpdone/vpold/sprg cells, g_se_immtab 1476B (92 x 16 + terminator),\n"
             "      # g_se_sprsave 932B (104 canvas natives + 2 lock structs + 6 tile pairs), g_se_lockplane 2 x 0x900,\n"
             "      # + 13 thunks (enter/immfix/stripe_top/sprites/tiles/locks/transform/sd2/rr_row/rr_col/stripe_px/rowdraw/\n"
             "      # btn_gate_pre v3).  Full design in assemble_se.py's docstring; ACTION_ITEMS SE section has the evidence.\n"
             "      # v2 2026-08-25b: immfix kinds 2/4/8 (rail-abutting backdrop L/R + ceil window width), +2 rail-arm sites.\n"
             + new_entries + "\n"
             f"      {MARK} END ==== contents\n")
    text = insert_after(text, "      # ==== council_scale END ==== contents", block, "contents anchor")
    pat = re.compile(r"(      - id: thunk_btn_gate_pre\n        offset: )0x[0-9A-Fa-f]+(\n        bytes: \")([^\"]*)(\")")
    if len(pat.findall(text)) != 1:
        sys.exit("splice: thunk_btn_gate_pre content entry not found exactly once")
    text = pat.sub(lambda m: m.group(1) + gp_off + m.group(2) + gp_bytes + m.group(4), text)
    old_note = "      # thunk_btn_gate_pre v2 (47B, 2026-08-22 council_scale, RELOCATED 0xC080 -> tail):"
    if "      # thunk_btn_gate_pre v3 (69B, 2026-08-25 se_scale" not in text:
        text = must_replace(text, old_note,
                            "      # thunk_btn_gate_pre v3 (69B, 2026-08-25 se_scale, RELOCATED 0x13760 -> tail, old slot zeros; src\n"
                            "      # assemble_se.py): 22B prefix HIT (eax=1; ret) for esi in [0x8AC290, 0x8C4E0C) = SocialWin+0x6020 +\n"
                            "      # [0..35)*0xB4C, the SE option/society/OK-RESET-CANCEL/arrow FlatButtons (their faces take the\n"
                            "      # shrink/2D-zoom pipeline; no global flag -> MENU/COMMLINK and btntext_nudge untouched), then v2 VERBATIM:\n"
                            "      # thunk_btn_gate_pre v2 (47B, 2026-08-22 council_scale, RELOCATED 0xC080 -> tail):",
                            "gate_pre content note")

    # ---- group ------------------------------------------------------------
    site_ids = re.findall(r"^  - id: (\S+)", frag("sites"), flags=re.M)
    members = "\n".join(f"      - {sid}" for sid in site_ids)
    text = insert_after(text, "  # ==== council_scale END ==== group", GROUP.format(members=members), "group anchor")

    # ---- sites ------------------------------------------------------------
    block = (f"  {MARK} sites (2026-08-25 se bake; src assemble_se.py) ====\n" + frag("sites").rstrip("\n") + "\n"
             f"  {MARK} END ==== sites\n")
    text = insert_after(text, "  # ==== council_scale END ==== sites", block, "sites anchor")

    PATCHES.write_bytes(text.replace("\n", nl).encode("utf-8"))
    print(f"{'re-' if resplice else ''}spliced: {len(entries)} cave entries, {len(site_ids)} sites, group se_scale, "
          f"gate_pre @ {gp_off}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
