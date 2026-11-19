"""The uninstall design (user-approved 2026-11-15): the record of the Thinker Mod this installer put in place, the
question at --uninstall, removing Thinker Mod when chosen, the optional packs always, and our desktop shortcut.
Each written to fail first; the audit cases (a locked pack file, an edited thinker.ini, a planted junction, a record
pointing outside the folder) included."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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
import thinker_flow as tf           # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
from test_thinker_install_review import _first_install_plan  # noqa: E402
from test_thinker_update import KNOWN, NEW, _folder  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")

REAL_MENU = inst._arrow_menu


def _installed_thinker(tmp_path, game_files=None):
    """A folder where this installer installed Thinker Mod 5.5 (a real plan, commit and finish)."""
    game, prep = _first_install_plan(tmp_path, game_files or {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")
    tf.finish(prep)
    return game, prep


# ---------------------------------------------------------------- 1: the record

def test_finishing_a_change_records_what_it_put_in_place(tmp_path):
    game, prep = _installed_thinker(tmp_path, {"terranx.exe": b"MZ", "alphax.txt": b"the game's rules",
                                               "thinker_user.ini": b"[thinker]\r\nmine=1\r\n"})
    rec = tf.read_install_record(game)
    assert rec["pin"] == "5.5.0"
    assert rec["files"]["thinker.dll"] == tu.sha256(game / "thinker.dll")
    assert {"thinker.exe", "thinker.ini", "basenames/hive.txt"} <= set(rec["files"])
    assert "alphax.txt" not in rec["files"] and "thinker_user.ini" not in rec["files"]


def test_the_record_survives_a_normal_update_of_the_receipt(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    before = (game / tf.INSTALL_RECORD).read_bytes()
    rc.write(game, target_id="pracx_thinker", modules={"base": {"version": "9.9.9"}}, say=lambda *a: None)
    assert (game / tf.INSTALL_RECORD).read_bytes() == before


def test_a_finished_recovery_records_the_change_too(tmp_path):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")                       # interrupted before finish: the journal stays
    assert tf.recover_at_entry(game) == tu.FINISHED
    assert tf.read_install_record(game)["files"]["thinker.dll"] == tu.sha256(game / "thinker.dll")


# ---------------------------------------------------------------- 2: the question

def _console(monkeypatch, keys):
    monkeypatch.setattr(ix, "stdin_is_console", lambda: True)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    it = iter(keys)
    monkeypatch.setattr(inst, "_read_key", lambda: next(it))
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)


def test_the_question_reads_as_approved_and_defaults_to_keeping_thinker(tmp_path, monkeypatch, capsys):
    game, _ = _installed_thinker(tmp_path)
    _console(monkeypatch, ["enter"])
    assert tf.ask_uninstall_thinker(game) is False
    out = capsys.readouterr().out
    assert " THINKER MOD\n Longevity Vaccine installed Thinker Mod 5.5 in this folder.\n" \
           " Thinker Mod works without Longevity Vaccine.\n" in out
    assert " -> Only uninstall Longevity Vaccine\n    Also uninstall Thinker Mod 5.5\n" in out


def test_down_enter_chooses_to_uninstall_thinker(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    _console(monkeypatch, ["down", "enter"])
    assert tf.ask_uninstall_thinker(game) is True


@pytest.mark.parametrize("why", ["swapped-dll", "no-prompt", "no-console", "no-record"])
def test_no_question_and_thinker_stays(tmp_path, monkeypatch, why):
    game, _ = _installed_thinker(tmp_path)
    _console(monkeypatch, [])                            # any key read would fail the test (StopIteration)
    if why == "swapped-dll":
        (game / "thinker.dll").write_bytes(b"the player's own build")
    elif why == "no-prompt":
        ix.set_player_no_prompt(True)
    elif why == "no-console":
        monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    else:
        (game / tf.INSTALL_RECORD).unlink()
    assert tf.ask_uninstall_thinker(game) is False


def test_ctrl_c_at_the_question_changes_nothing(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    monkeypatch.setattr(ix, "stdin_is_console", lambda: True)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    monkeypatch.setattr(inst, "_read_key", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(ix.InstallerError) as e:
        tf.ask_uninstall_thinker(game)
    assert e.value.title == "NOTHING WAS CHANGED" and (game / "thinker.dll").is_file()


# ---------------------------------------------------------------- 3: removing Thinker Mod

def test_removing_thinker_removes_its_files_an_edited_ini_too_and_empty_folders(tmp_path, capsys):
    game, _ = _installed_thinker(tmp_path, {"terranx.exe": b"MZ", "smac_mod/mine.txt": b"the player's"})
    (game / "thinker.ini").write_text("[thinker]\nedited=1\n", encoding="ascii")      # edited: still Thinker's
    removed, failed = tf.remove_thinker(game)
    assert failed == 0 and removed >= 5
    for rel in ("thinker.dll", "thinker.exe", "thinker.ini", "basenames/hive.txt", "smac_mod/helpx.txt"):
        assert not game.joinpath(*rel.split("/")).exists(), rel
    assert not (game / "basenames").exists()                 # emptied: removed
    assert (game / "smac_mod" / "mine.txt").is_file()        # not ours: stays, and so does its folder
    assert (game / "terranx.exe").is_file()
    assert not (game / tf.INSTALL_RECORD).exists()
    assert "  removed Thinker Mod 5.5" in capsys.readouterr().out


def test_removing_an_updated_thinker_never_puts_the_older_one_back(tmp_path):
    game = _folder(tmp_path / "game", {"thinker.dll": b"old dll", "thinker.exe": b"old exe"})
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=st.parse_label("Thinker Mod v5.4"))
    prep = tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), types.SimpleNamespace(label=st.parse_label("Thinker Mod v5.4")),
                       p, "5.5", st.UP)
    tf.commit(prep, route="fresh")
    tf.finish(prep)
    tf.remove_thinker(game)
    assert not (game / "thinker.dll").exists() and not (game / "thinker.exe").exists()
    assert len(tu.older_backups(game)) == 1                    # the 5.4 copies stay in LongevityMods\backups


def test_a_locked_thinker_file_is_finished_by_the_rerun_without_asking(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    with open(game / "thinker.exe", "rb"):                   # held open: Windows refuses the delete
        removed, failed = tf.remove_thinker(game)
    assert failed == 1 and (game / "thinker.exe").is_file()
    rec = tf.read_install_record(game)
    assert rec and rec.get("remove")                          # decided: the re-run does not ask again
    monkeypatch.setattr(ix, "can_ask", lambda: pytest.fail("must not ask again"))
    assert tf.ask_uninstall_thinker(game) is True
    assert tf.remove_thinker(game)[1] == 0 and not (game / "thinker.exe").exists()


@pytest.mark.parametrize("rel", ["../outside.txt", "C:/Windows/win.ini", "alphax.txt", "LongevityMods/x.txt"])
def test_a_record_naming_a_file_it_could_not_have_written_is_refused(tmp_path, monkeypatch, rel):
    game, _ = _installed_thinker(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me", encoding="ascii")
    (game / "alphax.txt").write_text("the game's rules", encoding="ascii")
    rec = json.loads((game / tf.INSTALL_RECORD).read_text(encoding="utf-8"))
    rec["files"][rel] = "0" * 64
    (game / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    assert tf.read_install_record(game) is None and tf.ask_uninstall_thinker(game) is False
    assert tf.remove_thinker(game) == (0, 0)
    assert outside.read_text() == "keep me" and (game / "alphax.txt").is_file() and (game / "thinker.dll").is_file()


# ---------------------------------------------------------------- 4: the optional packs are always removed

def _pack(game: Path, rel: str, kind: str, names: list):
    d = game.joinpath(*rel.split("/"))
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_bytes(b"x" * 10)
    (d / "PROVENANCE.txt").write_text("credit", encoding="ascii")
    key = "clips" if kind == "movies-hd" else "files"
    (d / "pack-manifest.json").write_text(json.dumps({"schema": 1, "pack": kind, key: [{"name": n} for n in names]}),
                                          encoding="utf-8")
    return d


def test_both_packs_are_removed_by_their_manifests_and_the_players_portraits_stay(tmp_path, capsys):
    game = tmp_path / "game"
    mv = _pack(game, "movies/hd", "movies-hd", ["angels.mp4", "believe.mp4"])
    pt = _pack(game, "portraits/hd", "portraits-hd", ["caretake.png"])
    (game / "portraits" / "mine.png").write_bytes(b"the player's")
    (game / "movies" / "opening.wve").write_bytes(b"the game's")
    assert inst.remove_pack(game, "movies-hd") == (4, 0)
    assert inst.remove_pack(game, "portraits-hd") == (3, 0)
    assert not mv.exists() and not pt.exists()
    assert (game / "portraits" / "mine.png").is_file() and (game / "movies" / "opening.wve").is_file()
    out = capsys.readouterr().out
    assert "  removed Z2k Retro's HD Cinematics" in out and "  removed Turovetsky's HD Portrait Pack" in out


def test_a_file_the_manifest_does_not_list_stays_with_its_folder(tmp_path):
    game = tmp_path / "game"
    pt = _pack(game, "portraits/hd", "portraits-hd", ["caretake.png"])
    (pt / "my_extra.png").write_bytes(b"the player's")
    inst.remove_pack(game, "portraits-hd")
    assert (pt / "my_extra.png").is_file() and not (pt / "caretake.png").exists()


def test_a_locked_pack_file_keeps_the_manifest_and_the_rerun_finishes(tmp_path):
    game = tmp_path / "game"
    mv = _pack(game, "movies/hd", "movies-hd", ["angels.mp4", "believe.mp4"])
    with open(mv / "believe.mp4", "rb"):
        removed, failed = inst.remove_pack(game, "movies-hd")
    assert failed == 1 and (mv / "pack-manifest.json").is_file() and (mv / "believe.mp4").is_file()
    assert inst.remove_pack(game, "movies-hd")[1] == 0 and not mv.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows junction")
def test_a_junction_planted_in_movies_hd_is_never_followed(tmp_path):
    import _winapi
    game = tmp_path / "game"
    elsewhere = _pack(tmp_path / "elsewhere", "stuff", "movies-hd", ["angels.mp4"])
    (game / "movies").mkdir(parents=True)
    _winapi.CreateJunction(str(elsewhere), str(game / "movies" / "hd"))
    assert inst.remove_pack(game, "movies-hd") == (0, 0)
    assert (elsewhere / "angels.mp4").is_file() and (elsewhere / "pack-manifest.json").is_file()


def test_a_manifest_naming_a_path_outside_the_pack_is_not_ours(tmp_path):
    game = tmp_path / "game"
    d = _pack(game, "portraits/hd", "portraits-hd", ["caretake.png"])
    (game / "portraits" / "mine.png").write_bytes(b"the player's")
    (d / "pack-manifest.json").write_text(json.dumps({"files": [{"name": "../mine.png"}]}), encoding="utf-8")
    assert inst.remove_pack(game, "portraits-hd") == (0, 0)
    assert (game / "portraits" / "mine.png").is_file()


# ---------------------------------------------------------------- 6: the desktop shortcut

def test_only_our_shortcut_to_this_folder_is_removed(tmp_path, monkeypatch, capsys):
    game = tmp_path / "game"
    game.mkdir()
    desk = tmp_path / "desk"
    other = tmp_path / "other-desk"
    for d in (desk, other):
        d.mkdir()
    (desk / (inst.MOD_SHORTCUT_NAME + ".lnk")).write_bytes(b"lnk")
    (other / (inst.MOD_SHORTCUT_NAME + ".lnk")).write_bytes(b"lnk")
    (desk / "My Thinker.lnk").write_bytes(b"lnk")
    targets = {str(desk / (inst.MOD_SHORTCUT_NAME + ".lnk")): str(game / "thinker.exe"),
               str(other / (inst.MOD_SHORTCUT_NAME + ".lnk")): str(tmp_path / "another-install" / "terranx.exe")}
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [desk, other])
    monkeypatch.setattr(inst, "_shortcut_target", lambda lnk: targets.get(str(lnk), ""))
    assert inst.remove_our_shortcut(game) == 1
    assert not (desk / (inst.MOD_SHORTCUT_NAME + ".lnk")).exists()
    assert (other / (inst.MOD_SHORTCUT_NAME + ".lnk")).is_file() and (desk / "My Thinker.lnk").is_file()
    assert '  removed the desktop shortcut "SMACX Longevity"' in capsys.readouterr().out


# ---------------------------------------------------------------- the whole uninstall, on a real install

@pytest.fixture
def installed_with_thinker(tmp_path, bak_path, monkeypatch):
    """A real setup run that also installed Thinker Mod (B), its download faked as the review tests do, then an HD
    Cinematics pack and our shortcut beside it."""
    from test_thinker_install_review import _args, _fake_thinker_step
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    _game, prep = _first_install_plan(tmp_path / "plan", {"terranx.exe": b"MZ"})
    real_commit, real_finish = tf.commit, tf.finish
    prep.game_dir = g
    prep.plan.game_dir = g
    # Its own patches only, undone here: the test's own (install_globals, synthetic_pin) stay in force.
    with pytest.MonkeyPatch.context() as mp:
        _fake_thinker_step(mp, g)
        mp.setattr(tf, "prepare", lambda *a, **k: prep)
        mp.setattr(tf, "commit", lambda p, route, exe=None: real_commit(p, route=route, exe=exe))
        mp.setattr(tf, "finish", real_finish)
        assert inst._install(g, _args()) == 0
    _pack(g, "movies/hd", "movies-hd", ["angels.mp4"])
    return g


def test_uninstall_without_a_console_keeps_thinker_and_removes_the_packs(installed_with_thinker, monkeypatch, capsys):
    g = installed_with_thinker
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    assert inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False)) == ix.EXIT_OK
    out = capsys.readouterr().out
    assert (g / "thinker.dll").is_file() and not (g / "movies" / "hd").exists()
    assert "stays installed and works without Longevity Vaccine" in out
    assert "movies\\hd            -" not in out and "portraits\\           -" not in out
    assert not (g / tf.INSTALL_RECORD).exists() and not (g / rc.JSON_NAME).exists()


def test_uninstall_also_removing_thinker(installed_with_thinker, monkeypatch, capsys):
    g = installed_with_thinker
    _console(monkeypatch, ["down", "enter"])
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    assert inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False)) == ix.EXIT_OK
    out = capsys.readouterr().out
    assert not (g / "thinker.dll").exists() and not (g / "thinker.exe").exists()
    assert "stays installed" not in out and "  removed Thinker Mod 5.5" in out
    assert not (g / tf.INSTALL_RECORD).exists()
    assert inst.check_game_folder(g)[0] == inst.FOLDER_OK                 # a plain PRACX folder again
