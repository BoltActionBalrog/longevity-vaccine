"""Setting a Thinker folder up: plan (asks nothing, writes nothing), apply (all or nothing), undo
(the uninstall puts the original back, and never destroys a file it did not put there). The full
install / re-run / uninstall cycle runs end to end in test_install_e2e; this covers every shape,
failure and edge case, in process, on throwaway folders."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst        # noqa: E402
import installer_exit as ix   # noqa: E402

inst._load_modules()


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): _md5(p) for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def folder(tmp_path, bak_path, pristine_bytes):
    g = tmp_path / "game"
    g.mkdir()
    (g / "terranx.exe").write_bytes(pristine_bytes)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "thinker.dll").write_bytes(b"dll")
    (g / "thinker.exe").write_bytes(b"exe")
    return g


def _args(**kw):
    return types.SimpleNamespace(**{"no_prompt": False, **kw})


def _console(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": next(it))


def _unattended(monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("must not ask"))


BASE = None


@pytest.fixture(autouse=True)
def _base():
    global BASE
    BASE = inst._thinker_overlay().base_md5


# ---------------------------------------------------------------- the plan

def _no_question(monkeypatch):
    """A console whose keyboard is never read: the set-up asks nothing (user 2026-11-06)."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("the set-up must not ask"))
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("the set-up must not ask"))


def test_a_stock_folder_is_set_up_without_a_question_and_the_plan_writes_nothing(folder, monkeypatch, capsys):
    before = _tree(folder)
    _no_question(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["action"] == "setup" and plan["vanilla"]
    assert plan["backup"].name == "terranx_original.exe" and plan["src"].name == "terranx_PRACX.exe"
    assert _tree(folder) == before
    assert capsys.readouterr().out == ""                  # the plan says nothing; apply says one line


def test_apply_says_the_users_one_line(folder, monkeypatch, capsys):
    _no_question(monkeypatch)
    assert inst.apply_thinker_setup(inst.plan_thinker_setup(folder, _args()))
    out = capsys.readouterr().out
    assert ("  Swapped the vanilla Alien Crossfire .exe for the PRACX .exe. This is required to load both Longevity "
            "and Thinker. Your original is kept as terranx_original.exe. Uninstalling Longevity Vaccine puts it back.") in out
    assert out.count("\n  ") == 1 and "Thinker starts only" not in out and "?" not in out


def test_an_unrecognised_terranx_is_set_up_too_and_kept_under_a_hashed_name(folder, monkeypatch, capsys):
    """Reversible, so no question even here (user 2026-11-06): the file is kept, --uninstall puts
    it back; the line names what was swapped and where it went."""
    (folder / "terranx.exe").write_bytes(b"MZ something else")
    own = _md5(folder / "terranx.exe")
    _no_question(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["md5"] == own and not plan["vanilla"]
    assert inst.apply_thinker_setup(plan)
    assert _md5(folder / "terranx_original.exe") == own and _md5(folder / "terranx.exe") == BASE
    out = capsys.readouterr().out
    assert "Swapped the terranx.exe that was here for the PRACX .exe." in out
    assert "Your original is kept as terranx_original.exe." in out


def test_unattended_sets_up_a_stock_folder_and_an_unrecognised_one_alike(folder, monkeypatch, capsys):
    _unattended(monkeypatch)
    assert inst.plan_thinker_setup(folder, _args())["vanilla"]
    (folder / "terranx.exe").write_bytes(b"MZ something else")
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["action"] == "setup" and not plan["vanilla"]
    assert capsys.readouterr().out == ""


def test_no_prompt_never_asks(folder, monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": pytest.fail("must not ask"))
    assert inst.plan_thinker_setup(folder, _args(no_prompt=True))


@pytest.mark.parametrize("change", ["no-thinker", "terranx-is-pracx", "no-pracx"])
def test_nothing_to_set_up(folder, monkeypatch, bak_path, change):
    _unattended(monkeypatch)
    if change == "no-thinker":
        (folder / "thinker.dll").unlink()
    elif change == "terranx-is-pracx":
        shutil.copy2(bak_path, folder / "terranx.exe")
    else:
        (folder / "terranx_PRACX.exe").unlink()
    assert inst.plan_thinker_setup(folder, _args()) is None


def test_the_source_can_be_the_backup_of_a_patched_pracx(folder, monkeypatch, bak_path):
    """terranx_PRACX.exe already patched by an earlier plain install: the copy comes from its .bak."""
    _unattended(monkeypatch)
    shutil.copy2(bak_path, folder / "terranx_PRACX.exe.bak")
    (folder / "terranx_PRACX.exe").write_bytes(b"MZ our plain build")
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan["src"].name == "terranx_PRACX.exe.bak"
    assert inst.apply_thinker_setup(plan)
    assert _md5(folder / "terranx.exe") == BASE


# ---------------------------------------------------------------- applying it

def test_apply_keeps_the_original_and_records_it(folder, monkeypatch):
    _unattended(monkeypatch)
    vanilla = _md5(folder / "terranx.exe")
    assert inst.apply_thinker_setup(inst.plan_thinker_setup(folder, _args()))
    assert _md5(folder / "terranx_original.exe") == vanilla and _md5(folder / "terranx.exe") == BASE
    rec = json.loads((folder / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    assert rec == {"exe": "terranx.exe", "backup": "terranx_original.exe", "original_md5": vanilla,
                   "source": "terranx_PRACX.exe"}
    assert inst.plan_thinker_setup(folder, _args()) is None          # set up: nothing more to do


def test_a_taken_backup_name_is_never_overwritten(folder, monkeypatch):
    _unattended(monkeypatch)
    (folder / "terranx_original.exe").write_bytes(b"the player's own file")
    vanilla = _md5(folder / "terranx.exe")
    assert inst.apply_thinker_setup(inst.plan_thinker_setup(folder, _args()))
    assert (folder / "terranx_original.exe").read_bytes() == b"the player's own file"
    assert _md5(folder / f"terranx_original-{vanilla[:8]}.exe") == vanilla


def test_not_enough_space_changes_nothing(folder, monkeypatch):
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    before = _tree(folder)
    monkeypatch.setattr(inst.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=1000))
    with pytest.raises(ix.InstallerError) as e:
        inst.apply_thinker_setup(plan)
    assert e.value.changed is False and "disk space" in e.value.message
    assert _tree(folder) == before


def test_a_failure_after_the_original_moved_puts_it_back(folder, monkeypatch):
    """The second rename failing (the new terranx.exe cannot be placed) rolls the first back."""
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    before = _tree(folder)
    real, calls = inst.os.replace, []

    def flaky(a, b):
        calls.append((Path(a).name, Path(b).name))
        if Path(a).name.endswith(".longevity-tmp"):
            raise PermissionError("locked")
        return real(a, b)
    monkeypatch.setattr(inst.os, "replace", flaky)
    with pytest.raises(ix.InstallerError) as e:
        inst.apply_thinker_setup(plan)
    assert e.value.changed is False
    assert ("terranx.exe", "terranx_original.exe") in calls        # it did get that far
    assert _tree(folder) == before


def test_a_set_up_that_stopped_half_way_is_finished_without_a_second_backup(folder, monkeypatch):
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    inst.apply_thinker_setup(plan)
    rec = (folder / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8")
    (folder / "terranx.exe").unlink()                               # stopped between the renames
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["backup"] is None
    assert inst.apply_thinker_setup(plan)
    assert _md5(folder / "terranx.exe") == BASE
    assert (folder / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8") == rec
    assert sorted(p.name for p in folder.glob("terranx_original*")) == ["terranx_original.exe"]


# ---------------------------------------------------------------- undoing it

@pytest.fixture
def set_up(folder, monkeypatch, bak_path):
    """A folder set up for Thinker, as the uninstall sees it after restoring the exes: terranx.exe
    is our clean PRACX copy with its .bak beside it."""
    _unattended(monkeypatch)
    vanilla = _md5(folder / "terranx.exe")
    inst.apply_thinker_setup(inst.plan_thinker_setup(folder, _args()))
    shutil.copy2(bak_path, folder / "terranx.exe.bak")
    return folder, vanilla


def test_undo_puts_the_original_back_and_removes_what_it_added(set_up):
    g, vanilla = set_up
    assert inst.undo_thinker_setup(g) == 1
    assert _md5(g / "terranx.exe") == vanilla
    assert not (g / "terranx_original.exe").exists() and not (g / "terranx.exe.bak").exists()
    assert not (g / inst.THINKER_SETUP_NAME).exists()
    assert _md5(g / "terranx_PRACX.exe") == BASE
    assert inst.undo_thinker_setup(g) == 0                           # idempotent


def test_undo_leaves_a_terranx_the_player_replaced(set_up, capsys):
    g, vanilla = set_up
    (g / "terranx.exe").write_bytes(b"MZ the player's own")
    held = []
    assert inst.undo_thinker_setup(g, held) == 0
    assert (g / "terranx.exe").read_bytes() == b"MZ the player's own"
    assert _md5(g / "terranx_original.exe") == vanilla
    assert "left as it is" in capsys.readouterr().out
    # held for the uninstall's generic restore, and the record goes (it would keep the folder
    # "installed" for good, and a second uninstall loop on it): re-audit 2026-11-01
    assert held == ["terranx.exe"] and not (g / inst.THINKER_SETUP_NAME).exists()
    assert not (g / "terranx.exe.bak").exists() and not inst._has_install(g)


def test_undo_never_destroys_the_folders_only_pracx_copy(set_up):
    g, vanilla = set_up
    (g / "terranx_PRACX.exe").unlink()
    (g / "terranx.exe.bak").unlink()
    assert inst.undo_thinker_setup(g) == 1
    assert _md5(g / "terranx.exe") == vanilla
    assert _md5(g / "terranx_PRACX.exe") == BASE                     # kept under its old name


def test_undo_will_not_put_back_an_original_that_changed(set_up, capsys):
    g, vanilla = set_up
    (g / "terranx_original.exe").write_bytes(b"MZ changed since")
    assert inst.undo_thinker_setup(g) == 0
    assert _md5(g / "terranx.exe") == BASE
    assert "has changed since" in capsys.readouterr().out


def test_a_set_up_folder_counts_as_installed(set_up):
    g, _ = set_up
    (g / "terranx.exe.bak").unlink()
    assert inst._has_install(g)


# ---------------------------------------------------------------- audit round 1 (2026-11-01)

def _gog_verified(g: Path, vanilla_bytes: bytes) -> None:
    """GOG Galaxy's "verify files" after a set-up: the original terranx.exe is written back."""
    (g / "terranx.exe").write_bytes(vanilla_bytes)


def test_a_foreign_terranx_backup_stops_the_whole_install_before_any_write(folder, monkeypatch, capsys):
    """User 2026-11-05: a terranx.exe.bak that is neither the clean PRACX base nor GOG's original
    fails the install, in the user's words, in red, with nothing written -- at a console or not."""
    (folder / "terranx.exe.bak").write_bytes(b"another tool's backup")
    before = _tree(folder)
    for console in (False, True):
        if console:
            _console(monkeypatch, "", "", "")
        else:
            _unattended(monkeypatch)
        with pytest.raises(ix.InstallerError) as e:
            inst.plan_thinker_setup(folder, _args())
        err = e.value
        assert err.message == inst.FOREIGN_BACKUP_TEXT.format(name="terranx.exe.bak")
        assert err.message == ("Your game installation folder has an unrecognized terranx.exe.bak file. This should only "
                               "happen if you edited that file by hand. Longevity Vaccine cannot install over it. To "
                               "install, verify that you do not need terranx.exe.bak and delete it, then re-run this "
                               "installer. Your game was not modified.")
        assert err.code == ix.EXIT_ABORTED and err.changed is False and err.title == "INSTALLATION FAILED"
        assert err.red and err.any_key and err.disk_note is False and not err.remedy
    assert _tree(folder) == before
    assert "--- Thinker ---" not in capsys.readouterr().out


def test_the_foreign_backup_refusal_is_red_says_nothing_more_and_waits_for_any_key(folder, monkeypatch, capsys):
    """The guard's rendering of that error: the message in red, no second disk line (the message
    already says the game was not modified), no "What to do", the window held on any key."""
    (folder / "terranx.exe.bak").write_bytes(b"another tool's backup")
    _unattended(monkeypatch)
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    waits = []
    monkeypatch.setattr(ix, "wait_for_key", lambda prompt="Press Enter to close this window... ", any_key=False:
                        waits.append((prompt, any_key)))
    monkeypatch.setattr(ix, "interactive", lambda: True)
    code = ix.run_guarded(lambda: inst.plan_thinker_setup(folder, _args()) and 0)
    out = capsys.readouterr().out
    assert code == ix.EXIT_ABORTED
    assert "\x1b[31mYour game installation folder has an unrecognized terranx.exe.bak file." in out
    assert "Nothing on disk was changed" not in out and "What to do" not in out
    assert waits == [("Press any key to close this window...", True)]


def test_a_gog_original_terranx_backup_is_accepted_and_the_duplicate_goes(folder, monkeypatch, pristine_bytes, capsys):
    """terranx.exe.bak that is GOG's original, byte for byte, beside the same original: a spare
    copy of the file the set-up keeps as terranx_original.exe. Accepted without a word; the
    duplicate goes, so the patch pass can write the set-up's own clean-base .bak under that name."""
    (folder / "terranx.exe.bak").write_bytes(pristine_bytes)
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["gog_bak"] == folder / "terranx.exe.bak"
    assert "bak" not in capsys.readouterr().out.lower()
    assert inst.apply_thinker_setup(plan)
    assert not (folder / "terranx.exe.bak").exists()
    assert _md5(folder / "terranx_original.exe") == hashlib.md5(pristine_bytes).hexdigest()
    assert _md5(folder / "terranx.exe") == BASE
    rec = json.loads((folder / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    assert rec["backup"] == "terranx_original.exe" and not rec.get("set_aside")


def test_a_gog_original_backup_beside_another_terranx_is_set_aside_and_recorded(folder, monkeypatch, pristine_bytes, capsys):
    """The rare shape: terranx.exe is something the installer does not know, and terranx.exe.bak is
    GOG's original. Nothing is deleted: the unknown exe is kept as the original, GOG's copy is set
    aside under an _original name and recorded, so --uninstall names it."""
    (folder / "terranx.exe").write_bytes(b"MZ a player's own build")
    (folder / "terranx.exe.bak").write_bytes(pristine_bytes)
    gog = hashlib.md5(pristine_bytes).hexdigest()
    _no_question(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["gog_bak"] is not None
    assert inst.apply_thinker_setup(plan)
    own = hashlib.md5(b"MZ a player's own build").hexdigest()
    # The live file is "the original" the set-up keeps, under the plain name as always; GOG's
    # spare copy takes the hashed one, so neither is lost and --uninstall puts the live one back.
    assert _md5(folder / "terranx_original.exe") == own
    aside = folder / f"terranx_original-{gog[:8]}.exe"
    assert _md5(aside) == gog and not (folder / "terranx.exe.bak").exists()
    rec = json.loads((folder / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    assert rec["set_aside"] == [aside.name] and rec["backup"] == "terranx_original.exe"
    assert f"GOG's original) is kept as {aside.name}" in capsys.readouterr().out
    # and the undo names it, puts the player's own build back, and leaves GOG's copy where it is
    assert inst.undo_thinker_setup(folder) == 1
    assert _md5(folder / "terranx.exe") == own and _md5(aside) == gog
    assert not (folder / inst.THINKER_SETUP_NAME).exists()


def test_the_backup_is_checked_whatever_terranx_is(folder, monkeypatch, bak_path, pristine_bytes, capsys):
    """Audit 2026-11-05: with terranx.exe ALREADY the clean PRACX base, a foreign .bak used to slip
    past the check, get patched over (the patch pass keeps an existing .bak) and leave a build no
    later run could recognise. The foreign refusal now comes first; a GOG spare is set aside."""
    shutil.copy2(bak_path, folder / "terranx.exe")
    (folder / "terranx.exe.bak").write_bytes(b"MZ another tool's backup")
    _unattended(monkeypatch)
    with pytest.raises(ix.InstallerError) as e:
        inst.plan_thinker_setup(folder, _args())
    assert e.value.message.startswith("Your game installation folder has an unrecognized terranx.exe.bak")
    (folder / "terranx.exe.bak").write_bytes(pristine_bytes)
    before = _tree(folder)
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["action"] == "aside" and _tree(folder) == before
    assert inst.apply_thinker_setup(plan) is False
    gog = hashlib.md5(pristine_bytes).hexdigest()
    assert not (folder / "terranx.exe.bak").exists() and _md5(folder / "terranx_original.exe") == gog
    assert "GOG's original) is kept as terranx_original.exe" in capsys.readouterr().out
    assert inst.plan_thinker_setup(folder, _args()) is None          # nothing left to do
    # a second spare under the same name is a duplicate of the kept one: dropped, not renamed
    (folder / "terranx.exe.bak").write_bytes(pristine_bytes)
    assert inst.apply_thinker_setup(inst.plan_thinker_setup(folder, _args())) is False
    assert not (folder / "terranx.exe.bak").exists()
    assert sorted(p.name for p in folder.glob("terranx_original*")) == ["terranx_original.exe"]


def test_a_backup_swapped_after_the_question_is_refused_with_nothing_written(folder, monkeypatch, pristine_bytes):
    """Between the plan and apply the player swaps terranx.exe.bak for something else: the same
    refusal, and the folder is exactly as it was (no copy, no record, no move)."""
    (folder / "terranx.exe.bak").write_bytes(pristine_bytes)
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    (folder / "terranx.exe.bak").write_bytes(b"MZ swapped in")
    before = _tree(folder)
    with pytest.raises(ix.InstallerError) as e:
        inst.apply_thinker_setup(plan)
    assert e.value.red and e.value.changed is False
    assert _tree(folder) == before


def test_a_stopped_set_up_records_the_spare_it_sets_aside(folder, monkeypatch, pristine_bytes):
    """Audit: a set-up that stopped between its two steps (the original already kept, no
    terranx.exe) wrote no record when it set GOG's spare aside, so --uninstall could never name
    it. The spare here is a duplicate of the kept original, so it is dropped; a different GOG copy
    would be recorded -- both paths go through the record now."""
    _unattended(monkeypatch)
    inst.apply_thinker_setup(inst.plan_thinker_setup(folder, _args()))
    (folder / "terranx.exe").unlink()                  # stopped between its two steps
    (folder / "terranx.exe.bak").write_bytes(pristine_bytes)
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["backup"] is None and plan["gog_bak"] is not None
    assert inst.apply_thinker_setup(plan)
    assert not (folder / "terranx.exe.bak").exists() and _md5(folder / "terranx.exe") == BASE
    rec = json.loads((folder / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    assert rec["backup"] == "terranx_original.exe" and not rec.get("set_aside")


def test_a_failed_set_up_puts_a_set_aside_gog_backup_back(folder, monkeypatch, pristine_bytes):
    """All or nothing still holds with the extra move: when the final copy fails, the GOG .bak that
    was set aside is back under its own name, and the record is gone."""
    (folder / "terranx.exe").write_bytes(b"MZ a player's own build")
    (folder / "terranx.exe.bak").write_bytes(pristine_bytes)
    before = _tree(folder)
    _no_question(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    real_replace = os.replace

    def failing_replace(a, b):
        if Path(a).name.endswith(inst._SETUP_TMP):
            raise OSError("disk full")
        return real_replace(a, b)
    monkeypatch.setattr(inst.os, "replace", failing_replace)
    with pytest.raises(ix.InstallerError):
        inst.apply_thinker_setup(plan)
    assert _tree(folder) == before


def test_the_original_back_from_gog_is_set_up_again_without_a_second_backup(set_up, monkeypatch, pristine_bytes, capsys):
    g, vanilla = set_up
    _gog_verified(g, pristine_bytes)
    assert not inst._setup_in_effect(g)
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(g, _args())
    assert plan["action"] == "setup" and plan["vanilla"] and capsys.readouterr().out == ""
    assert inst.apply_thinker_setup(plan)
    assert _md5(g / "terranx.exe") == BASE and _md5(g / "terranx_original.exe") == vanilla
    assert sorted(p.name for p in g.glob("terranx_original*")) == ["terranx_original.exe"]


def test_a_failed_set_up_over_a_kept_duplicate_loses_nothing(set_up, monkeypatch, pristine_bytes):
    """The kept original and the live one are the same file: the live one is replaced, never
    renamed over the kept one -- so a failure leaves both exactly as they were."""
    g, vanilla = set_up
    _gog_verified(g, pristine_bytes)
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(g, _args())
    before = _tree(g)
    real = inst.os.replace

    def flaky(a, b):
        if Path(a).name.endswith(".longevity-tmp"):
            raise PermissionError("locked")
        return real(a, b)
    monkeypatch.setattr(inst.os, "replace", flaky)
    with pytest.raises(ix.InstallerError) as e:
        inst.apply_thinker_setup(plan)
    assert e.value.changed is False and _tree(g) == before


def test_thinker_removed_lets_go_of_the_set_up(set_up, monkeypatch, capsys):
    g, vanilla = set_up
    (g / "thinker.dll").unlink()
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(g, _args())
    assert plan["action"] == "release" and "no longer in this folder" in capsys.readouterr().out
    inst.apply_thinker_setup(plan)
    assert _md5(g / "terranx.exe") == vanilla and not (g / inst.THINKER_SETUP_NAME).exists()


def test_a_record_left_by_a_crash_blocks_nothing(folder, monkeypatch):
    """A record written just before the first rename, Thinker then removed: the plain install sees
    every exe again, and the record is let go."""
    vanilla = _md5(folder / "terranx.exe")
    inst._write_setup(folder, {"exe": "terranx.exe", "backup": "terranx_original.exe",
                               "original_md5": vanilla, "source": "terranx_PRACX.exe"})
    (folder / "thinker.dll").unlink()
    assert {p.name for p in inst._install_candidates(folder)} == {"terranx.exe", "terranx_PRACX.exe"}
    _unattended(monkeypatch)
    inst.apply_thinker_setup(inst.plan_thinker_setup(folder, _args()))
    assert not (folder / inst.THINKER_SETUP_NAME).exists() and _md5(folder / "terranx.exe") == vanilla


def test_undo_with_the_original_already_in_place_only_cleans_up(set_up):
    g, vanilla = set_up
    (g / "terranx.exe").unlink()
    (g / "terranx_original.exe").rename(g / "terranx.exe")          # put back by hand
    assert inst.undo_thinker_setup(g) == 0
    assert _md5(g / "terranx.exe") == vanilla
    assert not (g / "terranx.exe.bak").exists() and not (g / inst.THINKER_SETUP_NAME).exists()


# ---------------------------------------------------------------- re-audit (2026-11-01)

def _older_build(g: Path) -> str:
    """terranx.exe as an EARLIER release's build would look: not the base, not any hash this
    table knows, beside the clean-base .bak the set-up left."""
    data = bytearray((g / "terranx.exe").read_bytes())
    data[0x2000] ^= 0xFF
    (g / "terranx.exe").write_bytes(bytes(data))
    return hashlib.md5(bytes(data)).hexdigest()


def test_an_earlier_releases_build_is_still_ours(set_up, monkeypatch):
    g, vanilla = set_up
    _older_build(g)
    assert inst._setup_in_effect(g)
    _unattended(monkeypatch)
    assert inst.plan_thinker_setup(g, _args()) is None                # nothing to set up again
    assert [p.name for p in inst._install_candidates(g)] == ["terranx.exe"]


def test_reverting_an_earlier_build_puts_the_original_back_and_keeps_its_bytes(set_up):
    g, vanilla = set_up
    old = _older_build(g)
    held = []
    assert inst.revert_thinker_setup(g, held) == 1 and held == []
    assert _md5(g / "terranx.exe") == vanilla
    assert _md5(g / f"terranx.exe.replaced-{old[:8]}") == old
    assert not (g / "terranx.exe.bak").exists() and not (g / inst.THINKER_SETUP_NAME).exists()


def test_a_replaced_terranx_stops_the_whole_install_with_nothing_written(set_up, monkeypatch, capsys):
    """Setting up over an unrecognised exe in a set-up folder would point the record at that exe
    as "the original" and lose the real one (re-audit Y1); installing the plain build beside it is
    not what a Thinker player asked for (user 2026-11-06). So: the red refusal, the user's shape,
    nothing written -- and --uninstall leaves this terranx.exe too, so the text names the file."""
    g, vanilla = set_up
    (g / "terranx.exe.bak").unlink()
    (g / "terranx.exe").write_bytes(b"MZ something else")
    before = _tree(g)
    for console in (False, True):
        if console:
            _no_question(monkeypatch)
        else:
            _unattended(monkeypatch)
        with pytest.raises(ix.InstallerError) as e:
            inst.plan_thinker_setup(g, _args())
        err = e.value
        assert err.message == inst.REPLACED_EXE_TEXT.format(
            name="terranx.exe", was=", and it is not the original that install kept as terranx_original.exe")
        assert err.message == (
            "Your game installation folder was set up for Thinker by an earlier Longevity Vaccine install, but its "
            "terranx.exe is no longer the file that install put there, and it is not the original that install kept "
            "as terranx_original.exe. This should only happen if you replaced that file by hand. Longevity Vaccine "
            "cannot install over it. To install, verify that you do not need the current terranx.exe and delete it, "
            "then re-run this installer. Your game was not modified.")
        assert err.code == ix.EXIT_ABORTED and err.changed is False and err.title == "INSTALLATION FAILED"
        assert err.red and err.any_key and err.disk_note is False and not err.remedy
    assert _tree(g) == before
    assert capsys.readouterr().out == ""
    # the remedy the text gives works: with the file gone, the set-up puts PRACX in place and the
    # record still points at the kept original, which --uninstall puts back
    (g / "terranx.exe").unlink()
    plan = inst.plan_thinker_setup(g, _args())
    assert plan and plan["action"] == "setup" and plan["backup"] is None
    assert inst.apply_thinker_setup(plan)
    assert _md5(g / "terranx.exe") == BASE and "Your original is kept as terranx_original.exe" in capsys.readouterr().out
    assert inst.undo_thinker_setup(g) == 1 and _md5(g / "terranx.exe") == vanilla


def test_the_replaced_exe_refusal_without_the_kept_original_names_no_file(set_up, monkeypatch, capsys):
    g, vanilla = set_up
    (g / "terranx.exe.bak").unlink()
    (g / "terranx.exe").write_bytes(b"MZ something else")
    (g / "terranx_original.exe").unlink()
    _unattended(monkeypatch)
    with pytest.raises(ix.InstallerError) as e:
        inst.plan_thinker_setup(g, _args())
    assert " kept. This should only happen" in e.value.message and "terranx_original" not in e.value.message
    # a kept original that CHANGED is not named either (the name would vouch for it)
    (g / "terranx_original.exe").write_bytes(b"MZ changed since")
    with pytest.raises(ix.InstallerError) as e:
        inst.plan_thinker_setup(g, _args())
    assert "terranx_original" not in e.value.message
    # the remedy with the kept original gone: the set-up's line says gone, not "changed"
    (g / "terranx_original.exe").unlink()
    (g / "terranx.exe").unlink()
    assert inst.apply_thinker_setup(inst.plan_thinker_setup(g, _args()))
    out = capsys.readouterr().out
    assert "(terranx_original.exe, the original it kept, is no longer in the folder)" in out and "has changed" not in out


def test_the_replaced_exe_refusal_for_a_set_up_that_found_no_terranx(folder, monkeypatch):
    """Set up from a folder with no terranx.exe (nothing kept), then one appears by hand: refused,
    and the text does not speak of an original that was never kept."""
    (folder / "terranx.exe").unlink()
    _unattended(monkeypatch)
    assert inst.apply_thinker_setup(inst.plan_thinker_setup(folder, _args()))
    (folder / "terranx.exe").write_bytes(b"MZ a file placed by hand")
    with pytest.raises(ix.InstallerError) as e:
        inst.plan_thinker_setup(folder, _args())
    assert "put there (there was no terranx.exe before it). This should only happen" in e.value.message
    assert "original that install kept" not in e.value.message


def test_the_replaced_exe_is_refused_even_with_no_pracx_copy_to_set_up_from(set_up, monkeypatch):
    """Audit LOW-4: with terranx_PRACX.exe gone too, the loud refusal still wins over the generic
    "nothing to patch" error."""
    g, vanilla = set_up
    (g / "terranx.exe.bak").unlink()
    (g / "terranx_PRACX.exe").unlink()
    (g / "terranx.exe").write_bytes(b"MZ something else")
    _unattended(monkeypatch)
    with pytest.raises(ix.InstallerError) as e:
        inst.plan_thinker_setup(g, _args())
    assert e.value.red and e.value.message.startswith("Your game installation folder was set up for Thinker")


def test_our_build_with_gogs_copy_as_its_backup_is_left_alone(set_up, monkeypatch, pristine_bytes):
    """Audit HIGH-1: terranx.exe a build of ours, its .bak GOG's original, no clean base under the
    name: the "aside" shape used to move the .bak and then the pass found nothing to patch -- a
    write before an error that said nothing was changed. Now nothing is planned."""
    g, vanilla = set_up
    old = _older_build(g)
    ov = inst._thinker_overlay()
    monkeypatch.setattr(ov, "known_patched", list(ov.known_patched) + [old])
    (g / "terranx.exe.bak").write_bytes(pristine_bytes)
    _unattended(monkeypatch)
    before = _tree(g)
    assert inst.plan_thinker_setup(g, _args()) is None
    assert inst.plan_backups(g, inst._install_candidates(g), None) == []
    assert _tree(g) == before


def test_thinker_removed_still_checks_the_backup_first(set_up, monkeypatch, pristine_bytes, bak_path, capsys):
    """Audit HIGH-2: the revert can leave terranx.exe a clean PRACX copy that the pass patches, so
    its .bak follows the rule too: a foreign one is refused before the revert; GOG's copy is set
    aside after it (plan_backups on the folder as the revert left it)."""
    g, vanilla = set_up
    (g / "thinker.dll").unlink()
    (g / "terranx.exe.bak").write_bytes(b"MZ another tool's backup")
    _unattended(monkeypatch)
    before = _tree(g)
    with pytest.raises(ix.InstallerError) as e:
        inst.plan_thinker_setup(g, _args())
    assert "unrecognized terranx.exe.bak" in e.value.message and _tree(g) == before
    assert "--- Thinker ---" not in capsys.readouterr().out
    (g / "terranx.exe.bak").write_bytes(pristine_bytes)
    plan = inst.plan_thinker_setup(g, _args())
    assert plan["action"] == "release" and _tree(g) != before and _tree(g) == {**before, "terranx.exe.bak": _md5(g / "terranx.exe.bak")}


def test_the_original_put_back_by_hand_is_not_a_replaced_exe(set_up, monkeypatch):
    """The kept original copied back over terranx.exe by hand (or by GOG) is restored_by_gog: set
    up again without a second backup, never refused."""
    g, vanilla = set_up
    (g / "terranx.exe.bak").unlink()
    shutil.copy2(g / "terranx_original.exe", g / "terranx.exe")
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(g, _args())
    assert plan and plan["action"] == "setup"
    assert inst.apply_thinker_setup(plan) and _md5(g / "terranx.exe") == BASE
    assert sorted(p.name for p in g.glob("terranx_original*")) == ["terranx_original.exe"]


# ---------------------------------------------------------------- the backup rule's "ours" kind (2026-11-06)

def _a_build_of_ours(monkeypatch, data: bytes) -> str:
    """Make `data`'s hash a build this project made from the PRACX base (an earlier release's)."""
    md5 = hashlib.md5(data).hexdigest()
    ov = inst._thinker_overlay()
    monkeypatch.setattr(ov, "known_patched", list(ov.known_patched) + [md5])
    return md5


def test_our_build_as_the_backup_is_dropped_beside_a_clean_terranx(folder, monkeypatch, bak_path, capsys):
    """The rule's third kind: a terranx.exe.bak that is a build of ours is not foreign -- it is
    dropped (remade from the clean base by the pass), so the pass can write its own backup."""
    shutil.copy2(bak_path, folder / "terranx.exe")
    (folder / "terranx.exe.bak").write_bytes(b"MZ an earlier release's build")
    _a_build_of_ours(monkeypatch, b"MZ an earlier release's build")
    _unattended(monkeypatch)
    before = _tree(folder)
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["action"] == "aside" and plan["gog_bak"] is None and plan["drop_bak"].name == "terranx.exe.bak"
    assert _tree(folder) == before                                     # the plan writes nothing
    assert inst.apply_thinker_setup(plan) is False
    assert not (folder / "terranx.exe.bak").exists() and _md5(folder / "terranx.exe") == BASE
    assert "terranx.exe.bak (a Longevity Vaccine build) was removed" in capsys.readouterr().out
    assert not list(folder.glob("terranx_original*")) and not list(folder.glob("*.replaced-*"))


def test_our_build_as_the_backup_is_dropped_before_a_set_up(folder, monkeypatch, capsys):
    """The stock folder with such a .bak: the set-up drops it first, then swaps as usual; the
    record is the ordinary one."""
    (folder / "terranx.exe.bak").write_bytes(b"MZ an earlier release's build")
    _a_build_of_ours(monkeypatch, b"MZ an earlier release's build")
    vanilla = _md5(folder / "terranx.exe")
    _no_question(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan["action"] == "setup" and plan["drop_bak"] is not None and plan["gog_bak"] is None
    assert inst.apply_thinker_setup(plan)
    assert not (folder / "terranx.exe.bak").exists()
    assert _md5(folder / "terranx.exe") == BASE and _md5(folder / "terranx_original.exe") == vanilla
    rec = json.loads((folder / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    assert rec["backup"] == "terranx_original.exe" and not rec.get("set_aside")
    out = capsys.readouterr().out
    assert "(a Longevity Vaccine build) was removed" in out and "Swapped the vanilla" in out


def test_our_build_over_our_build_is_left_alone(set_up, monkeypatch):
    """terranx.exe a build of ours, its .bak another build of ours: no clean base anywhere under
    that name, nothing the pass can patch -- the .bak stays (dropping it would be a write before
    an error)."""
    g, vanilla = set_up
    old = _older_build(g)
    ov = inst._thinker_overlay()
    monkeypatch.setattr(ov, "known_patched", list(ov.known_patched) + [old])
    shutil.copy2(g / "terranx.exe", g / "terranx.exe.bak")
    _unattended(monkeypatch)
    before = _tree(g)
    assert inst.plan_thinker_setup(g, _args()) is None
    assert _tree(g) == before


def test_a_build_of_ours_swapped_for_something_else_after_the_plan_is_refused(folder, monkeypatch, bak_path):
    shutil.copy2(bak_path, folder / "terranx.exe")
    (folder / "terranx.exe.bak").write_bytes(b"MZ an earlier release's build")
    _a_build_of_ours(monkeypatch, b"MZ an earlier release's build")
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(folder, _args())
    (folder / "terranx.exe.bak").write_bytes(b"MZ swapped in")
    before = _tree(folder)
    with pytest.raises(ix.InstallerError) as e:
        inst.apply_thinker_setup(plan)
    assert e.value.red and e.value.changed is False and _tree(folder) == before
    # the clean base back under the name is fine: nothing to drop
    shutil.copy2(bak_path, folder / "terranx.exe.bak")
    assert inst.apply_thinker_setup(plan) is False and (folder / "terranx.exe.bak").exists()


def test_our_backup_never_outlives_the_record(set_up, bak_path):
    """With no other clean PRACX copy, our terranx.exe.bak is the folder's only one: it is kept
    under a plain PRACX name, never left as a .bak beside the original -- which a later uninstall's
    generic restore would copy over it (re-audit P1)."""
    g, vanilla = set_up
    (g / "terranx_PRACX.exe").write_bytes(b"MZ not a clean PRACX")
    assert inst.undo_thinker_setup(g) == 1
    assert _md5(g / "terranx.exe") == vanilla and not (g / "terranx.exe.bak").exists()
    kept = [p for p in g.glob("terranx_PRACX*.exe") if _md5(p) == BASE]
    assert kept, "the only clean PRACX copy was lost"


# ---------------------------------------------------------------- third round (2026-11-01)

def test_gogs_stock_exe_is_never_taken_for_our_build(tmp_path, bak_path, pristine_bytes, monkeypatch):
    """Set up a folder that had NO terranx.exe; GOG's verify then writes its stock one: that is
    the original now, not a build of ours -- the next run sets up again keeping it, and the
    uninstall puts it back (audit 3 #2: it was re-patched over and the uninstall left none)."""
    g = tmp_path / "g"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "thinker.dll").write_bytes(b"dll")
    _unattended(monkeypatch)
    assert inst.apply_thinker_setup(inst.plan_thinker_setup(g, _args()))
    shutil.copy2(bak_path, g / "terranx.exe.bak")                   # as the patch pass leaves it
    (g / "terranx.exe").write_bytes(pristine_bytes)                  # GOG's verify
    vanilla = _md5(g / "terranx.exe")
    assert not inst._ours_in_setup(g, inst._thinker_overlay()) and not inst._setup_in_effect(g)
    plan = inst.plan_thinker_setup(g, _args())
    assert plan["action"] == "setup" and not plan["keep_record"]
    assert inst.apply_thinker_setup(plan)
    assert json.loads((g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))["original_md5"] == vanilla
    assert inst.revert_thinker_setup(g) == 1 and _md5(g / "terranx.exe") == vanilla


def test_gogs_stock_exe_over_a_custom_original_keeps_the_true_original(set_up, monkeypatch, pristine_bytes, bak_path, capsys):
    g, _ = set_up
    rec = json.loads((g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    (g / "terranx_original.exe").write_bytes(b"MZ the player's own original")
    rec["original_md5"] = _md5(g / "terranx_original.exe")
    inst._write_setup(g, rec)
    (g / "terranx.exe").write_bytes(pristine_bytes)                  # GOG's verify, stock
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(g, _args())
    assert plan["keep_record"]
    inst.apply_thinker_setup(plan)
    now = json.loads((g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    aside = now.pop("set_aside")
    assert now == rec and len(aside) == 1 and (g / aside[0]).read_bytes() == pristine_bytes
    # the one line for this shape names both kept files and promises the right one back
    assert (f"Your earlier terranx.exe is still kept as terranx_original.exe, and GOG's copy as {aside[0]}. "
            "Uninstalling Longevity Vaccine puts your earlier terranx.exe back.") in capsys.readouterr().out
    assert (g / "terranx_original.exe").read_bytes() == b"MZ the player's own original"
    # ... and the uninstall puts the player's own back and names GOG's copy (audit 4 #4)
    shutil.copy2(bak_path, g / "terranx.exe.bak")
    assert inst.revert_thinker_setup(g) == 1
    assert (g / "terranx.exe").read_bytes() == b"MZ the player's own original"


def test_with_the_kept_original_gone_the_set_aside_stock_copy_goes_back(set_up, monkeypatch, pristine_bytes, bak_path):
    """GOG's stock copy set aside by a keep-record set-up IS an original at hand: when the player's
    own kept one disappears, the uninstall puts the stock copy back instead of leaving PRACX there
    (audit 5 #2)."""
    g, _ = set_up
    rec = json.loads((g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    (g / "terranx_original.exe").write_bytes(b"MZ the player's own original")
    rec["original_md5"] = _md5(g / "terranx_original.exe")
    inst._write_setup(g, rec)
    (g / "terranx.exe").write_bytes(pristine_bytes)
    _unattended(monkeypatch)
    inst.apply_thinker_setup(inst.plan_thinker_setup(g, _args()))
    (g / "terranx_original.exe").unlink()
    shutil.copy2(bak_path, g / "terranx.exe.bak")
    assert inst.revert_thinker_setup(g) == 1
    assert (g / "terranx.exe").read_bytes() == pristine_bytes
    assert not (g / "terranx.exe.bak").exists() and not (g / inst.THINKER_SETUP_NAME).exists()


def test_gogs_stock_exe_straight_over_a_custom_original_puts_the_custom_one_back(set_up, pristine_bytes, capsys):
    """No re-run in between: the uninstall finds GOG's stock exe in place while the player's own
    original is still kept -- the player's own goes back, the stock copy is set aside (audit 4 #2)."""
    g, _ = set_up
    rec = json.loads((g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    (g / "terranx_original.exe").write_bytes(b"MZ the player's own original")
    rec["original_md5"] = _md5(g / "terranx_original.exe")
    inst._write_setup(g, rec)
    (g / "terranx.exe").write_bytes(pristine_bytes)
    assert inst.undo_thinker_setup(g) == 1
    assert (g / "terranx.exe").read_bytes() == b"MZ the player's own original"
    stock = hashlib.md5(pristine_bytes).hexdigest()
    assert (g / f"terranx.exe.replaced-{stock[:8]}").read_bytes() == pristine_bytes
    assert "GOG's copy of terranx.exe is kept as" in capsys.readouterr().out


def test_with_the_custom_original_gone_gogs_stock_exe_becomes_the_original(set_up, monkeypatch, pristine_bytes):
    """The record must never point at a kept file that is now GOG's stock copy under the player's
    original's name (audit 4 #3)."""
    g, _ = set_up
    rec = json.loads((g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    rec["original_md5"] = "0" * 32                                  # a custom original ...
    inst._write_setup(g, rec)
    (g / "terranx_original.exe").unlink()                           # ... since deleted
    (g / "terranx.exe").write_bytes(pristine_bytes)
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(g, _args())
    assert not plan["keep_record"]
    inst.apply_thinker_setup(plan)
    now = json.loads((g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8"))
    assert now["original_md5"] == hashlib.md5(pristine_bytes).hexdigest()
    assert _md5(g / now["backup"]) == now["original_md5"]


def test_a_missing_exe_is_not_called_a_clean_copy(set_up, capsys):
    g, _ = set_up
    (g / "terranx.exe").unlink()
    (g / "terranx_original.exe").unlink()
    inst.undo_thinker_setup(g)
    out = capsys.readouterr().out
    assert "there is no terranx.exe in the folder now" in out and "stays a clean PRACX copy" not in out


def test_a_replaced_exe_is_refused_not_installed_for_plain_pracx(set_up, monkeypatch, capsys):
    """Until 2026-11-06 this shape printed "Thinker will not load it" and went on to install the
    plain build: the user asked for a loud refusal instead."""
    g, _ = set_up
    (g / "terranx.exe.bak").unlink()
    (g / "terranx.exe").write_bytes(b"MZ something else")
    _unattended(monkeypatch)
    with pytest.raises(ix.InstallerError) as e:
        inst.plan_thinker_setup(g, _args())
    assert e.value.red and "Thinker will not load" not in capsys.readouterr().out


def test_an_earlier_release_recorded_in_the_history_comes_back_without_its_bak(set_up, monkeypatch):
    """A build the target's known_patched records is ours BY ITS HASH: with its .bak gone it is
    restored from the folder's other clean PRACX copy, and no .replaced copy of our own bytes is
    kept (audit 2026-11-01: the Thinker side's use of the history was untested)."""
    g, vanilla = set_up
    old = _older_build(g)
    ov = inst._thinker_overlay()
    monkeypatch.setattr(ov, "known_patched", list(ov.known_patched) + [old])
    assert old in inst._our_builds(ov)
    (g / "terranx.exe.bak").unlink()
    assert inst.revert_thinker_setup(g) == 1
    assert _md5(g / "terranx.exe") == vanilla
    assert not list(g.glob("*.replaced-*")) and not (g / inst.THINKER_SETUP_NAME).exists()


def test_a_stock_thinker_folder_is_labelled_for_thinker(folder):
    status, label = inst.check_game_folder(folder)
    assert status == inst.FOLDER_OK and "Thinker" in label
