"""The last five typed [Y/n] / [y/N] questions become arrow-key choices (user-approved 2026-11-15): the game
resolution, the desktop shortcut (one question for both cases), the Thinker changelog (no title), and "Start the
game" (the marker on "Close this window" after a run that changed nothing; that row closes the window at once).
Ctrl-C / EOF behave as each prompt did; every no-console / --no-prompt path keeps its lines. Keys are fed at
_read_key, and once at the console-record level (_poll_key), as test_install_console does."""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import thinker_flow as tf           # noqa: E402

inst._load_modules()

pytestmark = pytest.mark.usefixtures("install_globals")

KEYS = " Up/Down: move   Enter: choose"


def _keys(monkeypatch, *keys):
    """A console that hands out `keys` (then fails the test if more are wanted); input() is never used."""
    it = iter(keys)

    def read():
        try:
            k = next(it)
        except StopIteration:
            pytest.fail("the question wanted more keys than the test supplied")
        if isinstance(k, BaseException):
            raise k
        return k
    monkeypatch.setattr(ix, "stdin_is_console", lambda: True)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    monkeypatch.setattr(inst, "_read_key", read)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("a typed answer was asked for"))


def _block(out: str, title: str, notes: list, rows: list) -> str:
    head = f"{ix.RULE}\n {title.upper()}\n" + "".join(f" {n}\n" for n in notes) + f"{ix.RULE}\n{KEYS}\n"
    return head + "".join(r + "\n" for r in rows) + ix.RULE + "\n"


# ---------------------------------------------------------------- 1: game resolution

def _res_game(tmp_path) -> Path:
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text("[PRACX]\nScreenWidth=1920\nScreenHeight=1080\n", encoding="ascii")
    return g


RES_ROWS = [" -> Use your display's resolution (3840x2160)", "    Keep 1920x1080 (the game will look stretched)"]


def test_resolution_is_an_arrow_choice_and_enter_uses_the_display(tmp_path, monkeypatch, capsys):
    g = _res_game(tmp_path)
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    _keys(monkeypatch, "enter")
    inst.check_display_resolution(g, "pracx")
    out = capsys.readouterr().out
    assert "WARNING: Alpha Centauri.ini sets the game to 1920x1080, but your display is 3840x2160." in out
    assert _block(out, "Game resolution", [], RES_ROWS) in out
    assert inst.read_ini_str(g, "PRACX", "ScreenWidth", "") == "<DEFAULT>"
    assert "the game now follows your display (3840x2160)" in out


@pytest.mark.parametrize("keys", [("down", "enter"), (KeyboardInterrupt(),), (EOFError(),)],
                         ids=["keep", "ctrl-c", "eof"])
def test_resolution_keep_or_a_stop_leaves_the_ini(tmp_path, monkeypatch, capsys, keys):
    g = _res_game(tmp_path)
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    _keys(monkeypatch, *keys)
    inst.check_display_resolution(g, "pracx")
    assert inst.read_ini_str(g, "PRACX", "ScreenWidth", "") == "1920"
    assert "Left your resolution as is." in capsys.readouterr().out


def test_resolution_without_a_console_keeps_its_hint(tmp_path, monkeypatch, capsys):
    g = _res_game(tmp_path)
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    inst.check_display_resolution(g, "pracx")
    out = capsys.readouterr().out
    assert "Set [PRACX] ScreenWidth and ScreenHeight to <DEFAULT> in Alpha Centauri.ini to fix this." in out
    assert "GAME RESOLUTION" not in out


# ---------------------------------------------------------------- 2+3: the desktop shortcut, one question

@pytest.fixture
def desk(tmp_path, monkeypatch):
    d = tmp_path / "Desktop"
    d.mkdir()
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [d])
    monkeypatch.setattr(inst, "_SHORTCUT_NAME", None)
    monkeypatch.setattr(inst, "find_shortcut_to", lambda exe: None)
    made = []

    def create(lnk, exe, icon=None):
        made.append(Path(lnk))
        Path(lnk).write_bytes(b"lnk")
        return ""
    monkeypatch.setattr(inst, "create_shortcut", create)
    return d, made


@pytest.fixture
def sgame(tmp_path):
    g = tmp_path / "Game Folder"
    g.mkdir()
    (g / "terranx_PRACX.exe").write_bytes(b"MZ")
    return g


NO_SHORTCUT = "You do not have a desktop shortcut that starts the game with Longevity Vaccine."
CREATE_ROWS = [f' -> Create the "{inst.MOD_SHORTCUT_NAME}" shortcut on your desktop', "    Don't create a shortcut"]


def test_no_shortcut_is_one_arrow_choice_and_enter_creates_it(desk, sgame, monkeypatch, capsys):
    d, made = desk
    _keys(monkeypatch, "enter")
    inst.check_desktop_shortcut(sgame, "pracx")
    out = capsys.readouterr().out
    assert _block(out, "Desktop shortcut", [NO_SHORTCUT], CREATE_ROWS) in out
    assert made == [d / (inst.MOD_SHORTCUT_NAME + ".lnk")]
    assert f'Created "{inst.MOD_SHORTCUT_NAME}" on your desktop.' in out


def test_dont_create_says_the_existing_line(desk, sgame, monkeypatch, capsys):
    d, made = desk
    _keys(monkeypatch, "down", "enter")
    inst.check_desktop_shortcut(sgame, "pracx")
    assert made == []
    assert "No shortcut created. Start terranx_PRACX.exe from the game folder to play with Longevity Vaccine." \
        in capsys.readouterr().out


def test_a_shortcut_of_that_name_is_the_replace_question_asked_once(desk, sgame, monkeypatch, capsys):
    d, made = desk
    (d / (inst.MOD_SHORTCUT_NAME + ".lnk")).write_bytes(b"something else")
    _keys(monkeypatch, "enter")                               # one question only: a second would fail the test
    inst.check_desktop_shortcut(sgame, "pracx")
    out = capsys.readouterr().out
    note = f'A desktop shortcut named "{inst.MOD_SHORTCUT_NAME}" already exists but starts something else.'
    rows = [f' -> Replace "{inst.MOD_SHORTCUT_NAME}" with a shortcut that starts Longevity Vaccine',
            "    Don't create a shortcut"]
    assert _block(out, "Desktop shortcut", [note], rows) in out
    assert made == [d / (inst.MOD_SHORTCUT_NAME + ".lnk")] and "Replace it?" not in out


def test_declining_the_replace_keeps_the_existing_line(desk, sgame, monkeypatch, capsys):
    d, made = desk
    (d / (inst.MOD_SHORTCUT_NAME + ".lnk")).write_bytes(b"something else")
    _keys(monkeypatch, "down", "enter")
    inst.check_desktop_shortcut(sgame, "pracx")
    assert made == [] and (d / (inst.MOD_SHORTCUT_NAME + ".lnk")).read_bytes() == b"something else"
    assert "Left as it is. Start terranx_PRACX.exe from the game folder to play with Longevity Vaccine." \
        in capsys.readouterr().out


def test_ctrl_c_at_the_shortcut_question_makes_none(desk, sgame, monkeypatch, capsys):
    d, made = desk
    _keys(monkeypatch, KeyboardInterrupt())
    inst.check_desktop_shortcut(sgame, "pracx")
    assert made == [] and "No shortcut created." in capsys.readouterr().out


def test_no_desktop_folder_is_handled_as_before(sgame, monkeypatch, capsys):
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    monkeypatch.setattr(inst, "find_shortcut_to", lambda exe: None)
    _keys(monkeypatch, "enter")
    inst.check_desktop_shortcut(sgame, "pracx")
    assert "Could not find your desktop folder. Start terranx_PRACX.exe from the game folder to play with " \
           "Longevity Vaccine." in capsys.readouterr().out


def test_the_shortcut_without_a_console_keeps_its_lines(desk, sgame, monkeypatch, capsys):
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    inst.check_desktop_shortcut(sgame, "pracx")
    out = capsys.readouterr().out
    assert f"\n{NO_SHORTCUT}\nRun the installer again to create one, or start terranx_PRACX.exe from the game " \
           "folder.\n" in out and "DESKTOP SHORTCUT" not in out


# ---------------------------------------------------------------- 4: the Thinker changelog, no title

def _cl_game(tmp_path):
    from test_thinker_flow import _cl_game as real
    return real(tmp_path, None)


def test_the_changelog_is_an_untitled_arrow_choice(tmp_path, monkeypatch, capsys):
    g = _cl_game(tmp_path)
    opened = []
    monkeypatch.setattr(tf, "_open_changelog", lambda *a: opened.append(a))
    _keys(monkeypatch, "enter")
    tf.offer_changelog(g, 1999999999)
    out = capsys.readouterr().out
    assert f"\n{KEYS}\n -> Open the Thinker Mod 5.5 changelog\n    Don't open it\n" in out
    assert ix.RULE not in out and "CHANGELOG" not in out
    assert len(opened) == 1


@pytest.mark.parametrize("keys", [("down", "enter"), (KeyboardInterrupt(),), (EOFError(),)],
                         ids=["dont", "ctrl-c", "eof"])
def test_the_changelog_not_opened(tmp_path, monkeypatch, keys):
    g = _cl_game(tmp_path)
    opened = []
    monkeypatch.setattr(tf, "_open_changelog", lambda *a: opened.append(a))
    _keys(monkeypatch, *keys)
    tf.offer_changelog(g, 1999999999)
    assert opened == []


# ---------------------------------------------------------------- 5: start the game

@pytest.fixture
def exe(tmp_path, monkeypatch):
    e = tmp_path / "thinker.exe"
    e.write_bytes(b"MZ")
    monkeypatch.setattr(ix, "interactive", lambda: True)
    started = []
    monkeypatch.setattr(ix.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    return e, started


START_ROWS = ["Start the game (thinker.exe)", "Close this window"]


@pytest.mark.parametrize("default,marked", [(True, 0), (False, 1)], ids=["changed", "unchanged"])
def test_start_the_game_is_an_arrow_choice_with_the_marker_by_outcome(exe, monkeypatch, capsys, default, marked):
    e, started = exe
    _keys(monkeypatch, "enter")
    closes = ix.offer_relaunch(e, default=default)
    out = capsys.readouterr().out
    rows = [(" -> " if i == marked else "    ") + r for i, r in enumerate(START_ROWS)]
    assert _block(out, "Start the game", [], rows) in out
    assert closes is True                                     # either row closes the window without a keypress
    assert started == ([[str(e)]] if marked == 0 else [])


def test_close_this_window_after_a_change(exe, monkeypatch):
    e, started = exe
    _keys(monkeypatch, "down", "enter")
    assert ix.offer_relaunch(e, default=True) is True and started == []


def test_start_after_no_change_takes_an_explicit_up(exe, monkeypatch):
    e, started = exe
    _keys(monkeypatch, "up", "enter")
    assert ix.offer_relaunch(e, default=False) is True and started == [[str(e)]]


@pytest.mark.parametrize("stop", [KeyboardInterrupt(), EOFError()], ids=["ctrl-c", "eof"])
def test_a_stop_at_start_the_game_waits_as_before(exe, monkeypatch, stop):
    e, started = exe
    _keys(monkeypatch, stop)
    assert ix.offer_relaunch(e) is False and started == []


def test_close_this_window_skips_the_keypress_wait(exe, monkeypatch):
    e, started = exe
    _keys(monkeypatch, "down", "enter")
    waited = []
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: waited.append(a))
    monkeypatch.setattr(ix, "write_guard_marker", lambda: None)
    assert ix.run_guarded(lambda: ix.EXIT_OK, relaunch_exe=e) == ix.EXIT_OK
    assert waited == [] and started == []


def test_start_the_game_from_console_records(exe, monkeypatch):
    """The real console path: _poll_key records (VT arrows as ESC [ B, Enter as CR) through _read_key."""
    e, started = exe
    queue = [(0, "\x1b"), (0, "["), (0, "B"), (0x0D, "\r")]
    monkeypatch.setattr(inst, "_poll_key", lambda: queue.pop(0) if queue else None)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(ix, "stdin_is_console", lambda: True)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    assert ix.offer_relaunch(e, default=True) is True and started == [] and queue == []


def test_no_prompt_never_offers_to_start(exe, monkeypatch):
    e, started = exe
    ix.set_player_no_prompt(True)
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("asked under --no-prompt"))
    assert ix.offer_relaunch(e) is False


# ---------------------------------------------------------------- none of the installer's prompts is typed

def test_no_typed_yes_no_prompt_remains():
    """No call to ask / ask_line / input() in the installer puts a [Y/n] or [y/N] question any more."""
    import ast
    hits = []
    for name in ("install.py", "installer_exit.py", "thinker_flow.py", "bootstrap.py"):
        tree = ast.parse((_SCRIPTS / name).read_text("utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if fn not in ("ask", "ask_line", "input"):
                continue
            text = " ".join(c.value for a in node.args for c in ast.walk(a)
                            if isinstance(c, ast.Constant) and isinstance(c.value, str))
            if "[Y/n]" in text or "[y/N]" in text:
                hits.append(f"{name}:{node.lineno}")
    assert hits == [], hits
