"""The seventh verification (audit-h, of 873c573, 2026-11-16): one regression per finding, each written to fail
first. M1 (a repair's install record), M2 + L1 ("See what's new" from a stale file), L2 (a recovered repair), L3 (our
own build in the "as they were" sentence), L4 (--check lines in a setup run), L5 (thinker.ini). Synthetic Thinker
files stand in for the pinned release (conftest's synthetic_pin)."""
from __future__ import annotations

import json
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
import receipt as rc                # noqa: E402
import thinker_flow as tf           # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
import version as ver               # noqa: E402
from test_arrow_choices import _keys  # noqa: E402
from test_thinker_update import KNOWN, NEW, _folder  # noqa: E402
from test_uninstall_thinker_packs import _installed_thinker, installed_with_thinker  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")
V55 = st.parse_label("Thinker Mod v5.5")


def _record(game: Path) -> dict:
    return json.loads((game / tf.INSTALL_RECORD).read_text(encoding="utf-8"))


def _plant(game: Path, rec: dict) -> None:
    (game / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")


# ---------------------------------------------------------------- M1 / L2: a repair keeps the whole record

def _repair_prep(tmp_path, game: Path, missing: list) -> tf.Prepared:
    """The repair a setup or update run makes: the release planned over the folder as it is, then as_repair."""
    files = {**NEW, "Changelog.md": b"what's new"}
    staged_dir = _folder(tmp_path / "staged-repair", files)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in files}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V55)
    prep = tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), types.SimpleNamespace(label=V55), p, "5.5",
                       st.OTHER)
    tf.as_repair(prep, missing)
    return prep


@pytest.fixture
def changed_then_damaged(tmp_path):
    """Thinker 5.5 put in place by this installer; since then the player edited modmenu.txt and thinker.ini, the
    Datalinks patch rewrote smac_mod/helpx.txt (its stock text in the .longevity.bak), and thinker.exe went."""
    game, _ = _installed_thinker(tmp_path)
    before = tf.read_install_record(game)["files"]
    (game / "modmenu.txt").write_bytes(b"my menu")
    (game / "thinker.ini").write_bytes(b"[thinker]\r\nvideo_mode=3\r\n")
    (game / "smac_mod" / "helpx.txt.longevity.bak").write_bytes(NEW["smac_mod/helpx.txt"])
    (game / "smac_mod" / "helpx.txt").write_bytes(b"new stock help, patched by Longevity Vaccine")
    (game / "thinker.exe").unlink()
    return game, before


def test_a_repair_keeps_every_entry_of_the_record(tmp_path, changed_then_damaged):
    game, before = changed_then_damaged
    prep = _repair_prep(tmp_path, game, ["thinker.exe"])
    tf.commit(prep, route="longevity")
    tf.finish(prep)
    assert (game / "thinker.exe").read_bytes() == NEW["thinker.exe"]
    assert tf.read_install_record(game)["files"] == before         # helpx, the edited files and thinker.ini stay


def test_after_a_repair_also_uninstall_still_removes_the_patched_help_text(tmp_path, changed_then_damaged):
    """H27 against H28: a repair must not make "Also uninstall" leave smac_mod\\helpx.txt silently behind."""
    game, _ = changed_then_damaged
    prep = _repair_prep(tmp_path, game, ["thinker.exe"])
    tf.commit(prep, route="longevity")
    tf.finish(prep)
    tf.remove_thinker(game)
    assert "smac_mod/helpx.txt" in tf.LAST_KEPT                       # named, as without the repair


def test_a_recovered_repair_behaves_like_a_completed_one(tmp_path, changed_then_damaged, capsys):
    """L2 (H1Hb): a repair stopped after its swap. The next run finishes it: no Thinker changelog offer, no
    thinker-update.json rewrite, and the install record keeps every entry."""
    game, before = changed_then_damaged
    offered = json.loads((game / tf.RECORD_FILE).read_text(encoding="utf-8"))
    offered["changelog_offered"] = True                               # the install's own offer was made
    (game / tf.RECORD_FILE).write_text(json.dumps(offered), encoding="utf-8")
    was = (game / tf.RECORD_FILE).read_bytes()
    prep = _repair_prep(tmp_path, game, ["thinker.exe"])
    tf.commit(prep, route="thinker")                                  # killed before finish: the journal stays
    assert tu.journal_path(game).exists()
    assert tf.recover_at_entry(game) == tu.FINISHED
    assert (game / tf.RECORD_FILE).read_bytes() == was                # not rewritten: nothing new to offer
    assert tf.read_install_record(game)["files"] == before


def test_a_recovered_change_that_is_not_a_repair_still_offers_the_changelog(tmp_path):
    from test_thinker_install_review import _first_install_plan
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")
    (game / tf.RECORD_FILE).unlink()
    assert tf.recover_at_entry(game) == tu.FINISHED
    assert json.loads((game / tf.RECORD_FILE).read_text(encoding="utf-8"))["changelog_offered"] is False


# ---------------------------------------------------------------- L3: our own build is not "a different build"

def test_a_failed_repair_download_names_our_own_build(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    dll = types.SimpleNamespace(label=V55, sha256=tu.sha256(game / "thinker.dll"))
    monkeypatch.setattr(st, "classify", lambda g, want: (st.PIN, dll))

    def offline(*a, **k):
        raise fetch.FetchError("no route")
    monkeypatch.setattr(tf.src, "fetch_zip", offline)
    with pytest.raises(ix.InstallerError) as e:
        tf.prepare(game, tf.compiled_pin(), tf.compiled_meta(), "1.0.0", route="A", lv_have="0.9.0",
                   repair=["thinker.exe"])
    assert e.value.message.endswith(" Longevity Vaccine 0.9.0 and your Thinker Mod 5.5 are as they were.")
    assert "different build" not in e.value.message


def test_a_different_build_with_the_same_number_is_still_called_one(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    monkeypatch.setattr(st, "classify", lambda g, want: (st.OFF_PIN, types.SimpleNamespace(label=V55, sha256="1" * 64)))
    monkeypatch.setattr(tf.src, "fetch_zip", lambda *a, **k: (_ for _ in ()).throw(fetch.FetchError("no route")))
    with pytest.raises(ix.InstallerError) as e:
        tf.prepare(game, tf.compiled_pin(), tf.compiled_meta(), "1.0.0", route="A", lv_have="0.9.0")
    assert e.value.message.endswith(" your different build of Thinker Mod 5.5 are as they were.")


# ---------------------------------------------------------------- L4: no --check lines outside --check

def _stop_download(monkeypatch):
    monkeypatch.setattr(fetch, "download", lambda *a, **k: (_ for _ in ()).throw(fetch.FetchError("stop")))


def _cache(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(fetch, "fallback_cache_dir", lambda game_dir: cache)


@windows
@pytest.mark.parametrize("linked", ["LongevityMods", "LongevityMods/staging"])
def test_a_setup_run_with_a_linked_folder_prints_no_check_lines(tmp_path, monkeypatch, capsys, linked):
    import _winapi
    g = tmp_path / "game"
    link = g.joinpath(*linked.split("/"))
    link.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "players").mkdir()
    _winapi.CreateJunction(str(tmp_path / "players"), str(link))
    _cache(monkeypatch, tmp_path)
    _stop_download(monkeypatch)
    with pytest.raises(ix.InstallerError):
        inst.fetch_manifest(g, quick=True)                            # module_catalogue's fetch
    assert "--check" not in capsys.readouterr().err


@windows
def test_check_says_once_that_staging_is_a_link_and_never_that_the_folder_is_not_writable(tmp_path, monkeypatch,
                                                                                            capsys):
    import _winapi
    g = tmp_path / "game"
    (g / "LongevityMods").mkdir(parents=True)
    (tmp_path / "players").mkdir()
    _winapi.CreateJunction(str(tmp_path / "players"), str(g / "LongevityMods" / "staging"))
    _cache(monkeypatch, tmp_path)
    _stop_download(monkeypatch)
    with pytest.raises(ix.InstallerError):
        inst.fetch_manifest(g, quick=True, check=True)
    err = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("--check:")]
    assert len(err) == 1 and "is a link" in err[0] and "not writable" not in err[0], err


def test_check_still_says_when_the_folder_is_not_writable(tmp_path, monkeypatch, capsys):
    g = tmp_path / "game"
    g.mkdir()
    _cache(monkeypatch, tmp_path)
    _stop_download(monkeypatch)
    monkeypatch.setattr(fetch, "assert_writable", lambda d: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(ix.InstallerError):
        inst.fetch_manifest(g, quick=True, check=True)
    assert "is not writable" in capsys.readouterr().err
    with pytest.raises(ix.InstallerError):
        inst.fetch_manifest(g, quick=True)
    assert "--check" not in capsys.readouterr().err


def test_check_main_asks_for_its_lines():
    import inspect
    assert "fetch_manifest(game_dir, args.manifest, args.offline, quick=True, check=True)" in \
        inspect.getsource(inst)


# ---------------------------------------------------------------- M2 / L1: "See what's new" is recomputed

OLD = "0.9.0"
NOW = ver.VERSION


def _game(tmp_path) -> Path:
    g = tmp_path / "game"
    (g / "LongevityMods").mkdir(parents=True)
    return g


def _pending(g: Path, data: bytes) -> Path:
    p = inst._whats_new_path(g)
    p.write_bytes(data)
    return p


def test_the_kept_version_names_the_run_it_belongs_to(tmp_path):
    g = _game(tmp_path)
    inst.remember_whats_new(g, OLD, NOW)
    assert inst._whats_new_path(g).read_text(encoding="ascii") == f"{OLD}|{NOW}"


def test_the_retry_of_a_run_that_failed_past_its_receipt_shows_the_line(tmp_path):
    g = _game(tmp_path)
    inst.remember_whats_new(g, OLD, NOW)
    inst.finish_whats_new(g, NOW, NOW)                     # the receipt said NOW when the retry started
    assert inst._WHATS_NEW == NOW and not inst._whats_new_path(g).exists()


@pytest.mark.parametrize("before,now,data", [
    (ver.UNKNOWN, NOW, f"{OLD}|{NOW}"),                    # a fresh install (W03/W13): no receipt when it started
    ("9.9.9", NOW, f"{OLD}|9.9.9"),                        # a downgrade (W14)
    (NOW, NOW, OLD),                                       # a planted or older bare version (W10)
    (NOW, NOW, f"{OLD}|8.8.8"),                            # kept for another version
    (NOW, NOW, "garbage"),
    (NOW, NOW, f"{NOW}|{NOW}"),                            # nothing older
], ids=["fresh", "downgrade", "bare", "other-version", "garbage", "same"])
def test_the_line_shows_only_when_the_run_started_from_an_older_version(tmp_path, before, now, data):
    g = _game(tmp_path)
    _pending(g, data.encode("ascii"))
    inst.finish_whats_new(g, before, now)
    assert inst._WHATS_NEW is None and not inst._whats_new_path(g).exists()


def test_utf16_content_is_discarded_and_deleted(tmp_path):
    g = _game(tmp_path)
    _pending(g, f"{OLD}|{NOW}".encode("utf-16"))
    inst.finish_whats_new(g, NOW, NOW)
    assert inst._WHATS_NEW is None and not inst._whats_new_path(g).exists()


def test_without_a_file_the_live_version_decides(tmp_path):
    g = _game(tmp_path)
    inst.finish_whats_new(g, OLD, NOW)
    assert inst._WHATS_NEW == NOW


def test_the_runs_that_finish_it_always_call_it():
    import inspect
    import bootstrap as bs
    rest, upd, run, boot = (inspect.getsource(f) for f in (inst._install_rest, inst.do_update, bs.run, bs._run_installer))
    assert "take_whats_new" not in inspect.getsource(inst) + inspect.getsource(bs)
    assert rest.index("remember_whats_new(") < rest.index("rc.write(") < rest.index("finish_whats_new(game_dir, base_before")
    assert "if base_before != ver.UNKNOWN" not in rest                    # a fresh install deletes a leftover too
    assert upd.index("remember_whats_new(") < upd.index("rc.write(") < upd.rindex("finish_whats_new(game_dir, base_version")
    # L1: the retry that finds nothing to update (W21, W23) shows the line and deletes the file.
    idle = upd[upd.index("rc.note_check(game_dir)      # a completed check"):upd.index('_VERDICT = ("ALREADY UP TO DATE"')]
    assert "finish_whats_new(game_dir, base_version, base_version)" in idle
    boot_idle = run[run.index('ix.say(f"  already current'):run.index('_VERDICT = ("ALREADY UP TO DATE"')]
    assert "finish_whats_new(" in boot_idle
    assert "finish_whats_new(game_dir, before, after)" in boot


def test_an_up_to_date_verdict_still_ends_with_the_armed_line(monkeypatch, capsys):
    """The idle verdicts print no play note: the armed line alone closes them (install and the bootstrap)."""
    import bootstrap as bs
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(bs, "_NOTE_ARGS", None)
    inst.note_whats_new(OLD, NOW)
    inst._success_after()
    bs._closing_note()
    out = capsys.readouterr().out.splitlines()
    assert out == [inst.whats_new_line(NOW)] * 2


def test_the_uninstall_deletes_the_kept_version(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    (game / "LongevityMods").mkdir(exist_ok=True)
    p = _pending(game, f"{OLD}|{NOW}".encode("ascii"))
    inst._load_modules()
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    with pytest.raises(ix.InstallerError):
        inst.do_uninstall(game, types.SimpleNamespace(no_prompt=False, force=False))
    assert not p.exists()


# ---------------------------------------------------------------- L5: thinker.ini and the record

def test_a_planted_record_without_thinker_exe_is_never_acted_on(tmp_path, monkeypatch):
    """H26: {thinker.dll: the pin's, thinker.ini: anything} over a hand-installed 5.5 with the player's settings."""
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    (game / "thinker.ini").write_bytes(b"[thinker]\r\nmine=1\r\n")
    _plant(game, {"pin": rec["pin"], "files": {"thinker.dll": rec["files"]["thinker.dll"], "thinker.ini": "0" * 64}})
    _keys(monkeypatch, "down", "enter")                        # "Also", were it asked
    if tf.ask_uninstall_thinker(game):
        tf.remove_thinker(game)
    assert (game / "thinker.ini").read_bytes() == b"[thinker]\r\nmine=1\r\n"
    assert (game / "thinker.dll").is_file() and (game / "thinker.exe").is_file()


def test_a_marked_record_without_thinker_dll_present_removes_nothing(tmp_path, monkeypatch):
    """H2A: remove:true, no thinker.dll in the folder, --no-prompt: 24 files went."""
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    rec["remove"] = True
    _plant(game, rec)
    (game / "thinker.dll").unlink()
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    if tf.ask_uninstall_thinker(game):
        tf.remove_thinker(game)
    assert (game / "thinker.exe").is_file() and (game / "basenames" / "hive.txt").is_file()
    assert (game / "thinker.ini").is_file()


def test_thinker_ini_is_kept_when_thinker_exe_is_not_the_releases(tmp_path, monkeypatch):
    """The question is never put while thinker.exe is a build of the player's: removing thinker.dll would leave it
    without its dll."""
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.exe").write_bytes(b"the player's own launcher")
    monkeypatch.setattr(ix, "can_ask", lambda: pytest.fail("asked although thinker.exe is not the release's"))
    assert tf.ask_uninstall_thinker(game) is False


def test_without_thinker_exe_in_the_folder_thinker_ini_stays(tmp_path, monkeypatch):
    """The record is ours and thinker.exe is gone (the player deleted it): Thinker's own files go, the settings file
    -- removed only together with a whole, release-identical thinker.dll AND thinker.exe -- stays."""
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.exe").unlink()
    (game / "thinker.ini").write_bytes(b"[thinker]\r\nmine=1\r\n")
    _keys(monkeypatch, "down", "enter")
    assert tf.ask_uninstall_thinker(game) is True
    tf.remove_thinker(game)
    assert not (game / "thinker.dll").exists() and (game / "thinker.ini").is_file()


def test_our_whole_release_still_takes_an_edited_thinker_ini(tmp_path, monkeypatch):
    """The user's ruling stands for the installer's own install: thinker.ini goes even when edited."""
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.ini").write_bytes(b"[thinker]\r\nmine=1\r\n")
    _keys(monkeypatch, "down", "enter")
    assert tf.ask_uninstall_thinker(game) is True
    removed, failed = tf.remove_thinker(game)
    assert failed == 0 and not (game / "thinker.ini").exists() and not (game / "thinker.dll").exists()


def test_a_marked_record_finishes_a_locked_thinker_ini(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.ini").write_bytes(b"[thinker]\r\nmine=1\r\n")
    with open(game / "thinker.ini", "rb"):
        assert tf.remove_thinker(game)[1] == 1
    # thinker.ini goes last (audit-i MEDIUM-1): thinker.dll is already gone, the marked record keeps its entry
    assert _record(game).get("remove") is True and "thinker.dll" in _record(game)["files"]
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert tf.ask_uninstall_thinker(game) is True                     # finished without asking
    assert tf.remove_thinker(game)[1] == 0
    assert not (game / "thinker.ini").exists() and not (game / "thinker.dll").exists()
