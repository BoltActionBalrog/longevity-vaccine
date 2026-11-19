"""Three changes from the user after talking with the Thinker author (2026-11-16), each written to fail first.
B1: new Thinker users are pointed at Thinker's Details.md. B2: the Thinker changelog choice only when the build
shipped a Changelog.md (a development build may not). B3: a thinker.ini choice after every Thinker install, upgrade,
downgrade or build swap. Synthetic Thinker files stand in for the pinned release (conftest's synthetic_pin)."""
from __future__ import annotations

import hashlib
import json
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
import thinker_source as src        # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
from test_thinker_install_choices import Menu  # noqa: E402
from test_thinker_update import KNOWN, NEW, _folder  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")

DETAILS = "https://github.com/induktio/thinker/blob/master/Details.md"
FALLBACK = f"What's new in Thinker Mod: {src.CHANGELOG_URL}"


# ---------------------------------------------------------------- B1: Details.md for players new to Thinker

def test_the_details_page_is_a_constant_beside_the_repository():
    assert src.THINKER_DETAILS_URL == DETAILS == src.THINKER_REPO_URL + "/blob/master/Details.md"


def test_only_the_new_install_screen_points_at_the_details_page():
    assert tf.new_install_notes("5.5")[-1].endswith(f"Learn more here: {DETAILS}")
    # The screens for players who have Thinker (Q1, journey R's Q-T) keep the repository page.
    assert tf.project_line().endswith(f"Learn more here: {src.THINKER_REPO_URL}")
    assert tf.thinker_block("first", ["can"], st.UP, "5.5")[-1] == tf.project_line()


# ---------------------------------------------------------------- B2: the changelog only when the build has one

def _without_changelog(monkeypatch):
    """A build whose release has no Changelog.md (a development build may not)."""
    table = {rel.lower(): (rel, hashlib.sha256(data).hexdigest()) for rel, data in NEW.items()}
    pid = tf.compiled_pin().pin_id
    monkeypatch.setattr(tf, "_pin_files", lambda pin_id: dict(table) if pin_id == pid else {})


def _install(tmp_path, *, changelog: bool, pin=None, game_files=None) -> tuple:
    """A first Thinker install through the real plan, commit and finish (as setup's B)."""
    files = {**NEW, **({"Changelog.md": b"what's new"} if changelog else {})}
    game = _folder(tmp_path / "game", game_files or {"terranx.exe": b"MZ"})
    staged_dir = _folder(tmp_path / "staged", files)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in files}
    pin = pin or tf.compiled_pin()
    p = tu.plan(game, pin.pin_id, staged, known=KNOWN, old_stock=None, ts=st.ts_display(pin.pin_id),
                from_label=st.Label())
    prep = tf.Prepared(game, pin, tf.compiled_meta(), None, p, st.ts_display(pin.pin_id), st.OTHER, new=True)
    tf.commit(prep, route="fresh")
    tf.finish(prep)
    return game, prep


def _stale(game: Path, name: str = "thinker-changelog-5.4.txt") -> Path:
    """A copy an older build left (its deletion failed): never this build's."""
    p = game / "LongevityMods" / name
    p.write_bytes(b"Thinker Mod 5.4's changelog")
    return p


def _console(monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)


def test_a_build_without_a_changelog_never_offers_one(tmp_path, monkeypatch, capsys):
    _without_changelog(monkeypatch)
    game, _ = _install(tmp_path, changelog=False)
    assert not list((game / "LongevityMods").glob(tf.CHANGELOG_GLOB))
    _stale(game)
    _console(monkeypatch)
    m = Menu(monkeypatch)
    tf.offer_changelog(game, 0)
    assert not m.calls
    assert FALLBACK in capsys.readouterr().out


def test_a_development_build_without_a_changelog_never_offers_one(tmp_path, monkeypatch, capsys):
    dev = src.Pin("dev-20261101", dropbox="https://www.dropbox.com/scl/fi/x/thinker.zip", rlkey="k",
                  zip_size=1, zip_sha256="0" * 64)
    game, prep = _install(tmp_path, changelog=False, pin=dev)
    assert json.loads((game / tf.RECORD_FILE).read_text(encoding="utf-8"))["to"] == "dev-20261101"
    _stale(game, "thinker-changelog-5.5.txt")                          # the release installed before it
    _console(monkeypatch)
    m = Menu(monkeypatch)
    tf.offer_changelog(game, 0)
    assert not m.calls and FALLBACK in capsys.readouterr().out
    assert tf.ask_uninstall_thinker(game) is False                     # no record of a pin it cannot check: no crash


def test_installing_a_build_without_a_changelog_deletes_an_older_builds_copy(tmp_path, monkeypatch):
    _without_changelog(monkeypatch)
    game = tmp_path / "game"
    (game / "LongevityMods").mkdir(parents=True)
    old = _stale(game)
    _install(tmp_path, changelog=False)
    assert not old.exists()


def test_a_build_with_a_changelog_offers_its_own_copy(tmp_path, monkeypatch):
    game, _ = _install(tmp_path, changelog=True)
    _stale(game)                                                        # sorts first; never this build's
    _console(monkeypatch)
    opened = []
    monkeypatch.setattr(tf, "_open_changelog", lambda copy, ts, rel: opened.append(copy.name))
    m = Menu(monkeypatch, 0)
    tf.offer_changelog(game, 0)
    assert m.calls[0]["options"] == ["Open the Thinker Mod 5.5 changelog", "Don't open it"]
    assert opened == ["thinker-changelog-5.5.txt"]


def test_uninstalling_a_build_without_a_changelog(tmp_path, monkeypatch):
    _without_changelog(monkeypatch)
    game, _ = _install(tmp_path, changelog=False)
    assert "Changelog.md" not in tf.read_install_record(game)["files"]
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    Menu(monkeypatch, 1)
    assert tf.ask_uninstall_thinker(game) is True
    removed, failed = tf.remove_thinker(game)
    assert failed == 0 and not (game / "thinker.dll").exists() and not (game / tf.INSTALL_RECORD).exists()


# ---------------------------------------------------------------- B3: the thinker.ini choice

NOTE = "Check Thinker.ini to adjust options, such as difficulty."      # the user's text, verbatim
OPEN = "Opening Thinker.ini in Notepad. If it does not appear, it is in your game folder: {}"
FAILED = "Thinker.ini could not be opened. It is in your game folder: {}"


def _args(**kw):
    return types.SimpleNamespace(**{"no_prompt": False, **kw})


def _asked(monkeypatch):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(ix, "is_worker", lambda: False)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)


def test_the_choice_is_owed_by_the_summary_untitled_with_skip_first(tmp_path, monkeypatch, capsys):
    """Asked in the closing lines, directly before the changelog (user 2026-11-16; test_ini_before_changelog)."""
    game, prep = _install(tmp_path, changelog=True)
    _asked(monkeypatch)
    m = Menu(monkeypatch, 0)
    tf.report_change(game, prep, _args())
    assert not m.calls
    tf.offer_owed_ini(game, 0)
    c, = m.calls
    assert c["title"] is None and c["notes"] == [NOTE] and c["at"] == 0
    assert c["options"] == ["Skip", "Open Thinker.ini"]
    assert capsys.readouterr().out.startswith("\n--- Thinker Mod ---\n"            # its own section (user 2026-11-16)
                                              + "".join(line + "\n" for line in tf.summary_lines(prep)))


def test_the_real_menu_puts_the_note_line_above_the_keys(tmp_path, monkeypatch, capsys):
    from test_arrow_choices import KEYS, _keys
    game, prep = _install(tmp_path, changelog=True)
    monkeypatch.setattr(ix, "is_worker", lambda: False)
    _keys(monkeypatch, "enter")
    capsys.readouterr()
    tf.offer_ini(game, _args())
    # (the empty line above it is ix.blank's, which never doubles one already printed)
    assert capsys.readouterr().out.lstrip("\n") == f"{NOTE}\n{KEYS}\n -> Skip\n    Open Thinker.ini\n\n"


def test_open_thinker_ini_opens_the_game_folders_copy_in_notepad(tmp_path, monkeypatch, capsys):
    game, _ = _install(tmp_path, changelog=True)
    _asked(monkeypatch)
    Menu(monkeypatch, 1)
    started = []
    monkeypatch.setattr(tf.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    tf.offer_ini(game, _args())
    assert started and started[0][0].lower().endswith("notepad.exe") and started[0][1] == str(game / "thinker.ini")
    assert OPEN.format(game / "thinker.ini") in capsys.readouterr().out


def test_open_thinker_ini_that_fails_says_where_it_is(tmp_path, monkeypatch, capsys):
    game, _ = _install(tmp_path, changelog=True)
    _asked(monkeypatch)
    Menu(monkeypatch, 1)
    monkeypatch.setattr(tf.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    tf.offer_ini(game, _args())
    out = capsys.readouterr().out
    assert FAILED.format(game / "thinker.ini") in out and "Opening" not in out


@pytest.mark.parametrize("stop", [KeyboardInterrupt(), EOFError()], ids=["ctrl-c", "eof"])
def test_ctrl_c_or_eof_is_skip(tmp_path, monkeypatch, capsys, stop):
    game, _ = _install(tmp_path, changelog=True)
    _asked(monkeypatch)
    Menu(monkeypatch, stop)
    monkeypatch.setattr(tf.subprocess, "Popen", lambda *a, **k: pytest.fail("opened on a stop"))
    tf.offer_ini(game, _args())                                         # no raise: the change is committed
    assert "Opening" not in capsys.readouterr().out


@pytest.mark.parametrize("how", ["no-console", "no-prompt", "worker-no-prompt"])
def test_without_a_choice_only_the_note_line(tmp_path, monkeypatch, capsys, how):
    game, prep = _install(tmp_path, changelog=True)
    monkeypatch.setattr(ix, "can_ask", lambda: how != "no-console")
    monkeypatch.setattr(ix, "is_worker", lambda: how == "worker-no-prompt")
    if how == "worker-no-prompt":
        monkeypatch.setenv(tf.PLAYER_NO_PROMPT_ENV, "1")
    m = Menu(monkeypatch)
    capsys.readouterr()
    tf.report_change(game, prep, _args(no_prompt=how == "no-prompt"))
    assert capsys.readouterr().out.splitlines() == ["", "--- Thinker Mod ---", *tf.summary_lines(prep)]
    tf.offer_owed_ini(game, 0)                                          # the closing lines (user 2026-11-16)
    assert not m.calls
    assert capsys.readouterr().out.splitlines() == ["", NOTE, ""]


def test_never_after_a_repair(monkeypatch, capsys):
    _asked(monkeypatch)
    m = Menu(monkeypatch)
    prep = types.SimpleNamespace(repair=1, ts="5.5")
    tf.report_change(Path("."), prep, _args())
    assert not m.calls and NOTE not in capsys.readouterr().out


@pytest.mark.parametrize("label,direction", [("Thinker Mod v5.4", st.UP), ("Thinker Mod v5.6", st.DOWN),
                                             ("Thinker Mod v5.5", st.OTHER)],
                         ids=["upgrade", "downgrade", "same-version-swap"])
def test_after_an_upgrade_a_downgrade_and_a_same_version_swap(tmp_path, monkeypatch, label, direction):
    from test_thinker_update import _setup
    game, p = _setup(tmp_path)
    prep = tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), types.SimpleNamespace(label=st.parse_label(label)),
                       p, "5.5", direction)
    tf.commit(prep, route="thinker")
    tf.finish(prep)
    _asked(monkeypatch)
    m = Menu(monkeypatch, 0)
    tf.report_change(game, prep, _args())
    tf.offer_owed_ini(game, 0)                                          # the closing lines (user 2026-11-16)
    assert m.calls and m.calls[0]["options"] == ["Skip", "Open Thinker.ini"]


def test_setup_the_update_and_fix_thinker_all_report_through_it():
    """Every place a committed change prints its summary goes through report_change (so the choice is owed, and the
    closing lines ask it)."""
    import inspect
    for f in (inst._install_from_questions, inst.do_update, tf._fix_thinker):
        src_ = inspect.getsource(f)
        assert "report_change(" in src_ and "summary_lines(" not in src_, f.__name__
