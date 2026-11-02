"""Setting a Thinker folder up: plan (asks, writes nothing), apply (all or nothing), undo (the
uninstall puts the original back, and never destroys a file it did not put there). The full
install / re-run / uninstall cycle runs end to end in test_install_e2e; this covers the questions
and every failure and edge case, in process, on throwaway folders."""
from __future__ import annotations

import hashlib
import json
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

def test_enter_sets_a_stock_folder_up_and_the_plan_writes_nothing(folder, monkeypatch, capsys):
    before = _tree(folder)
    _console(monkeypatch, "")
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["backup"].name == "terranx_original.exe" and plan["src"].name == "terranx_PRACX.exe"
    assert _tree(folder) == before
    out = capsys.readouterr().out
    assert "original game without PRACX" in out and "--uninstall puts the original back" in out


def test_no_leaves_the_folder_as_it_is(folder, monkeypatch, capsys):
    _console(monkeypatch, "n")
    assert inst.plan_thinker_setup(folder, _args()) is None
    assert "Left as it is" in capsys.readouterr().out


def test_an_unrecognised_terranx_defaults_to_no(folder, monkeypatch, capsys):
    (folder / "terranx.exe").write_bytes(b"MZ something else")
    _console(monkeypatch, "")
    assert inst.plan_thinker_setup(folder, _args()) is None
    assert "does not recognise" in capsys.readouterr().out
    _console(monkeypatch, "y")
    plan = inst.plan_thinker_setup(folder, _args())
    assert plan and plan["md5"] == _md5(folder / "terranx.exe")


def test_unattended_sets_up_a_stock_folder_but_never_an_unrecognised_one(folder, monkeypatch, capsys):
    _unattended(monkeypatch)
    assert inst.plan_thinker_setup(folder, _args())
    (folder / "terranx.exe").write_bytes(b"MZ something else")
    assert inst.plan_thinker_setup(folder, _args()) is None
    assert "not one the installer recognises" in capsys.readouterr().out


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


def test_a_foreign_terranx_backup_is_never_set_up_over(folder, monkeypatch, capsys):
    _unattended(monkeypatch)
    (folder / "terranx.exe.bak").write_bytes(b"another tool's backup")
    assert inst.plan_thinker_setup(folder, _args()) is None
    assert "did not make" in capsys.readouterr().out


def test_the_original_back_from_gog_is_set_up_again_without_a_second_backup(set_up, monkeypatch, pristine_bytes, capsys):
    g, vanilla = set_up
    _gog_verified(g, pristine_bytes)
    assert not inst._setup_in_effect(g)
    _unattended(monkeypatch)
    plan = inst.plan_thinker_setup(g, _args())
    assert plan["action"] == "setup" and "GOG may have restored it" in capsys.readouterr().out
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


def test_no_in_a_folder_gog_restored_lets_go_of_the_set_up(set_up, monkeypatch, pristine_bytes):
    """Declining the set-up again must not leave a record and our PRACX .bak behind, or the plain
    install that follows swaps the original out anyway (audit: "Left as it is" was untrue)."""
    g, vanilla = set_up
    _gog_verified(g, pristine_bytes)
    _console(monkeypatch, "n")
    plan = inst.plan_thinker_setup(g, _args())
    assert plan == {"action": "release", "game_dir": g}
    assert inst.apply_thinker_setup(plan) is False
    assert _md5(g / "terranx.exe") == vanilla
    assert not (g / "terranx.exe.bak").exists() and not (g / "terranx_original.exe").exists()
    assert not (g / inst.THINKER_SETUP_NAME).exists()
    assert {p.name for p in inst._install_candidates(g)} == {"terranx.exe", "terranx_PRACX.exe"}


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


def test_a_replaced_terranx_never_rewrites_the_record(set_up, monkeypatch, capsys):
    """Saying yes to setting up over an unrecognised exe in a set-up folder would point the record
    at that exe as "the original" and lose the real one (re-audit Y1)."""
    g, vanilla = set_up
    (g / "terranx.exe.bak").unlink()
    (g / "terranx.exe").write_bytes(b"MZ something else")
    rec = (g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8")
    _console(monkeypatch, "y")
    assert inst.plan_thinker_setup(g, _args()) is None
    assert "the original is still terranx_original.exe" in capsys.readouterr().out
    assert (g / inst.THINKER_SETUP_NAME).read_text(encoding="utf-8") == rec


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


def test_gogs_stock_exe_over_a_custom_original_keeps_the_true_original(set_up, monkeypatch, pristine_bytes, bak_path):
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


def test_a_replaced_exe_says_thinker_will_not_load_the_mod(set_up, monkeypatch, capsys):
    g, _ = set_up
    (g / "terranx.exe.bak").unlink()
    (g / "terranx.exe").write_bytes(b"MZ something else")
    _unattended(monkeypatch)
    assert inst.plan_thinker_setup(g, _args()) is None
    assert "Thinker will not load it" in capsys.readouterr().out


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
