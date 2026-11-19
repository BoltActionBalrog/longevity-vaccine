"""Audit-m #7 (2026-11-16): a thinker.dll held open with no sharing (another program has it) crashed setup with
INSTALLER ERROR -- a PermissionError out of thinker_state.read_dll. Every caller now says it the way a locked Thinker
file is said (the approved "<file> is in use by another program, so nothing was installed/changed." and its remedy),
or, where nothing is being changed, goes on without it. Each test written to fail first."""
from __future__ import annotations

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
import thinker_state as st          # noqa: E402
from test_audit_l import _Exclusive  # noqa: E402
from test_thinker_flow import _dll  # noqa: E402
from test_uninstall_thinker_packs import _installed_thinker  # noqa: E402

pytestmark = [pytest.mark.usefixtures("install_globals", "synthetic_pin"),
              pytest.mark.skipif(sys.platform != "win32", reason="a Windows no-share lock")]

REMEDY = ("close any program that may have the game folder open (a file manager, an editor, another copy of the "
          "game), wait a minute for any antivirus scan, then {}.")


def _game_with_thinker_54(tmp_path) -> Path:
    g = tmp_path / "game"
    g.mkdir()
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    return g


def _args(**kw):
    return types.SimpleNamespace(**{"with_thinker": False, "keep_thinker": False, "no_prompt": False, **kw})


def _in_use(e, nothing: str, route: str) -> None:
    assert e.message == f"thinker.dll is in use by another program, so {nothing}.", e.message
    assert e.remedy == REMEDY.format(tf.RETRY[route]) and e.changed is False


def test_read_dll_says_the_dll_cannot_be_read(tmp_path):
    g = _game_with_thinker_54(tmp_path)
    with _Exclusive(g / "thinker.dll"):
        with pytest.raises(st.DllUnreadable):
            st.classify(g, "0" * 64)


@pytest.mark.parametrize("fresh,nothing,route", [(True, "nothing was installed", "B"),
                                                 (False, "nothing was changed", "A")], ids=["setup", "update"])
def test_setup_and_the_update_say_it_is_in_use(tmp_path, fresh, nothing, route):
    g = _game_with_thinker_54(tmp_path)
    with _Exclusive(g / "thinker.dll"):
        with pytest.raises(ix.InstallerError) as e:
            tf.update_preflight(g, _args(), None, fresh=fresh, lv="1.0.0", persist_issued=False)
    _in_use(e.value, nothing, route)


def test_setups_new_install_screen_says_it_is_in_use(tmp_path):
    g = _game_with_thinker_54(tmp_path)
    with _Exclusive(g / "thinker.dll"):
        with pytest.raises(ix.InstallerError) as e:
            tf.offer_thinker_install(g, _args(), "1.0.0")
    _in_use(e.value, "nothing was installed", "B")


def test_the_deferred_download_step_says_it_is_in_use(tmp_path):
    g = _game_with_thinker_54(tmp_path)
    with _Exclusive(g / "thinker.dll"):
        with pytest.raises(ix.InstallerError) as e:
            tf.prepare(g, tf.compiled_pin(), tf.compiled_meta(), "1.0.0", route="B", fresh=True)
    _in_use(e.value, "nothing was installed", "B")


def test_fix_thinker_says_it_is_in_use(tmp_path, monkeypatch):
    from test_thinker_flow import World
    w = World(tmp_path, monkeypatch, answers=[])
    with _Exclusive(w.g / "thinker.dll"):
        with pytest.raises(ix.InstallerError) as e:
            w.run()
    _in_use(e.value, "nothing was changed", "R")


def test_the_uninstall_goes_on_and_keeps_thinker_and_its_record(tmp_path, monkeypatch, capsys):
    """Nothing about Thinker can be decided while its dll cannot be read: the question is not put, and -- since the
    merge with master's up-front check (user ruling 2026-11-17, D3(a)) -- the uninstall refuses before any change,
    as for any file it reads that is in use: Thinker, its record and everything else stay, so the next run asks."""
    game, _ = _installed_thinker(tmp_path)
    inst._load_modules()
    monkeypatch.setattr(ix, "stdin_is_console", lambda: True)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("asked about a Thinker it cannot read"))
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    with _Exclusive(game / "thinker.dll"):
        with pytest.raises(ix.InstallerError) as e:
            inst.do_uninstall(game, types.SimpleNamespace(no_prompt=False, force=False))
    assert e.value.title == "UNINSTALL NOT STARTED" and "thinker.dll" in (e.value.detail or "")   # no crash
    assert (game / tf.INSTALL_RECORD).is_file() and (game / "thinker.dll").is_file()


def test_the_uninstall_lines_and_the_changelog_offer_never_crash(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    (game / tf.RECORD_FILE).write_text(json.dumps({"to": tf.compiled_pin().pin_id, "at": 2_000_000_000,
                                                   "changelog_offered": False}), encoding="utf-8")
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    with _Exclusive(game / "thinker.dll"):
        assert tf.uninstall_lines(game) == []
        tf.offer_changelog(game, 0)


# ---------------------------------------------------------------- the Thinker summary's own section (user 2026-11-16)

def _summary_world(monkeypatch, *, repair=0):
    monkeypatch.setattr(tf, "summary_lines", lambda prep: ["  Thinker Mod: updated to 5.5 (1 file replaced, 0 added, 0 kept)"])
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(ix, "is_worker", lambda: False)
    return types.SimpleNamespace(repair=repair, ts="5.5")


@pytest.mark.parametrize("repair", [0, 2], ids=["change", "repair"])
def test_the_thinker_summary_has_its_own_heading(tmp_path, monkeypatch, capsys, repair):
    """Part 3 of the walkthrough: the summary printed under "--- PRACX icons ---". Every route reports through
    report_change, so one heading covers setup, the update, --fix-thinker and a repair; the thinker.ini note (or choice)
    follows under it. The thinker.ini note moved to the closing lines, before the changelog (user 2026-11-16): owed
    here, never a repair's."""
    prep = _summary_world(monkeypatch, repair=repair)
    ix.say("--- PRACX icons ---")
    ix.say("  added PRACX's icon art to Icons.pcx")
    capsys.readouterr()
    tf.report_change(tmp_path, prep, _args())
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["", "--- Thinker Mod ---", "  Thinker Mod: updated to 5.5 (1 file replaced, 0 added, 0 kept)"]
    assert tf._INI_OWED is (None if repair else False)                 # no console: the note line, at the close
