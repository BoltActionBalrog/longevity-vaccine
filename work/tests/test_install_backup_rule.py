"""The one backup rule for every exe the install pass patches (install.plan_backups /
apply_backup_plan; user 2026-11-06, the generalisation of the Thinker folder's terranx.exe.bak
check): <exe>.bak absent or the clean base -> fine; GOG's original -> set aside under an
_original name (or dropped as a duplicate); a build of ours -> dropped; anything else -> the red
refusal before any write. The pass keeps whatever sits under <exe>.bak, so without this a foreign
.bak was patched over and left a build no later run could recognise and no --uninstall restore.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst        # noqa: E402
import installer_exit as ix   # noqa: E402

inst._load_modules()          # config / receipt / version, as main() loads them


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): _md5(p) for p in sorted(root.rglob("*")) if p.is_file()}


def _args(**kw):
    return types.SimpleNamespace(**{"no_prompt": False, **kw})


@pytest.fixture
def plain(tmp_path, bak_path, pristine_bytes):
    """The common GOG layout, no Thinker: the stock terranx.exe beside the clean PRACX build."""
    g = tmp_path / "game"
    g.mkdir()
    (g / "terranx.exe").write_bytes(pristine_bytes)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    return g


def _plan(g: Path, thinker_plan=None) -> list:
    return inst.plan_backups(g, inst._install_candidates(g), thinker_plan)


def _ours(monkeypatch, data: bytes) -> str:
    md5 = hashlib.md5(data).hexdigest()
    ov = inst._thinker_overlay()
    monkeypatch.setattr(ov, "known_patched", list(ov.known_patched) + [md5])
    return md5


# ---------------------------------------------------------------- the plan

def test_no_backup_and_a_clean_one_are_nothing_to_do(plain, bak_path):
    assert _plan(plain) == []
    shutil.copy2(bak_path, plain / "terranx_PRACX.exe.bak")
    assert _plan(plain) == []


def test_a_foreign_backup_beside_an_exe_the_pass_patches_is_refused_before_any_write(plain, capsys):
    (plain / "terranx_PRACX.exe.bak").write_bytes(b"MZ another tool's backup")
    before = _tree(plain)
    with pytest.raises(ix.InstallerError) as e:
        _plan(plain)
    err = e.value
    assert err.message == inst.FOREIGN_BACKUP_TEXT.format(name="terranx_PRACX.exe.bak")
    assert "unrecognized terranx_PRACX.exe.bak file" in err.message and "Your game was not modified." in err.message
    assert err.code == ix.EXIT_ABORTED and err.changed is False and err.title == "INSTALLATION FAILED"
    assert err.red and err.any_key and err.disk_note is False and not err.remedy
    assert _tree(plain) == before and capsys.readouterr().out == ""


def test_a_backup_beside_an_exe_the_pass_does_not_touch_is_nobodys_business(plain):
    """The stock terranx.exe is not a clean shipping base: the pass never writes it, never backs
    it up -- whatever sits under terranx.exe.bak beside it is left alone, refused or not."""
    (plain / "terranx.exe.bak").write_bytes(b"MZ another tool's backup")
    assert _plan(plain) == []


def test_gogs_original_as_the_backup_is_a_duplicate_of_the_stock_exe_and_is_dropped(plain, pristine_bytes, capsys):
    (plain / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    plan = _plan(plain)
    assert [(i["bak"].name, i["kind"], i["aside_to"]) for i in plan] == [("terranx_PRACX.exe.bak", "gog", None)]
    assert inst.apply_backup_plan(plan) == []
    assert not (plain / "terranx_PRACX.exe.bak").exists() and _md5(plain / "terranx.exe") == hashlib.md5(pristine_bytes).hexdigest()
    assert capsys.readouterr().out == "", "a dropped duplicate is accepted without a word"


def test_gogs_original_as_the_backup_with_no_other_copy_is_kept_under_the_original_name(plain, pristine_bytes, capsys):
    (plain / "terranx.exe").unlink()
    (plain / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    gog = hashlib.md5(pristine_bytes).hexdigest()
    plan = _plan(plain)
    assert plan[0]["aside_to"].name == "terranx_original.exe"
    moves = inst.apply_backup_plan(plan)
    assert moves == [(plain / "terranx_original.exe", plain / "terranx_PRACX.exe.bak")]
    assert _md5(plain / "terranx_original.exe") == gog and not (plain / "terranx_PRACX.exe.bak").exists()
    out = capsys.readouterr().out
    assert "--- terranx_PRACX.exe.bak ---" in out
    assert "terranx_PRACX.exe.bak (GOG's original) is kept as terranx_original.exe (delete it if you do not need it)" in out
    # a second such spare is a duplicate of the kept copy: dropped
    (plain / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    assert inst.apply_backup_plan(_plan(plain)) == [] and not (plain / "terranx_PRACX.exe.bak").exists()
    assert sorted(p.name for p in plain.glob("terranx_original*")) == ["terranx_original.exe"]


def test_two_gog_spares_planned_to_one_name_keep_one_copy(plain, pristine_bytes, bak_path, monkeypatch):
    """Both exes the pass patches carry GOG's original as their .bak: the plan names the same
    _original file for both (free at plan time); at apply the second finds the first there and is
    a duplicate -- dropped, not an error."""
    (plain / "terranx.exe").unlink()
    (plain / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    shutil.copy2(bak_path, plain / "terranx_two.exe")
    (plain / "terranx_two.exe.bak").write_bytes(pristine_bytes)
    monkeypatch.setattr(inst, "_exe_names", lambda: ["terranx.exe", "terranx_PRACX.exe", "terranx_two.exe"])
    plan = _plan(plain)
    assert [i["aside_to"].name for i in plan] == ["terranx_original.exe", "terranx_original.exe"]
    moves = inst.apply_backup_plan(plan)
    assert [m[1].name for m in moves] == ["terranx_PRACX.exe.bak"]
    assert not (plain / "terranx_PRACX.exe.bak").exists() and not (plain / "terranx_two.exe.bak").exists()
    assert sorted(p.name for p in plain.glob("terranx_original*")) == ["terranx_original.exe"]


def test_a_taken_original_name_gives_way_to_a_hashed_one(plain, pristine_bytes):
    (plain / "terranx.exe").unlink()
    (plain / "terranx_original.exe").write_bytes(b"MZ somebody's file under that name")
    (plain / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    gog = hashlib.md5(pristine_bytes).hexdigest()
    plan = _plan(plain)
    assert plan[0]["aside_to"].name == f"terranx_original-{gog[:8]}.exe"
    inst.apply_backup_plan(plan)
    assert _md5(plain / f"terranx_original-{gog[:8]}.exe") == gog
    assert (plain / "terranx_original.exe").read_bytes() == b"MZ somebody's file under that name"


def test_our_build_as_the_backup_is_dropped(plain, monkeypatch, capsys):
    (plain / "terranx_PRACX.exe.bak").write_bytes(b"MZ an earlier release's build")
    _ours(monkeypatch, b"MZ an earlier release's build")
    plan = _plan(plain)
    assert plan[0]["kind"] == "ours" and plan[0]["aside_to"] is None
    assert inst.apply_backup_plan(plan) == []
    assert not (plain / "terranx_PRACX.exe.bak").exists() and not list(plain.glob("*.replaced-*"))
    assert "terranx_PRACX.exe.bak (a Longevity Vaccine build) was removed; the installer writes a fresh backup" \
        in capsys.readouterr().out


# ---------------------------------------------------------------- the Thinker folder

def test_in_a_thinker_folder_the_exe_thinker_starts_is_the_set_ups_business(plain, pristine_bytes):
    """plan_thinker_setup applies the rule to terranx.exe (with the record); after a set-up only
    that exe is patched, so nothing else is checked; without one, the other exe still is."""
    (plain / "thinker.dll").write_bytes(b"dll")
    (plain / "thinker.exe").write_bytes(b"exe")
    (plain / "terranx_PRACX.exe.bak").write_bytes(b"MZ another tool's backup")
    setup = inst.plan_thinker_setup(plain, _args())
    assert setup["action"] == "setup"
    assert inst.plan_backups(plain, inst._install_candidates(plain), setup) == []
    # the "aside" shape: terranx.exe already PRACX (no record), both exes are patched -> checked
    shutil.copy2(plain / "terranx_PRACX.exe", plain / "terranx.exe")
    (plain / "terranx.exe.bak").write_bytes(pristine_bytes)
    aside = inst.plan_thinker_setup(plain, _args())
    assert aside["action"] == "aside"
    with pytest.raises(ix.InstallerError) as e:
        inst.plan_backups(plain, inst._install_candidates(plain), aside)
    assert "terranx_PRACX.exe.bak" in e.value.message
    (plain / "terranx_PRACX.exe.bak").unlink()
    assert inst.plan_backups(plain, inst._install_candidates(plain), aside) == []   # terranx.exe.bak: the plan's


# ---------------------------------------------------------------- apply: all or nothing

def test_a_backup_swapped_after_the_plan_is_refused_before_anything_is_dropped(plain, pristine_bytes, bak_path, monkeypatch):
    """Audit MEDIUM-3: a dropped duplicate cannot be undone, so every planned .bak is hashed again
    BEFORE the first drop (recheck_planned_backups); apply's own re-check undoes moves."""
    (plain / "terranx.exe").unlink()
    (plain / "terranx_PRACX.exe.bak").write_bytes(b"MZ an earlier release's build")      # a drop, planned first
    _ours(monkeypatch, b"MZ an earlier release's build")
    shutil.copy2(bak_path, plain / "terranx_two.exe")
    (plain / "terranx_two.exe.bak").write_bytes(pristine_bytes)                         # a move
    shutil.copy2(bak_path, plain / "terranx_three.exe")
    (plain / "terranx_three.exe.bak").write_bytes(pristine_bytes)                       # swapped below
    monkeypatch.setattr(inst, "_exe_names", lambda: ["terranx.exe", "terranx_PRACX.exe", "terranx_two.exe", "terranx_three.exe"])
    plan = _plan(plain)
    assert [i["kind"] for i in plan] == ["ours", "gog", "gog"]
    (plain / "terranx_three.exe.bak").write_bytes(b"MZ swapped in")
    before = _tree(plain)
    with pytest.raises(ix.InstallerError) as e:
        inst.recheck_planned_backups(plan, None)
    assert e.value.red and e.value.changed is False and _tree(plain) == before, "nothing dropped, nothing moved"
    # apply's own re-check (the brace to that belt): the move is undone; the drop before it is
    # the one thing it cannot give back -- which is why the recheck comes first
    with pytest.raises(ix.InstallerError):
        inst.apply_backup_plan(plan)
    after = _tree(plain)
    assert "terranx_two.exe.bak" in after and "terranx_original.exe" not in after
    # the clean base swapped in instead is fine
    shutil.copy2(bak_path, plain / "terranx_three.exe.bak")
    inst.recheck_planned_backups(plan, None)
    moves = inst.apply_backup_plan(plan)
    assert [m[1].name for m in moves] == ["terranx_two.exe.bak"] and _md5(plain / "terranx_three.exe.bak") == _md5(bak_path)


def test_the_thinker_plans_spares_are_rechecked_before_the_first_drop(plain, pristine_bytes, bak_path, monkeypatch):
    (plain / "thinker.dll").write_bytes(b"dll")
    (plain / "thinker.exe").write_bytes(b"exe")
    (plain / "terranx.exe.bak").write_bytes(pristine_bytes)                       # the set-up's gog_bak
    (plain / "terranx_PRACX.exe.bak").write_bytes(b"MZ an earlier release's build")   # left out after a set-up...
    _ours(monkeypatch, b"MZ an earlier release's build")
    setup = inst.plan_thinker_setup(plain, _args())
    assert setup["action"] == "setup" and setup["gog_bak"] is not None
    plan = inst.plan_backups(plain, inst._install_candidates(plain), setup)
    assert plan == []
    (plain / "terranx.exe.bak").write_bytes(b"MZ swapped in")
    before = _tree(plain)
    with pytest.raises(ix.InstallerError) as e:
        inst.recheck_planned_backups(plan, setup)
    assert e.value.red and _tree(plain) == before
    shutil.copy2(bak_path, plain / "terranx.exe.bak")
    inst.recheck_planned_backups(plan, setup)                                   # the clean base: fine


def test_two_original_names_taken_is_said_at_plan_time(plain, pristine_bytes):
    """Audit LOW-7: the clash is found with nothing written, not at apply after the questions."""
    (plain / "terranx.exe").unlink()
    (plain / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    gog = hashlib.md5(pristine_bytes).hexdigest()
    (plain / "terranx_original.exe").write_bytes(b"MZ one")
    (plain / f"terranx_original-{gog[:8]}.exe").write_bytes(b"MZ two")
    before = _tree(plain)
    with pytest.raises(ix.InstallerError) as e:
        _plan(plain)
    assert e.value.changed is False and "could not be moved out of the way" in e.value.message and _tree(plain) == before


def test_a_failed_move_undoes_the_earlier_ones(plain, pristine_bytes, bak_path, monkeypatch):
    (plain / "terranx.exe").unlink()
    (plain / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    shutil.copy2(bak_path, plain / "terranx_two.exe")
    (plain / "terranx_two.exe.bak").write_bytes(b"MZ an earlier release's build")
    _ours(monkeypatch, b"MZ an earlier release's build")
    monkeypatch.setattr(inst, "_exe_names", lambda: ["terranx.exe", "terranx_PRACX.exe", "terranx_two.exe"])
    plan = _plan(plain)
    before = _tree(plain)
    real_unlink = Path.unlink

    def failing_unlink(self, *a, **k):
        if self.name == "terranx_two.exe.bak":
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(ix.InstallerError) as e:
        inst.apply_backup_plan(plan)
    assert e.value.changed is False and "could not be moved out of the way" in e.value.message
    assert _tree(plain) == before


def test_a_set_up_that_fails_after_the_moves_puts_them_back(plain, pristine_bytes, monkeypatch, bak_path):
    """_install: the spares move first, then the Thinker set-up; a set-up that fails leaves the
    folder as it found it, moved backups included."""
    (plain / "terranx.exe").unlink()
    (plain / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    before = _tree(plain)
    seen = {}

    def failing_setup(plan):
        seen["moved"] = (plain / "terranx_original.exe").is_file() and not (plain / "terranx_PRACX.exe.bak").exists()
        raise ix.InstallerError("The folder could not be set up for Thinker.", code=ix.EXIT_ABORTED, changed=False)
    monkeypatch.setattr(inst, "plan_thinker_setup", lambda g, a: {"action": "aside", "ov": inst._thinker_overlay()})
    monkeypatch.setattr(inst, "apply_thinker_setup", failing_setup)
    monkeypatch.setattr(inst, "module_catalogue", lambda g, a: ([], None))
    monkeypatch.setattr(inst, "pick_modules", lambda c, a, g: ([], [], []))
    with pytest.raises(ix.InstallerError):
        inst._install(plain, _args(ai="off", modules=None, force=False))
    assert seen == {"moved": True} and _tree(plain) == before
