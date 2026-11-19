"""The audit of 2a46d18..9da2804 (audit-f, 2026-11-15): one regression per finding, each written to fail first.
H1/H2 (an edited, planted or marked record deleting files that are not ours), M1-M4, L1-L3, and the user's ruling
"Leave edited files" (M2) with its approved "Left in place" lines. The whole-uninstall cases run do_uninstall on a
real setup run (installed_with_thinker): a console-less run is the `< NUL` case."""
from __future__ import annotations

import inspect
import json
import socket
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
import thinker_flow as tf           # noqa: E402
import thinker_update as tu         # noqa: E402
from test_thinker_install_review import _first_install_plan  # noqa: E402
from test_thinker_update import NEW  # noqa: E402
from test_uninstall_thinker_packs import _console, _installed_thinker, _pack, installed_with_thinker  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")


def _record(game: Path) -> dict:
    return json.loads((game / tf.INSTALL_RECORD).read_text(encoding="utf-8"))


def _plant(game: Path, rec: dict) -> None:
    (game / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")


# ---------------------------------------------------------------- H1(a): only the pinned release's own files

@pytest.mark.parametrize("rel", ["ALPHAX.TXT", "Alphax.txt", "THINKER_USER.INI", "smac_mod/alphax.txt",
                                 "smac_mod/ALPHAX.TXT", "prac.dll", "prax.dll", "ddraw.dll", "terranx_mod.exe",
                                 "x.SAV", "Icons.pcx", "terranx.exe.bak", "longevity-install.json",
                                 "smac_mod/MyMod.txt"])
def test_a_record_naming_a_file_outside_the_pinned_release_is_never_acted_on(tmp_path, rel):
    game, _ = _installed_thinker(tmp_path)
    target = game.joinpath(*rel.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"the player's or the game's")
    rec = _record(game)
    rec["files"][rel] = tu.sha256(target)                   # even with the live file's own hash
    _plant(game, rec)
    assert tf.read_install_record(game) is None
    assert tf.remove_thinker(game) == (0, 0)
    assert target.read_bytes() == b"the player's or the game's" and (game / "thinker.dll").is_file()


def test_a_record_naming_another_release_is_never_acted_on(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    rec["pin"] = "5.4.0"
    _plant(game, rec)
    assert tf.read_install_record(game) is None and tf.remove_thinker(game) == (0, 0)
    assert (game / "thinker.dll").is_file()


# ---------------------------------------------------------------- H1(b) / M2: only byte-identical files go

def test_an_edited_release_file_is_left_with_its_folder_and_thinker_ini_still_goes(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    (game / "basenames" / "hive.txt").write_bytes(b"my own base names")
    (game / "modmenu.txt").write_bytes(b"my menu")
    (game / "thinker.ini").write_bytes(b"[thinker]\r\nedited=1\r\n")
    removed, failed = tf.remove_thinker(game)
    assert failed == 0
    assert (game / "basenames" / "hive.txt").read_bytes() == b"my own base names"
    assert (game / "modmenu.txt").read_bytes() == b"my menu"
    assert not (game / "thinker.ini").exists() and not (game / "thinker.dll").exists()
    assert sorted(tf.LAST_KEPT) == ["basenames/hive.txt", "modmenu.txt"]
    assert not (game / tf.INSTALL_RECORD).exists()          # only edited files remain: the record goes


def test_the_kept_lines_read_as_approved():
    tf.LAST_KEPT[:] = ["smac_mod/helpx.txt", "modmenu.txt", "thinker.ini"]
    assert tf.kept_lines() == ["smac_mod\\helpx.txt   - a Thinker Mod file you changed, so it was kept",
                               "modmenu.txt          - a Thinker Mod file you changed, so it was kept",
                               # named too since audit-k LOW-2 (an edited one: the existing row)
                               "thinker.ini          - a Thinker Mod file you changed, so it was kept"]
    tf.LAST_KEPT[:] = []


# ---------------------------------------------------------------- H2: the mark never removes what is not ours

def test_a_marked_record_never_removes_a_thinker_the_player_installed_since(tmp_path, monkeypatch):
    """P03: an earlier "Also" left the mark; the player hand-installs another Thinker; a `< NUL` uninstall."""
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    rec["remove"] = True
    _plant(game, rec)
    (game / "thinker.dll").write_bytes(b"Thinker 5.4, by hand")
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    if tf.ask_uninstall_thinker(game):
        tf.remove_thinker(game)
    assert (game / "thinker.dll").read_bytes() == b"Thinker 5.4, by hand"
    assert (game / "thinker.exe").is_file() and (game / "basenames" / "hive.txt").is_file()
    # The question itself changes nothing (audit of 356c8f8, H1): do_uninstall drops the record past its up-front
    # check (test_audit_356c8f8's test_the_unrefused_run_still_drops_that_record_and_keeps_the_players_thinker).
    assert (game / tf.INSTALL_RECORD).exists()


def test_a_successful_install_or_update_clears_the_mark(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    rec["remove"] = True
    _plant(game, rec)
    (game / "thinker.exe").unlink()                          # W9: a part-finished "Also" already took it
    tf.settle_install_record(game)
    after = _record(game)
    # the mark goes; thinker.exe stays listed, so the run's repair question can put it back (audit-j MEDIUM-2)
    assert "remove" not in after and "thinker.exe" in after["files"] and "thinker.dll" in after["files"]
    assert tf.missing_release_files(game) == ["thinker.exe"]


def test_the_mark_goes_with_the_record_when_thinker_dll_is_not_ours(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    rec["remove"] = True
    _plant(game, rec)
    (game / "thinker.dll").unlink()
    tf.settle_install_record(game)
    assert not (game / tf.INSTALL_RECORD).exists()


def test_install_and_update_both_settle_the_record():
    assert "settle_install_record(game_dir)" in inspect.getsource(inst._install_rest)
    assert "settle_install_record(game_dir)" in inspect.getsource(inst.do_update)


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows junction")
def test_a_file_behind_a_link_keeps_the_full_marked_record(tmp_path, monkeypatch, capsys):
    """P23: a junction in the folder: the run cannot finish. Audit-j MEDIUM-2 (superseding "ask again"): the FULL
    record keeps its mark, as after any partial failure, and the next uninstall finishes unasked -- its verdict says to
    replace the link (user-approved 2026-11-16). The warning names the path with backslashes (L2)."""
    import _winapi
    game, _ = _installed_thinker(tmp_path)
    elsewhere = game / "elsewhere-inside"                    # P23: an INNER junction (outside: the record is invalid)
    (game / "smac_mod").rename(elsewhere)
    _winapi.CreateJunction(str(elsewhere), str(game / "smac_mod"))
    removed, failed = tf.remove_thinker(game)
    assert failed == 1 and (elsewhere / "helpx.txt").is_file()
    assert (game / "thinker.dll").is_file()                  # M3: never half-removed
    assert "  WARNING: smac_mod\\helpx.txt goes through a link, so it was left alone." in capsys.readouterr().out
    rec = tf.read_install_record(game)
    assert rec is not None and rec.get("remove") is True and "smac_mod/helpx.txt" in rec["files"]
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert tf.ask_uninstall_thinker(game) is True            # finished unasked, as a locked file's


# ---------------------------------------------------------------- M1: the record holds the whole release in place

def test_the_record_holds_the_release_files_that_were_already_identical(tmp_path):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ", "thinker.exe": NEW["thinker.exe"],
                                                "basenames/hive.txt": NEW["basenames/hive.txt"]})
    tf.commit(prep, route="fresh")
    tf.finish(prep)
    files = tf.read_install_record(game)["files"]
    assert {"thinker.exe", "basenames/hive.txt", "thinker.dll"} <= set(files)
    tf.remove_thinker(game)
    assert not (game / "thinker.exe").exists() and not (game / "basenames").exists()


# ---------------------------------------------------------------- M3: thinker.dll last, and only when all else went

def test_a_locked_file_keeps_thinker_dll(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    with open(game / "thinker.exe", "rb"):
        removed, failed = tf.remove_thinker(game)
    assert failed == 1 and (game / "thinker.dll").is_file() and (game / "thinker.exe").is_file()
    rec = tf.read_install_record(game)
    # the FULL record keeps its mark (audit-j MEDIUM-2), thinker.ini with it (audit-i MEDIUM-1)
    assert rec.get("remove") and {"thinker.exe", "thinker.dll", "thinker.ini", "basenames/hive.txt"} <= set(rec["files"])
    assert tf.remove_thinker(game) == (3, 0) and not (game / "thinker.dll").exists()


def test_the_stays_line_never_follows_a_chosen_also(tmp_path):
    game, _ = _installed_thinker(tmp_path)
    assert any("stays installed" in ln for ln in tf.uninstall_lines(game))
    assert not any("stays installed" in ln for ln in tf.uninstall_lines(game, also=True))


def test_a_locked_thinker_dll_after_also_never_says_thinker_stays(installed_with_thinker, monkeypatch, capsys):
    """The fallback for a lock the up-front check cannot foresee (taken after it: the check is bypassed here); with
    the check, the run refuses before any change (test_uninstall_plan, user ruling 2026-11-17)."""
    import preflight as pfm
    g = installed_with_thinker
    _console(monkeypatch, ["down", "enter"])
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    monkeypatch.setattr(pfm, "probe", lambda p, modes: "")
    with open(g / "thinker.dll", "rb"):
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    out = capsys.readouterr().out
    assert "stays installed" not in out and "  removed Thinker Mod" not in out
    assert inst._VERDICT[0] == "UNINSTALL INCOMPLETE"


# ---------------------------------------------------------------- M2 + the approved header, in the whole uninstall

def test_the_uninstall_lists_an_edited_thinker_file_it_kept(installed_with_thinker, monkeypatch, capsys):
    g = installed_with_thinker
    (g / "modmenu.txt").write_bytes(b"my menu")
    _console(monkeypatch, ["down", "enter"])
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    assert inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False)) == ix.EXIT_OK
    out = capsys.readouterr().out
    assert "\n  Left in place:\n" in out and "deliberately" not in out
    assert "    modmenu.txt          - a Thinker Mod file you changed, so it was kept\n" in out
    assert (g / "modmenu.txt").read_bytes() == b"my menu" and not (g / "thinker.dll").exists()


def test_without_also_no_kept_lines(installed_with_thinker, monkeypatch, capsys):
    g = installed_with_thinker
    (g / "modmenu.txt").write_bytes(b"my menu")
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    out = capsys.readouterr().out
    assert "\n  Left in place:\n" in out and "you changed, so it was kept" not in out


# ---------------------------------------------------------------- M4: a second partial failure is still INCOMPLETE

def test_a_pack_file_locked_across_two_runs_stays_incomplete_and_keeps_the_receipt(installed_with_thinker,
                                                                                   monkeypatch):
    # the fallback for a lock taken after the up-front check (bypassed here; with it the run refuses up front)
    import preflight as pfm
    g = installed_with_thinker
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    monkeypatch.setattr(pfm, "probe", lambda p, modes: "")
    args = types.SimpleNamespace(no_prompt=False, force=False)
    with open(g / "movies" / "hd" / "angels.mp4", "rb"):
        inst.do_uninstall(g, args)
        assert inst._VERDICT[0] == "UNINSTALL INCOMPLETE" and (g / rc.JSON_NAME).is_file()
        try:
            inst.do_uninstall(g, args)
        except ix.InstallerError as e:
            pytest.fail(f"the second run refused: {e.message}")
    assert inst._VERDICT[0] == "UNINSTALL INCOMPLETE" and (g / rc.JSON_NAME).is_file()


# ---------------------------------------------------------------- L3: no "removed" line for nothing removed

def test_no_removed_line_when_nothing_was_left_to_remove(tmp_path, capsys):
    """RW8: killed at the record clear -- every file already gone."""
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    for rel in rec["files"]:
        game.joinpath(*rel.split("/")).unlink()
    assert tf.remove_thinker(game) == (0, 0)
    assert "removed Thinker Mod" not in capsys.readouterr().out
    assert not (game / tf.INSTALL_RECORD).exists()


# ---------------------------------------------------------------- L1: the guard

@pytest.mark.parametrize("host,local", [("127.0.0.1", True), ("127.5.6.7", True), ("::1", True), ("localhost", True),
                                        ("127.example.invalid", False), ("10.0.0.1", False),
                                        ("example.invalid", False)])
def test_the_guard_parses_the_address(host, local):
    import conftest
    assert conftest._loopback((host, 80)) is local


def _blocked(call) -> list:
    import conftest
    before = len(conftest._NET_TRIES)
    with pytest.raises(OSError):
        call()
    tried = conftest._NET_TRIES[before:]
    del conftest._NET_TRIES[before:]                          # recorded on purpose: not this test's failure
    return tried


def test_the_guard_refuses_connect_ex_and_name_lookups():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert _blocked(lambda: s.connect_ex(("192.0.2.1", 9)))
    finally:
        s.close()
    assert _blocked(lambda: socket.getaddrinfo("example.invalid", 443))
    assert _blocked(lambda: socket.gethostbyname("example.invalid"))
    assert socket.getaddrinfo("127.0.0.1", 80)                  # this machine still resolves
