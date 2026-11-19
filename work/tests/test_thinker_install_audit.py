"""The end-to-end execution audit of feat/thinker-install (2026-11-15): one regression per finding, each written
to fail first. (Its own runs drove the real install.py as __main__; these pin the defects in-process.)"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch                        # noqa: E402
import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import thinker_flow as tf           # noqa: E402
import thinker_source as src        # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
from test_thinker_flow import World, _dll  # noqa: E402
from test_thinker_install_review import _args, _fake_thinker_step, _first_install_plan  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")


# ---------------------------------------------------------------- #2: a corrupted Thinker zip

def test_a_file_that_arrives_whole_and_wrong_is_not_retried_as_a_network_error(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "Thinker_v5.5.zip"
    bad.write_bytes(b"not the release")
    calls = []
    real = fetch._fetch_one
    monkeypatch.setattr(fetch, "_fetch_one", lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    with pytest.raises(fetch.MismatchError):
        fetch.download(bad.as_uri(), tmp_path / "out" / "z.zip", sha256="0" * 64, size=bad.stat().st_size,
                       allow_file=True)
    assert len(calls) == 1
    assert "Could not reach the update server" not in capsys.readouterr().out


def test_a_corrupted_thinker_zip_says_it_did_not_match_the_release(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "Thinker_v5.5.zip"
    bad.write_bytes(b"x" * tf.compiled_pin().zip_size)          # whole, and not the release
    g = tmp_path / "game"
    g.mkdir()
    real = fetch.download
    monkeypatch.setattr(src, "download_url", lambda pin: bad.as_uri())
    monkeypatch.setattr(fetch, "download", lambda *a, **k: real(*a, **{**k, "allow_file": True}))
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    with pytest.raises(ix.InstallerError) as e:
        tf.prepare(g, tf.compiled_pin(), tf.compiled_meta(), "1.0.0", route="B", fresh=True)
    assert e.value.message.startswith("The Thinker Mod download did not match the Thinker Mod 5.5 release")
    assert "check your connection" not in (e.value.remedy or "")
    assert "Could not reach the update server" not in capsys.readouterr().out


# ---------------------------------------------------------------- #3: --no-prompt in a console

@pytest.mark.parametrize("fresh", [True, False], ids=["setup", "update"])
def test_no_prompt_in_a_console_names_the_flags_not_a_console(tmp_path, monkeypatch, fresh):
    g = tmp_path / "game"
    g.mkdir()
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(tf, "take_for_worker", lambda *a: None)
    ix.set_player_no_prompt(True)
    with pytest.raises(ix.InstallerError) as e:
        tf.update_preflight(g, types.SimpleNamespace(no_prompt=True), None, fresh=fresh, lv="1.0.0",
                            persist_issued=False)
    text = e.value.message + " " + (e.value.remedy or "")
    assert "--with-thinker" in text and "--keep-thinker" in text
    assert "console window" not in text


# ---------------------------------------------------------------- #5: --fix-thinker on the pinned build

def _pinned_world(tmp_path, monkeypatch, doc):
    refs = os.environ.get("LONGEVITY_REFS", "")
    if not refs:
        pytest.skip("LONGEVITY_REFS is not set (the pinned Thinker Mod 5.5 thinker.dll is under it)")
    real = Path(refs) / "thinker-release" / "v5.5" / "thinker.dll"
    if not real.is_file():
        from conftest import _missing           # set, and missing: a FAILURE under LONGEVITY_REQUIRE_E2E (audit-l L4)
        _missing(real, "the pinned Thinker Mod 5.5 thinker.dll")
    kw = {} if doc == "default" else {"doc": doc}
    w = World(tmp_path, monkeypatch, label=None, answers=[], **kw)
    (w.g / "thinker.dll").write_bytes(real.read_bytes())
    return w


@pytest.mark.parametrize("doc", ["default", None], ids=["online", "offline"])
def test_fix_thinker_on_the_pinned_build_is_already_up_to_date(tmp_path, monkeypatch, capsys, doc):
    w = _pinned_world(tmp_path, monkeypatch, doc)
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    out = capsys.readouterr().out
    assert e.value.title == "ALREADY UP TO DATE", (e.value.title, e.value.message)
    assert "This game folder has Thinker Mod 5.5." in out and "different build" not in out
    assert "InstallerError" not in out                      # #7: no Python class name in the console


# ---------------------------------------------------------------- #6: --no-prompt asks nothing at all

def test_no_prompt_means_no_question_at_all(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    assert ix.can_ask()
    ix.set_player_no_prompt(True)
    assert not ix.can_ask()
    monkeypatch.setattr(ix, "ask_line", lambda *a, **k: pytest.fail("asked the changelog question"))
    monkeypatch.setattr(ix, "ask", lambda *a, **k: pytest.fail("asked a question"))
    import install as inst
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("asked an arrow-key question"))
    g = tmp_path / "game"
    (g / "LongevityMods").mkdir(parents=True)
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    (g / "LongevityMods" / "thinker-changelog-5.5.txt").write_text("notes", encoding="utf-8")
    import json
    import time
    (g / tf.RECORD_FILE).write_text(json.dumps({"from": "x", "to": "5.4.0", "at": int(time.time()),
                                                "changelog_offered": False}), encoding="utf-8")
    tf.offer_changelog(g, time.time() - 5)
    exe = g / "thinker.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(ix, "interactive", lambda: True)
    assert ix.offer_relaunch(exe) is False


def test_the_worker_marker_is_the_players_no_prompt(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setenv("LONGEVITY_PLAYER_NO_PROMPT", "1")
    assert not ix.can_ask()


# ---------------------------------------------------------------- #7: the smaller findings

def test_one_file_is_singular(tmp_path):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    prep.report = types.SimpleNamespace(added=1, replaced=1, kept_or_merged=1, older_backups=0,
                                        backup_dir=tmp_path / "set")
    prep.new = False
    prep.dll = types.SimpleNamespace(label=st.parse_label("Thinker Mod v5.4"))
    prep.direction = st.UP
    assert tf.summary_lines(prep)[0] == "  Thinker Mod: updated to 5.5 (1 file replaced, 1 added, 1 kept)"


def test_the_keep_line_is_said_once(tmp_path, bak_path, monkeypatch, capsys):
    """Q1 answered "Only install": the KEEP line belongs to the verdict; the summary row says Skipped."""
    import shutil
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    (g / "thinker.exe").write_bytes(b"MZ")
    _fake_thinker_step(monkeypatch, g)
    assert inst._install(g, _args(with_thinker=False, keep_thinker=True)) == 0
    out = capsys.readouterr().out
    keep = "Your Thinker Mod 5.4 stays as it is."
    assert keep in inst._VERDICT[1] and out.count(keep) == 0


def test_a_finished_thinker_change_leaves_no_staging(tmp_path, monkeypatch):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    stg = game / "LongevityMods" / "staging" / "thinker"
    (stg / "files-5.5.0").mkdir(parents=True)
    (stg / "thinker-5.5.0.zip").write_bytes(b"zip")
    tf.commit(prep, route="fresh")
    tf.finish(prep)
    assert not stg.exists() and not stg.parent.exists()


def test_a_failed_download_leaves_no_empty_staging_folder(tmp_path, monkeypatch):
    g = tmp_path / "game"
    g.mkdir()

    def download(url, dest, **kw):
        raise fetch.FetchError("offline")
    monkeypatch.setattr(fetch, "download", download)
    with pytest.raises(ix.InstallerError):
        tf.prepare(g, tf.compiled_pin(), tf.compiled_meta(), "1.0.0", route="B", fresh=True)
    assert not (g / "LongevityMods" / "staging" / "thinker").exists()


def test_a_stop_says_nothing_was_changed_once(monkeypatch):
    assert ix.stopped_error().disk_note is False                  # the message itself says it


def test_the_fatal_refusals_of_a_setup_say_nothing_was_changed_once(tmp_path, monkeypatch):
    g = tmp_path / "game"
    g.mkdir()
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    _s, dll = st.classify(g, "0" * 64)
    monkeypatch.setattr(tf, "fatal_for", lambda *a: {dll.sha256})
    monkeypatch.setattr(tf, "take_for_worker", lambda *a: None)
    with pytest.raises(ix.InstallerError) as e:               # --keep-thinker on a fatal build
        tf.update_preflight(g, types.SimpleNamespace(keep_thinker=True), None, fresh=True, lv="1.0.0",
                            persist_issued=False)
    assert e.value.message.endswith("Nothing was changed.") and e.value.disk_note is False
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    monkeypatch.setattr(tf, "choose", lambda *a, **k: 1)       # "Cancel the installation"
    with pytest.raises(ix.InstallerError) as e:
        tf.update_preflight(g, types.SimpleNamespace(), None, fresh=True, lv="1.0.0", persist_issued=False)
    assert e.value.message.endswith("Nothing was changed.") and e.value.disk_note is False


def test_a_setup_that_changes_nothing_leaves_no_longevitymods_folder(tmp_path, bak_path, monkeypatch):
    """The fetched manifest went to LongevityMods\\staging before the questions; a cancel then said "Nothing on disk
    was changed". A first install that ends with nothing changed takes the folder it created away again."""
    import shutil
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    _fake_thinker_step(monkeypatch, g)

    def catalogue(gd, a):
        (gd / "LongevityMods" / "staging").mkdir(parents=True)
        (gd / "LongevityMods" / "staging" / "manifest.json").write_text("{}", encoding="utf-8")
        return [], None
    monkeypatch.setattr(inst, "module_catalogue", catalogue)
    monkeypatch.setattr(inst, "pick_modules", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(ix.InstallerError) as e:
        inst._install(g, _args(with_thinker=False, keep_thinker=True))
    assert e.value.changed is False and not (g / "LongevityMods").exists()


def test_an_update_refused_at_the_thinker_question_says_only_the_updater_was_refreshed(monkeypatch):
    """do_update wraps update_preflight: a no-change refusal there carries the updater's own disk note."""
    import ast
    tree = ast.parse((_SCRIPTS / "install.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "do_update")
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)
             and any(isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "update_preflight"
                     for s in n.body for c in ast.walk(s))]
    assert tries and "Only the updater itself was refreshed" in ast.unparse(tries[0])


def test_uninstall_says_thinker_stays_even_with_no_backup_set(tmp_path):
    """A first Thinker install by this installer keeps no backup set; uninstalling still says Thinker Mod stays."""
    g = tmp_path / "game"
    g.mkdir()
    assert tf.uninstall_lines(g) == []
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.5"))
    assert tf.uninstall_lines(g) == ["Thinker Mod 5.5 stays installed and works without Longevity Vaccine."]


def test_an_updates_keep_line_is_said_by_the_verdict_unless_it_is_muted():
    """do_update said the KEEP line, and its verdict said it again (execution audit 2026-11-15, s12g): only a worker,
    whose verdict the bootstrap's console mutes, says it before the verdict."""
    import ast
    tree = ast.parse((_SCRIPTS / "install.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "do_update")
    says = [n for n in ast.walk(fn) if isinstance(n, ast.If) and "tstep.keep" in ast.unparse(n.test)
            and any("ix.say" in ast.unparse(s) for s in n.body)]
    assert says and all("is_worker" in ast.unparse(n.test) for n in says)


# ---------------------------------------------------------------- the user's wording rulings (2026-11-15)

@pytest.mark.parametrize("label,want", [
    (b"Thinker Mod v5.4", "Your Thinker Mod 5.4 files will be backed up to a new folder in LongevityMods\\backups."),
    (b"Thinker Mod develop build",
     "Your development build of Thinker Mod will be backed up to a new folder in LongevityMods\\backups."),
    (b"Thinker Mod v5.5",
     "Your different build of Thinker Mod 5.5 will be backed up to a new folder in LongevityMods\\backups."),
    (b"Thinker Mod vX.5",
     "Your unrecognised build of Thinker Mod will be backed up to a new folder in LongevityMods\\backups."),
], ids=["version", "development", "different", "unrecognised"])
def test_the_backup_sentence_takes_files_only_after_a_version_number(tmp_path, label, want):
    """User 2026-11-15: "your development build of thinkermod will be backed up to a new folder in ..."; a build
    named by its version keeps "files"."""
    g = tmp_path / "game"
    g.mkdir()
    (g / "thinker.dll").write_bytes(_dll(label))
    _s, dll = st.classify(g, "0" * 64)
    assert tf.backup_sentence(dll.label, "5.5") == want


@pytest.mark.parametrize("label,want", [
    (b"Thinker Mod v5.4", "  Your Thinker Mod 5.4 files are saved in LongevityMods\\backups\\set"),
    (b"Thinker Mod develop build", "  Your development build of Thinker Mod is saved in LongevityMods\\backups\\set"),
], ids=["version", "development"])
def test_the_summary_backup_line_follows_the_same_rule(tmp_path, label, want):
    g = tmp_path / "game"
    g.mkdir()
    (g / "thinker.dll").write_bytes(_dll(label))
    _s, dll = st.classify(g, "0" * 64)
    prep = types.SimpleNamespace(report=types.SimpleNamespace(added=1, replaced=2, kept_or_merged=0, older_backups=0,
                                                              backup_dir=tmp_path / "set"),
                                 plan=types.SimpleNamespace(kept_alphax=False, ini=None, user_ini=None, actions=[]),
                                 dll=dll, ts="5.5", new=False,
                                 direction=st.direction(dll.label, "5.5"))
    assert want in tf.summary_lines(prep)


def test_the_thinker_downloads_retry_line_names_github(tmp_path, monkeypatch, capsys):
    """User 2026-11-15: "  Could not reach GitHub, trying again (2 of 3)..." for the Thinker download; Longevity
    Vaccine's own downloads keep "the update server"."""
    monkeypatch.setattr(fetch, "_fetch_one", lambda *a, **k: (_ for _ in ()).throw(fetch.FetchError("offline")))
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    pin = tf.compiled_pin()
    with pytest.raises(fetch.FetchError):
        src.fetch_zip(pin, tmp_path)
    out = capsys.readouterr().out
    assert "  Could not reach GitHub, trying again (2 of 3)...\n" in out and "update server" not in out
    with pytest.raises(fetch.FetchError):
        fetch.download("https://longevitymods.com/x.zip", tmp_path / "x.zip")
    assert "  Could not reach the update server, trying again (2 of 3)...\n" in capsys.readouterr().out
