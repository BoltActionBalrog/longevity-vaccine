"""User ruling 2026-11-17 (walkthrough Part 8): the uninstall verdict no longer ends with "The items listed above were
deliberately left in place." -- UNINSTALL COMPLETE and INCOMPLETE alike. The rest of the verdict is unchanged."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
from test_uninstall_thinker_packs import _console, _installed_thinker, installed_with_thinker  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")   # as the fixture's own module

GONE = "deliberately left in place"


def _uninstall(g, monkeypatch):
    _console(monkeypatch, ["down", "enter"])
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    return inst._VERDICT


def test_a_complete_uninstall_verdict_does_not_say_items_were_left_in_place(installed_with_thinker, monkeypatch):
    title, body = _uninstall(installed_with_thinker, monkeypatch)
    assert title == "UNINSTALL COMPLETE"
    assert GONE not in body
    assert body.endswith(" removed."), body          # the counts sentence is now the whole verdict


def test_an_incomplete_uninstall_verdict_does_not_say_it_either(installed_with_thinker, monkeypatch):
    """INCOMPLETE is the fallback for a lock the up-front check cannot foresee (bypassed here)."""
    import preflight as pfm
    g = installed_with_thinker
    monkeypatch.setattr(pfm, "probe", lambda p, modes: "")
    with open(g / "thinker.exe", "rb"):              # held open: its removal fails
        title, body = _uninstall(g, monkeypatch)
    assert title == "UNINSTALL INCOMPLETE"
    assert GONE not in body
    assert body.endswith("Close the game and any program that has those files open, make sure they are not read-only, and run --uninstall again to finish."), body


def test_the_sentence_is_gone_from_the_source():
    assert GONE not in (_SCRIPTS / "install.py").read_text(encoding="utf-8")
