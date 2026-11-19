"""A setup re-run over an existing install never defaults to a pack the player does not have (user rule 2026-11-17:
"if a user is updating their installation instead of doing a fresh one ... default to not checking a pack they have
not already installed. We should not be installing a new pack for a user that already has longevity but refused the
pack as the default action."). With a receipt in the folder, every pack not installed starts unticked, whatever the
declines say; an installed one keeps its rules; a first install is unchanged; --no-prompt and an unattended run take
the list as it starts; --modules and --ai on still install what they name. Each test written to fail first."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import receipt as rc                # noqa: E402
from test_setup_pack_rerun import CLIPS, _keys, _pack  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")


def _game(tmp_path, *, installed: bool, movies_on_disk: bool = False) -> Path:
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    if installed:
        mods = {"base": {"version": "1.0.0"}}
        if movies_on_disk:
            mods["movies-hd"] = {"version": "1.0.0"}
        rc.write(g, target_id="pracx", modules=mods)
    if movies_on_disk:
        _pack(g, "movies-hd", CLIPS)
    return g


def _cat(g: Path) -> dict:
    return {n: {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": inst.pack_on_disk(g, n),
                "locked": False} for n in ("movies-hd", "portraits-hd")}


def _args(**kw):
    return types.SimpleNamespace(**{"modules": None, "ai": "ask", "no_prompt": False, **kw})


def _console(monkeypatch, on: bool):
    monkeypatch.setattr(ix, "can_ask", lambda: on)


# ---------------------------------------------------------------- the list as it starts

def test_a_rerun_starts_every_pack_it_does_not_have_unticked(tmp_path, monkeypatch):
    g = _game(tmp_path, installed=True)
    _console(monkeypatch, True)
    _keys(monkeypatch, "down", "down", "enter")                        # straight to Continue
    chosen, _down, _ticked = inst.pick_modules(_cat(g), _args(), g)
    assert chosen == []


def test_a_rerun_keeps_an_installed_pack_ticked(tmp_path, monkeypatch):
    g = _game(tmp_path, installed=True, movies_on_disk=True)
    _console(monkeypatch, True)
    _keys(monkeypatch, "down", "down", "enter")
    assert inst.pick_modules(_cat(g), _args(), g)[0] == ["movies-hd"]


def test_the_player_can_still_tick_one_on_a_rerun(tmp_path, monkeypatch):
    g = _game(tmp_path, installed=True)
    _console(monkeypatch, True)
    _keys(monkeypatch, "down", "enter", "down", "enter")                # tick the portrait pack, then Continue
    assert inst.pick_modules(_cat(g), _args(), g)[0] == ["portraits-hd"]


def test_a_first_install_still_starts_everything_ticked(tmp_path, monkeypatch):
    g = _game(tmp_path, installed=False)
    _console(monkeypatch, True)
    _keys(monkeypatch, "down", "down", "enter")
    assert inst.pick_modules(_cat(g), _args(), g)[0] == ["movies-hd", "portraits-hd"]


# ---------------------------------------------------------------- no list: --no-prompt and an unattended run

@pytest.mark.parametrize("movies_on_disk,expect", [(False, []), (True, ["movies-hd"])], ids=["none", "installed"])
def test_no_prompt_on_a_rerun_installs_no_pack_the_player_does_not_have(tmp_path, monkeypatch, movies_on_disk,
                                                                        expect):
    g = _game(tmp_path, installed=True, movies_on_disk=movies_on_disk)
    _console(monkeypatch, True)
    assert inst.pick_modules(_cat(g), _args(no_prompt=True), g)[0] == expect


def test_no_prompt_on_a_first_install_still_takes_every_pack(tmp_path, monkeypatch):
    g = _game(tmp_path, installed=False)
    _console(monkeypatch, True)
    assert inst.pick_modules(_cat(g), _args(no_prompt=True), g)[0] == ["movies-hd", "portraits-hd"]


@pytest.mark.parametrize("movies_on_disk,expect", [(False, []), (True, ["movies-hd"])], ids=["none", "installed"])
def test_an_unattended_rerun_installs_no_pack_the_player_does_not_have(tmp_path, monkeypatch, movies_on_disk, expect):
    g = _game(tmp_path, installed=True, movies_on_disk=movies_on_disk)
    _console(monkeypatch, False)
    assert inst.pick_modules(_cat(g), _args(), g)[0] == expect


def test_an_unattended_first_install_still_takes_the_cinematics(tmp_path, monkeypatch):
    g = _game(tmp_path, installed=False)
    _console(monkeypatch, False)
    assert inst.pick_modules(_cat(g), _args(), g)[0] == ["movies-hd"]


# ---------------------------------------------------------------- explicit flags

def test_modules_and_ai_on_still_install_what_they_name_on_a_rerun(tmp_path, monkeypatch):
    g = _game(tmp_path, installed=True)
    _console(monkeypatch, True)
    assert inst.pick_modules(_cat(g), _args(modules="portraits-hd"), g)[0] == ["portraits-hd"]
    assert inst.pick_modules(_cat(g), _args(ai="on"), g)[0] == ["movies-hd"]


# ---------------------------------------------------------------- what leaving one unticked records (unchanged)

def test_a_pack_left_unticked_by_default_on_a_rerun_is_not_turned_down(tmp_path, monkeypatch):
    """Decision for the user (2026-11-17, after this commit): on a re-run only a pack the player explicitly unticked
    is turned down; one that merely started unticked here records nothing (test_rerun_declines). A pack on disk never
    is."""
    g = _game(tmp_path, installed=True, movies_on_disk=True)
    _console(monkeypatch, True)
    _keys(monkeypatch, "down", "down", "enter")
    chosen, turned_down, _t = inst.pick_modules(_cat(g), _args(), g)
    assert chosen == ["movies-hd"] and turned_down == []
