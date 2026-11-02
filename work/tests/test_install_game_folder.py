"""The installer finds or asks for the game folder itself -- no command prompt, no --game-dir.

Without --game-dir: the folders it installed into before, the GOG locations and every folder the
GOG registry names are checked; an interactive run lists the good ones and lets the player pick
one, browse for another or paste a path, and asks for the folder when it found none. Every choice
is checked (a supported game build is there) and a bad one is explained and asked again. A
non-interactive run never asks. conftest points LONGEVITY_GAME_CANDIDATES at nothing, so no test
here can see the real game.
"""
from __future__ import annotations

import os
import shutil
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import config                 # noqa: E402
import install as inst        # noqa: E402
import installer_exit as ix   # noqa: E402
import receipt as rc          # noqa: E402

inst._load_modules()

#: Maintainer-machine text that must never reach a player as if it applied to them.
MAINTAINER = ("SmacxUi", "GOG Galaxy", "D:\\")


@pytest.fixture
def games(tmp_path, bak_path, monkeypatch):
    """Throwaway folders: a good one (clean PRACX), a second good one, an empty one, a folder
    whose game sits one level further in, and one with an unsupported terranx.exe."""
    root = tmp_path / "games"
    g = {k: root / k for k in ("good", "second", "empty", "outer", "bad")}
    for d in g.values():
        d.mkdir(parents=True)
    shutil.copy2(bak_path, g["good"] / "terranx_PRACX.exe")
    shutil.copy2(bak_path, g["second"] / "terranx_PRACX.exe")
    (g["outer"] / "Alpha Centauri").mkdir()
    shutil.copy2(bak_path, g["outer"] / "Alpha Centauri" / "terranx_PRACX.exe")
    (g["bad"] / "terranx.exe").write_bytes(b"MZ" + b"\0" * 4096)
    monkeypatch.setenv(config.INSTALLS_ENV, str(tmp_path / "installs.txt"))
    monkeypatch.setenv(config.CANDIDATES_ENV, "")
    return g


def _args(**kw):
    base = dict(game_dir=None, no_prompt=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _answers(monkeypatch, *answers):
    it = iter(answers)
    asked = []

    def ask(prompt=""):
        asked.append(prompt)
        try:
            return next(it)
        except StopIteration:
            pytest.fail(f"asked once too often: {prompt!r}")
    monkeypatch.setattr("builtins.input", ask)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    return asked


def _no_browse(monkeypatch):
    monkeypatch.setattr(inst, "browse_for_folder", lambda title: pytest.fail("must not browse"))


# ---------------------------------------------------------------- checking a folder

def test_a_folder_with_a_supported_build_checks_out(games):
    status, label = inst.check_game_folder(games["good"])
    assert status == inst.FOLDER_OK and "PRACX" in label


@pytest.mark.parametrize("key,status,words", [
    ("empty", "no-game", "terranx.exe"),
    ("outer", "nested", '"Alpha Centauri"'),
    ("bad", "unsupported", "PRACX"),
])
def test_a_wrong_folder_says_what_is_wrong(games, key, status, words):
    got, why = inst.check_game_folder(games[key])
    assert got == status and words in why, why


def test_a_missing_folder_and_an_exe_path_are_explained(games, tmp_path):
    assert inst.check_game_folder(tmp_path / "nowhere")[0] == "missing"
    assert inst.check_game_folder(games["good"] / "terranx_PRACX.exe")[0] == "file"
    (games["good"] / "Alpha Centauri.lnk").write_bytes(b"L")
    status, why = inst.check_game_folder(games["good"] / "Alpha Centauri.lnk")
    assert status == "file" and "shortcut" in why


def test_an_already_patched_exe_checks_out_by_its_backup(games, bak_path):
    g = games["good"]
    shutil.copy2(bak_path, g / "terranx_PRACX.exe.bak")
    (g / "terranx_PRACX.exe").write_bytes(b"MZ ours, patched")
    assert inst.check_game_folder(g)[0] == inst.FOLDER_OK


def test_installed_mode_wants_the_mod_there(games, bak_path):
    g = games["good"]
    assert inst.check_game_folder(g, installed=True)[0] == "not-installed"
    (g / rc.JSON_NAME).write_text('{"target_id": "pracx", "modules": {}}', encoding="utf-8")
    assert inst.check_game_folder(g, installed=True)[0] == inst.FOLDER_OK
    (g / rc.JSON_NAME).unlink()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe.bak")         # a receipt-less install:
    (g / "terranx_PRACX.exe").write_bytes(b"MZ patched")        # our backup, a different exe
    assert inst.check_game_folder(g, installed=True)[0] == inst.FOLDER_OK


def test_installed_mode_ignores_a_left_behind_updater(games):
    g = games["good"]
    (g / "LongevityMods" / "updater").mkdir(parents=True)        # what an uninstall leaves
    assert inst.check_game_folder(g, installed=True)[0] == "not-installed"


# ---------------------------------------------------------------- candidates and memory

def test_the_candidate_override_replaces_every_machine_source(games, monkeypatch, tmp_path):
    monkeypatch.setenv("SMACX_GAME_DIR", str(games["second"]))
    monkeypatch.setenv(config.CANDIDATES_ENV,
                       f'"{games["good"]}"|{tmp_path / "gone"}|{str(games["good"]).upper()}|')
    assert config.candidate_game_dirs() == [games["good"]]
    monkeypatch.setenv(config.CANDIDATES_ENV, "")
    assert config.candidate_game_dirs() == []


def test_the_gog_registry_scan_never_raises():
    assert all(isinstance(p, Path) for p in config._gog_registry_dirs())


def test_remembered_folders_are_newest_first_and_drop_what_is_gone(games):
    assert config.remembered_game_dirs() == []
    config.remember_game_dir(games["good"])
    config.remember_game_dir(games["second"])
    config.remember_game_dir(games["good"])                      # again: moves to the front
    assert config.remembered_game_dirs() == [games["good"], games["second"]]
    shutil.rmtree(games["second"])
    assert config.remembered_game_dirs() == [games["good"]]
    config.forget_game_dir(Path(str(games["good"]).upper()))     # any spelling of it
    assert config.remembered_game_dirs() == []


def test_an_unwritable_memory_is_not_an_error(games, monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv(config.INSTALLS_ENV, str(blocker / "sub" / "installs.txt"))
    assert config.remember_game_dir(games["good"]) is False
    assert config.remembered_game_dirs() == []


# ---------------------------------------------------------------- resolving, non-interactive

def test_game_dir_wins_and_is_taken_as_given(games, monkeypatch, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("must not ask"))
    assert inst.resolve_game_dir(_args(game_dir=str(tmp_path / "x"))) == tmp_path / "x"


def test_unattended_takes_the_first_good_folder(games, monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("must not ask"))
    monkeypatch.setenv(config.CANDIDATES_ENV, f"{games['bad']}|{games['empty']}|{games['second']}")
    assert inst.resolve_game_dir(_args()) == games["second"]
    config.remember_game_dir(games["good"])                      # remembered beats detected
    assert inst.resolve_game_dir(_args()) == games["good"]


def test_no_prompt_never_asks_even_at_a_console(games, monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("must not ask"))
    monkeypatch.setenv(config.CANDIDATES_ENV, str(games["good"]))
    assert inst.resolve_game_dir(_args(no_prompt=True)) == games["good"]


def test_unattended_with_nothing_found_explains_in_player_words(games, monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    with pytest.raises(ix.InstallerError) as e:
        inst.resolve_game_dir(_args())
    err = e.value
    assert err.code == ix.EXIT_NO_GAME and err.changed is False
    assert "INSTALL.bat" in err.remedy and "--game-dir" in err.remedy
    text = " ".join(str(x) for x in (err.message, err.detail, err.remedy))
    assert "SMACX_GAME_DIR" not in text and not any(m in text for m in MAINTAINER), text


def test_a_resident_updater_never_asks(games, monkeypatch):
    monkeypatch.setattr(config, "resident_game_dir", lambda d: games["good"])
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("must not ask"))
    assert inst.resolve_game_dir(_args(), installed=True) == games["good"]


# ---------------------------------------------------------------- resolving, interactive

def test_enter_accepts_the_folder_found(games, monkeypatch, capsys):
    monkeypatch.setenv(config.CANDIDATES_ENV, str(games["good"]))
    _no_browse(monkeypatch)
    _answers(monkeypatch, "")
    assert inst.resolve_game_dir(_args()) == games["good"]
    out = capsys.readouterr().out
    assert "1. " + str(games["good"]) in out and "PRACX" in out


def test_a_number_picks_another_folder_found(games, monkeypatch):
    monkeypatch.setenv(config.CANDIDATES_ENV, f"{games['good']}|{games['bad']}|{games['second']}")
    _no_browse(monkeypatch)
    _answers(monkeypatch, "2")                       # the bad one is not listed: 2 is "second"
    assert inst.resolve_game_dir(_args()) == games["second"]


def test_a_typed_path_is_checked_and_a_bad_one_asked_again(games, monkeypatch, capsys):
    monkeypatch.setenv(config.CANDIDATES_ENV, str(games["good"]))
    _no_browse(monkeypatch)
    asked = _answers(monkeypatch, str(games["empty"]), f'  "{games["outer"]}"  ', str(games["second"]))
    assert inst.resolve_game_dir(_args()) == games["second"]
    out = capsys.readouterr().out
    assert "terranx.exe" in out and '"Alpha Centauri"' in out and len(asked) == 3


def test_browse_opens_the_picker_and_its_choice_is_checked(games, monkeypatch, capsys):
    monkeypatch.setenv(config.CANDIDATES_ENV, str(games["good"]))
    picks = iter([games["bad"], games["second"]])
    monkeypatch.setattr(inst, "browse_for_folder", lambda title: next(picks))
    _answers(monkeypatch, "b", "B")
    assert inst.resolve_game_dir(_args()) == games["second"]
    assert "not a version this mod supports" in capsys.readouterr().out


def test_nothing_found_asks_and_enter_opens_the_picker(games, monkeypatch, capsys):
    picks = iter([None, games["good"]])                          # cancelled once, then chosen
    monkeypatch.setattr(inst, "browse_for_folder", lambda title: next(picks))
    _answers(monkeypatch, "", "")
    assert inst.resolve_game_dir(_args()) == games["good"]
    out = capsys.readouterr().out
    assert "could not find Alpha Centauri" in out and "No folder chosen" in out
    assert not any(m in out for m in ("SmacxUi", "GOG Galaxy")), out


@pytest.mark.parametrize("answer", ["q", "Q", EOFError, KeyboardInterrupt])
def test_quitting_changes_nothing(games, monkeypatch, answer):
    monkeypatch.setattr(ix, "can_ask", lambda: True)

    def ask(prompt=""):
        if isinstance(answer, str):
            return answer
        raise answer
    monkeypatch.setattr("builtins.input", ask)
    with pytest.raises(ix.InstallerError) as e:
        inst.resolve_game_dir(_args())
    assert e.value.code == ix.EXIT_ABORTED and e.value.changed is False


def test_uninstall_lists_only_installed_folders(games, monkeypatch):
    g = games["second"]
    (g / rc.JSON_NAME).write_text('{"target_id": "pracx", "modules": {}}', encoding="utf-8")
    monkeypatch.setenv(config.CANDIDATES_ENV, f"{games['good']}|{g}")
    _no_browse(monkeypatch)
    _answers(monkeypatch, "")
    assert inst.resolve_game_dir(_args(), installed=True) == g


# ---------------------------------------------------------------- the Windows folder picker

def test_the_folder_picker_object_answers_its_option_calls():
    """The IFileOpenDialog vtable slots are right (Get/SetOptions round-trip; SetTitle) -- the
    dialog is created and released without being shown."""
    import ctypes
    from ctypes import wintypes
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    hr = ole32.CoInitializeEx(None, 0x2 | 0x4)
    try:
        dlg = ctypes.c_void_p()
        assert ole32.CoCreateInstance(inst._ptr(inst._guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")), None, 1,
                                      inst._ptr(inst._guid("D57C7288-D4AD-4768-BE02-9D969532D960")),
                                      ctypes.byref(dlg)) == 0
        try:
            want = inst._FOS_PICKFOLDERS | inst._FOS_FORCEFILESYSTEM | inst._FOS_PATHMUSTEXIST
            inst._com_call(dlg, inst._FD_SETOPTIONS, ctypes.HRESULT, wintypes.DWORD(want))
            got = wintypes.DWORD()
            inst._com_call(dlg, inst._FD_GETOPTIONS, ctypes.HRESULT, inst._ptr(got))
            assert got.value & want == want
            inst._com_call(dlg, inst._FD_SETTITLE, ctypes.HRESULT, wintypes.LPCWSTR("t"))
        finally:
            inst._com_call(dlg, inst._RELEASE, ctypes.c_ulong)
    finally:
        if hr in (0, 1):
            ole32.CoUninitialize()


# ---------------------------------------------------------------- audit round 1 (2026-11-01)

def test_no_wait_on_the_command_line_means_no_question(monkeypatch):
    """The bootstrap asks for the folder before anything exports LONGEVITY_NO_WAIT: a scripted
    `--update --no-wait` from a console must still never stop at a prompt."""
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--update"])
    assert ix.can_ask()
    for flag in ("--no-wait", "--no-wait=1"):
        monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--update", flag])
        assert not ix.can_ask()


def test_an_uninstalled_folder_is_not_called_installed(games, bak_path):
    """An uninstall copies each .bak back and keeps it: a .bak equal to its exe is no install."""
    g = games["good"]
    shutil.copy2(bak_path, g / "terranx_PRACX.exe.bak")
    assert inst.check_game_folder(g, installed=True)[0] == "not-installed"
    assert "installed here" not in inst.check_game_folder(g)[1]
    (g / "uimod.dll").write_bytes(b"left by an incomplete uninstall")
    assert inst.check_game_folder(g, installed=True)[0] == inst.FOLDER_OK


@pytest.mark.parametrize("left", ["longevity_sm.pcx", "uimod.dll"])
def test_any_file_an_uninstall_could_not_remove_keeps_the_folder_installed(games, left):
    """The retry an UNINSTALL INCOMPLETE asks for must find the folder whichever file was in use."""
    g = games["good"]
    assert left in inst._uninstall_files()
    (g / left).write_bytes(b"left behind")
    assert inst.check_game_folder(g, installed=True)[0] == inst.FOLDER_OK


def test_an_access_denied_folder_is_a_reason_not_a_crash(games, monkeypatch):
    real = Path.is_file

    def is_file(self):
        if self.parent.name == "good":
            raise PermissionError(5, "Access is denied")
        return real(self)
    monkeypatch.setattr(Path, "is_file", is_file)
    for installed in (False, True):
        status, why = inst.check_game_folder(games["good"], installed=installed)
        assert status == "missing" and "cannot be read" in why


def test_one_folder_through_a_junction_is_one_folder(games, monkeypatch):
    import _winapi
    link = games["good"].parent / "good-link"
    _winapi.CreateJunction(str(games["good"]), str(link))
    try:
        monkeypatch.setenv(config.CANDIDATES_ENV, f"{games['good']}|{link}")
        assert config.candidate_game_dirs() == [games["good"]]
    finally:
        os.rmdir(link)                    # the junction only


def test_game_dir_given_the_exe_means_its_folder(games):
    got = inst.resolve_game_dir(_args(game_dir=str(games["good"] / "terranx_PRACX.exe")))
    assert got == games["good"]


def test_a_foreign_backup_is_no_install(games):
    g = games["good"]
    (g / "terranx_PRACX.exe.bak").write_bytes(b"another tool's backup")
    assert inst.check_game_folder(g, installed=True)[0] == "not-installed"


def test_the_folder_is_always_absolute(games, monkeypatch):
    monkeypatch.chdir(games["good"].parent)
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    got = inst.resolve_game_dir(_args(game_dir="good"))
    assert got.is_absolute() and got == games["good"]
    _no_browse(monkeypatch)
    _answers(monkeypatch, "second")
    got = inst.resolve_game_dir(_args())
    assert got.is_absolute() and got == games["second"]


def test_a_dragged_in_exe_means_its_folder(games, monkeypatch):
    _no_browse(monkeypatch)
    _answers(monkeypatch, f'"{games["second"] / "terranx_PRACX.exe"}"')
    assert inst.resolve_game_dir(_args()) == games["second"]


def test_a_number_like_answer_is_a_path_not_a_crash(games, monkeypatch, capsys):
    _no_browse(monkeypatch)
    monkeypatch.setenv(config.CANDIDATES_ENV, str(games["good"]))
    _answers(monkeypatch, "²", "7", "1")
    assert inst.resolve_game_dir(_args()) == games["good"]
    assert capsys.readouterr().out.count("Not that folder") == 2


def test_unattended_says_which_folder_was_found_and_why_it_cannot_be_used(games, monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setenv(config.CANDIDATES_ENV, str(games["bad"]))
    with pytest.raises(ix.InstallerError) as e:
        inst.resolve_game_dir(_args())
    assert str(games["bad"]) in e.value.detail and "not a version this mod supports" in e.value.detail
    assert "could not be found" not in e.value.message


def test_unattended_never_guesses_between_two_installs(games, monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    for k in ("good", "second"):
        (games[k] / rc.JSON_NAME).write_text('{"target_id": "pracx", "modules": {}}', encoding="utf-8")
    monkeypatch.setenv(config.CANDIDATES_ENV, f"{games['good']}|{games['second']}")
    with pytest.raises(ix.InstallerError) as e:
        inst.resolve_game_dir(_args(), installed=True)
    assert e.value.code == ix.EXIT_ABORTED and e.value.changed is False
    assert str(games["good"]) in e.value.detail and str(games["second"]) in e.value.detail
    assert inst.resolve_game_dir(_args()) == games["good"]          # an install may take the first


def test_an_unreadable_remembered_folder_is_skipped_not_a_crash(games, monkeypatch, tmp_path):
    locked = tmp_path / "locked"
    config.remember_game_dir(locked)
    config.remember_game_dir(games["good"])
    real = Path.is_dir

    def is_dir(self):
        if self.name == "locked":
            raise PermissionError(5, "Access is denied")
        return real(self)
    monkeypatch.setattr(Path, "is_dir", is_dir)
    assert config.remembered_game_dirs() == [games["good"]]


def test_the_registry_folders_count_only_with_the_game_in_them(games, monkeypatch):
    monkeypatch.delenv(config.CANDIDATES_ENV)
    monkeypatch.setattr(config, "_from_env_dir", lambda: None)
    monkeypatch.setattr(config, "_from_file_dir", lambda: None)
    monkeypatch.setattr(config, "_CANDIDATES", [])
    (games["second"] / "terranx.exe").write_bytes(b"MZ")
    monkeypatch.setattr(config, "_gog_registry_dirs", lambda: [games["good"], games["second"], games["empty"]])
    assert config.candidate_game_dirs() == [games["second"]]       # the marker is terranx.exe
