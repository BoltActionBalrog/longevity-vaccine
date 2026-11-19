"""What leaving a pack unticked records, and what the game's update prompt (--check) then offers (the parent's
decision for the user, 2026-11-17): on a re-run, Continue records a decline ONLY for a pack the player explicitly
unticked -- one that started ticked and was toggled off. A pack that merely started unticked under the re-run default
(6d19e84) and was left so records nothing new, so the game still offers it. Existing declines are kept. A first
install is unchanged. Written to fail first."""
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
from test_check import _doc         # noqa: E402
from test_rerun_pack_defaults import _cat, _game  # noqa: E402
from test_setup_pack_rerun import _keys  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

NEW_PORTRAITS = f"new=portraits-hd|Turovetsky's HD Portrait Pack|1.0.0|{1300 << 20}"
DOC = _doc(base="1.0.0", **{"portraits-hd": "1.0.0"})


def _setup_list(game: Path, monkeypatch, *keys) -> tuple:
    """The setup list answered with `keys`, then the decline bookkeeping as _install_rest does it (nothing placed),
    then what --check tells the game."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, *keys)
    cat = {"portraits-hd": _cat(game)["portraits-hd"]}
    chosen, turned_down, ticked_now = inst.pick_modules(cat, types.SimpleNamespace(modules=None, ai="ask",
                                                                                    no_prompt=False), game)
    inst.record_module_choice(game, sorted(set(ticked_now)), turned_down)
    state = rc.read(game)
    if not state.get("modules"):              # a first install: the receipt the install then writes
        state = {"modules": {"base": {"version": "1.0.0"}}, "target_id": "pracx"}
    return chosen, turned_down, inst.check_report(DOC, state, rc.declined(game))[1]


def test_a_rerun_that_leaves_a_pack_unticked_by_default_records_nothing(tmp_path, monkeypatch):
    game = _game(tmp_path, installed=True)
    chosen, turned_down, offered = _setup_list(game, monkeypatch, "down", "enter")          # straight to Continue
    assert chosen == [] and turned_down == []
    assert inst.NEW_PACK_PREFIX + "portraits-hd" not in rc.declined(game)
    assert offered == ["latest=1.0.0", NEW_PORTRAITS]                   # the game still offers it


def test_a_rerun_that_ticks_then_unticks_a_pack_records_nothing(tmp_path, monkeypatch):
    """It started unticked: toggling it on and off again is not "explicitly unticked" (it never started ticked)."""
    game = _game(tmp_path, installed=True)
    chosen, turned_down, offered = _setup_list(game, monkeypatch, "enter", "enter", "down", "enter")
    assert chosen == [] and turned_down == [] and offered == ["latest=1.0.0", NEW_PORTRAITS]


def test_a_rerun_keeps_an_existing_decline(tmp_path, monkeypatch):
    game = _game(tmp_path, installed=True)
    rc.decline(game, inst.NEW_PACK_PREFIX + "portraits-hd", rc.DECLINE_ANY)
    _chosen, _down, offered = _setup_list(game, monkeypatch, "down", "enter")
    assert inst.NEW_PACK_PREFIX + "portraits-hd" in rc.declined(game)
    assert offered == ["latest=1.0.0"]                                  # hidden, as before


def test_a_first_install_still_records_an_explicitly_unticked_pack(tmp_path, monkeypatch):
    """Unchanged: on a first install the pack starts ticked; unticking it is the player's "no", and the game does not
    offer it until "Reset Skipped Updates"."""
    game = _game(tmp_path, installed=False)
    chosen, turned_down, offered = _setup_list(game, monkeypatch, "enter", "down", "enter")
    assert chosen == [] and turned_down == ["portraits-hd"]
    assert offered == ["latest=1.0.0"]
