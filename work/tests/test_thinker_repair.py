"""W9 (user-approved 2026-11-16): a setup or update run in a folder where this installer put Thinker Mod in place,
whose thinker.dll is still the recorded one, but some of the recorded release files are missing (an "Also
uninstall" that stopped part-way, say). It offers to put them back -- only them: a file the player changed is never
replaced -- with "Also repair and update Thinker Mod 5.5" / "Only update Longevity Vaccine". Each written to fail
first. The synthetic Thinker files of the other tests stand in for 5.5: the compiled pin's DLL hash is pointed at
them."""
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
import thinker_update as tu         # noqa: E402
from test_arrow_choices import KEYS, _keys  # noqa: E402
from test_thinker_install_review import _first_install_plan  # noqa: E402
from test_thinker_update import KNOWN, NEW, _folder  # noqa: E402
from test_uninstall_thinker_packs import _installed_thinker  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")

NOTES = ["Thinker Mod 5.5 in this game folder is missing 2 of its files.", "",
         "This installer can download Thinker Mod 5.5 and put the missing files back. Files you changed are not "
         "touched."]
ROWS = [" -> Also repair and update Thinker Mod 5.5", "    Only update Longevity Vaccine"]


@pytest.fixture
def damaged(tmp_path, monkeypatch):
    """Thinker 5.5 put in place by this installer, two of its files since removed."""
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.exe").unlink()
    (game / "basenames" / "hive.txt").unlink()
    real = tf.compiled_meta()
    monkeypatch.setattr(tf, "compiled_meta", lambda: {**real, "dll": tu.sha256(game / "thinker.dll")})
    prepared = []

    def prepare(game_dir, pin, meta, lv, **kw):
        prepared.append(kw)
        return types.SimpleNamespace(kw=kw)
    monkeypatch.setattr(tf, "prepare", prepare)
    return game, prepared


def _args(**kw):
    return types.SimpleNamespace(**{"with_thinker": False, "keep_thinker": False, "no_prompt": False, **kw})


def test_the_missing_files_come_from_the_record(damaged):
    game, _ = damaged
    assert tf.missing_release_files(game) == ["basenames/hive.txt", "thinker.exe"]


def test_no_missing_files_without_the_record_or_with_another_dll(damaged):
    game, _ = damaged
    (game / "thinker.dll").write_bytes(b"the player's own build")
    assert tf.missing_release_files(game) == []
    (game / tf.INSTALL_RECORD).unlink()
    assert tf.missing_release_files(game) == []


@pytest.mark.parametrize("fresh", [True, False], ids=["setup", "update"])
def test_the_repair_question_reads_as_approved_and_enter_repairs(damaged, monkeypatch, capsys, fresh):
    game, prepared = damaged
    _keys(monkeypatch, "enter")
    step = tf.update_preflight(game, _args(), None, fresh=fresh, lv="1.0.0", persist_issued=False)
    out = capsys.readouterr().out
    block = (f"{ix.RULE}\n THINKER MOD\n" + "".join(f" {n}\n" for n in NOTES) + f"{ix.RULE}\n{KEYS}\n"
             + "".join(r + "\n" for r in ROWS) + ix.RULE + "\n")
    assert block in out
    assert prepared and prepared[0]["repair"] == ["basenames/hive.txt", "thinker.exe"]
    assert step.prep is not None


def test_only_update_leaves_thinker_and_is_not_asked_again(damaged, monkeypatch):
    game, prepared = damaged
    _keys(monkeypatch, "down", "enter")
    step = tf.update_preflight(game, _args(), None, fresh=False, lv="1.0.0", persist_issued=False)
    assert step.prep is None and step.todo is None and prepared == []
    tf.settle_install_record(game)              # the run succeeded: only now are they forgotten (audit-l L3)
    assert tf.missing_release_files(game) == []                       # the record no longer lists them


def test_setup_defers_the_download(damaged, monkeypatch):
    game, prepared = damaged
    _keys(monkeypatch, "enter")
    step = tf.update_preflight(game, _args(), None, fresh=True, lv="1.0.0", persist_issued=False, defer=True)
    assert step.todo is not None and step.todo[3]["repair"] == ["basenames/hive.txt", "thinker.exe"]
    assert prepared == []


@pytest.mark.parametrize("how", ["no-console", "no-prompt"])
def test_without_asking_it_says_so_and_goes_on(damaged, monkeypatch, capsys, how):
    game, prepared = damaged
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("must not ask"))
    if how == "no-console":
        monkeypatch.setattr(ix, "can_ask", lambda: False)
        args = _args()
    else:
        monkeypatch.setattr(ix, "can_ask", lambda: True)
        args = _args(no_prompt=True)
    step = tf.update_preflight(game, args, None, fresh=True, lv="1.0.0", persist_issued=False)
    assert step.prep is None and prepared == []
    assert ("  Thinker Mod 5.5 is missing 2 of its files. Run the installer again in a console window to put them "
            "back.\n") in capsys.readouterr().out


def test_with_thinker_repairs_without_asking_and_keep_thinker_leaves_it(damaged, monkeypatch, capsys):
    game, prepared = damaged
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("must not ask"))
    tf.update_preflight(game, _args(with_thinker=True), None, fresh=False, lv="1.0.0", persist_issued=False)
    assert prepared[-1]["repair"] == ["basenames/hive.txt", "thinker.exe"]
    step = tf.update_preflight(game, _args(keep_thinker=True), None, fresh=False, lv="1.0.0", persist_issued=False)
    assert step.prep is None and len(prepared) == 1 and "is missing" not in capsys.readouterr().out


def test_ctrl_c_at_the_repair_question_changes_nothing(damaged, monkeypatch):
    game, prepared = damaged
    _keys(monkeypatch, KeyboardInterrupt())
    with pytest.raises(ix.InstallerError) as e:
        tf.update_preflight(game, _args(), None, fresh=True, lv="1.0.0", persist_issued=False)
    assert e.value.title == "NOTHING WAS CHANGED" and prepared == []


def test_nothing_is_missing_means_no_question(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    real = tf.compiled_meta()
    monkeypatch.setattr(tf, "compiled_meta", lambda: {**real, "dll": tu.sha256(game / "thinker.dll")})
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("must not ask"))
    step = tf.update_preflight(game, _args(), None, fresh=True, lv="1.0.0", persist_issued=False)
    assert step.prep is None and step.todo is None


# ---------------------------------------------------------------- the repair itself: only the missing files

def test_a_repair_puts_back_only_the_missing_files(tmp_path, capsys):
    game = _folder(tmp_path / "game", {**NEW, "modmenu.txt": b"my menu", "thinker.ini": b"[thinker]\r\nmine=1\r\n",
                                       "thinker_user.ini": b"[thinker]\r\nretired=1\r\n"})
    (game / "thinker.exe").unlink()
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=st.parse_label("Thinker Mod v5.5"))
    prep = tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), types.SimpleNamespace(label=st.parse_label("Thinker Mod v5.5")),
                       p, "5.5", st.OTHER)
    tf.as_repair(prep, ["thinker.exe"])
    assert [a.rel for a in prep.plan.changes()] == ["thinker.exe"] and prep.plan.user_ini is None
    tf.commit(prep, route="A")
    tf.finish(prep)
    assert (game / "thinker.exe").read_bytes() == NEW["thinker.exe"]
    assert (game / "modmenu.txt").read_bytes() == b"my menu"
    assert (game / "thinker.ini").read_bytes() == b"[thinker]\r\nmine=1\r\n"
    assert (game / "thinker_user.ini").read_bytes() == b"[thinker]\r\nretired=1\r\n"
    assert tu.older_backups(game) == []                                 # no empty "copies of your files" set
    assert not (game / tf.RECORD_FILE).exists()                         # no changelog offer for a repair
    assert tf.summary_lines(prep) == ["  Thinker Mod 5.5: 1 missing file put back"]


def test_the_summary_line_for_several(tmp_path):
    prep = types.SimpleNamespace(repair=2, ts="5.5")
    assert tf.summary_lines(prep) == ["  Thinker Mod 5.5: 2 missing files put back"]


def test_the_verdicts_say_nothing_more_of_a_repair():
    import inspect
    assert "repair" in inspect.getsource(inst._install_rest).split("_THINKER_NEW = ", 1)[1].split("_VERDICT = (", 1)[0]
    assert "repair" in inspect.getsource(inst.do_update).split("if base_stale:\n        done.insert", 1)[1][:400]
