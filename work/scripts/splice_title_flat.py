r"""One-shot splice: the popup TITLE pair draws FLAT (no frame_grow_delta outward grow), and every
compensation written against the grow is zeroed (law title_grow_delta == 0).  2026-09-18.

  + thunk_box_thick_flat (pcave2): byte clone of thunk_box_thick with the Delta computation
    `83 E8 10 C1 E8 03 8B D8` -> `33 DB 90*6` (the hollow_flat technique).  thunk_box_thick itself is
    KEPT: the diplomacy talk screen (t_dp_title_outer/inner) insets its own rects by +D against it.
  * thunk_inner_margin / thunk_pf_title_stash: tail target thunk_box_thick -> thunk_box_thick_flat.
  * every popup-chain `(g-16) >> 3` delta: shift count 3 -> 31 (== 0 for g > 16; same length, no
    relocation):  pf_frame_align, pf_union_align x2, tutwin_backdrop, popup_fieldpads x3,
    untitled_stash, popup_nestpads, popup_artalign.
  * thunk_popup_fieldpads' keyed flat/slide T arm (T = B + 2*(ps3+delta)) -> 22 NOPs: eax keeps the
    engine arm T = t_src - ps3 (vanilla x g/16: ring top s(32), field top s(35)).

Byte-level yaml edit (read_bytes/write_bytes, CRLF kept)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import apply_patches as ap  # noqa: E402

YAML = HERE.parent / "patches" / "patches.yaml"
NL = "\r\n"
FLAT_OFF = 0x2E840
DELTA_OLD = "83 E8 10 C1 E8 03 8B D8"
DELTA_NEW = "33 DB 90 90 90 90 90 90"

# (thunk id, resolved offset of the `sub r,0x10` that starts the delta computation)
DELTA_SITES = [
    ("thunk_pf_frame_align", 0x5E), ("thunk_pf_union_align", 0xBA), ("thunk_pf_union_align", 0x128),
    ("thunk_tutwin_backdrop", 0x2B),
    ("thunk_popup_fieldpads", 0x67), ("thunk_popup_fieldpads", 0x9F), ("thunk_popup_fieldpads", 0x151),
    ("thunk_untitled_stash", 0x72), ("thunk_popup_nestpads", 0x42), ("thunk_popup_artalign", 0x41),
]
KEYED_T = ("thunk_popup_fieldpads", 0x127, 22)      # A1 g / sub / sar / add eax,edx / mov ecx,[tb] / lea


def tok_index(tokens: list[str], off: int) -> int:
    pos = 0
    for i, t in enumerate(tokens):
        if pos == off:
            return i
        pos += 4 if t.startswith("{") else 1
    raise AssertionError(f"offset {off:#x} is not on a token boundary")


def main() -> int:
    text = YAML.read_bytes().decode("utf-8")
    assert "\r\n" in text
    if "thunk_box_thick_flat" in text:
        print("already spliced")
        return 0

    def bytes_span(tid: str) -> tuple[int, int]:
        key = f"      - id: {tid}{NL}"
        assert text.count(key) == 1, tid
        i = text.index(key)
        j = text.index('        bytes: "', i) + len('        bytes: "')
        assert "- id:" not in text[i + len(key):j], tid
        k = text.index('"', j)
        return j, k

    edits: dict[str, list[str]] = {}

    def toks(tid: str) -> list[str]:
        if tid not in edits:
            j, k = bytes_span(tid)
            edits[tid] = text[j:k].split()
        return edits[tid]

    for tid, off in DELTA_SITES:
        t = toks(tid)
        i = tok_index(t, off)
        assert t[i] == "83" and t[i + 2] == "10" and t[i + 3] == "C1" and t[i + 5] == "03", (tid, hex(off), t[i:i + 6])
        assert int(t[i + 1], 16) & 0xF8 == 0xE8 and int(t[i + 4], 16) & 7 == int(t[i + 1], 16) & 7
        t[i + 5] = "1F"

    tid, off, n = KEYED_T
    t = toks(tid)
    i = tok_index(t, off)
    want = ["A1", "{abs32:g_popup_scale_num}", "83", "E8", "10", "C1", "F8", "03", "01", "D0",
            "8B", "0D", "{abs32:g_title_bottom}", "8D", "04", "41"]
    assert t[i:i + len(want)] == want, t[i:i + len(want)]
    assert t[i + len(want)] == "59"                                  # pop ecx follows
    t[i:i + len(want)] = ["90"] * n

    for tid, t in edits.items():
        j, k = bytes_span(tid)
        text = text[:j] + " ".join(t) + text[k:]

    # ---- the flat clone ----------------------------------------------------
    j, k = bytes_span("thunk_box_thick")
    src = text[j:k]
    assert src.count(DELTA_OLD) == 1
    flat = src.replace(DELTA_OLD, DELTA_NEW)
    nbytes = sum(4 if x.startswith("{") else 1 for x in flat.split())

    def once(old: str, new: str, what: str) -> None:
        nonlocal text
        assert text.count(old) == 1, f"{what}: {text.count(old)}"
        text = text.replace(old, new)

    def line_of(prefix: str) -> str:
        assert text.count(prefix) == 1, prefix
        i = text.index(prefix)
        return text[i:text.index(NL, i)]

    anchor = line_of("  thunk_backdrop_railtrim:       {")
    once(anchor, anchor + NL +
         f"  thunk_box_thick_flat:          {{ cave: pcave2, offset: {FLAT_OFF:#x} }}             "
         f"# {nbytes}B 2026-09-18 (src splice_title_flat.py; law title_grow_delta): thunk_box_thick with Delta = 0 -- the popup "
         f"title pair (thunk_pf_title_stash outer + thunk_inner_margin inner) draws AT its rect, like every body frame since "
         f"2026-07-09. thunk_box_thick (grow) stays for the diplomacy talk title (t_dp_title_*), whose rects pre-inset +D",
         "sym")

    anchor = line_of("      - id: thunk_backdrop_railtrim")
    i = text.index(anchor)
    e = text.index(NL, text.index('        bytes: "', i)) + len(NL)
    text = (text[:e] +
            "      # thunk_box_thick_flat (2026-09-18): the popup title box drew frame_grow_delta OUTSIDE its rect on all four" + NL +
            "      # sides (4K Quit: strokes at frame+7 vs vanilla x g/16 = +10 on L/T/R, 67 rows tall vs 61) and the whole body was" + NL +
            "      # aligned to the grown stroke.  Clone of thunk_box_thick with Delta = 0; every `(g-16)>>3` compensation in the" + NL +
            "      # popup chain is zeroed in place (shift count 3 -> 31) and fieldpads' keyed T arm falls back to the engine arm." + NL +
            "      - id: thunk_box_thick_flat" + NL +
            f"        offset: {FLAT_OFF:#x}" + NL +
            f'        bytes: "{flat}"' + NL +
            text[e:])

    n = text.count("{abs32:thunk_box_thick}")
    assert n == 2, n
    text = text.replace("{abs32:thunk_box_thick}", "{abs32:thunk_box_thick_flat}")

    YAML.write_bytes(text.encode("utf-8"))
    print(f"spliced: thunk_box_thick_flat @ {FLAT_OFF:#x} ({nbytes}B), {len(DELTA_SITES)} delta sites zeroed, keyed T arm -> engine arm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
