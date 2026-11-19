"""Audit-s (2026-11-17): the parent's replacement model for pending state. Each test written to fail first.

1. Pending state (the marker or a .partial) is honoured on a first install too: a first install killed while placing
   a pack (the receipt is written only at the end, so the re-run is a first install again) is completed by the next
   run, unattended included. Pending state outlives a run only through an interrupted install; uninstall clears it.
2. An explicit "no" to a half-placed pack -- an untick in the list, --ai off for the Cinematics, or a decline the game
   recorded, found at the start of a run -- ENDS its pending state: the files the .partial proves ours (size+sha256)
   and our .tmp-<pid> leftovers go, then the .partial, then the marker entry, then the folder when empty; the decline
   is recorded. Unproven files stay. A later "Reset Skipped Updates" then finds nothing pending: nothing installs
   itself and UpscaledVideos stays off. A complete pack is never deleted by this."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import receipt as rc                # noqa: E402
from test_audit_n import PROV, _game, _setup_rest  # noqa: E402
from test_audit_p import PARTIAL, _manifest_bytes  # noqa: E402
from test_audit_q import _remote_cat  # noqa: E402
from test_audit_r import _declined, _pick  # noqa: E402
from test_setup_pack_rerun import CLIPS, PORTRAITS, _pack  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

SECOND = {"portraits-hd": "usurper.png", "movies-hd": "intro.mp4"}       # a listed name not yet placed


def _killed_first_install(game: Path, name: str = "portraits-hd", *, unproven: bool = False) -> Path:
    """A first install stopped while placing `name`: one file placed (proven), the .partial, the marker -- and no
    receipt. With `unproven`, a second listed name holds something else (the player's, or torn)."""
    files = PORTRAITS if name == "portraits-hd" else CLIPS
    root = game / inst.MODULE_ROOTS[name][0]
    root.mkdir(parents=True, exist_ok=True)
    first, second = list(files)[0], SECOND[name]
    listed = {**files, second: files.get(second, b"u" * 20)}
    (root / first).write_bytes(listed[first])
    if unproven:
        (root / second).write_bytes(b"not what we placed")
    (root / "PROVENANCE.txt").write_bytes(PROV)
    (root / f"{first}.tmp-4321").write_bytes(b"half")
    (root / PARTIAL).write_bytes(_manifest_bytes(name, listed))
    inst._mark_pending(game, [name], True)
    return root


# ---------------------------------------------------------------- 1. a killed first install is completed

@pytest.mark.parametrize("how", ["unattended", "no-prompt"])
def test_a_first_install_killed_while_placing_a_pack_is_completed(tmp_path, monkeypatch, how):
    """K0/PO0: the re-run is a first install again (no receipt yet), unattended or --no-prompt."""
    game = _game(tmp_path)
    _killed_first_install(game)
    chosen, _down, _t = _pick(game, monkeypatch, tmp_path, how)
    assert "portraits-hd" in chosen                       # (a first install takes the Cinematics as always, too)
    downloads = _setup_rest(game, monkeypatch, _remote_cat(game), chosen, [])
    assert len(downloads) == 1 and "portraits-hd" in downloads[0]


def test_an_interactive_first_install_starts_it_ticked(tmp_path, monkeypatch):
    game = _game(tmp_path)
    _killed_first_install(game)
    assert "portraits-hd" in _pick(game, monkeypatch, tmp_path, "interactive", "down", "down", "enter")[0]


# ---------------------------------------------------------------- 2. an explicit no ends it cleanly

def _untick(game, monkeypatch, tmp_path):
    """P2: the list, the half-placed portrait pack unticked, Continue; then the bookkeeping as _install_rest does."""
    chosen, down, ticked = _pick(game, monkeypatch, tmp_path, "interactive", "down", "enter", "down", "enter")
    assert "portraits-hd" not in chosen and "portraits-hd" in down
    inst.record_module_choice(game, ticked, down)


def test_unticking_a_half_placed_pack_removes_what_we_placed(tmp_path, monkeypatch):
    game = _game(tmp_path)
    root = _killed_first_install(game)
    _untick(game, monkeypatch, tmp_path)
    assert not root.exists()                                              # proven file, leftover, lists: all ours
    assert "portraits-hd" not in inst.pending_packs(game) and _declined(game, "portraits-hd")


def test_unproven_files_stay_and_nothing_stays_pending(tmp_path, monkeypatch):
    game = _game(tmp_path)
    root = _killed_first_install(game, unproven=True)
    _untick(game, monkeypatch, tmp_path)
    second = SECOND["portraits-hd"]
    assert (root / second).read_bytes() == b"not what we placed"
    assert not (root / list(PORTRAITS)[0]).exists() and not (root / PARTIAL).exists()
    assert inst.pack_pending(game, "portraits-hd") is False


def test_a_decline_the_game_recorded_ends_it_at_the_start_of_a_run(tmp_path, monkeypatch):
    game = _game(tmp_path)
    root = _killed_first_install(game)
    rc.decline(game, inst.NEW_PACK_PREFIX + "portraits-hd", rc.DECLINE_ANY)          # "Don't ask me again" in game
    _pick(game, monkeypatch, tmp_path, "unattended")
    assert not root.exists() and inst.pack_pending(game, "portraits-hd") is False


def test_ai_off_ends_a_half_placed_cinematics_pack(tmp_path, monkeypatch):
    game = _game(tmp_path)
    root = _killed_first_install(game, "movies-hd")
    chosen, down, ticked = inst.pick_modules({}, types.SimpleNamespace(modules=None, ai="off", no_prompt=False), game)
    inst.record_module_choice(game, ticked, down)
    assert down == ["movies-hd"] and not root.exists() and inst.pack_pending(game, "movies-hd") is False


@pytest.mark.parametrize("how", ["unattended", "no-prompt"])
def test_reset_skipped_updates_then_installs_nothing(tmp_path, monkeypatch, how):
    """D6/H5: the Cinematics half-placed, the player says no (UpscaledVideos off), then resets skipped updates in the
    game's Preferences: nothing pending is left, so nothing installs itself and the flag stays off."""
    game = _game(tmp_path)
    rc.write(game, target_id="pracx", modules={"base": {"version": "1.0.0"}})
    _killed_first_install(game, "movies-hd")
    chosen, down, ticked = inst.pick_modules({}, types.SimpleNamespace(modules=None, ai="off", no_prompt=False), game)
    inst.record_module_choice(game, ticked, down)
    inst.set_ini_flag(game, False)
    rc.clear_declines(game)                                               # Preferences: Reset Skipped Updates
    chosen, down, ticked = _pick(game, monkeypatch, tmp_path, how)
    cat = {"movies-hd": {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": False, "locked": False,
                         "release_manifest": None, "release_provenance": None}}
    assert chosen == [] and _setup_rest(game, monkeypatch, cat, chosen, ticked) == []
    assert inst.ini_flag_state(game, "UpscaledVideos") is False


def test_a_complete_pack_is_never_deleted_by_a_no(tmp_path, monkeypatch):
    game = _game(tmp_path)
    root = _pack(game, "portraits-hd", PORTRAITS)
    inst._mark_pending(game, ["portraits-hd"], True)
    rc.decline(game, inst.NEW_PACK_PREFIX + "portraits-hd", rc.DECLINE_ANY)
    _pick(game, monkeypatch, tmp_path, "unattended")
    inst.record_module_choice(game, [], ["portraits-hd"])
    assert sorted(p.name for p in root.iterdir()) == sorted([*PORTRAITS, "pack-manifest.json"])


def test_a_killed_update_keeps_the_older_pack_on_a_no(tmp_path, monkeypatch):
    """An update stopped part-way: the older pack's own manifest is still there beside the new .partial. A "no" ends
    the pending state but deletes nothing: those files are an installed pack, not a half-placed one."""
    game = _game(tmp_path)
    root = _pack(game, "portraits-hd", PORTRAITS)
    (root / PARTIAL).write_bytes(_manifest_bytes("portraits-hd", PORTRAITS))
    inst.record_module_choice(game, [], ["portraits-hd"])
    assert (root / "caretake.png").is_file() and (root / "pack-manifest.json").is_file()
    assert not (root / PARTIAL).exists()
