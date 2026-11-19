"""uimod pracxfocus_core.h -- the game window gets keyboard focus back when PRACX's Preferences panel closes on Wine
(issue longevity-vaccine #6), and Esc on a panel button closes the panel.

PRACX gates its map wheel zoom and right-drag scroll on GetFocus() == the game window and never sets focus itself;
Wine leaves nobody with focus when the panel is destroyed with one of its buttons focused. The self-test builds real
Win32 windows laid out like PRACX's (game window, PRACXSettingsWnd child, buttons) on its own thread, off-screen, and
drives OnMessage through each case; the Wine close is emulated by clearing focus after the destroy (Windows itself
hands focus back), so it shows the fix reacts to Wine's end state, not that Wine reaches it. One exe, one run, one
line per case. Not covered here: pracxfocus.cpp's hook glue (PM_REMOVE gate, g_game_hwnd address, logging) -- the
in-game check covers that (user-verified 2026-11-13 on Windows).
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402

CASES = [
    "restore", "focused_noop", "other_child_untouched", "panel_open_noop", "other_active_noop", "no_game_noop",
    "esc_routed", "esc_elsewhere_unchanged", "other_keys_unchanged", "wine_close_restored", "minimised_noop",
    "disabled_noop", "stale_hwnd_noop",
]


@pytest.fixture(scope="module")
def results() -> dict[str, str]:
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    exe = cpp_harness.build(ROOT / "tests" / "pracxfocus_selftest.cpp", "pracxfocus_selftest_")
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    lines = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
    assert lines.get("setup") == "ok", r.stdout + r.stderr
    return lines


@pytest.mark.parametrize("case", CASES)
def test_case(results, case):
    assert results.get(case) == "ok", f"{case}: {results.get(case, 'missing')}"


def test_every_case_is_listed(results):
    assert set(results) - {"setup"} == set(CASES)


def test_hook_is_installed_only_with_pracx():
    src = (ROOT.parent / "src" / "uimod" / "src")
    init = (src / "init.cpp").read_text(encoding="utf-8")
    assert "InstallPracxFocusFix(pracx);" in init
    body = (src / "pracxfocus.cpp").read_text(encoding="utf-8")
    assert "if (!pracx)" in body and body.index("if (!pracx)") < body.index("SetWindowsHookExA")
