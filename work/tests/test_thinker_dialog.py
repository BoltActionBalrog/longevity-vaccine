"""The Thinker Mod startup dialog (src/uimod/src/thinkerdialog.h): the in-memory template, the procedure and our own
modal loop.

The self-test creates the REAL dialog through CreateDialogIndirectParamW -- never visible, never foreground, a fake
clock instead of a real 400 ms wait, no beep -- and feeds the production loop body synthetic messages. So the things
a player can do before the game window exists are pinned without a game: mashing Enter or Space through the intro
(ignored for the guard interval, and auto-repeat is ignored after it), Esc (never an answer), the close box / Alt+F4 /
system menu Close (the fourth answer, kClosed, after the guard only), the default button (Update now; Not now when
update checks are off), and that the text and three buttons fit.

One exe per module (cpp_harness), one run, well under a second after the build.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import cpp_harness  # noqa: E402

SRC = ROOT.parent / "src" / "uimod" / "src"
HEADER = (SRC / "thinkerdialog.h").read_text(encoding="utf-8")

CHECKS = [
    "template_dword_aligned", "template_five_items", "template_style", "template_production_is_foreground_topmost_visible",
    "created", "ctx_bound", "title", "close_box", "close_box_enabled", "not_visible_under_test", "not_topmost_under_test",
    "three_buttons_ids_100_101_102", "no_ampersand_in_captions", "every_button_is_a_tab_stop",
    "group_on_first_button_only", "no_reserved_ids", "text_static_noprefix", "text_carried_verbatim", "icon_set",
    "controls_inside_client", "buttons_in_a_row_below_text_equal_width", "buttons_do_not_overlap", "text_fits_its_static",
    "default_update_now_when_checks_on", "default_not_now_when_checks_off",
    "close_requests_inside_guard_do_not_end_it", "keys_inside_guard_ignored", "drop_click_inside_guard",
    "command_inside_guard_ignored", "drop_close_box_press_inside_guard", "auto_repeat_after_guard_ignored",
    "click_after_guard_not_dropped", "close_box_press_after_guard_not_dropped",
    "first_answer_wins_button_then_close", "first_answer_wins_close_then_button",
    "esc_and_letters_do_nothing", "idcancel_and_idok_after_guard_do_nothing",
    "fresh_enter_presses_default", "button_100_answers", "button_101_answers", "button_102_answers",
    "foreign_command_ids_ignored",
    # the close box, Alt+F4 and system menu Close: the fourth answer
    "close_box_answers_closed", "wm_close_answers_closed", "alt_f4_answers_closed", "alt_f4_auto_repeat_ignored",
    "esc_never_answers_closed",
    # focus and the keys that move it
    "focus_starts_on_update_now", "focus_starts_on_not_now_when_checks_off", "arrow_right_wraps_last_to_first",
    "arrow_left_wraps_first_to_last", "tab_moves_to_the_next_button", "space_key_up_alone_does_nothing",
    "fresh_space_presses_the_focused_button",
    # Run(): the real GetMessage loop
    "run_ends_on_an_answer_sent_from_another_thread", "run_destroys_its_window",
    "run_ends_closed_on_a_close_sent_from_another_thread", "run_returns_no_answer_on_quit",
    "run_hands_the_quit_on", "run_restores_the_thread_dpi_context",
]


@pytest.fixture(scope="module")
def results():
    if not cpp_harness.have_toolchain():
        pytest.skip("MSVC toolchain not present")
    exe = cpp_harness.build(ROOT / "tests" / "thinkerdialog_selftest.cpp", "thinkerdialog_selftest_", "user32.lib gdi32.lib")
    p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    out = {}
    for line in p.stdout.splitlines():
        verdict, name, *detail = line.split(" ", 2)
        out[name] = (verdict, " ".join(detail).strip())
    return out


@pytest.mark.parametrize("name", CHECKS)
def test_dialog_check(results, name):
    assert name in results, f"the self-test did not run {name}"
    verdict, detail = results[name]
    assert verdict == "PASS", detail


def test_the_self_test_ran_nothing_this_file_does_not_know(results):
    assert sorted(results) == sorted(CHECKS)


def test_the_loop_is_ours_and_keeps_the_buttons_enabled():
    """DialogBoxIndirectParam cannot filter keys; disabled buttons leave the dialog without a focused control."""
    code = re.sub(r"//.*", "", HEADER)
    assert "DialogBoxIndirectParam" not in code
    assert "CreateDialogIndirectParamW(" in code and "IsDialogMessageW(c.dlg, &m)" in code
    assert "WS_DISABLED" not in code and "EnableWindow" not in code
    assert "(1L << 30)" in code, "auto-repeat key-downs are dropped"
    assert "WS_SYSMENU" in code, "the close box (user 2026-11-14)"
    assert "SC_CLOSE" not in code, "the close box reaches WM_CLOSE through DefWindowProc; nothing filters SC_CLOSE"
    assert "MessageBeep" not in code, "the beep is the caller's, so a test never sounds it"


def test_it_centres_on_the_primary_monitor_and_scales_through_a_thread_dpi_context():
    assert "SPI_GETWORKAREA" in HEADER
    assert '"SetThreadDpiAwarenessContext"' in HEADER, "resolved at run time: absent before Windows 10 1607"
    assert "MonitorFromPoint" not in HEADER and "GetCursorPos" not in HEADER
