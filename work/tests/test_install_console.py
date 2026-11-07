"""The installer's console as a player reads it (user brief, 2026-09-27).

  * the optional modules are LISTED with sizes and the installer WAITS for a choice;
  * the patcher reports one coloured line per phase, names skipped sites without bytes and
    prints the bytes only for a failing site;
  * the summary is Success / Error / Skipped rows, with no row for an executable the mod does
    not touch and no "recorded" bookkeeping line;
  * saying yes to starting the game closes the window instead of waiting for a key.
"""
from __future__ import annotations

import os
import shutil
import sys
import types
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap    # noqa: E402
import install as inst        # noqa: E402
import installer_exit as ix   # noqa: E402

inst._load_modules()

CATALOGUE = {
    "movies-hd": {"size": 1395864371, "source": "manifest", "on_disk": False},
    "portraits-hd": {"size": 671088640, "source": "manifest", "on_disk": True},
}


def _args(**kw):
    # portrait_pack: never this checkout's real dist\portraits-hd (tests choose their packs explicitly)
    base = dict(modules=None, ai="ask", pack=None, portrait_pack=str(_SCRIPTS / "_no_portrait_pack"),
                manifest=None, offline=False, no_prompt=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _answers(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


# ---------------------------------------------------------------- the module picker
#
# Up / Down move the marker, Enter (or Space) ticks or unticks the pack under it, Enter on
# Confirm (the last row) ends the pick (user 2026-11-01). The marker starts on the first pack.

def _keys(monkeypatch, *keys):
    it = iter(keys)

    def read():
        try:
            return next(it)
        except StopIteration:
            pytest.fail("the picker wanted more keys than the test supplied")
    monkeypatch.setattr(inst, "_read_key", read)


def _rows(out: str) -> list:
    return [ln for ln in out.split("\n") if ln.startswith((" > [", "   ["))
            or ln[3:] in (inst.INSTALL_SELECTED, inst.SKIP_MODULES)]


def _pick(catalogue, args, game_dir):
    """(chosen, turned down); the third part (what the player ticked) is tested on its own."""
    return inst.pick_modules(catalogue, args, game_dir)[:2]


def test_only_a_shown_list_reports_what_the_player_ticked(monkeypatch, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "enter", "down", "down", "enter")
    assert inst.pick_modules(CATALOGUE, _args(), tmp_path) == (["portraits-hd"], ["movies-hd"], ["portraits-hd"])
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: None)
    assert inst.pick_modules(CATALOGUE, _args(), tmp_path)[2] == []
    assert inst.pick_modules(CATALOGUE, _args(no_prompt=True), tmp_path)[2] == []


def _console(monkeypatch, *presses):
    """The console's key records as _poll_key hands them out: (virtual-key code, character)."""
    queue = list(presses)
    monkeypatch.setattr(inst, "_poll_key", lambda: queue.pop(0) if queue else None)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    return queue


# The records a plain Command Prompt delivered on 2026-11-03 (keydump): Up vk 0x26 char '\x00',
# Down 0x28 '\x00', Enter 0x0d '\r', a 0x41 'a'. VT input hands an arrow over as ESC [ A, one
# character per record with no key code.
@pytest.mark.parametrize("presses,want", [
    (((0x26, "\x00"),), "up"), (((0x28, "\x00"),), "down"),
    (((0x0D, "\r"),), "enter"), (((0x20, " "),), "space"),
    (((0x25, "\x00"),), ""), (((0x41, "a"),), ""),          # left; a letter
    (((0xC0, "\xe0"),), ""),                                 # a typed a-grave (AZERTY 0): NOT an arrow
    (((0, "\x1b"), (0, "["), (0, "A")), "up"), (((0, "\x1b"), (0, "["), (0, "B")), "down"),
    (((0, "\x1b"), (0, "O"), (0, "A")), "up"), (((0, "\x1b"), (0, "O"), (0, "B")), "down"),
    (((0, "\x1b"), (0, "["), (0, "C")), ""),                 # right
    (((0, "\x1b"), (0, "["), (0, "1"), (0, ";"), (0, "5"), (0, "A")), ""),   # Ctrl+Up
    (((0x1B, "\x1b"),), ""),                                 # the Esc key alone
    (((0, "\r"),), "enter"),                                 # Enter as VT text
])
def test_read_key_maps_the_console_records(monkeypatch, presses, want):
    queue = _console(monkeypatch, *presses)
    assert inst._read_key() == want
    assert queue == []


def test_an_arrow_then_a_typed_a_grave_are_two_keys(monkeypatch):
    """The getwch bug (2026-11-03): an arrow's "\\xe0" prefix and a typed a-grave looked alike."""
    _console(monkeypatch, (0x26, "\x00"), (0xC0, "\xe0"), (0x28, "\x00"))
    assert [inst._read_key() for _ in range(3)] == ["up", "", "down"]


def test_read_key_ctrl_c_cancels(monkeypatch):
    _console(monkeypatch, (0x43, "\x03"))
    with pytest.raises(KeyboardInterrupt):
        inst._read_key()


def test_keys_typed_before_the_list_is_drawn_are_dropped(monkeypatch):
    queue = _console(monkeypatch, (0x0D, "\r"), (0x0D, "\r"))
    inst._drop_typed_ahead()
    assert queue == []


def test_poll_key_reads_this_console_without_waiting():
    """The real console API: nothing waiting (or no console at all) is None at once, never a hang."""
    import time
    t = time.monotonic()
    got = inst._poll_key()
    assert got is None or (isinstance(got, tuple) and len(got) == 2)
    assert time.monotonic() - t < 1


def test_the_list_names_every_module_with_its_size_ticked_on_a_first_run(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "down", "down", "enter")              # first pack -> Confirm
    assert _pick(CATALOGUE, _args(), tmp_path) == (["movies-hd", "portraits-hd"], [])
    out = capsys.readouterr().out
    rows = _rows(out)
    assert rows[0].startswith(" > [X] HD cinematics") and "1.4 GB" in rows[0]
    assert "[X] Turovetsky's HD Portrait Pack" in rows[1] and "671 MB" in rows[1]
    assert "already installed" in rows[1] and "already installed" not in rows[0]
    assert "already on disk" not in "".join(rows)                   # user wording 2026-11-06
    assert rows[2] == "   Install selected modules" and rows[-1] == " > Install selected modules"
    assert "Selected: HD cinematics, Turovetsky's HD Portrait Pack" in out
    assert "Select which optional modules you would like to install. You can download these later from the in-game preferences menu." in out


def test_enter_on_a_pack_ticks_it_and_never_confirms(monkeypatch, tmp_path):
    """A reflex Enter (every earlier prompt trains Enter as "yes") must not commit to gigabytes
    (audit 2026-09-27): the marker starts on a pack, where Enter only flips its box."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "enter", "enter", "enter", "down", "down", "enter")
    assert _pick(CATALOGUE, _args(), tmp_path)[0] == ["portraits-hd"]
    _keys(monkeypatch, "space", "down", "down", "enter")
    chosen, turned_down = _pick(CATALOGUE, _args(), tmp_path)
    assert chosen == ["portraits-hd"] and turned_down == ["movies-hd"]


def test_unticking_a_pack_on_disk_turns_nothing_down(monkeypatch, tmp_path):
    """A pack already in the folder is installed, not offered: unticking it only skips the
    re-copy, and records no "Don't ask me again"."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "enter", "down", "enter", "down", "enter")
    assert _pick(CATALOGUE, _args(), tmp_path) == ([], ["movies-hd"])


def test_the_last_row_says_install_or_skip(monkeypatch):
    """User wording 2026-11-04: "Install selected modules", "Skip optional modules" when nothing
    is ticked; the row follows every tick."""
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    names = ["movies-hd", "portraits-hd"]
    some = inst._picker_rows(names, CATALOGUE, {"movies-hd": True, "portraits-hd": False}, 2)
    none = inst._picker_rows(names, CATALOGUE, {"movies-hd": False, "portraits-hd": False}, 0)
    assert some[2] == " > Install selected modules" and none[2] == "   Skip optional modules"
    assert some[-1] == none[-1] == ix.RULE


def test_the_marker_stops_at_both_ends_and_other_keys_do_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "up", "up", "", "", "down", "down", "down", "down", "enter")
    assert _pick(CATALOGUE, _args(), tmp_path)[0] == ["movies-hd", "portraits-hd"]


def test_ctrl_c_at_the_picker_cancels_the_install(monkeypatch, tmp_path):
    """Ctrl-C is the universal abort, not consent: it must reach run_guarded, which cancels
    with nothing changed. Swallowing it as "none" went on to patch the game (audit)."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)

    def interrupt():
        raise KeyboardInterrupt
    monkeypatch.setattr(inst, "_read_key", interrupt)
    with pytest.raises(KeyboardInterrupt):
        inst.choose_modules(CATALOGUE, _args(), tmp_path)


def test_reading_a_key_without_a_console_raises_instead_of_waiting(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    with pytest.raises(EOFError):
        inst._read_key()


def test_what_starts_ticked_follows_the_players_earlier_no(monkeypatch, tmp_path):
    """Everything on a first run (user 2026-11-01); a pack declined before -- "Don't ask me
    again" in game, or left unticked by an earlier install -- or the HD cinematics switched off
    start unticked. A pack on disk is always ticked."""
    import receipt as rc
    (tmp_path / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    cat = {"movies-hd": dict(CATALOGUE["movies-hd"]),
           "portraits-hd": dict(CATALOGUE["portraits-hd"], on_disk=False)}
    d = rc.declined(tmp_path)
    assert inst._starts_ticked("movies-hd", cat, tmp_path, d)
    assert inst._starts_ticked("portraits-hd", cat, tmp_path, d)
    assert rc.decline(tmp_path, "new:portraits-hd", rc.DECLINE_ANY)
    assert not inst._starts_ticked("portraits-hd", cat, tmp_path, rc.declined(tmp_path))
    assert inst._starts_ticked("portraits-hd", dict(cat, **{"portraits-hd": CATALOGUE["portraits-hd"]}),
                               tmp_path, rc.declined(tmp_path))
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: False)
    assert not inst._starts_ticked("movies-hd", cat, tmp_path, d)


def test_a_redraw_rewrites_the_rows_in_place_or_prints_them_again(monkeypatch, capsys):
    monkeypatch.setattr(ix, "can_redraw", lambda: True)
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback=None: os.terminal_size((10, 24)))
    ix.redraw(["a", "b"], ["c", "d"])
    assert capsys.readouterr().out == "\x1b[2F\x1b[Jc\nd\n"
    # A row longer than the window took two lines (colour codes take none): back over three.
    ix.redraw(["\x1b[32m" + "x" * 15 + "\x1b[0m", "b"], ["c", "d"])
    assert capsys.readouterr().out == "\x1b[3F\x1b[Jc\nd\n"
    monkeypatch.setattr(ix, "can_redraw", lambda: False)
    ix.redraw(["a", "b"], ["c", "d"])
    assert capsys.readouterr().out == "\nc\nd\n"


def test_every_prompt_gets_exactly_one_blank_line_above_it(monkeypatch, capsys):
    """User rule 2026-11-01: one empty line between the installer's output and a question --
    added when the output above did not end in one, never a second."""
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "y")
    ix.say("some output")
    ix.ask("Q1? ")
    ix.ask("Q2? ")                      # straight after an answer: still one blank line
    ix.say("more\n")                    # output ending in an empty line already
    ix.ask("Q3? [Y/n] ", title="Third question")
    r = ix.RULE
    assert capsys.readouterr().out == f"some output\n\n\nmore\n\n{r}\n THIRD QUESTION\n{r}\n{r}\n"
    assert asked == ["Q1? ", "Q2? ", " Q3? [Y/n] "]


def test_control_hints_are_blue_and_plain_without_colour(monkeypatch, capsys):
    """User 2026-11-04: the keys to press in (bright) blue -- the block's key line and a yes/no
    prompt's [Y/n]; plain text on a console without colour."""
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "")
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    ix.question_head("Choose", ["a note"], keys="Up/Down: move")
    ix.ask("Replace it? [Y/n] ", title="Shortcut")
    ix.ask("Sure? [y/N] ", title="Sure")
    out = capsys.readouterr().out
    assert " \x1b[94mUp/Down: move\x1b[0m\n a note\n" in out
    assert asked == [" Replace it? \x1b[94m[Y/n]\x1b[0m ", " Sure? \x1b[94m[y/N]\x1b[0m "]
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    ix.question_head("Choose", keys="Up/Down: move")
    ix.ask("Replace it? [Y/n] ", title="Shortcut")
    assert " Up/Down: move\n" in capsys.readouterr().out and asked[-1] == " Replace it? [Y/n] "


def test_a_question_is_a_ruled_block_set_apart_from_output(monkeypatch, capsys):
    """User 2026-11-03: a rule, the title in capitals, the notes (keys), a rule, then the
    question; a rule under the answer. Plain '-': no colour or codepage needed to see it."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    ix.say("output")
    assert ix.ask("Replace it? [Y/n] ", title="Desktop shortcut") == "n"
    ix.question_head("Choose", ["Up/Down: move"])
    assert set(ix.RULE) == {"-"} and len(ix.RULE) >= 40
    r = ix.RULE
    assert capsys.readouterr().out == (f"output\n\n{r}\n DESKTOP SHORTCUT\n{r}\n{r}\n"
                                       f"\n{r}\n CHOOSE\n Up/Down: move\n{r}\n")


# ---------------------------------------------------------------- the update-check opt-in (user 2026-11-06)

def _first_install(monkeypatch, tmp_path, *answers):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(inst, "_has_install", lambda g: False)
    it = iter(answers)
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or next(it))
    return asked


def _ini(tmp_path) -> str:
    try:
        return (tmp_path / "Alpha Centauri.ini").read_text(encoding="mbcs")
    except FileNotFoundError:
        return ""


def test_a_first_install_asks_about_update_checks_in_the_users_words(monkeypatch, capsys, tmp_path):
    """The website says the player chooses during installation whether the game checks for updates: a
    first install at a console asks, as a ruled block with the user's text; Enter means yes."""
    asked = _first_install(monkeypatch, tmp_path, "")
    ix.say("Selected: none")
    assert inst.ask_update_checks(tmp_path, _args()) is True
    out = capsys.readouterr().out
    r = ix.RULE
    assert out == ("Selected: none\n\n" + f"{r}\n AUTOMATIC UPDATES\n"
                   " When the game starts, it can check our server for a newer version of Longevity Vaccine and its\n"
                   " optional modules, and offer to install them. You can change this any time in Longevity Mod\n"
                   " Preferences (\"Check for Updates at Startup\").\n"
                   f"{r}\n{r}\n  The game will check for updates when it starts.\n")
    assert asked == [" Check for updates when the game starts? [Y/n] "]
    assert _ini(tmp_path) == "", "the answer is written after the patch pass, not at the question"
    inst.write_update_check(tmp_path, True)
    assert "CheckForUpdates=1" in _ini(tmp_path)


@pytest.mark.parametrize("answer,on", [("y", True), ("YES", True), ("n", False), ("no", False), ("maybe", False)])
def test_the_answer_becomes_the_games_setting(monkeypatch, capsys, tmp_path, answer, on):
    _first_install(monkeypatch, tmp_path, answer)
    assert inst.ask_update_checks(tmp_path, _args()) is on
    out = capsys.readouterr().out
    if on:
        assert "The game will check for updates when it starts." in out
    else:
        assert ("The game will not check for updates. Turn it on any time in Longevity Mod Preferences "
                "(\"Check for Updates at Startup\").") in out
    inst.write_update_check(tmp_path, on)
    assert f"CheckForUpdates={1 if on else 0}" in _ini(tmp_path)


def test_a_rerun_keeps_the_players_setting_and_says_so(monkeypatch, capsys, tmp_path):
    """Not asked again: the key the first install wrote (or the game's Preferences) stands; one line."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    monkeypatch.setattr(inst, "_has_install", lambda g: True)
    for value, word in (("1", "checks"), ("0", "does not check")):
        (tmp_path / "Alpha Centauri.ini").write_text(f"[UIMod]\nCheckForUpdates={value}\n", encoding="ascii")
        assert inst.ask_update_checks(tmp_path, _args()) is None
        out = capsys.readouterr().out
        assert out == ("\n--- automatic updates ---\n"
                       f"  The game {word} for updates when it starts (as before); change it in Longevity Mod "
                       "Preferences (\"Check for Updates at Startup\").\n"), out
    # the mod installed by a release that never wrote the key (0.2.x): the default stands, no question
    (tmp_path / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    assert inst.ask_update_checks(tmp_path, _args()) is None
    assert "checks for updates when it starts (the default)" in capsys.readouterr().out
    inst.write_update_check(tmp_path, None)
    assert "CheckForUpdates" not in _ini(tmp_path)


def test_the_key_is_read_as_the_game_reads_it(tmp_path):
    """update.cpp: GetPrivateProfileIntW(default 1): empty -> on, a word -> off, a number's leading
    digits decide. The installer's line must say what the GAME will do (audit 2026-11-06)."""
    ini = tmp_path / "Alpha Centauri.ini"
    assert inst.update_check_state(tmp_path) is None
    for value, want in (("1", True), ("0", False), ("", True), ("yes", False), ("true", False), ("2", True),
                        ("0 ; keep it off", False), ("1 ; on", True), ("-1", True), ("07", True)):
        ini.write_text(f"[UIMod]\nCheckForUpdates={value}\n", encoding="ascii")
        assert inst.update_check_state(tmp_path) is want, value


def test_the_mod_already_here_means_no_question_even_without_the_key(tmp_path, monkeypatch, capsys):
    """_has_install for real: a lone uimod.dll (a part-finished uninstall, or an install that failed after
    the patch) makes a re-run, not a first install."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    (tmp_path / "uimod.dll").write_bytes(b"dll")
    assert inst.ask_update_checks(tmp_path, _args()) is None
    assert "checks for updates when it starts (the default)" in capsys.readouterr().out


def test_the_answer_is_written_the_moment_the_exe_is_patched(tmp_path, bak_path, monkeypatch, capsys):
    """Audit 2026-11-06: written at the end of the install, a "no" was lost to any failure after the patch
    pass (a copy, a download, Ctrl+C), and the re-run -- the folder now installed -- never asked again,
    so the game checked against a stated no. The install here fails right after the patch; the key is
    there, and the re-run keeps it."""
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    monkeypatch.setattr(inst, "module_catalogue", lambda gd, a: ([], None))
    monkeypatch.setattr(inst, "pick_modules", lambda c, a, gd: ([], [], []))
    monkeypatch.setattr(inst, "deploy_runtime", lambda gd, quiet=False: False)
    args = types.SimpleNamespace(no_prompt=False, ai="off", modules=None, force=False, manifest=None,
                                 offline=False, pack=None, portrait_pack=None)
    with pytest.raises(ix.InstallerError) as e:
        inst._install(g, args)
    assert e.value.changed is True and "copying the mod files" in e.value.message
    assert "CheckForUpdates=0" in (g / "Alpha Centauri.ini").read_text(encoding="mbcs")
    assert "The game will not check for updates." in capsys.readouterr().out
    assert inst._has_install(g), "the patched exe beside its backup counts as installed"
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("a re-run must not ask"))
    assert inst.ask_update_checks(g, args) is None
    assert "does not check for updates when it starts (as before)" in capsys.readouterr().out


def test_no_prompt_and_an_unattended_install_keep_the_default_without_asking(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(inst, "_has_install", lambda g: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    assert inst.ask_update_checks(tmp_path, _args(no_prompt=True)) is None
    assert "checks for updates when it starts (the default)" in capsys.readouterr().out
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert inst.ask_update_checks(tmp_path, _args()) is None
    assert "checks for updates when it starts (the default)" in capsys.readouterr().out
    assert _ini(tmp_path) == ""


def test_a_closed_stdin_at_the_question_keeps_the_default(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(inst, "_has_install", lambda g: False)

    def eof(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert inst.ask_update_checks(tmp_path, _args()) is None
    assert "checks for updates when it starts (the default)" in capsys.readouterr().out


def test_ctrl_c_at_the_update_question_cancels_like_the_picker(monkeypatch, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(inst, "_has_install", lambda g: False)

    def interrupt(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", interrupt)
    with pytest.raises(KeyboardInterrupt):
        inst.ask_update_checks(tmp_path, _args())


def test_no_prompt_takes_every_module_without_asking(monkeypatch, capsys, tmp_path):
    """The PLAYER's --no-prompt on a first install (user 2026-11-01): every module on offer,
    nothing asked, nothing turned down. --modules / --ai still win."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("must not ask"))
    assert _pick(CATALOGUE, _args(no_prompt=True), tmp_path) \
        == (["movies-hd", "portraits-hd"], [])
    assert "(--no-prompt)" in capsys.readouterr().out
    assert _pick(CATALOGUE, _args(no_prompt=True, ai="off"), tmp_path)[0] == []
    assert _pick(CATALOGUE, _args(no_prompt=True, modules="movies-hd"), tmp_path) \
        == (["movies-hd"], [])


def test_no_prompt_on_a_rerun_keeps_the_players_earlier_no(monkeypatch, tmp_path):
    """--no-prompt takes the list as it would start: a pack declined before, or the HD
    cinematics switched off, stay out -- a default here once reversed an opt-out (audit
    2026-11-03); a pack on disk is still taken."""
    import receipt as rc
    (tmp_path / "Alpha Centauri.ini").write_text("[UIMod]\nUpscaledVideos=0\n", encoding="ascii")
    cat = {"movies-hd": CATALOGUE["movies-hd"],
           "portraits-hd": dict(CATALOGUE["portraits-hd"], on_disk=False)}
    assert rc.decline(tmp_path, "new:portraits-hd", rc.DECLINE_ANY)
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("must not ask"))
    assert _pick(cat, _args(no_prompt=True), tmp_path) == ([], [])
    assert _pick(CATALOGUE, _args(no_prompt=True), tmp_path) == (["portraits-hd"], [])   # on disk


def test_ai_off_turns_the_cinematics_down_unless_they_are_on_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(inst, "pack_on_disk", lambda g, n: False)
    assert _pick({}, _args(ai="off"), tmp_path) == ([], ["movies-hd"])
    monkeypatch.setattr(inst, "pack_on_disk", lambda g, n: True)
    assert _pick({}, _args(ai="off"), tmp_path) == ([], [])


def test_a_turned_down_pack_is_declined_as_the_game_declines_it(tmp_path):
    """The same `new:<id>:*` the DLL's "Don't ask me again" writes on a NEW pack's offer
    (update.cpp `new:%s`, update_core.h DeclineVersionFor kDeclineAny); choosing it later
    forgets it, and leaves every other decline as it was."""
    import receipt as rc
    (tmp_path / "Alpha Centauri.ini").write_text("[Longevity]\nDeclinedUpdates=base:9.9.9\n",
                                                 encoding="ascii")
    inst.record_module_choice(tmp_path, [], ["movies-hd"])
    assert rc.declined(tmp_path) == {"base": "9.9.9", "new:movies-hd": rc.DECLINE_ANY}
    assert rc.ini_get(tmp_path, rc.KEY_DECLINED) == "base:9.9.9;new:movies-hd:*"
    inst.record_module_choice(tmp_path, ["movies-hd"], [])
    assert rc.declined(tmp_path) == {"base": "9.9.9"}


def test_unattended_and_flag_runs_turn_nothing_down(monkeypatch, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: None)
    assert _pick(CATALOGUE, _args(), tmp_path) == (["movies-hd"], [])
    assert _pick(CATALOGUE, _args(ai="on"), tmp_path) == (["movies-hd"], [])
    assert _pick(CATALOGUE, _args(modules="portraits-hd"), tmp_path) == (["portraits-hd"], [])


def test_flags_decide_without_asking(monkeypatch, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    assert inst.choose_modules(CATALOGUE, _args(ai="off"), tmp_path) == []
    assert inst.choose_modules(CATALOGUE, _args(ai="on"), tmp_path) == ["movies-hd"]
    assert inst.choose_modules(CATALOGUE, _args(modules="portraits-hd,movies-hd"), tmp_path) \
        == ["portraits-hd", "movies-hd"]


def test_a_named_module_that_is_not_on_offer_is_refused_before_anything_happens(tmp_path):
    with pytest.raises(ix.InstallerError) as e:
        inst.choose_modules({"movies-hd": CATALOGUE["movies-hd"]}, _args(modules="portraits-hd"),
                            tmp_path)
    assert e.value.code == ix.EXIT_ABORTED and e.value.changed is False
    assert "Turovetsky's HD Portrait Pack is not available" in e.value.message


def test_unattended_keeps_the_players_earlier_choice(monkeypatch, tmp_path):
    """No keyboard: a first install takes the headline pack; a re-run follows the ini."""
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: None)
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == ["movies-hd"]
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: False)
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == []
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: True)
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == ["movies-hd"]


def test_ai_off_never_touches_the_network(monkeypatch, tmp_path):
    """The e2e suite runs `--ai off` fifty times; a manifest fetch there would hit the CDN."""
    def boom(*a, **k):
        pytest.fail("fetch_manifest must not be called for --ai off")
    monkeypatch.setattr(inst, "fetch_manifest", boom)
    cat, manifest = inst.module_catalogue(tmp_path, _args(ai="off", pack=str(tmp_path / "nope")))
    assert cat == {} and manifest is None
    # ...nor when nobody is at the keyboard and nothing was named
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    cat, manifest = inst.module_catalogue(tmp_path, _args(pack=str(tmp_path / "nope")))
    assert cat == {} and manifest is None


def test_an_unreachable_server_lists_nothing_and_says_so_once(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)

    def offline(*a, **k):
        assert k.get("quick"), "the listing must use the quick single-attempt profile"
        raise ix.InstallerError("Could not reach the update server.", code=ix.EXIT_ABORTED)
    monkeypatch.setattr(inst, "fetch_manifest", offline)
    cat, manifest = inst.module_catalogue(tmp_path, _args(pack=str(tmp_path / "nope")))
    assert cat == {} and manifest is None
    out = capsys.readouterr().out
    assert out.count("Optional modules could not be listed") == 1
    assert "update prompt" in out


def test_a_local_pack_is_listed_with_its_size_on_disk(tmp_path, monkeypatch):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "a.mp4").write_bytes(b"x" * 1000)
    (pack / "b.mp4").write_bytes(b"y" * 500)
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    cat, _ = inst.module_catalogue(tmp_path, _args(ai="on", pack=str(pack)))
    assert cat["movies-hd"]["source"] == "local" and cat["movies-hd"]["size"] == 1500
    assert cat["movies-hd"]["on_disk"] is False


def test_cinematics_flag_rules(monkeypatch, tmp_path):
    monkeypatch.setattr(inst, "pack_on_disk", lambda g, n: False)
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: None)
    flag = inst.cinematics_flag
    assert flag(["movies-hd"], tmp_path, _args(ai="off")) is True
    assert flag([], tmp_path, _args(ai="off")) is False
    assert flag([], tmp_path, _args(ai="on")) is True, "--ai on forces it (run-install.bat header)"
    assert flag([], tmp_path, _args(), offered=["movies-hd"]) is False, "shown the pack, said no"
    assert flag([], tmp_path, _args(), offered=[]) is True, "never listed (offline): first install on"
    assert flag(["portraits-hd"], tmp_path, _args(), offered=["portraits-hd"]) is True, \
        "only the portraits were on offer: nothing was declined"
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: False)
    assert flag([], tmp_path, _args(), offered=[]) is False, "keeps the opt-out"
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: True)
    assert flag([], tmp_path, _args(), offered=[]) is True, "keeps the opt-in"
    monkeypatch.setattr(inst, "pack_on_disk", lambda g, n: True)
    assert flag([], tmp_path, _args(ai="off")) is True, "clips already there"


# ---------------------------------------------------------------- the patcher's summary

def test_the_patcher_reports_one_line_per_phase(tmp_path, bak_path):
    exe = tmp_path / "t.exe"
    shutil.copy2(bak_path, exe)
    lines = []
    rc = ap.apply_patches(exe, Path(ap.DEFAULT_PATCHES), do_apply=True,
                          spec=ap.load_targets(ap.DEFAULT_PATCHES)["pracx"],
                          summary=lambda s, t: lines.append((s, t)))
    assert rc == 0
    text = "\n".join(t for _, t in lines)
    assert len(lines) < 12, text                          # a summary, not a transcript
    assert "Code caves: SUCCESS (2/2 ready)" in text
    assert "Patch sites: SUCCESS (" in text and "Patch groups: SUCCESS (" in text
    assert "Patching: SUCCESS (" in text and "Backup: t.exe.bak" in text
    # skipped sites are NAMED, never with their bytes; the note says skips are expected
    skips = [t for s, t in lines if s == "skip"]
    assert any("uimod_native.stub" in t for t in skips)
    assert not any("expected" in t or "got" in t for t in skips)
    assert any("Skipped sites are expected" in t for s, t in lines if s == "info")
    assert all(s in ("ok", "skip", "info") for s, _ in lines), "no error on a clean base"


def test_a_failing_site_is_reported_with_its_bytes(tmp_path, bak_path):
    """Corrupt one patch site's original bytes: the summary goes red and the bytes are shown."""
    import hashlib
    import pefile
    exe = tmp_path / "t.exe"
    data = bytearray(bak_path.read_bytes())
    sites, _g, _c, _s = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    site = next(s for s in sites if s.get("status") == "confirmed" and not s.get("group")
                and not s.get("skippable"))
    off = ap.VaResolver(pefile.PE(data=bytes(data), fast_load=True)) \
        .to_file_offset(int(site["virtual_addr"]))
    data[off] ^= 0xFF
    exe.write_bytes(bytes(data))
    lines = []
    # The legacy baseline arguments, so the run gets PAST the whole-file hash check and reaches
    # the per-site verification where the corrupted site fails.
    rc = ap.apply_patches(exe, Path(ap.DEFAULT_PATCHES), do_apply=False,
                          expected_md5=hashlib.md5(bytes(data)).hexdigest(),
                          expected_size=len(data),
                          summary=lambda s, t: lines.append((s, t)))
    assert rc == 3
    errors = [t for s, t in lines if s == "error"]
    assert any(t.startswith("Patch sites: ERROR (1/") for t in errors), errors
    detail = next(t for t in errors if site["id"] in t)
    assert "expected" in detail and "got" in detail, detail       # the bytes, for a FAILING site
    assert not any(site["id"] in t for s, t in lines if s == "skip")


def test_the_installer_colours_the_phase_lines(monkeypatch, capsys):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    inst._patch_summary("ok", "Patching: SUCCESS (1/1 sites patched, 0 skipped, 0 code cave(s) written)")
    inst._patch_summary("error", "Patch sites: ERROR (1/2 failed, 0 skipped)")
    inst._patch_summary("skip", "  skipped: a")
    out = capsys.readouterr().out.split("\n")
    assert out[0].startswith("\x1b[32m") and out[1].startswith("\x1b[31m")
    assert "\x1b[" not in out[2]


# ---------------------------------------------------------------- summary rows + closing

def test_summary_rows_are_success_error_or_skipped(monkeypatch, capsys):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    ix.status_line("terranx_PRACX.exe", "ok")
    ix.status_line("prax.dll", "skip")
    ix.status_line("HD cinematics", "error")
    rows = capsys.readouterr().out.rstrip("\n").split("\n")
    assert rows[0] == "  terranx_PRACX.exe              \x1b[32mSuccess\x1b[0m"
    assert rows[1] == "  prax.dll                       Skipped"
    assert rows[2] == "  HD cinematics                  \x1b[31mError\x1b[0m"
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    ix.status_line("x", "ok")
    assert capsys.readouterr().out == "  x                              Success\n"
    # the longest pack name keeps the column (audit 2026-11-06)
    ix.status_line(inst.MODULE_LABELS["portraits-hd"], "ok")
    ix.status_line("prax.dll", "ok")
    a, b = capsys.readouterr().out.rstrip("\n").split("\n")
    assert a.index("Success") == b.index("Success")


def test_the_picker_and_the_download_line_keep_the_whole_pack_name(tmp_path):
    """Audit 2026-11-06: "Turovetsky's HD Portrait Pack" was cut mid-word in the download progress line, and the
    picker's size column must line up under every label."""
    import re
    import fetch
    name = inst.MODULE_LABELS["portraits-hd"]
    assert name == "Turovetsky's HD Portrait Pack"
    lines = []

    class Tty:
        def write(self, s):
            lines.append(s)

        def flush(self):
            pass

        def isatty(self):
            return True
    old = fetch.sys.stdout
    fetch.sys.stdout = Tty()
    try:
        fetch._progress(512 << 20, 1 << 30, fetch.time.monotonic() - 1, name)
        fetch._progress(512 << 20, 0, fetch.time.monotonic() - 1, name)
    finally:
        fetch.sys.stdout = old
    assert len(lines) == 2
    for ln in lines:
        assert f"  {name} " in ln and len(ln.lstrip("\r")) < 80, ln
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    cat = {"movies-hd": {"size": 1 << 30}, "portraits-hd": {"size": 50 << 20, "on_disk": True}}
    rows = [ansi.sub("", r) for r in
            inst._picker_rows(["movies-hd", "portraits-hd"], cat, {"movies-hd": True, "portraits-hd": False}, 0)[:2]]
    ends = [len(r.split("   already")[0].rstrip()) for r in rows]
    assert ends[0] == ends[1], rows                                  # the size column ends at one place
    assert "already installed" in rows[1] and name in rows[1]


def test_a_portrait_folder_without_the_pack_manifest_is_not_the_installed_pack(tmp_path):
    """Audit 2026-11-06: the picker says "already installed"; a stray image or an interrupted copy in
    portraits\\hd is not the pack, and the game does not use it (it requires pack-manifest.json)."""
    hd = tmp_path / "portraits" / "hd"
    hd.mkdir(parents=True)
    (hd / "gaians.png").write_bytes(b"png")
    assert not inst.pack_on_disk(tmp_path, "portraits-hd")
    (hd / "pack-manifest.json").write_text("{}", encoding="utf-8")
    assert inst.pack_on_disk(tmp_path, "portraits-hd")


def test_the_banner_says_what_the_installer_does_and_an_update_skips_it(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["install.py"])
    inst.banner()
    assert ("This installer will patch Alpha Centauri: Alien Crossfire with Longevity Vaccine. Your "
            "original game .exe will be backed up (.bak) and can be restored at any time.\n\n") \
        in capsys.readouterr().out                                   # user 2026-11-04
    monkeypatch.setattr(sys, "argv", ["install.py", "--update"])
    inst.banner()
    assert "This installer will patch" not in capsys.readouterr().out


def test_the_play_note_no_longer_explains_alien_crossfire(monkeypatch, capsys, tmp_path):
    (tmp_path / "terranx_PRACX.exe").write_bytes(b"MZ")
    monkeypatch.setattr(inst, "find_shortcut_to", lambda exe: None)
    inst.print_play_note(tmp_path, "pracx")
    out = capsys.readouterr().out
    assert "Alien Crossfire" not in out
    assert "The GOG Galaxy Play button" in out and inst.ENJOY_LINE in out


def test_the_resolution_refusal_is_a_yellow_stretched_warning(tmp_path, monkeypatch, capsys):
    ini = tmp_path / "Alpha Centauri.ini"
    ini.write_text("[PRACX]\r\nScreenWidth=1920\r\nScreenHeight=1080\r\n", encoding="ascii")
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    inst.check_display_resolution(tmp_path, "pracx")
    out = capsys.readouterr().out
    line = next(l for l in out.split("\n") if "Left your resolution as is" in l)
    assert line.startswith("\x1b[33m") and "stretched until you fix this!" in line


def test_saying_yes_to_starting_the_game_closes_the_window(monkeypatch, capsys):
    monkeypatch.setattr(ix, "offer_relaunch", lambda exe: True)
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: pytest.fail("must not wait"))
    assert ix.run_guarded(lambda: 0, relaunch_exe=Path("x.exe")) == ix.EXIT_OK


def test_declining_the_launch_still_holds_the_window(monkeypatch, capsys):
    monkeypatch.setattr(ix, "offer_relaunch", lambda exe: False)
    waited = []
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: waited.append(1))
    assert ix.run_guarded(lambda: 0, relaunch_exe=Path("x.exe")) == ix.EXIT_OK
    assert waited == [1]


def test_a_failed_copy_is_one_readable_line():
    """shutil.copytree's error carries every failed file; printing it dumped a screenful of
    paths (2026-11-04). The count, the first file and its reason, and a plain word for length."""
    e = shutil.Error([("C:/src/a", "D:/game/LongevityMods/a", "[WinError 3] not found"),
                      ("C:/src/b", "D:/game/LongevityMods/b", "[WinError 206] The filename or extension is too long")])
    text = inst.copy_error_summary(e)
    assert text.startswith("2 files could not be copied, the first D:/game/LongevityMods/a: [WinError 3] not found")
    assert "longer than Windows allows" in text and "C:/src/b" not in text
    assert inst.copy_error_summary(OSError("disk full")) == "disk full"
