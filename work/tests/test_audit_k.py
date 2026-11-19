"""The tenth verification (audit-k, of 853886c..62543f6, 2026-11-16): one regression per LOW finding, each written to
fail first. Synthetic Thinker files stand in for the pinned release (conftest's synthetic_pin)."""
from __future__ import annotations

import json
import re
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
import thinker_flow as tf           # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
from test_thinker_update import KNOWN, NEW, OLD, V54, _folder  # noqa: E402
from test_uninstall_thinker_packs import _installed_thinker  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")


def _record(game: Path) -> dict:
    return json.loads((game / tf.INSTALL_RECORD).read_text(encoding="utf-8"))


def lv_in_place(game: Path) -> None:
    """What makes a folder one Longevity Vaccine is installed in: uimod.dll, and an exe that is not its .bak."""
    (game / "uimod.dll").write_bytes(b"uimod")
    (game / "terranx.exe").write_bytes(b"MZ patched by Longevity Vaccine")
    (game / "terranx.exe.bak").write_bytes(b"MZ the player's original")


# ---------------------------------------------------------------- LOW-3: no temp file left beside the ini

def test_a_failed_ini_rewrite_leaves_no_temp_file(tmp_path, monkeypatch):
    game = tmp_path / "game"
    ini = Path(inst._ini_path_str(game))
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_bytes(b"[Alpha Centauri]\r\nx=1\r\n[Longevity]\r\n\r\n")

    def refused(src, dst):
        raise PermissionError(5, "Access is denied")              # R04: a read-only Alpha Centauri.ini
    monkeypatch.setattr(inst.os, "replace", refused)
    assert inst.drop_empty_ini_section(game, "Longevity") is False
    assert not any(p.name.endswith(".longevity-tmp") for p in ini.parent.iterdir())


# ---------------------------------------------------------------- LOW-4: the gate covers every e2e prerequisite

E2E_FILES = ("test_install_e2e.py", "test_archive_e2e.py", "test_release.py", "test_runtime38.py", "test_targets.py",
             "test_installer_exit.py", "test_dev_player_zip.py")
PREREQ = re.compile(r"runtime|uimod\.dll|ffmpeg|interpreter|python38|PY38|_STAGED", re.I)


def test_no_e2e_prerequisite_skips_around_the_gate():
    hits = []
    for name in E2E_FILES:
        for n, line in enumerate((_TESTS / name).read_text(encoding="utf-8").splitlines(), 1):
            if ("pytest.skip(" in line or "skipif(" in line) and PREREQ.search(line):
                hits.append(f"{name}:{n}: {line.strip()}")
    assert hits == [], hits


# ---------------------------------------------------------------- LOW-5: the set holds the player's original text

def stock_help() -> bytes:
    """A help text with every stock block patch_helptext replaces: what Thinker 5.4 ships, as far as the patch sees."""
    import patch_helptext as ph
    return b"; Thinker Mod 5.4 helpx\r\n" + b"".join(tag + b"\r\n" + b"\r\n".join(lines) + b"\r\n"
                                                  for tag, lines in ph.HELPX_STOCK.items())


def patched_help() -> bytes:
    import patch_helptext as ph
    return ph.patch_bytes(stock_help(), ph.FILES["helpx.txt"])


def _update_over_patched_help(tmp_path, live: bytes = None):
    """Thinker 5.4 whose smac_mod/helpx.txt Longevity Vaccine patched: `live` the help text in place -- by default
    exactly our patch. An earlier version's .longevity.bak sits beside it (OLD's), never read: master's exact-undo
    model (user ruling 2026-11-17)."""
    game = _folder(tmp_path / "game", {**OLD, "smac_mod/helpx.txt": live if live is not None else patched_help()})
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V54)
    assert p.datalinks_ours == (["smac_mod/helpx.txt"] if live is None else [])
    prep = tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), types.SimpleNamespace(label=V54), p, "5.5", st.UP)
    return game, prep


def _set(bdir: Path) -> dict:
    return {f.relative_to(bdir).as_posix(): f.read_bytes() for f in bdir.rglob("*") if f.is_file()}


def test_the_set_holds_the_players_original_help_text_and_no_longevity_bak(tmp_path):
    game, prep = _update_over_patched_help(tmp_path)
    tf.commit(prep, route="thinker")
    got = _set(prep.report.backup_dir)
    assert got["smac_mod/helpx.txt"] == stock_help()                                    # their build's own text
    assert not any(r.endswith(tu.BAK) for r in got), sorted(got)
    tf.finish(prep)
    assert not tu.rollback_dir(prep.report.backup_dir).exists()                        # undo-only copies: gone
    assert tu.older_backups(game) == [prep.report.backup_dir]                          # never counted as a set


def test_undo_still_puts_the_patched_text_back(tmp_path):
    game, prep = _update_over_patched_help(tmp_path)
    old_bak = (game / "smac_mod" / "helpx.txt.longevity.bak").read_bytes()
    tf.commit(prep, route="thinker")
    assert tu.undo(game) == tu.UNDONE
    assert (game / "smac_mod" / "helpx.txt").read_bytes() == patched_help()
    assert (game / "smac_mod" / "helpx.txt.longevity.bak").read_bytes() == old_bak     # never touched
    assert not tu.rollback_dir(prep.report.backup_dir).exists()


def test_a_finished_recovery_drops_the_undo_copies(tmp_path):
    game, prep = _update_over_patched_help(tmp_path)
    tf.commit(prep, route="thinker")                                       # killed before finish
    assert tf.recover_at_entry(game) == tu.FINISHED
    assert not tu.rollback_dir(prep.report.backup_dir).exists()
    assert _set(prep.report.backup_dir)["smac_mod/helpx.txt"] == stock_help()


# ---------------------------------------------------------------- LOW-7: "Keep" clears the remove mark

def test_keep_at_fix_thinker_clears_the_remove_mark(tmp_path, monkeypatch):
    from test_audit_j import _fix_world
    w = _fix_world(tmp_path, monkeypatch, answers=["n"])
    lv_in_place(w.g)
    rec = _record(w.g)
    rec["remove"] = True
    (w.g / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.title == "UPDATE CANCELLED"
    after = _record(w.g)
    assert "remove" not in after and after["files"] == rec["files"]
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert tf.ask_uninstall_thinker(w.g) is False                          # the next uninstall asks; unattended: stays


# ---------------------------------------------------------------- LOW-1: --fix-thinker without Longevity Vaccine

NOT_INSTALLED = "Longevity Vaccine is not installed in this game folder, so nothing was changed."


@pytest.mark.parametrize("flags", [{}, {"with_thinker": True}], ids=["asked", "with-thinker"])
def test_fix_thinker_refuses_a_folder_without_longevity_vaccine(tmp_path, monkeypatch, flags):
    """M01 / M09: a part-finished "Also uninstall" took uimod.dll and put the original exe back."""
    from test_audit_j import _fix_world
    w = _fix_world(tmp_path, monkeypatch, answers=[""])
    monkeypatch.setattr(inst, "lv_in_place", _LV, raising=False)            # the real test (World stubs it)
    for k, v in flags.items():
        setattr(w.args, k, v)
    patched = []
    monkeypatch.setattr(inst, "patch_datalinks_text", lambda g: patched.append(g) or {})
    (w.g / "terranx.exe").write_bytes(b"MZ the player's original")
    (w.g / "terranx.exe.bak").write_bytes(b"MZ the player's original")
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.message == NOT_INSTALLED and e.value.title == "NOTHING WAS CHANGED"
    assert e.value.remedy == f"run the Longevity Vaccine installer to install it; you can download it from {tf.DOWNLOAD_PAGE}."
    assert w.prepared == [] and w.committed == [] and patched == [] and w.asked == []
    assert inst._LAUNCH_EXE is None                                         # no "Start the game"


_LV = getattr(inst, "lv_in_place", None)


def test_lv_in_place_needs_uimod_dll_and_a_patched_exe(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    assert inst.lv_in_place(g) is False
    lv_in_place(g)
    assert inst.lv_in_place(g) is True
    (g / "uimod.dll").unlink()
    assert inst.lv_in_place(g) is False
    lv_in_place(g)
    (g / "terranx.exe").write_bytes((g / "terranx.exe.bak").read_bytes())  # the original back
    assert inst.lv_in_place(g) is False


# ---------------------------------------------------------------- LOW-2: our thinker.ini is never left unlisted

KEPT_EDITED = f"{'thinker.ini':<20} - a Thinker Mod file you changed, so it was kept"
KEPT_AS_WRITTEN = f"{'thinker.ini':<20} - Thinker Mod's settings file"           # user-approved 2026-11-16


def test_m11_an_edited_thinker_ini_kept_is_named(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.exe").unlink()                                         # the player deleted it
    (game / "thinker.ini").write_bytes(b"[thinker]\r\nmine=1\r\n")
    tf.remove_thinker(game)
    assert (game / "thinker.ini").is_file() and KEPT_EDITED in tf.kept_lines()


def test_m11_our_thinker_ini_as_written_is_named_too(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.exe").unlink()
    tf.remove_thinker(game)
    assert (game / "thinker.ini").is_file() and KEPT_AS_WRITTEN in tf.kept_lines()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows locks")
def test_m08_a_setup_after_a_locked_thinker_ini_keeps_the_removal_to_finish(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    with open(game / "thinker.ini", "rb"):
        assert tf.remove_thinker(game)[1] == 1
    assert not (game / "thinker.dll").exists()
    tf.settle_install_record(game)                                          # setup, "Only install"
    assert _record(game).get("remove") is True
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert tf.ask_uninstall_thinker(game) is True and tf.remove_thinker(game)[1] == 0
    assert not (game / "thinker.ini").exists()


# ---------------------------------------------------------------- LOW-6: a full disk is not a lock

@pytest.mark.parametrize("err", [OSError(28, "No space left on device"), OSError(None, "disk full", None, 112)],
                         ids=["errno-28", "winerror-112"])
def test_a_full_disk_during_the_backup_says_so(tmp_path, monkeypatch, err):
    from test_thinker_install_review import _first_install_plan
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ", "thinker.ini": b"[thinker]\r\nx=1\r\n"})
    prep.nothing, prep.retry, prep.as_were = "nothing was changed", "run the installer again", ""
    real = Path.write_bytes

    def full(self, data):
        if "backups" in self.parts:
            raise err
        return real(self, data)
    monkeypatch.setattr(Path, "write_bytes", full)
    with pytest.raises(ix.InstallerError) as e:
        tf.commit(prep, route="fresh")
    assert e.value.message == "Thinker Mod could not be changed (the disk is full), so nothing was changed."
    assert e.value.remedy == "free some disk space, then run the installer again."
    assert "antivirus" not in e.value.remedy
