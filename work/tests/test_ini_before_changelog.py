"""The thinker.ini choice sits directly before the Thinker changelog choice (user 2026-11-16: "Move the thinker.ini
prompt to be right before the changelog prompt in all cases. We shouldn't have the shortcut prompt bisecting them.").
The "--- Thinker Mod ---" heading and summary stay where they were; the choice (or its no-console note) follows the
verdict, as the last thing before the changelog choice or its fallback line, in setup, the update, the bootstrap's
worker and --fix-thinker. Same conditions (never after a repair), same text, Ctrl-C = Skip. Each test written to fail
first."""
from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bootstrap as bs              # noqa: E402
import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import thinker_flow as tf           # noqa: E402
from test_thinker_author_changes import FALLBACK, NOTE, _install  # noqa: E402
from test_thinker_install_choices import Menu  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")

INI = ["Skip", "Open Thinker.ini"]
CL = ["Open the Thinker Mod 5.5 changelog", "Don't open it"]


@pytest.fixture(autouse=True)
def _a_fresh_process(monkeypatch):
    """Each test is its own run: nothing owed from another test's change."""
    monkeypatch.setattr(tf, "_INI_OWED", None, raising=False)
    monkeypatch.setattr(inst, "find_shortcut_to", lambda exe: None)


def _console(monkeypatch, *, worker=False):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(ix, "is_worker", lambda: worker)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)


def _args(**kw):
    return types.SimpleNamespace(**{"no_prompt": False, **kw})


def _closing(game: Path) -> None:
    """run_guarded's closing lines of a success verdict (install._success_after -> print_play_note)."""
    saved = inst._NOTE_ARGS
    inst._NOTE_ARGS = (game, None)
    try:
        inst._success_after()
    finally:
        inst._NOTE_ARGS = saved


def test_the_summary_no_longer_asks(tmp_path, monkeypatch, capsys):
    game, prep = _install(tmp_path, changelog=True)
    _console(monkeypatch)
    m = Menu(monkeypatch)
    capsys.readouterr()
    tf.report_change(game, prep, _args())
    assert not m.calls
    assert capsys.readouterr().out.splitlines() == ["", "--- Thinker Mod ---", *tf.summary_lines(prep)]


def test_the_choice_comes_directly_before_the_changelog_choice(tmp_path, monkeypatch, capsys):
    game, prep = _install(tmp_path, changelog=True)
    _console(monkeypatch)
    m = Menu(monkeypatch, 0, 1)                                        # Skip, then Don't open it
    tf.report_change(game, prep, _args())
    ix.say("You do not have a desktop shortcut ...")                   # the shortcut, resolution, packs, verdict ...
    assert not m.calls                                                 # nothing asked under the summary
    capsys.readouterr()
    _closing(game)
    assert [c["options"] for c in m.calls] == [INI, CL]
    assert m.calls[0]["notes"] == [NOTE] and m.calls[0]["title"] is None
    # nothing printed between them (the fake lists print nothing; the ini choice's own empty line only)
    assert not capsys.readouterr().out.split("\n")[0].strip()


@pytest.mark.parametrize("gate", ["no-record", "already-offered", "no-dll"])
def test_the_choice_appears_exactly_once_when_the_changelog_does_not(tmp_path, monkeypatch, capsys, gate):
    game, prep = _install(tmp_path, changelog=True)
    _console(monkeypatch)
    m = Menu(monkeypatch, 0)
    tf.report_change(game, prep, _args())
    assert not m.calls
    rec = game / tf.RECORD_FILE
    if gate == "no-record":
        rec.unlink()
    elif gate == "already-offered":
        rec.write_text(json.dumps({**json.loads(rec.read_text(encoding="utf-8")), "changelog_offered": True}),
                       encoding="utf-8")
    else:
        (game / "thinker.dll").unlink()
    _closing(game)
    _closing(game)                                                      # a second closing never asks again
    assert [c["options"] for c in m.calls] == [INI]


def test_no_console_the_note_is_the_last_thing_before_the_fallback_line(tmp_path, monkeypatch, capsys):
    from test_thinker_author_changes import _without_changelog
    _without_changelog(monkeypatch)
    game, prep = _install(tmp_path, changelog=False)
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(ix, "is_worker", lambda: False)
    tf.report_change(game, prep, _args())
    capsys.readouterr()
    _closing(game)
    lines = capsys.readouterr().out.splitlines()
    i = lines.index(NOTE)
    assert lines[i + 1:i + 3] == ["", FALLBACK] and lines.count(NOTE) == 1


def test_never_after_a_repair(tmp_path, monkeypatch, capsys):
    game, _ = _install(tmp_path, changelog=True)
    _console(monkeypatch)
    m = Menu(monkeypatch, 1)
    tf.report_change(game, types.SimpleNamespace(repair=2, ts="5.5"), _args())
    _closing(game)
    assert [c["options"] for c in m.calls] == [CL] and NOTE not in capsys.readouterr().out


# ---------------------------------------------------------------- the bootstrap: the worker changes, the parent closes

def _worker_then_parent(game, prep, monkeypatch, capsys, m, *, player_no_prompt=False) -> tuple:
    """(what the worker asked, what it printed after its summary, what the parent printed)."""
    _console(monkeypatch, worker=True)
    if player_no_prompt:
        monkeypatch.setenv(tf.PLAYER_NO_PROMPT_ENV, "1")
    capsys.readouterr()
    tf.report_change(game, prep, _args(no_prompt=True))               # the bootstrap always passes --no-prompt
    asked = [c["options"] for c in m.calls]
    worker = capsys.readouterr().out.split("\n".join(tf.summary_lines(prep)), 1)[-1]
    monkeypatch.setattr(tf, "_INI_OWED", None, raising=False)          # the parent is another process
    monkeypatch.setattr(ix, "is_worker", lambda: False)
    monkeypatch.setattr(bs, "_NOTE_ARGS", (game, None))
    bs._closing_note()
    return asked, worker, capsys.readouterr().out


def test_the_bootstraps_parent_asks_it_directly_before_the_changelog(tmp_path, monkeypatch, capsys):
    game, prep = _install(tmp_path, changelog=True)
    m = Menu(monkeypatch, 0, 1)
    asked, _, _ = _worker_then_parent(game, prep, monkeypatch, capsys, m)
    assert asked == [] and [c["options"] for c in m.calls] == [INI, CL]


def test_the_players_no_prompt_reaches_the_parent_as_the_note(tmp_path, monkeypatch, capsys):
    game, prep = _install(tmp_path, changelog=True)
    m = Menu(monkeypatch, 1)
    _, worker, parent = _worker_then_parent(game, prep, monkeypatch, capsys, m, player_no_prompt=True)
    assert [c["options"] for c in m.calls] == [CL]
    assert NOTE not in worker and parent.count(NOTE) == 1


def test_a_worker_that_cannot_hand_it_on_asks_it_itself_once(tmp_path, monkeypatch, capsys):
    """The fallback (the old place, under the summary) only when the record cannot carry it: never lost, never twice."""
    game, prep = _install(tmp_path, changelog=True)
    (game / tf.RECORD_FILE).unlink()                                   # nowhere to carry it
    m = Menu(monkeypatch, 0)
    asked, _, _ = _worker_then_parent(game, prep, monkeypatch, capsys, m)
    assert asked == [INI] and [c["options"] for c in m.calls] == [INI]


def test_an_older_runs_unasked_choice_is_never_asked(tmp_path, monkeypatch):
    game, prep = _install(tmp_path, changelog=True)
    _console(monkeypatch, worker=True)
    tf.report_change(game, prep, _args(no_prompt=True))                # its parent failed, so nothing closed
    monkeypatch.setattr(ix, "is_worker", lambda: False)
    m = Menu(monkeypatch)
    tf.offer_changelog(game, 2_000_000_000)                            # a later run's closing
    tf.offer_owed_ini(game, 2_000_000_000)
    assert not m.calls


# ---------------------------------------------------------------- --fix-thinker, and every route's closing

def test_fix_thinker_asks_it_after_the_verdict(tmp_path, monkeypatch):
    from test_thinker_flow import World
    w = World(tmp_path, monkeypatch, answers=[""])                     # the change only
    assert w.run() == ix.EXIT_OK
    assert [a[0] for a in w.asked] == [["Update Thinker Mod to 5.5", "Keep Thinker Mod 5.4"]]
    w.answers[:] = [""]
    _closing(w.g)
    assert w.asked[1][0] == INI


def test_every_route_closes_through_the_one_place():
    """Setup, the update and --fix-thinker report through report_change, which owes the choice; the closing lines
    (install.print_play_note, the bootstrap's too) ask it, then the changelog, with nothing between."""
    for f in (inst._install_from_questions, inst.do_update, tf._fix_thinker, tf._fix_repair):
        assert "offer_ini(" not in inspect.getsource(f), f.__name__
    assert "offer_ini(" not in inspect.getsource(tf.report_change)
    note = inspect.getsource(inst.print_play_note)
    assert "offer_closing(" in note and "offer_changelog(" not in note
    assert "print_play_note(" in inspect.getsource(bs._closing_note)
    body = inspect.getsource(tf.offer_closing).split('"""')[-1]
    assert body.index("offer_owed_ini(") < body.index("offer_changelog(")
