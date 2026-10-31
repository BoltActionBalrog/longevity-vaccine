r"""One-shot splice of the UNTITLED-popup chrome set into patches.yaml
(src assemble_untitled_popup.py).  Byte-level edit (read_bytes/write_bytes, CRLF
kept -- memory feedback-yaml-utf8-encoding); every replace is asserted unique.

  symbols   thunk_scale_header / thunk_popup_nestpads -> pcave2 tail slots;
            + thunk_untitled_stash, Win_is_visible
  caves     menu_strip_thunks: thunk_scale_header v1 entry REMOVED (slot -> padding)
            pcave2: thunk_popup_nestpads v2 entry REPLACED by the three new entries
  sites     + Popup_on_draw_background.untitled_stash (group popup_chrome_insets)

NOTE for later bakes: assemble_dw.py / splice_dw.py still carry nestpads v2 IN
PLACE at 0x3770 -- a refresh of those fragments would put v2 back (memory
feedback-fragment-refresh-reverts-foreign-entries).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assemble_untitled_popup as ASM  # noqa: E402

YAML = HERE.parent / "patches" / "patches.yaml"
NL = "\r\n"


def main() -> int:
    raw = YAML.read_bytes()
    assert b"\r\n" in raw
    text = raw.decode("utf-8")
    if "thunk_untitled_stash" in text:
        print("already spliced")
        return 0
    tpl = ASM.templates()

    def once(old: str, new: str, what: str) -> None:
        nonlocal text
        assert text.count(old) == 1, f"{what}: {text.count(old)} matches"
        i = text.index(old)
        assert 0 < i < i + len(old)
        text = text[:i] + new + text[i + len(old):]

    def line_of(prefix: str) -> str:
        i = text.index(prefix)
        assert text.count(prefix) == 1, prefix
        j = text.index(NL, i)
        return text[i:j]

    # ---- symbols ---------------------------------------------------------
    off_hdr, tpl_hdr, n_hdr = tpl["thunk_scale_header"]
    off_nest, tpl_nest, n_nest = tpl["thunk_popup_nestpads"]
    off_st, tpl_st, n_st = tpl["thunk_untitled_stash"]

    old = line_of("  thunk_scale_header:            {")
    once(old, f"  thunk_scale_header:            {{ cave: pcave2, offset: {off_hdr:#x} }}             "
              f"# v2 {n_hdr}B 2026-09-18 (RELOCATED menu_strip 0xBB0 -> pcave2 tail; src assemble_untitled_popup.py; law "
              f"popup_header_reserve): header reserve [0x30e8]=popup_pad([0x21b8]) at the BasePop_calc copy 0x6039b3 for TITLED "
              f"popups (v1) AND untitled FLAT/SLIDE popups (18 -> 45 @g40; excluded: faction-quote singleton = "
              f"thunk_d528_inset owns its top, ornate = thunk_tutwin_ctop). push/ret detour -> 0x6039b9 store",
         "sym scale_header")
    old = line_of("  thunk_popup_nestpads:          {")
    once(old, f"  thunk_popup_nestpads:          {{ cave: pcave2, offset: {off_nest:#x} }}             "
              f"# v3 {n_nest}B 2026-09-18 (RELOCATED 0x3770 -> pcave2 tail; src assemble_untitled_popup.py; law "
              f"nested_frame_pad(g, body_only)): BODY-ONLY path ([30d4]!=0 & ([2350]==-1 | art)) pad = popup_pad(3) = the "
              f"stroke PITCH (v2's list law scale_px(2) gave L/T/B pitch 5 vs the pf-aligned R 7 @g40); list / UnionRect "
              f"paths keep v2. + keyed flat art-anchor pre-add (law flat_art_anchor)",
         "sym nestpads")
    anchor = line_of("  g_fp_ornart:                   {")
    once(anchor, anchor + NL +
         f"  thunk_untitled_stash:          {{ cave: pcave2, offset: {off_st:#x} }}             "
         f"# {n_st}B 2026-09-18 (src assemble_untitled_popup.py; law untitled_virtual_title_bottom; parity "
         f"tests\\test_untitled_popup_asm_parity.py): CALL helper over Popup_on_draw_background's 0x405F7C "
         f"`mov eax,[esi+0xa48]`. Untitled FLAT/SLIDE popup at g>16: runs the titled path's own inset thunks on the "
         f"window rect and stores the VIRTUAL g_title_left/right (the engine skips the title block, so the pf-align pair "
         f"read the PREVIOUS popup's stash), arms g_band_popup + a virtual g_title_bottom that lands fieldpads' keyed arm on "
         f"the engine T",
         "sym new")
    anchor = line_of("  header_reserve_resume:        {")
    once(anchor, anchor + NL +
         "  Win_is_visible:               { va: 0x005F7E90 }   # thiscall(Win*) -> bool; the engine's in-game test is "
         "Win_is_visible(MainWin_g 0x7AE820)",
         "sym Win_is_visible")

    # ---- menu_strip cave: drop thunk_scale_header v1 -----------------------
    i = text.index("      # thunk_scale_header (31): scales the header reserve.")
    j = text.index("      # thunk_title_hmargin (28):", i)
    assert 0 < i < j and text.count("      - id: thunk_scale_header" + NL) == 1
    assert "- id: thunk_scale_header" in text[i:j] and text[i:j].count("- id:") == 1
    text = (text[:i] +
            "      # thunk_scale_header: v2 RELOCATED to pcave2 2026-09-18 (slot 0xBB0..0xBCF back to padding)." + NL +
            text[j:])

    # ---- pcave2: nestpads v2 entry -> the new set -------------------------
    i = text.index("      # thunk_popup_nestpads (38B): replaces the 15B nested-d5a0")
    j = text.index("      # ======== QUIT art/text-box alignment (group popup_art_align, 2026-07-03) ========", i)
    assert 0 < i < j and text[i:j].count("- id:") == 1 and "- id: thunk_popup_nestpads" in text[i:j]
    new = (
        "      # ---- UNTITLED-popup chrome set (2026-09-18; src scripts\\assemble_untitled_popup.py; parity" + NL +
        "      # tests\\test_untitled_popup_asm_parity.py; 4K shot 20260918-003046 vs refs\\pristine\\VersionNumber.png).  An" + NL +
        "      # untitled popup ([0xa48]==0) skips the engine's title block (je @0x405f84): no title stash ran, so the pf-align" + NL +
        "      # pair used the PREVIOUS popup's g_title_left/right (text box 178px short), the header reserve 18 stayed native" + NL +
        "      # (ring top +6 vs +30 @g40), the art was unkeyed, and nestpads v2's list law hit the body-only ring (pitch 5 vs 7)." + NL +
        "      # thunk_untitled_stash: CALL-entered over the 6B `mov eax,[esi+0xa48]`; returns eax=[0xa48]. pushad around" + NL +
        "      # Win_is_visible(MainWin) -> thunk_popup_titleinsets | thunk_title_hmargin on [ebp-0x14]/[ebp-0xc] (dead locals" + NL +
        "      # on the untitled path) = the titled cascade itself, then the engine's +1/-1." + NL +
        "      - id: thunk_untitled_stash" + NL +
        f"        offset: {off_st:#x}" + NL +
        f'        bytes: "{tpl_st}"' + NL +
        "      # thunk_scale_header v2: v1 + the untitled FLAT/SLIDE arm (law popup_header_reserve)." + NL +
        "      - id: thunk_scale_header" + NL +
        f"        offset: {off_hdr:#x}" + NL +
        f'        bytes: "{tpl_hdr}"' + NL +
        "      # thunk_popup_nestpads v3: replaces the 15B nested-d5a0 +-3 block @0x406211 (all three source-rect paths" + NL +
        "      # converge here): eax-=pad (L), ecx+=pad (R), [ebp-0x24]=eax, edx-=pad (T), edi+=pad (B); pad per law" + NL +
        "      # nested_frame_pad(g, body_only)." + NL +
        "      - id: thunk_popup_nestpads" + NL +
        f"        offset: {off_nest:#x}" + NL +
        f'        bytes: "{tpl_nest}"' + NL +
        NL)
    text = text[:i] + new + text[j:]

    # ---- site + group member ------------------------------------------------
    anchor = "  # ==== popup_art_align: stash the title-band L + arm the art-alignment key ===="
    once(anchor,
         "  - id: Popup_on_draw_background.untitled_stash" + NL +
         "    status: confirmed   # PENDING in-game visual confirm (4K + non-4K)" + NL +
         "    group: popup_chrome_insets" + NL +
         "    function: Popup_on_draw_background" + NL +
         f"    virtual_addr: 0x{ASM.SITE_VA:08X}" + NL +
         "    length: 6" + NL +
         '    original_bytes: "8B 86 48 0A 00 00"                     # mov eax,[esi+0xa48] (title string; the je @0x405f84 skips the title block)' + NL +
         '    new_bytes:      "E8 {rel32:thunk_untitled_stash} 90"' + NL +
         "    pattern: instruction_to_thunk_call_plus_nop" + NL + NL + anchor,
         "site")
    once("      - Popup_on_draw_background.nest_pads" + NL + "    code_caves:",
         "      - Popup_on_draw_background.nest_pads" + NL +
         "      - Popup_on_draw_background.untitled_stash" + NL + "    code_caves:",
         "group member")

    YAML.write_bytes(text.encode("utf-8"))
    print("spliced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
