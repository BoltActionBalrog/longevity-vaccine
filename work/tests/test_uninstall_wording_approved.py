"""Two uninstall texts the user approved (2026-11-16), each written to fail first:
(2) a pack whose pack-manifest.json cannot be read is left in place and said so -- a WARNING line and a "Left in
    place:" row -- without counting as a failure (a re-run could not read it either);
(3) a Ctrl-C during --uninstall is "UNINSTALL CANCELLED", not "INSTALLATION CANCELLED"."""
from __future__ import annotations

import json
import os
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
from test_uninstall_thinker_packs import _pack, installed_with_thinker  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("install_globals")

MOVIES_WARN = ("  WARNING: movies\\hd\\pack-manifest.json could not be read, so Z2k Retro's HD Cinematics was left "
               "in place.")
PORTRAITS_WARN = ("  WARNING: portraits\\hd\\pack-manifest.json could not be read, so Turovetsky's HD Portrait Pack "
                  "was left in place.")
MOVIES_ROW = "    movies\\hd\\           - Z2k Retro's HD Cinematics: its file list could not be read"
PORTRAITS_ROW = "    portraits\\hd\\        - Turovetsky's HD Portrait Pack: its file list could not be read"


@pytest.mark.parametrize("body", [b"{not json", json.dumps({"files": [{"name": "../mine.png"}]}).encode()],
                         ids=["unparseable", "a-name-leaving-the-pack"])
def test_an_unreadable_pack_manifest_is_said_and_not_a_failure(tmp_path, capsys, body):
    game = tmp_path / "game"
    d = _pack(game, "portraits/hd", "portraits-hd", ["caretake.png"])
    (d / "pack-manifest.json").write_bytes(body)
    assert inst.remove_pack(game, "portraits-hd") == (0, 0)
    assert (d / "caretake.png").is_file()
    assert PORTRAITS_WARN + "\n" in capsys.readouterr().out
    assert inst._PACKS_UNREAD == ["portraits-hd"]


def test_the_uninstall_lists_the_unread_pack_and_completes(installed_with_thinker, monkeypatch, capsys):
    g = installed_with_thinker
    (g / "movies" / "hd" / "pack-manifest.json").write_bytes(b"\x00garbled")
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    assert inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False)) == ix.EXIT_OK
    out = capsys.readouterr().out
    assert MOVIES_WARN + "\n" in out
    left = out.split("\n  Left in place:\n", 1)[1]
    assert MOVIES_ROW + "\n" in left
    assert inst._VERDICT[0] == "UNINSTALL COMPLETE" and not (g / rc.JSON_NAME).exists()
    assert (g / "movies" / "hd" / "angels.mp4").is_file()


def test_a_readable_pack_says_nothing_of_it(tmp_path, capsys):
    game = tmp_path / "game"
    _pack(game, "movies/hd", "movies-hd", ["angels.mp4"])
    inst._PACKS_UNREAD[:] = []
    inst.remove_pack(game, "movies-hd")
    assert "could not be read" not in capsys.readouterr().out and inst._PACKS_UNREAD == []


# ---------------------------------------------------------------- (3) UNINSTALL CANCELLED

def test_a_ctrl_c_during_the_uninstall_is_uninstall_cancelled(monkeypatch, capsys):
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    monkeypatch.setattr(ix, "write_guard_marker", lambda: None)

    def run():
        raise KeyboardInterrupt
    code = ix.run_guarded(run, cancelled=lambda: inst.UNINSTALL_CANCELLED)
    out = capsys.readouterr().out
    assert code == ix.EXIT_INTERRUPTED
    assert "\nUNINSTALL CANCELLED\nYou interrupted the uninstall (Ctrl-C).\n\nRun the uninstall again to finish it.\n" \
        in out
    assert "INSTALLATION CANCELLED" not in out and "please uninstall" not in out


def test_any_other_ctrl_c_is_still_installation_cancelled(monkeypatch, capsys):
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    monkeypatch.setattr(ix, "write_guard_marker", lambda: None)

    def run():
        raise KeyboardInterrupt
    ix.run_guarded(run, cancelled=lambda: None)
    assert "\nINSTALLATION CANCELLED\nYou interrupted the installer (Ctrl-C).\n" in capsys.readouterr().out


def test_main_names_the_uninstall_for_its_cancel(monkeypatch):
    """install.main sets it from --uninstall, before anything else can be interrupted; the __main__ block passes it."""
    import inspect
    src = (_SCRIPTS / "install.py").read_text(encoding="utf-8")
    assert "cancelled=lambda: _CANCELLED" in src
    body = inspect.getsource(inst.main)
    assert body.index("_CANCELLED = UNINSTALL_CANCELLED") < body.index("resolve_game_dir(")
