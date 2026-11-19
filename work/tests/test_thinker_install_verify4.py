"""The fourth verification (of f076f34, 2026-11-15): one regression per item, each written to fail first. MEDIUM-2's
--update run is a real __main__ run (test_install_e2e); the rest are in-process, with real junctions."""
from __future__ import annotations

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
import thinker_update as tu         # noqa: E402
from test_thinker_flow import World  # noqa: E402
from test_thinker_install_review import _first_install_plan  # noqa: E402

pytestmark = [pytest.mark.usefixtures("install_globals"),
              pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")]


def _junction(link: Path, target: Path) -> None:
    import _winapi
    link.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))


def _players_folder(tmp_path) -> Path:
    """A folder of the player's OUTSIDE the game folder, shaped like what the installer would remove."""
    d = tmp_path / "players"
    (d / "thinker").mkdir(parents=True)
    (d / "thinker" / "player.txt").write_text("mine", encoding="ascii")
    (d / "backups" / "set").mkdir(parents=True)
    (d / "backups" / "set" / "player.txt").write_text("mine", encoding="ascii")
    return d


# ---------------------------------------------------------------- MEDIUM-3 / LOW-3: never delete through a link

def test_a_junctioned_staging_is_never_emptied(tmp_path):
    outside = _players_folder(tmp_path)
    g = tmp_path / "game"
    _junction(g / "LongevityMods" / "staging", outside)
    tf._clear_staging(g)
    assert (outside / "thinker" / "player.txt").is_file()
    assert os.path.lexists(g / "LongevityMods" / "staging")            # the link itself is not removed


def test_a_junctioned_longevitymods_is_never_emptied(tmp_path):
    outside = _players_folder(tmp_path)
    g = tmp_path / "game"
    g.mkdir()
    (outside / "staging").mkdir()
    _junction(g / "LongevityMods", outside)
    tf._clear_staging(g)
    inst._forget_staging(g)
    tf._drop_set(g / "LongevityMods" / "backups" / "set")
    assert (outside / "thinker" / "player.txt").is_file() and (outside / "backups" / "set" / "player.txt").is_file()
    assert os.path.lexists(g / "LongevityMods")


def test_a_junctioned_backups_folder_is_never_emptied_or_unlinked(tmp_path):
    outside = _players_folder(tmp_path)
    g = tmp_path / "game"
    _junction(g / "LongevityMods" / "backups", outside / "backups")
    tf._drop_set(g / "LongevityMods" / "backups" / "set")
    tu._remove_own_set(g / "LongevityMods" / "backups" / "set")
    assert (outside / "backups" / "set" / "player.txt").is_file() and os.path.lexists(g / "LongevityMods" / "backups")


def test_fetchs_staging_clear_never_follows_a_link(tmp_path):
    import fetch
    outside = _players_folder(tmp_path)
    g = tmp_path / "game"
    _junction(g / "LongevityMods" / "staging", outside)
    fetch.clear_staging(g)
    assert (outside / "thinker" / "player.txt").is_file()


def test_the_bootstraps_updater_cleanup_never_follows_a_link(tmp_path):
    import bootstrap as bs
    outside = tmp_path / "players"
    (outside / "updater.old").mkdir(parents=True)
    (outside / "updater.old" / "player.txt").write_text("mine", encoding="ascii")
    g = tmp_path / "game"
    g.mkdir()
    _junction(g / "LongevityMods", outside)
    bs._rm_tree(g, g / "LongevityMods" / "updater.old")
    assert (outside / "updater.old" / "player.txt").is_file()


def test_safe_fs_never_rmdirs_a_link(tmp_path):
    import safe_fs
    target = tmp_path / "empty-target"
    target.mkdir()
    g = tmp_path / "game"
    _junction(g / "LongevityMods", target)
    assert safe_fs.rmdir(g, g / "LongevityMods") is False and os.path.lexists(g / "LongevityMods")


# ---------------------------------------------------------------- MEDIUM-4: recovery never deletes what it did not add

def test_a_backward_roll_leaves_a_file_the_player_put_back_by_hand(tmp_path):
    g = tmp_path / "g"
    g.mkdir()
    (g / "thinker.dll").write_bytes(b"Thinker 5.4, extracted by hand after the crash")
    acts = [{"rel": "thinker.dll", "kind": "add", "old": "", "new": "0" * 64}]       # the change added 5.5
    assert tu._roll(g, acts, g / "no-set", False) == tu.LOST
    assert (g / "thinker.dll").read_bytes().startswith(b"Thinker 5.4")


def test_a_backward_roll_still_removes_the_file_it_added(tmp_path):
    g = tmp_path / "g"
    g.mkdir()
    (g / "thinker.dll").write_bytes(b"new")
    acts = [{"rel": "thinker.dll", "kind": "add", "old": "", "new": tu.sha256(g / "thinker.dll")}]
    assert tu._roll(g, acts, g / "no-set", False) == tu.UNDONE and not (g / "thinker.dll").exists()


# ---------------------------------------------------------------- MEDIUM-1: --fix-thinker with no console

def test_fix_thinker_without_a_console_refuses_instead_of_drawing_the_menu(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, answers=[""])
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert w.asked == [] and w.committed == []
    assert "this run cannot ask questions, so nothing was updated" in e.value.message


def test_fix_thinker_with_thinker_unattended_offers_no_longevity_update(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, latest="9.9.9", answers=[])
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    w.args.with_thinker = True
    try:
        w.run()
    except ix.InstallerError:
        pass
    assert w.asked == []


# ---------------------------------------------------------------- LOW-1: a bad-signature manifest is discarded

def test_a_manifest_that_does_not_verify_is_discarded_from_staging(tmp_path, monkeypatch):
    import manifest as mf
    stg = tmp_path / "LongevityMods" / "staging"
    stg.mkdir(parents=True)

    def fetched(game_dir, *a, **k):
        (stg / "manifest.json").write_text("{}", encoding="ascii")
        (stg / "manifest.json.sig").write_text("bad", encoding="ascii")
        return b"{}", "bad"
    monkeypatch.setattr(inst, "fetch_manifest", fetched)
    monkeypatch.setattr(mf, "load_verified", lambda *a, **k: (_ for _ in ()).throw(mf.ManifestError("bad sig")))
    monkeypatch.setattr(ix, "stdin_is_console", lambda: True)
    inst.module_catalogue(tmp_path, types.SimpleNamespace(ai="ask", modules=None, pack=None, portrait_pack=None,
                                                          manifest=None, offline=False, no_prompt=False))
    assert not (stg / "manifest.json").exists() and not (stg / "manifest.json.sig").exists()


# ---------------------------------------------------------------- LOW-2: a Ctrl-C past the pass says what stays

def test_a_ctrl_c_with_a_committed_thinker_change_says_it_stays(tmp_path, capsys):
    prep = types.SimpleNamespace(committed=True, ts="5.5")

    def run(g, a):
        tf.LAST_COMMITTED = prep
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        inst._saying_thinker_state(run, tmp_path, None)
    assert ("  Thinker Mod 5.5 was installed and stays in the game folder. Run the installer again to finish "
            "installing Longevity Vaccine.") in capsys.readouterr().out


@pytest.mark.parametrize("prep", [types.SimpleNamespace(committed=False, ts="5.5"),
                                  types.SimpleNamespace(committed=True, ts="5.5", state_said=True), None],
                         ids=["put-back", "already-said", "no-change"])
def test_a_ctrl_c_says_nothing_of_thinker_when_nothing_of_it_stays(tmp_path, capsys, prep):
    def run(g, a):
        tf.LAST_COMMITTED = prep
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        inst._saying_thinker_state(run, tmp_path, None)
    assert "stays in the game folder" not in capsys.readouterr().out


# ---------------------------------------------------------------- LOW-4: --fix-thinker's Ctrl-C leaves no download

def test_a_fix_thinker_ctrl_c_leaves_no_download(tmp_path, monkeypatch):
    stg = tmp_path / "game" / "LongevityMods" / "staging" / "thinker"

    def stopped(game_dir, args):
        stg.mkdir(parents=True)
        (stg / "thinker-5.5.0.zip").write_bytes(b"zip")
        raise KeyboardInterrupt
    monkeypatch.setattr(tf, "_fix_thinker", stopped)
    with pytest.raises(KeyboardInterrupt):
        tf.fix_thinker(tmp_path / "game", types.SimpleNamespace())
    assert not stg.exists()


def test_a_fix_thinker_ctrl_c_after_its_commit_says_thinker_is_in_place(tmp_path, monkeypatch, capsys):
    """User-approved 2026-11-15 (X_cj, a Ctrl-C in finish): "  Thinker Mod 5.5 is in place. Run the installer again to
    finish the change." -- the version is the pinned build's label."""
    prep = types.SimpleNamespace(committed=True, ts="5.5")

    def stopped(game_dir, args):
        tf.LAST_COMMITTED = prep
        raise KeyboardInterrupt
    monkeypatch.setattr(tf, "_fix_thinker", stopped)
    with pytest.raises(KeyboardInterrupt):
        tf.fix_thinker(tmp_path / "game", types.SimpleNamespace())
    assert "  Thinker Mod 5.5 is in place. Run the installer again to finish the change.\n" in capsys.readouterr().out


@pytest.mark.parametrize("prep", [None, types.SimpleNamespace(committed=False, ts="5.5")], ids=["none", "put-back"])
def test_a_fix_thinker_ctrl_c_with_nothing_committed_says_nothing_of_it(tmp_path, monkeypatch, capsys, prep):
    tf.LAST_COMMITTED = types.SimpleNamespace(committed=True, ts="9.9")      # a stale one from an earlier call

    def stopped(game_dir, args):
        if prep is not None:
            tf.LAST_COMMITTED = prep
        raise KeyboardInterrupt
    monkeypatch.setattr(tf, "_fix_thinker", stopped)
    with pytest.raises(KeyboardInterrupt):
        tf.fix_thinker(tmp_path / "game", types.SimpleNamespace())
    assert "is in place" not in capsys.readouterr().out
