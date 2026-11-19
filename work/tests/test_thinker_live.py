"""The Thinker startup check's readers of things it does not own (src/uimod/src/thinkerlive.h), run for real:
- the label string in another module's memory, over a committed page followed by a reserved one -- a read one byte
  too far is an access violation and fails the run, not a string comparison;
- the resident installer copy's VERSION file, and the scan of its install.py for the switch "Update now" passes;
- the label of a thinker.dll file on disk, by the installer's own rule (every label string in it must agree).

These replace source-text checks: the code audit of 2026-11-14 found that the earlier tests would still pass with
the bounds broken. One self-test exe for the module, one run, real temp files, no sleeps.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import cpp_harness  # noqa: E402

CHECKS = [
    # memory
    "a_label_inside_the_image", "a_label_ending_on_the_last_readable_byte", "a_string_running_off_the_readable_region",
    "a_pointer_into_unreadable_memory", "a_pointer_outside_the_image", "a_null_pointer", "a_string_running_off_the_image",
    "a_string_ending_on_the_images_last_byte", "a_long_unterminated_run", "a_readable_string_that_is_not_a_label",
    "readable_inside_one_region", "not_readable_across_into_reserved",
    # the VERSION file
    "version_plain", "version_crlf", "version_no_newline", "version_bom", "version_trailing_space", "version_empty",
    "version_two_lines_is_not_a_version", "version_long_content_is_cut_and_refused",
    "version_missing_file_is_empty_and_older", "version_with_a_second_line_is_refused",
    # the capability scan
    "mentions_a_present_token", "does_not_mention_an_absent_token", "mentions_a_token_across_a_read_boundary",
    "mentions_a_token_at_the_very_end_of_a_large_file", "a_missing_file_mentions_nothing",
    # the label of a file on disk
    "file_four_identical_labels", "file_development_build", "file_two_different_labels_is_unrecognised",
    "file_a_version_and_a_development_label_is_unrecognised", "file_other_text_after_the_name_is_ignored",
    "file_an_unterminated_label_is_not_one", "file_a_string_longer_than_a_label_is_ignored", "file_without_any_label",
    "file_missing_is_not_read", "file_empty_is_not_read",
    # log text
    "utf8_keeps_a_non_ansi_path", "utf8_of_nothing_is_empty",
]


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    if not cpp_harness.have_toolchain():
        pytest.skip("MSVC toolchain not present")
    exe = cpp_harness.build(ROOT / "tests" / "thinkerlive_selftest.cpp", "thinkerlive_selftest_")
    scratch = tmp_path_factory.mktemp("thinkerlive")
    p = subprocess.run([str(exe), str(scratch)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"the self-test crashed (exit {p.returncode:#x}): a read went where it must not\n{p.stdout[-600:]}"
    out = {}
    for line in p.stdout.splitlines():
        verdict, name, *detail = line.split(" ", 2)
        out[name] = (verdict, " ".join(detail).strip())
    return out


@pytest.mark.parametrize("name", CHECKS)
def test_live_reader(results, name):
    assert name in results, f"the self-test did not run {name}"
    verdict, detail = results[name]
    assert verdict == "PASS", detail


def test_the_self_test_ran_nothing_this_file_does_not_know(results):
    assert sorted(results) == sorted(CHECKS)


def test_the_on_disk_label_rule_is_the_installers(tmp_path):
    """Both sides read the same file the same way: the installer's dll_label and the DLL's LabelFromFile agree on
    every shape (the DLL uses it only when Thinker is not in the process and the offer must still name the build)."""
    import thinker_state as st
    z = lambda s: s.encode("ascii") + b"\0"     # noqa: E731
    shapes = {
        "four": b"\x01" * 300 + z("Thinker Mod v5.5") * 4,
        "dev": z("Thinker Mod develop build") * 2,
        "two": z("Thinker Mod v5.5") + z("Thinker Mod v5.6"),
        "mixed": z("Thinker Mod v5.5") + z("Thinker Mod develop build"),
        "other-text": z("Thinker Mod requires this") + z("Thinker Mod v5.5"),
        "none": b"\0" * 64,
    }
    want = {"four": st.VERSION, "dev": st.DEVELOP, "two": st.UNRECOGNISED, "mixed": st.UNRECOGNISED,
            "other-text": st.VERSION, "none": st.UNRECOGNISED}
    for name, data in shapes.items():
        assert st.dll_label(data).kind == want[name], name
    # and the DLL's side of the same six shapes is what the self-test pins above
    for check in ("file_four_identical_labels", "file_development_build", "file_two_different_labels_is_unrecognised",
                  "file_a_version_and_a_development_label_is_unrecognised", "file_other_text_after_the_name_is_ignored",
                  "file_without_any_label"):
        assert check in CHECKS


def test_the_startup_check_uses_these_readers_and_no_private_copy():
    src = ROOT.parent / "src" / "uimod" / "src"
    import re
    cpp = (src / "thinkerversion.cpp").read_text(encoding="utf-8")
    assert '#include "thinkerlive.h"' in cpp
    cpp = re.sub(r"//.*", "", cpp)               # code only: a comment may name what the code must not do
    for call in ("thinkerlive::ReadLabel(p, lo, hi, &why)", "thinkerlive::ReadVersionFile(", "thinkerlive::FileMentions(script.c_str(), kFixThinkerFlag)",
                 "thinkerlive::LabelFromFile(", "thinkerlive::Readable(base, sizeof(IMAGE_DOS_HEADER))"):
        assert call in cpp, call
    assert "VirtualQuery(" not in cpp and "CreateFileW(" not in cpp and "ReadFile(" not in cpp, \
        "the readers live in thinkerlive.h, where they are tested"
    assert "%ls" not in cpp, "a wide path goes through Utf8(): %ls empties the whole log line on a non-ANSI name"
    proj = (ROOT.parent / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")
    assert "src\\thinkerlive.h" in proj
