"""The whole-branch verification (audit-l, of 5a646f0, 2026-11-16): one regression per finding, each written to fail
first. H1 (the player's Datalinks help text), M1 (a failed help-text restore at "Also uninstall"), M2 / L1 (read-only
and other attributes of replaced files), L2 (edited files in the record), L3 ("Only update" forgotten too early). The
real-script chains for H1 and M1 are in test_install_e2e. Synthetic Thinker files stand in for the pinned release."""
from __future__ import annotations

import json
import os
import stat
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import patch_helptext as ph         # noqa: E402
import safe_fs                      # noqa: E402
import thinker_flow as tf           # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
from test_audit_k import patched_help, stock_help  # noqa: E402
from test_thinker_update import KNOWN, NEW, OLD, V54, _folder  # noqa: E402
from test_uninstall_thinker_packs import _installed_thinker  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows attributes and locks")
HIDDEN, READONLY = 0x2, 0x1
H = "smac_mod/helpx.txt"


def _record(game: Path) -> dict:
    return json.loads((game / tf.INSTALL_RECORD).read_text(encoding="utf-8"))


def _set(bdir: Path) -> dict:
    return {f.relative_to(bdir).as_posix(): f.read_bytes() for f in bdir.rglob("*") if f.is_file()}


def _update(tmp_path, files: dict):
    game = _folder(tmp_path / "game", {**OLD, **files})
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V54)
    prep = tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), types.SimpleNamespace(label=V54), p, "5.5", st.UP)
    return game, prep


# ---------------------------------------------------------------- H1: only our exact patch is taken back out
# On master's exact-undo model (user ruling 2026-11-17): no .longevity.bak is read or written; "ours" is a live file
# unpatch_bytes inverts, proved by patching the result back to the live bytes.

def edited_help() -> bytes:
    """Our patch with a word changed INSIDE our text: unpatch_bytes refuses it (EDITED)."""
    return patched_help().replace(b"Cloaking Device", b"Cloaking Devise")


ADDED = b"\r\n; PLAYER HELP EDIT\r\n"


@pytest.mark.parametrize("live,in_set", [(b"; PLAYER HELP EDIT - the player's own text\r\n#HELP\r\nhello\r\n", None),
                                         (edited_help(), None),
                                         (patched_help() + ADDED, stock_help() + ADDED)],
                         ids=["L2-replaced", "edited-our-text", "L1-added-to"])
def test_the_players_help_text_is_backed_up_as_it_is(tmp_path, live, in_set):
    """Not ours (replaced, or our text edited): the set keeps it byte for byte. Added to below ours: the exact undo
    takes only our text out, so the set gets the player's text with their addition."""
    game, prep = _update(tmp_path, {H: live})
    assert prep.plan.datalinks_ours == ([H] if in_set is not None else [])
    tf.commit(prep, route="thinker")
    tf.finish(prep)
    assert _set(prep.report.backup_dir)[H] == (live if in_set is None else in_set)
    # no backup written; an earlier version's leftover one (OLD has it) is never read or rewritten
    assert (game / "smac_mod" / ("helpx.txt" + tu.BAK)).read_bytes() == OLD["smac_mod/helpx.txt" + tu.BAK]
    assert not tu.rollback_dir(prep.report.backup_dir).joinpath("smac_mod", "helpx.txt" + tu.BAK).exists()


def test_our_exact_patch_still_backs_up_the_original(tmp_path):
    game, prep = _update(tmp_path, {H: patched_help()})
    assert prep.plan.datalinks_ours == [H]
    tf.commit(prep, route="thinker")
    assert _set(prep.report.backup_dir)[H] == stock_help()


@pytest.mark.parametrize("live,ours", [(patched_help(), True), (patched_help() + b"x", True),
                                       (edited_help(), False), (b"something else", False)],
                         ids=["exact", "added-to", "edited", "other"])
def test_is_our_patch_is_exact(tmp_path, live, ours):
    """"added-to": the inverse keeps the player's addition and patches back to the live bytes -- ours to undo."""
    p = tmp_path / "helpx.txt"
    p.write_bytes(live)
    assert ph.is_our_patch(p) is ours
    assert (ph.refused_status(p) == ph.EDITED) is (live == edited_help())


# ---------------------------------------------------------------- H1 / L5: the uninstall restores only our patch

def test_a_plain_uninstall_never_restores_over_the_players_help_text(tmp_path):
    """Our text edited: left as it is (held: master's verdict sentence names it); an earlier version's backup stays
    beside it, as the one manual way back (master's rule)."""
    g = tmp_path / "game"
    g.mkdir()
    (g / "helpx.txt").write_bytes(edited_help())
    (g / "helpx.txt.longevity.bak").write_bytes(stock_help())
    assert inst.restore_datalinks_text(g) == (0, ["helpx.txt"], [], [], [])
    assert (g / "helpx.txt").read_bytes() == edited_help()
    assert (g / "helpx.txt.longevity.bak").read_bytes() == stock_help()


def test_our_exact_patch_is_still_restored(tmp_path):
    """And a 1.0.0 player's leftover backup goes, as master does: never read, deleted once the file is undone."""
    g = tmp_path / "game"
    g.mkdir()
    (g / "helpx.txt").write_bytes(patched_help() + ADDED)
    (g / "helpx.txt.longevity.bak").write_bytes(b"an older stock text")
    assert inst.restore_datalinks_text(g) == (1, [], [], [], ["helpx.txt.longevity.bak"])
    assert (g / "helpx.txt").read_bytes() == stock_help() + ADDED and not (g / "helpx.txt.longevity.bak").exists()


def test_the_uninstall_has_no_help_row_any_more():
    """Master's verdict sentences name a help text left as it is; no "Left in place:" row besides (ruling 2026-11-17)."""
    import inspect
    src_ = inspect.getsource(inst.do_uninstall)
    assert "_HELP_KEPT" not in src_ and "help_kept_row" not in src_ and not hasattr(inst, "help_kept_row")
    assert "text_held" in src_ and "Datalinks text left as it is" in src_


# ---------------------------------------------------------------- M1: a failed restore never reads as "you changed"

class _Exclusive:
    """The file held open with no sharing at all (another program has it): every write and delete fails."""

    def __init__(self, p: Path):
        self.p = p

    def __enter__(self):
        import ctypes
        from ctypes import wintypes
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.CreateFileW.restype = wintypes.HANDLE
        self.k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.h = self.k32.CreateFileW(str(self.p), 0x80000000, 0, None, 3, 0x80, None)
        return self

    def __exit__(self, *a):
        self.k32.CloseHandle(self.h)
        return False


@windows
def test_a_failed_help_restore_keeps_the_marked_record_and_says_nothing_false(tmp_path, monkeypatch, capsys):
    """U3: our Thinker 5.5, whose smac_mod\\helpx.txt (the release's stock text) Longevity Vaccine patched; the
    uninstall's restore of it fails."""
    import hashlib
    files = {**NEW, H: stock_help(), "Changelog.md": b"what's new"}
    table = {rel.lower(): (rel, hashlib.sha256(data).hexdigest()) for rel, data in files.items()}
    pid = tf.compiled_pin().pin_id
    monkeypatch.setattr(tf, "_pin_files", lambda pin_id: dict(table) if pin_id == pid else {})
    game, _ = _installed_thinker(tmp_path)
    (game / "smac_mod" / "helpx.txt").write_bytes(stock_help())
    tf.write_install_record(game, pid, {rel: sha for rel, sha in table.values()
                                        if game.joinpath(*rel.split("/")).is_file() and not tf._never_removed(rel)})
    assert tf.read_install_record(game) is not None
    (game / "smac_mod" / "helpx.txt").write_bytes(patched_help())          # Longevity Vaccine's patch
    with _Exclusive(game / "smac_mod" / "helpx.txt"):                      # the restore fails (in use)
        restored, held, failed, unmarked, dropped = inst.restore_datalinks_text(game)
        assert failed == ["smac_mod" + chr(92) + "helpx.txt"]
        capsys.readouterr()
        removed, failed = tf.remove_thinker(game)
    assert failed >= 1 and "smac_mod/helpx.txt" not in tf.LAST_KEPT and tf.kept_lines() == []
    assert "removed Thinker Mod" not in capsys.readouterr().out
    assert _record(game).get("remove") is True
    # the re-run finishes it
    assert inst.restore_datalinks_text(game) == (1, [], [], [], [])
    assert tf.remove_thinker(game)[1] == 0 and not (game / "smac_mod" / "helpx.txt").exists()


@windows
def test_a_read_only_help_text_is_never_written_and_stops_the_uninstall_up_front(tmp_path):
    """Master's model for the help text (user ruling 2026-11-17): a read-only file is not written (the restore fails
    on it, said), and the up-front check refuses the whole uninstall for it before any change."""
    import types
    g = tmp_path / "game"
    g.mkdir()
    (g / "helpx.txt").write_bytes(patched_help())
    os.chmod(g / "helpx.txt", stat.S_IREAD)
    try:
        assert inst.restore_datalinks_text(g) == (0, [], ["helpx.txt"], [], [])
        assert (g / "helpx.txt").read_bytes() == patched_help()
        with pytest.raises(ix.InstallerError) as e:
            inst.do_uninstall(g, types.SimpleNamespace(no_prompt=True, force=False))
        assert e.value.title == "UNINSTALL NOT STARTED" and "helpx.txt: the file is read-only" in e.value.detail
    finally:
        os.chmod(g / "helpx.txt", stat.S_IREAD | stat.S_IWRITE)


# ---------------------------------------------------------------- M2 / L1: attributes through the swap

def _attr(p: Path, a: int) -> None:
    safe_fs.set_file_attrs(p, (safe_fs.file_attrs(p) or 0) | a)


@windows
def test_a_read_only_thinker_file_is_not_in_use(tmp_path):
    game, prep = _update(tmp_path, {})
    _attr(game / "thinker.ini", READONLY)
    assert tu.probe_locks(prep.plan, tries=1, wait=0) is None
    with open(game / "thinker.ini", "rb"):
        assert tu.probe_locks(prep.plan, tries=1, wait=0) == game / "thinker.ini"     # truly locked: still said


@windows
def test_the_swap_keeps_read_only_and_hidden_on_the_new_files_and_in_the_set(tmp_path):
    game, prep = _update(tmp_path, {})
    _attr(game / "thinker.ini", READONLY | HIDDEN)
    _attr(game / "modmenu.txt", HIDDEN)
    tf.commit(prep, route="thinker")
    tf.finish(prep)
    assert (game / "thinker.ini").read_bytes() != OLD["thinker.ini"]                   # replaced
    assert safe_fs.file_attrs(game / "thinker.ini") & (READONLY | HIDDEN) == READONLY | HIDDEN
    assert safe_fs.file_attrs(game / "modmenu.txt") & HIDDEN
    b = prep.report.backup_dir
    assert safe_fs.file_attrs(b / "thinker.ini") & (READONLY | HIDDEN) == READONLY | HIDDEN
    tf._drop_set(b)
    assert not b.exists()                                                              # a read-only set still goes


@windows
def test_undo_puts_the_attributes_back(tmp_path):
    game, prep = _update(tmp_path, {})
    _attr(game / "thinker.ini", READONLY | HIDDEN)
    tf.commit(prep, route="thinker")
    assert tu.undo(game) == tu.UNDONE
    assert (game / "thinker.ini").read_bytes() == OLD["thinker.ini"]
    assert safe_fs.file_attrs(game / "thinker.ini") & (READONLY | HIDDEN) == READONLY | HIDDEN


# ---------------------------------------------------------------- L2: an edited file stays in the record

def test_a_setup_keeps_an_edited_file_in_the_record(tmp_path, monkeypatch, capsys):
    game, _ = _installed_thinker(tmp_path)
    rec = _record(game)
    rec["remove"] = True
    (game / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")
    (game / "basenames" / "hive.txt").write_bytes(b"my hive names")                 # LC1: the player edited it
    tf.settle_install_record(game)
    assert "basenames/hive.txt" in _record(game)["files"]
    tf.remove_thinker(game)                                                        # a later "Also uninstall"
    assert any(line.startswith("basenames\\hive.txt") for line in tf.kept_lines())


# ---------------------------------------------------------------- L3: "Only update" waits for the run

def test_only_update_is_forgotten_only_when_the_run_succeeds(tmp_path, monkeypatch):
    from test_thinker_repair import _args
    from test_arrow_choices import _keys
    game, _ = _installed_thinker(tmp_path)
    (game / "thinker.exe").unlink()
    real = tf.compiled_meta()
    monkeypatch.setattr(tf, "compiled_meta", lambda: {**real, "dll": tu.sha256(game / "thinker.dll")})
    _keys(monkeypatch, "down", "enter")                                              # "Only update"
    tf.update_preflight(game, _args(), None, fresh=True, lv="1.0.0", persist_issued=False)
    assert tf.missing_release_files(game) == ["thinker.exe"]                        # a Ctrl-C now: nothing changed
    tf.settle_install_record(game)                                                  # the run succeeded
    assert tf.missing_release_files(game) == []


# ---------------------------------------------------------------- L4 / L5: the gate and the network sink

@pytest.mark.parametrize("require", [False, True], ids=["skip", "fail-under-the-gate"])
def test_a_refs_path_that_is_set_but_missing_goes_through_the_gate(tmp_path, monkeypatch, require):
    import test_install_e2e as e2e
    monkeypatch.setenv("LONGEVITY_REFS", str(tmp_path / "refs"))
    if require:
        monkeypatch.setenv("LONGEVITY_REQUIRE_E2E", "1")
    else:
        monkeypatch.delenv("LONGEVITY_REQUIRE_E2E", raising=False)
    got = None
    try:
        e2e._thinker_zip()
    except BaseException as e:          # noqa: B036 - pytest's outcomes are BaseExceptions; a skip must not escape
        got = e
    assert isinstance(got, pytest.fail.Exception if require else pytest.skip.Exception), repr(got)
    assert "\t" not in str(got)                                          # no literal tab from a non-raw "\t"


def test_runtime38_children_get_the_network_sink(monkeypatch):
    import test_runtime38 as r38
    seen = {}
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(r38.subprocess, "run", lambda argv, **kw: seen.update(kw["env"]) or None)
    r38._run("-c", "pass")
    assert seen.get("HTTP_PROXY") == "http://127.0.0.1:9"


def test_at_also_uninstall_an_edited_thinker_help_text_is_named_once_by_the_verdict(tmp_path, monkeypatch):
    """Our text in Thinker's smac_mod copy, edited: the restore leaves it (held -- master's verdict sentence names
    it), and the Thinker removal leaves it too without a second "a Thinker Mod file you changed" row (ruling
    2026-11-17)."""
    import hashlib
    files = {**NEW, H: stock_help(), "Changelog.md": b"what's new"}
    table = {rel.lower(): (rel, hashlib.sha256(data).hexdigest()) for rel, data in files.items()}
    pid = tf.compiled_pin().pin_id
    monkeypatch.setattr(tf, "_pin_files", lambda pin_id: dict(table) if pin_id == pid else {})
    game, _ = _installed_thinker(tmp_path)
    tf.write_install_record(game, pid, {rel: sha for rel, sha in table.values()
                                        if (game.joinpath(*rel.split("/")).is_file() or rel == H)
                                        and not tf._never_removed(rel)})
    mine = edited_help()
    (game / "smac_mod" / "helpx.txt").write_bytes(mine)
    held = inst.restore_datalinks_text(game)[1]
    tf.remove_thinker(game)
    assert (game / "smac_mod" / "helpx.txt").read_bytes() == mine
    assert held == ["smac_mod" + chr(92) + "helpx.txt"]
    assert tf.LAST_HELP_EDITED == [H] and H not in tf.LAST_KEPT and tf.kept_lines() == []
