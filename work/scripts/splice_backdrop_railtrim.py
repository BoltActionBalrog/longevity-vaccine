r"""One-shot splice of thunk_backdrop_railtrim into patches.yaml (src assemble_untitled_popup.py).
Byte-level edit (read_bytes/write_bytes, CRLF kept); every replace asserted unique.

  symbols   + thunk_backdrop_railtrim
  caves     pcave2: + the entry, after thunk_popup_nestpads v3
  sites     Popup_on_draw_background.d690_backdrop: call target thunk_tutwin_backdrop -> thunk_backdrop_railtrim
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

YAML = HERE.parent / "patches" / "patches.yaml"
NL = "\r\n"


def main() -> int:
    raw = YAML.read_bytes()
    assert b"\r\n" in raw
    text = raw.decode("utf-8")
    if "thunk_backdrop_railtrim" in text:
        print("already spliced")
        return 0

    # The assembler resolves thunk_tutwin_backdrop from the yaml, which already has it.
    import assemble_untitled_popup as ASM
    off, tpl, n = ASM.templates()["thunk_backdrop_railtrim"]

    def once(old: str, new: str, what: str) -> None:
        nonlocal text
        assert text.count(old) == 1, f"{what}: {text.count(old)} matches"
        i = text.index(old)
        assert 0 < i < i + len(old)
        text = text[:i] + new + text[i + len(old):]

    def line_of(prefix: str) -> str:
        assert text.count(prefix) == 1, prefix
        i = text.index(prefix)
        return text[i:text.index(NL, i)]

    anchor = line_of("  thunk_untitled_stash:          {")
    once(anchor, anchor + NL +
         f"  thunk_backdrop_railtrim:       {{ cave: pcave2, offset: {off:#x} }}             "
         f"# {n}B 2026-09-18 (src assemble_untitled_popup.py; law popup_backdrop_draw_right; parity "
         f"tests\\test_untitled_popup_asm_parity.py): call-redirect target of the d690 backdrop draw @0x405F77, in front of "
         f"thunk_tutwin_backdrop. g>16 and the DRAW rect's R != the window rect's R (ebx) = the rail-inset in-game arm -> "
         f"dec rect.R: devfill band-maps INCLUSIVE, so the border's outer column sat ON the rail's first column and the "
         f"rail covered it (visible border K-1)",
         "sym")

    anchor = line_of("      - id: thunk_popup_nestpads")
    i = text.index(anchor)
    j = text.index(NL, text.index('        bytes: "', i)) + len(NL)
    assert 0 < i < j
    text = (text[:j] +
            "      # thunk_backdrop_railtrim (2026-09-18): the in-game d690 backdrop's right border lost 1 device px at every g" + NL +
            "      # (4K/1600/1920 shots 011743/012134/012158: 1/1/0 px visible vs the left border's K=2/2/1; pristine shows the" + NL +
            "      # full stroke abutting the rail).  d690insets lands R on the rail's first column -- right for vanilla's" + NL +
            "      # HALF-OPEN draw -- but devfill's band-map footprint is INCLUSIVE (law bandmap_rect_from_halfopen), so the" + NL +
            "      # stroke's outer column is col R, under the rail.  Trim the DRAW copy only ([ebp-0x14..-8]; the rect proper" + NL +
            "      # still feeds the title band + field R).  Menu / ornate popups (rect.R == window R) untouched." + NL +
            "      - id: thunk_backdrop_railtrim" + NL +
            f"        offset: {off:#x}" + NL +
            f'        bytes: "{tpl}"' + NL +
            text[j:])

    once('    new_bytes:      "E8 {rel32:thunk_tutwin_backdrop}"   # v8 (2026-07-10):',
         '    new_bytes:      "E8 {rel32:thunk_backdrop_railtrim}"   # v9 (2026-09-18): via thunk_backdrop_railtrim (in-game '
         'rail-inset rect: R-1 for the inclusive band-map) -> thunk_tutwin_backdrop. v8 (2026-07-10):',
         "site")

    YAML.write_bytes(text.encode("utf-8"))
    print(f"spliced: thunk_backdrop_railtrim @ {off:#x} ({n}B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
