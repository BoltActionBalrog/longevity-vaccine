"""The whole-branch verification (audit-j, of 65243cb, 2026-11-16): one regression per finding, each written to fail
first. MEDIUM-2 (a partial "Also uninstall" cut the record down, and nothing repaired the half-removed Thinker),
MEDIUM-3 (a read-only file made every uninstall loop), L2 (leftovers: Thinker's own alphax.txt copies, our portraits
readme, an empty [Longevity]), L3 (the updater deployed through a junction), L4 (e2e tests that skipped silently under
LONGEVITY_REQUIRE_E2E). Synthetic Thinker files stand in for the pinned release (conftest's synthetic_pin)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_TESTS))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import safe_fs                      # noqa: E402
import thinker_flow as tf           # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
from test_thinker_update import KNOWN, NEW, _folder  # noqa: E402
from test_uninstall_thinker_packs import _installed_thinker  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows locks, attributes and junctions")
REMOVED_LINE = "removed Thinker Mod 5.5"


def _record(game: Path) -> dict:
    return json.loads((game / tf.INSTALL_RECORD).read_text(encoding="utf-8"))


def _read_only(p: Path) -> None:
    os.chmod(p, stat.S_IREAD)


def _is_read_only(p: Path) -> bool:
    return not os.stat(p).st_mode & stat.S_IWRITE


# ---------------------------------------------------------------- MEDIUM-2: the full record stays, marked

@windows
def test_j01_a_locked_thinker_exe_keeps_the_full_marked_record(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    full = _record(game)["files"]
    with open(game / "thinker.exe", "rb"):
        removed, failed = tf.remove_thinker(game)
    assert failed == 1 and removed >= 1
    rec = _record(game)
    assert rec["files"] == full and rec["remove"] is True               # exactly what a Ctrl-C leaves


@windows
def test_j01_the_next_setup_offers_the_repair_and_clears_the_mark(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    with open(game / "thinker.exe", "rb"):
        tf.remove_thinker(game)
    gone = sorted(r for r in _record(game)["files"] if not game.joinpath(*r.split("/")).is_file())
    assert gone and tf.missing_release_files(game) == gone            # the approved repair is offered
    tf.settle_install_record(game)                                     # the setup / update run succeeded
    rec = _record(game)
    assert not rec.get("remove")
    assert tf.missing_release_files(game) == gone                      # still offered until put back or declined


@windows
def test_j01_the_later_also_finishes_everything(tmp_path, monkeypatch, capsys):
    game, _ = _installed_thinker(tmp_path)
    with open(game / "thinker.exe", "rb"):
        tf.remove_thinker(game)
    capsys.readouterr()
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert tf.ask_uninstall_thinker(game) is True                     # marked: finished without asking
    assert tf.remove_thinker(game)[1] == 0
    assert not any((game / n).exists() for n in ("thinker.exe", "thinker.dll", "thinker.ini"))
    assert not (game / tf.INSTALL_RECORD).exists() and REMOVED_LINE in capsys.readouterr().out


@windows
def test_k04_a_locked_thinker_dll_then_the_later_also_leaves_no_thinker_ini(tmp_path, monkeypatch, capsys):
    game, _ = _installed_thinker(tmp_path)
    full = _record(game)["files"]
    with open(game / "thinker.dll", "rb"):
        assert tf.remove_thinker(game)[1] == 1
    assert not (game / "thinker.exe").exists() and (game / "thinker.ini").is_file()
    assert _record(game)["files"] == full and _record(game)["remove"] is True
    assert "thinker.exe" in tf.missing_release_files(game)             # a setup run offers to put it back
    capsys.readouterr()
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert tf.ask_uninstall_thinker(game) is True
    assert tf.remove_thinker(game)[1] == 0
    assert not (game / "thinker.ini").exists() and not (game / "thinker.dll").exists()
    assert REMOVED_LINE in capsys.readouterr().out


@windows
def test_a_link_only_failure_keeps_the_full_marked_record_too(tmp_path):
    import _winapi
    game, _ = _installed_thinker(tmp_path)
    full = _record(game)["files"]
    inside = game / "elsewhere-inside"
    (game / "smac_mod").rename(inside)
    _winapi.CreateJunction(str(inside), str(game / "smac_mod"))
    assert tf.remove_thinker(game)[1] >= 1
    assert _record(game)["files"] == full and _record(game)["remove"] is True


def test_no_removed_line_while_a_recorded_file_is_still_in_place(tmp_path, monkeypatch, capsys):
    """thinker.exe gone (not by us): thinker.ini stays by the L5 rule -- never "removed Thinker Mod" beside it."""
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.exe").unlink()
    capsys.readouterr()
    removed, failed = tf.remove_thinker(game)
    assert failed == 0 and removed >= 1 and (game / "thinker.ini").is_file()
    assert REMOVED_LINE not in capsys.readouterr().out


# ---------------------------------------------------------------- MEDIUM-3: read-only files we may delete

@windows
@pytest.mark.parametrize("rel", ["thinker.ini", "basenames/hive.txt"], ids=["thinker.ini", "release-file"])
def test_a_read_only_thinker_file_is_removed(tmp_path, rel):
    game, _ = _installed_thinker(tmp_path)
    _read_only(game.joinpath(*rel.split("/")))
    removed, failed = tf.remove_thinker(game)
    assert failed == 0 and not game.joinpath(*rel.split("/")).exists()
    assert not (game / tf.INSTALL_RECORD).exists()


@windows
def test_a_read_only_file_the_player_changed_keeps_its_attribute(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    p = game / "modmenu.txt"
    p.write_bytes(b"my menu")
    _read_only(p)
    tf.remove_thinker(game)
    assert p.read_bytes() == b"my menu" and _is_read_only(p)


@windows
def test_a_read_only_file_that_still_cannot_go_keeps_its_attribute(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"x")
    _read_only(p)
    with open(p, "rb"):
        with pytest.raises(OSError):
            safe_fs.unlink_entitled(p)
    assert p.is_file() and _is_read_only(p)


@windows
def test_a_read_only_pack_file_is_removed(tmp_path):
    game = tmp_path / "game"
    d = game / "portraits" / "hd"
    d.mkdir(parents=True)
    (d / "a.png").write_bytes(b"png")
    (d / "pack-manifest.json").write_text(json.dumps({"files": [{"name": "a.png"}]}), encoding="utf-8")
    _read_only(d / "a.png")
    _read_only(d / "pack-manifest.json")
    assert inst.remove_pack(game, "portraits-hd") == (2, 0)
    assert not d.exists()


def test_our_mod_files_and_packs_delete_through_the_entitled_helper():
    import inspect
    assert "safe_fs.unlink_entitled(p)" in inspect.getsource(inst.do_uninstall)
    assert "safe_fs.unlink_entitled(f)" in inspect.getsource(inst.remove_pack)


# ---------------------------------------------------------------- L2 (a): Thinker's own alphax.txt copies

THINKER_COPIES = {"smac_mod/alphax.txt": b"thinker's smac rules", "german/alphax.txt": b"thinker's german rules"}


def _with_copies(tmp_path, monkeypatch):
    files = {**NEW, **THINKER_COPIES, "Changelog.md": b"what's new"}
    table = {rel.lower(): (rel, hashlib.sha256(data).hexdigest()) for rel, data in files.items()}
    pid = tf.compiled_pin().pin_id
    monkeypatch.setattr(tf, "_pin_files", lambda pin_id: dict(table) if pin_id == pid else {})
    game = _folder(tmp_path / "game", {"terranx.exe": b"MZ", "alphax.txt": b"the game's rules"})
    staged_dir = _folder(tmp_path / "staged", files)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in files}
    p = tu.plan(game, pid, staged, known=KNOWN, old_stock=None, ts="5.5", from_label=st.Label())
    prep = tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), None, p, "5.5", st.OTHER, new=True)
    tf.commit(prep, route="fresh")
    tf.finish(prep)
    return game


def test_thinkers_own_alphax_copies_are_recorded_and_removed(tmp_path, monkeypatch):
    game = _with_copies(tmp_path, monkeypatch)
    rec = tf.read_install_record(game)
    assert set(THINKER_COPIES) <= set(rec["files"]) and "alphax.txt" not in rec["files"]
    tf.remove_thinker(game)
    assert not any(game.joinpath(*r.split("/")).exists() for r in THINKER_COPIES)
    assert (game / "alphax.txt").is_file()                              # the game's own rules: never


def test_an_edited_thinker_alphax_copy_is_kept_and_named(tmp_path, monkeypatch):
    game = _with_copies(tmp_path, monkeypatch)
    (game / "german" / "alphax.txt").write_bytes(b"my german rules")
    tf.remove_thinker(game)
    assert (game / "german" / "alphax.txt").read_bytes() == b"my german rules"
    assert f"{'german' + chr(92) + 'alphax.txt':<20} - a Thinker Mod file you changed, so it was kept" in tf.kept_lines()


@pytest.mark.parametrize("rel", ["alphax.txt", "ALPHAX.TXT", "thinker_user.ini", "smac_mod/thinker_user.ini"])
def test_the_games_rules_and_the_players_settings_are_never_ours(rel):
    assert tf._never_removed(rel)


# ---------------------------------------------------------------- L2 (b): our portraits readme

def test_the_portraits_readme_goes_and_then_an_empty_portraits_folder(tmp_path):
    game = tmp_path / "game"
    (game / "portraits").mkdir(parents=True)
    (game / "portraits" / inst.PORTRAITS_README).write_bytes(b"how to replace portraits")
    assert inst.remove_portraits_readme(game) == (1, 0)
    assert not (game / "portraits").exists()


def test_the_players_portraits_stay(tmp_path):
    game = tmp_path / "game"
    (game / "portraits").mkdir(parents=True)
    (game / "portraits" / inst.PORTRAITS_README).write_bytes(b"how to replace portraits")
    (game / "portraits" / "mine.png").write_bytes(b"the player's")
    inst.remove_portraits_readme(game)
    assert (game / "portraits" / "mine.png").read_bytes() == b"the player's"
    assert not (game / "portraits" / inst.PORTRAITS_README).exists()


def test_the_uninstall_removes_the_readme():
    import inspect
    assert "remove_portraits_readme(game_dir)" in inspect.getsource(inst.do_uninstall)


# ---------------------------------------------------------------- L2 (c): no empty [Longevity] left behind

def _ini(game: Path, data: bytes) -> Path:
    p = Path(inst._ini_path_str(game))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_an_empty_longevity_section_goes_and_every_other_byte_stays(tmp_path):
    before = b"; the game's\r\n[Alpha Centauri]\r\nx=1\r\n\r\n"
    after = b"[UIMod]\r\ny = 2 \r\n"
    p = _ini(tmp_path / "game", before + b"[Longevity]\r\n\r\n" + after)
    assert inst.drop_empty_ini_section(tmp_path / "game", "Longevity") is True
    assert p.read_bytes() == before + after


def test_a_section_with_anything_left_in_it_stays(tmp_path):
    data = b"[Longevity]\r\nPlayersOwn=1\r\n[UIMod]\r\ny=2\r\n"
    p = _ini(tmp_path / "game", data)
    assert inst.drop_empty_ini_section(tmp_path / "game", "Longevity") is False
    assert p.read_bytes() == data


def test_the_uninstall_drops_the_empty_section_wherever_it_clears_the_receipt():
    import inspect
    src_ = inspect.getsource(inst.do_uninstall)
    assert src_.count("rc.clear(game_dir, say=ix.say)") == src_.count("drop_empty_ini_section(game_dir, rc.INI_SECTION)")


# ---------------------------------------------------------------- L3: the updater is never deployed through a link

@windows
def test_the_updater_is_never_deployed_through_a_junction(tmp_path):
    import _winapi
    import bootstrap as bs
    game = tmp_path / "game"
    game.mkdir()
    outside = tmp_path / "players"
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(game / "LongevityMods"))
    with pytest.raises(OSError) as e:
        bs.deploy(game, tmp_path / "payload", "1.0.0", say=lambda *a: None)
    assert str(e.value) == f"{game / 'LongevityMods'} is a link to another folder"
    assert not any(outside.iterdir())


@windows
def test_setup_says_this_copy_cannot_update_itself(tmp_path, monkeypatch):
    import _winapi
    game = tmp_path / "game"
    game.mkdir()
    (tmp_path / "players").mkdir()
    _winapi.CreateJunction(str(tmp_path / "players"), str(game / "LongevityMods"))
    err = inst._deploy_resident(game)
    assert isinstance(err, OSError) and "is a link to another folder" in str(err)
    assert not any((tmp_path / "players").iterdir())


@windows
def test_reconcile_never_works_through_a_junction(tmp_path):
    import _winapi
    import bootstrap as bs
    game = tmp_path / "game"
    game.mkdir()
    outside = tmp_path / "players"
    (outside / "updater.prev").mkdir(parents=True)
    _winapi.CreateJunction(str(outside), str(game / "LongevityMods"))
    bs.reconcile(game, say=lambda *a: None)
    assert (outside / "updater.prev").is_dir() and not (outside / "updater").exists()


# ---------------------------------------------------------------- L4: no silent e2e skips under the release gate

def test_no_test_skips_the_bundled_interpreter_or_the_batch_with_a_plain_skipif():
    plain = re.compile(r"skipif\(\s*not\s+_(PY|BAT)\.(exists|is_file)\(\)")
    hits = [p.name for p in _TESTS.glob("test_*.py") if plain.search(p.read_text(encoding="utf-8"))]
    assert hits == [], hits


@pytest.mark.parametrize("require", [False, True], ids=["skip", "fail-under-the-gate"])
def test_needs_local_skips_or_fails(tmp_path, monkeypatch, require):
    import conftest
    if require:
        monkeypatch.setenv("LONGEVITY_REQUIRE_E2E", "1")
    else:
        monkeypatch.delenv("LONGEVITY_REQUIRE_E2E", raising=False)
    mark = pytest.mark.needs_local(tmp_path / "absent.exe", "the bundled interpreter").mark
    item = types.SimpleNamespace(iter_markers=lambda name: [mark] if name == "needs_local" else [])
    with pytest.raises(pytest.fail.Exception if require else pytest.skip.Exception):
        conftest.pytest_runtest_setup(item)


# ---------------------------------------------------------------- MEDIUM-2: --fix-thinker sees the missing files

def _fix_world(tmp_path, monkeypatch, answers=()):
    """--fix-thinker over this installer's Thinker 5.5 (the pinned build), two of its files gone."""
    from test_thinker_flow import World
    game, _ = _installed_thinker(tmp_path)
    (game / "modmenu.txt").unlink()
    (game / "basenames" / "hive.txt").unlink()
    real = tf.compiled_meta()
    monkeypatch.setattr(tf, "compiled_meta", lambda: {**real, "dll": tu.sha256(game / "thinker.dll")})
    w = World(tmp_path, monkeypatch, label=None, answers=list(answers))
    w.prepared = []
    monkeypatch.setattr(tf, "prepare", lambda *a, **k: w.prepared.append(k) or types.SimpleNamespace(
        committed=False, repair=len(k.get("repair") or []), ts="5.5", report=None, plan=None, dll=None))
    return w


def test_fix_thinker_offers_the_repair_instead_of_already_working_together(tmp_path, monkeypatch):
    w = _fix_world(tmp_path, monkeypatch, answers=[""])
    assert w.run() == ix.EXIT_OK
    assert w.asked == [(["Repair Thinker Mod 5.5", "Keep Thinker Mod 5.5 as it is"],
                        ["Thinker Mod 5.5 in this game folder is missing 2 of its files.", "",
                         "This installer can download Thinker Mod 5.5 and put the missing files back. Files you "
                         "changed are not touched."])]                 # and no thinker.ini choice after a repair
    assert w.prepared[0]["repair"] == ["basenames/hive.txt", "modmenu.txt"] and w.committed == [{"route": "thinker"}]
    assert inst._VERDICT == ("UPDATE COMPLETE", f"Thinker Mod 5.5 was repaired. Longevity Vaccine {inst.ver.VERSION} "
                                                "and Thinker Mod 5.5 now work together.")


def test_fix_thinker_keep_changes_nothing(tmp_path, monkeypatch):
    w = _fix_world(tmp_path, monkeypatch, answers=["n"])
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.title == "UPDATE CANCELLED" and w.committed == [] and w.prepared == []
    assert e.value.message == "You chose to keep Thinker Mod 5.5 as it is, so nothing was changed. It is missing 2 of " \
                              "its files."


@pytest.mark.parametrize("how", ["no-console", "no-prompt"])
def test_fix_thinker_without_asking_refuses_and_never_says_they_work_together(tmp_path, monkeypatch, how):
    w = _fix_world(tmp_path, monkeypatch)
    if how == "no-console":
        monkeypatch.setattr(ix, "can_ask", lambda: False)
    else:
        w.args.no_prompt = True
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert "already work together" not in e.value.message and w.prepared == []
    assert e.value.message.startswith("Thinker Mod 5.5 is missing 2 of its files, and ")


def test_fix_thinker_with_thinker_repairs_without_asking(tmp_path, monkeypatch):
    w = _fix_world(tmp_path, monkeypatch)
    w.args.with_thinker = True
    assert w.run() == ix.EXIT_OK and w.asked == [] and w.prepared[0]["repair"]


# ---------------------------------------------------------------- MEDIUM-1 (user-approved 2026-11-16): the whole Thinker

def _update_from_54(tmp_path):
    """The player's Thinker 5.4 (test_thinker_update.OLD) plus one file identical to the release's ("keep")."""
    from test_thinker_update import OLD, V54
    game = _folder(tmp_path / "game", {**OLD, "basenames/hive.txt": NEW["basenames/hive.txt"]})
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V54)
    prep = tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), types.SimpleNamespace(label=V54), p, "5.5", st.UP)
    before = {rel: game.joinpath(*rel.split("/")).read_bytes() for rel in NEW if game.joinpath(*rel.split("/")).is_file()}
    return game, prep, before


def _set(bdir: Path) -> dict:
    return {f.relative_to(bdir).as_posix(): f.read_bytes() for f in bdir.rglob("*") if f.is_file()}


def test_an_update_backs_up_the_players_whole_thinker(tmp_path):
    """Every file of the player's build that the new release also has -- replaced or kept as it is (hive.txt, the
    player's alphax.txt), thinker.exe included: the set can put the old Thinker back on its own."""
    game, prep, before = _update_from_54(tmp_path)
    assert {a.rel for a in prep.plan.actions if a.kind == "keep"} >= {"basenames/hive.txt", "alphax.txt"}
    tf.commit(prep, route="thinker")
    got = _set(prep.report.backup_dir)
    # OLD's "patched help" is not exactly our patch of its backup: the player's own text, kept as it is (audit-l H1)
    assert {rel: got.get(rel) for rel in before} == before


def test_a_first_install_and_a_repair_back_up_nothing_they_did_not_replace(tmp_path):
    from test_thinker_install_review import _first_install_plan
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ", "basenames/hive.txt": NEW["basenames/hive.txt"]})
    tf.commit(prep, route="fresh")
    assert _set(prep.report.backup_dir) == {}


def test_undo_never_writes_a_kept_files_backup_copy_back(tmp_path):
    game, prep, _ = _update_from_54(tmp_path)
    tf.commit(prep, route="thinker")
    (prep.report.backup_dir / "basenames" / "hive.txt").write_bytes(b"not what is in the game folder")
    (game / "basenames" / "hive.txt").write_bytes(b"the player edited it after the swap")
    assert tu.undo(game) == tu.UNDONE
    assert (game / "basenames" / "hive.txt").read_bytes() == b"the player edited it after the swap"
    assert (game / "thinker.dll").read_bytes() == b"old dll"            # what the change replaced: back


def test_recovery_never_writes_a_kept_files_backup_copy_back(tmp_path):
    game, prep, _ = _update_from_54(tmp_path)
    tf.commit(prep, route="thinker")                                     # killed before finish: the journal stays
    (prep.report.backup_dir / "alphax.txt").write_bytes(b"tampered copy")
    for a in prep.plan.changes():                                        # half the swap undone by hand: roll back
        if a.rel == "thinker.exe":
            (game / "thinker.exe").write_bytes(b"something else")
    tu.recover(game)
    assert (game / "alphax.txt").read_bytes() == b"player rules"
