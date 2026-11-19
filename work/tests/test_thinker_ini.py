"""thinker_ini: Thinker's settings files read the way Thinker's own inih reads them, the thinker.ini
merge, and the in-place commenting of thinker_user.ini (design: work/briefs/thinker-updater-design.md
section 6; user rulings of 2026-11-14). Pure bytes in, bytes out: no game, no files."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import thinker_data as td     # noqa: E402
import thinker_ini as ti      # noqa: E402

KNOWN = {b"video_mode", b"expansion_limit", b"script_label", b"DirectDraw", b"skip_event", b"cost_factor"}
STOCK = (b"; header comment\r\n"
         b"[thinker]\r\n"
         b"; Select display mode\r\n"
         b"video_mode=0\r\n"
         b"expansion_limit=50\r\n"
         b"cost_factor=13,12,11\r\n"
         b"script_label=A\r\n"
         b"script_label=B\r\n"
         b";skip_event=14\r\n"
         b"; End of config\r\n")


def kinds(data: bytes) -> list:
    return [[r.kind for r in pl.reads] for pl in ti.scan(data)]


# ---------------------------------------------------------------- the reader model

def test_comments_keys_sections():
    lines = ti.scan(b"; c\n# c\n[thinker]\nvideo_mode = 1\nx : 2\n\n")
    assert [pl.reads[0].kind for pl in lines] == ["comment", "comment", "section", "key", "key", "blank"]
    assert lines[3].reads[0].name == b"video_mode" and lines[3].reads[0].value == b"1"
    assert lines[4].reads[0].name == b"x" and lines[4].reads[0].value == b"2"


def test_names_are_case_sensitive():
    assert ti.warnings(b"[thinker]\nVideo_Mode=1\n", KNOWN) == [(2, b"thinker", b"Video_Mode")]
    assert ti.warnings(b"[thinker]\nvideo_mode=1\n", KNOWN) == []


def test_inline_comment_needs_whitespace():
    v = ti.scan(b"[thinker]\nvideo_mode=1 ; note\nexpansion_limit=5;x\n")
    assert v[1].reads[0].value == b"1"
    assert v[2].reads[0].value == b"5;x"


def test_continuation_survives_blank_and_comment_lines_but_not_a_header():
    lines = ti.scan(b"[thinker]\nscript_label=A\n\n; c\n  B\n[thinker]\n  C\n")
    assert lines[4].reads[0].kind == "cont" and lines[4].reads[0].name == b"script_label"
    assert lines[6].reads[0].kind != "cont"           # the header cleared prev_name


def test_indented_header_is_a_continuation():
    lines = ti.scan(b"[thinker]\nvideo_mode=1\n  [other]\n")
    assert lines[2].reads[0].kind == "cont"


def test_line_without_separator_raises_nothing_and_keeps_prev_name():
    lines = ti.scan(b"[thinker]\nvideo_mode=1\njunk\n  2\n")
    assert lines[2].reads[0].kind == "error"
    assert lines[3].reads[0].kind == "cont" and lines[3].reads[0].name == b"video_mode"
    assert ti.warnings(b"[thinker]\njunk\n", KNOWN) == []


def test_continuation_name_is_truncated_to_49():
    name = b"n" * 60
    lines = ti.scan(b"[thinker]\n" + name + b"=1\n  2\n")
    assert lines[1].reads[0].name == name
    assert lines[2].reads[0].name == name[:49]


def test_section_other_than_thinker_warns():
    assert ti.warnings(b"[other]\nvideo_mode=1\n", KNOWN) == [(2, b"other", b"video_mode")]
    assert ti.warnings(b"video_mode=1\n", KNOWN) == [(1, b"", b"video_mode")]   # no header at all


def test_bom_is_skipped_and_counts_as_indentation():
    lines = ti.scan(b"\xef\xbb\xbf[thinker]\nvideo_mode=1\n")
    assert lines[0].reads[0].kind == "section" and lines[0].reads[0].section == b"thinker"


def test_crlf_is_text_mode_and_0x1a_ends_the_file():
    lines = ti.scan(b"[thinker]\r\nvideo_mode=1\r\n\x1azzz=1\r\n")
    assert lines[1].eol == b"\r\n" and lines[1].reads[0].value == b"1"
    assert lines[-1].reads == [] and lines[-1].raw.startswith(b"\x1a")
    assert ti.warnings(b"[thinker]\n\x1azzz=1\n", KNOWN) == []


def test_nul_ends_the_line_text():
    lines = ti.scan(b"[thinker]\nvideo_mode=1\x00zzz=1\n")
    assert [r.name for r in lines[1].reads] == [b"video_mode"]


def test_long_line_is_several_reads():
    line = b"video_mode=" + b"1" * 300                # 311 bytes: reads of 255 and 56 (+ newline)
    lines = ti.scan(b"[thinker]\n" + line + b"\n")
    assert len(lines[1].reads) == 2
    assert lines[1].reads[1].kind == "error"          # "111..." has no '=': no handler, no warning


def test_255_byte_line_is_one_read_plus_a_blank():
    line = b"video_mode=" + b"1" * 244                # exactly 255 content bytes
    lines = ti.scan(b"[thinker]\n" + line + b"\n")
    assert [r.kind for r in lines[1].reads] == ["key", "blank"]


def test_long_comment_hides_every_read():
    raw = b"zzz=" + b"=" * 600                        # a tail of '=' would reach the handler as name ''
    out = ti._join(ti._commented(raw, b"\r\n"))
    assert ti.warnings(b"[thinker]\r\n" + out, KNOWN) == []
    assert all(len(line) <= ti.COMMENT_CHUNK + 1 for line in out.split(b"\r\n"))


# ---------------------------------------------------------------- merge (thinker.ini)

def test_untouched_player_file_gives_the_stock_file():
    r = ti.merge(STOCK, STOCK, KNOWN, "5.5")
    assert r.data == STOCK and r.appended == [] and r.commented == []


def test_player_values_are_carried_in_place():
    player = STOCK.replace(b"expansion_limit=50", b"expansion_limit=77")
    r = ti.merge(player, STOCK, KNOWN, "5.5")
    assert b"expansion_limit=77\r\n" in r.data and b"expansion_limit=50" not in r.data
    assert r.data.index(b"expansion_limit=77") < r.data.index(b"cost_factor")


def test_repeated_key_is_carried_as_a_set_at_its_first_stock_place():
    player = b"[thinker]\nscript_label=X\nvideo_mode=1\nscript_label=Y\nscript_label=Z\n"
    r = ti.merge(player, STOCK, KNOWN, "5.5")
    body = r.data
    assert body.count(b"script_label=") == 3
    assert body.index(b"script_label=X") < body.index(b"script_label=Y") < body.index(b"script_label=Z")
    assert b"script_label=A" not in body and b"script_label=B" not in body


def test_known_key_absent_from_stock_is_appended_active():
    player = b"[thinker]\nDirectDraw=1\nskip_event=14\n"
    r = ti.merge(player, STOCK, KNOWN, "5.5")
    assert r.appended == [b"DirectDraw", b"skip_event"]
    tail = r.data.split(b"; End of config\r\n", 1)[1]
    assert tail.startswith(b"DirectDraw=1\r\nskip_event=14\r\n")
    assert ti.warnings(r.data, KNOWN) == []


def test_unknown_settings_are_commented_under_the_approved_header():
    player = b"[thinker]\nvideo_mode=1\nnerve_staple=3\n  2\n[other]\nfoo=1\njunk\n"
    r = ti.merge(player, STOCK, KNOWN, "5.5")
    head = ti.header_line("5.5")
    assert head == (b"; Settings from your previous thinker.ini that Thinker Mod 5.5 does not use. "
                    b"They are kept here for reference and have no effect.")
    block = r.data.split(head + b"\r\n", 1)[1]
    assert block == b";nerve_staple=3\r\n;  2\r\n;[other]\r\n;foo=1\r\n;junk\r\n"
    assert ti.console_names(r.commented) == "nerve_staple, foo"
    assert ti.warnings(r.data, KNOWN) == []


def test_development_build_pin_header_text():
    assert ti.header_line("rel. Nov 9 2025").endswith(b"Thinker Mod rel. Nov 9 2025 does not use. "
                                                      b"They are kept here for reference and have no effect.")


def test_md_carries_only_values_the_player_changed():
    old = {"video_mode": ["0"], "expansion_limit": ["40"], "cost_factor": ["12,11,10"], "script_label": ["A"]}
    player = b"[thinker]\nvideo_mode=0\nexpansion_limit=40\ncost_factor=9,9,9\nscript_label=A\n"
    r = ti.merge(player, STOCK, KNOWN, "5.5", old_stock=old)
    assert r.carried == [b"cost_factor"]
    assert b"expansion_limit=50" in r.data            # untouched old default: the new default wins
    assert b"cost_factor=9,9,9" in r.data


def test_md_none_carries_every_value():
    player = b"[thinker]\nexpansion_limit=40\n"
    assert b"expansion_limit=40" in ti.merge(player, STOCK, KNOWN, "5.5", old_stock=None).data


def test_second_merge_keeps_the_earlier_block():
    first = ti.merge(b"[thinker]\nzzz=1\n", STOCK, KNOWN, "5.4").data
    second = ti.merge(first + b"yyy=2\r\n", STOCK, KNOWN, "5.5")
    assert second.data.count(b";zzz=1") == 1 and b";yyy=2" in second.data
    assert second.data.count(b"; Settings from your previous") == 1


def test_oversized_or_binary_file_is_not_parsed():
    r = ti.merge(b"[thinker]\nvideo_mode=1\x00\n", STOCK, KNOWN, "5.5")
    assert r.unparsed and r.data == STOCK
    r = ti.merge(b"x" * (ti.MAX_INI_BYTES + 1), STOCK, KNOWN, "5.5")
    assert r.unparsed and r.data == STOCK


def test_player_bytes_are_copied_unchanged():
    player = "[thinker]\r\nexpansion_limit=7 ; état\r\n".encode("cp1252")
    r = ti.merge(player, STOCK, KNOWN, "5.5")
    assert "expansion_limit=7 ; état\r\n".encode("cp1252") in r.data


# ---------------------------------------------------------------- comment in place (thinker_user.ini)

def test_user_ini_comments_only_rejected_lines():
    data = b"[thinker]\r\nvideo_mode=1\r\nnerve_staple=3\r\n  2\r\n; mine\r\n[foo]\r\nbar=1\r\n"
    r = ti.comment_unknown(data, KNOWN)
    assert r.data == (b"[thinker]\r\nvideo_mode=1\r\n;nerve_staple=3\r\n;  2\r\n; mine\r\n"
                      b"[foo]\r\n;bar=1\r\n")
    assert r.changed and ti.console_names(r.commented) == "nerve_staple, bar"


def test_user_ini_without_header_is_rejected_by_thinker_too():
    r = ti.comment_unknown(b"video_mode=1\n", KNOWN)
    assert r.data == b";video_mode=1\n"


def test_user_ini_clean_file_is_unchanged():
    data = b"[thinker]\nvideo_mode=1\n\x1atrailing garbage"
    r = ti.comment_unknown(data, KNOWN)
    assert r.data == data and not r.changed


def test_console_names_filter_and_cap():
    names = [b"a%b", b"DirectDraw"] + [b"k%d" % i for i in range(12)]
    s = ti.console_names(names, limit=10)
    assert s.startswith("ab, DirectDraw, k0") and s.endswith("and 4 more")


# ---------------------------------------------------------------- the compiled data

def test_compiled_data_shape():
    assert td.PIN_VERSION == "5.5.0" and td.PIN_TAG == "v5.5"
    assert len(td.PIN_FILES) == 28 and "thinker.dll" in td.PIN_FILES
    assert td.PIN_DLL_SHA256 == td.PIN_FILES["thinker.dll"]
    assert {"video_mode", "DirectDraw", "skip_event", "script_label"} <= td.KNOWN_KEYS
    assert td.STOCK_VALUES["v5.3"]["nerve_staple"] and "nerve_staple" not in td.KNOWN_KEYS


# refs/ is gitignored, so a worktree has none: LONGEVITY_REFS may point at the main checkout's.
_REFS = Path(os.environ.get("LONGEVITY_REFS") or Path(__file__).resolve().parents[2] / "refs")


@pytest.mark.skipif(not (_REFS / "thinker").is_dir(), reason="refs/thinker not present (gitignored)")
def test_compiled_data_is_current():
    r = subprocess.run([sys.executable, str(_SCRIPTS / "gen_thinker_data.py"), "--check", "--refs", str(_REFS)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(not (_REFS / "thinker-release" / "v5.5").is_dir(), reason="refs/thinker-release not present")
def test_real_stock_file_reads_clean_and_merges_from_5_3():
    stock = (_REFS / "thinker-release" / "v5.5" / "thinker.ini").read_bytes()
    known = {k.encode() for k in td.KNOWN_KEYS}
    assert ti.warnings(stock, known) == []
    old = subprocess.run(["git", "-C", str(_REFS / "thinker"), "show", "v5.3:docs/thinker.ini"],
                         capture_output=True).stdout
    r = ti.merge(old, stock, known, "5.5", old_stock=td.STOCK_VALUES["v5.3"])
    assert r.carried == [] and ti.console_names(r.commented) == "nerve_staple"
    assert r.data.startswith(stock.rstrip(b"\r\n"))



def test_an_indented_player_key_is_carried_unindented():
    """Round-7 review D2: pasted after a stock key, an indented line would become its continuation."""
    r = ti.merge(b"[thinker]\r\n  expansion_limit=7\r\n", STOCK, KNOWN, "5.5")
    assert b"\r\nexpansion_limit=7\r\n" in r.data
    vals = [rd for pl in ti.scan(r.data) for rd in pl.reads if rd.kind in ("key", "cont")]
    assert ("expansion_limit", "7") in [(x.name.decode(), x.value.decode()) for x in vals]
    assert not any(x.kind == "cont" for x in vals)


def test_a_long_known_line_with_an_unknown_tail_never_raises():
    """Round-7 review D3: a known key whose second 255-byte read is an unknown key is commented, not carried."""
    line = b"expansion_limit=3 ;" + b"x" * 250 + b" note: foo"
    r = ti.merge(b"[thinker]\n" + line + b"\n", STOCK, KNOWN, "5.5")
    assert ti.warnings(r.data, KNOWN) == []


def test_a_known_line_of_exactly_255_bytes_is_carried():
    line = b"expansion_limit=" + b"1" * 239
    assert len(line) == 255
    r = ti.merge(b"[thinker]\n" + line + b"\n", STOCK, KNOWN, "5.5")
    assert line in r.data and b";" + line[:20] not in r.data
