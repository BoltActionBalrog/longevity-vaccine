"""The setup re-run's pack texts, user-approved 2026-11-17 (after ff582f5): the summary statuses "Already installed",
"Updated", "Repaired" and "Success"; the list hint "Modules that are already installed stay ticked.", shown only when
a module in the list is installed; and a kept pack's own section. Each test written to fail first."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
from test_setup_pack_rerun import CLIPS, PORTRAITS, _World, _keys, _listed, _pack, _remote  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

HINT = "Modules that are already installed stay ticked."


# ---------------------------------------------------------------- 1. the summary statuses

@pytest.mark.parametrize("status,how,word", [("ok", "keep", "Already installed"), ("ok", "update", "Updated"),
                                             ("ok", "repair", "Repaired"), ("ok", "install", "Success"),
                                             ("error", "repair", "Error"), ("skip", None, "Skipped")])
def test_the_summary_says_what_happened_to_each_pack(monkeypatch, capsys, status, how, word):
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    ix.status_line("Z2k Retro's HD Cinematics", inst.pack_summary_status(status, how))
    assert capsys.readouterr().out.rstrip("\n").endswith(" " + word)


def test_the_setup_summary_uses_them():
    import inspect
    assert "pack_summary_status(" in inspect.getsource(inst._install_rest)


# ---------------------------------------------------------------- 2. the list hint, only with an installed module

def _picker_out(monkeypatch, capsys, catalogue) -> str:
    _keys(monkeypatch, "down", "down", "enter")
    capsys.readouterr()
    inst._tick_picker(list(catalogue), catalogue, {n: True for n in catalogue})
    return capsys.readouterr().out


def test_the_hint_appears_when_a_module_is_installed(monkeypatch, capsys):
    out = _picker_out(monkeypatch, capsys, {"movies-hd": _listed(on_disk=True, locked=True),
                                            "portraits-hd": _listed()})
    assert out.count(HINT) == 1
    assert out.index("You can download these later from the in-game preferences menu.") < out.index(HINT) \
        < out.index("Up/Down: move")


@pytest.mark.parametrize("on_disk", [False, True], ids=["none-installed", "a-folder-without-its-manifest"])
def test_no_hint_without_an_installed_module(monkeypatch, capsys, on_disk):
    out = _picker_out(monkeypatch, capsys, {"movies-hd": _listed(on_disk=on_disk), "portraits-hd": _listed()})
    assert HINT not in out


# ---------------------------------------------------------------- 3. the kept pack's own section

@pytest.mark.parametrize("name,files,credit", [("movies-hd", CLIPS, "CINEMATICS_CREDIT"),
                                               ("portraits-hd", PORTRAITS, "PORTRAIT_ART_CREDIT")])
def test_a_kept_pack_says_so_with_its_credit(tmp_path, monkeypatch, capsys, name, files, credit):
    w = _World(tmp_path, monkeypatch)
    _pack(w.game, name, files)
    capsys.readouterr()
    w.place([name], {name: _remote("1.0.0")}, {name: "1.0.0"})
    lines = capsys.readouterr().out.split("\n")
    i = lines.index(f"--- {inst.MODULE_LABELS[name]} ---")
    assert lines[i - 1] == "" and lines[i + 1:i + 3] == ["  v1.0.0 is already installed; nothing was downloaded.",
                                                          getattr(inst, credit)]


def test_a_pack_that_is_downloaded_has_no_kept_line(tmp_path, monkeypatch, capsys):
    w = _World(tmp_path, monkeypatch)
    capsys.readouterr()
    w.place(["movies-hd"], {"movies-hd": _remote("1.0.0")}, {})
    assert "already installed; nothing was downloaded" not in capsys.readouterr().out
