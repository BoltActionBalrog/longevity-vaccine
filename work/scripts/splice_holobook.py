#!/usr/bin/env python
"""First-time splice of the retirement Holobook bake (assemble_holobook.py, group holobook_scale) into patches.yaml.

Inserts (idempotent: refuses when t_hb_build is already present -- use `refresh_fragments_yaml.py hb` afterwards):
  symbols   the hb block before `code_caves:`
  contents  the hb cave entries at the end of pcave2's contents (pcave2 is the last cave)
  group     holobook_scale at the end of `groups:`
  sites     the 23 hb sites at the end of the file
and edits two shared chain points + the section length:
  pcave2 length              0x44000 -> 0x46000 (holobook_scale's reserved region 0x44000..0x45FFF)
  t_ntw_gate                 its tail `push {abs32:t_mon_gate}` -> `push {abs32:t_hb_gate}` (t_hb_gate chains to t_mon_gate)
  Buffer_draw_2.mon_button_restripe  new_bytes -> E9 to t_hb_restripe (t_hb_restripe chains to t_mon_restripe)
UTF-8 + newline preserving (feedback-yaml-utf8-encoding)."""
from __future__ import annotations

import contextlib
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
P = os.path.join(HERE, "..", "patches", "patches.yaml")

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_holobook as HBM  # noqa: E402

GROUP = """  - id: holobook_scale
    description: >
      The retirement Holobook ("Welcome to the Planetary Archives"; quayle 0x496670 from Console_retire_game and
      end_of_game) was drawn as its native 1024x768 window at (0,0) over the map with the popup-scaled report fonts
      overflowing its boxes. Now the Hall of Fame's design (src assemble_holobook.py; laws scaling_laws "RETIREMENT
      HOLOBOOK" hb_*; static map work\\_hb_static_map.md): full-height 4:3, centred, black letterbox, num =
      hb_scale_num = hof_scale_num over 16, armed in the wide layout with num > 16. t_hb_build at quayle's call of
      Holobook_gwinit: window to the screen (painter gated across the synchronous resize repaint -- the static's
      page/tier are stale until quayle sets them), content rect, the 6 rects of +0xA34 rebuilt from gwinit's
      literals, CLOSE/BACK s(120) x s(20) with the Arial 14 bold label at num, the painter's 4 fonts at vanilla's
      SNAPPED size x num/16 (user decision 2026-11-15: AN 24 b / AN 18 b+i / Arial 12 / AN 32 b) + their vanilla
      shadows, the list's 3 imm8 gaps through t_dl_immfix. frame.pcx -> t_mon_resample; Holobook.pcx and the
      artboxes -> t_hof_pairnn (pair-only restripe; Holobook.pcx with its own field pair 64/197 through the
      generalized t_hof_pairfld). Captions (pages 1/2/8) at hb_caption_rect. Vanilla LINE BREAKS (user decision
      2026-11-15): the painter's wrap calls arm t_hb_flb at Font_find_line_break_l's entry, which measures with
      the vanilla font at the vanilla width while the draw keeps the scaled font. CLOSE/BACK faces: t_hb_gate
      (in front of t_mon_gate) + t_hb_restripe (in front of t_mon_restripe at Buffer_draw_2). Line pitch = the
      fonts' own metric (user decision: no override; the user re-checks in game). Not levered: the GameLanguage
      != 0 ListBox list. Verify: retire at 4K, 1920x1080, 1600x1200, 1280x1024 -- list page, every title -> its
      book page (1 and 2 captioned), BACK, Esc, CLOSE.
    members:
{members}
    code_caves:
      - pcave2
"""


def main() -> int:
    txt = io.open(P, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in txt else "\n"
    if "t_hb_build:" in txt:
        print("already spliced -- use refresh_fragments_yaml.py hb")
        return 1
    sym, content, site_yaml, end = HBM.fragments()
    layout, _cells, _end, names = HBM.assemble_all()
    lines = txt.split(nl)
    sym = [x for s in sym for x in s.split(chr(10))]          # one yaml line per element: the file's own EOL joins them
    content = [x for s in content for x in s.split(chr(10))]

    def idx(pred, start=0):
        for i in range(start, len(lines)):
            if pred(lines[i]):
                return i
        raise SystemExit("anchor not found")

    # 1. symbols before `code_caves:` (and its separator comment)
    i = idx(lambda l: l == "code_caves:")
    while lines[i - 1].startswith("# ---") or lines[i - 1] == "":
        i -= 1
    lines[i:i] = ["# ==== holobook_scale (src scripts/assemble_holobook.py) ==== symbols"] + sym + \
                 ["# ==== holobook_scale END ==== symbols", ""]
    # 2. contents at the end of pcave2 (the last cave) = before `groups:` and its separator
    i = idx(lambda l: l == "groups:")
    while lines[i - 1].startswith("# ---") or lines[i - 1] == "":
        i -= 1
    lines[i:i] = ["      # ==== holobook_scale (2026-11-15, src assemble_holobook.py): the retirement Holobook, pcave2 "
                  f"0x44000..{end:#x} (region reserved to 0x45FFF)"] + content
    # 3. pcave2 length
    p = idx(lambda l: l == "  - id: pcave2")
    j = idx(lambda l: l.startswith("    length: 0x44000"), p)
    lines[j] = lines[j].replace("length: 0x44000            # (", "length: 0x46000            # (2026-11-15 holobook_scale region "
                                "0x44000..0x45FFF, grown 0x44000 -> 0x46000; src assemble_holobook.py).  (", 1)
    assert "0x46000" in lines[j]
    # 4. group at the end of groups (before `sites:`)
    i = idx(lambda l: l == "sites:")
    while lines[i - 1].startswith("# ---") or lines[i - 1] == "" or lines[i - 1].startswith("#"):
        i -= 1
    members = "\n".join(f"      - {s['id']}" for s in HBM.site_list(names))
    lines[i:i] = [""] + GROUP.format(members=members).rstrip("\n").split("\n")
    # 5. t_ntw_gate's tail push -> t_hb_gate
    k = idx(lambda l: l.strip() == "- id: t_ntw_gate")
    assert lines[k + 2].strip().startswith("bytes:") and lines[k + 2].count("{abs32:t_mon_gate}") == 1
    lines[k + 2] = lines[k + 2].replace("{abs32:t_mon_gate}", "{abs32:t_hb_gate}")
    lines[k:k] = ["      # 2026-11-15 holobook_scale: the tail push now enters t_hb_gate (admits the Holobook's CLOSE/BACK when armed),",
                  "      # which tail-jumps t_mon_gate -- the chain order is t_ntw_gate -> t_hb_gate -> t_mon_gate -> thunk_btn_gate_pre."]
    # 6. the Buffer_draw_2 restripe site -> t_hb_restripe
    k = idx(lambda l: l == "  - id: Buffer_draw_2.mon_button_restripe")
    n = idx(lambda l: l.strip().startswith("new_bytes:"), k)
    jmp = " ".join(f"{x:02X}" for x in b"\xE9" + struct.pack("<i", names["t_hb_restripe"] - (0x5D84C0 + 5)))
    assert lines[n].strip() == 'new_bytes:      "E9 4B F2 45 00"', lines[n]
    lines[n] = f'    new_bytes:      "{jmp}"   # 2026-11-15: E9 -> t_hb_restripe (Holobook CLOSE/BACK), which tail-jumps t_mon_restripe'
    # 7. sites at the end
    while lines and lines[-1] == "":
        lines.pop()
    lines += ["", "  # ==== holobook_scale: the retirement Holobook (src scripts/assemble_holobook.py) ===="] + site_yaml.rstrip("\n").split("\n") + [""]
    io.open(P, "w", encoding="utf-8", newline="").write(nl.join(lines))
    print(f"spliced: {len(sym)} symbols, {len(content)} contents, {len(HBM.site_list(names))} sites, block end {end:#x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
