"""The eighth verification (audit-i, of 873c573..0178e6d, 2026-11-16): one regression per finding, each written to
fail first. MEDIUM-1: an interrupted "Also uninstall" removed thinker.ini while thinker.exe and thinker.dll stayed --
Thinker's DllMain stops with "Error while opening thinker.ini file." (refs/thinker/src/main.cpp) -- and no later run
put it back. LOW-1: a double empty line after the thinker.ini note. Synthetic Thinker files stand in for the pinned
release (conftest's synthetic_pin)."""
from __future__ import annotations

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
from test_uninstall_thinker_packs import _installed_thinker  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions and locks")
STARTS = ("thinker.exe", "thinker.dll", "thinker.ini")      # what Thinker needs to start


def _startable(game: Path) -> bool:
    return all((game / n).is_file() for n in STARTS)


def _lock_other(game: Path):
    return open(game / "basenames" / "hive.txt", "rb")       # L16: a locked file of the release (Readme.md there)


def _lock_exe(game: Path):
    return open(game / "thinker.exe", "rb")                   # L07 / L08: a locked thinker.exe


def _link_on_the_way(game: Path):
    """U04: a link-only failure (smac_mod is a junction to a folder inside the game folder)."""
    import _winapi
    inside = game / "elsewhere-inside"
    (game / "smac_mod").rename(inside)
    _winapi.CreateJunction(str(inside), str(game / "smac_mod"))

    class _Nothing:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return _Nothing()


@windows
@pytest.mark.parametrize("failure", [_lock_other, _lock_exe, _link_on_the_way], ids=["locked-file", "locked-exe", "link"])
def test_a_partial_also_uninstall_leaves_thinker_startable(tmp_path, failure):
    game, _ = _installed_thinker(tmp_path)
    with failure(game):
        removed, failed = tf.remove_thinker(game)
    assert failed >= 1
    assert _startable(game), [n for n in STARTS if not (game / n).is_file()]


@windows
@pytest.mark.parametrize("failure", [_lock_other, _lock_exe, _link_on_the_way], ids=["locked-file", "locked-exe", "link"])
def test_the_rewritten_record_keeps_every_file_still_present(tmp_path, failure):
    game, _ = _installed_thinker(tmp_path)
    with failure(game):
        tf.remove_thinker(game)
    rec = tf.read_install_record(game)
    # Audit-j MEDIUM-2 goes further than "every file still present": the FULL record stays, marked.
    present = {r for r in rec["files"] if game.joinpath(*r.split("/")).is_file()} if rec else set()
    assert rec is not None and rec["remove"] is True and {"thinker.ini", "thinker.exe", "thinker.dll"} <= present


@windows
def test_a_reinstall_after_a_partial_uninstall_keeps_thinker_ini(tmp_path, monkeypatch):
    """The setup / update run that follows (settle_install_record) and --fix-thinker's "already work together" leave
    the folder as it is: Thinker must still start, thinker.ini included."""
    game, _ = _installed_thinker(tmp_path)
    with _lock_exe(game):
        tf.remove_thinker(game)
    tf.settle_install_record(game)                            # every successful setup / update run
    assert _startable(game)
    rec = tf.read_install_record(game)
    assert rec is not None and "thinker.ini" in rec["files"] and not rec.get("remove")
    assert "thinker.ini" not in tf.missing_release_files(game)


@windows
def test_the_next_uninstall_still_finishes_the_whole_set(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    with _lock_exe(game):
        tf.remove_thinker(game)
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert tf.ask_uninstall_thinker(game) is True             # marked: finished without asking
    assert tf.remove_thinker(game)[1] == 0
    assert not any((game / n).exists() for n in STARTS)


def test_thinker_ini_goes_after_thinker_exe_and_thinker_dll(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    order = []
    real = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: order.append(self.name) or real(self, *a, **k))
    removed, failed = tf.remove_thinker(game)
    assert failed == 0
    ours = [n for n in order if n in STARTS]
    assert ours == ["thinker.exe", "thinker.dll", "thinker.ini"], order


# ---------------------------------------------------------------- LOW-1: one empty line after the note

def test_one_empty_line_between_the_note_and_the_shortcut_lines(tmp_path, monkeypatch, capsys):
    game, _ = _installed_thinker(tmp_path)
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "mod_exe", lambda *a: game / "thinker.exe")
    monkeypatch.setattr(inst, "find_shortcut_to", lambda exe: None)
    capsys.readouterr()
    tf.offer_ini(game, types.SimpleNamespace(no_prompt=False))
    inst.check_desktop_shortcut(game, "pracx_thinker", ask=False)
    out = capsys.readouterr().out
    assert f"{tf.INI_NOTE}\n\nYou do not have a desktop shortcut" in out, out


# ---------------------------------------------------------------- thinker.ini is the one that fails

@windows
def test_a_locked_thinker_ini_left_last_is_finished_by_the_next_uninstall(tmp_path, monkeypatch):
    """thinker.ini goes after thinker.exe and thinker.dll: when it alone fails, Thinker is already gone, and the
    marked record (it keeps our thinker.dll entry) finishes it without asking."""
    game, _ = _installed_thinker(tmp_path)
    with open(game / "thinker.ini", "rb"):
        assert tf.remove_thinker(game)[1] == 1
    assert not (game / "thinker.dll").exists() and (game / "thinker.ini").is_file()
    rec = tf.read_install_record(game)
    assert rec["remove"] is True and {"thinker.dll", "thinker.ini", "thinker.exe"} <= set(rec["files"])   # full
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert tf.ask_uninstall_thinker(game) is True
    assert tf.remove_thinker(game) == (1, 0)
    assert not (game / "thinker.ini").exists() and not (game / tf.INSTALL_RECORD).exists()


def test_the_remainder_rule_never_takes_thinker_ini_while_other_files_are_in_place(tmp_path, monkeypatch):
    """H2A stays refused: a marked record, no thinker.dll, but other recorded files still there."""
    import json
    game, _ = _installed_thinker(tmp_path)
    rec = json.loads((game / tf.INSTALL_RECORD).read_text(encoding="utf-8"))
    rec["remove"] = True
    (game / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")
    (game / "thinker.dll").unlink()
    (game / "thinker.exe").unlink()
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    if tf.ask_uninstall_thinker(game):
        tf.remove_thinker(game)
    assert (game / "thinker.ini").is_file() and (game / "basenames" / "hive.txt").is_file()
