"""The installer's display-resolution check: a [PRACX] ScreenWidth/ScreenHeight pinned to a
resolution other than the display's current mode makes PRACX run the game stretched
(pracx.cpp SetVideoMode -> ChangeDisplaySettings). The installer warns and offers to put
"<DEFAULT>" back, which PRACX resolves to the display's own mode at every launch."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst        # noqa: E402


@pytest.mark.parametrize("w,h,display,want", [
    ("1920", "1080", (3840, 2160), (1920, 1080)),      # pinned below native: stretched
    ("1600", "1200", (3840, 2160), (1600, 1200)),      # different aspect: distorted too
    ("3840", "2160", (3840, 2160), None),              # pinned to native: fine
    ("<DEFAULT>", "<DEFAULT>", (3840, 2160), None),    # PRACX follows the display
    ("", "", (3840, 2160), None),                      # keys absent
    ("1920", "<DEFAULT>", (3840, 2160), None),         # half-pinned: not numeric -> left alone
    ("abc", "1080", (3840, 2160), None),
    ("0", "0", (3840, 2160), None),
    ("1920", "1080", None, None),                      # display unknown: nothing to compare
    (" 1920 ", " 1080 ", (1920, 1080), None),
])
def test_mismatch_decision(w, h, display, want):
    assert inst.resolution_mismatch(w, h, display) == want


def _game(tmp_path, pracx: str) -> Path:
    g = tmp_path / "game"
    g.mkdir(parents=True)
    (g / "Alpha Centauri.ini").write_text(f"[PRACX]\n{pracx}\n[UIMod]\nUpscaledVideos=0\n", encoding="ascii")
    return g


import installer_exit as ix   # noqa: E402


def test_yes_resets_both_keys_to_default(tmp_path, monkeypatch, capsys):
    g = _game(tmp_path, "ScreenWidth=1920\nScreenHeight=1080\nZoomLevels=<DEFAULT>")
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    monkeypatch.setattr(ix, "can_ask", lambda: True)                     # a keyboard is attached
    monkeypatch.setattr("builtins.input", lambda prompt="": "")          # Enter = the default, yes
    inst.check_display_resolution(g, "pracx")
    out = capsys.readouterr().out
    assert "1920x1080" in out and "3840x2160" in out and "stretched" in out
    assert inst.read_ini_str(g, "PRACX", "ScreenWidth", "") == "<DEFAULT>"
    assert inst.read_ini_str(g, "PRACX", "ScreenHeight", "") == "<DEFAULT>"
    assert inst.read_ini_str(g, "PRACX", "ZoomLevels", "") == "<DEFAULT>", "other keys untouched"
    assert inst.read_ini_str(g, "UIMod", "UpscaledVideos", "") == "0"
    assert "follows your display (3840x2160)" in out


def test_no_leaves_the_ini_alone(tmp_path, monkeypatch, capsys):
    g = _game(tmp_path, "ScreenWidth=1920\nScreenHeight=1080")
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    inst.check_display_resolution(g, "pracx")
    assert inst.read_ini_str(g, "PRACX", "ScreenWidth", "") == "1920"
    assert "Left your resolution as is. Your game will likely appear stretched" in capsys.readouterr().out


def test_the_question_is_asked_even_under_the_workers_no_prompt(tmp_path, monkeypatch, capsys):
    """The bootstrap's worker always carries --no-prompt (optional extras) but runs in the
    console the player is watching: with a keyboard attached the question must still be put."""
    g = _game(tmp_path, "ScreenWidth=1920\nScreenHeight=1080")
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    inst.check_display_resolution(g, "pracx", no_prompt=True)
    assert inst.read_ini_str(g, "PRACX", "ScreenWidth", "") == "<DEFAULT>"


def test_without_a_keyboard_it_only_warns(tmp_path, monkeypatch, capsys):
    g = _game(tmp_path, "ScreenWidth=1920\nScreenHeight=1080")
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    monkeypatch.setattr(ix, "can_ask", lambda: False)                    # piped / scripted stdin
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    inst.check_display_resolution(g, "pracx")
    out = capsys.readouterr().out
    assert "WARNING" in out and "<DEFAULT>" in out
    assert inst.read_ini_str(g, "PRACX", "ScreenWidth", "") == "1920"
    # a keyboard that then goes away (EOF) is the same: left alone, told how to fix it
    monkeypatch.setattr(ix, "can_ask", lambda: True)

    def eof(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    inst.check_display_resolution(g, "pracx")
    assert "Left your resolution as is" in capsys.readouterr().out
    assert inst.read_ini_str(g, "PRACX", "ScreenWidth", "") == "1920"


def test_can_ask_reflects_stdin_and_the_no_wait_env(monkeypatch):
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)

    class Tty:
        def isatty(self):
            return True
    monkeypatch.setattr(sys, "stdin", Tty())
    assert ix.can_ask() is True
    monkeypatch.setenv("LONGEVITY_NO_WAIT", "1")
    assert ix.can_ask() is False


def test_nothing_said_when_it_matches_or_is_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    cases = ("ScreenWidth=3840\nScreenHeight=2160", "ScreenWidth=<DEFAULT>\nScreenHeight=<DEFAULT>", "")
    for i, pracx in enumerate(cases):
        g = _game(tmp_path / f"case{i}", pracx)
        inst.check_display_resolution(g, "pracx")
    inst.check_display_resolution(_game(tmp_path / "vanilla", "ScreenWidth=1920\nScreenHeight=1080"), "vanilla")
    assert capsys.readouterr().out == ""


def test_the_display_mode_reader_returns_physical_pixels():
    mode = inst.current_display_mode()
    if mode is None:
        pytest.skip("no display (headless)")
    w, h = mode
    assert w >= 640 and h >= 480 and w >= h
