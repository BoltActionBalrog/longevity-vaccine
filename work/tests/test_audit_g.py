"""The sixth verification (audit-g, of 1b70fc5..19dfe03, 2026-11-16): one regression per finding, each written to
fail first. HIGH-1 (a record carrying the live files' hashes), LOW-1..LOW-9. Synthetic Thinker files stand in for
the pinned release (conftest's synthetic_pin)."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
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
import safe_fs                      # noqa: E402
import thinker_flow as tf           # noqa: E402
import thinker_update as tu         # noqa: E402
import version as ver               # noqa: E402
from test_arrow_choices import _keys  # noqa: E402
from test_thinker_install_review import _first_install_plan  # noqa: E402
from test_uninstall_thinker_packs import _installed_thinker, installed_with_thinker  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")


def _junction(link: Path, target: Path) -> None:
    import _winapi
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))


def _record(game: Path) -> dict:
    return json.loads((game / tf.INSTALL_RECORD).read_text(encoding="utf-8"))


def _plant(game: Path, rec: dict) -> None:
    (game / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")


# ---------------------------------------------------------------- HIGH-1: the record's hashes are the pin's

@pytest.fixture
def players_thinker(tmp_path):
    """The player's own Thinker (5.4), kept: every pin path present, none of them the release's bytes."""
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    for rel in rec["files"]:
        game.joinpath(*rel.split("/")).write_bytes(b"Thinker 5.4's " + rel.encode())
    planted = {"pin": rec["pin"], "files": {rel: tu.sha256(game.joinpath(*rel.split("/"))) for rel in rec["files"]}}
    return game, planted


@pytest.mark.parametrize("mark", [False, True], ids=["asked", "marked"])
def test_a_record_of_the_live_files_hashes_never_removes_the_players_thinker(players_thinker, monkeypatch, mark):
    game, planted = players_thinker
    if mark:
        planted["remove"] = True
    _plant(game, planted)
    _keys(monkeypatch, "down", "enter")                        # "Also", were it asked
    assert tf.read_install_record(game) is None
    if tf.ask_uninstall_thinker(game):
        tf.remove_thinker(game)
    assert (game / "thinker.dll").read_bytes().startswith(b"Thinker 5.4") and (game / "thinker.exe").is_file()


def test_the_question_compares_with_the_pins_dll(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    real = tf._pin_files
    monkeypatch.setattr(tf, "_pin_dll", lambda pin_id: "f" * 64)  # the release's dll is some other build
    monkeypatch.setattr(ix, "can_ask", lambda: pytest.fail("asked although the live dll is not the release's"))
    assert tf.ask_uninstall_thinker(game) is False
    assert real is tf._pin_files


# ---------------------------------------------------------------- LOW-5: one spelling of every key

def test_a_record_spelled_in_another_case_is_read_in_the_pins_spelling(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    rec["files"] = {(k.upper() if k == "thinker.dll" else k): v for k, v in rec["files"].items()}
    _plant(game, rec)
    assert "thinker.dll" in tf.read_install_record(game)["files"]
    _keys(monkeypatch, "down", "enter")
    assert tf.ask_uninstall_thinker(game) is True


def test_two_spellings_of_one_file_is_not_a_record(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    rec["files"]["THINKER.DLL"] = rec["files"]["thinker.dll"]
    _plant(game, rec)
    assert tf.read_install_record(game) is None


# ---------------------------------------------------------------- LOW-1: a link is not a connection failure

LONG = ("Sid Meier's Alpha Centauri Planetary Pack " * 3).strip()


@windows
def test_the_manifest_downloads_link_refusal_is_the_approved_line_uncut(tmp_path):
    g = tmp_path / LONG
    _junction(g / "LongevityMods", tmp_path / "players")
    with pytest.raises(ix.InstallerError) as e:
        inst.fetch_manifest(g)
    assert e.value.message == f"{g / 'LongevityMods'} is a link to another folder, so nothing was downloaded there."
    assert "connection" not in (e.value.remedy or "") + (e.value.disk_note or "") and e.value.title != "UPDATE FAILED"
    assert not (tmp_path / "players" / "staging").exists()      # nothing created through the link


@windows
def test_the_thinker_downloads_link_refusal_is_the_approved_line(tmp_path):
    g = tmp_path / LONG
    _junction(g / "LongevityMods", tmp_path / "players")
    with pytest.raises(ix.InstallerError) as e:
        tf.prepare(g, tf.compiled_pin(), tf.compiled_meta(), "1.0.0")
    assert e.value.message == f"{g / 'LongevityMods'} is a link to another folder, so nothing was downloaded there."
    assert not e.value.remedy


@windows
def test_the_new_installers_link_refusal_is_the_approved_line(tmp_path):
    import bootstrap as bs
    g = tmp_path / "game"
    _junction(g / "LongevityMods", tmp_path / "players")
    with pytest.raises(ix.InstallerError) as e:
        bs._download_new_payload(g, {"url": "https://x/i.zip", "sha256": "0" * 64, "size": 1}, "9.9.9",
                                 types.SimpleNamespace(manifest=None))
    assert e.value.message.endswith("is a link to another folder, so nothing was downloaded there.")
    assert not e.value.remedy


def test_link_error_is_a_fetch_error():
    assert issubclass(fetch.LinkError, fetch.FetchError)


# ---------------------------------------------------------------- LOW-2: the record survives a stop in finish

def test_a_ctrl_c_as_the_journal_goes_keeps_the_record(tmp_path, monkeypatch):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")
    monkeypatch.setattr(tf.tu, "finish", lambda g: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        tf.finish(prep)
    assert tf.read_install_record(game)["files"]["thinker.dll"] == tu.sha256(game / "thinker.dll")


# ---------------------------------------------------------------- LOW-3: "See what's new" survives a retry

def test_the_version_before_is_kept_until_a_run_finishes(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    inst.remember_whats_new(g, "0.9.0", ver.VERSION)
    assert inst._WHATS_NEW is None                               # kept, not yet shown
    inst.finish_whats_new(g, ver.VERSION, ver.VERSION)           # the retry that finishes (audit-h M2's rule)
    assert inst._WHATS_NEW == ver.VERSION and not inst._whats_new_path(g).exists()


@pytest.mark.parametrize("before", [ver.VERSION, ver.UNKNOWN, "9.9.9"])
def test_nothing_is_kept_when_the_version_does_not_go_up(tmp_path, before):
    g = tmp_path / "game"
    g.mkdir()
    inst.remember_whats_new(g, before, ver.VERSION)
    assert not inst._whats_new_path(g).exists()


def test_install_and_update_keep_it_before_the_receipt_and_take_it_on_success():
    import inspect
    rest, upd = inspect.getsource(inst._install_rest), inspect.getsource(inst.do_update)
    assert rest.index("remember_whats_new(") < rest.index("rc.write(") < rest.index("finish_whats_new(")
    assert upd.index("remember_whats_new(") < upd.index("rc.write(") < upd.rindex("finish_whats_new(")


def test_the_bootstrap_retry_still_ends_with_whats_new(monkeypatch, tmp_path):
    """The failed run wrote the receipt (base = this version) and kept 0.9.0; the retry's worker finishes."""
    from test_whats_new_line import _args, _bootstrap_world
    bs, g = _bootstrap_world(monkeypatch, tmp_path, after=ver.VERSION, code=ix.EXIT_OK)
    rc.write(g, target_id="pracx", modules={"base": {"version": ver.VERSION}})
    inst.remember_whats_new(g, "0.9.0", ver.VERSION)
    bs._run_installer(_SCRIPTS, g, _args())
    assert inst._WHATS_NEW == ver.VERSION


def test_a_fresh_install_never_takes_a_leftover(tmp_path):
    """Now by the rule itself (audit-h M2): a run with no receipt when it started arms nothing and deletes the file."""
    g = tmp_path / "game"
    g.mkdir()
    inst.remember_whats_new(g, "0.9.0", ver.VERSION)
    inst.finish_whats_new(g, ver.UNKNOWN, ver.VERSION)
    assert inst._WHATS_NEW is None and not inst._whats_new_path(g).exists()


# ---------------------------------------------------------------- LOW-4: a marked record and the player's dll

def test_a_marked_record_with_the_players_dll_says_thinker_stays(installed_with_thinker, monkeypatch, capsys):
    g = installed_with_thinker
    rec = _record(g)
    rec["remove"] = True
    _plant(g, rec)
    (g / "thinker.dll").write_bytes(b"the player's own build")
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    out = capsys.readouterr().out
    assert "stays installed and works without Longevity Vaccine" in out
    assert (g / "thinker.exe").is_file() and not (g / tf.INSTALL_RECORD).exists()


# ---------------------------------------------------------------- LOW-6: the launcher stays with the dll

def test_a_locked_file_keeps_thinker_exe_and_thinker_dll(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    with open(game / "basenames" / "hive.txt", "rb"):
        removed, failed = tf.remove_thinker(game)
    assert failed == 1 and (game / "thinker.exe").is_file() and (game / "thinker.dll").is_file()
    rec = tf.read_install_record(game)                    # the FULL record, marked (audit-j MEDIUM-2)
    assert rec["remove"] is True and {"basenames/hive.txt", "thinker.exe", "thinker.dll", "thinker.ini",
                                      "modmenu.txt"} <= set(rec["files"])


def test_nothing_to_uninstall_clears_the_record_nobody_acted_on(tmp_path, monkeypatch):
    game, _ = _installed_thinker(tmp_path)
    inst._load_modules()
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    with pytest.raises(ix.InstallerError) as e:
        inst.do_uninstall(game, types.SimpleNamespace(no_prompt=False, force=False))
    assert e.value.message.startswith("Nothing to uninstall")
    assert not (game / tf.INSTALL_RECORD).exists()


# ---------------------------------------------------------------- LOW-7 / LOW-8: logs and --check

@windows
def test_logs_are_never_written_through_a_link(tmp_path, monkeypatch):
    g = tmp_path / "game"
    _junction(g / "LongevityMods", tmp_path / "players")
    assert inst._log_path(g, "patch").parent == Path(tempfile.gettempdir())
    monkeypatch.setattr(inst, "_CRASH_LOG_GAME_DIR", g)
    assert inst.crash_log_dir() == Path(tempfile.gettempdir())
    assert not (tmp_path / "players" / "logs").exists()


@windows
def test_check_uses_the_per_user_cache_when_staging_is_a_link(tmp_path, monkeypatch):
    g = tmp_path / "game"
    _junction(g / "LongevityMods" / "staging", tmp_path / "players")
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(fetch, "fallback_cache_dir", lambda game_dir: cache)
    seen = []

    def spy(url, dest, **kw):
        seen.append(Path(dest).parent)
        raise fetch.FetchError("stop")
    monkeypatch.setattr(fetch, "download", spy)
    with pytest.raises(ix.InstallerError):
        inst.fetch_manifest(g, quick=True)
    assert seen and all(d == cache for d in seen)
    assert not any((tmp_path / "players").iterdir())


# ---------------------------------------------------------------- LOW-9: only junctions and symlinks are links

def _lstat_with(monkeypatch, tag):
    st_ = types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400, st_reparse_tag=tag)
    monkeypatch.setattr(safe_fs.os, "lstat", lambda p: st_)


@pytest.mark.parametrize("tag,link", [(0xA0000003, True), (0xA000000C, True),     # junction, symlink
                                      (0x9000001A, False), (0x80000013, False),    # OneDrive placeholder, dedup
                                      (0x80000017, False)])                        # WOF-compressed
def test_only_a_junction_or_a_symlink_is_a_link(monkeypatch, tag, link):
    _lstat_with(monkeypatch, tag)
    assert safe_fs.is_link(Path("x")) is link
    assert tu._is_reparse(Path("x")) is link and inst._is_link(Path("x")) is link


def test_a_reparse_point_that_leaves_the_folder_is_still_refused(tmp_path, monkeypatch):
    g = tmp_path / "game"
    (g / "sub").mkdir(parents=True)
    real_resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda self, *a, **k: tmp_path / "elsewhere" if self.name == "sub"
                        else real_resolve(self, *a, **k))
    assert safe_fs.link_on_path(g, g / "sub" / "x.txt") is True


# ---------------------------------------------------------------- LOW-6, W1 run 1: a link-only failure's remedy

LINK_REMEDY = "Replace the link named above with an ordinary folder, then run the uninstall again to finish."


def _also(monkeypatch):
    from test_uninstall_thinker_packs import _console
    _console(monkeypatch, ["down", "enter"])
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])


def _tree(g: Path) -> dict:
    return {p.relative_to(g).as_posix(): p.read_bytes() for p in g.rglob("*") if p.is_file()}


@windows
def test_a_link_on_the_way_refuses_the_uninstall_up_front(installed_with_thinker, monkeypatch):
    """User ruling 2026-11-17 (D3(c)): refused before any change, with the approved remedy (the old sentence minus
    "to finish"). The message and the detail line for a link to a folder are user-approved too (2026-11-17)."""
    import _winapi
    g = installed_with_thinker
    inside = g / "elsewhere-inside"
    (g / "smac_mod").rename(inside)
    _winapi.CreateJunction(str(inside), str(g / "smac_mod"))
    _also(monkeypatch)
    before = _tree(g)
    with pytest.raises(ix.InstallerError) as e:
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    assert e.value.title == "UNINSTALL NOT STARTED"
    assert e.value.remedy == "replace the link named above with an ordinary folder, then run the uninstall again."
    assert e.value.detail == "  smac_mod: a link to another folder"       # the link itself (audit of 356c8f8, L3)
    assert _tree(g) == before


@windows
def test_an_uninstall_whose_only_failures_are_links_says_to_replace_the_link(installed_with_thinker, monkeypatch):
    """The fallback for a link made after the up-front check (bypassed here). User-approved 2026-11-16: in that case
    only, in place of the general remedy."""
    import _winapi
    g = installed_with_thinker
    inside = g / "elsewhere-inside"
    (g / "smac_mod").rename(inside)
    _winapi.CreateJunction(str(inside), str(g / "smac_mod"))
    _also(monkeypatch)
    monkeypatch.setattr(inst, "uninstall_links", lambda game_dir, thinker_too: [])
    inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    title, body = inst._VERDICT
    assert title == "UNINSTALL INCOMPLETE"
    assert f"(see the warnings above). {LINK_REMEDY}" in body
    assert "Close the game" not in body


def test_any_other_failure_keeps_its_remedy(installed_with_thinker, monkeypatch):
    """The fallback for a lock taken after the up-front check (bypassed here): master's remedy."""
    import preflight as pfm
    g = installed_with_thinker
    _also(monkeypatch)
    monkeypatch.setattr(pfm, "probe", lambda p, modes: "")
    with open(g / "thinker.exe", "rb"):
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    body = inst._VERDICT[1]
    assert "Close the game and any program that has those files open, make sure they are not read-only, and run --uninstall again to finish." in body and LINK_REMEDY not in body
