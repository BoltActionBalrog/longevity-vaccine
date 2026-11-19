"""thinker_update: plan, timestamped backup sets, journal, tmp-and-rename swap with thinker.dll last,
rollback (F5 / F6) and crash recovery. Throwaway folders only."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import thinker_state as st     # noqa: E402
import thinker_update as tu    # noqa: E402

KNOWN = {"video_mode", "expansion_limit"}
OLD = {"thinker.dll": b"old dll", "thinker.exe": b"old exe", "alphax.txt": b"player rules",
       "thinker.ini": b"[thinker]\r\nvideo_mode=2\r\nretired=1\r\n", "modmenu.txt": b"old menu",
       "smac_mod/helpx.txt": b"patched help", "smac_mod/helpx.txt.longevity.bak": b"old stock help",
       "ac_mod/legacy.txt": b"left alone"}
NEW = {"thinker.dll": b"new dll", "thinker.exe": b"new exe", "alphax.txt": b"thinker rules",
       "thinker.ini": b"[thinker]\r\nvideo_mode=0\r\nexpansion_limit=50\r\n", "modmenu.txt": b"new menu",
       "smac_mod/helpx.txt": b"new stock help", "basenames/hive.txt": b"hive"}
V54 = st.parse_label("Thinker Mod v5.4")


def _folder(root: Path, files: dict) -> Path:
    for rel, data in files.items():
        p = root.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def _setup(tmp_path, user_ini: bytes = None):
    game = _folder(tmp_path / "game", OLD)
    if user_ini is not None:
        (game / "thinker_user.ini").write_bytes(user_ini)
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V54)
    return game, p


def _read(game: Path, rel: str) -> bytes:
    return game.joinpath(*rel.split("/")).read_bytes()


def test_plan_and_commit(tmp_path):
    game, p = _setup(tmp_path, user_ini=b"[thinker]\r\nvideo_mode=1\r\nnerve_staple=3\r\n")
    kinds = {a.rel: a.kind for a in p.actions}
    assert kinds["alphax.txt"] == "keep" and p.kept_alphax
    assert kinds["basenames/hive.txt"] == "add" and kinds["thinker.dll"] == "replace"
    assert kinds["thinker_user.ini"] == "rewrite"
    assert p.datalinks_ours == []                     # "patched help" is not a patch of ours (no exact undo)
    r = tu.commit(p, now=1763130612)
    assert _read(game, "thinker.dll") == b"new dll" and _read(game, "basenames/hive.txt") == b"hive"
    assert _read(game, "alphax.txt") == b"player rules"                     # always kept
    assert _read(game, "ac_mod/legacy.txt") == b"left alone"                # not in the release
    assert b"video_mode=2" in _read(game, "thinker.ini")                    # carried
    assert b";retired=1" in _read(game, "thinker.ini")                      # commented
    assert _read(game, "thinker_user.ini") == b"[thinker]\r\nvideo_mode=1\r\n;nerve_staple=3\r\n"
    assert _read(game, "smac_mod/helpx.txt") == b"new stock help"
    # an earlier version's leftover backup is never read or rewritten (master's exact-undo model, ruling 2026-11-17)
    assert _read(game, "smac_mod/helpx.txt.longevity.bak") == b"old stock help"
    b = r.backup_dir
    assert b.name.startswith("thinker-5.4-") and b.parent == game / "LongevityMods" / "backups"
    assert (b / "thinker.dll").read_bytes() == b"old dll"
    # "patched help" is not a patch of ours that inverts exactly, so it is the player's own text: the set keeps it
    # byte for byte (audit-l H1); no .longevity.bak goes anywhere
    assert (b / "smac_mod" / "helpx.txt").read_bytes() == b"patched help"
    assert not (b / "smac_mod" / "helpx.txt.longevity.bak").exists()
    assert not (tu.rollback_dir(b) / "smac_mod" / "helpx.txt.longevity.bak").exists()
    assert (b / "thinker_user.ini").exists() and not (b / "basenames").exists()
    assert tu.read_journal(game)["step"] == 3                               # until step 6
    tu.finish(game)
    assert tu.read_journal(game) is None
    assert not list(game.rglob("*" + tu.TMP))


def test_sets_are_never_reused_or_deleted(tmp_path):
    game, p = _setup(tmp_path)
    r1 = tu.commit(p, now=1763130612)
    tu.finish(game)
    staged = {rel: tmp_path.joinpath("staged", *rel.split("/")) for rel in NEW}
    _folder(game, {"thinker.dll": b"older again"})
    p2 = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V54)
    r2 = tu.commit(p2, now=1763130612)                                      # same second
    assert r2.backup_dir.name == r1.backup_dir.name + "-2"
    assert r1.backup_dir.is_dir() and r2.older_backups == 1


def test_backup_labels():
    assert tu.backup_label(V54) == "5.4"
    assert tu.backup_label(st.parse_label("Thinker Mod develop build")) == "develop"
    assert tu.backup_label(st.Label()) == "other"


def test_dll_is_renamed_last(tmp_path):
    game, p = _setup(tmp_path)
    seen = []
    real = tu.os.replace

    def spy(a, b):
        seen.append(Path(b).name)
        real(a, b)
    tu.commit(p, _replace=spy)
    assert seen[-1] == "thinker.dll" and "helpx.txt.longevity.bak" not in seen


def test_failure_rolls_back_f5(tmp_path):
    game, p = _setup(tmp_path)
    before = {f: f.read_bytes() for f in game.rglob("*") if f.is_file()}
    calls = []
    real = tu.os.replace

    def flaky(a, b):
        calls.append(b)
        if len(calls) == 3:
            raise PermissionError(13, "in use", str(b))
        real(a, b)
    with pytest.raises(tu.ThinkerError) as e:
        tu.commit(p, _replace=flaky)
    assert e.value.kind == "F5"
    after = {f: f.read_bytes() for f in game.rglob("*") if f.is_file()}
    assert after == before                                  # including no new backup set
    assert tu.read_journal(game) is None
    assert not (game / "LongevityMods" / "backups").exists() or not any((game / "LongevityMods" / "backups").iterdir())


def test_rollback_failure_reports_f6(tmp_path, monkeypatch):
    game, p = _setup(tmp_path)
    calls = []
    real = tu.os.replace

    def flaky(a, b):
        calls.append(b)
        if len(calls) == 3:
            raise PermissionError(13, "in use", str(b))
        real(a, b)
    monkeypatch.setattr(tu, "_rollback", lambda *a: ["thinker.exe"])
    with pytest.raises(tu.ThinkerError) as e:
        tu.commit(p, _replace=flaky)
    assert e.value.kind == "F6" and e.value.files == ["thinker.exe"]
    assert tu.read_journal(game) is not None                # F6 leaves the journal for recovery


def _crash_after(n):
    calls = []
    real = tu.os.replace

    def crashing(a, b):
        calls.append(b)
        if len(calls) > n:
            raise KeyboardInterrupt                         # not an OSError: no rollback, like a power cut
        real(a, b)
    return crashing


def test_crash_mid_swap_is_finished_by_recovery(tmp_path):
    game, p = _setup(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        tu.commit(p, _replace=_crash_after(2))
    assert tu.read_journal(game)["step"] == 2
    assert _read(game, "thinker.dll") == b"old dll"
    assert tu.recover(game) == tu.FINISHED
    assert _read(game, "thinker.dll") == b"new dll" and tu.read_journal(game) is None
    assert not list(game.rglob("*" + tu.TMP))


def test_crash_without_tmp_files_is_undone(tmp_path):
    game, p = _setup(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        tu.commit(p, _replace=_crash_after(2))
    for t in game.rglob("*" + tu.TMP):
        t.unlink()                                          # e.g. an antivirus removed them
    assert tu.recover(game) == tu.UNDONE
    assert _read(game, "thinker.dll") == b"old dll" and _read(game, "thinker.exe") == b"old exe"
    assert _read(game, "smac_mod/helpx.txt.longevity.bak") == b"old stock help"


def test_longevity_route_follows_the_live_exe(tmp_path):
    game, p = _setup(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        tu.commit(p, route="longevity", exe={"current": "aa", "staged": "bb"}, _replace=_crash_after(2))
    assert tu.recover(game, live_exe_md5="aa") == tu.UNDONE          # old exe: Thinker back
    assert _read(game, "thinker.dll") == b"old dll"


def test_longevity_route_unknown_exe_is_lost(tmp_path):
    game, p = _setup(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        tu.commit(p, route="longevity", exe={"current": "aa", "staged": "bb"}, _replace=_crash_after(2))
    assert tu.recover(game, live_exe_md5="zz") == tu.LOST
    assert tu.read_journal(game) is None                              # never outlives one attempt


def test_recovery_sees_a_finished_or_undone_folder(tmp_path):
    game, p = _setup(tmp_path)
    tu.commit(p)
    assert tu.recover(game) == tu.FINISHED                            # step 6 never ran
    assert tu.recover(game) is None


def test_reparse_points_are_refused(tmp_path, monkeypatch):
    game = _folder(tmp_path / "game", OLD)
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    monkeypatch.setattr(tu, "_is_reparse", lambda p: Path(p).name == "basenames")
    with pytest.raises(tu.ThinkerError) as e:
        tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V54)
    assert e.value.kind == "REFUSED"


def test_unchanged_files_are_kept(tmp_path):
    game = _folder(tmp_path / "game", {**OLD, "modmenu.txt": b"new menu"})
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V54)
    assert {a.rel: a.kind for a in p.actions}["modmenu.txt"] == "keep"


def test_probe_locks_none_when_free(tmp_path):
    game, p = _setup(tmp_path)
    assert tu.probe_locks(p, tries=1, wait=0) is None


# ---------------------------------------------------------------- round-7 security regressions (planted journals)

def _plant(game: Path, doc) -> None:
    j = game / tu.JOURNAL
    j.parent.mkdir(parents=True, exist_ok=True)
    j.write_text(__import__("json").dumps(doc), encoding="utf-8")


def test_a_planted_journal_cannot_delete_outside_the_game_folder(tmp_path):
    game = _folder(tmp_path / "game", OLD)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"keep me")
    _plant(game, {"route": "thinker", "step": 0, "backup": "thinker-5.4-20261114-153012",
                  "actions": [{"rel": "../victim.txt", "old": "", "new": "0" * 64}]})
    assert tu.recover(game) == tu.LOST
    assert victim.read_bytes() == b"keep me" and tu.read_journal(game) is None


def test_a_planted_journal_cannot_write_through_a_backup_name(tmp_path):
    game = _folder(tmp_path / "game", OLD)
    _plant(game, {"route": "thinker", "step": 0, "backup": "../../evil",
                  "actions": [{"rel": "thinker.dll", "old": "a" * 64, "new": "b" * 64}]})
    assert tu.recover(game) == tu.LOST
    assert _read(game, "thinker.dll") == b"old dll"


@pytest.mark.parametrize("doc", [[1, 2], {"actions": [{"rel": 5}]}, {"backup": 7, "actions": []},
                                 {"backup": "thinker-5.4-20261114-153012", "actions": "x"},
                                 {"backup": "thinker-5.4-20261114-153012", "actions": [{"rel": "thinker.dll"}]},
                                 {"backup": "thinker-5.4-20261114-153012", "step": "2", "actions": []}])
def test_a_malformed_journal_never_crashes_and_is_cleared(tmp_path, doc):
    game = _folder(tmp_path / "game", OLD)
    _plant(game, doc)
    assert tu.recover(game) == tu.LOST
    assert tu.read_journal(game) is None


def test_a_journal_that_is_not_json_is_cleared(tmp_path):
    game = _folder(tmp_path / "game", OLD)
    (game / tu.JOURNAL).parent.mkdir(parents=True, exist_ok=True)
    (game / tu.JOURNAL).write_bytes(b"\x00garbage")
    assert tu.recover(game) == tu.LOST and not (game / tu.JOURNAL).exists()


def test_undo_after_a_successful_swap_puts_the_old_files_back(tmp_path):
    game, p = _setup(tmp_path)
    tu.commit(p)
    assert _read(game, "thinker.dll") == b"new dll"
    assert tu.undo(game) == tu.UNDONE
    assert _read(game, "thinker.dll") == b"old dll" and not (game / "basenames" / "hive.txt").exists()
    assert _read(game, "smac_mod/helpx.txt.longevity.bak") == b"old stock help"
    assert tu.read_journal(game) is None


def test_f5_never_removes_a_set_it_did_not_create(tmp_path, monkeypatch):
    game, p = _setup(tmp_path)
    existing = game / tu.BACKUPS / "thinker-5.4-20261114-153012"
    existing.mkdir(parents=True)
    (existing / "precious.txt").write_bytes(b"x")
    monkeypatch.setattr(tu, "new_backup_dir", lambda *a: existing)          # a race: the name now exists
    with pytest.raises(tu.ThinkerError):
        tu.commit(p)
    assert (existing / "precious.txt").exists()


def test_a_link_at_the_tmp_name_is_not_followed(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_bytes(b"untouched")
    dest = tmp_path / "game" / "thinker.dll"
    dest.parent.mkdir()
    tmp = dest.with_name(dest.name + tu.TMP)
    try:
        os.symlink(target, tmp)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    tu._write_tmp(dest, b"new")
    assert target.read_bytes() == b"untouched" and tmp.read_bytes() == b"new"
