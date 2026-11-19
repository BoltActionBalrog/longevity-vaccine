"""Audit-r (2026-11-17, an antagonistic audit of 48eaece): the player's latest explicit "no" ALWAYS beats pending
state (the pending marker or a .partial); pending state completes a pack only when nothing says no, and never on a
first install. Each test written to fail first; real-flow tests where possible.

HIGH-1: a recorded decline (new:<pack>, any version) starts the pack unticked, is never overridden by pending state in
        any mode, and drops it from the marker; UpscaledVideos is never flipped by pending state.
MEDIUM-1: an explicit untick (or --ai off) of a half-placed pack records the decline and ends its pending state.
MEDIUM-2: an uninstall always drops the .partial and the marker entry; a first install ignores pending state.
L-a: a read-only marker is cleared like our other files, and a KEEP wins over a stale marker.
L-c: a marker naming a pack the verified manifest no longer offers is dropped.
R10: a same-size player file is not "ours" (the sha256 half of the proof)."""
from __future__ import annotations

import os
import stat
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
from test_audit_n import _game, _setup_rest  # noqa: E402
from test_audit_p import PARTIAL, _failed_portraits, _manifest_bytes, _rerun_game  # noqa: E402
from test_audit_q import _args, _remote_cat, _signed, _unattended  # noqa: E402
from test_setup_pack_rerun import CLIPS, PORTRAITS, _keys, _pack  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

BOTH = {"movies-hd": "1.0.0", "portraits-hd": "1.0.0"}


def _decline(game, name):
    rc.decline(game, inst.NEW_PACK_PREFIX + name, rc.DECLINE_ANY)


def _declined(game, name) -> bool:
    return inst.NEW_PACK_PREFIX + name in rc.declined(game)


def _pick(game, monkeypatch, tmp_path, how: str, *keys) -> list:
    """The real flow: module_catalogue (a signed manifest, the network stubbed) then pick_modules, in `how` mode."""
    _unattended(monkeypatch)
    _signed(tmp_path, monkeypatch, BOTH)
    if how == "interactive":
        monkeypatch.setattr(ix, "has_console", lambda: True)
        monkeypatch.setattr(ix, "can_ask", lambda: True)
        _keys(monkeypatch, *keys)
    elif how == "no-prompt":
        monkeypatch.setattr(ix, "has_console", lambda: True)
        monkeypatch.setattr(ix, "can_ask", lambda: True)
    args = _args(no_prompt=how == "no-prompt")
    cat, _m = inst.module_catalogue(game, args)
    return inst.pick_modules(cat, args, game)


# ---------------------------------------------------------------- HIGH-1: a decline beats the marker

@pytest.mark.parametrize("how", ["no-prompt", "unattended", "interactive"])
def test_a_decline_made_in_the_game_beats_the_pending_marker(tmp_path, monkeypatch, how):
    """A9/A9b/A9c: a failed first-install download left both packs pending; the player then chose "Don't ask me
    again" for the Cinematics in the game."""
    game = _rerun_game(tmp_path)
    inst._mark_pending(game, ["movies-hd", "portraits-hd"], True)
    _decline(game, "movies-hd")
    chosen, _down, _t = _pick(game, monkeypatch, tmp_path, how, "down", "down", "enter")
    assert "movies-hd" not in chosen and "portraits-hd" in chosen
    assert "movies-hd" not in inst.pending_packs(game)                   # dropped from the marker when seen
    assert _declined(game, "movies-hd")


def test_a_decline_beats_a_partial_too(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_portraits(game)
    _decline(game, "portraits-hd")
    for how in ("no-prompt", "unattended"):
        assert "portraits-hd" not in _pick(game, monkeypatch, tmp_path, how)[0]


def test_pending_state_never_switches_the_cinematics_back_on(tmp_path, monkeypatch):
    """C4: the Cinematics declined at first install (UpscaledVideos=0), a marker planted for it."""
    game = _rerun_game(tmp_path)
    inst.set_ini_flag(game, False)
    _decline(game, "movies-hd")
    inst._mark_pending(game, ["movies-hd"], True)
    chosen, down, ticked = _pick(game, monkeypatch, tmp_path, "unattended")
    cat = {"movies-hd": {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": False, "locked": False,
                         "release_manifest": None, "release_provenance": None}}
    downloads = _setup_rest(game, monkeypatch, cat, chosen, ticked)
    assert downloads == [] and inst.ini_flag_state(game, "UpscaledVideos") is False and _declined(game, "movies-hd")


# ---------------------------------------------------------------- MEDIUM-1: an explicit untick of a half-placed pack

def test_unticking_a_half_placed_pack_records_the_decline_and_ends_it(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_portraits(game)
    inst._mark_pending(game, ["portraits-hd"], True)
    chosen, down, ticked = _pick(game, monkeypatch, tmp_path, "interactive", "down", "enter", "down", "enter")
    assert chosen == [] and down == ["portraits-hd"]
    inst.record_module_choice(game, ticked, down)
    assert _declined(game, "portraits-hd") and "portraits-hd" not in inst.pending_packs(game)
    for how in ("no-prompt", "unattended"):                              # D6 / X4: no later run completes it
        assert "portraits-hd" not in _pick(game, monkeypatch, tmp_path, how)[0]


def test_ai_off_turns_down_a_half_placed_cinematics_pack(tmp_path, monkeypatch):
    """X1: --ai off is an explicit no."""
    game = _rerun_game(tmp_path)
    root = game / "movies" / "hd"
    root.mkdir(parents=True)
    (root / "angels.mp4").write_bytes(CLIPS["angels.mp4"])
    (root / PARTIAL).write_bytes(_manifest_bytes("movies-hd", CLIPS))
    chosen, down, _t = inst.pick_modules({}, types.SimpleNamespace(modules=None, ai="off", no_prompt=False), game)
    assert chosen == [] and down == ["movies-hd"]
    assert inst.cinematics_flag([], game, types.SimpleNamespace(ai="off"), offered=down) is False


# ---------------------------------------------------------------- MEDIUM-2: uninstall and first install

def _kept_file_uninstall(game) -> Path:
    root = game / "movies" / "hd"
    root.mkdir(parents=True)
    (root / "angels.mp4").write_bytes(CLIPS["angels.mp4"])
    (root / "intro.mp4").write_bytes(b"the player's own intro, under a game movie name")
    (root / PARTIAL).write_bytes(_manifest_bytes("movies-hd", CLIPS))
    return root


def test_an_uninstall_always_drops_the_partial(tmp_path, capsys):
    game = _game(tmp_path)
    root = _kept_file_uninstall(game)
    inst.remove_pack(game, "movies-hd")
    assert (root / "intro.mp4").is_file() and not (root / "angels.mp4").exists() and not (root / PARTIAL).exists()
    assert "removed Z2k Retro's HD Cinematics" not in capsys.readouterr().out


# The audit-r rule (b) -- a first install ignores and drops pending state -- was replaced by the parent's model
# (audit-s): an interrupted first install IS the common source of pending state and must be completed; an explicit no
# ends it instead. Its two tests (test_a_first_install_ignores_pending_state and
# test_a_first_install_clears_pending_state_it_did_not_choose) asserted the defect; see test_audit_s.


def test_uninstall_clears_the_pending_mark(installed_with_thinker, monkeypatch):
    """Behaviour, not the source text: a real uninstall leaves no pending marker."""
    g = installed_with_thinker
    inst._mark_pending(g, ["portraits-hd"], True)
    assert inst.pending_packs(g) == {"portraits-hd"}
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    assert inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False)) == ix.EXIT_OK
    assert inst.pending_packs(g) == set() and not (g / "LongevityMods" / inst.PENDING_PACKS).exists()


from test_uninstall_thinker_packs import installed_with_thinker  # noqa: E402,F401  (a fixture)


# ---------------------------------------------------------------- L-a and L-c

def test_a_read_only_marker_is_still_cleared(tmp_path):
    game = _rerun_game(tmp_path)
    inst._mark_pending(game, ["movies-hd", "portraits-hd"], True)
    p = game / "LongevityMods" / inst.PENDING_PACKS
    os.chmod(p, stat.S_IREAD)
    try:
        inst._mark_pending(game, ["movies-hd"], False)
        assert inst.pending_packs(game) == {"portraits-hd"}
        os.chmod(p, stat.S_IREAD)
        inst._mark_pending(game, ["portraits-hd"], False)
        assert not p.exists()
    finally:
        if p.exists():
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)


def test_a_keep_wins_over_a_stale_marker(tmp_path, monkeypatch):
    """A complete, current pack is never fetched again because a marker could not be cleared."""
    game = _rerun_game(tmp_path)
    _pack(game, "portraits-hd", PORTRAITS)
    inst._mark_pending(game, ["portraits-hd"], True)
    assert inst.pack_action(game, "portraits-hd", "1.0.0", "1.0.0") == "keep"
    monkeypatch.setattr(inst, "install_packs_from_manifest", lambda *a: pytest.fail("downloaded a complete pack"))
    _got, status, how = inst.place_packs(game, _args(), ["portraits-hd"], _remote_cat(game), ("r", "s", {}), None,
                                         game / "terranx.exe", {"portraits-hd": "1.0.0"})
    assert how["portraits-hd"] == "keep" and inst.pending_packs(game) == set()


def test_a_marker_for_a_pack_no_longer_offered_is_dropped(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    inst._mark_pending(game, ["movies-hd", "portraits-hd"], True)
    _unattended(monkeypatch)
    _signed(tmp_path, monkeypatch, {"portraits-hd": "1.0.0"})            # the Cinematics are not on offer
    inst.module_catalogue(game, _args())
    assert inst.pending_packs(game) == {"portraits-hd"}


# ---------------------------------------------------------------- R10: the sha256 half of the proof

def test_a_same_size_player_file_is_not_ours(tmp_path):
    game = _game(tmp_path)
    root = game / "movies" / "hd"
    root.mkdir(parents=True)
    (root / "angels.mp4").write_bytes(b"x" * len(CLIPS["angels.mp4"]))   # same size, other content
    (root / PARTIAL).write_bytes(_manifest_bytes("movies-hd", CLIPS))
    inst.remove_pack(game, "movies-hd")
    assert (root / "angels.mp4").read_bytes() == b"x" * len(CLIPS["angels.mp4"])
