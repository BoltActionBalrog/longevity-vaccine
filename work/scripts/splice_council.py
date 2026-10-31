#!/usr/bin/env python
"""Splice the council_scale fragments (assemble_council.py --fragments) into
work/patches/patches.yaml.  Idempotent (marker-guarded); UTF-8 + newline
preserving (feedback-yaml-utf8-encoding: never round-trip the yaml through a
default-encoding open()).

What it does:
  symbols   : + the council_scale symbols (after thunk_t16_measure_native);
              thunk_popup_fieldpads / thunk_btn_gate_pre symbol offsets -> tail
  contents  : + the new thunks/data (after thunk_t16_measure_native);
              IN-PLACE bytes for thunk_pf_textfollow v2 / thunk_popup_artalign v6;
              thunk_popup_fieldpads v6 + thunk_btn_gate_pre v2 offset+bytes;
              thunk_sprite_draw's internal call -> thunk_sd_reblit_wrap
  groups    : + council_scale
  sites     : + the 16 council sites; 0x406238 -> thunk_gv_frameskip;
              0x404BDE -> thunk_gv_arthead
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = HERE.parent / "patches" / "patches.yaml"
FRAG = HERE.parent / "patches"
MARK = "# ==== council_scale"


def frag(name: str) -> str:
    return (FRAG / f"_fragment_council_{name}.yaml").read_text(encoding="utf-8")


def frag_entries(text: str) -> dict[str, str]:
    """{id: 'bytes: "..."'} for every content entry in the cave fragment."""
    out = {}
    for m in re.finditer(r"- id: (\S+)\n\s+offset: (\S+)\n\s+bytes: \"([^\"]*)\"", text):
        out[m.group(1)] = (m.group(2), m.group(3))
    return out


def must_replace(text: str, old: str, new: str, what: str) -> str:
    n = text.count(old)
    if n != 1:
        sys.exit(f"splice: {what}: expected exactly 1 occurrence, found {n}")
    return text.replace(old, new)


def main() -> int:
    raw = PATCHES.read_bytes()
    nl = "\r\n" if b"\r\n" in raw[:4096] else "\n"
    text = raw.decode("utf-8")
    if MARK in text:
        print("already spliced (marker present) - nothing to do")
        return 0
    text = text.replace("\r\n", "\n")
    entries = frag_entries(frag("cave"))
    inplace = {"thunk_pf_textfollow", "thunk_popup_artalign", "thunk_popup_fieldpads", "thunk_btn_gate_pre"}
    # thunk_pf_title_stash v6 (assemble_pf_align.py): + g_title_bottom stash
    text = must_replace(text,
                        '      - id: thunk_pf_title_stash\n        offset: 0xF18\n        bytes: "A1 {abs32:g_popup_scale_num} 83 F8 10 7E 6C 81 FE E0 03 94 00 74 64 8B 96 AC 30 00 00 81 EA 20 4E 00 00 81 FA 10 27 00 00 72 0E 81 EA 40 9C 00 00 81 FA 10 27 00 00 73 2D 6B D0 25 C1 FA 04 83 EA 0D 8B 44 24 04 03 50 04 89 50 0C A1 {abs32:g_popup_scale_num} 6B C0 0D C1 F8 04 83 E8 0D 8B 54 24 04 01 02 01 42 04 29 42 08 8B 44 24 04 8B 10 89 15 {abs32:g_title_left} 8B 50 08 89 15 {abs32:g_title_right} 68 {abs32:thunk_box_thick} C3"',
                        '      # v7 (127B, 2026-08-23c council_scale; src assemble_pf_align.py, law ornate_title_rect): the ornate band lands at\n'
                        '      # s(13)/s(37) POPUP-LOCAL whatever the engine top (v4-v6 added s(13)-13 to a top that is 9+ps3+3 = 15 @g25 / 19 @g40 at\n'
                        '      # g>16 -> band 2/6px low+in; 4K probe 38,38,1703,98 vs 32,32,1709,92 — the "1px field channel" / "text crowding the\n'
                        '      # frame" on the council talk popups were this, the engine\'s [30e8]/T/text chain is proportionate). v6: + stash the\n'
                        '      # POST-arm bottom -> g_title_bottom (pcave2+0x12A10; the flat keyed arm in fieldpads reads it). Slot to 0x1000.\n'
                        '      - id: thunk_pf_title_stash\n        offset: 0xF18\n        bytes: "A1 {abs32:g_popup_scale_num} 83 F8 10 7E 6F 81 FE E0 03 94 00 74 67 8B 96 AC 30 00 00 81 EA 20 4E 00 00 81 FA 10 27 00 00 72 0E 81 EA 40 9C 00 00 81 FA 10 27 00 00 73 27 6B D0 25 C1 FA 04 8B 44 24 04 89 50 0C A1 {abs32:g_popup_scale_num} 6B C0 0D C1 F8 04 8B 54 24 04 2B 42 04 01 02 01 42 04 29 42 08 8B 44 24 04 8B 10 89 15 {abs32:g_title_left} 8B 50 08 89 15 {abs32:g_title_right} 8B 50 0C 89 15 {abs32:g_title_bottom} 68 {abs32:thunk_box_thick} C3"',
                        "title_stash v6 bytes")
    new_entries = "\n".join(
        f"      - id: {i}\n        offset: {o}\n        bytes: \"{b}\"" for i, (o, b) in entries.items() if i not in inplace)

    # ---- symbols ----------------------------------------------------------
    sym_lines = [ln for ln in frag("symbols").splitlines() if ln.strip()]
    sym_keep = [ln for ln in sym_lines if not ln.lstrip().startswith(("thunk_popup_fieldpads:", "thunk_btn_gate_pre:"))]
    fp_off = entries["thunk_popup_fieldpads"][0]
    gp_off = entries["thunk_btn_gate_pre"][0]
    text = must_replace(text, "  thunk_pf_textfollow:           { cave: pcave2, offset: 0x2090 }             # thunk_faction_textmargin's tail (BODY TEXT).",
                        "  thunk_pf_textfollow:           { cave: pcave2, offset: 0x2090 }             # v2 2026-08-22 (council_scale; src assemble_council.py): + the popup_frame_rewrite_applies gate on the X arm (law popup_textfollow_applies, 94B in place). v1: thunk_faction_textmargin's tail (BODY TEXT).",
                        "textfollow symbol")
    anchor = "  thunk_t16_measure_native:      { cave: pcave2, offset: 0xCD40, size: 57 }"
    i = text.index(anchor)
    j = text.index("\n", i) + 1
    block = (f"  {MARK} symbols (2026-08-22 council bake, src assemble_council.py) ====\n" + "\n".join(sym_keep) + "\n"
             f"  {MARK} END ==== symbols\n")
    text = text[:j] + block + text[j:]
    text = must_replace(text, "  thunk_popup_fieldpads:         { cave: pcave2, offset: 0x4550 }             # v5 148B",
                        f"  thunk_popup_fieldpads:         {{ cave: pcave2, offset: {fp_off} }}            # v6 254B 2026-08-22 (council_scale, RELOCATED 0x4550 -> tail, old slot zeros; src assemble_council.py): + ornate R arm (law popup_field_right_src_ornate: key armed & type 2/6 -> ecx = g_title_right - 2*ps3 + Delta) + the keyed-T arm now gated by popup_frame_rewrite_applies (law popup_field_top: ornate keeps the engine T). v5 148B",
                        "fieldpads symbol")
    text = must_replace(text, "  thunk_btn_gate_pre:            { cave: pcave2, offset: 0xC080, size: 25 }    # v1 2026-08-21",
                        f"  thunk_btn_gate_pre:            {{ cave: pcave2, offset: {gp_off}, size: 47 }}   # v2 2026-08-22 (council_scale, RELOCATED 0xC080 -> tail, old slot zeros): 22B HIT prefix for the 6 CouncilWin FlatButtons [0x6FFA14,0x703DDC) (lever G: their faces take the shrink/2D-zoom pipeline), then v1 VERBATIM. v1 2026-08-21",
                        "gate_pre symbol")

    # ---- cave contents ------------------------------------------------------
    anchor = ('      - id: thunk_t16_measure_native\n        offset: 0xCD40\n        bytes: "A1 {abs32:g_popup_scale_num} 83 F8 10 7F 06 68 90 C7 5D 00 C3 A1 D8 03 94 00 85 C0 74 F1 FF B1 2C 05 00 00 51 89 81 2C 05 00 00 FF 74 24 0C E8 21 3A BC FF 59 8F 81 2C 05 00 00 C2 04 00"\n')
    i = text.index(anchor) + len(anchor)
    block = (f"      {MARK} contents (2026-08-22 council bake; src assemble_council.py, REGENERATE FROM THERE; parity tests\\test_council_asm_parity.py) ====\n"
             "      # Tail block 0x12940..0x13920: data cells (g_council_active/g_cw_vpdone/g_cw_vpold/g_flag_ret, g_cw_seedtab 84B,\n"
             "      # g_cw_chipscr 96B, g_flag_lut 512B @0x12A00 [256-aligned: xor ebx,0x100 toggles bright/dark], g_cw_immtab 644B)\n"
             "      # + 15 thunks.  Full design in assemble_council.py's docstring; ACTION_ITEMS council section has the evidence.\n"
             + new_entries + "\n"
             f"      {MARK} END ==== contents\n")
    text = text[:i] + block + text[i:]
    # in-place bytes
    for tid in ("thunk_pf_textfollow", "thunk_popup_artalign"):
        off, b = entries[tid]
        pat = re.compile(rf"(      - id: {tid}\n        offset: {off}\n        bytes: \")([^\"]*)(\")", re.IGNORECASE)
        m = pat.search(text)
        if not m or len(pat.findall(text)) != 1:
            sys.exit(f"splice: {tid} content entry not found exactly once")
        text = text[:m.start(2)] + b + text[m.end(2):]
    # relocated: offset + bytes
    for tid, old_off in (("thunk_popup_fieldpads", "0x4550"), ("thunk_btn_gate_pre", "0xC080")):
        off, b = entries[tid]
        pat = re.compile(rf"(      - id: {tid}\n        offset: ){old_off}(\n        bytes: \")([^\"]*)(\")", re.IGNORECASE)
        if len(pat.findall(text)) != 1:
            sys.exit(f"splice: {tid} content entry not found exactly once")
        text = pat.sub(lambda m: m.group(1) + off + m.group(2) + b + m.group(4), text)
    # version notes on the in-place/relocated entries
    text = must_replace(text, "      # thunk_popup_fieldpads (148B, v5 2026-07-04 @0x4550,",
                        "      # thunk_popup_fieldpads v6 (254B, 2026-08-22 council_scale, RELOCATED 0x4550 -> tail; src assemble_council.py): + ORNATE R ARM\n"
                        "      # (g>16 & esi==g_band_popup & type 2/6: ecx = g_title_right - 2*ps3 + Delta, law popup_field_right_src_ornate — vanilla's\n"
                        "      # ornate `sub ecx,9` @0x40612c stayed native; field R now == the drawn band INNER, union == OUTER, rows == OK bar) and the\n"
                        "      # keyed-T arm GATED by popup_frame_rewrite_applies (law popup_field_top: ornate keeps T = ebx - ps3; run-25 zero channel).\n"
                        "      # thunk_popup_fieldpads (148B, v5 2026-07-04 @0x4550,", "fieldpads note")
    text = must_replace(text, "      # thunk_pf_textfollow (67):",
                        "      # thunk_pf_textfollow v2 (94B, 2026-08-22 council_scale; src assemble_council.py): + popup_frame_rewrite_applies band test\n"
                        "      # on [esi+0x30ac] (law popup_textfollow_applies: ONE gate with frame_align — the ornate family keeps the engine X; the\n"
                        "      # University popup drew at the PD popup's stale g_d528_left+ps3).  v1 notes:\n"
                        "      # thunk_pf_textfollow (67):", "textfollow note")
    text = must_replace(text, "      # thunk_popup_artalign (86, v5 2026-07-03):",
                        "      # thunk_popup_artalign v6 (86B, 2026-08-22 council_scale): v5 bytes VERBATIM except ONE dword — the x anchor reads\n"
                        "      # g_title_left (thunk_pf_title_stash's POST-ornate-shift stash) instead of g_band_left (pre-shift): law popup_art_x\n"
                        "      # (ornate: + ornate_title_inset_delta; flat: identical values).  v5 notes:\n"
                        "      # thunk_popup_artalign (86, v5 2026-07-03):", "artalign note")
    text = must_replace(text, "      # thunk_btn_gate_pre v1 (25, 2026-08-21 council_btn_exclude):",
                        "      # thunk_btn_gate_pre v2 (47B, 2026-08-22 council_scale, RELOCATED 0xC080 -> tail): 22B prefix HIT (eax=1; ret) for\n"
                        "      # esi in [CWIN+0xD94, +6*0xB4C) = the 6 CouncilWin FlatButtons (lever G: faces take the shrink/2D-zoom pipeline,\n"
                        "      # the ctor-default 9-slice drew a native 20px bar at the top of the scaled rect), then v1 VERBATIM:\n"
                        "      # thunk_btn_gate_pre v1 (25, 2026-08-21 council_btn_exclude):", "gate_pre note")
    # thunk_sprite_draw: internal call -> the reblit wrap
    text = must_replace(text,
                        'bytes: "55 8B EC 8B 4D 14 8B 55 18 8B 45 0C 83 E9 05 83 EA 06 85 C0 74 07 05 44 04 00 00 EB 02 33 C0 6A 10 FF 35 {abs32:g_popup_scale_num} 52 51 8B 4D 08 33 D2 8A 51 08 52 50 E8 {rel32:thunk_portrait_drop} 5D C3"',
                        'bytes: "55 8B EC 8B 4D 14 8B 55 18 8B 45 0C 83 E9 05 83 EA 06 85 C0 74 07 05 44 04 00 00 EB 02 33 C0 6A 10 FF 35 {abs32:g_popup_scale_num} 52 51 8B 4D 08 33 D2 8A 51 08 52 50 E8 {rel32:thunk_sd_reblit_wrap} 5D C3"   # 2026-08-22 council_scale: -> thunk_sd_reblit_wrap (portrait_drop, then the parity re-blit; fix D)',
                        "thunk_sprite_draw bytes")

    # ---- groups -------------------------------------------------------------
    anchor = "      - DiploTalkIface_on_mode.railarm_show\n      - DiploTalkIface_on_mode.railarm_hide\n"
    i = text.index(anchor) + len(anchor)
    members = "\n".join(f"      - {m}" for m in re.findall(r"  - id: (\S+)", frag("sites")))
    block = (f"\n  {MARK} group ====\n"
             "  - id: council_scale\n"
             "    description: >\n"
             "      PLANETARY COUNCIL session screen + its popups scale to the runtime popup scale (prototype\n"
             "      hook_council_proto.js v28, USER-VERIFIED 4K/1920/1600/1024 2026-08-22; src assemble_council.py).\n"
             "      Tally screen: seed table + 40 painter/exec immediates x g/16 (runtime imm table, VirtualProtect\n"
             "      bootstrap like scenedit), portraits/logos sd2 num=g/den=16 + parity-forced re-blit (scanline\n"
             "      dither regenerated at device density), frames/chips through the box_thick family, name-line y,\n"
             "      backdrop right inset, VOTE-row FlatButton faces (btn_gate_pre HIT).  Cast-a-Vote: engine device\n"
             "      seeds pass-through (artalign bypass) + empty-body frame hide; the UN flag (Cast-a-Vote AND the\n"
             "      PROTOCOL DIRECTOR modal) pair-LUT restriped at the blit core's Buffer_draw_2 call, content-gated.\n"
             "      Talk popups (WhoToVote / DiploBribe): body-text X, portrait x, field top/right, and the leader\n"
             "      portrait's dither (parity re-blit) — laws popup_textfollow_applies / popup_art_x /\n"
             "      popup_field_top / popup_field_right_src_ornate.  Every thunk is a native no-op at g<=16.\n"
             "    code_caves:\n"
             "      - pcave2\n"
             "      - menu_strip_thunks\n"
             "    members:\n" + members + "\n"
             f"  {MARK} END ==== group\n")
    text = text[:i] + block + text[i:]

    # ---- sites --------------------------------------------------------------
    text = must_replace(text, '    new_bytes:      "E8 {rel32:thunk_content_frame}"        # -> thunk: force rect.right = boxW-left, then tail-jump thunk_box_thick_hollow (width-correct + thicken stroke)',
                        '    new_bytes:      "E8 {rel32:thunk_gv_frameskip}"        # 2026-08-22 council_scale: Cast-a-Vote content gate (council active & ornate & art & no body) -> RET 8 (empty-body frame hide), else tail-jmp thunk_content_frame (was {rel32:thunk_content_frame}: force rect.right = boxW-left, then tail-jump thunk_box_thick_hollow)',
                        "site 0x406238")
    text = must_replace(text, '    new_bytes:      "C7 86 68 31 00 00 {abs32:t_dp_artalign}"  # -> alignment wrapper -> thunk_sprite_draw   # diplo_talk_scale: anchored-gate wrapper (was {abs32:thunk_popup_artalign})',
                        '    new_bytes:      "C7 86 68 31 00 00 {abs32:thunk_gv_arthead}"  # 2026-08-22 council_scale: Cast-a-Vote gate head -> thunk_sprite_draw (engine device seeds untouched) else t_dp_artalign (was {abs32:t_dp_artalign}; diplo_talk_scale: anchored-gate wrapper; before that {abs32:thunk_popup_artalign})',
                        "site 0x404BDE")
    tail_anchor = "# ==== diplo_talk_scale END ==== sites"
    i = text.index(tail_anchor) + len(tail_anchor)
    block = (f"\n\n  {MARK} sites (2026-08-22 council bake; src assemble_council.py) ====\n" + frag("sites").rstrip("\n") + "\n"
             f"  {MARK} END ==== sites")
    text = text[:i] + block + text[i:]

    PATCHES.write_bytes(text.replace("\n", nl).encode("utf-8"))
    print("spliced council_scale into", PATCHES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
